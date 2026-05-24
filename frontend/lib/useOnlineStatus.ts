"use client"
import { useEffect, useRef, useState } from "react"

/**
 * Tracks effective online status for F-14 offline-banner gating.
 *
 * `navigator.onLine` alone produces false-positives — macOS reports false
 * during Wi-Fi/Ethernet handoffs, VPN reconnects, and captive-portal
 * transitions; Chrome DevTools "Offline" throttling flips it without
 * changing real reachability. Even more confounding: the `online` event
 * doesn't fire reliably on every platform when the network actually
 * recovers, so a single failed probe can wedge the banner.
 *
 * Strategy:
 *   1. Trust `navigator.onLine === true` (fast path — no probe).
 *   2. When `navigator.onLine === false` OR an `offline` event fires,
 *      probe the BACKEND API. If the probe succeeds, we're effectively
 *      online (the path that actually matters to the user).
 *   3. While the hook believes we're offline, poll the probe every 5s
 *      so we recover automatically when the network returns — without
 *      relying on the `online` event.
 *
 * Probe target: NEXT_PUBLIC_API_URL + "/healthz". The path is intercepted
 * by Cloud Run's GFE (returns 404 with no CORS headers — Cloud Run reserves
 * /healthz globally and won't pass it through to the app's CORS middleware).
 * We send the probe with `mode: "no-cors"` so the browser does NOT enforce
 * CORS-header validation; the fetch resolves with an opaque response on ANY
 * HTTP reply (200/404/503 all count as "network reached server"). Only
 * genuine network-level failures (DNS, dropped TCP, browser-offline,
 * navigator-offline) throw, and those are exactly the cases we want to
 * treat as offline.
 *
 * SSR-safe (defaults to `true` on the server so the banner never flashes
 * during hydration on a working client).
 */

const PROBE_TIMEOUT_MS = 2500
const POLL_WHILE_OFFLINE_MS = 5000

function probeUrl(): string {
  const base =
    process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? ""
  // No-base fallback — same-origin healthz won't exist but the probe will
  // still resolve against the SW or 404 from Vercel, which is "online".
  return `${base}/healthz`
}

export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState<boolean>(() => {
    if (typeof navigator === "undefined") return true
    return navigator.onLine
  })
  const probeAbort = useRef<AbortController | null>(null)
  const pollTimer = useRef<number | null>(null)
  const url = useRef<string>(probeUrl())

  useEffect(() => {
    if (typeof window === "undefined") return

    const probe = async (): Promise<boolean> => {
      probeAbort.current?.abort()
      const ctrl = new AbortController()
      probeAbort.current = ctrl
      const timer = window.setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS)
      try {
        await fetch(url.current, {
          method: "GET",
          cache: "no-store",
          signal: ctrl.signal,
          // Don't send credentials — keeps the preflight cheap and the
          // probe independent of any auth state.
          credentials: "omit",
          // no-cors so the browser doesn't reject the opaque 404 from
          // Cloud Run's GFE-served /healthz for missing CORS headers.
          // We never read the body — we only need to know the network
          // reached the server.
          mode: "no-cors",
        })
        // ANY HTTP response (200, 404, 503) means the network reached
        // the server, so we're online.
        return true
      } catch {
        return false
      } finally {
        window.clearTimeout(timer)
      }
    }

    const stopPolling = () => {
      if (pollTimer.current !== null) {
        window.clearInterval(pollTimer.current)
        pollTimer.current = null
      }
    }

    const startPollingIfOffline = () => {
      stopPolling()
      pollTimer.current = window.setInterval(async () => {
        const reachable = await probe()
        if (reachable) {
          setOnline(true)
          stopPolling()
        }
      }, POLL_WHILE_OFFLINE_MS)
    }

    const handleOnline = () => {
      // Optimistic flip — let any in-flight poll confirm. The poll will
      // bail itself out via stopPolling when the next tick sees reachable.
      setOnline(true)
      stopPolling()
    }
    const handleOffline = async () => {
      const reachable = await probe()
      setOnline(reachable)
      if (!reachable) startPollingIfOffline()
    }
    window.addEventListener("online", handleOnline)
    window.addEventListener("offline", handleOffline)

    // Reconcile mount-time state: if navigator says offline, probe before
    // committing to the banner; start the recovery poll if probe fails.
    if (!navigator.onLine) {
      probe().then((reachable) => {
        setOnline(reachable)
        if (!reachable) startPollingIfOffline()
      })
    } else {
      setOnline(true)
    }

    return () => {
      window.removeEventListener("online", handleOnline)
      window.removeEventListener("offline", handleOffline)
      probeAbort.current?.abort()
      stopPolling()
    }
  }, [])

  return online
}
