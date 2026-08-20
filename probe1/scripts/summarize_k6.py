from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from experimentlib import classify_slo, type7_quantile, write_json


def _counter_value(point: dict[str, Any]) -> float:
    data = point.get("data", {})
    value = data.get("value", 0)
    return float(value) if isinstance(value, (int, float)) else 0.0


def summarize_compact(phase_dir: Path, rate: int, duration_seconds: int) -> dict[str, Any]:
    required = (
        phase_dir / "compact-primary.json",
        phase_dir / "summary.json",
        phase_dir / "run-status.json",
        phase_dir / "scenario-config.json",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ValueError(f"missing primary files: {missing}")

    try:
        json.loads((phase_dir / "summary.json").read_text(encoding="utf-8"))
        run_status = json.loads((phase_dir / "run-status.json").read_text(encoding="utf-8"))
        scenario = json.loads((phase_dir / "scenario-config.json").read_text(encoding="utf-8"))
        compact = json.loads((phase_dir / "compact-primary.json").read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid primary JSON: {exc}") from exc

    if scenario.get("rate") != rate or scenario.get("duration_seconds") != duration_seconds:
        raise ValueError("scenario config differs from requested rate/duration")
    if scenario.get("preAllocatedVUs") != 320 or scenario.get("maxVUs") != 320:
        raise ValueError("scenario config does not use static 320 VUs")

    if compact.get("schema_version") != 1:
        raise ValueError("unsupported compact primary schema")
    checkout_durations = compact.get("checkout_durations_ms")
    if not isinstance(checkout_durations, list) or not all(isinstance(value, (int, float)) for value in checkout_durations):
        raise ValueError("compact checkout durations are invalid")
    successful_int = int(compact.get("successful_iterations", -1))
    started = int(compact.get("protocol_iterations_started", -1))
    checkout_started = int(compact.get("checkout_requests_started", -1))
    k6_reported_dropped = int(compact.get("k6_reported_dropped_iterations", -1))
    scheduled = rate * duration_seconds
    dropped_int = scheduled - started
    if not 0 <= started <= scheduled:
        raise ValueError(f"invalid started count: scheduled={scheduled}, dropped={dropped_int}")
    if not 0 <= successful_int <= started:
        raise ValueError(f"invalid successful count: {successful_int}")
    if checkout_started != len(checkout_durations):
        raise ValueError(f"checkout request counter differs from durations: {checkout_started} != {len(checkout_durations)}")
    if k6_reported_dropped < 0:
        raise ValueError("invalid k6 dropped-iteration count")
    p95 = type7_quantile([float(value) for value in checkout_durations], 0.95)
    slo = classify_slo(p95, successful_int, scheduled)
    return {
        **slo,
        "scheduled_iterations": scheduled,
        "started_iterations": started,
        "successful_iterations": successful_int,
        "dropped_iterations": dropped_int,
        "k6_reported_dropped_iterations": k6_reported_dropped,
        "checkout_requests": len(checkout_durations),
        "k6_exit_code": run_status.get("exit_code"),
        "k6_completed": run_status.get("completed") is True,
        "raw_metric_lines": int(compact.get("source_raw_metric_lines", 0)),
        "vus_observed_max": float(compact.get("vus_observed_max", 0.0)),
        "vus_max_observed": float(compact.get("vus_max_observed", 0.0)),
        "trace_sample": compact.get("trace_sample"),
    }


def summarize_phase(phase_dir: Path, rate: int, duration_seconds: int) -> dict[str, Any]:
    raw_path = phase_dir / "raw-metrics.jsonl"
    if not raw_path.is_file():
        raise ValueError(f"missing primary file: {raw_path}")
    checkout_durations: list[float] = []
    successful = 0.0
    k6_reported_dropped = 0.0
    protocol_started = 0.0
    checkout_started_counter = 0.0
    trace_sample = None
    vus_max_observed = 0.0
    vus_observed = 0.0
    line_count = 0
    with raw_path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            line_count += 1
            try:
                point = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid raw metric at line {number}: {exc}") from exc
            metric = point.get("metric")
            tags = point.get("data", {}).get("tags", {}) or {}
            if metric == "http_req_duration" and tags.get("request_name") == "checkout":
                checkout_durations.append(_counter_value(point))
                if trace_sample is None:
                    trace_sample = {"trace_id": tags.get("trace_id"), "timestamp": point.get("data", {}).get("time")}
            elif metric == "successful_iterations":
                successful += _counter_value(point)
            elif metric == "protocol_iterations_started":
                protocol_started += _counter_value(point)
            elif metric == "dropped_iterations":
                k6_reported_dropped += _counter_value(point)
            elif metric == "checkout_requests_started":
                checkout_started_counter += _counter_value(point)
            elif metric == "vus":
                vus_observed = max(vus_observed, _counter_value(point))
            elif metric == "vus_max":
                vus_max_observed = max(vus_max_observed, _counter_value(point))

    if line_count == 0:
        raise ValueError("raw metrics file is empty")
    compact = {
        "schema_version": 1,
        "source_raw_metric_lines": line_count,
        "checkout_durations_ms": checkout_durations,
        "successful_iterations": int(round(successful)),
        "protocol_iterations_started": int(round(protocol_started)),
        "checkout_requests_started": int(round(checkout_started_counter)),
        "k6_reported_dropped_iterations": int(round(k6_reported_dropped)),
        "vus_observed_max": vus_observed,
        "vus_max_observed": vus_max_observed,
        "trace_sample": trace_sample,
    }
    write_json(phase_dir / "compact-primary.json", compact)
    result = summarize_compact(phase_dir, rate, duration_seconds)
    raw_path.unlink()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase_dir", type=Path)
    parser.add_argument("--rate", required=True, type=int)
    parser.add_argument("--duration-seconds", required=True, type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = summarize_phase(args.phase_dir, args.rate, args.duration_seconds)
    if args.output:
        write_json(args.output, result)
    else:
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
