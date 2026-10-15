import importlib.util
import sys
from pathlib import Path
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from spec import DESIGN, allocation, load, matrix
from primary import parse_events, quantile, summarize


class BoundaryTests(unittest.TestCase):
    def test_fixed_eighteen_fresh_trials(self):
        rows = matrix()
        self.assertEqual(len(rows), 18)
        self.assertEqual(len({r['trial_id'] for r in rows}), 18)
        for r in rows:
            state = allocation(r['quota'])
            self.assertAlmostEqual(sum(state['cpu'].values()), 3.4)
            self.assertAlmostEqual(state['cpu']['checkout'] + state['cpu']['ad'], .7)

    def test_vu_capacity_covers_both_timeout_paths(self):
        cfg = load(DESIGN)
        self.assertGreater(cfg['checkout_vus'], 2 * cfg['http_timeout_seconds'] * cfg['checkout_rate'])
        self.assertGreater(cfg['advertising_vus'], 2 * cfg['rpc_timeout_seconds'] * cfg['advertising_rate'])

    def test_runtime_imports_without_running_docker(self):
        spec = importlib.util.spec_from_file_location('boundary_runner', SCRIPTS / 'run.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(module.run))

    def data(self, extra=None):
        cfg = {**load(DESIGN), 'warmup_seconds': 1, 'window_seconds': 1, 'measurement_windows': 2,
               'checkout_rate': 1, 'advertising_rate': 1}
        events = []
        for name in ['checkout', 'advertising']:
            for i in range(3):
                row = {'stream': name, 'id': i, 'origin': 10000, 't': 10000 + 1000*i + 10}
                events += [{**row, 'kind': 'start'}, {**row, 'kind': 'finish', 't': row['t'] + 100,
                                                    'success': True, 'latency_ms': 100}]
        if extra:
            extra(events)
        return cfg, events

    def test_warmup_separate_and_finite_window_cohorts(self):
        cfg, events = self.data()
        rows = summarize(events, [], cfg)
        self.assertEqual(len(rows), 6)
        self.assertEqual(sum(r['measured'] for r in rows), 4)
        self.assertTrue(all(r['load_valid'] for r in rows))

    def test_late_completion_assigned_to_start_cohort(self):
        cfg, events = self.data()
        for e in events:
            if e['stream'] == 'checkout' and e['id'] == 1 and e['kind'] == 'finish':
                e.update(t=12200, latency_ms=1190)
        rows = [r for r in summarize(events, [], cfg) if r['stream'] == 'checkout']
        self.assertEqual(rows[1]['p95_ms'], 1190)
        self.assertFalse(rows[1]['slo_safe'])
        self.assertEqual(rows[1]['client_outstanding_end'], 1)
        self.assertEqual(rows[2]['client_outstanding_end'], 0)

    def test_missing_finish_is_unsuccessful_not_excluded(self):
        cfg, events = self.data()
        events = [e for e in events if not (e['stream'] == 'checkout' and e['id'] == 1 and e['kind'] == 'finish')]
        rows = [r for r in summarize(events, [], cfg) if r['stream'] == 'checkout']
        self.assertEqual(rows[1]['unfinished'], 1)
        self.assertEqual(rows[1]['error_fraction'], 1)
        self.assertFalse(rows[1]['slo_safe'])

    def test_drops_preserved_as_failure_and_load_diagnostic(self):
        cfg, events = self.data()
        rows = summarize(events, [{'stream': 'checkout', 't': 11500, 'count': 1}], cfg)
        row = next(r for r in rows if r['stream'] == 'checkout' and r['offset_seconds'] == 1)
        self.assertEqual(row['error_fraction'], .5)
        self.assertFalse(row['load_valid'])
        self.assertFalse(row['slo_safe'])

    def test_duplicate_events_rejected(self):
        cfg, events = self.data()
        with self.assertRaises(ValueError):
            summarize(events + [events[0]], [], cfg)

    def test_primary_parser_and_quantile(self):
        self.assertEqual(parse_events('noise\nCAL {"kind":"start"}\n'), [{'kind': 'start'}])
        self.assertEqual(quantile([100, 200, 300], .95), 290)


if __name__ == '__main__':
    unittest.main()
