"""Scan-level analysis for every hole that has both an SM CSV and a raw TSG package.

  python scripts/run_scan_analysis.py --inputs ../../data/nvcl_wa --out work/analyses [--pytsg-path DIR]

Writes work/analyses/<hole>/analyses.json and scan_stats.json. Then run run_pipeline.py with
--analyses work/analyses to merge them into the hole packages (scan_stats.json is copied too).
Requires numpy, pandas and GSWA pytsg (MIT, github.com/Geological-Survey-of-Western-Australia/pytsg).

Author: Ding Qing
Date: 2026-10-15
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", nargs="+", required=True)
    ap.add_argument("--out", default="work/analyses")
    ap.add_argument("--pytsg-path", help="folder containing the pytsg package, if not installed")
    a = ap.parse_args()
    if a.pytsg_path:
        sys.path.insert(0, a.pytsg_path)
    from run_pipeline import find_inputs
    from hylogger_pipeline.summary_csv import read_summary_csv
    from hylogger_pipeline.package import jsonable
    from hylogger_pipeline import tsg_scans
    csvs, tsgs = find_inputs(a.inputs)
    out = Path(a.out)
    for f in csvs:
        hole = read_summary_csv(f)
        hid = hole["hole_id"]
        if hid not in tsgs:
            print(f"{hid}: no raw TSG package found - summary-only package")
            continue
        an_path = out / hid / "analyses.json"
        existing = json.loads(an_path.read_text(encoding="utf-8")) if an_path.exists() else {}
        existing.update(tsg_scans.process(tsgs[hid], hole, out))
        an_path.parent.mkdir(parents=True, exist_ok=True)
        an_path.write_text(json.dumps(jsonable(existing), indent=1), encoding="utf-8")
        for col, r in existing["summary_reproduction"].items():
            if not isinstance(r, dict):
                continue
            key = [k for k in r if k.startswith("n_bins_matched")][0]
            print(f"{hid} {col:12s} reproduced {r[key]}/{r['n_bins_compared']} bins, max |diff| = {r['max_abs_diff']:.6g} {r['unit']}")


if __name__ == "__main__":
    main()
