from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path

from drift import DESIGN, OVERLAY, ROOT, RUNTIME, VERSION, features, load, matrix, proposal, sha256_file, write_json


def measured_safe(measurement: dict) -> bool:
    checkout = measurement['checkout']
    safe = checkout['p95_ms'] is not None and checkout['p95_ms'] <= 500 and checkout['error_rate'] < 0.01
    if checkout['safe'] is not safe:
        raise ValueError('SLO label differs from the primary measurements')
    return safe


def valid_history(h: dict) -> bool:
    return bool(h['baseline_valid'] and all(e['valid'] for e in h['epochs']) and
                h['stop_reason'] in {'observed_slo_boundary', 'recipient_pressure_not_binding', 'move_limit_reached'})


def analyze(blocks: dict, commit: str) -> tuple[dict, list[dict], list[dict]]:
    design = load(ROOT / DESIGN)
    expected = {r['block_id']: r for r in matrix(design)}
    if set(blocks) - set(expected):
        raise ValueError('unexpected block IDs')
    hashes = {'design_sha256': sha256_file(ROOT / DESIGN), 'runtime_sha256': sha256_file(ROOT / RUNTIME),
              'overlay_sha256': sha256_file(ROOT / OVERLAY)}
    rows, pairs, histories = [], [], {}
    for bid, spec in expected.items():
        block = blocks.get(bid)
        if block is None:
            continue
        if block['block_id'] != bid or block['study_version'] != VERSION or block['repository_commit'] != commit or block['order'] != spec['order']:
            raise ValueError(f'block provenance differs: {bid}')
        if any(block['verification'].get(k) != v for k, v in hashes.items()):
            raise ValueError(f'block input hashes differ: {bid}')
        if set(block['histories']) != {'drift', 'control'}:
            raise ValueError('both histories must be recorded, including failed histories')
        histories[bid] = {}
        for policy, h in block['histories'].items():
            if h['policy'] != policy:
                raise ValueError('policy label differs')
            if h['stop_reason'] == 'move_limit_reached' and len(h['epochs']) != design['maximum_moves']:
                raise ValueError('truncated history labeled move-limit completion')
            if h['stop_reason'] == 'observed_slo_boundary' and (not h['epochs'] or
                    not h['epochs'][-1]['valid'] or measured_safe(h['epochs'][-1])):
                raise ValueError('boundary stop without a valid unsafe final epoch')
            q = dict(design['reference'])
            previous = h['baseline']
            all_measurements = [(0, q, previous)] if previous is not None else []
            for index, epoch in enumerate(h['epochs'], 1):
                if index > design['maximum_moves'] or epoch['epoch'] != index:
                    raise ValueError('epoch sequence differs')
                expected_donor = None
                if policy == 'drift':
                    if not previous['valid'] or not measured_safe(previous) or (previous['advertising'].get('throttled_period_fraction_mean') or 0) <= 0:
                        raise ValueError('transfer violates the observable decision rule')
                    q, expected_donor = proposal(q, index, design)
                if epoch['quotas'] != q or epoch['donor'] != expected_donor:
                    raise ValueError('allocation differs from the policy')
                coords = features(design, q)
                if any(not math.isclose(coords[k], epoch['coordinates'][k], abs_tol=1e-10) for k in coords):
                    raise ValueError('coordinates differ from the recorded allocation')
                change = epoch['advertising']['goodput_per_second'] - previous['advertising']['goodput_per_second']
                if not math.isclose(change, epoch['goodput_change'], abs_tol=1e-10):
                    raise ValueError('goodput change differs')
                all_measurements.append((index, dict(q), epoch))
                previous = epoch
            crossing = next((e for e in h['epochs'] if e['valid'] and not measured_safe(e)), None)
            gains = [e['goodput_change'] for e in h['epochs']]
            histories[bid][policy] = {'baseline_valid': h['baseline_valid'], 'valid_history': valid_history(h),
                'epochs': len(h['epochs']), 'stop_reason': h['stop_reason'],
                'baseline_reasons': h.get('baseline_reason_codes', []),
                'exception': h.get('exception'), 'diagnostic_errors': h.get('diagnostic_errors', []),
                'first_unsafe_epoch': crossing['epoch'] if crossing else None,
                'positive_goodput_moves': sum(g > 0 for g in gains), 'zero_goodput_moves': sum(g == 0 for g in gains),
                'negative_goodput_moves': sum(g < 0 for g in gains),
                'system_failure_epochs': sum(bool(e['system_failures']) for e in h['epochs'])}
            for index, quotas, m in all_measurements:
                ads = m['advertising']
                seconds = design['baseline_seconds'] if index == 0 else design['measurement_seconds']
                if not math.isclose(ads['goodput_per_second'], ads['successful_inside_window'] / seconds, abs_tol=1e-10):
                    raise ValueError('goodput differs from the window counter')
                rows.append({'block_id': bid, 'policy': policy, 'epoch': index,
                    'baseline_valid': h['baseline_valid'], 'valid': m['valid'], 'safe': measured_safe(m),
                    'p95_ms': m['checkout']['p95_ms'], 'error_rate': m['checkout']['error_rate'],
                    'ad_goodput': ads['goodput_per_second'], 'ad_successes': ads['successful_inside_window'],
                    'ad_throttling': ads['throttled_period_fraction_mean'],
                    'workload_overlap_fraction': m['workload_overlap_fraction'],
                    'goodput_change': m.get('goodput_change'), 'donor': m.get('donor'),
                    'system_failure': bool(m.get('system_failures')),
                    'reasons': '|'.join(m['reason_codes']), **quotas, **features(design, quotas)})
        drift, control = block['histories']['drift'], block['histories']['control']
        for left, right in zip(drift['epochs'], control['epochs']):
            valid = drift['baseline_valid'] and control['baseline_valid'] and left['valid'] and right['valid']
            lp, rp = left['checkout']['p95_ms'], right['checkout']['p95_ms']
            pairs.append({'block_id': bid, 'epoch': left['epoch'], 'valid_pair': valid,
                'drift_safe': measured_safe(left), 'control_safe': measured_safe(right),
                'latency_difference_ms': lp - rp if lp is not None and rp is not None else None,
                'goodput_change_difference':
                    (left['advertising']['goodput_per_second'] - drift['baseline']['advertising']['goodput_per_second']) -
                    (right['advertising']['goodput_per_second'] - control['baseline']['advertising']['goodput_per_second']),
                'drift_goodput': left['advertising']['goodput_per_second'],
                'control_goodput': right['advertising']['goodput_per_second']})
    crossings = []
    for bid, policies in histories.items():
        epoch = policies['drift']['first_unsafe_epoch']
        p = next((p for p in pairs if p['block_id'] == bid and p['epoch'] == epoch), None)
        crossings.append({'block_id': bid, 'drift_crossing': epoch, 'contrast': p})
    missing = sorted(set(expected) - set(blocks))
    report = {'study_version': VERSION, 'repository_commit': commit, 'status': 'incomplete' if missing else 'complete',
        'planned_blocks': len(expected), 'received_blocks': len(blocks), 'missing_blocks': missing,
        'analysis': design['analysis'], 'histories': histories, 'crossings': crossings,
        'counts': {policy: {'baseline_valid': sum(h[policy]['baseline_valid'] for h in histories.values()),
            'valid_histories': sum(h[policy]['valid_history'] for h in histories.values()),
            'histories_with_unsafe_epoch': sum(h[policy]['first_unsafe_epoch'] is not None for h in histories.values()),
            'stop_reasons': dict(Counter(h[policy]['stop_reason'] for h in histories.values()))}
                   for policy in ['drift', 'control']}}
    return report, rows, pairs


