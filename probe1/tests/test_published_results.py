from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class PublishedResultTests(unittest.TestCase):
    def test_aggregate_matches_replicate_table(self) -> None:
        summary = json.loads((ROOT / "probe1/results/summary.json").read_text(encoding="utf-8"))
        with (ROOT / "probe1/results/replicate-level.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 256)
        self.assertEqual(sum(row["a5_safe"] == "True" for row in rows), 256)
        self.assertEqual(sum(row["b5_safe"] == "False" for row in rows), 221)
        self.assertEqual(sum(int(row["y"]) for row in rows), 221)
        self.assertEqual(summary["primary"]["N"], len(rows))
        self.assertEqual(summary["primary"]["K"], sum(int(row["y"]) for row in rows))
        self.assertIsNone(summary["primary"]["decision_criterion"])

    def test_pair_order_is_balanced(self) -> None:
        with (ROOT / "probe1/results/replicate-level.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(sum(row["order"] == "A5->B5" for row in rows), 128)
        self.assertEqual(sum(row["order"] == "B5->A5" for row in rows), 128)


if __name__ == "__main__":
    unittest.main()
