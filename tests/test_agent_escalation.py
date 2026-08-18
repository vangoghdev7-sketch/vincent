"""
Testes de vincent.agent.VincentAgent._escalate_for_tools — escalação
transparente de modelos locais pequenos (<3B) pro modelo de tool-calling
configurado (VINCENT_ESCALATION_MODEL / ESCALATION_MODEL, default
"qwen2.5-coder:7b"). Sem LLM/rede real: ModelManager é mockado (ver
tests/conftest.py::agent_factory).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import vincent.agent as agent_mod


def test_escalates_small_local_model_to_default_escalation_model(agent_factory):
    agent, _mm, _save = agent_factory(
        model="qwen3:0.6b",
        available_models=[{"id": "qwen3:0.6b"}, {"id": "qwen2.5-coder:7b"}],
    )
    result = agent._escalate_for_tools("qwen3:0.6b")
    assert result == "qwen2.5-coder:7b"


def test_does_not_mutate_self_model(agent_factory):
    """Escalação é só-neste-turno: self.model nunca muda."""
    agent, _mm, _save = agent_factory(
        model="qwen3:0.6b",
        available_models=[{"id": "qwen3:0.6b"}, {"id": "qwen2.5-coder:7b"}],
    )
    agent._escalate_for_tools(agent.model)
    assert agent.model == "qwen3:0.6b"

    agent._escalate_for_tools(agent.model)
    agent._escalate_for_tools(agent.model)
    assert agent.model == "qwen3:0.6b"


def test_large_local_model_is_not_escalated(agent_factory):
    agent, _mm, _save = agent_factory(model="qwen2.5-coder:32b")
    result = agent._escalate_for_tools("qwen2.5-coder:32b")
    assert result == "qwen2.5-coder:32b"


def test_model_without_size_pattern_is_not_escalated(agent_factory):
    """Modelo cloud/desconhecido sem ':<N>b' no id -> não mexe (regra documentada)."""
    agent, _mm, _save = agent_factory(model="auto/coding")
    result = agent._escalate_for_tools("auto/coding")
    assert result == "auto/coding"


def test_boundary_exactly_3b_is_not_escalated(agent_factory):
    agent, _mm, _save = agent_factory(model="qwen:3b")
    result = agent._escalate_for_tools("qwen:3b")
    assert result == "qwen:3b"


def test_decimal_size_below_3b_is_escalated(agent_factory):
    agent, _mm, _save = agent_factory(
        model="phi:2.7b",
        available_models=[{"id": "phi:2.7b"}, {"id": "qwen2.5-coder:7b"}],
    )
    result = agent._escalate_for_tools("phi:2.7b")
    assert result == "qwen2.5-coder:7b"


def test_uppercase_b_suffix_is_matched_case_insensitively(agent_factory):
    agent, _mm, _save = agent_factory(
        model="qwen3:0.6B",
        available_models=[{"id": "qwen3:0.6B"}, {"id": "qwen2.5-coder:7b"}],
    )
    result = agent._escalate_for_tools("qwen3:0.6B")
    assert result == "qwen2.5-coder:7b"


def test_escalation_target_not_in_catalog_falls_back_to_original(agent_factory):
    """Se o modelo alvo de escalação não está disponível na cascata local, não escala."""
    agent, _mm, _save = agent_factory(
        model="qwen3:0.6b",
        available_models=[{"id": "qwen3:0.6b"}],  # sem qwen2.5-coder:7b disponível
    )
    result = agent._escalate_for_tools("qwen3:0.6b")
    assert result == "qwen3:0.6b"


def test_escalation_target_equal_to_source_falls_back_to_original(agent_factory, monkeypatch):
    """Se o próprio modelo de escalação configurado é pequeno e é o modelo atual,
    'escalado == model_id' evita um no-op disfarçado de escalação."""
    monkeypatch.setattr(agent_mod, "ESCALATION_MODEL", "tiny:1b")
    agent, _mm, _save = agent_factory(
        model="tiny:1b",
        available_models=[{"id": "tiny:1b"}],
    )
    result = agent._escalate_for_tools("tiny:1b")
    assert result == "tiny:1b"


def test_on_step_callback_invoked_when_escalating(agent_factory):
    agent, _mm, _save = agent_factory(
        model="qwen3:0.6b",
        available_models=[{"id": "qwen3:0.6b"}, {"id": "qwen2.5-coder:7b"}],
    )
    events = []
    result = agent._escalate_for_tools("qwen3:0.6b", on_step_callback=events.append)
    assert result == "qwen2.5-coder:7b"
    assert len(events) == 1
    assert "qwen2.5-coder:7b" in events[0]
    assert "qwen3:0.6b" in events[0]


def test_on_step_callback_not_invoked_when_not_escalating(agent_factory):
    agent, _mm, _save = agent_factory(model="qwen2.5-coder:32b")
    events = []
    result = agent._escalate_for_tools("qwen2.5-coder:32b", on_step_callback=events.append)
    assert result == "qwen2.5-coder:32b"
    assert events == []


def test_custom_escalation_model_env_var_is_respected(agent_factory, monkeypatch):
    monkeypatch.setattr(agent_mod, "ESCALATION_MODEL", "llama3:8b")
    agent, _mm, _save = agent_factory(
        model="qwen3:0.6b",
        available_models=[{"id": "qwen3:0.6b"}, {"id": "llama3:8b"}],
    )
    result = agent._escalate_for_tools("qwen3:0.6b")
    assert result == "llama3:8b"
