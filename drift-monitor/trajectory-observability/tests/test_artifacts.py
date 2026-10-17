"""Check produced tables against summary counts and recurrence identities."""
from collections import defaultdict
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
import numpy as np
from analyze import OUT, PARTS, LAM, read, table


@unittest.skipUnless((OUT/"summary.json").exists(), "Run analyze.py first")
class ArtifactChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = read(OUT/"summary.json")
        cls.windows = table(OUT/"adaptation-windows.csv")
        cls.events = table(OUT/"adaptation-events.csv")

    def test_every_archived_window_and_short_history_remains(self):
        self.assertEqual(len(self.windows), self.summary["adaptation"]["windows"])
        self.assertEqual(len(self.windows), 988)
        self.assertEqual(len(read(OUT/"adaptation-histories.json")), 48)
        short = self.summary["adaptation"]["short_histories_retained"]
        self.assertEqual(len(short), 1)
        self.assertEqual(short[0]["stop_reason"], "baseline_not_valid_and_safe")

    def test_native_counter_replay_and_coverage(self):
        rows = table(OUT/"native-replay.csv")
        self.assertEqual(len(rows), len(self.windows))
        self.assertLess(max(float(r["maximum_mean_replay_error"]) for r in rows), 1e-12)
        self.assertTrue(all(float(r["minimum_counter_coverage"])>=.95 for r in rows))

    def test_actual_increment_and_ewma_recurrences(self):
        groups = defaultdict(list)
        for r in self.windows: groups[r["block_id"],r["policy"]].append(r)
        for rows in groups.values():
            rows.sort(key=lambda r:int(r["epoch"]))
            for kind in ("quota", "usage"):
                before = np.zeros(11); filtered = np.zeros(11)
                for r in rows:
                    displacement = np.array([float(r[kind+"_displacement_clr_"+p]) for p in PARTS])
                    increment = np.array([float(r[kind+"_increment_clr_"+p]) for p in PARTS])
                    reported = np.array([float(r[kind+"_ewma_increment_clr_"+p]) for p in PARTS])
                    np.testing.assert_allclose(increment, displacement-before, atol=1e-12)
                    filtered = LAM*increment+(1-LAM)*filtered
                    np.testing.assert_allclose(filtered, reported, atol=1e-12)
                    self.assertAlmostEqual(float(increment.sum()), 0)
                    before = displacement

    def test_quota_holds_and_restores_have_distinct_position_and_motion(self):
        holds = [r for r in self.events if r["action"]=="hold"]
        restores = [r for r in self.events if r["action"]=="restore"]
        self.assertEqual(len(holds),4); self.assertEqual(len(restores),5)
        for r in holds:
            self.assertAlmostEqual(float(r["quota_increment_norm"]),0)
            self.assertGreater(float(r["quota_displacement_norm"]),0)
            self.assertGreater(float(r["quota_ewma_increment_norm"]),0)
        self.assertEqual(sum(float(r["usage_displacement_change"])<0 for r in restores),
                         self.summary["adaptation"]["restore_usage_distance_reduced"])
        self.assertEqual(sum(float(r["integrated_usage_displacement_change"])<0 for r in restores),
                         self.summary["adaptation"]["restore_integrated_usage_distance_reduced"])

    def test_structural_replay_preserves_two_levels_but_not_within_group_information(self):
        rows = table(OUT/"structure-replay.csv")
        self.assertEqual(len(rows),4000)
        self.assertLess(max(float(r["pure_structure_detail_distance"]) for r in rows),1e-12)
        self.assertLess(max(float(r["within_group_change_canonical_distance"]) for r in rows),1e-12)
        self.assertTrue(all(float(r["within_group_change_detail_distance"])>0 for r in rows if int(r["epoch"])>=10))
        self.assertEqual(sum(r["unknown_lineage_gated"]=="True" for r in rows),250)

    def test_no_continuous_history_is_dropped(self):
        self.assertEqual(len(table(OUT/"continuous-histories.csv")),500)
        self.assertEqual(len(table(OUT/"continuous-windows.csv")),8000)
        self.assertEqual(len(read(OUT/"source-provenance.json")),250)


if __name__ == "__main__":
    unittest.main()
