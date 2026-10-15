"""Turn whatever HyLogger files are in a folder into standard hole packages.

Usage:
  python run_pipeline.py --inputs <data folder> --out packages       [--sqlite <HyLogger_Dataset_Package.sqlite>] [--nvcl-catalog <saved NCI catalogue JSON>]

Nothing is configured per hole: SM_*.csv files are found recursively, the hole id comes from the
file's own "Dataset" row, and raw TSG packages (*_tsg.tsg + *_tsg.bip) next to them are used
when the optional scientific stack (numpy, pandas, pytsg) is installed.
Source files are only read.

Author: Ding Qing
Date: 2026-10-15
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from hylogger_pipeline.summary_csv import read_summary_csv  # noqa: E402
from hylogger_pipeline.package import build_package, jsonable, PIPELINE_VERSION, SCHEMA_VERSION  # noqa: E402
from hylogger_pipeline import catalog as cat  # noqa: E402


def find_inputs(paths):
    csvs, tsgs = [], {}
    for p in paths:
        p = Path(p)
        files = [p] if p.is_file() else sorted(p.rglob("*"))
        for f in files:
            if f.is_file() and f.suffix.lower() == ".csv" and f.name.upper().startswith("SM_"):
                csvs.append(f)
            if f.is_file() and f.name.lower().endswith("_tsg.tsg"):
                hole = f.name[: -len("_tsg.tsg")]
                tsgs[hole] = f.parent
    return csvs, tsgs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inputs", nargs="+", required=True)
    ap.add_argument("--sqlite", help="interim HyLogger package SQLite (optional; collars + state-wide layer)")
    ap.add_argument("--nvcl-catalog", help="saved NCI THREDDS catalogue JSON (optional; raw package links)")
    ap.add_argument("--out", default="packages")
    ap.add_argument("--analyses", help="folder with <hole>/analyses.json produced by the scan/ML scripts (optional)")
    a = ap.parse_args(argv)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    holes_index, by_id = [], {}
    if a.sqlite:
        holes_index = cat.load_index(a.sqlite, a.nvcl_catalog)
        by_id = {h["hole_id"]: h for h in holes_index}

    csvs, tsgs = find_inputs(a.inputs)
    processed, log, queryable = {}, [], {}
    # 1) read everything first, so duplicate Dataset ids are decided on content, not file order
    by_hole = {}
    for f in csvs:
        try:
            hole = read_summary_csv(f)
        except Exception as e:  # report and continue with the other holes
            log.append({"file": f.name, "status": "rejected", "reason": str(e)})
            continue
        by_hole.setdefault(hole["hole_id"], []).append((f, hole))
    groups = {}
    for hid in sorted(by_hole):
        entries = by_hole[hid]
        hashes = sorted({h["source"]["sha256"] for _, h in entries})
        if len(hashes) > 1:
            for f, h in entries:
                log.append({"file": f.name, "status": "conflict_not_packaged", "hole_id": hid,
                            "reason": f"{len(hashes)} different files claim Dataset {hid}; none chosen automatically"})
            continue
        f, hole = entries[0]
        for f2, _ in entries[1:]:
            log.append({"file": f2.name, "status": "duplicate_identical_skipped", "hole_id": hid,
                        "reason": f"same SHA-256 as {f.name}"})
        collar = cat.collar_for(by_id, hid)
        analyses = {}
        if a.analyses and (Path(a.analyses) / hid / "analyses.json").exists():
            adir = Path(a.analyses) / hid
            analyses = json.loads((adir / "analyses.json").read_text(encoding="utf-8"))
            (out / hid).mkdir(parents=True, exist_ok=True)
            for extra in ("scan_stats.json", "lithology.json"):
                if (adir / extra).exists():
                    shutil.copyfile(adir / extra, out / hid / extra)
        url = (collar or {}).get("links", {}).get("summary_csv")
        doc = build_package(hole, out, collar=collar, analyses=analyses, source_url=url)
        processed[hid] = f"{hid}/hole.json"
        review = doc["import_review"]
        status = "packaged_queryable" if review["queryable"] else "packaged_quarantined"
        if review["queryable"]:
            queryable[hid] = {"package": f"{hid}/hole.json", "source_sha256": hole["source"]["sha256"],
                              "metadata_group": doc["metadata_group"]["id"],
                              "identity_status": (collar or {}).get("identity_status", "no_index_entry")}
        g = groups.setdefault(doc["metadata_group"]["id"], {"fields": doc["metadata_group"]["fields"], "holes": []})
        g["holes"].append(hid)
        log.append({"file": f.name, "status": status, "hole_id": hid, "records": doc["coverage"]["n_records"],
                    "metrics": len(doc["metrics"]), "metric_counts": doc["metric_counts"],
                    "located": doc["location"]["status"], "identity_status": (collar or {}).get("identity_status"),
                    "quarantine_reasons": review["reasons"], "raw_tsg_found": hid in tsgs, "warnings": doc["warnings"]})
    catalog_meta = None
    if holes_index:
        catalog_meta = cat.write_catalog(holes_index, out / "_catalog", processed)
    manifest = {"schema_version": SCHEMA_VERSION, "pipeline_version": PIPELINE_VERSION,
                "queryable_holes": queryable,
                "packages": processed,
                "metadata_groups": groups,
                "rules": {"queryable": "only holes listed in queryable_holes may enter queries",
                          "metadata_groups": "values are compared or joined only within one metadata group",
                          "identity": "UI should show identity_status; 'needs_review' entries stay visible but flagged"},
                "catalog": catalog_meta, "log": log}
    (out / "manifest.json").write_text(json.dumps(jsonable(manifest), indent=1), encoding="utf-8")
    for e in log:
        print(f"{e['status']:22s} {e.get('hole_id', ''):12s} {e['file']}  " +
              (f"{e.get('records')} records, {e.get('metric_counts')}, {e.get('located')}, {e.get('identity_status')}"
               if e["status"].startswith("packaged") else e.get("reason", "")))
    print(f"metadata groups: {[(k, v['holes']) for k, v in groups.items()]}")
    if catalog_meta:
        print(f"catalog: {catalog_meta['n_entries']} entries, {catalog_meta['n_located']} located "
              f"({catalog_meta['n_located_by_collar']} by collar, {catalog_meta['n_located_by_index_only']} by index only), "
              f"{catalog_meta['n_with_summary_csv']} with summary CSV link, {catalog_meta['n_processed']} processed; "
              f"identity {catalog_meta['identity_status_counts']}; names {catalog_meta['name_check_counts']}; "
              f"reports {catalog_meta['report_check_counts']}; co-located flags {catalog_meta['n_co_located_within_5m']}")


if __name__ == "__main__":
    main()
