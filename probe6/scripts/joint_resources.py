from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'probe5/scripts'))
import drift as migration
from study import balance, features, load, project_name, sha256_file, write_json

engine = migration.engine
VERSION = 'joint-resource-migration-0.1.0'
DESIGN = 'probe6/design-v0.1.0.json'
RUNTIME = 'probe6/runtime-v0.1.0.json'
OVERLAY = 'probe6/memory-v0.1.0.yaml'


def matrix(design: dict) -> list[dict]:
    ids = [f'resources-{i:03d}' for i in range(1, design['replications'] + 1)]
    salt = design['randomization_salt']
    ranked = sorted(ids, key=lambda s: hashlib.sha256(f'{salt}:{s}'.encode()).digest())
    base = sorted(design['policies'], key=lambda s: hashlib.sha256(f'{salt}:policy:{s}'.encode()).digest())
    return [{'block_id': bid, 'order': base[ranked.index(bid) % 4:] + base[:ranked.index(bid) % 4]}
            for bid in ids]


def allocation(policy: str, epoch: int, design: dict) -> tuple[dict, dict]:
    if policy not in design['policies'] or not 0 <= epoch <= design['maximum_moves']:
        raise ValueError('unknown policy or epoch')
    q = {k: Decimal(str(v)) for k, v in design['reference'].items()}
    memory = dict(design['memory_reference_bytes'])
    donor, recipient = design['donor'], design['recipient']
    if policy in ('cpu', 'joint'):
        transfer = epoch * Decimal(str(design['transfer_cpu']))
        q[donor] -= transfer
        q[recipient] += transfer
    if policy in ('ram', 'joint'):
        transfer = epoch * design['transfer_memory_bytes']
        memory[donor] -= transfer
        memory[recipient] += transfer
    if min(q.values()) < Decimal('0.05') or sum(q.values()) != Decimal('1'):
        raise ValueError('CPU budget is not positive and closed')
    if min(memory.values()) < 64 * 1024 ** 2 or sum(memory.values()) != sum(design['memory_reference_bytes'].values()):
        raise ValueError('memory budget is not positive and closed')
    return {k: float(v) for k, v in q.items()}, memory


def coordinates(design: dict, q: dict, memory: dict) -> dict:
    result = {'cpu_' + k: v for k, v in features(design, q).items()}
    ref = design['memory_reference_bytes']
    donor, recipient = design['donor'], design['recipient']
    result['ram_balance_displacement'] = balance(ref, [donor], [recipient]) - balance(memory, [donor], [recipient])
    result['ram_donor_share'] = memory[donor] / sum(memory.values())
    result['ram_recipient_share'] = memory[recipient] / sum(memory.values())
    return result


def compose_prefix(upstream: Path, project: str) -> list[str]:
    return [*engine.compose_prefix(ROOT, upstream, project), '-f', str(ROOT / OVERLAY)]


def verify(upstream: Path | None = None, check_runner: bool = False) -> dict:
    design, runtime = load(ROOT / DESIGN), load(ROOT / RUNTIME)
    if design['study_version'] != VERSION or runtime['study_version'] != VERSION:
        raise ValueError('version mismatch')
    if (design['replications'], design['maximum_moves'], design['checkout_rate'], design['transfer_cpu'],
        design['transfer_memory_bytes']) != (20, 12, 40, 0.02, 16 * 1024 ** 2):
        raise ValueError('unexpected bounded design')
    if design['policies'] != ['control', 'cpu', 'ram', 'joint']:
        raise ValueError('unexpected policies')
    if design['donor'] != 'checkout' or design['recipient'] != 'ad':
        raise ValueError('unexpected transfer endpoints')
    if design['analysis']['binary_success_criterion'] is not None:
        raise ValueError('no binary scientific success criterion')
    for key in ('parent_runtime', 'measurement_runtime'):
        if sha256_file(ROOT / runtime[key]) != runtime[key + '_sha256']:
            raise ValueError(f'parent hash mismatch: {key}')
    if runtime['workload'] != {'pre_allocated_vus': 800, 'max_vus': 800, 'minimum_started_fraction': 0.99}:
        raise ValueError('unexpected generator capacity')
    for policy in design['policies']:
        for epoch in range(design['maximum_moves'] + 1):
            q, memory = allocation(policy, epoch, design)
            coordinates(design, q, memory)
    rows = matrix(design)
    for position in range(4):
        if Counter(r['order'][position] for r in rows) != Counter({p: 5 for p in design['policies']}):
            raise ValueError('history position is not balanced')
    parent_verification = migration.verify(upstream, check_runner)
    if upstream:
        rendered = json.loads(engine.run([*compose_prefix(upstream, 'resources-render'), 'config',
                                          '--no-path-resolution', '--format', 'json']).stdout)
        memory = {**runtime['fixed_memory_bytes'], **design['memory_reference_bytes']}
        for name, value in memory.items():
            if int(rendered['services'][name]['deploy']['resources']['limits']['memory']) != value:
                raise ValueError(f'rendered memory differs: {name}')
        for name, value in design['memory_reference_bytes'].items():
            if int(rendered['services'][name]['memswap_limit']) != value:
                raise ValueError(f'rendered swap differs: {name}')
        for name, value in runtime['gomemlimit'].items():
            if rendered['services'][name]['environment']['GOMEMLIMIT'] != value:
                raise ValueError(f'rendered GOMEMLIMIT differs: {name}')
    return {'valid': True, 'study_version': VERSION, 'parent_verification': parent_verification,
            **{key: sha256_file(ROOT / path) for key, path in
               [('design_sha256', DESIGN), ('runtime_sha256', RUNTIME), ('overlay_sha256', OVERLAY)]}}


