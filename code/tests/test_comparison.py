"""Context availability and reproducible comparisons preserve missing source states.

Author: Ding Qing
Date: 2026-10-15
"""

import csv
import io
import json
import threading
import unittest
import urllib.error
import urllib.request
import zipfile

import app
import comparison
import engine


WAVELENGTH = "2200W_AlOH"
KAOLIN = "Kaolin_(System_SWIR)"
MICA = "White-Mica_(System_SWIR)"


def record(hole, depth, wavelength="2201", kaolin="N.A.", mica="N.A."):
    return {"hole_id": hole, "series_id": hole + "-summary", "record_id": f"{hole}:{depth}",
            "metric_id": WAVELENGTH, "from_m": depth, "to_m": depth + 1,
            "raw_token": wavelength, "source_sha256": hole + "-fixture-sha",
            "source_filename": f"SM_{hole}.csv", "data_record_index": depth + 1,
            "field_aliases": {"kaolin-source": KAOLIN},
            "raw_row": {WAVELENGTH: wavelength, "kaolin-source": kaolin, MICA: mica}}


def fixture():
    return engine.catalog_from_records([
        record("A", 0, kaolin="0"), record("A", 1, wavelength="N.A.", kaolin="0.4"),
        record("A", 2, kaolin="N.A."), record("A", 3, kaolin="NaN"),
        record("A", 4, kaolin="-1"), record("B", 0, wavelength="N.A.", kaolin="N.A."),
        record("B", 1, kaolin="NULL"), record("B", 2, kaolin="0.8"),
    ])


def scope(**changes):
    value = {"hole_ids": ["A", "B"], "depth_from_m": 0, "depth_to_m": 2}
    value.update(changes)
    return value


