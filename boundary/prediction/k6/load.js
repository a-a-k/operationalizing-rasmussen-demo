import http from 'k6/http';
import grpc from 'k6/net/grpc';
import exec from 'k6/execution';
import { Counter } from 'k6/metrics';

const cfg = JSON.parse(open('/scripts/design.json'));
const seconds = cfg.warmup_seconds + cfg.window_seconds * cfg.measurement_windows;
const client = new grpc.Client();
client.load(['/proto'], 'demo.proto');
let connected = false;
const starts = new Counter('calibration_starts');
const finishes = new Counter('calibration_finishes');
function scenario(name, rate, vus) {
  return {executor: 'constant-arrival-rate', exec: name, rate, timeUnit: '1s',
    duration: seconds + 's', preAllocatedVUs: vus, maxVUs: vus,
    gracefulStop: cfg.graceful_stop_seconds + 's'};
}
export const options = {
  scenarios: {
    checkout: scenario('checkout', cfg.checkout_rate, cfg.checkout_vus),
    advertising: scenario('advertising', cfg.advertising_rate, cfg.advertising_vus),
  },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(95)', 'p(99)'],
};
function begin(stream) {
  if (exec.scenario.iterationInTest >= seconds * (stream === 'checkout' ? cfg.checkout_rate : cfg.advertising_rate)) return null;
  const row = {kind: 'start', stream, id: exec.scenario.iterationInTest,
    t: Date.now(), origin: exec.scenario.startTime};
  console.log('CAL ' + JSON.stringify(row));
  starts.add(1, {stream});
  return row;
}
function end(row, extra) {
  finishes.add(1, {stream: row.stream});
  console.log('CAL ' + JSON.stringify({...row, ...extra, kind: 'finish', t: Date.now()}));
}
const order = {
  email: 'load@example.invalid',
  address: {streetAddress: '1 Test Street', zipCode: '94043', city: 'Mountain View', state: 'CA', country: 'United States'},
  userCurrency: 'USD',
  creditCard: {creditCardNumber: '4432-8015-6152-0454', creditCardExpirationMonth: 1,
    creditCardExpirationYear: 2039, creditCardCvv: 672},
};
export function checkout() {
  const row = begin('checkout');
  if (row === null) return;
  let success = false, latency = null, status = null, errorCode = null;
  try {
    const user = __ENV.TRIAL_ID + '-' + row.id;
    const params = {headers: {'Content-Type': 'application/json',
      traceparent: '00-00000000000000000000000000000001-0000000000000001-00'},
      timeout: cfg.http_timeout_seconds + 's', redirects: 0};
    const cart = http.post('http://frontend-proxy:8080/api/cart',
      JSON.stringify({userId: user, item: {productId: '0PUK6V6EV0', quantity: 1}}), params);
    const response = http.post('http://frontend-proxy:8080/api/checkout', JSON.stringify({...order, userId: user}), params);
    latency = response.timings.duration;
    status = response.status;
    errorCode = response.error_code || null;
    let hasOrder = false;
    try {const body = response.json(); hasOrder = body && typeof body.orderId === 'string' && body.orderId.length > 0;} catch (_) {}
    success = cart.status >= 200 && cart.status < 300 && status >= 200 && status < 300 && hasOrder;
  } catch (_) {success = false;}
  finally {end(row, {success, latency_ms: latency, status, error_code: errorCode});}
}
export function advertising() {
  const row = begin('advertising');
  if (row === null) return;
  let success = false;
  try {
    if (!connected) {
      client.connect('ad:9555', {plaintext: true, timeout: cfg.rpc_timeout_seconds + 's'});
      connected = true;
    }
    const response = client.invoke('oteldemo.AdService/GetAds', {contextKeys: ['clothing']},
      {timeout: cfg.rpc_timeout_seconds + 's',
       metadata: {traceparent: '00-00000000000000000000000000000001-0000000000000001-00'}});
    success = response.status === grpc.StatusOK && response.message && Array.isArray(response.message.ads) && response.message.ads.length > 0;
  } catch (_) {connected = false;}
  finally {end(row, {success: Boolean(success), latency_ms: Date.now() - row.t});}
}
export function handleSummary(data) {
  return {'/artifacts/summary.json': JSON.stringify(data, null, 2)};
}
