"""
Testa as tools de computer-use (screenshot/mouse/teclado) com pyautogui
mockado — nunca chama display real (política do projeto: sem hardware/GUI
de verdade em teste, só lógica pura).
"""

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import vincent.agent_tools as agent_tools
from vincent.agent_tools import execute_agent_tool, tool_computer_action, tool_computer_screenshot


def test_computer_screenshot_calls_pyautogui(monkeypatch):
    fake_img = MagicMock(width=1920, height=1080)
    fake_pag = MagicMock()
    fake_pag.screenshot.return_value = fake_img
    monkeypatch.setattr(agent_tools, "_pyautogui", lambda: fake_pag)

    result = tool_computer_screenshot(path="/tmp/out.png")

    fake_img.save.assert_called_once_with("/tmp/out.png")
    assert result == {"path": "/tmp/out.png", "width": 1920, "height": 1080}


def test_computer_action_click_dispatches_coordinates(monkeypatch):
    fake_pag = MagicMock()
    monkeypatch.setattr(agent_tools, "_pyautogui", lambda: fake_pag)

    result = tool_computer_action(action="click", x=10, y=20, button="right")

    fake_pag.click.assert_called_once_with(x=10, y=20, button="right")
    assert result == {"ok": True, "action": "click"}


def test_computer_action_unknown_action_errors(monkeypatch):
    monkeypatch.setattr(agent_tools, "_pyautogui", lambda: MagicMock())
    result = tool_computer_action(action="fly")
    assert "error" in result


def test_computer_action_without_pyautogui_installed_errors_cleanly(monkeypatch):
    def boom():
        raise RuntimeError("Controle de tela indisponível (No module named 'pyautogui')")

    monkeypatch.setattr(agent_tools, "_pyautogui", boom)
    result = tool_computer_action(action="click", x=1, y=1)
    assert "error" in result
    assert "indisponível" in result["error"]


def test_execute_agent_tool_routes_computer_action(monkeypatch):
    fake_pag = MagicMock()
    monkeypatch.setattr(agent_tools, "_pyautogui", lambda: fake_pag)

    result = execute_agent_tool("computer_action", {"action": "type", "text": "oi"})

    fake_pag.typewrite.assert_called_once_with("oi", interval=0.02)
    assert result["ok"] is True
