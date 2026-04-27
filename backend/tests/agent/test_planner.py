"""Unit tests for ``planner_node`` — uses ``stub_planner_llm`` to avoid real API calls.

Covers:
- in-scope happy path with species + location + time-window extraction
- out-of-scope: non_nj_geo + non_fishing
- empty-query safe default (no LLM call)
- SEC-06: user input never appears in the SystemMessage
- lexicon presence in the system prompt
"""
from __future__ import annotations

from datetime import datetime

import pytest


@pytest.fixture(autouse=True)
def _reset_singleton(stub_planner_llm):
    """Reset the planner_node LLM singleton so the freshly-stubbed
    ``ChatOpenAI`` is picked up on the very next call.
    """
    from agent.nodes.planner import _reset_planner_llm_for_tests

    _reset_planner_llm_for_tests()
    yield
    _reset_planner_llm_for_tests()


@pytest.mark.asyncio
async def test_planner_in_scope_extracts_species_and_location(stub_planner_llm):
    from agent.nodes.planner import planner_node, PlannerOutput

    stub_planner_llm.next_response = PlannerOutput(
        intent="fishing-recommendation",
        species_canonical="striper",
        location_hint_raw="Barnegat Inlet",
        time_window_label="Saturday morning",
        reject_reason="none",
    )
    result = await planner_node(
        {"query": "Where can I catch striper at Barnegat Inlet on Saturday morning?"}
    )
    assert result["intent"] == "fishing-recommendation"
    assert result["species_canonical"] == "striper"
    assert result["location_hint_raw"] == "Barnegat Inlet"
    assert result["time_window_label"] == "Saturday morning"
    assert result["reject_reason"] == "none"
    assert isinstance(result["time_window_start"], datetime)
    assert isinstance(result["time_window_end"], datetime)
    assert result["time_window_end"] > result["time_window_start"]
    assert result["planner_latency_ms"] >= 0.0


@pytest.mark.asyncio
async def test_planner_out_of_scope_geo(stub_planner_llm):
    from agent.nodes.planner import planner_node, PlannerOutput

    stub_planner_llm.next_response = PlannerOutput(
        intent="out-of-scope", reject_reason="non_nj_geo",
    )
    result = await planner_node({"query": "Where do I fish in Maine?"})
    assert result["intent"] == "out-of-scope"
    assert result["reject_reason"] == "non_nj_geo"


@pytest.mark.asyncio
async def test_planner_out_of_scope_non_fishing(stub_planner_llm):
    from agent.nodes.planner import planner_node, PlannerOutput

    stub_planner_llm.next_response = PlannerOutput(
        intent="out-of-scope", reject_reason="non_fishing",
    )
    result = await planner_node(
        {"query": "What's the boat rental price at Barnegat?"}
    )
    assert result["intent"] == "out-of-scope"
    assert result["reject_reason"] == "non_fishing"


@pytest.mark.asyncio
async def test_planner_out_of_scope_non_mvp_species(stub_planner_llm):
    from agent.nodes.planner import planner_node, PlannerOutput

    stub_planner_llm.next_response = PlannerOutput(
        intent="out-of-scope", reject_reason="non_mvp_species",
    )
    result = await planner_node({"query": "Where can I catch redfish in Brielle?"})
    assert result["intent"] == "out-of-scope"
    assert result["reject_reason"] == "non_mvp_species"


@pytest.mark.asyncio
async def test_planner_empty_query_safe_default(stub_planner_llm):
    """Empty query never reaches the LLM."""
    from agent.nodes.planner import planner_node

    result = await planner_node({"query": ""})
    assert result["intent"] == "out-of-scope"
    assert result["reject_reason"] == "non_fishing"
    assert result["planner_latency_ms"] == 0.0


@pytest.mark.asyncio
async def test_planner_no_species_returns_null(stub_planner_llm):
    """User asks generic 'what's biting' → species_canonical=null is OK."""
    from agent.nodes.planner import planner_node, PlannerOutput

    stub_planner_llm.next_response = PlannerOutput(
        intent="fishing-recommendation",
        species_canonical=None,
        location_hint_raw="Barnegat Bay",
        time_window_label=None,
        reject_reason="none",
    )
    result = await planner_node(
        {"query": "What's biting in Barnegat Bay right now?"}
    )
    assert result["intent"] == "fishing-recommendation"
    assert result["species_canonical"] is None
    assert result["location_hint_raw"] == "Barnegat Bay"


def test_system_prompt_does_not_echo_query():
    """SEC-06: user input must never reach the SystemMessage."""
    from agent.nodes.planner import _system_prompt

    sp = _system_prompt()
    # spot-check tokens a malicious user might inject
    for needle in ("IGNORE PREVIOUS", "INSTRUCTIONS:", "SYSTEM:", "${", "<script"):
        assert needle not in sp


def test_lexicon_block_present_in_system_prompt():
    """The lexicon (curated map + vocabulary anchor) must appear in the system prompt."""
    from agent.nodes.planner import _system_prompt, _NICKNAMES_BLOCK

    sp = _system_prompt()
    assert "MVP-5 species" in sp
    assert "Curated alias" in sp
    # All MVP-5 canonical names must be referenced
    for canonical in ("striper", "fluke", "bluefish", "weakfish", "tautog"):
        assert canonical in sp
    # The block builds successfully even when YAML is missing
    assert _NICKNAMES_BLOCK


def test_curated_aliases_cover_canary_terms():
    """Sanity: every nickname-canary expected canonical exists in our curated map."""
    from agent.nodes.planner import _ALIAS_TO_CANONICAL

    expected = {
        "blackfish": "tautog",
        "schoolies": "striper",
        "doormat": "fluke",
        "cocktail blue": "bluefish",
        "sea trout": "weakfish",
        "sea-trout": "weakfish",
        "linesider": "striper",
        "choppers": "bluefish",
        "whitelegger": "tautog",
        "fluker": "fluke",
        "weakies": "weakfish",
    }
    for alias, canonical in expected.items():
        assert _ALIAS_TO_CANONICAL.get(alias) == canonical, (
            f"missing or wrong mapping: {alias!r} → expected {canonical!r}, "
            f"got {_ALIAS_TO_CANONICAL.get(alias)!r}"
        )


def test_parse_time_window_saturday_morning_returns_pair():
    from agent.nodes.planner import _parse_time_window

    start, end = _parse_time_window("Saturday morning")
    assert start is not None and end is not None
    assert end > start
    # 06:00 → 11:00 NJ-local
    assert start.hour == 6
    assert end.hour == 11


def test_parse_time_window_none_returns_none_pair():
    from agent.nodes.planner import _parse_time_window

    assert _parse_time_window(None) == (None, None)
    assert _parse_time_window("") == (None, None)


def test_parse_time_window_tomorrow_afternoon():
    from agent.nodes.planner import _parse_time_window

    start, end = _parse_time_window("tomorrow afternoon")
    assert start is not None and end is not None
    assert start.hour == 12
    assert end.hour == 16
