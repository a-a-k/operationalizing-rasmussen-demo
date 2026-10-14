from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe8/scripts"))
from prometheus_replay import opportunities
sys.path.insert(0, str(Path(__file__).parent))
from analyze import attach_prom, evaluate, load_analysis, run_native


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary-dir", type=Path, required=True)
    args = parser.parse_args()
    analysis = load_analysis()
    blocks = json.loads((ROOT / "probe8/results/confirmation-v0.1.0/evaluation/block-level.json").read_text())
    rows, events = opportunities(blocks, analysis)
    lookup = {}
    for bid, block in blocks.items():
        for policy, history in block["histories"].items():
            for window in history["observations"]:
                lookup[(bid, policy, window["epoch"])] = window["online_warning"]
    prepared = []
    for row in rows:
        record = lookup[(row["block_id"], row["policy"], row["epoch"])]
        prepared.append({**row, "initial_state": blocks[row["block_id"]]["initial_state"],
                         "resource_scored_ms": row["ilr_scored_ms"],
                         "share_score": record["methods"]["share_history"]["score"],
                         "share_frozen_alert": record["methods"]["share_history"]["alert"],
                         "ilr_frozen_alert": row["ilr_alert"]})
    for event in events:
        event.update(initial_state=blocks[event["block_id"]]["initial_state"],
                     profile=blocks[event["block_id"]]["profile"],
                     outcome_available_ms=None)
    with tempfile.TemporaryDirectory() as name:
        native, checks, _ = run_native(blocks, prepared, analysis, args.binary_dir.resolve(), Path(name) / "engine")
        attached = attach_prom(prepared, native, analysis)
        lookbacks, _, _, _, _ = evaluate(attached, events, analysis)
    saved = json.loads((ROOT / analysis["practical_baseline_result"]).read_text())
    for lookback in (300, 120, 600):
        expected = saved["lookbacks"][str(lookback)]["methods"]
        actual = lookbacks[str(lookback)]["methods"]
        for method in ("prometheus_predict_linear", "ilr_history"):
            if actual[method] != {**expected[method],
                                  "histories_with_false_warning": actual[method]["histories_with_false_warning"]}:
                comparable = {k: actual[method][k] for k in expected[method]}
                if comparable != expected[method]:
                    raise ValueError(f"Native preflight differs: {lookback}/{method}")
    fixture = checks["steady_trend_and_future_invariance"]["data"]["result"]
    if {row["metric"]["variant"]: float(row["value"][1]) for row in fixture} != {"full": 0.6, "prefix": 0.6}:
        raise ValueError("Native future-cutoff fixture differs")
    print(json.dumps({"status": "verified", "decisions": len(prepared),
                      "native_queries": len(native), "old_events": len(events)}))


if __name__ == "__main__":
    main()
