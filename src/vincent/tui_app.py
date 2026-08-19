"""
Vincent TUI — Terminal de tela cheia (Textual) no nível de Claude Code / OpenCode.

Substitui o REPL primitivo linha-a-linha por um app Textual completo:
Header vivo (modelo + caveman + effort + estado), conversa scrollável com
markdown/syntax-highlighting, streaming de tokens ao vivo, trace agêntico
com spinner, slash commands e Input fixo no rodapé.

Embrulha `vincent.agent.VincentAgent` sem tocar em nenhum outro módulo.

Entrada:
    python -m vincent.tui_app

O agente roda SEMPRE num worker de thread (`@work(thread=True)`) para nunca
travar a UI; os callbacks marshalam de volta pra thread da UI via
`App.call_from_thread`.
"""

from __future__ import annotations

import os
import re
import time
import traceback
from typing import Optional, List, Dict, Any

# Inferência local por padrão (o agente também lê isto).
os.environ.setdefault("OLLAMA_HOST", "127.0.0.1:11434")

from rich.text import Text
from rich.markup import escape as rich_escape

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll, Container
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    Markdown,
    RichLog,
    Static,
)

# ─── Paleta "noite estrelada" (mesma de vincent.ui / vincent.tui) ──────────────
COBALT = "#0087ff"
GOLD = "#ffd700"
STARRY_GOLD = "#ffaf00"
GREEN = "#00ff87"
VIOLET = "#af87ff"
SCARLET = "#ff5f5f"
WHITE = "#e4e4e4"
GRAY = "#6c6c6c"
NIGHT = "#0b0f1a"
NIGHT_2 = "#111726"
PANEL = "#141b2d"


BANNER = r"""[b #af87ff]╦  ╦[/][b #0087ff]╦[/][b #af87ff]╔╗╔╔═╗╔═╗╔╗╔╔╦╗[/]
[b #af87ff]╚╗╔╝[/][b #0087ff]║[/][b #af87ff]║║║║  ║╣ ║║║ ║ [/]
[b #af87ff] ╚╝ [/][b #0087ff]╩[/][b #af87ff]╝╚╝╚═╝╚═╝╝╚╝ ╩ [/]  [#6c6c6c]terminal de inteligência unificada[/]"""


HELP_MD = """\
# Vincent — Ajuda

Digite normalmente para conversar / rodar uma tarefa agêntica (o Vincent decide
sozinho quando usar ferramentas).

## Slash commands
| Comando | Efeito |
|---|---|
| `/help` | mostra esta ajuda |
| `/models` | abre o catálogo de modelos |
| `/model <id>` | troca o modelo ativo |
| `/effort <low\\|medium\\|high>` | nível de raciocínio |
| `/caveman <off\\|lite\\|full\\|ultra>` | compressão de tokens |
| `/act <tarefa>` | força o modo agente explicitamente |
| `/ask <pergunta>` | chat direto simples (sem loop de ferramentas) |
| `/clear` | limpa a conversa |
| `/exit` | sai |

## Atalhos
`Enter` envia · `Ctrl+L` limpa · `Ctrl+P` catálogo · `Ctrl+C` / `Ctrl+Q` sai
"""


# ══════════════════════════════════════════════════════════════════════════════
#  Widgets de mensagem
# ══════════════════════════════════════════════════════════════════════════════
class ChatMessage(Vertical):
    """Uma bolha de conversa (usuário ou Vincent) com cabeçalho + corpo markdown.

    O corpo é um `Markdown`, então blocos ```lang``` ganham syntax-highlight e a
    formatação (títulos, listas, tabelas) é renderizada de verdade. Durante o
    streaming acumulamos o texto cru e re-renderizamos via `update()`.
    """

    def __init__(self, role: str, text: str = "") -> None:
        super().__init__()
        self.role = role  # "user" | "vincent" | "system"
        self._raw = text
        self.add_class(f"msg-{role}")

    def compose(self) -> ComposeResult:
        if self.role == "user":
            label = "▌ você"
        elif self.role == "vincent":
            label = "✦ vincent"
        else:
            label = "· sistema"
        yield Label(label, classes="msg-role")
        yield Markdown(self._raw, classes="msg-body")

    @property
    def body(self) -> Markdown:
        return self.query_one(Markdown)

    def set_text(self, text: str) -> None:
        self._raw = text
        try:
            self.body.update(text)
        except Exception:
            pass

    def append_text(self, chunk: str) -> None:
        self._raw += chunk
        try:
            self.body.update(self._raw)
        except Exception:
            pass

    @property
    def raw(self) -> str:
        return self._raw


