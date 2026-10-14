from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe8/scripts"))
sys.path.insert(0, str(Path(__file__).parent))
from prometheus_replay import (forecast_alert, native_checks, native_server,
                               openmetrics, predictions, query)
from warning_model import FROZEN, WarningModel, alerts, canonical_hash, csv_save, target
from live_runner import CAMPAIGN, campaign_matrix, load_design

ANALYSIS = "probe9/analysis-v0.1.0.json"
SCORE_FIELDS = {
    "ilr_history": "ilr_score",
    "share_history": "share_score",
    "local_history": "local_score",
    "service_indicators": "service_score",
}


def load_analysis(root=ROOT):
    spec = json.loads((root / ANALYSIS).read_text())
    for key in ("design", "frozen_model", "old_threshold_table", "practical_baseline_result"):
        if canonical_hash(root / spec[key]) != spec[key + "_sha256_lf"]:
            raise ValueError("Pinned analysis source differs: " + key)
    previous = json.loads((root / spec["practical_baseline_result"]).read_text())
    if previous["cadence"]["forecast_seconds"] != spec["forecast_seconds"]:
        raise ValueError("Fixed practical forecast horizon differs")
    with (root / spec["old_threshold_table"]).open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    for method in ("ilr_history", "share_history"):
        available = [float(r["threshold"]) if r["threshold"] else None
                     for r in rows if r["method"] == method]
        if available != spec["operating_points"]["resource_secondary_thresholds"]:
            raise ValueError("Fixed resource operating points differ: " + method)
        if spec["operating_points"]["resource_primary_thresholds"][method] != 0.2:
            raise ValueError("Frozen resource threshold differs: " + method)
    return spec


def read_blocks(inputs):
    blocks = {}
    for path in sorted(inputs.rglob("block.json")):
        block = json.loads(path.read_text())
        bid = block["block_id"]
        if bid in blocks:
            raise ValueError("Duplicate block: " + bid)
        blocks[bid] = block
    return blocks


def event_start(window):
    values = [window.get("window_start_ms"), window.get("checkout_window_start_ms")]
    values = [v for v in values if v is not None]
    return min(values) if values else None


def sample_time_ms(window):
    value = window.get("primary_available_ms")
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Missing primary availability timestamp")
    return math.ceil(value)


