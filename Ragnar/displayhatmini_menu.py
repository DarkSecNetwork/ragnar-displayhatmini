# displayhatmini_menu.py - Settings menu structure and logic for Display HAT Mini
# Used when A opens menu; X/Y navigate, B select, long/double B back.

import glob
import os
import subprocess
import threading
import logging

logger = logging.getLogger(__name__)

# Menu: list of (section_title, [items]). Item: {"label": str, "type": "header"|"toggle"|"text"|"readonly"|"action", "key": str, "options": [(label, value)] or None}
MENU_STRUCTURE = [
    ("--- NETWORK ---", [
        {"label": "WiFi SSID", "type": "readonly", "key": "wifi_ssid"},
        {"label": "WiFi Password", "type": "text", "key": "wifi_password"},
        {"label": "Auto Reconnect", "type": "toggle", "key": "wifi_auto_reconnect", "options": [("ON", True), ("OFF", False)]},
        {"label": "Preferred Interface", "type": "readonly", "key": "preferred_interface"},
        {"label": "Ethernet DHCP", "type": "toggle", "key": "ethernet_dhcp", "options": [("ON", True), ("OFF", False)]},
        {"label": "Static IP", "type": "readonly", "key": "static_ip"},
        {"label": "Bluetooth Scan", "type": "toggle", "key": "bluetooth_scan", "options": [("OFF", False), ("ON", True)]},
    ]),
    ("--- WIFI ATTACK ---", [
        {"label": "Monitor Mode", "type": "toggle", "key": "monitor_mode", "options": [("OFF", False), ("ON", True)]},
        {"label": "Interface", "type": "readonly", "key": "wlan_interface"},
        {"label": "Handshake Save Path", "type": "readonly", "key": "handshake_path"},
        {"label": "Deauth Power", "type": "readonly", "key": "deauth_power"},
        {"label": "Channel Hop", "type": "toggle", "key": "channel_hop", "options": [("ON", True), ("OFF", False)]},
        {"label": "Auto Capture", "type": "toggle", "key": "auto_capture", "options": [("ON", True), ("OFF", False)]},
    ]),
    ("--- AI ---", [
        {"label": "AI Enabled", "type": "toggle", "key": "ai_enabled", "options": [("ON", True), ("OFF", False)]},
        {"label": "Provider", "type": "readonly", "key": "ai_provider"},
        {"label": "API Key", "type": "text", "key": "openai_api_key"},
        {"label": "Model", "type": "readonly", "key": "ai_model"},
        {"label": "Response Speed", "type": "readonly", "key": "ai_speed"},
        {"label": "Memory Enabled", "type": "toggle", "key": "ai_memory", "options": [("ON", True), ("OFF", False)]},
        {"label": "Offline Mode", "type": "toggle", "key": "ai_offline", "options": [("OFF", False), ("ON", True)]},
    ]),
    ("--- DISPLAY ---", [
        {"label": "Brightness", "type": "readonly", "key": "brightness"},
        {"label": "Rotation", "type": "readonly", "key": "rotation"},
        {"label": "Sleep Timeout", "type": "readonly", "key": "sleep_timeout"},
        {"label": "FPS / Refresh Rate", "type": "readonly", "key": "fps"},
        {"label": "Invert Colors", "type": "toggle", "key": "invert_colors", "options": [("OFF", False), ("ON", True)]},
        {"label": "Sleep Timer", "type": "toggle", "key": "sleep_timer", "options": [("ON", True), ("OFF", False)]},
        {"label": "Wake Up Button", "type": "readonly", "key": "wake_button"},
    ]),
    ("--- SOUND ---", [
        {"label": "Volume", "type": "readonly", "key": "volume"},
        {"label": "Button Beep", "type": "toggle", "key": "button_beep", "options": [("ON", True), ("OFF", False)]},
        {"label": "Voice Output", "type": "toggle", "key": "voice_output", "options": [("OFF", False), ("ON", True)]},
    ]),
    ("--- SYSTEM ---", [
        {"label": "Device Name", "type": "readonly", "key": "device_name"},
        {"label": "IP Address", "type": "readonly", "key": "ip_address"},
        {"label": "CPU Usage", "type": "readonly", "key": "cpu_usage"},
        {"label": "Temperature", "type": "readonly", "key": "temperature"},
        {"label": "Auto Start Services", "type": "toggle", "key": "auto_start_services", "options": [("ON", True), ("OFF", False)]},
        {"label": "Startup Mode", "type": "readonly", "key": "startup_mode"},
    ]),
    ("--- STORAGE ---", [
        {"label": "Used Space", "type": "readonly", "key": "used_space"},
        {"label": "Handshake Files", "type": "readonly", "key": "handshake_count"},
        {"label": "Logs Size", "type": "readonly", "key": "logs_size"},
        {"label": "Auto Delete Old Files", "type": "toggle", "key": "auto_delete_old", "options": [("ON", True), ("OFF", False)]},
    ]),
    ("--- SECURITY ---", [
        {"label": "Device Lock", "type": "toggle", "key": "device_lock", "options": [("OFF", False), ("ON", True)]},
        {"label": "PIN Code", "type": "text", "key": "pin_code"},
        {"label": "Auto Lock", "type": "readonly", "key": "auto_lock"},
        {"label": "SSH Enabled", "type": "toggle", "key": "ssh_enabled", "options": [("ON", True), ("OFF", False)]},
        {"label": "Change SSH Port", "type": "action", "key": "action_ssh_port"},
    ]),
    ("--- REMOTE ACCESS ---", [
        {"label": "SSH Host", "type": "readonly", "key": "ssh_host"},
        {"label": "SSH Port", "type": "readonly", "key": "ssh_port"},
        {"label": "Web UI", "type": "toggle", "key": "web_ui", "options": [("ON", True), ("OFF", False)]},
        {"label": "Web UI Port", "type": "readonly", "key": "web_ui_port"},
        {"label": "Allow Remote Commands", "type": "toggle", "key": "remote_commands", "options": [("OFF", False), ("ON", True)]},
    ]),
    ("--- LOGGING ---", [
        {"label": "Debug Mode", "type": "toggle", "key": "debug_mode", "options": [("OFF", False), ("ON", True)]},
        {"label": "Save Logs", "type": "toggle", "key": "save_logs", "options": [("ON", True), ("OFF", False)]},
        {"label": "View Logs", "type": "action", "key": "action_view_logs"},
        {"label": "Clear Logs", "type": "action", "key": "action_clear_logs"},
    ]),
    ("--- UPDATES ---", [
        {"label": "Check Updates", "type": "action", "key": "action_check_updates"},
        {"label": "Auto Update", "type": "toggle", "key": "auto_update", "options": [("OFF", False), ("ON", True)]},
        {"label": "Update Channel", "type": "readonly", "key": "update_channel"},
    ]),
    ("--- DEVELOPER ---", [
        {"label": "GPIO Test", "type": "action", "key": "action_gpio_test"},
        {"label": "Button Mapping", "type": "action", "key": "action_button_mapping"},
        {"label": "Simulate Input", "type": "action", "key": "action_simulate_input"},
        {"label": "Reset Config", "type": "action", "key": "action_reset_config"},
        {"label": "Factory Reset", "type": "action", "key": "action_factory_reset"},
    ]),
    ("--- POWER ---", [
        {"label": "Restart", "type": "action", "key": "action_restart"},
        {"label": "Shutdown", "type": "action", "key": "action_shutdown"},
        {"label": "Safe Mode Boot", "type": "action", "key": "action_safe_mode"},
    ]),
]


