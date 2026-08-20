from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import sha256_file, write_json
from confirmation_common import confirmation_matrix, load_confirmation_design
from runtime import load_runtime, verify_runner


FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def verify(repo: Path, *, check_runner: bool) -> dict[str, object]:
    errors = []
    design_hash = None
    runtime_hash = None
    expected_actions = {}
    try:
        design = load_confirmation_design(repo)
        matrix = confirmation_matrix(design)
        if len(matrix) != 32 or len({row["block_id"] for row in matrix}) != 32:
            errors.append("confirmation matrix is not exactly 32 unique blocks")
        counts = {order_id: sum(row["order_id"] == order_id for row in matrix) for order_id in design["condition_orders"]}
        if set(counts.values()) != {8}:
            errors.append("confirmation orders are not balanced 8 times each")
        design_hash = sha256_file(repo / "probe2/design.json")
    except Exception as exc:
        errors.append(f"confirmation design verification failed: {exc!r}")
    try:
        runtime, parent = load_runtime(repo)
        runtime_hash = sha256_file(repo / "probe2/runtime.json")
        expected_actions = parent["github_actions"]
        if check_runner:
            verify_runner(runtime)
    except Exception as exc:
        errors.append(f"runtime verification failed: {exc!r}")
    workflow = repo / ".github/workflows/probe2.yml"
    if not workflow.is_file():
        errors.append("joint allocation confirmation workflow is missing")
    else:
        for number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("uses:"):
                value = stripped.removeprefix("uses:").strip().strip("'\"")
                action, separator, reference = value.rpartition("@")
                if not separator or not FULL_SHA.fullmatch(reference):
                    errors.append(f"workflow uses mutable action reference at line {number}")
                elif action in expected_actions and reference != expected_actions[action]:
                    errors.append(f"workflow action differs from runtime lock at line {number}: {action}")
    return {
        "valid": not errors,
        "errors": errors,
        "design_sha256": design_hash,
        "measurement_runtime_sha256": runtime_hash,
        "attempted_blocks": 32,
        "point_trials": 128,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--check-runner", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = verify(args.repo.resolve(), check_runner=args.check_runner)
    if args.report:
        write_json(args.report, report)
    if not report["valid"]:
        for error in report["errors"]:
            print(error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
