from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'probe5/scripts'))
import drift
from analyze_migration import analyze, measured_safe, save


def measurement(*, safe=True, goodput=100, valid=True, throttling=0.8):
    return {'valid': valid, 'reason_codes': [] if valid else ['checkout_started_below_99_percent'],
            'checkout': {'safe': safe, 'p95_ms': 100 if safe else 600, 'error_rate': 0},
            'advertising': {'goodput_per_second': goodput, 'successful_inside_window': goodput * 60,
                            'throttled_period_fraction_mean': throttling},
            'workload_overlap_fraction': 0.99, 'system_failures': {}}


def fixture():
    design = drift.load(ROOT / drift.DESIGN)
    row = drift.matrix(design)[0]
    histories = {}
    for policy in ['drift', 'control']:
        q = dict(design['reference'])
        baseline = measurement()
        baseline['advertising']['successful_inside_window'] = 100 * 90
        previous, epochs = baseline, []
        for index in range(1, 3 if policy == 'drift' else design['maximum_moves'] + 1):
            donor = None
            if policy == 'drift':
                q, donor = drift.proposal(q, index, design)
            m = measurement(safe=not (policy == 'drift' and index == 2), goodput=100 + index * 10)
            m.update(epoch=index, donor=donor, quotas=dict(q), coordinates=drift.features(design, q),
                     goodput_change=m['advertising']['goodput_per_second'] - previous['advertising']['goodput_per_second'])
            epochs.append(m); previous = m
        histories[policy] = {'policy': policy, 'baseline_valid': True, 'baseline': baseline, 'epochs': epochs,
                             'stop_reason': 'observed_slo_boundary' if policy == 'drift' else 'move_limit_reached'}
    return {'study_version': drift.VERSION, 'repository_commit': 'fixture', **row, 'histories': histories,
            'verification': {key: drift.sha256_file(ROOT / path) for key, path in
                             [('design_sha256', drift.DESIGN), ('runtime_sha256', drift.RUNTIME),
                              ('overlay_sha256', drift.OVERLAY)]}}


class DesignTests(unittest.TestCase):
    def test_fixed_inputs_verify(self):
        self.assertTrue(drift.verify()['valid'])

    def test_twenty_deterministic_paired_runners_and_balanced_order(self):
        design = drift.load(ROOT / drift.DESIGN)
        rows = drift.matrix(design)
        self.assertEqual(rows, drift.matrix(design))
        self.assertEqual(len(rows), 20)
        self.assertEqual(Counter(r['order'][0] for r in rows), {'drift': 10, 'control': 10})

    def test_each_move_changes_exactly_one_donor_and_the_recipient(self):
        design = drift.load(ROOT / drift.DESIGN)
        q = design['reference']
        for index in range(1, 19):
            changed, donor = drift.proposal(q, index, design)
            self.assertEqual({k for k in q if q[k] != changed[k]}, {donor, 'ad'})
            self.assertAlmostEqual(changed[donor], q[donor] - 0.04)
            self.assertAlmostEqual(sum(changed.values()), 1)
            self.assertGreaterEqual(min(changed.values()), 0.05)
            q = changed
        self.assertEqual(q, {'checkout': 0.06, 'payment': 0.06, 'shipping': 0.06, 'ad': 0.82})

    def test_controller_uses_observed_safety_and_binding_pressure(self):
        self.assertEqual(drift.decision(measurement()), 'transfer')
        self.assertEqual(drift.decision(measurement(safe=False)), 'observed_slo_boundary')
        self.assertEqual(drift.decision(measurement(valid=False)), 'technical_measurement_failure')
        self.assertEqual(drift.decision(measurement(throttling=0)), 'recipient_pressure_not_binding')
        self.assertEqual(drift.decision(measurement(throttling=None)), 'recipient_pressure_unobserved')

    def test_negative_reward_is_not_a_deletion_or_stopping_rule(self):
        m = measurement(goodput=10)
        m['goodput_change'] = -50
        self.assertEqual(drift.decision(m), 'transfer')

    def test_static_generator_bound(self):
        design = drift.load(ROOT / drift.DESIGN)
        runtime = drift.load(ROOT / drift.RUNTIME)
        self.assertGreaterEqual(runtime['workload']['pre_allocated_vus'],
                                1.25 * design['checkout_rate'] * 2 * design['http_timeout_seconds'])


class MeasurementTests(unittest.TestCase):
    def summary(self):
        metrics = {f'ad_window_{key}': {'values': {'count': value}}
                   for key, value in [('attempts', 20), ('completions', 18), ('successes', 16)]}
        metrics['ad_connection_failures'] = {'values': {'count': 2}}
        metrics['ad_window_start_ms'] = {'values': {'min': 1000}}
        return {'metrics': metrics}

    def test_reward_is_successful_in_window_goodput(self):
        measured = drift.summarize_ads(self.summary(), 60)
        self.assertEqual(measured['goodput_per_second'], 16 / 60)
        self.assertEqual(measured['window_ended_ms'], 61000)

    def test_impossible_or_missing_advertising_counters_rejected(self):
        s = self.summary(); s['metrics']['ad_window_successes']['values']['count'] = 19
        with self.assertRaises(ValueError):
            drift.summarize_ads(s, 60)
        with self.assertRaises(KeyError):
            drift.summarize_ads({'metrics': {}}, 60)

    def test_missing_pressure_is_not_silently_replaced_with_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'samples.jsonl'
            rows = [{'timestamp': str(i), 'containers': {'ad': {'delta':
                    {'cpu_cores': 0.1, 'throttled_period_fraction': t}}}}
                    for i, t in enumerate([None, 0.8, None])]
            p.write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
            observed = drift.ad_resource_samples(p, '0', '2')
            self.assertEqual(observed['throttled_period_fraction_mean'], 0.8)

    def test_slo_is_not_overridden_by_restart(self):
        m = measurement(); m['system_failures'] = {'checkout': {'oom_snapshot': True}}
        self.assertTrue(measured_safe(m))


