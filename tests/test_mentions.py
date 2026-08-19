"""
Expansão de menções '@arquivo' (src/vincent/cli.py).

Regra pura: entra texto do usuário, sai texto com o conteúdo dos arquivos
citados anexado. Nada de REPL, nada de rede.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vincent.cli import MENTION_MAX_FILES, MENTION_MAX_LINES, expand_mentions


@pytest.fixture
def projeto(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ui.py").write_text("linha 1\nlinha 2\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_anexa_o_conteudo_do_arquivo_citado(projeto):
    texto, notas = expand_mentions("explica o @src/ui.py pra mim")

    assert texto.startswith("explica o @src/ui.py pra mim")   # a frase fica intacta
    assert "linha 2" in texto                                  # e o conteúdo entra
    assert "[arquivo: src/ui.py] 2 linha(s)" in texto
    assert notas == ["◈ @src/ui.py — 2 linha(s)"]


def test_arquivo_grande_e_truncado_avisando_quantas_linhas_cairam(projeto):
    total = MENTION_MAX_LINES + 57
    (projeto / "gigante.txt").write_text("\n".join(f"l{i}" for i in range(total)),
                                         encoding="utf-8")
    texto, notas = expand_mentions("@gigante.txt")

    assert f"l{MENTION_MAX_LINES - 1}" in texto        # última linha que coube
    assert f"l{MENTION_MAX_LINES}" not in texto        # a primeira cortada não veio
    assert f"57 de {total} linhas cortadas" in texto   # o modelo é avisado
    assert notas == [f"◈ @gigante.txt — {MENTION_MAX_LINES}/{total} linhas (57 cortadas)"]


def test_mencao_que_nao_existe_e_email_passam_intactos(projeto):
    texto, notas = expand_mentions("manda pro fulano@gmail.com sobre @naoexiste.py")
    assert texto == "manda pro fulano@gmail.com sobre @naoexiste.py"
    assert notas == []


def test_mencao_repetida_entra_uma_vez_so(projeto):
    texto, notas = expand_mentions("@src/ui.py e de novo @src/ui.py")
    assert texto.count("[arquivo: src/ui.py]") == 1
    assert len(notas) == 1


def test_pontuacao_final_nao_entra_no_caminho(projeto):
    texto, _ = expand_mentions("olha o @src/ui.py, por favor")
    assert "[arquivo: src/ui.py]" in texto


def test_diretorio_citado_vira_listagem(projeto):
    texto, notas = expand_mentions("o que tem em @src ?")
    assert "[diretório: src]" in texto
    assert "📄 ui.py" in texto
    assert notas == ["◈ @src/ — 1 entrada(s)"]


def test_binario_nao_e_anexado(projeto):
    (projeto / "foto.png").write_bytes(b"\x89PNG\x00\x00blob")
    texto, notas = expand_mentions("@foto.png")
    assert "Conteúdo dos arquivos citados" not in texto
    assert notas == ["✗ @foto.png: arquivo binário, não anexado"]


def test_limite_de_arquivos_por_mensagem(projeto):
    nomes = []
    for i in range(MENTION_MAX_FILES + 2):
        (projeto / f"f{i}.txt").write_text("x", encoding="utf-8")
        nomes.append(f"@f{i}.txt")
    texto, notas = expand_mentions(" ".join(nomes))

    assert texto.count("[arquivo:") == MENTION_MAX_FILES
    assert sum(1 for n in notas if n.startswith("⚠")) == 2


def test_caminho_absoluto_e_til_funcionam(projeto, monkeypatch):
    monkeypatch.setenv("HOME", str(projeto))
    texto, _ = expand_mentions(f"@{projeto / 'src' / 'ui.py'} e @~/src/ui.py")
    assert texto.count("linha 2") == 2
