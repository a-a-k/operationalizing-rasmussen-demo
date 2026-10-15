"""Retain compact primary evidence and summarize all completed fixed trials."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil

from analyze import analyze
from spec import load, matrix


def compact_event(event):
    attrs = event.get('Actor', {}).get('Attributes', {})
    return {'Action': event['Action'], 'service': attrs.get('name'),
            'timeNano': event.get('timeNano', event.get('time', 0) * 10**9),
            'exit_code': attrs.get('exitCode')}


def archive(inputs, output):
    expected = {r['trial_id'] for r in matrix()}
    sources = {}
    for path in inputs.rglob('trial.json'):
        if not path.with_name('primary-events.json.gz').exists():
            continue
        data = load(path)
        if data['trial_id'] not in expected:
            raise ValueError('Unexpected trial')
        if data['trial_id'] in sources:
            raise ValueError('Resolve duplicate trials before archiving')
        sources[data['trial_id']] = path.parent
    if set(sources) != expected:
        raise ValueError(f'Missing primary evidence: {sorted(expected - set(sources))}')
    if (output / 'evidence').exists() or (output / 'evaluation').exists():
        raise ValueError('Refusing to overwrite an existing evidence archive')
    output.mkdir(parents=True, exist_ok=True)
    retained = output / 'evidence'
    diagnostics, hashes = [], {}
    for ident, source in sorted(sources.items()):
        target = retained / ident
        target.mkdir(parents=True)
        for name in ['trial.json', 'primary-events.json.gz', 'host-context.json',
                     'initial-quota-checks.json', 'final-quota-checks.json', 'resource-samples.jsonl.gz']:
            shutil.copyfile(source / name, target / name)
            hashes[f'{ident}/{name}'] = hashlib.sha256((target / name).read_bytes()).hexdigest()
        event_path = source / 'container-events.jsonl'
        opener = event_path.open
        if not event_path.exists():
            event_path = source / 'container-events.jsonl.gz'
            opener = lambda **kw: gzip.open(event_path, mode='rt', **kw)
        with opener(encoding='utf-8') as f:
            events = [json.loads(line) for line in f if line.strip()]
        failures = [compact_event(r) for r in events if r.get('Action') in ('oom', 'die', 'restart', 'kill')]
        inspected = load(source / 'final-container-inspect.json')
        snapshots = [{'service': r['Name'].lstrip('/'), 'restart_count': r['RestartCount'],
                      'running': r['State']['Running'], 'oom_killed': r['State']['OOMKilled']} for r in inspected]
        windows = load(source / 'trial.json')['windows']
        origin = min(w['window_start_ms'] for w in windows)
        measured_start = min(w['window_start_ms'] for w in windows if w['measured'])
        end = max(w['window_end_ms'] for w in windows)
        # Event recording stops before teardown. Separate startup events from load-time events.
        during = [r for r in failures if origin <= r['timeNano']/1e6 <= end]
        measured = [r for r in during if r['timeNano']/1e6 >= measured_start]
        diagnostics.append({'trial_id': ident, 'failure_events_all': failures,
                            'failure_events_during_load': during, 'failure_events_during_measurement': measured,
                            'final_states': snapshots})
    analyze(retained, output / 'evaluation')
    (output / 'diagnostics.json').write_text(json.dumps(diagnostics, indent=2) + '\n', encoding='utf-8')
    (output / 'evidence-sha256.json').write_text(json.dumps(hashes, indent=2) + '\n', encoding='utf-8')
    print('Retained and rescored all eighteen trials; full generator logs remain in the downloaded runtime artifacts.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    archive(args.inputs, args.output_dir)
