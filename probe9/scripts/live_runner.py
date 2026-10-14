from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe8/scripts"))
from warning_model import FROZEN, WarningModel, canonical_hash

_observer_spec = importlib.util.spec_from_file_location(
    "frozen_warning_live_runner", ROOT / "probe8/scripts/live_runner.py")
_observer_module = importlib.util.module_from_spec(_observer_spec)
_observer_spec.loader.exec_module(_observer_module)
Observer = _observer_module.Observer

CAMPAIGN = "probe9/runtime-design-v0.1.0.json"


def load_design(root=ROOT):
    return json.loads((root / CAMPAIGN).read_text())


def campaign_matrix(design):
    rows = []
    cells = [(state["id"], profile["id"])
             for state in design["initial_states"] for profile in design["profiles"]]
    for cell_index, (state, profile) in enumerate(cells):
        cell = [{"block_id": f"{state}-{profile}-{rep:02d}", "initial_state": state,
                 "profile": profile, "repetition": rep}
                for rep in range(1, design["repetitions"] + 1)]
        ranked = sorted(cell, key=lambda r: hashlib.sha256(
            (design["randomization_salt"] + ":" + r["block_id"]).encode()).digest())
        start_adaptive = cell_index % 2 == 0
        for index, row in enumerate(ranked):
            adaptive_first = start_adaptive if index % 2 == 0 else not start_adaptive
            row["order"] = ["adaptive", "control"] if adaptive_first else ["control", "adaptive"]
        rows.extend(cell)
    return rows


def guarded_module():
    spec = importlib.util.spec_from_file_location(
        "guarded_generalization_parent", ROOT / "probe7/scripts/runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(upstream, output, block_id):
    design = load_design()
    planned = {row["block_id"]: row for row in campaign_matrix(design)}
    if block_id not in planned:
        raise ValueError("Block is outside the fixed 250-job matrix")
    model = WarningModel()
    observer = Observer(model, canonical_hash(ROOT / FROZEN))
    parent = guarded_module()
    original_phase = parent.phase
    parent.DESIGN = CAMPAIGN
    parent.matrix = campaign_matrix
    parent.phase = lambda *args, **kwargs: observer.phase(original_phase, *args, **kwargs)
    code = parent.execute(upstream, output, block_id, None)
    block_file = output / "block.json"
    block = json.loads(block_file.read_text())
    block["warning_model"] = {
        "sha256_lf": observer.model_hash,
        "version": model.definition["version"],
        "development_execution": model.frozen["development_execution"],
        "observer_failures": len(observer.failures),
        "runtime_mode": "observer_only"
    }
    block_file.write_text(json.dumps(block, indent=2) + "\n", encoding="utf-8")
    if observer.failures:
        print(json.dumps({"observer_failures": len(observer.failures)}), flush=True)
        return 1
    return code


def main():
    parser = argparse.ArgumentParser(description="Run the fixed drift-generalization matrix.")
    parser.add_argument("command", choices=["matrix", "run"])
    parser.add_argument("--upstream-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--block-id")
    args = parser.parse_args()
    if args.command == "matrix":
        print(json.dumps({"include": campaign_matrix(load_design())}, separators=(",", ":")))
    else:
        raise SystemExit(run(args.upstream_dir.resolve(), args.output_dir.resolve(), args.block_id))


if __name__ == "__main__":
    main()
