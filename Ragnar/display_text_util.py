"""Pixel-accurate journal / log line fitting for small PIL displays (Display HAT Mini)."""
from __future__ import annotations

import re

# journalctl -o short-iso: "2026-03-28 14:23:06 hostname unit[123]: …"
_RE_SHORT_ISO = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*\s+\S+\s+"
)
# Classic syslog: "Mar 28 14:23:06 hostname …"
_RE_SYSLOG = re.compile(r"^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\S+\s+")


def compact_journal_line(s: str) -> str:
    """Drop date/time and hostname prefix so more of the message fits on screen."""
    s = (s or "").strip()
    if not s:
        return ""
    m = _RE_SHORT_ISO.match(s)
    if m:
        return s[m.end() :].strip()
    m = _RE_SYSLOG.match(s)
    if m:
        return s[m.end() :].strip()
    return s


def text_pixel_width(draw, text: str, font) -> float:
    try:
        return float(draw.textlength(text, font=font))
    except (AttributeError, TypeError, ValueError):
        bbox = draw.textbbox((0, 0), text, font=font)
        return float(bbox[2] - bbox[0])


def ellipsis_fit_to_width(draw, text: str, font, max_width: int) -> str:
    """Return text shortened with an ellipsis so rendered width <= max_width (pixels)."""
    text = (text or "").replace("\t", " ")
    if max_width <= 10:
        return ""
    if text_pixel_width(draw, text, font) <= max_width:
        return text
    ell = "…"
    if text_pixel_width(draw, ell, font) > max_width:
        return ""
    lo, hi = 0, len(text)
    best = ell
    while lo <= hi:
        mid = (lo + hi + 1) // 2
        cand = text[:mid].rstrip() + ell
        if text_pixel_width(draw, cand, font) <= max_width:
            best = cand
            lo = mid + 1
        else:
            hi = mid - 1
    return best
