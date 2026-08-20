"""AISHub REST fallback for ship tracking.

Background
----------
When ``stream.aisstream.io`` (the WebSocket primary) is unreachable, the
ships layer goes empty. ``aishub_fallback.py`` polls ``data.aishub.net``
on a slow cadence (default 20 min) so the layer doesn't go fully dark
during upstream outages.

These tests pin:

  * Configuration gating — without ``AISHUB_USERNAME`` the fetcher is a
    no-op. The username's presence is the opt-in.
  * Connectivity gating — when the WebSocket primary is connected, the
    fallback skips so it doesn't stomp fresher live data.
  * Response parsing — successful, error, and empty AISHub payloads.
  * Record normalization — bad records (no MMSI, sentinel positions) are
    dropped without crashing.
  * Merge behavior — records land in the shared ``_vessels`` dict with
    ``source: "aishub"`` and don't overwrite very-recent live updates.
  * Poll interval clamping — env var overrides honored within [1, 360].
"""

from __future__ import annotations

import json
import os
import time

import pytest


# ---------------------------------------------------------------------------
# Configuration / gating
# ---------------------------------------------------------------------------


class TestGating:
    def test_no_username_means_disabled(self, monkeypatch):
        from services.fetchers.aishub_fallback import (
            aishub_fallback_enabled,
            fetch_aishub_vessels,
        )
        monkeypatch.delenv("AISHUB_USERNAME", raising=False)

        assert aishub_fallback_enabled() is False
        # The full fetch path should early-return 0 without making any
        # network call — verified indirectly by it not crashing on missing
        # username and not calling fetch_with_curl.
        assert fetch_aishub_vessels() == 0

    def test_username_set_means_enabled(self, monkeypatch):
        from services.fetchers.aishub_fallback import aishub_fallback_enabled
        monkeypatch.setenv("AISHUB_USERNAME", "vincent_os-test")

        assert aishub_fallback_enabled() is True

    def test_skips_when_websocket_primary_is_connected(self, monkeypatch):
        """If the AISStream WebSocket is currently delivering messages,
        the fallback should skip — fresher live data is already flowing."""
        from services.fetchers import aishub_fallback
        from services import ais_stream as ais

        monkeypatch.setenv("AISHUB_USERNAME", "vincent_os-test")

        # Force "connected" state in the ais_stream module.
        with ais._vessels_lock:
            ais._last_msg_at = time.time() - 5  # 5s ago — well inside 60s
            ais._proxy_spawn_count = 1
        # Sanity check the gate:
        assert ais.ais_proxy_status()["connected"] is True

        # And confirm the fallback skips:
        called = {"hit": False}
        monkeypatch.setattr(
            aishub_fallback,
            "fetch_with_curl",
            lambda *a, **kw: (_ for _ in ()).throw(
                AssertionError("network call must not happen when primary is connected")
            ),
        )

        assert aishub_fallback.fetch_aishub_vessels() == 0


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


class TestResponseParsing:
    def test_successful_response_parsed(self):
        from services.fetchers.aishub_fallback import _parse_aishub_response

        payload = json.dumps([
            {"ERROR": False, "USERNAME": "test", "FORMAT": "1", "RECORDS": 2},
            [
                {"MMSI": 123, "LATITUDE": 40.0, "LONGITUDE": -73.0},
                {"MMSI": 456, "LATITUDE": 51.5, "LONGITUDE": -0.1},
            ],
        ])

        rows = _parse_aishub_response(payload)

        assert len(rows) == 2
        assert rows[0]["MMSI"] == 123
        assert rows[1]["MMSI"] == 456

    def test_error_response_returns_empty(self):
        """AISHub signals errors with an ERROR=True in the header. We log
        and treat as no data."""
        from services.fetchers.aishub_fallback import _parse_aishub_response

        payload = json.dumps([
            {"ERROR": True, "ERROR_MESSAGE": "Invalid username"}
        ])

        assert _parse_aishub_response(payload) == []

    def test_empty_payload_returns_empty(self):
        """Silent rate-limit drops return 200 with empty body (we saw this
        in practice when testing with a bogus username)."""
        from services.fetchers.aishub_fallback import _parse_aishub_response
        assert _parse_aishub_response("") == []
        assert _parse_aishub_response("   ") == []

    def test_malformed_json_returns_empty(self):
        from services.fetchers.aishub_fallback import _parse_aishub_response
        assert _parse_aishub_response("not json {") == []

    def test_unexpected_shape_returns_empty(self):
        """Defensive: shape doesn't match what AISHub documents."""
        from services.fetchers.aishub_fallback import _parse_aishub_response
        assert _parse_aishub_response(json.dumps({"unexpected": "object"})) == []
        assert _parse_aishub_response(json.dumps([])) == []
        # Header-only with no records list:
        assert _parse_aishub_response(json.dumps([
            {"ERROR": False, "RECORDS": 0}
        ])) == []


