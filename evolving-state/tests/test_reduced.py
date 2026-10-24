"""Independent reduced history on the same policy and availability semantics."""
import json
import math
from pathlib import Path
import sys
import unittest

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE/'scripts'))
from reduced import ReducedHistory, analyze, diagnose


class ReducedTests(unittest.TestCase):
    def test_causal_repeated_window_and_gap(self):
        history = ReducedHistory(.2)
        self.assertIsNone(history.update(1, [0.,0.])['increment'])
        second = history.update(2, [1.,-1.])
        self.assertEqual(second['increment'], [1.,-1.])
        self.assertEqual(second, history.update(2, [1.,-1.]))
        history.update(3, None)
        self.assertIsNone(history.update(3, [2.,0.])['increment'])
        self.assertIsNone(history.update(5, [3.,0.])['smoothed_increment'])

    def test_log_odds_contact_matches_direct_ratio(self):
        result = diagnose([math.log(.2), math.log(.1)], [1.,0.], {'catalog':.5,'currency':.5})
        self.assertEqual(result['first_constraints'], ['catalog'])
        self.assertEqual(result['directions'], {'catalog':'toward','currency':'tangent'})

    def test_all_238_saved_diagnoses(self):
        bundle = MODULE/'results/campaign-v0.1.1'
        summary, comparisons = analyze(bundle)
        destination = bundle/'directional-v0.1.0/reduced-v0.1.0'
        self.assertEqual(summary, json.loads((destination/'summary.json').read_text(encoding='utf-8')))
        self.assertEqual(comparisons, json.loads((destination/'comparisons.json').read_text(encoding='utf-8')))
        self.assertEqual(summary['comparisons'], 238)


if __name__ == '__main__':
    unittest.main()
