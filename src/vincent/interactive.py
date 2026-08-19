"""
Vincent CLI — Camada Interativa 'Noite Estrelada'.

Substitui o `input()` cru do REPL por uma interface de verdade: picker fuzzy
navegável (adeus "+35 rotas adicionais"), sessão de prompt com histórico,
autocomplete de comandos/argumentos, bottom toolbar ao vivo e permission-prompt
estilo Claude Code.

Tudo degrada sem dor: se prompt_toolkit não existir ou não houver TTY, cada
função cai no comportamento antigo (print/input) sem levantar exceção.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .agent_tools import is_ignored
from .ui import (
    CLR_RST, CLR_BOLD, COBALT_BLUE, CHROME_YELLOW, STARRY_GOLD,
    CYPRESS_GREEN, VIOLET_SWIRL, ALERT_SCARLET, SHADOW_GRAY,
    CANVAS_WHITE, get_terminal_width,
)

# ─── prompt_toolkit é opcional: sem ele o Vincent volta ao modo texto ──────────
try:
    from prompt_toolkit.application import Application, run_in_terminal
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.completion import Completer, Completion, PathCompleter
    from prompt_toolkit.document import Document
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, VSplit, Window
    from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.shortcuts import PromptSession
    from prompt_toolkit.styles import Style

    HAS_PTK = True
except Exception:  # pragma: no cover - só roda em ambiente sem prompt_toolkit
    HAS_PTK = False
    Completer = object  # type: ignore
    PromptSession = None  # type: ignore


def supports_interactive() -> bool:
    """True quando dá pra desenhar a interface rica.

    Vale TTY de verdade **ou** um AppSession com input/output injetados
    (`create_app_session(input=pipe, output=DummyOutput())`) — é assim que os
    testes dirigem pick_model/browse_models sem terminal nenhum.
    """
    if not HAS_PTK:
        return False
    try:
        from prompt_toolkit.application.current import get_app_session
        sess = get_app_session()
        # _input/_output só existem quando alguém injetou: o AppSession padrão
        # cria os dele preguiçosamente a partir do stdio.
        if getattr(sess, "_input", None) is not None or getattr(sess, "_output", None) is not None:
            return True
    except Exception:
        pass
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False


# ─── Paleta Noite Estrelada em hex (prompt_toolkit não fala ANSI cru) ──────────
NIGHT_STYLE = {
    "search.label": "#4a7fd4 bold",
    "search.input": "#e4e4e4",
    "title": "#4a7fd4 bold",
    "subtitle": "#6c7086",
    "counter": "#ffd700 bold",
    "header": "#9d7fd4 bold",
    "selected": "bg:#4a7fd4 #0b1020 bold",
    "item": "#e4e4e4",
    "item.local": "#00ff87",
    "item.combo": "#4a7fd4",
    "item.free": "#ffd700",
    "item.pro": "#9d7fd4",
    "footer": "#6c7086",
    "sep": "#2b3a55",
    "prompt": "#4a7fd4 bold",
    "prompt.model": "#ffd700",
    "prompt.arrow": "#00ff87 bold",
    "bottom-toolbar": "bg:#0b1020 #6c7086",
    "bottom-toolbar.model": "bg:#0b1020 #4a7fd4 bold",
    "bottom-toolbar.on": "bg:#0b1020 #00ff87",
    "bottom-toolbar.off": "bg:#0b1020 #6c7086",
    "bottom-toolbar.gold": "bg:#0b1020 #ffd700",
    "completion-menu.completion": "bg:#101a2e #e4e4e4",
    "completion-menu.completion.current": "bg:#4a7fd4 #0b1020 bold",
    "completion-menu.meta.completion": "bg:#101a2e #6c7086",
    "completion-menu.meta.completion.current": "bg:#4a7fd4 #0b1020",
    "auto-suggestion": "#3d4761",
}


def _style() -> "Style":
    return Style.from_dict(NIGHT_STYLE)


# ─── Fuzzy: subsequência com score (prefixo > contíguo > espalhado) ────────────
_FIELD_WEIGHTS = (
    ("display_id", 1.0),
    ("cmd", 1.0),
    ("id", 0.9),
    ("name", 0.7),
    ("desc", 0.6),
    ("provider", 0.5),
    ("group", 0.4),
)
_WORD_BREAKS = "-_/:. ,"


def fuzzy_score(query: str, text: str) -> Optional[float]:
    """Pontua `text` contra `query`. None = não bate.

    Prefixo pontua mais que trecho contíguo no meio, que pontua mais que
    subsequência espalhada — é o que faz "qwen" trazer 'qwen3:0.6b' antes de
    'x-qwen-turbo' e muito antes de 'quantum-wenzel'.
    """
    if not query:
        return 0.0
    if not text:
        return None
    q, t = query.lower(), str(text).lower()

    idx = t.find(q)
    if idx >= 0:
        # Match contíguo: quanto mais no começo e menos sobra, melhor.
        return 1000.0 - idx * 5 - max(0, len(t) - len(q)) * 0.5

    score = 0.0
    pos = -1
    prev = -2
    for ch in q:
        pos = t.find(ch, pos + 1)
        if pos < 0:
            return None
        if pos == prev + 1:
            score += 6.0                      # letras coladas valem mais
        if pos == 0 or t[pos - 1] in _WORD_BREAKS:
            score += 4.0                      # início de palavra
        prev = pos
    return score - pos * 0.25                 # espalhar até o fim penaliza


def _score_term(term: str, item: Any) -> Optional[float]:
    """Melhor score de UM termo no item, olhando display_id/name/provider."""
    if not isinstance(item, dict):
        return fuzzy_score(term, str(item))
    best: Optional[float] = None
    for key, weight in _FIELD_WEIGHTS:
        val = item.get(key)
        if not isinstance(val, str):
            continue
        s = fuzzy_score(term, val)
        if s is None:
            continue
        s *= weight
        if best is None or s > best:
            best = s
    return best


def score_item(query: str, item: Any) -> Optional[float]:
    """Score do item contra a busca inteira. None = não bate.

    Espaço separa termos e todos precisam bater (AND): "claude opus" acha
    'vincent/claude-opus-5', que é como qualquer pessoa busca de verdade.
    """
    terms = str(query or "").split()
    if not terms:
        return 0.0
    total = 0.0
    for term in terms:
        s = _score_term(term, item)
        if s is None:
            return None
        total += s
    return total


def _fit_hint(hint: str, room: int) -> str:
    """Encolhe uma dica 'a · b · c' até caber, preservando o ÚLTIMO pedaço
    (que é sempre como sair — cortar isso deixa o usuário preso)."""
    hint = str(hint or "")
    if len(hint) <= room:
        return hint
    parts = [p for p in hint.split(" · ") if p]
    if not parts:
        return hint[:room]
    tail, out = parts[-1], ""
    for part in parts[:-1]:
        cand = f"{out} · {part}".strip(" ·")
        if len(cand) + 3 + len(tail) > room:
            break
        out = cand
    return f"{out} · {tail}".strip(" ·")[:room]


def _ellip(text: str, width: int) -> str:
    """Corta com reticências e preenche até `width` (colunas alinhadas)."""
    text = str(text)
    if width <= 0:
        return ""
    if len(text) > width:
        return text[:max(1, width - 1)] + "…"
    return text.ljust(width)


# ─── Picker fuzzy full-screen ─────────────────────────────────────────────────
class FuzzyPicker:
    """Lista navegável de N itens (485 modelos rodam lisos: só a janela visível
    é renderizada). Enter devolve o item; Esc/Ctrl+C devolvem None."""

    def __init__(self, items: List[Dict], title: str, subtitle: str = "",
                 group_key: Optional[Callable[[Dict], Optional[str]]] = None,
                 render_row: Optional[Callable[[Dict, bool], str]] = None,
                 initial_query: str = "", footer_hint: Optional[str] = None,
                 height: Optional[int] = None):
        self.items = list(items or [])
        self.title = title
        self.subtitle = subtitle
        self.group_key = group_key
        self.render_row = render_row or (lambda it, sel: str(
            it.get("display_id") or it.get("cmd") or it.get("name") or it
        ))
        self.initial_query = initial_query or ""
        # As duas ações que ninguém adivinha vão juntas no FIM: _fit_hint corta
        # do começo pra dentro e sempre preserva o último pedaço.
        self.footer_hint = footer_hint or (
            "↑↓/Ctrl+P·Ctrl+N navegar · PgUp/PgDn página · Home/End extremos · "
            "Ctrl+U limpar · Enter escolhe/Esc sai"
        )
        self.height = height or self._auto_height()
        self.entries: List[Dict] = []
        self.index = -1
        self.offset = 0
        self._matches = len(self.items)

    # ── layout helpers ────────────────────────────────────────────────────
    @staticmethod
    def _auto_height() -> int:
        try:
            rows = shutil.get_terminal_size((80, 24)).lines
        except Exception:
            rows = 24
        return max(5, min(22, rows - 8))

    def _width(self) -> int:
        return max(24, min(get_terminal_width(), 120))

    def _row_class(self, item: Dict) -> str:
        g = ""
        if self.group_key:
            try:
                g = (self.group_key(item) or "").upper()
            except Exception:
                g = ""
        if "LOCAL" in g:
            return "class:item.local"
        if "COMBO" in g:
            return "class:item.combo"
        if "ZERO-KEY" in g or "FREE" in g or "GRAT" in g:
            return "class:item.free"
        if "PRO" in g:
            return "class:item.pro"
        return "class:item"

    # ── filtro / navegação ────────────────────────────────────────────────
    def _rebuild(self, query: str = ""):
        query = (query or "").strip()
        if query:
            scored = []
            for it in self.items:
                s = score_item(query, it)
                if s is not None:
                    scored.append((s, it))
            scored.sort(key=lambda p: -p[0])          # sort estável: empate = ordem original
            # Com busca ativa os cabeçalhos somem — o ranking manda.
            self.entries = [{"header": None, "item": it} for _, it in scored]
        else:
            entries: List[Dict] = []
            last = None
            for it in self.items:
                g = None
                if self.group_key:
                    try:
                        g = self.group_key(it)
                    except Exception:
                        g = None
                if g and g != last:
                    entries.append({"header": g, "item": None})
                    last = g
                entries.append({"header": None, "item": it})
            self.entries = entries
        self._matches = sum(1 for e in self.entries if e["item"] is not None)
        self.offset = 0
        self.index = self._next_selectable(-1, +1)

    def _next_selectable(self, start: int, step: int) -> int:
        i = start + step
        while 0 <= i < len(self.entries):
            if self.entries[i]["item"] is not None:
                return i
            i += step
        return start if 0 <= start < len(self.entries) and self.entries[start]["item"] is not None else -1

    def _move(self, step: int):
        nxt = self._next_selectable(self.index, step)
        if nxt >= 0:
            self.index = nxt
        self._clamp()

    def _jump(self, to_end: bool):
        if to_end:
            self.index = self._next_selectable(len(self.entries), -1)
        else:
            self.index = self._next_selectable(-1, +1)
        self._clamp()

    def _page(self, direction: int):
        for _ in range(max(1, self.height - 1)):
            nxt = self._next_selectable(self.index, direction)
            if nxt < 0 or nxt == self.index:
                break
            self.index = nxt
        self._clamp()

    def _clamp(self):
        if self.index < 0:
            self.offset = 0
            return
        if self.index < self.offset:
            self.offset = self.index
        elif self.index >= self.offset + self.height:
            self.offset = self.index - self.height + 1
        self.offset = max(0, min(self.offset, max(0, len(self.entries) - self.height)))

    def selection(self) -> Optional[Dict]:
        if 0 <= self.index < len(self.entries):
            return self.entries[self.index]["item"]
        return None

    # ── render ────────────────────────────────────────────────────────────
    def _render_header(self):
        """Contador SEMPRE visível (é a única pista de quantos itens sobraram);
        o subtítulo é o primeiro a cair quando o terminal aperta."""
        width = self._width()
        counter = f"[{self._matches}/{len(self.items)}]"
        line = f" {self.title} "
        if self.subtitle and len(line) + len(self.subtitle) + len(counter) + 4 <= width:
            line += f"— {self.subtitle} "
        line = line[:max(0, width - len(counter) - 1)]
        pad = max(1, width - len(line) - len(counter))
        return [("class:title", line), ("class:subtitle", " " * pad), ("class:counter", counter)]

    def _render_list(self):
        self._clamp()
        width = self._width()
        frags = []
        if not self.entries:
            return [("class:footer", "  (nenhum resultado — Ctrl+U limpa a busca)")]
        view = self.entries[self.offset:self.offset + self.height]
        for i, e in enumerate(view, start=self.offset):
            if e["header"]:
                frags.append(("class:header", f"  {e['header']}".ljust(width)[:width] + "\n"))
                continue
            item = e["item"]
            selected = (i == self.index)
            try:
                text = str(self.render_row(item, selected))
            except Exception:
                text = str(item)
            text = (("❯ " if selected else "  ") + text).replace("\n", " ")
            text = text[:width].ljust(width)
            frags.append(("class:selected" if selected else self._row_class(item), text + "\n"))
        return frags

    def _render_footer(self):
        """Rolagem à ESQUERDA (com 343 itens, saber onde se está é o que
        importa) e a ajuda encolhendo à direita — 'Esc sair' nunca some."""
        above = self.offset
        below = max(0, len(self.entries) - (self.offset + self.height))
        scroll = f" ▲{above} ▼{below} " if (above or below) else " "
        room = max(0, self._width() - len(scroll))
        return [("class:counter", scroll),
                ("class:footer", _fit_hint(self.footer_hint, room))]

    # ── execução ──────────────────────────────────────────────────────────
    def run(self) -> Optional[Dict]:
        if supports_interactive():
            try:
                return self._run_ptk()
            except Exception:
                # Nunca deixa a interface derrubar o REPL — cai no texto.
                # Sem isto, um bug de layout virava 485 linhas de cuspe sem
                # nenhuma pista do motivo. VINCENT_DEBUG=1 mostra a pista.
                if os.environ.get("VINCENT_DEBUG"):
                    import traceback
                    traceback.print_exc(file=sys.stderr)
                return self._run_plain()
        return self._run_plain()

    def _run_ptk(self) -> Optional[Dict]:
        buf = Buffer(multiline=False)
        buf.text = self.initial_query
        # O setter de .text só clipa o cursor pra baixo: sem isto ele fica na
        # coluna 0 e o que o usuário digitar entra ANTES da busca pré-preenchida
        # ("/search qwen" + tecla '3' virava '3qwen').
        buf.cursor_position = len(buf.text)
        self._rebuild(buf.text)

        def _on_change(_):
            self._rebuild(buf.text)

        buf.on_text_changed += _on_change

        kb = KeyBindings()

        @kb.add("up")
        @kb.add("c-p")
        def _(event):
            self._move(-1)

        @kb.add("down")
        @kb.add("c-n")
        def _(event):
            self._move(+1)

        @kb.add("pageup")
        def _(event):
            self._page(-1)

        @kb.add("pagedown")
        def _(event):
            self._page(+1)

        @kb.add("home")
        def _(event):
            self._jump(False)

        @kb.add("end")
        def _(event):
            self._jump(True)

        @kb.add("c-u")
        def _(event):
            buf.text = ""   # `reset()` não dispara on_text_changed — a lista ficaria filtrada

        @kb.add("enter")
        def _(event):
            event.app.exit(result=self.selection())

        @kb.add("escape", eager=True)
        @kb.add("c-c")
        @kb.add("c-g")
        def _(event):
            event.app.exit(result=None)

        # Nota: 'q' NÃO fecha o picker — com 485 modelos, "qwen" é a busca mais
        # provável do mundo. Sair é Esc / Ctrl+C / Ctrl+G.

        body = HSplit([
            Window(FormattedTextControl(self._render_header), height=1),
            VSplit([
                Window(FormattedTextControl([("class:search.label", " 🔍 ")]), width=4, height=1),
                Window(BufferControl(buffer=buf), height=1, style="class:search.input"),
            ], height=1),
            Window(char="─", height=1, style="class:sep"),
            Window(FormattedTextControl(self._render_list, focusable=False),
                   height=Dimension(preferred=self.height, max=self.height)),
            Window(char="─", height=1, style="class:sep"),
            Window(FormattedTextControl(self._render_footer), height=1),
        ])

        app = Application(layout=Layout(body), key_bindings=kb, style=_style(),
                          full_screen=True, mouse_support=False)
        return app.run()

    def _run_plain(self) -> Optional[Dict]:
        """Sem prompt_toolkit/TTY: lista COMPLETA (nada de '+N adicionais') e
        escolha por número."""
        self._rebuild(self.initial_query)
        if not self.entries:
            return None
        try:
            interactive = sys.stdin.isatty()
        except Exception:
            interactive = False

        print(f"\n{COBALT_BLUE}◈ {self.title}{CLR_RST} {SHADOW_GRAY}{self.subtitle}{CLR_RST}")
        n = 0
        numbered: List[Dict] = []
        for e in self.entries:
            if e["header"]:
                print(f"{VIOLET_SWIRL}  {e['header']}{CLR_RST}")
                continue
            n += 1
            numbered.append(e["item"])
            try:
                row = str(self.render_row(e["item"], False))
            except Exception:
                row = str(e["item"])
            print(f"  {SHADOW_GRAY}{n:>4}{CLR_RST} {row}")
        if not interactive:
            return None
        try:
            raw = input(f"{CHROME_YELLOW}Número (Enter cancela): {CLR_RST}").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(numbered):
            return numbered[int(raw) - 1]
        return None


# ─── Pickers de modelo ────────────────────────────────────────────────────────
GROUP_LOCAL = "◈ PALETA LOCAL"
GROUP_COMBO = "◈ COMBOS"
GROUP_FREE = "◈ ROTAS ZERO-KEY"
GROUP_PRO = "◈ ATELIER PRO"
_GROUP_ORDER = {GROUP_LOCAL: 0, GROUP_COMBO: 1, GROUP_FREE: 2, GROUP_PRO: 3}


def model_group(m: Dict) -> str:
    if m.get("is_local"):
        return GROUP_LOCAL
    if str(m.get("id", "")).startswith("auto"):
        return GROUP_COMBO
    if m.get("is_free"):
        return GROUP_FREE
    return GROUP_PRO


def model_badge(m: Dict) -> str:
    return {GROUP_LOCAL: "⚡", GROUP_COMBO: "◆", GROUP_FREE: "🆓", GROUP_PRO: "▲"}[model_group(m)]


def _model_rows(agent) -> List[Dict]:
    try:
        models = agent.model_manager.get_all_models() or []
    except Exception:
        models = []
    # str(... or "") porque display_id=None (chave presente, valor nulo) fazia
    # o sorted estourar TypeError e o picker simplesmente não abria.
    return sorted(models, key=lambda m: (_GROUP_ORDER[model_group(m)],
                                         str(m.get("display_id") or "")))


def _current_ids(agent) -> set:
    ids = set()
    for attr in ("display_model", "model"):
        try:
            v = getattr(agent, attr, None)
            if isinstance(v, str) and v:
                ids.add(v)
        except Exception:
            pass
    return ids


def _make_model_renderer(agent):
    current = _current_ids(agent)

    def _row(m: Dict, selected: bool) -> str:
        mark = "●" if m.get("display_id") in current or m.get("id") in current else " "
        disp = str(m.get("display_id") or m.get("id") or "")
        name = str(m.get("name") or "")
        if name.startswith(disp):
            name = name[len(disp):].strip(" ()")
        if not name:
            # ~340 modelos de nuvem têm name == display_id: em vez de 44 colunas
            # em branco, mostra de onde a rota vem.
            name = str(m.get("provider") or "")
        # Colunas seguem a largura REAL do terminal (34 fixos cortavam
        # 'vincent/claude-opus-4-5-20251101-high' bem no -high/-low/-medium).
        total = max(30, min(get_terminal_width(), 120) - 7)
        id_w = max(18, min(60, int(total * 0.62)))
        return f"{mark} {model_badge(m)} {_ellip(disp, id_w)} {_ellip(name, total - id_w - 1)}"

    return _row


def _run_model_picker(agent, initial_query: str, title: str, subtitle: str) -> Optional[str]:
    models = _model_rows(agent)
    if not models:
        print(f"\n{ALERT_SCARLET}⚠ Nenhum modelo indexado nos ateliers.{CLR_RST}")
        print(f"{SHADOW_GRAY}Confira a Galeria Vincent (:20128) ou o Atelier Local (:11434).{CLR_RST}\n")
        return None
    picker = FuzzyPicker(
        models, title=title, subtitle=subtitle, group_key=model_group,
        render_row=_make_model_renderer(agent), initial_query=initial_query,
    )
    chosen = picker.run()
    if not chosen:
        return None
    return chosen.get("display_id") or chosen.get("id")


def pick_model(agent, initial_query: str = "") -> Optional[str]:
    """Picker de TODOS os modelos. Devolve o display_id (não troca o modelo)."""
    return _run_model_picker(
        agent, initial_query,
        "SINTONIZAR PINCELADA NEURAL",
        "digite pra filtrar entre todas as rotas",
    )


def browse_models(agent, initial_query: str = "") -> Optional[str]:
    """Catálogo navegável (substitui o /models truncado). Enter TAMBÉM troca."""
    chosen = _run_model_picker(
        agent, initial_query,
        "CATÁLOGO DE OBRAS NEURAIS",
        "Enter sintoniza o modelo escolhido",
    )
    if not chosen:
        return None
    try:
        agent.set_model(chosen)
        print(f"{CYPRESS_GREEN}✓ Modelo ativo alterado para: {agent.display_model}{CLR_RST}\n")
    except Exception as e:
        print(f"{ALERT_SCARLET}✗ Falha ao trocar de modelo: {e}{CLR_RST}\n")
    return chosen


def pick_command(commands: List[Dict], initial_query: str = "") -> Optional[str]:
    """Paleta de comandos. Devolve a string do comando (ex: '/models')."""
    cmds = list(commands or [])
    if not cmds:
        return None

    def _row(c: Dict, selected: bool) -> str:
        usage = f"{c.get('cmd', '')} {c.get('args', '')}".strip()
        return f"  {usage:<28.28} {str(c.get('desc', ''))[:56]}"

    picker = FuzzyPicker(
        cmds, title="PALETA DE COMANDOS", subtitle="Enter insere o comando",
        group_key=(lambda c: c.get("group")) if any(c.get("group") for c in cmds) else None,
        render_row=_row, initial_query=initial_query,
    )
    chosen = picker.run()
    return chosen.get("cmd") if chosen else None


# ─── Menções a arquivo com '@' ────────────────────────────────────────────────
_MENTION_TTL = 5.0            # o índice de arquivos é refeito a cada 5s
_MENTION_MAX_ENTRIES = 4000   # teto do scan (monorepo não pode travar a tecla)
_mention_cache: Dict[str, Any] = {}


def _git_files(root: str) -> Optional[List[str]]:
    """Rastreados + não rastreados, já filtrados pelo .gitignore.

    Deixa o git aplicar as regras de ignore (inclusive .gitignore aninhado e o
    global) em vez de reimplementar o matcher. None = aqui não tem git.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root, capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def _walk_files(root: str) -> List[str]:
    """Sem git: varredura crua usando o IGNORE_PATTERNS do agent_tools."""
    files: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not is_ignored(d)]
        for name in filenames:
            if is_ignored(name):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            files.append(rel.replace(os.sep, "/"))
            if len(files) >= _MENTION_MAX_ENTRIES:
                return files
    return files


