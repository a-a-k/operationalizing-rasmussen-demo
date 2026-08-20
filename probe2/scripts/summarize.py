from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Sequence

from common import write_json


def type7_quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


def _value(point: dict[str, Any]) -> float:
    value = point.get("data", {}).get("value", 0)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _read_required_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"missing or empty primary file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"primary file is not an object: {path}")
    return value


def summarize_phase(
    phase_dir: Path,
    *,
    rate: int,
    duration_seconds: int,
    expected_vus: int,
    slo_p95_ms: float,
    slo_error_rate: float,
) -> dict[str, Any]:
    raw_path = phase_dir / "raw-metrics.jsonl"
    if not raw_path.is_file() or raw_path.stat().st_size == 0:
        raise ValueError(f"missing or empty primary stream: {raw_path}")
    summary = _read_required_json(phase_dir / "summary.json")
    run_status = _read_required_json(phase_dir / "run-status.json")
    scenario = _read_required_json(phase_dir / "scenario-config.json")
    if scenario.get("rate") != rate or scenario.get("duration_seconds") != duration_seconds:
        raise ValueError("recorded scenario differs from point specification")
    if scenario.get("preAllocatedVUs") != expected_vus or scenario.get("maxVUs") != expected_vus:
        raise ValueError("recorded scenario differs from frozen VU capacity")

    checkout_durations: list[float] = []
    successful = started = checkout_started = reported_dropped = 0.0
    vus_observed = vus_max_observed = 0.0
    trace_sample = None
    source_lines = 0
    with raw_path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            source_lines += 1
            try:
                point = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid raw metric at line {number}: {exc}") from exc
            metric = point.get("metric")
            tags = point.get("data", {}).get("tags", {}) or {}
            if metric == "http_req_duration" and tags.get("request_name") == "checkout":
                checkout_durations.append(_value(point))
                if trace_sample is None:
                    trace_sample = {"trace_id": tags.get("trace_id"), "timestamp": point.get("data", {}).get("time")}
            elif metric == "successful_iterations":
                successful += _value(point)
            elif metric == "protocol_iterations_started":
                started += _value(point)
            elif metric == "checkout_requests_started":
                checkout_started += _value(point)
            elif metric == "dropped_iterations":
                reported_dropped += _value(point)
            elif metric == "vus":
                vus_observed = max(vus_observed, _value(point))
            elif metric == "vus_max":
                vus_max_observed = max(vus_max_observed, _value(point))
    if source_lines == 0:
        raise ValueError("raw primary stream has no observations")

    scheduled = rate * duration_seconds
    started_int = int(round(started))
    checkout_started_int = int(round(checkout_started))
    successful_int = int(round(successful))
    if not 0 <= successful_int <= started_int <= scheduled:
        raise ValueError("iteration counters violate 0 <= successful <= started <= scheduled")
    if checkout_started_int != len(checkout_durations):
        raise ValueError("checkout duration count differs from checkout request counter")
    p95 = type7_quantile(checkout_durations, 0.95)
    error_count = scheduled - successful_int
    error_rate = error_count / scheduled
    safe = p95 is not None and p95 <= slo_p95_ms and error_rate < slo_error_rate
    compact = {
        "schema_version": 1,
        "source_raw_metric_lines": source_lines,
        "checkout_durations_ms": checkout_durations,
        "successful_iterations": successful_int,
        "protocol_iterations_started": started_int,
        "checkout_requests_started": checkout_started_int,
        "k6_reported_dropped_iterations": int(round(reported_dropped)),
        "vus_observed_max": vus_observed,
        "vus_max_observed": vus_max_observed,
        "trace_sample": trace_sample,
    }
    write_json(phase_dir / "compact-primary.json", compact)
    raw_path.unlink()
    return {
        "safe": safe,
        "p95_ms": p95,
        "error_count": error_count,
        "error_rate": error_rate,
        "scheduled_iterations": scheduled,
        "started_iterations": started_int,
        "started_fraction": started_int / scheduled,
        "successful_iterations": successful_int,
        "dropped_iterations": scheduled - started_int,
        "k6_reported_dropped_iterations": int(round(reported_dropped)),
        "checkout_requests": checkout_started_int,
        "vus_observed_max": vus_observed,
        "vus_max_observed": vus_max_observed,
        "k6_exit_code": run_status.get("exit_code"),
        "k6_completed": run_status.get("completed") is True,
        "trace_sample": trace_sample,
        "summary_metric_names": sorted(summary.get("metrics", {}).keys()),
    }
