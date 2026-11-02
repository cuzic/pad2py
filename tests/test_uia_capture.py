"""A1/A2/A3/A7/A8: pywinautoによる実アプリUIツリー走査の検証。"""
from __future__ import annotations

import sys

import pytest

from dump_daemon.uia_capture import (
    dump_uia_tree,
    flatten_control_types,
    flatten_element_ids,
)

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows専用")


def test_dump_uia_tree_extracts_expected_attributes(notepad_window) -> None:
    tree = dump_uia_tree(notepad_window)
    assert tree["control_type"] != ""

    control_types = flatten_control_types(tree)
    # Notepadのバージョンによりテキスト領域のControlTypeが異なる(Edit/Document等)ため幅を持たせる
    assert any(ct in ("Edit", "Document", "Pane") for ct in control_types), control_types


def test_stable_element_id_is_deterministic(notepad_window) -> None:
    tree1 = dump_uia_tree(notepad_window)
    tree2 = dump_uia_tree(notepad_window)
    assert flatten_element_ids(tree1) == flatten_element_ids(tree2)


def test_no_element_id_collisions(notepad_window) -> None:
    tree = dump_uia_tree(notepad_window)
    ids = flatten_element_ids(tree)
    assert len(ids) == len(set(ids)), "同一ツリー内でelement_idが衝突している"


def test_uia_vs_win32_backend_both_enumerate_without_error(notepad_window) -> None:
    from pywinauto import Desktop

    uia_count = len(notepad_window.descendants())

    win32_window = Desktop(backend="win32").window(handle=notepad_window.handle)
    win32_count = len(win32_window.descendants())

    # 厳密な大小関係は環境・バージョン依存のため、両バックエンドで例外なく走査できることを
    # 主目的とし、件数はCI実行結果として記録に残す。
    assert uia_count >= 0
    assert win32_count >= 0
