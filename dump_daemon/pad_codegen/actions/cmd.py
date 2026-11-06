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

知見139(`ActionSelectorBase`一括列挙監査をCmd.Actions.dllに適用): `ReadFromCmdSession`
クラスは既存結線の`Read`(`CmdOutput`/`CmdError`を1本に合流、`SplitOutputAndError=False`)
に加え、兄弟セレクタ`ReadAndSplit`(`SplitOutputAndError=True`、`CmdOutput`/`CmdError`を
別々の出力に分ける)を持つ——既存の`CmdSession.read(split_output_and_error=True)`が
そのまま対応できるため新規結線した。`OpenCmdSession`クラスの兄弟セレクタ
`OpenWithCodePage`(`ChangeCodePage: Boolean`/`Encoding: Encoding`という型付き列挙の
組み合わせ)は、VM上のプロパティ確認で`Encoding`が単純な文字列ではなく専用の`Encoding`
型だと判明し、その列挙値とPythonコーデック名/Windows `chcp`番号との対応関係が実機未確認
のため今回は見送った(既存の`open_cmd_session(encoding: str = "utf-8")`がPythonの
テキストデコードと`chcp {encoding}`コマンド引数の両方にこの1つの文字列を再利用している
点も、実際のPADの`chcp`呼び出し形式との整合性が未検証のまま残っている)。
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

    if action_id == "Cmd.ReadFromCmdSession.ReadAndSplit":
        # 知見139: `Read`の兄弟セレクタ(`SplitOutputAndError=True`、標準出力/標準エラーを
        # 別々の出力変数に分ける)。
        session = safe_render(p.get("Session"))
        output_var = node.output_vars.get("CmdOutput")
        error_var = node.output_vars.get("CmdError")
        if session is None or not output_var or not error_var:
            return None
        return [
            f"{prefix}{output_var}, {error_var} = {session}.read(split_output_and_error=True)"
        ]

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
