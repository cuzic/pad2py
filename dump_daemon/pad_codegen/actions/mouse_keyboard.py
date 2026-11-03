"""`MouseAndKeyboard.*`(マウス/キーボード直接操作)系アクションのcodegen。

pyautoguiへのマッピングのみで完結し、UI要素リポジトリ(`CodegenContext`)は参照しない。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord, EnumRef
from ..context import CodegenContext
from ..render import INDENT, render_value

# MouseAndKeyboard.PressReleaseKey.*のBoolパラメータ名 → pyautoguiのキー名。
_MODIFIER_TO_PYAUTOGUI_KEY = {
    "Control": "ctrl",
    "Alt": "alt",
    "Shift": "shift",
    "Win": "win",
}


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    prefix = INDENT * indent
    if node.action_id == "MouseAndKeyboard.SendKeys.FocusAndSendKeys":
        text = node.params.get("TextToSend")
        if isinstance(text, str):
            delay_ms = node.params.get("DelayBetweenKeystrokes", 10)
            interval = delay_ms / 1000 if isinstance(delay_ms, (int, float)) else 0.01
            return [f"{prefix}pyautogui.typewrite({render_value(text)}, interval={interval!r})"]
    if node.action_id == "MouseAndKeyboard.MoveMouse":
        x = node.params.get("X")
        y = node.params.get("Y")
        # "Relative to: Window"や"Move mouse from previous position: Smoothly"は
        # pyautoguiでの対応方法が未検証のため、確認済みの組み合わせ(Screen基準・Instant)の
        # ときだけ変換する。
        if (
            isinstance(x, (int, float))
            and isinstance(y, (int, float))
            and node.params.get("RelativeTo") == EnumRef("MouseAndKeyboard.PositionRelativeTo.Screen")
            and node.params.get("MovementStyle") == EnumRef("MouseAndKeyboard.MovementStyle.Instant")
        ):
            return [f"{prefix}pyautogui.moveTo({render_value(x)}, {render_value(y)})"]
    if node.action_id == "MouseAndKeyboard.SendMouseClick.Click":
        # "Mouse event to send"には他に7種(Right click/Double click/Middle click等)あるが
        # (design/dsl_format_findings.md 知見21)、実機確認したのはLeft clickのDSL表現
        # (MouseAndKeyboard.MouseClickType.LeftClick)だけなので、それ以外は推測で
        # マッピングせずTODOに倒す。
        if node.params.get("ClickType") == EnumRef("MouseAndKeyboard.MouseClickType.LeftClick"):
            delay_ms = node.params.get("MillisecondsDelay", 0)
            lines = []
            if isinstance(delay_ms, (int, float)) and delay_ms:
                lines.append(f"{prefix}time.sleep({delay_ms / 1000!r})")
            lines.append(f"{prefix}pyautogui.click()")
            return lines
    if node.action_id in (
        "MouseAndKeyboard.PressReleaseKey.PressKey",
        "MouseAndKeyboard.PressReleaseKey.ReleaseKey",
    ):
        # Control/Alt/Shift/Winのうちどれか1つだけがTrueの組み合わせのみ実機検証済み
        # (design/dsl_format_findings.md 知見23)。0個または複数同時Trueの場合の意味論は
        # 未検証のため推測しない。
        active = [name for name in _MODIFIER_TO_PYAUTOGUI_KEY if node.params.get(name) is True]
        if len(active) == 1:
            pyautogui_key = _MODIFIER_TO_PYAUTOGUI_KEY[active[0]]
            func = "keyDown" if node.action_id.endswith("PressKey") else "keyUp"
            return [f"{prefix}pyautogui.{func}({pyautogui_key!r})"]
    return None
