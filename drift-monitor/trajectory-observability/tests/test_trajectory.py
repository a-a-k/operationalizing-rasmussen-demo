import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
import numpy as np
from analyze import PARTS, LAM, trajectory, smooth_steps, clr, close, coarse, action, resolve, fragments_at, structural_check, angle


class TrajectoryChecks(unittest.TestCase):
    def reference(self):
        return np.linspace(.1, 1.1, len(PARTS))

    def test_prefix_does_not_depend_on_future(self):
        rng = np.random.default_rng(12)
        values = rng.uniform(.1, 2, (8, len(PARTS)))
        _, full = trajectory(values, self.reference(), np.arange(8)*40000)
        _, prefix = trajectory(values[:4], self.reference(), np.arange(4)*40000)
        for key in ("steps", "filtered", "displacement", "raw_steps", "raw_filtered"):
            np.testing.assert_allclose(full[key][:4], prefix[key], atol=1e-14)

    def test_actual_stop_has_zero_increment_but_ewma_decays(self):
        ref = self.reference(); moved = ref.copy(); moved[0] *= 2
        rows, data = trajectory([ref, moved, moved], ref, [0, 40e3, 80e3], first_is_reference=True)
        np.testing.assert_allclose(data["steps"][2], 0, atol=1e-14)
        np.testing.assert_allclose(data["filtered"][2], (1-LAM)*data["filtered"][1], atol=1e-14)
        self.assertGreater(rows[2]["displacement_norm"], 0)
        self.assertIsNone(angle(data["steps"][2], data["filtered"][2]))

    def test_restore_returns_position_and_changes_direction(self):
        ref = self.reference(); moved = ref.copy(); moved[0] *= 2
        rows, data = trajectory([ref, moved, ref], ref, [0, 40e3, 80e3], first_is_reference=True)
        self.assertAlmostEqual(rows[2]["displacement_norm"], 0)
        np.testing.assert_allclose(data["steps"][2], -data["steps"][1], atol=1e-14)
        self.assertAlmostEqual(rows[2]["increment_toward_reference_cosine"], 1)

    def test_direction_is_undefined_for_zero(self):
        self.assertIsNone(angle(np.zeros(11), np.ones(11)))

    def test_ewma_is_not_reused_mewma_alarm(self):
        steps = np.ones((4, 11))
        expected = (1-(1-LAM)**np.arange(1, 5))[:, None]*np.ones((4,11))
        np.testing.assert_allclose(smooth_steps(steps), expected)

    def test_common_multiplicative_path_has_same_relative_increments(self):
        rng = np.random.default_rng(20)
        factors = rng.uniform(.8, 1.2, (5, 11))
        a = self.reference(); b = a[::-1]
        _, da = trajectory(a*factors, a, np.arange(5))
        _, db = trajectory(b*factors, b, np.arange(5))
        np.testing.assert_allclose(da["steps"], db["steps"], atol=1e-14)
        np.testing.assert_allclose(da["filtered"], db["filtered"], atol=1e-14)

    def test_zero_negative_missing_are_not_replaced(self):
        for value in (0, -.1, np.nan):
            a = self.reference(); a[0] = value
            with self.assertRaises(ValueError): close(a)

    def test_lineage_recovers_detail_and_coarse_states(self):
        x = self.reference()
        for epoch in (1,5,8,10,12,16):
            fragments, lineage = fragments_at(x, epoch)
            reconstructed = resolve(fragments, lineage)
            np.testing.assert_allclose(reconstructed, x, atol=1e-14)
            np.testing.assert_allclose(coarse(reconstructed), coarse(x), atol=1e-14)

    def test_unknown_or_missing_semantic_part_gates_readout(self):
        f,l = fragments_at(self.reference(), 8)
        del l["accounting-b"]
        self.assertIsNone(resolve(f,l))
        f,l = fragments_at(self.reference(), 1)
        del f["cart"]
        self.assertIsNone(resolve(f,l))

    def test_within_group_change_not_hidden_in_detail(self):
        rows = structural_check(np.tile(self.reference(), (16,1)))
        self.assertTrue(all(r["within_group_change_detail_distance"]>0 for r in rows if r["epoch"]>=10))
        self.assertTrue(all(r["within_group_change_canonical_distance"]<1e-12 for r in rows))
        self.assertEqual(sum(r["unknown_lineage_gated"] for r in rows), 1)

    def test_quota_actions_are_not_consumption_labels(self):
        q = self.reference()
        self.assertEqual(action(q,q), "hold")
        self.assertEqual(action(q*2,q, {"restore":True}), "restore")
        self.assertEqual(action(q*2,q), "transfer")


if __name__ == "__main__":
    unittest.main()
