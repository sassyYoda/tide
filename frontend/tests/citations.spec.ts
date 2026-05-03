import { test, expect } from "@playwright/test"

const today = new Date().toISOString().slice(0, 10)
const d1 = new Date(Date.now() - 86400000).toISOString().slice(0, 10)
const d2 = new Date(Date.now() - 2 * 86400000).toISOString().slice(0, 10)

const SSE_HAPPY = [
  `event: recommendation\ndata: {"recommendation_text":"Try Barnegat.","citations":[{"source":"NJF","date":"${today}","chunk_id":null},{"source":"SO","date":"${d1}","chunk_id":null},{"source":"NJF","date":"${d2}","chunk_id":null}],"confidence_label":"High","retrieval_ok":true,"ml_score_available":true,"conditions_stale":false,"data_age_seconds":420,"spot_id":7,"spot_name":"Barnegat Inlet","ml_score":0.81,"shap_top3":["a","b","c"],"rag_latency_ms":null,"species_canonical":"striper","time_window_label":"Saturday"}\n\n`,
].join("")

async function fillAndSubmit(page: import("@playwright/test").Page) {
  const trigger = page.getByTestId("query-sheet-trigger")
  if (await trigger.isVisible().catch(() => false)) {
    await trigger.click()
  }
  await page.getByTestId("query-input").first().fill("test")
  await page.getByTestId("query-submit").first().click()
}

test.describe("F-10 — Citations panel: Sheet desktop, Dialog mobile", () => {
  test("desktop project shows Sheet trigger", async ({ page }, testInfo) => {
    test.skip(!testInfo.project.name.includes("desktop"), "desktop-only")
    await page.route("**/api/v1/query", (r) =>
      r.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: SSE_HAPPY,
      }),
    )
    await page.goto("/")
    await fillAndSubmit(page)
    await expect(page.getByTestId("citations-trigger-desktop")).toBeVisible({
      timeout: 5000,
    })
    await expect(page.getByTestId("citations-trigger-mobile")).not.toBeVisible()
  })

  test("mobile project shows Dialog trigger", async ({ page }, testInfo) => {
    test.skip(!testInfo.project.name.includes("mobile"), "mobile-only")
    await page.route("**/api/v1/query", (r) =>
      r.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: SSE_HAPPY,
      }),
    )
    await page.goto("/")
    await fillAndSubmit(page)
    await expect(page.getByTestId("citations-trigger-mobile")).toBeVisible({
      timeout: 5000,
    })
    await expect(page.getByTestId("citations-trigger-desktop")).not.toBeVisible()
  })

  test("opens panel and lists 3 citations", async ({ page }) => {
    await page.route("**/api/v1/query", (r) =>
      r.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: SSE_HAPPY,
      }),
    )
    await page.goto("/")
    await fillAndSubmit(page)
    await expect(page.getByTestId("recommendation-card")).toBeVisible({ timeout: 5000 })
    // Use whichever trigger is visible for the active project
    const triggers = page.getByTestId(/citations-trigger-/)
    const visibleTrigger = triggers.first()
    await visibleTrigger.click()
    await expect(page.getByTestId("citations-list")).toBeVisible()
    await expect(page.getByTestId("citations-list").locator("li")).toHaveCount(3)
  })
})
