/**
 * Vincent AI Swarm Gateway Liveness & Capability Probe (same-origin, CSP-safe).
 *
 * Vincent is the unified multi-AI brain and gateway running at port 20128
 * (OpenAI-compatible /v1/*, zero-key local routing + multi-provider swarm).
 *
 * The browser must not hit :20128 directly due to CSP connect-src restrictions
 * and container network boundaries. This Next.js server route performs the
 * server-side probe, inspects available models, and returns capabilities for:
 *   - OpenAI (GPT-4o, o1, o3-mini)
 *   - Anthropic (Claude 3.7 Sonnet, Claude 3.5 Haiku/Sonnet)
 *   - Google Gemini (Gemini 2.5 Pro/Flash, 2.0 Flash, 1.5 Pro)
 *   - DeepSeek (DeepSeek-V3, DeepSeek-R1 / Reasoner)
 *   - xAI Grok (Grok-2, Grok-Vision)
 *   - Ollama local models (Qwen2.5, Llama 3.3, Mistral, DeepSeek-R1 local)
 *   - Kimi / Moonshot (Moonshot-v1, Kimi K1.5)
 *   - MiniMax (abab6.5s, minimax-text-01)
 *   - Qwen / DashScope (Qwen-Max, Qwen-Plus, Qwen-Coder)
 */

import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

const DEFAULT_CANDIDATE_URLS = [
  process.env.VINCENT_AI_GATEWAY_URL,
  process.env.VINCENT_ROUTER_URL,
  process.env.BRAIN_BASE,
  'http://host.containers.internal:20128',
  'http://127.0.0.1:20128',
  'http://localhost:20128',
].filter(Boolean) as string[];

const PUBLIC_ENDPOINT = process.env.NEXT_PUBLIC_VINCENT_AI_URL || 'http://localhost:20128';

const NO_STORE_HEADERS = {
  'Cache-Control': 'no-store, max-age=0, must-revalidate',
  Pragma: 'no-cache',
};

export interface RawModelItem {
  id: string;
  object?: string;
  owned_by?: string;
  created?: number;
  context_length?: number;
  max_input_tokens?: number;
  max_output_tokens?: number;
  capabilities?: {
    tool_calling?: boolean;
    reasoning?: boolean;
    thinking?: boolean;
    temperature?: boolean;
    vision?: boolean;
  };
}

export interface ProviderCapability {
  id: string;
  name: string;
  available: boolean;
  modelCount: number;
  models: string[];
  features: {
    toolCalling: boolean;
    reasoning: boolean;
    vision: boolean;
    streaming: boolean;
  };
}

const SUPPORTED_PROVIDERS: Record<string, { name: string; pattern: RegExp; ownedByPattern?: RegExp }> = {
  openai: {
    name: 'OpenAI',
    pattern: /^(gpt-|o1|o3|chatgpt-|text-embedding-)/i,
    ownedByPattern: /openai/i,
  },
  anthropic: {
    name: 'Anthropic Claude',
    pattern: /^claude-/i,
    ownedByPattern: /anthropic/i,
  },
  gemini: {
    name: 'Google Gemini',
    pattern: /^gemini-/i,
    ownedByPattern: /(google|gemini)/i,
  },
  deepseek: {
    name: 'DeepSeek',
    pattern: /^deepseek-/i,
    ownedByPattern: /deepseek/i,
  },
  grok: {
    name: 'xAI Grok',
    pattern: /^grok-/i,
    ownedByPattern: /(xai|grok)/i,
  },
  ollama: {
    name: 'Ollama (Local)',
    pattern: /(^ollama\/|:latest$|:0\.5b|:1\.5b|:7b|:8b|:14b|:32b|:70b|llama|mistral|phi|gemma|nomic)/i,
    ownedByPattern: /ollama/i,
  },
  kimi: {
    name: 'Moonshot Kimi',
    pattern: /(kimi|moonshot)/i,
    ownedByPattern: /(kimi|moonshot)/i,
  },
  minimax: {
    name: 'MiniMax',
    pattern: /(minimax|abab)/i,
    ownedByPattern: /minimax/i,
  },
  qwen: {
    name: 'Qwen / DashScope',
    pattern: /(qwen|qwq|dashscope)/i,
    ownedByPattern: /(qwen|alibaba|dashscope)/i,
  },
  combos: {
    name: 'Vincent Smart Combos',
    pattern: /^(auto\/|combo\/|router\/|vincent)/i,
    ownedByPattern: /(combo|vincent|system)/i,
  },
};

