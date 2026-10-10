from __future__ import annotations

import copy
import itertools
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe4/scripts"))
from scenarios import DESIGN, OVERLAY, RUNTIME, VERSION, arm, compose_prefix, engine, features, load, matrix, measurement_engine, sha256_file, validate, verify, write_json
from compare import SIGNS, analyze, collect, compare, local_or_table, save, threshold_table


def scored(unsafe, **values):
    scores = {name: 0.0 for name in SIGNS}
    scores.update(values)
    return {"unsafe": unsafe, "scores": scores}


class DesignTests(unittest.TestCase):
    def setUp(self):
        self.design, self.runtime = load(ROOT / DESIGN), load(ROOT / RUNTIME)

    def test_fixed_inputs_verify(self):
        report = verify()
        self.assertEqual((report["blocks"], report["point_trials"]), (12, 72))

    def test_all_points_repeated_and_order_deterministic(self):
        rows = matrix(self.design)
        self.assertEqual(rows, matrix(self.design))
        for rate in self.design["rates"]:
            for panel in self.design["panels"]:
                group = [r for r in rows if r["rate"] == rate and r["panel"] == panel]
                self.assertEqual(len(group), 3)
                for row in group:
                    self.assertEqual(set(row["order"]), set(self.design["panels"][panel]))
        self.assertGreater(len({tuple(r["order"]) for r in rows}), 2)

    def test_generator_capacity_is_worst_case_not_baseline_selected(self):
        self.assertEqual(64 * 2 * self.design["http_timeout_seconds"] * 1.25, 800)
        self.runtime["workload"]["max_vus"] = 320
        with self.assertRaises(ValueError):
            validate(self.design, self.runtime)

    def test_matched_sums_minima_and_balance_limits(self):
        j, s = self.design["panels"]["joint"], self.design["panels"]["selective"]
        a = features(self.design, j["joint_014"])
        for name in ["checkout_skew_007", "payment_skew_007", "shipping_skew_007"]:
            b = features(self.design, s[name])
            self.assertAlmostEqual(a["group_sum"], b["group_sum"])
            self.assertAlmostEqual(a["recipient_quota"], b["recipient_quota"])
            self.assertNotAlmostEqual(a["R_group"], b["R_group"])
        skew = [features(self.design, q) for name, q in s.items() if "skew" in name]
        self.assertEqual(len({round(x["R_group"], 12) for x in skew}), 1)
        for q in s.values():
            self.assertEqual(min(q[k] for k in self.design["group_g"]), 0.07)
        self.assertEqual(min(j["joint_007"][k] for k in self.design["group_g"]), 0.07)

    def test_no_magic_success_rule_or_rate_pool(self):
        self.design["analysis"]["binary_success_criterion"] = "majority"
        with self.assertRaises(ValueError):
            validate(self.design, self.runtime)
        self.design["analysis"]["binary_success_criterion"] = None
        self.design["analysis"]["pool_rates"] = True
        with self.assertRaises(ValueError):
            validate(self.design, self.runtime)

    def test_overlay_only_affects_new_measurement_context(self):
        original = (engine.VERSION, engine.DESIGN, engine.RUNTIME, engine.compose_prefix)
        with measurement_engine() as runner:
            self.assertEqual(runner.VERSION, VERSION)
            self.assertEqual(runner.compose_prefix(ROOT, ROOT, "x")[-2:], ["-f", str(ROOT / OVERLAY)])
        self.assertEqual((engine.VERSION, engine.DESIGN, engine.RUNTIME, engine.compose_prefix), original)


