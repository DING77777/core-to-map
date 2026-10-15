"""Full-hole extents describe numeric records without filling missing depths.

Author: Ding Qing
Date: 2026-10-15
"""

import copy
import unittest

import depth_ranges
from metrics import LEGACY_METRIC_ID, METRIC_ID


KAOLIN = "Kaolin_(System_SWIR)"


def row(depth, token="2201", *, raw=None, aliases=None, metric=METRIC_ID):
    return {"hole_id": "A", "from_m": depth, "to_m": depth + 1,
            "metric_id": metric, "raw_token": token,
            "raw_row": raw or {}, "field_aliases": aliases or {}}


def catalog(rows):
    return {"holes": [{"hole_id": "A"}, {"hole_id": "B"}], "records": rows,
            "metric_registry": {METRIC_ID: {"minimum_valid_value": 0},
                                KAOLIN: {"minimum_valid_value": 0}},
            "default_query": {"depth_from_m": 100, "depth_to_m": 101}}


class DepthRangeTests(unittest.TestCase):
    def test_zero_counts_and_gaps_do_not_inflate_record_count(self):
        source = catalog([row(10, "0"), row(12, "N.A."), row(20, "2201")])
        result = depth_ranges.summarize(source)["A"][METRIC_ID]
        self.assertEqual(result, {"from_m": 10, "to_m": 21, "numeric_count": 2})

    def test_missing_nonfinite_negative_and_unparseable_tokens_are_excluded(self):
        tokens = ["N.A.", "NULL", "", "NaN", "inf", "-inf", "-1", "stone", None, True]
        source = catalog([row(i, token) for i, token in enumerate(tokens)])
        result = depth_ranges.summarize(source)["A"][METRIC_ID]
        self.assertEqual(result, {"from_m": None, "to_m": None, "numeric_count": 0})

    def test_registry_minimum_applies_to_each_field(self):
        source = catalog([row(i, raw={KAOLIN: value})
                          for i, value in enumerate(["0", "0.09", "0.1", "2"])])
        source["metric_registry"][KAOLIN]["minimum_valid_value"] = 0.1
        self.assertEqual(depth_ranges.summarize(source)["A"][KAOLIN],
                         {"from_m": 2, "to_m": 4, "numeric_count": 2})

    def test_field_aliases_and_legacy_metric_ids_are_canonicalized(self):
        source = catalog([row(7, "2201", metric=LEGACY_METRIC_ID,
                              raw={"source-kaolin": "0.5", "unknown": "123"},
                              aliases={"source-kaolin": KAOLIN})])
        result = depth_ranges.summarize(source)["A"]
        self.assertEqual(set(result), {METRIC_ID, KAOLIN})
        self.assertTrue(all(item == {"from_m": 7, "to_m": 8, "numeric_count": 1}
                            for item in result.values()))

    def test_primary_raw_token_overrides_duplicate_raw_row_value(self):
        source = catalog([row(3, "N.A.", raw={METRIC_ID: "2201"}),
                          row(4, "2202", raw={METRIC_ID: "N.A."})])
        self.assertEqual(depth_ranges.summarize(source)["A"][METRIC_ID],
                         {"from_m": 4, "to_m": 5, "numeric_count": 1})

    def test_all_holes_and_registry_metrics_remain_present_without_values(self):
        result = depth_ranges.summarize(catalog([]))
        self.assertEqual(set(result), {"A", "B"})
        for ranges in result.values():
            self.assertEqual(set(ranges), {METRIC_ID, KAOLIN})
            self.assertTrue(all(item == {"from_m": None, "to_m": None, "numeric_count": 0}
                                for item in ranges.values()))

    def test_full_hole_range_ignores_query_window_and_does_not_mutate_catalog(self):
        source = catalog([row(200), row(2)])
        before = copy.deepcopy(source)
        result = depth_ranges.summarize(source)
        self.assertEqual(result["A"][METRIC_ID],
                         {"from_m": 2, "to_m": 201, "numeric_count": 2})
        result["A"][KAOLIN]["numeric_count"] = 999
        self.assertEqual(source, before)
        self.assertEqual(result["B"][KAOLIN]["numeric_count"], 0)


if __name__ == "__main__":
    unittest.main()
