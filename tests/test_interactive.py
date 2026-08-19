"""
Testes da camada interativa (vincent.interactive).

Usa o harness headless do prompt_toolkit (create_pipe_input + DummyOutput)
pra alimentar teclas de verdade no Application do picker. Nada de rede, nada
de escrita em ~/.vincent (build_session só é exercitado no caminho sem TTY).
"""

import os
import shutil
import subprocess
import sys
from contextlib import contextmanager

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vincent import interactive as ia

ptk = pytest.importorskip("prompt_toolkit")
from prompt_toolkit.application import create_app_session
from prompt_toolkit.document import Document
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput


KEY_DOWN = "\x1b[B"
KEY_UP = "\x1b[A"
KEY_END = "\x1b[F"
ENTER = "\r"
ESC = "\x1b"


@contextmanager
def keys(text):
    """Roda um bloco com as teclas `text` já enfileiradas no stdin virtual."""
    with create_pipe_input() as pipe:
        pipe.send_text(text)
        with create_app_session(input=pipe, output=DummyOutput()):
            yield


@pytest.fixture
def force_interactive(monkeypatch):
    monkeypatch.setattr(ia, "supports_interactive", lambda: True)


MODELS = [
    {"id": "qwen3:0.6b", "display_id": "qwen3:0.6b", "name": "qwen3:0.6b (Local)",
     "provider": "vincent-local", "is_free": True, "is_local": True},
    {"id": "auto/best-coding", "display_id": "auto/best-coding", "name": "Combo Coding",
     "provider": "vincent-cloud", "is_free": True, "is_local": False},
    {"id": "free/glm-4-flash", "display_id": "vincent/glm-4-flash", "name": "GLM 4 Flash",
     "provider": "vincent-cloud", "is_free": True, "is_local": False},
    {"id": "pro/claude-x", "display_id": "vincent/atelier-x", "name": "Atelier X",
     "provider": "vincent-cloud", "is_free": False, "is_local": False},
]

COMMANDS = [
    {"cmd": "/models", "args": "", "desc": "Catálogo navegável", "group": "Galeria"},
    {"cmd": "/model", "args": "<id>", "desc": "Sintoniza o modelo ativo", "group": "Galeria"},
    {"cmd": "/effort", "args": "low|medium|high", "desc": "Nível de raciocínio", "group": "Ajustes"},
    {"cmd": "/help", "args": "", "desc": "Guia de comandos", "group": "Ajustes"},
]


# ─── fuzzy score / ordenação ──────────────────────────────────────────────────
def test_fuzzy_score_prefix_beats_middle_beats_scattered():
    prefix = ia.fuzzy_score("gpt", "gpt-4-turbo")
    middle = ia.fuzzy_score("gpt", "openai/gpt-4-turbo")
    scattered = ia.fuzzy_score("gpt", "grande-pintura-tela")
    assert prefix > middle > scattered
    assert ia.fuzzy_score("gpt", "qwen3:0.6b") is None
    assert ia.fuzzy_score("", "qualquer coisa") == 0.0


def test_fuzzy_score_is_case_insensitive():
    assert ia.fuzzy_score("QWEN", "qwen3:0.6b") == ia.fuzzy_score("qwen", "QWEN3:0.6B")


def test_score_item_uses_display_id_name_and_provider():
    m = MODELS[2]
    assert ia.score_item("glm", m) is not None          # display_id
    assert ia.score_item("flash", m) is not None        # name
    assert ia.score_item("cloud", m) is not None        # provider
    assert ia.score_item("zzzz", m) is None


def test_filter_orders_by_score(force_interactive):
    items = [
        {"display_id": "openai/gpt-4"},
        {"display_id": "gpt-4-mini"},
        {"display_id": "grande-pintura-tela"},
    ]
    p = ia.FuzzyPicker(items, "t")
    p._rebuild("gpt")
    assert [e["item"]["display_id"] for e in p.entries] == [
        "gpt-4-mini", "openai/gpt-4", "grande-pintura-tela"
    ]


def test_no_truncation_all_485_items_reachable():
    items = [{"display_id": f"model-{i:03d}"} for i in range(485)]
    p = ia.FuzzyPicker(items, "t", height=10)
    p._rebuild("")
    assert len(p.entries) == 485
    p._jump(to_end=True)
    assert p.selection()["display_id"] == "model-484"


