from __future__ import annotations

import argparse
import csv
import itertools
import json
import statistics
from collections import Counter
from pathlib import Path

from scenarios import DESIGN, OVERLAY, ROOT, RUNTIME, VERSION, arm, features, load, matrix, sha256_file, write_json

SIGNS = {"R_group": 1, "checkout_quota": -1, "payment_quota": -1,
         "shipping_quota": -1, "minimum_group_quota": -1, "group_sum": -1,
         "reduced_count": 1, "E": 1, "d_A": 1}
SERVICES = ["checkout", "payment", "shipping"]


def counts(rows: list[dict], alarms: list[bool], rule: dict) -> dict:
    tp = sum(a and r["unsafe"] for r, a in zip(rows, alarms))
    fp = sum(a and not r["unsafe"] for r, a in zip(rows, alarms))
    positives = sum(r["unsafe"] for r in rows)
    return {"rule": rule, "tp": tp, "fp": fp, "fn": positives - tp,
            "tn": len(rows) - positives - fp}


def threshold_table(rows: list[dict], feature: str) -> list[dict]:
    sign = SIGNS[feature]
    scores = [round(sign * r["scores"][feature], 12) for r in rows]
    result = [counts(rows, [False] * len(rows), {"operator": "disabled", "threshold": None})]
    for value in sorted(set(scores), reverse=True):
        rule = {"operator": ">=" if sign > 0 else "<=", "threshold": value * sign}
        result.append(counts(rows, [v >= value for v in scores], rule))
    return result


def local_or_table(rows: list[dict]) -> list[dict]:
    cuts = [[None, *sorted({r["scores"][s + "_quota"] for r in rows})] for s in SERVICES]
    result = []
    for thresholds in itertools.product(*cuts):
        rule = dict(zip(SERVICES, thresholds))
        alarms = [any(t is not None and r["scores"][s + "_quota"] <= t
                      for s, t in rule.items()) for r in rows]
        result.append(counts(rows, alarms, {"operator": "OR of <=", "thresholds": rule}))
    return result


def compare(rows: list[dict]) -> dict:
    tables = {feature: threshold_table(rows, feature) for feature in SIGNS}
    tables["local_or"] = local_or_table(rows)
    safe = sum(not r["unsafe"] for r in rows)
    envelopes = {model: [max((p for p in table if p["fp"] <= budget),
                             key=lambda p: (p["tp"], -p["fp"]))
                         for budget in range(safe + 1)] for model, table in tables.items()}
    relations = {}
    for model in tables:
        changes = [a["tp"] - b["tp"] for a, b in zip(envelopes["R_group"], envelopes[model])]
        relations[model] = {"better_at_fp_budgets": [i for i, d in enumerate(changes) if d > 0],
                            "worse_at_fp_budgets": [i for i, d in enumerate(changes) if d < 0],
                            "same_at_fp_budgets": [i for i, d in enumerate(changes) if d == 0]}
    return {"n": len(rows), "unsafe": len(rows) - safe, "safe": safe,
            "informative_two_class_comparison": bool(safe and len(rows) > safe),
            "all_thresholds": tables, "fp_budget_envelopes": envelopes,
            "balance_comparison": relations}


