# 🌌 VINCENT CLI 4.0 — Van Gogh 'Starry Night' Edition

```text
   ★    .   ☆  *   .   ★    .   *   ☆  .   ★    .   *   ☆  .   ★
  ██╗   ██╗██╗███╗   ██╗ ██████╗███████╗███╗   ██╗████████╗
  ██║   ██║██║████╗  ██║██╔════╝██╔════╝████╗  ██║╚══██╔══╝
  ██║   ██║██║██╔██╗ ██║██║     █████╗  ██╔██╗ ██║   ██║   
  ╚██╗ ██╔╝██║██║╚██╗██║██║     ██╔══╝  ██║╚██╗██║   ██║   
   ╚████╔╝ ██║██║ ╚████║╚██████╗███████╗██║ ╚████║   ██║   
    ╚═══╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝╚══════╝╚═╝  ╚═══╝   ╚═╝   
  ◈ V I N C E N T   O S   •   S T A R R Y   N I G H T   E D I T I O N ◈
```

> **Orquestrador Neural Autônomo Universal & Laboratório Embarcado ESP32**  
> Inspirado na estética pós-impressionista de *"A Noite Estrelada"* de Vincent van Gogh, construído com arquitetura adaptativa *"Be Water"* para rodar perfeitamente em Desktops, Servidores e dispositivos móveis via **Termux / ADB Root**.

---

## 🎨 Principais Funcionalidades

### 1. 🖌️ Identidade Visual 'Starry Night' & Redemoinho Neural
- **Paleta TrueColor ANSI**: Azul Cobalto (`#0087ff`), Azul Noturno (`#005fd7`), Amarelo Limão (`#ffff00`), Dourado Ocre (`#ffaf00`) e Verde Cipreste (`#00ff87`).
- **Animated Swirl Spinners**: Pinceladas e redemoinhos celestes em espiral (`໑`, `๑`, `༄`, `≋`, `✵`, `🌀`) com pulsos estelares.
- **Whitelabel Absoluto**: Toda a infraestrutura e rotas de terceiros são mascaradas sob o ecossistema artístico da **Galeria Vincent**.

### 2. ⚡ Catálogo de 1200+ Modelos & Motor Local Zero-Key
- **Rotas Zero-Key & Gratuitas**: Suporte a centenas de rotas públicas e combos de auto-roteamento (`auto/best-coding`, `auto/best-reasoning`, `auto/best-free`, `auto/smart`).
- **Atelier Local Offline (Ollama)**: opera com zero latência e 100% offline usando modelos locais que você já tenha puxado via `ollama pull` (ex: `qwen3:0.6b`, `qwen2.5-coder:7b`, `granite4:tiny-h`). O Vincent não baixa modelos sozinho.
- **Cascata com Failover Inteligente**: Chaveamento transparente e instantâneo entre nós locais e remotos em caso de indisponibilidade ou rate-limit.

