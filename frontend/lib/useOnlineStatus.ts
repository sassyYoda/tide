"use client"
import { useEffect, useState } from "react"

/**
 * Tracks `navigator.onLine` for F-14 offline-banner gating. SSR-safe (defaults
 * to `true` on first server render so the page does NOT flash an offline
 * banner during hydration on a perfectly online client).
 *
 * Listens to both `online` and `offline` window events; cleans up on unmount.
 * Re-syncs once on mount in case the event was missed during hydration.
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
    setOnline(navigator.onLine)
    return () => {
      window.removeEventListener("online", handleOnline)
      window.removeEventListener("offline", handleOffline)
    }
  }, [])

  return online
}
