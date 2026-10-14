from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
from warning_model import FROZEN, WarningModel, canonical_hash

CAMPAIGN = "probe8/runtime-design-v0.1.0.json"


def campaign_matrix(design):
    rows = copy.deepcopy(design["confirmation_blocks"])
    cells = sorted({(r["initial_state"], r["profile"]) for r in rows})
    for state, profile in cells:
        cell = [r for r in rows if (r["initial_state"], r["profile"]) == (state, profile)]
        ranked = sorted(cell, key=lambda r: hashlib.sha256((design["randomization_salt"] + ":" + r["block_id"]).encode()).digest())
        start_adaptive = not (state == "ledger" and profile == "moderate")
        for index, row in enumerate(ranked):
            adaptive_first = start_adaptive if index % 2 == 0 else not start_adaptive
            row["order"] = ["adaptive", "control"] if adaptive_first else ["control", "adaptive"]
    return rows


def guarded_module():
    spec = importlib.util.spec_from_file_location("guarded_warning_parent", ROOT / "probe7/scripts/runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Observer:
    def __init__(self, model, model_hash):
        self.model, self.model_hash = model, model_hash
        self.prefixes, self.failures = {}, []

    def phase(self, original, *args, **kwargs):
        measured = original(*args, **kwargs)
        folder = args[5] if len(args) > 5 else kwargs["folder"]
        profile = args[2] if len(args) > 2 else kwargs["profile"]
        if not folder.name.isdigit():
            return measured
        measured["epoch"] = int(folder.name)
        measured["primary_available_ms"] = time.time() * 1000
        prefix = self.prefixes.setdefault(str(folder.parent), [])
        prefix.append(copy.deepcopy(measured))
        started = time.time() * 1000
        try:
            result = self.model.score(prefix, profile["id"])
            result["prediction_valid"] = True
        except Exception as exc:
            result = {"eligible": None, "prediction_valid": False, "error": repr(exc), "methods": {}}
            self.failures.append(str(folder))
        result.update(epoch=measured["epoch"], features_available_ms=measured["primary_available_ms"],
                      scored_ms=time.time() * 1000, model_sha256_lf=self.model_hash,
                      runtime_mode="observer_only")
        result["prediction_duration_ms"] = result["scored_ms"] - started
        measured["online_warning"] = result
        (folder / "online-warning.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return measured


def run(upstream, output, block_id):
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
    block["warning_model"] = {"sha256_lf": observer.model_hash, "version": model.definition["version"],
                              "development_execution": model.frozen["development_execution"],
                              "observer_failures": len(observer.failures), "runtime_mode": "observer_only"}
    block_file.write_text(json.dumps(block, indent=2) + "\n", encoding="utf-8")
    if observer.failures:
        print(json.dumps({"observer_failures": len(observer.failures)}), flush=True)
        return 1
    return code


def main():
    parser = argparse.ArgumentParser(description="Run independent guarded histories with passive frozen warnings.")
    parser.add_argument("command", choices=["matrix", "run"])
    parser.add_argument("--upstream-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--block-id")
    args = parser.parse_args()
    if args.command == "matrix":
        print(json.dumps({"include": campaign_matrix(json.loads((ROOT / CAMPAIGN).read_text()))}))
    else:
        raise SystemExit(run(args.upstream_dir.resolve(), args.output_dir.resolve(), args.block_id))


if __name__ == "__main__":
    main()
