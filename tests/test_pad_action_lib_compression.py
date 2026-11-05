"""`pad_action_lib.compression_actions`の単体テスト。"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from dump_daemon.pad_action_lib import compression_actions as co


def test_zip_and_unzip_round_trip(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "a.txt").write_text("hello")
    archive = tmp_path / "out.zip"

    result = co.zip_files(str(archive), [str(src_dir / "a.txt")])
    assert zipfile.is_zipfile(archive)
    # design/dsl_format_findings.md 知見129: 実機の`ZipFile`出力は`ArchivePath`と同じパスを
    # 指すFileObjectだったため(VM上のリフレクション直接呼び出しで確認済み)、同じ文字列を返す。
    assert result == str(archive)

    dest = tmp_path / "extracted"
    extracted = co.unzip_files(str(archive), str(dest))
    assert len(extracted) == 1
    assert Path(extracted[0]).read_text() == "hello"


def test_zip_includes_empty_directory_marker(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    (src_dir / "empty").mkdir(parents=True)
    archive = tmp_path / "out.zip"

    co.zip_files(str(archive), [str(src_dir)])
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    assert any(n.endswith("empty/") for n in names)


def test_zip_appends_to_existing_archive(tmp_path: Path) -> None:
    archive = tmp_path / "out.zip"
    a = tmp_path / "a.txt"
    a.write_text("a")
    b = tmp_path / "b.txt"
    b.write_text("b")

    co.zip_files(str(archive), [str(a)])
    co.zip_files(str(archive), [str(b)])

    with zipfile.ZipFile(archive) as zf:
        names = sorted(zf.namelist())
    assert names == ["a.txt", "b.txt"]


def test_zip_existing_invalid_file_raises(tmp_path: Path) -> None:
    archive = tmp_path / "out.zip"
    archive.write_text("not a zip")
    a = tmp_path / "a.txt"
    a.write_text("a")
    with pytest.raises(co.ArchiveExistsInvalidError):
        co.zip_files(str(archive), [str(a)])


def test_zip_missing_source_raises_and_leaves_archive_untouched(tmp_path: Path) -> None:
    archive = tmp_path / "out.zip"
    with pytest.raises(co.FileNotFoundError):
        co.zip_files(str(archive), [str(tmp_path / "missing.txt")])
    assert not archive.exists()


def test_zip_and_unzip_with_password(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("secret content")
    archive = tmp_path / "out.zip"
    co.zip_files(str(archive), [str(src)], password="hunter2")

    dest = tmp_path / "extracted"
    extracted = co.unzip_files(str(archive), str(dest), password="hunter2")
    assert Path(extracted[0]).read_text() == "secret content"


def test_unzip_missing_archive_raises(tmp_path: Path) -> None:
    with pytest.raises(co.ArchiveNotFoundError):
        co.unzip_files(str(tmp_path / "missing.zip"), str(tmp_path / "dest"))


def test_unzip_respects_include_and_exclude_masks(tmp_path: Path) -> None:
    archive = tmp_path / "out.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a.txt", "a")
        zf.writestr("b.csv", "b")
        zf.writestr("c.txt", "c")

    dest = tmp_path / "dest"
    extracted = co.unzip_files(
        str(archive), str(dest), include_mask="*.txt", exclude_mask="c.txt"
    )
    names = sorted(Path(f).name for f in extracted)
    assert names == ["a.txt"]


def test_unzip_blocks_zip_slip(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escaped.txt", "evil")

    dest = tmp_path / "dest"
    with pytest.raises(co.InvalidArchiveError):
        co.unzip_files(str(archive), str(dest))
    assert not (tmp_path / "escaped.txt").exists()
