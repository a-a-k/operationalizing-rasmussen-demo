import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from diagnostic_spec import DESIGN, base_config, config, limits, matrix, plan, render, runtime_allocation
from diagnostic_run import check_snapshot, expected_limits
from diagnostic_observe import CPU_FIELDS, container_delta, host_delta
from diagnostic_analyze import analyze, contrast, pooled_plan
from prediction_primary import score


class DiagnosticTests(unittest.TestCase):
    def test_four_complete_counterbalanced_runner_blocks(self):
        rows = matrix()
        self.assertEqual(len(rows), 4)
        ids = {r['id'] for r in config()['conditions']}
        self.assertTrue(all(set(r['order']) == ids for r in rows))
        for position in range(4):
            self.assertEqual({r['order'][position] for r in rows}, ids)
        self.assertEqual(len({(a, b) for r in rows for a, b in zip(r['order'], r['order'][1:])}), 12)

    def test_exact_integer_limits_same_capacity_both_periods(self):
        self.assertEqual(limits(.14, 100000), (14000, 100000))
        self.assertEqual(limits(.14, 10000), (1400, 10000))
        with self.assertRaises(ValueError):
            limits(.14, 1000)
        with self.assertRaises(ValueError):
            limits(.14001, 10000)

    def test_rendered_limits_preserve_budget_memory_and_source(self):
        state = runtime_allocation(.14)
        source = {'services': {n: {'cpus': '.9', 'deploy': {'resources': {'limits': {'cpus': '.9'}}}}
                               for n in state['cpu']}}
        before = copy.deepcopy(source)
        rendered = render(source, config()['conditions'][1])
        self.assertEqual(source, before)
        self.assertAlmostEqual(sum(state['cpu'].values()), 3.4)
        self.assertEqual(state['cpu']['ad'], .56)
        for name, service in rendered['services'].items():
            self.assertNotIn('cpus', service)
            self.assertNotIn('cpus', service['deploy']['resources']['limits'])
            self.assertEqual(service['cpu_quota']/service['cpu_period'], state['cpu'][name])
            self.assertEqual(service['cpu_period'], 10000 if name == 'checkout' else 100000)
            self.assertEqual(service['mem_limit'], str(state['memory'][name]))

    def snapshot(self):
        condition = config()['conditions'][1]
        state = runtime_allocation(.14)
        items, actual = [], {}
        for name, (quota, period) in expected_limits(state, condition).items():
            items.append({'Name': '/'+name, 'RestartCount': 0,
                          'HostConfig': {'NanoCpus': 0, 'CpuQuota': quota, 'CpuPeriod': period,
                                         'Memory': state['memory'][name], 'MemorySwap': state['memory'][name]},
                          'State': {'Running': True, 'Pid': 123, 'OOMKilled': False}})
            actual[name] = {'cpu.max': f'{quota} {period}', 'memory.max': str(state['memory'][name]), 'memory.swap.max': '0'}
        return items, actual, state, condition

    def test_checker_requires_exact_period_and_quota_not_just_ratio(self):
        items, actual, state, condition = self.snapshot()
        self.assertTrue(check_snapshot(items, actual, state, condition)['valid'])
        actual['checkout']['cpu.max'] = '14000 100000'
        self.assertFalse(check_snapshot(items, actual, state, condition)['valid'])
        actual['checkout']['cpu.max'] = '1401 10000'
        self.assertFalse(check_snapshot(items, actual, state, condition)['valid'])

    def test_checker_rejects_nano_limits_and_missing_container(self):
        items, actual, state, condition = self.snapshot()
        items[0]['HostConfig']['NanoCpus'] = 1
        self.assertFalse(check_snapshot(items, actual, state, condition)['valid'])
        self.assertFalse(check_snapshot(items[:-1], actual, state, condition)['valid'])

    def test_post_load_oom_not_limit_exclusion_but_preload_exit_is(self):
        items, actual, state, condition = self.snapshot()
        name = items[0]['Name'].lstrip('/')
        items[0]['State'].update(Running=False, Pid=0, OOMKilled=True)
        actual[name] = {'error': 'process exited'}
        self.assertTrue(check_snapshot(items, actual, state, condition)['valid'])
        self.assertFalse(check_snapshot(items, actual, state, condition, require_running=True)['valid'])

    def test_sampler_distinguishes_steal_and_resets_counters(self):
        previous = dict.fromkeys(CPU_FIELDS, 0)
        current = dict(previous, user=20, idle=60, steal=20)
        self.assertEqual(host_delta(previous, current)['steal'], .2)
        self.assertIsNone(host_delta(current, previous))
        first = {'identity': [1, 2, 3], 'cpu': {'usage_usec': 1000, 'nr_periods': 1, 'nr_throttled': 0}}
        second = {'identity': [1, 2, 3], 'cpu': {'usage_usec': 1001000, 'nr_periods': 11, 'nr_throttled': 5}}
        self.assertEqual(container_delta(first, second, 2)['cpu_cores'], .5)
        self.assertEqual(container_delta(first, second, 2)['throttled_period_fraction'], .5)
        self.assertIsNone(container_delta(second, first, 2))
        self.assertIsNone(container_delta(first, {**second, 'identity': [2, 2, 3]}, 2))

    def test_static_windows_do_not_include_quota_updates(self):
        self.assertEqual(plan()['updates'], [])
        self.assertEqual(plan()['total_seconds'], 300)
        self.assertEqual([w['offset'] for w in plan()['intervals'] if w['measured']], [180, 240])

    def test_session_p95_pools_requests_instead_of_averaging_window_quantiles(self):
        events = []
        origin = 1000000
        for name, rate in [('checkout', 40), ('advertising', 100)]:
            for i in range(rate*300):
                t = origin+1000*i/rate
                latency = 100 if t < origin+240000 else 900
                events.extend([{'kind': 'start', 'stream': name, 'id': i, 'origin': origin, 't': t},
                               {'kind': 'finish', 'stream': name, 'id': i, 'origin': origin, 't': t+latency,
                                'latency_ms': latency, 'error_code': 0, 'success': True}])
        original = [w for w in score(events, [], plan()) if w['stream'] == 'checkout' and w['measured']]
        pooled = next(w for w in score(events, [], pooled_plan()) if w['stream'] == 'checkout' and w['measured'])
        self.assertEqual([w['p95_ms'] for w in original], [100, 900])
        self.assertEqual(pooled['p95_ms'], 900)
        self.assertNotEqual(pooled['p95_ms'], sum(w['p95_ms'] for w in original)/2)

    def test_contrast_signs_and_missing_or_censored_values(self):
        values = {'long-idle': 500, 'short-idle': 300, 'long-busy': 700, 'short-busy': 400}
        row = contrast(values)
        self.assertEqual(row['period_short_minus_long_idle_ms'], -200)
        self.assertEqual(row['load_busy_minus_idle_short_ms'], 100)
        self.assertEqual(row['interaction_ms'], -100)
        self.assertEqual(contrast({**values, 'short-busy': None}), {})

    def test_empty_aggregate_is_explicitly_incomplete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.joinpath('input').mkdir()
            result = analyze(root/'input', root/'output')
            self.assertEqual(result['received_blocks'], 0)
            self.assertEqual(result['valid_sessions'], 0)
            self.assertEqual(len(result['failures']), 4)

    def test_raw_replay_and_latest_whole_attempt_without_splicing(self):
        # Reduced-rate synthetic records exercise the scorer, not the application.
        rates = {**base_config(), 'checkout_rate': 2, 'advertising_rate': 3}
        with tempfile.TemporaryDirectory() as temporary, patch('prediction_primary.base_config', return_value=rates):
            root = Path(temporary)
            folder = root/'inputs'/'attempt-1'/'diagnostic-r1'
            folder.mkdir(parents=True)
            def write(path, value):
                path.write_text(json.dumps(value), encoding='utf-8')
            block = {**matrix()[0], 'run_attempt': 1, 'config': config(), 'complete': True,
                     'design_sha256': hashlib.sha256(DESIGN.read_bytes()).hexdigest(),
                     'execution_commit': os.getenv('GITHUB_SHA', 'synthetic')}
            write(folder/'block.json', block)
            state = runtime_allocation(config()['checkout_cpu'])
            for condition in config()['conditions']:
                destination = folder/condition['id']
                destination.mkdir()
                events = []
                for stream, rate in [('checkout', 2), ('advertising', 3)]:
                    for i in range(300*rate):
                        start = {'id': i, 'stream': stream, 'origin': 1000000, 't': 1000000+1000*(i+.1)/rate}
                        events.extend([{**start, 'kind': 'start'}, {**start, 'kind': 'finish',
                                       't': start['t']+100, 'latency_ms': 100, 'success': True, 'error_code': 0}])
                session = {'block_id': 'diagnostic-r1', 'condition': condition, 'plan': plan(),
                           'allocation': state, 'load_origin_ms': 1000000, 'generator_name': 'generator',
                           'background_name': 'background', 'comparison_valid': True, 'reasons': [],
                           'windows': score(events, [], plan())}
                write(destination/'session.json', session)
                with gzip.open(destination/'primary-events.json.gz', 'wt', encoding='utf-8') as stream:
                    json.dump({'events': events, 'drops': []}, stream)
                containers = {name: {'cpu_max': f'{q} {p}', 'delta': {'usage_usec': 200000,
                                      'sample_seconds': 2, 'nr_periods': 20, 'nr_throttled': 0, 'throttled_usec': 0}}
                              for name, (q, p) in expected_limits(state, condition).items()}
                containers['background'] = {'cpu_max': '50000 100000', 'delta': {'usage_usec': 0, 'sample_seconds': 2}}
                containers['generator'] = {'delta': {'usage_usec': 200000, 'sample_seconds': 2}}
                frames = [{'timestamp_ms': 1000000+offset*1000, 'containers': containers,
                           'host_cpu_fractions': dict.fromkeys(CPU_FIELDS, 0)} for offset in [182, 242]]
                (destination/'resource-samples.jsonl').write_text('\n'.join(json.dumps(f) for f in frames), encoding='utf-8')
                (destination/'container-events.jsonl').write_text('', encoding='utf-8')
            result = analyze(root/'inputs', root/'output')
            self.assertEqual(result['valid_sessions'], 4)
            self.assertEqual(result['complete_uncensored_blocks'], 1)
            self.assertEqual(result['contrasts'][0]['interaction_ms'], 0)
            latest = root/'inputs'/'attempt-2'/'diagnostic-r1'
            latest.mkdir(parents=True)
            write(latest/'block.json', {**block, 'run_attempt': 2, 'complete': False})
            result = analyze(root/'inputs', root/'latest-output')
            self.assertEqual(result['rescored_sessions'], 0)
            self.assertEqual(result['complete_uncensored_blocks'], 0)
            self.assertEqual(result['contrasts'][0]['run_attempt'], 2)


if __name__ == '__main__':
    unittest.main()
