"""State-wide "what exists" layer and collar lookup from the GSWA interim HyLogger package.

Reads the SQLite read-only. Joins hylogger_dataset_index.WAMEX_CollarId -> wamex_collar.CollarId
(primary id only; the alternate id is reported, not silently used). Coordinates are GDA2020
geographic (per the package metadata); they are passed through unchanged and labelled as such.

LICENCE FLAG: the interim package licence page carries both CC BY 4.0 wording and third-party
sharing/display restrictions. Everything derived from it is marked licence_flag="interim_display_unresolved".
Standard library only.

Author: Ding Qing
Date: 2026-10-15
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

LICENCE_FLAG = "interim_display_unresolved"
CRS = {"name": "GDA2020 geographic", "epsg": 7844, "axis_order_in_geojson": "lon,lat",
       "note": "Passed through from the interim package; not transformed to WGS84."}


def _connect(sqlite_path):
    return sqlite3.connect(f"file:{Path(sqlite_path).as_posix()}?mode=ro", uri=True)


def _flag(v):
    return {"1": True, "0": False}.get(str(v).strip(), None) if v is not None else None


def _norm(s):
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def _name_check(hole_id, company_hole_id, collar_hole_id):
    if company_hole_id is None and collar_hole_id is None:
        return "no_collar"
    if company_hole_id == hole_id:
        return "exact"
    if _norm(company_hole_id) == _norm(hole_id):
        return "case_or_punctuation_differs"
    return "differs"


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_index(sqlite_path, nvcl_catalog_json=None) -> list[dict]:
    zips = {}
    if nvcl_catalog_json and Path(nvcl_catalog_json).exists():
        for d in json.loads(Path(nvcl_catalog_json).read_text(encoding="utf-8"))["datasets"]:
            zips[d["name"][:-4]] = {"url": d["download_url"], "approx_bytes": d["approx_bytes"]}
    db_sha = file_sha256(sqlite_path)
    con = _connect(sqlite_path); con.row_factory = sqlite3.Row
    surveys = {str(k): v for k, v in con.execute("select CollarId, count(*) from wamex_survey group by CollarId").fetchall()}
    rows = con.execute("""
        select i.*, w.Longitude lon, w.Latitude lat, w.MaxDepth max_depth, w.Elevation elev,
               w.TectonicRegion tregion, w.HoleType hole_type, w.Company company,
               w.HoleId collar_hole_id, w.CompanyHoleId collar_company_hole_id, w.Anumber collar_anumber
        from hylogger_dataset_index i left join wamex_collar w on w.CollarId = i.WAMEX_CollarId
        where i.NVCL_HoleName is not null and trim(i.NVCL_HoleName) != ''
        order by i.NVCL_HoleName, i.HyloggerIndexId""").fetchall()
    holes, seen = [], {}
    for r in rows:
        hid = r["NVCL_HoleName"].strip()
        if hid in seen:
            seen[hid]["duplicate_index_rows"] += 1
            continue
        collar_found = r["collar_hole_id"] is not None
        name_check = _name_check(hid, r["collar_company_hole_id"], r["collar_hole_id"])
        rep = str(r["Primary_report_number"]).strip() if r["Primary_report_number"] is not None else None
        others = {str(x).strip() for x in (r["WAMEX_report_Anumber"], r["WAMEX_report_Anumber_alternate"]) if x is not None}
        ca = str(r["collar_anumber"]) if r["collar_anumber"] is not None else None
        report_check = ("no_collar" if not collar_found else
                        "missing" if ca is None or (rep is None and not others) else
                        "match_primary_report" if rep == ca else
                        "match_other_index_report_field" if ca in others else "differs")
        if not collar_found:
            identity = "index_coordinates_only" if r["Shapefile_longitude"] is not None else "unlocated"
        elif name_check == "exact" and report_check.startswith("match"):
            identity = "name_and_report_match"
        else:
            identity = "needs_review"
        verification = {
            "identity_status": identity,
            "name_check": name_check, "report_check": report_check,
            "index_id": r["HyloggerIndexId"], "index_data_name": r["Data_name"],
            "primary_collar_id": r["WAMEX_CollarId"], "alternate_collar_id": r["WAMEX_CollarId_alternate"],
            "index_reports": {"primary": r["Primary_report_number"], "wamex_anumber": r["WAMEX_report_Anumber"],
                              "wamex_anumber_alternate": r["WAMEX_report_Anumber_alternate"]},
            "collar_hole_id": r["collar_hole_id"], "collar_company_hole_id": r["collar_company_hole_id"],
            "collar_anumber": r["collar_anumber"],
            "join": "hylogger_dataset_index.NVCL_HoleName -> WAMEX_CollarId -> wamex_collar.CollarId",
            "coordinate_fields": ("wamex_collar.Longitude/Latitude" if collar_found else
                                  "hylogger_dataset_index.Shapefile_longitude/latitude"),
            "db_sha256": db_sha,
            "note": "Automatic check only; 'needs_review' is not an error claim, 'name_and_report_match' is not a field survey.",
        }
        if r["lon"] is not None and r["lat"] is not None:
            loc = {"status": "located", "lon": r["lon"], "lat": r["lat"], "crs": CRS,
                   "source": "wamex_collar via hylogger_dataset_index.WAMEX_CollarId", "licence_flag": LICENCE_FLAG}
        elif r["Shapefile_longitude"] is not None and r["Shapefile_latitude"] is not None:
            # Fallback: coordinates carried in the index itself. Kept distinguishable from collar records.
            loc = {"status": "located", "lon": r["Shapefile_longitude"], "lat": r["Shapefile_latitude"], "crs": CRS,
                   "source": "hylogger_dataset_index Shapefile_longitude/latitude (no collar match)",
                   "licence_flag": LICENCE_FLAG}
        else:
            loc = {"status": "unlocated", "reason": "no collar match and no index coordinates"}
        loc["verification"] = verification
        h = {
            "hole_id": hid,
            "index_id": r["HyloggerIndexId"],
            "identity_status": identity,
            "survey_record_count_primary_collar": surveys.get(str(r["WAMEX_CollarId"]).strip(), 0),
            "location": loc,
            "commodities": [c.strip().title() for c in (r["COMMODITY"] or "").split(";") if c.strip()],
            "target_commodity": (r["WS_TargetCommodity"] or "").title() or None,
            "report": r["Primary_report_number"],
            "confidentiality": r["Confidentiality_primary_Anumber"],
            "max_depth_m": r["max_depth"], "elevation_m": r["elev"], "tectonic_region": r["tregion"],
            "hole_type": r["hole_type"],
            "has_summary_csv": bool(r["MINERALLOG"] and str(r["MINERALLOG"]).startswith("http")),
            "has_tir": bool(r["SCDATE_TIR"]), "has_mir": bool(r["SCDATE_MIR"]),
            "has_assay": _flag(r["Assay_data"]), "has_geology_log": _flag(r["Logging_data"]),
            "has_survey": _flag(r["Survey_data"]),
            "links": {"summary_csv": r["MINERALLOG"], "summary_histogram_pdf": r["SUM_HISTO"],
                      "core_mosaic": r["MOSAIC"], "raw_package_zip": zips.get(hid, {}).get("url")},
            "raw_package_approx_bytes": zips.get(hid, {}).get("approx_bytes"),
            "alternate_collar_id": r["WAMEX_CollarId_alternate"],
            "duplicate_index_rows": 0,
        }
        seen[hid] = h
        holes.append(h)
    con.close()
    return holes


def collar_for(holes_by_id: dict, hole_id: str) -> dict | None:
    h = holes_by_id.get(hole_id)
    if not h:
        return None
    keys = ("location", "identity_status", "commodities", "target_commodity", "report", "max_depth_m", "elevation_m",
            "tectonic_region", "hole_type", "links", "has_assay", "has_geology_log", "has_tir",
            "survey_record_count_primary_collar")
    return {k: h[k] for k in keys}


def write_catalog(holes: list[dict], out_dir: Path, processed: dict) -> dict:
    """catalog.json (all holes) + catalog.geojson (located holes) for the map's state-wide layer."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    for h in holes:
        h["processed_package"] = processed.get(h["hole_id"])
        h["co_located_with"] = []
    # Flag datasets sitting on (almost) the same collar, e.g. CMDD001 / CMDD001A: they may be repeat
    # scans of one hole and must not be counted as independent holes without checking.
    import math
    pts = [(h, h["location"]["lon"], h["location"]["lat"]) for h in holes if h["location"]["status"] == "located"]
    pts.sort(key=lambda t: t[2])
    for i, (a, lon1, lat1) in enumerate(pts):
        for b, lon2, lat2 in pts[i + 1:]:
            if lat2 - lat1 > 0.0001:
                break
            dx = (lon2 - lon1) * 111320 * math.cos(math.radians(lat1)); dy = (lat2 - lat1) * 110574
            if math.hypot(dx, dy) <= 5:
                a["co_located_with"].append(b["hole_id"]); b["co_located_with"].append(a["hole_id"])
    ids = {}
    for h in holes:
        ids[h["identity_status"]] = ids.get(h["identity_status"], 0) + 1
    names = {}
    for h in holes:
        k = h["location"].get("verification", {}).get("name_check", "n/a")
        names[k] = names.get(k, 0) + 1
    reps = {}
    for h in holes:
        k = h["location"].get("verification", {}).get("report_check", "n/a")
        reps[k] = reps.get(k, 0) + 1
    meta = {"source": "GSWA INTERIM HyLogger Dataset Package (GDA2020), DASC download 5464",
            "description": "drillhole DATA ENTRIES in the HyLogger index (distinct NVCL_HoleName), not a count of "
                           "independent holes; only processed_package entries have loaded, queryable summaries",
            "licence_flag": LICENCE_FLAG, "crs": CRS, "n_entries": len(holes),
            "identity_status_counts": ids, "name_check_counts": names, "report_check_counts": reps,
            "db_sha256": holes[0]["location"].get("verification", {}).get("db_sha256") if holes else None,
            "co_located_note": "co_located_with = another entry within 5 m; a flag for review, not a confirmed duplicate count",
            "n_located": sum(1 for h in holes if h["location"]["status"] == "located"),
            "n_with_summary_csv": sum(1 for h in holes if h["has_summary_csv"]),
            "n_processed": sum(1 for h in holes if h["processed_package"]),
            "n_located_by_collar": sum(1 for h in holes if h["location"].get("source", "").startswith("wamex_collar")),
            "n_located_by_index_only": sum(1 for h in holes if h["location"].get("source", "").startswith("hylogger_dataset_index")),
            "n_co_located_within_5m": sum(1 for h in holes if h["co_located_with"])}
    (out_dir / "catalog.json").write_text(json.dumps({"meta": meta, "holes": holes}, indent=0, default=str), encoding="utf-8")
    feats = []
    for h in holes:
        if h["location"]["status"] != "located":
            continue
        props = {k: v for k, v in h.items() if k not in ("location", "links")}
        v = h["location"].get("verification", {})
        props.update(name_check=v.get("name_check"), report_check=v.get("report_check"),
                     primary_collar_id=v.get("primary_collar_id"))
        props["commodities"] = ";".join(h["commodities"])
        props["co_located_with"] = ";".join(h["co_located_with"])
        props["location_source"] = h["location"].get("source")
        props.update({f"link_{k}": v for k, v in h["links"].items()})
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [h["location"]["lon"], h["location"]["lat"]]},
                      "properties": props})
    gj = {"type": "FeatureCollection", "name": "hylogger_catalog",
          "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::7844"}},
          "features": feats}
    (out_dir / "catalog.geojson").write_text(json.dumps(gj, default=str), encoding="utf-8")
    return meta
