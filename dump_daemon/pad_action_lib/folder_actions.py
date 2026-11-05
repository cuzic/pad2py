"""`Folder.Actions`(フォルダ単位の操作)のロジック層。"""
from __future__ import annotations

import fnmatch
import os
import shutil
from pathlib import Path

from .errors import PadActionError


class InvalidSourceFolderError(PadActionError):
    pass


class InvalidDestinationFolderError(PadActionError):
    pass


class CopyFolderError(PadActionError):
    pass


class CreateFolderError(PadActionError):
    pass


class DeleteFolderError(PadActionError):
    pass


class MoveFolderError(PadActionError):
    pass


class RenameFolderError(PadActionError):
    pass


class FolderNotFoundError(PadActionError):  # noqa: A001
    pass


def copy_folder(source: str, destination: str, if_file_exists: str = "DoNothing") -> None:
    src = Path(source)
    dst = Path(destination)
    if not src.is_dir():
        raise InvalidSourceFolderError(str(source))
    if not dst.parent.is_dir():
        raise InvalidDestinationFolderError(str(destination))

    def _copy_function(s: str, d: str) -> None:
        if Path(d).exists() and if_file_exists == "DoNothing":
            return
        shutil.copy2(s, d)

    try:
        shutil.copytree(src, dst, dirs_exist_ok=True, copy_function=_copy_function)
    except OSError as exc:
        raise CopyFolderError(str(exc)) from exc


def create_folder(folder_path: str, folder_name: str) -> str:
    # 末尾がパス区切り文字の場合、そのセグメントが「名前」側に畳み込まれる非自明な正規化。
    combined = Path(folder_path) / folder_name
    try:
        combined.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CreateFolderError(str(exc)) from exc
    return str(combined)


def delete_folder(folder: str) -> None:
    path = Path(folder)
    if not path.is_dir():
        raise FolderNotFoundError(str(folder))
    try:
        shutil.rmtree(path)
    except OSError as exc:
        raise DeleteFolderError(str(exc)) from exc


def empty_folder(folder: str) -> None:
    path = Path(folder)
    if not path.is_dir():
        raise FolderNotFoundError(str(folder))
    for child in path.iterdir():
        try:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        except OSError as exc:
            raise DeleteFolderError(str(exc)) from exc


def move_folder(source: str, destination: str) -> str:
    src = Path(source)
    dst = Path(destination)
    if not src.is_dir():
        raise InvalidSourceFolderError(str(source))
    if dst.exists():
        # 上書きオプションが無い——既存ならエラー化する。
        raise MoveFolderError(f"destination already exists: {destination}")
    try:
        shutil.move(str(src), str(dst))
    except OSError as exc:
        raise MoveFolderError(str(exc)) from exc
    return str(dst)


def rename_folder(folder: str, new_name: str) -> Path:
    src = Path(folder)
    if not src.is_dir():
        raise InvalidSourceFolderError(str(folder))
    dst = src.parent / new_name
    if dst.exists():
        # ターゲット名が既に存在する場合は何もせず黙って成功したように見える罠。
        return src
    try:
        src.rename(dst)
    except OSError as exc:
        raise RenameFolderError(str(exc)) from exc
    return dst


def _matches_any_mask(name: str, masks: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, mask) for mask in masks)


def _split_masks(mask_text: str) -> list[str]:
    return [m for m in mask_text.split(";") if m]


def get_files_in_folder(
    folder: str,
    file_filter: str = "*",
    include_subfolders: bool = False,
    fail_on_access_denied: bool = True,
    sort_by: list[tuple[str, bool]] | None = None,
) -> list[str]:
    masks = _split_masks(file_filter)
    root = Path(folder)
    results: set[str] = set()
    iterator = root.rglob("*") if include_subfolders else root.glob("*")
    try:
        entries = list(iterator)
    except PermissionError:
        if fail_on_access_denied:
            raise
        entries = []
    for entry in entries:
        try:
            if entry.is_file() and _matches_any_mask(entry.name, masks):
                results.add(str(entry))
        except PermissionError:
            if fail_on_access_denied:
                raise
    files = list(results)
    if sort_by:
        for key, descending in reversed(sort_by):
            files.sort(key=lambda f: _sort_key(Path(f), key), reverse=descending)
    return files


