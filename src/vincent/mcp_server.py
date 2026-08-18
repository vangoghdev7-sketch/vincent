"""
Vincent MCP server — Model Context Protocol, JSON-RPC 2.0.
Transport: stdio (default, spawned by an IDE MCP client) or a Unix socket
(`--daemon` / `--socket`), for a persistent background instance.

Tools:
  read_buffer(path)        -> file contents from disk
  apply_diff(path, diff)   -> apply a unified diff via the system `patch`, write result

Payload shapes cross-checked against manzaltu/claude-code-ide.el as a
protocol reference only — this is Vincent's own server, not a copy.
"""

import json
import os
import socket
import subprocess
import sys

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "vincent-mcp", "version": "1.0"}

TOOLS = [
    {
        "name": "read_buffer",
        "description": "Read a file's current contents from disk.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "apply_diff",
        "description": "Apply a unified diff (diff -u format) to a file and write the result.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "diff": {"type": "string"},
            },
            "required": ["path", "diff"],
        },
    },
]


def tool_read_buffer(args):
    path = os.path.abspath(os.path.expanduser(args["path"]))
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    return {"content": [{"type": "text", "text": text}]}


def tool_apply_diff(args):
    path = os.path.abspath(os.path.expanduser(args["path"]))
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    proc = subprocess.run(
        ["patch", "--fuzz=0", "-p0", "-o", "-", path],
        input=args["diff"], capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or "patch failed")
    with open(path, "w", encoding="utf-8") as f:
        f.write(proc.stdout)
    return {"content": [{"type": "text", "text": f"applied, {len(proc.stdout)} bytes written to {path}"}]}


DISPATCH = {"read_buffer": tool_read_buffer, "apply_diff": tool_apply_diff}


def _result(msg_id, result):
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle(msg):
    method = msg.get("method")
    msg_id = msg.get("id")

    if method == "initialize":
        return _result(msg_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _result(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        params = msg.get("params", {})
        fn = DISPATCH.get(params.get("name"))
        if fn is None:
            return _error(msg_id, -32601, f"unknown tool: {params.get('name')}")
        try:
            return _result(msg_id, fn(params.get("arguments", {})))
        except Exception as e:
            return _result(msg_id, {"content": [{"type": "text", "text": str(e)}], "isError": True})

    if msg_id is not None:
        return _error(msg_id, -32601, f"unknown method: {method}")
    return None


def _dispatch_line(line, write):
    line = line.strip()
    if not line:
        return
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return
    reply = handle(msg)
    if reply is not None:
        write(json.dumps(reply) + "\n")


def serve_stdio():
    for line in sys.stdin:
        _dispatch_line(line, lambda s: (sys.stdout.write(s), sys.stdout.flush()))


def serve_socket(sock_path):
    os.makedirs(os.path.dirname(sock_path), exist_ok=True)
    if os.path.exists(sock_path):
        os.remove(sock_path)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    os.chmod(sock_path, 0o600)
    srv.listen(4)
    while True:
        conn, _ = srv.accept()
        f = conn.makefile("rw")
        try:
            for line in f:
                _dispatch_line(line, lambda s: (f.write(s), f.flush()))
        finally:
            conn.close()


def daemonize(log_path):
    """ponytail: classic double-fork, no external daemon lib needed for a single-user background process."""
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


def run(daemon=False, socket_path=None):
    sock_path = socket_path or os.path.expanduser("~/.vincent/run/mcp.sock")
    if daemon:
        run_dir = os.path.dirname(sock_path)
        os.makedirs(run_dir, exist_ok=True)
        daemonize(os.path.join(run_dir, "mcp-daemon.log"))
        with open(os.path.join(run_dir, "mcp-daemon.pid"), "w") as f:
            f.write(str(os.getpid()))
        serve_socket(sock_path)
    elif socket_path:
        serve_socket(sock_path)
    else:
        serve_stdio()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Vincent MCP server")
    p.add_argument("--daemon", action="store_true", help="Detach from terminal, serve via Unix socket in background")
    p.add_argument("--socket", default=None, help="Serve via Unix socket at PATH instead of stdio")
    ns = p.parse_args()
    run(daemon=ns.daemon, socket_path=ns.socket)
