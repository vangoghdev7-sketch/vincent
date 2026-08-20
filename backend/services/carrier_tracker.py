"""
Carrier Strike Group OSINT Tracker
===================================
Maintains estimated positions for US Navy Carrier Strike Groups with
honest provenance and freshness signals.

Issues #244 / #245 / #246 (tg12 external audit):

The previous implementation baked a snapshot of USNI News Fleet &
Marine Tracker positions (March 9, 2026) into the registry as
``fallback_lat``/``fallback_lng`` and stamped ``updated = now()``
every time the dossier was rendered. That presented stale editorial
data as live state. It also persisted GDELT-derived positions to the
on-disk cache with no freshness signal, so a single news mention from
months ago could keep overriding the (already-stale) registry default
indefinitely.

Architecture after this PR:

::

    backend/data/carrier_seed.json   read-only, shipped with image,
                                     used ONCE on first-ever startup
                                     to bootstrap carrier_cache.json.

    backend/data/carrier_cache.json  mutable, lives in the runtime data
                                     volume, written by every GDELT
                                     refresh + any future source.

Startup flow:

1.  ``carrier_cache.json`` exists?  → load it.
2.  Otherwise, copy ``carrier_seed.json`` → ``carrier_cache.json``,
    then load it. (This happens once, ever, per install.)
3.  Background: GDELT fetch runs. Any carrier mentioned in fresh news
    gets its entry replaced with the news-derived position.
    ``position_source_at`` is set to the news article timestamp.

Freshness is a *labelling* decision, not an eviction decision:

- ``position_source_at`` within the configurable freshness window
  (default 14 days) → ``position_confidence = "recent"``.
- Older than that              → ``position_confidence = "stale"``.
- Bootstrapped from the seed file (never updated) → ``"seed"``.
- No cache entry at all (e.g. a carrier added to the registry after
  first install) → carrier renders at its homeport with
  ``"homeport_default"``.

Carriers are never hidden, never teleported, never disappeared. The
position the user sees is always the last position the system actually
observed, with an honest "as-of" timestamp the UI can render however
it likes. A year from now, the runtime cache reflects whatever this
install has observed via GDELT — not the seed snapshot.
"""

import os
import json
import time
import logging
import threading
import random
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from services.network_utils import fetch_with_curl

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------
# Carrier registry: hull number → identity only.
#
# Issue #244 (tg12): the previous registry carried hard-coded
# ``fallback_lat``/``fallback_lng`` that were dated editorial
# snapshots from a 2026-03-09 article. Those fields are DELETED. The
# registry is now identity + homeport only; positions are sourced
# exclusively from carrier_cache.json (and via that, from the
# bootstrap seed or live OSINT).
# -----------------------------------------------------------------
CARRIER_REGISTRY: Dict[str, dict] = {
    # --- Bremerton, WA (Naval Base Kitsap) ---
    "CVN-68": {
        "name": "USS Nimitz (CVN-68)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Nimitz",
        "homeport": "Bremerton, WA",
        "homeport_lat": 47.5535,
        "homeport_lng": -122.6400,
    },
    "CVN-76": {
        "name": "USS Ronald Reagan (CVN-76)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Ronald_Reagan",
        "homeport": "Bremerton, WA",
        "homeport_lat": 47.5580,
        "homeport_lng": -122.6360,
    },
    # --- Norfolk, VA (Naval Station Norfolk) ---
    "CVN-69": {
        "name": "USS Dwight D. Eisenhower (CVN-69)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Dwight_D._Eisenhower",
        "homeport": "Norfolk, VA",
        "homeport_lat": 36.9465,
        "homeport_lng": -76.3265,
    },
    "CVN-78": {
        "name": "USS Gerald R. Ford (CVN-78)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Gerald_R._Ford",
        "homeport": "Norfolk, VA",
        "homeport_lat": 36.9505,
        "homeport_lng": -76.3250,
    },
    "CVN-74": {
        "name": "USS John C. Stennis (CVN-74)",
        "wiki": "https://en.wikipedia.org/wiki/USS_John_C._Stennis",
        "homeport": "Norfolk, VA",
        "homeport_lat": 36.9540,
        "homeport_lng": -76.3235,
    },
    "CVN-75": {
        "name": "USS Harry S. Truman (CVN-75)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Harry_S._Truman",
        "homeport": "Norfolk, VA",
        "homeport_lat": 36.9580,
        "homeport_lng": -76.3220,
    },
    "CVN-77": {
        "name": "USS George H.W. Bush (CVN-77)",
        "wiki": "https://en.wikipedia.org/wiki/USS_George_H.W._Bush",
        "homeport": "Norfolk, VA",
        "homeport_lat": 36.9620,
        "homeport_lng": -76.3210,
    },
    # --- San Diego, CA (Naval Base San Diego) ---
    "CVN-70": {
        "name": "USS Carl Vinson (CVN-70)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Carl_Vinson",
        "homeport": "San Diego, CA",
        "homeport_lat": 32.6840,
        "homeport_lng": -117.1290,
    },
    "CVN-71": {
        "name": "USS Theodore Roosevelt (CVN-71)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Theodore_Roosevelt_(CVN-71)",
        "homeport": "San Diego, CA",
        "homeport_lat": 32.6885,
        "homeport_lng": -117.1280,
    },
    "CVN-72": {
        "name": "USS Abraham Lincoln (CVN-72)",
        "wiki": "https://en.wikipedia.org/wiki/USS_Abraham_Lincoln_(CVN-72)",
        "homeport": "San Diego, CA",
        "homeport_lat": 32.6925,
        "homeport_lng": -117.1275,
    },
    # --- Yokosuka, Japan (CFAY) ---
    "CVN-73": {
        "name": "USS George Washington (CVN-73)",
        "wiki": "https://en.wikipedia.org/wiki/USS_George_Washington_(CVN-73)",
        "homeport": "Yokosuka, Japan",
        "homeport_lat": 35.2830,
        "homeport_lng": 139.6700,
    },
}

