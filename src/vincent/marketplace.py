"""
Vincent CLI — Marketplace de Skills (módulo compartilhado).

O catálogo curado vivia preso dentro do web_ui.py: a GUI web tinha marketplace,
o CLI não tinha nada. Aqui ele vira um só lugar — a rota /api/marketplace e o
REPL consomem o MESMO catálogo, com o mesmo estado de instalado/ativo.

Dois diretórios de skills coexistem no Vincent (e não é bug, é histórico):
  ~/.vincent/skills  → skills.SKILLS_DIR, onde add_skill_from_git INSTALA
  ~/.agents/skills   → plugins.SKILLS_DIR, ecossistema de agentes que o
                       PluginManager varre e liga/desliga
Instalar/remover mexe só nesses dois; qualquer caminho que escape deles é
recusado (path traversal / symlink pra fora).
"""

import os
import shutil
from typing import Dict, List, Optional

from . import plugins as _plugins
from . import skills as _skills
from .ui import (
    CHROME_YELLOW,
    CLR_BOLD,
    CLR_DIM,
    CLR_RST,
    COBALT_BLUE,
    CYPRESS_GREEN,
    SHADOW_GRAY,
    STARRY_GOLD,
    VIOLET_SWIRL,
    get_terminal_width,
    strip_ansi,
)

# ─── Catálogo curado ─────────────────────────────────────────────────────────
# Skills instaláveis conhecidas (formato skills/<nome>/SKILL.md, o mesmo que
# add_skill_from_git espera). Se um repo estiver indisponível na hora de
# instalar, o erro do git clone volta na mensagem — nada é inventado aqui.
# tags[0] é a categoria (a SPA usa esse primeiro item pro ícone do card).
#
# SÓ ENTRA AQUI REPO QUE RESOLVE NO `git ls-remote`. As entradas de
# github.com/vincent-skills/* e obsidianmd/obsidian-skills foram removidas:
# a org vincent-skills não existe e os 5 repos davam 404 — o catálogo
# prometia skills que nenhum clone conseguiria trazer. Qualquer outro repo
# continua instalável por URL: /marketplace install <git-url>.
_CATALOG = [
    {
        "name": "anthropic-skills",
        "title": "Anthropic Agent Skills",
        "desc": ("Coleção oficial em skills/<nome>/SKILL.md: pdf, docx, pptx, xlsx, "
                 "mcp-builder, skill-creator, canvas-design, webapp-testing e mais "
                 "(19 skills instaladas de uma vez)."),
        "source": "https://github.com/anthropics/skills",
        "tags": ["Documentos", "pdf", "docx", "xlsx", "mcp", "skills"],
        "author": "anthropics",
    },
]


# ─── Cerca de segurança ──────────────────────────────────────────────────────

def _roots() -> List[str]:
    """Diretórios onde o marketplace pode escrever/apagar. Lidos em tempo de
    chamada (não no import) pra os testes conseguirem isolar via monkeypatch."""
    return [_skills.SKILLS_DIR, _plugins.SKILLS_DIR]


def _safe_skill_dir(name: str) -> Optional[str]:
    """
    Resolve <root>/<name> e devolve o caminho REAL só se ele for filho direto
    de um dos roots permitidos. Recusa nome vazio, com separador, '..',
    absoluto, ou symlink que aponte pra fora da cerca. None = recusado.
    """
    if not name or not isinstance(name, str):
        return None
    name = name.strip()
    if not name or name in (".", "..") or os.path.isabs(name):
        return None
    if "\x00" in name:
        # Recusa, não exceção: o contrato é "None = recusado" e o realpath
        # levantaria ValueError (embedded null character) na cara do chamador.
        return None
    if os.sep in name or (os.altsep and os.altsep in name) or "/" in name or "\\" in name:
        return None

    for root in _roots():
        real_root = os.path.realpath(root)
        candidate = os.path.realpath(os.path.join(root, name))
        # filho DIRETO do root, e nunca o próprio root
        if candidate != real_root and os.path.dirname(candidate) == real_root:
            if os.path.isdir(candidate):
                return candidate
    return None


