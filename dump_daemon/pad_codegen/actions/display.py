"""`Display.ShowMessageDialog`のcodegen。`pad_action_lib.display_actions`へ委譲する。

design/dsl_format_findings.md 知見184/185: `ShowMessage`(`CloseAutomatically=False`
固定)は実装済み。`ShowMessageWithTimeout`(`CloseAutomatically=True`固定)は
`pad_action_lib.display_actions.show_message_dialog_with_timeout()`側で
`NotImplementedError`に委ねるため、ここでは分岐を追加しない(安全にTODOへ倒れる)。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import enum_last, safe_render


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    if node.action_id != "Display.ShowMessageDialog.ShowMessage":
        return None
    prefix = INDENT * indent
    p = node.params

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
