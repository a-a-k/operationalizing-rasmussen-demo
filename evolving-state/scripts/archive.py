"""Export a narrow anonymous, replayable evidence bundle from hosted artifacts."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from analyze import client_responses, compare, save

JSON_FILES = ("status.json", "design.json", "load-config.json", "initial-metadata.json",
              "initial-configuration.json", "final-metadata.json", "k6/summary.json")
STREAM_FILES = ("observer-inputs.jsonl", "diagnoses.jsonl", "interventions.jsonl",
                "metadata-receipts.jsonl", "journals/client.jsonl")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def export_history(source, destination):
    destination.mkdir(parents=True, exist_ok=False)
    provenance = []
    for relative in JSON_FILES:
        path = source / relative
        if not path.exists():
            continue
        data = path.read_bytes().replace(b"\r\n", b"\n")
        value = json.loads(data)
        if relative == "status.json":
            # Public reproducibility needs the implementation, not an identifying
            # link into a hosting account or the account's workflow-run number.
            value.pop("workflow_run_id", None)
            value.pop("workflow_attempt", None)
        save(destination / relative, value)
        provenance.append({"file": relative, "source_sha256_lf": digest(data),
                           "archived_sha256_lf": digest((destination / relative).read_bytes())})
    paths = [source / p for p in STREAM_FILES]
    paths += sorted((source / "journals").glob("reader-*.jsonl"))
    for path in paths:
        if not path.exists():
            continue
        relative = path.relative_to(source).as_posix()
        data = path.read_bytes().replace(b"\r\n", b"\n")
        output = destination / (relative + ".gz")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(gzip.compress(data, mtime=0))
        provenance.append({"file": relative + ".gz", "source_sha256_lf": digest(data),
                           "archived_uncompressed_sha256_lf": digest(data)})
    client = client_responses(source)
    data = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in client).encode()
    (destination / "k6").mkdir(exist_ok=True)
    (destination / "k6/client-responses.jsonl.gz").write_bytes(gzip.compress(data, mtime=0))
    provenance.append({"file": "k6/client-responses.jsonl.gz",
                       "operation": "CLIENT records only, extracted from raw generator logs",
                       "uncompressed_sha256": digest(data), "records": len(client)})
    original = compare(source)
    reproduced = compare(destination)
    if original != reproduced:
        raise ValueError("Export changed a reconstructed result")
    return provenance


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Archive destinations must be new; never overwrite an evidence bundle")
    statuses = sorted(args.inputs.rglob("status.json"))
    if not statuses:
        raise ValueError("No histories to export")
    blocks = [json.loads(p.read_text())["block"] for p in statuses]
    if len(set(blocks)) != len(blocks):
        raise ValueError("Duplicate histories: select and document attempts before export")
    args.output.mkdir(parents=True)
    provenance = {"label": args.label, "histories": {}, "analysis_source_sha256_lf":
                  digest(Path(__file__).with_name("analyze.py").read_bytes().replace(b"\r\n", b"\n")),
                  "omitted": "Host paths, workflow-run identifiers, container console logs and unneeded rendered deployment paths. Native source artifacts remain separate; the retained event and observation inputs reproduce the analysis."}
    for status in statuses:
        block = json.loads(status.read_text())["block"]
        provenance["histories"][block] = export_history(status.parent, args.output / "inputs" / block)
    save(args.output / "provenance.json", provenance)
    subprocess.run([sys.executable, "-B", str(Path(__file__).with_name("analyze.py")),
                    "--inputs", str(args.output / "inputs"),
                    "--output", str(args.output / "analysis")], check=True)
    print(json.dumps({"archived_histories": len(blocks), "label": args.label}))


if __name__ == "__main__":
    main()