function classifyModels(rawModels: RawModelItem[]): Record<string, ProviderCapability> {
  const result: Record<string, ProviderCapability> = {};

  for (const [key, meta] of Object.entries(SUPPORTED_PROVIDERS)) {
    result[key] = {
      id: key,
      name: meta.name,
      available: false,
      modelCount: 0,
      models: [],
      features: {
        toolCalling: false,
        reasoning: false,
        vision: false,
        streaming: true,
      },
    };
  }

  for (const model of rawModels) {
    const id = model.id || '';
    const ownedBy = model.owned_by || '';

    for (const [key, meta] of Object.entries(SUPPORTED_PROVIDERS)) {
      const matchId = meta.pattern.test(id);
      const matchOwner = meta.ownedByPattern ? meta.ownedByPattern.test(ownedBy) : false;

      if (matchId || matchOwner) {
        const prov = result[key];
        prov.available = true;
        prov.modelCount += 1;
        if (!prov.models.includes(id)) {
          prov.models.push(id);
        }

        if (model.capabilities) {
          if (model.capabilities.tool_calling) prov.features.toolCalling = true;
          if (model.capabilities.reasoning || model.capabilities.thinking) prov.features.reasoning = true;
          if (model.capabilities.vision) prov.features.vision = true;
        }

        if (/vision|image|vl/i.test(id)) prov.features.vision = true;
        if (/reasoner|o1|o3|r1|thinking/i.test(id)) prov.features.reasoning = true;
      }
    }
  }

  return result;
}

async function probeGateway(): Promise<{
  connected: boolean;
  models: RawModelItem[];
  gatewayUrl?: string;
}> {
  for (const base of DEFAULT_CANDIDATE_URLS) {
    try {
      const res = await fetch(`${base}/v1/models`, {
        signal: AbortSignal.timeout(2500),
        headers: { Accept: 'application/json' },
      });

      if (res.ok) {
        const data = await res.json().catch(() => null);
        const models = Array.isArray(data?.data) ? (data.data as RawModelItem[]) : [];
        return { connected: true, models, gatewayUrl: base };
      }
    } catch {
      /* continue trying next candidate */
    }

    try {
      const rootRes = await fetch(`${base}/`, {
        signal: AbortSignal.timeout(2000),
      });
      if (rootRes.ok || rootRes.status === 307 || rootRes.status === 302) {
        return { connected: true, models: [], gatewayUrl: base };
      }
    } catch {
      /* continue */
    }
  }

  return { connected: false, models: [] };
}

export async function GET() {
  const probe = await probeGateway();
  const capabilities = classifyModels(probe.models);

  const activeProviders = Object.entries(capabilities)
    .filter(([_, cap]) => cap.available)
    .map(([key]) => key);

  return NextResponse.json(
    {
      ok: true,
      connected: probe.connected,
      service: 'VINCENT OS AI Swarm Gateway',
      model: 'vincent',
      endpoint: PUBLIC_ENDPOINT,
      gateway_url: probe.gatewayUrl || null,
      total_models: probe.models.length,
      active_providers: activeProviders,
      supported_providers: Object.keys(SUPPORTED_PROVIDERS),
      capabilities,
      models: probe.models.map((m) => ({
        id: m.id,
        owned_by: m.owned_by || 'unknown',
        context_length: m.context_length || null,
        capabilities: m.capabilities || null,
      })),
      features: {
        smart_routing: true,
        combos: true,
        fallback_resilience: true,
        zero_key_local: true,
        openclaw_hmac_auth: true,
        sse_streaming: true,
      },
      timestamp: Date.now(),
    },
    { headers: NO_STORE_HEADERS },
  );
}
