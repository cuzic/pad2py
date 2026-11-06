"""`tests/fake_pywinauto.py`自身の単体テスト。"""
from __future__ import annotations

import pytest

from fake_pywinauto import FakeElementNotFoundError, FakeRegistry, make_fake_desktop


def test_window_exists_only_when_registered() -> None:
    registry = FakeRegistry()
    registry.register_window(title="Notepad")
    desktop = make_fake_desktop(registry)(backend="uia")

    assert desktop.window(title="Notepad").exists() is True
    assert desktop.window(title="Other").exists() is False


def test_child_window_requires_full_path_match() -> None:
    registry = FakeRegistry()
    registry.register_descendant({"title": "Notepad"}, {"class_name": "Edit"})
    desktop = make_fake_desktop(registry)(backend="uia")

    window = desktop.window(title="Notepad")
    assert window.child_window(class_name="Edit").exists() is True
    assert window.child_window(class_name="Other").exists() is False
    # 親のtitleが違えば、子の条件が同じでも一致しない。
    assert desktop.window(title="Other").child_window(class_name="Edit").exists() is False


def test_wrapper_object_raises_when_not_found() -> None:
    registry = FakeRegistry()
    desktop = make_fake_desktop(registry)(backend="uia")
    with pytest.raises(FakeElementNotFoundError):
        desktop.window(title="Missing").wrapper_object()


def test_click_input_and_set_focus_are_recorded() -> None:
    registry = FakeRegistry()
    registry.register_window(title="Notepad")
    desktop = make_fake_desktop(registry)(backend="uia")
    window = desktop.window(title="Notepad")

    window.click_input()
    window.set_focus()
    window.type_keys("hello")

    assert registry.calls == [
        ("click_input", [{"title": "Notepad"}], {}),
        ("set_focus", [{"title": "Notepad"}], {}),
        ("type_keys", [{"title": "Notepad"}], {"keys": "hello"}),
    ]


def test_wait_and_wait_not_are_recorded_and_return_self() -> None:
    registry = FakeRegistry()
    registry.register_window(title="Notepad")
    desktop = make_fake_desktop(registry)(backend="uia")
    window = desktop.window(title="Notepad")

    result = window.wait("exists", timeout=5)
    assert result is window
    window.wait_not("exists")

    assert registry.calls == [
        ("wait", [{"title": "Notepad"}], {"criteria": "exists", "timeout": 5}),
        ("wait_not", [{"title": "Notepad"}], {"criteria": "exists", "timeout": None}),
    ]


def test_windows_lists_only_top_level_registered_windows() -> None:
    registry = FakeRegistry()
    registry.register_window(title="Notepad")
    registry.register_descendant({"title": "Notepad"}, {"class_name": "Edit"})
    desktop = make_fake_desktop(registry)(backend="uia")

    windows = desktop.windows()
    assert len(windows) == 1
    assert windows[0].criteria == {"title": "Notepad"}


def test_set_active_controls_wrapper_object_regardless_of_call_count() -> None:
    # `wrapper_object()`は呼ぶたびに新しいオブジェクトを返すため、`is_active()`の値は
    # 個々のオブジェクトではなくレジストリ側で管理する(`UIAutomation.IfWindow.IsFocused`
    # 等の生成コードは同じセレクタに対し`wrapper_object()`を複数回呼ぶため)。
    registry = FakeRegistry()
    registry.register_window(title="Notepad")
    registry.set_active([{"title": "Notepad"}], False)
    desktop = make_fake_desktop(registry)(backend="uia")
    window = desktop.window(title="Notepad")

    assert window.wrapper_object().is_active() is False
    assert window.wrapper_object().is_active() is False  # 2回目の呼び出しでも値が保持される
