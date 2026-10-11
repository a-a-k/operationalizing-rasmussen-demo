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
sys.path.insert(0, str(ROOT / 'probe6/scripts'))
import joint_resources as joint
from analyze_resources import analyze, measured_safe, save, validate_block


def measurement(seconds=60, safe=True, goodput=100, valid=True):
    return {'valid': valid, 'reason_codes': [] if valid else ['checkout_started_below_99_percent'],
            'checkout': {'safe': safe, 'p95_ms': 100 if safe else 600, 'error_rate': 0},
            'advertising': {'goodput_per_second': goodput, 'successful_inside_window': goodput * seconds,
                            'throttled_period_fraction_mean': 0.8},
            'resources': {'checkout': {'sample_count': 10, 'memory_events_increment': {}},
                          'ad': {'sample_count': 10, 'memory_events_increment': {}}},
            'workload_overlap_fraction': 0.99, 'system_failures': {}}


def limits(q, memory, hits=0):
    return {'valid': True, 'requested_cpu': q, 'requested_memory': memory,
            'raw': {name: {'container_id': name, 'pid': 123, 'running': True,
                           'cgroup_inode': '456', 'memory_events': {'max': hits}} for name in q or ['checkout']}}


def fixture(engineering=False, policy=None):
    design = joint.load(ROOT / joint.DESIGN)
    if engineering: design.update(design['engineering'])
    row = {'block_id': 'engineering-' + policy, 'order': [policy]} if engineering else joint.matrix(design)[0]
    histories = {}
    for arm in row['order']:
        baseline = measurement(design['baseline_seconds'])
        previous, epochs = baseline, []
        maximum = 2 if arm == 'joint' else design['maximum_moves']
        for index in range(1, maximum + 1):
            q, memory = joint.allocation(arm, index, design)
            e = measurement(design['measurement_seconds'], safe=not (arm == 'joint' and index == 2), goodput=100 + 10 * index)
            e.update(epoch=index, quotas=q, memory_bytes=memory, limits_start=limits(q, memory),
                     limits_end=limits(q, memory), coordinates=joint.coordinates(design, q, memory),
                     goodput_change=e['advertising']['goodput_per_second'] - previous['advertising']['goodput_per_second'],
                     donor_memory_cap_hit=arm in ('ram', 'joint'))
            epochs.append(e); previous = e
        histories[arm] = {'policy': arm, 'baseline_valid': True, 'baseline': baseline, 'epochs': epochs,
                          'stop_reason': 'observed_slo_boundary' if arm == 'joint' else 'move_limit_reached'}
    return {'study_version': joint.VERSION, 'cohort': 'engineering' if engineering else 'campaign',
            'repository_commit': 'fixture', **row, 'histories': histories,
            'verification': {key: joint.sha256_file(ROOT / path) for key, path in
                             [('design_sha256', joint.DESIGN), ('runtime_sha256', joint.RUNTIME),
                              ('overlay_sha256', joint.OVERLAY)]}}


class DesignTests(unittest.TestCase):
    def test_inputs_verify(self):
        self.assertTrue(joint.verify()['valid'])

    def test_twenty_balanced_four_history_blocks(self):
        design = joint.load(ROOT / joint.DESIGN)
        rows = joint.matrix(design)
        self.assertEqual(rows, joint.matrix(design))
        self.assertEqual(len(rows), 20)
        for position in range(4):
            self.assertEqual(Counter(r['order'][position] for r in rows),
                             {'control': 5, 'cpu': 5, 'ram': 5, 'joint': 5})

    def test_each_budget_closes_separately_and_only_requested_axis_changes(self):
        design = joint.load(ROOT / joint.DESIGN)
        for policy in design['policies']:
            for epoch in range(13):
                q, memory = joint.allocation(policy, epoch, design)
                self.assertAlmostEqual(sum(q.values()), 1)
                self.assertEqual(sum(memory.values()), 768 * 1024 ** 2)
                self.assertEqual(q['payment'], 0.30)
                self.assertEqual(q['shipping'], 0.30)
                if policy in ('control', 'ram'): self.assertEqual(q, design['reference'])
                if policy in ('control', 'cpu'): self.assertEqual(memory, design['memory_reference_bytes'])
        q, memory = joint.allocation('joint', 12, design)
        self.assertEqual(q['checkout'], 0.06)
        self.assertEqual(memory['checkout'], 64 * 1024 ** 2)

    def test_unknown_policy_and_unbounded_path_rejected(self):
        design = joint.load(ROOT / joint.DESIGN)
        for policy, epoch in [('unknown', 0), ('joint', 13), ('cpu', -1)]:
            with self.assertRaises(ValueError): joint.allocation(policy, epoch, design)

    def test_coordinates_do_not_mix_cpu_and_bytes(self):
        design = joint.load(ROOT / joint.DESIGN)
        q, memory = joint.allocation('ram', 3, design)
        coords = joint.coordinates(design, q, memory)
        self.assertEqual(coords['cpu_R_group'], 0)
        self.assertGreater(coords['ram_balance_displacement'], 0)
        scaled = {k: v * 2 for k, v in memory.items()}
        scaled_design = copy.deepcopy(design)
        scaled_design['memory_reference_bytes'] = {k: v * 2 for k, v in design['memory_reference_bytes'].items()}
        self.assertAlmostEqual(joint.coordinates(scaled_design, q, scaled)['ram_balance_displacement'],
                               coords['ram_balance_displacement'])


