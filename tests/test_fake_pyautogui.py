"""`tests/fake_pyautogui.py`自身の単体テスト。"""
from __future__ import annotations

import sys

from fake_pyautogui import FakePyAutoGuiRegistry, fake_pyautogui_module


def test_fake_module_is_installed_and_removed() -> None:
    assert "pyautogui" not in sys.modules
    registry = FakePyAutoGuiRegistry()
    with fake_pyautogui_module(registry):
        import pyautogui

        pyautogui.click()
    assert "pyautogui" not in sys.modules


def test_click_move_to_and_keyboard_calls_are_recorded() -> None:
    registry = FakePyAutoGuiRegistry()
    with fake_pyautogui_module(registry):
        import pyautogui

        pyautogui.click()
        pyautogui.moveTo(10, 20)
        pyautogui.typewrite("hello", interval=0.01)
        pyautogui.keyDown("ctrl")
        pyautogui.keyUp("ctrl")

    assert registry.calls == [
        ("click",),
        ("moveTo", 10, 20),
        ("typewrite", "hello", 0.01),
        ("keyDown", "ctrl"),
        ("keyUp", "ctrl"),
    ]


def test_unsupported_call_raises_attribute_error() -> None:
    with fake_pyautogui_module() as registry:
        import pyautogui

        try:
            pyautogui.locateOnScreen("x.png")
        except AttributeError:
            pass
        else:
            raise AssertionError("should not fabricate unsupported pyautogui calls")
    assert registry.calls == []
