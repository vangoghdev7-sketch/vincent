"""
Vincent Agent — Núcleo de Inteligência Unificada ESP32 & Orquestrador de LLMs.
Executa em nome do Vincent com suporte a mais de 1200 rotas neurais próprias,
modelos locais de alta velocidade, Caveman Compression, GSD Swarm e Agentic Loop com Tool Calling.
"""

import json
import os
import re
import threading
import time
from typing import Optional, List, Dict, Any, Callable

from .config import DEVICES, CAPABILITIES
from .devices import DeviceRegistry, DeviceEvent
from .plugins import PluginManager
from .models import ModelManager, DEFAULT_MODEL
from .caveman import CavemanEngine
from .telemetry import PonytailTelemetry
from .agent_tools import execute_agent_tool, TOOL_DEFINITIONS

SYSTEM_BASE = """Você é o Vincent — Inteligência Central de Hardware, Software e Engenharia de Sistemas.
Você possui capacidades autônomas de investigação de código, execução de ferramentas e controle de hardware ESP32.

## Ferramentas de Workspace Disponíveis:
Quando precisar inspecionar arquivos, procurar trechos de código ou validar alterações, você pode emitir uma chamada de ferramenta no formato JSON exato:

```tool_call
{
  "tool": "<nome_da_ferramenta>",
  "args": { ... }
}
```

Ferramentas suportadas:
1. `list_dir`: {"path": ".", "max_depth": 2}
2. `read_file`: {"path": "caminho/do/arquivo", "start_line": 1, "end_line": 50}
3. `grep_search`: {"pattern": "termo_de_busca", "path": ".", "is_regex": false}
4. `run_bash`: {"command": "comando_de_terminal"}
5. `apply_diff`: {"path": "arquivo", "search_block": "código_antigo", "replace_block": "código_novo"}

## Hardware sob seu controle direto:
1. TEMBED — LilyGo T-Embed CC1101 (ESP32-S3, Sub-GHz RF 433/868/915 MHz, IR TX/RX, WiFi, BLE, Display ST7789, Bruce shell).
2. ESP32DIV — ESP32-S3 DIV Kilaz v2 (3x NRF24L01 2.4GHz, Sub-GHz CC1101, Display ILI9341 Touch, SD Card, PCF8574).
Para interagir com as placas, emita: CMD:TEMBED: <comando> ou CMD:ESP32DIV: <comando>.

## Regras de Atuação:
- Seja assertivo, técnico, objetivo, direto e inteligente.
- Sempre que solicitado a resolver um bug ou investigar o código, use `grep_search` e `read_file` antes de propor a solução.
- Ao propor correções em arquivos existentes, use `apply_diff` com search_block exato para modificações cirúrgicas.
- Responda em Português do Brasil.
"""


