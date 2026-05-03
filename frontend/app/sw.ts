/// <reference lib="webworker" />
// LOAD-BEARING ORDERING — DO NOT MOVE THE FIRST TWO ENTRIES.
// First-match-wins. Putting `/api/v1/query` ANYWHERE except the first entry
// (or letting `defaultCache` match it before the NetworkOnly above)
// silently breaks SSE chunked responses. TTFT goes from 2s to 8s; the page
// renders one giant blob instead of streaming progress + partial + final.
// See PATTERNS P1 + RESEARCH Q3 / A4. Falsifier: tests/sw-sse-bypass.test.ts.
import { defaultCache } from "@serwist/next/worker"
import type { PrecacheEntry, SerwistGlobalConfig } from "serwist"
import { NetworkOnly, Serwist } from "serwist"

declare global {
  interface WorkerGlobalScope extends SerwistGlobalConfig {
    __SW_MANIFEST: (PrecacheEntry | string)[] | undefined
  }
}

declare const self: ServiceWorkerGlobalScope

const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  skipWaiting: true,
  clientsClaim: true,
  navigationPreload: true,
  runtimeCaching: [
    // [1] SSE BYPASS — FIRST ENTRY MANDATORY (P1 / A4).
    // DO NOT MOVE — first-match-wins; SSE chunks die if anything else matches first.
    {
      matcher: ({ url }: { url: URL }) => url.pathname === "/api/v1/query",
      handler: new NetworkOnly(),
    },
    // [2] CONDITIONS — NetworkOnly so the staleness banner reads live data_age_seconds
    // (P6 / RESEARCH Q3 deviation). NetworkFirst would leak past the freshness banner.
    {
      matcher: ({ url }: { url: URL }) => url.pathname.startsWith("/api/v1/conditions"),
      handler: new NetworkOnly(),
    },
    // [3] Static assets + /api/v1/spots get @serwist defaults
    // (StaleWhileRevalidate is fine; bbox tolerates ~30s lag).
    ...defaultCache,
  ],
})

serwist.addEventListeners()