# ─── Estado instalado/ativo ──────────────────────────────────────────────────

def _installed_names() -> set:
    """Nomes de skills presentes no disco (frontmatter + nome de diretório)."""
    names = set()
    try:
        for sk in _skills.list_skills():
            names.add(sk.get("name", ""))
    except Exception:
        pass
    for root in _roots():
        try:
            for entry in os.listdir(root):
                if os.path.isdir(os.path.join(root, entry)):
                    names.add(entry)
        except OSError:
            pass
    names.discard("")
    return names


def _active_names() -> set:
    """Plugins ligados no PluginManager (~/.agents/skills)."""
    try:
        return set(_plugins.PluginManager().active_plugins)
    except Exception:
        return set()


# ─── API pública ─────────────────────────────────────────────────────────────

def catalog() -> List[Dict]:
    """Catálogo curado com installed/active resolvidos contra o disco."""
    inst, act = _installed_names(), _active_names()
    return [
        dict(item, installed=item["name"] in inst, active=item["name"] in act)
        for item in _CATALOG
    ]


def installed() -> List[Dict]:
    """Só as skills do catálogo que já estão instaladas."""
    return [item for item in catalog() if item["installed"]]


def search(term: str) -> List[Dict]:
    """Filtra o catálogo por nome, título, descrição ou tags."""
    term = (term or "").strip().lower()
    if not term:
        return catalog()
    out = []
    for item in catalog():
        haystack = " ".join([
            item["name"], item["title"], item["desc"], item["author"],
            " ".join(item["tags"]),
        ]).lower()
        if term in haystack:
            out.append(item)
    return out


def _unlink_escaped(names: List[str]) -> List[str]:
    """Tira do root os symlinks que fizeram o nome escapar da cerca.
    Só `os.unlink` no LINK — o alvo (que pode ser ~/Documentos) fica intacto."""
    removed = []
    for name in names:
        for root in _roots():
            path = os.path.join(root, name)
            try:
                if os.path.islink(path):
                    os.unlink(path)
                    removed.append(name)
            except OSError:
                pass
    return removed


def install(name_or_url: str) -> Dict:
    """
    Instala uma skill: aceita um nome do catálogo ou uma URL git http(s).
    Retorna {"ok", "msg", "files"} — files são os nomes das skills instaladas.
    """
    ref = (name_or_url or "").strip()
    if not ref:
        return {"ok": False, "msg": "Informe o nome de uma skill ou a URL do repositório.", "files": []}

    if ref.startswith("http://") or ref.startswith("https://"):
        url = ref
    else:
        match = next((i for i in _CATALOG if i["name"] == ref.lower()), None)
        if not match:
            return {"ok": False, "msg": f"Skill '{ref}' não está no catálogo. Use /market buscar <termo> ou passe uma URL git.", "files": []}
        url = match["source"]

    try:
        files = _skills.add_skill_from_git(url)
    except (ValueError, RuntimeError) as e:
        return {"ok": False, "msg": str(e), "files": []}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "msg": f"falha inesperada ao instalar: {e}", "files": []}

    if not files:
        return {"ok": False, "msg": "Nenhuma skill encontrada no repositório (esperado skills/<nome>/SKILL.md ou SKILL.md na raiz).", "files": []}

    # Cerca de segurança: confere que tudo aterrissou dentro dos roots.
    # É PÓS-FATO (o clone já copiou), então recusar sem limpar deixava os
    # arquivos no disco com um "recusado" na tela.
    escaped = [f for f in files if _safe_skill_dir(f) is None]
    if escaped:
        soltos = _unlink_escaped(escaped)
        msg = f"Instalação recusada: caminho fora de {_skills.SKILLS_DIR} ({', '.join(escaped)})."
        msg += (f" Link(s) removido(s): {', '.join(soltos)}." if soltos
                else " Confira o disco: os arquivos podem ter ficado fora da cerca.")
        return {"ok": False, "msg": msg, "files": []}

    return {"ok": True, "msg": f"{len(files)} skill(s) instalada(s): {', '.join(files)}", "files": files}