def read_cgroup(inspected: dict, filename: str) -> str:
    if filename not in ('cpu.max', 'memory.max', 'memory.swap.max', 'memory.current', 'memory.events', 'identity'):
        raise ValueError('unsupported cgroup filename')
    pid = int(inspected['State']['Pid'])
    if pid <= 0:
        raise ValueError('no live PID')
    root = f'/proc/{pid}/root/sys/fs/cgroup'
    command = ['stat', '-c', '%i', root] if filename == 'identity' else ['cat', root + '/' + filename]
    return engine.run(['sudo', '--non-interactive', *command]).stdout.strip()


def limit_check(q: dict, memory: dict) -> dict:
    raw, reasons = {}, []
    for name, value in q.items():
        inspected = engine.inspect_container(name)
        config, state = inspected['HostConfig'], inspected['State']
        item = {'container_id': inspected['Id'], 'pid': state['Pid'], 'running': state['Running'],
                'restarting': state.get('Restarting', False), 'nano_cpus': config['NanoCpus']}
        if abs(config['NanoCpus'] / 1e9 - value) > value * 0.01:
            reasons.append(f'{name}:configured_cpu_mismatch')
        if name in memory:
            item.update(memory=config['Memory'], memory_swap=config['MemorySwap'])
            if config['Memory'] != memory[name] or config['MemorySwap'] != memory[name]:
                reasons.append(f'{name}:configured_memory_mismatch')
        if state['Running'] and not state.get('Restarting', False) and state['Pid'] > 0:
            try:
                item['cgroup_inode'] = read_cgroup(inspected, 'identity')
                item['cpu.max'] = read_cgroup(inspected, 'cpu.max')
                quota, period = item['cpu.max'].split()
                if quota == 'max' or abs(int(quota) / int(period) - value) > value * 0.01:
                    reasons.append(f'{name}:effective_cpu_mismatch')
                if name in memory:
                    for filename in ('memory.max', 'memory.swap.max', 'memory.current', 'memory.events'):
                        item[filename] = read_cgroup(inspected, filename)
                    if item['memory.max'] != str(memory[name]) or item['memory.swap.max'] != '0':
                        reasons.append(f'{name}:effective_memory_mismatch')
                    item['memory_events'] = {k: int(v) for k, v in
                                             (line.split() for line in item['memory.events'].splitlines())}
            except Exception as exc:
                current = engine.inspect_container(name)
                changed = current['State']['Pid'] != state['Pid'] or not current['State']['Running'] or current['State'].get('Restarting')
                item['cgroup_read_error'] = repr(exc)
                item['process_changed_during_snapshot'] = bool(changed)
                if not changed:
                    reasons.append(f'{name}:live_cgroup_unreadable')
        else:
            item['cgroup_unavailable_reason'] = 'system_container_not_stably_running'
        raw[name] = item
    cpu_total = sum(r['nano_cpus'] / 1e9 for r in raw.values())
    memory_total = sum(raw[k]['memory'] for k in memory)
    if not math.isclose(cpu_total, sum(q.values()), abs_tol=1e-9): reasons.append('configured_cpu_budget_mismatch')
    if memory_total != sum(memory.values()): reasons.append('configured_memory_budget_mismatch')
    return {'valid': not reasons, 'reason_codes': reasons, 'requested_cpu': q, 'requested_memory': memory,
            'configured_cpu_total': cpu_total, 'configured_memory_total': memory_total, 'raw': raw}


