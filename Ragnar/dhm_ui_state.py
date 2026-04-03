# dhm_ui_state.py — Display HAT Mini state UI (RAGNAR_DHM_UI_MODE=state)
#
# UIState centralizes mode, indices, smooth scroll, WiFi scan list, and input idle time.
# Full settings uses the same build_flat_entries / apply_select as displayhatmini_menu.py.
# Config persistence uses shared_data.config + shared_data.save_config() (shared_config.json).

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

STATE_HOME = "HOME"
STATE_MENU = "MENU"
STATE_SETTINGS = "SETTINGS"
STATE_WIFI_MENU = "WIFI_MENU"
STATE_WIFI_LIST = "WIFI_LIST"
STATE_FULL_MENU = "FULL_MENU"
STATE_NETWORK_MODE = "NETWORK_MODE"
STATE_HOTSPOT = "HOTSPOT"

L_UP = "UP"
L_DOWN = "DOWN"
L_SELECT = "SELECT"
L_BACK = "BACK"

SCROLL_LERP = 0.22
LINE_HEIGHT = 16
ROOT_MENU_ROW_HEIGHT = 40  # icon row height for state UI root menu (32px icon + padding)
IDLE_DIM_SEC = 30.0
HOTSPOT_IDLE_DEFAULT_SEC = 180.0

ROOT_MENU_SPEC = [
    {"label": "Network Mode", "action": "network_mode_hub", "icon": "network"},
    {"label": "WiFi", "action": "wifi_hub", "icon": "wifi"},
    {"label": "Bluetooth", "action": "bluetooth_toggle", "icon": "bluetooth"},
    {"label": "System Info", "action": "system_info", "icon": "system"},
    {"label": "All settings", "action": "full_settings_menu", "icon": "settings"},
    {"label": "Reboot", "action": "reboot", "icon": "reboot"},
    {"label": "Shutdown", "action": "shutdown", "icon": "shutdown"},
]

WIFI_MENU_SPEC = [
    {"label": "Scan networks", "action": "wifi_scan"},
    {"label": "Connect to selected", "action": "wifi_connect"},
    {"label": "Back", "action": "wifi_back"},
]

NETWORK_MODE_SPEC = [
    {"label": "Client (WiFi)", "action": "net_client"},
    {"label": "Hotspot (Ragnar-Setup)", "action": "net_hotspot"},
    {"label": "Back", "action": "network_mode_back"},
]

_ITEM_BLUETOOTH_TOGGLE = {
    "label": "Bluetooth Scan",
    "type": "toggle",
    "key": "bluetooth_scan",
    "options": [("OFF", False), ("ON", True)],
}
_ITEM_RESTART = {"label": "Restart", "type": "action", "key": "action_restart"}
_ITEM_SHUTDOWN = {"label": "Shutdown", "type": "action", "key": "action_shutdown"}
_ITEM_HEALTH = {"label": "PiSugar & System Health", "type": "action", "key": "action_open_health_panel"}


class UIState:
    """Single object for DHM state UI (replaces scattered globals on Display)."""

    def __init__(self) -> None:
        self.state: str = STATE_HOME
        self.root_index: int = 0
        self.settings_index: int = 0
        self.scroll_offset: float = 0.0
        self.scroll_target: float = 0.0
        self.last_input_time: float = time.time()
        self.line_height: int = LINE_HEIGHT
        self.transition: float = 0.0
        self.dimmed: bool = False
        # WiFi
        self.wifi_menu_index: int = 0
        self.wifi_networks: List[str] = []
        self.wifi_list_index: int = 0
        self.wifi_scanning: bool = False
        self.wifi_status_line: str = ""
        self.wifi_scroll_offset: float = 0.0
        self.wifi_scroll_target: float = 0.0
        # Manual AP vs client (ragnar_fallback_ap.sh)
        self.network_mode_index: int = 0
        self.network_mode: str = "CLIENT"  # CLIENT | AP (best-effort)
        self.network_status_line: str = ""
        # Hotspot onboarding screen (QR + auto-return)
        self.hotspot_start_time: float = 0.0
        self.last_hotspot_activity: float = time.time()
        # XOR with 6s phase for QR vs text; A/X (L_UP/L_DOWN) flips this
        self.hotspot_view_flip: bool = False

    def touch_input(self) -> None:
        self.last_input_time = time.time()
        self.dimmed = False


