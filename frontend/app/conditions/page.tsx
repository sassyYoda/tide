"use client"
import { useEffect, useState } from "react"
import { NJ_STATIONS } from "@/lib/nj-stations"
import {
  useConditionsCache,
  type ConditionsResult,
} from "@/lib/useConditionsCache"
import { useOnlineStatus } from "@/lib/useOnlineStatus"
import { ConditionsGrid } from "@/components/conditions/ConditionsGrid"
import { apiUrl } from "@/lib/api-client"
import type { components } from "@/lib/api-types"

type ConditionsResponse = components["schemas"]["ConditionsResponse"]
type ErrorEnvelope = components["schemas"]["ErrorEnvelope"]

/**
 * Fetch one station's conditions. The 503/404 paths read the ErrorEnvelope
 * from either the flat body OR `body.detail` because FastAPI's HTTPException
 * wraps the dict under `detail`, while custom envelopes may be returned flat.
 * On network error (`fetch` reject), returns status=0 with a null envelope.
 */
async function fetchOne(stationId: string): Promise<ConditionsResult> {
  try {
    const resp = await fetch(
      apiUrl(`/api/v1/conditions/${encodeURIComponent(stationId)}`),
    )
    if (resp.ok) {
      const data = (await resp.json()) as ConditionsResponse
      return { ok: true, station_id: stationId, data }
    }
    let envelope: ErrorEnvelope | null = null
    try {
      const body = (await resp.json()) as { detail?: unknown } & Record<
        string,
        unknown
      >
      envelope = ((body?.detail as ErrorEnvelope | undefined) ??
        (body as unknown as ErrorEnvelope)) as ErrorEnvelope
    } catch {
      envelope = null
    }
    return { ok: false, station_id: stationId, status: resp.status, envelope }
  } catch {
    return { ok: false, station_id: stationId, status: 0, envelope: null }
  }
}

export default function ConditionsPage() {
  const [results, setResults] = useState<ConditionsResult[]>([])
  const [cachedAt, setCachedAt] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const online = useOnlineStatus()
  const { set, read } = useConditionsCache()

  useEffect(() => {
    let cancelled = false

    async function load() {
      // ─── F-14 offline branch: hydrate from sessionStorage cache ──────────
      if (!online) {
        const cached = read()
        if (cached) {
          if (!cancelled) {
            setResults(cached.entries)
            setCachedAt(cached.fetchedAt)
            setLoading(false)
          }
          return
        }
        if (!cancelled) {
          setResults([])
          setLoading(false)
        }
        return
      }

      // ─── Online: fan out 9 parallel fetches ──────────────────────────────
      const settled = await Promise.all(
        NJ_STATIONS.map((s) => fetchOne(s.id)),
      )
      if (cancelled) return
      setResults(settled)
      setCachedAt(null)
      setLoading(false)
      // Mirror the 9-station snapshot for the F-14 offline branch.
      set(settled)
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [online, set, read])

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-6">
        <h1 className="font-display text-3xl text-tide-high">Live conditions</h1>
        <p className="mt-1 text-sm text-stone-600">
          Real-time tidal, weather, and solunar snapshot across{" "}
          {NJ_STATIONS.length} NJ NOAA stations.
        </p>
      </header>

      {loading ? (
        <p data-testid="conditions-loading" className="text-sm text-stone-500">
          Loading conditions for {NJ_STATIONS.length} stations…
        </p>
      ) : (
        <ConditionsGrid
          results={results}
          stations={NJ_STATIONS}
          cachedAt={cachedAt}
        />
      )}
    </main>
  )
}
