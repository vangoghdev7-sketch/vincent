"""
Fixtures compartilhados pros testes de vincent.agent. Constrói um VincentAgent
real (lógica de _escalate_for_tools/spawn_workers intacta) mas com
ModelManager, memória (SQLite) e skills mockados via monkeypatch — nenhuma
chamada de rede/LLM real, nenhuma escrita em ~/.vincent (política de teste
em CLAUDE.md).
"""

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest


@pytest.fixture
def agent_factory(monkeypatch):
    """Retorna uma função `_make(model=..., available_models=..., execute_inference=...)`
    que devolve `(agent, model_manager_mock, save_summary_mock)`."""
    import vincent.agent as agent_mod
    from vincent.devices import DeviceRegistry

    def _make(model="qwen3:0.6b", available_models=None, execute_inference=None):
        fake_mm = MagicMock(name="ModelManager")
        fake_mm.get_all_models.return_value = (
            available_models if available_models is not None else [{"id": model}]
        )
        fake_mm.resolve.side_effect = lambda x: x
        fake_mm.mask.side_effect = lambda x: x
        fake_mm.sync_catalogs.return_value = (0, 0)
        if execute_inference is not None:
            fake_mm.execute_inference.side_effect = execute_inference

        fake_save_summary = MagicMock(name="save_summary")

        monkeypatch.setattr(agent_mod, "ModelManager", lambda: fake_mm)
        monkeypatch.setattr(agent_mod, "recall_context", lambda: "")
        monkeypatch.setattr(agent_mod, "save_summary", fake_save_summary)
        monkeypatch.setattr(agent_mod, "skills_context", lambda task: "")

        registry = DeviceRegistry(lambda e: None)
        agent = agent_mod.VincentAgent(registry, model=model)
        return agent, fake_mm, fake_save_summary

    return _make
