import http from 'k6/http';
import exec from 'k6/execution';
import crypto from 'k6/crypto';
import { Counter, Trend } from 'k6/metrics';

const RATE = Number.parseInt(__ENV.RATE, 10);
const SECONDS = Number.parseInt(__ENV.DURATION_SECONDS, 10);
const VUS = Number.parseInt(__ENV.VUS, 10);
const TIMEOUT = Number.parseInt(__ENV.HTTP_TIMEOUT_SECONDS, 10);
const PHASE = __ENV.PHASE;
const TRIAL = __ENV.TRIAL_ID;
const POINT = __ENV.POINT_ID;
const TARGET = 'http://frontend-proxy:8080';
for (const value of [RATE, SECONDS, VUS, TIMEOUT]) {
  if (!Number.isInteger(value) || value <= 0) throw new Error('Invalid frozen workload value');
}

export const options = {
  scenarios: {
    checkout: {
      executor: 'constant-arrival-rate',
      rate: RATE,
      timeUnit: '1s',
      duration: String(SECONDS) + 's',
      preAllocatedVUs: VUS,
      maxVUs: VUS,
      gracefulStop: '30s',
      tags: { phase: PHASE, trial_id: TRIAL, point_id: POINT },
    },
  },
};

const started = new Counter('protocol_iterations_started');
const finished = new Counter('protocol_iterations_finished');
const successful = new Counter('successful_iterations');
const checkoutStarted = new Counter('checkout_requests_started');
const operationDuration = new Trend('protocol_iteration_duration', true);
const ORDER = {
  email: 'larry_sergei@example.com',
  address: {
    streetAddress: '1600 Amphitheatre Parkway', zipCode: '94043',
    city: 'Mountain View', state: 'CA', country: 'United States',
  },
  userCurrency: 'USD',
  creditCard: {
    creditCardNumber: '4432-8015-6152-0454', creditCardExpirationMonth: 1,
    creditCardExpirationYear: 2039, creditCardCvv: 672,
  },
};

function params(name, trace, user) {
  return {
    headers: {
      'Content-Type': 'application/json',
      traceparent: '00-' + trace + '-' + crypto.sha256(user + ':' + name, 'hex').slice(0, 16) + '-01',
    },
    timeout: String(TIMEOUT) + 's',
    redirects: 0,
    tags: { name, request_name: name, trace_id: trace },
  };
}

function hasOrder(response) {
  try {
    const body = response.json();
    return body && typeof body.orderId === 'string' && body.orderId.length > 0;
  } catch (_) { return false; }
}

export default function () {
  const iteration = exec.scenario.iterationInTest;
  // The executor can emit one terminal, no-op iteration. It is not a protocol attempt.
  if (iteration >= RATE * SECONDS) return;
  started.add(1);
  const begin = Date.now();
  try {
    const user = TRIAL + '-' + POINT + '-' + PHASE + '-' + iteration;
    const trace = crypto.sha256(user, 'hex').slice(0, 32);
    const cart = http.post(
      TARGET + '/api/cart',
      JSON.stringify({ userId: user, item: { productId: '0PUK6V6EV0', quantity: 1 } }),
      params('add_to_cart', trace, user),
    );
    checkoutStarted.add(1);
    const checkout = http.post(
      TARGET + '/api/checkout', JSON.stringify({ ...ORDER, userId: user }),
      params('checkout', trace, user),
    );
    if (cart.status >= 200 && cart.status < 300 &&
        checkout.status >= 200 && checkout.status < 300 && hasOrder(checkout)) {
      successful.add(1);
    }
  } finally {
    finished.add(1);
    operationDuration.add(Date.now() - begin);
  }
}

export function handleSummary(data) {
  return { '/artifacts/summary.json': JSON.stringify(data, null, 2) };
}
