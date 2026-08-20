from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from common import CONTROLLED_SERVICES, load_json, sha256_file, write_json
from summarize import summarize_phase


def run(command: list[str], *, check: bool = True, capture: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command), flush=True)
    return subprocess.run(command, check=check, text=True, capture_output=capture, cwd=cwd)


def load_runtime(repo: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    runtime = load_json(repo / "probe2/runtime.json")
    parent_path = repo / runtime["parent_runtime_lock"]
    if sha256_file(parent_path) != runtime["parent_runtime_lock_sha256"]:
        raise ValueError("parent runtime lock SHA-256 mismatch")
    for path_key, hash_key in (("compose_override", "compose_override_sha256"), ("environment_file", "environment_file_sha256")):
        if sha256_file(repo / runtime[path_key]) != runtime[hash_key]:
            raise ValueError(f"runtime input SHA-256 mismatch: {runtime[path_key]}")
    return runtime, load_json(parent_path)


def verify_runner(runtime: Mapping[str, Any]) -> None:
    if os.getenv("GITHUB_ACTIONS") != "true" or os.name != "posix":
        raise RuntimeError("runtime execution is restricted to Linux GitHub Actions")
    if os.cpu_count() != int(runtime["runner"]["logical_cpus"]):
        raise RuntimeError(f"expected {runtime['runner']['logical_cpus']} logical CPUs, observed {os.cpu_count()}")
    mem_kib = 0
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            mem_kib = int(line.split()[1])
            break
    if mem_kib < int(runtime["runner"]["minimum_memory_gib"]) * 1024 * 1024:
        raise RuntimeError("runner memory is below the frozen minimum")


def pull_images(parent: Mapping[str, Any]) -> None:
    for image in sorted({*parent["images"].values(), parent["workload"]["k6_image"]}):
        run(["docker", "pull", image])


def compose_prefix(repo: Path, upstream: Path, project: str) -> list[str]:
    return [
        "docker", "compose", "--project-name", project, "--project-directory", str(upstream),
        "--env-file", str(upstream / ".env"), "--env-file", str(repo / "probe1/otel.env"),
        "-f", str(upstream / "compose.yaml"), "-f", str(repo / "probe1/compose.lock.yaml"),
    ]


def project_name(spec: Mapping[str, Any]) -> str:
    raw = f"joint-{os.getenv('GITHUB_RUN_ID', 'local')}-{spec['candidate_id']}-{spec['replication_id']}-{spec['condition']}"
    return re.sub(r"[^a-z0-9_-]", "-", raw.lower())[:60]


def inspect(service: str) -> dict[str, Any]:
    return json.loads(run(["docker", "inspect", service]).stdout)[0]


def inspect_all(services: Iterable[str], *, tolerate_missing: bool = False) -> dict[str, Any]:
    result = {}
    for service in services:
        try:
            result[service] = inspect(service)
        except (subprocess.CalledProcessError, json.JSONDecodeError, IndexError):
            if not tolerate_missing:
                raise
            result[service] = {"RestartCount": 0, "State": {"Running": False, "OOMKilled": False, "Status": "missing"}}
    return result


def wait_for_stack(parent: Mapping[str, Any], timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    required = parent["required_running_containers"]
    healthy = set(parent["mandatory_healthy_containers"])
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        ready = True
        for service in required:
            try:
                state = inspect(service)["State"]
                if service in healthy:
                    status = state.get("Health", {}).get("Status", "no-health")
                    ok = state.get("Running") is True and status == "healthy"
                else:
                    status = state.get("Status", "missing")
                    ok = state.get("Running") is True
            except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, IndexError):
                status, ok = "missing", False
            last[service] = status
            ready = ready and ok
        if ready:
            return
        time.sleep(5)
    raise TimeoutError(f"stack health timeout: {last}")


def read_cgroup(service: str, filename: str, inspected: Mapping[str, Any] | None = None) -> str:
    if filename not in {"cpu.max", "cpu.stat"}:
        raise ValueError("unsupported cgroup file")
    data = inspected or inspect(service)
    pid = int(data.get("State", {}).get("Pid", 0))
    if pid <= 0:
        raise RuntimeError(f"{service} has no live PID")
    path = Path("/proc") / str(pid) / "root/sys/fs/cgroup" / filename
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        completed = run(["sudo", "--non-interactive", "cat", str(path)], check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"cannot read {service} {filename}: {completed.stderr.strip()}")
        return completed.stdout.strip()


def apply_quotas(quotas: Mapping[str, float]) -> None:
    if set(quotas) != set(CONTROLLED_SERVICES):
        raise ValueError("quota set differs from controlled services")
    for service in CONTROLLED_SERVICES:
        run(["docker", "update", "--cpus", f"{float(quotas[service]):.9f}", service])


def quota_snapshot(requested: Mapping[str, float]) -> dict[str, Any]:
    effective: dict[str, float] = {}
    cpu_max: dict[str, str] = {}
    nano_cpus: dict[str, int] = {}
    reasons: list[str] = []
    for service in CONTROLLED_SERVICES:
        data = inspect(service)
        nano = int(data["HostConfig"]["NanoCpus"])
        text = read_cgroup(service, "cpu.max", data)
        quota, period = text.split()
        if quota == "max":
            reasons.append(f"{service}:unbounded")
            value = 0.0
        else:
            value = int(quota) / int(period)
        effective[service] = value
        cpu_max[service] = text
        nano_cpus[service] = nano
        expected = float(requested[service])
        if expected <= 0 or abs(value - expected) / expected > 0.01:
            reasons.append(f"{service}:effective_quota_mismatch")
        if abs(nano / 1_000_000_000.0 - value) / expected > 0.01:
            reasons.append(f"{service}:docker_cgroup_disagreement")
    if abs(sum(effective.values()) - 1.0) > 0.01:
        reasons.append("effective_quota_sum_mismatch")
    return {"valid": not reasons, "reason_codes": reasons, "requested": dict(requested), "effective": effective, "cpu_max": cpu_max, "nano_cpus": nano_cpus}


def cpu_stat() -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for service in CONTROLLED_SERVICES:
        values = {}
        for line in read_cgroup(service, "cpu.stat").splitlines():
            key, value = line.split(maxsplit=1)
            values[key] = int(value)
        result[service] = values
    return result


def throttling(before: Mapping[str, Mapping[str, int]], after: Mapping[str, Mapping[str, int]]) -> dict[str, float | None]:
    result = {}
    for service in CONTROLLED_SERVICES:
        periods = after[service].get("nr_periods", 0) - before[service].get("nr_periods", 0)
        count = after[service].get("nr_throttled", 0) - before[service].get("nr_throttled", 0)
        result[service] = count / periods if periods > 0 else None
    return result


def failures(before: Mapping[str, Any], after: Mapping[str, Any], services: Iterable[str]) -> tuple[bool, dict[str, Any]]:
    details = {}
    for service in services:
        prior, current = before[service], after[service]
        restart_delta = int(current.get("RestartCount", 0)) - int(prior.get("RestartCount", 0))
        state = current.get("State", {})
        failed = restart_delta > 0 or state.get("OOMKilled") is True or state.get("Running") is not True
        details[service] = {"restart_delta": restart_delta, "oom_killed": state.get("OOMKilled", False), "running": state.get("Running", False), "failed": failed}
    return any(item["failed"] for item in details.values()), details


def run_k6(repo: Path, parent: Mapping[str, Any], runtime: Mapping[str, Any], spec: Mapping[str, Any], phase: str, seconds: int, output: Path, *, primary: bool) -> None:
    output.mkdir(parents=True, exist_ok=True)
    workload = runtime["workload"]
    scenario = {
        "rate": spec["rate"], "duration_seconds": seconds, "timeUnit": workload["time_unit"],
        "preAllocatedVUs": workload["pre_allocated_vus"], "maxVUs": workload["max_vus"],
        "gracefulStop_seconds": workload["graceful_stop_seconds"], "http_timeout_seconds": workload["http_timeout_seconds"],
        "phase": phase, "trial_id": spec["trial_id"], "condition": spec["condition"],
    }
    write_json(output / "scenario-config.json", scenario)
    uid, gid = run(["id", "-u"]).stdout.strip(), run(["id", "-g"]).stdout.strip()
    command = [
        "docker", "run", "--rm", "--user", f"{uid}:{gid}", "--network", "opentelemetry-demo",
        "-v", f"{output.resolve()}:/artifacts", "-v", f"{(repo / 'probe2/k6/checkout.js').resolve()}:/scripts/checkout.js:ro",
        "-e", f"RATE={spec['rate']}", "-e", f"DURATION_SECONDS={seconds}",
        "-e", f"VUS={workload['pre_allocated_vus']}", "-e", f"HTTP_TIMEOUT_SECONDS={workload['http_timeout_seconds']}",
        "-e", f"PHASE={phase}", "-e", f"TRIAL_ID={spec['trial_id']}", "-e", f"CONDITION={spec['condition']}",
        "-e", "TARGET_URL=http://frontend-proxy:8080", "-e", "SUMMARY_PATH=/artifacts/summary.json",
        parent["workload"]["k6_image"], "run",
    ]
    if primary:
        command.extend(["--out", "json=/artifacts/raw-metrics.jsonl"])
    command.append("/scripts/checkout.js")
    started = dt.datetime.now(dt.timezone.utc)
    completed = run(command, check=False)
    ended = dt.datetime.now(dt.timezone.utc)
    (output / "stdout.log").write_text(completed.stdout, encoding="utf-8", newline="\n")
    (output / "stderr.log").write_text(completed.stderr, encoding="utf-8", newline="\n")
    write_json(output / "run-status.json", {"exit_code": completed.returncode, "completed": completed.returncode == 0, "started_at": started.isoformat(), "ended_at": ended.isoformat()})


def summarize_primary(runtime: Mapping[str, Any], spec: Mapping[str, Any], phase_dir: Path, seconds: int) -> dict[str, Any]:
    workload = runtime["workload"]
    return summarize_phase(
        phase_dir, rate=int(spec["rate"]), duration_seconds=seconds,
        expected_vus=int(workload["pre_allocated_vus"]), slo_p95_ms=float(workload["slo_p95_ms"]),
        slo_error_rate=float(workload["slo_error_rate"]),
    )
