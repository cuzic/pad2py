"""`Excel.*`のcodegen。

`pad_action_lib.excel_actions`へ委譲する。知見80で、action_id文字列は全てPADデザイナー
自身の検索結果`TreeItem`のUIA `AutomationId`プロパティを直接読んで実機確認済み
(知見77と同じ経路——検索語を入力して結果を読むだけで、キーボード追加やクリップボード
貼り付けさえ不要)。パラメータ名は実機UIではなく、各`*Action`クラスの`InputArgument`/
`OutputArgument`属性宣言(ilspycmdによるdecompile、docs-local/pad_excel_findings.md)
から読み取った値——DSL上の実際の直列化形式(特に`Instance`のような不透明参照が
どう表現されるか)はまだ実機未確認。

`Instance`(`ExcelInstanceHandle`への参照)は、PAD側では不透明な参照だが、Pythonコード
生成の観点では他の変数参照と全く同じ(`LaunchExcel`の出力変数名をそのまま後続アクションの
引数として使うだけ)——`window_instance`問題のような特別な結線は不要。

ライブExcel COM専用の機能(`LaunchInNewInstance`/`Visible`/マクロ実行・セル書式の
レンダリング・ライブ選択範囲等)は`pad_action_lib.excel_actions`側で最初からスコープ外
(docs-local/pad_excel_findings.md)。このモジュールでも、該当パラメータが明示的に
非対応の値を持つ場合(`GetCellContentsMode`が`TypedValues`以外・`ReadMode`/`WriteMode`が
`Selection`/`ActiveCell`等)は、でっち上げたコードを出力せず安全にTODOフォールバックへ
委ねる。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import enum_last, safe_render


def _enum_arg(p: dict, name: str, default: str) -> str | None:
    """enumパラメータの値(省略時は`default`)を`repr()`済みのPython式として返す。"""
    if name in p:
        value = enum_last(p.get(name))
        if value is None:
            return None
        return repr(value)
    return repr(default)


def _optional_path_arg(p: dict, name: str) -> str | None:
    """`FileObject`系のオプション引数(省略時はPythonの`None`リテラル)を返す。"""
    if name in p:
        return safe_render(p.get(name))
    return "None"


def _worksheet_lookup_args(p: dict) -> str | None:
    """`FindWorksheetBy`/`Name`/`Index`の3引数を結合したPython式の断片を返す。"""
    find_by = _enum_arg(p, "FindWorksheetBy", "Name")
    name = safe_render(p.get("Name", ""))
    index = safe_render(p.get("Index", 0))
    if find_by is None or name is None or index is None:
        return None
    return f"find_worksheet_by={find_by}, name={name}, index={index}"


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("Excel."):
        return None
    prefix = INDENT * indent
    p = node.params

    if action_id == "Excel.LaunchExcel":
        if not node.output_var:
            return None
        launch_mode = _enum_arg(p, "LaunchExcelMode", "NewDocument")
        path = _optional_path_arg(p, "Path")
        read_only = safe_render(p.get("ReadOnly", False))
        if launch_mode is None or path is None or read_only is None:
            return None
        return [
            f"{prefix}{node.output_var} = excel_actions.launch_excel("
            f"launch_excel_mode={launch_mode}, path={path}, read_only={read_only})"
        ]

    if action_id == "Excel.SaveExcel":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        save_mode = _enum_arg(p, "SaveMode", "Save")
        document_path = _optional_path_arg(p, "DocumentPath")
        if save_mode is None or document_path is None:
            return None
        return [
            f"{prefix}excel_actions.save_excel({instance}, save_mode={save_mode}, "
            f"document_path={document_path})"
        ]

    if action_id == "Excel.CloseExcel":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        close_mode = _enum_arg(p, "CloseMode", "DoNotSave")
        document_path = _optional_path_arg(p, "DocumentPath")
        if close_mode is None or document_path is None:
            return None
        return [
            f"{prefix}excel_actions.close_excel({instance}, close_mode={close_mode}, "
            f"document_path={document_path})"
        ]

    if action_id == "Excel.ReadFromExcel":
        instance = safe_render(p.get("Instance"))
        if instance is None or not node.output_var:
            return None
        if "ReadMode" in p:
            read_mode_literal = enum_last(p.get("ReadMode"))
            if read_mode_literal is None or read_mode_literal == "Selection":
                return None
            read_mode = repr(read_mode_literal)
        else:
            read_mode = repr("SingleCell")
        if "GetCellContentsMode" in p:
            contents_mode = enum_last(p.get("GetCellContentsMode"))
            if contents_mode is None or contents_mode != "TypedValues":
                return None
        start_column = safe_render(p.get("StartColumn", "A"))
        start_row = safe_render(p.get("StartRow", 1))
        end_column = safe_render(p.get("EndColumn", "A"))
        end_row = safe_render(p.get("EndRow", 1))
        cell_name = safe_render(p.get("CellName", ""))
        first_line_is_header = safe_render(p.get("FirstLineIsHeader", False))
        trim_empty_cells = safe_render(p.get("TrimEmptyCells", False))
        if None in (
            start_column,
            start_row,
            end_column,
            end_row,
            cell_name,
            first_line_is_header,
            trim_empty_cells,
        ):
            return None
        return [
            f"{prefix}{node.output_var} = excel_actions.read_from_excel({instance}, "
            f"read_mode={read_mode}, start_column={start_column}, start_row={start_row}, "
            f"end_column={end_column}, end_row={end_row}, cell_name={cell_name}, "
            f"first_line_is_header={first_line_is_header}, trim_empty_cells={trim_empty_cells})"
        ]

    if action_id == "Excel.WriteToExcel":
        instance = safe_render(p.get("Instance"))
        value = safe_render(p.get("Value"))
        if instance is None or value is None:
            return None
        if "WriteMode" in p:
            write_mode_literal = enum_last(p.get("WriteMode"))
            if write_mode_literal is None or write_mode_literal == "ActiveCell":
                return None
            write_mode = repr(write_mode_literal)
        else:
            write_mode = repr("SpecifiedCell")
        column = safe_render(p.get("Column", "A"))
        row = safe_render(p.get("Row", 1))
        cell_name = safe_render(p.get("CellName", ""))
        write_to_all_cells = safe_render(p.get("WriteToAllCells", False))
        if None in (column, row, cell_name, write_to_all_cells):
            return None
        return [
            f"{prefix}excel_actions.write_to_excel({instance}, {value}, write_mode={write_mode}, "
            f"column={column}, row={row}, cell_name={cell_name}, "
            f"write_to_all_cells={write_to_all_cells})"
        ]

    if action_id == "Excel.AddWorksheet":
        instance = safe_render(p.get("Instance"))
        name = safe_render(p.get("Name"))
        if instance is None or name is None:
            return None
        position = _enum_arg(p, "WorksheetPosition", "First")
        if position is None:
            return None
        return [
            f"{prefix}excel_actions.add_worksheet({instance}, {name}, worksheet_position={position})"
        ]

    if action_id == "Excel.DeleteWorksheet":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        lookup_args = _worksheet_lookup_args(p)
        if lookup_args is None:
            return None
        return [f"{prefix}excel_actions.delete_worksheet({instance}, {lookup_args})"]

    if action_id == "Excel.RenameWorksheet":
        instance = safe_render(p.get("Instance"))
        new_name = safe_render(p.get("NewName"))
        if instance is None or new_name is None:
            return None
        lookup_args = _worksheet_lookup_args(p)
        if lookup_args is None:
            return None
        return [f"{prefix}excel_actions.rename_worksheet({instance}, {new_name}, {lookup_args})"]

    if action_id == "Excel.SetActiveWorksheet":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        lookup_args = _worksheet_lookup_args(p)
        if lookup_args is None:
            return None
        return [f"{prefix}excel_actions.set_active_worksheet({instance}, {lookup_args})"]

    if action_id == "Excel.GetActiveWorksheet":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        name_var = node.output_vars.get("Name")
        index_var = node.output_vars.get("Index")
        if not name_var and not index_var:
            return None
        lines = [f"{prefix}_active_worksheet = excel_actions.get_active_worksheet({instance})"]
        if name_var:
            lines.append(f"{prefix}{name_var} = _active_worksheet[0]")
        if index_var:
            lines.append(f"{prefix}{index_var} = _active_worksheet[1]")
        return lines

    if action_id == "Excel.GetAllWorksheets":
        instance = safe_render(p.get("Instance"))
        if instance is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = excel_actions.get_all_worksheets({instance})"]

    if action_id == "Excel.GetColumnName":
        cell_column_index = safe_render(p.get("CellColumnIndex"))
        if cell_column_index is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = excel_actions.get_column_name({cell_column_index})"]

    if action_id == "Excel.GetFirstFreeColumnRow":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        column_var = node.output_vars.get("FirstFreeColumn")
        row_var = node.output_vars.get("FirstFreeRow")
        if not column_var and not row_var:
            return None
        lines = [f"{prefix}_first_free = excel_actions.get_first_free_column_row({instance})"]
        if column_var:
            lines.append(f"{prefix}{column_var} = _first_free[0]")
        if row_var:
            lines.append(f"{prefix}{row_var} = _first_free[1]")
        return lines

    if action_id == "Excel.GetFirstFreeRowOnColumn":
        instance = safe_render(p.get("Instance"))
        column = safe_render(p.get("Column"))
        if instance is None or column is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = excel_actions.get_first_free_row_on_column("
            f"{instance}, {column})"
        ]

    return None
