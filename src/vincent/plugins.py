"""
Vincent CLI 4.0 — Plugin & Skill Integrator.
Auto-discovers and integrates agent skills from ~/.agents/skills,
including Caveman, GSD Core, Ponytail, UI/UX Pro Max, Ruflo, etc.
"""

import os
import glob
from typing import Dict, List, Optional
from .ui import CYAN_NEON, MAGENTA_NEON, GREEN_MATRIX, PURPLE_GLOW, GRAY_LIGHT, GRAY_MUTED, CLR_BOLD, CLR_RST, render_hud_card

SKILLS_DIR = os.path.expanduser("~/.agents/skills")

class PluginManager:
    """Gerenciador de Skills e Plugins do ecossistema de agentes."""

    def __init__(self):
        self.skills: Dict[str, Dict] = {}
        self.active_plugins: set[str] = set()
        self.scan_skills()

    def scan_skills(self) -> int:
        """Varre o diretório de skills e indexa os manifestos."""
        self.skills.clear()
        if not os.path.isdir(SKILLS_DIR):
            return 0

        for entry in os.listdir(SKILLS_DIR):
            skill_path = os.path.join(SKILLS_DIR, entry)
            if not os.path.isdir(skill_path):
                continue

            skill_md = os.path.join(skill_path, "SKILL.md")
            readme_md = os.path.join(skill_path, "README.md")
            pkg_json = os.path.join(skill_path, "package.json")

            desc = "Skill do ecossistema de agentes"
            if os.path.isfile(skill_md):
                try:
                    with open(skill_md, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read(1000)
                        for line in content.splitlines():
                            if line.startswith("description:"):
                                desc = line.replace("description:", "").strip(" >\"'")
                                break
                except Exception:
                    pass
            elif os.path.isfile(readme_md):
                try:
                    with open(readme_md, "r", encoding="utf-8", errors="ignore") as f:
                        lines = [
                            l.strip() for l in f.readlines()
                            if l.strip() and not l.lstrip().startswith(("#", "<", "[![", "!["))
                            and '="' not in l and len(l.split()) >= 3
                        ]
                        if lines:
                            desc = lines[0][:100]
                except Exception:
                    pass

            self.skills[entry] = {
                "name": entry,
                "path": skill_path,
                "description": desc,
                "active": entry in self.active_plugins
            }

        # Ativa plugins essenciais por padrão
        for core in ["caveman", "gsd-core", "ponytail", "ui-ux-pro-max-skill"]:
            if core in self.skills:
                self.active_plugins.add(core)
                self.skills[core]["active"] = True

        return len(self.skills)

    def list_plugins(self):
        """Renderiza um HUD com todos os plugins e skills disponíveis."""
        items = []
        for name, info in sorted(self.skills.items()):
            status = f"{GREEN_MATRIX}● ATIVO{CLR_RST}" if info["active"] else f"{GRAY_MUTED}○ INATIVO{CLR_RST}"
            items.append((f"{name.upper()}", f"{status} — {info['description'][:65]}"))
        render_hud_card("SKILLS & PLUGINS INTEGRADOS", items, CYAN_NEON)

    def toggle(self, plugin_name: str) -> Optional[bool]:
        """Ativa ou desativa um plugin específico."""
        name = plugin_name.lower().strip()
        if name not in self.skills:
            return None
        if name in self.active_plugins:
            self.active_plugins.remove(name)
            self.skills[name]["active"] = False
            return False
        else:
            self.active_plugins.add(name)
            self.skills[name]["active"] = True
            return True

    def system_prompt_addon(self) -> str:
        """Gera aditivo de contexto com as skills ativas."""
        if not self.active_plugins:
            return ""
        lines = ["\n## Plugins & Capacidades Neurais Ativas:"]
        for p in self.active_plugins:
            desc = self.skills.get(p, {}).get("description", "")
            lines.append(f"- **{p}**: {desc}")
        return "\n".join(lines) + "\n"
