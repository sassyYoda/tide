/**
 * 9 NJ saltwater NOAA stations — mirrors Phase 1 seed `noaa_stations` table.
 *
 * Source of truth: `seeds/noaa_stations.json` (Phase 1 — `01-03` seed).
 *
 * IMPLEMENTER NOTE (Plan 04-07): the IDs and names below were copied
 * verbatim from the seed JSON at execution time and DO NOT match every
 * entry in `frontend/tests/fixtures/conditions-9stations.json` —
 * the fixture was authored speculatively in Plan 02 before the seed
 * landed. The seed wins because the runtime backend reads from the
 * `noaa_stations` table populated from this seed; the fixture is sample
 * data only. If the seed is ever amended, update this file accordingly.
 *
 * Fixture deviations vs. seed (recorded for traceability):
 *   - fixture has 8533615 "Reedy Point"        → not in seed
 *   - fixture has 8538886 "Tacony-Palmyra Bridge" → not in seed
 *   - seed   has 8548989 "Newbold"               → not in fixture
 *   - seed   has 8570283 "Ocean City Inlet"      → not in fixture
 */

export type NJStation = { id: string; name: string }

export const NJ_STATIONS: ReadonlyArray<NJStation> = [
  { id: "8531680", name: "Sandy Hook" },
  { id: "8534720", name: "Atlantic City" },
  { id: "8536110", name: "Cape May" },
  { id: "8537121", name: "Ship John Shoal" },
  { id: "8539094", name: "Burlington, Delaware River" },
  { id: "8540433", name: "Marcus Hook" },
  { id: "8548989", name: "Newbold" },
  { id: "8557380", name: "Lewes" },
  { id: "8570283", name: "Ocean City Inlet" },
] as const

/**
 * F-08 staleness threshold (seconds). Trigger fires STRICTLY when
 * `data_age_seconds > STALE_THRESHOLD_S` — equality (1800) does NOT trigger.
 * Matches backend `require_fresh_conditions` gating window.
 */
export const STALE_THRESHOLD_S = 1800
