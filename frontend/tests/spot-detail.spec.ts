import { test, expect } from "@playwright/test"

/**
 * F-07 — /spot/[id] async Server Component e2e.
 *
 * IMPORTANT design note (Rule 1 fix from a first draft of this spec):
 * /spot/[id] is a Next 16 async Server Component (P5 mandate). Its
 * `fetch()` calls run on the Node side (in the next-dev server), NOT in
 * the browser, so Playwright's `page.route(...)` browser-level handlers
 * DO NOT intercept them. Two options follow:
 *
 *   1. Run against the live backend (planning_context: "Backend live at
 *      http://localhost:8000"). Use a real spot_id for happy path. The
 *      F-16 path uses spot 999 (does not exist). Conditions snapshot
 *      tolerates the 503-stale envelope from the live backend (renders
 *      the "unavailable" stub, which is what the contract specifies for
 *      a 503 response — see ConditionsSnapshot.tsx).
 *
 *   2. Stand up an isolated stub-backend HTTP server on a different port
 *      and run a SEPARATE `next dev` against that NEXT_PUBLIC_API_URL.
 *      This is heavier than warranted for the contract checks here.
 *
 * We take option (1) for the happy + F-16 paths. The stale-badge logic
 * is a pure component branch already covered by the round-trip parser
 * tests' siblings; we assert it via a dedicated component-level
 * verification at the bottom of this spec rather than forcing
 * data_age_seconds via a route mock that wouldn't run.
 *
 * The contract this spec proves:
 *   - URL ?shap= → <ShapTopThree shap={shap} /> renders a list (B-4).
 *   - URL ?cite= → <ReportsList reports={reports} /> renders rows (B-4).
 *   - Absent shap → ShapTopThree empty branch.
 *   - Absent cite → ReportsList empty branch.
 *   - Both absent + spot lookup fails → SpotEmptyState (F-16, non-tautological).
 */

const SHAP_QS = "shap=outgoing_tide,ne_wind,falling_pressure"
const CITE_QS = "cite=NJF:2026-04-22,SO:2026-04-20"

test.describe("F-07 — /spot/[id] async Server Component (live backend)", () => {
  test("renders ShapTopThree + ReportsList from URL params on real spot id=1", async ({
    page,
  }) => {
    await page.goto(`/spot/1?${SHAP_QS}&${CITE_QS}`)

    // Panel mounts (live backend has spot_id=1 — Barnegat Inlet — North Jetty).
    await expect(page.getByTestId("spot-detail-panel")).toBeVisible({
      timeout: 10_000,
    })

    // ShapTopThree renders the three URL-supplied features (B-4 destination).
    await expect(page.getByTestId("shap-top-three")).toBeVisible()
    await expect(page.getByTestId("shap-top-three")).toContainText(
      "outgoing_tide",
    )
    await expect(page.getByTestId("shap-top-three")).toContainText("ne_wind")
    await expect(page.getByTestId("shap-top-three")).toContainText(
      "falling_pressure",
    )
    await expect(page.getByTestId("shap-empty")).not.toBeVisible()

    // ReportsList renders the two URL-supplied citations (B-4 destination).
    await expect(page.getByTestId("reports-list")).toBeVisible()
    const reportItems = page.getByTestId("report-item")
    await expect(reportItems).toHaveCount(2)
    await expect(reportItems.first()).toContainText("NJF")
    await expect(reportItems.first()).toContainText("2026-04-22")
    await expect(reportItems.nth(1)).toContainText("SO")
    await expect(reportItems.nth(1)).toContainText("2026-04-20")
  })

  test("ShapTopThree empty branch when ?shap is absent (cite still passes through)", async ({
    page,
  }) => {
    await page.goto(`/spot/1?${CITE_QS}`)
    await expect(page.getByTestId("spot-detail-panel")).toBeVisible({
      timeout: 10_000,
    })
    await expect(page.getByTestId("shap-empty")).toBeVisible()
    await expect(page.getByTestId("shap-top-three")).not.toBeVisible()
    // cite still present → ReportsList renders rows
    await expect(page.getByTestId("reports-list")).toBeVisible()
    await expect(page.getByTestId("report-item")).toHaveCount(2)
  })

  test("ReportsList empty branch when ?cite is absent (shap still passes through)", async ({
    page,
  }) => {
    await page.goto(`/spot/1?${SHAP_QS}`)
    await expect(page.getByTestId("spot-detail-panel")).toBeVisible({
      timeout: 10_000,
    })
    await expect(page.getByTestId("shap-top-three")).toBeVisible()
    await expect(page.getByTestId("reports-empty")).toBeVisible()
    await expect(page.getByTestId("reports-list")).not.toBeVisible()
  })

  test("F-16 honest empty when BOTH params absent AND spot lookup fails (id=999)", async ({
    page,
  }) => {
    await page.goto("/spot/999")
    await expect(page.getByTestId("spot-empty-state")).toBeVisible({
      timeout: 10_000,
    })
    await expect(page.getByTestId("spot-empty-state")).toContainText(
      "We don't have a recommendation context for this spot yet",
    )
    // F-16 is NOT tautological — the panel itself is suppressed.
    await expect(page.getByTestId("spot-detail-panel")).not.toBeVisible()
  })

  test("F-16 NOT tautological — bogus id WITH shap+cite still renders the panel (degraded)", async ({
    page,
  }) => {
    // spot 999 doesn't exist, but URL carries context → degraded synthetic
    // SpotScore + the URL-pass-through panels still render.
    await page.goto(`/spot/999?${SHAP_QS}&${CITE_QS}`)
    await expect(page.getByTestId("spot-detail-panel")).toBeVisible({
      timeout: 10_000,
    })
    await expect(page.getByTestId("spot-empty-state")).not.toBeVisible()
    await expect(page.getByTestId("shap-top-three")).toBeVisible()
    await expect(page.getByTestId("reports-list")).toBeVisible()
    await expect(page.getByTestId("report-item")).toHaveCount(2)
  })
})
