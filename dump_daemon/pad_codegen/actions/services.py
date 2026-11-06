"""`Services.Start`/`Stop`/`Pause`/`Resume`のcodegen。`pad_action_lib.services_actions`へ委譲する。

design/dsl_format_findings.md 知見187: `Microsoft.Flow.RPA.Desktop.Modules.
Services.Actions.dll`に`[Action(Name = "Start"/"Stop"/"Pause"/"Resume")]`で
定義された4つのフラットなaction(兄弟セレクタ無し、知見162/179で確認済みの
「`Id`属性が無ければ`Name`属性がEffectiveId」というSDK一般ルールを適用)。
いずれも`ServiceName`(string)の1入力のみ、出力変数は無い。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import safe_render

_FUNC_BY_ACTION_ID = {
    "Services.Start": "start_service",
    "Services.Stop": "stop_service",
    "Services.Pause": "pause_service",
    "Services.Resume": "resume_service",
}


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    func = _FUNC_BY_ACTION_ID.get(node.action_id)
    if func is None:
        return None
    prefix = INDENT * indent
    service_name = safe_render(node.params.get("ServiceName"))
    if service_name is None:
        return None
    return [f"{prefix}services_actions.{func}({service_name})"]
