"""
VINCENT OS — Multi-AI Swarm & Router Gateway API.

Provides endpoints for inspecting AI providers, discovering models, checking swarm
liveness at port 20128 (Vincent AI Swarm Gateway / OmniRoute), and smart routing
with graceful fallbacks when keys are not configured yet.
"""

import asyncio
import logging
import os
import re
import time
from typing import Any, Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from auth import require_local_operator, require_openclaw_or_local
from limiter import limiter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ai-swarm"])

AI_GATEWAY_DEFAULT_URLS = [
    os.environ.get("VINCENT_AI_GATEWAY_URL", ""),
    os.environ.get("OMNIROUTE_URL", ""),
    "http://127.0.0.1:20128",
    "http://localhost:20128",
    "http://host.containers.internal:20128",
]

AI_PROVIDERS_CONFIG = {
    "openai": {
        "name": "OpenAI",
        "env_key": "OPENAI_API_KEY",
        "description": "GPT-4o, GPT-4o-mini, o1, o3-mini models",
        "url": "https://platform.openai.com/api-keys",
        "default_models": ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini"],
        "category": "cloud",
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "env_key": "ANTHROPIC_API_KEY",
        "description": "Claude 3.7 Sonnet, Claude 3.5 Sonnet & Haiku",
        "url": "https://console.anthropic.com/",
        "default_models": ["claude-3-7-sonnet", "claude-3-5-sonnet", "claude-3-5-haiku"],
        "category": "cloud",
    },
    "gemini": {
        "name": "Google Gemini",
        "env_key": "GEMINI_API_KEY",
        "description": "Gemini 2.5 Pro, 2.5 Flash, 2.0 Flash",
        "url": "https://aistudio.google.com/app/apikey",
        "default_models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
        "category": "cloud",
    },
    "deepseek": {
        "name": "DeepSeek",
        "env_key": "DEEPSEEK_API_KEY",
        "description": "DeepSeek-V3 and DeepSeek-R1 (Reasoner)",
        "url": "https://platform.deepseek.com/api_keys",
        "default_models": ["deepseek-chat", "deepseek-reasoner"],
        "category": "cloud",
    },
    "grok": {
        "name": "xAI Grok",
        "env_key": "GROK_API_KEY",
        "description": "Grok-2 and Grok-Vision",
        "url": "https://console.x.ai/",
        "default_models": ["grok-2", "grok-vision-beta"],
        "category": "cloud",
    },
    "ollama": {
        "name": "Ollama (Local LLM)",
        "env_key": "OLLAMA_BASE_URL",
        "description": "Local zero-key models (Qwen2.5, Llama 3.3, Mistral, DeepSeek-R1)",
        "url": "https://ollama.com/",
        "default_models": ["qwen2.5:0.5b", "qwen2.5:1.5b-instruct", "qwen2.5-coder:7b", "llama3.3:8b"],
        "category": "local",
    },
    "kimi": {
        "name": "Moonshot Kimi",
        "env_key": "KIMI_API_KEY",
        "description": "Kimi K1.5 and Moonshot-v1",
        "url": "https://platform.moonshot.cn/",
        "default_models": ["moonshot-v1-8k", "moonshot-v1-32k", "kimi-k1.5"],
        "category": "cloud",
    },
    "minimax": {
        "name": "MiniMax",
        "env_key": "MINIMAX_API_KEY",
        "description": "MiniMax abab6.5s and text-01",
        "url": "https://platform.minimaxi.com/",
        "default_models": ["abab6.5s-chat", "minimax-text-01"],
        "category": "cloud",
    },
    "qwen": {
        "name": "Qwen / DashScope",
        "env_key": "QWEN_API_KEY",
        "description": "Qwen-Max, Qwen-Plus, and Qwen-Coder",
        "url": "https://dashscope.aliyun.com/",
        "default_models": ["qwen-max", "qwen-plus", "qwen-coder-plus"],
        "category": "cloud",
    },
}


class RouteRequest(BaseModel):
    prompt: str = Field(..., description="Prompt or query to analyze for optimal model routing")
    task_type: Optional[str] = Field(None, description="Optional override: 'code', 'reasoning', 'chat', 'fast', 'vision'")
    prefer_local: bool = Field(False, description="Prefer local Ollama execution when available")


async def _probe_ai_gateway() -> tuple[bool, Optional[str], list[dict[str, Any]]]:
    """Probe candidate gateway endpoints and return (is_connected, live_url, models_list)."""
    urls = [u for u in AI_GATEWAY_DEFAULT_URLS if u]
    for url in urls:
        clean_url = url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{clean_url}/v1/models")
                if resp.status_code == 200:
                    data = resp.json()
                    models = data.get("data", []) if isinstance(data, dict) else []
                    return True, clean_url, models
        except Exception:
            continue

        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                resp = await client.get(f"{clean_url}/")
                if resp.status_code in (200, 302, 307):
                    return True, clean_url, []
        except Exception:
            continue

    return False, None, []


def _check_key_configured(env_key: Optional[str]) -> bool:
    if not env_key:
        return False
    val = os.environ.get(env_key, "").strip()
    return bool(val)


