"""A-09: empty ``SPECIES_MODELS`` ⇒ ``ml_score_available=False``; conditions still read.

These are unit tests — no testcontainer needed. We monkeypatch the DB
session factory to a stub and the ml singletons to empty dicts.
"""
from __future__ import annotations

from typing import Any

import pytest


class _StubResultEmpty:
    def scalar_one_or_none(self) -> None:
        return None

    def scalars(self) -> "_StubResultEmpty":
        return self

    def all(self) -> list[Any]:
        return []

    def first(self) -> None:
        return None

    def mappings(self) -> "_StubResultEmpty":
        return self


class _StubAsyncSession:
    """Minimal async session that returns no rows for every query."""

    async def __aenter__(self) -> "_StubAsyncSession":
        return self

    async def __aexit__(self, *_a: Any) -> bool:
        return False

    async def execute(self, *_a: Any, **_kw: Any) -> _StubResultEmpty:
        return _StubResultEmpty()


@pytest.mark.asyncio
async def test_fresh_score_one_spot_returns_none_when_models_empty(monkeypatch):
    """``_fresh_score_one_spot`` returns (None, None) when SPECIES_MODELS is empty (A-09)."""
    from agent.nodes import data_fetcher as df

    # Patch the deferred import path AFTER the module is loaded so the
    # function's local `from ml.model import ...` picks up the patched dict.
    monkeypatch.setattr("ml.model.SPECIES_MODELS", {})

    score, top3 = await df._fresh_score_one_spot(
        _StubAsyncSession(), spot_id=1, species="striper",
    )
    assert score is None
    assert top3 is None


@pytest.mark.asyncio
async def test_data_fetcher_no_species_keeps_conditions_path(
    monkeypatch, lazy_models, lazy_spots,
):
    """species_canonical=None ⇒ ml_score_available=False but no raise; spot still resolved."""
    from agent.nodes.data_fetcher import data_fetcher_node
    from agent.spot_resolver import reset_for_test

    # Single seeded spot for the resolver to fuzzy-match against.
    reset_for_test([{
        "id": 1, "name": "Barnegat Inlet", "lat": 39.0, "lon": -74.0,
    }])

    # Stub the DB session factory so no real DB is needed.
    monkeypatch.setattr(
        "db.session.async_session_factory", lambda: _StubAsyncSession(),
    )

    out = await data_fetcher_node({
        "query": "general fishing",
        "species_canonical": None,
        "location_hint_raw": "Barnegat Inlet",
    })
    assert out["spot_id"] == 1
    assert out["spot_resolution_strategy"] == "fuzzy_name"
    assert out["ml_score_available"] is False
    assert out["ml_score"] is None
    assert out["conditions_stale"] is False  # default
    assert out["data_fetcher_latency_ms"] >= 0


@pytest.mark.asyncio
async def test_data_fetcher_species_missing_from_models_graceful(
    monkeypatch, lazy_models, lazy_spots,
):
    """species set + SPECIES_MODELS empty + no persisted score ⇒ ml_score_available=False."""
    from agent.nodes.data_fetcher import data_fetcher_node
    from agent.spot_resolver import reset_for_test

    monkeypatch.setattr("ml.model.SPECIES_MODELS", {})
    reset_for_test([{
        "id": 7, "name": "Sea Girt", "lat": 40.13, "lon": -74.04,
    }])
    monkeypatch.setattr(
        "db.session.async_session_factory", lambda: _StubAsyncSession(),
    )

    out = await data_fetcher_node({
        "query": "weakfish near Sea Girt",
        "species_canonical": "weakfish",
        "location_hint_raw": "Sea Girt",
    })
    assert out["spot_id"] == 7
    assert out["ml_score"] is None
    assert out["shap_top3"] is None
    assert out["ml_score_available"] is False
    # No raise — graceful (A-09).


def test_summarize_conditions_whitelists_only():
    """T-03-02-03: only whitelisted feature keys appear in the summary."""
    from agent.nodes.data_fetcher import _summarize_conditions

    raw = {
        "features": {
            "tide_height_m": 0.4,
            "wind_speed_mps": 5.0,
            "secret_internal_feature": "should not appear",
            "another_unsafe_field": 42,
        },
        "model_run_id": "abc123",
    }
    summary = _summarize_conditions(raw)
    assert "tide_height_m" in summary
    assert "wind_speed_mps" in summary
    assert "secret_internal_feature" not in summary
    assert "another_unsafe_field" not in summary
    assert "model_run_id" not in summary  # outside whitelist


def test_shap_top3_handles_top_features_shape():
    """Phase-2 scorer writes ``shap_values = {'top_features': [{'feature':, 'value':}, ...]}``."""
    from agent.nodes.data_fetcher import _shap_top3_names

    sv = {
        "top_features": [
            {"feature": "tide_phase_incoming", "value": 0.35},
            {"feature": "wind_speed_mps", "value": -0.20},
            {"feature": "tide_height_m", "value": 0.15},
        ]
    }
    names = _shap_top3_names(sv)
    assert names == ["tide_phase_incoming", "wind_speed_mps", "tide_height_m"]


def test_shap_top3_handles_legacy_top3_shape():
    """Legacy shape ``{'top3': [name, name, name]}`` still works."""
    from agent.nodes.data_fetcher import _shap_top3_names

    sv = {"top3": ["a", "b", "c", "d"]}
    names = _shap_top3_names(sv)
    assert names == ["a", "b", "c"]


def test_shap_top3_returns_none_for_empty():
    from agent.nodes.data_fetcher import _shap_top3_names

    assert _shap_top3_names(None) is None
    assert _shap_top3_names({}) is None
    assert _shap_top3_names({"top_features": []}) is None
