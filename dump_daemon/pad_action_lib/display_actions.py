"""`Display.ShowMessageDialog`(メッセージボックス表示)のロジック層。

design/dsl_format_findings.md 知見184/185: 本プロジェクト最初の実機キャプチャ
(design/g1_g2_verification_result.md、知見1)でありながら一度も`pad_codegen`に
結線されていなかったアクション。decompileした`FormMessageBox`(PAD独自のWinForms
ダイアログ、標準の`System.Windows.Forms.MessageBox`ではない)が各`Buttons`コンボに
割り当てる`System.Windows.Forms.DialogResult`値は、Win32標準のMessageBox戻り値
(IDOK=1/IDCANCEL=2/IDABORT=3/IDRETRY=4/IDIGNORE=5/IDYES=6/IDNO=7)と完全に一致する
(decompileで確認済み、PAD固有の推測ではない)——`ctypes.windll.user32.MessageBoxW`の
ネイティブ戻り値をそのまま`ButtonPressed`文字列(`DialogResult.ToString()`相当、
"OK"/"Cancel"/"Abort"/"Retry"/"Ignore"/"Yes"/"No")へ変換するだけで再現できる。

Windows専用(`ctypes.windll`はWindows以外には存在しない)——生成されたPythonコードは
Windows上でのみ実行される前提のため、他のモジュール(`win32timezone`/`win32crypt`等)
と同じ制約。

`ShowMessageWithTimeout`(`CloseAutomatically=True`)は見送る: decompile確認済みの
通り、タイムアウト時は`AcceptButton.DialogResult`(=`DefaultButton`が示す実際の
結果)を返す仕様だが、標準のWin32 `MessageBoxW`にはタイムアウト機能が無く、非公開API
`MessageBoxTimeoutW`はタイムアウト時に別の戻り値(`32000`)を返すため正確な再現が
できない——でっち上げず`NotImplementedError`のままにする。

`Display.SelectFolder`(`SelectFolderDialog`、兄弟セレクタの無いフラットなaction)も
同DLLに実装済み——`tkinter.filedialog.askdirectory()`がWindows上でPAD実機と同じ
ネイティブフォルダ選択ダイアログを呼び出す(知見185追補)。
"""
from __future__ import annotations

import ctypes

from .errors import PadActionError


class ShowMessageDialogError(PadActionError):
    pass


#: decompile確認済み(`FormMessageBox.SetButtons()`): 各`Buttons`コンボの
#: Win32標準フラグ値そのもの(`MB_OK`=0/`MB_OKCANCEL`=1/`MB_ABORTRETRYIGNORE`=2/
#: `MB_YESNOCANCEL`=3/`MB_YESNO`=4/`MB_RETRYCANCEL`=5)。
_BUTTONS_FLAG = {
    "OK": 0x0,
    "OKCancel": 0x1,
    "AbortRetryIgnore": 0x2,
    "YesNoCancel": 0x3,
    "YesNo": 0x4,
    "RetryCancel": 0x5,
}

#: Win32標準の`MB_ICON*`フラグ値。
_ICON_FLAG = {
    "None": 0x0,
    "ErrorIcon": 0x10,
    "Question": 0x20,
    "Warning": 0x30,
    "Information": 0x40,
}

#: Win32標準の`MB_DEFBUTTON*`フラグ値。
_DEFAULT_BUTTON_FLAG = {
    "Button1": 0x0,
    "Button2": 0x100,
    "Button3": 0x200,
}

#: `MB_TOPMOST`(Win32標準フラグ)。
_MB_TOPMOST = 0x40000

#: decompile確認済み(`FormMessageBox.SetButtons()`の`_button{1,2,3}.DialogResult`):
#: Win32標準のMessageBox戻り値(IDOK等)と完全に一致。
_RESULT_TO_BUTTON_PRESSED = {
    1: "OK",
    2: "Cancel",
    3: "Abort",
    4: "Retry",
    5: "Ignore",
    6: "Yes",
    7: "No",
}


def _compute_message_box_flags(icon: str, buttons: str, default_button: str, is_topmost: bool) -> int:
    try:
        flags = _BUTTONS_FLAG[buttons] | _ICON_FLAG[icon] | _DEFAULT_BUTTON_FLAG[default_button]
    except KeyError as exc:
        raise ValueError(str(exc)) from exc
    if is_topmost:
        flags |= _MB_TOPMOST
    return flags


def _button_pressed_from_result(result: int) -> str:
    return _RESULT_TO_BUTTON_PRESSED.get(result, "")


def show_message_dialog(
    message: str = "",
    title: str = "",
    icon: str = "None",
    buttons: str = "OK",
    default_button: str = "Button1",
    is_topmost: bool = False,
) -> str:
    """`Display.ShowMessageDialog.ShowMessage`(`CloseAutomatically=False`固定の
    兄弟セレクタ)。実際にブロッキングのメッセージボックスを表示し、ユーザーが押した
    ボタンに対応する文字列を返す。
    """
    flags = _compute_message_box_flags(icon, buttons, default_button, is_topmost)
    try:
        result = ctypes.windll.user32.MessageBoxW(0, message, title, flags)  # type: ignore[attr-defined]
    except Exception as exc:
        raise ShowMessageDialogError(str(exc)) from exc
    return _button_pressed_from_result(result)


def show_message_dialog_with_timeout(*_args: object, **_kwargs: object) -> str:
    raise NotImplementedError(
        "ShowMessageWithTimeout requires reproducing PAD's exact timeout-then-"
        "default-button behavior; the standard Win32 MessageBoxW has no timeout, "
        "and the undocumented MessageBoxTimeoutW returns a different sentinel "
        "(32000) on timeout rather than the default button's result, so this "
        "cannot be faithfully reproduced without further investigation"
    )


class SelectFolderDialogError(PadActionError):
    pass


def show_select_folder_dialog(
    description: str = "",
    initial_directory: str = "",
    is_topmost: bool = False,
) -> tuple[str, str]:
    """`Display.SelectFolder`(フラットなaction、`SelectFolderDialog`クラス)。

    design/dsl_format_findings.md 知見185追補: decompile確認済みの
    `FormDialogFocus.ShowSelectFolderDialog()`は、標準`System.Windows.Forms.
    FolderBrowserDialog`(.NET既定でAutoUpgradeEnabled=true、モダンな
    Explorer風フォルダ選択ダイアログ)をそのまま表示するだけで、OK時は
    選択パス+`ButtonPressed="OK"`、Cancel時は空文字列+`ButtonPressed="Cancel"`
    (いずれも`DialogResult.ToString()`相当)。`tkinter.filedialog.askdirectory()`
    はWindows上でこの同じネイティブフォルダ選択ダイアログを呼び出すため、
    戻り値の対応が一対一で確定できる(でっち上げ無し)。

    戻り値は`(selected_folder, button_pressed)`のタプル。
    """
    try:
        import tkinter
        from tkinter import filedialog
    except Exception as exc:
        raise SelectFolderDialogError(str(exc)) from exc

    try:
        root = tkinter.Tk()
        root.withdraw()
        if is_topmost:
            root.attributes("-topmost", True)
        try:
            selected = filedialog.askdirectory(
                title=description or None,
                initialdir=initial_directory or None,
            )
        finally:
            root.destroy()
    except Exception as exc:
        raise SelectFolderDialogError(str(exc)) from exc

    if selected:
        return selected, "OK"
    return "", "Cancel"
