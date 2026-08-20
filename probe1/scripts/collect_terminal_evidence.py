from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from experimentlib import write_json


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def collect(state_path: Path, downloads: Path, output: Path, terminal_run_id: str) -> dict[str, Any]:
    state = load_json(state_path)
    if state.get("status") != "complete" or state.get("target_replications") != 256:
        raise ValueError("controller state is not the complete 256-replication state")
    valid_results = state.get("valid_results", {})
    history = state.get("attempt_history", [])
    if not isinstance(valid_results, dict) or len(valid_results) != 256 or not isinstance(history, list):
        raise ValueError("controller state result counts differ from the frozen design")

    keys: set[tuple[str, int]] = set()
    selected_artifacts: list[dict[str, Any]] = []
    expected_missing: list[dict[str, Any]] = []
    used_directories: set[Path] = set()
    output.mkdir(parents=True, exist_ok=False)

    for attempt in history:
        replication = attempt.get("replication_id")
        attempt_id = attempt.get("attempt_id")
        workflow_run_id = str(attempt.get("workflow_run_id", ""))
        key = (replication, attempt_id)
        if not isinstance(replication, str) or not isinstance(attempt_id, int) or key in keys:
            raise ValueError("attempt history contains an invalid or duplicate attempt key")
        keys.add(key)
        artifact_name = f"confirmation-{replication}-a{attempt_id}"
        artifact_dir = downloads / workflow_run_id / artifact_name
        reasons = attempt.get("reason_codes", [])
        if reasons == ["missing_pair_artifact"]:
            expected_missing.append({
                "replication_id": replication,
                "attempt_id": attempt_id,
                "workflow_run_id": workflow_run_id,
                "artifact_present_after_terminal_state": artifact_dir.is_dir(),
            })
            continue
        if not artifact_dir.is_dir():
            raise ValueError(f"missing attempt artifact: {workflow_run_id}/{artifact_name}")
        pair_results = list(artifact_dir.rglob("pair-result.json"))
        evidence_archives = list(artifact_dir.rglob("evidence.tar.gz"))
        if len(pair_results) != 1 or len(evidence_archives) != 1:
            raise ValueError(f"artifact contract differs: {workflow_run_id}/{artifact_name}")
        if load_json(pair_results[0]) != attempt:
            raise ValueError(f"artifact result differs from controller state: {workflow_run_id}/{artifact_name}")
        if evidence_archives[0].stat().st_size > 500_000:
            raise ValueError(f"evidence archive exceeds the frozen bound: {workflow_run_id}/{artifact_name}")
        destination = output / workflow_run_id / artifact_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(artifact_dir, destination)
        used_directories.add(artifact_dir.resolve())
        selected_artifacts.append({
            "replication_id": replication,
            "attempt_id": attempt_id,
            "workflow_run_id": workflow_run_id,
            "artifact_name": artifact_name,
            "pair_result_sha256": file_sha256(pair_results[0]),
            "evidence_sha256": file_sha256(evidence_archives[0]),
            "evidence_bytes": evidence_archives[0].stat().st_size,
        })

    for replication, result in valid_results.items():
        matches = [attempt for attempt in history if attempt.get("replication_id") == replication and attempt.get("valid") is True]
        if len(matches) != 1 or matches[0] != result:
            raise ValueError(f"valid result is not uniquely represented in attempt history: {replication}")

    downloaded_directories = {
        path.resolve()
        for run_dir in downloads.iterdir()
        if run_dir.is_dir()
        for path in run_dir.glob("confirmation-*-a*")
        if path.is_dir()
    }
    ignored = sorted(path.relative_to(downloads.resolve()).as_posix() for path in downloaded_directories - used_directories)
    manifest = {
        "schema_version": 1,
        "protocol_version": state.get("protocol_version"),
        "terminal_controller_run_id": terminal_run_id,
        "terminal_state_sha256": file_sha256(state_path),
        "terminal_status": state["status"],
        "valid_replications": len(valid_results),
        "attempt_history_count": len(history),
        "selected_artifact_count": len(selected_artifacts),
        "expected_missing_artifacts": expected_missing,
        "ignored_post_terminal_or_unreferenced_artifacts": ignored,
        "selected_artifacts": selected_artifacts,
    }
    write_json(output / "evidence-selection.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--downloads", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--terminal-run-id", required=True)
    args = parser.parse_args()
    manifest = collect(args.state, args.downloads, args.output, args.terminal_run_id)
    print(json.dumps({
        "valid_replications": manifest["valid_replications"],
        "attempts": manifest["attempt_history_count"],
        "artifacts": manifest["selected_artifact_count"],
        "ignored": len(manifest["ignored_post_terminal_or_unreferenced_artifacts"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
