# Vincent

Orquestrador neural de IA (OmniRoute + Ollama local) e laboratório de hardware ESP32 (T-Embed CC1101, ESP32DIV).

## Instalação

Este diretório é o pacote Python `vincent` — precisa estar acessível via `PYTHONPATH` a partir do diretório pai:

```bash
git clone <este-repo> vincent
export PYTHONPATH="$(dirname "$(pwd)/vincent")"
python3 -m vincent.cli
```

Ou use o launcher em `~/.local/bin/vincent`:

```bash
#!/usr/bin/env bash
export PYTHONPATH="/caminho/para/IA_e_LLMs:${PYTHONPATH}"
exec python3 -m vincent.cli "$@"
```

Dependências: apenas stdlib (`urllib`, `json`, `argparse`) — sem pip install necessário.

## Uso

```bash
vincent                          # REPL interativo
vincent "pergunta direta"        # modo one-shot
vincent -l                       # lista catálogo de modelos
vincent -p ponytail "..."        # ativa plugin/skill por nome
```

Comandos do REPL: `/models`, `/model <id>`, `/plugins`, `/plugin <nome>`, `/caveman <modo>`, `/gsd <tarefa>`, `/devices`, `/cmd <dev> <cmd>`, `/stats`, `/help`.

## Backends de IA

1. **Ollama local** (`OLLAMA_HOST`, padrão `127.0.0.1:11434`) — zero-key, offline.
2. **OmniRoute** (`OMNIROUTE_URL`, padrão `localhost:20128/v1`) — proxy local pra 1200+ modelos/rotas, muitas gratuitas.

## Plugins

Descobre skills em `~/.agents/skills/**/SKILL.md` e injeta as ativas no system prompt. Ver `/plugins` no REPL.

## Status

Empacotamento pip real (Termux/Windows/instalação universal) ainda não feito — o layout atual depende de `PYTHONPATH` apontando pro diretório pai. Restruturar pra `pyproject.toml` + `pip install` funcional é trabalho futuro (precisa mover pra layout `src/`, auditar paths Linux-only em `devices.py`, e validar ANSI colors em terminal Windows).
