"""Candidate spectral change positions along a hole, compared with company-log code changes.

Optional analysis module (needs numpy and scipy). The viewer must work without it.

Terms (kept deliberately modest):
* candidate spectral change  - algorithm output: a depth where the 1 m summary values change and
                               stay changed (a change point). Not a confirmed geological contact.
* company-log code change    - reference: a depth where two touching company-log intervals carry
                               different non-empty codes. An interpretation, not ground truth.
* expert review              - recorded separately; this module never decides it.

Method (fixed before evaluation):
* Input: 1 m summary records of one hole, in contiguous valid blocks. Segmentation never crosses
  a source gap or a record whose chosen features are not all usable.
* Feature sets (declared, not tuned on test logs):
    composition36 - the 36 mineral-group proportions (System SWIR + TIR, quality columns excluded).
                    Source N.A. ("not detected or below threshold") is encoded as 0 for the
                    distance ONLY; per bin and region the detected groups already sum to 1, so 0
                    is the value consistent with the source's own normalisation. Blank / invalid
                    tokens make the record unusable. Raw proportions, no rescaling (same unit).
    scalars6      - 2200W_AlOH, 2200D_AlOH, 2250W_FeOH, 2250D_FeOH, 1900D_Water, VIS-SWIR_Albedo
                    (numeric in every record of all 8 inspected holes). Mixed units, so each column
                    is robust-scaled within the hole: (x - median) / IQR.
    aloh2200w     - 2200W_AlOH only, robust-scaled. Simple single-indicator comparison.
* Segmentation: exact optimal partitioning with an L2 (within-segment sum of squares) cost,
  a minimum segment length and a per-change penalty (the optimum PELT also finds).
  Penalty = beta * sigma2 * ln(n): sigma2 = median over adjacent records of ||x[i+1]-x[i]||^2 / 2
  (a label-free, robust within-segment noise estimate), n = usable records in the hole.
* Evaluation: one-to-one matching in metres, |candidate - reference| <= tolerance; maximum number of
  matches first, then minimum total offset (scipy linear_sum_assignment with a large cost for
  out-of-tolerance pairs). Precision, recall, F1 and offsets per hole.
* Baselines with the SAME number of candidates, the same usable blocks and the same minimum
  spacing: random placement (repeated, fixed seed), equal spacing, and a window-difference
  detector on 2200W_AlOH alone.

Author: Ding Qing
Date: 2026-10-15
"""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import numpy as np

SCALARS6 = ["2200W_AlOH", "2200D_AlOH", "2250W_FeOH", "2250D_FeOH", "1900D_Water", "VIS-SWIR_Albedo"]
FEATURE_SETS = ("composition36", "scalars6", "aloh2200w")


# ----------------------------------------------------------------------------- features
def feature_columns(hole, feature_set):
    if feature_set == "composition36":
        return [m["id"] for m in hole["registry"] if m["kind"] == "mineral_group_proportion"]
    if feature_set == "scalars6":
        return list(SCALARS6)
    if feature_set == "aloh2200w":
        return ["2200W_AlOH"]
    raise ValueError(feature_set)


