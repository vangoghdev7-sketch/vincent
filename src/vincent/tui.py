"""
Vincent CLI 4.0 — Live dashboard (rich).

Display layer only. Renders whatever state it is handed (dicts or the
dataclasses defined below) — it does NOT import vincent.agent or vincent.cli
and does NOT drive a VincentAgent. A future integration pass in cli.py is
expected to call `mount()` (or `render_frame()` per tick) with state pulled
from wherever the agent lives.

Entry point: `mount(state: dict) -> None`. See its docstring for the
expected shape of `state`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Palette pulled from vincent.ui's official ANSI table, translated to the
# hex rich understands (rich renders its own truecolor, no ANSI codes to
# import — see CLAUDE.md "Sempre importar de vincent.ui" which governs raw
# \033[...] escapes, not rich's color system).
COBALT_BLUE = "#0087ff"
CHROME_YELLOW = "#ffd700"
STARRY_GOLD = "#ffaf00"
CYPRESS_GREEN = "#00ff87"
VIOLET_SWIRL = "#af87ff"
ALERT_SCARLET = "#ff0000"
CANVAS_WHITE = "#e4e4e4"
SHADOW_GRAY = "#6c6c6c"

STATUS_COLOR = {
    "running": CHROME_YELLOW,
    "done": CYPRESS_GREEN,
    "failed": ALERT_SCARLET,
}

# ponytail: tool-call args/result are shown truncated to this many chars,
# with a "(collapsed, N more chars)" note instead of real interactive
# expand/collapse — Live redraw doesn't have a clean per-line focus/keypress
# model without a much bigger event loop. Upgrade path: swap Live for a
# proper Textual app if real keyboard-driven expand is ever needed.
COLLAPSE_CHARS = 200


@dataclass
class WorkerState:
    """One row in the worker-status panel."""
    id: str
    task: str
    status: str = "running"  # running | done | failed


@dataclass
class ToolCallEntry:
    """One collapsed-by-default tool-call log entry."""
    name: str
    args: dict = field(default_factory=dict)
    result: Any = None
    ok: bool = True


@dataclass
class ChatMessage:
    """One line in the scrollback log. role: user | assistant | system | tool."""
    role: str
    text: str


def _fmt_tokens(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def render_header(state: dict) -> Panel:
    """Top row: model, tokens used/saved, estimated cost."""
    model = state.get("model", "?")
    tokens_used = state.get("tokens_used", 0)
    tokens_saved = state.get("tokens_saved", 0)
    cost = state.get("cost_usd", 0.0)

    line = Text()
    line.append("● ", style=CYPRESS_GREEN)
    line.append(str(model), style=f"bold {COBALT_BLUE}")
    line.append("   tokens ", style=SHADOW_GRAY)
    line.append(_fmt_tokens(tokens_used), style=CANVAS_WHITE)
    line.append(" used", style=SHADOW_GRAY)
    line.append(" / ", style=SHADOW_GRAY)
    line.append(_fmt_tokens(tokens_saved), style=CYPRESS_GREEN)
    line.append(" saved", style=SHADOW_GRAY)
    line.append("   ~$", style=SHADOW_GRAY)
    line.append(f"{cost:.4f}", style=STARRY_GOLD)

    return Panel(line, title="Vincent", border_style=COBALT_BLUE, height=3)


def render_workers(workers: list) -> Panel:
    """Worker-status panel. Accepts WorkerState instances or plain dicts."""
    table = Table(expand=True, box=None, show_edge=False)
    table.add_column("id", style=SHADOW_GRAY, width=8)
    table.add_column("task", style=CANVAS_WHITE, ratio=1)
    table.add_column("status", justify="right", width=10)

    for w in workers:
        wid = w.id if isinstance(w, WorkerState) else w.get("id", "?")
        task = w.task if isinstance(w, WorkerState) else w.get("task", "")
        status = w.status if isinstance(w, WorkerState) else w.get("status", "running")
        color = STATUS_COLOR.get(status, CANVAS_WHITE)
        table.add_row(str(wid), str(task), Text(status, style=color))

    if not workers:
        table.add_row("-", "no active workers", Text("idle", style=SHADOW_GRAY))

    return Panel(table, title="Workers", border_style=VIOLET_SWIRL)


def _render_tool_call(entry) -> Text:
    """Collapsed one-liner for a tool call, e.g. '▸ ran git_status (collapsed, 84 more chars)'."""
    name = entry.name if isinstance(entry, ToolCallEntry) else entry.get("name", "?")
    args = entry.args if isinstance(entry, ToolCallEntry) else entry.get("args", {})
    result = entry.result if isinstance(entry, ToolCallEntry) else entry.get("result")
    ok = entry.ok if isinstance(entry, ToolCallEntry) else entry.get("ok", True)

    payload = json.dumps({"args": args, "result": result}, default=str, ensure_ascii=False)
    color = CYPRESS_GREEN if ok else ALERT_SCARLET

    t = Text()
    t.append("▸ ran ", style=SHADOW_GRAY)
    t.append(str(name), style=f"bold {color}")
    if len(payload) > COLLAPSE_CHARS:
        shown = payload[:COLLAPSE_CHARS]
        more = len(payload) - COLLAPSE_CHARS
        t.append(f"  {shown}...(collapsed, {more} more chars)", style=SHADOW_GRAY)
    else:
        t.append(f"  {payload}", style=SHADOW_GRAY)
    return t


def render_log(messages: list, max_lines: int = 20) -> Panel:
    """Chat/log scrollback: renders the last `max_lines` entries.

    Accepts ChatMessage/ToolCallEntry instances or plain dicts with a
    `"kind"` key ("chat" default, or "tool") to pick the renderer.
    """
    recent = messages[-max_lines:]
    lines = []
    for m in recent:
        if isinstance(m, ToolCallEntry) or (isinstance(m, dict) and m.get("kind") == "tool"):
            lines.append(_render_tool_call(m))
            continue

        role = m.role if isinstance(m, ChatMessage) else m.get("role", "?")
        text = m.text if isinstance(m, ChatMessage) else m.get("text", "")
        role_color = {
            "user": CHROME_YELLOW,
            "assistant": COBALT_BLUE,
            "system": SHADOW_GRAY,
        }.get(role, CANVAS_WHITE)
        line = Text()
        line.append(f"{role}: ", style=f"bold {role_color}")
        line.append(str(text), style=CANVAS_WHITE)
        lines.append(line)

    if not lines:
        lines = [Text("(no messages yet)", style=SHADOW_GRAY)]

    return Panel(Group(*lines), title="Log", border_style=CYPRESS_GREEN)


def render_frame(state: dict) -> Layout:
    """Build one full dashboard frame from `state`. Pure function, no I/O."""
    layout = Layout()
    layout.split_column(
        Layout(render_header(state), name="header", size=3),
        Layout(name="body"),
    )
    layout["body"].split_row(
        Layout(render_workers(state.get("workers", [])), name="workers", ratio=1),
        Layout(render_log(state.get("log", []), state.get("max_log_lines", 20)), name="log", ratio=2),
    )
    return layout


def mount(state: dict, console: Console | None = None, refresh_per_second: int = 4) -> Live:
    """Build a `Live` display for `state` and return it un-started.

    `state` shape (all keys optional, sane defaults applied):
        {
            "model": str,
            "tokens_used": int,
            "tokens_saved": int,
            "cost_usd": float,
            "workers": list[WorkerState | dict],
            "log": list[ChatMessage | ToolCallEntry | dict],
            "max_log_lines": int,
        }

    The caller owns the update loop: `mount()` does not block or spin a
    thread. Typical use from cli.py (not written here — integration is a
    separate pass):

        live = mount(state)
        with live:
            while running:
                state = collect_state(...)
                live.update(render_frame(state))

    Passing `console=` lets tests/headless callers render to an in-memory
    buffer instead of a real terminal.
    """
    console = console or Console()
    return Live(render_frame(state), console=console, refresh_per_second=refresh_per_second, screen=False)


def _demo_state() -> dict:
    return {
        "model": "vincent-agent/qwen2.5-coder:3b",
        "tokens_used": 18234,
        "tokens_saved": 5120,
        "cost_usd": 0.0142,
        "workers": [
            WorkerState(id="w1", task="grep_search 'TODO' src/", status="done"),
            WorkerState(id="w2", task="run_bash pytest tests/", status="running"),
            WorkerState(id="w3", task="apply_diff cli.py", status="failed"),
        ],
        "log": [
            ChatMessage(role="user", text="roda os testes e me diz o que quebrou"),
            ToolCallEntry(name="git_status", args={}, result={"branch": "main", "dirty": True}, ok=True),
            ChatMessage(role="assistant", text="rodando pytest em background, te aviso quando sair"),
        ],
    }


if __name__ == "__main__":
    # Demo only — does not run on import. `python3 -m vincent.tui` for a
    # quick visual check against a real terminal.
    import time

    demo = _demo_state()
    live = mount(demo)
    with live:
        for i in range(5):
            demo["tokens_used"] += 137
            live.update(render_frame(demo))
            time.sleep(0.5)
