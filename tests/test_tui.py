"""Testes de lógica pura pro tui.py — sem LLM, sem rede, sem terminal real.

Renderiza pra um Console(file=io.StringIO()) e só confere que não explode
e que produz saída não-vazia.
"""

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rich.console import Console

from vincent import tui


def _render_to_string(renderable) -> str:
    buf = io.StringIO()
    console = Console(file=buf, width=100, force_terminal=False, no_color=True)
    console.print(renderable)
    return buf.getvalue()


def test_render_header_nonempty():
    out = _render_to_string(tui.render_header({"model": "test-model", "tokens_used": 100,
                                                "tokens_saved": 20, "cost_usd": 0.01}))
    assert out.strip()
    assert "test-model" in out


def test_render_header_missing_keys_uses_defaults():
    out = _render_to_string(tui.render_header({}))
    assert out.strip()


def test_render_workers_with_dataclasses():
    workers = [
        tui.WorkerState(id="w1", task="do a thing", status="running"),
        tui.WorkerState(id="w2", task="did a thing", status="done"),
        tui.WorkerState(id="w3", task="broke", status="failed"),
    ]
    out = _render_to_string(tui.render_workers(workers))
    assert "w1" in out and "w2" in out and "w3" in out
    assert "running" in out and "done" in out and "failed" in out


def test_render_workers_with_plain_dicts():
    workers = [{"id": "w1", "task": "plain dict worker", "status": "running"}]
    out = _render_to_string(tui.render_workers(workers))
    assert "plain dict worker" in out


def test_render_workers_empty():
    out = _render_to_string(tui.render_workers([]))
    assert "no active workers" in out


def test_render_log_chat_and_tool_entries():
    messages = [
        tui.ChatMessage(role="user", text="hello vincent"),
        tui.ToolCallEntry(name="git_status", args={"cwd": "."}, result={"dirty": False}, ok=True),
        tui.ChatMessage(role="assistant", text="all clean"),
    ]
    out = _render_to_string(tui.render_log(messages))
    assert "hello vincent" in out
    assert "ran" in out and "git_status" in out
    assert "all clean" in out


def test_render_log_tool_call_collapses_long_payload():
    big_result = {"data": "x" * 500}
    entry = tui.ToolCallEntry(name="read_file", args={}, result=big_result, ok=True)
    out = _render_to_string(tui.render_log([entry]))
    assert "collapsed" in out
    # the full 500-char blob should NOT appear verbatim (line-wrapping in
    # the panel can split "more chars" across lines, so check collapsed
    # unambiguously instead of the trailing words)
    assert "x" * 500 not in out


def test_render_log_empty():
    out = _render_to_string(tui.render_log([]))
    assert "no messages yet" in out


def test_render_log_respects_max_lines():
    messages = [tui.ChatMessage(role="user", text=f"msg {i}") for i in range(50)]
    out = _render_to_string(tui.render_log(messages, max_lines=3))
    assert "msg 49" in out
    assert "msg 0" not in out


def test_render_frame_full_state_smoke():
    state = {
        "model": "vincent-agent/qwen2.5-coder:3b",
        "tokens_used": 18234,
        "tokens_saved": 5120,
        "cost_usd": 0.0142,
        "workers": [tui.WorkerState(id="w1", task="grep_search", status="running")],
        "log": [
            tui.ChatMessage(role="user", text="oi vincent"),
            tui.ToolCallEntry(name="git_status", args={}, result={}, ok=True),
        ],
    }
    frame = tui.render_frame(state)
    out = _render_to_string(frame)
    assert out.strip()
    assert "vincent-agent" in out


def test_render_frame_empty_state_does_not_crash():
    out = _render_to_string(tui.render_frame({}))
    assert out.strip()


def test_mount_returns_live_without_blocking():
    buf = io.StringIO()
    console = Console(file=buf, width=100, force_terminal=False, no_color=True)
    live = tui.mount({"model": "m"}, console=console)
    assert live is not None
    # mount() must not start/block — confirm it's not already running
    assert live.is_started is False
