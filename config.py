"""
Vincent Hardware Registry — conhecimento exato de cada placa.
Fonte da verdade sobre hardware, firmware, bugs conhecidos e capacidades.
"""

# ─── Perfis de hardware ───────────────────────────────────────────────────────

DEVICES = {
    "TEMBED": {
        "label":    "T-Embed CC1101",
        "mac":      "30:ed:a0:34:54:a8",
        "chip":     "ESP32-S3",
        "flash_mb": 16,
        "psram_mb": 8,
        "port_hint": "ACM",          # USB-CDC nativo → /dev/ttyACMx
        "display":  "ST7789 170×320",
        "hardware": [
            "cc1101",                # Sub-GHz RF (433/868/915 MHz)
            "ir_tx", "ir_rx",        # Infravermelho
            "wifi",
            "ble",
            "encoder",               # Rotary encoder / D-pad
            "pmu",                   # I2C 0x55, 0x6B
        ],
        "firmware_current": "bruce-vdev",
        "firmware_recommended": "vincent-os-0.3.2",
        "protocol": "bruce-shell",   # protocolo ativo no momento
    },

    "ESP32DIV": {
        "label":    "ESP32-S3 DIV Kilaz Edition v2",
        "mac":      "3c:dc:75:54:fc:70",
        "chip":     "ESP32-S3",
        "flash_mb": 16,
        "psram_mb": 0,               # SEM PSRAM
        "port_hint": "USB",          # CP2102 → /dev/ttyUSBx  (vira ACM após flash USB-CDC)
        "display":  "ILI9341 240×320 + XPT2046 touch",
        "hardware": [
            "nrf24_x3",              # 3× NRF24L01 2.4 GHz
            "cc1101",                # Sub-GHz RF
            "ir_tx", "ir_rx",
            "wifi",
            "ble",
            "sd_card",
            "touch_xpt2046",
            "pcf8574_buttons",       # I/O expander I2C (0x20 v2.0 / 0x27 v2.1)
            "battery_ip5306",        # Charger IC
        ],
        "firmware_current": "cifertech-1.5.3",
        "firmware_recommended": "bruce-generic-usbcdc",
        "protocol": None,            # sem protocolo serial (firmware atual)
    },
}

# ─── Perfis de firmware ───────────────────────────────────────────────────────

FIRMWARE = {
    "bruce-vdev": {
        "protocol":   "bruce-shell",
        "prompt":     ["COMMAND:", "#"],
        "encoding":   "utf-8",
        "baud":       115200,

        # Comandos seguros (testados, não travam)
        "safe": [
            "settings", "ls", "wifi on", "wifi off",
            "wifi add {ssid} {pass}", "sniffer", "listen",
            "webui", "ir rx {secs}", "ir tx {proto} {addr} {val}",
            "led r {v}", "led g {v}", "led b {v}",
            "storage list {path}", "storage read {path}",
            "power reboot",
        ],
        # Comandos que causam crash ou bloqueiam — NUNCA enviar
        "blocked": {
            "arp":       "CRASH FreeRTOS assert (xTaskPriorityDisinherit)",
            "diag all":  "comando inexistente nesta versão",
            "subghz rx": "bloqueia indefinido sem frequência explícita válida",
        },
    },

    "vincent-os-0.3.2": {
        "protocol":  "vincent-json",
        "prompt":    [],             # responde a qualquer momento via serial
        "encoding":  "utf-8",
        "baud":      115200,
        "safe": [
            "/status", "/json", "/wifi", "/ble",
            "/i2c", "/cc1101", "/files", "/menu", "/help",
            '{"cmd":"status"}', '{"cmd":"screen","screen":"wifi"}',
        ],
        "blocked": {},
    },

    "cifertech-1.5.3": {
        "protocol":  None,           # firmware sem interface serial de comandos
        "prompt":    [],
        "encoding":  "utf-8",
        "baud":      115200,
        "safe":      [],
        "blocked":   {"*": "firmware original — sem CLI serial"},
    },

    "bruce-generic-usbcdc": {
        "protocol":  "bruce-shell",
        "prompt":    ["COMMAND:", "#"],
        "encoding":  "utf-8",
        "baud":      115200,
        "safe": [
            "settings", "ls", "wifi on", "wifi off",
            "wifi add {ssid} {pass}", "sniffer", "listen",
            "webui", "ir rx {secs}", "ir tx {proto} {addr} {val}",
            "led r {v}", "led g {v}", "led b {v}",
            "dual status", "dual marauder", "dual bruce",
            "power reboot",
        ],
        "blocked": {
            "arp": "CRASH FreeRTOS assert (mesma base do bruce-vdev)",
        },
    },
}

