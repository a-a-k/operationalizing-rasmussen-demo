from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

from experimentlib import PROTOCOL_VERSION, SERVICES, canonical_json, ilr, sha256_file, write_json
from summarize_k6 import summarize_phase
from verify_runtime import load_manifest


def run(command: list[str], *, check: bool = True, capture: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command), flush=True)
    return subprocess.run(command, check=check, text=True, capture_output=capture, cwd=cwd)


def compose_prefix(repo: Path, upstream: Path, project: str) -> list[str]:
    return [
        "docker", "compose", "--project-name", project, "--project-directory", str(upstream),
        "--env-file", str(upstream / ".env"), "--env-file", str(repo / "probe1" / "otel.env"),
        "-f", str(upstream / "compose.yaml"), "-f", str(repo / "probe1" / "compose.lock.yaml"),
    ]


def validate_point_spec(spec: dict[str, Any]) -> None:
    required = {
        "protocol_version", "environment_id", "stage_id", "point_id", "replication_id", "attempt_id",
        "total_cpu", "rate", "duration_seconds", "baseline_composition", "test_composition",
        "baseline_quotas", "test_quotas", "geometry",
    }
    missing = sorted(required - set(spec))
    if missing:
        raise ValueError(f"point spec missing keys: {missing}")
    if spec["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError("point spec protocol version mismatch")
    allowed_replications = {"calibration", *(f"c{i:03d}" for i in range(1, 257))}
    if spec["replication_id"] not in allowed_replications:
        raise ValueError("invalid replication_id")
    if spec["attempt_id"] not in (1, 2, 3):
        raise ValueError("attempt_id must be 1..3")
    provided_hash = spec.get("spec_sha256")
    unsigned = {key: value for key, value in spec.items() if key != "spec_sha256"}
    calculated_hash = hashlib.sha256(canonical_json(unsigned).encode("utf-8")).hexdigest()
    if provided_hash != calculated_hash:
        raise ValueError("point spec SHA-256 mismatch")
    if spec["rate"] not in (8, 16, 32):
        raise ValueError("invalid frozen rate")
    for field in ("baseline_composition", "test_composition", "baseline_quotas", "test_quotas"):
        if set(spec[field]) != set(SERVICES):
            raise ValueError(f"{field} must contain checkout/payment/shipping")
    for field in ("baseline_composition", "test_composition"):
        if abs(sum(float(value) for value in spec[field].values()) - 1.0) > 1e-9:
            raise ValueError(f"{field} does not sum to one")
    for field in ("baseline_quotas", "test_quotas"):
        values = [float(value) for value in spec[field].values()]
        if min(values) < 0.05 or abs(sum(values) - float(spec["total_cpu"])) > 1e-9:
            raise ValueError(f"{field} violates quota constraints")
        if any(abs(value * 100 - round(value * 100)) > 1e-9 for value in values):
            raise ValueError(f"{field} is not aligned to the 0.01 CPU quota grid")


def sanitized_project(spec: dict[str, Any]) -> str:
    raw = f"rasmussen-{os.getenv('GITHUB_RUN_ID', 'local')}-{spec['point_id']}-{spec['replication_id']}-a{spec['attempt_id']}"
    return re.sub(r"[^a-z0-9_-]", "-", raw.lower())[:60]


def inspect_container(service: str) -> dict[str, Any]:
    completed = run(["docker", "inspect", service])
    return json.loads(completed.stdout)[0]


def inspect_all(services: Iterable[str], *, tolerate_missing: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for service in services:
        try:
            result[service] = inspect_container(service)
        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
            if not tolerate_missing:
                raise
            result[service] = {
                "RestartCount": 0,
                "State": {"Running": False, "OOMKilled": False, "Status": "missing"},
                "diagnostic_error": "container_inspect_unavailable",
            }
    return result


def read_container_cgroup_file(
    service: str,
    filename: str,
    *,
    inspected: dict[str, Any] | None = None,
    proc_root: Path = Path("/proc"),
    cgroup_root: Path = Path("/sys/fs/cgroup"),
) -> tuple[str, str]:
    if filename not in {"cpu.max", "cpu.stat"}:
        raise ValueError(f"unsupported cgroup file: {filename}")
    container = inspected or inspect_container(service)
    pid = int(container.get("State", {}).get("Pid", 0))
    if pid <= 0:
        raise RuntimeError(f"{service}: container has no live host PID")

    process_root_path = proc_root / str(pid) / "root" / "sys" / "fs" / "cgroup" / filename
    candidates = [process_root_path]
    cgroup_membership = proc_root / str(pid) / "cgroup"
    try:
        for line in cgroup_membership.read_text(encoding="utf-8").splitlines():
            hierarchy, controllers, relative = line.split(":", 2)
            if hierarchy == "0" and controllers == "" and relative != "/":
                candidates.append(cgroup_root / relative.lstrip("/") / filename)
                break
    except (OSError, ValueError):
        pass

    failures: list[str] = []
    for path in candidates:
        try:
            return path.read_text(encoding="utf-8").strip(), str(path)
        except OSError as exc:
            direct_failure = str(exc)
        elevated = run(["sudo", "--non-interactive", "cat", str(path)], check=False)
        if elevated.returncode == 0:
            return elevated.stdout.strip(), f"sudo:{path}"
        failures.append(f"{path}:direct={direct_failure};sudo={elevated.stderr.strip()}")
    raise RuntimeError(f"{service}: cannot read {filename} through host cgroup paths: {'; '.join(failures)}")


def wait_for_stack(manifest: dict[str, Any], timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    required = manifest["required_running_containers"]
    healthy = set(manifest["mandatory_healthy_containers"])
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        ready = True
        for service in required:
            try:
                state = inspect_container(service)["State"]
                status = state.get("Status", "missing")
                if service in healthy:
                    status += "/" + state.get("Health", {}).get("Status", "no-health")
                    ok = state.get("Running") is True and state.get("Health", {}).get("Status") == "healthy"
                else:
                    ok = state.get("Running") is True
            except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
                status, ok = "missing", False
            last[service] = status
            ready = ready and ok
        if ready:
            return
        time.sleep(5)
    raise TimeoutError(f"stack health timeout: {last}")


def apply_quotas(requested: dict[str, float]) -> None:
    for service in SERVICES:
        run(["docker", "update", "--cpus", f"{requested[service]:.9f}", service])


def quota_snapshot(requested: dict[str, float], total_cpu: float) -> dict[str, Any]:
    effective: dict[str, float] = {}
    cpu_max: dict[str, str] = {}
    cpu_max_source: dict[str, str] = {}
    host_config_nano_cpus: dict[str, int] = {}
    errors: list[str] = []
    for service in SERVICES:
        inspected = inspect_container(service)
        nano = int(inspected["HostConfig"]["NanoCpus"])
        host_config_nano_cpus[service] = nano
        cpu_max[service], cpu_max_source[service] = read_container_cgroup_file(
            service, "cpu.max", inspected=inspected
        )
        quota_text, period_text = cpu_max[service].split()
        if quota_text == "max":
            errors.append(f"{service}:cpu_max_is_unbounded")
            effective[service] = 0.0
            continue
        effective[service] = int(quota_text) / int(period_text)
        relative = abs(effective[service] - requested[service]) / requested[service]
        if relative > 0.01:
            errors.append(f"{service}:relative_quota_error={relative}")
        if effective[service] < 0.05:
            errors.append(f"{service}:effective_quota_below_0.05={effective[service]}")
        nano_effective = nano / 1_000_000_000.0
        if abs(nano_effective - effective[service]) / requested[service] > 0.01:
            errors.append(f"{service}:hostconfig_cgroup_disagreement")
    sum_relative = abs(sum(effective.values()) - total_cpu) / total_cpu
    if sum_relative > 0.01:
        errors.append(f"quota_sum_relative_error={sum_relative}")
    return {
        "valid": not errors,
        "reason_codes": errors,
        "requested": requested,
        "effective": effective,
        "cpu_max": cpu_max,
        "cpu_max_source": cpu_max_source,
        "host_config_nano_cpus": host_config_nano_cpus,
    }


def apply_geometry_gate(snapshot: dict[str, Any], geometry: dict[str, Any]) -> None:
    constraint = geometry.get("constraint")
    if not constraint:
        return
    total = sum(snapshot["effective"].values())
    composition = {service: snapshot["effective"][service] / total for service in SERVICES}
    r, n = ilr(composition, geometry["critical"], geometry["n1"], geometry["n2"])
    coordinate = {"r": r, "n": n}[constraint["coordinate"]]
    snapshot["effective_geometry"] = {"r": r, "n": n}
    if abs(coordinate - float(constraint["expected"])) > float(constraint["tolerance"]):
        snapshot["valid"] = False
        snapshot["reason_codes"].append(
            f"orthogonal_coordinate_error:{constraint['coordinate']}:{coordinate}:{constraint['expected']}"
        )


def cpu_stat(services: Iterable[str], *, tolerate_unavailable: bool = False) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for service in services:
        try:
            text, _ = read_container_cgroup_file(service, "cpu.stat")
        except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
            if not tolerate_unavailable:
                raise
            result[service] = {}
            continue
        values: dict[str, int] = {}
        for line in text.splitlines():
            key, value = line.split(maxsplit=1)
            values[key] = int(value)
        result[service] = values
    return result


def throttling_fraction(before: dict[str, dict[str, int]], after: dict[str, dict[str, int]]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for service in SERVICES:
        periods = after[service].get("nr_periods", 0) - before[service].get("nr_periods", 0)
        throttled = after[service].get("nr_throttled", 0) - before[service].get("nr_throttled", 0)
        result[service] = throttled / periods if periods > 0 else None
    return result


def cpu_stat_delta(
    before: dict[str, dict[str, int]], after: dict[str, dict[str, int]]
) -> dict[str, dict[str, int] | None]:
    return {
        service: (
            {key: after[service][key] - before[service].get(key, 0) for key in after[service]}
            if after[service] else None
        )
        for service in SERVICES
    }


def phase_config(spec: dict[str, Any], phase: str, seconds: int) -> dict[str, Any]:
    return {
        "executor": "constant-arrival-rate", "rate": spec["rate"], "timeUnit": "1s",
        "duration_seconds": seconds, "preAllocatedVUs": 320, "maxVUs": 320,
        "gracefulStop_seconds": 30, "http_timeout_seconds": 10,
        "phase": phase, "trial_id": spec["trial_id"], "point_id": spec["point_id"],
    }


def run_k6(
    repo: Path,
    manifest: dict[str, Any],
    spec: dict[str, Any],
    phase: str,
    seconds: int,
    output: Path,
    *,
    record_primary_observations: bool,
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "scenario-config.json", phase_config(spec, phase, seconds))
    uid = run(["id", "-u"]).stdout.strip()
    gid = run(["id", "-g"]).stdout.strip()
    command = [
        "docker", "run", "--rm", "--user", f"{uid}:{gid}", "--network", "opentelemetry-demo",
        "-v", f"{output.resolve()}:/artifacts", "-v", f"{(repo / 'probe1/k6/checkout.js').resolve()}:/scripts/checkout.js:ro",
        "-e", f"RATE={spec['rate']}", "-e", f"DURATION_SECONDS={seconds}", "-e", f"PHASE={phase}",
        "-e", f"TRIAL_ID={spec['trial_id']}", "-e", f"POINT_ID={spec['point_id']}",
        "-e", "TARGET_URL=http://frontend-proxy:8080", "-e", "SUMMARY_PATH=/artifacts/summary.json",
        manifest["workload"]["k6_image"], "run",
    ]
    if record_primary_observations:
        command.extend(["--out", "json=/artifacts/raw-metrics.jsonl"])
    command.append("/scripts/checkout.js")
    started = dt.datetime.now(dt.timezone.utc)
    completed = run(command, check=False)
    ended = dt.datetime.now(dt.timezone.utc)
    (output / "stdout.log").write_text(completed.stdout, encoding="utf-8", newline="\n")
    (output / "stderr.log").write_text(completed.stderr, encoding="utf-8", newline="\n")
    write_json(output / "run-status.json", {
        "exit_code": completed.returncode, "completed": completed.returncode == 0,
        "started_at": started.isoformat(), "ended_at": ended.isoformat(),
    })


def system_failure(before: dict[str, Any], after: dict[str, Any], sut: Iterable[str]) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {}
    observed_at = dt.datetime.now(dt.timezone.utc).isoformat()
    for service in sut:
        prior, current = before[service]["State"], after[service]["State"]
        restart_delta = int(after[service].get("RestartCount", 0)) - int(before[service].get("RestartCount", 0))
        failed = restart_delta > 0 or current.get("OOMKilled") is True or current.get("Running") is not True
        details[service] = {
            "restart_delta": restart_delta, "oom_killed": current.get("OOMKilled", False),
            "running": current.get("Running", False), "status": current.get("Status"), "failed": failed,
            "observed_at": observed_at,
        }
    return any(item["failed"] for item in details.values()), details


def capture_diagnostics(prefix: list[str], artifact_dir: Path, manifest: dict[str, Any]) -> None:
    diagnostics = artifact_dir / "diagnostics"
    diagnostics.mkdir(parents=True, exist_ok=True)
    for name, command in {
        "docker-version.txt": ["docker", "version"],
        "compose-version.txt": ["docker", "compose", "version"],
        "docker-stats.txt": ["docker", "stats", "--no-stream"],
        "compose-ps.txt": [*prefix, "ps", "--all"],
    }.items():
        completed = run(command, check=False)
        (diagnostics / name).write_text(completed.stdout + completed.stderr, encoding="utf-8", newline="\n")
    inspections = inspect_all(manifest["required_running_containers"])
    write_json(diagnostics / "container-inspect.json", inspections)
    rendered = run([*prefix, "config"], check=False)
    (diagnostics / "compose-rendered.yaml").write_text(rendered.stdout + rendered.stderr, encoding="utf-8", newline="\n")
    image_inspect = run(["docker", "image", "inspect", *sorted(set(manifest["images"].values()))], check=False)
    (diagnostics / "image-inspect.json").write_text(image_inspect.stdout or "[]\n", encoding="utf-8", newline="\n")
    write_json(diagnostics / "host-metrics.json", {
        "logical_cpus": os.cpu_count(),
        "load_average": list(os.getloadavg()),
        "meminfo_sha256": sha256_file(Path("/proc/meminfo")),
        "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    })
    logs = run([
        *prefix,
        "logs",
        "--no-color",
        "--timestamps",
        "--tail",
        str(manifest["diagnostic_log_tail_lines"]),
    ], check=False)
    (diagnostics / "compose.log").write_text(logs.stdout + logs.stderr, encoding="utf-8", newline="\n")


def primary_files_valid(
    artifact_dir: Path, manifest: dict[str, Any], phases: tuple[str, ...] = ("baseline", "test")
) -> tuple[bool, list[str], dict[str, Any]]:
    errors: list[str] = []
    report: dict[str, Any] = {}
    for relative in manifest["primary_observation_artifact_files"]:
        if not any(relative.startswith(f"k6/{phase}/") for phase in phases):
            continue
        path = artifact_dir / relative
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"missing_or_empty:{relative}")
            report[relative] = {"valid": False, "reason": "missing_or_empty"}
            continue
        report[relative] = {"valid": True, "bytes": path.stat().st_size, "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest()}
        try:
            if path.suffix == ".json":
                json.loads(path.read_text(encoding="utf-8"))
            elif path.suffix == ".jsonl":
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"invalid_json:{relative}")
            report[relative]["valid"] = False
            report[relative]["reason"] = "invalid_json"
    return not errors, errors, report


def execute(args: argparse.Namespace) -> dict[str, Any]:
    repo, upstream, artifact_dir = args.repo.resolve(), args.upstream_dir.resolve(), args.artifact_dir.resolve()
    manifest = load_manifest(repo / args.manifest)
    spec = json.loads(args.point_spec.read_text(encoding="utf-8"))
    validate_point_spec(spec)
    spec["trial_id"] = f"{spec['environment_id']}-{spec['point_id']}-{spec['replication_id']}-a{spec['attempt_id']}"
    if args.dry_run:
        return {"dry_run": True, "valid": True, "trial_id": spec["trial_id"], "spec": spec}

    if sys.platform != "linux" or os.getenv("GITHUB_ACTIONS") != "true":
        raise RuntimeError("runtime execution is restricted to Linux GitHub Actions runners")
    artifact_dir.mkdir(parents=True, exist_ok=False)
    write_json(artifact_dir / "point-spec.json", spec)
    write_json(artifact_dir / "metadata.json", {
        "protocol_version": PROTOCOL_VERSION,
        "repository_commit": os.getenv("GITHUB_SHA"),
        "github_run_id": os.getenv("GITHUB_RUN_ID"),
        "github_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "runner_image": os.getenv("ImageOS"),
        "runner_image_version": os.getenv("ImageVersion"),
        "runtime_lock_sha256": sha256_file(repo / args.manifest),
        "point_id": spec["point_id"],
        "replication_id": spec["replication_id"],
        "attempt_id": spec["attempt_id"],
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "images": manifest["images"],
        "k6_image": manifest["workload"]["k6_image"],
    })
    project = sanitized_project(spec)
    prefix = compose_prefix(repo, upstream, project)
    result: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION, "trial_id": spec["trial_id"], "point_id": spec["point_id"],
        "replication_id": spec["replication_id"], "attempt_id": spec["attempt_id"],
        "spec_sha256": spec["spec_sha256"],
        "provenance": {
            "github_run_id": os.getenv("GITHUB_RUN_ID"),
            "github_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
            "github_job": os.getenv("GITHUB_JOB"),
            "runner_name": os.getenv("RUNNER_NAME"),
            "runner_image": os.getenv("ImageOS"),
            "runner_image_version": os.getenv("ImageVersion"),
        },
        "validity": {"valid": False, "reason_codes": []},
    }
    try:
        run([*prefix, "down", "--volumes", "--remove-orphans"], check=False)
        for image in [*manifest["images"].values(), manifest["workload"]["k6_image"]]:
            run(["docker", "pull", image])
        run([*prefix, "up", "--detach", "--no-build", "--pull", "never"])
        wait_for_stack(manifest, manifest["workload"]["health_check_timeout_seconds"])
        initial = inspect_all(manifest["required_running_containers"])

        apply_quotas(spec["baseline_quotas"])
        baseline_quota = quota_snapshot(spec["baseline_quotas"], spec["total_cpu"])
        run_k6(
            repo, manifest, spec, "warmup", manifest["workload"]["warmup_seconds"],
            artifact_dir / "k6" / "warmup", record_primary_observations=False,
        )
        run_k6(
            repo, manifest, spec, "baseline", spec["duration_seconds"],
            artifact_dir / "k6" / "baseline", record_primary_observations=True,
        )
        baseline = summarize_phase(artifact_dir / "k6" / "baseline", spec["rate"], spec["duration_seconds"])
        baseline_artifacts_ok, baseline_artifact_errors, baseline_artifact_report = primary_files_valid(
            artifact_dir, manifest, ("baseline",)
        )
        write_json(artifact_dir / "primary-artifact-validation.json", baseline_artifact_report)
        before_intervention = inspect_all(manifest["required_running_containers"])

        pre_reasons: list[str] = []
        if not baseline_quota["valid"]:
            pre_reasons.extend(f"baseline_{reason}" for reason in baseline_quota["reason_codes"])
        if not baseline["safe"]:
            pre_reasons.append("baseline_slo_unsafe")
        if baseline["started_iterations"] < 0.95 * baseline["scheduled_iterations"]:
            pre_reasons.append("baseline_started_below_95_percent")
        if baseline["checkout_requests"] < 300:
            pre_reasons.append("baseline_checkout_requests_below_300")
        if baseline["k6_exit_code"] != 0:
            pre_reasons.append("baseline_k6_nonzero_exit")
        if not baseline_artifacts_ok:
            pre_reasons.extend(baseline_artifact_errors)
        pre_failure, pre_details = system_failure(initial, before_intervention, manifest["system_under_test_containers"])
        if pre_failure:
            pre_reasons.append("pre_intervention_restart_or_oom")
        if pre_reasons:
            result.update({
                "validity": {"valid": False, "reason_codes": pre_reasons}, "baseline": baseline,
                "test": None, "manipulation": {"valid": False, "requested_quotas": spec["test_quotas"], "effective_quotas": {}},
                "diagnostics": {"post_intervention_system_failure": False, "containers": pre_details, "throttling_fraction": {}},
            })
            return result

        apply_quotas(spec["test_quotas"])
        manipulation = quota_snapshot(spec["test_quotas"], spec["total_cpu"])
        apply_geometry_gate(manipulation, spec["geometry"])
        stat_before = cpu_stat(SERVICES)
        run_k6(
            repo, manifest, spec, "stabilization", manifest["workload"]["stabilization_seconds"],
            artifact_dir / "k6" / "stabilization", record_primary_observations=False,
        )
        run_k6(
            repo, manifest, spec, "test", spec["duration_seconds"],
            artifact_dir / "k6" / "test", record_primary_observations=True,
        )
        stat_after = cpu_stat(SERVICES, tolerate_unavailable=True)
        after_intervention = inspect_all(manifest["required_running_containers"], tolerate_missing=True)
        test = summarize_phase(artifact_dir / "k6" / "test", spec["rate"], spec["duration_seconds"])
        artifacts_ok, artifact_errors, artifact_report = primary_files_valid(artifact_dir, manifest)
        write_json(artifact_dir / "primary-artifact-validation.json", artifact_report)
        post_failure, post_details = system_failure(before_intervention, after_intervention, manifest["system_under_test_containers"])

        reasons = list(manipulation["reason_codes"])
        if not artifacts_ok:
            reasons.extend(artifact_errors)
        if baseline["k6_exit_code"] != 0 or test["k6_exit_code"] != 0:
            reasons.append("k6_nonzero_exit")
        result.update({
            "validity": {"valid": not reasons, "reason_codes": reasons},
            "baseline": baseline,
            "test": test,
            "manipulation": {
                "valid": manipulation["valid"], "reason_codes": manipulation["reason_codes"],
                "requested_quotas": manipulation["requested"], "effective_quotas": manipulation["effective"],
                "cpu_max": manipulation["cpu_max"],
                "cpu_max_source": manipulation["cpu_max_source"],
                "host_config_nano_cpus": manipulation["host_config_nano_cpus"],
            },
            "diagnostics": {
                "post_intervention_system_failure": post_failure, "containers": post_details,
                "throttling_fraction": throttling_fraction(stat_before, stat_after),
                "cpu_stat_delta": cpu_stat_delta(stat_before, stat_after),
            },
        })
        write_json(artifact_dir / "trace-sample.json", {
            "baseline": baseline.get("trace_sample"),
            "test": test.get("trace_sample"),
        })
        return result
    finally:
        if artifact_dir.exists():
            try:
                capture_diagnostics(prefix, artifact_dir, manifest)
            except Exception as exc:  # diagnostics never replace a recoverable primary outcome
                (artifact_dir / "diagnostics-error.txt").write_text(str(exc), encoding="utf-8")
        run([*prefix, "down", "--volumes", "--remove-orphans"], check=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--upstream-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path("probe1/runtime.json"))
    parser.add_argument("--point-spec", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = execute(args)
    except Exception as exc:
        try:
            spec = json.loads(args.point_spec.read_text(encoding="utf-8"))
        except Exception:
            spec = {}
        result = {
            "protocol_version": PROTOCOL_VERSION,
            "trial_id": spec.get("trial_id", f"{spec.get('environment_id', 'unknown')}-{spec.get('point_id', 'unknown')}-{spec.get('replication_id', 'unknown')}-a{spec.get('attempt_id', 'unknown')}"),
            "point_id": spec.get("point_id"), "replication_id": spec.get("replication_id"),
            "attempt_id": spec.get("attempt_id"),
            "spec_sha256": spec.get("spec_sha256"),
            "provenance": {
                "github_run_id": os.getenv("GITHUB_RUN_ID"),
                "github_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
                "github_job": os.getenv("GITHUB_JOB"),
                "runner_name": os.getenv("RUNNER_NAME"),
                "runner_image": os.getenv("ImageOS"),
                "runner_image_version": os.getenv("ImageVersion"),
            },
            "validity": {"valid": False, "reason_codes": ["harness_exception"]},
            "baseline": None, "test": None,
            "manipulation": {"valid": False, "requested_quotas": spec.get("test_quotas", {}), "effective_quotas": {}},
            "diagnostics": {"post_intervention_system_failure": False, "containers": {}, "throttling_fraction": {}},
            "exception": repr(exc),
        }
        args.artifact_dir.mkdir(parents=True, exist_ok=True)
        write_json(args.artifact_dir / "trial-result.json", result)
        print(f"trial recorded as infrastructure-invalid: {exc!r}", file=sys.stderr)
        return 0
    write_json(args.artifact_dir / "trial-result.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
