from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
from pathlib import Path

from experimentlib import SERVICES, write_json
from run_trial import (
    apply_quotas,
    compose_prefix,
    cpu_stat,
    inspect_all,
    quota_snapshot,
    run,
    run_k6,
    wait_for_stack,
)
from summarize_k6 import summarize_phase
from verify_runtime import load_manifest


def memory_gib() -> float:
    with open("/proc/meminfo", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / (1024 * 1024)
    raise RuntimeError("MemTotal missing")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--upstream-dir", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != "Linux" or not os.getenv("GITHUB_ACTIONS"):
        raise SystemExit("runtime smoke is restricted to GitHub Actions Linux runners")

    repo, upstream, output = args.repo.resolve(), args.upstream_dir.resolve(), args.artifact_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest = load_manifest(repo / "probe1/runtime.json")
    cpus, memory = os.cpu_count(), memory_gib()
    if cpus != manifest["runner"]["logical_cpus"] or memory < manifest["runner"]["minimum_memory_gib"]:
        raise RuntimeError(f"runner class mismatch: cpus={cpus}, memory_gib={memory:.3f}")

    project = f"rasmussen-smoke-{os.environ['GITHUB_RUN_ID']}"
    prefix = compose_prefix(repo, upstream, project)
    evidence: dict[str, object] = {"runner": {"cpus": cpus, "memory_gib": memory}}
    try:
        run([*prefix, "down", "--volumes", "--remove-orphans"], check=False)
        for image in [*manifest["images"].values(), manifest["workload"]["k6_image"]]:
            run(["docker", "pull", image])
        run([*prefix, "up", "--detach", "--no-build", "--pull", "never"])
        wait_for_stack(manifest, manifest["workload"]["health_check_timeout_seconds"])
        apply_quotas({service: 0.5 for service in SERVICES})
        quota_evidence = quota_snapshot({service: 0.5 for service in SERVICES}, 1.5)
        if not quota_evidence["valid"]:
            raise RuntimeError(f"host-side cgroup quota smoke failed: {quota_evidence}")
        evidence["quota_snapshot"] = quota_evidence
        evidence["cpu_stat"] = cpu_stat(SERVICES)
        inspections = inspect_all(manifest["required_running_containers"])
        image_ids = {service: value["Image"] for service, value in inspections.items()}
        evidence["container_image_ids"] = image_ids

        spec = {
            "trial_id": "runtime-smoke", "point_id": "runtime-smoke", "rate": 1,
            "duration_seconds": 10,
        }
        run_k6(
            repo, manifest, spec, "smoke", 10, output / "k6" / "smoke",
            record_primary_observations=True,
        )
        summary = summarize_phase(output / "k6" / "smoke", 1, 10)
        evidence["k6_smoke"] = summary
        evidence["ok"] = summary["k6_exit_code"] == 0 and summary["checkout_requests"] > 0
        write_json(output / "runtime-evidence.json", evidence)
        if not evidence["ok"]:
            raise RuntimeError(f"k6 smoke failed: {summary}")
    finally:
        logs = run([
            *prefix, "logs", "--no-color", "--timestamps", "--tail",
            str(manifest["diagnostic_log_tail_lines"]),
        ], check=False)
        (output / "compose.log").write_text(logs.stdout + logs.stderr, encoding="utf-8", newline="\n")
        run([*prefix, "down", "--volumes", "--remove-orphans"], check=False)
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
