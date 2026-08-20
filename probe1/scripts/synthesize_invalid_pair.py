from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from experimentlib import PROTOCOL_VERSION, sha256_file, write_json  # noqa: E402
from lean_design import load_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selected", type=Path, required=True)
    parser.add_argument("--replication-id", required=True)
    parser.add_argument("--attempt-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    selected = load_json(args.selected)
    result = {
        "protocol_version": PROTOCOL_VERSION,
        "phase": "confirmation",
        "candidate_id": selected["selected_candidate"]["id"],
        "replication_id": args.replication_id,
        "attempt_id": args.attempt_id,
        "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        "selected_design_sha256": sha256_file(args.selected),
        "order": [],
        "valid": False,
        "reason_codes": ["workflow_step_failure_before_pair_result"],
        "primary": None,
        "points": {},
    }
    write_json(args.output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
