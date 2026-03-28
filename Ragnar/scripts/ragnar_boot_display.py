#!/usr/bin/env python3
"""
Boot-time live journal viewer on Display HAT Mini (st7789).

SPI conflict: only ONE process can own the panel. This unit runs as Type=oneshot and EXITS
before ragnar.service starts (systemd After=/Wants= ordering). It shows the last ~45s of
boot journal (configurable) so you see kernel/systemd activity; Ragnar's own logs then appear
in display.py after handoff.

Env:
  RAGNAR_DIR          default /home/ragnar/Ragnar
  RAGNAR_BOOT_DISPLAY_SEC  how long to tail journal (default 45)
  RAGNAR_NETWORK_SCREEN_SEC  after journal, show network/SSH info (default 10; set 0 to skip)
"""
from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

# Defaults tuned for Pi Zero 2 W
RAGNAR_DIR = os.environ.get("RAGNAR_DIR", "/home/ragnar/Ragnar")
RUN_SEC = float(os.environ.get("RAGNAR_BOOT_DISPLAY_SEC", "45"))
NETWORK_SEC = float(os.environ.get("RAGNAR_NETWORK_SCREEN_SEC", "10"))
MAX_LINES = 14
TITLE = "RAGNAR BOOT LOG"
MIN_REDRAW_INTERVAL = 0.18  # ~5.5 fps max

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:
    from network_boot_facts import collect_network_facts
except ImportError:
    collect_network_facts = None  # type: ignore[misc, assignment]


def _classify(line: str) -> str:
    low = line.lower()
    if any(x in low for x in ("error", "failed", "traceback", "exception", "fatal")):
        return "[ERR] "
    if "warn" in low:
        return "[WRN] "
    if any(x in low for x in ("started", "reached target", "listening on", "active (running)")):
        return "[OK]  "
    return "      "


def _truncate(s: str, max_chars: int) -> str:
    s = s.replace("\t", " ")
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _reader(q: queue.Queue, stop: threading.Event) -> None:
    cmd = ["journalctl", "-f", "-b", "-o", "short-iso"]
    try:
        p = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except OSError:
        q.put("(journalctl not available)")
        return

    assert p.stdout is not None
    try:
        while not stop.is_set():
            line = p.stdout.readline()
            if not line:
                break
            q.put(line.rstrip("\n"))
    finally:
        try:
            p.terminate()
            p.wait(timeout=2)
        except Exception:
            pass


