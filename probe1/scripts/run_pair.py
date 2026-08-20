from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from experimentlib import PROTOCOL_VERSION, sha256_file, write_json
from lean_design import confirmation_replication_ids, load_json, point_spec, validate_plan, verify_selected


def randomized_order(salt: str, replication_id: str) -> list[str]:
    replication_ids = [f"c{index:03d}" for index in range(1, 257)]
    if replication_id not in replication_ids:
        raise ValueError("randomization requires replication ID c001..c256")
    ranked = sorted(
        replication_ids,
        key=lambda item: (hashlib.sha256(f"{salt}:{item}".encode("utf-8")).digest(), item),
    )
    return ["A5", "B5"] if ranked.index(replication_id) < 128 else ["B5", "A5"]


def execute(args: argparse.Namespace) -> dict[str, Any]:
    plan = load_json(args.plan)
    validate_plan(plan)
    selected_sha = None
    if args.phase == "calibration":
        candidate_id = args.candidate_id
        if args.replication_id != "calibration" or args.attempt_id != 1:
            raise ValueError("calibration must use replication_id=calibration and attempt_id=1")
        order = ["A5", "B5"]
    else:
        if args.selected is None:
            raise ValueError("confirmation requires --selected")
        selected = load_json(args.selected)
        verify_selected(selected, args.plan, args.runtime, args.expected_commit)
        candidate_id = selected["selected_candidate"]["id"]
        selected_sha = sha256_file(args.selected)
        confirmation = selected["confirmation"]
        if args.replication_id not in confirmation_replication_ids(confirmation):
            raise ValueError("invalid confirmation replication ID")
        if not 1 <= args.attempt_id <= confirmation["max_infrastructure_attempts"]:
            raise ValueError("invalid confirmation attempt ID")
        order = randomized_order(confirmation["randomization_salt"], args.replication_id)

    output = args.artifact_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    specs = output / "point-specs"
    specs.mkdir()
    write_json(output / "order.json", {"phase": args.phase, "order": order})
    results: dict[str, Any] = {}
    reasons: list[str] = []
    for point_id in order:
        spec_path = specs / f"{point_id}.json"
        write_json(spec_path, point_spec(plan, candidate_id, point_id, args.replication_id, args.attempt_id))
        point_output = output / "points" / point_id
        completed = subprocess.run(
            [
                sys.executable,
                str(args.repo / "probe1/scripts/run_trial.py"),
                "--repo", str(args.repo),
                "--upstream-dir", str(args.upstream_dir),
                "--manifest", str(args.runtime),
                "--point-spec", str(spec_path),
                "--artifact-dir", str(point_output),
            ],
            check=False,
        )
        result_path = point_output / "trial-result.json"
        if completed.returncode != 0 or not result_path.is_file():
            reasons.append(f"{point_id}:missing_trial_result")
            break
        result = load_json(result_path)
        results[point_id] = result
        if result.get("validity", {}).get("valid") is not True or result.get("manipulation", {}).get("valid") is not True:
            codes = result.get("validity", {}).get("reason_codes", ["unknown_invalidity"])
            reasons.extend(f"{point_id}:{code}" for code in codes)
            break
    valid = not reasons and set(results) == {"A5", "B5"}
    primary = None
    if valid:
        a_safe = results["A5"]["test"]["safe"] is True
        b_safe = results["B5"]["test"]["safe"] is True
        primary = {"a5_safe": a_safe, "b5_safe": b_safe, "y": int(a_safe and not b_safe)}
    return {
        "protocol_version": PROTOCOL_VERSION,
        "phase": args.phase,
        "candidate_id": candidate_id,
        "replication_id": args.replication_id,
        "attempt_id": args.attempt_id,
        "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        "selected_design_sha256": selected_sha,
        "order": order,
        "valid": valid,
        "reason_codes": reasons,
        "primary": primary,
        "points": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--upstream-dir", type=Path, required=True)
    parser.add_argument("--plan", type=Path, default=Path("probe1/design.json"))
    parser.add_argument("--runtime", type=Path, default=Path("probe1/runtime.json"))
    parser.add_argument("--phase", choices=("calibration", "confirmation"), required=True)
    parser.add_argument("--candidate-id")
    parser.add_argument("--selected", type=Path)
    parser.add_argument("--expected-commit", default="")
    parser.add_argument("--replication-id", required=True)
    parser.add_argument("--attempt-id", type=int, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()
    args.repo = args.repo.resolve()
    args.upstream_dir = args.upstream_dir.resolve()
    args.plan = args.plan if args.plan.is_absolute() else args.repo / args.plan
    args.runtime = args.runtime if args.runtime.is_absolute() else args.repo / args.runtime
    if args.selected and not args.selected.is_absolute():
        args.selected = args.repo / args.selected
    try:
        result = execute(args)
    except Exception as exc:
        args.artifact_dir.mkdir(parents=True, exist_ok=True)
        fallback_candidate_id = args.candidate_id
        if args.phase == "confirmation" and args.selected and args.selected.is_file():
            try:
                fallback_candidate_id = load_json(args.selected)["selected_candidate"]["id"]
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                pass
        result = {
            "protocol_version": PROTOCOL_VERSION,
            "phase": args.phase,
            "candidate_id": fallback_candidate_id,
            "replication_id": args.replication_id,
            "attempt_id": args.attempt_id,
            "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
            "selected_design_sha256": sha256_file(args.selected) if args.selected and args.selected.is_file() else None,
            "order": [],
            "valid": False,
            "reason_codes": ["pair_harness_exception"],
            "exception": repr(exc),
            "primary": None,
            "points": {},
        }
    write_json(args.artifact_dir / "pair-result.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
