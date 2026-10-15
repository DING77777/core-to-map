# Local data

Store downloaded source files in this folder. Source datasets are not included in the repository.

## Summary logs and collars

Place original GSWA Summary Mineral Log CSVs directly in **data/inbox/**, then double-click **CoreToMap.exe**. No datasets are downloaded automatically. If the folder is empty, the launcher waits for you to add files and press **Enter**. While the application is running, use **Refresh library** after adding files.

The [download manifest](../code/download_manifest.json) identifies the 42 drillholes, exact relative destinations, official URLs and SHA-256 fingerprints. It covers:

09THD028, 12DHDD0002, 15BRDD001, 17SRDD0004, 20CFRCD003, 22ACHD0001, AED022, AMDD003, BBDD0011, BCMH0072, BNRD023, CCUD001, CMDD001, CMDD002, CYDD0220, DRDD380, EHD001, HCRD0051, JLS14DD002, KDD001, LJM-D007, MDDH0003, MFED069, MG19-003, MNDD0003, MOD7, MVRC041D, NDD17002, PLRCD001, RAGD039, RBDD008, RRLGDDD063, SCDD002, SCDD003, SGD001, TBDD126, TBDD127, TBDD128, TUR13DD003, TUR13DD004, UGD4107 and YARDDH003.

Sources:

- [DASC](https://dasc.dmirs.wa.gov.au/): search a hole name for its TSG Summary Mineral Log. For example, [SM_CMDD001.csv](https://dasc.dmirs.wa.gov.au/download/metadata?fileName=Hylogger/Mineral_Logs/SM_CMDD001.csv).
- [HyLogger Drillhole Package](https://dasc.dmirs.wa.gov.au/Download/File/5464): official collar and associated data, including its metadata and licence. Extract the required members into the paths recorded in the manifest.
- [WA NVCL catalogue](https://thredds.nci.org.au/thredds/catalog/rs07/WA/catalog.html): full spectral packages and original core tray photographs. These are optional for summary queries and must be obtained separately.

For additional compatible summary CSVs, use [inbox/](inbox/README.md) and refresh the library. Missing collars leave a hole available for profile inspection but without a map location.

Saved mineral-change data belong under **code/analysis/viewer/data/** and associated analysis outputs under **code/analysis/results/**. Generated results are not included in the repository. Using the bundled NumPy runtime, select **Calculate mineral changes** to create results locally from available summary files.

## How files are recognised

The application has two summary-file entry points:

- Eight reference holes also support the fixed relative paths in `code/datasets.py`.
- Additional CSVs are read directly from **data/inbox/**. The application does not search nested folders inside the inbox.

For example:

```text
data/
  inbox/
    SM_NEW_HOLE.csv
```

The filename alone does not establish compatibility. The reader checks the product header, the **Dataset** hole identifier, **Depth_from_(m)** and **Depth_to_(m)** columns, required indicator fields, processing settings and source definitions. Known files must match their recorded SHA-256 fingerprints. Incompatible files appear in the input audit. Identical copies of a hole are read once; conflicting accepted versions are excluded for review.

After adding a CSV, click **Refresh library** or restart. Keep original descriptive headers and source values. Raw `.tsg` or `.bip` files cannot replace a summary CSV.

Collar coordinates use the separate official SQLite database and metadata files at the paths in the manifest. Missing or unmatched coordinates leave profiles available without a map point.

Optional core photographs require matching TSG metadata and the native archive structure:

```text
data/nvcl_wa/<hole_id>/extracted/<package>/<hole_id>_tsg.tsg
data/nvcl_wa/<hole_id>/extracted/<package>/<hole_id>_0001.jpg
```

Obtain these from the WA NVCL catalogue linked above. Keep tray JPEGs and their matching TSG file together; a standalone photograph has no verified depth association.

## Optional offline map

To create the optional offline background, download these five archives into **data/natural_earth_sources/** without extracting or renaming them:

- [ne_10m_admin_0_countries.zip](https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_0_countries.zip)
- [ne_10m_roads.zip](https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_roads.zip)
- [ne_10m_populated_places_simple.zip](https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_populated_places_simple.zip)
- [ne_10m_lakes.zip](https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_lakes.zip)
- [ne_10m_lakes_australia.zip](https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_lakes_australia.zip)

From the package folder, run:

```powershell
.\runtime\python.exe -B code/tools/build_basemap.py --sources data/natural_earth_sources --output code/static/basemap.json
```

The builder accepts the recorded source versions and checks their fingerprints. If a source changes, obtain the matching version rather than bypassing verification. Natural Earth is generalised regional cartography at 1:10,000,000 scale. Its name does not imply ten-metre resolution. See [Natural Earth terms](https://www.naturalearthdata.com/about/terms-of-use/).

Online aerial imagery uses [Landgate Locate Mosaic](https://catalogue.data.wa.gov.au/dataset/locate-wa-mosaic) and requires internet access. Images are requested for the visible map extent and are not included in the package.

## Attribution and sharing

Source data: GSWA / State of Western Australia, Department of Mines, Petroleum and Exploration. Retain the downloaded metadata, original licence documents and source links. The project's MIT licence covers its original code and documentation.

Keep datasets, photos, basemap files, calculated results and caches out of version control. The supplied ignore rules help maintain that separation after running the application locally.