### 3. 📉 Compressão Caveman (-65% Tokens)
- Baseado em [juliusbrussee/caveman](https://github.com/juliusbrussee/caveman).
- Elimina ruídos de linguagem natural, artigos e saudações mantendo 100% da precisão técnica de comandos e código.
- Modos: `off`, `lite`, `full`, `ultra`, `wenyan-lite`, `wenyan-full`, `wenyan-ultra`.

### 4. 📊 Telemetria Ponytail em Tempo Real
- Baseado em [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail).
- Statusline viva no prompt com métricas de latência média, hardware USB conectado, consumo de CPU/RAM e gráfico visual de economia de tokens.

### 5. 🛠️ Agentic Loop com Tool Calling (chat = ação)
- Motor único e generalista — investiga e corrige código sozinho via `list_dir`, `read_file`, `grep_search`,
  `run_bash`, `apply_diff`, GitOps (`git_status`/`git_diff`/`git_commit`/`git_rollback`) e pesquisa web
  (`web_search`/`fetch_url`).
- Todo prompt digitado no REPL (não só `/act`) passa pelo mesmo loop agêntico — ele sai em 1 turno se
  não houver ferramenta a chamar (ex: "oi") e executa de verdade quando o modelo pede.
- Auto-cura: todo `apply_diff` em `.py` é validado por sintaxe; se quebrar, o próprio Vincent restaura a
  versão anterior e tenta de novo (até 3x) sem intervenção manual.
- `/bg <tarefa>` roda uma tarefa agêntica em segundo plano (thread própria) sem travar o REPL.
- `/spawn <n> <tarefas>` dispara N workers paralelos de verdade (`ThreadPoolExecutor`), cada um com
  estado 100% local — tarefas separadas por `;` ou a mesma tarefa repetida N vezes.

### 6. 🧠 Treinamento e Fine-Tuning Nativo (LlamaFactory)
- Baseado em [hiyouga/LlamaFactory](https://github.com/hiyouga/LlamaFactory).
- Geração automática de pipelines LoRA/QLoRA e exportação de datasets de conversação no padrão ShareGPT/Alpaca com o comando `/train` e `/export`.

### 7. 📱 Princípio da Adaptabilidade Extrema ("Be Water")
- Detecção automática de ambiente (`Desktop Linux/macOS/Windows` vs `Termux Android/ADB Root`).
- Layout adaptativo: comprime painéis e buffers em telas móveis sem quebrar bordas ANSI.
- Serial Fallback de aço para dispositivos USB/OTG no Android (`/dev/ttyACM*`, `/dev/ttyUSB*`, `termux-usb`).

### 8. 🧩 Skills sob Demanda
- Mesmo padrão de `SKILL.md` (frontmatter YAML + corpo Markdown) do OpenCode/Claude Agent Skills/obsidian-skills.
- `/skill add <git-url>` clona um repositório de skills para `~/.vincent/skills/<nome>/`.
- No boot só o frontmatter é lido (barato); o corpo entra no contexto apenas quando a tarefa bate com a
  `description` da skill via correspondência de palavras-chave (sem chamada extra de LLM).

### 9. 🔌 Camada de Resiliência de Roteamento
- Circuit breaker por provider, cooldown exponencial por conexão/chave e lockout por modelo
  (`src/vincent/routing/resilience.py`), com estado persistido em `~/.vincent/brain.db`.
- Estratégias de seleção plugáveis (`routing/strategies.py`): `priority` (padrão), `round_robin`,
  `cost_optimized` e `lkgp` (sticky no último modelo que funcionou).
- `/gateway` exibe o status ao vivo do gateway OmniRoute: alcançabilidade, contagem de modelos, estado
  do circuito e cooldown ativo.

---

## 🚀 Instalação Rápida

### Instalador universal (um único comando)

Detecta Termux/Linux/macOS automaticamente, clona (ou reusa) o repositório e instala via `pipx` quando
disponível (senão `pip --user`). Idempotente — rodar de novo só atualiza o checkout existente.

```bash
curl -fsSL https://raw.githubusercontent.com/vangoghdev7-sketch/vincent/master/install.sh | bash
```

### Linux / macOS / Windows (WSL) — manual

```bash
git clone https://github.com/vangoghdev7-sketch/vincent.git
cd vincent
pip install -e .
```

### Termux (Android Mobile / ADB Root)

Execute o instalador automatizado de um único passo:

```bash
chmod +x install-termux.sh
./install-termux.sh
```

---

## 🕹️ Guia de Uso

### Iniciar o REPL Interativo

```bash
vincent
```

### Executar Prompt Direto no Terminal

```bash
# Prompt simples com modelo padrão
vincent "Como implementar um sniffer no CC1101?"

# Prompt com compressão Caveman (-65% tokens)
vincent -c full "Refatore o driver serial do ESP32DIV em C++"

# Executar tarefa via Agentic Loop (investiga e corrige código sozinho)
vincent -a "Criar script de automação de backup no systemd"
```

### Flags da CLI

| Flag | Descrição |
| :--- | :--- |
| `-m, --model <id>` | Modelo inicial (padrão: `qwen3:0.6b`) |
| `-a, --agent <tarefa>` | Executa via Agentic Loop autônomo com Tool Calling |
| `-l, --list-models` | Lista o catálogo completo de modelos |
| `-s, --search <termo>` | Filtra modelos por palavra-chave |
| `-c, --caveman <modo>` | Modo caveman (`lite`, `full`, `ultra`) |
| `-d, --devices` | Lista dispositivos de hardware USB conectados |
| `-t, --train` | Gera configuração de treino LoRA via LlamaFactory |
| `--vault, --auth` | Exibe status do cofre de chaves (chmod 0600) |
| `--config` | Abre o painel visual interativo (setas, curses) de configuração |
| `--serve, --daemon` | Inicia servidor MCP em background (daemon) |
| `--mcp` | Inicia servidor MCP no terminal via stdio |
| `--socket <path>` | Caminho do socket Unix para o servidor MCP |

### Comandos Internos do REPL

Qualquer comando abaixo também funciona sem a barra inicial (ex: `models` funciona igual a `/models`).
Um prompt sem barra que não seja um comando reconhecido vai direto para o chat = ação (agentic loop).

| Comando | Descrição |
| :--- | :--- |
| `/models` | Lista o catálogo completo de 1200+ rotas neurais |
| `/search <termo>` | Filtra modelos por palavra-chave (ex: `/search free` ou `/search coding`) |
| `/model <id>` | Sintoniza o modelo ativo em tempo real |
| `/caveman <modo>` | Alterna modos de compressão de tokens (`off`, `lite`, `full`, `ultra`, `wenyan-lite`, `wenyan-full`, `wenyan-ultra`) |
| `<prompt>` (sem comando) | Chat = ação: mesmo agentic loop de `/act`, sai em 1 turno se não precisar de ferramenta |
| `/act <tarefa>` / `/agent <tarefa>` | Força o Agentic Loop: investiga e corrige código sozinho com tool calling |
| `/bg <tarefa>` | Roda uma tarefa agêntica em segundo plano, sem travar o REPL |
| `/spawn <n> <tarefas>` | N workers paralelos de verdade (separe tarefas com `;`, ou repita a mesma N vezes) |
| `/commit <msg>` | Checkpoint git manual (Conventional Commits) |
| `/vision <img> [pergunta]` | Lê uma imagem (print de erro, mockup) via modelo multimodal |
| `/config` | Painel visual interativo (setas, curses) de modelo e chaves |
| `/gateway` | Status ao vivo do gateway OmniRoute (alcançabilidade, circuit breaker, cooldown) |
| `/tui` | Painel visual (Rich): modelo/tokens/custo, workers, log. Ao vivo se houver `/bg`/`/spawn` rodando, snapshot estático senão |
| `/vault` / `/auth` / `/login` | Menu do cofre de chaves local (chmod 0600) — sem OAuth, chave real por provedor |
| `/key [chave]` | Atalho para registrar direto a chave OmniRoute no cofre |
| `/skills` | Lista as skills instaladas (`~/.vincent/skills/<nome>/SKILL.md`) |
| `/skill add <git-url>` | Clona um repositório de skills (padrão `skills/<nome>/SKILL.md`) |
| `/train` / `/lora` | Gera configuração de fine-tuning LoRA via LlamaFactory |
| `/export` | Exporta histórico da sessão como dataset de treino |
| `/devices` | Varre e inspeciona placas ESP32/USB conectadas |
| `/cmd <dev> <cmd>` | Envia comando serial direto para o hardware |
| `/stats` | Exibe telemetria detalhada, recursos e economia de tokens |
| `/clear` | Limpa a tela e o histórico da sessão |
| `/help` | Mostra este guia de comandos |
| `/exit` | Encerra o Vincent CLI (avisa antes se houver tarefas em `/bg`/`/spawn` ainda rodando) |

---

## 📜 Licença

Distribuído sob a licença MIT. Criado com paixão e arte pela equipe Vincent.
