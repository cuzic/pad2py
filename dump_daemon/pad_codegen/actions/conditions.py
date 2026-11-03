"""`IfActionRecord`/`ElseIfActionRecord`(`[ConditionAction]`カテゴリ)の条件式codegen。

現状`UIAutomation.IfWindow.*`ファミリーのみ対応(複雑な設定モードを持つ`IfImage`/
`IfWindowContains`等は意図的に未対応のまま`None`を返す)。
"""
from __future__ import annotations

from ...pad_dsl import ElseIfActionRecord, IfActionRecord, UiElementRef
from ..context import CodegenContext
from ..selectors import _build_pywinauto_selector_expr


def render_if_window_condition(header: IfActionRecord | ElseIfActionRecord, ctx: CodegenContext) -> str | None:
    """`UIAutomation.IfWindow.*`(`_generate_conditional()`のコメント参照)の条件式を
    pywinautoの真偽値式に変換する。セレクタが知見56の仕組みで解決できない場合、または
    `IfWindow`ファミリー以外(`IfImage`/`IfWindowContains`等、複数の設定可能なサブモードを
    持ち`IfWindow`より複雑であることが確認済み)の場合は`None`を返し、呼び出し元に安全な
    フォールバック(`NotImplementedError`)をさせる。

    `IsFocused`/`IsNotFocused`は、ウィンドウが存在しない場合にpywinautoの`wrapper_object()`
    が例外を投げてしまうのを避けるため、`exists()`を先に確認する防御的な合成式にしている
    (閉じているウィンドウはフォーカスされていないという素直な意味でFalseを返すと推測される。
    これは意味論そのものの推測ではなく、クラッシュを避けるための実装上のガード)。
    `IsOpen`/`IsNotOpen`は`exists()`の直接確認・否定のみ。調査根拠は`docs-local/`配下の
    リポジトリ非管理メモを参照(ソースコメントには残さない方針)。
    """
    if not header.action_id.startswith("UIAutomation.IfWindow."):
        return None
    window = header.params.get("Window")
    if not isinstance(window, UiElementRef):
        return None
    selector_expr = _build_pywinauto_selector_expr(window.path, ctx)
    if selector_expr is None:
        return None
    mode = header.action_id.rsplit(".", 1)[-1]
    exists_expr = f"{selector_expr}.exists()"
    if mode == "IsOpen":
        return exists_expr
    if mode == "IsNotOpen":
        return f"not {exists_expr}"
    if mode in ("IsFocused", "IsNotFocused"):
        active_expr = f"({exists_expr} and {selector_expr}.wrapper_object().is_active())"
        return active_expr if mode == "IsFocused" else f"not {active_expr}"
    return None
