from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from geometry import (CPU_BASIS, RAM_BASIS, aitchison, angle, close, difference,
                      distance, ilr, inverse_ilr, norm, perturb, product,
                      rotate_basis, share_euclidean)

ROOT = Path(__file__).resolve().parents[2]
DESIGN = 'geometry/design-v0.1.0.json'
VERSION = 'compositional-geometry-0.1.0'


def text_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def load_sources(root: Path, design: dict) -> tuple[dict, dict]:
    tables, contracts = {}, {}
    for series, source in design['sources'].items():
        for key in ('design', 'observations'):
            if text_sha(root / source[key]) != source[key + '_sha256']:
                raise ValueError('source checksum mismatch: ' + source[key])
        contracts[series] = json.loads((root / source['design']).read_text(encoding='utf-8'))
        tables[series] = list(csv.DictReader(io.StringIO((root / source['observations']).read_text(encoding='utf-8'))))
    return tables, contracts


def flag(value: str) -> bool:
    if value not in ('True', 'False'):
        raise ValueError('invalid Boolean observation')
    return value == 'True'


def optional(value: str) -> float | None:
    if not value:
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('nonfinite observation')
    return result


def vectors(row: dict, series: str, design: dict) -> tuple[tuple, tuple]:
    prefix = 'cpu_' if series == 'joint' else ''
    cpu = tuple(float(row[prefix + part]) for part in design['cpu_parts'])
    ram = tuple(int(row['memory_' + part]) for part in design['ram_parts']) if series == 'joint' else ()
    return cpu, ram


def synthetic_checks(tables: dict, design: dict) -> tuple[list, dict]:
    selection = design['synthetic_backgrounds']
    selected = []
    for epoch in selection['epochs']:
        matches = [r for r in tables[selection['source']] if r['policy'] == selection['policy'] and int(r['epoch']) == epoch]
        if not matches:
            raise ValueError('specified geometric background is absent')
        selected.append(min(matches, key=lambda r: r['block_id']))
    rotated = rotate_basis(CPU_BASIS, design['alternate_cpu_basis_rotation_degrees'])
    rows = []
    for original in selected:
        cpu, ram = vectors(original, selection['source'], design)
        for resource, values, basis in [('cpu', cpu, CPU_BASIS), ('ram', ram, RAM_BASIS)]:
            factors, common = design['relative_update'][resource], design['common_perturbation'][resource]
            base, changed = close(values), perturb(values, factors)
            after_base, after_changed = perturb(base, common), perturb(changed, common)
            displacement = difference(ilr(changed, basis), ilr(base, basis))
            after_displacement = difference(ilr(after_changed, basis), ilr(after_base, basis))
            da, de = aitchison(base, changed), share_euclidean(base, changed)
            other = rotated if resource == 'cpu' else basis
            other_displacement = difference(ilr(changed, other), ilr(base, other))
            rows.append({'resource': resource, 'background_epoch': int(original['epoch']),
                         'background_block': original['block_id'], 'evidence_class': 'synthetic_property_check',
                         'slo_safe': None, 'base_shares': json.dumps(base), 'changed_shares': json.dumps(changed),
                         'relative_factors': json.dumps(factors), 'euclidean_shares': de, 'aitchison': da,
                         'ilr_distance': norm(displacement), 'ilr_displacement': json.dumps(displacement),
                         'common_perturbation_aitchison': aitchison(after_base, after_changed),
                         'common_perturbation_euclidean': share_euclidean(after_base, after_changed),
                         'common_perturbation_vector_error': distance(displacement, after_displacement),
                         'alternate_basis_distance_error': abs(norm(other_displacement) - da),
                         'inverse_ilr_error': distance(base, inverse_ilr(ilr(base, basis), basis))})
    details = {}
    for resource in ('cpu', 'ram'):
        rr = [r for r in rows if r['resource'] == resource]
        first_vector = json.loads(rr[0]['ilr_displacement'])
        details[resource] = {
            'aitchison_min': min(r['aitchison'] for r in rr), 'aitchison_max': max(r['aitchison'] for r in rr),
            'euclidean_min': min(r['euclidean_shares'] for r in rr), 'euclidean_max': max(r['euclidean_shares'] for r in rr),
            'equal_update_vector_max_error': max(distance(json.loads(r['ilr_displacement']), first_vector) for r in rr),
            'common_perturbation_distance_max_error': max(abs(r['aitchison'] - r['common_perturbation_aitchison']) for r in rr),
            'common_perturbation_vector_max_error': max(r['common_perturbation_vector_error'] for r in rr),
            'ilr_isometry_max_error': max(abs(r['aitchison'] - r['ilr_distance']) for r in rr),
            'alternate_basis_distance_max_error': max(r['alternate_basis_distance_error'] for r in rr),
            'inverse_ilr_max_error': max(r['inverse_ilr_error'] for r in rr)}
    # Dominance, not equality of full and reduced distances, is required here.
    x, y = (0.1, 0.1, 0.8), (0.1, 0.2, 0.7)
    details['subcomposition_example'] = {'full_aitchison': aitchison(x, y), 'subset_aitchison': aitchison(x[:2], y[:2]),
        'full_euclidean_shares': share_euclidean(x, y), 'subset_euclidean_shares': share_euclidean(x[:2], y[:2])}
    return rows, details