def build_matrix(hole, feature_set):
    """Return depths (from,to), raw matrix, scaled matrix, usable mask and a preprocessing record."""
    cols = feature_columns(hole, feature_set)
    recs = hole["records"]
    n, d = len(recs), len(cols)
    raw = np.full((n, d), np.nan)
    usable = np.ones(n, bool)
    na_as_zero = feature_set == "composition36"
    n_na_encoded = 0
    for i, r in enumerate(recs):
        for j, c in enumerate(cols):
            st = r["status"].get(c, "absent")
            if st == "ok":
                raw[i, j] = float(r["values"][c])
            elif st == "source_na" and na_as_zero:
                raw[i, j] = 0.0
                n_na_encoded += 1
            else:
                usable[i] = False
    scaled = raw.copy()
    prep = {"feature_set": feature_set, "columns": cols, "n_columns": d}
    if feature_set == "composition36":
        prep["scaling"] = "none (all columns are 0-1 proportions)"
        prep["missing_policy"] = ("source N.A. encoded as 0 for the distance only "
                                  "(detected groups sum to 1 per bin and region); blank/invalid -> record unusable")
        prep["n_na_encoded_as_zero"] = n_na_encoded
    else:
        med = np.nanmedian(raw[usable], axis=0) if usable.any() else np.zeros(d)
        q75, q25 = (np.nanpercentile(raw[usable], [75, 25], axis=0) if usable.any() else (np.ones(d), np.zeros(d)))
        iqr = np.where((q75 - q25) > 0, q75 - q25, 1.0)
        scaled = (raw - med) / iqr
        prep["scaling"] = "robust: (x - median) / IQR within the hole"
        prep["median"] = [float(x) for x in med]
        prep["iqr"] = [float(x) for x in iqr]
        prep["missing_policy"] = "any non-numeric value in these columns -> record unusable (none occurred in the 8 inspected holes)"
    froms = np.array([float(r["from_m"]) for r in recs])
    tos = np.array([float(r["to_m"]) for r in recs])
    return froms, tos, raw, scaled, usable, prep


def usable_blocks(froms, tos, usable):
    """Contiguous runs of usable, touching records -> list of (i0, i1) with i1 exclusive."""
    blocks, i0 = [], None
    for i in range(len(froms)):
        ok = usable[i]
        touching = i > 0 and abs(froms[i] - tos[i - 1]) < 1e-9 and usable[i - 1]
        if ok and (i0 is None or not touching):
            if i0 is not None:
                blocks.append((i0, i))
            i0 = i
        elif not ok and i0 is not None:
            blocks.append((i0, i)); i0 = None
    if i0 is not None:
        blocks.append((i0, len(froms)))
    return blocks


def noise_sigma2(X, blocks):
    diffs = [np.sum(np.diff(X[a:b], axis=0) ** 2, axis=1) for a, b in blocks if b - a > 1]
    diffs = np.concatenate(diffs) if diffs else np.array([0.0])
    return float(np.median(diffs) / 2.0)


# ----------------------------------------------------------------------------- segmentation
def optimal_partition(X, pen, min_size):
    """Exact minimiser of sum_segments L2cost + pen * (#segments - 1), segments >= min_size.

    Returns the change indices (start index of each new segment, excluding 0).
    O(n^2 d) with cumulative sums; equal to what PELT returns for the L2 cost.
    """
    n = len(X)
    if n < 2 * min_size:
        return []
    X = np.asarray(X, float)
    c1 = np.vstack([np.zeros((1, X.shape[1])), np.cumsum(X, axis=0)])
    c2 = np.concatenate([[0.0], np.cumsum(np.sum(X ** 2, axis=1))])
    F = np.full(n + 1, np.inf); F[0] = -pen
    last = np.zeros(n + 1, int)
    for t in range(min_size, n + 1):
        s = np.arange(0, t - min_size + 1)
        s = s[(s == 0) | (s >= min_size)]
        s = s[np.isfinite(F[s])]
        L = (t - s)[:, None]
        cost = (c2[t] - c2[s]) - np.sum((c1[t] - c1[s]) ** 2, axis=1) / L[:, 0]
        tot = F[s] + cost + pen
        k = int(np.argmin(tot))
        F[t] = tot[k]; last[t] = s[k]
    cps, t = [], n
    while t > 0:
        s = last[t]
        if s > 0:
            cps.append(int(s))
        t = s
    return sorted(cps)


