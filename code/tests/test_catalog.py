"""Eight-hole import, scalar selection and source evidence checks.

Author: Ding Qing
Date: 2026-10-15
"""

import copy
import csv
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
from collections import Counter

import coords
import engine
from datasets import SOURCES
from metrics import METRIC_REGISTRY
from tests.test_engine import independent_runs, write_summary


class RegistryTests(unittest.TestCase):
    def test_all_summary_fields_have_distinct_meanings(self):
        counts = Counter(metric["kind"] for metric in METRIC_REGISTRY.values())
        self.assertEqual(counts, {"mineral_group_proportion": 36, "quality_proportion": 2,
                                  "spectral_feature_wavelength": 4, "spectral_feature_depth": 6, "albedo": 1})
        self.assertEqual(METRIC_REGISTRY["2200D_AlOH"]["unit"], "dimensionless")
        self.assertEqual(METRIC_REGISTRY["2200W_AlOH"]["unit"], "nm")
        self.assertEqual(METRIC_REGISTRY["Invalid_(System_SWIR)"]["group"], "Quality")

    def test_unreviewed_source_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            write_summary(root, "CMDD001")
            with self.assertRaisesRegex(ValueError, "fingerprint differs"):
                engine.load_catalog(root, hole_ids=["CMDD001"])

    def test_whitespace_only_metadata_differences_are_compatible(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as root:
            write_summary(root, "CMDD001")
            write_summary(root, "CMDD002", **{"****W": "Wavelength of dominant spectral feature centred around wavelength **** (nm),\t labelled by typical feature assignment"})
            catalog = engine.load_catalog(root, hole_ids=engine.DEFAULT_HOLES, verify_sources=False)
            self.assertEqual(len(catalog["holes"]), 2)
            self.assertEqual(catalog["audit"]["source_issues"], [])


@unittest.skipUnless(os.environ.get("HYLOGGER_DATA_ROOT"), "Set HYLOGGER_DATA_ROOT for source checks")
class ReviewedCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ["HYLOGGER_DATA_ROOT"]).resolve()
        cls.catalog = engine.load_catalog(cls.root, coords.load_coordinates(cls.root))
        cls.source_rows = {}
        for hole, (relative, _) in SOURCES.items():
            with (cls.root / relative).open(encoding="utf-8-sig", newline="") as source:
                table = list(csv.reader(source))
            offset = next(i for i, row in enumerate(table) if row[:2] == ["Depth_from_(m)", "Depth_to_(m)"])
            cls.source_rows[hole] = [dict(zip(table[offset], row)) for row in table[offset + 1:] if any(row)]

    def test_eight_reviewed_sources_and_collars_are_loaded(self):
        catalog = self.catalog
        self.assertEqual(len(catalog["records"]), 2478)
        self.assertEqual(len(catalog["holes"]), 8)
        self.assertEqual(len(catalog["metric_registry"]), 49)
        self.assertFalse(catalog["audit"]["source_issues"])
        self.assertTrue(all(hole["located"] for hole in catalog["holes"]))
        for source in catalog["manifest"]["sources"]:
            self.assertEqual(source["sha256"], SOURCES[source["hole_id"]][1])
            self.assertTrue(source["fingerprint_verified"])

    def test_tbdd_common_window_matches_independent_reference(self):
        result = engine.run_query(self.catalog, engine.DEFAULT_QUERY)
        expected = {
            "TBDD126": [(96,105), (106,124), (125,132), (134,139), (146,151)],
            "TBDD127": [(96,109), (158,161)],
            "TBDD128": [(107,121), (122,127), (131,137), (138,143)],
        }
        actual = {hole: [(run["from_m"], run["to_m"]) for run in result["runs"] if run["hole_id"] == hole] for hole in expected}
        self.assertEqual(actual, expected)
        self.assertEqual((result["run_count"], result["total_length_m"]), (11, 90))

    def test_scalar_queries_match_decimal_source_oracle(self):
        for field, threshold in (("2200D_AlOH", "0.01"), ("Silica_(System_TIR)", "0.2")):
            with self.subTest(field=field):
                spec = dict(engine.DEFAULT_QUERY, hole_ids=list(SOURCES), depth_from_m=0,
                            depth_to_m=1312, metric_id=field, threshold=float(threshold))
                result = engine.run_query(self.catalog, spec)
                expected = []
                for hole, rows in self.source_rows.items():
                    values = [(Decimal(row["Depth_from_(m)"]), Decimal(row["Depth_to_(m)"]), Decimal(row[field]))
                              for row in rows if row[field] != "N.A."]
                    expected += [(hole, start, end) for start, end in independent_runs(values, Decimal(0), Decimal(1312), Decimal(threshold), 3)]
                actual = [(run["hole_id"], run["from_m"], run["to_m"]) for run in result["runs"]]
                self.assertEqual(sorted(actual), sorted(expected))

    def test_every_registered_scalar_keeps_source_tokens_and_record_ids(self):
        for field in METRIC_REGISTRY:
            spec = dict(engine.DEFAULT_QUERY, metric_id=field, hole_ids=["CMDD001"])
            result = engine.run_query(self.catalog, spec)
            self.assertEqual(len(result["records"]), 45)
            for record in result["records"]:
                raw = self.source_rows["CMDD001"][record["data_record_index"] - 1]
                self.assertEqual(record["raw_token"], raw[field])
                self.assertEqual(record["metric_id"], field)
                self.assertEqual(record["source_sha256"], SOURCES["CMDD001"][1])
        depth = engine.run_query(self.catalog, dict(engine.DEFAULT_QUERY, hole_ids=["CMDD001"], metric_id="2200D_AlOH"))
        wavelength = engine.run_query(self.catalog, dict(engine.DEFAULT_QUERY, hole_ids=["CMDD001"]))
        self.assertNotEqual(depth["records"][0]["record_id"], wavelength["records"][0]["record_id"])

    def test_metric_specific_missing_values_are_not_shared(self):
        result = engine.run_query(self.catalog, dict(engine.DEFAULT_QUERY, metric_id="White-Mica_(System_SWIR)", threshold=0.2))
        self.assertEqual([hole["numeric_coverage_m"] for hole in result["holes"]], [2, 9, 2])
        self.assertEqual([hole["row_coverage_m"] for hole in result["holes"]], [79, 79, 79])

    def test_coverage_excludes_gaps_and_preserves_depth_disagreements(self):
        holes = {hole["hole_id"]: hole for hole in self.catalog["holes"]}
        ehd = holes["EHD001"]
        self.assertEqual(ehd["extent_span_m"], 451)
        self.assertEqual(ehd["covered_record_length_m"], 448)
        self.assertAlmostEqual(ehd["covered_fraction_of_drilled_depth"], 448 / 451)
        warned = {issue["hole_id"] for issue in self.catalog["audit"]["issues"] if issue["reason"] == "summary_exceeds_collar_depth"}
        self.assertEqual(warned, {"DRDD380", "RBDD008", "TBDD126"})

    def test_legacy_metric_alias_is_explicitly_canonicalised(self):
        result = engine.run_query(self.catalog, dict(engine.DEFAULT_QUERY, metric_id="aloh_2200w_summary"))
        self.assertEqual(result["query"]["metric_id"], "2200W_AlOH")

    def test_scalar_export_uses_selected_metric_units_and_restores(self):
        result = engine.run_query(self.catalog, dict(engine.DEFAULT_QUERY, metric_id="2200D_AlOH", threshold=0.01))
        with zipfile.ZipFile(io.BytesIO(engine.make_export(self.catalog, result))) as archive:
            readme = archive.read("README.txt").decode("utf-8")
            self.assertIn("2200D_AlOH (dimensionless)", readme)
            restored = engine.restore_query(self.catalog, json.loads(archive.read("query.json")))
        self.assertEqual(restored["query_id"], result["query_id"])
        for row in result["evidence"]:
            self.assertIn("dimensionless", row["match_reason"])
            self.assertNotIn(" nm ", row["match_reason"])


if __name__ == "__main__":
    unittest.main()