# ─── navegação / seleção no Application real ──────────────────────────────────
def test_enter_returns_first_item(force_interactive):
    p = ia.FuzzyPicker(MODELS, "modelos", group_key=ia.model_group)
    with keys(ENTER):
        assert p.run()["display_id"] == "qwen3:0.6b"


def test_navigation_skips_group_headers(force_interactive):
    # Cada modelo cai num grupo diferente => 4 cabeçalhos intercalados.
    p = ia.FuzzyPicker(MODELS, "modelos", group_key=ia.model_group)
    with keys(KEY_DOWN + KEY_DOWN + ENTER):
        chosen = p.run()
    assert chosen["display_id"] == "vincent/glm-4-flash"
    # 4 itens + 4 cabeçalhos, e o índice parou num item de verdade.
    assert len(p.entries) == 8
    assert p.entries[p.index]["item"] is chosen


def test_end_key_selects_last_item(force_interactive):
    p = ia.FuzzyPicker(MODELS, "modelos", group_key=ia.model_group)
    with keys(KEY_END + ENTER):
        assert p.run()["display_id"] == "vincent/atelier-x"


def test_typing_filters_and_hides_headers(force_interactive):
    p = ia.FuzzyPicker(MODELS, "modelos", group_key=ia.model_group)
    with keys("glm" + ENTER):
        chosen = p.run()
    assert chosen["display_id"] == "vincent/glm-4-flash"
    assert all(e["header"] is None for e in p.entries)   # busca ativa some com os grupos


def test_esc_returns_none(force_interactive):
    p = ia.FuzzyPicker(MODELS, "modelos", group_key=ia.model_group)
    with keys(ESC):
        assert p.run() is None


def test_letter_q_filters_instead_of_quitting(force_interactive):
    """Com 485 modelos, 'q' TEM que digitar 'qwen' — não fechar o picker."""
    p = ia.FuzzyPicker(MODELS, "modelos", group_key=ia.model_group)
    with keys("qwen" + ENTER):
        assert p.run()["display_id"] == "qwen3:0.6b"


def test_ctrl_c_returns_none(force_interactive):
    p = ia.FuzzyPicker(MODELS, "modelos", group_key=ia.model_group)
    with keys("\x03"):
        assert p.run() is None


def test_ctrl_u_clears_query_and_brings_headers_back(force_interactive):
    p = ia.FuzzyPicker(MODELS, "modelos", group_key=ia.model_group)
    with keys("glm" + "\x15" + ENTER):
        chosen = p.run()
    assert chosen["display_id"] == "qwen3:0.6b"
    assert any(e["header"] for e in p.entries)


def test_pick_model_returns_display_id(force_interactive):
    with keys(KEY_DOWN + ENTER):
        assert ia.pick_model(FakeAgent()) == "auto/best-coding"


def test_browse_models_switches_model(force_interactive):
    switched = []

    class Recording(FakeAgent):
        def set_model(self, m):
            switched.append(m)
            self.display_model = m

    with keys(KEY_END + ENTER):
        assert ia.browse_models(Recording()) == "vincent/atelier-x"
    assert switched == ["vincent/atelier-x"]


def test_pick_command_returns_cmd(force_interactive):
    with keys("effort" + ENTER):
        assert ia.pick_command(COMMANDS) == "/effort"


# ─── sessão de prompt ─────────────────────────────────────────────────────────
class FakeAgent:
    display_model = "qwen3:0.6b"
    model = "qwen3:0.6b"

    class model_manager:
        @staticmethod
        def get_all_models():
            return list(MODELS)

    def set_model(self, m):
        self.display_model = m


def _status():
    return {"model": "qwen3:0.6b", "effort": "medium", "caveman": "off",
            "autoedit": "on", "tier": "Galeria", "latency": "1.2s"}


@pytest.fixture
def session_env(force_interactive, monkeypatch, tmp_path):
    # Nunca escreve em ~/.vincent durante os testes.
    monkeypatch.setattr(ia, "HISTORY_PATH", str(tmp_path / "repl_history"))


def test_toolbar_shows_every_chip():
    text = "".join(t for _, t in ia._toolbar_fragments(_status(), width=200))
    for chip in ("◆ qwen3:0.6b", "⚙ medium", "▣ caveman off", "✎ autoedit on",
                 "● Galeria", "⏱ 1.2s"):
        assert chip in text


def test_toolbar_cabe_na_largura_do_terminal():
    """175 colunas de chips quebravam no meio da palavra em qualquer terminal
    de 80/100 col. O que não cabe é cortado pelo fim, o modelo fica."""
    for width in (60, 80, 100, 120):
        text = "".join(t for _, t in ia._toolbar_fragments(_status(), width=width))
        assert len(text) <= width, (width, len(text), text)
        assert "◆ qwen3:0.6b" in text


