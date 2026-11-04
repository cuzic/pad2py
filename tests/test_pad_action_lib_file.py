"""`pad_action_lib.file_actions`の単体テスト(実ファイルシステムをtmp_pathで使う)。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from dump_daemon.pad_action_lib import file_actions as fa


def test_copy_files_skips_existing_by_default(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()
    src_file = src_dir / "a.txt"
    src_file.write_text("new")
    existing = dst_dir / "a.txt"
    existing.write_text("old")

    fa.copy_files([str(src_file)], str(dst_dir))
    assert existing.read_text() == "old"


def test_copy_files_wildcard_expands_multiple_files(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()
    (src_dir / "a.txt").write_text("a")
    (src_dir / "b.txt").write_text("b")

    copied = fa.copy_files([str(src_dir / "*.txt")], str(dst_dir))
    assert sorted(Path(c).name for c in copied) == ["a.txt", "b.txt"]


def test_move_files_is_noop_for_same_destination(tmp_path: Path) -> None:
    src_file = tmp_path / "a.txt"
    src_file.write_text("a")
    fa.move_files([str(src_file)], str(tmp_path))
    assert src_file.exists()


def test_delete_files_missing_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(fa.FileNotFoundError):
        fa.delete_files([str(tmp_path / "missing.txt")])


def test_delete_files_removes_file(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("a")
    fa.delete_files([str(f)])
    assert not f.exists()


def test_sequential_numberer_increments_across_calls() -> None:
    numberer = fa.SequentialNumberer(start=1, increment=2)
    assert [numberer.next() for _ in range(3)] == [1, 3, 5]


def test_rename_make_sequential_uses_shared_numberer_state() -> None:
    numberer = fa.SequentialNumberer(start=1, increment=1)
    assert fa.rename_make_sequential("file.txt", numberer, digits=3) == "file001.txt"
    assert fa.rename_make_sequential("file.txt", numberer, digits=3) == "file002.txt"


def test_rename_schemes() -> None:
    assert fa.rename_set_new_name("old.txt", "new") == "new.txt"
    assert fa.rename_add_text("file.txt", "_v2", position="Suffix") == "file_v2.txt"
    assert fa.rename_add_text("file.txt", "v2_", position="Prefix") == "v2_file.txt"
    assert fa.rename_remove_text("file_old.txt", "_old") == "file.txt"
    assert fa.rename_replace_text("file_old.txt", "old", "new") == "file_new.txt"
    assert fa.rename_change_extension("file.txt", "csv") == "file.csv"


def test_apply_rename_is_case_insensitive_noop_for_same_name(tmp_path: Path) -> None:
    f = tmp_path / "File.txt"
    f.write_text("x")
    result = fa.apply_rename(str(tmp_path), "File.txt", "file.txt")
    assert result == f
    assert f.exists()


def test_apply_rename_do_nothing_skips_existing_target(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("a")
    dst = tmp_path / "b.txt"
    dst.write_text("b")
    result = fa.apply_rename(str(tmp_path), "a.txt", "b.txt")
    assert result == src
    assert src.exists()
    assert dst.read_text() == "b"


def test_base64_round_trip(tmp_path: Path) -> None:
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello bytes")
    encoded = fa.file_to_base64(str(f))
    out = tmp_path / "b.bin"
    fa.base64_to_file(encoded, str(out))
    assert out.read_bytes() == b"hello bytes"


def test_binary_round_trip(tmp_path: Path) -> None:
    f = tmp_path / "a.bin"
    f.write_bytes(b"\x00\x01\x02")
    data = fa.file_to_binary(str(f))
    out = tmp_path / "b.bin"
    fa.binary_to_file(data, str(out))
    assert out.read_bytes() == b"\x00\x01\x02"


def test_read_text_from_file_default_utf8(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")
    assert fa.read_text_from_file(str(f)) == "hello"


def test_read_text_from_file_as_list(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("a\nb\nc")
    assert fa.read_text_from_file(str(f), store_content_as="List") == ["a", "b", "c"]


def test_read_text_from_file_missing_raises() -> None:
    with pytest.raises(fa.FileNotFoundError):
        fa.read_text_from_file("/nonexistent/path.txt")


def test_write_text_to_file_default_encoding_is_utf16(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    fa.write_text_to_file(str(f), "hi", append_new_line=False)
    assert f.read_bytes().startswith(b"\xff\xfe")  # UTF-16 LE BOM
    assert f.read_text(encoding="utf-16") == "hi"


def test_write_text_to_file_appends_newline_by_default(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    fa.write_text_to_file(str(f), "hi", encoding="UTF8")
    assert f.read_bytes() == b"hi\r\n"


def test_write_text_to_file_datarow_joins_with_comma_space(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    fa.write_text_to_file(str(f), [{"a": 1, "b": 2}], append_new_line=False, encoding="UTF8")
    assert f.read_text(encoding="utf-8") == "1, 2"


def test_csv_round_trip(tmp_path: Path) -> None:
    f = tmp_path / "a.csv"
    table = [{"a": "1", "b": "2"}]
    fa.write_to_csv_file(str(f), table, encoding="UTF8")
    assert fa.read_from_csv_file(str(f), encoding="UTF8") == table


def test_get_file_path_part(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    parts = fa.get_file_path_part(str(f))
    assert parts["FileName"] == "a.txt"
    assert parts["FileNameWithoutExtension"] == "a"
    assert parts["Extension"] == ".txt"


def test_get_temp_file_path_creates_unique_file() -> None:
    path1 = fa.get_temp_file_path()
    path2 = fa.get_temp_file_path()
    try:
        assert path1 != path2
        assert Path(path1).exists()
    finally:
        Path(path1).unlink(missing_ok=True)
        Path(path2).unlink(missing_ok=True)


def test_if_file_exists(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    assert fa.if_file_exists(str(f)) is False
    f.write_text("x")
    assert fa.if_file_exists(str(f)) is True
