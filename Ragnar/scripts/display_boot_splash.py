#!/usr/bin/env python3
"""Display HAT Mini boot splash: boot log → network/IP → button map (press B/Select to continue). One SPI handoff."""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

_R = Path(__file__).resolve().parent.parent
_SCRIPTS = Path(__file__).resolve().parent
for _p in (_R, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
try:
    from display_text_util import compact_journal_line, ellipsis_fit_to_width
except ImportError:
    compact_journal_line = lambda s: (s or "").strip()
    ellipsis_fit_to_width = None  # type: ignore[misc, assignment]

try:
    from displayhatmini_buttons import PIN_A, PIN_B, PIN_X, PIN_Y
except ImportError:
    PIN_A, PIN_B, PIN_X, PIN_Y = 5, 6, 16, 24


def _init_lgpio_at_startup() -> bool:
    """Force LGPIO before display init / splash wait (reliable GPIO diagnostic)."""
    try:
        from gpiozero import Device
        from gpiozero.pins.lgpio import LGPIOFactory

        Device.pin_factory = LGPIOFactory()
        print("display_boot_splash: LGPIO pin factory active", file=sys.stderr, flush=True)
        return True
    except Exception as e:
        print(f"display_boot_splash: LGPIO primary init failed ({e}); trying fallback", file=sys.stderr, flush=True)
    try:
        from displayhatmini_buttons import _ensure_gpiozero_pin_factory

        return _ensure_gpiozero_pin_factory()
    except Exception as e2:
        print(f"display_boot_splash: gpio pin factory unavailable: {e2}", file=sys.stderr, flush=True)
        return False


def _ensure_lgpio_factory() -> bool:
    """Idempotent: prefer LGPIO; fall back to displayhatmini_buttons chain."""
    return _init_lgpio_at_startup()


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


def _draw_network_screen(epd, Image, ImageDraw, w: int, h: int, font_title, font_small, bg, fg, accent):
    """Show iface, IPv4, gateway, SSH listen (network_boot_facts)."""
    lines = ["Network", "(no data)"]
    try:
        from network_boot_facts import collect_network_facts

        nf = collect_network_facts()
        lines = [
            "Network",
            f"IF {nf.interface}  IP {nf.ip_addr}",
            f"GW {nf.gateway}  DNS {nf.dns[:28]}",
            f"SSH {nf.ssh_status}",
        ]
    except Exception as e:
        lines = ["Network", str(e)[:40]]

    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)
    y = 4
    if font_title:
        draw.text((4, y), lines[0], font=font_title, fill=accent)
        y += 26
    margin_x = 4
    max_tw = max(40, w - 8)
    lh = 13
    for line in lines[1:]:
        if y + lh > h - 2:
            break
        if font_small:
            shown = (
                ellipsis_fit_to_width(draw, line, font_small, max_tw)
                if ellipsis_fit_to_width is not None
                else line[:56]
            )
        else:
            shown = line
        draw.text((margin_x, y), shown, font=font_small, fill=fg)
        y += lh
    epd.display(img)


def _draw_button_wait_ui(
    epd,
    Image,
    ImageDraw,
    w: int,
    h: int,
    font_title,
    font_small,
    bg,
    fg,
    accent,
    *,
    last_input: str,
    debug: bool,
    remaining_sec=None,
) -> None:
    """Live splash: mapping + last key; debug adds wait hint and countdown feel."""
    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)
    y = 4
    if font_title:
        draw.text((4, y), "Button test", font=font_title, fill=accent)
        y += 26
    margin_x = 4
    max_tw = max(40, w - 8)
    lh = 12
    lines = [
        f"A={PIN_A} B={PIN_B} X={PIN_X} Y={PIN_Y}",
        "B = Select (continue)",
    ]
    for line in lines:
        if y + lh > h - 2:
            break
        shown = (
            ellipsis_fit_to_width(draw, line, font_small, max_tw)
            if font_small and ellipsis_fit_to_width is not None
            else (line[:56] if line else "")
        )
        draw.text((margin_x, y), shown, font=font_small, fill=fg)
        y += lh
    y += 4
    if debug:
        draw.text((margin_x, y), "Waiting for button... (press A)", font=font_small, fill=(180, 220, 255))
        y += lh
        draw.text((margin_x, y), "Press B (Select) to continue", font=font_small, fill=(160, 200, 255))
        y += lh
    last_line = f"Last input: {last_input}"
    draw.text((margin_x, y), last_line[:48], font=font_small, fill=(200, 200, 120))
    y += lh
    if debug and remaining_sec is not None:
        draw.text((margin_x, y), f"Timeout in ~{int(max(0, remaining_sec))}s", font=font_small, fill=(150, 150, 150))
    epd.display(img)


