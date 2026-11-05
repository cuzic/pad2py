"""`Compression.Actions`(Zip圧縮/解凍)のロジック層。

PADの実装はSharpZipLibベース(.NET標準の`System.IO.Compression`ではない)で、
パスワード付きZip(AES/ZipCrypto)の**書き込み**にも対応している。Python標準の
`zipfile`はパスワード付き書き込みに対応しないため、パスワード指定時のみ
`pyzipper`(AES対応)を使う——パスワード無しの大多数のケースでは標準`zipfile`で足りる。

`ZipFiles`は`ArchivePath`が既存の有効なzipなら追記(既存エントリ+新規エントリを
`.temp`ステージングファイルへ書き直し、最後に差し替える——クラッシュセーフ)。
`UnzipFiles`はZip Slip(パストラバーサル)対策を明示的に実装する。
"""
from __future__ import annotations

import fnmatch
import os
import tempfile
import zipfile
from pathlib import Path

import pyzipper

from .errors import PadActionError

_OS_FILE_NOT_FOUND_ERROR = FileNotFoundError


class FileNotFoundError(PadActionError):  # noqa: A001 - PADの[Throws]タグ名をそのまま使う
    pass


class InvalidFileError(PadActionError):
    pass


class ArchiveExistsInvalidError(PadActionError):
    pass


class ZipError(PadActionError):
    pass


class CreateFolderError(PadActionError):
    pass


class ArchiveNotFoundError(PadActionError):
    pass


class InvalidArchiveError(PadActionError):
    pass


class UnzipError(PadActionError):
    pass


def _split_masks(mask_text: str) -> list[str]:
    return [m for m in mask_text.split(";") if m]


def _matches_any_mask(name: str, masks: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, mask) for mask in masks)


def _collect_entries(path: Path) -> list[tuple[Path | None, str]]:
    """1つのファイル/フォルダを(実ファイルパス, zip内アーカイブ名)の列に展開する。

    空ディレクトリは実ファイルを持たないマーカーエントリ(`None`, `"dir/"`)として返す。
    """
    if path.is_file():
        return [(path, path.name)]

    def _walk(current: Path, arc_prefix: str) -> list[tuple[Path | None, str]]:
        children = sorted(current.iterdir())
        if not children:
            return [(None, arc_prefix.rstrip("/") + "/")]
        entries: list[tuple[Path | None, str]] = []
        for child in children:
            child_arc = f"{arc_prefix.rstrip('/')}/{child.name}" if arc_prefix else child.name
            if child.is_dir():
                entries.extend(_walk(child, child_arc))
            else:
                entries.append((child, child_arc))
        return entries

    return _walk(path, path.name)


def zip_files(
    archive_path: str,
    files_or_folders: list[str],
    compression_level: int = 6,
    password: str | None = None,
    archive_comment: str = "",
) -> str:
    """戻り値は実機の`ZipFile`出力(`ArchivePath`と同じパスを指す`FileObject`)に対応する。

    design/dsl_format_findings.md 知見129(VM上でのリフレクション直接呼び出しで実機確認済み):
    `ZipFilesAction`(実際のクラス名`ZipFiles`)をインスタンス化・`Execute()`を直接呼び出し、
    実行後の`ZipFile`プロパティの値(`FileObject.FullName`)が渡した`ArchivePath`と同一の
    パス文字列だったことを確認した——つまり単なるecho。それまでこの関数は`None`を返し、
    `pad_codegen`側は`{output_var} = zip_files(...)`という代入文を生成していたため、
    `ZipFile=>`を実際に束縛したフローでは出力変数が常に`None`になる潜在バグがあった
    (既存の合成テストは`archive_path.is_file()`という副作用だけを検証しており、
    代入先の値自体は一度も検証していなかった)。
    """
    archive = Path(archive_path)
    entries: dict[str, bytes] = {}
    if archive.is_file():
        if not zipfile.is_zipfile(archive):
            raise ArchiveExistsInvalidError(str(archive))
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                entries[info.filename] = b"" if info.is_dir() else zf.read(info.filename)
    elif archive.exists():
        raise ArchiveExistsInvalidError(str(archive))

    for item in files_or_folders:
        path = Path(item)
        if not path.exists():
            raise FileNotFoundError(str(item))
        for src, arcname in _collect_entries(path):
            entries[arcname] = src.read_bytes() if src is not None else b""

    tmp_dir = archive.parent if archive.parent.exists() else None
    fd, tmp_name = tempfile.mkstemp(suffix=".temp", dir=tmp_dir)
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        if password:
            with pyzipper.AESZipFile(
                tmp_path, "w", compression=zipfile.ZIP_DEFLATED, encryption=pyzipper.WZ_AES
            ) as zf:
                zf.setpassword(password.encode("utf-8"))
                zf.comment = archive_comment.encode("utf-8")
                for arcname, data in entries.items():
                    zf.writestr(arcname, data)
        else:
            with zipfile.ZipFile(
                tmp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=compression_level
            ) as zf:
                zf.comment = archive_comment.encode("utf-8")
                for arcname, data in entries.items():
                    zf.writestr(arcname, data)
        tmp_path.replace(archive)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise ZipError(str(exc)) from exc
    return archive_path


def unzip_files(
    archive_path: str,
    destination_folder: str,
    password: str | None = None,
    include_mask: str = "*",
    exclude_mask: str = "",
) -> list[str]:
    archive = Path(archive_path)
    if not archive.is_file():
        raise ArchiveNotFoundError(str(archive))

    dest = Path(destination_folder)
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CreateFolderError(str(exc)) from exc

    include_masks = _split_masks(include_mask) or ["*"]
    exclude_masks = _split_masks(exclude_mask)
    dest_resolved = dest.resolve()

    opener = (lambda p: pyzipper.AESZipFile(p)) if password else (lambda p: zipfile.ZipFile(p))
    extracted: list[str] = []
    try:
        with opener(archive) as zf:
            if password:
                zf.setpassword(password.encode("utf-8"))
            for info in zf.infolist():
                name = info.filename
                target = (dest / name).resolve()
                if dest_resolved not in target.parents and target != dest_resolved:
                    raise InvalidArchiveError(f"unsafe path in archive (zip slip): {name}")
                if name.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                base_name = Path(name).name
                if not _matches_any_mask(base_name, include_masks):
                    continue
                if exclude_masks and _matches_any_mask(base_name, exclude_masks):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(name))
                extracted.append(str(target))
    except zipfile.BadZipFile as exc:
        raise InvalidArchiveError(str(exc)) from exc
    except RuntimeError as exc:
        raise UnzipError(str(exc)) from exc
    return extracted
