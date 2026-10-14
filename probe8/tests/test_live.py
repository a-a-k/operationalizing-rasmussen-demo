from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe8/scripts"))
from live_runner import CAMPAIGN, Observer, campaign_matrix, guarded_module
from warning_model import FROZEN, WarningModel, canonical_hash, choose_threshold
from analyze_confirmation import analyze


class FakeModel:
    definition = {"version": "test", "methods": ["m"], "horizon_cycles": 2, "scope": "test"}
    frozen = {"thresholds": {"m": .5}, "development_execution": {"run_id": "old"}}

    def score(self, prefix, profile):
        if prefix[-1]["safe"] is not True:
            return {"eligible": False, "reason": "unsafe", "methods": {}}
        return {"eligible": True, "reason": None, "methods": {
            "m": {"score": .8, "threshold": .5, "alert": True, "neighbors": ["old"], "neighbor_pairs": 1}}}


class LiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.campaign = json.loads((ROOT / CAMPAIGN).read_text())

    def test_twenty_jobs_have_balanced_orders_and_unchanged_parent_runtime(self):
        matrix = campaign_matrix(self.campaign)
        self.assertEqual(len(matrix), 20)
        self.assertEqual(sum(r["order"][0] == "adaptive" for r in matrix), 10)
        parent = guarded_module()
        self.assertEqual(parent.RUNTIME, "probe7/runtime-v0.2.0.json")
        self.assertEqual(parent.OVERLAY, "probe7/compose-v0.1.1.yaml")

    def test_observer_does_not_modify_controller_inputs_or_policy(self):
        original = {"allocation": {"cpu": {"a": 1}}, "safe": True, "valid": True,
                    "headroom": {"checkout": .8}, "resources": {"a": {"cpu_cores": .1}}}
        expected = copy.deepcopy(original)
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name) / "adaptive" / "000"
            folder.mkdir(parents=True)
            observer = Observer(FakeModel(), "hash")
            result = observer.phase(lambda *a: copy.deepcopy(original), None, None, {"id": "busy"}, None, 30, folder, None, None)
            for key, value in expected.items():
                self.assertEqual(result[key], value)
            self.assertGreaterEqual(result["online_warning"]["scored_ms"], result["primary_available_ms"])
            self.assertTrue((folder / "online-warning.json").exists())
            self.assertEqual(len(observer.prefixes[str(folder.parent)]), 1)

    def test_warmup_never_becomes_a_forecast_baseline(self):
        observer = Observer(FakeModel(), "hash")
        with tempfile.TemporaryDirectory() as name:
            result = observer.phase(lambda *a: {"safe": True}, None, None, {"id": "busy"}, None, 120, Path(name) / "warmup", None, None)
        self.assertEqual(result, {"safe": True})
        self.assertEqual(observer.prefixes, {})

    def test_observer_failure_preserves_measurement_but_is_not_silent(self):
        class Broken(FakeModel):
            def score(self, prefix, profile):
                raise ValueError("broken")
        observer = Observer(Broken(), "hash")
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name) / "000"
            folder.mkdir()
            result = observer.phase(lambda *a: {"safe": True, "valid": True}, None, None, {"id": "busy"}, None, 30, folder, None, None)
        self.assertTrue(result["safe"])
        self.assertFalse(result["online_warning"]["prediction_valid"])
        self.assertEqual(len(observer.failures), 1)

    def test_frozen_model_matches_development_threshold_table(self):
        import csv
        model = WarningModel()
        with (ROOT / "probe8/results/development-v0.1.0/development-thresholds.csv").open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        for method in model.definition["methods"]:
            decoded = [{"threshold": float(r["threshold"]) if r["threshold"] else None,
                        "true_warning_decisions": int(r["true_warning_decisions"]),
                        "false_warning_decisions": int(r["false_warning_decisions"]),
                        "false_warning_rate": float(r["false_warning_rate"])} for r in rows if r["method"] == method]
            self.assertEqual(choose_threshold(decoded, model.definition), model.frozen["thresholds"][method])

    def test_first_violation_requires_warning_before_violating_window(self):
        row = campaign_matrix(self.campaign)[0]
        model = FakeModel()
        model_hash = canonical_hash(ROOT / FROZEN)
        observations = [{"epoch": t, "valid": True, "safe": t == 0,
                         "window_start_ms": t * 200, "window_end_ms": t * 200 + 90,
                         "checkout_window_start_ms": t * 200, "primary_available_ms": t * 200 + 100}
                        for t in range(2)]
        for i, w in enumerate(observations):
            record = model.score(observations[:i + 1], row["profile"])
            record.update(prediction_valid=True, model_sha256_lf=model_hash, epoch=i,
                          runtime_mode="observer_only", features_available_ms=w["primary_available_ms"],
                          scored_ms=w["primary_available_ms"] + 1, prediction_duration_ms=1)
            w["online_warning"] = record
        block = {**row, "design": self.campaign, "execution_commit": "commit", "run_id": "run",
                 "warning_model": {"sha256_lf": model_hash, "runtime_mode": "observer_only"},
                 "histories": {"adaptive": {"observations": observations, "stop_reason": "test"}}}
        summary, decisions, histories, events, integrity = analyze({row["block_id"]: block}, model, self.campaign, "commit", "run")
        self.assertEqual(summary["methods"]["m"]["first_violation_histories_warned"], 1)
        self.assertEqual(events[0]["lead_to_window_start_ms"], 99)
        observations[0]["online_warning"]["scored_ms"] = 201
        changed = analyze({row["block_id"]: block}, model, self.campaign, "commit", "run")[0]
        self.assertEqual(changed["methods"]["m"]["first_violation_histories_warned"], 0)


if __name__ == "__main__":
    unittest.main()
