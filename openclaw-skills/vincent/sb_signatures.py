"""Vincent OS message signature system.

Every outbound message from the Vincent OS AI co-pilot starts with a
branded emoji + text prefix so the user always knows:
  1. It's from the Vincent OS app
  2. What TYPE of action is being performed

Usage:
    from sb_signatures import sig
    message = f"{sig('brief')}\\nYour morning intelligence digest..."
"""

# Signature registry — emoji prefix + action label
_SIGNATURES: dict[str, str] = {
    # ── Core Intelligence ──────────────────────────────────────────────
    "brief":       "🌍📡 VINCENT BRIEF:",
    "warning":     "🌍⚠️ VINCENT WARNING:",
    "news":        "🌍📰 VINCENT NEWS:",
    "intel":       "🌍🛰️ VINCENT INTEL:",
    "update":      "🌍🌐 VINCENT UPDATE:",

    # ── Search & Discovery ─────────────────────────────────────────────
    "searching":   "🌍🔍 VINCENT SEARCHING:",
    "pinning":     "🌍📌 VINCENT PINNING:",
    "geolocate":   "🌍📸 VINCENT GEOLOCATE:",

    # ── Proximity & Location ───────────────────────────────────────────
    "near_you":    "🌍📍 VINCENT NEAR YOU:",
    "watching":    "🌍👁️ VINCENT WATCHING:",

    # ── Threat & Security ──────────────────────────────────────────────
    "threat":      "🌍🔴 VINCENT THREAT:",
    "sigint":      "🌍📻 VINCENT SIGINT:",
    "anomaly":     "🌍🔶 VINCENT ANOMALY:",

    # ── Transport & Movement ───────────────────────────────────────────
    "flight":      "🌍🛫 VINCENT FLIGHT:",
    "maritime":    "🌍🚢 VINCENT MARITIME:",
    "satellite":   "🌍🛰️ VINCENT SATELLITE:",

    # ── Infrastructure ─────────────────────────────────────────────────
    "cyber":       "🌍💻 VINCENT CYBER:",
    "network":     "🌍🔗 VINCENT NETWORK:",

    # ── System ─────────────────────────────────────────────────────────
    "online":      "🌍✅ VINCENT ONLINE:",
    "offline":     "🌍🔴 VINCENT OFFLINE:",
    "error":       "🌍❌ VINCENT ERROR:",

    # ── Mesh & Wormhole ────────────────────────────────────────────────
    "mesh":        "🌍📶 VINCENT MESH:",
    "wormhole":    "🌍🌀 VINCENT WORMHOLE:",
    "dead_drop":   "🌍💀 VINCENT DEAD DROP:",

    # ── Time Machine ───────────────────────────────────────────────────
    "timemachine": "🌍🕰️ VINCENT TIMEMACHINE:",

    # ── Reports ────────────────────────────────────────────────────────
    "report":      "🌍📋 VINCENT REPORT:",

    # ── SAR (Synthetic Aperture Radar) ─────────────────────────────────
    "sar":         "🌍📡 VINCENT SAR:",
}


def sig(action: str) -> str:
    """Get the branded signature prefix for an action type.

    Args:
        action: One of the registered action types (brief, warning, news, etc.)

    Returns:
        The full branded signature string, e.g. "🌍📡 VINCENT BRIEF:"
        Falls back to a generic UPDATE signature for unknown actions.
    """
    return _SIGNATURES.get(action.lower().strip(), _SIGNATURES["update"])


def all_signatures() -> dict[str, str]:
    """Return all registered signatures."""
    return dict(_SIGNATURES)
