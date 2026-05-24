"use client"
import { useEffect, useState } from "react"
import { useOnlineStatus } from "@/lib/useOnlineStatus"

const HISTORY_KEY = "tide.history.last5"
const CONDITIONS_KEY = "tide.conditions.snapshot"

/**
 * F-14 sticky-top OfflineBanner — visible signal that the page is rendering
 * from sessionStorage caches (Plan 04 last-5 history + Plan 07 conditions
 * snapshot). Reads `useOnlineStatus()` (Plan 04 hook with SSR guard).
 *
 * The banner intentionally surfaces the cache `fetchedAt` ISO timestamp so
 * the user can see HOW stale the data is — repudiation mitigation per
 * threat-register T-04-08-05.
 */
export function OfflineBanner() {
  const online = useOnlineStatus()
  const [cachedAt, setCachedAt] = useState<string | null>(null)
  const [hasHistory, setHasHistory] = useState<boolean>(false)

  useEffect(() => {
    if (online) {
      setCachedAt(null)
      setHasHistory(false)
      return
    }
    // Read both caches when offline. Best-effort — sessionStorage may be
    // unavailable (private mode / quota); silently degrade.
    try {
      const condRaw = window.sessionStorage.getItem(CONDITIONS_KEY)
      if (condRaw) {
        const parsed = JSON.parse(condRaw) as { fetchedAt?: string }
        if (parsed.fetchedAt) setCachedAt(parsed.fetchedAt)
      }
    } catch {
      /* sessionStorage unavailable / quota — silently no-op */
    }
    try {
      const histRaw = window.sessionStorage.getItem(HISTORY_KEY)
      if (histRaw && histRaw !== "[]") setHasHistory(true)
    } catch {
      /* sessionStorage unavailable / quota — silently no-op */
    }
  }, [online])

  if (online) return null

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="offline-banner"
      className="sticky top-0 z-50 bg-tide-mid/30 px-4 py-2 text-center text-sm text-stone-800"
    >
      <p>
        <span className="font-medium">You&apos;re offline.</span>
        {cachedAt && (
          <>
            {" "}
            Last cached: <span className="font-mono">{cachedAt}</span>.
          </>
        )}
        {hasHistory && <> Last query history available.</>}
      </p>
    </div>
  )
}
