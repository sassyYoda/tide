import { test, expect } from "@playwright/test"

/**
 * F-01 — PWA install metadata. Asserts:
 *   1. /manifest.webmanifest is reachable + display=standalone + 3 icons + palette colors
 *   2. apple-touch-icon link is in the rendered <head> (P9 / A7 falsifier)
 *   3. apple-touch-icon-180.png is reachable + image/png
 */
test.describe("F-01 — PWA install metadata", () => {
  test("manifest.webmanifest reachable with display=standalone + 3 icons", async ({
    request,
  }) => {
    const resp = await request.get("/manifest.webmanifest")
    expect(resp.ok()).toBe(true)
    const body = (await resp.json()) as Record<string, unknown>
    expect(body.display).toBe("standalone")
    expect(body.theme_color).toBe("#0F766E")
    expect(body.background_color).toBe("#FAF8F1")
    const icons = body.icons as Array<{ src: string; sizes: string; purpose?: string }>
    expect(icons).toHaveLength(3)
    expect(icons.find((i) => i.sizes === "192x192")).toBeTruthy()
    expect(icons.find((i) => i.sizes === "512x512" && !i.purpose)).toBeTruthy()
    expect(icons.find((i) => i.purpose === "maskable")).toBeTruthy()
  })

  test("apple-touch-icon link present in <head> (P9 / A7)", async ({ page }) => {
    await page.goto("/")
    const apple = await page
      .locator("link[rel='apple-touch-icon']")
      .first()
      .getAttribute("href")
    expect(apple).toBeTruthy()
    expect(apple).toContain("apple-touch-icon-180")
  })

  test("apple-touch-icon-180.png is reachable + image/png", async ({ request }) => {
    const resp = await request.get("/icons/apple-touch-icon-180.png")
    expect(resp.ok()).toBe(true)
    expect(resp.headers()["content-type"]).toContain("image/png")
  })
})
