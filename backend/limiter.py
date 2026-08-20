"""Rate-limit key function for slowapi.

Issue #287 (tg12): the previous implementation used
``slowapi.util.get_remote_address`` which only ever returns
``request.client.host``. Behind the bundled Next.js proxy (or any other
reverse proxy), every connected operator's ``client.host`` is the
frontend container's bridge IP. ``@limiter.limit("120/minute")`` then
collapses into one shared bucket for everybody on the same backend —
one heavy tab can starve every other operator on the node.

This module replaces that key function with one that:

  * Reads ``X-Forwarded-For`` ONLY when the immediate peer is a trusted
    frontend container (same allowlist used by the Docker bridge
    local-operator trust path — see ``backend/auth.py`` ``#250``).
  * Picks the FIRST entry in the XFF chain. That's the client end of
    the proxy chain, which is the operator we want to bucket on.
  * Falls back to ``request.client.host`` for any peer that isn't on
    the trusted-frontend allowlist. Direct hits, unrelated containers,
    and unknown hosts are bucketed exactly like before — there is no
    way for an untrusted caller to spoof XFF and steal another
    operator's rate-limit bucket.

Single-operator nodes are unaffected: the frontend resolves to one IP,
that IP is on the trust list, the XFF header is read, and you get one
bucket per operator (i.e. you).
"""

from __future__ import annotations

from typing import Any

from slowapi import Limiter
from slowapi.util import get_remote_address


def _client_host(request: Any) -> str:
    """Return the immediate peer's IP, normalised to a lowercase string."""
    client = getattr(request, "client", None)
    if client is None:
        return ""
    host = getattr(client, "host", "") or ""
    return host.lower()


def _first_forwarded_for(value: str) -> str:
    """Return the first non-empty entry from an ``X-Forwarded-For`` header.

    RFC 7239 / de-facto XFF format is ``client, proxy1, proxy2, …``. The
    client end is what we want to bucket on. Empty parts (which appear
    in some malformed headers) are skipped so we don't end up keying on
    an empty string.
    """
    for raw in value.split(","):
        candidate = raw.strip()
        if candidate:
            return candidate.lower()
    return ""


def _is_trusted_frontend_peer(host: str) -> bool:
    """True iff ``host`` is one of the resolved trusted-frontend IPs.

    Imported lazily so this module stays usable in unit tests that
    don't want to pull the whole auth module into scope.
    """
    if not host:
        return False
    try:
        from auth import _resolve_trusted_bridge_ips
    except Exception:  # pragma: no cover - defensive
        return False
    try:
        trusted_ips = _resolve_trusted_bridge_ips()
    except Exception:  # pragma: no cover - defensive
        return False
    return host in trusted_ips


def vincent_os_rate_limit_key(request: Any) -> str:
    """slowapi key_func that is proxy-aware on trusted frontend peers only.

    Behaviour matrix:

    * Direct loopback / unknown peer → ``request.client.host``
      (identical to slowapi's default ``get_remote_address``).
    * Peer is a trusted frontend container AND ``X-Forwarded-For`` is
      present → first XFF entry (the actual operator).
    * Peer is a trusted frontend container but no XFF → fall back to
      ``request.client.host`` (the bridge IP). One shared bucket for
      everyone in that case, same as before — but you only get there
      if the trusted frontend forgot to forward XFF, which it won't.
    """
    peer = _client_host(request)
    if _is_trusted_frontend_peer(peer):
        headers = getattr(request, "headers", None)
        if headers is not None:
            xff = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
            if xff:
                first = _first_forwarded_for(xff)
                if first:
                    return first
    # Untrusted peer (or trusted peer without XFF): match the original
    # get_remote_address behaviour byte-for-byte.
    return get_remote_address(request)


limiter = Limiter(key_func=vincent_os_rate_limit_key)
