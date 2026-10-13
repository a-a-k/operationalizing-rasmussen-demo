from __future__ import annotations

import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"probe7/scripts"))
from analyze import METHODS, analogs, descriptors, rank, save, summarize
from model import initial_state, proposal, representation


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
        d=json.loads((ROOT/"probe7/design-v0.2.0.json").read_text())
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

    def test_tied_analogs_average_pairs_not_lexical_outcomes(self):
        samples=[]
        for block,epoch,outcome in [("a",1,0),("b",1,1),("b",2,1),("c",1,3)]:
            samples.append({"block_id":block,"profile":"moderate","policy":"adaptive","epoch":epoch,
                            "features":{m:[0] for m in METHODS},"outcome_change":[outcome]*3})
        rows=[r for r in analogs(samples) if r["query_block"]=="a"]
        self.assertTrue(all(r["checkout_predicted_change"]==2 for r in rows))
        self.assertTrue(all(r["equidistant_pairs"]==2 for r in rows))

    def test_missing_blocks_are_not_invented_and_pilot_is_rejected(self):
        d=json.loads((ROOT/"probe7/design-v0.2.0.json").read_text())
        with tempfile.TemporaryDirectory() as name:
            result=save(Path(name)/"out",{},d)
            self.assertEqual(result["received_pairs"],0)
            self.assertEqual(len(result["missing_pairs"]),24)
            self.assertIsNone(result["retrieval"]["full_ilr_change"]["macro_pair_mean_absolute_error"])
        bid="balanced-moderate-01"
        with self.assertRaises(ValueError):
            summarize({bid:{"mode":"pilot"}},d)

    def test_full_save_keeps_accumulated_changes_and_valid_svg(self):
        d=json.loads((ROOT/"probe7/design-v0.2.0.json").read_text())
        state=initial_state(d,"balanced")
        changed=proposal(state,"cpu","accounting","ad",.04)
        def window(epoch,allocation):
            return {"epoch":epoch,"valid":True,"safe":True,"allocation":allocation,
                    "headroom":{p:.8 for p in ("checkout","advertising","accounting")},
                    "checkout":{"p95_ms":100,"error_rate":0},
                    "advertising":{"goodput":500,"timely_fraction":1},
                    "accounting":{"timely_fraction":1,"missing":0},
                    "representation":representation(allocation,d),"window_start_ms":0,"window_end_ms":30000}
        block={"mode":"main","profile":"moderate","initial_state":"balanced","design":d,
               "histories":{p:{"baseline_valid":True,"observations":[window(0,state),window(1,changed if p=="adaptive" else state)],
                               "transitions":[]} for p in ("adaptive","control")}}
        with tempfile.TemporaryDirectory() as name:
            out=Path(name)/"out"
            result=save(out,{"balanced-moderate-01":block},d)
            self.assertEqual(result["initially_valid_pairs"],1)
            self.assertEqual(result["retrieval_sections"],1)
            self.assertIn("full_ilr_change_from_baseline_norm",(out/"windows.csv").read_text())
            ET.fromstring((out/"example.svg").read_text())


if __name__=="__main__":
    unittest.main()
