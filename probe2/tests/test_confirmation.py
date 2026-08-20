from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe2/scripts"))

from analyze_confirmation import analyze, binomial_summary, clopper_pearson  # noqa: E402
from common import CONDITIONS, load_json  # noqa: E402
from confirmation_common import confirmation_matrix  # noqa: E402


def result_for(block_id: str, block_number: int, order_id: str, *, pattern: bool = True, valid: bool = True) -> dict:
    points = {}
    for condition in CONDITIONS:
        safe = condition != "joint" if pattern else True
        points[condition] = {
            "valid": valid,
            "reason_codes": [] if valid else ["synthetic_invalid"],
            "test": {"safe": safe, "p95_ms": 100 if safe else 1000, "error_rate": 0 if safe else 0.5},
        }
    return {
        "study_protocol_version": "experiment2-confirmation-0.2",
        "block_id": block_id,
        "block_number": block_number,
        "order_id": order_id,
        "candidate_id": "r40-s019",
        "provenance": {"repository_commit": "c" * 40},
        "complete": True,
        "valid": valid,
        "points": points,
    }


class ConfirmationTests(unittest.TestCase):
    def test_matrix_has_32_blocks_and_balanced_orders(self) -> None:
        design = load_json(ROOT / "probe2/design.json")
        matrix = confirmation_matrix(design)
        self.assertEqual(len(matrix), 32)
        self.assertEqual(len({row["block_id"] for row in matrix}), 32)
        for order_id in design["condition_orders"]:
            self.assertEqual(sum(row["order_id"] == order_id for row in matrix), 8)

    def test_exact_interval_boundaries(self) -> None:
        lower, upper = clopper_pearson(32, 32)
        self.assertAlmostEqual(lower, 0.8911, places=3)
        self.assertEqual(upper, 1.0)
        self.assertEqual(clopper_pearson(0, 32)[0], 0.0)

    def test_binomial_summary_is_descriptive(self) -> None:
        summary = binomial_summary(8, 28)
        self.assertEqual(summary["successes"], 8)
        self.assertEqual(summary["trials"], 28)
        self.assertAlmostEqual(summary["proportion"], 8 / 28)
        self.assertEqual(
            set(summary),
            {"successes", "trials", "proportion", "clopper_pearson_95"},
        )

    def test_analysis_separates_valid_primary_and_invalid_sensitivity(self) -> None:
        design = load_json(ROOT / "probe2/design.json")
        results = {}
        for row in confirmation_matrix(design):
            results[row["block_id"]] = result_for(row["block_id"], row["block_number"], row["order_id"])
        results["c032"] = result_for("c032", 32, "o4", valid=False)
        summary = analyze(design, results, "c" * 40)
        self.assertEqual(summary["status"], "complete")
        self.assertEqual(summary["valid_blocks"], 31)
        self.assertEqual(summary["primary_valid_block_estimand"]["successes"], 31)
        self.assertEqual(summary["primary_valid_block_estimand"]["trials"], 31)
        self.assertEqual(summary["conservative_all_attempted_sensitivity"]["successes"], 31)
        self.assertEqual(summary["conservative_all_attempted_sensitivity"]["trials"], 32)

    def test_published_aggregate_matches_block_rows(self) -> None:
        summary = load_json(ROOT / "probe2/results/summary.json")
        blocks = summary["blocks"]
        self.assertEqual(len(blocks), 32)
        self.assertEqual(sum(block["valid"] for block in blocks), 28)
        self.assertEqual(sum(block["pattern"] for block in blocks), 8)
        self.assertEqual(summary["primary_valid_block_estimand"]["successes"], 8)
        self.assertEqual(summary["primary_valid_block_estimand"]["trials"], 28)
        self.assertEqual(summary["conservative_all_attempted_sensitivity"]["trials"], 32)
        self.assertEqual(
            set(summary["primary_valid_block_estimand"]),
            {"clopper_pearson_95", "proportion", "successes", "trials"},
        )


if __name__ == "__main__":
    unittest.main()
