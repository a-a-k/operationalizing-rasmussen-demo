from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path

from bounded_resources import DESIGN, ROOT, RUNTIME, OVERLAY, VERSION, allocation, coordinates, load, matrix, sha256_file, write_json
from study import proportion


def measured_safe(m: dict) -> bool:
    checkout = m['checkout']
    return checkout['p95_ms'] is not None and checkout['p95_ms'] <= 500 and checkout['error_rate'] < 0.01


def valid_history(h: dict, maximum: int) -> bool:
    return bool(h['baseline_valid'] and h['epochs'] and all(e['valid'] for e in h['epochs']) and
                h['stop_reason'] in ('move_limit_reached', 'observed_slo_boundary',
                                     'recipient_pressure_not_binding', 'recipient_pressure_unobserved') and
                (h['stop_reason'] != 'move_limit_reached' or len(h['epochs']) == maximum))


def validate_block(block: dict, commit: str) -> None:
    design = load(ROOT / DESIGN)
    if block['study_version'] != VERSION or block['repository_commit'] != commit:
        raise ValueError('wrong version or execution commit')
    if block['cohort'] != 'campaign':
        raise ValueError('engineering and campaign cannot be pooled')
    for key, path in [('design_sha256', DESIGN), ('runtime_sha256', RUNTIME), ('overlay_sha256', OVERLAY)]:
        if block['verification'][key] != sha256_file(ROOT / path):
            raise ValueError('frozen input hash mismatch')
    expected = next((r for r in matrix(design) if r['block_id'] == block['block_id']), None)
    if expected is None or block['order'] != expected['order']:
        raise ValueError('unknown block or history order')
    if set(block['histories']) != set(block['order']):
        raise ValueError('history set differs')
    for policy, h in block['histories'].items():
        if h['policy'] != policy:
            raise ValueError('policy label differs')
        previous = h['baseline']
        if h['baseline_valid'] and (previous is None or not previous['valid'] or not measured_safe(previous)):
            raise ValueError('initially safe baseline is missing')
        if not h['baseline_valid'] and h['epochs']:
            raise ValueError('adaptation after invalid baseline')
        measurements = [(0, previous)] if previous is not None else []
        for index, e in enumerate(h['epochs'], 1):
            if e['epoch'] != index or index > design['maximum_moves']:
                raise ValueError('epoch sequence differs')
            if policy != 'control' and (previous is None or not previous['valid'] or not measured_safe(previous)
                                       or (previous['advertising'].get('throttled_period_fraction_mean') or 0) <= 0):
                raise ValueError('adaptation violates the preceding-state decision rule')
            q, memory = allocation(policy, index, design)
            if e['quotas'] != q or e['memory_bytes'] != memory:
                raise ValueError('allocation differs from the fixed policy')
            expected_coords = coordinates(design, q, memory)
            if set(e['coordinates']) != set(expected_coords) or any(
                    not math.isclose(e['coordinates'][k], v, abs_tol=1e-10) for k, v in expected_coords.items()):
                raise ValueError('allocation coordinates differ')
            for key in ('limits_start', 'limits_end'):
                if e[key]['requested_cpu'] != q or e[key]['requested_memory'] != memory:
                    raise ValueError('resource snapshot targets differ')
                if e['valid'] and not e[key]['valid']:
                    raise ValueError('resource mismatch marked valid')
            gain = e['advertising']['goodput_per_second'] - previous['advertising']['goodput_per_second']
            if not math.isclose(gain, e['goodput_change'], abs_tol=1e-10):
                raise ValueError('recipient reward change differs')
            measurements.append((index, e))
            previous = e
        for index, m in measurements:
            if m['checkout']['safe'] != measured_safe(m):
                raise ValueError('SLO label differs from external measurements')
            seconds = design['baseline_seconds'] if index == 0 else design['measurement_seconds']
            ads = m['advertising']
            if not math.isclose(ads['goodput_per_second'], ads['successful_inside_window'] / seconds, abs_tol=1e-10):
                raise ValueError('goodput differs from the native window counter')
        if h['stop_reason'] == 'move_limit_reached' and len(h['epochs']) != design['maximum_moves']:
            raise ValueError('short history mislabeled as full')
        if h['stop_reason'] == 'observed_slo_boundary' and (
                policy == 'control' or not h['epochs'] or not h['epochs'][-1]['valid'] or measured_safe(h['epochs'][-1])):
            raise ValueError('boundary stop without a valid unsafe endpoint')


