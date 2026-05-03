"use client"

import { STALE_THRESHOLD_S } from "@/lib/nj-stations"

interface Props {
  /** The WORST (highest) `data_age_seconds` observed across all 9 stations. */
  maxAgeSeconds: number
}

/**
 * F-08 staleness banner. Triggers strictly when `maxAgeSeconds > 1800`
 * (matches backend `require_fresh_conditions` gating). Equality at 1800 must
 * NOT trigger — see test "hides at exactly 1800".
 *
 * Renders as `role="alert"` so screen readers announce it on initial render
 * and on subsequent re-render when staleness changes.
 */
export function StalenessBanner({ maxAgeSeconds }: Props) {
  if (maxAgeSeconds <= STALE_THRESHOLD_S) return null

  const minutes = Math.round(maxAgeSeconds / 60)

  return (
    <div
      role="alert"
      data-testid="staleness-banner"
      className="mb-4 rounded-md border border-tide-mid bg-tide-mid/20 p-3 text-sm text-stone-800"
    >
      <p className="font-medium">
        Some conditions are stale ({minutes} min old — more than 30 min threshold).
      </p>
      <p className="mt-1 text-xs text-stone-700">
        The data pipeline may be lagging. Refresh in a few minutes or treat values with care.
      </p>
    </div>
  )
}
