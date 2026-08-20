from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Iterable, Mapping, Sequence


PROTOCOL_VERSION = "0.3.3"
SERVICES = ("checkout", "payment", "shipping")
SCREEN_DELTAS = (0.0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.75, 1.00)
ENDPOINT_DELTAS = tuple(round(i * 0.05, 2) for i in range(1, 21))
ENVIRONMENTS = tuple((q, rate) for q in (1.50, 1.25, 1.00) for rate in (1, 2, 4, 6, 8))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def measurement_seconds(rate: int) -> int:
    return 30 * math.ceil(max(180.0, 300.0 / (0.95 * rate)) / 30.0)


def type7_quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be in [0, 1]")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    h = (len(ordered) - 1) * probability
    lower = math.floor(h)
    upper = math.ceil(h)
    return ordered[lower] + (h - lower) * (ordered[upper] - ordered[lower])


def median(values: Sequence[float]) -> float | None:
    return type7_quantile(values, 0.5)


def classify_slo(p95_ms: float | None, successful_iterations: int, scheduled_iterations: int) -> dict[str, object]:
    if scheduled_iterations <= 0:
        raise ValueError("scheduled_iterations must be positive")
    if not 0 <= successful_iterations <= scheduled_iterations:
        raise ValueError("successful_iterations must be in [0, scheduled_iterations]")
    errors = scheduled_iterations - successful_iterations
    error_rate = errors / scheduled_iterations
    safe = p95_ms is not None and p95_ms <= 500.0 and error_rate < 0.01
    return {"safe": safe, "error_count": errors, "error_rate": error_rate, "p95_ms": p95_ms}


def ilr(composition: Mapping[str, float], critical: str, n1: str, n2: str) -> tuple[float, float]:
    xc, x1, x2 = composition[critical], composition[n1], composition[n2]
    if min(xc, x1, x2) <= 0:
        raise ValueError("composition parts must be positive")
    r = math.sqrt(2.0 / 3.0) * math.log(xc / math.sqrt(x1 * x2))
    n = (1.0 / math.sqrt(2.0)) * math.log(x1 / x2)
    return r, n


def inverse_ilr(r: float, n: float, critical: str, n1: str, n2: str) -> dict[str, float]:
    y = {
        critical: math.sqrt(2.0 / 3.0) * r,
        n1: -r / math.sqrt(6.0) + n / math.sqrt(2.0),
        n2: -r / math.sqrt(6.0) - n / math.sqrt(2.0),
    }
    maximum = max(y.values())
    exponentials = {key: math.exp(value - maximum) for key, value in y.items()}
    total = sum(exponentials.values())
    return {key: exponentials[key] / total for key in (critical, n1, n2)}


def euclidean(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    return math.sqrt(sum((left[key] - right[key]) ** 2 for key in SERVICES))


def point_composition(path: str, step: int, delta: float, roles: Mapping[str, str]) -> dict[str, float]:
    if path not in {"A", "B"} or step not in range(1, 6):
        raise ValueError("path must be A/B and step must be 1..5")
    baseline = {roles["critical"]: 0.40, roles["n1"]: 0.30, roles["n2"]: 0.30}
    r0, n0 = ilr(baseline, roles["critical"], roles["n1"], roles["n2"])
    fraction = step / 5.0
    r = r0 if path == "A" else r0 - fraction * delta
    n = n0 + fraction * delta if path == "A" else n0
    return inverse_ilr(r, n, roles["critical"], roles["n1"], roles["n2"])


def service_screen_composition(service: str, delta: float) -> dict[str, float]:
    others = sorted(set(SERVICES) - {service})
    return inverse_ilr(-delta, 0.0, service, others[0], others[1])


def quotas(composition: Mapping[str, float], total_cpu: float) -> dict[str, float]:
    return {service: total_cpu * composition[service] for service in SERVICES}


def average_ranks(values: Sequence[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(indexed):
        end = start + 1
        while end < len(indexed) and indexed[end][1] == indexed[start][1]:
            end += 1
        rank = ((start + 1) + end) / 2.0
        for position in range(start, end):
            ranks[indexed[position][0]] = rank
        start = end
    return ranks


def spearman(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("Spearman inputs must have equal length >= 2")
    x, y = average_ranks(left), average_ranks(right)
    xmean, ymean = sum(x) / len(x), sum(y) / len(y)
    numerator = sum((a - xmean) * (b - ymean) for a, b in zip(x, y))
    denominator = math.sqrt(sum((a - xmean) ** 2 for a in x) * sum((b - ymean) ** 2 for b in y))
    return numerator / denominator if denominator else 0.0


def theil_sen(xs: Sequence[float], ys: Sequence[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("Theil-Sen inputs must have equal length >= 2")
    slopes = [(ys[j] - ys[i]) / (xs[j] - xs[i]) for i in range(len(xs)) for j in range(i + 1, len(xs)) if xs[j] != xs[i]]
    result = median(slopes)
    if result is None:
        raise ValueError("no distinct x values")
    return result


def normalized_geometry(composition: Mapping[str, float], roles: Mapping[str, str]) -> dict[str, float]:
    baseline = {roles["critical"]: 0.40, roles["n1"]: 0.30, roles["n2"]: 0.30}
    r0, n0 = ilr(baseline, roles["critical"], roles["n1"], roles["n2"])
    r, n = ilr(composition, roles["critical"], roles["n1"], roles["n2"])
    return {
        "E": euclidean(composition, baseline),
        "R": r0 - r,
        "d_A": math.sqrt((r - r0) ** 2 + (n - n0) ** 2),
        "r": r,
        "n": n,
    }


def all_close(left: Iterable[float], right: Iterable[float], tolerance: float = 1e-12) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(left, right))
