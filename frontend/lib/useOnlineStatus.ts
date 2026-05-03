"use client"
import { useEffect, useState } from "react"

/**
 * Tracks `navigator.onLine` for F-14 offline-banner gating. SSR-safe (defaults
 * to `true` on first server render so the page does NOT flash an offline
 * banner during hydration on a perfectly online client).
 *
 * Listens to both `online` and `offline` window events; cleans up on unmount.
 *
 * NOTE (Plan 04-07): this hook is the minimal surface needed by
 * `app/conditions/page.tsx`. A richer Plan 08 OfflineBanner may extend it
 * (e.g., SW-driven sync state). When that lands, keep the boolean return so
 * existing callers don't break.
 */
export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState<boolean>(() => {
    if (typeof navigator === "undefined") return true
    return navigator.onLine
  })

  useEffect(() => {
    if (typeof window === "undefined") return
    const handleOnline = () => setOnline(true)
    const handleOffline = () => setOnline(false)
    window.addEventListener("online", handleOnline)
    window.addEventListener("offline", handleOffline)
    // Re-sync once on mount in case the event was missed during hydration.
    setOnline(navigator.onLine)
    return () => {
      window.removeEventListener("online", handleOnline)
      window.removeEventListener("offline", handleOffline)
    }
  }, [])

  return online
}
