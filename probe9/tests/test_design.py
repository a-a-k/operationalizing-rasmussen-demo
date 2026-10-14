from __future__ import annotations

import copy
import csv
import json
import math
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe7/scripts"))
sys.path.insert(0, str(ROOT / "probe8/scripts"))
sys.path.insert(0, str(ROOT / "probe9/scripts"))
from live_runner import CAMPAIGN, campaign_matrix, guarded_module, load_design
sys.path.insert(0, str(ROOT / "probe9/scripts"))
from analyze import (load_analysis, method_alert, paired_events, prom_expression,
                     paired_false_histories, sample_time_ms, summarize)
from model import initial_state, proposal, representation
from warning_model import canonical_hash

RESULTS = ROOT / "probe9/results/generalization-v0.1.0"


class MatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design = load_design()
        cls.analysis = load_analysis()
        cls.matrix = campaign_matrix(cls.design)

    def test_exactly_250_unique_jobs_and_fifty_cells(self):
        self.assertEqual(len(self.matrix), 250)
        self.assertEqual(len({r["block_id"] for r in self.matrix}), 250)
        cells = Counter((r["initial_state"], r["profile"]) for r in self.matrix)
        self.assertEqual(len(cells), 50)
        self.assertEqual(set(cells.values()), {5})

    def test_order_is_deterministic_and_globally_balanced(self):
        self.assertEqual(self.matrix, campaign_matrix(self.design))
        self.assertEqual(Counter(r["order"][0] for r in self.matrix), {"adaptive": 125, "control": 125})
        for state in self.design["initial_states"]:
            for profile in self.design["profiles"]:
                rows = [r for r in self.matrix if r["initial_state"] == state["id"] and r["profile"] == profile["id"]]
                self.assertEqual(sorted(Counter(r["order"][0] for r in rows).values()), [2, 3])

    def test_twenty_five_closed_positive_cpu_states_and_fixed_ram(self):
        totals, memories = [], []
        for spec in self.design["initial_states"]:
            state = initial_state(self.design, spec["id"])
            totals.append(math.fsum(state["cpu"].values()))
            memories.append(state["memory"])
            self.assertGreaterEqual(min(state["cpu"].values()), 0.15)
        self.assertEqual(len({round(v, 12) for v in totals}), 1)
        self.assertEqual(len({json.dumps(v, sort_keys=True) for v in memories}), 1)
        self.assertEqual(len({json.dumps(initial_state(self.design, s["id"])["cpu"], sort_keys=True)
                              for s in self.design["initial_states"]}), 25)

    def test_same_absolute_transfer_has_same_raw_distance_but_different_ilr_distance(self):
        low = initial_state(self.design, "a-p100-b-000")
        high = initial_state(self.design, "a-m100-b-000")
        low_after = proposal(low, "cpu", "accounting", "ad", 0.04)
        high_after = proposal(high, "cpu", "accounting", "ad", 0.04)
        def distances(before, after):
            a, b = representation(before, self.design), representation(after, self.design)
            raw = math.dist(a["shares"]["cpu"], b["shares"]["cpu"])
            ilr = math.dist(a["ilr"][:10], b["ilr"][:10])
            return raw, ilr
        raw_low, ilr_low = distances(low, low_after)
        raw_high, ilr_high = distances(high, high_after)
        self.assertAlmostEqual(raw_low, raw_high)
        self.assertNotAlmostEqual(ilr_low, ilr_high)
        self.assertGreater(ilr_low, ilr_high)

    def test_parent_runtime_and_frozen_observer_are_reused(self):
        parent = guarded_module()
        self.assertEqual(parent.RUNTIME, "probe7/runtime-v0.2.0.json")
        self.assertEqual(parent.OVERLAY, "probe7/compose-v0.1.1.yaml")
        self.assertEqual(self.analysis["frozen_model_sha256_lf"],
                         canonical_hash(ROOT / self.analysis["frozen_model"]))
        self.assertEqual(self.analysis["design_sha256_lf"], canonical_hash(ROOT / CAMPAIGN))

    def test_three_methods_and_two_primary_comparisons_are_explicit(self):
        self.assertEqual(set(self.analysis["methods"]),
                         {"ilr_history", "share_history", "prometheus_predict_linear"})
        self.assertEqual(self.analysis["primary_comparisons"],
                         ["ilr_history vs prometheus_predict_linear",
                          "share_history vs prometheus_predict_linear"])
        self.assertEqual(self.analysis["diagnostic_comparison"], "ilr_history vs share_history")
        self.assertEqual(self.analysis["operating_points"]["resource_primary_thresholds"],
                         {"ilr_history": 0.2, "share_history": 0.2})
        self.assertEqual(self.analysis["operating_points"]["resource_secondary_thresholds"],
                         [None, 0.6, 0.4, 0.2, 0.0])

    def test_prometheus_inputs_and_horizon_are_fixed(self):
        self.assertEqual(self.analysis["primary_lookback_seconds"], 300)
        self.assertEqual(self.analysis["sensitivity_lookbacks_seconds"], [120, 600])
        self.assertEqual(self.analysis["forecast_seconds"], 86.962)
        self.assertEqual(self.analysis["prometheus"]["version"], "3.15.0")
        self.assertEqual(len(self.analysis["prometheus"]["tar_sha256"]), 64)