def prepare(blocks, design, analysis, model, commit, run_id):
    planned = {row["block_id"]: row for row in campaign_matrix(design)}
    unexpected = set(blocks) - set(planned)
    if unexpected:
        raise ValueError("Unexpected blocks: " + ",".join(sorted(unexpected)))
    model_hash = canonical_hash(ROOT / FROZEN)
    decisions, events, histories, integrity = [], [], [], []
    for bid, block in sorted(blocks.items()):
        if block.get("execution_commit") != commit or str(block.get("run_id")) != str(run_id):
            raise ValueError("Execution provenance differs: " + bid)
        if block.get("design") != design or block.get("mode") != "main":
            raise ValueError("Runtime definition differs: " + bid)
        for key in ("initial_state", "profile", "repetition", "order"):
            if block.get(key) != planned[bid][key]:
                raise ValueError("Matrix row differs: " + bid + "/" + key)
        metadata = block.get("warning_model", {})
        if (metadata.get("sha256_lf") != model_hash or metadata.get("runtime_mode") != "observer_only"
                or metadata.get("observer_failures") != 0):
            raise ValueError("Frozen observer metadata differs: " + bid)
        for policy, history in sorted(block["histories"].items()):
            observations = sorted(history.get("observations", []), key=lambda w: w["epoch"])
            consecutive = [w["epoch"] for w in observations] == list(range(len(observations)))
            if not consecutive:
                raise ValueError("Nonconsecutive history: " + bid + "/" + policy)
            baseline_safe = bool(observations and observations[0]["valid"] and observations[0]["safe"])
            first = next((w for w in observations[1:] if w["valid"] and w["safe"] is False), None) if baseline_safe else None
            if first:
                start = event_start(first)
                if start is None:
                    raise ValueError("Missing violating-window timestamp")
                events.append({"block_id": bid, "policy": policy, "initial_state": block["initial_state"],
                               "profile": block["profile"], "first_unsafe_epoch": first["epoch"],
                               "violating_window_start_ms": start,
                               "outcome_available_ms": first["primary_available_ms"]})
            history_rows = []
            for index, window in enumerate(observations):
                record = window.get("online_warning")
                fresh = model.score(observations[:index + 1], block["profile"])
                if record is None or record.get("prediction_valid") is not True:
                    integrity.append({"block_id": bid, "policy": policy, "epoch": window["epoch"],
                                      "reason": "missing_or_failed_live_prediction"})
                    continue
                if (record.get("model_sha256_lf") != model_hash or record.get("runtime_mode") != "observer_only"
                        or record.get("features_available_ms") != window.get("primary_available_ms")
                        or record.get("epoch") != window["epoch"]
                        or record.get("scored_ms", -math.inf) < window.get("primary_available_ms", math.inf)):
                    raise ValueError("Live prediction chronology differs")
                if fresh["eligible"] != record.get("eligible") or fresh["reason"] != record.get("reason"):
                    raise ValueError("Live eligibility replay differs")
                if not fresh["eligible"]:
                    continue
                methods = {}
                for method in ("ilr_history", "share_history"):
                    live, replay = record["methods"][method], fresh["methods"][method]
                    for key in ("score", "threshold", "alert", "neighbor_pairs", "neighbors"):
                        if live[key] != replay[key]:
                            raise ValueError("Frozen live prediction replay differs")
                    methods[method] = live
                row = {"block_id": bid, "policy": policy, "initial_state": block["initial_state"],
                       "profile": block["profile"], "epoch": window["epoch"],
                       "sample_time_ms": sample_time_ms(window),
                       "features_available_ms": window["primary_available_ms"],
                       "resource_scored_ms": record["scored_ms"],
                       "future_label": target(observations, window["epoch"], analysis["horizon_cycles"]),
                       "ilr_score": methods["ilr_history"]["score"],
                       "ilr_frozen_alert": methods["ilr_history"]["alert"],
                       "share_score": methods["share_history"]["score"],
                       "share_frozen_alert": methods["share_history"]["alert"]}
                decisions.append(row)
                history_rows.append(row)
            histories.append({"block_id": bid, "policy": policy, "initial_state": block["initial_state"],
                              "profile": block["profile"], "baseline_safe": baseline_safe,
                              "windows": len(observations), "last_epoch": observations[-1]["epoch"] if observations else None,
                              "complete": bool(observations and observations[-1]["epoch"] == design["cycles"]),
                              "first_unsafe_epoch": first["epoch"] if first else None,
                              "eligible_predictions": len(history_rows), "stop_reason": history.get("stop_reason")})
    return {"planned": planned, "decisions": decisions, "events": events,
            "histories": histories, "integrity": integrity}


def prom_expression(row, lookback, horizon):
    labels = f'block_id={json.dumps(row["block_id"])},policy={json.dumps(row["policy"])}'
    return f"predict_linear(allocation_warning_requirement{{{labels}}}[{lookback}s], {json.dumps(horizon)})"


def run_native(blocks, rows, analysis, binary_dir, work):
    work.mkdir(parents=True, exist_ok=False)
    versions = {name: subprocess.check_output([str(binary_dir / name), "--version"], text=True,
                                               stderr=subprocess.STDOUT)
                for name in ("prometheus", "promtool")}
    if any("version " + analysis["prometheus"]["version"] not in value for value in versions.values()):
        raise ValueError("Prometheus binary version differs")
    metrics = openmetrics(blocks, analysis)
    (work / "inputs.openmetrics").write_text(metrics, encoding="utf-8")
    with (work / "backfill.log").open("w", encoding="utf-8") as log:
        subprocess.run([str(binary_dir / "promtool"), "tsdb", "create-blocks-from", "openmetrics",
                        str(work / "inputs.openmetrics"), str(work / "tsdb")],
                       check=True, stdout=log, stderr=subprocess.STDOUT)
    records = []
    lookbacks = [analysis["primary_lookback_seconds"], *analysis["sensitivity_lookbacks_seconds"]]
    with native_server(binary_dir, work) as url:
        checks = native_checks(url)
        for lookback in lookbacks:
            for row in rows:
                expression = prom_expression(row, lookback, analysis["forecast_seconds"])
                response = query(url, expression, row["sample_time_ms"])
                records.append({"block_id": row["block_id"], "policy": row["policy"],
                                "epoch": row["epoch"], "lookback_seconds": lookback,
                                "sample_time_ms": row["sample_time_ms"], "expression": expression,
                                "response": response})
    return records, checks, versions


