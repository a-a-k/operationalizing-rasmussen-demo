from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe1/scripts"))
from analyze_lean import clopper_pearson  # noqa: E402
from experimentlib import canonical_json, sha256_file, write_json  # noqa: E402
from verify_runtime import verify_actions, verify_runner, verify_structure, verify_upstream  # noqa: E402

VERSION = "followup-0.1.1"
DESIGN = "probe3/design-v0.1.1.json"
RUNTIME = "probe3/runtime-v0.1.1.json"


def project_name(run_id: str, block_id: str, point_id: str) -> str:
    name = f"followup-{run_id}-{block_id}-{point_id}".replace("_", "-").lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name):
        raise ValueError("invalid Compose project name")
    return name


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def balance(q: Mapping[str, float], g: list[str], h: list[str]) -> float:
    ng, nh = len(g), len(h)
    return math.sqrt(ng * nh / (ng + nh)) * (
        sum(math.log(q[k]) for k in g) / ng - sum(math.log(q[k]) for k in h) / nh
    )


def features(arm: Mapping[str, Any], q: Mapping[str, float]) -> dict[str, float]:
    ref, g, h = arm["reference"], arm["group_g"], arm["group_h"]
    logs = {k: math.log(q[k] / ref[k]) for k in q}
    mean = sum(logs.values()) / len(logs)
    return {
        "checkout_quota": q["checkout"],
        "group_sum": sum(q[k] for k in g),
        "minimum_group_quota": min(q[k] for k in g),
        "reduced_count": sum(q[k] < ref[k] - 1e-12 for k in g),
        "recipient_quota": sum(q[k] for k in h),
        "R_group": balance(ref, g, h) - balance(q, g, h),
        "E": math.sqrt(sum((q[k] - ref[k]) ** 2 for k in q)),
        "d_A": math.sqrt(sum((logs[k] - mean) ** 2 for k in q)),
    }


def rank(salt: str, items: list[str]) -> list[str]:
    return sorted(items, key=lambda value: (hashlib.sha256(f"{salt}:{value}".encode()).digest(), value))


def matrix(design: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for arm_id, arm in design["arms"].items():
        ids = [f"{arm_id}-{i:03d}" for i in range(1, arm["blocks"] + 1)]
        points = list(arm["points"])
        ranked_ids = rank(f'{design["randomization_salt"]}:{arm_id}:blocks', ids)
        for block_id in ids:
            index = ranked_ids.index(block_id)
            cycle, offset = divmod(index, len(points))
            base = rank(f'{design["randomization_salt"]}:{arm_id}:cycle:{cycle}', points)
            order = base[offset:] + base[:offset]
            rows.append({"arm": arm_id, "block_id": block_id, "order": order})
    return rows


def validate(design: Mapping[str, Any], runtime: Mapping[str, Any]) -> None:
    if design["study_version"] != VERSION or runtime["study_version"] != VERSION:
        raise ValueError("study version mismatch")
    if set(design["arms"]) != {"ab", "context"}:
        raise ValueError("unexpected study arms")
    if (design["arms"]["ab"]["blocks"], design["arms"]["context"]["blocks"]) != (16, 12):
        raise ValueError("follow-up must contain 16 A/B and 12 context blocks")
    if len(design["arms"]["ab"]["points"]) != 2 or len(design["arms"]["context"]["points"]) != 6:
        raise ValueError("unexpected point counts")
    for arm in design["arms"].values():
        if set(arm["group_g"]) & set(arm["group_h"]) or set(arm["group_g"] + arm["group_h"]) != set(arm["reference"]):
            raise ValueError("groups must partition the controlled allocation")
        for q in [arm["reference"], *arm["points"].values()]:
            if set(q) != set(arm["reference"]) or min(q.values()) < 0.05 or abs(sum(q.values()) - 1) > 1e-12:
                raise ValueError("invalid positive closed CPU-limit allocation")
            if any(abs(v * 100 - round(v * 100)) > 1e-9 for v in q.values()):
                raise ValueError("quota is outside the 0.01 CPU grid")
        for comparison in arm["comparisons"]:
            a = features(arm, arm["points"][comparison["left"]])
            b = features(arm, arm["points"][comparison["right"]])
            if any(abs(a[k] - b[k]) > 1e-12 for k in comparison["matched_features"]):
                raise ValueError(f'matched features differ: {comparison["id"]}')
        required = math.ceil(1.25 * arm["rate"] * 2 * arm["http_timeout_seconds"])
        if runtime["workload"]["pre_allocated_vus"] < required:
            raise ValueError("VU capacity does not cover two timeouts plus 25% allowance")
    w = runtime["workload"]
    if w["pre_allocated_vus"] != 800 or w["max_vus"] != 800 or w["minimum_started_fraction"] != 0.99:
        raise ValueError("unexpected static capacity or generator gate")
    if w["graceful_stop_seconds"] != 30 or w["time_unit"] != "1s":
        raise ValueError("unexpected executor timing")
    if design["analysis"]["binary_success_criterion"] is not None:
        raise ValueError("this descriptive study has no binary success threshold")
    for row in matrix(design):
        for point_id in row["order"]:
            project_name("123", row["block_id"], point_id)
    for arm_id, arm in design["arms"].items():
        rows = [r for r in matrix(design) if r["arm"] == arm_id]
        for position in range(len(arm["points"])):
            counts = Counter(r["order"][position] for r in rows)
            if set(counts.values()) != {arm["blocks"] // len(arm["points"])}:
                raise ValueError("condition position is not exactly balanced")


def generator_valid(phase: Mapping[str, Any], minimum: float = 0.99) -> bool:
    return phase["started_iterations"] >= minimum * phase["scheduled_iterations"]


def proportion(k: int, n: int) -> dict[str, Any]:
    return {"K": k, "N": n, "proportion": k / n if n else None,
            "clopper_pearson_95": clopper_pearson(k, n) if n else None}


def verify(repo: Path, upstream: Path | None = None, check_runner: bool = False) -> dict[str, Any]:
    design, runtime = load(repo / DESIGN), load(repo / RUNTIME)
    validate(design, runtime)
    parent_path = repo / runtime["parent_runtime"]
    if sha256_file(parent_path) != runtime["parent_runtime_sha256"]:
        raise ValueError("parent runtime hash mismatch")
    for path, key in [("probe1/compose.lock.yaml", "compose_override_sha256"), ("probe1/otel.env", "environment_file_sha256")]:
        if sha256_file(repo / path) != runtime[key]:
            raise ValueError(f"runtime input mismatch: {path}")
    parent = load(parent_path)
    errors: list[str] = []
    verify_structure(parent, errors)
    verify_actions(repo, parent, errors)
    if upstream:
        verify_upstream(repo, upstream, parent, errors, compose=True)
    if check_runner:
        verify_runner(parent, errors)
    if errors:
        raise ValueError("; ".join(errors))
    return {"valid": True, "study_version": VERSION, "repository_commit": os.getenv("GITHUB_SHA"),
            "design_sha256": sha256_file(repo / DESIGN), "runtime_sha256": sha256_file(repo / RUNTIME),
            "blocks": 28, "point_trials": 104,
            "feature_table": {key: {p: features(arm, q) for p, q in arm["points"].items()} for key, arm in design["arms"].items()}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["verify", "matrix"])
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--upstream-dir", type=Path)
    parser.add_argument("--check-runner", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = verify(args.repo.resolve(), args.upstream_dir.resolve() if args.upstream_dir else None, args.check_runner)
    if args.report:
        write_json(args.report, report)
    print(json.dumps({"include": matrix(load(args.repo / DESIGN))} if args.command == "matrix" else report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
