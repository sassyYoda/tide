import { test, expect } from "@playwright/test"

// A4 falsifier — SW SSE bypass for /api/v1/query.
//
// This test runs only when BACKEND_LIVE=1 (a real Phase 3 backend reachable
// at NEXT_PUBLIC_API_URL). It builds the SW (via `pnpm next build && pnpm
// next start` in CI) and asserts the SW does NOT buffer the SSE response.
// If buffered (NetworkOnly mis-wired, wrong order, or defaultCache catching
// it first), `chunks.length === 1` (one giant blob). ≥4 means progress +
// partial + recommendation arrived as separate frames — proof that the
// FIRST runtimeCaching entry's NetworkOnly is winning the match race.
test.describe("A4 falsifier — SW SSE bypass for /api/v1/query", () => {
  test.skip(
    !process.env.BACKEND_LIVE,
    "BACKEND_LIVE=1 required (live Phase 3 backend at NEXT_PUBLIC_API_URL)"
  )

  test("SSE response chunks pass through SW unchanged (>=4 chunks)", async ({
    page,
    context,
  }) => {
    await context.addInitScript(() => {
      ;(window as unknown as { __sse_chunks: number[] }).__sse_chunks = []
    })
    await page.goto("/")
    // Wait for the SW to be in control of the page.
    await page.waitForFunction(
      () => navigator.serviceWorker.controller !== null,
      undefined,
      { timeout: 10_000 }
    )

    // Issue a real /api/v1/query POST + count chunks.
    await page.evaluate(async () => {
      const resp = await fetch("/api/v1/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: "stripers at barnegat saturday" }),
      })
      const reader = resp.body!.getReader()
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        ;(window as unknown as { __sse_chunks: number[] }).__sse_chunks.push(
          value!.length
        )
      }
    })

    const chunks = await page.evaluate(
      () => (window as unknown as { __sse_chunks: number[] }).__sse_chunks
    )
    // FALSIFIER: if the SW buffers (NetworkOnly mis-wired or wrong order),
    // chunks.length === 1 (one big blob). >=4 means progress + partial +
    // recommendation arrived as separate frames.
    expect(chunks.length).toBeGreaterThanOrEqual(4)
  })
})
