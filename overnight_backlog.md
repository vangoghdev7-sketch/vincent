# Backlog do loop noturno — Vincent rumo a CLI completo

Consumido de cima pra baixo por `overnight.py`. Cada linha `- [ ]` é UM ciclo do Claude em modo
agente, com portão de testes e commit próprio. `- [x]` = feito, `- [~]` = tentou e falhou.

Ordenado por **quanto a falta incomoda no primeiro minuto de uso**, comparando com Claude Code CLI,
GitHub Copilot CLI, OpenCode e Kimi Code.

---

- [ ] Menções a arquivo com `@`: digitar `@` no prompt abre autocomplete de caminhos do projeto (fuzzy, respeitando .gitignore, mostrando ícone de diretório/arquivo) e, ao enviar, o conteúdo dos arquivos citados entra no contexto da mensagem. É a feature mais usada do Claude Code e do Copilot CLI. Implementar o completer em interactive.py, a expansão em cli.py, e limitar o tamanho injetado (truncar arquivo grande avisando quantas linhas foram cortadas).

- [~] Preview de diff antes de aplicar edição: quando o loop agêntico for escrever/alterar arquivo (tools de escrita em agent_tools.py), renderizar um diff unificado COLORIDO (verde/vermelho, com número de linha e contexto) e, se `agent.autoedit` estiver off, perguntar aprovar/rejeitar/sempre. Hoje o usuário aprova às cegas, sem ver o que muda — é a diferença mais gritante pro Claude Code.  <!-- falhou: claude falhou 2x (rc=1) -->

- [ ] `/undo`: desfazer a última alteração feita pelo agente. Antes de cada tool de escrita, gravar um checkpoint (git stash-like próprio ou cópia em ~/.vincent/undo/) e permitir reverter arquivo por arquivo ou tudo. Mostrar o que seria desfeito antes de confirmar.

