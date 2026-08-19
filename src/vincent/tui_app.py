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
import sys
import threading
import time
import traceback
from typing import Iterable, Optional, List, Dict, Any, Tuple

# Inferência local por padrão (o agente também lê isto).
os.environ.setdefault("OLLAMA_HOST", "127.0.0.1:11434")

from rich.text import Text
from rich.markup import escape as rich_escape

try:
    # O fuzzy COM pontuação do REPL — a TUI usava só subsequência crua.
    from vincent.interactive import score_item as _score_item
except Exception:  # pragma: no cover - só sem prompt_toolkit/instalação parcial
    _score_item = None

try:
    # Preview de diff no modal de permissão (stdlib puro, sem dependência nova).
    from vincent.agent_tools import build_edit_preview as _build_edit_preview
    from vincent.ui import diff_lines as _diff_lines
except Exception:  # pragma: no cover - instalação parcial
    _build_edit_preview = None
    _diff_lines = None

from textual import work
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll, Container
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    Markdown,
    OptionList,
    RichLog,
    Static,
)
from textual.widgets.option_list import Option

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
| `/models`, `/model` | abre o seletor de modelos (busca fuzzy) |
| `/model <id>` | troca o modelo ativo direto |
| `/marketplace` | marketplace de skills (instalar / remover) |
| `/effort <low\\|medium\\|high>` | nível de raciocínio |
| `/autoedit <on\\|off>` | `off` = pede permissão antes de mexer no sistema |
| `/reload-plugins` | re-varre skills e plugins do disco |
| `/caveman <off\\|lite\\|full\\|ultra>` | compressão de tokens |
| `/act <tarefa>` | força o modo agente explicitamente |
| `/ask <pergunta>` | chat direto simples (sem loop de ferramentas) |
| `/clear` | limpa a conversa |
| `/exit` | sai |

