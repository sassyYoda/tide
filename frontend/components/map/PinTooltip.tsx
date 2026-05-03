"use client"
import type { components } from "@/lib/api-types"
import { buildAriaPinLabel } from "@/lib/aria-pin-label"
import { scoreBand, BAND_TO_LABEL } from "@/lib/score-band"

type SpotScore = components["schemas"]["SpotScore"]

interface Props {
  spot: SpotScore
  x: number
  y: number
}

export function PinTooltip({ spot, x, y }: Props) {
  const label = buildAriaPinLabel({
    species: spot.species,
    score: spot.score,
    dataAgeSeconds: spot.data_age_seconds,
    // Citations come from RecommendationPayload, not /api/v1/spots; default 0 here.
    citationCount: 0,
  })
  const band = scoreBand(spot.score)
  return (
    <div
      role="tooltip"
      aria-label={label}
      data-testid="pin-tooltip"
      className="pointer-events-none absolute z-20 rounded bg-stone-900/90 px-2 py-1 text-xs text-white shadow"
      style={{ left: x + 12, top: y + 12 }}
    >
      <div className="font-semibold">{spot.name}</div>
      <div className="capitalize text-stone-300">{spot.species ?? "unknown"}</div>
      <div>
        {BAND_TO_LABEL[band]} confidence
        {spot.score != null ? ` (${(spot.score * 100).toFixed(0)})` : ""}
      </div>
    </div>
  )
}
