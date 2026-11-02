from __future__ import annotations

import sys
import time

import pytest


@pytest.fixture
def notepad_window():
    """検証用にNotepadを起動し、pywinauto(uiaバックエンド)のトップウィンドウを返す。

    Windows以外ではスキップする。GitHub Actions windows-latest には標準でNotepadが
    同梱されている前提(A1/A2等の検証の土台)。
    """
    if sys.platform != "win32":
        pytest.skip("Windows専用のフィクスチャ")

    import subprocess

    from pywinauto import Desktop

    # CI検証で判明した知見: pywinauto の Application.start()+top_window() は
    # 起動元プロセスIDでウィンドウを検索するが、Windows 11以降のNotepadは
    # 起動元プロセスとウィンドウ所有プロセスが一致しない場合があり
    # "No windows for that process could be found" で失敗する。
    # そのため本番のdump_daemon._get_foreground_window()と同じ、
    # タイトルベースでDesktopから検索する方式に統一する。
    proc = subprocess.Popen(["notepad.exe"])
    window = None
    for _ in range(30):
        time.sleep(0.5)
        try:
            candidates = Desktop(backend="uia").windows(title_re=".*Notepad.*")
        except Exception:
            candidates = []
        if candidates:
            window = candidates[0]
            break
    if window is None:
        proc.terminate()
        pytest.fail("Notepadウィンドウをタイムアウト内に検出できなかった")

    window.wait("visible", timeout=10)
    try:
        yield window
    finally:
        try:
            window.close()
        except Exception:
            pass
        try:
            proc.terminate()
        except Exception:
            pass
