#!/usr/bin/env python3
"""
Vincent CLI 4.0 — Cyberpunk Neural HUD & Autonomous Orchestrator.
Integrates 1200+ Vincent Neural Routes, Zero-Key Free Gateways, Local Offline Engine,
UI/UX Pro Max Interface, Caveman Ultra-Compression, and GSD Multi-Agent Swarm.
"""

import argparse
import os
import sys
import time

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from vincent.devices import DeviceRegistry
from vincent.agent import VincentAgent
from vincent.gsd import GSDOrchestrator
from vincent.ui import (
    BANNER, CLR_RST, CLR_BOLD, CLR_DIM, CYAN_NEON, MAGENTA_NEON,
    PURPLE_GLOW, GREEN_MATRIX, AMBER_WARN, RED_ALERT, GRAY_LIGHT,
    GRAY_MUTED, GRAY_DARK, NeuralSpinner, render_hud_card, render_section_header,
    render_response_box
)


def display_models_catalog(agent: VincentAgent, search_term: str = ""):
    """Exibe o catálogo estruturado de 1200+ modelos e rotas ativas."""
    all_models = agent.model_manager.get_all_models()
    if not all_models:
        print(f"\n{RED_ALERT}⚠ Nenhum modelo indexado nos gateways.{CLR_RST}")
        print(f"{GRAY_MUTED}Certifique-se de que o Núcleo Vincent (:20128) ou o Motor Local (:11434) estejam ativos.{CLR_RST}\n")
        return

    if search_term:
        term = search_term.lower()
        all_models = [m for m in all_models if term in m["display_id"].lower() or term in m.get("name", "").lower() or term in m.get("provider", "").lower()]
        render_section_header(f"BUSCA POR '{search_term}': {len(all_models)} MODELOS ENCONTRADOS", "🔍", CYAN_NEON)
    else:
        render_section_header(f"CATÁLOGO DE MODELOS NEURAIS ({len(all_models)}+ MODELOS)", "⚡", CYAN_NEON)

    local_models = [m for m in all_models if m.get("is_local")]
    combos = [m for m in all_models if m["id"].startswith("auto")]
    free_models = [m for m in all_models if m.get("is_free") and not m.get("is_local") and not m["id"].startswith("auto")]
    pro_models = [m for m in all_models if not m.get("is_free") and not m.get("is_local") and not m["id"].startswith("auto")]

    if local_models:
        print(f"\n{GREEN_MATRIX}◈ MODELOS LOCAIS OFFLINE ZERO-KEY ({len(local_models)}):{CLR_RST} {GRAY_MUTED}(Zero Latência / Sem Internet / Sem Chave){CLR_RST}")
        for m in local_models:
            print(f"  {GREEN_MATRIX}⚡{CLR_RST} {CLR_BOLD}{m['display_id']:<28}{CLR_RST} {GRAY_MUTED}→ {m['name']}{CLR_RST}")

    if combos:
        print(f"\n{CYAN_NEON}◈ COMBOS DE ROTEAMENTO DINÂMICO ({len(combos)}):{CLR_RST}")
        for m in combos[:12]:
            print(f"  {CYAN_NEON}◆{CLR_RST} {m['display_id']:<28} {GRAY_MUTED}[Auto-Routing Failover]{CLR_RST}")
        if len(combos) > 12:
            print(f"  {GRAY_MUTED}... +{len(combos)-12} combos adicionais (use /search combo){CLR_RST}")

    if free_models:
        print(f"\n{AMBER_WARN}◈ ROTAS ZERO-KEY / FREE GATEWAYS ({len(free_models)}):{CLR_RST}")
        for m in free_models[:14]:
            print(f"  {AMBER_WARN}🆓{CLR_RST} {m['display_id']:<32} {GRAY_MUTED}({m.get('provider', 'vincent-cloud')}){CLR_RST}")
        if len(free_models) > 14:
            print(f"  {GRAY_MUTED}... +{len(free_models)-14} rotas gratuitas (use /search free){CLR_RST}")

    if pro_models:
        print(f"\n{PURPLE_GLOW}◈ MODELOS PRO / CODING / CLOUD ({len(pro_models)}):{CLR_RST}")
        for m in pro_models[:12]:
            print(f"  {MAGENTA_NEON}▲{CLR_RST} {m['display_id']:<32} {GRAY_MUTED}({m.get('provider', 'vincent-cloud')}){CLR_RST}")
        if len(pro_models) > 12:
            print(f"  {GRAY_MUTED}... +{len(pro_models)-12} modelos avançados (use /search pro){CLR_RST}")

    print(f"\n{GRAY_MUTED}Sintonia: /model <id> | Busca rápida: /search <termo> | Total: {len(all_models)} modelos{CLR_RST}\n")


