"""
Vincent API — REST + WebSocket para controle local e app mobile futuro.

Endpoints REST:
  GET  /api/devices                    → lista dispositivos
  GET  /api/devices/<id>               → status de um dispositivo
  POST /api/devices/<id>/command       → envia comando  {cmd, wait?}
  GET  /api/devices/<id>/capabilities  → hardware + comandos seguros
  POST /api/agent/ask                  → pergunta avulsa ao agente Claude
  GET  /api/flash/status               → status dos binários de flash disponíveis

WebSocket (SocketIO):
  Evento emitido → cliente:
    "device_update"   {device_id, kind, payload}
    "agent_analysis"  {text}
    "agent_followup"  {text}
    "agent_cycle"     {devices}

CORS habilitado → app mobile pode conectar de qualquer origem.
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO
import os

_STATIC = os.path.join(os.path.dirname(__file__), "static")

from .config import FLASH_IMAGES, FIRMWARE, DEVICES as DEVICE_PROFILES
from .devices import DeviceRegistry, DeviceEvent

app     = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("VINCENT_SECRET", "vincent-dev")

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

_registry: DeviceRegistry | None = None
_agent    = None   # VincentAgent, injetado em run.py


def setup(registry: DeviceRegistry, agent):
    global _registry, _agent
    _registry = registry
    _agent    = agent

    # Propaga eventos dos devices para WebSocket
    def on_event(ev: DeviceEvent):
        socketio.emit("device_update", ev.to_dict())
    registry.on_event = on_event


# ─── REST ────────────────────────────────────────────────────────────────────

@app.get("/")
def mobile_app():
    return send_from_directory(_STATIC, "app.html")


@app.get("/api/devices")
def list_devices():
    return jsonify(_registry.all_dict())


@app.get("/api/devices/<dev_id>")
def get_device(dev_id):
    dev = _registry.get(dev_id)
    if not dev:
        return jsonify({"error": f"{dev_id} não encontrado"}), 404
    return jsonify(dev.status_dict())


@app.post("/api/devices/<dev_id>/command")
def send_command(dev_id):
    body = request.get_json(silent=True) or {}
    cmd  = body.get("cmd", "").strip()
    wait = float(body.get("wait", 5.0))
    if not cmd:
        return jsonify({"error": "campo 'cmd' obrigatório"}), 400
    result = _registry.send(dev_id, cmd, wait)
    return jsonify(result)


@app.get("/api/devices/<dev_id>/capabilities")
def get_capabilities(dev_id):
    dev = _registry.get(dev_id)
    if not dev:
        return jsonify({"error": "não encontrado"}), 404
    profile = DEVICE_PROFILES.get(dev_id, {})
    fw      = FIRMWARE.get(profile.get("firmware_current", ""), {})
    return jsonify({
        "device_id":   dev_id,
        "label":       dev.label,
        "hardware":    dev.hardware,
        "safe_cmds":   fw.get("safe", []),
        "blocked_cmds": fw.get("blocked", {}),
        "protocol":    dev.protocol,
    })


@app.post("/api/agent/ask")
def agent_ask():
    if not _agent:
        return jsonify({"error": "agente não iniciado"}), 503
    body = request.get_json(silent=True) or {}
    q    = body.get("question", "").strip()
    if not q:
        return jsonify({"error": "campo 'question' obrigatório"}), 400
    answer = _agent.ask(q)
    return jsonify({"answer": answer})


@app.get("/api/flash/status")
def flash_status():
    result = {}
    for dev_id, images in FLASH_IMAGES.items():
        result[dev_id] = {}
        for name, info in images.items():
            path   = info.get("path", "")
            exists = os.path.exists(path)
            result[dev_id][name] = {
                "available": exists,
                "path":      path,
                "slots":     info.get("slots", {}),
                "boot_method": info.get("boot_method", "?"),
                "note":      info.get("note", ""),
            }
    return jsonify(result)


@app.get("/api/health")
def health():
    devs = _registry.all_dict() if _registry else []
    return jsonify({
        "status": "ok",
        "devices": len(devs),
        "agent":   _agent is not None,
    })


# ─── WebSocket ───────────────────────────────────────────────────────────────

@socketio.on("connect")
def on_connect():
    if _registry:
        socketio.emit("device_update", {
            "kind":    "all_devices",
            "payload": _registry.all_dict(),
        })


@socketio.on("command")
def on_ws_command(data):
    dev_id = data.get("device_id", "")
    cmd    = data.get("cmd", "")
    wait   = float(data.get("wait", 5.0))
    if not dev_id or not cmd:
        socketio.emit("command_result", {"error": "device_id e cmd obrigatórios"})
        return
    result = _registry.send(dev_id, cmd, wait)
    socketio.emit("command_result", {"device_id": dev_id, **result})