def _draw_raw_gpio_ui(
    epd,
    Image,
    ImageDraw,
    w: int,
    h: int,
    font_title,
    font_small,
    bg,
    fg,
    accent,
    *,
    vals: dict,
    remaining_sec: Optional[float],
    hint: str,
) -> None:
    """Low-level GPIO diagnostic: show BCM pin levels (5,6,16,24)."""
    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)
    y = 4
    if font_title:
        draw.text((4, y), "RAW GPIO", font=font_title, fill=accent)
        y += 26
    margin_x = 4
    max_tw = max(40, w - 8)
    lh = 12
    parts = [f"{p}={vals.get(p, '?')}" for p in (PIN_A, PIN_B, PIN_X, PIN_Y)]
    line = " ".join(parts)
    shown = (
        ellipsis_fit_to_width(draw, line, font_small, max_tw)
        if font_small and ellipsis_fit_to_width is not None
        else line[:56]
    )
    draw.text((margin_x, y), shown, font=font_small, fill=fg)
    y += lh + 2
    if hint:
        hs = (
            ellipsis_fit_to_width(draw, hint, font_small, max_tw)
            if font_small and ellipsis_fit_to_width is not None
            else hint[:56]
        )
        draw.text((margin_x, y), hs, font=font_small, fill=(180, 200, 255))
        y += lh
    if remaining_sec is not None:
        draw.text(
            (margin_x, y),
            f"Timeout ~{int(max(0, remaining_sec))}s  (B low = continue)",
            font=font_small,
            fill=(150, 150, 150),
        )
    epd.display(img)


def _open_raw_pin_reader(pins: tuple[int, ...]):
    """Return (reader, None) or (None, error string). Prefer lgpio, then RPi.GPIO."""
    pins = tuple(pins)

    def _read_lgpio():
        import lgpio

        pull = getattr(lgpio, "SET_PULL_UP", None)
        if pull is None:
            pull = 0x00000020

        h = None
        for chip in (0, 4):
            try:
                h = lgpio.gpiochip_open(chip)
                break
            except Exception:
                continue
        if h is None:
            raise RuntimeError("gpiochip_open failed for chips 0 and 4")

        for p in pins:
            try:
                lgpio.gpio_claim_input(h, p, pull)
            except TypeError:
                lgpio.gpio_claim_input(h, p)

        class _R:
            def read(self_inner):
                return {p: int(lgpio.gpio_read(h, p)) for p in pins}

            def close(self_inner):
                for p in pins:
                    try:
                        lgpio.gpio_free(h, p)
                    except Exception:
                        pass
                try:
                    lgpio.gpiochip_close(h)
                except Exception:
                    pass

        return _R()

    try:
        return _read_lgpio(), None
    except Exception as e:
        lgpio_err = str(e)

    try:
        import RPi.GPIO as GPIO

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for p in pins:
            GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        class _R:
            def read(self_inner):
                return {p: int(GPIO.input(p)) for p in pins}

            def close(self_inner):
                try:
                    GPIO.cleanup()
                except Exception:
                    pass

        return _R(), None
    except Exception as e2:
        return None, f"lgpio: {lgpio_err}; RPi.GPIO: {e2}"


