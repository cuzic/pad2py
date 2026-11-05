"""`pad_action_lib.variables_actions`の単体テスト。"""
from __future__ import annotations

import pytest

from dump_daemon.pad_action_lib import variables_actions as va


def test_truncate_number_integer_and_decimal_part() -> None:
    assert va.truncate_number(3.7, "GetIntegerPart") == 3
    assert va.truncate_number(3.7, "GetDecimalPart") == pytest.approx(0.7)


def test_truncate_number_round_at_nth_digit() -> None:
    assert va.truncate_number(3.14159, "RoundAtNthDecimalDigits", decimal_digits=2) == 3.14


def test_generate_random_number_without_duplicates_is_unique() -> None:
    result = va.generate_random_number(1, 5, count=5, allow_duplicates=False)
    assert sorted(result) == [1, 2, 3, 4, 5]


def test_generate_random_number_without_duplicates_raises_when_count_too_large() -> None:
    with pytest.raises(ValueError):
        va.generate_random_number(1, 3, count=5, allow_duplicates=False)


def test_increase_decrease_variable() -> None:
    assert va.increase_variable(5, 2) == 7
    assert va.decrease_variable(5, 2) == 3


def test_add_item_to_list_mutates_in_place() -> None:
    items = [1, 2]
    va.add_item_to_list(items, 3)
    assert items == [1, 2, 3]


def test_remove_item_from_list_by_index_and_value() -> None:
    items = ["a", "b", "c"]
    va.remove_item_from_list_by_index(items, 1)
    assert items == ["a", "c"]
    va.remove_item_from_list_by_value(items, "a")
    assert items == ["c"]


def test_clear_reverse_shuffle_list() -> None:
    items = [1, 2, 3]
    va.reverse_list(items)
    assert items == [3, 2, 1]
    va.clear_list(items)
    assert items == []


def test_shuffle_list_uses_injected_rng() -> None:
    items = [1, 2, 3]

    class FixedRng:
        def shuffle(self, seq: list) -> None:
            seq.reverse()

    va.shuffle_list(items, rng=FixedRng())
    assert items == [3, 2, 1]


def test_merge_lists_extends_target() -> None:
    target = [1, 2]
    va.merge_lists(target, [3, 4])
    assert target == [1, 2, 3, 4]


def test_subtract_lists_is_case_sensitive_for_strings() -> None:
    # design/dsl_format_findings.md 知見85(実機確認済み): PADのComparisonCalculator.Compare
    # は文字列の大文字小文字を区別する(SubtractListsは一致する要素だけを取り除く)。
    assert va.subtract_lists(["Apple"], ["apple"]) == ["Apple"]


def test_subtract_lists_coerces_numeric_string_and_number_as_equal() -> None:
    # design/dsl_format_findings.md 知見85(実機確認済み): 数値を表す文字列と数値は
    # 型をまたいで等価と判定される(SubtractListsが一致とみなして取り除く)。
    assert va.subtract_lists(["1"], [1]) == []


def test_find_common_list_items_is_case_sensitive_for_strings() -> None:
    assert va.find_common_list_items(["Apple"], ["apple"]) == []


def test_find_common_list_items_coerces_numeric_string_and_number_as_equal() -> None:
    assert va.find_common_list_items(["1"], [1]) == ["1"]


def test_remove_duplicate_items_ignore_case_only_for_all_string_lists() -> None:
    items = ["a", "A", "b"]
    va.remove_duplicate_items_from_list(items, ignore_case=True)
    assert items == ["a", "b"]

    mixed = ["a", "A", 1, 1]
    va.remove_duplicate_items_from_list(mixed, ignore_case=True)
    # 文字列以外が混在する場合、IgnoreCaseは黙って無視される。
    assert mixed == ["a", "A", 1]


def test_sort_list_by_properties() -> None:
    items = [{"age": 30, "name": "b"}, {"age": 20, "name": "a"}]
    va.sort_list(items, keys=["age"])
    assert [i["name"] for i in items] == ["a", "b"]