def project_files(root: Optional[str] = None) -> List[Dict]:
    """Índice do projeto: [{'path': 'src/vincent/ui.py', 'is_dir': False}, …].

    Diretórios entram derivados dos caminhos (o git só lista arquivos) e a
    ordem sem busca é do raso pro fundo — quem digita '@' quer ver a raiz.
    """
    root = os.path.abspath(root or os.getcwd())
    now = time.monotonic()
    hit = _mention_cache.get(root)
    if hit and now - hit[0] < _MENTION_TTL:
        return hit[1]

    try:
        files = _git_files(root)
        if files is None:
            files = _walk_files(root)
    except Exception:
        files = []
    files = sorted(set(files))[:_MENTION_MAX_ENTRIES]

    dirs = set()
    for f in files:
        parts = f.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]))

    entries = ([{"path": d, "is_dir": True} for d in dirs]
               + [{"path": f, "is_dir": False} for f in files])
    entries.sort(key=lambda e: (e["path"].count("/"), not e["is_dir"], e["path"]))
    _mention_cache[root] = (now, entries)
    return entries


def rank_mentions(query: str, root: Optional[str] = None) -> List[Dict]:
    """Entradas do projeto que batem com o trecho digitado depois do '@'.

    Sem corte: 'src vin' (AND dos termos) acha src/vincent/*, e um empate de
    score prefere o caminho mais curto — ui.py antes de build/lib/ui.py.
    """
    entries = project_files(root)
    if not str(query or "").strip():
        return entries
    scored = []
    for e in entries:
        s = score_item(query, e["path"])
        if s is not None:
            scored.append((s, e))
    scored.sort(key=lambda p: (-p[0], len(p[1]["path"])))
    return [e for _, e in scored]


