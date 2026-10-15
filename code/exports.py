"""Write deterministic ZIP result packs with source evidence and query settings.

Author: Ding Qing
Date: 2026-10-15
"""

import csv
import io
import json
import zipfile


def _json(value, *, pretty=False):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      indent=2 if pretty else None,
                      separators=None if pretty else (",", ":"))


def _csv_bytes(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def write_result_pack(catalog, result, envelope):
    """Package a validated query result and its provenance."""
    metric = catalog["metric_registry"][result["query"]["metric_id"]]
    runs = [dict(run, query_id=result["query_id"]) for run in result["runs"]]
    manifest = {"versions": catalog["versions"], "data_manifest": catalog["manifest"],
                "metric_registry": catalog["metric_registry"], "query_id": result["query_id"]}
    browsing = result["query"]["operator"] == "none"
    mode = ("Browse mode: no threshold or continuity filtering. Empty intervals/evidence files do not mean no mineral was detected.\n"
            if browsing else "Filter mode: intervals/evidence contain threshold matches; profiles.csv retains all displayed source values in the requested window.\n")
    readme = (
        "HyLogger Interval Explorer - reproducible local result pack\n\n"
        f"Query ID: {result['query_id']}\n"
        f"Query: {_json(result['query'])}\n\n"
        f"{mode}"
        f"Metric: {metric['source_field']} ({metric['unit']}). {metric['definition']}\n"
        "The within-bin aggregation algorithm is not verified. The threshold is a numeric search condition, not a geological criterion.\n"
        "Windows are left-closed/right-open integer metres. Only complete one-metre records participate.\n"
        "N.A. means 'Not detected or below threshold' in these source files. N.A., invalid values, low values and absent records break runs.\n"
        "Zero is a valid value; absent data is never filled with zero. Coverage describes reported summary support, not confidence or scan quality.\n"
        "Run start_reason/end_reason describe the adjacent source record: window_continues means the condition continues beyond the query window, not a geological boundary.\n"
        "numeric_coverage_fraction uses the full requested window; numeric_fraction_of_summary_span and numeric_fraction_of_reported_rows have separate explicit denominators.\n"
        "source_gap_m is absent records inside the summary span. Outside that span, verified collar depth separates within_drill_without_summary_m and outside_drill_m; without verified depth it remains unknown_extent_m.\n"
        "source_na_m means not detected/below source threshold; unknown_missing_m means NULL/blank, and neither is zero. Summary/collar depth conflicts are flagged without truncating source data.\n"
        "Source data_record_index counts logical CSV data records after the header, starting at 1; it is not a physical text line number.\n"
        "Coordinates are labelled with their native CRS. No unrecorded CRS transformation or underground trajectory is implied.\n"
        "No matching run does not prove absence of minerals. Spectral proportions are not measured mass fractions, grade or geological truth.\n"
        "Restore query.json with exactly matching data, metric registry and engine versions. A version mismatch requires a new query.\n"
        "The pack contains derived records, not original HyLogger source datasets. Review applicable data permissions before external publication.\n"
    )
    files = {
        "query.json": _json(envelope, pretty=True).encode("utf-8"),
        "intervals.csv": _csv_bytes(runs, ["hole_id", "series_id", "from_m", "to_m", "length_m", "start_reason", "end_reason", "starts_at_query_boundary", "ends_at_query_boundary", "run_id", "query_id"]),
        "holes.csv": _csv_bytes([dict(hole, query_id=result["query_id"], summary_depth_conflict=_json(hole.get("summary_depth_conflict"))) for hole in result["holes"]], ["query_id", "hole_id", "longitude", "latitude", "crs", "located", "run_count", "total_length_m", "row_coverage_m", "numeric_coverage_m", "numeric_coverage_fraction", "numeric_coverage_denominator", "numeric_coverage_denominator_m", "query_window_m", "summary_span_window_m", "numeric_fraction_of_summary_span", "numeric_fraction_of_reported_rows", "source_na_m", "unknown_missing_m", "invalid_value_m", "source_gap_m", "outside_summary_span_m", "within_drill_without_summary_m", "outside_drill_m", "unknown_extent_m", "drilled_depth_verified", "summary_depth_conflict", "missing_m", "status", "has_rejected_series"]),
        "evidence.csv": _csv_bytes(result["evidence"], ["query_id", "run_id", "hole_id", "series_id", "metric_id", "from_m", "to_m", "value", "raw_token", "status", "source_id", "source_filename", "source_sha256", "data_record_index", "record_id"]),
        "manifest.json": _json(manifest, pretty=True).encode("utf-8"),
        "data_audit.json": _json(catalog["audit"], pretty=True).encode("utf-8"),
        "README.txt": readme.encode("utf-8"),
    }
    if "display_metric_ids" in result["query"] or browsing:
        profiles = [dict(row, unit=profile["metric"]["unit"], query_id=result["query_id"])
                    for profile in result["profiles"] for row in profile["records"]]
        files["profiles.csv"] = _csv_bytes(profiles, ["query_id", "hole_id", "series_id", "metric_id", "unit",
                                                      "from_m", "to_m", "value", "raw_token", "status", "source_id",
                                                      "source_field", "source_filename", "source_sha256", "data_record_index", "record_id"])
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for filename in sorted(files):
            info = zipfile.ZipInfo(filename, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, files[filename])
    return stream.getvalue()
