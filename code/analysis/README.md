# Core to Map — analysis tools

**Author:** Ding Qing  
**Date:** 15 October 2026

Python tools from the Core to Map entry to the GSWA HyLogger Hackathon 2026. They do three things:

1. Read GSWA *TSG Summary Mineral Log* CSVs exactly as published and turn each hole into the same set of files (`run_pipeline.py`).
2. Search for continuous depth intervals that meet a condition, as an independent check of the interval search in the main application.
3. Run one experiment: find depths where the spectral mineralogy changes along a hole, and measure how often those depths line up with changes in the company drill logs. It was tested on 40 holes.

A small viewer (`viewer/index.html`) shows the mineral groups and candidate changes for any hole, and can be rebuilt with one command for new holes. There are also smaller experiments on the raw scans and core photos of CMDD001 and CMDD002 (see the end of this page).

## Data

Source datasets are stored in `../../data/`, relative to this `code/analysis/` folder. The scripts search that folder recursively by filename. Source datasets and generated results are not included in the repository. See the [data instructions](../../data/README.md).

| What | Source | Used for |
|---|---|---|
| `SM_<hole>.csv` for the 42 holes in the [download manifest](../download_manifest.json) | DASC; the manifest records each source URL and SHA-256 | summary profiles, intervals and change analysis |
| Interim HyLogger Dataset Package, `HyLogger_Dataset_Package.sqlite` | DASC download 5464, `https://dasc.dmirs.wa.gov.au/Download/File/5464` | collar locations; company drill logs used as the reference in the experiment |
| Raw TSG packages for CMDD001 and CMDD002 (optional) | NCI THREDDS, `https://thredds.nci.org.au/thredds/catalog/rs07/WA/catalog.html` | scan-level work and core photos only |

## Optional research setup

The desktop viewer and its mineral-change calculation use the bundled runtime. The commands below reproduce the separate research experiments and figures, which require additional packages.

Use Python 3.12 or newer. Run the commands below from `code/analysis/`. In a terminal opened at the package root, first run `cd code/analysis`.

```
python -m pip install -r requirements.txt
```

Reading the CSVs and the interval search need only the standard library. The experiment needs numpy, scipy and matplotlib.

## Run

Hole packages:

```
python run_pipeline.py --inputs ../../data --out packages --sqlite "../../data/official_interim_20261009/extracted/INTERIM_HyLogger_Dataset_Package_GDA2020_DB/DATABASES/HyLogger_Dataset_Package.sqlite"
```

Reproduce the candidate-change experiment locally:

```
python reproduce_boundaries.py --data-root ../../data --sqlite "../../data/official_interim_20261009/extracted/INTERIM_HyLogger_Dataset_Package_GDA2020_DB/DATABASES/HyLogger_Dataset_Package.sqlite"
```

This writes `output/boundary_results_per_hole.csv`, `output/boundary_experiment_summary.json`, one `boundaries.json` per hole and the two figures. Generated evaluation outputs, packages and caches remain local and are excluded from version control.

One review sheet per hole (needs the hole packages from the step above):

```
python scripts/plot_change_sheets.py --packages packages --boundaries output --out output/sheets
```

Tray-photo rows next to the mineral strips (needs the extracted raw package of CMDD001 or CMDD002):

```
python scripts/plot_core_photo_comparison.py --tsg-dir "../../data/PATH_TO_EXTRACTED_CMDD002_TSG" --hole CMDD002 --from 129 --to 146 --packages packages --boundaries output
```

Replace `PATH_TO_EXTRACTED_CMDD002_TSG` with the relative folder containing `CMDD002_tsg.tsg` and the original tray JPEG files.

The output format is described in [docs/OUTPUT_FORMAT.md](docs/OUTPUT_FORMAT.md).

## Change viewer

Place compatible `SM_<hole>.csv` files under `../../data/`, and retain `HyLogger_Dataset_Package.sqlite` there if you want company-log changes shown. Then build the viewer:

```
python build_viewer.py --data ../../data
```

Every hole found is processed with the same settings. Use the main application to open the integrated viewer. A locally built standalone `viewer/index.html` can also be opened directly in a browser without an internet connection.

In the viewer you can:

- tick up to six holes and set a depth window (the mouse wheel zooms); group colours and ordering stay fixed when the selected holes change;
- hover over a line to see which mineral groups changed and by how much;
- switch the sensitivity (more or fewer lines; the default is the setting tested on 40 holes);
- download the segment table for the current view.

