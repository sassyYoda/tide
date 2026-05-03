import { describe, expect, test, beforeEach } from "vitest"
import { render, screen, renderHook, act } from "@testing-library/react"
import { StalenessBanner } from "@/components/conditions/StalenessBanner"
import { StationCard } from "@/components/conditions/StationCard"
import { useConditionsCache, type ConditionsResult } from "@/lib/useConditionsCache"
import { NJ_STATIONS, STALE_THRESHOLD_S } from "@/lib/nj-stations"
import type { components } from "@/lib/api-types"

type ConditionsResponse = components["schemas"]["ConditionsResponse"]
type ErrorEnvelope = components["schemas"]["ErrorEnvelope"]

// ─── F-08 trigger semantics ─────────────────────────────────────────────────

describe("StalenessBanner — F-08 > 30 min trigger", () => {
  test("hides when maxAgeSeconds = 600 (fresh, 10 min)", () => {
    render(<StalenessBanner maxAgeSeconds={600} />)
    expect(screen.queryByTestId("staleness-banner")).toBeNull()
  })

  test("hides at exactly 1800 (strict >, equality must NOT trigger)", () => {
    render(<StalenessBanner maxAgeSeconds={1800} />)
    expect(screen.queryByTestId("staleness-banner")).toBeNull()
  })

  test("shows when maxAgeSeconds = 1801 (just past threshold)", () => {
    render(<StalenessBanner maxAgeSeconds={1801} />)
    const banner = screen.getByTestId("staleness-banner")
    expect(banner).toBeVisible()
    expect(banner.getAttribute("role")).toBe("alert")
  })

  test("formats minutes when maxAge = 2400 (40 min stale) and references 30-min threshold", () => {
    render(<StalenessBanner maxAgeSeconds={2400} />)
    const banner = screen.getByTestId("staleness-banner")
    expect(banner.textContent).toMatch(/40/)
    expect(banner.textContent).toMatch(/stale|30 min/i)
  })

  test("STALE_THRESHOLD_S equals 1800", () => {
    expect(STALE_THRESHOLD_S).toBe(1800)
  })
})

// ─── F-14 sessionStorage cache (P7 enforcement) ─────────────────────────────

describe("useConditionsCache — sessionStorage only (P7)", () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    window.localStorage.clear()
  })

  test("read() returns null when no cache exists", () => {
    const { result } = renderHook(() => useConditionsCache())
    expect(result.current.read()).toBeNull()
  })

  test("set() then read() round-trips entries with fetchedAt timestamp", () => {
    const { result } = renderHook(() => useConditionsCache())
    const entries: ConditionsResult[] = [
      { ok: false, station_id: "8531680", status: 503, envelope: null },
    ]
    act(() => {
      result.current.set(entries)
    })
    const cached = result.current.read()
    expect(cached?.entries).toHaveLength(1)
    expect(cached?.fetchedAt).toMatch(/^\d{4}-\d{2}-\d{2}T/)
  })

  test("set() does NOT touch localStorage (P7)", () => {
    const { result } = renderHook(() => useConditionsCache())
    act(() => {
      result.current.set([{ ok: false, station_id: "x", status: 503, envelope: null }])
    })
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.getItem("tide.conditions.snapshot")).toBeTruthy()
  })

  test("clear() removes the cache entry", () => {
    const { result } = renderHook(() => useConditionsCache())
    act(() => {
      result.current.set([{ ok: false, station_id: "x", status: 503, envelope: null }])
    })
    expect(result.current.read()).not.toBeNull()
    act(() => {
      result.current.clear()
    })
    expect(result.current.read()).toBeNull()
  })
})

// ─── NJ_STATIONS — Phase 1 seed mirror ───────────────────────────────────────

describe("NJ_STATIONS — Phase 1 seed mirror", () => {
  test("contains exactly 9 entries", () => {
    expect(NJ_STATIONS).toHaveLength(9)
  })

  test("each entry has a non-empty id and name", () => {
    for (const s of NJ_STATIONS) {
      expect(s.id).toMatch(/^\d+$/)
      expect(s.name.length).toBeGreaterThan(0)
    }
  })

  test("includes the canonical NJ Sandy Hook + Cape May anchor IDs", () => {
    const ids = NJ_STATIONS.map((s) => s.id)
    expect(ids).toContain("8531680") // Sandy Hook
    expect(ids).toContain("8536110") // Cape May
  })
})

// ─── StationCard — 200 / 503 / 404 branches ─────────────────────────────────

