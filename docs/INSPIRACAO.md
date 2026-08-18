# Inspiração — Antigravity CLI / OpenCode / obsidian-skills

Levantamento feito neste PC (não é código-fonte deles — nenhum dos dois é
open-source completo aqui — é comportamento observado ao vivo). Sem cópia
literal de código, só ideia.

## Antigravity CLI (`agy`, Google)

Binário real em `~/.local/bin/agy` (206MB, stripped, closed-source). Dados
de sessão em `~/.gemini/antigravity-cli/`. `agy --help` real:

```
--model / --agent / --mode (accept-edits|plan) / --effort (low|medium|high)
--continue / -c / --conversation <id>        → retoma sessão
--output-format (text|json|stream-json) / --input-format (stream-json)
--add-dir (repetível)                        → multi-workspace
--dangerously-skip-permissions / --sandbox
subcomandos: agent/agents, models, plugin/plugins, changelog, update, install
```

**O que fazem melhor:** nenhuma barreira `/comando` para agir — é tudo uma
sessão de agente contínua; flags não-interativas para tudo (`--model`,
config, `--print`); `--mode plan` vs `accept-edits` como controle de
autonomia em vez de pedir confirmação a cada ação.

**O que eu porto:** a ideia central de "chat = execução" (Parte 1). O
`--mode plan|accept-edits` deles é essencialmente o gate que o Vincent já
tinha como bloqueio de comando perigoso (`agent_tools.py`) — mantive esse,
não portei um segundo modo "plan" ainda (YAGNI: ninguém pediu dry-run).

**O que NÃO porto agora:** `--output-format stream-json` (scripting
avançado, ninguém pediu), `--sandbox` de verdade (precisaria de
bwrap/firejail, mais infra que o pedido cobre agora).

## OpenCode

Sem instalação/binário neste PC. Formato real do plugin/skill dele,
recuperado de integrações de terceiros já instaladas aqui (caveman,
ponytail):

```
opencode.json (raiz do projeto):
  { "plugin": ["./.opencode/plugins/x.mjs"] }

.opencode/command/<nome>.md:
  ---
  description: ...
  ---
  corpo com $ARGUMENTS

Hooks reais: event (session.created), chat.message,
experimental.chat.system.transform
Config dir: $XDG_CONFIG_HOME/opencode ou ~/.config/opencode
```

**O que fazem melhor:** skill/comando é um arquivo markdown solto, sem
precisar editar Python — qualquer um adiciona um comando novo largando um
`.md` na pasta certa.

**O que eu porto (Parte 3):** exatamente esse formato — pasta com
`SKILL.md` + frontmatter simples (`name`, `description`), carregado sob
demanda. `~/.vincent/skills/<nome>/SKILL.md`.

**O que NÃO porto:** o sistema de hooks JS/Bun inteiro (plugin.js com
`event`/`chat.message`/etc.) — reimplementar um dispatcher de hooks em
Python pra um projeto de 1 usuário é abstração sem necessidade agora.

## kepano/obsidian-skills

Repo real (`github.com/kepano/obsidian-skills`), confirmado via fetch: é
uma coleção de **Claude Agent Skills** (`skills/<nome>/SKILL.md` +
frontmatter) para formatos do Obsidian — markdown flavor, Bases, JSON
Canvas, Obsidian CLI, extração de página web (`defuddle`).

**O que eu porto:** não o conteúdo (é sobre Obsidian, Vincent não é), mas a
confirmação de que o FORMATO SKILL.md é o mesmo padrão do OpenCode — reforça
que vale a pena implementar um único loader de skills (Parte 3) compatível
com os dois. Depois de implementado, dá pra rodar
`/skill add https://github.com/kepano/obsidian-skills` e puxar a skill de
markdown do Obsidian de verdade, já que o usuário confirmou que usa vault
Obsidian como base de conhecimento.

## Decisão de arquitetura mantida

Motor único e generalista continua — nenhuma das três inspirações usa
"agente especialista por persona" no motor de raciocínio em si; multi-agent
neles é paralelismo de execução (workers), não personas. Isso já era a regra
do projeto (`SYSTEM_BASE` em `agent.py`: "Motor único e generalista") — não
mudou, só ganhou mais um caminho de execução (Parte 1) e paralelismo real
(Parte 2, pendente).
