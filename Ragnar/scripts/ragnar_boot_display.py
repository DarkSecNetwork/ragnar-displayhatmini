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
  RAGNAR_BOOT_PISUGAR_SCREEN_SEC  PiSugar installer only: total seconds split 50/50 between
      connection-status screen and I2C bus 1 chart (0 = skip both).
  RAGNAR_BOOT_BUTTON_HELP_SEC  Display HAT Mini button legend (0 = skip).
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
PISUGAR_BOOT_SEC = float(os.environ.get("RAGNAR_BOOT_PISUGAR_SCREEN_SEC", "0"))
BUTTON_HELP_SEC = float(os.environ.get("RAGNAR_BOOT_BUTTON_HELP_SEC", "10"))
MAX_LINES = 14
TITLE = "RAGNAR BOOT LOG"
MIN_REDRAW_INTERVAL = 0.18  # ~5.5 fps max

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
_RAGNAR_ROOT = str(Path(__file__).resolve().parent.parent)
for _p in (_SCRIPT_DIR, _RAGNAR_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from display_text_util import compact_journal_line, ellipsis_fit_to_width
except ImportError:
    compact_journal_line = lambda s: (s or "").strip()  # type: ignore[assignment, misc]
    ellipsis_fit_to_width = None  # type: ignore[assignment, misc]

try:
    from network_boot_facts import collect_network_facts
except ImportError:
    collect_network_facts = None  # type: ignore[misc, assignment]

try:
    from boot_pisugar_facts import collect_pisugar_boot_facts
except ImportError:
    collect_pisugar_boot_facts = None  # type: ignore[misc, assignment]


def _classify(line: str) -> str:
    low = line.lower()
    if any(x in low for x in ("error", "failed", "traceback", "exception", "fatal")):
        return "[ERR] "
    if "warn" in low:
        return "[WRN] "
    if any(x in low for x in ("started", "reached target", "listening on", "active (running)")):
        return "[OK]  "
    return "      "


def _format_log_row(raw: str) -> str:
    """Prefix + compact message (timestamp stripped) for display buffer."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    body = compact_journal_line(raw)
    return _classify(raw) + body[:500]


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
        font_tiny = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 7
        )
    except OSError:
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()
        font_tiny = font_body

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
            row = _format_log_row(raw)
            if row:
                lines_buf.append(row)
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
                    row = _format_log_row(q.get_nowait())
                    if row:
                        lines_buf.append(row)
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

            margin_x = 2
            max_text_w = max(40, w - 2 * margin_x)
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
                if ellipsis_fit_to_width is not None:
                    fit = ellipsis_fit_to_width(draw, row, font_body, max_text_w)
                else:
                    fit = row[: max(20, w // 6)]
                draw.text((margin_x, y), fit, font=font_body, fill=col)
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

    if PISUGAR_BOOT_SEC > 0.5 and collect_pisugar_boot_facts is not None:
        try:
            half = PISUGAR_BOOT_SEC / 2.0
            _show_pisugar_status_screen(epd, w, h, font_title, font_body, half)
            _show_pisugar_i2c_screen(epd, w, h, font_title, font_tiny, half)
        except Exception as e:
            print(f"ragnar_boot_display: PiSugar boot screen error: {e}", file=sys.stderr)

    if BUTTON_HELP_SEC > 0.5:
        try:
            _show_button_help_screen(epd, w, h, font_title, font_body, BUTTON_HELP_SEC)
        except Exception as e:
            print(f"ragnar_boot_display: button help screen error: {e}", file=sys.stderr)

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
        margin_x = 4
        max_tw = max(40, w - 2 * margin_x)
        for line in lines:
            col = fg
            if "NO NETWORK" in line:
                col = warn
            fit = (
                ellipsis_fit_to_width(draw, line, font_body, max_tw)
                if ellipsis_fit_to_width is not None
                else line[:48]
            )
            draw.text((margin_x, y), fit, font=font_body, fill=col)
            y += lh

        ssh_col = accent if facts.ssh_status == "READY" else (warn if facts.ssh_status in ("OFFLINE", "LOCALHOST") else fg)
        ssh_fit = (
            ellipsis_fit_to_width(draw, ssh_line, font_body, max_tw)
            if ellipsis_fit_to_width is not None
            else ssh_line[:48]
        )
        draw.text((margin_x, y), ssh_fit, font=font_body, fill=ssh_col)
        y += lh + 4
        draw.text((4, y), "ssh ragnar@<IP>", font=font_body, fill=(160, 160, 180))

        try:
            epd.display(img)
        except Exception as e:
            print(f"ragnar_boot_display: network frame: {e}", file=sys.stderr)
        time.sleep(0.5)

    print("ragnar_boot_display: network screen done", file=sys.stderr)


def _show_pisugar_status_screen(
    epd, w: int, h: int, font_title, font_body, duration_sec: float
) -> None:
    from PIL import Image, ImageDraw

    t_end = time.time() + duration_sec
    bg = (18, 12, 22)
    fg = (240, 230, 245)
    ok = (130, 255, 160)
    bad = (255, 100, 100)
    warn = (255, 200, 120)
    accent = (220, 160, 255)

    while time.time() < t_end:
        facts = collect_pisugar_boot_facts()
        img = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(img)
        draw.text((4, 2), "RAGNAR PISUGAR", font=font_title, fill=accent)

        margin_x = 4
        max_tw = max(40, w - 2 * margin_x)
        y = 22
        lh = 13

        def put(line: str, color=fg) -> None:
            nonlocal y
            if y + lh > h - 2:
                return
            fit = (
                ellipsis_fit_to_width(draw, line, font_body, max_tw)
                if ellipsis_fit_to_width is not None
                else line[:48]
            )
            draw.text((margin_x, y), fit, font=font_body, fill=color)
            y += lh

        mfit = (
            ellipsis_fit_to_width(draw, facts.model_label, font_body, max_tw)
            if ellipsis_fit_to_width is not None
            else facts.model_label[:48]
        )
        draw.text((margin_x, y), mfit, font=font_body, fill=(200, 200, 255))
        y += lh + 2

        put(
            f"pisugar-server: {'ACTIVE' if facts.service_active else 'INACTIVE'}",
            ok if facts.service_active else bad,
        )
        put(
            f"Power mgr TCP: {facts.tcp_detail}"
            if facts.tcp_port_open
            else "Power mgr TCP: not listening (8421?)",
            ok if facts.tcp_port_open else warn,
        )
        put(f"I2C: {facts.i2c_summary}", ok if "no devices" not in facts.i2c_summary.lower() else warn)
        y += 2
        for hl in facts.hint_lines:
            put(hl, warn)

        try:
            epd.display(img)
        except Exception as e:
            print(f"ragnar_boot_display: pisugar status frame: {e}", file=sys.stderr)
        time.sleep(0.5)

    print("ragnar_boot_display: PiSugar status screen done", file=sys.stderr)


def _show_pisugar_i2c_screen(
    epd, w: int, h: int, font_title, font_tiny, duration_sec: float
) -> None:
    from PIL import Image, ImageDraw

    t_end = time.time() + duration_sec
    bg = (8, 14, 18)
    fg = (200, 220, 230)
    accent = (100, 200, 255)

    while time.time() < t_end:
        facts = collect_pisugar_boot_facts()
        img = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(img)
        draw.text((4, 2), "I2C BUS 1 (i2cdetect)", font=font_title, fill=accent)
        margin_x = 2
        max_tw = max(36, w - 4)
        y = 22
        lh = 10
        summary = (
            ellipsis_fit_to_width(draw, facts.i2c_summary, font_tiny, max_tw)
            if ellipsis_fit_to_width is not None
            else facts.i2c_summary[:56]
        )
        draw.text((margin_x, y), summary, font=font_tiny, fill=(180, 255, 180))
        y += lh + 2
        for raw in facts.i2c_grid_lines:
            if y + lh > h - 2:
                break
            fit = (
                ellipsis_fit_to_width(draw, raw, font_tiny, max_tw)
                if ellipsis_fit_to_width is not None
                else raw[: w // 5]
            )
            draw.text((margin_x, y), fit, font=font_tiny, fill=fg)
            y += lh

        try:
            epd.display(img)
        except Exception as e:
            print(f"ragnar_boot_display: pisugar i2c frame: {e}", file=sys.stderr)
        time.sleep(0.5)

    print("ragnar_boot_display: PiSugar I2C screen done", file=sys.stderr)


def _show_button_help_screen(
    epd, w: int, h: int, font_title, font_body, duration_sec: float
) -> None:
    """Display HAT Mini — short legend (see MENU_BUTTONS.md)."""
    from PIL import Image, ImageDraw

    t_end = time.time() + duration_sec
    bg = (12, 18, 14)
    fg = (230, 240, 230)
    accent = (160, 255, 180)
    lines = [
        "A: Menu open/close",
        "B short: Select",
        "B long: Back",
        "B double: Back",
        "X: Up    Y: Down",
    ]

    while time.time() < t_end:
        img = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(img)
        draw.text((4, 2), "BUTTONS (HAT Mini)", font=font_title, fill=accent)
        margin_x = 4
        max_tw = max(40, w - 2 * margin_x)
        y = 24
        lh = 15
        for line in lines:
            if y + lh > h - 4:
                break
            fit = (
                ellipsis_fit_to_width(draw, line, font_body, max_tw)
                if ellipsis_fit_to_width is not None
                else line[:48]
            )
            draw.text((margin_x, y), fit, font=font_body, fill=fg)
            y += lh
        hint = "Open menu (A) for settings"
        hf = (
            ellipsis_fit_to_width(draw, hint, font_body, max_tw)
            if ellipsis_fit_to_width is not None
            else hint[:48]
        )
        draw.text((margin_x, min(y + 4, h - 18)), hf, font=font_body, fill=(150, 180, 150))

        try:
            epd.display(img)
        except Exception as e:
            print(f"ragnar_boot_display: button help frame: {e}", file=sys.stderr)
        time.sleep(0.5)

    print("ragnar_boot_display: button help screen done", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
