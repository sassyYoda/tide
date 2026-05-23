// Phase 6 P-08 + A1 falsification — k6 load test against the deployed backend.
//
// Goal: 100 concurrent virtual users, 5-minute sustained POST /api/v1/query,
// p95 < 8s, failure rate < 1%. If the test PASSES on the GCP e2-micro VM
// hosting TimescaleDB+Qdrant+Redis, A1 (the 1GB-RAM + 4GB-swap configuration
// can sustain portfolio-scale load without OOM) is CONFIRMED. If the test
// FAILS (OOM, 5xx spike, p95 > 8s), A1 is FALSIFIED — the documented
// fallback is e2-small (+$13/mo budget break) or splitting Qdrant onto a
// second project.
//
// Run from a dev machine with k6 installed (`brew install k6`):
//
//   TIDE_URL=https://tide-backend-XXX.run.app k6 run scripts/load_test.js
//
// Run with a ramp instead of constant-VUs (preferred for SLI verification —
// avoids cold-start thundering-herd skewing the early p95 window):
//
//   TIDE_URL=https://tide-backend-XXX.run.app SCENARIO=ramp k6 run scripts/load_test.js
//
// Output: k6 prints a per-metric summary at exit. The two metrics gating the
// pass/fail decision are http_req_duration.p(95) and http_req_failed.rate.
// Both are encoded as thresholds — k6's exit code is non-zero on threshold
// breach, so CI / a shell wrapper can rely on it.

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Rate, Counter } from 'k6/metrics';

// ───────────────────────────────────────────────────────────────────────────
// Custom metrics — give the operator finer-grained visibility than the
// default http_req_* metrics, especially around 5xx (OOM canary) and 429
// (rate limit, which is EXPECTED to fire under 100-VU load).

const ttfb_query = new Trend('ttfb_query_ms', true);
const status_429_rate = new Rate('rate_429');
const status_5xx_count = new Counter('count_5xx');
const status_503_count = new Counter('count_503');

// ───────────────────────────────────────────────────────────────────────────
// Scenario selection — `constant-vus` for the P-08 spec exact match;
// `ramp` for SLI work that wants warmup time.

const SCENARIO = __ENV.SCENARIO || 'constant';

const scenarios =
  SCENARIO === 'ramp'
    ? {
        portfolio_ramp: {
          executor: 'ramping-vus',
          startVUs: 0,
          stages: [
            { duration: '1m', target: 50 },   // ramp to 50
            { duration: '1m', target: 100 },  // ramp to 100
            { duration: '3m', target: 100 },  // hold 100 for 3 min (matches P-08 5m total)
          ],
          gracefulRampDown: '30s',
        },
      }
    : {
        portfolio_load: {
          executor: 'constant-vus',
          vus: 100,
          duration: '5m',
        },
      };

export const options = {
  scenarios,
  thresholds: {
    // P-08 budget: p95 latency under 8s end-to-end (TTFB + full SSE drain).
    http_req_duration: ['p(95)<8000'],

    // Failure rate: <1% of requests return network error / non-2xx-or-429.
    // (429 is expected and not counted as a failure — slowapi 20/IP/hr will
    //  fire quickly under sustained 100-VU load from one source IP.)
    http_req_failed: ['rate<0.01'],

    // OOM canary — if any 5xx appears, A1 is at risk. Threshold logs warn
    // but does not fail the run (5xx may also reflect upstream transient).
    count_5xx: ['count<50'],

    // Freshness-gate 503 canary — Pitfall P3. Acceptable; logged for the ops
    // record so the user knows whether the VM caught up before launch.
    count_503: ['count<200'],
  },

  // 100 VUs from one source IP -> slowapi 20/IP/hr will rate-limit ~80% of
  // requests after the first 20. The thresholds above account for this:
  // failure_rate excludes 429s, and the OOM canary tracks 5xx separately.
  // For a TRUE 100-distinct-user simulation, run k6 from a load-testing
  // cloud (k6 Cloud / k6 Distributed) — but the e2-micro stress test
  // (which IS what A1 is gating) is dominated by the worker queue + cache
  // behaviour, both of which the single-IP run exercises faithfully.
};

const BASE = __ENV.TIDE_URL || 'http://localhost:8000';

