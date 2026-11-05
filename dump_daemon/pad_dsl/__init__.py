"""PADクリップボードDSLの字句・構文解析 core。

`parse_dsl()`(テキスト → フラットな`Record`列)・`build_block_tree()`(`Record`列 →
ブロック木`Node`)が本coreの公開APIの中心。内部は関心事ごとに以下のサブモジュールへ
分割している:

- `tokens`: エスケープ/マスキングの正規表現・解除関数
- `types`: `VarRef`/`RawExpr`/各種`*Record`/`Node`等の値・ASTノード型(他coreもここを参照)
- `line_parser`: 1行分のテキスト(マスキング済み)を`Record`へ変換する`_parse_line()`
- `block_tree`: フラットな`Record`列から`Node`のブロック木を組み立てる`build_block_tree()`

UI要素リポジトリJSON(`# [ControlRepository]...`節)は完全に別フォーマットのため、
`control_repository`coreとして独立させている——本モジュールは区切り行の位置を知って
テキストを前後に分割するだけで、JSON自体のパースには一切関与しない。
"""
from __future__ import annotations

import re

from ..control_repository import _split_control_repository
from .block_tree import build_block_tree
from .line_parser import _parse_line
from .tokens import _COMMENT_RE, _STRING_RE, _UI_ELEMENT_RE, _UI_ELEMENT_SEGMENT_RE, _unescape_ui_element_segment
from .types import (
    ActionRecord,
    BlockNode,
    BlockRecord,
    CaseDefaultRecord,
    CaseRecord,
    CommentRecord,
    ConditionalNode,
    DpapiSensitiveLiteral,
    ElseIfActionRecord,
    ElseIfFunctionRecord,
    ElseIfRecord,
    EnumRef,
    GuardedNode,
    IfActionRecord,
    IfFunctionRecord,
    IfRecord,
    KeywordRecord,
    LoopForeachRecord,
    LoopRecord,
    LoopWhileRecord,
    Node,
    OnBlockErrorRecord,
    OnErrorNode,
    OnErrorRecord,
    RawExpr,
    RawRecord,
    Record,
    SetVariableRecord,
    SwitchNode,
    SwitchRecord,
    UiElementRef,
    VarRef,
    WaitActionRecord,
)

__all__ = [
    "ActionRecord",
    "BlockNode",
    "BlockRecord",
    "CaseDefaultRecord",
    "CaseRecord",
    "CommentRecord",
    "ConditionalNode",
    "DpapiSensitiveLiteral",
    "ElseIfActionRecord",
    "ElseIfFunctionRecord",
    "ElseIfRecord",
    "EnumRef",
    "GuardedNode",
    "IfActionRecord",
    "IfFunctionRecord",
    "IfRecord",
    "KeywordRecord",
    "LoopForeachRecord",
    "LoopRecord",
    "LoopWhileRecord",
    "Node",
    "OnBlockErrorRecord",
    "OnErrorNode",
    "OnErrorRecord",
    "RawExpr",
    "RawRecord",
    "Record",
    "SetVariableRecord",
    "SwitchNode",
    "SwitchRecord",
    "UiElementRef",
    "VarRef",
    "WaitActionRecord",
    "build_block_tree",
    "parse_dsl",
]


def parse_dsl(text: str) -> list[Record]:
    text, _ = _split_control_repository(text)
    placeholders: dict[str, str | tuple[str, ...]] = {}

    def _stash_comment(m: re.Match[str]) -> str:
        key = f"\x00CMT{len(placeholders)}\x00"
        placeholders[key] = m.group(1)
        return key

    def _stash_string(m: re.Match[str]) -> str:
        key = f"\x00STR{len(placeholders)}\x00"
        placeholders[key] = m.group(1)
        return key

    def _stash_ui_element(m: re.Match[str]) -> str:
        key = f"\x00UIE{len(placeholders)}\x00"
        # 知見46: 各`['...']`セグメントを個別に取り出し、それぞれエスケープを解除してから
        # パス(祖先→対象の順のタプル)として保持する。
        placeholders[key] = tuple(
            _unescape_ui_element_segment(seg) for seg in _UI_ELEMENT_SEGMENT_RE.findall(m.group(0))
        )
        return key

    # コメントを先に退避する(本文中に`$'''`等が含まれていても文字列リテラルとして
    # 誤認されないようにするため)。UI要素参照(`appmask['<表示名>']`)も表示名に空白を
    # 含みうるため同様に退避する。
    masked = _COMMENT_RE.sub(_stash_comment, text)
    masked = _STRING_RE.sub(_stash_string, masked)
    masked = _UI_ELEMENT_RE.sub(_stash_ui_element, masked)

    records: list[Record] = []
    for raw_line in masked.split("\n"):
        if not raw_line.strip():
            continue
        stripped = raw_line.lstrip(" ")
        indent = (len(raw_line) - len(stripped)) // 4
        records.append(_parse_line(stripped.rstrip(), placeholders, indent))
    return records

