from __future__ import annotations

import csv
import gzip
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe8/scripts"))
sys.path.insert(0, str(ROOT / "probe7/scripts"))
from analyze_confirmation import analyze, operating_curves
from audit_primary import audit
from live_runner import CAMPAIGN
from warning_model import WarningModel

ARCHIVE = ROOT / "probe8/results/confirmation-v0.1.0"


def rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def rendered(row):
    return {key: "" if value is None else str(value) for key, value in row.items()}


class ConfirmationArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = WarningModel()
        cls.blocks = json.loads((ARCHIVE / "evaluation/block-level.json").read_text())
        cls.saved = json.loads((ARCHIVE / "evaluation/summary.json").read_text())
        campaign = json.loads((ROOT / CAMPAIGN).read_text())
        cls.result = analyze(cls.blocks, cls.model, campaign,
                             cls.saved["execution_commit"], cls.saved["run_id"])

    def test_summary_and_every_live_prediction_replay(self):
        summary, decisions, histories, events, integrity = self.result
        self.assertEqual(summary, self.saved)
        self.assertEqual(summary["planned_pairs"], 20)
        self.assertEqual(summary["received_pairs"], 20)
        self.assertEqual(integrity, [])
        for name, generated in (("warning-decisions.csv", decisions),
                                ("history-level.csv", histories),
                                ("first-violation-events.csv", events)):
            self.assertEqual(rows(ARCHIVE / "evaluation" / name),
                             [rendered(row) for row in generated])

    def test_descriptive_curves_use_unchanged_development_thresholds(self):
        _, decisions, _, events, _ = self.result
        generated = operating_curves(decisions, events,
                                     self.model.definition["methods"],
                                     self.model.definition["horizon_cycles"])
        self.assertEqual(rows(ARCHIVE / "evaluation/operating-curves.csv"),
                         [rendered(row) for row in generated])

    def test_primary_outcomes_and_provenance_are_independently_reproduced(self):
        saved = json.loads((ARCHIVE / "primary/summary.json").read_text())
        reproduced = []
        for path in sorted((ARCHIVE / "primary").glob("*.json.gz")):
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                pack = json.load(stream)
            block = self.blocks[pack["block_id"]]
            self.assertEqual(pack["execution_commit"], block["execution_commit"])
            self.assertEqual(pack["run_id"], block["run_id"])
            reproduced.append(audit(pack))
        self.assertEqual(reproduced, saved["per_block"])
        for key in ("windows", "checkout_requests", "confirmed_orders", "ad_attempts"):
            self.assertEqual(sum(row[key] for row in reproduced), saved[key])
        self.assertEqual(len(reproduced), len(self.blocks))

    def test_host_contexts_cover_the_original_confirmation_pairs(self):
        runtime = json.loads((ROOT / "probe7/runtime-v0.2.0.json").read_text())
        paths = {path.stem: path for path in (ARCHIVE / "hosts").glob("*.json")}
        self.assertEqual(set(paths), set(self.blocks))
        for bid, path in paths.items():
            host = json.loads(path.read_text())
            self.assertEqual(host["upstream_commit"], runtime["upstream_commit"])
            self.assertEqual(host["runner_image"], self.blocks[bid]["runner_image"])
            self.assertTrue(host["cpu"])
            self.assertTrue(host["docker"])
            self.assertTrue(host["kernel"])


if __name__ == "__main__":
    unittest.main()
