"""`Variables.Actions`(数値・リスト・DataTable・JSON)のロジック層。

PADのDataTable/List系アクションの多くは対象コレクションを`[InputArgument(Mutable
= true)]`で受け取る——つまり既存の変数をその場で変更する。この層でもその意味論に
合わせ、リスト/DataTableを引数として受け取り、戻り値を返す代わりに**その場で変更
する**関数として実装する(新しいリストを作って返す関数と誤って混用しないよう、
全てのin-place関数は戻り値`None`に統一する)。

`SubtractLists`/`FindCommonListItems`が使うPAD独自の汎用比較エンジン
(`ComparisonCalculator.Compare`)は design/dsl_format_findings.md 知見85で実機確認
済み(文字列は大文字小文字を区別するが、数値を表す文字列と数値は型をまたいで
等価)。知見88で`IF`/`SET`の`=`/`<>`演算子も同じ規則に従うことを実機確認済み
(`pad_action_lib.expr_runtime.pad_equal()`に共通実装、`pad_codegen`側もこれを使うよう
結線済み)。`FilterDataTableAction`のフィルタ条件(`FilterParameters`)のDataTableスキーマ
(`COLUMN`/`OPERATOR`/`VALUE`/`RULE`列)は知見90でdecompile+実機確認済みのため結線済み
(`filter_datatable()`)。`JoinDataTableAction`の結合条件(`JoinParameters`)のDataTable
スキーマ(`"COLUMN 1"`/`OPERATOR`/`"COLUMN 2"`列)も知見91で同じ手法(decompile+実機
確認)で判明したため結線済み(`join_datatable()`)。
"""
from __future__ import annotations

import json
import math

from .expr_runtime import pad_equal as _pad_compare_equal
import random as _random

from .datatable import DataTable, Row
from .datatable import datatable_from_csv_text as datatable_from_csv_text
from .datatable import datatable_to_csv_text as datatable_to_csv_text

# --- 数値系 ---------------------------------------------------------------


def truncate_number(number: float, mode: str = "GetIntegerPart", decimal_digits: int = 0) -> float:
    if mode == "GetIntegerPart":
        return math.trunc(number)
    if mode == "GetDecimalPart":
        return number - math.trunc(number)
    if mode == "RoundAtNthDecimalDigits":
        return round(number, decimal_digits)
    raise ValueError(f"Unknown TruncateNumber mode: {mode!r}")


def generate_random_number(
    minimum: int,
    maximum: int,
    count: int = 1,
    allow_duplicates: bool = True,
    *,
    rng: object | None = None,
) -> list[int]:
    rand = rng if rng is not None else _random
    if not allow_duplicates:
        pool_size = maximum - minimum + 1
        if count > pool_size:
            # [Throws]タグの外側で素の例外として伝播する(他アクションと不整合)。
            raise ValueError("count exceeds the number of unique values available in range")
        return list(rand.sample(range(minimum, maximum + 1), count))
    return [rand.randint(minimum, maximum) for _ in range(count)]


def increase_variable(value: float, increment: float = 1) -> float:
    return value + increment


def decrease_variable(value: float, decrement: float = 1) -> float:
    return value - decrement


# --- リスト系 ---------------------------------------------------------------


def create_new_list() -> list:
    return []


def add_item_to_list(items: list, item: object) -> None:
    items.append(item)


def remove_item_from_list_by_index(items: list, index: int) -> None:
    del items[index]


def remove_item_from_list_by_value(items: list, value: object) -> None:
    items.remove(value)


def clear_list(items: list) -> None:
    items.clear()


def reverse_list(items: list) -> None:
    items.reverse()


def shuffle_list(items: list, *, rng: object | None = None) -> None:
    (rng if rng is not None else _random).shuffle(items)


def merge_lists(target: list, other: list) -> None:
    target.extend(other)


def subtract_lists(items: list, other: list) -> list:
    return [item for item in items if not any(_pad_compare_equal(item, o) for o in other)]


def find_common_list_items(items: list, other: list) -> list:
    return [item for item in items if any(_pad_compare_equal(item, o) for o in other)]


def remove_duplicate_items_from_list(items: list, ignore_case: bool = False) -> None:
    # IgnoreCaseは全要素が文字列の場合のみ有効、それ以外は黙って無視する。
    use_ignore_case = ignore_case and all(isinstance(v, str) for v in items)
    seen: set = set()
    deduped: list = []
    for value in items:
        key = value.lower() if use_ignore_case else value
        if key not in seen:
            seen.add(key)
            deduped.append(value)
    items[:] = deduped


