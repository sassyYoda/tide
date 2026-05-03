import { test, expect } from "@playwright/test"

test.describe("F-13 / L-09 — mobile bottom sheet vs desktop card", () => {
  test("desktop project shows Card side panel", async ({ page }, testInfo) => {
    test.skip(!testInfo.project.name.includes("desktop"), "desktop-only")
    await page.goto("/")
    const desktopBox = page.getByTestId("query-input-desktop")
    await expect(desktopBox).toBeVisible()
    // textarea visible without opening anything (autoFocus prop ensures it)
    await expect(page.getByTestId("query-input").first()).toBeVisible()
  })

  test("mobile project shows bottom Sheet trigger (textarea hidden until open)", async ({
    page,
  }, testInfo) => {
    test.skip(!testInfo.project.name.includes("mobile"), "mobile-only")
    await page.goto("/")
    const mobileBox = page.getByTestId("query-input-mobile")
    await expect(mobileBox).toBeVisible()
    // Click the trigger to open the bottom sheet
    await page.getByTestId("query-sheet-trigger").click()
    await expect(page.getByTestId("query-input").first()).toBeVisible()
  })
})