## Atalhos
`Enter` envia · `^P` palette de comandos · `^O` modelos · `^S` skills
`^L` limpa · `^B` sidebar · `^T` trace · `^C`/`^Q` sai
"""


def _now() -> str:
    """Timestamp discreto HH:MM para o cabeçalho das mensagens."""
    return time.strftime("%H:%M")


def _ellip(text: str, width: int) -> str:
    """Corta com reticências e preenche até `width` — alinhamento de colunas."""
    text = str(text)
    if len(text) > width:
        return text[: width - 1] + "…"
    return text.ljust(width)


# ══════════════════════════════════════════════════════════════════════════════
#  Catálogo — agrupamento e busca fuzzy
#  485 modelos não cabem numa lista truncada com "+N adicionais": o seletor
#  mostra TODOS, agrupados, e a busca por subsequência filtra na hora.
# ══════════════════════════════════════════════════════════════════════════════
GROUP_ORDER = ("LOCAL", "COMBOS", "FREE", "PRO")

# grupo → (badge, cor, legenda)
GROUP_META: Dict[str, Tuple[str, str, str]] = {
    "LOCAL":  ("● local", GREEN,       "na sua máquina"),
    "COMBOS": ("◈ combo", VIOLET,      "roteadores automáticos"),
    "FREE":   ("◐ free",  STARRY_GOLD, "grátis no gateway"),
    "PRO":    ("○ pro",   COBALT,      "premium / pagos"),
}


def _group_of(m: Dict[str, Any]) -> str:
    """Classifica um modelo do catálogo nos quatro baldes da UI."""
    if m.get("is_local"):
        return "LOCAL"
    if str(m.get("id") or "").lower().startswith("auto"):
        return "COMBOS"
    if m.get("is_free"):
        return "FREE"
    return "PRO"


def _fuzzy(query: str, text: str) -> bool:
    """Casa por subsequência, sem acento nem regex — a ideia do fzf, versão magra."""
    if not query:
        return True
    haystack = text.lower()
    pos = 0
    for ch in query.lower():
        if ch.isspace():
            continue
        pos = haystack.find(ch, pos) + 1
        if pos == 0:
            return False
    return True


def _rank_model(query: str, model: Dict[str, Any]) -> Optional[float]:
    """Score do modelo pra busca do modal. None = não bate.

    Usa o mesmo fuzzy COM PONTUAÇÃO do REPL (prefixo > contíguo > espalhado,
    espaço = AND de termos); se o interactive não estiver disponível, cai na
    subsequência crua de `_fuzzy`.
    """
    if _score_item is None:
        hay = " ".join(str(model.get(k) or "") for k in ("display_id", "id", "name", "provider"))
        return 0.0 if _fuzzy(query, hay) else None
    return _score_item(query, model)


# Preview de diff (linhas vindas de `vincent.ui.diff_lines`) mapeado pra paleta
# da TUI — mesmos prefixos que o REPL colore via `ui.colorize_diff_line`.
_DIFF_STYLES = {
    "◆ ": f"b {GOLD}",
    "@@": CYAN,
    "+ ": GREEN,
    "- ": SCARLET,
    "· ": FG_DIM,
}


def _pending_diff(tool_name: str, args: Any, max_lines: int = 60) -> List[str]:
    """Diff da edição que está pra ser aplicada (linhas de `ui.diff_lines`).

    [] quando não é edição, quando não dá pra prever a mudança ou quando o
    núcleo não pôde ser importado — aí o modal cai no preview de argumentos.
    """
    if not isinstance(args, dict) or _build_edit_preview is None:
        return []
    try:
        return _diff_lines(_build_edit_preview(tool_name, args),
                           title=str(args.get("path") or ""), max_lines=max_lines)
    except Exception:
        return []


def _diff_text(lines: List[str]) -> Text:
    """Linhas de diff → `rich.Text` colorido (verde/vermelho, contexto apagado)."""
    out = Text()
    for i, line in enumerate(lines):
        if i:
            out.append("\n")
        out.append(line, style=_DIFF_STYLES.get(line[:2], FG))
    return out


def _preview_args(args: Any, width: int = 220) -> str:
    """Resumo legível dos argumentos de uma ferramenta (pro modal de permissão)."""
    if isinstance(args, dict):
        for key in ("command", "path", "filepath", "code", "url", "message", "content"):
            if args.get(key):
                return str(args[key])[:width]
        return ", ".join(f"{k}={str(v)[:60]}" for k, v in list(args.items())[:4])[:width]
    return str(args or "")[:width]


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
        diff_style = _DIFF_STYLES.get(line[:2])
        if diff_style:
            self.write(f"[{diff_style}]{safe}[/]")
            return
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
class PickerScreen(ModalScreen):
    """Base dos modais de escolha: busca no topo + `OptionList` rolável embaixo.

    O foco fica no campo de busca (dá pra digitar direto), e ↑↓/⇞⇟ são
    repassados pra lista — mesma sensação do seletor do Claude Code.
    """

    BINDINGS = [
        Binding("escape", "close", "Fechar"),
        Binding("up", "nav_up", "↑", show=False),
        Binding("down", "nav_down", "↓", show=False),
        Binding("pageup", "nav_pgup", "⇞", show=False),
        Binding("pagedown", "nav_pgdn", "⇟", show=False),
    ]

    LIST_ID = "picker-list"
    SEARCH_ID = "picker-search"

    def _list(self) -> OptionList:
        return self.query_one(f"#{self.LIST_ID}", OptionList)

    def action_nav_up(self) -> None:
        self._list().action_cursor_up()

    def action_nav_down(self) -> None:
        self._list().action_cursor_down()

    def action_nav_pgup(self) -> None:
        self._list().action_page_up()

    def action_nav_pgdn(self) -> None:
        self._list().action_page_down()

    def action_close(self) -> None:
        self.dismiss(None)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == self.SEARCH_ID:
            event.stop()
            self.refill(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == self.SEARCH_ID:
            event.stop()
            opt = self._list().highlighted_option
            self.choose(opt.id if opt is not None else None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.choose(event.option.id)

    def _highlight_first(self, index: Optional[int] = None) -> None:
        """Põe o cursor numa opção selecionável (cabeçalhos de grupo são disabled)."""
        lst = self._list()
        if index is not None:
            lst.highlighted = index
            return
        for i in range(lst.option_count):
            if not lst.get_option_at_index(i).disabled:
                lst.highlighted = i
                return

    # subclasses implementam
    def refill(self, query: str) -> None: ...
    def choose(self, opt_id: Optional[str]) -> None: ...


# ══════════════════════════════════════════════════════════════════════════════
#  Modal: seletor de modelos
# ══════════════════════════════════════════════════════════════════════════════
class ModelsScreen(PickerScreen):
    """Seletor de modelos com busca fuzzy e grupos LOCAL / COMBOS / FREE / PRO.

    Mostra o catálogo INTEIRO (485+ modelos) — nada de "+N adicionais": a lista
    rola e a busca filtra. Enter aplica, Esc fecha.
    """

    LIST_ID = "models-list"
    SEARCH_ID = "models-search"

    def __init__(self, models: List[Dict[str, Any]], current: str) -> None:
        super().__init__()
        self._models = list(models or [])
        self._current = str(current or "")
        self._filtered: List[Dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="models-box"):
            with Horizontal(classes="picker-header"):
                yield Static(
                    Text("✦ ", style=f"bold {VIOLET}") + Text("Selecionar modelo", style=f"bold {FG}"),
                    classes="picker-title",
                )
                yield Static("", id="models-count", classes="picker-count")
            yield Input(placeholder="filtrar…  (ex.: qwen, sonnet, auto, free)", id=self.SEARCH_ID, classes="picker-search")
            yield OptionList(id=self.LIST_ID, classes="picker-list")
            yield Static(
                Text("↑↓ navega · ⇞⇟ página · ⏎ aplica · esc fecha", style=f"{FG_MUTED}"),
                classes="picker-hint",
            )

    def on_mount(self) -> None:
        self.refill("")
        self.query_one(f"#{self.SEARCH_ID}", Input).focus()

    def _is_current(self, m: Dict[str, Any]) -> bool:
        return self._current in (m.get("display_id"), m.get("id")) and bool(self._current)

    def _row(self, m: Dict[str, Any], group: str) -> Text:
        badge, color, _ = GROUP_META[group]
        disp = str(m.get("display_id") or m.get("id") or "?")
        cur = self._is_current(m)
        t = Text()
        t.append("● " if cur else "  ", style=f"bold {GOLD}")
        t.append(_ellip(disp, 46), style=f"bold {FG}" if cur else FG)
        t.append(f" {badge:<8}", style=color)
        prov = str(m.get("provider") or "")
        if prov:
            t.append(f" {_ellip(prov, 14)}", style=FG_MUTED)
        return t

    def refill(self, query: str) -> None:
        query = str(query or "").strip()
        self._filtered = []
        options: List[Option] = []
        cur_index: Optional[int] = None

        def _add(m: Dict[str, Any]) -> None:
            nonlocal cur_index
            if self._is_current(m) and cur_index is None:
                cur_index = len(options)
            options.append(Option(self._row(m, _group_of(m)), id=str(len(self._filtered))))
            self._filtered.append(m)

        if query:
            # Busca ativa = lista única RANQUEADA. Agrupada, 'opus' devolvia
            # auto/pro-reasoning no topo e o claude-opus só na 11ª linha.
            scored = []
            for m in self._models:
                s = _rank_model(query, m)
                if s is not None:
                    scored.append((s, m))
            scored.sort(key=lambda p: -p[0])
            for _, m in scored:
                _add(m)
        else:
            buckets: Dict[str, List[Dict[str, Any]]] = {g: [] for g in GROUP_ORDER}
            for m in self._models:
                buckets[_group_of(m)].append(m)
            for group in GROUP_ORDER:
                bucket = buckets[group]
                if not bucket:
                    continue
                _, color, legend = GROUP_META[group]
                head = Text()
                head.append(f"─ {group} ", style=f"bold {color}")
                head.append(f"({len(bucket)}) · {legend}", style=FG_MUTED)
                options.append(Option(head, disabled=True))
                for m in bucket:
                    _add(m)

        lst = self._list()
        lst.clear_options()
        if options:
            lst.add_options(options)
            self._highlight_first(cur_index)
        else:
            # Lista vazia e sem explicação era o pior desfecho possível.
            lst.add_options([Option(Text("nenhum modelo bate com a busca", style=FG_MUTED),
                                    disabled=True)])

        count = Text()
        count.append(f"{len(self._filtered)}", style=f"bold {VIOLET}")
        count.append(f" / {len(self._models)} modelos", style=FG_MUTED)
        self.query_one("#models-count", Static).update(count)

    def choose(self, opt_id: Optional[str]) -> None:
        if opt_id is None or not opt_id.isdigit():
            return
        m = self._filtered[int(opt_id)]
        self.dismiss(m.get("display_id") or m.get("id"))


# ══════════════════════════════════════════════════════════════════════════════
#  Modal: marketplace de skills
# ══════════════════════════════════════════════════════════════════════════════
class MarketplaceScreen(PickerScreen):
    """Marketplace de skills: instalar / remover, com estado instalada + ativa.

    Cada item é um dict normalizado: {name, description, installed, active}.
    Enter alterna (instala se falta, remove se já tem) e devolve
    ("install"|"remove", nome) — o trabalho pesado (git clone) roda num worker.
    """

    LIST_ID = "market-list"
    SEARCH_ID = "market-search"

    def __init__(self, items: List[Dict[str, Any]], warning: str = "") -> None:
        super().__init__()
        self._items = list(items or [])
        self._warning = warning
        self._filtered: List[Dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="market-box"):
            with Horizontal(classes="picker-header"):
                yield Static(
                    Text("⬢ ", style=f"bold {GREEN}") + Text("Marketplace de skills", style=f"bold {FG}"),
                    classes="picker-title",
                )
                yield Static("", id="market-count", classes="picker-count")
            if self._warning:
                yield Static(Text(f"⚠ {self._warning}", style=f"{STARRY_GOLD}"), id="market-warn")
            yield Input(placeholder="filtrar skills…", id=self.SEARCH_ID, classes="picker-search")
            yield OptionList(id=self.LIST_ID, classes="picker-list")
            yield Static(
                Text("⏎ instala / remove · ↑↓ navega · esc fecha", style=f"{FG_MUTED}"),
                classes="picker-hint",
            )

    def on_mount(self) -> None:
        self.refill("")
        self.query_one(f"#{self.SEARCH_ID}", Input).focus()

    def _row(self, it: Dict[str, Any]) -> Text:
        t = Text()
        if it.get("active"):
            t.append("● ", style=f"bold {GREEN}")
        elif it.get("installed"):
            t.append("◍ ", style=f"bold {COBALT}")
        else:
            t.append("○ ", style=FG_MUTED)
        t.append(_ellip(it.get("name", "?"), 26), style=f"bold {FG}" if it.get("installed") else FG_DIM)
        state = "ativa" if it.get("active") else ("instalada" if it.get("installed") else "disponível")
        color = GREEN if it.get("active") else (COBALT if it.get("installed") else FG_MUTED)
        t.append(f" {state:<11}", style=color)
        t.append(_ellip(it.get("description", ""), 44), style=FG_MUTED)
        return t

    def refill(self, query: str) -> None:
        self._filtered = [
            it for it in self._items
            if _fuzzy(query, f"{it.get('name', '')} {it.get('description', '')}")
        ]
        lst = self._list()
        lst.clear_options()
        if self._filtered:
            lst.add_options([
                Option(self._row(it), id=str(i)) for i, it in enumerate(self._filtered)
            ])
            self._highlight_first()
        else:
            lst.add_options([Option(Text("nenhuma skill no catálogo", style=FG_MUTED), disabled=True)])

        count = Text()
        count.append(f"{len(self._filtered)}", style=f"bold {GREEN}")
        count.append(f" / {len(self._items)} skills", style=FG_MUTED)
        self.query_one("#market-count", Static).update(count)

    def choose(self, opt_id: Optional[str]) -> None:
        if opt_id is None or not opt_id.isdigit():
            return
        it = self._filtered[int(opt_id)]
        self.dismiss(("remove" if it.get("installed") else "install", it.get("name")))


# ══════════════════════════════════════════════════════════════════════════════
#  Modal: permissão (estilo Claude Code) — [s] sim · [n] não · [a] sempre
# ══════════════════════════════════════════════════════════════════════════════
class PermissionScreen(ModalScreen):
    """Pergunta antes de uma ferramenta que MODIFICA o sistema.

    Devolve "yes" | "no" | "always". Quem chama é o `permission_callback` do
    agente, que roda na THREAD DO WORKER e espera num `threading.Event`.
    """

    BINDINGS = [
        Binding("s", "yes", "sim"),
        Binding("y", "yes", "sim", show=False),
        Binding("enter", "yes", "sim", show=False),
        Binding("n", "no", "não"),
        Binding("escape", "no", "não", show=False),
        Binding("a", "always", "sempre"),
    ]

    def __init__(self, tool_name: str, args: Any) -> None:
        super().__init__()
        self._tool = str(tool_name)
        self._preview = _preview_args(args)
        self._diff = _pending_diff(tool_name, args)

    def compose(self) -> ComposeResult:
        with Vertical(id="perm-box"):
            yield Static(
                Text("⚠ ", style=f"bold {STARRY_GOLD}") + Text("Permissão necessária", style=f"bold {FG}"),
                id="perm-title",
            )
            yield Static(
                Text("O Vincent quer rodar ", style=FG_DIM) + Text(self._tool, style=f"bold {SCARLET}"),
                id="perm-tool",
            )
            # Edição de arquivo: o diff colorido substitui o preview cru dos
            # argumentos — dá pra ver o que muda antes de aprovar.
            if self._diff:
                yield Static(_diff_text(self._diff), id="perm-diff")
            elif self._preview:
                yield Static(Text(self._preview, style=f"{FG}"), id="perm-preview")
            hint = Text()
            hint.append(" s ", style=f"bold {NIGHT} on {GREEN}")
            hint.append(" sim   ", style=FG_DIM)
            hint.append(" n ", style=f"bold {NIGHT} on {SCARLET}")
            hint.append(" não   ", style=FG_DIM)
            hint.append(" a ", style=f"bold {NIGHT} on {COBALT}")
            hint.append(" sempre (liga autoedit)", style=FG_DIM)
            yield Static(hint, id="perm-hint")

    def action_yes(self) -> None:
        self.dismiss("yes")

    def action_no(self) -> None:
        self.dismiss("no")

    def action_always(self) -> None:
        self.dismiss("always")


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
       MODAIS DE ESCOLHA — modelos e marketplace (superfície elevada)
       ═══════════════════════════════════════════════════════════════════ */
    ModelsScreen, MarketplaceScreen, PermissionScreen {
        align: center middle;
    }
    #models-box, #market-box {
        width: 96;
        max-width: 94%%;
        height: 80%%;
        max-height: 44;
        background: %(PANEL)s;
        border: round %(ACCENT_2)s;
        padding: 1 2 1 2;
    }
    #market-box {
        border: round %(OK)s;
    }
    .picker-header {
        height: 1;
        margin: 0 0 1 0;
    }
    .picker-title {
        width: auto;
        height: 1;
        content-align: left middle;
    }
    .picker-count {
        width: 1fr;
        height: 1;
        content-align: right middle;
    }
    .picker-search {
        height: 3;
        background: %(ELEVATED)s;
        border: round %(BORDER)s;
        color: %(FG)s;
        margin: 0 0 1 0;
    }
    .picker-search:focus {
        border: round %(ACCENT)s;
    }
    .picker-search > .input--placeholder {
        color: %(FG_MUTED)s;
    }
    .picker-list {
        height: 1fr;
        background: %(SURFACE)s;
        border: round %(BORDER)s;
        margin: 0 0 1 0;
        padding: 0 1;
        scrollbar-size-vertical: 1;
    }
    .picker-list > .option-list--option-highlighted {
        background: %(ACCENT_2)s 25%%;
        text-style: bold;
    }
    .picker-list > .option-list--option-disabled {
        color: %(FG_MUTED)s;
    }
    .picker-hint {
        height: 1;
        content-align: center middle;
    }
    #market-warn {
        height: auto;
        margin: 0 0 1 0;
    }

    /* ═══════════════════════════════════════════════════════════════════
       MODAL DE PERMISSÃO — pequeno, centrado, borda de alerta
       ═══════════════════════════════════════════════════════════════════ */
    #perm-box {
        width: 96;
        max-width: 92%%;
        height: auto;
        background: %(PANEL)s;
        border: round %(WARN)s;
        padding: 1 2;
    }
    #perm-title {
        height: 1;
        margin: 0 0 1 0;
    }
    #perm-tool {
        height: auto;
        margin: 0 0 1 0;
    }
    #perm-preview {
        height: auto;
        max-height: 8;
        overflow-y: auto;
        background: %(SURFACE)s;
        border-left: thick %(WARN)s;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    #perm-diff {
        height: auto;
        max-height: 16;
        overflow-y: auto;
        overflow-x: hidden;
        background: %(SURFACE)s;
        border-left: thick %(ACCENT)s;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    #perm-hint {
        height: 1;
        content-align: center middle;
    }
    """ % {
        "BG": BG, "SURFACE": SURFACE, "PANEL": PANEL, "ELEVATED": ELEVATED,
        "BORDER": BORDER, "BORDER_SOFT": BORDER_SOFT, "FG": FG, "FG_DIM": FG_DIM,
        "FG_MUTED": FG_MUTED, "ACCENT": ACCENT, "ACCENT_2": ACCENT_2,
        "OK": OK, "WARN": WARN, "ERR": ERR, "GOLD": GOLD, "WHITE": WHITE,
    }

    # ^P fica com a palette de comandos nativa do Textual (ver
    # `get_system_commands`), que já tem busca fuzzy e descrição.
    # ^O/^S abrem os modais direto. ^O e não ^M: em xterm/gnome-terminal/tmux
    # o Ctrl+M É o byte \r, o parser do Textual o entrega como Enter e o
    # binding NUNCA dispara (com foco no Input ele só mandava a mensagem).
    # ^O também é o atalho de modelos do REPL — um só pra decorar.
    BINDINGS = [
        Binding("ctrl+c", "quit", "Sair", priority=True),
        Binding("ctrl+q", "quit", "Sair"),
        Binding("ctrl+l", "clear_chat", "Limpar"),
        Binding("ctrl+o", "open_models", "Modelos"),
        Binding("ctrl+s", "open_marketplace", "Skills"),
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
        self._auto_hidden: Dict[str, bool] = {}   # painel -> escondido por largura

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
                        ("/model", "seletor ^O"),
                        ("/marketplace", "skills ^S"),
                        ("/effort", "raciocínio"),
                        ("/autoedit", "permissão"),
                        ("/reload", "re-varre"),
                        ("/caveman", "compressão"),
                        ("/act", "modo agente"),
                        ("/ask", "chat direto"),
                        ("/clear", "limpar"),
                    ):
                        row = Text()
                        row.append(f"{key:<13}", style=f"bold {ACCENT}")
                        row.append(desc, style=f"{FG_DIM}")
                        yield Static(row, classes="side-row")
                yield Static(
                    Text("^P", style=f"bold {ACCENT}") + Text(" palette  ", style=FG_MUTED)
                    + Text("^O", style=f"bold {ACCENT}") + Text(" modelos\n", style=FG_MUTED)
                    + Text("^S", style=f"bold {ACCENT}") + Text(" skills   ", style=FG_MUTED)
                    + Text("^L", style=f"bold {ACCENT}") + Text(" limpa\n", style=FG_MUTED)
                    + Text("^B", style=f"bold {ACCENT}") + Text(" sidebar  ", style=FG_MUTED)
                    + Text("^T", style=f"bold {ACCENT}") + Text(" trace", style=FG_MUTED),
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
            self._wire_agent()
            self._post_welcome()
            self._refresh_status()

    def _wire_agent(self) -> None:
        """Pluga o prompt de permissão do agente no modal da TUI."""
        try:
            self._agent.permission_callback = self._permission_callback
        except Exception:
            pass

    def _post_welcome(self) -> None:
        conv = self.query_one("#conversation", VerticalScroll)
        conv.mount(ChatMessage("system", (
            "Bem-vindo ao **Vincent**. Converse normalmente ou peça uma tarefa — "
            "eu decido sozinho quando investigar o código e rodar ferramentas.\n\n"
            "`/help` lista os comandos · `^P` abre a palette · `^O` os modelos · `^S` o marketplace de skills."
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
        self._wire_agent()
        self._post_welcome()
        self._refresh_status()
        self.query_one(TracePanel).step("✦ motor neural online")

    # ── Permission prompt (estilo Claude Code) ────────────────────────────────
    def _permission_callback(self, tool_name: str, args: Any) -> bool:
        """Chamado pelo agente na THREAD DO WORKER quando `autoedit` está off.

        A UI só pode ser tocada na thread do app, então: `call_from_thread`
        empurra o modal e um `threading.Event` segura o worker até o usuário
        responder. Sem UI viva (ou timeout) → NEGA, que é o lado seguro.
        """
        answered = threading.Event()
        answer: List[str] = []

        def _open_modal() -> None:
            def _done(result: Optional[str]) -> None:
                answer.append(result or "no")
                answered.set()

            self.push_screen(PermissionScreen(tool_name, args), _done)

        try:
            self.call_from_thread(_open_modal)
        except Exception:
            return False

        # ponytail: 5 min de teto pra não pendurar o worker pra sempre se o app
        # morrer com o modal aberto; se alguém reclamar, virar espera + cancelamento.
        if not answered.wait(timeout=300):
            return False

        result = answer[0] if answer else "no"
        if result == "always":
            try:
                self._agent.autoedit = True
                self.call_from_thread(self._ui_permission_always)
            except Exception:
                pass
        try:
            self.call_from_thread(
                self._ui_step,
                ("✅ permitido: " if result != "no" else "⚠ negado: ") + str(tool_name),
            )
        except Exception:
            pass
        return result in ("yes", "always")

    def _ui_permission_always(self) -> None:
        self._add_message("system", "✎ **autoedit ligado** — não pergunto mais nesta sessão (`/autoedit off` reverte).")
        self._refresh_status()

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
        autoedit = bool(getattr(self._agent, "autoedit", True))
        busy = self.working

        sep = Text("  ·  ", style=f"{BORDER}")
        line = Text()
        line.append_text(self._badge("◆", str(model), ACCENT))
        line.append_text(sep)
        line.append_text(self._badge("⚙ effort", str(effort), WARN))
        line.append_text(sep)
        # ✎ autoedit off = pede permissão antes de mexer no sistema (verde = seguro).
        line.append_text(self._badge("✎ autoedit", "on" if autoedit else "off", OK if autoedit else ACCENT_2))
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

        if cmd in ("marketplace", "skills", "market"):
            self.action_open_marketplace()
            return

        if cmd in ("reload-plugins", "reload", "plugins"):
            self._reload_plugins()
            return

        if cmd == "autoedit":
            val = arg.lower()
            if self._agent is None:
                self._add_message("system", "⚠️ Motor ainda não está pronto.")
            elif val not in ("on", "off"):
                cur = "on" if getattr(self._agent, "autoedit", True) else "off"
                self._add_message("system", f"Uso: `/autoedit <on|off>` — atual: **{cur}**. `off` = pergunto antes de rodar comando/editar/commitar.")
            else:
                self._agent.autoedit = (val == "on")
                self._add_message("system", (
                    "✎ **autoedit on** — executo ferramentas sem perguntar."
                    if val == "on" else
                    "✎ **autoedit off** — vou pedir permissão antes de mexer no sistema."
                ))
                self._refresh_status()
            self._scroll_conversation()
            return

        if cmd == "model":
            if not arg:
                # Sem argumento abre o seletor — nada de "Uso: /model <id>".
                self.action_open_models()
                return
            if self._agent is None:
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

    def on_resize(self, event) -> None:
        """Esconde o cromo quando não cabe: a 80 colunas a sidebar (26) mais o
        trace (30) comiam 56 e sobravam ~20 pro chat. Só reage quando a
        largura CRUZA o limite — ^B/^T continuam mandando entre uma e outra."""
        width = event.size.width
        for selector, limit in (("#side", 100), ("#sidebar", 78)):
            hide = width < limit
            if self._auto_hidden.get(selector) is hide:
                continue
            self._auto_hidden[selector] = hide
            try:
                self.query_one(selector).set_class(hide, "-hidden")
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

    # ── Marketplace de skills ─────────────────────────────────────────────────
    def _marketplace_items(self) -> Tuple[List[Dict[str, Any]], str]:
        """Junta o catálogo remoto com o que já está instalado no disco.

        `vincent.marketplace` é de outro agente e pode não existir ainda — o
        import é protegido e a UI cai pro que está instalado, com aviso.
        """
        warning = ""
        raw: List[Any] = []
        try:
            from vincent import marketplace as mk  # type: ignore
            raw = list(mk.catalog() or [])
        except Exception as e:
            warning = f"catálogo remoto indisponível ({type(e).__name__}) — listando só o que já está instalado"

        installed: set = set()
        try:
            from vincent.skills import list_skills
            installed |= {s.get("name", "") for s in list_skills()}
        except Exception:
            pass
        plugins = getattr(self._agent, "plugins", None)
        local_desc: Dict[str, str] = {}
        if plugins is not None:
            try:
                installed |= set(plugins.skills.keys())
                local_desc = {k: v.get("description", "") for k, v in plugins.skills.items()}
            except Exception:
                pass
        active: set = set(getattr(plugins, "active_plugins", set()) or set())

        items: List[Dict[str, Any]] = []
        seen: set = set()
        for entry in raw:
            if isinstance(entry, str):
                entry = {"name": entry}
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or entry.get("id") or "?")
            seen.add(name)
            # `desc` é a chave do vincent.marketplace; as outras são tolerância.
            desc = entry.get("desc") or entry.get("description") or entry.get("summary") or entry.get("title") or ""
            items.append({
                "name": name,
                "description": str(desc),
                "installed": bool(entry.get("installed", name in installed)),
                "active": bool(entry.get("active", name in active)),
            })
        for name in sorted(installed - seen):
            if not name:
                continue
            items.append({
                "name": name,
                "description": local_desc.get(name, "instalada localmente"),
                "installed": True,
                "active": name in active,
            })
        return items, warning

    def action_open_marketplace(self) -> None:
        items, warning = self._marketplace_items()

        def _acted(choice: Optional[Any]) -> None:
            if not choice:
                return
            action, name = choice
            self._add_message("system", f"⬢ {'Instalando' if action == 'install' else 'Removendo'} `{name}`…")
            self._scroll_conversation()
            self._marketplace_worker(action, name)

        self.push_screen(MarketplaceScreen(items, warning), _acted)

    @work(thread=True, group="marketplace")
    def _marketplace_worker(self, action: str, name: str) -> None:
        """git clone / rmtree são I/O — fora da thread da UI."""
        try:
            from vincent import marketplace as mk  # type: ignore
            res = (mk.install if action == "install" else mk.remove)(name)
            # a API devolve {"ok", "msg"} em vez de levantar exceção
            if isinstance(res, dict):
                msg = ("✅ " if res.get("ok") else "⚠️ ") + str(res.get("msg") or name)
            else:
                msg = f"✅ `{name}` {'instalada' if action == 'install' else 'removida'}."
        except Exception as e:
            msg = f"⚠️ Falha ao {action} `{name}`: {e}"
        self.call_from_thread(self._ui_marketplace_done, msg)

    def _ui_marketplace_done(self, msg: str) -> None:
        self._add_message("system", msg)
        self._scroll_conversation()
        self._reload_plugins(quiet=True)

    # ── Plugins / effort ──────────────────────────────────────────────────────
    def _reload_plugins(self, quiet: bool = False) -> None:
        if self._agent is None:
            self._add_message("system", "⚠️ Motor ainda não está pronto.")
            self._scroll_conversation()
            return
        try:
            n_plugins = self._agent.plugins.scan_skills()
        except Exception as e:
            self._add_message("system", f"⚠️ Falha ao re-varrer plugins: {e}")
            self._scroll_conversation()
            return
        try:
            from vincent.skills import list_skills
            n_skills = len(list_skills())
        except Exception:
            n_skills = 0
        active = len(getattr(self._agent.plugins, "active_plugins", set()) or set())
        if not quiet:
            self._add_message(
                "system",
                f"🔄 Recarregado: **{n_plugins}** plugins ({active} ativos) · **{n_skills}** skills.",
            )
            self._scroll_conversation()
        try:
            self.query_one(TracePanel).step(f"⚙ plugins recarregados: {n_plugins} · skills: {n_skills}")
        except Exception:
            pass

    def _set_effort(self, level: str) -> None:
        if self._agent is None:
            self._add_message("system", "⚠️ Motor ainda não está pronto.")
        else:
            self._agent.model_manager.effort = level
            self._add_message("system", f"⚙ Effort agora é **{level}**.")
            self._refresh_status()
        self._scroll_conversation()

    def _toggle_autoedit(self) -> None:
        if self._agent is None:
            return
        self._handle_slash("/autoedit " + ("off" if getattr(self._agent, "autoedit", True) else "on"))

    # ── Palette de comandos (^P — nativa do Textual, com busca fuzzy) ──────────
    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield SystemCommand("Modelos", "Seletor de modelos com busca (^O)", self.action_open_models)
        yield SystemCommand("Marketplace", "Instalar / remover skills (^S)", self.action_open_marketplace)
        yield SystemCommand("Recarregar plugins", "Re-varre skills e plugins do disco", self._reload_plugins)
        for lvl in ("low", "medium", "high"):
            yield SystemCommand(f"Effort: {lvl}", f"Nível de raciocínio → {lvl}", lambda l=lvl: self._set_effort(l))
        yield SystemCommand("Autoedit: alternar", "off = pede permissão antes de mexer no sistema", self._toggle_autoedit)
        yield SystemCommand("Limpar conversa", "Esvazia a conversa e o trace (^L)", self.action_clear_chat)
        yield SystemCommand("Sidebar", "Mostra/esconde a barra lateral (^B)", self.action_toggle_sidebar)
        yield SystemCommand("Trace agêntico", "Mostra/esconde o painel de trace (^T)", self.action_toggle_trace)
        yield SystemCommand("Ajuda", "Comandos e atalhos do Vincent", lambda: self._handle_slash("/help"))
        yield from super().get_system_commands(screen)


def main() -> None:
    """Ponto único por onde `vincent --tui` e o /tui do REPL passam.

    Sem TTY o Textual fica desenhando pra sempre num pipe (84KB de ANSI cru e
    um relógio redesenhando 1x/s, até o timeout matar) — a guarda mora aqui,
    e não em cada chamador, justamente por ser o ponto único.
    """
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("A TUI de tela cheia precisa de um terminal interativo (TTY).\n"
              "Sem TTY, use o REPL: `vincent`, ou o painel de texto: `/tui workers`.",
              file=sys.stderr)
        return
    VincentTUI().run()


if __name__ == "__main__":
    main()
