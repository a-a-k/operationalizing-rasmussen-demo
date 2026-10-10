from __future__ import annotations

import gzip
import json
import math
from pathlib import Path
from typing import Any

from study import write_json


def quantile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


def summarize(folder: Path, *, rate: int, seconds: int, vus: int, timeout: int,
              p95_limit: float, error_limit: float) -> dict[str, Any]:
    scenario = json.loads((folder / "scenario-config.json").read_text())
    status = json.loads((folder / "run-status.json").read_text())
    json.loads((folder / "summary.json").read_text())
    expected = {"rate": rate, "duration_seconds": seconds, "preAllocatedVUs": vus,
                "maxVUs": vus, "http_timeout_seconds": timeout, "timeUnit": "1s",
                "gracefulStop_seconds": 30}
    if any(scenario.get(k) != v for k, v in expected.items()):
        raise ValueError("recorded executor differs from the fixed workload")
    counters = {k: 0.0 for k in (
        "protocol_iterations_started", "protocol_iterations_finished",
        "successful_iterations", "checkout_requests_started", "dropped_iterations",
    )}
    durations: list[float] = []
    operation_durations: list[float] = []
    vus_peak = 0.0
    lines = 0
    raw_path = folder / "raw-metrics.jsonl"
    with raw_path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            lines += 1
            point = json.loads(line)
            if point.get("type") != "Point":
                continue
            metric, data = point["metric"], point["data"]
            value = float(data["value"])
            if not math.isfinite(value):
                raise ValueError("non-finite primary observation")
            if metric in counters:
                counters[metric] += value
            elif metric == "http_req_duration" and data.get("tags", {}).get("request_name") == "checkout":
                durations.append(value)
            elif metric == "protocol_iteration_duration":
                operation_durations.append(value)
            elif metric == "vus":
                vus_peak = max(vus_peak, value)
    if lines == 0:
        raise ValueError("empty primary stream")
    if any(value != round(value) for value in counters.values()):
        raise ValueError("non-integer iteration counter")
    started = int(counters["protocol_iterations_started"])
    finished = int(counters["protocol_iterations_finished"])
    successes = int(counters["successful_iterations"])
    checkout_started = int(counters["checkout_requests_started"])
    scheduled = rate * seconds
    if not 0 <= successes <= finished <= started <= scheduled:
        raise ValueError("iteration counter invariant failed")
    if not 0 <= len(durations) <= checkout_started <= started:
        raise ValueError("checkout counter invariant failed")
    if len(operation_durations) != finished:
        raise ValueError("completed-operation durations differ from finished counter")
    # Mutually exclusive categories; timeouts are already failures.
    failed, dropped, unfinished = finished - successes, scheduled - started, started - finished
    error_count = failed + dropped + unfinished
    p95 = quantile(durations, 0.95)
    error_rate = error_count / scheduled
    compact = {
        "schema_version": 1, "checkout_durations_ms": durations,
        "operation_durations_ms": operation_durations,
        "counters": counters, "source_metric_lines": lines,
    }
    write_json(folder / "compact-primary.json", compact)
    # Preserve timestamps, response failures and generator metrics for diagnosis.
    # This is lossless compression, not the historical deletion of the raw stream.
    with raw_path.open("rb") as source, (folder / "raw-metrics.jsonl.gz").open("wb") as target:
        with gzip.GzipFile(fileobj=target, mode="wb", mtime=0) as compressed:
            while chunk := source.read(1024 * 1024):
                compressed.write(chunk)
    raw_path.unlink()
    return {
        "safe": p95 is not None and p95 <= p95_limit and error_rate < error_limit,
        "p95_ms": p95, "error_rate": error_rate, "error_count": error_count,
        "scheduled_iterations": scheduled, "started_iterations": started,
        "finished_iterations": finished, "successful_iterations": successes,
        "failed_iterations": failed, "dropped_iterations": dropped,
        "unfinished_iterations": unfinished, "started_fraction": started / scheduled,
        "checkout_requests_started": checkout_started, "checkout_requests_completed": len(durations),
        "k6_reported_dropped_iterations": int(counters["dropped_iterations"]),
        "operation_p95_ms": quantile(operation_durations, 0.95),
        "operation_max_ms": max(operation_durations) if operation_durations else None,
        "vus_observed_max": vus_peak, "k6_exit_code": status["exit_code"],
        "latency_population": "All completed checkout HTTP requests, including failed responses and timeouts; includes completions during the 30-second graceful stop.",
    }
