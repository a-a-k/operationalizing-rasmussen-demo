"""Independent event reconstruction and paired diagnostic assessment."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
import math
from pathlib import Path
import statistics

from observer import Observer


def lines(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def oracle(events, snapshot, origin, width):
    # Group membership is the logical operation in individual client events,
    # not the observer's component registry or its aggregate counters.
    start = origin + (snapshot["window"] - 1) * width
    end = start + width
    count = Counter((e["logical_group"], "retry" if e["attempt"] else "first")
                    for e in events if e["type"] == "attempt_start"
                    and start <= e["started_ms"] < end)
    applied = [e for e in events if e["type"] == "configuration_applied"
               and e["applied_ms"] <= snapshot["generated_ms"]]
    config = max(applied, key=lambda e: e["applied_ms"])["config"]
    groups = {}
    for group in ("catalog", "currency"):
        first, retry = count[group, "first"], count[group, "retry"]
        ratio = retry / (first + retry) if first + retry else None
        rho = config["policy_limits"][group]
        groups[group] = {"first": first, "retry": retry, "ratio": ratio, "rho": rho,
                         "margin": rho - ratio if ratio is not None else None,
                         "violation": ratio > rho + 1e-12 if ratio is not None else None}
    return {"groups": groups, "policy_version": config["policy_version"]}


def compare(directory):
    status = json.loads((directory / "status.json").read_text())
    if not status["complete"]:
        return {"block": status["block"], "complete": False, "error": status["error"]}, [], []
    cfg = json.loads((directory / "load-config.json").read_text())
    events = lines(directory / "journals/client.jsonl")
    inputs = lines(directory / "observer-inputs.jsonl")
    diagnoses = lines(directory / "diagnoses.jsonl")
    if len(inputs) != len(diagnoses):
        raise ValueError("Observation/diagnosis recording mismatch")
    initial = json.loads((directory / "initial-metadata.json").read_text())
    replay = [Observer(mode, initial, cfg["ewma_alpha"]) for mode in ("fixed", "direct", "coda")]
    records, geometric = [], []
    previous_truth, previous_rows = None, {}
    disagreements = 0
    expected_windows = set(range(1, cfg["windows"] + 1))
    actual_windows = {i["snapshot"]["window"] for i in inputs}
    truth_by_input = []
    for item, observed in zip(inputs, diagnoses):
        snapshot = item["snapshot"]
        truth = oracle(events, snapshot, cfg["origin_ms"], cfg["window_seconds"] * 1000)
        truth_by_input.append(truth)
        reproduced = [o.update(snapshot, item["metadata"]) for o in replay]
        for a, b in zip(observed["rows"], reproduced):
            if {k: v for k, v in a.items() if k != "compute_ns"} != {k: v for k, v in b.items() if k != "compute_ns"}:
                raise ValueError("Live/prefix replay mismatch")
        direct, coda = observed["rows"][1:]
        if direct["groups"] != coda["groups"]:
            disagreements += 1
        if coda.get("geometry"):
            geometric.append({"block": status["block"], "window": snapshot["window"],
                              "observed_ms": snapshot["received_ms"], **coda["geometry"]})
        for row in observed["rows"]:
            for group, current in row["groups"].items():
                actual = truth["groups"][group]
                comparable = current["status"] == "available" and actual["ratio"] is not None
                state_error = (abs(current["first"] - actual["first"]) +
                               abs(current["retry"] - actual["retry"])) if current["first"] is not None else None
                margin_error = abs(current["margin"] - actual["margin"]) if comparable else None
                violation_error = current["violation"] != actual["violation"] if comparable else None
                old = previous_rows.get((row["mode"], group))
                delta_error, ratio_delta_error, policy_delta_error = None, None, None
                if current["delta_margin"] is not None and previous_truth and old:
                    expected = actual["margin"] - previous_truth["groups"][group]["margin"]
                    delta_error = abs(current["delta_margin"] - expected)
                    ratio_delta_error = abs(current["delta_ratio"] - (
                        actual["ratio"] - previous_truth["groups"][group]["ratio"]))
                    policy_delta_error = abs(current["delta_policy"] - (
                        actual["rho"] - previous_truth["groups"][group]["rho"]))
                correct = comparable and state_error == 0 and margin_error <= 1e-12 and not violation_error
                records.append({"block": status["block"], "window": snapshot["window"],
                                "received_ms": snapshot["received_ms"], "mode": row["mode"],
                                "group": group, "status": current["status"],
                                "state_error": state_error, "margin_error": margin_error,
                                "policy_error": violation_error, "delta_margin_error": delta_error,
                                "delta_ratio_error": ratio_delta_error, "delta_policy_error": policy_delta_error,
                                "trustworthy": bool(correct), "compute_ns": row["compute_ns"],
                                "ratio": actual["ratio"], "rho": actual["rho"],
                                "reported_ratio": current["ratio"], "reported_rho": current["rho"],
                                "geometry_status": row["geometry_status"]})
                previous_rows[row["mode"], group] = current
        previous_truth = truth
    attempts = [e for e in events if e["type"] == "attempt_start"]
    ids = [(e["logical_id"], e["attempt"]) for e in attempts]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate client attempt identity")
    forwarded = [e for p in (directory / "journals").glob("reader-*.jsonl") for e in lines(p)]
    forward_ids = [(e["logical_id"], e["attempt"]) for e in forwarded]
    if len(forward_ids) != len(set(forward_ids)) or set(forward_ids) - set(ids):
        raise ValueError("Duplicate or unmatched forwarded attempt")
    logical = [e for e in events if e["type"] == "logical_end"]
    states = {}
    for mode in ("fixed", "direct", "coda"):
        rows = [r for r in records if r["mode"] == mode]
        states[mode] = {
            "group_diagnoses": len(rows), "status_counts": dict(Counter(r["status"] for r in rows)),
            "trustworthy_group_diagnoses": sum(r["trustworthy"] for r in rows),
            "policy_errors": sum(r["policy_error"] is True for r in rows),
            "state_errors": sum(r["state_error"] not in (None, 0) for r in rows),
            "maximum_margin_error": max((r["margin_error"] or 0 for r in rows), default=0),
            "maximum_delta_margin_error": max((r["delta_margin_error"] or 0 for r in rows), default=0),
            "maximum_delta_ratio_error": max((r["delta_ratio_error"] or 0 for r in rows), default=0),
            "maximum_delta_policy_error": max((r["delta_policy_error"] or 0 for r in rows), default=0),
            "median_compute_microseconds": statistics.median(r["compute_ns"] / 1000 for r in rows),
        }
        # A held report can become stale before the next poll. Split intervals at
        # actual policy applications and completed-window boundaries.
        spans = {"total_ms": 0., "trustworthy_ms": 0., "unavailable_ms": 0., "incorrect_ms": 0.}
        for i, (item, result) in enumerate(zip(inputs, diagnoses)):
            start = item["snapshot"]["received_ms"]
            stop = (inputs[i + 1]["snapshot"]["received_ms"] if i + 1 < len(inputs)
                    else cfg["origin_ms"] + cfg["windows"] * cfg["window_seconds"] * 1000 + 1200)
            selected = [r for r in rows if r["received_ms"] == start]
            cuts = [start, max(start, stop)]
            cuts += [e["applied_ms"] for e in events if e["type"] == "configuration_applied"
                     and start < e["applied_ms"] < stop]
            cuts += [cfg["origin_ms"] + w * cfg["window_seconds"] * 1000
                     for w in range(1, cfg["windows"] + 1)
                     if start < cfg["origin_ms"] + w * cfg["window_seconds"] * 1000 < stop]
            for left, right in zip(sorted(set(cuts)), sorted(set(cuts))[1:]):
                middle = (left + right) / 2
                latest_window = min(cfg["windows"], math.floor(
                    (middle - cfg["origin_ms"]) / (cfg["window_seconds"] * 1000)))
                at_time = oracle(events, {**item["snapshot"], "window": latest_window,
                                         "generated_ms": middle},
                                 cfg["origin_ms"], cfg["window_seconds"] * 1000)
                duration = right - left
                spans["total_ms"] += duration
                current_correct = all(
                    r["trustworthy"] and r["window"] == latest_window
                    and abs(r["reported_rho"] - at_time["groups"][r["group"]]["rho"]) < 1e-12
                    for r in selected)
                key = ("trustworthy_ms" if current_correct else "unavailable_ms"
                       if any(r["status"] != "available" for r in selected) else "incorrect_ms")
                spans[key] += duration
        states[mode]["held_diagnosis_time"] = spans
    # Applied-to-first-correct reporting latency, without consulting intended event labels.
    updates = [e for e in events if e["type"] == "configuration_applied"]
    latency = []
    for event_index, event in enumerate(updates[1:], 1):
        at = event["applied_ms"]
        old_config = updates[event_index - 1]["config"]
        representation_changed = event["config"]["deployment"] != old_config["deployment"]
        next_update = updates[event_index + 1]["applied_ms"] if event_index + 1 < len(updates) else math.inf
        for mode in ("fixed", "direct", "coda"):
            # For lineage updates require a window actually containing new components.
            candidates = [i for i, item in enumerate(inputs)
                          if item["snapshot"]["received_ms"] >= at
                          and item["snapshot"]["received_ms"] < next_update
                          and item["snapshot"]["configuration_version"] >= event["config"]["version"]]
            first, exposure = None, None
            for i in candidates:
                snap = inputs[i]["snapshot"]
                if representation_changed and not any(r["deployment"] == event["config"]["deployment"]
                                                      for r in snap["counts"]):
                    continue
                if exposure is None:
                    exposure = snap["received_ms"]
                relevant = [r for r in records if r["mode"] == mode and r["received_ms"] == snap["received_ms"]]
                policy_matches = diagnoses[i]["rows"][("fixed", "direct", "coda").index(mode)]["policy_used"] == event["config"]["policy_version"]
                if policy_matches and all(r["trustworthy"] for r in relevant):
                    first = snap["received_ms"] - at
                    break
            latency.append({"configuration": event["config"]["version"], "mode": mode,
                            "representation_changed": representation_changed,
                            "first_exposed_ms": exposure,
                            "first_correct_after_update_ms": first,
                            "first_correct_after_exposure_ms": first - (exposure - at) if first is not None else None,
                            "censored_at_next_update": first is None})
    summary = {"block": status["block"], "complete": True,
               "missing_windows": sorted(expected_windows - actual_windows),
               "observer_input_batches": len(inputs), "direct_coda_disagreements": disagreements,
               "live_prefix_replay": "identical_except_compute_time", "methods": states,
               "update_latencies": latency, "client_attempts": len(attempts),
               "forwarded_attempts": len(forwarded), "attempts_without_worker_receipt": len(set(ids) - set(forward_ids)),
               "upstream_successes": sum(e["upstream_status"] == 200 for e in forwarded),
               "logical_completed": len(logical), "logical_successes": sum(e["status"] == 200 for e in logical),
               "k6_dropped_iterations": json.loads((directory / "k6/summary.json").read_text())["metrics"].get("dropped_iterations", {}).get("values", {}).get("count", 0),
               "explicit_worker_annotations": len(list((directory / "journals").glob("reader-*.jsonl"))),
               "initial_group_annotations": 2,
               "successor_lineage_annotations": max(0, len(list((directory / "journals").glob("reader-*.jsonl"))) - 2),
               "limitation": "Scripted updates and delivery faults; eight descriptive replications planned after engineering."}
    return summary, records, geometric


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summaries, rows, geometry = [], [], []
    for status in sorted(args.inputs.rglob("status.json")):
        summary, records, g = compare(status.parent)
        summaries.append(summary)
        rows.extend(records)
        geometry.extend(g)
    if not summaries:
        raise ValueError("No histories found")
    save(args.output / "summary.json", {"histories": summaries})
    save(args.output / "geometry.json", geometry)
    if rows:
        with (args.output / "diagnostic-comparison.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps({"received_histories": len(summaries),
                      "complete": sum(s["complete"] for s in summaries),
                      "direct_coda_disagreements": sum(s.get("direct_coda_disagreements", 0) for s in summaries)}))


if __name__ == "__main__":
    main()
