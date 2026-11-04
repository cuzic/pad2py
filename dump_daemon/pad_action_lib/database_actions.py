"""`Database.Actions`(OpenConnection/ExecuteSqlStatement/CloseConnection)のロジック層。

実際のADO/ODBC/OleDb/Oracle接続分岐ロジック自体はこのDLLには無く、コアランタイム側に
あると見られる(未確認)。PADの接続文字列形式(OleDb/ODBC風)はSQLAlchemyのURL構文と
1:1対応しないため、この層では「どのドライバを使うか」を決め打ちせず、DB-API 2.0
互換の`connect(connection_string) -> Connection`呼び出し可能オブジェクトを呼び出し側
から注入できるようにする(既定は`pyodbc`があれば使う、無ければ`NativeProviderNotAvailable`)
——でっち上げた接続文字列変換テーブルは作らない。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .datatable import DataTable, datatable_from_rows
from .errors import PadActionError


class ConnectToDataSourceError(PadActionError):
    pass


class InvalidConnectionStringError(PadActionError):
    pass


class NativeProviderNotAvailable(PadActionError):
    pass


class SqlStatementError(PadActionError):
    pass


@dataclass
class SqlConnectionHandle:
    """不透明な接続ハンドル(「window instance」問題と同種、実行時オブジェクト参照)。"""

    raw: object
    database_type: str = "Other"


def _default_connect(connection_string: str) -> object:
    try:
        import pyodbc  # type: ignore[import-not-found]
    except ImportError as exc:
        raise NativeProviderNotAvailable(
            "no DB-API driver configured; pass connect= explicitly or install pyodbc"
        ) from exc
    return pyodbc.connect(connection_string)


def open_connection(
    connection_string: str,
    database_type: str = "Other",
    provider_library_path: str | None = None,
    *,
    connect: Callable[[str], object] | None = None,
) -> SqlConnectionHandle:
    connector = connect if connect is not None else _default_connect
    try:
        raw = connector(connection_string)
    except NativeProviderNotAvailable:
        raise
    except Exception as exc:
        message = str(exc)
        if "connection string" in message.lower():
            raise InvalidConnectionStringError(message) from exc
        raise ConnectToDataSourceError(message) from exc
    return SqlConnectionHandle(raw=raw, database_type=database_type)


def execute_sql_statement(connection: SqlConnectionHandle, statement: str, timeout: int = 30) -> DataTable:
    try:
        cursor = connection.raw.cursor()
        if hasattr(cursor, "timeout"):
            cursor.timeout = timeout
        cursor.execute(statement)
        if cursor.description is None:
            # INSERT/UPDATE等の非SELECTでは空のDataTable(`null`ではない)。
            return []
        columns = [col[0] for col in cursor.description]
        rows = [list(row) for row in cursor.fetchall()]
        return datatable_from_rows(columns, rows)
    except Exception as exc:
        raise SqlStatementError(str(exc)) from exc


def connect_and_execute(
    connection_string: str,
    statement: str,
    database_type: str = "Other",
    provider_library_path: str | None = None,
    timeout: int = 30,
    *,
    connect: Callable[[str], object] | None = None,
) -> tuple[SqlConnectionHandle, DataTable]:
    connection = open_connection(connection_string, database_type, provider_library_path, connect=connect)
    result = execute_sql_statement(connection, statement, timeout)
    return connection, result


def close_connection(connection: SqlConnectionHandle) -> None:
    # このクラス自体には[Throws]が無い(失敗が[Throws]タグとして正規化されない)。
    # 実際のクローズ確認ができなくても例外にはならず警告ログのみという記述と整合させ、
    # ベストエフォートで閉じて失敗は静かに無視する(Cmd.Actions の Close と同じ方針)。
    try:
        connection.raw.close()
    except Exception:
        pass
