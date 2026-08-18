"""
Testa a integração do circuit breaker dentro de ModelManager.execute_inference
com urlopen MOCKADO — nenhuma chamada de rede/LLM real, só valida que o
circuito abre e passa a pular a rota depois do limiar de falhas.
"""

import os
import sys
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from vincent import models
from vincent.routing import resilience


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(resilience, "DB_FILE", str(tmp_path / "test_brain.db"))
    yield


def test_circuit_opens_and_skips_omniroute_after_repeated_503(monkeypatch):
    mm = models.ModelManager()
    mm.cached_ollama_models = []  # força ir direto pro caminho OmniRoute

    call_count = {"n": 0}

    def fake_urlopen(req, timeout=None):
        call_count["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 503, "Service Unavailable", {}, None)

    monkeypatch.setattr(models.urllib.request, "urlopen", fake_urlopen)

    # 1a chamada: cascata tenta 6 rotas (target + 5 auto/*), todas 503 -> circuito abre em 12 falhas
    reply, used_model, dt = mm.execute_inference([{"role": "user", "content": "oi"}], target_model="auto")
    assert "ERRO NEURAL VINCENT" in reply
    first_call_attempts = call_count["n"]
    assert first_call_attempts >= 1

    # circuito ainda não abriu (open_at=12 pra api_key, cascata só tem ~5 rotas por chamada)
    state_after_first = mm._omniroute_circuit.get_state("omniroute")

    # repete até o circuito abrir de verdade
    for _ in range(5):
        mm.execute_inference([{"role": "user", "content": "oi"}], target_model="auto")
        if mm._omniroute_circuit.get_state("omniroute") == "open":
            break

    assert mm._omniroute_circuit.get_state("omniroute") == "open"

    # com o circuito aberto, execute_inference NÃO deve nem tentar chamar urlopen de novo
    calls_before = call_count["n"]
    mm.execute_inference([{"role": "user", "content": "oi"}], target_model="auto")
    assert call_count["n"] == calls_before, "circuito aberto deveria pular a tentativa de rede, mas urlopen foi chamado de novo"


def test_circuit_stays_closed_on_429_uses_cooldown_instead(monkeypatch):
    mm = models.ModelManager()
    mm.cached_ollama_models = []

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(models.urllib.request, "urlopen", fake_urlopen)

    mm.execute_inference([{"role": "user", "content": "oi"}], target_model="auto")

    # 429 nao deve abrir o circuito (nao esta em TRIP_CODES)
    assert mm._omniroute_circuit.get_state("omniroute") == "closed"
    # mas deve ter registrado cooldown
    assert mm._omniroute_cooldown.is_available("omniroute") is False
