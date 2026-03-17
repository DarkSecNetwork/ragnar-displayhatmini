#!/usr/bin/env python3
"""Display HAT Mini boot splash: show Booting / Starting Ragnar / Loading before main process."""
import sys
import time
def main():
    try:
        from PIL import Image, ImageDraw
        from waveshare_epd import displayhatmini
    except ImportError:
        return 0
    W, H = 320, 240
    messages = [("Booting...", 2.0), ("Starting Ragnar...", 2.0), ("Loading...", 4.0)]
    try:
        epd = displayhatmini.EPD()
        if epd.init() != 0:
            return 1
        epd.Clear(255)
    except Exception:
        return 1
    try:
        for text, duration in messages:
            img = __import__("PIL.Image", fromlist=["new"]).Image.new("RGB", (W, H), (255, 255, 255))
            draw = __import__("PIL.ImageDraw", fromlist=["Draw"]).ImageDraw.Draw(img)
            try:
                font = __import__("PIL.ImageFont", fromlist=["truetype"]).ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
            except Exception:
                font = None
            if font:
                bbox = draw.textbbox((0, 0), text, font=font)
            else:
                bbox = (0, 0, len(text) * 8, 20)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            x, y = (W - tw) // 2, (H - th) // 2
            draw.text((x, y), text, font=font, fill=(0, 0, 0))
            epd.display(img)
            time.sleep(duration)
    except Exception:
        pass
    return 0
if __name__ == "__main__":
    sys.exit(main())
