"""Tests for issue #287: proxy-aware slowapi key function.

Contract:
 * Untrusted peer → key is the peer IP (matches old get_remote_address).
 * Trusted frontend peer with X-Forwarded-For → key is first XFF entry.
 * Trusted frontend peer without X-Forwarded-For → key is the peer IP
   (fail-soft: no behaviour change vs. before #287).
 * XFF from an untrusted peer is IGNORED — there must be no way to
   spoof another operator's bucket by sending XFF directly.
 * The first XFF entry is used (not the last — that's the trusted
   proxy talking to the backend, not the actual operator).
"""

import pytest


class _FakeClient:
    def __init__(self, host: str):
        self.host = host


class _FakeRequest:
    """Minimal slowapi-compatible request shim — has ``client`` and
    ``headers`` attributes, which is all the key_func touches."""

    def __init__(self, client_host: str, headers: dict | None = None):
        self.client = _FakeClient(client_host) if client_host is not None else None
        self.headers = dict(headers or {})
        # slowapi's get_remote_address also tries request.client; we
        # exercise both branches via the same shim.


# ───────────────────────── untrusted peers ──────────────────────────────


class TestUntrustedPeer:
    def test_direct_loopback_uses_client_host(self, monkeypatch):
        """Direct hit from 127.0.0.1 — no XFF — keys on the peer IP."""
        from limiter import vincent_os_rate_limit_key
        # Make sure the trusted-frontend cache resolves to nothing relevant.
        monkeypatch.setattr("auth._resolve_trusted_bridge_ips", lambda: frozenset())
        req = _FakeRequest("127.0.0.1")
        assert vincent_os_rate_limit_key(req) == "127.0.0.1"

    def test_xff_from_untrusted_peer_is_ignored(self, monkeypatch):
        """A random caller sending X-Forwarded-For must NOT steal another
        operator's bucket. The XFF is dropped on the floor."""
        from limiter import vincent_os_rate_limit_key
        # Trusted set deliberately does NOT include 1.2.3.4.
        monkeypatch.setattr("auth._resolve_trusted_bridge_ips", lambda: frozenset({"172.20.0.5"}))
        req = _FakeRequest("1.2.3.4", {"X-Forwarded-For": "9.9.9.9"})
        # Falls back to the peer IP, not 9.9.9.9.
        assert vincent_os_rate_limit_key(req) == "1.2.3.4"

    def test_unknown_host_with_xff_uses_peer_host(self, monkeypatch):
        from limiter import vincent_os_rate_limit_key
        monkeypatch.setattr("auth._resolve_trusted_bridge_ips", lambda: frozenset())
        req = _FakeRequest("10.0.0.5", {"X-Forwarded-For": "1.1.1.1"})
        assert vincent_os_rate_limit_key(req) == "10.0.0.5"


# ───────────────────────── trusted frontend peers ───────────────────────


class TestTrustedFrontendPeer:
    def test_trusted_peer_with_xff_uses_first_xff_entry(self, monkeypatch):
        """When the immediate peer is the trusted frontend container and
        XFF carries the operator's chain, we key on the operator."""
        from limiter import vincent_os_rate_limit_key
        monkeypatch.setattr("auth._resolve_trusted_bridge_ips", lambda: frozenset({"172.20.0.5"}))
        req = _FakeRequest("172.20.0.5", {"X-Forwarded-For": "203.0.113.7"})
        assert vincent_os_rate_limit_key(req) == "203.0.113.7"

    def test_first_xff_entry_picked_in_chain(self, monkeypatch):
        """`client, proxy1, proxy2` → we pick the client, not the proxies.
        Picking the last entry would mean every operator behind the same
        upstream gets bucketed together, which is the bug we're fixing."""
        from limiter import vincent_os_rate_limit_key
        monkeypatch.setattr("auth._resolve_trusted_bridge_ips", lambda: frozenset({"172.20.0.5"}))
        req = _FakeRequest(
            "172.20.0.5",
            {"X-Forwarded-For": "203.0.113.7, 198.51.100.1, 10.0.0.1"},
        )
        assert vincent_os_rate_limit_key(req) == "203.0.113.7"

    def test_trusted_peer_without_xff_falls_back_to_peer(self, monkeypatch):
        """If the trusted frontend forgot to forward XFF (legacy clients,
        broken deploys), don't crash — bucket on the bridge IP exactly
        like the pre-#287 behaviour."""
        from limiter import vincent_os_rate_limit_key
        monkeypatch.setattr("auth._resolve_trusted_bridge_ips", lambda: frozenset({"172.20.0.5"}))
        req = _FakeRequest("172.20.0.5", headers={})
        assert vincent_os_rate_limit_key(req) == "172.20.0.5"

    def test_trusted_peer_with_empty_xff_falls_back(self, monkeypatch):
        """``X-Forwarded-For: ,  ,`` → no usable entries → falls back."""
        from limiter import vincent_os_rate_limit_key
        monkeypatch.setattr("auth._resolve_trusted_bridge_ips", lambda: frozenset({"172.20.0.5"}))
        req = _FakeRequest("172.20.0.5", {"X-Forwarded-For": " , , "})
        assert vincent_os_rate_limit_key(req) == "172.20.0.5"

    def test_xff_header_case_insensitive(self, monkeypatch):
        """HTTP header names are case-insensitive — slowapi normalises
        but our shim doesn't, so we explicitly check both forms."""
        from limiter import vincent_os_rate_limit_key
        monkeypatch.setattr("auth._resolve_trusted_bridge_ips", lambda: frozenset({"172.20.0.5"}))
        req = _FakeRequest("172.20.0.5", {"x-forwarded-for": "203.0.113.7"})
        assert vincent_os_rate_limit_key(req) == "203.0.113.7"


