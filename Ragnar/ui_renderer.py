# ui_renderer.py — Display HAT Mini oriented menu/home/hotspot frames (PIL 1-bit)
#
# Use standalone (pass frame to epd_helper.display_partial) or with a duck-typed display
# that exposes .width, .height, and optional .image(img) / .show().

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

SCROLL_LERP = 0.22
ROW_HEIGHT = 40
ICON_SIZE = 32
ICON_PAD_X = 5
TEXT_X = 45
TITLE_H = 22

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
        display: Any = None,
    ) -> None:
        self.width = width
        self.height = height
        self.display = display
        self.menu_items = menu_items if menu_items is not None else _default_menu_items()
        self.icon_path = icon_dir if icon_dir is not None else default_icon_dir()
        self.font_title = _resolve_font(font_title_size)
        self.font_row = _resolve_font(font_row_size)
        self.menu_index = 0
        self.scroll_offset = 0.0
        self.scroll_target = 0.0
        self._icon_cache: Dict[Tuple[str, int, int], Image.Image] = {}

    def clear_icon_cache(self) -> None:
        self._icon_cache.clear()

    def load_icon(self, name: str, size: Tuple[int, int] = (ICON_SIZE, ICON_SIZE)) -> Image.Image:
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

    def update_scroll(self) -> None:
        n = max(1, len(self.menu_items))
        self.scroll_target = float(max(0, min(self.menu_index, n - 1)) * ROW_HEIGHT)
        self.scroll_offset += (self.scroll_target - self.scroll_offset) * SCROLL_LERP
        if abs(self.scroll_target - self.scroll_offset) < 0.45:
            self.scroll_offset = self.scroll_target

    def render_menu_image(self) -> Image.Image:
        """Single menu frame: white background, black text; inverted bar for selection."""
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, self.width - 1, self.height - 1), fill=255)
        draw.text((4, 2), "Menu", fill=0, font=self.font_title)

        off = int(self.scroll_offset)
        base_y = 2 + TITLE_H
        idx = max(0, min(self.menu_index, len(self.menu_items) - 1))

        for i, item in enumerate(self.menu_items):
            y = base_y + i * ROW_HEIGHT - off
            if y < -ROW_HEIGHT or y > self.height - 2:
                continue
            selected = i == idx
            row_top = max(0, y)
            row_bot = min(self.height - 1, y + ROW_HEIGHT - 1)
            label = item["label"]
            if selected:
                draw.rectangle((0, row_top, self.width - 1, row_bot), fill=0)

            icn = self.load_icon(item["icon"], (ICON_SIZE, ICON_SIZE))
            if selected:
                try:
                    from dhm_menu_icons import invert_icon_1bit

                    icn = invert_icon_1bit(icn)
                except ImportError:
                    icn = icn.convert("L").point(lambda x: 255 - x).point(
                        lambda x: 0 if x < 128 else 255, mode="1"
                    )
            iy = row_top + (ROW_HEIGHT - ICON_SIZE) // 2
            iy = max(row_top, min(iy, row_bot - ICON_SIZE))
            img.paste(icn, (ICON_PAD_X, iy))

            ty = row_top + (ROW_HEIGHT - 15) // 2
            fill = 255 if selected else 0
            draw.text((TEXT_X, ty), label[:42], font=self.font_row, fill=fill)

        return img

    def draw_menu(self, push: Optional[Callable[[Image.Image], None]] = None) -> Image.Image:
        """Render menu and optionally push to display or callback."""
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
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        cpu = stats.get("cpu", 0)
        mem = stats.get("mem", 0)
        temp = stats.get("temp", 0)
        draw.text((2, 2), f"CPU: {cpu:.0f}%", font=self.font_row, fill=0)
        draw.text((2, 22), f"MEM: {mem:.0f}%", font=self.font_row, fill=0)
        draw.text((2, 42), f"TEMP: {temp:.0f}C", font=self.font_row, fill=0)
        return img

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
        ssid: str = "Ragnar-Setup",
        password: str = "ragnarconnect",
    ) -> Image.Image:
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        draw.text((2, 2), "HOTSPOT ACTIVE", font=self.font_row, fill=0)
        draw.text((2, 22), f"SSID: {ssid[:32]}", font=self.font_row, fill=0)
        draw.text((2, 42), f"PASS: {password[:32]}", font=self.font_row, fill=0)
        return img

    def draw_hotspot(
        self,
        ssid: str = "Ragnar-Setup",
        password: str = "ragnarconnect",
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
