"""
Vincent CLI 4.0 — Ponytail Real-Time Telemetry & Statusline HUD (DietrichGebert/ponytail).
Provides real-time model indicators, hardware connection link, latency tracking,
session token meters, memory and system load statistics.
"""

import time
import os
import psutil
from datetime import timedelta
from .ui import (
    CYAN_NEON, MAGENTA_NEON, GREEN_MATRIX, AMBER_WARN, RED_ALERT,
    PURPLE_GLOW, GRAY_MUTED, GRAY_LIGHT, CLR_BOLD, CLR_RST
)

class PonytailTelemetry:
    """Monitor de telemetria em tempo real para o Vincent CLI."""
    
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
        Gera uma statusline futurista compacta estilo Ponytail.
        """
        # Badge de Modelo
        tier_tag = f"{GREEN_MATRIX}[ZERO-KEY] 🆓{CLR_RST}" if is_free else f"{PURPLE_GLOW}[PRO] ⚡{CLR_RST}"
        model_badge = f"{CYAN_NEON}◈ {current_model}{CLR_RST} {tier_tag}"

        # Status de Hardware
        hw_color = GREEN_MATRIX if hw_count > 0 else GRAY_MUTED
        hw_badge = f"{hw_color}⬢ HW: {hw_count}{CLR_RST}"

        # Gateways
        omni_badge = f"{GREEN_MATRIX}● OmniRoute{CLR_RST}" if omniroute_ok else f"{RED_ALERT}○ OmniRoute{CLR_RST}"
        ollama_badge = f"{GREEN_MATRIX}● Ollama{CLR_RST}" if ollama_ok else f"{RED_ALERT}○ Ollama{CLR_RST}"

        # Caveman
        caveman_badge = f"{AMBER_WARN}⚡ Caveman:{caveman_mode}{CLR_RST}" if caveman_mode != "off" else f"{GRAY_MUTED}Caveman:off{CLR_RST}"

        # Latência
        lat_badge = f"{CYAN_NEON}⏱ {self.last_latency:.2f}s{CLR_RST}" if self.last_latency > 0 else f"{GRAY_MUTED}⏱ --{CLR_RST}"

        line = f" {model_badge} {GRAY_MUTED}│{CLR_RST} {hw_badge} {GRAY_MUTED}│{CLR_RST} {omni_badge} {ollama_badge} {GRAY_MUTED}│{CLR_RST} {caveman_badge} {GRAY_MUTED}│{CLR_RST} {lat_badge}"
        return line

    def get_summary_cards(self, current_model: str, caveman_stats: dict) -> list[tuple[str, str]]:
        sys_info = self.get_system_stats()
        return [
            ("MODELO ATUAL", f"{CYAN_NEON}{current_model}{CLR_RST}"),
            ("CONSULTAS", f"{self.total_queries} (Média: {self.avg_latency:.2f}s | Última: {self.last_latency:.2f}s)"),
            ("TOKENS ECONOMIZADOS", f"{GREEN_MATRIX}+{caveman_stats.get('total_tokens_saved', 0)} tok{CLR_RST} (Modo: {caveman_stats.get('mode', 'off')})"),
            ("SISTEMA / RECURSOS", f"CPU: {sys_info['cpu_pct']}% | RAM: {sys_info['mem_mb']}MB ({sys_info['mem_pct']}%)"),
            ("UPTIME DA SESSÃO", f"{self.session_uptime}")
        ]