class ResourceTests(unittest.TestCase):
    def inspect(self, name, running=True):
        design = joint.load(ROOT / joint.DESIGN)
        return {'Id': name, 'State': {'Pid': 123 if running else 0, 'Running': running},
                'HostConfig': {'NanoCpus': int(design['reference'][name] * 1e9),
                               'Memory': design['memory_reference_bytes'].get(name, 0),
                               'MemorySwap': design['memory_reference_bytes'].get(name, 0)}}

    def cgroup(self, inspected, filename):
        config = inspected['HostConfig']
        return {'cpu.max': f"{config['NanoCpus'] // 10000} 100000", 'memory.max': str(config['Memory']),
                'memory.swap.max': '0', 'memory.current': '100', 'memory.events': 'max 0\noom 0\noom_kill 0', 'identity': '456'}[filename]

    def test_real_limit_check_reads_both_axes_and_swap(self):
        design = joint.load(ROOT / joint.DESIGN)
        with patch.object(joint.engine, 'inspect_container', side_effect=self.inspect), \
             patch.object(joint, 'read_cgroup', side_effect=self.cgroup):
            result = joint.limit_check(design['reference'], design['memory_reference_bytes'])
        self.assertTrue(result['valid'])
        self.assertEqual(result['configured_memory_total'], 768 * 1024 ** 2)

    def test_wrong_memory_or_swap_is_invalid(self):
        design = joint.load(ROOT / joint.DESIGN)
        def inspect(name):
            row = self.inspect(name)
            if name == 'checkout': row['HostConfig']['MemorySwap'] *= 2
            return row
        with patch.object(joint.engine, 'inspect_container', side_effect=inspect), \
             patch.object(joint, 'read_cgroup', side_effect=self.cgroup):
            result = joint.limit_check(design['reference'], design['memory_reference_bytes'])
        self.assertFalse(result['valid'])

    def test_stopped_system_is_not_a_resource_exclusion(self):
        design = joint.load(ROOT / joint.DESIGN)
        with patch.object(joint.engine, 'inspect_container', side_effect=lambda name: self.inspect(name, name != 'checkout')), \
             patch.object(joint, 'read_cgroup', side_effect=self.cgroup):
            result = joint.limit_check(design['reference'], design['memory_reference_bytes'])
        self.assertTrue(result['valid'])
        self.assertEqual(result['raw']['checkout']['cgroup_unavailable_reason'], 'system_container_not_stably_running')

    def test_stable_live_cgroup_read_failure_is_invalid(self):
        design = joint.load(ROOT / joint.DESIGN)
        with patch.object(joint.engine, 'inspect_container', side_effect=self.inspect), \
             patch.object(joint, 'read_cgroup', side_effect=RuntimeError('missing')):
            result = joint.limit_check(design['reference'], design['memory_reference_bytes'])
        self.assertFalse(result['valid'])

    def test_memory_events_not_differenced_across_processes(self):
        before, after = limits({}, {}, 1), limits({}, {}, 10)
        after['raw']['checkout']['pid'] = 456
        self.assertFalse(joint.memory_cap_hit(before, after, measurement(), 'checkout'))
        after['raw']['checkout']['pid'] = 123
        self.assertTrue(joint.memory_cap_hit(before, after, measurement(), 'checkout'))

    def test_update_journal_records_failed_partial_manipulation(self):
        design = joint.load(ROOT / joint.DESIGN)
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=1 if command[-1] == 'ad' else 0, stdout='', stderr='test')
        with tempfile.TemporaryDirectory() as tmp, patch.object(joint.engine, 'run', side_effect=run):
            path = Path(tmp) / 'journal.jsonl'
            with self.assertRaises(RuntimeError): joint.apply(design['reference'], design['memory_reference_bytes'], path)
            recorded = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual([c[-1] for c in calls], ['checkout', 'payment', 'shipping', 'ad'])
        self.assertEqual(recorded[-1]['exit_code'], 1)
        self.assertIn('--memory-swap', calls[0])


