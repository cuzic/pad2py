"""`File.Actions`(単一ファイル操作)のロジック層。

`RenameFiles`の各`RenameScheme`(`AddText`/`RemoveText`/`ReplaceText`/
`ChangeExtension`/`AddDateTime`)が実際にどのパラメータ名を使うかはデコンパイル
結果からも未確認("各スキーム専用パラメータ多数"としか分からない)ため、この層では
変換内容(「何をするか」)だけを素直な関数として実装し、パラメータ名はこのモジュール
独自の名前を使う——実機でDSLのプロパティ名が確認できた後、codegen側でその名前から
この関数の引数へマッピングする結線作業が別途必要。
"""
from __future__ import annotations

import base64
import glob
import os
import shutil
from pathlib import Path

from .datatable import DataTable
from .errors import PadActionError

# ビルトインの`FileNotFoundError`と、PADの`[Throws("FileNotFoundError")]`タグに対応する
# 例外クラスの名前が衝突するため、実OSエラーの捕捉用に先に退避しておく。
_OS_FILE_NOT_FOUND_ERROR = FileNotFoundError


class InvalidSourceFolderError(PadActionError):
    pass


class InvalidDestinationFolderError(PadActionError):
    pass


class FileNotFoundError(PadActionError):  # noqa: A001 - PADの[Throws]タグ名をそのまま使う
    pass


class CopyFileError(PadActionError):
    pass


class MoveFileError(PadActionError):
    pass


class DeleteFileError(PadActionError):
    pass


class DirectoryNotFoundError(PadActionError):  # noqa: A001
    pass


class ReadFromFileError(PadActionError):
    pass


class WriteTextToFileError(PadActionError):
    pass


class InvalidDirectoryError(PadActionError):
    pass


def _has_wildcard(pattern: str) -> bool:
    return "*" in pattern or "?" in pattern


def _expand(pattern: str) -> list[str]:
    return glob.glob(pattern) if _has_wildcard(pattern) else [pattern]


def copy_files(files: list[str], destination: str, if_file_exists: str = "DoNothing") -> list[str]:
    dest_dir = Path(destination)
    if not dest_dir.is_dir():
        raise InvalidDestinationFolderError(str(destination))
    copied: list[str] = []
    for pattern in files:
        matches = _expand(pattern)
        if not matches:
            raise CopyFileError(f"source not found: {pattern}")
        for src in matches:
            src_path = Path(src)
            if not src_path.is_file():
                raise CopyFileError(f"source not found: {src}")
            dst_path = dest_dir / src_path.name
            if dst_path.exists() and if_file_exists == "DoNothing":
                continue
            try:
                shutil.copy2(src_path, dst_path)
            except OSError as exc:
                raise CopyFileError(str(exc)) from exc
            copied.append(str(dst_path))
    return copied


def move_files(files: list[str], destination: str, if_file_exists: str = "DoNothing") -> list[str]:
    dest_dir = Path(destination)
    if not dest_dir.is_dir():
        raise InvalidDestinationFolderError(str(destination))
    moved: list[str] = []
    for pattern in files:
        matches = _expand(pattern)
        if not matches:
            raise MoveFileError(f"source not found: {pattern}")
        for src in matches:
            src_path = Path(src)
            dst_path = dest_dir / src_path.name
            if src_path.resolve() == dst_path.resolve():
                moved.append(str(dst_path))
                continue
            if dst_path.exists():
                if if_file_exists == "DoNothing":
                    continue
                if if_file_exists == "Overwrite":
                    dst_path.unlink()
                else:
                    raise ValueError(f"Unknown IfExists mode: {if_file_exists!r}")
            try:
                shutil.move(str(src_path), str(dst_path))
            except OSError as exc:
                raise MoveFileError(str(exc)) from exc
            moved.append(str(dst_path))
    return moved


def delete_files(files: list[str]) -> None:
    for pattern in files:
        matches = _expand(pattern)
        if not matches:
            raise FileNotFoundError(pattern)
        for f in matches:
            path = Path(f)
            if not path.is_file():
                raise FileNotFoundError(str(path))
            try:
                path.unlink()
            except OSError as exc:
                raise DeleteFileError(str(exc)) from exc


