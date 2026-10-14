from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path

from live_runner import CAMPAIGN, campaign_matrix
from warning_model import FROZEN, ROOT, WarningModel, alerts, canonical_hash, csv_save, target


def analyze(blocks, model, campaign, commit, run_id):
    planned = {r["block_id"]: r for r in campaign_matrix(campaign)}
    if set(blocks) - set(planned):
        raise ValueError("Unexpected confirmation pair")
    model_hash = canonical_hash(ROOT / FROZEN)
    decisions, histories, events, integrity = [], [], [], []
    for bid, block in sorted(blocks.items()):
        if block["execution_commit"] != commit or str(block["run_id"]) != str(run_id) or block["design"] != campaign:
            raise ValueError("Confirmation provenance differs")
        if block["warning_model"]["sha256_lf"] != model_hash or block["warning_model"]["runtime_mode"] != "observer_only":
            raise ValueError("Warning model differs")
        for key in ("order", "profile", "initial_state", "repetition"):
            if block[key] != planned[bid][key]:
                raise ValueError("Confirmation matrix differs")
        for policy, history in sorted(block["histories"].items()):
            observations = sorted(history["observations"], key=lambda w: w["epoch"])
            baseline_safe = bool(observations and observations[0]["valid"] and observations[0]["safe"])
            first = next((w for w in observations[1:] if w["valid"] and w["safe"] is False), None) if baseline_safe else None
            history_decisions = []
            for i, w in enumerate(observations):
                record = w.get("online_warning")
                fresh = model.score(observations[:i + 1], block["profile"])
                if record is None or record.get("prediction_valid") is not True:
                    integrity.append({"block_id": bid, "policy": policy, "epoch": w["epoch"], "reason": "missing_or_failed_live_prediction"})
                    continue
                if (record["model_sha256_lf"] != model_hash or record["runtime_mode"] != "observer_only"
                        or record["features_available_ms"] != w["primary_available_ms"]
                        or record["epoch"] != w["epoch"] or record["scored_ms"] < w["primary_available_ms"]):
                    raise ValueError("Live prediction chronology/model differs")
                if fresh["eligible"] != record["eligible"] or fresh["reason"] != record["reason"]:
                    raise ValueError("Live eligibility cannot be reproduced")
                if not fresh["eligible"]:
                    continue
                label = target(observations, w["epoch"], model.definition["horizon_cycles"])
                for method, replay in fresh["methods"].items():
                    live = record["methods"][method]
                    if replay["score"] != live["score"] or replay["alert"] != live["alert"] or replay["threshold"] != live["threshold"]:
                        raise ValueError("Live forecast differs from frozen replay")
                    if replay["neighbors"] != live["neighbors"]:
                        raise ValueError("Live neighbors differ")
                    row = {"block_id": bid, "policy": policy, "profile": block["profile"], "epoch": w["epoch"],
                           "method": method, "score": live["score"], "threshold": live["threshold"], "alert": live["alert"],
                           "future_label": label, "features_available_ms": w["primary_available_ms"],
                           "scored_ms": record["scored_ms"], "prediction_duration_ms": record["prediction_duration_ms"],
                           "neighbor_pairs": live["neighbor_pairs"]}
                    decisions.append(row); history_decisions.append(row)
            for method in model.definition["methods"]:
                warned = [r for r in history_decisions if r["method"] == method and r["alert"]]
                valid_warnings = []
                start = None
                if first:
                    start = min(v for v in (first["window_start_ms"], first.get("checkout_window_start_ms")) if v is not None)
                    valid_warnings = [r for r in warned if 1 <= first["epoch"] - r["epoch"] <= model.definition["horizon_cycles"]
                                      and r["scored_ms"] < start]
                    warning = min(valid_warnings, key=lambda r: r["scored_ms"]) if valid_warnings else None
                    events.append({"block_id": bid, "policy": policy, "method": method, "first_unsafe_epoch": first["epoch"],
                                   "violating_window_start_ms": start, "outcome_available_ms": first["primary_available_ms"],
                                   "warned": bool(warning), "warning_epoch": warning["epoch"] if warning else None,
                                   "lead_to_window_start_ms": start - warning["scored_ms"] if warning else None,
                                   "lead_to_outcome_available_ms": first["primary_available_ms"] - warning["scored_ms"] if warning else None})
                histories.append({"block_id": bid, "policy": policy, "method": method, "baseline_safe": baseline_safe,
                                  "windows": len(observations), "last_epoch": observations[-1]["epoch"] if observations else None,
                                  "complete": bool(observations and observations[-1]["epoch"] == campaign["cycles"]),
                                  "first_unsafe_epoch": first["epoch"] if first else None,
                                  "first_violation_warned": bool(valid_warnings) if first else None,
                                  "false_warning_decisions": sum(r["alert"] and r["future_label"] == 0 for r in history_decisions if r["method"] == method),
                                  "unknown_future_decisions": sum(r["future_label"] is None for r in history_decisions if r["method"] == method),
                                  "stop_reason": history.get("stop_reason")})
    summary = {"version": model.definition["version"], "execution_commit": commit, "run_id": str(run_id),
               "model_sha256_lf": model_hash, "development_execution": model.frozen["development_execution"],
               "planned_pairs": len(planned), "received_pairs": len(blocks), "missing_pairs": sorted(set(planned) - set(blocks)),
               "prediction_integrity_failures": len(integrity), "horizon_cycles": model.definition["horizon_cycles"],
               "methods": {}, "scope": model.definition["scope"]}
    for method in model.definition["methods"]:
        rows = [r for r in decisions if r["method"] == method and r["future_label"] is not None]
        tp = sum(r["alert"] and r["future_label"] == 1 for r in rows)
        fp = sum(r["alert"] and r["future_label"] == 0 for r in rows)
        positives = sum(r["future_label"] == 1 for r in rows)
        negatives = len(rows) - positives
        crossings = [r for r in events if r["method"] == method]
        leads = [r["lead_to_window_start_ms"] / 1000 for r in crossings if r["warned"]]
        summary["methods"][method] = {"threshold": model.frozen["thresholds"][method], "eligible_known_decisions": len(rows),
             "positive_decisions": positives, "negative_decisions": negatives, "true_warning_decisions": tp,
             "false_warning_decisions": fp, "missed_positive_decisions": positives - tp,
             "decision_precision": tp / (tp + fp) if tp + fp else None,
             "false_warning_rate": fp / negatives if negatives else None,
             "first_violation_histories": len(crossings), "first_violation_histories_warned": sum(r["warned"] for r in crossings),
             "first_violation_histories_missed": sum(not r["warned"] for r in crossings),
             "median_conservative_lead_seconds": statistics.median(leads) if leads else None,
             "minimum_conservative_lead_seconds": min(leads) if leads else None}
    return summary, decisions, histories, events, integrity


