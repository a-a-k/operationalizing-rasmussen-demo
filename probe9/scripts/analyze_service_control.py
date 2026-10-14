from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe8/scripts"))
sys.path.insert(0, str(Path(__file__).parent))
from warning_model import WarningModel, canonical_hash, csv_save, target
sys.path.insert(0, str(Path(__file__).parent))
from analyze import event_start, paired_events, paired_false_histories, summarize

SPEC = "probe9/service-control-v0.1.0.json"
METHODS = ("ilr_history", "share_history", "service_indicators")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_spec(root=ROOT):
    spec = read_json(root / SPEC)
    for key in ("source_summary", "campaign_design", "frozen_model"):
        if canonical_hash(root / spec[key]) != spec[key + "_sha256_lf"]:
            raise ValueError("Pinned source differs: " + key)
    if tuple(spec["methods"]) != METHODS:
        raise ValueError("Method set differs")
    return spec


def read_blocks(folder: Path):
    blocks = {}
    for path in sorted(folder.glob("*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            block = json.load(stream)
        if block["block_id"] in blocks:
            raise ValueError("Duplicate block: " + block["block_id"])
        blocks[block["block_id"]] = block
    return blocks


def prepare(blocks, design, model, source_summary, horizon):
    decisions, events, integrity = [], [], []
    model_hash = canonical_hash(ROOT / "probe8/frozen-model-v0.1.0.json")
    for bid, block in sorted(blocks.items()):
        if (block.get("execution_commit") != source_summary["execution_commit"]
                or str(block.get("run_id")) != str(source_summary["run_id"])):
            raise ValueError("Execution provenance differs: " + bid)
        if block.get("design") != design or block.get("mode") != "main":
            raise ValueError("Campaign definition differs: " + bid)
        metadata = block.get("warning_model", {})
        if (metadata.get("sha256_lf") != model_hash or metadata.get("runtime_mode") != "observer_only"
                or metadata.get("observer_failures") != 0):
            raise ValueError("Frozen observer metadata differs: " + bid)
        for policy, history in sorted(block["histories"].items()):
            observations = sorted(history.get("observations", []), key=lambda w: w["epoch"])
            if [w["epoch"] for w in observations] != list(range(len(observations))):
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
            for index, window in enumerate(observations):
                recorded = window.get("online_warning")
                replay = model.score(observations[:index + 1], block["profile"])
                if recorded is None or recorded.get("prediction_valid") is not True:
                    integrity.append({"block_id": bid, "policy": policy, "epoch": window["epoch"],
                                      "reason": "missing_or_failed_live_prediction"})
                    continue
                if (recorded.get("model_sha256_lf") != model_hash
                        or recorded.get("runtime_mode") != "observer_only"
                        or recorded.get("features_available_ms") != window.get("primary_available_ms")
                        or recorded.get("epoch") != window["epoch"]
                        or recorded.get("scored_ms", -math.inf) < window.get("primary_available_ms", math.inf)):
                    raise ValueError("Live prediction chronology differs")
                if replay["eligible"] != recorded.get("eligible") or replay["reason"] != recorded.get("reason"):
                    raise ValueError("Live eligibility replay differs")
                if not replay["eligible"]:
                    continue
                checked = {}
                for method in METHODS:
                    live, fresh = recorded["methods"][method], replay["methods"][method]
                    for key in ("score", "threshold", "alert", "neighbor_pairs", "neighbors"):
                        if live[key] != fresh[key]:
                            raise ValueError(f"Frozen live prediction replay differs: {bid}/{policy}/{window['epoch']}/{method}/{key}")
                    checked[method] = live
                decisions.append({
                    "block_id": bid, "policy": policy, "initial_state": block["initial_state"],
                    "profile": block["profile"], "epoch": window["epoch"],
                    "features_available_ms": window["primary_available_ms"],
                    "resource_scored_ms": recorded["scored_ms"],
                    "future_label": target(observations, window["epoch"], horizon),
                    "ilr_score": checked["ilr_history"]["score"],
                    "ilr_alert": checked["ilr_history"]["alert"],
                    "share_score": checked["share_history"]["score"],
                    "share_alert": checked["share_history"]["alert"],
                    "service_score": checked["service_indicators"]["score"],
                    "service_alert": checked["service_indicators"]["alert"],
                })
    return decisions, events, integrity


def write_results(output: Path, summary: dict):
    lines = [
        "# Matched service-indicator control",
        "",
        "This is a retrospective aggregation of predictions that were produced online during Series 9 by the model frozen before that campaign. No model, feature, neighbor count or threshold was fitted after Series 9.",
        "",
        "All three observers use the same labeled library, five-nearest-pair mechanism, service-headroom context, two-cycle target and pre-frozen threshold-selection procedure. `service_indicators` sees only current service headrooms and their last changes; the other observers additionally see the complete CPU/RAM allocation history in ILR or raw-share coordinates.",
        "",
        "| Observer input | First violations warned | False decisions | Histories with false signals | Precision | Median lead (s) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for method in METHODS:
        row = summary["methods"][method]
        precision = "NA" if row["decision_precision"] is None else f'{row["decision_precision"]:.6f}'
        lead = "NA" if row["median_lead_seconds"] is None else f'{row["median_lead_seconds"]:.3f}'
        lines.append(f'| {method} | {row["first_violations_warned"]}/{row["first_violation_histories"]} | '
                     f'{row["false_warning_decisions"]} | {row["histories_with_false_warning"]} | {precision} | {lead} |')
    lines += [
        "",
        "The aligned comparison isolates what the recorded allocation history adds to the same learned warning mechanism. It does not by itself establish that ILR is superior to complete raw shares; that remains a representational comparison.",
        "",
        "Prometheus `predict_linear` remains a separate practical reference in the original Series 9 result. It is not included in this matched table because it does not use the historical labeled library or the nearest-history rule.",
        "",
        "[Machine-readable summary](summary.json), [all aligned decisions](decisions.csv), [event-level outcomes](first-events.csv), and [integrity checks](prediction-integrity.csv).",
        "",
    ]
    (output / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    spec = load_spec()
    source = ROOT / spec["source_result"]
    source_summary = read_json(ROOT / spec["source_summary"])
    design = read_json(ROOT / spec["campaign_design"])
    model = WarningModel()
    blocks = read_blocks(source / "blocks")
    if len(blocks) != source_summary["received_pairs"]:
        raise ValueError("Archived block count differs")
    decisions, events, integrity = prepare(blocks, design, model, source_summary, spec["horizon_cycles"])
    thresholds = {method: model.frozen["thresholds"][method] for method in METHODS}
    methods, event_rows = {}, []
    for method in METHODS:
        result, rows = summarize(decisions, events, method, spec["horizon_cycles"], thresholds[method])
        methods[method] = result
        event_rows.extend(rows)
    pairs = {}
    for left, right in (("ilr_history", "service_indicators"),
                        ("share_history", "service_indicators"),
                        ("ilr_history", "share_history")):
        pairs[left + "__vs__" + right] = {
            "first_violation_events": paired_events(event_rows, left, right),
            "histories_with_false_signals": paired_false_histories(decisions, left, right, thresholds),
        }
    summary = {
        "version": spec["version"],
        "status": spec["status"],
        "source_execution_commit": source_summary["execution_commit"],
        "source_run_id": source_summary["run_id"],
        "source_pairs": len(blocks),
        "histories": source_summary["histories"],
        "first_violation_histories": len(events),
        "eligible_decisions": len(decisions),
        "known_decisions": sum(r["future_label"] is not None for r in decisions),
        "prediction_integrity_failures": len(integrity),
        "thresholds": thresholds,
        "methods": methods,
        "paired_comparisons": pairs,
        "interpretation": spec["scope"],
    }
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    csv_save(output / "decisions.csv", decisions)
    csv_save(output / "first-events.csv", event_rows)
    csv_save(output / "prediction-integrity.csv", integrity)
    write_results(output, summary)
    print(json.dumps({"source_pairs": len(blocks), "events": len(events), "methods": methods}, allow_nan=False))


if __name__ == "__main__":
    main()
