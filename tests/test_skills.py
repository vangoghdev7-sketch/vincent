"""
Testes de lógica pura pro src/vincent/skills.py (loader de SKILL.md sob
demanda). Sem rede — add_skill_from_git mocka subprocess.run (não clona de
verdade). SKILLS_DIR isolado por teste via monkeypatch + tmp_path.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from vincent import skills


@pytest.fixture(autouse=True)
def isolated_skills_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "SKILLS_DIR", str(tmp_path / "skills_home"))
    yield


def _write_skill(root: str, name: str, description: str = "desc", body: str = "corpo", extra_frontmatter: str = ""):
    skill_dir = os.path.join(root, name)
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(f"---\nname: {name}\ndescription: {description}\n{extra_frontmatter}---\n{body}\n")
    return skill_dir


# ── list_skills ──────────────────────────────────────────────────────────

def test_list_skills_missing_dir_returns_empty():
    assert skills.list_skills() == []


def test_list_skills_reads_frontmatter_only_not_body():
    _write_skill(skills.SKILLS_DIR, "obsidian-markdown", description="usar com notas obsidian", body="SEGREDO_DO_CORPO")
    out = skills.list_skills()
    assert len(out) == 1
    entry = out[0]
    assert entry["name"] == "obsidian-markdown"
    assert entry["description"] == "usar com notas obsidian"
    assert entry["when_to_use"] == "usar com notas obsidian"
    assert entry["path"].endswith("SKILL.md")
    # boot é barato: corpo não deve vazar pro resultado do list_skills
    assert "SEGREDO_DO_CORPO" not in str(entry)


def test_list_skills_skips_dirs_without_skill_md():
    os.makedirs(os.path.join(skills.SKILLS_DIR, "not-a-skill"))
    with open(os.path.join(skills.SKILLS_DIR, "not-a-skill", "README.md"), "w") as f:
        f.write("nada de SKILL.md aqui")
    assert skills.list_skills() == []


def test_list_skills_falls_back_to_dirname_when_meta_has_no_name():
    skill_dir = os.path.join(skills.SKILLS_DIR, "fallback-name")
    os.makedirs(skill_dir)
    with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
        f.write("---\ndescription: sem campo name\n---\ncorpo\n")
    out = skills.list_skills()
    assert len(out) == 1
    assert out[0]["name"] == "fallback-name"


def test_list_skills_ignores_unreadable_frontmatter_gracefully():
    # tab em YAML é inválido -> _split_frontmatter cai no except e usa meta={}
    skill_dir = os.path.join(skills.SKILLS_DIR, "bad-yaml")
    os.makedirs(skill_dir)
    with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
        f.write("---\nfoo:\n\tbar: 1\n---\ncorpo\n")
    out = skills.list_skills()
    assert len(out) == 1
    assert out[0]["name"] == "bad-yaml"  # fallback pro nome do diretório
    assert out[0]["description"] == ""


def test_list_skills_sorted_by_dirname():
    _write_skill(skills.SKILLS_DIR, "zebra")
    _write_skill(skills.SKILLS_DIR, "alpha")
    out = skills.list_skills()
    assert [s["name"] for s in out] == ["alpha", "zebra"]


# ── load_skill_body ──────────────────────────────────────────────────────

def test_load_skill_body_returns_stripped_body():
    skill_dir = _write_skill(skills.SKILLS_DIR, "demo", body="  \nlinha 1\nlinha 2\n  ")
    path = os.path.join(skill_dir, "SKILL.md")
    body = skills.load_skill_body(path)
    assert body == "linha 1\nlinha 2"


def test_load_skill_body_missing_file_returns_empty_string():
    assert skills.load_skill_body("/nao/existe/SKILL.md") == ""


# ── match_skills ──────────────────────────────────────────────────────────

def test_match_skills_no_keywords_in_task_returns_empty():
    fake = [{"name": "x", "description": "algo", "when_to_use": "algo", "path": ""}]
    assert skills.match_skills("", skills=fake) == []
    # só stopwords -> nenhuma keyword extraída
    assert skills.match_skills("de a o e", skills=fake) == []


def test_match_skills_empty_skill_list():
    assert skills.match_skills("qualquer tarefa relevante", skills=[]) == []


def test_match_skills_scores_by_keyword_overlap():
    # match_skills é keyword literal (sem stemming) — usa as MESMAS palavras
    # da tarefa nas descriptions pra controlar o overlap de forma determinística.
    fake = [
        {"name": "low", "description": "python code review", "when_to_use": "python code review", "path": ""},
        {"name": "high", "description": "python code review debug tests", "when_to_use": "python code review debug tests", "path": ""},
        {"name": "none", "description": "receitas de bolo", "when_to_use": "receitas de bolo", "path": ""},
    ]
    matches = skills.match_skills("python code review debug tests urgent", skills=fake, max_matches=2)
    names = [m["name"] for m in matches]
    assert names == ["high", "low"]  # mais overlap (5) primeiro que (3), "none" (0) nunca bate
    assert "none" not in names


def test_match_skills_respects_max_matches():
    fake = [
        {"name": "a", "description": "python tests debug", "when_to_use": "python tests debug", "path": ""},
        {"name": "b", "description": "python tests", "when_to_use": "python tests", "path": ""},
        {"name": "c", "description": "python", "when_to_use": "python", "path": ""},
    ]
    assert len(skills.match_skills("python tests debug", skills=fake, max_matches=1)) == 1
    assert len(skills.match_skills("python tests debug", skills=fake, max_matches=10)) == 3


def test_match_skills_falls_back_to_description_when_no_when_to_use():
    fake = [{"name": "x", "description": "obsidian vault markdown", "path": ""}]
    matches = skills.match_skills("editar notas do obsidian vault", skills=fake)
    assert len(matches) == 1


# ── skills_context ──────────────────────────────────────────────────────

def test_skills_context_empty_when_no_match():
    _write_skill(skills.SKILLS_DIR, "obsidian", description="notas obsidian vault")
    assert skills.skills_context("qual a capital da frança") == ""


def test_skills_context_includes_body_of_matched_skill():
    _write_skill(skills.SKILLS_DIR, "obsidian", description="ler notas obsidian vault markdown", body="use [[wikilinks]]")
    ctx = skills.skills_context("preciso ler minhas notas obsidian vault markdown")
    assert "## Skills Ativadas" in ctx
    assert "obsidian" in ctx
    assert "[[wikilinks]]" in ctx


# ── add_skill_from_git ────────────────────────────────────────────────────

def test_add_skill_from_git_rejects_non_http_url():
    with pytest.raises(ValueError):
        skills.add_skill_from_git("git@github.com:foo/bar.git")


def test_add_skill_from_git_raises_on_clone_failure(monkeypatch):
    def fake_run(*a, **k):
        return subprocess.CompletedProcess(a[0], returncode=128, stdout="", stderr="fatal: repository not found")
    monkeypatch.setattr(skills.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="git clone falhou"):
        skills.add_skill_from_git("https://example.com/nope.git")


def test_add_skill_from_git_installs_from_skills_subdir(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        dest = cmd[-1]
        skill_dir = os.path.join(dest, "skills", "demo-skill")
        os.makedirs(skill_dir)
        with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
            f.write("---\nname: demo-skill\ndescription: test\n---\ncorpo\n")
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(skills.subprocess, "run", fake_run)

    installed = skills.add_skill_from_git("https://example.com/skills-repo.git")

    assert installed == ["demo-skill"]
    assert os.path.isfile(os.path.join(skills.SKILLS_DIR, "demo-skill", "SKILL.md"))


def test_add_skill_from_git_fallback_single_skill_at_repo_root(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        dest = cmd[-1]
        with open(os.path.join(dest, "SKILL.md"), "w") as f:
            f.write("---\nname: root-skill\ndescription: test\n---\ncorpo\n")
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(skills.subprocess, "run", fake_run)

    installed = skills.add_skill_from_git("https://example.com/my-single-skill.git")

    assert installed == ["my-single-skill"]
    assert os.path.isfile(os.path.join(skills.SKILLS_DIR, "my-single-skill", "SKILL.md"))


def test_add_skill_from_git_no_candidates_installs_nothing(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(cmd, 0)  # repo clonado, mas sem SKILL.md em lugar nenhum
    monkeypatch.setattr(skills.subprocess, "run", fake_run)

    installed = skills.add_skill_from_git("https://example.com/empty-repo.git")
    assert installed == []


def test_add_skill_from_git_overwrites_existing_dest(monkeypatch):
    # dest já existe com conteúdo antigo
    old_dir = os.path.join(skills.SKILLS_DIR, "demo-skill")
    os.makedirs(old_dir)
    with open(os.path.join(old_dir, "OLD_FILE.txt"), "w") as f:
        f.write("lixo antigo")

    def fake_run(cmd, capture_output, text, timeout):
        dest = cmd[-1]
        skill_dir = os.path.join(dest, "skills", "demo-skill")
        os.makedirs(skill_dir)
        with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
            f.write("---\nname: demo-skill\ndescription: nova versão\n---\ncorpo novo\n")
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(skills.subprocess, "run", fake_run)

    installed = skills.add_skill_from_git("https://example.com/skills-repo.git")

    assert installed == ["demo-skill"]
    assert not os.path.exists(os.path.join(skills.SKILLS_DIR, "demo-skill", "OLD_FILE.txt"))
    assert os.path.isfile(os.path.join(skills.SKILLS_DIR, "demo-skill", "SKILL.md"))


# ── self-check embutido ────────────────────────────────────────────────────

def test_module_demo_self_check_runs_clean(capsys):
    skills.demo()
    assert "skills.py: OK" in capsys.readouterr().out
