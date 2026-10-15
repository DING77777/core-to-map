# Code guide

Core to Map runs a local Python web server and displays the interface in a browser.

| File or folder | Purpose |
|---|---|
| `app.py`, `launch.py`, `../start.ps1` | Start and serve the application. |
| `static/` | Browser interface, linked maps and depth profiles. |
| `datasets.py`, `library.py`, `summaries.py` | Discover and read compatible summary logs. |
| `metrics.py`, `depth_ranges.py` | Indicator definitions and available depth ranges. |
| `engine.py`, `comparison.py` | Threshold intervals and aligned comparisons. |
| `coords.py` | Match source collars to drillhole identities. |
| `core_photos.py` | Find local core photographs and their depth references. |
| `change_viewer.py`, `analysis_overlay.py` | Load and serve mineral-change results. |
| `analysis/` | Mineral-change calculations and viewer files. |
| `exports.py` | Result packs, query settings and source references. |
| `download_data.py`, `download_manifest.json` | Download and verify the named public data sources. |
| `tools/build_basemap.py` | Build the optional Natural Earth offline background. |
| `docs/` | Source, interpretation and map documentation. |

Inputs are stored in **../data/**. The bundled interpreter is in **../runtime/**. New analysis caches are created locally when calculations run. Downloaded inputs, generated results and caches are excluded from version control.

## Windows launcher

`CoreToMap.cs` starts the bundled Python runtime and reopens an existing instance from the same folder when available. The application and analysis remain in the Python modules above.

Rebuild the launcher on Windows from the project folder:

```powershell
& "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:exe /platform:anycpu /optimize+ /reference:System.Web.Extensions.dll /out:CoreToMap.exe code/CoreToMap.cs
```
