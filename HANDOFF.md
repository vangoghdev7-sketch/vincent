# 🌌 VINCENT / SNOOP INTELLIGENCE — HANDOFF (LER PRIMEIRO)

Documento de identidade + contrato de trabalho. Qualquer pessoa ou IA que for
mexer neste projeto lê ISTO antes de qualquer ação.

---

## Quem somos

| | |
|---|---|
| **Team** | Snoop Intelligence |
| **Produto / marca** | **VincentOS** — AI Coder + gateway de IA multi-provider |
| **Estética** | Van Gogh — *A Noite Estrelada* ("Galeria Vincent") |
| **Ecossistema** | `vincent` CLI (este repo) + console web (OmniRoute rebrandado) |
| **CLI backend** | o `vincent` CLI usa o gateway de backend (`pyproject.toml`) |

## Identidade visual (fonte da verdade: [`web/`](./web))

- Nome exibido: **VincentOS**
- Fundo noturno `#060610`; superfícies `#0e0e1a` / `#16162a`
- Acento: gradiente **`#7c3aed` violeta → `#06b6d4` ciano**
- Estrelas: dourado `#ffaf00`, limão `#ffff00`; verde cipreste `#00ff87`
- Logo/favicon: swirl + estrelas — [`web/branding/`](./web/branding)
- Tema web completo: [`web/vincent-theme.css`](./web/vincent-theme.css)

---

## ⚖️ REGRAS DE OURO (contrato — vale pra qualquer sessão/IA)

Projetos em **PRODUÇÃO REAL, financeiro, com users ativos. 0 margem pra erro.**

**Verdade e status**
- Nunca prometer certeza absoluta. PROIBIDO: "0 erros", "tá perfeito", "100% testado", "garantido", "blindado".
- Todo status em **3 blocos**: (1) verificado com evidência, (2) NÃO verificado, (3) riscos em aberto.
- Evidência sempre = ler o código com os próprios olhos (**arquivo:linha**). Suspeita ≠ bug.
- **Falso positivo é falha grave.** Relatório de outra IA = suspeita, não verdade.

**Antes de mexer**
- Nunca alterar código sem **mapa de impacto completo** (quem chama, quem lê/escreve estado, locks, hooks, side effects).
- Nunca deletar/mover arquivo de DADOS sem perguntar — nem se parece órfão.
- Nunca mexer em runtime global (versões, libs do sistema, instalação global). Na dúvida, pergunta.

**Execução em produção — 5 etapas**
1. backup nomeado → 2. validar sintaxe → 3. diff visual → 4. smoke test → 5. confirmar antes de subir.
- Escopo **CIRÚRGICO**: muda só o pedido. Achou outro bug? REPORTA, não mexe sem OK.
- **Fluxo crítico (pagamento, auth, saldo, permissão, webhook, secrets, infra): mostrar o MAPA e pedir OK ANTES.**

**Relação e comunicação**
- Ordem do usuário é ordem. Instrução dada = autorização (para de perguntar "tem certeza?").
- **Não expor internals pro cliente final** (provedor, gateway, stack, versão, path). Erro pro cliente = genérico; detalhe só no log interno.
- Perfeito ou não entrega. Sem TODO/debug esquecido, sem código morto. Resposta curta, ao ponto.

**Infra desta VPS (173)**
- Auditoria/sweep **multi-agente pesado JÁ derrubou a prod** (load 44–101). Triage = bash read-only **sequencial**, nunca fleet de agentes.

---

## 📦 Estado do produto (2026-08-19)

**Gateway:** OmniRoute (MIT, github.com/diegosouzapw/OmniRoute) rebrandado **VincentOS**, servindo em `https://dash.snoopintelligence.cloud/openroute/`. Source do OmniRoute intacto; marca aplicada como camada (settings + injeção nginx). Senha do painel: `INITIAL_PASSWORD`.

**Providers ativos** (todos **free-tier / integração reversa** — ver risco abaixo):
- GitHub Copilot ×5 · Amazon Q ×1 · Claude ×1 — todos ✓
- Antigravity ×3 contas — **MORTO** (Google rejeita `onboardUser` com 400; desativado)

**Fallback:** `auto/best-coding` já roteia entre providers + as 5 contas GitHub se revezam sozinhas. Combo custom (pago→primário, grátis→fallback) **pendente** da key paga.

## 🛑 Riscos abertos (honestos)
1. **Monetizar revendendo free-tier viola ToS** de GitHub/Google/Amazon/Anthropic → risco de ban + produto frágil (Antigravity morrendo é o preview). **Precisa de 1 provider PAGO como espinha dorsal.**
2. **Latência ~13s** por completion (provável proxy Copilot / overhead auto-combo).
3. **Gateway aberto** (`REQUIRE_API_KEY` vazio) — sem metering, não dá pra cobrar ainda.

## ▶️ Próximos passos
1. Adicionar **1 provider PAGO** (Anthropic recomendado p/ coder) como primário.
2. Montar combo **VincentOS Coder** (pago primário → GitHub/Claude/Amazon-Q fallback).
3. Investigar latência.
4. Ligar `REQUIRE_API_KEY` + emitir chaves por cliente (metering) — passo que **tranca** o gateway, só no fim.
