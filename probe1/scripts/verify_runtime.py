from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from experimentlib import PROTOCOL_VERSION, canonical_json, sha256_file


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
IMAGE_RE = re.compile(r"@sha256:[0-9a-f]{64}$")
USES_RE = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.MULTILINE)


def load_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("runtime lock root must be an object")
    return value


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def verify_structure(manifest: dict[str, Any], errors: list[str]) -> None:
    required = {
        "schema_version", "protocol_version", "source", "runner", "workload", "compose",
        "system_under_test_containers", "mandatory_healthy_containers",
        "required_running_containers", "primary_observation_artifact_files",
        "diagnostic_log_tail_lines", "images", "github_actions",
    }
    require(set(manifest) == required, "runtime lock has unexpected or missing keys", errors)
    require(manifest.get("schema_version") == 1, "schema_version must be 1", errors)
    require(manifest.get("protocol_version") == PROTOCOL_VERSION, "protocol version mismatch", errors)
    source = manifest.get("source", {})
    require(COMMIT_RE.fullmatch(str(source.get("commit", ""))) is not None, "source commit is not a full SHA", errors)
    for path, digest in source.get("files", {}).items():
        require(isinstance(path, str) and SHA256_RE.fullmatch(str(digest)) is not None, f"invalid source hash: {path}", errors)
    workload = manifest.get("workload", {})
    require(workload.get("pre_allocated_vus") == 320 and workload.get("max_vus") == 320, "VU capacity must be 320/320", errors)
    require(workload.get("time_unit") == "1s", "timeUnit must be 1s", errors)
    require(workload.get("graceful_stop_seconds") == 30, "gracefulStop must be 30 s", errors)
    require(workload.get("health_check_timeout_seconds") == 300, "health timeout must be 300 s", errors)
    require(IMAGE_RE.search(str(workload.get("k6_image", ""))) is not None, "k6 image is not digest-pinned", errors)
    sut = manifest.get("system_under_test_containers", [])
    healthy = manifest.get("mandatory_healthy_containers", [])
    running = manifest.get("required_running_containers", [])
    for name, values in (("SUT", sut), ("healthy", healthy), ("running", running)):
        require(isinstance(values, list) and values == sorted(set(values)), f"{name} list must be sorted and unique", errors)
    require(set(healthy).issubset(sut), "healthy containers are not a SUT subset", errors)
    require(set(sut).issubset(running), "SUT containers are not a running subset", errors)
    require("otel-collector" in running and "otel-collector" not in sut, "collector classification is invalid", errors)
    require(set(manifest.get("images", {})) == set(running), "image keys differ from running containers", errors)
    for service, image in manifest.get("images", {}).items():
        require(IMAGE_RE.search(str(image)) is not None, f"image is not digest-pinned: {service}", errors)
    artifacts = manifest.get("primary_observation_artifact_files", [])
    require(len(artifacts) == 8 and len(set(artifacts)) == 8, "exactly eight primary artifacts are required", errors)
    require(
        {path for path in artifacts if path.endswith("compact-primary.json")}
        == {"k6/baseline/compact-primary.json", "k6/test/compact-primary.json"},
        "compact primary observation artifacts differ",
        errors,
    )
    require(manifest.get("diagnostic_log_tail_lines") == 200, "diagnostic log tail must be 200 lines", errors)
    for action, commit in manifest.get("github_actions", {}).items():
        require("/" in action and COMMIT_RE.fullmatch(str(commit)) is not None, f"Action is not fully pinned: {action}", errors)


def verify_actions(repo: Path, manifest: dict[str, Any], errors: list[str]) -> None:
    expected = manifest["github_actions"]
    found: dict[str, set[str]] = {}
    for path in sorted((repo / ".github" / "workflows").glob("*.yml")):
        for match in USES_RE.finditer(path.read_text(encoding="utf-8")):
            reference = match.group(1).strip("'\"")
            if reference.startswith(("./", "docker://")):
                continue
            if "@" not in reference:
                errors.append(f"Action without ref: {reference}")
                continue
            action, commit = reference.rsplit("@", 1)
            found.setdefault(action, set()).add(commit)
            require(expected.get(action) == commit, f"Action differs from runtime lock: {reference}", errors)
    require(set(found) == set(expected), "workflow Action set differs from runtime lock", errors)


