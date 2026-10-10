import grpc from 'k6/net/grpc';
import exec from 'k6/execution';
import { Counter, Trend } from 'k6/metrics';

const SECONDS = Number(__ENV.DURATION_SECONDS);
const VUS = Number(__ENV.AD_VUS);
const TIMEOUT = Number(__ENV.AD_TIMEOUT_SECONDS);
for (const value of [SECONDS, VUS, TIMEOUT]) {
  if (!Number.isInteger(value) || value <= 0) throw new Error('Invalid fixed workload value');
}
const client = new grpc.Client();
client.load(['/proto'], 'demo.proto');
let connected = false;
const attempts = new Counter('ad_window_attempts');
const successes = new Counter('ad_window_successes');
const completions = new Counter('ad_window_completions');
const connections = new Counter('ad_connection_failures');
const windowStart = new Trend('ad_window_start_ms');

export const options = {
  scenarios: {
    advertising: {
      executor: 'constant-vus', vus: VUS, duration: String(SECONDS) + 's',
      gracefulStop: '30s',
    },
  },
};

export default function () {
  const end = exec.scenario.startTime + SECONDS * 1000;
  if (__ITER === 0) {
    windowStart.add(exec.scenario.startTime);
    attempts.add(0); successes.add(0); completions.add(0); connections.add(0);
  }
  if (Date.now() >= end) return;
  attempts.add(1);
  try {
    if (!connected) {
      client.connect(__ENV.AD_ENDPOINT, { plaintext: true, timeout: String(TIMEOUT) + 's' });
      connected = true;
    }
    const response = client.invoke('oteldemo.AdService/GetAds', { contextKeys: ['clothing'] }, {
      timeout: String(TIMEOUT) + 's',
      metadata: { baggage: 'session.id=allocation-demo', traceparent: '00-00000000000000000000000000000001-0000000000000001-00' },
    });
    if (Date.now() < end) {
      completions.add(1);
      if (response.status === grpc.StatusOK && response.message &&
          Array.isArray(response.message.ads) && response.message.ads.length > 0) successes.add(1);
    }
  } catch (_) {
    connections.add(1);
    connected = false;
    if (Date.now() < end) completions.add(1);
  }
}

export function handleSummary(data) {
  return { '/artifacts/summary.json': JSON.stringify(data, null, 2) };
}
