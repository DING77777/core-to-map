"""Scan-level processing of a raw TSG package (optional; needs numpy, pandas and GSWA's pytsg).

What it does
1. Re-computes the official 1 m summary from individual scans and reports the agreement.
   Empirical rule found for four feature columns in CMDD001/CMDD002 (2200W/2250W, 2200D/2250D):
   mean of the scan scalar over scans whose 'Depth (m)' lies in (from, to] and whose feature depth
   (e.g. '2200D') >= Scalar_min_depth (0.001 in the CSV metadata). This is a reproduction on a
   finite sample, not an official specification, and it covers only those four columns.
2. Keeps the individual scans behind every 1 m value - scan index, depth and full-precision value -
   so a viewer can show their distribution and trace each scan back to the TSG file.
3. Re-aggregates the same scans at other bin sizes (0.5 m, 2 m) with the same rule (multi-scale).
   The last, shorter bucket is kept and flagged; buckets that touch a source gap are not averaged.

Scan scalars use -3.4028e38 (float32 min) as "no value"; it is converted to NaN here.

Author: Ding Qing
Date: 2026-10-15
"""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd

SENTINEL_BELOW = -1.0e38
FEATURE_PAIRS = {"2200W_AlOH": ("2200W", "2200D"), "2250W_FeOH": ("2250W", "2250D")}
DEPTH_COLUMN_PAIRS = {"2200D_AlOH": "2200D", "2250D_FeOH": "2250D"}


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_nir(tsg_dir: Path, hole_id: str):
    from pytsg import read_spectra  # imported lazily: optional dependency
    tsg_dir = Path(tsg_dir)
    return read_spectra(tsg_dir / f"{hole_id}_tsg.tsg", tsg_dir / f"{hole_id}_tsg.bip", spectrum_name="nir")


def _clean(series):
    a = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    a[a < SENTINEL_BELOW] = np.nan
    return a


def _bins(depth, lo, hi):
    """Scans in (lo, hi] - the membership that reproduces the official summary."""
    return (depth > lo) & (depth <= hi)


def rebin(depth, values, keep, lo, hi, size, gaps):
    """Average `values[keep]` in consecutive buckets of `size` metres from lo to hi.

    * the final bucket may be shorter than `size`; it is kept and flagged partial;
    * a bucket that overlaps a source gap (list of (from, to)) is NOT averaged across the gap:
      it is reported with mean None and status 'spans_source_gap';
    * no bucket is silently dropped.
    """
    rows, a = [], float(lo)
    while a < hi - 1e-9:
        b = min(a + size, float(hi))
        gap_hit = any(g0 < b and g1 > a for g0, g1 in gaps)
        sel = _bins(depth, a, b) & keep
        v = values[sel]
        rows.append({"from_m": round(a, 6), "to_m": round(b, 6), "width_m": round(b - a, 6),
                     "partial": (b - a) < size - 1e-9,
                     "status": "spans_source_gap" if gap_hit else ("ok" if len(v) else "no_scans"),
                     "n_scans_used": int(len(v)),
                     "mean": (float(v.mean()) if len(v) and not gap_hit else None)})
        a = b
    return rows


