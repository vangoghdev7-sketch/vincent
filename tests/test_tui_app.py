"""Testes headless da TUI full-screen (`vincent --tui`).

Sem TTY, sem LLM, sem rede: usa o harness `App.run_test()` do Textual com um
agente falso. Cobre os modais novos (modelos, marketplace, permissão), a
palette de comandos e os slash commands de effort/autoedit/reload.
"""

import asyncio
import html
import os
import re
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from vincent import tui_app
from vincent.tui_app import (
    MarketplaceScreen,
    ModelsScreen,
    PermissionScreen,
    VincentTUI,
    _fuzzy,
    _group_of,
)
from textual.widgets import Input, OptionList


# ── Dublês ────────────────────────────────────────────────────────────────────
class FakeModelManager:
    def __init__(self, models):
        self.effort = "medium"
        self._models = models

    def get_all_models(self):
        return self._models

    def mask(self, m):
        return m

    def resolve(self, m):
        return m

    def is_free_tier(self, m):
        return "free" in m


class FakeCaveman:
    mode = "off"
    INTENSITY_LEVELS = ["off", "lite", "full", "ultra"]


class FakePlugins:
    def __init__(self):
        self.skills = {
            "ponytail": {"name": "ponytail", "description": "corta over-engineering", "active": True},
            "caveman": {"name": "caveman", "description": "comprime tokens", "active": True},
        }
        self.active_plugins = {"ponytail"}
        self.scans = 0

    def scan_skills(self):
        self.scans += 1
        return len(self.skills)


def _catalog(n=485):
    """485 modelos, cobrindo os quatro grupos da UI."""
    out = [
        {"id": "qwen2.5-coder:3b", "display_id": "qwen2.5-coder:3b", "name": "Qwen Coder",
         "provider": "ollama", "is_free": True, "is_local": True},
        {"id": "auto-best", "display_id": "auto-best", "name": "Auto Best",
         "provider": "omniroute", "is_free": True, "is_local": False},
    ]
    for i in range(n - len(out)):
        free = i % 2 == 0
        out.append({
            "id": f"prov{i % 7}/model-{i}{'-free' if free else ''}",
            "display_id": f"prov{i % 7}/model-{i}{'-free' if free else ''}",
            "name": f"Model {i}",
            "provider": f"prov{i % 7}",
            "is_free": free,
            "is_local": False,
        })
    return out


class FakeAgent:
    def __init__(self):
        self.model_manager = FakeModelManager(_catalog())
        self.model = "qwen2.5-coder:3b"
        self.autoedit = True
        self.permission_callback = None
        self.caveman = FakeCaveman()
        self.plugins = FakePlugins()

    @property
    def display_model(self):
        return self.model

    def set_model(self, m):
        self.model = m

    def set_caveman_mode(self, mode):
        self.caveman.mode = mode
        return True


def _app():
    return VincentTUI(agent=FakeAgent())


def svg_text(app) -> str:
    """Texto visível de um screenshot SVG, remontado por coluna (x/y).

    Sem TTY o único jeito de "olhar" a tela é o SVG do harness do Textual;
    cada run vira um <text x= y=>, então reconstruímos as linhas pela posição.
    """
    svg = app.export_screenshot()
    runs = [
        (float(m.group(2)), float(m.group(1)), html.unescape(m.group(3)))
        for m in re.finditer(
            r'<text[^>]*\bx="([\d.]+)"[^>]*\by="([\d.]+)"[^>]*>(.*?)</text>', svg, re.DOTALL
        )
    ]
    if not runs:
        return ""
    xs = sorted({x for _, x, _ in runs})
    deltas = [b - a for a, b in zip(xs, xs[1:]) if b > a]
    cell = min(deltas) if deltas else 1.0
    left = xs[0]
    lines = []
    for y in sorted({y for y, _, _ in runs}):
        row = ""
        for _, x, txt in sorted((r for r in runs if r[0] == y), key=lambda r: r[1]):
            col = int(round((x - left) / cell))
            row = row.ljust(col) + txt.replace("\xa0", " ")
        lines.append(row.rstrip())
    return "\n".join(lines)


def option_texts(screen):
    """Prompts (str) de todas as opções da OptionList do modal."""
    lst = screen.query_one(OptionList)
    return [str(lst.get_option_at_index(i).prompt) for i in range(lst.option_count)]


# ── Helpers puros ─────────────────────────────────────────────────────────────
def test_fuzzy_subsequence():
    assert _fuzzy("qwn", "qwen2.5-coder")
    assert _fuzzy("", "qualquer coisa")
    assert not _fuzzy("zzz", "qwen2.5-coder")
    assert _fuzzy("QWEN", "qwen2.5-coder")  # case-insensitive


def test_group_of_classifies_four_buckets():
    assert _group_of({"is_local": True, "id": "x"}) == "LOCAL"
    assert _group_of({"id": "auto-best", "is_free": True}) == "COMBOS"
    assert _group_of({"id": "p/m", "is_free": True}) == "FREE"
    assert _group_of({"id": "p/m", "is_free": False}) == "PRO"


