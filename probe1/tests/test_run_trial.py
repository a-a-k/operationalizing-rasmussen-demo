from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from run_trial import cpu_stat, quota_snapshot, read_container_cgroup_file, system_failure  # noqa: E402


class TrialValidityTest(unittest.TestCase):
    @patch("run_trial.read_container_cgroup_file")
    @patch("run_trial.inspect_container")
    def test_effective_quota_comes_from_cpu_max(self, inspect, cgroup_read) -> None:
        inspect.return_value = {"HostConfig": {"NanoCpus": 500_000_000}, "State": {"Pid": 10}}
        cgroup_read.return_value = ("50000 100000", "/proc/10/root/sys/fs/cgroup/cpu.max")
        snapshot = quota_snapshot(
            {"checkout": 0.5, "payment": 0.5, "shipping": 0.5},
            1.5,
        )
        self.assertTrue(snapshot["valid"])
        self.assertEqual(snapshot["effective"]["checkout"], 0.5)

    @patch("run_trial.read_container_cgroup_file")
    def test_post_intervention_cpu_stat_can_be_unavailable(self, cgroup_read) -> None:
        cgroup_read.side_effect = RuntimeError("container stopped")
        self.assertEqual(cpu_stat(["checkout"], tolerate_unavailable=True), {"checkout": {}})

    def test_reads_cgroup_via_container_process_root_without_container_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc_root, cgroup_root = root / "proc", root / "cgroup"
            target = proc_root / "42" / "root" / "sys" / "fs" / "cgroup"
            target.mkdir(parents=True)
            (target / "cpu.max").write_text("50000 100000\n", encoding="utf-8")
            (proc_root / "42" / "cgroup").write_text("0::/docker/test\n", encoding="utf-8")
            value, source = read_container_cgroup_file(
                "checkout",
                "cpu.max",
                inspected={"State": {"Pid": 42}},
                proc_root=proc_root,
                cgroup_root=cgroup_root,
            )
            self.assertEqual(value, "50000 100000")
            self.assertTrue(source.endswith("cpu.max"))

    def test_stopped_container_is_system_failure_diagnostic(self) -> None:
        before = {"checkout": {"RestartCount": 0, "State": {"Running": True, "OOMKilled": False}}}
        after = {"checkout": {"RestartCount": 1, "State": {"Running": False, "OOMKilled": True, "Status": "exited"}}}
        failed, details = system_failure(before, after, ["checkout"])
        self.assertTrue(failed)
        self.assertTrue(details["checkout"]["failed"])


if __name__ == "__main__":
    unittest.main()
