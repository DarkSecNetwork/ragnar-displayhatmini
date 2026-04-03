#!/usr/bin/env python3
"""Display HAT Mini boot splash: Booting / Starting Ragnar / boot log / button test (press Select to continue)."""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

_R = Path(__file__).resolve().parent.parent
if str(_R) not in sys.path:
    sys.path.insert(0, str(_R))
try:
    from display_text_util import compact_journal_line, ellipsis_fit_to_width
except ImportError:
    compact_journal_line = lambda s: (s or "").strip()
    ellipsis_fit_to_width = None  # type: ignore[misc, assignment]

try:
    from displayhatmini_buttons import PIN_A, PIN_B, PIN_X, PIN_Y
except ImportError:
    PIN_A, PIN_B, PIN_X, PIN_Y = 5, 6, 16, 24


def _get_boot_log_lines(max_lines=12):
    """Return last journal lines for this boot (message text compacted)."""
    try:
        out = subprocess.check_output(
            ["journalctl", "-b", "-n", str(max_lines * 3), "--no-pager", "-o", "short-iso"],
            timeout=5,
            text=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return ["(journal unavailable)"]
    lines = []
    for raw in out.strip().splitlines():
        raw = (raw or "").strip()
        if not raw:
            continue
        lines.append(compact_journal_line(raw))
        if len(lines) >= max_lines:
            break
    return lines[-max_lines:] if len(lines) > max_lines else lines


def _ensure_lgpio_factory() -> bool:
    """Prefer LGPIO (Bookworm); fall back to displayhatmini_buttons factory chain."""
    try:
        from gpiozero import Device
        from gpiozero.pins.lgpio import LGPIOFactory

        Device.pin_factory = LGPIOFactory()
        return True
    except Exception:
        pass
    try:
        from displayhatmini_buttons import _ensure_gpiozero_pin_factory

        return _ensure_gpiozero_pin_factory()
    except Exception:
        return False


def _draw_button_test_screen(
    epd, Image, ImageDraw, w: int, h: int, font_title, font_small, bg, fg, accent
) -> None:
    """Show GPIO mapping + instruction to press B (Select)."""
    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)
    y = 4
    if font_title:
        draw.text((4, y), "Button test", font=font_title, fill=accent)
        y += 28
    lines = [
        f"A (menu)   GPIO{PIN_A}",
        f"B (Select) GPIO{PIN_B}  <- press",
        f"X (up)     GPIO{PIN_X}",
        f"Y (down)   GPIO{PIN_Y}",
        "",
        "Press B (Select) to continue",
    ]
    margin_x = 4
    max_tw = max(40, w - 8)
    lh = 13
    for line in lines:
        if y + lh > h - 2:
            break
        if line and font_small:
            shown = (
                ellipsis_fit_to_width(draw, line, font_small, max_tw)
                if ellipsis_fit_to_width is not None
                else line[:60]
            )
        else:
            shown = line or " "
        draw.text((margin_x, y), shown, font=font_small, fill=fg)
        y += lh
    epd.display(img)


def _run_button_test(
    epd, Image, ImageDraw, w: int, h: int, font_title, font_small, bg, fg, accent
) -> None:
    """
    Wait for Select (B) via gpiozero + LGPIO; debounce 0.1s.
    Main thread polls a threading.Event so the process stays responsive (no busy loop).
    """
    try:
        delay = float(os.environ.get("RAGNAR_DHM_BUTTON_DELAY", "1.0"))
    except ValueError:
        delay = 1.0
    delay = max(0.0, delay)
    if delay > 0:
        time.sleep(delay)

    if not _ensure_lgpio_factory():
        print("display_boot_splash: gpiozero/LGPIO unavailable — skipping button wait", file=sys.stderr)
        return

    try:
        from gpiozero import Button
    except ImportError:
        print("display_boot_splash: gpiozero not installed — skipping button wait", file=sys.stderr)
        return

    def _journal_btn(line: str) -> None:
        # stderr → systemd journal (visible in journalctl -b / boot log)
        print(line, file=sys.stderr, flush=True)

    done = threading.Event()
    bounce = 0.1
    buttons = []

    def _on_a():
        _journal_btn(f"[BTN] A pressed (menu, GPIO{PIN_A})")

    def _on_x():
        _journal_btn(f"[BTN] X pressed (up, GPIO{PIN_X})")

    def _on_y():
        _journal_btn(f"[BTN] Y pressed (down, GPIO{PIN_Y})")

    def _on_b():
        _journal_btn("[BTN] B/Select pressed — continuing")
        done.set()

    btn_a = Button(PIN_A, pull_up=True, bounce_time=bounce)
    buttons.append(btn_a)
    btn_a.when_pressed = _on_a
    btn_b = Button(PIN_B, pull_up=True, bounce_time=bounce)
    buttons.append(btn_b)
    btn_b.when_pressed = _on_b
    btn_x = Button(PIN_X, pull_up=True, bounce_time=bounce)
    buttons.append(btn_x)
    btn_x.when_pressed = _on_x
    btn_y = Button(PIN_Y, pull_up=True, bounce_time=bounce)
    buttons.append(btn_y)
    btn_y.when_pressed = _on_y

    timeout_sec: Optional[float]
    raw_to = os.environ.get("RAGNAR_SPLASH_BUTTON_TIMEOUT_SEC", "").strip()
    try:
        timeout_sec = float(raw_to) if raw_to else None
    except ValueError:
        timeout_sec = None

    _draw_button_test_screen(epd, Image, ImageDraw, w, h, font_title, font_small, bg, fg, accent)

    deadline = time.monotonic() + timeout_sec if (timeout_sec is not None and timeout_sec > 0) else None
    try:
        while not done.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                print(
                    "display_boot_splash: RAGNAR_SPLASH_BUTTON_TIMEOUT_SEC — continuing without press",
                    file=sys.stderr,
                )
                return
            done.wait(0.05)
    finally:
        for b in buttons:
            try:
                b.close()
            except Exception:
                pass


