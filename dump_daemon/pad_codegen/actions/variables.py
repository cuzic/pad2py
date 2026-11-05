"""`Variables.*`(数値・リスト・DataTable・JSON)のcodegen。

`pad_action_lib.variables_actions`へ委譲する。パラメータ名は design/
dsl_format_findings.md 知見66で実機キャプチャした`tests/fixtures/
tier1_variables_list_datatable_batch3.txt`・`tier1_text_variables_batch1.txt`・
`tier1_text_variables_batch4.txt`から確認済み。

`Variables.CreateNewDatatable`の`InputTable: { }`は知見74でパーサーが空の`{ }`配列
リテラルを正しく空リスト`[]`として解釈するようになったため結線できる(実機キャプチャ
では2次元配列を編集しなかったため常に空。非空の配列リテラルの表現は実機未確認のため
依然対応しない)。

`Variables.SubtractLists`/`Variables.FindCommonListItems`が使う比較エンジンは
知見85で実機確認済み(文字列は大文字小文字区別、数値文字列と数値は型をまたいで
等価)のため結線済み。

`Variables.FindOrReplaceInDataTable.FindItemInDataTableEverywhere`の出力契約は
知見89で実機確認済み: `DataTableMatches`は`(行, 列)`の0始まりペアのリスト(行→列の
順で走査、`AllMatches: False`でも最初の1件だけを含むリストのまま)。専用の
`find_item_in_datatable_everywhere()`を実装・結線した。

`Variables.FilterDataTable`の`FilterParameters`スキーマ(`COLUMN`/`OPERATOR`/`VALUE`/
`RULE`列)は知見90でdecompile(`FilterDataTableUtilities.cs`)+実機のRun実行による
検証(`Equal`の2条件AND・`Contains`)で確認済みのため結線した(`filter_datatable()`)。

`Variables.JoinDataTable`の`JoinParameters`スキーマ(`"COLUMN 1"`/`OPERATOR`/
`"COLUMN 2"`列、空白を含む列名に注意)は知見91で同じ手法(decompile+`Inner`/`Left`/
`Full`の実機Run実行検証)で確認済みのため結線した(`join_datatable()`)。両テーブルの
列名重複時は2番目のテーブル側に`" (2)"`を付けて区別する実機挙動も確認済み。

`Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator`の`ReadFieldsAsText: False`
(数値らしき文字列を実際の数値型に変換する)は知見92で実機確認済みのため`True`/`False`
両方を結線した(`datatable_from_csv_text()`の`read_fields_as_text`引数に委譲)。
`TrimFields`(各フィールドの前後の空白除去)も知見93で実機確認済みのため`True`/`False`
両方を結線した(`trim_fields`引数に委譲)。

`Variables.ConvertDataTableToCSV.*`/`Variables.GenerateDataTableFromCSV.*`の
ヘッダー無しケース(`IncludeColumnNames`/`FirstLineContainsColumnNames: False`)は
知見84で実機確認済み(列名は`"Column#1"`/`"Column#2"`...が割り当てられる)。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord, VarRef
from ..context import CodegenContext
from ..render import INDENT
from ._support import enum_last, safe_render


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("Variables."):
        return None
    prefix = INDENT * indent
    p = node.params

    if action_id == "Variables.TruncateNumber.GetIntegerPart":
        number = safe_render(p.get("Number"))
        if number is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = variables_actions.truncate_number({number}, mode='GetIntegerPart')"]

    if action_id in ("Variables.IncreaseVariable", "Variables.DecreaseVariable"):
        value = p.get("Value")
        if not isinstance(value, VarRef):
            return None
        amount_key = "IncrementValue" if action_id == "Variables.IncreaseVariable" else "DecrementValue"
        amount = safe_render(p.get(amount_key))
        if amount is None:
            return None
        func = "increase_variable" if action_id == "Variables.IncreaseVariable" else "decrease_variable"
        return [f"{prefix}{value.name} = variables_actions.{func}({value.name}, {amount})"]

    if action_id == "Variables.CreateNewDatatable":
        input_table = safe_render(p.get("InputTable"))
        if input_table is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = variables_actions.create_new_datatable({input_table})"]

    if action_id == "Variables.CreateNewList":
        if not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = variables_actions.create_new_list()"]

    if action_id == "Variables.AddItemToList":
        items = safe_render(p.get("List"))
        item = safe_render(p.get("Item"))
        if items is None or item is None:
            return None
        return [f"{prefix}variables_actions.add_item_to_list({items}, {item})"]

    if action_id == "Variables.RemoveItemFromList.RemoveItemFromListByIndex":
        items = safe_render(p.get("List"))
        index = safe_render(p.get("ItemIndex"))
        if items is None or index is None:
            return None
        return [f"{prefix}variables_actions.remove_item_from_list_by_index({items}, {index})"]

    if action_id == "Variables.ClearList":
        items = safe_render(p.get("List"))
        if items is None:
            return None
        return [f"{prefix}variables_actions.clear_list({items})"]

    if action_id == "Variables.ShuffleList":
        items = safe_render(p.get("List"))
        if items is None:
            return None
        return [f"{prefix}variables_actions.shuffle_list({items})"]

    if action_id == "Variables.MergeLists":
        first = safe_render(p.get("FirstList"))
        second = safe_render(p.get("SecondList"))
        if first is None or second is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = {first} + {second}"]

    if action_id == "Variables.SubtractLists":
        first = safe_render(p.get("FirstList"))
        second = safe_render(p.get("SecondList"))
        if first is None or second is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = variables_actions.subtract_lists({first}, {second})"]

    if action_id == "Variables.FindCommonListItems":
        first = safe_render(p.get("FirstList"))
        second = safe_render(p.get("SecondList"))
        if first is None or second is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = variables_actions.find_common_list_items({first}, {second})"
        ]

    if action_id == "Variables.RemoveDuplicateItemsFromList":
        items = safe_render(p.get("List"))
        ignore_case = safe_render(p.get("IgnoreCase"))
        if items is None or ignore_case is None:
            return None
        return [f"{prefix}variables_actions.remove_duplicate_items_from_list({items}, ignore_case={ignore_case})"]

    if action_id == "Variables.SortList.SortList":
        items = safe_render(p.get("List"))
        if items is None:
            return None
        return [f"{prefix}variables_actions.sort_list({items})"]

    if action_id == "Variables.ReverseList":
        items = safe_render(p.get("List"))
        if items is None:
            return None
        return [f"{prefix}variables_actions.reverse_list({items})"]

    if action_id == "Variables.GenerateRandomNumber.RandomNumber":
        minimum = safe_render(p.get("MinimumValue"))
        maximum = safe_render(p.get("MaximumValue"))
        if minimum is None or maximum is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = variables_actions.generate_random_number({minimum}, {maximum})[0]"
        ]

    if action_id == "Variables.GenerateRandomNumber.ListOfRandomNumbers":
        # design/dsl_format_findings.md 知見122(decompile確認済み): `GenerateRandomNumber`の
        # 兄弟セレクタ(`GenerateMultipleNumbers: True`固定)。`pad_action_lib.variables_actions.
        # generate_random_number()`は元から`count`/`allow_duplicates`引数を持ち複数生成に
        # 対応済みだったため、結線を追加するだけで済む(新規実装は不要)。
        minimum = safe_render(p.get("MinimumValue"))
        maximum = safe_render(p.get("MaximumValue"))
        count = safe_render(p.get("NumbersCount"))
        allow_duplicates = p.get("AllowDuplicates", False)
        if (
            minimum is None
            or maximum is None
            or count is None
            or not isinstance(allow_duplicates, bool)
            or not node.output_var
        ):
            return None
        return [
            f"{prefix}{node.output_var} = variables_actions.generate_random_number("
            f"{minimum}, {maximum}, {count}, allow_duplicates={allow_duplicates!r})"
        ]

    if action_id == "Variables.ConvertJsonToCustomObject":
        json_text = safe_render(p.get("Json"))
        if json_text is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = variables_actions.json_to_custom_object({json_text})"]

    if action_id == "Variables.ConvertCustomObjectToJson":
        value = safe_render(p.get("CustomObject"))
        if value is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = variables_actions.custom_object_to_json({value})"]

    if action_id == "Variables.AddRowToDataTable.AppendRowToDataTable":
        table = safe_render(p.get("DataTable"))
        row = safe_render(p.get("RowToAdd"))
        if table is None or row is None:
            return None
        return [f"{prefix}variables_actions.add_row_to_datatable({table}, {row})"]

    if action_id == "Variables.FindOrReplaceInDataTable.FindItemInDataTableEverywhere":
        table = safe_render(p.get("DataTable"))
        value = safe_render(p.get("ValueToFind"))
        all_matches = safe_render(p.get("AllMatches"))
        match_case = safe_render(p.get("MatchCase"))
        entire_cell = safe_render(p.get("MatchEntireCellContents"))
        if None in (table, value, all_matches, match_case, entire_cell) or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = variables_actions.find_item_in_datatable_everywhere("
            f"{table}, {value}, all_matches={all_matches}, match_case={match_case}, "
            f"match_entire_cell_contents={entire_cell})"
        ]

    if action_id == "Variables.FilterDataTable":
        table = safe_render(p.get("DataTable"))
        # 知見72の「一度も編集されていない」空バックティック文字列(`` `` ``→Pythonの`""`)は
        # 「フィルタ未設定」を意味し、`FilterDataTableAction.Execute()`自身も
        # `FilterParameters.Rows.Count == 0`で元のテーブルをそのまま返す——
        # `filter_datatable(table, [])`の既定動作と一致するため`[]`に読み替える。
        raw_filter_parameters = p.get("FilterParameters")
        filter_parameters = "[]" if raw_filter_parameters == "" else safe_render(raw_filter_parameters)
        match_case = safe_render(p.get("MatchCase"))
        if None in (table, filter_parameters, match_case) or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = variables_actions.filter_datatable("
            f"{table}, {filter_parameters}, match_case={match_case})"
        ]

    if action_id == "Variables.JoinDataTable":
        first = safe_render(p.get("FirstDataTable"))
        second = safe_render(p.get("SecondDataTable"))
        join_operation = enum_last(p.get("JoinOperation"))
        # 知見91: 空バックティック文字列(知見72)は「結合条件が0件」を意味し、
        # JoinDataTableAction.Execute()にはFilterDataTableのような早期returnが無いため
        # (全条件をAND判定するall()の空リストに対する挙動がPAD側のVacuous-Trueな
        # .All()と一致する)、join_datatable()へそのまま`[]`として渡せば実機と同じ
        # 直積(cartesian product)になる。
        raw_join_parameters = p.get("JoinParameters")
        join_parameters = "[]" if raw_join_parameters == "" else safe_render(raw_join_parameters)
        if None in (first, second, join_operation, join_parameters) or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = variables_actions.join_datatable("
            f"{first}, {second}, {join_parameters}, join_operation={join_operation!r})"
        ]

    if action_id == "Variables.DeleteEmptyRowsFromDataTable":
        table = safe_render(p.get("DataTable"))
        if table is None:
            return None
        return [f"{prefix}variables_actions.delete_empty_rows_from_datatable({table})"]

    if action_id == "Variables.ModifyDataTableItem":
        table = safe_render(p.get("DataTable"))
        column = safe_render(p.get("ColumnNameOrIndex"))
        row_index = safe_render(p.get("RowIndex"))
        value = safe_render(p.get("Value"))
        if None in (table, column, row_index, value):
            return None
        return [
            f"{prefix}variables_actions.modify_datatable_item({table}, row_index={row_index}, "
            f"column={column}, value={value})"
        ]

    if action_id == "Variables.AddColumnToDataTable.AppendColumnToDataTable":
        table = safe_render(p.get("DataTable"))
        column = safe_render(p.get("ColumnName"))
        if table is None or column is None:
            return None
        return [f"{prefix}variables_actions.add_column_to_datatable({table}, {column})"]

    if action_id == "Variables.DeleteColumnFromDataTable.DeleteColumnWithName":
        table = safe_render(p.get("DataTable"))
        column = safe_render(p.get("ColumnName"))
        if table is None or column is None:
            return None
        return [f"{prefix}variables_actions.delete_column_from_datatable({table}, {column})"]

    if action_id == "Variables.DeleteDuplicateRowsFromDataTable":
        table = safe_render(p.get("DataTable"))
        if table is None:
            return None
        return [f"{prefix}variables_actions.delete_duplicate_rows_from_datatable({table})"]

    if action_id == "Variables.ClearDataTable":
        table = safe_render(p.get("DataTable"))
        if table is None:
            return None
        return [f"{prefix}variables_actions.clear_datatable({table})"]

    if action_id == "Variables.SortDataTable.SortWithColumnName":
        table = safe_render(p.get("DataTable"))
        column = safe_render(p.get("ColumnName"))
        order = enum_last(p.get("Order"))
        if table is None or column is None or order is None:
            return None
        return [
            f"{prefix}variables_actions.sort_datatable({table}, {column}, descending={order == 'Descending'})"
        ]

    if action_id == "Variables.RetrieveDataTableColumnIntoList":
        table = safe_render(p.get("DataTable"))
        column = safe_render(p.get("ColumnNameOrIndex"))
        if table is None or column is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = variables_actions.retrieve_datatable_column_into_list({table}, {column})"]

    if action_id == "Variables.MergeDataTables":
        # `merge_datatables()`は行を無条件に連結するだけ(各行は独立した辞書なので、
        # 列が揃っていない行が混在しても単にそのまま追加されるだけで欠落・エラーに
        # ならない)——これは実機で確認できた唯一の値`AddExtraColumns`(「余分な列が
        # あれば追加する」)が指す挙動と合致するため、その場合のみ変換する。
        first = safe_render(p.get("FirstDataTable"))
        second = safe_render(p.get("SecondDataTable"))
        merge_mode = enum_last(p.get("MergeMode"))
        if first is None or second is None or merge_mode != "AddExtraColumns":
            return None
        return [f"{prefix}variables_actions.merge_datatables({first}, {second})"]

    if action_id == "Variables.DeleteRowFromDataTable":
        table = safe_render(p.get("DataTable"))
        row_index = safe_render(p.get("RowIndex"))
        if table is None or row_index is None:
            return None
        return [f"{prefix}variables_actions.delete_row_from_datatable({table}, {row_index})"]

    if action_id == "Variables.ConvertDataTableToCSV.DataTableToCSVCommonSeparator":
        table = safe_render(p.get("DataTable"))
        separator = enum_last(p.get("ColumnsSeparator"))
        include_names = safe_render(p.get("IncludeColumnNames"))
        if table is None or include_names is None or separator != "SystemDefault" or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = variables_actions.datatable_to_csv_text("
            f"{table}, include_column_names={include_names})"
        ]

    if action_id == "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator":
        text = safe_render(p.get("CSVText"))
        separator = enum_last(p.get("ColumnsSeparator"))
        first_line = safe_render(p.get("FirstLineContainsColumnNames"))
        read_as_text = p.get("ReadFieldsAsText")
        trim_fields = p.get("TrimFields")
        if (
            text is None
            or first_line is None
            or separator != "SystemDefault"
            or not isinstance(read_as_text, bool)
            or not isinstance(trim_fields, bool)
            or not node.output_var
        ):
            return None
        return [
            f"{prefix}{node.output_var} = variables_actions.datatable_from_csv_text("
            f"{text}, first_line_contains_column_names={first_line}, "
            f"read_fields_as_text={read_as_text!r}, trim_fields={trim_fields!r})"
        ]

    return None
