"""Application engine checks: synthetic edge cases and independent source oracle.

Run with: python -m unittest discover -s tests -v
Set HYLOGGER_DATA_ROOT to the external project data directory for the real-data
checks. No raw HyLogger data is included in these test fixtures or this module.

Author: Ding Qing
Date: 2026-10-15
"""

from __future__ import annotations

import copy
import csv
from decimal import Decimal
import io
import itertools
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from engine import (
    catalog_from_records,
    load_catalog,
    make_export,
    normalize_records,
    restore_query,
    run_query,
)


METRIC = "aloh_2200w_summary"
HOLES = ("CMDD001", "CMDD002")
TEST_ROOT = Path(__file__).resolve().parent


def row(depth, token="2200", *, hole="CMDD001", series="fixture-a", **changes):
    record = {
        "hole_id": hole,
        "series_id": series,
        "metric_id": METRIC,
        "from_m": depth,
        "to_m": depth + 1,
        "raw_token": str(token),
        "source_id": "fixture-source",
        "data_record_index": int(depth) + 1,
        "record_id": f"{hole}:{series}:{depth}",
    }
    record.update(changes)
    return record


def spec(**changes):
    query = {
        "metric_id": METRIC,
        "hole_ids": ["CMDD001"],
        "depth_from_m": 0,
        "depth_to_m": 20,
        "operator": "gte",
        "threshold": 2200,
        "min_run_m": 1,
    }
    query.update(changes)
    return query


def bounds(result):
    return sorted(
        (r["hole_id"], r["series_id"], r["from_m"], r["to_m"])
        for r in result["runs"]
    )


def write_summary(root, hole, values=("2200", "2201"), **metadata_changes):
    """A tiny artificial file with the actual public source's metadata layout."""
    path = Path(root) / "nvcl_wa" / hole / "supporting" / f"SM_{hole}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "Dataset": hole,
        "Date_generated": "16-02-2024",
        "SWIR_algorithm": "TSA+",
        "TIR_algorithm": "jCLST",
        "Bin_min_threshold": "0.05",
        "Scalar_min_depth": "0.001",
        "****W": "Wavelength of dominant spectral feature centred around wavelength **** (nm), labelled by typical feature assignment",
        "N.A.": "Not detected or below threshold",
    }
    metadata.update(metadata_changes)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["GSWA TSG Summary Mineral Log", "", ""])
        writer.writerows(metadata.items())
        writer.writerow(["Depth_from_(m)", "Depth_to_(m)", "2200W_AlOH"])
        for depth, value in enumerate(values):
            writer.writerow([f"{depth}.0", f"{depth + 1}.0", value])
    return path


