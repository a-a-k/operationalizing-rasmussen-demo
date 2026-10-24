"""Read-only cgroup/host sampler, run with sudo on an ephemeral Actions runner."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import time
from pathlib import Path


def counters(path: Path) -> dict[str, int]:
    return {key: int(value) for key, value in
            (line.split() for line in path.read_text().splitlines())}


def checked_delta(previous: dict | None, current: dict, elapsed: float) -> dict | None:
    if previous is None or previous["identity"] != current["identity"] or elapsed <= 0:
        return None
    if any(current["cpu"].get(k, 0) < v for k, v in previous["cpu"].items()):
        return None
    delta = {key: value - previous["cpu"].get(key, 0) for key, value in current["cpu"].items()}
    periods = delta.get("nr_periods", 0)
    return {
        "cpu_seconds": delta.get("usage_usec", 0) / 1e6,
        "cpu_cores": delta.get("usage_usec", 0) / (1e6 * elapsed),
        "throttled_period_fraction": delta.get("nr_throttled", 0) / periods if periods > 0 else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    registry: dict = {}
    previous: dict = {}
    last_refresh = last_sample = 0.0
    prior_host = None
    with Path(config["output"]).open("w", encoding="utf-8", buffering=1) as stream:
        while not Path(config["stop_file"]).exists():
            now = time.monotonic()
            frame = {"timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                     "monotonic_seconds": now, "containers": {}}
            if now - last_refresh >= config["refresh_seconds"]:
                try:
                    result = subprocess.run(["docker", "inspect", *config["containers"]],
                                            capture_output=True, text=True, timeout=5, check=False)
                    registry = {item["Name"].lstrip("/"): item for item in json.loads(result.stdout)}
                except Exception as exc:
                    frame["registry_error"] = repr(exc)
                last_refresh = now
            host = [int(v) for v in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
            total, idle = sum(host), host[3] + host[4]
            if prior_host is not None and total > prior_host[0]:
                frame["host_cpu_fraction"] = 1 - (idle - prior_host[1]) / (total - prior_host[0])
            prior_host = (total, idle)
            frame["host_load_average"] = os.getloadavg()
            for name, inspected in registry.items():
                pid = inspected["State"].get("Pid", 0)
                if pid <= 0:
                    continue
                root = Path(f"/proc/{pid}/root/sys/fs/cgroup")
                try:
                    sample = {
                        "identity": [inspected["Id"], pid, root.stat().st_ino],
                        "cpu": counters(root / "cpu.stat"),
                        "memory_events": counters(root / "memory.events"),
                        "memory_current_bytes": int((root / "memory.current").read_text()),
                        "memory_max": (root / "memory.max").read_text().strip(),
                        "restart_count": inspected["RestartCount"],
                    }
                    sample["delta"] = checked_delta(previous.get(name), sample, now - last_sample)
                    sample["counter_segment_start"] = sample["delta"] is None
                    frame["containers"][name] = sample
                    previous[name] = sample
                except (OSError, ValueError) as exc:
                    frame["containers"][name] = {"sample_error": repr(exc)}
                    previous.pop(name, None)
            stream.write(json.dumps(frame, separators=(",", ":")) + "\n")
            last_sample = now
            time.sleep(config["interval_seconds"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
