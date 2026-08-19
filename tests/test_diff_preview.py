"""
Preview de diff ANTES de aplicar a edição (a peça que faltava pro nível Claude Code):

- `vincent.agent_tools.build_edit_preview` — o que a edição VAI mudar, sem tocar no disco
- `vincent.ui.diff_lines` / `colorize_diff_line` — nº de linha, contexto e verde/vermelho
- integração no loop agêntico (`agentic_run`) e no prompt de permissão do REPL
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from vincent import ui
from vincent.agent_tools import build_edit_preview, is_edit_tool, tool_apply_diff
from vincent.ui import colorize_diff_line, diff_lines


ARQUIVO = "def alfa():\n    return 1\n\n\ndef beta():\n    return 2\n"


@pytest.fixture
def arquivo(tmp_path):
    p = tmp_path / "modulo.py"
    p.write_text(ARQUIVO, encoding="utf-8")
    return p


# ── build_edit_preview ────────────────────────────────────────────────────────

def test_preview_de_search_replace_mostra_a_mudanca(arquivo):
    diff = build_edit_preview("apply_diff", {
        "path": str(arquivo),
        "search_block": "    return 1",
        "replace_block": "    return 42",
    })
    assert "-    return 1" in diff
    assert "+    return 42" in diff
    assert diff.startswith("--- a/modulo.py")


def test_preview_nao_escreve_no_disco(arquivo):
    build_edit_preview("apply_diff", {
        "path": str(arquivo), "search_block": "    return 1", "replace_block": "    return 42",
    })
    assert arquivo.read_text(encoding="utf-8") == ARQUIVO


def test_preview_bate_com_o_que_a_ferramenta_aplica(arquivo):
    """O diff mostrado é exatamente a edição que vai pro disco — não uma aproximação."""
    args = {"path": str(arquivo), "search_block": "    return 2", "replace_block": "    return 99"}
    diff = build_edit_preview("apply_diff", args)
    assert tool_apply_diff(**args)["success"] is True
    depois = arquivo.read_text(encoding="utf-8")
    aplicado = ARQUIVO.replace("    return 2", "    return 99")
    assert depois == aplicado
    assert "+    return 99" in diff


def test_preview_aceita_diff_unificado_cru_do_modelo(arquivo):
    cru = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-velho\n+novo\n"
    assert build_edit_preview("patch", {"path": str(arquivo), "diff": cru}) == cru
    # 'diff_content' é o nome do parâmetro na própria ferramenta — mesmo preview
    assert build_edit_preview("patch", {"path": str(arquivo), "diff_content": cru}) == cru


def test_diff_content_previsto_e_o_diff_content_aplicado(arquivo):
    """Preview e execução leem as MESMAS chaves: sem promessa que não vai pro disco."""
    from vincent.agent_tools import execute_agent_tool

    cru = "--- a/modulo.py\n+++ b/modulo.py\n@@ -1,2 +1,2 @@\n def alfa():\n-    return 1\n+    return 42\n"
    args = {"path": str(arquivo), "diff_content": cru}
    assert build_edit_preview("apply_diff", args) == cru
    res = execute_agent_tool("apply_diff", args)
    assert "insuficientes" not in str(res.get("error") or "")


@pytest.mark.parametrize("nome, args", [
    ("run_bash", {"command": "ls"}),                       # não é edição
    ("git_commit", {"message": "x"}),                      # não é edição
    ("apply_diff", {"path": "/nao/existe.py", "search_block": "a", "replace_block": "b"}),
    ("apply_diff", {"path": "__ARQUIVO__", "search_block": "inexistente", "replace_block": "b"}),
    ("apply_diff", {"path": "__ARQUIVO__", "search_block": "    return 1", "replace_block": "    return 1"}),
    ("apply_diff", {"path": "__ARQUIVO__"}),               # sem blocos
])
def test_preview_vazio_quando_nao_da_pra_prever(arquivo, nome, args):
    args = {k: (str(arquivo) if v == "__ARQUIVO__" else v) for k, v in args.items()}
    assert build_edit_preview(nome, args) == ""


def test_preview_ignora_args_invalidos():
    assert build_edit_preview("apply_diff", None) == ""
    assert build_edit_preview(None, {}) == ""


def test_is_edit_tool_cobre_os_apelidos():
    assert is_edit_tool("apply_diff") and is_edit_tool("PATCH") and is_edit_tool(" replace ")
    assert not is_edit_tool("run_bash") and not is_edit_tool("") and not is_edit_tool(None)


def test_preview_de_arquivo_sem_quebra_de_linha_final(tmp_path):
    """Sem newline no fim, duas linhas do diff não podem grudar numa só."""
    p = tmp_path / "sem_nl.txt"
    p.write_text("alfa\nbeta", encoding="utf-8")
    linhas = build_edit_preview("apply_diff", {
        "path": str(p), "search_block": "beta", "replace_block": "gama",
    }).splitlines()
    assert "-beta" in linhas and "+gama" in linhas


# ── diff_lines ────────────────────────────────────────────────────────────────

def test_diff_lines_numera_e_marca_contexto(arquivo):
    linhas = diff_lines(build_edit_preview("apply_diff", {
        "path": str(arquivo), "search_block": "    return 2", "replace_block": "    return 99",
    }), title="modulo.py")

    assert linhas[0] == "◆ modulo.py · +1 −1"
    assert any(l.startswith("@@") for l in linhas)
    # linha 6 do arquivo é o "return 2" — o gutter tem que dizer isso
    assert "-     6 │     return 2" in linhas
    assert "+     6 │     return 99" in linhas
    # contexto vem marcado com '·' e também numerado
    assert "·     5 │ def beta():" in linhas
    # cabeçalhos ---/+++ do unified diff não poluem a tela
    assert not any(l.startswith(("---", "+++")) for l in linhas)


def test_diff_lines_vazio_quando_nao_ha_mudanca():
    assert diff_lines("") == []
    assert diff_lines(None) == []
    assert diff_lines("--- a/x\n+++ b/x\n@@ -1 +1 @@\n contexto puro") == []


def test_diff_lines_trunca_diff_gigante():
    corpo = "".join(f"+linha {i}\n" for i in range(500))
    linhas = diff_lines("--- a/x\n+++ b/x\n@@ -1,0 +1,500 @@\n" + corpo, max_lines=20)
    assert len(linhas) == 22          # cabeçalho + 20 linhas + aviso de corte
    assert "mais 481 linha(s)" in linhas[-1]
    assert linhas[0] == "◆ edição · +500 −0"


def test_diff_lines_corta_linha_absurdamente_longa():
    longa = "x" * 900
    linhas = diff_lines(f"@@ -1 +1 @@\n+{longa}")
    assert len(linhas[-1]) < 250 and linhas[-1].endswith("…")


def test_diff_lines_sem_hunk_nao_inventa_numero():
    linhas = diff_lines("+solta\n-outra")
    assert linhas[1] == "+       │ solta"
    assert linhas[2] == "-       │ outra"


# ── colorize_diff_line ────────────────────────────────────────────────────────

def test_colorize_usa_a_paleta_noite_estrelada():
    assert colorize_diff_line("+ 1 │ novo") == f"{ui.CYPRESS_GREEN}+ 1 │ novo{ui.CLR_RST}"
    assert colorize_diff_line("- 1 │ velho") == f"{ui.ALERT_SCARLET}- 1 │ velho{ui.CLR_RST}"
    assert colorize_diff_line("· 1 │ ctx") == f"{ui.SHADOW_GRAY}· 1 │ ctx{ui.CLR_RST}"
    assert colorize_diff_line("@@ -1 +1 @@") == f"{ui.COBALT_BLUE}@@ -1 +1 @@{ui.CLR_RST}"
    assert colorize_diff_line("◆ x.py · +1 −0").startswith(ui.CHROME_YELLOW)


def test_colorize_devolve_none_fora_do_diff():
    assert colorize_diff_line("⚙️  apply_diff  ›  x.py") is None
    assert colorize_diff_line("") is None


def test_style_trace_do_repl_colore_diff():
    from vincent.cli import _style_trace
    assert _style_trace("+ 1 │ novo") == colorize_diff_line("+ 1 │ novo")
    assert _style_trace("🧠 pensando") != colorize_diff_line("+ 1 │ novo")


# ── Loop agêntico ─────────────────────────────────────────────────────────────

def _inferencia_que_edita(arquivo):
    """Turno 1: emite tool_call de apply_diff. Turno 2: responde em texto."""
    chamadas = {"n": 0}

    def _exec(messages, target_model=None, system_prompt=None, stream_callback=None):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            bloco = (
                '```tool_call\n{"tool": "apply_diff", "args": {"path": "%s", '
                '"search_block": "    return 1", "replace_block": "    return 42"}}\n```'
                % str(arquivo)
            )
            return bloco, "fake", 0.1
        return "Pronto, troquei o retorno.", "fake", 0.1

    return _exec


def test_agentic_run_mostra_diff_antes_de_aplicar(agent_factory, arquivo):
    agent, _, _ = agent_factory(execute_inference=_inferencia_que_edita(arquivo))
    passos = []
    agent.agentic_run("troca o retorno", on_step_callback=passos.append, max_turns=3)

    diff = [p for p in passos if p[:2] in ("◆ ", "@@", "+ ", "- ", "· ")]
    assert diff, f"nenhuma linha de diff no trace: {passos}"
    assert any(p.startswith("+") and "return 42" in p for p in diff)
    assert any(p.startswith("-") and "return 1" in p for p in diff)
    # e o preview veio ANTES da edição de fato
    assert passos.index(diff[0]) < passos.index(next(p for p in passos if p.startswith("   ↳")))
    assert "return 42" in arquivo.read_text(encoding="utf-8")


def test_agentic_run_pergunta_com_diff_e_nao_duplica_no_trace(agent_factory, arquivo):
    """Com autoedit off quem mostra o diff é o prompt de permissão — sem eco no trace."""
    agent, _, _ = agent_factory(execute_inference=_inferencia_que_edita(arquivo))
    agent.autoedit = False
    perguntas = []

    def _nega(tool_name, args):
        perguntas.append((tool_name, args))
        return False

    agent.permission_callback = _nega
    passos = []
    agent.agentic_run("troca o retorno", on_step_callback=passos.append, max_turns=3)

    assert perguntas and perguntas[0][0] == "apply_diff"
    assert not [p for p in passos if p[:2] in ("◆ ", "@@", "+ ", "- ", "· ")]
    assert arquivo.read_text(encoding="utf-8") == ARQUIVO  # negado = nada escrito
    # quem pergunta consegue montar o diff a partir dos args recebidos
    assert diff_lines(build_edit_preview(*perguntas[0]))


def test_agentic_run_sem_callback_de_permissao_ainda_mostra_o_diff(agent_factory, arquivo):
    """autoedit off mas nenhum front-end pra perguntar: melhor mostrar do que sumir."""
    agent, _, _ = agent_factory(execute_inference=_inferencia_que_edita(arquivo))
    agent.autoedit = False
    agent.permission_callback = None
    passos = []
    agent.agentic_run("troca o retorno", on_step_callback=passos.append, max_turns=3)
    assert [p for p in passos if p.startswith("+ ")]


def test_agentic_run_nao_quebra_se_o_preview_falhar(agent_factory, arquivo, monkeypatch):
    import vincent.agent as agent_mod
    monkeypatch.setattr(agent_mod, "build_edit_preview", lambda *a, **k: 1 / 0)
    agent, _, _ = agent_factory(execute_inference=_inferencia_que_edita(arquivo))
    passos = []
    resposta = agent.agentic_run("troca o retorno", on_step_callback=passos.append, max_turns=3)
    assert "return 42" in arquivo.read_text(encoding="utf-8")
    assert resposta


# ── Prompt de permissão do REPL ───────────────────────────────────────────────

def test_permission_box_imprime_o_diff_acima_da_pergunta(capsys, monkeypatch):
    from vincent import interactive
    monkeypatch.setattr("builtins.input", lambda *a, **k: "s")
    linhas = ["◆ modulo.py · +1 −1", "@@ -1 +1 @@", "-     1 │ velho", "+     1 │ novo"]

    assert interactive._permission_box("apply_diff", "modulo.py", linhas) == "yes"
    out = capsys.readouterr().out
    for l in linhas:
        assert l in out
    assert out.index("+     1 │ novo") < out.index("PERMISSÃO SOLICITADA")


def test_permission_box_sem_diff_continua_como_antes(capsys, monkeypatch):
    from vincent import interactive
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")
    assert interactive._permission_box("run_bash", "ls -la") == "no"
    out = capsys.readouterr().out
    assert "PERMISSÃO SOLICITADA" in out and "ls -la" in out


def test_confirm_permission_repassa_o_diff(monkeypatch):
    from vincent import interactive
    visto = {}
    monkeypatch.setattr(interactive.sys.stdin, "isatty", lambda: True, raising=False)
    def _falso_box(tool, prev, diff=None):
        visto["diff"] = diff
        return "yes"

    monkeypatch.setattr(interactive, "_permission_box", _falso_box)
    assert interactive.confirm_permission("apply_diff", "x.py", ["◆ x.py · +1 −0"]) == "yes"
    assert visto["diff"] == ["◆ x.py · +1 −0"]


def test_preview_vazio_quando_o_bloco_e_ambiguo(tmp_path):
    """Bloco repetido: a ferramenta recusa a edição, então não pode haver preview
    prometendo uma mudança que nunca vai pro disco."""
    p = tmp_path / "dup.py"
    p.write_text("x = 1\ny = 0\nx = 1\n", encoding="utf-8")
    args = {"path": str(p), "search_block": "x = 1", "replace_block": "x = 2"}

    assert build_edit_preview("apply_diff", args) == ""
    assert tool_apply_diff(**args)["success"] is False
    assert p.read_text(encoding="utf-8") == "x = 1\ny = 0\nx = 1\n"


# ── Modo texto puro (sem prompt_toolkit) e one-shot ───────────────────────────

def test_permissao_modo_texto_aceita_sempre(capsys, monkeypatch, arquivo):
    """Sem prompt_toolkit o 'sempre' também existe — e o diff sai colorido antes."""
    from vincent import cli

    monkeypatch.setattr(cli, "_HAS_INTERACTIVE", False)
    respostas = iter(["a", "n"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(respostas))

    ask = cli.make_permission_asker()
    args = {"path": str(arquivo), "search_block": "    return 1", "replace_block": "    return 42"}

    assert ask("apply_diff", args) is True                 # "a" = sempre
    out = capsys.readouterr().out
    limpo = ui.strip_ansi(out)
    assert "+     2 │     return 42" in limpo              # viu o diff antes de aprovar
    assert "-     2 │     return 1" in limpo
    assert ui.CYPRESS_GREEN in out and ui.ALERT_SCARLET in out
    assert "liberada nesta sessão" in limpo

    assert ask("apply_diff", args) is True                 # não pergunta de novo
    liberado = ui.strip_ansi(capsys.readouterr().out)
    assert "+     2 │     return 42" in liberado           # "sempre" ≠ aprovação às cegas
    assert "-     2 │     return 1" in liberado

    assert ask("run_bash", {"command": "rm -rf /"}) is False    # outra ferramenta: "n"


def test_permissao_modo_texto_nega_por_padrao(capsys, monkeypatch, arquivo):
    from vincent import cli
    monkeypatch.setattr(cli, "_HAS_INTERACTIVE", False)
    pergunta = []
    monkeypatch.setattr("builtins.input", lambda prompt="": (pergunta.append(prompt), "")[1])
    assert cli.make_permission_asker()("apply_diff", {"path": str(arquivo)}) is False
    assert "s = sim / N = não / a = sempre" in ui.strip_ansi(pergunta[0])


def test_permissao_modo_texto_nega_sem_stdin(monkeypatch, arquivo):
    """Ctrl-D / pipe fechado no meio da pergunta = negar, não estourar."""
    from vincent import cli
    monkeypatch.setattr(cli, "_HAS_INTERACTIVE", False)
    def _boom(*a, **k):
        raise EOFError
    monkeypatch.setattr("builtins.input", _boom)
    assert cli.make_permission_asker()("apply_diff", {"path": str(arquivo)}) is False


def test_spinner_step_persiste_diff_e_atualiza_o_resto():
    """One-shot (`vincent --agent`): diff vai pro log persistente, resto pro spinner."""
    from vincent.cli import _spinner_step

    class _Spy:
        def __init__(self):
            self.logs, self.msgs = [], []
        def log(self, m): self.logs.append(m)
        def update_message(self, m): self.msgs.append(m)

    spy = _Spy()
    on_step = _spinner_step(spy)
    on_step("🧠 Passo 1/8 — pensando…")
    on_step("◆ x.py · +1 −1")
    on_step("+     1 │ novo")
    on_step("   ↳ ok")

    assert len(spy.logs) == 2 and all(ui.CLR_RST in l for l in spy.logs)
    assert ui.CYPRESS_GREEN in spy.logs[1]
    assert spy.msgs == ["Vincent: 🧠 Passo 1/8 — pensando…", "Vincent:    ↳ ok"]
