# ui_renderer.py — Display HAT Mini oriented menu/home/hotspot frames (PIL 1-bit)
#
# Animations: eased menu scroll, selection icon bounce, screen cross-fade (L-blend),
# hotspot title blink — tuned for Pi Zero 2 W (~30 FPS loop with time.sleep(0.03)).
#
# Use standalone (pass frame to epd_helper.display_partial) or with a duck-typed display
# that exposes .width, .height, and optional .image(img) / .show().
#
# Ragnar DHM (RAGNAR_DHM_UI_MODE=state): root menu includes "Hotspot QR"; SELECT (B short) opens
# the QR screen; BACK (B long / Y) or SELECT returns to menu; idle uses check_hotspot_qr_idle_timeout
# in display.py. Hotspot credentials come from hotspot_config (env + /run/ragnar/hotspot-credentials.env).
#
# Standalone queue loop (conceptual):
#   while True:
#       try:
#           event = event_queue.get_nowait()
#           if event == EVENT_SELECT:
#               renderer.start_screen_transition("hotspot")
#           elif event == EVENT_BACK and renderer.current_screen == "hotspot":
#               renderer.start_screen_transition("menu")
#           elif event == EVENT_UP:
#               renderer.menu_index = (renderer.menu_index - 1) % len(renderer.menu_items)
#           elif event == EVENT_DOWN:
#               renderer.menu_index = (renderer.menu_index + 1) % len(renderer.menu_items)
#       except queue.Empty:
#           pass
#       renderer.animate_bounce()
#       renderer.update_scroll()
#       renderer.draw_current_screen()
#       renderer.check_auto_return(timeout=120)
#       renderer.check_auto_hotspot_suggestion()  # optional; needs RAGNAR_UI_AUTO_HOTSPOT_WHEN_DISCONNECTED=1
#       time.sleep(0.03)
#
# Wi‑Fi strip: get_wifi_status() + footer on menu (RAGNAR_WIFI_IFACE=wlan0).
# Menu header: bitmap Wi‑Fi waves (WIFI_FRAMES) top-right; optional RAGNAR_UI_WIFI_ICON_SCALE.
# Hotspot header: blinking HOTSPOT_ICON (5×5) + label. Fade: use start_screen_transition, not animate_fade_in sleeps.

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

try:
    import qrcode  # type: ignore
except ImportError:  # pragma: no cover
    qrcode = None  # type: ignore

# Scroll: target follows menu_index × row height (easing factor 0.2 matches spec)
SCROLL_EASE = 0.2
ROW_HEIGHT = 40
ICON_SIZE = 32
ICON_PAD_X = 5
TEXT_X = 45
TITLE_H = 22
HOTSPOT_HEADER_H = 20
HOTSPOT_FOOTER_H = 32
# Bottom strip: SSID label only (signal shown as bitmap in header)
MENU_WIFI_FOOTER_H = 16

# 5×5 Wi‑Fi wave glyphs (3 strength tiers); drawn scaled for DHM readability
WIFI_FRAMES = [
    [0b00100, 0b01010, 0b10001, 0b00000, 0b00100],
    [0b00100, 0b01010, 0b10001, 0b11111, 0b00100],
    [0b00100, 0b01010, 0b11111, 0b11111, 0b00100],
]
HOTSPOT_ICON = [0b00100, 0b01110, 0b11111, 0b01110, 0b00100]
BLUETOOTH_ICON = [
    0b00100,
    0b01110,
    0b10101,
    0b01110,
    0b00100,
]
BATTERY_OUTLINE = [
    0b00100,
    0b01110,
    0b10001,
    0b10001,
    0b01110,
]

# Status row spacing (5×5 icons scaled)
STATUS_GAP = 4
# Optional second line on hotspot: STA SSID when RAGNAR_UI_SHOW_STA_ON_HOTSPOT=1
HOTSPOT_STA_LINE_H = 11

# Transition: progress 0→1 per frame step (fade blend or horizontal slide); RAGNAR_UI_TRANSITION=slide|fade
FADE_STEP = 0.06

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def default_icon_dir() -> Path:
    env = os.environ.get("RAGNAR_ICONS_DIR", "").strip()
    if env:
        return Path(env)
    if Path("/home/ragnar/Ragnar/assets/icons").is_dir():
        return Path("/home/ragnar/Ragnar/assets/icons")
    return Path(__file__).resolve().parent / "assets" / "icons"


