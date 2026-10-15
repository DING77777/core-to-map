"""Candidate spectral change positions vs company-log code changes: development / locked test protocol.

  python scripts/run_boundary_experiment.py --sqlite <interim.sqlite> --out work/boundaries       --hole CMDD001=<SM csv>=3663110 --hole CMDD002=<SM csv>=3663111 ... --dev CMDD001,CMDD002

Protocol (fixed in this file before any test-hole log was compared):
1. Reference rule, feature sets, parameter grid, tolerance and baselines are as in
   hylogger_pipeline/boundaries.py and below.
2. For each feature set, (beta, min_size) is chosen on the DEVELOPMENT holes only, by pooled F1 at
   1 m tolerance; ties -> larger beta, then larger min_size (fewer candidates).
3. Parameters are locked and applied once to every TEST hole. Test logs are never used to choose
   parameters or the number of candidates.
4. composition36 is the declared primary feature set; the others are comparisons.
5. A full-grid sensitivity table on the test holes is written afterwards and labelled post hoc.

Author: Ding Qing
Date: 2026-10-15
"""
import argparse
import csv
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from hylogger_pipeline.summary_csv import read_summary_csv  # noqa: E402
from hylogger_pipeline import boundaries as B  # noqa: E402
from hylogger_pipeline.package import jsonable  # noqa: E402

