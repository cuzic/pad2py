"""`win32gui`/`win32con`(pywin32)の最小限のフェイク実装。

design/common_rpa_framework_roadmap.md 層7(c)。`win32gui`/`win32con`はLinuxでは
そもそも`import`できない(`tests/fake_pywinauto.py`のpywinautoと違い、パッケージ自体が
存在しない)ため、`sys.modules`へ直接フェイクモジュールを差し込む方式を取る。

対応しているAPI表面は`dump_daemon/pad_codegen/actions/_window_state.py`・`ui_element.py`
が実際に生成する呼び出し(`GetWindowRect`/`MoveWindow`/`ShowWindow`/
`GetForegroundWindow`、`SW_SHOW`/`SW_HIDE`定数)のみ——新しい呼び出し形が増えたら、
その都度ここに追加する(未対応の呼び出しをでっち上げて成功させない)。
"""
from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from typing import Iterator


class FakeWin32Registry:
    """1テスト分のフェイクウィンドウ状態(スクリプト可能)+呼び出しログ。"""

    def __init__(self) -> None:
        self.rects: dict[int, tuple[int, int, int, int]] = {}
        self.foreground_hwnd = 0
        self.calls: list[tuple[object, ...]] = []

    def set_rect(self, hwnd: int, left: int, top: int, right: int, bottom: int) -> None:
        self.rects[hwnd] = (left, top, right, bottom)

    def set_foreground(self, hwnd: int) -> None:
        self.foreground_hwnd = hwnd


def _make_win32gui_module(registry: FakeWin32Registry) -> types.ModuleType:
    mod = types.ModuleType("win32gui")

    def GetWindowRect(hwnd: int) -> tuple[int, int, int, int]:
        return registry.rects.get(hwnd, (0, 0, 0, 0))

    def MoveWindow(hwnd: int, x: int, y: int, width: int, height: int, repaint: bool) -> None:
        registry.calls.append(("MoveWindow", hwnd, x, y, width, height, repaint))

    def ShowWindow(hwnd: int, flag: int) -> None:
        registry.calls.append(("ShowWindow", hwnd, flag))

    def GetForegroundWindow() -> int:
        return registry.foreground_hwnd

    mod.GetWindowRect = GetWindowRect  # type: ignore[attr-defined]
    mod.MoveWindow = MoveWindow  # type: ignore[attr-defined]
    mod.ShowWindow = ShowWindow  # type: ignore[attr-defined]
    mod.GetForegroundWindow = GetForegroundWindow  # type: ignore[attr-defined]
    return mod


def _make_win32con_module() -> types.ModuleType:
    mod = types.ModuleType("win32con")
    mod.SW_SHOW = 5  # type: ignore[attr-defined]
    mod.SW_HIDE = 0  # type: ignore[attr-defined]
    return mod


@contextmanager
def fake_win32_modules(registry: FakeWin32Registry) -> Iterator[None]:
    """`win32gui`/`win32con`を`sys.modules`上でフェイクに差し替える(ブロックを抜けたら
    元の状態に戻す——未インストールだった場合は`sys.modules`から取り除く)。
    """
    names_and_modules = {
        "win32gui": _make_win32gui_module(registry),
        "win32con": _make_win32con_module(),
    }
    saved: dict[str, types.ModuleType | None] = {
        name: sys.modules.get(name) for name in names_and_modules
    }
    sys.modules.update(names_and_modules)
    try:
        yield
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