def dhm_state_ui_enabled() -> bool:
    v = os.environ.get("RAGNAR_DHM_UI_MODE", "").strip().lower()
    return v in ("state", "1", "true", "yes", "on")


def map_hardware_event_to_logical(ev: str) -> Optional[str]:
    from displayhatmini_buttons import (
        EVENT_MENU_TOGGLE,
        EVENT_UP,
        EVENT_DOWN,
        EVENT_SELECT,
        EVENT_BACK,
    )

    m = {
        EVENT_MENU_TOGGLE: L_UP,
        EVENT_UP: L_DOWN,
        EVENT_DOWN: L_BACK,
        EVENT_SELECT: L_SELECT,
        EVENT_BACK: L_BACK,
    }
    return m.get(ev)


def update_dhm_scroll(ui: UIState, n_items: int, row_height: Optional[float] = None) -> None:
    """Smooth scroll toward target (pixel offset for root menu)."""
    rh = float(row_height if row_height is not None else ui.line_height)
    ui.scroll_target = float(max(0, ui.root_index) * rh)
    max_off = float(max(0, n_items - 1)) * rh
    ui.scroll_target = min(ui.scroll_target, max_off)
    ui.scroll_offset += (ui.scroll_target - ui.scroll_offset) * SCROLL_LERP
    if abs(ui.scroll_target - ui.scroll_offset) < 0.45:
        ui.scroll_offset = ui.scroll_target


def update_wifi_list_scroll(ui: UIState) -> None:
    n = max(1, len(ui.wifi_networks))
    ui.wifi_scroll_target = float(max(0, ui.wifi_list_index) * ui.line_height)
    max_off = float(max(0, n - 1)) * ui.line_height
    ui.wifi_scroll_target = min(ui.wifi_scroll_target, max_off)
    ui.wifi_scroll_offset += (ui.wifi_scroll_target - ui.wifi_scroll_offset) * SCROLL_LERP
    if abs(ui.wifi_scroll_target - ui.wifi_scroll_offset) < 0.45:
        ui.wifi_scroll_offset = ui.wifi_scroll_target


def get_dhm_live_stats() -> dict:
    """CPU / RAM / °C for HOME strip (psutil optional)."""
    out = {"cpu": 0.0, "mem": 0.0, "temp": 0.0}
    try:
        import psutil  # type: ignore

        out["cpu"] = float(psutil.cpu_percent(interval=None))
        out["mem"] = float(psutil.virtual_memory().percent)
    except Exception:
        try:
            with open("/proc/loadavg", "r", encoding="utf-8") as f:
                parts = f.read().split()
                if parts:
                    out["cpu"] = min(100.0, float(parts[0]) * 25.0)
        except Exception:
            pass
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
                mem_total = mem_avail = 0
                for ln in lines:
                    if ln.startswith("MemTotal:"):
                        mem_total = int(ln.split()[1])
                    elif ln.startswith("MemAvailable:"):
                        mem_avail = int(ln.split()[1])
                if mem_total > 0:
                    out["mem"] = round(100.0 * (1.0 - mem_avail / mem_total), 1)
        except Exception:
            pass
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r", encoding="utf-8") as f:
            out["temp"] = int(f.read().strip()) / 1000.0
    except Exception:
        out["temp"] = 0.0
    return out


def scan_wifi_networks() -> List[str]:
    try:
        out = subprocess.check_output(
            ["nmcli", "-t", "-f", "SSID", "dev", "wifi"],
            timeout=28,
            stderr=subprocess.DEVNULL,
        )
        ssids: List[str] = []
        for line in out.decode(errors="replace").splitlines():
            s = line.strip()
            if s and s not in ssids:
                ssids.append(s)
        return ssids[:48]
    except Exception as e:
        logger.warning("WiFi scan failed: %s", e)
        return []