def sort_list(items: list, descending: bool = False, keys: list[str] | None = None) -> None:
    if keys:
        items.sort(key=lambda item: tuple(item[k] for k in keys), reverse=descending)
    else:
        items.sort(reverse=descending)


# --- DataTable系 -------------------------------------------------------------


def create_new_datatable(source: DataTable) -> DataTable:
    return [dict(row) for row in source]


def clear_datatable(table: DataTable) -> None:
    table.clear()


def add_row_to_datatable(table: DataTable, row: Row) -> None:
    table.append(dict(row))


def delete_row_from_datatable(table: DataTable, index: int) -> None:
    del table[index]


def modify_datatable_item(table: DataTable, row_index: int, column: str, value: object) -> None:
    table[row_index][column] = value


def _cell_matches(cell: object, find_value: str, is_regex: bool, ignore_case: bool, entire_cell: bool) -> bool:
    import re

    text = str(cell)
    if is_regex:
        flags = re.IGNORECASE if ignore_case else 0
        pattern = f"^{find_value}$" if entire_cell else find_value
        return re.search(pattern, text, flags=flags) is not None
    haystack = text.lower() if ignore_case else text
    needle = find_value.lower() if ignore_case else find_value
    return haystack == needle if entire_cell else needle in haystack


def find_or_replace_in_datatable(
    table: DataTable,
    find_value: str,
    replace_value: str,
    *,
    is_regex: bool = False,
    ignore_case: bool = False,
    entire_cell: bool = False,
    column: str | None = None,
) -> int:
    import re

    replaced = 0
    for row in table:
        target_columns = [column] if column is not None else list(row.keys())
        for col in target_columns:
            if col not in row:
                continue
            if _cell_matches(row[col], find_value, is_regex, ignore_case, entire_cell):
                text = str(row[col])
                if is_regex:
                    flags = re.IGNORECASE if ignore_case else 0
                    row[col] = re.sub(find_value, replace_value, text, flags=flags)
                elif entire_cell:
                    row[col] = replace_value
                else:
                    if ignore_case:
                        row[col] = re.sub(re.escape(find_value), replace_value, text, flags=re.IGNORECASE)
                    else:
                        row[col] = text.replace(find_value, replace_value)
                replaced += 1
    return replaced


def find_item_in_datatable_everywhere(
    table: DataTable,
    value_to_find: str,
    *,
    all_matches: bool = True,
    match_case: bool = False,
    match_entire_cell_contents: bool = False,
) -> list[tuple[int, int]]:
    """design/dsl_format_findings.md 知見89で実機確認済みの出力契約。

    `DataTableMatches`は`(行インデックス, 列インデックス)`の0始まりペアのリストで、
    行→列の順で走査して見つかった順に並ぶ。`AllMatches: False`でも(スカラーではなく)
    最初の1件だけを含むリストのまま返る(実機のテキスト直列化`"0, 0"`は要素数1の
    リストと要素数2のリスト`"0, 0\\n1, 0"`で同じ"行, 列"形式が繰り返されるのみで、
    型が変わる兆候は無かった)。
    """
    matches: list[tuple[int, int]] = []
    for row_idx, row in enumerate(table):
        for col_idx, cell in enumerate(row.values()):
            if _cell_matches(cell, value_to_find, False, not match_case, match_entire_cell_contents):
                matches.append((row_idx, col_idx))
                if not all_matches:
                    return matches
    return matches


def delete_empty_rows_from_datatable(table: DataTable) -> None:
    table[:] = [row for row in table if any(str(v).strip() for v in row.values())]


def delete_duplicate_rows_from_datatable(table: DataTable) -> None:
    seen: set = set()
    deduped: list[Row] = []
    for row in table:
        key = tuple(sorted(row.items()))
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    table[:] = deduped


def add_column_to_datatable(table: DataTable, column: str, default_value: object = "") -> None:
    for row in table:
        row[column] = default_value


def delete_column_from_datatable(table: DataTable, column: str) -> None:
    for row in table:
        row.pop(column, None)


def sort_datatable(table: DataTable, column: str, descending: bool = False) -> None:
    table.sort(key=lambda row: row.get(column), reverse=descending)


def merge_datatables(target: DataTable, other: DataTable) -> None:
    target.extend(dict(row) for row in other)


