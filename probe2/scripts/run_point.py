from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from common import CONTROLLED_SERVICES, PROTOCOL_VERSION, canonical_json, group_balance, load_json, write_json
from runtime import (
    apply_quotas, compose_prefix, cpu_stat, failures, inspect_all, load_runtime, project_name,
    quota_snapshot, run, run_k6, summarize_primary, throttling, wait_for_stack,
)


def validate_spec(spec: dict[str, Any]) -> None:
    if spec.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("point protocol version mismatch")
    provided = spec.get("spec_sha256")
    unsigned = {key: value for key, value in spec.items() if key != "spec_sha256"}
    if provided != hashlib.sha256(canonical_json(unsigned).encode("utf-8")).hexdigest():
        raise ValueError("point specification SHA-256 mismatch")
    if set(spec.get("baseline_quotas", {})) != set(CONTROLLED_SERVICES) or set(spec.get("test_quotas", {})) != set(CONTROLLED_SERVICES):
        raise ValueError("point quota services mismatch")
    for field in ("baseline_quotas", "test_quotas"):
        values = [float(value) for value in spec[field].values()]
        if min(values) <= 0 or abs(sum(values) - 1.0) > 1e-9:
            raise ValueError(f"{field} is not a positive closed allocation")
    if spec.get("rate") not in (32, 40):
        raise ValueError("point rate is outside the frozen pilot grid")


def execute(repo: Path, upstream: Path, spec_path: Path, artifact_dir: Path) -> dict[str, Any]:
    runtime, parent = load_runtime(repo)
    spec = load_json(spec_path)
    validate_spec(spec)
    spec["trial_id"] = f"{spec['candidate_id']}-{spec['replication_id']}-{spec['condition']}"
    artifact_dir.mkdir(parents=True, exist_ok=False)
    write_json(artifact_dir / "point-spec.json", spec)
    prefix = compose_prefix(repo, upstream, project_name(spec))
    result: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION, "candidate_id": spec["candidate_id"], "condition": spec["condition"],
        "replication_id": spec["replication_id"], "spec_sha256": spec["spec_sha256"],
        "provenance": {"repository_commit": os.getenv("GITHUB_SHA"), "workflow_run_id": os.getenv("GITHUB_RUN_ID"), "runner_name": os.getenv("RUNNER_NAME"), "runner_image": os.getenv("ImageOS"), "runner_image_version": os.getenv("ImageVersion")},
        "valid": False, "reason_codes": [],
    }
    try:
        run([*prefix, "down", "--volumes", "--remove-orphans"], check=False)
        run([*prefix, "up", "--detach", "--no-build", "--pull", "never"])
        wait_for_stack(parent, int(parent["workload"]["health_check_timeout_seconds"]))
        initial = inspect_all(parent["required_running_containers"])

        apply_quotas(spec["baseline_quotas"])
        baseline_quota = quota_snapshot(spec["baseline_quotas"])
        run_k6(repo, parent, runtime, spec, "warmup", int(runtime["workload"]["warmup_seconds"]), artifact_dir / "k6/warmup", primary=False)
        run_k6(repo, parent, runtime, spec, "baseline", int(runtime["workload"]["baseline_seconds"]), artifact_dir / "k6/baseline", primary=True)
        baseline = summarize_primary(runtime, spec, artifact_dir / "k6/baseline", int(runtime["workload"]["baseline_seconds"]))
        before = inspect_all(parent["required_running_containers"])
        pre_failure, pre_details = failures(initial, before, parent["system_under_test_containers"])
        pre_reasons = list(baseline_quota["reason_codes"])
        if not baseline["safe"]:
            pre_reasons.append("baseline_slo_unsafe")
        if baseline["started_fraction"] < float(runtime["workload"]["minimum_started_fraction"]):
            pre_reasons.append("baseline_started_below_99_percent")
        if baseline["k6_exit_code"] != 0:
            pre_reasons.append("baseline_k6_nonzero_exit")
        if pre_failure:
            pre_reasons.append("pre_intervention_restart_or_oom")
        if pre_reasons:
            result.update({"reason_codes": pre_reasons, "baseline": baseline, "test": None, "baseline_quota": baseline_quota, "manipulation": None, "diagnostics": {"pre_intervention_containers": pre_details}})
            return result

        apply_quotas(spec["test_quotas"])
        manipulation = quota_snapshot(spec["test_quotas"])
        observed_balance = group_balance(manipulation["effective"])
        if abs(observed_balance - float(spec["geometry"]["test_balance"])) > 0.01:
            manipulation["valid"] = False
            manipulation["reason_codes"].append("effective_balance_mismatch")
        stat_before = cpu_stat()
        run_k6(repo, parent, runtime, spec, "stabilization", int(runtime["workload"]["stabilization_seconds"]), artifact_dir / "k6/stabilization", primary=False)
        run_k6(repo, parent, runtime, spec, "test", int(runtime["workload"]["test_seconds"]), artifact_dir / "k6/test", primary=True)
        stat_after = cpu_stat()
        test = summarize_primary(runtime, spec, artifact_dir / "k6/test", int(runtime["workload"]["test_seconds"]))
        after = inspect_all(parent["required_running_containers"], tolerate_missing=True)
        post_failure, post_details = failures(before, after, parent["system_under_test_containers"])
        reasons = list(manipulation["reason_codes"])
        if test["started_fraction"] < float(runtime["workload"]["minimum_started_fraction"]):
            reasons.append("test_started_below_99_percent")
        if test["k6_exit_code"] != 0:
            reasons.append("test_k6_nonzero_exit")
        result.update({
            "valid": not reasons, "reason_codes": reasons, "baseline": baseline, "test": test,
            "baseline_quota": baseline_quota,
            "manipulation": {**manipulation, "effective_balance": observed_balance},
            "diagnostics": {"post_intervention_system_failure": post_failure, "containers": post_details, "throttling_fraction": throttling(stat_before, stat_after)},
        })
        return result
    finally:
        if artifact_dir.exists():
            try:
                logs = run([*prefix, "logs", "--no-color", "--timestamps", "--tail", str(runtime["evidence"]["diagnostic_log_tail_lines"])], check=False)
                (artifact_dir / "compose.log").write_text(logs.stdout + logs.stderr, encoding="utf-8", newline="\n")
            except Exception as exc:
                (artifact_dir / "diagnostics-error.txt").write_text(repr(exc), encoding="utf-8")
        run([*prefix, "down", "--volumes", "--remove-orphans"], check=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--upstream-dir", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = execute(args.repo.resolve(), args.upstream_dir.resolve(), args.spec.resolve(), args.artifact_dir.resolve())
    except Exception as exc:
        args.artifact_dir.mkdir(parents=True, exist_ok=True)
        result = {"protocol_version": PROTOCOL_VERSION, "valid": False, "reason_codes": ["harness_exception"], "exception": repr(exc)}
    write_json(args.artifact_dir / "point-result.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
