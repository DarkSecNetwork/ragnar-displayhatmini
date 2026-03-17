#!/usr/bin/env python3
"""Display HAT Mini boot splash: show Booting / Starting Ragnar / boot log / Loading."""
import os
import subprocess
import sys
import time


def _get_boot_log_lines(max_lines=10, line_chars=48):
    """Return last N lines of current-boot journal, each line wrapped to line_chars."""
    try:
        out = subprocess.check_output(
            ["journalctl", "-b", "-n", str(max_lines * 2), "--no-pager", "-o", "short-iso"],
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
        # Strip leading timestamp for brevity: "2025-03-15T12:34:56+00:00 hostname msg" -> "msg" or keep last part
        if len(raw) > line_chars:
            # Wrap long lines
            while raw:
                lines.append(raw[:line_chars])
                raw = raw[line_chars:].lstrip()
        else:
            lines.append(raw)
        if len(lines) >= max_lines:
            break
    return lines[-max_lines:] if len(lines) > max_lines else lines


def main():
    try:
        from PIL import Image, ImageDraw
        from waveshare_epd import displayhatmini
    except ImportError:
        return 0
    W = int(os.environ.get("DISPLAY_BOOT_W", "320"))
    H = int(os.environ.get("DISPLAY_BOOT_H", "240"))
    # Black background, white text; W,H from env support portrait (240x320) or landscape (320x240)
    BG = (0, 0, 0)
    FG = (255, 255, 255)
    try:
        epd = displayhatmini.EPD()
        if epd.init() != 0:
            return 1
        # Clear to black
        epd.Clear(0)
    except Exception:
        return 1
    try:
        # Big font for status lines
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

        # 1) Booting...
        img = __import__("PIL.Image", fromlist=["new"]).Image.new("RGB", (W, H), BG)
        draw = __import__("PIL.ImageDraw", fromlist=["Draw"]).ImageDraw.Draw(img)
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
        img = __import__("PIL.Image", fromlist=["new"]).Image.new("RGB", (W, H), BG)
        draw = __import__("PIL.ImageDraw", fromlist=["Draw"]).ImageDraw.Draw(img)
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

        # 3) System log (last boot messages)
        log_lines = _get_boot_log_lines(max_lines=10, line_chars=48)
        img = __import__("PIL.Image", fromlist=["new"]).Image.new("RGB", (W, H), BG)
        draw = __import__("PIL.ImageDraw", fromlist=["Draw"]).ImageDraw.Draw(img)
        draw.text((4, 2), "Boot log:", font=font_small, fill=FG)
        y = 16
        for line in log_lines:
            if y + 14 > H:
                break
            draw.text((4, y), line[:52], font=font_small, fill=FG)
            y += 13
        epd.display(img)
        time.sleep(6.0)

        # 4) Loading...
        img = __import__("PIL.Image", fromlist=["new"]).Image.new("RGB", (W, H), BG)
        draw = __import__("PIL.ImageDraw", fromlist=["Draw"]).ImageDraw.Draw(img)
        text = "Loading..."
        if font_big:
            bbox = draw.textbbox((0, 0), text, font=font_big)
        else:
            bbox = (0, 0, len(text) * 8, 20)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x, y = (W - tw) // 2, (H - th) // 2
        draw.text((x, y), text, font=font_big, fill=FG)
        epd.display(img)
        time.sleep(4.0)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