def _filter_column_type(table: DataTable, column: str) -> type | None:
    seen: type | None = None
    for row in table:
        value = row.get(column)
        if value is None:
            continue
        value_type = type(value)
        if seen is None:
            seen = value_type
        elif value_type is not seen:
            raise ValueError(f"Column {column!r} has mixed types: {seen} vs {value_type}")
    return seen


def _filter_text_equal(a: object, b: object, match_case: bool) -> bool:
    if isinstance(a, str) and isinstance(b, str) and not match_case:
        return a.lower() == b.lower()
    return a == b


def _filter_condition_matches(row: Row, condition: Row, column_types: dict, match_case: bool) -> bool:
    column = str(condition.get("COLUMN"))
    operator = str(condition.get("OPERATOR"))
    value = condition.get("VALUE")
    cell = row.get(column)
    if operator == "IsBlank":
        return cell is None
    if operator == "IsNotBlank":
        return cell is not None
    if operator == "IsEmpty":
        return cell is None or str(cell) == ""
    if operator == "IsNotEmpty":
        return not (cell is None or str(cell) == "")
    if operator in ("Equal", "NotEqual"):
        # 知見98で実機確認済み: ReadFieldsAsText: Falseで数値型に変換した列を文字列の
        # VALUEでEqualフィルタすると0件になる(型不一致は常に不一致)。
        type_mismatch = cell is not None and value is not None and type(cell) is not type(value)
        if operator == "Equal":
            return False if type_mismatch else _filter_text_equal(cell, value, match_case)
        return True if type_mismatch else (cell is None or not _filter_text_equal(cell, value, match_case))
    if operator in ("GreaterThan", "GreaterThanOrEqual", "LessThan", "LessThanOrEqual"):
        if cell is None:
            return False
        if operator == "GreaterThan":
            return cell > value  # type: ignore[operator]
        if operator == "GreaterThanOrEqual":
            return cell >= value  # type: ignore[operator]
        if operator == "LessThan":
            return cell < value  # type: ignore[operator]
        return cell <= value  # type: ignore[operator]
    text = "" if cell is None else str(cell)
    needle = "" if value is None else str(value)
    if not match_case:
        text, needle = text.lower(), needle.lower()
    if operator == "StartsWith":
        return text.startswith(needle)
    if operator == "EndsWith":
        return text.endswith(needle)
    if operator == "Contains":
        return needle in text
    if operator == "NotContains":
        return needle not in text
    if operator == "NotStartsWith":
        return not text.startswith(needle)
    if operator == "NotEndsWith":
        return not text.endswith(needle)
    raise ValueError(f"Unsupported FilterDataTable operator: {operator!r}")


def filter_datatable(table: DataTable, conditions: DataTable, match_case: bool = True) -> DataTable:
    """design/dsl_format_findings.md 知見90で実機確認済みの出力契約。

    `conditions`(`FilterParameters`)は`COLUMN`/`OPERATOR`/`VALUE`/`RULE`列を持つDataTable
    (decompileした`FilterDataTableUtilities`/`FilterDataTableExtensions`から判明、`Equal`で
    3行(`Age Equal 30 AND Name Equal Carol`)・`Contains`・`RULE: Or`(知見99)を実機のRun
    実行+ファイル書き出しで検証済み)。`RULE`は2行目以降で前の行との結合方法(`"Or"`/
    `"And"`、既定は`"And"`)を表す。標準的な論理演算子の優先順位(ANDがORより強く結合)に
    従い、OR区切りのAND-group群として評価する。`Equal`/`NotEqual`は両辺のPython型が
    一致しない場合、常に不一致(`Equal`→常に偽、`NotEqual`→常に真)という実機特有の挙動
    (decompile済みソースの`flag`判定、知見98で実機確認済み)を再現する。順序比較演算子
    (`GreaterThan`等)は数値変換せず文字列のまま比較する(知見97で実機確認済み)。
    """
    if not conditions:
        return [dict(row) for row in table]
    columns = {str(c.get("COLUMN")) for c in conditions}
    column_types = {col: _filter_column_type(table, col) for col in columns}
    groups: list[list[Row]] = [[]]
    for i, condition in enumerate(conditions):
        if i > 0 and condition.get("RULE") == "Or":
            groups.append([])
        groups[-1].append(condition)

    def row_matches(row: Row) -> bool:
        return any(
            all(_filter_condition_matches(row, cond, column_types, match_case) for cond in group)
            for group in groups
        )

    return [dict(row) for row in table if row_matches(row)]


