"""`pad_action_lib.display_actions`の単体テスト。

design/dsl_format_findings.md 知見184/185: `ctypes.windll`はWindows以外には
存在しないため(`display_actions`モジュール自体のimportはどのOSでも成功するが、
`show_message_dialog()`の呼び出しはWindows専用)、フラグ計算・戻り値変換の純粋な
ロジックは直接テストし、実際のOS呼び出し経路は`ctypes.windll`を偽装注入して
(実際にダイアログを表示せず)配線のみを検証する。`show_select_folder_dialog()`も
同様に、`sys.modules`へ偽装した`tkinter`/`tkinter.filedialog`を注入し、実際の
GUIダイアログを一切表示せずに配線を検証する。
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


class _FakeTk:
    instances: list["_FakeTk"] = []

    def __init__(self) -> None:
        self.destroyed = False
        self.attributes_calls: list[tuple] = []
        _FakeTk.instances.append(self)

    def withdraw(self) -> None:
        pass

    def attributes(self, *args: object) -> None:
        self.attributes_calls.append(args)

    def destroy(self) -> None:
        self.destroyed = True


def _install_fake_tkinter(monkeypatch: pytest.MonkeyPatch, askdirectory_return: str) -> list[dict]:
    import sys
    import types

    _FakeTk.instances.clear()
    fake_tkinter = types.ModuleType("tkinter")
    fake_tkinter.Tk = _FakeTk  # type: ignore[attr-defined]

    fake_filedialog = types.ModuleType("tkinter.filedialog")
    calls: list[dict] = []

    def _askdirectory(**kwargs: object) -> str:
        calls.append(kwargs)
        return askdirectory_return

    fake_filedialog.askdirectory = _askdirectory  # type: ignore[attr-defined]
    fake_tkinter.filedialog = fake_filedialog  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "tkinter", fake_tkinter)
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", fake_filedialog)
    return calls


def test_show_select_folder_dialog_returns_selected_path_and_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_tkinter(monkeypatch, askdirectory_return="C:\\Users\\test\\Documents")

    folder, button = da.show_select_folder_dialog(description="Pick a folder", initial_directory="C:\\")

    assert folder == "C:\\Users\\test\\Documents"
    assert button == "OK"
    assert calls == [{"title": "Pick a folder", "initialdir": "C:\\"}]
    assert _FakeTk.instances[0].destroyed is True


def test_show_select_folder_dialog_returns_empty_and_cancel_when_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_tkinter(monkeypatch, askdirectory_return="")

    folder, button = da.show_select_folder_dialog()

    assert folder == ""
    assert button == "Cancel"


def test_show_select_folder_dialog_sets_topmost_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_tkinter(monkeypatch, askdirectory_return="")

    da.show_select_folder_dialog(is_topmost=True)

    assert _FakeTk.instances[0].attributes_calls == [("-topmost", True)]


def test_show_select_folder_dialog_wraps_tkinter_import_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "tkinter", None)

    with pytest.raises(da.SelectFolderDialogError):
        da.show_select_folder_dialog()


def test_show_select_folder_dialog_wraps_dialog_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    fake_tkinter = types.ModuleType("tkinter")

    class _BrokenTk:
        def __init__(self) -> None:
            raise RuntimeError("no display")

    fake_tkinter.Tk = _BrokenTk  # type: ignore[attr-defined]
    fake_filedialog = types.ModuleType("tkinter.filedialog")
    fake_tkinter.filedialog = fake_filedialog  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tkinter", fake_tkinter)
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", fake_filedialog)

    with pytest.raises(da.SelectFolderDialogError):
        da.show_select_folder_dialog()
