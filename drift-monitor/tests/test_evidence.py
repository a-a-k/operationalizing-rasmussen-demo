"""Reproduce the archived fit, all-attempt selection and both threshold rows."""
import json
from pathlib import Path
import sys
import unittest

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE/'scripts'))
from replay_evidence import analyze


class EvidenceTests(unittest.TestCase):
    def test_complete_replay(self):
        bundle = MODULE/'results/campaign-v0.1.1'
        actual = analyze(bundle)
        saved = json.loads((bundle/'analysis/summary.json').read_text(encoding='utf-8'))
        self.assertLess(actual.pop('maximum_online_score_replay_error'), 1e-9)
        saved.pop('maximum_online_score_replay_error')
        self.assertEqual(actual, saved)
        self.assertEqual(actual['qualified_pairs'], 250)
        self.assertEqual([(r['earlier'],r['tied'],r['later']) for r in actual['rows']],
                         [(207,40,3),(179,66,5)])


if __name__ == '__main__':
    unittest.main()
