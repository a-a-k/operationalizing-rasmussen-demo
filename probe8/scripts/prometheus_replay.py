from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import json
import math
import statistics
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

from warning_model import ROOT, canonical_hash, csv_save, target

DEFINITION = "probe8/practical-baseline-v0.1.0.json"
METRIC = "allocation_warning_requirement"
FIXTURE_TIME = 1791936000


def read_inputs(root=ROOT):
    definition = json.loads((root / DEFINITION).read_text())
    for key in ("records", "cadence_records", "frozen_model"):
        if canonical_hash(root / definition[key]) != definition[key + "_sha256_lf"]:
            raise ValueError("Pinned replay source differs: " + key)
    blocks = json.loads((root / definition["records"]).read_text())
    old = json.loads((root / definition["cadence_records"]).read_text())
    return definition, blocks, old


def forecast_horizon(old, cycles):
    intervals = []
    for block in old.values():
        for history in block["histories"].values():
            observations = sorted(history["observations"], key=lambda w: w["epoch"])
            for a, b in zip(observations, observations[1:]):
                if (a["epoch"] >= 1 and b["epoch"] == a["epoch"] + 1
                        and a["valid"] and b["valid"]):
                    delta = (b["window_start_ms"] - a["window_start_ms"]) / 1000
                    if not math.isfinite(delta) or delta <= 0:
                        raise ValueError("Nonpositive old cadence")
                    intervals.append(delta)
    if not intervals:
        raise ValueError("No development cadence timestamps")
    cadence = statistics.median(intervals)
    return {"source_intervals": len(intervals), "median_cycle_seconds": cadence,
            "forecast_seconds": cycles * cadence}


def sample_time_ms(w):
    value = w["primary_available_ms"]
    if not math.isfinite(value):
        raise ValueError("Missing primary availability")
    return math.ceil(value)


def gauge_values(w, definition):
    values = {}
    if not w["valid"]:
        return values
    for name, requirement in definition["requirements"].items():
        value = w
        for key in requirement["path"]:
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value):
            values[name] = value
    return values


def forecast_alert(predictions, definition):
    if set(predictions) != set(definition["requirements"]) or not all(math.isfinite(v) for v in predictions.values()):
        return None, []
    crossed = []
    for name, spec in definition["requirements"].items():
        value, limit, op = predictions[name], spec["limit"], spec["unsafe_operator"]
        unsafe = value > limit if op == ">" else value >= limit if op == ">=" else value < limit
        if unsafe:
            crossed.append(name)
    return bool(crossed), crossed


def opportunities(blocks, definition):
    rows, events = [], []
    for bid, block in sorted(blocks.items()):
        for policy, history in sorted(block["histories"].items()):
            observations = sorted(history["observations"], key=lambda w: w["epoch"])
            if [w["epoch"] for w in observations] != list(range(len(observations))):
                raise ValueError("Nonconsecutive history")
            times = [sample_time_ms(w) for w in observations]
            if any(b <= a for a, b in zip(times, times[1:])):
                raise ValueError("Nonincreasing availability timestamps")
            baseline_safe = bool(observations and observations[0]["valid"] and observations[0]["safe"])
            first = next((w for w in observations[1:] if w["valid"] and w["safe"] is False), None) if baseline_safe else None
            if first:
                start = min(v for v in (first["window_start_ms"], first.get("checkout_window_start_ms")) if v is not None)
                events.append({"block_id": bid, "policy": policy, "first_unsafe_epoch": first["epoch"],
                               "violating_window_start_ms": start})
            for w in observations:
                record = w.get("online_warning", {})
                if not record.get("prediction_valid") or not record.get("eligible"):
                    continue
                if not w["valid"] or w["safe"] is not True or record["scored_ms"] < w["primary_available_ms"]:
                    raise ValueError("Frozen warning eligibility/chronology differs")
                live = record["methods"]["ilr_history"]
                rows.append({"block_id": bid, "policy": policy, "profile": block["profile"], "epoch": w["epoch"],
                             "sample_time_ms": sample_time_ms(w), "features_available_ms": w["primary_available_ms"],
                             "ilr_scored_ms": record["scored_ms"], "ilr_alert": live["alert"], "ilr_score": live["score"],
                             "ilr_threshold": live["threshold"],
                             "future_label": target(observations, w["epoch"], definition["horizon_cycles"])})
    return rows, events


