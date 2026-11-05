"""`UIAutomation.*ByTitleClass`(ウィンドウ単位の状態操作)系アクションのcodegen。

`Title`/`Class`パラメータだけからウィンドウを特定できる、ByTitleClassセレクタパターンに
限定したシンプルなファミリー(UI要素リポジトリ/`CodegenContext`は参照しない——
`_window_lookup_expr()`はDSLのパラメータ値から直接組み立てる)。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord, EnumRef, VarRef
from ..context import CodegenContext
from ..render import INDENT, render_value
from ._window_state import VISIBILITY_VALUE_TO_BOOL as _VISIBILITY_VALUE_TO_BOOL
from ._window_state import WINDOW_STATE_TO_PYWINAUTO_METHOD as _WINDOW_STATE_TO_PYWINAUTO_METHOD
from ._window_state import render_move_or_resize, render_set_visibility


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    prefix = INDENT * indent
    if node.action_id == "UIAutomation.SetWindowState.SetStateByTitleClass":
        window_expr = _window_lookup_expr(node)
        state = node.params.get("State")
        if window_expr and isinstance(state, EnumRef) and state.value in _WINDOW_STATE_TO_PYWINAUTO_METHOD:
            method = _WINDOW_STATE_TO_PYWINAUTO_METHOD[state.value]
            return [f"{prefix}{window_expr}.{method}()"]
    if node.action_id == "UIAutomation.MoveWindow.MoveByTitleClass":
        # design/dsl_format_findings.md 知見119(実機確認済み): pywinautoの
        # `WindowSpecification`には`move_window()`メソッド自体が無い(UIAバックエンドで
        # `AttributeError`になることをVM上の実venvで確認した)。`render_move_or_resize()`
        # (`win32gui.MoveWindow`経由、知見119)に差し替えた。
        window_expr = _window_lookup_expr(node)
        x = node.params.get("X")
        y = node.params.get("Y")
        if window_expr and isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return render_move_or_resize(prefix, window_expr, x=render_value(x), y=render_value(y))
    if node.action_id == "UIAutomation.ResizeWindow.ResizeByTitleClass":
        window_expr = _window_lookup_expr(node)
        width = node.params.get("Width")
        height = node.params.get("Height")
        if window_expr and isinstance(width, (int, float)) and isinstance(height, (int, float)):
            return render_move_or_resize(
                prefix, window_expr, width=render_value(width), height=render_value(height)
            )
    if node.action_id == "UIAutomation.FocusWindow.FocusByTitleClass":
        # design/dsl_format_findings.md 知見27(実機確認済み、SetWindowState等と同じ
        # ByTitleClassパターン)。
        window_expr = _window_lookup_expr(node)
        if window_expr:
            return [f"{prefix}{window_expr}.set_focus()"]
    if node.action_id == "UIAutomation.CloseWindow.CloseByTitleClass":
        # 他の4つのByTitleClass系アクションと全く同じパターンだと確認できている
        # (action_id自体は実機未確認、パターンからの推論)。
        window_expr = _window_lookup_expr(node)
        if window_expr:
            return [f"{prefix}{window_expr}.close()"]
    if node.action_id == "UIAutomation.CloseWindow.CloseByInstanceOrHandle":
        # design/dsl_format_findings.md 知見57(実機確認済み): `WindowInstance`パラメータは
        # 引用符もUI要素参照の角括弧も付かない、完全に裸の変数参照(`VarRef`)として直列化
        # される。この変数は`UIAutomation.GetWindow.GetUseTimeout`の結線
        # (`ui_element.py`、知見57・81)でpywinautoの`WindowSpecification`が代入される
        # 設計のため、同じ変数へ`.close()`を呼ぶだけで良い——knowledge75系の「window
        # instanceは単なる変数参照」という知見をそのまま活かせる、他のInstance系アクション
        # (Excel/Word/PowerPoint、知見79・80)と同種の結線。
        window_instance = node.params.get("WindowInstance")
        if isinstance(window_instance, VarRef):
            return [f"{prefix}{render_value(window_instance)}.close()"]
    if node.action_id == "UIAutomation.FocusWindow.FocusByInstanceOrHandle":
        # design/dsl_format_findings.md 知見117の追記(decompile確認済み): `CloseWindow.
        # CloseByInstanceOrHandle`と全く同じ構造の兄弟セレクタ(`FocusWindow`側)。
        window_instance = node.params.get("WindowInstance")
        if isinstance(window_instance, VarRef):
            return [f"{prefix}{render_value(window_instance)}.set_focus()"]
    if node.action_id == "UIAutomation.MoveWindow.MoveByInstanceOrHandle":
        # design/dsl_format_findings.md 知見119(decompile確認済み): `MoveWindow`/
        # `ResizeWindow`/`SetWindowState`も`GetWindow`/`CloseWindow`/`FocusWindow`と
        # 全く同じ3セレクタ構造を持つ——`WindowInstance`ベースの兄弟セレクタ。
        window_instance = node.params.get("WindowInstance")
        x = node.params.get("X")
        y = node.params.get("Y")
        if isinstance(window_instance, VarRef) and isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return render_move_or_resize(
                prefix, render_value(window_instance), x=render_value(x), y=render_value(y)
            )
    if node.action_id == "UIAutomation.ResizeWindow.ResizeByInstanceOrHandle":
        window_instance = node.params.get("WindowInstance")
        width = node.params.get("Width")
        height = node.params.get("Height")
        if (
            isinstance(window_instance, VarRef)
            and isinstance(width, (int, float))
            and isinstance(height, (int, float))
        ):
            return render_move_or_resize(
                prefix, render_value(window_instance), width=render_value(width), height=render_value(height)
            )
    if node.action_id == "UIAutomation.SetWindowVisibility.SetVisibilityByTitleClass":
        # design/dsl_format_findings.md 知見120(decompile+実機確認済み): `UIAutomation.
        # Actions.dll`に完全に未結線だった`SetWindowVisibility`アクション(`Control`/
        # `WindowInstance`/`Title`+`Class`の3セレクタ構造、知見117〜119と同種)を発見した。
        # `win32gui.ShowWindow(hwnd, SW_SHOW/SW_HIDE)`で実機確認済み。
        window_expr = _window_lookup_expr(node)
        visibility = node.params.get("Visibility")
        if window_expr and isinstance(visibility, EnumRef) and visibility.value in _VISIBILITY_VALUE_TO_BOOL:
            return render_set_visibility(prefix, window_expr, visible=_VISIBILITY_VALUE_TO_BOOL[visibility.value])
    if node.action_id == "UIAutomation.SetWindowVisibility.SetVisibilityByInstanceOrHandle":
        window_instance = node.params.get("WindowInstance")
        visibility = node.params.get("Visibility")
        if (
            isinstance(window_instance, VarRef)
            and isinstance(visibility, EnumRef)
            and visibility.value in _VISIBILITY_VALUE_TO_BOOL
        ):
            return render_set_visibility(
                prefix, render_value(window_instance), visible=_VISIBILITY_VALUE_TO_BOOL[visibility.value]
            )
    if node.action_id == "UIAutomation.SetWindowState.SetStateByInstanceOrHandle":
        window_instance = node.params.get("WindowInstance")
        state = node.params.get("State")
        if (
            isinstance(window_instance, VarRef)
            and isinstance(state, EnumRef)
            and state.value in _WINDOW_STATE_TO_PYWINAUTO_METHOD
        ):
            method = _WINDOW_STATE_TO_PYWINAUTO_METHOD[state.value]
            return [f"{prefix}{render_value(window_instance)}.{method}()"]
    return None


def _window_lookup_expr(node: ActionRecord) -> str | None:
    """`Title`/`Class`パラメータから`Desktop(backend='uia').window(title=...)`式を組み立てる。

    `Window class`を併用した組み合わせ(知見24で未検証のまま)では`None`を返し、
    呼び出し元に架空の変換をさせない。`Title`/`Class`の両方を持つ`UIAutomation.*ByTitleClass`
    系アクション(SetWindowState/MoveWindow/ResizeWindow)で共通して使うヘルパー。
    """
    title = node.params.get("Title")
    window_class = node.params.get("Class")
    if isinstance(title, str) and window_class == "":
        return f"Desktop(backend='uia').window(title={render_value(title)})"
    return None
