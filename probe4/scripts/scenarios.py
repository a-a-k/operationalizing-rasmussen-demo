from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe3/scripts"))
import run_block as engine
from study import features, load, sha256_file, verify as verify_parent, write_json

VERSION = "threshold-scenarios-0.1.1"
DESIGN = "probe4/design-v0.1.1.json"
RUNTIME = "probe4/runtime-v0.1.1.json"
OVERLAY = "probe4/memory-v0.1.1.yaml"
BASE_COMPOSE = engine.compose_prefix


def matrix(design: dict) -> list[dict]:
    rows = []
    for rate in design["rates"]:
        for panel, points in design["panels"].items():
            for repetition in range(1, design["repetitions"] + 1):
                bid = f"r{rate}-{panel}-{repetition:03d}"
                salt = f'{design["randomization_salt"]}:{bid}'
                order = sorted(points, key=lambda p: (hashlib.sha256(f"{salt}:{p}".encode()).digest(), p))
                rows.append({"block_id": bid, "panel": panel, "rate": rate,
                             "repetition": repetition, "order": order})
    return rows


def arm(design: dict, row: dict) -> dict:
    return {**design, "rate": row["rate"], "points": design["panels"][row["panel"]]}


def smoke_spec(design: dict) -> tuple[dict, dict]:
    row = {"block_id": "smoke", "panel": "joint", "rate": max(design["rates"]),
           "repetition": 0, "order": ["reference"]}
    return row, arm(design, row)


def smoke_valid(point: dict) -> bool:
    return (point["valid"] and point["test"]["safe"]
            and not point.get("post_intervention_failures")
            and not any(e["post_intervention"] for e in point.get("diagnostics", {}).get("failure_events", []))
            and point.get("diagnostics", {}).get("generator_sample_intervals", 0) > 0)


def compose_prefix(repo: Path, upstream: Path, project: str) -> list[str]:
    return [*BASE_COMPOSE(repo, upstream, project), "-f", str(repo / OVERLAY)]


def validate(design: dict, runtime: dict) -> None:
    if design["study_version"] != VERSION or runtime["study_version"] != VERSION:
        raise ValueError("scenario version mismatch")
    if design["rates"] != [40, 64] or design["repetitions"] != 5:
        raise ValueError("unexpected fixed loads or repeat count")
    if set(design["panels"]) != {"joint", "selective"} or any(len(p) != 6 for p in design["panels"].values()):
        raise ValueError("expected two six-point panels")
    g, h = design["group_g"], design["group_h"]
    if g != ["checkout", "payment", "shipping"] or h != ["ad"]:
        raise ValueError("unexpected fixed groups")
    names = [name for points in design["panels"].values() for name in points]
    if len(set(names)) != 12:
        raise ValueError("duplicate point names")
    for q in [design["reference"], *(q for pp in design["panels"].values() for q in pp.values())]:
        if set(q) != set(g + h) or min(q.values()) < 0.05 or abs(sum(q.values()) - 1) > 1e-12:
            raise ValueError("invalid positive closed allocation")
        if any(abs(v * 100 - round(v * 100)) > 1e-9 for v in q.values()):
            raise ValueError("quotas must lie on the 0.01 CPU grid")
    work = runtime["workload"]
    if work["pre_allocated_vus"] != 800 or work["max_vus"] != 800 or work["minimum_started_fraction"] != 0.99:
        raise ValueError("unexpected generator capacity or gate")
    if 800 < math.ceil(1.25 * max(design["rates"]) * 2 * design["http_timeout_seconds"]):
        raise ValueError("insufficient generator capacity")
    if runtime["memory_override"]["checkout_memory_bytes"] != 256 * 1024 * 1024:
        raise ValueError("unexpected memory reserve")
    if runtime["memory_override"]["checkout_gomemlimit"] != "192MiB":
        raise ValueError("unexpected Go memory limit")
    if runtime["memory_override"]["astronomy_db_memory_bytes"] != 1024 * 1024 * 1024:
        raise ValueError("unexpected PostgreSQL memory reserve")
    if design["analysis"]["binary_success_criterion"] is not None or design["analysis"]["pool_rates"]:
        raise ValueError("no binary scientific criterion or pooled-load analysis")


