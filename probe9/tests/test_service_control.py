import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe9/scripts"))
spec = importlib.util.spec_from_file_location("service_control", ROOT / "probe9/scripts/analyze_service_control.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ServiceControlTests(unittest.TestCase):
    def test_spec_pins_prospective_frozen_service_control(self):
        definition = module.load_spec()
        model = module.WarningModel()
        self.assertEqual(definition["status"].split(";")[0],
                         "Retrospective aggregation of prospectively recorded frozen predictions")
        self.assertEqual(model.frozen["thresholds"]["service_indicators"], 0.4)
        self.assertIn("service_indicators", model.frozen["definition"]["methods"])

    def test_generic_summary_uses_service_score(self):
        rows = [
            {"block_id": "a", "policy": "adaptive", "epoch": 0, "future_label": 1,
             "resource_scored_ms": 10, "service_score": 0.4},
            {"block_id": "b", "policy": "adaptive", "epoch": 0, "future_label": 0,
             "resource_scored_ms": 10, "service_score": 0.2},
        ]
        events = [{"block_id": "a", "policy": "adaptive", "first_unsafe_epoch": 1,
                   "violating_window_start_ms": 1000}]
        result, _ = module.summarize(rows, events, "service_indicators", 2, 0.4)
        self.assertEqual(result["true_warning_decisions"], 1)
        self.assertEqual(result["false_warning_decisions"], 0)
        self.assertEqual(result["first_violations_warned"], 1)

    def test_archived_matched_result(self):
        result = json.loads((ROOT / "probe9/results/service-control-v0.1.0/summary.json").read_text())
        self.assertEqual(result["source_pairs"], 250)
        self.assertEqual(result["first_violation_histories"], 104)
        self.assertEqual(result["prediction_integrity_failures"], 0)
        self.assertEqual(result["methods"]["service_indicators"]["first_violations_warned"], 6)
        self.assertEqual(result["methods"]["ilr_history"]["first_violations_warned"], 44)
        self.assertEqual(result["methods"]["share_history"]["first_violations_warned"], 41)
        self.assertEqual(result["paired_comparisons"]["ilr_history__vs__service_indicators"]
                         ["first_violation_events"]["left_only"], 38)


if __name__ == "__main__":
    unittest.main()