def main():
    try:
        from PIL import Image, ImageDraw
        from waveshare_epd import displayhatmini
    except ImportError:
        return 0
    BG = (0, 0, 0)
    FG = (255, 255, 255)
    ACCENT = (120, 200, 255)
    try:
        epd = displayhatmini.EPD()
        if epd.init() != 0:
            return 1
        W, H = epd.width, epd.height
        epd.Clear(0)
    except Exception:
        return 1
    try:
        try:
            font_big = __import__("PIL.ImageFont", fromlist=["truetype"]).ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28
            )
        except Exception:
            font_big = None
        try:
            font_small = __import__("PIL.ImageFont", fromlist=["truetype"]).ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11
            )
        except Exception:
            font_small = None

        Image = __import__("PIL.Image", fromlist=["new"])
        ImageDraw = __import__("PIL.ImageDraw", fromlist=["Draw"])

        # 1) Booting...
        img = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(img)
        text = "Booting..."
        if font_big:
            bbox = draw.textbbox((0, 0), text, font=font_big)
        else:
            bbox = (0, 0, len(text) * 8, 20)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x, y = (W - tw) // 2, (H - th) // 2
        draw.text((x, y), text, font=font_big, fill=FG)
        epd.display(img)
        time.sleep(2.0)

        # 2) Starting Ragnar...
        img = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(img)
        text = "Starting Ragnar..."
        if font_big:
            bbox = draw.textbbox((0, 0), text, font=font_big)
        else:
            bbox = (0, 0, len(text) * 8, 20)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x, y = (W - tw) // 2, (H - th) // 2
        draw.text((x, y), text, font=font_big, fill=FG)
        epd.display(img)
        time.sleep(2.0)

        # 3) System log
        log_lines = _get_boot_log_lines(max_lines=12)
        img = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(img)
        draw.text((4, 2), "Boot log:", font=font_small, fill=FG)
        y = 16
        max_tw = max(40, W - 8)
        for line in log_lines:
            if y + 14 > H:
                break
            if ellipsis_fit_to_width is not None and font_small:
                shown = ellipsis_fit_to_width(draw, line, font_small, max_tw)
            else:
                shown = (line or "")[: max(20, W // 6)]
            draw.text((4, y), shown, font=font_small, fill=FG)
            y += 13
        epd.display(img)
        time.sleep(6.0)

        # 4) Button test — press B (Select) to continue
        skip = os.environ.get("RAGNAR_SKIP_DHM_BUTTONS", "").strip().lower()
        skip_test = os.environ.get("RAGNAR_SPLASH_SKIP_BUTTON_TEST", "").strip().lower()
        if skip in ("1", "true", "yes", "on") or skip_test in ("1", "true", "yes"):
            img = Image.new("RGB", (W, H), BG)
            draw = ImageDraw.Draw(img)
            msg = "Skipping button test (env)"
            if font_small:
                draw.text((4, H // 2), msg, font=font_small, fill=FG)
            epd.display(img)
            time.sleep(1.5)
        else:
            _run_button_test(epd, Image, ImageDraw, W, H, font_big, font_small, BG, FG, ACCENT)

        epd.Clear(0)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
