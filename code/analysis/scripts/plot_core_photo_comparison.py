"""Original tray-photo rows for a depth window, next to the mineral strips and candidate changes.

  python scripts/plot_core_photo_comparison.py --tsg-dir <folder with HOLE_tsg.tsg and HOLE_0001.jpg ...> --hole CMDD002
      --from 128 --to 146 --packages packages --boundaries output --out output/photos

Each row of a tray photo is shown as photographed (not resampled). Every HyLogger sample header gives its
tray, row, distance along the row (mm) and depth (m), so the rows are labelled with their depth range and
candidate changes are marked at the matching position along the row. TSG renders the photos with the
distance axis at x = 370 px + 9.996 px per mm and rows starting 370 px from the top (read from the axis).

Author: Ding Qing
Date: 2026-10-15
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
SURFACE, INK, INK2, GRID, LOG = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e2dc", "#8a8780"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
OTHER = "#d6d4cd"
X0_PX, PX_PER_MM, TOP_PX, SCALE = 370.0, 9.996, 370, 0.25
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE})


def parse_samples(tsg_path):
    rows = {}
    pat = re.compile(r"T=(\d+) L=(\d+) P=\d+ D=([-\d.]+) X=([-\d.]+)")
    for line in open(tsg_path, errors="ignore"):
        m = pat.search(line)
        if m:
            rows.setdefault((int(m[1]), int(m[2])), []).append((float(m[4]), float(m[3])))
    return {k: np.array(sorted(v)) for k, v in rows.items()}


def tray_rows(tsg_dir, hole, lo, hi):
    samples = parse_samples(Path(tsg_dir) / f"{hole}_tsg.tsg")
    out, cache = [], {}
    for (tray, line), xd in sorted(samples.items(), key=lambda kv: kv[1][0, 1]):
        d0, d1 = float(xd[:, 1].min()), float(xd[:, 1].max())
        if d1 < lo or d0 > hi:
            continue
        if tray not in cache:
            path = Path(tsg_dir) / f"{hole}_{tray:04d}.jpg"
            if not path.exists():
                continue
            im = Image.open(path)
            fields = im.info.get("comment", b"").decode("latin-1").strip("\x00").split(",")
            heights = [int(fields[9 + 3 * i]) for i in range(int(fields[2]))]
            cache[tray] = (np.asarray(im.convert("RGB").resize((int(im.width * SCALE), int(im.height * SCALE)))), heights)
        img, heights = cache[tray]
        top = TOP_PX + sum(heights[:line - 1])
        h = heights[line - 1]
        y0, y1 = int((top + 0.03 * h) * SCALE), int((top + 0.72 * h) * SCALE)
        x0 = int((X0_PX + PX_PER_MM * (xd[:, 0].min() - 5)) * SCALE)
        x1 = int((X0_PX + PX_PER_MM * (xd[:, 0].max() + 5)) * SCALE)
        out.append({"tray": tray, "line": line, "from": d0, "to": d1, "img": img[y0:y1, max(x0, 0):x1],
                    "x_of_depth": lambda z, xd=xd, x0=x0: (X0_PX + PX_PER_MM * np.interp(z, np.maximum.accumulate(xd[:, 1]), xd[:, 0])) * SCALE - max(x0, 0)})
    return out


def name(col):
    return col.split("_(System_")[0]


def num(v):
    return v if isinstance(v, (int, float)) else 0.0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tsg-dir", required=True)
    ap.add_argument("--hole", required=True)
    ap.add_argument("--from", dest="lo", type=float, required=True)
    ap.add_argument("--to", dest="hi", type=float, required=True)
    ap.add_argument("--packages", default="packages")
    ap.add_argument("--boundaries", default="output")
    ap.add_argument("--out", default="output/photos")
    a = ap.parse_args()
    lo, hi = a.lo, a.hi
    m = json.loads((Path(a.packages) / a.hole / "metres.json").read_text())
    b = json.loads((Path(a.boundaries) / a.hole / "boundaries.json").read_text())
    rows = tray_rows(a.tsg_dir, a.hole, lo, hi)
    cands = [c["depth_m"] for c in b["candidates"] if lo <= c["depth_m"] <= hi]
    logs = [r["depth_m"] for r in b["reference"]["boundaries"] if lo <= r["depth_m"] <= hi]
    matched = {round(p["candidate_m"], 3) for p in b["scores"]["1.0"]["pairs"]}

    vals = m["values"]
    idx = [i for i, (f, t) in enumerate(zip(m["from_m"], m["to_m"])) if t > lo and f < hi]
    swir = [c for c in vals if c.endswith("(System_SWIR)") and not c.lower().startswith("invalid")]
    tir = [c for c in vals if c.endswith("(System_TIR)") and not c.lower().startswith("invalid")]
    tot = {c: sum(num(vals[c][i]) for i in idx) for c in swir + tir}
    names = []
    for c in sorted(swir, key=lambda c: -tot[c])[:4] + sorted(tir, key=lambda c: -tot[c])[:4]:
        if name(c) not in names:
            names.append(name(c))
    color = {nm: SERIES[i] for i, nm in enumerate(names)}

    left, width = 0.40, 0.58
    aspect = float(np.median([r["img"].shape[0] / r["img"].shape[1] for r in rows])) if rows else 0.04
    row_h = 14 * width * aspect  # rows keep the proportions of the photo
    height = max(6.0, 1.6 + len(rows) * (row_h + 0.16))
    fig = plt.figure(figsize=(14, height))
    ax = fig.add_axes((0.06, 0.7 / height, 0.24, 1 - 1.55 / height))
    for x0, cols in ((0.0, swir), (1.08, tir)):
        cols = [c for c in cols if name(c) in color]
        for i in idx:
            f, t, x = m["from_m"][i], m["to_m"][i], x0
            for c in cols:
                v = num(vals[c][i])
                if v > 0:
                    ax.barh(f, v, height=t - f, left=x, align="edge", color=color[name(c)], linewidth=0)
                x += v
            ax.barh(f, max(0, x0 + 1 - x), height=t - f, left=x, align="edge", color=OTHER, linewidth=0)
    for z in cands:
        ok = round(z, 3) in matched
        ax.plot([-0.03, 2.14], [z, z], color=INK if ok else INK2, lw=1.6 if ok else 1.2, ls="-" if ok else (0, (3, 2)))
        ax.text(2.18, z, f"{z:g} m", va="center", fontsize=8.5, color=INK)
    for z in logs:
        ax.plot([2.55, 2.75], [z, z], color=LOG, lw=1.3)
    ax.text(0.5, lo - (hi - lo) * 0.012, "SWIR groups", ha="center", va="bottom", color=INK2)
    ax.text(1.58, lo - (hi - lo) * 0.012, "TIR groups", ha="center", va="bottom", color=INK2)
    ax.text(2.65, lo - (hi - lo) * 0.012, "log", ha="center", va="bottom", color=INK2)
    ax.set_xlim(-0.05, 2.8); ax.set_ylim(hi, lo - (hi - lo) * 0.04); ax.set_xticks([])
    for sp in ("top", "right", "bottom"):
        ax.spines[sp].set_visible(False)
    ax.set_ylabel("Along-hole depth (m)")

    for k, r in enumerate(rows):
        bottom = 1 - (1.05 + (k + 1) * (row_h + 0.16)) / height
        rax = fig.add_axes((left, bottom, width, row_h / height))
        img = r["img"]
        rax.imshow(img, aspect="auto", extent=(0, img.shape[1], img.shape[0], 0))
        for z in cands:
            if r["from"] <= z <= r["to"]:
                x = r["x_of_depth"](z)
                ok = round(z, 3) in matched
                rax.axvline(x, color="#e34948", lw=2.2)
                rax.text(x, -2, f"{z:g} m", ha="center", va="bottom", fontsize=8.5, color="#e34948", clip_on=False)
        for z in logs:
            if r["from"] <= z <= r["to"]:
                rax.plot([r["x_of_depth"](z)], [img.shape[0] - 1], marker="^", color=LOG, ms=7, clip_on=False)
        rax.set_xticks([]); rax.set_yticks([])
        for sp in rax.spines.values():
            sp.set_color(GRID)
        rax.text(-8, img.shape[0] / 2, f"{r['from']:.2f}–{r['to']:.2f} m", ha="right", va="center", fontsize=8, color=INK2)
    fig.text(0.06, 1 - 0.28 / height, f"{a.hole}, {lo:.0f}–{hi:.0f} m: mineral groups and the original tray-photo rows",
             fontsize=13, color=INK, va="top")
    fig.text(0.06, 1 - 0.58 / height, "Photo rows are shown as photographed, top to bottom in depth order, with their logged depth range. "
             "Red lines mark the candidate changes at their position along the row; grey triangles mark company-log changes.",
             fontsize=8.5, color=INK2, va="top")
    if b.get("role") == "development":
        fig.text(0.06, 1 - 0.80 / height, f"{a.hole} was one of the two holes used to choose the change-detection settings, so this is an illustration, not a test.",
                 fontsize=8.5, color=INK2, va="top")
    handles = [Patch(color=color[n], label=n) for n in names] + [Patch(color=OTHER, label="Other / unclassified"),
               Line2D([], [], color=INK, lw=1.6, label="Candidate change"), Line2D([], [], color=LOG, lw=1.3, label="Company-log change")]
    fig.legend(handles=handles, loc="lower left", ncol=6, frameon=False, fontsize=8, bbox_to_anchor=(0.05, 0.05 / height))
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    path = out / f"{a.hole}_{lo:.0f}-{hi:.0f}m_tray_rows.png"
    fig.savefig(path, dpi=160)
    print("written", path, f"{len(rows)} rows")


if __name__ == "__main__":
    main()
