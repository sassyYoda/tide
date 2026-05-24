import { describe, expect, test } from "vitest"
import {
  buildSpotDetailQuerystring,
  parseShap,
  parseCite,
} from "@/lib/spot-querystring"
import type { RecommendationPayload } from "@/lib/api-types"

// NOTE on Rule 3 deviation from PLAN.md "action" block: the planning template
// reaches for `components["schemas"]["RecommendationPayload"]` and
// `components["schemas"]["CitationOut"]`. Those schemas are NOT in the codegen
// (the FastAPI route is StreamingResponse-typed and OpenAPI does not surface
// SSE payloads). The hand-mirrored `RecommendationPayload` / `CitationOut`
// interfaces live as standalone exports from `@/lib/api-types`. The sibling
// test `spot-querystring.test.ts` already uses this exact import, so we
// follow the project convention.

const sample: RecommendationPayload = {
  recommendation_text: "Try Barnegat Inlet Saturday 6:30-9am.",
  citations: [
    { source: "NJF", date: "2026-04-22", chunk_id: null, source_url: null },
    { source: "SO", date: "2026-04-20", chunk_id: null, source_url: null },
    { source: "NJF", date: "2026-04-19", chunk_id: null, source_url: null },
  ],
  confidence_label: "High",
  retrieval_ok: true,
  ml_score_available: true,
  conditions_stale: false,
  data_age_seconds: 420,
  spot_id: 7,
  spot_name: "Barnegat Inlet",
  ml_score: 0.81,
  shap_top3: ["outgoing_tide", "ne_wind", "falling_pressure"],
  rag_latency_ms: 145.2,
  species_canonical: "striper",
  time_window_label: "Saturday morning",
}

describe("B-4 destination side — round-trip via Plan 05 builder + Plan 06 parsers", () => {
  test("builder → URLSearchParams → parsers preserves shap_top3 (first 3)", () => {
    const qs = buildSpotDetailQuerystring(sample)
    const params = new URLSearchParams(qs)
    const shap = parseShap(params.get("shap") ?? undefined)
    expect(shap).toEqual(["outgoing_tide", "ne_wind", "falling_pressure"])
  })

  test("builder → URLSearchParams → parsers preserves citations field-for-field", () => {
    const qs = buildSpotDetailQuerystring(sample)
    const params = new URLSearchParams(qs)
    const cites = parseCite(params.get("cite") ?? undefined)
    expect(cites).toHaveLength(3)
    expect(cites[0]).toEqual({
      source: "NJF",
      date: "2026-04-22",
      chunk_id: null,
      source_url: null,
    })
    expect(cites[1]).toEqual({
      source: "SO",
      date: "2026-04-20",
      chunk_id: null,
      source_url: null,
    })
    expect(cites[2]).toEqual({
      source: "NJF",
      date: "2026-04-19",
      chunk_id: null,
      source_url: null,
    })
  })

  test("parseShap absent input → null (NOT empty array — used as empty-state signal)", () => {
    expect(parseShap(undefined)).toBeNull()
    expect(parseShap("")).toBeNull()
    expect(parseShap(null)).toBeNull()
  })

  test("parseCite absent input → [] (NOT null — components iterate)", () => {
    expect(parseCite(undefined)).toEqual([])
    expect(parseCite("")).toEqual([])
    expect(parseCite(null)).toEqual([])
  })

  test("parseCite trailing colon → date: null (round-trips Plan 05's `${date ?? \"\"}`)", () => {
    const cites = parseCite("NJF:")
    expect(cites).toHaveLength(1)
    expect(cites[0]).toEqual({ source: "NJF", date: null, chunk_id: null, source_url: null })
  })

  test("parseShap truncates to first 3 (regression net on destination)", () => {
    expect(parseShap("a,b,c,d,e")).toEqual(["a", "b", "c"])
  })

  test("parseCite truncates to first 5 (regression net on destination)", () => {
    const long = Array.from(
      { length: 10 },
      (_, i) => `S${i}:2026-01-0${(i % 9) + 1}`,
    ).join(",")
    const cites = parseCite(long)
    expect(cites).toHaveLength(5)
  })
})
