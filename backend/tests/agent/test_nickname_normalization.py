"""Nickname-canary contract test against ``fixtures/nickname_queries.json``.

Uses a faked LLM that returns the expected canonical for each query — this
is a CONTRACT test (planner_node correctly threads the LLM output through to
state), NOT an LLM-accuracy test. Real LLM accuracy was measured in Wave 0
and recorded in ``03-WAVE0-NOTES.md``; the live-API check is deferred to the
03-04 graph integration test.
"""
from __future__ import annotations

import json
import pathlib

import pytest

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "nickname_queries.json"


@pytest.fixture(autouse=True)
def _reset_singleton(stub_planner_llm):
    from agent.nodes.planner import _reset_planner_llm_for_tests

    _reset_planner_llm_for_tests()
    yield
    _reset_planner_llm_for_tests()


@pytest.mark.asyncio
async def test_planner_threads_canonical_to_state(stub_planner_llm):
    from agent.nodes.planner import planner_node, PlannerOutput

    queries = json.loads(FIXTURE.read_text())
    assert len(queries) >= 10, "expected ≥10 nickname canary entries"

    passes = 0
    failures: list[str] = []
    for q in queries:
        stub_planner_llm.next_response = PlannerOutput(
            intent="fishing-recommendation",
            species_canonical=q["expected_canonical"],
            reject_reason="none",
        )
        result = await planner_node({"query": q["query"]})
        if result["species_canonical"] == q["expected_canonical"] and result["intent"] == "fishing-recommendation":
            passes += 1
        else:
            failures.append(
                f"{q['query']!r} → expected {q['expected_canonical']!r}, "
                f"got species={result.get('species_canonical')!r} "
                f"intent={result.get('intent')!r}"
            )

    # Plan acceptance: ≥9/10 passing on contract test.
    assert passes >= 9, (
        f"Only {passes}/{len(queries)} canary cases passed; failures:\n"
        + "\n".join(failures)
    )


def test_canary_includes_sea_trout_case():
    """The W-0 sea-trout add MUST be present in the canary fixture."""
    queries = json.loads(FIXTURE.read_text())
    sea_trout_cases = [
        q for q in queries
        if "sea trout" in q["query"].lower() or "sea-trout" in q["query"].lower()
    ]
    assert sea_trout_cases, "sea-trout case missing from canary fixture"
    for q in sea_trout_cases:
        assert q["expected_canonical"] == "weakfish"