def mention_text(entry: Dict) -> str:
    """'@src/vincent/' pra diretório, '@src/vincent/ui.py' pra arquivo."""
    return "@" + entry["path"] + ("/" if entry["is_dir"] else "")


# ─── Autocomplete de comandos e argumentos ────────────────────────────────────
_EFFORT_VALUES = ("low", "medium", "high")
_ONOFF_VALUES = ("on", "off")
_ARG_VALUES = {
    "/effort": _EFFORT_VALUES,
    "/autoedit": _ONOFF_VALUES,
    "/caveman": ("on", "off", "lite", "full", "ultra"),
}
_PATHS = PathCompleter(expanduser=True) if HAS_PTK else None


class VincentCompleter(Completer):
    """Completa comandos (/…) e seus argumentos conhecidos.

    Faz o fuzzy internamente (via `fuzzy_score`) em vez de usar o
    FuzzyCompleter: ele trunca o Document antes de chamar o completer interno,
    o que apaga o contexto do '/' e quebra ids de modelo com '/' dentro
    (auto/best-coding). Menos código e resultado correto.
    """

    def __init__(self, commands: List[Dict], model_ids: Optional[Callable[[], List[str]]] = None):
        self.commands = list(commands or [])
        self.model_ids = model_ids or (lambda: [])

    def _rank(self, query: str, options, key=lambda o: o):
        scored = []
        for o in options:
            s = score_item(query, key(o))
            if s is not None:
                scored.append((s, o))
        scored.sort(key=lambda p: -p[0])
        return [o for _, o in scored]

    def _paths(self, document, complete_event):
        """'@arquivo' (estilo Claude Code): busca fuzzy no índice do projeto,
        respeitando .gitignore. Palavra com '/' ou '~': PathCompleter da lib."""
        word = document.get_word_before_cursor(WORD=True)
        if word.startswith("@"):
            for e in rank_mentions(word[1:]):
                icon = "📁" if e["is_dir"] else "📄"
                yield Completion(
                    mention_text(e), start_position=-len(word),
                    display=f"{icon} {e['path']}" + ("/" if e["is_dir"] else ""),
                    display_meta="diretório" if e["is_dir"] else "arquivo",
                )
            return
        if "/" in word or word.startswith("~"):
            for c in _PATHS.get_completions(Document(word, len(word)), complete_event):
                yield Completion(c.text, start_position=c.start_position,
                                 display=c.display, display_meta="arquivo")

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            yield from self._paths(document, complete_event)
            return
        head, sep, tail = text.partition(" ")
        if not sep:
            # '/' pelado mostra o registro na ordem dos GRUPOS; a partir da 1ª
            # letra o ranking assume (antes, '/' ordenava por comprimento e
            # jogava /bg /act /tui pro topo).
            cmds = (self.commands if len(text) <= 1
                    else self._rank(text, self.commands, key=lambda c: c.get("cmd", "")))
            for c in cmds:
                cmd = c.get("cmd", "")
                yield Completion(
                    cmd, start_position=-len(text),
                    display=f"{cmd} {c.get('args', '')}".strip(),
                    display_meta=str(c.get("desc", "")),
                )
            return

        word = tail.rpartition(" ")[2]
        if head == "/model":
            # Sem corte em 200: truncar aqui é o mesmo pecado do "+N adicionais".
            for mid in self._rank(word, self.model_ids()):
                yield Completion(mid, start_position=-len(word), display=mid)
            return
        values = _ARG_VALUES.get(head)
        if values:
            for value in self._rank(word, values):
                yield Completion(value, start_position=-len(word), display=value)
            return
        yield from self._paths(document, complete_event)


