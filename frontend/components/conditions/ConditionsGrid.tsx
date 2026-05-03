"use client"
import { StalenessBanner } from "./StalenessBanner"
import { StationCard } from "./StationCard"
import type { ConditionsResult } from "@/lib/useConditionsCache"
import type { NJStation } from "@/lib/nj-stations"
import { STALE_THRESHOLD_S } from "@/lib/nj-stations"

interface Props {
  results: ConditionsResult[]
  stations: ReadonlyArray<NJStation>
  /** When non-null, indicates the grid is rendering from sessionStorage cache
   * (offline path) — surfaces an "offline-cache-banner" with the timestamp. */
  cachedAt?: string | null
}

/**
 * 9-station responsive grid. Owns:
 *
 *   - Top StalenessBanner (F-08): triggers when ANY station's age > 1800.
 *     A 503 result is treated as "definitely stale" — surfaces banner with a
 *     synthetic age (>30 min) so the message renders.
 *   - Optional offline-cache-banner (F-14 groundwork): rendered when
 *     `cachedAt` prop is non-null.
 *   - The grid itself: 1-col mobile / 2-col tablet / 3-col desktop.
 */
export function ConditionsGrid({ results, stations, cachedAt }: Props) {
  const okAges = results
    .filter((r): r is Extract<ConditionsResult, { ok: true }> => r.ok)
    .map((r) => r.data.data_age_seconds)
  const has503 = results.some((r) => !r.ok && r.status === 503)
  // If any 503 → treat as "definitely stale" — synthesize an age past the
  // threshold so StalenessBanner fires. 60 min is comfortably > 1800s.
  const maxAge = has503
    ? Math.max(STALE_THRESHOLD_S * 2, ...okAges)
    : okAges.length > 0
    ? Math.max(...okAges)
    : 0

  // station-id → display name map (so 404 cards still show a friendly name).
  const nameById = new Map(stations.map((s) => [s.id, s.name]))

  return (
    <div data-testid="conditions-grid" className="space-y-4">
      {cachedAt && (
        <div
          role="status"
          data-testid="offline-cache-banner"
          className="rounded-md border border-stone-300 bg-stone-50 p-3 text-sm text-stone-700"
        >
          <p className="font-medium">You&apos;re offline.</p>
          <p className="mt-1 text-xs">
            Showing last cached snapshot from{" "}
            <span className="font-mono">{cachedAt}</span>.
          </p>
        </div>
      )}
      <StalenessBanner maxAgeSeconds={maxAge} />
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {results.map((r) => (
          <StationCard
            key={r.station_id}
            result={r}
            stationName={nameById.get(r.station_id) ?? r.station_id}
          />
        ))}
      </section>
    </div>
  )
}
