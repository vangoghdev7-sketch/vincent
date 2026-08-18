"""
Vincent CLI 4.0 — Van Gogh 'Starry Night' Cyber-Impressionist UI/UX System.
TrueColor ANSI palette (Cobalt Blue, Chrome Yellow, Starry Gold, Cypress Green),
Swirling 'Redemoinho' Neural Spinners, Termux/ADB Adaptive Layouts and Whitelabeled HUD.
"""

import os
import sys
import time
import threading
import itertools
import shutil
import re
from .env_detect import PlatformEnvironment

# ─── TrueColor & 256 ANSI 'Starry Night' Palette ──────────────────────────────
CLR_RST = "\033[0m"
CLR_BOLD = "\033[1m"
CLR_DIM = "\033[2m"
CLR_ITALIC = "\033[3m"
CLR_UNDERLINE = "\033[4m"

# Paleta Noite Estrelada (Van Gogh Post-Impressionism + Cyber-HUD)
COBALT_BLUE   = "\033[38;5;33m"   # #0087ff - Azul Cobalto da Noite Estrelada
PRUSSIAN_BLUE = "\033[38;5;25m"   # #005fd7 - Azul Noturno Profundo
LEMON_YELLOW  = "\033[38;5;226m"  # #ffff00 - Amarelo Limão das Estrelas
CHROME_YELLOW = "\033[38;5;220m"  # #ffd700 - Amarelo Cromo dos Astros
STARRY_GOLD   = "\033[38;5;214m"  # #ffaf00 - Dourado das Pinceladas
OCHRE_ORANGE  = "\033[38;5;208m"  # #ff8700 - Laranja Ocre
CYPRESS_GREEN = "\033[38;5;48m"   # #00ff87 - Verde Cipreste Luminoso
CYPRESS_DARK  = "\033[38;5;29m"   # #00875f - Verde Floresta Profundo
VIOLET_SWIRL  = "\033[38;5;141m"  # #af87ff - Violeta dos Redemoinhos Celestes
ALERT_SCARLET = "\033[38;5;196m"  # #ff0000 - Escarlate de Alerta
CANVAS_WHITE  = "\033[38;5;254m"  # #e4e4e4 - Branco Tela / Pérola
SHADOW_GRAY   = "\033[38;5;242m"  # #6c6c6c - Sombra Cinza / Detalhes
NIGHT_BG      = "\033[48;5;234m"  # #1c1c1c - Fundo Noite

# Aliases de compatibilidade visual
CYAN_NEON    = COBALT_BLUE
CYAN_DARK    = PRUSSIAN_BLUE
MAGENTA_NEON = CHROME_YELLOW
MAGENTA_DEEP = STARRY_GOLD
PURPLE_GLOW  = VIOLET_SWIRL
GREEN_MATRIX = CYPRESS_GREEN
GREEN_DARK   = CYPRESS_DARK
AMBER_WARN   = STARRY_GOLD
RED_ALERT    = ALERT_SCARLET
ORANGE_FIRE  = OCHRE_ORANGE
BLUE_ELECTRIC= COBALT_BLUE
GRAY_LIGHT   = CANVAS_WHITE
GRAY_MUTED   = SHADOW_GRAY
GRAY_DARK    = "\033[38;5;236m"

