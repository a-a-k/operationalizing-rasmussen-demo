from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from study import DESIGN, ROOT, RUNTIME, VERSION, features, load, matrix, proportion, sha256_file, write_json


def pair_counts(rows: list[tuple[dict, dict]]) -> dict[str, Any]:
    forward = sum(a["test"]["safe"] and not b["test"]["safe"] for a, b in rows)
    reverse = sum(not a["test"]["safe"] and b["test"]["safe"] for a, b in rows)
    contrasts = [b["test"]["p95_ms"] - a["test"]["p95_ms"] for a, b in rows
                 if a["test"]["p95_ms"] is not None and b["test"]["p95_ms"] is not None]
    return {
        "left_safe_right_unsafe": proportion(forward, len(rows)),
        "left_unsafe_right_safe": proportion(reverse, len(rows)),
        "discordant": forward + reverse,
        "both_safe": sum(a["test"]["safe"] and b["test"]["safe"] for a, b in rows),
        "both_unsafe": sum(not a["test"]["safe"] and not b["test"]["safe"] for a, b in rows),
        "median_p95_difference_right_minus_left_ms": statistics.median(contrasts) if contrasts else None,
        "complete_latency_pairs": len(contrasts),
    }


def analyze(design: dict, blocks: dict[str, dict], repository_commit: str) -> dict:
    expected = {r["block_id"]: r for r in matrix(design)}
    extra = sorted(set(blocks) - set(expected))
    if extra:
        raise ValueError(f"unexpected blocks: {extra}")
    arms = {}
    for arm_id, arm in design["arms"].items():
        ids = [k for k, row in expected.items() if row["arm"] == arm_id]
        collected = []
        for bid in ids:
            if bid not in blocks:
                continue
            block = blocks[bid]
            if block["study_version"] != VERSION or block["repository_commit"] != repository_commit:
                raise ValueError(f"block provenance differs: {bid}")
            if block["order"] != expected[bid]["order"] or set(block["points"]) != set(arm["points"]):
                raise ValueError(f"block conditions/order differ: {bid}")
            collected.append(block)
        points = {}
        for name, q in arm["points"].items():
            pp = [b["points"][name] for b in collected]
            recoverable = [p for p in pp if p.get("primary_recoverable") and p.get("test") is not None]
            valid = [p for p in recoverable if p["valid"]]
            latencies = [p["test"]["p95_ms"] for p in valid if p["test"]["p95_ms"] is not None]
            points[name] = {
                "quotas": q, "features": features(arm, q),
                "recorded_points": len(pp), "recoverable_points": len(recoverable),
                "valid_points": len(valid),
                "unsafe_valid": proportion(sum(not p["test"]["safe"] for p in valid), len(valid)),
                "unsafe_all_recoverable": proportion(sum(not p["test"]["safe"] for p in recoverable), len(recoverable)),
                "median_p95_ms_valid": statistics.median(latencies) if latencies else None,
                "invalid_reason_counts": dict(Counter(reason for p in pp for reason in p["reason_codes"])),
                "post_intervention_failure_points": sum(bool(p.get("post_intervention_failures")) for p in recoverable),
                "post_intervention_oom_event_points": sum(any(
                    e["action"] == "oom" and e["post_intervention"]
                    for e in p.get("diagnostics", {}).get("failure_events", [])) for p in recoverable),
                "runner_image_counts": dict(Counter(p["provenance"]["runner_image_version"] for p in pp)),
            }
        comparisons = {}
        for comparison in arm["comparisons"]:
            left, right = comparison["left"], comparison["right"]
            recoverable = [(b["points"][left], b["points"][right]) for b in collected
                           if all(b["points"][k].get("primary_recoverable") and b["points"][k].get("test") is not None
                                  for k in (left, right))]
            valid = [(a, b) for a, b in recoverable if a["valid"] and b["valid"]]
            no_restart = [(a, b) for a, b in valid if not a.get("post_intervention_failures")
                          and not b.get("post_intervention_failures")]
            valid_ids = [b["block_id"] for b in collected
                         if all(b["points"][k]["valid"] for k in (left, right))]
            forward_ids = [b["block_id"] for b in collected if b["block_id"] in valid_ids
                           and b["points"][left]["test"]["safe"] and not b["points"][right]["test"]["safe"]]
            reverse_ids = [b["block_id"] for b in collected if b["block_id"] in valid_ids
                           and not b["points"][left]["test"]["safe"] and b["points"][right]["test"]["safe"]]
            comparisons[comparison["id"]] = {
                **comparison, "valid_pairs": pair_counts(valid),
                "all_recoverable_pairs": pair_counts(recoverable),
                "valid_pairs_without_snapshot_failures": pair_counts(no_restart),
                "left_safe_right_unsafe_block_ids": forward_ids,
                "left_unsafe_right_safe_block_ids": reverse_ids,
                "missing_or_invalid_pairs": len(ids) - len(valid),
            }
        arms[arm_id] = {
            "planned_blocks": len(ids), "received_blocks": len(collected),
            "complete_valid_blocks": sum(b["valid"] for b in collected),
            "points": points, "comparisons": comparisons,
        }
    return {
        "study_version": VERSION, "repository_commit": repository_commit,
        "status": "complete" if set(blocks) == set(expected) else "incomplete",
        "planned_blocks": len(expected), "received_blocks": len(blocks),
        "missing_blocks": sorted(set(expected) - set(blocks)),
        "analysis": design["analysis"], "arms": arms,
        "interval_note": "Descriptive exact binomial intervals, conditional on the stated subsets and under independent-repeat assumptions; not detector accuracy or general production risk.",
        "diagnostic_note": "Restarts and OOM never override latency/error SLO labels. All recoverable outcomes are retained separately from generator-valid/manipulation-valid subsets.",
        "no_restart_subset_note": "Conditional descriptive subset without snapshot-detected post-intervention failures; selection is on a post-intervention diagnostic, not a separate randomized intervention or a causal CPU-only estimate. Full event traces are retained separately.",
    }


