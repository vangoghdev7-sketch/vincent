"""
Vincent Device Layer — gerencia conexão serial, identidade e comandos.
Cada Device sabe o que é, o que pode fazer e o que não pode.
"""

import glob
import json
import os
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

try:
    import serial
except ImportError:
    serial = None

from .config import DEVICES, FIRMWARE, FLASH_IMAGES


# ─── Tipos ───────────────────────────────────────────────────────────────────

@dataclass
class DeviceEvent:
    device_id: str
    kind: str          # "connected" | "disconnected" | "data" | "command_result" | "error"
    payload: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self):
        return {
            "device_id": self.device_id,
            "kind":      self.kind,
            "payload":   self.payload,
            "ts":        self.ts,
        }


# ─── Identificação ───────────────────────────────────────────────────────────

def _read_all(ser: serial.Serial, first_byte_timeout: float = 3.5, drain_timeout: float = 0.5) -> str:
    """
    Aguarda até `first_byte_timeout` pelo primeiro byte,
    depois drena tudo até nada chegar por `drain_timeout` segundos.
    """
    chunks: list[bytes] = []
    # Espera o primeiro byte
    deadline = time.time() + first_byte_timeout
    while not ser.in_waiting:
        if time.time() >= deadline:
            return ""
        time.sleep(0.05)
    # Drena a rajada completa
    drain_dl = time.time() + drain_timeout
    while True:
        waiting = ser.in_waiting
        if waiting:
            chunks.append(ser.read(waiting))
            drain_dl = time.time() + drain_timeout
        elif time.time() >= drain_dl:
            break
        else:
            time.sleep(0.05)
    return b"".join(chunks).decode("utf-8", errors="replace")


# Mapeia firmware_id detectado em runtime → chave em FIRMWARE
_RUNTIME_FW_MAP = {
    "BRUCE":              "bruce-vdev",
    "VINCENT-OS":         "vincent-os-0.3.2",
    "MARAUDER":           "bruce-vdev",
    "ESP32DIV-CIFERTECH": "cifertech-1.5.3",
}

_BRUCE_KEYWORDS  = ["bruce", "wifi off", "wifi on", "arp - starts", "subghz", "webui"]
_VINCENT_KEYWORDS = ["vincent embed", "/status", "/wifi", "/ble", "/cc1101"]
_DIV_KEYWORDS    = ["esp32-div", "cifertech", "kilaz"]
_MARAUDER_KEYWORDS = ["marauder"]

def _classify_banner(text: str) -> Optional[str]:
    t = text.lower()
    if any(k in t for k in _BRUCE_KEYWORDS):    return "BRUCE"
    if any(k in t for k in _VINCENT_KEYWORDS):  return "VINCENT-OS"
    if any(k in t for k in _DIV_KEYWORDS):      return "ESP32DIV-CIFERTECH"
    if any(k in t for k in _MARAUDER_KEYWORDS): return "MARAUDER"
    return None

def _match_device_profile(firmware_id: Optional[str], port: str = "") -> Optional[str]:
    """Mapeia firmware detectado para device profile ID."""
    if firmware_id == "ESP32DIV-CIFERTECH":
        return "ESP32DIV"
    if firmware_id in ("BRUCE", "VINCENT-OS", "MARAUDER"):
        # CP2102 → /dev/ttyUSB* → ESP32DIV antes do flash
        if "USB" in port.upper():
            return "ESP32DIV"
        return "TEMBED"
    return None

def _esp_reset(ser: serial.Serial):
    ser.dtr = False; ser.rts = True;  time.sleep(0.1)
    ser.rts = False;                  time.sleep(0.1)
    ser.dtr = True


# ─── Device ──────────────────────────────────────────────────────────────────

