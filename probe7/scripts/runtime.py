from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import gzip
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe3/scripts"))
import run_block as engine
from measure import summarize as summarize_checkout
from study import load, write_json
sys.path.insert(0, str(Path(__file__).parent))
from measurements import accounting, advertising, parse_ack_lines
from model import choose, initial_state, matrix, proposal, representation

RUNTIME = "probe7/runtime-v0.1.1.json"
DESIGN = "probe7/design-v0.1.1.json"
PILOT = "probe7/pilot-design-v0.1.1.json"
OVERLAY = "probe7/compose-v0.1.1.yaml"


def command(args, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True)


def prefix(upstream: Path, project: str) -> list[str]:
    return ["docker", "compose", "--project-name", project, "--project-directory", str(upstream),
            "--env-file", str(upstream / ".env"), "--env-file", str(ROOT / "probe1/otel.env"),
            "-f", str(upstream / "compose.yaml"), "-f", str(upstream / "compose.full.yaml"),
            "-f", str(ROOT / "probe1/compose.lock.yaml"), "-f", str(ROOT / OVERLAY)]


def apply(state: dict, before: dict | None, journal: Path) -> None:
    names = list(state["cpu"])
    if before is not None:
        names.sort(key=lambda n: (state["cpu"][n] - before["cpu"][n] > 0 or
                                  state["memory"][n] - before["memory"][n] > 0, n))
    for name in names:
        if before is not None and all(state[r][name] == before[r][name] for r in ("cpu", "memory")):
            continue
        args = ["docker", "update", "--cpus", str(state["cpu"][name]),
                "--memory", str(state["memory"][name]), "--memory-swap", str(state["memory"][name]), name]
        start = time.time()
        result = command(args, check=False)
        with journal.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"started_ms": start * 1000, "ended_ms": time.time() * 1000,
                               "service": name, "cpu": state["cpu"][name], "memory": state["memory"][name],
                               "exit_code": result.returncode, "stderr": result.stderr}) + "\n")
        if result.returncode:
            raise RuntimeError(f"Limit update failed for {name}: {result.stderr}")


def quotas(state: dict) -> dict:
    items = json.loads(command(["docker", "inspect", *state["cpu"]]).stdout)
    rows, errors = {}, []
    for item in items:
        name = item["Name"].lstrip("/")
        host = item["HostConfig"]
        row = {"container_id": item["Id"], "pid": item["State"]["Pid"],
               "cpu": host["NanoCpus"] / 1e9, "memory": host["Memory"],
               "memory_swap": host["MemorySwap"], "restart_count": item["RestartCount"],
               "running": item["State"]["Running"], "oom_snapshot": item["State"]["OOMKilled"]}
        if abs(row["cpu"] - state["cpu"][name]) > 1e-7 or row["memory"] != state["memory"][name] or row["memory_swap"] != row["memory"]:
            errors.append(name + ":configured_limit_mismatch")
        rows[name] = row
    code = ("import sys,json,pathlib; rows=json.loads(sys.argv[1]); out={}; "
            "\nfor n,r in rows.items():"
            "\n try:"
            "\n  p=pathlib.Path('/proc')/str(r['pid'])/'root/sys/fs/cgroup'; "
            "out[n]={k:(p/k).read_text().strip() for k in ['cpu.max','memory.max','memory.swap.max']}"
            "\n except Exception as e: out[n]={'error':str(e)}"
            "\nprint(json.dumps(out))")
    cg = json.loads(command(["sudo", "-n", sys.executable, "-c", code, json.dumps(rows)]).stdout)
    for name, fields in cg.items():
        rows[name]["cgroup"] = fields
        if "error" in fields:
            current = json.loads(command(["docker", "inspect", name]).stdout)[0]["State"]
            changed = current["Pid"] != rows[name]["pid"] or not current["Running"]
            rows[name]["process_changed_during_readback"] = changed
            if rows[name]["running"] and not changed:
                errors.append(name + ":cgroup_unreadable")
            continue
        quota, period = fields["cpu.max"].split()
        if quota == "max" or abs(int(quota) / int(period) - state["cpu"][name]) > 1e-5:
            errors.append(name + ":effective_cpu_mismatch")
        if fields["memory.max"] != str(state["memory"][name]) or fields["memory.swap.max"] != "0":
            errors.append(name + ":effective_memory_mismatch")
    return {"valid": not errors, "reasons": errors, "rows": rows,
            "cpu_total": sum(r["cpu"] for r in rows.values()),
            "memory_total": sum(r["memory"] for r in rows.values())}


