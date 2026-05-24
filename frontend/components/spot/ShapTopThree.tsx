"use client"

import Link from "next/link"
import type { Route } from "next"

interface Props {
  shap: string[] | null // NOTE: NOT optional, NOT `[]` — null signals empty-state
  spotName?: string | null
}

export function ShapTopThree({ shap, spotName }: Props) {
  // F-16 honest empty branch: null means the URL didn't carry shap context.
  // Do NOT render an empty <ol>. Do NOT pretend there's data. But DO give
  // the user a path forward — a one-click way to generate the context by
  // asking Tide about this spot.
  if (shap === null || shap.length === 0) {
    const seed = spotName
      ? `stripers at ${spotName}`
      : ""
    const askHref = seed
      ? `/?q=${encodeURIComponent(seed)}`
      : "/"
    return (
      <section
        data-testid="shap-empty"
        className="rounded-md border border-stone-300 bg-stone-50 p-3 text-sm text-stone-600"
      >
        <p className="font-medium">No reasoning context for this view.</p>
        <p className="mt-1 text-xs">
          The top-3 features driving the activity score flow into this page
          when you arrive from a Tide recommendation.
        </p>
        <Link
          // Next 16 typedRoutes can't prove arbitrary `?q=...` is a valid
          // route — cast like RecommendationCard does for /spot/[id].
          href={askHref as Route}
          data-testid="shap-empty-cta"
          className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-tide-high underline-offset-2 hover:underline"
        >
          Ask Tide about {spotName ?? "this spot"} →
        </Link>
      </section>
    )
  }

  return (
    <section
      data-testid="shap-top-three"
      className="rounded-md border border-stone-200 bg-white p-3"
    >
      <h3 className="font-display text-sm uppercase tracking-wide text-stone-700">
        Top features driving this score
      </h3>
      <ol className="mt-2 ml-5 list-decimal space-y-1 text-sm text-stone-800">
        {shap.slice(0, 3).map((feat) => (
          <li key={feat}>{feat}</li>
        ))}
      </ol>
    </section>
  )
}