A link such as `viewer/index.html#holes=TBDD126,TBDD127,TBDD128&from=96&to=175` opens a given view, so another application can link straight to it. Generate `viewer/data/` from downloaded summaries, or use Calculate mineral changes in the main application with NumPy installed.

The strips show the six leading groups saved for each region of each hole; the remainder is grey. These are relative spectral proportions, not mass percentages. The full 36-group calculation is unchanged. Segment exports split at coverage blocks and gaps, and use only the displayed portions of metre records. Validation captions always refer to the full-hole tested default, even when other settings or a smaller depth range are displayed.

The main application serves this viewer at `/change-viewer/index.html`. Add `?embed=1` for an inline view controlled by the parent application's holes and depth range. Hash parameters `beta`, `min` and `showlog` preserve the sensitivity, shortest segment and company-log overlay. Embedded candidate clicks return the hole and depth to the parent for inspection. The embedded view contains no core photographs.

## Candidate spectral changes

**Question.** Without telling the method anything about rock types, can it find the depths where a hole's mineralogy changes? And do those depths agree with where geologists changed the lithology code in the company log?

**Input.** The 36 mineral-group proportions in the 1 m summary (13 SWIR groups and 23 TIR groups; the two "Invalid" columns are left out). In the evaluated files, the reported groups in each metre add up to 1 for each spectral range, and the source never writes 0. A group marked N.A. ("not detected or below threshold") is encoded as 0 for this calculation only. This is an analysis assumption; source profiles and threshold queries preserve the original N.A. state. Holes are processed in continuous blocks and never across a missing metre.

**Method.** Each hole is split into segments by exact optimal partitioning: the split points minimise the within-segment sum of squares, plus a fixed penalty for every extra split point. The penalty is β·σ²·ln(n), where σ² is the hole's own metre-to-metre noise, estimated without any labels. A split therefore needs a change in the average mineral mix that is clearly larger than the hole's normal fluctuation. Segments must be at least 2 m long, so a single odd metre is never a change. The split points are the "candidate spectral changes". The implementation was checked against an exhaustive search on 25 small random examples.

**Reference.** A company-log code change is a depth where two touching log intervals have different, non-empty codes. For CMDD001 and CMDD002 the logs filed with report 103450 are used, because the primary CMDD002 log has no codes. These logs are interpretations made by different companies at different levels of detail. They are a reference, not ground truth.

**Protocol.** The rules were fixed before any test hole was scored.

- β (1, 2, 4 or 8) and the minimum segment length (2, 3 or 5 m) were chosen on CMDD001 and CMDD002 only. The choice was β = 2 and 2 m.
- The settings were then locked and applied once to 40 test holes:
  - six chosen at the start (EHD001, DRDD380 and RBDD008 drawn at random, plus the TBDD126–128 cluster);
  - ten drawn at random (seed 20261015) from the 897 catalogue holes that have a summary CSV, a verified collar identity and at least three log code changes;
  - 24 more drawn at random (seed 20261016) from the remaining eligible holes.

  Every drawn hole is reported.
- A hole is "not scored" only when its log has no code change inside the depths the HyLogger scanned. This rule was set before the draws. No hole was removed for scoring badly.
- A candidate counts as matched if it lies within 1 m of a reference change. Each candidate and each reference change can be matched only once.
- Three comparisons use the same number of lines in the same usable depth ranges:
  - random placement, repeated 1,000 times;
  - equal spacing;
  - a simple detector that only looks at the 2200 nm Al–OH wavelength.

**Results.** None of the 40 test holes took part in choosing the settings.

| | Holes |
|---|---:|
| Better than random lines (p < 0.05) | 27 |
| Not better than random lines | 9 |
| Not scored (no log change inside the scanned depths) | 4 |

| All 40 test holes together, 1 m tolerance | F1 |
|---|---:|
| Candidate spectral changes (36 mineral groups) | **0.32** (precision 0.36, recall 0.29) |
| Random lines, same number (mean; 95th percentile) | 0.16; 0.17 (p = 0.001) |
| Equal spacing | 0.17 |
| Simple 2200 nm detector | 0.25 |

Reproduce the experiment to generate `output/boundary_results_per_hole.csv`, which records per-hole evaluation results. The source-file list, URLs and fingerprints are in the [download manifest](../download_manifest.json).

The experiment also produces a figure comparing reference changes found by candidate and random lines.

The two segmentations used for comparison, with the same protocol, score lower. Six mineral-feature scalars score 0.31 against their own random baseline of 0.20. The 2200 nm wavelength alone scores 0.27 against 0.19.

**What this shows.** In 27 of the 36 holes that could be scored, the candidates line up with log changes clearly more often than random lines. The simple 2200 nm detector beats the 36-group method in six holes, but loses overall.

