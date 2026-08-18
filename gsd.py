"""
Vincent CLI 4.0 — GSD Multi-Agent Swarm Orchestrator (open-gsd/gsd-core).
Autonomous task breakdown: Phases, Waves, Multi-Agent Swarm dispatch,
Verification, and Hardware/Software execution.
"""

from typing import List, Dict, Tuple
from .ui import (
    CYAN_NEON, MAGENTA_NEON, GREEN_MATRIX, AMBER_WARN, PURPLE_GLOW,
    GRAY_LIGHT, GRAY_MUTED, CLR_BOLD, CLR_RST, render_hud_card, render_section_header
)

SQUAD_AGENTS = {
    "vincent-product": {
        "role": "Product & Scope Architect",
        "focus": "Especificação funcional, requisitos, design de features e regras de negócio.",
        "icon": "📋"
    },
    "vincent-auditor": {
        "role": "Security & Architecture Auditor",
        "focus": "Análise estática, conformidade de segurança, bloqueio de comandos perigosos e integridade.",
        "icon": "🛡️"
    },
    "vincent-coder": {
        "role": "Senior Systems & Firmware Coder",
        "focus": "Geração de código de alta performance, scripts Python, C++/Arduino e drivers.",
        "icon": "💻"
    },
    "vincent-hardware": {
        "role": "Embedded Hardware & RF Lab Engineer",
        "focus": "Orquestração de TEMBED (CC1101 Sub-GHz, IR) e ESP32DIV (NRF24, SD, Bruce shell).",
        "icon": "📡"
    },
    "vincent-tester": {
        "role": "Quality Assurance & Unit Tester",
        "focus": "Validação de planos, execução de testes de fumaça e testes de regressão.",
        "icon": "🧪"
    },
    "vincent-devops": {
        "role": "Autonomous DevOps & Daemons Engineer",
        "focus": "Gerenciamento de serviços systemd, timers, pipelines de CI e automação.",
        "icon": "⚙️"
    }
}

class GSDOrchestrator:
    """Motor de orquestração autônoma multi-agente GSD Core."""

    def __init__(self, agent):
        self.agent = agent

    def list_squad(self):
        """Exibe o squad de agentes especializados disponíveis."""
        items = []
        for name, info in SQUAD_AGENTS.items():
            items.append((f"{info['icon']} {name.upper()}", f"{info['role']} — {info['focus']}"))
        render_hud_card("SQUAD GSD MULTI-AGENT SWARM", items, PURPLE_GLOW)

    def execute_plan(self, task_description: str) -> str:
        """
        Executa um plano GSD completo divido em ondas e fases:
        Fase 1: Escopo (Product)
        Fase 2: Auditoria (Auditor)
        Fase 3: Execução (Coder + Hardware)
        Fase 4: Verificação (Tester)
        """
        prompt = f"""
[GSD CORE MULTI-AGENT SWARM EXECUTION]
Tarefa: {task_description}

Você deve agir como o Orquestrador Central GSD e coordenar os seguintes agentes especializados:
1. 📋 Vincent-Product: Delimita escopo e objetivos imediatos.
2. 🛡️ Vincent-Auditor: Identifica riscos, comandos bloqueados e dependências críticas.
3. 💻 Vincent-Coder & 📡 Vincent-Hardware: Produz o plano de ação técnico e comandos exatos (ex: CMD:TEMBED: ou CMD:ESP32DIV: se envolver hardware).
4. 🧪 Vincent-Tester: Define o critério de validação e verificação de sucesso.

Estruture a resposta com clareza em Fases e Ondas de Execução.
"""
        return self.agent.ask(prompt)
