"""
Regras de despacho de entrada do REPL (src/vincent/cli.py).

Sem harness de REPL: `normalize_bare_command` é a regra pura que decide se
uma linha digitada vira comando ou continua sendo conversa.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from vincent.cli import BARE_COMMAND_ALIASES, normalize_bare_command


@pytest.mark.parametrize("linha,esperado", [
    ("models", "/models"),
    ("MODELS", "/MODELS"),        # o dispatch já compara em minúsculas
    ("  help  ", "/help"),
    ("exit", "/exit"),
])
def test_apelido_sem_barra_vira_comando(linha, esperado):
    assert normalize_bare_command(linha) == esperado


@pytest.mark.parametrize("frase", [
    "auto conserta o bug do login",     # disparava o modo autônomo de 40 passos
    "store os dados no banco",
    "reload the page please",
    "help me with this function",
    "effort dobrado na revisão",
])
def test_frase_de_chat_que_comeca_com_palavra_de_comando_continua_chat(frase):
    assert normalize_bare_command(frase) == frase


def test_linha_com_barra_passa_intacta():
    assert normalize_bare_command("/act conserta o login") == "/act conserta o login"


def test_palavras_comuns_de_prosa_estao_mesmo_no_set():
    """Se estas saírem do registro, o teste acima vira falso verde."""
    assert {"auto", "store", "reload"} <= BARE_COMMAND_ALIASES
