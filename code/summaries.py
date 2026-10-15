"""Read GSWA summary CSVs without changing their source tokens.

Author: Ding Qing
Date: 2026-10-15
"""

import csv
import hashlib
import io
import json
import re
from pathlib import Path

from datasets import SOURCES
from metrics import METRIC_ID, METRIC_REGISTRY


def _hash(value):
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


FIELD_ALIASES = {"Invalid_(System_TIR)": "INVALID_(System_TIR)"}


def load_summary(path: Path, hole_id: str | None = None) -> dict:
    """Read one declared GSWA summary; preserve logical CSV record positions."""
    path = Path(path)
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError(f"Summary exceeds the 20 MiB input limit: {path.name}")
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    table = list(csv.reader(io.StringIO(content.decode("utf-8-sig")), strict=True))
    index = next((i for i, cells in enumerate(table)
                  if cells[:2] == ["Depth_from_(m)", "Depth_to_(m)"]), None)
    if index is None:
        raise ValueError(f"Missing logical CSV depth header in {path.name}")
    header = table[index]
    field = METRIC_REGISTRY[METRIC_ID]["source_field"]
    if len(set(header)) != len(header) or field not in header:
        raise ValueError(f"Duplicate columns or missing {field} in {path.name}")
    metadata = {}
    metadata_records = []
    for cells in table[:index]:
        metadata_records.append(cells)
        if len(cells) >= 2 and cells[0]:
            if cells[0] in metadata and metadata[cells[0]] != cells[1]:
                raise ValueError(f"Conflicting metadata {cells[0]} in {path.name}")
            metadata[cells[0]] = cells[1]
    if hole_id is None:
        hole_id = metadata.get("Dataset", "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", hole_id):
        raise ValueError("Missing or unsupported Dataset identifier")
    if metadata.get("Dataset") != hole_id:
        raise ValueError(f"Dataset does not match declared hole {hole_id}")
    if metadata.get("N.A.") != "Not detected or below threshold":
        raise ValueError(f"Unrecognized N.A. definition in {path.name}")
    if not metadata.get("****W", "").startswith("Wavelength of dominant spectral feature"):
        raise ValueError(f"Unrecognized feature wavelength definition in {path.name}")
    product = table[0][0] if table and table[0] else ""
    if product != METRIC_REGISTRY[METRIC_ID]["product"]:
        raise ValueError(f"Unsupported summary product in {path.name}")
    series_id = f"{hole_id}:" + _hash({"hole_id": hole_id, "product": product, "metadata": metadata})[:24]
    source_id = f"{hole_id}:summary:{digest[:16]}"
    aliases = {name: FIELD_ALIASES[name] for name in header if name in FIELD_ALIASES}
    canonical_fields = [FIELD_ALIASES.get(name, name) for name in header[2:]]
    if len(set(canonical_fields)) != len(canonical_fields):
        raise ValueError("Conflicting canonical scalar columns")
    records = []
    for position, cells in enumerate(table[index + 1:], 1):
        if not cells or not any(cell.strip() for cell in cells):
            continue
        if len(cells) != len(header):
            raise ValueError(f"Malformed CSV data record {position} in {path.name}")
        original = dict(zip(header, cells))
        records.append({
            "hole_id": hole_id, "series_id": series_id, "metric_id": METRIC_ID,
            "from_m": original["Depth_from_(m)"], "to_m": original["Depth_to_(m)"],
            "raw_token": original[field], "source_id": source_id,
            "data_record_index": position, "record_id": _hash([digest, position, field]),
            "source_filename": path.name, "source_sha256": digest,
            "raw_row": original,
            "field_aliases": aliases,
        })
    return {"records": records, "rows": records, "source": {
        "source_id": source_id, "hole_id": hole_id, "filename": path.name,
        "relative_path": SOURCES.get(hole_id, (path.name, None))[0],
        "sha256": digest, "series_id": series_id, "metric_id": METRIC_ID,
        "metadata": metadata, "metadata_records": metadata_records,
        "logical_header_record": index + 1, "data_record_count": len(records),
        "source_url": f"https://dasc.dmirs.wa.gov.au/download/metadata?fileName=Hylogger/Mineral_Logs/SM_{hole_id}.csv",
        "reader_version": "hylogger-v2-2.1", "fields": canonical_fields,
        "original_fields": header[2:], "field_aliases": aliases,
    }}