class SyntheticQueryTests(unittest.TestCase):
    def execute(self, records, **query_changes):
        return run_query(catalog_from_records(records), spec(**query_changes))

    def test_equality_is_inclusive_and_final_run_is_flushed(self):
        result = self.execute([row(0, "2199.9999"), row(1), row(2, "2200.01")], min_run_m=2)
        self.assertEqual(bounds(result), [("CMDD001", "fixture-a", 1, 3)])

    def test_na_gap_and_low_value_break_continuity(self):
        records = [row(0), row(1), row(2, "N.A."), row(3), row(4),
                   row(6), row(7), row(8, "2199"), row(9), row(10)]
        result = self.execute(records, min_run_m=2)
        self.assertEqual(
            bounds(result),
            [("CMDD001", "fixture-a", start, end) for start, end in [(0, 2), (3, 5), (6, 8), (9, 11)]],
        )

    def test_zero_is_numeric_and_can_match_zero_threshold(self):
        result = self.execute([row(0, "0"), row(1, "N.A."), row(2, "0.0")], threshold=0)
        self.assertEqual(len(result["runs"]), 2)
        numeric = [record for record in result["records"] if record["status"] == "valid_numeric"]
        self.assertEqual([record["value"] for record in numeric], [0, 0])

    def test_invalid_values_do_not_become_zero_or_bridge_runs(self):
        for token in ("NaN", "Infinity", "-Infinity", "oops", ""):
            with self.subTest(token=token):
                result = self.execute([row(0), row(1, token), row(2)], min_run_m=2)
                self.assertEqual(result["runs"], [])
                middle = next(r for r in result["records"] if r["from_m"] == 1)
                self.assertNotEqual(middle["status"], "valid_numeric")
                self.assertIsNone(middle["value"])

    def test_numeric_value_and_status_are_rederived_from_raw_token(self):
        result = self.execute([row(0, "N.A.", value=9999, status="valid_numeric")])
        self.assertEqual(result["runs"], [])
        self.assertEqual(result["records"][0]["status"], "source_na")

    def test_minimum_length_applies_to_whole_run(self):
        result = self.execute([row(0), row(1), row(3), row(4), row(5)], min_run_m=3)
        self.assertEqual(bounds(result), [("CMDD001", "fixture-a", 3, 6)])

    def test_query_window_is_half_open_and_does_not_read_outside(self):
        result = self.execute([row(i) for i in range(5)], depth_from_m=1, depth_to_m=4, min_run_m=3)
        self.assertEqual(bounds(result), [("CMDD001", "fixture-a", 1, 4)])
        # records may include full-depth context for the plot; query evidence
        # and coverage must still contain only complete bins in this window.
        self.assertEqual([r["from_m"] for r in result["evidence"]], [1, 2, 3])
        self.assertEqual(result["holes"][0]["row_coverage_m"], 3)

    def test_adjacent_records_from_different_series_do_not_join(self):
        records = [row(0), row(1), row(2, series="fixture-b"), row(3, series="fixture-b")]
        self.assertEqual(self.execute(records, min_run_m=3)["runs"], [])
        result = self.execute(records, min_run_m=2)
        self.assertEqual(len(result["runs"]), 2)
        self.assertEqual({r["series_id"] for r in result["runs"]}, {"fixture-a", "fixture-b"})

    def test_different_holes_do_not_join(self):
        records = [row(0), row(1, hole="CMDD002")]
        result = self.execute(records, hole_ids=list(HOLES), min_run_m=2)
        self.assertEqual(result["runs"], [])

    def test_record_order_cannot_change_results(self):
        records = [row(0), row(1), row(2, "2199"), row(3)]
        self.assertEqual(bounds(self.execute(records)), bounds(self.execute(list(reversed(records)))))

    def test_source_na_keeps_row_coverage_but_not_numeric_coverage(self):
        result = self.execute([row(0), row(1, "N.A."), row(3, "oops")], depth_to_m=5)
        hole = result["holes"][0]
        self.assertEqual(hole["row_coverage_m"], 3)
        self.assertEqual(hole["numeric_coverage_m"], 1)
        self.assertAlmostEqual(hole["numeric_coverage_fraction"], 0.2)
        self.assertEqual(hole["source_na_m"], 1)

    def test_evidence_is_only_qualifying_records_and_retains_source_reference(self):
        result = self.execute([row(0), row(1), row(2, "2199"), row(3)], min_run_m=2)
        self.assertEqual({r["record_id"] for r in result["evidence"]}, {"CMDD001:fixture-a:0", "CMDD001:fixture-a:1"})
        for record in result["evidence"]:
            self.assertEqual(record["source_id"], "fixture-source")
            self.assertIn(record["data_record_index"], (1, 2))
            self.assertEqual(record["raw_token"], "2200")