class ComparisonTests(unittest.TestCase):
    def test_perfect_reverse_and_tied_thresholds(self):
        rows = [scored(False, R_group=0), scored(True, R_group=1)]
        self.assertEqual([(p["tp"], p["fp"]) for p in threshold_table(rows, "R_group")], [(0, 0), (1, 0), (1, 1)])
        rows.reverse()
        self.assertEqual(compare(rows)["fp_budget_envelopes"]["R_group"][0]["tp"], 1)
        tied = [scored(False, R_group=1), scored(True, R_group=1)]
        self.assertEqual([(p["tp"], p["fp"]) for p in threshold_table(tied, "R_group")], [(0, 0), (1, 1)])
        self.assertEqual(compare(tied)["fp_budget_envelopes"]["R_group"][0]["tp"], 0)

    def test_low_quota_is_fixed_risk_direction(self):
        rows = [scored(False, checkout_quota=0.3), scored(True, checkout_quota=0.1)]
        rule = threshold_table(rows, "checkout_quota")[1]
        self.assertEqual((rule["tp"], rule["fp"]), (1, 0))
        self.assertEqual(rule["rule"], {"operator": "<=", "threshold": 0.1})

    def test_local_or_includes_all_single_channel_rules(self):
        rows = [scored(a, checkout_quota=c, payment_quota=p, shipping_quota=s)
                for a, c, p, s in [(False, .3, .1, .2), (True, .1, .3, .2), (True, .2, .2, .1)]]
        c = compare(rows)
        for service in ["checkout", "payment", "shipping"]:
            for oracle, single in zip(c["fp_budget_envelopes"]["local_or"], c["fp_budget_envelopes"][service + "_quota"]):
                self.assertGreaterEqual(oracle["tp"], single["tp"])
        self.assertTrue(any(all(v is None for v in p["rule"]["thresholds"].values()) for p in local_or_table(rows)))

    def test_balance_can_lose_and_curves_can_cross(self):
        rows = [scored(False, R_group=2, checkout_quota=.3), scored(True, R_group=1, checkout_quota=.1)]
        c = compare(rows)
        self.assertEqual(c["balance_comparison"]["checkout_quota"]["worse_at_fp_budgets"], [0])
        self.assertEqual(c["fp_budget_envelopes"]["R_group"][0]["tp"], 0)

    def test_empty_and_single_class_have_no_discrimination_claim(self):
        for rows in [[], [scored(False)], [scored(True)]]:
            c = compare(rows)
            self.assertFalse(c["informative_two_class_comparison"])
            self.assertEqual(c["n"], len(rows))

    def test_confusion_counts_conserve_points(self):
        rows = [scored(bool(i % 2), R_group=i // 2, checkout_quota=.1 * i,
                       payment_quota=.4 - .05 * i, shipping_quota=.2) for i in range(6)]
        for table in compare(rows)["all_thresholds"].values():
            for p in table:
                self.assertEqual(sum(p[k] for k in ["tp", "fp", "fn", "tn"]), 6)
                self.assertEqual(p["tp"] + p["fn"], 3)


class EvidenceTests(unittest.TestCase):
    def block(self):
        design = load(ROOT / DESIGN)
        row = matrix(design)[0]
        points = {}
        for name, q in design["panels"][row["panel"]].items():
            points[name] = {"study_version": VERSION, "point_id": name, "block_id": row["block_id"],
                            "test_quotas": q, "rate": row["rate"], "valid": True,
                            "primary_recoverable": True, "reason_codes": [],
                            "test": {"safe": True, "p95_ms": 100, "error_rate": 0},
                            "post_intervention_failures": {}, "diagnostics": {"failure_events": []}}
        return {**row, "study_version": VERSION, "repository_commit": "fixture", "points": points,
                "design_sha256": sha256_file(ROOT / DESIGN), "runtime_sha256": sha256_file(ROOT / RUNTIME),
                "overlay_sha256": sha256_file(ROOT / OVERLAY)}

    def test_invalid_outcome_and_oom_are_retained_without_label_override(self):
        b = self.block()
        p = b["points"]["joint_010"]
        p.update(valid=False, reason_codes=["test_started_below_99_percent"])
        p["test"].update(safe=False, p95_ms=1000)
        b["points"]["joint_019"]["post_intervention_failures"] = {"checkout": {"oom_snapshot": True}}
        report, rows = analyze(ROOT, {b["block_id"]: b}, "fixture")
        self.assertEqual(report["rates"]["40"]["valid"]["unsafe"], 0)
        self.assertEqual(report["rates"]["40"]["all_recoverable"]["unsafe"], 1)
        self.assertEqual(report["valid_points"], 5)
        self.assertEqual(len(rows), 72)
        self.assertFalse(next(r for r in rows if r["point_id"] == "joint_019" and r["recorded"])["unsafe"])

    def test_missing_latency_is_measured_unsafe(self):
        b = self.block()
        b["points"]["joint_010"]["test"].update(safe=False, p95_ms=None)
        report, _ = analyze(ROOT, {b["block_id"]: b}, "fixture")
        self.assertEqual(report["rates"]["40"]["valid"]["unsafe"], 1)

    def test_bad_commit_hash_order_and_slo_label_rejected(self):
        for key in ["repository_commit", "design_sha256", "order", "label"]:
            b = self.block()
            if key == "order":
                b[key] = list(reversed(b[key]))
            elif key == "label":
                b["points"]["joint_010"]["test"]["safe"] = False
            else:
                b[key] = "incorrect"
            with self.assertRaises(ValueError):
                analyze(ROOT, {b["block_id"]: b}, "fixture")

    def test_reporting_and_duplicates(self):
        b = self.block()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "input/one/block-result.json", b)
            report = save(ROOT, root / "input", root / "output", "fixture")
            self.assertEqual(report["recorded_points"], 6)
            self.assertEqual(report["status"], "incomplete")
            for name in ["comparison.json", "point-level.csv", "thresholds.csv", "RESULTS.md"]:
                self.assertTrue((root / "output" / name).exists())
            write_json(root / "input/two/block-result.json", b)
            with self.assertRaises(ValueError):
                save(ROOT, root / "input", root / "duplicate-output", "fixture")


if __name__ == "__main__":
    unittest.main()
