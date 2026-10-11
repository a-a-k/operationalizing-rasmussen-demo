from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'probe6/scripts'))
import ram_calibration as calibration
from test_joint_resources import limits, measurement


def fixture(condition='ram-028', *, safe=False, valid=True):
    design = calibration.load(ROOT / calibration.DESIGN)
    row = next(r for r in calibration.matrix(design) if r['condition_id'] == condition)
    return {'study_version': calibration.VERSION, 'cohort': 'engineering-calibration', **row,
            'repository_commit': 'fixture', 'verification': {
                'design_sha256': calibration.joint.sha256_file(ROOT / calibration.DESIGN),
                'runtime_sha256': calibration.joint.sha256_file(ROOT / calibration.RUNTIME)},
            'point': {**row, 'cpu': design['cpu_reference'],
                      'memory_bytes': calibration.target_memory(design, row['checkout_mib']),
                      'baseline_valid': True, 'valid': valid, 'baseline': measurement(),
                      'test': measurement(safe=safe), 'reason_codes': [] if valid else ['test_limits_invalid'],
                      'memory_cap_hit': True, 'post_intervention_checkout_oom_events': [{'time_seconds': 123}],
                      'system_failures': {'checkout': {'restart_delta': 1}}}}


class CalibrationTests(unittest.TestCase):
    def test_inputs_and_fixed_nine_point_matrix(self):
        self.assertTrue(calibration.verify()['valid'])
        rows = calibration.matrix(calibration.load(ROOT / calibration.DESIGN))
        self.assertEqual(len(rows), 9)
        self.assertEqual([r['checkout_mib'] for r in rows], [256, 64, 48, 40, 36, 32, 28, 24, 20])
        self.assertEqual(len({r['condition_id'] for r in rows}), 9)

    def test_separate_ram_budget_including_sub_64_mib_targets(self):
        design = calibration.load(ROOT / calibration.DESIGN)
        for row in calibration.matrix(design):
            memory = calibration.target_memory(design, row['checkout_mib'])
            self.assertEqual(sum(memory.values()), 768 * 1024 ** 2)
            self.assertEqual(memory['checkout'], row['checkout_mib'] * 1024 ** 2)
        with self.assertRaises(ValueError): calibration.target_memory(design, 22)

    def test_failed_donor_command_does_not_skip_recipient_attempt(self):
        design = calibration.load(ROOT / calibration.DESIGN)
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            return SimpleNamespace(returncode=1 if command[-1] == 'checkout' else 0, stdout='', stderr='diagnostic')
        with tempfile.TemporaryDirectory() as tmp, patch.object(calibration.engine, 'run', side_effect=run):
            path = Path(tmp) / 'updates.jsonl'
            errors = calibration.apply_target(design['cpu_reference'], calibration.target_memory(design, 20), path)
            recorded = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual([c[-1] for c in commands], ['checkout', 'payment', 'shipping', 'ad'])
        self.assertEqual(len(errors), 1)
        self.assertEqual(len(recorded), 4)

    def test_oom_diagnostic_excludes_baseline_and_other_containers(self):
        rows = [{'Action': 'oom', 'time': stamp, 'Actor': {'ID': 'one', 'Attributes': {'name': name}}}
                for stamp, name in [(5, 'checkout'), (15, 'checkout'), (15, 'ad'), (25, 'checkout')]]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'events.jsonl'
            path.write_text('\n'.join(json.dumps(r) for r in rows))
            events = calibration.oom_events(path, '1970-01-01T00:00:10+00:00', '1970-01-01T00:00:20+00:00')
        self.assertEqual(len(events), 1)


