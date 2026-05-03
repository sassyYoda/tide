import { test, expect } from "@playwright/test"

// Build dates dynamically so tests stay fresh-citation (≤ 14 days) forever.
const today = new Date().toISOString().slice(0, 10)
const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10)

const SSE_HAPPY = [
  `event: progress\ndata: {"stage":"planner"}\n\n`,
  `event: recommendation\ndata: {"recommendation_text":"Try Barnegat.","citations":[{"source":"NJF","date":"${today}","chunk_id":null},{"source":"SO","date":"${yesterday}","chunk_id":null}],"confidence_label":"High","retrieval_ok":true,"ml_score_available":true,"conditions_stale":false,"data_age_seconds":420,"spot_id":7,"spot_name":"Barnegat Inlet","ml_score":0.81,"shap_top3":["outgoing_tide","ne_wind","falling_pressure"],"rag_latency_ms":null,"species_canonical":"striper","time_window_label":"Saturday"}\n\n`,
].join("")

async function fillAndSubmit(page: import("@playwright/test").Page) {
  // Mobile projects render input behind a Sheet trigger; desktop projects show input inline.
  const trigger = page.getByTestId("query-sheet-trigger")
  if (await trigger.isVisible().catch(() => false)) {
    await trigger.click()
  }
  await page.getByTestId("query-input").first().fill("test")
  await page.getByTestId("query-submit").first().click()
}

test.describe("F-12 — Show reasoning toggle", () => {
  test("reveals SHAP top-3 INLINE (NOT in a modal)", async ({ page }) => {
    await page.route("**/api/v1/query", (route) =>
      route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: SSE_HAPPY,
      }),
    )
    await page.goto("/")
    await fillAndSubmit(page)
    await expect(page.getByTestId("recommendation-card")).toBeVisible({ timeout: 5000 })

    // Panel hidden initially
    await expect(page.getByTestId("reasoning-panel")).not.toBeVisible()
    // Click toggle
    await page.getByTestId("show-reasoning-toggle").click()
    // L-12: panel is INLINE inside the card — NOT a dialog/modal
    const panel = page.getByTestId("reasoning-panel")
    await expect(panel).toBeVisible()
    // Panel must be a descendant of the recommendation card (inline reveal)
    const isInsideCard = await panel.evaluate((node) => {
      const card = node.closest("[data-testid='recommendation-card']")
      return card !== null
    })
    expect(isInsideCard).toBe(true)
    // Panel must NOT have role="dialog"
    await expect(panel).not.toHaveAttribute("role", "dialog")
    // SHAP top-3 features visible
    await expect(panel).toContainText("outgoing_tide")
    await expect(panel).toContainText("ne_wind")
    await expect(panel).toContainText("falling_pressure")
  })
})
