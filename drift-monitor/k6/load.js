import http from 'k6/http';
import grpc from 'k6/net/grpc';
import exec from 'k6/execution';
import { Counter, Trend } from 'k6/metrics';

const cfg = JSON.parse(open('/scripts/load-design.json'));
const client = new grpc.Client();
client.load(['/proto'], 'demo.proto');
let connected = false;
const checkoutStarts = new Counter('monitor_checkout_starts');
const checkoutGood = new Counter('monitor_checkout_good');
const checkoutLatency = new Trend('monitor_checkout_latency', true);
const adAttempts = new Counter('monitor_ad_attempts');
const adTimely = new Counter('monitor_ad_timely');
const adGood = new Counter('monitor_ad_good');
const adLatency = new Trend('monitor_ad_latency', true);
const thresholds = {};
for (let i = 1; i <= cfg.monitor_windows; i++) {
  for (const name of ['monitor_checkout_starts', 'monitor_checkout_good', 'monitor_ad_attempts', 'monitor_ad_timely', 'monitor_ad_good']) {
    thresholds[name + '{slot:' + i + '}'] = ['count>=0'];
  }
  thresholds['monitor_checkout_latency{slot:' + i + '}'] = ['p(95)>=0'];
  thresholds['monitor_ad_latency{slot:' + i + '}'] = ['p(99)>=0'];
}
export const options = {
  scenarios: {
    checkout: {executor: 'constant-arrival-rate', exec: 'checkout', rate: cfg.checkout_rate, timeUnit: '1s',
      duration: cfg.total_seconds + 's', preAllocatedVUs: cfg.checkout_vus, maxVUs: cfg.checkout_vus,
      gracefulStop: cfg.graceful_stop_seconds + 's'},
    advertising: {executor: 'constant-vus', exec: 'advertising', vus: cfg.advertising_vus,
      duration: cfg.total_seconds + 's', gracefulStop: cfg.graceful_stop_seconds + 's'},
  },
  thresholds,
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(95)', 'p(99)'],
};
function location(now) {
  const relative = (now - exec.scenario.startTime) / 1000 - cfg.warmup_seconds - cfg.reference_seconds;
  const cycle = cfg.guard_seconds + cfg.window_seconds;
  const slot = Math.floor(relative / cycle) + 1;
  if (relative < 0 || relative % cycle < cfg.guard_seconds || slot > cfg.monitor_windows) return {slot: 'other', end: Infinity};
  return {slot: String(slot), end: exec.scenario.startTime + 1000 * (cfg.warmup_seconds + cfg.reference_seconds + slot * cycle)};
}
function origin() {
  if (__ITER === 0) console.log('ORIGIN ' + JSON.stringify({stream: exec.scenario.name, origin: exec.scenario.startTime}));
}
const order = {
  email: 'load@example.invalid',
  address: {streetAddress: '1 Test Street', zipCode: '94043', city: 'Mountain View', state: 'CA', country: 'United States'},
  userCurrency: 'USD',
  creditCard: {creditCardNumber: '4432-8015-6152-0454', creditCardExpirationMonth: 1, creditCardExpirationYear: 2039, creditCardCvv: 672},
};
export function checkout() {
  origin();
  if (exec.scenario.iterationInTest >= cfg.checkout_rate * cfg.total_seconds) return;
  const start = Date.now();
  const loc = location(start);
  const tags = {slot: loc.slot};
  checkoutStarts.add(1, tags);
  checkoutGood.add(0, tags);
  const user = __ENV.TRIAL_ID + '-' + exec.scenario.iterationInTest;
  const params = {headers: {'Content-Type': 'application/json', traceparent: '00-00000000000000000000000000000001-0000000000000001-00'},
    timeout: cfg.http_timeout_seconds + 's', redirects: 0};
  let latency = null, success = false;
  try {
    const cart = http.post('http://frontend-proxy:8080/api/cart', JSON.stringify({userId: user, item: {productId: '0PUK6V6EV0', quantity: 1}}), params);
    const response = http.post('http://frontend-proxy:8080/api/checkout', JSON.stringify({...order, userId: user}), params);
    latency = response.timings.duration;
    let id = null;
    try {id = response.json().orderId;} catch (_) {}
    success = cart.status >= 200 && cart.status < 300 && response.status >= 200 && response.status < 300 && typeof id === 'string' && id.length > 0;
    checkoutLatency.add(latency, tags);
    if (success) checkoutGood.add(1, tags);
  } finally {
    console.log('CHECKOUT ' + JSON.stringify({start_ms: start, finish_ms: Date.now(), slot: loc.slot, success, latency_ms: latency}));
  }
}
export function advertising() {
  origin();
  if (Date.now() >= exec.scenario.startTime + cfg.total_seconds * 1000) return;
  const start = Date.now();
  const loc = location(start);
  const tags = {slot: loc.slot};
  adAttempts.add(1, tags); adTimely.add(0, tags); adGood.add(0, tags);
  let good = false;
  try {
    if (!connected) {client.connect('ad:9555', {plaintext: true, timeout: cfg.rpc_timeout_seconds + 's'}); connected = true;}
    const response = client.invoke('oteldemo.AdService/GetAds', {contextKeys: ['clothing']},
      {timeout: cfg.rpc_timeout_seconds + 's', metadata: {traceparent: '00-00000000000000000000000000000001-0000000000000001-00'}});
    good = response.status === grpc.StatusOK && response.message && Array.isArray(response.message.ads) && response.message.ads.length > 0;
  } catch (_) {connected = false;}
  finally {
    const elapsed = Date.now() - start;
    adLatency.add(elapsed, tags);
    if (good && elapsed <= 200) adTimely.add(1, tags);
    if (good && Date.now() < loc.end) adGood.add(1, tags);
  }
}
export function handleSummary(data) {return {'/artifacts/summary.json': JSON.stringify(data, null, 2)};}
