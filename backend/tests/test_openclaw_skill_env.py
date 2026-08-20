"""Regression coverage for OpenClaw skill HMAC environment names."""

import asyncio
import importlib.util
from pathlib import Path


def _load_sb_query(monkeypatch):
    module_path = Path(__file__).resolve().parents[2] / "openclaw-skills" / "vincent_os" / "sb_query.py"
    spec = importlib.util.spec_from_file_location("vincent_os_skill_sb_query_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_openclaw_skill_prefers_hmac_secret_env(monkeypatch):
    monkeypatch.setenv("VINCENT_HMAC_SECRET", "preferred-hmac-secret")
    monkeypatch.setenv("VINCENT_KEY", "legacy-hmac-secret")

    module = _load_sb_query(monkeypatch)

    assert module.Vincent OSClient()._hmac_secret == "preferred-hmac-secret"


def test_openclaw_skill_accepts_legacy_key_as_hmac_secret_alias(monkeypatch):
    monkeypatch.delenv("VINCENT_HMAC_SECRET", raising=False)
    monkeypatch.setenv("VINCENT_KEY", "legacy-hmac-secret")

    module = _load_sb_query(monkeypatch)
    client = module.Vincent OSClient()
    headers = client._sign_headers("GET", "/api/ai/tools")

    assert client._hmac_secret == "legacy-hmac-secret"
    assert "X-Vincent-Timestamp" in headers
    assert "X-Vincent-Nonce" in headers
    assert "X-Vincent-Signature" in headers
    assert "Authorization" not in headers
    assert "X-Admin-Key" not in headers


def test_openclaw_skill_get_fetch_health_unwraps_command_result(monkeypatch):
    module = _load_sb_query(monkeypatch)
    client = module.Vincent OSClient()
    commands = []

    async def send_command(cmd, args=None):
        commands.append((cmd, args))
        return {
            "result": {
                "ok": True,
                "data": {"scope": "process", "tasks": {}},
            }
        }

    monkeypatch.setattr(client, "send_command", send_command)

    result = asyncio.run(client.get_fetch_health())

    assert commands == [("get_fetch_health", None)]
    assert result == {"scope": "process", "tasks": {}}