# ── Modal de modelos ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_model_modal_lists_every_model_grouped():
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert isinstance(app.screen, ModelsScreen)
        lst = app.screen.query_one(OptionList)
        # 485 modelos + 4 cabeçalhos de grupo — nada de "+N adicionais".
        assert lst.option_count == 485 + 4
        # os 4 grupos existem na lista inteira...
        prompts = option_texts(app.screen)
        for group in ("LOCAL", "COMBOS", "FREE", "PRO"):
            assert any(p.startswith(f"\u2500 {group} ") for p in prompts), f"faltou o grupo {group}"
        # ...e o que cabe na tela aparece de fato renderizado
        out = svg_text(app)
        assert "485 / 485 modelos" in out
        assert "LOCAL" in out and "COMBOS" in out and "FREE" in out


@pytest.mark.asyncio
async def test_model_modal_fuzzy_search_filters():
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+o")
        await pilot.pause()
        await pilot.press(*"qwen")
        await pilot.pause()
        screen = app.screen
        assert screen.query_one(Input).value == "qwen"
        assert len(screen._filtered) == 1
        assert screen._filtered[0]["id"] == "qwen2.5-coder:3b"


@pytest.mark.asyncio
async def test_model_modal_ranqueia_o_melhor_no_topo():
    """A busca era subsequência pura: 'opus' devolvia os combos primeiro e o
    claude-opus lá pra 11ª linha. Agora usa o fuzzy COM score do REPL."""
    agent = FakeAgent()
    agent.model_manager._models = [
        {"id": "auto/pro-supervisor", "display_id": "auto/pro-supervisor", "name": "Combo",
         "provider": "omniroute", "is_free": True, "is_local": False},
        {"id": "vincent/claude-opus-5", "display_id": "vincent/claude-opus-5", "name": "Claude Opus 5",
         "provider": "anthropic", "is_free": False, "is_local": False},
    ]
    app = VincentTUI(agent=agent)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+o")
        await pilot.pause()
        await pilot.press(*"opus")
        await pilot.pause()
        assert [m["id"] for m in app.screen._filtered][0] == "vincent/claude-opus-5"


@pytest.mark.asyncio
async def test_model_modal_avisa_quando_nada_bate():
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+o")
        await pilot.pause()
        await pilot.press(*"zzzzzzzz")
        await pilot.pause()
        assert app.screen._filtered == []
        assert "nenhum modelo" in option_texts(app.screen)[0]


@pytest.mark.asyncio
async def test_layout_estreito_esconde_o_cromo():
    """A 80 colunas, sidebar (26) + trace (30) deixavam ~20 col pro chat."""
    app = _app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        assert app.query_one("#side").has_class("-hidden")
        assert not app.query_one("#sidebar").has_class("-hidden")


def test_main_sem_tty_nao_abre_a_tui(monkeypatch, capsys):
    """--tui num pipe ficava desenhando pra sempre (84KB de ANSI e EXIT=124)."""
    monkeypatch.setattr(tui_app.sys, "stdin", type("S", (), {"isatty": staticmethod(lambda: False)})())
    monkeypatch.setattr(tui_app.VincentTUI, "run", lambda self: pytest.fail("não podia rodar"))
    tui_app.main()
    assert "TTY" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_model_modal_enter_applies_model():
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+o")
        await pilot.pause()
        await pilot.press(*"auto")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app._agent.model == "auto-best"
        assert not isinstance(app.screen, ModelsScreen)  # fechou


@pytest.mark.asyncio
async def test_model_modal_arrows_move_cursor_with_focus_on_search():
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+o")
        await pilot.pause()
        lst = app.screen.query_one(OptionList)
        start = lst.highlighted
        await pilot.press("down")
        await pilot.pause()
        # cabeçalhos de grupo sao disabled: o cursor pula pro proximo modelo
        assert lst.highlighted > start
        assert not lst.get_option_at_index(lst.highlighted).disabled
        after_down = lst.highlighted
        await pilot.press("pagedown")
        await pilot.pause()
        assert lst.highlighted > after_down
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ModelsScreen)


@pytest.mark.asyncio
async def test_slash_model_without_arg_opens_modal():
    """A reclamação original: `/model` sozinho só imprimia 'Uso: /model <id>'."""
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one("#prompt", Input).focus()
        await pilot.press(*"/model")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ModelsScreen)


# ── Marketplace ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_marketplace_modal_merges_catalog_with_installed():
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, MarketplaceScreen)
        names = {i["name"] for i in app.screen._items}
        # skills instaladas localmente (do FakePlugins) sempre entram...
        assert {"ponytail", "caveman"} <= names
        # ...e o catálogo de vincent.marketplace também, quando existe
        from vincent import marketplace as mk
        assert {i["name"] for i in mk.catalog()} <= names
        out = svg_text(app)
        assert "Marketplace de skills" in out
        assert "ativa" in out or "instalada" in out or "disponível" in out