class Device:
    """
    Representa um ESP conectado. Encapsula:
    - identidade (qual placa, qual firmware)
    - serial I/O com fila de leitura
    - envio de comandos com await de resposta
    - evento de dados recebidos
    """

    def __init__(self, dev_id: str, port: str, ser: serial.Serial,
                 firmware_id: str, on_event: Callable[[DeviceEvent], None]):
        self.id          = dev_id
        self.port        = port
        self.ser         = ser
        self.firmware_id = firmware_id
        self.on_event    = on_event
        self._rx_q: queue.Queue[str] = queue.Queue()
        self._lock       = threading.Lock()
        self._alive      = True
        self._profile    = DEVICES.get(dev_id, {})
        fw_key = _RUNTIME_FW_MAP.get(
            firmware_id,
            self._profile.get("firmware_current", "")
        )
        # ESP32DIV after flash (Bruce) → use bruce-generic-usbcdc profile for safe cmds
        if dev_id == "ESP32DIV" and firmware_id == "BRUCE":
            fw_key = "bruce-generic-usbcdc"
        self._fw_profile = FIRMWARE.get(fw_key, {})
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    # ── Propriedades ─────────────────────────────────────────────────────────

    @property
    def label(self) -> str:
        return self._profile.get("label", self.id)

    @property
    def hardware(self) -> list[str]:
        return self._profile.get("hardware", [])

    @property
    def has(self):
        hw = self.hardware
        class _Has:
            cc1101      = "cc1101" in hw
            nrf24       = "nrf24_x3" in hw
            ir          = "ir_tx" in hw
            wifi        = "wifi" in hw
            ble         = "ble" in hw
            display     = "display" in " ".join(hw)
            touch       = "touch_xpt2046" in hw
            sd          = "sd_card" in hw
            encoder     = "encoder" in hw
        return _Has()

    @property
    def protocol(self) -> Optional[str]:
        return self._fw_profile.get("protocol")

    @property
    def online(self) -> bool:
        return self._alive and self.ser.isOpen()

    def status_dict(self) -> dict:
        return {
            "id":        self.id,
            "label":     self.label,
            "port":      self.port,
            "firmware":  self.firmware_id,
            "protocol":  self.protocol,
            "hardware":  self.hardware,
            "online":    self.online,
        }

    # ── Verificação de segurança ──────────────────────────────────────────────

    def is_safe(self, cmd: str) -> tuple[bool, str]:
        """Retorna (pode_enviar, motivo_se_nao)."""
        if self.protocol is None:
            return False, "dispositivo não tem protocolo serial ativo — precisa de flash"
        blocked = self._fw_profile.get("blocked", {})
        cmd_lower = cmd.strip().lower()
        for pattern, reason in blocked.items():
            if cmd_lower.startswith(pattern.lower()):
                return False, f"BLOQUEADO: {reason}"
        return True, ""

    # ── Envio de comandos ─────────────────────────────────────────────────────

    def send(self, cmd: str, wait: float = 4.0) -> dict:
        """
        Envia comando e aguarda resposta.
        Retorna {"ok": bool, "cmd": str, "response": str, "blocked": bool}
        """
        ok, reason = self.is_safe(cmd)
        if not ok:
            return {"ok": False, "cmd": cmd, "response": reason, "blocked": True}

        with self._lock:
            # Limpa buffer pendente
            while not self._rx_q.empty():
                try: self._rx_q.get_nowait()
                except queue.Empty: break

            # Enter vazio para garantir prompt limpo (Bruce não interpreta Ctrl+C via serial)
            self.ser.write(b"\r\n")
            time.sleep(0.15)
            self.ser.reset_input_buffer()

            # Envia o comando
            self.ser.write((cmd + "\r\n").encode())

            # Coleta resposta
            lines: list[str] = []
            deadline = time.time() + wait
            while time.time() < deadline:
                try:
                    line = self._rx_q.get(timeout=0.15)
                    lines.append(line)
                    deadline = max(deadline, time.time() + 0.4)
                except queue.Empty:
                    if lines:
                        break

        response = "\n".join(lines)
        # Remove artefatos de protocolo Bruce (prompt + echo do comando)
        response = re.sub(r"(?:COMMAND:|#\s*COMMAND:)\s*[^\n]*\n?", "", response)
        # Remove bytes de controle e erros residuais
        response = re.sub(r"[\x03\x1b]+", "", response)
        response = re.sub(r"ERROR: Command not found at '[^']*'\n?", "", response)
        response = re.sub(r"#\s*\n", "\n", response)
        response = re.sub(r"\n{3,}", "\n\n", response).strip()

        event = DeviceEvent(self.id, "command_result", {
            "cmd": cmd, "response": response, "ok": True
        })
        self.on_event(event)
        return {"ok": True, "cmd": cmd, "response": response, "blocked": False}

    def send_json(self, cmd: str, wait: float = 3.0) -> dict:
        """Envia comando Vincent OS JSON e faz parse da resposta."""
        result = self.send(cmd, wait)
        if not result["ok"]:
            return result
        try:
            data = json.loads(result["response"])
            result["data"] = data
        except Exception:
            result["data"] = None
        return result

    # ── Loop de leitura ───────────────────────────────────────────────────────

    def _read_loop(self):
        reident_buf: list[str] = []
        while self._alive:
            try:
                if self.ser.in_waiting:
                    line = self.ser.readline().decode("utf-8", errors="replace").strip()
                    if line:
                        self._rx_q.put(line)
                        self.on_event(DeviceEvent(self.id, "data", {"line": line}))
                        # Re-identificação tardia para firmwares que só printam banner no boot
                        if self.firmware_id in (None, "unknown"):
                            reident_buf.append(line)
                            if len(reident_buf) >= 3:
                                banner = "\n".join(reident_buf)
                                fw = _classify_banner(banner)
                                if fw:
                                    self.firmware_id = fw
                                    pid = _match_device_profile(fw, self.port)
                                    if pid and pid != self.id:
                                        self.id = pid
                                        new_key = _RUNTIME_FW_MAP.get(fw,
                                            DEVICES.get(pid, {}).get("firmware_current", ""))
                                        self._fw_profile = FIRMWARE.get(new_key, {})
                                        self._profile    = DEVICES.get(pid, {})
                                        self.on_event(DeviceEvent(
                                            self.id, "reidentified",
                                            {"firmware": fw, "new_id": pid}
                                        ))
                                reident_buf.clear()
            except Exception:
                self._alive = False
                self.on_event(DeviceEvent(self.id, "disconnected", {}))
                break
            time.sleep(0.02)

    def close(self):
        self._alive = False
        try: self.ser.close()
        except Exception: pass


