"""
Vincent TUI — Terminal de tela cheia (Textual) no nível de Claude Code / OpenCode.

Substitui o REPL primitivo linha-a-linha por um app Textual completo, agora com
um LAYOUT DE DASHBOARD profissional:

    ┌──────────────────────────────────────────────────────────────────┐
    │  header (título · relógio)                                         │
    ├──────────────────────────────────────────────────────────────────┤
    │  ✦ Vincent          ◆ modelo   ⚙ effort   ▣ caveman   ● estado    │  ← barra de status
    ├───────────────┬──────────────────────────────────┬────────────────┤
    │  SIDEBAR      │  CONVERSA (scroll)                │  TRACE         │
    │  · sessão     │   bolhas de mensagem refinadas    │  passos        │
    │  · comandos   │                                   │  agênticos     │
    │  · atalhos    │                                   │  ao vivo       │
    ├───────────────┴──────────────────────────────────┴────────────────┤
    │  indicador "pensando"                                              │
    │  ❯  input …                                    (Enter envia)        │
    ├──────────────────────────────────────────────────────────────────┤
    │  footer (atalhos)                                                  │
    └──────────────────────────────────────────────────────────────────┘

Header vivo, conversa scrollável com markdown/syntax-highlighting, streaming de
tokens ao vivo, trace agêntico com spinner, slash commands e Input fixo no rodapé.

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

# ══════════════════════════════════════════════════════════════════════════════
#  DESIGN TOKENS — arquitetura de 3 camadas (primitivo → semântico → aplicado)
#  Paleta "noite estrelada" mantida, mas organizada em superfícies em camadas,
#  bordas sutis, um acento forte (cobalto/violeta) usado com parcimônia e cores
#  de estado consistentes (sucesso / aviso / erro).
# ══════════════════════════════════════════════════════════════════════════════

# ── Camada 1: primitivos (valores crus) ───────────────────────────────────────
COBALT = "#3b82f6"       # acento primário — azul cobalto vivo
COBALT_DIM = "#1d4ed8"   # acento fundo/hover
VIOLET = "#a78bfa"       # acento secundário — violeta estelar
VIOLET_DIM = "#7c3aed"
GOLD = "#facc15"         # destaque do usuário
STARRY_GOLD = "#f59e0b"  # aviso / "trabalhando"
GREEN = "#34d399"        # sucesso / ocioso
SCARLET = "#f87171"      # erro
CYAN = "#22d3ee"         # info fria (ferramentas)

# Neutros em rampa (do mais escuro ao mais claro) — superfícies em camadas.
INK_0 = "#080b14"        # base absoluta (fundo do app)
INK_1 = "#0c1120"        # superfície de conteúdo (conversa)
INK_2 = "#121a2e"        # painel elevado (sidebar / trace)
INK_3 = "#1a2540"        # elevado 2 (cabeçalhos de painel / campo de input)
INK_4 = "#24314f"        # bordas / divisores
LINE = "#1e293b"         # linha sutil / hairline
TEXT = "#e8eaf0"         # texto primário
TEXT_DIM = "#9aa4bf"     # texto secundário
MUTED = "#5b6689"        # texto terciário / desabilitado

# ── Camada 2: aliases semânticos (usados no CSS via % de formatação) ───────────
BG = INK_0
SURFACE = INK_1
PANEL = INK_2
ELEVATED = INK_3
BORDER = INK_4
BORDER_SOFT = LINE
FG = TEXT
FG_DIM = TEXT_DIM
FG_MUTED = MUTED
ACCENT = COBALT
ACCENT_2 = VIOLET
OK = GREEN
WARN = STARRY_GOLD
ERR = SCARLET

# Compat: nomes antigos ainda referenciados no corpo (trace coloring etc.).
WHITE = TEXT
GRAY = MUTED
NIGHT = BG
NIGHT_2 = PANEL


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
`Enter` envia · `Ctrl+L` limpa · `Ctrl+P` catálogo · `Ctrl+B` sidebar · `Ctrl+C` / `Ctrl+Q` sai
"""


def _now() -> str:
    """Timestamp discreto HH:MM para o cabeçalho das mensagens."""
    return time.strftime("%H:%M")


