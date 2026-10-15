import gzip
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from prediction_spec import allocation, base_config, calibration_plan, config, matrix, runtime_allocation, validation_plan
from prediction_model import arc_length, fit, forecast, ilr_quota, permitted, point_prediction, predict, vector
from prediction_primary import bounded_quantile, intervals, score
from prediction_analyze import analyze, evaluate, select_blocks
from prediction_run import digest
from geometry import aitchison


class PredictionTests(unittest.TestCase):
    def model(self):
        return {'status': 'fitted', 'critical_quota': .08, 'offset_ms': 100, 'error_guard_quota': .08}

    def test_six_independent_blocks_with_fixed_calibration_sets(self):
        rows = matrix()
        self.assertEqual(len(rows), 6)
        self.assertEqual(len({r['block_id'] for r in rows}), 6)
        for row in rows:
            self.assertEqual(sorted(row['calibration_order']), sorted(config()['calibration_quotas']))
        self.assertEqual(rows, matrix())

    def test_fits_known_parameters_without_validation_input(self):
        observations = [{'quota': q, 'p95_lower_ms': predict(self.model(), q), 'p95_censored': False, 'error_fraction': 0}
                        for q in [.30, .22, .16, .12]]
        observations.append({'quota': .08, 'p95_lower_ms': 5000, 'p95_censored': True, 'error_fraction': 1})
        fitted = fit(observations)
        self.assertAlmostEqual(fitted['critical_quota'], .08)
        self.assertEqual(fitted['offset_ms'], 100)
        self.assertLess(fitted['training_log_loss'], 1e-20)
        self.assertEqual(fitted['censored_observations'], 1)
        self.assertEqual(fitted['error_guard_quota'], .08)

    def test_insufficient_calibration_abstains(self):
        self.assertEqual(fit([])['status'], 'abstain')

    def test_prediction_monotone_and_saturation_explicit(self):
        self.assertLess(predict(self.model(), .20), predict(self.model(), .12))
        self.assertTrue(math.isinf(predict(self.model(), .08)))
        self.assertFalse(permitted(self.model(), .08))

    def test_error_guard_not_hidden_in_latency_model(self):
        model = {**self.model(), 'error_guard_quota': .16}
        self.assertLess(predict(model, .16), 500)
        self.assertFalse(permitted(model, .16))
        self.assertTrue(permitted(model, .17))

    def test_forecast_and_ilr_root_match_and_recommendation_inserted(self):
        frozen = forecast(self.model())
        self.assertEqual(frozen['status'], 'recommended')
        self.assertAlmostEqual(frozen['latency_boundary_quota'], frozen['latency_boundary_via_ilr'], places=10)
        self.assertTrue(permitted(self.model(), frozen['recommended_quota']))
        self.assertIn(frozen['recommended_quota'], validation_plan(frozen)['quotas'])
        self.assertGreaterEqual(frozen['recommended_quota'], frozen['guarded_boundary_quota'])
        self.assertLess(frozen['recommended_quota']-frozen['guarded_boundary_quota'], .00101)

    def test_full_composition_inverse_and_curve_length(self):
        self.assertEqual(len(vector(.12)), 11)
        for q in [.30, .22, .12, .08, .094978661367]:
            self.assertAlmostEqual(ilr_quota(q), q, places=12)
            self.assertAlmostEqual(math.fsum(allocation(q)['cpu'].values()), 3.4, places=12)
        self.assertGreaterEqual(arc_length(.30, .10), aitchison(vector(.30), vector(.10)))
        self.assertAlmostEqual(arc_length(.30, .10, 256), arc_length(.30, .10, 512), places=8)
        self.assertEqual(arc_length(.16, .16), 0)

    def test_no_infinite_json_prediction(self):
        row = point_prediction(forecast(self.model()), .08)
        self.assertIsNone(row['p95_prediction_ms'])
        self.assertEqual(row['prediction_kind'], 'no_stationary_prediction')
        json.dumps(row, allow_nan=False)

    def test_runtime_cpu_arguments_have_fixed_point_precision(self):
        for q in [*config()['calibration_quotas'], *validation_plan(forecast(self.model()))['quotas']]:
            actual = runtime_allocation(q)
            for name, value in actual['cpu'].items():
                self.assertLessEqual(len(str(value).split('.')[-1]), 8)
                self.assertAlmostEqual(value, allocation(q)['cpu'][name], places=12)

    def test_every_time_interval_retained_and_no_recovery(self):
        plan = validation_plan(forecast(self.model()))
        rows = intervals(plan)
        self.assertEqual(rows[0]['offset'], 0)
        self.assertEqual(rows[-1]['offset']+rows[-1]['seconds'], plan['total_seconds'])
        self.assertEqual(sum(r['seconds'] for r in rows), plan['total_seconds'])
        self.assertTrue(all(a > b for a, b in zip(plan['quotas'], plan['quotas'][1:])))
        self.assertTrue(all(q >= .08 for q in plan['quotas']))
        self.assertEqual(calibration_plan(.12)['total_seconds'], 300)

    def data(self, n=100, timeouts=0):
        events = []
        for name in ['checkout', 'advertising']:
            for i in range(n):
                row = {'stream': name, 'id': i, 'origin': 10000, 't': 10000 + i*10}
                timeout = name == 'checkout' and i < timeouts
                latency = 5000 if timeout else 100
                events += [{**row, 'kind': 'start'}, {**row, 'kind': 'finish', 't': row['t']+latency,
                           'success': not timeout, 'latency_ms': latency, 'error_code': 1050 if timeout else None}]
        plan = {'kind': 'calibration', 'quota': .12, 'total_seconds': 1, 'updates': [],
                'intervals': [{'offset': 0, 'seconds': 1, 'quota': .12, 'measured': True, 'role': 'calibration'}]}
        return events, plan

    def test_censored_quantile_is_lower_bound_not_exact_deadline(self):
        events, plan = self.data(timeouts=10)
        row = next(r for r in score(events, [], plan) if r['stream'] == 'checkout')
        self.assertEqual(row['p95_ms'], 5000)
        self.assertEqual(row['p95_lower_ms'], 5000)
        self.assertTrue(row['p95_censored'])
        self.assertIsNone(row['p95_upper_ms'])
        self.assertEqual(row['error_fraction'], .1)
        self.assertFalse(row['slo_safe'])

    def test_small_timeout_tail_does_not_censor_known_p95(self):
        events, plan = self.data(timeouts=1)
        row = next(r for r in score(events, [], plan) if r['stream'] == 'checkout')
        self.assertEqual(row['p95_lower_ms'], 100)
        self.assertFalse(row['p95_censored'])
        self.assertEqual(row['error_fraction'], .01)
        self.assertFalse(row['slo_safe'])

    def test_interpolation_touching_timeout_is_censored(self):
        self.assertTrue(math.isinf(bounded_quantile([100]*19 + [math.inf], .95)))

    def test_missing_finishes_remain_failures(self):
        events, plan = self.data(n=10)
        events = [r for r in events if not (r['stream'] == 'checkout' and r['kind'] == 'finish' and r['id'] == 0)]
        row = next(r for r in score(events, [], plan) if r['stream'] == 'checkout')
        self.assertEqual(row['unfinished'], 1)
        self.assertEqual(row['error_fraction'], .1)
        self.assertTrue(row['p95_censored'])

    def test_duplicate_records_rejected(self):
        events, plan = self.data()
        with self.assertRaises(ValueError):
            score(events+[events[0]], [], plan)

    def session(self, safe=(True, True, False), baseline=True):
        rows = []
        for i, (quota, ok) in enumerate(zip([.30, .16, .12, .10], [baseline, *safe])):
            rows.append({'stream': 'checkout', 'quota': quota, 'measured': True,
                         'role': 'baseline' if i == 0 else 'validation', 'offset_seconds': 180+i*90,
                         'slo_safe': ok, 'p95_ms': 200 if ok else 600, 'p95_censored': False})
        return {'comparison_valid': True, 'windows': rows}

    def test_overpermission_counted_at_first_unsafe_not_postfailure_points(self):
        frozen = forecast(self.model())
        summary, rows = evaluate(frozen, self.session())
        self.assertTrue(summary['primary_eligible'])
        self.assertTrue(summary['unsafe_allowed'])
        self.assertAlmostEqual(summary['last_safe_transfer_cpu'], .18)
        self.assertAlmostEqual(summary['first_unsafe_transfer_cpu'], .20)
        later = self.session(safe=(True, False, False))
        _, rows = evaluate(frozen, later)
        self.assertFalse(rows[-1]['in_first_crossing_prefix'])
        self.assertFalse(rows[-1]['false_permission_in_prefix'])

    def test_unsafe_baseline_is_out_of_scope_not_a_success(self):
        summary, _ = evaluate(forecast(self.model()), self.session(baseline=False))
        self.assertFalse(summary['primary_eligible'])
        self.assertIsNone(summary['unsafe_allowed'])

    def test_no_crossing_is_censored(self):
        summary, _ = evaluate(forecast(self.model()), self.session(safe=(True, True, True)))
        self.assertTrue(summary['no_crossing_grid_censored'])
        self.assertIsNone(summary['first_unsafe_transfer_cpu'])
        self.assertIsNone(summary['overprediction_beyond_observed_bracket_cpu'])

    def test_latest_attempt_selected_even_if_it_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for attempt in [1, 2]:
                folder = root / str(attempt)
                folder.mkdir()
                row = {**matrix()[0], 'config': config(), 'run_id': 'one', 'execution_commit': 'fixed', 'run_attempt': str(attempt),
                       'calibration_infrastructure_valid': True, 'validation_infrastructure_valid': attempt == 1, 'reasons': []}
                (folder / 'block.json').write_text(json.dumps(row), encoding='utf-8')
            selected, attempts = select_blocks(root)
            self.assertEqual(next(iter(selected.values())).parent.name, '2')
            self.assertEqual(len(attempts), 2)

    def test_runner_import_has_no_docker_side_effects(self):
        spec = importlib.util.spec_from_file_location('prediction_runner_test', SCRIPTS / 'prediction_run.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(module.calibrate))
        self.assertTrue(callable(module.validate))

    def test_replay_whole_frozen_block_and_reject_tampering(self):
        # Small synthetic fixture, not a runtime observation or model validation.
        tiny_rates = {**base_config(), 'checkout_rate': 2, 'advertising_rate': 3}
        with tempfile.TemporaryDirectory() as tmp, patch('prediction_primary.base_config', return_value=tiny_rates):
            root = Path(tmp)
            folder = root / 'inputs' / 'prediction-r1'
            folder.mkdir(parents=True)
            provenance = {'block_id': 'prediction-r1', 'run_id': 'synthetic', 'run_attempt': '1', 'execution_commit': 'synthetic'}
            def write(path, value):
                path.write_text(json.dumps(value, allow_nan=False), encoding='utf-8')
            def session(name, plan, started_ms):
                destination = folder / name
                destination.mkdir()
                events = []
                for stream, rate in [('checkout', 2), ('advertising', 3)]:
                    ident = 0
                    for interval in intervals(plan):
                        quota = interval['quota']
                        timeout = stream == 'checkout' and quota <= .08
                        value = 5000 if timeout else predict(self.model(), quota) if stream == 'checkout' else 25
                        for i in range(interval['seconds']*rate):
                            t = 10000 + 1000*(interval['offset'] + (i+.1)/rate)
                            row = {'stream': stream, 'id': ident, 'origin': 10000, 't': t}
                            events.extend([{**row, 'kind': 'start'}, {**row, 'kind': 'finish', 't': t+value,
                                           'success': not timeout, 'latency_ms': value, 'error_code': 1050 if timeout else None}])
                            ident += 1
                rows = score(events, [], plan)
                self.assertTrue(all(r['load_valid'] for r in rows))
                with gzip.open(destination / 'primary-events.json.gz', 'wt', encoding='utf-8') as out:
                    json.dump({'events': events, 'drops': []}, out)
                (destination / 'container-events.jsonl').write_text('', encoding='utf-8')
                result = {**provenance, 'config': config(), 'plan': plan, 'infrastructure_valid': True,
                          'comparison_valid': True, 'quality_reasons': [], 'reasons': [],
                          'started_ms': started_ms, 'windows': rows}
                write(destination / 'session.json', result)
                return rows
            observations, hashes = [], {}
            for q in matrix()[0]['calibration_order']:
                name = f'calibration-{round(q*1000):03d}'
                observations.extend(r for r in session(name, calibration_plan(q), 1) if r['stream'] == 'checkout' and r['measured'])
                for filename in ['session.json', 'primary-events.json.gz']:
                    relative = name + '/' + filename
                    hashes[relative] = digest(folder / relative)
            frozen = forecast(fit(observations))
            frozen.update(**provenance, config=config(), calibration_hashes=hashes,
                          calibration_observations=observations, frozen_ms=2)
            frozen['plan'] = validation_plan(frozen)
            frozen['point_predictions'] = [point_prediction(frozen, q) for q in frozen['plan']['quotas']]
            write(folder / 'frozen-forecast.json', frozen)
            write(folder / 'block.json', {**matrix()[0], **provenance, 'config': config(),
                  'calibration_infrastructure_valid': True, 'validation_infrastructure_valid': True,
                  'reasons': [], 'frozen_forecast_sha256': digest(folder / 'frozen-forecast.json')})
            session('validation', frozen['plan'], 3)
            analyze(root / 'inputs', root / 'output')
            result = json.loads((root / 'output' / 'summary.json').read_text())
            self.assertEqual(result['received_blocks'], 1)
            self.assertEqual(result['primary_eligible'], 1)
            self.assertEqual(result['unsafe_allowed'], 0)
            self.assertEqual(len(result['missing_blocks']), 5)
            frozen['recommended_quota'] = .08
            write(folder / 'frozen-forecast.json', frozen)
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                analyze(root / 'inputs', root / 'tampered-output')


if __name__ == '__main__':
    unittest.main()