def attach_prom(rows, native, analysis):
    index = {(r["block_id"], r["policy"], r["epoch"]): r for r in rows}
    output = []
    for record in native:
        key = record["block_id"], record["policy"], record["epoch"]
        if key not in index or record["sample_time_ms"] != index[key]["sample_time_ms"]:
            raise ValueError("Native response does not match an eligible decision")
        values = predictions(record["response"])
        alert, crossed = forecast_alert(values, analysis)
        output.append({**index[key], "lookback_seconds": record["lookback_seconds"],
                       "prometheus_covered": alert is not None, "prometheus_alert": alert,
                       "prometheus_crossed": ";".join(crossed),
                       **{"forecast_" + name: values.get(name) for name in analysis["requirements"]}})
    expected = len(rows) * (1 + len(analysis["sensitivity_lookbacks_seconds"]))
    if len(output) != expected or len({(r["block_id"], r["policy"], r["epoch"], r["lookback_seconds"])
                                      for r in output}) != expected:
        raise ValueError("Native response coverage differs")
    return output


def method_alert(row, method, threshold=None):
    if method == "prometheus_predict_linear":
        return row["prometheus_alert"] is True
    if method not in SCORE_FIELDS:
        raise ValueError("Unknown warning method: " + method)
    return alerts(row[SCORE_FIELDS[method]], threshold)


def method_time(row, method):
    return row["sample_time_ms"] if method == "prometheus_predict_linear" else row["resource_scored_ms"]


def summarize(rows, events, method, horizon, threshold=None):
    known = [r for r in rows if r["future_label"] is not None]
    tp = sum(method_alert(r, method, threshold) and r["future_label"] == 1 for r in known)
    fp_rows = [r for r in known if method_alert(r, method, threshold) and r["future_label"] == 0]
    positives = sum(r["future_label"] == 1 for r in known)
    negatives = len(known) - positives
    event_rows = []
    for event in events:
        candidates = [r for r in known if r["block_id"] == event["block_id"] and r["policy"] == event["policy"]
                      and 1 <= event["first_unsafe_epoch"] - r["epoch"] <= horizon]
        warned = [r for r in candidates if method_alert(r, method, threshold)
                  and method_time(r, method) < event["violating_window_start_ms"]]
        first = min(warned, key=lambda r: method_time(r, method)) if warned else None
        event_rows.append({**event, "method": method, "threshold": threshold,
                           "eligible_opportunities": len(candidates), "warned": bool(first),
                           "warning_epoch": first["epoch"] if first else None,
                           "lead_seconds": ((event["violating_window_start_ms"] - method_time(first, method)) / 1000
                                            if first else None)})
    leads = [r["lead_seconds"] for r in event_rows if r["warned"]]
    false_histories = {(r["block_id"], r["policy"]) for r in fp_rows}
    return ({"known_decisions": len(known), "positive_decisions": positives, "negative_decisions": negatives,
             "true_warning_decisions": tp, "false_warning_decisions": len(fp_rows),
             "missed_positive_decisions": positives - tp,
             "histories_with_false_warning": len(false_histories),
             "decision_precision": tp / (tp + len(fp_rows)) if tp + len(fp_rows) else None,
             "false_warning_rate": len(fp_rows) / negatives if negatives else None,
             "first_violation_histories": len(events),
             "first_violations_with_covered_opportunity": sum(r["eligible_opportunities"] > 0 for r in event_rows),
             "first_violations_warned": sum(r["warned"] for r in event_rows),
             "median_lead_seconds": statistics.median(leads) if leads else None}, event_rows)


def paired_events(event_rows, left, right):
    left_rows = {(r["block_id"], r["policy"]): r for r in event_rows if r["method"] == left}
    right_rows = {(r["block_id"], r["policy"]): r for r in event_rows if r["method"] == right}
    keys = sorted(set(left_rows) & set(right_rows))
    return {"events_compared": len(keys),
            "both_warned": sum(left_rows[k]["warned"] and right_rows[k]["warned"] for k in keys),
            "left_only": sum(left_rows[k]["warned"] and not right_rows[k]["warned"] for k in keys),
            "right_only": sum(not left_rows[k]["warned"] and right_rows[k]["warned"] for k in keys),
            "neither": sum(not left_rows[k]["warned"] and not right_rows[k]["warned"] for k in keys)}


