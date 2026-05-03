"use client"
import type { components } from "@/lib/api-types"

type ConditionsResponse = components["schemas"]["ConditionsResponse"]

interface Props {
  conditions: ConditionsResponse | null // null when fetch failed / 503 / 404
  ageSeconds?: number
}

function fmt(value: number | null | undefined, suffix = ""): string {
  if (value == null) return "—"
  return `${value.toFixed(1)}${suffix}`
}

export function ConditionsSnapshot({ conditions, ageSeconds }: Props) {
  if (conditions == null) {
    return (
      <section
        data-testid="conditions-snapshot-empty"
        className="rounded-md border border-stone-300 bg-stone-50 p-3 text-sm text-stone-600"
      >
        <p>Conditions snapshot unavailable for this spot.</p>
      </section>
    )
  }

  // P6 / WR-02: data_age_seconds > 1800 = stale; do NOT coalesce moon_phase to 0.
  const effectiveAge = ageSeconds ?? conditions.data_age_seconds
  const stale = effectiveAge > 1800

  return (
    <section
      data-testid="conditions-snapshot"
      className="rounded-md border border-stone-200 bg-white p-3"
    >
      <header className="mb-2 flex items-center justify-between">
        <h3 className="font-display text-sm uppercase tracking-wide text-stone-700">
          Live conditions — {conditions.station_name}
        </h3>
        {stale && (
          <span
            data-testid="conditions-stale-badge"
            className="rounded bg-tide-mid/30 px-2 py-0.5 text-xs text-stone-700"
          >
            Stale ({Math.round(effectiveAge / 60)}m)
          </span>
        )}
      </header>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-stone-700">
        <dt className="font-medium">Water level</dt>
        <dd>{fmt(conditions.tidal?.current_level_m, " m")}</dd>
        <dt className="font-medium">Water temp</dt>
        <dd>{fmt(conditions.tidal?.water_temp_c, "°C")}</dd>
        <dt className="font-medium">Wind</dt>
        <dd>
          {fmt(conditions.weather?.wind_speed_ms, " m/s")}
          {conditions.weather?.wind_direction_deg != null
            ? ` @${Math.round(conditions.weather.wind_direction_deg)}°`
            : ""}
        </dd>
        <dt className="font-medium">Pressure</dt>
        <dd>{fmt(conditions.weather?.surface_pressure_hpa, " hPa")}</dd>
        <dt className="font-medium">Air temp</dt>
        <dd>{fmt(conditions.weather?.air_temperature_c, "°C")}</dd>
        <dt className="font-medium">Moon phase</dt>
        {/* WR-02: do NOT coalesce null to 0 — render — to signal missing */}
        <dd>{conditions.solunar?.moon_phase ?? "—"}</dd>
      </dl>
    </section>
  )
}
