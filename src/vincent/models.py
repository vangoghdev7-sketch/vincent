"""
Vincent CLI 4.0 — Unified Model Hub & 1200+ OmniRoute Engine.
Integrates OmniRoute Gateway, Local Ollama Models, Zero-Key Free Gateways,
and Smart Adaptive Cascade Failover.
"""

import json
import os
import time
import urllib.request
import urllib.error
from typing import Optional, List, Dict, Tuple

OMNIROUTE_URL = os.environ.get("OMNIROUTE_URL", "http://localhost:20128/v1").rstrip("/")
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
if not OLLAMA_URL.startswith("http"):
    OLLAMA_URL = "http://" + OLLAMA_URL

DEFAULT_MODEL = os.environ.get("VINCENT_MODEL", "qwen3:0.6b")

CACHE_PATH = os.path.expanduser("~/.vincent/models_cache.json")

class ModelManager:
    """Orquestrador Central de 1200+ Modelos de IA para o Vincent."""

    def __init__(self):
        self.cached_omniroute_models: List[Dict] = []
        self.cached_ollama_models: List[str] = []
        self.last_sync = 0.0
        self.display_to_real: Dict[str, str] = {}
        self._load_cache()

    @staticmethod
    def mask(model_id: str) -> str:
        """Rebrand a rota upstream (tllm/, oc/, ddgw/, felo/, aug/, ...) como 'vincent/'.
        Combos 'auto/*' são do próprio roteador, não de terceiro — ficam como estão."""
        if "/" in model_id and not model_id.startswith("auto/") and model_id != "auto":
            return "vincent/" + model_id.split("/", 1)[1]
        return model_id

    def resolve(self, display_or_real_id: str) -> str:
        """Traduz um id exibido (mascarado) de volta pro id real usado na chamada upstream."""
        return self.display_to_real.get(display_or_real_id, display_or_real_id)

    def _load_cache(self):
        if os.path.exists(CACHE_PATH):
            try:
                with open(CACHE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.cached_omniroute_models = data.get("omniroute", [])
                    self.cached_ollama_models = data.get("ollama", [])
            except Exception:
                pass

    def _save_cache(self):
        try:
            os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "omniroute": self.cached_omniroute_models,
                    "ollama": self.cached_ollama_models,
                    "ts": time.time()
                }, f, indent=2)
        except Exception:
            pass

    def sync_catalogs(self) -> Tuple[int, int]:
        """Sincroniza os catálogos do OmniRoute e do Ollama local."""
        # 1. OmniRoute
        omni_count = len(self.cached_omniroute_models)
        try:
            req = urllib.request.Request(f"{OMNIROUTE_URL}/models", headers={"User-Agent": "Vincent-CLI/4.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict) and "data" in data:
                    self.cached_omniroute_models = data["data"]
                elif isinstance(data, list):
                    self.cached_omniroute_models = data
                omni_count = len(self.cached_omniroute_models)
        except Exception:
            pass

        # 2. Ollama Local
        ollama_count = len(self.cached_ollama_models)
        try:
            req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.cached_ollama_models = [m.get("name") for m in data.get("models", [])]
                ollama_count = len(self.cached_ollama_models)
        except Exception:
            pass

        self._save_cache()
        return omni_count, ollama_count

    def get_all_models(self) -> List[Dict]:
        """Retorna lista consolidada de todos os modelos disponíveis."""
        if not self.cached_omniroute_models and not self.cached_ollama_models:
            self.sync_catalogs()

        models = []
        self.display_to_real = {}

        # Adiciona modelos locais do Ollama com badge especial
        for m in self.cached_ollama_models:
            models.append({
                "id": m,
                "display_id": m,
                "name": f"{m} (Local Offline Zero-Key)",
                "provider": "vincent-local",
                "is_free": True,
                "is_local": True
            })

        # Adiciona modelos do OmniRoute (rebrandado — upstream nunca exposto)
        for m in self.cached_omniroute_models:
            m_id = m.get("id", "")
            disp = self.mask(m_id)
            self.display_to_real[disp] = m_id
            is_free = any(k in m_id.lower() for k in ["free", "tllm", "oc", "ddgw", "felo", "pepper", "auto"])
            models.append({
                "id": m_id,
                "display_id": disp,
                "name": self.mask(m.get("name", m_id)),
                "provider": "vincent-cloud",
                "is_free": is_free,
                "is_local": False
            })

        return models

    def is_free_tier(self, model_name: str) -> bool:
        if model_name in self.cached_ollama_models:
            return True
        return any(k in model_name.lower() for k in ["free", "tllm", "oc", "ddgw", "felo", "pepper", "auto"])

    def execute_inference(self, messages: List[Dict], target_model: str, system_prompt: str = "") -> Tuple[Optional[str], str, float]:
        """
        Executa inferência com cascata inteligente e failover automático.
        Retorna (texto_resposta, modelo_utilizado, tempo_gasto).
        """
        import time
        t0 = time.time()

        # Monta cascata de modelos prioritários
        cascade: List[str] = [target_model]

        # Se for local, garante fallback em outros locais
        for local_m in ["qwen2.5:3b-instruct", "qwen2.5-coder:7b", "qwen3:4b", "granite4:tiny-h"]:
            if local_m in self.cached_ollama_models and local_m not in cascade:
                cascade.append(local_m)

        # Adiciona rotas do OmniRoute
        for omni_m in ["auto/best-free", "auto/best-coding", "auto/smart", "auto"]:
            if omni_m not in cascade:
                cascade.append(omni_m)

        # Remove duplicados preservando ordem
        seen = set()
        models_ordered = [m for m in cascade if not (m in seen or seen.add(m))]

        last_error = ""

        for idx, model in enumerate(models_ordered):
            # 1. Tentativa via Ollama Local
            if model in self.cached_ollama_models or model.startswith("ollama/"):
                ollama_name = model.replace("ollama/", "")
                try:
                    payload = {
                        "model": ollama_name,
                        "messages": ([{"role": "system", "content": system_prompt}] if system_prompt else []) + messages,
                        "stream": False,
                        "options": {"num_predict": 512, "temperature": 0.3, "num_thread": 4}
                    }
                    req = urllib.request.Request(
                        f"{OLLAMA_URL}/api/chat",
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST"
                    )
                    timeout_val = 25 if idx == 0 else 12
                    with urllib.request.urlopen(req, timeout=timeout_val) as resp:
                        res_data = json.loads(resp.read().decode("utf-8"))
                        text = res_data.get("message", {}).get("content", "").strip()
                        if text:
                            dt = time.time() - t0
                            return text, model, dt
                except Exception as e:
                    last_error = f"Ollama ({model}): {e}"
                    continue

            # 2. Tentativa via OmniRoute Gateway
            try:
                headers = {"Content-Type": "application/json"}
                if "OMNIROUTE_API_KEY" in os.environ:
                    headers["Authorization"] = f"Bearer {os.environ['OMNIROUTE_API_KEY']}"

                omni_payload = {
                    "model": model,
                    "messages": ([{"role": "system", "content": system_prompt}] if system_prompt else []) + messages,
                    "stream": False,
                    "temperature": 0.3
                }
                req = urllib.request.Request(
                    f"{OMNIROUTE_URL}/chat/completions",
                    data=json.dumps(omni_payload).encode("utf-8"),
                    headers=headers,
                    method="POST"
                )
                timeout_val = 20 if idx == 0 else 10
                with urllib.request.urlopen(req, timeout=timeout_val) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    text = res_data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                    if text:
                        dt = time.time() - t0
                        return text, model, dt
            except Exception as e:
                last_error = f"OmniRoute ({model}): {e}"
                continue

        # Se todas as rotas falharem
        dt = time.time() - t0
        err_msg = f"[ERRO NEURAL VINCENT] Não foi possível obter resposta após cascata em {len(models_ordered)} modelos. Último erro: {last_error}"
        return err_msg, target_model, dt
