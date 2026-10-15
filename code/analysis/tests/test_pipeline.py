"""Tests: shared real-data acceptance case + synthetic edge cases (clearly synthetic).

Run from this folder:
  HYLOGGER_DATA_ROOT=../../data python -m unittest discover -s tests -v
Real-data tests are skipped (and reported as skipped) when the two summary CSVs are absent.
Set HYLOGGER_TEST_TMP to a writable folder if the system temp folder is not writable.

Author: Ding Qing
Date: 2026-10-15
"""
import os
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hylogger_pipeline.summary_csv import read_summary_csv  # noqa: E402
from hylogger_pipeline.intervals import find_runs  # noqa: E402

DATA = Path(os.environ.get("HYLOGGER_DATA_ROOT", Path(__file__).resolve().parents[2] / "data"))
def _find(name):
    """Locate a source file anywhere under the data folder (no fixed layout)."""
    hits = sorted(DATA.rglob(name)) if DATA.is_dir() else []
    return hits[0] if hits else DATA / name


CSV1 = _find("SM_CMDD001.csv")
CSV2 = _find("SM_CMDD002.csv")
HAVE_REAL = CSV1.exists() and CSV2.exists()
W = "2200W_AlOH"


def _q(holes, minlen, thr=2200, conds=None):
    conds = conds or [{"metric": W, "op": ">=", "value": thr}]
    res = [find_runs(h, conds, 0, 150, minlen) for h in holes]
    runs = [(r["hole_id"], x["from_m"], x["to_m"]) for r in res for x in r["runs"]]
    return runs, sum(x["length_m"] for r in res for x in r["runs"])


@unittest.skipUnless(HAVE_REAL, f"real summary CSVs not found under {DATA}")
class RealAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h1, cls.h2 = read_summary_csv(CSV1), read_summary_csv(CSV2)

    def test_identity_and_shape(self):
        self.assertEqual((self.h1["hole_id"], len(self.h1["records"])), ("CMDD001", 45))
        self.assertEqual((self.h2["hole_id"], len(self.h2["records"])), ("CMDD002", 100))
        self.assertEqual(len(self.h1["registry"]), 49)
        self.assertEqual(self.h1["source"]["sha256"], "839e89f496a2d01919c37c77e6fac6968e51868d70a75792072012fa27e3d4bb")
        self.assertEqual(self.h2["source"]["sha256"], "184f516414a92c87faedcb03659d9e05aa29145e445e6d50735fdd601444a036")

    def test_min_1m(self):
        runs, total = _q([self.h1, self.h2], 1)
        self.assertEqual((len(runs), total), (17, Decimal("59")))

    def test_min_3m(self):
        runs, total = _q([self.h1, self.h2], 3)
        self.assertEqual(runs, [("CMDD001", 0, 27), ("CMDD001", 30, 35), ("CMDD002", 53, 64)])
        self.assertEqual(total, Decimal("43"))

    def test_min_12m(self):
        runs, total = _q([self.h1, self.h2], 12)
        self.assertEqual((runs, total), ([("CMDD001", 0, 27)], Decimal("27")))

    def test_coverage(self):
        r1 = find_runs(self.h1, [{"metric": W, "op": ">=", "value": 2200}], 0, 150, 3)
        r2 = find_runs(self.h2, [{"metric": W, "op": ">=", "value": 2200}], 0, 150, 3)
        self.assertEqual((r1["window_coverage_m"], r2["window_coverage_m"]), (Decimal(45), Decimal(100)))

    def test_near_threshold_value_not_rounded(self):
        rec = next(r for r in self.h2["records"] if r["from_m"] == 50)
        self.assertEqual(rec["values"][W], Decimal("2199.9641"))  # fails >= 2200 by 0.0359 nm

    def test_edge_flags(self):
        r1 = find_runs(self.h1, [{"metric": W, "op": ">=", "value": 2200}], 0, 150, 1)
        self.assertIn("starts_at_coverage_start", r1["runs"][0]["edge_flags"])
        self.assertIn("ends_at_coverage_end", r1["runs"][-1]["edge_flags"])

    def test_extra_condition(self):
        runs, total = _q([self.h1, self.h2], 3, conds=[{"metric": W, "op": ">=", "value": 2200},
                                                      {"metric": "White-Mica_(System_SWIR)", "op": ">=", "value": 0.2}])
        self.assertEqual(runs, [("CMDD001", 0, 16), ("CMDD001", 18, 22), ("CMDD001", 23, 27),
                                ("CMDD001", 32, 35), ("CMDD002", 53, 64)])
        self.assertEqual(total, Decimal("38"))


