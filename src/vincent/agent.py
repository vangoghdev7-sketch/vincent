"""
Vincent Agent — Núcleo de Inteligência Unificada ESP32 & Orquestrador de LLMs.
Executa em nome do Vincent com suporte a mais de 1200 rotas neurais próprias,
modelos locais de alta velocidade, Caveman Compression e Agentic Loop com Tool Calling.
Motor único e generalista.
"""

import json
import os
import re
import threading
import time
from typing import Optional, List, Dict, Any, Callable

from .config import DEVICES, CAPABILITIES
from .devices import DeviceRegistry, DeviceEvent
from .plugins import PluginManager
from .models import ModelManager, DEFAULT_MODEL
from .caveman import CavemanEngine
from .telemetry import PonytailTelemetry
from .agent_tools import execute_agent_tool, TOOL_DEFINITIONS
from .memory import recall_context, save_summary
from .skills import skills_context

ESCALATION_MODEL = os.environ.get("VINCENT_ESCALATION_MODEL", "qwen2.5-coder:7b")

# Teto de passos do loop agêntico. 6 era baixo demais e cortava tarefas no meio;
# o loop JÁ para sozinho quando a tarefa termina (modelo para de pedir ferramenta),
# então isto é só uma trava de segurança contra runaway. Configurável via env.
MAX_TURNS = int(os.environ.get("VINCENT_MAX_TURNS", "25"))

OBSIDIAN_VAULT_CANDIDATES = [
    os.environ.get("VINCENT_OBSIDIAN_VAULT", ""),
    os.path.expanduser("~/Documents/Obsidian Vault"),
]


def _detect_obsidian_vault() -> str:
    """Detecta um vault Obsidian local (override via VINCENT_OBSIDIAN_VAULT, senão path padrão)."""
    for path in OBSIDIAN_VAULT_CANDIDATES:
        if path and os.path.isdir(path):
            return path
    return ""


SYSTEM_BASE = """Você é o Vincent — assistente de engenharia de software e conversação técnica geral.
Você conversa normalmente, responde perguntas, escreve e investiga código, e — quando (e somente quando) for pedido ou houver uma placa conectada — também controla hardware ESP32.
Para um cumprimento ou pergunta comum, responda de forma natural e direta, SEM mencionar hardware, placas ou dispositivos.

## MODO AGENTE — VOCÊ EXECUTA, NÃO EXPLICA:
Você é um agente autônomo. Quando a tarefa exige uma informação do sistema, um arquivo ou o resultado de um comando, VOCÊ MESMO executa a ferramenta — NUNCA peça pro usuário rodar nada, NUNCA responda "rode este comando e me diga o resultado". Aja.

Para executar, emita EXATAMENTE um bloco assim (e nada além dele nesse turno), com JSON válido:

```tool_call
{"tool": "<nome_da_ferramenta>", "args": { ... }}
```

Exemplo — descobrir a versão do kernel (VOCÊ executa, não pede ao usuário):

```tool_call
{"tool": "run_bash", "args": {"command": "uname -r"}}
```

Depois que eu te devolver o [RESULTADO DA FERRAMENTA], aí sim você responde ao usuário em linguagem natural com a informação obtida. Enquanto precisar de dados, continue emitindo tool_calls (um por turno).

Ferramentas suportadas:
1. `list_dir`: {"path": ".", "max_depth": 2}
2. `read_file`: {"path": "caminho/do/arquivo", "start_line": 1, "end_line": 50}
3. `grep_search`: {"pattern": "termo_de_busca", "path": ".", "is_regex": false}
4. `run_bash`: {"command": "comando_de_terminal"}
5. `apply_diff`: {"path": "arquivo", "search_block": "código_antigo", "replace_block": "código_novo"}
6. `git_status`: {}
7. `git_diff`: {"path": "opcional"}
8. `git_commit`: {"message": "feat(core): descrição", "paths": ["opcional"]}
9. `git_rollback`: {"path": "arquivo_a_reverter"}
10. `web_search`: {"query": "termo de busca"}
11. `fetch_url`: {"url": "https://..."}

## Regras de GitOps:
- Antes de aplicar um `apply_diff` arriscado, confira `git_status`/`git_diff` primeiro.
- Depois de validar uma mudança (lint/teste passou), use `git_commit` como checkpoint.
- `git_rollback` exige um `path` explícito — nunca reverte o repositório inteiro de uma vez.
- Todo `apply_diff` em arquivo `.py` é auto-validado (checagem de sintaxe). Se quebrar, o próprio
  sistema restaura a versão anterior automaticamente — você não precisa (e não deve) usar `git_rollback`
  pra isso, ele é só pra correções manuais fora do loop.

## Regra de Pesquisa:
- Se a tarefa envolve lib, API ou hardware que você não tem certeza, use `web_search`/`fetch_url`
  pra checar documentação oficial ANTES de propor código. Se `web_search` vier bloqueado, tente
  `fetch_url` direto numa URL de documentação conhecida.

## Hardware (USE SÓ QUANDO RELEVANTE):
Ignore esta seção inteira a menos que o usuário fale explicitamente de placa/hardware OU haja um dispositivo listado como conectado no contexto da mensagem. Nunca traga hardware à tona por conta própria.
1. TEMBED — LilyGo T-Embed CC1101 (ESP32-S3, Sub-GHz RF 433/868/915 MHz, IR TX/RX, WiFi, BLE, Display ST7789, Bruce shell).
2. ESP32DIV — ESP32-S3 DIV Kilaz v2 (3x NRF24L01 2.4GHz, Sub-GHz CC1101, Display ILI9341 Touch, SD Card, PCF8574).
Para interagir com as placas (só se conectadas), emita: CMD:TEMBED: <comando> ou CMD:ESP32DIV: <comando>.

## Regras de Atuação:
- Seja assertivo, técnico, objetivo, direto e inteligente.
- Sempre que solicitado a resolver um bug ou investigar o código, use `grep_search` e `read_file` antes de propor a solução.
- Ao propor correções em arquivos existentes, use `apply_diff` com search_block exato para modificações cirúrgicas.
- Responda em Português do Brasil.
"""


