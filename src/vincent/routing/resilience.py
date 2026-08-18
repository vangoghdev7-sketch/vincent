"""
Vincent CLI 4.0 — Camada de resiliência da cascata de roteamento.
Circuit breaker por provider, cooldown exponencial por conexão/chave e
lockout por modelo — padrões lidos de docs/architecture/RESILIENCE_GUIDE.md
do diegosouzapw/OmniRoute (MIT), adaptados: estado persistido em brain.db
em vez de memória do processo, porque um CLI reinicia a cada sessão — o
servidor deles é de longa duração e pode manter estado em RAM.
"""

import os
import sqlite3
import time
from enum import Enum
from typing import Optional

DB_FILE = os.path.expanduser("~/.vincent/brain.db")


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS circuit_breaker (
            provider TEXT PRIMARY KEY,
            failures INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL DEFAULT 'closed',
            opened_at REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cooldown (
            connection_id TEXT PRIMARY KEY,
            rate_limited_until REAL NOT NULL DEFAULT 0,
            backoff_level INTEGER NOT NULL DEFAULT 0,
            terminal_state TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS model_lockout (
            model_key TEXT PRIMARY KEY,
            failure_count INTEGER NOT NULL DEFAULT 0,
            locked_until REAL NOT NULL DEFAULT 0
        )
    """)
    return conn


# ─── Circuit Breaker (por provider) ────────────────────────────────────────
# RESILIENCE_GUIDE.md "Provider Circuit Breaker": 4 estados, só abre em
# códigos de infra (408/500/502/503/504) — 401/403/429 são conta/rate-limit,
# isso é cooldown, não circuito. Vincent não tem provider OAuth (removido na
# Fase 5), então as classes viram só api_key/local.

class CircuitState(str, Enum):
    CLOSED = "closed"
    DEGRADED = "degraded"
    OPEN = "open"
    HALF_OPEN = "half_open"


TRIP_CODES = {408, 500, 502, 503, 504}

# provider_class: (degrade_at, open_at, reset_timeout_sec)
THRESHOLDS = {
    "api_key": (7, 12, 30),
    "local": (2, 2, 15),
}


class CircuitBreaker:
    """Um circuito por provider (ex: 'omniroute', 'ollama'). Estado em brain.db."""

    def __init__(self, provider_class: str = "api_key"):
        self.degrade_at, self.open_at, self.reset_timeout = THRESHOLDS.get(
            provider_class, THRESHOLDS["api_key"]
        )

    def _row(self, conn, provider: str):
        row = conn.execute(
            "SELECT failures, state, opened_at FROM circuit_breaker WHERE provider = ?",
            (provider,)
        ).fetchone()
        return row or (0, CircuitState.CLOSED.value, None)

    def can_execute(self, provider: str) -> bool:
        """Recuperação preguiçosa: OPEN vira HALF_OPEN sozinho quando o timeout expira."""
        conn = _connect()
        failures, state, opened_at = self._row(conn, provider)
        if state == CircuitState.OPEN.value:
            if opened_at is not None and time.time() - opened_at >= self.reset_timeout:
                conn.execute(
                    "UPDATE circuit_breaker SET state = ? WHERE provider = ?",
                    (CircuitState.HALF_OPEN.value, provider)
                )
                conn.commit()
                conn.close()
                return True  # 1 sonda permitida
            conn.close()
            return False
        conn.close()
        return True

    def record_result(self, provider: str, success: bool, status_code: Optional[int] = None):
        if not success and status_code is not None and status_code not in TRIP_CODES:
            return  # 401/403/429 não abrem o circuito
        conn = _connect()
        failures, state, _opened_at = self._row(conn, provider)

        if success:
            conn.execute(
                "INSERT INTO circuit_breaker (provider, failures, state, opened_at) "
                "VALUES (?, 0, 'closed', NULL) "
                "ON CONFLICT(provider) DO UPDATE SET failures = 0, state = 'closed', opened_at = NULL",
                (provider,)
            )
        else:
            failures += 1
            new_state = state
            opened = _opened_at
            if failures >= self.open_at:
                new_state, opened = CircuitState.OPEN.value, time.time()
            elif failures >= self.degrade_at:
                new_state = CircuitState.DEGRADED.value
            conn.execute(
                "INSERT INTO circuit_breaker (provider, failures, state, opened_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(provider) DO UPDATE SET failures = ?, state = ?, opened_at = ?",
                (provider, failures, new_state, opened, failures, new_state, opened)
            )
        conn.commit()
        conn.close()

    def get_state(self, provider: str) -> str:
        conn = _connect()
        _, state, _ = self._row(conn, provider)
        conn.close()
        return state


# ─── Cooldown (por conexão/chave) ──────────────────────────────────────────
# RESILIENCE_GUIDE.md "Connection Cooldown": cooldownMs = base * 2^falhas,
# Retry-After do 429 tem prioridade sobre o cooldown padrão calculado.

BASE_COOLDOWN_SEC = {"oauth": 5, "api_key": 3}


class Cooldown:
    def __init__(self, connection_class: str = "api_key"):
        self.base_sec = BASE_COOLDOWN_SEC.get(connection_class, 3)

    def is_available(self, connection_id: str) -> bool:
        conn = _connect()
        row = conn.execute(
            "SELECT rate_limited_until, terminal_state FROM cooldown WHERE connection_id = ?",
            (connection_id,)
        ).fetchone()
        conn.close()
        if not row:
            return True
        rate_limited_until, terminal_state = row
        if terminal_state:
            return False
        return time.time() >= rate_limited_until

    def record_failure(self, connection_id: str, retry_after_sec: Optional[float] = None,
                        terminal: Optional[str] = None):
        conn = _connect()
        row = conn.execute(
            "SELECT backoff_level FROM cooldown WHERE connection_id = ?", (connection_id,)
        ).fetchone()
        backoff_level = (row[0] if row else 0) + 1
        cooldown_sec = retry_after_sec if retry_after_sec is not None else self.base_sec * (2 ** (backoff_level - 1))
        until = time.time() + cooldown_sec
        conn.execute(
            "INSERT INTO cooldown (connection_id, rate_limited_until, backoff_level, terminal_state) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(connection_id) DO UPDATE SET "
            "rate_limited_until = excluded.rate_limited_until, backoff_level = excluded.backoff_level, "
            "terminal_state = COALESCE(excluded.terminal_state, cooldown.terminal_state)",
            (connection_id, until, backoff_level, terminal)
        )
        conn.commit()
        conn.close()

    def record_success(self, connection_id: str):
        conn = _connect()
        conn.execute(
            "INSERT INTO cooldown (connection_id, rate_limited_until, backoff_level, terminal_state) "
            "VALUES (?, 0, 0, NULL) ON CONFLICT(connection_id) DO UPDATE SET "
            "rate_limited_until = 0, backoff_level = 0",
            (connection_id,)
        )
        conn.commit()
        conn.close()


# ─── Model Lockout (por provider+conexão+modelo) ───────────────────────────
# RESILIENCE_GUIDE.md "Model Lockout" (defaults v3.8.23): desligado por
# padrão, exponencial com decaimento por sucesso em vez de reset total.

LOCKOUT_ERROR_CODES = {403, 404, 429, 502, 503, 504}
LOCKOUT_BASE_MS = 120_000
LOCKOUT_MAX_MS = 1_800_000
LOCKOUT_MAX_STEPS = 10


class ModelLockout:
    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def is_locked(self, model_key: str) -> bool:
        if not self.enabled:
            return False
        conn = _connect()
        row = conn.execute(
            "SELECT locked_until FROM model_lockout WHERE model_key = ?", (model_key,)
        ).fetchone()
        conn.close()
        return bool(row) and time.time() < row[0]

    def record_failure(self, model_key: str, status_code: int):
        if not self.enabled or status_code not in LOCKOUT_ERROR_CODES:
            return
        conn = _connect()
        row = conn.execute(
            "SELECT failure_count FROM model_lockout WHERE model_key = ?", (model_key,)
        ).fetchone()
        failure_count = (row[0] if row else 0) + 1
        step = min(failure_count, LOCKOUT_MAX_STEPS)
        cooldown_ms = min(LOCKOUT_BASE_MS * (2 ** (step - 1)), LOCKOUT_MAX_MS)
        locked_until = time.time() + cooldown_ms / 1000
        conn.execute(
            "INSERT INTO model_lockout (model_key, failure_count, locked_until) VALUES (?, ?, ?) "
            "ON CONFLICT(model_key) DO UPDATE SET failure_count = ?, locked_until = ?",
            (model_key, failure_count, locked_until, failure_count, locked_until)
        )
        conn.commit()
        conn.close()

    def record_success(self, model_key: str):
        """Decaimento por sucesso: reduz a falha pela metade em vez de resetar na hora."""
        if not self.enabled:
            return
        conn = _connect()
        row = conn.execute(
            "SELECT failure_count FROM model_lockout WHERE model_key = ?", (model_key,)
        ).fetchone()
        if not row:
            conn.close()
            return
        new_count = row[0] // 2
        if new_count <= 0:
            conn.execute("DELETE FROM model_lockout WHERE model_key = ?", (model_key,))
        else:
            conn.execute("UPDATE model_lockout SET failure_count = ? WHERE model_key = ?", (new_count, model_key))
        conn.commit()
        conn.close()