def test_toolbar_survives_missing_fields():
    assert "◆ x" in "".join(t for _, t in ia._toolbar_fragments({"model": "x"}))


def test_session_reads_a_line(session_env):
    with keys("olá vincent" + ENTER):
        session = ia.build_session(FakeAgent(), COMMANDS, _status)
        assert session is not None
        assert ia.read_prompt(session, FakeAgent()) == "olá vincent"


def test_ctrl_o_opens_model_picker_and_returns_slash_model(session_env):
    # Ctrl+O sai da linha, o picker abre, ↓ + Enter escolhe o 2º modelo.
    with keys("\x0f" + KEY_DOWN + ENTER):
        session = ia.build_session(FakeAgent(), COMMANDS, _status)
        assert ia.read_prompt(session, FakeAgent()) == "/model auto/best-coding"


def test_ctrl_p_opens_command_palette(session_env):
    """Comando SEM argumento obrigatório sai direto da paleta."""
    with keys("\x10" + "help" + ENTER):
        session = ia.build_session(FakeAgent(), COMMANDS, _status)
        assert ia.read_prompt(session, FakeAgent()) == "/help"


def test_ctrl_p_preenche_a_linha_quando_o_comando_exige_argumento(session_env):
    """'/effort <valor>' escolhido na paleta NÃO pode submeter pelado (era beco
    sem saída: 'Uso: /effort low|medium|high'). Volta pra linha preenchida."""
    with keys("\x10" + "effort" + ENTER + "high" + ENTER):
        session = ia.build_session(FakeAgent(), COMMANDS, _status)
        assert ia.read_prompt(session, FakeAgent()) == "/effort high"


def test_alt_enter_inserts_newline_and_enter_sends(session_env):
    with keys("linha1" + "\x1b\r" + "linha2" + ENTER):
        session = ia.build_session(FakeAgent(), COMMANDS, _status)
        assert ia.read_prompt(session, FakeAgent()) == "linha1\nlinha2"


def test_ctrl_c_clears_the_line_without_exiting(session_env):
    with keys("lixo" + "\x03" + "bom" + ENTER):
        session = ia.build_session(FakeAgent(), COMMANDS, _status)
        assert ia.read_prompt(session, FakeAgent()) == "bom"


def test_ctrl_d_raises_eof(session_env):
    with keys("\x04"):
        session = ia.build_session(FakeAgent(), COMMANDS, _status)
        with pytest.raises(EOFError):
            ia.read_prompt(session, FakeAgent())


# ─── completer ────────────────────────────────────────────────────────────────
def _complete(text, completer=None):
    c = completer or ia.VincentCompleter(COMMANDS, lambda: [m["display_id"] for m in MODELS])
    return list(c.get_completions(Document(text, len(text)), None))


def test_completer_lists_all_commands_on_slash():
    comps = _complete("/")
    assert {c.text for c in comps} == {"/models", "/model", "/effort", "/help"}
    metas = {c.text: c.display_meta_text for c in comps}
    assert metas["/help"] == "Guia de comandos"


def test_completer_ranks_fuzzy_matches():
    assert [c.text for c in _complete("/mod")][0] == "/model"
    assert _complete("/ef")[0].text == "/effort"


def test_completer_ignores_plain_prose():
    assert _complete("olá vincent") == []
    assert _complete("h") == []


def test_completer_completes_model_ids_with_slashes():
    comps = _complete("/model auto/be")
    assert comps[0].text == "auto/best-coding"
    assert comps[0].start_position == -len("auto/be")


def test_completer_completes_known_arg_values():
    assert [c.text for c in _complete("/effort ")] == ["low", "medium", "high"]
    assert [c.text for c in _complete("/effort hi")] == ["high"]


# ─── fallback sem TTY / sem prompt_toolkit ────────────────────────────────────
def test_supports_interactive_false_without_tty(monkeypatch):
    monkeypatch.setattr(ia.sys, "stdin", type("S", (), {"isatty": staticmethod(lambda: False)})())
    assert ia.supports_interactive() is False


def test_build_session_returns_none_without_tty(monkeypatch):
    monkeypatch.setattr(ia, "supports_interactive", lambda: False)
    assert ia.build_session(object(), COMMANDS, dict) is None


