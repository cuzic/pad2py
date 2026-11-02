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

    from pywinauto.application import Application

    app = Application(backend="uia").start("notepad.exe")
    time.sleep(1)
    window = app.top_window()
    window.wait("visible", timeout=10)
    try:
        yield window
    finally:
        try:
            window.close()
        except Exception:
            pass
        try:
            app.kill()
        except Exception:
            pass
