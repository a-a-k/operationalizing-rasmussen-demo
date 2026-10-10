from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from measure import summarize
from study import DESIGN, ROOT, RUNTIME, VERSION, features, generator_valid, load, matrix, verify, write_json, sha256_file
from run_trial import compose_prefix, inspect_all, inspect_container, read_container_cgroup_file, wait_for_stack


def utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(command), flush=True)
    return subprocess.run(command, text=True, capture_output=True, check=check)


def apply(quotas: dict[str, float]) -> None:
    for name, value in quotas.items():
        run(["docker", "update", "--cpus", f"{value:.9f}", name])


def quota_check(quotas: dict[str, float]) -> dict[str, Any]:
    effective, raw, reasons = {}, {}, []
    for name, value in quotas.items():
        inspected = inspect_container(name)
        text, source = read_container_cgroup_file(name, "cpu.max", inspected=inspected)
        quota, period = text.split()
        if quota == "max":
            raise ValueError(f"unbounded quota: {name}")
        observed = int(quota) / int(period)
        effective[name] = observed
        raw[name] = {"cpu.max": text, "source": source, "pid": inspected["State"]["Pid"],
                     "nano_cpus": inspected["HostConfig"]["NanoCpus"]}
        if abs(observed - value) / value > 0.01 or abs(raw[name]["nano_cpus"] / 1e9 - observed) / value > 0.01:
            reasons.append(f"{name}:effective_quota_mismatch")
    if abs(sum(effective.values()) - sum(quotas.values())) > 0.01:
        reasons.append("effective_quota_sum_mismatch")
    return {"valid": not reasons, "reason_codes": reasons, "requested": quotas,
            "effective": effective, "raw": raw}


def failures(before: dict, after: dict, names: list[str]) -> dict:
    return {name: {"restart_delta": after[name]["RestartCount"] - before[name]["RestartCount"],
                   "oom_snapshot": after[name]["State"]["OOMKilled"],
                   "running": after[name]["State"]["Running"]}
            for name in names
            if after[name]["RestartCount"] > before[name]["RestartCount"]
            or after[name]["State"]["OOMKilled"] or not after[name]["State"]["Running"]}


def phase(repo: Path, parent: dict, runtime: dict, arm: dict, trial: str, point: str,
          name: str, seconds: int, folder: Path, generator: str, *, primary: bool) -> dict | None:
    folder.mkdir(parents=True, exist_ok=False)
    vus = runtime["workload"]["pre_allocated_vus"]
    write_json(folder / "scenario-config.json", {
        "rate": arm["rate"], "duration_seconds": seconds, "preAllocatedVUs": vus, "maxVUs": vus,
        "timeUnit": "1s", "gracefulStop_seconds": 30, "http_timeout_seconds": arm["http_timeout_seconds"],
        "trial_id": trial, "point_id": point, "phase": name,
    })
    command = ["docker", "run", "--name", generator, "--user", f"{os.getuid()}:{os.getgid()}",
               "--network", "opentelemetry-demo",
               "-v", f"{folder.resolve()}:/artifacts",
               "-v", f"{repo / 'probe3/k6/checkout.js'}:/scripts/checkout.js:ro"]
    for key, value in {"RATE": arm["rate"], "DURATION_SECONDS": seconds, "VUS": vus,
                       "HTTP_TIMEOUT_SECONDS": arm["http_timeout_seconds"], "TRIAL_ID": trial,
                       "POINT_ID": point, "PHASE": name}.items():
        command.extend(["-e", f"{key}={value}"])
    command.extend([parent["workload"]["k6_image"], "run"])
    if primary:
        command.extend(["--out", "json=/artifacts/raw-metrics.jsonl"])
    command.append("/scripts/checkout.js")
    started = utc()
    completed = run(command, check=False)
    write_json(folder / "run-status.json", {"started_at": started, "ended_at": utc(), "exit_code": completed.returncode})
    (folder / "stdout.log").write_text(completed.stdout, encoding="utf-8")
    (folder / "stderr.log").write_text(completed.stderr, encoding="utf-8")
    inspected = run(["docker", "inspect", generator], check=False)
    if inspected.returncode == 0:
        write_json(folder / "generator-inspect.json", json.loads(inspected.stdout))
    run(["docker", "rm", "--force", generator], check=False)
    if not primary:
        if completed.returncode != 0:
            raise RuntimeError(f"{name} load-generator failed")
        return None
    return summarize(folder, rate=arm["rate"], seconds=seconds, vus=vus,
                     timeout=arm["http_timeout_seconds"],
                     p95_limit=runtime["workload"]["slo_p95_ms"],
                     error_limit=runtime["workload"]["slo_error_rate"])


