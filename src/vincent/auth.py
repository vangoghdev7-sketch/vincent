"""
Vincent CLI 4.0 — Local Key Vault & Credential Manager.
Stores user API keys and endpoints in ~/.vincent/credentials.json with strict
OS-level permissions (chmod 0600) so only the owner/root user can read/write.
"""

import os
import json
import getpass
import time
from typing import Dict, Any, Optional

CREDENTIALS_FILE = os.path.expanduser("~/.vincent/credentials.json")

SUPPORTED_PROVIDERS = {
    "omniroute": "Chave Neural OmniRoute / Galeria Vincent",
    "openai": "OpenAI API Key (sk-...)",
    "anthropic": "Anthropic API Key (sk-ant-...)",
    "gemini": "Google Gemini API Key (AIza...)",
    "deepseek": "DeepSeek API Key (sk-...)",
    "ollama_host": "Host do Ollama Local (ex: http://127.0.0.1:11434)"
}

class VincentAuth:
    """Gerenciador seguro de credenciais e chaves de API locais."""

    def __init__(self):
        self.credentials: Dict[str, Any] = {}
        self.load_credentials()

    def load_credentials(self) -> Dict[str, Any]:
        """Carrega o cofre de credenciais do disco."""
        if os.path.exists(CREDENTIALS_FILE):
            try:
                with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                    self.credentials = json.load(f)
            except Exception:
                self.credentials = {}
        else:
            self.credentials = {}
        self._export_to_env()
        return self.credentials

    def save_credentials(self):
        """Salva as credenciais e aplica chmod 0600 estrito."""
        os.makedirs(os.path.dirname(CREDENTIALS_FILE), exist_ok=True)
        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.credentials, f, indent=2)
        try:
            os.chmod(CREDENTIALS_FILE, 0o600)
        except Exception:
            pass
        self._export_to_env()

    def _export_to_env(self):
        """Injeta credenciais no ambiente do processo atual."""
        mapping = {
            "omniroute": ["OMNIROUTE_API_KEY", "VINCENT_AUTH_KEY"],
            "openai": ["OPENAI_API_KEY"],
            "anthropic": ["ANTHROPIC_API_KEY"],
            "gemini": ["GEMINI_API_KEY"],
            "deepseek": ["DEEPSEEK_API_KEY"],
            "ollama_host": ["OLLAMA_HOST"]
        }
        for provider, env_vars in mapping.items():
            val = self.credentials.get(provider)
            if val:
                for var in env_vars:
                    os.environ[var] = str(val)

    def set_key(self, provider: str, key_value: str) -> bool:
        """Salva uma chave de API para o provedor especificado."""
        provider_clean = provider.strip().lower()
        key_clean = key_value.strip()
        if not key_clean:
            return False
        self.credentials[provider_clean] = key_clean
        self.credentials[f"_{provider_clean}_updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.save_credentials()
        return True

    def get_key(self, provider: str) -> Optional[str]:
        """Recupera a chave de um provedor."""
        return self.credentials.get(provider.strip().lower())

    def remove_key(self, provider: str) -> bool:
        """Remove a chave de um provedor do cofre."""
        provider_clean = provider.strip().lower()
        if provider_clean in self.credentials:
            del self.credentials[provider_clean]
            self.credentials.pop(f"_{provider_clean}_updated_at", None)
            self.save_credentials()
            return True
        return False

    def interactive_login(self, provider: str = "omniroute") -> bool:
        """Solicita a chave via terminal seguro sem eco (getpass)."""
        prov_label = SUPPORTED_PROVIDERS.get(provider.lower(), provider)
        print(f"\n🔐 Inserindo credencial para: {prov_label}")
        try:
            secret = getpass.getpass("Chave de API (oculta): ").strip()
            if not secret:
                print("⚠ Nenhuma chave fornecida. Operação cancelada.")
                return False
            self.set_key(provider, secret)
            print(f"✓ Credencial para '{provider}' salva com sucesso em {CREDENTIALS_FILE} (chmod 0600).\n")
            return True
        except (KeyboardInterrupt, EOFError):
            print("\nOperação cancelada.")
            return False

    @property
    def is_authenticated(self) -> bool:
        """Verifica se há ao menos uma chave configurada no cofre."""
        keys = [k for k in self.credentials.keys() if not k.startswith("_")]
        return len(keys) > 0

    @property
    def identity(self) -> str:
        if self.is_authenticated:
            return "Desenvolvedor Autenticado (Root/Vault)"
        return "Visitante do Atelier (Zero-Key / Gratuito)"

    @property
    def tier(self) -> str:
        if self.is_authenticated:
            return "Key Vault Ativo (Chmod 0600) ⚡"
        return "Atelier Comunitário 🆓"

    def status_card_data(self) -> list[tuple[str, str]]:
        """Gera dados para o HUD Starry Night."""
        items = [
            ("ARQUIVO DO COFRE", f"{CREDENTIALS_FILE} (0600)"),
            ("STATUS DO COFRE", "🟢 CHAVES ATIVAS" if self.is_authenticated else "🟡 MODO ZERO-KEY")
        ]
        for p, desc in SUPPORTED_PROVIDERS.items():
            val = self.credentials.get(p)
            if val:
                masked = val[:4] + "..." + val[-4:] if len(val) > 10 else "***"
                items.append((p.upper(), f"✓ Configurado ({masked})"))
            else:
                items.append((p.upper(), "○ Não configurado"))
        return items
