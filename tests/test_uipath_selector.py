"""uipath_selector の単体テスト。

セレクタ文字列は design/uipath_xaml_findings.md 知見9で実機確認した
`ui:Click`の`Selector`属性の実例そのもの(でっち上げではない)。

`role`→`control_type`マッピングが実機(pad2py-pad-host VMの実Notepad)で
`KeyError`を起こすと確認された(知見38)ため、本モジュールは`role`を
意図的に未対応のままにしている——本テストもその挙動を前提にする。
"""
from __future__ import annotations

from dump_daemon.uipath_selector import (
    MappedNode,
    SelectorNode,
    map_selector_nodes,
    parse_selector,
    render_pywinauto_chain,
    selector_text_to_pywinauto,
)

# 知見9: ui:Clickの実例。
KNOWN_SELECTOR = (
    "<wnd app='notepad.exe' cls='Notepad' title='Untitled - Notepad' />"
    "<wnd aaname='Horizontal' cls='Edit' />"
    "<ctrl name='Text Editor' role='editable text' />"
)


def test_parse_selector_splits_into_nodes():
    nodes = parse_selector(KNOWN_SELECTOR)
    assert len(nodes) == 3
    assert nodes[0] == SelectorNode(
        tag="wnd",
        attrs={"app": "notepad.exe", "cls": "Notepad", "title": "Untitled - Notepad"},
    )
    assert nodes[1] == SelectorNode(tag="wnd", attrs={"aaname": "Horizontal", "cls": "Edit"})
    assert nodes[2] == SelectorNode(tag="ctrl", attrs={"name": "Text Editor", "role": "editable text"})


def test_map_selector_nodes_separates_mapped_and_unmapped():
    nodes = parse_selector(KNOWN_SELECTOR)
    mapped = map_selector_nodes(nodes)
    assert mapped[0].kwargs == {"class_name": "Notepad", "title": "Untitled - Notepad"}
    assert mapped[0].unmapped == {"app": "notepad.exe"}
    assert mapped[1].kwargs == {"class_name": "Edit"}
    assert mapped[1].unmapped == {"aaname": "Horizontal"}
    # roleは知見38で実機KeyErrorが確認されたため意図的に未対応(unmapped)
    assert mapped[2].kwargs == {"title": "Text Editor"}
    assert mapped[2].unmapped == {"role": "editable text"}


def test_render_pywinauto_chain_builds_expected_call_chain():
    """知見38: このチェーン(role/control_typeを含まない)は実機
    pad2py-pad-host VMの実Notepadで実際に対象要素を一意特定できることを
    確認済み。"""
    result = selector_text_to_pywinauto(KNOWN_SELECTOR)
    assert result.expr == (
        'Desktop(backend="uia")'
        ".window(class_name='Notepad', title='Untitled - Notepad')"
        ".child_window(class_name='Edit')"
        ".child_window(title='Text Editor')"
    )
    # unmapped属性(app/aaname/role)が無言で捨てられず警告として残っていること
    assert any("app" in w for w in result.warnings)
    assert any("aaname" in w for w in result.warnings)
    assert any("role" in w for w in result.warnings)


def test_node_with_no_mappable_attrs_is_skipped_not_fabricated():
    """知見37でマッピングが未確定の属性(例: `idx`)しか無いノードは、
    でっち上げたkwargsを出力せず、呼び出し自体を省略して警告に回す。"""
    mapped = [MappedNode(kwargs={}, unmapped={"idx": "2"}, source_tag="wnd")]
    result = render_pywinauto_chain(mapped)
    assert result.expr == 'Desktop(backend="uia")'
    assert any("no mappable attributes" in w for w in result.warnings)


def test_empty_selector_list_returns_bare_desktop():
    result = render_pywinauto_chain([])
    assert result.expr == 'Desktop(backend="uia")'
    assert result.warnings == []
