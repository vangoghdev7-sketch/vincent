# Vincent CLI — instruções do projeto

## Regra do motor único (não violar)

Vincent é um motor de raciocínio ÚNICO e generalista. É proibido no código do
**produto** (`src/vincent/**`) qualquer persona, role, squad, ou orchestrator
que finja múltiplos agentes especialistas ("Vincent-Coder", "Vincent-Auditor",
system prompt dizendo "você é especialista em X"). Esse conceito existiu (GSD
Swarm) e foi removido de propósito: era um único `agent.ask()` fingindo
personas no texto, sem orquestração real por trás.

Paralelismo real (`spawn_workers`, `/spawn`, `/bg`) é permitido e já existe —
a regra é sobre personas fictícias no *raciocínio*, não sobre concorrência de
verdade na *execução*.

Subagentes de build (`.claude/agents/*.md`) são ferramenta de desenvolvimento
deste repositório, não do produto — não contam pra essa regra.

## Política de teste

Esta máquina é fraca e sobrecarrega fácil (Ollama já mediu load 18-32 e
timeout com múltiplos modelos carregados ao mesmo tempo — não é hipotético,
já aconteceu nesta sessão). Por isso:

- **Permitido e obrigatório** antes de qualquer commit: `python3 -m py_compile`
  em todo arquivo tocado, import de cada módulo mudado, testes de lógica pura
  com `pytest` (LLM/rede sempre mockados via `unittest.mock`).
- **Evitar**: chamada de LLM real (local ou cloud) só pra "confirmar rapidinho"
  — isso trava a máquina e não prova nada que um teste mockado não prove
  melhor. Quando uma mudança genuinamente precisa de validação ao vivo (ex:
  UI interativa como curses), teste via mecanismo determinístico (pty real
  com teclas simuladas), não uma chamada de LLM solta.
- Documente em `docs/TESTPLAN.md` os passos que só dá pra confirmar com
  hardware/rede reais (ex: hardware ESP32, modelo de visão específico).

## Convenções de commit

Conventional Commits (`feat`, `fix`, `chore`, `refactor`, `docs`), escopo
entre parênteses quando fizer sentido. Mensagem explica o porquê, não narra
o diff linha a linha. Sem `Co-Authored-By`. `git add` por nome de arquivo
explícito, nunca `-A`/`.` às cegas.

## Estrutura de `src/vincent`

- `cli.py` — REPL + argparse, dispatcher de comandos `/foo`
- `agent.py` — `VincentAgent`: inferência, agentic loop, auto-cura, workers
- `agent_tools.py` — arsenal de tools (list_dir, read_file, grep_search,
  run_bash, apply_diff, git_status/diff/commit/rollback, web_search/fetch_url)
- `routing/resilience.py`, `routing/strategies.py` — circuit breaker,
  cooldown, lockout e estratégias de seleção pra cascata de modelos
- `models.py` — `ModelManager`: OmniRoute + Ollama, cascata de failover,
  `mask()` de whitelabel, visão multimodal
- `memory.py` — SQLite (`~/.vincent/brain.db`), memória de sessão persistente
- `auth.py` — key vault local (`~/.vincent/credentials.json`, chmod 0600)
- `mcp_server.py` — servidor MCP (stdio/socket)
- `tui_config.py` — painel de configuração interativo (curses)
- `skills.py` — skills sob demanda (`~/.vincent/skills/<nome>/SKILL.md`)
- `ui.py` — paleta, banner, HUD, spinner

## Paleta ANSI oficial (`src/vincent/ui.py`)

| Nome | Código 256 | Hex aproximado | Uso |
|---|---|---|---|
| `COBALT_BLUE` | `\033[38;5;33m` | `#0087ff` | cor primária de destaque |
| `PRUSSIAN_BLUE` | `\033[38;5;25m` | `#005fd7` | azul escuro do banner |
| `LEMON_YELLOW` | `\033[38;5;226m` | `#ffff00` | destaque forte |
| `CHROME_YELLOW` | `\033[38;5;220m` | `#ffd700` | prompts interativos |
| `STARRY_GOLD` | `\033[38;5;214m` | `#ffaf00` | cards de HUD |
| `CYPRESS_GREEN` | `\033[38;5;48m` | `#00ff87` | sucesso |
| `VIOLET_SWIRL` | `\033[38;5;141m` | `#af87ff` | spinners/agentic loop |
| `ALERT_SCARLET` | `\033[38;5;196m` | `#ff0000` | erro |
| `CANVAS_WHITE` | `\033[38;5;254m` | `#e4e4e4` | texto normal |
| `SHADOW_GRAY` | `\033[38;5;242m` | `#6c6c6c` | texto secundário/uso |

Sempre importar de `vincent.ui`, nunca hardcodar `\033[...]` direto em outro
módulo.
