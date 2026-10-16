from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from monitor_core import (DESIGN, METHODS, Observer, allocation, close, coordinates,
                          feature, fit_background, helmert, integrate, load, matrix, settling, timing)
from monitor_analyze import score_history
from monitor_run import first_origin


class MonitorChecks(unittest.TestCase):
    def test_generator_origin_is_read_from_either_log_stream(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            out, err = folder / "stdout.log", folder / "stderr.log"
            out.write_text("", encoding="utf-8")
            err.write_text('ORIGIN {"stream":"checkout","origin":1000000}\n', encoding="utf-8")
            self.assertEqual(first_origin([out, err], Mock()), 1000.)

    def test_matrix_partition_and_balanced_test_order(self):
        background, test = matrix("background"), matrix("test")
        self.assertEqual(len(background), 20)
        self.assertEqual(sum(r["role"] == "fit" for r in background), 8)
        self.assertEqual(sum(r["role"] == "calibration" for r in background), 12)
        self.assertEqual(len(test), 20)
        self.assertEqual(sum(r["order"][0] == "drift" for r in test), 10)

    def test_every_allocation_preserves_budget_and_exact_microseconds(self):
        cfg = load(DESIGN)
        for context in cfg["initial_states"]:
            for step in range(13):
                state = allocation(context, step)
                self.assertAlmostEqual(sum(state["cpu"].values()), 3.4)
                for q in state["cpu"].values():
                    self.assertAlmostEqual(q * 100000, round(q * 100000))

    def test_helmert(self):
        h = helmert(11)
        np.testing.assert_allclose(h @ h.T, np.eye(10), atol=1e-12)
        np.testing.assert_allclose(h.sum(axis=1), 0, atol=1e-12)

    def test_both_representations_preserve_complete_composition(self):
        x = close(np.arange(1, 12))
        h = helmert(11)
        np.testing.assert_allclose(coordinates(x, "raw_composition") @ h + 1/11, x)
        np.testing.assert_allclose(close(np.exp(coordinates(x, "ilr_composition") @ h)), x)

    def test_common_cpu_scale_does_not_change_relative_state(self):
        x = np.arange(1, 12)
        for method in METHODS:
            np.testing.assert_allclose(coordinates(x, method), coordinates(7*x, method), atol=1e-12)

    def test_feature_is_relative_to_fixed_reference(self):
        x, reference = np.arange(1, 12), np.arange(3, 14)
        for method in METHODS:
            np.testing.assert_allclose(feature(x, reference, method), coordinates(x, method)-coordinates(reference, method))

    def frames(self):
        return [{"wall_seconds": t, "containers": {"a": {"identity": [1], "delta": {"cpu_seconds": 4.}}}} for t in (0, 2, 4, 6)]

    def test_native_counter_window_boundary_integration(self):
        actual = integrate(self.frames(), ["a"], .5, 5.5)
        self.assertTrue(actual["valid"])
        self.assertAlmostEqual(actual["cpu"][0], 2.)
        self.assertAlmostEqual(actual["coverage"][0], 1.)

    def test_counter_identity_break_is_not_silently_filled(self):
        frames = self.frames()
        frames[1]["containers"]["a"]["identity"] = [2]
        actual = integrate(frames, ["a"], 0, 6)
        self.assertFalse(actual["valid"])

    def test_zero_cpu_is_not_given_a_pseudocount(self):
        frames = self.frames()
        for row in frames:
            row["containers"]["a"]["delta"]["cpu_seconds"] = 0
        self.assertFalse(integrate(frames, ["a"], 0, 6)["valid"])
        with self.assertRaises(ValueError):
            close([1., 0.])

    def test_settling_gate_is_scale_and_ratio_aware(self):
        cfg = load(DESIGN)
        a = {"valid": True, "cpu": np.arange(1, 12).tolist()}
        self.assertTrue(settling(a, a, cfg)["passed"])
        b = {"valid": True, "cpu": (np.arange(1, 12)*2).tolist()}
        self.assertFalse(settling(a, b, cfg)["passed"])

    def test_timing_has_continuous_load_and_declared_guards(self):
        cfg = load(DESIGN)
        slots = timing(cfg)
        self.assertEqual(len(slots), 16)
        self.assertEqual(slots[0]["slot_start"], 690)
        self.assertTrue(all(w["measurement_end"] - w["measurement_start"] == 30 for w in slots))
        self.assertTrue(all(a["measurement_end"] == b["slot_start"] for a, b in zip(slots, slots[1:])))

    def frozen(self):
        return {"lambda": .2, "methods": {m: {"mean": np.zeros(10).tolist(), "covariance": np.eye(10).tolist(), "threshold": 1.} for m in METHODS}}

    def test_first_mewma_statistic_equals_mahalanobis(self):
        baseline = np.arange(1, 12)
        cpu = baseline.copy().astype(float)
        cpu[0] *= .7
        result = Observer(self.frozen(), baseline).update(cpu)
        for method in METHODS:
            y = feature(cpu, baseline, method)
            self.assertAlmostEqual(result[method]["score"], y @ y)

    def test_online_prefix_has_no_future_dependency(self):
        baseline = np.arange(1, 12)
        a, b = Observer(self.frozen(), baseline), Observer(self.frozen(), baseline)
        prefix = [baseline * np.linspace(1, 1 + .02*t, 11) for t in range(5)]
        self.assertEqual([a.update(v) for v in prefix], [b.update(v) for v in prefix])
        a.update(np.arange(2, 13))
        self.assertEqual(b.t, 5)

    def test_exact_finite_covariance_matches_direct_ewma_weights(self):
        baseline = np.arange(1, 12)
        frozen = self.frozen()
        observer = Observer(frozen, baseline)
        inputs = [baseline * np.linspace(1, 1 + .03*t, 11) for t in range(1, 8)]
        history = {m: [] for m in METHODS}
        for t, cpu in enumerate(inputs, start=1):
            output = observer.update(cpu)
            weights = np.array([.2 * .8 ** j for j in range(t-1, -1, -1)])
            for method in METHODS:
                history[method].append(feature(cpu, baseline, method))
                state = weights @ np.array(history[method])
                self.assertAlmostEqual(output[method]["score"], state @ state / (weights @ weights))

    def background_jobs(self):
        rng = np.random.default_rng(19)
        jobs = []
        for row in matrix("background"):
            reference = np.arange(1, 12, dtype=float) / 30
            observations = [{"cpu": (reference * np.exp(rng.normal(0, .01, 11))).tolist()} for _ in range(16)]
            jobs.append({**row, "histories": {"background": {"qualified": True,
                          "reference": {"cpu": reference.tolist()}, "observations": observations}}})
        return jobs

    def test_fitting_and_thresholds_never_read_test_jobs(self):
        jobs = self.background_jobs()
        original = fit_background(jobs)
        with_test = fit_background(jobs + [{"role": "test", "histories": None}])
        self.assertEqual(original, with_test)

    def test_frozen_calibration_and_online_replay_end_to_end(self):
        jobs = self.background_jobs()
        frozen = fit_background(jobs)
        self.assertEqual(len(frozen["fit_ids"]), 8)
        self.assertEqual(len(frozen["calibration_ids"]), 12)
        for method in METHODS:
            self.assertEqual(frozen["methods"][method]["threshold"], max(frozen["methods"][method]["calibration_maxima"]))
        history = copy.deepcopy(jobs[0]["histories"]["background"])
        observer = Observer(frozen, history["reference"]["cpu"])
        for epoch, row in enumerate(history["observations"], start=1):
            row.update(epoch=epoch, online=observer.update(row["cpu"]))
        scores = score_history(history, frozen, "control")
        self.assertEqual(set(scores), set(METHODS))

    def test_premature_signal_is_not_detection(self):
        frozen = self.frozen()
        for method in METHODS:
            frozen["methods"][method]["threshold"] = 0.
        reference = np.arange(1, 12, dtype=float)
        observer = Observer(frozen, reference)
        cpu = reference * np.linspace(1., 1.1, 11)
        history = {"reference": {"cpu": reference.tolist()}, "observations": []}
        for epoch in range(1, 17):
            history["observations"].append({"epoch": epoch, "cpu": cpu.tolist(), "online": observer.update(cpu)})
        result = score_history(history, frozen, "drift")
        for method in METHODS:
            self.assertTrue(result[method]["premature"])
            self.assertFalse(result[method]["detected"])


if __name__ == "__main__":
    unittest.main()