# ---------------------------------------------------------------------------
# Record normalization
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_full_record_normalized(self):
        from services.fetchers.aishub_fallback import _normalize_record

        record = _normalize_record({
            "MMSI": 366998410,
            "LATITUDE": 37.8,
            "LONGITUDE": -122.4,
            "COG": 280,
            "SOG": 12.5,
            "HEADING": 285,
            "NAME": "MV TESTSHIP",
            "CALLSIGN": "WDH7100",
            "DEST": "OAKLAND",
            "TYPE": 70,
            "IMO": 9111111,
        })

        assert record is not None
        assert record["mmsi"] == 366998410
        assert record["lat"] == 37.8
        assert record["lng"] == -122.4
        assert record["sog"] == 12.5
        assert record["heading"] == 285
        assert record["name"] == "MV TESTSHIP"
        assert record["destination"] == "OAKLAND"
        assert record["ais_type_code"] == 70

    def test_speed_sentinel_sanitized(self):
        """SOG raw 102.3+ kn = "speed not available" in the AIS spec.
        Sanitize to 0 so it doesn't look like a 200-knot ship."""
        from services.fetchers.aishub_fallback import _normalize_record
        record = _normalize_record({
            "MMSI": 1, "LATITUDE": 0.5, "LONGITUDE": 0.5,
            "SOG": 102.3, "COG": 0,
        })
        assert record["sog"] == 0.0

    def test_heading_sentinel_falls_back_to_cog(self):
        """511 = heading not available in AIS spec. Use COG instead."""
        from services.fetchers.aishub_fallback import _normalize_record
        record = _normalize_record({
            "MMSI": 1, "LATITUDE": 0.5, "LONGITUDE": 0.5,
            "HEADING": 511, "COG": 280,
        })
        assert record["heading"] == 280

    def test_missing_mmsi_rejected(self):
        from services.fetchers.aishub_fallback import _normalize_record
        assert _normalize_record({"LATITUDE": 0.5, "LONGITUDE": 0.5}) is None
        assert _normalize_record({"MMSI": 0, "LATITUDE": 0.5, "LONGITUDE": 0.5}) is None

    def test_no_position_rejected(self):
        from services.fetchers.aishub_fallback import _normalize_record
        assert _normalize_record({"MMSI": 1}) is None
        assert _normalize_record({"MMSI": 1, "LATITUDE": 0.5}) is None
        assert _normalize_record({"MMSI": 1, "LONGITUDE": 0.5}) is None

    def test_position_sentinels_rejected(self):
        """AIS spec uses 91/181 as "no position available"."""
        from services.fetchers.aishub_fallback import _normalize_record
        assert _normalize_record({
            "MMSI": 1, "LATITUDE": 91.0, "LONGITUDE": 0.0
        }) is None
        assert _normalize_record({
            "MMSI": 1, "LATITUDE": 0.0, "LONGITUDE": 181.0
        }) is None

    def test_out_of_range_rejected(self):
        from services.fetchers.aishub_fallback import _normalize_record
        assert _normalize_record({
            "MMSI": 1, "LATITUDE": 95.0, "LONGITUDE": 0.0
        }) is None
        assert _normalize_record({
            "MMSI": 1, "LATITUDE": 0.0, "LONGITUDE": 200.0
        }) is None

    def test_destination_at_sign_stripped(self):
        """AIS pads short DESTINATION strings with @ characters per the
        protocol. Strip them so the UI doesn't render "OAKLAND@@@@@"."""
        from services.fetchers.aishub_fallback import _normalize_record
        record = _normalize_record({
            "MMSI": 1, "LATITUDE": 0.5, "LONGITUDE": 0.5,
            "DEST": "OAKLAND@@@",
        })
        assert record["destination"] == "OAKLAND"


