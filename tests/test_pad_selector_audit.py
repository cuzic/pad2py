"""`tools/pad_selector_audit.py`自身の単体テスト。

VM上のリフレクション出力(実際のdumpファイル)に依存せず、小さな埋め込みフィクスチャで
ツールのロジック(文字列リテラル抽出・dump解析・突き合わせ)だけを検証する。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from tools.pad_selector_audit import (
    audit,
    extract_wired_action_ids,
    parse_selector_dump,
)


def _write(tmp: str, name: str, content: str) -> Path:
    path = Path(tmp) / name
    path.write_text(content, encoding="utf-8")
    return path


def test_extract_wired_action_ids_finds_flat_and_dict_literal_forms() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(
            tmp,
            "sample.py",
            "def generate(node, indent, ctx):\n"
            "    action_id = node.action_id\n"
            "    if action_id == 'Excel.AddWorksheet':\n"
            "        return None\n"
            "    _FIXED = {\n"
            "        'Excel.SaveExcel.Save': 'Save',\n"
            "        'Excel.SaveExcel.SaveAs': 'SaveAs',\n"
            "    }\n"
            "    not_an_action_id = 'just some text'\n"
            "    return None\n",
        )
        found = extract_wired_action_ids(path)
    assert found == {"Excel.AddWorksheet", "Excel.SaveExcel.Save", "Excel.SaveExcel.SaveAs"}
    assert "just some text" not in found


def test_parse_selector_dump_reads_pipe_delimited_lines() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(
            tmp,
            "dump.txt",
            "SaveExcel | SaveExcelSelector | ActionName=Save\n"
            "SaveExcel | SaveExcelAsSelector | ActionName=SaveAs\n"
            "\n"
            "not a valid line without pipes\n",
        )
        entries = parse_selector_dump(path)
    assert entries == [
        ("SaveExcel", "SaveExcelSelector", "Save"),
        ("SaveExcel", "SaveExcelAsSelector", "SaveAs"),
    ]


def test_audit_reports_missing_and_wired_selectors_correctly() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        actions_py = _write(
            tmp,
            "excel.py",
            "def generate(node, indent, ctx):\n"
            "    action_id = node.action_id\n"
            "    if action_id == 'Excel.SaveExcel.Save':\n"
            "        return None\n"
            "    return None\n",
        )
        dump = _write(
            tmp,
            "dump.txt",
            "SaveExcel | SaveExcelSelector | ActionName=Save\n"
            "SaveExcel | SaveExcelAsSelector | ActionName=SaveAs\n",
        )
        missing = audit("Excel", actions_py, dump)
    assert missing == ["Excel.SaveExcel.SaveAs"]


def test_audit_applies_id_override_for_action_attribute_id_mismatch() -> None:
    # 知見156: `[Action(Id = "ExtractImagesFromPDF")]`のように、クラス名
    # (`ExtractImagesFromPDFAction`)とは異なる明示的なIdを持つケース。
    with tempfile.TemporaryDirectory() as tmp:
        actions_py = _write(
            tmp,
            "pdf.py",
            "def generate(node, indent, ctx):\n"
            "    action_id = node.action_id\n"
            "    if action_id == 'Pdf.ExtractImagesFromPDF.ExtractImages':\n"
            "        return None\n"
            "    return None\n",
        )
        dump = _write(
            tmp,
            "dump.txt",
            "ExtractImagesFromPDFAction | ExtractImagesSelector | ActionName=ExtractImages\n",
        )
        missing_without_override = audit("Pdf", actions_py, dump)
        missing_with_override = audit(
            "Pdf", actions_py, dump, {"ExtractImagesFromPDFAction": "ExtractImagesFromPDF"}
        )
    assert missing_without_override == ["Pdf.ExtractImagesFromPDFAction.ExtractImages"]
    assert missing_with_override == []


def test_real_excel_dump_flags_only_known_out_of_scope_selectors() -> None:
    # design/dsl_format_findings.md 知見155: `Excel.*`は知見155で修正済みの8グループ
    # (LaunchExcel/CloseExcel/SaveExcel/ReadFromExcel/WriteToExcel/DeleteWorksheet/
    # RenameWorksheet/SetActiveWorksheet)のうち、ライブCOM専用のスコープ外4件
    # (LaunchUnderExistingProcess系2件・Read(Selection)・Write(ActiveCell))は依然
    # 未結線のまま——このテストは「それ以外の同グループのセレクタは全て結線済み」
    # という回帰防止を主目的とする(他の84件のCOM専用グループはスコープ外として
    # 許容する)。
    repo_root = Path(__file__).resolve().parent.parent
    dump = repo_root / "tools" / "selector_dumps" / "Excel.txt"
    actions_py = repo_root / "dump_daemon" / "pad_codegen" / "actions" / "excel.py"
    missing = audit("Excel", actions_py, dump)

    fixed_groups = (
        "LaunchExcel.",
        "CloseExcel.",
        "SaveExcel.",
        "ReadFromExcel.",
        "WriteToExcel.",
        "DeleteWorksheet.",
        "RenameWorksheet.",
        "SetActiveWorksheet.",
    )
    known_out_of_scope = {
        "Excel.LaunchExcel.LaunchUnderExistingProcess",
        "Excel.LaunchExcel.LaunchAndOpenUnderExistingProcess",
        "Excel.ReadFromExcel.Read",
        "Excel.WriteToExcel.Write",
    }
    missing_in_fixed_groups = {
        m for m in missing if any(f"Excel.{g}" in m for g in fixed_groups)
    }
    assert missing_in_fixed_groups == known_out_of_scope
