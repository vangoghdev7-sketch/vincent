import json as json_mod
import logging
import os
import threading
from pathlib import Path
from typing import Any
from fastapi import APIRouter, Request, Depends, Response
from pydantic import BaseModel
from limiter import limiter
from auth import require_admin, require_local_operator
from node_state import (
    _current_node_mode,
    _participant_node_enabled,
    _refresh_node_peer_store,
    _set_participant_node_enabled,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class NodeSettingsUpdate(BaseModel):
    enabled: bool


class TimeMachineToggle(BaseModel):
    enabled: bool


class MeshtasticMqttUpdate(BaseModel):
    enabled: bool | None = None
    broker: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    psk: str | None = None
    include_default_roots: bool | None = None
    extra_roots: str | None = None
    extra_topics: str | None = None


@router.get("/api/settings/api-keys", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_get_keys(request: Request):
    from services.api_settings import get_api_keys
    return get_api_keys()


@router.put("/api/settings/api-keys", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def api_save_keys(request: Request):
    from services.api_settings import save_api_keys
    body = await request.json()
    if not isinstance(body, dict):
        return Response(
            content=json_mod.dumps({"ok": False, "detail": "Expected a JSON object."}),
            status_code=400,
            media_type="application/json",
        )
    result = save_api_keys({str(k): str(v) for k, v in body.items()})
    if result.get("ok"):
        return result
    return Response(
        content=json_mod.dumps(result),
        status_code=400,
        media_type="application/json",
    )


@router.get("/api/settings/api-keys/meta")
@limiter.limit("30/minute")
async def api_get_keys_meta(request: Request):
    """Return absolute paths for the backend .env and .env.example template.

    Not gated behind admin auth: the paths are not sensitive, and the frontend
    needs them to render the API Keys panel banner before the user has had a
    chance to enter an admin key. Helps users find the file when in-app editing
    is blocked or when the backend is read-only.
    """
    from services.api_settings import get_env_path_info
    return get_env_path_info()


@router.get(
    "/api/settings/operator-handle",
    dependencies=[Depends(require_local_operator)],
)
@limiter.limit("60/minute")
async def api_get_operator_handle(request: Request):
    """Round 7a: return the per-install operator handle so the frontend
    can include it in browser-direct third-party API calls (Wikipedia /
    Wikidata via lib/wikimediaClient). The handle is auto-generated on
    first use; operators can override it via the OPERATOR_HANDLE setting
    or the env var of the same name.

    Gated on local-operator: legitimate browser usage goes through the
    Next.js proxy which auto-attaches the admin key; remote scanners get
    403. The handle itself isn't a secret (it's sent to every third-party
    API the operator touches), but admin-gating it matches the rest of
    the settings endpoints and follows least-privilege.
    """
    from services.network_utils import get_operator_handle
    return {"handle": get_operator_handle()}


@router.get(
    "/api/settings/news-feeds",
    dependencies=[Depends(require_local_operator)],
)
@limiter.limit("30/minute")
async def api_get_news_feeds(request: Request):
    """Issue #252 (tg12): the curated feed inventory is configuration
    state, not a public data feed. Gated on local-operator so the
    Tauri shell, the Docker bridge frontend, and any caller with an
    admin key all see the full list; anonymous LAN/internet callers
    can no longer enumerate operator source URLs.
    """
    from services.news_feed_config import get_feeds
    return get_feeds()


@router.put("/api/settings/news-feeds", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def api_save_news_feeds(request: Request):
    from services.news_feed_config import save_feeds
    body = await request.json()
    ok = save_feeds(body)
    if ok:
        return {"status": "updated", "count": len(body)}
    return Response(
        content=json_mod.dumps({"status": "error",
            "message": "Validation failed (max 20 feeds, each needs name/url/weight 1-5)"}),
        status_code=400,
        media_type="application/json",
    )


@router.post("/api/settings/news-feeds/reset", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
async def api_reset_news_feeds(request: Request):
    from services.news_feed_config import get_feeds, reset_feeds
    ok = reset_feeds()
    if ok:
        return {"status": "reset", "feeds": get_feeds()}
    return {"status": "error", "message": "Failed to reset feeds"}


@router.get("/api/settings/node")
@limiter.limit("30/minute")
async def api_get_node_settings(request: Request):
    """Issue #243 (tg12): node_mode and node_enabled are operational
    posture. Anonymous callers receive an empty stub; authenticated
    callers (local-operator or admin/scoped token) see the full
    state. See the canonical handler in backend/main.py for the full
    rationale.
    """
    import asyncio
    from auth import _scoped_view_authenticated
    from services.node_settings import read_node_settings
    data = await asyncio.to_thread(read_node_settings)
    if not _scoped_view_authenticated(request, "node"):
        return {}
    return {
        **data,
        "node_mode": _current_node_mode(),
        "node_enabled": _participant_node_enabled(),
    }


@router.put("/api/settings/node", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def api_set_node_settings(request: Request, body: NodeSettingsUpdate):
    _refresh_node_peer_store()
    if bool(body.enabled):
        try:
            from services.transport_lane_isolation import disable_public_mesh_lane

            disable_public_mesh_lane(reason="private_node_enabled")
        except Exception as exc:
            logger.warning("Failed to disable public Mesh while enabling private node: %s", exc)
    result = _set_participant_node_enabled(bool(body.enabled))
    if bool(body.enabled):
        try:
            import main as _main

            _main._kick_public_sync_background("operator_enable")
        except Exception:
            logger.debug("Unable to kick Infonet sync after node enable", exc_info=True)
    return result


def _meshtastic_runtime_snapshot() -> dict[str, Any]:
    from services.meshtastic_mqtt_settings import redacted_meshtastic_mqtt_settings
    from services.sigint_bridge import sigint_grid

    return {
        **redacted_meshtastic_mqtt_settings(),
        "runtime": sigint_grid.mesh.status(),
    }


@router.get("/api/settings/meshtastic-mqtt", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_get_meshtastic_mqtt_settings(request: Request):
    return _meshtastic_runtime_snapshot()


@router.put("/api/settings/meshtastic-mqtt", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def api_set_meshtastic_mqtt_settings(request: Request, body: MeshtasticMqttUpdate):
    from services.meshtastic_mqtt_settings import write_meshtastic_mqtt_settings
    from services.sigint_bridge import sigint_grid

    updates = body.model_dump(exclude_unset=True)
    # Empty secret fields mean "keep existing"; explicit non-empty values replace.
    if updates.get("password") == "":
        updates.pop("password", None)
    if updates.get("psk") == "":
        updates.pop("psk", None)

    enabled_requested = updates.get("enabled")
    settings = write_meshtastic_mqtt_settings(**updates)
    if isinstance(enabled_requested, bool):
        logger.info("Meshtastic MQTT settings update: enabled=%s", enabled_requested)

    if enabled_requested is True:
        # Public MQTT and Wormhole are intentionally mutually exclusive lanes.
        try:
            from services.node_settings import write_node_settings
            from services.wormhole_settings import write_wormhole_settings
            from services.wormhole_supervisor import disconnect_wormhole

            write_wormhole_settings(enabled=False)
            disconnect_wormhole(reason="public_mesh_enabled")
            write_node_settings(enabled=False)
            _set_participant_node_enabled(False)
        except Exception as exc:
            logger.warning("Failed to disable private mesh lane while enabling public mesh: %s", exc)

    if bool(settings.get("enabled")):
        if sigint_grid.mesh.is_running():
            sigint_grid.mesh.stop()
            threading.Timer(1.0, sigint_grid.mesh.start).start()
        else:
            sigint_grid.mesh.start()
    else:
        sigint_grid.mesh.stop()

    return _meshtastic_runtime_snapshot()


@router.get(
    "/api/settings/timemachine",
    dependencies=[Depends(require_local_operator)],
)
@limiter.limit("30/minute")
async def api_get_timemachine_settings(request: Request):
    """Issue #253 (tg12): archival-capture posture is operationally
    sensitive — it tells a remote caller whether this deployment is
    retaining replayable historical surveillance data. Gated on
    local-operator so the Tauri shell and Docker bridge frontend
    still see the toggle state, but anonymous LAN/internet callers
    can no longer fingerprint Time Machine state.
    """
    import asyncio
    from services.node_settings import read_node_settings
    data = await asyncio.to_thread(read_node_settings)
    return {
        "enabled": data.get("timemachine_enabled", False),
        "storage_warning": "Time Machine auto-snapshots use ~68 MB/day compressed (~2 GB/month). "
                           "Snapshots capture entity positions (flights, ships, satellites) for historical playback.",
    }


@router.put("/api/settings/timemachine", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def api_set_timemachine_settings(request: Request, body: TimeMachineToggle):
    import asyncio
    from services.node_settings import write_node_settings
    result = await asyncio.to_thread(write_node_settings, timemachine_enabled=body.enabled)
    return {
        "ok": True,
        "enabled": result.get("timemachine_enabled", False),
    }


@router.post("/api/system/update", dependencies=[Depends(require_admin)])
@limiter.limit("1/minute")
async def system_update(request: Request):
    """Download latest release, backup current files, extract update, and restart."""
    from services.updater import perform_update, schedule_restart
    candidate = Path(__file__).resolve().parent.parent.parent
    if (candidate / "frontend").is_dir() or (candidate / "backend").is_dir():
        project_root = str(candidate)
    else:
        project_root = os.getcwd()
    result = perform_update(project_root)
    if result.get("status") == "error":
        return Response(content=json_mod.dumps(result), status_code=500, media_type="application/json")
    if result.get("status") == "docker":
        return result
    threading.Timer(2.0, schedule_restart, args=[project_root]).start()
    return result


# ── Tor Hidden Service ──────────────────────────────────────────────


@router.get("/api/settings/tor", dependencies=[Depends(require_local_operator)])
@limiter.limit("30/minute")
async def api_tor_status(request: Request):
    """Return Tor hidden service status and .onion address if available."""
    import asyncio
    from services.tor_hidden_service import tor_service

    return await asyncio.to_thread(tor_service.status)


@router.post("/api/settings/tor/start", dependencies=[Depends(require_local_operator)])
@limiter.limit("5/minute")
async def api_tor_start(request: Request):
    """Start Tor and provision a hidden service for this Vincent instance.

    Also enables MESH_ARTI so the mesh/wormhole system can route traffic
    through the Tor SOCKS proxy (port 9050) automatically.
    """
    import asyncio
    from services.tor_hidden_service import tor_service

    result = await asyncio.to_thread(tor_service.start)

    # If Tor started successfully, enable Arti (Tor SOCKS proxy for mesh)
    if result.get("ok"):
        try:
            from routers.ai_intel import _write_env_value
            from services.config import get_settings
            _write_env_value("MESH_ARTI_ENABLED", "true")
            get_settings.cache_clear()
        except Exception:
            pass  # Non-fatal — hidden service still works without mesh Arti

    return result


@router.post("/api/settings/tor/reset-identity", dependencies=[Depends(require_local_operator)])
@limiter.limit("2/minute")
async def api_tor_reset_identity(request: Request):
    """Destroy current .onion identity and generate a fresh one on next start.

    This is irreversible — the old .onion address is permanently lost.
    """
    import asyncio, shutil
    from services.tor_hidden_service import tor_service, TOR_DIR

    # Stop Tor if running
    await asyncio.to_thread(tor_service.stop)

    # Delete the hidden service directory (contains the private key)
    hs_dir = TOR_DIR / "hidden_service"
    if hs_dir.exists():
        shutil.rmtree(str(hs_dir), ignore_errors=True)

    # Clear cached address
    tor_service._onion_address = ""

    return {"ok": True, "detail": "Tor identity destroyed. A new .onion will be generated on next start."}


@router.post("/api/settings/agent/reset-all", dependencies=[Depends(require_local_operator)])
@limiter.limit("2/minute")
async def api_reset_all_agent_credentials(request: Request):
    """Nuclear reset: regenerate HMAC key, destroy .onion, revoke agent identity.

    After this, the agent is fully disconnected and needs new credentials.
    """
    import asyncio, secrets, shutil
    from services.tor_hidden_service import tor_service, TOR_DIR
    from services.config import get_settings

    results = {}

    # 1. Regenerate HMAC key
    new_secret = secrets.token_hex(24)
    from routers.ai_intel import _write_env_value
    _write_env_value("OPENCLAW_HMAC_SECRET", new_secret)
    results["hmac"] = "regenerated"

    # 2. Revoke agent identity (Ed25519 keypair)
    try:
        from services.openclaw_bridge import revoke_agent_identity
        revoke_agent_identity()
        results["identity"] = "revoked"
    except Exception as e:
        results["identity"] = f"error: {e}"

    # 3. Destroy .onion and restart Tor with new identity
    await asyncio.to_thread(tor_service.stop)
    hs_dir = TOR_DIR / "hidden_service"
    if hs_dir.exists():
        shutil.rmtree(str(hs_dir), ignore_errors=True)
    tor_service._onion_address = ""
    results["tor"] = "identity destroyed"

    # 4. Bootstrap fresh identity + start Tor with new .onion
    try:
        from services.openclaw_bridge import generate_agent_keypair
        keypair = generate_agent_keypair(force=True)
        results["new_node_id"] = keypair.get("node_id", "")
    except Exception as e:
        results["new_node_id"] = f"error: {e}"

    tor_result = await asyncio.to_thread(tor_service.start)
    results["new_onion"] = tor_result.get("onion_address", "")
    results["tor_ok"] = tor_result.get("ok", False)

    # Clear settings cache
    get_settings.cache_clear()

    return {
        "ok": True,
        "hmac_regenerated": True,
        "detail": "All agent credentials have been reset. Use the agent connection screen to generate or reveal replacement credentials.",
        **results,
    }


@router.post("/api/settings/tor/stop", dependencies=[Depends(require_local_operator)])
@limiter.limit("10/minute")
async def api_tor_stop(request: Request):
    """Stop the Tor hidden service."""
    import asyncio
    from services.tor_hidden_service import tor_service

    return await asyncio.to_thread(tor_service.stop)
