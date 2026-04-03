# Display HAT Mini — responsive layout (scaling)

This note complements [DISPLAY_HAT_MINI.md](DISPLAY_HAT_MINI.md) (orientation and driver setup).

## Why UI can look wrong on SPI LCDs

1. **Logical vs physical size** — The ST7789 is driven at 320×240; Ragnar may use **240×320** after rotation. Every PIL buffer and `draw` call must use the same **width/height** as `shared_data` (logical framebuffer), not the physical panel dimensions only.
2. **Framebuffer / X11 DPI** — Not used for this path: Python draws into an image buffer and pushes pixels over SPI. Ignore desktop DPI.
3. **Fixed pixel constants** — Icons and fonts tied to “32px” or “16pt” break on small panels or test resolutions. Prefer scaling from a reference (320×240) or from `min(width, height)`.
4. **Bitmap fonts** — Use integer **point** sizes; cache `ImageFont.truetype` instances per size (see `DHMLayout` in `dhm_layout.py`) to avoid I/O every frame on Pi Zero 2 W.
5. **1-bit / NEAREST icons** — Use even icon sizes when resizing with `Image.NEAREST` for crisp halftone.

## Source of truth for resolution

Use **`shared_data.width` / `shared_data.height`** (or your `SharedData` equivalent) everywhere you layout or allocate images. For a full snapshot of scaled paddings, fonts, and menu geometry:

```python
from dhm_layout import layout_from_shared_data, compute_dhm_layout

lo = layout_from_shared_data(shared_data)
# lo.icon_menu_px, lo.row_height, lo.font_row_px, lo.label_x_offset, ...
```

Menu row geometry (icon, row height, title band) is centralized in **`compute_root_menu_layout_tuple`**; **`dhm_root_menu_layout`** in `dhm_menu_icons.py` delegates to it so there is a single code path.

## Environment variables

| Variable | Effect |
|----------|--------|
| `RAGNAR_MENU_ICON_PX` | Even value 16–40: fixed menu icon width (env-driven branch). |
| `RAGNAR_UI_WIFI_ICON_SCALE` | Wi‑Fi glyph scale (1+); affects reserved right margin (`dhm_strip_metrics.py`). |

## Status strip and label room

The right side reserves space for Wi‑Fi / Bluetooth / battery glyphs. **`dhm_menu_right_reserved_px`** (in `dhm_strip_metrics.py`) must stay in sync with `ui_renderer` status spacing. **`_clamp_menu_icon_for_label_room`** in `dhm_layout.py` shrinks icons if labels would collide with that strip.

## Performance (low-memory devices)

- One **full-frame** draw per update is typical; avoid redrawing unchanged regions unless you measure a win.
- **Cache** decoded PNG menu icons (`dhm_menu_icons` / `_ICON_LOAD_CACHE`).
- Prefer **`Image.NEAREST`** for icon resize; avoid `LANCZOS` on hot paths.
- **Load fonts once** per point size (e.g. store on `UIRenderer` or reuse `DHMLayout` sizes).

## Helper summary

| Module | Role |
|--------|------|
| `dhm_layout.py` | `layout_scale_uniform`, `scale_px`, `DHMLayout`, `compute_root_menu_layout_tuple`, `compute_dhm_layout` |
| `dhm_strip_metrics.py` | `wifi_icon_scale_for_layout`, `dhm_menu_right_reserved_px` |
| `dhm_menu_icons.py` | `dhm_root_menu_layout`, `load_menu_icon`, `fit_text_to_width` |