# ---------------------------------------------------------------------------
# Poll interval clamping
# ---------------------------------------------------------------------------


class TestPollInterval:
    def test_default_is_twenty_minutes(self, monkeypatch):
        from services.fetchers.aishub_fallback import aishub_poll_interval_minutes
        monkeypatch.delenv("AISHUB_POLL_INTERVAL_MINUTES", raising=False)
        assert aishub_poll_interval_minutes() == 20

    def test_env_override_honored(self, monkeypatch):
        from services.fetchers.aishub_fallback import aishub_poll_interval_minutes
        monkeypatch.setenv("AISHUB_POLL_INTERVAL_MINUTES", "45")
        assert aishub_poll_interval_minutes() == 45

    def test_clamp_lower_bound(self, monkeypatch):
        """A 0 or negative env var would hammer the upstream — clamp."""
        from services.fetchers.aishub_fallback import aishub_poll_interval_minutes
        monkeypatch.setenv("AISHUB_POLL_INTERVAL_MINUTES", "0")
        assert aishub_poll_interval_minutes() == 1
        monkeypatch.setenv("AISHUB_POLL_INTERVAL_MINUTES", "-5")
        assert aishub_poll_interval_minutes() == 1

    def test_clamp_upper_bound(self, monkeypatch):
        """A 99999 env var would silence the fallback effectively forever."""
        from services.fetchers.aishub_fallback import aishub_poll_interval_minutes
        monkeypatch.setenv("AISHUB_POLL_INTERVAL_MINUTES", "99999")
        assert aishub_poll_interval_minutes() == 360

    def test_malformed_env_defaults(self, monkeypatch):
        from services.fetchers.aishub_fallback import aishub_poll_interval_minutes
        monkeypatch.setenv("AISHUB_POLL_INTERVAL_MINUTES", "twenty")
        assert aishub_poll_interval_minutes() == 20


# ---------------------------------------------------------------------------
# End-to-end fetch + merge into _vessels store
# ---------------------------------------------------------------------------


