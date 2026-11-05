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


def test_modify_datatable_item_rejects_numeric_column_index() -> None:
    table: va.DataTable = [{"a": 1, "b": 2}]
    with pytest.raises(ValueError, match="numeric ColumnNameOrIndex"):
        va.modify_datatable_item(table, 0, "1", 99)


def test_add_row_to_datatable_with_list_zips_positionally_against_existing_columns() -> None:
    # design/dsl_format_findings.md 知見124(decompile確認済み): PADの実際の
    # AddRowToDataTable.RowToAddはList<object>(DataRow.ItemArray = RowToAdd.ToArray()、
    # 辞書ではなく列順序による位置対応)——このため以前はdict(row)が直接クラッシュ
    # していた潜在バグを修正した。テーブルに既存の行が1件以上あれば、その列順序
    # (columns_of())と位置で対応付けて追加できる。
    table: va.DataTable = [{"a": 1, "b": 2}]
    va.add_row_to_datatable(table, [3, 4])
    assert table == [{"a": 1, "b": 2}, {"a": 3, "b": 4}]


def test_add_row_to_datatable_with_list_on_empty_table_raises_clear_error() -> None:
    # design/dsl_format_findings.md 知見124: 行が1件も無い状態(AddColumnToDataTableだけ
    # 呼ばれた直後)では列名が独立して追跡されていない(モジュールdocstring参照)ため、
    # list形式のRowToAddを解決できない——でっち上げた列名を使わず明示的にエラーにする。
    with pytest.raises(ValueError, match="no rows yet"):
        va.add_row_to_datatable([], [1, 2])


def test_add_row_to_datatable_with_list_wrong_length_raises() -> None:
    table: va.DataTable = [{"a": 1, "b": 2}]
    with pytest.raises(ValueError, match="3 values but table has 2 columns"):
        va.add_row_to_datatable(table, [3, 4, 5])


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


def test_find_item_in_datatable_everywhere_use_regex() -> None:
    # design/dsl_format_findings.md 知見123(decompile確認済み、実機未確認):
    # FindOrReplaceInDataTableの兄弟セレクタFindItemInDataTableWithRegexEverywhere。
    table = [{"a": "order-123", "b": "no digits here"}]
    assert va.find_item_in_datatable_everywhere(table, r"\d+", use_regex=True) == [(0, 0)]


def test_find_item_in_datatable_everywhere_column_scoped() -> None:
    # design/dsl_format_findings.md 知見123の追記: 兄弟セレクタ
    # FindItemInDataTableByColumnIndex(この層では列名のみ対応)。
    table = [{"a": "x", "b": "x"}, {"a": "y", "b": "x"}]
    assert va.find_item_in_datatable_everywhere(table, "x", column="b") == [(0, 1), (1, 1)]


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


def test_join_datatable_inner_equal_matches() -> None:
    # design/dsl_format_findings.md 知見91(実機確認済み)。
    t1 = [{"Name": "Alice", "Age": "30"}, {"Name": "Bob", "Age": "25"}]
    t2 = [{"Name": "Alice", "City": "NYC"}, {"Name": "Carol", "City": "LA"}]
    params = [{"COLUMN 1": "Name", "OPERATOR": "Equal", "COLUMN 2": "Name"}]
    assert va.join_datatable(t1, t2, params, join_operation="Inner") == [
        {"Name": "Alice", "Age": "30", "Name (2)": "Alice", "City": "NYC"},
    ]


def test_join_datatable_left_pads_unmatched_first_rows_with_none() -> None:
    t1 = [{"Name": "Alice", "Age": "30"}, {"Name": "Bob", "Age": "25"}]
    t2 = [{"Name": "Alice", "City": "NYC"}, {"Name": "Carol", "City": "LA"}]
    params = [{"COLUMN 1": "Name", "OPERATOR": "Equal", "COLUMN 2": "Name"}]
    assert va.join_datatable(t1, t2, params, join_operation="Left") == [
        {"Name": "Alice", "Age": "30", "Name (2)": "Alice", "City": "NYC"},
        {"Name": "Bob", "Age": "25", "Name (2)": None, "City": None},
    ]


def test_join_datatable_full_also_includes_unmatched_second_rows() -> None:
    t1 = [{"Name": "Alice", "Age": "30"}, {"Name": "Bob", "Age": "25"}]
    t2 = [{"Name": "Alice", "City": "NYC"}, {"Name": "Carol", "City": "LA"}]
    params = [{"COLUMN 1": "Name", "OPERATOR": "Equal", "COLUMN 2": "Name"}]
    assert va.join_datatable(t1, t2, params, join_operation="Full") == [
        {"Name": "Alice", "Age": "30", "Name (2)": "Alice", "City": "NYC"},
        {"Name": "Bob", "Age": "25", "Name (2)": None, "City": None},
        {"Name": None, "Age": None, "Name (2)": "Carol", "City": "LA"},
    ]


