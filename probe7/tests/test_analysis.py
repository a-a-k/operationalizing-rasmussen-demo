from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"probe7/scripts"))
from analyze import METHODS, analogs, descriptors, rank
from model import initial_state, proposal


class AnalysisTests(unittest.TestCase):
    def test_same_pair_and_different_profile_are_never_neighbors(self):
        samples=[]
        for block,profile,epoch,value in [("a","moderate",1,0),("a","moderate",2,0),
                                          ("b","moderate",1,2),("c","busy",1,0)]:
            samples.append({"block_id":block,"profile":profile,"policy":"adaptive","epoch":epoch,
                            "features":{m:[value] for m in METHODS},"outcome_change":[0,0,0]})
        rows=analogs(samples)
        for r in rows:
            self.assertNotEqual(r["query_block"],r["neighbor_block"])
            if r["query_block"]=="a":
                self.assertEqual(r["neighbor_block"],"b")
        self.assertFalse(any(r["query_block"]=="c" for r in rows))

    def test_unobserved_local_direction_is_retained_by_full_state(self):
        d=json.loads((ROOT/"probe7/design-v0.1.1.json").read_text())
        start=initial_state(d,"balanced")
        end=proposal(start,"cpu","accounting","kafka",.05)
        f=descriptors(start,end,d)
        self.assertTrue(all(abs(v)<1e-12 for v in f["selected_log_ratios"]))
        self.assertGreater(sum(v*v for v in f["full_ilr_change"]),0)
        self.assertEqual(len(f["euclidean_share_change"]),22)
        self.assertEqual(len(f["full_ilr_change"]),20)

    def test_observed_span_is_numerical_not_window_count(self):
        self.assertEqual(rank([[1,0],[2,0],[0,1],[1,1]]),2)
        self.assertEqual(rank([]),0)


if __name__=="__main__":
    unittest.main()
