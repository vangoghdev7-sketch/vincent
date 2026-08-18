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
- **Atelier Local Offline (Ollama)**: Modelos locais pré-carregados para operação com zero latência e 100% offline (`qwen3:0.6b`, `qwen2.5-coder:7b`, `granite4:tiny-h`, etc.).
- **Cascata com Failover Inteligente**: Chaveamento transparente e instantâneo entre nós locais e remotos em caso de indisponibilidade ou rate-limit.

### 3. 📉 Compressão Caveman (-65% Tokens)
- Baseado em [juliusbrussee/caveman](https://github.com/juliusbrussee/caveman).
- Elimina ruídos de linguagem natural, artigos e saudações mantendo 100% da precisão técnica de comandos e código.
- Modos: `lite`, `full`, `ultra`, `wenyan-lite`, `wenyan-full` e `off`.

### 4. 📊 Telemetria Ponytail em Tempo Real
- Baseado em [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail).
- Statusline viva no prompt com métricas de latência média, hardware USB conectado, consumo de CPU/RAM e gráfico visual de economia de tokens.

### 5. 🤖 GSD Swarm & AG-Kit Multi-Agent Orchestration
- Baseado em [open-gsd/gsd-core](https://github.com/open-gsd/gsd-core) e [vudovn/ag-kit](https://github.com/vudovn/ag-kit).
- Execução autônoma de tarefas complexas em fases e ondas através do squad especializado:
  - 📋 `Vincent-Product`: Curador de Obra & Especificação
  - 🛡️ `Vincent-Auditor`: Crítico de Arte & Auditoria de Segurança
  - 💻 `Vincent-Coder`: Mestre Pintor & Engenharia de Código
  - 📡 `Vincent-Hardware`: Engenheiro de Chassis & Rádio ESP32
  - 🧪 `Vincent-Tester`: Restaurador & Testes de Fumaça
  - ⚙️ `Vincent-DevOps`: Guardião da Galeria & Daemons

### 6. 🧠 Treinamento e Fine-Tuning Nativo (LlamaFactory)
- Baseado em [hiyouga/LlamaFactory](https://github.com/hiyouga/LlamaFactory).
- Geração automática de pipelines LoRA/QLoRA e exportação de datasets de conversação no padrão ShareGPT/Alpaca com o comando `/train` e `/export`.

### 7. 📱 Princípio da Adaptabilidade Extrema ("Be Water")
- Detecção automática de ambiente (`Desktop Linux/macOS/Windows` vs `Termux Android/ADB Root`).
- Layout adaptativo: comprime painéis e buffers em telas móveis sem quebrar bordas ANSI.
- Serial Fallback de aço para dispositivos USB/OTG no Android (`/dev/ttyACM*`, `/dev/ttyUSB*`, `termux-usb`).

---

## 🚀 Instalação Rápida

### Linux / macOS / Windows (WSL)

```bash
git clone https://github.com/seu-usuario/vincent-cli.git
cd vincent-cli
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

# Executar tarefa com Swarm de Agentes GSD
vincent -g "Criar script de automação de backup no systemd"
```

### Comandos Internos do REPL

| Comando | Descrição |
| :--- | :--- |
| `/models` | Lista o catálogo completo de 1200+ rotas neurais |
| `/search <termo>` | Filtra modelos por palavra-chave (ex: `/search free` ou `/search coding`) |
| `/model <id>` | Sintoniza o modelo ativo em tempo real |
| `/caveman <modo>` | Alterna modos de compressão de tokens (`off`, `lite`, `full`, `ultra`) |
| `/gsd <tarefa>` | Inicia plano autônomo multi-agente em ondas |
| `/squad` | Exibe o squad de agentes especializados da Galeria |
| `/login` / `/key` | Autenticação Enterprise via OAuth2 ou injeção de Chave Neural |
| `/train` / `/lora` | Gera configuração de fine-tuning LoRA via LlamaFactory |
| `/export` | Exporta histórico da sessão como dataset de treino |
| `/devices` | Varre e inspeciona placas ESP32/USB conectadas |
| `/cmd <dev> <cmd>` | Envia comando serial direto para o hardware |
| `/stats` | Exibe telemetria detalhada, recursos e economia de tokens |
| `/clear` | Limpa a tela e o histórico da sessão |
| `/exit` | Encerra o Vincent CLI |

---

## 📜 Licença

Distribuído sob a licença MIT. Criado com paixão e arte pela equipe Vincent.
