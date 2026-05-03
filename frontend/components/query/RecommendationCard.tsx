"use client"
import Link from "next/link"
import type { Route } from "next"
import type {
  RecommendationPayload,
  PartialConditionsPayload,
  CitationOut,
} from "@/lib/api-types"
import { ConfidenceBadge } from "./ConfidenceBadge"
import { ShowReasoning } from "./ShowReasoning"
import { CitationsPanel } from "./CitationsPanel"
import { EmptyState } from "./EmptyState"
import { buildSpotDetailQuerystring } from "@/lib/spot-querystring"

interface Props {
  recommendation: RecommendationPayload
  partial?: PartialConditionsPayload
}

/**
 * F-16 / L-13 freshness rule: a citation backs the recommendation only if
 * its date is within 14 days of "now". An older citation may still be
 * informative but does NOT count toward the L-13 floor of "≥ 2 FRESH reports".
 *
 * Returns false for citations with null/missing dates, since L-13 demands
 * "recent local reports" — undated citations cannot prove recency.
 */
function isFreshCitation(c: CitationOut): boolean {
  if (!c.date) return false
  const t = new Date(c.date).getTime()
  if (Number.isNaN(t)) return false
  const ageDays = (Date.now() - t) / 86400000
  return ageDays >= 0 && ageDays <= 14
}

export function RecommendationCard({ recommendation, partial }: Props) {
  const rec = recommendation

  // F-16 / L-13 empty-state branch (per CONTEXT.md L-13: "fewer than 2 FRESH
  // reports back the recommendation"). NOT a raw citations.length check — a
  // 3-citation set where every entry is months stale is still empty-state
  // territory because L-13's promise is RECENT local intel.
  //
  // Triggers:
  //   freshCount < 2                 → not enough recent evidence
  //   rec.retrieval_ok === false     → backend signaled retrieval failure
  const freshCount = rec.citations.filter(isFreshCitation).length
  const showEmpty = freshCount < 2 || rec.retrieval_ok === false
  if (showEmpty) {
    return <EmptyState />
  }

  // B-4 source side: build /spot/{spot_id}?shap=...&cite=...
  const qs = buildSpotDetailQuerystring(rec)
  const spotHref =
    rec.spot_id != null ? `/spot/${rec.spot_id}${qs ? `?${qs}` : ""}` : null

  return (
    <article
      data-testid="recommendation-card"
      className="min-h-[400px] rounded-lg border border-stone-200 bg-white p-5 shadow-sm"
    >
      <header className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-2xl text-tide-high">
            {rec.spot_name ?? "Recommendation"}
          </h2>
          {rec.time_window_label && (
            <p className="text-sm text-stone-600">{rec.time_window_label}</p>
          )}
        </div>
        <ConfidenceBadge label={rec.confidence_label} />
      </header>

      {/* P11 enforcement: render recommendation_text as a React text node ONLY.
          Never raw HTML insertion. */}
      <p
        data-testid="recommendation-text"
        className="whitespace-pre-wrap text-base leading-relaxed text-stone-800"
      >
        {rec.recommendation_text}
      </p>

      {rec.conditions_stale && (
        <p
          role="status"
          className="mt-3 rounded bg-tide-mid/20 px-2 py-1 text-xs text-stone-700"
        >
          Conditions are slightly stale (
          {rec.data_age_seconds != null
            ? `${Math.round(rec.data_age_seconds / 60)} min old`
            : "age unknown"}
          ). Treat with care.
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <CitationsPanel citations={rec.citations} />
        {spotHref && (
          <Link
            // Next 16 typedRoutes: cast dynamic /spot/[id]?... href to Route.
            // The route exists at app/spot/[id]/page.tsx; the cast is needed
            // because typedRoutes can't statically prove arbitrary id values.
            href={spotHref as Route}
            data-testid="spot-detail-link"
            className="text-sm text-tide-high underline-offset-2 hover:underline"
          >
            View spot detail →
          </Link>
        )}
      </div>

      <ShowReasoning recommendation={rec} partial={partial} />
    </article>
  )
}
