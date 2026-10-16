import copy
import gzip
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from period_spec import (DESIGN, allocation, base_config, config, digest, fit, legacy,
                         limits, matrix, plan, prediction, recommend, render)
from period_analyze import analyze, paired_summary, prediction_error, select_blocks
from prediction_primary import score
from diagnostic_run import expected_limits
from diagnostic_observe import CPU_FIELDS


class PeriodPredictionTests(unittest.TestCase):
    def test_complete_interleaved_calibration_and_counterbalanced_tests(self):
        rows = matrix()
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows, matrix())
        self.assertEqual(sum(b['test_order'][0] == 100000 for b in rows), 2)
        for block in rows:
            self.assertEqual(len(block['calibration_order']), 10)
            self.assertEqual({(c['period_us'], c['quota']) for c in block['calibration_order']},
                             {(p, q) for p in config()['periods_us'] for q in config()['calibration_quotas']})

    def test_minimum_quota_representable_at_both_periods(self):
        for period in config()['periods_us']:
            for milli in range(80, 301):
                quota, actual = limits(milli/1000, period)
                self.assertGreaterEqual(quota, 1000)
                self.assertEqual(quota/actual, milli/1000)
        with self.assertRaises(ValueError):
            limits(.08, 10000)

    def test_render_arbitrary_target_without_changing_budget_or_other_periods(self):
        state = allocation(.133)
        source = {'services': {n: {'cpus': '.4'} for n in state['cpu']}}
        before = copy.deepcopy(source)
        rendered = render(source, state, 20000, True)
        self.assertEqual(before, source)
        self.assertAlmostEqual(sum(state['cpu'].values()), 3.4)
        for name, service in rendered['services'].items():
            self.assertNotIn('cpus', service)
            self.assertEqual(service['cpu_period'], 20000 if name == 'checkout' else 100000)
            self.assertEqual(service['cpu_quota']/service['cpu_period'], state['cpu'][name])
        startup = render(source, state, 20000, False)
        self.assertTrue(all('cpu_quota' not in s for s in startup['services'].values()))

    def model(self, c=.08, b=100):
        return {'status': 'fitted', 'critical_quota': c, 'offset_ms': b, 'error_guard_quota': .08}

    def test_unchanged_formula_and_fitter(self):
        model = self.model()
        observations = [{'quota': q, 'p95_lower_ms': legacy.predict(model, q), 'p95_censored': False, 'error_fraction': 0}
                        for q in [.30, .22, .16, .12]]
        observations.append({'quota': .08, 'p95_lower_ms': 5000, 'p95_censored': True, 'error_fraction': 1})
        a, b = fit(observations), legacy.fit(observations)
        self.assertEqual(a, b)
        self.assertAlmostEqual(a['critical_quota'], .08)
        self.assertEqual(a['offset_ms'], 100)

    def test_recommendation_rounds_up_and_keeps_empirical_guard(self):
        model = self.model(.11, 139)
        quota = recommend(model)
        self.assertTrue(legacy.permitted(model, quota))
        self.assertFalse(legacy.permitted(model, round(quota-.001, 8)))
        self.assertAlmostEqual(quota/.001, round(quota/.001))
        self.assertIsNone(recommend({'status': 'abstain'}))
        guarded = {**model, 'error_guard_quota': .2}
        self.assertGreater(recommend(guarded), .2)

    def test_signed_error_is_not_latency_difference_or_automatic_accuracy_gain(self):
        observed = {'p95_ms': 600, 'p95_lower_ms': 600, 'p95_censored': False}
        self.assertEqual(prediction_error(400, observed)['signed_error_ms'], 200)
        over = prediction_error(1000, observed)
        self.assertEqual(over['signed_error_ms'], -400)
        self.assertEqual(over['absolute_error_ms'], 400)
        self.assertIsNone(prediction_error(None, observed)['signed_error_ms'])

    def test_censored_quantile_retains_bound_not_exact_error(self):
        observed = {'p95_ms': 5000, 'p95_lower_ms': 5000, 'p95_censored': True}
        row = prediction_error(400, observed)
        self.assertEqual(row['error_lower_bound_ms'], 4600)
        self.assertIsNone(row['signed_error_ms'])
        self.assertIsNone(row['absolute_error_ms'])

    def test_matching_period_prediction_shift_separates_absorption_from_residual(self):
        rows = {'100000': {'p95_ms': 600, 'p95_lower_ms': 600, 'p95_censored': False},
                '20000': {'p95_ms': 300, 'p95_lower_ms': 300, 'p95_censored': False}}
        pair = paired_summary(rows, {'100000': 500, '20000': 250})
        self.assertEqual(pair['observed_long_minus_short_ms'], 300)
        self.assertEqual(pair['predicted_long_minus_short_ms'], 250)
        self.assertEqual(pair['matched_error_difference_ms'], 50)

    def test_budget_and_distinct_fresh_test_windows(self):
        self.assertEqual(plan(.12, 'calibration')['total_seconds'], 240)
        self.assertEqual(plan(.12, 'test')['total_seconds'], 300)
        self.assertEqual(plan(.12, 'test')['updates'], [])
        self.assertEqual(10*240+2*300, 3000)

    def test_full_raw_replay_freeze_integrity_and_atomic_retry(self):
        rates = {**base_config(), 'checkout_rate': 2, 'advertising_rate': 3}
        with tempfile.TemporaryDirectory() as temporary, patch('prediction_primary.base_config', return_value=rates):
            root = Path(temporary)
            folder = root/'inputs'/'attempt-1'/'period-r1'
            folder.mkdir(parents=True)
            block = {**matrix()[0], 'config': config(), 'design_sha256': digest(DESIGN),
                     'run_id': 'synthetic', 'run_attempt': 1, 'execution_commit': os.getenv('GITHUB_SHA', 'synthetic'),
                     'test_complete': True}
            def write(path, value):
                path.write_text(json.dumps(value), encoding='utf-8')
            def session(name, quota, period, phase, model):
                destination = folder/name
                destination.mkdir()
                origin = 10000 if phase == 'calibration' else 1000000
                session_plan = plan(quota, phase)
                value = prediction(model, quota)
                censored = value is None
                value = 5000 if censored else value+(100 if period == 100000 else 50) if phase == 'test' else value
                records = []
                for stream, rate in [('checkout', 2), ('advertising', 3)]:
                    for i in range(session_plan['total_seconds']*rate):
                        t = origin+1000*(i+.1)/rate
                        start = {'id': i, 'stream': stream, 'origin': origin, 't': t}
                        latency = value if stream == 'checkout' else 30
                        records.extend([{**start, 'kind': 'start'}, {**start, 'kind': 'finish', 't': t+latency,
                                        'latency_ms': latency, 'success': not censored if stream == 'checkout' else True,
                                        'error_code': 1050 if censored and stream == 'checkout' else 0}])
                windows = score(records, [], session_plan)
                cached = {'block_id': 'period-r1', 'session_id': name, 'plan': session_plan, 'quota': quota,
                          'period_us': period, 'phase': phase, 'allocation': allocation(quota), 'generator_name': 'generator',
                          'load_origin_ms': origin, 'comparison_valid': True, 'reasons': [], 'windows': windows,
                          'execution_commit': block['execution_commit']}
                write(destination/'session.json', cached)
                with gzip.open(destination/'primary-events.json.gz', 'wt', encoding='utf-8') as stream:
                    json.dump({'events': records, 'drops': []}, stream)
                for filename in ['initial-quota-checks.json', 'final-quota-checks.json']:
                    write(destination/filename, {'valid': True})
                containers = {n: {'cpu_max': f'{q} {p}', 'delta': {'usage_usec': 200000, 'sample_seconds': 2,
                                     'nr_periods': 20, 'nr_throttled': 0, 'throttled_usec': 0}}
                              for n, (q, p) in expected_limits(allocation(quota), {'period_us': period}).items()}
                containers['generator'] = {'delta': {'usage_usec': 200000, 'sample_seconds': 2}}
                frames = [{'timestamp_ms': origin+(w['offset_seconds']+2)*1000, 'containers': containers,
                           'host_cpu_fractions': dict.fromkeys(CPU_FIELDS, 0)}
                          for w in windows if w['stream'] == 'checkout' and w['measured']]
                (destination/'resource-samples.jsonl').write_text('\n'.join(json.dumps(f) for f in frames), encoding='utf-8')
                (destination/'container-events.jsonl').write_text('', encoding='utf-8')
                return [w for w in windows if w['stream'] == 'checkout' and w['measured']]
            truth = {'100000': self.model(.09, 100), '20000': self.model(.06, 90)}
            observations = {p: [] for p in truth}
            hashes = {}
            for condition in block['calibration_order']:
                name, p, q = condition['id'], condition['period_us'], condition['quota']
                observations[str(p)].extend(session(name, q, p, 'calibration', truth[str(p)]))
                for filename in ['session.json', 'primary-events.json.gz']:
                    relative = name+'/'+filename
                    hashes[relative] = digest(folder/relative)
            models = {p: fit(rows) for p, rows in observations.items()}
            target = recommend(models['100000'])
            frozen = {**block, 'models': models, 'calibration_observations': observations, 'calibration_hashes': hashes,
                      'target_quota': target, 'target_is_recommendation': True,
                      'predictions': {p: prediction(m, target) for p, m in models.items()}, 'frozen_ms': 500000}
            write(folder/'frozen-models.json', frozen)
            block['frozen_sha256'] = digest(folder/'frozen-models.json')
            write(folder/'block.json', block)
            for p in block['test_order']:
                session(f'test-{p}', target, p, 'test', models[str(p)])
            result = analyze(root/'inputs', root/'output')
            self.assertEqual(result['complete_pairs'], 1)
            self.assertEqual(result['rescored_sessions'], 12)
            self.assertAlmostEqual(result['pairs'][0]['long_matched_error_ms'], 100)
            self.assertAlmostEqual(result['pairs'][0]['short_matched_error_ms'], 50)
            latest = root/'inputs'/'attempt-2'/'period-r1'
            latest.mkdir(parents=True)
            write(latest/'block.json', {**block, 'run_attempt': 2, 'test_complete': False})
            self.assertEqual(select_blocks(root/'inputs')['period-r1'][0]['run_attempt'], 2)
            self.assertEqual(analyze(root/'inputs', root/'latest-output')['complete_pairs'], 0)
            (latest/'block.json').unlink()
            frozen['target_quota'] += .001
            write(folder/'frozen-models.json', frozen)
            failure = analyze(root/'inputs', root/'tampered-output')
            self.assertTrue(any('hash mismatch' in r['error'] for r in failure['failures']))


if __name__ == '__main__':
    unittest.main()
