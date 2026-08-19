# 🌌 VincentOS — Console Web

Console web do ecossistema **Vincent** (Galeria Vincent), com a identidade
*"A Noite Estrelada"* de Van Gogh. É o painel/gateway de IA que o `vincent` CLI
usa de backend (ver `pyproject.toml`: *"orquestrador neural de IA (OmniRoute/Ollama)"*).

## Base

Construído sobre o **OmniRoute** (github.com/diegosouzapw/OmniRoute), um AI gateway
open-source sob licença **MIT**. O código upstream **não é modificado**: a marca
Vincent é aplicada como uma camada por cima —

- **Nome / logo / favicon / modo escuro** → configurações do painel
  (`instanceName = "VincentOS"`, `customLogoBase64`, `customFaviconUrl`, `theme = dark`).
- **Paleta exata "Noite Estrelada"** → [`vincent-theme.css`](./vincent-theme.css),
  injetado no HTML pelo nginx (`sub_filter`) só nas rotas do painel.

Assim a identidade fica 100% neste repositório + na config do deploy, sem fork
pesado do OmniRoute e sem tocar strings funcionais dele (user-agents, IDs de OAuth,
descrições de provedor).

## Identidade

| Elemento | Valor |
|----------|-------|
| Nome | **VincentOS** |
| Tema | Van Gogh — *A Noite Estrelada* (night-first) |
| Fundo | `#060610` (noite) · superfícies `#0e0e1a` / `#16162a` |
| Acento | gradiente **`#7c3aed` violeta → `#06b6d4` ciano** |
| Estrelas | dourado `#ffaf00` · limão `#ffff00` |
| Texto | `#e2e8f0` / `#94a3b8` · borda `#1e1e38` |
| Logo | [`branding/vincent-logo.svg`](./branding/vincent-logo.svg) — swirl + estrelas |
| Favicon | [`branding/vincent-favicon.svg`](./branding/vincent-favicon.svg) |

## Deploy (resumo)

O painel roda em Docker sob subpath `/openroute` atrás do nginx. Detalhe de
infra (compose, portas, basePath) fica na máquina do deploy, não neste repo.

> Nota técnica: deploy do OmniRoute em subpath precisou de um fix no `basePath.ts`
> (o `fetch()` do client não recebia o prefixo `/openroute` → caía no root do
> domínio). Corrigido no deploy.

## Licença

OmniRoute é MIT (© diegosouzapw) — permite renomear, usar e comercializar.
A marca **Vincent** e os assets deste diretório são teus.
