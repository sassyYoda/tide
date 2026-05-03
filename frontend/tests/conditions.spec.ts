import { test, expect } from "@playwright/test"

/**
 * Build a ConditionsResponse-shaped body. Tests stub the route so the backend
 * doesn't have to be live (independent of BACKEND_LIVE).
 */
const FRESH_BODY = (id: string, ageSeconds: number) => ({
  station_id: id,
  station_name: `Station ${id}`,
  observed_at: "2026-05-02T13:55:00Z",
  data_age_seconds: ageSeconds,
  tidal: {
    phase: "incoming",
    current_level_m: 0.42,
    water_temp_c: 12.4,
    next_high: null,
    next_high_level_m: null,
    next_low: null,
    next_low_level_m: null,
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
  sunrise: "2026-05-02T05:50:00Z",
  sunset: "2026-05-02T19:55:00Z",
})

test.describe("F-08 — /conditions page", () => {
  test("renders 9 station cards with no banner when all fresh", async ({ page }) => {
    await page.route("**/api/v1/conditions/*", (route) => {
      const url = new URL(route.request().url())
      const id = url.pathname.split("/").pop() ?? "unknown"
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(FRESH_BODY(id, 600)),
      })
    })
    await page.goto("/conditions")
    await expect(page.getByTestId("station-card")).toHaveCount(9, {
      timeout: 10_000,
    })
    // No staleness banner because all stations are 10 min old (< 30 min).
    await expect(page.getByTestId("staleness-banner")).toHaveCount(0)
  })

  test("StalenessBanner appears when ANY station > 30 min stale", async ({ page }) => {
    let count = 0
    await page.route("**/api/v1/conditions/*", (route) => {
      const url = new URL(route.request().url())
      const id = url.pathname.split("/").pop() ?? "unknown"
      const age = count === 0 ? 2400 : 600
      count += 1
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(FRESH_BODY(id, age)),
      })
    })
    await page.goto("/conditions")
    await expect(page.getByTestId("station-card")).toHaveCount(9, {
      timeout: 10_000,
    })
    await expect(page.getByTestId("staleness-banner")).toBeVisible()
    await expect(page.getByTestId("staleness-banner")).toContainText(/40/)
    await expect(page.getByTestId("card-stale-chip").first()).toBeVisible()
  })

  test("503 + 404 per-card branches do NOT crash the page", async ({ page }) => {
    let i = 0
    await page.route("**/api/v1/conditions/*", (route) => {
      const url = new URL(route.request().url())
      const id = url.pathname.split("/").pop() ?? "unknown"
      const turn = i++
      if (turn === 0) {
        return route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({
            detail: {
              code: "conditions_stale",
              message: "Bucket > 30 min old",
              latest_bucket: "2026-05-02T08:00:00Z",
            },
          }),
        })
      }
      if (turn === 1) {
        return route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({
            detail: {
              code: "station_not_found",
              message: "Station unknown",
              latest_bucket: null,
            },
          }),
        })
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(FRESH_BODY(id, 600)),
      })
    })
    await page.goto("/conditions")
    await expect(page.getByTestId("station-card")).toHaveCount(9, {
      timeout: 10_000,
    })
    await expect(page.getByTestId("card-stale-chip").first()).toBeVisible()
    await expect(page.getByTestId("station-unreachable")).toHaveCount(1)
    // Banner triggers because the 503 is treated as definitely stale.
    await expect(page.getByTestId("staleness-banner")).toBeVisible()
  })

  test("offline path renders cached snapshot with offline-cache-banner", async ({
    page,
    context,
  }) => {
    await page.route("**/api/v1/conditions/*", (route) => {
      const url = new URL(route.request().url())
      const id = url.pathname.split("/").pop() ?? "unknown"
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(FRESH_BODY(id, 600)),
      })
    })
    await page.goto("/conditions")
    await expect(page.getByTestId("station-card")).toHaveCount(9, {
      timeout: 10_000,
    })
    const cached = await page.evaluate(() =>
      window.sessionStorage.getItem("tide.conditions.snapshot"),
    )
    expect(cached).toBeTruthy()

    await context.setOffline(true)
    await page.reload()
    await expect(page.getByTestId("offline-cache-banner")).toBeVisible({
      timeout: 5_000,
    })
    await expect(page.getByTestId("station-card")).toHaveCount(9)
  })

  test("WR-02: missing moon_phase renders as '—' (NOT 0)", async ({ page }) => {
    await page.route("**/api/v1/conditions/*", (route) => {
      const url = new URL(route.request().url())
      const id = url.pathname.split("/").pop() ?? "unknown"
      const body = FRESH_BODY(id, 600)
      ;(body.solunar as Record<string, unknown>).moon_phase = null
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      })
    })
    await page.goto("/conditions")
    await expect(page.getByTestId("station-card").first()).toBeVisible({
      timeout: 10_000,
    })
    await expect(page.getByTestId("moon-phase").first()).toHaveText("—")
  })
})