def remove(name: str) -> Dict:
    """Apaga o diretório de uma skill instalada. Só dentro dos roots permitidos."""
    target = _safe_skill_dir(name)
    if target is None:
        return {"ok": False, "msg": f"Recusado: '{name}' não é uma skill instalada dentro de {_skills.SKILLS_DIR}."}
    # Se a entrada é um symlink pra uma skill irmã, o realpath já resolveu pro
    # ALVO — rmtree apagaria a skill errada e deixaria o link pendurado.
    for root in _roots():
        path = os.path.join(root, name)
        if os.path.islink(path):
            try:
                os.unlink(path)
            except OSError as e:
                return {"ok": False, "msg": f"falha ao remover o link '{name}': {e}"}
            return {"ok": True, "msg": f"Link '{name}' removido (o alvo {target} ficou intacto)."}
    try:
        shutil.rmtree(target)
    except OSError as e:
        return {"ok": False, "msg": f"falha ao remover '{name}': {e}"}
    return {"ok": True, "msg": f"Skill '{name}' removida de {target}."}


# ─── Render ANSI (CLI / fallback sem TTY) ────────────────────────────────────

def render_text(items: List[Dict], width: Optional[int] = None) -> str:
    """
    Cartões 'Noite Estrelada' pro terminal. As cores de ui.py já se apagam
    sozinhas quando a saída não é um TTY, então isto degrada pra texto puro.
    """
    if width is None:
        width = get_terminal_width()
    width = max(40, min(int(width), 94))

    if not items:
        return f"{SHADOW_GRAY}Nenhuma skill encontrada no marketplace.{CLR_RST}"

    title = "MARKETPLACE DE SKILLS"
    lines = [f"{COBALT_BLUE}◈ {CHROME_YELLOW}{CLR_BOLD}{title}{CLR_RST} "
             f"{COBALT_BLUE}{'─' * max(3, width - len(title) - 4)}{CLR_RST}"]

    for item in items:
        if item.get("active"):
            badge = f"{CYPRESS_GREEN}● ativa{CLR_RST}"
        elif item.get("installed"):
            badge = f"{CYPRESS_GREEN}✓ instalada{CLR_RST}"
        else:
            badge = f"{SHADOW_GRAY}○ disponível{CLR_RST}"

        head = f"{STARRY_GOLD}{CLR_BOLD}{item['name']}{CLR_RST}"
        pad = max(1, width - len(strip_ansi(head)) - len(strip_ansi(badge)) - 2)
        lines.append(f"\n{head}{' ' * pad}{badge}")

        for chunk in _wrap(item.get("desc", ""), width - 2):
            lines.append(f"  {chunk}")

        tags = " ".join(f"#{t}" for t in item.get("tags", []))
        meta = f"  {VIOLET_SWIRL}{tags}{CLR_RST}  {CLR_DIM}{item.get('source', '')}{CLR_RST}"
        lines.append(meta)

    lines.append(f"\n{SHADOW_GRAY}{len(items)} skill(s) · instale com {CLR_RST}"
                 f"{CHROME_YELLOW}/market instalar <nome|url>{CLR_RST}")
    return "\n".join(lines)


def _wrap(text: str, width: int) -> List[str]:
    """Quebra de linha por palavra (sem textwrap: não precisa de mais que isso)."""
    out, line = [], ""
    for word in str(text).split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


def demo():
    """ponytail self-check: catálogo, busca e a cerca de path traversal."""
    assert catalog() and all(
        {"name", "title", "desc", "source", "tags", "author", "installed", "active"} <= set(i)
        for i in catalog()
    )
    assert [i["name"] for i in search("pdf")] == ["anthropic-skills"]
    assert search("zzzz-nao-existe") == []
    assert remove("../../../etc")["ok"] is False
    assert remove("/etc/passwd")["ok"] is False
    assert remove("evil\x00name")["ok"] is False   # byte nulo = recusa, não ValueError
    assert install("nao-existe-no-catalogo")["ok"] is False
    print(render_text(catalog()))
    print("marketplace.py: OK")


if __name__ == "__main__":
    demo()