def verify(repo: Path = ROOT, upstream: Path | None = None, check_runner: bool = False) -> dict:
    design, runtime = load(repo / DESIGN), load(repo / RUNTIME)
    validate(design, runtime)
    if sha256_file(repo / runtime["parent_runtime"]) != runtime["parent_runtime_sha256"]:
        raise ValueError("parent runtime checksum differs")
    parent_report = verify_parent(repo, upstream, check_runner)
    report = {"valid": True, "study_version": VERSION, "blocks": len(matrix(design)),
              "point_trials": sum(len(r["order"]) for r in matrix(design)),
              "design_sha256": sha256_file(repo / DESIGN), "runtime_sha256": sha256_file(repo / RUNTIME),
              "overlay_sha256": sha256_file(repo / OVERLAY), "parent_verification": parent_report}
    if upstream:
        rendered = json.loads(engine.run([*compose_prefix(repo, upstream, "scenarios-render"),
                                          "config", "--no-path-resolution", "--format", "json"]).stdout)
        checkout = rendered["services"]["checkout"]
        if int(checkout["deploy"]["resources"]["limits"]["memory"]) != runtime["memory_override"]["checkout_memory_bytes"]:
            raise ValueError("rendered checkout memory differs")
        if checkout["environment"]["GOMEMLIMIT"] != runtime["memory_override"]["checkout_gomemlimit"]:
            raise ValueError("rendered GOMEMLIMIT differs")
        database = rendered["services"]["astronomy-db"]
        if int(database["deploy"]["resources"]["limits"]["memory"]) != runtime["memory_override"]["astronomy_db_memory_bytes"]:
            raise ValueError("rendered PostgreSQL memory differs")
        report["rendered_compose_sha256"] = hashlib.sha256(
            json.dumps(rendered, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return report


@contextlib.contextmanager
def measurement_engine():
    # Reuse the unmodified measurement and validity path with this series' provenance and Compose overlay.
    with contextlib.ExitStack() as stack:
        for key, value in {"VERSION": VERSION, "DESIGN": DESIGN, "RUNTIME": RUNTIME,
                           "compose_prefix": compose_prefix}.items():
            stack.enter_context(patch.object(engine, key, value))
        yield engine


def execute(upstream: Path, block_id: str, output: Path, smoke: bool = False) -> int:
    verification = verify(ROOT, upstream, check_runner=True)
    design, runtime = load(ROOT / DESIGN), load(ROOT / RUNTIME)
    inherited = load(ROOT / runtime["parent_runtime"])
    inherited["workload"].update(runtime["workload"])
    parent = load(ROOT / inherited["parent_runtime"])
    output.mkdir(parents=True, exist_ok=False)
    images = sorted({*parent["images"].values(), parent["workload"]["k6_image"]})
    for image in images:
        engine.run(["docker", "pull", image])
    write_json(output / "image-inspect.json", json.loads(engine.run(["docker", "image", "inspect", *images]).stdout))
    write_json(output / "rendered-compose.json", json.loads(engine.run([
        *compose_prefix(ROOT, upstream, "scenarios-render"), "config", "--no-path-resolution", "--format", "json"]).stdout))
    write_json(output / "runner.json", {"runner_image": os.getenv("ImageOS"),
               "runner_image_version": os.getenv("ImageVersion"), "cpu_count": os.cpu_count(),
               "verification": verification, "repository_commit": os.environ["GITHUB_SHA"]})
    if smoke:
        row, spec = smoke_spec(design)
    else:
        row = next(r for r in matrix(design) if r["block_id"] == block_id)
        spec = arm(design, row)
    write_json(output / "order.json", row)
    points = {}
    with measurement_engine() as runner:
        for point_id in row["order"]:
            points[point_id] = runner.point(ROOT, upstream, parent, inherited, spec, row["panel"],
                                            row["block_id"], point_id, output / "points" / point_id)
    block = {"study_version": VERSION, **row, "points": points,
             "valid": all(p["valid"] for p in points.values()),
             "repository_commit": os.environ["GITHUB_SHA"], "workflow_run_id": os.environ["GITHUB_RUN_ID"],
             "design_sha256": verification["design_sha256"], "runtime_sha256": verification["runtime_sha256"],
             "overlay_sha256": verification["overlay_sha256"]}
    write_json(output / "block-result.json", block)
    if smoke:
        p = points["reference"]
        return 0 if smoke_valid(p) else 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["verify", "matrix", "run"])
    parser.add_argument("--upstream-dir", type=Path)
    parser.add_argument("--check-runner", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--block-id")
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.command == "run":
        if not args.upstream_dir or not args.artifact_dir or not args.block_id:
            parser.error("run requires upstream-dir, block-id and artifact-dir")
        return execute(args.upstream_dir.resolve(), args.block_id, args.artifact_dir.resolve(), args.smoke)
    report = verify(ROOT, args.upstream_dir.resolve() if args.upstream_dir else None, args.check_runner)
    if args.report:
        write_json(args.report, report)
    print(json.dumps({"include": matrix(load(ROOT / DESIGN))} if args.command == "matrix" else report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