def openmetrics(blocks, definition):
    lines = [f"# TYPE {METRIC} gauge"]
    series = {}
    for bid, block in sorted(blocks.items()):
        for policy, history in sorted(block["histories"].items()):
            for w in history["observations"]:
                ts = sample_time_ms(w)
                for name, value in gauge_values(w, definition).items():
                    series.setdefault((bid, policy, name), []).append((ts, value))
    for (bid, policy, name), samples in sorted(series.items()):
        labels = f'block_id={json.dumps(bid)},policy={json.dumps(policy)},requirement={json.dumps(name)}'
        for ts, value in sorted(samples):
            lines.append(f"{METRIC}{{{labels}}} {value:.17g} {ts // 1000}.{ts % 1000:03d}")
    lines.append("# TYPE allocation_warning_fixture gauge")
    for variant in ("prefix", "full"):
        for offset, value in ((0, 0.9), (60, 0.8), (120, 0.7)):
            lines.append(f'allocation_warning_fixture{{variant="{variant}"}} {value} {FIXTURE_TIME + offset}')
        if variant == "full":
            lines.append(f'allocation_warning_fixture{{variant="{variant}"}} 999 {FIXTURE_TIME + 180}')
    lines.extend(["# EOF", ""])
    return "\n".join(lines)


def expression(row, lookback, horizon):
    selector = f'{METRIC}{{block_id={json.dumps(row["block_id"])},policy={json.dumps(row["policy"])}}}'
    return f"predict_linear({selector}[{lookback}s], {horizon:.17g})"


def query(url, expr, timestamp_ms):
    params = urllib.parse.urlencode({"query": expr, "time": f"{timestamp_ms // 1000}.{timestamp_ms % 1000:03d}"})
    with urllib.request.urlopen(url + "/api/v1/query?" + params, timeout=30) as response:
        result = json.load(response)
    if result.get("status") != "success" or result["data"]["resultType"] != "vector":
        raise ValueError("Native PromQL query failed")
    if result.get("warnings") or result.get("infos"):
        raise ValueError("Unexpected native PromQL annotation")
    return result


def predictions(result):
    values = {}
    for entry in result["data"]["result"]:
        key = entry["metric"]["requirement"]
        if key in values:
            raise ValueError("Duplicate predicted requirement")
        values[key] = float(entry["value"][1])
    return values


