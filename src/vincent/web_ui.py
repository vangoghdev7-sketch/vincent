"""
Vincent Web UI — Blueprint com as rotas NOVAS que alimentam a SPA moderna
(static/app.html): seletor de modelos, chat/modo-agente, Caveman e o
marketplace de skills.

Não substitui nada de api.py — apenas ADICIONA endpoints. O blueprint reusa o
MESMO agente/registry global que run.py injeta via api.setup(), lendo
`api._agent` / `api._registry` em tempo de request (não no import — no momento
do import o agente ainda não foi criado).

Rotas:
  GET  /api/models            → catálogo consolidado + modelo ativo
  POST /api/model    {id}     → troca o modelo ativo
  POST /api/agent/act {task}  → agentic_run (tool-calling autônomo; pode ser lento)
  POST /api/caveman  {mode}   → liga/desliga a compressão Caveman
  GET  /api/skills            → skills instaladas em ~/.vincent/skills
  POST /api/skills/install {git_url} → instala skills de um repo git
  GET  /api/marketplace       → catálogo curado de skills instaláveis
"""

import json
import queue
import threading

from flask import Blueprint, Response, jsonify, request, stream_with_context

# NOTA: 'api' é importado LAZY dentro de _require_agent() (não aqui no topo)
# para evitar import circular — api.py registra este blueprint no fim dele.
from . import marketplace
from .skills import list_skills, add_skill_from_git

bp = Blueprint("web_ui", __name__)


def _require_agent():
    """Retorna o agente global de api.py, ou (None, resposta_503) se não subiu."""
    from . import api  # lazy: evita import circular (api.py registra este bp no fim)
    agent = getattr(api, "_agent", None)
    if agent is None:
        return None, (jsonify({"error": "agente não iniciado"}), 503)
    return agent, None


# ─── Modelos ─────────────────────────────────────────────────────────────────

@bp.get("/api/models")
def list_models():
    agent, err = _require_agent()
    if err:
        return err
    try:
        models = agent.model_manager.get_all_models()
    except Exception as e:
        models = []
        return jsonify({"error": f"falha ao listar modelos: {e}", "models": [], "active": None}), 200
    active_real = agent.model
    return jsonify({
        "models": models,
        "active": active_real,
        "active_display": agent.display_model,
    })


@bp.post("/api/model")
def set_model():
    agent, err = _require_agent()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    model_id = (body.get("id") or "").strip()
    if not model_id:
        return jsonify({"error": "campo 'id' obrigatório"}), 400
    agent.set_model(model_id)
    return jsonify({
        "active": agent.model,
        "active_display": agent.display_model,
    })


# ─── Modo Agente (agentic loop) ──────────────────────────────────────────────

@bp.post("/api/agent/act")
def agent_act():
    agent, err = _require_agent()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    task = (body.get("task") or "").strip()
    if not task:
        return jsonify({"error": "campo 'task' obrigatório"}), 400
    # O loop emite o preview de diff das edições no trace (`ui.diff_lines`).
    # No navegador não dá pra perguntar de forma síncrona, mas devolver o diff
    # junto da resposta é o mínimo pro usuário ver o que foi escrito nos
    # arquivos dele em vez de só ler "pronto, ajustei".
    trace: list = []
    try:
        answer = agent.agentic_run(task, on_step_callback=trace.append)
    except Exception as e:
        return jsonify({"error": f"falha no modo agente: {e}"}), 500
    diff = [line for line in trace if str(line)[:2] in ("◆ ", "@@", "+ ", "- ", "· ")]
    return jsonify({"answer": answer, "diff": diff})


# ─── Chat com Streaming ao vivo (Server-Sent Events) ─────────────────────────
#
# Espelha o comportamento de agent.ask() — compressão Caveman, histórico curto,
# telemetria e execução de comandos de hardware — mas entrega a resposta token a
# token via SSE. A inferência roda numa thread separada com um stream_callback
# que empurra pedaços numa fila; o gerador Flask drena a fila e emite os frames
# `data: {...}\n\n`. Ollama local streama de verdade; rotas OmniRoute chegam de
# uma vez só (o callback ainda é chamado com o texto inteiro no final).