def nmcli_wifi_connect(ssid: str, password: Optional[str] = None) -> tuple[bool, str]:
    """Connect to SSID; empty password tries open network."""
    try:
        if password:
            r = subprocess.run(
                ["nmcli", "dev", "wifi", "connect", ssid, "password", password],
                capture_output=True,
                timeout=90,
                text=True,
            )
        else:
            r = subprocess.run(
                ["nmcli", "dev", "wifi", "connect", ssid],
                capture_output=True,
                timeout=90,
                text=True,
            )
        if r.returncode == 0:
            return True, "connected"
        err = (r.stderr or r.stdout or "")[:120]
        return False, err.strip() or "failed"
    except Exception as e:
        return False, str(e)[:120]


def _persist_wifi_to_config(shared_data, ssid: str) -> None:
    try:
        cfg = getattr(shared_data, "config", None) or {}
        cfg["wifi_ssid"] = ssid
        if hasattr(shared_data, "save_config"):
            shared_data.save_config()
    except Exception as e:
        logger.debug("persist wifi ssid: %s", e)


def _fallback_ap_con_name() -> str:
    return os.environ.get("RAGNAR_FALLBACK_AP_CON_NAME", "Ragnar-Setup").strip() or "Ragnar-Setup"


def _fallback_ap_ssid() -> str:
    return os.environ.get("RAGNAR_FALLBACK_AP_SSID", "Ragnar-Setup").strip() or "Ragnar-Setup"


def _fallback_ap_password() -> str:
    return os.environ.get("RAGNAR_FALLBACK_AP_PASSWORD", "ragnar123").strip() or "ragnar123"


def get_ap_ipv4() -> str:
    iface = _primary_wlan_iface()
    try:
        out = subprocess.check_output(["ip", "-4", "-o", "addr", "show", "dev", iface], timeout=4, text=True)
        parts = out.split()
        for i, p in enumerate(parts):
            if p == "inet" and i + 1 < len(parts):
                return parts[i + 1].split("/")[0]
    except Exception:
        pass
    try:
        out = subprocess.check_output(["hostname", "-I"], timeout=3, text=True)
        return (out.split() or [""])[0].strip()
    except Exception:
        return ""


def web_ui_url(shared_data) -> str:
    ip = get_ap_ipv4()
    if not ip:
        ip = "192.168.4.1"
    try:
        port = int((getattr(shared_data, "config", {}) or {}).get("web_ui_port", 8000))
    except (TypeError, ValueError):
        port = 8000
    return f"http://{ip}:{port}"


def wifi_join_qr_string() -> str:
    """WIFI: QR for WPA2 — matches fallback AP SSID/password."""
    ssid = _fallback_ap_ssid()
    pwd = _fallback_ap_password()
    return f"WIFI:T:WPA;S:{ssid};P:{pwd};;"


def get_connected_wifi_clients() -> int:
    """Count STAs associated to our AP (hostapd/NM hotspot on wlan)."""
    iface = _primary_wlan_iface()
    try:
        out = subprocess.check_output(["iw", "dev", iface, "station", "dump"], timeout=5, text=True)
        return out.count("Station")
    except Exception:
        return 0


def hotspot_idle_sec() -> float:
    try:
        return float(os.environ.get("RAGNAR_DHM_HOTSPOT_IDLE_SEC", "").strip() or HOTSPOT_IDLE_DEFAULT_SEC)
    except ValueError:
        return HOTSPOT_IDLE_DEFAULT_SEC


def _hotspot_retry_wifi(display) -> None:
    """While AP is up: rescan / hint reconnect (does not tear down AP)."""
    ui: UIState = display.dhm_ui
    sd = display.shared_data

    def _go() -> None:
        logger.info("[NET] Hotspot: user requested WiFi retry (rescan)")
        ui.network_status_line = "Rescanning…"
        try:
            subprocess.run(["nmcli", "radio", "wifi", "on"], timeout=12, capture_output=True, text=True)
            subprocess.run(["nmcli", "device", "wifi", "rescan"], timeout=35, capture_output=True, text=True)
        except Exception as e:
            logger.debug("hotspot_retry_wifi: %s", e)
        ssid = (getattr(sd, "config", {}) or {}).get("wifi_ssid", "") or ""
        ssid = str(ssid).strip()
        if ssid:
            try:
                subprocess.run(
                    ["nmcli", "connection", "up", ssid],
                    timeout=90,
                    capture_output=True,
                    text=True,
                )
            except Exception as e:
                logger.debug("nmcli connection up: %s", e)
        ui.network_status_line = "Retry done (phone: reconnect WiFi)"
        ui.last_hotspot_activity = time.time()

    threading.Thread(target=_go, daemon=True).start()


