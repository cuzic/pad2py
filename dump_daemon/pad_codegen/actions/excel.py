"""`Excel.*`のcodegen。

`pad_action_lib.excel_actions`へ委譲する。知見80では、action_id文字列はPADデザイナー
自身の検索結果`TreeItem`のUIA `AutomationId`を直接読んで「`Excel.ReadFromExcel`等の
14アクションが存在する」ことまでは確認していたが、これはアクション**グループ**の
AutomationIdであり、他の全モジュール(知見139以降のWeb/XML/Cmd/Text/Cryptography/
Database/File)と全く同じ`ActionSelectorBase`一括列挙監査を知見155で適用した結果、
`LaunchExcel`/`CloseExcel`/`SaveExcel`/`ReadFromExcel`/`WriteToExcel`/
`DeleteWorksheet`/`RenameWorksheet`/`SetActiveWorksheet`の8グループには実際には
兄弟セレクタがあり、DSL上の真のaction_idは`Excel.<グループ>.<ActionName>`という
3セグメント形式だと判明した(`ActionName`=各`ActionSelector<T>`サブクラスの
`UseName(...)`の値、知見150で確立した`.Arguments`監査と同じ原理)——従来のフラットな
`Excel.ReadFromExcel`等の判定は、実際には存在しない形式のため**常にマッチせず
TODOフォールバックへ落ちていた**(知見155で発見・修正)。`AddWorksheet`/
`GetActiveWorksheet`/`GetAllWorksheets`/`GetColumnName`/`GetFirstFreeColumnRow`/
`GetFirstFreeRowOnColumn`の6件は兄弟セレクタが存在せず、フラットな形式のままで
正しい。

`Instance`(`ExcelInstanceHandle`への参照)は、PAD側では不透明な参照だが、Pythonコード
生成の観点では他の変数参照と全く同じ(`LaunchExcel`の出力変数名をそのまま後続アクションの
引数として使うだけ)——`window_instance`問題のような特別な結線は不要。

ライブExcel COM専用の機能(`LaunchInNewInstance=False`での既存プロセスアタッチ・
`ReadMode`/`WriteMode`の`Selection`/`ActiveCell`等)は、知見155のセレクタ監査で
各セレクタが固定する`Prop<>.ShouldBe()`値から判別し、`pad_action_lib.excel_actions`
側のスコープ外(docs-local/pad_excel_findings.md)と一致する場合のみ`None`を返して
TODOフォールバックへ委ねる。各セレクタが固定する列挙値(`ReadMode`/`WriteMode`/
`SaveMode`/`CloseMode`/`FindWorksheetBy`/`LaunchExcelMode`等)は、でっち上げではなく
decompileした`ActionSelector<T>`サブクラスの`Prop<>.ShouldBe()`呼び出しそのもの
(知見155)から直接書き起こしたもので、`enum_last()`でDSLから動的に読む必要は無い
(セレクタが選ばれた時点で値は一意に確定している)。

`Excel.GetActiveCell`(フラットな`GetActiveCellAction`)も知見189で精査済み、ライブExcel
COMの`Application.ActiveCell`(現在のユーザー選択セル)読み取りのみで`openpyxl`に対応
概念が無いため、知見171の6件に次ぐ7件目のライブCOM専用として専用dispatchを追加せず
意図的に汎用TODOフォールバックのままにしている。
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


# design/dsl_format_findings.md 知見192(decompile確認済み): `GetEmptyCellFromExcel`の
# 8兄弟セレクタ → `(range_mode, operation)`。
_GET_EMPTY_CELL_DISPATCH: dict[str, tuple[str, str]] = {
    "Excel.GetEmptyCellFromExcel.GetEmptyCellsNamedCellFirstEmptyCell": ("NamedCell", "FirstEmptyCell"),
    "Excel.GetEmptyCellFromExcel.GetEmptyCellsNamedCellFirstEmptyCellInRow": ("NamedCell", "FirstEmptyCellInRow"),
    "Excel.GetEmptyCellFromExcel.GetEmptyCellsNamedCellFirstEmptyCellInColumn": (
        "NamedCell",
        "FirstEmptyCellInColumn",
    ),
    "Excel.GetEmptyCellFromExcel.GetEmptyCellsNamedCellAllEmptyCells": ("NamedCell", "AllEmptyCells"),
    "Excel.GetEmptyCellFromExcel.GetEmptyCellsAbsoluteRangeFirstEmptyCell": ("Coordinates", "FirstEmptyCell"),
    "Excel.GetEmptyCellFromExcel.GetEmptyCellsAbsoluteRangeFirstEmptyCellInRow": (
        "Coordinates",
        "FirstEmptyCellInRow",
    ),
    "Excel.GetEmptyCellFromExcel.GetEmptyCellsAbsoluteRangeFirstEmptyCellInColumn": (
        "Coordinates",
        "FirstEmptyCellInColumn",
    ),
    "Excel.GetEmptyCellFromExcel.GetEmptyCellsAbsoluteRangeAllEmptyCells": ("Coordinates", "AllEmptyCells"),
}


# design/dsl_format_findings.md 知見193(decompile確認済み): `CopyExcelWorksheet`の
# 兄弟セレクタ2件 → `FindWorksheetBy`の値。
_COPY_WORKSHEET_FIND_BY: dict[str, str] = {
    "Excel.CopyExcelWorksheet.CopyWorksheetWithName": "Name",
    "Excel.CopyExcelWorksheet.CopyWorksheetWithIndex": "Index",
}


def _worksheet_lookup_args(p: dict, find_by: str) -> str | None:
    """`FindWorksheetBy`(セレクタごとに固定、知見155)/`Name`/`Index`の3引数を
    結合したPython式の断片を返す。"""
    name = safe_render(p.get("Name", ""))
    index = safe_render(p.get("Index", 0))
    if name is None or index is None:
        return None
    return f"find_worksheet_by={find_by!r}, name={name}, index={index}"


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("Excel."):
        return None
    prefix = INDENT * indent
    p = node.params

    # 知見155: `LaunchExcel`の兄弟セレクタ4件。`LaunchInNewInstance=False`
    # (既存プロセスへのアタッチ、`UnderExistingProcess`接尾辞)はライブCOM専用のため
    # スコープ外。
    if action_id == "Excel.LaunchExcel.Launch":
        if not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = excel_actions.launch_excel("
            f"launch_excel_mode='NewDocument', path=None, read_only=False)"
        ]

    if action_id == "Excel.LaunchExcel.LaunchAndOpen":
        path = safe_render(p.get("Path"))
        read_only = safe_render(p.get("ReadOnly", False))
        if path is None or read_only is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = excel_actions.launch_excel("
            f"launch_excel_mode='StoredDocument', path={path}, read_only={read_only})"
        ]

    # 知見155: `SaveExcel`の兄弟セレクタ2件(`SaveMode`は`Save`/`SaveAs`で固定)。
    if action_id == "Excel.SaveExcel.Save":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        return [f"{prefix}excel_actions.save_excel({instance}, save_mode='Save')"]

    if action_id == "Excel.SaveExcel.SaveAs":
        instance = safe_render(p.get("Instance"))
        document_path = safe_render(p.get("DocumentPath"))
        if instance is None or document_path is None:
            return None
        return [
            f"{prefix}excel_actions.save_excel({instance}, save_mode='SaveAs', "
            f"document_path={document_path})"
        ]

    # 知見155: `CloseExcel`の兄弟セレクタ3件(`CloseMode`は`DoNotSave`/`Save`/`SaveAs`で固定)。
    if action_id == "Excel.CloseExcel.Close":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        return [f"{prefix}excel_actions.close_excel({instance}, close_mode='DoNotSave')"]

    if action_id == "Excel.CloseExcel.CloseAndSave":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        return [f"{prefix}excel_actions.close_excel({instance}, close_mode='Save')"]

    if action_id == "Excel.CloseExcel.CloseAndSaveAs":
        instance = safe_render(p.get("Instance"))
        document_path = safe_render(p.get("DocumentPath"))
        if instance is None or document_path is None:
            return None
        return [
            f"{prefix}excel_actions.close_excel({instance}, close_mode='SaveAs', "
            f"document_path={document_path})"
        ]

    # 知見155: `ReadFromExcel`の兄弟セレクタ5件のうち、`Read`(`ReadMode=Selection`、
    # ライブExcel UIの現在の選択範囲)はスコープ外。`ReadMode`はセレクタごとに固定。
    _EXCEL_READ_MODE_BY_ACTION_NAME = {
        "Excel.ReadFromExcel.ReadCell": "SingleCell",
        "Excel.ReadFromExcel.ReadCells": "RangeOfCells",
        "Excel.ReadFromExcel.ReadAllCells": "AllCells",
        "Excel.ReadFromExcel.ReadNamedCell": "NamedCells",
    }
    read_mode_literal = _EXCEL_READ_MODE_BY_ACTION_NAME.get(action_id)
    if read_mode_literal is not None:
        instance = safe_render(p.get("Instance"))
        if instance is None or not node.output_var:
            return None
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
            f"read_mode={read_mode_literal!r}, start_column={start_column}, start_row={start_row}, "
            f"end_column={end_column}, end_row={end_row}, cell_name={cell_name}, "
            f"first_line_is_header={first_line_is_header}, trim_empty_cells={trim_empty_cells})"
        ]

    # 知見155: `WriteToExcel`の兄弟セレクタ3件のうち、`Write`(`WriteMode=ActiveCell`、
    # ライブExcel UIのアクティブセル)はスコープ外。`WriteMode`はセレクタごとに固定。
    _EXCEL_WRITE_MODE_BY_ACTION_NAME = {
        "Excel.WriteToExcel.WriteCell": "SpecifiedCell",
        "Excel.WriteToExcel.WriteNamedCell": "NamedCells",
    }
    write_mode_literal = _EXCEL_WRITE_MODE_BY_ACTION_NAME.get(action_id)
    if write_mode_literal is not None:
        instance = safe_render(p.get("Instance"))
        value = safe_render(p.get("Value"))
        if instance is None or value is None:
            return None
        column = safe_render(p.get("Column", "A"))
        row = safe_render(p.get("Row", 1))
        cell_name = safe_render(p.get("CellName", ""))
        write_to_all_cells = safe_render(p.get("WriteToAllCells", False))
        if None in (column, row, cell_name, write_to_all_cells):
            return None
        return [
            f"{prefix}excel_actions.write_to_excel({instance}, {value}, "
            f"write_mode={write_mode_literal!r}, column={column}, row={row}, cell_name={cell_name}, "
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

    # 知見155: `DeleteWorksheet`/`RenameWorksheet`/`SetActiveWorksheet`はいずれも
    # `FindWorksheetBy`(`Index`/`Name`)で分かれる2つの兄弟セレクタを持つ
    # (`ActionName`はグループ名と異なり`<Group>By<Index|Name>`系の表記)。
    _EXCEL_DELETE_WORKSHEET_FIND_BY = {
        "Excel.DeleteWorksheet.DeleteWorksheetByIndex": "Index",
        "Excel.DeleteWorksheet.DeleteWorksheetByName": "Name",
    }
    find_by = _EXCEL_DELETE_WORKSHEET_FIND_BY.get(action_id)
    if find_by is not None:
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        lookup_args = _worksheet_lookup_args(p, find_by)
        if lookup_args is None:
            return None
        return [f"{prefix}excel_actions.delete_worksheet({instance}, {lookup_args})"]

    _EXCEL_RENAME_WORKSHEET_FIND_BY = {
        "Excel.RenameWorksheet.RenameWorksheetWithIndex": "Index",
        "Excel.RenameWorksheet.RenameWorksheetWithName": "Name",
    }
    find_by = _EXCEL_RENAME_WORKSHEET_FIND_BY.get(action_id)
    if find_by is not None:
        instance = safe_render(p.get("Instance"))
        new_name = safe_render(p.get("NewName"))
        if instance is None or new_name is None:
            return None
        lookup_args = _worksheet_lookup_args(p, find_by)
        if lookup_args is None:
            return None
        return [f"{prefix}excel_actions.rename_worksheet({instance}, {new_name}, {lookup_args})"]

    _EXCEL_SET_ACTIVE_WORKSHEET_FIND_BY = {
        "Excel.SetActiveWorksheet.ActivateWorksheetByIndex": "Index",
        "Excel.SetActiveWorksheet.ActivateWorksheetByName": "Name",
    }
    find_by = _EXCEL_SET_ACTIVE_WORKSHEET_FIND_BY.get(action_id)
    if find_by is not None:
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        lookup_args = _worksheet_lookup_args(p, find_by)
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

    if action_id == "Excel.DeleteColumn":
        instance = safe_render(p.get("Instance"))
        column = safe_render(p.get("Column"))
        if instance is None or column is None:
            return None
        return [f"{prefix}excel_actions.delete_column({instance}, {column})"]

    if action_id == "Excel.InsertColumn":
        instance = safe_render(p.get("Instance"))
        column = safe_render(p.get("Column"))
        if instance is None or column is None:
            return None
        return [f"{prefix}excel_actions.insert_column({instance}, {column})"]

    if action_id == "Excel.DeleteRow":
        instance = safe_render(p.get("Instance"))
        index = safe_render(p.get("Index"))
        if instance is None or index is None:
            return None
        return [f"{prefix}excel_actions.delete_row({instance}, {index})"]

    if action_id == "Excel.InsertRow":
        instance = safe_render(p.get("Instance"))
        index = safe_render(p.get("Index"))
        if instance is None or index is None:
            return None
        return [f"{prefix}excel_actions.insert_row({instance}, {index})"]

    if action_id == "Excel.GetTableRange":
        # design/dsl_format_findings.md 知見180(decompile確認済み): `IsPivot=True`は
        # openpyxlに対応APIが無いため`excel_actions.get_table_range()`側で
        # `NotImplementedError`に委ねる(ここでは安全にTODOへ倒す)。
        instance = safe_render(p.get("Instance"))
        table_name = safe_render(p.get("TableName"))
        is_pivot = p.get("IsPivot", False)
        if instance is None or table_name is None or is_pivot is not False:
            return None
        row_var = node.output_vars.get("FirstRowIndex")
        col_var = node.output_vars.get("FirstColumnIndex")
        last_row_var = node.output_vars.get("LastRowIndex")
        last_col_var = node.output_vars.get("LastColumnIndex")
        if not (row_var or col_var or last_row_var or last_col_var):
            return None
        lines = [f"{prefix}_table_range = excel_actions.get_table_range({instance}, {table_name})"]
        if row_var:
            lines.append(f"{prefix}{row_var} = _table_range[0]")
        if col_var:
            lines.append(f"{prefix}{col_var} = _table_range[1]")
        if last_row_var:
            lines.append(f"{prefix}{last_row_var} = _table_range[2]")
        if last_col_var:
            lines.append(f"{prefix}{last_col_var} = _table_range[3]")
        return lines

    if action_id in (
        "Excel.ReadCellFormula.ReadFormulaFromCellCoordinates",
        "Excel.ReadCellFormula.ReadFormulaFromNamedCell",
    ):
        # design/dsl_format_findings.md 知見190: `write_to_excel()`が「数式文字列は
        # テキストとしてそのまま書き込むだけ」と対になる読み取り側。
        instance = safe_render(p.get("Instance"))
        if instance is None or not node.output_var:
            return None
        if action_id == "Excel.ReadCellFormula.ReadFormulaFromCellCoordinates":
            column = safe_render(p.get("Column"))
            row = safe_render(p.get("Row"))
            if column is None or row is None:
                return None
            call = f"excel_actions.read_cell_formula({instance}, 'CellCoordinates', column={column}, row={row})"
        else:
            cell_name = safe_render(p.get("CellName"))
            if cell_name is None:
                return None
            call = f"excel_actions.read_cell_formula({instance}, 'NamedCell', cell_name={cell_name})"
        return [f"{prefix}{node.output_var} = {call}"]

    empty_cell_dispatch = _GET_EMPTY_CELL_DISPATCH.get(action_id)
    if empty_cell_dispatch is not None:
        # design/dsl_format_findings.md 知見192: 各セレクタが`Show<>`するパラメータのみ
        # DSLに現れる想定のため、モードごとに必要な引数だけ`safe_render()`する。
        range_mode, operation = empty_cell_dispatch
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        args = [f"operation={operation!r}", f"range_mode={range_mode!r}"]
        if range_mode == "NamedCell":
            named_cell = safe_render(p.get("NamedCell"))
            if named_cell is None:
                return None
            args.append(f"named_cell={named_cell}")
        else:
            start_column = safe_render(p.get("StartColumn"))
            start_row = safe_render(p.get("StartRow"))
            end_column = safe_render(p.get("EndColumn"))
            end_row = safe_render(p.get("EndRow"))
            if None in (start_column, start_row, end_column, end_row):
                return None
            args.append(f"start_column={start_column}, start_row={start_row}, "
                        f"end_column={end_column}, end_row={end_row}")
        if operation == "FirstEmptyCellInRow":
            search_row = safe_render(p.get("SearchRow"))
            if search_row is None:
                return None
            args.append(f"search_row={search_row}")
        elif operation == "FirstEmptyCellInColumn":
            search_column = safe_render(p.get("SearchColumn"))
            if search_column is None:
                return None
            args.append(f"search_column={search_column}")
        elif operation == "FirstEmptyCell":
            search_direction = _enum_arg(p, "EmptyCellsSearchDirection", "Rows")
            if search_direction is None:
                return None
            args.append(f"search_direction={search_direction}")
        call = f"excel_actions.get_empty_cell({instance}, {', '.join(args)})"
        if operation == "AllEmptyCells":
            empty_cells_var = node.output_vars.get("EmptyCells")
            if not empty_cells_var:
                return None
            return [f"{prefix}{empty_cells_var} = {call}"]
        col_var = node.output_vars.get("EmptyCellColumnIndex")
        row_var = node.output_vars.get("EmptyCellRowIndex")
        if not (col_var or row_var):
            return None
        lines = [f"{prefix}_empty_cell = {call}"]
        if col_var:
            lines.append(f"{prefix}{col_var} = _empty_cell[0]")
        if row_var:
            lines.append(f"{prefix}{row_var} = _empty_cell[1]")
        return lines

    copy_worksheet_find_by = _COPY_WORKSHEET_FIND_BY.get(action_id)
    if copy_worksheet_find_by is not None:
        # design/dsl_format_findings.md 知見193: `openpyxl`はワークブック間コピーを
        # 禁止するため、`copy_excel_worksheet()`側で同一ワークブック以外は
        # `NotImplementedError`に委ねる。
        source_instance = safe_render(p.get("SourceInstance"))
        target_instance = safe_render(p.get("TargetInstance"))
        target_name = safe_render(p.get("TargetWorksheetName"))
        position = _enum_arg(p, "PasteWorksheetPosition", "First")
        if None in (source_instance, target_instance, target_name, position):
            return None
        args = [source_instance, target_instance, target_name, f"find_worksheet_by={copy_worksheet_find_by!r}"]
        if copy_worksheet_find_by == "Name":
            source_name = safe_render(p.get("SourceWorksheetName"))
            if source_name is None:
                return None
            args.append(f"source_worksheet_name={source_name}")
        else:
            source_index = safe_render(p.get("SourceWorksheetIndex"))
            if source_index is None:
                return None
            args.append(f"source_worksheet_index={source_index}")
        args.append(f"paste_worksheet_position={position}")
        return [f"{prefix}excel_actions.copy_excel_worksheet({', '.join(args)})"]

    return None
