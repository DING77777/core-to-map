"""One review sheet per hole: mineral-group strips, candidate spectral changes and a segment table.

  python scripts/plot_change_sheets.py --packages packages --boundaries output --out output/sheets

Reads <hole>/metres.json (from run_pipeline.py) and <hole>/boundaries.json (from the boundary
experiment). Writes <hole>_changes.png and <hole>_segments.csv for every hole that has both.

Author: Ding Qing
Date: 2026-10-15
"""
import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e2dc"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
OTHER = "#d6d4cd"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE})
N_LABELS = 8


def name(col):
    return col.split("_(System_")[0]


def region_cols(values, region):
    return [c for c in values if c.endswith(f"(System_{region})") and not c.lower().startswith("invalid")]


def num(v):
    return v if isinstance(v, (int, float)) else 0.0  # N.A. = not detected; the region's detected groups sum to 1


def segment_means(m, cols, lo, hi):
    idx = [i for i, (f, t) in enumerate(zip(m["from_m"], m["to_m"])) if f >= lo - 1e-9 and t <= hi + 1e-9]
    return {c: sum(num(m["values"][c][i]) for i in idx) / len(idx) for c in cols} if idx else {c: 0.0 for c in cols}


def change_size(m, cand):
    """Share of the mineral mix that differs between the two segments (0-1, averaged over SWIR and TIR)."""
    total = 0.0
    for region in ("SWIR", "TIR"):
        cols = region_cols(m["values"], region)
        a = segment_means(m, cols, cand["segment_above"]["from_m"], cand["segment_above"]["to_m"])
        b = segment_means(m, cols, cand["segment_below"]["from_m"], cand["segment_below"]["to_m"])
        total += 0.5 * sum(abs(a[c] - b[c]) for c in cols)
    return total / 2


def describe(changes, k=2):
    parts = []
    for ch in changes[:k]:
        arrow = "↑" if ch["change"] > 0 else "↓"
        reg = "SWIR" if ch["metric"].endswith("(System_SWIR)") else "TIR"
        parts.append(f"{name(ch['metric'])} ({reg}) {arrow} {ch['mean_above']:.2f}→{ch['mean_below']:.2f}")
    return "; ".join(parts)


