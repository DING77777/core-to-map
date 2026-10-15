# Add summary logs

Place additional **GSWA TSG Summary Mineral Log CSV** files directly in this folder, keeping their original filenames and descriptive header rows. In Core to Map, select **Refresh library** or restart the application.

Nested subfolders are not scanned. The hole identity comes from the CSV's Dataset metadata, not just its filename.

The reader supports the GSWA one-metre summary format. A raw TSG file, full spectrum file or unrelated CSV cannot be substituted for a summary log. Identical files are read once; incompatible files appear in the library audit.

Download logs from [DASC](https://dasc.dmirs.wa.gov.au/) by searching for the drillhole name. A hole can be explored without a verified collar, but it will have no map location.

CSV files directly in this folder are local inputs and are excluded from version control.
