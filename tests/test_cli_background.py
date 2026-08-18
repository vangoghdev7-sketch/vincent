"""
Testes do mecanismo de /bg (tarefa em segundo plano) de src/vincent/cli.py.

_spawn_background é uma closure definida dentro de interactive_repl()
(cli.py, aprox. linhas 132-150) — não dá pra importar e chamar direto, e
cli.py está fora de escopo pra edição (sessão concorrente escrevendo nele).

Por isso este arquivo reproduz fielmente o MESMO padrão stdlib
threading+queue.Queue lido em cli.py contra um agent mockado, seguindo o
estilo de tests/test_resilience.py. Qualquer mudança no padrão real de
cli.py deve ser espelhada aqui.

Padrão original (cli.py):

    bg_results: "queue.Queue" = queue.Queue()
    bg_counter = [0]
    bg_threads: list = []

    def _spawn_background(task: str):
        bg_counter[0] += 1
        task_id = bg_counter[0]

        def _worker():
            try:
                res = agent.agentic_run(task, max_turns=6)
            except Exception as e:
                res = f"[VINCENT BG] Falhou: {e}"
            bg_results.put((task_id, task, res))

        t = threading.Thread(target=_worker, daemon=True)
        bg_threads.append(t)
        t.start()
        return task_id

E o dreno não-bloqueante feito no loop do REPL a cada iteração:

    while not bg_results.empty():
        bg_id, bg_task, bg_res = bg_results.get_nowait()
        ...
"""

import os
import queue
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import MagicMock


def make_bg_harness(agent):
    """Reprodução fiel do closure _spawn_background de cli.py."""
    bg_results: "queue.Queue" = queue.Queue()
    bg_counter = [0]
    bg_threads: list = []

    def _spawn_background(task: str):
        bg_counter[0] += 1
        task_id = bg_counter[0]

        def _worker():
            try:
                res = agent.agentic_run(task, max_turns=6)
            except Exception as e:
                res = f"[VINCENT BG] Falhou: {e}"
            bg_results.put((task_id, task, res))

        t = threading.Thread(target=_worker, daemon=True)
        bg_threads.append(t)
        t.start()
        return task_id

    return bg_results, bg_counter, bg_threads, _spawn_background


def drain(bg_results):
    """Reprodução fiel do dreno não-bloqueante feito no loop do REPL."""
    out = []
    while not bg_results.empty():
        out.append(bg_results.get_nowait())
    return out


def _join_all(bg_threads, timeout=2.0):
    for t in bg_threads:
        t.join(timeout=timeout)
        assert not t.is_alive(), "worker de background não terminou a tempo"


# ── testes ──────────────────────────────────────────────────────────────

def test_spawn_background_returns_incrementing_task_ids():
    agent = MagicMock()
    agent.agentic_run.return_value = "ok"
    bg_results, bg_counter, bg_threads, spawn = make_bg_harness(agent)

    id1 = spawn("primeira tarefa")
    id2 = spawn("segunda tarefa")

    assert (id1, id2) == (1, 2)
    _join_all(bg_threads)


def test_spawn_background_puts_result_tuple_in_queue():
    agent = MagicMock()
    agent.agentic_run.return_value = "resultado da tarefa"
    bg_results, bg_counter, bg_threads, spawn = make_bg_harness(agent)

    task_id = spawn("investigar bug")
    _join_all(bg_threads)

    got = bg_results.get(timeout=2)
    assert got == (task_id, "investigar bug", "resultado da tarefa")
    agent.agentic_run.assert_called_once_with("investigar bug", max_turns=6)


def test_spawn_background_catches_exception_and_formats_failure_message():
    agent = MagicMock()
    agent.agentic_run.side_effect = RuntimeError("modelo indisponível")
    bg_results, bg_counter, bg_threads, spawn = make_bg_harness(agent)

    spawn("tarefa que falha")
    _join_all(bg_threads)

    task_id, task, res = bg_results.get(timeout=2)
    assert task == "tarefa que falha"
    assert res == "[VINCENT BG] Falhou: modelo indisponível"


def test_spawn_background_does_not_block_the_caller():
    """Prova que /bg não trava o REPL: spawn() retorna antes do
    agent.agentic_run (mockado pra bloquear) terminar."""
    started = threading.Event()
    release = threading.Event()

    agent = MagicMock()

    def slow_run(task, max_turns=6):
        started.set()
        release.wait(timeout=2)
        return "terminou depois"

    agent.agentic_run.side_effect = slow_run
    bg_results, bg_counter, bg_threads, spawn = make_bg_harness(agent)

    task_id = spawn("tarefa lenta")

    # spawn() já retornou (id síncrono) mesmo com o worker ainda rodando
    assert task_id == 1
    assert started.wait(timeout=2), "worker nunca começou"
    assert bg_results.empty()  # ainda não terminou -> nada na fila

    release.set()
    _join_all(bg_threads)
    assert bg_results.get(timeout=2) == (1, "tarefa lenta", "terminou depois")


def test_multiple_background_tasks_all_land_in_queue_regardless_of_order():
    agent = MagicMock()
    delays = {"slow": 0.15, "fast": 0.02, "medium": 0.08}

    def run(task, max_turns=6):
        import time
        time.sleep(delays[task])
        return f"resultado-{task}"

    agent.agentic_run.side_effect = run
    bg_results, bg_counter, bg_threads, spawn = make_bg_harness(agent)

    ids = {spawn(name): name for name in ("slow", "fast", "medium")}
    _join_all(bg_threads)

    collected = drain(bg_results)
    assert len(collected) == 3
    by_id = {task_id: (task, res) for task_id, task, res in collected}
    for task_id, name in ids.items():
        task, res = by_id[task_id]
        assert task == name
        assert res == f"resultado-{name}"


def test_drain_pattern_empties_queue_and_is_idempotent():
    agent = MagicMock()
    agent.agentic_run.return_value = "ok"
    bg_results, bg_counter, bg_threads, spawn = make_bg_harness(agent)

    spawn("t1")
    spawn("t2")
    _join_all(bg_threads)

    first_drain = drain(bg_results)
    assert len(first_drain) == 2
    assert bg_results.empty()
    assert drain(bg_results) == []


def test_bg_threads_are_tracked_and_daemonized():
    agent = MagicMock()
    agent.agentic_run.return_value = "ok"
    bg_results, bg_counter, bg_threads, spawn = make_bg_harness(agent)

    spawn("t1")
    spawn("t2")
    spawn("t3")

    assert len(bg_threads) == 3
    assert all(isinstance(t, threading.Thread) for t in bg_threads)
    assert all(t.daemon for t in bg_threads)
    _join_all(bg_threads)