# ─── Sessão de prompt ─────────────────────────────────────────────────────────
_PICK_MODEL = "\x00vincent:pick-model"
_PICK_COMMAND = "\x00vincent:pick-command"
HISTORY_PATH = os.path.join(os.path.expanduser("~"), ".vincent", "repl_history")

# (chave, ícone, rótulo, estilo fixo) — rótulo só onde o ícone sozinho é
# adivinhação ("▣ off" não diz a NINGUÉM que aquilo é o caveman).
# A ordem também é a prioridade: o que estoura a largura cai pelo fim.
_CHIP_ORDER = (
    ("model", "◆", "", "class:bottom-toolbar.model"),
    ("effort", "⚙", "", "class:bottom-toolbar.gold"),
    ("caveman", "▣", "caveman ", None),
    ("autoedit", "✎", "autoedit ", None),
    ("tier", "●", "", "class:bottom-toolbar.gold"),
    ("latency", "⏱", "", "class:bottom-toolbar"),
)
_TOOLBAR_HINT = ("Ctrl+O modelos · Ctrl+P comandos · Ctrl+L limpa · "
                 "Alt+Enter nova linha · @ anexa arquivo · Ctrl+D sai")


def _toolbar_fragments(status: Dict, width: Optional[int] = None) -> List:
    """Barra de status que CABE: 175 colunas de chips viravam quebra de linha
    no meio da palavra em qualquer terminal de 80/100 colunas."""
    width = int(width or get_terminal_width())
    frags: List = []
    used = 0
    for key, icon, label, forced in _CHIP_ORDER:
        val = status.get(key)
        if val in (None, ""):
            continue
        style = forced
        if style is None:
            style = ("class:bottom-toolbar.on" if str(val).lower() in ("on", "true", "sim")
                     else "class:bottom-toolbar.off")
        chip = f" {icon} {label}{val} "
        if used + len(chip) + 1 > width:
            break
        frags.append((style, chip))
        frags.append(("class:bottom-toolbar", "│"))
        used += len(chip) + 1
    if frags:
        frags.pop()
        used -= 1
    room = width - used - 2
    if room >= 14:
        frags.append(("class:bottom-toolbar", "  " + _fit_hint(_TOOLBAR_HINT, room)))
    return frags