class ImportValidationTests(unittest.TestCase):
    def test_duplicate_record_id_rejects_affected_series(self):
        records = [row(0), row(1, record_id="CMDD001:fixture-a:0"), row(2, series="good")]
        audit = normalize_records(records)
        self.assertTrue(audit["issues"])
        self.assertTrue(audit["rejected_series"])
        self.assertEqual([r["series_id"] for r in audit["records"]], ["good"])

    def test_duplicate_interval_rejects_affected_series(self):
        audit = normalize_records([row(0), row(0, record_id="different-id"), row(3, series="good")])
        self.assertTrue(audit["rejected_series"])
        self.assertEqual([r["series_id"] for r in audit["records"]], ["good"])

    def test_invalid_depth_intervals_are_excluded_and_audited(self):
        invalid = [row(-1), row(0.5), row(3, to_m=5), row(7, to_m=7), row(9, to_m=float("inf"))]
        audit = normalize_records(invalid + [row(12)])
        self.assertEqual([r["from_m"] for r in audit["records"]], [12])
        self.assertGreaterEqual(len(audit["issues"]), len(invalid))

    def test_integer_depth_tolerance_is_inclusive_and_bounded(self):
        for start, end in ((1.999999, 2.999999), (2.000001, 3.000001)):
            with self.subTest(start=start, end=end):
                audit = normalize_records([row(start, to_m=end)])
                self.assertEqual(audit["accepted_records"], 1)
                self.assertEqual((audit["records"][0]["from_m"], audit["records"][0]["to_m"]), (2, 3))
        for start, end in ((1.9999989, 2.9999989), (2.0000011, 3.0000011), (True, 2)):
            with self.subTest(start=start, end=end):
                audit = normalize_records([row(start, to_m=end)])
                self.assertEqual(audit["accepted_records"], 0)
                self.assertEqual(audit["rejected_records"], 1)
                self.assertTrue(audit["issues"])

    def test_source_loader_preserves_one_based_data_record_index_and_raw_token(self):
        with tempfile.TemporaryDirectory(prefix="engine-fixture-", dir=TEST_ROOT) as directory:
            for hole in HOLES:
                write_summary(directory, hole, values=("2200.0000", "N.A.", "0"))
            catalog = load_catalog(directory, hole_ids=HOLES, verify_sources=False)
        records = [r for r in catalog["records"] if r["hole_id"] == "CMDD001"]
        self.assertEqual([r["data_record_index"] for r in records], [1, 2, 3])
        self.assertEqual([r["raw_token"] for r in records], ["2200.0000", "N.A.", "0"])
        self.assertEqual([r["status"] for r in records], ["valid_numeric", "source_na", "valid_numeric"])

    def test_unknown_metadata_rejects_source_instead_of_guessing_meaning(self):
        for field, value in (("Dataset", "WRONG_HOLE"), ("N.A.", "Unknown"), ("****W", "Unverified feature")):
            with self.subTest(field=field), tempfile.TemporaryDirectory(prefix="engine-fixture-", dir=TEST_ROOT) as directory:
                write_summary(directory, "CMDD001", **{field: value})
                write_summary(directory, "CMDD002")
                catalog = load_catalog(directory, hole_ids=HOLES, verify_sources=False)
                self.assertEqual({r["hole_id"] for r in catalog["records"]}, {"CMDD002"})
                self.assertTrue(catalog["audit"]["issues"])

    def test_incompatible_source_processing_and_definitions_are_not_mixed(self):
        cases = (
            ("SWIR_algorithm", "different algorithm"),
            ("Bin_min_threshold", "0.10"),
            ("Scalar_min_depth", "0.002"),
            ("****W", "Wavelength of dominant spectral feature using a different declared assignment"),
        )
        for field, value in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory(prefix="engine-fixture-", dir=TEST_ROOT) as directory:
                write_summary(directory, "CMDD001")
                write_summary(directory, "CMDD002", **{field: value})
                catalog = load_catalog(directory, hole_ids=HOLES, verify_sources=False)
                self.assertEqual({r["hole_id"] for r in catalog["records"]}, {"CMDD001"})
                self.assertTrue(any(issue.get("hole_id") == "CMDD002" and issue.get("reason") == "incompatible_source_settings" for issue in catalog["audit"]["issues"]))

    def test_unverified_or_missing_coordinates_do_not_create_a_located_hole(self):
        # Deliberately synthetic coordinate fixture; these are not real collars.
        coordinates = {"CMDD001": {"longitude": 121.0, "latitude": -29.0,
                                   "crs": "GDA2020", "verified": False}}
        catalog = catalog_from_records([row(0), row(0, hole="CMDD002")], coordinate_catalog=coordinates)
        by_hole = {item["hole_id"]: item for item in catalog["holes"]}
        self.assertFalse(by_hole["CMDD001"]["located"])
        self.assertFalse(by_hole["CMDD002"]["located"])
        self.assertIsNone(by_hole["CMDD002"]["longitude"])
        self.assertIsNone(by_hole["CMDD002"]["latitude"])

    def test_missing_all_sources_is_explicit_error(self):
        with tempfile.TemporaryDirectory(prefix="engine-fixture-", dir=TEST_ROOT) as directory:
            with self.assertRaises(ValueError):
                load_catalog(directory, hole_ids=HOLES, verify_sources=False)