def process(tsg_dir: Path, sm_hole: dict, out_dir: Path, min_depth: float | None = None) -> dict:
    tsg_dir = Path(tsg_dir)
    hid = sm_hole["hole_id"]
    s = read_nir(tsg_dir, hid)
    sc = s.scalars
    depth = _clean(sc["Depth (m)"])
    scan_index = pd.to_numeric(s.sampleheaders["sample"], errors="coerce").to_numpy(dtype=int)
    min_depth = float(min_depth if min_depth is not None else sm_hole["metadata"].get("Scalar_min_depth", 0.001))
    recs = sm_hole["records"]
    gaps = [(float(g["from_m"]), float(g["to_m"])) for g in sm_hole["gaps"]]
    try:
        import pytsg
        pytsg_version = getattr(pytsg, "__version__", "unknown")
    except Exception:  # pragma: no cover
        pytsg_version = "unknown"
    files = {}
    for name in (f"{hid}_tsg.tsg", f"{hid}_tsg.bip"):
        p = tsg_dir / name
        files[name] = {"bytes": p.stat().st_size, "sha256": _sha(p)}
    analyses = {"raw_tsg": {"spectral_region": "nir (VNIR-SWIR)", "n_scans": int(len(depth)),
                            "n_bands": int(s.spectra.shape[1]),
                            "wavelength_nm": [float(s.wavelength[0]), float(s.wavelength[-1])],
                            "scan_depth_range_m": [float(np.nanmin(depth)), float(np.nanmax(depth))],
                            "null_sentinel": "-3.4028e38 converted to NaN",
                            "files": files,
                            "software": {"python": platform.python_version(), "numpy": np.__version__,
                                         "pandas": pd.__version__, "pytsg": pytsg_version,
                                         "pytsg_source_commit": "481f5faf6e1153791b849d4216a47f86f7db20ce"}}}
    repro = {}
    scan_stats = {"hole_id": hid, "scan_bin_membership": "(from_m, to_m]",
                  "scan_index_meaning": "0-based 'sample' column of the TSG sample headers (same order as the BIP file)",
                  "source_files": files, "metrics": {}}

    for col, (wcol, dcol) in FEATURE_PAIRS.items():
        if col not in sm_hole["header"] or wcol not in sc or dcol not in sc:
            continue
        w, d = _clean(sc[wcol]), _clean(sc[dcol])
        keep = (d >= min_depth) & ~np.isnan(w)
        diffs, bins = [], []
        for r in recs:
            in_bin = _bins(depth, float(r["from_m"]), float(r["to_m"]))
            sel = in_bin & keep
            order = np.argsort(depth[sel], kind="stable")
            vals, deps, idx = w[sel][order], depth[sel][order], scan_index[sel][order]
            official = r["values"][col] if r["status"][col] == "ok" else None
            mean = float(vals.mean()) if len(vals) else None
            if official is not None and mean is not None:
                diffs.append(abs(mean - float(official)))
            bins.append({"from_m": float(r["from_m"]), "to_m": float(r["to_m"]), "record_no": r["record_no"],
                         "official": (float(official) if official is not None else r["status"][col]),
                         "n_scans_in_bin": int(in_bin.sum()),
                         "n_scans_used": int(len(vals)),
                         "mean": mean,
                         "std": (float(vals.std(ddof=1)) if len(vals) > 1 else None),
                         "p10": (float(np.percentile(vals, 10)) if len(vals) else None),
                         "p50": (float(np.percentile(vals, 50)) if len(vals) else None),
                         "p90": (float(np.percentile(vals, 90)) if len(vals) else None),
                         "scan_index": [int(i) for i in idx],
                         "scan_depth_m": [float(x) for x in deps],
                         "scan_value": [float(x) for x in vals]})
        diffs = np.array(diffs)
        repro[col] = {"scan_scalar": wcol, "filter": f"{dcol} >= {min_depth}", "scan_bin_membership": "(from_m, to_m]",
                      "n_bins_compared": int(len(diffs)),
                      "n_bins_matched_within_0p001_nm": int((diffs < 1e-3).sum()),
                      "max_abs_diff": float(diffs.max()) if len(diffs) else None,
                      "mean_abs_diff": float(diffs.mean()) if len(diffs) else None, "unit": "nm"}
        lo, hi = float(recs[0]["from_m"]), float(recs[-1]["to_m"])
        multiscale = {str(size): rebin(depth, w, keep, lo, hi, size, gaps) for size in (0.5, 2.0)}
        scan_stats["metrics"][col] = {
            "unit": "nm", "scan_scalar": wcol, "filter": f"{dcol} >= {min_depth}",
            "denominator": "n_scans_used = scans in (from,to] that pass the feature-depth filter; "
                           "any 'share of scans >= threshold' must use this denominator, not n_scans_in_bin",
            "p10_p90_meaning": "spread of scan values (distribution range), NOT a confidence interval",
            "bins_1m": bins, "multiscale": multiscale}

    for col, dcol in DEPTH_COLUMN_PAIRS.items():
        if col not in sm_hole["header"] or dcol not in sc:
            continue
        d = _clean(sc[dcol]); keep = d >= min_depth
        diffs = []
        for r in recs:
            if r["status"][col] != "ok":
                continue
            v = d[_bins(depth, float(r["from_m"]), float(r["to_m"])) & keep]
            if len(v):
                diffs.append(abs(float(v.mean()) - float(r["values"][col])))
        diffs = np.array(diffs)
        repro[col] = {"scan_scalar": dcol, "filter": f"{dcol} >= {min_depth}", "scan_bin_membership": "(from_m, to_m]",
                      "n_bins_compared": int(len(diffs)), "n_bins_matched_within_1e-5": int((diffs < 1e-5).sum()),
                      "max_abs_diff": float(diffs.max()) if len(diffs) else None, "unit": "unitless"}

    out_dir = Path(out_dir) / hid
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "scan_stats.json").write_text(json.dumps(scan_stats, separators=(",", ":")), encoding="utf-8")
    analyses["summary_reproduction"] = dict(
        repro, scope="four feature columns, this hole only; not all 49 columns; empirical, not an official specification")
    analyses["scan_stats"] = {"file": "scan_stats.json", "metrics": list(scan_stats["metrics"].keys()),
                              "scales_m": [0.5, 1.0, 2.0],
                              "multiscale_rules": "last shorter bucket kept (partial=true); buckets touching a source gap not averaged"}
    return analyses
