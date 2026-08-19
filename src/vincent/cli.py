#!/usr/bin/env python3
"""
Vincent CLI 4.0 — Van Gogh 'Starry Night' Cyber-Impressionist Orchestrator.
Integrates 1200+ Whitelabeled Neural Routes, Zero-Key Free Engine, Local Offline Models,
Local Key Vault (chmod 0600), MCP Server (JSON-RPC stdio/socket), Agentic Loop with Tool Calling,
LlamaFactory Fine-Tuning, Caveman Compression (-65%), and Termux/ADB Universal Adaptation.
"""

import argparse
import os
import queue
import sys
import threading
import time

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from vincent.devices import DeviceRegistry
from vincent.agent import VincentAgent
from vincent.models import build_image_content
from vincent.tui_config import run_config_tui
from vincent.auth import VincentAuth, SUPPORTED_PROVIDERS
from vincent.llama_factory import LlamaFactoryOrchestrator
from vincent.env_detect import PlatformEnvironment
from vincent.mcp_server import run_server
from vincent.ui import (
    BANNER, CLR_RST, CLR_BOLD, CLR_DIM, COBALT_BLUE, PRUSSIAN_BLUE,
    LEMON_YELLOW, CHROME_YELLOW, STARRY_GOLD, CYPRESS_GREEN, CYPRESS_DARK,
    VIOLET_SWIRL, ALERT_SCARLET, CANVAS_WHITE, SHADOW_GRAY,
    NeuralSpinner, render_hud_card, render_section_header, render_response_box,
    get_terminal_width
)


def _style_trace(step: str) -> str:
    """Colore uma linha do trace ao vivo do loop agêntico conforme o tipo de evento
    (pensamento / execução de ferramenta / saída), estilo Claude Code."""
    s = step.lstrip()
    if s.startswith("🧠"):
        return f"{VIOLET_SWIRL}{step}{CLR_RST}"
    if s.startswith("⚙️") or s.startswith("⚙"):
        return f"{CHROME_YELLOW}{CLR_BOLD}{step}{CLR_RST}"
    if s.startswith("↳"):
        return f"{SHADOW_GRAY}{step}{CLR_RST}"
    return f"{CANVAS_WHITE}{step}{CLR_RST}"


class _StreamCoordinator:
    """
    Coordena o NeuralSpinner (fase de 'pensando' / trace de ferramentas) com o
    streaming da resposta final ao vivo, sem que o `\\r` do spinner conflite com
    o texto que flui. Uso:

        with _StreamCoordinator("processando…", COBALT_BLUE) as sc:
            reply = agent.agentic_run(task, on_step_callback=sc.on_step,
                                      stream_callback=sc.on_token)

    Enquanto nenhum token chega, o spinner gira e as linhas de trace são
    persistidas via spinner.log(). No PRIMEIRO token da resposta, o spinner é
    parado, imprime-se um cabeçalho 'Vincent:' e os pedaços passam a ser escritos
    direto no stdout (write+flush), aparecendo caractere a caractere.
    """
    def __init__(self, message: str, color: str):
        self._spinner = NeuralSpinner(message, color=color)
        self._streaming = False

    def __enter__(self):
        self._spinner.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._streaming:
            # já streamou: fecha a linha de texto ao vivo com uma quebra
            sys.stdout.write("\n")
            sys.stdout.flush()
        return self._spinner.__exit__(exc_type, exc_val, exc_tb)

    def on_step(self, step: str):
        """Linha de trace do loop agêntico (só faz sentido antes de streamar)."""
        if not self._streaming:
            self._spinner.log(_style_trace(step))

    def on_token(self, piece: str):
        """Pedaço da resposta final — para o spinner na 1ª vez e escreve ao vivo."""
        if not self._streaming:
            self._streaming = True
            # Encerra o spinner (limpa a linha \r do redemoinho) antes de escrever.
            self._spinner.stop_event.set()
            if self._spinner.thread:
                self._spinner.thread.join(timeout=0.4)
            if sys.stdout.isatty():
                sys.stdout.write("\r\033[K")
            sys.stdout.write(f"\n{CYPRESS_GREEN}{CLR_BOLD}Vincent:{CLR_RST} ")
            sys.stdout.flush()
        sys.stdout.write(piece)
        sys.stdout.flush()