def get_subfolders_in_folder(
    folder: str,
    folder_filter: str = "*",
    include_subfolders: bool = False,
    fail_on_access_denied: bool = True,
    sort_by: list[tuple[str, bool]] | None = None,
) -> list[str]:
    masks = _split_masks(folder_filter)
    root = Path(folder)
    results: set[str] = set()
    iterator = root.rglob("*") if include_subfolders else root.glob("*")
    try:
        entries = list(iterator)
    except PermissionError:
        if fail_on_access_denied:
            raise
        entries = []
    for entry in entries:
        try:
            if entry.is_dir() and _matches_any_mask(entry.name, masks):
                results.add(str(entry))
        except PermissionError:
            if fail_on_access_denied:
                raise
    folders = list(results)
    if sort_by:
        for key, descending in reversed(sort_by):
            folders.sort(key=lambda f: _sort_key(Path(f), key), reverse=descending)
    return folders


def _sort_key(path: Path, key: str) -> object:
    if key == "Name":
        return path.name
    if key == "Size":
        return path.stat().st_size if path.is_file() else -1
    if key == "CreatedDate":
        return path.stat().st_ctime
    if key == "ModifiedDate":
        return path.stat().st_mtime
    raise ValueError(f"Unknown sort key: {key!r}")


# PADの`Folder.SpecialFolder`列挙は.NETの`Environment.SpecialFolder`(Windows CSIDL定数の
# ラッパー、公開されたMicrosoft APIの一部でPAD固有の推測ではない)を模している。このうち
# `pad_codegen`が実機確認済みで結線しているのは`"Desktop"`(`DesktopDirectory`、知見84)
# のみだが、生成スクリプトは常にWindows上で実行される前提のため、ここで実際に動く
# 実装(`win32com.shell.shell.SHGetFolderPath`)を用意しておく——結線されていない他の
# キーも同じ理由で併せて対応付けておく(`pad_codegen`側が新たに結線する際のでっち上げ
# 防止にはならないが、関数自体は正しく動く)。
_SPECIAL_FOLDER_CSIDL_NAMES = {
    "Desktop": "CSIDL_DESKTOPDIRECTORY",
    # 実機のVM(pywin32)で確認済み: `CSIDL_MYDOCUMENTS`は属性としては存在するが
    # `SHGetFolderPath`に渡すと`com_error: The parameter is incorrect.`になる
    # (値が12=本来のCSIDL_CONNECTIONSと食い違う、pywin32側の既知の別名違いらしい)。
    # 正しく動くのは`CSIDL_PERSONAL`(実機で`C:\Users\<user>\Documents`を確認)。
    "Documents": "CSIDL_PERSONAL",
    "AppData": "CSIDL_APPDATA",
    "Temp": None,  # CSIDLに無い(`tempfile.gettempdir()`を使う)。
}


def get_special_folder(name: str) -> str:
    env_map = {
        "Desktop": "XDG_DESKTOP_DIR",
        "Documents": "XDG_DOCUMENTS_DIR",
        "AppData": "XDG_CONFIG_HOME",
        "Temp": "TMPDIR",
    }
    env_var = env_map.get(name)
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    if name == "Temp":
        import tempfile

        return tempfile.gettempdir()
    csidl_name = _SPECIAL_FOLDER_CSIDL_NAMES.get(name)
    if csidl_name is not None:
        try:
            import win32com.shell.shell as shell  # type: ignore[import-not-found]
            import win32com.shell.shellcon as shellcon  # type: ignore[import-not-found]
        except ImportError:
            pass
        else:
            csidl = getattr(shellcon, csidl_name, None)
            if csidl is not None:
                return shell.SHGetFolderPath(0, csidl, 0, 0)
    # Windowsの`Environment.SpecialFolder`(20種以上)のうち、上記で解決できなかった
    # ものは、でっち上げたパスを返す代わりにNotImplementedErrorとする。
    raise NotImplementedError(f"Special folder {name!r} is not mapped on this platform")


def if_folder_exists(folder: str) -> bool:
    return Path(folder).is_dir()