def runtime_coordinates(tables: dict, contracts: dict, design: dict) -> tuple[list, dict, dict]:
    output, counts = [], {}
    errors = Counter()
    alternate = rotate_basis(CPU_BASIS, design['alternate_cpu_basis_rotation_degrees'])
    for series, observations in tables.items():
        ref_cpu = tuple(contracts[series]['reference'][p] for p in design['cpu_parts'])
        ref_ram = tuple(contracts[series]['memory_reference_bytes'][p] for p in design['ram_parts']) if series == 'joint' else ()
        ref_z, ref_alt = ilr(ref_cpu, CPU_BASIS), ilr(ref_cpu, alternate)
        ref_m = ilr(ref_ram, RAM_BASIS) if ref_ram else ()
        previous, paths = {}, defaultdict(float)
        seen, unsafe_histories = set(), defaultdict(set)
        first_unsafe = {}
        policy_counts = defaultdict(Counter)
        for raw in sorted(observations, key=lambda r: (r['block_id'], r['policy'], int(r['epoch']))):
            bid, policy, epoch = raw['block_id'], raw['policy'], int(raw['epoch'])
            identity = bid, policy, epoch
            if identity in seen:
                raise ValueError('duplicate observation identity')
            seen.add(identity)
            key = bid, policy
            prev = previous.get(key)
            if (prev is None and epoch != 0) or (prev is not None and epoch != prev['epoch'] + 1):
                raise ValueError('missing baseline or internal epoch gap')
            cpu, ram = vectors(raw, series, design)
            if abs(math.fsum(cpu) - math.fsum(ref_cpu)) > 1e-10 or (ram and sum(ram) != sum(ref_ram)):
                raise ValueError('configured resource total changed')
            z, alt = ilr(cpu, CPU_BASIS), ilr(cpu, alternate)
            m = ilr(ram, RAM_BASIS) if ram else ()
            dc, dm = difference(z, ref_z), difference(m, ref_m)
            vector = product(dc, dm, design['product_metric_weights'])
            alt_vector = product(difference(alt, ref_alt), dm, design['product_metric_weights'])
            da = aitchison(ref_cpu, cpu)
            errors['cpu_isometry'] = max(errors['cpu_isometry'], abs(norm(dc) - da))
            errors['basis_distance'] = max(errors['basis_distance'], abs(norm(vector) - norm(alt_vector)))
            old_da = float(raw['cpu_d_A' if series == 'joint' else 'd_A'])
            old_balance = float(raw['cpu_R_group' if series == 'joint' else 'R_group'])
            errors['historical_cpu_distance'] = max(errors['historical_cpu_distance'], abs(da - old_da))
            errors['historical_cpu_balance'] = max(errors['historical_cpu_balance'], abs(-dc[0] - old_balance))
            if ram:
                errors['ram_isometry'] = max(errors['ram_isometry'], abs(norm(dm) - aitchison(ref_ram, ram)))
                errors['historical_ram_balance'] = max(errors['historical_ram_balance'], abs(-dm[0] - float(raw['ram_balance_displacement'])))
            latency, error_rate = optional(raw['p95_ms']), optional(raw['error_rate'])
            if error_rate is None or not 0 <= error_rate <= 1:
                raise ValueError('missing or out-of-range SLO error rate')
            safe = flag(raw['safe'])
            if safe != (latency is not None and latency <= 500 and error_rate < 0.01):
                raise ValueError('SLO label does not match the observed primary outcome')
            turn, step_length = None, 0.0
            increment = difference(vector, prev['vector']) if prev else None
            alt_increment = difference(alt_vector, prev['alt_vector']) if prev else None
            if increment is not None:
                step_length = norm(increment)
                paths[key] += step_length
                if prev['increment'] is not None:
                    turn = angle(prev['increment'], increment)
                    other_turn = angle(prev['alt_increment'], alt_increment)
                    if turn is not None and other_turn is not None:
                        errors['basis_angle'] = max(errors['basis_angle'], abs(turn - other_turn))
            previous[key] = {'epoch': epoch, 'vector': vector, 'alt_vector': alt_vector,
                             'increment': increment, 'alt_increment': alt_increment}
            valid, baseline_valid = flag(raw['valid']), flag(raw['baseline_valid'])
            output.append({'series': series, 'block_id': bid, 'policy': policy, 'epoch': epoch,
                'evidence_class': 'observed_runtime', 'valid': valid, 'baseline_valid': baseline_valid,
                'safe': safe, 'p95_ms': latency, 'error_rate': error_rate, 'ad_goodput': float(raw['ad_goodput']),
                'cpu_total': math.fsum(cpu), 'ram_total_bytes': sum(ram) if ram else None,
                **{'cpu_' + p: v for p, v in zip(design['cpu_parts'], cpu)},
                **{'ram_' + p + '_bytes': v for p, v in zip(design['ram_parts'], ram)},
                **{'cpu_ilr_' + str(i + 1): v for i, v in enumerate(z)}, 'ram_ilr_1': m[0] if m else None,
                **{'cpu_delta_ilr_' + str(i + 1): v for i, v in enumerate(dc)}, 'ram_delta_ilr_1': dm[0] if dm else None,
                'cpu_drift_to_ad': -dc[0], 'cpu_checkout_relative_loss': -dc[1],
                'ram_checkout_relative_loss': -dm[0] if dm else None,
                'cpu_d_A': da, 'ram_d_A': norm(dm) if dm else None, 'product_distance': norm(vector),
                'step_length': step_length, 'cumulative_path_length': paths[key], 'turn_angle_radians': turn})
            policy_counts[policy]['windows'] += 1
            policy_counts[policy]['invalid_windows'] += int(not valid)
            if epoch > 0:
                policy_counts[policy]['adaptation_windows'] += 1
                policy_counts[policy]['unsafe_windows'] += int(not safe)
                if valid and baseline_valid and not safe:
                    unsafe_histories[policy].add(bid)
                    first_unsafe.setdefault(key, epoch)
        counts[series] = {'total_windows': len(observations), 'blocks': len({r['block_id'] for r in observations}),
            'planned_source_blocks': contracts[series]['replications'],
            'source_blocks_without_observations': contracts[series]['replications'] - len({r['block_id'] for r in observations}),
            'policies': {p: dict(c, histories=len({r['block_id'] for r in observations if r['policy'] == p}),
                                  histories_with_valid_unsafe=len(unsafe_histories[p]),
                                  first_unsafe_epochs=dict(Counter(e for (b, pp), e in first_unsafe.items() if pp == p)))
                         for p, c in sorted(policy_counts.items())}}
    matched = defaultdict(dict)
    for r in output:
        if r['series'] == 'joint' and r['epoch'] > 0:
            matched[r['block_id'], r['epoch']][r['policy']] = r
    witness = []
    for (bid, epoch), conditions in sorted(matched.items()):
        if set(conditions) == {'control', 'cpu', 'ram', 'joint'} and all(r['valid'] and r['baseline_valid'] for r in conditions.values()):
            if all(conditions[p]['safe'] for p in ('control', 'cpu', 'ram')) and not conditions['joint']['safe']:
                witness.append({'block_id': bid, 'epoch': epoch})
    counts['joint']['witnesses'] = witness
    return output, counts, dict(errors)


