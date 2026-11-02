from __future__ import annotations

import sys
import time

import pytest


@pytest.fixture
def notepad_window():
    """検証用にNotepadを起動し、pywinauto(uiaバックエンド)のトップウィンドウを返す。

    Windows以外ではスキップする。GitHub Actions windows-latest には標準でNotepadが
    同梱されている前提(A1/A2等の検証の土台)。

    CI検証で判明した知見(複数回の実行で段階的に判明したもの):
    1. Application.start()+top_window() は起動元プロセスIDでウィンドウを検索するが、
       Windows 11以降のNotepadでは起動元プロセスとウィンドウ所有プロセスが一致せず
       "No windows for that process could be found" で失敗する。
    2. Desktop().windows(title_re=...)(複数形)は visible_only=False を明示するため
       検出できるが、返り値は生のUIAWrapperで .wait()/.child_window() が無い。
    3. Desktop().window(title_re=...)(単数形、WindowSpecification)は
       visible_only等のデフォルトが異なり、同じ条件で .wait("visible") がタイムアウトする
       (このCI環境ではNotepadウィンドウがUIA上 IsVisible=False を報告する時間帯がある
       と推測される)。
    よって、まず(2)の方式で確実に検出し、見つかったウィンドウのhandleで
    Desktop().window(handle=...) に包み直すことで、.wait()等が使える
    WindowSpecificationを可視性フィルタに左右されずに得る。
    4. ウィンドウが見つかった直後はまだ内部コントロールツリー(テキスト編集領域等)が
       完全に構築されていない場合があり、直後にdump_uia_treeすると要素が少ない状態の
       スナップショットになることがある(実行によって再現する間欠的な事象)。
       子要素数が安定するまで短く待ってから返す。
    """
    if sys.platform != "win32":
        pytest.skip("Windows専用のフィクスチャ")

    import subprocess

    from pywinauto import Desktop

    proc = subprocess.Popen(["notepad.exe"])
    raw_window = None
    for _ in range(30):
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
        pytest.fail("Notepadウィンドウをタイムアウト内に検出できなかった")

    window = Desktop(backend="uia").window(handle=raw_window.handle)

    # 内部コントロールツリーが構築され切るまで、子要素数が増え続けていないことを
    # 確認してから返す(最大5秒)。
    previous_count = -1
    for _ in range(25):
        try:
            current_count = len(window.descendants())
        except Exception:
            current_count = previous_count
        if current_count == previous_count and current_count > 1:
            break
        previous_count = current_count
        time.sleep(0.2)

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
