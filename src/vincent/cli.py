#!/usr/bin/env python3
"""
Vincent CLI 4.0 — Van Gogh 'Starry Night' Cyber-Impressionist Orchestrator.
Integrates 1200+ Whitelabeled Neural Routes, Zero-Key Free Engine, Local Offline Models,
Enterprise Authentication (OAuth2/Key), LlamaFactory Fine-Tuning, Caveman Compression (-65%),
Ponytail Real-time Telemetry, GSD Multi-Agent Swarm, and Termux/ADB Universal Adaptation.
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
from vincent.auth import VincentAuth
from vincent.llama_factory import LlamaFactoryOrchestrator
from vincent.env_detect import PlatformEnvironment
from vincent.ui import (
    BANNER, CLR_RST, CLR_BOLD, CLR_DIM, COBALT_BLUE, PRUSSIAN_BLUE,
    LEMON_YELLOW, CHROME_YELLOW, STARRY_GOLD, CYPRESS_GREEN, CYPRESS_DARK,
    VIOLET_SWIRL, ALERT_SCARLET, CANVAS_WHITE, SHADOW_GRAY,
    NeuralSpinner, render_hud_card, render_section_header, render_response_box,
    get_terminal_width
)


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


def interactive_repl(agent: VincentAgent, registry: DeviceRegistry):
    print(BANNER)
    
    gsd = GSDOrchestrator(agent)
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
        ("GALERIA CLOUD", f"{CYPRESS_GREEN}ONLINE{CLR_RST} (:20128) — {omni_count} obras conectadas"),
        ("ATELIER LOCAL", f"{CYPRESS_GREEN}ONLINE{CLR_RST} (:11434) — {ollama_count} modelos quentes"),
        ("HARDWARE LAB", f"{len(devs)} Placas Conectadas (TEMBED / ESP32DIV)"),
        ("AUTENTICAÇÃO", f"{CYPRESS_GREEN}CONECTADO{CLR_RST} ({auth.identity})" if auth.is_authenticated else f"{STARRY_GOLD}MODO ZERO-KEY (/login ou /key){CLR_RST}"),
        ("AMBIENTE", f"{env_summary['os']} (Modo: {env_summary['layout_mode']})")
    ]
    render_hud_card("TELEMETRIA NOITE ESTRELADA — VINCENT HUD", hud_items, COBALT_BLUE)
    
    print(f"\n{SHADOW_GRAY}Comandos essenciais da Galeria:{CLR_RST}")
    print(f"  {COBALT_BLUE}/models{CLR_RST} (catálogo)    • {COBALT_BLUE}/search <termo>{CLR_RST} (buscar)     • {COBALT_BLUE}/model <id>{CLR_RST} (trocar)")
    print(f"  {COBALT_BLUE}/caveman on|off{CLR_RST} (tokens) • {COBALT_BLUE}/gsd <tarefa>{CLR_RST} (swarm)     • {COBALT_BLUE}/squad{CLR_RST} (agentes)")
    print(f"  {COBALT_BLUE}/login /key <tok>{CLR_RST} (auth) • {COBALT_BLUE}/train /lora{CLR_RST} (finetune)  • {COBALT_BLUE}/export{CLR_RST} (dataset)")
    print(f"  {COBALT_BLUE}/devices{CLR_RST} (hardware)   • {COBALT_BLUE}/cmd <dev> <cmd>{CLR_RST} (serial)  • {COBALT_BLUE}/stats{CLR_RST} (telemetria) • {COBALT_BLUE}/exit{CLR_RST}\n")

    term_w = get_terminal_width()

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
            print(f"{SHADOW_GRAY}─" * min(term_w, 80) + f"{CLR_RST}")
            print(statusline)

            prompt = input(f"{COBALT_BLUE}vincent{CLR_RST} {CHROME_YELLOW}[{agent.display_model}]{CLR_RST} {CLR_BOLD}❯{CLR_RST} ").strip()
            if not prompt:
                continue

            # ── Comandos Especiais do REPL ──────────────────────────────────
            if prompt in ("/exit", "/quit", "exit", "quit", ":q"):
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
                    agent.set_model(new_m)
                else:
                    print(f"{CHROME_YELLOW}Modelo atual:{CLR_RST} {agent.display_model}")
                    print(f"{SHADOW_GRAY}Uso: /model <id_do_modelo> (ex: /model auto/best-coding ou /model qwen3:0.6b){CLR_RST}")
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
                        print(f"{ALERT_SCARLET}Modo inválido. Opções: off, lite, full, ultra, wenyan-lite, wenyan-full{CLR_RST}")
                else:
                    curr = agent.caveman.mode
                    print(f"{STARRY_GOLD}Modo Caveman ativo:{CLR_RST} {curr}")
                    print(f"{SHADOW_GRAY}Uso: /caveman off | lite | full | ultra{CLR_RST}")
                continue

            elif prompt.startswith("/gsd") or prompt.startswith("/plan"):
                parts = prompt.split(maxsplit=1)
                if len(parts) > 1:
                    task = parts[1].strip()
                    with NeuralSpinner(f"GSD Swarm orquestrando onda para: '{task}'...", color=VIOLET_SWIRL):
                        res = gsd.execute_plan(task)
                    render_response_box(res, agent.display_model, agent.telemetry.last_latency, mode="GSD Swarm Plan")
                else:
                    print(f"{VIOLET_SWIRL}Uso:{CLR_RST} /gsd <descrição da tarefa complexa>")
                continue

            elif prompt == "/squad":
                gsd.list_squad()
                continue

            elif prompt in ("/login", "/auth"):
                df = auth.start_device_flow()
                items = [
                    ("CÓDIGO DE DISPOSITIVO", f"{LEMON_YELLOW}{CLR_BOLD}{df['user_code']}{CLR_RST}"),
                    ("URL DE ATIVAÇÃO", f"{COBALT_BLUE}{df['verification_uri']}{CLR_RST}"),
                    ("VALIDADE", f"{df['expires_in']} segundos"),
                    ("INSTRUÇÃO", "Acesse a URL e insira o código acima para vincular sua assinatura da Galeria.")
                ]
                render_hud_card("CONECTAR À GALERIA VINCENT (OAUTH2)", items, COBALT_BLUE)
                auth.complete_device_flow(df['user_code'])
                print(f"{CYPRESS_GREEN}✓ Conectado com sucesso à Galeria Vincent!{CLR_RST}\n")
                continue

            elif prompt.startswith("/key"):
                parts = prompt.split(maxsplit=1)
                if len(parts) > 1:
                    key = parts[1].strip()
                    if auth.login_with_key(key):
                        print(f"{CYPRESS_GREEN}✓ Chave Neural da Galeria registrada com sucesso!{CLR_RST}\n")
                    else:
                        print(f"{ALERT_SCARLET}✗ Chave inválida.{CLR_RST}\n")
                else:
                    print(f"{CHROME_YELLOW}Uso:{CLR_RST} /key <sua_chave_neural>")
                continue

            elif prompt == "/logout":
                auth.logout()
                print(f"{STARRY_GOLD}✓ Sessão desconectada. Operando em modo público / Zero-Key.{CLR_RST}\n")
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

            elif prompt == "/help":
                render_section_header("GUIA DE COMANDOS DA GALERIA VINCENT", "💡", COBALT_BLUE)
                print(f"  {COBALT_BLUE}/models{CLR_RST}               Exibe todas as rotas e modelos de IA indexados")
                print(f"  {COBALT_BLUE}/search <termo>{CLR_RST}        Filtra modelos por palavra-chave (ex: /search free)")
                print(f"  {COBALT_BLUE}/model <id>{CLR_RST}            Sintoniza o modelo ativo em tempo real")
                print(f"  {COBALT_BLUE}/caveman <modo>{CLR_RST}        Ativa compressão extrema de tokens (off, lite, full, ultra)")
                print(f"  {COBALT_BLUE}/gsd <tarefa>{CLR_RST}          Dispara plano autônomo com o Swarm de Agentes")
                print(f"  {COBALT_BLUE}/login | /key <tok>{CLR_RST}   Autenticação e injeção de chave da Galeria")
                print(f"  {COBALT_BLUE}/train | /lora{CLR_RST}        Gera pipeline de fine-tuning LlamaFactory")
                print(f"  {COBALT_BLUE}/export{CLR_RST}                Exporta histórico para dataset de treino")
                print(f"  {COBALT_BLUE}/devices{CLR_RST}              Varre e inspeciona placas ESP32 conectadas")
                print(f"  {COBALT_BLUE}/cmd <dev> <cmd>{CLR_RST}       Envia comando serial direto para a placa")
                print(f"  {COBALT_BLUE}/stats{CLR_RST}                Relatório de telemetria, hardware e economia de tokens")
                print(f"  {COBALT_BLUE}/clear{CLR_RST}                Limpa a tela e o histórico da sessão")
                print(f"  {COBALT_BLUE}/exit{CLR_RST}                 Encerra o CLI\n")
                continue

            # ── Execução de Pergunta / Prompt Normal com Redemoinho Neural ──
            mode_label = f"Caveman ({agent.caveman.mode})" if agent.caveman.mode != "off" else "Standard"
            with NeuralSpinner(f"Pintando resposta com [{agent.display_model}]...", color=COBALT_BLUE):
                reply = agent.ask(prompt)

            render_response_box(
                reply=reply,
                model=agent.display_model,
                latency=agent.telemetry.last_latency,
                mode=mode_label,
                tokens_saved=agent.caveman.total_saved
            )

        except KeyboardInterrupt:
            print(f"\n{SHADOW_GRAY}Pincelada interrompida pelo usuário. Use /exit para sair.{CLR_RST}\n")
        except Exception as e:
            print(f"\n{ALERT_SCARLET}[ERRO VINCENT]: {e}{CLR_RST}\n")


def main():
    parser = argparse.ArgumentParser(description="Vincent CLI 4.0 — Van Gogh 'Starry Night' Cyber-Impressionist Orchestrator")
    parser.add_argument("prompt", nargs="*", help="Pergunta ou comando direto para o Vincent")
    parser.add_argument("-m", "--model", default="qwen3:0.6b", help="Modelo inicial (ex: qwen3:0.6b, qwen2.5-coder:7b, auto/best-free)")
    parser.add_argument("-l", "--list-models", action="store_true", help="Listar todos os modelos do catálogo")
    parser.add_argument("-s", "--search", type=str, default="", help="Filtrar modelos por termo de busca")
    parser.add_argument("-c", "--caveman", type=str, default=None, help="Modo caveman (lite, full, ultra)")
    parser.add_argument("-g", "--gsd", type=str, default=None, help="Executar plano autônomo via GSD Swarm")
    parser.add_argument("-d", "--devices", action="store_true", help="Listar dispositivos de hardware USB conectados")
    parser.add_argument("-t", "--train", action="store_true", help="Gerar configuração de treino LoRA via LlamaFactory")
    parser.add_argument("--auth", action="store_true", help="Exibir status ou conectar à Galeria Vincent")

    args = parser.parse_args()

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

    if args.auth:
        auth = VincentAuth()
        render_hud_card("AUTENTICAÇÃO DA GALERIA", auth.status_card_data(), COBALT_BLUE)
        sys.exit(0)

    if args.gsd:
        gsd = GSDOrchestrator(agent)
        with NeuralSpinner(f"GSD Swarm orquestrando: '{args.gsd}'...", color=VIOLET_SWIRL):
            res = gsd.execute_plan(args.gsd)
        render_response_box(res, agent.display_model, agent.telemetry.last_latency, mode="GSD Swarm Plan")
        sys.exit(0)

    if args.prompt:
        question = " ".join(args.prompt)
        with NeuralSpinner(f"Processando com [{agent.display_model}]...", color=COBALT_BLUE):
            reply = agent.ask(question)
        mode_label = f"Caveman ({agent.caveman.mode})" if agent.caveman.mode != "off" else "Standard"
        render_response_box(reply, agent.display_model, agent.telemetry.last_latency, mode=mode_label, tokens_saved=agent.caveman.total_saved)
        sys.exit(0)

    # Entra no REPL interativo futurista
    interactive_repl(agent, registry)


if __name__ == "__main__":
    main()
