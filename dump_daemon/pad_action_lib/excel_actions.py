"""`Excel.Actions`のロジック層(スコープ限定: 値の読み書き・基本ワークシート操作・静的な内容)。

PADの実装はライブのExcel COMインスタンスを駆動する設計(`LaunchExcel`/`AttachToRunningExcel`/
`ExcelInstanceHandle`)で、フィルタ・ソート・オートフィット・マクロ実行・セル色設定・コピペ・
検索置換・ルックアップまで多岐にわたる。これらはライブのExcelアプリケーションの機能そのもの
であり、ファイルベースの`openpyxl`では本質的に再現できない(マクロ実行不可、ライブセレクション
が存在しない等)——このモジュールはユーザー指定のスコープに従い、値の読み書き・基本ワークシート
操作・静的な内容だけを実装し、COM駆動の高度な機能は`NotImplementedError`で明示するだけに留める
(推測で`openpyxl`近似コードを書かない)。

書き込む数式文字列(`"=A1+B1"`等)はテキストとしてそのままセルに書き込まれるだけで、`openpyxl`は
Excelの数式エンジンを持たないため計算結果は保持されない——「静的数式」というスコープ通りの挙動。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import openpyxl
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.utils.cell import range_boundaries
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.worksheet import Worksheet

from .datatable import DataTable
from .errors import PadActionError


class LaunchExcelError(PadActionError):
    pass


class OpenDocumentError(PadActionError):
    pass


class SaveExcelError(PadActionError):
    pass


class CloseExcelError(PadActionError):
    pass


class ReadCellsError(PadActionError):
    pass


class WriteToExcelError(PadActionError):
    pass


class AppendCellsError(PadActionError):
    pass


class WorksheetAlreadyExistsError(PadActionError):
    pass


class AddWorksheetError(PadActionError):
    pass


class WorksheetNotFoundError(PadActionError):
    pass


class DeleteWorksheetError(PadActionError):
    pass


class RenameWorksheetError(PadActionError):
    pass


class ActivateWorksheetError(PadActionError):
    pass


class RetrieveAllWorksheetsError(PadActionError):
    pass


class RetrieveActiveWorksheetError(PadActionError):
    pass


class RetrieveFirstFreeColumnRowError(PadActionError):
    pass


class RetrieveFirstFreeRowError(PadActionError):
    pass


@dataclass
class ExcelInstanceHandle:
    """不透明なワークブック参照(「window instance」問題と同種)。

    `active_sheet_name`はこのハンドル側で追跡する——`SetActiveWorksheet`で変更した状態を
    PAD側の「アクティブワークシート」概念に対応させるため(`openpyxl`の`Workbook.active`は
    ファイルに記録された既定シートであり、このハンドルの生存中の状態変化は反映しない)。
    """

    workbook: openpyxl.Workbook
    path: str | None = None
    active_sheet_name: str = field(default="")

    def __post_init__(self) -> None:
        if not self.active_sheet_name:
            self.active_sheet_name = self.workbook.active.title

    @property
    def active_sheet(self) -> Worksheet:
        return self.workbook[self.active_sheet_name]


def launch_excel(
    launch_excel_mode: str = "NewDocument",
    path: str | None = None,
    read_only: bool = False,
) -> ExcelInstanceHandle:
    # LaunchInNewInstance/LoadAddInsAndMacros/UseMachineLocale/Visible/*ProtectionPasswordは
    # ライブExcelプロセスの起動オプションであり、ファイルベースのopenpyxlには対応物が無いため
    # 受け取らない。
    try:
        if launch_excel_mode == "NewDocument":
            workbook = openpyxl.Workbook()
        elif launch_excel_mode == "StoredDocument":
            if not path:
                raise OpenDocumentError("Path is required for LaunchExcelMode=StoredDocument")
            workbook = openpyxl.load_workbook(path, read_only=read_only, data_only=False)
        else:
            raise ValueError(f"Unknown LaunchExcelMode: {launch_excel_mode!r}")
    except OpenDocumentError:
        raise
    except FileNotFoundError as exc:
        raise OpenDocumentError(str(exc)) from exc
    except Exception as exc:
        raise LaunchExcelError(str(exc)) from exc
    return ExcelInstanceHandle(workbook=workbook, path=path)


def save_excel(instance: ExcelInstanceHandle, save_mode: str = "Save", document_path: str | None = None) -> None:
    try:
        if save_mode == "SaveAs":
            if not document_path:
                raise ValueError("document_path is required for SaveExcelMode=SaveAs")
            instance.workbook.save(document_path)
            instance.path = document_path
        elif save_mode == "Save":
            if not instance.path:
                raise ValueError("instance has no known path; use SaveMode=SaveAs")
            instance.workbook.save(instance.path)
        else:
            raise ValueError(f"Unknown SaveExcelMode: {save_mode!r}")
    except Exception as exc:
        raise SaveExcelError(str(exc)) from exc


def close_excel(
    instance: ExcelInstanceHandle,
    close_mode: str = "DoNotSave",
    document_path: str | None = None,
) -> None:
    try:
        if close_mode == "Save":
            save_excel(instance, "Save")
        elif close_mode == "SaveAs":
            save_excel(instance, "SaveAs", document_path)
        elif close_mode != "DoNotSave":
            raise ValueError(f"Unknown CloseExcelMode: {close_mode!r}")
    except SaveExcelError:
        raise
    except Exception as exc:
        raise CloseExcelError(str(exc)) from exc
    finally:
        # openpyxlにはライブインスタンスを閉じる概念が無いため、参照を手放すだけ。
        instance.workbook.close()


def _lookup_defined_name(workbook: openpyxl.Workbook, cell_name: str) -> DefinedName:
    defined_name = workbook.defined_names.get(cell_name)
    if defined_name is None:
        raise KeyError(cell_name)
    return defined_name


def _defined_name_start(workbook: openpyxl.Workbook, cell_name: str) -> tuple[Worksheet, int, int]:
    defined_name = _lookup_defined_name(workbook, cell_name)
    for sheet_title, range_string in defined_name.destinations:
        min_col, min_row, _max_col, _max_row = range_boundaries(range_string)
        return workbook[sheet_title], min_col, min_row
    raise KeyError(cell_name)


def _defined_name_range(workbook: openpyxl.Workbook, cell_name: str) -> tuple[Worksheet, int, int, int, int]:
    defined_name = _lookup_defined_name(workbook, cell_name)
    for sheet_title, range_string in defined_name.destinations:
        min_col, min_row, max_col, max_row = range_boundaries(range_string)
        return workbook[sheet_title], min_col, min_row, max_col, max_row
    raise KeyError(cell_name)


def _is_row_empty(row: tuple) -> bool:
    return all(cell.value is None for cell in row)


def _range_to_datatable(
    sheet: Worksheet,
    min_col: int,
    min_row: int,
    max_col: int,
    max_row: int,
    first_line_is_header: bool,
    trim_empty_cells: bool,
) -> DataTable:
    rows = list(sheet.iter_rows(min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col))
    if trim_empty_cells:
        # 正確な定義は実機未確認の近似: 範囲内の完全に空の行を除去する。
        rows = [row for row in rows if not _is_row_empty(row)]
    if not rows:
        return []
    if first_line_is_header:
        header = [str(c.value) if c.value is not None else "" for c in rows[0]]
        data_rows = rows[1:]
    else:
        header = [get_column_letter(c.column) for c in rows[0]]
        data_rows = rows
    return [dict(zip(header, (c.value for c in row))) for row in data_rows]


def read_from_excel(
    instance: ExcelInstanceHandle,
    read_mode: str = "SingleCell",
    start_column: str = "A",
    start_row: int = 1,
    end_column: str = "A",
    end_row: int = 1,
    cell_name: str = "",
    get_cell_contents_mode: str = "TypedValues",
    first_line_is_header: bool = False,
    trim_empty_cells: bool = False,
) -> object | DataTable:
    if get_cell_contents_mode != "TypedValues":
        raise NotImplementedError(
            f"GetCellContentsMode={get_cell_contents_mode!r} needs Excel's live number-format "
            "rendering engine, which openpyxl does not provide"
        )
    sheet = instance.active_sheet
    try:
        if read_mode == "SingleCell":
            return sheet[f"{start_column}{start_row}"].value
        if read_mode == "RangeOfCells":
            return _range_to_datatable(
                sheet,
                column_index_from_string(start_column),
                start_row,
                column_index_from_string(end_column),
                end_row,
                first_line_is_header,
                trim_empty_cells,
            )
        if read_mode == "AllCells":
            return _range_to_datatable(
                sheet, 1, 1, sheet.max_column, sheet.max_row, first_line_is_header, trim_empty_cells
            )
        if read_mode == "NamedCells":
            try:
                target_sheet, min_col, min_row, max_col, max_row = _defined_name_range(
                    instance.workbook, cell_name
                )
            except KeyError as exc:
                raise ReadCellsError(f"named cell not found: {cell_name!r}") from exc
            if (min_col, min_row) == (max_col, max_row):
                return target_sheet.cell(row=min_row, column=min_col).value
            return _range_to_datatable(
                target_sheet, min_col, min_row, max_col, max_row, first_line_is_header, trim_empty_cells
            )
        if read_mode == "Selection":
            raise NotImplementedError(
                "ReadExcelCellsMode.Selection reads the live Excel UI's current selection; "
                "not meaningful for a file-based (openpyxl) backend"
            )
        raise ValueError(f"Unknown ReadExcelCellsMode: {read_mode!r}")
    except (ReadCellsError, NotImplementedError):
        raise
    except Exception as exc:
        raise ReadCellsError(str(exc)) from exc


def _write_block(sheet: Worksheet, start_col: int, start_row: int, value: object) -> None:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        columns = list(value[0].keys())
        for r, row in enumerate(value):
            for c, col_name in enumerate(columns):
                sheet.cell(row=start_row + r, column=start_col + c, value=row.get(col_name))
    elif isinstance(value, list) and value and isinstance(value[0], list):
        for r, row in enumerate(value):
            for c, cell_value in enumerate(row):
                sheet.cell(row=start_row + r, column=start_col + c, value=cell_value)
    elif isinstance(value, list):
        for r, cell_value in enumerate(value):
            sheet.cell(row=start_row + r, column=start_col, value=cell_value)
    else:
        sheet.cell(row=start_row, column=start_col, value=value)


def write_to_excel(
    instance: ExcelInstanceHandle,
    value: object,
    write_mode: str = "SpecifiedCell",
    column: str = "A",
    row: int = 1,
    cell_name: str = "",
    write_to_all_cells: bool = False,
) -> None:
    sheet = instance.active_sheet
    try:
        if write_mode == "ActiveCell":
            raise NotImplementedError(
                "WriteExcelMode.ActiveCell writes to the live Excel UI's active cell; "
                "not meaningful for a file-based (openpyxl) backend"
            )
        if write_mode == "SpecifiedCell":
            start_col, start_row = column_index_from_string(column), row
        elif write_mode == "NamedCells":
            try:
                target_sheet, start_col, start_row = _defined_name_start(instance.workbook, cell_name)
            except KeyError as exc:
                raise WriteToExcelError(f"named cell not found: {cell_name!r}") from exc
            sheet = target_sheet
        else:
            raise ValueError(f"Unknown WriteExcelMode: {write_mode!r}")

        if write_to_all_cells:
            _write_block(sheet, start_col, start_row, value)
        else:
            sheet.cell(row=start_row, column=start_col, value=value)
    except (WriteToExcelError, NotImplementedError):
        raise
    except Exception as exc:
        raise WriteToExcelError(str(exc)) from exc


def append_cells(*_args: object, **_kwargs: object) -> None:
    raise NotImplementedError(
        "AppendCells has no Value input in the decompiled source "
        "(IExcelActions.AppendCellsToWorksheet/AppendCellsToNamedCells take no value parameter) "
        "- real-hardware behavior (implicit clipboard/selection source?) is unconfirmed"
    )


def add_worksheet(instance: ExcelInstanceHandle, name: str, worksheet_position: str = "First") -> None:
    if name in instance.workbook.sheetnames:
        raise WorksheetAlreadyExistsError(name)
    try:
        if worksheet_position == "First":
            instance.workbook.create_sheet(title=name, index=0)
        elif worksheet_position == "Last":
            instance.workbook.create_sheet(title=name)
        else:
            raise ValueError(f"Unknown WorksheetPosition: {worksheet_position!r}")
    except Exception as exc:
        raise AddWorksheetError(str(exc)) from exc


def _resolve_worksheet_name(
    workbook: openpyxl.Workbook, find_worksheet_by: str, name: str = "", index: int = 0
) -> str:
    if find_worksheet_by == "Name":
        if name not in workbook.sheetnames:
            raise WorksheetNotFoundError(name)
        return name
    if find_worksheet_by == "Index":
        try:
            return workbook.sheetnames[index]
        except IndexError as exc:
            raise WorksheetNotFoundError(str(index)) from exc
    raise ValueError(f"Unknown FindWorksheetBy: {find_worksheet_by!r}")


def delete_worksheet(
    instance: ExcelInstanceHandle, find_worksheet_by: str = "Name", name: str = "", index: int = 0
) -> None:
    resolved_name = _resolve_worksheet_name(instance.workbook, find_worksheet_by, name, index)
    try:
        del instance.workbook[resolved_name]
    except Exception as exc:
        raise DeleteWorksheetError(str(exc)) from exc
    if instance.active_sheet_name == resolved_name:
        instance.active_sheet_name = instance.workbook.active.title


def rename_worksheet(
    instance: ExcelInstanceHandle,
    new_name: str,
    find_worksheet_by: str = "Name",
    name: str = "",
    index: int = 0,
) -> None:
    resolved_name = _resolve_worksheet_name(instance.workbook, find_worksheet_by, name, index)
    try:
        instance.workbook[resolved_name].title = new_name
    except Exception as exc:
        raise RenameWorksheetError(str(exc)) from exc
    if instance.active_sheet_name == resolved_name:
        instance.active_sheet_name = new_name


def set_active_worksheet(
    instance: ExcelInstanceHandle, find_worksheet_by: str = "Name", name: str = "", index: int = 0
) -> None:
    resolved_name = _resolve_worksheet_name(instance.workbook, find_worksheet_by, name, index)
    try:
        instance.active_sheet_name = resolved_name
    except Exception as exc:
        raise ActivateWorksheetError(str(exc)) from exc


def get_active_worksheet(instance: ExcelInstanceHandle) -> tuple[str, int]:
    try:
        name = instance.active_sheet_name
        return name, instance.workbook.sheetnames.index(name)
    except Exception as exc:
        raise RetrieveActiveWorksheetError(str(exc)) from exc


def get_all_worksheets(instance: ExcelInstanceHandle) -> list[str]:
    try:
        return list(instance.workbook.sheetnames)
    except Exception as exc:
        raise RetrieveAllWorksheetsError(str(exc)) from exc


def get_column_name(cell_column_index: int) -> str:
    # Excelの列インデックス<->列名変換は公開された標準アルゴリズム(PAD固有の挙動ではない)。
    return get_column_letter(cell_column_index)


def get_first_free_column_row(instance: ExcelInstanceHandle) -> tuple[int, int]:
    # 正確なアルゴリズムは実機未確認の近似: 使用範囲の次の行・列。
    try:
        sheet = instance.active_sheet
        return sheet.max_column + 1, sheet.max_row + 1
    except Exception as exc:
        raise RetrieveFirstFreeColumnRowError(str(exc)) from exc


def get_first_free_row_on_column(instance: ExcelInstanceHandle, column: str) -> int:
    try:
        sheet = instance.active_sheet
        col_index = column_index_from_string(column)
        row = 1
        while sheet.cell(row=row, column=col_index).value is not None:
            row += 1
        return row
    except Exception as exc:
        raise RetrieveFirstFreeRowError(str(exc)) from exc