@contextlib.contextmanager
def native_server(binary_dir, work):
    config = work / "prometheus.yml"
    config.write_text("global:\n  scrape_interval: 1m\nscrape_configs: []\n", encoding="utf-8")
    url = "http://127.0.0.1:19095"
    args = [str(binary_dir / "prometheus"), "--config.file=" + str(config),
            "--storage.tsdb.path=" + str(work / "tsdb"), "--storage.tsdb.retention.time=100y",
            "--web.listen-address=127.0.0.1:19095", "--log.level=warn"]
    with (work / "prometheus.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Prometheus stopped before readiness")
                try:
                    with urllib.request.urlopen(url + "/-/ready", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Prometheus readiness timed out")
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def native_checks(url):
    result = query(url, "predict_linear(allocation_warning_fixture[5m], 60)", (FIXTURE_TIME + 120) * 1000)
    actual = {r["metric"]["variant"]: float(r["value"][1]) for r in result["data"]["result"]}
    if set(actual) != {"prefix", "full"} or not all(math.isclose(v, 0.6, abs_tol=1e-12) for v in actual.values()):
        raise ValueError("Native steady-trend/no-lookahead fixture failed")
    warmup = query(url, "predict_linear(allocation_warning_fixture[5m], 60)", FIXTURE_TIME * 1000)
    if warmup["data"]["result"]:
        raise ValueError("Native forecast accepted one sample")
    return {"steady_trend_and_future_invariance": result, "one_sample_unavailable": warmup}


def summarize(rows, events, method, horizon):
    known = [r for r in rows if r["future_label"] is not None]
    key = "ilr_alert" if method == "ilr_history" else "baseline_alert"
    tp = sum(r[key] and r["future_label"] == 1 for r in known)
    fp = sum(r[key] and r["future_label"] == 0 for r in known)
    positives = sum(r["future_label"] == 1 for r in known)
    negatives = len(known) - positives
    outcomes = []
    for event in events:
        candidates = [r for r in known if r["block_id"] == event["block_id"] and r["policy"] == event["policy"]
                      and 1 <= event["first_unsafe_epoch"] - r["epoch"] <= horizon]
        timestamp_key = "ilr_scored_ms" if method == "ilr_history" else "sample_time_ms"
        warned = [r for r in candidates if r[key] and r[timestamp_key] < event["violating_window_start_ms"]]
        first = min(warned, key=lambda r: r[timestamp_key]) if warned else None
        outcomes.append({**event, "method": method, "eligible_opportunities": len(candidates), "warned": bool(first),
                         "warning_epoch": first["epoch"] if first else None,
                         "lead_seconds": (event["violating_window_start_ms"] - first[timestamp_key]) / 1000 if first else None})
    leads = [e["lead_seconds"] for e in outcomes if e["warned"]]
    summary = {"known_decisions": len(known), "positive_decisions": positives, "negative_decisions": negatives,
               "true_warning_decisions": tp, "false_warning_decisions": fp, "missed_positive_decisions": positives - tp,
               "decision_precision": tp / (tp + fp) if tp + fp else None,
               "false_warning_rate": fp / negatives if negatives else None,
               "first_violation_histories": len(events), "first_violations_with_covered_opportunity": sum(e["eligible_opportunities"] > 0 for e in outcomes),
               "first_violations_warned": sum(e["warned"] for e in outcomes),
               "median_lead_seconds": statistics.median(leads) if leads else None}
    return summary, outcomes


def evaluate(native_records, rows, events, definition):
    index = {(r["block_id"], r["policy"], r["epoch"]): r for r in rows}
    decisions, summaries, event_rows = [], {}, []
    lookbacks = [definition["primary_lookback_seconds"], *definition["sensitivity_lookbacks_seconds"]]
    for lookback in lookbacks:
        evaluated = []
        records = [r for r in native_records if r["lookback_seconds"] == lookback]
        if len(records) != len(index) or len({(r["block_id"], r["policy"], r["epoch"]) for r in records}) != len(index):
            raise ValueError("Incomplete/duplicate native query archive")
        for native in records:
            row = index[(native["block_id"], native["policy"], native["epoch"])]
            if native["sample_time_ms"] != row["sample_time_ms"]:
                raise ValueError("Native query chronology differs")
            values = predictions(native["response"])
            alert, crossed = forecast_alert(values, definition)
            decision = {**row, "lookback_seconds": lookback, "covered": alert is not None,
                        "baseline_alert": alert, "crossed_requirements": ";".join(crossed),
                        **{"forecast_" + name: values.get(name) for name in definition["requirements"]}}
            decisions.append(decision)
            if alert is not None:
                evaluated.append(decision)
        result = {"opportunities": len(rows), "covered": len(evaluated), "unavailable": len(rows) - len(evaluated),
                  "unknown_targets_on_covered": sum(r["future_label"] is None for r in evaluated), "methods": {}, "policy_counts": {}}
        for method in ("prometheus_predict_linear", "ilr_history"):
            result["methods"][method], es = summarize(evaluated, events, method, definition["horizon_cycles"])
            event_rows.extend({**e, "lookback_seconds": lookback} for e in es)
            for policy in ("adaptive", "control"):
                subset = [r for r in evaluated if r["policy"] == policy]
                subset_events = [e for e in events if e["policy"] == policy]
                result["policy_counts"].setdefault(policy, {})[method] = summarize(subset, subset_events, method, definition["horizon_cycles"])[0]
        summaries[str(lookback)] = result
    return summaries, decisions, event_rows


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    definition, blocks, old = read_inputs()
    cadence = forecast_horizon(old, definition["horizon_cycles"])
    rows, events = opportunities(blocks, definition)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    binaries = args.binary_dir.resolve()
    versions = {name: subprocess.check_output([str(binaries / name), "--version"], text=True, stderr=subprocess.STDOUT)
                for name in ("prometheus", "promtool")}
    if any("version " + definition["prometheus"]["version"] not in version for version in versions.values()):
        raise ValueError("Prometheus version differs")
    (output / "inputs.openmetrics").write_text(openmetrics(blocks, definition), encoding="utf-8")
    with (output / "backfill.log").open("w", encoding="utf-8") as log:
        subprocess.run([str(binaries / "promtool"), "tsdb", "create-blocks-from", "openmetrics",
                        str(output / "inputs.openmetrics"), str(output / "tsdb")], check=True, stdout=log, stderr=subprocess.STDOUT)
    native_records = []
    with native_server(binaries, output) as url:
        save_json(output / "native-checks.json", native_checks(url))
        for lookback in [definition["primary_lookback_seconds"], *definition["sensitivity_lookbacks_seconds"]]:
            for row in rows:
                expr = expression(row, lookback, cadence["forecast_seconds"])
                native_records.append({"block_id": row["block_id"], "policy": row["policy"], "epoch": row["epoch"],
                                       "lookback_seconds": lookback, "sample_time_ms": row["sample_time_ms"],
                                       "expression": expr, "response": query(url, expr, row["sample_time_ms"])})
    with (output / "native-responses.jsonl.gz").open("wb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            for record in native_records:
                compressed.write((json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n").encode())
    summaries, decisions, event_rows = evaluate(native_records, rows, events, definition)
    summary = {"version": definition["version"], "execution_commit": args.commit, "run_id": args.run_id,
               "definition_sha256_lf": canonical_hash(ROOT / DEFINITION), "source_runtime_run_id": "38547221917",
               "source_runtime_commit": "2f8cf9e8bde4413eef7bd9cc3cdc43e28f87ca85", "pairs": len(blocks),
               "cadence": cadence, "lookbacks": summaries,
               "full_original_ilr": summarize(rows, events, "ilr_history", definition["horizon_cycles"])[0],
               "native_versions": versions,
               "native_binary_sha256": {name: hashlib.sha256((binaries / name).read_bytes()).hexdigest() for name in versions},
               "scope": definition["scope"], "baseline_lead": "Retrospective availability-time estimate; not a recorded live Prometheus notification."}
    save_json(output / "summary.json", summary)
    csv_save(output / "decisions.csv", decisions)
    csv_save(output / "first-events.csv", event_rows)
    lines = ["# Native Prometheus forecast replay", "", definition["scope"], "",
             f'Forecast horizon: {cadence["forecast_seconds"]:.3f} s, two old median cycles. Primary lookback: 300 s.', "",
             "| Lookback (s) | Method on common decisions | Covered decisions | First violations warned | False signals | Precision | Median lead (s) |",
             "| ---: | --- | ---: | --- | ---: | ---: | ---: |"]
    for lookback, result in summaries.items():
        for method, counts in result["methods"].items():
            precision = counts["decision_precision"]
            lead = counts["median_lead_seconds"]
            lines.append(f'| {lookback} | {method} | {counts["known_decisions"]} | {counts["first_violations_warned"]}/{counts["first_violation_histories"]} | {counts["false_warning_decisions"]} | {precision if precision is not None else "NA"} | {lead if lead is not None else "NA"} |')
    lines.extend(["", "Unavailable forecasts are not no-alert decisions. Every lookback is retained; no best setting is selected.",
                  "ILR counts above use the same covered decisions. Original full ILR counts remain in summary.json.",
                  "Service trajectories are short, irregular and affected by controller actions; linear trends are an applicability assumption, not guaranteed.",
                  "Native queries use only samples at or before primary availability. Baseline lead is a replay estimate, not a measured live notification.",
                  "[Summary](summary.json), [every decision](decisions.csv), [first events](first-events.csv), [native queries/responses](native-responses.jsonl.gz), [native fixture checks](native-checks.json).", ""])
    (output / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"cadence": cadence, "lookbacks": summaries}, allow_nan=False))


if __name__ == "__main__":
    main()
