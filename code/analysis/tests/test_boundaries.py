"""Tests for the candidate-change module (synthetic data only; needs numpy and scipy).

Author: Ding Qing
Date: 2026-10-15
"""
import itertools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import numpy as np
    import scipy  # noqa: F401
    from hylogger_pipeline import boundaries as B
    HAVE = True
except ImportError:  # optional analysis stack absent
    HAVE = False


def _l2(seg):
    return float(((seg - seg.mean(axis=0)) ** 2).sum())


def _brute(X, pen, m):
    n = len(X)
    best = (float("inf"), None)
    for k in range(0, n):
        for cps in itertools.combinations(range(1, n), k):
            edges = [0, *cps, n]
            if any(b - a < m for a, b in zip(edges, edges[1:])):
                continue
            v = sum(_l2(X[a:b]) for a, b in zip(edges, edges[1:])) + pen * k
            if v < best[0] - 1e-12:
                best = (v, list(cps))
    return best


def _obj(X, cps, pen):
    edges = [0, *cps, len(X)]
    return sum(_l2(X[a:b]) for a, b in zip(edges, edges[1:])) + pen * len(cps)


@unittest.skipUnless(HAVE, "numpy/scipy not installed")
class Segmentation(unittest.TestCase):
    def test_matches_exhaustive_search(self):
        rng = np.random.default_rng(1)
        for trial in range(25):
            n = int(rng.integers(6, 12)); d = int(rng.integers(1, 4)); m = int(rng.integers(1, 4))
            X = rng.normal(size=(n, d)) + np.repeat(rng.normal(scale=3, size=(3, d)), [n // 3, n // 3, n - 2 * (n // 3)], axis=0)
            pen = float(rng.uniform(0.5, 8))
            best, _ = _brute(X, pen, m)
            got = B.optimal_partition(X, pen, m)
            self.assertAlmostEqual(_obj(X, got, pen), best, places=8, msg=f"trial {trial}")

    def test_known_breaks(self):
        rng = np.random.default_rng(7)
        X = np.concatenate([np.zeros((20, 2)), np.ones((15, 2)) * 3, np.zeros((25, 2)) - 2]) + rng.normal(scale=0.2, size=(60, 2))
        self.assertEqual(B.optimal_partition(X, pen=5.0, min_size=3), [20, 35])

    def test_too_short(self):
        self.assertEqual(B.optimal_partition(np.zeros((5, 1)), 1.0, 3), [])


@unittest.skipUnless(HAVE, "numpy/scipy not installed")
class Matching(unittest.TestCase):
    def test_one_to_one_and_tolerance(self):
        # two candidates near one reference: only one may match it
        s = B.score([10.0, 10.5], [10.2], tol=1.0)
        self.assertEqual((s["n_matched"], s["precision"], s["recall"]), (1, 0.5, 1.0))
        # inclusive tolerance in metres
        self.assertEqual(B.score([11.0], [10.0], tol=1.0)["n_matched"], 1)
        self.assertEqual(B.score([11.01], [10.0], tol=1.0)["n_matched"], 0)

    def test_max_matches_then_min_offset(self):
        # greedy nearest would pair 10<->10.6 and leave 11.4 unmatched; optimum keeps both
        s = B.score([10.0, 11.0], [10.6, 11.9], tol=1.0)
        self.assertEqual(s["n_matched"], 2)

    def test_empty(self):
        self.assertIsNone(B.score([], [5.0], 1.0)["precision"])
        self.assertIsNone(B.score([5.0], [], 1.0)["recall"])


@unittest.skipUnless(HAVE, "numpy/scipy not installed")
class Baselines(unittest.TestCase):
    def test_random_respects_blocks_and_spacing(self):
        froms = np.arange(0, 30, dtype=float)
        blocks = [(0, 12), (15, 30)]
        allowed = B.allowed_positions(froms, blocks, 3)
        self.assertTrue(all(3 <= d <= 9 or 18 <= d <= 27 for d, _ in allowed))
        rng = np.random.default_rng(0)
        for _ in range(50):
            got = B.random_placement(allowed, 4, 3, rng)
            self.assertEqual(len(got), 4)
            for a, b in zip(got, got[1:]):
                same = (a <= 11) == (b <= 11)
                if same:
                    self.assertGreaterEqual(b - a, 3)

    def test_equal_spacing_count(self):
        got = B.equal_spacing([{"from_m": 0, "to_m": 100}, {"from_m": 120, "to_m": 140}], 6, 3)
        self.assertEqual(len(got), 6)


if __name__ == "__main__":
    unittest.main()
