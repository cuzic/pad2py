"""`Database.*`のcodegen。`pad_action_lib.database_actions`へ委譲する。

パラメータ名は design/dsl_format_findings.md 知見70/知見71で実機キャプチャした
`tests/fixtures/tier1_crypto_database_batch7.txt`・`tier1_web_xml_batch8.txt`から
確認済み。`Database.ExecuteSqlStatement.Execute`の`Statement`は知見74でパーサーが
空のバックティック文字列``を正しく空文字列として解釈するようになったため結線できる
(実機キャプチャではSQL文を編集しなかったため常に空文字列)。

知見139(`ActionSelectorBase`一括列挙監査をDatabase.Actions.dllに適用): `OpenConnection`
クラス(Name="Connect")は`OpenConnectionOtherSelector`(ActionName="Connect"、既存結線)
と`OpenConnectionOracleSelector`(ActionName="ConnectOracle"、新規結線)の兄弟セレクタを
持つ——両方とも同一クラスの`ConnectionString`プロパティを共有すると確認済み(VM上の
プロパティ一覧で確認)。`ExecuteSqlStatement`クラス(Name=""、型名がそのままCategory)も
同様に`ExecuteSelector`(既存結線)に加え`ConnectAndExecuteSelector`/
`ConnectAndExecuteOracleSelector`の兄弟セレクタを持ち、同一クラスが`ConnectionString`/
`Statement`/`Timeout`/`Result`を共有する——`pad_action_lib.database_actions.
connect_and_execute()`は既に実装済み(おそらく当初から用意されていたが未結線だった)
だったため、そのまま新規結線できた。Oracle版は選択した時点でモードが固定される
(`DatabaseType`パラメータ自体はDSL上に現れない——知見71の実機キャプチャが
`DatabaseType`省略時のデフォルト("Other")のみだったため、既存の`Connect.Connect`も
元々このパラメータを読んでいない、その前例を維持する)。接続+実行後の`Connection`の
別出力は無く(`Execute`セレクタと同じ単一`output_var`のみ)、という前提も既存セレクタと
同じクラスである事実から推測した(実機キャプチャでの確証は無い——`DatabaseType`を
明示指定した場合の挙動・ConnectAndExecuteの出力束縛の正確な形は依然未確認のまま)。
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

    if action_id == "Database.Connect.ConnectOracle":
        # 知見139: `OpenConnection`クラスの兄弟セレクタ(Oracle専用モード)。
        connection_string = safe_render(p.get("ConnectionString"))
        if connection_string is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = database_actions.open_connection("
            f"{connection_string}, database_type='Oracle')"
        ]

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

    if action_id in (
        "Database.ExecuteSqlStatement.ConnectAndExecute",
        "Database.ExecuteSqlStatement.ConnectAndExecuteOracle",
    ):
        # 知見139: `ExecuteSqlStatement`クラスの兄弟セレクタ(接続文字列から直接実行)。
        connection_string = safe_render(p.get("ConnectionString"))
        statement = safe_render(p.get("Statement"))
        timeout = safe_render(p.get("Timeout"))
        if connection_string is None or statement is None or timeout is None or not node.output_var:
            return None
        database_type = "Oracle" if action_id.endswith("Oracle") else "Other"
        return [
            f"{prefix}{node.output_var} = database_actions.connect_and_execute("
            f"{connection_string}, {statement}, database_type={database_type!r}, "
            f"timeout={timeout})[1]"
        ]

    return None
