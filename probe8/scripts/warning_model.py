from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe7/scripts"))
from model import representation

DEFINITION = "probe8/warning-design-v0.1.0.json"
FROZEN = "probe8/frozen-model-v0.1.0.json"
PROCESSES = ("checkout", "advertising", "accounting")


def canonical_hash(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def read_inputs(root=ROOT):
    definition = json.loads((root / DEFINITION).read_text())
    for key in ("source_records", "parent_design"):
        if canonical_hash(root / definition[key]) != definition[key + "_sha256_lf"]:
            raise ValueError("Development source differs: " + key)
    blocks = json.loads((root / definition["source_records"]).read_text())
    design = json.loads((root / definition["parent_design"]).read_text())
    if any(b["mode"] != "main" or b["design"] != design for b in blocks.values()):
        raise ValueError("Mixed development provenance")
    return definition, design, blocks


def target(observations, epoch, horizon):
    indexed = {w["epoch"]: w for w in observations}
    future = [indexed.get(epoch + k) for k in range(1, horizon + 1)]
    if any(w and w["valid"] and w["safe"] is False for w in future):
        return 1
    if all(w and w["valid"] and w["safe"] is True for w in future):
        return 0
    return None


def clip(value):
    return max(-1., min(1., value))


def coordinates(window, design):
    r = representation(window["allocation"], design)
    return {"ilr_history": [r["ilr"][:10], r["ilr"][10:]],
            "share_history": [r["shares"]["cpu"], r["shares"]["memory"]],
            "local_history": [r["local"]], "service_indicators": []}


def current_features(prefix, design, definition):
    if not prefix or [w["epoch"] for w in prefix] != list(range(len(prefix))):
        return None, "nonconsecutive_prefix"
    current = prefix[-1]
    if current["epoch"] > design["cycles"] - definition["horizon_cycles"]:
        return None, "planned_horizon_unobserved"
    if any(not w["valid"] for w in prefix):
        return None, "invalid_prefix"
    if current["safe"] is not True:
        return None, "currently_unsafe_or_unknown"
    previous = prefix[-2] if len(prefix) > 1 else current
    heads = [current["headroom"][p] for p in PROCESSES]
    before = [previous["headroom"][p] for p in PROCESSES]
    if any(v is None or not math.isfinite(v) for v in heads + before):
        return None, "unavailable_current_or_previous_headroom"
    return {"epoch": current["epoch"], "business": [clip(v) for v in heads] +
            [clip(a - b) for a, b in zip(heads, before)],
            "prefix": [coordinates(w, design) for w in prefix]}, None


def prepare(blocks, design, definition):
    examples, snapshots = [], []
    for bid, block in sorted(blocks.items()):
        for policy, history in sorted(block["histories"].items()):
            observations = sorted(history["observations"], key=lambda w: w["epoch"])
            for i, w in enumerate(observations):
                if w["valid"]:
                    snapshots.append({"block_id": bid, "coords": coordinates(w, design)})
                features, reason = current_features(observations[:i + 1], design, definition)
                outcome = target(observations, w["epoch"], definition["horizon_cycles"])
                if features is not None and outcome is not None:
                    examples.append({"block_id": bid, "policy": policy, "profile": block["profile"],
                                     "label": outcome, **features})
    return examples, snapshots


def scatter_scales(snapshots, methods):
    result = {}
    for method in methods:
        groups = len(snapshots[0]["coords"][method]) if snapshots else 0
        scales = []
        for group in range(groups):
            values = [r["coords"][method][group] for r in snapshots]
            center = [statistics.mean(v[i] for v in values) for i in range(len(values[0]))]
            variance = statistics.mean(math.fsum((x - y)**2 for x, y in zip(v, center)) for v in values)
            scales.append(math.sqrt(variance) if variance > 1e-20 else None)
        result[method] = scales
    return result


def history_distance(query, candidate, method, scales):
    if query["epoch"] != candidate["epoch"]:
        raise ValueError("Prefix lengths must match")
    value = math.fsum((a - b)**2 for a, b in zip(query["business"], candidate["business"]))
    for group, scale in enumerate(scales[method]):
        if scale is None:
            continue
        value += math.fsum(math.fsum((a - b)**2 for a, b in zip(x[method][group], y[method][group]))
                           for x, y in zip(query["prefix"], candidate["prefix"])) / (len(query["prefix"]) * scale**2)
    return math.sqrt(max(0., value))


def predict(query, candidates, scales, definition, exclude_pair=None):
    pool = [c for c in candidates if c["profile"] == query["profile"] and c["epoch"] == query["epoch"]
            and c["block_id"] != exclude_pair]
    results = {}
    tolerance = definition["tie_tolerance"]
    for method in definition["methods"]:
        by_pair = {}
        for candidate in pool:
            distance = history_distance(query, candidate, method, scales)
            by_pair.setdefault(candidate["block_id"], []).append((distance, candidate))
        ranked = []
        for bid, candidates_in_pair in by_pair.items():
            minimum = min(d for d, _ in candidates_in_pair)
            tied = [c for d, c in candidates_in_pair if d <= minimum + tolerance]
            ranked.append((minimum, bid, statistics.mean(c["label"] for c in tied)))
        ranked.sort()
        if not ranked:
            results[method] = {"score": None, "neighbor_pairs": 0, "neighbors": []}
            continue
        cut = ranked[min(definition["neighbor_pairs"], len(ranked)) - 1][0]
        selected = [r for r in ranked if r[0] <= cut + tolerance]
        results[method] = {"score": statistics.mean(r[2] for r in selected),
                           "neighbor_pairs": len(selected), "neighbors": [r[1] for r in selected]}
    return results


def alerts(score, threshold):
    return score is not None and threshold is not None and score >= threshold


def threshold_rows(records, method):
    usable = [r for r in records if r["method"] == method and r["score"] is not None]
    positives = sum(r["label"] == 1 for r in usable)
    negatives = len(usable) - positives
    thresholds = [None] + sorted({r["score"] for r in usable}, reverse=True)
    result = []
    for threshold in thresholds:
        tp = sum(r["label"] == 1 and alerts(r["score"], threshold) for r in usable)
        fp = sum(r["label"] == 0 and alerts(r["score"], threshold) for r in usable)
        result.append({"method": method, "threshold": threshold, "true_warning_decisions": tp,
                       "false_warning_decisions": fp, "positive_decisions": positives, "negative_decisions": negatives,
                       "recall": tp / positives if positives else None,
                       "false_warning_rate": fp / negatives if negatives else None,
                       "precision": tp / (tp + fp) if tp + fp else None})
    return result


def choose_threshold(rows, definition):
    eligible = [r for r in rows if r["false_warning_rate"] is not None and
                r["false_warning_rate"] <= definition["false_warning_rate_budget"]]
    if not eligible:
        return None
    selected = max(eligible, key=lambda r: (r["true_warning_decisions"], -r["false_warning_decisions"],
                                          math.inf if r["threshold"] is None else r["threshold"]))
    return selected["threshold"]


def csv_save(path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in rows for k in r)), lineterminator="\n")
            writer.writeheader(); writer.writerows(rows)