class VincentAgent:
    def __init__(self, registry: DeviceRegistry, emit_fn=None, model: str = DEFAULT_MODEL):
        self.registry = registry
        self.emit = emit_fn or (lambda e, d: None)
        self._history: List[Dict] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Módulos Integrados
        self.model_manager = ModelManager()
        self.caveman = CavemanEngine(mode="off")
        self.telemetry = PonytailTelemetry()
        self.plugins = PluginManager()

        # Sincronização inicial de catálogo
        self.model_manager.sync_catalogs()
        self.model_manager.get_all_models()
        self.model = self.model_manager.resolve(model)

    @property
    def display_model(self) -> str:
        """Nome do modelo ativo mascarado sob a marca Vincent."""
        return self.model_manager.mask(self.model)

    def set_model(self, new_model: str):
        self.model = self.model_manager.resolve(new_model)

    def set_caveman_mode(self, mode: str) -> bool:
        return self.caveman.set_mode(mode)

    def ask(self, question: str, model_override: str | None = None) -> str:
        """Execução direta padrão com compressão Caveman e comandos de hardware."""
        target_m = model_override or self.model
        processed_prompt, _ = self.caveman.compress_prompt(question)
        
        state = self._device_state()
        user_content = f"[{state}]\nPergunta: {processed_prompt}"
        
        if len(self._history) >= 6:
            self._history = self._history[-5:]

        messages_to_send = self._history + [{"role": "user", "content": user_content}]

        reply, used_model, latency = self.model_manager.execute_inference(
            messages_to_send,
            target_model=target_m,
            system_prompt=SYSTEM_BASE + self.plugins.system_prompt_addon()
        )

        in_toks = CavemanEngine.estimate_tokens(user_content)
        out_toks = CavemanEngine.estimate_tokens(reply or "")
        self.telemetry.record_query(latency, in_toks, out_toks)

        if reply:
            self._history.append({"role": "user", "content": processed_prompt})
            self._history.append({"role": "assistant", "content": reply})
            self._execute_commands(reply)
            return reply
        
        return "[VINCENT] Resposta vazia ou falha de comunicação com os nós neurais."

    def agentic_run(self, task: str, on_step_callback: Optional[Callable[[str], None]] = None, max_turns: int = 6) -> str:
        """
        Agentic Loop com Function/Tool Calling autônomo e auto-cura.
        Investiga o código, executa ferramentas, inspeciona resultados e sintetiza a solução.
        """
        target_m = self.model
        processed_task, _ = self.caveman.compress_prompt(task)
        state = self._device_state()

        turn_messages: List[Dict[str, str]] = [
            {"role": "user", "content": f"[{state}]\nTarefa Agênica: {processed_task}"}
        ]

        total_latency = 0.0
        final_response = ""

        for turn in range(max_turns):
            if on_step_callback:
                on_step_callback(f"Raciocinando passo {turn + 1}/{max_turns}...")

            reply, used_model, lat = self.model_manager.execute_inference(
                turn_messages,
                target_model=target_m,
                system_prompt=SYSTEM_BASE + self.plugins.system_prompt_addon()
            )
            total_latency += lat

            if not reply:
                break

            # Verifica se o modelo emitiu uma chamada de ferramenta
            tool_call = self._extract_tool_call(reply)
            if not tool_call:
                # Não há mais ferramentas a chamar: loop concluído
                final_response = reply
                break

            tool_name = tool_call.get("tool", "")
            tool_args = tool_call.get("args", {})

            if on_step_callback:
                on_step_callback(f"Executando ferramenta: {tool_name}...")

            # Executa ferramenta real no workspace
            tool_result = execute_agent_tool(tool_name, tool_args)

            # Auto-cura: Detecta erros de execução e injeta alerta no contexto
            is_error = bool(tool_result.get("error")) or (tool_result.get("exit_code", 0) != 0)
            prefix = "[AUTO-CURA: ERRO NA FERRAMENTA]" if is_error else "[RESULTADO DA FERRAMENTA]"

            turn_messages.append({"role": "assistant", "content": reply})
            turn_messages.append({
                "role": "user",
                "content": f"{prefix} {tool_name}:\n{json.dumps(tool_result, ensure_ascii=False, indent=2)}\n\nAnalise o resultado acima e continue sua investigação ou aplique a correção necessária."
            })
            time.sleep(0.1)

        in_toks = CavemanEngine.estimate_tokens(processed_task)
        out_toks = CavemanEngine.estimate_tokens(final_response or "")
        self.telemetry.record_query(total_latency, in_toks, out_toks)

        if final_response:
            self._history.append({"role": "user", "content": processed_task})
            self._history.append({"role": "assistant", "content": final_response})
            self._execute_commands(final_response)
            return final_response

        return reply or "[VINCENT AGENTIC] Limite de passos atingido sem conclusão."

    def _extract_tool_call(self, text: str) -> Optional[Dict[str, Any]]:
        """Extrai bloco tool_call em JSON da resposta do modelo."""
        # 1. Procura por bloco ```tool_call ... ```
        m = re.search(r"```(?:tool_call|json)?\s*(\{\s*\"tool\".*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass

        # 2. Procura por JSON solto contendo chave "tool"
        m = re.search(r"(\{\s*\"tool\"\s*:\s*\"[^\"]+\".*?\})", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass

        return None

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
                wait = 4.0 if any(w in cmd for w in ["wifi", "sniffer", "listen"]) else 2.0
                self.registry.send(tid, cmd, wait)
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