def _join_condition_matches(row1: Row, row2: Row, condition: Row) -> bool:
    column1 = str(condition.get("COLUMN 1"))
    column2 = str(condition.get("COLUMN 2"))
    operator = str(condition.get("OPERATOR"))
    a, b = row1.get(column1), row2.get(column2)
    if operator == "Equal":
        return _pad_compare_equal(a, b)
    if operator == "NotEqual":
        return not _pad_compare_equal(a, b)
    # design/dsl_format_findings.md 知見97(実機確認済み): 順序比較演算子(GreaterThan等)は
    # `Equal`/`NotEqual`と違いクロス型の数値文字列同値判定をしない——`"9" GreaterThan "10"`
    # が真になる(文字列としての辞書順比較、数値なら偽になるはず)ことを実機で確認した。
    # 以前は数値変換を試みていたが、これは実機の挙動と食い違う誤りだったため削除した。
    if operator == "GreaterThan":
        return a > b  # type: ignore[operator]
    if operator == "GreaterThanOrEqual":
        return a >= b  # type: ignore[operator]
    if operator == "LessThan":
        return a < b  # type: ignore[operator]
    if operator == "LessThanOrEqual":
        return a <= b  # type: ignore[operator]
    raise ValueError(f"Unsupported JoinDataTable operator: {operator!r}")


def join_datatable(
    first: DataTable, second: DataTable, join_parameters: DataTable, join_operation: str = "Inner"
) -> DataTable:
    """design/dsl_format_findings.md 知見91で実機確認済みの出力契約。

    `join_parameters`(`JoinParameters`)は`"COLUMN 1"`/`OPERATOR`/`"COLUMN 2"`列を持つ
    DataTable(decompileした`JoinDataTableExtensions`/`JoinDataTableAction`から判明、
    `Equal`での`Inner`/`Left`/`Full`を実機のRun実行+ファイル書き出しで検証済み)。
    全条件行はAND結合(`FilterParameters`の`RULE`に相当する列は無い)。`OPERATOR`は
    `Equal`/`NotEqual`のみ知見85/88の`pad_equal()`(クロス型の数値文字列同値判定)を
    使い、順序比較系は数値変換できる場合のみ数値として比較する(decompile済みソースが
    `ComparisonCalculator.Compare`に委譲している箇所を`expr_runtime`の既存ヘルパーで
    再現、個別の実機検証はしていない)。両テーブルで列名が重複する場合、2番目の
    テーブル側の列名に`" (2)"`を付けて区別する(実機確認済み)。`Left`/`Full`の
    不一致側は`None`で埋める(CSV変換時は空文字列として書き出される、実機確認済み)。
    """
    first_columns = list(first[0].keys()) if first else []
    second_columns = list(second[0].keys()) if second else []
    renamed_second_columns = [f"{c} (2)" if c in first_columns else c for c in second_columns]

    def rows_match(row1: Row, row2: Row) -> bool:
        return all(_join_condition_matches(row1, row2, cond) for cond in join_parameters)

    def combine(row1: Row | None, row2: Row | None) -> Row:
        result: Row = {col: (row1.get(col) if row1 is not None else None) for col in first_columns}
        for col, renamed in zip(second_columns, renamed_second_columns):
            result[renamed] = row2.get(col) if row2 is not None else None
        return result

    result: DataTable = []
    if join_operation in ("Inner", "Left", "Full"):
        for row1 in first:
            matched = False
            for row2 in second:
                if rows_match(row1, row2):
                    result.append(combine(row1, row2))
                    matched = True
            if not matched and join_operation != "Inner":
                result.append(combine(row1, None))
        if join_operation == "Full":
            for row2 in second:
                if not any(rows_match(row1, row2) for row1 in first):
                    result.append(combine(None, row2))
    else:
        raise ValueError(f"Unsupported JoinDataTable join_operation: {join_operation!r}")
    return result


def retrieve_datatable_column_into_list(table: DataTable, column: str) -> list:
    return [row.get(column) for row in table]


# CSV<->DataTable変換は`.datatable`の実装をそのまま再公開する(File.Actionsの
# ReadFromCSVFile/WriteToCSVFileと実装を共有するため、ロジック自体はそちらに集約)。


# --- JSON/CustomObject系 -----------------------------------------------------


def json_to_custom_object(json_text: str) -> object:
    return json.loads(json_text)


def custom_object_to_json(value: object, indent: int | None = None) -> str:
    return json.dumps(value, indent=indent)
