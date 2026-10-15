"""Generic reader for GSWA "TSG Summary Mineral Log" CSVs (SM_<hole>.csv).

Nothing here is specific to CMDD001/CMDD002: the header row is located by its
first two cells, the hole id comes from the file's own ``Dataset`` metadata row,
and every column is classified from its name pattern. Unknown columns are kept
and reported, never silently dropped.

Standard library only.

Author: Ding Qing
Date: 2026-10-15
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

PRODUCT_NAME = "GSWA TSG Summary Mineral Log"
NA_DEFINITION = "Not detected or below threshold"
DEPTH_FROM, DEPTH_TO = "Depth_from_(m)", "Depth_to_(m)"
# Metadata that must match before values from two files may be compared or joined.
COMPATIBILITY_KEYS = ("SWIR_algorithm", "TIR_algorithm", "Bin_min_threshold", "Scalar_min_depth",
                      "System", "User", "****D", "****W", "N.A.")

_GROUP_RE = re.compile(r"^(?P<group>.+)_\((?P<level>System|User|Domained)_(?P<region>SWIR|TIR|MIR)\)$", re.I)
_FEATURE_RE = re.compile(r"^(?P<centre>\d+)(?P<kind>[WD])_(?P<assignment>.+)$")


def classify_column(name: str, metadata: dict) -> dict:
    """Return a metric-registry entry for one source column."""
    m = _GROUP_RE.match(name)
    if m and m.group("group").strip().lower() == "invalid":
        level = m.group("level").capitalize()
        region = m.group("region").upper()
        return {
            "id": name,
            "kind": "quality_fraction",
            "label": f"Invalid / unclassified spectra ({level} {region})",
            "group": "Invalid",
            "interpretation_level": level,
            "region": region,
            "unit": "fraction 0-1 (share of the 1 m bin not assigned to a mineral group)",
            "definition": (
                "Share of the bin's spectra the unmixing could not classify. Source metadata: "
                f"'{metadata.get('Invalid', 'Unclassified e.g. aspectral, noisy, low albedo, high errors')}'. "
                "A data-quality indicator, not a mineral."
            ),
            "comparable_across": "same level and region only",
        }
    if m:
        group = m.group("group")
        level = m.group("level").capitalize()
        region = m.group("region").upper()
        return {
            "id": name,
            "kind": "mineral_group_proportion",
            "label": f"{group} ({level} {region})",
            "group": group,
            "interpretation_level": level,
            "region": region,
            "unit": "fraction 0-1 (relative proportion within the 1 m bin)",
            "definition": (
                f"Relative proportion of the {group} group in the {level.lower()} {region} "
                f"spectral unmixing result for this 1 m bin ({metadata.get(region + '_algorithm', 'algorithm not stated')}). "
                "Values in one region sum to 1 per bin in the inspected files. Not a mass percentage; "
                "the exact within-bin aggregation of group proportions has not been independently verified."
            ),
            "comparable_across": f"same group, level and region only; never add SWIR and TIR proportions",
        }
    m = _FEATURE_RE.match(name)
    if m:
        centre, kind, assignment = m.group("centre"), m.group("kind"), m.group("assignment")
        if kind == "W":
            return {
                "id": name, "kind": "feature_wavelength", "label": f"{assignment} feature wavelength (~{centre} nm)",
                "region": _region_for_nm(int(centre)), "unit": "nm", "assignment": assignment,
                "definition": metadata.get("****W", "Wavelength of dominant spectral feature").replace("****", centre),
                "comparable_across": "same column name and product",
            }
        return {
            "id": name, "kind": "feature_depth", "label": f"{assignment} feature depth (~{centre} nm)",
            "region": _region_for_nm(int(centre)), "unit": "background-normalised depth (unitless)",
            "assignment": assignment,
            "definition": metadata.get("****D", "Background normalised depth of dominant spectral feature").replace("****", centre)
            + " 'Depth' here is absorption strength, not depth down the hole.",
            "comparable_across": "same column name and product",
        }
    if name.lower().endswith("albedo"):
        return {"id": name, "kind": "albedo", "label": name.replace("_", " "), "region": "VNIR-SWIR",
                "unit": "reflectance (unitless)", "definition": "Visible-SWIR albedo reported in the summary.",
                "comparable_across": "same column name and product"}
    return {"id": name, "kind": "unclassified", "label": name, "region": None, "unit": None,
            "definition": "Column not recognised by this reader version; kept unchanged.",
            "comparable_across": "unknown"}


def _region_for_nm(nm: int) -> str:
    if nm < 1300:
        return "VNIR"
    if nm <= 2500:
        return "SWIR"
    if nm <= 5500:
        return "MIR"
    return "TIR"


def parse_value(token: str, na_token: str = "N.A."):
    """Return (value, status). Status is ok | source_na | blank | invalid."""
    t = (token or "").strip()
    if t == na_token:
        return None, "source_na"
    if t == "":
        return None, "blank"
    try:
        v = Decimal(t)
    except InvalidOperation:
        return None, "invalid"
    if not v.is_finite():
        return None, "invalid"
    return v, "ok"


def read_summary_csv(path: str | Path) -> dict:
    """Read one SM CSV and return metadata, registry, records and an audit."""
    path = Path(path)
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    table = list(csv.reader(io.StringIO(raw.decode("utf-8-sig")), strict=True))
    header_idx = next((i for i, r in enumerate(table) if r[:2] == [DEPTH_FROM, DEPTH_TO]), None)
    if header_idx is None:
        raise ValueError(f"{path.name}: no '{DEPTH_FROM},{DEPTH_TO}' header row found")
    header = table[header_idx]
    if len(set(header)) != len(header):
        raise ValueError(f"{path.name}: duplicate column names")
    metadata = {}
    for r in table[:header_idx]:
        if r and r[0].strip():
            metadata[r[0].strip()] = r[1].strip() if len(r) > 1 else ""
    product = table[0][0].strip() if table and table[0] else ""
    hole_id = metadata.get("Dataset", "").strip()
    if not hole_id:
        raise ValueError(f"{path.name}: no Dataset metadata row; hole id unknown")
    na_def = metadata.get("N.A.")
    registry = [classify_column(c, metadata) for c in header[2:]]

    records, issues = [], []
    for k, r in enumerate(table[header_idx + 1:], start=1):
        if not any(c.strip() for c in r):
            continue
        if len(r) != len(header):
            issues.append({"record_no": k, "issue": f"expected {len(header)} cells, got {len(r)}"})
            continue
        f, sf = parse_value(r[0]); t, st = parse_value(r[1])
        if sf != "ok" or st != "ok" or t <= f:
            issues.append({"record_no": k, "issue": f"bad depth interval {r[0]!r}-{r[1]!r}"})
            continue
        values, statuses = {}, {}
        for col, tok in zip(header[2:], r[2:]):
            v, s = parse_value(tok)
            values[col] = v
            statuses[col] = s
        records.append({"record_no": k, "from_m": f, "to_m": t, "values": values, "status": statuses,
                        "tokens": dict(zip(header[2:], r[2:]))})

    records.sort(key=lambda x: (x["from_m"], x["to_m"]))
    # Overlaps / duplicates are reported; the hole stays usable only if none exist.
    for a, b in zip(records, records[1:]):
        if b["from_m"] < a["to_m"]:
            issues.append({"record_no": b["record_no"], "issue": f"overlaps previous record ({a['from_m']}-{a['to_m']})"})
    gaps = [{"from_m": a["to_m"], "to_m": b["from_m"]} for a, b in zip(records, records[1:]) if b["from_m"] > a["to_m"]]
    lengths = sorted({str(x["to_m"] - x["from_m"]) for x in records})

    # Import review. Record-level problems or unknown semantics => package is kept for inspection
    # but marked NOT queryable. Nothing is silently dropped or "fixed".
    reasons = []
    if product != PRODUCT_NAME:
        reasons.append(f"unrecognised product line {product!r}")
    if na_def != NA_DEFINITION:
        reasons.append(f"N.A. definition {na_def!r} differs from {NA_DEFINITION!r}")
    if any(i["issue"].startswith("expected") for i in issues):
        reasons.append("malformed rows")
    if any(i["issue"].startswith("bad depth") for i in issues):
        reasons.append("bad depth intervals")
    if any(i["issue"].startswith("overlaps") for i in issues):
        reasons.append("overlapping records")
    if not records:
        reasons.append("no data records")
    unknown = [m["id"] for m in registry if m["kind"] == "unclassified"]
    status = "accepted" if not reasons else "quarantined"
    # Whitespace-only differences (e.g. a stray tab inside a definition) do not change meaning:
    # they are normalised for grouping; the raw text stays in sources[].metadata.
    group_fields = {k: (" ".join(metadata[k].split()) if metadata.get(k) is not None else None) for k in COMPATIBILITY_KEYS}
    group_fields.update(product=product, interpretation_levels=sorted({m.get("interpretation_level") for m in registry if m.get("interpretation_level")}))
    group_id = "mg-" + hashlib.sha256(repr(sorted(group_fields.items())).encode()).hexdigest()[:12]
    return {
        "import_review": {
            "status": status,
            "queryable": status == "accepted",
            "reasons": reasons,
            "unclassified_columns": unknown,
            "note": "Unclassified columns are kept but must not be offered for queries until registered.",
        },
        "metadata_group": {"id": group_id, "fields": group_fields,
                           "rule": "values are only compared or joined within one metadata group"},
        "hole_id": hole_id,
        "product": product,
        "product_recognised": product == PRODUCT_NAME,
        "metadata": metadata,
        "na_definition": na_def,
        "header": header,
        "logical_header_record": header_idx + 1,
        "registry": registry,
        "records": records,
        "issues": issues,
        "gaps": gaps,
        "record_lengths_m": lengths,
        "source": {"kind": "summary_csv", "filename": path.name, "sha256": sha, "bytes": len(raw)},
    }
