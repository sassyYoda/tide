import { defineConfig, devices } from "@playwright/test"

export default defineConfig({
  testDir: "./tests",
  testMatch: /.*\.spec\.ts$/,
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  globalSetup: require.resolve("./playwright/global-setup.ts"),
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium-desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "webkit-desktop", use: { ...devices["Desktop Safari"] } },
    { name: "chromium-mobile", use: { ...devices["Pixel 5"] } },
    { name: "webkit-mobile", use: { ...devices["iPhone 13"] } },
  ],
  webServer: process.env.CI
    ? undefined
    : {
        command: "pnpm dev",
        url: "http://localhost:3000",
        reuseExistingServer: true,
        timeout: 60_000,
      },
})
