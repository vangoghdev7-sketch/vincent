"""
Testes do marketplace de skills (src/vincent/marketplace.py) e da rota
/api/marketplace, que agora consome o mesmo catálogo.

Sem rede: install() nunca chega a clonar (monkeypatch em add_skill_from_git).
Os dois roots de skills (~/.vincent/skills e ~/.agents/skills) são isolados em
tmp_path — nenhum teste toca o HOME de verdade.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from vincent import marketplace, plugins, skills

ITEM_KEYS = {"name", "title", "desc", "source", "tags", "author", "installed", "active"}


@pytest.fixture(autouse=True)
def isolated_roots(tmp_path, monkeypatch):
    """Aponta os dois SKILLS_DIR pra tmp_path e zera os plugins ativos."""
    vincent_root = tmp_path / "vincent_skills"
    agents_root = tmp_path / "agents_skills"
    vincent_root.mkdir()
    agents_root.mkdir()
    monkeypatch.setattr(skills, "SKILLS_DIR", str(vincent_root))
    monkeypatch.setattr(plugins, "SKILLS_DIR", str(agents_root))
    monkeypatch.setattr(marketplace, "_active_names", lambda: set())
    return vincent_root, agents_root


def _install_fake(root, name: str):
    d = root / name
    d.mkdir()
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: fake\n---\ncorpo\n", encoding="utf-8")
    return d


# ── catalog() ────────────────────────────────────────────────────────────

def test_catalog_shape_e_conteudo():
    items = marketplace.catalog()
    assert items, "catálogo não pode estar vazio"
    for item in items:
        assert set(item) == ITEM_KEYS
        assert isinstance(item["tags"], list) and item["tags"]
        assert item["source"].startswith("https://")
        assert isinstance(item["installed"], bool)
        assert isinstance(item["active"], bool)


def test_catalog_nada_instalado_por_padrao():
    assert all(not i["installed"] for i in marketplace.catalog())
    assert marketplace.installed() == []


def test_catalog_marca_installed_ao_achar_o_diretorio(isolated_roots):
    vincent_root, _ = isolated_roots
    assert marketplace.installed() == []
    _install_fake(vincent_root, "anthropic-skills")
    by_name = {i["name"]: i for i in marketplace.catalog()}
    assert by_name["anthropic-skills"]["installed"] is True
    assert [i["name"] for i in marketplace.installed()] == ["anthropic-skills"]


def test_catalog_marca_active_pelo_plugin_manager(monkeypatch):
    monkeypatch.setattr(marketplace, "_active_names", lambda: {"anthropic-skills"})
    by_name = {i["name"]: i for i in marketplace.catalog()}
    assert by_name["anthropic-skills"]["active"] is True


def test_catalog_so_aponta_pra_repos_que_existem():
    """Regressão: 5 das 6 entradas apontavam pra repos 404 (a org
    vincent-skills nem existe) — o catálogo prometia o que nenhum clone
    conseguiria trazer. Sem rede aqui: só as origens conhecidas passam."""
    permitidas = {"https://github.com/anthropics/skills"}
    assert {i["source"] for i in marketplace._CATALOG} <= permitidas


def test_catalog_nao_quebra_com_root_inexistente(monkeypatch, tmp_path):
    monkeypatch.setattr(skills, "SKILLS_DIR", str(tmp_path / "nunca_criado"))
    assert len(marketplace.catalog()) == len(marketplace._CATALOG)


# ── search() ─────────────────────────────────────────────────────────────

def test_search_por_nome():
    assert [i["name"] for i in marketplace.search("anthropic")] == ["anthropic-skills"]


def test_search_por_tag_e_case_insensitive():
    assert [i["name"] for i in marketplace.search("DOCUMENTOS")] == ["anthropic-skills"]


def test_search_por_descricao():
    nomes = [i["name"] for i in marketplace.search("mcp-builder")]
    assert nomes == ["anthropic-skills"]


def test_search_por_autor():
    assert [i["name"] for i in marketplace.search("anthropics")] == ["anthropic-skills"]


def test_search_sem_resultado():
    assert marketplace.search("zzz-nao-existe-zzz") == []


def test_search_vazio_devolve_catalogo_inteiro():
    assert len(marketplace.search("")) == len(marketplace.catalog())
    assert len(marketplace.search("   ")) == len(marketplace.catalog())


# ── remove(): cerca de path traversal ────────────────────────────────────

@pytest.mark.parametrize("evil", [
    "../../../etc",
    "..",
    ".",
    "../agents_skills",
    "sub/../../escape",
    "/etc/passwd",
    "",
    "   ",
    None,
])
def test_remove_recusa_path_traversal(evil, tmp_path):
    fora = tmp_path / "fora"
    fora.mkdir()
    (fora / "arquivo.txt").write_text("não me apague", encoding="utf-8")
    res = marketplace.remove(evil)
    assert res["ok"] is False
    assert "Recusado" in res["msg"]
    assert fora.exists() and (fora / "arquivo.txt").exists()


def test_remove_recusa_symlink_que_escapa(isolated_roots, tmp_path):
    vincent_root, _ = isolated_roots
    fora = tmp_path / "alvo_secreto"
    fora.mkdir()
    (fora / "segredo.txt").write_text("intacto", encoding="utf-8")
    os.symlink(str(fora), str(vincent_root / "cavalo-de-troia"))

    res = marketplace.remove("cavalo-de-troia")
    assert res["ok"] is False
    assert fora.exists() and (fora / "segredo.txt").read_text() == "intacto"


def test_remove_recusa_o_proprio_root(isolated_roots):
    vincent_root, _ = isolated_roots
    assert marketplace.remove(str(vincent_root))["ok"] is False
    assert vincent_root.exists()


def test_remove_apaga_skill_legitima(isolated_roots):
    vincent_root, _ = isolated_roots
    d = _install_fake(vincent_root, "pdf-tools")
    res = marketplace.remove("pdf-tools")
    assert res["ok"] is True
    assert not d.exists()
    assert vincent_root.exists()


def test_remove_tambem_cobre_o_root_de_agents(isolated_roots):
    _, agents_root = isolated_roots
    d = _install_fake(agents_root, "ponytail")
    assert marketplace.remove("ponytail")["ok"] is True
    assert not d.exists()


def test_remove_skill_inexistente():
    assert marketplace.remove("nunca-instalei-isso")["ok"] is False


# ── install() ────────────────────────────────────────────────────────────

def test_install_resolve_nome_do_catalogo_para_a_url(monkeypatch, isolated_roots):
    vincent_root, _ = isolated_roots
    chamadas = []

    def fake_clone(url):
        chamadas.append(url)
        _install_fake(vincent_root, "anthropic-skills")
        return ["anthropic-skills"]

    monkeypatch.setattr(marketplace._skills, "add_skill_from_git", fake_clone)
    res = marketplace.install("anthropic-skills")
    assert res["ok"] is True and res["files"] == ["anthropic-skills"]
    assert chamadas == ["https://github.com/anthropics/skills"]


def test_install_aceita_url_direta(monkeypatch, isolated_roots):
    vincent_root, _ = isolated_roots
    monkeypatch.setattr(
        marketplace._skills, "add_skill_from_git",
        lambda url: (_install_fake(vincent_root, "custom"), ["custom"])[1],
    )
    assert marketplace.install("https://github.com/foo/bar")["ok"] is True


def test_install_recusa_nome_fora_do_catalogo(monkeypatch):
    monkeypatch.setattr(
        marketplace._skills, "add_skill_from_git",
        lambda url: pytest.fail("não deveria clonar nada"),
    )
    for ref in ["nao-existe", "../../etc/passwd", "/etc/passwd", ""]:
        assert marketplace.install(ref)["ok"] is False


def test_install_propaga_erro_do_git(monkeypatch):
    def boom(url):
        raise RuntimeError("git clone falhou: repo não encontrado")
    monkeypatch.setattr(marketplace._skills, "add_skill_from_git", boom)
    res = marketplace.install("anthropic-skills")
    assert res["ok"] is False and "git clone falhou" in res["msg"]


def test_install_recusa_arquivo_que_aterrissou_fora_da_cerca(monkeypatch):
    """Se o clone reportar um nome que não resolve dentro dos roots, é recusado."""
    monkeypatch.setattr(marketplace._skills, "add_skill_from_git", lambda url: ["../fugiu"])
    res = marketplace.install("anthropic-skills")
    assert res["ok"] is False and "fora de" in res["msg"]


def test_remove_recusa_nome_com_byte_nulo():
    """Byte nulo é RECUSA (contrato: None = recusado), não ValueError vazando
    do realpath pra cima do chamador."""
    res = marketplace.remove("evil\x00name")
    assert res["ok"] is False and "Recusado" in res["msg"]


def test_remove_de_symlink_interno_apaga_o_link_e_nao_o_alvo(isolated_roots):
    """realpath resolve antes do rmtree: sem a guarda, remover o atalho
    apagava a skill irmã e deixava o link pendurado."""
    vincent_root, _ = isolated_roots
    real = _install_fake(vincent_root, "de-verdade")
    os.symlink(str(real), str(vincent_root / "atalho"))
    assert marketplace.remove("atalho")["ok"] is True
    assert not os.path.lexists(str(vincent_root / "atalho"))
    assert real.exists() and (real / "SKILL.md").exists()


def test_install_recusado_tira_o_link_que_escapou_da_cerca(isolated_roots, tmp_path, monkeypatch):
    """A cerca do install() é pós-fato: recusar sem limpar deixava o link no
    disco com um 'recusado' na tela."""
    vincent_root, _ = isolated_roots
    fora = tmp_path / "alvo_fora"
    fora.mkdir()
    (fora / "intacto.txt").write_text("intacto", encoding="utf-8")
    os.symlink(str(fora), str(vincent_root / "fugiu"))

    monkeypatch.setattr(marketplace._skills, "add_skill_from_git", lambda url: ["fugiu"])
    res = marketplace.install("anthropic-skills")
    assert res["ok"] is False
    assert not os.path.lexists(str(vincent_root / "fugiu"))     # link removido
    assert (fora / "intacto.txt").read_text() == "intacto"      # alvo intacto


# ── render_text() ────────────────────────────────────────────────────────

def test_render_text_sem_tty_nao_quebra_e_lista_tudo():
    out = marketplace.render_text(marketplace.catalog(), width=80)
    for item in marketplace._CATALOG:
        assert item["name"] in out
    assert all(len(linha) < 400 for linha in out.splitlines())


def test_render_text_lista_vazia():
    assert "Nenhuma skill" in marketplace.render_text([])


def test_render_text_marca_instalada(isolated_roots):
    vincent_root, _ = isolated_roots
    _install_fake(vincent_root, "anthropic-skills")
    assert "instalada" in marketplace.render_text(marketplace.installed(), width=80)


# ── rota web: mesmo shape de antes ───────────────────────────────────────

def test_rota_marketplace_mantem_o_shape_antigo():
    flask = pytest.importorskip("flask")
    from vincent.web_ui import bp

    app = flask.Flask(__name__)
    app.register_blueprint(bp)
    resp = app.test_client().get("/api/marketplace")

    assert resp.status_code == 200
    data = resp.get_json()
    assert set(data) == {"skills", "count"}
    assert data["count"] == len(data["skills"]) == len(marketplace._CATALOG)
    for entry in data["skills"]:
        assert set(entry) == {"name", "description", "git_url", "category"}
        assert entry["git_url"].startswith("https://")
        assert entry["description"]

    # tags[0] continua sendo a categoria que a SPA mapeia pro ícone do card
    cats = {e["category"] for e in data["skills"]}
    assert cats == {i["tags"][0] for i in marketplace._CATALOG}