class TracePanel(RichLog):
    """Painel lateral de trace: passos agênticos, tool-calls e saídas ao vivo."""

    def __init__(self) -> None:
        super().__init__(highlight=False, markup=True, wrap=True, auto_scroll=True)

    def step(self, line: str) -> None:
        """Colore a linha de trace conforme o prefixo emitido pelo agente."""
        safe = rich_escape(line)
        stripped = line.lstrip()
        if stripped.startswith("🧠"):
            self.write(f"[b {VIOLET}]{safe}[/]")
        elif stripped.startswith("⚙"):
            self.write(f"[{COBALT}]{safe}[/]")
        elif stripped.startswith("↳") or "↳" in stripped[:4]:
            self.write(f"[{GRAY}]{safe}[/]")
        elif stripped.startswith("⚡"):
            self.write(f"[{STARRY_GOLD}]{safe}[/]")
        elif "⚠" in stripped or stripped.lower().startswith("auto-cura"):
            self.write(f"[{SCARLET}]{safe}[/]")
        elif stripped.startswith("🧾"):
            self.write(f"[{GOLD}]{safe}[/]")
        else:
            self.write(f"[{WHITE}]{safe}[/]")

    def banner(self, line: str) -> None:
        self.write(f"[b {GREEN}]{rich_escape(line)}[/]")


