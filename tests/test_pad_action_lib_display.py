"""`pad_action_lib.display_actions`の単体テスト。

design/dsl_format_findings.md 知見184/185: `ctypes.windll`はWindows以外には
存在しないため(`display_actions`モジュール自体のimportはどのOSでも成功するが、
`show_message_dialog()`の呼び出しはWindows専用)、フラグ計算・戻り値変換の純粋な
ロジックは直接テストし、実際のOS呼び出し経路は`ctypes.windll`を偽装注入して
(実際にダイアログを表示せず)配線のみを検証する。
"""
from __future__ import annotations

import ctypes

import pytest

from dump_daemon.pad_action_lib import display_actions as da


def test_compute_message_box_flags_ok_none_button1() -> None:
    assert da._compute_message_box_flags("None", "OK", "Button1", False) == 0x0


def test_compute_message_box_flags_combines_all_components() -> None:
    # design/dsl_format_findings.md 知見185(decompile確認済み): 各フラグはWin32標準の
    # MB_YESNOCANCEL(3)|MB_ICONWARNING(0x30)|MB_DEFBUTTON2(0x100)|MB_TOPMOST(0x40000)。
    flags = da._compute_message_box_flags("Warning", "YesNoCancel", "Button2", True)
    assert flags == (0x3 | 0x30 | 0x100 | 0x40000)


def test_compute_message_box_flags_unknown_value_raises_value_error() -> None:
    with pytest.raises(ValueError):
        da._compute_message_box_flags("NotAnIcon", "OK", "Button1", False)


@pytest.mark.parametrize(
    "result,expected",
    [
        (1, "OK"),
        (2, "Cancel"),
        (3, "Abort"),
        (4, "Retry"),
        (5, "Ignore"),
        (6, "Yes"),
        (7, "No"),
    ],
)
def test_button_pressed_from_result_matches_decompiled_dialog_result_values(
    result: int, expected: str
) -> None:
    # design/dsl_format_findings.md 知見185(decompile確認済み): FormMessageBox.SetButtons()が
    # 各ボタンに割り当てるDialogResult値はWin32標準のMessageBox戻り値(IDOK等)と完全に一致。
    assert da._button_pressed_from_result(result) == expected


def test_button_pressed_from_result_unknown_code_returns_empty_string() -> None:
    assert da._button_pressed_from_result(0) == ""


class _FakeUser32:
    def __init__(self, return_value: int) -> None:
        self.return_value = return_value
        self.calls: list[tuple] = []

    def MessageBoxW(self, hwnd: int, message: str, title: str, flags: int) -> int:
        self.calls.append((hwnd, message, title, flags))
        return self.return_value


class _FakeWindll:
    def __init__(self, user32: _FakeUser32) -> None:
        self.user32 = user32


def test_show_message_dialog_calls_message_box_w_with_computed_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_user32 = _FakeUser32(return_value=6)  # Yes
    monkeypatch.setattr(ctypes, "windll", _FakeWindll(fake_user32), raising=False)

    result = da.show_message_dialog(
        message="hello", title="greeting", icon="Question", buttons="YesNo", default_button="Button1"
    )

    assert result == "Yes"
    assert fake_user32.calls == [(0, "hello", "greeting", 0x4 | 0x20 | 0x0)]


def test_show_message_dialog_wraps_os_level_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenUser32:
        def MessageBoxW(self, *args: object) -> int:
            raise OSError("no desktop session")

    monkeypatch.setattr(ctypes, "windll", _FakeWindll(_BrokenUser32()), raising=False)

    with pytest.raises(da.ShowMessageDialogError):
        da.show_message_dialog()


def test_show_message_dialog_with_timeout_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        da.show_message_dialog_with_timeout()
