# Seed Data — NOAA Stations + Fishing Spots

## noaa_stations.json

**Filter applied:** station must publish both `water_level` AND `water_temperature` per CONTEXT.md D-03 (and must have *active* sensors of each type, status=1 on the `sensors.json` endpoint — not merely tide-prediction stations).
**Source:** NOAA CO-OPS Metadata API — https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=watertemp (cross-referenced against the per-station sensors endpoint `.../stations/{id}/sensors.json`).
**Row count:** 9 after filter (minimum required: 8).
**Geographic bbox:** 38.3°N to 40.5°N, -75.5°W to -73.9°W. Covers Sandy Hook → Cape May on the NJ Atlantic coast, all of Delaware Bay, and south to Ocean City, MD. **Deviates from the original plan's NJ bbox (-75.0 to -73.5) — widened westward to -75.5 because the 8-station minimum is not achievable against real NOAA active-sensor coverage on the strict NJ coastline; Delaware Bay + River stations are the only way to cross the 8-station floor.** See Deviations in `01-03-SUMMARY.md`.

### Curated stations (N=9)

| station_id | name | lat, lon | products | role |
|---|---|---|---|---|
| 8531680 | Sandy Hook | 40.4669, -74.0094 | water_level, water_temperature, wind | N reference — Raritan Bay entrance |
| 8534720 | Atlantic City | 39.3567, -74.4180 | water_level, water_temperature | Primary mid-coast reference (closest to Barnegat Bay with an active water_temp sensor) |
| 8536110 | Cape May | 38.9683, -74.9600 | water_level, water_temperature, wind | S reference — Cape May / Delaware Bay entrance |
| 8537121 | Ship John Shoal | 39.3054, -75.3767 | water_level, water_temperature, wind | Delaware Bay mid — striper context |
| 8539094 | Burlington, Delaware River | 40.0817, -74.8697 | water_level, water_temperature, wind | Tidal Delaware River — freshwater striper |
| 8540433 | Marcus Hook | 39.8118, -75.4095 | water_level, water_temperature | Delaware River mid |
| 8548989 | Newbold | 40.1373, -74.7518 | water_level, water_temperature, wind | Delaware River upper-tidal |
| 8557380 | Lewes | 38.7828, -75.1193 | water_level, water_temperature, wind | Delaware Bay entrance (DE) — Atlantic shelf proxy |
| 8570283 | Ocean City Inlet | 38.3283, -75.0917 | water_level, water_temperature, wind | MD coast — southern Atlantic shelf reference |

### Notable candidates REJECTED

All IDs in RESEARCH.md §NOAA Stations Draft were re-verified against the live CO-OPS metadata and sensors APIs. **Many of the originally drafted IDs did not resolve, resolved to wrong stations, or lack active sensors.** Notable rejections:

- `8543320` "Toms River" — 404 on metadata API (not a current station ID).
- `8531064` "Keansburg" — 404.
- `8539497` "Waretown" — 404.
- `8532337` "Belmar" — 404.
- `8538174` "Little Egg Inlet" — 404.
- `8535365` "Ocean City NJ" — 404.
- `8531310` "Raritan Bay" — 404.
- `8536021` / `8535011` / `8534910` "Brigantine / Ocean City Inlet / Atlantic City Ocean" — 404.
- `8539707` "Barnegat Pier" — 404.
- `8532732` "Shark River" — 404.
- `8531716` "Seaside Heights" — 404.
- `8516945` Kings Point (NY) — has WL but no active water_temperature sensor; fails D-03.
- `8518750` The Battery (NY) — has water_temperature but no active routine WL sensor (only tide predictions); fails D-03.
- `8546252` Bridesburg (PA) — passes sensor filter but is inland industrial Philadelphia tidal river; dropped as not relevant to saltwater fishing. (Can be re-added if user wants more coverage — it is within -75.5 bbox.)

**Plan-drafted "Barnegat Inlet USCG" (8537121) was not Barnegat Inlet — it is Ship John Shoal in Delaware Bay.** There is NO active NOAA water-level+water-temperature station inside Barnegat Bay itself; the ingest layer (Plan 04/05) will have to interpolate tide and water temperature for Barnegat fishing spots from the nearest active stations (Sandy Hook or Atlantic City). This is a known MVP limitation documented here so downstream plans understand the constraint.

## Workflow

1. Claude drafts and verifies products against live metadata + sensors APIs.
2. User reviews lat/lon on the NOAA station page (each `source_url` links directly to sensors.json; lat/lon in this file matches the upstream metadata).
3. Seed migration 0004 applies via `alembic upgrade head` (Plan 04).

## User verification log

- [x] 2026-04-21: Station list reviewed and approved by user (auto-approved via orchestrator `workflow.auto_advance=true`; see SUMMARY Deviations).

## fishing_spots.json

**Row count:** 30
**Distribution:** 18 Barnegat Bay interior (60%), 8 inlet/jetty (27%), 4 Atlantic surf (13%)
**Multi-orientation handling:** dual-jetty inlets are modeled as separate rows per CONTEXT.md D-07.
**FK integrity:** every `nearest_station` value references a station in `noaa_stations.json`. Verified programmatically by `backend/tests/unit/test_seed_spots_validator.py::test_fk_integrity_vs_stations`.

**Nearest-station assignment strategy:** because the only NJ Atlantic-coast stations with live water-level + water-temperature sensors are Sandy Hook (northern), Atlantic City (mid), and Cape May (southern), most Barnegat Bay interior spots map to `8534720` (Atlantic City — closest great-circle distance) with northern Barnegat Bay spots mapping to `8531680` (Sandy Hook). This is a known MVP simplification.

**Satellite verification:** Claude's first pass uses public satellite imagery via NOAA station pages + general map knowledge. The user spot-check in Task 3 is the authoritative gate — in this run the checkpoint was auto-approved by the orchestrator because `workflow.auto_advance=true`. The first real run of the Plan 04 data migration against live UI is the effective manual verification step.