def build_session(agent, commands: List[Dict], status_provider: Callable[[], Dict]):
    """Monta a PromptSession rica. Devolve None quando não dá pra usar (o
    chamador então cai no input() via read_prompt)."""
    if not supports_interactive():
        return None
    try:
        os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
        history = FileHistory(HISTORY_PATH)
    except Exception:
        history = None

    # Memo de 5s: o completer roda a CADA tecla depois de '/model ', e
    # get_all_models() com os dois caches frios refaz sync_catalogs() — uma
    # requisição de 5s de timeout + gravação em disco por letra digitada.
    _ids_cache: List = [0.0, []]

    def _model_ids() -> List[str]:
        now = time.monotonic()
        if now - _ids_cache[0] > 5.0:
            _ids_cache[:] = [now, [str(m.get("display_id") or "") for m in _model_rows(agent)]]
        return _ids_cache[1]

    def _status() -> Dict:
        try:
            return dict(status_provider() or {})
        except Exception:
            return {}

    def _bottom_toolbar():
        try:
            return _toolbar_fragments(_status())
        except Exception:
            return ""

    def _message():
        model = _status().get("model") or getattr(agent, "display_model", "vincent")
        return [
            ("class:prompt", "vincent "),
            ("class:prompt.model", f"[{model}] "),
            ("class:prompt.arrow", "❯ "),
        ]

    kb = KeyBindings()

    @kb.add("c-o")
    def _(event):
        event.app.exit(result=_PICK_MODEL)

    @kb.add("c-p")
    def _(event):
        event.app.exit(result=_PICK_COMMAND)

    @kb.add("c-l")
    def _(event):
        event.app.renderer.clear()

    @kb.add("c-c")
    def _(event):
        # Cancela só a LINHA — sair é Ctrl+D.
        event.current_buffer.reset()

    @kb.add("escape", "enter")
    @kb.add("escape", "c-m")
    def _(event):
        event.current_buffer.insert_text("\n")

    try:
        session = PromptSession(
            message=_message,
            history=history,
            auto_suggest=AutoSuggestFromHistory(),
            completer=VincentCompleter(commands, _model_ids),
            complete_while_typing=True,
            complete_in_thread=True,   # completer nunca bloqueia o desenho
            key_bindings=kb,
            bottom_toolbar=_bottom_toolbar,
            style=_style(),
            mouse_support=False,
            multiline=False,
            # SEM enable_history_search: a flag desliga o complete_while_typing
            # lá dentro (shortcuts/prompt.py) e o menu de '/' só aparecia com
            # Tab. ↑↓ continuam navegando o histórico.
        )
    except Exception:
        return None
    # read_prompt precisa dos comandos pra abrir a paleta com Ctrl+P.
    session._vincent_commands = commands  # type: ignore[attr-defined]
    return session


