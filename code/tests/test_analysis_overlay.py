"""Source identity and depth integrity of optional candidate-change overlays.

Author: Ding Qing
Date: 2026-10-15
"""

import copy
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from analysis_overlay import COMPOSITION_COLUMNS, load_hole_overlay


SOURCE_HASH = hashlib.sha256(b"summary version one").hexdigest()
OTHER_HASH = hashlib.sha256(b"summary version two").hexdigest()
COLUMNS = list(COMPOSITION_COLUMNS)


def package():
    return {
        "hole_id": "H1", "role": "test",
        "provenance": {"run_id": "20261015T070445Z-seed20261015",
                       "method_version": "mineral-boundaries/0.1",
                       "summary_csv_sha256": {"H1": SOURCE_HASH}},
        "method": {"segmentation": "exact optimal partitioning, L2 cost",
                   "feature_set": "composition36", "selected_on": ["DEV1", "DEV2"],
                   "preprocessing": {"columns": COLUMNS,
                                     "missing_policy": "N.A. encoded as zero for this calculation only"},
                   "params": {"beta": 2, "min_size_m": 2, "sigma2": 0.1, "penalty": 0.5}},
        "usable_blocks": [{"from_m": 10, "to_m": 20}],
        "candidates": [{"depth_m": 14, "segment_above": {"from_m": 10, "to_m": 14},
                        "segment_below": {"from_m": 14, "to_m": 20},
                        "parameter_stability": 0.75,
                        "top_changes": [{"metric": COLUMNS[0], "mean_above": 0.2,
                                         "mean_below": 0.6, "change": 0.4}]}],
        "reference": {"boundaries": [{"depth_m": 14.2, "code_above": "A", "code_below": "B"}]},
    }


class AnalysisOverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = {"manifest": {"sources": [{"hole_id": "H1", "filename": "SM_H1.csv",
                                                  "sha256": SOURCE_HASH}]},
                        "records": [{"hole_id": "H1", "from_m": d, "to_m": d + 1,
                                     "raw_token": "N.A.", "raw_row": {col: "N.A." for col in COLUMNS}}
                                    for d in range(10, 20)]}
        self.document = package()
        self.save()

    def save(self):
        folder = self.root / "H1"
        folder.mkdir(exist_ok=True)
        (folder / "boundaries.json").write_text(json.dumps(self.document), encoding="utf-8")

    def load(self, hole="H1"):
        return load_hole_overlay(self.catalog, hole, self.root)

    def test_matching_source_preserves_changes_and_keeps_query_data_untouched(self):
        original = copy.deepcopy(self.catalog)
        result = self.load()
        self.assertTrue(result["available"])
        self.assertEqual(result["depth_reference"], "along_hole_m")
        self.assertEqual(result["candidates"][0]["depth_m"], 14)
        self.assertEqual(result["candidates"][0]["drivers"][0]["before"], 0.2)
        self.assertEqual(result["candidates"][0]["stability"]["value"], 0.75)
        self.assertIn("not a probability", result["candidates"][0]["stability"]["description"])
        self.assertEqual(self.catalog, original)
        self.assertNotIn("reference", result)
        self.assertEqual(result["source"]["sha256"], SOURCE_HASH)
        self.assertEqual(result["candidates"][0]["id"], self.load()["candidates"][0]["id"])

    def test_changed_current_source_hides_all_candidates(self):
        self.catalog["manifest"]["sources"][0]["sha256"] = OTHER_HASH
        result = self.load()
        self.assertEqual(result["status"], "source_mismatch")
        self.assertFalse(result["available"])
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["source"]["current_sha256"], OTHER_HASH)

    def test_conflicting_loaded_versions_are_not_guessed(self):
        self.catalog["manifest"]["sources"].append({"hole_id": "H1", "sha256": OTHER_HASH})
        self.assertEqual(self.load()["status"], "source_ambiguous")

    def test_missing_package_and_missing_source_have_different_states(self):
        (self.root / "H1" / "boundaries.json").unlink()
        self.assertEqual(self.load()["status"], "analysis_missing")
        self.assertEqual(self.load("H2")["status"], "source_missing")

    def test_invalid_identifiers_cannot_read_a_sibling_package(self):
        for hole in ("../H1", "H1/..", "..\\H1", "C:\\H1"):
            with self.subTest(hole=hole):
                self.assertEqual(self.load(hole)["status"], "source_missing")

    def test_incomplete_json_is_unavailable_without_throwing(self):
        (self.root / "H1" / "boundaries.json").write_text('{"hole_id":', encoding="utf-8")
        self.assertEqual(self.load()["status"], "invalid_analysis")

    def test_unverifiable_provenance_never_enables_the_overlay(self):
        mutations = [lambda d: d["provenance"].pop("summary_csv_sha256"),
                     lambda d: d["provenance"].update(run_id=""),
                     lambda d: d.update(hole_id="H2")]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.document = package()
                mutate(self.document)
                self.save()
                self.assertEqual(self.load()["status"], "invalid_analysis")

    def test_candidate_cannot_bridge_a_source_gap(self):
        self.document["usable_blocks"] = [{"from_m": 10, "to_m": 14}, {"from_m": 15, "to_m": 20}]
        self.save()
        self.assertEqual(self.load()["status"], "invalid_analysis")

    def test_self_consistent_package_cannot_extend_beyond_actual_source(self):
        self.document["usable_blocks"][0]["to_m"] = 21
        self.document["candidates"][0]["segment_below"]["to_m"] = 21
        self.save()
        self.assertEqual(self.load()["status"], "invalid_analysis")

    def test_candidate_must_join_its_adjacent_segments(self):
        self.document["candidates"][0]["segment_below"]["from_m"] = 15
        self.save()
        self.assertEqual(self.load()["status"], "invalid_analysis")

    def test_bad_stability_or_driver_values_are_rejected(self):
        mutations = [lambda c: c.update(parameter_stability=1.2),
                     lambda c: c.update(parameter_stability=float("nan")),
                     lambda c: c["top_changes"][0].update(change=-0.4),
                     lambda c: c["top_changes"][0].update(mean_below=float("inf"))]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.document = package()
                mutate(self.document["candidates"][0])
                self.save()
                self.assertEqual(self.load()["status"], "invalid_analysis")

    def test_other_experiments_do_not_silently_use_proportion_units(self):
        self.document["method"]["feature_set"] = "aloh2200w"
        self.save()
        self.assertEqual(self.load()["status"], "unsupported_analysis")

    def test_no_candidates_is_a_valid_result(self):
        self.document["candidates"] = []
        self.save()
        result = self.load()
        self.assertTrue(result["available"])
        self.assertEqual(result["coverage"]["candidate_count"], 0)