# ─── Van Gogh Starry Night ASCII Masterpiece Banner ───────────────────────────
BANNER = f"""
{COBALT_BLUE}   ★    .   ☆  *   .   ★    .   *   ☆  .   ★    .   *   ☆  .   ★{CLR_RST}
{COBALT_BLUE}  ██╗   ██╗██╗███╗   ██╗ ██████╗███████╗███╗   ██╗████████╗{CLR_RST}
{PRUSSIAN_BLUE}  ██║   ██║██║████╗  ██║██╔════╝██╔════╝████╗  ██║╚══██╔══╝{CLR_RST}
{COBALT_BLUE}  ██║   ██║██║██╔██╗ ██║██║     █████╗  ██╔██╗ ██║   ██║   {CLR_RST}
{PRUSSIAN_BLUE}  ╚██╗ ██╔╝██║██║╚██╗██║██║     ██╔══╝  ██║╚██╗██║   ██║   {CLR_RST}
{COBALT_BLUE}   ╚████╔╝ ██║██║ ╚████║╚██████╗███████╗██║ ╚████║   ██║   {CLR_RST}
{PRUSSIAN_BLUE}    ╚═══╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝╚══════╝╚═╝  ╚═══╝   ╚═╝   {CLR_RST}
  {CHROME_YELLOW}◈ V I N C E N T   O S   •   S T A R R Y   N I G H T   E D I T I O N ◈{CLR_RST}
  {CANVAS_WHITE}Atelier Neural Autônomo • 1200+ Pinceladas de Modelos • Laboratório ESP32{CLR_RST}
  {SHADOW_GRAY}Pós-Impressionismo Cibernético • Caveman • Ponytail • GSD Swarm • Termux Ready{CLR_RST}
"""

def get_terminal_width(default: int = 80) -> int:
    cols, _ = PlatformEnvironment.get_terminal_dimensions()
    return cols