def test_join_datatable_no_conditions_is_cartesian_product() -> None:
    # JoinDataTableActionはFilterDataTableと違い空条件での早期returnが無く、
    # all()が空リストに対してVacuous-Trueになる(PAD側の.All()と一致)ため直積になる。
    t1 = [{"a": 1}, {"a": 2}]
    t2 = [{"b": 10}]
    assert va.join_datatable(t1, t2, []) == [
        {"a": 1, "b": 10},
        {"a": 2, "b": 10},
    ]


def test_join_datatable_greater_than_compares_as_strings_not_numbers() -> None:
    # design/dsl_format_findings.md 知見97(実機確認済み): 順序比較演算子は数値文字列を
    # 数値に変換せず、そのまま辞書順で比較する——"9" GreaterThan "10"/"5"/"2"は全て真
    # になる("9">"1..."/"9">"5"/"9">"2"は辞書順でも真だが、"9">"10"は数値なら偽になる
    # はずなのに実機では真だったことから、数値変換していないと確定した)。
    t1 = [{"Value": "9"}]
    t2 = [{"Value": "5"}, {"Value": "10"}, {"Value": "2"}]
    params = [{"COLUMN 1": "Value", "OPERATOR": "GreaterThan", "COLUMN 2": "Value"}]
    result = va.join_datatable(t1, t2, params, join_operation="Inner")
    assert result == [
        {"Value": "9", "Value (2)": "5"},
        {"Value": "9", "Value (2)": "10"},
        {"Value": "9", "Value (2)": "2"},
    ]


def test_filter_datatable_no_conditions_returns_copy() -> None:
    # design/dsl_format_findings.md 知見90(実機確認済み): FilterParametersが空なら
    # FilterDataTableAction.Execute()自身がDataTable.Copy()を返す。
    table = [{"a": 1}]
    result = va.filter_datatable(table, [])
    assert result == table
    assert result is not table


def test_filter_datatable_equal_matches_same_type_values() -> None:
    table = [{"Name": "Alice", "Age": "30"}, {"Name": "Bob", "Age": "25"}, {"Name": "Carol", "Age": "30"}]
    conditions = [{"COLUMN": "Age", "OPERATOR": "Equal", "VALUE": "30", "RULE": "And"}]
    assert va.filter_datatable(table, conditions) == [
        {"Name": "Alice", "Age": "30"},
        {"Name": "Carol", "Age": "30"},
    ]


def test_filter_datatable_equal_type_mismatch_never_matches() -> None:
    # decompile済みソースの`flag`判定(列の実際の型とVALUEの型が食い違う場合、Equalは
    # 常に偽・NotEqualは常に真になる)を知見98で実機確認済み: ReadFieldsAsText: Falseで
    # 数値型(int)に変換した列を`Equal "30"`(文字列)でフィルタすると0件になった。
    table = [{"Age": 30}]
    conditions = [{"COLUMN": "Age", "OPERATOR": "Equal", "VALUE": "30", "RULE": "And"}]
    assert va.filter_datatable(table, conditions) == []


def test_filter_datatable_not_equal_type_mismatch_always_matches() -> None:
    # 知見107(実機確認済み): 上記の鏡像——型不一致時のNotEqualは常に真(行が残る)。
    table = [{"Age": 30}]
    conditions = [{"COLUMN": "Age", "OPERATOR": "NotEqual", "VALUE": "30", "RULE": "And"}]
    assert va.filter_datatable(table, conditions) == table


def test_filter_datatable_contains_matches_substring() -> None:
    table = [{"Name": "Alice"}, {"Name": "Bob"}, {"Name": "Carol"}]
    conditions = [{"COLUMN": "Name", "OPERATOR": "Contains", "VALUE": "ob", "RULE": "And"}]
    assert va.filter_datatable(table, conditions) == [{"Name": "Bob"}]


def test_filter_datatable_and_combines_consecutive_conditions() -> None:
    table = [{"Name": "Alice", "Age": "30"}, {"Name": "Bob", "Age": "25"}, {"Name": "Carol", "Age": "30"}]
    conditions = [
        {"COLUMN": "Age", "OPERATOR": "Equal", "VALUE": "30", "RULE": "And"},
        {"COLUMN": "Name", "OPERATOR": "Equal", "VALUE": "Carol", "RULE": "And"},
    ]
    assert va.filter_datatable(table, conditions) == [{"Name": "Carol", "Age": "30"}]