class ExecutionPathTests(unittest.TestCase):
    def execute(self, policy='drift', *, baseline_failure=False, negative_gain=False):
        design = drift.load(ROOT / drift.DESIGN); design['maximum_moves'] = 3
        runtime = drift.load(ROOT / drift.RUNTIME)
        parent = {'required_running_containers': ['checkout'], 'system_under_test_containers': ['checkout']}
        before = {'checkout': {'RestartCount': 0, 'State': {'Running': True, 'OOMKilled': False}}}
        def phase(*args, **kwargs):
            name = args[7]
            is_epoch = name.startswith('epoch-')
            index = int(name.split('-')[-1]) if is_epoch else 0
            safe = not (name == 'baseline' and baseline_failure) and not (policy == 'drift' and index == 2)
            return measurement(safe=safe, goodput=100 + (-10 if negative_gain else 10) * index)
        process = SimpleNamespace(pid=1, wait=lambda **kw: 0, terminate=lambda: None, kill=lambda: None)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict('os.environ', {'GITHUB_RUN_ID': '1'}), \
             patch.object(drift, 'concurrent_phase', side_effect=phase), \
             patch.object(drift.engine, 'run', return_value=SimpleNamespace(stdout='', stderr='', returncode=0)), \
             patch.object(drift.engine, 'wait_for_stack'), \
             patch.object(drift.engine, 'inspect_all', return_value=before), \
             patch.object(drift.engine, 'apply') as apply, \
             patch.object(drift.engine, 'quota_check', side_effect=lambda q: {'valid': True, 'effective': q}), \
             patch.object(drift.subprocess, 'Popen', return_value=process):
            result = drift.history(ROOT, parent, {}, design, runtime, 'test', policy, Path(tmp) / 'history')
            self.assertEqual(drift.load(Path(tmp) / 'history/history-result.json')['stop_reason'], result['stop_reason'])
            return result, apply.call_count

    def test_real_execution_path_stops_after_observed_crossing(self):
        result, calls = self.execute()
        self.assertEqual(result['stop_reason'], 'observed_slo_boundary')
        self.assertEqual(len(result['epochs']), 2)
        self.assertEqual(calls, 3)

    def test_control_keeps_reference_allocation(self):
        result, calls = self.execute('control')
        self.assertEqual(len(result['epochs']), 3)
        self.assertEqual(calls, 4)
        self.assertTrue(all(e['quotas'] == drift.load(ROOT / drift.DESIGN)['reference'] for e in result['epochs']))

    def test_no_adaptation_after_unsafe_baseline(self):
        result, calls = self.execute(baseline_failure=True)
        self.assertEqual(result['stop_reason'], 'baseline_invalid')
        self.assertEqual(result['epochs'], [])
        self.assertEqual(calls, 1)

    def test_real_path_retains_negative_reward_moves(self):
        result, _ = self.execute(negative_gain=True)
        self.assertEqual(len(result['epochs']), 2)
        self.assertTrue(all(e['goodput_change'] < 0 for e in result['epochs']))


class AnalysisTests(unittest.TestCase):
    def test_paired_crossing_and_time_control(self):
        b = fixture(); report, rows, pairs = analyze({b['block_id']: b}, 'fixture')
        self.assertEqual(report['counts']['drift']['histories_with_unsafe_epoch'], 1)
        self.assertEqual(report['counts']['control']['histories_with_unsafe_epoch'], 0)
        self.assertEqual(len(rows), 22)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(report['crossings'][0]['contrast']['goodput_change_difference'], 0)
        self.assertEqual(report['status'], 'incomplete')

    def test_wrong_commit_and_allocation_rejected(self):
        b = fixture()
        with self.assertRaises(ValueError): analyze({b['block_id']: b}, 'wrong')
        b['histories']['drift']['epochs'][0]['quotas']['ad'] = 0.5
        with self.assertRaises(ValueError): analyze({b['block_id']: b}, 'fixture')

    def test_controller_cannot_move_after_an_unsafe_state(self):
        b = fixture(); p = b['histories']['drift']['epochs'][0]
        p['checkout'].update(safe=False, p95_ms=600)
        with self.assertRaises(ValueError): analyze({b['block_id']: b}, 'fixture')

    def test_technical_invalid_readable_outcomes_remain_visible(self):
        b = fixture(); p = b['histories']['drift']['epochs'][1]
        p.update(valid=False, reason_codes=['checkout_started_below_99_percent'])
        b['histories']['drift']['stop_reason'] = 'technical_measurement_failure'
        report, rows, pairs = analyze({b['block_id']: b}, 'fixture')
        self.assertEqual(len(rows), 22)
        self.assertFalse(pairs[1]['valid_pair'])
        self.assertEqual(report['counts']['drift']['valid_histories'], 0)

    def test_truncated_control_cannot_be_labeled_complete(self):
        b = fixture(); b['histories']['control']['epochs'] = b['histories']['control']['epochs'][:2]
        with self.assertRaises(ValueError): analyze({b['block_id']: b}, 'fixture')

    def test_duplicate_detection_and_compact_artifact(self):
        b = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drift.write_json(root / 'input/one/block-result.json', b)
            save(root / 'input', root / 'result', 'fixture')
            self.assertTrue((root / 'result/trajectory-level.csv').exists())
            drift.write_json(root / 'input/two/block-result.json', b)
            with self.assertRaises(ValueError): save(root / 'input', root / 'result-two', 'fixture')


if __name__ == '__main__':
    unittest.main()
