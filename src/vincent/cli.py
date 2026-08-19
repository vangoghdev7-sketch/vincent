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
import re
import shutil
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
    get_terminal_width, diff_lines, colorize_diff_line
)
from vincent.agent_tools import build_edit_preview, is_edit_tool

# Camadas opcionais: sem elas o REPL continua exatamente como antes (texto puro).
try:
    from vincent import interactive as interactive
    _HAS_INTERACTIVE = True
except Exception:  # pragma: no cover - ambiente sem prompt_toolkit
    interactive = None
    _HAS_INTERACTIVE = False

try:
    from vincent import marketplace as marketplace
    _HAS_MARKETPLACE = True
except Exception:  # pragma: no cover
    marketplace = None
    _HAS_MARKETPLACE = False


def _style_trace(step: str) -> str:
    """Colore uma linha do trace ao vivo do loop agêntico conforme o tipo de evento
    (pensamento / execução de ferramenta / saída), estilo Claude Code."""
    colored_diff = colorize_diff_line(step)
    if colored_diff:
        return colored_diff
    s = step.lstrip()
    if s.startswith("🧠"):
        return f"{VIOLET_SWIRL}{step}{CLR_RST}"
    if s.startswith("⚙️") or s.startswith("⚙"):
        return f"{CHROME_YELLOW}{CLR_BOLD}{step}{CLR_RST}"
    if s.startswith("↳"):
        return f"{SHADOW_GRAY}{step}{CLR_RST}"
    return f"{CANVAS_WHITE}{step}{CLR_RST}"


