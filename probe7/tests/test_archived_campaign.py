from __future__ import annotations

import gzip
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"probe7/scripts"))
from analyze import summarize
from audit_primary import audit


class ArchivedCampaignTests(unittest.TestCase):
    def test_all_received_observations_reproduce_the_aggregate(self):
        folder=ROOT/"probe7/results/main-v0.2.0"
        blocks=json.loads((folder/"block-level.json").read_text())
        design=json.loads((ROOT/"probe7/design-v0.2.0.json").read_text())
        actual=summarize(blocks,design)[0]
        self.assertEqual(actual,json.loads((folder/"summary.json").read_text()))
        self.assertEqual(actual["received_pairs"],24)
        self.assertEqual(actual["measured_windows"],988)
        self.assertEqual(actual["complete_cycle_pairs"],23)

    def test_primary_durations_counters_and_commit_bridge_rescore(self):
        folder=ROOT/"probe7/results/main-v0.2.0/primary"
        files=sorted(folder.glob("*.json.gz"))
        self.assertEqual(len(files),24)
        rows=[]
        for file in files:
            with gzip.open(file,"rt",encoding="utf-8") as f:
                rows.append(audit(json.load(f)))
        recorded=json.loads((folder/"summary.json").read_text())
        self.assertEqual(rows,recorded["per_block"])
        self.assertEqual(sum(r["windows"] for r in rows),988)
