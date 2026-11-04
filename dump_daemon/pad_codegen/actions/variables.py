"""`Variables.*`(数値・リスト・DataTable・JSON)のcodegen。

`pad_action_lib.variables_actions`へ委譲する。パラメータ名は design/
dsl_format_findings.md 知見66で実機キャプチャした`tests/fixtures/
tier1_variables_list_datatable_batch3.txt`・`tier1_text_variables_batch1.txt`・
`tier1_text_variables_batch4.txt`から確認済み。

以下は意図的に未対応としてフォールバックに委ねる(でっち上げを避ける):
- `Variables.SubtractLists`/`Variables.FindCommonListItems`/
  `Variables.FilterDataTable`/`Variables.JoinDataTable`: `pad_action_lib`側が
  常に`NotImplementedError`を投げる(PAD独自の比較エンジン・フィルタ/結合条件の
  DataTableスキーマが未確認)——コードを生成すると実行時に必ず壊れる。
- `Variables.CreateNewDatatable`: `InputTable: { }`が知見72の`{ }`配列リテラル
  未対応構文(`VarRef(name="{")`)で実機キャプチャされており、`safe_render()`で
  自動的にフォールバックする。
- `Variables.FindOrReplaceInDataTable.FindItemInDataTableEverywhere`: 実機の
  出力契約(`DataTableMatches`への一致結果)が、`pad_action_lib`の
  `find_or_replace_in_datatable()`(置換件数の`int`を返す、`replace_value`必須)
  と一致しない——別の「検索のみ」の関数が必要だが未実装。
- `Variables.ConvertDataTableToCSV.*`/`Variables.GenerateDataTableFromCSV.*`:
  実機DSLで`IncludeColumnNames`/`FirstLineContainsColumnNames`が明示的に`False`
  だが、`pad_action_lib.datatable`のCSV変換は常にヘッダー行ありを仮定しており
  不一致。
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

    return None
