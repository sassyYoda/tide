"use client"
import type { components, CitationOut } from "@/lib/api-types"
import { ShapTopThree } from "./ShapTopThree"
import { ReportsList } from "./ReportsList"
import { ConditionsSnapshot } from "./ConditionsSnapshot"
import { ConfidenceBadge } from "@/components/query/ConfidenceBadge"

type SpotScore = components["schemas"]["SpotScore"]
type ConditionsResponse = components["schemas"]["ConditionsResponse"]

interface Props {
  spot: SpotScore
  conditions: ConditionsResponse | null
  shap: string[] | null
  reports: CitationOut[]
}

export function SpotDetailPanel({ spot, conditions, shap, reports }: Props) {
  // P11: every text rendered via React text nodes — no raw HTML insertion.
  return (
    <article
      data-testid="spot-detail-panel"
      className="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-6"
    >
      <header className="flex items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl text-tide-high">{spot.name}</h1>
          {spot.species && (
            <p className="text-sm text-stone-600">
              Latest score for: <span className="font-medium">{spot.species}</span>
            </p>
          )}
          <p className="mt-1 text-xs text-stone-500">
            {spot.lat.toFixed(4)}, {spot.lon.toFixed(4)}
          </p>
        </div>
        {spot.confidence && <ConfidenceBadge label={spot.confidence} />}
      </header>

      {spot.score != null && (
        <section
          data-testid="spot-score"
          className="rounded-md border border-stone-200 bg-white p-3"
        >
          <h3 className="font-display text-sm uppercase tracking-wide text-stone-700">
            Activity score
          </h3>
          <p className="mt-1 font-mono text-2xl text-tide-high">
            {(spot.score * 100).toFixed(0)}/100
          </p>
          {spot.data_age_seconds != null && (
            <p className="mt-1 text-xs text-stone-500">
              Updated {Math.round(spot.data_age_seconds / 60)} min ago
            </p>
          )}
        </section>
      )}

      <ConditionsSnapshot
        conditions={conditions}
        ageSeconds={conditions?.data_age_seconds}
      />

      {/* B-4 destination side — pass parsed values explicitly per
          planning_context CRITICAL:
            <ShapTopThree shap={shap} />     (NOT shap={null})
            <ReportsList reports={reports} /> (NOT reports={[]}) */}
      <ShapTopThree shap={shap} />
      <ReportsList reports={reports} />
    </article>
  )
}
