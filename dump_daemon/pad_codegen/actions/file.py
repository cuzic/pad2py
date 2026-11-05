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

`ColumnsSeparator`がSystemDefault以外(Comma/Semicolon/Tab)の場合、および
`ReadCSVWithCustomSeparator`/`WriteCSVWithCustomSeparator`兄弟セレクタは、
`Variables.GenerateDataTableFromCSV`/`ConvertDataTableToCSV`と全く同じ
`CSVColumnsSeparator`列挙型(`Text.Utilities.dll`)を使っていると知見127・128で
確認したため`_support.CSV_PREDEFINED_SEPARATOR_TO_DELIMITER`を再利用して結線した。
`ReadCSVWithFixedColumnWidths`は知見132で`CSVUtilities.TryParseColumnWidths()`の
VM上の直接呼び出しにより`FixedColumnWidths`文字列の正確な構文・固定長パースの
全エッジケース(行が短いとエラー・長いと余りを無視・ヘッダー行も同じ幅で切り出し)を
確認し、`pad_action_lib.datatable.datatable_from_fixed_width_csv()`へ結線した。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import CSV_PREDEFINED_SEPARATOR_TO_DELIMITER, enum_last, safe_render


def _as_list_expr(rendered: str) -> str:
    return f"({rendered} if isinstance({rendered}, list) else [{rendered}])"


def _rename_add_text_transform(p: dict) -> str | None:
    text = safe_render(p.get("TextToAdd"))
    position = enum_last(p.get("TextPosition"))
    if text is None or position is None:
        return None
    return f"file_actions.rename_add_text(_rename_base, {text}, position={position!r})"


def _rename_remove_text_transform(p: dict) -> str | None:
    text = safe_render(p.get("TextToRemove"))
    if text is None:
        return None
    return f"file_actions.rename_remove_text(_rename_base, {text})"


def _rename_replace_text_transform(p: dict) -> str | None:
    find = safe_render(p.get("TextToReplace"))
    replace = safe_render(p.get("ReplaceWith"))
    if find is None or replace is None:
        return None
    return f"file_actions.rename_replace_text(_rename_base, {find}, {replace})"


def _rename_change_extension_transform(p: dict) -> str | None:
    new_extension = safe_render(p.get("NewExtension"))
    if new_extension is None:
        return None
    return f"file_actions.rename_change_extension(_rename_base, {new_extension})"