def main() -> int:
    start = time.time()
    try:
        from PIL import Image, ImageDraw, ImageFont
        from waveshare_epd import displayhatmini
    except ImportError as e:
        print(f"ragnar_boot_display: skip (import): {e}", file=sys.stderr)
        return 0

    lines_buf: list[str] = []

    try:
        epd = displayhatmini.EPD()
        if epd.init() != 0:
            print("ragnar_boot_display: EPD init failed", file=sys.stderr)
            return 0
        w, h = epd.width, epd.height
    except Exception as e:
        print(f"ragnar_boot_display: display error: {e}", file=sys.stderr)
        return 0

    try:
        font_title = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14
        )
        font_body = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 9
        )
    except OSError:
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()

    # ~42 chars at 9px mono on 320px; fewer in portrait
    max_chars = max(28, min(44, w // 7))

    q: queue.Queue[str] = queue.Queue(maxsize=400)
    stop = threading.Event()
    t = threading.Thread(target=_reader, args=(q, stop), daemon=True)
    t.start()

    # Seed with recent boot lines
    try:
        out = subprocess.check_output(
            ["journalctl", "-b", "-n", "30", "--no-pager", "-o", "short-iso"],
            text=True,
            timeout=8,
        )
        for raw in out.strip().splitlines():
            raw = raw.strip()
            if raw:
                lines_buf.append(_classify(raw) + _truncate(raw, max_chars + 6))
                if len(lines_buf) > MAX_LINES + 8:
                    lines_buf = lines_buf[-(MAX_LINES + 8) :]
    except Exception:
        pass

    last_draw = 0.0
    bg = (0, 0, 0)
    fg = (220, 220, 220)
    err_fg = (255, 80, 80)
    warn_fg = (255, 200, 100)
    ok_fg = (120, 255, 140)

    try:
        while time.time() - start < RUN_SEC:
            try:
                while True:
                    lines_buf.append(
                        _classify(line := q.get_nowait())
                        + _truncate(line, max_chars + 6)
                    )
            except queue.Empty:
                pass
            if len(lines_buf) > MAX_LINES + 40:
                lines_buf = lines_buf[-(MAX_LINES + 40) :]

            now = time.time()
            if now - last_draw < MIN_REDRAW_INTERVAL:
                time.sleep(0.02)
                continue
            last_draw = now

            img = Image.new("RGB", (w, h), bg)
            draw = ImageDraw.Draw(img)
            draw.rectangle((0, 0, w - 1, 18), outline=(60, 60, 60))
            draw.text((2, 1), TITLE, font=font_title, fill=(255, 255, 255))

            y = 22
            row_h = 13
            visible = lines_buf[-MAX_LINES:]
            for row in visible:
                col = fg
                if row.startswith("[ERR]"):
                    col = err_fg
                elif row.startswith("[WRN]"):
                    col = warn_fg
                elif row.startswith("[OK]"):
                    col = ok_fg
                draw.text((0, y), row[: max_chars + 12], font=font_body, fill=col)
                y += row_h
                if y > h - 4:
                    break

            try:
                epd.display(img)
            except Exception as e:
                print(f"ragnar_boot_display: frame error: {e}", file=sys.stderr)

            time.sleep(0.03)
    finally:
        stop.set()

    # --- Phase 2: network + SSH (keep SPI open — do not module_exit before this) ---
    if NETWORK_SEC > 0.5 and collect_network_facts is not None:
        try:
            _show_network_screen(epd, w, h, font_title, font_body, NETWORK_SEC)
        except Exception as e:
            print(f"ragnar_boot_display: network screen error: {e}", file=sys.stderr)

    try:
        epd.module_exit()
    except Exception:
        pass

    print("ragnar_boot_display: finished", file=sys.stderr)
    return 0


def _show_network_screen(epd, w: int, h: int, font_title, font_body, duration_sec: float) -> None:
    """Full-screen network summary for SSH/LAN discovery."""
    from PIL import Image, ImageDraw

    t_end = time.time() + duration_sec
    bg = (10, 14, 28)
    fg = (235, 240, 255)
    accent = (120, 200, 255)
    warn = (255, 180, 100)

    last_log = ""
    while time.time() < t_end:
        facts = collect_network_facts()
        line = f"{facts.detail} ssh={facts.ssh_status}"
        if line != last_log:
            print(f"ragnar_boot_display: network {line}", file=sys.stderr)
            last_log = line

        img = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(img)
        draw.text((4, 2), "RAGNAR NETWORK", font=font_title, fill=accent)

        y = 22
        lh = 14
        lines = [
            f"IF: {facts.interface}",
            f"IP: {facts.ip_addr}",
            f"GW: {facts.gateway}",
            f"DNS: {facts.dns}",
        ]
        ssh_line = f"SSH: {facts.ssh_status}"
        for line in lines:
            col = fg
            if "NO NETWORK" in line:
                col = warn
            draw.text((4, y), line[:48], font=font_body, fill=col)
            y += lh

        ssh_col = accent if facts.ssh_status == "READY" else (warn if facts.ssh_status in ("OFFLINE", "LOCALHOST") else fg)
        draw.text((4, y), ssh_line[:48], font=font_body, fill=ssh_col)
        y += lh + 4
        draw.text((4, y), "ssh ragnar@<IP>", font=font_body, fill=(160, 160, 180))

        try:
            epd.display(img)
        except Exception as e:
            print(f"ragnar_boot_display: network frame: {e}", file=sys.stderr)
        time.sleep(0.5)

    print("ragnar_boot_display: network screen done", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
