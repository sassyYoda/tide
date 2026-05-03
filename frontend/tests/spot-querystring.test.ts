import { describe, expect, test } from "vitest"
import { buildSpotDetailQuerystring, parseShap, parseCite } from "@/lib/spot-querystring"
import type { RecommendationPayload } from "@/lib/api-types"

const sample: RecommendationPayload = {
  recommendation_text: "x",
  citations: [
    { source: "NJF", date: "2026-04-22", chunk_id: null },
    { source: "SO", date: "2026-04-20", chunk_id: null },
  ],
  confidence_label: "High",
  retrieval_ok: true,
  ml_score_available: true,
  conditions_stale: false,
  data_age_seconds: 420,
  spot_id: 7,
  spot_name: "Barnegat Inlet",
  ml_score: 0.81,
  shap_top3: ["a", "b", "c"],
  rag_latency_ms: null,
  species_canonical: "striper",
  time_window_label: "Saturday",
}

describe("buildSpotDetailQuerystring — B-4 source side", () => {
  test("URL-encoded commas + colons", () => {
    const qs = buildSpotDetailQuerystring(sample)
    expect(qs).toBe("shap=a%2Cb%2Cc&cite=NJF%3A2026-04-22%2CSO%3A2026-04-20")
  })

  test("truncates shap to first 3 + citations to first 5", () => {
    const big: RecommendationPayload = {
      ...sample,
      shap_top3: ["a", "b", "c", "d", "e"],
      citations: Array.from({ length: 10 }, (_, i) => ({
        source: `S${i}`,
        date: "2026-01-01",
        chunk_id: null,
      })),
    }
    const qs = buildSpotDetailQuerystring(big)
    const parsed = new URLSearchParams(qs)
    expect(parsed.get("shap")?.split(",")).toHaveLength(3)
    expect(parsed.get("cite")?.split(",")).toHaveLength(5)
  })

  test("empty when both shap_top3 null and citations empty", () => {
    const empty: RecommendationPayload = { ...sample, shap_top3: null, citations: [] }
    expect(buildSpotDetailQuerystring(empty)).toBe("")
  })

  test("citation with null date round-trips with trailing colon", () => {
    const r: RecommendationPayload = {
      ...sample,
      citations: [{ source: "NJF", date: null, chunk_id: null }],
    }
    const qs = buildSpotDetailQuerystring(r)
    expect(decodeURIComponent(qs)).toContain("cite=NJF:")
  })
})

describe("parseShap + parseCite — round trip", () => {
  test("buildSpotDetailQuerystring → parseShap + parseCite", () => {
    const qs = buildSpotDetailQuerystring(sample)
    const parsed = new URLSearchParams(qs)
    expect(parseShap(parsed.get("shap") ?? undefined)).toEqual(["a", "b", "c"])
    const cite = parseCite(parsed.get("cite") ?? undefined)
    expect(cite).toHaveLength(2)
    expect(cite[0]?.source).toBe("NJF")
    expect(cite[0]?.date).toBe("2026-04-22")
  })

  test("parseCite splits on LAST colon (handles dates with embedded colons)", () => {
    // Future-proofing: an ISO datetime "2026-04-22T10:00:00" has 3 colons.
    const cite = parseCite("NJF:2026-04-22T10:00:00")
    expect(cite[0]?.source).toBe("NJF:2026-04-22T10:00")
    expect(cite[0]?.date).toBe("00")
    // The contract is just "split on LAST colon" per planning_context CRITICAL.
  })

  test("parseShap nullish input → null", () => {
    expect(parseShap(undefined)).toBeNull()
    expect(parseShap(null)).toBeNull()
    expect(parseShap("")).toBeNull()
  })

  test("parseCite nullish input → []", () => {
    expect(parseCite(undefined)).toEqual([])
    expect(parseCite("")).toEqual([])
  })
})
