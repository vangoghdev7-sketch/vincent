# Vincent OS // Multi-AI Swarm & Agent Hub Guide

**Vincent OS** unifies real-time multi-domain OSINT geospatial intelligence (`http://localhost:3000` / `:8000`) with an autonomous **Multi-AI Swarm Gateway** (`http://localhost:20128`).

---

## Architecture Overview

```
+-----------------------------------------------------------------------------------+
|                                  VINCENT OS                                       |
+-----------------------------------------+-----------------------------------------+
|     OSINT Geospatial & Signal Mesh      |     Multi-AI Swarm & Agent Gateway      |
|           (:3000 / :8000)               |                 (:20128)                |
+-----------------------------------------+-----------------------------------------+
| - Real-time map (ADS-B, AIS, Sats, etc) | - OpenAI-compatible endpoint (/v1/*)    |
| - SIGINT, CCTV, Cyber, Disinfo trackers | - Multi-LLM Smart Router & Load Balancer|
| - Private Infonet & Tor Onion Mesh      | - OpenClaw Autonomous Skill Agent       |
| - Threat Intelligence & Event Horizon   | - Zero-Key Local Brain + Cloud Providers|
+-----------------------------------------+-----------------------------------------+
```

---

## Supported AI Providers & Models

Vincent OS natively routes to the following models and providers:

| Provider | Supported Models | Description |
|----------|-----------------|-------------|
| **Local Vincent Brain** | `vincent`, `local-brain` | Zero-key default local router engine (`:20128`) |
| **OpenAI** | `gpt-4o`, `gpt-4o-mini`, `o1`, `o3-mini` | State-of-the-art reasoning and multimodal analysis |
| **Anthropic** | `claude-3-7-sonnet`, `claude-3-5-sonnet`, `claude-3-5-haiku` | Deep coding and analytical synthesis |
| **Google Gemini** | `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-2.0-flash-exp` | Ultra-long context and multimodal intelligence |
| **DeepSeek** | `deepseek-chat`, `deepseek-reasoner` (R1) | High-performance open reasoning models |
| **xAI Grok** | `grok-2`, `grok-beta`, `grok-vision-beta` | Real-time world knowledge and uncensored analysis |
| **Ollama (Local)** | `llama3.3`, `qwen2.5-coder`, `mistral`, `deepseek-r1` | 100% offline private local AI inference |
| **Moonshot Kimi** | `moonshot-v1-8k`, `moonshot-v1-32k`, `moonshot-v1-128k` | High-fidelity long document intelligence |
| **MiniMax** | `abab6.5s-chat`, `abab7-chat-preview` | Fast high-throughput conversational reasoning |
| **Qwen / Alibaba** | `qwen-plus`, `qwen-turbo`, `qwen-max` | Advanced multilingual and coding models |

---

## Configuration & Environment (.env)

Vincent OS is completely free of hardcoded secrets. Configure your API keys in your local `.env` file (copied from `.env.example`):

```bash
# ==============================================================================
# VINCENT OS - MULTI-AI SWARM CONFIGURATION
# ==============================================================================

# Vincent Multi-AI Swarm Gateway Port & Host
VINCENT_AI_PORT=20128
VINCENT_AI_HOST=127.0.0.1

# Cloud AI Provider Keys (fill as desired)
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
DEEPSEEK_API_KEY=
GROK_API_KEY=
MOONSHOT_API_KEY=
MINIMAX_API_KEY=
DASHSCOPE_API_KEY=

# Local Ollama Configuration
OLLAMA_BASE_URL=http://127.0.0.1:11434

# OpenClaw Autonomous Agent HMAC Authentication
OPENCLAW_HMAC_SECRET=
```

---

## Starting the Unified Stack

Run the unified launcher from the project root:

```bash
# Start both Vincent OSINT containers and the Multi-AI Swarm Router
./unified.sh start

# Check the health and status of all planes
./unified.sh status

# Stop containers while preserving local router infra
./unified.sh stop

# Run health diagnostics
./unified.sh doctor
```

Access the interfaces:
- **Vincent OSINT Command Dashboard:** [http://localhost:3000](http://localhost:3000)
- **Vincent Multi-AI Swarm Gateway:** [http://localhost:20128](http://localhost:20128)
- **Backend OSINT API & Feeds:** [http://localhost:8000](http://localhost:8000)

---

## OpenClaw Agent Integration

Vincent OS acts as an autonomous co-analyst via the OpenClaw skill agent.

1. Navigate to **AI Intel Panel** (`[A]` hotkey or top navigation).
2. Click **Connect OpenClaw Agent**.
3. Select your access tier (**Read Only** or **Full Access**).
4. Click **Generate HMAC Key** and paste the exported environment snippet into your OpenClaw agent environment.
5. Your agent now authenticates with SHA-256 HMAC signatures to query live SIGINT, place pins, and dispatch swarm alerts.