def query(**changes):
    value = dict(scope(), metric_id=WAVELENGTH, operator="gte", threshold=2200, min_run_m=1)
    value.update(changes)
    return value


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.catalog = fixture()

    def available(self, **changes):
        return {item["metric_id"]: item for item in comparison.availability(self.catalog, scope(**changes))["metrics"]}

    def test_zero_counts_and_partial_holes_remain_selectable(self):
        kaolin = self.available()[KAOLIN]
        self.assertTrue(kaolin["enabled"])
        self.assertEqual((kaolin["numeric_count"], kaolin["holes_with_values"], kaolin["hole_count"]), (2, 1, 2))
        self.assertFalse(self.available()[MICA]["enabled"])
        self.assertEqual(self.available()[MICA]["numeric_count"], 0)

    def test_selected_window_and_holes_control_availability(self):
        self.assertFalse(self.available(hole_ids=["B"])[KAOLIN]["enabled"])
        self.assertTrue(self.available(hole_ids=["B"], depth_from_m=2, depth_to_m=3)[KAOLIN]["enabled"])
        self.assertFalse(self.available(hole_ids=["A"], depth_from_m=3, depth_to_m=5)[KAOLIN]["enabled"])
        self.assertFalse(self.available(depth_from_m=20, depth_to_m=21)[WAVELENGTH]["enabled"])

    def test_empty_selection_disables_every_scalar(self):
        values = self.available(hole_ids=[])
        self.assertTrue(all(not item["enabled"] and item["hole_count"] == 0 for item in values.values()))

    def test_invalid_scope_is_rejected(self):
        for changes in ({"hole_ids": ["unknown"]}, {"depth_from_m": 0.5}, {"depth_to_m": 0}, {"extra": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                comparison.availability(self.catalog, scope(**changes))

    def test_optional_minimum_keeps_single_records_and_can_restore(self):
        result = engine.run_query(self.catalog, query(hole_ids=["A"], depth_to_m=3, min_run_m=None))
        self.assertEqual([(run["from_m"], run["to_m"]) for run in result["runs"]], [(0, 1), (2, 3)])
        self.assertIsNone(result["query"]["min_run_m"])
        self.assertIn("no minimum length", result["evidence"][0]["match_reason"])
        restored = engine.restore_query(self.catalog, engine.query_envelope(result))
        self.assertEqual(restored["query_id"], result["query_id"])
        self.assertEqual(restored["runs"], result["runs"])

    def test_profiles_do_not_inherit_filter_and_keep_raw_missing_states(self):
        result = engine.run_query(self.catalog, query(threshold=2300, display_metric_ids=[KAOLIN, WAVELENGTH, MICA]))
        self.assertEqual(result["runs"], [])
        self.assertEqual([p["metric"]["metric_id"] for p in result["profiles"]], [KAOLIN, WAVELENGTH, MICA])
        kaolin = result["profiles"][0]["records"]
        self.assertEqual(len(kaolin), 4)
        self.assertEqual([(r["value"], r["status"]) for r in kaolin], [(0.0, "valid_numeric"), (0.4, "valid_numeric"), (None, "source_na"), (None, "unknown_missing")])
        self.assertTrue(all(row["value"] is None for row in result["profiles"][2]["records"]))
        for row in kaolin:
            self.assertEqual(row["source_field"], "kaolin-source")
            self.assertTrue(row["source_sha256"])

    def test_browse_has_no_matches_and_exports_all_displayed_values(self):
        result = engine.run_query(self.catalog, query(operator="none", threshold=None, min_run_m=None,
                                                       display_metric_ids=[KAOLIN, WAVELENGTH]))
        self.assertEqual((result["runs"], result["evidence"], result["total_length_m"]), ([], [], 0))
        self.assertTrue(all(hole["status"].startswith("Viewing") for hole in result["holes"]))
        restored = engine.restore_query(self.catalog, engine.query_envelope(result))
        self.assertEqual(restored["query_id"], result["query_id"])
        with zipfile.ZipFile(io.BytesIO(engine.make_export(self.catalog, result))) as archive:
            profiles = list(csv.DictReader(io.StringIO(archive.read("profiles.csv").decode("utf-8-sig"))))
            readme = archive.read("README.txt").decode()
            envelope = json.loads(archive.read("query.json"))
        self.assertEqual(len(profiles), 8)
        self.assertEqual({row["unit"] for row in profiles}, {"nm", "relative proportion"})
        self.assertIn("Browse mode: no threshold", readme)
        self.assertEqual(envelope["query"]["display_metric_ids"], [KAOLIN, WAVELENGTH])

    def test_legacy_query_identity_is_unchanged_by_profiles_response(self):
        spec = query()
        result = engine.run_query(self.catalog, spec)
        self.assertEqual(result["query"], spec)
        expected = engine._hash({"query": spec, "versions": self.catalog["versions"]})
        self.assertEqual(result["query_id"], expected)
        self.assertEqual(len(result["profiles"]), 1)

    def test_invalid_display_or_browse_settings_are_rejected(self):
        for changes in ({"display_metric_ids": []}, {"display_metric_ids": [KAOLIN, KAOLIN]},
                        {"display_metric_ids": ["not-a-field"]}, {"display_metric_ids": [WAVELENGTH] * 7},
                        {"operator": "none"}, {"operator": "none", "threshold": None},
                        {"min_run_m": 0}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                engine.run_query(self.catalog, query(**changes))

    def test_http_profiles_omit_source_row_without_mutating_catalog(self):
        result = engine.run_query(self.catalog, query(display_metric_ids=[WAVELENGTH, KAOLIN]))
        payload = app.query_payload(result)
        self.assertTrue(all("raw_row" not in row for profile in payload["profiles"] for row in profile["records"]))
        self.assertIn("raw_row", self.catalog["records"][0])


class ComparisonHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.create_server(fixture(), port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(3)

    def test_availability_route_and_validation(self):
        url = f"http://127.0.0.1:{self.server.server_port}/api/availability"
        request = urllib.request.Request(url, data=json.dumps(scope()).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertTrue(json.load(response)["metrics"])
        invalid = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(invalid, timeout=5)
        self.assertEqual(raised.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
