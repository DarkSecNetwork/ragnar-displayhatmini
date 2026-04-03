# dhm_strip_metrics.py — Status strip width for DHM (Wi‑Fi / BT / battery glyphs)
#
# Shared by dhm_layout (label room) and menu / UI renderers. Must match ui_renderer.STATUS_GAP.

from __future__ import annotations

import os
from typing import Optional

_STATUS_STRIP_GAP = 4


def wifi_icon_scale_for_layout(screen_w: int) -> int:
    """Same default as UIRenderer.wifi_icon_scale for strip width reservation."""
    env = os.environ.get("RAGNAR_UI_WIFI_ICON_SCALE", "").strip()
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    return 2 if screen_w <= 200 else 1


def dhm_menu_right_reserved_px(screen_w: int, wifi_icon_scale: Optional[int] = None) -> int:
    """
    Horizontal space to keep clear on the right for the status strip (Wi‑Fi + BT + battery).

    Always reserves three glyph slots so text does not jump when battery appears/disappears.
    """
    sc = wifi_icon_scale if wifi_icon_scale is not None else wifi_icon_scale_for_layout(screen_w)
    w5 = 5 * max(1, sc)
    n = 3
    return 4 + n * w5 + (n - 1) * _STATUS_STRIP_GAP + 8
