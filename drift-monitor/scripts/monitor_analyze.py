"""Freeze background-only models, verify online replay and summarize paired timing."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
from pathlib import Path

import numpy as np

from monitor_core import (DESIGN, METHODS, Observer, close, digest, feature, fit_background, load, load_frozen, matrix, save)


def csv_save(path, rows):
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        writer.writeheader()
        writer.writerows(rows)


def read_jobs(folder, phase):
    latest = {}
    for path in sorted(folder.rglob("job.json")):
        job = load(path)
        if job["phase"] != phase:
            continue
        if job["design_sha256_lf"] != digest(DESIGN) or job["execution_commit"] != os.environ["GITHUB_SHA"]:
            raise ValueError("Job provenance mismatch")
        bid = job["block_id"]
        if bid not in latest or int(job["run_attempt"]) > int(latest[bid]["run_attempt"]):
            latest[bid] = job
    planned = {r["block_id"]: r for r in matrix(phase)}
    if set(latest) - set(planned):
        raise ValueError("Unexpected matrix jobs")
    for bid, job in latest.items():
        if any(job[k] != planned[bid][k] for k in ("context", "repetition", "role", "order")):
            raise ValueError("Recorded matrix row differs")
    return latest


def freeze(inputs, output):
    jobs = read_jobs(inputs, "background")
    status = [{"block_id": bid, "role": j["role"], "qualified": j["histories"].get("background", {}).get("qualified", False),
               "settling": j["histories"].get("background", {}).get("settling"),
               "reasons": j["histories"].get("background", {}).get("reasons", ["missing_history"])} for bid, j in jobs.items()]
    save(output / "background-status.json", {"received": len(jobs), "planned": len(matrix("background")), "histories": status})
    frozen = fit_background(list(jobs.values()))
    frozen.update(execution_commit=os.environ["GITHUB_SHA"], run_id=os.environ["GITHUB_RUN_ID"],
                  run_attempt=os.getenv("GITHUB_RUN_ATTEMPT", "1"), frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    save(output / "frozen-model.json", frozen)
    print(json.dumps({"status": "frozen", "fit_histories": len(frozen["fit_ids"]), "calibration_histories": len(frozen["calibration_ids"])}))


def score_history(history, frozen, policy):
    cfg = load(DESIGN)
    observer = Observer(frozen, history["reference"]["cpu"])
    first = {m: None for m in METHODS}
    for w in history["observations"]:
        replay = observer.update(w["cpu"])
        for method in METHODS:
            actual = w["online"][method]
            if not np.isclose(replay[method]["score"], actual["score"], rtol=1e-10, atol=1e-9):
                raise ValueError("Online score differs from prefix replay")
            if replay[method]["signal"] != actual["signal"]:
                raise ValueError("Online signal differs from prefix replay")
            if first[method] is None and actual["signal"]:
                first[method] = w["epoch"]
    output = {}
    onset = cfg["pre_intervention_windows"] + 1
    for method, epoch in first.items():
        detected = policy == "drift" and epoch is not None and epoch >= onset
        premature = policy == "drift" and epoch is not None and epoch < onset
        output[method] = {"first_epoch": epoch, "detected": detected, "premature": premature,
                          "control_signal": policy == "control" and epoch is not None,
                          "restricted_delay_windows": epoch - onset + 1 if detected else cfg["monitor_windows"] - cfg["pre_intervention_windows"]}
    return output




def compare(inputs, model_folder, output):
    cfg = load(DESIGN)
    jobs = read_jobs(inputs, "test")
    frozen = load_frozen(model_folder)
    statuses, decisions, pairs, trajectories = [], [], [], []
    for bid, job in sorted(jobs.items()):
        if job["frozen_model"] != frozen:
            raise ValueError("Test job used a different frozen model")
        qualified = all(job["histories"].get(p, {}).get("qualified", False) for p in ("drift", "control"))
        statuses.append({"block_id": bid, "qualified_pair": qualified,
                         "histories": {p: {k: h.get(k) for k in ("technical_complete", "qualified", "settling", "reasons")}
                                       for p, h in job["histories"].items()}})
        result = {}
        for policy, history in job["histories"].items():
            previous = np.zeros(len(cfg["parts"]) - 1)
            for w in history.get("observations", []):
                if not w["valid"]:
                    continue
                z = feature(w["cpu"], history["reference"]["cpu"], "ilr_composition")
                trajectories.append({"block_id": bid, "policy": policy, "epoch": w["epoch"], "qualified_pair": qualified,
                                     "total_cpu": sum(w["cpu"]), "aitchison_displacement": float(np.linalg.norm(z)),
                                     "step_norm": float(np.linalg.norm(z - previous)),
                                     **{"ilr_displacement_" + str(i+1): float(v) for i, v in enumerate(z)},
                                     **{"ilr_step_" + str(i+1): float(v) for i, v in enumerate(z - previous)}})
                previous = z
            if qualified:
                result[policy] = score_history(history, frozen, policy)
                for method, record in result[policy].items():
                    decisions.append({"block_id": bid, "policy": policy, "method": method, **record})
        if qualified:
            raw, ilr = (result["drift"][m] for m in METHODS)
            pairs.append({"block_id": bid, "raw_first_drift_epoch": raw["first_epoch"], "ilr_first_drift_epoch": ilr["first_epoch"],
                          "raw_detected": raw["detected"], "ilr_detected": ilr["detected"],
                          "raw_control_signal": result["control"]["raw_composition"]["control_signal"],
                          "ilr_control_signal": result["control"]["ilr_composition"]["control_signal"],
                          "ilr_minus_raw_restricted_delay": ilr["restricted_delay_windows"] - raw["restricted_delay_windows"]})
    methods = {}
    for method in METHODS:
        a = [r for r in decisions if r["method"] == method and r["policy"] == "drift"]
        c = [r for r in decisions if r["method"] == method and r["policy"] == "control"]
        methods[method] = {"detected": sum(r["detected"] for r in a), "premature": sum(r["premature"] for r in a),
                           "no_intervention_signals": sum(r["control_signal"] for r in c),
                           "restricted_mean_delay_windows": float(np.mean([r["restricted_delay_windows"] for r in a])) if a else None}
    summary = {"version": cfg["version"], "planned_test_pairs": len(matrix("test")), "received_test_pairs": len(jobs),
               "missing_pairs": sorted({r["block_id"] for r in matrix("test")} - set(jobs)), "qualified_pairs": len(pairs),
               "methods": methods, "fit_histories": len(frozen["fit_ids"]), "calibration_histories": len(frozen["calibration_ids"]),
               "interpretation": "Known-intervention detection and timing. Control signals are not automatically false positives. Settling is an engineering gate, not proof of stationarity.",
               "frozen_model_replayed": True}
    if cfg.get("source_frozen_model"):
        summary["source_frozen_model"] = cfg["source_frozen_model"]
        summary["sample_size_note"] = cfg["sample_size_note"]
    if pairs:
        differences = np.array([r["ilr_minus_raw_restricted_delay"] for r in pairs])
        rng = np.random.default_rng(cfg["bootstrap_seed"])
        sample = differences[rng.integers(0, len(pairs), size=(cfg["bootstrap_replicates"], len(pairs)))].mean(axis=1)
        summary["paired_delay_difference"] = {"ilr_minus_raw": float(differences.mean()),
                                               "descriptive_bootstrap_95": np.quantile(sample, [.025, .975]).tolist() if np.ptp(differences) else None}
    save(output / "summary.json", summary)
    save(output / "history-status.json", statuses)
    csv_save(output / "decisions.csv", decisions)
    csv_save(output / "pairs.csv", pairs)
    csv_save(output / "trajectories.csv", trajectories)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["freeze", "compare"])
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-folder", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.command == "freeze":
        freeze(args.inputs, args.output_dir)
    else:
        compare(args.inputs, args.model_folder, args.output_dir)