- [ ] Sessões persistentes: `/sessions` lista as conversas anteriores (data, modelo, primeira pergunta, nº de turnos) num picker navegável, e `/resume [id]` restaura o histórico da conversa escolhida no agente. Persistir em ~/.vincent/sessions/*.json a cada turno, com rotação (manter as 100 mais recentes). Claude Code tem `--resume` e o usuário perde todo o contexto ao fechar o terminal hoje.

- [ ] `/doctor`: diagnóstico do ambiente em tabela, no estilo `claude doctor` — checa Ollama (:11434) e quais modelos estão baixados, gateway OmniRoute (:20128) e quantos modelos expõe, binário do claude, gh autenticado, versão do Python e do pacote, libs opcionais presentes (prompt_toolkit/textual/rich/flask), skills instaladas, espaço em disco, e imprime ✓/✗ com a AÇÃO de conserto ao lado de cada falha. Adicionar também como flag `vincent --doctor`.

- [ ] Medidor de tokens e custo: contar tokens de entrada/saída por turno (usar o campo usage da resposta quando o backend devolver, senão estimar), acumular por sessão, exibir na bottom toolbar do prompt_toolkit e num comando `/cost` com a quebra por modelo. Marcar rotas zero-key como custo 0 e destacar quando estiver gastando rota paga.

- [ ] Modo headless de verdade: `vincent -p "pergunta"` (one-shot, já existe algo parecido — auditar e consolidar) mais `--output-format text|json|stream-json` e leitura de stdin quando o programa recebe pipe (`echo "..." | vincent -p -`). Sem TTY não deve imprimir banner, HUD nem cores. É o que permite usar o Vincent dentro de script e em CI, igual `claude -p`.

- [ ] Busca reversa no histórico (Ctrl+R) e navegação de histórico multi-linha no prompt_toolkit, com destaque do trecho casado e Enter para reexecutar. Persistir o histórico entre sessões em ~/.vincent/repl_history (já criado) e deduplicar entradas repetidas.

- [ ] Arquivo de instruções do projeto: ao iniciar, procurar `VINCENT.md`/`AGENTS.md`/`CLAUDE.md` subindo do diretório atual até a raiz do repositório e injetar o conteúdo no system prompt do agente, mostrando na HUD qual arquivo foi carregado. Adicionar `/init` que gera um VINCENT.md inicial descrevendo o projeto atual (varrendo a estrutura, linguagem, comandos de build/teste detectados).

- [ ] Overlay de ajuda com `?` e `/keys`: painel navegável com TODOS os atalhos de teclado e comandos agrupados por categoria, que abre por cima do prompt sem perder o que já foi digitado. Também documentar os atalhos no README.

- [ ] `/theme`: seletor de tema navegável (Noite Estrelada, alto contraste, claro, monocromático para terminal sem cor), aplicado tanto ao REPL quanto à TUI, persistido em ~/.vincent/config.json. Detectar terminal sem suporte a 256 cores e cair pro monocromático automaticamente, e respeitar a variável de ambiente NO_COLOR.

- [ ] Declarar as dependências no pyproject.toml (prompt_toolkit, textual, rich, flask, flask-socketio) com extras opcionais coerentes (`[tui]`, `[web]`), e atualizar install.sh/install-termux.sh e o README para instalar tudo que a interface nova precisa. Hoje o pacote só funciona nesta máquina porque as libs foram injetadas na mão no venv do pipx — ninguém mais consegue instalar.

- [ ] Servidor MCP para integração com IDE: auditar e completar `src/vincent/mcp_server.py` para expor as ferramentas do Vincent (bash, arquivos, git, busca web, modelos) por MCP stdio, e documentar no README como plugar no VS Code, no Claude Code e no Antigravity. O usuário quer o Vincent dentro da IDE, não só no terminal.

- [ ] Renderização de markdown e código no REPL à altura da TUI: cabeçalhos, listas, tabelas, blocos de código com destaque de sintaxe e faixa com o nome da linguagem, links clicáveis (OSC 8) e quebra de linha que respeita a largura do terminal. Reaproveitar o `rich` (já instalado) sem quebrar o streaming token-a-token.

- [ ] `/export` da conversa: salvar a sessão atual em Markdown ou JSON escolhendo o destino, incluindo o trace das ferramentas executadas, com nome de arquivo sugerido a partir da data e do assunto.

---

## Recursos extraídos do OmniRoute (gateway v3.8.49 já rodando em :20128)

Levantados contra o gateway vivo, com resposta real de cada endpoint. Todos funcionam
sem autenticação e sem mudar configuração do container.

- [ ] Em src/vincent/models.py, no bloco OmniRoute de execute_inference (~linha 389), capturar `resp.headers` e propagar um dict com `x-omniroute-model`, `-provider`, `-response-cost`, `-tokens-in`, `-tokens-out`, `-latency-ms` e `-cache-hit`. O gateway JÁ manda esses headers em toda resposta e o Vincent os descarta — é o medidor de custo pronto. Exibir modelo real + tokens + custo + latência na statusline de cada turno, estilo Claude Code. Usar `.get()` com default em tudo (o gateway atualiza e renomeia campo).

- [ ] Em src/vincent/models.py, corrigir três comentários que afirmam o oposto do que o gateway faz: `gateway_status()` (~linha 218) diz que não existe header de rota — existe `x-omniroute-decision: strategy=auto; provider=antigravity; latency_ms=1391`; a linha ~248 diz que o OmniRoute não streama — ele devolve `text/event-stream` normalmente (o Vincent só não vê porque manda `"stream": False` explícito); a linha ~269 diz que os canais `auto/best-*` não existem — `/v1/models` lista 38 deles.

- [ ] Em src/vincent/agent_tools.py, adicionar a tool `web_search` fazendo POST `{gateway}/v1/search` com `{"query":..., "max_results":5}`, devolvendo title/url/snippet de cada resultado. Funciona sem chave nenhuma pelo provider `duckduckgo-free`. Registrar a tool no schema do agente em agent.py.

- [ ] Em src/vincent/agent_tools.py, comprimir saída de comando de shell antes de devolver ao contexto: POST `{gateway}/api/context/rtk/test` com `{"command":<cmd>,"text":<stdout>}`, usando o campo `compressed` só quando `compressed==true` e o resultado for menor que o original. O RTK detecta o tipo da saída (jest, git status, npm) e colapsa o ruído — é o maior ganho real de tokens num CLI agêntico, porque o vilão é a saída de comando, não o prompt do usuário.

- [ ] Em src/vincent/caveman.py, trocar `estimate_tokens` (linha 41) por POST `{gateway}/v1/messages/count_tokens` lendo `input_tokens`, com a heurística `chars/3.5` atual como fallback em qualquer exceção e timeout de 3s. Contagem real em vez de chute.

- [ ] Em src/vincent/caveman.py, adicionar `compress_via_gateway(messages)` chamando POST `{gateway}/api/compression/preview` com `{"engine":"caveman","messages":[...]}`, devolvendo (texto comprimido, tokensSaved) e caindo no `compress_prompt()` de regex atual se falhar. O endpoint devolve também um `diff` estruturado — usar pra pintar antes/depois colorido num `/caveman preview`. Manter a injeção de MODE_DESCRIPTIONS intacta: ela é prompt-side e complementar à reescrita payload-side do gateway.

- [ ] Adicionar `/cost` (dispatch em cli.py, registro em COMMANDS): GET `{gateway}/api/usage/analytics` e imprimir totalCost, totalRequests, totalTokens, successRatePct e avgLatencyMs de `summary`, mais p50/p95/p99 de GET `{gateway}/api/telemetry/summary`. Mensagem clara se o gateway estiver offline.

- [ ] Adicionar `/quota` (dispatch em cli.py, registro em COMMANDS): GET `{gateway}/api/usage/quota` e `{gateway}/api/usage/provider-limits`, imprimindo por provedor/modelo uma barra de percentRemaining e o resetAt como tempo relativo ("reseta em 4h22"). Hoje o Vincent só descobre limite depois de tomar 429 — isso antecipa.

- [ ] Adicionar `/inspect` (dispatch em cli.py, registro em COMMANDS): GET `{gateway}/api/usage/call-logs?limit=20` numa tabela com timestamp, modelo, provedor, status, duração e tokens in/out. É o Inspector de Tráfego do painel, no terminal, sem precisar do MITM do Agent Bridge.

- [ ] Adicionar `/routes <canal>` (dispatch em cli.py): GET `{gateway}/v1/auto-combo/{canal}/candidates` mostrando cada candidato com `reachable`, `breakerState` (CLOSED/OPEN) e `connectionCooldown`. Deixa visível por que um `auto/*` escolheu determinada rota.

- [ ] Em src/vincent/models.py, adicionar os headers de request `X-OmniRoute-Mode` (de env VINCENT_ROUTE_MODE, default "balanced", aceita fast|balanced|quality|cheap|reliable|offline) e, quando a env VINCENT_MAX_COST_USD existir, `X-OmniRoute-Budget` + `X-OmniRoute-Budget-Fallback: strict`. Tratar HTTP 402 como erro de orçamento com mensagem própria, não como falha de rota. Atenção: o roteamento é fail-open, então só o `strict` garante teto de custo de verdade.

- [ ] Em src/vincent/models.py, estender a cascata de fallback (~linha 272) para `["auto/best-free","auto/cheap","auto/coding","auto/best-coding","auto/smart","auto/fast","auto/offline","auto"]` — todos verificados existentes no `/v1/models` do gateway 3.8.49; hoje `auto/best-free` e `auto/offline`, que são os certos pra fallback barato, ficam de fora.

- [ ] Em src/vincent/models.py (~linha 444), acrescentar à mensagem de onboarding do VINCENT_GATEWAY_URL um aviso de que o OmniRoute serve `/api/keys` e `/api/settings/*` SEM autenticação, e que expor a porta 20128 na rede sem proxy protegido vaza as chaves de provedor do dono.
