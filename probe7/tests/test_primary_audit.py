from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"probe7/scripts"))
from audit_primary import checkout, compare


class PrimaryAuditTests(unittest.TestCase):
    def test_replay_counts_failed_dropped_and_unfinished_once(self):
        primary={"counters":{"protocol_iterations_started":3,"protocol_iterations_finished":2,
                             "successful_iterations":1,"checkout_requests_started":2,"dropped_iterations":1},
                 "checkout_durations_ms":[200,600],"operation_durations_ms":[210,610]}
        c=checkout(primary,{"rate":1,"duration_seconds":4},{"p95_ms":500,"error_fraction":.01})
        self.assertEqual(c["error_count"],3)
        self.assertEqual(c["error_rate"],.75)
        self.assertEqual(c["p95_ms"],580)
        self.assertFalse(c["safe"])

    def test_changed_primary_outcome_is_rejected(self):
        with self.assertRaises(ValueError):
            compare({"safe":False},{"safe":True},["safe"])
        with self.assertRaises(ValueError):
            compare({"p95_ms":501},{"p95_ms":499},["p95_ms"])
