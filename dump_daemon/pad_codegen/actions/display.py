"""`Display.ShowMessageDialog`/`Display.SelectFolder`のcodegen。
`pad_action_lib.display_actions`へ委譲する。

design/dsl_format_findings.md 知見184/185: `ShowMessage`(`CloseAutomatically=False`
固定)は実装済み。`ShowMessageWithTimeout`(`CloseAutomatically=True`固定)は
`pad_action_lib.display_actions.show_message_dialog_with_timeout()`側で
`NotImplementedError`に委ねるため、ここでは分岐を追加しない(安全にTODOへ倒れる)。

知見185追補: `Display.SelectFolder`(`SelectFolderDialog`、兄弟セレクタの無い
フラットなaction、`[Action(Name = "SelectFolder")]`——知見162/179で確認済みの
「`Id`属性が無い場合は`Name`がEffectiveIdになる」というSDK一般ルールをそのまま
適用)は`SelectedFolder`/`ButtonPressed`の2つの名前付き出力を持つ。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import enum_last, safe_render


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    prefix = INDENT * indent
    p = node.params

    if node.action_id == "Display.ShowMessageDialog.ShowMessage":
        message = safe_render(p.get("Message", ""))
        title = safe_render(p.get("Title", ""))
        icon = enum_last(p.get("Icon")) or "None"
        buttons = enum_last(p.get("Buttons")) or "OK"
        default_button = enum_last(p.get("DefaultButton")) or "Button1"
        is_topmost = safe_render(p.get("IsTopMost", False))
        if None in (message, title, is_topmost):
            return None

        call = (
            f"display_actions.show_message_dialog({message}, {title}, "
            f"icon={icon!r}, buttons={buttons!r}, default_button={default_button!r}, "
            f"is_topmost={is_topmost})"
        )
        if node.output_var:
            return [f"{prefix}{node.output_var} = {call}"]
        return [f"{prefix}{call}"]

    if node.action_id == "Display.SelectFolder":
        description = safe_render(p.get("Description", ""))
        initial_directory = safe_render(p.get("InitialDirectory", ""))
        is_topmost = safe_render(p.get("IsTopMost", False))
        folder_var = node.output_vars.get("SelectedFolder")
        button_var = node.output_vars.get("ButtonPressed")
        if None in (description, initial_directory, is_topmost) or not (folder_var or button_var):
            return None

        call = (
            f"display_actions.show_select_folder_dialog({description}, {initial_directory}, "
            f"is_topmost={is_topmost})"
        )
        if folder_var and button_var:
            return [f"{prefix}{folder_var}, {button_var} = {call}"]
        if folder_var:
            return [f"{prefix}{folder_var}, _ = {call}"]
        return [f"{prefix}_, {button_var} = {call}"]

    return None
