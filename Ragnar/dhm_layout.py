# dhm_layout.py — Responsive layout for Pimoroni Display HAT Mini (ST7789) and similar SPI LCDs
#
# Design reference: 320×240 landscape (physical panel). Ragnar may use 240×320 logical (portrait)
# after rotation; always pass the **logical** width/height used for PIL drawing (shared_data.width/height).
#
# Common causes of “wrong size” UI on SPI LCDs
# ---------------------------------------------
# 1. **Logical vs physical resolution** — The ST7789 is driven at 320×240; software may rotate the
#    final image. Use the same W×H everywhere you allocate PIL Images (epd_helper / shared_data).
# 2. **Framebuffer / DPI** — Not used for ST7789 on Pi; the Python stack draws to a buffer and
#    pushes RGB via SPI. Ignore X11 DPI for this path.
# 3. **Fixed pixel sizes** — Hardcoding 32px icons looks wrong on 128×128 tests or 240×320 portrait.
#    Scale from a reference (320×240) or use min(w,h) fractions.
# 4. **Font point sizes** — Bitmap fonts scale with integer points; load one size per band (title/row)
#    and cache on a class instance to avoid I/O on Pi Zero 2 W.
# 5. **1-bit PIL** — Coordinates are integers; prefer even icon sizes for clean NEAREST resize.
#
# Performance (Pi Zero 2 W)
# -------------------------
# - One full-frame render per tick at ~30 FPS is enough; avoid per-glyph Image.open of PNG assets
#   every frame (cache in dhm_menu_icons._ICON_LOAD_CACHE).
# - Prefer `Image.NEAREST` for icon downscale; avoid LANCZOS on every row.
# - Status strip: subprocess for Wi‑Fi is already throttled by frame rate; don’t add more polls.

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from dhm_strip_metrics import dhm_menu_right_reserved_px, wifi_icon_scale_for_layout

# Physical panel reference (landscape). Logical size may be 240×320 — scale uses min(w,h) too.
DHM_REFERENCE_W = 320
DHM_REFERENCE_H = 240


def layout_scale_uniform(width: int, height: int) -> float:
    """
    Scale factor vs the 320×240 reference using the **smaller** axis ratio (content fits any aspect).

    Clamped to [0.45, 2.0] so tiny test windows and large emulators stay sane.
    """
    w = max(1, int(width))
    h = max(1, int(height))
    sw = w / float(DHM_REFERENCE_W)
    sh = h / float(DHM_REFERENCE_H)
    s = min(sw, sh)
    return max(0.45, min(2.0, s))


def scale_px(base: float, scale: float, *, min_v: int = 1, max_v: int = 512, even: bool = False) -> int:
    """Round ``base * scale`` to int with optional even alignment (for bitmap icons)."""
    v = int(round(base * scale))
    v = max(min_v, min(max_v, v))
    if even and v % 2:
        v -= 1
    return max(min_v, v)


@dataclass(frozen=True)
class DHMLayout:
    """
    Snapshot of sizes for one (width, height) pair. Use once per frame or when dimensions change.

    Fields are in **pixels** for the logical framebuffer used by Ragnar (PIL ``Image`` size).
    """

    width: int
    height: int
    scale: float
    # Menu list row
    icon_menu_px: int
    row_height: int
    title_band_h: int
    # Typography (integer pt for truetype)
    font_title_px: int
    font_row_px: int
    font_caption_px: int
    # Spacing
    pad_x: int
    pad_y: int
    gap_sm: int
    gap_md: int
    # Status strip (5×5 bitmap tiles); maps to wifi_icon_scale 1 or 2
    status_tile_scale: int
    # Label start after icon column (matches text_x = pad_x + icon + gap)
    label_x_offset: int


