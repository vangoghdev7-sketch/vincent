"""
Vincent CLI 4.0 — Unified Model Hub & 1200+ OmniRoute Engine.
Integrates OmniRoute Gateway, Local Ollama Models, Zero-Key Free Gateways,
and Smart Adaptive Cascade Failover.
"""

import base64
import json
import mimetypes
import os
import time
import urllib.request
import urllib.error
from typing import Optional, List, Dict, Tuple, Any, Callable

from .routing.resilience import CircuitBreaker, Cooldown

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def build_image_content(prompt: str, image_path: str) -> List[Dict]:
    """
    Monta o 'content' multimodal (formato OpenAI-compatible: text + image_url em base64)
    a partir de uma imagem local. OmniRoute/gateways cloud entendem esse formato nativamente;
    execute_inference converte pro formato nativo do Ollama quando a rota é local.
    """
    abs_path = os.path.abspath(os.path.expanduser(image_path))
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Imagem não encontrada: {image_path}")
    ext = os.path.splitext(abs_path)[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ValueError(f"Extensão não suportada: {ext} (aceitos: {', '.join(sorted(IMAGE_EXTENSIONS))})")

    with open(abs_path, "rb") as f:
        b64_data = base64.b64encode(f.read()).decode("ascii")
    media_type = mimetypes.guess_type(abs_path)[0] or "image/jpeg"

    return [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64_data}"}}
    ]


def _messages_for_ollama(messages: List[Dict]) -> List[Dict]:
    """Ollama não entende 'content' como lista OpenAI-style — usa content:str + images:[base64]."""
    converted = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            text_parts, images = [], []
            for part in content:
                if part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
                elif part.get("type") == "image_url":
                    url = part.get("image_url", {}).get("url", "")
                    if url.startswith("data:") and "," in url:
                        images.append(url.split(",", 1)[1])
            new_msg = {"role": msg.get("role", "user"), "content": "\n".join(text_parts)}
            if images:
                new_msg["images"] = images
            converted.append(new_msg)
        else:
            converted.append(msg)
    return converted

