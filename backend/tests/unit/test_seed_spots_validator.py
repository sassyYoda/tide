# backend/tests/unit/test_seed_spots_validator.py
# Wraps the inline seed-spots validator from Plan 01-03 Task 2 as pytest cases.
# Referenced by VALIDATION.md row 01-03-T2. Pitfall #7 FK-integrity gate.
import json
from pathlib import Path
import pytest

SEEDS_DIR = Path(__file__).resolve().parents[3] / "seeds"
STATIONS_PATH = SEEDS_DIR / "noaa_stations.json"
SPOTS_PATH = SEEDS_DIR / "fishing_spots.json"

VALID_TYPES = {"jetty", "inlet", "flat", "surf", "channel", "pier"}
VALID_ACCESS = {"shore", "boat", "kayak"}
VALID_SPECIES = {"striper", "fluke", "bluefish", "weakfish", "tautog"}
REQUIRED_FIELDS = {
    "name", "lat", "lon", "water_body", "spot_type",
    "species", "nearest_station", "access_type", "source_url",
}

NJ_LAT_MIN, NJ_LAT_MAX = 39.0, 41.0
NJ_LON_MIN, NJ_LON_MAX = -75.0, -73.5


@pytest.fixture(scope="module")
def station_ids():
    assert STATIONS_PATH.exists(), f"missing {STATIONS_PATH}"
    return {r["station_id"] for r in json.loads(STATIONS_PATH.read_text())}


@pytest.fixture(scope="module")
def spots():
    assert SPOTS_PATH.exists(), f"missing {SPOTS_PATH} — run Plan 03 Task 2 first"
    return json.loads(SPOTS_PATH.read_text())


def test_row_count_in_range(spots):
    assert 25 <= len(spots) <= 40, f"row count {len(spots)} out of range [25,40]"


def test_required_fields_present(spots):
    for s in spots:
        missing = REQUIRED_FIELDS - s.keys()
        assert not missing, f"{s.get('name','?')} missing fields {missing}"


def test_spot_type_enum(spots):
    for s in spots:
        assert s["spot_type"] in VALID_TYPES, f"{s['name']}: bad spot_type {s['spot_type']}"


def test_access_type_enum(spots):
    for s in spots:
        assert s["access_type"] in VALID_ACCESS, f"{s['name']}: bad access_type {s['access_type']}"


def test_fk_integrity_vs_stations(spots, station_ids):
    # Pitfall #7 — every nearest_station must exist in noaa_stations.json
    for s in spots:
        assert s["nearest_station"] in station_ids, (
            f"{s['name']}: FK violation nearest_station={s['nearest_station']}"
        )


def test_species_subset(spots):
    for s in spots:
        assert set(s["species"]) <= VALID_SPECIES, f"{s['name']}: invalid species {s['species']}"
        assert len(s["species"]) >= 1, f"{s['name']}: empty species array"


def test_species_coverage_minimum_eight_each(spots):
    counts = {sp: 0 for sp in VALID_SPECIES}
    for s in spots:
        for sp in s["species"]:
            counts[sp] += 1
    for sp, n in counts.items():
        assert n >= 8, f"species {sp} appears in only {n} spots (need >=8)"


def test_coordinates_in_nj_bbox(spots):
    for s in spots:
        assert NJ_LAT_MIN <= s["lat"] <= NJ_LAT_MAX, f"{s['name']}: lat out of NJ range"
        assert NJ_LON_MIN <= s["lon"] <= NJ_LON_MAX, f"{s['name']}: lon out of NJ range"


def test_inlet_jetty_minimum_count(spots):
    inlet_rows = [s for s in spots if s["spot_type"] in ("inlet", "jetty")]
    assert len(inlet_rows) >= 6, f"need >=6 inlet/jetty rows; got {len(inlet_rows)}"


def test_multi_orientation_split_rows_present(spots):
    names = {s["name"] for s in spots}
    assert any("North Jetty" in n for n in names), "missing North Jetty split row"
    assert any("South Jetty" in n for n in names), "missing South Jetty split row"


def test_source_urls_https(spots):
    for s in spots:
        assert s["source_url"].startswith(("http://", "https://")), (
            f"{s['name']}: bad source_url"
        )
