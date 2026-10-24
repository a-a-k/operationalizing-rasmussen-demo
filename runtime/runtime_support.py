"""Shared pinned stack and quota helpers for the two retained runtime studies."""
from __future__ import annotations
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ARCHIVED_PATHS = {"probe1/runtime.json": "runtime/base-lock.json",
                  "probe7/runtime-v0.2.0.json": "runtime/cpu-lock.json"}


def runtime_path(label):
    """Resolve the original design's immutable runtime label in this package."""
    return ROOT / ARCHIVED_PATHS.get(label, label)


def compose_prefix(repo, upstream, project):
    return ["docker", "compose", "--project-name", project, "--project-directory", str(upstream),
            "--env-file", str(upstream / ".env"), "--env-file", str(repo / "runtime/otel.env"),
            "-f", str(upstream / "compose.yaml"), "-f", str(repo / "runtime/compose.lock.yaml")]


def prefix(upstream, project):
    args = compose_prefix(ROOT, upstream, project)
    return [*args[:-4], "-f", str(upstream / "compose.yaml"), "-f", str(upstream / "compose.full.yaml"),
            "-f", str(ROOT / "runtime/compose.lock.yaml"), "-f", str(ROOT / "runtime/cpu-overlay.yaml")]


def run(command: list[str], *, check: bool = True, capture: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command), flush=True)
    return subprocess.run(command, check=check, text=True, capture_output=capture, cwd=cwd)


def command(args, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True)


def inspect_container(service: str) -> dict[str, Any]:
    completed = run(["docker", "inspect", service])
    return json.loads(completed.stdout)[0]


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
