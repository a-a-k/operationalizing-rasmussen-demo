from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
from typing import Any

from experimentlib import (
    PROTOCOL_VERSION,
    SERVICES,
    canonical_json,
    euclidean,
    ilr,
    normalized_geometry,
    point_composition,
    quotas,
    sha256_file,
    write_json,
)


DEFAULT_PLAN = Path("probe1/design.json")
DEFAULT_RUNTIME = Path("probe1/runtime.json")
QUOTA_QUANTUM = 0.01


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def candidates_by_id(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    candidates = plan["calibration"]["candidates"]
    result = {candidate["id"]: candidate for candidate in candidates}
    if len(result) != len(candidates):
        raise ValueError("candidate IDs are not unique")
    return result


def confirmation_replication_ids(confirmation: dict[str, Any]) -> list[str]:
    prefix = confirmation.get("replication_id_prefix")
    width = confirmation.get("replication_id_width")
    count = confirmation.get("replication_count")
    if prefix != "c" or width != 3 or count != 256:
        raise ValueError("confirmation range must be exactly c001..c256")
    return [f"{prefix}{index:0{width}d}" for index in range(1, count + 1)]


def quantized_point(
    path: str,
    ideal: dict[str, float],
    total_cpu: float,
    roles: dict[str, str],
) -> tuple[dict[str, float], dict[str, float], float]:
    total_units = int(round(total_cpu / QUOTA_QUANTUM))
    raw_units = {service: ideal[service] * total_units for service in SERVICES}
    options = {
        service: sorted({math.floor(raw_units[service]), math.ceil(raw_units[service])})
        for service in SERVICES
    }
    baseline = {roles["critical"]: 0.4, roles["n1"]: 0.3, roles["n2"]: 0.3}
    r0, n0 = ilr(baseline, roles["critical"], roles["n1"], roles["n2"])
    candidates = []
    for units in itertools.product(*(options[service] for service in SERVICES)):
        if sum(units) != total_units:
            continue
        composition = {service: value / total_units for service, value in zip(SERVICES, units)}
        r, n = ilr(composition, roles["critical"], roles["n1"], roles["n2"])
        orthogonal_error = abs((r - r0) if path == "A" else (n - n0))
        squared_error = sum((composition[service] - ideal[service]) ** 2 for service in SERVICES)
        candidates.append(((orthogonal_error, squared_error, units), units, composition))
    if not candidates:
        raise ValueError("no sum-preserving floor/ceil quota quantization exists")
    _, selected_units, composition = min(candidates, key=lambda item: item[0])
    requested = {
        service: round(value * QUOTA_QUANTUM, 2)
        for service, value in zip(SERVICES, selected_units)
    }
    r, n = ilr(composition, roles["critical"], roles["n1"], roles["n2"])
    orthogonal_error = abs((r - r0) if path == "A" else (n - n0))
    return requested, composition, orthogonal_error


def validate_plan(plan: dict[str, Any]) -> None:
    if plan.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("plan protocol version mismatch")
    roles = plan["roles"]
    if roles != {"critical": "checkout", "n1": "payment", "n2": "shipping"}:
        raise ValueError("roles differ from the fixed v0.3.3 orientation")
    baseline = plan["reference_composition"]
    if set(baseline) != set(SERVICES) or abs(sum(baseline.values()) - 1.0) > 1e-12:
        raise ValueError("reference composition is invalid")
    if baseline[roles["critical"]] != 0.4 or baseline[roles["n1"]] != 0.3 or baseline[roles["n2"]] != 0.3:
        raise ValueError("reference composition and roles differ")
    expected_candidates = [
        {
            "id": "q1p00-r32-db1p30-a-shipping",
            "total_cpu": 1.0,
            "rate": 32,
            "delta_b": 1.3,
            "delta_a": 1.4,
        }
    ]
    if plan["calibration"]["candidates"] != expected_candidates:
        raise ValueError("candidate differs from the single fixed v0.3.3 design")
    if plan["calibration"].get("enabled") is not False:
        raise ValueError("v0.3.3 calibration must be disabled")
    candidates_by_id(plan)
    for candidate in plan["calibration"]["candidates"]:
        if candidate["rate"] != 32 or candidate["total_cpu"] != 1.0:
            raise ValueError(f"candidate outside bounded grid: {candidate['id']}")
        ideal_a = point_composition("A", 5, candidate["delta_a"], roles)
        ideal_b = point_composition("B", 5, candidate["delta_b"], roles)
        a_quotas, a, a_error = quantized_point("A", ideal_a, candidate["total_cpu"], roles)
        b_quotas, b, b_error = quantized_point("B", ideal_b, candidate["total_cpu"], roles)
        a_geometry, b_geometry = normalized_geometry(a, roles), normalized_geometry(b, roles)
        if euclidean(a, baseline) - euclidean(b, baseline) < 0.01 - 1e-12:
            raise ValueError(f"E contrast is too small: {candidate['id']}")
        if a_geometry["d_A"] - b_geometry["d_A"] < 0.05 - 1e-12:
            raise ValueError(f"Aitchison contrast is too small: {candidate['id']}")
        if min(*a_quotas.values(), *b_quotas.values()) < 0.05:
            raise ValueError(f"quota below 0.05 CPU: {candidate['id']}")
        if a_error > 0.01 + 1e-12 or b_error > 0.01 + 1e-12:
            raise ValueError(f"orthogonal coordinate quantization error is too large: {candidate['id']}")
        if abs(sum(a_quotas.values()) - candidate["total_cpu"]) > 1e-12 or abs(sum(b_quotas.values()) - candidate["total_cpu"]) > 1e-12:
            raise ValueError(f"quantized quota sum differs: {candidate['id']}")
    confirmation = plan["confirmation"]
    ids = confirmation_replication_ids(confirmation)
    if ids[0] != "c001" or ids[-1] != "c256" or len(set(ids)) != 256:
        raise ValueError("confirmation replication range differs")
    if confirmation.get("decision_criterion") is not None:
        raise ValueError("v0.3.3 must estimate the reversal proportion without a binary criterion")
    if confirmation["max_infrastructure_attempts"] != 3:
        raise ValueError("confirmation infrastructure-attempt bound differs")


def candidate_spec(plan: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    validate_plan(plan)
    candidate = copy.deepcopy(candidates_by_id(plan)[candidate_id])
    roles = copy.deepcopy(plan["roles"])
    baseline = copy.deepcopy(plan["reference_composition"])
    points: dict[str, Any] = {}
    for point_id, path, delta in (("A5", "A", candidate["delta_a"]), ("B5", "B", candidate["delta_b"])):
        ideal_composition = point_composition(path, 5, delta, roles)
        requested_quotas, composition, orthogonal_error = quantized_point(
            path, ideal_composition, candidate["total_cpu"], roles
        )
        r, n = ilr(composition, roles["critical"], roles["n1"], roles["n2"])
        points[point_id] = {
            "path": path,
            "delta": delta,
            "ideal_composition": ideal_composition,
            "composition": composition,
            "requested_quotas": requested_quotas,
            "geometry": normalized_geometry(composition, roles),
            "orthogonal_coordinate_error": orthogonal_error,
            "quota_quantum": QUOTA_QUANTUM,
            "constraint": {
                "coordinate": "r" if path == "A" else "n",
                "expected": r if path == "A" else n,
                "tolerance": 0.001,
            },
        }
    return {
        **candidate,
        "duration_seconds": plan["duration_seconds"],
        "roles": roles,
        "reference_composition": baseline,
        "reference_quotas": quotas(baseline, candidate["total_cpu"]),
        "points": points,
    }


def point_spec(
    plan: dict[str, Any], candidate_id: str, point_id: str, replication_id: str, attempt_id: int
) -> dict[str, Any]:
    candidate = candidate_spec(plan, candidate_id)
    point = candidate["points"][point_id]
    roles = candidate["roles"]
    spec = {
        "protocol_version": PROTOCOL_VERSION,
        "environment_id": candidate_id,
        "stage_id": "calibration" if replication_id == "calibration" else "confirmation",
        "point_id": point_id,
        "replication_id": replication_id,
        "attempt_id": attempt_id,
        "total_cpu": candidate["total_cpu"],
        "rate": candidate["rate"],
        "duration_seconds": candidate["duration_seconds"],
        "baseline_composition": candidate["reference_composition"],
        "test_composition": point["composition"],
        "baseline_quotas": candidate["reference_quotas"],
        "test_quotas": point["requested_quotas"],
        "geometry": {
            "path": point["path"],
            "critical": roles["critical"],
            "n1": roles["n1"],
            "n2": roles["n2"],
            "constraint": point["constraint"],
            "test": point["geometry"],
        },
    }
    spec["spec_sha256"] = hashlib.sha256(canonical_json(spec).encode("utf-8")).hexdigest()
    return spec


def generator_gate(trial: dict[str, Any]) -> bool:
    return all(
        trial[phase]["started_iterations"] >= 0.99 * trial[phase]["scheduled_iterations"]
        for phase in ("baseline", "test")
    )


def feasible_pair(result: dict[str, Any]) -> bool:
    if result.get("valid") is not True or set(result.get("points", {})) != {"A5", "B5"}:
        return False
    a, b = result["points"]["A5"], result["points"]["B5"]
    return (
        a["validity"]["valid"] is True
        and b["validity"]["valid"] is True
        and a["manipulation"]["valid"] is True
        and b["manipulation"]["valid"] is True
        and a["baseline"]["safe"] is True
        and b["baseline"]["safe"] is True
        and a["test"]["safe"] is True
        and b["test"]["safe"] is False
        and generator_gate(a)
        and generator_gate(b)
    )


def find_pair_results(root: Path) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("pair-result.json")):
        result = load_json(path)
        candidate_id = result.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id in results:
            raise ValueError(f"duplicate or invalid calibration result: {path}")
        results[candidate_id] = result
    return results


def select_design(
    plan_path: Path,
    runtime_path: Path,
    artifacts: Path,
    output: Path,
    summary_path: Path,
    repository_commit: str,
) -> dict[str, Any]:
    plan = load_json(plan_path)
    validate_plan(plan)
    results = find_pair_results(artifacts)
    ordered = plan["calibration"]["candidates"]
    expected_ids = [candidate["id"] for candidate in ordered]
    unknown = sorted(set(results) - set(expected_ids))
    if unknown:
        raise ValueError(f"unknown candidate results: {unknown}")
    complete_batch = set(results) == set(expected_ids)
    selected_id = next(
        (candidate["id"] for candidate in ordered if feasible_pair(results.get(candidate["id"], {}))),
        None,
    ) if complete_batch else None
    summary = {
        "protocol_version": PROTOCOL_VERSION,
        "status": "feasible" if selected_id else "calibration-failed",
        "repository_commit": repository_commit,
        "candidate_order": [candidate["id"] for candidate in ordered],
        "complete_batch": complete_batch,
        "missing_candidates": sorted(set(expected_ids) - set(results)),
        "received_candidates": sorted(results),
        "feasible_candidates": [candidate["id"] for candidate in ordered if feasible_pair(results.get(candidate["id"], {}))],
        "selected_candidate_id": selected_id,
        "results": results,
    }
    write_json(summary_path, summary)
    selected = {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "status": summary["status"],
        "repository_commit": repository_commit,
        "plan_sha256": sha256_file(plan_path),
        "runtime_lock_sha256": sha256_file(runtime_path),
        "selection_rule": plan["calibration"]["selection_rule"],
        "selected_candidate": candidate_spec(plan, selected_id) if selected_id else None,
        "confirmation": plan["confirmation"],
    }
    write_json(output, selected)
    return selected


def fixed_design_payload(
    plan_path: Path,
    runtime_path: Path,
    repository_commit: str,
) -> dict[str, Any]:
    plan = load_json(plan_path)
    validate_plan(plan)
    if not isinstance(repository_commit, str) or len(repository_commit) != 40:
        raise ValueError("fixed design requires an exact 40-character repository commit")
    candidate_id = plan["calibration"]["candidates"][0]["id"]
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "status": "fixed",
        "repository_commit": repository_commit,
        "plan_sha256": sha256_file(plan_path),
        "runtime_lock_sha256": sha256_file(runtime_path),
        "selection_rule": plan["calibration"]["selection_rule"],
        "revision_basis": copy.deepcopy(plan["revision_basis"]),
        "selected_candidate": candidate_spec(plan, candidate_id),
        "confirmation": copy.deepcopy(plan["confirmation"]),
    }