# -----------------------------------------------------------------
# Region → approximate center coordinates.
#
# Issue #245 (tg12): converting a region name straight into precise
# map coordinates is false precision. We still use this table to
# infer a coarse position from a headline mention, but the resulting
# carrier object is now stamped ``position_confidence = "approximate"``
# so the UI can render an uncertainty radius / dimmed icon. The
# centroid is a best-effort midpoint of the named body of water.
# -----------------------------------------------------------------
REGION_COORDS: Dict[str, tuple] = {
    # Oceans & Seas
    "eastern mediterranean": (34.0, 25.0),
    "mediterranean": (36.0, 15.0),
    "western mediterranean": (37.0, 2.0),
    "red sea": (18.0, 39.5),
    "arabian sea": (16.0, 64.0),
    "persian gulf": (26.5, 51.5),
    "gulf of oman": (24.5, 58.5),
    "north arabian sea": (20.0, 64.0),
    "south china sea": (15.0, 115.0),
    "east china sea": (28.0, 125.0),
    "philippine sea": (20.0, 130.0),
    "sea of japan": (40.0, 135.0),
    "taiwan strait": (24.0, 119.5),
    "western pacific": (20.0, 140.0),
    "pacific": (20.0, -150.0),
    "indian ocean": (-5.0, 70.0),
    "north atlantic": (40.0, -40.0),
    "atlantic": (30.0, -50.0),
    "gulf of aden": (12.5, 45.0),
    "horn of africa": (10.0, 50.0),
    "strait of hormuz": (26.5, 56.3),
    "bab el-mandeb": (12.6, 43.3),
    "suez canal": (30.5, 32.3),
    "baltic sea": (57.0, 18.0),
    "north sea": (56.0, 3.0),
    "black sea": (43.0, 34.0),
    "south atlantic": (-20.0, -20.0),
    "coral sea": (-18.0, 155.0),
    "gulf of mexico": (25.0, -90.0),
    "caribbean": (15.0, -75.0),
    # Specific bases / ports
    "norfolk": (36.95, -76.33),
    "san diego": (32.68, -117.15),
    "yokosuka": (35.28, 139.67),
    "pearl harbor": (21.35, -157.95),
    "guam": (13.45, 144.79),
    "bahrain": (26.23, 50.55),
    "rota": (36.62, -6.35),
    "naples": (40.85, 14.27),
    "bremerton": (47.56, -122.63),
    "puget sound": (47.56, -122.63),
    "newport news": (36.98, -76.43),
    # Areas of operation
    "centcom": (25.0, 55.0),
    "indopacom": (20.0, 130.0),
    "eucom": (48.0, 15.0),
    "southcom": (10.0, -80.0),
    "5th fleet": (25.0, 55.0),
    "6th fleet": (36.0, 15.0),
    "7th fleet": (25.0, 130.0),
    "3rd fleet": (30.0, -130.0),
    "2nd fleet": (35.0, -60.0),
}

