"""`pad_action_lib.excel_actions`の単体テスト(`openpyxl`で実ファイルを使う)。"""
from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from dump_daemon.pad_action_lib import excel_actions as xl


def test_launch_new_document_write_save_reload_round_trip(tmp_path: Path) -> None:
    instance = xl.launch_excel("NewDocument")
    xl.write_to_excel(instance, "hello", column="A", row=1)
    xl.write_to_excel(instance, 42, column="B", row=1)
    dest = tmp_path / "out.xlsx"
    xl.save_excel(instance, "SaveAs", str(dest))
    xl.close_excel(instance, "DoNotSave")

    reopened = xl.launch_excel("StoredDocument", path=str(dest))
    assert xl.read_from_excel(reopened, "SingleCell", start_column="A", start_row=1) == "hello"
    assert xl.read_from_excel(reopened, "SingleCell", start_column="B", start_row=1) == 42


def test_launch_stored_document_missing_file_raises_open_document_error() -> None:
    with pytest.raises(xl.OpenDocumentError):
        xl.launch_excel("StoredDocument", path="/nonexistent/file.xlsx")


def test_launch_unknown_mode_raises_launch_excel_error() -> None:
    with pytest.raises(xl.LaunchExcelError):
        xl.launch_excel("NotAMode")


def test_close_excel_save_mode_writes_to_known_path(tmp_path: Path) -> None:
    dest = tmp_path / "a.xlsx"
    instance = xl.launch_excel("NewDocument")
    xl.save_excel(instance, "SaveAs", str(dest))
    xl.write_to_excel(instance, "value", column="A", row=1)
    xl.close_excel(instance, "Save")

    wb = openpyxl.load_workbook(dest)
    assert wb.active["A1"].value == "value"


def test_read_all_cells_returns_datatable_with_column_letters_as_keys(tmp_path: Path) -> None:
    instance = xl.launch_excel("NewDocument")
    xl.write_to_excel(instance, "x", column="A", row=1)
    xl.write_to_excel(instance, "y", column="B", row=1)
    xl.write_to_excel(instance, 1, column="A", row=2)
    xl.write_to_excel(instance, 2, column="B", row=2)

    table = xl.read_from_excel(instance, "AllCells")
    assert table == [{"A": "x", "B": "y"}, {"A": 1, "B": 2}]


def test_read_range_with_header_row(tmp_path: Path) -> None:
    instance = xl.launch_excel("NewDocument")
    xl.write_to_excel(instance, "Name", column="A", row=1)
    xl.write_to_excel(instance, "Age", column="B", row=1)
    xl.write_to_excel(instance, "Alice", column="A", row=2)
    xl.write_to_excel(instance, 30, column="B", row=2)

    table = xl.read_from_excel(
        instance,
        "RangeOfCells",
        start_column="A",
        start_row=1,
        end_column="B",
        end_row=2,
        first_line_is_header=True,
    )
    assert table == [{"Name": "Alice", "Age": 30}]


def test_write_to_all_cells_writes_2d_block(tmp_path: Path) -> None:
    instance = xl.launch_excel("NewDocument")
    xl.write_to_excel(instance, [[1, 2], [3, 4]], column="A", row=1, write_to_all_cells=True)
    assert instance.active_sheet["A1"].value == 1
    assert instance.active_sheet["B1"].value == 2
    assert instance.active_sheet["A2"].value == 3
    assert instance.active_sheet["B2"].value == 4


def test_write_static_formula_is_stored_as_text_not_evaluated(tmp_path: Path) -> None:
    instance = xl.launch_excel("NewDocument")
    xl.write_to_excel(instance, 1, column="A", row=1)
    xl.write_to_excel(instance, 2, column="A", row=2)
    xl.write_to_excel(instance, "=A1+A2", column="A", row=3)
    assert instance.active_sheet["A3"].value == "=A1+A2"


def test_write_to_active_cell_mode_not_implemented() -> None:
    instance = xl.launch_excel("NewDocument")
    with pytest.raises(NotImplementedError):
        xl.write_to_excel(instance, "x", write_mode="ActiveCell")


def test_read_selection_mode_not_implemented() -> None:
    instance = xl.launch_excel("NewDocument")
    with pytest.raises(NotImplementedError):
        xl.read_from_excel(instance, "Selection")


def test_read_formatted_text_mode_not_implemented() -> None:
    instance = xl.launch_excel("NewDocument")
    with pytest.raises(NotImplementedError):
        xl.read_from_excel(instance, "SingleCell", get_cell_contents_mode="PlainText")


