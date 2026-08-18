#!/usr/bin/env python3
"""
Vincent — entry point

Uso:
  python3 -m vincent.run                  # daemon + API + agente autônomo
  python3 -m vincent.run --no-agent       # só daemon + API (sem loop Claude)
  python3 -m vincent.run --no-api         # só daemon + agente (sem servidor web)
  python3 -m vincent.run --interval 120   # ciclo autônomo a cada 120s
  python3 -m vincent.run --once           # 1 ciclo e sai
"""

import argparse
import signal
import sys
import threading
import time
import os

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from vincent.devices import DeviceRegistry, DeviceEvent
from vincent.agent   import VincentAgent
from vincent.api     import app, socketio, setup as api_setup


def main():
    parser = argparse.ArgumentParser(description="Vincent ESP Hub")
    parser.add_argument("--no-agent",   action="store_true")
    parser.add_argument("--no-api",     action="store_true")
    parser.add_argument("--interval",   type=int, default=60)
    parser.add_argument("--once",       action="store_true")
    parser.add_argument("--api-port",   type=int, default=5001)
    parser.add_argument("--verbose",    action="store_true")
    args = parser.parse_args()

    print("""
╔══════════════════════════════════════════════════════════╗
║           Vincent — Sistema Unificado ESP32              ║
║   T-Embed CC1101  +  ESP32-S3 DIV Kilaz v2              ║
╠══════════════════════════════════════════════════════════╣
║  REST API  →  http://0.0.0.0:{port}                      ║
║  WebSocket →  ws://0.0.0.0:{port}  (SocketIO)            ║
║  Docs      →  GET /api/health                            ║
╚══════════════════════════════════════════════════════════╝
""".replace("{port}", str(args.api_port)))

    events_log = []

    def on_event(ev: DeviceEvent):
        events_log.append(ev)
        if args.verbose:
            print(f"[EVT] {ev.device_id} {ev.kind}: {str(ev.payload)[:80]}", flush=True)

    # Detecta dispositivos
    print("[SCAN] detectando dispositivos USB...", flush=True)
    registry = DeviceRegistry(on_event)
    devices  = registry.scan()

    if not devices:
        print("[SCAN] nenhum dispositivo encontrado. Verifique os cabos USB.", flush=True)
    else:
        for d in devices:
            print(f"[SCAN] {d.id} — {d.label} @ {d.port} | firmware={d.firmware_id}", flush=True)
            if not d.protocol:
                print(f"       ⚠  Sem protocolo serial → precisa flash. Veja: ~/vincent_flash.sh", flush=True)

    # Agente Claude
    agent = None
    if not args.no_agent:
        agent = VincentAgent(registry, emit_fn=lambda ev, d: socketio.emit(ev, d))
        if not args.once:
            agent.start(interval=args.interval)

    # API server
    api_thread = None
    if not args.no_api:
        api_setup(registry, agent)
        api_thread = threading.Thread(
            target=lambda: socketio.run(app, host="0.0.0.0", port=args.api_port, allow_unsafe_werkzeug=True),
            daemon=True
        )
        api_thread.start()
        print(f"[API] servidor em http://0.0.0.0:{args.api_port}", flush=True)

    # Modo --once
    if args.once:
        if agent and agent._client:
            print("[AGENT] rodando ciclo único...", flush=True)
            agent._cycle()
        print("[DONE] ciclo único concluído.", flush=True)
        registry.close_all()
        return

    # Loop principal (daemon)
    def shutdown(sig, frame):
        print("\n[VINCENT] encerrando...", flush=True)
        if agent:
            agent.stop()
        registry.close_all()
        sys.exit(0)

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("\n[VINCENT] rodando. Ctrl+C para parar.", flush=True)
    print(f"[VINCENT] API em http://localhost:{args.api_port}/api/health", flush=True)
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
