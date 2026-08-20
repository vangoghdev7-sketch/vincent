"""Issues #244, #245, #246 (tg12 external audit): carrier tracker
quality + provenance + freshness.

These tests pin the post-fix contract:

- **#244**: dated editorial snapshot positions no longer live in the
  registry. They live in a one-shot seed file that is consumed once
  on first-ever startup. After that, the runtime cache reflects only
  what THIS install has actually observed.

- **#245**: headline-derived positions (centroid of a region keyword)
  are stamped ``position_confidence = "approximate"`` so the UI can
  render them with appropriate uncertainty.

- **#246**: freshness is a *labelling* decision, not an eviction
  decision. Positions older than the configurable freshness window
  flip from ``"recent"`` to ``"stale"`` but are NEVER replaced with
  the registry default — that would teleport the carrier. The user
  always sees the last position the system actually observed.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def fresh_tracker(tmp_path, monkeypatch):
    """Isolated carrier_tracker with seed/cache paths redirected to tmp.

    Yields the module so tests can call its functions; resets globals
    between tests so position caches don't leak across cases.
    """
    from services import carrier_tracker

    seed_path = tmp_path / "data" / "carrier_seed.json"
    cache_path = tmp_path / "carrier_cache.json"
    seed_path.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(carrier_tracker, "SEED_FILE", seed_path)
    monkeypatch.setattr(carrier_tracker, "CACHE_FILE", cache_path)
    monkeypatch.delenv("VINCENT_CARRIER_FRESHNESS_DAYS", raising=False)

    # Reset module-level mutable state.
    carrier_tracker._carrier_positions.clear()
    carrier_tracker._cached_gdelt_articles.clear()
    carrier_tracker._last_gdelt_fetch_at = 0.0

    yield carrier_tracker

    # Clean up so subsequent tests start fresh.
    carrier_tracker._carrier_positions.clear()
    carrier_tracker._cached_gdelt_articles.clear()


def _write_seed(path: Path, hull: str = "CVN-78", **overrides) -> None:
    payload = {
        "_meta": {
            "as_of": "2026-03-09",
            "source": "USNI News Fleet & Marine Tracker",
            "source_url": "https://news.usni.org/...",
            "note": "test",
        },
        "carriers": {
            hull: {
                "lat": 18.0,
                "lng": 39.5,
                "heading": 0,
                "desc": "Red Sea — Operation Epic Fury (USNI Mar 9)",
                "source": "USNI News Fleet & Marine Tracker (seed, as of 2026-03-09)",
                "source_url": "https://news.usni.org/category/fleet-tracker",
                "position_source_at": "2026-03-09T00:00:00Z",
                "position_confidence": "seed",
                **overrides,
            }
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# #244 — first-run seed bootstrap, never re-seeds after that
# ---------------------------------------------------------------------------


class TestSeedBootstrap:
    def test_first_ever_startup_bootstraps_from_seed(self, fresh_tracker, tmp_path):
        _write_seed(fresh_tracker.SEED_FILE)
        # No cache exists yet.
        assert not fresh_tracker.CACHE_FILE.exists()

        positions = fresh_tracker._bootstrap_cache_if_missing()

        # The seed entry made it into the cache.
        assert "CVN-78" in positions
        assert positions["CVN-78"]["lat"] == 18.0
        assert positions["CVN-78"]["position_confidence"] == "seed"
        # And the cache file is now on disk so subsequent runs skip the seed.
        assert fresh_tracker.CACHE_FILE.exists()

    def test_subsequent_startup_ignores_seed(self, fresh_tracker, tmp_path):
        # Pre-seed a different position into the cache; the seed file says Red Sea.
        cache_data = {
            "CVN-78": {
                "lat": 25.0,
                "lng": 55.0,
                "heading": 0,
                "desc": "Persian Gulf — operator-observed",
                "source": "Operator log",
                "source_url": "",
                "position_source_at": "2026-04-15T12:00:00Z",
                "position_confidence": "recent",
            }
        }
        fresh_tracker.CACHE_FILE.write_text(json.dumps(cache_data))
        _write_seed(fresh_tracker.SEED_FILE)  # seed is present but should NOT be used

        positions = fresh_tracker._bootstrap_cache_if_missing()

        assert positions["CVN-78"]["lat"] == 25.0
        assert positions["CVN-78"]["desc"] == "Persian Gulf — operator-observed"

    def test_no_seed_no_cache_falls_back_to_homeport(self, fresh_tracker):
        # Neither seed nor cache. Must fall back to homeport defaults
        # (carrier never disappears).
        assert not fresh_tracker.SEED_FILE.exists()
        assert not fresh_tracker.CACHE_FILE.exists()

        positions = fresh_tracker._bootstrap_cache_if_missing()

        # Every registered carrier has SOMETHING.
        assert set(positions.keys()) == set(fresh_tracker.CARRIER_REGISTRY.keys())
        # All entries are labelled as homeport defaults.
        for hull, entry in positions.items():
            assert entry["position_confidence"] == "homeport_default"
            registry = fresh_tracker.CARRIER_REGISTRY[hull]
            assert entry["lat"] == registry["homeport_lat"]
            assert entry["lng"] == registry["homeport_lng"]


# ---------------------------------------------------------------------------
# #244 — no editorial fallbacks live in the registry
# ---------------------------------------------------------------------------


class TestRegistryShape:
    def test_registry_has_no_dated_fallback_fields(self, fresh_tracker):
        """The Mar 9 editorial coordinates are gone from the registry.
        They live only in the seed file."""
        forbidden = {"fallback_lat", "fallback_lng", "fallback_heading", "fallback_desc"}
        for hull, entry in fresh_tracker.CARRIER_REGISTRY.items():
            offending = forbidden & set(entry.keys())
            assert not offending, f"{hull} still has dated registry fields: {offending}"

    def test_registry_keeps_homeport_for_every_hull(self, fresh_tracker):
        for hull, entry in fresh_tracker.CARRIER_REGISTRY.items():
            assert "homeport_lat" in entry, f"{hull} missing homeport_lat"
            assert "homeport_lng" in entry, f"{hull} missing homeport_lng"
            assert "name" in entry
            assert "wiki" in entry


# ---------------------------------------------------------------------------
# #246 — freshness labelling, NOT eviction
# ---------------------------------------------------------------------------


class TestFreshnessLabelling:
    def test_recent_observation_labels_recent(self, fresh_tracker):
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        entry = {
            "lat": 25.0,
            "lng": 55.0,
            "position_source_at": (now - timedelta(days=3)).isoformat(),
        }
        assert fresh_tracker._compute_position_confidence(entry, now=now) == "recent"

    def test_aged_observation_flips_to_stale(self, fresh_tracker):
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        entry = {
            "lat": 25.0,
            "lng": 55.0,
            "position_source_at": (now - timedelta(days=30)).isoformat(),
        }
        assert fresh_tracker._compute_position_confidence(entry, now=now) == "stale"

    def test_seed_label_is_preserved_explicitly(self, fresh_tracker):
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        entry = {
            "lat": 18.0,
            "lng": 39.5,
            "position_source_at": "2026-03-09T00:00:00Z",
            "position_confidence": "seed",
        }
        # Even though the source is months old, the explicit "seed" label wins
        # so the UI can render the seed-specific badge instead of generic "stale".
        assert fresh_tracker._compute_position_confidence(entry, now=now) == "seed"

    def test_homeport_default_label_is_preserved(self, fresh_tracker):
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        entry = {
            "lat": 36.95,
            "lng": -76.32,
            "position_source_at": now.isoformat(),
            "position_confidence": "homeport_default",
        }
        assert fresh_tracker._compute_position_confidence(entry, now=now) == "homeport_default"

    def test_freshness_window_is_env_configurable(self, fresh_tracker, monkeypatch):
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        entry = {
            "lat": 25.0,
            "lng": 55.0,
            "position_source_at": (now - timedelta(days=20)).isoformat(),
        }
        # Default window = 14 days → 20-day-old entry is stale.
        assert fresh_tracker._compute_position_confidence(entry, now=now) == "stale"
        # Stretch to 30 days → same entry is now "recent".
        monkeypatch.setenv("VINCENT_CARRIER_FRESHNESS_DAYS", "30")
        assert fresh_tracker._compute_position_confidence(entry, now=now) == "recent"

    def test_aged_cache_entry_keeps_its_position_never_reverts(self, fresh_tracker):
        """The core regression test for the user's intent: a year-old
        cache entry must NOT be replaced with the seed or homeport.
        The PHYSICAL position the user sees is the last one observed;
        only the freshness LABEL changes."""
        a_year_ago = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        cache_data = {
            "CVN-78": {
                "lat": 25.0,
                "lng": 55.0,
                "heading": 0,
                "desc": "Persian Gulf",
                "source": "GDELT News API",
                "source_url": "https://news.example/...",
                "position_source_at": a_year_ago,
                "position_confidence": "recent",  # was recent when written
            }
        }
        fresh_tracker.CACHE_FILE.write_text(json.dumps(cache_data))

        positions = fresh_tracker._bootstrap_cache_if_missing()
        enriched = fresh_tracker._enrich_for_rendering("CVN-78", positions["CVN-78"])

        # The position is preserved exactly.
        assert enriched["lat"] == 25.0
        assert enriched["lng"] == 55.0
        # But the live label has flipped to stale.
        assert enriched["position_confidence"] == "stale"
        assert enriched["is_fallback"] is True


# ---------------------------------------------------------------------------
# #245 — approximate confidence for region-centroid positions
# ---------------------------------------------------------------------------


class TestApproximateConfidenceForNewsDerivedPositions:
    def test_news_parsing_stamps_approximate_confidence(self, fresh_tracker):
        articles = [
            {
                "title": "USS Ford carrier deployed in Mediterranean for joint exercise",
                "url": "https://news.example/ford-mediterranean",
                "seendate": "20260415120000",
            }
        ]
        updates = fresh_tracker._parse_carrier_positions_from_news(articles)
        assert "CVN-78" in updates
        entry = updates["CVN-78"]
        assert entry["position_confidence"] == "approximate"
        # And the source_at is the article's seen date, not now().
        assert entry["position_source_at"].startswith("2026-04-15")

    def test_gdelt_seendate_parser_handles_well_formed_input(self, fresh_tracker):
        iso = fresh_tracker._gdelt_seendate_to_iso("20260415120000")
        assert iso is not None
        assert iso.startswith("2026-04-15T12:00:00")

    def test_gdelt_seendate_parser_returns_none_on_garbage(self, fresh_tracker):
        assert fresh_tracker._gdelt_seendate_to_iso("") is None
        assert fresh_tracker._gdelt_seendate_to_iso("not-a-date") is None
        assert fresh_tracker._gdelt_seendate_to_iso("2026") is None


# ---------------------------------------------------------------------------
# Full enrichment → public API shape
# ---------------------------------------------------------------------------


class TestEnrichForRendering:
    def test_seed_entry_produces_expected_public_fields(self, fresh_tracker):
        seed_entry = {
            "lat": 18.0,
            "lng": 39.5,
            "heading": 0,
            "desc": "Red Sea (USNI Mar 9)",
            "source": "USNI News Fleet & Marine Tracker (seed, as of 2026-03-09)",
            "source_url": "https://news.usni.org/category/fleet-tracker",
            "position_source_at": "2026-03-09T00:00:00Z",
            "position_confidence": "seed",
        }
        enriched = fresh_tracker._enrich_for_rendering("CVN-78", seed_entry)
        # Existing UI fields preserved.
        assert enriched["lat"] == 18.0
        assert enriched["lng"] == 39.5
        assert enriched["source"].startswith("USNI")
        assert enriched["last_osint_update"] == "2026-03-09T00:00:00Z"
        # New audit-required fields.
        assert enriched["position_confidence"] == "seed"
        assert enriched["position_source_at"] == "2026-03-09T00:00:00Z"
        assert enriched["is_fallback"] is True

    def test_recent_observation_is_not_fallback(self, fresh_tracker):
        now = datetime.now(timezone.utc)
        recent_entry = {
            "lat": 25.0,
            "lng": 55.0,
            "heading": 0,
            "desc": "Persian Gulf",
            "source": "GDELT News API",
            "source_url": "https://news.example/...",
            "position_source_at": (now - timedelta(days=2)).isoformat(),
            "position_confidence": "approximate",
        }
        enriched = fresh_tracker._enrich_for_rendering("CVN-78", recent_entry, now=now)
        assert enriched["position_confidence"] == "approximate"
        # Approximate (from a recent headline) is honest precision, but the UI
        # treats it as live data — is_fallback only flips True for explicit
        # fallback categories (seed / stale / homeport_default).
        assert enriched["is_fallback"] is False


# ---------------------------------------------------------------------------
# Regression: existing frontend fields are preserved
# ---------------------------------------------------------------------------


class TestPublicResponseShapeBackwardCompat:
    """The frontend ShipPopup expects `estimated`, `source`, `source_url`,
    `last_osint_update`. The new fields are additive and existing fields
    keep their meaning so the UI does not need updating to keep working."""

    def test_get_carrier_positions_preserves_existing_keys(self, fresh_tracker):
        _write_seed(fresh_tracker.SEED_FILE)
        fresh_tracker._bootstrap_cache_if_missing()
        with fresh_tracker._positions_lock:
            fresh_tracker._carrier_positions.update(
                {
                    "CVN-78": {
                        "lat": 18.0,
                        "lng": 39.5,
                        "heading": 0,
                        "desc": "Red Sea (seed)",
                        "source": "Seed",
                        "source_url": "",
                        "position_source_at": "2026-03-09T00:00:00Z",
                        "position_confidence": "seed",
                    }
                }
            )

        out = fresh_tracker.get_carrier_positions()
        assert len(out) == 1
        c = out[0]
        # Old fields the frontend uses.
        for key in (
            "name",
            "type",
            "lat",
            "lng",
            "country",
            "desc",
            "wiki",
            "estimated",
            "source",
            "source_url",
            "last_osint_update",
        ):
            assert key in c, f"missing legacy field {key!r}"
        # New fields.
        for key in ("position_confidence", "position_source_at", "is_fallback"):
            assert key in c, f"missing audit-required field {key!r}"
        assert c["type"] == "carrier"
        assert c["estimated"] is True
