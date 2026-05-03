import { test, expect } from "@playwright/test"

const SPOTS_MIXED = [
  { spot_id: 10, name: "S1", lat: 39.85, lon: -74.10, score: 0.81, confidence: "High",     species: "striper",  last_score_time: "2026-05-02T08:00:00Z", data_age_seconds: 300 },
  { spot_id: 11, name: "F1", lat: 39.86, lon: -74.11, score: 0.55, confidence: "Moderate", species: "fluke",    last_score_time: "2026-05-02T08:00:00Z", data_age_seconds: 300 },
  { spot_id: 12, name: "B1", lat: 39.87, lon: -74.12, score: 0.50, confidence: "Moderate", species: "bluefish", last_score_time: "2026-05-02T08:00:00Z", data_age_seconds: 300 },
]

test.describe("F-04 — species filter is client-side (no re-fetch)", () => {
  test("toggling a species does NOT issue a new /api/v1/spots request", async ({ page }) => {
    let fetchCount = 0
    await page.route("**/api/v1/spots*", (route) => {
      fetchCount += 1
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(SPOTS_MIXED),
      })
    })
    await page.goto("/map")
    await expect(page.locator("canvas.maplibregl-canvas").first()).toBeVisible({ timeout: 10000 })
    // Allow initial onLoad fetch + any settling onMoveEnd
    await page.waitForTimeout(500)
    const baseline = fetchCount
    expect(baseline).toBeGreaterThanOrEqual(1)

    // Toggle a species checkbox — must NOT issue a new fetch
    await page.getByTestId("species-striper").click()
    await page.waitForTimeout(300)
    expect(fetchCount).toBe(baseline)

    // Toggle another
    await page.getByTestId("species-fluke").click()
    await page.waitForTimeout(300)
    expect(fetchCount).toBe(baseline)
  })

  test("species checkboxes have ARIA labels", async ({ page }) => {
    await page.route("**/api/v1/spots*", (r) =>
      r.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(SPOTS_MIXED),
      }),
    )
    await page.goto("/map")
    for (const s of ["striper", "fluke", "bluefish", "weakfish", "tautog"]) {
      await expect(page.getByTestId(`species-${s}`)).toHaveAttribute("aria-label", `Toggle ${s}`)
    }
  })
})
