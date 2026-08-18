"""
Vincent Agent — Núcleo de Inteligência Unificada ESP32 & Orquestrador de LLMs.
Executa em nome do Vincent com suporte a mais de 1200 modelos via OmniRoute,
modelos locais de alta velocidade Ollama, Caveman Compression e GSD Swarm.
"""

import json
import os
import re
import threading
import time
from typing import Optional, List, Dict

from .config import DEVICES, CAPABILITIES
from .devices import DeviceRegistry, DeviceEvent
from .plugins import PluginManager
from .models import ModelManager, DEFAULT_MODEL
from .caveman import CavemanEngine
from .telemetry import PonytailTelemetry

SYSTEM = """Você é o Vincent — Inteligência Central de Hardware e Desenvolvimento.
Você orquestra sistemas embarcados ESP32, hardware de RF/IR/WiFi/BLE e presta assistência técnica avançada de engenharia e software.

## Hardware sob seu controle direto:
1. TEMBED — LilyGo T-Embed CC1101 (ESP32-S3, Sub-GHz RF 433/868/915 MHz, IR TX/RX, WiFi, BLE, Display ST7789, Bruce shell).
2. ESP32DIV — ESP32-S3 DIV Kilaz v2 (3x NRF24L01 2.4GHz, Sub-GHz CC1101, Display ILI9341 Touch, SD Card, PCF8574).

## Protocolo de Comandos de Hardware:
Para interagir com as placas conectadas, emita exatamente:
  CMD:TEMBED: <comando>
  CMD:ESP32DIV: <comando>
  CMD:TODOS: <comando>

## Regras de Atuação:
- Você é Vincent: assertivo, técnico, direto, inteligente e futurista.
- Responda sempre em Português do Brasil de forma clara e profissional.
- Explique brevemente o raciocínio técnico antes de emitir qualquer comando CMD.
- Capaz de resolver problemas de código, firmwares, redes e arquitetura distribuída.
"""

class VincentAgent:
    def __init__(self, registry: DeviceRegistry, emit_fn=None, model: str = DEFAULT_MODEL):
        self.registry = registry
        self.emit = emit_fn or (lambda e, d: None)
        self.model = model
        self._history: List[Dict] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        # Módulos Integrados
        self.model_manager = ModelManager()
        self.caveman = CavemanEngine(mode="off")
        self.telemetry = PonytailTelemetry()
        self.plugins = PluginManager()
        
        # Pré-sincroniza catálogos
        self.model_manager.sync_catalogs()

    def set_model(self, new_model: str):
        """Altera o modelo neural de IA ativo."""
        self.model = new_model
        print(f"[VINCENT] Modelo neural sintonizado para: {self.model}", flush=True)

    def set_caveman_mode(self, mode: str) -> bool:
        return self.caveman.set_mode(mode)

    def ask(self, question: str, model_override: str | None = None) -> str:
        """Processa pergunta ou comando com compressão contextual e telemetria."""
        target_m = model_override or self.model
        
        # 1. Comprime prompt se Caveman estiver ativo
        processed_prompt, tokens_saved = self.caveman.compress_prompt(question)
        
        # 2. Injeta estado dos hardwares conectados de forma limpa
        state = self._device_state()
        user_content = f"[{state}]\nPergunta: {processed_prompt}"
        
        # Mantém histórico recente e enxuto (últimos 6 turnos)
        if len(self._history) >= 6:
            self._history = self._history[-5:]

        messages_to_send = self._history + [{"role": "user", "content": user_content}]

        # 3. Executa inferência via cascata de modelos
        reply, used_model, latency = self.model_manager.execute_inference(
            messages_to_send,
            target_model=target_m,
            system_prompt=SYSTEM + self.plugins.system_prompt_addon()
        )

        # 4. Registra na telemetria
        in_toks = CavemanEngine.estimate_tokens(user_content)
        out_toks = CavemanEngine.estimate_tokens(reply or "")
        self.telemetry.record_query(latency, in_toks, out_toks)

        if reply:
            self._history.append({"role": "user", "content": processed_prompt})
            self._history.append({"role": "assistant", "content": reply})
            # Executa comandos de hardware automáticos se presentes
            self._execute_commands(reply)
            return reply
        
        return "[VINCENT] Resposta vazia ou falha de comunicação com os nós neurais."

    def _execute_commands(self, analysis: str):
        """Executa comandos CMD: identificados no output se o hardware estiver conectado."""
        for line in analysis.splitlines():
            m = re.match(r"CMD:([A-Z0-9_\-]+):\s*(.+)", line.strip())
            if not m:
                continue
            dev_id, cmd = m.group(1), m.group(2).strip()
            targets = [d.id for d in self.registry.all() if d.online] if dev_id == "TODOS" else [dev_id]
            for tid in targets:
                dev = self.registry.get(tid)
                if not dev or not dev.online:
                    continue
                print(f"[{tid}] ← {cmd}", flush=True)
                wait = 4.0 if any(w in cmd for w in ["wifi", "sniffer", "listen"]) else 2.0
                r = self.registry.send(tid, cmd, wait)
                print(f"[{tid}] → {r.get('response', '')[:120]}", flush=True)
                time.sleep(0.2)

    def _device_state(self) -> str:
        devs = self.registry.all()
        if not devs:
            return "Nenhum dispositivo físico conectado no momento."
        lines = ["Dispositivos conectados:"]
        for d in devs:
            hw = ", ".join(d.hardware[:5])
            lines.append(f"  {d.id} ({d.label}) | firmware={d.firmware_id} | hw=[{hw}] | protocolo={d.protocol or 'NENHUM'}")
        return "\n".join(lines)