def apply(q: dict, memory: dict, journal: Path) -> None:
    with journal.open('a', encoding='utf-8', buffering=1) as stream:
        for name in q:
            command = ['docker', 'update', '--cpus', f'{q[name]:.9f}']
            if name in memory:
                command.extend(['--memory', str(memory[name]), '--memory-swap', str(memory[name])])
            command.append(name)
            started = engine.utc()
            done = engine.run(command, check=False)
            stream.write(json.dumps({'started_at': started, 'ended_at': engine.utc(), 'command': command,
                                     'exit_code': done.returncode, 'stdout': done.stdout, 'stderr': done.stderr}) + '\n')
            if done.returncode:
                raise RuntimeError(f'resource update failed for {name}: {done.stderr}')


def resource_window(path: Path, start_ms: float, end_ms: float, names: list[str]) -> dict:
    import datetime as dt
    samples = {name: [] for name in names}
    previous, increments = {}, {name: Counter() for name in names}
    text = path.read_text(encoding='utf-8')
    lines = text.splitlines()
    if text and not text.endswith('\n'):
        lines = lines[:-1]
    for line in lines:
        frame = json.loads(line)
        stamp = dt.datetime.fromisoformat(frame['timestamp']).timestamp() * 1000
        for name in names:
            current = frame['containers'].get(name)
            if not current or 'sample_error' in current:
                previous.pop(name, None)
                continue
            if start_ms <= stamp <= end_ms:
                samples[name].append(current)
                prior = previous.get(name)
                if prior and prior['identity'] == current['identity']:
                    delta = {k: v - prior['memory_events'].get(k, 0) for k, v in current['memory_events'].items()}
                    if all(v >= 0 for v in delta.values()):
                        increments[name].update(delta)
            previous[name] = current
    return {name: {'sample_count': len(rows), 'memory_current_bytes_max':
                   max((r['memory_current_bytes'] for r in rows), default=None),
                   'memory_events_increment': dict(increments[name])} for name, rows in samples.items()}


def memory_cap_hit(before: dict, after: dict, measured: dict, donor: str) -> bool:
    a, b = before['raw'].get(donor, {}), after['raw'].get(donor, {})
    same = tuple(a.get(k) for k in ('container_id', 'pid', 'cgroup_inode')) == tuple(
        b.get(k) for k in ('container_id', 'pid', 'cgroup_inode'))
    increments = measured.get('resources', {}).get(donor, {}).get('memory_events_increment', {})
    if same and 'memory_events' in a and 'memory_events' in b:
        for key in ('max', 'oom', 'oom_kill'):
            if b['memory_events'].get(key, 0) > a['memory_events'].get(key, 0):
                return True
    return any(increments.get(k, 0) > 0 for k in ('max', 'oom', 'oom_kill'))


def phase(upstream, parent, inherited, design, runtime, bid, policy, name, seconds, folder,
          checkout_generator, ad_generator, samples):
    measured = migration.concurrent_phase(upstream, parent, inherited, design, runtime, bid, policy,
                                          name, seconds, folder, checkout_generator, ad_generator, samples)
    start = measured['checkout_window_started_ms']
    if start is not None:
        measured['resources'] = resource_window(samples, start, start + seconds * 1000,
                                                 list(design['memory_reference_bytes']))
    else:
        measured['resources'] = {}
    if measured['workload_overlap_fraction'] < 1 - runtime['maximum_workload_start_skew_seconds'] / seconds:
        measured['valid'] = False
        measured['reason_codes'].append('workload_overlap_too_short')
    if any(measured['resources'].get(k, {}).get('sample_count', 0) == 0 for k in design['memory_reference_bytes']):
        # A dead SUT is not a missing instrument. Its absence remains diagnostic.
        measured['resource_samples_missing'] = True
    return measured


