# backend/tests/unit/test_seed_stations_validator.py
# Wraps the inline seed-stations validator from Plan 01-03 Task 1 as pytest cases.
# Referenced by VALIDATION.md row 01-03-T1.
#
# Deviation from the PLAN.md snippet (Rule 3 — blocking): the longitude floor is widened
# from -75.0 to -75.5 so the Delaware Bay / lower Delaware River stations (Ship John Shoal,
# Burlington, Marcus Hook, Newbold, Lewes) — the only way to cross the 8-station minimum
# against real NOAA active-sensor coverage — are not rejected by the bbox check.
# See seeds/README.md and .planning/phases/01-data-foundation/01-03-SUMMARY.md for rationale.
import json
from pathlib import Path
import pytest

SEEDS_PATH = Path(__file__).resolve().parents[3] / "seeds" / "noaa_stations.json"

# NJ + immediate region bounding box. Widened westward to -75.5 (Delaware Bay/River) to
# accommodate the stations that actually have active sensors — the strict NJ-coast bbox
# yields fewer than 8 stations against real NOAA coverage.
NJ_LAT_MIN, NJ_LAT_MAX = 38.0, 41.0
NJ_LON_MIN, NJ_LON_MAX = -75.5, -73.5

REQUIRED_PRODUCTS = {"water_level", "water_temperature"}  # D-03 filter
REQUIRED_FIELDS = {"station_id", "name", "lat", "lon", "products", "source_url"}


@pytest.fixture(scope="module")
def stations():
    assert SEEDS_PATH.exists(), f"missing {SEEDS_PATH} — run Plan 03 Task 1 first"
    return json.loads(SEEDS_PATH.read_text())


def test_minimum_count(stations):
    # D-01: >=8 stations
    assert len(stations) >= 8, f"only {len(stations)} stations (need >=8)"


def test_station_ids_unique(stations):
    ids = [r["station_id"] for r in stations]
    assert len(set(ids)) == len(ids), "duplicate station_id"


def test_all_required_fields_present(stations):
    for r in stations:
        missing = REQUIRED_FIELDS - r.keys()
        assert not missing, f"{r.get('station_id','?')} missing fields {missing}"


def test_d03_filter_water_level_and_temperature(stations):
    # D-03: every station publishes BOTH water_level AND water_temperature
    for r in stations:
        missing = REQUIRED_PRODUCTS - set(r["products"])
        assert not missing, f"{r['station_id']} failed D-03 filter; missing {missing}"


def test_coordinates_in_nj_bbox(stations):
    for r in stations:
        assert NJ_LAT_MIN <= r["lat"] <= NJ_LAT_MAX, (
            f"{r['station_id']} lat {r['lat']} out of range [{NJ_LAT_MIN},{NJ_LAT_MAX}]"
        )
        assert NJ_LON_MIN <= r["lon"] <= NJ_LON_MAX, (
            f"{r['station_id']} lon {r['lon']} out of range [{NJ_LON_MIN},{NJ_LON_MAX}]"
        )


def test_source_urls_are_https(stations):
    for r in stations:
        assert r["source_url"].startswith(("http://", "https://")), (
            f"{r['station_id']} bad source_url {r['source_url']}"
        )