class AnalysisAccountingTests(unittest.TestCase):
    def test_query_selects_one_history_and_uses_explicit_time_settings(self):
        row = {"block_id": "a-p100-b-000-busy-01", "policy": "adaptive"}
        self.assertEqual(
            prom_expression(row, 300, 86.962),
            'predict_linear(allocation_warning_requirement{block_id="a-p100-b-000-busy-01",policy="adaptive"}[300s], 86.962)')

    def test_availability_timestamp_rounds_up(self):
        self.assertEqual(sample_time_ms({"primary_available_ms": 1234.01}), 1235)
        with self.assertRaises(ValueError):
            sample_time_ms({"primary_available_ms": float("nan")})

    def test_summary_distinguishes_false_decisions_and_histories(self):
        rows = [
            {"block_id": "a", "policy": "adaptive", "epoch": 1, "future_label": 0,
             "ilr_score": 1, "resource_scored_ms": 1},
            {"block_id": "a", "policy": "adaptive", "epoch": 2, "future_label": 0,
             "ilr_score": 1, "resource_scored_ms": 2},
            {"block_id": "b", "policy": "adaptive", "epoch": 1, "future_label": 0,
             "ilr_score": 0, "resource_scored_ms": 1}
        ]
        summary, _ = summarize(rows, [], "ilr_history", 2, 0.2)
        self.assertEqual(summary["false_warning_decisions"], 2)
        self.assertEqual(summary["histories_with_false_warning"], 1)

    def test_first_event_credit_is_prospective_and_within_horizon(self):
        event = {"block_id": "a", "policy": "adaptive", "first_unsafe_epoch": 4,
                 "violating_window_start_ms": 10000}
        row = {"block_id": "a", "policy": "adaptive", "epoch": 2, "future_label": 1,
               "share_score": 1, "resource_scored_ms": 9000}
        summary, events = summarize([row], [event], "share_history", 2, 0.2)
        self.assertEqual(summary["first_violations_warned"], 1)
        self.assertEqual(events[0]["lead_seconds"], 1)
        row["resource_scored_ms"] = 10000
        self.assertEqual(summarize([row], [event], "share_history", 2, 0.2)[0]["first_violations_warned"], 0)

    def test_unknown_future_is_not_a_false_signal(self):
        row = {"block_id": "a", "policy": "adaptive", "epoch": 1,
               "future_label": None, "share_score": 1, "resource_scored_ms": 1}
        summary, _ = summarize([row], [], "share_history", 2, 0.2)
        self.assertEqual(summary["known_decisions"], 0)
        self.assertEqual(summary["false_warning_decisions"], 0)

    def test_paired_event_table_keeps_direction(self):
        rows = [
            {"block_id": "a", "policy": "adaptive", "method": "left", "warned": True},
            {"block_id": "a", "policy": "adaptive", "method": "right", "warned": False},
            {"block_id": "b", "policy": "adaptive", "method": "left", "warned": True},
            {"block_id": "b", "policy": "adaptive", "method": "right", "warned": True}
        ]
        self.assertEqual(paired_events(rows, "left", "right"),
                         {"events_compared": 2, "both_warned": 1, "left_only": 1,
                          "right_only": 0, "neither": 0})

    def test_false_signal_pairing_uses_histories_not_dependent_windows(self):
        rows = [
            {"block_id": "a", "policy": "adaptive", "future_label": 0,
             "ilr_score": 1, "prometheus_alert": False},
            {"block_id": "a", "policy": "adaptive", "future_label": 0,
             "ilr_score": 1, "prometheus_alert": False},
            {"block_id": "b", "policy": "control", "future_label": 0,
             "ilr_score": 0, "prometheus_alert": True}
        ]
        self.assertEqual(
            paired_false_histories(rows, "ilr_history", "prometheus_predict_linear",
                                   {"ilr_history": 0.2, "prometheus_predict_linear": None}),
            {"histories_compared": 2, "both_had_false_signal": 0, "left_only": 1,
             "right_only": 1, "neither": 0})


class ArchivedResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = json.loads((RESULTS / "summary.json").read_text())

    def test_complete_fixed_matrix_and_prediction_integrity(self):
        self.assertEqual(self.summary["planned_pairs"], 250)
        self.assertEqual(self.summary["received_pairs"], 250)
        self.assertEqual(self.summary["missing_pairs"], [])
        self.assertEqual(self.summary["histories"], 500)
        self.assertEqual(self.summary["baseline_safe_histories"], 483)
        self.assertEqual(self.summary["complete_histories"], 483)
        self.assertEqual(self.summary["first_violation_histories"], 104)
        self.assertEqual(self.summary["prediction_integrity_failures"], 0)
        self.assertEqual(len(list((RESULTS / "blocks").glob("*.json.gz"))), 250)

    def test_primary_comparisons_are_both_against_prometheus(self):
        methods = self.summary["lookbacks"]["300"]["methods"]
        self.assertEqual(methods["ilr_history"]["first_violations_warned"], 44)
        self.assertEqual(methods["share_history"]["first_violations_warned"], 41)
        self.assertEqual(methods["prometheus_predict_linear"]["first_violations_warned"], 0)
        pairs = self.summary["primary_paired_events"]
        self.assertEqual(pairs["ilr_history__vs__prometheus_predict_linear"]
                         ["first_violation_events"],
                         {"events_compared": 104, "both_warned": 0, "left_only": 44,
                          "right_only": 0, "neither": 60})
        self.assertEqual(pairs["share_history__vs__prometheus_predict_linear"]
                         ["first_violation_events"],
                         {"events_compared": 104, "both_warned": 0, "left_only": 41,
                          "right_only": 0, "neither": 63})

    def test_history_status_preserves_baseline_failures(self):
        with (RESULTS / "history-status.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(Counter((r["policy"], r["baseline_safe"], r["complete"])
                                 for r in rows),
                         Counter({("adaptive", "True", "True"): 244,
                                  ("control", "True", "True"): 239,
                                  ("adaptive", "False", "False"): 6,
                                  ("control", "False", "False"): 11}))

    def test_adaptive_control_violation_contrast(self):
        with (RESULTS / "history-status.csv").open(encoding="utf-8", newline="") as stream:
            histories = list(csv.DictReader(stream))
        with (RESULTS / "first-events.csv").open(encoding="utf-8", newline="") as stream:
            events = {(r["block_id"], r["policy"]) for r in csv.DictReader(stream)}
        by_block = {}
        for row in histories:
            by_block.setdefault(row["block_id"], {})[row["policy"]] = row
        contrast = Counter()
        for block_id, pair in by_block.items():
            if not all(pair[p]["baseline_safe"] == "True" and pair[p]["complete"] == "True"
                       for p in ("adaptive", "control")):
                contrast["not_jointly_eligible"] += 1
                continue
            adaptive = (block_id, "adaptive") in events
            control = (block_id, "control") in events
            contrast["both" if adaptive and control else
                     "adaptive_only" if adaptive else
                     "control_only" if control else "neither"] += 1
        self.assertEqual(contrast, Counter({"neither": 141, "adaptive_only": 89,
                                            "not_jointly_eligible": 13,
                                            "control_only": 4, "both": 3}))

    def test_resource_history_signals_occur_only_under_adaptation(self):
        with (RESULTS / "decisions.csv").open(encoding="utf-8", newline="") as stream:
            rows = [r for r in csv.DictReader(stream)
                    if r["lookback_seconds"] == "300" and r["prometheus_covered"] == "True"]
        self.assertEqual({r["policy"] for r in rows if r["ilr_frozen_alert"] == "True"},
                         {"adaptive"})
        self.assertEqual({r["policy"] for r in rows if r["share_frozen_alert"] == "True"},
                         {"adaptive"})
        self.assertEqual(sum(r["prometheus_alert"] == "True" and r["policy"] == "control"
                             for r in rows), 4)


if __name__ == "__main__":
    unittest.main()
