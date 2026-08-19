"""
Testa a tool social_post (Postiz CLI) com shutil.which/subprocess mockados —
nunca chama a CLI real nem publica de verdade (política do projeto: sem
rede/processo externo de verdade em teste, só lógica pura).
"""

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import vincent.agent_tools as agent_tools
from vincent.agent_tools import execute_agent_tool, tool_social_post


def test_social_post_errors_when_postiz_cli_missing(monkeypatch):
    monkeypatch.setattr(agent_tools.shutil, "which", lambda name: None)
    result = tool_social_post(content="oi", integrations="twitter-1")
    assert "error" in result
    assert "npm install -g postiz" in result["error"]


def test_social_post_defaults_to_draft(monkeypatch):
    monkeypatch.setattr(agent_tools.shutil, "which", lambda name: "/usr/local/bin/postiz")
    fake_proc = MagicMock(returncode=0, stdout="post criado", stderr="")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return fake_proc

    monkeypatch.setattr(agent_tools.subprocess, "run", fake_run)

    result = tool_social_post(content="oi mundo", integrations="twitter-1,linkedin-2")

    assert "-t" in captured["cmd"] and "draft" in captured["cmd"]
    assert result == {"ok": True, "draft": True, "stdout": "post criado"}


def test_social_post_publish_true_skips_draft_flag(monkeypatch):
    monkeypatch.setattr(agent_tools.shutil, "which", lambda name: "/usr/local/bin/postiz")
    fake_proc = MagicMock(returncode=0, stdout="publicado", stderr="")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return fake_proc

    monkeypatch.setattr(agent_tools.subprocess, "run", fake_run)

    result = tool_social_post(content="oi", integrations="twitter-1", publish=True)

    assert "-t" not in captured["cmd"]
    assert result["draft"] is False


def test_social_post_requires_content_and_integrations():
    assert "error" in tool_social_post(content="", integrations="twitter-1")
    assert "error" in tool_social_post(content="oi", integrations="")


def test_social_post_surfaces_cli_error(monkeypatch):
    monkeypatch.setattr(agent_tools.shutil, "which", lambda name: "/usr/local/bin/postiz")
    fake_proc = MagicMock(returncode=1, stdout="", stderr="integration not found")
    monkeypatch.setattr(agent_tools.subprocess, "run", lambda cmd, **kwargs: fake_proc)

    result = tool_social_post(content="oi", integrations="bad-id")

    assert result["error"] == "integration not found"
    assert result["exit_code"] == 1


def test_execute_agent_tool_routes_social_post(monkeypatch):
    monkeypatch.setattr(agent_tools.shutil, "which", lambda name: "/usr/local/bin/postiz")
    fake_proc = MagicMock(returncode=0, stdout="ok", stderr="")
    monkeypatch.setattr(agent_tools.subprocess, "run", lambda cmd, **kwargs: fake_proc)

    result = execute_agent_tool("social_post", {"content": "oi", "integrations": "twitter-1"})

    assert result["ok"] is True