def test_named_cell_write_then_read_round_trip() -> None:
    instance = xl.launch_excel("NewDocument")
    sheet = instance.active_sheet
    defined_name = openpyxl.workbook.defined_name.DefinedName(
        "MyCell", attr_text=f"'{sheet.title}'!$B$2"
    )
    instance.workbook.defined_names["MyCell"] = defined_name

    xl.write_to_excel(instance, "named-value", write_mode="NamedCells", cell_name="MyCell")
    assert xl.read_from_excel(instance, "NamedCells", cell_name="MyCell") == "named-value"


def test_write_to_unknown_named_cell_raises() -> None:
    instance = xl.launch_excel("NewDocument")
    with pytest.raises(xl.WriteToExcelError):
        xl.write_to_excel(instance, "x", write_mode="NamedCells", cell_name="DoesNotExist")


def test_read_unknown_named_cell_raises() -> None:
    instance = xl.launch_excel("NewDocument")
    with pytest.raises(xl.ReadCellsError):
        xl.read_from_excel(instance, "NamedCells", cell_name="DoesNotExist")


def test_append_cells_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        xl.append_cells()


def test_add_worksheet_first_and_last() -> None:
    instance = xl.launch_excel("NewDocument")
    original = instance.workbook.sheetnames[0]
    xl.add_worksheet(instance, "FirstSheet", worksheet_position="First")
    xl.add_worksheet(instance, "LastSheet", worksheet_position="Last")
    assert instance.workbook.sheetnames == ["FirstSheet", original, "LastSheet"]


def test_add_worksheet_duplicate_name_raises() -> None:
    instance = xl.launch_excel("NewDocument")
    name = instance.workbook.sheetnames[0]
    with pytest.raises(xl.WorksheetAlreadyExistsError):
        xl.add_worksheet(instance, name)


def test_delete_worksheet_by_name_and_index() -> None:
    instance = xl.launch_excel("NewDocument")
    xl.add_worksheet(instance, "Extra", worksheet_position="Last")
    xl.delete_worksheet(instance, find_worksheet_by="Name", name="Extra")
    assert "Extra" not in instance.workbook.sheetnames

    xl.add_worksheet(instance, "Extra2", worksheet_position="Last")
    index = instance.workbook.sheetnames.index("Extra2")
    xl.delete_worksheet(instance, find_worksheet_by="Index", index=index)
    assert "Extra2" not in instance.workbook.sheetnames


def test_delete_worksheet_not_found_raises() -> None:
    instance = xl.launch_excel("NewDocument")
    with pytest.raises(xl.WorksheetNotFoundError):
        xl.delete_worksheet(instance, find_worksheet_by="Name", name="NoSuchSheet")
    with pytest.raises(xl.WorksheetNotFoundError):
        xl.delete_worksheet(instance, find_worksheet_by="Index", index=99)


def test_rename_worksheet_updates_active_sheet_tracking() -> None:
    instance = xl.launch_excel("NewDocument")
    original = instance.workbook.sheetnames[0]
    xl.rename_worksheet(instance, "Renamed", find_worksheet_by="Name", name=original)
    assert instance.active_sheet_name == "Renamed"
    assert instance.workbook.sheetnames == ["Renamed"]


def test_rename_worksheet_not_found_raises() -> None:
    instance = xl.launch_excel("NewDocument")
    with pytest.raises(xl.WorksheetNotFoundError):
        xl.rename_worksheet(instance, "New", find_worksheet_by="Name", name="NoSuchSheet")


def test_set_and_get_active_worksheet() -> None:
    instance = xl.launch_excel("NewDocument")
    xl.add_worksheet(instance, "Second", worksheet_position="Last")
    xl.set_active_worksheet(instance, find_worksheet_by="Name", name="Second")
    name, index = xl.get_active_worksheet(instance)
    assert name == "Second"
    assert index == 1


def test_set_active_worksheet_not_found_raises() -> None:
    instance = xl.launch_excel("NewDocument")
    with pytest.raises(xl.WorksheetNotFoundError):
        xl.set_active_worksheet(instance, find_worksheet_by="Name", name="NoSuchSheet")


def test_get_all_worksheets() -> None:
    instance = xl.launch_excel("NewDocument")
    xl.add_worksheet(instance, "Second", worksheet_position="Last")
    assert xl.get_all_worksheets(instance) == [instance.workbook.sheetnames[0], "Second"]


def test_get_column_name() -> None:
    assert xl.get_column_name(1) == "A"
    assert xl.get_column_name(26) == "Z"
    assert xl.get_column_name(27) == "AA"


def test_get_first_free_column_row() -> None:
    instance = xl.launch_excel("NewDocument")
    xl.write_to_excel(instance, "x", column="A", row=1)
    xl.write_to_excel(instance, "y", column="C", row=2)
    column, row = xl.get_first_free_column_row(instance)
    assert (column, row) == (4, 3)


