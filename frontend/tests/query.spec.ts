import { test, expect } from "@playwright/test"

// Plan 05 introduced the F-16 / L-13 freshness rule: ≥2 citations within 14 days
// must back the recommendation. Use dynamic dates so this test doesn't drift.
const today = new Date().toISOString().slice(0, 10)
const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10)

const SSE_HAPPY = [
  `event: progress\ndata: {"stage":"planner"}\n\n`,
  `event: progress\ndata: {"stage":"data_fetcher"}\n\n`,
  `event: partial_conditions\ndata: {"spot_id":7,"spot_name":"Barnegat Inlet","ml_score":0.81,"shap_top3":["a","b","c"],"data_age_seconds":420.0,"conditions_stale":false,"conditions":{"wind_kt":8.2}}\n\n`,
  `event: progress\ndata: {"stage":"rag_retriever"}\n\n`,
  `event: progress\ndata: {"stage":"synthesizer"}\n\n`,
  `event: recommendation\ndata: {"recommendation_text":"Try Barnegat Inlet Saturday 6:30-9am.","citations":[{"source":"NJF","date":"${today}","chunk_id":"njf-001"},{"source":"SO","date":"${yesterday}","chunk_id":"so-001"}],"confidence_label":"High","retrieval_ok":true,"ml_score_available":true,"conditions_stale":false,"data_age_seconds":420,"spot_id":7,"spot_name":"Barnegat Inlet","ml_score":0.81,"shap_top3":["a","b","c"],"rag_latency_ms":380,"species_canonical":"striper","time_window_label":"Saturday morning"}\n\n`,
].join("")

test.describe("/ — query loop", () => {
  test("submits a query and renders the recommendation", async ({ page }) => {
    await page.route("**/api/v1/query", (route) =>
      route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: SSE_HAPPY,
      }),
    )
    await page.goto("/")
    // Plan 05: app/page.tsx now renders <RecommendationCard> on done (replacing
    // the recommendation-placeholder div from Plan 04).
    const sheet = page.getByTestId("query-sheet-trigger")
    if (await sheet.isVisible().catch(() => false)) await sheet.click()
    await page.getByTestId("query-input").first().fill("stripers at barnegat saturday")
    await page.getByTestId("query-submit").first().click()
    await expect(page.getByTestId("recommendation-card")).toBeVisible({ timeout: 5000 })
    await expect(page.getByTestId("recommendation-card")).toContainText("Barnegat Inlet")
  })

  test("rate-limit error shows friendly copy + dismiss", async ({ page }) => {
    const SSE_RL = `event: error\ndata: {"code":"rate_limited","message":"slow down"}\n\n`
    await page.route("**/api/v1/query", (route) =>
      route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: SSE_RL,
      }),
    )
    await page.goto("/")
    await page.getByTestId("query-input").first().fill("test")
    await page.getByTestId("query-submit").first().click()
    await expect(page.getByTestId("query-error")).toContainText("20-queries-per-hour")
  })

  test("history chip re-issues a saved query", async ({ page }) => {
    await page.addInitScript(() => {
      window.sessionStorage.setItem(
        "tide.history.last5",
        JSON.stringify(["fluke at sandy hook"]),
      )
    })
    await page.route("**/api/v1/query", (route) =>
      route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: SSE_HAPPY,
      }),
    )
    await page.goto("/")
    await page.getByTestId("history-chip").first().click()
    await expect(page.getByTestId("recommendation-card")).toBeVisible({ timeout: 5000 })
  })
})