def markdown(report: dict) -> str:
    text = ['# Adaptive boundary migration', '',
        'The tested mechanism is a reward-seeking sequence under a fixed configured CPU budget, not a static detector contest or a validation of human adaptation.', '',
        f"Received {report['received_blocks']}/{report['planned_blocks']} paired runners. Missing: {report['missing_blocks']}.", '',
        '| History | Initially valid | Valid histories | Histories with a valid unsafe epoch |',
        '| --- | ---: | ---: | ---: |']
    for policy, c in report['counts'].items():
        text.append(f"| {policy} | {c['baseline_valid']} | {c['valid_histories']} | {c['histories_with_unsafe_epoch']} |")
    text.extend(['', '## Descriptive contrasts at the first observed drift crossing', '',
        'These epochs are selected by the observed drift outcome. They are not a fixed-time causal estimand or a pass criterion.', '',
        '| Runner | Crossing epoch | Matched control safe | Valid pair | Goodput change difference (responses/s) |',
        '| --- | ---: | --- | --- | ---: |'])
    for c in report['crossings']:
        p = c['contrast']
        gain = f"{p['goodput_change_difference']:.2f}" if p else 'NA'
        text.append(f"| {c['block_id']} | {c['drift_crossing']} | {p['control_safe'] if p else 'NA'} | {p['valid_pair'] if p else 'NA'} | {gain} |")
    text.extend(['', '## Interpretation', '',
        'Evidence for the constructed mechanism requires actual recipient output gains and deterioration of checkout relative to the unchanged control. Neither gain nor crossing is assumed. All negative/zero moves, control failures, short histories and invalid measurements remain visible.', '',
        'A monotone path is not evidence that a balance uniquely detects the crossing: a suitably chosen component threshold can encode that same path. Balance is reported as an interpretable cumulative allocation coordinate; no tuned warning rule, general superiority, monetary benefit or human behavior is claimed.', '',
        'Full measured trajectories and matched contrasts are in trajectory-level.csv and paired-epochs.csv. Native counters, checkout raw streams, quota checks, container events and cgroup observations are retained in the execution artifacts.', ''])
    return '\n'.join(text)


def save(source: Path, output: Path, commit: str) -> dict:
    blocks = {}
    for path in sorted(source.rglob('block-result.json')):
        block = load(path)
        bid = block['block_id']
        if bid in blocks:
            raise ValueError('duplicate block ID')
        blocks[bid] = block
    report, rows, pairs = analyze(blocks, commit)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'summary.json', report)
    for name, records in [('trajectory-level.csv', rows), ('paired-epochs.csv', pairs)]:
        with (output / name).open('w', newline='', encoding='utf-8') as stream:
            fields = list(records[0]) if records else ['block_id']
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader(); writer.writerows(records)
    (output / 'RESULTS.md').write_text(markdown(report), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--results-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--repository-commit', required=True)
    args = parser.parse_args()
    print(json.dumps(save(args.results_root, args.output_dir, args.repository_commit)['counts']))
