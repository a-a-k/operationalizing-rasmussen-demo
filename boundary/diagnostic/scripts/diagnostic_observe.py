"""Read-only host and all-container sampling for a disposable hosted runner."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time


CPU_FIELDS = ['user', 'nice', 'system', 'idle', 'iowait', 'irq', 'softirq', 'steal']


def text_if_present(path):
    try:
        return path.read_text().strip()
    except OSError:
        return None


def counters(path):
    return {k: int(v) for k, v in (line.split() for line in path.read_text().splitlines())}


def host_delta(previous, current):
    if previous is None or any(current[k] < previous[k] for k in CPU_FIELDS):
        return None
    values = {k: current[k]-previous[k] for k in CPU_FIELDS}
    total = sum(values.values())
    return {k: v/total for k, v in values.items()} if total else None


def container_delta(previous, current, seconds):
    if not previous or previous['identity'] != current['identity'] or seconds <= 0:
        return None
    delta = {k: v-previous['cpu'].get(k, 0) for k, v in current['cpu'].items()}
    if any(v < 0 for v in delta.values()):
        return None
    periods = delta.get('nr_periods', 0)
    return {**delta, 'sample_seconds': seconds,
            'cpu_cores': delta.get('usage_usec', 0)/1e6/seconds,
            'throttled_period_fraction': delta.get('nr_throttled', 0)/periods if periods else None,
            'throttled_ms_per_period': delta.get('throttled_usec', 0)/1000/periods if periods else None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path)
    cfg = json.loads(parser.parse_args().config.read_text())
    registry, previous, previous_host = {}, {}, None
    last_refresh = last_sample = 0.0
    with Path(cfg['output']).open('w', encoding='utf-8', buffering=1) as stream:
        while not Path(cfg['stop_file']).exists():
            now = time.monotonic()
            frame = {'timestamp_ms': time.time()*1000, 'monotonic_seconds': now, 'containers': {}}
            if now-last_refresh >= 6:
                try:
                    ids = subprocess.run(['docker', 'ps', '-q'], capture_output=True, text=True,
                                         check=True, timeout=5).stdout.split()
                    items = json.loads(subprocess.run(['docker', 'inspect', *ids], capture_output=True,
                                       text=True, check=True, timeout=5).stdout) if ids else []
                    registry = {item['Name'].lstrip('/'): item for item in items}
                except Exception as exc:
                    frame['registry_error'] = repr(exc)
                last_refresh = now
            host = dict(zip(CPU_FIELDS, map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9])))
            frame.update(host_cpu=host, host_cpu_fractions=host_delta(previous_host, host),
                         host_logical_cpus=os.cpu_count(), host_load_average=os.getloadavg(),
                         host_pressure={name: text_if_present(Path('/proc/pressure')/name)
                                        for name in ['cpu', 'memory', 'io']})
            previous_host = host
            for name, inspected in registry.items():
                pid = inspected['State'].get('Pid', 0)
                if pid <= 0:
                    continue
                root = Path(f'/proc/{pid}/root/sys/fs/cgroup')
                try:
                    current = {'identity': [inspected['Id'], pid, root.stat().st_ino],
                               'cpu': counters(root/'cpu.stat'), 'cpu_max': (root/'cpu.max').read_text().strip(),
                               'memory_events': counters(root/'memory.events'),
                               'memory_current_bytes': int((root/'memory.current').read_text()),
                               'restart_count': inspected['RestartCount'],
                               'pressure': {p: text_if_present(root/(p+'.pressure')) for p in ['cpu', 'memory', 'io']}}
                    current['delta'] = container_delta(previous.get(name), current, now-last_sample)
                    previous[name] = current
                    frame['containers'][name] = current
                except (OSError, ValueError) as exc:
                    previous.pop(name, None)
                    frame['containers'][name] = {'sample_error': repr(exc)}
            stream.write(json.dumps(frame, separators=(',', ':'))+'\n')
            last_sample = now
            time.sleep(cfg['interval_seconds'])


if __name__ == '__main__':
    main()
