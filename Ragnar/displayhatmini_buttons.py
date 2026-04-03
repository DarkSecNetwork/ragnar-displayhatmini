# displayhatmini_buttons.py - Button support for Display HAT Mini (A, B, X, Y)
# Pimoroni Display HAT Mini: A=5, B=6, X=16, Y=24 (GPIO BCM)
# A = Toggle menu, B = Select (short) / Back (long or double-tap), X = Up, Y = Down
#
# RAGNAR_SKIP_DHM_BUTTONS=1 — skip gpiozero buttons (debug / PiSugar GPIO conflicts).
# RAGNAR_DHM_BUTTON_DELAY — seconds to wait before attaching buttons (default 1.0; increase if SPI races remain).
# RAGNAR_GPIOZERO_FACTORY — force pin factory: lgpio | native | rpigpio (Bookworm/Pi 5: use lgpio).

import logging
import os
import threading
import time
import queue

logger = logging.getLogger(__name__)


def _ensure_gpiozero_pin_factory():
    """st7789 uses gpiodevice/gpiod; gpiozero must use lgpio or native on Bookworm, not stale RPi.GPIO defaults."""
    try:
        from gpiozero import Device
    except ImportError:
        return False
    forced = os.environ.get("RAGNAR_GPIOZERO_FACTORY", "").strip().lower()
    candidates = []
    if forced in ("lgpio", "native", "rpigpio"):
        candidates = [forced]
    else:
        candidates = ["lgpio", "native", "rpigpio"]
    for name in candidates:
        try:
            if name == "lgpio":
                from gpiozero.pins.lgpio import LGPIOFactory

                Device.pin_factory = LGPIOFactory()
            elif name == "native":
                from gpiozero.pins.native import NativeFactory

                Device.pin_factory = NativeFactory()
            elif name == "rpigpio":
                from gpiozero.pins.rpigpio import RPiGPIOFactory

                Device.pin_factory = RPiGPIOFactory()
            else:
                continue
            fac = Device.pin_factory
            logger.info(
                "gpiozero pin factory: %s (%s)",
                name,
                fac.__class__.__name__ if fac is not None else "None",
            )
            return True
        except Exception as e:
            logger.debug("gpiozero factory %s: %s", name, e)
    logger.warning(
        "No working gpiozero hardware pin factory (tried %s); menu buttons may not respond. "
        "Install python3-lgpio or set RAGNAR_GPIOZERO_FACTORY=lgpio",
        candidates,
    )
    return False

# GPIO pins for Pimoroni Display HAT Mini (4 tactile buttons)
PIN_A = 5   # Toggle menu
PIN_B = 6   # Select / Back (long or double-tap)
PIN_X = 16  # Up
PIN_Y = 24  # Down

LONG_PRESS_SEC = 0.6
DOUBLE_TAP_SEC = 0.4

EVENT_MENU_TOGGLE = "menu_toggle"
EVENT_UP = "up"
EVENT_DOWN = "down"
EVENT_SELECT = "select"
EVENT_BACK = "back"


class DisplayHATMiniButtonListener:
    """Listens for A,B,X,Y on Display HAT Mini. B long-press or double-tap = Back."""

    def __init__(self, shared_data):
        self.shared_data = shared_data
        self.available = False
        self._buttons = []
        self._event_queue = queue.Queue(maxsize=64)
        self._b_last_press = 0.0
        self._b_press_count = 0
        self._b_holding = False
        self._b_fired_long_back = False
        self._hold_thread = None
        self._stop_hold = threading.Event()

    def start(self):
        skip = os.environ.get("RAGNAR_SKIP_DHM_BUTTONS", "").strip().lower()
        if skip in ("1", "true", "yes", "on"):
            logger.info("Display HAT Mini buttons disabled (RAGNAR_SKIP_DHM_BUTTONS)")
            return
        try:
            delay = float(os.environ.get("RAGNAR_DHM_BUTTON_DELAY", "0.25"))
        except ValueError:
            delay = 1.0
        delay = max(0.0, delay)

        def _run():
            if delay > 0:
                time.sleep(delay)
            self._start_impl()

        threading.Thread(target=_run, daemon=True).start()

    def _start_impl(self):
        try:
            _ensure_gpiozero_pin_factory()
            from gpiozero import Button
            a = Button(PIN_A, pull_up=True, bounce_time=0.15)
            b = Button(PIN_B, pull_up=True, bounce_time=0.15)
            x = Button(PIN_X, pull_up=True, bounce_time=0.15)
            y = Button(PIN_Y, pull_up=True, bounce_time=0.15)
            a.when_pressed = self._on_a
            b.when_pressed = self._on_b_press
            b.when_released = self._on_b_release
            x.when_pressed = self._on_x
            y.when_pressed = self._on_y
            self._buttons = [a, b, x, y]
            self.available = True
            logger.info("Display HAT Mini buttons started (A=%s B=%s X=%s Y=%s)", PIN_A, PIN_B, PIN_X, PIN_Y)
        except ImportError:
            logger.info("gpiozero not available - Display HAT Mini buttons disabled")
        except Exception as e:
            logger.warning("Could not start Display HAT Mini buttons: %s", e)

    def stop(self):
        self._stop_hold.set()
        for btn in self._buttons:
            try:
                btn.close()
            except Exception:
                pass
        self._buttons = []

    def get_event(self):
        """Non-blocking: return next event string or None."""
        try:
            return self._event_queue.get_nowait()
        except queue.Empty:
            return None

    def _put(self, evt):
        try:
            self._event_queue.put_nowait(evt)
        except queue.Full:
            pass

    def _on_a(self):
        self._put(EVENT_MENU_TOGGLE)

    def _on_x(self):
        self._put(EVENT_UP)

    def _on_y(self):
        self._put(EVENT_DOWN)

    def _on_b_press(self):
        self._b_holding = True
        self._b_fired_long_back = False
        self._stop_hold.clear()
        self._hold_thread = threading.Thread(target=self._check_long_b, daemon=True)
        self._hold_thread.start()

    def _check_long_b(self):
        if self._stop_hold.wait(LONG_PRESS_SEC):
            return
        self._b_fired_long_back = True
        self._put(EVENT_BACK)

    def _on_b_release(self):
        self._stop_hold.set()
        time.sleep(0.02)  # Let _check_long_b set _b_fired_long_back if it was long-press
        if self._b_holding and not self._b_fired_long_back:
            now = time.time()
            if self._b_last_press and now - self._b_last_press <= DOUBLE_TAP_SEC and self._b_press_count == 1:
                self._put(EVENT_BACK)
                self._b_last_press = 0
                self._b_press_count = 0
            else:
                self._put(EVENT_SELECT)
                self._b_last_press = now
                self._b_press_count = 1
        self._b_holding = False