class SequentialNumberer:
    """`MakeSequential`のバッチ内状態(呼び出しごとに`start += increment`)。"""

    def __init__(self, start: int = 1, increment: int = 1) -> None:
        self.start = start
        self.increment = increment

    def next(self) -> int:
        value = self.start
        self.start += self.increment
        return value


def rename_set_new_name(original_name: str, new_name: str, keep_extension: bool = True) -> str:
    if keep_extension:
        _, ext = os.path.splitext(original_name)
        return new_name + ext
    return new_name


def rename_add_text(original_name: str, text: str, position: str = "Suffix") -> str:
    stem, ext = os.path.splitext(original_name)
    return (text + stem + ext) if position == "Prefix" else (stem + text + ext)


def rename_remove_text(original_name: str, text: str) -> str:
    stem, ext = os.path.splitext(original_name)
    return stem.replace(text, "") + ext


def rename_replace_text(original_name: str, find: str, replace: str) -> str:
    stem, ext = os.path.splitext(original_name)
    return stem.replace(find, replace) + ext


def rename_change_extension(original_name: str, new_extension: str) -> str:
    stem, _ext = os.path.splitext(original_name)
    new_extension = new_extension if new_extension.startswith(".") else f".{new_extension}"
    return stem + new_extension


def rename_add_datetime(
    original_name: str,
    timestamp,
    strftime_format: str = "%Y%m%d%H%M%S",
    position: str = "Suffix",
) -> str:
    stem, ext = os.path.splitext(original_name)
    stamp = timestamp.strftime(strftime_format)
    return f"{stamp}{stem}{ext}" if position == "Prefix" else f"{stem}{stamp}{ext}"


def rename_make_sequential(original_name: str, numberer: SequentialNumberer, digits: int = 0) -> str:
    stem, ext = os.path.splitext(original_name)
    number = numberer.next()
    number_text = str(number).zfill(digits) if digits else str(number)
    return f"{stem}{number_text}{ext}"


def apply_rename(directory: str, original_name: str, new_name: str, if_file_exists: str = "DoNothing") -> Path:
    src = Path(directory) / original_name
    dst = Path(directory) / new_name
    if src.name.lower() == dst.name.lower():
        return src
    if dst.exists():
        if if_file_exists == "DoNothing":
            return src
        if if_file_exists == "Overwrite":
            dst.unlink()
        else:
            raise ValueError(f"Unknown IfExists mode: {if_file_exists!r}")
    src.rename(dst)
    return dst


def file_to_base64(path: str) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def _write_bytes(path: str, data: bytes, if_file_exists: str = "DoNothing") -> None:
    dest = Path(path)
    if dest.exists() and if_file_exists == "DoNothing":
        return
    dest.write_bytes(data)


def base64_to_file(data: str, path: str, if_file_exists: str = "DoNothing") -> None:
    _write_bytes(path, base64.b64decode(data), if_file_exists)


def file_to_binary(path: str) -> bytes:
    return Path(path).read_bytes()


def binary_to_file(data: bytes, path: str, if_file_exists: str = "DoNothing") -> None:
    _write_bytes(path, data, if_file_exists)


_TEXT_FILE_ENCODINGS = {
    "UTF8": "utf-8",
    "Unicode": "utf-16",
    "ASCII": "ascii",
    "Default": "utf-8",
}


def read_text_from_file(path: str, encoding: str = "UTF8", store_content_as: str = "SingleTextValue"):
    try:
        text = Path(path).read_text(encoding=_TEXT_FILE_ENCODINGS.get(encoding, encoding))
    except _OS_FILE_NOT_FOUND_ERROR as exc:
        raise FileNotFoundError(str(exc)) from exc
    except OSError as exc:
        raise ReadFromFileError(str(exc)) from exc
    if store_content_as == "List":
        return text.splitlines()
    return text