def analyze(root: Path, commit: str, run_id: str) -> tuple[dict, list, list]:
    if not re.fullmatch('[0-9a-f]{40}', commit) or not re.fullmatch('[0-9]+', run_id):
        raise ValueError('execution commit and numeric run ID are required')
    design = json.loads((root / DESIGN).read_text(encoding='utf-8'))
    if design['analysis_version'] != VERSION:
        raise ValueError('analysis version mismatch')
    tables, contracts = load_sources(root, design)
    synthetic, checks = synthetic_checks(tables, design)
    runtime, counts, errors = runtime_coordinates(tables, contracts, design)
    tolerance = design['absolute_numerical_tolerance']
    failures = [key for key, value in errors.items() if value > tolerance]
    for resource in ('cpu', 'ram'):
        failures.extend(resource + ':' + k for k, v in checks[resource].items() if k.endswith('_error') and v > tolerance)
        if checks[resource]['euclidean_max'] - checks[resource]['euclidean_min'] <= tolerance:
            failures.append(resource + ':missing_euclidean_counterexample')
    subset = checks['subcomposition_example']
    if subset['subset_aitchison'] > subset['full_aitchison'] + tolerance:
        failures.append('subcomposition_dominance')
    if subset['subset_euclidean_shares'] <= subset['full_euclidean_shares']:
        failures.append('missing_euclidean_subcomposition_counterexample')
    if failures:
        raise ValueError('numerical verification failed: ' + ', '.join(failures))
    hashes = {source[k]: source[k + '_sha256'] for source in design['sources'].values() for k in ('design', 'observations')}
    for path in (DESIGN, 'geometry/scripts/geometry.py', 'geometry/scripts/analyze.py'):
        hashes[path] = text_sha(root / path)
    report = {'analysis_version': VERSION, 'execution_commit': commit, 'execution_run_id': run_id,
              'input_sha256_lf': hashes, 'numerical_checks_passed': True, 'numerical_tolerance': tolerance,
              'synthetic_properties': checks, 'runtime_verification_max_errors': errors,
              'observed_counts_separate_series': counts, 'product_metric_weights': design['product_metric_weights'],
              'evidence_boundary': design['evidence_boundary']}
    return report, synthetic, runtime


