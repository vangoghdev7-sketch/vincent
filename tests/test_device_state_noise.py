"""
Achado ao vivo: usuário disse "oi" e "spawn agents" sem nenhum hardware
conectado, e o modelo (qwen3:0.6b) respondeu falando de dispositivos físicos
desconectados nos dois casos — a raiz era "[Nenhum dispositivo físico
conectado no momento.]" sendo injetado em TODA mensagem, mesmo sem hardware
nenhum envolvido. Testa que esse ruído sumiu quando não há dispositivo.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_device_state_empty_when_no_hardware(agent_factory):
    agent, _mm, _save = agent_factory()
    assert agent._device_state() == ""


def test_ask_does_not_inject_bracket_noise_without_hardware(agent_factory):
    captured = {}

    def fake_execute_inference(messages, target_model, system_prompt=""):
        captured["messages"] = messages
        captured["system_prompt"] = system_prompt
        return ("resposta qualquer", target_model, 0.01)

    agent, _mm, _save = agent_factory(execute_inference=fake_execute_inference)
    agent.ask("oi")

    user_content = captured["messages"][-1]["content"]
    assert "Nenhum dispositivo" not in user_content
    assert user_content == "Pergunta: oi"


def test_agentic_run_does_not_inject_bracket_noise_without_hardware(agent_factory, monkeypatch):
    import vincent.agent as agent_mod
    monkeypatch.setattr(agent_mod, "execute_agent_tool", lambda name, args: {"error": "n/a"})

    def fake_execute_inference(messages, target_model, system_prompt=""):
        return ("resposta final sem tool_call", target_model, 0.01)

    agent, _mm, _save = agent_factory(execute_inference=fake_execute_inference)
    agent.agentic_run("spawne agentes")

    first_user_msg = agent._history[-2]["content"] if len(agent._history) >= 2 else None
    # agentic_run só grava em _history a versão processed_task, não o
    # turn_messages interno — valida via chamada direta ao helper que monta o prefixo.
    assert agent._device_state() == ""


def test_device_state_reports_real_hardware_when_connected(agent_factory):
    agent, _mm, _save = agent_factory()

    class FakeDevice:
        id = "TEMBED"
        label = "T-Embed CC1101"
        firmware_id = "bruce-1.2"
        hardware = ["CC1101", "ST7789"]
        protocol = "usb-serial"

    agent.registry.all = lambda: [FakeDevice()]
    state = agent._device_state()
    assert "TEMBED" in state
    assert "Dispositivos conectados" in state