def test_filter_datatable_or_starts_a_new_and_group() -> None:
    # design/dsl_format_findings.md 知見99で実機確認済み: Age=30 OR Age=40の2条件
    # (単純なOR、グループ化無し)がAlice/Carolにマッチし、Bobが除外されることを確認。
    table = [{"Name": "Alice", "Age": "30"}, {"Name": "Bob", "Age": "25"}, {"Name": "Carol", "Age": "30"}]
    conditions = [
        {"COLUMN": "Name", "OPERATOR": "Equal", "VALUE": "Bob", "RULE": "And"},
        {"COLUMN": "Age", "OPERATOR": "Equal", "VALUE": "30", "RULE": "Or"},
    ]
    result = va.filter_datatable(table, conditions)
    assert result == [
        {"Name": "Alice", "Age": "30"},
        {"Name": "Bob", "Age": "25"},
        {"Name": "Carol", "Age": "30"},
    ]


def test_filter_datatable_match_case_false_ignores_case() -> None:
    table = [{"Name": "alice"}]
    conditions = [{"COLUMN": "Name", "OPERATOR": "Equal", "VALUE": "Alice", "RULE": "And"}]
    assert va.filter_datatable(table, conditions, match_case=True) == []
    assert va.filter_datatable(table, conditions, match_case=False) == table


def test_retrieve_column_into_list() -> None:
    table = [{"a": 1}, {"a": 2}]
    assert va.retrieve_datatable_column_into_list(table, "a") == [1, 2]


def test_csv_round_trip() -> None:
    table = [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]
    text = va.datatable_to_csv_text(table)
    assert text == "a,b\r\n1,2\r\n3,4\r\n"
    parsed = va.datatable_from_csv_text(text)
    assert parsed == table


def test_csv_read_fields_as_text_false_converts_numeric_fields() -> None:
    # design/dsl_format_findings.md 知見92(実機確認済み): 数値として解釈できる
    # フィールドは実際の数値型に変換される(先頭ゼロは失われる、"007" -> 7)。
    # 数値として解釈できないフィールドは文字列のまま変化しない。
    text = "007,abc\r\n1,2\r\n"
    table = va.datatable_from_csv_text(
        text, first_line_contains_column_names=False, read_fields_as_text=False
    )
    assert table == [
        {"Column#1": 7, "Column#2": "abc"},
        {"Column#1": 1, "Column#2": 2},
    ]


def test_csv_read_fields_as_text_false_handles_decimals_negatives_and_exponents() -> None:
    # design/dsl_format_findings.md 知見100(実機確認済み): "3.14"は小数のまま、"-5"は
    # 負の整数のまま、"1e2"(指数表記、int()では解釈できずfloat()経由になる)は実機の
    # 表示(小数点無しの"100")と一致させるため整数`100`に変換する——`str(100.0)`が
    # "100.0"になりPythonとして実機の表示と食い違う既知の問題を修正した。
    text = "3.14,-5,1e2,abc\r\n"
    table = va.datatable_from_csv_text(
        text, first_line_contains_column_names=False, read_fields_as_text=False
    )
    row = table[0]
    assert row["Column#1"] == 3.14
    assert row["Column#2"] == -5
    assert row["Column#3"] == 100
    assert isinstance(row["Column#3"], int)
    assert row["Column#4"] == "abc"
    assert (
        va.datatable_to_csv_text(table, include_column_names=False)
        == "3.14,-5,100,abc\r\n"
    )


def test_csv_read_fields_as_text_false_handles_thousands_separator() -> None:
    # design/dsl_format_findings.md 知見103(実機確認済み): "1,000"(CSVのクォート構文
    # `"1,000"`で単一フィールドとして保護)は数値`1000`として変換される——知見102の
    # +/=演算子と同じコンマ許容の挙動がこのCSV読み込みサブシステムにもあると確認した。
    text = '"1,000"\r\n'
    table = va.datatable_from_csv_text(
        text, first_line_contains_column_names=False, read_fields_as_text=False
    )
    assert table == [{"Column#1": 1000}]


def test_csv_read_fields_as_text_true_keeps_strings() -> None:
    text = "007,abc\r\n"
    table = va.datatable_from_csv_text(text, first_line_contains_column_names=False)
    assert table == [{"Column#1": "007", "Column#2": "abc"}]