def _clamp_menu_icon_for_label_room(
    screen_w: int,
    screen_h: int,
    icon: int,
    row: int,
    title_h: int,
) -> Tuple[int, int, int]:
    """Shrink row icons if needed so labels clear the right-hand status strip."""
    w = max(1, int(screen_w))
    h = max(1, int(screen_h))
    m = min(w, h)
    wifi_sc = wifi_icon_scale_for_layout(w, h)
    reserved = dhm_menu_right_reserved_px(w, wifi_sc)
    min_label = 48
    max_icon = w - 4 - 6 - min_label - reserved
    max_icon = max(16, min(36, max_icon))
    if max_icon % 2:
        max_icon -= 1
    if icon <= max_icon:
        return (icon, row, title_h)
    icon = max_icon
    pad = max(6, min(12, m // 16))
    row = icon + pad
    body = max(1, h - title_h - 2)
    max_row = max(24, int(body / 2.2))
    if row > max_row:
        row = max_row
        icon = max(16, row - pad)
        if icon % 2:
            icon -= 1
        icon = min(icon, max_icon)
    return (icon, row, title_h)


def compute_root_menu_layout_tuple(
    screen_w: int,
    screen_h: int,
    *,
    menu_icon_override: Optional[int] = None,
) -> Tuple[int, int, int]:
    """
    Icon size, row height, and title band height for the DHM root menu.

    Same semantics as the historical ``dhm_menu_icons.dhm_root_menu_layout``: respects
    ``RAGNAR_MENU_ICON_PX``, scales defaults from panel size, then clamps for the status strip.

    ``menu_icon_override``: when set, forces that icon width (16–40, even) for this call and ignores
    ``RAGNAR_MENU_ICON_PX``.
    """
    w = max(1, int(screen_w))
    h = max(1, int(screen_h))
    env = os.environ.get("RAGNAR_MENU_ICON_PX", "").strip()

    def _env_sized_branch(icon_ov: int) -> Tuple[int, int, int]:
        if icon_ov % 2:
            icon_ov -= 1
        title_h = max(18, min(28, h // 7))
        pad = max(6, min(12, min(w, h) // 18))
        row = icon_ov + pad
        max_row = max(26, int((h - title_h - 2) / 2.2))
        if row > max_row:
            row = max_row
            icon_ov = max(16, row - pad)
            if icon_ov % 2:
                icon_ov -= 1
        return _clamp_menu_icon_for_label_room(w, h, icon_ov, row, title_h)

    if menu_icon_override is not None:
        try:
            icon_ov = max(16, min(40, int(menu_icon_override)))
        except (TypeError, ValueError):
            icon_ov = 32
        return _env_sized_branch(icon_ov)

    if env:
        try:
            icon_ov = max(16, min(40, int(env)))
            return _env_sized_branch(icon_ov)
        except ValueError:
            pass

    m = min(w, h)
    title_h = max(18, min(28, int(h * 0.11 + 8)))
    raw = (m * 13) // 100 + 10
    icon = max(18, min(36, raw))
    if icon % 2:
        icon -= 1
    pad = max(6, min(12, m // 16))
    row = icon + pad
    body = max(1, h - title_h - 2)
    max_row = max(26, int(body / 2.2))
    if row > max_row:
        row = max_row
        icon = max(16, row - pad)
        if icon % 2:
            icon -= 1
        icon = max(16, min(36, icon))
    return _clamp_menu_icon_for_label_room(w, h, icon, row, title_h)


def compute_dhm_layout(
    width: int,
    height: int,
    *,
    menu_icon_override: Optional[int] = None,
) -> DHMLayout:
    """
    Build a :class:`DHMLayout` for the given logical resolution.

    Row/icon/title sizes match :func:`compute_root_menu_layout_tuple` (and ``dhm_root_menu_layout``).

    ``menu_icon_override``: explicit menu icon width in pixels (even, 16–40). When set, overrides
    ``RAGNAR_MENU_ICON_PX`` for this call only.
    """
    w = max(1, int(width))
    h = max(1, int(height))
    sc = layout_scale_uniform(w, h)

    icon, row_h, title_band = compute_root_menu_layout_tuple(w, h, menu_icon_override=menu_icon_override)

    font_title = max(13, min(18, scale_px(16, sc, min_v=13, max_v=18)))
    font_row = max(11, min(16, scale_px(15, sc, min_v=11, max_v=16)))
    font_cap = max(9, min(12, scale_px(10, sc, min_v=9, max_v=12)))

    pad_x = max(2, scale_px(4, sc, min_v=2, max_v=8))
    pad_y = max(2, scale_px(2, sc, min_v=2, max_v=6))
    gap_sm = max(4, scale_px(6, sc, min_v=4, max_v=10))
    gap_md = max(6, scale_px(8, sc, min_v=6, max_v=14))

    tile = wifi_icon_scale_for_layout(w, h)

    label_off = pad_x + icon + gap_sm

    return DHMLayout(
        width=w,
        height=h,
        scale=sc,
        icon_menu_px=icon,
        row_height=row_h,
        title_band_h=title_band,
        font_title_px=font_title,
        font_row_px=font_row,
        font_caption_px=font_cap,
        pad_x=pad_x,
        pad_y=pad_y,
        gap_sm=gap_sm,
        gap_md=gap_md,
        status_tile_scale=tile,
        label_x_offset=label_off,
    )


def layout_from_shared_data(shared_data: Any) -> DHMLayout:
    """Convenience: read ``width`` / ``height`` from a :class:`~shared.SharedData` instance."""
    w = int(getattr(shared_data, "width", DHM_REFERENCE_W))
    h = int(getattr(shared_data, "height", DHM_REFERENCE_H))
    return compute_dhm_layout(w, h)


# --- Backward-compatible tuple API for dhm_menu_icons.dhm_root_menu_layout -----------------

def root_menu_tuple_from_layout(lo: DHMLayout) -> Tuple[int, int, int]:
    """(icon_px, row_h, title_h) for existing callers."""
    return (lo.icon_menu_px, lo.row_height, lo.title_band_h)
