from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from collect_terminal_evidence import collect  # noqa: E402


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


class CollectTerminalEvidenceTest(unittest.TestCase):
    def test_selects_state_attempts_and_ignores_post_terminal_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            downloads = root / "downloads"
            history = []
            valid_results = {}
            missing = {
                "replication_id": "c001",
                "attempt_id": 1,
                "workflow_run_id": "run1",
                "valid": False,
                "reason_codes": ["missing_pair_artifact"],
            }
            history.append(missing)
            for index in range(1, 257):
                replication = f"c{index:03d}"
                attempt_id = 2 if replication == "c001" else 1
                run_id = "run2" if replication == "c001" else "run1"
                result = {
                    "replication_id": replication,
                    "attempt_id": attempt_id,
                    "workflow_run_id": run_id,
                    "valid": True,
                    "reason_codes": [],
                }
                history.append(result)
                valid_results[replication] = result
                artifact = downloads / run_id / f"confirmation-{replication}-a{attempt_id}" / f"{replication}-a{attempt_id}"
                write_json(artifact / "pair-result.json", result)
                (artifact / "evidence.tar.gz").write_bytes(b"evidence")

            post_terminal = downloads / "run1" / "confirmation-c001-a1" / "c001-a1"
            write_json(post_terminal / "pair-result.json", {**missing, "valid": True})
            (post_terminal / "evidence.tar.gz").write_bytes(b"late")
            state = {
                "protocol_version": "0.3.3",
                "status": "complete",
                "target_replications": 256,
                "valid_results": valid_results,
                "attempt_history": history,
            }
            state_path = root / "state.json"
            write_json(state_path, state)
            manifest = collect(state_path, downloads, root / "selected", "terminal-run")
            self.assertEqual(manifest["valid_replications"], 256)
            self.assertEqual(manifest["attempt_history_count"], 257)
            self.assertEqual(manifest["selected_artifact_count"], 256)
            self.assertTrue(manifest["expected_missing_artifacts"][0]["artifact_present_after_terminal_state"])
            self.assertEqual(
                manifest["ignored_post_terminal_or_unreferenced_artifacts"],
                ["run1/confirmation-c001-a1"],
            )


if __name__ == "__main__":
    unittest.main()
