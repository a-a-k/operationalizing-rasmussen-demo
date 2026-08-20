from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from experimentlib import median, write_json
from lean_design import confirmation_replication_ids, load_json


def beta_fraction(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > 1e-300 else 1e-300)
    result = d
    for iteration in range(1, 301):
        m2 = 2 * iteration
        coefficient = iteration * (b - iteration) * x / ((qam + m2) * (a + m2))
        d = 1.0 + coefficient * d
        d = 1.0 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1.0 + coefficient / (c if abs(c) > 1e-300 else 1e-300)
        result *= d * c
        coefficient = -(a + iteration) * (qab + iteration) * x / ((a + m2) * (qap + m2))
        d = 1.0 + coefficient * d
        d = 1.0 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1.0 + coefficient / (c if abs(c) > 1e-300 else 1e-300)
        delta = d * c
        result *= delta
        if abs(delta - 1.0) <= 3e-14:
            return result
    raise ArithmeticError("incomplete beta fraction did not converge")


def regularized_beta(x: float, a: float, b: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    factor = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return factor * beta_fraction(a, b, x) / a
    return 1.0 - factor * beta_fraction(b, a, 1.0 - x) / b


def beta_quantile(probability: float, a: float, b: float) -> float:
    low, high = 0.0, 1.0
    for _ in range(100):
        middle = (low + high) / 2.0
        if regularized_beta(middle, a, b) < probability:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def clopper_pearson(successes: int, trials: int, alpha: float = 0.05) -> list[float]:
    lower = 0.0 if successes == 0 else beta_quantile(alpha / 2.0, successes, trials - successes + 1)
    upper = 1.0 if successes == trials else beta_quantile(1.0 - alpha / 2.0, successes + 1, trials - successes)
    return [lower, upper]


def bootstrap_median(values: list[float], seed: int, resamples: int) -> list[float]:
    import numpy as np

    generator = np.random.Generator(np.random.PCG64(seed))
    data = np.asarray(values, dtype=float)
    indices = generator.integers(0, len(data), size=(resamples, len(data)))
    statistics = np.median(data[indices], axis=1)
    return [float(value) for value in np.quantile(statistics, [0.025, 0.975], method="linear")]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({field for row in rows for field in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--selected", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    state, selected = load_json(args.state), load_json(args.selected)
    rows: list[dict[str, Any]] = []
    replication_ids = confirmation_replication_ids(selected["confirmation"])
    for replication_id in replication_ids:
        result = state["valid_results"].get(replication_id)
        if not result:
            continue
        a, b = result["points"]["A5"]["test"], result["points"]["B5"]["test"]
        delta = None if a.get("p95_ms") is None or b.get("p95_ms") is None else (b["p95_ms"] - a["p95_ms"]) / 500.0
        rows.append({
            "replication_id": replication_id,
            "attempt_id": result["attempt_id"],
            "order": "->".join(result["order"]),
            "a5_safe": result["primary"]["a5_safe"],
            "b5_safe": result["primary"]["b5_safe"],
            "y": result["primary"]["y"],
            "a5_p95_ms": a.get("p95_ms"),
            "b5_p95_ms": b.get("p95_ms"),
            "a5_error_rate": a.get("error_rate"),
            "b5_error_rate": b.get("error_rate"),
            "normalized_p95_difference_b_minus_a": delta,
        })
    target = len(replication_ids)
    complete = state.get("status") == "complete" and len(rows) == target
    primary: dict[str, Any] = {"evaluated": complete, "valid_replicates": len(rows)}
    if complete:
        successes = sum(row["y"] for row in rows)
        primary.update({
            "N": target,
            "K": successes,
            "proportion": successes / target,
            "clopper_pearson_95": clopper_pearson(successes, target),
            "estimand": "Pr(A5 safe and B5 unsafe) under the fixed v0.3.3 runtime design",
            "decision_criterion": None,
        })
    deltas = [row["normalized_p95_difference_b_minus_a"] for row in rows if row["normalized_p95_difference_b_minus_a"] is not None]
    latency: dict[str, Any] = {
        "complete_pairs": len(deltas),
        "values": [row["normalized_p95_difference_b_minus_a"] for row in rows],
        "median": median(deltas) if deltas else None,
    }
    if complete and len(deltas) == target:
        latency["paired_percentile_bootstrap_95"] = bootstrap_median(
            deltas,
            selected["confirmation"]["bootstrap_seed"],
            selected["confirmation"]["bootstrap_resamples"],
        )
    summary = {
        "protocol_version": selected["protocol_version"],
        "candidate_id": selected["selected_candidate"]["id"],
        "confirmation_status": state["status"],
        "primary": primary,
        "paired_latency_contrast": latency,
        "attempt_count": len(state["attempt_history"]),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "summary.json", summary)
    write_csv(args.output_dir / "replicate-level.csv", rows)
    (args.output_dir / "results.tex").write_text(
        "\\newcommand{\\ConfirmationN}{" + str(primary.get("N", "NA")) + "}\n"
        "\\newcommand{\\ConfirmationK}{" + str(primary.get("K", "NA")) + "}\n"
        "\\newcommand{\\ConfirmationProportion}{" + str(primary.get("proportion", "NA")) + "}\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(primary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