# Application do REPL enquanto session.prompt() está no ar — as threads de
# /bg e /spawn precisam dela pra pedir permissão sem brigar pelo teclado.
_ACTIVE_APP: Any = None


def read_prompt(session, agent) -> str:
    """Lê uma linha. Sem sessão, é `input()` puro — mesmas exceções."""
    global _ACTIVE_APP
    if session is None:
        return input(
            f"{COBALT_BLUE}vincent{CLR_RST} {CHROME_YELLOW}[{getattr(agent, 'display_model', 'vincent')}]"
            f"{CLR_RST} {CLR_BOLD}❯{CLR_RST} "
        )
    commands = getattr(session, "_vincent_commands", []) or []
    default = ""
    while True:
        _ACTIVE_APP = getattr(session, "app", None)
        try:
            text = session.prompt(default=default)
        finally:
            _ACTIVE_APP = None
        default = ""
        if text == _PICK_MODEL:
            chosen = pick_model(agent)
            if chosen:
                return f"/model {chosen}"
            continue
        if text == _PICK_COMMAND:
            cmd = pick_command(commands)
            if not cmd:
                continue
            spec = next((c for c in commands if c.get("cmd") == cmd), None)
            args = str((spec or {}).get("args", ""))
            if args and not args.startswith("["):
                # Comando que EXIGE argumento: preenche a linha em vez de
                # submeter pelado (escolher '/act <tarefa>' respondia
                # "Uso: /act <descrição>" — beco sem saída).
                default = cmd + " "
                continue
            return cmd
        return text