def save(repo: Path, results: Path, output: Path, commit: str) -> dict:
    blocks = {}
    for path in sorted(results.rglob("block-result.json")):
        block = load(path)
        key = block["block_id"]
        if key in blocks:
            raise ValueError(f"duplicate block: {key}")
        blocks[key] = block
    design = load(repo / DESIGN)
    summary = analyze(design, blocks, commit)
    summary["design_sha256"] = sha256_file(repo / DESIGN)
    summary["runtime_sha256"] = sha256_file(repo / RUNTIME)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "summary.json", summary)
    write_json(output / "block-level.json", blocks)
    rows = []
    for block in blocks.values():
        for name, p in block["points"].items():
            t = p.get("test") or {}
            rows.append({
                "arm": block["arm"], "block_id": block["block_id"], "point_id": name,
                "position": block["order"].index(name) + 1, "valid": p["valid"],
                "primary_recoverable": p["primary_recoverable"],
                "reasons": "|".join(p["reason_codes"]), **p["features"],
                **{k: t.get(k) for k in (
                    "safe", "p95_ms", "error_rate", "scheduled_iterations", "started_iterations",
                    "finished_iterations", "successful_iterations", "failed_iterations",
                    "dropped_iterations", "unfinished_iterations", "operation_p95_ms", "operation_max_ms",
                )},
                "restart_or_failure": bool(p.get("post_intervention_failures")),
                **{k: p.get("diagnostics", {}).get(k) for k in (
                    "test_host_cpu_fraction_mean", "test_host_cpu_fraction_max",
                    "test_generator_cpu_cores_mean", "test_generator_cpu_cores_max",
                    "test_generator_sample_intervals",
                )},
                "runner_image_version": p["provenance"]["runner_image_version"],
            })
    if rows:
        with (output / "point-level.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    text = ["# Fixed follow-up: descriptive results", "",
            "These are new observations only; no pooling with historical probes.", "",
            "No fitted alert threshold, majority criterion, optional extension or binary scientific pass/fail.", ""]
    for arm_id, arm in summary["arms"].items():
        text.extend([f"## {arm_id}", "", "| Point | Valid | Unsafe (valid) | Unsafe (all recoverable) | Post-intervention failures | p95 median, valid (ms) |",
                     "| --- | ---: | ---: | ---: | ---: | ---: |"])
        for name, point in arm["points"].items():
            allp = point["unsafe_all_recoverable"]
            text.append(f"| {name} | {point['valid_points']} | {point['unsafe_valid']['K']} | {allp['K']}/{allp['N']} | {point['post_intervention_failure_points']} | {point['median_p95_ms_valid']} |")
        text.extend(["", "| Comparison | Left safe / right unsafe | Reverse | Discordant |",
                     "| --- | ---: | ---: | ---: |"])
        for name, comp in arm["comparisons"].items():
            counts = comp["valid_pairs"]
            forward, reverse = counts["left_safe_right_unsafe"], counts["left_unsafe_right_safe"]
            text.append(f"| {name} | {forward['K']}/{forward['N']} | {reverse['K']}/{reverse['N']} | {counts['discordant']} |")
        text.append("")
    text.extend([
        "Matched sums/counts show representational ambiguity only when observed outcomes differ.",
        "A differing balance is not by itself evidence that it predicts SLO or beats minimum-quota rules.",
        "Discordance at the same balance limits the sufficiency of that scalar coordinate.",
        "Timeout-saturated p95 is a censored severity measure. Technical-invalid points are retained in the all-recoverable analysis.",
        "The no-snapshot-failure comparison is a conditional diagnostic subset, not an independently randomized CPU-only experiment.",
        "",
        "Full counts, exact intervals, validity reasons and both contrast directions: summary.json, block-level.json and point-level.csv.",
    ])
    (output / "RESULTS.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repository-commit", required=True)
    args = parser.parse_args()
    report = save(ROOT, args.results_root, args.output_dir, args.repository_commit)
    print(json.dumps({"status": report["status"], "received_blocks": report["received_blocks"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
