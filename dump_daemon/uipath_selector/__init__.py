"""UiPathのClassic Selector文字列(`<wnd .../><ctrl .../>`形式)を解析し、
pywinautoの検索条件へマッピングする。

design/uipath_xaml_findings.md 知見37(公式ドキュメント調査、VM不使用)の
範囲から出発し、知見38(2026-11-05、pad2py-pad-host VMの実機Notepadで
実際に検証済み)で以下を確定した:

1. **Classic Selector(`WND`/`CTRL`タグ)のみ対応**。Dynamic Selector
   (`{{Value}}`)・Anchor Base・Computer Vision・Modern活動の
   `Fuzzy selector`/`Strict selector`(知見37、実XAML形が未確認のまま)は
   対象外。
2. **`cls`→`class_name`・`name`→`title`は実機のUIAツリーと一致することを
   確認済み**(知見38)——実際のNotepadの`Edit`コントロールに対し、
   `class_name='Edit'`は一意にマッチし、その要素の実`name`属性値も
   セレクタの`name='Text Editor'`と完全一致した。
3. **`role`→`control_type`は意図的に未対応のまま**(知見38で確定——
   当初`role`の値をそのまま`control_type`へ渡していたが、実機で
   `role='editable text'`を渡すと`control_type`がpywinautoの有効な
   UIA `ControlType`列挙値と一致せず**`KeyError`で即クラッシュ**すると
   判明した。実UIAの`control_type`は`'Edit'`で、UiPathの`role`値
   `'editable text'`とは文字列として一致しない——知見37が警告していた
   「語彙が一致する保証は無い」を実際に裏付け、かつ単なる不一致ではなく
   ハードクラッシュという最悪の形で確認されたため、`role`は安全側に倒して
   意図的に未対応(unmapped)のままにする)。
4. マッピング対応表に無い属性(`app`/`aaname`/`role`等)は**無言で捨てず**、
   コメントとして残す(他の全モジュールと同じ「データを失わない」方針)。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from lxml import etree

# design/uipath_xaml_findings.md 知見37・38で把握した属性語彙のうち、
# 実機検証(知見38)でも安全と確認できたものだけをマッピングする。
# `role`は意図的にマッピングしない(知見38: control_typeへそのまま渡すと
# 実機でKeyErrorになると確認済み)。それ以外(app/aaname/ctrlname/ctrlid/
# aastate等)も未対応のまま残す。
_WND_ATTR_MAP = {
    "cls": "class_name",
    "title": "title",
}
_CTRL_ATTR_MAP = {
    "automationid": "auto_id",
    "name": "title",
}


@dataclass(frozen=True)
class SelectorNode:
    """セレクタXML中の1ノード(`<wnd .../>`または`<ctrl .../>`)。"""

    tag: str
    attrs: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MappedNode:
    """1つの`SelectorNode`をpywinauto検索条件へ変換した結果。"""

    kwargs: dict[str, str]
    unmapped: dict[str, str]
    source_tag: str


def parse_selector(selector_text: str) -> list[SelectorNode]:
    """セレクタ文字列(`<wnd .../><ctrl .../>`の連鎖)をノード列に分解する。

    この形式は複数のルート要素を持つため単体では妥当なXMLではなく、
    一時的なラッパー要素で包んでからパースする。
    """
    wrapped = f"<_root>{selector_text}</_root>"
    root = etree.fromstring(wrapped.encode("utf-8"))
    nodes = []
    for child in root:
        if not isinstance(child.tag, str):
            continue
        nodes.append(SelectorNode(tag=child.tag, attrs=dict(child.attrib)))
    return nodes


def _map_node(node: SelectorNode) -> MappedNode:
    table = _WND_ATTR_MAP if node.tag == "wnd" else _CTRL_ATTR_MAP
    kwargs: dict[str, str] = {}
    unmapped: dict[str, str] = {}
    for key, value in node.attrs.items():
        mapped_key = table.get(key)
        if mapped_key is not None:
            kwargs[mapped_key] = value
        else:
            unmapped[key] = value
    return MappedNode(
        kwargs=kwargs,
        unmapped=unmapped,
        source_tag=node.tag,
    )


def map_selector_nodes(nodes: list[SelectorNode]) -> list[MappedNode]:
    """ノード列をマッピング結果列へ変換する(ノード単位、呼び出し順を保つ)。"""
    return [_map_node(n) for n in nodes]


@dataclass(frozen=True)
class RenderedSelector:
    """`render_pywinauto_chain()`の結果。`expr`は常に非空(マッピング可能な
    属性が1つも無いノードは単に`.child_window()`/`.window()`の呼び出し自体を
    省略するので、最悪の場合でも`Desktop(backend="uia")`までは返す)。
    `warnings`は人間が読むための注意書き(生成コードへコメントとして埋め込む
    想定)。
    """

    expr: str
    warnings: list[str] = field(default_factory=list)


def render_pywinauto_chain(mapped_nodes: list[MappedNode]) -> RenderedSelector:
    """マッピング済みノード列から、pywinautoの検索呼び出し連鎖を組み立てる。

    最初のノードを`Desktop(backend="uia").window(**kwargs)`、以降の
    ノードを`.child_window(**kwargs)`として連結する。マッピング可能な
    属性が1つも無いノードは、その階層を検索条件として表現できない
    (でっち上げるよりは何も指定しない方が安全)ため呼び出し自体を省略し、
    その旨を警告として記録する。
    """
    expr = 'Desktop(backend="uia")'
    warnings: list[str] = []
    for i, mn in enumerate(mapped_nodes):
        if mn.unmapped:
            unmapped_str = ", ".join(f"{k}={v!r}" for k, v in mn.unmapped.items())
            warnings.append(
                f"node {i} ({mn.source_tag}): unmapped selector attributes ignored: "
                f"{unmapped_str}"
            )
        if not mn.kwargs:
            warnings.append(
                f"node {i} ({mn.source_tag}): no mappable attributes — this hierarchy "
                "level could not be represented in the search chain"
            )
            continue
        call = "window" if i == 0 else "child_window"
        kwargs_str = ", ".join(f"{k}={v!r}" for k, v in mn.kwargs.items())
        expr += f".{call}({kwargs_str})"
    return RenderedSelector(expr=expr, warnings=warnings)


def selector_text_to_pywinauto(selector_text: str) -> RenderedSelector:
    """セレクタ文字列から直接`RenderedSelector`を組み立てる便利関数
    (`parse_selector()`→`map_selector_nodes()`→`render_pywinauto_chain()`を
    1回で呼ぶ)。"""
    nodes = parse_selector(selector_text)
    mapped = map_selector_nodes(nodes)
    return render_pywinauto_chain(mapped)