def interactive_repl(agent: VincentAgent, registry: DeviceRegistry):
    print(BANNER)
    
    gsd = GSDOrchestrator(agent)
    devs = registry.scan()
    
    # HUD Telemetria Inicial (UI/UX Pro Max)
    omni_count, ollama_count = agent.model_manager.sync_catalogs()
    is_free = agent.model_manager.is_free_tier(agent.model)
    
    hud_items = [
        ("NÚCLEO NEURAL", f"{GREEN_MATRIX}ATIVO{CLR_RST} ({agent.display_model})"),
        ("TIPO DO MODELO", f"{GREEN_MATRIX}ZERO-KEY / OFFLINE 🆓{CLR_RST}" if is_free else f"{PURPLE_GLOW}PRO GATEWAY ⚡{CLR_RST}"),
        ("NÚCLEO VINCENT CLOUD", f"{GREEN_MATRIX}ONLINE{CLR_RST} (:20128) — {omni_count} rotas"),
        ("MOTOR LOCAL VINCENT", f"{GREEN_MATRIX}ONLINE{CLR_RST} (:11434) — {ollama_count} modelos quentes"),
        ("DISPOSITIVOS HW", f"{len(devs)} Placas Conectadas (TEMBED / ESP32DIV)"),
        ("MODO CAVEMAN", f"{GRAY_MUTED}DESATIVADO (/caveman lite|full|ultra){CLR_RST}"),
        ("PLUGINS", f"{len(agent.plugins.active_plugins)} ativos / {len(agent.plugins.skills)} instalados (/plugins)")
    ]
    render_hud_card("TELEMETRIA VINCENT NEURAL HUD", hud_items, CYAN_NEON)
    
    print(f"\n{GRAY_MUTED}Comandos essenciais:{CLR_RST}")
    print(f"  {CYAN_NEON}/models{CLR_RST} (catálogo)    • {CYAN_NEON}/search <termo>{CLR_RST} (buscar)     • {CYAN_NEON}/model <id>{CLR_RST} (trocar)")
    print(f"  {CYAN_NEON}/caveman on|off{CLR_RST} (tokens) • {CYAN_NEON}/gsd <tarefa>{CLR_RST} (swarm)     • {CYAN_NEON}/squad{CLR_RST} (agentes)")
    print(f"  {CYAN_NEON}/plugins{CLR_RST} (listar)     • {CYAN_NEON}/plugin <nome>{CLR_RST} (ligar/desligar)")
    print(f"  {CYAN_NEON}/devices{CLR_RST} (hardware)   • {CYAN_NEON}/cmd <dev> <cmd>{CLR_RST} (serial)  • {CYAN_NEON}/stats{CLR_RST} (telemetria) • {CYAN_NEON}/exit{CLR_RST}\n")

    while True:
        try:
            # Ponytail Live Statusline
            statusline = agent.telemetry.render_statusline(
                current_model=agent.display_model,
                is_free=agent.model_manager.is_free_tier(agent.model),
                hw_count=len(registry.all()),
                omniroute_ok=(omni_count > 0),
                ollama_ok=(ollama_count > 0),
                caveman_mode=agent.caveman.mode
            )
            print(f"{GRAY_DARK}─" * 80 + f"{CLR_RST}")
            print(statusline)

            prompt = input(f"{CYAN_NEON}vincent{CLR_RST} {MAGENTA_NEON}[{agent.display_model}]{CLR_RST} {CLR_BOLD}❯{CLR_RST} ").strip()
            if not prompt:
                continue

            # ─── Comandos do Sistema ──────────────────────────────────────────
            if prompt in ["/exit", "exit", "quit", ":q"]:
                print(f"\n{CYAN_NEON}[VINCENT]{CLR_RST} Desconectando núcleo neural. Sessão salva.\n")
                break

            if prompt in ["/models", "/list"]:
                display_models_catalog(agent)
                continue

            if prompt.startswith("/search") or prompt.startswith("/find"):
                parts = prompt.split(maxsplit=1)
                term = parts[1] if len(parts) > 1 else ""
                display_models_catalog(agent, term)
                continue

            if prompt.startswith("/model"):
                parts = prompt.split()
                if len(parts) > 1:
                    target = parts[1]
                    agent.set_model(target)
                    print(f"{GREEN_MATRIX}✔ Sintonizado para o modelo: {agent.display_model}{CLR_RST}\n")
                else:
                    print(f"{AMBER_WARN}Uso: /model <id_do_modelo> (ex: /model qwen2.5-coder:7b ou /model auto/best-free){CLR_RST}\n")
                continue

            if prompt.startswith("/caveman"):
                parts = prompt.split()
                mode = parts[1].lower() if len(parts) > 1 else "full"
                if mode in ["1", "true", "on"]:
                    mode = "full"
                elif mode in ["0", "false"]:
                    mode = "off"

                if agent.set_caveman_mode(mode):
                    if mode != "off":
                        print(f"{GREEN_MATRIX}✔ Caveman Compression ativado ({mode.upper()}) — economia de tokens ativa.{CLR_RST}\n")
                    else:
                        print(f"{AMBER_WARN}✔ Modo Caveman desativado.{CLR_RST}\n")
                else:
                    print(f"{AMBER_WARN}Modos válidos: lite, full, ultra, wenyan-lite, wenyan-full, off{CLR_RST}\n")
                continue

            if prompt.startswith("/gsd") or prompt.startswith("/plan"):
                parts = prompt.split(maxsplit=1)
                if len(parts) > 1:
                    task = parts[1]
                    with NeuralSpinner(f"Orquestrando GSD Multi-Agent Swarm para: '{task}'..."):
                        res = gsd.execute_plan(task)
                    render_response_box(res, agent.model, agent.telemetry.last_latency, agent.caveman.mode)
                else:
                    print(f"{AMBER_WARN}Uso: /gsd <descrição da tarefa>{CLR_RST}\n")
                continue

            if prompt in ["/plugins", "/skills"]:
                if not agent.plugins.skills:
                    print(f"{AMBER_WARN}Nenhum plugin encontrado em ~/.agents/skills/{CLR_RST}\n")
                else:
                    agent.plugins.list_plugins()
                    print(f"{GRAY_MUTED}Uso: /plugin <nome> para ligar/desligar{CLR_RST}\n")
                continue

            if prompt.startswith("/plugin"):
                parts = prompt.split(maxsplit=1)
                if len(parts) < 2:
                    print(f"{AMBER_WARN}Uso: /plugin <nome> (ex: /plugin gsd-quick){CLR_RST}\n")
                else:
                    name = parts[1].strip()
                    result = agent.plugins.toggle(name)
                    if result is None:
                        print(f"{RED_ALERT}Plugin '{name}' não encontrado. Use /plugins para listar.{CLR_RST}\n")
                    else:
                        state = "ATIVADO" if result else "DESATIVADO"
                        print(f"{GREEN_MATRIX}✔ Plugin '{name}' {state}.{CLR_RST}\n")
                continue

            if prompt in ["/squad", "/agents"]:
                gsd.list_squad()
                print()
                continue

            if prompt in ["/stats", "/telemetry"]:
                cards = agent.telemetry.get_summary_cards(agent.display_model, agent.caveman.get_stats())
                render_hud_card("TELEMETRIA PONYTAIL & CAVEMAN", cards, PURPLE_GLOW)
                print()
                continue

            if prompt in ["/devices", "/scan", "/hw"]:
                devs = registry.scan()
                items = [(d.id, f"{d.label} | Porta: {d.port} | Firmware: {d.firmware_id} | Protocolo: {d.protocol or 'Nenhum'}") for d in devs]
                render_hud_card("LABORATÓRIO DE HARDWARE ESP32", items if items else [("STATUS", "Nenhuma placa USB detectada")], MAGENTA_NEON)
                print()
                continue

            if prompt.startswith("/cmd"):
                parts = prompt.split(maxsplit=2)
                if len(parts) >= 3:
                    dev_id, cmd = parts[1], parts[2]
                    res = registry.send(dev_id, cmd, wait=5.0)
                    print(f"{CYAN_NEON}[{dev_id}]{CLR_RST} → {res.get('response', 'sem resposta')}\n")
                else:
                    print(f"{AMBER_WARN}Uso: /cmd <DEVICE_ID> <comando_serial>{CLR_RST}\n")
                continue

            if prompt == "/clear":
                agent._history.clear()
                print(f"{GREEN_MATRIX}✔ Contexto e memória limpos com sucesso.{CLR_RST}\n")
                continue

            if prompt in ["/help", "/?", "help"]:
                render_section_header("CENTRAL DE COMANDOS VINCENT CLI 4.0", "◈", CYAN_NEON)
                print(f"  {CYAN_NEON}/models{CLR_RST}             Lista mais de 1200 modelos categorizados")
                print(f"  {CYAN_NEON}/search <termo>{CLR_RST}     Busca inteligente por modelos e capacidades")
                print(f"  {CYAN_NEON}/model <id>{CLR_RST}         Troca o modelo ativo em tempo real")
                print(f"  {CYAN_NEON}/caveman <modo>{CLR_RST}     Ativa compressão Caveman (lite, full, ultra, off)")
                print(f"  {CYAN_NEON}/gsd <tarefa>{CLR_RST}       Executa tarefa via Swarm Multi-Agente autônomo")
                print(f"  {CYAN_NEON}/squad{CLR_RST}              Exibe agentes do squad (Product, Coder, Auditor, etc.)")
                print(f"  {CYAN_NEON}/plugins{CLR_RST}            Lista plugins/skills instalados (~/.agents/skills)")
                print(f"  {CYAN_NEON}/plugin <nome>{CLR_RST}      Liga/desliga um plugin (injeta no system prompt)")
                print(f"  {CYAN_NEON}/devices{CLR_RST}            Inspeciona placas de hardware conectadas (TEMBED/ESP32DIV)")
                print(f"  {CYAN_NEON}/cmd <dev> <cmd>{CLR_RST}    Envia comando serial direto para a placa")
                print(f"  {CYAN_NEON}/stats{CLR_RST}              Mostra telemetria de latência, CPU e tokens economizados")
                print(f"  {CYAN_NEON}/clear{CLR_RST}              Limpa o histórico da sessão")
                print(f"  {CYAN_NEON}/exit{CLR_RST}               Fecha o Vincent CLI\n")
                continue

            # ─── Execução Padrão de Inferência ────────────────────────────────
            with NeuralSpinner(f"Vincent processando via [{agent.display_model}]..."):
                reply = agent.ask(prompt)

            render_response_box(
                reply,
                agent.display_model,
                agent.telemetry.last_latency,
                mode=f"Caveman ({agent.caveman.mode})" if agent.caveman.mode != "off" else "Standard",
                tokens_saved=agent.caveman.total_tokens_saved
            )

        except KeyboardInterrupt:
            print(f"\n{AMBER_WARN}[Interrompido]{CLR_RST} Digite /exit para fechar o Vincent.\n")
        except EOFError:
            break


