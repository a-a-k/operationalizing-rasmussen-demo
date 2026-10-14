from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe8/scripts"))
from warning_model import (alerts, choose_threshold, current_features, history_distance,
                      predict, read_inputs, scatter_scales, target, threshold_rows)


class WarningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.definition, cls.design, cls.blocks = read_inputs(ROOT)

    def test_missing_future_is_not_negative_but_observed_failure_is_known(self):
        windows = [{"epoch": 0, "valid": True, "safe": True},
                   {"epoch": 1, "valid": True, "safe": True}]
        self.assertIsNone(target(windows, 0, 2))
        windows[1]["safe"] = False
        self.assertEqual(target(windows, 0, 2), 1)
        windows[1]["valid"] = False
        self.assertIsNone(target(windows, 0, 2))

    def test_complete_safe_future_is_negative(self):
        windows = [{"epoch": i, "valid": True, "safe": True} for i in range(3)]
        self.assertEqual(target(windows, 0, 2), 0)

    def test_features_use_current_and_past_not_future(self):
        observations = self.blocks["balanced-moderate-01"]["histories"]["adaptive"]["observations"]
        features, reason = current_features(observations[:4], self.design, self.definition)
        changed = copy.deepcopy(observations)
        changed[4]["allocation"]["cpu"]["ad"] *= 5
        other, _ = current_features(changed[:4], self.design, self.definition)
        self.assertEqual(features, other)
        self.assertIsNone(reason)
        self.assertEqual(len(features["prefix"]), 4)
        self.assertEqual(len(features["prefix"][0]["ilr_history"][0]), 10)

    def test_unsafe_and_truncated_planned_horizon_are_ineligible(self):
        obs = self.blocks["interactive-busy-01"]["histories"]["adaptive"]["observations"]
        self.assertEqual(current_features(obs[:7], self.design, self.definition)[1], "currently_unsafe_or_unknown")
        self.assertEqual(current_features(obs[:20], self.design, self.definition)[1], "planned_horizon_unobserved")

    def test_scale_is_isotropic_not_per_coordinate(self):
        snapshots = [{"coords": {"m": [[1, 2], [3, 3]]}}, {"coords": {"m": [[3, 4], [3, 3]]}}]
        scales = scatter_scales(snapshots, ["m"])
        self.assertAlmostEqual(scales["m"][0], 2**.5)
        self.assertIsNone(scales["m"][1])

    def test_score_excludes_whole_development_pair_and_averages_pair_ties(self):
        definition = {"methods": ["m"], "neighbor_pairs": 2, "tie_tolerance": 1e-10}
        query = {"profile": "p", "epoch": 0, "business": [0], "prefix": [{"m": [[0]]}]}
        candidates = [dict(query, block_id=bid, label=label) for bid, label in
                      [("a", 1), ("b", 0), ("b", 0), ("c", 1)]]
        result = predict(query, candidates, {"m": [1]}, definition, exclude_pair="a")["m"]
        self.assertEqual(result["score"], .5)
        self.assertEqual(result["neighbor_pairs"], 2)
        self.assertNotIn("a", result["neighbors"])

    def test_unmatched_profile_and_epoch_are_not_neighbors(self):
        definition = {"methods": ["m"], "neighbor_pairs": 2, "tie_tolerance": 1e-10}
        query = {"profile": "p", "epoch": 0, "business": [0], "prefix": [{"m": [[0]]}]}
        candidates = [dict(query, block_id="b", profile="other", label=1),
                      dict(query, block_id="c", epoch=1, label=1)]
        self.assertIsNone(predict(query, candidates, {"m": [1]}, definition)["m"]["score"])

    def test_distance_preserves_every_prefix_vertex(self):
        a = {"epoch": 1, "business": [0], "prefix": [{"m": [[0]]}, {"m": [[0]]}]}
        b = copy.deepcopy(a)
        b["prefix"][0]["m"][0][0] = 2
        self.assertAlmostEqual(history_distance(a, b, "m", {"m": [1]}), 2**.5)

    def test_threshold_is_selected_only_from_development_operating_points(self):
        records = [{"method": "m", "label": label, "score": score} for label, score in
                   [(1, .8), (1, .6), (0, .7), (0, .1)]]
        rows = threshold_rows(records, "m")
        threshold = choose_threshold(rows, {"false_warning_rate_budget": .05})
        self.assertEqual(threshold, .8)
        self.assertTrue(alerts(.8, threshold))
        self.assertFalse(alerts(.7, threshold))
        self.assertFalse(alerts(1, None))

    def test_rule_and_parent_source_versions_are_explicit(self):
        self.assertEqual(self.definition["horizon_cycles"], 2)
        self.assertEqual(self.definition["confirmation_pairs"], 20)
        self.assertEqual(len(self.definition["methods"]), 4)
        campaign = json.loads((ROOT / "probe8/runtime-design-v0.1.0.json").read_text())
        self.assertEqual(campaign["controller"], self.design["controller"])
        self.assertEqual(campaign["reference_cpu"], self.design["reference_cpu"])
        self.assertEqual(len(campaign["confirmation_blocks"]), 20)
        self.assertEqual({(r["initial_state"], r["profile"]) for r in campaign["confirmation_blocks"]},
                         {(s["id"], p["id"]) for s in self.design["initial_states"] for p in self.design["profiles"]})


if __name__ == "__main__":
    unittest.main()
