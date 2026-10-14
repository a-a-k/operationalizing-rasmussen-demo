from __future__ import annotations

import copy
import csv
import gzip
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe8/scripts"))
from prometheus_replay import (DEFINITION, evaluate, expression, forecast_alert,
                               forecast_horizon, gauge_values, opportunities,
                               openmetrics, read_inputs, sample_time_ms, summarize)
from warning_model import alerts, canonical_hash

ARCHIVE = ROOT / "probe8/results/prometheus-baseline-v0.1.0"


class PracticalBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.definition, cls.blocks, cls.old = read_inputs()
        cls.rows, cls.events = opportunities(cls.blocks, cls.definition)

    def test_fixed_engine_settings_and_sources(self):
        self.assertEqual(self.definition["primary_lookback_seconds"], 300)
        self.assertEqual(self.definition["sensitivity_lookbacks_seconds"], [120, 600])
        self.assertEqual(self.definition["persistence_seconds"], 0)
        self.assertEqual(self.definition["prometheus"]["version"], "3.15.0")
        self.assertEqual(len(self.definition["prometheus"]["tar_sha256"]), 64)
        self.assertEqual(len(self.blocks), 20)

    def test_cadence_excludes_baseline_and_invalid_intervals(self):
        old = {"one": {"histories": {"adaptive": {"observations": [
            {"epoch": 0, "valid": True, "window_start_ms": 0},
            {"epoch": 1, "valid": True, "window_start_ms": 300000},
            {"epoch": 2, "valid": True, "window_start_ms": 340000},
            {"epoch": 3, "valid": True, "window_start_ms": 400000},
            {"epoch": 4, "valid": False, "window_start_ms": 999999}
        ]}}}}
        result = forecast_horizon(old, 2)
        self.assertEqual(result, {"source_intervals": 2, "median_cycle_seconds": 50.0, "forecast_seconds": 100.0})

    def test_cadence_does_not_use_outcomes(self):
        before = forecast_horizon(self.old, 2)
        changed = copy.deepcopy(self.old)
        for block in changed.values():
            for history in block["histories"].values():
                for w in history["observations"]:
                    w["safe"] = not w["safe"]
                    w["checkout"] = {"p95_ms": 999999}
        self.assertEqual(before, forecast_horizon(changed, 2))

    def test_timestamp_never_precedes_availability(self):
        self.assertEqual(sample_time_ms({"primary_available_ms": 1234.01}), 1235)
        with self.assertRaises(ValueError):
            sample_time_ms({"primary_available_ms": float("nan")})

    def test_gauges_are_original_service_values_not_allocations(self):
        w = self.blocks["balanced-busy-01"]["histories"]["adaptive"]["observations"][1]
        values = gauge_values(w, self.definition)
        self.assertEqual(values["checkout_p95_ms"], w["checkout"]["p95_ms"])
        self.assertEqual(values["accounting_timely_fraction"], w["accounting"]["timely_fraction"])
        changed = copy.deepcopy(w)
        changed["allocation"] = {}
        self.assertEqual(values, gauge_values(changed, self.definition))

    def test_missing_and_invalid_gauges_not_imputed(self):
        w = {"valid": True, "checkout": {"p95_ms": None, "error_rate": float("inf")}}
        self.assertEqual(gauge_values(w, self.definition), {})
        w = self.blocks["balanced-busy-01"]["histories"]["adaptive"]["observations"][1].copy()
        w["valid"] = False
        self.assertEqual(gauge_values(w, self.definition), {})

    def test_exact_requirement_equalities_and_or_rule(self):
        values = {"checkout_p95_ms": 500.0, "checkout_error_fraction": 0.0,
                  "advertising_timely_fraction": 0.99, "accounting_timely_fraction": 0.99}
        self.assertEqual(forecast_alert(values, self.definition), (False, []))
        values["checkout_error_fraction"] = 0.01
        self.assertEqual(forecast_alert(values, self.definition), (True, ["checkout_error_fraction"]))
        values["accounting_timely_fraction"] = 0.98
        self.assertEqual(len(forecast_alert(values, self.definition)[1]), 2)

    def test_unavailable_forecast_not_silent_negative(self):
        self.assertIsNone(forecast_alert({}, self.definition)[0])
        values = {key: 1.0 for key in self.definition["requirements"]}
        values["checkout_p95_ms"] = float("nan")
        self.assertIsNone(forecast_alert(values, self.definition)[0])

    def test_original_slo_labels_match_the_four_raw_requirements(self):
        for block in self.blocks.values():
            for history in block["histories"].values():
                for w in history["observations"]:
                    if w["valid"]:
                        unsafe, _ = forecast_alert(gauge_values(w, self.definition), self.definition)
                        self.assertIsNotNone(unsafe)
                        self.assertEqual(not unsafe, w["safe"])

    def test_same_eligible_targets_and_unchanged_online_ilr_counts(self):
        self.assertEqual(len(self.rows), 756)
        self.assertEqual(len(self.events), 6)
        self.assertTrue(all(r["epoch"] <= 18 for r in self.rows))
        summary, _ = summarize(self.rows, self.events, "ilr_history", 2)
        self.assertEqual(summary["positive_decisions"], 10)
        self.assertEqual(summary["negative_decisions"], 746)
        self.assertEqual(summary["first_violations_warned"], 5)
        self.assertEqual(summary["false_warning_decisions"], 45)

    def test_native_query_has_original_history_labels_and_explicit_seconds(self):
        row = {"block_id": "balanced-busy-01", "policy": "adaptive"}
        expr = expression(row, 300, 100)
        self.assertEqual(expr, 'predict_linear(allocation_warning_requirement{block_id="balanced-busy-01",policy="adaptive"}[300s], 100)')
        self.assertNotIn("offset", expr)
        self.assertNotIn("@", expr)

    def test_openmetrics_has_availability_seconds_no_fake_scrape_samples(self):
        data = openmetrics(self.blocks, self.definition)
        actual = [line for line in data.splitlines() if line.startswith("allocation_warning_requirement{")]
        self.assertEqual(len(actual), 840 * 4)
        self.assertTrue(data.endswith("# EOF\n"))
        w = self.blocks["balanced-busy-01"]["histories"]["adaptive"]["observations"][0]
        ts = sample_time_ms(w)
        selected = [line for line in actual if 'block_id="balanced-busy-01",policy="adaptive",requirement="checkout_p95_ms"' in line]
        self.assertTrue(selected[0].endswith(f" {ts // 1000}.{ts % 1000:03d}"))

    def test_event_credit_needs_horizon_and_pre_window_timestamp(self):
        event = {"block_id": "a", "policy": "adaptive", "first_unsafe_epoch": 4, "violating_window_start_ms": 10000}
        row = {"block_id": "a", "policy": "adaptive", "epoch": 2, "future_label": 1,
               "baseline_alert": True, "sample_time_ms": 9000}
        summary, _ = summarize([row], [event], "prometheus_predict_linear", 2)
        self.assertEqual(summary["first_violations_warned"], 1)
        self.assertEqual(summary["median_lead_seconds"], 1)
        row["sample_time_ms"] = 10000
        self.assertEqual(summarize([row], [event], "prometheus_predict_linear", 2)[0]["first_violations_warned"], 0)
        row["sample_time_ms"], row["epoch"] = 9000, 1
        self.assertEqual(summarize([row], [event], "prometheus_predict_linear", 2)[0]["first_violations_warned"], 0)

    def test_unknown_target_is_not_false_warning(self):
        row = {"future_label": None, "baseline_alert": True}
        summary, _ = summarize([row], [], "prometheus_predict_linear", 2)
        self.assertEqual(summary["known_decisions"], 0)
        self.assertEqual(summary["false_warning_decisions"], 0)
        self.assertIsNone(summary["decision_precision"])

    def test_common_mask_excludes_unavailable_for_both_methods(self):
        row = self.rows[0]
        natives = [{"block_id": row["block_id"], "policy": row["policy"], "epoch": row["epoch"],
                    "sample_time_ms": row["sample_time_ms"], "lookback_seconds": lookback,
                    "response": {"status": "success", "data": {"resultType": "vector", "result": []}}}
                   for lookback in (300, 120, 600)]
        summary, decisions, _ = evaluate(natives, [row], [], self.definition)
        self.assertEqual(len(decisions), 3)
        for result in summary.values():
            self.assertEqual(result["unavailable"], 1)
            self.assertEqual(result["covered"], 0)
            for method in result["methods"].values():
                self.assertEqual(method["known_decisions"], 0)

    def test_missing_duplicate_native_query_fails(self):
        with self.assertRaises(ValueError):
            evaluate([], [self.rows[0]], [], self.definition)


class NativeReplayArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.definition, cls.blocks, cls.old = read_inputs()
        cls.rows, cls.events = opportunities(cls.blocks, cls.definition)
        cls.saved = json.loads((ARCHIVE / "summary.json").read_text())
        with gzip.open(ARCHIVE / "native-responses.jsonl.gz", "rt", encoding="utf-8") as stream:
            cls.native = [json.loads(line) for line in stream]
        cls.result = evaluate(cls.native, cls.rows, cls.events, cls.definition)

    def test_every_count_and_decision_replays_from_native_responses(self):
        summaries, decisions, events = self.result
        self.assertEqual(summaries, self.saved["lookbacks"])
        for name, generated in (("decisions.csv", decisions), ("first-events.csv", events)):
            with (ARCHIVE / name).open(newline="", encoding="utf-8") as stream:
                saved = list(csv.DictReader(stream))
            self.assertEqual(saved, [{k: "" if v is None else str(v) for k, v in r.items()} for r in generated])
        self.assertEqual(self.saved["full_original_ilr"], summarize(self.rows, self.events, "ilr_history", 2)[0])

    def test_query_expressions_and_timestamps_match_fixed_inputs(self):
        cadence = forecast_horizon(self.old, 2)
        self.assertEqual(cadence, self.saved["cadence"])
        self.assertEqual(self.saved["definition_sha256_lf"], canonical_hash(ROOT / DEFINITION))
        self.assertEqual(self.saved["execution_commit"], "e12535e117665cb85808c11d1332cd21f0ce3012")
        self.assertEqual(self.saved["run_id"], "38563585497")
        index = {(r["block_id"], r["policy"], r["epoch"]): r for r in self.rows}
        self.assertEqual(len(self.native), len(index) * 3)
        for record in self.native:
            row = index[(record["block_id"], record["policy"], record["epoch"])]
            self.assertEqual(record["expression"], expression(row, record["lookback_seconds"], cadence["forecast_seconds"]))
            self.assertEqual(record["sample_time_ms"], row["sample_time_ms"])
            for value in record["response"]["data"]["result"]:
                self.assertEqual(value["metric"]["block_id"], row["block_id"])
                self.assertEqual(value["metric"]["policy"], row["policy"])
                self.assertAlmostEqual(value["value"][0], row["sample_time_ms"] / 1000, places=5)

    def test_exact_backfill_and_native_causal_fixture_are_preserved(self):
        self.assertEqual((ARCHIVE / "inputs.openmetrics").read_text(), openmetrics(self.blocks, self.definition))
        fixtures = json.loads((ARCHIVE / "native-checks.json").read_text())
        self.assertEqual(fixtures["one_sample_unavailable"]["data"]["result"], [])
        values = {r["metric"]["variant"]: float(r["value"][1])
                  for r in fixtures["steady_trend_and_future_invariance"]["data"]["result"]}
        self.assertEqual(values, {"full": 0.6, "prefix": 0.6})

    def test_coverage_excludes_only_single_sample_baselines_for_every_lookback(self):
        _, decisions, _ = self.result
        for lookback in (300, 120, 600):
            subset = [r for r in decisions if r["lookback_seconds"] == lookback]
            self.assertEqual(sum(not r["covered"] for r in subset), 40)
            self.assertTrue(all(r["covered"] == (r["epoch"] != 0) for r in subset))
            for row in subset:
                windows = self.blocks[row["block_id"]]["histories"][row["policy"]]["observations"]
                samples = [w for w in windows if row["sample_time_ms"] - lookback * 1000 < sample_time_ms(w) <= row["sample_time_ms"]]
                self.assertEqual(row["covered"], len(samples) >= 2)

    def test_all_old_ilr_thresholds_replay_on_exact_common_mask(self):
        with (ROOT / "probe8/results/development-v0.1.0/development-thresholds.csv").open(newline="") as stream:
            original = [r for r in csv.DictReader(stream) if r["method"] == "ilr_history"]
        with (ARCHIVE / "ilr-fixed-operating-points.csv").open(newline="") as stream:
            points = list(csv.DictReader(stream))
        self.assertEqual([float(r["threshold"]) if r["threshold"] else None for r in original],
                         [float(r["threshold"]) if r["threshold"] else None for r in points])
        common = [r for r in self.result[1] if r["lookback_seconds"] == 300 and r["covered"]]
        for point in points:
            threshold = float(point["threshold"]) if point["threshold"] else None
            rows = [{**r, "ilr_alert": alerts(r["ilr_score"], threshold)} for r in common]
            summary, _ = summarize(rows, self.events, "ilr_history", 2)
            for key in ("true_warning_decisions", "false_warning_decisions", "first_violations_warned",
                        "first_violation_histories", "known_decisions", "negative_decisions"):
                self.assertEqual(int(point[key]), summary[key])
            self.assertEqual(float(point["decision_precision"]) if point["decision_precision"] else None,
                             summary["decision_precision"])


if __name__ == "__main__":
    unittest.main()