# ─── Permission prompt (estilo Claude Code) ───────────────────────────────────
_YES = {"s", "sim", "y", "yes"}
_ALWAYS = {"a", "always", "sempre"}


def _ask_in_terminal(func: Callable[[], Any]) -> Any:
    """Roda `func()` emprestando o terminal do prompt_toolkit.

    O callback de permissão é chamado de dentro de agentic_run — que no /bg e
    no /spawn roda em THREAD de worker enquanto a principal está parada em
    session.prompt(), com o terminal em raw mode. Dois leitores de stdin ao
    mesmo tempo roubam as teclas um do outro e a caixa impressa corrompe o
    desenho do prompt; run_in_terminal suspende o prompt, roda a pergunta e
    redesenha depois.
    """
    app = _ACTIVE_APP
    if (app is None or not getattr(app, "is_running", False)
            or threading.current_thread() is threading.main_thread()):
        return func()

    box: Dict[str, Any] = {}
    done = threading.Event()

    def _schedule():
        async def _coro():
            try:
                box["v"] = await run_in_terminal(func, in_executor=True)
            except BaseException as e:  # noqa: BLE001
                box["e"] = e
            finally:
                done.set()
        try:
            app.create_background_task(_coro())
        except BaseException as e:  # noqa: BLE001
            box["e"] = e
            done.set()

    try:
        app.loop.call_soon_threadsafe(_schedule)
    except BaseException:  # noqa: BLE001
        return func()
    done.wait()
    if "e" in box:
        return func()   # último recurso: pergunta crua, como era antes
    return box["v"]


