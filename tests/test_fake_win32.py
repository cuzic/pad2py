"""`tests/fake_win32.py`自身の単体テスト。"""
from __future__ import annotations

import sys

from fake_win32 import FakeWin32Registry, fake_win32_modules


def test_fake_modules_are_installed_and_removed() -> None:
    assert "win32gui" not in sys.modules
    assert "win32con" not in sys.modules
    registry = FakeWin32Registry()
    with fake_win32_modules(registry):
        import win32con
        import win32gui

        assert win32con.SW_SHOW == 5
        assert win32con.SW_HIDE == 0
        assert win32gui.GetWindowRect(1) == (0, 0, 0, 0)
    assert "win32gui" not in sys.modules
    assert "win32con" not in sys.modules


def test_get_window_rect_returns_registered_value() -> None:
    registry = FakeWin32Registry()
    registry.set_rect(42, 1, 2, 300, 400)
    with fake_win32_modules(registry):
        import win32gui

        assert win32gui.GetWindowRect(42) == (1, 2, 300, 400)


def test_move_window_and_show_window_are_recorded() -> None:
    registry = FakeWin32Registry()
    with fake_win32_modules(registry):
        import win32con
        import win32gui

        win32gui.MoveWindow(42, 10, 20, 640, 480, True)
        win32gui.ShowWindow(42, win32con.SW_HIDE)

    assert registry.calls == [
        ("MoveWindow", 42, 10, 20, 640, 480, True),
        ("ShowWindow", 42, 0),
    ]


def test_get_foreground_window_returns_registered_handle() -> None:
    registry = FakeWin32Registry()
    registry.set_foreground(99)
    with fake_win32_modules(registry):
        import win32gui

        assert win32gui.GetForegroundWindow() == 99