def _hotspot_exit_to_client(display) -> None:
    """Stop fallback AP and return UI to HOME (threaded)."""
    ui: UIState = display.dhm_ui
    sd = display.shared_data

    def _go() -> None:
        logger.info("[NET] Exiting hotspot → WiFi client")
        _run_fallback_ap_subprocess("stop")
        _reconnect_wifi_client(sd)
        refresh_network_mode(ui)
        ui.state = STATE_HOME
        display.menu_visible = False
        ui.network_status_line = ""

    threading.Thread(target=_go, daemon=True).start()


def sync_hotspot_screen(display) -> None:
    """When NM hotspot is up, show STATE_HOTSPOT (unless user is deep in full menu / WiFi list)."""
    ui: UIState = display.dhm_ui
    if not ui:
        return
    if getattr(display.shared_data, "health_panel_open", False):
        return
    if not nm_fallback_ap_active():
        if ui.state == STATE_HOTSPOT:
            ui.state = STATE_HOME
            display.menu_visible = False
        return
    if ui.state in (STATE_FULL_MENU, STATE_WIFI_LIST):
        return
    if ui.state != STATE_HOTSPOT:
        ui.state = STATE_HOTSPOT
        display.menu_visible = True
        t = time.time()
        ui.hotspot_start_time = t
        ui.last_hotspot_activity = t
        ui.hotspot_view_flip = False


def hotspot_screen_payload(shared_data) -> dict:
    """Strings + client count for the HOTSPOT UI."""
    return {
        "ssid": _fallback_ap_ssid(),
        "password": _fallback_ap_password(),
        "url": web_ui_url(shared_data),
        "wifi_qr": wifi_join_qr_string(),
        "clients": get_connected_wifi_clients(),
        "status": format_ap_status_line(),
    }


def hotspot_active_use() -> bool:
    """True while at least one STA is associated to the AP (best signal of “in use”)."""
    return get_connected_wifi_clients() > 0


def check_hotspot_idle_timeout(display) -> None:
    """No clients for HOTSPOT_IDLE_SEC → stop AP and reconnect WiFi."""
    ui: UIState = display.dhm_ui
    if not ui or ui.state != STATE_HOTSPOT:
        return
    if not nm_fallback_ap_active():
        return
    if hotspot_active_use():
        ui.last_hotspot_activity = time.time()
        return
    if time.time() - ui.last_hotspot_activity < hotspot_idle_sec():
        return
    logger.info("[NET] Hotspot inactivity timeout → WiFi client")
    _hotspot_exit_to_client(display)


