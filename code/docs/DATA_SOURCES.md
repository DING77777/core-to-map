# Data sources

The interface reads GSWA **TSG Summary Mineral Log** CSV files directly. Each record summarises one metre along a drillhole, not a whole tray or a complete spectrum.

## Source files

Download source files into the project-root `data/` folder, following [data setup](../../data/README.md). Paths below are relative to that folder.

The recorded reference dataset on 15 October 2026 comprises 42 holes and 14,338 one-metre records. Download the source files separately. Eight reference paths are listed below. The other 34 are downloaded to inbox/SM_<hole_id>.csv, with 11,860 records. [download_manifest.json](../download_manifest.json) lists every file, official source page, download URL and SHA-256.

Added holes: 09THD028, 12DHDD0002, 15BRDD001, 17SRDD0004, 20CFRCD003, 22ACHD0001, AED022, AMDD003, BBDD0011, BCMH0072, BNRD023, CCUD001, CYDD0220, HCRD0051, JLS14DD002, KDD001, LJM-D007, MDDH0003, MFED069, MG19-003, MNDD0003, MOD7, MVRC041D, NDD17002, PLRCD001, RAGD039, RRLGDDD063, SCDD002, SCDD003, SGD001, TUR13DD003, TUR13DD004, UGD4107, YARDDH003.

Place compatible GSWA Summary CSVs directly in data/inbox and click Refresh library. Identical bytes are not loaded twice. Different versions of one hole are not silently overwritten. Files with incompatible format or processing metadata are rejected individually. Each refresh builds a manifest of the actual accepted sources.

| Hole | Relative path | Records | Depth span, m |
|---|---|---:|---|
| CMDD001 | nvcl_wa/CMDD001/supporting/SM_CMDD001.csv | 45 | 0–45 |
| CMDD002 | nvcl_wa/CMDD002/supporting/SM_CMDD002.csv | 100 | 50–150 |
| EHD001 | new_holes_20261015/SM_EHD001.csv | 448 | 0–451 |
| DRDD380 | new_holes_20261015/SM_DRDD380.csv | 709 | 603–1312 |
| RBDD008 | new_holes_20261015/SM_RBDD008.csv | 685 | 0–685 |
| TBDD126 | cluster_tbdd_20261015/SM_TBDD126.csv | 232 | 69–301 |
| TBDD127 | cluster_tbdd_20261015/SM_TBDD127.csv | 79 | 96–175 |
| TBDD128 | cluster_tbdd_20261015/SM_TBDD128.csv | 180 | 79–259 |

EHD001 lacks [28,29), [39,40) and [50,51) m records: its 0–451 m span contains 448 m of records. Span length is not actual coverage. Summary endpoints need not equal registered drilled depths.

Original downloads:

- [CMDD001](https://dasc.dmirs.wa.gov.au/download/metadata?fileName=Hylogger/Mineral_Logs/SM_CMDD001.csv)
- [CMDD002](https://dasc.dmirs.wa.gov.au/download/metadata?fileName=Hylogger/Mineral_Logs/SM_CMDD002.csv)
- [EHD001](https://dasc.dmirs.wa.gov.au/download/Metadata?fileName=Hylogger/Mineral_Logs/SM_EHD001.csv)
- [DRDD380](https://dasc.dmirs.wa.gov.au/download/Metadata?fileName=Hylogger/Mineral_Logs/SM_DRDD380.csv)
- [RBDD008](https://dasc.dmirs.wa.gov.au/download/Metadata?fileName=Hylogger/Mineral_Logs/SM_RBDD008.csv)
- [TBDD126](https://dasc.dmirs.wa.gov.au/download/metadata?fileName=Hylogger/Mineral_Logs/SM_TBDD126.csv)
- [TBDD127](https://dasc.dmirs.wa.gov.au/download/metadata?fileName=Hylogger/Mineral_Logs/SM_TBDD127.csv)
- [TBDD128](https://dasc.dmirs.wa.gov.au/download/metadata?fileName=Hylogger/Mineral_Logs/SM_TBDD128.csv)

Download in a browser and retain the filename. If a link changes, search [DASC](https://dasc.dmirs.wa.gov.au/) by hole name for the Summary Mineral Log. The application fingerprints loaded files and verifies data versions when restoring a query.

The [WA NVCL / NCI catalogue](https://thredds.nci.org.au/thredds/catalog/rs07/WA/catalog.html) supplies related full spectral archives. Those large archives are not required for summary queries and cannot directly replace the CSVs.

## Field meanings

Descriptive metadata and processing settings precede the CSV table. Its 49 numeric fields comprise 36 mineral-group proportions, two Invalid quality proportions, four feature wavelengths, six absorption depths and one albedo field. Availability varies by hole and depth.

- 2200W_AlOH: Al–OH feature position, in nm.
- 2200D_AlOH: absorption-feature depth, not drillhole depth.
- Mineral groups: algorithm-reported relative spectral proportions, not assay grades or established mass fractions.
- N.A.: defined by the source as "Not detected or below threshold"; not necessarily unscanned, and not zero.
- NULL or blank: unspecified missing values, retained rather than filled with zero.
- Entirely absent one-metre records: gaps in the source-record span, distinct from existing rows containing N.A.

Source processing is SWIR: TSA+ and TIR: jCLST, with Bin_min_threshold=0.05 and Scalar_min_depth=0.001. Cross-product comparisons must still respect spectral region, method, interpretation level and units.

Evidence record numbers refer to logical records after the descriptive header, not physical file-line numbers.

## Collar coordinates

Coordinates come from the separate [DASC HyLogger Drillhole Package, download 5464](https://dasc.dmirs.wa.gov.au/Download/File/5464):

    official_interim_20261009/extracted/
      INTERIM_HyLogger_Dataset_Package_GDA2020_DB/
        DATABASES/HyLogger_Dataset_Package.sqlite
        DOCUMENTS/METADATA/METADATA_INTERIM_Hylogger_GDA2020.pdf
        DOCUMENTS/Licence_CCBY4_intrim.pdf

The application verifies NVCL identity, main WAMEX CollarId and report identifiers before reading Longitude / Latitude. Missing packages or failed matches leave holes queryable but unlocated.

Regional markers use 0.1-degree groups; local collars retain GDA2020 coordinates. The Natural Earth WGS84 background is approximate and has no precise datum transformation. Landgate is requested directly in GDA2020. Surface positions do not establish underground trajectories. See [basemap sources](BASEMAP_SOURCES.md).

## Derived results

The application calculates threshold intervals, matched lengths and coverage without altering original indicators.

The Mineral Changes viewer uses source-matched results generated in `code/analysis/viewer/data` or a source- and method-matched cache in `code/work/change-viewer`. Generate results from downloaded summaries; they are not included in the repository. It uses 36 mineral-group fields over full-hole contiguous valid blocks; the current window clips the display rather than refitting it. These are candidate composition changes, not confirmed stratigraphic contacts, and are separate from threshold intervals and the query ZIP. Company logs are reference observations, with their availability stated.

The method encodes mineral-group N.A. as zero internally. This is an analysis assumption; source profiles and threshold queries preserve N.A. Parameter stability, where supplied, describes recurrence across tested settings, not correctness probability. Existing evaluation applies to the default sensitivity and 2 m minimum segment. New calculations do not inherit that validation automatically. See the [analysis guide](../analysis/README.md) for method and evaluation details.

TUR13DD003 summaries end at 817 m, while its collar record registers 631.6 m. The audit flags the conflict and retains the summaries without truncation.

The Core tray photographs section can read original NVCL archive photos after the matching files are installed. Reference examples use 12 CMDD001 trays and 23 CMDD002 trays. Matching TSG scan metadata and embedded JPEG identifiers establish tray/depth association. Whole-tray photos have no pixel-level depth calibration and are excluded from query ZIPs. The lower mineral-change viewer contains no photographs.

## Attribution and terms

Retain GSWA / State of Western Australia (Department of Mines, Petroleum and Exploration) attribution and original links. The project's MIT licence applies to its code and documentation, not third-party data.

The supplemental Licence_CCBY4_intrim.pdf contains CC BY 4.0 wording together with restrictions on third-party sharing/display. Their scope remains to be clarified with the organiser. Retain the original licence. A local preview or exported result does not itself establish public redistribution permission.

Obtain source datasets separately and generate derived outputs locally. Downloaded data, photos and generated results are excluded from version control.