GRID_BETA = [1, 2, 4, 8]
GRID_MIN = [2, 3, 5]
TOLS = [0.5, 1.0, 2.0]
MAIN_TOL = 1.0
PRIMARY = "composition36"
N_RANDOM = 1000


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pooled(rows):
    p = sum(r["n_candidates"] for r in rows); r_ = sum(r["n_reference"] for r in rows); k = sum(r["n_matched"] for r in rows)
    prec = k / p if p else None; rec = k / r_ if r_ else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else 0.0
    return {"n_candidates": p, "n_reference": r_, "n_matched": k, "precision": prec, "recall": rec, "f1": f1}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hole", action="append", required=True, help="HOLE=summary_csv=collar_id")
    ap.add_argument("--sqlite", required=True)
    ap.add_argument("--dev", required=True, help="comma-separated development holes")
    ap.add_argument("--out", default="work/boundaries")
    ap.add_argument("--seed", type=int, default=20261015)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-seed{a.seed}"
    dev = a.dev.split(",")
    spec = {}
    for x in a.hole:
        h, p, c = x.split("=")
        spec[h] = {"csv": Path(p), "collar": int(c)}
    holes = {h: read_summary_csv(s["csv"]) for h, s in spec.items()}
    test = [h for h in spec if h not in dev]
    db_sha = sha(a.sqlite)

    # references (frozen rule), computed on the usable blocks of the primary feature set
    refs, dets_cache = {}, {}

    def det(h, fs, beta, m):
        key = (h, fs, beta, m)
        if key not in dets_cache:
            dets_cache[key] = B.detect(holes[h], fs, beta, m)
        return dets_cache[key]

    for h in spec:
        d0 = det(h, PRIMARY, GRID_BETA[0], GRID_MIN[0])
        refs[h] = B.reference_boundaries(a.sqlite, spec[h]["collar"], d0["blocks"])

    def ref_depths(h):
        return [r["depth_m"] for r in refs[h]["boundaries"]]

    # 1) development selection
    selection = {}
    for fs in B.FEATURE_SETS:
        table = []
        for beta in GRID_BETA:
            for m in GRID_MIN:
                rows = [B.score([c["depth_m"] for c in det(h, fs, beta, m)["candidates"]], ref_depths(h), MAIN_TOL) for h in dev]
                table.append({"beta": beta, "min_size_m": m, **pooled(rows)})
        best = max(table, key=lambda t: (t["f1"], t["beta"], t["min_size_m"]))
        selection[fs] = {"chosen": {"beta": best["beta"], "min_size_m": best["min_size_m"]},
                         "dev_holes": dev, "dev_grid": table,
                         "rule": "max pooled F1 at 1 m on development holes; ties -> larger beta, larger min_size"}
        print(f"[dev] {fs:14s} chosen beta={best['beta']} min_size={best['min_size_m']} dev pooled F1={best['f1']:.3f} "
              f"(P={best['precision']}, R={best['recall']}, cand={best['n_candidates']}, ref={best['n_reference']})")

    # 2) locked evaluation on every hole (dev holes reported as development, not as tests)
    rng = np.random.default_rng(a.seed)
    results = {fs: {} for fs in B.FEATURE_SETS}
    rand_pool = {fs: [] for fs in B.FEATURE_SETS}
    for fs in B.FEATURE_SETS:
        beta, m = selection[fs]["chosen"]["beta"], selection[fs]["chosen"]["min_size_m"]
        draws_by_hole = {}
        for h in spec:
            d = det(h, fs, beta, m)
            cands = [c["depth_m"] for c in d["candidates"]]
            rd = ref_depths(h)
            scores = {str(t): B.score(cands, rd, t) for t in TOLS}
            allowed = B.allowed_positions(d["froms"], d["block_index"], m)
            draws = []
            for _ in range(N_RANDOM):
                pl = B.random_placement(allowed, len(cands), m, rng)
                draws.append(B.score(pl, rd, MAIN_TOL) if pl is not None else None)
            draws = [x for x in draws if x is not None]
            draws_by_hole[h] = draws
            f1s = np.array([x["f1"] or 0.0 for x in draws]) if draws else np.array([])
            mf1 = scores[str(MAIN_TOL)]["f1"] or 0.0
            eq = B.score(B.equal_spacing(d["blocks"], len(cands), m), rd, MAIN_TOL)
            wcol = d["preprocessing"]["columns"].index("2200W_AlOH") if "2200W_AlOH" in d["preprocessing"]["columns"] else None
            if wcol is None:
                fr, tr, raw_w, _, us, _ = B.build_matrix(holes[h], "aloh2200w")
                raw_col, bidx = raw_w[:, 0], B.usable_blocks(fr, tr, us)
            else:
                raw_col, bidx = d["raw"][:, wcol], d["block_index"]
            win = B.score(B.window_difference(d["froms"], raw_col, bidx, len(cands), m), rd, MAIN_TOL)
            results[fs][h] = {
                "role": "development" if h in dev else "test",
                "params": d["params"], "blocks": d["blocks"],
                "candidates": d["candidates"], "scores": scores,
                "baselines": {
                    "random_same_count": {"n_draws": len(draws), "seed": a.seed,
                                          "f1_mean": float(f1s.mean()) if len(f1s) else None,
                                          "f1_p95": float(np.percentile(f1s, 95)) if len(f1s) else None,
                                          "p_value_f1_ge_model": (float((1 + (f1s >= mf1 - 1e-12).sum()) / (1 + len(f1s))) if len(f1s) else None),
                                          "constraints": "same usable blocks, same count, same minimum spacing"},
                    "equal_spacing_same_count": {k: eq[k] for k in ("n_matched", "precision", "recall", "f1")},
                    "window_difference_2200W_same_count": dict({k: win[k] for k in ("n_matched", "precision", "recall", "f1")},
                                                               window_m=m)},
            }
        # pooled over test holes: model and random (draw i of every hole combined)
        tm = pooled([results[fs][h]["scores"][str(MAIN_TOL)] for h in test])
        n_draw = min(len(draws_by_hole[h]) for h in test)
        rf = np.array([pooled([draws_by_hole[h][i] for h in test])["f1"] for i in range(n_draw)])
        results[fs]["_test_pooled"] = {"model": tm, "random_f1_mean": float(rf.mean()), "random_f1_p95": float(np.percentile(rf, 95)),
                                       "p_value": float((1 + (rf >= tm["f1"] - 1e-12).sum()) / (1 + len(rf))),
                                       "equal_spacing": pooled([B.score(B.equal_spacing(results[fs][h]["blocks"], len(results[fs][h]["candidates"]), selection[fs]["chosen"]["min_size_m"]), ref_depths(h), MAIN_TOL) for h in test]),
                                       "window_difference_2200W": pooled([dict(results[fs][h]["baselines"]["window_difference_2200W_same_count"],
                                                                               n_candidates=len(results[fs][h]["candidates"]),
                                                                               n_reference=len(ref_depths(h))) for h in test])}
        tp = results[fs]["_test_pooled"]
        print(f"[test] {fs:14s} pooled F1={tm['f1']:.3f} P={tm['precision']:.3f} R={tm['recall']:.3f} "
              f"(cand {tm['n_candidates']}, ref {tm['n_reference']}, matched {tm['n_matched']}) | random F1 mean {tp['random_f1_mean']:.3f} "
              f"p95 {tp['random_f1_p95']:.3f} p={tp['p_value']:.4f} | equal-spacing F1 {tp['equal_spacing']['f1']:.3f} "
              f"| window-2200W F1 {tp['window_difference_2200W']['f1']:.3f}")

    # 3) parameter stability of the primary candidates (not a probability)
    beta, m = selection[PRIMARY]["chosen"]["beta"], selection[PRIMARY]["chosen"]["min_size_m"]
    variants = [(beta * 0.5, m), (beta * 2, m), (beta, max(2, m - 1)), (beta, m + 1)]
    for h in spec:
        vc = [[c["depth_m"] for c in B.detect(holes[h], PRIMARY, vb, vm)["candidates"]] for vb, vm in variants]
        for c in results[PRIMARY][h]["candidates"]:
            c["parameter_stability"] = sum(any(abs(c["depth_m"] - x) <= 1.0 for x in v) for v in vc) / len(vc)
            c["nearest_log_code_change_m"] = min((r for r in ref_depths(h)), key=lambda r: abs(r - c["depth_m"]), default=None)

    # 4) post-hoc sensitivity on test holes (NOT used for selection)
    posthoc = []
    for fs in B.FEATURE_SETS:
        for b_ in GRID_BETA:
            for m_ in GRID_MIN:
                posthoc.append({"feature_set": fs, "beta": b_, "min_size_m": m_,
                                **pooled([B.score([c["depth_m"] for c in det(h, fs, b_, m_)["candidates"]], ref_depths(h), MAIN_TOL) for h in test])})

    import scipy
    provenance = {"run_id": run_id, "seed": a.seed, "sqlite_sha256": db_sha,
                  "summary_csv_sha256": {h: holes[h]["source"]["sha256"] for h in spec},
                  "log_collar_ids": {h: spec[h]["collar"] for h in spec},
                  "software": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
                  "method_version": "hylogger-boundaries/0.1"}
    caveats = [
        "Company-log code changes are an interpretation with each company's own codes and logging detail; not ground truth.",
        "A candidate spectral change is not a confirmed geological contact or stratigraphic boundary.",
        "CMDD001/CMDD002 use the alternate WAMEX report 103450 logs (collars 3663110/3663111): the primary CMDD002 log has no codes.",
        "Development holes CMDD001/CMDD002 had been inspected earlier in the project; their scores are not independent tests.",
        "TBDD126/127/128 are one project, 60-164 m apart: three related cases, not three independent generalisation tests.",
        "Dense log changes (e.g. TBDD127: several changes within 2 m) make chance matches likely at 1 m tolerance; compare with the random baseline.",
        "1 m summaries cannot resolve logged units thinner than about 1 m.",
        "Parameter stability = share of 4 nearby parameter settings that keep a candidate within 1 m; it is not a probability of being right.",
    ]
    summary = {"protocol": __doc__, "provenance": provenance, "primary_feature_set": PRIMARY,
               "grid": {"beta": GRID_BETA, "min_size_m": GRID_MIN}, "tolerances_m": TOLS, "main_tolerance_m": MAIN_TOL,
               "development_holes": dev, "test_holes": test, "selection": selection,
               "test_pooled": {fs: results[fs]["_test_pooled"] for fs in B.FEATURE_SETS},
               "posthoc_sensitivity_test_holes": posthoc, "caveats": caveats,
               "references": {h: {k: v for k, v in refs[h].items() if k != "logged_coded_ranges"} for h in spec}}
    (out / "boundary_experiment_summary.json").write_text(json.dumps(jsonable(summary), indent=1), encoding="utf-8")

    # per-hole files for the viewer
    for h in spec:
        r = results[PRIMARY][h]
        doc = {"hole_id": h,
               "display_name": "Candidate spectral changes vs company-log code changes",
               "role": r["role"], "method": {"segmentation": "exact optimal partitioning, L2 cost (PELT-equivalent optimum)",
                                            "feature_set": PRIMARY, "preprocessing": B.detect(holes[h], PRIMARY, beta, m)["preprocessing"],
                                            "params": r["params"], "selected_on": dev},
               "usable_blocks": r["blocks"],
               "excluded_ranges": "depths outside usable_blocks (source gaps, unusable records, beyond summary coverage)",
               "candidates": r["candidates"],
               "reference": {"source": "WAMEX dh geology (interim package)", "collar_id": spec[h]["collar"],
                             **{k: v for k, v in refs[h].items() if k != "logged_coded_ranges"},
                             "logged_coded_ranges": refs[h]["logged_coded_ranges"]},
               "scores": r["scores"], "baselines": r["baselines"],
               "comparison_feature_sets": {fs: {"params": selection[fs]["chosen"],
                                                "score_1m": {k: results[fs][h]["scores"][str(MAIN_TOL)][k] for k in ("n_candidates", "n_matched", "precision", "recall", "f1")}}
                                           for fs in B.FEATURE_SETS if fs != PRIMARY},
               "terms": {"candidate": "candidate spectral change (algorithm output)",
                         "reference": "company-log code change (reference, not ground truth)",
                         "review": "expert review is recorded separately"},
               "provenance": provenance, "caveats": caveats}
        (out / h).mkdir(exist_ok=True)
        (out / h / "boundaries.json").write_text(json.dumps(jsonable(doc), separators=(",", ":")), encoding="utf-8")

    with open(out / "boundary_results_per_hole.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["feature_set", "hole", "role", "beta", "min_size_m", "n_candidates", "n_reference", "n_matched_1m",
                    "precision_1m", "recall_1m", "f1_1m", "f1_0.5m", "f1_2m", "mean_abs_offset_1m",
                    "random_f1_mean", "random_f1_p95", "random_p", "equal_spacing_f1", "window_2200W_f1"])
        for fs in B.FEATURE_SETS:
            for h in spec:
                r = results[fs][h]; s = r["scores"]; bl = r["baselines"]
                w.writerow([fs, h, r["role"], r["params"]["beta"], r["params"]["min_size_m"], s["1.0"]["n_candidates"],
                            s["1.0"]["n_reference"], s["1.0"]["n_matched"], s["1.0"]["precision"], s["1.0"]["recall"],
                            s["1.0"]["f1"], s["0.5"]["f1"], s["2.0"]["f1"], s["1.0"]["mean_abs_offset_m"],
                            bl["random_same_count"]["f1_mean"], bl["random_same_count"]["f1_p95"],
                            bl["random_same_count"]["p_value_f1_ge_model"], bl["equal_spacing_same_count"]["f1"],
                            bl["window_difference_2200W_same_count"]["f1"]])
    for h in spec:
        r = results[PRIMARY][h]; s = r["scores"]["1.0"]; bl = r["baselines"]["random_same_count"]
        f = lambda x: "n/a" if x is None else f"{x:.2f}"  # noqa: E731
        print(f"  {PRIMARY} {h:8s} {r['role']:11s} cand {s['n_candidates']:3d} ref {s['n_reference']:3d} match {s['n_matched']:3d} "
              f"P {f(s['precision'])} R {f(s['recall'])} F1 {f(s['f1'])} | random F1 {f(bl['f1_mean'])} p95 {f(bl['f1_p95'])} p={f(bl['p_value_f1_ge_model'])}")


if __name__ == "__main__":
    main()
