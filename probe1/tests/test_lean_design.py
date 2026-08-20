from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
EXPERIMENT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

from analyze_lean import clopper_pearson  # noqa: E402
from confirmation_controller import ingest, initial_state, wave  # noqa: E402
from lean_design import (  # noqa: E402
    candidate_spec,
    confirmation_replication_ids,
    fixed_design_payload,
    load_json,
    point_spec,
    validate_plan,
    verify_selected,
)
from run_pair import randomized_order  # noqa: E402
from run_trial import validate_point_spec  # noqa: E402


PLAN_PATH = EXPERIMENT / "design.json"
RUNTIME_PATH = EXPERIMENT / "runtime.json"


def trial(safe: bool) -> dict:
    window = {"safe": safe, "started_iterations": 1440, "scheduled_iterations": 1440, "p95_ms": 100.0 if safe else 700.0}
    return {
        "validity": {"valid": True},
        "manipulation": {"valid": True},
        "baseline": copy.deepcopy(window) | {"safe": True},
        "test": window,
    }


def pair(candidate_id: str, replication_id: str = "calibration", attempt_id: int = 1, *, valid: bool = True) -> dict:
    return {
        "protocol_version": "0.3.3",
        "phase": "calibration" if replication_id == "calibration" else "confirmation",
        "candidate_id": candidate_id,
        "replication_id": replication_id,
        "attempt_id": attempt_id,
        "workflow_run_id": "123456",
        "selected_design_sha256": None,
        "order": ["A5", "B5"],
        "valid": valid,
        "reason_codes": [] if valid else ["runner_failure"],
        "primary": {"a5_safe": True, "b5_safe": False, "y": 1} if valid else None,
        "points": {"A5": trial(True), "B5": trial(False)} if valid else {},
    }


class LeanDesignTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = load_json(PLAN_PATH)

    def test_bounded_plan_and_geometry(self) -> None:
        validate_plan(self.plan)
        self.assertEqual(len(self.plan["calibration"]["candidates"]), 1)
        for item in self.plan["calibration"]["candidates"]:
            candidate = candidate_spec(self.plan, item["id"])
            self.assertEqual(candidate["roles"], {"critical": "checkout", "n1": "payment", "n2": "shipping"})
            self.assertEqual(candidate["points"]["A5"]["requested_quotas"], {"checkout": 0.3, "payment": 0.62, "shipping": 0.08})
            self.assertEqual(candidate["points"]["B5"]["requested_quotas"], {"checkout": 0.12, "payment": 0.44, "shipping": 0.44})
            self.assertGreaterEqual(
                candidate["points"]["A5"]["geometry"]["E"] - candidate["points"]["B5"]["geometry"]["E"],
                0.01 - 1e-12,
            )
            self.assertGreaterEqual(
                candidate["points"]["A5"]["geometry"]["d_A"] - candidate["points"]["B5"]["geometry"]["d_A"],
                0.05 - 1e-12,
            )
            for point in candidate["points"].values():
                self.assertAlmostEqual(sum(point["requested_quotas"].values()), item["total_cpu"])
                self.assertLessEqual(point["orthogonal_coordinate_error"], 0.01 + 1e-12)
                for quota in point["requested_quotas"].values():
                    self.assertAlmostEqual(quota * 100, round(quota * 100))

    def test_point_spec_is_byte_hash_valid(self) -> None:
        spec = point_spec(self.plan, "q1p00-r32-db1p30-a-shipping", "A5", "calibration", 1)
        validate_point_spec(json.loads(json.dumps(spec)))

    def test_fixed_design_is_byte_exact(self) -> None:
        selected = fixed_design_payload(PLAN_PATH, RUNTIME_PATH, "a" * 40)
        self.assertEqual(selected["status"], "fixed")
        verify_selected(json.loads(json.dumps(selected)), PLAN_PATH, RUNTIME_PATH, "a" * 40)

    def test_confirmation_retries_only_invalid_replication(self) -> None:
        selected = {
            "selected_candidate": {"id": "candidate"},
            "confirmation": self.plan["confirmation"],
        }
        state = initial_state(selected, "b" * 64)
        results = []
        for item in wave(state)["matrix"]:
            result = pair("candidate", item["replication_id"], item["attempt_id"], valid=item["replication_id"] != "c003")
            result["selected_design_sha256"] = "b" * 64
            results.append(result)
        ingest(state, results, "123456")
        self.assertEqual(state["pending"], ["c003"])
        self.assertEqual(wave(state)["matrix"], [{"replication_id": "c003", "attempt_id": 2}])

    def test_confirmation_synthesizes_missing_artifact_as_invalid(self) -> None:
        selected = {
            "selected_candidate": {"id": "candidate"},
            "confirmation": self.plan["confirmation"],
        }
        state = initial_state(selected, "b" * 64)
        results = []
        for item in wave(state)["matrix"]:
            if item["replication_id"] == "c003":
                continue
            result = pair("candidate", item["replication_id"], item["attempt_id"])
            result["selected_design_sha256"] = "b" * 64
            results.append(result)
        ingest(state, results, "123456")
        missing = next(item for item in state["attempt_history"] if item["replication_id"] == "c003")
        self.assertEqual(missing["reason_codes"], ["missing_pair_artifact"])
        self.assertEqual(wave(state)["matrix"], [{"replication_id": "c003", "attempt_id": 2}])

    def test_randomization_is_deterministic_and_balanced_enough(self) -> None:
        salt = self.plan["confirmation"]["randomization_salt"]
        replication_ids = confirmation_replication_ids(self.plan["confirmation"])
        self.assertEqual(len(replication_ids), 256)
        self.assertEqual((replication_ids[0], replication_ids[-1]), ("c001", "c256"))
        orders = [randomized_order(salt, replication) for replication in replication_ids]
        self.assertEqual(orders, [randomized_order(salt, replication) for replication in replication_ids])
        self.assertEqual(orders.count(["A5", "B5"]), 128)
        self.assertEqual(orders.count(["B5", "A5"]), 128)

    def test_exact_interval_known_value(self) -> None:
        lower, upper = clopper_pearson(9, 10)
        self.assertAlmostEqual(lower, 0.55498388, places=7)
        self.assertAlmostEqual(upper, 0.99747142, places=7)


if __name__ == "__main__":
    unittest.main()
