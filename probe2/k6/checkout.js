import http from 'k6/http';
import exec from 'k6/execution';
import crypto from 'k6/crypto';
import { Counter } from 'k6/metrics';

const RATE = Number.parseInt(__ENV.RATE, 10);
const DURATION_SECONDS = Number.parseInt(__ENV.DURATION_SECONDS, 10);
const VUS = Number.parseInt(__ENV.VUS, 10);
const HTTP_TIMEOUT_SECONDS = Number.parseInt(__ENV.HTTP_TIMEOUT_SECONDS, 10);
const PHASE = __ENV.PHASE;
const TRIAL_ID = __ENV.TRIAL_ID;
const CONDITION = __ENV.CONDITION;
const SUMMARY_PATH = __ENV.SUMMARY_PATH || '/artifacts/summary.json';
const TARGET_URL = __ENV.TARGET_URL || 'http://frontend-proxy:8080';
const TARGET_ITERATIONS = RATE * DURATION_SECONDS;

for (const [name, value] of Object.entries({ RATE, DURATION_SECONDS, VUS, HTTP_TIMEOUT_SECONDS })) {
  if (!Number.isInteger(value) || value < 1) throw new Error(`${name} must be a positive integer`);
}

export const options = {
  discardResponseBodies: false,
  scenarios: {
    checkout: {
      executor: 'constant-arrival-rate',
      exec: 'checkoutIteration',
      rate: RATE,
      timeUnit: '1s',
      duration: `${DURATION_SECONDS}s`,
      preAllocatedVUs: VUS,
      maxVUs: VUS,
      gracefulStop: '30s',
      tags: { phase: PHASE, trial_id: TRIAL_ID, condition: CONDITION },
    },
  },
};

const successfulIterations = new Counter('successful_iterations');
const protocolIterationsStarted = new Counter('protocol_iterations_started');
const checkoutRequestsStarted = new Counter('checkout_requests_started');

const PRODUCT_ID = '0PUK6V6EV0';
const ORDER = Object.freeze({
  email: 'larry_sergei@example.com',
  address: {
    streetAddress: '1600 Amphitheatre Parkway', zipCode: '94043', city: 'Mountain View',
    state: 'CA', country: 'United States',
  },
  userCurrency: 'USD',
  creditCard: {
    creditCardNumber: '4432-8015-6152-0454', creditCardExpirationMonth: 1,
    creditCardExpirationYear: 2039, creditCardCvv: 672,
  },
});

function requestParams(name, traceId, spanId) {
  return {
    headers: { 'Content-Type': 'application/json', traceparent: `00-${traceId}-${spanId}-01` },
    timeout: `${HTTP_TIMEOUT_SECONDS}s`,
    redirects: 0,
    tags: { name, request_name: name, phase: PHASE, trial_id: TRIAL_ID, condition: CONDITION, trace_id: traceId },
  };
}

function is2xx(response) { return response.status >= 200 && response.status < 300; }

function hasOrderId(response) {
  try {
    const body = response.json();
    return typeof body === 'object' && body !== null && typeof body.orderId === 'string' && body.orderId.length > 0;
  } catch (_) { return false; }
}

export function checkoutIteration() {
  const iteration = exec.scenario.iterationInTest;
  if (iteration >= TARGET_ITERATIONS) return;
  protocolIterationsStarted.add(1);
  const userId = `${TRIAL_ID}-${CONDITION}-${PHASE}-${iteration}`;
  const traceId = crypto.sha256(userId, 'hex').slice(0, 32);
  const cartResponse = http.post(
    `${TARGET_URL}/api/cart`,
    JSON.stringify({ userId, item: { productId: PRODUCT_ID, quantity: 1 } }),
    requestParams('add_to_cart', traceId, crypto.sha256(`${userId}:cart`, 'hex').slice(0, 16)),
  );
  checkoutRequestsStarted.add(1);
  const checkoutResponse = http.post(
    `${TARGET_URL}/api/checkout`, JSON.stringify({ ...ORDER, userId }),
    requestParams('checkout', traceId, crypto.sha256(`${userId}:checkout`, 'hex').slice(0, 16)),
  );
  if (is2xx(cartResponse) && is2xx(checkoutResponse) && hasOrderId(checkoutResponse)) successfulIterations.add(1);
}

export function handleSummary(data) {
  return { [SUMMARY_PATH]: JSON.stringify(data, null, 2) };
}
