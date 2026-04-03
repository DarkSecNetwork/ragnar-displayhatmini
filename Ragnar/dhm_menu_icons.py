# dhm_menu_icons.py — Display HAT Mini menu icons: PNG assets or crisp 1-bit fallbacks
#
# Custom PNGs (optional): RAGNAR_ICONS_DIR or /home/ragnar/Ragnar/assets/icons/ or Ragnar/assets/icons/
# Naming: {wifi,hotspot,network,bluetooth,system,settings,reboot,shutdown,files}.png
# Prefer high-contrast B/W; loader uses NEAREST + threshold to mode "1".

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from dhm_strip_metrics import dhm_menu_right_reserved_px
from dhm_strip_metrics import wifi_icon_scale_for_layout as _wifi_icon_scale_for_layout

ICON_SIZE_DEFAULT = 32


def fit_text_to_width(
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont,
    text: str,
    max_width: float,
) -> str:
    """Truncate ``text`` with a trailing ellipsis so rendered width ≤ ``max_width``."""
    if not text or max_width <= 0:
        return text

    def measure(s: str) -> float:
        if hasattr(draw, "textlength"):
            return float(draw.textlength(s, font=font))
        if hasattr(font, "getlength"):
            return float(font.getlength(s))
        bbox = draw.textbbox((0, 0), s, font=font)
        return float(bbox[2] - bbox[0])

    try:
        if measure(text) <= max_width:
            return text
        ell = "…"
        if measure(ell) > max_width:
            return ""
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if measure(text[:mid] + ell) <= max_width:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo] + ell if lo > 0 else ell
    except Exception:
        n = max(0, int(max_width // 7.0))
        return text[:n] if n else text[:1]


def dhm_root_menu_layout(screen_w: int, screen_h: int) -> Tuple[int, int, int]:
    """
    Icon size, row height, and title band height for the DHM root / UIRenderer menu.

    Scales with the shorter panel side so 128×128, 240×320, etc. get proportional glyphs
    instead of a fixed 32×32 in 40px rows. Optional override: ``RAGNAR_MENU_ICON_PX`` (even
    16–40 recommended); row height follows as icon + padding.

    Implementation: :func:`dhm_layout.compute_root_menu_layout_tuple` (single source of truth).
    """
    from dhm_layout import compute_root_menu_layout_tuple

    return compute_root_menu_layout_tuple(screen_w, screen_h)


# Avoid reopening/decoding PNGs every frame when the same icon+size repeats.
_ICON_LOAD_CACHE: dict[tuple[str, int, int], Image.Image] = {}


def clear_menu_icon_cache() -> None:
    _ICON_LOAD_CACHE.clear()


def _candidate_dirs():
    out = []
    env = os.environ.get("RAGNAR_ICONS_DIR", "").strip()
    if env:
        out.append(Path(env))
    out.append(Path("/home/ragnar/Ragnar/assets/icons"))
    here = Path(__file__).resolve().parent
    out.append(here / "assets" / "icons")
    return out


def load_menu_icon(name: str, size: Tuple[int, int] = (ICON_SIZE_DEFAULT, ICON_SIZE_DEFAULT)) -> Image.Image:
    """Return crisp 1-bit PIL Image (ink black = 0, paper white = 1)."""
    w, h = size
    key = (name, w, h)
    if key in _ICON_LOAD_CACHE:
        return _ICON_LOAD_CACHE[key]
    for base in _candidate_dirs():
        path = base / f"{name}.png"
        if path.is_file():
            try:
                im = Image.open(path).convert("L")
                im = im.resize((w, h), Image.NEAREST)
                im = im.point(lambda x: 0 if x < 128 else 255, mode="1")
                _ICON_LOAD_CACHE[key] = im
                return im
            except Exception:
                break
    out = draw_fallback_icon(name, (w, h))
    _ICON_LOAD_CACHE[key] = out
    return out


def invert_icon_1bit(im: Image.Image) -> Image.Image:
    """Swap ink/paper for selection row (white-on-black)."""
    return (
        im.convert("L")
        .point(lambda x: 255 - x)
        .point(lambda x: 0 if x < 128 else 255, mode="1")
    )


def draw_fallback_icon(name: str, size: Tuple[int, int]) -> Image.Image:
    """Bold filled/simple shapes; line width ≥2 px on a 32×32 grid."""
    w, h = size
    im = Image.new("1", (w, h), 1)
    dr = ImageDraw.Draw(im)
    lw = max(2, min(w, h) // 14)

    def circ(cx: float, cy: float, r: float, **kw):
        dr.ellipse([cx - r, cy - r, cx + r, cy + r], **kw)

    if name == "wifi":
        for i in range(4):
            bw = max(3, 2 + i)
            bh = 5 + i * 5
            x0 = 3 + i * 7
            y0 = h - 4 - bh
            dr.rectangle([x0, y0, x0 + bw, h - 4], fill=0)
    elif name == "hotspot":
        dr.rectangle([w // 2 - 2, h // 2 - 2, w // 2 + 2, h - 3], fill=0)
        dr.polygon([(w // 2, 4), (w // 2 - 10, h // 2 - 4), (w // 2 + 10, h // 2 - 4)], fill=0)
    elif name == "network":
        for i in range(3):
            bh = 6 + i * 4
            x0 = 6 + i * 8
            dr.rectangle([x0, h - 4 - bh, x0 + 4, h - 4], fill=0)
        circ(w - 8, 10, 5, fill=0)
    elif name == "bluetooth":
        m = w // 2
        dr.polygon([(m, 4), (m + 8, h // 2 - 2), (m + 8, h // 2 + 2), (m, h - 4), (m - 8, h // 2)], fill=0)
    elif name == "system":
        dr.rectangle([4, 6, w - 4, h - 4], outline=0, width=lw)
        dr.rectangle([8, 10, w - 8, h - 10], fill=0)
    elif name == "settings":
        cx, cy, r = w // 2, h // 2, 7
        circ(cx, cy, r, outline=0, width=lw)
        for i in range(6):
            ang = i * 60
            rad = math.radians(ang)
            x1 = cx + (r + 4) * math.cos(rad)
            y1 = cy + (r + 4) * math.sin(rad)
            circ(x1, y1, 3, fill=0)
    elif name == "reboot":
        dr.arc([5, 5, w - 5, h - 5], 25, 290, fill=0, width=lw)
        dr.polygon([(w - 6, 8), (w - 2, 6), (w - 4, 12)], fill=0)
    elif name == "shutdown":
        circ(w // 2, h // 2 - 2, min(w, h) // 3, outline=0, width=lw)
        dr.rectangle([w // 2 - 2, h // 2 + 4, w // 2 + 2, h - 4], fill=0)
    elif name == "files":
        dr.rectangle([6, 10, w - 6, h - 6], fill=0)
        dr.polygon([(6, 10), (14, 4), (w - 6, 4), (w - 6, 10)], fill=0)
    else:
        dr.rectangle([4, 4, w - 4, h - 4], outline=0, width=lw)
    return im
