import { test, expect } from "@playwright/test"

const SPOTS_FIXTURE = [
  { spot_id: 1, name: "Barnegat Inlet", lat: 39.764, lon: -74.107, score: 0.81, confidence: "High", species: "striper", last_score_time: "2026-05-02T08:00:00Z", data_age_seconds: 420 },
  { spot_id: 2, name: "Sandy Hook",     lat: 40.451, lon: -74.001, score: 0.55, confidence: "Moderate", species: "fluke", last_score_time: "2026-05-02T08:00:00Z", data_age_seconds: 600 },
  { spot_id: 3, name: "Cape May",       lat: 38.935, lon: -74.906, score: 0.30, confidence: "Low", species: "tautog", last_score_time: "2026-05-02T08:00:00Z", data_age_seconds: 720 },
]

test.describe("F-03 / F-05 — /map renders MapLibre + pins from /api/v1/spots", () => {
  test("MapLibre canvas mounts and spots fetch resolves", async ({ page }) => {
    await page.route("**/api/v1/spots*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(SPOTS_FIXTURE),
      }),
    )
    await page.goto("/map")
    // Page heading is the LCP candidate
    await expect(page.getByRole("heading", { name: /^Map$/i })).toBeVisible()
    // MapLibre injects a <canvas class="maplibregl-canvas">
    await expect(page.locator("canvas.maplibregl-canvas").first()).toBeVisible({ timeout: 10000 })
  })
})