OMNIROUTE_URL = os.environ.get("VINCENT_GATEWAY_URL", os.environ.get("OMNIROUTE_URL", "http://localhost:20128/v1")).rstrip("/")
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
        self._omniroute_circuit = CircuitBreaker("api_key")
        self._ollama_circuit = CircuitBreaker("local")
        self._omniroute_cooldown = Cooldown("api_key")
        self._load_cache()
        # Nível de esforço/raciocínio: ajusta num_predict + temperatura. /effort no REPL.
        self.effort = os.environ.get("VINCENT_EFFORT", "medium")

    # (num_predict, temperature) por nível de effort
    _EFFORT_OPTS = {"low": (384, 0.2), "medium": (768, 0.3), "high": (2048, 0.45)}

    def _ollama_options(self) -> Dict[str, Any]:
        np_, temp_ = self._EFFORT_OPTS.get(self.effort, self._EFFORT_OPTS["medium"])
        return {"num_predict": np_, "temperature": temp_}

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
                    omni = data.get("omniroute", [])
                    ollama = data.get("ollama", [])
                    self.cached_omniroute_models = omni if isinstance(omni, list) else []
                    self.cached_ollama_models = ollama if isinstance(ollama, list) else []
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
            omni_headers = {"User-Agent": "Vincent-CLI/4.0"}
            api_key = os.environ.get("OMNIROUTE_API_KEY") or os.environ.get("VINCENT_AUTH_KEY")
            if api_key:
                omni_headers["Authorization"] = f"Bearer {api_key}"
            req = urllib.request.Request(f"{OMNIROUTE_URL}/models", headers=omni_headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                new_omni = None
                if isinstance(data, dict) and isinstance(data.get("data"), list):
                    new_omni = data["data"]
                elif isinstance(data, list):
                    new_omni = data
                if new_omni:
                    # Só substitui o cache se a resposta trouxe modelos de verdade —
                    # uma resposta 200 com lista vazia (hiccup do gateway) não pode
                    # apagar um catálogo bom que já tínhamos.
                    self.cached_omniroute_models = new_omni
                omni_count = len(self.cached_omniroute_models)
        except Exception:
            pass

        # 2. Ollama Local
        ollama_count = len(self.cached_ollama_models)
        try:
            req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.cached_ollama_models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                ollama_count = len(self.cached_ollama_models)
        except Exception:
            pass

        self.last_sync = time.time()
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

    def gateway_status(self) -> Dict[str, Any]:
        """
        Status do gateway OmniRoute detectado em OMNIROUTE_URL.
        Nota: a doc real (docs/routing/AUTO-COMBO.md) não documenta nenhum
        header de resposta identificando a rota/provider escolhido — não
        expomos nada tipo "decisão de rota" que não exista de verdade.
        """
        return {
            "url": OMNIROUTE_URL,
            "reachable": len(self.cached_omniroute_models) > 0,
            "model_count": len(self.cached_omniroute_models),
            "circuit_state": self._omniroute_circuit.get_state("omniroute"),
            "cooldown_active": not self._omniroute_cooldown.is_available("omniroute"),
        }

    def is_free_tier(self, model_name: str) -> bool:
        if model_name in self.cached_ollama_models:
            return True
        return any(k in model_name.lower() for k in ["free", "tllm", "oc", "ddgw", "felo", "pepper", "auto"])

    def execute_inference(self, messages: List[Dict], target_model: str, system_prompt: str = "",
                          stream_callback: Optional[Callable[[str], None]] = None) -> Tuple[Optional[str], str, float]:
        """
        Executa inferência com cascata inteligente e failover automático.
        Retorna (texto_resposta, modelo_utilizado, tempo_gasto).

        Se `stream_callback` for fornecido E a rota escolhida for local (Ollama),
        a resposta é lida token a token: o texto completo é acumulado e retornado
        igual antes, mas cada pedaço parcial também é entregue via stream_callback(pedaço)
        em tempo real. Quando None, mantém o comportamento antigo (stream=False).
        O OmniRoute não streama (fica igual) — foco no Ollama local.
        """
        import time
        t0 = time.time()

        if not messages:
            return "[VINCENT] Nenhuma mensagem para enviar — o prompt está vazio.", target_model, 0.0

        # Monta cascata de modelos prioritários (resolve ID exibido para ID real upstream)
        cascade: List[str] = [self.resolve(target_model)]

        # Se for local, garante fallback em outros locais
        for local_m in ["qwen2.5:3b-instruct", "qwen2.5-coder:7b", "qwen3:4b", "granite4:tiny-h"]:
            if local_m in self.cached_ollama_models and local_m not in cascade:
                cascade.append(local_m)

        # Adiciona rotas do OmniRoute. IDs reais confirmados em
        # docs/routing/AUTO-COMBO.md do diegosouzapw/OmniRoute (MIT) —
        # os antigos "auto/best-*" eram aproximação, não existem no gateway real.
        for omni_m in ["auto/cheap", "auto/coding", "auto/smart", "auto/fast", "auto"]:
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
                if not self._ollama_circuit.can_execute("ollama"):
                    last_error = f"Vincent Local ({model}): circuito aberto (falhas recentes)"
                    continue
                try:
                    use_stream = stream_callback is not None
                    payload = {
                        "model": ollama_name,
                        "messages": _messages_for_ollama(
                            ([{"role": "system", "content": system_prompt}] if system_prompt else []) + messages
                        ),
                        "stream": use_stream,
                        "think": False,
                        # num_thread removido: deixa o Ollama auto-detectar e usar
                        # todos os núcleos físicos (a máquina tem 12 threads; o fixo
                        # em 4 tornava a inferência de modelos 7B/8B ~3x mais lenta).
                        "options": self._ollama_options()
                    }
                    req = urllib.request.Request(
                        f"{OLLAMA_URL}/api/chat",
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST"
                    )
                    # Timeout generoso: modelos 7B/8B no CPU (sem GPU) podem levar
                    # dezenas de segundos pra gerar 512 tokens. O antigo 25s foi
                    # calibrado pro qwen3:0.6b e estourava com modelos maiores.
                    timeout_val = 300 if idx == 0 else 120
                    with urllib.request.urlopen(req, timeout=timeout_val) as resp:
                        if use_stream:
                            # Streaming: cada linha é um JSON com message.content parcial
                            # e um flag done. Acumula o texto completo e repassa cada
                            # pedaço ao callback em tempo real.
                            parts: List[str] = []
                            for raw_line in resp:
                                line = raw_line.decode("utf-8").strip()
                                if not line:
                                    continue
                                try:
                                    chunk = json.loads(line)
                                except Exception:
                                    continue
                                msg_obj = chunk.get("message") if isinstance(chunk, dict) else None
                                piece = msg_obj.get("content", "") if isinstance(msg_obj, dict) else ""
                                if piece:
                                    parts.append(piece)
                                    try:
                                        stream_callback(piece)
                                    except Exception:
                                        pass  # callback do usuário não pode derrubar a inferência
                                if isinstance(chunk, dict) and chunk.get("done"):
                                    break
                            text = "".join(parts).strip()
                        else:
                            res_data = json.loads(resp.read().decode("utf-8"))
                            msg_obj = res_data.get("message") if isinstance(res_data, dict) else None
                            text = (msg_obj.get("content", "") if isinstance(msg_obj, dict) else "").strip()
                        if text:
                            self._ollama_circuit.record_result("ollama", success=True)
                            dt = time.time() - t0
                            return text, model, dt
                    self._ollama_circuit.record_result("ollama", success=False, status_code=503)
                    last_error = f"Vincent Local ({model}): resposta vazia"
                    continue
                except Exception as e:
                    code = e.code if isinstance(e, urllib.error.HTTPError) else 503
                    self._ollama_circuit.record_result("ollama", success=False, status_code=code)
                    last_error = f"Vincent Local ({model}): {e}"
                    if stream_callback is not None:
                        try:
                            stream_callback(f"\n\n[Vincent] \u26a0 {model} falhou ({e}) \u2014 tentando pr\u00f3ximo modelo da cascata...\n\n")
                        except Exception:
                            pass  # callback do usu\u00e1rio n\u00e3o pode derrubar o failover
                    continue

            # 2. Tentativa via OmniRoute Gateway
            if not self._omniroute_circuit.can_execute("omniroute"):
                last_error = f"Vincent Cloud ({self.mask(model)}): circuito aberto (falhas recentes)"
                continue
            if not self._omniroute_cooldown.is_available("omniroute"):
                last_error = f"Vincent Cloud ({self.mask(model)}): em cooldown (rate limit recente)"
                continue
            try:
                headers = {"Content-Type": "application/json"}
                api_key = os.environ.get("OMNIROUTE_API_KEY") or os.environ.get("VINCENT_AUTH_KEY")
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

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
                    choices = res_data.get("choices") if isinstance(res_data, dict) else None
                    first = choices[0] if choices and isinstance(choices, list) and isinstance(choices[0], dict) else {}
                    msg = first.get("message") if isinstance(first.get("message"), dict) else {}
                    text = (msg.get("content") or "").strip()
                    if text:
                        self._omniroute_circuit.record_result("omniroute", success=True)
                        self._omniroute_cooldown.record_success("omniroute")
                        dt = time.time() - t0
                        return text, model, dt
                self._omniroute_circuit.record_result("omniroute", success=False, status_code=503)
            except Exception as e:
                code = e.code if isinstance(e, urllib.error.HTTPError) else 503
                if code == 429:
                    retry_after_sec = None
                    if isinstance(e, urllib.error.HTTPError) and e.headers:
                        raw = e.headers.get("Retry-After")
                        try:
                            retry_after_sec = float(raw) if raw else None
                        except ValueError:
                            retry_after_sec = None  # Retry-After em formato de data HTTP, não segundos — usa fallback
                    self._omniroute_cooldown.record_failure("omniroute", retry_after_sec=retry_after_sec)
                else:
                    self._omniroute_circuit.record_result("omniroute", success=False, status_code=code)
                last_error = f"Vincent Cloud ({self.mask(model)}): {e}"
                continue

        # Se todas as rotas falharem
        dt = time.time() - t0
        has_local = bool(self.cached_ollama_models)
        has_key = bool(os.environ.get("OMNIROUTE_API_KEY") or os.environ.get("VINCENT_AUTH_KEY"))
        if not has_local and not has_key:
            # Caso mais comum em instalação nova: sem Ollama local e sem
            # chave configurada — erro cru de urllib não ajuda ninguém,
            # aqui é guiar pro próximo passo real.
            err_msg = (
                "[VINCENT] Nenhum motor de IA disponível ainda. Escolha um caminho:\n"
                "  1. /vault — cole uma chave de API (OpenAI/Anthropic/Gemini/DeepSeek)\n"
                "  2. instale o Ollama (https://ollama.com) e rode: ollama pull qwen3:0.6b\n"
                "  3. tem um gateway OmniRoute rodando em outra máquina? export "
                "VINCENT_GATEWAY_URL=http://<ip>:20128/v1 antes de abrir o vincent"
            )
        else:
            err_msg = f"[ERRO NEURAL VINCENT] Não foi possível obter resposta após cascata em {len(models_ordered)} modelos. Último erro: {last_error}"
        return err_msg, target_model, dt
