from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe7/scripts"))
from analyze_accumulated import (DEFINITION, analyze, analyze_histories, bootstrap_median,
                                 delta, inverse, load_inputs, margins, norm, save, witnesses)
from accumulation_plot import figure, witness_figure
from model import initial_state, representation


class AccumulatedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blocks, cls.design, cls.definition = load_inputs(ROOT)
        cls.result = analyze(ROOT)
        (cls.summary, cls.rows, cls.trajectories, cls.paired, cls.endpoints,
         cls.prefixes, cls.real, cls.checks, _, _) = cls.result

    def test_preserves_all_received_histories_and_windows(self):
        self.assertEqual(self.summary["received_pairs"], 24)
        self.assertEqual(self.summary["histories"], 48)
        self.assertEqual(self.summary["windows"], 988)
        self.assertEqual(self.summary["complete_paired_endpoints"], 23)
        self.assertEqual(self.summary["missing_pairs"], [])
        self.assertEqual(self.summary["ram_moving_histories"], 0)

    def test_hash_check_rejects_modified_source(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            config = root / DEFINITION
            config.parent.mkdir(parents=True)
            (root / "input.json").write_text("altered", encoding="utf-8")
            config.write_text(json.dumps({"source_sha256_lf": {"input.json": hashlib.sha256(b"original").hexdigest()}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Source hash differs"):
                load_inputs(root)

    def test_inverse_recovers_each_resource_separately(self):
        for name in ("balanced", "interactive", "ledger"):
            state = representation(initial_state(self.design, name), self.design)
            for offset, resource in ((0, "cpu"), (10, "memory")):
                restored = inverse(state["ilr"][offset:offset + 10])
                self.assertLess(norm(delta(restored, state["shares"][resource])), 1e-12)
        self.assertEqual({k for k in self.rows[0] if k.startswith("relative_delta_")},
                         {f"relative_delta_{i}" for i in range(1, 21)})

    def test_geometry_checks_and_accumulation_telescope(self):
        self.assertTrue(all(v < 1e-12 for v in self.summary["geometry_verification"].values()))
        for row in self.rows:
            full = [row[f"relative_delta_{i}"] for i in range(1, 21)]
            self.assertAlmostEqual(norm(full), row["relative_net_norm"])
            self.assertLessEqual(row["local_projected_net_norm"], row["relative_net_norm"] + 1e-10)
            self.assertGreaterEqual(row["command_vertex_path_after_rollback"] + 1e-10, row["relative_net_norm"])

    def test_controls_and_rollback_can_have_zero_net_change(self):
        controls = [r for r in self.rows if r["policy"] == "control"]
        self.assertTrue(all(r["relative_net_norm"] == 0 and r["hidden_energy_fraction"] is None for r in controls))
        restored = [r for r in self.rows if r["policy"] == "adaptive" and r["epoch"] > 0
                    and r["relative_net_norm"] == 0 and r["observed_vertex_path_length"] > 0]
        self.assertGreater(len(restored), 0)

    def test_terminal_rollback_receives_no_imputed_slo(self):
        unknown = [r for r in self.trajectories if not r["last_commanded_state_has_matching_slo_measurement"]]
        self.assertEqual(len(unknown), 2)
        self.assertTrue(all(r["policy"] == "adaptive" and r["last_observed_safe"] is False for r in unknown))
        stopped = [r for r in self.trajectories if r["last_epoch"] == 0]
        self.assertEqual([(r["block_id"], r["policy"]) for r in stopped], [("ledger-busy-01", "control")])

    def test_labels_and_physical_margins_are_not_replaced_by_norm(self):
        for row in self.rows:
            w = next(w for w in self.blocks[row["block_id"]]["histories"][row["policy"]]["observations"] if w["epoch"] == row["epoch"])
            self.assertEqual(row["safe"], w["safe"])
            self.assertEqual(margins(w)["checkout_latency_margin_ms"], 500 - row["checkout_p95_ms"])
            self.assertAlmostEqual(row["accounting_timely_margin_pp"], 100 * (row["accounting_timely_fraction"] - .99))

    def test_fixed_endpoint_effects_and_pair_bootstrap(self):
        results = self.summary["fixed_endpoint_contrasts"]
        self.assertAlmostEqual(results["advertising_goodput"]["median"], 2105.35)
        self.assertEqual(results["advertising_goodput"]["positive_pairs"], 23)
        self.assertEqual(results["checkout_latency_margin_ms"]["negative_pairs"], 21)
        self.assertAlmostEqual(results["checkout_latency_margin_ms"]["median"], -45.83668585)
        values = [r["advertising_goodput_adjusted_change"] for r in self.paired if r["epoch"] == 20 and r["baseline_safe_pair"]]
        self.assertEqual(bootstrap_median(values, self.definition), results["advertising_goodput"]["pair_bootstrap_median_95"])
        self.assertIsNone(bootstrap_median([1], self.definition))

    def test_entire_prefix_not_just_final_coordinate_matches(self):
        self.assertEqual(len(self.prefixes), 2)
        self.assertEqual(len(self.endpoints), 5)
        self.assertEqual({r["unsafe_block"] for r in self.prefixes}, {"interactive-busy-01"})
        for row in self.prefixes:
            unsafe = self.blocks[row["unsafe_block"]]["histories"]["adaptive"]["observations"]
            safe = self.blocks[row["safe_block"]]["histories"]["adaptive"]["observations"]
            for epoch in range(row["unsafe_epoch"] + 1):
                self.assertEqual(unsafe[epoch]["representation"]["local"], safe[epoch]["representation"]["local"])
            self.assertEqual(row["unsafe_epoch"], 6)
            self.assertGreater(row["full_relative_distance"], .19)

    def test_changing_earlier_selected_trace_disqualifies_prefix(self):
        ids = ("interactive-busy-01", "interactive-busy-02")
        sample = copy.deepcopy({bid: self.blocks[bid] for bid in ids})
        sample[ids[1]]["histories"]["adaptive"]["observations"][2]["representation"]["local"][0] += .001
        endpoints, prefixes = witnesses(sample, self.design, self.definition)
        self.assertTrue(any(r["unsafe_epoch"] == r["safe_epoch"] == 6 for r in endpoints))
        self.assertEqual(prefixes, [])

    def test_actual_equal_absolute_transfers_have_different_relative_vectors(self):
        self.assertEqual(len(self.real), 3)
        self.assertEqual(len({r["raw_share_displacement_norm"] for r in self.real}), 1)
        self.assertEqual(len({r["relative_displacement_norm"] for r in self.real}), 3)
        self.assertTrue(all(r["observed_safe"] is True for r in self.real))
        for row in self.real:
            self.assertAlmostEqual(row["accounting_cpu_before"] - row["accounting_cpu_after"], .04)
            self.assertAlmostEqual(row["ad_cpu_after"] - row["ad_cpu_before"], .04)

    def test_equal_relative_updates_invariant_and_never_labeled(self):
        self.assertEqual(len(self.checks), 3)
        for row in self.checks:
            self.assertIsNone(row["slo_label"])
            self.assertEqual(row["evidence_class"], "unexecuted_geometry_check")
            self.assertLess(row["relative_vector_error"], 1e-12)
            self.assertAlmostEqual(row["relative_displacement_norm"], .22883719431200317)
        self.assertEqual(len({r["raw_share_displacement_norm"] for r in self.checks}), 3)

    def test_selected_energy_loss_is_not_alarm_error(self):
        self.assertAlmostEqual(self.summary["median_history_median_cumulative_hidden_fraction"], .7810880219403395)
        self.assertIsNone(self.definition["success_threshold"])
        self.assertIn("retrospective", self.definition["evidence_class"])

    def test_unchanged_analogy_and_separate_nochange_diagnostic(self):
        records = {r["method"]: r for r in self.summary["secondary_diagnostics"]}
        self.assertAlmostEqual(records["posthoc_no_headroom_change"]["macro_pair_mean_absolute_error"], .26912340630947634)
        self.assertAlmostEqual(records["full_ilr_change"]["macro_pair_mean_absolute_error"], .4119745245962941)
        self.assertEqual(records["euclidean_share_change"]["median_nearest_pairs"], 11)
        self.assertEqual(records["full_ilr_change"]["median_nearest_pairs"], 2)

    def test_changed_source_design_and_matrix_are_rejected(self):
        for key, value in (("mode", "pilot"), ("profile", "other"), ("order", [])):
            bid = "balanced-moderate-01"
            sample = {bid: dict(self.blocks[bid], **{key: value})}
            with self.assertRaises(ValueError):
                analyze_histories(sample, self.design, self.definition)

    def test_missing_pairs_are_retained_not_fabricated(self):
        rows, trajectories, errors = analyze_histories({}, self.design, self.definition)
        self.assertEqual((rows, trajectories), ([], []))
        self.assertTrue(all(v == 0 for v in errors.values()))

    def test_save_exports_every_window_valid_figures_and_unlabeled_checks(self):
        with tempfile.TemporaryDirectory() as name:
            out = Path(name) / "out"
            result = save(out)
            self.assertFalse(result["analysis_execution"]["runtime_started"])
            for csv_name, count in (("history-windows.csv", 988), ("trajectory-level.csv", 48),
                                    ("prefix-witnesses.csv", 2), ("prefix-witness-history.csv", 21)):
                with (out / csv_name).open(newline="", encoding="utf-8") as f:
                    self.assertEqual(len(list(csv.DictReader(f))), count)
            for svg in ("history.svg", "prefix-witness.svg"):
                ET.fromstring((out / svg).read_text(encoding="utf-8"))
            self.assertIn("not independent replications", (out / "RESULTS.md").read_text())
            with self.assertRaises(FileExistsError):
                save(out)

    def test_empty_plot_and_missing_prefix_have_no_invented_example(self):
        ET.fromstring(figure("Empty", "No values", []))
        svg = witness_figure(self.blocks, [])
        ET.fromstring(svg)
        self.assertIn("No equal-prefix", svg)

    def test_archived_packet_replays_from_pinned_observations(self):
        archive = ROOT / "probe7/results/accumulated-v0.1.0"
        recorded = json.loads((archive / "summary.json").read_text(encoding="utf-8"))
        execution = recorded["analysis_execution"]
        self.assertEqual(len(execution["commit"]), 40)
        self.assertNotEqual(execution["run_id"], "0")
        self.assertFalse(execution["runtime_started"])

        def compare(a, b):
            if isinstance(a, dict):
                self.assertEqual(set(a), set(b))
                for key in a:
                    compare(a[key], b[key])
            elif isinstance(a, list):
                self.assertEqual(len(a), len(b))
                for x, y in zip(a, b):
                    compare(x, y)
            elif isinstance(a, (int, float)) and not isinstance(a, bool):
                self.assertTrue(math.isclose(a, b, rel_tol=1e-11, abs_tol=1e-11), (a, b))
            else:
                self.assertEqual(a, b)

        with tempfile.TemporaryDirectory() as name:
            out = Path(name) / "replay"
            recreated = save(out, commit=execution["commit"], run_id=execution["run_id"])
            compare(recorded, recreated)
            self.assertEqual({p.name for p in out.iterdir()}, {p.name for p in archive.iterdir() if p.name != "README.md"})
            for csv_path in out.glob("*.csv"):
                expected = archive / csv_path.name
                with csv_path.open(newline="", encoding="utf-8") as a, expected.open(newline="", encoding="utf-8") as b:
                    actual_rows, expected_rows = list(csv.DictReader(a)), list(csv.DictReader(b))
                self.assertEqual(len(actual_rows), len(expected_rows))
                for actual, expected in zip(actual_rows, expected_rows):
                    self.assertEqual(set(actual), set(expected))
                    for key in actual:
                        if actual[key] != expected[key]:
                            try:
                                compare(float(actual[key]), float(expected[key]))
                            except ValueError:
                                self.fail(f"Changed archived field: {csv_path.name}/{key}")
            for svg in ("history.svg", "prefix-witness.svg"):
                self.assertEqual((out / svg).read_text(encoding="utf-8"), (archive / svg).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