def history(upstream, parent, inherited, design, runtime, bid, policy, folder):
    folder.mkdir(parents=True, exist_ok=False)
    prefix = compose_prefix(upstream, project_name(os.environ['GITHUB_RUN_ID'], bid, policy))
    checkout_generator, ad_generator = f'{bid}-{policy}-checkout-k6', f'{bid}-{policy}-ad-k6'
    result = {'policy': policy, 'baseline_valid': False, 'baseline': None, 'epochs': [],
              'stop_reason': 'not_started', 'diagnostic_errors': []}
    event_file = (folder / 'docker-events.jsonl').open('w', encoding='utf-8')
    event_error = (folder / 'docker-events.stderr.log').open('w', encoding='utf-8')
    events = subprocess.Popen(['docker', 'events', '--since', engine.utc(), '--filter', 'type=container',
                              '--filter', f'label=com.docker.compose.project={prefix[3]}', '--format', '{{json .}}'],
                             stdout=event_file, stderr=event_error)
    sampler = None
    samples = folder / 'resource-samples.jsonl'
    try:
        engine.run([*prefix, 'up', '--detach', '--no-build', '--pull', 'never'])
        engine.wait_for_stack(parent, runtime['health_check_timeout_seconds'])
        initial = engine.inspect_all(parent['required_running_containers'])
        write_json(folder / 'initial-container-inspect.json', initial)
        write_json(folder / 'observer-config.json', {
            'containers': [*design['reference'], 'astronomy-db', 'frontend', 'cart', 'product-catalog',
                           checkout_generator, ad_generator], 'output': str(samples.resolve()),
            'stop_file': str((folder / '.observer-stop').resolve()), 'interval_seconds': 2, 'refresh_seconds': 6})
        sampler = subprocess.Popen(['sudo', '--non-interactive', sys.executable,
                                    str(ROOT / 'probe3/scripts/observe.py'), '--config', str(folder / 'observer-config.json')])
        q, memory = allocation(policy, 0, design)
        apply(q, memory, folder / 'updates.jsonl')
        baseline_start = limit_check(q, memory)
        args = (upstream, parent, inherited, design, runtime, bid, policy)
        phase(*args, 'warmup', design['warmup_seconds'], folder / 'warmup', checkout_generator, ad_generator, samples)
        previous = phase(*args, 'baseline', design['baseline_seconds'], folder / 'baseline',
                         checkout_generator, ad_generator, samples)
        before = engine.inspect_all(parent['required_running_containers'])
        baseline_end = limit_check(q, memory)
        result.update(baseline=previous, baseline_limits_start=baseline_start, baseline_limits_end=baseline_end,
                      pre_adaptation_failures=engine.failures(initial, before, parent['system_under_test_containers']))
        reasons = list(previous['reason_codes'])
        if not previous['checkout']['safe']: reasons.append('baseline_slo_unsafe')
        if not baseline_start['valid'] or not baseline_end['valid']: reasons.append('baseline_limits_invalid')
        if result['pre_adaptation_failures']: reasons.append('pre_adaptation_system_failure')
        if previous['advertising']['goodput_per_second'] <= 0: reasons.append('baseline_recipient_output_missing')
        if (previous['advertising'].get('throttled_period_fraction_mean') or 0) <= 0:
            reasons.append('baseline_recipient_cpu_pressure_missing')
        if previous.get('resource_samples_missing'): reasons.append('baseline_resource_samples_missing')
        result['baseline_reason_codes'], result['baseline_valid'] = reasons, not reasons
        if reasons:
            result['stop_reason'] = 'baseline_invalid'
            return result
        previous_limits = baseline_end
        for epoch in range(1, design['maximum_moves'] + 1):
            if policy != 'control':
                decision = migration.decision(previous)
                if decision != 'transfer':
                    result['stop_reason'] = decision
                    break
            q, memory = allocation(policy, epoch, design)
            input_state = {'checkout_safe': previous['checkout']['safe'],
                           'ad_throttling': previous['advertising']['throttled_period_fraction_mean'],
                           'ad_goodput': previous['advertising']['goodput_per_second']}
            apply(q, memory, folder / 'updates.jsonl')
            limits_start = limit_check(q, memory)
            phase(*args, f'stabilize-{epoch:02d}', design['stabilization_seconds'],
                  folder / f'epochs/{epoch:02d}/stabilization', checkout_generator, ad_generator, samples)
            measured = phase(*args, f'epoch-{epoch:02d}', design['measurement_seconds'],
                             folder / f'epochs/{epoch:02d}/measurement', checkout_generator, ad_generator, samples)
            limits_end = limit_check(q, memory)
            if not limits_start['valid'] or not limits_end['valid']:
                measured['valid'] = False
                measured['reason_codes'].append('resource_limits_invalid')
            for name in memory:
                a, b = limits_start['raw'][name], limits_end['raw'][name]
                stable_live = a['running'] and b['running'] and a['pid'] == b['pid'] and a['container_id'] == b['container_id']
                if measured['resources'].get(name, {}).get('sample_count', 0) == 0 and stable_live:
                    measured['valid'] = False
                    measured['reason_codes'].append(name + ':live_memory_samples_missing')
            after = engine.inspect_all(parent['required_running_containers'], tolerate_missing=True)
            measured.update(epoch=epoch, quotas=q, memory_bytes=memory, decision_input=input_state,
                            limits_start=limits_start, limits_end=limits_end, coordinates=coordinates(design, q, memory),
                            goodput_change=measured['advertising']['goodput_per_second'] - input_state['ad_goodput'],
                            donor_memory_cap_hit=(memory_cap_hit(previous_limits, limits_start, measured, design['donor']) or
                                                  memory_cap_hit(limits_start, limits_end, measured, design['donor'])),
                            system_failures=engine.failures(before, after, parent['system_under_test_containers']))
            result['epochs'].append(measured)
            write_json(folder / f'epochs/{epoch:02d}/epoch-result.json', measured)
            print(json.dumps({'policy': policy, 'epoch': epoch, 'valid': measured['valid'],
                              'safe': measured['checkout']['safe'], 'p95_ms': measured['checkout']['p95_ms'],
                              'error_rate': measured['checkout']['error_rate'],
                              'ad_goodput': measured['advertising']['goodput_per_second'], 'cpu': q, 'memory': memory,
                              'donor_memory_cap_hit': measured['donor_memory_cap_hit']}), flush=True)
            previous, previous_limits, before = measured, limits_end, after
            if not measured['valid']:
                result['stop_reason'] = 'technical_measurement_failure'
                break
            if policy != 'control' and not measured['checkout']['safe']:
                result['stop_reason'] = 'observed_slo_boundary'
                break
        else:
            result['stop_reason'] = 'move_limit_reached'
    except Exception as exc:
        result['stop_reason'], result['exception'] = 'infrastructure_exception', repr(exc)
    finally:
        if sampler is not None:
            try:
                (folder / '.observer-stop').touch()
                sampler.wait(timeout=15)
            except subprocess.TimeoutExpired:
                engine.run(['sudo', '--non-interactive', 'kill', '-TERM', str(sampler.pid)], check=False)
            except Exception as exc:
                result['diagnostic_errors'].append(repr(exc))
        for command, filename in [([*prefix, 'logs', '--no-color', '--timestamps', '--tail', '200'], 'compose.log')]:
            try:
                done = engine.run(command, check=False)
                (folder / filename).write_text(done.stdout + done.stderr, encoding='utf-8')
            except Exception as exc:
                result['diagnostic_errors'].append(repr(exc))
        for command in [['docker', 'rm', '--force', checkout_generator, ad_generator],
                        [*prefix, 'down', '--volumes', '--remove-orphans']]:
            try: engine.run(command, check=False)
            except Exception as exc: result['diagnostic_errors'].append(repr(exc))
        try:
            events.terminate()
            try: events.wait(timeout=5)
            except subprocess.TimeoutExpired: events.kill(); events.wait(timeout=5)
        except Exception as exc:
            result['diagnostic_errors'].append(repr(exc))
        event_file.close(); event_error.close()
        for name in ['resource-samples.jsonl', 'docker-events.jsonl']:
            path = folder / name
            if path.exists():
                try:
                    with path.open('rb') as source, gzip.open(folder / (name + '.gz'), 'wb') as target:
                        while chunk := source.read(1024 * 1024): target.write(chunk)
                    path.unlink()
                except Exception as exc: result['diagnostic_errors'].append(repr(exc))
        write_json(folder / 'history-result.json', result)
    return result


