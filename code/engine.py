"""Validate intervals, search continuous runs and export reproducible results.

Author: Ding Qing
Date: 2026-10-15
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
from pathlib import Path
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import statistics

from datasets import DEFAULT_HOLES, DEMO_HOLES, LOADED_HOLES, SOURCES, GROUPS as HOLE_GROUPS
from metrics import METRIC_ID, METRIC_REGISTRY, canonical_metric
from summaries import load_summary
from exports import write_result_pack


SCHEMA_VERSION = "1.0"
ENGINE_VERSION = "hylogger-v2-2.2"
MAX_RESTORE_BYTES = 2 * 1024 * 1024
DEFAULT_QUERY = {
    "hole_ids": list(DEMO_HOLES), "metric_id": METRIC_ID,
    "depth_from_m": 96, "depth_to_m": 175, "threshold": 2200,
    "min_run_m": 3, "operator": "gte",
}


def _json(value, *, pretty=False):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      indent=2 if pretty else None,
                      separators=None if pretty else (",", ":"))


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _integer(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be an integer")
    try:
        finite = math.isfinite(value)
    except (OverflowError, TypeError):
        finite = False
    if not finite or int(value) != value:
        raise ValueError(f"{label} must be a finite integer")
    return int(value)


def _number(value, label):
    try:
        finite = math.isfinite(value)
    except (OverflowError, TypeError):
        finite = False
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not finite:
        raise ValueError(f"{label} must be a finite number")
    return int(value) if int(value) == value else value



def normalize_records(records: list[dict]) -> dict:
    """Normalize integer one-metre intervals; reject conflicting series entirely."""
    issues = []
    groups = defaultdict(list)
    identities = defaultdict(list)
    rejected = set()
    for position, original in enumerate(records, 1):
        record = copy.deepcopy(original)
        hole, series = record.get("hole_id"), record.get("series_id")
        rid = record.get("record_id")
        if not all(isinstance(value, str) and value for value in (hole, series, rid)):
            raise ValueError("Each record needs nonempty hole_id, series_id and record_id")
        metric = canonical_metric(record.setdefault("metric_id", METRIC_ID))
        record["metric_id"] = metric
        if not isinstance(metric, str) or not metric:
            raise ValueError("metric_id must be a nonempty string")
        key = (hole, series, metric)
        identities[rid].append(key)
        record.setdefault("source_id", "synthetic")
        record.setdefault("source_filename", record["source_id"])
        record.setdefault("data_record_index", position)
        issue_base = {"hole_id": hole, "series_id": series, "metric_id": metric, "record_id": rid}
        try:
            if isinstance(record["from_m"], bool) or isinstance(record["to_m"], bool):
                raise ValueError("boolean boundary")
            start, end = Decimal(str(record["from_m"])), Decimal(str(record["to_m"]))
            if not start.is_finite() or not end.is_finite():
                raise ValueError("non-finite boundary")
            if abs(start - round(start)) > Decimal("0.000001") or abs(end - round(end)) > Decimal("0.000001"):
                raise ValueError("non-integer boundary")
            start, end = round(start), round(end)
            if start < 0 or end != start + 1:
                raise ValueError("expected a nonnegative one-metre interval")
            record.update(from_m=start, to_m=end)
        except (KeyError, TypeError, ValueError, OverflowError, InvalidOperation) as error:
            issues.append(dict(issue_base, reason="invalid_interval", detail=str(error)))
            continue
        token = record.get("raw_token", "")
        if not isinstance(token, str):
            token = str(token)
        record.update(raw_token=token, value=None)
        if metric not in METRIC_REGISTRY:
            record["status"] = "unsupported_metric"
        elif token.strip() == "N.A.":
            record["status"] = "source_na"
        elif token.strip() in {"NULL", ""}:
            record["status"] = "unknown_missing"
        else:
            try:
                value = float(token.strip())
                if not math.isfinite(value) or value < METRIC_REGISTRY[metric]["minimum_valid_value"]:
                    record["status"] = "invalid_value"
                else:
                    record.update(value=value, status="valid_numeric")
            except (TypeError, ValueError, OverflowError):
                record["status"] = "parse_error"
        if record["status"] in {"invalid_value", "parse_error", "unsupported_metric", "unknown_missing"}:
            issues.append(dict(issue_base, reason=record["status"]))
        groups[key].append(record)
    for rid, keys in identities.items():
        if len(keys) > 1:
            rejected.update(keys)
            issues.append({"record_id": rid, "reason": "duplicate_record_id"})
    for key, rows in groups.items():
        rows.sort(key=lambda row: (row["from_m"], row["to_m"], row["record_id"]))
        if any(first["to_m"] > second["from_m"] for first, second in zip(rows, rows[1:])):
            rejected.add(key)
            issues.append({"hole_id": key[0], "series_id": key[1], "metric_id": key[2], "reason": "overlap_or_duplicate_interval"})
    accepted = [record for key in sorted(groups) if key not in rejected for record in groups[key]]
    return {
        "records": accepted, "issues": issues,
        "rejected_series": [{"hole_id": h, "series_id": s, "metric_id": m} for h, s, m in sorted(rejected)],
        "accepted_records": len(accepted), "rejected_records": len(records) - len(accepted),
    }


def _coordinates(hole_id, coordinates):
    supplied = copy.deepcopy((coordinates or {}).get(hole_id, {}))
    # Only portable coordinate provenance is exposed in exported files.
    allowed = {"longitude", "latitude", "crs", "source_id", "source_filename", "source_table",
               "source_sha256", "source_url", "collar_id", "coordinate_note", "note",
               "transform", "accuracy", "verified", "coordinate_source", "wamex_collar_id",
               "source_key", "index_table", "index_key", "source_package_url", "source_hashes",
               "join_field", "crs_authority_code", "audit", "max_depth_m", "report_number"}
    item = {key: value for key, value in supplied.items() if key in allowed}
    item.update(hole_id=hole_id, located=False)
    longitude, latitude = item.get("longitude"), item.get("latitude")
    if longitude is not None or latitude is not None:
        longitude = _number(longitude, f"{hole_id} longitude")
        latitude = _number(latitude, f"{hole_id} latitude")
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90 or not item.get("crs"):
            raise ValueError(f"Invalid or unlabelled geographic coordinates for {hole_id}")
        item.update(longitude=longitude, latitude=latitude, located=item.get("verified", True) is True)
    else:
        item.update(longitude=None, latitude=None)
        item.setdefault("crs", None)
    _json(item)
    return item


def catalog_from_records(records, sources=None, coordinate_catalog=None, *, hole_ids=None):
    """Build a catalog, also available for isolated synthetic engine tests."""
    normal = normalize_records(records)
    holes = sorted(set(hole_ids if hole_ids is not None else (record["hole_id"] for record in records)))
    coordinates = [_coordinates(hole, coordinate_catalog) for hole in holes]
    registry = copy.deepcopy(METRIC_REGISTRY)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "sources": sorted(copy.deepcopy(sources or []), key=lambda source: source.get("source_id", "")),
        "coordinates": coordinates,
        "record_content_hash": _hash([
            {field: str(record.get(field, "")) for field in
             ("hole_id", "series_id", "metric_id", "record_id", "from_m", "to_m", "raw_token", "source_id", "data_record_index")}
            for record in sorted(records, key=lambda row: (row["hole_id"], row["series_id"], row["record_id"]))
        ]),
        "series_policy": "One declared source processing sequence per hole; no automatic cross-file or cross-series joins.",
        "metric_ids": sorted(registry),
    }
    versions = {"schema_version": SCHEMA_VERSION, "engine_version": ENGINE_VERSION,
                "data_manifest_hash": _hash(manifest), "metric_registry_hash": _hash(registry)}
    audit = {key: copy.deepcopy(value) for key, value in normal.items() if key != "records"}
    audit.update(metric_id=METRIC_ID, unit="nm")
    audit["coverage"] = [{"hole_id": hole, "accepted_records": sum(row["hole_id"] == hole for row in normal["records"]),
                          "minimum_from_m": min((row["from_m"] for row in normal["records"] if row["hole_id"] == hole), default=None),
                          "maximum_to_m": max((row["to_m"] for row in normal["records"] if row["hole_id"] == hole), default=None)} for hole in holes]
    for hole in coordinates:
        present = [row for row in normal["records"] if row["hole_id"] == hole["hole_id"]]
        start = min((row["from_m"] for row in present), default=None)
        end = max((row["to_m"] for row in present), default=None)
        covered = _union_length(present)
        hole.update(record_count=len(present), depth_from_m=start, depth_to_m=end,
                    covered_record_length_m=covered, extent_span_m=end - start if present else 0)
        hole["group_id"] = next((group["id"] for group in HOLE_GROUPS if hole["hole_id"] in group["hole_ids"]), None)
        max_depth = hole.get("max_depth_m")
        if isinstance(max_depth, (float, int)) and max_depth > 0:
            hole["covered_fraction_of_drilled_depth"] = covered / max_depth
            if end is not None and end > max_depth:
                audit["issues"].append({"hole_id": hole["hole_id"], "reason": "summary_exceeds_collar_depth",
                                        "summary_to_m": end, "collar_max_depth_m": max_depth})
    versions["data_manifest_hash"] = _hash(manifest)
    return {"records": normal["records"], "holes": coordinates, "manifest": manifest,
            "versions": versions, "audit": audit, "metric_registry": registry}


def load_catalog(data_root: Path, coordinate_catalog: dict | None = None, *,
                 hole_ids=None, verify_sources=True) -> dict:
    holes = tuple(LOADED_HOLES if hole_ids is None else hole_ids)
    if set(holes) - SOURCES.keys():
        raise ValueError("Only declared source holes can be loaded")
    records, sources, issues = [], [], []
    compatibility = None
    for hole in holes:
        relative_path, expected_hash = SOURCES[hole]
        path = Path(data_root) / relative_path
        try:
            bundle = load_summary(path, hole)
            if verify_sources and bundle["source"]["sha256"] != expected_hash:
                raise ValueError("Source fingerprint differs from the reviewed CSV")
        except (OSError, UnicodeError, csv.Error, ValueError) as error:
            detail = str(error) if not isinstance(error, OSError) else type(error).__name__
            issues.append({"hole_id": hole, "source_filename": path.name, "reason": "source_rejected", "detail": detail})
            continue
        metadata = bundle["source"]["metadata"]
        keys = ("SWIR_algorithm", "TIR_algorithm", "Bin_min_threshold", "Scalar_min_depth",
                "****W", "****D", "N.A.", "System", "Invalid")
        signature = {key: " ".join(metadata[key].split()) if key in metadata else None for key in keys}
        if compatibility is not None and signature != compatibility:
            issues.append({"hole_id": hole, "source_filename": path.name,
                           "reason": "incompatible_source_settings",
                           "detail": "Summary definitions or processing settings differ."})
            continue
        compatibility = signature
        bundle["source"]["compatibility_settings"] = signature
        bundle["source"]["fingerprint_verified"] = verify_sources
        records.extend(bundle["records"])
        sources.append(bundle["source"])
    if not sources:
        raise ValueError("No supported summary input was loaded: " + "; ".join(f"{item['hole_id']}: {item['detail']}" for item in issues))
    catalog = catalog_from_records(records, sources, coordinate_catalog, hole_ids=[source["hole_id"] for source in sources])
    catalog["audit"]["issues"].extend(issues)
    catalog["audit"]["source_issues"] = issues
    available = set().union(*(set(source["fields"]) for source in sources))
    catalog["metric_registry"] = {key: value for key, value in catalog["metric_registry"].items() if key in available}
    catalog["manifest"]["metric_ids"] = sorted(catalog["metric_registry"])
    catalog["versions"]["data_manifest_hash"] = _hash(catalog["manifest"])
    catalog["versions"]["metric_registry_hash"] = _hash(catalog["metric_registry"])
    loaded = {source["hole_id"] for source in sources}
    catalog["groups"] = [dict(group, hole_ids=[h for h in group["hole_ids"] if h in loaded]) for group in HOLE_GROUPS]
    catalog["groups"] = [group for group in catalog["groups"] if group["hole_ids"]]
    catalog["default_query"] = copy.deepcopy(DEFAULT_QUERY)
    if not set(DEMO_HOLES).issubset(loaded):
        catalog["default_query"].update(hole_ids=sorted(loaded), depth_from_m=0,
                                        depth_to_m=max(row["to_m"] for row in catalog["records"]))
    return catalog


def _metric_records(catalog, metric_id, chosen):
    records = []
    for original in catalog["records"]:
        if original["hole_id"] not in chosen:
            continue
        if original["metric_id"] == metric_id:
            records.append(original)
        else:
            source_field = next((key for key, value in original.get("field_aliases", {}).items()
                                 if value == metric_id), metric_id)
            if source_field not in original.get("raw_row", {}):
                continue
            record = dict(original, metric_id=metric_id, raw_token=original["raw_row"][source_field],
                          source_field=source_field)
            record["record_id"] = _hash([original["source_sha256"], original["data_record_index"], metric_id])
            records.append(record)
    return records


def canonicalize_query(catalog, spec):
    required = {"hole_ids", "metric_id", "depth_from_m", "depth_to_m", "threshold", "min_run_m", "operator"}
    if not isinstance(spec, dict) or not required <= set(spec) or set(spec) - required - {"display_metric_ids"}:
        raise ValueError("Query requires: " + ", ".join(sorted(required)) + "; display_metric_ids is optional")
    metric_id = canonical_metric(spec["metric_id"])
    if not isinstance(metric_id, str) or metric_id not in catalog.get("metric_registry", METRIC_REGISTRY):
        raise ValueError("Unsupported metric_id")
    if spec["operator"] not in {"gte", "none"}:
        raise ValueError("operator must be gte or none")
    requested = spec["hole_ids"]
    if not isinstance(requested, list) or not requested or not all(isinstance(h, str) and h for h in requested):
        raise ValueError("hole_ids must be a nonempty list of hole names")
    holes = sorted(set(requested))
    known = {hole["hole_id"] for hole in catalog["holes"]}
    if set(holes) - known:
        raise ValueError("Unknown hole_ids: " + ", ".join(sorted(set(holes) - known)))
    start, end = _integer(spec["depth_from_m"], "depth_from_m"), _integer(spec["depth_to_m"], "depth_to_m")
    minimum = None if spec["min_run_m"] is None else _integer(spec["min_run_m"], "min_run_m")
    if start < 0 or end <= start:
        raise ValueError("Depth window must satisfy 0 <= from < to")
    if minimum is not None and minimum <= 0:
        raise ValueError("min_run_m must be positive")
    if spec["operator"] == "none":
        if spec["threshold"] is not None or minimum is not None:
            raise ValueError("Browse mode requires null threshold and min_run_m")
        threshold = None
    else:
        threshold = _number(spec["threshold"], "threshold")
    canonical = {"hole_ids": holes, "metric_id": metric_id, "depth_from_m": start,
                 "depth_to_m": end, "threshold": threshold,
                 "min_run_m": minimum, "operator": spec["operator"]}
    if "display_metric_ids" in spec:
        displayed = spec["display_metric_ids"]
        if not isinstance(displayed, list) or not 1 <= len(displayed) <= 6 or not all(isinstance(item, str) for item in displayed):
            raise ValueError("display_metric_ids must contain one to six metric names")
        displayed = [canonical_metric(item) for item in displayed]
        if len(set(displayed)) != len(displayed) or any(item not in catalog["metric_registry"] for item in displayed):
            raise ValueError("display_metric_ids must contain distinct supported metrics")
        canonical["display_metric_ids"] = displayed
    return canonical


def _union_length(rows):
    end, length = None, 0
    for row in sorted(rows, key=lambda r: (r["from_m"], r["to_m"])):
        start, stop = row["from_m"], row["to_m"]
        length += max(0, stop - (start if end is None else max(start, end)))
        end = stop if end is None else max(end, stop)
    return length


def _run_boundary_reason(boundary, rows, threshold, *, before):
    adjacent = next((row for row in rows if
                     (row["to_m"] == boundary if before else row["from_m"] == boundary)), None)
    if adjacent is not None:
        if adjacent["status"] == "valid_numeric":
            return "window_continues" if adjacent["value"] >= threshold else "nonmatch"
        return "invalid_value" if adjacent["status"] == "parse_error" else adjacent["status"]
    edge = min(row["from_m"] for row in rows) if before else max(row["to_m"] for row in rows)
    return ("source_start" if before else "source_end") if boundary == edge else "missing"


def _coverage_context(hole, present, start, end):
    span_start, span_end = hole.get("depth_from_m"), hole.get("depth_to_m")
    if span_start is None or span_end is None:
        left, right = start, start
    else:
        left, right = max(start, span_start), min(end, span_end)
        right = max(left, right)
    span = max(0, right - left)
    outside = end - start - span
    outside_ranges = ([(start, end)] if not span else
                      [(start, left), (right, end)])
    max_depth = hole.get("max_depth_m")
    verified = hole.get("verified", hole.get("located", False)) is True
    known_depth = verified and isinstance(max_depth, (int, float)) and not isinstance(max_depth, bool) and max_depth > 0
    outside_drill = sum(max(0, b - max(a, max_depth)) for a, b in outside_ranges) if known_depth else 0
    covered = _union_length(present)
    numeric = _union_length([row for row in present if row["status"] == "valid_numeric"])
    conflict = None
    if known_depth and span_end is not None and span_end > max_depth:
        conflict = {"summary_to_m": span_end, "collar_max_depth_m": max_depth,
                    "excess_m": span_end - max_depth}
    return {
        "query_window_m": end - start,
        "summary_span_window_m": span,
        "source_gap_m": max(0, span - covered),
        "unknown_missing_m": _union_length([row for row in present if row["status"] == "unknown_missing"]),
        "outside_summary_span_m": outside,
        "within_drill_without_summary_m": outside - outside_drill if known_depth else 0,
        "outside_drill_m": outside_drill,
        "unknown_extent_m": 0 if known_depth else outside,
        "drilled_depth_verified": known_depth,
        "numeric_coverage_denominator_m": end - start,
        "numeric_coverage_denominator": "requested_depth_window",
        "numeric_fraction_of_summary_span": numeric / span if span else None,
        "numeric_fraction_of_reported_rows": numeric / covered if covered else None,
        "summary_depth_conflict": conflict,
    }


def run_query(catalog, spec):
    canonical = canonicalize_query(catalog, spec)
    versions = copy.deepcopy(catalog["versions"])
    query_id = _hash({"query": canonical, "versions": versions})
    chosen = set(canonical["hole_ids"])
    metric = catalog["metric_registry"][canonical["metric_id"]]
    normal = normalize_records(_metric_records(catalog, canonical["metric_id"], chosen))
    rows = [row for row in normal["records"] if row["metric_id"] == canonical["metric_id"]]
    start, end = canonical["depth_from_m"], canonical["depth_to_m"]
    active = [row for row in rows if start <= row["from_m"] and row["to_m"] <= end]
    groups = defaultdict(list)
    for row in active:
        groups[(row["hole_id"], row["series_id"])].append(row)
    runs = []

    def flush(sequence):
        if not sequence:
            return
        length = sequence[-1]["to_m"] - sequence[0]["from_m"]
        if canonical["min_run_m"] is not None and length < canonical["min_run_m"]:
            return
        ids = [row["record_id"] for row in sequence]
        runs.append({"hole_id": sequence[0]["hole_id"], "series_id": sequence[0]["series_id"],
                     "from_m": sequence[0]["from_m"], "to_m": sequence[-1]["to_m"], "length_m": length,
                     "run_id": _hash([query_id, ids]), "record_ids": ids})

    for key in sorted(groups):
        sequence = []
        for row in sorted(groups[key], key=lambda r: r["from_m"]):
            matches = (canonical["operator"] == "gte" and row["status"] == "valid_numeric"
                       and row["value"] >= canonical["threshold"])
            if sequence and (not matches or row["from_m"] != sequence[-1]["to_m"]):
                flush(sequence)
                sequence = []
            if matches:
                sequence.append(row)
        flush(sequence)
    runs.sort(key=lambda r: (r["hole_id"], r["from_m"], r["to_m"], r["series_id"]))
    complete_groups = defaultdict(list)
    for row in rows:
        complete_groups[(row["hole_id"], row["series_id"])].append(row)
    for run in runs:
        complete = complete_groups[(run["hole_id"], run["series_id"])]
        run.update(
            start_reason=_run_boundary_reason(run["from_m"], complete, canonical["threshold"], before=True),
            end_reason=_run_boundary_reason(run["to_m"], complete, canonical["threshold"], before=False),
            starts_at_query_boundary=run["from_m"] == start,
            ends_at_query_boundary=run["to_m"] == end,
        )
    rejected = catalog.get("audit", {}).get("rejected_series", []) + normal["rejected_series"]
    holes = []
    by_hole = {hole["hole_id"]: hole for hole in catalog["holes"]}
    for hole in canonical["hole_ids"]:
        present = [row for row in active if row["hole_id"] == hole]
        numeric = [row for row in present if row["status"] == "valid_numeric"]
        matches = [run for run in runs if run["hole_id"] == hole]
        covered, available = _union_length(present), _union_length(numeric)
        source_na = _union_length([row for row in present if row["status"] == "source_na"])
        context = _coverage_context(by_hole[hole], present, start, end)
        has_rejected = any(item["hole_id"] == hole for item in rejected)
        if matches:
            status = "Match found"
        elif not available and covered and source_na == covered:
            status = ("Not detected / below source threshold" if metric["kind"] == "mineral_group_proportion"
                      else "No numeric values / source N.A.")
        elif not available and source_na:
            status = "No numeric values / mixed source states"
        elif not available:
            status = "No usable values"
        elif canonical["operator"] == "none":
            status = "Viewing / complete numeric coverage" if available == end - start else "Viewing / incomplete numeric coverage"
        elif available == end - start:
            status = "No match / complete numeric coverage"
        else:
            status = "No match / incomplete numeric coverage"
        holes.append(dict(copy.deepcopy(by_hole[hole]),
                          row_coverage_m=covered, numeric_coverage_m=available,
                          median_value=statistics.median(row["value"] for row in numeric) if numeric else None,
                          minimum_value=min((row["value"] for row in numeric), default=None),
                          maximum_value=max((row["value"] for row in numeric), default=None),
                          numeric_coverage_fraction=available / (end - start),
                          source_na_m=source_na, source_na_meaning="Not detected or below threshold",
                          invalid_value_m=_union_length([row for row in present if row["status"] in {"invalid_value", "parse_error"}]),
                          missing_m=end - start - covered, status=status, has_rejected_series=has_rejected,
                          run_count=len(matches), total_length_m=sum(run["length_m"] for run in matches),
                          **context))
    by_id = {row["record_id"]: row for row in rows}
    evidence = []
    minimum_note = (f"minimum {canonical['min_run_m']} m" if canonical["min_run_m"] is not None
                    else "no minimum length")
    for run in runs:
        for rid in run["record_ids"]:
            evidence.append(dict(copy.deepcopy(by_id[rid]), run_id=run["run_id"], query_id=query_id,
                                 match_reason=f"Reported value >= {canonical['threshold']} {metric['unit']} in a continuous {run['length_m']} m interval ({minimum_note})."))
    issues = copy.deepcopy(catalog.get("audit", {}).get("issues", []))
    issues.extend(issue for issue in normal["issues"] if issue not in issues)
    profiles = []
    for displayed in canonical.get("display_metric_ids", [canonical["metric_id"]]):
        if displayed == canonical["metric_id"]:
            profile_rows = active
        else:
            selected = _metric_records(catalog, displayed, chosen)
            compact = [{key: value for key, value in row.items() if key != "raw_row"} for row in selected]
            profile_normal = normalize_records(compact)
            profile_rows = [row for row in profile_normal["records"] if start <= row["from_m"] and row["to_m"] <= end]
            issues.extend(issue for issue in profile_normal["issues"] if issue not in issues)
        profiles.append({"metric": copy.deepcopy(catalog["metric_registry"][displayed]), "records": profile_rows})
    return {"query_id": query_id, "query": canonical, "metric": copy.deepcopy(metric), "versions": versions, "holes": holes,
            "runs": runs, "records": rows, "evidence": evidence, "profiles": profiles,
            "run_count": len(runs), "total_length_m": sum(run["length_m"] for run in runs),
            "audit": {"issues": issues, "rejected_series": rejected}}


def get_evidence(result, run_id):
    if not any(run["run_id"] == run_id for run in result["runs"]):
        raise ValueError("Unknown run_id")
    return [copy.deepcopy(row) for row in result["evidence"] if row["run_id"] == run_id]


def query_envelope(result):
    return {"schema_version": SCHEMA_VERSION, "query_id": result["query_id"],
            "query": copy.deepcopy(result["query"]), "versions": copy.deepcopy(result["versions"])}


def restore_query(catalog, envelope):
    if isinstance(envelope, bytes):
        if len(envelope) > MAX_RESTORE_BYTES:
            raise ValueError("Query file exceeds 2 MiB")
        envelope = envelope.decode("utf-8-sig")
    if isinstance(envelope, str):
        if len(envelope.encode("utf-8")) > MAX_RESTORE_BYTES:
            raise ValueError("Query file exceeds 2 MiB")
        def reject_constant(value):
            raise ValueError(f"Non-finite JSON number: {value}")
        def unique_keys(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"Duplicate JSON key: {key}")
                result[key] = value
            return result
        envelope = json.loads(envelope, parse_constant=reject_constant, object_pairs_hook=unique_keys)
    if not isinstance(envelope, dict) or set(envelope) != {"schema_version", "query_id", "query", "versions"}:
        raise ValueError("Invalid query envelope fields")
    if len(_json(envelope).encode("utf-8")) > MAX_RESTORE_BYTES:
        raise ValueError("Query file exceeds 2 MiB")
    if envelope["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Incompatible query schema_version")
    if envelope["versions"] != catalog["versions"]:
        differing = sorted(key for key in set(catalog["versions"]) | set(envelope["versions"] if isinstance(envelope["versions"], dict) else {})
                           if not isinstance(envelope["versions"], dict) or envelope["versions"].get(key) != catalog["versions"].get(key))
        raise ValueError("Version mismatch; create a new query with current data: " + ", ".join(differing))
    result = run_query(catalog, envelope["query"])
    if envelope["query_id"] != result["query_id"]:
        raise ValueError("Query identity mismatch; parameters or provenance were changed")
    result["reproduced"] = True
    return result


def make_export(catalog, result):
    result = restore_query(catalog, query_envelope(result))
    return write_result_pack(catalog, result, query_envelope(result))