def diagnostic_summary(folder: Path, intervention: str | None, measurement_end: str | None, generator: str) -> dict:
    events, sample_errors = [], []
    path = folder / "docker-events.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        try:
            event = json.loads(line)
            if event.get("Action") in {"die", "oom", "restart", "kill"}:
                seconds = event["timeNano"] / 1e9 if "timeNano" in event else event["time"]
                stamp = dt.datetime.fromtimestamp(seconds, dt.timezone.utc).isoformat()
                events.append({"timestamp": stamp, "action": event["Action"],
                               "attributes": event.get("Actor", {}).get("Attributes", {}),
                               "post_intervention": intervention is not None and measurement_end is not None
                               and dt.datetime.fromisoformat(intervention) <= dt.datetime.fromisoformat(stamp)
                               <= dt.datetime.fromisoformat(measurement_end),
                               "after_measurement": measurement_end is not None
                               and dt.datetime.fromisoformat(stamp) > dt.datetime.fromisoformat(measurement_end)})
        except (ValueError, KeyError) as exc:
            sample_errors.append(repr(exc))
    host, gen, test_host, test_gen = [], [], [], []
    status_path = folder / "k6/test/run-status.json"
    test_status = load(status_path) if status_path.exists() else None
    path = folder / "resource-samples.jsonl"
    rows = 0
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        try:
            sample = json.loads(line)
            rows += 1
            if "host_cpu_fraction" in sample:
                host.append(sample["host_cpu_fraction"])
            delta = sample["containers"].get(generator, {}).get("delta")
            if delta:
                gen.append(delta["cpu_cores"])
            if test_status and test_status["started_at"] <= sample["timestamp"] <= test_status["ended_at"]:
                if "host_cpu_fraction" in sample:
                    test_host.append(sample["host_cpu_fraction"])
                if delta:
                    test_gen.append(delta["cpu_cores"])
        except (ValueError, KeyError) as exc:
            sample_errors.append(repr(exc))
    return {
        "failure_events": events, "resource_sample_rows": rows, "diagnostic_errors": sample_errors,
        "host_cpu_fraction_mean": sum(host) / len(host) if host else None,
        "host_cpu_fraction_max": max(host) if host else None,
        "generator_cpu_cores_mean": sum(gen) / len(gen) if gen else None,
        "generator_cpu_cores_max": max(gen) if gen else None,
        "generator_sample_intervals": len(gen),
        "test_host_cpu_fraction_mean": sum(test_host) / len(test_host) if test_host else None,
        "test_host_cpu_fraction_max": max(test_host) if test_host else None,
        "test_generator_cpu_cores_mean": sum(test_gen) / len(test_gen) if test_gen else None,
        "test_generator_cpu_cores_max": max(test_gen) if test_gen else None,
        "test_generator_sample_intervals": len(test_gen),
    }