def execute(upstream: Path, bid: str, output: Path, policy: str | None = None) -> int:
    verification = verify(upstream, True)
    design, runtime = load(ROOT / DESIGN), load(ROOT / RUNTIME)
    inherited = load(ROOT / runtime['parent_runtime'])
    inherited['workload'].update(runtime['workload'])
    parent = load(ROOT / inherited['parent_runtime'])
    cohort = 'engineering' if policy else 'campaign'
    if policy:
        design.update(design['engineering'])
        row = {'block_id': 'engineering-' + policy, 'order': [policy]}
    else:
        row = next(r for r in matrix(design) if r['block_id'] == bid)
    output.mkdir(parents=True, exist_ok=False)
    images = sorted({*parent['images'].values(), parent['workload']['k6_image']})
    for image in images: engine.run(['docker', 'pull', image])
    write_json(output / 'image-inspect.json', json.loads(engine.run(['docker', 'image', 'inspect', *images]).stdout))
    write_json(output / 'rendered-compose.json', json.loads(engine.run([
        *compose_prefix(upstream, 'resources-render'), 'config', '--no-path-resolution', '--format', 'json']).stdout))
    histories = {p: history(upstream, parent, inherited, design, runtime, row['block_id'], p, output / p)
                 for p in row['order']}
    write_json(output / 'block-result.json', {'study_version': VERSION, 'cohort': cohort, **row,
               'histories': histories, 'repository_commit': os.environ['GITHUB_SHA'],
               'workflow_run_id': os.environ['GITHUB_RUN_ID'], 'verification': verification,
               'runner_image': os.getenv('ImageOS'), 'runner_image_version': os.getenv('ImageVersion')})
    return 0