def resolve_fallback_ap_script() -> Optional[str]:
    envp = os.environ.get("RAGNAR_FALLBACK_AP_SCRIPT", "").strip()
    if envp and os.path.isfile(envp):
        return envp
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        "/home/ragnar/Ragnar/scripts/ragnar_fallback_ap.sh",
        os.path.join(here, "scripts", "ragnar_fallback_ap.sh"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def nm_fallback_ap_active() -> bool:
    con = _fallback_ap_con_name()
    try:
        out = subprocess.check_output(
            ["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"],
            timeout=8,
            text=True,
        )
        for line in out.splitlines():
            if line.strip() == con:
                return True
    except Exception as e:
        logger.debug("nm_fallback_ap_active: %s", e)
    return False


def _primary_wlan_iface() -> str:
    try:
        out = subprocess.check_output(["iw", "dev"], timeout=4, text=True)
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "Interface":
                return parts[1]
    except Exception:
        pass
    return "wlan0"


def format_ap_status_line() -> str:
    """Short status: SSID + IPv4 on wlan when AP is up."""
    ssid = _fallback_ap_ssid()
    iface = _primary_wlan_iface()
    ip = ""
    try:
        out = subprocess.check_output(["ip", "-4", "-o", "addr", "show", "dev", iface], timeout=4, text=True)
        parts = out.split()
        for i, p in enumerate(parts):
            if p == "inet" and i + 1 < len(parts):
                ip = parts[i + 1].split("/")[0]
                break
    except Exception:
        pass
    if not ip:
        try:
            out = subprocess.check_output(["hostname", "-I"], timeout=3, text=True)
            ip = (out.split() or [""])[0].strip()
        except Exception:
            ip = ""
    return f"AP {ssid}  {ip}"[:48]


def refresh_network_mode(ui: UIState) -> None:
    ui.network_mode = "AP" if nm_fallback_ap_active() else "CLIENT"


def _reconnect_wifi_client(shared_data) -> None:
    """After AP stop: turn WiFi on, rescan, try bringing up saved profile."""
    try:
        subprocess.run(["nmcli", "radio", "wifi", "on"], timeout=15, capture_output=True, text=True)
        subprocess.run(["nmcli", "device", "wifi", "rescan"], timeout=30, capture_output=True, text=True)
    except Exception as e:
        logger.debug("reconnect_wifi_client rescan: %s", e)
    cfg = getattr(shared_data, "config", {}) or {}
    ssid = (cfg.get("wifi_ssid") or "").strip()
    if not ssid:
        return
    try:
        subprocess.run(
            ["nmcli", "connection", "up", ssid],
            timeout=90,
            capture_output=True,
            text=True,
        )
    except Exception as e:
        logger.debug("nmcli connection up %s: %s", ssid, e)


def _run_fallback_ap_subprocess(cmd: str) -> tuple[int, str]:
    script = resolve_fallback_ap_script()
    if not script:
        return 127, "ragnar_fallback_ap.sh not found"
    try:
        r = subprocess.run(
            ["/usr/bin/sudo", script, cmd],
            capture_output=True,
            timeout=120,
            text=True,
        )
        tail = ((r.stderr or "") + (r.stdout or ""))[-200:]
        return r.returncode, tail.strip()
    except Exception as e:
        return 1, str(e)[:200]


def _network_mode_dispatch(display, action: str, apply_select_fn: Callable) -> None:
    ui: UIState = display.dhm_ui
    sd = display.shared_data

    if action == "network_mode_back":
        ui.state = STATE_MENU
        ui.network_status_line = ""
        return

    if action == "net_hotspot":

        def _go() -> None:
            ui.network_status_line = "Starting AP…"
            logger.info("[NET] Manual switch to hotspot (fallback AP)")
            code, msg = _run_fallback_ap_subprocess("start")
            refresh_network_mode(ui)
            if code == 0 and nm_fallback_ap_active():
                ui.network_status_line = format_ap_status_line()
                ui.state = STATE_HOTSPOT
                display.menu_visible = True
                t = time.time()
                ui.hotspot_start_time = t
                ui.last_hotspot_activity = t
                ui.hotspot_view_flip = False
            else:
                ui.network_status_line = (msg or "AP failed")[:48]

        threading.Thread(target=_go, daemon=True).start()
        return

    if action == "net_client":

        def _go() -> None:
            ui.network_status_line = "Stopping AP…"
            logger.info("[NET] Manual switch to WiFi client")
            code, msg = _run_fallback_ap_subprocess("stop")
            _reconnect_wifi_client(sd)
            refresh_network_mode(ui)
            ui.network_status_line = "WiFi client" if ui.network_mode == "CLIENT" else (msg or "check nmcli")[:48]

        threading.Thread(target=_go, daemon=True).start()
        return


def _dispatch_root_action(display, action: str, apply_select_fn: Callable) -> None:
    sd = display.shared_data
    ui: UIState = display.dhm_ui
    if action == "network_mode_hub":
        refresh_network_mode(ui)
        ui.state = STATE_NETWORK_MODE
        ui.network_mode_index = 0
        ui.network_status_line = format_ap_status_line() if ui.network_mode == "AP" else "Mode: WiFi client"
        return
    if action == "wifi_hub":
        ui.state = STATE_WIFI_MENU
        ui.wifi_menu_index = 0
        ui.wifi_status_line = ""
        return
    if action == "bluetooth_toggle":
        apply_select_fn(sd, _ITEM_BLUETOOTH_TOGGLE)
        return
    if action == "system_info":
        display.menu_visible = False
        ui.state = STATE_HOME
        apply_select_fn(sd, _ITEM_HEALTH)
        return
    if action == "full_settings_menu":
        ui.state = STATE_FULL_MENU
        display.menu_cursor = 0
        display.menu_scroll = 0
        return
    if action == "reboot":
        apply_select_fn(sd, _ITEM_RESTART)
        return
    if action == "shutdown":
        apply_select_fn(sd, _ITEM_SHUTDOWN)
        return
    logger.debug("dhm_ui_state: unknown root action %s", action)


def _wifi_dispatch(display, action: str, apply_select_fn: Callable) -> None:
    ui: UIState = display.dhm_ui
    sd = display.shared_data

    if action == "wifi_back":
        ui.state = STATE_MENU
        ui.wifi_networks = []
        ui.wifi_list_index = 0
        ui.wifi_status_line = ""
        return

    if action == "wifi_scan":

        def _run() -> None:
            ui.wifi_scanning = True
            ui.wifi_status_line = "Scanning…"
            try:
                nets = scan_wifi_networks()
                ui.wifi_networks = nets
                ui.wifi_list_index = 0
                ui.wifi_status_line = f"{len(nets)} networks" if nets else "No networks"
                ui.state = STATE_WIFI_LIST
            finally:
                ui.wifi_scanning = False

        threading.Thread(target=_run, daemon=True).start()
        return

    if action == "wifi_connect":
        if not ui.wifi_networks:
            ui.wifi_status_line = "Scan first"
            return
        ssid = ui.wifi_networks[max(0, min(ui.wifi_list_index, len(ui.wifi_networks) - 1))]
        pwd = None
        try:
            cfg = getattr(sd, "config", {}) or {}
            if cfg.get("wifi_ssid") == ssid and cfg.get("wifi_password"):
                pwd = cfg.get("wifi_password")
        except Exception:
            pass

        def _run() -> None:
            ui.wifi_status_line = "Connecting…"
            ok, msg = nmcli_wifi_connect(ssid, pwd)
            ui.wifi_status_line = ("OK " + ssid) if ok else msg[:48]
            if ok:
                _persist_wifi_to_config(sd, ssid)

        threading.Thread(target=_run, daemon=True).start()
        return


_menu_bfe = None
_menu_gsc = None
_menu_cti = None
_menu_import_failed = False


def _ensure_menu_imports() -> None:
    global _menu_bfe, _menu_gsc, _menu_cti, _menu_import_failed
    if _menu_bfe is not None or _menu_import_failed:
        return
    try:
        from displayhatmini_menu import (
            build_flat_entries as bfe,
            get_selectable_count as gsc,
            cursor_to_line_index as cti,
        )

        _menu_bfe, _menu_gsc, _menu_cti = bfe, gsc, cti
    except ImportError:
        _menu_import_failed = True
        _menu_bfe = _menu_gsc = _menu_cti = None


def handle_dhm_state_event(display, logical: str, apply_select_fn: Callable) -> None:
    _ensure_menu_imports()
    ui: UIState = display.dhm_ui
    ui.touch_input()

    state = ui.state

    if state == STATE_HOTSPOT:
        if logical == L_SELECT:
            _hotspot_exit_to_client(display)
        elif logical == L_BACK:
            _hotspot_retry_wifi(display)
        elif logical in (L_UP, L_DOWN):
            ui.hotspot_view_flip = not ui.hotspot_view_flip
        ui.last_hotspot_activity = time.time()
        return

    n_root = len(ROOT_MENU_SPEC)

    if state == STATE_HOME:
        if logical == L_SELECT:
            display.menu_visible = True
            ui.state = STATE_MENU
            ui.root_index = 0
            ui.scroll_offset = 0.0
            ui.scroll_target = 0.0
        return

    if state == STATE_MENU:
        if logical == L_UP:
            ui.root_index = (ui.root_index - 1) % n_root
        elif logical == L_DOWN:
            ui.root_index = (ui.root_index + 1) % n_root
        elif logical == L_BACK:
            display.menu_visible = False
            ui.state = STATE_HOME
        elif logical == L_SELECT:
            idx = max(0, min(ui.root_index, n_root - 1))
            _dispatch_root_action(display, ROOT_MENU_SPEC[idx]["action"], apply_select_fn)
        return

    if state == STATE_NETWORK_MODE:
        nw = len(NETWORK_MODE_SPEC)
        if logical == L_UP:
            ui.network_mode_index = (ui.network_mode_index - 1) % nw
        elif logical == L_DOWN:
            ui.network_mode_index = (ui.network_mode_index + 1) % nw
        elif logical == L_BACK:
            ui.state = STATE_MENU
            ui.network_status_line = ""
        elif logical == L_SELECT:
            act = NETWORK_MODE_SPEC[max(0, min(ui.network_mode_index, nw - 1))]["action"]
            _network_mode_dispatch(display, act, apply_select_fn)
        return

    if state == STATE_WIFI_MENU:
        nw = len(WIFI_MENU_SPEC)
        if logical == L_UP:
            ui.wifi_menu_index = (ui.wifi_menu_index - 1) % nw
        elif logical == L_DOWN:
            ui.wifi_menu_index = (ui.wifi_menu_index + 1) % nw
        elif logical == L_BACK:
            ui.state = STATE_MENU
            ui.wifi_networks = []
        elif logical == L_SELECT:
            act = WIFI_MENU_SPEC[max(0, min(ui.wifi_menu_index, nw - 1))]["action"]
            _wifi_dispatch(display, act, apply_select_fn)
        return

    if state == STATE_WIFI_LIST:
        nn = len(ui.wifi_networks)
        if nn == 0:
            if logical == L_BACK:
                ui.state = STATE_WIFI_MENU
            return
        if logical == L_UP:
            ui.wifi_list_index = max(0, ui.wifi_list_index - 1)
        elif logical == L_DOWN:
            ui.wifi_list_index = min(nn - 1, ui.wifi_list_index + 1)
        elif logical == L_BACK:
            ui.state = STATE_WIFI_MENU
        elif logical == L_SELECT:
            ssid = ui.wifi_networks[ui.wifi_list_index]

            def _run() -> None:
                ui.wifi_status_line = "Connecting…"
                pwd = None
                try:
                    cfg = getattr(display.shared_data, "config", {}) or {}
                    if cfg.get("wifi_ssid") == ssid and cfg.get("wifi_password"):
                        pwd = cfg.get("wifi_password")
                except Exception:
                    pass
                ok, msg = nmcli_wifi_connect(ssid, pwd)
                ui.wifi_status_line = ("OK " + ssid) if ok else msg[:48]
                if ok:
                    _persist_wifi_to_config(display.shared_data, ssid)

            threading.Thread(target=_run, daemon=True).start()
        return

    if state == STATE_SETTINGS:
        if logical == L_BACK:
            ui.state = STATE_MENU
        return

    if state == STATE_FULL_MENU:
        if _menu_bfe is None or _menu_gsc is None or _menu_cti is None:
            ui.state = STATE_MENU
            return
        entries = _menu_bfe(display.shared_data)
        sel = _menu_gsc(entries)
        if logical == L_BACK:
            ui.state = STATE_MENU
            return
        if logical == L_UP and sel:
            display.menu_cursor = max(0, display.menu_cursor - 1)
        elif logical == L_DOWN and sel:
            display.menu_cursor = min(sel - 1, display.menu_cursor + 1)
        elif logical == L_SELECT:
            line_idx = _menu_cti(entries, display.menu_cursor)
            if line_idx < len(entries):
                _, _, item = entries[line_idx]
                if item:
                    apply_select_fn(display.shared_data, item)
        return
