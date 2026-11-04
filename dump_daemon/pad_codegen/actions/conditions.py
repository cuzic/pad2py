"""`IfActionRecord`/`ElseIfActionRecord`(`[ConditionAction]`カテゴリ)の条件式codegen。

現状`UIAutomation.IfWindow.*`ファミリーのみ対応(複雑な設定モードを持つ`IfImage`/
`IfWindowContains`等は意図的に未対応のまま`None`を返す)。
"""
from __future__ import annotations

from ...pad_dsl import ElseIfActionRecord, IfActionRecord, UiElementRef
from ..context import CodegenContext
from ..selectors import _build_pywinauto_selector_expr
from ._support import safe_render

# design/dsl_format_findings.md 知見68/69(実機確認済み): `File.IfFile.Exists`/
# `Folder.IfFolderExists.Exists`はUI要素セレクタを一切使わない単純な存在チェックで、
# `pad_action_lib`の対応する関数呼び出し1つに素直に変換できる(`IfImage`/
# `IfWindowContains`のような複数の設定可能なサブモードが無い)。
_EXISTENCE_CHECKS: dict[str, tuple[str, str]] = {
    "File.IfFile.Exists": ("File", "file_actions.if_file_exists"),
    "Folder.IfFolderExists.Exists": ("Path", "folder_actions.if_folder_exists"),
}


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
    existence_check = _EXISTENCE_CHECKS.get(header.action_id)
    if existence_check is not None:
        param_name, func_expr = existence_check
        rendered = safe_render(header.params.get(param_name))
        return f"{func_expr}({rendered})" if rendered is not None else None

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
