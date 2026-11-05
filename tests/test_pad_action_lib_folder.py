"""`pad_action_lib.folder_actions`の単体テスト(tmp_pathで実ファイルシステムを使う)。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from dump_daemon.pad_action_lib import folder_actions as fo


def test_copy_folder_recursive(tmp_path: Path) -> None:
    # design/dsl_format_findings.md 知見130(実機確認済み): `destination`はコピー先の
    # 正確なパスではなく、既存の親フォルダ——結果は`destination/<sourceの名前>`に
    # ネストされ、戻り値はそのネストされたパス。
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_text("a")
    (src / "sub" / "b.txt").write_text("b")
    dst_parent = tmp_path / "dst"
    dst_parent.mkdir()

    result = fo.copy_folder(str(src), str(dst_parent))
    copied = dst_parent / "src"
    assert result == str(copied)
    assert (copied / "a.txt").read_text() == "a"
    assert (copied / "sub" / "b.txt").read_text() == "b"


def test_copy_folder_requires_existing_destination(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("a")
    missing_dst = tmp_path / "does_not_exist"

    with pytest.raises(fo.InvalidDestinationFolderError):
        fo.copy_folder(str(src), str(missing_dst))


def test_create_folder_combines_path_and_name(tmp_path: Path) -> None:
    result = fo.create_folder(str(tmp_path), "newdir")
    assert Path(result).is_dir()
    assert Path(result) == tmp_path / "newdir"


def test_delete_folder_is_recursive(tmp_path: Path) -> None:
    target = tmp_path / "dir"
    (target / "sub").mkdir(parents=True)
    (target / "sub" / "f.txt").write_text("x")
    fo.delete_folder(str(target))
    assert not target.exists()


def test_delete_folder_missing_raises() -> None:
    with pytest.raises(fo.FolderNotFoundError):
        fo.delete_folder("/nonexistent/dir")


def test_empty_folder_removes_children_but_keeps_folder(tmp_path: Path) -> None:
    target = tmp_path / "dir"
    (target / "sub").mkdir(parents=True)
    (target / "a.txt").write_text("a")
    fo.empty_folder(str(target))
    assert target.is_dir()
    assert list(target.iterdir()) == []


def test_move_folder(tmp_path: Path) -> None:
    # design/dsl_format_findings.md 知見131(実機確認済み): `destination`は`copy_folder()`
    # (知見130)と同じく既存の親フォルダで、結果は`destination/<sourceの名前>`にネストされる。
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("a")
    dst_parent = tmp_path / "dst"
    dst_parent.mkdir()
    result = fo.move_folder(str(src), str(dst_parent))
    moved = dst_parent / "src"
    assert result == str(moved)
    assert not src.exists()
    assert (moved / "a.txt").read_text() == "a"


def test_move_folder_requires_existing_destination(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    missing_dst = tmp_path / "does_not_exist"
    with pytest.raises(fo.InvalidDestinationFolderError):
        fo.move_folder(str(src), str(missing_dst))


def test_move_folder_existing_nested_target_raises(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    dst_parent = tmp_path / "dst"
    dst_parent.mkdir()
    (dst_parent / "src").mkdir()  # ネストされた移動先が既に存在する
    with pytest.raises(fo.MoveFolderError):
        fo.move_folder(str(src), str(dst_parent))


def test_rename_folder(tmp_path: Path) -> None:
    src = tmp_path / "old"
    src.mkdir()
    result = fo.rename_folder(str(src), "new")
    assert result == tmp_path / "new"
    assert result.is_dir()


def test_rename_folder_existing_target_is_silent_noop(tmp_path: Path) -> None:
    src = tmp_path / "old"
    src.mkdir()
    dst = tmp_path / "new"
    dst.mkdir()
    result = fo.rename_folder(str(src), "new")
    assert result == src
    assert src.is_dir()  # リネームされないのに失敗しない罠


def test_get_files_in_folder_with_multiple_masks(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.csv").write_text("b")
    (tmp_path / "c.log").write_text("c")
    files = fo.get_files_in_folder(str(tmp_path), file_filter="*.txt;*.csv")
    names = sorted(Path(f).name for f in files)
    assert names == ["a.txt", "b.csv"]


def test_get_files_in_folder_sorted_by_name_descending(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    files = fo.get_files_in_folder(str(tmp_path), sort_by=[("Name", True)])
    names = [Path(f).name for f in files]
    assert names == ["b.txt", "a.txt"]


def test_get_subfolders_in_folder(tmp_path: Path) -> None:
    (tmp_path / "sub1").mkdir()
    (tmp_path / "sub2").mkdir()
    (tmp_path / "file.txt").write_text("x")
    folders = fo.get_subfolders_in_folder(str(tmp_path))
    names = sorted(Path(f).name for f in folders)
    assert names == ["sub1", "sub2"]


def test_if_folder_exists(tmp_path: Path) -> None:
    assert fo.if_folder_exists(str(tmp_path)) is True
    assert fo.if_folder_exists(str(tmp_path / "missing")) is False


def test_get_special_folder_temp_always_resolves() -> None:
    # 生成スクリプトは常にWindows上で実行される前提だが、`tempfile.gettempdir()`は
    # クロスプラットフォームで常に動く(TMPDIR/TEMP/TMPいずれかの環境変数、または
    # OS既定のtempディレクトリ)ため、"Temp"だけはこのリポジトリのCI(Linux)上でも
    # 実際にテストできる。
    import tempfile

    assert fo.get_special_folder("Temp") == tempfile.gettempdir()


def test_get_special_folder_respects_xdg_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DESKTOP_DIR", "/tmp/fake-desktop")
    assert fo.get_special_folder("Desktop") == "/tmp/fake-desktop"


def test_get_special_folder_unknown_name_raises() -> None:
    with pytest.raises(NotImplementedError):
        fo.get_special_folder("SomeUnmappedSpecialFolder")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows専用(SHGetFolderPath)")
def test_get_special_folder_desktop_resolves_via_csidl_on_windows() -> None:
    # design/dsl_format_findings.md 知見84: `Folder.GetSpecialFolder`の唯一の実機確認
    # 済み値`DesktopDirectory`は`pad_codegen`が`"Desktop"`へ結線する。以前の実装は
    # Linux向けのXDG環境変数しか見ておらず、実際のWindows実行環境では(XDG変数が
    # 存在しないため)常にNotImplementedErrorになっていた——`win32com.shell.shell.
    # SHGetFolderPath`(公開されたWindows API、PAD固有の推測ではない)経由で実際に
    # 解決できることを確認する。
    path = fo.get_special_folder("Desktop")
    assert path
    assert Path(path).name.lower() in ("desktop",)
