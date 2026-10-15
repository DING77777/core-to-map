"""Read candidate spectral changes for the exact summary currently in the library.

Author: Ding Qing
Date: 2026-10-15
"""

import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re

from metrics import METRIC_REGISTRY


ADAPTER_VERSION = "candidate-overlay/1.0"
MAX_PACKAGE_BYTES = 10 * 1024 * 1024
ANALYSIS_ROOT = Path(__file__).resolve().parent / "analysis"
DEFAULT_ANALYSIS_ROOT = ANALYSIS_ROOT / "packages"
DEFAULT_REVIEW_ROOT = ANALYSIS_ROOT / "results"
COMPOSITION_COLUMNS = tuple(key for key, metric in METRIC_REGISTRY.items()
                            if metric["kind"] == "mineral_group_proportion")
STABILITY_DESCRIPTION = (
    "Share of four nearby parameter settings retaining a candidate within 1 m; "
    "not a probability of being correct."
)
CAVEATS = [
    "Candidate spectral changes are algorithm suggestions, not confirmed geological contacts.",
    "Company-log code changes are a comparison reference, not ground truth.",
    "Depth is measured along the hole in metres, not elevation or true vertical depth.",
    "This overlay does not change the threshold query, its matching intervals or exports.",
    "N.A. is encoded as zero only inside this analysis; source and query values remain unchanged.",
]


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Expected a finite number")
    return value


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError("Missing or invalid source SHA-256")
    return value.lower()


def _range(item):
    start, end = _number(item["from_m"]), _number(item["to_m"])
    if start < 0 or end <= start:
        raise ValueError("Invalid analysis depth range")
    return {"from_m": start, "to_m": end}


def _base(hole_id):
    return {
        "hole_id": hole_id, "available": False, "status": "analysis_missing",
        "reason": "No candidate-change package with source provenance is available for this hole.",
        "adapter_version": ADAPTER_VERSION, "depth_reference": "along_hole_m",
        "method": {}, "source": {}, "coverage": {"usable_blocks": [], "candidate_count": 0},
        "candidates": [], "caveats": list(CAVEATS),
    }


def _unavailable(result, status, reason):
    result.update(available=False, status=status, reason=reason, candidates=[])
    return result


def _read(path):
    if path.stat().st_size > MAX_PACKAGE_BYTES:
        raise ValueError("Analysis package exceeds the input limit")
    content = path.read_bytes()
    document = json.loads(content)
    if not isinstance(document, dict):
        raise ValueError("Analysis package must be an object")
    return document, hashlib.sha256(content).hexdigest()


def _candidates(document, hole_id, package_hash, blocks, columns):
    points, seen = [], set()
    for candidate in document["candidates"]:
        depth = _number(candidate["depth_m"])
        above, below = _range(candidate["segment_above"]), _range(candidate["segment_below"])
        if (depth in seen or above["to_m"] != depth or below["from_m"] != depth
                or not any(block["from_m"] <= above["from_m"] < depth < below["to_m"] <= block["to_m"]
                           for block in blocks)):
            raise ValueError("Candidate crosses an excluded range or has inconsistent adjacent segments")
        seen.add(depth)
        stability = candidate.get("parameter_stability")
        if stability is not None and not 0 <= _number(stability) <= 1:
            raise ValueError("Invalid parameter stability")
        drivers = []
        for change in candidate["top_changes"]:
            name = change["metric"]
            before, after = _number(change["mean_above"]), _number(change["mean_below"])
            delta = _number(change["change"])
            if (name not in columns or not 0 <= before <= 1 or not 0 <= after <= 1
                    or not math.isclose(after - before, delta, abs_tol=1e-8)):
                raise ValueError("Invalid mineral-group change")
            drivers.append({"name": name, "before": before, "after": after,
                            "unit": "proportion", "delta": delta})
        points.append({
            "id": f"{hole_id}:{package_hash[:16]}:{depth:g}", "depth_m": depth,
            "segment_above": above, "segment_below": below, "drivers": drivers,
            "stability": {"value": stability, "label": "Parameter stability",
                          "description": STABILITY_DESCRIPTION},
        })
    return sorted(points, key=lambda point: point["depth_m"])