def paired_false_histories(rows, left, right, thresholds):
    histories = sorted({(r["block_id"], r["policy"]) for r in rows})
    states = {}
    for key in histories:
        negative = [r for r in rows if (r["block_id"], r["policy"]) == key and r["future_label"] == 0]
        a = any(method_alert(r, left, thresholds.get(left)) for r in negative)
        b = any(method_alert(r, right, thresholds.get(right)) for r in negative)
        states[key] = a, b
    return {"histories_compared": len(histories),
            "both_had_false_signal": sum(a and b for a, b in states.values()),
            "left_only": sum(a and not b for a, b in states.values()),
            "right_only": sum(not a and b for a, b in states.values()),
            "neither": sum(not a and not b for a, b in states.values())}


def evaluate(rows, events, analysis):
    primary_lookback = analysis["primary_lookback_seconds"]
    by_lookback, operating, all_event_rows = {}, [], []
    for lookback in [primary_lookback, *analysis["sensitivity_lookbacks_seconds"]]:
        selected = [r for r in rows if r["lookback_seconds"] == lookback]
        common = [r for r in selected if r["prometheus_covered"]]
        result = {"opportunities": len(selected), "common_covered": len(common),
                  "prometheus_unavailable": len(selected) - len(common), "methods": {}}
        methods = ("ilr_history", "share_history", "prometheus_predict_linear")
        for method in methods:
            threshold = (None if method == "prometheus_predict_linear" else
                         analysis["operating_points"]["resource_primary_thresholds"][method])
            summary, event_rows = summarize(common, events, method, analysis["horizon_cycles"], threshold)
            result["methods"][method] = summary
            all_event_rows.extend({**r, "lookback_seconds": lookback, "operating_point": "primary"}
                                  for r in event_rows)
        by_lookback[str(lookback)] = result
    primary = [r for r in rows if r["lookback_seconds"] == primary_lookback and r["prometheus_covered"]]
    for method in ("ilr_history", "share_history"):
        for threshold in analysis["operating_points"]["resource_secondary_thresholds"]:
            summary, event_rows = summarize(primary, events, method, analysis["horizon_cycles"], threshold)
            operating.append({"method": method, "threshold": threshold, **summary})
            all_event_rows.extend({**r, "lookback_seconds": primary_lookback,
                                   "operating_point": "fixed_curve"} for r in event_rows)
    primary_events = [r for r in all_event_rows if r["lookback_seconds"] == primary_lookback
                      and r["operating_point"] == "primary"]
    pairs = {}
    thresholds = {"ilr_history": analysis["operating_points"]["resource_primary_thresholds"]["ilr_history"],
                  "share_history": analysis["operating_points"]["resource_primary_thresholds"]["share_history"],
                  "prometheus_predict_linear": None}
    for left, right in (("ilr_history", "prometheus_predict_linear"),
                        ("share_history", "prometheus_predict_linear"),
                        ("ilr_history", "share_history")):
        pairs[left + "__vs__" + right] = {
            "first_violation_events": paired_events(primary_events, left, right),
            "histories_with_false_signals": paired_false_histories(primary, left, right, thresholds)
        }
    strata = []
    for initial_state in sorted({r["initial_state"] for r in primary}):
        for profile in sorted({r["profile"] for r in primary}):
            subset = [r for r in primary if r["initial_state"] == initial_state and r["profile"] == profile]
            subset_events = [e for e in events if e["initial_state"] == initial_state and e["profile"] == profile]
            for method in ("ilr_history", "share_history", "prometheus_predict_linear"):
                threshold = (None if method == "prometheus_predict_linear" else
                             analysis["operating_points"]["resource_primary_thresholds"][method])
                summary, _ = summarize(subset, subset_events, method, analysis["horizon_cycles"], threshold)
                strata.append({"initial_state": initial_state, "profile": profile, "method": method, **summary})
    return by_lookback, operating, all_event_rows, pairs, strata


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def save_blocks(output, blocks):
    folder = output / "blocks"
    folder.mkdir()
    for bid, block in sorted(blocks.items()):
        data = json.dumps(block, separators=(",", ":"), sort_keys=True).encode()
        (folder / (bid + ".json.gz")).write_bytes(gzip.compress(data, mtime=0))


