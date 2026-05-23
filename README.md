# tide

a hyper-local fishing intelligence agent that combines NOAA environmental streams, moon phase data and indexed fishing reports to predict where you should be fishing, what you should be fishing for, and why.

## Local Dev: MLflow UI

Per-species training runs (XGBoost activity model) are tracked in `backend/mlruns/`. To browse run history, AUC-ROC, Brier score, and SHAP feature-importance plots locally:

```bash
cd backend
uv run mlflow ui --backend-store-uri file://$PWD/mlruns --port 5000
```

Then open <http://localhost:5000> → select experiment `tide-activity-model` → group by `params.species` for the 5 MVP species (striper, fluke, bluefish, weakfish, tautog). Promotion status reflects D-04 (M-08 / M-09 gates lock as-is): **0 / 5 species are currently promoted to the MLflow `production` alias** because no run has cleared AUC-ROC ≥ 0.72 AND Brier ≤ 0.22 on the temporal-holdout test set. See `data/model_registry_report.json` for the per-species promotion attempt log; the corpus uplift to clear the gate is Phase 6 pre-launch QA work, not a Phase 5 regression. The pipeline (train → evaluate → register → gate → promote) is fully wired in `backend/scripts/promote_production.py`.

Phase 6 will migrate the tracking URI to `gs://tide-mlflow/` for production.

## Live Demo Links

- **Live PWA preview:** <https://tide-obd99510w-aryan-ahujas-projects-b54c1c1d.vercel.app>
- **Langfuse showcase traces** (4 curated scenarios, publicly viewable without a Langfuse account):
  - Happy path (striper): <https://us.cloud.langfuse.com/project/cmon6k8aa015mad07jxqayowr/traces/cdaa58b7e3d0207b8e15660a404df7c0>
  - Out-of-scope ("trout in Colorado"): <https://us.cloud.langfuse.com/project/cmon6k8aa015mad07jxqayowr/traces/10ea29e31ceb10550cf6f5b0ef6ffd4c>
  - Cache hit candidate (duplicate-query flow): <https://us.cloud.langfuse.com/project/cmon6k8aa015mad07jxqayowr/traces/75147a4438b155204c34cd5d92e200b4>
  - Partial conditions before recommendation: <https://us.cloud.langfuse.com/project/cmon6k8aa015mad07jxqayowr/traces/c2fdd862bfab4d58fee6c8900bd0d30b>

Each URL is verified accessible without auth via `python scripts/pin_showcase_traces.py verify`. The rate-limit trace is deferred to v1.x — slowapi shortcuts before LangGraph runs, so the Langfuse `CallbackHandler` does not fire on rate-limited requests (confirmed OQ-3, 2026-05-23).

## Monitoring + Metrics

The FastAPI backend exposes Prometheus `/metrics` with bounded-cardinality counters and gauges (no path-templated labels per Pitfall P4):

- `query_cache_hits_total` / `query_cache_misses_total` — query-cache effectiveness (P-09)
- `data_age_seconds{station_id, source}` — freshness signal per NOAA station
- `ingest_success_total` / `ingest_failure_total` — Celery ingest task health
- `freshness_gate_503_total{station_id, reason}` — `/conditions` 503 events

### Cache hit rate (P-09 target ≥ 40%)

`/metrics` does NOT expose a pre-computed gauge — operators compute it from the canonical Prometheus pattern (counters in-process; rates in PromQL):

```promql
rate(query_cache_hits_total[15m])
  /
(rate(query_cache_hits_total[15m]) + rate(query_cache_misses_total[15m]))
```

This pattern lets the operator change the rolling window without redeploying. (Pre-computed ratios silently lie when one of the rates is zero; the PromQL `rate()` form handles the zero-divisor case at scrape time.)

### Readiness: `/healthz` (REL-01)

```json
{
  "ts_lag_seconds": 142,
  "qdrant_ok": true,
  "model_loaded": true,
  "status": "ok"
}
```

Returns HTTP 200 when `status == "ok"`, HTTP 503 when `status == "degraded"`. Always served with `Cache-Control: no-store` to prevent CDN cache poisoning of stale `degraded` responses (Pitfall P3).
