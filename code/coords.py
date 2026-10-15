"""Resolve collar identities and native coordinates from the reviewed database.

Author: Ding Qing
Date: 2026-10-15
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import sqlite3
from datasets import LOADED_HOLES


HOLES = LOADED_HOLES
PACKAGE_PATH = Path("official_interim_20261009/extracted/INTERIM_HyLogger_Dataset_Package_GDA2020_DB")
DATABASE_PATH = PACKAGE_PATH / "DATABASES/HyLogger_Dataset_Package.sqlite"
METADATA_PATH = PACKAGE_PATH / "DOCUMENTS/METADATA/METADATA_INTERIM_Hylogger_GDA2020.pdf"
PACKAGE_URL = "https://dasc.dmirs.wa.gov.au/Download/File/5464"
TRUSTED_RELEASES = {
    (
        "dafae89138d06748f5514e752b3c335375414a8579e60c11b91a29d961c73f67",
        "24b4fb6c847ba3381c4860a5c057250120fe4c478ee197e45a0abca080f00a56",
    ): "GDA2020 geographic coordinates (decimal degrees)",
}


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _unlocated(note):
    return {
        "longitude": None,
        "latitude": None,
        "crs": None,
        "verified": False,
        "note": note,
        "source_url": PACKAGE_URL,
    }


def _positive_integer(value, label):
    # Do not accept coercions such as '104232x', floats, booleans, or NULL.
    if isinstance(value, bool):
        raise ValueError(f"{label} is not an exact positive integer identifier")
    text = str(value).strip()
    if not text.isascii() or not text.isdigit() or int(text) <= 0:
        raise ValueError(f"{label} is not an exact positive integer identifier")
    return int(text)


def _position(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} is not a numeric coordinate")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{label} is outside valid geographic bounds")
    return number


def _hole_coordinates(connection, hole, crs, fingerprints):
    rows = connection.execute(
        "SELECT HyloggerIndexId, Data_name, Hole_name, NVCL_HoleName, "
        "WAMEX_CollarId, WAMEX_report_Anumber, Primary_report_number, "
        "Confidentiality_primary_Anumber "
        "FROM hylogger_dataset_index WHERE NVCL_HoleName = ?", (hole,)
    ).fetchall()
    if len(rows) != 1:
        raise ValueError("Expected one exact NVCL index match; found " + str(len(rows)))
    index = rows[0]
    if any(index[key] != hole for key in ("Data_name", "Hole_name", "NVCL_HoleName")):
        raise ValueError("Index hole identifiers disagree")
    collar_id = _positive_integer(index["WAMEX_CollarId"], "Primary WAMEX_CollarId")
    report_id = _positive_integer(index["WAMEX_report_Anumber"], "WAMEX report")
    if _positive_integer(index["Primary_report_number"], "Primary report") != report_id:
        raise ValueError("Index primary report identifiers disagree")
    if index["Confidentiality_primary_Anumber"] != "OPEN FILE":
        raise ValueError("Index does not identify the primary report as open file")
    collars = connection.execute(
        "SELECT CollarId, CompanyHoleId, Anumber, Longitude, Latitude, Confidential, MaxDepth "
        "FROM wamex_collar WHERE CollarId = ?", (collar_id,)
    ).fetchall()
    if len(collars) != 1:
        raise ValueError("Expected one primary CollarId match; found " + str(len(collars)))
    collar = collars[0]
    if collar["CompanyHoleId"] != hole:
        raise ValueError("Collar company hole identifier disagrees with the NVCL hole")
    if _positive_integer(collar["Anumber"], "Collar report") != report_id:
        raise ValueError("Collar report does not match the index primary report")
    if collar["Confidential"] != 0:
        raise ValueError("Collar record is not marked open file")
    longitude = _position(collar["Longitude"], "Longitude", -180, 180)
    latitude = _position(collar["Latitude"], "Latitude", -90, 90)
    index_id = _positive_integer(index["HyloggerIndexId"], "HyLogger index ID")
    return {
        "longitude": longitude,
        "latitude": latitude,
        "crs": crs,
        "verified": True,
        "source_id": "official-interim-collar-20261009",
        "source_filename": DATABASE_PATH.as_posix(),
        "source_table": "wamex_collar",
        "source_sha256": fingerprints[0],
        "source_url": PACKAGE_URL,
        "collar_id": collar_id,
        "report_number": report_id,
        "max_depth_m": collar["MaxDepth"],
        "wamex_collar_id": collar_id,
        "transform": "None; native GDA2020 geographic grid.",
        "accuracy": "Positional accuracy is not specified by the source metadata.",
        "coordinate_note": "Verified primary collar identity. Collar position only; no downhole trajectory inferred.",
        "coordinate_source": {
            "index_table": "hylogger_dataset_index",
            "index_id": index_id,
            "join_field": "WAMEX_CollarId",
            "primary_report_anumber": report_id,
            "metadata_filename": METADATA_PATH.as_posix(),
            "metadata_sha256": fingerprints[1],
            "crs_verification": "Matched inspected database and metadata PDF SHA-256 pair; PDF page 1 declares GDA2020 decimal degrees.",
            "crs_authority_code": None,
        },
    }


def load_coordinates(data_root, hole_ids=None):
    """Return verified collars; missing or ambiguous identities remain unlocated."""
    root = Path(data_root).resolve()
    holes = tuple(HOLES if hole_ids is None else hole_ids)
    database, metadata = root / DATABASE_PATH, root / METADATA_PATH
    if not database.is_file():
        note = "Optional external collar database is absent. Add the official interim package to enable verified locations."
        return {hole: _unlocated(note) for hole in holes}
    if not metadata.is_file():
        note = "The official metadata PDF is absent; the source coordinate reference system cannot be verified."
        return {hole: _unlocated(note) for hole in holes}
    try:
        fingerprints = (_sha256(database), _sha256(metadata))
    except OSError:
        note = "The external collar database or metadata PDF could not be read."
        return {hole: _unlocated(note) for hole in holes}
    crs = TRUSTED_RELEASES.get(fingerprints)
    if not crs:
        note = "The database/metadata fingerprint pair is not a reviewed release. Verify its source CRS before enabling locations."
        return {hole: _unlocated(note) for hole in holes}
    try:
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only = ON")
            result = {}
            for hole in holes:
                try:
                    result[hole] = _hole_coordinates(connection, hole, crs, fingerprints)
                except ValueError as error:
                    result[hole] = _unlocated("Location identity validation failed: " + str(error))
                except sqlite3.Error:
                    result[hole] = _unlocated("The external database does not provide the expected verifiable collar schema.")
            return result
        finally:
            connection.close()
    except (sqlite3.Error, OSError):
        note = "The external collar database could not be opened read-only."
        return {hole: _unlocated(note) for hole in holes}