# ─── Binários de flash disponíveis ───────────────────────────────────────────

import os
_BASE = os.path.expanduser(
    "~/Downloads/PROJETO MERCADO LIVRE/admin/hardware-lab"
)

FLASH_IMAGES = {
    "TEMBED": {
        "dual-bruce-marauder": {
            "path": f"{_BASE}/build_artifacts/"
                    "vincent_dual_bruce_marauder_tembed_autoback_20260511_185157/"
                    "VincentDual-Bruce-Marauder-TEmbedCC1101-AutoBack.bin",
            "sha256": "9405e7e87d4ac05758dac928706ec202f6ada3913afb1d82645a1bf883f3cdb4",
            "chip":   "esp32s3",
            "offset": "0x0",
            "size_mb": 5.9,
            "boot_method": "manual",  # precisa BOOT+RESET físico (USB-CDC não tem auto-reset)
            "slots": {"ota_0": "bruce-cc1101", "ota_1": "marauder-autoback"},
        },
        "vincent-os-0.3.2": {
            "path": f"{_BASE}/esp32s3_firmware_lab/build_artifacts/"
                    "vincent_embed_os_0.3.2_hotfix/firmware.bin",
            "bootloader": f"{_BASE}/esp32s3_firmware_lab/build_artifacts/"
                          "vincent_embed_os_0.3.2_hotfix/bootloader.bin",
            "partitions": f"{_BASE}/esp32s3_firmware_lab/build_artifacts/"
                          "vincent_embed_os_0.3.2_hotfix/partitions.bin",
            "chip":   "esp32s3",
            "boot_method": "manual",
            "slots": {"ota_0": "vincent-os-0.3.2"},
        },
    },
    "ESP32DIV": {
        "dual-bruce-marauder-usbcdc": {
            "path": f"{_BASE}/build_artifacts/"
                    "vincent_dual_bruce_marauder_esp32s3div_usbcdc_20260511_164304/"
                    "VincentDual-BruceGeneric-Marauder-ESP32S3DIV-USBCDC.bin",
            "sha256": "45d29e4a60a8f89cbedcc5eb24601a87c250eb664b0198b62547e47bb4a2c954",
            "chip":   "esp32s3",
            "offset": "0x0",
            "size_mb": 5.9,
            "boot_method": "auto",   # CP2102 suporta DTR/RTS auto-reset
            "slots": {"ota_0": "bruce-generic-usbcdc", "ota_1": "marauder-headless"},
            "note": "Após flash: aparece como /dev/ttyACM* (USB-CDC nativa)",
        },
        "restore-original": {
            "path": f"{_BASE}/esp32s3_new_equipment_3CDC7554FC70/full_flash_20260511_1452.bin",
            "chip":   "esp32s3",
            "offset": "0x0",
            "size_mb": 16,
            "boot_method": "auto",
            "slots": {"full": "cifertech-1.5.3"},
        },
    },
}

# ─── Capacidades por hardware ─────────────────────────────────────────────────

CAPABILITIES = {
    "cc1101":          "RF Sub-GHz 315/433/868/915 MHz (RX/TX)",
    "nrf24_x3":        "RF 2.4 GHz com 3 módulos NRF24L01 (diversidade/paralelismo)",
    "ir_tx":           "Transmissão IR (controles remotos próprios)",
    "ir_rx":           "Recepção IR (captura de códigos)",
    "wifi":            "WiFi 802.11 b/g/n STA+AP",
    "ble":             "Bluetooth Low Energy scan/advertise",
    "encoder":         "Rotary encoder — navegação de menu",
    "sd_card":         "Armazenamento SD FAT32 (capturas, logs, assets)",
    "touch_xpt2046":   "Touch resistivo 240×320",
    "pcf8574_buttons": "8 botões físicos via I2C I/O expander",
    "battery_ip5306":  "Bateria com charging e proteção integrada",
    "pmu":             "Power management unit (I2C)",
    "display":         "Display TFT com UI própria",
}