def collect(repo: Path, design: dict, blocks: dict, commit: str) -> tuple[list[dict], list[str]]:
    expected = {r["block_id"]: r for r in matrix(design)}
    if set(blocks) - set(expected):
        raise ValueError("unexpected block IDs")
    hashes = {"design_sha256": sha256_file(repo / DESIGN), "runtime_sha256": sha256_file(repo / RUNTIME),
              "overlay_sha256": sha256_file(repo / OVERLAY)}
    rows = []
    for bid, spec in expected.items():
        block = blocks.get(bid)
        if block:
            if block["study_version"] != VERSION or block["repository_commit"] != commit:
                raise ValueError(f"block version or commit mismatch: {bid}")
            if any(block.get(key) != value for key, value in hashes.items()):
                raise ValueError(f"block input hashes differ: {bid}")
            if any(block.get(key) != spec[key] for key in spec) or set(block["points"]) != set(spec["order"]):
                raise ValueError(f"block conditions or order mismatch: {bid}")
        panel = design["panels"][spec["panel"]]
        for point_id in spec["order"]:
            p = block["points"][point_id] if block else None
            q = panel[point_id]
            scores = features(arm(design, spec), q)
            scores.update(payment_quota=q["payment"], shipping_quota=q["shipping"])
            t = p.get("test") if p else None
            recoverable = bool(p and p.get("primary_recoverable") and t is not None)
            if p:
                if p["point_id"] != point_id or p["block_id"] != bid or p["test_quotas"] != q:
                    raise ValueError(f"point specification differs: {bid}/{point_id}")
                if p["study_version"] != VERSION or p["rate"] != spec["rate"]:
                    raise ValueError(f"point version or load differs: {bid}/{point_id}")
                if p["valid"] and not recoverable:
                    raise ValueError("valid point without primary outcome")
            unsafe = None
            if recoverable:
                safe = t["p95_ms"] is not None and t["p95_ms"] <= 500 and t["error_rate"] < 0.01
                if t["safe"] is not safe:
                    raise ValueError("stored SLO label differs from measured latency/errors")
                unsafe = not safe
            rows.append({"rate": spec["rate"], "panel": spec["panel"], "block_id": bid,
                         "repetition": spec["repetition"], "point_id": point_id,
                         "position": spec["order"].index(point_id) + 1, "recorded": bool(p),
                         "valid": bool(p and p["valid"]), "primary_recoverable": recoverable,
                         "reasons": p["reason_codes"] if p else ["missing_block"],
                         "unsafe": unsafe, "p95_ms": t.get("p95_ms") if t else None,
                         "error_rate": t.get("error_rate") if t else None,
                         "post_intervention_failure": bool(p and p.get("post_intervention_failures")),
                         "post_intervention_oom": bool(p and any(e["action"] == "oom" and e["post_intervention"]
                                                   for e in p.get("diagnostics", {}).get("failure_events", []))),
                         "scores": scores, "quotas": q})
    return rows, sorted(set(expected) - set(blocks))


def analyze(repo: Path, blocks: dict, commit: str) -> tuple[dict, list[dict]]:
    design = load(repo / DESIGN)
    rows, missing = collect(repo, design, blocks, commit)
    report = {"study_version": VERSION, "repository_commit": commit,
              "status": "complete" if not missing else "incomplete", "missing_blocks": missing,
              "planned_points": len(rows), "recorded_points": sum(r["recorded"] for r in rows),
              "valid_points": sum(r["valid"] for r in rows), "analysis": design["analysis"],
              "memory_note": load(repo / RUNTIME)["memory_override"], "rates": {}}
    for rate in design["rates"]:
        rr = [r for r in rows if r["rate"] == rate]
        points = {}
        for name in [name for panel in design["panels"].values() for name in panel]:
            pp = [r for r in rr if r["point_id"] == name]
            valid = [r for r in pp if r["valid"]]
            recoverable = [r for r in pp if r["primary_recoverable"]]
            latencies = [r["p95_ms"] for r in valid if r["p95_ms"] is not None]
            points[name] = {"quotas": pp[0]["quotas"], "R_group": pp[0]["scores"]["R_group"],
                            "planned": len(pp), "valid": len(valid),
                            "unsafe_valid": sum(r["unsafe"] for r in valid),
                            "recoverable": len(recoverable), "unsafe_recoverable": sum(r["unsafe"] for r in recoverable),
                            "median_p95_ms_valid": statistics.median(latencies) if latencies else None,
                            "post_intervention_failures": sum(r["post_intervention_failure"] for r in pp),
                            "oom_points": sum(r["post_intervention_oom"] for r in pp),
                            "invalid_reasons": dict(Counter(reason for r in pp for reason in r["reasons"]))}
        report["rates"][str(rate)] = {"points": points, "valid": compare([r for r in rr if r["valid"]]),
                                      "all_recoverable": compare([r for r in rr if r["primary_recoverable"]])}
    return report, rows