def make_permission_asker():
    """Cria o `permission_callback` do REPL (estilo Claude Code): com /autoedit
    off, o loop agêntico chama isto antes de rodar comando/editar/commitar.

    Em edição de arquivo o diff colorido vem ANTES da pergunta — ninguém
    aprova às cegas. "sempre" é POR FERRAMENTA: autorizar um read_file
    inofensivo não pode liberar run_bash pelo resto da sessão (era isso que
    agent.autoedit=True fazia). /autoedit on continua liberando tudo, mas aí
    foi pedido.
    """
    always_ok: set = set()

    def _liberar_sempre(tool_name: str) -> bool:
        always_ok.add(tool_name)
        print(f"{CYPRESS_GREEN}✓ '{tool_name}' liberada nesta sessão "
              f"{SHADOW_GRAY}(as outras ferramentas continuam perguntando).{CLR_RST}")
        return True

    def _ask_permission(tool_name, args):
        preview = ""
        if isinstance(args, dict):
            preview = str(args.get("command") or args.get("path") or args.get("filepath") or args.get("code") or args.get("url") or args.get("message") or (next(iter(args.values())) if args else ""))
        else:
            preview = str(args or "")
        preview = preview.replace("\n", " ")[:90]
        # Preview de diff: antes de aprovar uma edição o usuário vê exatamente
        # o que muda (verde/vermelho, com número de linha e contexto).
        diff: list = []
        if is_edit_tool(tool_name):
            try:
                diff = diff_lines(build_edit_preview(tool_name, args if isinstance(args, dict) else {}),
                                  title=str((args or {}).get("path") or "") if isinstance(args, dict) else "")
            except Exception:
                diff = []
        if tool_name in always_ok:
            # Liberada nesta sessão ≠ invisível: o diff continua saindo, senão o
            # "sempre" transforma toda edição seguinte em aprovação às cegas —
            # e o agente não emite o preview no trace quando há callback.
            for line in diff:
                print(colorize_diff_line(line) or line)
            return True
        if _HAS_INTERACTIVE:
            answer = interactive.confirm_permission(tool_name, preview, diff)
            if answer == "always":
                return _liberar_sempre(tool_name)
            return answer == "yes"
        for line in diff:
            print(colorize_diff_line(line) or line)
        try:
            ans = input(f"\n{CHROME_YELLOW}  ⚠ Permitir {tool_name}{(' › ' + preview) if preview else ''}? "
                        f"{SHADOW_GRAY}[s = sim / N = não / a = sempre]{CHROME_YELLOW} {CLR_RST}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        # Sem prompt_toolkit o "sempre" também tem que existir, senão o modo
        # texto puro obriga a responder a cada edição.
        if ans in ("a", "always", "sempre"):
            return _liberar_sempre(tool_name)
        return ans in ("s", "sim", "y", "yes")

    return _ask_permission


def _spinner_step(spinner):
    """Callback de passo pros modos one-shot (`--agent` / prompt direto).

    Passo comum vira mensagem do spinner (transitória), mas linha de diff vai
    pro log PERSISTENTE: um preview de edição que pisca e some não serve pra
    nada — é justamente o que o usuário precisa ler antes da escrita."""
    def _on_step(step: str) -> None:
        colored = colorize_diff_line(step)
        if colored:
            spinner.log(colored)
        else:
            spinner.update_message(f"Vincent: {step}")
    return _on_step


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


def _has_tty() -> bool:
    """Terminal de verdade dos dois lados? Sem isso, nada de tela cheia/paginação."""
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False


def _print_paged(lines, show_all: bool = False):
    """Imprime uma lista de linhas em páginas ('-- mais --'). Nada de becos sem
    saída do tipo '+35 adicionais': ou pagina de verdade, ou cospe tudo."""
    if show_all or not _has_tty():
        for line in lines:
            print(line)
        return
    try:
        page = max(5, shutil.get_terminal_size((80, 24)).lines - 4)
    except Exception:
        page = 20
    for i, line in enumerate(lines):
        print(line)
        if (i + 1) % page == 0 and (i + 1) < len(lines):
            restam = len(lines) - (i + 1)
            try:
                ans = input(f"{SHADOW_GRAY}-- mais -- ({restam} linhas) "
                            f"[Enter=continua · a=tudo · q=sai]{CLR_RST} ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if ans == "q":
                return
            if ans == "a":
                page = len(lines) + 1


def display_models_catalog(agent: VincentAgent, search_term: str = "", show_all: bool = False):
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

    lines = []
    if local_models:
        lines.append(f"\n{CYPRESS_GREEN}◈ PALETA LOCAL OFFLINE ZERO-KEY ({len(local_models)}):{CLR_RST} {SHADOW_GRAY}(Zero Latência / Sem Internet / Sem Chave){CLR_RST}")
        for m in local_models:
            lines.append(f"  {CYPRESS_GREEN}⚡{CLR_RST} {CLR_BOLD}{m['display_id']:<28}{CLR_RST} {SHADOW_GRAY}→ {m['name']}{CLR_RST}")

    if combos:
        lines.append(f"\n{COBALT_BLUE}◈ COMBOS DE HARMONIA DINÂMICA ({len(combos)}):{CLR_RST}")
        for m in combos:
            lines.append(f"  {COBALT_BLUE}◆{CLR_RST} {m['display_id']:<28} {SHADOW_GRAY}[Failover Automático / Whitelabel]{CLR_RST}")

    if free_models:
        lines.append(f"\n{STARRY_GOLD}◈ ROTAS PÚBLICAS ZERO-KEY ({len(free_models)}):{CLR_RST}")
        for m in free_models:
            lines.append(f"  {LEMON_YELLOW}🆓{CLR_RST} {m['display_id']:<32} {SHADOW_GRAY}(Atelier Aberto){CLR_RST}")

    if pro_models:
        lines.append(f"\n{VIOLET_SWIRL}◈ ATELIER AVANÇADO / PRO ({len(pro_models)}):{CLR_RST}")
        for m in pro_models:
            lines.append(f"  {VIOLET_SWIRL}▲{CLR_RST} {m['display_id']:<32} {SHADOW_GRAY}(Galeria Pro){CLR_RST}")

    _print_paged(lines, show_all=show_all)
    print(f"\n{SHADOW_GRAY}Sintonia: /model <id> (sem id abre o navegador) │ Busca: /search <termo> │ "
          f"Lista inteira de uma vez: /models all │ Total: {len(all_models)} modelos{CLR_RST}\n")


# ── Registro central de comandos ──────────────────────────────────────────────
# Fonte única da verdade: alimenta o autocomplete, a paleta (Ctrl+P), o /help e
# os apelidos sem barra. Mexeu no dispatch? Mexe aqui também.
COMMANDS = [
    # Agente
    {"cmd": "/act", "args": "<tarefa>", "group": "Agente", "aliases": ["/agent"],
     "desc": "Agentic Loop: investiga e altera código com ferramentas"},
    {"cmd": "/auto", "args": "<objetivo>", "group": "Agente",
     "desc": "Modo autônomo contínuo — trabalha até terminar (máx 40 passos)"},
    {"cmd": "/bg", "args": "<tarefa>", "group": "Agente",
     "desc": "Roda a tarefa em segundo plano, sem travar o REPL"},
    {"cmd": "/spawn", "args": "<n> <t1>; <t2>", "group": "Agente",
     "desc": "N workers paralelos de verdade (separe as tarefas por ';')"},
    {"cmd": "/autoedit", "args": "on|off", "group": "Agente",
     "desc": "off = pede permissão antes de rodar comando/editar/commitar"},
    {"cmd": "/effort", "args": "low|medium|high", "group": "Agente",
     "desc": "Profundidade do raciocínio do modelo"},
    # Modelos
    {"cmd": "/models", "args": "[all]", "group": "Modelos",
     "desc": "Navegador do catálogo inteiro (Enter sintoniza) — 'all' cospe tudo em texto"},
    {"cmd": "/search", "args": "<termo>", "group": "Modelos",
     "desc": "Abre o navegador de modelos já filtrado pelo termo"},
    {"cmd": "/model", "args": "[id]", "group": "Modelos",
     "desc": "Sintoniza o modelo ativo — sem id abre o picker fuzzy (Ctrl+O)"},
    {"cmd": "/caveman", "args": "off|lite|full|ultra", "group": "Modelos",
     "desc": "Compressão extrema de tokens (-65%)"},
    {"cmd": "/gateway", "args": "", "group": "Modelos",
     "desc": "Status do gateway OmniRoute (circuito, cooldown, modelos)"},
    # Skills
    {"cmd": "/skills", "args": "", "group": "Skills",
     "desc": "Lista as skills instaladas"},
    {"cmd": "/skill", "args": "add <git-url>", "group": "Skills",
     "desc": "Clona um repo de skills pra ~/.vincent/skills"},
    {"cmd": "/marketplace", "args": "[install <nome|url>]", "group": "Skills",
     "aliases": ["/market", "/store"],
     "desc": "Navegador de skills do catálogo — instala com Enter"},
    {"cmd": "/reload-plugins", "args": "", "group": "Skills",
     "aliases": ["/reload", "/reload_plugins"],
     "desc": "Recarrega plugins e skills do disco"},
    # Estúdio (interface)
    {"cmd": "/tui", "args": "[workers]", "group": "Estúdio",
     "desc": "TUI de tela cheia (Ctrl+T) — 'workers' abre o painel ao vivo das tarefas"},
    {"cmd": "/config", "args": "", "group": "Estúdio",
     "desc": "Painel visual (setas) de chaves e modelo ativo"},
    {"cmd": "/help", "args": "", "group": "Estúdio",
     "desc": "Paleta navegável de comandos (Ctrl+P)"},
    {"cmd": "/clear", "args": "", "group": "Estúdio", "aliases": ["/cls"],
     "desc": "Limpa a tela e redesenha o banner"},
    # Ferramentas
    {"cmd": "/vision", "args": "<img> [pergunta]", "group": "Ferramentas",
     "desc": "Analisa uma imagem via modelo multimodal"},
    {"cmd": "/commit", "args": "<msg>", "group": "Ferramentas",
     "desc": "Checkpoint git manual (Conventional Commits)"},
    {"cmd": "/export", "args": "", "group": "Ferramentas",
     "desc": "Exporta o histórico da sessão como dataset de treino"},
    {"cmd": "/train", "args": "", "group": "Ferramentas", "aliases": ["/lora"],
     "desc": "Gera o pipeline de fine-tuning LlamaFactory"},
    {"cmd": "/stats", "args": "", "group": "Ferramentas",
     "desc": "Telemetria, hardware e economia de tokens"},
    # Hardware
    {"cmd": "/devices", "args": "", "group": "Hardware",
     "desc": "Varre e inspeciona as placas ESP32/USB conectadas"},
    {"cmd": "/cmd", "args": "<dev> <comando>", "group": "Hardware",
     "desc": "Envia comando serial direto pra placa"},
    # Chaves
    {"cmd": "/vault", "args": "", "group": "Chaves", "aliases": ["/auth", "/login"],
     "desc": "Cofre de chaves local (chmod 0600)"},
    {"cmd": "/key", "args": "[chave]", "group": "Chaves",
     "desc": "Registra a chave da Galeria Vincent no cofre"},
    # Sessão
    {"cmd": "/exit", "args": "", "group": "Sessão", "aliases": ["/quit"],
     "desc": "Encerra o CLI"},
]

# Apelidos sem barra ("models" == "/models"), derivados do registro acima.
BARE_COMMAND_ALIASES = {
    name.split()[0].lstrip("/").lower()
    for c in COMMANDS
    for name in [c["cmd"], *c.get("aliases", [])]
}


def normalize_bare_command(prompt: str) -> str:
    """'models' vira '/models'. Só a linha INTEIRA vale como apelido.

    Derivar os apelidos do registro trouxe palavras comuns de prosa — auto,
    store, reload. Com a regra por primeira-palavra, "auto conserta o bug do
    login" virava "/auto ..." e disparava o modo autônomo de 40 passos com
    ferramentas (e autoedit nasce True, então rodava bash sem perguntar).
    """
    bare = prompt.strip()
    if not bare.startswith("/") and bare.lower() in BARE_COMMAND_ALIASES:
        return "/" + bare
    return prompt


# ─── Menções a arquivo (@caminho) ─────────────────────────────────────────────
# Não bate depois de letra/dígito: "fulano@gmail.com" não é menção. O caminho
# pode ter ~, /, ponto e hífen; pontuação final da frase fica de fora.
MENTION_RE = re.compile(r"(?<![\w@/])@([~/\w.\-][\w.\-/]*)")
MENTION_MAX_LINES = 400        # por arquivo
MENTION_MAX_CHARS = 12000      # por arquivo, teto que o limite de linhas não pega
MENTION_MAX_FILES = 10         # por mensagem
MENTION_DIR_ENTRIES = 60       # ao citar um diretório
MENTION_MAX_BYTES = 2 * 1024 * 1024   # acima disso o arquivo não é lido inteiro

# Comandos que carregam tarefa em texto livre — só neles (e no chat) a menção
# é expandida. '/model @x' ou '/commit fix @v2' continuam literais.
MENTION_COMMANDS = ("/act", "/agent", "/auto", "/bg")


def _cap_chars(body: str, shown: int):
    """Aplica o teto de caracteres cortando em borda de linha.

    400 linhas não seguram um .js minificado (megabytes numa linha só), e o
    prompt inteiro ia junto pro modelo. Devolve (corpo, linhas_mantidas,
    caracteres_cortados).
    """
    if len(body) <= MENTION_MAX_CHARS:
        return body, shown, 0
    mantidas, usado = [], 0
    for linha in body.splitlines(keepends=True):
        if usado + len(linha) > MENTION_MAX_CHARS:
            break
        mantidas.append(linha)
        usado += len(linha)
    if not mantidas:                       # uma única linha maior que o teto
        mantidas = [body[:MENTION_MAX_CHARS] + "\n"]
        usado = MENTION_MAX_CHARS
    return "".join(mantidas), len(mantidas), len(body) - usado


def _read_mention_head(abs_path: str, rel: str, tamanho: int):
    """Cabeça de um arquivo grande demais pra ler inteiro.

    tool_read_file faz readlines() do arquivo todo antes de fatiar — citar um
    log de 2 GB ou um .gguf congelava o REPL (e só DEPOIS descobria que era
    binário). Aqui só os primeiros bytes saem do disco.
    """
    try:
        with open(abs_path, "rb") as fh:
            head = fh.read(MENTION_MAX_CHARS * 4).decode("utf-8", "replace")
    except OSError as exc:
        return None, f"✗ @{rel}: {exc.strerror or exc}"
    if "\x00" in head:
        return None, f"✗ @{rel}: arquivo binário, não anexado"

    linhas = head.splitlines(keepends=True)[:MENTION_MAX_LINES]
    numeradas = "".join(f"{i:4d} | {ln}" for i, ln in enumerate(linhas, start=1))
    body, shown, _ = _cap_chars(numeradas, len(linhas))
    mb = tamanho / (1024 * 1024)
    body += (f"\n… truncado: arquivo de {mb:.1f} MB, só as primeiras {shown} "
             f"linha(s) entraram (use read_file em {rel} pra ver o resto)\n")
    return (f"[arquivo: {rel}] {mb:.1f} MB\n```\n{body}```",
            f"◈ @{rel} — {shown} linha(s) de um arquivo de {mb:.1f} MB")


def _read_mention(abs_path: str, rel: str):
    """(bloco_pro_modelo, nota_pro_usuário) de UM arquivo citado."""
    from vincent.agent_tools import tool_read_file

    try:
        tamanho = os.path.getsize(abs_path)
    except OSError as exc:
        return None, f"✗ @{rel}: {exc.strerror or exc}"
    if tamanho > MENTION_MAX_BYTES:
        return _read_mention_head(abs_path, rel, tamanho)

    res = tool_read_file(abs_path, 1, MENTION_MAX_LINES)
    if res.get("error"):
        return None, f"✗ @{rel}: {res['error']}"
    if "\x00" in res.get("raw_content", ""):
        return None, f"✗ @{rel}: arquivo binário, não anexado"

    total, shown = int(res["total_lines"]), int(res["end_line"])
    body, shown, chars_cortados = _cap_chars(res["content"], shown)
    corte = total - shown
    header = f"[arquivo: {rel}] {total} linha(s)"
    if corte > 0:
        body += (f"\n… truncado: {corte} de {total} linhas cortadas "
                 f"(use read_file em {rel} pra ver o resto)\n")
        nota = f"◈ @{rel} — {shown}/{total} linhas ({corte} cortadas)"
    elif chars_cortados:
        body += (f"\n… truncado: linha longa demais, {chars_cortados} caractere(s) "
                 f"cortados (use read_file em {rel} pra ver o resto)\n")
        nota = f"◈ @{rel} — {total} linha(s), {chars_cortados} caractere(s) cortados"
    else:
        nota = f"◈ @{rel} — {total} linha(s)"
    return f"{header}\n```\n{body}```", nota


def _read_mention_dir(abs_path: str, rel: str):
    from vincent.agent_tools import tool_list_dir

    res = tool_list_dir(abs_path, max_depth=1)
    if res.get("error"):
        return None, f"✗ @{rel}: {res['error']}"
    entries = res.get("entries", [])
    linhas = [("📁 " if e.get("type") == "dir" else "📄 ") + str(e.get("path"))
              for e in entries[:MENTION_DIR_ENTRIES]]
    sobra = len(entries) - len(linhas)
    if sobra > 0:
        linhas.append(f"… e mais {sobra} entrada(s)")
    corpo = "\n".join(linhas) or "(vazio)"
    return (f"[diretório: {rel}] {len(entries)} entrada(s)\n```\n{corpo}\n```",
            f"◈ @{rel}/ — {len(entries)} entrada(s)")


def expand_mentions(prompt: str, root: str = None):
    """Anexa ao prompt o conteúdo dos arquivos citados com '@caminho'.

    Devolve (prompt_expandido, notas). O texto original fica intacto — o
    conteúdo entra num bloco no fim, truncado por arquivo (avisando quantas
    linhas foram cortadas) e limitado a MENTION_MAX_FILES arquivos. Menção que
    não existe em disco é deixada em paz (pode ser só uma arroba na frase).
    """
    root = os.path.abspath(root or os.getcwd())
    blocos, notas, vistos = [], [], set()
    for m in MENTION_RE.finditer(prompt or ""):
        # A barra final também sai: o autocomplete insere '@src/' pra diretório,
        # e sem isso a nota virava '@src//' e '@src' entrava duas vezes.
        rel = m.group(1).rstrip("/.,;:!?)]}'\"")
        if not rel or rel in vistos:
            continue
        alvo = os.path.expanduser(rel)
        alvo = alvo if os.path.isabs(alvo) else os.path.join(root, alvo)
        if not os.path.exists(alvo):
            continue
        vistos.add(rel)
        if len(vistos) > MENTION_MAX_FILES:
            notas.append(f"⚠ @{rel} ignorado — limite de {MENTION_MAX_FILES} anexos por mensagem")
            continue
        bloco, nota = (_read_mention_dir(alvo, rel) if os.path.isdir(alvo)
                       else _read_mention(alvo, rel))
        if bloco:
            blocos.append(bloco)
        notas.append(nota)

    if not blocos:
        return prompt, notas
    anexo = "\n\n".join(blocos)
    return (f"{prompt}\n\n--- Conteúdo dos arquivos citados ---\n{anexo}", notas)


def apply_mentions(prompt: str) -> str:
    """Expande '@caminho' e imprime as notas no tema. Devolve o prompt final.

    Vive aqui (e não dentro de agentic_run) porque a expansão é da entrada do
    usuário: quem chama o loop de novo com texto do modelo não pode reanexar.
    """
    if "@" not in (prompt or ""):
        return prompt
    prompt, notas = expand_mentions(prompt)
    for nota in notas:
        cor = ALERT_SCARLET if nota.startswith(("✗", "⚠")) else CYPRESS_GREEN
        print(f"{cor}{nota}{CLR_RST}")
    return prompt


def interactive_repl(agent: VincentAgent, registry: DeviceRegistry):
    # Num terminal curto o banner de 11 linhas empurra o HUD pra fora da tela
    # antes do primeiro prompt — aí ele vira só uma linha de assinatura.
    if shutil.get_terminal_size((80, 24)).lines >= 30:
        print(BANNER)
    else:
        print(f"\n{COBALT_BLUE}◈ VINCENT CLI{CLR_RST} {SHADOW_GRAY}— Noite Estrelada{CLR_RST}")

    auth = VincentAuth()
    trainer = LlamaFactoryOrchestrator()
    devs = registry.scan()
    
    # HUD Telemetria Inicial Starry Night
    omni_count, ollama_count = agent.model_manager.sync_catalogs()
    # sync_catalogs conta ROTAS cruas; o catálogo do /models conta display_ids
    # únicos. Mostrar só o primeiro fazia o HUD dizer 482 e o /models dizer 343.
    try:
        catalogo_n = len(agent.model_manager.get_all_models() or [])
    except Exception:
        catalogo_n = 0
    is_free = agent.model_manager.is_free_tier(agent.model)
    env_summary = PlatformEnvironment.get_device_summary()
    
    hud_items = [
        ("NÚCLEO NEURAL", f"{CYPRESS_GREEN}ATIVO{CLR_RST} ({agent.display_model})"),
        ("TIPO DE ROTA", f"{CYPRESS_GREEN}ZERO-KEY / OFFLINE 🆓{CLR_RST}" if is_free else f"{VIOLET_SWIRL}GALERIA PRO ⚡{CLR_RST}"),
        ("GALERIA CLOUD", (f"{CYPRESS_GREEN}ONLINE{CLR_RST}" if omni_count > 0 else f"{ALERT_SCARLET}OFFLINE{CLR_RST}")
                          + f" (:20128) — {omni_count} rotas → {catalogo_n} obras no /models"),
        ("ATELIER LOCAL", f"{CYPRESS_GREEN}ONLINE{CLR_RST} (:11434) — {ollama_count} modelos quentes" if ollama_count > 0 else f"{ALERT_SCARLET}OFFLINE{CLR_RST} (:11434) — {ollama_count} modelos quentes"),
        ("HARDWARE LAB", f"{len(devs)} Placas Conectadas (TEMBED / ESP32DIV)"),
        ("KEY VAULT (0600)", f"{CYPRESS_GREEN}CHAVES ATIVAS{CLR_RST} ({auth.identity})" if auth.is_authenticated else f"{STARRY_GOLD}MODO ZERO-KEY (/vault){CLR_RST}"),
        ("AMBIENTE", f"{env_summary['os']} (Modo: {env_summary['layout_mode']})")
    ]
    render_hud_card("TELEMETRIA NOITE ESTRELADA — VINCENT HUD", hud_items, COBALT_BLUE)
    
    # Antes eram 6 linhas repetindo o que o menu de '/' e o /help já mostram.
    print(f"\n  {COBALT_BLUE}/act <tarefa>{CLR_RST} agentic • {COBALT_BLUE}/models{CLR_RST} catálogo • "
          f"{COBALT_BLUE}/marketplace{CLR_RST} skills • {COBALT_BLUE}/config{CLR_RST} painel • {COBALT_BLUE}/exit{CLR_RST}")
    print(f"  {SHADOW_GRAY}Digite {CHROME_YELLOW}/{SHADOW_GRAY} pra abrir o menu de comandos, "
          f"ou {CHROME_YELLOW}/help{SHADOW_GRAY} pro guia completo.{CLR_RST}\n")

    term_w = get_terminal_width()

    agent.permission_callback = make_permission_asker()

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

    # ── Sessão interativa (prompt_toolkit): histórico, autocomplete, toolbar ──
    def _status():
        """Estado ao vivo pra bottom toolbar — chamado a cada redesenho."""
        lat = agent.telemetry.last_latency
        tier = "🆓 zero-key" if agent.model_manager.is_free_tier(agent.model) else "⚡ pro"
        return {
            "model": agent.display_model,
            "effort": agent.model_manager.effort,
            "caveman": agent.caveman.mode,
            "autoedit": "on" if agent.autoedit else "off",
            "tier": f"{tier} cloud{'●' if omni_count > 0 else '○'} local{'●' if ollama_count > 0 else '○'}",
            "latency": f"{lat:.2f}s" if lat and lat > 0 else None,
        }

    session = None
    if _HAS_INTERACTIVE:
        try:
            session = interactive.build_session(agent, COMMANDS, _status)
            if session is not None:
                # Ctrl+T sai da linha com "/tui" — o dispatch abaixo cuida do resto.
                session.key_bindings.add("c-t")(lambda event: event.app.exit(result="/tui"))
        except Exception:
            session = None

    if session is not None:
        print(f"{SHADOW_GRAY}Atalhos: {CHROME_YELLOW}Ctrl+O{SHADOW_GRAY} modelos · "
              f"{CHROME_YELLOW}Ctrl+P{SHADOW_GRAY} paleta · "
              f"{CHROME_YELLOW}Ctrl+T{SHADOW_GRAY} tela cheia ({CHROME_YELLOW}vincent --tui{SHADOW_GRAY}) · "
              f"{CHROME_YELLOW}@arq{SHADOW_GRAY} completa caminho · "
              f"{CHROME_YELLOW}Alt+Enter{SHADOW_GRAY} nova linha · {CHROME_YELLOW}Ctrl+D{SHADOW_GRAY} sai.{CLR_RST}\n")

    def _interactive_ready() -> bool:
        """True quando dá pra abrir picker/paleta (lib + TTY)."""
        return bool(_HAS_INTERACTIVE and interactive.supports_interactive())

    def _print_help():
        render_section_header("GUIA DE COMANDOS DA GALERIA VINCENT", "💡", COBALT_BLUE)
        for group in dict.fromkeys(c["group"] for c in COMMANDS):
            print(f"\n{VIOLET_SWIRL}◈ {group.upper()}{CLR_RST}")
            for c in (x for x in COMMANDS if x["group"] == group):
                usage = f"{c['cmd']} {c['args']}".strip()
                extra = f" {SHADOW_GRAY}({', '.join(c['aliases'])}){CLR_RST}" if c.get("aliases") else ""
                print(f"  {COBALT_BLUE}{usage:<26}{CLR_RST} {SHADOW_GRAY}{c['desc']}{CLR_RST}{extra}")
        print(f"\n{SHADOW_GRAY}Sem barra vale quando a linha É só o comando: 'models' == '/models' "
              f"(com argumento, vira conversa). Ctrl+P abre esta lista navegável.{CLR_RST}\n")

    def _marketplace(rest: str):
        """Navegador de skills — picker quando dá, texto quando não dá."""
        if not _HAS_MARKETPLACE:
            print(f"{ALERT_SCARLET}✗ Marketplace indisponível nesta instalação.{CLR_RST}\n")
            return
        parts = rest.split(maxsplit=1)
        verb = parts[0].lower() if parts else ""
        arg = parts[1].strip() if len(parts) > 1 else ""

        def _install(ref: str):
            with NeuralSpinner(f"Instalando '{ref}'...", color=VIOLET_SWIRL):
                res = marketplace.install(ref)
            cor = CYPRESS_GREEN if res["ok"] else ALERT_SCARLET
            print(f"{cor}{'✓' if res['ok'] else '✗'} {res['msg']}{CLR_RST}\n")

        if verb in ("install", "instalar", "add"):
            if not arg:
                print(f"{VIOLET_SWIRL}Uso:{CLR_RST} /marketplace install <nome|git-url>\n")
            else:
                _install(arg)
            return

        term = rest.strip()
        items = marketplace.search(term)
        if not items:
            print(f"{SHADOW_GRAY}Nenhuma skill bate com '{term}'.{CLR_RST}\n")
            return
        if not _interactive_ready():
            print(marketplace.render_text(items))
            print(f"{SHADOW_GRAY}Instale com /marketplace install <nome|url>.{CLR_RST}\n")
            return

        chosen = interactive.FuzzyPicker(
            items,
            title="MARKETPLACE DE SKILLS",
            subtitle="Enter instala a skill selecionada",
            group_key=lambda i: "◈ INSTALADAS" if i.get("installed") else "◈ DISPONÍVEIS",
            render_row=lambda i, sel: (
                f"{'●' if i.get('installed') else '○'} {str(i.get('name','')):<18.18} "
                f"{str(i.get('title','')):<28.28} {str(i.get('desc',''))[:44]}"
            ),
            initial_query="",
        ).run()
        if not chosen:
            return
        if chosen.get("installed"):
            estado = "ativa" if chosen.get("active") else "instalada (inativa)"
            print(f"{STARRY_GOLD}◆ '{chosen['name']}' já está {estado}.{CLR_RST}\n")
            return
        _install(chosen["name"])

    pending = None  # comando escolhido na paleta, executado na próxima volta

    while True:
        try:
            while not bg_results.empty():
                bg_id, bg_task, bg_res = bg_results.get_nowait()
                print(f"\n{CYPRESS_GREEN}◈ Tarefa em segundo plano #{bg_id} concluída:{CLR_RST} '{bg_task}'")
                render_response_box(bg_res, agent.display_model, agent.telemetry.last_latency, mode=f"Background #{bg_id}")
        except Exception as e:
            print(f"\n{ALERT_SCARLET}⚠ Erro no processamento de background: {e}{CLR_RST}")

        try:
            if pending:
                prompt, pending = pending, None
            else:
                # Com a sessão rica, o statusline vira a bottom toolbar ao vivo —
                # reimprimir aqui só poluiria a tela a cada volta.
                if session is None:
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
                    if _HAS_INTERACTIVE:
                        prompt = interactive.read_prompt(session, agent).strip()
                    else:
                        prompt = input(f"{COBALT_BLUE}vincent{CLR_RST} {CHROME_YELLOW}[{agent.display_model}]{CLR_RST} {CLR_BOLD}❯{CLR_RST} ").strip()
                except (EOFError, KeyboardInterrupt):
                    print(f"\n{COBALT_BLUE}◈ Sessão encerrada. As estrelas continuam brilhando na galeria. Até logo!{CLR_RST}\n")
                    break
            if not prompt:
                continue

            # Aceita o nome do comando sem a barra (ex: "models" == "/models"),
            # igual já acontecia com exit/clear — agora vale pra todos.
            prompt = normalize_bare_command(prompt)
            cmd_word = prompt.split(None, 1)[0].lower()

            # '@arquivo' vira contexto de verdade (chat e comandos de tarefa).
            if not prompt.startswith("/") or cmd_word in MENTION_COMMANDS:
                prompt = apply_mentions(prompt)

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

            elif prompt in ("/clear", "/cls", "clear", "cls"):
                os.system("clear" if os.name == "posix" else "cls")
                print(BANNER)
                continue

            elif cmd_word in ("/models", "/search"):
                parts = prompt.split(maxsplit=1)
                term = parts[1].strip() if len(parts) > 1 else ""
                if cmd_word == "/models" and term.lower() == "all":
                    display_models_catalog(agent, show_all=True)
                elif _interactive_ready():
                    interactive.browse_models(agent, term)
                else:
                    display_models_catalog(agent, search_term=term)
                continue

            elif cmd_word == "/model":
                parts = prompt.split(maxsplit=1)
                new_m = parts[1].strip() if len(parts) > 1 else ""

                def _tune(mid):
                    try:
                        agent.set_model(mid)
                        print(f"{CYPRESS_GREEN}✓ Modelo ativo alterado para: {agent.display_model}{CLR_RST}\n")
                    except Exception as e:
                        print(f"{ALERT_SCARLET}✗ Falha ao trocar de modelo: {e}{CLR_RST}\n")

                if not new_m:
                    # Sem argumento: picker fuzzy do catálogo inteiro.
                    if _interactive_ready():
                        chosen = interactive.pick_model(agent)
                        if chosen:
                            _tune(chosen)
                    else:
                        print(f"{CHROME_YELLOW}Modelo atual:{CLR_RST} {agent.display_model}")
                        print(f"{SHADOW_GRAY}Uso: /model <id_do_modelo> (ex: /model auto/best-coding ou /model qwen3:0.6b){CLR_RST}")
                    continue

                catalogo = agent.model_manager.get_all_models() or []
                conhecidos = {m["display_id"] for m in catalogo} | {m["id"] for m in catalogo}
                termo = new_m.lower()
                candidatos = [m for m in catalogo
                              if termo in m["display_id"].lower()
                              or termo in str(m.get("name", "")).lower()
                              or termo in str(m.get("provider", "")).lower()]
                if new_m in conhecidos or not candidatos:
                    # Bate exato, ou nem parece com nada indexado: respeita o que
                    # o usuário digitou (pode ser um modelo novo do backend).
                    _tune(new_m)
                elif _interactive_ready():
                    # Parcial: em vez de erro seco, abre o picker JÁ filtrado.
                    chosen = interactive.pick_model(agent, initial_query=new_m)
                    if chosen:
                        _tune(chosen)
                    else:
                        print(f"{SHADOW_GRAY}Mantido: {agent.display_model}{CLR_RST}\n")
                else:
                    print(f"{CHROME_YELLOW}'{new_m}' não é um id exato. Candidatos ({len(candidatos)}):{CLR_RST}")
                    _print_paged([f"  {COBALT_BLUE}◆{CLR_RST} {m['display_id']}" for m in candidatos])
                    print(f"{SHADOW_GRAY}Use /model <id exato>.{CLR_RST}\n")
                continue

            elif cmd_word in ("/marketplace", "/market", "/store"):
                parts = prompt.split(maxsplit=1)
                _marketplace(parts[1].strip() if len(parts) > 1 else "")
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
                    # '@arquivo' expande DEPOIS do split: o anexo vai no fim do
                    # texto, e expandir antes jogaria o conteúdo (com ';' dentro)
                    # só no último worker.
                    subtasks = [apply_mentions(t) for t in subtasks]
                    batch_id = _spawn_parallel(subtasks)
                    print(f"{VIOLET_SWIRL}◈ Lote #{batch_id} disparado: {len(subtasks)} workers em paralelo.{CLR_RST}")
                    print(f"{SHADOW_GRAY}Continue trabalhando — status de cada worker aparece aqui conforme termina.{CLR_RST}\n")
                else:
                    print(f"{VIOLET_SWIRL}Uso:{CLR_RST} /spawn <n> <tarefa1>; <tarefa2>; ... (ou uma tarefa só = N tentativas em paralelo)")
                continue

            elif cmd_word == "/skill":
                _p = prompt.split(maxsplit=2)
                url = _p[2].strip() if len(_p) > 2 and _p[1].lower() in ("add", "install", "instalar") else ""
                if not url:
                    print(f"{VIOLET_SWIRL}Uso:{CLR_RST} /skill add <git-url>  "
                          f"{SHADOW_GRAY}(catálogo pronto: /marketplace){CLR_RST}")
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

            elif cmd_word == "/tui":
                parts = prompt.split(maxsplit=1)
                sub = parts[1].strip().lower() if len(parts) > 1 else ""
                if sub not in ("workers", "panel", "painel") and _has_tty():
                    # Tela cheia (Textual) — é o que o Ctrl+T dispara.
                    try:
                        from vincent.tui_app import main as _tui_main
                        _tui_main()
                    except Exception as e:
                        print(f"\n{ALERT_SCARLET}✗ TUI de tela cheia indisponível: {e}{CLR_RST}")
                        print(f"{SHADOW_GRAY}Painel ao vivo das tarefas em background: /tui workers{CLR_RST}\n")
                    continue
                if sub not in ("workers", "panel", "painel"):
                    print(f"{SHADOW_GRAY}Sem terminal interativo — caindo no painel de texto "
                          f"(a tela cheia precisa de TTY).{CLR_RST}")

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

            elif cmd_word == "/help":
                # Paleta navegável (mesma do Ctrl+P); sem TTY, help agrupado.
                chosen = interactive.pick_command(COMMANDS) if _interactive_ready() else None
                if chosen and chosen != "/help":
                    spec = next((c for c in COMMANDS if c["cmd"] == chosen), None)
                    # args entre colchetes = opcional: dá pra executar direto.
                    opcional = not spec or not spec["args"] or spec["args"].startswith("[")
                    if opcional:
                        pending = chosen   # executa já na próxima volta
                    else:
                        print(f"{COBALT_BLUE}{spec['cmd']} {spec['args']}{CLR_RST} "
                              f"{SHADOW_GRAY}— {spec['desc']}{CLR_RST}\n")
                elif chosen == "/help":
                    _print_help()
                else:
                    _print_help()
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
        # Expande antes do spinner: nota impressa por baixo dele sai embaralhada.
        tarefa = apply_mentions(args.agent)
        spinner = NeuralSpinner(f"Vincent Agentic Loop iniciando para: '{args.agent}'...", color=VIOLET_SWIRL)
        with spinner:
            res = agent.agentic_run(tarefa, on_step_callback=_spinner_step(spinner))
        render_response_box(res, agent.display_model, agent.telemetry.last_latency, mode="Agentic Loop (Tools)")
        sys.exit(0)

    if args.prompt:
        question = apply_mentions(" ".join(args.prompt))
        spinner = NeuralSpinner(f"Processando com [{agent.display_model}]...", color=COBALT_BLUE)
        with spinner:
            reply = agent.agentic_run(question, on_step_callback=_spinner_step(spinner))
        mode_label = f"Caveman ({agent.caveman.mode})" if agent.caveman.mode != "off" else "Standard"
        render_response_box(reply, agent.display_model, agent.telemetry.last_latency, mode=mode_label, tokens_saved=agent.caveman.total_tokens_saved)
        sys.exit(0)

    # Entra no REPL interativo futurista
    interactive_repl(agent, registry)


if __name__ == "__main__":
    main()