def render_svg(synthetic: list, runtime: list) -> str:
    elements = ['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="800" viewBox="0 0 1000 800" role="img">',
                '<title>Relative drift geometry and separately observed runtime outcomes</title>',
                '<desc>Top: equal synthetic relative updates have constant Aitchison magnitude across three backgrounds; Euclidean share distances vary. Bottom: a two-coordinate projection of the four-dimensional CPU and RAM state with measured safe and unsafe counts. Synthetic states have no outcome labels.</desc>',
                '<rect width="1000" height="800" fill="white"/>',
                '<style>text{font-family:Arial,sans-serif;fill:#202934}.axis{stroke:#8794a4;stroke-width:1}.grid{stroke:#e7ecf1} .small{font-size:13px}</style>']
    def label(x, y, value, size=14):
        elements.append(f'<text x="{x}" y="{y}" font-size="{size}">{html.escape(str(value))}</text>')
    label(35, 30, 'A. Synthetic property check: identical relative updates, different starting compositions', 19)
    for index, resource in enumerate(('cpu', 'ram')):
        rr = sorted((r for r in synthetic if r['resource'] == resource), key=lambda r: r['background_epoch'])
        left, top, width, height = 65 + index * 480, 90, 365, 190
        maximum = max(1.2, *(r['euclidean_shares'] / rr[0]['euclidean_shares'] for r in rr)) * 1.12
        y = lambda v: top + height * (1 - v / maximum)
        for tick in (0, 0.5, 1.0):
            elements.append(f'<line x1="{left}" y1="{y(tick):.2f}" x2="{left + width}" y2="{y(tick):.2f}" class="grid"/>')
            label(left - 30, y(tick) + 5, tick)
        label(left, top - 28, resource.upper() + ': each metric divided by its first value', 14)
        elements.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + height}" class="axis"/>')
        for j, r in enumerate(rr):
            x = left + 45 + j * 130
            for offset, field, color in [(-18, 'euclidean_shares', '#8997aa'), (8, 'aitchison', '#246eb9')]:
                v = r[field] / rr[0][field]
                elements.append(f'<rect x="{x + offset}" y="{y(v):.2f}" width="23" height="{top + height - y(v):.2f}" fill="{color}"/>')
            label(x - 27, top + height + 22, 'epoch ' + str(r['background_epoch']))
    label(80, 335, 'Gray: Euclidean distance between shares. Blue: Aitchison distance. No synthetic SLO outcomes.')
    label(35, 385, 'B. Recorded CPU/RAM adaptation: projection with observed SLO counts', 19)
    rr = [r for r in runtime if r['series'] == 'joint']
    states = defaultdict(Counter)
    for r in rr:
        key = round(r['cpu_drift_to_ad'], 10), round(r['ram_checkout_relative_loss'], 10)
        states[key]['safe' if r['safe'] else 'unsafe'] += 1
    left, top, width, height = 100, 425, 750, 265
    xmax = max(x for x, y in states) * 1.12
    ymax = max(y for x, y in states) * 1.13
    point = lambda x, y: (left + x / xmax * width, top + height * (1 - y / ymax))
    for tick in (0, 0.3, 0.6, 0.9, 1.2):
        px, py = point(tick, 0)
        elements.append(f'<line x1="{px:.2f}" y1="{top}" x2="{px:.2f}" y2="{top + height}" class="grid"/>')
        label(px - 10, top + height + 20, f'{tick:.1f}', 12)
    for tick in (0, 0.1, 0.2, 0.3, 0.4, 0.5):
        px, py = point(0, tick)
        elements.append(f'<line x1="{left}" y1="{py:.2f}" x2="{left + width}" y2="{py:.2f}" class="grid"/>')
        label(left - 30, py + 5, f'{tick:.1f}', 12)
    for policy, color in [('cpu', '#6c83a0'), ('ram', '#b28c51'), ('joint', '#658b78')]:
        unique = sorted({(r['epoch'], r['cpu_drift_to_ad'], r['ram_checkout_relative_loss']) for r in rr if r['policy'] == policy})
        coords = ' '.join(f'{a:.2f},{b:.2f}' for e, x, y in unique for a, b in [point(x, y)])
        elements.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2"/>')
    elements.append(f'<path d="M {left},{top} V {top + height} H {left + width}" fill="none" class="axis"/>')
    for (x, y), c in sorted(states.items()):
        px, py = point(x, y)
        color = '#b64038' if c['unsafe'] else '#347c58'
        elements.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="5" fill="{color}"><title>safe={c["safe"]}, unsafe={c["unsafe"]}</title></circle>')
        label(px + 9, py - 8, f'{c["safe"]}/{c["unsafe"]}', 12)
    label(95, 413, 'RAM checkout-relative loss')
    label(310, 727, 'CPU functional-to-advertising balance displacement')
    label(95, 753, 'Labels: safe/unsafe windows, including baselines. Red: any unsafe window. Repeated windows are not independent.', 13)
    label(95, 777, 'Only 2 of 4 ILR coordinates shown; distances use all 4. No fitted warning threshold or inferred SLO boundary.')
    elements.append('</svg>')
    return '\n'.join(elements) + '\n'


