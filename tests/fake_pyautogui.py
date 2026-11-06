"""`pyautogui`の最小限のフェイク実装。

design/common_rpa_framework_roadmap.md 層7(検証基盤・シミュレータ)、(b)/(c)と同じ
考え方を`MouseAndKeyboard.*`(pyautoguiへのマッピング)にも適用する。`pyautogui`は
本プロジェクトの依存関係としてインストールされておらず(`pyproject.toml`参照、説明文に
名前が出るだけ)、かつ実機でもXサーバー等のディスプレイ依存のため、`win32gui`/`win32con`
と同じ`sys.modules`注入方式を取る(`tests/fake_win32.py`参照)。

対応しているAPI表面は`dump_daemon/pad_codegen/actions/mouse_keyboard.py`が実際に
生成する呼び出し(`click()`/`moveTo(x, y)`/`typewrite(text, interval=...)`/
`keyDown(key)`/`keyUp(key)`)のみ——新しい呼び出し形が出てきたら、その都度ここに
追加する(未対応の呼び出しをでっち上げて成功させるのではなく、素直に
`AttributeError`で気づけるようにする)。
"""
from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from typing import Iterator


class FakePyAutoGuiRegistry:
    """1テスト分の呼び出しログ。"""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []


def _make_pyautogui_module(registry: FakePyAutoGuiRegistry) -> types.ModuleType:
    mod = types.ModuleType("pyautogui")

    def click() -> None:
        registry.calls.append(("click",))

    def moveTo(x: float, y: float) -> None:
        registry.calls.append(("moveTo", x, y))

    def typewrite(text: str, interval: float = 0.0) -> None:
        registry.calls.append(("typewrite", text, interval))

    def keyDown(key: str) -> None:
        registry.calls.append(("keyDown", key))

    def keyUp(key: str) -> None:
        registry.calls.append(("keyUp", key))

    mod.click = click  # type: ignore[attr-defined]
    mod.moveTo = moveTo  # type: ignore[attr-defined]
    mod.typewrite = typewrite  # type: ignore[attr-defined]
    mod.keyDown = keyDown  # type: ignore[attr-defined]
    mod.keyUp = keyUp  # type: ignore[attr-defined]
    return mod


@contextmanager
def fake_pyautogui_module(
    registry: FakePyAutoGuiRegistry | None = None,
) -> Iterator[FakePyAutoGuiRegistry]:
    """`pyautogui`を`sys.modules`上でフェイクに差し替える(ブロックを抜けたら
    元の状態に戻す——未インストールだった場合は`sys.modules`から取り除く)。
    """
    reg = registry if registry is not None else FakePyAutoGuiRegistry()
    saved = sys.modules.get("pyautogui")
    sys.modules["pyautogui"] = _make_pyautogui_module(reg)
    try:
        yield reg
    finally:
        if saved is None:
            sys.modules.pop("pyautogui", None)
        else:
            sys.modules["pyautogui"] = saved