def test_read_prompt_falls_back_to_input(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "olá vincent")

    class A:
        display_model = "qwen3:0.6b"

    assert ia.read_prompt(None, A()) == "olá vincent"


def test_picker_plain_fallback_lists_everything_and_returns_none(monkeypatch, capsys):
    monkeypatch.setattr(ia, "supports_interactive", lambda: False)
    monkeypatch.setattr(ia.sys, "stdin", type("S", (), {"isatty": staticmethod(lambda: False)})())
    items = [{"display_id": f"model-{i:03d}"} for i in range(485)]
    assert ia.FuzzyPicker(items, "catálogo").run() is None
    out = capsys.readouterr().out
    assert "model-484" in out                 # imprimiu TUDO, sem "+N adicionais"
    assert "adicionais" not in out


def test_picker_plain_fallback_reads_number(monkeypatch):
    monkeypatch.setattr(ia, "supports_interactive", lambda: False)
    monkeypatch.setattr(ia.sys, "stdin", type("S", (), {"isatty": staticmethod(lambda: True)})())
    monkeypatch.setattr("builtins.input", lambda prompt="": "3")
    chosen = ia.FuzzyPicker(MODELS, "modelos", group_key=ia.model_group).run()
    assert chosen["display_id"] == "vincent/glm-4-flash"


def test_confirm_permission_without_tty_says_no(monkeypatch):
    monkeypatch.setattr(ia.sys, "stdin", type("S", (), {"isatty": staticmethod(lambda: False)})())
    assert ia.confirm_permission("run_command", "rm -rf /") == "no"


@pytest.mark.parametrize("answer,expected", [
    ("s", "yes"), ("sim", "yes"), ("y", "yes"), ("YES", "yes"),
    ("n", "no"), ("", "no"), ("qualquer", "no"),
    ("a", "always"), ("sempre", "always"), ("ALWAYS", "always"),
])
def test_confirm_permission_answers(monkeypatch, answer, expected):
    tty = type("S", (), {"isatty": staticmethod(lambda: True)})()
    monkeypatch.setattr(ia.sys, "stdin", tty)
    monkeypatch.setattr(ia.sys, "stdout", type("O", (), {
        "isatty": staticmethod(lambda: True),
        "write": staticmethod(lambda *a: None),
        "flush": staticmethod(lambda: None),
    })())
    monkeypatch.setattr("builtins.input", lambda prompt="": answer)
    assert ia.confirm_permission("edit_file", "/etc/passwd") == expected


