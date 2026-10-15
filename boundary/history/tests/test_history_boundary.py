import importlib.util
import gzip
import itertools
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import history_spec as spec
from history_analyze import analyze, select_blocks


class HistoryBoundaryTests(unittest.TestCase):
    def test_twelve_blocks_and_balanced_orders(self):
        rows = spec.matrix()
        self.assertEqual(len(rows), 12)
        for q in spec.config()['target_checkout_cpu']:
            orders = [tuple(r['order']) for r in rows if r['target_quota'] == q]
            self.assertEqual(set(orders), set(itertools.permutations(spec.config()['paths'])))
            self.assertEqual(len(orders), 6)

    def test_endpoints_match_in_all_resources(self):
        for block in spec.matrix():
            final = spec.allocation(block['target_quota'])
            for path in block['order']:
                initial = spec.initial_allocation(path, block['target_quota'])
                self.assertEqual(initial['memory'], final['memory'])
                self.assertAlmostEqual(sum(initial['cpu'].values()), 3.4)
                self.assertAlmostEqual(sum(final['cpu'].values()), 3.4)
                changed = {n for n in initial['cpu'] if initial['cpu'][n] != final['cpu'][n]}
                self.assertEqual(changed, set() if path == 'control' else {'checkout', 'ad'})
                if changed:
                    first = spec.updates(initial, final)[0]
                    self.assertLess(final['cpu'][first], initial['cpu'][first])
                else:
                    self.assertEqual(initial, final)

    def test_fixed_timing_and_capacity(self):
        cfg, load = spec.config(), spec.workload_config()
        self.assertEqual(load['warmup_seconds'] + 60*load['measurement_windows'], 490)
        self.assertLess(cfg['transition_seconds'] + cfg['transition_completion_tolerance_seconds'], cfg['post_start_seconds'])
        self.assertGreater(load['checkout_vus'], 2*load['http_timeout_seconds']*load['checkout_rate'])
        self.assertGreater(load['advertising_vus'], 2*load['rpc_timeout_seconds']*load['advertising_rate'])

    def small_data(self):
        events = []
        for name in ['checkout', 'advertising']:
            for i in range(6):
                row = {'stream': name, 'id': i, 'origin': 10000, 't': 10000 + 1000*i + 10}
                events += [{**row, 'kind': 'start'}, {**row, 'kind': 'finish', 't': row['t'] + 100,
                           'success': True, 'latency_ms': 100, 'status': 200}]
        return events

    def small_score(self, events, drops=None):
        cfg = {**spec.config(), 'transition_seconds': 2, 'post_start_seconds': 3, 'post_windows': 3, 'window_seconds': 1}
        load = {**spec.workload_config(), 'checkout_rate': 1, 'advertising_rate': 1}
        with patch.object(spec, 'config', return_value=cfg), patch.object(spec, 'workload_config', return_value=load):
            return spec.score(events, drops or [])

    def test_cohorts_align_and_transition_remains_visible(self):
        rows = self.small_score(self.small_data())
        self.assertEqual(len(rows), 12)
        self.assertEqual(sorted({r['offset_seconds'] for r in rows if r['measured']}), [3, 4, 5])
        self.assertTrue(all(r['load_valid'] for r in rows))
        self.assertEqual(len([r for r in rows if r['offset_seconds'] == 2 and not r['measured']]), 2)

    def test_pretransition_outstanding_work_retained(self):
        events = self.small_data()
        for e in events:
            if e['stream'] == 'checkout' and e['id'] == 1 and e['kind'] == 'finish':
                e.update(t=14400, latency_ms=3390)
        rows = self.small_score(events)
        first = next(r for r in rows if r['stream'] == 'checkout' and r['offset_seconds'] == 3)
        self.assertEqual(first['client_outstanding_start'], 1)
        self.assertEqual(first['p95_ms'], 100)

    def test_timeout_kept_as_failure_and_marked(self):
        events = self.small_data()
        for e in events:
            if e['stream'] == 'checkout' and e['id'] == 3 and e['kind'] == 'finish':
                e.update(t=18010, latency_ms=5000, success=False, status=0)
        row = next(r for r in self.small_score(events) if r['stream'] == 'checkout' and r['offset_seconds'] == 3)
        self.assertEqual(row['p95_ms'], 5000)
        self.assertEqual(row['error_fraction'], 1)
        self.assertEqual(row['near_http_deadline_finishes'], 1)
        self.assertEqual(row['status_zero_finishes'], 1)
        self.assertFalse(row['slo_safe'])

    def test_missing_finish_is_not_removed(self):
        events = [e for e in self.small_data() if not (e['stream'] == 'checkout' and e['id'] == 3 and e['kind'] == 'finish')]
        row = next(r for r in self.small_score(events) if r['stream'] == 'checkout' and r['offset_seconds'] == 3)
        self.assertEqual(row['unfinished'], 1)
        self.assertEqual(row['error_fraction'], 1)
        self.assertFalse(row['slo_safe'])

    def test_p95_difference_not_inferred_from_slo_agreement(self):
        rows = [r for r in self.small_score(self.small_data()) if r['stream'] == 'checkout' and r['measured']]
        a, b = {**rows[0], 'p95_ms': 400}, {**rows[0], 'p95_ms': 300}
        row = spec.contrast(a, b, {}, 'decrease-control')
        self.assertTrue(row['same_slo_label'])
        self.assertFalse(row['within_50_ms'])
        self.assertEqual(row['p95_difference_ms'], 100)

    def test_latest_block_not_best_outcome_selected_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for attempt in [1, 2]:
                folder = root / str(attempt)
                folder.mkdir()
                row = {**spec.matrix()[0], 'config': spec.config(), 'run_id': 'one', 'execution_commit': 'fixed',
                       'run_attempt': str(attempt), 'infrastructure_valid': attempt == 1, 'paths': [], 'reasons': []}
                (folder / 'block.json').write_text(json.dumps(row), encoding='utf-8')
            selected, attempts = select_blocks(root)
            self.assertEqual(next(iter(selected.values())).parent.name, '2')
            self.assertEqual(len(attempts), 2)

    def test_saved_events_rescored_and_invalid_load_remains_visible(self):
        events = self.small_data()
        windows = spec.score(events, [])
        block = {**spec.matrix()[0], 'config': spec.config(), 'run_id': 'one', 'execution_commit': 'fixed',
                 'run_attempt': '1', 'infrastructure_valid': True, 'paths': [], 'reasons': []}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'inputs'
            source.mkdir()
            (source / 'block.json').write_text(json.dumps(block), encoding='utf-8')
            for position, name in enumerate(block['order'], 1):
                path = source / name
                path.mkdir()
                trial = {**block, 'path': name, 'position': position, 'workload_config': spec.workload_config(),
                         'comparison_valid': False, 'quality_reasons': ['load_delivery_mismatch'],
                         'windows': windows, 'transition': None}
                (path / 'trial.json').write_text(json.dumps(trial), encoding='utf-8')
                (path / 'container-events.jsonl').write_text('', encoding='utf-8')
                with gzip.open(path / 'primary-events.json.gz', 'wt', encoding='utf-8') as stream:
                    json.dump({'events': events, 'drops': []}, stream)
            analyze(source, root / 'result')
            summary = json.loads((root / 'result/summary.json').read_text())
            self.assertEqual(summary['received_blocks'], 1)
            self.assertEqual(summary['comparison_valid_paths'], 0)
            self.assertEqual(len(summary['contrasts']), 15)
            self.assertTrue(all(r['usable_pairs'] == 0 for r in summary['contrasts']))
            self.assertTrue((root / 'result/windows.csv').exists())

    def test_runtime_import_without_docker(self):
        module = importlib.util.spec_from_file_location('history_runtime_test', SCRIPTS / 'history_run.py')
        loaded = importlib.util.module_from_spec(module)
        module.loader.exec_module(loaded)
        self.assertTrue(callable(loaded.run_block))

    def test_live_transition_reduces_donor_first_and_control_is_noop(self):
        import history_run
        final = spec.allocation(.12)
        with tempfile.TemporaryDirectory() as tmp:
            for path in ['decrease', 'recover', 'control']:
                initial = spec.initial_allocation(path, .12)
                fake_result = unittest.mock.Mock(returncode=0, stderr='')
                with patch.object(history_run.time, 'time', return_value=180), patch.object(history_run, 'command', return_value=fake_result) as command:
                    result = history_run.transition(initial, final, 0, Path(tmp) / (path + '.json'))
                self.assertTrue(result['timing_valid'])
                self.assertEqual(command.call_count, 2)
                self.assertEqual([c.args[0][-1] for c in command.call_args_list], spec.updates(initial, final))
                self.assertEqual({r['service']: r['cpu'] for r in result['updates']}, {'checkout': .12, 'ad': .58})

    def test_missed_transition_timing_is_flagged_not_rescheduled(self):
        import history_run
        with tempfile.TemporaryDirectory() as tmp, patch.object(history_run.time, 'time', return_value=183), patch.object(history_run, 'command', return_value=unittest.mock.Mock(returncode=0, stderr='')):
            result = history_run.transition(spec.allocation(.30), spec.allocation(.12), 0, Path(tmp) / 'transition.json')
        self.assertFalse(result['timing_valid'])
        self.assertEqual(result['planned_ms'], 180000)


if __name__ == '__main__':
    unittest.main()
