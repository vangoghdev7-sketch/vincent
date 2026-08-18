"""
Vincent CLI — local API key vault ('Galeria Vincent').
Key stored at ~/.vincent/auth.json, chmod 0600.
"""

import os
import json
import time
import urllib.request
import urllib.error
from typing import Optional, Dict, Any

AUTH_FILE = os.path.expanduser("~/.vincent/auth.json")

class VincentAuth:
    """Gerenciador de Credenciais e Autenticação da Galeria Vincent."""

    def __init__(self):
        self.session_data: Dict[str, Any] = {}
        self.load_session()

    def load_session(self) -> Dict[str, Any]:
        """Carrega a sessão ativa salva localmente."""
        if os.path.exists(AUTH_FILE):
            try:
                with open(AUTH_FILE, "r", encoding="utf-8") as f:
                    self.session_data = json.load(f)
            except Exception:
                self.session_data = {}
        else:
            self.session_data = {}
        return self.session_data

    def save_session(self):
        """Salva a sessão com permissões restritas (0600)."""
        try:
            os.makedirs(os.path.dirname(AUTH_FILE), exist_ok=True)
            with open(AUTH_FILE, "w", encoding="utf-8") as f:
                json.dump(self.session_data, f, indent=2)
            os.chmod(AUTH_FILE, 0o600)
        except Exception:
            pass

    @property
    def is_authenticated(self) -> bool:
        """Verifica se há token ou chave neural ativa."""
        return bool(self.session_data.get("token") or self.session_data.get("api_key"))

    @property
    def identity(self) -> str:
        """Retorna o codinome ou e-mail autenticado."""
        return self.session_data.get("user", "Pintor Autônomo (Zero-Key)")

    @property
    def tier(self) -> str:
        """Retorna o plano neural ativo."""
        return self.session_data.get("tier", "Atelier Comunitário 🆓")

    def login_with_key(self, api_key: str, user_label: str = "Pintor Registrado") -> bool:
        """Injeta uma Chave Neural da Galeria Vincent."""
        key_clean = api_key.strip()
        if not key_clean:
            return False
        
        self.session_data = {
            "api_key": key_clean,
            "user": user_label,
            "tier": "Galeria Mestre Pro ⚡",
            "auth_type": "neural_key",
            "connected_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        self.save_session()
        # Exporta para ambiente de execução
        os.environ["VINCENT_AUTH_KEY"] = key_clean
        os.environ["OMNIROUTE_API_KEY"] = key_clean
        return True

    def logout(self) -> bool:
        """Desconecta a sessão atual."""
        self.session_data = {}
        if os.path.exists(AUTH_FILE):
            try:
                os.remove(AUTH_FILE)
            except Exception:
                pass
        return True

    def status_card_data(self) -> list[tuple[str, str]]:
        """Dados formatados para renderização no HUD."""
        if self.is_authenticated:
            return [
                ("STATUS DA GALERIA", "🟢 CONECTADO"),
                ("IDENTIDADE", self.identity),
                ("PLANO NEURAL", self.tier),
                ("MÉTODO DE ACESSO", self.session_data.get("auth_type", "Chave Neural")),
                ("DESDE", self.session_data.get("connected_at", "--"))
            ]
        else:
            return [
                ("STATUS DA GALERIA", "🟡 MODO PÚBLICO / ZERO-KEY"),
                ("IDENTIDADE", "Visitante do Atelier"),
                ("MODELOS DISPONÍVEIS", "1200+ Rotas Gratuitas + Offline"),
                ("LOGIN", "Use /login ou /key <chave> para desbloquear Atelier Pro")
            ]