def detect(hole, feature_set, beta, min_size):
    froms, tos, raw, X, usable, prep = build_matrix(hole, feature_set)
    blocks = usable_blocks(froms, tos, usable)
    n_use = int(sum(b - a for a, b in blocks))
    sigma2 = noise_sigma2(X, blocks)
    pen = beta * sigma2 * math.log(max(n_use, 2))
    cands = []
    for a, b in blocks:
        cps = optimal_partition(X[a:b], pen, min_size)
        edges = [a] + [a + c for c in cps] + [b]
        for k in range(1, len(edges) - 1):
            l0, l1, r1 = edges[k - 1], edges[k], edges[k + 1]
            left, right = raw[l0:l1].mean(axis=0), raw[l1:r1].mean(axis=0)
            delta = right - left
            order = np.argsort(-np.abs(delta))[:3]
            cands.append({
                "depth_m": float(froms[l1]),
                "index": int(l1),
                "segment_above": {"from_m": float(froms[l0]), "to_m": float(froms[l1])},
                "segment_below": {"from_m": float(froms[l1]), "to_m": float(tos[r1 - 1])},
                "top_changes": [{"metric": prep["columns"][j], "mean_above": float(left[j]),
                                 "mean_below": float(right[j]), "change": float(delta[j])} for j in order],
            })
    blocks_m = [{"from_m": float(froms[a]), "to_m": float(tos[b - 1]), "n_records": int(b - a)} for a, b in blocks]
    params = {"beta": beta, "min_size_m": min_size, "sigma2": sigma2, "n_usable_records": n_use,
              "penalty": pen, "penalty_rule": "beta * sigma2 * ln(n_usable_records)"}
    return {"candidates": cands, "blocks": blocks_m, "block_index": blocks, "params": params,
            "preprocessing": prep, "froms": froms, "tos": tos, "raw": raw}


def allowed_positions(froms, block_index, min_size):
    """Depths where a change may sit: inside a block, >= min_size records from both block ends."""
    pos = []
    for a, b in block_index:
        for k in range(a + min_size, b - min_size + 1):
            pos.append((float(froms[k]), (a, b)))
    return pos


# ----------------------------------------------------------------------------- reference
def reference_boundaries(sqlite_path, collar_id, blocks_m):
    """Company-log code changes strictly inside the summary's contiguous blocks."""
    con = sqlite3.connect(f"file:{Path(sqlite_path).as_posix()}?mode=ro", uri=True)
    rows = con.execute("select FromDepth, ToDepth, CompanyLithologyCodeMerged from wamex_dh_geology "
                       "where CollarId = ? order by FromDepth, ToDepth", (collar_id,)).fetchall()
    con.close()
    issues = {"null_or_reversed": [r for r in rows if r[0] is None or r[1] is None or r[0] >= r[1]]}
    good = [(r[0], r[1], r[2] if r[2] is not None else "") for r in rows if r not in issues["null_or_reversed"]]
    issues["exact_duplicates"] = len(good) - len(set(good))
    good = sorted(set(good))
    issues["overlaps"] = [(a, b) for a, b in zip(good, good[1:]) if b[0] < a[1] - 1e-9]
    issues["empty_code_rows"] = sum(1 for r in good if not (r[2] or "").strip())
    # merge touching rows that carry the same code, so unit thickness is the logged unit, not a row
    merged = []
    for r in good:
        code = (r[2] or "").strip()
        if merged and code and merged[-1][2] == code and abs(merged[-1][1] - r[0]) < 1e-6:
            merged[-1] = (merged[-1][0], r[1], code)
        else:
            merged.append((r[0], r[1], code))
    issues["rows_merged_into_units"] = len(good) - len(merged)
    good = merged
    refs, outside = [], 0
    for i, (a, b) in enumerate(zip(good, good[1:])):
        ca, cb = (a[2] or "").strip(), (b[2] or "").strip()
        if abs(a[1] - b[0]) < 1e-6 and ca and cb and ca != cb:
            d = float(a[1])
            if any(bl["from_m"] < d < bl["to_m"] for bl in blocks_m):
                refs.append({"depth_m": d, "code_above": ca, "code_below": cb,
                             "unit_above_thickness_m": float(a[1] - a[0]),
                             "unit_below_thickness_m": float(b[1] - b[0]),
                             "thin_adjacent_unit_lt_1m": bool(min(a[1] - a[0], b[1] - b[0]) < 1.0)})
            else:
                outside += 1
    logged = [(float(r[0]), float(r[1])) for r in good if (r[2] or "").strip()]
    return {"collar_id": collar_id, "n_log_rows": len(rows), "boundaries": refs,
            "n_code_changes_outside_summary_blocks": outside,
            "n_thin_adjacent_unit_lt_1m": sum(1 for r in refs if r["thin_adjacent_unit_lt_1m"]),
            "issues": {k: (len(v) if isinstance(v, list) else v) for k, v in issues.items()},
            "logged_coded_ranges": logged,
            "rule": "touching intervals (|to - next from| < 1e-6 m), both codes non-empty and different, "
                    "depth strictly inside a contiguous summary block; exact duplicate rows removed"}