def analyze(blocks: dict, commit: str) -> tuple[dict, list, list]:
    design = load(ROOT / DESIGN)
    rows, contrasts, details = [], [], {}
    witness_blocks, fully_valid = [], []
    for bid, block in sorted(blocks.items()):
        if block['block_id'] != bid:
            raise ValueError('block key differs')
        validate_block(block, commit)
        histories = block['histories']
        full_valid = all(valid_history(h, design['maximum_moves']) for h in histories.values())
        if full_valid: fully_valid.append(bid)
        details[bid] = {'fully_valid': full_valid, 'policies': {}}
        for policy in design['policies']:
            h = histories[policy]
            crossing = next((e['epoch'] for e in h['epochs'] if e['valid'] and not measured_safe(e)), None)
            details[bid]['policies'][policy] = {'baseline_valid': h['baseline_valid'],
                'valid_history': valid_history(h, design['maximum_moves']), 'epochs': len(h['epochs']),
                'first_unsafe_epoch': crossing, 'stop_reason': h['stop_reason'], 'exception': h.get('exception'),
                'baseline_reason_codes': h.get('baseline_reason_codes', []),
                'memory_cap_hit_epochs': [e['epoch'] for e in h['epochs'] if e['donor_memory_cap_hit']],
                'negative_goodput_moves': sum(e['goodput_change'] < 0 for e in h['epochs']),
                'system_failure_epochs': sum(bool(e['system_failures']) for e in h['epochs'])}
            measurements = [(0, h['baseline'])] if h['baseline'] is not None else []
            measurements.extend((e['epoch'], e) for e in h['epochs'])
            for epoch, m in measurements:
                q, memory = allocation(policy, epoch, design)
                rows.append({'block_id': bid, 'policy': policy, 'epoch': epoch, 'baseline_valid': h['baseline_valid'],
                    'valid': m['valid'], 'safe': measured_safe(m), 'p95_ms': m['checkout']['p95_ms'],
                    'error_rate': m['checkout']['error_rate'], 'ad_goodput': m['advertising']['goodput_per_second'],
                    'goodput_change': m.get('goodput_change'), 'donor_memory_cap_hit': m.get('donor_memory_cap_hit'),
                    'system_failure': bool(m.get('system_failures')), 'reasons': '|'.join(m['reason_codes']),
                    **{'cpu_' + k: v for k, v in q.items()}, **{'memory_' + k: v for k, v in memory.items()},
                    **coordinates(design, q, memory)})
        witnessed = False
        for epoch in range(1, design['maximum_moves'] + 1):
            observed = {p: next((e for e in h['epochs'] if e['epoch'] == epoch), None) for p, h in histories.items()}
            if not any(observed.values()): continue
            complete = all(m is not None for m in observed.values())
            valid = complete and all(histories[p]['baseline_valid'] and m['valid'] for p, m in observed.items())
            labels = {p: measured_safe(m) if m else None for p, m in observed.items()}
            witness = bool(valid and labels['control'] and labels['cpu'] and labels['ram'] and not labels['joint'])
            witnessed = witnessed or witness
            row = {'block_id': bid, 'epoch': epoch, 'complete_four_way_epoch': complete,
                   'valid_four_way_epoch': bool(valid), 'joint_only_unsafe_witness': witness,
                   **{p + '_safe': value for p, value in labels.items()}}
            for policy, m in observed.items():
                row[policy + '_p95_ms'] = m['checkout']['p95_ms'] if m else None
                row[policy + '_error_rate'] = m['checkout']['error_rate'] if m else None
                row[policy + '_ad_goodput'] = m['advertising']['goodput_per_second'] if m else None
            # Only compute factorial contrasts at genuinely matched, valid epochs.
            for field, getter in [('p95_interaction_ms', lambda m: m['checkout']['p95_ms']),
                                  ('error_interaction', lambda m: m['checkout']['error_rate']),
                                  ('goodput_change_interaction', lambda m: m['advertising']['goodput_per_second'] -
                                   histories[m['_policy']]['baseline']['advertising']['goodput_per_second'])]:
                values = {p: getter({**m, '_policy': p}) for p, m in observed.items()} if valid else {}
                row[field] = (values['joint'] - values['cpu'] - values['ram'] + values['control']) if values and all(
                    v is not None for v in values.values()) else None
            contrasts.append(row)
        details[bid]['observed_witness'] = witnessed
        if witnessed: witness_blocks.append(bid)
    expected = {r['block_id'] for r in matrix(design)}
    missing = sorted(expected - set(blocks))
    valid_witnesses = [bid for bid in witness_blocks if bid in fully_valid]
    report = {'study_version': VERSION, 'repository_commit': commit, 'status': 'incomplete' if missing else 'complete',
              'planned_blocks': len(expected), 'received_blocks': len(blocks), 'missing_blocks': missing,
              'fully_valid_blocks': len(fully_valid), 'fully_valid_block_ids': fully_valid,
              'observed_witness_blocks': witness_blocks,
              'witness_fraction_among_fully_valid_blocks': proportion(len(valid_witnesses), len(fully_valid)),
              'complete_four_way_epochs': sum(r['complete_four_way_epoch'] for r in contrasts),
              'valid_four_way_epochs': sum(r['valid_four_way_epoch'] for r in contrasts),
              'witness_epochs': sum(r['joint_only_unsafe_witness'] for r in contrasts),
              'histories': details, 'raw_blocks': blocks, 'analysis': design['analysis'],
              'selection_provenance': design['selection_provenance'],
              'stop_reasons': {p: dict(Counter(d['policies'][p]['stop_reason'] for d in details.values()))
                               for p in design['policies']}}
    return report, rows, contrasts


