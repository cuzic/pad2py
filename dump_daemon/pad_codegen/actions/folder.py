"""`Folder.*`(フォルダ単位操作)のcodegen。

`pad_action_lib.folder_actions`へ委譲する。パラメータ名は design/
dsl_format_findings.md 知見68で実機キャプチャした`tests/fixtures/
tier1_folder_batch5.txt`・知見66の`tier1_datetime_folder_clipboard_batch2.txt`から
確認済み。

`Folder.GetFiles`/`Folder.GetSubfolders`の`SortBy1/2/3`は実機で全て`NoSort`
(未使用)のケースしか確認できていないため、その場合のみ`sort_by=None`相当
(省略)で呼び出す——実際に並べ替えが指定された場合の複合キー構築は未検証のため
フォールバックに委ねる。

`Folder.GetSpecialFolder`は実機で確認できた唯一の値`DesktopDirectory`だけを
`pad_action_lib.folder_actions.get_special_folder()`が知る`"Desktop"`へ対応付け、
他の値は未確認としてフォールバックに委ねる。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import enum_last, safe_render

_SPECIAL_FOLDER_MAP = {"DesktopDirectory": "Desktop"}


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("Folder."):
        return None
    prefix = INDENT * indent
    p = node.params

    if action_id == "Folder.Copy":
        source = safe_render(p.get("Folder"))
        dest = safe_render(p.get("Destination"))
        if_exists = enum_last(p.get("IfFolderExists"))
        if source is None or dest is None or if_exists is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = folder_actions.copy_folder({source}, {dest}, "
            f"if_file_exists={if_exists!r})"
        ]

    if action_id == "Folder.Create":
        folder_path = safe_render(p.get("FolderPath"))
        folder_name = safe_render(p.get("FolderName"))
        if folder_path is None or folder_name is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = folder_actions.create_folder({folder_path}, {folder_name})"]

    if action_id == "Folder.Delete":
        folder = safe_render(p.get("Folder"))
        if folder is None:
            return None
        return [f"{prefix}folder_actions.delete_folder({folder})"]

    if action_id == "Folder.Empty":
        folder = safe_render(p.get("Folder"))
        if folder is None:
            return None
        return [f"{prefix}folder_actions.empty_folder({folder})"]

    if action_id == "Folder.Move":
        source = safe_render(p.get("Folder"))
        dest = safe_render(p.get("Destination"))
        if source is None or dest is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = folder_actions.move_folder({source}, {dest})"]

    if action_id == "Folder.Rename":
        folder = safe_render(p.get("Folder"))
        new_name = safe_render(p.get("NewName"))
        if folder is None or new_name is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = str(folder_actions.rename_folder({folder}, {new_name}))"]

    if action_id == "Folder.GetFiles":
        folder = safe_render(p.get("Folder"))
        file_filter = safe_render(p.get("FileFilter"))
        include_sub = safe_render(p.get("IncludeSubfolders"))
        fail_on_denied = safe_render(p.get("FailOnAccessDenied"))
        sort_by1 = enum_last(p.get("SortBy1"))
        if None in (folder, file_filter, include_sub, fail_on_denied, sort_by1):
            return None
        if sort_by1 != "NoSort" or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = folder_actions.get_files_in_folder({folder}, "
            f"file_filter={file_filter}, include_subfolders={include_sub}, "
            f"fail_on_access_denied={fail_on_denied})"
        ]

    if action_id == "Folder.GetSubfolders":
        folder = safe_render(p.get("Folder"))
        folder_filter = safe_render(p.get("FolderFilter"))
        include_sub = safe_render(p.get("IncludeSubfolders"))
        fail_on_denied = safe_render(p.get("FailOnAccessDenied"))
        sort_by1 = enum_last(p.get("SortBy1"))
        if None in (folder, folder_filter, include_sub, fail_on_denied, sort_by1):
            return None
        if sort_by1 != "NoSort" or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = folder_actions.get_subfolders_in_folder({folder}, "
            f"folder_filter={folder_filter}, include_subfolders={include_sub}, "
            f"fail_on_access_denied={fail_on_denied})"
        ]

    if action_id == "Folder.GetSpecialFolder":
        name = enum_last(p.get("SpecialFolder"))
        if name is None or not node.output_var:
            return None
        mapped = _SPECIAL_FOLDER_MAP.get(name)
        if mapped is None:
            return None
        return [f"{prefix}{node.output_var} = folder_actions.get_special_folder({mapped!r})"]

    return None
