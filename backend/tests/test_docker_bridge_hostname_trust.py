"""Issue #250 (tg12): Docker bridge local-operator trust must be bound to
the frontend container's hostname, not the entire 172.16.0.0/12 range.

Previous behavior trusted ANY private-RFC1918 source IP on the bridge
when ``SHADOWBROKER_TRUST_DOCKER_BRIDGE_LOCAL_OPERATOR=1``. On a shared
Docker host this granted local-operator privileges to any other
container that could route to the backend's bridge — far broader than
intended.

The fix narrows trust to source IPs that forward-resolve from one of the
configured frontend container hostnames (default: the compose service
name ``frontend`` plus the explicit ``container_name``
``vincent_os-frontend``). Operators with renamed containers can list
the new names in ``SHADOWBROKER_TRUSTED_FRONTEND_HOSTS``.

These tests exercise the resolution helpers directly so that we don't
need a live Docker daemon to validate the contract.
"""
import socket
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# _trusted_bridge_frontend_hostnames — env parsing
# ---------------------------------------------------------------------------

class TestTrustedHostnameParsing:
    def _fn(self):
        from auth import _trusted_bridge_frontend_hostnames
        return _trusted_bridge_frontend_hostnames

    def test_default_covers_compose_service_and_container_name(self):
        with patch.dict("os.environ", {}, clear=False):
            # Make sure the env var is not set so we exercise the default.
            import os
            os.environ.pop("SHADOWBROKER_TRUSTED_FRONTEND_HOSTS", None)
            assert self._fn()() == ["frontend", "vincent_os-frontend"]

    def test_custom_list_via_env(self):
        with patch.dict(
            "os.environ",
            {"SHADOWBROKER_TRUSTED_FRONTEND_HOSTS": "my-ui,alt-frontend"},
        ):
            assert self._fn()() == ["my-ui", "alt-frontend"]

    def test_whitespace_trimmed(self):
        with patch.dict(
            "os.environ",
            {"SHADOWBROKER_TRUSTED_FRONTEND_HOSTS": "  my-ui , alt-frontend  "},
        ):
            assert self._fn()() == ["my-ui", "alt-frontend"]

    def test_empty_env_falls_back_to_default(self):
        # An empty string still falls back to the bundled defaults so a
        # misconfigured env var doesn't silently dismantle bridge trust.
        with patch.dict(
            "os.environ",
            {"SHADOWBROKER_TRUSTED_FRONTEND_HOSTS": ""},
        ):
            # Per docs: empty string sets the env var to "" so os.environ.get
            # returns "" — that string is parsed and yields []. We assert
            # that empty parse yields [] (caller fail-closes from there).
            assert self._fn()() == []


# ---------------------------------------------------------------------------
# _resolve_trusted_bridge_ips — DNS resolution with cache + fail-closed
# ---------------------------------------------------------------------------

