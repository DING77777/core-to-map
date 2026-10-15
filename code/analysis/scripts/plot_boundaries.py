"""Slide figures for the candidate-change experiment (matplotlib; reads work/boundaries + packages).

  python scripts/plot_boundaries.py --boundaries work/boundaries --packages packages --out work/boundaries

Author: Ding Qing
Date: 2026-10-15
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e2dc"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
OTHER = "#c9c7bf"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE})


def strip_figure(bdir, pdir, holes, out):
    metres = {h: json.loads((pdir / h / "metres.json").read_text()) for h in holes}
    bnd = {h: json.loads((bdir / h / "boundaries.json").read_text()) for h in holes}
    swir = [c for c in metres[holes[0]]["values"] if c.endswith("(System_SWIR)") and not c.lower().startswith("invalid")]
    tot = {c: sum(sum(v for v in metres[h]["values"][c] if isinstance(v, (int, float))) for h in holes) for c in swir}
    top = sorted(swir, key=lambda c: -tot[c])[:6]
    lo = min(metres[h]["from_m"][0] for h in holes); hi = max(metres[h]["to_m"][-1] for h in holes)
    fig, axes = plt.subplots(1, len(holes), figsize=(3.3 * len(holes) + 1.2, 9), sharey=True)
    for ax, h in zip(axes, holes):
        m, b = metres[h], bnd[h]
        for i, (f, t) in enumerate(zip(m["from_m"], m["to_m"])):
            x = 0.0
            for k, c in enumerate(top):
                v = m["values"][c][i]
                v = v if isinstance(v, (int, float)) else 0.0
                if v > 0:
                    ax.barh(f, v, height=t - f, left=x, align="edge", color=SERIES[k], linewidth=0)
                x += v
            rest = max(0.0, 1.0 - x)
            if rest > 0:
                ax.barh(f, rest, height=t - f, left=x, align="edge", color=OTHER, linewidth=0)
        matched = {round(p["candidate_m"], 3) for p in b["scores"]["1.0"]["pairs"]}
        for c in b["candidates"]:
            ok = round(c["depth_m"], 3) in matched
            ax.plot([1.04, 1.32], [c["depth_m"]] * 2, color=INK if ok else "#e34948", lw=2, solid_capstyle="round")
        for r in b["reference"]["boundaries"]:
            ax.plot([1.40, 1.62], [r["depth_m"]] * 2, color=INK2, lw=1.2)
        s = b["scores"]["1.0"]; rb = b["baselines"]["random_same_count"]
        ax.set_title(f"{h}\n{s['n_matched']}/{s['n_candidates']} candidates within 1 m of a log change\n"
                     f"F1 {s['f1']:.2f}  (random, same count: {rb['f1_mean']:.2f})", fontsize=9.5, color=INK, loc="left")
        ax.set_xlim(0, 1.66); ax.set_xticks([0, 0.5, 1.0]); ax.set_xticklabels(["0", "0.5", "1"])
        ax.text(1.18, lo - 3, "candidate", ha="center", va="bottom", fontsize=8, color=INK2)
        ax.text(1.51, lo - 3, "log code\nchange", ha="center", va="bottom", fontsize=8, color=INK2)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.set_xlabel("SWIR mineral-group proportion", fontsize=8.5)
    axes[0].set_ylim(hi + 2, lo - 10)
    axes[0].set_ylabel("Along-hole depth (m)")
    handles = [Patch(color=SERIES[k], label=c.replace("_(System_SWIR)", "")) for k, c in enumerate(top)]
    handles += [Patch(color=OTHER, label="Other / invalid / not detected"),
                Line2D([], [], color=INK, lw=2, label="Candidate within 1 m of a log change"),
                Line2D([], [], color="#e34948", lw=2, label="Candidate with no log change within 1 m"),
                Line2D([], [], color=INK2, lw=1.2, label="Company-log code change (reference)")]
    fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False, fontsize=8.5, bbox_to_anchor=(0.5, -0.005))
    fig.suptitle("Candidate spectral changes vs company-log code changes - TBDD126/127/128 (one project, 60-164 m apart)",
                 x=0.01, ha="left", fontsize=11.5, color=INK)
    fig.text(0.01, 0.945, "Parameters locked on CMDD001/002 before these holes were compared. Strip shows SWIR groups only; "
             "detection used 36 SWIR+TIR groups. Candidates are not confirmed contacts.", fontsize=8.5, color=INK2)
    fig.tight_layout(rect=(0, 0.06, 1, 0.94))
    fig.savefig(out, dpi=200)
    plt.close(fig)


def score_figure(summary, bdir, out):
    s = json.loads(summary.read_text())
    holes = s["test_holes"]
    rows = []
    skipped = []
    for h in holes:
        b = json.loads((bdir / h / "boundaries.json").read_text())
        if not b["scores"]["1.0"]["n_reference"]:
            skipped.append(h)  # no usable log change inside the scanned depths: nothing to score against
            continue
        rows.append((h, b["scores"]["1.0"]["f1"] or 0, b["baselines"]["random_same_count"]["f1_mean"],
                     b["baselines"]["random_same_count"]["f1_p95"], b["baselines"]["window_difference_2200W_same_count"]["f1"],
                     b["baselines"]["random_same_count"]["p_value_f1_ge_model"]))
    tp = s["test_pooled"]["composition36"]
    rows.append((f"All {len(holes)} test\nholes pooled", tp["model"]["f1"], tp["random_f1_mean"], tp["random_f1_p95"],
                 tp["window_difference_2200W"]["f1"], tp["p_value"]))
    fig, ax = plt.subplots(figsize=(9.5, 2.2 + 0.36 * len(rows)))
    ys = list(range(len(rows)))[::-1]
    for y, (h, f1, rm, rp, wd, p) in zip(ys, rows):
        ax.plot([rm, rp], [y, y], color=OTHER, lw=6, solid_capstyle="round", zorder=1)
        ax.scatter([wd], [y], s=60, marker="D", color=SERIES[1], zorder=3, edgecolor=SURFACE, linewidth=2)
        ax.scatter([f1], [y], s=90, color=SERIES[0], zorder=4, edgecolor=SURFACE, linewidth=2)
        if abs(f1 - wd) < 0.012:  # identical scores: draw the diamond inside the dot so both stay visible
            ax.scatter([wd], [y], s=28, marker="D", color=SERIES[1], zorder=5, edgecolor=SURFACE, linewidth=1)
        ax.text(max(f1, rp, wd) + 0.02, y, f"F1 {f1:.2f}   p = {p:.3f}", va="center", fontsize=9, color=INK2)
    ax.set_yticks(ys); ax.set_yticklabels([r[0] for r in rows], color=INK)
    ax.set_xlim(0, 0.75); ax.set_xlabel("F1 at 1 m tolerance (one-to-one matching with company-log code changes)")
    ax.grid(axis="x", color=GRID, lw=0.8); ax.set_axisbelow(True)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(axis="y", length=0)
    handles = [Line2D([], [], marker="o", ls="", color=SERIES[0], ms=9, label="Candidate changes (36 mineral groups, locked parameters)"),
               Line2D([], [], marker="D", ls="", color=SERIES[1], ms=7, label="Simple baseline: window difference on 2200W only"),
               Line2D([], [], color=OTHER, lw=6, label="Random placement, same count: mean to 95th percentile")]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.0, -0.16), ncol=1, frameon=False, fontsize=8.5)
    note = f"  Not scored (no log change inside the scanned depths): {', '.join(skipped)}." if skipped else ""
    ax.set_title("Test holes only (parameters chosen on CMDD001/002).  p = share of 1,000 random placements scoring at least as well."
                 + ("\n" + note.strip() if note else ""), fontsize=9.5, color=INK, loc="left")
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def hits_figure(summary, bdir, out):
    """Slide view: log changes found by the candidates vs. by the same number of random lines, per test hole."""
    s = json.loads(summary.read_text())
    rows, skipped = [], []
    for h in s["test_holes"]:
        b = json.loads((bdir / h / "boundaries.json").read_text())
        sc, rb = b["scores"]["1.0"], b["baselines"]["random_same_count"]
        if not sc["n_reference"]:
            skipped.append(h)
            continue
        expected = (rb["f1_mean"] or 0) * (sc["n_candidates"] + sc["n_reference"]) / 2
        rows.append((h, sc["n_matched"], expected, rb["p_value_f1_ge_model"] < 0.05))
    rows.sort(key=lambda r: (r[3], r[1] - r[2]))
    n_win = sum(r[3] for r in rows)
    fig, ax = plt.subplots(figsize=(10, 2.2 + 0.27 * len(rows)))
    for y, (h, k, e, win) in enumerate(rows):
        ax.plot([e, k], [y, y], color=GRID if not win else "#9fc0ea", lw=3, solid_capstyle="round", zorder=1)
        ax.scatter([e], [y], s=36, color=OTHER, zorder=2, edgecolor=SURFACE, linewidth=1.5)
        ax.scatter([k], [y], s=52, color=SERIES[0] if win else SURFACE, edgecolor=SERIES[0], linewidth=1.5, zorder=3)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([f"{h}" + ("" if win else "  (not better than random)") for h, _, _, win in rows], fontsize=8.5, color=INK)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.set_xlabel("Company-log code changes with a candidate within 1 m (count)")
    title = (f"{n_win} of {len(rows)} test holes: the candidates find more log changes than random lines\n"
             "Filled dot = candidates. Grey dot = the same number of random lines (average of 1,000 placements).\n"
             "Open dot = not better than random (p \u2265 0.05).")
    if skipped:
        title += f"\n{len(skipped)} more holes could not be scored: their logs have no code change inside the scanned depths."
    ax.set_ylim(-0.7, len(rows) - 0.3)
    fig.suptitle(title, x=0.01, y=0.995, ha="left", va="top", fontsize=9.5, color=INK)
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boundaries", default="work/boundaries")
    ap.add_argument("--packages", default="packages")
    ap.add_argument("--out", default="work/boundaries")
    a = ap.parse_args()
    bdir, pdir, out = Path(a.boundaries), Path(a.packages), Path(a.out)
    strip_figure(bdir, pdir, ["TBDD126", "TBDD127", "TBDD128"], out / "fig_tbdd_candidate_changes.png")
    score_figure(bdir / "boundary_experiment_summary.json", bdir, out / "fig_boundary_scores_test_holes.png")
    print("written", out / "fig_tbdd_candidate_changes.png", out / "fig_boundary_scores_test_holes.png")


if __name__ == "__main__":
    main()
