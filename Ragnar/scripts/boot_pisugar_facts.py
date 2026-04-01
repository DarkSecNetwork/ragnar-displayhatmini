#!/usr/bin/env python3
"""
PiSugar + I2C facts for the Display HAT Mini boot splash (before Ragnar main UI).
"""
from __future__ import annotations

import re
import socket
import subprocess
from dataclasses import dataclass


@dataclass
class PiSugarBootFacts:
    model_label: str
    service_active: bool
    tcp_port_open: bool
    tcp_detail: str
    i2c_grid_lines: list[str]
    i2c_summary: str
    hint_lines: list[str]


def _run(cmd: list[str], timeout: float = 4.0) -> str:
    try:
        return subprocess.check_output(cmd, text=True, timeout=timeout, stderr=subprocess.DEVNULL)
    except Exception:
        return ""


def _detect_pisugar_model() -> str:
    out = _run(["debconf-show", "pisugar-server"], timeout=2.0)
    candidates: list[str] = []
    if out:
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.search(r"\*?\s*pisugar-server/\S+:\s*(.+)$", line, re.I)
            if m:
                val = m.group(1).strip()
                if val and val.lower() not in ("none", "<unsaved>", ""):
                    candidates.append(val)
    if candidates:
        for c in candidates:
            if re.search(r"pisugar|[0-9]|plus|pro", c, re.I):
                return c[:52]
        return candidates[0][:52]
    for path in ("/etc/default/pisugar-server", "/etc/pisugar-server"):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                txt = f.read(4000)
            m = re.search(r"(?i)(pisugar\s*\d|model\s*[=:]\s*[^\s\n]+)", txt)
            if m:
                return m.group(0).strip()[:48]
        except OSError:
            pass
    ver = _run(["dpkg-query", "-W", "-f=${Version}", "pisugar-server"], timeout=2.0).strip()
    if ver:
        return f"PiSugar server {ver}"
    return "PiSugar (pisugar-server)"


def _systemctl_is_active(unit: str) -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return r.returncode == 0 and r.stdout.strip() == "active"
    except Exception:
        return False


def _tcp_localhost_open(port: int, timeout: float = 0.4) -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except OSError:
        return False


def _i2cdetect_lines(bus: int = 1) -> tuple[list[str], str]:
    """Return (grid lines for display, one-line summary of addresses found)."""
    out = _run(["i2cdetect", "-y", str(bus)], timeout=5.0)
    if not out.strip():
        return (
            ["(i2cdetect unavailable — apt install i2c-tools?)"],
            "I2C: ?",
        )
    raw_lines = [ln.rstrip() for ln in out.strip().splitlines() if ln.strip()]
    addrs: list[str] = []
    for ln in raw_lines:
        parts = ln.split()
        if not parts or not re.match(r"^[0-9a-f]{2}:$", parts[0], re.I):
            continue
        for cell in parts[1:]:
            c = cell.strip().upper()
            if re.match(r"^[0-9A-F]{2}$", c) and c != "--":
                addrs.append(f"0x{c}")
            elif c == "UU":
                addrs.append("UU")
    summary = "Bus %d: %s" % (bus, " ".join(addrs) if addrs else "(no devices)")
    return raw_lines, summary


def collect_pisugar_boot_facts() -> PiSugarBootFacts:
    model = _detect_pisugar_model()
    active = _systemctl_is_active("pisugar-server")
    # PiSugar Power Manager often listens on 8421 (web); try common ports
    tcp_ok = False
    tcp_detail = "no listener"
    for port in (8421, 8422, 8423):
        if _tcp_localhost_open(port):
            tcp_ok = True
            tcp_detail = f"127.0.0.1:{port}"
            break
    grid, i2c_sum = _i2cdetect_lines(1)

    hints: list[str] = []
    if not active:
        hints.append("Service: sudo systemctl start pisugar-server")
    elif not tcp_ok:
        hints.append("TCP: wait or journalctl -u pisugar-server")
    if "(no devices)" in i2c_sum or "no devices" in i2c_sum.lower():
        hints.append("I2C: reseat PiSugar, 5V, check stack")
        hints.append("See: Ragnar docs PISUGAR3_BOOT.md")
    if not hints:
        hints.append("Battery UI: http://<pi-ip>:8421")

    return PiSugarBootFacts(
        model_label=model,
        service_active=active,
        tcp_port_open=tcp_ok,
        tcp_detail=tcp_detail,
        i2c_grid_lines=grid,
        i2c_summary=i2c_sum,
        hint_lines=hints[:3],
    )
