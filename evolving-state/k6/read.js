import http from 'k6/http';
import exec from 'k6/execution';
import {sleep} from 'k6';

const cfg = JSON.parse(open('/scripts/load-config.json'));
const scenarios = {};
for (const group of ['catalog', 'currency']) {
  scenarios[group] = {
    executor: 'constant-arrival-rate',
    exec: 'read',
    rate: cfg.logical_rate_per_group,
    timeUnit: '1s',
    duration: `${cfg.active_windows * cfg.window_seconds}s`,
    preAllocatedVUs: cfg.preallocated_vus_per_group,
    maxVUs: cfg.preallocated_vus_per_group,
    gracefulStop: '10s',
    tags: {logical_group: group},
  };
}
export const options = {
  scenarios,
  discardResponseBodies: true,
  summaryTrendStats: ['avg', 'p(95)', 'max'],
};
export function setup() {
  while (Date.now() < cfg.origin_ms) {
    sleep(Math.max(0, Math.min(0.1, (cfg.origin_ms - Date.now()) / 1000)));
  }
}
export function read() {
  const group = exec.scenario.name;
  const id = `${cfg.block_id}:${group}:${exec.scenario.iterationInTest}`;
  const start = Date.now();
  const response = http.get(`http://retry-gateway:8080/request/${group}`, {
    headers: {'X-Logical-Id': id},
    timeout: `${cfg.request_timeout_seconds}s`,
    tags: {name: `logical_${group}`},
  });
  console.log('CLIENT ' + JSON.stringify({logical_id: id, group, started_ms: start,
    completed_ms: Date.now(), status: response.status, error_code: response.error_code || 0}));
}
export function handleSummary(data) {
  return {'/artifacts/summary.json': JSON.stringify(data, null, 2)};
}
