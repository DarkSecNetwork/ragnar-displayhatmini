"""
System health / PiSugar diagnostics for Display HAT Mini menu.
All probes are best-effort, time-bounded, and never raise to callers.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import threading
import time
from typing import Any, Callable, List, Optional

try:
    from pisugar_safe import safe_read_battery_level, safe_pisugar_available
except ImportError:

    def safe_pisugar_available(sd):
        return False

    def safe_read_battery_level(sd):
        return None


def _run(
    args: List[str],
    timeout: float = 3.0,
) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except Exception as e:
        return -1, "", str(e)


def i2c_bus_snapshot(bus: int = 1) -> str:
    code, out, err = _run(
        ["i2cdetect", "-y", str(bus)],
        timeout=4.0,
    )
    if code != 0:
        return f"i2cdetect: fail ({(err or 'n/a')[:80]})"
    lines = [ln for ln in out.splitlines() if ln.strip()][-6:]
    return "\n".join(lines) if lines else "(empty)"


def spi_device_present() -> bool:
    return bool(glob.glob("/dev/spidev*"))


def pisugar_service_active() -> bool:
    code, out, _ = _run(["systemctl", "is-active", "pisugar-server"], timeout=2.0)
    return code == 0 and "active" in (out or "").strip().lower()


def journal_grep(
    unit_or_slice: Optional[str],
    patterns: List[str],
    lines: int = 12,
) -> List[str]:
    """Last journal lines matching any pattern (slow — use small lines)."""
    try:
        cmd = ["journalctl", "-b", "-n", "200", "--no-pager"]
        if unit_or_slice:
            cmd.extend(["-u", unit_or_slice])
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=5.0)
        raw = (p.stdout or "").splitlines()
        out: List[str] = []
        plow = [x.lower() for x in patterns]
        for ln in raw:
            low = ln.lower()
            if any(x in low for x in plow):
                out.append(ln[:120])
            if len(out) >= lines:
                break
        return out
    except Exception:
        return []


def classify_boot_errors() -> dict:
    """Group recent journal hints by rough category."""
    blob = ""
    try:
        p = subprocess.run(
            ["journalctl", "-b", "-n", "400", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=6.0,
        )
        blob = (p.stdout or "").lower()
    except Exception:
        return {}

    def count(pat: str) -> int:
        return len(re.findall(pat, blob))

    return {
        "pisugar": count(r"pisugar|remote i/o error|os error 121"),
        "audio": count(r"alsa|pipewire|wireplumber"),
        "network": count(r"networkmanager|wpa_supplicant|nmcli|wlan"),
        "system": count(r"polkit|lightdm|bluetoothd|blkmapd"),
    }


def run_battery_diagnostics(shared_data: Any) -> List[str]:
    """
    Full test output lines for e-paper (ASCII only).
    Runs in worker thread — may take several seconds.
    """
    lines: List[str] = []
    lines.append("--- DIAG START ---")
    t0 = time.time()

    # I2C
    lines.append("[I2C bus 1]")
    lines.append(i2c_bus_snapshot(1)[:200].replace("\n", " | "))

    # SPI
    lines.append("[SPI]")
    lines.append("spidev: " + ("OK" if spi_device_present() else "none"))

    # pisugar-server
    lines.append("[pisugar-server]")
    lines.append("active: " + ("yes" if pisugar_service_active() else "no"))

    # TCP client / battery
    lines.append("[Ragnar PiSugar TCP]")
    lines.append("listener available: " + ("yes" if safe_pisugar_available(shared_data) else "no"))
    lvl = safe_read_battery_level(shared_data)
    lines.append("battery %: " + (str(int(lvl)) if lvl is not None else "n/a"))

    # Journal snippet
    lines.append("[recent PiSugar journal]")
    for j in journal_grep("pisugar-server", ["error", "warn", "121"], lines=4):
        lines.append(j[:100])

    overall = "PARTIAL"
    if safe_pisugar_available(shared_data) and lvl is not None:
        overall = "OK"
    elif not pisugar_service_active() and not safe_pisugar_available(shared_data):
        overall = "FAIL/not detected"

    lines.append(f"[RESULT] {overall} ({time.time()-t0:.1f}s)")
    lines.append("--- DIAG END ---")
    return lines


def get_live_status_lines(shared_data: Any) -> List[str]:
    """Short live summary for the health panel (8–14 lines)."""
    rows: List[str] = []
    rows.append("SYSTEM HEALTH")
    rows.append("PiSugar: " + ("OK" if safe_pisugar_available(shared_data) else "no TCP"))
    rows.append("pisugar-svc: " + ("active" if pisugar_service_active() else "inactive"))
    rows.append("SPI: " + ("OK" if spi_device_present() else "?"))
    i2c_short = i2c_bus_snapshot(1).splitlines()
    rows.append("I2C1: " + (i2c_short[-1][:36] if i2c_short else "?"))

    cat = classify_boot_errors()
    rows.append(f"errs~ P:{cat.get('pisugar',0)} A:{cat.get('audio',0)}")
    rows.append(f"     N:{cat.get('network',0)} S:{cat.get('system',0)}")
    rows.append("UP/D scroll  B:diag  A:close")
    return rows


def start_diagnostic_thread(shared_data: Any, on_done: Callable[[List[str]], None]) -> bool:
    """Run diagnostics in background; callback with line list."""
    if getattr(shared_data, "health_test_running", False):
        return False

    def _work():
        shared_data.health_test_running = True
        try:
            lines = run_battery_diagnostics(shared_data)
            on_done(lines)
        finally:
            shared_data.health_test_running = False

    threading.Thread(target=_work, daemon=True).start()
    return True
