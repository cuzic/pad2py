"""`Clipboard.*`のcodegen。`pad_action_lib.clipboard_actions`へ委譲する。

パラメータ名は design/dsl_format_findings.md 知見66で実機キャプチャした
`tests/fixtures/tier1_datetime_folder_clipboard_batch2.txt`から確認済み。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import safe_render


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("Clipboard."):
        return None
    prefix = INDENT * indent
    p = node.params

    if action_id == "Clipboard.GetText":
        if not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = clipboard_actions.get_clipboard_text()"]

    if action_id == "Clipboard.SetText":
        text = safe_render(p.get("Text"))
        if text is None:
            return None
        return [f"{prefix}clipboard_actions.set_clipboard_text({text})"]

    if action_id == "Clipboard.Clear":
        return [f"{prefix}clipboard_actions.clear_clipboard()"]

    return None
