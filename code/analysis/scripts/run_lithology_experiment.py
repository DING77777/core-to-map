"""Binary comparison experiment against company logs (felsic vs mafic), hole-wise.

  python scripts/run_lithology_experiment.py --tsg CMDD001=<dir> --tsg CMDD002=<dir>       --collar CMDD001=3663110 --collar CMDD002=3663111 --sqlite <interim.sqlite> --out work/analyses

Writes work/analyses/<hole>/lithology.json and merges a summary into analyses.json.
The exported per-metre predictions come from the model named in `exported_model` (SWIR only by
default, the best-scoring variant); its scores are reported next to it. Other variants are
reported for comparison only. The fitted model object is not saved; re-running with the same
inputs, seed and library versions should reproduce it.

Author: Ding Qing
Date: 2026-10-15
"""
import argparse
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tsg", action="append", required=True, help="HOLE=folder with raw TSG files")
    ap.add_argument("--collar", action="append", required=True, help="HOLE=WAMEX CollarId whose log supplies labels")
    ap.add_argument("--sqlite", required=True)
    ap.add_argument("--out", default="work/analyses")
    ap.add_argument("--pytsg-path")
    ap.add_argument("--seed", type=int, default=20261015)
    ap.add_argument("--export-model", default="swir", choices=["swir", "tir", "swir+tir"])
    a = ap.parse_args()
    if a.pytsg_path:
        sys.path.insert(0, a.pytsg_path)
    import sklearn
    import pandas as pd
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.tree import DecisionTreeClassifier
    from sklearn.metrics import balanced_accuracy_score, recall_score
    from hylogger_pipeline import lithology as L
    from hylogger_pipeline.package import jsonable

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-seed{a.seed}"
    rf_config = {"estimator": "sklearn.ensemble.RandomForestClassifier", "n_estimators": 300, "min_samples_leaf": 5,
                 "class_weight": "balanced", "random_state": a.seed}
    tsg = dict(x.split("=", 1) for x in a.tsg)
    collar = dict(x.split("=", 1) for x in a.collar)
    holes = sorted(tsg)
    data, provenance = {}, {"run_id": run_id, "seed": a.seed, "rf_config": rf_config,
                            "software": {"python": platform.python_version(), "numpy": np.__version__,
                                         "pandas": pd.__version__, "scikit_learn": sklearn.__version__,
                                         "pytsg_source_commit": "481f5faf6e1153791b849d4216a47f86f7db20ce"},
                            "sqlite_sha256": sha(a.sqlite), "label_collar_ids": collar, "input_files": {}}
    for h in holes:
        d = Path(tsg[h])
        provenance["input_files"][h] = {n: {"bytes": (d / n).stat().st_size, "sha256": sha(d / n)}
                                        for n in (f"{h}_tsg.tsg", f"{h}_tsg.bip", f"{h}_tsg_tir.tsg", f"{h}_tsg_tir.bip")}
        nir, tir = L.load_hole(d, h)
        depth = L._num(nir.scalars["Depth (m)"])
        lab, log = L.labels_from_log(a.sqlite, int(collar[h]), depth)
        mask = (L._num(nir.scalars["Final Mask"]) == 1) & (L._num(tir.scalars["Final Mask"]) == 1)
        keep = mask & np.isin(lab, ["felsic", "mafic"])
        data[h] = {"depth": depth, "lab": lab, "keep": keep, "mask": mask,
                   "X": {w: L.features(nir, tir, w) for w in ("swir", "tir", "swir+tir")},
                   "grp": [nir.scalars["Grp1 sTSAS"], tir.scalars["Grp1 sjCLST"]],
                   "log": log}
        u, c = np.unique(lab[keep], return_counts=True)
        print(h, "usable scans", int(keep.sum()), dict(zip(u, c.tolist())))

    results = {}
    for tr in holes:
        for te in holes:
            if tr == te:
                continue
            A, B = data[tr], data[te]
            ytr, yte = A["lab"][A["keep"]], B["lab"][B["keep"]]
            key = f"train_{tr}__test_{te}"
            res = {"n_train_scans": int(len(ytr)), "n_test_scans": int(len(yte)),
                   "test_class_share": {k: float(np.mean(yte == k)) for k in ("felsic", "mafic")},
                   "metric": "balanced accuracy at SCAN level (mean of felsic recall and mafic recall)"}
            for w in ("swir", "tir", "swir+tir"):
                m = RandomForestClassifier(n_estimators=300, min_samples_leaf=5, class_weight="balanced",
                                           n_jobs=-1, random_state=a.seed)
                m.fit(A["X"][w][A["keep"]], ytr)
                p = m.predict(B["X"][w][B["keep"]])
                res[f"random_forest_{w}"] = {"balanced_accuracy": float(balanced_accuracy_score(yte, p)),
                                             "recall_felsic": float(recall_score(yte, p, pos_label="felsic")),
                                             "recall_mafic": float(recall_score(yte, p, pos_label="mafic"))}
                if w == a.export_model:
                    prob = np.full(len(B["depth"]), np.nan)
                    mi = list(m.classes_).index("mafic")
                    prob[B["mask"]] = m.predict_proba(B["X"][w][B["mask"]])[:, mi]
                    B["p_mafic"] = prob
            gtr, cats = L.group_onehot([g[A["keep"]] for g in A["grp"]])
            gte, _ = L.group_onehot([g[B["keep"]] for g in B["grp"]], cats)
            for depth_ in (1, 3):
                t = DecisionTreeClassifier(max_depth=depth_, class_weight="balanced", random_state=a.seed).fit(gtr, ytr)
                res[f"shallow_tree_on_dominant_group_onehot_depth{depth_}"] = {
                    "balanced_accuracy": float(balanced_accuracy_score(yte, t.predict(gte)))}
            res["majority_class_baseline"] = {"balanced_accuracy": 0.5}
            results[key] = res
            print(key, {k: round(v["balanced_accuracy"], 3) for k, v in res.items() if isinstance(v, dict) and "balanced_accuracy" in v})

    out = Path(a.out)
    caveats = [
        "Two holes from one project only; scores do not generalise to other areas or companies.",
        "Only 22 logged intervals in the scanned ranges (7 + 15), 9 of them mafic: few independent units despite many scans.",
        "Labels are company log intervals (report 103450), coarse and interpretive; code dictionary not obtained.",
        "Log depth vs scan depth alignment not independently checked.",
        "Final Mask == 1 used as an experimental scan filter; its meaning is not verified.",
        "Felsic/mafic is a deliberately simple two-class target; not a lithology map, not mineralisation.",
    ]
    for h in holes:
        B = data[h]
        other = [x for x in holes if x != h][0]
        bins = []
        lo, hi = np.floor(np.nanmin(B["depth"])), np.ceil(np.nanmax(B["depth"]))
        for f in np.arange(lo, hi):
            sel = (B["depth"] > f) & (B["depth"] <= f + 1) & B["mask"]
            if not sel.any():
                continue
            pm = B["p_mafic"][sel]
            labs = [x for x in B["lab"][sel] if x in ("felsic", "mafic")]
            logged = max(set(labs), key=labs.count) if labs else None
            share = (labs.count(logged) / len(labs)) if labs else None
            model = "mafic" if np.nanmean(pm) >= 0.5 else "felsic"
            bins.append({"from_m": float(f), "to_m": float(f + 1), "n_scans": int(sel.sum()),
                         "p_mafic_mean": float(np.nanmean(pm)), "model_label": model,
                         "logged_label": logged, "logged_label_share": share,
                         "agree": (None if logged is None else model == logged)})
        compared = [b for b in bins if b["agree"] is not None]
        n_agree = sum(1 for b in compared if b["agree"])
        scores = results[f"train_{other}__test_{h}"]
        doc = {"hole_id": h,
               "display_name": "Binary comparison experiment against company logs (felsic vs mafic)",
               "task": "felsic vs mafic from scan spectra",
               "exported_model": f"random_forest_{a.export_model}", "trained_on": other,
               "exported_model_scores": scores[f"random_forest_{a.export_model}"],
               "scan_bin_membership": "(from_m, to_m]",
               "label_source": "WAMEX dh geology, report 103450 codes FRG/FAG->felsic, GAM->mafic",
               "metre_agreement": {"agree": n_agree, "compared": len(compared),
                                   "note": "per-metre majority label vs mean probability; different denominator from scan-level scores"},
               "validation_status": "hole-wise cross-check on two holes only",
               "method_version": "hylogger-pipeline/0.2",
               "provenance": provenance, "bins_1m": bins, "caveats": caveats}
        (out / h).mkdir(parents=True, exist_ok=True)
        (out / h / "lithology.json").write_text(json.dumps(jsonable(doc), separators=(",", ":")), encoding="utf-8")
        an_path = out / h / "analyses.json"
        an = json.loads(an_path.read_text(encoding="utf-8")) if an_path.exists() else {}
        an["lithology_model"] = {k: doc[k] for k in ("display_name", "task", "exported_model", "trained_on",
                                                   "exported_model_scores", "metre_agreement", "label_source",
                                                   "validation_status", "method_version", "caveats")}
        an["lithology_model"].update(file="lithology.json", all_scores_for_comparison=scores, run_id=run_id)
        an_path.write_text(json.dumps(jsonable(an), indent=1), encoding="utf-8")
        print(h, f"metre agreement {n_agree}/{len(compared)} (exported model {a.export_model})")


if __name__ == "__main__":
    main()
