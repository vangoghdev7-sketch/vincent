"""
Vincent CLI 4.0 — 'Be Water' Universal Environment & Platform Detector.
Adapts dynamically to Termux (Android mobile/ADB root), Linux Desktop/Server, macOS and Windows.
Optimizes memory buffers, layout columns, and serial USB device bindings.
"""

import os
import sys
import shutil
from typing import Dict, Any

class PlatformEnvironment:
    """Detecção e adaptação contextual ao ambiente de execução."""

    @staticmethod
    def is_termux() -> bool:
        """Verifica se está rodando no ambiente Termux (Android)."""
        return "com.termux" in os.environ.get("PREFIX", "") or os.path.exists("/data/data/com.termux")

    @staticmethod
    def is_android_adb() -> bool:
        """Verifica se está rodando em shell ADB com privilégios root."""
        return os.path.exists("/system/bin/app_process") or os.environ.get("ANDROID_ROOT") is not None

    @staticmethod
    def is_mobile() -> bool:
        return PlatformEnvironment.is_termux() or PlatformEnvironment.is_android_adb()

    @staticmethod
    def get_os_type() -> str:
        if PlatformEnvironment.is_termux():
            return "termux-android"
        if PlatformEnvironment.is_android_adb():
            return "adb-root-android"
        return sys.platform

    @staticmethod
    def get_terminal_dimensions() -> tuple[int, int]:
        """Retorna largura e altura do terminal de forma resiliente."""
        try:
            size = shutil.get_terminal_size((80, 24))
            return size.columns, size.lines
        except Exception:
            return 80, 24

    @staticmethod
    def get_hardware_serial_paths() -> list[str]:
        """Retorna lista de possíveis caminhos de dispositivos seriais adaptados ao OS."""
        paths = []
        if PlatformEnvironment.is_mobile():
            # Termux / Android USB CDC e OTG
            paths.extend([
                "/dev/ttyACM*",
                "/dev/ttyUSB*",
                "/dev/bus/usb/*/*",
                "/dev/usb/tty*"
            ])
        elif sys.platform.startswith("linux"):
            paths.extend(["/dev/ttyACM*", "/dev/ttyUSB*"])
        elif sys.platform == "darwin":
            paths.extend(["/dev/tty.usbmodem*", "/dev/tty.usbserial*"])
        elif sys.platform == "win32":
            paths.extend([f"COM{i}" for i in range(1, 32)])
        return paths

    @staticmethod
    def get_device_summary() -> Dict[str, Any]:
        cols, rows = PlatformEnvironment.get_terminal_dimensions()
        is_mob = PlatformEnvironment.is_mobile()
        return {
            "os": PlatformEnvironment.get_os_type(),
            "is_mobile": is_mob,
            "columns": cols,
            "rows": rows,
            "layout_mode": "compact-mobile" if (is_mob or cols < 60) else "full-desktop",
            "memory_constrained": is_mob,
            "max_history_turns": 4 if is_mob else 10,
            "spinner_density": "light" if is_mob else "dense"
        }

ENV_PROFILE = PlatformEnvironment.get_device_summary()