# ─── Registry ────────────────────────────────────────────────────────────────

class DeviceRegistry:
    """
    Detecta, identifica e gerencia todos os ESPs conectados.
    Thread-safe. Emite eventos via callback.
    """

    def __init__(self, on_event: Callable[[DeviceEvent], None]):
        self.on_event = on_event
        self._devices: dict[str, Device] = {}
        self._lock    = threading.Lock()

    # ── Detecção ──────────────────────────────────────────────────────────────

    def scan(self, quick: bool = True) -> list[Device]:
        """Varre portas USB, identifica dispositivos e conecta os novos. Multiplataforma (Linux/Windows/macOS/Termux)."""
        if serial is None:
            return []
        # pyserial não tem backend de enumeração pra Android/Termux (emite warning ruidoso
        # e não acha nada mesmo) — pula direto pro fallback silencioso via /dev
        is_android = "ANDROID_ROOT" in os.environ or "ANDROID_DATA" in os.environ
        try:
            if is_android:
                raise ImportError
            from serial.tools import list_ports
            # hwid == "n/a" = porta serial fixa (ex: UART de placa-mãe), não USB-serial real
            ports = sorted(p.device for p in list_ports.comports() if p.hwid != "n/a")
        except ImportError:
            ports = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
        connected = []
        for port in ports:
            dev = self._try_connect(port, quick=quick)
            if dev:
                connected.append(dev)
        return connected

    def _try_connect(self, port: str, quick: bool = True) -> Optional[Device]:
        with self._lock:
            # Já conectado nesta porta?
            for d in self._devices.values():
                if d.port == port and d.online:
                    return d

        try:
            timeout_first = 0.4 if quick else 2.0
            ser = serial.Serial(port, 115200, timeout=1)
            time.sleep(0.1 if quick else 0.4)
            ser.reset_input_buffer()

            # Primeira tentativa: envia Enter + help para acordar o shell
            ser.write(b"\r\nhelp\r\n")
            banner = _read_all(ser, first_byte_timeout=timeout_first, drain_timeout=0.2)

            if not banner.strip() and not quick:
                # Dispositivo mudo → Ctrl+C sai de submenus + help
                ser.write(b"\x03\r\nhelp\r\n")
                banner = _read_all(ser, first_byte_timeout=1.5, drain_timeout=0.3)

            if not banner.strip() and not quick:
                _esp_reset(ser)
                time.sleep(0.5)
                banner = _read_all(ser, first_byte_timeout=3.0, drain_timeout=0.5)
                if not banner.strip():
                    # Último recurso: já bootado, pede help
                    ser.write(b"\r\nhelp\r\n")
                    banner = _read_all(ser, first_byte_timeout=3.0)

            firmware_id = _classify_banner(banner)
            profile_id  = _match_device_profile(firmware_id, port)

            # Bruce em ACM: sonda "dual status" para distinguir T-Embed do ESP32DIV flashado.
            # ESP32DIV responde com info de slot OTA; T-Embed retorna "command not found".
            if firmware_id == "BRUCE" and "ACM" in port.upper():
                ser.write(b"\r\ndual status\r\n")
                time.sleep(2.0)
                probe = ser.read(512).decode("utf-8", errors="replace").lower()
                if any(k in probe for k in ("slot", "ota_", "dual")):
                    profile_id = "ESP32DIV"
                else:
                    profile_id = "TEMBED"

            if not firmware_id:
                firmware_id = "ESP32-S3 (Universal)"
            if not profile_id or profile_id.startswith("ESP-"):
                profile_id = "TEMBED" if "ACM" in port.upper() else "ESP32DIV"

            dev_id = profile_id
            # Resolve conflitos de ID (dois devices mesma família)
            with self._lock:
                if dev_id in self._devices and self._devices[dev_id].online:
                    dev_id = f"{profile_id}-2"

            dev = Device(dev_id, port, ser, firmware_id, self.on_event)

            with self._lock:
                self._devices[dev_id] = dev

            self.on_event(DeviceEvent(dev_id, "connected", dev.status_dict()))
            return dev

        except Exception:
            return None

    # ── Acesso ────────────────────────────────────────────────────────────────

    def get(self, dev_id: str) -> Optional[Device]:
        with self._lock:
            return self._devices.get(dev_id)

    def all(self) -> list[Device]:
        with self._lock:
            return [d for d in self._devices.values() if d.online]

    def all_dict(self) -> list[dict]:
        return [d.status_dict() for d in self.all()]

    def send(self, dev_id: str, cmd: str, wait: float = 4.0) -> dict:
        dev = self.get(dev_id)
        if not dev:
            return {"ok": False, "cmd": cmd, "response": f"dispositivo {dev_id} não encontrado", "blocked": False}
        return dev.send(cmd, wait)

    def close_all(self):
        with self._lock:
            for d in self._devices.values():
                d.close()
            self._devices.clear()
