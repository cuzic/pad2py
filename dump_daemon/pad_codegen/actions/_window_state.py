"""`UIAutomation.*Window`(ウィンドウ単位の状態・位置操作)系の共有ヘルパー。

`window.py`(`Title`/`Class`ベース)・`ui_element.py`(`Control`ベース)両方の
`SetWindowState`/`MoveWindow`/`ResizeWindow`系セレクタが共有する。
"""
from __future__ import annotations

# UIAutomation.WindowState.* の列挙値 → pywinautoの`WindowSpecification`メソッド名
# (知見27で実機確認済みの対応、知見118の追記で`Control`/`WindowInstance`ベースの
# 兄弟セレクタにも同じ対応が使えると確認)。
WINDOW_STATE_TO_PYWINAUTO_METHOD = {
    "UIAutomation.WindowState.Maximized": "maximize",
    "UIAutomation.WindowState.Minimized": "minimize",
    "UIAutomation.WindowState.Restored": "restore",
}


def render_move_or_resize(
    prefix: str,
    window_expr: str,
    *,
    x: str | None = None,
    y: str | None = None,
    width: str | None = None,
    height: str | None = None,
) -> list[str]:
    """ウィンドウの移動・リサイズのPythonコードを生成する。

    design/dsl_format_findings.md 知見119(実機確認済み): pywinautoの`WindowSpecification`
    には(想定していた)`move_window()`メソッド自体が無い(UIAバックエンドのラッパーで
    `AttributeError`になることをVM上の実venvでNotepadを使い確認した)。代わりに
    `win32gui.MoveWindow(hwnd, x, y, width, height, repaint)`(既存の依存関係pywin32、
    常にx/y/width/height全てを要求する)が実機で正しく動くことを確認した。PADの
    `MoveWindow`はX/Yのみ・`ResizeWindow`はWidth/Heightのみを指定するため、指定されて
    いない側は`win32gui.GetWindowRect()`で現在値を読み取って保持する。
    """
    lines = [
        f"{prefix}_hwnd = {window_expr}.wrapper_object().handle",
        f"{prefix}_rect = win32gui.GetWindowRect(_hwnd)",
    ]
    x_expr = x if x is not None else "_rect[0]"
    y_expr = y if y is not None else "_rect[1]"
    width_expr = width if width is not None else "_rect[2] - _rect[0]"
    height_expr = height if height is not None else "_rect[3] - _rect[1]"
    lines.append(f"{prefix}win32gui.MoveWindow(_hwnd, {x_expr}, {y_expr}, {width_expr}, {height_expr}, True)")
    return lines
