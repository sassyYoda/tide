// Server Component (NO "use client") — async page per Next 16 App Router.
import { parseShap, parseCite } from "@/lib/spot-querystring"
import { SpotDetailPanel } from "@/components/spot/SpotDetailPanel"
import { SpotEmptyState } from "@/components/spot/SpotEmptyState"
import type { components } from "@/lib/api-types"

type SpotScore = components["schemas"]["SpotScore"]
type ConditionsResponse = components["schemas"]["ConditionsResponse"]

const NJ_DEFAULT_STATION = "8534720" // Atlantic City — Barnegat pilot fallback (see <interfaces>)
const NJ_BBOX = "39.5,-75,41.0,-73.5" // covers all 30 MVP spots — bbox query is index-tap

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

async function fetchSpot(id: string): Promise<SpotScore | null> {
  // /api/v1/spots is bbox-only at MVP — pull NJ-wide list and find by spot_id.
  const url = `${API_BASE}/api/v1/spots?bbox=${encodeURIComponent(NJ_BBOX)}`
  try {
    const resp = await fetch(url, {
      // Server-side fetch — Next 16 default cache is "no-store" on dynamic
      // routes; spot detail tolerates ~30s lag, so opt into a short revalidate.
      next: { revalidate: 30 },
    })
    if (!resp.ok) return null
    const list = (await resp.json()) as SpotScore[]
    const numericId = Number(id)
    if (Number.isNaN(numericId)) return null
    return list.find((s) => s.spot_id === numericId) ?? null
  } catch {
    return null
  }
}

async function fetchConditions(
  stationId: string,
): Promise<ConditionsResponse | null> {
  const url = `${API_BASE}/api/v1/conditions/${encodeURIComponent(stationId)}`
  try {
    const resp = await fetch(url, { next: { revalidate: 30 } })
    if (!resp.ok) return null // 503/404 → null, banner branch handled by ConditionsSnapshot
    return (await resp.json()) as ConditionsResponse
  } catch {
    return null
  }
}

// P5 MANDATORY: Next 16 makes both `params` and `searchParams` Promises.
// Pre-Next-16 sync destructuring breaks at runtime with no helpful error.
export default async function SpotDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>
  searchParams: Promise<{ shap?: string; cite?: string }>
}) {
  const { id } = await params
  const { shap: shapParam, cite: citeParam } = await searchParams

  // B-4 destination side — VERBATIM from CONTEXT.md "Specific Ideas":
  // parseShap returns string[] | null; parseCite returns CitationOut[].
  // We bind the parsed values to local consts and pass them DOWN explicitly:
  //   <ShapTopThree shap={shap} />     (per planning_context CRITICAL)
  //   <ReportsList reports={reports} /> (per planning_context CRITICAL)
  const shap = parseShap(shapParam)
  const reports = parseCite(citeParam)

  const spot = await fetchSpot(id)

  // F-16 honest empty: spot lookup failed AND URL carried no context.
  // Do NOT render an empty SpotDetailPanel — render the honest empty.
  // (NOTE: F-16 must NOT be tautological — if either URL param was present,
  // we DO render the panel, even if the spot lookup partially fails.)
  if (spot == null && shap == null && reports.length === 0) {
    return <SpotEmptyState spotName={null} />
  }

  // If spot lookup failed but the URL carried context, render a degraded
  // panel using a synthetic SpotScore so the user isn't dead-ended.
  const resolvedSpot: SpotScore =
    spot ??
    ({
      spot_id: Number(id),
      name: `Spot ${id}`,
      lat: 0,
      lon: 0,
      score: null,
      confidence: null,
      species: null,
      last_score_time: null,
      data_age_seconds: null,
    } as SpotScore)

  // Conditions: use spot's nearest station if available; fall back to NJ default.
  // SpotScore doesn't currently expose nearest_station_id (v1.x extension);
  // we use NJ_DEFAULT_STATION until then.
  const stationId = NJ_DEFAULT_STATION
  const conditions = await fetchConditions(stationId)

  return (
    <SpotDetailPanel
      spot={resolvedSpot}
      conditions={conditions}
      shap={shap}
      reports={reports}
    />
  )
}
