---
name: vincent-conventions
description: Convenções do projeto Vincent CLI — paleta ANSI oficial, padrão de commit, estrutura de src/vincent, e a regra do motor único generalista. Use ao editar código deste repositório.
---

# Convenções do Vincent CLI

## Regra do motor único (não violar)

Vincent é um motor de raciocínio ÚNICO e generalista. É proibido no código do
**produto** (`src/vincent/**`) qualquer persona, role, squad, ou orchestrator
que finja múltiplos agentes especialistas ("Vincent-Coder", "Vincent-Auditor",
"você é especialista em X" em system prompt, etc). Esse conceito existiu
(GSD Swarm) e foi removido de propósito: era um único `agent.ask()` fingindo
personas no texto, sem orquestração real por trás.

Paralelismo e especialização real (múltiplos subagentes de verdade,
`.claude/agents/*.md`) são ferramenta de BUILD deste repositório — não vazam
pro produto.

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

## Estrutura de `src/vincent`

- `cli.py` — REPL + argparse, dispatcher de comandos `/foo`
- `agent.py` — `VincentAgent`: inferência, agentic loop (`agentic_run`), auto-cura
- `agent_tools.py` — arsenal de tools do agentic loop (list_dir, read_file,
  grep_search, run_bash, apply_diff, git_status/diff/commit/rollback,
  web_search/fetch_url)
- `models.py` — `ModelManager`/OmniRoute + Ollama, cascata de failover, `mask()`
  pra whitelabel de rota upstream, `build_image_content()`/vision
- `memory.py` — SQLite em `~/.vincent/brain.db`, resumo de sessão persistente
- `auth.py` — key vault local (`~/.vincent/credentials.json`, chmod 0600)
- `mcp_server.py` — servidor MCP (stdio/socket)
- `ui.py` — paleta, banner, HUD, spinner
- `caveman.py`, `telemetry.py`, `plugins.py`, `devices.py`, `llama_factory.py`,
  `env_detect.py`

## Padrão de commit

Conventional Commits (`feat`, `fix`, `chore`, `refactor`, `docs`), escopo
entre parênteses quando fizer sentido (`feat(agent): ...`, `fix(auth): ...`).
Mensagem explica o porquê, não narra o diff linha a linha. Sem
`Co-Authored-By` (não configurado neste projeto). Sempre `git add` por nome
de arquivo explícito, nunca `-A`/`.` às cegas.

## Antes de afirmar que algo funciona

Rodar `python3 -m py_compile` no arquivo editado é o mínimo. Pra tools novas
do agentic loop, chamar `execute_agent_tool` direto num teste ad-hoc antes de
reportar como pronto — este projeto já teve um bug em produção
(`total_saved` vs `total_tokens_saved`) por código que só foi checado
visualmente, nunca executado.
