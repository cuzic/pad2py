"""E1/E2: キャプチャしたAutomationId等から構築したcriteriaで、同じ要素を
再検出できるか(ラウンドトリップ)の検証。"""
from __future__ import annotations

import sys

import pytest

from dump_daemon.uia_capture import dump_uia_tree, find_first_with_automation_id

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows専用")


def test_captured_automation_id_can_relocate_element_in_same_run(notepad_window) -> None:
    tree = dump_uia_tree(notepad_window)
    target = find_first_with_automation_id(tree)
    if target is None:
        pytest.skip("AutomationIdを持つ要素が見つからなかった(UI構成依存)")

    relocated = notepad_window.child_window(
        auto_id=target["automation_id"], control_type=target["control_type"]
    )
    assert relocated.exists(timeout=5), (
        "キャプチャしたAutomationId/ControlTypeから同一実行内で要素を再検出できなかった"
    )


def _launch_notepad_and_find_window(timeout_s: float = 15.0):
    """conftest.notepad_window と同じ方式でNotepadを起動・検出する(詳細はそちらのdocstring参照)。

    Desktop().windows(title_re=...) (複数形、visible_only=False)で確実に検出し、
    見つかったウィンドウのhandleで Desktop().window(handle=...) に包み直すことで、
    .wait()/.child_window() が使えるWindowSpecificationを可視性フィルタに
    左右されずに得る。
    """
    import subprocess
    import time

    from pywinauto import Desktop

    proc = subprocess.Popen(["notepad.exe"])
    deadline = time.time() + timeout_s
    raw_window = None
    while time.time() < deadline:
        time.sleep(0.5)
        try:
            candidates = Desktop(backend="uia").windows(title_re=".*Notepad.*")
        except Exception:
            candidates = []
        if candidates:
            raw_window = candidates[0]
            break

    if raw_window is None:
        proc.terminate()
        raise RuntimeError("Notepadウィンドウをタイムアウト内に検出できなかった")

    window = Desktop(backend="uia").window(handle=raw_window.handle)
    return proc, window


def test_captured_selector_survives_process_restart(tmp_path) -> None:
    """E2: プロセスを再起動(ウィンドウハンドルが変わる)しても、AutomationId/ControlType
    ベースのcriteriaで同じ要素を再検出できるか。"""
    proc1, window1 = _launch_notepad_and_find_window()
    tree = dump_uia_tree(window1)
    target = find_first_with_automation_id(tree)
    handle1 = window1.handle
    proc1.terminate()

    if target is None:
        pytest.skip("AutomationIdを持つ要素が見つからなかった(UI構成依存)")

    proc2, window2 = _launch_notepad_and_find_window()
    try:
        assert window2.handle != handle1, "ウィンドウハンドルが再利用されてしまい、この検証の前提が崩れている"
        relocated = window2.child_window(
            auto_id=target["automation_id"], control_type=target["control_type"]
        )
        assert relocated.exists(timeout=5), (
            "プロセス再起動後、ハンドルに依存しないcriteriaで要素を再検出できなかった"
        )
    finally:
        proc2.terminate()