function makeFreshResponse(overrides: Partial<ConditionsResponse> = {}): ConditionsResponse {
  return {
    station_id: "8531680",
    station_name: "Sandy Hook",
    observed_at: "2026-05-02T13:55:00Z",
    data_age_seconds: 600,
    tidal: {
      phase: "incoming",
      current_level_m: 0.42,
      water_temp_c: 12.4,
      next_high: null,
      next_low: null,
    },
    weather: {
      wind_speed_ms: 3.2,
      wind_direction_deg: 90,
      surface_pressure_hpa: 1014,
      air_temperature_c: 14,
      precipitation_prob_pct: 5,
      cloud_cover_pct: 25,
      pressure_delta_1h: 0.1,
      pressure_delta_3h: 0.2,
      pressure_delta_6h: 0.3,
      pressure_trend_label: "Rising",
    },
    solunar: {
      moon_phase: 0.3,
      illumination: 0.45,
      lunar_day: 12,
      next_major_start: null,
      next_major_end: null,
      next_minor_start: null,
      next_minor_end: null,
      quality_score: 0.6,
    },
    sunrise: "2026-05-02T05:48:00Z",
    sunset: "2026-05-02T19:52:00Z",
    ...overrides,
  }
}

describe("StationCard — 200 OK rendering + WR-02", () => {
  test("renders station_name, observed_at, tidal current_level_m, and wind_speed_ms", () => {
    const data = makeFreshResponse()
    render(
      <StationCard
        result={{ ok: true, station_id: data.station_id, data }}
        stationName="Sandy Hook"
      />,
    )
    expect(screen.getByText(/Sandy Hook/)).toBeInTheDocument()
    expect(screen.getByText(/2026-05-02T13:55:00Z/)).toBeInTheDocument()
    // current_level_m formatted
    expect(screen.getByText(/0\.42 m/)).toBeInTheDocument()
    // wind_speed_ms formatted
    expect(screen.getByText(/3\.2 m\/s/)).toBeInTheDocument()
  })

  test("WR-02: moon_phase = null renders as '—' (NOT 0)", () => {
    const data = makeFreshResponse({
      solunar: {
        moon_phase: null,
        illumination: 0.45,
        lunar_day: 12,
        next_major_start: null,
        next_major_end: null,
        next_minor_start: null,
        next_minor_end: null,
        quality_score: 0.6,
      },
    })
    render(
      <StationCard
        result={{ ok: true, station_id: data.station_id, data }}
        stationName="Sandy Hook"
      />,
    )
    expect(screen.getByTestId("moon-phase").textContent).toBe("—")
  })

  test("WR-02: moon_phase = 0 renders as '0.0' (real new-moon, NOT '—')", () => {
    const data = makeFreshResponse({
      solunar: {
        moon_phase: 0,
        illumination: 0,
        lunar_day: 0,
        next_major_start: null,
        next_major_end: null,
        next_minor_start: null,
        next_minor_end: null,
        quality_score: null,
      },
    })
    render(
      <StationCard
        result={{ ok: true, station_id: data.station_id, data }}
        stationName="Sandy Hook"
      />,
    )
    // 0 must NOT be coalesced to '—' — it's a real new-moon reading
    expect(screen.getByTestId("moon-phase").textContent).not.toBe("—")
  })

  test("renders per-card stale chip when data_age_seconds > 1800", () => {
    const data = makeFreshResponse({ data_age_seconds: 2400 })
    render(
      <StationCard
        result={{ ok: true, station_id: data.station_id, data }}
        stationName="Sandy Hook"
      />,
    )
    expect(screen.getByTestId("card-stale-chip")).toBeVisible()
  })
})

describe("StationCard — 503 stale envelope", () => {
  test("renders per-card stale chip + latest_bucket from envelope", () => {
    const envelope: ErrorEnvelope = {
      code: "conditions_stale",
      message: "Bucket > 30 min old",
      latest_bucket: "2026-05-02T08:00:00Z",
    }
    render(
      <StationCard
        result={{ ok: false, station_id: "8531680", status: 503, envelope }}
        stationName="Sandy Hook"
      />,
    )
    expect(screen.getByTestId("card-stale-chip")).toBeVisible()
    expect(screen.getByText(/2026-05-02T08:00:00Z/)).toBeInTheDocument()
    expect(screen.getByText(/Sandy Hook/)).toBeInTheDocument()
  })

  test("renders without crashing when envelope is null", () => {
    render(
      <StationCard
        result={{ ok: false, station_id: "8531680", status: 503, envelope: null }}
        stationName="Sandy Hook"
      />,
    )
    expect(screen.getByTestId("card-stale-chip")).toBeVisible()
  })
})

describe("StationCard — 404 unreachable envelope", () => {
  test("renders 'Station unreachable' stub without crashing", () => {
    const envelope: ErrorEnvelope = {
      code: "station_not_found",
      message: "Station unknown",
      latest_bucket: null,
    }
    render(
      <StationCard
        result={{ ok: false, station_id: "9999999", status: 404, envelope }}
        stationName="Mystery Station"
      />,
    )
    expect(screen.getByTestId("station-unreachable")).toBeVisible()
    expect(screen.getByText(/Mystery Station/)).toBeInTheDocument()
  })
})
