"""Formal application HTTP checks using a local ephemeral server and real inputs.

Author: Ding Qing
Date: 2026-10-15
"""
import io
import http.client
import json
import os
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import zipfile

import app


@unittest.skipUnless(os.environ.get("HYLOGGER_DATA_ROOT"), "Set HYLOGGER_DATA_ROOT for real integration tests")
class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = app.load_app_catalog(os.environ["HYLOGGER_DATA_ROOT"])
        cls.server = app.create_server(cls.catalog, port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.spec = dict(hole_ids=["CMDD001", "CMDD002"], metric_id="aloh_2200w_summary", depth_from_m=0, depth_to_m=150, threshold=2200, min_run_m=3, operator="gte")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(3)

    def request(self, path, payload=None, headers=None):
        data = None if payload is None else json.dumps(payload).encode()
        h = {"Content-Type": "application/json"} if payload is not None else {}
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=data, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers

    def test_health_and_assets(self):
        for route in ["/health", "/", "/app.js", "/app.css", "/basemap.json", "/api/catalog"]:
            with self.subTest(route=route):
                status, body, headers = self.request(route)
                self.assertEqual(status, 200)
                self.assertTrue(body)
                self.assertIn("nosniff", headers.get("X-Content-Type-Options"))

    def test_real_query_export_and_restore(self):
        code, raw, _ = self.request("/api/query", self.spec)
        self.assertEqual(code, 200, raw)
        result = json.loads(raw)
        for row in result["records"] + result["evidence"]:
            self.assertNotIn("raw_row", row)
            self.assertTrue({"raw_token", "source_sha256", "data_record_index", "record_id"} <= set(row))
        self.assertIn("raw_row", self.catalog["records"][0])
        self.assertEqual([(r["hole_id"], r["from_m"], r["to_m"]) for r in result["runs"]], [("CMDD001", 0, 27), ("CMDD001", 30, 35), ("CMDD002", 53, 64)])
        envelope = {"schema_version": result["versions"]["schema_version"], "query": result["query"], "query_id": result["query_id"], "versions": result["versions"]}
        code, blob, headers = self.request("/api/export", envelope)
        self.assertEqual(code, 200, blob[:300])
        self.assertEqual(headers.get_content_type(), "application/zip")
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            self.assertIsNone(archive.testzip())
            query = json.loads(archive.read("query.json"))
            self.assertTrue({"query.json", "holes.csv", "intervals.csv", "evidence.csv", "manifest.json", "README.txt"} <= set(archive.namelist()))
        code, raw, _ = self.request("/api/restore", query)
        self.assertEqual(code, 200, raw)
        restored = json.loads(raw)
        self.assertTrue(restored["reproduced"])
        self.assertEqual(restored["query_id"], result["query_id"])

    def test_validation_error_keeps_server_available(self):
        code, raw, _ = self.request("/api/query", {**self.spec, "min_run_m": 0})
        self.assertEqual(code, 400)
        self.assertIn("error", json.loads(raw))
        self.assertEqual(self.request("/health")[0], 200)

    def test_optional_analysis_is_separate_from_query(self):
        _, before, _ = self.request("/api/query", self.spec)
        expected = {"hole_id": "CMDD001", "available": False,
                    "status": "unavailable", "reason": "No local analysis package."}
        with patch("app.analysis_overlay.load_hole_overlay", return_value=expected) as load:
            status, body, _ = self.request("/api/analysis?hole_id=CMDD001")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), expected)
            load.assert_called_once_with(self.catalog, "CMDD001", None)
        _, after, _ = self.request("/api/query", self.spec)
        self.assertEqual(json.loads(before)["query_id"], json.loads(after)["query_id"])
        self.assertEqual(json.loads(before)["runs"], json.loads(after)["runs"])

    def test_analysis_accepts_only_one_catalogue_hole(self):
        for route in ("/api/analysis", "/api/analysis?hole_id=",
                      "/api/analysis?hole_id=CMDD001&hole_id=CMDD002",
                      "/api/analysis?hole_id=CMDD001&path=x",
                      "/api/analysis?hole_id=..%2Fengine.py"):
            with self.subTest(route=route):
                self.assertEqual(self.request(route)[0], 400)

    def test_wrong_content_type(self):
        # All rejections must remain readable; an early close with unread
        # request bytes previously produced intermittent WinError 10053.
        for attempt in range(20):
            with self.subTest(attempt=attempt):
                status, body, _ = self.request("/api/query", self.spec, {"Content-Type": "text/plain"})
                self.assertEqual(status, 415)
                self.assertEqual(json.loads(body)["error"], "Send application/json.")

    def test_oversize_request_rejected_before_reading_body(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.putrequest("POST", "/api/restore")
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(app.MAX_BODY + 1))
            connection.endheaders()
            self.assertEqual(connection.getresponse().status, 413)
        finally:
            connection.close()

    def test_cross_origin_rejected(self):
        self.assertEqual(self.request("/api/query", self.spec, {"Origin": "https://example.invalid"})[0], 403)

    def test_foreign_host_rejected(self):
        self.assertEqual(self.request("/health", headers={"Host": "example.invalid"})[0], 403)

    def test_unpublished_file_paths_unavailable(self):
        for route in ["/engine.py", "/../coordinates.json", "/work/data_manifest.json"]:
            self.assertEqual(self.request(route)[0], 404)

    def test_no_external_bind(self):
        with self.assertRaises(ValueError):
            app.create_server(self.catalog, host="0.0.0.0", port=0)


if __name__ == "__main__":
    unittest.main()