def point(repo: Path, upstream: Path, parent: dict, runtime: dict, arm: dict,
          arm_id: str, block_id: str, point_id: str, folder: Path) -> dict:
    folder.mkdir(parents=True, exist_ok=False)
    project = f"followup-{os.environ['GITHUB_RUN_ID']}-{block_id}-{point_id}".replace("_", "-")
    generator = project + "-k6"
    prefix = compose_prefix(repo, upstream, project)
    spec = {"study_version": VERSION, "arm": arm_id, "block_id": block_id, "point_id": point_id,
            "reference_quotas": arm["reference"], "test_quotas": arm["points"][point_id],
            "rate": arm["rate"], "features": features(arm, arm["points"][point_id])}
    write_json(folder / "point-spec.json", spec)
    result: dict[str, Any] = {
        **spec, "valid": False, "primary_recoverable": False, "reason_codes": [],
        "baseline": None, "test": None, "intervention_at": None, "measurement_ended_at": None,
        "provenance": {"repository_commit": os.environ["GITHUB_SHA"], "workflow_run_id": os.environ["GITHUB_RUN_ID"],
                       "runner_image": os.getenv("ImageOS"), "runner_image_version": os.getenv("ImageVersion"),
                       "design_sha256": sha256_file(repo / DESIGN), "runtime_sha256": sha256_file(repo / RUNTIME)},
    }
    event_file = (folder / "docker-events.jsonl").open("w", encoding="utf-8")
    event_error = (folder / "docker-events.stderr.log").open("w", encoding="utf-8")
    events = subprocess.Popen(["docker", "events", "--since", utc(), "--filter", "type=container",
                               "--filter", f"label=com.docker.compose.project={project}", "--format", "{{json .}}"],
                              stdout=event_file, stderr=event_error)
    sampler = None
    try:
        run([*prefix, "up", "--detach", "--no-build", "--pull", "never"])
        wait_for_stack(parent, parent["workload"]["health_check_timeout_seconds"])
        initial = inspect_all(parent["required_running_containers"])
        write_json(folder / "initial-container-inspect.json", initial)
        sampled = sorted(set(arm["reference"]) | {"astronomy-db", "frontend", "cart", generator})
        write_json(folder / "observer-config.json", {
            "containers": sampled, "output": str((folder / "resource-samples.jsonl").resolve()),
            "stop_file": str((folder / ".observer-stop").resolve()),
            "interval_seconds": runtime["observation"]["sample_interval_seconds"],
            "refresh_seconds": runtime["observation"]["cgroup_refresh_seconds"],
        })
        sampler = subprocess.Popen(["sudo", "--non-interactive", sys.executable,
                                    str(repo / "probe3/scripts/observe.py"), "--config",
                                    str((folder / "observer-config.json").resolve())])
        apply(arm["reference"])
        result["baseline_quota"] = quota_check(arm["reference"])
        phase(repo, parent, runtime, arm, block_id, point_id, "warmup", arm["warmup_seconds"], folder / "k6/warmup", generator, primary=False)
        baseline = phase(repo, parent, runtime, arm, block_id, point_id, "baseline", arm["baseline_seconds"], folder / "k6/baseline", generator, primary=True)
        result["baseline"] = baseline
        before = inspect_all(parent["required_running_containers"])
        write_json(folder / "pre-intervention-container-inspect.json", before)
        pre_failures = failures(initial, before, parent["system_under_test_containers"])
        reasons = result["reason_codes"]
        if not result["baseline_quota"]["valid"]:
            reasons.append("baseline_quota_invalid")
        if not baseline["safe"]:
            reasons.append("baseline_slo_unsafe")
        if not generator_valid(baseline):
            reasons.append("baseline_started_below_99_percent")
        if baseline["k6_exit_code"] != 0:
            reasons.append("baseline_generator_failed")
        if pre_failures:
            reasons.append("pre_intervention_system_failure")
        result["pre_intervention_failures"] = pre_failures
        if reasons:
            return result
        result["intervention_at"] = utc()
        apply(arm["points"][point_id])
        result["manipulation"] = quota_check(arm["points"][point_id])
        observed = features(arm, result["manipulation"]["effective"])
        if abs(observed["R_group"] - spec["features"]["R_group"]) > 0.01:
            reasons.append("effective_balance_mismatch")
        if not result["manipulation"]["valid"]:
            reasons.append("test_quota_invalid")
        phase(repo, parent, runtime, arm, block_id, point_id, "stabilization", arm["stabilization_seconds"], folder / "k6/stabilization", generator, primary=False)
        test = phase(repo, parent, runtime, arm, block_id, point_id, "test", arm["test_seconds"], folder / "k6/test", generator, primary=True)
        result["test"] = test
        # A nonzero generator exit is a validity failure, not deletion of readable data.
        result["primary_recoverable"] = True
        result["measurement_ended_at"] = load(folder / "k6/test/run-status.json")["ended_at"]
        # This gate is on the real execution path, not just candidate selection.
        if not generator_valid(test):
            reasons.append("test_started_below_99_percent")
        if test["k6_exit_code"] != 0:
            reasons.append("test_generator_failed")
        after = inspect_all(parent["required_running_containers"], tolerate_missing=True)
        write_json(folder / "post-intervention-container-inspect.json", after)
        result["post_intervention_failures"] = failures(before, after, parent["system_under_test_containers"])
        # Post-intervention failures are deliberately absent from validity reasons.
        result["valid"] = not reasons
        return result
    except Exception as exc:
        result["reason_codes"].append("infrastructure_exception")
        result["exception"] = repr(exc)
        return result
    finally:
        cleanup_errors = []
        if result["measurement_ended_at"] is None:
            result["measurement_ended_at"] = utc()
        if sampler is not None:
            try:
                (folder / ".observer-stop").touch()
                sampler.wait(timeout=15)
            except subprocess.TimeoutExpired:
                try:
                    run(["sudo", "--non-interactive", "kill", "-TERM", str(sampler.pid)], check=False)
                    sampler.wait(timeout=10)
                except Exception as exc:
                    cleanup_errors.append(f"observer_stop:{exc!r}")
            except Exception as exc:
                cleanup_errors.append(f"observer_stop:{exc!r}")
        try:
            logs = run([*prefix, "logs", "--no-color", "--timestamps", "--tail",
                        str(runtime["observation"]["compose_log_tail_lines"])], check=False)
            (folder / "compose.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")
        except Exception as exc:
            cleanup_errors.append(f"compose_logs:{exc!r}")
        # No scientific outcome is changed by diagnostic collection or teardown.
        result["teardown_started_at"] = utc()
        try:
            run([*prefix, "down", "--volumes", "--remove-orphans"], check=False)
        except Exception as exc:
            cleanup_errors.append(f"compose_down:{exc!r}")
        try:
            events.terminate()
            try:
                events.wait(timeout=5)
            except subprocess.TimeoutExpired:
                events.kill()
                events.wait(timeout=5)
        except Exception as exc:
            cleanup_errors.append(f"events_stop:{exc!r}")
        finally:
            event_file.close()
            event_error.close()
        try:
            result["diagnostics"] = diagnostic_summary(folder, result["intervention_at"], result["measurement_ended_at"], generator)
        except Exception as exc:
            result["diagnostics"] = {"failure_events": [], "diagnostic_errors": [repr(exc)]}
        result["diagnostics"]["cleanup_errors"] = cleanup_errors
        write_json(folder / "point-result.json", result)
        # Compress the time series, preserving event rows and cgroup segments.
        for name in ["resource-samples.jsonl", "docker-events.jsonl"]:
            path = folder / name
            if path.exists():
                try:
                    with path.open("rb") as source, gzip.open(folder / (name + ".gz"), "wb") as target:
                        while chunk := source.read(1024 * 1024):
                            target.write(chunk)
                    path.unlink()
                except OSError as exc:
                    cleanup_errors.append(f"compression:{name}:{exc!r}")
        write_json(folder / "point-result.json", result)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-dir", type=Path, required=True)
    parser.add_argument("--block-id", required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    repo, upstream = ROOT, args.upstream_dir.resolve()
    verify(repo, upstream, check_runner=True)
    design, runtime = load(repo / DESIGN), load(repo / RUNTIME)
    parent = load(repo / runtime["parent_runtime"])
    output = args.artifact_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for image in sorted({*parent["images"].values(), parent["workload"]["k6_image"]}):
        run(["docker", "pull", image])
    write_json(output / "image-inspect.json", json.loads(run([
        "docker", "image", "inspect", *sorted({*parent["images"].values(), parent["workload"]["k6_image"]})
    ]).stdout))
    prefix = compose_prefix(repo, upstream, "followup-render")
    write_json(output / "rendered-compose.json", json.loads(run([
        *prefix, "config", "--no-path-resolution", "--format", "json"
    ]).stdout))
    write_json(output / "runner.json", {
        "runner_image": os.getenv("ImageOS"), "runner_image_version": os.getenv("ImageVersion"),
        "cpu_count": os.cpu_count(), "docker_version": run(["docker", "version", "--format", "{{json .}}"]).stdout,
        "compose_version": run(["docker", "compose", "version"]).stdout,
        "study_verification": verify(repo),
    })
    if args.smoke:
        arm = dict(design["arms"]["ab"])
        arm.update({"rate": 1, "warmup_seconds": 15, "baseline_seconds": 10, "stabilization_seconds": 5,
                    "test_seconds": 10, "points": {"reference": arm["reference"]}})
        row = {"arm": "smoke", "block_id": "smoke", "order": ["reference"]}
    else:
        row = next(r for r in matrix(design) if r["block_id"] == args.block_id)
        arm = design["arms"][row["arm"]]
    write_json(output / "order.json", row)
    results = {}
    for point_id in row["order"]:
        results[point_id] = point(repo, upstream, parent, runtime, arm, row["arm"], row["block_id"],
                                  point_id, output / "points" / point_id)
    block = {"study_version": VERSION, **row, "points": results,
             "valid": all(p["valid"] for p in results.values()),
             "repository_commit": os.environ["GITHUB_SHA"], "workflow_run_id": os.environ["GITHUB_RUN_ID"]}
    write_json(output / "block-result.json", block)
    if args.smoke:
        p = results["reference"]
        diagnostic_ok = p.get("diagnostics", {}).get("generator_sample_intervals", 0) > 0
        return 0 if block["valid"] and diagnostic_ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