class TestFetchAndMerge:
    def _force_primary_disconnected(self):
        """Set ais_stream module state so the gate allows the fallback."""
        from services import ais_stream as ais
        with ais._vessels_lock:
            # Far in the past → connected = false; spawn_count > 0 → primary
            # has at least tried so the gate engages.
            ais._last_msg_at = time.time() - 3600
            ais._proxy_spawn_count = 5
            ais._vessels.clear()

    def test_vessels_merged_with_source_tag(self, monkeypatch):
        """Happy path: AISHub returns 2 ships, both land in ``_vessels``
        with ``source: 'aishub'``."""
        from services.fetchers import aishub_fallback
        from services import ais_stream as ais

        monkeypatch.setenv("AISHUB_USERNAME", "test-user")
        self._force_primary_disconnected()

        payload = json.dumps([
            {"ERROR": False, "USERNAME": "test-user", "FORMAT": "1", "RECORDS": 2},
            [
                {
                    "MMSI": 111111111,
                    "LATITUDE": 40.0,
                    "LONGITUDE": -73.0,
                    "SOG": 12.0,
                    "COG": 270,
                    "HEADING": 275,
                    "NAME": "SHIP A",
                    "TYPE": 70,
                },
                {
                    "MMSI": 222222222,
                    "LATITUDE": 51.5,
                    "LONGITUDE": -0.1,
                    "SOG": 8.0,
                    "COG": 90,
                    "HEADING": 92,
                    "NAME": "SHIP B",
                    "TYPE": 60,
                },
            ],
        ])

        class FakeResp:
            status_code = 200
            text = payload

        monkeypatch.setattr(
            aishub_fallback, "fetch_with_curl", lambda *a, **kw: FakeResp()
        )

        count = aishub_fallback.fetch_aishub_vessels()

        assert count == 2
        with ais._vessels_lock:
            v1 = ais._vessels.get(111111111)
            v2 = ais._vessels.get(222222222)
        assert v1 is not None
        assert v1["source"] == "aishub"
        assert v1["lat"] == 40.0
        assert v1["name"] == "SHIP A"
        assert v2 is not None
        assert v2["source"] == "aishub"
        assert v2["type"] == "passenger"  # AIS type 60 → passenger

    def test_does_not_overwrite_fresh_live_data(self, monkeypatch):
        """If the WebSocket pushed an update for an MMSI 0.5s ago and the
        AISHub poll completes in that window, we should NOT clobber the
        fresher live data."""
        from services.fetchers import aishub_fallback
        from services import ais_stream as ais

        monkeypatch.setenv("AISHUB_USERNAME", "test-user")
        self._force_primary_disconnected()

        # Pre-seed _vessels with a "very fresh" live record.
        fresh_ts = time.time()
        with ais._vessels_lock:
            ais._vessels[111111111] = {
                "mmsi": 111111111,
                "lat": 12.34,
                "lng": 56.78,
                "source": "aisstream",
                "_updated": fresh_ts,
            }

        payload = json.dumps([
            {"ERROR": False, "USERNAME": "test-user", "FORMAT": "1", "RECORDS": 1},
            [
                {
                    "MMSI": 111111111,
                    "LATITUDE": 99.0,  # bogus to make the test obvious
                    "LONGITUDE": 99.0,
                    "NAME": "STALE",
                    "SOG": 0,
                    "COG": 0,
                    "TYPE": 0,
                },
            ],
        ])

        class FakeResp:
            status_code = 200
            text = payload

        monkeypatch.setattr(
            aishub_fallback, "fetch_with_curl", lambda *a, **kw: FakeResp()
        )

        # Note: 99.0/99.0 also exceeds the 91/181 sentinel guard and
        # would be filtered. Pick a valid-but-bogus position instead.
        payload = json.dumps([
            {"ERROR": False, "USERNAME": "test-user", "FORMAT": "1", "RECORDS": 1},
            [
                {
                    "MMSI": 111111111,
                    "LATITUDE": 0.0,  # different from the live 12.34
                    "LONGITUDE": 0.0,
                    "NAME": "STALE",
                    "SOG": 0,
                    "COG": 0,
                    "TYPE": 0,
                },
            ],
        ])
        monkeypatch.setattr(
            aishub_fallback, "fetch_with_curl",
            lambda *a, **kw: type("R", (), {"status_code": 200, "text": payload})(),
        )

        aishub_fallback.fetch_aishub_vessels()

        with ais._vessels_lock:
            v = ais._vessels.get(111111111)
        # Live data wins — position should still be 12.34 / 56.78.
        assert v["lat"] == 12.34
        assert v["lng"] == 56.78
        assert v["source"] == "aisstream"

    def test_http_failure_returns_zero(self, monkeypatch):
        from services.fetchers import aishub_fallback

        monkeypatch.setenv("AISHUB_USERNAME", "test-user")
        self._force_primary_disconnected()

        class FailResp:
            status_code = 503
            text = ""

        monkeypatch.setattr(
            aishub_fallback, "fetch_with_curl", lambda *a, **kw: FailResp()
        )

        assert aishub_fallback.fetch_aishub_vessels() == 0
