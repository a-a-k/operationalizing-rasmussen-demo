from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from summarize_k6 import summarize_compact, summarize_phase  # noqa: E402


class SummarizeK6Test(unittest.TestCase):
    def make_phase(self, root: Path, successful: int = 100, dropped: int = 0) -> Path:
        phase = root / "test"
        phase.mkdir()
        (phase / "summary.json").write_text("{}\n", encoding="utf-8")
        (phase / "run-status.json").write_text('{"exit_code": 0, "completed": true}\n', encoding="utf-8")
        (phase / "scenario-config.json").write_text(
            json.dumps({"rate": 1, "duration_seconds": 100, "preAllocatedVUs": 320, "maxVUs": 320}) + "\n",
            encoding="utf-8",
        )
        lines = []
        for _ in range(100 - dropped):
            lines.append({"metric": "protocol_iterations_started", "data": {"value": 1, "tags": {}}})
            lines.append({"metric": "checkout_requests_started", "data": {"value": 1, "tags": {}}})
            lines.append({"metric": "http_req_duration", "data": {"value": 100, "tags": {"request_name": "checkout"}}})
        for _ in range(successful):
            lines.append({"metric": "successful_iterations", "data": {"value": 1, "tags": {}}})
        for _ in range(dropped):
            lines.append({"metric": "dropped_iterations", "data": {"value": 1, "tags": {}}})
        (phase / "raw-metrics.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
        return phase

    def test_safe_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            phase = self.make_phase(Path(temporary))
            result = summarize_phase(phase, rate=1, duration_seconds=100)
            self.assertTrue(result["safe"])
            self.assertEqual(result["p95_ms"], 100)
            self.assertFalse((phase / "raw-metrics.jsonl").exists())
            self.assertTrue((phase / "compact-primary.json").is_file())
            self.assertEqual(summarize_compact(phase, 1, 100), result)

    def test_dropped_iterations_enter_error_rate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = summarize_phase(self.make_phase(Path(temporary), successful=98, dropped=2), rate=1, duration_seconds=100)
            self.assertFalse(result["safe"])
            self.assertEqual(result["error_rate"], 0.02)
            self.assertEqual(result["started_iterations"], 98)

    def test_executor_overflow_is_not_part_of_protocol_workload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            phase = self.make_phase(Path(temporary))
            with (phase / "raw-metrics.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"metric": "iterations", "data": {"value": 1, "tags": {}}}) + "\n")
            result = summarize_phase(phase, rate=1, duration_seconds=100)
            self.assertEqual(result["started_iterations"], 100)
            self.assertEqual(result["scheduled_iterations"], 100)


if __name__ == "__main__":
    unittest.main()
