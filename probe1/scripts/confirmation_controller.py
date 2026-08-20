from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from experimentlib import PROTOCOL_VERSION, sha256_file, write_json
from lean_design import confirmation_replication_ids, load_json, verify_selected


def initial_state(selected: dict[str, Any], selected_sha: str) -> dict[str, Any]:
    replications = confirmation_replication_ids(selected["confirmation"])
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "status": "running",
        "candidate_id": selected["selected_candidate"]["id"],
        "selected_design_sha256": selected_sha,
        "target_replications": len(replications),
        "max_infrastructure_attempts": selected["confirmation"]["max_infrastructure_attempts"],
        "attempts": {replication: 1 for replication in replications},
        "pending": list(replications),
        "valid_results": {},
        "attempt_history": [],
    }


def wave(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "status": state["status"],
        "selected_design_sha256": state["selected_design_sha256"],
        "matrix": [
            {"replication_id": replication, "attempt_id": state["attempts"][replication]}
            for replication in state["pending"]
        ] if state["status"] == "running" else [],
    }


def ingest(state: dict[str, Any], results: list[dict[str, Any]], workflow_run_id: str) -> None:
    if state["status"] != "running":
        raise ValueError("confirmation state is terminal")
    expected = {item["replication_id"]: item for item in wave(state)["matrix"]}
    received: dict[str, dict[str, Any]] = {}
    for result in results:
        replication = result.get("replication_id")
        if replication not in expected or replication in received:
            raise ValueError("confirmation result is unknown or duplicated")
        received[replication] = result
    for replication, item in expected.items():
        if replication not in received:
            received[replication] = {
                "protocol_version": PROTOCOL_VERSION,
                "phase": "confirmation",
                "candidate_id": state["candidate_id"],
                "replication_id": replication,
                "attempt_id": item["attempt_id"],
                "workflow_run_id": workflow_run_id,
                "selected_design_sha256": state["selected_design_sha256"],
                "order": [],
                "valid": False,
                "reason_codes": ["missing_pair_artifact"],
                "primary": None,
                "points": {},
            }
    for replication in state["pending"]:
        result = received[replication]
        item = expected[replication]
        if result.get("protocol_version") != PROTOCOL_VERSION:
            raise ValueError("result protocol version mismatch")
        if result.get("attempt_id") != item["attempt_id"]:
            raise ValueError("result attempt ID mismatch")
        if result.get("candidate_id") != state["candidate_id"]:
            raise ValueError("result candidate mismatch")
        if result.get("selected_design_sha256") != state["selected_design_sha256"]:
            raise ValueError("result selected-design hash mismatch")
        if result.get("workflow_run_id") != workflow_run_id:
            raise ValueError("result workflow-run ID mismatch")
        state["attempt_history"].append(result)
        if result.get("valid") is True:
            state["valid_results"][replication] = result
        elif state["attempts"][replication] < state["max_infrastructure_attempts"]:
            state["attempts"][replication] += 1
        else:
            state["status"] = "infrastructure-failed"
    state["pending"] = [replication for replication in state["pending"] if replication not in state["valid_results"]]
    if state["status"] == "running" and not state["pending"]:
        state["status"] = "complete"


def collect_results(root: Path) -> list[dict[str, Any]]:
    results = []
    for path in sorted(root.rglob("pair-result.json")):
        results.append(load_json(path))
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=Path("probe1/design.json"))
    parser.add_argument("--runtime", type=Path, default=Path("probe1/runtime.json"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init")
    init.add_argument("--selected", type=Path, required=True)
    init.add_argument("--expected-commit", required=True)
    init.add_argument("--state", type=Path, required=True)
    init.add_argument("--wave", type=Path, required=True)
    advance = subparsers.add_parser("ingest")
    advance.add_argument("--state", type=Path, required=True)
    advance.add_argument("--results-root", type=Path, required=True)
    advance.add_argument("--wave", type=Path, required=True)
    advance.add_argument("--workflow-run-id", default=os.getenv("GITHUB_RUN_ID", ""), required=False)
    args = parser.parse_args()
    if args.command == "init":
        selected = load_json(args.selected)
        verify_selected(selected, args.plan, args.runtime, args.expected_commit)
        state = initial_state(selected, sha256_file(args.selected))
    else:
        state = load_json(args.state)
        if not args.workflow_run_id:
            raise ValueError("ingest requires an exact workflow-run ID")
        ingest(state, collect_results(args.results_root), args.workflow_run_id)
    write_json(args.state, state)
    write_json(args.wave, wave(state))
    print(json.dumps({"status": state["status"], "pending_count": len(state["pending"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