Failures depend partly on how finely the company logged the hole:
- **Holes with up to 20 log changes per 100 m:** 23 of 27 pass.
- **Holes with more than 20 log changes per 100 m:** 4 of 9 pass. In those holes many units are thinner than 1 m, which a 1 m summary cannot resolve. In BCMH0072, for example, 68 of 74 changes sit next to such a unit.
- **The coarsest log, EHD001:** it records 3 changes per 100 m and none between 186 m and 366 m, while the spectra change many times there.

Different companies log at different levels of detail; one fixed rule applied to every hole makes those differences visible.

The three TBDD holes are 60–164 m apart in one project, and pairs such as SCDD002/003 and TUR13DD003/004 have consecutive names, so they probably come from the same projects. These are related cases rather than fully independent tests.

**What it does not show.**

- F1 is not an accuracy for identifying rock types.
- A candidate is not a confirmed geological contact.
- Thin units (under 1 m) are kept in the scoring even though the method cannot see them.

The candidates are best read as places worth a second look in the core photos or the full spectra.

**Review sheets.** Generate a figure and a segment table for each hole using `scripts/plot_change_sheets.py` and the commands above.

- **Figure.** Each figure shows:
  - the main SWIR and TIR mineral groups metre by metre;
  - every candidate change, solid where a company-log change lies within 1 m and dashed where none does;
  - the company-log changes;
  - the eight largest changes, written out (for example, TBDD126 at 84 m: Serpentine (SWIR) 0.61 → 0.09).
- **Table.** Each table lists every segment with its depth range, its main mineral groups and what changed at its top.


## Raw scans and core photos (CMDD001 and CMDD002)

These optional research scripts need the raw TSG packages and GSWA's [pytsg reader](https://github.com/Geological-Survey-of-Western-Australia/pytsg), plus pandas and scikit-learn for the scan-level classification experiment. They are separate from the application's NumPy-only mineral-change calculation. Use `python scripts/run_scan_analysis.py --help` and `python scripts/run_lithology_experiment.py --help` for input options. For scan summaries, run `python scripts/run_scan_analysis.py --inputs ../../data/nvcl_wa --out work/analyses`. Tray-photo comparisons use `scripts/plot_core_photo_comparison.py` as shown above. Keep their generated outputs local.

**Reproducing the 1 m summary.** The published 1 m values of 2200W, 2250W, 2200D and 2250D were recalculated from the individual scans, for all 145 metres of the two holes. The rule is: average the scans whose absorption depth is at least 0.001, counting a scan in a metre when its depth is in (from, to]. The largest difference is 0.0002 nm for wavelength and 1e-7 for depth.

**Spread inside one metre.** One summary value can hide a wide spread. In CMDD002 at 50–51 m, 89 scans fall in the metre and 75 pass the depth filter. Of those 75, 33 (44%) have a 2200 nm wavelength of at least 2200 nm.

**Felsic vs mafic.** A random forest was trained on the scans of one hole, using the company-log labels from report 103450, and tested on the other hole.

| Test hole | Random forest, balanced accuracy | Shallow tree on the dominant mineral group | Metres where the majority prediction matches the log |
|---|---:|---:|---:|
| CMDD002 | 0.80 | 0.62 | 80 of 99 |
| CMDD001 | 0.76 | 0.67 | 39 of 45 |

Two holes are not enough to call this a validated classifier.

**Tray photos next to the spectra.** Every HyLogger sample header records its tray, row, position along the row (mm) and depth. The tray-photo plotting script shows the original tray-photo rows for a depth window, as photographed. Each row carries its logged depth range, and each candidate change is marked at its position along the row.

In CMDD002 at 129–146 m, the candidate changes at 131, 134, 140 and 144 m fall where the core changes between dark and pale. The depth blocks written on the core (131.0, 134.0, …) sit right next to the red lines, which confirms the depth registration. CMDD002 was one of the two holes used to choose the change settings, so this is an illustration rather than a test.

Generate the CMDD002 129–146 m illustration using the tray-photo command above and the original NVCL files.

## Licence and data use

- **Code.** MIT licence (see `LICENSE`).
- **GSWA data.** The GSWA data belong to the State of Western Australia and keep their own licences.
- **Interim package.** Retain its supplied licence and metadata. Its licence document contains both CC BY 4.0 and wording restricting third-party sharing; their scope remains unresolved. Obtain source datasets separately and generate figures, tables and per-hole results locally. The project MIT licence does not relicense any source data or permit their redistribution.
