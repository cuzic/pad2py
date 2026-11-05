"""`Database.*`のcodegen。`pad_action_lib.database_actions`へ委譲する。

パラメータ名は design/dsl_format_findings.md 知見70/知見71で実機キャプチャした
`tests/fixtures/tier1_crypto_database_batch7.txt`・`tier1_web_xml_batch8.txt`から
確認済み。`Database.ExecuteSqlStatement.Execute`の`Statement`は知見74でパーサーが
空のバックティック文字列``を正しく空文字列として解釈するようになったため結線できる
(実機キャプチャではSQL文を編集しなかったため常に空文字列)。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import safe_render


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("Database."):
        return None
    prefix = INDENT * indent
    p = node.params

    if action_id == "Database.Connect.Connect":
        connection_string = safe_render(p.get("ConnectionString"))
        if connection_string is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = database_actions.open_connection({connection_string})"]

    if action_id == "Database.Close":
        connection = safe_render(p.get("Connection"))
        if connection is None:
            return None
        return [f"{prefix}database_actions.close_connection({connection})"]

    if action_id == "Database.ExecuteSqlStatement.Execute":
        connection = safe_render(p.get("Connection"))
        statement = safe_render(p.get("Statement"))
        timeout = safe_render(p.get("Timeout"))
        if connection is None or statement is None or timeout is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = database_actions.execute_sql_statement("
            f"{connection}, {statement}, timeout={timeout})"
        ]

    return None
