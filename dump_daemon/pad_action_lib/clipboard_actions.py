"""`Clipboard.Actions`(`System.Windows.Forms.Clipboard`の薄いラッパー、テキストのみ)のロジック層。

`SetText`は`catch (Exception) {}`で全例外を黙って握りつぶす([Throws]タグすら
宣言されていない)——クリップボードがロックされている等の失敗がPADフローに一切
見えないという、このプロジェクトが重視する「サイレントな失敗」の典型例として、
あえて潰さず再現する(「改善」しない)。`Clear`は`SetText`より対象例外がやや狭い
(`ThreadStateException`/`ExternalException`相当のみ)という記述があるが、Pythonの
クリップボードライブラリの例外型はこれらに1:1対応しないため、この層では両方とも
「全例外を握りつぶす」で近似する。
"""
from __future__ import annotations

import pyperclip

from .errors import PadActionError


class RetrieveContentsError(PadActionError):
    pass


def get_clipboard_text() -> str:
    try:
        text = pyperclip.paste()
    except Exception as exc:
        # API自体の失敗だけRetrieveContentsErrorにする
        # (クリップボードがテキストを持たない場合は""を返す、エラーにならない)。
        raise RetrieveContentsError(str(exc)) from exc
    return text or ""


def set_clipboard_text(text: str) -> None:
    try:
        # 空文字列のSetTextは.NET側で例外になるため、Clear()相当で回避する。
        pyperclip.copy(text if text else "")
    except Exception:
        pass


def clear_clipboard() -> None:
    try:
        pyperclip.copy("")
    except Exception:
        pass
