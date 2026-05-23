// Phase 6 P-08 — 100 concurrent users / 5 min sustained, p95 < 8s.
// Run: TIDE_URL=https://tide-backend-XXX.run.app k6 run scripts/load_test.js
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  scenarios: {
    portfolio_load: {
      executor: 'constant-vus',
      vus: 100,
      duration: '5m',
    },
  },
  thresholds: {
    // P-08 budget: p95 latency under 8s
    http_req_duration: ['p(95)<8000'],
    http_req_failed: ['rate<0.01'],
  },
};

const BASE = __ENV.TIDE_URL || 'http://localhost:8000';
const QUERIES = [
  'striper barnegat tonight',
  'fluke manasquan inlet drift',
  'bluefish chunking bunker',
  'weakfish raritan bay',
  'tautog wreck spots',
];

export default function () {
  const q = QUERIES[Math.floor(Math.random() * QUERIES.length)];
  const res = http.post(
    `${BASE}/api/v1/query`,
    JSON.stringify({ query: q }),
    { headers: { 'Content-Type': 'application/json' }, timeout: '120s' }
  );
  check(res, {
    'status is 200 or 429': (r) => r.status === 200 || r.status === 429,
  });
  sleep(1);  // 1 req/VU/sec, well within polite client behavior
}