def test_get_first_free_row_on_column() -> None:
    instance = xl.launch_excel("NewDocument")
    xl.write_to_excel(instance, "x", column="A", row=1)
    xl.write_to_excel(instance, "y", column="A", row=2)
    assert xl.get_first_free_row_on_column(instance, "A") == 3
    assert xl.get_first_free_row_on_column(instance, "B") == 1


def test_delete_column_shifts_remaining_columns_left() -> None:
    instance = xl.launch_excel("NewDocument")
    xl.write_to_excel(instance, "a", column="A", row=1)
    xl.write_to_excel(instance, "b", column="B", row=1)
    xl.delete_column(instance, "A")
    assert xl.read_from_excel(instance, "SingleCell", start_column="A", start_row=1) == "b"


def test_delete_column_invalid_letter_raises_column_not_found_error() -> None:
    instance = xl.launch_excel("NewDocument")
    with pytest.raises(xl.ColumnNotFoundError):
        xl.delete_column(instance, "1A")


def test_insert_column_shifts_existing_columns_right() -> None:
    instance = xl.launch_excel("NewDocument")
    xl.write_to_excel(instance, "a", column="A", row=1)
    xl.insert_column(instance, "A")
    assert xl.read_from_excel(instance, "SingleCell", start_column="A", start_row=1) is None
    assert xl.read_from_excel(instance, "SingleCell", start_column="B", start_row=1) == "a"


def test_insert_column_invalid_letter_raises_column_not_found_error() -> None:
    instance = xl.launch_excel("NewDocument")
    with pytest.raises(xl.ColumnNotFoundError):
        xl.insert_column(instance, "")


def test_delete_row_shifts_remaining_rows_up() -> None:
    instance = xl.launch_excel("NewDocument")
    xl.write_to_excel(instance, "a", column="A", row=1)
    xl.write_to_excel(instance, "b", column="A", row=2)
    xl.delete_row(instance, 1)
    assert xl.read_from_excel(instance, "SingleCell", start_column="A", start_row=1) == "b"


def test_delete_row_non_positive_index_raises_row_not_found_error() -> None:
    instance = xl.launch_excel("NewDocument")
    with pytest.raises(xl.RowNotFoundError):
        xl.delete_row(instance, 0)


def test_insert_row_shifts_existing_rows_down() -> None:
    instance = xl.launch_excel("NewDocument")
    xl.write_to_excel(instance, "a", column="A", row=1)
    xl.insert_row(instance, 1)
    assert xl.read_from_excel(instance, "SingleCell", start_column="A", start_row=1) is None
    assert xl.read_from_excel(instance, "SingleCell", start_column="A", start_row=2) == "a"


def test_insert_row_non_positive_index_raises_row_not_found_error() -> None:
    instance = xl.launch_excel("NewDocument")
    with pytest.raises(xl.RowNotFoundError):
        xl.insert_row(instance, -1)


def _add_table(instance: xl.ExcelInstanceHandle, name: str, ref: str) -> None:
    from openpyxl.worksheet.table import Table

    instance.active_sheet.add_table(Table(displayName=name, ref=ref))


def test_get_table_range_returns_header_inclusive_bounds() -> None:
    # design/dsl_format_findings.md 知見180(decompile確認済み): COMの`ListObject.Range`
    # (ヘッダー行を含むテーブル全体)を読むだけ——`openpyxl`の`Table.ref`も同じ意味。
    instance = xl.launch_excel("NewDocument")
    for col, row, value in [("A", 1, "Name"), ("B", 1, "Age"), ("A", 2, "Carol"), ("B", 2, 30)]:
        xl.write_to_excel(instance, value, column=col, row=row)
    _add_table(instance, "MyTable", "A1:B2")
    assert xl.get_table_range(instance, "MyTable") == (1, 1, 2, 2)


def test_get_table_range_not_found_raises() -> None:
    instance = xl.launch_excel("NewDocument")
    with pytest.raises(xl.GetTableRangeError):
        xl.get_table_range(instance, "NoSuchTable")


def test_get_table_range_searches_active_sheet_only() -> None:
    # decompile確認済み: ワークブック全体ではなくアクティブシートのみを検索する。
    instance = xl.launch_excel("NewDocument")
    xl.add_worksheet(instance, "Sheet2", worksheet_position="Last")
    xl.set_active_worksheet(instance, find_worksheet_by="Name", name="Sheet2")
    _add_table(instance, "OnSheet2", "A1:A1")
    xl.set_active_worksheet(instance, find_worksheet_by="Index", index=0)
    with pytest.raises(xl.GetTableRangeError):
        xl.get_table_range(instance, "OnSheet2")


def test_get_table_range_is_pivot_not_implemented() -> None:
    instance = xl.launch_excel("NewDocument")
    with pytest.raises(NotImplementedError):
        xl.get_table_range(instance, "AnyTable", is_pivot=True)