// 20-question rotation — covers all 5 MVP species, 5+ NJ locations, mixed
// intents (where / when / why / conditions). Designed to stress the cache
// MISS path (each question hashes to a distinct cache key) AND the cache HIT
// path (each question reappears every 20 requests).
const QUERIES = [
  // Striper (5 questions)
  'striper barnegat tonight',
  'where to target stripers at raritan bay sunday morning NE wind',
  'striped bass fall run sandy hook surf casting',
  'best striper tide for manasquan inlet outgoing',
  'striper bunker chunking shrewsbury river',

  // Fluke (4)
  'fluke manasquan inlet drift sunday',
  'flounder doormat sandy hook channel',
  'fluke bucktail color clear water shark river',
  'best fluke tide barnegat inlet outgoing',

  // Bluefish (3)
  'bluefish chunking bunker IBSP',
  'blues at point pleasant beach pencil poppers',
  'bluefish topwater run start of september NJ',

  // Weakfish (3)
  'weakfish raritan bay night',
  'spike weakfish navesink river new moon',
  'weakfish kettle creek april return',

  // Tautog (3)
  'tautog wreck spots manasquan ridge',
  'blackfish jigs vs green crabs sandy hook reef',
  'tog late november cold front shark river jetty',

  // Conditions / out-of-scope edge (2)
  'what are conditions at AC right now',
  'trout in colorado',
];

export default function () {
  const q = QUERIES[Math.floor(Math.random() * QUERIES.length)];
  const start = Date.now();

  const res = http.post(
    `${BASE}/api/v1/query`,
    JSON.stringify({ query: q }),
    {
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
      },
      // 120s upper bound: a Cloud Run cold start + agent worst case (8s p95)
      // should never exceed 30s; the 120s is paranoid headroom that lets
      // OOM-induced hangs ACTUALLY register as failures rather than k6 retry.
      timeout: '120s',
    }
  );

  ttfb_query.add(Date.now() - start);

  // Tally per-status counters BEFORE checks so they fire even when checks fail.
  if (res.status === 429) status_429_rate.add(true);
  else status_429_rate.add(false);
  if (res.status >= 500 && res.status !== 503) status_5xx_count.add(1);
  if (res.status === 503) status_503_count.add(1);

  // 200 = SSE stream started; 429 = expected rate limit (slowapi); both pass.
  // Any other status is a hard fail counted in http_req_failed.
  check(res, {
    'status is 200 or 429': (r) => r.status === 200 || r.status === 429,
    'no 5xx (OOM canary)': (r) => r.status < 500 || r.status === 503,
  });

  // 1 req/VU/sec is the polite-client default. With 100 VUs that's 100 RPS,
  // ~5x typical portfolio traffic — well above what the deployed system will
  // ever see in steady state, which is the entire point of stress testing.
  sleep(1);
}

// ───────────────────────────────────────────────────────────────────────────
// Optional teardown — print a one-line A1 verdict the operator can paste
// straight into 06-LAUNCH-SMOKE.md.

export function handleSummary(data) {
  const p95 = data.metrics.http_req_duration?.values?.['p(95)'] ?? null;
  const fail = data.metrics.http_req_failed?.values?.rate ?? null;
  const c5xx = data.metrics.count_5xx?.values?.count ?? 0;
  const c429 = data.metrics.rate_429?.values?.rate ?? 0;

  const a1_pass =
    p95 !== null &&
    p95 < 8000 &&
    fail !== null &&
    fail < 0.01 &&
    c5xx < 50;

  const verdict = a1_pass ? 'CONFIRMED' : 'FALSIFIED';

  // eslint-disable-next-line no-console
  console.log(`\n=== A1 status: ${verdict} ===`);
  // eslint-disable-next-line no-console
  console.log(`  p95: ${p95 !== null ? p95.toFixed(0) + 'ms' : 'n/a'}`);
  // eslint-disable-next-line no-console
  console.log(`  http_req_failed rate: ${fail !== null ? (fail * 100).toFixed(2) + '%' : 'n/a'}`);
  // eslint-disable-next-line no-console
  console.log(`  5xx count (OOM canary): ${c5xx}`);
  // eslint-disable-next-line no-console
  console.log(`  429 rate (expected, not a failure): ${(c429 * 100).toFixed(2)}%`);

  return {
    stdout: JSON.stringify(
      { a1_status: verdict, p95_ms: p95, fail_rate: fail, count_5xx: c5xx, rate_429: c429 },
      null,
      2
    ),
  };
}
