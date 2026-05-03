import { describe, expect, test } from "vitest"
import { render, screen } from "@testing-library/react"
import { ConditionsSnapshot } from "@/components/spot/ConditionsSnapshot"
import type { components } from "@/lib/api-types"

type ConditionsResponse = components["schemas"]["ConditionsResponse"]

const FRESH: ConditionsResponse = {
  station_id: "8534720",
  station_name: "Atlantic City",
  observed_at: "2026-05-02T10:00:00Z",
  data_age_seconds: 420,
  tidal: {
    phase: "incoming",
    current_level_m: 0.45,
    water_temp_c: 12.4,
  },
  weather: {
    wind_speed_ms: 4.2,
    wind_direction_deg: 45,
    surface_pressure_hpa: 1014.5,
    air_temperature_c: 14.1,
    pressure_trend_label: "Falling",
  },
  solunar: {
    moon_phase: 0.3,
    illumination: 0.45,
    lunar_day: 12,
  },
  sunrise: "2026-05-02T05:50:00Z",
  sunset: "2026-05-02T19:55:00Z",
}

describe("ConditionsSnapshot — staleness + WR-02", () => {
  test("renders 'unavailable' stub when conditions prop is null (503/404 branch)", () => {
    render(<ConditionsSnapshot conditions={null} />)
    expect(screen.getByTestId("conditions-snapshot-empty")).toBeDefined()
    expect(
      screen.getByTestId("conditions-snapshot-empty").textContent,
    ).toContain("unavailable")
  })

  test("renders snapshot WITHOUT stale badge when data_age_seconds <= 1800", () => {
    render(<ConditionsSnapshot conditions={FRESH} />)
    expect(screen.getByTestId("conditions-snapshot")).toBeDefined()
    expect(screen.queryByTestId("conditions-stale-badge")).toBeNull()
    expect(screen.getByTestId("conditions-snapshot").textContent).toContain(
      "Atlantic City",
    )
  })

  test("renders stale badge when data_age_seconds > 1800 (P6 staleness threshold)", () => {
    const stale = { ...FRESH, data_age_seconds: 2400 }
    render(<ConditionsSnapshot conditions={stale} />)
    const badge = screen.getByTestId("conditions-stale-badge")
    expect(badge).toBeDefined()
    expect(badge.textContent).toContain("Stale")
    // 2400 / 60 ≈ 40m
    expect(badge.textContent).toContain("40m")
  })

  test("ageSeconds prop overrides conditions.data_age_seconds for staleness check", () => {
    // conditions has fresh 420s; ageSeconds prop pushes it stale.
    render(<ConditionsSnapshot conditions={FRESH} ageSeconds={3600} />)
    expect(screen.getByTestId("conditions-stale-badge")).toBeDefined()
    expect(
      screen.getByTestId("conditions-stale-badge").textContent,
    ).toContain("60m")
  })

  test("WR-02: missing solunar.moon_phase renders '—' (NEVER coalesced to 0)", () => {
    const noMoon: ConditionsResponse = {
      ...FRESH,
      solunar: { ...FRESH.solunar, moon_phase: null },
    }
    render(<ConditionsSnapshot conditions={noMoon} />)
    const snap = screen.getByTestId("conditions-snapshot")
    // The dt 'Moon phase' is followed by a dd with the value
    expect(snap.textContent).toContain("Moon phase")
    expect(snap.textContent).toContain("—")
    // Critically: must NOT contain a literal "0" in the moon-phase slot.
    // Probe: textContent should not include "Moon phase0" (the dt+dd join).
    expect(snap.textContent).not.toContain("Moon phase0")
  })

  test("WR-02: missing tidal.current_level_m renders '—' (numeric formatter)", () => {
    const noLevel: ConditionsResponse = {
      ...FRESH,
      tidal: { ...FRESH.tidal, current_level_m: null },
    }
    render(<ConditionsSnapshot conditions={noLevel} />)
    const snap = screen.getByTestId("conditions-snapshot")
    expect(snap.textContent).toContain("Water level")
    expect(snap.textContent).toContain("—")
  })
})
