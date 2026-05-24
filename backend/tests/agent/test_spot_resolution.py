"""Golden-fixture test for spot_resolver against the 20-query Wave 0 benchmark."""
from __future__ import annotations

import json
import pathlib

import pytest


FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "spot_resolution_queries.json"


@pytest.fixture
def resolver_with_seeds(lazy_spots):
    """Load the resolver with the production seeded spots.

    Strategy: read the same seeds JSON used by Phase 1 alembic migrations and
    reset_for_test() so we don't depend on a live Postgres testcontainer for
    a unit test.
    """
    from agent.spot_resolver import reset_for_test

    # Discover seeds path. Phase 1 plan 01-04 seeds via alembic data migration;
    # the JSON source lives under <repo_root>/seeds/fishing_spots.json.
    test_path = pathlib.Path(__file__).resolve()
    candidates = [
        # backend/seeds/fishing_spots.json
        test_path.parents[2] / "seeds" / "fishing_spots.json",
        # backend/db/seeds/fishing_spots.json
        test_path.parents[2] / "db" / "seeds" / "fishing_spots.json",
        # <repo_root>/seeds/fishing_spots.json (current layout)
        test_path.parents[3] / "seeds" / "fishing_spots.json",
    ]
    seeds_path = next((p for p in candidates if p.exists()), None)
    if seeds_path is None:
        pytest.skip(f"fishing_spots.json not found in any of: {candidates}")
    spots = json.loads(seeds_path.read_text())
    # Normalize: each entry must have id, name, lat, lon.
    normalized: list[dict] = []
    for i, s in enumerate(spots, start=1):
        normalized.append(
            {
                "id": s.get("id", i),
                "name": s["name"],
                "lat": float(s.get("lat") or s["latitude"]),
                "lon": float(s.get("lon") or s["longitude"]),
            }
        )
    reset_for_test(normalized)
    yield normalized


def test_spot_resolution_golden(resolver_with_seeds):
    from agent.spot_resolver import resolve_spot

    queries = json.loads(FIXTURE.read_text())
    correct = 0
    failures: list[str] = []
    for q in queries:
        got = resolve_spot(q["query"])
        expected = q["expected_spot_name"]  # may be None for non-matches
        ok = got.spot_name == expected
        if not ok:
            failures.append(
                f"  query={q['query']!r} expected={expected!r} got={got.spot_name!r} "
                f"strategy={got.strategy}"
            )
        correct += ok
    rate = correct / len(queries)
    assert rate >= 0.80, (
        f"Spot resolution accuracy {correct}/{len(queries)} = {rate:.0%} below 80% gate.\n"
        + "\n".join(failures)
    )


def test_no_query_no_coords_returns_none(resolver_with_seeds):
    from agent.spot_resolver import resolve_spot

    got = resolve_spot(None, None, None)
    assert got.strategy == "none"
    assert got.spot_id is None


def test_haversine_fallback_within_5km(resolver_with_seeds):
    from agent.spot_resolver import resolve_spot

    spot = resolver_with_seeds[0]
    # Same lat/lon — should always match
    got = resolve_spot(None, spot["lat"], spot["lon"])
    assert got.strategy == "haversine"
    assert got.spot_id == spot["id"]


def test_haversine_too_far_returns_no_pin(resolver_with_seeds):
    from agent.spot_resolver import resolve_spot

    # 200 km offset — way outside the 5 km threshold
    got = resolve_spot(None, 50.0, -100.0)
    assert got.strategy == "no_pin"


def test_inline_single_spot_match(lazy_spots):
    """Smoke test independent of seeds JSON layout — used by CI as a hard gate."""
    from agent.spot_resolver import reset_for_test, resolve_spot

    reset_for_test([{"id": 1, "name": "Barnegat Inlet", "lat": 39.76, "lon": -74.10}])
    got = resolve_spot("Barnegat")
    assert got.spot_id == 1
    assert got.strategy == "fuzzy_name"


def test_resolve_spot_expands_ibsp_acronym(lazy_spots):
    """Bare 'IBSP' must resolve to Island Beach State Park via acronym expansion.

    Without expansion, rapidfuzz WRatio scores "IBSP" vs
    "Island Beach State Park — A7 Pocket" well below the locked cutoff of 65.
    """
    from agent.spot_resolver import reset_for_test, resolve_spot

    reset_for_test(
        [{"id": 8, "name": "Island Beach State Park — A7 Pocket", "lat": 39.8, "lon": -74.1}]
    )
    got = resolve_spot("IBSP")
    assert got.spot_id == 8
    assert got.strategy == "fuzzy_name"


def test_resolve_spot_acronym_inside_sentence(lazy_spots):
    """Whole-token acronym in a free-text sentence still expands and resolves."""
    from agent.spot_resolver import reset_for_test, resolve_spot

    reset_for_test(
        [{"id": 8, "name": "Island Beach State Park — A7 Pocket", "lat": 39.8, "lon": -74.1}]
    )
    got = resolve_spot("IBSP surf this weekend")
    assert got.spot_id == 8
    assert got.strategy == "fuzzy_name"


def test_resolve_spot_unknown_token_unchanged(lazy_spots):
    """An unrecognized token must not be invented into a match."""
    from agent.spot_resolver import reset_for_test, resolve_spot

    reset_for_test(
        [{"id": 8, "name": "Island Beach State Park — A7 Pocket", "lat": 39.8, "lon": -74.1}]
    )
    got = resolve_spot("XXNotARealAcronym")
    assert got.spot_id is None
    assert got.strategy in ("no_pin", "none")
