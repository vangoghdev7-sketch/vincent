"""
Vincent CLI 4.0 — Ponytail Real-Time Telemetry & Statusline HUD (DietrichGebert/ponytail).
Provides real-time model indicators, hardware connection link, latency tracking,
session token meters, memory and system load statistics.
"""

import time
import os
try:
    import psutil
except ImportError:
    psutil = None
from datetime import timedelta
from .ui import (
    COBALT_BLUE, PRUSSIAN_BLUE, LEMON_YELLOW, CHROME_YELLOW, STARRY_GOLD,
    CYPRESS_GREEN, CYPRESS_DARK, VIOLET_SWIRL, ALERT_SCARLET, CANVAS_WHITE,
    SHADOW_GRAY, CLR_BOLD, CLR_RST
)
from .env_detect import PlatformEnvironment

class PonytailTelemetry:
    """Monitor de telemetria em tempo real para o Vincent CLI (Estilo Starry Night)."""
    
    def __init__(self):
        self.start_time = time.time()
        self.total_queries = 0
        self.total_latency = 0.0
        self.last_latency = 0.0
        self.tokens_in = 0
        self.tokens_out = 0

    def record_query(self, latency: float, in_tokens: int = 0, out_tokens: int = 0):
        self.total_queries += 1
        self.total_latency += latency
        self.last_latency = latency
        self.tokens_in += in_tokens
        self.tokens_out += out_tokens

    @property
    def avg_latency(self) -> float:
        return (self.total_latency / self.total_queries) if self.total_queries > 0 else 0.0

    @property
    def session_uptime(self) -> str:
        uptime_sec = int(time.time() - self.start_time)
        return str(timedelta(seconds=uptime_sec))

    @staticmethod
    def get_system_stats() -> dict:
        if psutil is None:
            return {"cpu_pct": 0, "mem_mb": 0, "mem_pct": 0}
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            mem_used_mb = int(mem.used / (1024 * 1024))
            mem_pct = mem.percent
            return {"cpu_pct": cpu, "mem_mb": mem_used_mb, "mem_pct": mem_pct}
        except Exception:
            return {"cpu_pct": 0, "mem_mb": 0, "mem_pct": 0}

    def render_statusline(self, current_model: str, is_free: bool, hw_count: int, omniroute_ok: bool, ollama_ok: bool, caveman_mode: str) -> str:
        """
        Gera uma statusline futurista compacta estilo Ponytail com paleta Starry Night.
        """
        is_mobile = PlatformEnvironment.is_mobile()

        # Badge de Modelo
        tier_tag = f"{CYPRESS_GREEN}[ZERO-KEY] 🆓{CLR_RST}" if is_free else f"{VIOLET_SWIRL}[PRO] ⚡{CLR_RST}"
        model_badge = f"{COBALT_BLUE}◈ {current_model}{CLR_RST} {tier_tag}"

        # Status de Hardware
        hw_color = CYPRESS_GREEN if hw_count > 0 else SHADOW_GRAY
        hw_badge = f"{hw_color}⬢ HW:{hw_count}{CLR_RST}"

        # Gateways Whitelabeled
        omni_badge = f"{CYPRESS_GREEN}● Galeria Cloud{CLR_RST}" if omniroute_ok else f"{ALERT_SCARLET}○ Galeria Cloud{CLR_RST}"
        ollama_badge = f"{CYPRESS_GREEN}● Atelier Local{CLR_RST}" if ollama_ok else f"{ALERT_SCARLET}○ Atelier Local{CLR_RST}"

        # Caveman
        caveman_badge = f"{STARRY_GOLD}⚡ Caveman:{caveman_mode}{CLR_RST}" if caveman_mode != "off" else f"{SHADOW_GRAY}Caveman:off{CLR_RST}"

        # Latência
        lat_badge = f"{COBALT_BLUE}⏱ {self.last_latency:.2f}s{CLR_RST}" if self.last_latency > 0 else f"{SHADOW_GRAY}⏱ --{CLR_RST}"

        if is_mobile:
            # Layout enxuto para Termux
            return f" {model_badge} {SHADOW_GRAY}│{CLR_RST} {hw_badge} {SHADOW_GRAY}│{CLR_RST} {caveman_badge} {SHADOW_GRAY}│{CLR_RST} {lat_badge}"
        else:
            return f" {model_badge} {SHADOW_GRAY}│{CLR_RST} {hw_badge} {SHADOW_GRAY}│{CLR_RST} {omni_badge} {ollama_badge} {SHADOW_GRAY}│{CLR_RST} {caveman_badge} {SHADOW_GRAY}│{CLR_RST} {lat_badge}"

    def get_summary_cards(self, current_model: str, caveman_stats: dict) -> list[tuple[str, str]]:
        sys_info = self.get_system_stats()
        caveman_stats = caveman_stats or {}
        saved_tok = caveman_stats.get('total_tokens_saved', 0)
        mode = caveman_stats.get('mode', 'off')
        
        # Barra gráfica de economia de tokens
        bar_fill = min(10, max(1, int(saved_tok / 50))) if saved_tok > 0 else 0
        eco_bar = f"{CYPRESS_GREEN}{'█' * bar_fill}{'░' * (10 - bar_fill)}{CLR_RST}" if saved_tok > 0 else f"{SHADOW_GRAY}░░░░░░░░░░{CLR_RST}"

        env_name = "📱 Termux (Android Mobile)" if PlatformEnvironment.is_mobile() else f"🖥️ Desktop / Server ({PlatformEnvironment.get_os_type()})"

        return [
            ("AMBIENTE DE EXECUÇÃO", env_name),
            ("MODELO ATIVO", f"{COBALT_BLUE}{current_model}{CLR_RST}"),
            ("CONSULTAS NEURAIS", f"{self.total_queries} (Média: {self.avg_latency:.2f}s | Última: {self.last_latency:.2f}s)"),
            ("ECONOMIA CAVEMAN", f"{eco_bar} {CYPRESS_GREEN}+{saved_tok} tokens{CLR_RST} (Modo: {mode})"),
            ("RECURSOS DO SISTEMA", f"CPU: {sys_info['cpu_pct']}% | RAM: {sys_info['mem_mb']}MB ({sys_info['mem_pct']}%)"),
            ("UPTIME DA SESSÃO", f"{self.session_uptime}")
        ]
