"""`Variables.Actions`(数値・リスト・DataTable・JSON)のロジック層。

PADのDataTable/List系アクションの多くは対象コレクションを`[InputArgument(Mutable
= true)]`で受け取る——つまり既存の変数をその場で変更する。この層でもその意味論に
合わせ、リスト/DataTableを引数として受け取り、戻り値を返す代わりに**その場で変更
する**関数として実装する(新しいリストを作って返す関数と誤って混用しないよう、
全てのin-place関数は戻り値`None`に統一する)。

`SubtractLists`/`FindCommonListItems`はPAD独自の汎用比較エンジン
(`ComparisonCalculator.Compare`)に依存しており、その比較演算子の正確な意味論は
本プロジェクトの別の未解決課題(IF/SETの`=`/`<>`の挙動)と同じもの——安全側に倒し
`NotImplementedError`とする。`FilterDataTableAction`/`JoinDataTableAction`の
フィルタ条件・結合条件のDataTableスキーマも未確認のため同様に未実装とする。
"""
from __future__ import annotations

import json
import math
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
    raise NotImplementedError(
        "SubtractLists depends on PAD's ComparisonCalculator.Compare engine, "
        "whose exact comparison semantics are not yet resolved"
    )


def find_common_list_items(items: list, other: list) -> list:
    raise NotImplementedError(
        "FindCommonListItems depends on PAD's ComparisonCalculator.Compare engine, "
        "whose exact comparison semantics are not yet resolved"
    )


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


def filter_datatable(table: DataTable, conditions: DataTable) -> DataTable:
    raise NotImplementedError(
        "FilterDataTableAction's filter-condition DataTable schema "
        "(FilterConditionOperator and its parameters) has not been read from "
        "FilterDataTableUtilities.cs; not implemented"
    )


def join_datatable(left: DataTable, right: DataTable, join_type: str = "Inner") -> DataTable:
    raise NotImplementedError(
        "JoinDataTableAction's join-parameter DataTable schema has not been read; not implemented"
    )


def retrieve_datatable_column_into_list(table: DataTable, column: str) -> list:
    return [row.get(column) for row in table]


# CSV<->DataTable変換は`.datatable`の実装をそのまま再公開する(File.Actionsの
# ReadFromCSVFile/WriteToCSVFileと実装を共有するため、ロジック自体はそちらに集約)。


# --- JSON/CustomObject系 -----------------------------------------------------


def json_to_custom_object(json_text: str) -> object:
    return json.loads(json_text)


def custom_object_to_json(value: object, indent: int | None = None) -> str:
    return json.dumps(value, indent=indent)