def engineering_gate(source: Path, output: Path, commit: str) -> dict:
    from analyze_resources import validate_block, valid_history
    design = load(ROOT / DESIGN)
    policies, errors, details = {}, [], {}
    for path in sorted(source.rglob('block-result.json')):
        block = load(path)
        validate_block(block, commit, engineering=True)
        for policy, h in block['histories'].items():
            if policy in policies: raise ValueError('duplicate engineering history')
            policies[policy] = h
            if not valid_history(h, design['engineering']['maximum_moves']): errors.append(policy + ':invalid_history')
            details[policy] = {'baseline_valid': h['baseline_valid'], 'stop_reason': h['stop_reason'],
                               'epochs': len(h['epochs']), 'exception': h.get('exception'),
                               'baseline_reason_codes': h.get('baseline_reason_codes', []),
                               'memory_cap_hit_epochs': [e['epoch'] for e in h['epochs'] if e['donor_memory_cap_hit']]}
    missing = sorted(set(design['policies']) - set(policies))
    if missing: errors.append('missing_engineering_policies')
    binding = any(e['donor_memory_cap_hit'] for p in ('ram', 'joint')
                  for e in policies.get(p, {}).get('epochs', []))
    if not binding: errors.append('memory_cap_never_observed_binding')
    report = {'study_version': VERSION, 'repository_commit': commit, 'passed': not errors,
              'reason_codes': errors, 'missing_policies': missing, 'memory_binding_observed': binding,
              'histories': details, 'not_scientific_replications': True}
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'engineering-gate.json', report)
    (output / 'GATE.md').write_text('# CPU/memory engineering gate\n\n' +
        f"Passed: {report['passed']}. Memory ceiling binding observed: {binding}.\n\n" +
        'Reasons: ' + ', '.join(errors) + '\n\n' +
        'These four histories are instrumentation/feasibility observations, not campaign replications.\n', encoding='utf-8')
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['verify', 'matrix', 'run', 'gate'])
    parser.add_argument('--upstream-dir', type=Path)
    parser.add_argument('--block-id')
    parser.add_argument('--policy', choices=['control', 'cpu', 'ram', 'joint'])
    parser.add_argument('--artifact-dir', type=Path)
    parser.add_argument('--results-root', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--repository-commit')
    args = parser.parse_args()
    if args.command == 'run':
        return execute(args.upstream_dir.resolve(), args.block_id, args.artifact_dir.resolve(), args.policy)
    if args.command == 'gate':
        report = engineering_gate(args.results_root, args.output_dir, args.repository_commit)
        print(json.dumps(report)); return 0 if report['passed'] else 1
    report = verify(args.upstream_dir.resolve() if args.upstream_dir else None)
    print(json.dumps({'include': matrix(load(ROOT / DESIGN))} if args.command == 'matrix' else report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
