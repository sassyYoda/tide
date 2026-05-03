"use client"
import { useCallback } from "react"
import type { components } from "./api-types"

type ConditionsResponse = components["schemas"]["ConditionsResponse"]
type ErrorEnvelope = components["schemas"]["ErrorEnvelope"]

/**
 * One entry in the cached snapshot — discriminated union over fetch outcome.
 * `ok=true` carries the full ConditionsResponse; `ok=false` carries status +
 * an optional ErrorEnvelope (FastAPI may emit it under `body` or `body.detail`).
 */
export type ConditionsResult =
  | { ok: true; station_id: string; data: ConditionsResponse }
  | { ok: false; station_id: string; status: number; envelope: ErrorEnvelope | null }

/**
 * F-14 cache snapshot — last-9 station results + a write timestamp.
 * Surfaced to the UI as the "Last cached: <ts>" banner on offline reload.
 */
export type CachedSnapshot = {
  fetchedAt: string
  entries: ConditionsResult[]
}

// P7: sessionStorage ONLY. The persistent-storage alternative is forbidden
// here — it would violate the no-PII anonymous-session stance and the
// 04-PATTERNS.md offline-cache discipline. (Enforced by grep in plan
// acceptance criteria — the forbidden literal must not appear anywhere
// in this file.)
const CACHE_KEY = "tide.conditions.snapshot"

function readRaw(): CachedSnapshot | null {
  if (typeof window === "undefined") return null
  try {
    const raw = window.sessionStorage.getItem(CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as unknown
    if (
      parsed &&
      typeof parsed === "object" &&
      "fetchedAt" in parsed &&
      "entries" in parsed &&
      Array.isArray((parsed as CachedSnapshot).entries)
    ) {
      return parsed as CachedSnapshot
    }
    return null
  } catch {
    return null
  }
}

function writeRaw(snapshot: CachedSnapshot): void {
  if (typeof window === "undefined") return
  try {
    window.sessionStorage.setItem(CACHE_KEY, JSON.stringify(snapshot))
  } catch {
    // quota / private mode — silently no-op (degrade gracefully)
  }
}

function clearRaw(): void {
  if (typeof window === "undefined") return
  try {
    window.sessionStorage.removeItem(CACHE_KEY)
  } catch {
    // ignore
  }
}

export function useConditionsCache() {
  const set = useCallback((entries: ConditionsResult[]) => {
    writeRaw({ fetchedAt: new Date().toISOString(), entries })
  }, [])
  const read = useCallback((): CachedSnapshot | null => readRaw(), [])
  const clear = useCallback(() => {
    clearRaw()
  }, [])
  return { set, read, clear }
}