def commit_snapshot(folder: Path) -> dict[str, float]:
    sql = ('SELECT COALESCE(json_agg(json_build_object('
           "'order_id', order_id, 'commit_ms', EXTRACT(EPOCH FROM pg_xact_commit_timestamp(xmin))*1000)), '[]') "
           'FROM accounting."order";')
    result = command(["docker", "exec", "astronomy-db", "psql", "-U", "postgres",
                      "-d", "astronomy_db", "-At", "-c", sql])
    records = json.loads(result.stdout)
    if any(row["commit_ms"] is None for row in records):
        raise ValueError("Commit timestamp missing from a recorded order")
    with gzip.open(folder / "database-commits.json.gz", "wt", encoding="utf-8") as f:
        json.dump(records, f)
    return {r["order_id"]: float(r["commit_ms"]) for r in records}


def resources(path: Path, start_ms: float, end_ms: float, state: dict) -> dict:
    values = {p: [] for p in state["cpu"]}
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            stamp = dt.datetime.fromisoformat(row["timestamp"]).timestamp() * 1000
            if start_ms <= stamp <= end_ms:
                for name in values:
                    if name in row["containers"] and "memory_current_bytes" in row["containers"][name]:
                        values[name].append(row["containers"][name])
    result = {}
    for name, samples in values.items():
        deltas = [s["delta"] for s in samples if s.get("delta")]
        throttling = [d["throttled_period_fraction"] for d in deltas if d["throttled_period_fraction"] is not None]
        result[name] = {
            "samples": len(samples), "cpu_cores": sum(d["cpu_cores"] for d in deltas) / len(deltas) if deltas else None,
            "throttling": sum(throttling) / len(throttling) if throttling else None,
            "memory_peak_bytes": max(s["memory_current_bytes"] for s in samples) if samples else None,
            "memory_fraction": max(s["memory_current_bytes"] for s in samples) / state["memory"][name] if samples else 0,
        }
    return result


def generator(upstream: Path, runtime: dict, profile: dict, seconds: int, folder: Path,
              kind: str, identity: str, start_ms: int) -> dict:
    folder.mkdir(parents=True, exist_ok=False)
    parent = load(ROOT / runtime["parent_runtime"])
    env = {"DURATION_SECONDS": seconds, "START_AT_MS": start_ms, "K6_LOG_FORMAT": "raw"}
    args = ["docker", "run", "--name", identity, "--user", f"{os.getuid()}:{os.getgid()}",
            "--network", "opentelemetry-demo", "-v", f"{folder.resolve()}:/artifacts",
            "-v", f"{ROOT / ('probe7/k6/' + kind + '.js')}:/scripts/load.js:ro"]
    if kind == "checkout":
        env.update(RATE=profile["checkout_rate"], VUS=runtime["checkout"]["vus"],
                   HTTP_TIMEOUT_SECONDS=runtime["checkout"]["http_timeout_seconds"],
                   PHASE=folder.parent.name, TRIAL_ID=identity, POINT_ID=folder.parent.name)
        write_json(folder / "scenario-config.json", {"rate": profile["checkout_rate"],
            "duration_seconds": seconds, "preAllocatedVUs": env["VUS"], "maxVUs": env["VUS"],
            "http_timeout_seconds": env["HTTP_TIMEOUT_SECONDS"], "timeUnit": "1s", "gracefulStop_seconds": 30})
    else:
        env.update(AD_VUS=profile["ad_vus"], AD_TIMEOUT_SECONDS=runtime["advertising"]["rpc_timeout_seconds"],
                   AD_DEADLINE_MS=runtime["advertising"]["deadline_ms"], AD_ENDPOINT="ad:9555")
        args.extend(["-v", f"{upstream / 'pb'}:/proto:ro"])
        write_json(folder / "scenario-config.json", env)
    for k, v in env.items():
        args.extend(["-e", f"{k}={v}"])
    args.extend([parent["workload"]["k6_image"], "run", "--log-format", "raw"])
    if kind == "checkout":
        args.extend(["--out", "json=/artifacts/raw-metrics.jsonl"])
    args.append("/scripts/load.js")
    start = time.time() * 1000
    completed = command(args, check=False)
    write_json(folder / "run-status.json", {"started_at": start, "ended_at": time.time() * 1000,
                                          "exit_code": completed.returncode})
    (folder / "stdout.log").write_text(completed.stdout, encoding="utf-8")
    (folder / "stderr.log").write_text(completed.stderr, encoding="utf-8")
    command(["docker", "rm", "-f", identity], check=False)
    if kind == "checkout":
        measured = summarize_checkout(folder, rate=profile["checkout_rate"], seconds=seconds,
                    vus=env["VUS"], timeout=env["HTTP_TIMEOUT_SECONDS"],
                    p95_limit=runtime["checkout"]["p95_ms"], error_limit=runtime["checkout"]["error_fraction"])
        measured["acks"] = parse_ack_lines(completed.stdout + "\n" + completed.stderr)
    else:
        measured = advertising(load(folder / "summary.json"), seconds, runtime["advertising"])
    measured["exit_code"] = completed.returncode
    return measured