SYNTH = """GSWA TSG Summary Mineral Log,
Dataset,SYNTH1
N.A.,Not detected or below threshold
Depth_from_(m),Depth_to_(m),2200W_AlOH,Kaolin_(System_SWIR)
0.0,1.0,2201,0.5
1.0,2.0,2202,N.A.
2.0,3.0,N.A.,0.1
3.0,4.0,2203,0.2
4.0,5.0,2204,0.3
6.0,7.0,2205,0.4
7.0,8.0,2199,0.4
8.0,9.0,bad,0.4
9.0,10.0,2200,0.4
"""


class SyntheticEdges(unittest.TestCase):
    """Synthetic fixture (not real data): NA, gap, invalid token, equality, last-run flush."""

    def setUp(self):
        d = tempfile.mkdtemp(dir=os.environ.get("HYLOGGER_TEST_TMP"))
        p = Path(d) / "SM_SYNTH1.csv"
        p.write_text(SYNTH, encoding="utf-8")
        self.h = read_summary_csv(p)

    def runs(self, minlen=1, conds=None):
        conds = conds or [{"metric": W, "op": ">=", "value": 2200}]
        return [(x["from_m"], x["to_m"]) for x in find_runs(self.h, conds, 0, 20, minlen)["runs"]]

    def test_breaks(self):
        # NA at 2-3 breaks, gap 5-6 breaks, 2199 breaks, 'bad' breaks, equality passes, last run flushed
        self.assertEqual(self.runs(), [(0, 2), (3, 5), (6, 7), (9, 10)])

    def test_min_length(self):
        self.assertEqual(self.runs(2), [(0, 2), (3, 5)])

    def test_na_policy_explicit(self):
        conds = [{"metric": "Kaolin_(System_SWIR)", "op": ">=", "value": 0.2}]
        self.assertEqual(self.runs(1, conds), [(0, 1), (3, 5), (6, 10)])
        conds = [{"metric": "Kaolin_(System_SWIR)", "op": ">=", "value": 0.2, "na_passes": True}]
        self.assertEqual(self.runs(1, conds), [(0, 2), (3, 5), (6, 10)])

    def test_gap_reported(self):
        self.assertEqual(self.h["gaps"], [{"from_m": Decimal("5.0"), "to_m": Decimal("6.0")}])


NEW = DATA
NEW_EXPECT = {  # hole: (records, first from_m, last to_m, gaps) - read from the files, recorded 2026-10-15
    "EHD001": (448, 0, 451, 3), "DRDD380": (709, 603, 1312, 0), "RBDD008": (685, 0, 685, 0)}


@unittest.skipUnless(all((_find(f"SM_{h}.csv")).exists() for h in NEW_EXPECT), f"new-hole CSVs not found under {NEW}")
class NewHolesReuse(unittest.TestCase):
    """Three randomly drawn holes (seed 20261015) parse with no per-hole configuration."""

    def test_parse_without_configuration(self):
        for h, (n, f, t, g) in NEW_EXPECT.items():
            hole = read_summary_csv(_find(f"SM_{h}.csv"))
            self.assertEqual(hole["hole_id"], h)
            self.assertEqual((len(hole["records"]), hole["records"][0]["from_m"], hole["records"][-1]["to_m"], len(hole["gaps"])),
                             (n, Decimal(f), Decimal(t), g))
            self.assertEqual(hole["issues"], [])
            self.assertFalse([m for m in hole["registry"] if m["kind"] == "unclassified"])

    def test_gap_breaks_runs(self):
        hole = read_summary_csv(_find("SM_EHD001.csv"))
        runs = find_runs(hole, [{"metric": W, "op": ">=", "value": 0}], 0, 451, 1)["runs"]
        self.assertTrue(all(not (x["from_m"] < 29 < x["to_m"]) for x in runs))  # gap 28-29 is never bridged


CLUSTER = DATA
CLUSTER_EXPECT = {"TBDD126": (232, 69, 301), "TBDD127": (79, 96, 175), "TBDD128": (180, 79, 259)}