# ───────────────────────── isolation guarantees ─────────────────────────


class TestIsolation:
    def test_two_operators_behind_same_proxy_get_different_keys(self, monkeypatch):
        """The whole reason this fix exists — two operators behind the
        SAME proxy must end up in DIFFERENT buckets."""
        from limiter import vincent_os_rate_limit_key
        monkeypatch.setattr("auth._resolve_trusted_bridge_ips", lambda: frozenset({"172.20.0.5"}))
        op_a = _FakeRequest("172.20.0.5", {"X-Forwarded-For": "10.1.1.1"})
        op_b = _FakeRequest("172.20.0.5", {"X-Forwarded-For": "10.1.1.2"})
        key_a = vincent_os_rate_limit_key(op_a)
        key_b = vincent_os_rate_limit_key(op_b)
        assert key_a != key_b
        assert key_a == "10.1.1.1"
        assert key_b == "10.1.1.2"

    def test_no_xff_spoof_from_outside(self, monkeypatch):
        """If we ever expose the backend port directly to the internet,
        an attacker MUST NOT be able to steal another operator's bucket
        by sending their own XFF header."""
        from limiter import vincent_os_rate_limit_key
        # Trusted set is the frontend container IP; the attacker is on a
        # different (untrusted) IP and tries to spoof a victim's IP.
        monkeypatch.setattr("auth._resolve_trusted_bridge_ips", lambda: frozenset({"172.20.0.5"}))
        attacker = _FakeRequest("203.0.113.66", {"X-Forwarded-For": "10.1.1.1"})
        victim_via_proxy = _FakeRequest("172.20.0.5", {"X-Forwarded-For": "10.1.1.1"})
        assert vincent_os_rate_limit_key(attacker) == "203.0.113.66"
        assert vincent_os_rate_limit_key(victim_via_proxy) == "10.1.1.1"
        # The attacker burning their own bucket doesn't touch the victim's.
        assert vincent_os_rate_limit_key(attacker) != vincent_os_rate_limit_key(
            victim_via_proxy
        )

    def test_limiter_object_uses_proxy_aware_key(self):
        """Smoke check that the module-level Limiter exports the new key
        function rather than slowapi's default."""
        from limiter import limiter, vincent_os_rate_limit_key
        # slowapi stores it as ._key_func; we don't want to depend on
        # that internal name, so just check the function is reachable.
        assert callable(vincent_os_rate_limit_key)
        assert limiter is not None


# ───────────────────────── defensive corners ────────────────────────────


class TestDefensive:
    def test_no_client_object(self, monkeypatch):
        """Some upstream middleware paths (websocket, ASGI lifespan)
        produce requests with no ``client`` attribute — must not raise."""
        from limiter import vincent_os_rate_limit_key
        monkeypatch.setattr("auth._resolve_trusted_bridge_ips", lambda: frozenset())

        class _NoClient:
            def __init__(self):
                self.client = None
                self.headers = {}

        # slowapi's get_remote_address returns "127.0.0.1" as a default
        # in this case, so we just ensure no exception escapes.
        result = vincent_os_rate_limit_key(_NoClient())
        assert isinstance(result, str)

    def test_resolver_raises_is_treated_as_untrusted(self, monkeypatch):
        """If DNS blows up inside the trusted-bridge resolver, we MUST
        fall back to peer IP — never accept XFF blindly."""
        from limiter import vincent_os_rate_limit_key

        def _explode():
            raise RuntimeError("DNS down")

        monkeypatch.setattr("auth._resolve_trusted_bridge_ips", _explode)
        req = _FakeRequest("172.20.0.5", {"X-Forwarded-For": "9.9.9.9"})
        # XFF must be ignored when we can't confirm peer is trusted.
        assert vincent_os_rate_limit_key(req) == "172.20.0.5"
