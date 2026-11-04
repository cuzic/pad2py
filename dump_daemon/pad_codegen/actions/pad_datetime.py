"""`DateTime.*`のcodegen。`pad_action_lib.datetime_actions`へ委譲する。

パラメータ名は design/dsl_format_findings.md 知見66で実機キャプチャした
`tests/fixtures/tier1_datetime_folder_clipboard_batch2.txt`から確認済み。
モジュール名は標準ライブラリの`datetime`と衝突しないよう`pad_datetime`にしている
(パッケージ内の他モジュールは常に絶対importのため実害は無いが、紛らわしさを避ける)。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import enum_last, safe_render


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("DateTime."):
        return None
    prefix = INDENT * indent
    p = node.params

    if action_id == "DateTime.GetCurrentDateTime.Local":
        date_format = enum_last(p.get("DateTimeFormat"))
        if date_format is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = datetime_actions.get_current_datetime("
            f"date_time_format={date_format!r})"
        ]

    if action_id == "DateTime.Add":
        value = safe_render(p.get("DateTime"))
        time_to_add = safe_render(p.get("TimeToAdd"))
        time_unit = enum_last(p.get("TimeUnit"))
        if value is None or time_to_add is None or time_unit is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = datetime_actions.add_to_datetime({value}, {time_to_add}, "
            f"time_unit={time_unit!r})"
        ]

    if action_id == "DateTime.Subtract":
        from_date = safe_render(p.get("FromDate"))
        subtract_date = safe_render(p.get("SubstractDate"))
        time_unit = enum_last(p.get("TimeUnit"))
        if from_date is None or subtract_date is None or time_unit is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = datetime_actions.subtract_dates({from_date}, {subtract_date}, "
            f"time_unit={time_unit!r})"
        ]

    return None
