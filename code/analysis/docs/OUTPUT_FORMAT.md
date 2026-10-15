# Output format (hole packages, v0.2)

**Author:** Ding Qing  
**Date:** 15 October 2026

`run_pipeline.py` turns every GSWA TSG Summary Mineral Log it finds into the same folder structure,
so a viewer or notebook can read any hole without per-hole code. Source files are only read. Run commands from `code/analysis/`, with source data under `../../data/`. The paths below are relative to `code/analysis/`. Generated outputs are created locally and are not included in the repository.

```
packages/
  manifest.json              queryable_holes, metadata_groups, processing log, catalogue summary
  _catalog/catalog.json      every index entry (1,951 drillhole DATA ENTRIES, not independent holes)
  _catalog/catalog.geojson   same, located entries, Point features, GDA2020 (EPSG:7844) as supplied
  <HOLE_ID>/hole.json        metadata, provenance, coverage, review, registry, occurrence, analyses
  <HOLE_ID>/metres.json      1 m values, column-oriented (number | "NA" | "BLANK" | "INVALID")
  <HOLE_ID>/metres.csv       same rows with original source tokens
  <HOLE_ID>/records_long.csv one row per (record, metric): hole_id, from_m, to_m, metric_id, value, raw_token,
                             unit, kind, region, interpretation_level, algorithm, quality_status,
                             source_file, source_sha256, source_record_no
  <HOLE_ID>/scan_stats.json  OPTIONAL — only where the raw TSG package was processed (CMDD001/002)
  <HOLE_ID>/lithology.json   OPTIONAL — two-hole ML experiment only (CMDD001/002)
```

## Rules for using the outputs

1. **Only `manifest.queryable_holes` enter queries.** `import_review.status = "quarantined"` packages
   are for inspection only. Conflicting duplicate Dataset files are not packaged at all.
2. **Compare only within one metadata group** (`hole.json.metadata_group.id`; listed in
   `manifest.metadata_groups`). Whitespace-only differences in metadata text are normalised for
   grouping; raw text stays in `sources[].metadata`.
3. **Missing is not zero.** Value codes `"NA"` (source: "Not detected or below threshold"), `"BLANK"`,
   `"INVALID"`; gaps = depth ranges with no row (`coverage.gaps`). Never fill or interpolate.
4. **Depth is along-hole metres.** Not vertical depth, not elevation; no survey/trajectory is used.
5. **Two interval conventions, two layers.** Query/display of 1 m records: `[from, to)`
   (`conventions.display_interval_convention`). Scan membership in the summary reproduction:
   `(from, to]` (`conventions.scan_bin_membership`). Do not switch the query engine to right-closed.
6. **Map coordinates**: `location.lon/lat`, GDA2020 geographic, untransformed;
   `location.licence_flag = "interim_display_unresolved"`; show `location.verification.identity_status`.
7. **Zoom/pan never changes results.**

## hole.json (main keys)

| key | meaning |
|---|---|
| `schema_version` / `pipeline_version` | `hylogger-hole-package/0.2` / `hylogger-pipeline/0.2` |
| `sources[]` | filename, sha256, bytes, source_url, all metadata rows, logical_header_record |
| `import_review` | `status` accepted / quarantined, `queryable`, `reasons[]`, `unclassified_columns[]` |
| `metadata_group` | `id` + normalised fields (product, algorithms, thresholds, definitions, interpretation levels) |
| `conventions` | `display_interval_convention`, `scan_bin_membership` |
| `location` | lon, lat, crs, source, licence_flag, `verification` (see catalogue) |
| `collar` | commodities, report, max_depth_m, tectonic_region, links, has_* flags, identity_status, survey_record_count_primary_collar (records exist; not verified or used) |
| `coverage` | from_m, to_m, n_records, `extent_span_m` (last to − first from, includes gaps), `covered_record_length_m` (sum of record lengths), `gap_length_m`, gaps[], drilled_max_depth_m, `covered_fraction_of_drilled_depth{value, numerator, denominator, note}` — not clamped (>1 means the sources disagree; also in `warnings`) |
| `metric_counts` | e.g. `{mineral_group_proportion: 36, quality_fraction: 2, feature_wavelength: 4, feature_depth: 6, albedo: 1}` |
| `metrics[]` | per source column: id (= column name = metric_id), kind, label, unit, region, interpretation_level, definition, comparable_across, n_numeric, n_source_na, n_blank, n_invalid, min, max, median |
| `occurrence_index` | mineral groups only: `length_ge_threshold_m` (length, not count), `longest_run_ge_threshold`, `max_value`, `max_at`; threshold 0.2 is a display default |
| `analyses` | optional, below |
| `import_issues[]`, `warnings[]` | show them |

`metric.kind`: `mineral_group_proportion` (relative proportion 0–1, **not mass %**);
`quality_fraction` (Invalid/INVALID: share of unclassified spectra — data quality, **not a mineral**);
`feature_wavelength` (nm, **not abundance**); `feature_depth` (absorption strength, **not down-hole depth**);
`albedo`; `unclassified` (kept, not queryable until registered).

