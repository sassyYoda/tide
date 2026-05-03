import { test, expect } from "@playwright/test"

/**
 * F-14 — Offline cache + sticky-top OfflineBanner from layout.tsx.
 * The per-page `offline-cache-banner` is owned by ConditionsGrid (Plan 07);
 * the sticky-top `offline-banner` is owned by RootLayout (Plan 08).
 */
const FRESH_BODY = (id: string) => ({
  station_id: id,
  station_name: `Station ${id}`,
  observed_at: "2026-05-02T10:00:00Z",
  data_age_seconds: 600,
  tidal: {
    phase: "incoming",
    current_level_m: 0.5,
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

test.describe("F-14 — Offline cache + banner", () => {
  test("offline reload of /conditions hydrates from sessionStorage with banner", async ({
    page,
    context,
  }) => {
    // Prime cache online — stub the 9-station fan-out.
    await page.route("**/api/v1/conditions/*", (route) => {
      const url = new URL(route.request().url())
      const id = url.pathname.split("/").pop() ?? "x"
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(FRESH_BODY(id)),
      })
    })
    await page.goto("/conditions")
    await expect(page.getByTestId("station-card")).toHaveCount(9, {
      timeout: 10_000,
    })

    // Go offline + reload — the page should hydrate from sessionStorage.
    await context.setOffline(true)
    await page.reload()

    // Sticky-top OfflineBanner (from layout.tsx — Plan 08)
    await expect(page.getByTestId("offline-banner")).toBeVisible({ timeout: 5_000 })
    await expect(page.getByTestId("offline-banner")).toContainText(/Last cached/)

    // Per-page cache banner (from ConditionsGrid — Plan 07)
    await expect(page.getByTestId("offline-cache-banner")).toBeVisible()

    // 9 cards still rendered from sessionStorage cache
    await expect(page.getByTestId("station-card")).toHaveCount(9)
  })

  test("offline visit of / surfaces banner with last-query history hint", async ({
    page,
    context,
  }) => {
    // Seed the last-5 history cache before navigating.
    await page.addInitScript(() => {
      window.sessionStorage.setItem(
        "tide.history.last5",
        JSON.stringify(["fluke at sandy hook"])
      )
    })
    await page.goto("/")
    await context.setOffline(true)
    await page.reload()
    await expect(page.getByTestId("offline-banner")).toBeVisible({ timeout: 5_000 })
    await expect(page.getByTestId("offline-banner")).toContainText(
      /Last query history available/
    )
  })
})