def _resolve_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _default_menu_items() -> List[Dict[str, str]]:
    try:
        from dhm_ui_state import ROOT_MENU_SPEC

        return [{"label": s["label"], "icon": s["icon"]} for s in ROOT_MENU_SPEC]
    except ImportError:
        return [
            {"label": "WiFi", "icon": "wifi"},
            {"label": "Hotspot", "icon": "hotspot"},
            {"label": "Settings", "icon": "settings"},
            {"label": "Reboot", "icon": "reboot"},
            {"label": "Shutdown", "icon": "shutdown"},
        ]


def _one_bit_to_l(im: Image.Image) -> Image.Image:
    return im.convert("L")


def _l_to_one_bit(im: Image.Image) -> Image.Image:
    return im.point(lambda x: 0 if x < 128 else 255, mode="1")


def _slide_combine_l(old_l: Image.Image, new_l: Image.Image, progress: float) -> Image.Image:
    """Horizontal slide: old exits left, new enters from right (grayscale, same size)."""
    w, h = old_l.size
    off = int(w * min(1.0, max(0.0, progress)))
    out = Image.new("L", (w, h), 255)
    if off < w:
        out.paste(old_l.crop((off, 0, w, h)), (0, 0))
    if off > 0:
        out.paste(new_l.crop((0, 0, off, h)), (w - off, 0))
    return out


def _dbm_to_percent(sig_dbm: int) -> int:
    """Map RSSI dBm (~-100..-30) to 0..100 (same idea as 2*(dbm+100) clamped)."""
    return int(min(max(2 * (sig_dbm + 100), 0), 100))


def _blit_bitmap5(
    draw: ImageDraw.ImageDraw,
    rows: List[int],
    x: int,
    y: int,
    *,
    fill: int,
    scale: int = 1,
) -> None:
    """Plot a 5×5 mono bitmap (MSB = left column)."""
    sc = max(1, scale)
    for row_idx, row in enumerate(rows):
        for col_idx in range(5):
            if (row >> (4 - col_idx)) & 1:
                if sc == 1:
                    draw.point((x + col_idx, y + row_idx), fill=fill)
                else:
                    x0 = x + col_idx * sc
                    y0 = y + row_idx * sc
                    draw.rectangle([x0, y0, x0 + sc - 1, y0 + sc - 1], fill=fill)


