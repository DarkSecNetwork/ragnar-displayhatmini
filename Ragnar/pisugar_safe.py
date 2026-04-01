"""
Safe PiSugar accessors: never raise; return None / 'unavailable' on failure.
Uses TCP (pisugar package) when listener is up — does not replace pisugar-server.
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

try:
    from ragnar_safe import get_registry, safe_execute
except ImportError:
    def get_registry():
        return None

    def safe_execute(component, fn, *a, default=None, **k):
        try:
            return fn(*a, **k)
        except Exception:
            return default


def _listener(shared_data: Any):
    ri = getattr(shared_data, "ragnar_instance", None)
    if not ri:
        return None
    return getattr(ri, "pisugar_listener", None)


def safe_pisugar_available(shared_data: Any) -> bool:
    ps = _listener(shared_data)
    return bool(ps and getattr(ps, "available", False))


def safe_read_battery_level(shared_data: Any) -> Optional[float]:
    """Battery % or None if unavailable."""

    def _read():
        ps = _listener(shared_data)
        if not ps or not getattr(ps, "available", False):
            return None
        return ps.get_battery_level()

    return safe_execute("pisugar", _read, default=None)


def safe_read_voltage(shared_data: Any) -> Optional[float]:
    def _read():
        ps = _listener(shared_data)
        if not ps or not getattr(ps, "available", False):
            return None
        return ps.get_battery_voltage()

    return safe_execute("pisugar", _read, default=None)


def safe_is_charging(shared_data: Any) -> Optional[bool]:
    def _read():
        ps = _listener(shared_data)
        if not ps or not getattr(ps, "available", False):
            return None
        return ps.is_charging()

    return safe_execute("pisugar", _read, default=None)


def safe_init_retry(
    connect_fn: Any,
    max_seconds: float = 30.0,
    label: str = "pisugar_tcp",
) -> bool:
    """
    Optional exponential backoff wrapper for one-shot init (e.g. custom TCP).
    connect_fn: callable returning True on success.
    """
    t0 = time.time()
    delay = 0.5
    attempt = 0
    while time.time() - t0 < max_seconds:
        attempt += 1

        def _try():
            return bool(connect_fn())

        ok = safe_execute(label, _try, default=False)
        if ok:
            reg = get_registry()
            if reg:
                reg.record(label, f"connected after {attempt} attempt(s)", "info")
            return True
        time.sleep(min(delay, 8.0))
        delay *= 1.65
    reg = get_registry()
    if reg:
        reg.record(label, f"unavailable after {max_seconds:.0f}s — continuing without", "warning")
    return False
