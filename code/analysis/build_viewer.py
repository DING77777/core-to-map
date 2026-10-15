"""Build the change viewer from whatever HyLogger files are in a folder.

  python build_viewer.py --data ..\\..\\data

Put the files anywhere under --data:
  SM_<hole>.csv                       required, one per hole (GSWA TSG Summary Mineral Log)
  HyLogger_Dataset_Package.sqlite     optional: adds company-log code changes for comparison

Every hole found is processed with the same settings; nothing is configured per hole.
Then open viewer/index.html in a browser (no server needed).

Author: Ding Qing
Date: 2026-10-15
"""
import argparse
import csv
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "scripts"))

from hylogger_pipeline.summary_csv import read_summary_csv  # noqa: E402
from hylogger_pipeline import boundaries as B  # noqa: E402

DEFAULT = (2, 2)                       # beta, minimum segment (m): chosen on CMDD001/002, tested on 40 holes
BETAS, MINS = (1, 2, 4, 8), (2, 3, 5)
TOP_GROUPS = 6
# Company logs filed with report 103450 are used for CMDD001/002 (the primary CMDD002 log has no codes).
LOG_COLLAR_OVERRIDE = {"CMDD001": 3663110, "CMDD002": 3663111}


def num(v):
    return float(v) if v is not None and not isinstance(v, str) else 0.0


def region_columns(hole, region):
    return [m["id"] for m in hole["registry"]
            if m["kind"] == "mineral_group_proportion" and m["id"].endswith(f"(System_{region})")]


def strips(hole, region):
    cols = region_columns(hole, region)
    recs = hole["records"]
    vals = {c: [num(r["values"].get(c)) if r["status"].get(c) == "ok" else 0.0 for r in recs] for c in cols}
    top = sorted(cols, key=lambda c: -sum(vals[c]))[:TOP_GROUPS]
    return {"names": [c.split("_(System_")[0] for c in top],
            "values": [[round(vals[c][i], 4) for c in top] for i in range(len(recs))]}


def describe(cand, settings_key):
    return {"depth": cand["depth_m"],
            "above": [cand["segment_above"]["from_m"], cand["segment_above"]["to_m"]],
            "below": [cand["segment_below"]["from_m"], cand["segment_below"]["to_m"]],
            "changes": [{"group": t["metric"].split("_(System_")[0], "region": "SWIR" if "SWIR" in t["metric"] else "TIR",
                         "above": round(t["mean_above"], 3), "below": round(t["mean_below"], 3)} for t in cand["top_changes"]]}


def log_changes(sqlite_path, hole_id, blocks):
    if not sqlite_path:
        return None
    try:
        con = sqlite3.connect(f"file:{Path(sqlite_path).as_posix()}?mode=ro", uri=True)
        row = con.execute("select WAMEX_CollarId from hylogger_dataset_index where NVCL_HoleName = ?", (hole_id,)).fetchone()
        con.close()
    except sqlite3.Error:
        return None
    collar = LOG_COLLAR_OVERRIDE.get(hole_id) or (int(row[0]) if row and str(row[0]).strip().isdigit() else None)
    if not collar:
        return None
    ref = B.reference_boundaries(sqlite_path, collar, blocks)
    return [r["depth_m"] for r in ref["boundaries"]]


def validation_lookup():
    path = HERE / "results" / "holes.csv"
    if not path.exists():
        return {}
    return {r["hole_id"]: r for r in csv.DictReader(open(path, encoding="utf-8"))}


def build(hole_path, sqlite_path, data_root, out, checks):
    hole = read_summary_csv(hole_path)
    hid = hole["hole_id"]
    if not hole["import_review"]["queryable"]:
        return hid, f"skipped: {', '.join(hole['import_review']['reasons'])}"
    settings, blocks = {}, None
    for beta in BETAS:
        for m in MINS:
            d = B.detect(hole, "composition36", beta, m)
            settings[f"{beta}-{m}"] = [describe(c, f"{beta}-{m}") for c in d["candidates"]]
            if (beta, m) == DEFAULT:
                blocks = d["blocks"]
    nearby = [settings[k] for k in (f"{DEFAULT[0] // 2 or 1}-{DEFAULT[1]}", f"{DEFAULT[0] * 2}-{DEFAULT[1]}", f"{DEFAULT[0]}-3")]
    for c in settings[f"{DEFAULT[0]}-{DEFAULT[1]}"]:
        c["stability"] = sum(any(abs(c["depth"] - x["depth"]) <= 1.0 for x in v) for v in nearby) / len(nearby)
    recs = hole["records"]
    data = {
        "hole": hid, "source": hole["source"]["filename"], "sha256": hole["source"]["sha256"],
        "from": float(recs[0]["from_m"]), "to": float(recs[-1]["to_m"]),
        "metres": [float(r["from_m"]) for r in recs],
        "gaps": [[float(g["from_m"]), float(g["to_m"])] for g in hole["gaps"]],
        "blocks": blocks, "swir": strips(hole, "SWIR"), "tir": strips(hole, "TIR"),
        "settings": settings, "default": f"{DEFAULT[0]}-{DEFAULT[1]}",
        "log": log_changes(sqlite_path, hid, blocks),
        "validation": checks.get(hid),
    }
    (out / "data" / f"{hid}.js").write_text("window.HOLE_DATA=window.HOLE_DATA||{};window.HOLE_DATA[" + json.dumps(hid)
                                          + "]=" + json.dumps(data, separators=(",", ":")) + ";\n", encoding="utf-8")
    return hid, f"{len(recs)} m, {len(settings[data['default']])} candidates" + (", log" if data["log"] is not None else "")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, type=Path, help="folder that holds the SM_<hole>.csv files (searched recursively)")
    ap.add_argument("--sqlite", type=Path, help="HyLogger_Dataset_Package.sqlite (found automatically under --data if omitted)")
    ap.add_argument("--out", type=Path, default=HERE / "viewer")
    ap.add_argument("--holes", nargs="*", help="only these hole names")
    a = ap.parse_args()
    sqlite_path = a.sqlite or next(iter(sorted(a.data.rglob("HyLogger_Dataset_Package.sqlite"))), None)
    (a.out / "data").mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "viewer.css", "viewer-data.js", "viewer.js"):
        shutil.copyfile(HERE / "viewer_src" / name, a.out / name)
    checks = validation_lookup()
    seen, index = set(), []
    for path in sorted(a.data.rglob("SM_*.csv")):
        hid = path.stem[3:]
        if hid in seen or " " in path.stem or (a.holes and hid not in a.holes):
            continue
        seen.add(hid)
        try:
            hid, note = build(path, sqlite_path, a.data, a.out, checks)
        except Exception as exc:  # one bad file must not stop the others
            note = f"failed: {exc}"
        print(f"{hid:12s} {note}")
        if not note.startswith(("skipped", "failed")):
            index.append(hid)
    existing = sorted({p.stem for p in (a.out / "data").glob("*.js") if p.stem != "index"})
    (a.out / "data" / "index.js").write_text("window.HOLE_INDEX=" + json.dumps(existing) + ";\n", encoding="utf-8")
    print(f"{len(index)} holes built this run, {len(existing)} in the viewer. Open {a.out / 'index.html'}")


if __name__ == "__main__":
    main()
