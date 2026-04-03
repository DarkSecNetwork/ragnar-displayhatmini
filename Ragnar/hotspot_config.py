# hotspot_config.py — Fallback AP SSID/password for QR + UI (env + runtime file + defaults)
#
# ragnar_fallback_ap.sh writes /run/ragnar/hotspot-credentials.env and may export
# RAGNAR_HOTSPOT_SSID / RAGNAR_HOTSPOT_PASSWORD for the same values.
#
# Resolution order (first non-empty wins per field):
#   RAGNAR_HOTSPOT_* env → credentials file → RAGNAR_FALLBACK_AP_* env → file (fallback keys) → defaults

from __future__ import annotations

import os
from typing import Dict, Tuple

HOTSPOT_SSID_DEFAULT = "Ragnar"
HOTSPOT_PASSWORD_DEFAULT = "ragnarconnect"

_DEFAULT_CREDENTIALS_PATH = "/run/ragnar/hotspot-credentials.env"


def credentials_file_path() -> str:
    return os.environ.get("RAGNAR_HOTSPOT_ENV_FILE", _DEFAULT_CREDENTIALS_PATH).strip() or _DEFAULT_CREDENTIALS_PATH


def _parse_env_file(path: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def escape_wifi_qr_value(s: str) -> str:
    """Escape special characters in WIFI QR (WPA) payload."""
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace(":", "\\:")


def _pick(
    key_hot: str,
    key_fb: str,
    default: str,
    file_data: Dict[str, str],
) -> str:
    v = os.environ.get(key_hot, "").strip()
    if v:
        return v
    v = file_data.get(key_hot, "").strip()
    if v:
        return v
    v = os.environ.get(key_fb, "").strip()
    if v:
        return v
    v = file_data.get(key_fb, "").strip()
    if v:
        return v
    return default


def get_hotspot_credentials() -> Tuple[str, str]:
    """Current SSID and WPA password for the fallback hotspot (QR + labels)."""
    fd = _parse_env_file(credentials_file_path())
    ssid = _pick(
        "RAGNAR_HOTSPOT_SSID",
        "RAGNAR_FALLBACK_AP_SSID",
        HOTSPOT_SSID_DEFAULT,
        fd,
    )
    password = _pick(
        "RAGNAR_HOTSPOT_PASSWORD",
        "RAGNAR_FALLBACK_AP_PASSWORD",
        HOTSPOT_PASSWORD_DEFAULT,
        fd,
    )
    return ssid, password
