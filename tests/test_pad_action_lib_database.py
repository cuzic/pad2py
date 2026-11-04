"""`pad_action_lib.database_actions`の単体テスト。

実際のODBC/Oracleドライバは使わず、DB-API 2.0互換という共通契約を検証するために
標準ライブラリの`sqlite3`を注入した`connect=`経由でラッパーのロジックを確認する。
"""
from __future__ import annotations

import sqlite3

import pytest

from dump_daemon.pad_action_lib import database_actions as db


def _sqlite_connect(_connection_string: str) -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


def test_open_connection_wraps_raw_connection() -> None:
    conn = db.open_connection("irrelevant", connect=_sqlite_connect)
    assert isinstance(conn, db.SqlConnectionHandle)
    assert isinstance(conn.raw, sqlite3.Connection)
    db.close_connection(conn)


def test_open_connection_without_connector_raises_native_provider_not_available() -> None:
    def _missing_driver(_cs: str) -> object:
        raise db.NativeProviderNotAvailable("no driver")

    with pytest.raises(db.NativeProviderNotAvailable):
        db.open_connection("irrelevant", connect=_missing_driver)


def test_open_connection_wraps_generic_failures() -> None:
    def _broken(_cs: str) -> object:
        raise RuntimeError("boom")

    with pytest.raises(db.ConnectToDataSourceError):
        db.open_connection("irrelevant", connect=_broken)


def test_execute_sql_statement_select_returns_datatable() -> None:
    conn = db.open_connection("irrelevant", connect=_sqlite_connect)
    conn.raw.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    conn.raw.execute("INSERT INTO t VALUES (1, 'x')")
    conn.raw.commit()

    result = db.execute_sql_statement(conn, "SELECT a, b FROM t")
    assert result == [{"a": 1, "b": "x"}]
    db.close_connection(conn)


def test_execute_sql_statement_non_select_returns_empty_datatable_not_none() -> None:
    conn = db.open_connection("irrelevant", connect=_sqlite_connect)
    conn.raw.execute("CREATE TABLE t (a INTEGER)")
    result = db.execute_sql_statement(conn, "INSERT INTO t VALUES (1)")
    assert result == []
    db.close_connection(conn)


def test_execute_sql_statement_error_wraps_as_sql_statement_error() -> None:
    conn = db.open_connection("irrelevant", connect=_sqlite_connect)
    with pytest.raises(db.SqlStatementError):
        db.execute_sql_statement(conn, "SELECT * FROM nonexistent_table")
    db.close_connection(conn)


def test_connect_and_execute_combines_both_steps() -> None:
    conn, _ = db.connect_and_execute("irrelevant", "CREATE TABLE t (a INTEGER)", connect=_sqlite_connect)
    result = db.execute_sql_statement(conn, "SELECT * FROM t")
    assert result == []
    db.close_connection(conn)


def test_close_connection_swallows_errors() -> None:
    conn = db.SqlConnectionHandle(raw=object())  # .close()を持たないので必ず失敗する
    db.close_connection(conn)  # 例外を投げないことを確認するだけ