class TestResolveTrustedBridgeIps:
    def setup_method(self):
        # Reset the module-level cache before each test so prior tests
        # don't bleed state across cases.
        from auth import _DOCKER_BRIDGE_TRUST_CACHE
        _DOCKER_BRIDGE_TRUST_CACHE["ips"] = frozenset()
        _DOCKER_BRIDGE_TRUST_CACHE["expires"] = 0.0

    def test_resolves_configured_hostnames(self):
        from auth import _resolve_trusted_bridge_ips

        def fake_gethostbyname_ex(host):
            mapping = {
                "frontend": ("frontend", [], ["172.18.0.3"]),
                "vincent_os-frontend": ("vincent_os-frontend", [], ["172.18.0.3", "172.18.0.4"]),
            }
            if host not in mapping:
                raise socket.gaierror("no such host")
            return mapping[host]

        with patch("socket.gethostbyname_ex", side_effect=fake_gethostbyname_ex):
            ips = _resolve_trusted_bridge_ips()
        assert ips == frozenset({"172.18.0.3", "172.18.0.4"})

    def test_fail_closed_when_dns_returns_nothing(self):
        from auth import _resolve_trusted_bridge_ips

        def always_fail(host):
            raise socket.gaierror("no resolver")

        with patch("socket.gethostbyname_ex", side_effect=always_fail):
            ips = _resolve_trusted_bridge_ips()
        assert ips == frozenset()

    def test_partial_resolution_is_kept(self):
        """If one hostname resolves and another fails, we keep the
        successful one rather than discarding the whole set."""
        from auth import _resolve_trusted_bridge_ips

        def partial(host):
            if host == "frontend":
                return ("frontend", [], ["172.18.0.3"])
            raise socket.gaierror("missing")

        with patch("socket.gethostbyname_ex", side_effect=partial):
            ips = _resolve_trusted_bridge_ips()
        assert ips == frozenset({"172.18.0.3"})

    def test_cache_short_circuits_repeated_dns_calls(self):
        from auth import _resolve_trusted_bridge_ips

        call_count = {"n": 0}

        def counting(host):
            call_count["n"] += 1
            return ("frontend", [], ["172.18.0.3"])

        with patch("socket.gethostbyname_ex", side_effect=counting):
            _resolve_trusted_bridge_ips()
            calls_after_first = call_count["n"]
            _resolve_trusted_bridge_ips()
            _resolve_trusted_bridge_ips()
        # Second + third calls hit the cache, not the DNS stub.
        assert call_count["n"] == calls_after_first

    def test_cache_expires(self):
        from auth import _resolve_trusted_bridge_ips, _DOCKER_BRIDGE_TRUST_CACHE

        with patch("socket.gethostbyname_ex", return_value=("frontend", [], ["172.18.0.3"])):
            _resolve_trusted_bridge_ips()
        # Force expiry.
        _DOCKER_BRIDGE_TRUST_CACHE["expires"] = 0.0
        with patch("socket.gethostbyname_ex", return_value=("frontend", [], ["172.18.0.9"])) as stub:
            ips = _resolve_trusted_bridge_ips()
            assert stub.called
        assert "172.18.0.9" in ips


# ---------------------------------------------------------------------------
# _is_docker_bridge_host — composite of the helpers above
# ---------------------------------------------------------------------------

class TestIsDockerBridgeHost:
    def setup_method(self):
        from auth import _DOCKER_BRIDGE_TRUST_CACHE
        _DOCKER_BRIDGE_TRUST_CACHE["ips"] = frozenset()
        _DOCKER_BRIDGE_TRUST_CACHE["expires"] = 0.0

    def test_trusts_resolved_frontend_ip(self):
        from auth import _is_docker_bridge_host

        with patch("auth._resolve_trusted_bridge_ips", return_value=frozenset({"172.18.0.3"})):
            assert _is_docker_bridge_host("172.18.0.3") is True

    def test_rejects_arbitrary_bridge_ip(self):
        """A rogue container on the same bridge but at a different IP
        must NOT be trusted, even though it falls in 172.16.0.0/12."""
        from auth import _is_docker_bridge_host

        with patch("auth._resolve_trusted_bridge_ips", return_value=frozenset({"172.18.0.3"})):
            assert _is_docker_bridge_host("172.18.0.99") is False

    def test_rejects_public_ip_without_dns_work(self):
        """Public IPs skip DNS resolution entirely (perf + safety)."""
        from auth import _is_docker_bridge_host

        with patch("auth._resolve_trusted_bridge_ips") as stub:
            assert _is_docker_bridge_host("8.8.8.8") is False
            stub.assert_not_called()

    def test_rejects_non_ip_input(self):
        from auth import _is_docker_bridge_host

        assert _is_docker_bridge_host("") is False
        assert _is_docker_bridge_host("not-an-ip") is False
        assert _is_docker_bridge_host("frontend") is False

    def test_fails_closed_when_dns_returns_empty(self):
        """If Docker DNS can't resolve any frontend hostname, the bridge
        is not trusted — even for IPs that would have been trusted under
        the old 172.16.0.0/12 blanket policy."""
        from auth import _is_docker_bridge_host

        with patch("auth._resolve_trusted_bridge_ips", return_value=frozenset()):
            assert _is_docker_bridge_host("172.18.0.3") is False