def _draw_button_continue_screen(epd, Image, ImageDraw, w, h, font_title, font_small, bg, fg, accent):
    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)
    y = (h // 2) - 24
    msg = "Button detected — continuing..."
    if font_title:
        shown = (
            ellipsis_fit_to_width(draw, msg, font_title, max(40, w - 8))
            if ellipsis_fit_to_width is not None
            else msg[:24]
        )
        draw.text((4, y), shown, font=font_title, fill=accent)
    elif font_small:
        draw.text((4, y), msg[:40], font=font_small, fill=accent)
    epd.display(img)


def _run_button_test(
    epd, Image, ImageDraw, w: int, h: int, font_title, font_small, bg, fg, accent
) -> None:
    """Wait for Select (B); live UI + optional RAGNAR_SPLASH_DEBUG."""
    splash_debug = os.environ.get("RAGNAR_SPLASH_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")

    try:
        delay = float(os.environ.get("RAGNAR_DHM_BUTTON_DELAY", "0.25"))
    except ValueError:
        delay = 1.0
    delay = max(0.0, delay)
    if delay > 0:
        time.sleep(delay)

    if not _ensure_lgpio_factory():
        print("display_boot_splash: gpiozero/LGPIO unavailable — skipping button wait", file=sys.stderr, flush=True)
        return

    try:
        from gpiozero import Button
    except ImportError:
        print("display_boot_splash: gpiozero not installed — skipping button wait", file=sys.stderr, flush=True)
        return

    lock = threading.Lock()
    state = {"last": "NONE", "select": False}

    def _journal(line: str) -> None:
        print(line, file=sys.stderr, flush=True)

    def _set_last(name: str) -> None:
        with lock:
            state["last"] = name

    def _on_a():
        _set_last("A")
        _journal(f"[BTN] A (GPIO{PIN_A})")

    def _on_x():
        _set_last("X")
        _journal(f"[BTN] X (GPIO{PIN_X})")

    def _on_y():
        _set_last("Y")
        _journal(f"[BTN] Y (GPIO{PIN_Y})")

    def _on_b():
        with lock:
            state["last"] = "SELECT"
            state["select"] = True
        print("[BTN] SELECT detected", file=sys.stderr, flush=True)
        print("[BTN] SELECT detected", flush=True)

    bounce = 0.1
    buttons = []
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

    raw_to = os.environ.get("RAGNAR_SPLASH_BUTTON_TIMEOUT_SEC", "").strip()
    try:
        timeout_sec = float(raw_to) if raw_to else 180.0
        if timeout_sec <= 0:
            timeout_sec = 180.0
    except ValueError:
        timeout_sec = 180.0

    raw_fallback_sec = 5.0
    raw_env = os.environ.get("RAGNAR_SPLASH_RAW_FALLBACK_SEC", "").strip()
    if raw_env:
        try:
            raw_fallback_sec = float(raw_env)
        except ValueError:
            pass
    raw_fallback_sec = max(0.0, raw_fallback_sec)

    deadline = time.monotonic() + timeout_sec
    last_drawn = ""
    wait_start = time.monotonic()
    raw_pins = (PIN_A, PIN_B, PIN_X, PIN_Y)

    def _close_gpiozero_buttons() -> None:
        for b in buttons:
            try:
                b.close()
            except Exception:
                pass
        buttons.clear()

    try:
        while True:
            now = time.monotonic()
            with lock:
                sel = state["select"]
                last = state["last"]
            if sel:
                _draw_button_continue_screen(epd, Image, ImageDraw, w, h, font_title, font_small, bg, fg, accent)
                print("[✔] Splash input received", file=sys.stderr, flush=True)
                print("[✔] Splash input received", flush=True)
                time.sleep(0.9)
                return

            if now >= deadline:
                if splash_debug:
                    print(
                        "[WARN] Splash timeout reached without button press",
                        file=sys.stderr,
                        flush=True,
                    )
                print(
                    "[⚠] No button input detected within timeout",
                    file=sys.stderr,
                    flush=True,
                )
                print("[⚠] No button input detected within timeout", flush=True)
                return

            # No gpiozero activity for N seconds → low-level read to isolate library vs wiring.
            if raw_fallback_sec > 0 and (now - wait_start) >= raw_fallback_sec and last == "NONE":
                print(
                    f"[GPIO] No gpiozero events in {raw_fallback_sec:g}s — raw pin read diagnostic",
                    file=sys.stderr,
                    flush=True,
                )
                print(
                    f"[GPIO] No gpiozero events in {raw_fallback_sec:g}s — raw pin read diagnostic",
                    flush=True,
                )
                _close_gpiozero_buttons()
                time.sleep(0.05)
                reader, raw_err = _open_raw_pin_reader(raw_pins)
                if reader is None:
                    print(f"[GPIO] Raw read unavailable: {raw_err}", file=sys.stderr, flush=True)
                    print(f"[GPIO] Raw read unavailable: {raw_err}", flush=True)
                    return

                baseline: Optional[dict[int, int]] = None
                raw_levels_changed = False
                try:
                    while True:
                        now = time.monotonic()
                        if now >= deadline:
                            if raw_levels_changed:
                                print(
                                    "[GPIO] Raw levels changed during wait but gpiozero reported no events — "
                                    "likely gpiozero / pin-factory layer issue",
                                    file=sys.stderr,
                                    flush=True,
                                )
                                print(
                                    "[GPIO] Raw levels changed during wait but gpiozero reported no events — "
                                    "likely gpiozero / pin-factory layer issue",
                                    flush=True,
                                )
                            else:
                                print(
                                    "[GPIO] Raw levels never changed — check BCM pin mapping, wiring, "
                                    "or display/SPI interference",
                                    file=sys.stderr,
                                    flush=True,
                                )
                                print(
                                    "[GPIO] Raw levels never changed — check BCM pin mapping, wiring, "
                                    "or display/SPI interference",
                                    flush=True,
                                )
                            if splash_debug:
                                print(
                                    "[WARN] Splash timeout reached without button press",
                                    file=sys.stderr,
                                    flush=True,
                                )
                            print(
                                "[⚠] No button input detected within timeout",
                                file=sys.stderr,
                                flush=True,
                            )
                            print("[⚠] No button input detected within timeout", flush=True)
                            return

                        vals = reader.read()
                        parts = [f"{p}={vals[p]}" for p in raw_pins]
                        print(f"[GPIO RAW] {' '.join(parts)}", file=sys.stderr, flush=True)
                        print(f"[GPIO RAW] {' '.join(parts)}", flush=True)

                        if baseline is None:
                            baseline = dict(vals)
                        elif vals != baseline:
                            raw_levels_changed = True

                        rem = deadline - now
                        hint = "Press buttons; levels should toggle. B low = continue."
                        _draw_raw_gpio_ui(
                            epd,
                            Image,
                            ImageDraw,
                            w,
                            h,
                            font_title,
                            font_small,
                            bg,
                            fg,
                            accent,
                            vals=vals,
                            remaining_sec=rem if splash_debug else None,
                            hint=hint,
                        )

                        if vals.get(PIN_B) == 0:
                            print(
                                "[GPIO] B (GPIO%d) read low via raw GPIO — gpiozero saw no prior events — "
                                "likely gpiozero / pin-factory layer issue" % PIN_B,
                                file=sys.stderr,
                                flush=True,
                            )
                            print(
                                "[GPIO] B (GPIO%d) read low via raw GPIO — gpiozero saw no prior events — "
                                "likely gpiozero / pin-factory layer issue" % PIN_B,
                                flush=True,
                            )
                            _draw_button_continue_screen(
                                epd, Image, ImageDraw, w, h, font_title, font_small, bg, fg, accent
                            )
                            print("[✔] Splash input received", file=sys.stderr, flush=True)
                            print("[✔] Splash input received", flush=True)
                            time.sleep(0.9)
                            return

                        time.sleep(0.5)
                finally:
                    try:
                        reader.close()
                    except Exception:
                        pass

            rem = deadline - now
            if splash_debug or last != last_drawn:
                _draw_button_wait_ui(
                    epd,
                    Image,
                    ImageDraw,
                    w,
                    h,
                    font_title,
                    font_small,
                    bg,
                    fg,
                    accent,
                    last_input=last,
                    debug=splash_debug,
                    remaining_sec=rem if splash_debug else None,
                )
                last_drawn = last

            time.sleep(0.05)
    finally:
        for b in buttons:
            try:
                b.close()
            except Exception:
                pass


def main():
    _init_lgpio_at_startup()

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

        # 1) Boot log (journal — no duplicate "Starting Ragnar" slides; ragnar-display.service is not used)
        log_lines = _get_boot_log_lines(max_lines=12)
        img = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(img)
        draw.text((4, 2), "Boot log (journal):", font=font_small, fill=FG)
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

        # 2) IP / network / SSH
        _draw_network_screen(epd, Image, ImageDraw, W, H, font_big, font_small, BG, FG, ACCENT)
        time.sleep(5.0)

        # 3) Button test — press B (Select) to continue
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
