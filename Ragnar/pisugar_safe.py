"""
Safe PiSugar accessors: never raise; return None / 'unavailable' on failure.
Uses TCP (pisugar package) when listener is up — does not replace pisugar-server.

All entry points are time-bounded (thread pool) so a stuck TCP/I2C path in
another thread cannot block Ragnar indefinitely. Does not talk to I2C directly;
pisugar-server owns the bus — we only shield Ragnar's Python side.
"""

from __future__ import annotations

import concurrent.futures
import os
import time
from typing import Any, Callable, Optional, Union

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


def _run_with_timeout(
    fn: Callable[[], Any],
    timeout_sec: float,
    default: Any,
    label: str = "pisugar",
) -> Any:
    """Run fn in a worker; return default on timeout or any exception."""
    if timeout_sec <= 0:
        return safe_execute(label, fn, default=default)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(fn)
            return fut.result(timeout=timeout_sec)
    except Exception as e:
        reg = get_registry()
        if reg:
            reg.record(label, f"timeout/err: {e}"[:200], "warning")
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


def safe_init(
    shared_data: Any,
    timeout_sec: float = 5.0,
) -> str:
    """
    Quick probe: is PiSugar reachable via TCP (pisugar package) within timeout?
    Returns: 'ok' | 'unavailable' | 'error' — never raises.
    Does not start long retry loops; use for boot-guard / menu checks only.
    """
    try:
        from pisugar import connect_tcp, PiSugarServer  # type: ignore[import-untyped]
    except ImportError:
        return "unavailable"

    def _probe() -> bool:
        conn, ev = connect_tcp("127.0.0.1")
        srv = PiSugarServer(conn, ev)
        _ = srv.get_model()
        try:
            conn.close()
        except Exception:
            pass
        try:
            ev.close()
        except Exception:
            pass
        return True

    ok = _run_with_timeout(_probe, min(timeout_sec, 15.0), False, "pisugar_safe_init")
    if ok is True:
        return "ok"
    return "unavailable"


def safe_read(
    shared_data: Any,
    kind: str = "battery",
    timeout_sec: float = 2.0,
) -> Union[float, bool, str, None]:
    """
    Single read by kind: battery | voltage | charging | model
    Returns numeric/bool/str or None / 'unavailable'. Never raises.
    """
    kind = (kind or "battery").lower().strip()
    ps = _listener(shared_data)
    if not ps:
        return None

    def _do():
        if not getattr(ps, "available", False):
            return None
        if kind == "battery":
            return ps.get_battery_level()
        if kind in ("voltage", "volt"):
            return ps.get_battery_voltage()
        if kind in ("charging", "charge"):
            return ps.is_charging()
        if kind == "model":
            return ps.get_model()
        return None

    out = _run_with_timeout(_do, timeout_sec, None, f"pisugar_read_{kind}")
    return out


def safe_shutdown_signal(timeout_sec: float = 3.0) -> str:
    """
    Best-effort: ask pisugar-server to power off via TCP API if available.
    Many setups use `pisugar-cli` or physical button instead — this is optional.
    Returns: 'sent' | 'unavailable' | 'skipped'
    """
    try:
        from pisugar import connect_tcp, PiSugarServer  # type: ignore[import-untyped]
    except ImportError:
        return "unavailable"

    def _send():
        conn, ev = connect_tcp("127.0.0.1")
        srv = PiSugarServer(conn, ev)
        # Common pattern: raw API — if method missing, no-op
        if hasattr(srv, "shutdown"):
            srv.shutdown()  # type: ignore[misc]
            return True
        if hasattr(srv, "power_off"):
            srv.power_off()  # type: ignore[misc]
            return True
        return False

    try:
        ok = _run_with_timeout(_send, timeout_sec, False, "pisugar_shutdown")
        if ok is True:
            return "sent"
        return "skipped"
    except Exception:
        return "unavailable"


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