# design/dsl_format_findings.md 知見136: `RenameFilesAction`のVM上のリフレクションで
# 確認済みの`RenameScheme`列挙値(`AddText`/`RemoveText`/`ReplaceText`/`ChangeExtension`)
# それぞれに対応するaction_idセレクタ名(`ActionSelectorBase.ActionName`で確認済み)。
_RENAME_SCHEME_TRANSFORMS = {
    "File.RenameFiles.RenameAddText": _rename_add_text_transform,
    "File.RenameFiles.RenameRemoveText": _rename_remove_text_transform,
    "File.RenameFiles.RenameReplaceText": _rename_replace_text_transform,
    "File.RenameFiles.RenameChangeExtension": _rename_change_extension_transform,
}


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

    _rename_transform = _RENAME_SCHEME_TRANSFORMS.get(action_id)
    if _rename_transform is not None:
        # design/dsl_format_findings.md 知見136: `RenameFiles`の兄弟セレクタ群
        # (`ActionSelectorBase`一括列挙の監査で発見、実機の`RenameScheme`列挙値は
        # `AddText`/`RemoveText`/`ReplaceText`/`ChangeExtension`/`AddDateTime`/
        # `MakeSequential`——`SetNewName`が上記の`File.RenameFiles.Rename`)。
        # `AddDateTime`/`MakeSequential`(日時・連番の書式オプションが多く未検証)は
        # 今回は見送り、単純な文字列操作の4件のみ結線した。
        transform_expr = _rename_transform(p)
        if transform_expr is None:
            return None
        files = safe_render(p.get("Files"))
        if_exists = enum_last(p.get("IfFileExists"))
        if files is None or if_exists is None or not node.output_var:
            return None
        inner = INDENT * (indent + 1)
        return [
            f"{prefix}_rename_targets = {_as_list_expr(files)}",
            f"{prefix}{node.output_var} = []",
            f"{prefix}for _rename_src in _rename_targets:",
            f"{inner}_rename_dir, _rename_base = os.path.split(_rename_src)",
            f"{inner}_rename_new_base = {transform_expr}",
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

    if action_id == "File.ReadTextFromFile.ReadTextAsList":
        # design/dsl_format_findings.md 知見136: 兄弟セレクタ(出力変数名は`Content`ではなく
        # `Contents`——`ActionSelectorBase.ActionName`一括列挙の監査で発見)。
        # `read_text_from_file()`自体は既に`store_content_as="List"`を実装済みで、
        # VM上で`splitlines()`と同じ挙動(末尾の空行を生まない)だと確認済み。
        path = safe_render(p.get("File"))
        encoding = enum_last(p.get("Encoding"))
        if path is None or encoding is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = file_actions.read_text_from_file("
            f"{path}, encoding={encoding!r}, store_content_as='List')"
        ]

    if action_id == "File.ReadFromCSVFile.ReadCSV":
        path = safe_render(p.get("CSVFile"))
        encoding = enum_last(p.get("Encoding"))
        separator = enum_last(p.get("ColumnsSeparator"))
        first_line = safe_render(p.get("FirstLineContainsColumnNames"))
        trim_fields = p.get("TrimFields")
        delimiter = CSV_PREDEFINED_SEPARATOR_TO_DELIMITER.get(separator) if separator else None
        if (
            path is None
            or encoding is None
            or first_line is None
            or delimiter is None
            or not isinstance(trim_fields, bool)
            or not node.output_var
        ):
            return None
        return [
            f"{prefix}{node.output_var} = file_actions.read_from_csv_file({path}, delimiter={delimiter!r}, "
            f"encoding={encoding!r}, first_line_contains_column_names={first_line}, "
            f"trim_fields={trim_fields!r})"
        ]

    if action_id == "File.ReadFromCSVFile.ReadCSVWithCustomSeparator":
        path = safe_render(p.get("CSVFile"))
        encoding = enum_last(p.get("Encoding"))
        first_line = safe_render(p.get("FirstLineContainsColumnNames"))
        trim_fields = p.get("TrimFields")
        custom_separator = safe_render(p.get("CustomColumnsSeparator"))
        if (
            path is None
            or encoding is None
            or first_line is None
            or custom_separator is None
            or not isinstance(trim_fields, bool)
            or not node.output_var
        ):
            return None
        return [
            f"{prefix}{node.output_var} = file_actions.read_from_csv_file({path}, "
            f"delimiter={custom_separator}, encoding={encoding!r}, "
            f"first_line_contains_column_names={first_line}, trim_fields={trim_fields!r})"
        ]

    if action_id == "File.ReadFromCSVFile.ReadCSVWithFixedColumnWidths":
        path = safe_render(p.get("CSVFile"))
        encoding = enum_last(p.get("Encoding"))
        first_line = safe_render(p.get("FirstLineContainsColumnNames"))
        trim_fields = p.get("TrimFields")
        widths = safe_render(p.get("FixedColumnWidths"))
        if (
            path is None
            or encoding is None
            or first_line is None
            or widths is None
            or not isinstance(trim_fields, bool)
            or not node.output_var
        ):
            return None
        return [
            f"{prefix}{node.output_var} = file_actions.read_from_csv_file_fixed_width({path}, "
            f"{widths}, encoding={encoding!r}, "
            f"first_line_contains_column_names={first_line}, trim_fields={trim_fields!r})"
        ]

    if action_id == "File.WriteToCSVFile.WriteCSV":
        table = safe_render(p.get("VariableToWrite"))
        path = safe_render(p.get("CSVFile"))
        encoding = enum_last(p.get("CsvFileEncoding"))
        if_exists = enum_last(p.get("IfFileExists"))
        separator = enum_last(p.get("ColumnsSeparator"))
        include_names = safe_render(p.get("IncludeColumnNames"))
        delimiter = CSV_PREDEFINED_SEPARATOR_TO_DELIMITER.get(separator) if separator else None
        if (
            table is None
            or path is None
            or encoding is None
            or if_exists is None
            or include_names is None
            or delimiter is None
        ):
            return None
        return [
            f"{prefix}file_actions.write_to_csv_file({path}, {table}, delimiter={delimiter!r}, "
            f"if_file_exists={if_exists!r}, encoding={encoding!r}, include_column_names={include_names})"
        ]

    if action_id == "File.WriteToCSVFile.WriteCSVWithCustomSeparator":
        table = safe_render(p.get("VariableToWrite"))
        path = safe_render(p.get("CSVFile"))
        encoding = enum_last(p.get("CsvFileEncoding"))
        if_exists = enum_last(p.get("IfFileExists"))
        include_names = safe_render(p.get("IncludeColumnNames"))
        custom_separator = safe_render(p.get("CustomColumnsSeparator"))
        if (
            table is None
            or path is None
            or encoding is None
            or if_exists is None
            or include_names is None
            or custom_separator is None
        ):
            return None
        return [
            f"{prefix}file_actions.write_to_csv_file({path}, {table}, delimiter={custom_separator}, "
            f"if_file_exists={if_exists!r}, encoding={encoding!r}, include_column_names={include_names})"
        ]

    return None