def results_markdown(report: dict) -> str:
    checks, counts = report['synthetic_properties'], report['observed_counts_separate_series']
    lines = ['# Geometry verification v0.1.0', '',
        'This is a post-run analysis of committed observations, not an additional workload campaign.', '',
        '## Geometric result', '',
        'The same fixed multiplicative update was applied and closed at three starting compositions drawn from recorded joint epochs 0, 3 and 6. The resulting states are synthetic and have no measured SLO labels.', '',
        '| Resource | Aitchison distance range | Euclidean share-distance range |', '| --- | --- | --- |']
    for resource in ('cpu', 'ram'):
        c = checks[resource]
        lines.append(f'| {resource.upper()} | {c["aitchison_min"]:.6f}--{c["aitchison_max"]:.6f} | {c["euclidean_min"]:.6f}--{c["euclidean_max"]:.6f} |')
    lines.extend(['', 'Aitchison magnitude and the full ILR displacement vector are invariant for equal relative updates. Common perturbation of both endpoints preserves their Aitchison distance and displacement. The alternate orthonormal CPU basis preserves full-vector distances and turning angles. All checks passed the fixed absolute numerical tolerance of 1e-10.', '',
        'These verify known properties of the implemented geometry, not newly discovered empirical laws. Euclidean share distance is a valid additive-change measure; it does not have the same invariance under multiplicative changes. Metric scales differ, so the figure compares within-metric variation, not their absolute magnitudes.', '',
        'Subcomposition dominance is checked separately. Removing components can change Aitchison distance; this analysis does not claim that all reduced distances or angles remain equal.', '',
        '## Recorded runtime observations', '',
        '| Separate series | Policy | Histories | Histories with valid unsafe epochs |', '| --- | --- | --- |'])
    for series, entry in counts.items():
        for policy, c in entry['policies'].items():
            lines.append(f'| {series} | {policy} | {c["histories"]} | {c["histories_with_valid_unsafe"]} |')
    witnesses = counts['joint']['witnesses']
    lines.extend(['', f'The joint series retains {len({w["block_id"] for w in witnesses})} blocks with a matched joint-only unsafe witness. No later stopped epochs are imputed. Every CSV observation, including its validity flags and original SLO outcome, is retained; series are not pooled. The CPU migration source contains 19 of its 20 planned blocks; the missing source block supplies no observations and is not reconstructed.', '',
        'The migration records show pressure-motivated, closed CPU transfers with measured recipient output and externally observed checkout outcomes. The CPU/RAM records show that jointly changing two resource compositions can cross the SLO at a step where each single-resource history remains safe. These support operational relevance of allocation direction and joint context, not universal predictive superiority of a metric.', '',
        '## Representation and interpretation', '',
        'CPU uses all three orthonormal coordinates: functional services versus advertising, checkout versus payment/shipping, and payment versus shipping. RAM uses checkout versus advertising. Signed drift is an ILR-coordinate difference from the respective resource reference. CPU and RAM bytes are never closed together.', '',
        'The CPU/RAM state has four coordinates. The displayed projection uses only two; full distances use all four. The product distance uses CPU=1 and RAM=1 as explicit weights. These are a descriptive convention, not uniquely implied by CoDA, physical unit conversion, statistical independence, or calibrated risk weights. No topology of a safe region is inferred.', '',
        'A geometrically appropriate relative-drift metric is not automatically a distance to an SLO boundary. Actual capacity and workload remain relevant. No threshold fitting, accuracy comparison, production prevalence, or transport of SLO labels to synthetic states is performed.', '',
        '## Files and provenance', '',
        '- [Full observed coordinates](trajectory-coordinates.csv)',
        '- [Synthetic property checks](metric-properties.csv)',
        '- [Machine-readable verification and source hashes](summary.json)',
        '- [Geometry and observed-outcome figure](geometry.svg)', '',
        f'Analysis execution: run `{report["execution_run_id"]}`, commit `{report["execution_commit"]}`. Input hashes use LF text as stored in Git. Runtime execution provenance remains in the unchanged source series.', ''])
    return '\n'.join(lines)


def save(output: Path, report: dict, synthetic: list, runtime: list) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / 'summary.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    for name, rows in [('metric-properties.csv', synthetic), ('trajectory-coordinates.csv', runtime)]:
        fields = list(dict.fromkeys(k for row in rows for k in row))
        with (output / name).open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
    (output / 'geometry.svg').write_text(render_svg(synthetic, runtime), encoding='utf-8', newline='\n')
    (output / 'RESULTS.md').write_text(results_markdown(report), encoding='utf-8', newline='\n')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--commit', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report, synthetic, runtime = analyze(ROOT, args.commit, args.run_id)
    save(args.output, report, synthetic, runtime)
    print(json.dumps({'analysis_version': VERSION, 'numerical_checks_passed': True,
                      'runtime_windows': len(runtime), 'synthetic_checks': len(synthetic)}))


if __name__ == '__main__':
    main()
