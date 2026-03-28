#!/usr/bin/env python3
"""
Lightweight startup validation for Ragnar (no full app run, no display GPIO grab by default).
Used by pre_reboot_check.sh and optionally: python3 /home/ragnar/Ragnar/scripts/ragnar_startup_selftest.py
Exit 0 = OK, non-zero = failure with message on stderr.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import py_compile
import sys


def main() -> int:
    ragnar_dir = pathlib.Path(os.environ.get("RAGNAR_DIR", "/home/ragnar/Ragnar")).resolve()
    errors: list[str] = []

    def fail(msg: str) -> None:
        errors.append(msg)

    if not ragnar_dir.is_dir():
        print(f"FAIL: Ragnar directory missing or not a directory: {ragnar_dir}", file=sys.stderr)
        return 2

    entry = os.environ.get("RAGNAR_ENTRYPOINT", "Ragnar.py")
    ep = ragnar_dir / entry
    if not ep.is_file():
        fail(f"Entry point not found: {ep}")
    else:
        try:
            py_compile.compile(str(ep), doraise=True)
        except py_compile.PyCompileError as e:
            fail(f"Syntax error in {ep}: {e}")

    cfg_path = ragnar_dir / "config" / "shared_config.json"
    if not cfg_path.is_file():
        fail(f"Missing config: {cfg_path}")
    else:
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as e:
            fail(f"Invalid JSON {cfg_path}: {e}")
            cfg = {}
        epd = cfg.get("epd_type", "")
        if epd == "displayhatmini":
            spec = importlib.util.find_spec("waveshare_epd")
            if not spec or not spec.submodule_search_locations:
                fail("waveshare_epd package not found (required for displayhatmini)")
            else:
                wspath = pathlib.Path(spec.submodule_search_locations[0]) / "displayhatmini.py"
                if not wspath.is_file():
                    fail(f"Missing display driver file: {wspath}")
            spi0 = pathlib.Path("/dev/spidev0.0")
            spi1 = pathlib.Path("/dev/spidev0.1")
            if not spi0.exists() and not spi1.exists():
                fail("No /dev/spidev0.0 or /dev/spidev0.1 (enable SPI: raspi-config)")

    actions = ragnar_dir / "config" / "actions.json"
    if not actions.is_file():
        fail(f"Missing {actions}")

    sys.path.insert(0, str(ragnar_dir))
    for mod in ("PIL", "paramiko", "numpy"):
        try:
            __import__(mod)
        except ImportError as e:
            fail(f"Python import {mod} failed: {e}")

    dry_display = os.environ.get("RAGNAR_SELFTEST_DISPLAY_INIT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if dry_display:
        try:
            from waveshare_epd import displayhatmini

            e = displayhatmini.EPD()
            r = e.init()
            if r != 0:
                fail(f"displayhatmini EPD.init() returned {r}")
            e.module_exit()
        except OSError as ex:
            if getattr(ex, "errno", None) in (11, 16):  # EAGAIN, EBUSY
                fail(
                    "Display GPIO busy (another process holds SPI/GPIO). "
                    "Stop ragnar.service before RAGNAR_SELFTEST_DISPLAY_INIT=1."
                )
            else:
                fail(f"Display init OSError: {ex}")
        except Exception as ex:
            fail(f"Display init failed: {ex}")

    if errors:
        for line in errors:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1
    print("OK: ragnar_startup_selftest passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
