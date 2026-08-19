"""
Vincent CLI 4.0 — Motor de Skills (formato SKILL.md, mesmo padrão do
OpenCode/Claude Agent Skills/obsidian-skills). Pasta com frontmatter YAML
+ corpo em markdown, carregada sob demanda.

~/.vincent/skills/<nome>/SKILL.md:
    ---
    name: nome-da-skill
    description: quando usar isso (frase curta, indexada no boot)
    ---
    corpo em markdown, só lido quando a skill é ativada de verdade

Boot: só lê o frontmatter de cada skill (barato). O corpo entra no
contexto apenas quando a tarefa bate com a description (match por
palavra-chave — sem chamada de LLM extra pra decidir, sem embeddings:
ponytail — matching é substring/keyword, não semântico; trocar por
embeddings locais (já tem nomic-embed-text no catálogo) se a lista de
skills crescer e o keyword-match começar a errar muito).
"""

import os
import re
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional

import yaml

SKILLS_DIR = os.path.expanduser("~/.vincent/skills")

_STOPWORDS = {
    "a", "o", "as", "os", "de", "do", "da", "dos", "das", "e", "em", "um",
    "uma", "com", "para", "pra", "que", "no", "na", "nos", "nas", "se",
    "use", "when", "the", "and", "for", "com", "quando", "usar", "use",
}


def _split_frontmatter(text: str) -> tuple:
    """Separa frontmatter YAML (entre --- ---) do corpo. Retorna (meta, body)."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not m:
        # Tenta formato sem newline final após o segundo '---' (edge case comum
        # em arquivos salvos por editores que não adicionam trailing newline)
        m = re.match(r"^---\s*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)(.*)", text, re.DOTALL)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, m.group(2)


def list_skills() -> List[Dict]:
    """Boot: varre ~/.vincent/skills/*/SKILL.md e lê só o frontmatter (barato)."""
    if not os.path.isdir(SKILLS_DIR):
        return []
    out = []
    for name in sorted(os.listdir(SKILLS_DIR)):
        skill_file = os.path.join(SKILLS_DIR, name, "SKILL.md")
        if not os.path.isfile(skill_file):
            continue
        try:
            with open(skill_file, "r", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        meta, _ = _split_frontmatter(text)
        out.append({
            "name": meta.get("name", name),
            "description": meta.get("description", ""),
            "when_to_use": meta.get("when_to_use", meta.get("description", "")),
            "path": skill_file,
        })
    return out


def load_skill_body(skill_path: str) -> str:
    """Carrega o corpo completo (só quando a skill dispara de verdade)."""
    try:
        with open(skill_path, "r", encoding="utf-8") as f:
            _, body = _split_frontmatter(f.read())
        return body.strip()
    except OSError:
        return ""


def _keywords(text: str) -> set:
    words = re.findall(r"[a-zà-ú0-9]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def match_skills(task: str, skills: Optional[List[Dict]] = None, max_matches: int = 2) -> List[Dict]:
    """Casa a tarefa com skills por overlap de palavra-chave (barato, sem LLM extra)."""
    skills = skills if skills is not None else list_skills()
    task_kw = _keywords(task)
    if not task_kw:
        return []
    scored = []
    for sk in skills:
        sk_kw = _keywords(sk.get("when_to_use") or sk.get("description") or "")
        overlap = task_kw & sk_kw
        if overlap:
            scored.append((len(overlap), sk))
    scored.sort(key=lambda x: -x[0])
    return [sk for _, sk in scored[:max_matches]]


def skills_context(task: str) -> str:
    """Bloco pronto pra injetar no system prompt: corpo das skills que bateram com a tarefa."""
    matches = match_skills(task)
    if not matches:
        return ""
    parts = ["\n\n## Skills Ativadas (relevantes pra esta tarefa):"]
    for sk in matches:
        body = load_skill_body(sk["path"])
        if body:
            parts.append(f"\n### {sk['name']}\n{body}")
    return "\n".join(parts)


def add_skill_from_git(git_url: str) -> List[str]:
    """
    Clona um repo de skills (formato skills/<nome>/SKILL.md, padrão
    OpenCode/Claude Agent Skills) e instala cada skill encontrada em
    ~/.vincent/skills/<nome>/. Só copia arquivos — nunca executa nada do
    repo clonado.
    """
    if not re.match(r"^https?://", git_url):
        raise ValueError("Só URLs http(s) de git são aceitas.")

    os.makedirs(SKILLS_DIR, exist_ok=True)
    installed = []
    with tempfile.TemporaryDirectory(prefix="vincent-skill-") as tmp:
        try:
            proc = subprocess.run(
                ["git", "clone", "--depth", "1", git_url, tmp],
                capture_output=True, text=True, timeout=60
            )
        except FileNotFoundError:
            raise RuntimeError("git não encontrado no PATH.")
        except subprocess.TimeoutExpired:
            raise RuntimeError("git clone excedeu o tempo limite (60s).")
        if proc.returncode != 0:
            raise RuntimeError(f"git clone falhou: {proc.stderr.strip()[:300]}")

        # Padrão skills/<nome>/SKILL.md (obsidian-skills, opencode, claude skills)
        skills_root = os.path.join(tmp, "skills")
        candidates = []
        if os.path.isdir(skills_root):
            for name in sorted(os.listdir(skills_root)):
                src = os.path.join(skills_root, name)
                if os.path.isfile(os.path.join(src, "SKILL.md")):
                    candidates.append((name, src))
        # Fallback: repo de skill única, SKILL.md na raiz
        elif os.path.isfile(os.path.join(tmp, "SKILL.md")):
            name = os.path.basename(git_url.rstrip("/")).replace(".git", "")
            candidates.append((name, tmp))

        if not candidates:
            raise RuntimeError(
                "Nenhuma skill encontrada em '{}': esperado skills/<nome>/SKILL.md "
                "ou um SKILL.md na raiz do repo.".format(git_url)
            )

        for name, src in candidates:
            dest = os.path.join(SKILLS_DIR, name)
            if os.path.isdir(dest):
                shutil.rmtree(dest)
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git"))
            installed.append(name)

    return installed


def demo():
    """ponytail self-check: frontmatter parsing + keyword matching, sem tocar em ~/.vincent."""
    sample = """---
name: obsidian-markdown
description: usar quando precisar ler ou editar notas markdown do Obsidian
---
Corpo da skill: sintaxe de wikilinks [[nota]] e embeds ![[nota]].
"""
    meta, body = _split_frontmatter(sample)
    assert meta["name"] == "obsidian-markdown"
    assert "wikilinks" in body

    fake_skills = [{
        "name": "obsidian-markdown",
        "description": meta["description"],
        "when_to_use": meta["description"],
        "path": "",
    }]
    matches = match_skills("preciso ler minhas notas do obsidian", skills=fake_skills)
    assert len(matches) == 1 and matches[0]["name"] == "obsidian-markdown"

    no_match = match_skills("qual a capital da frança", skills=fake_skills)
    assert no_match == []

    print("skills.py: OK")


if __name__ == "__main__":
    demo()