class ExecutionTests(unittest.TestCase):
    def execute(self, *, baseline_safe=True, test_safe=False, restart=False):
        design = calibration.load(ROOT / calibration.DESIGN)
        runtime = calibration.load(ROOT / calibration.joint.RUNTIME)
        parent = {'required_running_containers': ['checkout'], 'system_under_test_containers': ['checkout']}
        state = {'checkout': {'RestartCount': 0, 'State': {'Running': True, 'OOMKilled': False}}}
        def phase(*args):
            name, seconds = args[7], args[8]
            m = measurement(seconds, safe=baseline_safe if name == 'baseline' else test_safe if name == 'test' else True)
            m['ended_at'] = '2026-10-11T23:00:00+00:00'
            return m
        process = SimpleNamespace(pid=1, wait=lambda **kw: 0, terminate=lambda: None, kill=lambda: None)
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'GITHUB_RUN_ID': '1'}), \
             patch.object(calibration.joint, 'phase', side_effect=phase), \
             patch.object(calibration, 'apply_target', return_value=[]) as apply, \
             patch.object(calibration.joint, 'limit_check', side_effect=lambda q, memory: limits(q, memory)), \
             patch.object(calibration.engine, 'run', return_value=SimpleNamespace(stdout='', stderr='', returncode=0)), \
             patch.object(calibration.engine, 'wait_for_stack'), \
             patch.object(calibration.engine, 'inspect_all', return_value=state), \
             patch.object(calibration.engine, 'failures', side_effect=[{}, {'checkout': {'restart_delta': 1}} if restart else {}]), \
             patch.object(calibration.subprocess, 'Popen', return_value=process):
            result = calibration.point(ROOT, parent, {}, design, runtime, {'condition_id': 'ram-020', 'checkout_mib': 20}, Path(tmp) / 'point')
            recorded = calibration.load(Path(tmp) / 'point/point-result.json')
        self.assertEqual(recorded['valid'], result['valid'])
        return result, apply.call_count

    def test_real_path_applies_ram_only_and_keeps_unsafe_measurement(self):
        result, calls = self.execute()
        self.assertTrue(result['valid'])
        self.assertFalse(result['test']['checkout']['safe'])
        self.assertEqual(result['cpu']['checkout'], 0.30)
        self.assertEqual(result['memory_bytes']['checkout'], 20 * 1024 ** 2)
        self.assertEqual(calls, 2)

    def test_unsafe_baseline_prevents_intervention(self):
        result, calls = self.execute(baseline_safe=False)
        self.assertFalse(result['baseline_valid'])
        self.assertIsNone(result['test'])
        self.assertEqual(calls, 1)

    def test_post_update_restart_does_not_override_safe_slo_or_exclude(self):
        result, _ = self.execute(test_safe=True, restart=True)
        self.assertTrue(result['valid'])
        self.assertTrue(result['test']['checkout']['safe'])
        self.assertTrue(result['system_failures'])


class AnalysisTests(unittest.TestCase):
    def analyze(self, record):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calibration.write_json(root / 'input/one/calibration-result.json', record)
            return calibration.analyze(root / 'input', root / 'output', 'fixture')

    def test_all_conditions_visible_with_missing_not_imputed(self):
        report = self.analyze(fixture())
        self.assertEqual(report['status'], 'incomplete')
        self.assertEqual(len(report['conditions']), 9)
        row = next(r for r in report['conditions'] if r['condition_id'] == 'ram-028')
        self.assertFalse(row['safe'])
        self.assertEqual(row['post_intervention_oom_events'], 1)
        self.assertFalse(report['automatic_follow_on_campaign'])
        self.assertIsNone(report['conditions'][0]['safe'])

    def test_technical_invalid_readable_slo_retained(self):
        report = self.analyze(fixture(valid=False))
        row = next(r for r in report['conditions'] if r['condition_id'] == 'ram-028')
        self.assertFalse(row['valid'])
        self.assertFalse(row['safe'])

    def test_wrong_provenance_and_allocation_rejected(self):
        for key, value in [('repository_commit', 'wrong'), ('cohort', 'campaign'), ('checkout_mib', 22)]:
            record = fixture(); record[key] = value
            with self.assertRaises(ValueError): self.analyze(record)
        record = fixture(); record['point']['cpu']['checkout'] = 0.12
        with self.assertRaises(ValueError): self.analyze(record)

    def test_oom_cannot_force_slo_label_unsafe(self):
        record = fixture(safe=True)
        report = self.analyze(record)
        row = next(r for r in report['conditions'] if r['condition_id'] == 'ram-028')
        self.assertTrue(row['safe'])
        record['point']['test']['checkout']['safe'] = False
        with self.assertRaises(ValueError): self.analyze(record)

    def test_duplicate_condition_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ['one', 'two']: calibration.write_json(root / 'input' / name / 'calibration-result.json', fixture())
            with self.assertRaises(ValueError): calibration.analyze(root / 'input', root / 'output', 'fixture')


if __name__ == '__main__':
    unittest.main()