# ══════════════════════════════════════════════════════════════════════════════
#  Widgets de mensagem
# ══════════════════════════════════════════════════════════════════════════════
class ChatMessage(Vertical):
    """Uma bolha de conversa (usuário ou Vincent) com cabeçalho + corpo markdown.

    Cabeçalho: ícone + nome do papel + timestamp discreto à direita.
    O corpo é um `Markdown`, então blocos ```lang``` ganham syntax-highlight e a
    formatação (títulos, listas, tabelas) é renderizada de verdade. Durante o
    streaming acumulamos o texto cru e re-renderizamos via `update()`.
    """

    def __init__(self, role: str, text: str = "") -> None:
        super().__init__()
        self.role = role  # "user" | "vincent" | "system"
        self._raw = text
        self._stamp = _now()
        self.add_class(f"msg-{role}")

    def compose(self) -> ComposeResult:
        if self.role == "user":
            icon, name = "▐", "você"
        elif self.role == "vincent":
            icon, name = "✦", "vincent"
        else:
            icon, name = "•", "sistema"
        head = Text()
        head.append(f"{icon} ", style="bold")
        head.append(name, style="bold")
        with Horizontal(classes="msg-head"):
            yield Static(head, classes="msg-role")
            yield Static(Text(self._stamp, style=f"{FG_MUTED}"), classes="msg-time")
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
            self.write(f"[{CYAN}]{safe}[/]")
        elif stripped.startswith("↳") or "↳" in stripped[:4]:
            self.write(f"[{FG_DIM}]{safe}[/]")
        elif stripped.startswith("⚡"):
            self.write(f"[{STARRY_GOLD}]{safe}[/]")
        elif "⚠" in stripped or stripped.lower().startswith("auto-cura"):
            self.write(f"[{SCARLET}]{safe}[/]")
        elif stripped.startswith("🧾"):
            self.write(f"[{GOLD}]{safe}[/]")
        elif stripped.startswith("✅") or stripped.startswith("✦"):
            self.write(f"[{GREEN}]{safe}[/]")
        else:
            self.write(f"[{FG_DIM}]{safe}[/]")

    def banner(self, line: str) -> None:
        self.write(f"[b {GREEN}]{rich_escape(line)}[/]")

    def rule(self) -> None:
        """Divisor sutil entre pedidos."""
        self.write(f"[{BORDER}]{'─' * 30}[/]")


