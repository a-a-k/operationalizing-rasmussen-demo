from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "probe2/scripts"))

from summarize import summarize_phase  # noqa: E402


class SummarizeTests(unittest.TestCase):
    def make_phase(self, root: Path, *, scheduled: int, started: int, successful: int) -> Path:
        phase = root / "phase"
        phase.mkdir()
        (phase / "summary.json").write_text(json.dumps({"metrics": {}}), encoding="utf-8")
        (phase / "run-status.json").write_text(
            json.dumps({"exit_code": 0, "completed": True}), encoding="utf-8"
        )
        (phase / "scenario-config.json").write_text(
            json.dumps({"rate": 1, "duration_seconds": scheduled, "preAllocatedVUs": 800, "maxVUs": 800}),
            encoding="utf-8",
        )
        points = []
        for _ in range(started):
            points.append({"metric": "protocol_iterations_started", "data": {"value": 1}})
            points.append({"metric": "checkout_requests_started", "data": {"value": 1}})
            points.append({"metric": "http_req_duration", "data": {"value": 100, "tags": {"request_name": "checkout"}}})
        for _ in range(successful):
            points.append({"metric": "successful_iterations", "data": {"value": 1}})
        (phase / "raw-metrics.jsonl").write_text(
            "".join(json.dumps(point) + "\n" for point in points), encoding="utf-8"
        )
        return phase

    def test_unstarted_iterations_count_as_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            phase = self.make_phase(Path(temporary), scheduled=100, started=98, successful=98)
            result = summarize_phase(
                phase,
                rate=1,
                duration_seconds=100,
                expected_vus=800,
                slo_p95_ms=500,
                slo_error_rate=0.01,
            )
            self.assertEqual(result["error_count"], 2)
            self.assertEqual(result["error_rate"], 0.02)
            self.assertFalse(result["safe"])
            self.assertAlmostEqual(result["started_fraction"], 0.98)


if __name__ == "__main__":
    unittest.main()
