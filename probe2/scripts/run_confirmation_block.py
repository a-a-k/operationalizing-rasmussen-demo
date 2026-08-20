from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from common import PROTOCOL_VERSION, load_json, point_spec, write_json
from confirmation_common import STUDY_PROTOCOL_VERSION, confirmation_matrix, load_confirmation_design
from runtime import load_runtime, pull_images, verify_runner


def execute(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repo.resolve()
    design = load_confirmation_design(repo)
    expected_rows = {row["block_id"]: row for row in confirmation_matrix(design)}
    if args.block_id not in expected_rows:
        raise ValueError("block ID is outside the frozen confirmation matrix")
    expected = expected_rows[args.block_id]
    if args.order_id != expected["order_id"]:
        raise ValueError("order ID differs from the frozen matrix")
    runtime, parent = load_runtime(repo)
    verify_runner(runtime)
    output = args.artifact_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    pull_images(parent)
    order = design["condition_orders"][args.order_id]
    write_json(output / "order.json", {
        "study_protocol_version": STUDY_PROTOCOL_VERSION,
        "block_id": args.block_id,
        "order_id": args.order_id,
        "order": order,
    })
    candidate = design["selected_candidate"]
    results = {}
    for condition in order:
        spec = point_spec(
            int(candidate["rate"]), float(candidate["critical_quota"]), condition, args.block_id
        )
        spec_path = output / "specs" / f"{condition}.json"
        write_json(spec_path, spec)
        point_dir = output / "points" / condition
        completed = subprocess.run([
            sys.executable,
            str(repo / "probe2/scripts/run_point.py"),
            "--repo", str(repo),
            "--upstream-dir", str(args.upstream_dir.resolve()),
            "--spec", str(spec_path),
            "--artifact-dir", str(point_dir),
        ], check=False)
        result_path = point_dir / "point-result.json"
        if completed.returncode != 0 or not result_path.is_file():
            results[condition] = {
                "protocol_version": PROTOCOL_VERSION,
                "valid": False,
                "reason_codes": ["missing_point_result"],
                "return_code": completed.returncode,
            }
        else:
            results[condition] = load_json(result_path)
    complete = set(results) == set(order)
    valid = complete and all(result.get("valid") is True for result in results.values())
    return {
        "study_protocol_version": STUDY_PROTOCOL_VERSION,
        "measurement_protocol_version": PROTOCOL_VERSION,
        "block_id": args.block_id,
        "block_number": expected["block_number"],
        "order_id": args.order_id,
        "order": order,
        "candidate_id": candidate["candidate_id"],
        "provenance": {
            "repository_commit": os.getenv("GITHUB_SHA"),
            "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
            "runner_name": os.getenv("RUNNER_NAME"),
        },
        "complete": complete,
        "valid": valid,
        "points": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--upstream-dir", type=Path, required=True)
    parser.add_argument("--block-id", required=True)
    parser.add_argument("--order-id", required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = execute(args)
    except Exception as exc:
        args.artifact_dir.mkdir(parents=True, exist_ok=True)
        result = {
            "study_protocol_version": STUDY_PROTOCOL_VERSION,
            "block_id": args.block_id,
            "block_number": int(args.block_id[1:]) if args.block_id.startswith("c") and args.block_id[1:].isdigit() else None,
            "order_id": args.order_id,
            "candidate_id": "r40-s019",
            "provenance": {
                "repository_commit": os.getenv("GITHUB_SHA"),
                "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
                "runner_name": os.getenv("RUNNER_NAME"),
            },
            "complete": False,
            "valid": False,
            "reason_codes": ["confirmation_block_harness_exception"],
            "exception": repr(exc),
            "points": {},
        }
    write_json(args.artifact_dir / "confirmation-block-result.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
