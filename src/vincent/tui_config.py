"""
Vincent CLI 4.0 — Painel de Configuração Interativo (curses, stdlib puro).
Navegação por setas: cofre de chaves e seleção de modelo ativo.
"""

import curses
from .auth import VincentAuth, SUPPORTED_PROVIDERS
from .models import ModelManager


def _masked_input(win, y: int, x: int, prompt: str, width: int = 50):
    """Lê uma linha com eco mascarado (*), sem sair do modo curses."""
    curses.echo(False)
    curses.curs_set(1)
    win.move(y, 0)
    win.clrtoeol()
    win.addstr(y, x, prompt)
    win.refresh()

    buf = []
    px = x + len(prompt)
    while True:
        ch = win.getch(y, min(px + len(buf), win.getmaxyx()[1] - 1))
        if ch in (curses.KEY_ENTER, 10, 13):
            break
        if ch == 27:  # ESC cancela
            curses.curs_set(0)
            return None
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            if buf:
                buf.pop()
                win.addstr(y, px + len(buf), " ")
        elif 32 <= ch <= 126 and len(buf) < width:
            buf.append(chr(ch))
            win.addstr(y, px + len(buf) - 1, "*")
        win.refresh()

    curses.curs_set(0)
    return "".join(buf) if buf else None


def _run(stdscr, initial_model: str = ""):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_GREEN, -1)
    curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_CYAN)

    auth = VincentAuth()
    model_manager = ModelManager()
    providers = list(SUPPORTED_PROVIDERS.items())
    models_cache = []

    section, idx = "providers", 0
    chosen_model = None

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        title = "VINCENT — PAINEL DE CONFIGURAÇÃO"
        stdscr.addstr(0, max(0, (w - len(title)) // 2), title, curses.color_pair(2) | curses.A_BOLD)
        stdscr.addstr(2, 2, "↑/↓ navega · Enter seleciona · Tab troca seção (chaves/modelo) · Esc sai",
                      curses.color_pair(1))

        if section == "providers":
            stdscr.addstr(4, 2, "COFRE DE CHAVES (~/.vincent/credentials.json, chmod 0600)", curses.A_BOLD)
            for i, (key, label) in enumerate(providers):
                y = 6 + i
                if y >= h - 3:
                    break
                configured = bool(auth.get_key(key))
                mark = "✓" if configured else "○"
                line = f"{mark} {key:<12} {label}"[:max(1, w - 6)]
                attr = curses.color_pair(4) if i == idx else (curses.color_pair(3) if configured else 0)
                stdscr.addstr(y, 4, line, attr)
        else:
            if not models_cache:
                model_manager.sync_catalogs()
                models_cache = model_manager.get_all_models()
            stdscr.addstr(4, 2, f"MODELO ATIVO (atual: {initial_model})", curses.A_BOLD)
            for i, m in enumerate(models_cache):
                y = 6 + i
                if y >= h - 3:
                    break
                attr = curses.color_pair(4) if i == idx else 0
                stdscr.addstr(y, 4, m["display_id"][:max(1, w - 6)], attr)

        stdscr.refresh()
        ch = stdscr.getch()
        items = providers if section == "providers" else models_cache
        if not items:
            items = [None]

        if ch == curses.KEY_UP and idx > 0:
            idx -= 1
        elif ch == curses.KEY_DOWN and idx < len(items) - 1:
            idx += 1
        elif ch == 9:  # Tab
            section = "models" if section == "providers" else "providers"
            idx = 0
        elif ch in (ord("q"), 27):
            break
        elif ch in (curses.KEY_ENTER, 10, 13):
            if section == "providers" and providers:
                key, _label = providers[idx]
                secret = _masked_input(stdscr, h - 2, 2, f"Chave para {key} (Esc cancela): ")
                if secret:
                    auth.set_key(key, secret)
            elif section == "models" and models_cache:
                chosen_model = models_cache[idx]["display_id"]
                break

    return chosen_model


def run_config_tui(current_model: str = "") -> str:
    """Abre o painel visual. Retorna o display_id do modelo escolhido, ou string vazia."""
    result = curses.wrapper(_run, current_model)
    return result or ""
