"""Build the standard hole package (see schema/HOLE_PACKAGE_SPEC.md).

Output per hole, in packages/<hole_id>/:
  hole.json    metadata, provenance, coverage, metric registry, occurrence index, analyses
  metres.json  column-oriented 1 m values for charts (number | "NA" | "BLANK" | "INVALID")
  metres.csv   the same rows with the original source tokens (for spreadsheets / GIS joins)

Author: Ding Qing
Date: 2026-10-15
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .intervals import find_runs

SCHEMA_VERSION = "hylogger-hole-package/0.2"
PIPELINE_VERSION = "hylogger-pipeline/0.2"
DISPLAY_INTERVAL_CONVENTION = "[from_m, to_m) for 1 m summary records (query and display)"
STATUS_CODE = {"source_na": "NA", "blank": "BLANK", "invalid": "INVALID"}
OCCURRENCE_THRESHOLD = Decimal("0.2")


def _num(x):
    if isinstance(x, Decimal):
        return float(x)
    return x


def jsonable(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    return obj


def _metric_stats(hole, col):
    vals = [r["values"][col] for r in hole["records"] if r["status"][col] == "ok"]
    st = {}
    for r in hole["records"]:
        st[r["status"][col]] = st.get(r["status"][col], 0) + 1
    out = {"n_numeric": st.get("ok", 0), "n_source_na": st.get("source_na", 0),
           "n_blank": st.get("blank", 0), "n_invalid": st.get("invalid", 0)}
    if vals:
        s = sorted(vals)
        out.update(min=s[0], max=s[-1], median=s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2)
    return out


def occurrence_index(hole, threshold=OCCURRENCE_THRESHOLD):
    """Per mineral-group column: how much and where it reaches the display threshold.

    Used by the state-wide filter ("which holes show >= 0.2 White-Mica over >= N m").
    The 0.2 threshold is a display default, not a geological cut-off.
    """
    if not hole["records"]:
        return {}
    wf, wt = hole["records"][0]["from_m"], hole["records"][-1]["to_m"]
    out = {}
    for m in hole["registry"]:
        if m["kind"] != "mineral_group_proportion":
            continue
        col = m["id"]
        res = find_runs(hole, [{"metric": col, "op": ">=", "value": threshold}], wf, wt, 0)
        # Length (not record count), so the figure stays right for non-1 m records.
        len_ge = sum((r["to_m"] - r["from_m"] for r in hole["records"]
                      if r["status"][col] == "ok" and r["values"][col] >= threshold), Decimal(0))
        longest = max(res["runs"], key=lambda x: (x["length_m"], -x["from_m"]), default=None)
        vals = [(r["values"][col], r["from_m"], r["to_m"]) for r in hole["records"] if r["status"][col] == "ok"]
        mx = max(vals, key=lambda x: x[0], default=None)
        out[col] = {
            "group": m["group"], "level": m["interpretation_level"], "region": m["region"],
            "threshold": threshold, "length_ge_threshold_m": len_ge,
            "longest_run_ge_threshold": ({"from_m": longest["from_m"], "to_m": longest["to_m"], "length_m": longest["length_m"]} if longest else None),
            "max_value": (mx[0] if mx else None), "max_at": ({"from_m": mx[1], "to_m": mx[2]} if mx else None),
        }
    return out


def build_package(hole: dict, out_dir: Path, collar: dict | None = None, analyses: dict | None = None,
                  source_url: str | None = None) -> dict:
    out_dir = Path(out_dir) / hole["hole_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    recs = hole["records"]
    cols = [m["id"] for m in hole["registry"]]
    extent = (recs[-1]["to_m"] - recs[0]["from_m"]) if recs else Decimal(0)
    covered = sum((r["to_m"] - r["from_m"] for r in recs), Decimal(0))
    coverage = {
        "from_m": recs[0]["from_m"] if recs else None,
        "to_m": recs[-1]["to_m"] if recs else None,
        "n_records": len(recs),
        "record_lengths_m": hole["record_lengths_m"],
        "extent_span_m": extent,
        "covered_record_length_m": covered,
        "gaps": hole["gaps"],
        "gap_length_m": extent - covered,
        "note": "Coverage of the summary table only; it is not the drilled length. "
                "extent_span_m = last to_m - first from_m (includes gaps); covered_record_length_m = sum of record lengths.",
    }
    if collar and collar.get("max_depth_m") and recs:
        md = Decimal(str(collar["max_depth_m"]))
        coverage["drilled_max_depth_m"] = collar["max_depth_m"]
        coverage["covered_fraction_of_drilled_depth"] = {
            "value": covered / md, "numerator": "covered_record_length_m", "denominator": "collar MaxDepth (wamex_collar)",
            "note": "Not clamped; > 1 means the summary and the collar table disagree about hole depth."}
    registry = []
    for m in hole["registry"]:
        e = dict(m); e.update(_metric_stats(hole, m["id"])); registry.append(e)
    src = dict(hole["source"])
    if source_url:
        src["source_url"] = source_url
    src.update(metadata=hole["metadata"], logical_header_record=hole["logical_header_record"],
               product=hole["product"], product_recognised=hole["product_recognised"])
    warnings = []
    if not hole["product_recognised"]:
        warnings.append(f"Unrecognised product line: {hole['product']!r}")
    if hole["na_definition"] != "Not detected or below threshold":
        warnings.append(f"N.A. definition differs from the inspected files: {hole['na_definition']!r}")
    if hole["issues"]:
        warnings.append(f"{len(hole['issues'])} import issues; see import_issues")
    if any(m["kind"] == "unclassified" for m in hole["registry"]):
        warnings.append("Some columns are unclassified by this reader version")
    if collar and collar.get("max_depth_m") and recs and float(recs[-1]["to_m"]) > float(collar["max_depth_m"]):
        warnings.append(f"Summary coverage ends at {recs[-1]['to_m']} m, beyond the collar MaxDepth "
                        f"{collar['max_depth_m']} m (different sources; not corrected here)")
    levels = sorted({m.get("interpretation_level") for m in hole["registry"] if m.get("interpretation_level")})
    doc = {
        "schema_version": SCHEMA_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "hole_id": hole["hole_id"],
        "sources": [src],
        "location": (collar or {}).get("location", {"status": "unlocated", "reason": "no collar source supplied"}),
        "collar": {k: v for k, v in (collar or {}).items() if k != "location"},
        "coverage": coverage,
        "interpretation_levels_present": levels,
        "import_review": hole["import_review"],
        "metadata_group": hole["metadata_group"],
        "conventions": {"display_interval_convention": DISPLAY_INTERVAL_CONVENTION,
                        "scan_bin_membership": "(from_m, to_m] - empirical rule that reproduces the official summary "
                                               "from scans for four feature columns in CMDD001/CMDD002 only"},
        "metric_counts": {k: sum(1 for m in registry if m["kind"] == k) for k in sorted({m["kind"] for m in registry})},
        "metrics": registry,
        "occurrence_index": occurrence_index(hole),
        "analyses": analyses or {},
        "import_issues": hole["issues"],
        "warnings": warnings,
        "files": {"metres_json": "metres.json", "metres_csv": "metres.csv", "records_long_csv": "records_long.csv"},
    }
    (out_dir / "hole.json").write_text(json.dumps(jsonable(doc), indent=1, ensure_ascii=False), encoding="utf-8")
    metres = {
        "hole_id": hole["hole_id"],
        "value_codes": {"NA": "source N.A. = " + str(hole["na_definition"]), "BLANK": "empty cell", "INVALID": "unparseable token"},
        "from_m": [_num(r["from_m"]) for r in recs],
        "to_m": [_num(r["to_m"]) for r in recs],
        "record_no": [r["record_no"] for r in recs],
        "values": {c: [(_num(r["values"][c]) if r["status"][c] == "ok" else STATUS_CODE[r["status"][c]]) for r in recs] for c in cols},
    }
    (out_dir / "metres.json").write_text(json.dumps(metres, separators=(",", ":")), encoding="utf-8")
    with open(out_dir / "metres.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["hole_id", "record_no", "from_m", "to_m"] + cols)
        for r in recs:
            w.writerow([hole["hole_id"], r["record_no"], r["from_m"], r["to_m"]] + [r["tokens"][c] for c in cols])
    # Long format, one row per (record, metric):
    # hole_id, from_m, to_m, metric_id, value, unit, series/algorithm, quality_status, source_file/hash/record.
    reg = {m["id"]: m for m in hole["registry"]}
    md = hole["metadata"]
    with open(out_dir / "records_long.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["hole_id", "from_m", "to_m", "metric_id", "value", "raw_token", "unit", "kind", "region",
                    "interpretation_level", "algorithm", "quality_status", "source_file", "source_sha256", "source_record_no"])
        for r in recs:
            for c in cols:
                m = reg[c]
                region = m.get("region") or ""
                algo = md.get(f"{region}_algorithm", "") if region in ("SWIR", "TIR") else ""
                st = r["status"][c]
                w.writerow([hole["hole_id"], r["from_m"], r["to_m"], c, (r["values"][c] if st == "ok" else ""), r["tokens"][c],
                            m.get("unit") or "", m["kind"], region, m.get("interpretation_level", ""), algo, st,
                            hole["source"]["filename"], hole["source"]["sha256"], r["record_no"]])
    return doc