def verify_selected(selected: dict[str, Any], plan_path: Path, runtime_path: Path, expected_commit: str) -> None:
    expected = fixed_design_payload(plan_path, runtime_path, expected_commit)
    if selected != expected:
        raise ValueError("selected design differs from the exact fixed v0.3.3 payload")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("matrix")
    spec_parser = subparsers.add_parser("specs")
    spec_parser.add_argument("--candidate-id", required=True)
    spec_parser.add_argument("--replication-id", required=True)
    spec_parser.add_argument("--attempt-id", type=int, required=True)
    spec_parser.add_argument("--output-dir", type=Path, required=True)
    select_parser = subparsers.add_parser("select")
    select_parser.add_argument("--artifacts", type=Path, required=True)
    select_parser.add_argument("--output", type=Path, required=True)
    select_parser.add_argument("--summary", type=Path, required=True)
    select_parser.add_argument("--repository-commit", default=os.getenv("GITHUB_SHA", ""))
    freeze_parser = subparsers.add_parser("freeze")
    freeze_parser.add_argument("--output", type=Path, required=True)
    freeze_parser.add_argument("--repository-commit", default=os.getenv("GITHUB_SHA", ""))
    verify_parser = subparsers.add_parser("verify-selected")
    verify_parser.add_argument("--selected", type=Path, required=True)
    verify_parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args()
    plan = load_json(args.plan)
    validate_plan(plan)
    if args.command == "matrix":
        print(json.dumps({"include": [{"candidate_id": item["id"]} for item in plan["calibration"]["candidates"]]}, separators=(",", ":")))
    elif args.command == "specs":
        args.output_dir.mkdir(parents=True, exist_ok=False)
        for point_id in ("A5", "B5"):
            write_json(
                args.output_dir / f"{point_id}.json",
                point_spec(plan, args.candidate_id, point_id, args.replication_id, args.attempt_id),
            )
    elif args.command == "select":
        selected = select_design(args.plan, args.runtime, args.artifacts, args.output, args.summary, args.repository_commit)
        print(json.dumps({"status": selected["status"], "selected": selected["selected_candidate"]["id"] if selected["selected_candidate"] else None}))
    elif args.command == "freeze":
        selected = fixed_design_payload(args.plan, args.runtime, args.repository_commit)
        write_json(args.output, selected)
        print(json.dumps({"status": selected["status"], "selected": selected["selected_candidate"]["id"]}))
    else:
        verify_selected(load_json(args.selected), args.plan, args.runtime, args.expected_commit)
        print(json.dumps({"ok": True, "selected_sha256": sha256_file(args.selected)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
