"""
Vincent CLI 4.0 — Persistent Brain (memória de longo prazo).
Guarda resumos de sessões/tarefas complexas em SQLite local
(~/.vincent/brain.db) para o Vincent lembrar decisões de arquitetura
entre reinícios do CLI.
"""

import os
import sqlite3
import time
from typing import List

DB_FILE = os.path.expanduser("~/.vincent/brain.db")


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            summary TEXT NOT NULL
        )
    """)
    return conn


def save_summary(summary: str) -> None:
    """Persiste um resumo de sessão/tarefa complexa concluída."""
    if not isinstance(summary, str):
        return
    text = summary.strip()
    if not text:
        return
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO sessions (timestamp, summary) VALUES (?, ?)",
                (time.strftime("%Y-%m-%d %H:%M:%S"), text[:2000])
            )
    finally:
        conn.close()


def recent_summaries(limit: int = 5) -> List[str]:
    """Retorna os últimos resumos salvos, do mais antigo para o mais recente."""
    conn = _connect()
    rows = conn.execute(
        "SELECT timestamp, summary FROM sessions ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [f"[{ts}] {s}" for ts, s in reversed(rows)]


def recall_context() -> str:
    """Bloco de texto pronto para injetar no system prompt no boot do CLI."""
    items = recent_summaries()
    if not items:
        return ""
    return "\n\n## Memória de Sessões Anteriores (Contexto Persistente):\n" + "\n".join(items)


def demo():
    """ponytail self-check: valida round-trip em banco temporário isolado."""
    import tempfile
    global DB_FILE
    original = DB_FILE
    fd, DB_FILE = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(DB_FILE)
    try:
        assert recall_context() == ""
        save_summary("Implementadas GitOps tools no agent_tools.py")
        recalled = recent_summaries()
        assert len(recalled) == 1
        assert "GitOps" in recalled[0]
        assert "Memória de Sessões" in recall_context()
        print("memory.py: OK")
    finally:
        os.remove(DB_FILE)
        DB_FILE = original


if __name__ == "__main__":
    demo()
