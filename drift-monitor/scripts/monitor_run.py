"""Hosted-runner-only continuous runtime collection and passive online observation."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

from monitor_core import (ROOT, DESIGN, Observer, SampleReader, allocation, digest,
                          feature, integrate, load, load_frozen, matrix, save, settling, timing)
import numpy as np

sys.path.insert(0, str(ROOT / "probe7/scripts"))
import runtime as stack


def command(args, check=True, timeout=600):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"Command failed: {args}\n{result.stderr[-4000:]}")
    return result


def hosted_only():
    if os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("RUNNER_ENVIRONMENT") != "github-hosted":
        raise RuntimeError("Runtime collection is restricted to disposable hosted runners")


def wait_until(stamp, process=None):
    while time.time() < stamp:
        if process is not None and process.poll() is not None:
            raise RuntimeError("Load generator exited before the measurement schedule ended")
        time.sleep(min(1., stamp - time.time()) if stamp > time.time() else .001)


def first_origin(paths, process):
    deadline = time.monotonic() + 90
    with ExitStack() as opened:
        streams = [opened.enter_context(path.open(encoding="utf-8")) for path in paths]
        while time.monotonic() < deadline:
            for stream in streams:
                while True:
                    position = stream.tell()
                    line = stream.readline()
                    if not line.endswith("\n"):
                        stream.seek(position)
                        break
                    if line.startswith("ORIGIN "):
                        row = json.loads(line[7:])
                        if row["stream"] == "checkout":
                            return row["origin"] / 1000
            if process.poll() is not None:
                raise RuntimeError("Generator exited before a checkout origin was recorded")
            time.sleep(.1)
    raise RuntimeError("No checkout origin within 90 seconds")


def quota_check(state):
    check = stack.quotas(state)
    for part, row in check["rows"].items():
        value = row.get("cgroup", {}).get("cpu.max", "")
        if not value or int(value.split()[1]) != 100000:
            check["reasons"].append(part + ":cpu_period_mismatch")
    check["valid"] = not check["reasons"]
    return check


def compress(folder):
    for path in folder.rglob("*"):
        if path.is_file() and path.suffix in (".jsonl", ".log") and path.stat().st_size > 100000:
            with path.open("rb") as source, gzip.open(str(path) + ".gz", "wb") as target:
                while data := source.read(1024 * 1024):
                    target.write(data)
            path.unlink()


def prepare(upstream, output):
    cfg = load(DESIGN)
    runtime = load(ROOT / cfg["runtime"])
    parent = load(ROOT / runtime["parent_runtime"])
    actual = command(["git", "-C", str(upstream), "rev-parse", "HEAD"]).stdout.strip()
    if actual != runtime["upstream_commit"]:
        raise ValueError("Upstream source mismatch")
    output.mkdir(parents=True, exist_ok=False)
    save(output / "host-context.json", {"upstream_commit": actual, "runner_image": os.getenv("ImageVersion"),
         "cpu": json.loads(command(["lscpu", "--json"]).stdout), "kernel": command(["uname", "-r"]).stdout.strip(),
         "docker": json.loads(command(["docker", "info", "--format", "{{json .}}"] ).stdout)})
    for image in sorted({*parent["images"].values(), *runtime["additional_images"].values(), parent["workload"]["k6_image"]}):
        command(["docker", "pull", image])
    return cfg, runtime, parent


def summarize_load(folder, cfg):
    summary = load(folder / "k6/summary.json")
    metrics = summary["metrics"]
    rows = []
    for epoch in range(1, cfg["monitor_windows"] + 1):
        def value(name, key="count"):
            return metrics.get(name + "{slot:" + str(epoch) + "}", {}).get("values", {}).get(key)
        expected = cfg["checkout_rate"] * cfg["window_seconds"]
        starts, good = value("monitor_checkout_starts"), value("monitor_checkout_good")
        attempts, adgood, timely = value("monitor_ad_attempts"), value("monitor_ad_good"), value("monitor_ad_timely")
        rows.append({"epoch": epoch, "checkout_started": starts, "checkout_expected": expected,
                     "checkout_start_fraction": starts / expected if starts is not None else None,
                     "checkout_error_fraction": (expected - good) / expected if good is not None else None,
                     "checkout_p95_ms": value("monitor_checkout_latency", "p(95)"),
                     "ad_attempts": attempts, "ad_goodput": adgood / cfg["window_seconds"] if adgood is not None else None,
                     "ad_timely_fraction": timely / attempts if attempts else None,
                     "ad_p99_ms": value("monitor_ad_latency", "p(99)")})
    return {"windows": rows, "dropped_iterations": metrics.get("dropped_iterations", {}).get("values", {}).get("count", 0),
            "checkout_starts_total": metrics["monitor_checkout_starts"]["values"]["count"]}


def session(upstream, output, row, policy, cfg, runtime, parent, frozen, smoke=False):
    output.mkdir()
    state = allocation(row["context"])
    result = {"policy": policy, "technical_complete": False, "qualified": False,
              "observations": [], "updates": [], "reasons": [], "config": cfg}
    project = "monitor-" + os.environ["GITHUB_RUN_ID"] + "-" + row["block_id"] + "-" + policy
    compose = stack.prefix(upstream, project)
    generator = project + "-load"
    handles, sampler, events, process = [], None, None, None
    try:
        save(output / "rendered-compose.json", json.loads(command([*compose, "config", "--no-path-resolution", "--format", "json"]).stdout))
        ef = (output / "container-events.jsonl").open("w", encoding="utf-8")
        ee = (output / "container-events.stderr.log").open("w", encoding="utf-8")
        handles.extend([ef, ee])
        events = subprocess.Popen(["docker", "events", "--filter", "type=container", "--filter",
                                  "label=com.docker.compose.project=" + project, "--format", "{{json .}}"], stdout=ef, stderr=ee)
        command([*compose, "up", "-d", "--no-build", "--pull", "never"])
        ready = {**parent, "required_running_containers": parent["required_running_containers"] + ["accounting", "kafka"],
                 "mandatory_healthy_containers": parent["mandatory_healthy_containers"] + ["kafka"]}
        stack.engine.wait_for_stack(ready, runtime["health_timeout_seconds"])
        stack.apply(state, None, output / "initial-updates.jsonl")
        initial = quota_check(state)
        save(output / "initial-quota-checks.json", initial)
        if not initial["valid"]:
            raise ValueError("Initial quota readback failed")
        rendered = load(output / "rendered-compose.json")
        images = sorted({s["image"] for s in rendered["services"].values() if s.get("profiles") != ["disabled"]})
        save(output / "image-inspect.json", json.loads(command(["docker", "image", "inspect", *images, parent["workload"]["k6_image"]]).stdout))
        samples = output / "resource-samples.jsonl"
        save(output / "observer-config.json", {"containers": cfg["parts"] + [generator], "output": str(samples),
             "stop_file": str(output / ".observer-stop"), "interval_seconds": cfg["sampling_seconds"], "refresh_seconds": 6})
        sampler = subprocess.Popen(["sudo", "-n", sys.executable, str(ROOT / "probe3/scripts/observe.py"),
                                    "--config", str(output / "observer-config.json")])
        reader = SampleReader(samples)
        load_cfg = {**cfg, "total_seconds": timing(cfg)[-1]["measurement_end"]}
        save(output / "load-design.json", load_cfg)
        k6 = output / "k6"
        k6.mkdir()
        out, err = (k6 / "stdout.log").open("w", encoding="utf-8"), (k6 / "stderr.log").open("w", encoding="utf-8")
        handles.extend([out, err])
        args = ["docker", "run", "--name", generator, "--user", f"{os.getuid()}:{os.getgid()}",
                "--network", "opentelemetry-demo", "-v", f"{k6}:/artifacts", "-v", f"{ROOT / 'drift-monitor/k6/load.js'}:/scripts/load.js:ro",
                "-v", f"{output / 'load-design.json'}:/scripts/load-design.json:ro", "-v", f"{upstream / 'pb'}:/proto:ro",
                "-e", "TRIAL_ID=" + row["block_id"] + "-" + policy, parent["workload"]["k6_image"],
                "run", "--quiet", "--log-format", "raw", "/scripts/load.js"]
        process = subprocess.Popen(args, stdout=out, stderr=err)
        origin = first_origin([k6 / "stdout.log", k6 / "stderr.log"], process)
        result["load_origin_ms"] = origin * 1000
        wait_until(origin + cfg["warmup_seconds"] + cfg["sample_availability_wait_seconds"], process)
        reader.refresh()
        span = cfg["settling"]["block_seconds"]
        warm = cfg["warmup_seconds"]
        a = integrate(reader.frames, cfg["parts"], origin + warm - 2 * span, origin + warm - span, cfg["minimum_counter_coverage"])
        b = integrate(reader.frames, cfg["parts"], origin + warm - span, origin + warm, cfg["minimum_counter_coverage"])
        result["settling"] = settling(a, b, cfg)
        save(output / "settling.json", result["settling"])
        reference_end = origin + warm + cfg["reference_seconds"]
        wait_until(reference_end + cfg["sample_availability_wait_seconds"], process)
        reader.refresh()
        reference = integrate(reader.frames, cfg["parts"], origin + warm, reference_end, cfg["minimum_counter_coverage"])
        result["reference"] = reference
        save(output / "reference.json", reference)
        if not reference["valid"]:
            raise ValueError("Reference CPU input is incomplete")
        observer = Observer(frozen, reference["cpu"]) if frozen is not None else None
        previous_z = np.zeros(len(cfg["parts"]) - 1)
        for slot in timing(cfg):
            planned = origin + slot["slot_start"]
            wait_until(planned, process)
            update = {"epoch": slot["epoch"], "planned_ms": planned * 1000, "commands": []}
            step = max(0, slot["epoch"] - cfg["pre_intervention_windows"])
            if policy == "drift" and step:
                target = allocation(row["context"], step)
                for service in [*cfg["donors"], cfg["receiver"]]:
                    start = time.time() * 1000
                    done = command(["docker", "update", "--cpus", str(target["cpu"][service]), service], check=False, timeout=20)
                    update["commands"].append({"service": service, "cpu": target["cpu"][service], "started_ms": start,
                                               "ended_ms": time.time() * 1000, "exit_code": done.returncode, "stderr": done.stderr})
                    if done.returncode:
                        raise RuntimeError("Quota update failed: " + done.stderr)
                state = target
            check = quota_check(state)
            save(output / f"quota-check-{slot['epoch']:02d}.json", check)
            update["completed_ms"] = time.time() * 1000
            update["timely"] = update["completed_ms"] <= 1000 * (origin + slot["measurement_start"])
            update["quota_valid"] = check["valid"]
            result["updates"].append(update)
            save(output / "updates.json", result["updates"])
            wait_until(origin + slot["measurement_end"] + cfg["sample_availability_wait_seconds"])
            reader.refresh()
            measured = integrate(reader.frames, cfg["parts"], origin + slot["measurement_start"],
                                 origin + slot["measurement_end"], cfg["minimum_counter_coverage"])
            measured.update(epoch=slot["epoch"], available_ms=time.time() * 1000, allocation=state,
                            quota_valid=check["valid"], update_timely=update["timely"])
            if measured["valid"]:
                z = feature(measured["cpu"], reference["cpu"], "ilr_composition")
                measured["ilr_displacement"] = z.tolist()
                measured["ilr_step"] = (z - previous_z).tolist()
                measured["aitchison_displacement"] = float(np.linalg.norm(z))
                previous_z = z
                measured["online"] = observer.update(measured["cpu"]) if observer else None
            else:
                result["reasons"].append("incomplete_cpu_window_" + str(slot["epoch"]))
                observer = None
            result["observations"].append(measured)
            save(output / "history.json", result)
            print(json.dumps({"policy": policy, "epoch": slot["epoch"], "cpu_valid": measured["valid"],
                              "settling_pass": result["settling"]["passed"], "online": measured.get("online")}), flush=True)
        process.wait(timeout=cfg["graceful_stop_seconds"] + 60)
        save(k6 / "run-status.json", {"exit_code": process.returncode})
        if process.returncode:
            raise RuntimeError("Continuous generator failed; see its archived stderr")
        result["load"] = summarize_load(output, cfg)
        if result["load"]["dropped_iterations"]:
            result["reasons"].append("generator_dropped_iterations")
        for w in result["load"]["windows"]:
            if w["checkout_start_fraction"] is None or not .99 <= w["checkout_start_fraction"] <= 1.01:
                result["reasons"].append("checkout_generator_capacity")
        if any(not u["timely"] or not u["quota_valid"] for u in result["updates"]):
            result["reasons"].append("update_timing_or_readback")
        result["technical_complete"] = True
        result["qualified"] = not result["reasons"] and (smoke or result["settling"]["passed"])
    except Exception as exc:
        result["reasons"].append(str(exc))
        (output / "failure.log").write_text(traceback.format_exc(), encoding="utf-8")
        print(traceback.format_exc(), flush=True)
    finally:
        if process and process.poll() is None:
            command(["docker", "stop", "--time", "35", generator], check=False)
            process.wait(timeout=45)
        if sampler:
            (output / ".observer-stop").touch()
            try:
                sampler.wait(timeout=10)
            except subprocess.TimeoutExpired:
                sampler.terminate()
        if events:
            events.terminate()
            try:
                events.wait(timeout=5)
            except subprocess.TimeoutExpired:
                events.kill()
        for handle in handles:
            handle.close()
        logs = command([*compose, "logs", "--no-color", "--timestamps", "--tail", "100"], check=False)
        (output / "container-logs.txt").write_text(logs.stdout + logs.stderr, encoding="utf-8")
        inspected = command(["docker", "inspect", *state["cpu"]], check=False)
        save(output / "final-container-inspect.json", json.loads(inspected.stdout or "[]"))
        save(output / "history.json", result)
        command(["docker", "rm", "-f", generator], check=False)
        command([*compose, "down", "--volumes", "--remove-orphans"], check=False)
        compress(output)
    return result


def run(upstream, output, phase, bid, model_folder=None):
    hosted_only()
    smoke = phase == "smoke"
    row = {"block_id": "smoke", "context": "balanced", "role": "engineering", "repetition": 0, "order": ["drift"]} if smoke else next(r for r in matrix(phase) if r["block_id"] == bid)
    cfg, runtime, parent = prepare(upstream, output)
    frozen = load_frozen(model_folder) if phase == "test" else None
    if smoke:
        cfg.update(warmup_seconds=30, reference_seconds=20, window_seconds=8, guard_seconds=4,
                   monitor_windows=4, pre_intervention_windows=1, sampling_seconds=.5, sample_availability_wait_seconds=1.2)
        cfg["settling"] = {**cfg["settling"], "block_seconds": 10}
    result = {**row, "phase": phase, "design_sha256_lf": digest(DESIGN), "execution_commit": os.environ["GITHUB_SHA"],
              "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", "1"),
              "frozen_model": frozen, "histories": {}}
    try:
        for policy in row["order"]:
            result["histories"][policy] = session(upstream, output / policy, row, policy, cfg, runtime, parent, frozen, smoke)
            save(output / "job.json", result)
    finally:
        save(output / "job.json", result)
    complete = len(result["histories"]) == len(row["order"]) and all(h["technical_complete"] for h in result["histories"].values())
    engineering_valid = not smoke or all(h["qualified"] for h in result["histories"].values())
    return 0 if complete and engineering_valid else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["matrix", "run", "config"])
    parser.add_argument("--phase", choices=["smoke", "background", "test"], default="background")
    parser.add_argument("--block-id")
    parser.add_argument("--upstream-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--model-folder", type=Path)
    args = parser.parse_args()
    if args.command == "matrix":
        print(json.dumps({"include": matrix(args.phase)}))
    elif args.command == "config":
        cfg = load(DESIGN)
        print(json.dumps({**cfg, "total_seconds": timing(cfg)[-1]["measurement_end"]}))
    else:
        raise SystemExit(run(args.upstream_dir.resolve(), args.output_dir.resolve(), args.phase, args.block_id, args.model_folder))
