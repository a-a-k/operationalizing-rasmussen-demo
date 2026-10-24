"""Validate the updated direct comparator with the genuine PromQL engine."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import urllib.request

from analyze import lines, oracle, save
from observer import extract

JOIN = "attempt_window_count * on (component, deployment) group_left (group) component_group_info"
# Filtering the raw attempt selector keeps first/retry labels until the metadata join.
NUMERATOR = ('sum by (group) (attempt_window_count{kind="retry"} * '
             'on (component, deployment) group_left (group) component_group_info)')
DENOMINATOR = 'sum by (group) (' + JOIN + ')'
EXPRESSION = "(" + NUMERATOR + " / " + DENOMINATOR + ") and on (group) (" + DENOMINATOR + " > 0)"


def fixture(directory):
    inputs = lines(directory / "observer-inputs.jsonl")
    events = lines(directory / "journals/client.jsonl")
    cfg = json.loads((directory / "load-config.json").read_text())
    tests = []
    for index, item in enumerate(inputs):
        snapshot = item["snapshot"]
        counts, missing, detail = extract(snapshot, item["metadata"])
        if missing or str(snapshot["policy_version"]) not in item["metadata"]["policies"]:
            continue
        truth = oracle(events, snapshot, cfg["origin_ms"], cfg["window_seconds"] * 1000)
        series, members = [], {}
        for row in detail:
            labels = ','.join(f'{key}={json.dumps(str(row[key]))}' for key in ("component", "deployment", "kind"))
            series.append({"series": "attempt_window_count{" + labels + "}", "values": str(row["count"])})
            members[row["component"], row["deployment"]] = row["group"]
        for (name, version), group in members.items():
            labels = f'component="{name}",deployment="{version}",group="{group}"'
            series.append({"series": "component_group_info{" + labels + "}", "values": "1"})
        # A retry-zero group still needs an explicit zero-valued series.
        for (name, version), group in members.items():
            for kind in ("first", "retry"):
                if not any(r["component"] == name and r["deployment"] == version and r["kind"] == kind for r in detail):
                    labels = f'component="{name}",deployment="{version}",kind="{kind}"'
                    series.append({"series": "attempt_window_count{" + labels + "}", "values": "0"})
        ratios, violations = [], []
        for group, actual in truth["groups"].items():
            received_limit = item["metadata"]["policies"][str(snapshot["policy_version"])]["limits"][group]
            series.append({"series": f'retry_policy_limit{{group="{group}"}}', "values": str(received_limit)})
            if actual["ratio"] is not None:
                ratios.append({"labels": f'{{group="{group}"}}', "value": actual["ratio"]})
                violations.append({"labels": f'{{group="{group}"}}', "value": int(actual["violation"])})
        tests.append({"name": f"input-{index}-window-{snapshot['window']}", "interval": "1s",
                      "input_series": series, "promql_expr_test": [
                          {"expr": EXPRESSION, "eval_time": "0s", "exp_samples": ratios},
                          {"expr": "(" + EXPRESSION + ") > bool on (group) (retry_policy_limit + 1e-12)",
                           "eval_time": "0s", "exp_samples": violations}]})
    return {"rule_files": [], "evaluation_interval": "1s", "tests": tests}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--promtool", type=Path)
    args = parser.parse_args()
    if args.promtool is None:
        root = Path(__file__).resolve().parents[2]
        spec = json.loads((root / "runtime/prometheus.json").read_text())
        args.output.mkdir(parents=True, exist_ok=True)
        archive = args.output / "prometheus.tar.gz"
        urllib.request.urlretrieve(spec["linux_amd64_url"], archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != spec["tar_sha256"]:
            raise ValueError("Prometheus release checksum mismatch")
        with tarfile.open(archive) as source:
            member = next(m for m in source.getmembers() if m.name.endswith("/promtool"))
            source.extract(member, args.output, filter="data")
        args.promtool = (args.output / member.name).resolve()
        args.promtool.chmod(0o755)
        save(args.output / "engine.json", spec)
    outcomes = []
    for status in sorted(args.inputs.rglob("status.json")):
        if not json.loads(status.read_text())["complete"]:
            continue
        data = fixture(status.parent)
        destination = args.output / (status.parent.name + "-promql.json")
        save(destination, data)
        result = subprocess.run([str(args.promtool), "test", "rules", str(destination)], text=True, capture_output=True)
        (destination.with_suffix(".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
        outcomes.append({"history": status.parent.name, "tests": len(data["tests"]), "exit_code": result.returncode})
    save(args.output / "promql-validation.json", outcomes)
    if not outcomes or any(r["exit_code"] for r in outcomes):
        raise SystemExit("Native PromQL verification failed")


if __name__ == "__main__":
    main()