class NeuralSpinner:
    """
    Animated Swirling Brushstroke Neural Spinner ('Redemoinho de Van Gogh').
    Simula redemoinhos celestes e estrelas pulsantes com alta fluidez.
    """
    def __init__(self, message="Pintando inferência neural...", color=COBALT_BLUE):
        self.message = message
        self.color = color
        self.stop_event = threading.Event()
        self.thread = None
        # Redemoinhos e pinceladas em espiral
        self.swirl_frames = ["໑", "๑", "༄", "≋", "✵", "✧", "✦", "✺", "🌀", "✶"]
        self.star_pulse   = ["★", "✦", "✧", "☆", "✹", "✺"]
        self.is_tty = sys.stdout.isatty()
        self.is_mobile = PlatformEnvironment.is_mobile()

    def _spin(self):
        idx = 0
        while not self.stop_event.is_set():
            if self.is_tty:
                swirl = self.swirl_frames[idx % len(self.swirl_frames)]
                star  = self.star_pulse[(idx // 2) % len(self.star_pulse)]
                
                # Adaptação para telas estreitas de celular (Termux)
                msg_display = self.message
                if self.is_mobile and len(msg_display) > 28:
                    msg_display = msg_display[:25] + "..."

                line = f"\r{self.color}{swirl}{CLR_RST} {LEMON_YELLOW}{star}{CLR_RST} {CANVAS_WHITE}{msg_display}{CLR_RST}"
                sys.stdout.write(line)
                sys.stdout.flush()
            idx += 1
            time.sleep(0.06)
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
            self.thread.join(timeout=0.4)


def strip_ansi(text: str) -> str:
    """Remove códigos de escape ANSI para cálculo exato de largura de colunas."""
    return re.sub(r'\x1b\[[0-9;]*m', '', str(text))


def render_hud_card(title: str, items: list[tuple[str, str]], color=COBALT_BLUE, border_style="rounded"):
    """
    Renderiza cartões HUD com bordas arredondadas e adaptação dinâmica para Termux/Desktop.
    """
    term_width = get_terminal_width()
    is_mobile = PlatformEnvironment.is_mobile() or term_width < 60
    
    # Calcula largura ideal
    max_len = 0
    for k, v in items:
        vis_len = len(strip_ansi(k)) + len(strip_ansi(v)) + 4
        if vis_len > max_len:
            max_len = vis_len
            
    min_width = 36 if is_mobile else 50
    max_width = min(term_width - 2, 94)
    width = max(max_len + 4, len(title) + 8, min_width)
    width = min(width, max_width)

    tl, tr, bl, br, h, v = ("╭", "╮", "╰", "╯", "─", "│") if border_style == "rounded" else ("╔", "╗", "╚", "╝", "═", "║")
    t_open, t_close = "─[ ", " ]─"

    title_block = f"{t_open}{LEMON_YELLOW}{CLR_BOLD}{title}{CLR_RST}{color}{t_close}"
    title_vis_len = len(strip_ansi(title)) + 6
    remaining_h = max(0, width - title_vis_len - 1)

    print(f"{color}{tl}{title_block}{h * remaining_h}{tr}{CLR_RST}")
    for k, val in items:
        k_str = f"{CHROME_YELLOW}{CLR_BOLD}{k}:{CLR_RST}"
        k_vis = len(strip_ansi(k)) + 1
        val_str = str(val)
        val_vis = len(strip_ansi(val_str))
        
        spacing = width - (k_vis + val_vis + 4)
        if spacing < 1:
            spacing = 1
            # Se for tela estreita e ultrapassar, quebra suavemente
            if is_mobile and (k_vis + val_vis + 4) > width:
                val_str = val_str[:max(10, width - k_vis - 7)] + ".."
                val_vis = len(strip_ansi(val_str))
                spacing = max(1, width - (k_vis + val_vis + 4))

        print(f"{color}{v}{CLR_RST}  {k_str} {val_str}{' ' * spacing} {color}{v}{CLR_RST}")
    print(f"{color}{bl}{h * width}{br}{CLR_RST}")


def render_section_header(title: str, icon="◈", color=COBALT_BLUE):
    """Renderiza um divisor de seção pós-impressionista."""
    term_width = min(get_terminal_width(), 90)
    line_len = max(3, term_width - len(title) - 8)
    print(f"\n{color}{icon} {CHROME_YELLOW}{CLR_BOLD}{title.upper()}{CLR_RST} {color}{'─' * line_len}{CLR_RST}")


def render_response_box(reply: str, model: str, latency: float, mode: str = "Standard", tokens_saved: int = 0):
    """Renderiza o output de IA dentro de um frame 'Noite Estrelada' com telemetria."""
    term_width = min(get_terminal_width(), 94)
    is_mobile = PlatformEnvironment.is_mobile() or term_width < 60
    
    header_title = "◈ OBRA NEURAL VINCENT ◈"
    top_bar = f"{CYPRESS_GREEN}╭─[ {LEMON_YELLOW}{CLR_BOLD}{header_title}{CLR_RST}{CYPRESS_GREEN} ]" + "─" * max(2, term_width - len(header_title) - 7) + f"╮{CLR_RST}"
    print(top_bar)
    
    lines = reply.strip().splitlines()
    in_code_block = False
    
    for line in lines:
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            print(f"{CYPRESS_GREEN}│{CLR_RST} {CHROME_YELLOW}{line}{CLR_RST}")
            continue
        
        if in_code_block:
            print(f"{CYPRESS_GREEN}│{CLR_RST} {COBALT_BLUE}{line}{CLR_RST}")
        elif line.startswith("#"):
            print(f"{CYPRESS_GREEN}│{CLR_RST} {LEMON_YELLOW}{CLR_BOLD}{line}{CLR_RST}")
        elif line.startswith("CMD:") or line.startswith("[HARDWARE]") or line.startswith("[GSD]"):
            print(f"{CYPRESS_GREEN}│{CLR_RST} {STARRY_GOLD}{CLR_BOLD}{line}{CLR_RST}")
        else:
            print(f"{CYPRESS_GREEN}│{CLR_RST} {CANVAS_WHITE}{line}{CLR_RST}")
            
    # Rodapé com telemetria Ponytail
    saved_str = f" | {CYPRESS_GREEN}-{tokens_saved} tok{SHADOW_GRAY}" if tokens_saved > 0 else ""
    meta_info = f" {SHADOW_GRAY}⏱ {COBALT_BLUE}{latency:.2f}s{SHADOW_GRAY} │ 🎨 {VIOLET_SWIRL}{model}{SHADOW_GRAY} │ ⚡ {mode}{saved_str} "
    
    clean_meta = strip_ansi(meta_info)
    footer_len = max(2, term_width - len(clean_meta) - 5)
    bottom_bar = f"{CYPRESS_GREEN}╰─[{meta_info}{CYPRESS_GREEN}]" + "─" * footer_len + f"╯{CLR_RST}\n"
    print(bottom_bar)