class QueryValidationAndExportTests(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog_from_records([row(0), row(1), row(2, hole="CMDD002")])

    def test_invalid_query_inputs_are_rejected(self):
        cases = [
            {"depth_from_m": -1}, {"depth_from_m": 0.5}, {"depth_to_m": 1.5},
            {"depth_from_m": 20}, {"depth_to_m": 0}, {"depth_to_m": float("inf")},
            {"threshold": float("nan")}, {"threshold": float("inf")},
            {"min_run_m": 0}, {"min_run_m": -1}, {"min_run_m": 1.5},
            {"hole_ids": []}, {"hole_ids": ["UNKNOWN"]}, {"metric_id": "unknown"},
            {"operator": "gt"},
        ]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                run_query(self.catalog, spec(**changes))

    def test_hole_order_is_canonical_for_query_identity(self):
        one = run_query(self.catalog, spec(hole_ids=list(HOLES)))
        two = run_query(self.catalog, spec(hole_ids=list(reversed(HOLES))))
        self.assertEqual(one["query_id"], two["query_id"])
        self.assertEqual(one["query"], two["query"])

    def test_changed_threshold_changes_query_identity(self):
        original = run_query(self.catalog, spec())
        changed = run_query(self.catalog, spec(threshold=2201))
        self.assertNotEqual(original["query_id"], changed["query_id"])

    def test_export_contains_reproducible_query_and_header_only_empty_results(self):
        result = run_query(self.catalog, spec(threshold=10000))
        bundle = make_export(self.catalog, result)
        self.assertEqual(bundle, make_export(self.catalog, result))
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            self.assertEqual(archive.testzip(), None)
            self.assertTrue({"query.json", "intervals.csv", "holes.csv", "evidence.csv", "manifest.json", "README.txt"}.issubset(archive.namelist()))
            for name in ("intervals.csv", "evidence.csv"):
                reader = csv.DictReader(io.StringIO(archive.read(name).decode("utf-8-sig")))
                self.assertTrue(reader.fieldnames, name)
                self.assertIn("query_id", reader.fieldnames)
                self.assertEqual(list(reader), [])
            envelope = json.loads(archive.read("query.json"))
        restored = restore_query(self.catalog, envelope)
        self.assertEqual(restored["query_id"], result["query_id"])
        self.assertTrue(restored["reproduced"])

    def test_exported_evidence_and_intervals_share_applied_query_identity(self):
        result = run_query(self.catalog, spec())
        with zipfile.ZipFile(io.BytesIO(make_export(self.catalog, result))) as archive:
            for name in ("intervals.csv", "holes.csv", "evidence.csv"):
                records = list(csv.DictReader(io.StringIO(archive.read(name).decode("utf-8-sig"))))
                self.assertTrue(records, name)
                self.assertEqual({r["query_id"] for r in records}, {result["query_id"]})

    def test_restore_refuses_changed_versions_query_id_and_query(self):
        result = run_query(self.catalog, spec())
        envelope = {"schema_version": "1.0", **{k: result[k] for k in ("query_id", "query", "versions")}}
        variants = []
        for key in result["versions"]:
            item = copy.deepcopy(envelope)
            item["versions"][key] = "changed"
            variants.append(item)
        changed_id = copy.deepcopy(envelope)
        changed_id["query_id"] = "changed"
        variants.append(changed_id)
        changed_query = copy.deepcopy(envelope)
        changed_query["query"]["threshold"] = 2201
        variants.append(changed_query)
        for item in variants:
            with self.subTest(item=item), self.assertRaises(ValueError):
                restore_query(self.catalog, item)

    def test_restore_refuses_different_input_values(self):
        result = run_query(self.catalog, spec())
        envelope = {"schema_version": "1.0", **{k: result[k] for k in ("query_id", "query", "versions")}}
        changed_catalog = catalog_from_records([row(0, "2201"), row(1), row(2, hole="CMDD002")])
        with self.assertRaises(ValueError):
            restore_query(changed_catalog, envelope)


def independent_source_rows(path):
    """Read source independently: no production importer, normalizer, or IDs."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    header_index = next(i for i, values in enumerate(rows) if values and values[0] == "Depth_from_(m)")
    header = rows[header_index]
    indices = [header.index(key) for key in ("Depth_from_(m)", "Depth_to_(m)", "2200W_AlOH")]
    return [tuple(Decimal(values[index]) for index in indices) for values in rows[header_index + 1:] if values and any(values)]


def independent_runs(rows, lower, upper, threshold, minimum):
    """Group qualifying integer depths by their depth-index difference.

    This differs from the production streaming run/flush algorithm and keeps
    source decimals exact through threshold comparison.
    """
    starts = sorted(int(a) for a, b, value in rows if a >= lower and b <= upper and value >= threshold)
    answer = []
    for _, group in itertools.groupby(enumerate(starts), key=lambda pair: pair[1] - pair[0]):
        depths = [depth for _, depth in group]
        if len(depths) >= minimum:
            answer.append((depths[0], depths[-1] + 1))
    return answer


@unittest.skipUnless(os.environ.get("HYLOGGER_DATA_ROOT"), "Set HYLOGGER_DATA_ROOT for real external CSV validation")
class RealSourceOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data_root = Path(os.environ["HYLOGGER_DATA_ROOT"])
        cls.catalog = load_catalog(cls.data_root)
        cls.source = {hole: independent_source_rows(cls.data_root / "nvcl_wa" / hole / "supporting" / f"SM_{hole}.csv") for hole in HOLES}

    def test_baseline_known_interval_counts_lengths_and_boundaries(self):
        for minimum, count, length in ((1, 17, 59), (3, 3, 43), (12, 1, 27)):
            with self.subTest(minimum=minimum):
                result = run_query(self.catalog, spec(hole_ids=list(HOLES), depth_to_m=150, min_run_m=minimum))
                self.assertEqual(len(result["runs"]), count)
                self.assertEqual(sum(r["to_m"] - r["from_m"] for r in result["runs"]), length)
                if minimum == 3:
                    self.assertEqual(sorted((r["hole_id"], r["from_m"], r["to_m"]) for r in result["runs"]), [("CMDD001", 0, 27), ("CMDD001", 30, 35), ("CMDD002", 53, 64)])

    def test_real_queries_match_independent_decimal_csv_oracle(self):
        for lower, upper in ((0, 150), (0, 45), (50, 150)):
            for threshold in ("2200", "2200.5"):
                for minimum in (1, 3, 12):
                    with self.subTest(window=(lower, upper), threshold=threshold, minimum=minimum):
                        result = run_query(self.catalog, spec(hole_ids=list(HOLES), depth_from_m=lower, depth_to_m=upper, threshold=float(threshold), min_run_m=minimum))
                        expected = sorted((hole, a, b) for hole, rows in self.source.items() for a, b in independent_runs(rows, Decimal(lower), Decimal(upper), Decimal(threshold), minimum))
                        actual = sorted((r["hole_id"], r["from_m"], r["to_m"]) for r in result["runs"])
                        self.assertEqual(actual, expected)

    def test_real_coverage_is_per_hole_not_inferred_from_requested_window(self):
        result = run_query(self.catalog, spec(hole_ids=list(HOLES), depth_to_m=150))
        by_hole = {h["hole_id"]: h for h in result["holes"]}
        for hole, count in (("CMDD001", 45), ("CMDD002", 100)):
            self.assertEqual(by_hole[hole]["row_coverage_m"], count)
            self.assertEqual(by_hole[hole]["numeric_coverage_m"], count)
            self.assertAlmostEqual(by_hole[hole]["numeric_coverage_fraction"], count / 150)

    def test_real_export_evidence_round_trips_to_exact_source_record(self):
        result = run_query(self.catalog, spec(hole_ids=list(HOLES), depth_to_m=150, min_run_m=3))
        self.assertEqual(len(result["evidence"]), 43)
        for record in result["evidence"]:
            source = self.source[record["hole_id"]][record["data_record_index"] - 1]
            self.assertEqual((Decimal(str(record["from_m"])), Decimal(str(record["to_m"])), Decimal(record["raw_token"])), source)
        with zipfile.ZipFile(io.BytesIO(make_export(self.catalog, result))) as archive:
            envelope = json.loads(archive.read("query.json"))
        restored = restore_query(self.catalog, envelope)
        self.assertEqual(bounds(restored), bounds(result))
        self.assertEqual(restored["query_id"], result["query_id"])


if __name__ == "__main__":
    unittest.main()
