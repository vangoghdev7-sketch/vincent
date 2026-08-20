#!/usr/bin/env bash
# ==============================================================================
# VINCENT OS // UNIFIED LAUNCHER & ORCHESTRATOR
# ==============================================================================
# Plane 1: Vincent OSINT Command Stack  -> :3000 (UI) + :8000 (API Backend)
# Plane 2: Vincent Multi-AI Swarm Router -> :20128 (Web Dashboard + OpenAI API)
# Plane 3: Vincent OpenClaw Skill Agent -> HMAC Agent Integration
# ==============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROUTER_URL="http://127.0.0.1:20128"
BACKEND_URL="http://127.0.0.1:8000"
FRONTEND_URL="http://127.0.0.1:3000"

detect_compose() {
  if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then COMPOSE=(podman compose); return; fi
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then COMPOSE=(docker compose); return; fi
  if command -v podman-compose >/dev/null 2>&1; then COMPOSE=(podman-compose); return; fi
  if command -v docker-compose >/dev/null 2>&1; then COMPOSE=(docker-compose); return; fi
  echo "[!] No compose engine found (need docker/podman compose)"; exit 1
}

compose() { ( cd "$ROOT" && "${COMPOSE[@]}" "$@" ); }

up_port() {
  local port="$1"
  timeout 2 bash -c "echo > /dev/tcp/127.0.0.1/$port" 2>/dev/null
}

cleanup_legacy_containers() {
  if command -v podman >/dev/null 2>&1; then
    podman rm -f vincent-backend vincent-frontend >/dev/null 2>&1 || true
  fi
  if command -v docker >/dev/null 2>&1; then
    docker rm -f vincent-backend vincent-frontend >/dev/null 2>&1 || true
  fi
}

link() {
  local target="$1" name="$2"
  [ -e "$target" ] || { echo "  [skip] $name (missing: $target)"; return; }
  ln -sfn "$target" "$ROOT/vincent/$name"
  echo "  [link] vincent/$name -> $target"
}

setup_links() {
  mkdir -p "$ROOT/vincent"
  echo "[*] Refreshing ./vincent symlink index:"
  link "$HOME/.vincent"                                                vincent-config
  link "$HOME/.vincentos"                                              vincentos-config
  link "$HOME/.vincent-router"                                              router-config
  link "$HOME/.openclaw/agents"                                        openclaw-agents
  link "$HOME/.openclaw/skills/vincent_os"                             openclaw-skill
  link "$HOME/.local/bin"                                              bin
  link "$HOME/.agents/skills"                                          skills-store
}

ensure_router() {
  if up_port 20128; then
    echo "[=] Vincent Multi-AI Router active at $ROUTER_URL"
    return
  fi
  local bin=""
  for candidate in \
    "$HOME/.local/bin/vincent_os" \
    "$(command -v vincent_os || true)" \
    "$HOME/.nvm/versions/node/v24.15.0/bin/vincent_os" \
    "$(command -v vincent-router || true)" \
    "$HOME/.nvm/versions/node/v24.15.0/bin/vincent-router"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
      bin="$candidate"
      break
    fi
  done

  if [ -z "$bin" ]; then
    echo "[!] Vincent Multi-AI router binary not found. Launch manually if needed."
    return
  fi

  echo "[*] Starting Vincent Multi-AI Swarm Gateway ($bin)..."
  mkdir -p "$HOME/.vincentos/logs"
  setsid nohup "$bin" >>"$HOME/.vincentos/logs/unified-launcher.log" 2>&1 &
  for _ in $(seq 1 15); do
    if up_port 20128; then break; fi
    sleep 1
  done

  if up_port 20128; then
    echo "[=] Vincent Multi-AI Router online at $ROUTER_URL"
  else
    echo "[!] Router starting in background — check $HOME/.vincentos/logs/unified-launcher.log"
  fi
}

detect_compose

case "${1:-status}" in
  start)
    cleanup_legacy_containers
    setup_links
    echo "[*] Launching Vincent OS containers (${COMPOSE[*]} up -d)..."
    compose up -d
    ensure_router
    echo ""
    "$0" status
    ;;
  stop)
    echo "[*] Stopping Vincent OS containers (${COMPOSE[*]} stop)..."
    compose stop
    echo "[i] Multi-AI Router (:20128) left active (shared Vincent infra)."
    echo "    To stop the router: $0 stop-router"
    ;;
  stop-router)
    pkill -f 'node .*(vincent_os|vincent-router)' && echo "[=] Vincent Router stopped" || echo "[i] No router process found"
    ;;
  restart)
    "$0" stop
    "$0" start
    ;;
  status)
    echo "======================================================================"
    echo "                   VINCENT OS // SYSTEM STATUS                        "
    echo "======================================================================"
    echo "Containers:"
    compose ps || true
    echo ""
    echo "Planes & Endpoints:"
    if up_port 3000; then
      echo "  [✓] Frontend UI          : $FRONTEND_URL (ONLINE)"
    else
      echo "  [✗] Frontend UI          : $FRONTEND_URL (OFFLINE)"
    fi
    if up_port 8000; then
      echo "  [✓] Backend API & Feeds  : $BACKEND_URL (ONLINE)"
    else
      echo "  [✗] Backend API & Feeds  : $BACKEND_URL (INITIALIZING / OFFLINE)"
    fi
    if up_port 20128; then
      echo "  [✓] Multi-AI Swarm Router: $ROUTER_URL (ONLINE)"
    else
      echo "  [✗] Multi-AI Swarm Router: $ROUTER_URL (OFFLINE)"
    fi
    echo ""
    echo "Integrations:"
    echo "  OpenClaw Skill   : $( [ -e "$HOME/.openclaw/skills/vincent_os" ] && echo '[✓] Installed' || echo '[!] Pending' )"
    echo "  Vincent Config   : $( [ -e "$HOME/.vincentos" ] && echo '[✓] Configured' || echo '[!] Default' )"
    echo "======================================================================"
    ;;
  doctor)
    echo "[*] Running Vincent OS Doctor Diagnostics..."
    echo -n "  Node.js: "; node -v 2>/dev/null || echo "Not found"
    echo -n "  Compose Engine: "; "${COMPOSE[@]}" version 2>/dev/null || echo "Error"
    echo -n "  Port 3000 (UI): "; up_port 3000 && echo "Occupied (OK)" || echo "Free"
    echo -n "  Port 8000 (API): "; up_port 8000 && echo "Occupied (OK)" || echo "Free"
    echo -n "  Port 20128 (AI): "; up_port 20128 && echo "Occupied (OK)" || echo "Free"
    ;;
  links)
    setup_links
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|doctor|links|stop-router}"
    exit 1
    ;;
esac
