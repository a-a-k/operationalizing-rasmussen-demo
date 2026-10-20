"""Small offline fixtures; these tests never start containers or a workload."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from observer import Observer
from analyze import compare, save
from promql_check import fixture
from archive import export_history
from test_observer import metadata, snap


def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def build(directory):
    cfg = {"origin_ms": 0, "windows": 3, "window_seconds": 10, "ewma_alpha": .2}
    meta = metadata()
    save(directory / "status.json", {"complete": True, "block": "offline-fixture"})
    save(directory / "load-config.json", cfg)
    save(directory / "initial-metadata.json", meta)
    save(directory / "k6/summary.json", {"metrics": {}})
    events = [{"type": "configuration_applied", "applied_ms": 0,
               "config": {"version": 1, "deployment": 1, "policy_version": 1,
                          "policy_limits": {"catalog": .25, "currency": .25}}}]
    forwarded = []
    for window in (1, 2):
        for group, component in (("catalog", "a"), ("currency", "b")):
            for j in range(5):
                request = f"{window}:{group}:{min(j, 3)}"
                attempt = int(j == 4)
                events.append({"type": "attempt_start", "logical_id": request, "attempt": attempt,
                               "logical_group": group, "component": component,
                               "configuration": 1,
                               "started_ms": (window - 1) * 10000 + j + 100})
                forwarded.append({"logical_id": request, "attempt": attempt, "upstream_status": 200})
                if j < 4:
                    events.append({"type": "logical_end", "logical_id": request, "status": 200})
    jsonl(directory / "journals/client.jsonl", events)
    jsonl(directory / "journals/reader-a.jsonl", forwarded)
    inputs, diagnoses = [], []
    observers = [Observer(mode, copy.deepcopy(meta)) for mode in ("fixed", "direct", "coda")]
    for window in (1, 2, 3):
        data = snap(window, (4, 1, 4, 1) if window < 3 else (0, 0, 0, 0))
        data["configuration_version"] = 1
        inputs.append({"snapshot": data, "metadata": copy.deepcopy(meta)})
        diagnoses.append({"rows": [o.update(data, meta) for o in observers]})
    jsonl(directory / "observer-inputs.jsonl", inputs)
    jsonl(directory / "diagnoses.jsonl", diagnoses)
    return inputs, diagnoses


class PipelineTests(unittest.TestCase):
    def test_complete_offline_replay_and_no_attempt_window(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            build(directory)
            result, rows, geometry = compare(directory)
            self.assertEqual(result["missing_windows"], [])
            self.assertEqual(result["direct_coda_disagreements"], 0)
            self.assertEqual(result["attempts_without_worker_receipt"], 0)
            self.assertEqual(result["client_attempts"], 20)
            self.assertEqual(len(geometry), 2)
            for mode in ("fixed", "direct", "coda"):
                self.assertEqual(result["methods"][mode]["state_errors"], 0)
                self.assertEqual(result["methods"][mode]["policy_errors"], 0)
                self.assertEqual(result["methods"][mode]["status_counts"]["no_attempts"], 2)
                self.assertGreater(result["methods"][mode]["held_diagnosis_time"]["stale_ms"], 0)
                self.assertEqual(result["methods"][mode]["held_diagnosis_time"]["incorrect_ms"], 0)

    def test_aggregate_corruption_is_caught_by_independent_events(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            inputs, _ = build(directory)
            inputs[0]["snapshot"]["counts"][0]["count"] += 1
            jsonl(directory / "observer-inputs.jsonl", inputs)
            # A replay mismatch is sufficient even before the oracle comparison.
            with self.assertRaisesRegex(ValueError, "replay mismatch"):
                compare(directory)

    def test_native_fixture_uses_metadata_join_and_event_expected_values(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            build(directory)
            tests = fixture(directory)["tests"]
            self.assertEqual(len(tests), 3)
            self.assertIn("group_left", tests[0]["promql_expr_test"][0]["expr"])
            self.assertEqual(tests[0]["promql_expr_test"][0]["exp_samples"][0]["value"], .2)
            # Runtime empty windows expose no component rows; zero-denominator
            # fixtures should not turn absence into a safe decision.
            self.assertEqual(tests[-1]["promql_expr_test"][0]["exp_samples"], [])

    def test_native_policy_input_is_received_metadata_not_oracle(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            inputs, _ = build(directory)
            inputs[0]["metadata"]["policies"]["1"]["limits"]["catalog"] = .1
            jsonl(directory / "observer-inputs.jsonl", inputs)
            test = fixture(directory)["tests"][0]
            limit = next(r for r in test["input_series"]
                         if r["series"] == 'retry_policy_limit{group="catalog"}')
            self.assertEqual(limit["values"], "0.1")
            expected = next(r for r in test["promql_expr_test"][1]["exp_samples"]
                            if r["labels"] == '{group="catalog"}')
            self.assertEqual(expected["value"], 0)

    def test_compressed_evidence_replays_without_host_identifiers(self):
        with tempfile.TemporaryDirectory() as name:
            source = Path(name) / "source"
            build(source)
            state = json.loads((source / "status.json").read_text())
            state["workflow_run_id"] = "fixture-run"
            state["workflow_attempt"] = "1"
            save(source / "status.json", state)
            destination = Path(name) / "archive"
            provenance = export_history(source, destination)
            self.assertEqual(compare(source), compare(destination))
            self.assertTrue((destination / "journals/client.jsonl.gz").exists())
            self.assertNotIn("workflow_run_id", (destination / "status.json").read_text())
            self.assertGreater(len(provenance), 3)


if __name__ == "__main__":
    unittest.main()