def test_csv_trim_fields_true_strips_whitespace() -> None:
    # design/dsl_format_findings.md 知見93(実機確認済み): " 7 , abc " -> "7"/"abc"。
    text = " 7 , abc \r\n"
    table = va.datatable_from_csv_text(text, first_line_contains_column_names=False)
    assert table == [{"Column#1": "7", "Column#2": "abc"}]


def test_csv_trim_fields_false_keeps_whitespace() -> None:
    text = " 7 , abc \r\n"
    table = va.datatable_from_csv_text(
        text, first_line_contains_column_names=False, trim_fields=False
    )
    assert table == [{"Column#1": " 7 ", "Column#2": " abc "}]


def test_csv_trim_fields_true_also_trims_header_row() -> None:
    # design/dsl_format_findings.md 知見106(実機確認済み): FirstLineContainsColumnNames:
    # True時のヘッダー行自体も" Name "->"Name"のようにトリム対象になる。
    text = " Name , Age \r\n Alice , 30 \r\n"
    table = va.datatable_from_csv_text(text, first_line_contains_column_names=True)
    assert table == [{"Name": "Alice", "Age": "30"}]


def test_datatable_from_fixed_width_csv_splits_by_character_position() -> None:
    # design/dsl_format_findings.md 知見132(VM上で`GenerateDataTableFromCSVAction`を
    # 直接インスタンス化・実行して確認済み): 区切り文字ではなく文字位置のみで列を切り出す。
    text = "AAABBBBBCC\nDDDEEEEEFF"
    table = va.datatable_from_fixed_width_csv(text, "3,5,2")
    assert table == [
        {"Column#1": "AAA", "Column#2": "BBBBB", "Column#3": "CC"},
        {"Column#1": "DDD", "Column#2": "EEEEE", "Column#3": "FF"},
    ]


def test_datatable_from_fixed_width_csv_trims_and_converts_like_delimited_csv() -> None:
    text = "G  H    II"
    table = va.datatable_from_fixed_width_csv(text, "3,5,2")
    assert table == [{"Column#1": "G", "Column#2": "H", "Column#3": "II"}]

    table2 = va.datatable_from_fixed_width_csv("007BBBBB42", "3,5,2", read_fields_as_text=False)
    assert table2 == [{"Column#1": 7, "Column#2": "BBBBB", "Column#3": 42}]


def test_datatable_from_fixed_width_csv_header_row_uses_same_widths() -> None:
    text = "COLABCDEHE\nAAABBBBBCC"
    table = va.datatable_from_fixed_width_csv(text, "3,5,2", first_line_contains_column_names=True)
    assert table == [{"COL": "AAA", "ABCDE": "BBBBB", "HE": "CC"}]


def test_datatable_from_fixed_width_csv_long_line_ignores_extra_chars() -> None:
    # design/dsl_format_findings.md 知見132: 行が長い場合は余りの文字を単に無視する
    # (実機ではエラーにならない)。
    table = va.datatable_from_fixed_width_csv("AAABBBBBCCXXXXX", "3,5,2")
    assert table == [{"Column#1": "AAA", "Column#2": "BBBBB", "Column#3": "CC"}]


def test_datatable_from_fixed_width_csv_short_line_raises() -> None:
    # design/dsl_format_findings.md 知見132: 行が`sum(widths)`より短いと実機では
    # ActionExceptionになる——でっち上げた空文字列で埋めずValueErrorにする。
    with pytest.raises(ValueError, match="too short"):
        va.datatable_from_fixed_width_csv("AAABB", "3,5,2")


def test_parse_fixed_column_widths_accepts_comma_or_whitespace_separated() -> None:
    # design/dsl_format_findings.md 知見132(実機の`CSVUtilities.TryParseColumnWidths`を
    # VM上で直接呼び出して確認済み): カンマ・空白どちらでも区切れ、空トークンは無視される。
    assert va.datatable_from_fixed_width_csv("ABCDE", "2,3") == [{"Column#1": "AB", "Column#2": "CDE"}]
    assert va.datatable_from_fixed_width_csv("ABCDE", "2 3") == [{"Column#1": "AB", "Column#2": "CDE"}]
    assert va.datatable_from_fixed_width_csv("ABCDE", "2,,3") == [{"Column#1": "AB", "Column#2": "CDE"}]


def test_json_custom_object_round_trip() -> None:
    obj = {"a": 1, "b": [1, 2, 3]}
    text = va.custom_object_to_json(obj)
    assert va.json_to_custom_object(text) == obj
