import { test, expect } from "@playwright/test"

const today = new Date().toISOString().slice(0, 10)
// 60-day-old citation = STALE; freshCount === 0 → EmptyState fires.
const stale = new Date(Date.now() - 60 * 86400000).toISOString().slice(0, 10)

// Case A: only 1 fresh citation → freshCount < 2 → EmptyState
const SSE_ONE_FRESH = [
  `event: recommendation\ndata: {"recommendation_text":"Maybe try this.","citations":[{"source":"NJF","date":"${today}","chunk_id":null}],"confidence_label":"Low","retrieval_ok":true,"ml_score_available":false,"conditions_stale":false,"data_age_seconds":420,"spot_id":null,"spot_name":null,"ml_score":null,"shap_top3":null,"rag_latency_ms":null,"species_canonical":null,"time_window_label":null}\n\n`,
].join("")

// Case B: 3 citations but ALL stale (> 14 days) → freshCount === 0 → EmptyState
// (proves the rule is freshness, not raw citations.length)
const SSE_ALL_STALE = [
  `event: recommendation\ndata: {"recommendation_text":"Maybe try this.","citations":[{"source":"NJF","date":"${stale}","chunk_id":null},{"source":"SO","date":"${stale}","chunk_id":null},{"source":"NJF","date":"${stale}","chunk_id":null}],"confidence_label":"Low","retrieval_ok":true,"ml_score_available":false,"conditions_stale":false,"data_age_seconds":420,"spot_id":null,"spot_name":null,"ml_score":null,"shap_top3":null,"rag_latency_ms":null,"species_canonical":null,"time_window_label":null}\n\n`,
].join("")

// Case C: retrieval_ok = false (regardless of citation count) → EmptyState
const SSE_RETRIEVAL_FAIL = [
  `event: recommendation\ndata: {"recommendation_text":"x","citations":[{"source":"NJF","date":"${today}","chunk_id":null},{"source":"SO","date":"${today}","chunk_id":null}],"confidence_label":"Low","retrieval_ok":false,"ml_score_available":false,"conditions_stale":false,"data_age_seconds":420,"spot_id":null,"spot_name":null,"ml_score":null,"shap_top3":null,"rag_latency_ms":null,"species_canonical":null,"time_window_label":null}\n\n`,
].join("")

async function fillAndSubmit(page: import("@playwright/test").Page) {
  const trigger = page.getByTestId("query-sheet-trigger")
  if (await trigger.isVisible().catch(() => false)) {
    await trigger.click()
  }
  await page.getByTestId("query-input").first().fill("trout")
  await page.getByTestId("query-submit").first().click()
}

test.describe("F-16 / L-13 — Empty state when fresh citations < 2", () => {
  test("only 1 fresh citation → locked copy + card suppressed", async ({ page }) => {
    await page.route("**/api/v1/query", (r) =>
      r.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: SSE_ONE_FRESH,
      }),
    )
    await page.goto("/")
    await fillAndSubmit(page)
    await expect(page.getByTestId("empty-state")).toBeVisible({ timeout: 5000 })
    await expect(page.getByTestId("empty-state")).toContainText(
      "Not enough recent local reports to recommend a spot",
    )
    await expect(page.getByTestId("recommendation-card")).not.toBeVisible()
  })

  test("3 STALE citations (all > 14 days) → empty state (proves freshness, not count)", async ({
    page,
  }) => {
    await page.route("**/api/v1/query", (r) =>
      r.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: SSE_ALL_STALE,
      }),
    )
    await page.goto("/")
    await fillAndSubmit(page)
    await expect(page.getByTestId("empty-state")).toBeVisible({ timeout: 5000 })
    await expect(page.getByTestId("recommendation-card")).not.toBeVisible()
  })

  test("retrieval_ok = false → empty state regardless of citation count", async ({
    page,
  }) => {
    await page.route("**/api/v1/query", (r) =>
      r.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: SSE_RETRIEVAL_FAIL,
      }),
    )
    await page.goto("/")
    await fillAndSubmit(page)
    await expect(page.getByTestId("empty-state")).toBeVisible({ timeout: 5000 })
    await expect(page.getByTestId("recommendation-card")).not.toBeVisible()
  })
})