@router.get("/api/ai/swarm/status", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("60/minute")
async def get_ai_swarm_status(request: Request):
    """
    Get full multi-AI swarm connectivity, active gateway info, and provider readiness.
    """
    from services.api_settings import load_persisted_api_keys_into_environ
    load_persisted_api_keys_into_environ()

    gateway_connected, active_url, live_models = await _probe_ai_gateway()

    provider_status = {}
    configured_count = 0
    for prov_id, meta in AI_PROVIDERS_CONFIG.items():
        is_set = _check_key_configured(meta.get("env_key"))
        if is_set:
            configured_count += 1
        provider_status[prov_id] = {
            "name": meta["name"],
            "configured": is_set,
            "env_key": meta.get("env_key"),
            "category": meta["category"],
            "url": meta["url"],
            "default_models": meta["default_models"],
        }

    # Check OpenClaw HMAC
    hmac_set = bool(os.environ.get("OPENCLAW_HMAC_SECRET", "").strip())

    return {
        "ok": True,
        "service": "VINCENT Multi-AI Swarm Gateway",
        "gateway": {
            "connected": gateway_connected,
            "url": active_url or "http://127.0.0.1:20128",
            "models_count": len(live_models),
            "protocol": "OpenAI-compatible /v1/*",
            "zero_key_local": True,
        },
        "providers": provider_status,
        "stats": {
            "total_providers": len(AI_PROVIDERS_CONFIG),
            "configured_providers": configured_count,
            "openclaw_hmac_configured": hmac_set,
        },
        "features": {
            "smart_intent_routing": True,
            "multi_tier_fallback": True,
            "token_budget_optimization": True,
            "openclaw_skill_orchestration": True,
        },
        "timestamp": time.time(),
    }


@router.get("/api/ai/models", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("60/minute")
async def list_ai_models(request: Request):
    """
    List all available and supported models across the swarm with their capabilities.
    """
    gateway_connected, active_url, live_models = await _probe_ai_gateway()

    if gateway_connected and live_models:
        return {
            "ok": True,
            "source": "live_gateway",
            "gateway_url": active_url,
            "count": len(live_models),
            "models": live_models,
        }

    # Offline/Fallback model catalog
    fallback_catalog = []
    for prov_id, meta in AI_PROVIDERS_CONFIG.items():
        is_set = _check_key_configured(meta.get("env_key"))
        for model_name in meta["default_models"]:
            fallback_catalog.append({
                "id": model_name,
                "provider": prov_id,
                "provider_name": meta["name"],
                "configured": is_set,
                "category": meta["category"],
            })

    return {
        "ok": True,
        "source": "catalog_fallback",
        "gateway_url": None,
        "gateway_connected": False,
        "count": len(fallback_catalog),
        "models": fallback_catalog,
        "note": "AI gateway at :20128 is currently offline or initialising. Start with ./unified.sh start",
    }


@router.post("/api/ai/route", dependencies=[Depends(require_openclaw_or_local)])
@limiter.limit("60/minute")
async def route_ai_prompt(request: Request, body: RouteRequest):
    """
    Analyzes prompt semantics and returns the optimal AI provider and model recommendation.
    """
    prompt = body.prompt.lower().strip()
    task_type = body.task_type.lower() if body.task_type else None

    # Domain classification
    is_code = bool(
        re.search(r"(```|def |function|class |error|traceback|debug|refactor|sql|postgres|python|typescript|docker|k8s|git|patch|diff)", prompt)
    )
    is_reasoning = bool(
        re.search(r"(plan|estrateg|arquitet|design|propos|compar|avali|revis|analis|por que|trade-off|decision|analys)", prompt)
    )
    is_fast = len(prompt.split()) <= 6 and not is_code

    if task_type == "code" or (not task_type and is_code):
        selected_category = "code"
        rec_cloud = "claude-3-7-sonnet" if _check_key_configured("ANTHROPIC_API_KEY") else ("deepseek-coder" if _check_key_configured("DEEPSEEK_API_KEY") else "gpt-4o")
        rec_local = "qwen2.5-coder:7b"
        reason = "Complex code generation and technical refactoring"
    elif task_type == "reasoning" or (not task_type and is_reasoning and len(prompt) > 25):
        selected_category = "reasoning"
        rec_cloud = "deepseek-reasoner" if _check_key_configured("DEEPSEEK_API_KEY") else ("o3-mini" if _check_key_configured("OPENAI_API_KEY") else "claude-3-7-sonnet")
        rec_local = "qwen2.5:7b-instruct"
        reason = "Multi-step analytical reasoning and strategic threat synthesis"
    elif task_type == "fast" or (not task_type and is_fast):
        selected_category = "fast"
        rec_cloud = "gpt-4o-mini" if _check_key_configured("OPENAI_API_KEY") else "gemini-2.5-flash"
        rec_local = "qwen2.5:0.5b"
        reason = "Short conversational interaction and quick triage"
    else:
        selected_category = "general"
        rec_cloud = "gemini-2.5-flash" if _check_key_configured("GEMINI_API_KEY") else ("gpt-4o-mini" if _check_key_configured("OPENAI_API_KEY") else "claude-3-5-haiku")
        rec_local = "qwen2.5:1.5b-instruct"
        reason = "Standard conversational intelligence"

    recommended_model = rec_local if body.prefer_local else rec_cloud

    return {
        "ok": True,
        "category": selected_category,
        "recommended_model": recommended_model,
        "recommended_local": rec_local,
        "recommended_cloud": rec_cloud,
        "reason": reason,
        "routing_engine": "VINCENT Semantic Dispatcher",
    }