def verify_upstream(repo: Path, upstream: Path, manifest: dict[str, Any], errors: list[str], compose: bool) -> None:
    source = manifest["source"]
    actual_commit = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    require(actual_commit == source["commit"], "upstream commit mismatch", errors)
    for relative, expected in source["files"].items():
        path = upstream / relative
        require(path.is_file() and sha256_file(path) == expected, f"upstream file mismatch: {relative}", errors)
    if not compose:
        return
    command = [
        "docker", "compose", "--project-directory", str(upstream),
        "--env-file", str(upstream / ".env"), "--env-file", str(repo / "probe1" / "otel.env"),
        "-f", str(upstream / "compose.yaml"), "-f", str(repo / "probe1" / "compose.lock.yaml"),
        "config", "--no-path-resolution", "--format", "json",
    ]
    rendered = json.loads(subprocess.check_output(command, text=True))
    services = rendered.get("services", {})
    require(set(services) == set(manifest["required_running_containers"]), "rendered service set mismatch", errors)
    require("load-generator" not in services, "stock load-generator is enabled", errors)
    require(not any("build" in service for service in services.values()), "rendered Compose contains build directives", errors)
    for service, image in manifest["images"].items():
        require(services.get(service, {}).get("image") == image, f"rendered image mismatch: {service}", errors)
    digest = __import__("hashlib").sha256(canonical_json(rendered).encode("utf-8")).hexdigest()
    require(digest == manifest["compose"]["canonical_rendered_sha256"], "rendered Compose hash mismatch", errors)


def verify_runner(manifest: dict[str, Any], errors: list[str]) -> None:
    require(platform.system() == "Linux" and os.getenv("GITHUB_ACTIONS") == "true", "runtime must execute in Linux GitHub Actions", errors)
    require(os.cpu_count() == manifest["runner"]["logical_cpus"], "logical CPU count mismatch", errors)
    with open("/proc/meminfo", encoding="utf-8") as handle:
        memory_kib = next(int(line.split()[1]) for line in handle if line.startswith("MemTotal:"))
    require(memory_kib / (1024 * 1024) >= manifest["runner"]["minimum_memory_gib"], "runner memory below minimum", errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, default=Path("probe1/runtime.json"))
    parser.add_argument("--design", type=Path, default=Path("probe1/design.json"))
    parser.add_argument("--upstream-dir", type=Path)
    parser.add_argument("--skip-compose", action="store_true")
    parser.add_argument("--check-runner", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    manifest_path = args.manifest if args.manifest.is_absolute() else repo / args.manifest
    design_path = args.design if args.design.is_absolute() else repo / args.design
    errors: list[str] = []
    try:
        manifest = load_manifest(manifest_path)
        design = json.loads(design_path.read_text(encoding="utf-8"))
        private_paths = [
            *repo.glob("experiment_protocol_ru_v*.md"),
            *((repo / "protocol").glob("**/*") if (repo / "protocol").exists() else []),
        ]
        require(not any(path.is_file() for path in private_paths), "private prose protocol is present in the public tree", errors)
        verify_structure(manifest, errors)
        require(design.get("protocol_version") == PROTOCOL_VERSION, "design version mismatch", errors)
        verify_actions(repo, manifest, errors)
        if args.upstream_dir:
            verify_upstream(repo, args.upstream_dir.resolve(), manifest, errors, not args.skip_compose)
        elif not args.skip_compose:
            errors.append("--upstream-dir is required unless --skip-compose is used")
        if args.check_runner:
            verify_runner(manifest, errors)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    report = {
        "ok": not errors,
        "errors": errors,
        "runtime_lock_sha256": sha256_file(manifest_path),
        "design_sha256": sha256_file(design_path),
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
