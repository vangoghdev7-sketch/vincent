"""
Testes de lógica pura (sem LLM, sem rede) pro routing/resilience.py.
DB isolado por teste via monkeypatch de resilience.DB_FILE.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from vincent.routing import resilience


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(resilience, "DB_FILE", str(tmp_path / "test_brain.db"))
    yield


def test_circuit_breaker_starts_closed():
    cb = resilience.CircuitBreaker("api_key")
    assert cb.get_state("omniroute") == "closed"
    assert cb.can_execute("omniroute") is True


def test_circuit_breaker_ignores_non_trip_codes():
    cb = resilience.CircuitBreaker("local")  # open_at=2
    for _ in range(5):
        cb.record_result("ollama", success=False, status_code=429)  # não é trip code
    assert cb.get_state("ollama") == "closed"


def test_circuit_breaker_opens_after_threshold():
    cb = resilience.CircuitBreaker("local")  # degrade_at=2, open_at=2
    cb.record_result("ollama", success=False, status_code=503)
    cb.record_result("ollama", success=False, status_code=503)
    assert cb.get_state("ollama") == "open"
    assert cb.can_execute("ollama") is False


def test_circuit_breaker_half_open_after_timeout_then_closes_on_success():
    cb = resilience.CircuitBreaker("local")  # reset_timeout=15s
    cb.record_result("ollama", success=False, status_code=503)
    cb.record_result("ollama", success=False, status_code=503)
    assert cb.get_state("ollama") == "open"

    # simula timeout expirado escrevendo opened_at manualmente
    conn = resilience._connect()
    conn.execute("UPDATE circuit_breaker SET opened_at = ? WHERE provider = 'ollama'", (time.time() - 999,))
    conn.commit()
    conn.close()

    assert cb.can_execute("ollama") is True  # sonda permitida, virou half_open
    assert cb.get_state("ollama") == "half_open"
    cb.record_result("ollama", success=True)
    assert cb.get_state("ollama") == "closed"


def test_cooldown_exponential_backoff():
    cd = resilience.Cooldown("api_key")  # base=3s
    assert cd.is_available("key1") is True
    cd.record_failure("key1")  # backoff_level=1 -> 3 * 2^0 = 3s
    assert cd.is_available("key1") is False


def test_cooldown_respects_retry_after():
    cd = resilience.Cooldown("api_key")
    cd.record_failure("key1", retry_after_sec=0.01)
    assert cd.is_available("key1") is False
    time.sleep(0.02)
    assert cd.is_available("key1") is True


def test_cooldown_terminal_state_blocks_regardless_of_time():
    cd = resilience.Cooldown("api_key")
    cd.record_failure("key1", retry_after_sec=0.01, terminal="credits_exhausted")
    time.sleep(0.02)
    assert cd.is_available("key1") is False  # terminal ignora o tempo


def test_cooldown_success_resets_backoff():
    cd = resilience.Cooldown("api_key")
    cd.record_failure("key1")
    cd.record_success("key1")
    assert cd.is_available("key1") is True


def test_model_lockout_disabled_by_default():
    ml = resilience.ModelLockout()  # enabled=False
    ml.record_failure("gpt-4:openai", 429)
    assert ml.is_locked("gpt-4:openai") is False


def test_model_lockout_locks_on_configured_codes():
    ml = resilience.ModelLockout(enabled=True)
    ml.record_failure("gpt-4:openai", 429)
    assert ml.is_locked("gpt-4:openai") is True


def test_model_lockout_ignores_non_configured_codes():
    ml = resilience.ModelLockout(enabled=True)
    ml.record_failure("gpt-4:openai", 400)  # não está em LOCKOUT_ERROR_CODES
    assert ml.is_locked("gpt-4:openai") is False


def test_model_lockout_success_decay():
    ml = resilience.ModelLockout(enabled=True)
    for _ in range(4):
        ml.record_failure("gpt-4:openai", 503)
    conn = resilience._connect()
    count_before = conn.execute(
        "SELECT failure_count FROM model_lockout WHERE model_key = ?", ("gpt-4:openai",)
    ).fetchone()[0]
    conn.close()
    assert count_before == 4

    ml.record_success("gpt-4:openai")
    conn = resilience._connect()
    row = conn.execute(
        "SELECT failure_count FROM model_lockout WHERE model_key = ?", ("gpt-4:openai",)
    ).fetchone()
    conn.close()
    assert row[0] == 2  # 4 // 2, decaimento, não reset total
