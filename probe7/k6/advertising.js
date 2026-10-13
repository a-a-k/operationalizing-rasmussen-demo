import grpc from 'k6/net/grpc';
import exec from 'k6/execution';
import { sleep } from 'k6';
import { Counter, Trend } from 'k6/metrics';

const SECONDS = Number(__ENV.DURATION_SECONDS);
const VUS = Number(__ENV.AD_VUS);
const TIMEOUT = Number(__ENV.AD_TIMEOUT_SECONDS);
const DEADLINE = Number(__ENV.AD_DEADLINE_MS);
const client = new grpc.Client();
client.load(['/proto'], 'demo.proto');
let connected = false;
const attempts = new Counter('ad_attempts');
const finished = new Counter('ad_finished');
const timely = new Counter('ad_timely');
const useful = new Counter('ad_useful_inside_window');
const duration = new Trend('ad_latency_ms');
const windowStart = new Trend('ad_window_start_ms');

export const options = {
  scenarios: {advertising: {executor: 'constant-vus', vus: VUS, duration: SECONDS + 's', gracefulStop: '30s'}},
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(95)', 'p(99)'],
};

export function setup() {
  const wait = (Number(__ENV.START_AT_MS) - Date.now()) / 1000;
  if (wait > 0) sleep(wait);
}

export default function () {
  const end = exec.scenario.startTime + SECONDS * 1000;
  if (__ITER === 0) {
    attempts.add(0); finished.add(0); timely.add(0); useful.add(0);
    windowStart.add(exec.scenario.startTime);
  }
  if (Date.now() >= end) return;
  const begin = Date.now();
  attempts.add(1);
  let nonempty = false;
  try {
    if (!connected) {
      client.connect(__ENV.AD_ENDPOINT, {plaintext: true, timeout: TIMEOUT + 's'});
      connected = true;
    }
    const response = client.invoke('oteldemo.AdService/GetAds', {contextKeys: ['clothing']}, {
      timeout: TIMEOUT + 's',
      metadata: {traceparent: '00-00000000000000000000000000000001-0000000000000001-00'},
    });
    nonempty = response.status === grpc.StatusOK && response.message &&
      Array.isArray(response.message.ads) && response.message.ads.length > 0;
  } catch (_) {
    connected = false;
    sleep(0.01);
  } finally {
    const elapsed = Date.now() - begin;
    finished.add(1);
    duration.add(elapsed);
    if (nonempty && elapsed <= DEADLINE) timely.add(1);
    if (nonempty && Date.now() < end) useful.add(1);
  }
}

export function handleSummary(data) {
  return {'/artifacts/summary.json': JSON.stringify(data, null, 2)};
}
