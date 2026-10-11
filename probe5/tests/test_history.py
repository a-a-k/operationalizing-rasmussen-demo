from __future__ import annotations

import copy
import csv
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe5/scripts"))
from analyze_history import DEFINITION, analyze, derive
from geometry import CPU_BASIS, inverse_ilr


class SavedHistoryTests(unittest.TestCase):
    def test_retrospective_pair_results(self):
        result, history, pairs, metadata = analyze()
        self.assertEqual(result["pair_count"], 19)
        self.assertEqual(result["valid_and_slo_safe_pairs"], 19)
        self.assertEqual(result["both_positive_pairs"], 19)
        self.assertEqual(result["missing_planned_pairs"], ["migration-006"])
        self.assertEqual(result["shared_step6_adaptive_allocation"], [.22, .22, .22, .34])
        self.assertAlmostEqual(result["goodput_change_difference_responses_per_second"]["median"], 863.9333333333)
        self.assertAlmostEqual(result["p95_change_difference_ms"]["median"], 47.09871765)
        self.assertEqual(len(history), 594)
        self.assertIn("Retrospective", result["selection"])
        self.assertIn("timestamps are absent", metadata["time_index"])

    def test_complete_coordinates_and_path_length(self):
        _, history, _, _ = analyze()
        for row in history:
            restored = inverse_ilr([row[f"z{i}"] for i in range(1, 4)], CPU_BASIS)
            for value, part in zip(restored, ["checkout", "payment", "shipping", "ad"]):
                self.assertAlmostEqual(value, row[part], places=13)
            self.assertGreaterEqual(row["registered_path_length"] + 1e-12, row["distance_from_reference"])
            if row["policy"] == "control":
                self.assertAlmostEqual(row["registered_path_length"], 0)

    def inputs(self):
        definition = json.loads((ROOT / DEFINITION).read_text())
        design = json.loads((ROOT / definition["execution_design"]).read_text())
        with (ROOT / definition["source"]).open(newline="") as f:
            return list(csv.DictReader(f)), definition, design

    def test_duplicate_and_missing_epochs_rejected(self):
        rows, definition, design = self.inputs()
        with self.assertRaises(ValueError):
            derive(rows + [copy.deepcopy(rows[0])], definition, design)
        with self.assertRaises(ValueError):
            derive([r for r in rows if not (r["block_id"] == "migration-001"
                   and r["policy"] == "drift" and r["epoch"] == "6")], definition, design)

    def test_readable_invalid_window_not_filtered(self):
        rows, definition, design = self.inputs()
        row = next(r for r in rows if r["block_id"] == "migration-001"
                   and r["policy"] == "drift" and r["epoch"] == "6")
        row["valid"] = "False"
        result, history, pairs, _ = derive(rows, definition, design)
        self.assertEqual(result["pair_count"], 19)
        self.assertEqual(result["valid_and_slo_safe_pairs"], 18)
        self.assertEqual(len(history), 594)
        self.assertFalse(next(r for r in pairs if r["block_id"] == "migration-001")["drift6_valid"])

    def test_goodput_denominator_mismatch_rejected(self):
        rows, definition, design = self.inputs()
        rows[0]["ad_goodput"] = str(float(rows[0]["ad_goodput"]) + 1)
        with self.assertRaises(ValueError):
            derive(rows, definition, design)


if __name__ == "__main__":
    unittest.main()