def test_create_new_datatable_is_a_copy() -> None:
    source = [{"a": 1}]
    copy = va.create_new_datatable(source)
    copy[0]["a"] = 2
    assert source[0]["a"] == 1


def test_add_delete_modify_row() -> None:
    table: va.DataTable = [{"a": 1, "b": 2}]
    va.add_row_to_datatable(table, {"a": 3, "b": 4})
    assert table == [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    va.modify_datatable_item(table, 0, "a", 99)
    assert table[0]["a"] == 99
    va.delete_row_from_datatable(table, 0)
    assert table == [{"a": 3, "b": 4}]


def test_find_or_replace_in_datatable() -> None:
    table = [{"a": "hello", "b": "world"}]
    count = va.find_or_replace_in_datatable(table, "hello", "HI")
    assert count == 1
    assert table[0]["a"] == "HI"


def test_find_item_in_datatable_everywhere_returns_row_col_pairs() -> None:
    # design/dsl_format_findings.md 知見89で実機確認済みの出力契約。
    table = [{"a": "apple", "b": "banana"}, {"a": "Apple", "b": "cherry"}]
    assert va.find_item_in_datatable_everywhere(table, "apple") == [(0, 0), (1, 0)]


def test_find_item_in_datatable_everywhere_all_matches_false_stops_at_first() -> None:
    table = [{"a": "apple", "b": "banana"}, {"a": "Apple", "b": "cherry"}]
    assert va.find_item_in_datatable_everywhere(table, "apple", all_matches=False) == [(0, 0)]


def test_find_item_in_datatable_everywhere_entire_cell_contents() -> None:
    table = [{"a": "apple", "b": "banana"}, {"a": "Apple", "b": "cherry"}]
    assert va.find_item_in_datatable_everywhere(
        table, "apple", match_entire_cell_contents=True
    ) == [(0, 0), (1, 0)]


def test_find_item_in_datatable_everywhere_no_match_returns_empty() -> None:
    table = [{"a": "apple", "b": "banana"}]
    assert va.find_item_in_datatable_everywhere(table, "zzz_nomatch") == []


def test_delete_empty_and_duplicate_rows() -> None:
    table = [{"a": "", "b": ""}, {"a": "1", "b": "2"}, {"a": "1", "b": "2"}]
    va.delete_empty_rows_from_datatable(table)
    assert len(table) == 2
    va.delete_duplicate_rows_from_datatable(table)
    assert len(table) == 1


def test_add_and_delete_column() -> None:
    table = [{"a": 1}]
    va.add_column_to_datatable(table, "b", default_value=0)
    assert table == [{"a": 1, "b": 0}]
    va.delete_column_from_datatable(table, "a")
    assert table == [{"b": 0}]


def test_sort_datatable() -> None:
    table = [{"a": 2}, {"a": 1}]
    va.sort_datatable(table, "a")
    assert [r["a"] for r in table] == [1, 2]


def test_merge_datatables() -> None:
    target = [{"a": 1}]
    va.merge_datatables(target, [{"a": 2}])
    assert target == [{"a": 1}, {"a": 2}]


def test_filter_and_join_datatable_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        va.filter_datatable([{"a": 1}], [])
    with pytest.raises(NotImplementedError):
        va.join_datatable([{"a": 1}], [{"a": 1}])


def test_retrieve_column_into_list() -> None:
    table = [{"a": 1}, {"a": 2}]
    assert va.retrieve_datatable_column_into_list(table, "a") == [1, 2]


def test_csv_round_trip() -> None:
    table = [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]
    text = va.datatable_to_csv_text(table)
    assert text == "a,b\r\n1,2\r\n3,4\r\n"
    parsed = va.datatable_from_csv_text(text)
    assert parsed == table


def test_json_custom_object_round_trip() -> None:
    obj = {"a": 1, "b": [1, 2, 3]}
    text = va.custom_object_to_json(obj)
    assert va.json_to_custom_object(text) == obj