class ReviewSheetTests(unittest.TestCase):
    save = AnalysisOverlayTests.save
    load = AnalysisOverlayTests.load

    def setUp(self):
        AnalysisOverlayTests.setUp(self)
        (self.root / "H1" / "boundaries.json").unlink()
        self.review_root = self.root / "results"
        (self.review_root / "sheets").mkdir(parents=True)
        self.manifest = [{"hole_id": "H1", "candidates": "1", "summary_csv_sha256": SOURCE_HASH,
                          "selection": "initial set"}]
        self.rows = [
            {"hole_id": "H1", "from_m": "10.0", "to_m": "14.0", "length_m": "4.0",
             "change_at_top": "start of a continuous block", "parameter_stability_at_top": ""},
            {"hole_id": "H1", "from_m": "14.0", "to_m": "20.0", "length_m": "6.0",
             "change_at_top": "Kaolin (SWIR) ↑ 0.20→0.60", "parameter_stability_at_top": "0.75"},
        ]
        self.save_sheet()

    def save_sheet(self):
        for path, rows in ((self.review_root / "holes.csv", self.manifest),
                           (self.review_root / "sheets" / "H1_segments.csv", self.rows)):
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)

    def test_sheet_records_both_hashes_without_inventing_run_parameters(self):
        result = self.load()
        self.assertTrue(result["available"])
        self.assertEqual(result["source"]["format"], "release_review_sheet")
        self.assertIsNone(result["source"]["run_id"])
        self.assertEqual(result["method"]["parameters"], {})
        self.assertEqual(len(result["source"]["manifest_sha256"]), 64)
        self.assertEqual(len(result["source"]["package_sha256"]), 64)
        self.assertTrue(result["candidates"][0]["drivers"][0]["rounded"])
        self.assertEqual(result["candidates"][0]["drivers"][0]["decimals"], 2)

    def test_sheet_with_missing_final_coverage_is_rejected(self):
        self.rows[1].update(to_m="19", length_m="5")
        self.save_sheet()
        self.assertEqual(self.load()["status"], "invalid_analysis")

    def test_sheet_wrong_count_or_hash_or_identity_is_rejected(self):
        for field, value, status in (("candidates", "2", "invalid_analysis"),
                                     ("summary_csv_sha256", OTHER_HASH, "source_mismatch"),
                                     ("hole_id", "H2", "invalid_analysis")):
            with self.subTest(field=field):
                original = copy.deepcopy(self.manifest)
                self.manifest[0][field] = value
                self.save_sheet()
                self.assertEqual(self.load()["status"], status)
                self.manifest = original

    def test_json_is_preferred_when_full_provenance_is_available(self):
        self.save()
        self.assertEqual(self.load()["source"]["format"], "boundaries_json")

    def test_sheet_does_not_join_two_source_blocks(self):
        self.catalog["records"] = [row for row in self.catalog["records"] if row["from_m"] != 16]
        self.assertEqual(self.load()["status"], "invalid_analysis")


if __name__ == "__main__":
    unittest.main()
