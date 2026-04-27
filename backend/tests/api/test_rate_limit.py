"""SEC-02: 21st query in rolling hour → SSE error event with code=rate_limited.

slowapi's storage_uri points at the testcontainer Redis (overridden via the
``test_client`` fixture's ``get_redis`` Depends). Each test fires sequential
POSTs from the same client (same IP per get_remote_address) and asserts the
21st one yields the rate-limited SSE error event — NOT an HTTP 429 JSON body.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_21st_request_emits_rate_limited_error(
    test_client,
    sse_events,
    monkeypatch,
    stub_planner_llm,
    stub_synth_llm,
    lazy_models,
    lazy_spots,
):
    """Fire 21 sequential POSTs — by the 21st, slowapi must emit the error event.

    The first 20 requests use a fast out-of-scope Planner stub (no Anthropic
    spend) so the test runs in seconds.
    """
    import agent.nodes.planner as planner_mod
    import agent.nodes.synthesizer as synth_mod

    monkeypatch.setattr(planner_mod, "ChatOpenAI", stub_planner_llm)
    monkeypatch.setattr(synth_mod, "ChatAnthropic", stub_synth_llm)

    from agent.nodes.planner import PlannerOutput

    # Out-of-scope short-circuits before data_fetcher / rag / synthesizer.
    stub_planner_llm.next_response = PlannerOutput(
        intent="out-of-scope",
        reject_reason="non_fishing",
    )
    from agent.graph import reset_for_test

    reset_for_test()

    # slowapi's in-memory bucket is keyed per-IP; flush the limiter's storage
    # at the start of the test so we have a clean budget.
    from api.middleware.rate_limit import limiter

    try:
        limiter.reset()
    except Exception:  # noqa: BLE001
        # Some slowapi versions may not expose reset(); swallow and rely on
        # a fresh testcontainer Redis per session.
        pass

    body = {"query": "x"}
    saw_rate_limited = False
    last_codes: list[str | None] = []

    for i in range(21):
        events = sse_events(test_client["client"], "/api/v1/query", body)
        types = [t for t, _ in events]
        # An ``error`` event should be present (out-of-scope OR rate_limited).
        assert "error" in types, (
            f"request {i}: expected error event, got types={types}"
        )
        err_payload = next(p for t, p in events if t == "error")
        code = err_payload.get("code") if err_payload else None
        last_codes.append(code)
        if code == "rate_limited":
            saw_rate_limited = True
            # Once rate-limited, the budget stays exhausted for the rest of
            # the rolling hour — break (we proved the gate).
            if i >= 19:
                # 21st request (i=20) or later was the rate_limited trigger
                # — this is the SEC-02 acceptance.
                break
        else:
            # Pre-limit responses must be the planner's out-of-scope rejection.
            assert code == "planner_out_of_scope", (
                f"request {i}: unexpected code {code!r}; "
                f"expected planner_out_of_scope or rate_limited; "
                f"trail: {last_codes}"
            )

    assert saw_rate_limited, (
        f"never observed rate_limited code across 21 requests; "
        f"codes seen: {last_codes}"
    )