@unittest.skipUnless(all((_find(f"SM_{h}.csv")).exists() for h in CLUSTER_EXPECT), f"TBDD CSVs not found under {CLUSTER}")
class ClusterHoles(unittest.TestCase):
    """Close cluster (report 94874, collars 60-164 m apart) for same-area cross-hole comparison."""

    def test_parse_and_common_window(self):
        holes = {}
        for h, (n, f, t) in CLUSTER_EXPECT.items():
            hole = read_summary_csv(_find(f"SM_{h}.csv"))
            self.assertEqual((hole["hole_id"], len(hole["records"]), hole["records"][0]["from_m"], hole["records"][-1]["to_m"]),
                             (h, n, Decimal(f), Decimal(t)))
            self.assertEqual((hole["issues"], hole["gaps"]), ([], []))
            holes[h] = hole
        lo = max(h["records"][0]["from_m"] for h in holes.values())
        hi = min(h["records"][-1]["to_m"] for h in holes.values())
        self.assertEqual((lo, hi), (Decimal(96), Decimal(175)))  # all three have data in [96,175)


# ---------------------------------------------------------------- import, coverage and classification rules
import json  # noqa: E402
import shutil  # noqa: E402
from hylogger_pipeline.package import build_package, occurrence_index  # noqa: E402

HDR = "GSWA TSG Summary Mineral Log,\nDataset,{h}\nN.A.,{na}\nDepth_from_(m),Depth_to_(m),2200W_AlOH,Kaolin_(System_SWIR),Invalid_(System_SWIR)\n"


def _write(tmp, name, hole, rows, na="Not detected or below threshold"):
    p = Path(tmp) / name
    p.write_text(HDR.format(h=hole, na=na) + "".join(rows), encoding="utf-8")
    return p


