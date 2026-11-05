"""`IfActionRecord`/`ElseIfActionRecord`(`[ConditionAction]`カテゴリ)の条件式codegen。

現状`UIAutomation.IfWindow.*`ファミリーのみ対応(複雑な設定モードを持つ`IfImage`/
`IfWindowContains`等は意図的に未対応のまま`None`を返す)。
"""
from __future__ import annotations

from ...pad_dsl import ElseIfActionRecord, IfActionRecord, UiElementRef, VarRef
from ..context import CodegenContext
from ..render import render_value
from ..selectors import _build_pywinauto_selector_expr
from ._support import safe_render

# design/dsl_format_findings.md 知見68/69(実機確認済み): `File.IfFile.Exists`/
# `Folder.IfFolderExists.Exists`はUI要素セレクタを一切使わない単純な存在チェックで、
# `pad_action_lib`の対応する関数呼び出し1つに素直に変換できる(`IfImage`/
# `IfWindowContains`のような複数の設定可能なサブモードが無い)。
# `File.IfFile.DoesNotExist`/`Folder.IfFolderExists.DoesNotExist`は知見136・137
# (`ActionSelectorBase`一括列挙の監査で発見)で追加した兄弟セレクタ——`Exists`の単純な
# 否定(`FileExistsSelector`/`FileDoesNotExistSelector`、`FolderExistsSelector`/
# `FolderDoesNotExistSelector`はいずれも`IfFileAction`/`IfFolderExistsAction`の
# `CheckMode`を切り替えるだけの同一構造とVM上で確認済み)。`Folder`側は`FolderExistsSelector`
# という名前に`IfFolder`という部分文字列を含まないため、以前の型名部分一致での監査では
# 見逃していた(`ActionSelectorBase`を基底型として辿る正しい列挙方法で知見137で発見)。
_EXISTENCE_CHECKS: dict[str, tuple[str, str, bool]] = {
    "File.IfFile.Exists": ("File", "file_actions.if_file_exists", False),
    "File.IfFile.DoesNotExist": ("File", "file_actions.if_file_exists", True),
    "Folder.IfFolderExists.Exists": ("Path", "folder_actions.if_folder_exists", False),
    "Folder.IfFolderExists.DoesNotExist": ("Path", "folder_actions.if_folder_exists", True),
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
        param_name, func_expr, negate = existence_check
        rendered = safe_render(header.params.get(param_name))
        if rendered is None:
            return None
        call = f"{func_expr}({rendered})"
        return f"not {call}" if negate else call

    if not header.action_id.startswith("UIAutomation.IfWindow."):
        return None
    mode_suffix = header.action_id.rsplit(".", 1)[-1]

    # design/dsl_format_findings.md 知見121(decompile確認済み): `IfWindow`も
    # `GetWindow`等(知見117〜120)と同じ3セレクタ構造(`Control`/`WindowInstance`/
    # `Title`+`Class`ベース)を、`IsOpen`/`IsNotOpen`/`IsFocused`/`IsNotFocused`の
    # 4モードそれぞれに持つ(計12セレクタ)。`Control`ベースの4つのみ結線済みだった
    # ため、`ByInstanceOrHandle`/`ByTitleClass`の兄弟セレクタ(計8つ)も同じ
    # `exists()`/`is_active()`ロジックへ結線する——ウィンドウ参照の取得元が
    # 違うだけで、以降の真偽値ロジックは完全に同一。
    if mode_suffix.endswith("ByInstanceOrHandle"):
        mode = mode_suffix[: -len("ByInstanceOrHandle")]
        window_instance = header.params.get("WindowInstance")
        window_expr = render_value(window_instance) if isinstance(window_instance, VarRef) else None
    elif mode_suffix.endswith("ByTitleClass"):
        mode = mode_suffix[: -len("ByTitleClass")]
        title = header.params.get("Title")
        window_class = header.params.get("Class")
        window_expr = (
            f"Desktop(backend='uia').window(title={render_value(title)})"
            if isinstance(title, str) and window_class == ""
            else None
        )
    else:
        mode = mode_suffix
        window = header.params.get("Window")
        window_expr = (
            _build_pywinauto_selector_expr(window.path, ctx) if isinstance(window, UiElementRef) else None
        )
    if window_expr is None:
        return None
    exists_expr = f"{window_expr}.exists()"
    if mode == "IsOpen":
        return exists_expr
    if mode == "IsNotOpen":
        return f"not {exists_expr}"
    if mode in ("IsFocused", "IsNotFocused"):
        active_expr = f"({exists_expr} and {window_expr}.wrapper_object().is_active())"
        return active_expr if mode == "IsFocused" else f"not {active_expr}"
    return None
