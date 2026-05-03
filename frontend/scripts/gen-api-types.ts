#!/usr/bin/env tsx
/**
 * Codegen frontend/lib/api-types.ts from the live FastAPI backend's openapi.json.
 *
 * Usage:
 *   pnpm gen:api-types              # writes lib/api-types.ts (commit the result)
 *   pnpm gen:api-types:check        # fails if committed snapshot drifts from live spec
 *
 * Env:
 *   NEXT_PUBLIC_API_URL  default http://localhost:8000  — backend base URL
 */
import { execSync } from "node:child_process"
import { readFileSync, appendFileSync } from "node:fs"
import { resolve, dirname } from "node:path"
import { fileURLToPath } from "node:url"

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
const SPEC_URL = `${API}/openapi.json`
const OUT_PATH = resolve(__dirname, "../lib/api-types.ts")
const CHECK_PATH = "/tmp/api-types.gen.ts"
const isCheck = process.argv.includes("--check")
const target = isCheck ? CHECK_PATH : OUT_PATH

try {
  execSync(`pnpm exec openapi-typescript ${SPEC_URL} --output ${target}`, {
    stdio: "inherit",
  })
} catch {
  console.error(`\n[gen-api-types] FAILED. Is the backend running at ${API}?`)
  console.error(`Set NEXT_PUBLIC_API_URL=<url> and ensure ${SPEC_URL} returns 200.`)
  process.exit(1)
}

// SSE-payload addendum.
//
// FastAPI's openapi.json does NOT describe SSE event payloads (the /api/v1/query
// route uses StreamingResponse, so no response_model is registered). The SSE
// payload models live in backend/agent/sse_protocol.py. We mirror them here as
// hand-maintained TS types so the frontend can type-check useTideQuery against
// the actual wire format.
//
// CONTRACT: Update this addendum whenever sse_protocol.py changes. The drift
// test (tests/api-types-drift.test.ts) catches HTTP-route drift; the SSE
// addendum has its own discipline (P12 narrow exception — codegen is only
// possible against typed HTTP routes).
const SSE_ADDENDUM = `
// ─── SSE event payloads (hand-mirrored from backend/agent/sse_protocol.py) ───
// The OpenAPI spec describes only HTTP routes; SSE event payloads are not
// surfaced by FastAPI for StreamingResponse routes. These types MUST be kept
// in sync with backend/agent/sse_protocol.py manually. See gen-api-types.ts.

export type SSEEventType =
  | "progress"
  | "partial_conditions"
  | "recommendation"
  | "error";

export type SSEErrorCode =
  | "rate_limited"
  | "planner_timeout"
  | "planner_out_of_scope"
  | "llm_unavailable"
  | "internal";

export type ProgressStage =
  | "planner"
  | "data_fetcher"
  | "rag_retriever"
  | "synthesizer";

export type ConfidenceLabel = "High" | "Moderate" | "Low";

export interface ProgressPayload {
  stage: ProgressStage;
}

export interface PartialConditionsPayload {
  spot_id: number | null;
  spot_name: string | null;
  conditions: Record<string, unknown> | null;
  ml_score: number | null;
  shap_top3: string[] | null;
  data_age_seconds: number | null;
  conditions_stale: boolean;
}

export interface CitationOut {
  source: string;
  date: string | null;
  chunk_id: string | null;
}

export interface RecommendationPayload {
  recommendation_text: string;
  citations: CitationOut[];
  confidence_label: ConfidenceLabel;
  retrieval_ok: boolean;
  ml_score_available: boolean;
  conditions_stale: boolean;
  data_age_seconds: number | null;
  spot_id: number | null;
  spot_name: string | null;
  ml_score: number | null;
  shap_top3: string[] | null;
  rag_latency_ms: number | null;
  species_canonical: string | null;
  time_window_label: string | null;
}

export interface ErrorPayload {
  code: SSEErrorCode;
  message: string;
  partial_state: Record<string, unknown> | null;
}
`

// Append SSE addendum (always — the addendum is part of the snapshot).
appendFileSync(target, SSE_ADDENDUM)

if (isCheck) {
  const fresh = readFileSync(CHECK_PATH, "utf-8")
  const committed = readFileSync(OUT_PATH, "utf-8")
  if (fresh !== committed) {
    console.error(
      "[gen-api-types] DRIFT: live backend OpenAPI does not match committed snapshot.",
    )
    console.error("Run `pnpm gen:api-types` and commit the result.")
    process.exit(2)
  }
  console.log("[gen-api-types] snapshot matches live backend.")
}