def display_models_catalog(agent: VincentAgent, search_term: str = ""):
    """Exibe o catálogo estruturado e whitelabeled de 1200+ modelos e rotas neurais."""
    all_models = agent.model_manager.get_all_models()
    if not all_models:
        print(f"\n{ALERT_SCARLET}⚠ Nenhum modelo indexado nos ateliers.{CLR_RST}")
        print(f"{SHADOW_GRAY}Certifique-se de que a Galeria Vincent (:20128) ou o Atelier Local (:11434) estejam ativos.{CLR_RST}\n")
        return

    if search_term:
        term = search_term.lower()
        all_models = [m for m in all_models if term in m["display_id"].lower() or term in m.get("name", "").lower() or term in m.get("provider", "").lower()]
        render_section_header(f"BUSCA POR '{search_term}': {len(all_models)} MODELOS ENCONTRADOS", "🔍", COBALT_BLUE)
    else:
        render_section_header(f"CATÁLOGO DE OBRAS NEURAIS ({len(all_models)}+ ROTAS)", "🎨", COBALT_BLUE)

    local_models = [m for m in all_models if m.get("is_local")]
    combos = [m for m in all_models if m["id"].startswith("auto")]
    free_models = [m for m in all_models if m.get("is_free") and not m.get("is_local") and not m["id"].startswith("auto")]
    pro_models = [m for m in all_models if not m.get("is_free") and not m.get("is_local") and not m["id"].startswith("auto")]

    if local_models:
        print(f"\n{CYPRESS_GREEN}◈ PALETA LOCAL OFFLINE ZERO-KEY ({len(local_models)}):{CLR_RST} {SHADOW_GRAY}(Zero Latência / Sem Internet / Sem Chave){CLR_RST}")
        for m in local_models:
            print(f"  {CYPRESS_GREEN}⚡{CLR_RST} {CLR_BOLD}{m['display_id']:<28}{CLR_RST} {SHADOW_GRAY}→ {m['name']}{CLR_RST}")

    if combos:
        print(f"\n{COBALT_BLUE}◈ COMBOS DE HARMONIA DINÂMICA ({len(combos)}):{CLR_RST}")
        for m in combos[:12]:
            print(f"  {COBALT_BLUE}◆{CLR_RST} {m['display_id']:<28} {SHADOW_GRAY}[Failover Automático / Whitelabel]{CLR_RST}")
        if len(combos) > 12:
            print(f"  {SHADOW_GRAY}... +{len(combos)-12} combos adicionais (use /search combo){CLR_RST}")

    if free_models:
        print(f"\n{STARRY_GOLD}◈ ROTAS PÚBLICAS ZERO-KEY ({len(free_models)}):{CLR_RST}")
        for m in free_models[:14]:
            print(f"  {LEMON_YELLOW}🆓{CLR_RST} {m['display_id']:<32} {SHADOW_GRAY}(Atelier Aberto){CLR_RST}")
        if len(free_models) > 14:
            print(f"  {SHADOW_GRAY}... +{len(free_models)-14} rotas gratuitas (use /search free){CLR_RST}")

    if pro_models:
        print(f"\n{VIOLET_SWIRL}◈ ATELIER AVANÇADO / PRO ({len(pro_models)}):{CLR_RST}")
        for m in pro_models[:12]:
            print(f"  {VIOLET_SWIRL}▲{CLR_RST} {m['display_id']:<32} {SHADOW_GRAY}(Galeria Pro){CLR_RST}")
        if len(pro_models) > 12:
            print(f"  {SHADOW_GRAY}... +{len(pro_models)-12} modelos avançados (use /search pro){CLR_RST}")

    print(f"\n{SHADOW_GRAY}Sintonia: /model <id> │ Busca rápida: /search <termo> │ Total: {len(all_models)} modelos{CLR_RST}\n")


BARE_COMMAND_ALIASES = {
    "models", "search", "model", "act", "agent", "bg", "vision", "commit", "caveman",
    "vault", "auth", "login", "key", "train", "lora", "export", "devices",
    "cmd", "stats", "help", "config", "skills", "skill", "spawn", "gateway", "tui",
}


