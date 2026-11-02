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


def test_captured_selector_survives_process_restart(tmp_path) -> None:
    """E2: プロセスを再起動(ウィンドウハンドルが変わる)しても、AutomationId/ControlType
    ベースのcriteriaで同じ要素を再検出できるか。"""
    import time

    from pywinauto.application import Application

    from dump_daemon.uia_capture import dump_uia_tree, find_first_with_automation_id

    app1 = Application(backend="uia").start("notepad.exe")
    time.sleep(1)
    window1 = app1.top_window()
    window1.wait("visible", timeout=10)
    tree = dump_uia_tree(window1)
    target = find_first_with_automation_id(tree)
    handle1 = window1.handle
    app1.kill()

    if target is None:
        pytest.skip("AutomationIdを持つ要素が見つからなかった(UI構成依存)")

    app2 = Application(backend="uia").start("notepad.exe")
    time.sleep(1)
    window2 = app2.top_window()
    window2.wait("visible", timeout=10)
    try:
        assert window2.handle != handle1, "ウィンドウハンドルが再利用されてしまい、この検証の前提が崩れている"
        relocated = window2.child_window(
            auto_id=target["automation_id"], control_type=target["control_type"]
        )
        assert relocated.exists(timeout=5), (
            "プロセス再起動後、ハンドルに依存しないcriteriaで要素を再検出できなかった"
        )
    finally:
        app2.kill()