@pytest.mark.asyncio
async def test_marketplace_degrades_without_module(monkeypatch):
    """Sem `vincent.marketplace` a TUI avisa e lista só o instalado — não crasha."""
    import vincent
    monkeypatch.delattr(vincent, "marketplace", raising=False)
    monkeypatch.setitem(sys.modules, "vincent.marketplace", None)

    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, MarketplaceScreen)
        assert "indisponível" in app.screen._warning
        names = {i["name"] for i in app.screen._items}
        assert {"ponytail", "caveman"} <= names          # instaladas continuam
        assert "indisponível" in svg_text(app)


@pytest.mark.asyncio
async def test_marketplace_enter_triggers_remove_for_installed():
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.press(*"ponytail")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, MarketplaceScreen)
        body = " ".join(m.raw for m in app.query("ChatMessage"))
        assert "Removendo" in body and "ponytail" in body


# ── Permission prompt (o ponto delicado: worker thread → UI) ──────────────────
@pytest.mark.asyncio
async def test_permission_callback_from_worker_thread_says_yes():
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        result = {}

        def worker():  # simula a thread do agentic_run
            result["ok"] = app._agent.permission_callback("run_bash", {"command": "rm -rf /tmp/x"})

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        for _ in range(50):  # espera o modal montar
            await pilot.pause()
            if isinstance(app.screen, PermissionScreen):
                break
        assert isinstance(app.screen, PermissionScreen)
        out = svg_text(app)
        assert "run_bash" in out and "rm -rf /tmp/x" in out
        await pilot.press("s")
        for _ in range(50):
            await pilot.pause()
            if not t.is_alive():
                break
        t.join(timeout=5)
        assert result["ok"] is True


@pytest.mark.asyncio
async def test_permission_modal_mostra_diff_da_edicao(tmp_path):
    """Edição pendente aparece como diff (verde/vermelho + nº de linha) no modal."""
    alvo = tmp_path / "modulo.py"
    alvo.write_text("def alfa():\n    return 1\n", encoding="utf-8")
    args = {"path": str(alvo), "search_block": "    return 1", "replace_block": "    return 42"}

    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(PermissionScreen("apply_diff", args))
        for _ in range(50):
            await pilot.pause()
            if isinstance(app.screen, PermissionScreen):
                break
        out = svg_text(app)
        assert "+1 −1" in out
        assert "return 42" in out and "return 1" in out
        assert "@@" in out
        await pilot.press("n")


@pytest.mark.asyncio
async def test_trace_panel_colore_linhas_de_diff():
    from vincent.tui_app import TracePanel, _DIFF_STYLES

    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        trace = app.query_one(TracePanel)
        trace.step("+     6 │     return 42")
        trace.step("-     6 │     return 1")
        await pilot.pause()
        out = svg_text(app)
        assert "return 42" in out
        assert set(_DIFF_STYLES) == {"◆ ", "@@", "+ ", "- ", "· "}


@pytest.mark.asyncio
async def test_permission_callback_deny_and_always():
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        async def ask(key):
            box = {}
            t = threading.Thread(
                target=lambda: box.update(ok=app._agent.permission_callback("apply_diff", {"path": "a.py"})),
                daemon=True,
            )
            t.start()
            for _ in range(50):
                await pilot.pause()
                if isinstance(app.screen, PermissionScreen):
                    break
            await pilot.press(key)
            for _ in range(50):
                await pilot.pause()
                if not t.is_alive():
                    break
            t.join(timeout=5)
            return box.get("ok")

        assert await ask("n") is False
        assert app._agent.autoedit is True  # não mexeu
        app._agent.autoedit = False
        assert await ask("a") is True
        assert app._agent.autoedit is True  # "sempre" liga o autoedit


def test_permission_callback_without_running_app_denies():
    """Sem UI viva o callback nega em vez de explodir (degrada sem TTY)."""
    app = _app()
    assert app._permission_callback("run_bash", {"command": "ls"}) is False


# ── Slash commands novos ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_slash_effort_autoedit_and_reload():
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        app._handle_slash("/effort high")
        await pilot.pause()
        assert app._agent.model_manager.effort == "high"

        app._handle_slash("/autoedit off")
        await pilot.pause()
        assert app._agent.autoedit is False
        assert "autoedit off" in svg_text(app)

        before = app._agent.plugins.scans
        app._handle_slash("/reload-plugins")
        await pilot.pause()
        assert app._agent.plugins.scans == before + 1
        body = " ".join(m.raw for m in app.query("ChatMessage"))
        assert "Recarregado" in body


@pytest.mark.asyncio
async def test_status_bar_shows_effort_and_autoedit_chips():
    app = _app()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        out = svg_text(app)
        assert "effort" in out and "autoedit" in out


# ── Palette de comandos ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_command_palette_lists_vincent_commands():
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        titles = {c.title for c in app.get_system_commands(app.screen)}
        assert {"Modelos", "Marketplace", "Recarregar plugins", "Effort: high",
                "Autoedit: alternar", "Limpar conversa"} <= titles
        await pilot.press("ctrl+p")
        await pilot.pause()
        await pilot.pause()
        assert "Palette" in app.screen.__class__.__name__ or "Command" in app.screen.__class__.__name__
