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

    if action_id == "DateTime.GetCurrentDateTime.Current":
        # design/dsl_format_findings.md 知見138: `Local`の兄弟セレクタ(`Current`は実機で
        # `[Deprecated]`属性付き、`Specific`モードの別名——decompileで確認済み)。
        date_format = enum_last(p.get("DateTimeFormat"))
        offset = safe_render(p.get("Offset"))
        if date_format is None or offset is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = datetime_actions.get_current_datetime("
            f"date_time_format={date_format!r}, time_zone_mode='Specific', offset={offset})"
        ]

    if action_id == "DateTime.GetCurrentDateTime.Windows":
        # design/dsl_format_findings.md 知見116・138: `TimeZoneLocation`は`TimeZoneMode`列挙と
        # 同じ命名規則(スペース無しの141値)で、`get_current_datetime()`の
        # `_TIME_ZONE_LOCATION_TO_WINDOWS_ID`がそのままキーとして受け付ける。
        date_format = enum_last(p.get("DateTimeFormat"))
        tz_location = enum_last(p.get("TimeZoneLocation"))
        if date_format is None or tz_location is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = datetime_actions.get_current_datetime("
            f"date_time_format={date_format!r}, time_zone_mode='Windows', "
            f"time_zone_location={tz_location!r})"
        ]

    if action_id == "DateTime.GetCurrentDateTime.CustomOffset":
        date_format = enum_last(p.get("DateTimeFormat"))
        custom_offset = safe_render(p.get("CustomOffset"))
        if date_format is None or custom_offset is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = datetime_actions.get_current_datetime("
            f"date_time_format={date_format!r}, time_zone_mode='Custom', "
            f"custom_offset={custom_offset}, input_type='Offset')"
        ]

    if action_id == "DateTime.GetCurrentDateTime.CustomTimeZone":
        # design/dsl_format_findings.md 知見138: `CustomTimeZone`はルックアップテーブルを
        # 経由せず、.NETの`TimeZoneInfo.Id`形式の文字列(スペースを含む、例:
        # `"Tokyo Standard Time"`)をそのまま渡す経路だとVM上の直接呼び出しで確認済み。
        date_format = enum_last(p.get("DateTimeFormat"))
        custom_timezone = safe_render(p.get("CustomTimeZone"))
        if date_format is None or custom_timezone is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = datetime_actions.get_current_datetime("
            f"date_time_format={date_format!r}, time_zone_mode='Custom', "
            f"custom_timezone={custom_timezone}, input_type='Windows')"
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
