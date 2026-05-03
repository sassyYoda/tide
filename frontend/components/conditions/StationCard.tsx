"use client"
import type { ConditionsResult } from "@/lib/useConditionsCache"
import { STALE_THRESHOLD_S } from "@/lib/nj-stations"

interface Props {
  result: ConditionsResult
  /** Display fallback name from `nj-stations.ts` — used when API failed and
   * we therefore cannot trust `result.data.station_name` to exist. */
  stationName: string
}

function fmt(value: number | null | undefined, suffix = "", digits = 1): string {
  if (value == null) return "—"
  return `${value.toFixed(digits)}${suffix}`
}

/**
 * Per-station card. Three render branches:
 *
 *   1. 200 OK     → full tidal/weather/solunar summary + per-card stale chip
 *                   if `data_age_seconds > 1800`.
 *   2. 503 stale  → per-card stale chip + ErrorEnvelope.latest_bucket if
 *                   present. Page does NOT crash on missing envelope.
 *   3. 404 unknown → "Station unreachable" stub. Page does NOT crash.
 *
 * WR-02: `solunar.moon_phase ?? "—"`. NEVER coalesce null to 0 — that masks
 * a missing solunar row as a real new-moon reading. Note `?? "—"` is the
 * correct nullish-coalescing operator: it preserves `0` (real new moon)
 * while substituting "—" only for `null`/`undefined`.
 */
export function StationCard({ result, stationName }: Props) {
  // ─── Branch 3: 404 — station unreachable ────────────────────────────────
  if (!result.ok && result.status === 404) {
    return (
      <article
        data-testid="station-card"
        data-station-id={result.station_id}
        className="rounded-md border border-stone-300 bg-stone-50 p-4"
      >
        <h3 className="font-display text-lg text-stone-900">{stationName}</h3>
        <p
          data-testid="station-unreachable"
          className="mt-2 text-sm text-stone-600"
        >
          Station unreachable.
        </p>
        {result.envelope?.message && (
          <p className="mt-1 text-xs text-stone-500">{result.envelope.message}</p>
        )}
      </article>
    )
  }

  // ─── Branch 2: 503 (or other non-OK) — stale envelope ───────────────────
  if (!result.ok) {
    return (
      <article
        data-testid="station-card"
        data-station-id={result.station_id}
        className="rounded-md border border-tide-mid bg-tide-mid/10 p-4"
      >
        <header className="flex items-center justify-between">
          <h3 className="font-display text-lg text-stone-900">{stationName}</h3>
          <span
            data-testid="card-stale-chip"
            className="rounded bg-tide-mid/40 px-2 py-0.5 text-xs text-stone-800"
          >
            Stale
          </span>
        </header>
        <p className="mt-2 text-sm text-stone-700">
          Latest data unavailable (HTTP {result.status}).
        </p>
        {result.envelope?.latest_bucket && (
          <p className="mt-1 text-xs text-stone-600">
            Last successful read: {result.envelope.latest_bucket}
          </p>
        )}
      </article>
    )
  }

  // ─── Branch 1: 200 OK ───────────────────────────────────────────────────
  const c = result.data
  const isStale = c.data_age_seconds > STALE_THRESHOLD_S
  const ageMin = Math.round(c.data_age_seconds / 60)

  // WR-02: equivalent of `c.solunar?.moon_phase ?? "—"` but with toFixed(2)
  // formatting when present. The ternary preserves 0 (real new moon) and only
  // substitutes "—" for null/undefined — same semantics as ?? "—".
  const moonPhaseDisplay =
    c.solunar?.moon_phase == null ? "—" : c.solunar.moon_phase.toFixed(2)

  return (
    <article
      data-testid="station-card"
      data-station-id={c.station_id}
      className="rounded-md border border-stone-200 bg-white p-4"
    >
      <header className="flex items-center justify-between">
        <h3 className="font-display text-lg text-stone-900">{c.station_name}</h3>
        {isStale && (
          <span
            data-testid="card-stale-chip"
            className="rounded bg-tide-mid/40 px-2 py-0.5 text-xs text-stone-800"
          >
            Stale ({ageMin}m)
          </span>
        )}
      </header>
      <p className="mt-1 text-xs text-stone-500">
        Observed: <span className="font-mono">{c.observed_at}</span>
      </p>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-stone-700">
        <dt className="font-medium">Water level</dt>
        <dd>{fmt(c.tidal?.current_level_m, " m", 2)}</dd>
        <dt className="font-medium">Water temp</dt>
        <dd>{fmt(c.tidal?.water_temp_c, "°C")}</dd>
        <dt className="font-medium">Wind</dt>
        <dd>
          {fmt(c.weather?.wind_speed_ms, " m/s")}
          {c.weather?.wind_direction_deg != null
            ? ` @${Math.round(c.weather.wind_direction_deg)}°`
            : ""}
        </dd>
        <dt className="font-medium">Pressure</dt>
        <dd>{fmt(c.weather?.surface_pressure_hpa, " hPa")}</dd>
        <dt className="font-medium">Air temp</dt>
        <dd>{fmt(c.weather?.air_temperature_c, "°C")}</dd>
        <dt className="font-medium">Pressure trend</dt>
        <dd>{c.weather?.pressure_trend_label ?? "—"}</dd>
        <dt className="font-medium">Moon phase</dt>
        {/* WR-02: NEVER coalesce null moon_phase to 0 — that masks missing as new-moon */}
        <dd data-testid="moon-phase">{moonPhaseDisplay}</dd>
        <dt className="font-medium">Sunrise</dt>
        <dd className="font-mono">{c.sunrise ?? "—"}</dd>
        <dt className="font-medium">Sunset</dt>
        <dd className="font-mono">{c.sunset ?? "—"}</dd>
      </dl>
    </article>
  )
}