def _get_value_from_system(shared_data, key):
    """Resolve readonly/display values from config or system."""
    cfg = getattr(shared_data, "config", {}) or {}
    if key == "wifi_ssid":
        return getattr(shared_data, "active_network_ssid", None) or cfg.get("wifi_ssid", "-") or "-"
    if key == "preferred_interface":
        return cfg.get("preferred_interface", "wlan0")
    if key == "static_ip":
        return cfg.get("static_ip", "-") or "-"
    if key == "wlan_interface":
        return cfg.get("wlan_interface", "wlan0")
    if key == "handshake_path":
        return getattr(shared_data, "datadir", "") + "/handshakes" if getattr(shared_data, "datadir", None) else "-"
    if key == "deauth_power":
        return cfg.get("deauth_power", "MED")
    if key == "ai_provider":
        return cfg.get("ai_provider", "OpenAI")
    if key == "openai_api_key":
        v = cfg.get("openai_api_key", "") or ""
        return "***" if len(v) > 4 else "-"
    if key == "wifi_password":
        v = cfg.get("wifi_password", "") or ""
        return "********" if v else "-"
    if key == "pin_code":
        v = cfg.get("pin_code", "") or ""
        return "****" if v else "-"
    if key == "ai_model":
        return cfg.get("openai_model", "gpt-4o-mini")
    if key == "ai_speed":
        return cfg.get("ai_speed", "FAST")
    if key == "brightness":
        return str(cfg.get("brightness", 80)) + "%"
    if key == "rotation":
        return str(cfg.get("rotation", 180)) + "°"
    if key == "sleep_timeout":
        return str(cfg.get("sleep_timeout", 60)) + "s"
    if key == "volume":
        return str(cfg.get("volume", 40)) + "%"
    if key == "device_name":
        try:
            return open("/etc/hostname").read().strip() or "RAGNAR"
        except Exception:
            return "RAGNAR"
    if key == "ip_address":
        try:
            out = subprocess.check_output(["hostname", "-I"], timeout=2, text=True)
            return (out.split()[0] or "-").strip()
        except Exception:
            return "-"
    if key == "cpu_usage":
        try:
            out = subprocess.check_output(["top", "-bn1"], timeout=2, text=True)
            for line in out.splitlines():
                if "Cpu(s)" in line or "cpu " in line.lower():
                    return line.split()[1][:6] + "%" if line.split() else "-"
        except Exception:
            pass
        return "-"
    if key == "temperature":
        try:
            t = open("/sys/class/thermal/thermal_zone0/temp").read().strip()
            return str(int(t) // 1000) + "°C"
        except Exception:
            return "-"
    if key == "used_space":
        try:
            out = subprocess.check_output(["df", "-h", "/"], timeout=2, text=True)
            parts = out.splitlines()[-1].split()
            return parts[4] + " used" if len(parts) >= 5 else "-"
        except Exception:
            return "-"
    if key == "logs_size":
        logdir = getattr(shared_data, "logsdir", "") or "/home/ragnar/Ragnar/data/logs"
        try:
            out = subprocess.check_output(["du", "-sh", logdir], timeout=2, text=True)
            return out.split()[0]
        except Exception:
            return "-"
    if key == "ssh_host":
        return _get_value_from_system(shared_data, "ip_address")
    if key == "ssh_port":
        return str(cfg.get("ssh_port", 22))
    if key == "web_ui_port":
        return str(cfg.get("web_ui_port", 8000))
    if key == "update_channel":
        return cfg.get("update_channel", "Stable")
    if key == "invert_colors":
        return "ON" if cfg.get("screen_reversed", False) else "OFF"
    if key == "wake_button":
        return cfg.get("wake_button", "B")
    if key == "startup_mode":
        return cfg.get("startup_mode", "Dashboard")
    if key == "auto_lock":
        return str(cfg.get("auto_lock", 2)) + " min"
    if key == "fps":
        return str(cfg.get("fps", 1)) + " FPS"
    if key == "handshake_count":
        datadir = getattr(shared_data, "datadir", None) or "/home/ragnar/Ragnar/data"
        hs = os.path.join(datadir, "handshakes")
        try:
            n = len(glob.glob(os.path.join(hs, "*.cap")) + glob.glob(os.path.join(hs, "*.pcap")))
            return str(n)
        except Exception:
            return "-"
    try:
        return cfg.get(key, "-")
    except Exception:
        return "-"


def get_menu_line_count():
    n = 0
    for _, items in MENU_STRUCTURE:
        n += 1 + len(items)
    return n


def get_line_at(index):
    """Return (display_text, is_section_header, item_dict or None) for flat index."""
    i = 0
    for section, items in MENU_STRUCTURE:
        if i == index:
            return section, True, None
        i += 1
        for it in items:
            if i == index:
                val = ""
                if it["type"] == "toggle" and it.get("options"):
                    # Will be filled by caller with shared_data
                    val = ""
                elif it["type"] in ("readonly", "toggle", "text"):
                    val = ""
                return it["label"], False, it
            i += 1
    return "", False, None


def get_value_for_item(shared_data, item):
    if not item:
        return ""
    key = item.get("key")
    if item["type"] == "toggle" and item.get("options"):
        cfg = getattr(shared_data, "config", {}) or {}
        config_key = key
        if key == "invert_colors":
            config_key = "screen_reversed"
        val = cfg.get(config_key, item["options"][0][1])
        if key == "invert_colors":
            val = getattr(shared_data, "screen_reversed", val)
        for lbl, v in item["options"]:
            if v == val:
                return lbl
        return str(val)
    if item["type"] in ("readonly", "text"):
        return _get_value_from_system(shared_data, key)
    return ""


def apply_select(shared_data, item):
    """Handle B Select on item: toggle config or run action. Return True if something changed."""
    if not item or item["type"] not in ("toggle", "action"):
        return False
    cfg = getattr(shared_data, "config", {}) or {}
    key = item.get("key", "")

    if item["type"] == "toggle" and item.get("options"):
        # Map menu key to config key (e.g. invert_colors -> screen_reversed)
        config_key = key
        if key == "invert_colors":
            config_key = "screen_reversed"
        current = cfg.get(config_key, item["options"][0][1])
        for i, (_, v) in enumerate(item["options"]):
            if v == current:
                next_val = item["options"][(i + 1) % len(item["options"])][1]
                cfg[config_key] = next_val
                if key == "invert_colors":
                    shared_data.screen_reversed = bool(next_val)
                    shared_data.web_screen_reversed = bool(next_val)
                if hasattr(shared_data, "save_config"):
                    shared_data.save_config()
                return True
        return False

    if item["type"] == "action":
        def _run(cmd):
            try:
                subprocess.Popen(cmd, shell=True, start_new_session=True)
            except Exception as e:
                logger.warning("Menu action failed: %s", e)

        if key == "action_restart":
            threading.Thread(target=lambda: _run("sleep 2 && sudo reboot"), daemon=True).start()
            return True
        if key == "action_shutdown":
            threading.Thread(target=lambda: _run("sleep 2 && sudo shutdown -h now"), daemon=True).start()
            return True
        if key == "action_view_logs":
            # No-op on device; could open a submenu later
            return False
        if key == "action_clear_logs":
            threading.Thread(target=lambda: _run("truncate -s 0 /home/ragnar/Ragnar/data/logs/*.log 2>/dev/null || true"), daemon=True).start()
            return True
        if key == "action_check_updates":
            threading.Thread(target=lambda: _run("apt update 2>/dev/null"), daemon=True).start()
            return True
        if key in ("action_gpio_test", "action_button_mapping", "action_simulate_input", "action_reset_config", "action_factory_reset", "action_ssh_port", "action_safe_mode"):
            # Stub
            return False
    return False


def build_flat_entries(shared_data):
    """Build list of (display_line_string, is_header, item_or_none) for rendering."""
    entries = []
    for section, items in MENU_STRUCTURE:
        entries.append((section, True, None))
        for it in items:
            val = get_value_for_item(shared_data, it)
            if val is not None and str(val):
                text = (it["label"] + ": " + str(val))[:36]
            else:
                text = it["label"][:36]
            entries.append((text, False, it))
    return entries


def get_selectable_count(entries):
    return sum(1 for (_, is_h, _) in entries if not is_h)


def cursor_to_line_index(entries, cursor_selectable_index):
    """Map cursor (index among selectable lines) to flat line index."""
    n = 0
    for i, (_, is_header, _) in enumerate(entries):
        if not is_header:
            if n == cursor_selectable_index:
                return i
            n += 1
    return 0


def line_index_to_cursor(entries, line_index):
    """Map flat line index to selectable cursor index."""
    n = 0
    for i in range(min(line_index + 1, len(entries))):
        if not entries[i][1]:
            n += 1
    return max(0, n - 1)
