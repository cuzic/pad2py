"""A4: Electron/Chromium系アプリでpywinauto標準View(Control View)が
要素取得にどう振る舞うかの検証。

CI環境に対象アプリが無い場合はスキップし、その事実自体を記録として残す。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time

import pytest

from dump_daemon.uia_capture import dump_uia_tree, flatten_control_types

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows専用")

# GitHub Actions windows-latest ランナーに pre-installed されている可能性のある
# Electron/Chromium系アプリの候補(ドキュメントの事前確認はできないため実機で確認する)。
CANDIDATE_LAUNCHERS = [
    ("VSCode", ["code", "--new-window", "--disable-gpu"]),
    ("Edge", ["msedge", "--new-window", "about:blank"]),
]


def _resolve_launcher(name: str, argv: list[str]) -> list[str] | None:
    exe = shutil.which(argv[0])
    if exe is None:
        return None
    return [exe] + argv[1:]


def _find_available_app() -> tuple[str, list[str]] | None:
    for name, argv in CANDIDATE_LAUNCHERS:
        resolved = _resolve_launcher(name, argv)
        if resolved is not None:
            return name, resolved
    return None


def test_pywinauto_control_view_on_electron_or_chromium_app(tmp_path) -> None:
    found = _find_available_app()
    if found is None:
        tried = [name for name, _ in CANDIDATE_LAUNCHERS]
        pytest.skip(f"検証対象のElectron/Chromium系アプリがランナー上に見つからなかった(試行: {tried})")

    name, argv = found
    proc = subprocess.Popen(argv)
    try:
        from pywinauto import Desktop

        window = None
        for _ in range(40):
            time.sleep(0.5)
            try:
                # どちらも最終的なウィンドウタイトルが起動直後は不定(タブ名やプロファイル名に依存)
                # なため、全トップレベルウィンドウを取得して最も要素数が多いものを採用する。
                candidates = Desktop(backend="uia").windows()
            except Exception:
                candidates = []
            if candidates:
                window = max(candidates, key=lambda w: _safe_descendant_count(w))
                if _safe_descendant_count(window) > 0:
                    break
        if window is None:
            pytest.skip(f"{name} のウィンドウをタイムアウト内に検出できなかった")

        tree = dump_uia_tree(window)
        control_types = flatten_control_types(tree)
        element_count = len(control_types)

        # 失敗(クラッシュ)しないことと、取得できた要素数を記録することが目的。
        # Electron/Chromium系では取得できる要素数が極端に少ない(=標準Viewで内部要素が
        # 見えていない)可能性があるため、厳密な下限は設けず情報として記録する。
        print(f"[A4] {name}: dump_uia_tree で {element_count} 要素を取得, capture_mode=UIA")
        assert element_count >= 1, f"{name} のウィンドウからルート要素すら取得できなかった"
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


def _safe_descendant_count(window) -> int:
    try:
        return len(window.descendants())
    except Exception:
        return 0