# -----------------------------------------------------------------
# Files
# -----------------------------------------------------------------
#
# The seed lives in the read-only image data dir (it ships with each
# release). The cache lives in the same data dir but is written at
# runtime; under Docker compose this dir is volume-mounted so the
# cache persists across container restarts, which is the whole point
# of the seed-then-observe model — the user's runtime observations
# survive image upgrades.
SEED_FILE = Path(__file__).parent.parent / "data" / "carrier_seed.json"
CACHE_FILE = Path(__file__).parent.parent / "data" / "carrier_cache.json"

# -----------------------------------------------------------------
# Freshness window for position_confidence labeling. Issue #246 (tg12):
# previously persisted cache entries had no freshness signal at all.
# After this change, the position itself is preserved (we never lose
# what was last observed) but the confidence label flips from
# "recent" to "stale" once the underlying source is older than this
# window. Operator-overridable via env var.
# -----------------------------------------------------------------
_DEFAULT_FRESHNESS_WINDOW_DAYS = 14


def _freshness_window_days() -> int:
    raw = str(os.environ.get("VINCENT_CARRIER_FRESHNESS_DAYS", os.environ.get("SHADOWBROKER_CARRIER_FRESHNESS_DAYS", "") or "").strip()
    if not raw:
        return _DEFAULT_FRESHNESS_WINDOW_DAYS
    try:
        n = int(raw)
        return n if n > 0 else _DEFAULT_FRESHNESS_WINDOW_DAYS
    except (TypeError, ValueError):
        return _DEFAULT_FRESHNESS_WINDOW_DAYS


_carrier_positions: Dict[str, dict] = {}
_positions_lock = threading.Lock()
_last_update: Optional[datetime] = None
_last_gdelt_fetch_at = 0.0
_cached_gdelt_articles: List[dict] = []
_GDELT_FETCH_INTERVAL_SECONDS = 1800
_GDELT_REQUEST_DELAY_SECONDS = 1.25
_GDELT_REQUEST_JITTER_SECONDS = 0.35


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        # Python's fromisoformat accepts +00:00 but not 'Z' until 3.11.
        normalized = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _compute_position_confidence(entry: dict, *, now: Optional[datetime] = None) -> str:
    """Return the public confidence label for a carrier cache entry.

    Order of precedence:
      - explicit "homeport_default" / "seed" labels are preserved.
      - dated entries (with position_source_at) are "recent" if within
        the configured freshness window, else "stale".
      - missing position_source_at falls through to "stale".
    """
    raw_label = str(entry.get("position_confidence", "") or "").strip()
    # Explicit "kind of provenance" labels are preserved as-is. They
    # describe HOW we got the position, not WHEN — a fresh headline-to-
    # centroid match (#245) is still imprecise no matter how recently
    # it was observed, and the seed (#244) is always the seed.
    if raw_label in {"seed", "homeport_default", "approximate"}:
        # Approximate entries can still age into "stale_approximate" if
        # they fall out of the freshness window — that distinction lets
        # the UI render a different badge for old-and-imprecise vs
        # recent-and-imprecise. seed/homeport_default never age (they
        # were never timestamped against real observations).
        if raw_label == "approximate":
            source_at = _parse_iso(str(entry.get("position_source_at", "") or ""))
            if source_at is not None:
                reference = now or datetime.now(timezone.utc)
                if reference - source_at > timedelta(days=_freshness_window_days()):
                    return "stale_approximate"
        return raw_label

    source_at = _parse_iso(str(entry.get("position_source_at", "") or ""))
    if not source_at:
        return "stale"

    reference = now or datetime.now(timezone.utc)
    window = timedelta(days=_freshness_window_days())
    if reference - source_at <= window:
        return "recent"
    return "stale"


def _load_seed() -> Dict[str, dict]:
    """Load the read-only seed file shipped with the image.

    Returns a hull→entry dict (no _meta wrapper). Missing or malformed
    seed files yield an empty dict — the caller falls back to homeport
    defaults.
    """
    try:
        if not SEED_FILE.exists():
            logger.info("Carrier seed file not present at %s; first-run will fall back to homeport defaults", SEED_FILE)
            return {}
        raw = json.loads(SEED_FILE.read_text(encoding="utf-8"))
        carriers = raw.get("carriers", {}) if isinstance(raw, dict) else {}
        if not isinstance(carriers, dict):
            return {}
        logger.info("Carrier seed loaded: %d entries from %s", len(carriers), SEED_FILE)
        return carriers
    except (IOError, OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning("Failed to load carrier seed file %s: %s", SEED_FILE, e)
        return {}


def _load_cache() -> Dict[str, dict]:
    """Load the mutable cache (last-known positions persisted between restarts)."""
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                logger.info("Carrier cache loaded: %d carriers from %s", len(data), CACHE_FILE)
                return data
    except (IOError, OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning("Failed to load carrier cache: %s", e)
    return {}


def _save_cache(positions: Dict[str, dict]) -> None:
    """Persist the mutable cache. Atomic write (temp + rename) so a crash
    mid-write can't leave the file truncated."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_FILE.with_suffix(CACHE_FILE.suffix + ".tmp")
        tmp.write_text(json.dumps(positions, indent=2), encoding="utf-8")
        # On Windows os.replace is atomic and overwrites existing files.
        os.replace(tmp, CACHE_FILE)
        logger.info("Carrier cache saved: %d carriers", len(positions))
    except (IOError, OSError) as e:
        logger.warning("Failed to save carrier cache: %s", e)


def _homeport_entry_for(hull: str) -> Optional[dict]:
    """Return a homeport-default cache entry for a hull, or None if the
    hull is not in the registry."""
    info = CARRIER_REGISTRY.get(hull)
    if not info:
        return None
    return {
        "lat": info["homeport_lat"],
        "lng": info["homeport_lng"],
        "heading": 0,
        "desc": f"{info['homeport']} (no observations yet)",
        "source": f"Homeport default ({info['homeport']})",
        "source_url": info.get("wiki", ""),
        "position_source_at": _now_iso(),
        "position_confidence": "homeport_default",
    }


def _bootstrap_cache_if_missing() -> Dict[str, dict]:
    """One-shot: if no cache exists, materialize one from the seed file.

    Returns the cache contents (hull→entry). On first-ever startup,
    this writes ``carrier_cache.json`` so subsequent restarts skip the
    seed entirely. Operator-deleted caches re-bootstrap the same way —
    operators can use that to "reset" carrier positions, but it's an
    explicit operator action.
    """
    if CACHE_FILE.exists():
        return _load_cache()

    seed = _load_seed()
    if not seed:
        # No seed file either. Build a homeport-default cache so the
        # first save_cache call still produces something honest.
        homeports: Dict[str, dict] = {}
        for hull in CARRIER_REGISTRY:
            entry = _homeport_entry_for(hull)
            if entry is not None:
                homeports[hull] = entry
        if homeports:
            _save_cache(homeports)
        return homeports

    # Persist the seed as the first cache so subsequent runs skip this branch.
    _save_cache(seed)
    logger.info("Carrier cache bootstrapped from seed (first-ever startup)")
    return dict(seed)


def _match_region(text: str) -> Optional[tuple]:
    """Match a text string against known regions, return (lat, lng) or None."""
    text_lower = text.lower()
    for region, coords in sorted(REGION_COORDS.items(), key=lambda x: -len(x[0])):
        if region in text_lower:
            return coords
    return None


def _match_carrier(text: str) -> Optional[str]:
    """Match a text string against known carrier names/hull numbers."""
    text_lower = text.lower()
    for hull, info in CARRIER_REGISTRY.items():
        hull_check = hull.lower().replace("-", "")
        name_parts = info["name"].lower()
        if hull.lower() in text_lower or hull_check in text_lower.replace("-", ""):
            return hull
        ship_name = name_parts.split("(")[0].strip()
        last_name = ship_name.split()[-1] if ship_name else ""
        if last_name and len(last_name) > 3 and last_name in text_lower:
            return hull
    return None


def _fetch_gdelt_carrier_news() -> List[dict]:
    """Search GDELT for recent carrier movement news."""
    global _last_gdelt_fetch_at, _cached_gdelt_articles

    now = time.time()
    if _cached_gdelt_articles and (now - _last_gdelt_fetch_at) < _GDELT_FETCH_INTERVAL_SECONDS:
        logger.info("Carrier OSINT: using cached GDELT article set to avoid startup bursts")
        return list(_cached_gdelt_articles)

    results = []
    search_terms = [
        "aircraft+carrier+deployed",
        "carrier+strike+group+navy",
        "USS+Nimitz+carrier",
        "USS+Ford+carrier",
        "USS+Eisenhower+carrier",
        "USS+Vinson+carrier",
        "USS+Roosevelt+carrier+navy",
        "USS+Lincoln+carrier",
        "USS+Truman+carrier",
        "USS+Reagan+carrier",
        "USS+Washington+carrier+navy",
        "USS+Bush+carrier",
        "USS+Stennis+carrier",
    ]

    for idx, term in enumerate(search_terms):
        try:
            url = f"https://api.gdeltproject.org/api/v2/doc/doc?query={term}&mode=artlist&maxrecords=5&format=json&timespan=14d"
            raw = fetch_with_curl(url, timeout=8)
            if getattr(raw, "status_code", 500) == 429:
                logger.warning(
                    "GDELT returned 429 for '%s'; preserving cached carrier OSINT results",
                    term,
                )
                continue
            if not raw or not hasattr(raw, "text"):
                continue
            data = raw.json()
            articles = data.get("articles", [])
            for art in articles:
                title = art.get("title", "")
                article_url = art.get("url", "")
                article_at = art.get("seendate") or art.get("date") or ""
                results.append({"title": title, "url": article_url, "seendate": article_at})
        except (ConnectionError, TimeoutError, ValueError, KeyError, OSError) as e:
            logger.debug(f"GDELT search failed for '{term}': {e}")
            continue
        if idx < len(search_terms) - 1:
            time.sleep(
                _GDELT_REQUEST_DELAY_SECONDS
                + random.uniform(0.0, _GDELT_REQUEST_JITTER_SECONDS)
            )

    _cached_gdelt_articles = list(results)
    _last_gdelt_fetch_at = time.time()
    logger.info(f"Carrier OSINT: found {len(results)} GDELT articles")
    return results


def _gdelt_seendate_to_iso(seendate: str) -> Optional[str]:
    """GDELT returns YYYYMMDDhhmmss (UTC). Convert to ISO8601 for
    position_source_at. Returns None if the input is unparseable."""
    raw = (seendate or "").strip()
    if len(raw) < 8 or not raw.isdigit():
        return None
    try:
        dt = datetime.strptime(raw[:14] if len(raw) >= 14 else raw[:8] + "000000", "%Y%m%d%H%M%S")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def _parse_carrier_positions_from_news(articles: List[dict]) -> Dict[str, dict]:
    """Parse carrier positions from news article titles.

    Issue #245 (tg12): the position is a region centroid, which is
    coarse — we now stamp ``position_confidence = "approximate"`` so
    the UI can render that uncertainty. Issue #244: the
    ``position_source_at`` field is the news article's actual seen
    date, NOT now(), so the freshness check correctly flips entries
    to "stale" once they age past the configured window.
    """
    updates: Dict[str, dict] = {}

    for article in articles:
        title = article.get("title", "")
        hull = _match_carrier(title)
        if not hull:
            continue
        coords = _match_region(title)
        if not coords:
            continue

        # First match wins (most recent article, GDELT returns newest first
        # per term).
        if hull not in updates:
            iso_at = _gdelt_seendate_to_iso(str(article.get("seendate", ""))) or _now_iso()
            updates[hull] = {
                "lat": coords[0],
                "lng": coords[1],
                "heading": 0,
                "desc": title[:100],
                "source": "GDELT News API (headline region match — approximate)",
                "source_url": article.get("url", "https://api.gdeltproject.org"),
                "position_source_at": iso_at,
                # Headline-to-centroid match is explicitly approximate.
                "position_confidence": "approximate",
            }
            logger.info(
                "Carrier update: %s → %s (from: %s)",
                CARRIER_REGISTRY[hull]["name"],
                coords,
                title[:80],
            )

    return updates


def _enrich_for_rendering(hull: str, entry: dict, *, now: Optional[datetime] = None) -> dict:
    """Add live computed fields (confidence label, last_osint_update)
    on top of the persisted cache entry. The persisted entry is left
    untouched; this function builds the public-facing object.
    """
    info = CARRIER_REGISTRY.get(hull, {})
    confidence = _compute_position_confidence(entry, now=now)
    return {
        "name": entry.get("name", info.get("name", hull)),
        "lat": entry["lat"],
        "lng": entry["lng"],
        "heading": entry.get("heading", 0),
        "desc": entry.get("desc", ""),
        "wiki": entry.get("wiki", info.get("wiki", "")),
        "source": entry.get("source", "OSINT estimated position"),
        "source_url": entry.get("source_url", ""),
        "position_source_at": entry.get("position_source_at", ""),
        "position_confidence": confidence,
        # Existing field preserved for backward compatibility with the
        # current frontend ShipPopup; now reflects the SOURCE's observed
        # time (not now()), so "last reported X days ago" is honest.
        "last_osint_update": entry.get("position_source_at", ""),
        # Convenience boolean for the UI: true when the position is
        # NOT live OSINT (used to render dimmed icons / badges).
        "is_fallback": confidence in {"seed", "stale", "stale_approximate", "homeport_default"},
    }


def update_carrier_positions() -> None:
    """Refresh carrier positions.

    Phase 1 (instant): publish whatever's in carrier_cache.json (or
    bootstrap from seed on first-ever run), so the map has carriers
    immediately.

    Phase 2 (slow): query GDELT and replace position entries for any
    carrier mentioned in fresh news. Persist back to cache.
    """
    global _last_update

    # --- Phase 1: instant cache (bootstrap from seed on first-ever run) ---
    positions = _bootstrap_cache_if_missing()

    # Ensure every registered hull has SOMETHING in the cache. A hull
    # the seed didn't cover (e.g. added after install) renders at its
    # homeport with "homeport_default" confidence.
    for hull in CARRIER_REGISTRY:
        if hull not in positions:
            entry = _homeport_entry_for(hull)
            if entry is not None:
                positions[hull] = entry

    with _positions_lock:
        if not _carrier_positions:
            _carrier_positions.update(positions)
            _last_update = datetime.now(timezone.utc)
    logger.info(
        "Carrier tracker: %d carriers loaded from cache (USNI + GDELT enrichment starting...)",
        len(positions),
    )

    # --- Phase 2: USNI Fleet & Marine Tracker (PRIMARY source) ---
    #
    # USNI publishes a weekly editorial tracker with each carrier's
    # actual operating area, parsed from explicit prose like
    #   "The Gerald R. Ford Carrier Strike Group is operating in the Red Sea"
    # These positions are tagged ``position_confidence: "recent"`` because
    # they reflect actual reporting, not headline-keyword centroids.
    # USNI updates are preferred over GDELT — they're authoritative on
    # US Navy positions where GDELT is just article-title text mining.
    try:
        from services.fetchers.usni_fleet_tracker import (
            fetch_latest_fleet_tracker_positions,
        )
        usni_positions = fetch_latest_fleet_tracker_positions()
        for hull, pos in usni_positions.items():
            positions[hull] = pos
            logger.info(
                "Carrier USNI update: %s → %s",
                CARRIER_REGISTRY[hull]["name"],
                pos.get("desc", ""),
            )
    except Exception as e:
        logger.warning("USNI fleet-tracker fetch failed: %s", e)

    # --- Phase 3: GDELT enrichment (SECONDARY — fills gaps) ---
    #
    # Used only to backfill carriers USNI didn't mention this week. The
    # position is stamped ``approximate`` so the UI knows it's a
    # headline-centroid match (Issue #245).
    try:
        articles = _fetch_gdelt_carrier_news()
        news_positions = _parse_carrier_positions_from_news(articles)
        for hull, pos in news_positions.items():
            # Only overwrite if the existing entry is NOT a recent USNI
            # observation. A "recent" USNI position is higher-confidence
            # than a GDELT headline-centroid match — don't let GDELT
            # demote a real position to an approximate one.
            existing = positions.get(hull, {})
            existing_conf = _compute_position_confidence(existing)
            if existing_conf == "recent":
                continue
            positions[hull] = pos
            logger.info(
                "Carrier OSINT: updated %s from GDELT news",
                CARRIER_REGISTRY[hull]["name"],
            )
    except (ValueError, KeyError, json.JSONDecodeError, OSError) as e:
        logger.warning("GDELT carrier fetch failed: %s", e)

    with _positions_lock:
        _carrier_positions.clear()
        _carrier_positions.update(positions)
        _last_update = datetime.now(timezone.utc)

    _save_cache(positions)

    confidences: Dict[str, int] = {}
    for entry in positions.values():
        label = _compute_position_confidence(entry)
        confidences[label] = confidences.get(label, 0) + 1
    logger.info("Carrier tracker: %d carriers updated. Confidence: %s", len(positions), confidences)


def _deconflict_positions(result: List[dict]) -> List[dict]:
    """Offset carriers that share identical coordinates so they don't stack."""
    from collections import defaultdict

    groups: dict[str, list[int]] = defaultdict(list)
    for i, c in enumerate(result):
        key = f"{round(c['lat'], 2)},{round(c['lng'], 2)}"
        groups[key].append(i)

    for indices in groups.values():
        if len(indices) < 2:
            continue
        n = len(indices)
        sample = result[indices[0]]
        at_port = any(
            abs(sample["lat"] - info.get("homeport_lat", 0)) < 0.05
            and abs(sample["lng"] - info.get("homeport_lng", 0)) < 0.05
            for info in CARRIER_REGISTRY.values()
        )

        if at_port:
            for idx in indices:
                carrier = result[idx]
                hull = None
                for h, info in CARRIER_REGISTRY.items():
                    if info["name"] == carrier["name"]:
                        hull = h
                        break
                if hull:
                    info = CARRIER_REGISTRY[hull]
                    carrier["lat"] = info["homeport_lat"]
                    carrier["lng"] = info["homeport_lng"]
        else:
            spacing = 0.08
            start_offset = -(n - 1) * spacing / 2
            for j, idx in enumerate(indices):
                result[idx]["lng"] += start_offset + j * spacing

    return result


def get_carrier_positions() -> List[dict]:
    """Return current carrier positions for the data pipeline.

    Each entry has the full provenance + freshness fields; the UI can
    decide how to render them. Carriers are never hidden — only
    labeled.
    """
    now = datetime.now(timezone.utc)
    with _positions_lock:
        result: List[dict] = []
        for hull, entry in _carrier_positions.items():
            enriched = _enrich_for_rendering(hull, entry, now=now)
            result.append(
                {
                    "name": enriched["name"],
                    "type": "carrier",
                    "lat": enriched["lat"],
                    "lng": enriched["lng"],
                    "heading": None,  # OSINT cannot determine true heading.
                    "sog": 0,
                    "cog": 0,
                    "country": "United States",
                    "desc": enriched["desc"],
                    "wiki": enriched["wiki"],
                    "estimated": True,
                    "source": enriched["source"],
                    "source_url": enriched["source_url"],
                    "last_osint_update": enriched["last_osint_update"],
                    # New fields (additive — existing UI continues to work):
                    "position_source_at": enriched["position_source_at"],
                    "position_confidence": enriched["position_confidence"],
                    "is_fallback": enriched["is_fallback"],
                }
            )
        return _deconflict_positions(result)


# -----------------------------------------------------------------
# Scheduler: runs at startup, then at 00:00 and 12:00 UTC daily.
# -----------------------------------------------------------------
_scheduler_thread: Optional[threading.Thread] = None
_scheduler_stop = threading.Event()


def _scheduler_loop():
    """Background thread that triggers updates at 00:00 and 12:00 UTC."""
    try:
        update_carrier_positions()
    except Exception as e:
        logger.error(f"Carrier tracker initial update failed: {e}")

    while not _scheduler_stop.is_set():
        now = datetime.now(timezone.utc)
        hour = now.hour
        if hour < 12:
            next_hour = 12
        else:
            next_hour = 24  # midnight = next day 00:00

        next_run = now.replace(hour=next_hour % 24, minute=0, second=0, microsecond=0)
        if next_hour == 24:
            next_run = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

        wait_seconds = (next_run - now).total_seconds()
        logger.info(
            "Carrier tracker: next update at %s (%.1fh)",
            next_run.isoformat(),
            wait_seconds / 3600,
        )

        if _scheduler_stop.wait(timeout=wait_seconds):
            break

        try:
            update_carrier_positions()
        except Exception as e:
            logger.error(f"Carrier tracker scheduled update failed: {e}")


def start_carrier_tracker():
    """Start the carrier tracker background thread."""
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop, daemon=True, name="carrier-tracker"
    )
    _scheduler_thread.start()
    logger.info("Carrier tracker started")


def stop_carrier_tracker():
    """Stop the carrier tracker background thread."""
    _scheduler_stop.set()
    if _scheduler_thread:
        _scheduler_thread.join(timeout=5)
    logger.info("Carrier tracker stopped")
