from __future__ import annotations

import copy
import json
import math
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'geometry/scripts'))
from geometry import (CPU_BASIS, RAM_BASIS, aitchison, angle, close, difference,
                      distance, ilr, inverse_ilr, norm, perturb, product,
                      rotate_basis, share_euclidean, validate_basis)
from analyze import (DESIGN, VERSION, analyze, load_sources, results_markdown,
                     runtime_coordinates, save, synthetic_checks)


class GeometryTests(unittest.TestCase):
    def test_full_orthonormal_bases(self):
        validate_basis(CPU_BASIS)
        validate_basis(RAM_BASIS)
        with self.assertRaises(ValueError):
            validate_basis(CPU_BASIS[:1])
        with self.assertRaises(ValueError):
            validate_basis(((1.0, 0.0),))

    def test_invalid_compositions_are_not_replaced_or_imputed(self):
        for value in ([], [1], [0, 1], [-1, 2], [math.nan, 1], [math.inf, 1]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                close(value)
        with self.assertRaises(ValueError):
            ilr([1, 2], CPU_BASIS)
        with self.assertRaises(ValueError):
            perturb([1, 2], [1, 2, 3])
        with self.assertRaises(ValueError):
            difference([1], [1, 2])

    def test_isometry_inverse_and_unit_changes(self):
        x, y = (0.3, 0.3, 0.3, 0.1), (0.12, 0.3, 0.3, 0.28)
        self.assertAlmostEqual(aitchison(x, y), distance(ilr(x, CPU_BASIS), ilr(y, CPU_BASIS)), places=12)
        self.assertLess(distance(close(x), inverse_ilr(ilr(x, CPU_BASIS), CPU_BASIS)), 1e-12)
        self.assertLess(distance(ilr(x, CPU_BASIS), ilr([v * 1000 for v in x], CPU_BASIS)), 1e-12)
        self.assertAlmostEqual(share_euclidean(x, y), share_euclidean([v * 1000 for v in x], y), places=12)
        ram = (48 * 1048576, 720 * 1048576)
        self.assertLess(distance(ilr(ram, RAM_BASIS), ilr([v / 1048576 for v in ram], RAM_BASIS)), 1e-12)

    def test_equal_relative_updates_have_equal_vectors_and_norms(self):
        factors = (0.5, 1, 1, 1.5)
        backgrounds = [(0.3, 0.3, 0.3, 0.1), (0.21, 0.3, 0.3, 0.19), (0.12, 0.3, 0.3, 0.28)]
        vectors = [difference(ilr(perturb(x, factors), CPU_BASIS), ilr(x, CPU_BASIS)) for x in backgrounds]
        self.assertTrue(all(distance(vectors[0], v) < 1e-12 for v in vectors))
        euclidean = [share_euclidean(x, perturb(x, factors)) for x in backgrounds]
        self.assertGreater(max(euclidean) - min(euclidean), 0.01)

    def test_common_perturbation_invariance(self):
        x, y, p = (0.3, 0.3, 0.3, 0.1), (0.12, 0.3, 0.3, 0.28), (1, 2, 0.5, 3)
        a, b = perturb(x, p), perturb(y, p)
        self.assertAlmostEqual(aitchison(x, y), aitchison(a, b), places=12)
        self.assertNotAlmostEqual(share_euclidean(x, y), share_euclidean(a, b), places=6)

    def test_basis_rotation_preserves_distances_and_angles(self):
        alternate = rotate_basis(CPU_BASIS, 30)
        x, y, z = (0.3, 0.3, 0.3, 0.1), (0.26, 0.3, 0.3, 0.14), (0.26, 0.26, 0.3, 0.18)
        a, b = difference(ilr(y, CPU_BASIS), ilr(x, CPU_BASIS)), difference(ilr(z, CPU_BASIS), ilr(y, CPU_BASIS))
        aa, bb = difference(ilr(y, alternate), ilr(x, alternate)), difference(ilr(z, alternate), ilr(y, alternate))
        self.assertAlmostEqual(norm(a), norm(aa), places=12)
        self.assertAlmostEqual(angle(a, b), angle(aa, bb), places=12)
        self.assertIsNone(angle((0, 0), (1, 0)))
        self.assertAlmostEqual(angle((1, 0), (0, 1)), math.pi / 2, places=12)
        self.assertAlmostEqual(angle((1, 0), (-1, 0)), math.pi, places=12)

    def test_full_state_retains_change_hidden_by_one_balance(self):
        x, y = (0.3, 0.3, 0.3, 0.1), (0.3, 0.6, 0.15, 0.1)
        displacement = difference(ilr(y, CPU_BASIS), ilr(x, CPU_BASIS))
        self.assertAlmostEqual(displacement[0], 0, places=12)
        self.assertAlmostEqual(displacement[1], 0, places=12)
        self.assertGreater(abs(displacement[2]), 0.9)

    def test_subcomposition_dominance_not_distance_equality(self):
        x, y = (0.1, 0.1, 0.8), (0.1, 0.2, 0.7)
        self.assertLess(aitchison(x[:2], y[:2]), aitchison(x, y))
        self.assertGreater(share_euclidean(x[:2], y[:2]), share_euclidean(x, y))

    def test_product_weights_are_explicit_and_no_raw_units_are_added(self):
        self.assertAlmostEqual(norm(product((3, 4), (2,), {'cpu': 1, 'ram': 4})), math.sqrt(41))
        self.assertEqual(len(product((1, 2, 3), (4,), {'cpu': 1, 'ram': 1})), 4)
        with self.assertRaises(ValueError):
            product((1,), (1,), {'cpu': 0, 'ram': 1})


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design = json.loads((ROOT / DESIGN).read_text(encoding='utf-8'))
        cls.tables, cls.contracts = load_sources(ROOT, cls.design)

    def test_fixed_input_version_and_no_new_runtime(self):
        self.assertEqual(self.design['analysis_version'], VERSION)
        self.assertEqual(self.design['absolute_numerical_tolerance'], 1e-10)
        self.assertEqual(self.design['product_metric_weights'], {'cpu': 1, 'ram': 1})
        source = (ROOT / 'geometry/scripts/analyze.py').read_text(encoding='utf-8')
        self.assertNotIn('subprocess', source)
        self.assertNotIn('docker', source)

    def test_synthetic_states_never_receive_source_slo_labels(self):
        rows, checks = synthetic_checks(self.tables, self.design)
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(r['slo_safe'] is None and r['evidence_class'] == 'synthetic_property_check' for r in rows))
        self.assertGreater(checks['ram']['euclidean_max'] - checks['ram']['euclidean_min'], 0.001)

    def test_committed_runtime_labels_counts_and_coordinates_are_preserved(self):
        rows, counts, errors = runtime_coordinates(self.tables, self.contracts, self.design)
        self.assertEqual(len(rows), sum(map(len, self.tables.values())))
        self.assertEqual(counts['migration']['blocks'], 19)
        self.assertEqual(counts['migration']['policies']['drift']['histories_with_valid_unsafe'], 19)
        self.assertEqual(counts['joint']['total_windows'], 551)
        self.assertEqual(counts['joint']['policies']['joint']['histories_with_valid_unsafe'], 20)
        self.assertEqual(len(counts['joint']['witnesses']), 5)
        self.assertLess(max(errors.values()), 1e-10)
        self.assertTrue(all(r['ram_ilr_1'] is None and r['ram_d_A'] is None for r in rows if r['series'] == 'migration'))

    def test_duplicate_gaps_and_changed_labels_fail_loudly(self):
        for mutation in ('duplicate', 'gap', 'label', 'quota'):
            tables = copy.deepcopy(self.tables)
            if mutation == 'duplicate': tables['joint'].append(copy.deepcopy(tables['joint'][0]))
            if mutation == 'gap': del tables['joint'][1]
            if mutation == 'label': tables['joint'][0]['safe'] = 'False'
            if mutation == 'quota': tables['joint'][0]['cpu_checkout'] = '0.25'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                runtime_coordinates(tables, self.contracts, self.design)

    def test_mutated_source_hash_is_rejected(self):
        modified = copy.deepcopy(self.design)
        modified['sources']['joint']['observations_sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            load_sources(ROOT, modified)

    def test_reproducible_outputs_and_well_formed_native_svg(self):
        first = analyze(ROOT, '0' * 40, '0')
        self.assertEqual(first, analyze(ROOT, '0' * 40, '0'))
        with tempfile.TemporaryDirectory() as tmp:
            save(Path(tmp), *first)
            self.assertEqual({p.name for p in Path(tmp).iterdir()},
                             {'summary.json', 'metric-properties.csv', 'trajectory-coordinates.csv', 'geometry.svg', 'RESULTS.md'})
            self.assertEqual(ET.parse(Path(tmp) / 'geometry.svg').getroot().tag, '{http://www.w3.org/2000/svg}svg')
        self.assertIn('not an additional workload campaign', results_markdown(first[0]))
        with self.assertRaises(ValueError): analyze(ROOT, 'main', '0')


if __name__ == '__main__':
    unittest.main()
