"""Dedicated hosted orchestration; observer inputs exclude the scenario journal."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback
import urllib.request

from observer import Observer

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "evolving-state"
DESIGN = MODULE / "design-v0.1.1.json"
sys.path.insert(0, str(ROOT / "runtime"))
from runtime_support import compose_prefix, wait_for_stack, runtime_path


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def append(path, value):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, allow_nan=False, separators=(",", ":")) + "\n")


def command(args, check=True, timeout=600):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"Command failed {args[:5]}: {result.stderr[-3000:]}")
    return result


def api(path, data=None):
    request = urllib.request.Request("http://127.0.0.1:18080" + path,
                                     data=json.dumps(data).encode() if data is not None else None,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def wait_health():
    for _ in range(60):
        try:
            if api("/health")["ok"]:
                return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("Gateway health timeout")


def worker(name, group, parents, cfg, output):
    args = ["docker", "run", "-d", "--name", name, "--network", "opentelemetry-demo",
            "--user", f"{os.getuid()}:{os.getgid()}", "--memory", "128m",
            "--label", "observation.group=" + (group if not parents else ""),
            "--label", "observation.predecessors=" + json.dumps(parents),
            "-v", f"{MODULE / 'scripts/service.py'}:/service.py:ro",
            "-v", f"{output / 'journals'}:/journals", cfg["python_image"], "python", "/service.py",
            "--role", "worker", "--component", name, "--output", f"/journals/{name}.jsonl",
            "--timeout", str(cfg["attempt_timeout_seconds"])]
    command(args)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        health = command(["docker", "exec", name, "python", "-c",
                          "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=1).read()"],
                         check=False, timeout=5)
        if health.returncode == 0:
            return
        time.sleep(0.2)
    raise RuntimeError("New forwarding worker did not become ready")


def watch(available, metadata_lock, stop, output, alpha, interval, errors):
    """Independent polling; no intervention schedule or evaluator journal access."""
    try:
        with metadata_lock:
            initial = copy.deepcopy(available)
        observers = [Observer(mode, initial, alpha) for mode in ("fixed", "direct", "coda")]
        previous_key = None
        while not stop.is_set():
            snapshot = api("/snapshot")
            with metadata_lock:
                received = copy.deepcopy(available)
            snapshot["received_ms"] = time.time() * 1000
            if snapshot["ready"]:
                key = (snapshot["window"], snapshot["policy_version"],
                       tuple(received["deployments"]), tuple(received["policies"]))
                if key != previous_key:
                    append(output / "observer-inputs.jsonl", {"snapshot": snapshot, "metadata": received})
                    append(output / "diagnoses.jsonl",
                           {"rows": [o.update(snapshot, received) for o in observers]})
                    previous_key = key
            stop.wait(interval)
    except Exception as exc:
        errors.append(repr(exc))
        (output / "observer-failure.log").write_text(traceback.format_exc(), encoding="utf-8")


def deployment_document(version, routes):
    """Extract actual container metadata, without inferring membership from names."""
    ids = sorted({c for components in routes.values() for c in components})
    inspected = json.loads(command(["docker", "inspect", *ids]).stdout)
    components = {}
    for item in inspected:
        labels = item["Config"]["Labels"]
        components[item["Name"].lstrip("/")] = {
            "group": labels.get("observation.group") or None,
            "predecessors": json.loads(labels.get("observation.predecessors", "[]")),
            "container_id": item["Id"], "image_id": item["Image"]}
    return {"version": version, "components": components, "extracted_ms": time.time() * 1000}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--block", required=True)
    args = parser.parse_args()
    if os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("RUNNER_ENVIRONMENT") != "github-hosted":
        raise RuntimeError("Runtime is restricted to disposable GitHub-hosted runners")
    cfg = json.loads(DESIGN.read_text())
    parent = json.loads(runtime_path(cfg["parent_runtime"]).read_text())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "journals").mkdir()
    (output / "k6").mkdir()
    save(output / "design.json", cfg)
    upstream = args.upstream.resolve()
    if command(["git", "-C", str(upstream), "rev-parse", "HEAD"]).stdout.strip() != cfg["upstream_commit"]:
        raise ValueError("Upstream commit mismatch")
    project = "evolving-" + args.block
    compose = compose_prefix(ROOT, upstream, project)
    containers, process = [], None
    observer_thread, observer_stop = None, threading.Event()
    observer_errors = []
    status = {"block": args.block, "complete": False, "error": None,
              "implementation_commit": os.getenv("GITHUB_SHA"),
              "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
              "workflow_attempt": os.getenv("GITHUB_RUN_ATTEMPT")}
    try:
        save(output / "host.json", {"cpu": json.loads(command(["lscpu", "--json"]).stdout),
             "kernel": command(["uname", "-r"]).stdout.strip(),
             "runner_image": os.getenv("ImageVersion")})
        images = sorted({*parent["images"].values(), parent["workload"]["k6_image"], cfg["python_image"]})
        for image in images:
            command(["docker", "pull", image])
        print("Pinned images ready", flush=True)
        save(output / "image-inspect.json", json.loads(command(["docker", "image", "inspect", *images]).stdout))
        save(output / "rendered-compose.json",
             json.loads(command([*compose, "config", "--no-path-resolution", "--format", "json"]).stdout))
        command([*compose, "up", "-d", "--no-build", "--pull", "never"])
        wait_for_stack(parent, 300)
        print("Application healthy", flush=True)
        routes = {"catalog": ["reader-a"], "currency": ["reader-b"]}
        for group, names in routes.items():
            for name in names:
                worker(name, group, [], cfg, output)
                containers.append(name)
        command(["docker", "run", "-d", "--name", "retry-gateway", "--network", "opentelemetry-demo",
                 "--user", f"{os.getuid()}:{os.getgid()}", "--memory", "256m",
                 "-p", "127.0.0.1:18080:8080",
                 "-v", f"{MODULE / 'scripts/service.py'}:/service.py:ro",
                 "-v", f"{output / 'journals'}:/journals",
                 cfg["python_image"], "python", "/service.py", "--role", "gateway",
                 "--output", "/journals/client.jsonl"])
        containers.append("retry-gateway")
        wait_health()
        # All workers are started before the open-loop generator is allowed to begin.
        origin = int(time.time() * 1000) + 10000
        state = {"version": 1, "deployment": 1, "policy_version": 1,
                 "policy_limits": cfg["initial_policy"], "routes": routes,
                 "fault_probability": 0.12, "max_attempts": 2,
                 "origin_ms": origin, "windows": cfg["windows"],
                 "window_seconds": cfg["window_seconds"],
                 "attempt_timeout_seconds": cfg["attempt_timeout_seconds"],
                 "seed": int(hashlib.sha256(args.block.encode()).hexdigest()[:8], 16)}
        initial_doc = deployment_document(1, routes)
        initial_policy = {"version": 1, "limits": copy.deepcopy(state["policy_limits"]),
                          "published_ms": time.time() * 1000}
        applied = api("/configuration", state)
        initial_policy["effective_ms"] = applied["applied_ms"]
        available = {"deployments": {"1": initial_doc}, "policies": {"1": initial_policy},
                     "initial_policy": 1}
        save(output / "initial-metadata.json", available)
        save(output / "initial-configuration.json", state)
        metadata_lock = threading.RLock()
        observer_thread = threading.Thread(
            target=watch, args=(available, metadata_lock, observer_stop, output,
                               cfg["ewma_alpha"], cfg["observer_poll_seconds"], observer_errors),
            daemon=True)
        observer_thread.start()
        save(output / "load-config.json", {**cfg, "origin_ms": origin, "block_id": args.block})
        with (output / "k6/stdout.log").open("w") as stdout, (output / "k6/stderr.log").open("w") as stderr:
            process = subprocess.Popen([
                "docker", "run", "--name", "retry-load", "--network", "opentelemetry-demo",
                "--user", f"{os.getuid()}:{os.getgid()}",
                "-v", f"{output / 'k6'}:/artifacts",
                "-v", f"{MODULE / 'k6/read.js'}:/scripts/read.js:ro",
                "-v", f"{output / 'load-config.json'}:/scripts/load-config.json:ro",
                parent["workload"]["k6_image"], "run", "--quiet", "--log-format", "raw", "/scripts/read.js"],
                stdout=stdout, stderr=stderr)
            containers.append("retry-load")
            pending, done = [], {1}
            end = origin + cfg["windows"] * cfg["window_seconds"] * 1000
            while time.time() * 1000 < end + 1200:
                now = time.time() * 1000
                for event in cfg["scheduled_changes"]:
                    w = event["window"]
                    if w in done or now < origin + (w - 1) * cfg["window_seconds"] * 1000:
                        continue
                    done.add(w)
                    record = {"planned_window": w, "event": event["event"],
                              "started_ms": time.time() * 1000}
                    if w in (8, 12, 15):
                        old = state["routes"]["catalog"]
                        new = {8: ["reader-c", "reader-d"], 12: ["reader-e", "reader-f"],
                               15: ["reader-g"]}[w]
                        for name in new:
                            worker(name, "catalog", old, cfg, output)
                            containers.append(name)
                        state["routes"]["catalog"] = new
                        state["deployment"] += 1
                        doc = deployment_document(state["deployment"], state["routes"])
                        delay = event.get("metadata_delay_windows", 0) * cfg["window_seconds"] * 1000
                        pending.append((time.time() * 1000 + delay, doc))
                        record["deployment_document"] = doc
                    for key in ("fault_probability", "max_attempts"):
                        if key in event:
                            state[key] = event[key]
                    if "rho" in event:
                        state["policy_version"] += 1
                        state["policy_limits"] = {g: event["rho"] for g in cfg["groups"]}
                        policy = {"version": state["policy_version"],
                                  "limits": copy.deepcopy(state["policy_limits"]),
                                  "published_ms": time.time() * 1000}
                    else:
                        policy = None
                    state["version"] += 1
                    record.update(api("/configuration", state))
                    if policy:
                        policy["effective_ms"] = record["applied_ms"]
                        with metadata_lock:
                            available["policies"][str(policy["version"])] = policy
                        record["policy_document"] = policy
                    append(output / "interventions.jsonl", record)
                    print(json.dumps({"applied_window": w, "version": state["version"]}), flush=True)
                ready = [(at, doc) for at, doc in pending if time.time() * 1000 >= at]
                for at, doc in ready:
                    with metadata_lock:
                        available["deployments"][str(doc["version"])] = doc
                    append(output / "metadata-receipts.jsonl",
                           {"received_ms": time.time() * 1000, "document": doc})
                    pending.remove((at, doc))
                load_end = origin + cfg["active_windows"] * cfg["window_seconds"] * 1000
                if process.poll() is not None and time.time() * 1000 < load_end:
                    raise RuntimeError("Load exited before the scheduled final idle window")
                if observer_errors:
                    raise RuntimeError("Passive observer failed: " + repr(observer_errors))
                time.sleep(cfg["observer_poll_seconds"])
            exit_code = process.wait(timeout=30)
            if exit_code != 0:
                raise RuntimeError(f"Load generator exit {exit_code}")
        save(output / "final-metadata.json", available)
        observer_stop.set()
        observer_thread.join(timeout=15)
        if observer_thread.is_alive() or observer_errors:
            raise RuntimeError("Passive observer did not finish cleanly")
        status["collection_finished_ms"] = time.time() * 1000
        status["complete"] = True
    except Exception as exc:
        status["error"] = repr(exc)
        (output / "failure.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        observer_stop.set()
        if observer_thread:
            observer_thread.join(timeout=15)
        for name in containers:
            result = command(["docker", "logs", name], check=False)
            (output / (name + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
        logs = command([*compose, "logs", "--no-color", "--tail", "60"], check=False)
        (output / "compose.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")
        save(output / "status.json", status)
        if containers:
            command(["docker", "rm", "-f", *containers], check=False)
        command([*compose, "down", "--volumes"], check=False)


if __name__ == "__main__":
    main()