def main():
    parser = argparse.ArgumentParser(description="Vincent OS CLI 4.0 — Cyberpunk Neural Orchestrator")
    parser.add_argument("prompt", nargs="*", help="Pergunta ou comando direto para o Vincent")
    parser.add_argument("-m", "--model", default="qwen3:0.6b", help="Modelo inicial (ex: qwen3:0.6b, qwen2.5-coder:7b, auto/best-free)")
    parser.add_argument("-l", "--list-models", action="store_true", help="Listar todos os modelos do catálogo")
    parser.add_argument("-s", "--search", type=str, default="", help="Filtrar modelos por termo de busca")
    parser.add_argument("-c", "--caveman", type=str, default=None, help="Modo caveman (lite, full, ultra)")
    parser.add_argument("-g", "--gsd", type=str, default=None, help="Executar tarefa via GSD Multi-Agent Swarm")
    parser.add_argument("-d", "--devices", action="store_true", help="Listar dispositivos de hardware conectados")
    parser.add_argument("-p", "--plugin", action="append", default=[], help="Ativa plugin/skill por nome (repetível, ex: -p ponytail -p gsd-quick)")
    args = parser.parse_args()

    registry = DeviceRegistry(lambda ev: None)
    agent = VincentAgent(registry, model=args.model)

    if args.caveman:
        agent.set_caveman_mode(args.caveman)

    for plugin_name in args.plugin:
        if agent.plugins.toggle(plugin_name) is None:
            print(f"{AMBER_WARN}Plugin '{plugin_name}' não encontrado.{CLR_RST}")

    if args.list_models or args.search:
        display_models_catalog(agent, args.search)
        return

    if args.devices:
        devs = registry.scan()
        items = [(d.id, f"{d.label} | Porta: {d.port} | Firmware: {d.firmware_id}") for d in devs]
        render_hud_card("HARDWARE CONECTADO", items if items else [("STATUS", "Nenhum dispositivo")], MAGENTA_NEON)
        return

    if args.gsd:
        gsd = GSDOrchestrator(agent)
        with NeuralSpinner(f"GSD Swarm executando: '{args.gsd}'..."):
            res = gsd.execute_plan(args.gsd)
        render_response_box(res, agent.display_model, agent.telemetry.last_latency, agent.caveman.mode)
        return

    if args.prompt:
        question = " ".join(args.prompt)
        registry.scan()
        with NeuralSpinner(f"Vincent processando via [{agent.display_model}]..."):
            reply = agent.ask(question)
        render_response_box(reply, agent.display_model, agent.telemetry.last_latency, agent.caveman.mode)
        return

    # Inicia REPL interativo
    interactive_repl(agent, registry)


if __name__ == "__main__":
    main()
