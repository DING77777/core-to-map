"""Folder ingestion rejects conflicts and preserves source meaning.

Author: Ding Qing
Date: 2026-10-15
"""

import csv
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

import app
import engine
import library
from tests.test_engine import write_summary


def summary(root, hole, values=("2201", "2202", "2203")):
    metadata = dict(library.SETTINGS)
    metadata["****D"] = "Background normalised depth of dominant spectral feature centred around wavelength **** (nm)"
    source = write_summary(root, hole, values=values, **metadata)
    destination = Path(root) / "inbox" / f"SM_{hole}.csv"
    destination.parent.mkdir(exist_ok=True)
    shutil.move(source, destination)
    return destination


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_unknown_hole_is_discovered_without_code_or_coordinates(self):
        summary(self.root, "TESTA")
        catalog = library.load_library(self.root)
        self.assertEqual([hole["hole_id"] for hole in catalog["holes"]], ["TESTA"])
        self.assertFalse(catalog["holes"][0]["located"])
        self.assertEqual(catalog["library"]["inbox_accepted_count"], 1)
        source = catalog["manifest"]["sources"][0]
        self.assertFalse(source["fingerprint_verified"])
        self.assertIsNone(source["source_url"])
        self.assertEqual(engine.run_query(catalog, catalog["default_query"])["total_length_m"], 3)

    def test_identical_copies_count_once_and_conflicting_versions_are_excluded(self):
        source = summary(self.root, "TESTA")
        copy = source.with_name("another.csv")
        shutil.copyfile(source, copy)
        catalog = library.load_library(self.root)
        self.assertEqual(len(catalog["records"]), 3)
        self.assertEqual(catalog["library"]["issues"][0]["reason"], "duplicate_ignored")
        copy.write_text(copy.read_text().replace("2203", "2204"))
        summary(self.root, "TESTB")
        catalog = library.load_library(self.root)
        self.assertEqual([hole["hole_id"] for hole in catalog["holes"]], ["TESTB"])
        self.assertIn("conflicting_versions", [issue["reason"] for issue in catalog["library"]["issues"]])

    def test_bad_file_does_not_break_good_hole_and_settings_are_checked(self):
        summary(self.root, "TESTA")
        bad = summary(self.root, "TESTB")
        bad.write_text(bad.read_text().replace("TSA+", "different algorithm"))
        (self.root / "inbox/not-a-summary.csv").write_text("hello,world\n1,2")
        catalog = library.load_library(self.root)
        self.assertEqual(len(catalog["holes"]), 1)
        self.assertEqual(sum(issue["reason"] == "source_rejected" for issue in catalog["library"]["issues"]), 2)

    def test_null_is_unknown_missing_and_breaks_continuity(self):
        summary(self.root, "TESTA", ("2201", "NULL", "2201"))
        catalog = library.load_library(self.root)
        records = catalog["records"]
        self.assertEqual(records[1]["raw_token"], "NULL")
        self.assertIsNone(records[1]["value"])
        self.assertEqual(records[1]["status"], "unknown_missing")
        result = engine.run_query(catalog, dict(catalog["default_query"], min_run_m=2))
        self.assertEqual(result["run_count"], 0)

    def test_alias_preserves_original_column_and_scalar_token(self):
        path = summary(self.root, "TESTA")
        rows = list(csv.reader(path.read_text().splitlines()))
        header = next(i for i, row in enumerate(rows) if row[0] == "Depth_from_(m)")
        rows[header].append("Invalid_(System_TIR)")
        for row in rows[header + 1:]:
            row.append("0.25")
        with path.open("w", newline="") as stream:
            csv.writer(stream).writerows(rows)
        catalog = library.load_library(self.root)
        result = engine.run_query(catalog, dict(catalog["default_query"], metric_id="INVALID_(System_TIR)", threshold=.2))
        self.assertEqual(result["total_length_m"], 3)
        row = result["evidence"][0]
        self.assertEqual(row["raw_row"]["Invalid_(System_TIR)"], "0.25")
        self.assertNotIn("INVALID_(System_TIR)", row["raw_row"])

    def test_refresh_adds_holes_and_failed_refresh_keeps_previous_catalog(self):
        first = summary(self.root, "TESTA")
        server = app.create_server(library.load_library(self.root), port=0, data_root=self.root)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            summary(self.root, "TESTB")
            request = urllib.request.Request(base + "/api/library/refresh", data=b"{}", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request) as response:
                catalog = json.load(response)
            self.assertEqual(len(catalog["holes"]), 2)
            for path in (self.root / "inbox").glob("*.csv"):
                path.unlink()
            with self.assertRaises(urllib.error.HTTPError) as rejected:
                urllib.request.urlopen(request)
            self.assertEqual(rejected.exception.code, 400)
            with urllib.request.urlopen(base + "/api/catalog") as response:
                self.assertEqual(len(json.load(response)["holes"]), 2)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(3)


if __name__ == "__main__":
    unittest.main()