def _load_json_overlay(catalog, hole_id, analysis_root=None):
    """Return a separate display overlay; never modify catalog records or query state.

    The root contains <hole_id>/boundaries.json. A package with a mismatched
    input is disabled; no older result is substituted silently.
    """
    result = _base(hole_id)
    if not isinstance(hole_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", hole_id):
        return _unavailable(result, "source_missing", "Select a hole present in the library.")
    sources = [source for source in catalog.get("manifest", {}).get("sources", [])
               if source.get("hole_id") == hole_id]
    if not sources:
        return _unavailable(result, "source_missing", "This hole has no loaded summary source.")
    try:
        hashes = {_sha(source.get("sha256")) for source in sources}
    except ValueError:
        return _unavailable(result, "source_missing", "The current summary has no verifiable source hash.")
    if len(hashes) != 1:
        return _unavailable(result, "source_ambiguous", "Multiple source versions are loaded for this hole.")
    current_hash = hashes.pop()
    result["source"] = {"filename": sources[0].get("filename", ""), "current_sha256": current_hash}
    roots = [Path(analysis_root) if analysis_root is not None else DEFAULT_ANALYSIS_ROOT]
    packages = []
    for root in roots:
        path = root / hole_id / "boundaries.json"
        if not path.is_file():
            continue
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("Analysis must be a regular file inside its directory")
            document, package_hash = _read(path)
            run_id = document.get("provenance", {}).get("run_id", "")
            if not isinstance(run_id, str) or not re.fullmatch(r"\d{8}T\d{6}Z(?:-[A-Za-z0-9_-]+)?", run_id):
                raise ValueError("Missing analysis run identifier")
            packages.append((run_id, document, package_hash, path))
        except (OSError, ValueError, TypeError, AttributeError):
            return _unavailable(result, "invalid_analysis", "The analysis package is incomplete or cannot be validated.")
    if not packages:
        return result
    _, document, package_hash, path = max(packages, key=lambda package: package[0])
    try:
        if document["hole_id"] != hole_id:
            raise ValueError("Analysis hole does not match selected hole")
        provenance, method = document["provenance"], document["method"]
        expected_hash = _sha(provenance["summary_csv_sha256"][hole_id])
        version = provenance["method_version"]
        if not isinstance(version, str) or not version:
            raise ValueError("Missing method version")
        result["source"].update({"sha256": expected_hash, "run_id": provenance["run_id"],
                                 "package_sha256": package_hash, "package_filename": str(path),
                                 "version": version, "format": "boundaries_json"})
        if current_hash != expected_hash:
            return _unavailable(result, "source_mismatch", "This analysis used a different summary CSV; its candidate changes are hidden.")
        if method["feature_set"] != "composition36":
            return _unavailable(result, "unsupported_analysis", "This overlay supports the 36 mineral-group experiment only.")
        columns = method["preprocessing"]["columns"]
        if not isinstance(columns, list) or len(columns) != 36 or set(columns) != set(COMPOSITION_COLUMNS):
            raise ValueError("Invalid mineral-group feature set")
        if any(not isinstance(col, str) or not re.fullmatch(r"[A-Za-z0-9-]+_\(System_(SWIR|TIR)\)", col)
               or col.lower().startswith("invalid") for col in columns):
            raise ValueError("Unsupported mineral-group feature")
        blocks = sorted((_range(block) for block in document["usable_blocks"]), key=lambda block: block["from_m"])
        if any(first["to_m"] > second["from_m"] for first, second in zip(blocks, blocks[1:])):
            raise ValueError("Overlapping usable blocks")
        if blocks != _composition_blocks(catalog, hole_id):
            raise ValueError("Analysis coverage differs from the current mineral-group records")
        candidates = _candidates(document, hole_id, package_hash, blocks, columns)
        params = method["params"]
        parameters = {key: _number(params[key]) for key in ("beta", "min_size_m", "sigma2", "penalty")}
        if any(value < 0 for value in parameters.values()) or parameters["min_size_m"] <= 0:
            raise ValueError("Invalid method parameters")
        result.update({
            "available": True, "status": "available", "reason": "Analysis input matches the current summary CSV.",
            "method": {"name": method["segmentation"], "version": version,
                       "feature_set": "composition36", "parameters": parameters,
                       "missing_policy": method["preprocessing"]["missing_policy"],
                       "selected_on": method.get("selected_on", []), "role": document.get("role")},
            "coverage": {"usable_blocks": blocks, "candidate_count": len(candidates),
                         "excluded_ranges": document.get("excluded_ranges", "Outside usable blocks")},
            "candidates": candidates,
        })
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        return _unavailable(result, "invalid_analysis", "The analysis has inconsistent provenance, depths or mineral-group changes.")
    return result


def _csv(path):
    if path.stat().st_size > MAX_PACKAGE_BYTES:
        raise ValueError("Review sheet exceeds the input limit")
    content = path.read_bytes()
    table = csv.DictReader(io.StringIO(content.decode("utf-8-sig")), strict=True)
    if not table.fieldnames or len(set(table.fieldnames)) != len(table.fieldnames):
        raise ValueError("Missing or duplicate review-sheet columns")
    rows = list(table)
    if any(None in row or None in row.values() for row in rows):
        raise ValueError("Incomplete review-sheet record")
    return rows, hashlib.sha256(content).hexdigest()


def _composition_blocks(catalog, hole_id):
    records = sorted((row for row in catalog.get("records", []) if row["hole_id"] == hole_id),
                     key=lambda row: (row["from_m"], row["to_m"]))
    blocks, previous_end = [], None
    for row in records:
        interval = _range(row)
        start, end = interval["from_m"], interval["to_m"]
        if end != start + 1 or int(start) != start or (previous_end is not None and start < previous_end):
            raise ValueError("Current summary intervals are not distinct one-metre records")
        previous_end = end
        usable = True
        for column in COMPOSITION_COLUMNS:
            token = row.get("raw_row", {}).get(column)
            if token == "N.A.":
                continue
            try:
                value = float(token)
                usable = usable and math.isfinite(value) and 0 <= value <= 1
            except (TypeError, ValueError):
                usable = False
        if not usable:
            continue
        if blocks and blocks[-1]["to_m"] == start:
            blocks[-1]["to_m"] = end
        else:
            blocks.append(interval)
    if not blocks:
        raise ValueError("Current source has no verifiable mineral-group coverage")
    return blocks


def _rounded_drivers(description):
    drivers = []
    for part in description.split("; "):
        match = re.fullmatch(r"(.+) \((SWIR|TIR)\) ([↑↓]) (\d+\.\d{2})→(\d+\.\d{2})", part)
        if not match:
            return []
        name, region, arrow, a, b = match.groups()
        metric, before, after = f"{name}_(System_{region})", float(a), float(b)
        if metric not in COMPOSITION_COLUMNS or not 0 <= before <= 1 or not 0 <= after <= 1:
            raise ValueError("Invalid review-sheet mineral-group description")
        if (arrow == "↑" and after < before) or (arrow == "↓" and after > before):
            raise ValueError("Inconsistent review-sheet change direction")
        drivers.append({"name": metric, "before": before, "after": after,
                        "delta": round(after - before, 2), "unit": "proportion",
                        "rounded": True, "decimals": 2})
    return drivers


def _load_review_sheet(catalog, hole_id, result, root):
    manifest_path, sheet_path = root / "holes.csv", root / "sheets" / f"{hole_id}_segments.csv"
    if not manifest_path.is_file() or not sheet_path.is_file():
        return result
    try:
        if any(path.is_symlink() or not path.resolve().is_relative_to(root.resolve())
               for path in (manifest_path, sheet_path)):
            raise ValueError("Review files must remain inside their directory")
        manifest, manifest_hash = _csv(manifest_path)
        entries = [entry for entry in manifest if entry["hole_id"] == hole_id]
        if len(entries) != 1:
            raise ValueError("Missing or duplicated review-sheet source entry")
        entry = entries[0]
        expected_hash = _sha(entry["summary_csv_sha256"])
        if expected_hash != result["source"]["current_sha256"]:
            return _unavailable(result, "source_mismatch", "The review sheet used a different summary CSV; its candidate changes are hidden.")
        if not re.fullmatch(r"\d+", entry["candidates"]):
            raise ValueError("Invalid expected candidate count")
        rows, sheet_hash = _csv(sheet_path)
        if not rows:
            raise ValueError("Empty review sheet")
        blocks = _composition_blocks(catalog, hole_id)
        intervals, sheet_blocks, candidates = [], [], []
        for row in rows:
            if row["hole_id"] != hole_id:
                raise ValueError("Review-sheet hole identity differs")
            interval = _range({"from_m": float(row["from_m"]), "to_m": float(row["to_m"])})
            start, end = interval["from_m"], interval["to_m"]
            if int(start) != start or int(end) != end or float(row["length_m"]) != end - start:
                raise ValueError("Invalid review-sheet segment length")
            if intervals and intervals[-1]["to_m"] > start:
                raise ValueError("Review-sheet segments overlap or are out of order")
            if not any(block["from_m"] <= start < end <= block["to_m"] for block in blocks):
                raise ValueError("Review-sheet segment crosses excluded source depths")
            block_start = not intervals or intervals[-1]["to_m"] != start
            description = row["change_at_top"]
            if block_start:
                if description != "start of a continuous block" or row["parameter_stability_at_top"]:
                    raise ValueError("Review-sheet block start is inconsistent")
                sheet_blocks.append(dict(interval))
            else:
                if not description or description == "start of a continuous block":
                    raise ValueError("Missing candidate at a segment join")
                stability = _number(float(row["parameter_stability_at_top"]))
                if not 0 <= stability <= 1:
                    raise ValueError("Invalid parameter stability")
                candidates.append({
                    "id": f"{hole_id}:{sheet_hash[:16]}:{start:g}", "depth_m": start,
                    "segment_above": dict(intervals[-1]), "segment_below": dict(interval),
                    "description": description, "drivers": _rounded_drivers(description),
                    "stability": {"value": stability, "label": "Parameter stability",
                                  "description": STABILITY_DESCRIPTION},
                })
                sheet_blocks[-1]["to_m"] = end
            intervals.append(interval)
        if sheet_blocks != blocks or len(candidates) != int(entry["candidates"]):
            raise ValueError("Review-sheet coverage or candidate count is incomplete")
        result.update({
            "available": True, "status": "available", "reason": "Review-sheet source hash, depth coverage and candidate count match the current summary.",
            "method": {"name": "Precomputed candidate changes in 36 mineral-group proportions",
                       "version": None, "feature_set": "composition36", "parameters": {},
                       "role": "development" if entry.get("selection") == "development" else "test"},
            "source": {"filename": result["source"].get("filename", ""), "sha256": expected_hash,
                       "current_sha256": expected_hash, "format": "release_review_sheet",
                       "run_id": None, "version": None, "package_filename": str(sheet_path),
                       "package_sha256": sheet_hash, "manifest_sha256": manifest_hash,
                       "manifest_filename": str(manifest_path),
                       "snapshot_id": f"review-sheet:{manifest_hash[:16]}:{sheet_hash[:16]}"},
            "coverage": {"usable_blocks": blocks, "candidate_count": len(candidates)},
            "candidates": candidates,
        })
        result["caveats"].append("Review-sheet mineral means are rounded to two decimal places. The sheet does not provide a run ID or per-run parameters.")
    except (OSError, UnicodeError, csv.Error, KeyError, TypeError, ValueError, OverflowError):
        return _unavailable(result, "invalid_analysis", "The review sheet is incomplete or its source, depths and candidate count cannot be validated.")
    return result


def load_hole_overlay(catalog, hole_id, analysis_root=None, review_root=None):
    """Load a verified JSON package, otherwise a separately identified review sheet."""
    result = _load_json_overlay(catalog, hole_id, analysis_root)
    if result["available"] or result["status"] in {"source_missing", "source_ambiguous"}:
        return result
    if review_root is None:
        review_root = (DEFAULT_REVIEW_ROOT if analysis_root is None or Path(analysis_root).resolve() == DEFAULT_ANALYSIS_ROOT.resolve()
                       else Path(analysis_root) / "results")
    return _load_review_sheet(catalog, hole_id, result, Path(review_root))