# ══════════════════════════════════════════════════════════════════════════════
#  Modal: catálogo de modelos
# ══════════════════════════════════════════════════════════════════════════════
class ModelsScreen(ModalScreen):
    """Lista os modelos disponíveis; Enter/click seleciona, Esc fecha."""

    BINDINGS = [
        Binding("escape", "dismiss", "Fechar"),
        Binding("up", "cursor_up", "↑", show=False),
        Binding("down", "cursor_down", "↓", show=False),
        Binding("pageup", "page_up", "↟", show=False),
        Binding("pagedown", "page_down", "↡", show=False),
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
            with Horizontal(id="models-header"):
                yield Static(Text("✦ ", style=f"bold {VIOLET}") + Text("Catálogo de modelos", style=f"bold {FG}"), id="models-title")
                yield Static(Text(f"{len(self._models)} disponíveis", style=f"{FG_MUTED}"), id="models-count")
            log = RichLog(id="models-list", markup=True, highlight=False, wrap=False, auto_scroll=False)
            yield log
            yield Static(Text("↑/↓ navega   ⇞/⇟ página   ⏎ seleciona   esc fecha", style=f"{FG_MUTED}"), id="models-hint")

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
            log.write(f"[{MUTED}]   ⋯ {start} acima[/]")
        for i in range(start, end):
            m = self._models[i]
            disp = m.get("display_id") or m.get("id") or "?"
            local = m.get("is_local")
            free = m.get("is_free")
            if local:
                badge = f"[{GREEN}]● local[/]"
            elif free:
                badge = f"[{STARRY_GOLD}]◐ free [/]"
            else:
                badge = f"[{COBALT}]○ cloud[/]"
            name = rich_escape(str(disp))
            if i == self._idx:
                log.write(f"[b {GOLD}] ❯ [/][b {WHITE}]{name}[/]   {badge}")
            else:
                log.write(f"   [{FG_DIM}]{name}[/]   {badge}")
        if end < total:
            log.write(f"[{MUTED}]   ⋯ {total - end} abaixo[/]")

    def action_cursor_up(self) -> None:
        self._idx = max(0, self._idx - 1)
        self._render_list()

    def action_cursor_down(self) -> None:
        self._idx = min(len(self._models) - 1, self._idx + 1)
        self._render_list()

    def action_page_up(self) -> None:
        self._idx = max(0, self._idx - 12)
        self._render_list()

    def action_page_down(self) -> None:
        self._idx = min(len(self._models) - 1, self._idx + 12)
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
    /* ═══════════════════════════════════════════════════════════════════
       BASE — fundo em camadas + scrollbars estilizadas
       ═══════════════════════════════════════════════════════════════════ */
    Screen {
        background: %(BG)s;
        color: %(FG)s;
        layers: base overlay;
    }
    * {
        scrollbar-background: %(SURFACE)s;
        scrollbar-background-hover: %(SURFACE)s;
        scrollbar-background-active: %(SURFACE)s;
        scrollbar-color: %(BORDER)s;
        scrollbar-color-hover: %(ACCENT_2)s;
        scrollbar-color-active: %(ACCENT)s;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
    }
    Header {
        background: %(BG)s;
        color: %(FG_DIM)s;
    }
    Footer {
        background: %(PANEL)s;
        color: %(FG_DIM)s;
    }
    Footer > .footer-key--key {
        color: %(ACCENT)s;
        text-style: bold;
    }
    Footer > .footer-key--description {
        color: %(FG_DIM)s;
    }

    /* ═══════════════════════════════════════════════════════════════════
       STATUS BAR — barra de acento com badges (modelo/effort/caveman/estado)
       ═══════════════════════════════════════════════════════════════════ */
    #statusbar {
        height: 3;
        padding: 0 2;
        background: %(PANEL)s;
        border-bottom: tall %(BORDER)s;
    }
    #brand {
        width: auto;
        content-align: left middle;
        color: %(ACCENT_2)s;
        text-style: bold;
        padding: 0 2 0 0;
    }
    #statusline {
        width: 1fr;
        content-align: right middle;
    }

    /* ═══════════════════════════════════════════════════════════════════
       LAYOUT PRINCIPAL — sidebar · conversa · trace
       ═══════════════════════════════════════════════════════════════════ */
    #main {
        height: 1fr;
    }

    /* ── Sidebar esquerda (sessão / comandos / atalhos) ── */
    #sidebar {
        width: 30;
        min-width: 26;
        max-width: 38;
        background: %(PANEL)s;
        border-right: tall %(BORDER)s;
        padding: 0;
    }
    #sidebar.-hidden {
        display: none;
    }
    .side-section {
        height: auto;
        padding: 1 2 0 2;
    }
    .side-head {
        height: 1;
        color: %(ACCENT_2)s;
        text-style: bold;
        margin: 0 0 1 0;
    }
    .side-row {
        height: 1;
        color: %(FG_DIM)s;
    }
    .side-key {
        color: %(ACCENT)s;
        text-style: bold;
    }
    #side-hint {
        dock: bottom;
        height: auto;
        padding: 1 2;
        color: %(FG_MUTED)s;
        border-top: tall %(BORDER)s;
    }

    /* ── Conversa (centro) ── */
    #conversation {
        width: 1fr;
        padding: 1 3 1 3;
        background: %(SURFACE)s;
    }

    /* ── Painel de trace (direita) ── */
    #side {
        width: 40;
        min-width: 30;
        max-width: 52;
        background: %(PANEL)s;
        border-left: tall %(BORDER)s;
        padding: 0;
    }
    #side.-hidden {
        display: none;
    }
    #trace-title {
        height: 1;
        padding: 0 2;
        background: %(ELEVATED)s;
        color: %(ACCENT_2)s;
        text-style: bold;
        border-bottom: tall %(BORDER)s;
    }
    TracePanel {
        height: 1fr;
        padding: 1 2;
        background: %(PANEL)s;
    }

    /* ═══════════════════════════════════════════════════════════════════
       BOLHAS DE MENSAGEM — superfície, padding respirável, acento por papel
       ═══════════════════════════════════════════════════════════════════ */
    ChatMessage {
        height: auto;
        width: 1fr;
        max-width: 120;
        margin: 0 0 1 0;
        padding: 0 0 0 0;
    }
    .msg-head {
        height: 1;
        margin: 0 0 0 1;
    }
    .msg-role {
        width: auto;
        height: 1;
        content-align: left middle;
    }
    .msg-time {
        width: 1fr;
        height: 1;
        content-align: right middle;
        color: %(FG_MUTED)s;
    }
    .msg-body {
        height: auto;
        margin: 0;
        padding: 1 2;
        background: %(PANEL)s;
    }

    /* Usuário — acento dourado */
    .msg-user .msg-role { color: %(GOLD)s; }
    .msg-user .msg-body {
        background: %(ELEVATED)s;
        border-left: thick %(GOLD)s;
    }
    /* Vincent — acento cobalto */
    .msg-vincent .msg-role { color: %(ACCENT)s; }
    .msg-vincent .msg-body {
        background: %(PANEL)s;
        border-left: thick %(ACCENT)s;
    }
    /* Sistema — discreto */
    .msg-system .msg-role { color: %(FG_MUTED)s; }
    .msg-system .msg-body {
        background: %(SURFACE)s;
        border-left: thick %(BORDER)s;
        color: %(FG_DIM)s;
    }

    /* ═══════════════════════════════════════════════════════════════════
       INDICADOR "PENSANDO"
       ═══════════════════════════════════════════════════════════════════ */
    #working {
        height: 1;
        padding: 0 3;
        color: %(WARN)s;
        background: %(SURFACE)s;
    }

    /* ═══════════════════════════════════════════════════════════════════
       BARRA DE INPUT — campo elevado com borda de foco de acento + chevron
       ═══════════════════════════════════════════════════════════════════ */
    #prompt-row {
        height: auto;
        padding: 1 2;
        background: %(PANEL)s;
        border-top: tall %(BORDER)s;
    }
    #promptwrap {
        height: auto;
        background: %(ELEVATED)s;
        border: round %(BORDER)s;
        padding: 0 1;
    }
    #promptwrap:focus-within {
        border: round %(ACCENT)s;
        background: %(ELEVATED)s;
    }
    #chevron {
        width: 3;
        content-align: center middle;
        color: %(ACCENT)s;
        text-style: bold;
    }
    #prompt {
        width: 1fr;
        border: none;
        height: auto;
        background: %(ELEVATED)s;
        color: %(FG)s;
        padding: 0 1;
    }
    #prompt:focus {
        border: none;
        background: %(ELEVATED)s;
    }
    #prompt > .input--placeholder {
        color: %(FG_MUTED)s;
    }
    #prompt-hint {
        width: auto;
        content-align: right middle;
        color: %(FG_MUTED)s;
        padding: 0 1 0 2;
    }

    /* ═══════════════════════════════════════════════════════════════════
       MODAL — catálogo de modelos (superfície elevada, borda de acento)
       ═══════════════════════════════════════════════════════════════════ */
    ModelsScreen {
        align: center middle;
    }
    #models-box {
        width: 86;
        max-width: 92%%;
        height: 80%%;
        max-height: 42;
        background: %(PANEL)s;
        border: round %(ACCENT_2)s;
        padding: 1 2 1 2;
    }
    #models-header {
        height: 1;
        margin: 0 0 1 0;
    }
    #models-title {
        width: auto;
        height: 1;
        content-align: left middle;
    }
    #models-count {
        width: 1fr;
        height: 1;
        content-align: right middle;
    }
    #models-list {
        height: 1fr;
        background: %(SURFACE)s;
        border: round %(BORDER)s;
        margin: 0 0 1 0;
        padding: 1 1;
    }
    #models-hint {
        height: 1;
        content-align: center middle;
    }
    """ % {
        "BG": BG, "SURFACE": SURFACE, "PANEL": PANEL, "ELEVATED": ELEVATED,
        "BORDER": BORDER, "BORDER_SOFT": BORDER_SOFT, "FG": FG, "FG_DIM": FG_DIM,
        "FG_MUTED": FG_MUTED, "ACCENT": ACCENT, "ACCENT_2": ACCENT_2,
        "OK": OK, "WARN": WARN, "ERR": ERR, "GOLD": GOLD, "WHITE": WHITE,
    }

    BINDINGS = [
        Binding("ctrl+c", "quit", "Sair", priority=True),
        Binding("ctrl+q", "quit", "Sair"),
        Binding("ctrl+l", "clear_chat", "Limpar"),
        Binding("ctrl+p", "open_models", "Modelos"),
        Binding("ctrl+b", "toggle_sidebar", "Sidebar"),
        Binding("ctrl+t", "toggle_trace", "Trace"),
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
        with Horizontal(id="statusbar"):
            yield Static(Text("✦ Vincent", style=f"bold {ACCENT_2}"), id="brand")
            yield Static("", id="statusline")
        with Horizontal(id="main"):
            # Sidebar esquerda — identidade da sessão, comandos e atalhos.
            with Vertical(id="sidebar"):
                with Vertical(classes="side-section"):
                    yield Static(Text("SESSÃO", style=f"bold {ACCENT_2}"), classes="side-head")
                    yield Static(self._session_line(), id="side-session", classes="side-row")
                with Vertical(classes="side-section"):
                    yield Static(Text("COMANDOS", style=f"bold {ACCENT_2}"), classes="side-head")
                    for key, desc in (
                        ("/help", "ajuda"),
                        ("/models", "catálogo"),
                        ("/model", "trocar modelo"),
                        ("/effort", "raciocínio"),
                        ("/caveman", "compressão"),
                        ("/act", "modo agente"),
                        ("/ask", "chat direto"),
                        ("/clear", "limpar"),
                    ):
                        row = Text()
                        row.append(f"{key:<9}", style=f"bold {ACCENT}")
                        row.append(desc, style=f"{FG_DIM}")
                        yield Static(row, classes="side-row")
                yield Static(
                    Text("Enter", style=f"bold {ACCENT}") + Text(" envia  ", style=FG_MUTED)
                    + Text("^L", style=f"bold {ACCENT}") + Text(" limpa\n", style=FG_MUTED)
                    + Text("^P", style=f"bold {ACCENT}") + Text(" modelos  ", style=FG_MUTED)
                    + Text("^B", style=f"bold {ACCENT}") + Text(" sidebar", style=FG_MUTED),
                    id="side-hint",
                )
            # Conversa central.
            yield VerticalScroll(id="conversation")
            # Painel de trace direito.
            with Vertical(id="side"):
                yield Static(Text("● trace agêntico", style=f"bold {ACCENT_2}"), id="trace-title")
                yield TracePanel()
        yield Static("", id="working")
        with Horizontal(id="prompt-row"):
            with Horizontal(id="promptwrap"):
                yield Static("❯", id="chevron")
                yield Input(placeholder="Pergunte, ou peça uma tarefa…   (/help para comandos)", id="prompt")
            yield Static(Text("Enter ↵", style=f"{FG_MUTED}"), id="prompt-hint")
        yield Footer()

    def _session_line(self) -> Text:
        """Linha de estado compacta pra sidebar."""
        t = Text()
        if self._agent is None:
            if self._boot_error:
                t.append("● offline", style=f"bold {ERR}")
            else:
                t.append("◌ iniciando…", style=f"bold {WARN}")
        else:
            t.append("● online", style=f"bold {OK}")
        return t

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
            "Use `/help` para ver os comandos, ou `Ctrl+P` para o catálogo de modelos."
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
    def _badge(self, label: str, value: str, color: str, *, on: bool = True) -> Text:
        """Um 'chip' de status: rótulo apagado + valor colorido."""
        t = Text()
        t.append(f"{label} ", style=f"{FG_MUTED}")
        t.append(value, style=f"bold {color}" if on else f"{FG_MUTED}")
        return t

    def _refresh_status(self) -> None:
        # Sincroniza a linha de sessão da sidebar (se já montada).
        try:
            self.query_one("#side-session", Static).update(self._session_line())
        except Exception:
            pass

        st = self.query_one("#statusline", Static)
        if self._agent is None:
            if self._boot_error:
                st.update(Text("● motor offline", style=f"bold {ERR}"))
            else:
                st.update(Text("◌ iniciando motor…", style=f"bold {WARN}"))
            return

        model = getattr(self._agent, "display_model", "?")
        caveman = getattr(getattr(self._agent, "caveman", None), "mode", "off")
        effort = getattr(getattr(self._agent, "model_manager", None), "effort", "medium")
        busy = self.working

        sep = Text("  ·  ", style=f"{BORDER}")
        line = Text()
        line.append_text(self._badge("◆", str(model), ACCENT))
        line.append_text(sep)
        line.append_text(self._badge("⚙ effort", str(effort), WARN))
        line.append_text(sep)
        line.append_text(self._badge("▣ caveman", str(caveman), OK, on=(caveman != "off")))
        line.append_text(sep)
        if busy:
            line.append("● trabalhando", style=f"bold {WARN}")
        else:
            line.append("● ocioso", style=f"bold {OK}")
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
            msg = getattr(self, "_spinner_msg", "pensando")
            t = Text()
            t.append(f"{frame} ", style=f"bold {ACCENT_2}")
            t.append(f"{msg}", style=f"{WARN}")
            t.append(" …", style=f"{FG_MUTED}")
            self.query_one("#working", Static).update(t)
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
        trace.rule()
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

    def action_toggle_sidebar(self) -> None:
        try:
            self.query_one("#sidebar").toggle_class("-hidden")
        except Exception:
            pass

    def action_toggle_trace(self) -> None:
        try:
            self.query_one("#side").toggle_class("-hidden")
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
