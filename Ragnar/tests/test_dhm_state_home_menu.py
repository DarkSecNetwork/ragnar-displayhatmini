#!/usr/bin/env python3
"""
Regression tests: STATE_HOME opens root menu on Button A (L_UP) and B (L_SELECT);
STATE_MENU uses L_UP for scrolling only.

Run from repo Ragnar/ directory:
  python3 -m unittest tests.test_dhm_state_home_menu -v

Or on device:
  cd /home/ragnar/Ragnar && python3 -m unittest tests.test_dhm_state_home_menu -v
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

# Ensure Ragnar package root is importable when run as unittest module
_HERE = os.path.dirname(os.path.abspath(__file__))
_RAGNAR_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
if _RAGNAR_ROOT not in sys.path:
    sys.path.insert(0, _RAGNAR_ROOT)


class _FakeDisplay:
    __slots__ = ("menu_visible", "dhm_ui")

    def __init__(self) -> None:
        self.menu_visible = False
        from dhm_ui_state import UIState

        self.dhm_ui = UIState()


class TestDhmHomeOpensMenu(unittest.TestCase):
    """Minimal behavioral tests for dhm_ui_state.handle_dhm_state_event (no hardware)."""

    def setUp(self) -> None:
        from dhm_ui_state import (
            STATE_HOME,
            STATE_MENU,
            UIState,
            _HOME_OPEN_MENU_LOGICALS,
            handle_dhm_state_event,
            L_UP,
            L_SELECT,
        )

        self.STATE_HOME = STATE_HOME
        self.STATE_MENU = STATE_MENU
        self.UIState = UIState
        self._HOME_OPEN_MENU_LOGICALS = _HOME_OPEN_MENU_LOGICALS
        self.handle_dhm_state_event = handle_dhm_state_event
        self.L_UP = L_UP
        self.L_SELECT = L_SELECT

    def test_home_open_constants_include_a_and_b(self) -> None:
        self.assertIn(self.L_UP, self._HOME_OPEN_MENU_LOGICALS)
        self.assertIn(self.L_SELECT, self._HOME_OPEN_MENU_LOGICALS)

    @patch("dhm_ui_state._ensure_menu_imports", lambda: None)
    def test_home_l_up_opens_menu(self) -> None:
        d = _FakeDisplay()
        d.dhm_ui.state = self.STATE_HOME
        self.handle_dhm_state_event(d, self.L_UP, lambda *a, **k: None)
        self.assertEqual(d.dhm_ui.state, self.STATE_MENU)
        self.assertTrue(d.menu_visible)
        self.assertEqual(d.dhm_ui.root_index, 0)

    @patch("dhm_ui_state._ensure_menu_imports", lambda: None)
    def test_home_l_select_opens_menu(self) -> None:
        d = _FakeDisplay()
        d.dhm_ui.state = self.STATE_HOME
        self.handle_dhm_state_event(d, self.L_SELECT, lambda *a, **k: None)
        self.assertEqual(d.dhm_ui.state, self.STATE_MENU)
        self.assertTrue(d.menu_visible)

    @patch("dhm_ui_state._ensure_menu_imports", lambda: None)
    @patch("dhm_ui_state.ROOT_MENU_SPEC", [{"action": "x", "label": "a", "icon": "i"}] * 3)
    def test_menu_l_up_scrolls_does_not_go_home(self) -> None:
        d = _FakeDisplay()
        d.menu_visible = True
        d.dhm_ui.state = self.STATE_MENU
        d.dhm_ui.root_index = 0
        self.handle_dhm_state_event(d, self.L_UP, lambda *a, **k: None)
        self.assertEqual(d.dhm_ui.state, self.STATE_MENU)
        self.assertTrue(d.menu_visible)
        self.assertNotEqual(d.dhm_ui.root_index, 0)  # wrapped


if __name__ == "__main__":
    unittest.main()
