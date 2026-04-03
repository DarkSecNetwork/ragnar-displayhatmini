#!/usr/bin/env python3
"""Generate 32×32 PNG icons for Display HAT Mini (Ragnar).

White paper, black ink — matches dhm_menu_icons.load_menu_icon() thresholding.

  python3 Ragnar/assets/generate_icons.py

On the Pi, paths resolve next to this file; optional env RAGNAR_ICONS_DIR
overrides the output directory (same as dhm_menu_icons).
"""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 32
LW = 3


def _icons_dir() -> Path:
    env = os.environ.get("RAGNAR_ICONS_DIR", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / "icons"


def new_paper() -> Image.Image:
    """1-bit canvas: 1 = white (paper)."""
    return Image.new("1", (SIZE, SIZE), 1)


def save(img: Image.Image, name: str, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    img.save(out / f"{name}.png")


def wifi(d: ImageDraw.ImageDraw) -> None:
    d.arc([4, 10, 28, 30], 0, 180, fill=0, width=LW)
    d.arc([8, 14, 24, 28], 0, 180, fill=0, width=LW)
    d.arc([12, 18, 20, 26], 0, 180, fill=0, width=LW)
    d.ellipse([14, 24, 18, 28], fill=0)


def hotspot(d: ImageDraw.ImageDraw) -> None:
    d.line([16, 6, 16, 20], fill=0, width=LW)
    # Lower arcs opening downward (Display HAT–friendly broadcast metaphor)
    d.arc([6, 12, 26, 32], 200, 340, fill=0, width=LW)
    d.arc([10, 16, 22, 28], 200, 340, fill=0, width=LW)


def settings(d: ImageDraw.ImageDraw) -> None:
    d.ellipse([8, 8, 24, 24], outline=0, width=LW)
    d.ellipse([13, 13, 19, 19], fill=0)


def reboot(d: ImageDraw.ImageDraw) -> None:
    d.arc([6, 6, 26, 26], 30, 300, fill=0, width=LW)
    d.polygon([(22, 6), (28, 6), (25, 12)], fill=0)


def shutdown(d: ImageDraw.ImageDraw) -> None:
    d.arc([6, 6, 26, 26], 45, 315, fill=0, width=LW)
    d.line([16, 4, 16, 14], fill=0, width=LW)


def network(d: ImageDraw.ImageDraw) -> None:
    for i in range(3):
        bh = 6 + i * 4
        x0 = 6 + i * 8
        d.rectangle([x0, SIZE - 4 - bh, x0 + 4, SIZE - 4], fill=0)
    d.ellipse([SIZE - 13, 5, SIZE - 3, 15], fill=0)


def bluetooth(d: ImageDraw.ImageDraw) -> None:
    m = SIZE // 2
    d.polygon(
        [(m, 4), (m + 8, SIZE // 2 - 2), (m + 8, SIZE // 2 + 2), (m, SIZE - 4), (m - 8, SIZE // 2)],
        fill=0,
    )


def system(d: ImageDraw.ImageDraw) -> None:
    d.rectangle([4, 6, SIZE - 4, SIZE - 4], outline=0, width=LW)
    d.rectangle([8, 10, SIZE - 8, SIZE - 8], fill=0)


def files(d: ImageDraw.ImageDraw) -> None:
    d.rectangle([6, 10, SIZE - 6, SIZE - 6], fill=0)
    d.polygon([(6, 10), (14, 4), (SIZE - 6, 4), (SIZE - 6, 10)], fill=0)


def main() -> None:
    out = _icons_dir()
    specs = [
        ("wifi", wifi),
        ("hotspot", hotspot),
        ("settings", settings),
        ("reboot", reboot),
        ("shutdown", shutdown),
        ("network", network),
        ("bluetooth", bluetooth),
        ("system", system),
        ("files", files),
    ]
    for name, draw_fn in specs:
        img = new_paper()
        d = ImageDraw.Draw(img)
        draw_fn(d)
        save(img, name, out)
    print(f"Wrote {len(specs)} icons to {out}")


if __name__ == "__main__":
    main()
