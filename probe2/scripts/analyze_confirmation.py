from __future__ import annotations

import argparse
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from common import CONDITIONS, load_json, write_json
from confirmation_common import (
    SINGLES, STUDY_PROTOCOL_VERSION, confirmation_matrix, has_pattern,
    load_confirmation_design, valid_block,
)


def binomial_cdf(k: int, n: int, probability: float) -> float:
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return sum(
        math.comb(n, index) * probability**index * (1.0 - probability) ** (n - index)
        for index in range(k + 1)
    )


def binomial_upper_tail(k: int, n: int, probability: float) -> float:
    return 1.0 - binomial_cdf(k - 1, n, probability)


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> list[float | None]:
    if n == 0:
        return [None, None]
    if not 0 <= k <= n:
        raise ValueError("binomial count must satisfy 0 <= k <= n")
    if k == 0:
        lower = 0.0
    else:
        lo, hi = 0.0, 1.0
        for _ in range(100):
            mid = (lo + hi) / 2.0
            if binomial_upper_tail(k, n, mid) < alpha / 2.0:
                lo = mid
            else:
                hi = mid
        lower = (lo + hi) / 2.0
    if k == n:
        upper = 1.0
    else:
        lo, hi = 0.0, 1.0
        for _ in range(100):
            mid = (lo + hi) / 2.0
            if binomial_cdf(k, n, mid) > alpha / 2.0:
                lo = mid
            else:
                hi = mid
        upper = (lo + hi) / 2.0
    return [lower, upper]


def binomial_summary(k: int, n: int) -> dict[str, Any]:
    return {
        "successes": k,
        "trials": n,
        "proportion": k / n if n else None,
        "clopper_pearson_95": clopper_pearson(k, n),
    }


def collect(root: Path) -> dict[str, dict[str, Any]]:
    results = {}
    for path in sorted(root.rglob("confirmation-block-result.json")):
        result = load_json(path)
        identifier = result.get("block_id")
        if not isinstance(identifier, str) or identifier in results:
            raise ValueError(f"duplicate or invalid confirmation block: {path}")
        results[identifier] = result
    return results


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def analyze(
    design: Mapping[str, Any],
    results: Mapping[str, Mapping[str, Any]],
    repository_commit: str,
) -> dict[str, Any]:
    expected_rows = confirmation_matrix(design)
    expected = {row["block_id"] for row in expected_rows}
    received = set(results)
    complete_run = received == expected
    valid_ids = [identifier for identifier in sorted(expected & received) if valid_block(results[identifier])]
    pattern_ids = [identifier for identifier in valid_ids if has_pattern(results[identifier])]
    primary = binomial_summary(len(pattern_ids), len(valid_ids))
    sensitivity = binomial_summary(len(pattern_ids), len(expected))

    invalid_reasons: Counter[str] = Counter()
    blocks = []
    condition_values = {name: {"valid": 0, "safe": 0, "p95_ms": [], "error_rate": []} for name in CONDITIONS}
    latency_contrasts = []
    expected_by_id = {row["block_id"]: row for row in expected_rows}
    for identifier in sorted(expected & received):
        result = results[identifier]
        expected_row = expected_by_id[identifier]
        if result.get("block_number") != expected_row["block_number"]:
            raise ValueError(f"block number differs from frozen matrix: {identifier}")
        if result.get("order_id") != expected_row["order_id"]:
            raise ValueError(f"block order differs from frozen matrix: {identifier}")
        if result.get("candidate_id") != design["selected_candidate"]["candidate_id"]:
            raise ValueError(f"block candidate differs from frozen design: {identifier}")
        if result.get("provenance", {}).get("repository_commit") != repository_commit:
            raise ValueError(f"block repository commit mismatch: {identifier}")
        for reason in result.get("reason_codes", []):
            invalid_reasons[str(reason)] += 1
        point_summary = {}
        for name in CONDITIONS:
            point = result.get("points", {}).get(name, {})
            test = point.get("test") or {}
            if point.get("valid") is True:
                condition_values[name]["valid"] += 1
                condition_values[name]["safe"] += int(test.get("safe") is True)
                if test.get("p95_ms") is not None:
                    condition_values[name]["p95_ms"].append(float(test["p95_ms"]))
                if test.get("error_rate") is not None:
                    condition_values[name]["error_rate"].append(float(test["error_rate"]))
            for reason in point.get("reason_codes", []):
                invalid_reasons[str(reason)] += 1
            point_summary[name] = {
                "valid": point.get("valid") is True,
                "safe": test.get("safe"),
                "p95_ms": test.get("p95_ms"),
                "error_rate": test.get("error_rate"),
                "reason_codes": point.get("reason_codes", []),
            }
        if valid_block(result):
            p95_values = [result["points"][name]["test"].get("p95_ms") for name in (*SINGLES, "joint")]
            if all(value is not None for value in p95_values):
                joint_p95 = float(p95_values[-1])
                largest_single = max(float(value) for value in p95_values[:-1])
                latency_contrasts.append(joint_p95 - largest_single)
        blocks.append({
            "block_id": identifier,
            "order_id": result.get("order_id"),
            "valid": valid_block(result),
            "pattern": has_pattern(result),
            "points": point_summary,
        })

    conditions = {}
    for name, values in condition_values.items():
        conditions[name] = {
            "valid_points": values["valid"],
            "safe_points": values["safe"],
            "median_p95_ms": _median(values["p95_ms"]),
            "median_error_rate": _median(values["error_rate"]),
            "p95_ms_values": values["p95_ms"],
            "error_rate_values": values["error_rate"],
        }

    return {
        "schema_version": 1,
        "study_protocol_version": STUDY_PROTOCOL_VERSION,
        "status": "complete" if complete_run else "incomplete",
        "repository_commit": repository_commit,
        "expected_blocks": len(expected),
        "received_blocks": len(received),
        "missing_blocks": sorted(expected - received),
        "unexpected_blocks": sorted(received - expected),
        "valid_blocks": len(valid_ids),
        "invalid_blocks": len(expected) - len(valid_ids),
        "invalid_reason_counts": dict(sorted(invalid_reasons.items())),
        "pattern_block_ids": pattern_ids,
        "primary_valid_block_estimand": primary,
        "conservative_all_attempted_sensitivity": sensitivity,
        "paired_latency_contrast_ms": {
            "definition": "joint p95 minus maximum single-condition p95 within each valid block",
            "median": _median(latency_contrasts),
            "values": latency_contrasts,
        },
        "conditions": conditions,
        "blocks": blocks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--design", type=Path, default=Path("probe2/design.json"))
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--repository-commit", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    design = load_json(args.design)
    summary = analyze(design, collect(args.results_root), args.repository_commit)
    write_json(args.output_dir / "confirmation-summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
