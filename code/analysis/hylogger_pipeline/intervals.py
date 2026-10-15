"""Continuous-interval search over 1 m summary records.

Rules (identical to the shared acceptance semantics):
* only records lying fully inside the window [window_from, window_to) are eligible;
* a record passes when every condition passes; comparisons use exact Decimal values;
* passing records join only when they touch (previous to_m == next from_m) in the same hole;
* source N.A., blanks, invalid tokens, failed comparisons and missing metres all break a run.
  (`na_passes` exists in the engine for future quality guards but is NOT exposed in v1; if it is
  ever used it is echoed in the output and must be shown and exported.)
* runs shorter than min_length_m are dropped. No interpolation, smoothing or zero filling.

Each run carries edge flags that say WHY it stops where it stops, when that is not the data itself:
  starts_at_coverage_start / ends_at_coverage_end   - first/last record of the hole's summary
  starts_after_gap / ends_before_gap                - a missing-metre gap in the source
  truncated_by_window_start / truncated_by_window_end - the user's query window cut a run that
                                                       would continue in the data
Standard library only.

Author: Ding Qing
Date: 2026-10-15
"""
from __future__ import annotations

from decimal import Decimal

OPS = {">=": lambda v, t: v >= t, "<=": lambda v, t: v <= t, ">": lambda v, t: v > t, "<": lambda v, t: v < t}


def _check(record, cond):
    v = record["values"].get(cond["metric"])
    s = record["status"].get(cond["metric"], "absent")
    if s == "ok":
        return OPS[cond["op"]](v, Decimal(str(cond["value"]))), s
    if s == "source_na" and cond.get("na_passes"):
        return True, s
    return False, s


def _passes(record, conditions):
    return all(_check(record, c)[0] for c in conditions)


def find_runs(hole: dict, conditions: list[dict], window_from, window_to, min_length_m) -> dict:
    wf, wt, ml = Decimal(str(window_from)), Decimal(str(window_to)), Decimal(str(min_length_m))
    all_recs = hole["records"]
    by_from = {r["from_m"]: r for r in all_recs}
    by_to = {r["to_m"]: r for r in all_recs}
    cov_start = all_recs[0]["from_m"] if all_recs else None
    cov_end = all_recs[-1]["to_m"] if all_recs else None
    gap_starts = {g["from_m"] for g in hole.get("gaps", [])}
    gap_ends = {g["to_m"] for g in hole.get("gaps", [])}

    recs = [r for r in all_recs if r["from_m"] >= wf and r["to_m"] <= wt]
    runs, cur, prev_to, explain = [], None, None, []
    for r in recs:
        results = [(c["metric"], *_check(r, c)) for c in conditions]
        ok = all(p for _, p, _ in results)
        touching = prev_to is not None and r["from_m"] == prev_to
        reason = "pass" if ok else "; ".join(f"{m}:{'fail' if st == 'ok' else st}" for m, p, st in results if not p)
        if prev_to is not None and r["from_m"] > prev_to:
            reason += " (gap before)"
        explain.append({"from_m": r["from_m"], "to_m": r["to_m"], "record_no": r["record_no"], "pass": ok, "reason": reason})
        if ok:
            if cur and touching:
                cur["to_m"] = r["to_m"]; cur["record_nos"].append(r["record_no"])
            else:
                if cur:
                    runs.append(cur)
                cur = {"from_m": r["from_m"], "to_m": r["to_m"], "record_nos": [r["record_no"]]}
        else:
            if cur:
                runs.append(cur); cur = None
        prev_to = r["to_m"]
    if cur:
        runs.append(cur)
    kept = [x for x in runs if x["to_m"] - x["from_m"] >= ml]
    for x in kept:
        x["length_m"] = x["to_m"] - x["from_m"]
        flags = []
        if x["from_m"] == cov_start:
            flags.append("starts_at_coverage_start")
        elif x["from_m"] in gap_ends:
            flags.append("starts_after_gap")
        elif x["from_m"] == wf and x["from_m"] in by_to and _passes(by_to[x["from_m"]], conditions):
            flags.append("truncated_by_window_start")
        if x["to_m"] == cov_end:
            flags.append("ends_at_coverage_end")
        elif x["to_m"] in gap_starts:
            flags.append("ends_before_gap")
        elif x["to_m"] == wt and x["to_m"] in by_from and _passes(by_from[x["to_m"]], conditions):
            flags.append("truncated_by_window_end")
        x["edge_flags"] = flags
    covered = sum((r["to_m"] - r["from_m"]) for r in recs)
    return {
        "hole_id": hole["hole_id"],
        "conditions": conditions,
        "na_passes_used": any(c.get("na_passes") for c in conditions),
        "window": [wf, wt],
        "window_convention": "[from, to) whole records only",
        "min_length_m": ml,
        "runs": kept,
        "total_length_m": sum((x["length_m"] for x in kept), Decimal(0)),
        "window_coverage_m": covered,
        "window_coverage_fraction": (covered / (wt - wf)) if wt > wf else None,
        "per_record": explain,
    }
