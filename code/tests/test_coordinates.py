"""Synthetic coordinate loader tests; no original coordinates or data fixtures.

Author: Ding Qing
Date: 2026-10-15
"""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import coords


class CoordinatesTests(unittest.TestCase):
    def setUp(self):
        # Keep synthetic fixtures short even when the user's project path is long.
        # The separate real-source test checks the actual release directory layout.
        for name, value in (("DATABASE_PATH", Path("db/source.sqlite")),
                            ("METADATA_PATH", Path("meta/source.pdf"))):
            patcher = patch.object(coords, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        fixture_parent = Path(__file__).resolve().parent
        self.temp = tempfile.TemporaryDirectory(dir=fixture_parent, prefix=".coordinates-")
        assert Path(self.temp.name).resolve().is_relative_to(fixture_parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / coords.DATABASE_PATH
        self.metadata = self.root / coords.METADATA_PATH
        self.database.parent.mkdir(parents=True)
        self.metadata.parent.mkdir(parents=True)
        self.metadata.write_bytes(b"Synthetic test metadata; not official source data.")
        with closing(sqlite3.connect(self.database)) as db, db:
            db.executescript("""
                CREATE TABLE hylogger_dataset_index (
                    HyloggerIndexId INTEGER, Data_name TEXT, Hole_name TEXT,
                    NVCL_HoleName TEXT, WAMEX_CollarId TEXT,
                    WAMEX_report_Anumber TEXT, Primary_report_number TEXT,
                    Confidentiality_primary_Anumber TEXT);
                CREATE TABLE wamex_collar (
                    CollarId INTEGER, CompanyHoleId TEXT, Anumber INTEGER,
                    Longitude REAL, Latitude REAL, Confidential INTEGER, MaxDepth REAL);
            """)
            for number, hole in enumerate(coords.HOLES, 1):
                db.execute("INSERT INTO hylogger_dataset_index VALUES (?,?,?,?,?,?,?,?)",
                           (number, hole, hole, hole, str(number), "7", "7", "OPEN FILE"))
                db.execute("INSERT INTO wamex_collar VALUES (?,?,?,?,?,?,?)",
                           (number, hole, 7, 120 + number / 10, -25 - number / 10, 0, 100))

    def execute(self, *, trust_fixture=True):
        release = {(coords._sha256(self.database), coords._sha256(self.metadata)):
                   "GDA2020 geographic coordinates (decimal degrees)"}
        if trust_fixture:
            with patch.dict(coords.TRUSTED_RELEASES, release, clear=True):
                return coords.load_coordinates(self.root)
        return coords.load_coordinates(self.root)

    def edit(self, statement, args=()):
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute(statement, args)

    def assert_unlocated(self, item, contains):
        self.assertIsNone(item["longitude"])
        self.assertIsNone(item["latitude"])
        self.assertIsNone(item["crs"])
        self.assertFalse(item["verified"])
        self.assertIn(contains, item["note"])

    def test_verified_exact_join_is_read_only_and_portable(self):
        before = self.database.read_bytes()
        result = self.execute()
        self.assertEqual(result["CMDD001"]["longitude"], 120.1)
        self.assertEqual(result["CMDD002"]["latitude"], -25.2)
        self.assertEqual(result["CMDD001"]["collar_id"], 1)
        self.assertEqual(result["CMDD002"]["coordinate_source"]["primary_report_anumber"], 7)
        self.assertIsNone(result["CMDD001"]["coordinate_source"]["crs_authority_code"])
        self.assertTrue(all(item["verified"] for item in result.values()))
        self.assertEqual(self.database.read_bytes(), before)
        self.assertFalse(Path(str(self.database) + "-journal").exists())
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_absent_database_never_created(self):
        self.database.unlink()
        for item in coords.load_coordinates(self.root).values():
            self.assert_unlocated(item, "absent")
        self.assertFalse(self.database.exists())

    def test_missing_metadata_does_not_guess_crs(self):
        self.metadata.unlink()
        for item in coords.load_coordinates(self.root).values():
            self.assert_unlocated(item, "metadata PDF is absent")

    def test_unreviewed_pair_does_not_guess_crs(self):
        for item in self.execute(trust_fixture=False).values():
            self.assert_unlocated(item, "not a reviewed release")

    def test_changed_metadata_invalidates_trust(self):
        release = {(coords._sha256(self.database), coords._sha256(self.metadata)): "GDA2020"}
        self.metadata.write_bytes(b"Different source declaration")
        with patch.dict(coords.TRUSTED_RELEASES, release, clear=True):
            for item in coords.load_coordinates(self.root).values():
                self.assert_unlocated(item, "not a reviewed release")

    def test_changed_database_invalidates_crs_binding(self):
        release = {(coords._sha256(self.database), coords._sha256(self.metadata)): "GDA2020"}
        self.edit("UPDATE wamex_collar SET Longitude = 130")
        with patch.dict(coords.TRUSTED_RELEASES, release, clear=True):
            for item in coords.load_coordinates(self.root).values():
                self.assert_unlocated(item, "not a reviewed release")

    def test_missing_index_is_unlocated_only_for_affected_hole(self):
        self.edit("DELETE FROM hylogger_dataset_index WHERE NVCL_HoleName='CMDD001'")
        result = self.execute()
        self.assert_unlocated(result["CMDD001"], "found 0")
        self.assertTrue(result["CMDD002"]["verified"])

    def test_duplicate_index_is_unlocated(self):
        self.edit("INSERT INTO hylogger_dataset_index SELECT * FROM hylogger_dataset_index WHERE NVCL_HoleName='CMDD001'")
        self.assert_unlocated(self.execute()["CMDD001"], "found 2")

    def test_name_only_alternate_does_not_affect_primary_join(self):
        self.edit("INSERT INTO wamex_collar VALUES (9,'CMDD001',8,129.0,-22.0,0,100)")
        result = self.execute()["CMDD001"]
        self.assertTrue(result["verified"])
        self.assertEqual(result["collar_id"], 1)
        self.assertEqual(result["longitude"], 120.1)

    def test_missing_or_duplicate_primary_collar_is_unlocated(self):
        for statement, expected in (
            ("DELETE FROM wamex_collar WHERE CollarId=1", "found 0"),
            ("INSERT INTO wamex_collar SELECT * FROM wamex_collar WHERE CollarId=2", "found 2"),
        ):
            self.edit(statement)
            hole = "CMDD001" if "DELETE" in statement else "CMDD002"
            self.assert_unlocated(self.execute()[hole], expected)

    def test_identity_mismatches_fail_closed(self):
        for column, value, table, expected in (
            ("Data_name", "OTHER", "hylogger_dataset_index", "identifiers disagree"),
            ("Hole_name", "OTHER", "hylogger_dataset_index", "identifiers disagree"),
            ("CompanyHoleId", "OTHER", "wamex_collar", "company hole identifier"),
            ("Anumber", 8, "wamex_collar", "Collar report"),
            ("Primary_report_number", "8", "hylogger_dataset_index", "primary report identifiers"),
        ):
            with self.subTest(column=column):
                with closing(sqlite3.connect(self.database)) as db, db:
                    old = db.execute(f"SELECT {column} FROM {table} LIMIT 1").fetchone()[0]
                    db.execute(f"UPDATE {table} SET {column}=?", (value,))
                self.assert_unlocated(self.execute()["CMDD001"], expected)
                self.edit(f"UPDATE {table} SET {column}=? WHERE rowid=1", (old,))

    def test_invalid_identifier_never_coerced(self):
        for value in (None, "1 OR 1=1", "1.0", "-1", "0", "1x"):
            with self.subTest(value=value):
                self.edit("UPDATE hylogger_dataset_index SET WAMEX_CollarId=? WHERE NVCL_HoleName='CMDD001'", (value,))
                self.assert_unlocated(self.execute()["CMDD001"], "exact positive integer")

    def test_out_of_bounds_or_non_numeric_positions_unlocated(self):
        for column, value in (("Longitude", 181), ("Longitude", "east"), ("Latitude", 91), ("Latitude", None), ("Latitude", float("inf"))):
            with self.subTest(column=column, value=value):
                self.edit(f"UPDATE wamex_collar SET Longitude=120.1, Latitude=-25.1, {column}=? WHERE CollarId=1", (value,))
                self.assert_unlocated(self.execute()["CMDD001"], "validation failed")

    def test_non_open_file_records_unlocated(self):
        self.edit("UPDATE wamex_collar SET Confidential=1 WHERE CollarId=1")
        self.assert_unlocated(self.execute()["CMDD001"], "not marked open file")
        self.edit("UPDATE hylogger_dataset_index SET Confidentiality_primary_Anumber='CONFIDENTIAL' WHERE NVCL_HoleName='CMDD002'")
        self.assert_unlocated(self.execute()["CMDD002"], "not identify the primary report as open file")

    def test_missing_schema_is_reported_without_crashing_summary_app(self):
        self.edit("DROP TABLE wamex_collar")
        for item in self.execute().values():
            self.assert_unlocated(item, "expected verifiable collar schema")


@unittest.skipUnless(os.environ.get("HYLOGGER_DATA_ROOT"), "Set HYLOGGER_DATA_ROOT for optional external-source validation")
class ExternalSourceCoordinateTests(unittest.TestCase):
    def test_local_release_positions_resolve_from_sources(self):
        root = Path(os.environ["HYLOGGER_DATA_ROOT"])
        result = coords.load_coordinates(root)
        self.assertEqual(set(result), set(coords.HOLES))
        for hole, item in result.items():
            with self.subTest(hole=hole):
                self.assertTrue(item["verified"], item.get("note"))
                self.assertIn("GDA2020", item["crs"])
                self.assertEqual(item["source_table"], "wamex_collar")
                self.assertIsNone(item["coordinate_source"]["crs_authority_code"])


if __name__ == "__main__":
    unittest.main()
