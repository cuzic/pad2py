"""`Cmd.*`のcodegen。`pad_action_lib.cmd_actions`へ委譲する。

パラメータ名は design/dsl_format_findings.md 知見72で実機キャプチャした
`tests/fixtures/tier1_cmd_batch9.txt`から確認済み。`Session`変数は
`pad_action_lib.cmd_actions.CmdSession`インスタンスを保持する想定で、
`Open`以外のアクションはそのインスタンスのメソッド呼び出しに変換する
(`cmd_actions`モジュール自体の再importは不要)。

`Cmd.WaitForText`は知見72で確認した通り`WaitActionRecord`(`WAIT (...) FOR`構文)
ではなく通常の`ActionRecord`としてシリアライズされる——`Timeout`は普通の
パラメータであり、`[WaitAction]`カテゴリの無期限ポーリング前提
(`actions.wait`)とは別物として扱う。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import safe_render


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("Cmd."):
        return None
    prefix = INDENT * indent
    p = node.params

    if action_id == "Cmd.Open.Open":
        directory = safe_render(p.get("Directory"))
        if directory is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = cmd_actions.open_cmd_session({directory})"]

    if action_id == "Cmd.Write":
        session = safe_render(p.get("Session"))
        command = safe_render(p.get("Command"))
        send_enter = safe_render(p.get("SendEnter"))
        if session is None or command is None or send_enter is None:
            return None
        return [f"{prefix}{session}.write({command}, send_enter={send_enter})"]

    if action_id == "Cmd.ReadFromCmdSession.Read":
        session = safe_render(p.get("Session"))
        if session is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = {session}.read()"]

    if action_id == "Cmd.WaitForText":
        session = safe_render(p.get("Session"))
        text = safe_render(p.get("Text"))
        is_regex = safe_render(p.get("IsRegEx"))
        ignore_case = safe_render(p.get("IgnoreCase"))
        timeout = safe_render(p.get("Timeout"))
        if None in (session, text, is_regex, ignore_case, timeout):
            return None
        return [
            f"{prefix}{session}.wait_for_text({text}, timeout={timeout}, is_regex={is_regex}, "
            f"ignore_case={ignore_case})"
        ]

    if action_id == "Cmd.Close":
        session = safe_render(p.get("Session"))
        if session is None:
            return None
        return [f"{prefix}{session}.close()"]

    return None