class ExecutionTests(unittest.TestCase):
    def execute(self, policy='joint', baseline_failure=False, restart=False):
        design = joint.load(ROOT / joint.DESIGN); design['maximum_moves'] = 3
        runtime = joint.load(ROOT / joint.RUNTIME)
        parent = {'required_running_containers': ['checkout'], 'system_under_test_containers': ['checkout']}
        state = {'checkout': {'RestartCount': 0, 'State': {'Running': True, 'OOMKilled': False}}}
        def phase(*args):
            name, seconds = args[7], args[8]
            epoch = int(name.split('-')[-1]) if name.startswith('epoch-') else 0
            m = measurement(seconds, safe=not (name == 'baseline' and baseline_failure) and
                            not (policy == 'joint' and epoch == 2), goodput=100 - epoch * 10)
            return m
        process = SimpleNamespace(pid=1, wait=lambda **kw: 0, terminate=lambda: None, kill=lambda: None)
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'GITHUB_RUN_ID': '1'}), \
             patch.object(joint, 'phase', side_effect=phase), \
             patch.object(joint, 'apply') as apply, \
             patch.object(joint, 'limit_check', side_effect=lambda q, memory: limits(q, memory)), \
             patch.object(joint.engine, 'run', return_value=SimpleNamespace(stdout='', stderr='', returncode=0)), \
             patch.object(joint.engine, 'wait_for_stack'), \
             patch.object(joint.engine, 'inspect_all', return_value=state), \
             patch.object(joint.engine, 'failures', return_value={'checkout': {'restart_delta': 1}} if restart and not baseline_failure else {}), \
             patch.object(joint.subprocess, 'Popen', return_value=process):
            # Restart diagnostics begin after baseline in this fixture.
            if restart:
                joint.engine.failures.side_effect = [{}, {'checkout': {'restart_delta': 1}}, {'checkout': {'restart_delta': 1}}]
            result = joint.history(ROOT, parent, {}, design, runtime, 'test', policy, Path(tmp) / 'history')
            recorded = joint.load(Path(tmp) / 'history/history-result.json')
        self.assertEqual(recorded['stop_reason'], result['stop_reason'])
        return result, apply.call_count

    def test_sequential_adaptation_stops_at_observed_boundary(self):
        result, calls = self.execute()
        self.assertEqual(result['stop_reason'], 'observed_slo_boundary')
        self.assertEqual(len(result['epochs']), 2)
        self.assertEqual(calls, 3)
        self.assertTrue(all(e['goodput_change'] < 0 for e in result['epochs']))

    def test_control_performs_all_sham_steps(self):
        result, calls = self.execute('control')
        self.assertEqual(len(result['epochs']), 3)
        self.assertEqual(calls, 4)
        self.assertTrue(all(e['memory_bytes'] == joint.load(ROOT / joint.DESIGN)['memory_reference_bytes'] for e in result['epochs']))

    def test_invalid_baseline_prevents_any_adaptation(self):
        result, calls = self.execute(baseline_failure=True)
        self.assertFalse(result['baseline_valid'])
        self.assertEqual(result['epochs'], [])
        self.assertEqual(calls, 1)

    def test_post_adaptation_restart_retains_measured_slo(self):
        result, _ = self.execute(restart=True)
        self.assertTrue(result['epochs'][0]['valid'])
        self.assertTrue(result['epochs'][0]['checkout']['safe'])
        self.assertTrue(result['epochs'][0]['system_failures'])


