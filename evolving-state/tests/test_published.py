"""Replay published event evidence; dependent observations stay within histories."""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
import sys
import unittest

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE / "scripts"))
from analyze import compare
from describe import describe


class PublishedTests(unittest.TestCase):
    def test_every_history_reconstructs_without_runtime(self):
        for bundle in sorted((MODULE / "results").iterdir()):
            expected = json.loads((bundle / "analysis/summary.json").read_text())["histories"]
            for row in expected:
                with self.subTest(bundle=bundle.name, block=row["block"]):
                    actual, _, _ = compare(bundle / "inputs" / row["block"])
                    self.assertEqual(actual, row)

    def test_descriptive_statistics_follow_individual_calls(self):
        bundle = MODULE / "results/campaign-v0.1.1"
        data = json.loads((bundle / "analysis/interpretation-stats.json").read_text())
        self.assertEqual(len(data["histories"]), 8)
        for row in data["histories"]:
            self.assertEqual(describe(bundle / "inputs" / row["block"]), row)
        self.assertEqual(data["third_attempt_rescues"], 667)
        self.assertEqual(data["same_window_policy_decision_flips"], 5)
        self.assertEqual(data["geometry_status_counts"],
                         {"available": 135, "missing_lineage": 16, "zero_part": 30})

    def test_native_engine_and_all_applicable_fixtures_preserved(self):
        bundle = MODULE / "results/campaign-v0.1.1"
        engine = json.loads((bundle / "engine.json").read_text())
        self.assertEqual(engine["version"], "3.15.0")
        validations = json.loads((bundle / "promql-validation.json").read_text())
        self.assertEqual(len(validations), 8)
        self.assertEqual(sum(r["tests"] for r in validations), 165)
        self.assertTrue(all(r["exit_code"] == 0 for r in validations))

    def test_public_evidence_has_no_personal_paths_or_workflow_links(self):
        forbidden = ("C:\\Users\\", "/home/runner/" + "work/",
                     "workflow_run_id", ".tex", ".pdf")
        for path in (MODULE / "results").rglob("*"):
            if not path.is_file() or path.suffix not in (".json", ".jsonl", ".gz", ".csv", ".md"):
                continue
            data = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
            text = data.decode("utf-8")
            self.assertIsNone(re.search(r"github\.com/[^/]+/[^/]+/actions/", text))
            for term in forbidden:
                self.assertNotIn(term, text, str(path.relative_to(MODULE)))


if __name__ == "__main__":
    unittest.main()