def operating_curves(decisions, events, methods, horizon):
    path = ROOT / "probe8/results/development-v0.1.0/development-thresholds.csv"
    with path.open(newline="", encoding="utf-8") as f:
        development_rows = list(csv.DictReader(f))
    curves = []
    for method in methods:
        thresholds = [float(r["threshold"]) if r["threshold"] else None for r in development_rows if r["method"] == method]
        rows = [r for r in decisions if r["method"] == method and r["future_label"] is not None]
        crossings = [r for r in events if r["method"] == method]
        for threshold in thresholds:
            tp = sum(r["future_label"] == 1 and alerts(r["score"], threshold) for r in rows)
            fp = sum(r["future_label"] == 0 and alerts(r["score"], threshold) for r in rows)
            negatives = sum(r["future_label"] == 0 for r in rows)
            caught = sum(any(r["block_id"] == e["block_id"] and r["policy"] == e["policy"]
                              and 1 <= e["first_unsafe_epoch"] - r["epoch"] <= horizon
                              and r["scored_ms"] < e["violating_window_start_ms"]
                              and alerts(r["score"], threshold) for r in rows) for e in crossings)
            curves.append({"method": method, "predeclared_development_threshold": threshold,
                           "true_warning_decisions": tp, "false_warning_decisions": fp,
                           "decision_precision": tp / (tp + fp) if tp + fp else None,
                           "false_warning_rate": fp / negatives if negatives else None,
                           "first_violation_histories": len(crossings), "first_violation_histories_warned": caught,
                           "scope": "Descriptive fixed-score curve; not a newly selected or refitted live rule"})
    return curves


def save(inputs, output, commit, run_id):
    model = WarningModel()
    campaign = json.loads((ROOT / CAMPAIGN).read_text())
    blocks = {}
    for file in sorted(inputs.rglob("block.json")):
        block = json.loads(file.read_text())
        if block["block_id"] in blocks:
            raise ValueError("Duplicate confirmation pair")
        blocks[block["block_id"]] = block
    summary, decisions, histories, events, integrity = analyze(blocks, model, campaign, commit, run_id)
    output.mkdir(parents=True, exist_ok=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (output / "block-level.json").write_text(json.dumps(blocks, separators=(",", ":")) + "\n", encoding="utf-8")
    for name, rows in (("warning-decisions.csv", decisions), ("history-level.csv", histories),
                       ("first-violation-events.csv", events), ("prediction-integrity.csv", integrity)):
        csv_save(output / name, rows)
    csv_save(output / "operating-curves.csv", operating_curves(decisions, events, model.definition["methods"], model.definition["horizon_cycles"]))
    lines = ["# Independent passive warning confirmation", "", "Frozen rules; no fitting on these observations.", "",
             f'Received {len(blocks)}/{summary["planned_pairs"]} fresh runner pairs. Missing: {summary["missing_pairs"]}.', "",
             "| Method | First violations warned / observed | False warning decisions | Decision precision | Achieved false-warning rate | Median lead to violating window start (s) |",
             "| --- | --- | ---: | --- | --- | --- |"]
    for method, m in summary["methods"].items():
        lines.append(f'| {method} | {m["first_violation_histories_warned"]}/{m["first_violation_histories"]} | {m["false_warning_decisions"]} | {m["decision_precision"]} | {m["false_warning_rate"]} | {m["median_conservative_lead_seconds"]} |')
    lines += ["", "Decision windows are dependent. Warning precision and event recall are different quantities.",
              "Lead to the start of the first violating window is conservative relative to the measured outcome's availability, not the unknowable instant of a latent failure.",
              "Actual false-warning rates can differ despite a common development budget; greater recall at greater false-alarm burden is not automatically superiority.",
              "[Fixed-threshold operating curves](operating-curves.csv) use only thresholds enumerated during development; no threshold is refitted on confirmation outcomes.",
              "Truncated unknown futures are not negatives. Baseline failures, early stops, failed predictions and missing runners remain visible.",
              "The observer emits every frozen method simultaneously and never changes the guarded allocation policy.",
              "[Summary](summary.json), [every decision](warning-decisions.csv), [every history](history-level.csv), [first-violation events](first-violation-events.csv), [integrity failures](prediction-integrity.csv), [full records](block-level.json).", ""]
    (output / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary))
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    save(args.inputs, args.output_dir, args.commit, args.run_id)


if __name__ == "__main__":
    main()