class AnalysisTests(unittest.TestCase):
    def test_joint_only_witness_and_no_imputation_after_stop(self):
        block = fixture()
        report, rows, contrasts = analyze({block['block_id']: block}, 'fixture')
        self.assertEqual(report['fully_valid_blocks'], 1)
        self.assertEqual(report['observed_witness_blocks'], [block['block_id']])
        self.assertEqual(report['witness_epochs'], 1)
        self.assertEqual(report['valid_four_way_epochs'], 2)
        self.assertEqual(len(rows), 42)
        self.assertIsNone(contrasts[2]['joint_safe'])
        self.assertIsNone(contrasts[2]['p95_interaction_ms'])
        self.assertEqual(contrasts[1]['p95_interaction_ms'], 500)

    def test_invalid_readable_endpoint_remains_but_is_not_a_witness(self):
        block = fixture()
        h = block['histories']['joint']
        h['epochs'][-1]['valid'] = False
        h['stop_reason'] = 'technical_measurement_failure'
        report, rows, contrasts = analyze({block['block_id']: block}, 'fixture')
        self.assertEqual(report['witness_epochs'], 0)
        self.assertEqual(report['fully_valid_blocks'], 0)
        self.assertFalse(contrasts[1]['joint_safe'])
        self.assertEqual(len(rows), 42)

    def test_slo_label_is_not_changed_by_oom(self):
        m = measurement(); m['system_failures'] = {'checkout': {'oom_snapshot': True}}
        self.assertTrue(measured_safe(m))

    def test_allocation_provenance_and_cross_cohort_pooling_rejected(self):
        block = fixture()
        with self.assertRaises(ValueError): validate_block(block, 'other')
        wrong = copy.deepcopy(block); wrong['histories']['joint']['epochs'][0]['memory_bytes']['ad'] += 1
        with self.assertRaises(ValueError): validate_block(wrong, 'fixture')
        with self.assertRaises(ValueError): analyze({'engineering-ram': fixture(True, 'ram')}, 'fixture')

    def test_unsafe_preceding_state_cannot_authorize_a_transfer(self):
        block = fixture()
        block['histories']['joint']['epochs'][0]['checkout'].update(safe=False, p95_ms=600)
        with self.assertRaises(ValueError): validate_block(block, 'fixture')

    def test_missing_baseline_and_short_failure_are_retained(self):
        block = fixture()
        h = block['histories']['ram']
        h.update(baseline_valid=False, baseline=None, epochs=[], stop_reason='infrastructure_exception')
        report, rows, contrasts = analyze({block['block_id']: block}, 'fixture')
        self.assertEqual(report['fully_valid_blocks'], 0)
        self.assertEqual(report['valid_four_way_epochs'], 0)
        self.assertIsNone(contrasts[0]['ram_safe'])

    def test_compact_outputs_and_duplicate_detection(self):
        block = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            joint.write_json(root / 'input/one/block-result.json', block)
            save(root / 'input', root / 'output', 'fixture')
            self.assertTrue((root / 'output/four-way-epochs.csv').exists())
            joint.write_json(root / 'input/two/block-result.json', block)
            with self.assertRaises(ValueError): save(root / 'input', root / 'duplicate', 'fixture')

    def test_engineering_gate_requires_real_binding_not_slo_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for policy in ['control', 'cpu', 'ram', 'joint']:
                block = fixture(True, policy)
                # Engineering may pass without the desired unsafe joint outcome.
                if policy == 'joint':
                    block = fixture(True, 'cpu')
                    block['block_id'], block['order'] = 'engineering-joint', ['joint']
                    h = block['histories'].pop('cpu'); h['policy'] = 'joint'
                    design = joint.load(ROOT / joint.DESIGN)
                    for e in h['epochs']:
                        q, memory = joint.allocation('joint', e['epoch'], design)
                        e.update(quotas=q, memory_bytes=memory, limits_start=limits(q, memory), limits_end=limits(q, memory),
                                 coordinates=joint.coordinates(design, q, memory))
                    block['histories'] = {'joint': h}
                joint.write_json(root / 'input' / policy / 'block-result.json', block)
            result = joint.engineering_gate(root / 'input', root / 'pass', 'fixture')
            self.assertTrue(result['passed'])
            for path in (root / 'input').rglob('block-result.json'):
                block = joint.load(path)
                for h in block['histories'].values():
                    for e in h['epochs']: e['donor_memory_cap_hit'] = False
                joint.write_json(path, block)
            result = joint.engineering_gate(root / 'input', root / 'fail', 'fixture')
            self.assertFalse(result['passed'])
            self.assertIn('memory_cap_never_observed_binding', result['reason_codes'])


if __name__ == '__main__':
    unittest.main()