def _stringify_for_write(value: object) -> str:
    from .datatable import DataTable as _DataTable  # 遅延import(循環回避)

    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and isinstance(value[0], dict):
        # DataTable(行の辞書リスト)——各行を再帰的に書き込み、行内はセルを", "で連結する
        # (区切り文字はカスタマイズ不可の固定値)。
        rows = [", ".join(str(v) for v in row.values()) for row in value]
        return "\r\n".join(rows)
    if isinstance(value, dict):
        import json

        return json.dumps(value, indent=2)
    if isinstance(value, list):
        return "\r\n".join(str(v) for v in value)
    return str(value)


def write_text_to_file(
    path: str,
    value: object,
    append_new_line: bool = True,
    encoding: str = "Unicode",
    if_file_exists: str = "Overwrite",
) -> None:
    dest = Path(path)
    if not dest.parent.is_dir():
        raise DirectoryNotFoundError(str(dest.parent))
    text = _stringify_for_write(value)
    if append_new_line:
        text += "\r\n"
    mode_encoding = _TEXT_FILE_ENCODINGS.get(encoding, encoding)
    try:
        if if_file_exists == "Append":
            with dest.open("a", encoding=mode_encoding, newline="") as fh:
                fh.write(text)
        else:
            dest.write_text(text, encoding=mode_encoding, newline="")
    except OSError as exc:
        raise WriteTextToFileError(str(exc)) from exc


def read_from_csv_file(
    path: str,
    delimiter: str = ",",
    encoding: str = "UTF8",
    first_line_contains_column_names: bool = True,
    trim_fields: bool = True,
) -> DataTable:
    from .datatable import datatable_from_csv_text

    try:
        text = Path(path).read_text(encoding=_TEXT_FILE_ENCODINGS.get(encoding, encoding))
    except _OS_FILE_NOT_FOUND_ERROR as exc:
        raise FileNotFoundError(str(exc)) from exc
    return datatable_from_csv_text(
        text,
        delimiter=delimiter,
        first_line_contains_column_names=first_line_contains_column_names,
        trim_fields=trim_fields,
    )


def read_from_csv_file_fixed_width(
    path: str,
    widths: str,
    encoding: str = "UTF8",
    first_line_contains_column_names: bool = True,
    trim_fields: bool = True,
) -> DataTable:
    from .datatable import datatable_from_fixed_width_csv

    try:
        text = Path(path).read_text(encoding=_TEXT_FILE_ENCODINGS.get(encoding, encoding))
    except _OS_FILE_NOT_FOUND_ERROR as exc:
        raise FileNotFoundError(str(exc)) from exc
    return datatable_from_fixed_width_csv(
        text,
        widths,
        first_line_contains_column_names=first_line_contains_column_names,
        trim_fields=trim_fields,
    )


def write_to_csv_file(
    path: str,
    table: DataTable,
    delimiter: str = ",",
    if_file_exists: str = "Overwrite",
    encoding: str = "UTF8",
    include_column_names: bool = True,
) -> None:
    from .datatable import datatable_to_csv_text

    text = datatable_to_csv_text(table, delimiter=delimiter, include_column_names=include_column_names)
    mode_encoding = _TEXT_FILE_ENCODINGS.get(encoding, encoding)
    dest = Path(path)
    if if_file_exists == "Append" and dest.exists() and dest.stat().st_size > 0:
        # 既存の空でないファイルへのAppendはヘッダー行を書き直さない
        # (include_column_names=Falseならそもそもヘッダー行が無いので何もしない)。
        if include_column_names:
            text = text.split("\r\n", 1)[1] if "\r\n" in text else ""
        with dest.open("a", encoding=mode_encoding, newline="") as fh:
            fh.write(text)
        return
    dest.write_text(text, encoding=mode_encoding, newline="")


def get_file_path_part(path: str) -> dict[str, str]:
    p = Path(path)
    return {
        "RootPath": p.drive + os.sep if p.drive else p.anchor,
        "Directory": str(p.parent),
        "FileName": p.name,
        "FileNameWithoutExtension": p.stem,
        "Extension": p.suffix,
    }


def get_temp_file_path(extension: str = ".tmp") -> str:
    import tempfile

    fd, path = tempfile.mkstemp(suffix=extension)
    os.close(fd)
    return path


def if_file_exists(path: str) -> bool:
    return Path(path).is_file()