class UIRenderer:
    """Build 1-bit PIL frames for small e-paper / DHM; icons cached by name and size."""

    def __init__(
        self,
        width: int,
        height: int,
        *,
        menu_items: Optional[List[Dict[str, str]]] = None,
        icon_dir: Optional[Path] = None,
        font_title_size: int = 16,
        font_row_size: int = 15,
        font_wifi_size: int = 11,
        display: Any = None,
        show_menu_wifi_footer: bool = True,
    ) -> None:
        self.width = width
        self.height = height
        self.display = display
        self.menu_items = menu_items if menu_items is not None else _default_menu_items()
        self.icon_path = icon_dir if icon_dir is not None else default_icon_dir()
        self.show_menu_wifi_footer = show_menu_wifi_footer
        self.wifi_iface = os.environ.get("RAGNAR_WIFI_IFACE", "wlan0").strip() or "wlan0"
        self._auto_hotspot_suggested = False
        # 2× scale ≈ 10×10 px on 128×64 DHM; override with RAGNAR_UI_WIFI_ICON_SCALE
        _ws = os.environ.get("RAGNAR_UI_WIFI_ICON_SCALE", "").strip()
        _min_side = min(width, height)
        try:
            if _ws:
                self.wifi_icon_scale = int(_ws)
            else:
                # Small panels: 2× 5×5 glyphs; full DHM (e.g. 240×320): also 2× so strip matches enlarged UI
                self.wifi_icon_scale = 2 if _min_side <= 200 or _min_side >= 220 else 1
        except ValueError:
            self.wifi_icon_scale = 2 if _min_side <= 200 or _min_side >= 220 else 1
        _hs = os.environ.get("RAGNAR_UI_HOTSPOT_ICON_SCALE", "").strip()
        try:
            self.hotspot_icon_scale = int(_hs) if _hs else self.wifi_icon_scale
        except ValueError:
            self.hotspot_icon_scale = self.wifi_icon_scale
        self.menu_index = 0
        self.scroll_offset = 0.0
        self._icon_cache: Dict[Tuple[str, int, int], Image.Image] = {}
        try:
            from dhm_menu_icons import dhm_root_menu_layout

            mic, mrh, mth = dhm_root_menu_layout(width, height)
        except ImportError:
            mic, mrh, mth = ICON_SIZE, ROW_HEIGHT, TITLE_H
        self.menu_icon_size = mic
        self.menu_row_height = mrh
        self.menu_title_h = mth
        self.menu_text_x = ICON_PAD_X + mic + 6
        title_px = max(font_title_size, min(18, max(13, mth + 2)))
        row_px = max(font_row_size, min(16, max(11, mrh - 6)))
        self.menu_row_font_px = row_px
        self.font_title = _resolve_font(title_px)
        self.font_row = _resolve_font(row_px)
        self.font_wifi = _resolve_font(font_wifi_size)

        # Animation / screen state
        self.icon_bounce_offset = 0.0
        self.bounce_dir = 1
        self.last_update_time = time.time()
        self._bounce_menu_index: int = -1

        self.transition_progress = 1.0
        self.transition_type: str = "fade"
        self.current_screen = "menu"
        self.next_screen: Optional[str] = None
        self._fade_snapshot_l: Optional[Image.Image] = None

        self.home_stats: Dict[str, Any] = {"cpu": 0.0, "mem": 0.0, "temp": 0.0}
        self.hotspot_ssid = "Ragnar"
        self.hotspot_password = "ragnarconnect"
        self._qr_cache_key: Optional[Tuple[Any, ...]] = None
        self._qr_cached_im: Optional[Image.Image] = None
        self._hotspot_start_time: Optional[float] = None
        self._hotspot_layout_top: int = HOTSPOT_HEADER_H

    def clear_icon_cache(self) -> None:
        self._icon_cache.clear()

    def clear_hotspot_qr_cache(self) -> None:
        self._qr_cache_key = None
        self._qr_cached_im = None

    def get_wifi_status(self, iface: Optional[str] = None) -> Dict[str, Any]:
        """Current STA association: SSID, signal 0–100, connected. Safe if Wi‑Fi down or tools missing."""
        iface = iface or self.wifi_iface
        status: Dict[str, Any] = {"ssid": None, "signal": 0, "connected": False}
        ssid: Optional[str] = None
        try:
            ssid = subprocess.check_output(
                ["iwgetid", "-r"],
                text=True,
                timeout=3,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            ssid = None
        if ssid:
            status["ssid"] = ssid
            status["connected"] = True

        sig_pct = 0
        parsed = False
        try:
            r = subprocess.run(
                ["iwconfig", iface],
                capture_output=True,
                text=True,
                timeout=3,
            )
            for line in (r.stdout or "").splitlines():
                if "Signal level" not in line:
                    continue
                if "dBm" in line:
                    m = re.search(r"Signal level=(-?\d+)\s*dBm", line)
                    if m:
                        sig_pct = _dbm_to_percent(int(m.group(1)))
                        parsed = True
                        break
                else:
                    m2 = re.search(r"Signal level=(\d+)\s*/\s*(\d+)", line)
                    if m2:
                        a, b = int(m2.group(1)), int(m2.group(2))
                        sig_pct = int(min(100, max(0, round(100.0 * a / b)))) if b else 0
                        parsed = True
                        break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        if status["connected"] and not parsed:
            try:
                out = subprocess.check_output(
                    ["iw", "dev", iface, "link"],
                    text=True,
                    timeout=3,
                    stderr=subprocess.DEVNULL,
                )
                for line in out.splitlines():
                    line = line.strip()
                    if line.startswith("signal:") and "dBm" in line:
                        m = re.search(r"signal:\s*(-?\d+(?:\.\d+)?)\s*dBm", line)
                        if m:
                            sig_pct = _dbm_to_percent(int(float(m.group(1))))
                        break
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                pass

        status["signal"] = sig_pct
        return status

    def bluetooth_active(self) -> bool:
        """True if Bluetooth should show as active (env or hciconfig UP)."""
        if os.environ.get("RAGNAR_BT_ACTIVE", "").strip() == "1":
            return True
        try:
            out = subprocess.check_output(["hciconfig"], text=True, timeout=2, stderr=subprocess.DEVNULL)
            u = out.upper()
            return "UP" in u or "RUNNING" in u
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def get_battery_percent(self) -> Optional[int]:
        """0–100 from RAGNAR_BATTERY_PERCENT or first ``.../capacity`` under sysfs; None if unknown."""
        v = os.environ.get("RAGNAR_BATTERY_PERCENT", "").strip()
        if v:
            try:
                return int(min(100, max(0, int(v))))
            except ValueError:
                pass
        try:
            root = Path("/sys/class/power_supply")
            if root.is_dir():
                for cap in sorted(root.glob("*/capacity")):
                    try:
                        raw = (cap.read_text(encoding="utf-8") or "").strip()
                        if raw.isdigit():
                            return int(min(100, max(0, int(raw))))
                    except OSError:
                        continue
        except OSError:
            pass
        return None

    def draw_bluetooth_icon(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        *,
        active: bool = False,
        fill: int = 0,
        scale: Optional[int] = None,
    ) -> None:
        """Static when inactive; blinks when ``active`` (connected / powered)."""
        if active and int(time.time() * 2) % 2 != 0:
            return
        sc = scale if scale is not None else self.wifi_icon_scale
        _blit_bitmap5(draw, BLUETOOTH_ICON, x, y, fill=fill, scale=sc)

    def draw_battery_icon(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        *,
        level: Optional[int] = None,
        fill: int = 0,
        scale: Optional[int] = None,
    ) -> None:
        """Outline + bottom-up fill by level; skipped if ``level`` is None."""
        pct = self.get_battery_percent() if level is None else level
        if pct is None:
            return
        sc = scale if scale is not None else self.wifi_icon_scale
        _blit_bitmap5(draw, BATTERY_OUTLINE, x, y, fill=fill, scale=sc)
        # Inner column fill (approximate 3 rows inside body)
        filled_rows = min(3, max(0, int(pct / 34)))
        for r in range(filled_rows):
            ry = y + (4 - r) * sc
            if sc == 1:
                draw.point((x + 2, ry), fill=fill)
            else:
                draw.rectangle(
                    [x + 2 * sc, ry, x + 3 * sc - 1, ry + sc - 1],
                    fill=fill,
                )

    def check_auto_hotspot_suggestion(self) -> None:
        """If RAGNAR_UI_AUTO_HOTSPOT_WHEN_DISCONNECTED=1 and STA is down, cross-fade to hotspot once until reconnect."""
        if (
            os.environ.get("RAGNAR_UI_AUTO_HOTSPOT_WHEN_DISCONNECTED", "").strip().lower()
            not in ("1", "true", "yes", "on")
        ):
            return
        if self.current_screen != "menu" or self.next_screen is not None:
            return
        st = self.get_wifi_status()
        if st["connected"]:
            self._auto_hotspot_suggested = False
            return
        if self._auto_hotspot_suggested:
            return
        self._auto_hotspot_suggested = True
        self.start_screen_transition("hotspot")

    def draw_wifi_icon(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        signal: int,
        *,
        connected: bool = True,
        fill: int = 0,
        scale: Optional[int] = None,
    ) -> None:
        """5×5 wave bitmap; strength 0–100 maps to frames; subtle tier pulse when connected."""
        sc = scale if scale is not None else self.wifi_icon_scale
        if not connected:
            frame_idx = 0
        else:
            base = min(2, int(signal / 34))
            frame_idx = base if int(time.time() * 2) % 2 == 0 else min(2, base + 1)
        _blit_bitmap5(draw, WIFI_FRAMES[frame_idx], x, y, fill=fill, scale=sc)

    def draw_hotspot_icon(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        *,
        fill: int = 255,
        scale: Optional[int] = None,
    ) -> None:
        """5×5 blinking broadcast glyph (caller gates with time phase if desired)."""
        sc = scale if scale is not None else self.hotspot_icon_scale
        _blit_bitmap5(draw, HOTSPOT_ICON, x, y, fill=fill, scale=sc)

    def animate_fade_in(self, img: Image.Image, step: float = 0.05) -> None:
        """No-op: 1-bit panels have no alpha. Use :meth:`start_screen_transition` + :meth:`draw_current_screen` instead.

        Blocking sleep loops here would stall the Pi Zero; cross-fade is implemented via L-blend in ``draw_current_screen``.
        """
        del img, step

    def menu_status_reserved_right(self) -> int:
        """Pixels to leave clear on the right edge (matches :meth:`_draw_status_icons_menu`)."""
        try:
            from dhm_menu_icons import dhm_menu_right_reserved_px

            return dhm_menu_right_reserved_px(self.width, self.wifi_icon_scale)
        except ImportError:
            return 52

    def _draw_status_icons_menu(self, draw: ImageDraw.ImageDraw) -> None:
        """Wi‑Fi + BT + optional battery, top-right on white menu (black ink)."""
        sc = self.wifi_icon_scale
        w5 = 5 * sc
        gap = STATUS_GAP
        x = self.width - w5 - 4
        wifi = self.get_wifi_status()
        self.draw_wifi_icon(
            draw,
            x,
            2,
            int(wifi["signal"]),
            connected=bool(wifi["connected"]),
            fill=0,
        )
        x -= gap + w5
        self.draw_bluetooth_icon(draw, x, 2, active=self.bluetooth_active(), fill=0)
        x -= gap + w5
        if self.get_battery_percent() is not None:
            self.draw_battery_icon(draw, x, 2, level=None, fill=0)

    def _draw_status_icons_hotspot(self, draw: ImageDraw.ImageDraw) -> None:
        """Same indicators on hotspot screen (white ink). Two rows if panel is narrow."""
        sc = self.wifi_icon_scale
        w5 = 5 * sc
        gap = STATUS_GAP
        y1, y2 = 2, 2 + w5 + gap
        x = self.width - w5 - 4
        wifi = self.get_wifi_status()
        self.draw_wifi_icon(
            draw,
            x,
            y1,
            int(wifi["signal"]),
            connected=bool(wifi["connected"]),
            fill=255,
        )
        x = self.width - w5 - 4
        self.draw_bluetooth_icon(draw, x, y2, active=self.bluetooth_active(), fill=255)
        x -= gap + w5
        if self.get_battery_percent() is not None:
            self.draw_battery_icon(draw, x, y2, level=None, fill=255)

    def _draw_menu_wifi_footer(self, draw: ImageDraw.ImageDraw) -> None:
        """SSID-only line (signal strength is the bitmap in the header)."""
        fy = self.height - MENU_WIFI_FOOTER_H
        draw.rectangle((0, fy, self.width - 1, self.height - 1), fill=255)
        draw.rectangle((0, fy, self.width - 1, fy + 1), fill=0)
        wifi = self.get_wifi_status()
        if wifi["connected"] and wifi["ssid"]:
            line = f"WiFi: {wifi['ssid'][:28]}  {wifi['signal']}%"
        else:
            line = "WiFi: —"
        draw.text((2, fy + 2), line[:52], font=self.font_wifi, fill=0)

    def _resolve_hotspot_credentials(
        self,
        ssid: Optional[str],
        password: Optional[str],
    ) -> Tuple[str, str]:
        """Prefer explicit args; else hotspot_config (env + /run/ragnar/hotspot-credentials.env)."""
        if ssid is not None and password is not None:
            return ssid, password
        try:
            from hotspot_config import get_hotspot_credentials

            live_s, live_p = get_hotspot_credentials()
        except ImportError:
            live_s, live_p = self.hotspot_ssid, self.hotspot_password
        return (ssid if ssid is not None else live_s, password if password is not None else live_p)

    def generate_hotspot_qr(
        self,
        ssid: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Image.Image:
        """WPA QR for Wi‑Fi settings; reads live credentials when args omitted. Cached per SSID/PASS/size."""
        ssid, password = self._resolve_hotspot_credentials(ssid, password)
        try:
            from hotspot_config import escape_wifi_qr_value
        except ImportError:

            def escape_wifi_qr_value(x: str) -> str:  # type: ignore[misc]
                return (
                    x.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace(":", "\\:")
                )

        cache_key = (ssid, password, self.width, self.height)
        if cache_key == self._qr_cache_key and self._qr_cached_im is not None:
            return self._qr_cached_im

        if qrcode is None:
            side = max(24, min(self.width, self.height) // 5)
            im = Image.new("1", (side, side), 255)
            ImageDraw.Draw(im).rectangle([2, 2, side - 2, side - 2], outline=0, width=2)
            self._qr_cache_key = cache_key
            self._qr_cached_im = im
            return im

        esc_s = escape_wifi_qr_value(ssid)
        esc_p = escape_wifi_qr_value(password)
        qr_data = f"WIFI:T:WPA;S:{esc_s};P:{esc_p};;"
        qr = qrcode.QRCode(
            border=0,
            box_size=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        # Dark modules on white — phones expect high contrast
        img_qr = qr.make_image(fill_color="black", back_color="white").convert("1")

        top = getattr(self, "_hotspot_layout_top", HOTSPOT_HEADER_H)
        avail_h = max(1, self.height - top - HOTSPOT_FOOTER_H - 2)
        avail_w = max(1, self.width - 4)
        max_size = max(1, min(avail_h, avail_w, min(self.width, self.height) - 20))
        img_qr = img_qr.resize((max_size, max_size), Image.NEAREST)

        self._qr_cache_key = cache_key
        self._qr_cached_im = img_qr
        return img_qr

    def check_auto_return(self, timeout: float = 120.0) -> None:
        """After idle on hotspot, cross‑fade back to menu. Call once per frame from your main loop."""
        if self.next_screen is not None:
            return
        if self.current_screen != "hotspot":
            self._hotspot_start_time = None
            return
        if self._hotspot_start_time is None:
            self._hotspot_start_time = time.time()
            return
        if time.time() - self._hotspot_start_time >= timeout:
            self._hotspot_start_time = None
            self.start_screen_transition("menu")

    def load_icon(self, name: str, size: Optional[Tuple[int, int]] = None) -> Image.Image:
        if size is None:
            size = (self.menu_icon_size, self.menu_icon_size)
        key = (name, size[0], size[1])
        if key in self._icon_cache:
            return self._icon_cache[key]
        path = self.icon_path / f"{name}.png"
        if path.is_file():
            img = Image.open(path).convert("L")
            img = img.resize(size, Image.NEAREST)
            img = img.point(lambda x: 0 if x < 128 else 255, mode="1")
        else:
            try:
                from dhm_menu_icons import draw_fallback_icon

                img = draw_fallback_icon(name, size)
            except ImportError:
                img = Image.new("1", size, 1)
                ImageDraw.Draw(img).rectangle([2, 2, size[0] - 2, size[1] - 2], outline=0, width=2)
        self._icon_cache[key] = img
        return img

    def animate_bounce(self) -> None:
        """Subtle vertical bounce (0–2 px) on the selected row icon; cheap on CPU."""
        if self.menu_index != self._bounce_menu_index:
            self.icon_bounce_offset = 0.0
            self.bounce_dir = 1
            self._bounce_menu_index = self.menu_index

        now = time.time()
        dt = now - self.last_update_time
        self.last_update_time = now

        self.icon_bounce_offset += self.bounce_dir * dt * 20.0
        if self.icon_bounce_offset > 2.0:
            self.icon_bounce_offset = 2.0
            self.bounce_dir = -1.0
        elif self.icon_bounce_offset < 0.0:
            self.icon_bounce_offset = 0.0
            self.bounce_dir = 1.0

    def update_scroll(self) -> None:
        """Ease scroll_offset toward menu_index × row height (slide animation)."""
        n = max(1, len(self.menu_items))
        target = float(max(0, min(self.menu_index, n - 1)) * self.menu_row_height)
        diff = target - self.scroll_offset
        self.scroll_offset += diff * SCROLL_EASE
        if abs(diff) < 0.45:
            self.scroll_offset = target

    def start_screen_transition(
        self,
        screen_name: str,
        *,
        home_stats: Optional[Dict[str, Any]] = None,
        transition: Optional[str] = None,
    ) -> None:
        """Begin transition to menu | home | hotspot. Use ``transition='slide'`` or ``RAGNAR_UI_TRANSITION=slide`` for horizontal slide; else L-blend fade."""
        if home_stats is not None:
            self.home_stats = dict(home_stats)
        self._fade_snapshot_l = self._snapshot_current_as_l()
        self.next_screen = screen_name
        self.transition_progress = 0.0
        tt = (transition or os.environ.get("RAGNAR_UI_TRANSITION", "fade") or "fade").strip().lower()
        self.transition_type = "slide" if tt == "slide" else "fade"
        if screen_name == "hotspot":
            self._hotspot_start_time = time.time()
        elif screen_name == "menu":
            self._hotspot_start_time = None

    def _snapshot_current_as_l(self) -> Image.Image:
        if self.current_screen == "menu":
            return _one_bit_to_l(self._render_menu_content(apply_bounce=False))
        if self.current_screen == "home":
            return _one_bit_to_l(self._render_home_content(self.home_stats))
        if self.current_screen == "hotspot":
            return _one_bit_to_l(self._render_hotspot_content())
        return Image.new("L", (self.width, self.height), 255)

    def _render_screen_by_name(self, name: str) -> Image.Image:
        if name == "menu":
            return self._render_menu_content(apply_bounce=True)
        if name == "home":
            return self._render_home_content(self.home_stats)
        if name == "hotspot":
            return self._render_hotspot_content()
        return Image.new("1", (self.width, self.height), 255)

    def _advance_transition(self) -> None:
        if self.next_screen is None:
            return
        self.transition_progress = min(1.0, self.transition_progress + FADE_STEP)
        if self.transition_progress >= 1.0:
            self.transition_progress = 1.0
            self.current_screen = self.next_screen  # type: ignore[assignment]
            self.next_screen = None
            self._fade_snapshot_l = None

    def update_transition(self) -> None:
        """No-op placeholder: transition progress advances inside :meth:`draw_current_screen` each frame."""
        pass

    def draw_current_screen(
        self,
        home_stats: Optional[Dict[str, Any]] = None,
        push: Optional[Callable[[Image.Image], None]] = None,
    ) -> Image.Image:
        """Compose one frame: fade (L-blend) or slide between snapshot and target; completes ``transition_progress``."""
        if home_stats is not None:
            self.home_stats = dict(home_stats)

        if self.next_screen is not None and self._fade_snapshot_l is not None:
            target = self._render_screen_by_name(self.next_screen)
            target_l = _one_bit_to_l(target)
            p = self.transition_progress
            if self.transition_type == "slide":
                blended = _slide_combine_l(self._fade_snapshot_l, target_l, p)
            else:
                blended = Image.blend(self._fade_snapshot_l, target_l, p)
            out = _l_to_one_bit(blended)
            self._advance_transition()
        else:
            out = self._render_screen_by_name(self.current_screen)

        if push is not None:
            push(out)
        elif self.display is not None:
            if hasattr(self.display, "image"):
                self.display.image(out)
            if hasattr(self.display, "show"):
                self.display.show()
        return out

    def _render_menu_content(self, *, apply_bounce: bool) -> Image.Image:
        """Full menu bitmap; optional bounce on selected icon only."""
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, self.width - 1, self.height - 1), fill=255)
        reserved = self.menu_status_reserved_right()
        try:
            from dhm_menu_icons import fit_text_to_width

            title_txt = fit_text_to_width(
                draw,
                self.font_title,
                "Menu",
                float(max(24, self.width - 4 - reserved - 2)),
            )
        except ImportError:
            title_txt = "Menu"
        draw.text((4, 2), title_txt, fill=0, font=self.font_title)
        self._draw_status_icons_menu(draw)

        off = int(self.scroll_offset)
        base_y = 2 + self.menu_title_h
        idx = max(0, min(self.menu_index, len(self.menu_items) - 1))
        menu_bottom = self.height - (MENU_WIFI_FOOTER_H if self.show_menu_wifi_footer else 0)
        rh = self.menu_row_height
        ic_sz = self.menu_icon_size
        label_max_w = float(max(20, self.width - reserved - self.menu_text_x - 2))

        for i, item in enumerate(self.menu_items):
            y = base_y + i * rh - off
            if y < -rh or y > menu_bottom - 2:
                continue
            selected = i == idx
            row_top = max(0, y)
            row_bot = min(menu_bottom - 1, y + rh - 1)
            label = item["label"]
            try:
                from dhm_menu_icons import fit_text_to_width

                label = fit_text_to_width(draw, self.font_row, label, label_max_w)
            except ImportError:
                label = label[:42]
            if selected:
                draw.rectangle((0, row_top, self.width - 1, row_bot), fill=0)

            icn = self.load_icon(item["icon"], (ic_sz, ic_sz))
            if selected:
                try:
                    from dhm_menu_icons import invert_icon_1bit

                    icn = invert_icon_1bit(icn)
                except ImportError:
                    icn = icn.convert("L").point(lambda x: 255 - x).point(
                        lambda x: 0 if x < 128 else 255, mode="1"
                    )
            iy = row_top + (rh - ic_sz) // 2
            if selected and apply_bounce:
                iy += int(self.icon_bounce_offset)
            iy = max(row_top, min(iy, row_bot - ic_sz))
            img.paste(icn, (ICON_PAD_X, iy))

            _rp = getattr(self, "menu_row_font_px", 15)
            ty = row_top + max(0, (rh - _rp) // 2)
            fill = 255 if selected else 0
            draw.text((self.menu_text_x, ty), label, font=self.font_row, fill=fill)

        if self.show_menu_wifi_footer:
            self._draw_menu_wifi_footer(draw)

        return img

    def _render_home_content(self, stats: Dict[str, Any]) -> Image.Image:
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        cpu = float(stats.get("cpu", 0))
        mem = float(stats.get("mem", 0))
        temp = float(stats.get("temp", 0))
        draw.text((2, 2), f"CPU: {cpu:.0f}%", font=self.font_row, fill=0)
        draw.text((2, 22), f"MEM: {mem:.0f}%", font=self.font_row, fill=0)
        draw.text((2, 42), f"TEMP: {temp:.0f}C", font=self.font_row, fill=0)
        return img

    def _render_hotspot_content(
        self,
        ssid: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Image.Image:
        """Black screen, status icons, blinking AP glyph, QR, optional STA line, AP SSID/PASS footer."""
        ssid, password = self._resolve_hotspot_credentials(ssid, password)
        self.hotspot_ssid = ssid
        self.hotspot_password = password
        img = Image.new("1", (self.width, self.height), 0)
        draw = ImageDraw.Draw(img)
        blink_on = (int(time.time() * 2.0) % 2) == 0
        _hs = 5 * self.hotspot_icon_scale
        _w5 = 5 * self.wifi_icon_scale
        hotspot_top_h = max(HOTSPOT_HEADER_H, 2 * _w5 + STATUS_GAP + 4)
        show_sta = os.environ.get("RAGNAR_UI_SHOW_STA_ON_HOTSPOT", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        sta_h = HOTSPOT_STA_LINE_H if show_sta else 0
        self._hotspot_layout_top = hotspot_top_h + sta_h

        draw.rectangle((0, 0, self.width - 1, hotspot_top_h), fill=0)
        if blink_on:
            self.draw_hotspot_icon(draw, 2, 2, fill=255)
        title = "Hotspot" if self.width < 200 else "HOTSPOT ACTIVE"
        draw.text((4 + _hs, 2), title, font=self.font_row, fill=255)
        self._draw_status_icons_hotspot(draw)

        if show_sta:
            wst = self.get_wifi_status()
            if wst["connected"] and wst.get("ssid"):
                draw.text(
                    (2, hotspot_top_h + 1),
                    f"STA {wst['ssid'][:22]} {wst['signal']}%",
                    font=self.font_wifi,
                    fill=255,
                )

        qr_img = self.generate_hotspot_qr(ssid, password)
        qr_x = max(0, (self.width - qr_img.width) // 2)
        body_top = self._hotspot_layout_top
        body_h = max(1, self.height - self._hotspot_layout_top - HOTSPOT_FOOTER_H)
        qr_y = body_top + max(0, (body_h - qr_img.height) // 2)
        qr_y = min(qr_y, self.height - HOTSPOT_FOOTER_H - qr_img.height)
        img.paste(qr_img, (qr_x, qr_y))

        draw.text((2, self.height - 30), f"SSID: {ssid[:36]}", font=self.font_row, fill=255)
        draw.text((2, self.height - 14), f"PASS: {password[:36]}", font=self.font_row, fill=255)
        return img

    def render_menu_image(self) -> Image.Image:
        """Single menu frame (respects bounce offset if animate_bounce() runs in your loop)."""
        return self._render_menu_content(apply_bounce=True)

    def draw_menu(self, push: Optional[Callable[[Image.Image], None]] = None) -> Image.Image:
        frame = self.render_menu_image()
        if push is not None:
            push(frame)
        elif self.display is not None:
            if hasattr(self.display, "image"):
                self.display.image(frame)
            if hasattr(self.display, "show"):
                self.display.show()
        return frame

    def render_home_image(self, stats: Dict[str, Any]) -> Image.Image:
        self.home_stats = dict(stats)
        return self._render_home_content(self.home_stats)

    def draw_home(self, stats: Dict[str, Any], push: Optional[Callable[[Image.Image], None]] = None) -> Image.Image:
        frame = self.render_home_image(stats)
        if push is not None:
            push(frame)
        elif self.display is not None:
            if hasattr(self.display, "image"):
                self.display.image(frame)
            if hasattr(self.display, "show"):
                self.display.show()
        return frame

    def render_hotspot_image(
        self,
        ssid: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Image.Image:
        """Omit ssid/password to use live credentials (env + credentials file)."""
        rs, rp = self._resolve_hotspot_credentials(ssid, password)
        if rs != self.hotspot_ssid or rp != self.hotspot_password:
            self.clear_hotspot_qr_cache()
        return self._render_hotspot_content(ssid, password)

    def draw_hotspot(
        self,
        ssid: Optional[str] = None,
        password: Optional[str] = None,
        push: Optional[Callable[[Image.Image], None]] = None,
    ) -> Image.Image:
        frame = self.render_hotspot_image(ssid=ssid, password=password)
        if push is not None:
            push(frame)
        elif self.display is not None:
            if hasattr(self.display, "image"):
                self.display.image(frame)
            if hasattr(self.display, "show"):
                self.display.show()
        return frame