def development(output, commit, run_id, root=ROOT):
    definition, design, blocks = read_inputs(root)
    examples, snapshots = prepare(blocks, design, definition)
    records = []
    for bid in sorted(blocks):
        library = [c for c in examples if c["block_id"] != bid]
        scales = scatter_scales([r for r in snapshots if r["block_id"] != bid], definition["methods"])
        for query in (r for r in examples if r["block_id"] == bid):
            results = predict(query, library, scales, definition, exclude_pair=bid)
            for method, result in results.items():
                records.append({"block_id": bid, "policy": query["policy"], "profile": query["profile"],
                                "epoch": query["epoch"], "label": query["label"], "method": method,
                                "score": result["score"], "neighbor_pairs": result["neighbor_pairs"]})
    curves = [r for method in definition["methods"] for r in threshold_rows(records, method)]
    thresholds = {method: choose_threshold([r for r in curves if r["method"] == method], definition)
                  for method in definition["methods"]}
    model = {"version": definition["version"], "definition": definition,
             "definition_sha256_lf": canonical_hash(root / DEFINITION),
             "development_execution": {"commit": commit, "run_id": str(run_id)},
             "training_pairs": len(blocks), "training_query_decisions": len(examples),
             "positive_query_decisions": sum(r["label"] for r in examples),
             "scales": scatter_scales(snapshots, definition["methods"]), "thresholds": thresholds,
             "scope": "Frozen before new confirmation observations; development counts are not confirmation performance."}
    output.mkdir(parents=True, exist_ok=False)
    (output / "frozen-model-v0.1.0.json").write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8")
    csv_save(output / "development-decisions.csv", records)
    csv_save(output / "development-thresholds.csv", curves)
    operating = [r for r in curves if r["threshold"] == thresholds[r["method"]]]
    csv_save(output / "development-operating-points.csv", operating)
    (output / "README.md").write_text("# Warning-rule development\n\nSaved-data development only; no runtime confirmation evidence.\n\n"
        "Whole runner pairs are held out for score calculation. Thresholds are then fitted to these development scores; their performance is not an independent estimate.\n\n"
        "[Frozen model](frozen-model-v0.1.0.json), [all decisions](development-decisions.csv), [every threshold](development-thresholds.csv), [selected operating points](development-operating-points.csv).\n", encoding="utf-8")
    print(json.dumps({"queries": len(examples), "positive_queries": model["positive_query_decisions"],
                      "thresholds": thresholds, "operating_points": operating}))
    return model


class WarningModel:
    def __init__(self, root=ROOT):
        self.definition, self.design, blocks = read_inputs(root)
        self.frozen = json.loads((root / FROZEN).read_text())
        if self.frozen["definition"] != self.definition or self.frozen["definition_sha256_lf"] != canonical_hash(root / DEFINITION):
            raise ValueError("Model and warning definition differ")
        self.library, snapshots = prepare(blocks, self.design, self.definition)
        calculated = scatter_scales(snapshots, self.definition["methods"])
        for method, values in calculated.items():
            for a, b in zip(values, self.frozen["scales"][method]):
                if (a is None) != (b is None) or (a is not None and not math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10)):
                    raise ValueError("Frozen scales differ from source")

    def score(self, prefix, profile):
        features, reason = current_features(prefix, self.design, self.definition)
        if features is None:
            return {"eligible": False, "reason": reason, "methods": {}}
        results = predict({**features, "profile": profile}, self.library, self.frozen["scales"], self.definition)
        for method, result in results.items():
            result["threshold"] = self.frozen["thresholds"][method]
            result["alert"] = alerts(result["score"], result["threshold"])
        return {"eligible": True, "reason": None, "methods": results}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    development(args.output_dir, args.commit, args.run_id)


if __name__ == "__main__":
    main()
