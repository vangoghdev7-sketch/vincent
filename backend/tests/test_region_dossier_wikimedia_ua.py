"""Issues #218 / #219 (tg12): outbound Wikipedia + Wikidata calls must
identify Vincent OS via the Wikimedia-recommended User-Agent /
Api-User-Agent headers.

Before this fix, ``backend/services/region_dossier.py`` called
``fetch_with_curl(url)`` with no explicit headers, falling back to the
generic project default UA. That sent a too-anonymous identifier to
Wikimedia. Per Wikimedia's policy
(https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy)
the API caller should send a stable, contactable identifier so Wikimedia
operators can rate-limit or reach the project.

This test does NOT make network calls. It patches ``fetch_with_curl``
and asserts the headers that get passed through.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _fake_resp(payload: dict, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    return r


def test_wikidata_call_passes_wikimedia_request_headers():
    from services import region_dossier

    calls = []

    def fake_fetch(url, **kwargs):
        calls.append(kwargs.get("headers"))
        return _fake_resp({"results": {"bindings": []}})

    with patch.object(region_dossier, "fetch_with_curl", side_effect=fake_fetch):
        region_dossier._fetch_wikidata_leader("Testlandia")

    assert calls, "fetch_with_curl was not called"
    headers = calls[0] or {}
    assert "User-Agent" in headers
    assert "Api-User-Agent" in headers
    # Stable identifier should mention the project + a contact path.
    assert "Vincent OS" in headers["Api-User-Agent"] or "Vincent OS" in headers["Api-User-Agent"]
    assert "github.com" in headers["Api-User-Agent"].lower()


def test_wikipedia_summary_call_passes_wikimedia_request_headers():
    from services import region_dossier

    calls = []

    def fake_fetch(url, **kwargs):
        calls.append((url, kwargs.get("headers")))
        return _fake_resp(
            {
                "type": "standard",
                "description": "test desc",
                "extract": "test extract",
                "thumbnail": {"source": ""},
            }
        )

    with patch.object(region_dossier, "fetch_with_curl", side_effect=fake_fetch):
        region_dossier._fetch_local_wiki_summary("Paris", "France")

    # At least one Wikipedia REST call was issued.
    wikipedia_calls = [c for c in calls if "wikipedia.org" in c[0]]
    assert wikipedia_calls, "no Wikipedia call was issued"
    for url, headers in wikipedia_calls:
        headers = headers or {}
        assert "User-Agent" in headers, f"missing User-Agent on {url}"
        assert "Api-User-Agent" in headers, f"missing Api-User-Agent on {url}"
        assert "github.com" in headers["Api-User-Agent"].lower()


def test_wikimedia_headers_helper_is_stable():
    """Regression guard: if someone removes the contact path or the
    per-operator handle from the Wikimedia headers, we want a loud
    test failure, not a silent ToS drift.

    Round 7a: the original ``_WIKIMEDIA_REQUEST_HEADERS`` constant was
    replaced with the ``_wikimedia_request_headers()`` function so the
    per-install operator handle is embedded at call time. This test
    pins both the project identifier AND the contact path AND the
    per-operator format.
    """
    from services.region_dossier import _wikimedia_request_headers

    headers = _wikimedia_request_headers()
    aua = headers.get("Api-User-Agent", "")
    ua = headers.get("User-Agent", "")
    for h, label in ((ua, "User-Agent"), (aua, "Api-User-Agent")):
        assert "Vincent OS" in h or "Vincent OS" in h, f"{label} missing project id"
        assert "github.com" in h.lower(), f"{label} missing contact URL"
        assert "issues" in h.lower(), f"{label} missing /issues contact path"
        # Round 7a: must include the per-operator handle.
        assert "operator:" in h, f"{label} missing per-operator handle: {h!r}"
