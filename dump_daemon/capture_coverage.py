"""Tier1/Tier2モジュール(Text/DateTime/Variables/File/Folder/Compression/Cryptography/
Database/Web/XML/Cmd/Clipboard)の実機DSLキャプチャがどこまで進んでいるかを計測するツール。

`codegen_coverage.py`が「pad_codegenがどこまで実コードを生成できているか」を計測するのに
対し、本ツールは一段手前の「どのアクションの実機DSLをまだ一度も取得していないか」を計測する
——つまりdesign/dsl_format_findings.md 知見62以降で進めている実機キャプチャ作業そのものの
進捗管理・残タスクの可視化が目的。

対象アクションの一覧(`TARGET_ACTIONS`)は、過去の静的解析調査(各アクションクラスの属性・
プロパティから予測したaction_id)に基づく。exact action_idは実機未確認のものを多く含むため、
`expected_id_prefix`は「このプレフィックスで始まるaction_idが`tests/fixtures/`のいずれかに
一度でも現れればキャプチャ済みとみなす」という緩い判定に使う(予測が多少外れていても
`search_term`でPAD上の実際のアクションを特定できれば、キャプチャ後にこの一覧を直せばよい)。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .pad_dsl import ActionRecord, IfActionRecord, WaitActionRecord, parse_dsl

_ACTION_ID_RECORD_TYPES = (ActionRecord, IfActionRecord, WaitActionRecord)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


@dataclass(frozen=True)
class TargetAction:
    module: str
    name: str
    search_term: str
    expected_id_prefix: str


# (module, name, PAD Actionsパネルでの検索語, 予測したaction_idプレフィックス)
TARGET_ACTIONS: list[TargetAction] = [
    # --- Text ---
    TargetAction("Text", "AppendLine", "Append line", "Text.AppendLine"),
    TargetAction("Text", "ChangeCase", "Change case", "Text.ChangeCase"),
    TargetAction("Text", "CreateHTMLContent", "Create HTML content", "Text.CreateHTMLContent"),
    TargetAction("Text", "CreateRandomText", "Random text", "Text.Random"),
    TargetAction("Text", "CropText", "Crop text", "Text.CropText"),
    TargetAction("Text", "EscapeForRegularExpression", "Escape for regular", "Text.EscapeForRegularExpression"),
    TargetAction("Text", "GetSubtext", "Get subtext", "Text.GetSubtext"),
    TargetAction("Text", "JoinText", "Join text", "Text.JoinText"),
    TargetAction("Text", "Pad", "Pad text", "Text.Pad"),
    TargetAction("Text", "ParseText", "Parse text", "Text.ParseText"),
    TargetAction("Text", "RecognizeEntitiesInText", "Recognize entities", "Text.RecognizeEntitiesInText"),
    TargetAction("Text", "ReplaceText", "Replace text", "Text.Replace"),
    TargetAction("Text", "ReverseText", "Reverse text", "Text.Reverse"),
    TargetAction("Text", "SplitText", "Split text", "Text.SplitText"),
    TargetAction("Text", "Trim", "Trim text", "Text.Trim"),
    TargetAction("Text", "ConvertNumberToText", "Convert number to text", "Text.FromNumber"),
    TargetAction("Text", "ConvertTextToNumber", "Convert text to number", "Text.ToNumber"),
    TargetAction("Text", "ConvertDateTimeToText", "Convert datetime to text", "Text.ConvertDateTimeToText"),
    TargetAction("Text", "ConvertTextToDateTime", "Convert text to datetime", "Text.ConvertTextToDateTime"),
    # --- DateTime ---
    TargetAction("DateTime", "GetCurrentDateTime", "Get current date and time", "DateTime.GetCurrentDateTime"),
    TargetAction("DateTime", "AddToDateTime", "Add to date", "DateTime.Add"),
    TargetAction("DateTime", "SubtractDates", "Subtract dates", "DateTime.Subtract"),
    # --- Variables ---
    TargetAction("Variables", "TruncateNumber", "Truncate number", "Variables.TruncateNumber"),
    TargetAction("Variables", "GenerateRandomNumber", "Generate random number", "Variables.GenerateRandomNumber"),
    TargetAction("Variables", "IncreaseVariable", "Increase variable", "Variables.IncreaseVariable"),
    TargetAction("Variables", "DecreaseVariable", "Decrease variable", "Variables.DecreaseVariable"),
    TargetAction("Variables", "CreateNewList", "Create new list", "Variables.CreateNewList"),
    TargetAction("Variables", "AddItemToList", "Add item to list", "Variables.AddItemToList"),
    TargetAction("Variables", "RemoveItemFromList", "Remove item from list", "Variables.RemoveItemFromList"),
    TargetAction("Variables", "ClearList", "Clear list", "Variables.ClearList"),
    TargetAction("Variables", "ReverseList", "Reverse list", "Variables.ReverseList"),
    TargetAction("Variables", "ShuffleList", "Shuffle list", "Variables.ShuffleList"),
    TargetAction("Variables", "MergeLists", "Merge lists", "Variables.MergeLists"),
    TargetAction("Variables", "SubtractLists", "Subtract lists", "Variables.SubtractLists"),
    TargetAction("Variables", "FindCommonListItems", "Find common list items", "Variables.FindCommonListItems"),
    TargetAction("Variables", "RemoveDuplicateItemsFromList", "Remove duplicate items from list", "Variables.RemoveDuplicateItemsFromList"),
    TargetAction("Variables", "SortList", "Sort list", "Variables.SortList"),
    TargetAction("Variables", "CreateNewDatatable", "Create new datatable", "Variables.CreateNewDatatable"),
    TargetAction("Variables", "ClearDataTable", "Clear datatable", "Variables.ClearDataTable"),
    TargetAction("Variables", "AddRowToDataTable", "Add row to datatable", "Variables.AddRowToDataTable"),
    TargetAction("Variables", "DeleteRowFromDataTable", "Delete row from datatable", "Variables.DeleteRowFromDataTable"),
    TargetAction("Variables", "ModifyDataTableItem", "Modify datatable item", "Variables.ModifyDataTableItem"),
    TargetAction("Variables", "FindOrReplaceInDataTable", "Find or replace in datatable", "Variables.FindOrReplaceInDataTable"),
    TargetAction("Variables", "DeleteEmptyRowsFromDataTable", "Delete empty rows from datatable", "Variables.DeleteEmptyRowsFromDataTable"),
    TargetAction("Variables", "DeleteDuplicateRowsFromDataTable", "Delete duplicate rows from datatable", "Variables.DeleteDuplicateRowsFromDataTable"),
    TargetAction("Variables", "AddColumnToDataTable", "Add column to datatable", "Variables.AddColumnToDataTable"),
    TargetAction("Variables", "DeleteColumnFromDataTable", "Delete column from datatable", "Variables.DeleteColumnFromDataTable"),
    TargetAction("Variables", "SortDataTable", "Sort datatable", "Variables.SortDataTable"),
    TargetAction("Variables", "FilterDataTable", "Filter datatable", "Variables.FilterDataTable"),
    TargetAction("Variables", "MergeDataTables", "Merge datatables", "Variables.MergeDataTables"),
    TargetAction("Variables", "JoinDataTable", "Join datatable", "Variables.JoinDataTable"),
    TargetAction("Variables", "RetrieveDataTableColumnIntoList", "Retrieve datatable column into list", "Variables.RetrieveDataTableColumnIntoList"),
    TargetAction("Variables", "GenerateDataTableFromCSV", "Generate datatable from CSV", "Variables.GenerateDataTableFromCSV"),
    TargetAction("Variables", "ConvertDataTableToCSV", "Convert datatable to CSV", "Variables.ConvertDataTableToCSV"),
    TargetAction("Variables", "ConvertJsonToCustomObject", "Convert JSON to custom object", "Variables.ConvertJsonToCustomObject"),
    TargetAction("Variables", "ConvertCustomObjectToJson", "Convert custom object to JSON", "Variables.ConvertCustomObjectToJson"),
    # --- File ---
    TargetAction("File", "Copy", "Copy file(s)", "File.Copy"),
    TargetAction("File", "Move", "Move file(s)", "File.Move"),
    TargetAction("File", "Delete", "Delete file(s)", "File.Delete"),
    TargetAction("File", "RenameFiles", "Rename file(s)", "File.RenameFiles"),
    TargetAction("File", "ConvertFileToBase64", "Convert file to base64", "File.ConvertToBase64"),
    TargetAction("File", "ConvertBase64ToFile", "Convert base64 to file", "File.ConvertFromBase64"),
    TargetAction("File", "ConvertFileToBinary", "Convert file to binary", "File.ConvertToBinary"),
    TargetAction("File", "ConvertBinaryToFile", "Convert binary to file", "File.ConvertFromBinary"),
    TargetAction("File", "ReadTextFromFile", "Read text from file", "File.ReadTextFromFile"),
    TargetAction("File", "WriteTextToFile", "Write text to file", "File.WriteText"),
    TargetAction("File", "ReadFromCSVFile", "Read from CSV file", "File.ReadFromCSVFile"),
    TargetAction("File", "WriteToCSVFile", "Write to CSV file", "File.WriteToCSVFile"),
    TargetAction("File", "GetFilePathPart", "Get file path part", "File.GetPathPart"),
    TargetAction("File", "GetTempFilePath", "Get temporary file path", "File.GetTempPath"),
    TargetAction("File", "IfFile", "If file", "File.IfFile"),
    TargetAction("File", "WaitForFile", "Wait for file", "File.WaitForFile"),
    # --- Folder ---
    TargetAction("Folder", "CopyFolder", "Copy folder", "Folder.Copy"),
    TargetAction("Folder", "CreateFolder", "Create folder", "Folder.Create"),
    TargetAction("Folder", "DeleteFolder", "Delete folder", "Folder.Delete"),
    TargetAction("Folder", "EmptyFolder", "Empty folder", "Folder.Empty"),
    TargetAction("Folder", "MoveFolder", "Move folder", "Folder.Move"),
    TargetAction("Folder", "RenameFolder", "Rename folder", "Folder.Rename"),
    TargetAction("Folder", "GetFilesInFolder", "Get files in folder", "Folder.GetFiles"),
    TargetAction("Folder", "GetSubfoldersInFolder", "Get subfolders in folder", "Folder.GetSubfolders"),
    TargetAction("Folder", "GetSpecialFolder", "Get special folder", "Folder.GetSpecialFolder"),
    TargetAction("Folder", "IfFolderExists", "If folder exists", "Folder.IfFolderExists"),
    # --- Compression ---
    TargetAction("Compression", "ZipFiles", "Zip files", "Compression.ZipFiles"),
    TargetAction("Compression", "UnzipFiles", "Unzip files", "Compression.UnzipFiles"),
    # --- Cryptography ---
    TargetAction("Cryptography", "EncryptText", "Encrypt text", "Cryptography.EncryptText"),
    TargetAction("Cryptography", "EncryptFromFile", "Encrypt file", "Cryptography.EncryptFromFile"),
    TargetAction("Cryptography", "DecryptText", "Decrypt text", "Cryptography.DecryptText"),
    TargetAction("Cryptography", "DecryptToFile", "Decrypt to file", "Cryptography.DecryptToFile"),
    TargetAction("Cryptography", "HashText", "Hash text", "Cryptography.HashText"),
    TargetAction("Cryptography", "HashFromFile", "Hash file", "Cryptography.HashFromFile"),
    TargetAction("Cryptography", "HashTextWithKey", "Hash text with key", "Cryptography.HashTextWithKey"),
    TargetAction("Cryptography", "HashFromFileWithKey", "Hash file with key", "Cryptography.HashFromFileWithKey"),
    # --- Database ---
    TargetAction("Database", "OpenConnection", "Open connection", "Database.Connect"),
    TargetAction("Database", "ExecuteSqlStatement", "Execute SQL statement", "Database.Execute"),
    TargetAction("Database", "CloseConnection", "Close connection", "Database.Close"),
    # --- Web ---
    TargetAction("Web", "DownloadFromWeb", "Download from web", "Web.Download"),
    TargetAction("Web", "InvokeWebService", "Invoke web service", "Web.InvokeWebService"),
    TargetAction("Web", "InvokeSoapService", "Invoke SOAP service", "Web.InvokeSoapService"),
    # --- XML ---
    TargetAction("XML", "ReadXmlFromFile", "Read XML from file", "XML.ReadFromFile"),
    TargetAction("XML", "WriteXmlToFile", "Write XML to file", "XML.WriteXmlToFile"),
    TargetAction("XML", "GetXmlElementValue", "Get XML element value", "XML.GetXmlElementValue"),
    TargetAction("XML", "SetElementValue", "Set XML element value", "XML.SetElementValue"),
    TargetAction("XML", "GetXmlElementAttribute", "Get XML element attribute", "XML.GetXmlElementAttribute"),
    TargetAction("XML", "SetElementAttribute", "Set XML element attribute", "XML.SetElementAttribute"),
    TargetAction("XML", "RemoveElementAttribute", "Remove XML element attribute", "XML.RemoveElementAttribute"),
    TargetAction("XML", "InsertElement", "Insert XML element", "XML.InsertElement"),
    TargetAction("XML", "RemoveElement", "Remove XML element", "XML.RemoveElement"),
    TargetAction("XML", "ExecuteXPathQuery", "Execute XPath query", "XML.ExecuteXPathQuery"),
    # --- Cmd ---
    TargetAction("Cmd", "OpenCmdSession", "Open CMD session", "Cmd.Open"),
    TargetAction("Cmd", "WriteToCmdSession", "Write to CMD session", "Cmd.Write"),
    TargetAction("Cmd", "ReadFromCmdSession", "Read from CMD session", "Cmd.Read"),
    TargetAction("Cmd", "WaitForTextOnCmdSession", "Wait for text on CMD session", "Cmd.WaitForText"),
    TargetAction("Cmd", "CloseCmdSession", "Close CMD session", "Cmd.Close"),
    # --- Clipboard ---
    TargetAction("Clipboard", "GetClipboardText", "Get clipboard text", "Clipboard.GetText"),
    TargetAction("Clipboard", "SetClipboardText", "Set clipboard text", "Clipboard.SetText"),
    TargetAction("Clipboard", "ClearClipboardContents", "Clear clipboard", "Clipboard.Clear"),
]


def collect_captured_action_ids(fixtures_dir: Path) -> set[str]:
    """`tests/fixtures/`配下の全テキストファイルを`parse_dsl()`に通し、実際に現れた
    `ActionRecord.action_id`を集める(パース失敗する行は無視して先へ進む——このツール自体は
    計測用であり、パーサーのバグ検出が目的ではない)。
    """
    ids: set[str] = set()
    for path in sorted(fixtures_dir.glob("*.txt")):
        try:
            text = path.read_text(encoding="utf-8")
            records = parse_dsl(text)
        except Exception:
            continue
        for record in records:
            if isinstance(record, _ACTION_ID_RECORD_TYPES):
                ids.add(record.action_id)
    return ids


def is_captured(target: TargetAction, captured_ids: set[str]) -> bool:
    return any(aid.startswith(target.expected_id_prefix) for aid in captured_ids)


def compute_report(fixtures_dir: Path = FIXTURES_DIR) -> dict[str, list[tuple[TargetAction, bool]]]:
    captured_ids = collect_captured_action_ids(fixtures_dir)
    by_module: dict[str, list[tuple[TargetAction, bool]]] = defaultdict(list)
    for target in TARGET_ACTIONS:
        by_module[target.module].append((target, is_captured(target, captured_ids)))
    return by_module


def format_report(by_module: dict[str, list[tuple[TargetAction, bool]]]) -> str:
    total = sum(len(items) for items in by_module.values())
    total_done = sum(sum(1 for _, done in items if done) for items in by_module.values())
    lines = ["# Tier1/Tier2 実機DSLキャプチャ 完了率レポート", ""]
    pct = (total_done / total * 100) if total else 0.0
    lines.append(f"全体: {total_done}/{total} ({pct:.0f}%)")
    lines.append("")
    for module in sorted(by_module):
        items = by_module[module]
        done = sum(1 for _, ok in items if ok)
        lines.append(f"## {module} ({done}/{len(items)})")
        for target, ok in items:
            mark = "x" if ok else " "
            suffix = "" if ok else f" — 検索語案: 「{target.search_term}」"
            lines.append(f"- [{mark}] {target.name} ({target.expected_id_prefix}*){suffix}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    report = compute_report()
    print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
