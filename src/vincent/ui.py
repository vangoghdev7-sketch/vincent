"""
Vincent CLI 4.0 — UI/UX Pro Max Design System
Van Gogh Starry Night Neural HUD — cobalt blue and chrome yellow TrueColor ANSI,
glowing borders, dynamic neural spinners, syntax highlighting and responsive layouts.
"""

import os
import sys
import time
import threading
import itertools
import shutil
import re

# ─── TrueColor & 256 ANSI Palette ─────────────────────────────────────────────
CLR_RST = "\033[0m"
CLR_BOLD = "\033[1m"
CLR_DIM = "\033[2m"
CLR_ITALIC = "\033[3m"
CLR_UNDERLINE = "\033[4m"

# Van Gogh Starry Night Palette (UI/UX Pro Max)
CYAN_NEON    = "\033[38;5;33m"   # #0087ff - Starry Night Cobalt Blue - Primary HUD & Accent
CYAN_DARK    = "\033[38;5;25m"   # #005fd7 - Deep Prussian Blue - Secondary
MAGENTA_NEON = "\033[38;5;220m"  # #ffd700 - Chrome Yellow - Highlights & Prompts
MAGENTA_DEEP = "\033[38;5;178m"  # #d7af00 - Ochre Gold - Secondary Highlight
PURPLE_GLOW  = "\033[38;5;141m"  # #af87ff - Swirling Violet - Neural / Pro Tiers
GREEN_MATRIX = "\033[38;5;48m"   # #00ff87 - Success / Online / Free
GREEN_DARK   = "\033[38;5;28m"   # #008700 - Cypress Green - Subdued
AMBER_WARN   = "\033[38;5;214m"  # #ffaf00 - Warnings / Hardware
RED_ALERT    = "\033[38;5;196m"  # #ff0000 - Errors / Critical
ORANGE_FIRE  = "\033[38;5;208m"  # #ff8700 - Active Processes
BLUE_ELECTRIC= "\033[38;5;75m"   # #5fafff - Info / Núcleo Vincent
GRAY_LIGHT   = "\033[38;5;250m"  # #bcbcbc - Normal Text
GRAY_MUTED   = "\033[38;5;242m"  # #6c6c6c - Dim / Secondary
GRAY_DARK    = "\033[38;5;236m"  # #303030 - Dark Borders
BG_DARK_HUD  = "\033[48;5;234m"  # Background Tint

# ─── Futuristic ASCII Banner ──────────────────────────────────────────────────
BANNER = f"""
{CYAN_NEON}  ██╗   ██╗██╗███╗   ██╗ ██████╗███████╗███╗   ██╗████████╗
  ██║   ██║██║████╗  ██║██╔════╝██╔════╝████╗  ██║╚══██╔══╝
  ██║   ██║██║██╔██╗ ██║██║     █████╗  ██╔██╗ ██║   ██║   
  ╚██╗ ██╔╝██║██║╚██╗██║██║     ██╔══╝  ██║╚██╗██║   ██║   
   ╚████╔╝ ██║██║ ╚████║╚██████╗███████╗██║ ╚████║   ██║   
    ╚═══╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝╚══════╝╚═╝  ╚═══╝   ╚═╝   {CLR_RST}
  {MAGENTA_NEON}◈ V I N C E N T   O S   N E U R A L   C L I   v 4 . 0 ◈{CLR_RST}
  {GRAY_LIGHT}Motor OmniRoute • Zero-Key Free • Caveman • GSD Swarm • ESP32 Lab{CLR_RST}
  {GRAY_MUTED}Catálogo ao vivo: rode /models pra ver a contagem real conectada agora{CLR_RST}
  {GRAY_MUTED}van Gogh Edition — Starry Night HUD{CLR_RST}
"""

def get_terminal_width(default: int = 80) -> int:
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except Exception:
        return default