def phase(upstream: Path, runtime: dict, profile: dict, state: dict, seconds: int,
          folder: Path, samples: Path, identity: str) -> dict:
    folder.mkdir(parents=True, exist_ok=False)
    start_ms = int(time.time() * 1000) + 3000
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        c = pool.submit(generator, upstream, runtime, profile, seconds, folder / "checkout", "checkout", identity + "-c", start_ms)
        a = pool.submit(generator, upstream, runtime, profile, seconds, folder / "advertising", "advertising", identity + "-a", start_ms)
        checkout, ads = c.result(), a.result()
    acks = checkout.pop("acks")
    if len(acks) != checkout["successful_iterations"]:
        raise ValueError("Confirmed-order log differs from the successful-operation counter")
    latest_deadline = max((a["confirmed_ms"] + runtime["accounting"]["deadline_ms"] for a in acks), default=0)
    if latest_deadline > time.time() * 1000:
        time.sleep((latest_deadline - time.time() * 1000) / 1000 + .1)
    ledger = accounting(acks, commit_snapshot(folder), runtime["accounting"])
    write_json(folder / "order-outcomes.json", ledger)
    ledger.pop("orders")
    check = quotas(state)
    reasons = list(check["reasons"])
    if checkout["started_fraction"] < runtime["checkout"]["minimum_started_fraction"]:
        reasons.append("checkout_generator_capacity")
    if checkout["exit_code"] or ads["exit_code"]:
        reasons.append("generator_exit")
    observed = resources(samples, ads["window_start_ms"], ads["window_end_ms"], state)
    checkout_start_ms = None
    with gzip.open(folder / "checkout/raw-metrics.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            point = json.loads(line)
            if point.get("type") == "Point" and point.get("metric") == "protocol_iterations_started":
                checkout_start_ms = dt.datetime.fromisoformat(point["data"]["time"].replace("Z", "+00:00")).timestamp()*1000
                break
    overlap = max(0, min(checkout_start_ms + seconds*1000, ads["window_end_ms"]) -
                  max(checkout_start_ms, ads["window_start_ms"]))/(seconds*1000) if checkout_start_ms is not None else 0
    if overlap < .9:
        reasons.append("concurrent_window_overlap_below_90_percent")
    croom = min(1 - (checkout["p95_ms"] if checkout["p95_ms"] is not None else float("inf")) / runtime["checkout"]["p95_ms"],
                1 - checkout["error_rate"] / runtime["checkout"]["error_fraction"])
    result = {"valid": not reasons, "reasons": reasons,
              "safe": checkout["safe"] and ads["safe"] and ledger["safe"] is True,
              "checkout": checkout, "advertising": ads, "accounting": ledger,
              "headroom": {"checkout": croom, "advertising": ads["headroom"], "accounting": ledger["headroom"]},
              "allocation": state, "resources": observed, "quota_checks": check,
              "window_start_ms": ads["window_start_ms"], "window_end_ms": ads["window_end_ms"],
              "checkout_window_start_ms": checkout_start_ms, "workload_overlap_fraction": overlap}
    write_json(folder / "window.json", result)
    print(json.dumps({"window": folder.name, "valid": result["valid"], "safe": result["safe"],
                      "checkout_p95": checkout["p95_ms"], "ad_goodput": ads["goodput"],
                      "ad_timely": ads["timely_fraction"], "accounting_timely": ledger["timely_fraction"]}), flush=True)
    return result


def history(upstream: Path, spec: dict, profile: dict, state: dict, policy: str, folder: Path,
            pilot: bool = False, pilot_id: int = 1) -> dict:
    runtime = load(ROOT / RUNTIME)
    parent = load(ROOT / runtime["parent_runtime"])
    folder.mkdir(parents=True, exist_ok=False)
    project = "guarded-" + str(os.environ["GITHUB_RUN_ID"]) + "-" + folder.parent.name + "-" + policy
    compose = prefix(upstream, project)
    observations, transitions, blocked = [], [], set()
    baseline_state = {r: dict(q) for r, q in state.items()}
    result = {"policy": policy, "baseline_valid": False, "observations": observations, "transitions": transitions}
    sampler = None
    events_file = (folder / "container-events.jsonl").open("w", encoding="utf-8")
    events_error = (folder / "container-events.stderr.log").open("w", encoding="utf-8")
    events = subprocess.Popen(["docker", "events", "--filter", "type=container",
                               "--filter", "label=com.docker.compose.project=" + project,
                               "--format", "{{json .}}"], stdout=events_file, stderr=events_error)
    try:
        command([*compose, "up", "-d", "--no-build", "--pull", "never"])
        ready = {**parent, "required_running_containers": parent["required_running_containers"] + ["accounting", "kafka"],
                 "mandatory_healthy_containers": parent["mandatory_healthy_containers"] + ["kafka"]}
        engine.wait_for_stack(ready, runtime["health_timeout_seconds"])
        apply(state, None, folder / "limit-updates.jsonl")
        write_json(folder / "initial-quota-checks.json", quotas(state))
        samples = folder / "resource-samples.jsonl"
        write_json(folder / "observer-config.json", {
            "containers": spec["parts"] + [project+"-c", project+"-a"], "output": str(samples), "stop_file": str(folder / ".observer-stop"),
            "interval_seconds": 2, "refresh_seconds": 6})
        sampler = subprocess.Popen(["sudo", "-n", sys.executable, str(ROOT / "probe3/scripts/observe.py"),
                                    "--config", str(folder / "observer-config.json")])
        phase(upstream, runtime, profile, state, spec["warmup_seconds"], folder / "warmup", samples, project)
        previous = phase(upstream, runtime, profile, state, spec["baseline_seconds"], folder / "000", samples, project)
        previous.update(epoch=0, representation=representation(state, load(ROOT / DESIGN)))
        observations.append(previous)
        result["baseline_valid"] = previous["valid"] and previous["safe"]
        if not result["baseline_valid"]:
            result["stop_reason"] = "baseline_not_valid_and_safe"
            return result
        if pilot:
            resources_order = ["cpu", "memory"] if pilot_id == 1 else ["memory", "cpu"]
            plan = []
            for r in resources_order:
                amount = spec["cpu_trial"] if r == "cpu" else spec["memory_trial_mib"] * 2**20
                plan.append({"resource": r, "donor": spec["trial_donor"], "receiver": spec["receiver"], "amount": amount})
                plan.append({"restore": True})
        else:
            plan = [None] * spec["cycles"]
        for epoch, fixed in enumerate(plan, 1):
            before = {r: dict(q) for r, q in state.items()}
            action = fixed if pilot else choose(state, previous, spec, blocked) if policy == "adaptive" else None
            if action and action.get("restore"):
                state = {r: dict(q) for r, q in baseline_state.items()}
            elif action:
                state = proposal(state, **{k: action[k] for k in ("resource", "donor", "receiver", "amount")})
            elif not previous["safe"] and policy == "adaptive":
                state = {r: dict(q) for r, q in baseline_state.items()}
                action = {"restore": True, "reason": "global_requirement_recovery"}
            apply(state, before, folder / "limit-updates.jsonl")
            time.sleep(spec["stabilization_seconds"])
            measured = phase(upstream, runtime, profile, state, spec["measurement_seconds"],
                             folder / f"{epoch:03d}", samples, project)
            measured.update(epoch=epoch, representation=representation(state, load(ROOT / DESIGN)), action=action)
            observations.append(measured)
            transition = {"epoch": epoch, "action": action, "before": before, "trial": state,
                          "window_start_ms": measured["window_start_ms"], "window_end_ms": measured["window_end_ms"],
                          "measured_safe": measured["safe"], "rolled_back": False}
            if action and not action.get("restore") and not pilot:
                margins = list(measured["headroom"].values())
                unsafe = not measured["safe"] or any(v is None or v < spec["controller"]["rollback_headroom"] for v in margins)
                if unsafe:
                    apply(before, state, folder / "limit-updates.jsonl")
                    blocked.add((action["resource"], action["donor"]))
                    state = before
                    transition["rolled_back"] = True
            transition["next_allocation"] = state
            transitions.append(transition)
            previous = measured
            if not measured["valid"]:
                result["stop_reason"] = "measurement_infrastructure_invalid"
                break
        else:
            result["stop_reason"] = "planned_cycles_completed"
    except Exception as exc:
        result["error"] = repr(exc)
        result["stop_reason"] = "runtime_or_measurement_error"
    finally:
        if sampler:
            (folder / ".observer-stop").touch()
            try:
                sampler.wait(timeout=10)
            except subprocess.TimeoutExpired:
                command(["sudo", "-n", "kill", "-TERM", str(sampler.pid)], check=False)
        logs = command([*compose, "logs", "--no-color", "--timestamps", "--tail", "100"], check=False)
        (folder / "compose.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")
        write_json(folder / "final-container-inspect.json", json.loads(command(["docker", "inspect", *spec["parts"]], check=False).stdout or "[]"))
        command([*compose, "down", "--volumes", "--remove-orphans"], check=False)
        events.terminate()
        try:
            events.wait(timeout=5)
        except subprocess.TimeoutExpired:
            events.kill()
            events.wait(timeout=5)
        events_file.close()
        events_error.close()
        write_json(folder / "history.json", result)
        for name in ("resource-samples.jsonl", "container-events.jsonl"):
          if (folder / name).exists():
            with (folder / name).open("rb") as source, gzip.open(folder / (name+".gz"), "wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
            (folder / name).unlink()
    return result


def execute(upstream: Path, output: Path, block_id: str | None, pilot_id: int | None) -> int:
    runtime, main, pilot = load(ROOT / RUNTIME), load(ROOT / DESIGN), load(ROOT / PILOT)
    parent = load(ROOT / runtime["parent_runtime"])
    output.mkdir(parents=True, exist_ok=False)
    for image in sorted({*parent["images"].values(), *runtime["additional_images"].values(), parent["workload"]["k6_image"]}):
        command(["docker", "pull", image])
    rendered = json.loads(command([*prefix(upstream, "guarded-render"), "config", "--no-path-resolution", "--format", "json"]).stdout)
    write_json(output / "rendered-compose.json", rendered)
    write_json(output / "image-inspect.json", json.loads(command(["docker", "image", "inspect", *sorted({s["image"] for s in rendered["services"].values() if s.get("profiles") != ["disabled"]})]).stdout))
    if pilot_id:
        spec = pilot
        state = {"cpu": dict(zip(pilot["parts"], pilot["cpu"])), "memory": dict(zip(pilot["parts"], [v * 2**20 for v in pilot["memory_mib"]]))}
        profile = {"checkout_rate": pilot["checkout_rates"][pilot_id - 1], "ad_vus": pilot["ad_vus"]}
        row = {"block_id": f"pilot-{pilot_id:02d}", "profile": profile, "order": ["pilot"]}
        histories = {"pilot": history(upstream, spec, profile, state, "pilot", output / "pilot", True, pilot_id)}
    else:
        if not main["ready"]:
            raise ValueError("Main design has not been finalized after technical feasibility checks")
        row = next(r for r in matrix(main) if r["block_id"] == block_id)
        profile = next(p for p in main["profiles"] if p["id"] == row["profile"])
        state = initial_state(main, row["initial_state"])
        histories = {p: history(upstream, main, profile, state, p, output / p) for p in row["order"]}
    write_json(output / "block.json", {**row, "histories": histories, "mode": "pilot" if pilot_id else "main",
               "execution_commit": os.environ["GITHUB_SHA"], "run_id": os.environ["GITHUB_RUN_ID"],
               "runtime_version": runtime["version"], "design": spec if pilot_id else main,
               "runner_image": os.getenv("ImageVersion")})
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["matrix", "run"])
    parser.add_argument("--upstream-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--block-id")
    parser.add_argument("--pilot-id", type=int)
    args = parser.parse_args()
    if args.command == "matrix":
        print(json.dumps({"include": matrix(load(ROOT / DESIGN))}))
    else:
        raise SystemExit(execute(args.upstream_dir.resolve(), args.output_dir.resolve(), args.block_id, args.pilot_id))


if __name__ == "__main__":
    main()
