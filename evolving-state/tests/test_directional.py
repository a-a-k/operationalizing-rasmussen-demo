"""Boundary rays, independent multiplicative continuation, and causal replay."""
from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path
import random
import sys
import unittest

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE / "scripts"))
from observer import ilr
from directional import (DESIGN, DirectHistory, analyze, direct_ratio, direct_ray,
                         helmert, ilr_ray, matched_states, norm, verify_ray)


def centered(values):
    logs = [math.log(x) for x in values]
    mean = math.fsum(logs) / len(logs)
    return [x - mean for x in logs]


def coordinates(vector):
    return [math.fsum(x * y for x, y in zip(row, vector)) for row in helmert(4)]


class DirectionalTests(unittest.TestCase):
    def assert_nested_close(self, actual, expected):
        if isinstance(expected, dict):
            self.assertEqual(set(actual), set(expected))
            for key in expected:
                self.assert_nested_close(actual[key], expected[key])
        elif isinstance(expected, list):
            self.assertEqual(len(actual), len(expected))
            for a, b in zip(actual, expected):
                self.assert_nested_close(a, b)
        elif isinstance(expected, float):
            self.assertTrue(math.isclose(actual, expected, abs_tol=1e-9, rel_tol=1e-9),
                            f"{actual} != {expected}")
        else:
            self.assertEqual(actual, expected)

    def test_known_crossing_and_two_constraints(self):
        counts = [100., 20., 100., 10.]
        velocity = [-.25, .75, -.25, -.25]
        limits = {"catalog": .5, "currency": .5}
        result = ilr_ray(ilr(counts), coordinates(velocity), limits)
        checked = direct_ray(counts, velocity, limits)
        verify_ray(result, checked)
        self.assertEqual(result["first_constraints"], ["catalog"])
        self.assertAlmostEqual(result["distance"], math.sqrt(.75) * math.log(5))
        self.assertAlmostEqual(result["groups"]["catalog"]["signed_perpendicular_distance"],
                               math.log(5) / math.sqrt(2))
        self.assertEqual(result["groups"]["currency"]["direction"], "tangent")
        s, w = checked["distance"], checked["unit_direction"]
        self.assertLess(direct_ratio(counts, w, s - 1e-6, 0, 1), .5)
        self.assertGreater(direct_ratio(counts, w, s + 1e-6, 0, 1), .5)

    def test_first_of_two_different_boundaries_and_ties(self):
        counts = [100., 20., 100., 20.]
        velocity = [-.5, .5, -.5, .5]
        limits = {"catalog": .5, "currency": .3}
        result = ilr_ray(ilr(counts), coordinates(velocity), limits)
        verify_ray(result, direct_ray(counts, velocity, limits))
        self.assertEqual(result["first_constraints"], ["currency"])
        limits["catalog"] = .3
        result = ilr_ray(ilr(counts), coordinates(velocity), limits)
        self.assertEqual(result["first_constraints"], ["catalog", "currency"])

    def test_away_stationary_and_already_violated(self):
        counts = [100., 20., 100., 20.]
        limits = {"catalog": .5, "currency": .5}
        for velocity, expected in (([.5, -.5, .5, -.5], "no_forward_crossing"),
                                   ([0.] * 4, "stationary")):
            result = ilr_ray(ilr(counts), coordinates(velocity), limits)
            verify_ray(result, direct_ray(counts, velocity, limits))
            self.assertEqual(result["status"], expected)
            self.assertIsNone(result["distance"])
        limits["catalog"] = .1
        result = ilr_ray(ilr(counts), [0.] * 3, limits)
        self.assertEqual(result["status"], "already_violated")
        self.assertEqual(result["distance"], 0)
        self.assertEqual(result["first_constraints"], [])

    def test_on_boundary_outward_vs_inward(self):
        counts = [100., 100., 100., 20.]
        limits = {"catalog": .5, "currency": .5}
        for velocity, expected in (([-.25, .75, -.25, -.25], "immediate_exit"),
                                   ([.25, -.75, .25, .25], "no_forward_crossing")):
            result = ilr_ray(ilr(counts), coordinates(velocity), limits)
            verify_ray(result, direct_ray(counts, velocity, limits))
            self.assertEqual(result["status"], expected)

    def test_positive_scaling_of_velocity_does_not_change_geometric_distance(self):
        counts = [100., 20., 100., 10.]
        limits = {"catalog": .5, "currency": .5}
        velocity = [-.25, .75, -.25, -.25]
        a = ilr_ray(ilr(counts), coordinates(velocity), limits)
        b = ilr_ray(ilr([1000 * x for x in counts]),
                    coordinates([.2 * x for x in velocity]), limits)
        self.assertAlmostEqual(a["distance"], b["distance"])
        for x, y in zip(a["intersection_composition"], b["intersection_composition"]):
            self.assertAlmostEqual(x, y)
        direct = direct_ray(counts, [v + 7 for v in velocity], limits)
        verify_ray(a, direct)

    def test_random_positive_paths_against_independent_bisection(self):
        rng = random.Random(481027)
        for _ in range(300):
            counts = [math.exp(rng.uniform(-4, 4)) for _ in range(4)]
            velocity = [rng.gauss(0, 1) for _ in range(4)]
            mean = math.fsum(velocity) / 4
            velocity = [v - mean for v in velocity]
            limits = {g: rng.uniform(.05, .95) for g in ("catalog", "currency")}
            a = ilr_ray(ilr(counts), coordinates(velocity), limits)
            b = direct_ray(counts, velocity, limits)
            verify_ray(a, b)

    def test_invalid_inputs_are_not_pseudocount_repaired(self):
        limits = {"catalog": .5, "currency": .5}
        with self.assertRaises(ValueError):
            direct_ray([1, 0, 1, 1], [0.] * 4, limits)
        with self.assertRaises(ValueError):
            ilr_ray([0.] * 3, [0.] * 3, {**limits, "catalog": 1})
        with self.assertRaises(ValueError):
            ilr_ray([float("nan"), 0., 0.], [0.] * 3, limits)

    def test_causal_history_repeated_windows_and_missingness(self):
        observer = DirectHistory(.2)
        a = observer.update(1, [100, 20, 100, 10], True)
        self.assertIsNone(a["increment"])
        b = observer.update(2, [100, 40, 100, 10], True)
        self.assertGreater(norm(b["increment"]), 0)
        repeated = observer.update(2, [100, 40, 100, 10], True)
        self.assertEqual(b, repeated)
        observer.update(3, [100, 90, 100, 90], False)
        restored = observer.update(3, [100, 90, 100, 90], True)
        self.assertIsNone(restored["increment"])
        self.assertIsNone(restored["smoothed_increment"])
        skipped = observer.update(5, [100, 10, 100, 10], True)
        self.assertIsNone(skipped["increment"])
        self.assertEqual(b, repeated)

    def test_policy_edit_changes_boundary_not_direction(self):
        z, v = ilr([100., 20., 100., 10.]), coordinates([-.25, .75, -.25, -.25])
        a = ilr_ray(z, v, {"catalog": .5, "currency": .5})
        b = ilr_ray(z, v, {"catalog": .2, "currency": .5})
        self.assertEqual(a["unit_direction"], b["unit_direction"])
        self.assertLess(b["distance"], a["distance"])
        self.assertAlmostEqual(b["distance"], math.sqrt(.75) * math.log(1.25))

    def test_analysis_definition_matches_implementation(self):
        design = json.loads(DESIGN.read_text())
        self.assertEqual(design["bisection_iterations"], 100)
        self.assertEqual(design["ewma_alpha"], .2)
        self.assertFalse(design["runtime_started"])

    def test_published_directional_results_replay(self):
        bundle = MODULE / "results/campaign-v0.1.1"
        destination = bundle / "directional-v0.1.0"
        summary, reports, pairs = analyze(bundle)
        self.assert_nested_close(summary, json.loads((destination / "summary.json").read_text()))
        self.assert_nested_close(reports, json.loads((destination / "reports.json").read_text()))
        self.assert_nested_close(pairs, json.loads((destination / "matched-local-states.json").read_text()))
        self.assertEqual(summary["histories"], 8)
        self.assertEqual(summary["report_batches"], 181)
        self.assertEqual(summary["sources"]["increment"]["independent_checks"], 119)
        self.assertEqual(summary["sources"]["smoothed_increment"]["independent_checks"], 119)
        self.assertEqual(summary["direction_available_and_all_policies_satisfied"], 85)
        self.assertEqual(len(summary["same_window_policy_only"]), 13)
        self.assertEqual(sum(r["current_policy_status_changed"] for r in summary["same_window_policy_only"]), 5)
        self.assertEqual(summary["matched_pairs_with_all_policies_satisfied"], 26)
        for example in summary["example_reports"]:
            expected = "away" if example["history"] == "history-01" else "toward"
            for source in ("increment", "smoothed_increment"):
                self.assertEqual(example["directions"][source]["ilr"]["groups"]["catalog"]["direction"],
                                 expected)

    def test_primary_input_provenance_is_unchanged(self):
        bundle = MODULE / "results/campaign-v0.1.1"
        data = json.loads((bundle / "directional-v0.1.0/provenance.json").read_text())
        self.assertEqual(hashlib.sha256(DESIGN.read_bytes()).hexdigest(), data["analysis_design_sha256"])
        paths = {p.relative_to(bundle).as_posix() for p in (bundle / "inputs").rglob("*") if p.is_file()}
        self.assertEqual(paths, set(data["source_files_sha256"]))
        for relative, expected in data["source_files_sha256"].items():
            self.assertEqual(hashlib.sha256((bundle / relative).read_bytes()).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()