def markdown(report: dict) -> str:
    text = ["# Allocation scenarios: threshold comparison", "",
            "Exploratory, in-sample comparison; no held-out prediction, binary scientific success criterion, or pooling with earlier observations.", "",
            f"Recorded {report['recorded_points']}/{report['planned_points']} points; valid {report['valid_points']}. Missing blocks: {report['missing_blocks']}.", "",
            "Fixed memory reserves: checkout 256 MiB (GOMEMLIMIT=192MiB), PostgreSQL 1 GiB. OOM/restart is diagnostic, never an SLO-label override or exclusion. No pooling with the cancelled runtime attempt.", ""]
    for rate, data in report["rates"].items():
        text.extend([f"## Fixed load: {rate} iterations/s", "",
                     "| Allocation | CPU: checkout / payment / shipping / ad | Balance displacement | Unsafe / valid | Unsafe / recoverable | Failures / OOM | Median p95, valid (ms) |",
                     "| --- | --- | ---: | ---: | ---: | ---: | ---: |"])
        for name, p in data["points"].items():
            quota = " / ".join(f"{p['quotas'][s]:.2f}" for s in [*SERVICES, "ad"])
            latency = f"{p['median_p95_ms_valid']:.1f}" if p['median_p95_ms_valid'] is not None else "NA"
            text.append(f"| {name} | {quota} | {p['R_group']:.4f} | {p['unsafe_valid']}/{p['valid']} | {p['unsafe_recoverable']}/{p['recoverable']} | {p['post_intervention_failures']} / {p['oom_points']} | {latency} |")
        for subset in ["valid", "all_recoverable"]:
            c = data[subset]
            text.extend(["", f"### {subset}: {c['unsafe']} unsafe, {c['safe']} safe points", ""])
            if not c["informative_two_class_comparison"]:
                text.extend(["Only one outcome class (or no primary outcomes): this subset cannot establish discriminative advantage.", ""])
            models = list(c["fp_budget_envelopes"])
            text.extend(["Each cell is detected unsafe points / actual false alarms. The budget is a maximum, not an exact number of alarms or a pass criterion.", "",
                         "| Maximum false alarms | " + " | ".join(models) + " |",
                         "| ---: | " + " | ".join(["---:"] * len(models)) + " |"])
            for budget in range(c["safe"] + 1):
                cells = [f"{c['fp_budget_envelopes'][m][budget]['tp']}/{c['fp_budget_envelopes'][m][budget]['fp']}" for m in models]
                text.append(f"| {budget} | " + " | ".join(cells) + " |")
            text.append("")
    text.extend(["## Reading the result", "",
                 "A balance advantage at a budget means fewer missed unsafe points among these observations while staying within the same maximum false-alarm count. Crossing curves mean a trade-off, not a universally better method. The budgets are correlated display coordinates, not statistical votes.", "",
                 "All achievable thresholds are retained, including disabling alarms. Local OR exhausts separate per-service thresholds, so it is a flexible in-sample oracle comparator. No favorable threshold is presented as independently validated performance. Quota thresholds are not alerts on measured CPU utilization or throttling.", "",
                 "Multiple redistribution directions expand the tested state context; the joint panel alone would merely compare monotone reparameterizations. Identical balance values with different SLO outcomes remain evidence against scalar sufficiency and are not discarded.", "",
                 "The reference allocation is a sham intervention, not an expected-safe label. Baseline failures can prevent a test; missing and invalid points remain in the point table. Recoverable technical-invalid outcomes are also compared separately. Results at the two loads are never pooled.", "",
                 "These are independently measured allocations, not a temporally observed adaptive process. They show representation and discrimination on fixed scenarios, not adaptation incentives, advertisement performance, early warning, or general operational reliability.", "",
                 f"Full rules, confusion counts and false-alarm-budget envelopes: comparison.json and thresholds.csv. All {report['planned_points']} planned point records, including missing/invalid observations: point-level.csv.", ""])
    return "\n".join(text)


def save(repo: Path, inputs: Path, output: Path, commit: str) -> dict:
    blocks = {}
    for path in sorted(inputs.rglob("block-result.json")):
        block = load(path)
        if block["block_id"] in blocks:
            raise ValueError("duplicate block result")
        blocks[block["block_id"]] = block
    report, rows = analyze(repo, blocks, commit)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "comparison.json", report)
    flat = [{**{k: v for k, v in r.items() if k not in {"scores", "quotas", "reasons"}},
             "reasons": "|".join(r["reasons"]), **r["scores"], "ad_quota": r["quotas"]["ad"]} for r in rows]
    with (output / "point-level.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(flat[0]))
        writer.writeheader()
        writer.writerows(flat)
    curves = [{"rate": rate, "subset": subset, "method": model, "rule": json.dumps(p["rule"], sort_keys=True),
               **{k: p[k] for k in ("tp", "fp", "fn", "tn")}}
              for rate, data in report["rates"].items() for subset in ["valid", "all_recoverable"]
              for model, table in data[subset]["all_thresholds"].items() for p in table]
    with (output / "thresholds.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(curves[0]))
        writer.writeheader()
        writer.writerows(curves)
    (output / "RESULTS.md").write_text(markdown(report), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repository-commit", required=True)
    args = parser.parse_args()
    report = save(ROOT, args.results_root, args.output_dir, args.repository_commit)
    print(json.dumps({"status": report["status"], "valid_points": report["valid_points"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