class NeuralSpinner:
    """Cyberpunk Animated Multi-Frame Neural Spinner."""
    def __init__(self, message="Processando inferência neural...", color=CYAN_NEON):
        self.message = message
        self.color = color
        self.stop_event = threading.Event()
        self.thread = None
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.pulse = ["◐", "◓", "◑", "◒"]
        self.is_tty = sys.stdout.isatty()

    def _spin(self):
        idx = 0
        while not self.stop_event.is_set():
            if self.is_tty:
                frame = self.frames[idx % len(self.frames)]
                pulse = self.pulse[(idx // 2) % len(self.pulse)]
                msg = f"\r{self.color}{frame}{CLR_RST} {MAGENTA_NEON}{pulse}{CLR_RST} {GRAY_LIGHT}{self.message}{CLR_RST}"
                sys.stdout.write(msg)
                sys.stdout.flush()
            idx += 1
            time.sleep(0.07)
        if self.is_tty:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

    def update_message(self, new_msg: str):
        self.message = new_msg

    def __enter__(self):
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=0.5)


def render_hud_card(title: str, items: list[tuple[str, str]], color=CYAN_NEON, border_style="rounded"):
    """
    Renderiza cartões HUD com bordas futuristas e alinhamento responsivo.
    """
    term_width = min(get_terminal_width(), 96)
    
    # Extrai o tamanho visível sem ANSI
    def strip_ansi(text: str) -> str:
        return re.sub(r'\x1b\[[0-9;]*m', '', str(text))
    
    max_len = 0
    for k, v in items:
        vis_len = len(strip_ansi(k)) + len(strip_ansi(v)) + 4
        if vis_len > max_len:
            max_len = vis_len
            
    width = max(max_len + 4, len(title) + 8, 48)
    width = min(width, term_width - 4)

    if border_style == "double":
        tl, tr, bl, br, h, v = "╔", "╗", "╚", "╝", "═", "║"
        t_open, t_close = "╡ ", " ╞"
    else:
        tl, tr, bl, br, h, v = "╭", "╮", "╰", "╯", "─", "│"
        t_open, t_close = "─[ ", " ]─"

    title_block = f"{t_open}{CLR_BOLD}{title}{CLR_RST}{color}{t_close}"
    title_vis_len = len(strip_ansi(title)) + 6
    remaining_h = max(0, width - title_vis_len - 1)

    print(f"{color}{tl}{title_block}{h * remaining_h}{tr}{CLR_RST}")
    for k, val in items:
        k_str = f"{CLR_BOLD}{k}:{CLR_RST}"
        k_vis = len(strip_ansi(k)) + 1
        val_str = str(val)
        val_vis = len(strip_ansi(val_str))
        
        spacing = width - (k_vis + val_vis + 4)
        if spacing < 1:
            spacing = 1
        print(f"{color}{v}{CLR_RST}  {k_str} {val_str}{' ' * spacing} {color}{v}{CLR_RST}")
    print(f"{color}{bl}{h * width}{br}{CLR_RST}")


def render_section_header(title: str, icon="◈", color=CYAN_NEON):
    """Renderiza um divisor de seção com estilo Neo-Tokyo."""
    term_width = min(get_terminal_width(), 90)
    line_len = max(4, term_width - len(title) - 8)
    print(f"\n{color}{icon} {CLR_BOLD}{title.upper()}{CLR_RST} {color}{'─' * line_len}{CLR_RST}")


def render_response_box(reply: str, model: str, latency: float, mode: str = "Standard", tokens_saved: int = 0):
    """Renderiza o output de IA dentro de um frame elegante com telemetria."""
    term_width = min(get_terminal_width(), 96)
    
    # Top frame
    header_title = "◈ VINCENT NEURAL OUTPUT ◈"
    top_bar = f"{GREEN_MATRIX}╭─[ {CLR_BOLD}{header_title}{CLR_RST}{GREEN_MATRIX} ]" + "─" * max(2, term_width - len(header_title) - 7) + f"╮{CLR_RST}"
    print(top_bar)
    
    # Formatação de texto com destaque de código
    lines = reply.strip().splitlines()
    in_code_block = False
    
    for line in lines:
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            print(f"{GREEN_MATRIX}│{CLR_RST} {MAGENTA_NEON}{line}{CLR_RST}")
            continue
        
        if in_code_block:
            print(f"{GREEN_MATRIX}│{CLR_RST} {CYAN_NEON}{line}{CLR_RST}")
        elif line.startswith("#"):
            print(f"{GREEN_MATRIX}│{CLR_RST} {MAGENTA_NEON}{CLR_BOLD}{line}{CLR_RST}")
        elif line.startswith("CMD:") or line.startswith("[HARDWARE]") or line.startswith("[GSD]"):
            print(f"{GREEN_MATRIX}│{CLR_RST} {AMBER_WARN}{CLR_BOLD}{line}{CLR_RST}")
        else:
            print(f"{GREEN_MATRIX}│{CLR_RST} {GRAY_LIGHT}{line}{CLR_RST}")
            
    # Bottom Telemetry Bar
    saved_str = f" | Economia: {GREEN_MATRIX}-{tokens_saved} tok{GRAY_MUTED}" if tokens_saved > 0 else ""
    meta_info = f" {GRAY_MUTED}Latência: {CYAN_NEON}{latency:.2f}s{GRAY_MUTED} | Modelo: {PURPLE_GLOW}{model}{GRAY_MUTED} | Modo: {mode}{saved_str} "
    
    # Strip ansi for bottom length calculation
    clean_meta = re.sub(r'\x1b\[[0-9;]*m', '', meta_info)
    footer_len = max(2, term_width - len(clean_meta) - 5)
    bottom_bar = f"{GREEN_MATRIX}╰─[{meta_info}{GREEN_MATRIX}]" + "─" * footer_len + f"╯{CLR_RST}\n"
    print(bottom_bar)
