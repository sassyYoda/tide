"use client"
import { useEffect, useState } from "react"

const HINT_KEY = "tide.ios.install.hint.dismissed"

function isIOSSafariStandaloneEligible(): boolean {
  if (typeof window === "undefined") return false
  const ua = navigator.userAgent
  const isIOS = /iPhone|iPad|iPod/i.test(ua)
  // matchMedia covers modern iOS Safari + WebKit; navigator.standalone is the
  // legacy iOS flag (still set on older Safari builds).
  const standaloneByMQ =
    typeof window.matchMedia === "function" &&
    window.matchMedia("(display-mode: standalone)").matches
  const standaloneByLegacy =
    "standalone" in navigator &&
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  return isIOS && !standaloneByMQ && !standaloneByLegacy
}

/**
 * F-01 / Q8 iOS A2HS hint — iOS Safari has NO `beforeinstallprompt` API, so
 * we render a small dismissible hint after a short delay on eligible devices.
 * Dismissal is sticky for the session via sessionStorage (P7).
 */
export function InstallPromptIOS() {
  const [show, setShow] = useState(false)

  useEffect(() => {
    try {
      if (window.sessionStorage.getItem(HINT_KEY)) return
    } catch {
      /* sessionStorage unavailable — fall through to eligibility check */
    }
    if (isIOSSafariStandaloneEligible()) {
      // Defer to second-page-view feel: show after 2s on first eligible visit.
      const t = window.setTimeout(() => setShow(true), 2000)
      return () => window.clearTimeout(t)
    }
  }, [])

  const dismiss = () => {
    try {
      window.sessionStorage.setItem(HINT_KEY, "1")
    } catch {
      /* */
    }
    setShow(false)
  }

  if (!show) return null

  return (
    <div
      role="dialog"
      aria-label="Install Tide on your iPhone"
      data-testid="ios-install-hint"
      className="fixed bottom-20 left-4 right-4 z-50 rounded-lg border border-tide-high bg-white p-3 shadow-lg"
    >
      <p className="text-sm text-stone-800">
        Install Tide: tap <span className="font-medium">Share</span> →{" "}
        <span className="font-medium">Add to Home Screen</span>.
      </p>
      <button
        type="button"
        onClick={dismiss}
        className="mt-2 text-xs text-stone-600 underline"
      >
        Got it
      </button>
    </div>
  )
}
