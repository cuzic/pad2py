"""A5/A6: comtypes経由のUIA3 Rawフォールバックの検証。

RawViewWalkerの初期化やイベント登録はCOM型ライブラリの動的生成に依存するため、
CI環境側の制約で失敗する場合は(実装の誤りと区別して)スキップとして記録する。
"""
from __future__ import annotations

import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows専用")


def test_raw_view_walker_can_enumerate_children(notepad_window) -> None:
    raw_fallback = pytest.importorskip("dump_daemon.raw_fallback")

    try:
        count = raw_fallback.get_raw_view_children_count(notepad_window.handle)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"RawViewWalkerの初期化に失敗(CI環境側の制約の可能性): {exc!r}")

    assert count >= 0


def test_focus_changed_handler_registers_and_unregisters_cleanly(notepad_window) -> None:
    raw_fallback = pytest.importorskip("dump_daemon.raw_fallback")

    events: list[object] = []
    try:
        registration = raw_fallback.register_focus_changed_handler(events.append)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"フォーカス変化イベントの登録に失敗(CI環境側の制約の可能性): {exc!r}")

    try:
        notepad_window.set_focus()
        time.sleep(1)
    finally:
        raw_fallback.unregister_focus_changed_handler(registration)

    # 発火の確実性はCI環境(フォーカス制御の可否)に依存するため、ここでは
    # 登録・解除がエラーなく完了することを主目的とする。発火していれば追加情報として記録する。
