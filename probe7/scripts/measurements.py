from __future__ import annotations

import math
import re


def quantile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * p
    low, high = math.floor(position), math.ceil(position)
    return values[low] + (position - low) * (values[high] - values[low])


def advertising(summary: dict, seconds: int, policy: dict) -> dict:
    def counter(name):
        value = summary["metrics"][name]["values"]["count"]
        if not math.isfinite(value) or value < 0 or int(value) != value:
            raise ValueError("Invalid advertising counter")
        return int(value)
    attempts, finished, timely, useful = [counter("ad_" + n) for n in
                                         ("attempts", "finished", "timely", "useful_inside_window")]
    if not 0 <= timely <= finished <= attempts or not 0 <= useful <= finished:
        raise ValueError("Advertising counter invariant failed")
    fraction = timely / attempts if attempts else None
    tail = summary["metrics"].get("ad_latency_ms", {}).get("values", {}).get("p(99)")
    safe = fraction is not None and fraction >= policy["minimum_timely_fraction"]
    headroom = min((fraction - policy["minimum_timely_fraction"]) /
                   (1 - policy["minimum_timely_fraction"]),
                   1 - tail / policy["deadline_ms"]) if fraction is not None and tail is not None else None
    start = summary["metrics"]["ad_window_start_ms"]["values"]["min"]
    return {"attempts": attempts, "finished": finished, "timely": timely,
            "unfinished": attempts - finished, "timely_fraction": fraction,
            "p99_ms": tail, "goodput": useful / seconds, "safe": safe,
            "headroom": headroom, "window_start_ms": start,
            "window_end_ms": start + seconds * 1000}


def accounting(acks: list[dict], commits: dict[str, float], policy: dict) -> dict:
    ids = [a["order_id"] for a in acks]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate confirmed order identifier")
    records, latencies = [], []
    for ack in acks:
        stamp = commits.get(ack["order_id"])
        lag = max(0.0, stamp - ack["confirmed_ms"]) if stamp is not None else None
        timely = lag is not None and lag <= policy["deadline_ms"]
        records.append({**ack, "commit_ms": stamp, "lag_ms": lag, "timely": timely})
        if lag is not None:
            latencies.append(lag)
    n = len(acks)
    timely = sum(r["timely"] for r in records)
    fraction = timely / n if n else None
    tail = quantile(latencies, .99)
    headroom = min((fraction - policy["minimum_timely_fraction"]) /
                   (1 - policy["minimum_timely_fraction"]),
                   1 - tail / policy["deadline_ms"]) if fraction is not None and tail is not None else None
    return {"confirmed": n, "timely": timely, "missing": sum(r["commit_ms"] is None for r in records),
            "late": sum(r["commit_ms"] is not None and not r["timely"] for r in records),
            "timely_fraction": fraction, "p99_observed_lag_ms": tail,
            "safe": fraction >= policy["minimum_timely_fraction"] if fraction is not None else None,
            "headroom": headroom, "orders": records}


def parse_ack_lines(text: str) -> list[dict]:
    import json
    return [json.loads(match.group(1)) for match in re.finditer(r"ORDER_ACK\s+(\{[^\r\n]*\})", text)]
