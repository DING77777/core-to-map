"""Keep source support, source N.A. and query-window clipping distinct.

Author: Ding Qing
Date: 2026-10-15
"""

import csv
import io
import json
import os
from pathlib import Path
import unittest
import zipfile

import engine
import library


def row(depth, token="2201"):
    return {"hole_id": "TEST", "series_id": "one", "record_id": f"r{depth}",
            "from_m": depth, "to_m": depth + 1, "raw_token": token,
            "metric_id": "2200W_AlOH"}


def query(holes=("TEST",), start=0, end=10, metric="2200W_AlOH", threshold=2200, minimum=1):
    return {"hole_ids": list(holes), "metric_id": metric, "depth_from_m": start,
            "depth_to_m": end, "threshold": threshold, "min_run_m": minimum, "operator": "gte"}


class QuerySemanticsTests(unittest.TestCase):
    def test_boundary_reasons_use_adjacent_source_records(self):
        catalog = engine.catalog_from_records([
            row(0), row(1), row(2, "N.A."), row(3), row(5), row(6, "NULL"), row(7), row(8, "2190")])
        result = engine.run_query(catalog, query(start=1, end=9))
        reasons = {(r["from_m"], r["to_m"]): (r["start_reason"], r["end_reason"]) for r in result["runs"]}
        self.assertEqual(reasons[(1, 2)], ("window_continues", "source_na"))
        self.assertEqual(reasons[(3, 4)], ("source_na", "missing"))
        self.assertEqual(reasons[(5, 6)], ("missing", "unknown_missing"))
        self.assertEqual(reasons[(7, 8)], ("unknown_missing", "nonmatch"))

    def test_window_end_continuation_and_actual_source_edges(self):
        catalog = engine.catalog_from_records([row(n) for n in range(4)])
        clipped = engine.run_query(catalog, query(start=1, end=3))["runs"][0]
        full = engine.run_query(catalog, query(end=4))["runs"][0]
        self.assertEqual((clipped["start_reason"], clipped["end_reason"]), ("window_continues", "window_continues"))
        self.assertEqual((full["start_reason"], full["end_reason"]), ("source_start", "source_end"))

    def test_coverage_partitions_without_inventing_drilled_depth(self):
        catalog = engine.catalog_from_records([row(2), row(3, "N.A."), row(4, "NULL"), row(6, "-1")])
        hole = engine.run_query(catalog, query())["holes"][0]
        self.assertEqual(hole["summary_span_window_m"], 5)
        self.assertEqual([hole[k] for k in ("numeric_coverage_m", "source_na_m", "unknown_missing_m", "invalid_value_m", "source_gap_m")], [1, 1, 1, 1, 1])
        self.assertEqual(hole["outside_summary_span_m"], 5)
        self.assertEqual(hole["unknown_extent_m"], 5)
        self.assertFalse(hole["drilled_depth_verified"])
        self.assertEqual(hole["numeric_coverage_denominator_m"], 10)
        self.assertEqual(hole["numeric_fraction_of_summary_span"], 0.2)
        self.assertEqual(hole["numeric_fraction_of_reported_rows"], 0.25)

    def test_verified_depth_partitions_and_conflict_do_not_clip_records(self):
        coords = {"TEST": {"longitude": 120, "latitude": -30, "crs": "EPSG:7844", "verified": True, "max_depth_m": 5.5}}
        catalog = engine.catalog_from_records([row(2), row(3)], coordinate_catalog=coords)
        hole = engine.run_query(catalog, query())["holes"][0]
        self.assertEqual(hole["within_drill_without_summary_m"], 3.5)
        self.assertEqual(hole["outside_drill_m"], 4.5)
        self.assertEqual(hole["unknown_extent_m"], 0)
        conflict = engine.catalog_from_records([row(5), row(6)], coordinate_catalog=coords)
        result = engine.run_query(conflict, query())
        self.assertEqual(result["total_length_m"], 2)
        self.assertEqual(result["holes"][0]["summary_depth_conflict"]["excess_m"], 1.5)

    def test_export_carries_reasons_and_denominators(self):
        catalog = engine.catalog_from_records([row(0), row(1), row(2)])
        result = engine.run_query(catalog, query(start=1, end=2))
        with zipfile.ZipFile(io.BytesIO(engine.make_export(catalog, result))) as archive:
            intervals = list(csv.DictReader(io.StringIO(archive.read("intervals.csv").decode("utf-8-sig"))))
            holes = list(csv.DictReader(io.StringIO(archive.read("holes.csv").decode("utf-8-sig"))))
        self.assertEqual(intervals[0]["start_reason"], "window_continues")
        self.assertEqual(holes[0]["numeric_coverage_denominator"], "requested_depth_window")


@unittest.skipUnless(os.environ.get("HYLOGGER_DATA_ROOT"), "Set HYLOGGER_DATA_ROOT for official source regressions")
class OfficialQuerySemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = library.load_library(Path(os.environ["HYLOGGER_DATA_ROOT"]))

    def test_default_result_and_tbdd126_clipped_start(self):
        result = engine.run_query(self.catalog, self.catalog["default_query"])
        self.assertEqual((result["run_count"], result["total_length_m"]), (11, 90))
        run = next(r for r in result["runs"] if r["hole_id"] == "TBDD126" and r["from_m"] == 96)
        self.assertEqual((run["to_m"], run["start_reason"], run["end_reason"]), (105, "window_continues", "nonmatch"))

    def test_ehd_internal_gaps_and_outside_window_are_separate(self):
        hole = engine.run_query(self.catalog, query(("EHD001",), 0, 1312))["holes"][0]
        self.assertEqual((hole["summary_span_window_m"], hole["source_gap_m"], hole["numeric_coverage_m"]), (451, 3, 448))
        self.assertEqual((hole["outside_summary_span_m"], hole["outside_drill_m"]), (861, 861))

    def test_cmdd001_105_metres_without_summary_is_not_internal_gap(self):
        hole = engine.run_query(self.catalog, query(("CMDD001",), 0, 150))["holes"][0]
        self.assertEqual(hole["within_drill_without_summary_m"], 105)
        self.assertEqual(hole["source_gap_m"], 0)
        self.assertEqual(hole["outside_drill_m"], 0)

    def test_olivine_na_is_source_non_detection_not_zero_or_gap(self):
        result = engine.run_query(self.catalog, query(("TBDD127",), 96, 175, "Olivine_(System_TIR)", 0.2))
        hole = result["holes"][0]
        self.assertEqual((hole["source_na_m"], hole["numeric_coverage_m"], hole["source_gap_m"]), (79, 0, 0))
        self.assertEqual(hole["status"], "Not detected / below source threshold")
        self.assertTrue(all(r["value"] is None and r["raw_token"] == "N.A." for r in result["records"]))

    def test_tur_depth_conflict_remains_visible(self):
        if "TUR13DD003" not in {h["hole_id"] for h in self.catalog["holes"]}:
            self.skipTest("TUR13DD003 is not installed")
        result = engine.run_query(self.catalog, query(("TUR13DD003",), 283, 817))
        hole = result["holes"][0]
        self.assertEqual(hole["summary_depth_conflict"]["summary_to_m"], 817)
        self.assertAlmostEqual(hole["summary_depth_conflict"]["excess_m"], 185.4)
        self.assertEqual(max(r["to_m"] for r in result["records"]), 817)


if __name__ == "__main__":
    unittest.main()