class V02Rules(unittest.TestCase):
    """Synthetic fixtures (not real data) for the v0.2 fixes."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(dir=os.environ.get("HYLOGGER_TEST_TMP"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_coverage_with_gap_not_clamped(self):
        p = _write(self.tmp, "SM_G1.csv", "G1", ["0,1,2201,0.5,N.A.\n", "1,2,2201,0.5,N.A.\n", "3,4,2201,0.5,N.A.\n"])
        doc = build_package(read_summary_csv(p), Path(self.tmp) / "out", collar={"max_depth_m": 3.5})
        c = doc["coverage"]
        self.assertEqual((c["extent_span_m"], c["covered_record_length_m"], c["gap_length_m"]), (Decimal(4), Decimal(3), Decimal(1)))
        self.assertAlmostEqual(float(c["covered_fraction_of_drilled_depth"]["value"]), 3 / 3.5)
        self.assertTrue(any("beyond the collar MaxDepth" in w for w in doc["warnings"]))  # 4 m > 3.5 m: warned, not clipped

    def test_quarantine_overlap_and_na_definition(self):
        p = _write(self.tmp, "SM_O1.csv", "O1", ["0,1,2201,0.5,N.A.\n", "0.5,1.5,2201,0.5,N.A.\n"])
        r = read_summary_csv(p)["import_review"]
        self.assertEqual((r["status"], r["queryable"]), ("quarantined", False))
        self.assertIn("overlapping records", r["reasons"])
        p = _write(self.tmp, "SM_N1.csv", "N1", ["0,1,2201,0.5,N.A.\n"], na="Not analysed")
        r = read_summary_csv(p)["import_review"]
        self.assertFalse(r["queryable"])

    def test_invalid_is_quality_not_mineral(self):
        p = _write(self.tmp, "SM_Q1.csv", "Q1", ["0,1,2201,0.5,0.1\n"])
        kinds = {m["id"]: m["kind"] for m in read_summary_csv(p)["registry"]}
        self.assertEqual(kinds["Invalid_(System_SWIR)"], "quality_fraction")
        self.assertEqual(kinds["Kaolin_(System_SWIR)"], "mineral_group_proportion")

    def test_duplicate_dataset_rules(self):
        import run_pipeline
        a = Path(self.tmp) / "a"; b = Path(self.tmp) / "b"; a.mkdir(); b.mkdir()
        rows = ["0,1,2201,0.5,N.A.\n"]
        _write(a, "SM_D1.csv", "D1", rows); _write(b, "SM_D1.csv", "D1", rows)            # identical
        _write(a, "SM_D2.csv", "D2", rows); _write(b, "SM_D2.csv", "D2", ["0,1,2199,0.5,N.A.\n"])  # conflicting
        out = Path(self.tmp) / "pk"
        run_pipeline.main(["--inputs", str(a), str(b), "--out", str(out)])
        m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        st = sorted((e["hole_id"], e["status"]) for e in m["log"])
        self.assertIn(("D1", "duplicate_identical_skipped"), st)
        self.assertIn(("D1", "packaged_queryable"), st)
        self.assertEqual([s for h, s in st if h == "D2"], ["conflict_not_packaged", "conflict_not_packaged"])
        self.assertNotIn("D2", m["queryable_holes"])

    def test_edge_flags_gap_and_window(self):
        p = _write(self.tmp, "SM_E1.csv", "E1", [f"{i},{i+1},2201,0.5,N.A.\n" for i in range(0, 10) if i != 5])
        h = read_summary_csv(p)
        runs = find_runs(h, [{"metric": W, "op": ">=", "value": 2200}], 2, 8, 1)["runs"]
        self.assertEqual([(x["from_m"], x["to_m"], x["edge_flags"]) for x in runs],
                         [(Decimal(2), Decimal(5), ["truncated_by_window_start", "ends_before_gap"]),
                          (Decimal(6), Decimal(8), ["starts_after_gap", "truncated_by_window_end"])])
        full = find_runs(h, [{"metric": W, "op": ">=", "value": 2200}], 0, 10, 1)["runs"]
        self.assertEqual(full[0]["edge_flags"], ["starts_at_coverage_start", "ends_before_gap"])
        self.assertEqual(full[-1]["edge_flags"], ["starts_after_gap", "ends_at_coverage_end"])

    def test_occurrence_uses_length_not_count(self):
        p = _write(self.tmp, "SM_H1.csv", "H1", ["0,0.5,2201,0.5,N.A.\n", "0.5,1.0,2201,0.5,N.A.\n", "1.0,3.0,2201,0.1,N.A.\n"])
        oi = occurrence_index(read_summary_csv(p))
        self.assertEqual(oi["Kaolin_(System_SWIR)"]["length_ge_threshold_m"], Decimal("1.0"))
        self.assertNotIn("Invalid_(System_SWIR)", oi)


@unittest.skipUnless(HAVE_REAL, "real CSVs absent")
class V02RealCounts(unittest.TestCase):
    def test_metric_kind_counts(self):
        reg = read_summary_csv(CSV1)["registry"]
        counts = {}
        for m in reg:
            counts[m["kind"]] = counts.get(m["kind"], 0) + 1
        self.assertEqual(counts, {"mineral_group_proportion": 36, "quality_fraction": 2, "feature_wavelength": 4,
                                  "feature_depth": 6, "albedo": 1})

    def test_whitespace_only_metadata_difference_same_group(self):
        groups = {read_summary_csv(CSV1)["metadata_group"]["id"]}
        if all((_find(f"SM_{h}.csv")).exists() for h in NEW_EXPECT):
            groups |= {read_summary_csv(_find(f"SM_{h}.csv"))["metadata_group"]["id"] for h in NEW_EXPECT}
        self.assertEqual(len(groups), 1)


try:
    import numpy as _np  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed (needed only for scan re-binning)")
class Rebin(unittest.TestCase):
    def test_tail_kept_and_gap_not_averaged(self):
        import numpy as np
        try:
            from hylogger_pipeline.tsg_scans import rebin
        except ImportError as e:  # pandas missing
            self.skipTest(str(e))
        depth = np.array([0.5, 1.5, 2.5, 3.5, 4.5]); vals = np.array([1.0, 1.0, 3.0, 3.0, 5.0]); keep = np.ones(5, bool)
        rows = rebin(depth, vals, keep, 0, 5, 2.0, gaps=[])
        self.assertEqual([(r["from_m"], r["to_m"], r["partial"]) for r in rows], [(0, 2, False), (2, 4, False), (4, 5, True)])
        self.assertEqual([r["mean"] for r in rows], [1.0, 3.0, 5.0])
        rows = rebin(depth, vals, keep, 0, 5, 2.0, gaps=[(2.0, 3.0)])
        self.assertEqual(rows[1]["status"], "spans_source_gap")
        self.assertIsNone(rows[1]["mean"])


if __name__ == "__main__":
    unittest.main()