def write_results(output, summary):
    primary = summary["lookbacks"][str(summary["primary_lookback_seconds"])]["methods"]
    lines = ["# Drift-generalization comparison", "",
             f'Received {summary["received_pairs"]}/{summary["planned_pairs"]} fixed runner pairs; missing {len(summary["missing_pairs"])}.', "",
             "| Method | First violations warned | False decisions | Histories with false signals | Precision |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for method in ("ilr_history", "share_history", "prometheus_predict_linear"):
        row = primary[method]
        lines.append(f'| {method} | {row["first_violations_warned"]}/{row["first_violation_histories"]} | {row["false_warning_decisions"]} | {row["histories_with_false_warning"]} | {row["decision_precision"] if row["decision_precision"] is not None else "NA"} |')
    lines += ["", "Primary comparisons are ILR versus Prometheus and raw shares versus Prometheus on identical common coverage.",
              "ILR versus shares is diagnostic. All resource thresholds and Prometheus lookbacks fixed before execution remain available; no best point is selected here.",
              "Decision windows are dependent. First-violation histories are the detection unit; runner histories also summarize false-signal burden.",
              "Native Prometheus uses availability-timestamped raw requirement gauges and cannot read samples after each query time.",
              "[Summary](summary.json), [decisions](decisions.csv), [first events](first-events.csv), [fixed resource curves](resource-operating-points.csv), [strata](strata.csv), [integrity](prediction-integrity.csv), [native responses](native-responses.jsonl.gz).", ""]
    (output / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--binary-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    design, analysis, model = load_design(), load_analysis(), WarningModel()
    blocks = read_blocks(args.inputs)
    prepared = prepare(blocks, design, analysis, model, args.commit, args.run_id)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    native, checks, versions = run_native(blocks, prepared["decisions"], analysis,
                                           args.binary_dir.resolve(), output / "native-engine")
    rows = attach_prom(prepared["decisions"], native, analysis)
    lookbacks, operating, event_rows, pairs, strata = evaluate(rows, prepared["events"], analysis)
    summary = {"version": analysis["version"], "execution_commit": args.commit, "run_id": str(args.run_id),
               "design_sha256_lf": canonical_hash(ROOT / CAMPAIGN),
               "analysis_sha256_lf": canonical_hash(ROOT / ANALYSIS),
               "frozen_model_sha256_lf": canonical_hash(ROOT / FROZEN),
               "planned_pairs": len(prepared["planned"]), "received_pairs": len(blocks),
               "missing_pairs": sorted(set(prepared["planned"]) - set(blocks)),
               "histories": len(prepared["histories"]),
               "baseline_safe_histories": sum(r["baseline_safe"] for r in prepared["histories"]),
               "complete_histories": sum(r["complete"] for r in prepared["histories"]),
               "first_violation_histories": len(prepared["events"]),
               "prediction_integrity_failures": len(prepared["integrity"]),
               "primary_lookback_seconds": analysis["primary_lookback_seconds"],
               "forecast_seconds": analysis["forecast_seconds"], "lookbacks": lookbacks,
               "primary_paired_events": pairs, "native_versions": versions,
               "native_binary_sha256": {name: hashlib.sha256((args.binary_dir / name).read_bytes()).hexdigest()
                                         for name in versions},
               "interpretation": analysis["interpretation"]}
    save_json(output / "summary.json", summary)
    save_json(output / "native-checks.json", checks)
    csv_save(output / "decisions.csv", rows)
    csv_save(output / "first-events.csv", event_rows)
    csv_save(output / "resource-operating-points.csv", operating)
    csv_save(output / "strata.csv", strata)
    csv_save(output / "history-status.csv", prepared["histories"])
    csv_save(output / "prediction-integrity.csv", prepared["integrity"])
    with (output / "native-responses.jsonl.gz").open("wb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            for record in native:
                compressed.write((json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n").encode())
    save_blocks(output, blocks)
    write_results(output, summary)
    print(json.dumps({"received_pairs": len(blocks), "missing_pairs": len(summary["missing_pairs"]),
                      "first_violations": len(prepared["events"]), "lookbacks": lookbacks}, allow_nan=False))


if __name__ == "__main__":
    main()