def interactive_repl(agent: VincentAgent, registry: DeviceRegistry):
    print(BANNER)
    
    auth = VincentAuth()
    trainer = LlamaFactoryOrchestrator()
    devs = registry.scan()
    
    # HUD Telemetria Inicial Starry Night
    omni_count, ollama_count = agent.model_manager.sync_catalogs()
    is_free = agent.model_manager.is_free_tier(agent.model)
    env_summary = PlatformEnvironment.get_device_summary()
    
    hud_items = [
        ("NÚCLEO NEURAL", f"{CYPRESS_GREEN}ATIVO{CLR_RST} ({agent.display_model})"),
        ("TIPO DE ROTA", f"{CYPRESS_GREEN}ZERO-KEY / OFFLINE 🆓{CLR_RST}" if is_free else f"{VIOLET_SWIRL}GALERIA PRO ⚡{CLR_RST}"),
        ("GALERIA CLOUD", f"{CYPRESS_GREEN}ONLINE{CLR_RST} (:20128) — {omni_count} obras conectadas" if omni_count > 0 else f"{ALERT_SCARLET}OFFLINE{CLR_RST} (:20128) — {omni_count} obras conectadas"),
        ("ATELIER LOCAL", f"{CYPRESS_GREEN}ONLINE{CLR_RST} (:11434) — {ollama_count} modelos quentes" if ollama_count > 0 else f"{ALERT_SCARLET}OFFLINE{CLR_RST} (:11434) — {ollama_count} modelos quentes"),
        ("HARDWARE LAB", f"{len(devs)} Placas Conectadas (TEMBED / ESP32DIV)"),
        ("KEY VAULT (0600)", f"{CYPRESS_GREEN}CHAVES ATIVAS{CLR_RST} ({auth.identity})" if auth.is_authenticated else f"{STARRY_GOLD}MODO ZERO-KEY (/vault){CLR_RST}"),
        ("AMBIENTE", f"{env_summary['os']} (Modo: {env_summary['layout_mode']})")
    ]
    render_hud_card("TELEMETRIA NOITE ESTRELADA — VINCENT HUD", hud_items, COBALT_BLUE)
    
    print(f"\n{SHADOW_GRAY}Comandos essenciais da Galeria:{CLR_RST}")
    print(f"  {COBALT_BLUE}/act <tarefa>{CLR_RST} (agentic loop) • {COBALT_BLUE}/bg <tarefa>{CLR_RST} (background)  • {COBALT_BLUE}/config{CLR_RST} (painel visual)")
    print(f"  {COBALT_BLUE}/models{CLR_RST} (catálogo)           • {COBALT_BLUE}/search <termo>{CLR_RST} (buscar)  • {COBALT_BLUE}/caveman on|off{CLR_RST} (tokens)")
    print(f"  {COBALT_BLUE}/vision <img>{CLR_RST} (multimodal)   • {COBALT_BLUE}/commit <msg>{CLR_RST} (git)       • {COBALT_BLUE}/export{CLR_RST} (dataset)")
    print(f"  {COBALT_BLUE}/vault /key{CLR_RST} (credenciais)     • {COBALT_BLUE}/train /lora{CLR_RST} (finetune)  • {COBALT_BLUE}/help{CLR_RST} (mais)")
    print(f"  {COBALT_BLUE}/devices{CLR_RST} (hardware)          • {COBALT_BLUE}/cmd <dev> <cmd>{CLR_RST} (serial)  • {COBALT_BLUE}/stats{CLR_RST} (telemetria) • {COBALT_BLUE}/exit{CLR_RST}\n")

    term_w = get_terminal_width()

    # Permission prompt (estilo Claude Code): com /autoedit off, o loop agêntico
    # chama isto antes de rodar comando/editar/commitar e espera [s/N].
    def _ask_permission(tool_name, args):
        preview = ""
        if isinstance(args, dict):
            preview = str(args.get("command") or args.get("path") or args.get("filepath") or args.get("code") or args.get("url") or args.get("message") or (next(iter(args.values())) if args else ""))
        else:
            preview = str(args or "")
        preview = preview.replace("\n", " ")[:90]
        try:
            ans = input(f"\n{CHROME_YELLOW}  ⚠ Permitir {tool_name}{(' › ' + preview) if preview else ''}? [s/N] {CLR_RST}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        return ans in ("s", "sim", "y", "yes")
    agent.permission_callback = _ask_permission

    # Spawn de tarefas em background (thread + queue, stdlib puro). São
    # I/O-bound (chamadas de rede pro Ollama/OmniRoute), então threading já
    # sobrepõe de verdade enquanto o usuário segue digitando.
    # ponytail: agentic_run compartilha estado do agent (_history, telemetry,
    # _heal_attempts) — rodar 2 tarefas ao mesmo tempo pode causar corrida
    # nesses campos. Ok pro uso ocasional de 1 usuário; se virar rotina,
    # trocar por fila serial ou lock por-campo.
    bg_results: "queue.Queue" = queue.Queue()
    bg_counter = [0]
    bg_threads: list = []  # rastreados só pra avisar em /exit se algo ainda roda
    bg_tasks: dict = {}  # task_id -> (thread, label) — pro /tui mostrar workers reais

    def _spawn_background(task: str):
        bg_counter[0] += 1
        task_id = bg_counter[0]

        def _worker():
            try:
                res = agent.agentic_run(task)
            except Exception as e:
                res = f"[VINCENT BG] Falhou: {e}"
            bg_results.put((task_id, task, res))

        t = threading.Thread(target=_worker, daemon=True, name=f"bg-{task_id}")
        bg_threads.append(t)
        bg_tasks[task_id] = (t, task[:60])
        t.start()
        return task_id

    def _spawn_parallel(subtasks: list):
        """/spawn — N workers de verdade (ThreadPoolExecutor em agent.spawn_workers),
        disparado numa thread própria pra não travar o REPL enquanto rodam."""
        bg_counter[0] += 1
        batch_id = bg_counter[0]

        def _on_worker_event(i: int, status: str):
            print(f"\n{SHADOW_GRAY}  worker {i+1}/{len(subtasks)}: {status} — '{subtasks[i][:60]}'{CLR_RST}")

        def _runner():
            try:
                results = agent.spawn_workers(subtasks, on_worker_event=_on_worker_event)
            except Exception as e:
                results = [f"[VINCENT SPAWN] Falhou: {e}"]
            summary = "\n\n".join(f"── Worker {i+1} ──\n{r}" for i, r in enumerate(results))
            bg_results.put((batch_id, f"/spawn {len(subtasks)} workers", summary))

        t = threading.Thread(target=_runner, daemon=True, name=f"spawn-{batch_id}")
        bg_threads.append(t)
        bg_tasks[batch_id] = (t, f"/spawn {len(subtasks)} workers")
        t.start()
        return batch_id

    while True:
        try:
            while not bg_results.empty():
                bg_id, bg_task, bg_res = bg_results.get_nowait()
                print(f"\n{CYPRESS_GREEN}◈ Tarefa em segundo plano #{bg_id} concluída:{CLR_RST} '{bg_task}'")
                render_response_box(bg_res, agent.display_model, agent.telemetry.last_latency, mode=f"Background #{bg_id}")
        except Exception as e:
            print(f"\n{ALERT_SCARLET}⚠ Erro no processamento de background: {e}{CLR_RST}")

            statusline = agent.telemetry.render_statusline(
                current_model=agent.display_model,
                is_free=agent.model_manager.is_free_tier(agent.model),
                hw_count=len(registry.all()),
                omniroute_ok=(omni_count > 0),
                ollama_ok=(ollama_count > 0),
                caveman_mode=agent.caveman.mode
            )
            print(f"{SHADOW_GRAY}─" * min(term_w, 80) + f"{CLR_RST}")
            print(statusline)

            try:
                prompt = input(f"{COBALT_BLUE}vincent{CLR_RST} {CHROME_YELLOW}[{agent.display_model}]{CLR_RST} {CLR_BOLD}❯{CLR_RST} ").strip()
            except (EOFError, KeyboardInterrupt):
                print(f"\n{COBALT_BLUE}◈ Sessão encerrada. As estrelas continuam brilhando na galeria. Até logo!{CLR_RST}\n")
                break
            if not prompt:
                continue

            # Aceita o nome do comando sem a barra (ex: "models" == "/models"),
            # igual já acontecia com exit/clear — agora vale pra todos.
            first_word = prompt.split(None, 1)[0].lower() if prompt else ""
            if not prompt.startswith("/") and first_word in BARE_COMMAND_ALIASES:
                prompt = "/" + prompt

            # ── Comandos Especiais do REPL ──────────────────────────────────
            if prompt in ("/exit", "/quit", "exit", "quit", ":q"):
                still_running = sum(1 for t in bg_threads if t.is_alive())
                if still_running:
                    print(f"\n{ALERT_SCARLET}⚠ {still_running} tarefa(s) em segundo plano ainda rodando — serão perdidas ao sair.{CLR_RST}")
                    confirm = input(f"{CHROME_YELLOW}Sair mesmo assim? (s/N):{CLR_RST} ").strip().lower()
                    if confirm != "s":
                        continue
                print(f"\n{COBALT_BLUE}◈ Sessão encerrada. As estrelas continuam brilhando na galeria. Até logo!{CLR_RST}\n")
                break

            elif prompt in ("/clear", "clear", "cls"):
                os.system("clear" if os.name == "posix" else "cls")
                print(BANNER)
                continue

            elif prompt == "/models":
                display_models_catalog(agent)
                continue

            elif prompt.startswith("/search"):
                parts = prompt.split(maxsplit=1)
                term = parts[1].strip() if len(parts) > 1 else ""
                display_models_catalog(agent, search_term=term)
                continue

            elif prompt.startswith("/model"):
                parts = prompt.split(maxsplit=1)
                if len(parts) > 1:
                    new_m = parts[1].strip()
                    try:
                        agent.set_model(new_m)
                        print(f"{CYPRESS_GREEN}✓ Modelo ativo alterado para: {agent.display_model}{CLR_RST}\n")
                    except Exception as e:
                        print(f"{ALERT_SCARLET}✗ Falha ao trocar de modelo: {e}{CLR_RST}\n")
                else:
                    print(f"{CHROME_YELLOW}Modelo atual:{CLR_RST} {agent.display_model}")
                    print(f"{SHADOW_GRAY}Uso: /model <id_do_modelo> (ex: /model auto/best-coding ou /model qwen3:0.6b){CLR_RST}")
                continue

            # ── Agentic Loop com Tool Calling e Auto-cura ───────────────────
            elif prompt.startswith("/act") or prompt.startswith("/agent"):
                parts = prompt.split(maxsplit=1)
                if len(parts) > 1:
                    task = parts[1].strip()
                    print(f"\n{VIOLET_SWIRL}◈ Agentic Loop{CLR_RST} {SHADOW_GRAY}— trace ao vivo:{CLR_RST}")
                    try:
                        with _StreamCoordinator("processando…", VIOLET_SWIRL) as sc:
                            res = agent.agentic_run(task, on_step_callback=sc.on_step, stream_callback=sc.on_token)
                    except KeyboardInterrupt:
                        print(f"\n{ALERT_SCARLET}✗ Tarefa interrompida pelo usuário (Ctrl+C). Voltando ao prompt.{CLR_RST}\n")
                        continue
                    except Exception as e:
                        print(f"\n{ALERT_SCARLET}✗ Erro na execução da tarefa: {e}{CLR_RST}\n")
                        continue
                    render_response_box(res, agent.display_model, agent.telemetry.last_latency, mode="Agentic Loop (Tools)")
                else:
                    print(f"{VIOLET_SWIRL}Uso:{CLR_RST} /act <descrição da tarefa de código/investigação>")
                continue

            elif prompt.startswith("/bg"):
                parts = prompt.split(maxsplit=1)
                if len(parts) > 1:
                    task = parts[1].strip()
                    bg_id = _spawn_background(task)
                    print(f"{VIOLET_SWIRL}◈ Tarefa em segundo plano #{bg_id} disparada:{CLR_RST} '{task}'")
                    print(f"{SHADOW_GRAY}Continue trabalhando — aviso quando terminar.{CLR_RST}\n")
                else:
                    print(f"{VIOLET_SWIRL}Uso:{CLR_RST} /bg <tarefa> — roda em segundo plano, não trava o REPL")
                continue

            elif prompt.startswith("/spawn"):
                parts = prompt.split(maxsplit=2)
                if len(parts) > 2 and parts[1].isdigit():
                    n = int(parts[1])
                    task_str = parts[2].strip()
                    # "a; b; c" = uma subtarefa distinta por worker. Sem ";" = as
                    # N cópias da mesma tarefa rodam em paralelo (N tentativas).
                    subtasks = [t.strip() for t in task_str.split(";") if t.strip()] or [task_str]
                    if len(subtasks) == 1 and n > 1:
                        subtasks = [task_str] * n
                    batch_id = _spawn_parallel(subtasks)
                    print(f"{VIOLET_SWIRL}◈ Lote #{batch_id} disparado: {len(subtasks)} workers em paralelo.{CLR_RST}")
                    print(f"{SHADOW_GRAY}Continue trabalhando — status de cada worker aparece aqui conforme termina.{CLR_RST}\n")
                else:
                    print(f"{VIOLET_SWIRL}Uso:{CLR_RST} /spawn <n> <tarefa1>; <tarefa2>; ... (ou uma tarefa só = N tentativas em paralelo)")
                continue

            elif prompt.startswith("/skill add"):
                url = prompt.split(maxsplit=2)[2].strip() if len(prompt.split(maxsplit=2)) > 2 else ""
                if not url:
                    print(f"{VIOLET_SWIRL}Uso:{CLR_RST} /skill add <git-url>")
                else:
                    from vincent.skills import add_skill_from_git
                    try:
                        with NeuralSpinner(f"Clonando skills de {url}...", color=VIOLET_SWIRL):
                            installed = add_skill_from_git(url)
                        if installed:
                            print(f"{CYPRESS_GREEN}✓ Skills instaladas:{CLR_RST} {', '.join(installed)}\n")
                        else:
                            print(f"{ALERT_SCARLET}✗ Nenhum SKILL.md encontrado nesse repo (esperado: skills/<nome>/SKILL.md).{CLR_RST}\n")
                    except (ValueError, RuntimeError) as e:
                        print(f"{ALERT_SCARLET}✗ {e}{CLR_RST}\n")
                continue

            elif prompt == "/skills":
                from vincent.skills import list_skills
                sk = list_skills()
                if not sk:
                    print(f"{SHADOW_GRAY}Nenhuma skill instalada. Use /skill add <git-url>.{CLR_RST}\n")
                else:
                    render_section_header(f"SKILLS INSTALADAS ({len(sk)})", "🧠", VIOLET_SWIRL)
                    for s in sk:
                        print(f"  {VIOLET_SWIRL}◆{CLR_RST} {CLR_BOLD}{s['name']}{CLR_RST} — {SHADOW_GRAY}{s['description']}{CLR_RST}")
                    print()
                continue

            elif prompt.startswith("/vision"):
                parts = prompt.split(maxsplit=2)
                if len(parts) > 1:
                    img_path = parts[1].strip()
                    question = parts[2].strip() if len(parts) > 2 else "Descreva em detalhes o que há nesta imagem."
                    try:
                        content = build_image_content(question, img_path)
                    except (FileNotFoundError, ValueError) as e:
                        print(f"{ALERT_SCARLET}✗ {e}{CLR_RST}\n")
                        continue
                    try:
                        with NeuralSpinner(f"Vincent analisando imagem: '{img_path}'...", color=VIOLET_SWIRL):
                            reply, used_model, lat = agent.model_manager.execute_inference(
                                [{"role": "user", "content": content}],
                                target_model=agent.model,
                                system_prompt="Você é o Vincent. Analise a imagem enviada e responda de forma técnica e direta em Português."
                            )
                    except Exception as e:
                        print(f"{ALERT_SCARLET}✗ Falha na inferência multimodal: {e}{CLR_RST}\n")
                        continue
                    render_response_box(
                        reply or "[VINCENT VISION] Sem resposta do modelo.",
                        agent.display_model, lat, mode="Visão Multimodal"
                    )
                else:
                    print(f"{VIOLET_SWIRL}Uso:{CLR_RST} /vision <caminho_da_imagem> [pergunta opcional]")
                    print(f"{SHADOW_GRAY}Requer modelo multimodal ativo (ex: /model qwen2.5vl, /model auto/best-vision).{CLR_RST}")
                continue

            elif prompt.startswith("/gateway"):
                status = agent.model_manager.gateway_status()
                items = [
                    ("URL", status["url"]),
                    ("ALCANÇÁVEL", f"{CYPRESS_GREEN}SIM{CLR_RST} ({status['model_count']} modelos)" if status["reachable"] else f"{ALERT_SCARLET}NÃO{CLR_RST}"),
                    ("CIRCUITO", status["circuit_state"].upper()),
                    ("COOLDOWN ATIVO", "SIM" if status["cooldown_active"] else "NÃO"),
                ]
                render_hud_card("STATUS DO GATEWAY OMNIROUTE", items, COBALT_BLUE)
                continue

            elif prompt == "/tui":
                from vincent import tui as _tui

                def _collect_state():
                    workers = [
                        {"id": tid, "task": label, "status": "running" if t.is_alive() else "done"}
                        for tid, (t, label) in bg_tasks.items()
                    ]
                    log = [
                        {"role": m.get("role", "user"), "text": str(m.get("content", ""))[:300]}
                        for m in agent._history[-10:]
                    ]
                    return {
                        "model": agent.display_model,
                        "tokens_used": agent.telemetry.tokens_in + agent.telemetry.tokens_out,
                        "tokens_saved": agent.caveman.total_tokens_saved,
                        "cost_usd": agent.caveman.get_stats()["estimated_cost_saved_usd"],
                        "workers": workers,
                        "log": log,
                    }

                any_alive = any(t.is_alive() for t, _ in bg_tasks.values())
                if not any_alive:
                    # sem worker rodando: só um snapshot estático, sem sentido ficar "ao vivo"
                    console = _tui.Console()
                    console.print(_tui.render_frame(_collect_state()))
                else:
                    live = _tui.mount(_collect_state())
                    print(f"{SHADOW_GRAY}Ctrl+C pra sair do painel ao vivo (as tarefas em background continuam).{CLR_RST}")
                    try:
                        with live:
                            while any(t.is_alive() for t, _ in bg_tasks.values()):
                                live.update(_tui.render_frame(_collect_state()))
                                time.sleep(0.5)
                            live.update(_tui.render_frame(_collect_state()))
                    except KeyboardInterrupt:
                        pass
                continue

            elif prompt == "/config":
                chosen = run_config_tui(agent.display_model)
                if chosen:
                    agent.set_model(chosen)
                    print(f"{CYPRESS_GREEN}✓ Modelo ativo: {agent.display_model}{CLR_RST}\n")
                continue

            elif prompt.startswith("/commit"):
                parts = prompt.split(maxsplit=1)
                if len(parts) > 1:
                    from vincent.agent_tools import tool_git_status, tool_git_commit
                    status = tool_git_status()
                    if not status.get("stdout", "").strip():
                        print(f"{SHADOW_GRAY}Nada para commitar — working tree limpo.{CLR_RST}\n")
                    else:
                        res = tool_git_commit(message=parts[1].strip())
                        if res.get("success"):
                            print(f"{CYPRESS_GREEN}✓ Checkpoint criado: {parts[1].strip()}{CLR_RST}\n")
                        else:
                            print(f"{ALERT_SCARLET}✗ Commit falhou: {res.get('stderr') or res.get('error')}{CLR_RST}\n")
                else:
                    print(f"{VIOLET_SWIRL}Uso:{CLR_RST} /commit <mensagem Conventional Commits, ex: 'fix(core): ...'>")
                continue

            elif prompt.startswith("/caveman"):
                parts = prompt.split(maxsplit=1)
                if len(parts) > 1:
                    mode = parts[1].strip().lower()
                    if agent.set_caveman_mode(mode):
                        stats = agent.caveman.get_stats()
                        items = [
                            ("MODO CAVEMAN", f"{STARRY_GOLD}{stats['mode'].upper()}{CLR_RST}"),
                            ("DIRETIVA", stats['description']),
                            ("TOTAL ECONOMIZADO", f"{CYPRESS_GREEN}+{stats['total_tokens_saved']} tokens{CLR_RST}")
                        ]
                        render_hud_card("MOTOR DE COMPRESSÃO CAVEMAN (-65%)", items, STARRY_GOLD)
                    else:
                        opcoes = ", ".join(agent.caveman.INTENSITY_LEVELS)
                        print(f"{ALERT_SCARLET}Modo inválido. Opções: {opcoes}{CLR_RST}")
                else:
                    curr = agent.caveman.mode
                    opcoes = " | ".join(agent.caveman.INTENSITY_LEVELS)
                    print(f"{STARRY_GOLD}Modo Caveman ativo:{CLR_RST} {curr}")
                    print(f"{SHADOW_GRAY}Uso: /caveman {opcoes}{CLR_RST}")
                continue

            # ── Key Vault & Autenticação Segura ─────────────────────────────
            elif prompt in ("/vault", "/auth", "/login"):
                render_section_header("COFRE DE CHAVES LOCAL (CHMOD 0600)", "🔐", COBALT_BLUE)
                print(f"  1. Inserir chave OmniRoute / Galeria Vincent")
                print(f"  2. Inserir chave OpenAI")
                print(f"  3. Inserir chave Anthropic")
                print(f"  4. Inserir chave Gemini")
                print(f"  5. Inserir chave DeepSeek")
                print(f"  6. Configurar Host Ollama Local")
                print(f"  7. Inserir chave Tavily (fallback de busca web)")
                print(f"  8. Inserir chave Serper (fallback de busca web)")
                print(f"  9. Ver status do cofre\n")
                choice = input(f"{CHROME_YELLOW}Escolha uma opção (1-9 ou Enter para voltar):{CLR_RST} ").strip()
                prov_map = {
                    "1": "omniroute", "2": "openai", "3": "anthropic", "4": "gemini",
                    "5": "deepseek", "6": "ollama_host", "7": "tavily", "8": "serper"
                }
                if choice in prov_map:
                    auth.interactive_login(prov_map[choice])
                elif choice == "9":
                    render_hud_card("STATUS DO COFRE DE CHAVES", auth.status_card_data(), COBALT_BLUE)
                continue

            elif prompt.startswith("/key"):
                parts = prompt.split(maxsplit=1)
                if len(parts) > 1:
                    key = parts[1].strip()
                    if auth.set_key("omniroute", key):
                        print(f"{CYPRESS_GREEN}✓ Chave Neural da Galeria registrada no cofre (chmod 0600)!{CLR_RST}\n")
                    else:
                        print(f"{ALERT_SCARLET}✗ Chave inválida.{CLR_RST}\n")
                else:
                    auth.interactive_login("omniroute")
                continue

            elif prompt.startswith("/train") or prompt.startswith("/lora"):
                cfg = trainer.generate_lora_config(base_model=agent.model)
                cmd = trainer.build_training_command(cfg)
                items = [
                    ("FRAMEWORK", "LlamaFactory Native Fine-Tuning Hook"),
                    ("CONFIGURAÇÃO YAML", cfg),
                    ("MODELO BASE", agent.model),
                    ("COMANDO DE EXECUÇÃO", f"{LEMON_YELLOW}{cmd}{CLR_RST}")
                ]
                render_hud_card("TREINAMENTO & FINE-TUNING LLM", items, STARRY_GOLD)
                continue

            elif prompt == "/export":
                exported_file = trainer.export_session_dataset(agent._history)
                print(f"{CYPRESS_GREEN}✓ Dataset de sessão exportado para:{CLR_RST} {exported_file}\n")
                continue

            elif prompt == "/devices":
                devs = registry.scan(quick=False)
                if devs:
                    items = []
                    for d in devs:
                        items.append((d.id, f"{d.label} | Porta: {d.port} | Firmware: {d.firmware_id}"))
                    render_hud_card("LABORATÓRIO DE HARDWARE USB", items, CYPRESS_GREEN)
                else:
                    print(f"\n{ALERT_SCARLET}Nenhuma placa ESP32/USB detectada.{CLR_RST}")
                    print(f"{SHADOW_GRAY}Conecte o LilyGo T-Embed ou o ESP32DIV e execute /devices novamente.{CLR_RST}\n")
                continue

            elif prompt.startswith("/cmd"):
                parts = prompt.split(maxsplit=2)
                if len(parts) >= 3:
                    target_dev, cmd_str = parts[1], parts[2]
                    dev = registry.get(target_dev)
                    if dev and dev.online:
                        print(f"[{target_dev}] ← {cmd_str}")
                        r = registry.send(target_dev, cmd_str)
                        print(f"[{target_dev}] → {r.get('response', '')}")
                    else:
                        print(f"{ALERT_SCARLET}Dispositivo '{target_dev}' offline ou não encontrado.{CLR_RST}")
                else:
                    print(f"{CHROME_YELLOW}Uso:{CLR_RST} /cmd <TEMBED|ESP32DIV> <comando_serial>")
                continue

            elif prompt == "/stats":
                c_stats = agent.caveman.get_stats()
                items = agent.telemetry.get_summary_cards(agent.display_model, c_stats)
                render_hud_card("TELEMETRIA PONYTAIL & ECONOMIA DE TOKENS", items, COBALT_BLUE)
                continue

            elif prompt in ("/reload-plugins", "/reload", "/reload_plugins"):
                n = agent.plugins.scan_skills()
                print(f"{CYPRESS_GREEN}✓ Plugins/skills recarregados ({n} encontrados).{CLR_RST} {SHADOW_GRAY}Use /skills pra ver.{CLR_RST}\n")
                continue

            elif prompt.startswith("/effort"):
                parts = prompt.split(maxsplit=1)
                val = parts[1].strip().lower() if len(parts) > 1 else ""
                val = "medium" if val == "med" else val
                if val in ("low", "medium", "high"):
                    agent.model_manager.effort = val
                    desc = {"low": "rápido / curto", "medium": "equilibrado", "high": "raciocínio profundo / longo"}[val]
                    print(f"{CYPRESS_GREEN}✓ Effort: {val}{CLR_RST} {SHADOW_GRAY}({desc}){CLR_RST}\n")
                else:
                    print(f"{CHROME_YELLOW}Uso:{CLR_RST} /effort low | medium | high  {SHADOW_GRAY}(atual: {agent.model_manager.effort}){CLR_RST}\n")
                continue

            elif prompt.startswith("/autoedit"):
                parts = prompt.split(maxsplit=1)
                val = parts[1].strip().lower() if len(parts) > 1 else ""
                if val in ("on", "off"):
                    agent.autoedit = (val == "on")
                    msg = "executa sem perguntar" if agent.autoedit else "PERGUNTA [s/N] antes de rodar comando/editar/commitar"
                    print(f"{CYPRESS_GREEN}✓ Autoedit: {val}{CLR_RST} {SHADOW_GRAY}— {msg}{CLR_RST}\n")
                else:
                    cur = "on" if agent.autoedit else "off"
                    print(f"{CHROME_YELLOW}Uso:{CLR_RST} /autoedit on | off  {SHADOW_GRAY}(atual: {cur} — off = pede permissão, tipo Claude Code){CLR_RST}\n")
                continue

            elif prompt.startswith("/auto "):
                goal = prompt.split(maxsplit=1)[1].strip()
                task = (f"OBJETIVO (modo autônomo contínuo): {goal}\n\n"
                        "Trabalhe de forma AUTÔNOMA até completar 100% do objetivo. Encadeie quantas "
                        "ferramentas forem necessárias, verifique cada resultado, e só finalize quando estiver de fato pronto.")
                print(f"\n{VIOLET_SWIRL}◈ Auto-mode contínuo{CLR_RST} {SHADOW_GRAY}— trabalha até terminar (máx 40 passos):{CLR_RST}")
                spinner = NeuralSpinner("Auto-mode: processando…", color=VIOLET_SWIRL)
                with spinner:
                    res = agent.agentic_run(task, on_step_callback=lambda s: spinner.log(_style_trace(s)), max_turns=40)
                render_response_box(res, agent.display_model, agent.telemetry.last_latency, mode="Auto-mode Contínuo")
                continue

            elif prompt == "/help":
                render_section_header("GUIA DE COMANDOS DA GALERIA VINCENT", "💡", COBALT_BLUE)
                print(f"  {COBALT_BLUE}/act <tarefa>{CLR_RST}           Agentic Loop: investiga e altera código com ferramentas")
                print(f"  {COBALT_BLUE}/bg <tarefa>{CLR_RST}           Roda tarefa em segundo plano, sem travar o REPL")
                print(f"  {COBALT_BLUE}/config{CLR_RST}                Painel visual (setas) de chaves e modelo ativo")
                print(f"  {COBALT_BLUE}/vision <img> [pergunta]{CLR_RST} Analisa imagem via modelo multimodal")
                print(f"  {COBALT_BLUE}/commit <msg>{CLR_RST}          Checkpoint git manual (Conventional Commits)")
                print(f"  {COBALT_BLUE}/models{CLR_RST}               Exibe todas as rotas e modelos de IA indexados")
                print(f"  {COBALT_BLUE}/search <termo>{CLR_RST}        Filtra modelos por palavra-chave (ex: /search free)")
                print(f"  {COBALT_BLUE}/model <id>{CLR_RST}            Sintoniza o modelo ativo em tempo real")
                print(f"  {COBALT_BLUE}/caveman <modo>{CLR_RST}        Ativa compressão extrema de tokens (off, lite, full, ultra)")
                print(f"  {COBALT_BLUE}/vault | /key{CLR_RST}          Gerencia chaves de API com segurança (chmod 0600)")
                print(f"  {COBALT_BLUE}/train | /lora{CLR_RST}        Gera pipeline de fine-tuning LlamaFactory")
                print(f"  {COBALT_BLUE}/export{CLR_RST}                Exporta histórico para dataset de treino")
                print(f"  {COBALT_BLUE}/skills{CLR_RST}               Lista skills instaladas (SKILL.md carregado sob demanda)")
                print(f"  {COBALT_BLUE}/skill add <git-url>{CLR_RST}   Clona um repo de skills (ex: obsidian-skills) pra ~/.vincent/skills")
                print(f"  {COBALT_BLUE}/spawn <n> <tarefas>{CLR_RST}   N workers paralelos (separe por ';' ou repete a mesma tarefa)")
                print(f"  {COBALT_BLUE}/tui{CLR_RST}                  Painel visual (Rich) — ao vivo se tiver /bg ou /spawn rodando")
                print(f"  {COBALT_BLUE}/gateway{CLR_RST}              Status do gateway OmniRoute (circuito, cooldown, modelos)")
                print(f"  {COBALT_BLUE}/devices{CLR_RST}              Varre e inspeciona placas ESP32 conectadas")
                print(f"  {COBALT_BLUE}/cmd <dev> <cmd>{CLR_RST}       Envia comando serial direto para a placa")
                print(f"  {COBALT_BLUE}/stats{CLR_RST}                Relatório de telemetria, hardware e economia de tokens")
                print(f"  {COBALT_BLUE}/clear{CLR_RST}                Limpa a tela e o histórico da sessão")
                print(f"  {COBALT_BLUE}/exit{CLR_RST}                 Encerra o CLI\n")
                continue

            elif prompt.startswith("/"):
                # Comando com barra que não bateu em nenhum handler acima — não
                # manda pro chat (o modelo alucina JSON de tool-call que nunca
                # executa). Erro direto.
                cmd = prompt.split(maxsplit=1)[0]
                print(f"{ALERT_SCARLET}✗ Comando desconhecido: {cmd}{CLR_RST}")
                print(f"{SHADOW_GRAY}Use /help para ver os comandos disponíveis.{CLR_RST}\n")
                continue

            # ── Execução de Prompt Padrão (chat = ação, mesmo loop do /act) ──
            # Um único caminho: agentic_run já sai em 1 turno se o modelo não
            # pedir ferramenta (ex: "oi"), e executa de verdade quando pede.
            mode_label = f"Caveman ({agent.caveman.mode})" if agent.caveman.mode != "off" else "Standard"
            with _StreamCoordinator("processando…", COBALT_BLUE) as sc:
                reply = agent.agentic_run(prompt, on_step_callback=sc.on_step, stream_callback=sc.on_token)

            render_response_box(
                reply=reply,
                model=agent.display_model,
                latency=agent.telemetry.last_latency,
                mode=mode_label,
                tokens_saved=agent.caveman.total_tokens_saved
            )

        except KeyboardInterrupt:
            print(f"\n{SHADOW_GRAY}Pincelada interrompida pelo usuário. Use /exit para sair.{CLR_RST}\n")
        except Exception as e:
            print(f"\n{ALERT_SCARLET}[ERRO VINCENT]: {e}{CLR_RST}\n")


def main():
    parser = argparse.ArgumentParser(description="Vincent CLI 4.0 — Van Gogh 'Starry Night' Cyber-Impressionist Orchestrator")
    parser.add_argument("prompt", nargs="*", help="Pergunta ou comando direto para o Vincent")
    parser.add_argument("-m", "--model", default="qwen3:0.6b", help="Modelo inicial (ex: qwen3:0.6b, qwen2.5-coder:7b, auto/best-free)")
    parser.add_argument("-a", "--agent", type=str, default=None, help="Executar tarefa via Agentic Loop autônomo com Tool Calling")
    parser.add_argument("-l", "--list-models", action="store_true", help="Listar todos os modelos do catálogo")
    parser.add_argument("-s", "--search", type=str, default="", help="Filtrar modelos por termo de busca")
    parser.add_argument("-c", "--caveman", type=str, default=None, help="Modo caveman (lite, full, ultra)")
    parser.add_argument("-d", "--devices", action="store_true", help="Listar dispositivos de hardware USB conectados")
    parser.add_argument("-t", "--train", action="store_true", help="Gerar configuração de treino LoRA via LlamaFactory")
    parser.add_argument("--vault", "--auth", action="store_true", help="Exibir status do cofre de chaves (chmod 0600)")
    parser.add_argument("--config", action="store_true", help="Abrir painel visual interativo (setas) de configuração")
    parser.add_argument("--serve", "--daemon", action="store_true", help="Iniciar servidor MCP em segundo plano (daemon rastreável)")
    parser.add_argument("--mcp", action="store_true", help="Iniciar servidor MCP no terminal via stdio")
    parser.add_argument("--socket", type=str, default=None, help="Caminho do socket Unix para o servidor MCP")
    parser.add_argument("--tui", action="store_true", help="Abrir a interface TUI de tela cheia (estilo Claude Code / OpenCode)")

    args = parser.parse_args()

    # Modo TUI de tela cheia (Textual) — a interface "não-primitiva"
    if args.tui:
        from vincent.tui_app import main as tui_main
        tui_main()
        sys.exit(0)

    # Modo Servidor MCP / Daemon
    if args.serve:
        print(f"{CYPRESS_GREEN}Iniciando servidor MCP em segundo plano (daemon)...{CLR_RST}")
        run_server(daemon=True, socket_path=args.socket)
        sys.exit(0)

    if args.mcp:
        run_server(daemon=False, socket_path=args.socket)
        sys.exit(0)

    registry = DeviceRegistry(lambda evt: None)
    agent = VincentAgent(registry=registry, model=args.model)

    if args.caveman:
        agent.set_caveman_mode(args.caveman)

    if args.list_models:
        display_models_catalog(agent, search_term=args.search)
        sys.exit(0)

    if args.search:
        display_models_catalog(agent, search_term=args.search)
        sys.exit(0)

    if args.devices:
        devs = registry.scan(quick=False)
        if devs:
            items = [(d.id, f"{d.label} | Porta: {d.port} | Firmware: {d.firmware_id}") for d in devs]
            render_hud_card("LABORATÓRIO DE HARDWARE USB", items, CYPRESS_GREEN)
        else:
            print(f"\n{ALERT_SCARLET}Nenhuma placa ESP32 detectada.{CLR_RST}\n")
        sys.exit(0)

    if args.train:
        trainer = LlamaFactoryOrchestrator()
        cfg = trainer.generate_lora_config(base_model=agent.model)
        cmd = trainer.build_training_command(cfg)
        items = [
            ("FRAMEWORK", "LlamaFactory Native Fine-Tuning Hook"),
            ("CONFIGURAÇÃO YAML", cfg),
            ("MODELO BASE", agent.model),
            ("COMANDO", f"{LEMON_YELLOW}{cmd}{CLR_RST}")
        ]
        render_hud_card("TREINAMENTO & FINE-TUNING LLM", items, STARRY_GOLD)
        sys.exit(0)

    if args.vault:
        auth = VincentAuth()
        render_hud_card("COFRE DE CHAVES LOCAL (CHMOD 0600)", auth.status_card_data(), COBALT_BLUE)
        sys.exit(0)

    if args.config:
        chosen = run_config_tui(agent.display_model)
        if chosen:
            print(f"{CYPRESS_GREEN}✓ Modelo ativo: {chosen} — rode 'vincent -m {chosen}' pra usar direto.{CLR_RST}")
        sys.exit(0)

    if args.agent:
        spinner = NeuralSpinner(f"Vincent Agentic Loop iniciando para: '{args.agent}'...", color=VIOLET_SWIRL)
        with spinner:
            res = agent.agentic_run(args.agent, on_step_callback=lambda step: spinner.update_message(f"Vincent: {step}"))
        render_response_box(res, agent.display_model, agent.telemetry.last_latency, mode="Agentic Loop (Tools)")
        sys.exit(0)

    if args.prompt:
        question = " ".join(args.prompt)
        spinner = NeuralSpinner(f"Processando com [{agent.display_model}]...", color=COBALT_BLUE)
        with spinner:
            reply = agent.agentic_run(question, on_step_callback=lambda step: spinner.update_message(f"Vincent: {step}"))
        mode_label = f"Caveman ({agent.caveman.mode})" if agent.caveman.mode != "off" else "Standard"
        render_response_box(reply, agent.display_model, agent.telemetry.last_latency, mode=mode_label, tokens_saved=agent.caveman.total_tokens_saved)
        sys.exit(0)

    # Entra no REPL interativo futurista
    interactive_repl(agent, registry)


if __name__ == "__main__":
    main()