# System prompt enxuto para CHAT normal (VincentAgent.ask). O SYSTEM_BASE
# completo — com JSON de tool-calling e o manual de hardware — é pesado demais
# e domina modelos locais pequenos (ex.: qwen3:0.6b passa a responder sobre
# ESP32 até num "ola"). Para conversa direta basta a identidade + regras.
# Os loops agênticos (agentic_run / _run_worker_task) continuam usando SYSTEM_BASE.
SYSTEM_CHAT = """Você é o Vincent, um assistente técnico que responde em Português do Brasil.
Converse de forma natural, direta, objetiva e inteligente. Responda exatamente o que o usuário perguntou.
Você entende de programação, engenharia de software e sistemas. Só fale de hardware, placas ou ESP32 se o usuário perguntar isso explicitamente — nunca traga o assunto por conta própria."""


class VincentAgent:
    def __init__(self, registry: DeviceRegistry, emit_fn=None, model: str = DEFAULT_MODEL):
        self.registry = registry
        self.emit = emit_fn or (lambda e, d: None)
        self._history: List[Dict] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Módulos Integrados
        self.model_manager = ModelManager()
        self.caveman = CavemanEngine(mode="off")
        self.telemetry = PonytailTelemetry()
        self.plugins = PluginManager()
        # Features estilo Claude Code:
        self.autoedit = True              # False = pergunta antes de rodar comando/editar
        self.permission_callback = None   # callable(tool_name, args)->bool, setado pelo REPL
        self._obsidian_vault = _detect_obsidian_vault()
        vault_note = (
            f"\n\n## Segundo Cérebro (Obsidian):\nVault Markdown disponível em: {self._obsidian_vault}\n"
            f"Use list_dir/grep_search/read_file nesse caminho pra consultar as notas técnicas quando relevante."
        ) if self._obsidian_vault else ""
        self._memory_context = recall_context() + vault_note

        # Sincronização inicial de catálogo (best-effort — se a rede ou o
        # serviço de modelos estiver indisponível, o Vincent ainda deve subir
        # usando o catálogo local/cache em vez de crashar no __init__).
        try:
            self.model_manager.sync_catalogs()
            self.model_manager.get_all_models()
        except Exception as e:
            self.emit("error", {"message": f"Falha ao sincronizar catálogo de modelos: {e}"})
        self.model = self.model_manager.resolve(model)

    @property
    def display_model(self) -> str:
        """Nome do modelo ativo mascarado sob a marca Vincent."""
        return self.model_manager.mask(self.model)

    def set_model(self, new_model: str):
        self.model = self.model_manager.resolve(new_model)

    def set_caveman_mode(self, mode: str) -> bool:
        return self.caveman.set_mode(mode)

    def _escalate_for_tools(self, model_id: str, on_step_callback: Optional[Callable[[str], None]] = None) -> str:
        """
        Modelos locais muito pequenos (<3B) nem sempre emitem o bloco
        tool_call de forma confiavel — so descrevem o que fariam. Escala
        SO NESTE TURNO pra um modelo melhor da cascata local, sem mudar
        self.model (a troca e transparente, nao "gruda").
        ponytail: threshold e alvo fixos (3B / qwen2.5-coder:7b); virar
        cascata configuravel se a lista de modelos locais mudar muito.
        """
        m = re.search(r":(\d+(?:\.\d+)?)b\b", model_id.lower())
        if not m or float(m.group(1)) >= 3:
            return model_id  # cloud/desconhecido/já grande — não mexe

        escalated = ESCALATION_MODEL
        available = {mm["id"] for mm in self.model_manager.get_all_models()}
        if escalated not in available or escalated == model_id:
            return model_id

        if on_step_callback:
            on_step_callback(f"⚡ escalado para {escalated} (tool-calling — {model_id} é pequeno demais pra chamar ferramenta com confiança)")
        return escalated

    def ask(self, question: str, model_override: str | None = None) -> str:
        """Execução direta padrão com compressão Caveman e comandos de hardware."""
        target_m = model_override or self.model
        processed_prompt, _ = self.caveman.compress_prompt(question)
        
        state = self._device_state()
        hw_prefix = f"[{state}]\n" if state else ""
        user_content = f"{hw_prefix}Pergunta: {processed_prompt}"
        
        if len(self._history) >= 6:
            self._history = self._history[-4:]  # par completo (user+assistant), evita órfão de role

        messages_to_send = self._history + [{"role": "user", "content": user_content}]

        try:
            reply, used_model, latency = self.model_manager.execute_inference(
                messages_to_send,
                target_model=target_m,
                system_prompt=SYSTEM_CHAT + self.plugins.system_prompt_addon() + self._memory_context + skills_context(question)
            )
        except Exception as e:
            return f"[VINCENT] Falha de comunicação com os nós neurais: {e}"

        in_toks = CavemanEngine.estimate_tokens(user_content)
        out_toks = CavemanEngine.estimate_tokens(reply or "")
        self.telemetry.record_query(latency, in_toks, out_toks)

        if reply:
            self._history.append({"role": "user", "content": processed_prompt})
            self._history.append({"role": "assistant", "content": reply})
            self._execute_commands(reply)
            # NÃO salvamos chat trivial na memória de longo prazo (brain.db):
            # o recall_context() reinjeta essas respostas no system prompt do
            # próximo boot, e modelos pequenos copiam a última resposta ao pé da
            # letra — criava um loop de autoenvenenamento. A memória persistente
            # fica reservada para os loops agênticos (tarefas complexas de fato).
            return reply
        
        return "[VINCENT] Resposta vazia ou falha de comunicação com os nós neurais."

    def agentic_run(self, task: str, on_step_callback: Optional[Callable[[str], None]] = None, max_turns: int = MAX_TURNS,
                    stream_callback: Optional[Callable[[str], None]] = None) -> str:
        """
        Agentic Loop com Function/Tool Calling autônomo e auto-cura.
        Investiga o código, executa ferramentas, inspeciona resultados e sintetiza a solução.

        `stream_callback` (opcional): recebe pedaços da resposta em tempo real. É
        puramente cosmético — o parsing de tool_call sempre usa o texto COMPLETO
        retornado por execute_inference, nunca o stream. Para não vazar JSON de
        tool_call na tela, o stream é filtrado: pára de repassar pedaços assim que
        o texto do turno começa a parecer um bloco tool_call (```/{"tool").
        """
        def _guarded_stream():
            """Fábrica de callback por-turno: só repassa enquanto não vira tool_call."""
            if not stream_callback:
                return None
            buf = {"txt": "", "muted": False}

            def _cb(piece: str):
                if buf["muted"]:
                    return
                buf["txt"] += piece
                # Heurística barata: se o acumulado do turno começar a formar um
                # bloco de ferramenta, silencia o resto (o texto retornado ainda
                # é parseado normalmente lá embaixo — isto é só visual).
                low = buf["txt"].lstrip()
                if low.startswith("```") or '"tool"' in buf["txt"] or "tool_call" in buf["txt"]:
                    buf["muted"] = True
                    return
                stream_callback(piece)

            return _cb
        target_m = self._escalate_for_tools(self.model, on_step_callback)
        processed_task, _ = self.caveman.compress_prompt(task)
        state = self._device_state()
        self._heal_attempts: Dict[str, int] = {}
        skills_ctx = skills_context(task)

        hw_prefix = f"[{state}]\n" if state else ""
        turn_messages: List[Dict[str, str]] = [
            {"role": "user", "content": f"{hw_prefix}Tarefa Agênica: {processed_task}\n\nExecute você mesmo as ferramentas necessárias (emita um bloco ```tool_call). NÃO peça para eu rodar comandos."}
        ]

        total_latency = 0.0
        final_response = ""
        last_sig = None   # assinatura da última tool_call — detecta repetição improdutiva

        for turn in range(max_turns):
            if on_step_callback:
                on_step_callback(f"🧠 Passo {turn + 1}/{max_turns} — pensando…")

            try:
                reply, used_model, lat = self.model_manager.execute_inference(
                    turn_messages,
                    target_model=target_m,
                    system_prompt=SYSTEM_BASE + self.plugins.system_prompt_addon() + self._memory_context + skills_ctx,
                    stream_callback=_guarded_stream()
                )
            except Exception as e:
                final_response = f"[VINCENT] Falha de comunicação com os nós neurais: {e}"
                break
            total_latency += lat

            if not reply:
                break

            # Verifica se o modelo emitiu uma chamada de ferramenta
            tool_call = self._extract_tool_call(reply)
            if not tool_call:
                # Não há mais ferramentas a chamar: loop concluído
                final_response = self._strip_tool_call(reply)
                break

            tool_name = tool_call.get("tool", "")
            tool_args = tool_call.get("args") or {}

            # Detecta repetição EXATA da mesma chamada (loop improdutivo do modelo)
            sig = f"{tool_name.strip().lower()}::{json.dumps(tool_args, sort_keys=True, ensure_ascii=False)}"
            repeated = (sig == last_sig)
            last_sig = sig

            if on_step_callback:
                # Mostra o QUE vai executar (comando/caminho/query), estilo Claude Code
                arg_preview = (
                    tool_args.get("command") or tool_args.get("path") or tool_args.get("pattern")
                    or tool_args.get("query") or tool_args.get("url") or tool_args.get("message") or ""
                )
                arg_preview = str(arg_preview).replace("\n", " ")[:120]
                on_step_callback(f"⚙️  {tool_name}  ›  {arg_preview}" if arg_preview else f"⚙️  {tool_name}")

            # Snapshot em memória ANTES do patch, para auto-cura poder desfazer só
            # a mudança deste loop (git_rollback voltaria pro último commit, o que
            # apagaria também qualquer edição não commitada fora deste loop).
            pre_patch_snapshot = None
            patch_path = tool_args.get("path", "")
            if tool_name.strip().lower() in ("apply_diff", "patch", "replace") and patch_path:
                abs_patch_path = os.path.abspath(os.path.expanduser(patch_path))
                if os.path.isfile(abs_patch_path):
                    try:
                        with open(abs_patch_path, "r", encoding="utf-8") as f:
                            pre_patch_snapshot = f.read()
                    except Exception:
                        pre_patch_snapshot = None

            # Permission prompt (estilo Claude Code): se autoedit=off, pergunta antes de
            # rodar comando/editar/commitar. Só em ferramentas que MODIFICAM o sistema.
            _mutating = tool_name.strip().lower() in ("run_bash", "bash", "exec", "apply_diff",
                                                      "patch", "replace", "git_commit", "git_rollback")
            if (not self.autoedit) and self.permission_callback and _mutating \
                    and not self.permission_callback(tool_name, tool_args):
                tool_result = {"success": False, "error": "Execução negada pelo usuário.", "denied": True}
            else:
                # Executa ferramenta real no workspace
                try:
                    tool_result = execute_agent_tool(tool_name, tool_args)
                except Exception as e:
                    tool_result = {"success": False, "error": f"Exceção não tratada na ferramenta: {e}"}

            if pre_patch_snapshot is not None and tool_result.get("success"):
                tool_result["auto_heal"] = self._auto_heal_check(
                    patch_path, pre_patch_snapshot, on_step_callback
                )

            # Auto-cura: Detecta erros de execução e injeta alerta no contexto
            is_error = bool(tool_result.get("error")) or (tool_result.get("exit_code", 0) != 0)
            prefix = "[AUTO-CURA: ERRO NA FERRAMENTA]" if is_error else "[RESULTADO DA FERRAMENTA]"

            if on_step_callback:
                # Mostra a SAÍDA da ferramenta ao vivo (preview), estilo Claude Code
                if is_error:
                    out_preview = str(tool_result.get("error") or tool_result.get("stderr") or "erro")
                    on_step_callback(f"   ↳ ⚠️  {out_preview.replace(chr(10), ' ')[:160]}")
                elif "results" in tool_result:
                    # web_search: mostra quantos achou + 1º título (antes só dizia "ok")
                    res = tool_result.get("results") or []
                    n = tool_result.get("total_results", len(res))
                    first_t = (res[0].get("title", "") if res else "")
                    out_preview = f"{n} resultado(s)" + (f" — {first_t}" if first_t else " (nenhum — busca sem retorno útil)")
                    on_step_callback(f"   ↳ {out_preview.replace(chr(10), ' ')[:160]}")
                else:
                    out_preview = str(
                        tool_result.get("stdout") or tool_result.get("content")
                        or tool_result.get("result") or tool_result.get("output") or "ok"
                    )
                    on_step_callback(f"   ↳ {out_preview.replace(chr(10), ' ')[:160]}")

            turn_messages.append({"role": "assistant", "content": reply})
            result_json = json.dumps(tool_result, ensure_ascii=False, indent=2)
            if repeated:
                followup = (
                    f"{prefix} {tool_name}:\n{result_json}\n\n"
                    "⚠️ Você repetiu EXATAMENTE a mesma chamada de ferramenta. NÃO repita de novo. "
                    "Com base no que já obteve, escreva AGORA a resposta final ao usuário em texto natural, SEM emitir tool_call."
                )
            else:
                followup = (
                    f"{prefix} {tool_name}:\n{result_json}\n\n"
                    "Analise o resultado. Se ainda precisa de dados, emita a PRÓXIMA tool_call (diferente da anterior). "
                    "Se já tem o suficiente, escreva a resposta final ao usuário SEM tool_call."
                )
            turn_messages.append({"role": "user", "content": followup})
            time.sleep(0.1)

        # Esgotou os passos ainda emitindo tool_calls: força uma SÍNTESE limpa em
        # vez de devolver o último bloco tool_call cru (que aparecia feio na tela).
        if not final_response:
            if on_step_callback:
                on_step_callback("🧾 Sintetizando resposta final…")
            synth_msgs = turn_messages + [{
                "role": "user",
                "content": ("PARE de usar ferramentas. Com base em tudo que você executou e observou acima, "
                            "escreva AGORA a resposta final ao usuário, em português, clara e direta. NÃO emita tool_call."),
            }]
            synth_reply, _, lat2 = self.model_manager.execute_inference(
                synth_msgs, target_model=target_m,
                system_prompt=SYSTEM_BASE + self.plugins.system_prompt_addon() + self._memory_context + skills_ctx,
                stream_callback=_guarded_stream()
            )
            total_latency += lat2
            final_response = self._strip_tool_call(synth_reply) or \
                "[VINCENT] Executei os passos acima, mas não consegui fechar uma resposta final clara. Veja o trace."

        in_toks = CavemanEngine.estimate_tokens(processed_task)
        out_toks = CavemanEngine.estimate_tokens(final_response or "")
        self.telemetry.record_query(total_latency, in_toks, out_toks)

        self._history.append({"role": "user", "content": processed_task})
        self._history.append({"role": "assistant", "content": final_response})
        self._execute_commands(final_response)
        save_summary(f"Tarefa: {processed_task}\nResultado: {final_response[:500]}")
        return final_response

    def spawn_workers(self, subtasks: List[str], on_worker_event: Optional[Callable[[int, str], None]] = None) -> List[str]:
        """
        N workers genéricos rodando em paralelo (ThreadPoolExecutor — as
        chamadas são I/O-bound, então threads bastam, sem asyncio). Motor
        único: cada worker é o MESMO loop de tool-calling, só que com
        estado 100% local (sem tocar self._history/self._heal_attempts),
        pra não correr com o agente principal nem entre si.
        ponytail: sem auto-heal por worker (isso é só pra apply_diff
        arriscado no loop principal) — adicionar se workers começarem a
        aplicar patch e quebrar sem chance de restaurar.
        """
        if not subtasks:
            return []

        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _worker(i: int, task: str) -> str:
            if on_worker_event:
                on_worker_event(i, "ocupado")
            try:
                result = self._run_worker_task(task)
            except Exception as e:
                result = f"[VINCENT WORKER {i}] Falhou: {e}"
            if on_worker_event:
                on_worker_event(i, "terminado")
            return result

        results = [""] * len(subtasks)
        with ThreadPoolExecutor(max_workers=len(subtasks)) as pool:
            futures = {pool.submit(_worker, i, t): i for i, t in enumerate(subtasks)}
            for fut in as_completed(futures):
                results[futures[fut]] = fut.result()
        return results

    def _run_worker_task(self, task: str, max_turns: int = MAX_TURNS) -> str:
        """Mesmo loop de tool-calling do agentic_run, mas com estado 100%
        local — seguro pra chamar de várias threads ao mesmo tempo."""
        target_m = self._escalate_for_tools(self.model)
        processed_task, _ = self.caveman.compress_prompt(task)
        state = self._device_state()
        heal_attempts: Dict[str, int] = {}
        skills_ctx = skills_context(task)

        hw_prefix = f"[{state}]\n" if state else ""
        turn_messages: List[Dict[str, str]] = [
            {"role": "user", "content": f"{hw_prefix}Tarefa (worker): {processed_task}\n\nExecute você mesmo as ferramentas necessárias (emita um bloco ```tool_call). NÃO peça para eu rodar comandos."}
        ]
        final_response = ""
        reply = ""

        for _ in range(max_turns):
            reply, _used_model, _lat = self.model_manager.execute_inference(
                turn_messages,
                target_model=target_m,
                system_prompt=SYSTEM_BASE + self.plugins.system_prompt_addon() + self._memory_context + skills_ctx
            )
            if not reply:
                break
            tool_call = self._extract_tool_call(reply)
            if not tool_call:
                final_response = self._strip_tool_call(reply)
                break

            tool_name = tool_call.get("tool", "")
            tool_args = tool_call.get("args") or {}
            try:
                tool_result = execute_agent_tool(tool_name, tool_args)
            except Exception as e:
                tool_result = {"success": False, "error": f"Exceção não tratada na ferramenta: {e}"}
            is_error = bool(tool_result.get("error")) or (tool_result.get("exit_code", 0) != 0)
            prefix = "[AUTO-CURA: ERRO NA FERRAMENTA]" if is_error else "[RESULTADO DA FERRAMENTA]"
            turn_messages.append({"role": "assistant", "content": reply})
            turn_messages.append({
                "role": "user",
                "content": f"{prefix} {tool_name}:\n{json.dumps(tool_result, ensure_ascii=False, indent=2)}\n\nContinue ou finalize."
            })

        final_response = final_response or self._strip_tool_call(reply) or "[VINCENT WORKER] Limite de passos atingido sem conclusão."
        save_summary(f"Tarefa (worker): {processed_task}\nResultado: {final_response[:500]}")
        return final_response

    def _auto_heal_check(
        self, path: str, pre_patch_snapshot: str, on_step_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """
        Roda checagem de sintaxe pós-patch (só .py por enquanto). Se quebrar,
        restaura o snapshot de ANTES do patch (não usa git — preserva qualquer
        mudança não commitada fora deste loop). Máx 3 tentativas por arquivo
        por execução de agentic_run.
        """
        if not path.endswith(".py"):
            return {"syntax_check": "skipped", "reason": "só .py é validado por enquanto"}

        abs_path = os.path.abspath(os.path.expanduser(path))
        check = execute_agent_tool("run_bash", {"command": f'python3 -m py_compile "{abs_path}"'})
        if check.get("exit_code") == 0:
            return {"syntax_check": "ok"}

        attempts = self._heal_attempts.get(path, 0) + 1
        self._heal_attempts[path] = attempts

        try:
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(pre_patch_snapshot)
            restored = True
        except Exception:
            restored = False

        if on_step_callback:
            on_step_callback(f"Auto-cura: patch quebrou a sintaxe de {path}, revertido ({attempts}/3)...")

        return {
            "syntax_check": "failed",
            "stderr": (check.get("stderr") or check.get("error") or "")[:2000],
            "restored_previous_version": restored,
            "attempt": attempts,
            "max_attempts": 3,
            "note": (
                "Limite de 3 tentativas atingido — pare de tentar corrigir sozinho e explique o problema."
                if attempts >= 3 else
                "Arquivo restaurado pro estado anterior ao patch. Analise o erro de sintaxe acima e tente de novo com apply_diff."
            )
        }

    def _strip_tool_call(self, text: str) -> str:
        """Remove blocos tool_call (fenced ou JSON solto) do texto — garante que a
        resposta final ao usuário nunca contenha JSON cru de ferramenta."""
        if not text:
            return ""
        # 1. bloco fenced ```tool_call {...}``` (inclui o objeto com "args" aninhado)
        t = re.sub(r"```(?:tool_call|json)?\s*\{\s*\"tool\".*?\}\s*```", "", text, flags=re.DOTALL)
        # 2. JSON solto {"tool": "...", "args": {...}} — tolera 1 nível de aninhamento
        #    pra não deixar um `}` órfão quando há "args": { ... }.
        t = re.sub(r"\{\s*\"tool\"\s*:\s*\"[^\"]+\"(?:[^{}]|\{[^{}]*\})*\}", "", t, flags=re.DOTALL)
        return t.strip()

    def _extract_tool_call(self, text: str) -> Optional[Dict[str, Any]]:
        """Extrai bloco tool_call em JSON da resposta do modelo."""
        # 1. Procura por bloco ```tool_call ... ```
        m = re.search(r"```(?:tool_call|json)?\s*(\{\s*\"tool\".*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass

        # 2. Procura por JSON solto contendo chave "tool"
        m = re.search(r"(\{\s*\"tool\"\s*:\s*\"[^\"]+\".*?\})", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass

        return None

    def _execute_commands(self, analysis: str):
        """Executa comandos CMD: identificados no output se o hardware estiver conectado."""
        for line in analysis.splitlines():
            m = re.match(r"CMD:([A-Z0-9_\-]+):\s*(.+)", line.strip())
            if not m:
                continue
            dev_id, cmd = m.group(1), m.group(2).strip()
            targets = [d.id for d in self.registry.all() if d.online] if dev_id == "TODOS" else [dev_id]
            for tid in targets:
                dev = self.registry.get(tid)
                if not dev or not dev.online:
                    continue
                wait = 4.0 if any(w in cmd for w in ["wifi", "sniffer", "listen"]) else 2.0
                self.registry.send(tid, cmd, wait)
                time.sleep(0.2)

    def _device_state(self) -> str:
        """
        Vazio quando não há hardware conectado — de propósito. Injetar "nenhum
        dispositivo conectado" em TODA mensagem (achado ao vivo: usuário disse
        "oi" e "spawn agents", modelo pequeno respondeu falando de hardware
        desconectado nos dois casos) prende modelos pequenos nesse tema mesmo
        quando a pergunta não tem nada a ver com ESP32. Só vale a pena mencionar
        quando há dispositivo de verdade pra descrever.
        """
        devs = self.registry.all()
        if not devs:
            # Sem placa conectada: não injeta contexto de hardware nenhum.
            # Antes retornava "Nenhum dispositivo físico conectado...", o que
            # fazia modelos pequenos responderem sobre hardware pra qualquer
            # pergunta (ex.: "ola" -> resposta sobre ESP32).
            return ""
        lines = ["Dispositivos conectados:"]
        for d in devs:
            hw = ", ".join(d.hardware[:5])
            lines.append(f"  {d.id} ({d.label}) | firmware={d.firmware_id} | hw=[{hw}] | protocolo={d.protocol or 'NENHUM'}")
        return "\n".join(lines)
