from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping


PROTOCOL_VERSION = "experiment2-0.1"
CONTROLLED_SERVICES = ("checkout", "payment", "shipping", "ad")
CRITICAL_SERVICES = ("checkout", "payment", "shipping")
CONDITIONS = ("checkout_only", "payment_only", "shipping_only", "joint")


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def group_balance(quotas: Mapping[str, float]) -> float:
    values = [float(quotas[name]) for name in CRITICAL_SERVICES]
    recipient = float(quotas["ad"])
    if min(*values, recipient) <= 0:
        raise ValueError("balance requires positive quotas")
    geometric_mean = math.prod(values) ** (1.0 / len(values))
    return math.sqrt(3.0 / 4.0) * math.log(geometric_mean / recipient)


def euclidean(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    return math.sqrt(sum((float(left[key]) - float(right[key])) ** 2 for key in CONTROLLED_SERVICES))


def candidate_id(rate: int, critical_quota: float) -> str:
    return f"r{rate}-s{round(critical_quota * 100):03d}"


def condition_quotas(condition: str, critical_quota: float) -> dict[str, float]:
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition: {condition}")
    if critical_quota != 0.19:
        raise ValueError("critical quota differs from the fixed follow-up design")
    quotas = {"checkout": 0.30, "payment": 0.30, "shipping": 0.30, "ad": 0.10}
    if condition == "joint":
        for service in CRITICAL_SERVICES:
            quotas[service] = critical_quota
        quotas["ad"] = 1.0 - 3.0 * critical_quota
    else:
        service = condition.removesuffix("_only")
        quotas[service] = critical_quota
        quotas["ad"] = 0.40 - critical_quota
    quotas = {key: round(value, 2) for key, value in quotas.items()}
    if abs(sum(quotas.values()) - 1.0) > 1e-12 or min(quotas.values()) <= 0:
        raise ValueError("generated quotas are not a positive closed allocation")
    return quotas


def point_spec(rate: int, critical_quota: float, condition: str, replication_id: str) -> dict[str, Any]:
    reference = {"checkout": 0.30, "payment": 0.30, "shipping": 0.30, "ad": 0.10}
    test = condition_quotas(condition, critical_quota)
    reference_balance = group_balance(reference)
    test_balance = group_balance(test)
    value: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "candidate_id": candidate_id(rate, critical_quota),
        "condition": condition,
        "replication_id": replication_id,
        "rate": rate,
        "total_cpu": 1.0,
        "baseline_quotas": reference,
        "test_quotas": test,
        "geometry": {
            "reference_balance": reference_balance,
            "test_balance": test_balance,
            "risk_directed_change": reference_balance - test_balance,
            "euclidean": euclidean(reference, test),
        },
    }
    value["spec_sha256"] = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return value
