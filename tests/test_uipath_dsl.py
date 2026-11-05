"""uipath_dsl の単体テスト。

フィクスチャは design/evidence/uipath_xaml_probe/ に保存した、実機UiPath
Studio(2021.4.4)の `xaml_probe` プロジェクトから実際に書き出された
`Main.xaml`/`Sub1.xaml` そのもの(design/uipath_xaml_findings.md 知見1〜36参照)。
"""
from __future__ import annotations

from pathlib import Path

import pytest

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
    UnknownActivityNode,
    VbExpr,
    WhileNode,
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


def test_switch(main_wf):
    switch = main_wf.root.body[6]
    assert isinstance(switch, SwitchNode)
    assert switch.type_arguments == "x:Int32"
    assert isinstance(switch.expression, VbExpr)
    assert switch.expression.text == "result"
    assert len(switch.arms) == 1
    assert switch.arms[0].key == "1"
    assert isinstance(switch.arms[0].body[0], AssignNode)


def test_click_selector(main_wf):
    click = main_wf.root.body[8]
    assert isinstance(click, ClickNode)
    assert click.selector is not None
    assert "notepad.exe" in click.selector
    assert "<ctrl name='Text Editor' role='editable text' />" in click.selector


def test_invoke_workflow_file(main_wf):
    invoke = main_wf.root.body[9]
    assert isinstance(invoke, InvokeWorkflowFileNode)
    assert invoke.workflow_file == "Sub1.xaml"
    assert invoke.arguments["in_text"] == Literal(value="hello")


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
