"""Binary comparison experiment against company logs: felsic vs mafic from scan spectra.
(optional; numpy, pandas, scikit-learn, pytsg). Two holes only - an experiment, not a validated
lithology classifier and not a mineralisation predictor.

Question: do the raw VNIR-SWIR and TIR spectra carry information about the logged rock type,
beyond the dominant mineral group that TSA/jCLST already report?

Design choices (stated so they can be challenged):
* Labels: company geology log codes from WAMEX report 103450 (alternate collar IDs 3663110/3663111,
  one coding system in both holes): FRG, FAG -> felsic; GAM -> mafic. Other codes (e.g. VQZ quartz
  vein) are excluded. The official code dictionary has not been obtained; the mapping and the
  depth alignment between log and scans are NOT independently confirmed. Labels are a
  geologist's interval interpretation, not ground truth.
* Train on one whole hole, test on the other (no random split: neighbouring scans are nearly
  identical, so a random split would leak and inflate scores).
* Same scans for every model: NIR Final Mask == 1 and TIR Final Mask == 1, label available.
  This is an experimental choice. (Observation only: in CMDD001/CMDD002 every scan with
  2200D >= 0.001 also has Final Mask == 1; the meaning of Final Mask itself is not verified, and
  the summary-reproduction code does not use Final Mask.)
* Comparison baselines: majority class (balanced accuracy 0.5) and a shallow decision tree
  (depth 1 or 3) trained on one-hot dominant TSA SWIR / jCLST TIR group per scan.
* NIR and TIR scans are paired by sample index after checking tray/line/position are identical.
* The exported per-metre predictions come from the SAME model whose scores are reported with them.

Author: Ding Qing
Date: 2026-10-15
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

LABEL_MAP = {"FRG": "felsic", "FAG": "felsic", "GAM": "mafic"}
SENTINEL_BELOW = -1.0e38


def load_hole(tsg_dir, hole_id):
    from pytsg import read_spectra
    tsg_dir = Path(tsg_dir)
    nir = read_spectra(tsg_dir / f"{hole_id}_tsg.tsg", tsg_dir / f"{hole_id}_tsg.bip", spectrum_name="nir")
    tir = read_spectra(tsg_dir / f"{hole_id}_tsg_tir.tsg", tsg_dir / f"{hole_id}_tsg_tir.bip", spectrum_name="tir")
    for c in ("T", "L", "P"):
        if not (nir.sampleheaders[c].values == tir.sampleheaders[c].values).all():
            raise ValueError(f"{hole_id}: NIR and TIR samples are not paired ({c} differs)")
    return nir, tir


def _num(s):
    a = pd.to_numeric(s, errors="coerce").to_numpy(dtype=float)
    a[a < SENTINEL_BELOW] = np.nan
    return a


def labels_from_log(sqlite_path, collar_id, depth):
    con = sqlite3.connect(f"file:{Path(sqlite_path).as_posix()}?mode=ro", uri=True)
    log = pd.read_sql("select FromDepth, ToDepth, CompanyLithologyCodeMerged code from wamex_dh_geology "
                      "where CollarId = ? order by FromDepth", con, params=(collar_id,))
    con.close()
    lab = np.array([None] * len(depth), dtype=object)
    for r in log.itertuples():
        if r.FromDepth is None or r.ToDepth is None:
            continue
        lab[(depth >= r.FromDepth) & (depth < r.ToDepth)] = LABEL_MAP.get(r.code, f"other:{r.code}")
    return lab, log


def features(nir, tir, which):
    wl = nir.wavelength
    parts = []
    if "swir" in which:
        sw = nir.spectra[:, (wl >= 1300) & (wl <= 2500)].astype(float)
        sw = sw / sw.mean(axis=1, keepdims=True)
        parts += [sw, np.diff(sw, axis=1)]
    if "tir" in which:
        t = tir.spectra.astype(float)
        t = t / np.where(np.abs(t.mean(axis=1, keepdims=True)) < 1e-9, 1, t.mean(axis=1, keepdims=True))
        parts += [t, np.diff(t, axis=1)]
    return np.hstack(parts)


def group_onehot(series_list, cats=None):
    vals = [s.astype(str).fillna("") for s in series_list]
    if cats is None:
        cats = [sorted(set(v)) for v in vals]
    cols = [np.stack([(v == c).to_numpy() for c in cs], 1) for v, cs in zip(vals, cats)]
    return np.hstack(cols).astype(int), cats