def _sse(event: str, payload: dict) -> str:
    """Formata um frame Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _run_stream(agent, question: str):
    """Gerador que executa a inferência e emite tokens como SSE."""
    # Importações locais: os módulos internos do agente não são públicos, então
    # pegamos as mesmas peças que ask() usa, com fallback tolerante.
    try:
        from .agent import SYSTEM_CHAT
    except Exception:
        SYSTEM_CHAT = ""
    try:
        from .caveman import CavemanEngine
    except Exception:
        CavemanEngine = None
    try:
        from .skills import skills_context
    except Exception:
        skills_context = lambda q: ""  # noqa: E731

    q: "queue.Queue" = queue.Queue()
    _DONE = object()
    result = {"reply": None, "used_model": None, "error": None}

    # Pré-processa igual ao ask(): Caveman + estado de hardware + histórico.
    try:
        processed_prompt, _ = agent.caveman.compress_prompt(question)
    except Exception:
        processed_prompt = question
    try:
        state = agent._device_state()
    except Exception:
        state = ""
    hw_prefix = f"[{state}]\n" if state else ""
    user_content = f"{hw_prefix}Pergunta: {processed_prompt}"

    history = list(getattr(agent, "_history", []) or [])
    if len(history) >= 6:
        history = history[-5:]
    messages_to_send = history + [{"role": "user", "content": user_content}]

    try:
        system_prompt = (
            SYSTEM_CHAT
            + agent.plugins.system_prompt_addon()
            + getattr(agent, "_memory_context", "")
            + skills_context(question)
        )
    except Exception:
        system_prompt = SYSTEM_CHAT

    def _worker():
        def _cb(piece: str):
            if piece:
                q.put(piece)
        try:
            reply, used_model, latency = agent.model_manager.execute_inference(
                messages_to_send,
                target_model=agent.model,
                system_prompt=system_prompt,
                stream_callback=_cb,
            )
            result["reply"] = reply
            result["used_model"] = used_model
            result["latency"] = latency
        except Exception as e:  # noqa: BLE001
            result["error"] = str(e)
        finally:
            q.put(_DONE)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    yield _sse("start", {"model": agent.display_model})

    streamed = []
    while True:
        piece = q.get()
        if piece is _DONE:
            break
        streamed.append(piece)
        yield _sse("token", {"t": piece})

    t.join(timeout=1.0)

    if result["error"]:
        yield _sse("error", {"error": result["error"]})
        return

    reply = result["reply"] or "".join(streamed)
    if not reply:
        yield _sse("error", {"error": "Resposta vazia dos nós neurais."})
        return

    # Efeitos colaterais idênticos ao ask(): telemetria, histórico e comandos.
    try:
        if CavemanEngine is not None:
            in_toks = CavemanEngine.estimate_tokens(user_content)
            out_toks = CavemanEngine.estimate_tokens(reply)
            agent.telemetry.record_query(result.get("latency", 0.0), in_toks, out_toks)
    except Exception:
        pass
    try:
        agent._history.append({"role": "user", "content": processed_prompt})
        agent._history.append({"role": "assistant", "content": reply})
    except Exception:
        pass
    try:
        agent._execute_commands(reply)
    except Exception:
        pass

    yield _sse("done", {"full": reply, "model": result.get("used_model") or agent.display_model})


@bp.route("/api/agent/stream", methods=["GET", "POST"])
def agent_stream():
    agent, err = _require_agent()
    if err:
        # Precisa emitir SSE mesmo no erro pra o EventSource não estourar feio.
        msg = "agente não iniciado"
        return Response(_sse("error", {"error": msg}), mimetype="text/event-stream", status=503)

    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        question = (body.get("question") or body.get("q") or "").strip()
    else:
        question = (request.args.get("q") or request.args.get("question") or "").strip()

    if not question:
        return Response(_sse("error", {"error": "campo 'q' obrigatório"}),
                        mimetype="text/event-stream", status=400)

    headers = {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return Response(stream_with_context(_run_stream(agent, question)), headers=headers)


# ─── Caveman ─────────────────────────────────────────────────────────────────

@bp.post("/api/caveman")
def set_caveman():
    agent, err = _require_agent()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    mode = (body.get("mode") or "").strip()
    if not mode:
        return jsonify({"error": "campo 'mode' obrigatório"}), 400
    ok = agent.set_caveman_mode(mode)
    if not ok:
        return jsonify({
            "error": f"modo inválido: {mode}",
            "valid_modes": agent.caveman.INTENSITY_LEVELS,
        }), 400
    return jsonify({"mode": agent.caveman.mode})


# ─── Skills ──────────────────────────────────────────────────────────────────

@bp.get("/api/skills")
def get_skills():
    try:
        skills = list_skills()
    except Exception as e:
        return jsonify({"error": f"falha ao listar skills: {e}", "skills": []}), 200
    return jsonify({"skills": skills, "count": len(skills)})


@bp.post("/api/skills/install")
def install_skill():
    body = request.get_json(silent=True) or {}
    git_url = (body.get("git_url") or "").strip()
    if not git_url:
        return jsonify({"error": "campo 'git_url' obrigatório"}), 400
    try:
        installed = add_skill_from_git(git_url)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    if not installed:
        return jsonify({
            "installed": [],
            "warning": "nenhuma skill encontrada no repositório (esperado skills/<nome>/SKILL.md ou SKILL.md na raiz).",
        }), 200
    return jsonify({"installed": installed, "count": len(installed)})


@bp.get("/api/marketplace")
def get_marketplace():
    """Catálogo curado vindo de marketplace.py (fonte única, compartilhada com
    o CLI). O shape da resposta é o mesmo de antes — a SPA lê name/description/
    git_url/category; tags[0] é a categoria."""
    skills_out = [
        {
            "name": item["name"],
            "description": item["desc"],
            "git_url": item["source"],
            "category": (item["tags"] or ["skill"])[0],
        }
        for item in marketplace.catalog()
    ]
    return jsonify({"skills": skills_out, "count": len(skills_out)})