def markdown(report: dict) -> str:
    f = report['witness_fraction_among_fully_valid_blocks']
    lines = ['# Joint CPU/memory adaptation', '',
        f"Received {report['received_blocks']}/{report['planned_blocks']} fresh-runner blocks; {report['fully_valid_blocks']} have four technically valid histories.", '',
        f"Observed joint-only unsafe witnesses in {len(report['observed_witness_blocks'])} blocks. Among fully valid blocks: {f['K']}/{f['N']}; descriptive exact 95% interval: {f['clopper_pearson_95']}.", '',
        f"Complete four-way epochs: {report['complete_four_way_epochs']}; valid four-way epochs: {report['valid_four_way_epochs']}; witness epochs: {report['witness_epochs']}.", '',
        'A witness means that control, CPU-only and memory-only are safe, but the joint history is unsafe at the same observed step. Separate totals are conserved: configured CPU ceilings and configured memory ceilings, not reserved physical capacity.', '',
        'Every history is sequential. Matched step does not guarantee equal queue state. Later steps are missing after a policy stops, never imputed. This bounded-path descriptive frequency is neither detector reliability nor a preselected fixed-time causal effect. Count all alternative patterns and inspect the full trajectories.', '',
        'Advertising goodput is the measured reward. Extra allocation is not a reward, and every negative or zero reward change is retained. Memory-only transfers may offer no reward if recipient CPU is the real bottleneck; assess that limitation explicitly.', '',
        'SLO labels come only from external latency/errors. Restart/OOM is diagnostic, not an exclusion. Technical-invalid observations remain in the tables. The prior engineering histories and RAM range calibration are separate and never included here.', '',
        'Neither a simplicial complex nor downward closure has been established. An observed joint-only contrast would support context-dependent safety of the tested adaptations; it would not make balances uniquely capable of detection or beat an arbitrary multivariate rule.', '',
        'This is an engineering-informed follow-up: the RAM range and previous CPU path informed the new six-step design. No formally eligible pilot candidate was selected, no outcome proportion defines success, and prior observations are not new replications.', '',
        'See trajectory-level.csv and four-way-epochs.csv for all observations and factorial contrasts. There is no fitted warning threshold or binary scientific pass criterion.', '']
    return '\n'.join(lines)


def save(source: Path, output: Path, commit: str) -> dict:
    blocks = {}
    for path in sorted(source.rglob('block-result.json')):
        block = load(path)
        if block['block_id'] in blocks: raise ValueError('duplicate block ID')
        blocks[block['block_id']] = block
    report, rows, contrasts = analyze(blocks, commit)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'summary.json', report)
    for name, records in [('trajectory-level.csv', rows), ('four-way-epochs.csv', contrasts)]:
        with (output / name).open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]) if records else ['block_id'])
            writer.writeheader(); writer.writerows(records)
    (output / 'RESULTS.md').write_text(markdown(report), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--results-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--repository-commit', required=True)
    args = parser.parse_args()
    result = save(args.results_root, args.output_dir, args.repository_commit)
    print(json.dumps({key: value for key, value in result.items() if key != 'raw_blocks'}))
