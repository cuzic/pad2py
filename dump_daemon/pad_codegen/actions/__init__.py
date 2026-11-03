"""`ActionRecord` → Pythonコードのディスパッチ。

各アクションファミリーモジュール(`scripting`/`mouse_keyboard`/`window`/`ui_element`)は
互いを一切知らない(疎結合)。`generate_action()`は各ファミリーの`generate()`を順番に
試し、最初に`None`以外を返したものを採用する——全て`None`なら、でっち上げたコードを
出力せず安全な`# TODO`コメント(関連UI要素のヒント付き)にフォールバックする。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ..selectors import _ui_element_hint
from . import mouse_keyboard, scripting, ui_element, window

_FAMILIES = (scripting, mouse_keyboard, window, ui_element)


def generate_action(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str]:
    for family in _FAMILIES:
        result = family.generate(node, indent, ctx)
        if result is not None:
            return result
    prefix = INDENT * indent
    return [f"{prefix}# TODO: map PAD action: {node.action_id}{_ui_element_hint(node, ctx)}"]
