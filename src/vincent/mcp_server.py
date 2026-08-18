"""
Vincent MCP Server — Model Context Protocol, JSON-RPC 2.0.
Provides standard tools for IDE integration (Emacs, Neovim, VSCode) via stdio or Unix Socket.
Includes audit logging to ~/.vincent/mcp.log and daemon PID tracking.
"""

import json
import os
import sys
import time
import socket
import subprocess
from datetime import datetime
from typing import Dict, Any, Optional

from .agent_tools import (
    tool_read_file, tool_apply_diff, tool_list_dir,
    tool_grep, tool_bash, TOOL_DEFINITIONS
)

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "vincent-mcp", "version": "4.0.0"}
LOG_FILE = os.path.expanduser("~/.vincent/mcp.log")
PID_FILE = os.path.expanduser("~/.vincent/daemon.pid")

MCP_TOOLS = [
    {
        "name": "read_file",
        "description": "Lê o conteúdo de um arquivo do disco com numeração de linhas opcional.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "read_buffer",
        "description": "Alias para read_file para compatibilidade com clientes MCP legados.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"]
        }
    },
    {
        "name": "apply_diff",
        "description": "Aplica alteração cirúrgica no código via Search & Replace de blocos exatos ou unified diff.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "search_block": {"type": "string"},
                "replace_block": {"type": "string"},
                "diff": {"type": "string"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "list_dir",
        "description": "Lista diretórios e arquivos recursivamente ignorando artefatos temporários.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_depth": {"type": "integer"}
            }
        }
    },
    {
        "name": "grep_search",
        "description": "Busca global por texto ou regex no código-fonte.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
                "is_regex": {"type": "boolean"}
            },
            "required": ["pattern"]
        }
    },
    {
        "name": "run_command",
        "description": "Executa comando de terminal no workspace em ambiente controlado.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout_sec": {"type": "integer"}
            },
            "required": ["command"]
        }
    }
]


def audit_log(event_type: str, details: Dict[str, Any]):
    """Registra auditoria limpa em ~/.vincent/mcp.log."""
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        entry = {
            "ts": timestamp,
            "event": event_type,
            "details": details
        }
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def dispatch_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.time()
    try:
        if name in ("read_file", "read_buffer"):
            res = tool_read_file(
                path=args.get("path", ""),
                start_line=args.get("start_line"),
                end_line=args.get("end_line")
            )
            text_out = res.get("content") or res.get("raw_content") or res.get("error", "")
        elif name == "apply_diff":
            res = tool_apply_diff(
                path=args.get("path", ""),
                search_block=args.get("search_block"),
                replace_block=args.get("replace_block"),
                diff_content=args.get("diff")
            )
            text_out = res.get("message") or res.get("error", "")
        elif name == "list_dir":
            res = tool_list_dir(
                path=args.get("path", "."),
                max_depth=args.get("max_depth", 2)
            )
            text_out = json.dumps(res, indent=2, ensure_ascii=False)
        elif name == "grep_search":
            res = tool_grep(
                pattern=args.get("pattern", ""),
                path=args.get("path", "."),
                is_regex=args.get("is_regex", False)
            )
            text_out = json.dumps(res, indent=2, ensure_ascii=False)
        elif name in ("run_command", "run_bash"):
            res = tool_bash(
                command=args.get("command", ""),
                timeout_sec=args.get("timeout_sec", 30)
            )
            text_out = f"[Exit Code: {res.get('exit_code')}]\nSTDOUT:\n{res.get('stdout', '')}\nSTDERR:\n{res.get('stderr', '')}"
        else:
            raise ValueError(f"Ferramenta MCP desconhecida: {name}")

        dt = time.time() - t0
        audit_log("tool_call_success", {"tool": name, "args": args, "latency_sec": round(dt, 4)})
        return {"content": [{"type": "text", "text": text_out}]}

    except Exception as e:
        dt = time.time() - t0
        audit_log("tool_call_error", {"tool": name, "args": args, "error": str(e), "latency_sec": round(dt, 4)})
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}


def handle_message(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = msg.get("method")
    msg_id = msg.get("id")

    if method == "initialize":
        audit_log("client_connected", {"params": msg.get("params")})
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            }
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": MCP_TOOLS}
        }
    if method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})
        res = dispatch_tool(tool_name, tool_args)
        return {"jsonrpc": "2.0", "id": msg_id, "result": res}

    if msg_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Método não suportado: {method}"}
        }
    return None


def serve_stdio():
    """Servidor MCP sobre STDIN/STDOUT padrão."""
    audit_log("server_start", {"transport": "stdio"})
    for line in sys.stdin:
        line_clean = line.strip()
        if not line_clean:
            continue
        try:
            msg = json.loads(line_clean)
            reply = handle_message(msg)
            if reply is not None:
                sys.stdout.write(json.dumps(reply) + "\n")
                sys.stdout.flush()
        except Exception as e:
            audit_log("parse_error", {"raw": line_clean[:200], "error": str(e)})


def serve_socket(sock_path: str):
    """Servidor MCP sobre Unix Domain Socket com permissão 0600."""
    os.makedirs(os.path.dirname(sock_path), exist_ok=True)
    if os.path.exists(sock_path):
        try:
            os.remove(sock_path)
        except Exception:
            pass

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    try:
        os.chmod(sock_path, 0o600)
    except Exception:
        pass
    srv.listen(4)
    audit_log("server_start", {"transport": "unix_socket", "path": sock_path})

    while True:
        conn, _ = srv.accept()
        f = conn.makefile("rw")
        try:
            for line in f:
                line_clean = line.strip()
                if not line_clean:
                    continue
                try:
                    msg = json.loads(line_clean)
                    reply = handle_message(msg)
                    if reply is not None:
                        f.write(json.dumps(reply) + "\n")
                        f.flush()
                except Exception:
                    pass
        finally:
            conn.close()


def daemonize(log_path: str):
    """Duplo fork clássico para execução em segundo plano rastreável."""
    if os.fork() > 0:
        sys.exit(0)
    os.setsid()
    if os.fork() > 0:
        sys.exit(0)
    sys.stdout.flush()
    sys.stderr.flush()
    log = open(log_path, "a+")
    os.dup2(log.fileno(), sys.stdout.fileno())
    os.dup2(log.fileno(), sys.stderr.fileno())
    devnull = open(os.devnull, "r")
    os.dup2(devnull.fileno(), sys.stdin.fileno())


def run_server(daemon: bool = False, socket_path: Optional[str] = None):
    sock_path = socket_path or os.path.expanduser("~/.vincent/run/mcp.sock")
    if daemon:
        run_dir = os.path.dirname(sock_path)
        os.makedirs(run_dir, exist_ok=True)
        daemon_log = os.path.join(run_dir, "mcp-daemon.log")
        daemonize(daemon_log)
        
        # Salva PID nos dois caminhos rastreáveis
        current_pid = str(os.getpid())
        with open(PID_FILE, "w") as f:
            f.write(current_pid)
        with open(os.path.join(run_dir, "mcp-daemon.pid"), "w") as f:
            f.write(current_pid)
            
        audit_log("daemon_spawned", {"pid": os.getpid(), "sock": sock_path})
        serve_socket(sock_path)
    elif socket_path:
        serve_socket(sock_path)
    else:
        serve_stdio()