## Interval search (reference: `hylogger_pipeline/intervals.py`)

Window `[from,to)`, whole records; conditions `{metric, op (>=,<=,>,<), value}`; touching passing records
join; NA/blank/invalid/gap/fail break runs. `na_passes` is **not exposed in v1**.
Edge flags: `starts_at_coverage_start`, `ends_at_coverage_end`, `starts_after_gap`, `ends_before_gap`,
`truncated_by_window_start`, `truncated_by_window_end` (the run would continue in the data).
Reference results — CMDD001+CMDD002, [0,150), 2200W_AlOH ≥ 2200: min 1 m 17 runs/59 m; min 3 m
CMDD001 [0,27), [30,35), CMDD002 [53,64) = 43 m; min 12 m 1 run/27 m.
TBDD126/127/128, [96,175), min 3 m: 5 runs/44 m, 2/16 m, 4/30 m.

## scan_stats.json (CMDD001/002 only)

Per metric (2200W_AlOH, 2250W_FeOH): `bins_1m[]` with `official`, `n_scans_in_bin` (all scans in (from,to]),
`n_scans_used` (those passing the feature-depth filter — **the denominator for any "% of scans ≥ threshold"**),
mean, std, p10/p50/p90 (**distribution range, not a confidence interval**), and per-scan arrays
`scan_index` (0-based TSG `sample`), `scan_depth_m`, `scan_value` (full precision). `source_files` gives
TSG/BIP SHA-256. `multiscale["0.5"|"2.0"]`: buckets from coverage start; last shorter bucket kept with
`partial: true`; buckets touching a source gap get `status: "spans_source_gap"` and no mean.

## lithology.json (CMDD001/002 only; optional experiment)

`display_name`: "Binary comparison experiment against company logs (felsic vs mafic)".
`exported_model` (random_forest_swir) + `exported_model_scores` for that same model; `metre_agreement{agree, compared}`;
`bins_1m[]` {from_m, to_m, n_scans, p_mafic_mean, model_label, logged_label, logged_label_share, agree};
`provenance` (run_id, seed, rf_config, software versions, SQLite/TSG/BIP SHA-256, label collar IDs); `caveats[]`.
Not a validated lithology classifier; the UI must run without it.

## Catalogue entry verification (`location.verification`)

`identity_status`: `name_and_report_match` | `needs_review` | `index_coordinates_only` | `unlocated`;
`name_check`: exact | case_or_punctuation_differs | differs | no_collar;
`report_check`: match_primary_report | match_other_index_report_field | differs | missing | no_collar;
plus index_id, index_data_name, primary/alternate collar ids, index report fields, collar HoleId /
CompanyHoleId / Anumber, join, coordinate_fields, db_sha256. Automatic checks only:
`needs_review` is not an error claim; a match is not a field survey. `co_located_with` (≤ 5 m) is a review
flag, not a duplicate count.

## boundaries.json (optional)

Produced by `scripts/run_boundary_experiment.py` (method `hylogger-boundaries/0.1`, needs numpy and scipy).
Nothing else depends on it.

| key | meaning |
|---|---|
| `display_name` | "Candidate spectral changes vs company-log code changes" |
| `role` | `development` (CMDD001/002, used to choose parameters) or `test` (parameters locked before comparison) |
| `method` | segmentation (exact optimal partitioning, L2 cost), `feature_set` (composition36), `preprocessing` (columns, N.A. encoding rule), `params` (beta, min_size_m, sigma2, penalty), `selected_on` |
| `usable_blocks[]` | {from_m, to_m, n_records}; nothing is detected or scored outside these |
| `candidates[]` | {depth_m, segment_above, segment_below, top_changes[3] {metric, mean_above, mean_below, change}, parameter_stability (0-1; share of 4 nearby settings keeping it within 1 m — NOT a probability), nearest_log_code_change_m} |
| `reference` | collar_id, rule, boundaries[] {depth_m, code_above, code_below, unit_above/below_thickness_m, thin_adjacent_unit_lt_1m}, issues, logged_coded_ranges |
| `scores` | per tolerance "0.5" / "1.0" / "2.0": n_candidates, n_reference, n_matched, precision, recall, f1, mean_abs_offset_m, pairs[] |
| `baselines` | random_same_count {n_draws, seed, f1_mean, f1_p95, p_value_f1_ge_model}, equal_spacing_same_count, window_difference_2200W_same_count |
| `comparison_feature_sets` | scalars6 / aloh2200w params and 1 m scores |
| `terms`, `provenance` (run_id, seed, SQLite + CSV SHA-256, collar ids, software), `caveats[]` |

Wording: "candidate spectral change" and "company-log code change (reference)". Never "boundary confirmed",
"contact" or "stratigraphy". Depth = along-hole metres. Reference log for CMDD001/002 = alternate report 103450.
