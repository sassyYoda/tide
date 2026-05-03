"use client"
import { useState } from "react"
import type { RecommendationPayload, PartialConditionsPayload } from "@/lib/api-types"

interface Props {
  recommendation: RecommendationPayload
  partial?: PartialConditionsPayload
}

export function ShowReasoning({ recommendation, partial }: Props) {
  const [open, setOpen] = useState(false)
  const shap = recommendation.shap_top3
  const score = recommendation.ml_score
  const conditions = partial?.conditions

  return (
    <div className="mt-4">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls="reasoning-panel"
        data-testid="show-reasoning-toggle"
        className="text-sm text-tide-high underline-offset-2 hover:underline"
      >
        {open ? "Hide reasoning" : "Show reasoning"}
      </button>
      {/* L-12: inline reveal — must NOT be a modal/dialog */}
      {open && (
        <div
          id="reasoning-panel"
          data-testid="reasoning-panel"
          className="mt-2 rounded-md border border-stone-200 bg-stone-50 p-3 text-sm"
        >
          {score != null && (
            <div className="mb-2">
              <span className="font-medium">ML score:</span>{" "}
              <span className="font-mono">{(score * 100).toFixed(0)}/100</span>
            </div>
          )}
          {shap && shap.length > 0 ? (
            <div className="mb-2">
              <p className="font-medium">Top features driving this score:</p>
              <ol className="ml-5 mt-1 list-decimal space-y-0.5 text-stone-700">
                {shap.slice(0, 3).map((feat) => (
                  <li key={feat}>{feat}</li>
                ))}
              </ol>
            </div>
          ) : (
            <p className="text-stone-500">No SHAP features available.</p>
          )}
          {conditions ? (
            <div>
              <p className="font-medium">Live conditions:</p>
              <ul className="ml-5 mt-1 list-disc space-y-0.5 text-stone-700">
                {Object.entries(conditions).slice(0, 6).map(([k, v]) => (
                  <li key={k}>
                    <span className="font-mono text-xs">{k}</span>: {String(v)}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}
