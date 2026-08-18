"""
Testes de vincent.agent.VincentAgent.spawn_workers / _run_worker_task —
N workers paralelos (ThreadPoolExecutor) com estado 100% local. Sem
LLM/rede real: model_manager.execute_inference é mockado (ver
tests/conftest.py::agent_factory).
"""

import os
import re
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import vincent.agent as agent_mod


def _task_from_messages(messages) -> str:
    """Extrai o texto da tarefa do primeiro turn_message montado por
    _run_worker_task ('...Tarefa (worker): <task>')."""
    content = messages[0]["content"]
    m = re.search(r"Tarefa \(worker\): (.*)", content, re.DOTALL)
    return m.group(1) if m else content


# ── spawn_workers: mapeamento de índice e concorrência ─────────────────────

def test_spawn_workers_maps_results_to_correct_subtask_index(agent_factory):
    subtasks = ["task-A", "task-B", "task-C"]
    delays = {"task-A": 0.15, "task-B": 0.02, "task-C": 0.08}  # termina fora de ordem: B, C, A

    def fake_execute_inference(messages, target_model, system_prompt=""):
        task = _task_from_messages(messages)
        import time
        time.sleep(delays.get(task, 0))
        return (f"resposta-para-{task}", target_model, 0.01)

    agent, _mm, _save = agent_factory(execute_inference=fake_execute_inference)

    results = agent.spawn_workers(subtasks)

    assert results == [
        "resposta-para-task-A",
        "resposta-para-task-B",
        "resposta-para-task-C",
    ]


def test_spawn_workers_run_truly_concurrently(agent_factory):
    """Prova que os N workers rodam em paralelo de verdade (não serializado):
    todos precisam alcançar a barreira ao mesmo tempo, senão time out e o
    worker captura a exceção como falha."""
    n = 4
    barrier = threading.Barrier(n, timeout=3)

    def fake_execute_inference(messages, target_model, system_prompt=""):
        barrier.wait()  # só passa se as N threads chegarem juntas
        return ("ok", target_model, 0.01)

    agent, _mm, _save = agent_factory(execute_inference=fake_execute_inference)

    results = agent.spawn_workers([f"task-{i}" for i in range(n)])

    assert results == ["ok"] * n


def test_spawn_workers_worker_exception_isolated_per_index(agent_factory):
    def fake_execute_inference(messages, target_model, system_prompt=""):
        task = _task_from_messages(messages)
        if task == "boom-task":
            raise RuntimeError("modelo caiu")
        return (f"ok-{task}", target_model, 0.01)

    agent, _mm, _save = agent_factory(execute_inference=fake_execute_inference)

    results = agent.spawn_workers(["fine-task", "boom-task", "fine-task-2"])

    assert results[0] == "ok-fine-task"
    assert results[1] == "[VINCENT WORKER 1] Falhou: modelo caiu"
    assert results[2] == "ok-fine-task-2"


def test_spawn_workers_reports_busy_then_done_per_worker(agent_factory):
    def fake_execute_inference(messages, target_model, system_prompt=""):
        return ("ok", target_model, 0.01)

    agent, _mm, _save = agent_factory(execute_inference=fake_execute_inference)

    events = []
    lock = threading.Lock()

    def on_worker_event(i, status):
        with lock:
            events.append((i, status))

    agent.spawn_workers(["a", "b", "c"], on_worker_event=on_worker_event)

    for i in range(3):
        per_worker = [status for idx, status in events if idx == i]
        assert per_worker == ["ocupado", "terminado"]


def test_spawn_workers_does_not_touch_shared_agent_state(agent_factory):
    """Docstring garante que workers não tocam self._history/self._heal_attempts."""
    def fake_execute_inference(messages, target_model, system_prompt=""):
        return ("resposta final", target_model, 0.01)

    agent, _mm, _save = agent_factory(execute_inference=fake_execute_inference)

    agent.spawn_workers(["t1", "t2"])

    assert agent._history == []
    assert not hasattr(agent, "_heal_attempts")


def test_spawn_workers_empty_subtasks_raises_valueerror(agent_factory):
    """ACHADO: spawn_workers([]) não retorna [] — ThreadPoolExecutor(max_workers=0)
    levanta ValueError. Documentado aqui, não corrigido (fora de escopo: agent.py)."""
    agent, _mm, _save = agent_factory()
    with pytest.raises(ValueError, match="max_workers must be greater than 0"):
        agent.spawn_workers([])


# ── _run_worker_task isolado ────────────────────────────────────────────

def test_run_worker_task_returns_final_response_and_saves_summary(agent_factory):
    def fake_execute_inference(messages, target_model, system_prompt=""):
        return ("resposta direta sem tool_call", target_model, 0.01)

    agent, _mm, fake_save = agent_factory(execute_inference=fake_execute_inference)

    result = agent._run_worker_task("investigar bug X")

    assert result == "resposta direta sem tool_call"
    fake_save.assert_called_once()
    saved_text = fake_save.call_args[0][0]
    assert "Tarefa (worker):" in saved_text
    assert "resposta direta sem tool_call" in saved_text


def test_run_worker_task_empty_inference_reply_returns_fallback_message(agent_factory):
    def fake_execute_inference(messages, target_model, system_prompt=""):
        return ("", target_model, 0.0)

    agent, _mm, _save = agent_factory(execute_inference=fake_execute_inference)

    result = agent._run_worker_task("tarefa qualquer")

    assert result == "[VINCENT WORKER] Limite de passos atingido sem conclusão."


def test_run_worker_task_max_turns_exhausted_with_tool_calls_returns_last_raw_reply(agent_factory, monkeypatch):
    """
    ACHADO: se o modelo emite tool_call em TODOS os turnos até max_turns
    (nunca dá uma resposta final "pura"), o loop sai normalmente do `for`
    com final_response ainda "" — e a mensagem de fallback
    "[VINCENT WORKER] Limite de passos atingido..." só é usada quando
    `reply` também está vazio. Na prática, o texto cru do último turno
    (que ainda contém o bloco ```tool_call``` não interpretado) é
    devolvido como se fosse a resposta final. Comportamento real
    documentado aqui, não corrigido (fora de escopo: agent.py).
    """
    monkeypatch.setattr(agent_mod, "execute_agent_tool", lambda name, args: {"success": True, "result": "ok"})

    tool_reply = '```tool_call\n{"tool": "list_dir", "args": {}}\n```'

    def fake_execute_inference(messages, target_model, system_prompt=""):
        return (tool_reply, target_model, 0.01)

    agent, _mm, _save = agent_factory(execute_inference=fake_execute_inference)

    result = agent._run_worker_task("investigar loop infinito", max_turns=2)

    assert result == tool_reply
    assert result != "[VINCENT WORKER] Limite de passos atingido sem conclusão."
