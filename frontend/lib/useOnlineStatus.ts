"use client"
import { useEffect, useRef, useState } from "react"

/**
 * Tracks effective online status for F-14 offline-banner gating.
 *
 * `navigator.onLine` alone produces false-positives — on macOS (and some
 * VPN/captive-portal handoffs) it can stay `false` while the network is
 * actually fine, and Chrome DevTools "Offline" throttling toggles it without
 * changing real reachability. So we verify any `offline` signal with a
 * lightweight same-origin HEAD probe against the SW-served root before
 * concluding we're really offline.
 *
 * SSR-safe (defaults to `true` on the server so the banner never flashes
 * during hydration on a perfectly online client).
 */
export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState<boolean>(() => {
    if (typeof navigator === "undefined") return true
    return navigator.onLine
  })
  const probeAbort = useRef<AbortController | null>(null)

  useEffect(() => {
    if (typeof window === "undefined") return

    const probe = async (): Promise<boolean> => {
      probeAbort.current?.abort()
      const ctrl = new AbortController()
      probeAbort.current = ctrl
      const timer = window.setTimeout(() => ctrl.abort(), 2500)
      try {
        await fetch("/?_=" + Date.now(), {
          method: "HEAD",
          cache: "no-store",
          signal: ctrl.signal,
        })
        return true
      } catch {
        return false
      } finally {
        window.clearTimeout(timer)
      }
    }

    const handleOnline = () => setOnline(true)
    const handleOffline = async () => {
      const reachable = await probe()
      setOnline(reachable)
    }
    window.addEventListener("online", handleOnline)
    window.addEventListener("offline", handleOffline)

    // Reconcile mount-time state: if navigator says offline, probe before
    // committing to the banner.
    if (!navigator.onLine) {
      probe().then(setOnline)
    } else {
      setOnline(true)
    }

    return () => {
      window.removeEventListener("online", handleOnline)
      window.removeEventListener("offline", handleOffline)
      probeAbort.current?.abort()
    }
  }, [])

  return online
}
