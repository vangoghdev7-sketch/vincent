# Vincent

Orquestrador neural de IA (OmniRoute + Ollama local) e laboratório de hardware ESP32 (T-Embed CC1101, ESP32DIV).

## Instalação

Pacote Python real (`pyproject.toml`, layout `src/`). Funciona em Linux, macOS, Windows e Termux (Android).

**Recomendado — [pipx](https://pipx.pypa.io/) (isola dependências, não precisa de venv manual):**

```bash
pipx install git+https://github.com/vangoghdev7-sketch/vincent
# ou, a partir de um clone local:
git clone https://github.com/vangoghdev7-sketch/vincent
pipx install --editable ./vincent
```

**Alternativa — pip direto (venv recomendado; em Termux não há restrição PEP 668):**

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install .
```

Isso cria o comando `vincent` disponível globalmente. Dependências: `pyserial` (hardware USB-serial), `psutil` (telemetria de CPU/RAM) — resolvidas automaticamente.

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

## Hardware (opcional)

Detecção de placas USB-serial (T-Embed CC1101, ESP32DIV) via `pyserial.tools.list_ports` — funciona nativamente em Linux (`/dev/ttyACM*`), Windows (`COM*`) e macOS (`/dev/cu.*`). Sem placa conectada, o Vincent funciona normalmente só como cliente de IA.

## Plugins

Descobre skills em `~/.agents/skills/*/` (procura `SKILL.md` ou `README.md`) e injeta as ativas no system prompt. Ver `/plugins` no REPL.

## Estrutura

```
src/vincent/     pacote instalável (agent, cli, devices, models, plugins, ...)
pyproject.toml   empacotamento (setuptools, entry point `vincent`)
```
