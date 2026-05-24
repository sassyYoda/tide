import type { RecommendationPayload, CitationOut } from "./api-types"

/**
 * Build the `?shap=...&cite=...` querystring for /spot/{id} navigation.
 * COPIED VERBATIM from .planning/phases/04-frontend-pwa/04-CONTEXT.md
 * "Specific Ideas" — locked by prior plan-checker round.
 *
 * Round-trip contract: parseShap + parseCite (in app/spot/[id]/page.tsx,
 * Plan 06) reconstruct the same shape. Format: comma-separated; citations
 * use "source:date" tokens. parseCite MUST split on LAST colon to survive
 * dates with embedded colons.
 */
export function buildSpotDetailQuerystring(rec: RecommendationPayload): string {
  const params = new URLSearchParams()
  if (rec.shap_top3 && rec.shap_top3.length > 0) {
    params.set("shap", rec.shap_top3.slice(0, 3).join(","))
  }
  if (rec.citations.length > 0) {
    const cite = rec.citations
      .slice(0, 5)
      .map((c) => `${c.source}:${c.date ?? ""}`)
      .join(",")
    params.set("cite", cite)
  }
  return params.toString()
}

/**
 * Plan 06's app/spot/[id]/page.tsx imports the parsers from here, but the
 * parsers themselves live in this module so they can be unit-tested without
 * mounting an App Router page.
 *
 * IMPORTANT: parseCite splits on the LAST colon (lastIndexOf), NOT the first,
 * so future date formats with embedded colons (e.g. ISO timestamps) survive.
 */
export function parseShap(s?: string | null): string[] | null {
  if (!s) return null
  const parts = s.split(",").map((p) => p.trim()).filter(Boolean)
  return parts.length > 0 ? parts.slice(0, 3) : null
}

export function parseCite(s?: string | null): CitationOut[] {
  if (!s) return []
  return s
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean)
    .map((p) => {
      // P-04 review note from planning_context: split on LAST colon, not first.
      const idx = p.lastIndexOf(":")
      const source = idx >= 0 ? p.slice(0, idx) : p
      const dateStr = idx >= 0 ? p.slice(idx + 1) : ""
      // source_url is null when parsed from the URL — the original click-
      // through URL isn't serialized in the spot-link querystring (would
      // blow past sane URL length budgets); the spot-detail page renders
      // these as plain text, not anchors.
      return {
        source,
        date: dateStr || null,
        chunk_id: null,
        source_url: null,
      } as CitationOut
    })
    .slice(0, 5)
}
