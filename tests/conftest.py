from __future__ import annotations

import sys

import pytest


@pytest.fixture
def notepad_window():
    """検証用にNotepadを起動し、pywinauto(uiaバックエンド)のトップウィンドウを返す。

    Windows以外ではスキップする。GitHub Actions windows-latest には標準でNotepadが
    同梱されている前提(A1/A2等の検証の土台)。

    CI検証で判明した知見: pywinauto の Application.start()+top_window() は
    起動元プロセスIDでウィンドウを検索するが、Windows 11以降のNotepadは
    起動元プロセスとウィンドウ所有プロセスが一致しない場合があり
    "No windows for that process could be found" で失敗する。
    そのため、タイトルベースで検索する Desktop().window()(複数形の .windows() ではない)
    を使う。.window() は WindowSpecification を返すため .wait()/.child_window() が
    使えるが、.windows() が返す生のラッパーオブジェクトにはこれらが無い。
    """
    if sys.platform != "win32":
        pytest.skip("Windows専用のフィクスチャ")

    import subprocess

    from pywinauto import Desktop

    proc = subprocess.Popen(["notepad.exe"])
    window = Desktop(backend="uia").window(title_re=".*Notepad.*")
    try:
        window.wait("visible", timeout=15)
    except Exception as exc:
        proc.terminate()
        pytest.fail(f"Notepadウィンドウをタイムアウト内に検出できなかった: {exc!r}")

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
