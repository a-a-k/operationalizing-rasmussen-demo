from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from experimentlib import (  # noqa: E402
    SERVICES,
    all_close,
    classify_slo,
    ilr,
    inverse_ilr,
    measurement_seconds,
    point_composition,
    type7_quantile,
)


class ExperimentLibTest(unittest.TestCase):
    def test_measurement_window_grid(self) -> None:
        self.assertEqual(measurement_seconds(1), 330)
        self.assertEqual(measurement_seconds(2), 180)
        self.assertEqual(measurement_seconds(8), 180)

    def test_type7_quantile(self) -> None:
        self.assertEqual(type7_quantile([0, 10], 0.95), 9.5)
        self.assertIsNone(type7_quantile([], 0.95))

    def test_slo_boundary_is_strict_for_errors(self) -> None:
        self.assertTrue(classify_slo(500.0, 1000, 1000)["safe"])
        self.assertFalse(classify_slo(500.0, 990, 1000)["safe"])
        self.assertFalse(classify_slo(None, 1000, 1000)["safe"])

    def test_ilr_round_trip(self) -> None:
        original = {"checkout": 0.4, "payment": 0.3, "shipping": 0.3}
        r, n = ilr(original, "checkout", "payment", "shipping")
        restored = inverse_ilr(r, n, "checkout", "payment", "shipping")
        self.assertTrue(all_close((original[key] for key in SERVICES), (restored[key] for key in SERVICES)))

    def test_paths_hold_orthogonal_coordinate(self) -> None:
        roles = {"critical": "checkout", "n1": "payment", "n2": "shipping"}
        baseline = {"checkout": 0.4, "payment": 0.3, "shipping": 0.3}
        r0, n0 = ilr(baseline, **roles)
        a = point_composition("A", 5, 0.5, roles)
        b = point_composition("B", 5, 0.5, roles)
        ra, _ = ilr(a, **roles)
        _, nb = ilr(b, **roles)
        self.assertAlmostEqual(ra, r0)
        self.assertAlmostEqual(nb, n0)
        self.assertAlmostEqual(sum(a.values()), 1.0)
        self.assertAlmostEqual(sum(b.values()), 1.0)


if __name__ == "__main__":
    unittest.main()
