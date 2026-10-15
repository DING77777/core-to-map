"""Cached result identity, safe serving and background calculation lifecycle.

Author: Ding Qing
Date: 2026-10-15
"""

import copy
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

import app
import change_viewer as cv


class ChangeViewerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.source_path = self.data / "SM_H1.csv"
        self.source_path.write_bytes(b"original source")
        self.sha = cv.digest_file(self.source_path)
        self.analysis = self.root / "analysis"
        (self.analysis / "viewer" / "data").mkdir(parents=True)
        (self.analysis / "hylogger_pipeline").mkdir()
        for filename in ("build_viewer.py", "hylogger_pipeline/boundaries.py", "hylogger_pipeline/summary_csv.py"):
            (self.analysis / filename).write_text("# test method\n", encoding="utf-8")
        for filename in cv.ASSETS:
            (self.analysis / "viewer" / filename).write_text("test asset", encoding="utf-8")
        self.source = {"hole_id": "H1", "sha256": self.sha, "filename": "SM_H1.csv",
                       "relative_path": "SM_H1.csv", "fields": list(cv.COMPOSITION_COLUMNS)}
        self.catalog = {"holes": [{"hole_id": "H1"}], "manifest": {"sources": [self.source]},
                        "records": [{"hole_id": "H1", "from_m": d, "to_m": d + 1} for d in range(5)],
                        "versions": {"engine_version": "test"}}
        self.result = {"hole": "H1", "source": "SM_H1.csv", "sha256": self.sha, "from": 0, "to": 5,
                       "metres": list(range(5)), "gaps": [], "blocks": [{"from_m": 0, "to_m": 5}],
                       "settings": {k: [] for k in cv.SETTINGS}, "default": "2-2", "log": None,
                       "swir": {"names": [], "values": []}, "tir": {"names": [], "values": []},
                       "validation": {"test_claim": "must not transfer to a new calculation"}}
        self.store = self.make_store()

    def make_store(self, runner=None):
        return cv.ChangeViewer(lambda: self.catalog, self.data, self.analysis, self.root / "cache", runner=runner or self.runner)

    def runner(self, source, out):
        (out / "data" / "H1.js").write_bytes(cv.result_bytes(self.result))

    def packaged(self):
        (self.analysis / "viewer" / "data" / "H1.js").write_bytes(cv.result_bytes(self.result))

    def finish(self, store=None):
        store = store or self.store
        until = time.monotonic() + 5
        while time.monotonic() < until:
            state = store.snapshot()
            if state["job"] and state["job"]["status"] != "running":
                return state
            time.sleep(0.01)
        self.fail("Background computation did not finish")

    def test_packaged_result_is_ready_only_for_current_physical_source(self):
        self.packaged()
        self.assertEqual(self.store.snapshot()["holes"][0]["status"], "ready")
        self.source_path.write_bytes(b"changed outside library")
        row = self.store.snapshot()["holes"][0]
        self.assertEqual(row["status"], "stale")
        self.assertFalse(row["can_compute"])
        self.assertIsNone(self.store.asset("data/H1.js"))

    def test_stale_package_is_computable_after_catalog_refresh(self):
        self.result["sha256"] = hashlib.sha256(b"older source").hexdigest()
        self.packaged()
        row = self.store.snapshot()["holes"][0]
        self.assertEqual(row["status"], "stale")
        self.assertTrue(row["can_compute"])

    def test_missing_compute_is_cached_and_reused_after_restart_without_validation_claim(self):
        self.assertEqual(self.store.snapshot()["holes"][0]["status"], "missing")
        self.store.start({"hole_ids": ["H1"]})
        state = self.finish()
        self.assertEqual(state["holes"][0]["status"], "ready")
        self.assertEqual(state["job"]["completed"], 1)
        cache_path = self.store._cache_path("H1", self.sha)
        document = cv.read_result(cache_path, "H1")
        self.assertIsNone(document["validation"])
        self.assertEqual(document["calculation"]["source_sha256"], self.sha)
        restarted = self.make_store(runner=lambda *_: self.fail("cached result recomputed"))
        self.assertEqual(restarted.start({"hole_ids": ["H1"]})["holes"][0]["computed_from"], "local cache")
        self.assertIsNone(restarted.snapshot()["job"])

    def test_background_job_does_not_block_and_second_compute_is_rejected(self):
        gate = threading.Event()
        entered = threading.Event()
        self.addCleanup(gate.set)
        def slow(source, out):
            entered.set()
            gate.wait(3)
            self.runner(source, out)
        self.store = self.make_store(slow)
        self.store.start({"hole_ids": ["H1"]})
        self.assertTrue(entered.wait(2))
        row = self.store.snapshot()["holes"][0]
        self.assertEqual(row["status"], "running")
        with self.assertRaises(cv.BusyError):
            self.store.start({"hole_ids": ["H1"]})
        gate.set()
        self.finish()

    def test_source_changed_during_calculation_is_never_published(self):
        def changing(source, out):
            self.runner(source, out)
            source.write_bytes(b"changed during compute")
        self.store = self.make_store(changing)
        self.store.start({"hole_ids": ["H1"]})
        state = self.finish()
        self.assertEqual(state["job"]["failed"], 1)
        self.assertFalse(self.store._cache_path("H1", self.sha).exists())
        self.assertIsNone(self.store.asset("data/H1.js"))

    def test_method_change_invalidates_local_cache(self):
        self.store.start({"hole_ids": ["H1"]})
        self.finish()
        (self.analysis / "hylogger_pipeline" / "boundaries.py").write_text("# revised method", encoding="utf-8")
        self.assertEqual(self.make_store().snapshot()["holes"][0]["status"], "missing")

    def test_changed_reference_suppresses_company_lines_but_keeps_candidates(self):
        database = self.data / "HyLogger_Dataset_Package.sqlite"
        database.write_bytes(b"reference version one")
        self.result["log"] = [2]
        self.result["reference_source"] = {"sha256": cv.digest_file(database)}
        self.store.start({"hole_ids": ["H1"]})
        self.finish()
        self.assertTrue(self.store.snapshot()["holes"][0]["has_company_log"])
        database.write_bytes(b"reference version two is changed")
        row = self.store.snapshot()["holes"][0]
        self.assertEqual(row["status"], "ready")
        self.assertFalse(row["has_company_log"])

    def test_missing_numpy_disables_calculation_but_not_saved_results(self):
        self.store.compute_available = False
        row = self.store.snapshot()["holes"][0]
        self.assertEqual(row["status"], "unsupported")
        self.assertIn("NumPy", row["reason"])
        self.packaged()
        self.assertEqual(self.store.snapshot()["holes"][0]["status"], "ready")

    def test_unsupported_groups_and_nonmetre_records_cannot_compute(self):
        self.source["fields"] = self.source["fields"][:-1]
        self.assertEqual(self.store.snapshot()["holes"][0]["status"], "unsupported")
        with self.assertRaises(ValueError):
            self.store.start({"hole_ids": ["H1"]})
        self.source["fields"] = list(cv.COMPOSITION_COLUMNS)
        self.catalog["records"][0]["to_m"] = 0.5
        self.assertFalse(self.store.snapshot()["holes"][0]["can_compute"])

    def test_quality_column_case_does_not_change_36_group_eligibility(self):
        self.source["fields"] += ["Invalid_(System_SWIR)", "INVALID_(System_TIR)"]
        self.assertEqual(self.store.snapshot()["holes"][0]["status"], "missing")
        self.assertTrue(self.store.snapshot()["holes"][0]["can_compute"])

    def test_real_catalog_is_eligible_without_packaged_results(self):
        data_root = Path(app.ROOT).parent / "data"
        if not data_root.is_dir():
            self.skipTest("Source library is not included in this checkout")
        catalog = app.load_app_catalog(data_root)
        store = cv.ChangeViewer(lambda: catalog, data_root, self.analysis, self.root / "real-cache", runner=self.runner)
        statuses = store.snapshot()["holes"]
        target = next((h for h in statuses if h["hole_id"] == "CMDD001"), None)
        if target is None:
            self.skipTest("CMDD001 is not loaded")
        self.assertEqual(target["status"], "missing")
        self.assertTrue(target["can_compute"])
        self.assertTrue(all(h["can_compute"] for h in statuses), statuses)

    def test_static_assets_are_allowlisted_and_index_only_contains_ready_holes(self):
        self.assertNotIn(b'H1', self.store.asset("data/index.js")[0])
        self.packaged()
        self.assertIn(b'H1', self.store.asset("data/index.js")[0])
        for path in ("../build_viewer.py", "data/../../build_viewer.py", "data/%2e%2e/H1.js", "data/H2.js", "viewer/../index.html"):
            self.assertIsNone(self.store.asset(path))
        self.assertIsNotNone(self.store.asset("viewer-data.js"))

    def test_unknown_duplicate_and_excess_holes_rejected(self):
        for payload in ({"hole_ids": ["../H1"]}, {"hole_ids": ["H1", "H1"]}, {"hole_ids": []},
                        {"hole_ids": ["H1"] * 7}, {"hole_ids": "H1"}, {"hole_ids": ["H1"], "path": "/tmp"}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.store.start(payload)

    def test_results_are_parsed_never_evaluated(self):
        path = self.analysis / "viewer" / "data" / "H1.js"
        path.write_text('window.HOLE_DATA["H1"]=alert(1);', encoding="utf-8")
        self.assertEqual(self.store.snapshot()["holes"][0]["status"], "missing")
        self.assertIsNone(self.store.asset("data/H1.js"))

    def test_failed_job_is_retryable_without_partial_result(self):
        def failed(*args):
            raise ValueError("Calculation needs NumPy installed.")
        self.store = self.make_store(failed)
        self.store.start({"hole_ids": ["H1"]})
        state = self.finish()
        self.assertEqual(state["holes"][0]["status"], "error")
        self.assertTrue(state["holes"][0]["can_compute"])
        self.store.runner = self.runner
        self.store.start({"hole_ids": ["H1"]})
        self.assertEqual(self.finish()["holes"][0]["status"], "ready")

    def test_http_routes_keep_main_frame_restriction_and_reject_cross_origin_compute(self):
        self.packaged()
        server = app.create_server(self.catalog, port=0, data_root=self.data,
                                   change_viewer_root=self.analysis, change_viewer_cache=self.root / "http-cache")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        self.addCleanup(connection.close)
        for path, ancestor in (("/health", "'none'"), ("/change-viewer/index.html", "'self'")):
            connection.request("GET", path)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn("frame-ancestors " + ancestor, response.getheader("Content-Security-Policy"))
            response.read()
        connection.request("GET", "/api/change-viewer")
        response = connection.getresponse()
        self.assertEqual(json.loads(response.read())["holes"][0]["status"], "ready")
        connection.request("POST", "/api/change-viewer/compute", json.dumps({"hole_ids": ["H1"]}),
                           {"Content-Type": "application/json", "Origin": "https://example.com"})
        response = connection.getresponse()
        self.assertEqual(response.status, 403)
        response.read()


if __name__ == "__main__":
    unittest.main()
