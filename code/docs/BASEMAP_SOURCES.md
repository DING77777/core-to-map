# Map background sources

The default **Aerial · Landgate** mode requests public Locate aerial imagery online. **Offline map** selects the Natural Earth background when it has been generated locally; see [data setup](../../data/README.md#optional-offline-map). Online failures are shown explicitly with the hole markers retained; users can select the offline mode themselves. None of these backgrounds contributes to scalar values, interval calculation or geological prediction.

## Landgate Locate aerial imagery

[Locate Mosaic (LGATE-322)](https://catalogue.data.wa.gov.au/dataset/locate-wa-mosaic) is Landgate's public, statewide background imagery service. Its public endpoint requires no ArcGIS Online account or API key:

```text
https://public-services.slip.wa.gov.au/public/services/SLIP_Public_Services/Locate/MapServer/WMSServer
```

The application requests WMS 1.3.0, layer `1`, transparent PNG, and `EPSG:7844`. The advertised GDA2020 output allows the local background to use the same geographic CRS as the verified source collar coordinates. WMS 1.3.0 BBOX order for this geographic CRS is south, west, north, east. The service renders the requested CRS; the client does not silently relabel a WGS84 image. This does not remove source imagery or collar-position error. Regional hole-group markers remain approximate 0.1-degree group positions.

The service inspection around TBDD126–128 on 2026-10-15 found 0.5 m pixels, capture batches from September 2010 and April 2011, and a stated accuracy of 5 m. These describe the inspected coverage, not all of WA. Image detail, capture date and positional accuracy are separate properties. The mosaic is not live imagery and should not be labelled as a 2025 acquisition.

The catalogue identifies a custom [SLIP Transaction Personal Use Licence](https://www.landgate.wa.gov.au/siteassets/documents/location-data-and-services/licensing/slip-transaction-personal-use-licence-300523.pdf), covering personal and noncommercial use. It is not CC BY, public-domain imagery or an unrestricted commercial basemap. Retain **© Western Australian Land Information Authority (Landgate)**. The code archive and result exports contain no Landgate images; connecting to a public service does not grant permission to redistribute or commercialise its imagery.

Browser requests contain the visible map extent and requested image dimensions, without hole identifiers, scalar records or query thresholds. The application does not bulk-download imagery. Failure to load a background leaves query results available.

The same endpoint can be used in QGIS. `code/docs/qgis_landgate_wms.xml` contains a WMS connection in the format read by QGIS 3.44. `code/docs/QGIS_CONNECTION.txt` covers import and loading the current result pack's `holes.csv` as GDA2020 points. This connection is not a completed QGIS plugin.

## Natural Earth offline background

The offline map uses Natural Earth public-domain cartographic data. It contains no HyLogger input, borehole coordinate, query output, or user path. The data were prepared locally from complete public distribution files, using a fixed Australia-wide selection rectangle. No point coordinates, project viewport, or location-specific tile request was sent to an external map service during that preparation. After generating `code/static/basemap.json`, offline mode requires no account, API key or runtime download.

## Licence and attribution

Natural Earth's [official terms](https://www.naturalearthdata.com/about/terms-of-use/) place its raster and vector data in the public domain and permit modification and electronic redistribution. Permission and attribution are not required; the application nevertheless displays **Made with Natural Earth**. These terms govern the background data only. They do not remove any separate restrictions on HyLogger/interim data or borehole overlays. Review those separately before sharing screenshots, exports or a public demonstration.

## Sources and acquired versions

The official product pages identify each theme:

- [Countries](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/): polygons used as land/coastline context.
- [Lakes and reservoirs, including the Australia supplement](https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-lakes/).
- [Roads](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/roads/).
- [Populated places, simple attributes](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-populated-places/).

The distribution archives are available from the official download host linked below. Versions are recorded from each archive's `.VERSION.txt`; SHA-256 fingerprints identify the reference file bytes. The Australia lakes archive identifies itself as **5.0.0-pre9**.

| Archive | Acquired version | Bytes | SHA-256 |
|---|---|---:|---|
| [ne_10m_admin_0_countries.zip](https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_0_countries.zip) | 5.1.1 | 4930492 | `ce1ac7036499a0edd641fbc093cd209a98f96a49d2eca8480aaacad35138a7f6` |
| [ne_10m_roads.zip](https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_roads.zip) | 5.0.0 | 9075919 | `880b235383a1e1ccf33f4ea6f82b6755a2ffbce07e3974e412b43e88fe954ae9` |
| [ne_10m_populated_places_simple.zip](https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_populated_places_simple.zip) | 5.1.2 | 652145 | `2963ee08f7743f13f37d5243acd77a2f7a510e26a36c7e04b920f1b381f2b251` |
| [ne_10m_lakes.zip](https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_lakes.zip) | 5.0.0 | 2349685 | `0803a06f9c3cb4671d89b68c48b142aad9366ba40f665245e12a913fbc61722a` |
| [ne_10m_lakes_australia.zip](https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_lakes_australia.zip) | 5.0.0-pre9 | 98367 | `44c604c90ae459947b41f082973d58a7f0a1da61e9928ee89464ba7a8b00e00e` |

The five complete archives total 17,106,608 bytes. No source raster was used.

## CRS, scale and display policy

Natural Earth's [official features documentation](https://www.naturalearthdata.com/features/) identifies geographic WGS84 coordinates (EPSG:4326). Every acquired shapefile `.prj` was also checked for the WGS84 datum and degree units. The label **10m means 1:10,000,000 scale**, not ten-metre resolution. Features are generalised regional cartography, not authoritative road routing, property boundaries, imagery or hundred-metre terrain detail. Do not infer that a missing feature is absent on the ground.

The separate local collar view retains the verified native GDA2020 coordinates. The Natural Earth regional background is WGS84. [NSW Spatial Services](https://www.nsw.gov.au/environment-land-and-water/surveying/geodesy-and-geocentric-datum-of-australia/gda2020) explains that unspecified WGS84 can have metre-level misalignment and is suitable only for low-accuracy applications (about 3 m); GDA2020 and WGS84 must not silently be relabelled as identical datums. The Landgate background instead requests the server's EPSG:7844 output, as described above.

For broad context only, the application may show a borehole-group area rounded to **0.1 degree** (roughly a ten-kilometre region at Australian latitudes), clearly labelled as approximate. This coarse contextual display does not assert a precise datum transformation, exact pin alignment, survey accuracy or a safe navigation destination. Precision measurements and local inspection belong in the native GDA2020 view. Natural Earth should not be enlarged as if it contained site-scale detail.

## Reproducible preparation

The Python-standard-library builder reads the ZIPs directly, checks their SHA-256 fingerprints and CRCs, verifies WGS84 `.prj` declarations and UTF-8 encoding, and matches geometry/attribute record counts. Run it against a local directory containing the five archives:

```powershell
python -B code/tools/build_basemap.py --sources PATH_TO_NATURAL_EARTH_ZIPS --output code/static/basemap.json
```

The preparation uses the fixed selection bbox `[112, -44, 154, -10]` in longitude/latitude order. Points are selected inside that rectangle. Line parts and polygon exterior rings are selected by bounding-box intersection; associated holes are retained. Selected shapes are **not geometrically clipped or simplified**, so some coordinates extend beyond the selection rectangle. The renderer must clip the view. Polygon rings are converted to GeoJSON winding conventions, and DBF whitespace/NUL padding is removed from labels. Source geometry, not auxiliary latitude/longitude attribute columns, determines map position.

The recorded reference GeoJSON contains **4 land features, 115 lake features, 487 road features and 227 place points** (833 features total). Properties use `layer: land|lakes|roads|places`, `name`, `scalerank`, and portable source identifiers. The output is 1,780,752 bytes with SHA-256 `eab0c4cbefe764e4ced3a0b3e64550bcd76a938b8f8e7defa231b4ed870ef1e8`.

## Validation and known source differences

All output coordinates are finite and within valid geographic ranges; polygon rings close, use the expected winding, and have properly associated holes. All 227 retained place geometries were independently checked through their original SHX record offsets. The builder reproduces identical output bytes.

In the source place file, 222 retained SHP geometries agree with the DBF longitude/latitude attributes within their six-decimal rounding. Five places differ more: **Derby, Wyndham, Halls Creek, Newcastle and Sydney**. The GeoJSON preserves the formal SHP geometry; it does not substitute the inconsistent attribute coordinates. This audit did not independently survey those locations. Treat all labels and roads as regional reference information.


Transparent no-data areas in the aerial image reveal the coarse Natural Earth geographic background underneath. This is not replacement aerial imagery and does not add image detail.
