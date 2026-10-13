from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe7/scripts"))
from measurements import accounting, advertising, parse_ack_lines
from model import choose, helmert, initial_state, matrix, proposal, representation


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.d = json.loads((ROOT / "probe7/design-v0.2.0.json").read_text())
        self.s = initial_state(self.d, "balanced")

    def test_twenty_four_pairs_and_twenty_coordinates(self):
        rows = matrix(self.d)
        self.assertEqual(len(rows), 24)
        self.assertEqual(sum(r["order"][0] == "adaptive" for r in rows), 12)
        for state in self.d["initial_states"]:
            for profile in self.d["profiles"]:
                self.assertEqual(sum(r["order"][0]=="adaptive" for r in rows
                                     if r["initial_state"]==state["id"] and r["profile"]==profile["id"]),2)
        for named in self.d["initial_states"]:
            state = initial_state(self.d, named["id"])
            self.assertAlmostEqual(sum(state["cpu"].values()), 3.4)
            self.assertEqual(sum(state["memory"].values()), 4544 * 2**20)
            self.assertEqual(len(representation(state, self.d)["ilr"]), 20)

    def test_multiplicative_change_is_initial_state_invariant(self):
        factors = [0.8 + i / 10 for i in range(11)]
        deltas = []
        for named in self.d["initial_states"]:
            shares = representation(initial_state(self.d, named["id"]), self.d)["shares"]["cpu"]
            changed = [a*b for a,b in zip(shares, factors)]
            total = sum(changed)
            deltas.append([a-b for a,b in zip(helmert([v/total for v in changed]), helmert(shares))])
        for a,b in zip(deltas[0],deltas[1]):
            self.assertAlmostEqual(a,b)

    def test_transfer_closes_each_budget(self):
        for r, amount in [("cpu", .04), ("memory", 32 * 2**20)]:
            changed = proposal(self.s, r, "frontend", "ad", amount)
            self.assertAlmostEqual(sum(changed[r].values()), sum(self.s[r].values()))
            other = "memory" if r == "cpu" else "cpu"
            self.assertEqual(changed[other],self.s[other])
        with self.assertRaises(ValueError):
            proposal(self.s, "cpu", "frontend", "ad", 2)

    def previous(self):
        return {"valid": True, "safe": True,
                "headroom": {"checkout": .7, "advertising": .6, "accounting": .9},
                "resources": {p: {"cpu_cores": .01, "throttling": 1 if p == "ad" else 0,
                                  "memory_peak_bytes": 64*2**20, "memory_fraction": .2}
                              for p in self.d["parts"]}}

    def test_controller_uses_requirements_and_pressure_not_geometry(self):
        p = self.previous()
        action = choose(self.s, p, self.d, set())
        self.assertIsNotNone(action)
        p["safe"] = False
        self.assertIsNone(choose(self.s,p,self.d,set()))
        p["safe"] = True
        p["resources"]["ad"]["throttling"] = 0
        self.assertIsNone(choose(self.s,p,self.d,set()))

    def test_memory_requires_capacity_reserve(self):
        self.d["controller"]["active_resources"] = ["memory"]
        p = self.previous()
        self.assertIsNone(choose(self.s,p,self.d,set()))
        p["resources"]["ad"]["memory_fraction"] = .9
        for donor in self.d["controller"]["dependencies"]:
            p["resources"][donor]["memory_peak_bytes"] = self.s["memory"][donor]
        self.assertIsNone(choose(self.s,p,self.d,set()))


class MeasurementTests(unittest.TestCase):
    def test_missing_and_late_orders_are_not_dropped(self):
        p={"deadline_ms":5000,"minimum_timely_fraction":.99}
        result=accounting([{"order_id":"a","confirmed_ms":1000},{"order_id":"b","confirmed_ms":1000},
                           {"order_id":"c","confirmed_ms":1000}],{"a":500,"b":7000},p)
        self.assertEqual(result["timely"],1)
        self.assertEqual(result["late"],1)
        self.assertEqual(result["missing"],1)
        self.assertFalse(result["safe"])
        self.assertEqual(result["orders"][0]["lag_ms"],0)

    def test_duplicate_acknowledgments_rejected(self):
        with self.assertRaises(ValueError):
            accounting([{"order_id":"a","confirmed_ms":0}]*2,{},{"deadline_ms":5000,"minimum_timely_fraction":.99})

    def test_raw_log_order_bridge(self):
        self.assertEqual(parse_ack_lines('ORDER_ACK {"order_id":"a","confirmed_ms":123}\n'),
                         [{"order_id":"a","confirmed_ms":123}])

    def test_ad_unfinished_attempts_violate_deadline(self):
        metrics={n:{"values":{"count":v}} for n,v in
                 [("ad_attempts",100),("ad_finished",98),("ad_timely",98),("ad_useful_inside_window",98)]}
        metrics.update(ad_latency_ms={"values":{"p(99)":20}},ad_window_start_ms={"values":{"min":1000}})
        result=advertising({"metrics":metrics},30,{"deadline_ms":200,"minimum_timely_fraction":.99})
        self.assertFalse(result["safe"])
        self.assertEqual(result["unfinished"],2)


if __name__ == "__main__":
    unittest.main()
