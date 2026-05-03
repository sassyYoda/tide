import { test, expect } from "@playwright/test"
import AxeBuilder from "@axe-core/playwright"

/**
 * A11Y-01: WCAG 2.1 AA contrast >= 4.5:1 on ALL 5 Phase-4 pages.
 *
 * Routes (CONTEXT.md lines 13-16):
 *   /                — home / query loop (Plan 04 + 05)
 *   /map             — map (Plan 03, this plan)
 *   /spot/[id]       — spot detail (Plan 06) — URL state populated to exercise all branches
 *   /conditions      — conditions table (Plan 07)
 *   /about           — about / landing copy (Plan 01 stub or Plan 08)
 *
 * Routes from later plans render Plan 01 stub pages (or Next 404) until the
 * owning plan ships. The test still runs axe on whatever HTML loads — the
 * assertion strengthens automatically once each plan lands. Do NOT skip them.
 *
 * Asserts: zero `serious` and zero `critical` axe violations per route.
 */

const ROUTES = [
  { path: "/", lcp: "h1" },
  { path: "/map", lcp: "h1" },
  // Spot detail with B-4 URL state populated so all conditional branches render
  // (shap chips + citations panel) — exercises the most complex tree.
  { path: "/spot/7?shap=tide,moon,wind&cite=NJF:2026-04-22,SO:2026-04-20", lcp: "h1" },
  { path: "/conditions", lcp: "h1" },
  { path: "/about", lcp: "h1" },
] as const

// Stub backend so /map and / don't hang on a missing backend in CI.
const SPOTS_FIXTURE = JSON.stringify([
  { spot_id: 1, name: "Barnegat Inlet", lat: 39.76, lon: -74.10, score: 0.81, confidence: "High", species: "striper", last_score_time: "2026-05-02T08:00:00Z", data_age_seconds: 300 },
])

test.describe("A11Y-01 — axe-core sweep across all 5 Phase-4 routes", () => {
  for (const { path, lcp } of ROUTES) {
    test(`${path} → zero serious/critical axe violations`, async ({ page }) => {
      // Stub network so a backend-less CI run still loads each route deterministically.
      await page.route("**/api/v1/spots*", (r) =>
        r.fulfill({ status: 200, contentType: "application/json", body: SPOTS_FIXTURE }),
      )
      await page.route("**/api/v1/conditions*", (r) =>
        r.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ stations: [] }),
        }),
      )
      await page.route("**/api/v1/spots/*", (r) =>
        r.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            spot_id: 7,
            name: "Barnegat Inlet",
            lat: 39.76,
            lon: -74.10,
            score: 0.81,
            species: "striper",
            last_score_time: "2026-05-02T08:00:00Z",
            data_age_seconds: 300,
          }),
        }),
      )

      await page.goto(path, { waitUntil: "domcontentloaded" })

      // Wait for the visible LCP element so we don't axe a bare skeleton.
      // If the route is a Next 404 (because a later-plan page hasn't shipped),
      // Next's default 404 page also has an h1 — axe still runs against THAT.
      try {
        await page.waitForSelector(lcp, { timeout: 10000 })
      } catch {
        // Even without a heading, run axe on what's there. Failures on a 404
        // are still legitimate violations the team should fix.
      }

      const results = await new AxeBuilder({ page }).analyze()

      // Filter to serious + critical (the WCAG-AA-grade severity floor)
      const blockers = results.violations.filter(
        (v) => v.impact === "serious" || v.impact === "critical",
      )

      if (blockers.length > 0) {
        // Print a digestible summary so failures are self-debugging
        // eslint-disable-next-line no-console
        console.error(
          `\nA11Y-01 violations on ${path}:\n` +
            blockers
              .map(
                (v) =>
                  `  [${v.impact}] ${v.id}: ${v.description}\n` +
                  v.nodes.slice(0, 3).map((n) => `    - ${n.target.join(" ")}`).join("\n"),
              )
              .join("\n\n"),
        )
      }

      expect(blockers, `serious|critical violations on ${path}`).toEqual([])
    })
  }
})