def test_confirm_permission_eof_says_no(monkeypatch):
    tty = type("S", (), {"isatty": staticmethod(lambda: True)})()
    monkeypatch.setattr(ia.sys, "stdin", tty)
    monkeypatch.setattr(ia.sys, "stdout", type("O", (), {
        "isatty": staticmethod(lambda: True),
        "write": staticmethod(lambda *a: None),
        "flush": staticmethod(lambda: None),
    })())

    def _boom(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", _boom)
    assert ia.confirm_permission("run_command", "") == "no"


# ─── regressões da rodada de revisão ──────────────────────────────────────────
def test_permissao_pedida_de_thread_de_fundo_nao_disputa_o_teclado(session_env, monkeypatch, capsys):
    """/bg e /spawn chamam o permission_callback de uma THREAD enquanto a
    principal está dentro de session.prompt(), com o terminal em raw mode.
    Dois leitores de stdin roubavam as teclas um do outro; agora o pedido
    passa pelo run_in_terminal, que suspende o prompt."""
    import threading
    import time

    from prompt_toolkit.input import create_pipe_input as _pipe_input

    monkeypatch.setattr(ia.sys, "stdin", type("S", (), {"isatty": staticmethod(lambda: True)})())
    onde = []
    monkeypatch.setattr("builtins.input",
                        lambda prompt="": (onde.append(threading.current_thread().name), "s")[1])

    out = {}
    with _pipe_input() as pipe:
        with create_app_session(input=pipe, output=DummyOutput()):
            session = ia.build_session(FakeAgent(), COMMANDS, _status)

            def _worker():
                for _ in range(500):                      # espera o prompt subir
                    if getattr(session.app, "is_running", False):
                        break
                    time.sleep(0.01)
                out["ans"] = ia.confirm_permission("run_bash", "rm -rf /")
                pipe.send_text("continua" + ENTER)        # só então digita a linha

            t = threading.Thread(target=_worker, name="bg-1", daemon=True)
            t.start()
            linha = ia.read_prompt(session, FakeAgent())
            t.join(10)

    assert out["ans"] == "yes"
    assert linha == "continua"                            # a linha não foi corrompida
    assert onde and onde[0] != "bg-1"                     # a pergunta NÃO leu stdin da thread


def test_caixa_de_permissao_alinhada(monkeypatch, capsys):
    """Era meia-caixa: topo com 80 col, base com 78 e o conteúdo sem borda
    direita."""
    import re

    monkeypatch.setattr(ia, "get_terminal_width", lambda: 80)
    monkeypatch.setattr(ia.sys, "stdin", type("S", (), {"isatty": staticmethod(lambda: True)})())
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")

    ia.confirm_permission("run_bash", "echo oi")
    limpo = [re.sub(r"\x1b\[[0-9;]*m", "", l) for l in capsys.readouterr().out.splitlines()]
    caixa = [l for l in limpo if l and l[0] in "╭│╰"]
    assert len(caixa) == 5                                 # topo + 3 linhas + base
    assert all(l.rstrip()[-1] in "╮│╯" for l in caixa)      # todas fecham à direita
    assert len({len(l.rstrip()) for l in caixa}) == 1       # e no mesmo tamanho



def test_supports_interactive_dentro_de_app_session_injetada():
    """As APIs públicas (pick_model/browse_models) precisam ser dirigíveis
    headless — antes só o _run_ptk privado era."""
    assert ia.supports_interactive() is False        # fora do harness, sem TTY
    with keys(""):
        assert ia.supports_interactive() is True


def test_pick_model_dirigivel_headless_sem_monkeypatch():
    with keys(KEY_DOWN + ENTER):
        assert ia.pick_model(FakeAgent()) == "auto/best-coding"


def test_initial_query_deixa_o_cursor_no_fim(force_interactive):
    """'/search qwen' + tecla '3' tem que virar 'qwen3', não '3qwen'."""
    items = [{"display_id": "3-qwen-antigo"}, {"display_id": "qwen3:0.6b"}]
    with keys("3" + ENTER):
        chosen = ia.FuzzyPicker(items, "t", initial_query="qwen").run()
    assert chosen["display_id"] == "qwen3:0.6b"      # com o cursor na coluna 0 vinha '3-qwen-antigo'


def test_busca_com_espaco_faz_AND_dos_termos():
    m = {"display_id": "vincent/claude-opus-5", "name": "Claude Opus 5"}
    assert ia.score_item("claude opus", m) is not None
    assert ia.score_item("claude gemini", m) is None
    # e o ranqueado ganha do que só casa por subsequência espalhada
    espalhado = {"display_id": "auto/pro-reasoning"}
    assert ia.score_item("opus", m) > (ia.score_item("opus", espalhado) or 0)


def test_picker_com_zero_resultados_avisa(force_interactive):
    with keys(ESC):
        picker = ia.FuzzyPicker([{"display_id": "a"}], "t", initial_query="zzzz")
        picker._rebuild("zzzz")
        assert "nenhum resultado" in "".join(t for _, t in picker._render_list())


def test_footer_do_picker_preserva_a_saida_e_a_rolagem():
    picker = ia.FuzzyPicker([{"display_id": f"m{i}"} for i in range(50)], "t")
    picker._rebuild("")
    picker.index = 40
    texto = "".join(t for _, t in picker._render_footer())
    assert "Esc sai" in texto                        # nunca é cortado
    assert "▲" in texto and "▼" in texto             # rolagem visível...
    assert texto.index("▲") < texto.index("Esc")     # ...e não colada no fim da ajuda


@pytest.fixture
def projeto(tmp_path, monkeypatch):
    """Projeto de mentira no cwd, com o índice de menções zerado."""
    (tmp_path / "src" / "vincent").mkdir(parents=True)
    (tmp_path / "src" / "vincent" / "ui.py").write_text("x", encoding="utf-8")
    (tmp_path / "src" / "vincent" / "cli.py").write_text("x", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "ui.pyc").write_text("x", encoding="utf-8")
    (tmp_path / "segredo.log").write_text("x", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("segredo.log\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    ia._mention_cache.clear()
    yield tmp_path
    ia._mention_cache.clear()


def test_completer_completa_caminhos_com_arroba(projeto):
    comps = _complete("olha o @vincent/ui")
    assert comps[0].text == "@src/vincent/ui.py"      # insere a menção inteira
    assert comps[0].start_position == -len("@vincent/ui")
    assert "📄" in "".join(str(t) for _, t in comps[0].display)


def test_arroba_pelado_lista_o_projeto_com_icone_de_diretorio(projeto):
    comps = _complete("@")
    textos = [c.text for c in comps]
    assert "@src/" in textos and "@src/vincent/ui.py" in textos
    dirs = {c.text: "".join(str(t) for _, t in c.display) for c in comps}
    assert "📁" in dirs["@src/"]
    assert [c.display_meta_text for c in comps if c.text == "@src/"] == ["diretório"]


def test_mencoes_ignoram_lixo_e_respeitam_o_gitignore(projeto):
    caminhos = [e["path"] for e in ia.project_files()]
    assert "src/vincent/ui.py" in caminhos
    assert not any("__pycache__" in p for p in caminhos)   # IGNORE_PATTERNS
    if shutil.which("git"):
        subprocess.run(["git", "init", "-q"], cwd=projeto, check=True)
        ia._mention_cache.clear()
        assert "segredo.log" not in [e["path"] for e in ia.project_files()]
    else:                                                   # sem git: fallback
        assert "segredo.log" in caminhos


@pytest.mark.skipif(not shutil.which("git"), reason="precisa de git")
def test_caminho_com_acento_vem_inteiro_do_git(projeto):
    """git ls-files escapa acento entre aspas — o completer inseria caminho morto."""
    (projeto / "src" / "coração.py").write_text("x", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=projeto, check=True)
    ia._mention_cache.clear()
    assert "src/coração.py" in [e["path"] for e in ia.project_files()]

    from vincent.cli import expand_mentions
    texto, notas = expand_mentions("olha o @src/coração.py")
    assert "[arquivo: src/coração.py]" in texto and notas == ["◈ @src/coração.py — 1 linha(s)"]


def test_ranking_de_mencao_faz_AND_e_prefere_caminho_curto(projeto):
    (projeto / "build").mkdir()
    (projeto / "build" / "ui.py").write_text("x", encoding="utf-8")
    ia._mention_cache.clear()
    assert ia.rank_mentions("vincent ui")[0]["path"] == "src/vincent/ui.py"
    assert ia.rank_mentions("naoexistezzz") == []


def test_indice_de_arquivos_e_cacheado(projeto, monkeypatch):
    ia.project_files()
    monkeypatch.setattr(ia, "_git_files", lambda root: (_ for _ in ()).throw(AssertionError("rescan")))
    monkeypatch.setattr(ia, "_walk_files", lambda root: (_ for _ in ()).throw(AssertionError("rescan")))
    assert ia.project_files()                       # veio do cache, não reescaneou


def test_completer_nao_corta_o_catalogo_em_200():
    ids = [f"prov/model-{i}" for i in range(343)]
    c = ia.VincentCompleter(COMMANDS, lambda: ids)
    assert len(_complete("/model model", completer=c)) == 343


def test_menu_da_barra_pelada_segue_a_ordem_do_registro():
    """'/' sozinho ordenava por comprimento (/bg, /act no topo)."""
    assert [c.text for c in _complete("/")] == [c["cmd"] for c in COMMANDS]


def test_sessao_nao_liga_history_search(session_env):
    """enable_history_search desliga o complete_while_typing lá dentro do
    prompt_toolkit: com ela, digitar '/' não abria menu nenhum sem Tab."""
    with keys(""):
        session = ia.build_session(FakeAgent(), COMMANDS, _status)
    assert session.complete_while_typing
    assert not session.enable_history_search
    assert session.complete_in_thread


def test_render_de_modelo_usa_reticencias_e_a_largura_do_terminal(monkeypatch):
    monkeypatch.setattr(ia, "get_terminal_width", lambda: 120)
    row = ia._make_model_renderer(FakeAgent())(
        {"display_id": "vincent/claude-opus-4-5-20251101-high", "name": "", "provider": "vincent-cloud"},
        False,
    )
    assert "-high" in row                            # o sufixo sobrevive
    assert "vincent-cloud" in row                    # coluna direita não fica vazia
    monkeypatch.setattr(ia, "get_terminal_width", lambda: 60)
    curto = ia._make_model_renderer(FakeAgent())(
        {"display_id": "vincent/" + "x" * 80, "name": ""}, False)
    assert "…" in curto


def test_module_imports_without_prompt_toolkit(monkeypatch):
    """Simula a ausência da lib: HAS_PTK=False => tudo degrada, nada estoura."""
    monkeypatch.setattr(ia, "HAS_PTK", False)
    assert ia.supports_interactive() is False
    assert ia.build_session(object(), COMMANDS, dict) is None
