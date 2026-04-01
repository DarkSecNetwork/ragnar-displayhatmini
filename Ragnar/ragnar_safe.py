"""
Ragnar resilience utilities: non-blocking error registry, safe_execute, boot/file logging.
Hardware failures must never take down the main loop.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Deque, List, Optional

_LOG = logging.getLogger("ragnar_safe")

# Optional rotating handler for /var/log/ragnar.log (attached once)
_ragnar_file_handler = None
_file_lock = threading.Lock()


@dataclass
class ErrorRecord:
    component: str
    message: str
    severity: str  # "info", "warning", "error"
    ts: float = field(default_factory=time.time)


class ErrorRegistry:
    """Thread-safe ring buffer of recent failures (for UI / diagnostics)."""

    def __init__(self, maxlen: int = 80):
        self._lock = threading.Lock()
        self._items: Deque[ErrorRecord] = deque(maxlen=maxlen)

    def record(
        self,
        component: str,
        message: str,
        severity: str = "warning",
    ) -> None:
        rec = ErrorRecord(component=component, message=message[:500], severity=severity)
        with self._lock:
            self._items.append(rec)

    def recent(self, limit: int = 24) -> List[ErrorRecord]:
        with self._lock:
            return list(self._items)[-limit:]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


_registry = ErrorRegistry()


def get_registry() -> ErrorRegistry:
    return _registry


def safe_execute(
    component: str,
    fn: Callable[..., Any],
    *args: Any,
    default: Any = None,
    severity: str = "warning",
    log_trace: bool = False,
    **kwargs: Any,
) -> Any:
    """
    Run fn(*args, **kwargs); on failure log + registry + return default (never raise).
    """
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        msg = f"{e}"
        _LOG.warning("[%s] safe_execute: %s", component, msg)
        _registry.record(component, msg, severity=severity)
        if log_trace:
            _registry.record(component, traceback.format_exc()[:400], severity="error")
        return default


def log_boot_marker(stage: str) -> None:
    """Structured boot line (journal + optional file)."""
    line = f"BOOT {datetime.now().isoformat(timespec='seconds')} pid={os.getpid()} {stage}"
    _LOG.info(line)
    try:
        with _file_lock:
            path = "/var/log/ragnar.log"
            if os.access("/var/log", os.W_OK) or os.path.isfile(path):
                with open(path, "a", encoding="utf-8", errors="replace") as f:
                    f.write(line + "\n")
                    f.flush()
    except Exception:
        pass


def setup_ragnar_file_logging(path: str = "/var/log/ragnar.log") -> None:
    """
    Attach a rotating file handler to the 'ragnar' logger (idempotent).
    Requires write access to path (ragnar.service runs as root).
    """
    global _ragnar_file_handler
    if _ragnar_file_handler is not None:
        return
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    except Exception:
        pass
    try:
        from logging.handlers import RotatingFileHandler

        lg = logging.getLogger("ragnar")
        lg.setLevel(logging.DEBUG)
        h = RotatingFileHandler(path, maxBytes=4 * 1024 * 1024, backupCount=3)
        h.setLevel(logging.DEBUG)
        h.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        lg.addHandler(h)
        _ragnar_file_handler = h
        lg.info("Ragnar file logging initialized: %s", path)
    except Exception as e:
        _LOG.debug("setup_ragnar_file_logging skipped: %s", e)


def log_component_init(component: str, ok: bool, detail: str = "") -> None:
    """Boot-time component outcome."""
    status = "OK" if ok else "FAIL"
    msg = f"init {component}: {status} {detail}".strip()
    lg = logging.getLogger("ragnar")
    if ok:
        lg.info(msg)
    else:
        lg.warning(msg)
        _registry.record(component, detail or status, severity="warning")
