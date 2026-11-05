"""`File.*`(単一ファイル操作)のcodegen。

`pad_action_lib.file_actions`へ委譲する。パラメータ名は design/
dsl_format_findings.md 知見69で実機キャプチャした`tests/fixtures/
tier1_file_batch6.txt`・知見70の`tier1_crypto_database_batch7.txt`から確認済み。

`Files`パラメータ(Copy/Move/RenameFiles)は実機で単一パスのサンプル値しか
確認できておらず、複数ファイル(リスト変数)を渡すケースの実際の型は未確認
——`pad_action_lib.file_actions`側の関数は`list[str]`を要求するため、生成コードは
実行時に`isinstance`で単一文字列/リストどちらでも動くよう正規化する(でっち上げた
一方だけの型を仮定しない)。

`File.ReadFromCSVFile.ReadCSV`/`File.WriteToCSVFile.WriteCSV`のヘッダー無しケース
(`FirstLineContainsColumnNames`/`IncludeColumnNames: False`)は知見84で実機確認済み
(列名は`"Column#1"`/`"Column#2"`...が割り当てられる)。`TrimFields`(各フィールドの
前後の空白除去)は知見93で実機確認済みのため`True`/`False`両方を結線した
(`file_actions.read_from_csv_file()`の`trim_fields`引数に委譲)。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import enum_last, safe_render


def _as_list_expr(rendered: str) -> str:
    return f"({rendered} if isinstance({rendered}, list) else [{rendered}])"


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("File."):
        return None
    prefix = INDENT * indent
    p = node.params

    if action_id == "File.Copy":
        files = safe_render(p.get("Files"))
        dest = safe_render(p.get("Destination"))
        if_exists = enum_last(p.get("IfFileExists"))
        if files is None or dest is None or if_exists is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = file_actions.copy_files({_as_list_expr(files)}, {dest}, "
            f"if_file_exists={if_exists!r})"
        ]

    if action_id == "File.Move":
        files = safe_render(p.get("Files"))
        dest = safe_render(p.get("Destination"))
        if_exists = enum_last(p.get("IfFileExists"))
        if files is None or dest is None or if_exists is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = file_actions.move_files({_as_list_expr(files)}, {dest}, "
            f"if_file_exists={if_exists!r})"
        ]

    if action_id == "File.Delete":
        files = safe_render(p.get("Files"))
        if files is None:
            return None
        return [f"{prefix}file_actions.delete_files({_as_list_expr(files)})"]

    if action_id == "File.RenameFiles.Rename":
        files = safe_render(p.get("Files"))
        new_name = safe_render(p.get("NewName"))
        keep_ext = safe_render(p.get("KeepExtension"))
        if_exists = enum_last(p.get("IfFileExists"))
        if files is None or new_name is None or keep_ext is None or if_exists is None:
            return None
        if not node.output_var:
            return None
        inner = INDENT * (indent + 1)
        return [
            f"{prefix}_rename_targets = {_as_list_expr(files)}",
            f"{prefix}{node.output_var} = []",
            f"{prefix}for _rename_src in _rename_targets:",
            f"{inner}_rename_dir, _rename_base = os.path.split(_rename_src)",
            f"{inner}_rename_new_base = file_actions.rename_set_new_name(_rename_base, {new_name}, "
            f"keep_extension={keep_ext})",
            f"{inner}{node.output_var}.append(str(file_actions.apply_rename("
            f"_rename_dir, _rename_base, _rename_new_base, if_file_exists={if_exists!r})))",
        ]

    if action_id == "File.ConvertToBase64":
        path = safe_render(p.get("File"))
        if path is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = file_actions.file_to_base64({path})"]

    if action_id == "File.ConvertFromBase64":
        data = safe_render(p.get("Base64Text"))
        path = safe_render(p.get("File"))
        if_exists = enum_last(p.get("IfFileExists"))
        if data is None or path is None or if_exists is None:
            return None
        return [f"{prefix}file_actions.base64_to_file({data}, {path}, if_file_exists={if_exists!r})"]

    if action_id == "File.ConvertToBinary":
        path = safe_render(p.get("File"))
        if path is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = file_actions.file_to_binary({path})"]

    if action_id == "File.ConvertFromBinary":
        data = safe_render(p.get("BinaryData"))
        path = safe_render(p.get("File"))
        if_exists = enum_last(p.get("IfFileExists"))
        if data is None or path is None or if_exists is None:
            return None
        return [f"{prefix}file_actions.binary_to_file({data}, {path}, if_file_exists={if_exists!r})"]

    if action_id == "File.GetTempPath":
        if not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = file_actions.get_temp_file_path()"]

    if action_id == "File.GetPathPart":
        path = safe_render(p.get("File"))
        if path is None:
            return None
        outputs = {
            "RootPath": node.output_vars.get("RootPath"),
            "Directory": node.output_vars.get("Directory"),
            "FileName": node.output_vars.get("FileName"),
            "FileNameWithoutExtension": node.output_vars.get("FileNameWithoutExtension"),
            "Extension": node.output_vars.get("Extension"),
        }
        if not any(outputs.values()):
            return None
        lines = [f"{prefix}_path_part = file_actions.get_file_path_part({path})"]
        for key, var_name in outputs.items():
            if var_name:
                lines.append(f"{prefix}{var_name} = _path_part[{key!r}]")
        return lines

    if action_id == "File.WriteText":
        path = safe_render(p.get("File"))
        text = safe_render(p.get("TextToWrite"))
        append_newline = safe_render(p.get("AppendNewLine"))
        encoding = enum_last(p.get("Encoding"))
        if_exists = enum_last(p.get("IfFileExists"))
        if None in (path, text, append_newline, encoding, if_exists):
            return None
        return [
            f"{prefix}file_actions.write_text_to_file({path}, {text}, append_new_line={append_newline}, "
            f"encoding={encoding!r}, if_file_exists={if_exists!r})"
        ]

    if action_id == "File.ReadTextFromFile.ReadText":
        path = safe_render(p.get("File"))
        encoding = enum_last(p.get("Encoding"))
        if path is None or encoding is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = file_actions.read_text_from_file({path}, encoding={encoding!r})"]

    if action_id == "File.ReadFromCSVFile.ReadCSV":
        path = safe_render(p.get("CSVFile"))
        encoding = enum_last(p.get("Encoding"))
        separator = enum_last(p.get("ColumnsSeparator"))
        first_line = safe_render(p.get("FirstLineContainsColumnNames"))
        trim_fields = p.get("TrimFields")
        if (
            path is None
            or encoding is None
            or first_line is None
            or separator != "SystemDefault"
            or not isinstance(trim_fields, bool)
            or not node.output_var
        ):
            return None
        return [
            f"{prefix}{node.output_var} = file_actions.read_from_csv_file({path}, encoding={encoding!r}, "
            f"first_line_contains_column_names={first_line}, trim_fields={trim_fields!r})"
        ]

    if action_id == "File.WriteToCSVFile.WriteCSV":
        table = safe_render(p.get("VariableToWrite"))
        path = safe_render(p.get("CSVFile"))
        encoding = enum_last(p.get("CsvFileEncoding"))
        if_exists = enum_last(p.get("IfFileExists"))
        separator = enum_last(p.get("ColumnsSeparator"))
        include_names = safe_render(p.get("IncludeColumnNames"))
        if (
            table is None
            or path is None
            or encoding is None
            or if_exists is None
            or include_names is None
            or separator != "SystemDefault"
        ):
            return None
        return [
            f"{prefix}file_actions.write_to_csv_file({path}, {table}, if_file_exists={if_exists!r}, "
            f"encoding={encoding!r}, include_column_names={include_names})"
        ]

    return None
