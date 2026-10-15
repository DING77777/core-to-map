"""Contracts used by the multi-hole workspace.

Author: Ding Qing
Date: 2026-10-15
"""

import json
import os
import threading
import unittest
import urllib.request

import app


@unittest.skipUnless(os.environ.get("HYLOGGER_DATA_ROOT"), "Set HYLOGGER_DATA_ROOT")
class WorkspaceHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = app.load_app_catalog(os.environ["HYLOGGER_DATA_ROOT"])
        cls.server = app.create_server(cls.catalog, port=0)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(3)

    def request(self, path, payload=None):
        raw = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.base + path, data=raw, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

    def test_default_workspace(self):
        catalog = self.request("/api/catalog")
        self.assertGreaterEqual(len(catalog["holes"]), 8)
        self.assertTrue({"CMDD001", "CMDD002", "TBDD126", "TBDD127", "TBDD128"}.issubset({h["hole_id"] for h in catalog["holes"]}))
        self.assertEqual(len(catalog["metrics"]), 49)
        self.assertEqual(len({metric["metric_id"] for metric in catalog["metrics"]}), 49)
        result = self.request("/api/query", catalog["default_query"])
        self.assertEqual((result["run_count"], result["total_length_m"]), (11, 90))
        self.assertEqual({hole["hole_id"] for hole in result["holes"]}, {"TBDD126", "TBDD127", "TBDD128"})

    def test_absorption_strength_is_not_wavelength(self):
        catalog = self.request("/api/catalog")
        result = self.request("/api/query", {**catalog["default_query"], "metric_id": "2200D_AlOH", "threshold": 0.01})
        self.assertEqual(result["metric"]["unit"], "dimensionless")
        self.assertTrue(result["evidence"])
        original = {(row["source_sha256"], row["data_record_index"]): row["raw_row"]
                    for row in self.catalog["records"]}
        for row in result["evidence"]:
            source = original[(row["source_sha256"], row["data_record_index"])]
            self.assertEqual(row["raw_token"], source["2200D_AlOH"])
            self.assertNotIn(" nm ", row["match_reason"])

    def test_catalog_separates_quality_from_minerals(self):
        catalog = self.request("/api/catalog")
        metrics = {metric["metric_id"]: metric for metric in catalog["metrics"]}
        self.assertEqual(metrics["Invalid_(System_SWIR)"]["kind"], "quality_proportion")
        self.assertEqual(metrics["INVALID_(System_TIR)"]["kind"], "quality_proportion")
        self.assertEqual(metrics["Silica_(System_TIR)"]["kind"], "mineral_group_proportion")


if __name__ == "__main__":
    unittest.main()