def sheet(hole, m, b, out_png, out_csv):
    swir, tir = region_cols(m["values"], "SWIR"), region_cols(m["values"], "TIR")
    tot = {c: sum(num(v) for v in m["values"][c]) for c in swir + tir}
    top_s = sorted(swir, key=lambda c: -tot[c])[:4]
    top_t = sorted(tir, key=lambda c: -tot[c])[:4]
    names = []
    for c in top_s + top_t:
        if name(c) not in names:
            names.append(name(c))
    color = {n: SERIES[i] for i, n in enumerate(names)}

    lo, hi = m["from_m"][0], m["to_m"][-1]
    span = hi - lo
    height = min(24.0, max(7.5, 3.2 + span / 32))
    fig = plt.figure(figsize=(12, height))
    ax = fig.add_axes((0.06, 0.95 / height, 0.92, 1 - 2.35 / height))
    x_s, x_t, x_c, x_l, x_txt = 0.0, 1.12, 2.24, 2.40, 2.62

    order = {n: i for i, n in enumerate(names)}
    strip_s = sorted([c for c in swir if name(c) in color], key=lambda c: order[name(c)])
    strip_t = sorted([c for c in tir if name(c) in color], key=lambda c: order[name(c)])
    for x0, cols in ((x_s, strip_s), (x_t, strip_t)):
        for i, (f, t) in enumerate(zip(m["from_m"], m["to_m"])):
            x = x0
            for c in cols:
                v = num(m["values"][c][i])
                if v > 0:
                    ax.barh(f, v, height=t - f, left=x, align="edge", color=color[name(c)], linewidth=0)
                x += v
            if x0 + 1.0 - x > 0:
                ax.barh(f, x0 + 1.0 - x, height=t - f, left=x, align="edge", color=OTHER, linewidth=0)
    present = set(zip(m["from_m"], m["to_m"]))
    for f in range(int(lo), int(hi)):
        if (f, f + 1) not in present and not any(a <= f < z for a, z in zip(m["from_m"], m["to_m"])):
            for x0 in (x_s, x_t):
                ax.barh(f, 1.0, height=1, left=x0, align="edge", color=SURFACE, hatch="////", edgecolor=GRID, linewidth=0)

    matched = {round(p["candidate_m"], 3) for p in b["scores"]["1.0"]["pairs"]}
    cands = b["candidates"]
    for c in cands:
        ok = round(c["depth_m"], 3) in matched
        ax.plot([x_s - 0.03, x_c + 0.10], [c["depth_m"]] * 2, color=INK if ok else INK2,
                lw=1.5 if ok else 1.1, ls="-" if ok else (0, (3, 2)), solid_capstyle="butt", zorder=4)
    for r in b["reference"]["boundaries"]:
        ax.plot([x_l, x_l + 0.12], [r["depth_m"]] * 2, color="#8a8780", lw=1.1, zorder=3)

    sized = sorted(cands, key=lambda c: -change_size(m, c))[:N_LABELS]
    labels = sorted(sized, key=lambda c: c["depth_m"])
    gap = span * 0.028
    ys = []
    for c in labels:
        y = c["depth_m"] if not ys else max(c["depth_m"], ys[-1] + gap)
        ys.append(y)
    overflow = (ys[-1] - hi) if ys else 0
    if overflow > 0:
        ys = [y - overflow for y in ys]
        for i in range(len(ys) - 2, -1, -1):
            ys[i] = min(ys[i], ys[i + 1] - gap)
    for c, y in zip(labels, ys):
        ax.plot([x_l + 0.13, x_txt - 0.03], [c["depth_m"], y], color=GRID, lw=0.8, zorder=2)
        ax.text(x_txt, y, f"{c['depth_m']:g} m   {describe(c['top_changes'])}", va="center", fontsize=8.5, color=INK)

    for x0, label in ((x_s, "SWIR groups"), (x_t, "TIR groups")):
        ax.text(x0 + 0.5, lo - span * 0.012, label, ha="center", va="bottom", fontsize=9, color=INK2)
    ax.text(x_l + 0.06, lo - span * 0.012, "log", ha="center", va="bottom", fontsize=8, color=INK2)
    ax.text(x_txt, lo - span * 0.012, f"Largest {len(labels)} changes (mean above → below)", va="bottom", fontsize=9, color=INK2)
    ax.set_ylim(hi + span * 0.005, lo - span * 0.045)
    ax.set_xlim(-0.05, 5.6)
    ax.set_xticks([])
    for sp in ("top", "right", "bottom"):
        ax.spines[sp].set_visible(False)
    ax.set_ylabel("Along-hole depth (m)")

    s = b["scores"]["1.0"]
    rb = b["baselines"]["random_same_count"]
    role = "development hole (used to choose the settings)" if b["role"] == "development" else "test hole (settings fixed beforehand)"
    fig.text(0.06, 1 - 0.30 / height, f"{hole}: where the measured mineral mix changes", fontsize=14, color=INK, va="top")
    if s["n_reference"]:
        summary = (f"{len(cands)} candidate changes, {s['n_reference']} company-log code changes, {s['n_matched']} within 1 m of each other. "
                   f"F1 {s['f1']:.2f}; random lines of the same number: {rb['f1_mean']:.2f}. {role[0].upper() + role[1:]}.")
    else:
        summary = (f"{len(cands)} candidate changes. The company log has no usable code change inside the scanned depths, "
                   f"so this hole could not be scored.")
    fig.text(0.06, 1 - 0.68 / height, summary, fontsize=9, color=INK2, va="top")
    fig.text(0.06, 1 - 0.90 / height, "A candidate marks a change in the spectral mineral mix. It is a place to look, not a confirmed contact. "
             "Proportions are relative spectral proportions, not assays.", fontsize=9, color=INK2, va="top")
    handles = [Patch(color=color[n], label=n) for n in names]
    handles += [Patch(color=OTHER, label="Other groups / unclassified"),
                Patch(facecolor=SURFACE, edgecolor=GRID, hatch="////", label="No record"),
                Line2D([], [], color=INK, lw=1.5, label="Candidate, log change within 1 m"),
                Line2D([], [], color=INK2, lw=1.1, ls=(0, (3, 2)), label="Candidate, no log change within 1 m"),
                Line2D([], [], color="#8a8780", lw=1.1, label="Company-log code change (reference)")]
    fig.legend(handles=handles, loc="lower left", ncol=5, frameon=False, fontsize=8.5, bbox_to_anchor=(0.05, 0.08 / height))
    fig.savefig(out_png, dpi=150)
    plt.close(fig)

    blocks = [(blk["from_m"], blk["to_m"]) for blk in b["usable_blocks"]]
    rows = []
    for a, z in blocks:
        cuts = [c for c in cands if a < c["depth_m"] < z]
        edges = [a] + [c["depth_m"] for c in cuts] + [z]
        for i in range(len(edges) - 1):
            f, t = edges[i], edges[i + 1]
            ms = segment_means(m, swir, f, t)
            mt = segment_means(m, tir, f, t)
            top_c = cuts[i - 1] if i > 0 else None
            rows.append({
                "hole_id": hole, "from_m": f, "to_m": t, "length_m": round(t - f, 3),
                "main_swir_groups": "; ".join(f"{name(c)} {ms[c]:.2f}" for c in sorted(swir, key=lambda c: -ms[c])[:4] if ms[c] >= 0.05),
                "main_tir_groups": "; ".join(f"{name(c)} {mt[c]:.2f}" for c in sorted(tir, key=lambda c: -mt[c])[:4] if mt[c] >= 0.05),
                "change_at_top": describe(top_c["top_changes"], 3) if top_c else "start of a continuous block",
                "change_size_at_top": round(change_size(m, top_c), 3) if top_c else "",
                "parameter_stability_at_top": top_c["parameter_stability"] if top_c else "",
                "nearest_log_change_m": top_c["nearest_log_code_change_m"] if top_c else "",
                "log_change_within_1m": ("yes" if round(top_c["depth_m"], 3) in matched else "no") if top_c else "",
            })
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--packages", default="packages")
    ap.add_argument("--boundaries", default="output")
    ap.add_argument("--out", default="output/sheets")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for bfile in sorted(Path(a.boundaries).glob("*/boundaries.json")):
        hole = bfile.parent.name
        mfile = Path(a.packages) / hole / "metres.json"
        if not mfile.exists():
            continue
        n = sheet(hole, json.loads(mfile.read_text()), json.loads(bfile.read_text()),
                  out / f"{hole}_changes.png", out / f"{hole}_segments.csv")
        print(f"{hole}: {n} segments")


if __name__ == "__main__":
    main()
