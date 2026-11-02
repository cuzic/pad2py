"""UIA3 Raw View への直接アクセス(検証項目 A5/A6, comtypes経由)。

pywinautoの標準View(Control View)が仮想化リストやElectron系アプリで要素を
取得できない場合のフォールバック手段として、RawViewWalkerで直接ツリーを走査する。
PAD自身が「UIA3 Raw」モードに切り替える状況と同じ条件を想定したもの
(research_notes/.../04_selector_mapping.md 参照)。

comtypes.gen.UIAutomationClient はこのプロセスで初めて使われるタイミングで
動的に型ライブラリから生成されるため、モジュールのimport自体は安全に行えるよう、
生成処理は呼び出し時(関数内)に遅延させている。
"""
from __future__ import annotations

from typing import Any, Callable

import comtypes
import comtypes.client


def _load_uia_module() -> Any:
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as UIA  # noqa: PLC0415

    return UIA


def get_raw_view_children_count(hwnd: int) -> int:
    """指定ウィンドウのRawViewにおける直下の子要素数を返す。

    フォールバック経路が例外なく動作することの最小確認が主目的。
    """
    uia_mod = _load_uia_module()
    uia = comtypes.client.CreateObject(uia_mod.CUIAutomation, interface=uia_mod.IUIAutomation)
    element = uia.ElementFromHandle(hwnd)
    walker = uia.RawViewWalker

    count = 0
    child = walker.GetFirstChildElement(element)
    while child is not None:
        count += 1
        try:
            child = walker.GetNextSiblingElement(child)
        except Exception:
            break
    return count


def register_focus_changed_handler(callback: Callable[[Any], None]) -> tuple[Any, Any]:
    """フォーカス変化イベントを購読する(検証項目 A6)。

    戻り値は unregister_focus_changed_handler に渡すための登録情報。
    """
    uia_mod = _load_uia_module()
    uia = comtypes.client.CreateObject(uia_mod.CUIAutomation, interface=uia_mod.IUIAutomation)

    class _FocusHandler(comtypes.COMObject):
        _com_interfaces_ = [uia_mod.IUIAutomationFocusChangedEventHandler]

        def IUIAutomationFocusChangedEventHandler_HandleFocusChangedEvent(self, sender: Any) -> None:
            callback(sender)

    handler = _FocusHandler()
    uia.AddFocusChangedEventHandler(handler)
    return uia, handler


def unregister_focus_changed_handler(registration: tuple[Any, Any]) -> None:
    uia, handler = registration
    uia.RemoveFocusChangedEventHandler(handler)