def _permission_box(tool_name: str, preview: str) -> str:
    preview = str(preview or "").replace("\n", " ").strip()
    width = max(40, min(get_terminal_width() - 2, 96))
    inner = width - 4                      # "│ " + conteúdo + " │"
    if len(preview) > inner:
        preview = preview[:inner - 1] + "…"

    def _row(plain: str, colored: str):
        print(f"{CHROME_YELLOW}│{CLR_RST} {colored}"
              + " " * max(0, inner - len(plain))
              + f" {CHROME_YELLOW}│{CLR_RST}")

    title = "⚠ PERMISSÃO SOLICITADA"
    print(f"\n{CHROME_YELLOW}╭─[ {CLR_BOLD}{title}{CLR_RST}{CHROME_YELLOW} ]"
          + "─" * max(2, width - len(title) - 7) + f"╮{CLR_RST}")
    _row(tool_name, f"{VIOLET_SWIRL}{CLR_BOLD}{tool_name}{CLR_RST}")
    if preview:
        _row(f"› {preview}", f"{SHADOW_GRAY}› {CANVAS_WHITE}{preview}{CLR_RST}")
    opts = "[s] sim, uma vez · [n] não · [a] sempre (esta ferramenta)"
    _row(opts, f"{CYPRESS_GREEN}[s]{CLR_RST} sim, uma vez {SHADOW_GRAY}·{CLR_RST} "
               f"{ALERT_SCARLET}[n]{CLR_RST} não {SHADOW_GRAY}·{CLR_RST} "
               f"{STARRY_GOLD}[a]{CLR_RST} sempre (esta ferramenta)")
    print(f"{CHROME_YELLOW}╰" + "─" * (width - 2) + f"╯{CLR_RST}")

    try:
        ans = input(f"{CHROME_YELLOW}  ❯ {CLR_RST}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return "no"
    if ans in _ALWAYS:
        return "always"
    if ans in _YES:
        return "yes"
    return "no"


def confirm_permission(tool_name: str, preview: str) -> str:
    """Devolve 'yes' | 'no' | 'always'. Sem stdin de terminal responde 'no'.

    Exige só o stdin: com `vincent | tee sessao.log` o stdout não é TTY, e
    exigir os dois negava toda ferramenta EM SILÊNCIO — o usuário via a tarefa
    falhar sem nunca ver a pergunta.
    """
    try:
        if not sys.stdin.isatty():
            return "no"
    except Exception:
        return "no"
    return _ask_in_terminal(lambda: _permission_box(tool_name, preview))
