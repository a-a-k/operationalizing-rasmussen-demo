from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from common import CONDITIONS, load_json


STUDY_PROTOCOL_VERSION = "experiment2-confirmation-0.2"
SINGLES = ("checkout_only", "payment_only", "shipping_only")


def load_confirmation_design(repo: Path) -> dict[str, Any]:
    design = load_json(repo / "probe2/design.json")
    validate_confirmation_design(design)
    return design


def block_id(number: int) -> str:
    if not 1 <= number <= 32:
        raise ValueError("confirmation block number must be in 1..32")
    return f"c{number:03d}"


def confirmation_matrix(design: Mapping[str, Any]) -> list[dict[str, Any]]:
    validate_confirmation_design(design)
    rows = []
    for number in range(1, int(design["attempted_blocks"]) + 1):
        order_id = f"o{((number - 1) % 4) + 1}"
        rows.append({"block_number": number, "block_id": block_id(number), "order_id": order_id})
    return rows


def validate_confirmation_design(design: Mapping[str, Any]) -> None:
    if design.get("study_protocol_version") != STUDY_PROTOCOL_VERSION:
        raise ValueError("confirmation study protocol version mismatch")
    if design.get("measurement_protocol_version") != "experiment2-0.1":
        raise ValueError("unexpected measurement protocol version")
    candidate = design.get("selected_candidate", {})
    if candidate != {"candidate_id": "r40-s019", "rate": 40, "critical_quota": 0.19}:
        raise ValueError("unexpected selected candidate")
    if design.get("attempted_blocks") != 32:
        raise ValueError("confirmation must contain exactly 32 attempted blocks")
    orders = design.get("condition_orders", {})
    if set(orders) != {"o1", "o2", "o3", "o4"}:
        raise ValueError("confirmation must define four orders")
    for order in orders.values():
        if len(order) != len(CONDITIONS) or set(order) != set(CONDITIONS):
            raise ValueError("each confirmation order must contain every condition exactly once")
    analysis = design.get("analysis", {})
    if analysis.get("confidence_level") != 0.95:
        raise ValueError("unexpected confidence level")
    expected_analysis_keys = {
        "primary_estimand", "confidence_level", "invalid_block_sensitivity",
    }
    if set(analysis) != expected_analysis_keys:
        raise ValueError("unexpected confirmation analysis fields")


def valid_block(result: Mapping[str, Any]) -> bool:
    return (
        result.get("study_protocol_version") == STUDY_PROTOCOL_VERSION
        and result.get("complete") is True
        and result.get("valid") is True
        and set(result.get("points", {})) == set(CONDITIONS)
    )


def has_pattern(result: Mapping[str, Any]) -> bool:
    if not valid_block(result):
        return False
    points = result["points"]
    return all(points[name]["test"]["safe"] is True for name in SINGLES) and points["joint"]["test"]["safe"] is False
