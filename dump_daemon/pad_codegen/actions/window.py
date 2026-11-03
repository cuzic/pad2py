"""`UIAutomation.*ByTitleClass`(ウィンドウ単位の状態操作)系アクションのcodegen。

`Title`/`Class`パラメータだけからウィンドウを特定できる、ByTitleClassセレクタパターンに
限定したシンプルなファミリー(UI要素リポジトリ/`CodegenContext`は参照しない——
`_window_lookup_expr()`はDSLのパラメータ値から直接組み立てる)。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord, EnumRef
from ..context import CodegenContext
from ..render import INDENT, render_value

# UIAutomation.WindowState.* の列挙値 → pywinautoのWindowSpecificationメソッド名。
_WINDOW_STATE_TO_PYWINAUTO_METHOD = {
    "UIAutomation.WindowState.Maximized": "maximize",
    "UIAutomation.WindowState.Minimized": "minimize",
    "UIAutomation.WindowState.Restored": "restore",
}


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    prefix = INDENT * indent
    if node.action_id == "UIAutomation.SetWindowState.SetStateByTitleClass":
        window_expr = _window_lookup_expr(node)
        state = node.params.get("State")
        if window_expr and isinstance(state, EnumRef) and state.value in _WINDOW_STATE_TO_PYWINAUTO_METHOD:
            method = _WINDOW_STATE_TO_PYWINAUTO_METHOD[state.value]
            return [f"{prefix}{window_expr}.{method}()"]
    if node.action_id == "UIAutomation.MoveWindow.MoveByTitleClass":
        window_expr = _window_lookup_expr(node)
        x = node.params.get("X")
        y = node.params.get("Y")
        if window_expr and isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return [f"{prefix}{window_expr}.move_window(x={render_value(x)}, y={render_value(y)})"]
    if node.action_id == "UIAutomation.ResizeWindow.ResizeByTitleClass":
        window_expr = _window_lookup_expr(node)
        width = node.params.get("Width")
        height = node.params.get("Height")
        if window_expr and isinstance(width, (int, float)) and isinstance(height, (int, float)):
            return [
                f"{prefix}{window_expr}.move_window(width={render_value(width)}, height={render_value(height)})"
            ]
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
