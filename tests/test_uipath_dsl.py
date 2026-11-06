"""uipath_dsl の単体テスト。

フィクスチャは design/evidence/uipath_xaml_probe/ に保存した、実機UiPath
Studio(2021.4.4)の `xaml_probe` プロジェクトから実際に書き出された
`Main.xaml`/`Sub1.xaml` そのもの(design/uipath_xaml_findings.md 知見1〜36参照)。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lxml import etree

from dump_daemon.uipath_dsl import (
    AppendLineNode,
    AssignNode,
    BreakNode,
    ClickNode,
    DoWhileNode,
    ExcelApplicationScopeNode,
    ExcelWriteCellNode,
    ForEachNode,
    HttpClientNode,
    IfNode,
    InvokeCodeNode,
    InvokeWorkflowFileNode,
    Literal,
    MessageBoxNode,
    ParallelNode,
    ReadTextFileNode,
    SendOutlookMailNode,
    SequenceNode,
    SetToClipboardNode,
    SwitchNode,
    TryCatchNode,
    TypeIntoNode,
    UnknownActivityNode,
    VbExpr,
    WhileNode,
    parse_activity,
    parse_workflow_file,
)

FIXTURE_DIR = Path(__file__).parent.parent / "design" / "evidence" / "uipath_xaml_probe"


@pytest.fixture(scope="module")
def main_wf():
    return parse_workflow_file(FIXTURE_DIR / "Main.xaml")


def test_class_name_and_top_level_sequence(main_wf):
    assert main_wf.class_name == "Main"
    assert isinstance(main_wf.root, SequenceNode)
    assert main_wf.root.variables[0].name == "content"
    assert main_wf.root.variables[0].type_arguments == "x:String"


def test_assign_with_vb_expr(main_wf):
    first = main_wf.root.body[0]
    assert isinstance(first, AssignNode)
    assert isinstance(first.target, VbExpr)
    assert first.target.text == "result"
    assert isinstance(first.value, VbExpr)
    assert "CStr(1 Mod 3)" in first.value.text


def test_message_box_with_literal_text(main_wf):
    mb = main_wf.root.body[1]
    assert isinstance(mb, MessageBoxNode)
    assert isinstance(mb.text, VbExpr)
    assert mb.text.text == '"Hello from pad2py"'


def test_assign_to_object_typed_var_stays_bracketed(main_wf):
    """`result`は`x:Object`型(知見13)のため、単純な文字列リテラル代入でも
    `[...]`角括弧形(VbExpr)のまま——`Literal`にはならない。"""
    assign_ok = main_wf.root.body[2]
    assert isinstance(assign_ok, AssignNode)
    assert isinstance(assign_ok.value, VbExpr)
    assert assign_ok.value.text == '"ok"'


def test_if_with_unknown_child_in_then(main_wf):
    if_node = main_wf.root.body[3]
    assert isinstance(if_node, IfNode)
    assert isinstance(if_node.condition, VbExpr)
    assert if_node.condition.text == 'result="ok"'
    assert len(if_node.then_body) == 1
    # HttpClient is Tier1-in-scope but appears here only to exercise the
    # "unknown nested inside known" path is not the point — it's handled.
    assert isinstance(if_node.then_body[0], HttpClientNode)
    assert if_node.else_body == []


def test_for_each(main_wf):
    for_each = main_wf.root.body[4]
    assert isinstance(for_each, ForEachNode)
    assert for_each.item_var == "item"
    assert isinstance(for_each.values, VbExpr)
    assert len(for_each.body) == 1
    assert isinstance(for_each.body[0], MessageBoxNode)
    assert for_each.body[0].text == VbExpr(text="item")


def test_try_catch(main_wf):
    try_catch = main_wf.root.body[5]
    assert isinstance(try_catch, TryCatchNode)
    assert try_catch.variables[0].name == "myVar"
    assert try_catch.variables[0].default == "init"
    assert len(try_catch.catches) == 1
    catch = try_catch.catches[0]
    assert catch.exception_type == "s:Exception"
    assert catch.var_name == "exception"
    assert catch.body == []


def test_variable_default_literal_child_element_form():
    """知見7が記録した`Variable.Default`の2つの直列化形のうち、本fixtureには
    実例が無かった`<Literal>`子要素形(公式ドキュメント上は確認済み)を
    合成XMLで確認する——属性形(`test_try_catch`のMain.xaml実例)とは別の
    直列化だが同じ`VariableDecl.default`文字列に正規化されることを検証する。
    """
    xml = (
        '<Sequence xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" DisplayName="Seq">'
        "<Sequence.Variables>"
        '<Variable x:TypeArguments="x:String" Name="myVar">'
        "<Variable.Default>"
        '<Literal x:TypeArguments="x:String">init</Literal>'
        "</Variable.Default>"
        "</Variable>"
        "</Sequence.Variables>"
        "</Sequence>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, SequenceNode)
    assert len(node.variables) == 1
    assert node.variables[0].name == "myVar"
    assert node.variables[0].type_arguments == "x:String"
    assert node.variables[0].default == "init"


def test_switch(main_wf):
    switch = main_wf.root.body[6]
    assert isinstance(switch, SwitchNode)
    assert switch.type_arguments == "x:Int32"
    assert isinstance(switch.expression, VbExpr)
    assert switch.expression.text == "result"
    assert len(switch.arms) == 1
    assert switch.arms[0].key == "1"
    assert isinstance(switch.arms[0].body[0], AssignNode)


def test_switch_default_arm_from_property_element():
    """知見40: `Switch`の`Default`アームは`x:Key`付き辞書エントリ(知見21)とは
    別の`<Switch.Default>`プロパティ要素として直列化される——実機
    (pad2py-pad-host VM)で確認した実例をそのまま合成XMLで再現する。
    修正前は`_activity_children()`がプロパティ要素を除外するため、この
    アームが無言で読み捨てられるバグがあった。"""
    xml = (
        '<Switch xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" '
        'x:TypeArguments="x:Int32" DisplayName="Switch" Expression="[result]">'
        "<Switch.Default>"
        '<Assign DisplayName="Assign">'
        "<Assign.To>"
        '<OutArgument x:TypeArguments="x:String">[content]</OutArgument>'
        "</Assign.To>"
        "<Assign.Value>"
        '<InArgument x:TypeArguments="x:String">defaultcase</InArgument>'
        "</Assign.Value>"
        "</Assign>"
        "</Switch.Default>"
        '<Assign x:Key="1" DisplayName="Assign">'
        "<Assign.To>"
        '<OutArgument x:TypeArguments="x:String">[content]</OutArgument>'
        "</Assign.To>"
        "<Assign.Value>"
        '<InArgument x:TypeArguments="x:String">case1</InArgument>'
        "</Assign.Value>"
        "</Assign>"
        "</Switch>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, SwitchNode)
    assert len(node.arms) == 2
    default_arm, case_arm = node.arms
    assert default_arm.key is None
    assert isinstance(default_arm.body[0], AssignNode)
    assert default_arm.body[0].value == Literal(value="defaultcase")
    assert case_arm.key == "1"
    assert isinstance(case_arm.body[0], AssignNode)
    assert case_arm.body[0].value == Literal(value="case1")


def test_click_selector(main_wf):
    click = main_wf.root.body[8]
    assert isinstance(click, ClickNode)
    assert click.selector is not None
    assert "notepad.exe" in click.selector
    assert "<ctrl name='Text Editor' role='editable text' />" in click.selector
    # 知見71: ClickType/MouseButton/KeyModifiersも実機XAMLの生テキストの
    # まま捕捉される(単純な左シングルクリック・修飾キー無しの実例)。
    assert click.click_type == "CLICK_SINGLE"
    assert click.mouse_button == "BTN_LEFT"
    assert click.key_modifiers == "None"
    # 知見73: `ui:Click.CursorPosition`配下の`Position`属性も捕捉される。
    assert click.cursor_position == "Center"


_UI_XMLNS = (
    'xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
    'xmlns:ui="http://schemas.uipath.com/workflow/activities" '
    'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"'
)


def test_type_into_selector_and_nullable_attrs():
    """知見110: `ui:TypeInto`。`UiPath/skills`公式リポジトリの実機保存済み
    XAML(Classicパッケージ用テストフィクスチャ)の属性構成をそのまま
    合成XMLで再現する——`ClickBeforeTyping`/`EmptyField`以外は全て
    `{x:Null}`(nullable、`None`に正規化される)。"""
    xml = (
        f"<ui:TypeInto {_UI_XMLNS} "
        'ActivateBefore="{x:Null}" AlterIfDisabled="{x:Null}" ContinueOnError="{x:Null}" '
        'DelayBefore="{x:Null}" DelayBetweenKeys="{x:Null}" DelayMS="{x:Null}" '
        'SendWindowMessages="{x:Null}" SimulateType="{x:Null}" ClickBeforeTyping="NONE" '
        'DisplayName="Type Into \'Account Number\'" EmptyField="False" Text="8891245">'
        "<ui:TypeInto.Target>"
        "<ui:Target Selector=\"&lt;wnd title='Vendor Master' /&gt;&lt;wnd ctrlid='txtAccountNumber' /&gt;\" />"
        "</ui:TypeInto.Target>"
        "</ui:TypeInto>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, TypeIntoNode)
    assert "txtAccountNumber" in node.selector
    assert node.text == Literal(value="8891245")
    assert node.empty_field == Literal(value="False")
    assert node.click_before_typing == Literal(value="NONE")
    assert node.activate_before is None
    assert node.alter_if_disabled is None
    assert node.continue_on_error is None
    assert node.delay_before is None
    assert node.delay_ms is None
    assert node.delay_between_keys is None
    assert node.send_window_messages is None
    assert node.simulate_type is None


def test_type_into_legacy_activate_attribute_name():
    """知見110: 古い(2017〜2021年頃の)サードパーティ実機XAMLでは
    `ActivateBefore`ではなく`Activate`という属性名で同じ意味の値が
    直列化されている(パッケージバージョン間のリネームと推定)。
    どちらの属性名でも`activate_before`フィールドに正規化される。"""
    xml = (
        f"<ui:TypeInto {_UI_XMLNS} "
        'Activate="False" ClickBeforeTyping="True" DisplayName="T" '
        'EmptyField="True" Text="hi">'
        "<ui:TypeInto.Target>"
        "<ui:Target Selector=\"&lt;wnd title='Notepad' /&gt;\" />"
        "</ui:TypeInto.Target>"
        "</ui:TypeInto>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, TypeIntoNode)
    assert node.activate_before == Literal(value="False")
    assert node.click_before_typing == Literal(value="True")
    assert node.empty_field == Literal(value="True")


def test_invoke_workflow_file(main_wf):
    invoke = main_wf.root.body[9]
    assert isinstance(invoke, InvokeWorkflowFileNode)
    assert invoke.workflow_file == "Sub1.xaml"
    assert invoke.arguments["in_text"] == Literal(value="hello")
    # 知見72: `ContinueOnError="{x:Null}"`(実機の確認済み実例)は未設定
    # (`None`)として捕捉される。
    assert invoke.continue_on_error is None


def test_while_and_do_while(main_wf):
    while_node = main_wf.root.body[10]
    assert isinstance(while_node, WhileNode)
    assert isinstance(while_node.condition, VbExpr)
    assert while_node.condition.text == 'result<>"x"'
    assert while_node.body == []

    do_while_node = main_wf.root.body[11]
    assert isinstance(do_while_node, DoWhileNode)
    assert do_while_node.condition is None  # Condition属性が省略されている実例
    assert do_while_node.body == []


def test_append_line_and_read_text_file(main_wf):
    append = main_wf.root.body[12]
    assert isinstance(append, AppendLineNode)
    assert append.file_name == Literal(value="out.txt")
    assert append.text == Literal(value="hello")

    read = main_wf.root.body[13]
    assert isinstance(read, ReadTextFileNode)
    assert read.content == VbExpr(text="content")


def test_invoke_code(main_wf):
    invoke_code = main_wf.root.body[14]
    assert isinstance(invoke_code, InvokeCodeNode)
    assert invoke_code.code == "content=content.ToUpper()"
    assert invoke_code.arguments["myArg"] == VbExpr(text="content")


def test_break_and_parallel(main_wf):
    assert isinstance(main_wf.root.body[15], BreakNode)
    parallel = main_wf.root.body[16]
    assert isinstance(parallel, ParallelNode)
    assert len(parallel.branches) == 1
    assert isinstance(parallel.branches[0], AssignNode)


def test_excel_application_scope(main_wf):
    scope = main_wf.root.body[17]
    assert isinstance(scope, ExcelApplicationScopeNode)
    assert scope.workbook_path == "wb.xlsx"
    assert scope.scope_var == "ExcelWorkbookScope"
    assert len(scope.body) == 1
    assert isinstance(scope.body[0], ExcelWriteCellNode)
    assert scope.body[0].cell == "A1"
    assert scope.body[0].sheet_name == "Sheet1"


def test_send_outlook_mail_and_set_to_clipboard(main_wf):
    mail = main_wf.root.body[18]
    assert isinstance(mail, SendOutlookMailNode)
    assert mail.to == Literal(value="a@b.com")
    assert mail.subject == Literal(value="hi")

    clip = main_wf.root.body[19]
    assert isinstance(clip, SetToClipboardNode)
    assert clip.text == Literal(value="cliptext")


def test_library_call_is_unknown_activity(main_wf):
    """Libraryはdesign/uipath_transpiler_roadmap.md Phase 1でv1スコープ外と
    決定済み——`p:NewActivity`(xaml_probe_libのLibrary呼び出し)は
    `UnknownActivityNode`として素通しされ、架空の変換はされないことを確認する。"""
    last = main_wf.root.body[-1]
    assert isinstance(last, UnknownActivityNode)
    assert last.tag.endswith("NewActivity")
    assert last.attrs.get("in_greeting") == "hellofromlib"


def test_http_client_extra_attrs_preserved(main_wf):
    if_node = main_wf.root.body[3]
    http = if_node.then_body[0]
    assert isinstance(http, HttpClientNode)
    assert http.method == "GET"
    assert isinstance(http.endpoint, Literal)
    assert "example.com" in http.endpoint.value
    # 主要属性(EndPoint/Method)以外も取りこぼしていないことを確認
    assert any(k.endswith("DisplayName") or k == "DisplayName" for k in http.extra_attrs)


def test_sub1_workflow_arguments():
    wf = parse_workflow_file(FIXTURE_DIR / "Sub1.xaml")
    assert wf.class_name == "Sub1"
    assert wf.arguments == {"in_text": "InArgument(x:String)"}
    assert isinstance(wf.root, SequenceNode)
    assign = wf.root.body[0]
    assert isinstance(assign, AssignNode)
    assert assign.target == VbExpr(text="in_text")
    assert assign.value == Literal(value="test2")