# ----------------------------------------------------------------------------- matching
def match(pred, ref, tol):
    """One-to-one matching: max number of pairs within tol, then minimum total |offset|."""
    from scipy.optimize import linear_sum_assignment
    pred, ref = list(pred), list(ref)
    if not pred or not ref:
        return []
    P, R = np.array(pred, float)[:, None], np.array(ref, float)[None, :]
    off = np.abs(P - R)
    big = 1e6
    cost = np.where(off <= tol + 1e-9, off, big)
    ri, ci = linear_sum_assignment(cost)
    return [(pred[i], ref[j], float(off[i, j])) for i, j in zip(ri, ci) if cost[i, j] < big]


def score(pred, ref, tol):
    m = match(pred, ref, tol)
    n_p, n_r, k = len(pred), len(ref), len(m)
    prec = k / n_p if n_p else None
    rec = k / n_r if n_r else None
    f1 = (2 * prec * rec / (prec + rec)) if (prec and rec) else (0.0 if (n_p and n_r) else None)
    return {"tolerance_m": tol, "n_candidates": n_p, "n_reference": n_r, "n_matched": k,
            "precision": prec, "recall": rec, "f1": f1,
            "mean_abs_offset_m": (float(np.mean([x[2] for x in m])) if m else None),
            "pairs": [{"candidate_m": a, "reference_m": b, "offset_m": c} for a, b, c in m]}


# ----------------------------------------------------------------------------- baselines
def random_placement(allowed, n, min_size, rng, tries=200):
    """n depths from `allowed`, at least min_size apart within a block; None if impossible."""
    if n == 0:
        return []
    depths = np.array([p[0] for p in allowed]); blk = [p[1] for p in allowed]
    for _ in range(tries):
        order = rng.permutation(len(depths))
        chosen = []
        for i in order:
            if all(not (blk[i] == blk[j] and abs(depths[i] - depths[j]) < min_size) for j in chosen):
                chosen.append(i)
                if len(chosen) == n:
                    return sorted(float(depths[j]) for j in chosen)
    return None


def equal_spacing(blocks_m, n, min_size):
    if n == 0:
        return []
    lens = np.array([b["to_m"] - b["from_m"] for b in blocks_m], float)
    share = np.floor(lens / lens.sum() * n).astype(int)
    for i in np.argsort(-(lens / lens.sum() * n - share))[: n - share.sum()]:
        share[i] += 1
    out = []
    for b, k in zip(blocks_m, share):
        if k <= 0:
            continue
        step = (b["to_m"] - b["from_m"]) / (k + 1)
        out += [float(round(b["from_m"] + step * (i + 1))) for i in range(k)]
    return sorted(out)


def window_difference(froms, raw_col, block_index, n, w):
    """|mean(w above) - mean(w below)| on one raw column; top-n peaks at least w apart."""
    scores = []
    for a, b in block_index:
        for k in range(a + w, b - w + 1):
            scores.append((abs(raw_col[k - w:k].mean() - raw_col[k:k + w].mean()), float(froms[k]), (a, b)))
    scores.sort(key=lambda t: -t[0])
    chosen = []
    for s, d, blk in scores:
        if len(chosen) == n:
            break
        if all(not (blk == cb and abs(d - cd) < w) for _, cd, cb in chosen):
            chosen.append((s, d, blk))
    return sorted(d for _, d, _ in chosen)
