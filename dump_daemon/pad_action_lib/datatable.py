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


def _csv_as_number(value: str) -> int | float | str:
    # 知見103(実機確認済み): 桁区切りコンマ(`"1,000"`)もこのCSV読み込みサブシステムでは
    # 数値(`1000`)として認識される(知見102の`+`/`=`演算子と同じ挙動)ため、`int()`/
    # `float()`に渡す前にコンマを取り除く(元の値にコンマが無ければ影響しない)。
    cleaned = value.replace(",", "")
    try:
        return int(cleaned)
    except ValueError:
        pass
    try:
        parsed = float(cleaned)
    except ValueError:
        return value
    # 知見100(実機確認済み): 指数表記等(`"1e2"`)は`int()`でパースできず`float()`経由に
    # なるが、整数値になる場合は.NETの既定表示(小数点無し、`"100"`)と一致させるため
    # Pythonの`int`に変換する(`str(100.0)`は`"100.0"`になり実機の`"100"`と食い違う)。
    return int(parsed) if parsed.is_integer() else parsed


def datatable_from_csv_text(
    text: str,
    delimiter: str = ",",
    first_line_contains_column_names: bool = True,
    read_fields_as_text: bool = True,
    trim_fields: bool = True,
) -> DataTable:
    """標準/カスタム区切りCSVテキストを`DataTable`に変換する。

    design/dsl_format_findings.md 知見84(実機確認済み): `first_line_contains_column_names=
    False`の場合、列名は実機と同じ`"Column#1"`/`"Column#2"`...(1始まり、`#`付き)が
    割り当てられ、1行目もヘッダーとして切り出さず全ての行がデータ行として扱われる。

    知見92(実機確認済み): `read_fields_as_text=False`の場合、数値として解釈できる
    フィールド(`"007"`等)は実際に数値型へ変換される(`int`→`float`の順でパースを試みる、
    先頭ゼロは失われる——`"007"`は`7`になる)。数値として解釈できないフィールドは文字列
    のまま変化しない。既定の`True`では常に文字列のまま保持する(従来通り)。

    知見93(実機確認済み): `trim_fields=True`(実機の既定値)の場合、各フィールドの
    前後の空白が除去される(`" 7 , abc "`→`"7"`/`"abc"`)。`False`では空白を保持する
    (`" 7 "`/`" abc "`のまま)。トリム処理は数値変換より先に適用する(`int()`/`float()`
    自体も前後の空白を無視するため実害は無いが、文字列のまま保持する場合に影響する)。
    知見106(実機確認済み): `first_line_contains_column_names=True`時のヘッダー行
    自体もトリム対象になる(`" Name "`→`"Name"`)——ヘッダー行にも本体データと同じ
    `.strip()`を適用する現在の実装が正しいと確定した。
    """
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return []
    if trim_fields:
        rows = [[cell.strip() for cell in row] for row in rows]
    if first_line_contains_column_names:
        header, *data = rows
    else:
        header = [f"Column#{i + 1}" for i in range(len(rows[0]))]
        data = rows
    if not read_fields_as_text:
        data = [[_csv_as_number(cell) for cell in row] for row in data]
    return [dict(zip(header, row)) for row in data]


def datatable_to_csv_text(
    table: DataTable, delimiter: str = ",", include_column_names: bool = True
) -> str:
    """`DataTable`をCSVテキストに変換する(改行はWindows固定の`\\r\\n`)。

    `include_column_names=False`の場合はヘッダー行を省略する(design/dsl_format_findings.md
    知見84、`IncludeColumnNames: False`の実機DSLで確認済み)。
    """
    cols = columns_of(table)
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter, lineterminator="\r\n")
    if include_column_names:
        writer.writerow(cols)
    for row in table:
        writer.writerow([row.get(col, "") for col in cols])
    return buf.getvalue()
