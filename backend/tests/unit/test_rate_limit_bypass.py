"""Unit tests for the operator rate-limit bypass helper.

Verifies the pure logic of ``_is_bypass`` and ``_limit_for_request`` in
isolation from slowapi's internals (the SEC-02 integration test in
backend/tests/api/test_rate_limit.py covers the wire-level 429 path).

The bypass is operator-only: when ``TIDE_RATE_LIMIT_BYPASS_TOKEN`` is set
on the Cloud Run service AND a request carries header ``X-Tide-Test-Token``
matching that value, slowapi's key_func routes the request to a near-
unlimited bucket. Public traffic is unaffected — the 20/hour ceiling is
preserved.
"""
from __future__ import annotations

from types import SimpleNamespace



def _fake_request(headers: dict[str, str] | None = None) -> SimpleNamespace:
    """Minimal duck-typed Request — only ``.headers.get`` is used by ``_is_bypass``."""
    return SimpleNamespace(headers=(headers or {}))


def test_is_bypass_returns_true_for_matching_header(monkeypatch):
    from api.middleware import rate_limit as rl

    monkeypatch.setattr(rl.settings, "rate_limit_bypass_token", "secret-xyz")
    req = _fake_request({"X-Tide-Test-Token": "secret-xyz"})

    assert rl._is_bypass(req) is True


def test_is_bypass_returns_false_for_wrong_token(monkeypatch):
    from api.middleware import rate_limit as rl

    monkeypatch.setattr(rl.settings, "rate_limit_bypass_token", "secret-xyz")
    req = _fake_request({"X-Tide-Test-Token": "wrong-value"})

    assert rl._is_bypass(req) is False


def test_is_bypass_returns_false_when_header_missing(monkeypatch):
    from api.middleware import rate_limit as rl

    monkeypatch.setattr(rl.settings, "rate_limit_bypass_token", "secret-xyz")
    req = _fake_request({})

    assert rl._is_bypass(req) is False


def test_is_bypass_returns_false_when_token_unset(monkeypatch):
    """Critical: dev/local with no TIDE_RATE_LIMIT_BYPASS_TOKEN must NEVER
    treat any header value as a valid bypass — even an empty header.
    """
    from api.middleware import rate_limit as rl

    monkeypatch.setattr(rl.settings, "rate_limit_bypass_token", None)
    # Even a request that "looks" bypass-shaped must not be honored.
    req = _fake_request({"X-Tide-Test-Token": "anything"})

    assert rl._is_bypass(req) is False


def test_is_bypass_returns_false_when_token_empty_string(monkeypatch):
    """Empty-string token is treated as disabled (matches the `if not token`
    semantics in the helper). Prevents a misconfiguration where an empty
    secret accidentally exempts requests with an empty header.
    """
    from api.middleware import rate_limit as rl

    monkeypatch.setattr(rl.settings, "rate_limit_bypass_token", "")
    req = _fake_request({"X-Tide-Test-Token": ""})

    assert rl._is_bypass(req) is False


def test_limit_for_request_returns_high_ceiling_for_bypass_key():
    from api.middleware import rate_limit as rl

    assert rl._limit_for_request(rl._BYPASS_KEY) == rl._BYPASS_LIMIT


def test_limit_for_request_returns_public_ceiling_for_ip_key():
    from api.middleware import rate_limit as rl

    # ``get_remote_address``-style key (an IP literal) must hit the public limit.
    assert rl._limit_for_request("127.0.0.1") == rl._PUBLIC_LIMIT
    assert rl._limit_for_request("10.0.0.42") == rl._PUBLIC_LIMIT


def test_bypass_aware_key_routes_bypass_to_shared_bucket(monkeypatch):
    """Wires _is_bypass + key_func together: a valid bypass request must
    collapse to the shared ``bypass:tide-test`` bucket regardless of source IP.
    """
    from api.middleware import rate_limit as rl

    monkeypatch.setattr(rl.settings, "rate_limit_bypass_token", "secret-xyz")
    # Build a request that ``get_remote_address`` would normally read as
    # ``1.2.3.4`` — assert the bypass branch wins.
    req = SimpleNamespace(
        headers={"X-Tide-Test-Token": "secret-xyz"},
        client=SimpleNamespace(host="1.2.3.4"),
    )

    assert rl._bypass_aware_key(req) == rl._BYPASS_KEY


def test_bypass_aware_key_falls_back_to_remote_address(monkeypatch):
    from api.middleware import rate_limit as rl

    monkeypatch.setattr(rl.settings, "rate_limit_bypass_token", "secret-xyz")
    req = SimpleNamespace(
        headers={},  # no bypass header
        client=SimpleNamespace(host="1.2.3.4"),
    )

    assert rl._bypass_aware_key(req) == "1.2.3.4"
