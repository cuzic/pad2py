"""PADの`DataTable`型の共通表現。

PADのDataTableはExcelのようにセル単位で値を持つ(列全体が単一の型に推論されるわけ
ではない)。`pandas.DataFrame`は列単位で型推論するため型混在列で食い違う可能性が
あり、Variables.Actions/File.Actions双方のCSV相互変換・DataTable CRUD系アクションは
この`DataTable`(行の辞書のリスト、列順序は各行の辞書のキー順序で保持)を共通の
中間表現として使う。
"""
from __future__ import annotations

import csv
import io

Row = dict[str, object]
DataTable = list[Row]


def columns_of(table: DataTable) -> list[str]:
    """先頭行のキー順序を列順序として返す(空テーブルは空リスト)。"""
    return list(table[0].keys()) if table else []


def datatable_from_rows(columns: list[str], rows: list[list[object]]) -> DataTable:
    """列名リスト+行ごとの値リストから`DataTable`を組み立てる(CSV読み込み等で使う)。"""
    return [dict(zip(columns, row)) for row in rows]


def rows_of(table: DataTable, columns: list[str] | None = None) -> list[list[object]]:
    """`DataTable`を列名リスト基準の値リストの並びに変換する(CSV書き出し等で使う)。"""
    cols = columns if columns is not None else columns_of(table)
    return [[row.get(col, "") for col in cols] for row in table]


def datatable_from_csv_text(text: str, delimiter: str = ",") -> DataTable:
    """標準/カスタム区切りCSVテキスト(1行目をヘッダーとして扱う)を`DataTable`に変換する。"""
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return []
    header, *data = rows
    return [dict(zip(header, row)) for row in data]


def datatable_to_csv_text(table: DataTable, delimiter: str = ",") -> str:
    """`DataTable`をヘッダー行付きCSVテキストに変換する(改行はWindows固定の`\\r\\n`)。"""
    cols = columns_of(table)
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(cols)
    for row in table:
        writer.writerow([row.get(col, "") for col in cols])
    return buf.getvalue()
