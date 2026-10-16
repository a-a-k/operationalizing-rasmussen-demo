import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import prediction_spec as spec
from prediction_model import forecast, predict
from prediction_dynamic import merge_streams, threshold_crossings
from prediction_run import quota_preflight

FINE = spec.ROOT / 'boundary/prediction/design-v0.1.2.json'


class FinePredictionTests(unittest.TestCase):
    def setUp(self):
        self.design_patch = patch.object(spec, 'DESIGN', FINE)
        self.design_patch.start()
        self.addCleanup(self.design_patch.stop)

    def model(self):
        return {'status': 'fitted', 'critical_quota': .08, 'offset_ms': 100, 'error_guard_quota': .08}

    def test_fine_band_contains_all_thousandths_and_coarse_points(self):
        plan = spec.validation_plan({'recommended_quota': .14})
        self.assertEqual(plan['fine_band'], {'center': .14, 'lower': .12, 'upper': .16, 'quantum': .001})
        self.assertTrue(set(spec.config()['validation_grid']).issubset(plan['quotas']))
        self.assertTrue({i/1000 for i in range(120,161)}.issubset(plan['quotas']))
        self.assertEqual(len(plan['quotas']), len(set(plan['quotas'])))
        self.assertTrue(all(a>b for a,b in zip(plan['quotas'],plan['quotas'][1:])))

    def test_band_is_clipped_without_moving_the_recommendation(self):
        plan = spec.validation_plan({'recommended_quota': .085})
        self.assertEqual(plan['fine_band']['lower'], .08)
        self.assertEqual(plan['fine_band']['upper'], .105)
        self.assertEqual(min(plan['quotas']), .08)

    def test_abstention_keeps_only_coarse_diagnostics(self):
        plan = spec.validation_plan({'recommended_quota': None})
        self.assertIsNone(plan['fine_band'])
        self.assertEqual(plan['quotas'], spec.config()['validation_grid'])

    def test_all_possible_recommendations_fit_time_budget_and_exact_cpu_grid(self):
        max_seconds = 0
        for center in spec.preflight_quotas():
            plan = spec.validation_plan({'recommended_quota': center})
            max_seconds = max(max_seconds, plan['total_seconds'])
            for q in plan['quotas']:
                allocation = spec.runtime_allocation(q)
                self.assertAlmostEqual(allocation['cpu']['checkout']+allocation['cpu']['ad'], .70)
                self.assertAlmostEqual(math.fsum(allocation['cpu'].values()), 3.4)
        self.assertLess(max_seconds, 90*60)
        self.assertEqual(len(spec.preflight_quotas()), 221)
        self.assertEqual(spec.runtime_allocation(.126)['cpu']['ad'], .574)

    def test_forecast_resolves_recommendation_on_thousandth_grid(self):
        frozen = forecast(self.model())
        self.assertLessEqual(frozen['recommendation_rounding_cpu'], .001+1e-12)
        self.assertIn(frozen['recommended_quota'], spec.validation_plan(frozen)['quotas'])
        self.assertAlmostEqual(predict(self.model(), frozen['latency_boundary_quota']), 500)

    def test_preflight_does_not_round_thousandths_back_to_hundredths(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'GITHUB_RUN_ID': 'test'}), \
             patch('prediction_run.command', return_value=SimpleNamespace(returncode=0)) as command, \
             patch('prediction_run.stack.apply'), \
             patch('prediction_run.quota_check', return_value={'valid': True, 'reasons': []}):
            quota_preflight(Path(tmp), 'prediction-r1', 'pinned-image')
            report = json.loads((Path(tmp)/'quota-preflight.json').read_text())
            self.assertEqual(len(report['checks']), 221)
            values = [r.args[0][3] for r in command.call_args_list if r.args[0][:3] == ['docker','update','--cpus']]
            self.assertIn('0.29900000', values)
            self.assertIn('0.40100000', values)

    def test_each_threshold_keeps_its_own_first_crossing_and_censoring(self):
        windows = [dict(stream='checkout', measured=True, role='baseline' if i==0 else 'validation',
                        offset_seconds=i*90, quota=q, p95_ms=p95, error_fraction=0)
                   for i,(q,p95) in enumerate([(.30,200),(.12,400),(.10,600),(.09,800)])]
        rows = threshold_crossings({'model':self.model()}, {'windows':windows,'comparison_valid':True}, True)
        result = {r['threshold_ms']:r for r in rows}
        self.assertEqual(result[300]['first_unsafe_quota'], .12)
        self.assertEqual(result[500]['first_unsafe_quota'], .10)
        self.assertTrue(result[500]['first_unsafe_permitted'])
        self.assertFalse(result[1000]['observed_crossing'])
        self.assertIsNone(result[1000]['first_unsafe_permitted'])

    def test_separate_ad_requirement_does_not_relabel_checkout(self):
        common = {'offset_seconds':180,'duration_seconds':60,'quota':.16,'load_valid':True}
        checkout = {**common,'stream':'checkout','p95_ms':200,'p95_censored':False,'error_fraction':0,
                    'client_outstanding_start':2,'client_outstanding_end':3}
        ad = {**common,'stream':'advertising','timely_fraction':.98}
        row = merge_streams([checkout,ad], {'model':self.model()})[0]
        self.assertGreater(row['checkout_latency_margin_ms'],0)
        self.assertLess(row['advertising_timely_margin'],0)
        self.assertFalse(row['all_three_requirements_met'])

    def test_complete_primary_replay_also_exports_secondary_trajectories(self):
        from test_prediction import PredictionTests
        case = PredictionTests(methodName='test_replay_whole_frozen_block_and_reject_tampering')
        case.test_replay_whole_frozen_block_and_reject_tampering()


if __name__ == '__main__':
    unittest.main()
