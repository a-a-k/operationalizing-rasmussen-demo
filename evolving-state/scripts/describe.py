"""Descriptive interpretation of preserved calls, policies and relative states."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import statistics

from analyze import client_responses, lines, save


def describe(directory):
    events = lines(directory / "journals/client.jsonl")
    applied = [e for e in events if e["type"] == "configuration_applied"]
    configs = {e["config"]["version"]: e["config"] for e in applied}
    changes = [(a["config"], b["config"]) for a, b in zip(applied, applied[1:])
               if a["config"]["max_attempts"] != b["config"]["max_attempts"]
               and a["config"]["fault_probability"] == b["config"]["fault_probability"]]
    if len(changes) != 1:
        raise ValueError("Expected one isolated attempt-allowance intervention")
    before, after = changes[0]
    clients = {r["logical_id"]: r for r in client_responses(directory)}
    starts = {r["logical_id"]: r for r in events if r["type"] == "logical_start"}
    attempts = [r for r in events if r["type"] == "attempt_start"]
    outcomes = {(r["logical_id"], r["attempt"]): r for r in events if r["type"] == "attempt_end"}
    cohorts = []
    for config in (before, after):
        calls = {key for key, row in starts.items()
                 if configs[row["configuration"]]["max_attempts"] == config["max_attempts"]
                 and configs[row["configuration"]]["fault_probability"] == config["fault_probability"]}
        measured = [clients[key] for key in sorted(calls) if key in clients]
        physical = [r for r in attempts if r["logical_id"] in calls]
        first = sum(r["attempt"] == 0 for r in physical)
        retry = len(physical) - first
        third = [r for r in physical if r["attempt"] == 2]
        rescued = [r for r in third if outcomes.get((r["logical_id"], 2), {}).get("status") == 200
                   and all(outcomes.get((r["logical_id"], k), {}).get("status", 200) != 200 for k in (0, 1))
                   and clients.get(r["logical_id"], {}).get("status") == 200]
        cohorts.append({"max_attempts": config["max_attempts"], "fault_probability": config["fault_probability"],
                        "logical_calls": len(calls), "client_observed_calls": len(measured),
                        "client_successes": sum(r["status"] == 200 for r in measured),
                        "success_fraction": sum(r["status"] == 200 for r in measured) / len(measured) if measured else None,
                        "attempt_starts": len(physical), "retry_starts": retry,
                        "retry_fraction": retry / len(physical) if physical else None,
                        "third_attempts": len(third), "third_attempt_rescues": len(rescued)})
    observations = [record["rows"][2] for record in lines(directory / "diagnoses.jsonl")]
    policy_delays = []
    for a, b in zip(applied, applied[1:]):
        version = b["config"]["policy_version"]
        if version == a["config"]["policy_version"]:
            continue
        candidates = [r for r in observations if r["diagnosed_ms"] >= b["applied_ms"]
                      and r["policy_used"] == r["policy_announced"] == version
                      and all(g["status"] == "available" for g in r["groups"].values())]
        policy_delays.append({"policy_version": version,
                              "correct_report_after_apply_ms": min(r["diagnosed_ms"] for r in candidates) - b["applied_ms"] if candidates else None})
    witnesses = []
    for a, b in zip(observations, observations[1:]):
        if a["window"] != b["window"] or a["policy_used"] == b["policy_used"]:
            continue
        if any(x["status"] != "available" for row in (a, b) for x in row["groups"].values()):
            continue
        same = all(a["groups"][g][k] == b["groups"][g][k] for g in ("catalog", "currency") for k in ("first", "retry"))
        if not same:
            continue
        if a["geometry"] and b["geometry"] and a["geometry"]["ilr"] != b["geometry"]["ilr"]:
            raise ValueError("A policy-only edit moved the reconstructed composition")
        witnesses.append({"window": b["window"], "from_policy": a["policy_used"], "to_policy": b["policy_used"],
                          "state_unchanged": True,
                          "policy_decision_changed": any(a["groups"][g]["violation"] != b["groups"][g]["violation"]
                                                        for g in ("catalog", "currency")),
                          "before": a["groups"], "after": b["groups"]})
    return {"block": json.loads((directory / "status.json").read_text())["block"],
            "allowance_cohorts": cohorts,
            "clients_without_gateway_start": len(set(clients) - set(starts)),
            "same_window_policy_only_witnesses": witnesses,
            "policy_update_latencies": policy_delays,
            "geometry_status_counts": dict(Counter(r["geometry_status"] for r in observations)),
            "limits": "Cohorts span different times and include later policy/component changes with the same fault setting. Their rate comparison is descriptive, not a randomized causal estimate. Third-attempt rescues are directly recorded within-request witnesses under controlled delivery faults; they do not estimate production benefit."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    blocks = [describe(p.parent) for p in sorted((args.bundle / "inputs").rglob("status.json"))
              if json.loads(p.read_text())["complete"]]
    summaries = json.loads((args.bundle / "analysis/summary.json").read_text())["histories"]
    methods = {}
    for method in ("fixed", "direct", "coda"):
        methods[method] = {key: sum(r["methods"][method][key] for r in summaries) for key in
                           ("group_diagnoses", "trustworthy_group_diagnoses", "policy_errors", "state_errors")}
        methods[method]["status_counts"] = dict(sum((Counter(r["methods"][method]["status_counts"]) for r in summaries), Counter()))
        times = [r["methods"][method]["median_compute_microseconds"] for r in summaries]
        methods[method]["per_history_median_compute_microseconds"] = {
            "median": statistics.median(times), "min": min(times), "max": max(times)}
    result = {"histories": blocks, "methods": methods,
              "same_window_policy_only_witnesses": sum(len(b["same_window_policy_only_witnesses"]) for b in blocks),
              "same_window_policy_decision_flips": sum(w["policy_decision_changed"] for b in blocks
                                                       for w in b["same_window_policy_only_witnesses"]),
              "third_attempt_rescues": sum(b["allowance_cohorts"][1]["third_attempt_rescues"] for b in blocks),
              "third_attempts": sum(b["allowance_cohorts"][1]["third_attempts"] for b in blocks),
              "cohort_success_fraction_increased_histories": sum(b["allowance_cohorts"][1]["success_fraction"] > b["allowance_cohorts"][0]["success_fraction"] for b in blocks),
              "cohort_retry_fraction_increased_histories": sum(b["allowance_cohorts"][1]["retry_fraction"] > b["allowance_cohorts"][0]["retry_fraction"] for b in blocks),
              "geometry_status_counts": dict(sum((Counter(b["geometry_status_counts"]) for b in blocks), Counter())),
              "statistical_unit": "history; no binomial confidence interval treats dependent windows as independent"}
    save(args.bundle / "analysis/interpretation-stats.json", result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("histories", "methods")}))


if __name__ == "__main__":
    main()
