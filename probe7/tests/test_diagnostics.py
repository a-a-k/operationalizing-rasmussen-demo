from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"probe7/scripts"))
spec=importlib.util.spec_from_file_location("guarded_runtime",ROOT/"probe7/scripts/runtime.py")
runtime=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class DiagnosticTests(unittest.TestCase):
    def test_disappearing_pid_frame_does_not_override_a_primary_outcome(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/"samples.jsonl"
            rows=[
                {"timestamp":"2026-10-13T00:00:01+00:00","containers":{"ad":{"error":"process vanished"}}},
                {"timestamp":"2026-10-13T00:00:02+00:00","containers":{"ad":{
                    "memory_current_bytes":100,"delta":{"cpu_cores":.2,"throttled_period_fraction":.5}}}},
            ]
            p.write_text("\n".join(json.dumps(r) for r in rows)+"\n")
            result=runtime.resources(p,0,9999999999999,{"cpu":{"ad":.25},"memory":{"ad":200}})
            self.assertEqual(result["ad"]["samples"],1)
            self.assertEqual(result["ad"]["memory_peak_bytes"],100)


if __name__=="__main__":
    unittest.main()
