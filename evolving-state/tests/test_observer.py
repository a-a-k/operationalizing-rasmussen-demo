from __future__ import annotations

import copy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from observer import Observer, extract, ilr, inverse_ilr, registry
from analyze import oracle


def metadata():
    return {"initial_policy": 1, "deployments": {"1": {"components": {
        "a": {"group": "catalog", "predecessors": []},
        "b": {"group": "currency", "predecessors": []}}}},
        "policies": {"1": {"limits": {"catalog": .25, "currency": .25}}}}


def snap(window=1, values=(80, 20, 90, 10), version=1, policy=1):
    return {"window": window, "received_ms": window * 10000 + 500,
            "generated_ms": window * 10000 + 400, "window_end_ms": window * 10000,
            "policy_version": policy, "counts": [
                {"deployment": version, "component": c, "kind": k, "count": n}
                for (c, k), n in zip((("a", "first"), ("a", "retry"),
                                     ("b", "first"), ("b", "retry")), values)]}


class ObserverTests(unittest.TestCase):
    def test_ilr_inverse_and_scale_invariance(self):
        original = [80., 20., 90., 10.]
        z = ilr(original)
        for x, y in zip(inverse_ilr(z), [v / sum(original) for v in original]):
            self.assertAlmostEqual(x, y)
        for x, y in zip(z, ilr([v * 7 for v in original])):
            self.assertAlmostEqual(x, y)
        mean = sum(math.log(v) for v in original) / 4
        self.assertAlmostEqual(sum(v * v for v in z),
                               sum((math.log(v) - mean) ** 2 for v in original))

    def test_known_helmert_coordinate(self):
        self.assertAlmostEqual(ilr([1., 4.])[0], -math.log(4) / math.sqrt(2))

    def test_pure_reexpression_preserves_counts_and_ilr(self):
        meta = metadata()
        obs = Observer("coda", meta)
        first = obs.update(snap(), meta)
        meta["deployments"]["2"] = {"components": {
            "c": {"predecessors": ["a"]}, "d": {"predecessors": ["a"]},
            "b": {"group": "currency", "predecessors": []}}}
        second = snap(2, version=2)
        second["counts"] = [r for r in second["counts"] if r["component"] == "b"] + [
            {"deployment": 2, "component": c, "kind": kind, "count": count}
            for c in ("c", "d") for kind, count in (("first", 40), ("retry", 10))]
        last = obs.update(second, meta)
        self.assertEqual(first["geometry"]["ilr"], last["geometry"]["ilr"])
        self.assertEqual(last["geometry"]["increment"], [0., 0., 0.])

    def test_actual_change_survives_split(self):
        meta = metadata()
        obs = Observer("coda", meta)
        obs.update(snap(), meta)
        meta["deployments"]["2"] = {"components": {"a": {"group": "catalog"},
                                                  "b": {"group": "currency"}}}
        row = obs.update(snap(2, (80, 60, 90, 10), version=2), meta)
        self.assertTrue(row["groups"]["catalog"]["violation"])
        self.assertGreater(sum(v * v for v in row["geometry"]["increment"]), 0)

    def test_policy_only_change_has_no_movement(self):
        meta = metadata()
        obs = Observer("coda", copy.deepcopy(meta))
        obs.update(snap(), meta)
        meta["policies"]["2"] = {"limits": {"catalog": .1, "currency": .1}}
        row = obs.update(snap(2, policy=2), meta)
        self.assertEqual(row["geometry"]["increment"], [0., 0., 0.])
        self.assertAlmostEqual(row["groups"]["catalog"]["delta_margin"], -.15)
        self.assertEqual(row["groups"]["catalog"]["delta_ratio"], 0.)
        self.assertTrue(row["groups"]["catalog"]["violation"])

    def test_concurrent_policy_and_execution_decomposition(self):
        meta = metadata()
        obs = Observer("direct", copy.deepcopy(meta))
        obs.update(snap(), meta)
        meta["policies"]["2"] = {"limits": {"catalog": .1, "currency": .1}}
        row = obs.update(snap(2, (80, 40, 90, 10), policy=2), meta)
        g = row["groups"]["catalog"]
        self.assertAlmostEqual(g["delta_margin"], g["delta_policy"] - g["delta_ratio"])
        self.assertNotEqual(g["delta_ratio"], 0)
        self.assertNotEqual(g["delta_policy"], 0)

    def test_missing_policy_different_from_missing_lineage(self):
        meta = metadata()
        row = Observer("coda", meta).update(snap(policy=2), meta)
        self.assertEqual(row["policy_status"], "missing_policy")
        self.assertEqual(row["geometry_status"], "available")
        row = Observer("coda", meta).update(snap(version=2), meta)
        self.assertEqual(row["state_status"], "missing_lineage")
        self.assertIsNone(row["groups"]["catalog"]["ratio"])

    def test_zero_retry_and_no_observation_are_distinct(self):
        for mode in ("direct", "coda"):
            meta = metadata()
            row = Observer(mode, meta).update(snap(values=(100, 0, 100, 0)), meta)
            self.assertFalse(row["groups"]["catalog"]["violation"])
            self.assertEqual(row["groups"]["catalog"]["status"], "available")
            row = Observer(mode, meta).update(snap(values=(0, 0, 100, 0)), meta)
            self.assertIsNone(row["groups"]["catalog"]["violation"])
            self.assertEqual(row["groups"]["catalog"]["status"], "no_attempts")
        self.assertEqual(row["geometry_status"], "zero_part")

    def test_direct_and_coda_decisions_including_exact_boundary(self):
        for n in (0, 1, 2, 3, 6, 20, 100):
            meta = metadata()
            direct = Observer("direct", meta).update(snap(values=(6, n, 90, 10)), meta)
            coda = Observer("coda", meta).update(snap(values=(6, n, 90, 10)), meta)
            self.assertEqual(direct["groups"], coda["groups"])

    def test_causal_prefix_and_repeated_window_do_not_refilter(self):
        meta = metadata()
        obs = Observer("coda", meta)
        obs.update(snap(), meta)
        second = obs.update(snap(2, (80, 40, 90, 10)), meta)
        again = obs.update(snap(2, (80, 40, 90, 10)), meta)
        self.assertEqual(second["geometry"], again["geometry"])
        earlier = copy.deepcopy(second)
        obs.update(snap(3, (1, 10000, 999, 2)), meta)
        self.assertEqual(second, earlier)

    def test_gap_does_not_generate_fictitious_step(self):
        meta = metadata()
        obs = Observer("coda", meta)
        obs.update(snap(), meta)
        row = obs.update(snap(3), meta)
        self.assertIsNone(row["geometry"]["increment"])
        self.assertIsNone(row["groups"]["catalog"]["delta_margin"])

    def test_unknown_and_conflicting_predecessors_are_not_guessed(self):
        meta = metadata()
        meta["deployments"]["2"] = {"components": {
            "c": {"group": "catalog", "predecessors": ["absent"]},
            "d": {"group": "currency", "predecessors": ["a"]},
            "e": {"predecessors": ["a", "b"]}}}
        self.assertEqual(set(registry(meta)), {("1", "a"), ("1", "b")})

    def test_fixed_schema_preserves_known_ids_but_uses_old_policy(self):
        meta = metadata()
        row = Observer("fixed", meta).update(snap(version=2, policy=2), meta)
        self.assertEqual(row["state_status"], "available")
        self.assertEqual(row["policy_used"], 1)

    def test_duplicate_metric_rejected(self):
        data = snap()
        data["counts"].append(data["counts"][0])
        with self.assertRaises(ValueError):
            extract(data, metadata())

    def test_oracle_uses_event_route_not_component_name_or_registry(self):
        events = [
            {"type": "configuration_applied", "applied_ms": 0,
             "config": {"policy_limits": {"catalog": .25, "currency": .25}, "policy_version": 1}},
            {"type": "attempt_start", "logical_group": "catalog", "attempt": 0, "started_ms": 100,
             "component": "misleading-unmapped-name"},
            {"type": "attempt_start", "logical_group": "catalog", "attempt": 1, "started_ms": 200},
            {"type": "attempt_start", "logical_group": "catalog", "attempt": 2, "started_ms": 10000}]
        truth = oracle(events, snap(), 0, 10000)
        self.assertEqual(truth["groups"]["catalog"]["ratio"], .5)
        self.assertTrue(truth["groups"]["catalog"]["violation"])


if __name__ == "__main__":
    unittest.main()