# ══════════════════════════════════════════════════════════════════════════════
#  Modal: catálogo de modelos
# ══════════════════════════════════════════════════════════════════════════════
class ModelsScreen(ModalScreen):
    """Lista os modelos disponíveis; Enter/click seleciona, Esc fecha."""

    BINDINGS = [
        Binding("escape", "dismiss", "Fechar"),
        Binding("up", "cursor_up", "↑", show=False),
        Binding("down", "cursor_down", "↓", show=False),
        Binding("enter", "choose", "Selecionar"),
    ]

    def __init__(self, models: List[Dict[str, Any]], current: str) -> None:
        super().__init__()
        self._models = models
        self._current = current
        self._idx = 0
        for i, m in enumerate(models):
            if m.get("display_id") == current or m.get("id") == current:
                self._idx = i
                break

    def compose(self) -> ComposeResult:
        with Vertical(id="models-box"):
            yield Label(f"Catálogo de modelos  ·  {len(self._models)} disponíveis", id="models-title")
            log = RichLog(id="models-list", markup=True, highlight=False, wrap=False, auto_scroll=False)
            yield log
            yield Label("↑/↓ navega · Enter seleciona · Esc fecha", id="models-hint")

    def on_mount(self) -> None:
        self._render_list()

    def _render_list(self) -> None:
        log = self.query_one("#models-list", RichLog)
        log.clear()
        # Janela ao redor do índice atual para listas gigantes (1200+ modelos).
        total = len(self._models)
        window = 400
        start = max(0, self._idx - window // 2)
        end = min(total, start + window)
        if start > 0:
            log.write(f"[{GRAY}]  … {start} acima …[/]")
        for i in range(start, end):
            m = self._models[i]
            disp = m.get("display_id") or m.get("id") or "?"
            local = m.get("is_local")
            free = m.get("is_free")
            badge = (
                f"[{GREEN}]● local[/]" if local
                else (f"[{STARRY_GOLD}]○ free[/]" if free else f"[{COBALT}]○ cloud[/]")
            )
            marker = f"[b {GOLD}]➤ [/]" if i == self._idx else "  "
            name = rich_escape(str(disp))
            if i == self._idx:
                log.write(f"{marker}[b {WHITE}]{name}[/]  {badge}")
            else:
                log.write(f"{marker}[{WHITE}]{name}[/]  {badge}")
        if end < total:
            log.write(f"[{GRAY}]  … {total - end} abaixo …[/]")

    def action_cursor_up(self) -> None:
        self._idx = max(0, self._idx - 1)
        self._render_list()

    def action_cursor_down(self) -> None:
        self._idx = min(len(self._models) - 1, self._idx + 1)
        self._render_list()

    def action_choose(self) -> None:
        if self._models:
            chosen = self._models[self._idx]
            self.dismiss(chosen.get("display_id") or chosen.get("id"))
        else:
            self.dismiss(None)

    def action_dismiss(self) -> None:  # type: ignore[override]
        self.dismiss(None)


# ══════════════════════════════════════════════════════════════════════════════
#  App principal
# ══════════════════════════════════════════════════════════════════════════════
class VincentTUI(App):
    """TUI de tela cheia para o Vincent."""

    TITLE = "Vincent"
    SUB_TITLE = "terminal de inteligência unificada"

    CSS = """
    Screen {
        background: %(NIGHT)s;
        color: %(WHITE)s;
        layers: base overlay;
    }

    #topbar {
        height: 3;
        padding: 0 1;
        background: %(NIGHT_2)s;
        border-bottom: heavy %(COBALT)s;
    }
    #brand {
        width: auto;
        content-align: left middle;
        color: %(VIOLET)s;
        text-style: bold;
        padding: 0 2 0 0;
    }
    #statusline {
        width: 1fr;
        content-align: right middle;
    }

    #main {
        height: 1fr;
    }

    #conversation {
        width: 3fr;
        padding: 1 2;
        background: %(NIGHT)s;
    }

    #side {
        width: 1fr;
        min-width: 34;
        padding: 0;
        border-left: heavy %(PANEL)s;
    }
    #trace-title {
        height: 1;
        padding: 0 1;
        background: %(PANEL)s;
        color: %(VIOLET)s;
        text-style: bold;
    }
    TracePanel {
        height: 1fr;
        padding: 0 1;
        background: %(NIGHT_2)s;
        scrollbar-size-vertical: 1;
    }

    /* Mensagens */
    ChatMessage {
        height: auto;
        margin: 1 0 0 0;
        padding: 0 1 1 1;
    }
    .msg-role {
        height: 1;
        text-style: bold;
        margin: 0 0 0 0;
    }
    .msg-body {
        height: auto;
        margin: 0;
        padding: 0 1;
        background: transparent;
    }
    .msg-user {
        border-left: heavy %(GOLD)s;
    }
    .msg-user .msg-role { color: %(GOLD)s; }
    .msg-vincent {
        border-left: heavy %(COBALT)s;
    }
    .msg-vincent .msg-role { color: %(COBALT)s; }
    .msg-system {
        border-left: heavy %(GRAY)s;
    }
    .msg-system .msg-role { color: %(GRAY)s; }

    /* Barra de digitação */
    #prompt-row {
        height: auto;
        padding: 0 1 0 1;
        background: %(NIGHT_2)s;
        border-top: heavy %(COBALT)s;
    }
    #chevron {
        width: 3;
        content-align: center middle;
        color: %(GREEN)s;
        text-style: bold;
    }
    #prompt {
        border: none;
        background: %(NIGHT_2)s;
        color: %(WHITE)s;
    }
    #prompt:focus {
        border: none;
    }
    #working {
        height: 1;
        padding: 0 1;
        color: %(STARRY_GOLD)s;
        background: %(NIGHT_2)s;
    }

    /* Modal de modelos */
    ModelsScreen {
        align: center middle;
    }
    #models-box {
        width: 82;
        height: 80%%;
        max-height: 40;
        background: %(PANEL)s;
        border: heavy %(VIOLET)s;
        padding: 1 2;
    }
    #models-title {
        height: 1;
        text-style: bold;
        color: %(VIOLET)s;
    }
    #models-list {
        height: 1fr;
        background: %(NIGHT_2)s;
        margin: 1 0;
        padding: 0 1;
    }
    #models-hint {
        height: 1;
        color: %(GRAY)s;
    }
    """ % {
        "NIGHT": NIGHT, "NIGHT_2": NIGHT_2, "PANEL": PANEL, "COBALT": COBALT,
        "VIOLET": VIOLET, "GOLD": GOLD, "GREEN": GREEN, "WHITE": WHITE,
        "GRAY": GRAY, "STARRY_GOLD": STARRY_GOLD,
    }

    BINDINGS = [
        Binding("ctrl+c", "quit", "Sair", priority=True),
        Binding("ctrl+q", "quit", "Sair"),
        Binding("ctrl+l", "clear_chat", "Limpar"),
        Binding("ctrl+p", "open_models", "Modelos"),
    ]

    working = reactive(False)

    def __init__(self, agent: Optional[Any] = None) -> None:
        super().__init__()
        # Permite injetar um agente/mock nos testes; senão é criado no mount
        # (o __init__ do agente faz rede, então fica fora da thread da UI).
        self._agent = agent
        self._boot_error: Optional[str] = None
        self._active_vincent: Optional[ChatMessage] = None
        self._stream_started = False
        self._spinner_frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        self._spinner_i = 0
        self._spinner_timer = None

    # ── Layout ────────────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="topbar"):
            yield Static(BANNER.splitlines()[0] if False else "✦ Vincent", id="brand")
            yield Static("", id="statusline")
        with Horizontal(id="main"):
            yield VerticalScroll(id="conversation")
            with Vertical(id="side"):
                yield Label("● trace agêntico", id="trace-title")
                yield TracePanel()
        yield Static("", id="working")
        with Horizontal(id="prompt-row"):
            yield Static("❯", id="chevron")
            yield Input(placeholder="Pergunte, ou peça uma tarefa…  (/help pra comandos)", id="prompt")
        yield Footer()

    # ── Ciclo de vida ─────────────────────────────────────────────────────────
    def on_mount(self) -> None:
        self.query_one("#prompt", Input).focus()
        self._refresh_status()
        # Inicializa o agente em background (faz rede ~2-5s) pra não bloquear o boot.
        if self._agent is None:
            self._welcome_pending = True
            self._boot_agent()
        else:
            self._post_welcome()
            self._refresh_status()

    def _post_welcome(self) -> None:
        conv = self.query_one("#conversation", VerticalScroll)
        conv.mount(ChatMessage("system", (
            "Bem-vindo ao **Vincent**. Converse normalmente ou peça uma tarefa — "
            "eu decido sozinho quando investigar o código e rodar ferramentas.\n\n"
            "Use `/help` para ver os comandos."
        )))
        trace = self.query_one(TracePanel)
        trace.banner("✦ trace pronto — passos agênticos aparecem aqui")

    @work(thread=True, exclusive=True, group="boot")
    def _boot_agent(self) -> None:
        """Constrói o VincentAgent numa thread (o __init__ faz I/O de rede)."""
        try:
            from vincent.devices import DeviceRegistry
            from vincent.agent import VincentAgent
            registry = DeviceRegistry(lambda evt: None)
            agent = VincentAgent(registry=registry)
            self._agent = agent
            self.call_from_thread(self._on_agent_ready)
        except Exception as e:  # boot resiliente: nunca crasha a UI
            self._boot_error = f"{e}\n{traceback.format_exc()}"
            self.call_from_thread(self._on_agent_boot_failed, str(e))

    def _on_agent_ready(self) -> None:
        self._post_welcome()
        self._refresh_status()
        self.query_one(TracePanel).step("✦ motor neural online")

    def _on_agent_boot_failed(self, msg: str) -> None:
        conv = self.query_one("#conversation", VerticalScroll)
        conv.mount(ChatMessage("system", (
            "⚠️ **Não consegui inicializar o motor do Vincent.**\n\n"
            f"```\n{msg}\n```\n\n"
            "Verifique se o Ollama (`127.0.0.1:11434`) e/ou o gateway OmniRoute estão de pé. "
            "A interface continua funcionando; comandos de chat vão falhar até o motor subir."
        )))
        self._refresh_status()

    # ── Status ────────────────────────────────────────────────────────────────
    def _refresh_status(self) -> None:
        st = self.query_one("#statusline", Static)
        if self._agent is None:
            if self._boot_error:
                st.update(Text("● motor offline", style=f"bold {SCARLET}"))
            else:
                st.update(Text("● iniciando motor…", style=f"bold {STARRY_GOLD}"))
            return

        model = getattr(self._agent, "display_model", "?")
        caveman = getattr(getattr(self._agent, "caveman", None), "mode", "off")
        effort = getattr(getattr(self._agent, "model_manager", None), "effort", "medium")
        busy = self.working

        line = Text()
        line.append("◆ ", style=COBALT)
        line.append(str(model), style=f"bold {COBALT}")
        line.append("   caveman:", style=GRAY)
        line.append(str(caveman), style=GREEN if caveman != "off" else GRAY)
        line.append("   effort:", style=GRAY)
        line.append(str(effort), style=STARRY_GOLD)
        line.append("   ", style=GRAY)
        if busy:
            line.append("● trabalhando", style=f"bold {STARRY_GOLD}")
        else:
            line.append("● ocioso", style=f"bold {GREEN}")
        st.update(line)

    def watch_working(self, _old: bool, _new: bool) -> None:
        # reactive: só atualiza se os widgets já existirem
        try:
            self._refresh_status()
        except Exception:
            pass

    # ── Spinner "pensando" ────────────────────────────────────────────────────
    def _start_spinner(self, msg: str = "pensando") -> None:
        self._spinner_msg = msg
        if self._spinner_timer is None:
            self._spinner_timer = self.set_interval(0.1, self._tick_spinner)

    def _tick_spinner(self) -> None:
        if not self.working:
            return
        frame = self._spinner_frames[self._spinner_i % len(self._spinner_frames)]
        self._spinner_i += 1
        try:
            self.query_one("#working", Static).update(
                Text(f"{frame} {getattr(self, '_spinner_msg', 'pensando')}…", style=STARRY_GOLD)
            )
        except Exception:
            pass

    def _stop_spinner(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
        try:
            self.query_one("#working", Static).update("")
        except Exception:
            pass

    # ── Conversa ──────────────────────────────────────────────────────────────
    def _add_message(self, role: str, text: str = "") -> ChatMessage:
        conv = self.query_one("#conversation", VerticalScroll)
        msg = ChatMessage(role, text)
        conv.mount(msg)
        conv.scroll_end(animate=False)
        return msg

    def _scroll_conversation(self) -> None:
        try:
            self.query_one("#conversation", VerticalScroll).scroll_end(animate=False)
        except Exception:
            pass

    # ── Input / submit ────────────────────────────────────────────────────────
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "prompt":
            return
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if self.working:
            self._add_message("system", "⏳ Ainda estou processando o pedido anterior — aguarde terminar.")
            self._scroll_conversation()
            return
        if text.startswith("/"):
            self._handle_slash(text)
            return
        # Texto normal → modo agente (agentic_run).
        self._run_agent(text, agentic=True)

    # ── Slash commands ────────────────────────────────────────────────────────
    def _handle_slash(self, text: str) -> None:
        parts = text.split(maxsplit=1)
        cmd = parts[0][1:].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("exit", "quit", "q"):
            self.exit()
            return

        if cmd == "help":
            self._add_message("system", HELP_MD)
            self._scroll_conversation()
            return

        if cmd == "clear":
            self.action_clear_chat()
            return

        if cmd == "models":
            self.action_open_models()
            return

        if cmd == "model":
            if not arg:
                self._add_message("system", "Uso: `/model <id>`. Use `/models` para ver o catálogo.")
            elif self._agent is None:
                self._add_message("system", "⚠️ Motor ainda não está pronto.")
            else:
                try:
                    self._agent.set_model(arg)
                    self._add_message("system", f"✅ Modelo agora é **{self._agent.display_model}**.")
                    self._refresh_status()
                except Exception as e:
                    self._add_message("system", f"⚠️ Falha ao trocar de modelo: {e}")
            self._scroll_conversation()
            return

        if cmd == "effort":
            level = arg.lower()
            aliases = {"med": "medium", "m": "medium", "l": "low", "h": "high"}
            level = aliases.get(level, level)
            if level not in ("low", "medium", "high"):
                self._add_message("system", "Uso: `/effort <low|medium|high>`.")
            elif self._agent is None:
                self._add_message("system", "⚠️ Motor ainda não está pronto.")
            else:
                self._agent.model_manager.effort = level
                self._add_message("system", f"✅ Effort agora é **{level}**.")
                self._refresh_status()
            self._scroll_conversation()
            return

        if cmd == "caveman":
            if self._agent is None:
                self._add_message("system", "⚠️ Motor ainda não está pronto.")
            elif not arg:
                modes = ", ".join(getattr(self._agent.caveman, "INTENSITY_LEVELS", ["off"]))
                self._add_message("system", f"Uso: `/caveman <modo>`. Modos: {modes}")
            else:
                ok = self._agent.set_caveman_mode(arg)
                if ok:
                    self._add_message("system", f"✅ Caveman agora é **{self._agent.caveman.mode}**.")
                    self._refresh_status()
                else:
                    self._add_message("system", f"⚠️ Modo caveman inválido: `{arg}`.")
            self._scroll_conversation()
            return

        if cmd == "act":
            if not arg:
                self._add_message("system", "Uso: `/act <tarefa>` — força o modo agente.")
                self._scroll_conversation()
            else:
                self._run_agent(arg, agentic=True)
            return

        if cmd == "ask":
            if not arg:
                self._add_message("system", "Uso: `/ask <pergunta>` — chat direto, sem ferramentas.")
                self._scroll_conversation()
            else:
                self._run_agent(arg, agentic=False)
            return

        self._add_message("system", f"Comando desconhecido: `/{cmd}`. Use `/help`.")
        self._scroll_conversation()

    # ── Execução do agente (worker de thread) ─────────────────────────────────
    def _run_agent(self, task: str, agentic: bool = True) -> None:
        if self._agent is None:
            self._add_message("system", "⚠️ O motor do Vincent ainda não está pronto (ou falhou ao subir). Tente daqui a pouco.")
            self._scroll_conversation()
            return

        self._add_message("user", task)
        # Bolha do Vincent que será preenchida ao vivo pelo stream.
        self._active_vincent = self._add_message("vincent", "")
        self._stream_started = False
        self.working = True
        self._start_spinner("pensando")

        trace = self.query_one(TracePanel)
        trace.write(f"[{GRAY}]{'─' * 28}[/]")
        trace.step(f"🧠 novo pedido: {rich_escape(task[:70])}")

        self._agent_worker(task, agentic)

    @work(thread=True, exclusive=True, group="agent")
    def _agent_worker(self, task: str, agentic: bool) -> None:
        """Roda o loop agêntico / chat numa thread; callbacks marshalam pra UI."""

        def on_step(line: str) -> None:
            self.call_from_thread(self._ui_step, line)

        def on_stream(piece: str) -> None:
            self.call_from_thread(self._ui_stream, piece)

        try:
            if agentic:
                result = self._agent.agentic_run(
                    task,
                    on_step_callback=on_step,
                    stream_callback=on_stream,
                )
            else:
                # ask() é bloqueante e não streama; damos um passo de trace e
                # entregamos o resultado de uma vez.
                self.call_from_thread(self._ui_step, "🧠 chat direto…")
                result = self._agent.ask(task)
        except Exception as e:
            result = f"[VINCENT] Erro inesperado ao processar: {e}"

        self.call_from_thread(self._ui_finish, result)

    # ── Callbacks marshalados pra thread da UI ────────────────────────────────
    def _ui_step(self, line: str) -> None:
        try:
            self.query_one(TracePanel).step(line)
        except Exception:
            pass
        # Atualiza o texto do spinner com o passo mais recente (resumido).
        m = re.match(r"🧠 Passo (\d+/\d+)", line)
        if m:
            self._spinner_msg = f"pensando · passo {m.group(1)}"

    def _ui_stream(self, piece: str) -> None:
        if self._active_vincent is None:
            return
        if not self._stream_started:
            self._stream_started = True
            self._spinner_msg = "escrevendo"
            self._active_vincent.set_text("")
        self._active_vincent.append_text(piece)
        self._scroll_conversation()

    def _ui_finish(self, result: str) -> None:
        self.working = False
        self._stop_spinner()
        if self._active_vincent is not None:
            # Se nada streamou (ex.: cloud não streama, ou ask()), preenche agora.
            final = result if (not self._stream_started or not self._active_vincent.raw.strip()) else self._active_vincent.raw
            if not final.strip():
                final = "_(resposta vazia)_"
            self._active_vincent.set_text(final)
        self._scroll_conversation()
        try:
            self.query_one(TracePanel).step("✅ concluído")
        except Exception:
            pass
        self._active_vincent = None
        self._refresh_status()
        try:
            self.query_one("#prompt", Input).focus()
        except Exception:
            pass

    # ── Actions ───────────────────────────────────────────────────────────────
    def action_clear_chat(self) -> None:
        conv = self.query_one("#conversation", VerticalScroll)
        for child in list(conv.children):
            child.remove()
        conv.mount(ChatMessage("system", "🧹 Conversa limpa."))
        try:
            self.query_one(TracePanel).clear()
            self.query_one(TracePanel).banner("✦ trace limpo")
        except Exception:
            pass

    def action_open_models(self) -> None:
        if self._agent is None:
            self._add_message("system", "⚠️ Motor ainda não está pronto para listar modelos.")
            self._scroll_conversation()
            return
        try:
            models = self._agent.model_manager.get_all_models()
        except Exception as e:
            self._add_message("system", f"⚠️ Não consegui obter o catálogo: {e}")
            self._scroll_conversation()
            return
        if not models:
            self._add_message("system", "Nenhum modelo no catálogo (offline?).")
            self._scroll_conversation()
            return

        current = getattr(self._agent, "display_model", "")

        def _picked(choice: Optional[str]) -> None:
            if choice:
                try:
                    self._agent.set_model(choice)
                    self._add_message("system", f"✅ Modelo agora é **{self._agent.display_model}**.")
                    self._refresh_status()
                except Exception as e:
                    self._add_message("system", f"⚠️ Falha ao trocar: {e}")
                self._scroll_conversation()

        self.push_screen(ModelsScreen(models, current), _picked)


def main() -> None:
    VincentTUI().run()


if __name__ == "__main__":
    main()
