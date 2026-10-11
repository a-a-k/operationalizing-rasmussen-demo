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
sys.path.insert(0, str(ROOT / "geometry/scripts"))
from geometry import CPU_BASIS, difference, ilr, norm

DEFINITION = "probe5/history-analysis-v0.1.0.json"


def flag(value: str) -> bool:
    if value not in {"True", "False"}:
        raise ValueError(f"Invalid recorded Boolean: {value!r}")
    return value == "True"


def canonical_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def describe(values: list[float]) -> dict:
    if not values or not all(math.isfinite(v) for v in values):
        raise ValueError("A descriptive summary requires finite observations")
    return {"median": statistics.median(values), "minimum": min(values),
            "maximum": max(values), "positive": sum(v > 0 for v in values),
            "negative": sum(v < 0 for v in values), "zero": sum(v == 0 for v in values)}


def derive(rows: list[dict], definition: dict, design: dict) -> tuple[dict, list, list, dict]:
    parts = definition["parts"]
    step = definition["comparison_step"]
    indexed = {(r["block_id"], r["policy"], int(r["epoch"])): r for r in rows}
    if len(indexed) != len(rows):
        raise ValueError("Duplicate history/epoch")
    planned = {f"migration-{i:03d}" for i in range(1, design["replications"] + 1)}
    blocks = sorted({r["block_id"] for r in rows})
    if set(blocks) - planned:
        raise ValueError("Unexpected runner identifier")

    def coordinates(row):
        q = tuple(float(row[p]) for p in parts)
        if not math.isclose(math.fsum(q), 1.0, abs_tol=1e-12, rel_tol=0):
            raise ValueError("The recorded CPU budget is not closed")
        return ilr(q, CPU_BASIS)

    history = []
    maximum_normalization_error = 0.0
    for block in blocks:
        for policy in ("control", "drift"):
            epochs = sorted(e for b, p, e in indexed if (b, p) == (block, policy))
            if not epochs or epochs != list(range(max(epochs) + 1)):
                raise ValueError("A history has missing epochs; no imputation is permitted")
            reference = previous = coordinates(indexed[block, policy, 0])
            length = 0.0
            for epoch in epochs:
                row = indexed[block, policy, epoch]
                z = coordinates(row)
                delta, displacement = difference(z, previous), difference(z, reference)
                length += norm(delta)
                seconds = design["baseline_seconds"] if epoch == 0 else design["measurement_seconds"]
                error = abs(float(row["ad_successes"]) / seconds - float(row["ad_goodput"]))
                maximum_normalization_error = max(maximum_normalization_error, error)
                if error > 1e-9:
                    raise ValueError("Goodput does not match its counter/window duration")
                record = {"block_id": block, "policy": policy, "epoch": epoch}
                record.update({p: float(row[p]) for p in parts})
                for prefix, vector in (("z", z), ("delta", delta), ("displacement", displacement)):
                    record.update({f"{prefix}{i + 1}": v for i, v in enumerate(vector)})
                record.update({"distance_from_reference": norm(displacement),
                               "registered_path_length": length,
                               "valid": flag(row["valid"]), "safe": flag(row["safe"]),
                               "p95_ms": float(row["p95_ms"]),
                               "error_rate": float(row["error_rate"]),
                               "ad_goodput": float(row["ad_goodput"])})
                history.append(record)
                previous = z

    pairs = []
    for block in blocks:
        if any((block, policy, epoch) not in indexed
               for policy, epoch in (("drift", 0), ("drift", step), ("control", 0), ("control", step))):
            raise ValueError("The selected comparison lacks a recorded endpoint")
        d0, ds, c0, cs = [indexed[block, p, e] for p, e in
                         (("drift", 0), ("drift", step), ("control", 0), ("control", step))]
        r = {"block_id": block, "epoch": step,
             "preceding_drift_ad_throttling": float(indexed[block, "drift", step - 1]["ad_throttling"]),
             "step6_donor": ds["donor"]}
        for label, row in (("drift0", d0), ("drift6", ds), ("control0", c0), ("control6", cs)):
            r.update({f"{label}_{m}": float(row[m]) for m in ("ad_goodput", "p95_ms", "error_rate")})
            r.update({f"{label}_{f}": flag(row[f]) for f in ("valid", "baseline_valid", "safe")})
        for metric, key in (("ad_goodput", "goodput_change_difference"),
                            ("p95_ms", "p95_change_difference_ms")):
            r[key] = (float(ds[metric]) - float(d0[metric])) - (float(cs[metric]) - float(c0[metric]))
        for policy, row in (("drift", ds), ("control", cs)):
            r.update({f"{policy}6_{p}_cpu": float(row[p]) for p in parts})
        r["both_positive"] = r["goodput_change_difference"] > 0 and r["p95_change_difference_ms"] > 0
        pairs.append(r)

    shared = {tuple(r[f"drift6_{p}_cpu"] for p in parts) for r in pairs}
    result = {
        "analysis_version": definition["analysis_version"],
        "selection": definition["selection"], "comparison_step": step,
        "summary_unit": definition["summary_unit"], "source_sha256_lf": definition["source_sha256_lf"],
        "planned_pairs": len(planned), "pair_count": len(pairs),
        "missing_planned_pairs": sorted(planned - set(blocks)),
        "valid_and_slo_safe_pairs": sum(all(r[f"{label}_{f}"] for label in
            ("drift0", "drift6", "control0", "control6") for f in ("valid", "baseline_valid", "safe")) for r in pairs),
        "both_positive_pairs": sum(r["both_positive"] for r in pairs),
        "goodput_change_difference_responses_per_second": describe([r["goodput_change_difference"] for r in pairs]),
        "p95_change_difference_ms": describe([r["p95_change_difference_ms"] for r in pairs]),
        "shared_step6_adaptive_allocation": list(next(iter(shared))) if len(shared) == 1 else None,
        "source_windows": len(rows), "maximum_goodput_normalization_error": maximum_normalization_error,
    }
    metadata = {
        "source": definition["source"], "source_sha256_lf": definition["source_sha256_lf"],
        "parts": parts, "resource": "CPU", "administrative_budget_cpu": 1.0,
        "basis_rows": CPU_BASIS, "reference": "Each history's recorded epoch-0 allocation",
        "execution_design": definition["execution_design"],
        "time_index": "Recorded epoch; actual decision/window timestamps are absent from the aggregate CSV",
        "registered_path_length": definition["path_length"],
        "scope": definition["scope"],
    }
    return result, history, pairs, metadata


def analyze(root: Path = ROOT) -> tuple[dict, list, list, dict]:
    definition = json.loads((root / DEFINITION).read_text(encoding="utf-8"))
    for name, key in (("source", "source_sha256_lf"), ("execution_design", "execution_design_sha256_lf")):
        if canonical_sha(root / definition[name]) != definition[key]:
            raise ValueError(f"Frozen source checksum mismatch: {definition[name]}")
    design = json.loads((root / definition["execution_design"]).read_text(encoding="utf-8"))
    with (root / definition["source"]).open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return derive(rows, definition, design)


def save(output: Path, result: dict, history: list, pairs: list, metadata: dict) -> None:
    output.mkdir(parents=True, exist_ok=False)
    for name, value in (("summary.json", result), ("measurement-metadata.json", metadata)):
        (output / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")
    for name, rows in (("ilr-history.csv", history), ("step6-pairs.csv", pairs)):
        with (output / name).open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay the versioned saved-data CPU-history analysis.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result, history, pairs, metadata = analyze()
    save(args.output_dir, result, history, pairs, metadata)
    print(json.dumps({"analysis_version": result["analysis_version"],
                      "pairs": result["pair_count"], "source_windows": len(history)}))


if __name__ == "__main__":
    main()
