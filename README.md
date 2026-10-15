# Core to Map

Explore HyLogger drillholes through linked maps, depth profiles and mineral-change views.

**Team:** Core to Map  
**Author, member and captain:** Ding Qing  
**Date:** 15 October 2026  
**Challenge:** Data Visualisation & Interactivity — GSWA HyLogger Hackathon 2026

Core to Map brings indicators from different drillholes into one local viewer. Compare measurements along depth, find continuous intervals matching a condition, inspect candidate mineral changes and trace observations to their source records.

## Start on Windows

1. Extract the complete folder to a writable location.
2. Place original GSWA Summary Mineral Log CSVs directly in **data/inbox/**, keeping their `SM_<hole>.csv` filenames and descriptive headers.
3. Double-click **CoreToMap.exe**. The interface opens in your browser. Keep the command window open while using the application; press **Ctrl+C** to stop.

The Windows x64 package includes Python and NumPy; no separate Python installation or account is needed. Keep **CoreToMap.exe**, **code/**, **data/** and **runtime/** together. **START.cmd** opens the same application. Opening the EXE again reuses a running instance from this folder when available. The local port may vary.

The application does not download datasets on startup. If no summary CSVs are present, the command window asks you to add files to **data/inbox/** and press **Enter**. See [data setup](data/README.md) for original source links, compatible inputs, coordinates and optional photographs.

A CSV alone is enough to inspect a hole's indicators. Map locations also require the official collar package. Online aerial imagery requires internet access; the optional offline background can be generated using the data setup instructions.

### Run from Python source

With Python 3.12 or newer, run from the project folder:

```powershell
python -m pip install -r code/requirements.txt
python -B code/launch.py
```

NumPy is required for new mineral-change calculations. See [runtime information](runtime/README.md).

## Use

1. Select drillholes from the map or **Browse group**, then choose **Add to analysis list**.
2. Set a depth window and indicators, then click **Update view**.
3. Inspect aligned profiles. Hover or pin a depth to see indicator values and source records.
4. Enable **Highlight a condition** to find continuous matching intervals. Export a result pack or restore its query later.
5. Open the mineral-change viewer. Load matching saved results or calculate them from the source summaries.

To add a compatible GSWA TSG Summary Mineral Log, place the original CSV directly in **data/inbox/** and click **Refresh library**. Preserve its descriptive headers. A hole can be inspected without collar coordinates, but it will not have a map location.

## Data and interpretation

The recorded reference dataset comprises 42 drillholes and 14,338 one-metre summary records from GSWA. Source files are downloaded separately. The manifest records the hole list, official URLs, target paths and SHA-256 fingerprints. Summary logs and collar information come from [DASC](https://dasc.dmirs.wa.gov.au/); optional full spectral packages and core photographs come from the [WA NVCL catalogue](https://thredds.nci.org.au/thredds/catalog/rs07/WA/catalog.html).

Mineral proportions are spectral interpretations, not assay grades. N.A., missing records and numerical zero remain distinct in source profiles and threshold queries. Mineral-change candidates require geological interpretation. Surface collars do not describe underground hole trajectories. The [analysis guide](code/analysis/README.md) documents the method, evaluation and limitations.

Landgate aerial imagery is requested online. The optional Natural Earth background is generated locally using the [data setup instructions](data/README.md#optional-offline-map).

## Project files and licence

**code/** contains the application and analysis tools. **data/** holds downloaded inputs. Generated results and caches are excluded by the supplied ignore rules. See the [code guide](code/FILE_GUIDE.md).

Original project code and documentation use the [MIT licence](LICENSE). GSWA data, Natural Earth and Landgate imagery retain their respective source terms and attribution. This repository contains no source datasets or generated results.
