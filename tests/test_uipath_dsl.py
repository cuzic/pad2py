"""uipath_dsl の単体テスト。

フィクスチャは design/evidence/uipath_xaml_probe/ に保存した、実機UiPath
Studio(2021.4.4)の `xaml_probe` プロジェクトから実際に書き出された
`Main.xaml`/`Sub1.xaml` そのもの(design/uipath_xaml_findings.md 知見1〜36参照)。
"""
from __future__ import annotations

import html
from pathlib import Path

import pytest

from lxml import etree

from dump_daemon.uipath_dsl import (
    ActivateNode,
    AppendLineNode,
    AssignNode,
    AttachWindowNode,
    BreakNode,
    BuildDataTableNode,
    CheckNode,
    ClickNode,
    CloseTabNode,
    CommentNode,
    CopyFileNode,
    DatabaseConnectNode,
    DatabaseDisconnectNode,
    DelayNode,
    DoWhileNode,
    ExcelApplicationScopeNode,
    ExcelAppendRangeNode,
    ExcelReadCellNode,
    ExcelReadRangeNode,
    ExcelWriteCellNode,
    ExcelWriteRangeNode,
    ExecuteNonQueryNode,
    ExecuteQueryNode,
    ForEachNode,
    GetOutlookMailMessagesNode,
    GetTextNode,
    HighlightNode,
    HoverNode,
    HttpClientNode,
    IfNode,
    InputDialogNode,
    InvokeCodeNode,
    InvokeWorkflowFileNode,
    KillProcessNode,
    Literal,
    LogMessageNode,
    MessageBoxNode,
    MultipleAssignNode,
    OpenApplicationNode,
    OpenBrowserNode,
    ParallelNode,
    ReadTextFileNode,
    RethrowNode,
    SelectItemNode,
    SendHotkeyNode,
    SendMailNode,
    SendOutlookMailNode,
    SequenceNode,
    SetToClipboardNode,
    SwitchNode,
    TerminateWorkflowNode,
    ThrowNode,
    TryCatchNode,
    TypeIntoNode,
    UiElementExistsNode,
    UnknownActivityNode,
    VbExpr,
    WhileNode,
    WordApplicationScopeNode,
    WordReplaceTextNode,
    WriteLineNode,
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


def test_for_each_row():
    """知見118: `ui:ForEachRow`(`UiPath.System.Activities`、
    `HarshadRanganathan/uipath-learning`の実機XAMLで発見)。`ui:ForEach`
    (知見5)と直接の子要素構造が同じで、反復対象の属性名のみ`DataTable`
    に変わる——既存の`ForEachNode`をそのまま再利用する(新しいノード型は
    追加しない)。"""
    xml = (
        f"<ui:ForEachRow {_UI_XMLNS} "
        'DataTable="[dt]" DisplayName="For each row">'
        "<ui:ForEachRow.Body>"
        '<ActivityAction x:TypeArguments="sd:DataRow">'
        "<ActivityAction.Argument>"
        '<DelegateInArgument x:TypeArguments="sd:DataRow" Name="row" />'
        "</ActivityAction.Argument>"
        '<Sequence DisplayName="Body">'
        '<ui:SetToClipboard Text="[row]" />'
        "</Sequence>"
        "</ActivityAction>"
        "</ui:ForEachRow.Body>"
        "</ui:ForEachRow>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ForEachNode)
    assert node.item_var == "row"
    assert node.values == VbExpr(text="dt")
    assert len(node.body) == 1


def test_base_wf_for_each_implicit_body_content_property():
    """知見155: 基本WF版`System.Activities.Statements.ForEach<T>`
    (`ui:`プレフィックス無し、`WF_NS`)——UiPathプログラマがVB式ベースの
    ループを書く際に`ui:ForEach`ではなく直接使う実例を実機確認した
    (`plaah/web-application-with-rpa-dhl`等5件)。`Body`はContent
    Propertyのため、`<ForEach.Body>`ラッパー無しで`ActivityAction`が
    直接の子として置かれる暗黙形が実機で最も多かった。"""
    xml = (
        f"<ForEach {_UI_XMLNS} "
        'x:TypeArguments="x:String" DisplayName="For each file" '
        'Values="[Directory.GetFiles(folder)]">'
        '<ActivityAction x:TypeArguments="x:String">'
        "<ActivityAction.Argument>"
        '<DelegateInArgument x:TypeArguments="x:String" Name="filePath" />'
        "</ActivityAction.Argument>"
        '<Sequence DisplayName="Body">'
        '<WriteLine Text="[filePath]" />'
        "</Sequence>"
        "</ActivityAction>"
        "</ForEach>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ForEachNode)
    assert node.item_var == "filePath"
    assert node.values == VbExpr(text="Directory.GetFiles(folder)")
    assert len(node.body) == 1
    assert isinstance(node.body[0], WriteLineNode)


def test_base_wf_for_each_explicit_body_wrapper():
    """知見155: 基本WF版`ForEach<T>`で`.Body`を明示的にラップする形
    (`R1zzabh/signalforge`の実機XAMLで確認済み)も同じ`ForEachNode`へ
    変換される。"""
    xml = (
        f"<ForEach {_UI_XMLNS} "
        'x:TypeArguments="x:String" Values="[incidentIds]" '
        'DisplayName="Process each incident">'
        "<ForEach.Body>"
        '<ActivityAction x:TypeArguments="x:String">'
        "<ActivityAction.Argument>"
        '<DelegateInArgument x:TypeArguments="x:String" Name="incidentId" />'
        "</ActivityAction.Argument>"
        '<Sequence DisplayName="Body">'
        '<WriteLine Text="[incidentId]" />'
        "</Sequence>"
        "</ActivityAction>"
        "</ForEach.Body>"
        "</ForEach>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ForEachNode)
    assert node.item_var == "incidentId"
    assert node.values == VbExpr(text="incidentIds")
    assert len(node.body) == 1


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


def test_type_secure_text_reuses_type_into_node():
    """知見158: `ui:TypeSecureText`(GitHub code searchで544件ヒット
    ——`piyushagarwal08/JU-Notes`等の実機XAMLで確認)。`ui:TypeInto`
    (知見110)と属性構成が全く同じで、入力文字列の属性名のみ`Text`
    ではなく`SecureText`——意味論・コード生成が完全に同じため、
    新しいノード型を追加せず既存の`TypeIntoNode`をそのまま再利用する。"""
    xml = (
        f"<ui:TypeSecureText {_UI_XMLNS} "
        'Activate="True" DisplayName="Type Secure Text password" '
        'SecureText="[Password]">'
        "<ui:TypeSecureText.Target>"
        "<ui:Target Selector=\"&lt;ctrl automationid='pass' /&gt;\" />"
        "</ui:TypeSecureText.Target>"
        "</ui:TypeSecureText>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, TypeIntoNode)
    assert "automationid='pass'" in node.selector
    assert node.text == VbExpr(text="Password")
    assert node.activate_before == Literal(value="True")
    assert node.display_name == "Type Secure Text password"


def test_get_text_selector_and_output_binding():
    """知見111: `ui:GetText`。`UiPath/skills`公式リポジトリの実機保存済み
    XAMLの属性構成をそのまま合成XMLで再現する——`ContinueOnError`/
    `DelayMS`は`{x:Null}`(nullable)、`Text`は出力先の`VbExpr`。"""
    xml = (
        f"<ui:GetText {_UI_XMLNS} "
        'ContinueOnError="{x:Null}" DelayBefore="{x:Null}" DelayMS="{x:Null}" '
        'DisplayName="Get Text \'balance\'" Text="[balanceText]">'
        "<ui:GetText.Target>"
        "<ui:Target Selector=\"&lt;webctrl aaname='Current balance' tag='SPAN' /&gt;\" />"
        "</ui:GetText.Target>"
        "</ui:GetText>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, GetTextNode)
    assert "Current balance" in node.selector
    assert node.text == VbExpr(text="balanceText")
    assert node.delay_before is None
    assert node.delay_ms is None
    assert node.continue_on_error is None


def test_get_full_text_reuses_get_text_node():
    """知見159: `ui:GetFullText`(`GetText`とは別の活動、GitHub code
    searchで300件ヒット)。`Target`構造は同じだが、出力`Text`は属性形
    ではなくプロパティ要素形(`<ui:GetFullText.Text><OutArgument>...
    </OutArgument></ui:GetFullText.Text>`)で直列化される——同じ
    `GetTextNode`を`full_text=True`で返す。"""
    xml = (
        f"<ui:GetFullText {_UI_XMLNS} "
        'DisplayName="Get Full Text \'editable text\'" IgnoreHidden="False">'
        "<ui:GetFullText.Target>"
        "<ui:Target Selector=\"&lt;wnd title='Notepad' /&gt;\" />"
        "</ui:GetFullText.Target>"
        "<ui:GetFullText.Text>"
        '<OutArgument x:TypeArguments="ui:GenericValue">[txt]</OutArgument>'
        "</ui:GetFullText.Text>"
        "</ui:GetFullText>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, GetTextNode)
    assert node.full_text is True
    assert "Notepad" in node.selector
    assert node.text == VbExpr(text="txt")
    assert node.ignore_hidden == Literal(value="False")
    assert node.display_name == "Get Full Text 'editable text'"


def test_get_value_reuses_get_text_node():
    """知見167: `ui:GetValue`(`ui:GetText`の裏のCLR型名そのものがタグ名
    として直列化される実例、GitHub code searchで1262件ヒット)。
    `DisplayName`は常に`"Get Text '...'"`になり(`HarshadRanganathan/
    uipath-learning`等の実機XAMLで確認)、意味論が`GetText`そのものの
    ため`full_text=False`(既定)のまま同じ`GetTextNode`を返す——
    `GetFullText`とは出力プロパティ名(`Value`、`Text`ではない)のみ
    異なる。"""
    xml = (
        f"<ui:GetValue {_UI_XMLNS} "
        'DisplayName="Get Text \'text  6/6/2016\'" ContinueOnError="{x:Null}">'
        "<ui:GetValue.Target>"
        "<ui:Target Selector=\"&lt;ctrl role='text' /&gt;\" />"
        "</ui:GetValue.Target>"
        "<ui:GetValue.Value>"
        '<OutArgument x:TypeArguments="ui:GenericValue">[inv_date]</OutArgument>'
        "</ui:GetValue.Value>"
        "</ui:GetValue>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, GetTextNode)
    assert node.full_text is False
    assert "role='text'" in node.selector
    assert node.text == VbExpr(text="inv_date")
    assert node.continue_on_error is None
    assert node.display_name == "Get Text 'text  6/6/2016'"


def test_select_item_selector_and_alter_if_disabled():
    """知見112: `ui:SelectItem`。`UiPath/skills`公式リポジトリの実機保存済み
    XAMLの属性構成をそのまま合成XMLで再現する——`ContinueOnError`/
    `DelayAfter`/`DelayBefore`/`Items`は`{x:Null}`(nullable)、
    `AlterIfDisabled`は公式ドキュメントで確認済みの既定(`True`相当)が
    明示的な実例として現れる。design-time snapshotの`Items`子要素は
    捕捉しない(実行時には使われないため)。"""
    xml = (
        f"<ui:SelectItem {_UI_XMLNS} xmlns:scg=\"clr-namespace:System.Collections.Generic;assembly=System\" "
        'ContinueOnError="{x:Null}" DelayAfter="{x:Null}" DelayBefore="{x:Null}" '
        'Items="{x:Null}" AlterIfDisabled="True" DisplayName="Select Benefits Plan" '
        'Item="[BenefitPlan]">'
        "<ui:SelectItem.Target>"
        "<ui:Target Selector=\"&lt;webctrl id='benefitPlanDropdown' tag='SELECT' /&gt;\" />"
        "</ui:SelectItem.Target>"
        "</ui:SelectItem>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, SelectItemNode)
    assert "benefitPlanDropdown" in node.selector
    assert node.item == VbExpr(text="BenefitPlan")
    assert node.alter_if_disabled == Literal(value="True")
    assert node.delay_before is None
    assert node.delay_after is None
    assert node.continue_on_error is None


def test_ui_element_exists_selector_and_output_binding():
    """知見113: `ui:UiElementExists`(DisplayNameは「Element Exists」)。
    実機確認済みの実タグ名は`ui:ElementExists`ではなく`ui:UiElementExists`
    (公式ドキュメントの裏のCLR型名`UiPath.Core.Activities.
    UiElementExists`とも一致)。"""
    xml = (
        f"<ui:UiElementExists {_UI_XMLNS} "
        'DisplayName="Element Exists" Exists="[notepadOpened]">'
        "<ui:UiElementExists.Target>"
        "<ui:Target Selector=\"&lt;wnd title='Notepad' /&gt;\" />"
        "</ui:UiElementExists.Target>"
        "</ui:UiElementExists>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, UiElementExistsNode)
    assert "Notepad" in node.selector
    assert node.exists == VbExpr(text="notepadOpened")


def test_database_connect_and_disconnect():
    """知見114: `ui:DatabaseConnect`/`ui:DatabaseDisconnect`。
    `allenlooplee/RPABook`の実機保存済みXAMLの属性構成を合成XMLで再現する。"""
    connect_xml = (
        f"<ui:DatabaseConnect {_UI_XMLNS} "
        'DatabaseConnection="[PostDbConnection]" DisplayName="Connect" '
        'ProviderName="System.Data.SQLite" '
        'ConnectionString="Data Source=db.sqlite;Version=3;" />'
    )
    connect = parse_activity(etree.fromstring(connect_xml))
    assert isinstance(connect, DatabaseConnectNode)
    assert connect.database_connection == VbExpr(text="PostDbConnection")
    assert connect.provider_name == Literal(value="System.Data.SQLite")
    assert connect.connection_string == Literal(value="Data Source=db.sqlite;Version=3;")
    assert connect.secure_connection_string is None

    disconnect_xml = (
        f"<ui:DatabaseDisconnect {_UI_XMLNS} "
        'DatabaseConnection="[PostDbConnection]" DisplayName="Disconnect" />'
    )
    disconnect = parse_activity(etree.fromstring(disconnect_xml))
    assert isinstance(disconnect, DatabaseDisconnectNode)
    assert disconnect.database_connection == VbExpr(text="PostDbConnection")


def test_execute_query_and_execute_non_query():
    """知見114: `ui:ExecuteQuery`/`ui:ExecuteNonQuery`。空の`Parameters`
    辞書(`_xkey_dict_entries`経由)も合わせて確認する。"""
    query_xml = (
        f"<ui:ExecuteQuery {_UI_XMLNS} "
        'xmlns:scg="clr-namespace:System.Collections.Generic;assembly=System" '
        'ContinueOnError="{x:Null}" TimeoutMS="{x:Null}" CommandType="Text" '
        'DataTable="[PostTable]" DisplayName="Execute Query" '
        'ExistingDbConnection="[PostDbConnection]" Sql="SELECT * FROM post">'
        "<ui:ExecuteQuery.Parameters>"
        '<scg:Dictionary x:TypeArguments="x:String, Argument" />'
        "</ui:ExecuteQuery.Parameters>"
        "</ui:ExecuteQuery>"
    )
    query = parse_activity(etree.fromstring(query_xml))
    assert isinstance(query, ExecuteQueryNode)
    assert query.sql == Literal(value="SELECT * FROM post")
    assert query.existing_db_connection == VbExpr(text="PostDbConnection")
    assert query.data_table == VbExpr(text="PostTable")
    assert query.command_type == "Text"
    assert query.parameters == {}
    assert query.continue_on_error is None
    assert query.timeout_ms is None

    non_query_xml = (
        f"<ui:ExecuteNonQuery {_UI_XMLNS} "
        'xmlns:scg="clr-namespace:System.Collections.Generic;assembly=System" '
        'ContinueOnError="{x:Null}" TimeoutMS="{x:Null}" CommandType="Text" '
        'AffectedRecords="[rows]" DisplayName="Execute Non Query" '
        'ExistingDbConnection="[PostDbConnection]" Sql="DELETE FROM post WHERE id=1">'
        "<ui:ExecuteNonQuery.Parameters>"
        '<scg:Dictionary x:TypeArguments="x:String, Argument" />'
        "</ui:ExecuteNonQuery.Parameters>"
        "</ui:ExecuteNonQuery>"
    )
    non_query = parse_activity(etree.fromstring(non_query_xml))
    assert isinstance(non_query, ExecuteNonQueryNode)
    assert non_query.sql == Literal(value="DELETE FROM post WHERE id=1")
    assert non_query.affected_records == VbExpr(text="rows")
    assert non_query.command_type == "Text"
    assert non_query.parameters == {}


def test_excel_read_range_and_write_range():
    """知見115: `ui:ExcelReadRange`/`ui:ExcelWriteRange`。`Range`の
    ネスト`InArgument`+`Literal`形(`HarshadRanganathan/uipath-learning`の
    実例)、`StartingCell`の属性直書き形(`allenlooplee/RPABook`の実例)を
    合成XMLで再現する。"""
    read_xml = (
        f"<ui:ExcelReadRange {_UI_XMLNS} "
        'AddHeaders="False" DataTable="[dt]" DisplayName="Read Range" '
        'SheetName="Sheet1">'
        "<ui:ExcelReadRange.Range>"
        '<InArgument x:TypeArguments="x:String">'
        '<Literal x:TypeArguments="x:String" Value="" />'
        "</InArgument>"
        "</ui:ExcelReadRange.Range>"
        "</ui:ExcelReadRange>"
    )
    read_node = parse_activity(etree.fromstring(read_xml))
    assert isinstance(read_node, ExcelReadRangeNode)
    assert read_node.sheet_name == "Sheet1"
    assert read_node.range == Literal(value="")
    assert read_node.add_headers == "False"
    assert read_node.data_table == VbExpr(text="dt")

    write_xml = (
        f"<ui:ExcelWriteRange {_UI_XMLNS} "
        'AddHeaders="True" DataTable="[uploadTable]" DisplayName="Write Range" '
        'SheetName="Sheet2" StartingCell="A1" />'
    )
    write_node = parse_activity(etree.fromstring(write_xml))
    assert isinstance(write_node, ExcelWriteRangeNode)
    assert write_node.sheet_name == "Sheet2"
    assert write_node.starting_cell == "A1"
    assert write_node.add_headers == "True"
    assert write_node.data_table == VbExpr(text="uploadTable")


def test_excel_append_range_properties():
    """知見117: `ui:ExcelAppendRange`。`allenlooplee/RPABook`の実機保存済み
    XAMLの属性構成をそのまま合成XMLで再現する——`AddHeaders`/
    `StartingCell`は無い(確認済み)。"""
    xml = (
        f"<ui:ExcelAppendRange {_UI_XMLNS} "
        'DataTable="[checklogTable]" DisplayName="Append Range" SheetName="Sheet1" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ExcelAppendRangeNode)
    assert node.sheet_name == "Sheet1"
    assert node.data_table == VbExpr(text="checklogTable")
    assert node.display_name == "Append Range"


def test_excel_write_cell_with_dynamic_cell_expression():
    """知見119: `Cell`は`PacktPublishing/
    Robotic-Process-Automation-Projects`の実機XAMLで動的な実例
    (`Cell="[&quot;B&quot;+intCounter.ToString]"`)を発見し`Expr`へ昇格
    した。"""
    xml = (
        f"<ui:ExcelWriteCell {_UI_XMLNS} "
        'Cell="[&quot;B&quot;+intCounter.ToString]" DisplayName="Write Cell" '
        'SheetName="Sheet1" Text="[strAdult]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ExcelWriteCellNode)
    assert node.cell == VbExpr(text='"B"+intCounter.ToString')
    assert node.sheet_name == "Sheet1"
    assert node.text == VbExpr(text="strAdult")
    # 知見135: `DisplayName`は当初捕捉されていなかった。
    assert node.display_name == "Write Cell"


def test_excel_read_cell_properties():
    """知見119: `ui:ExcelReadCell`(`ExcelWriteCellNode`と対になる読み取り
    側)。`.Result`はネストした`OutArgument`要素形
    (`_in_argument_property_expr`、知見115で確立した共通パーサーを
    `InArgument`以外のタグ名でも再利用できることを確認)。"""
    xml = (
        f"<ui:ExcelReadCell {_UI_XMLNS} "
        'Cell="[&quot;A&quot;+intCounter.ToString]" DisplayName="Read Cell" '
        'SheetName="Sheet1">'
        "<ui:ExcelReadCell.Result>"
        '<OutArgument x:TypeArguments="x:String">[strImagePath]</OutArgument>'
        "</ui:ExcelReadCell.Result>"
        "</ui:ExcelReadCell>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ExcelReadCellNode)
    assert node.cell == VbExpr(text='"A"+intCounter.ToString')
    assert node.sheet_name == "Sheet1"
    assert node.result == VbExpr(text="strImagePath")
    assert node.display_name == "Read Cell"


def test_comment_properties():
    """知見119: `ui:Comment`(`PacktPublishing/
    Robotic-Process-Automation-Projects`の実機XAMLで発見)。`Text`は常に
    生のリテラル文字列(VbExprでは無い)。"""
    xml = f'<ui:Comment {_UI_XMLNS} Text="// Attach a browser" />'
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, CommentNode)
    assert node.text == "// Attach a browser"


def test_write_line_properties():
    """知見147: `WriteLine`(.NET Workflow Foundation本体の標準活動、
    `WF_NS`——UiPath独自ではないため`ui:`接頭辞が無い)。`RealBenTen10/
    Handle-Order`等、実機検証を通じて非常に高頻度で「unknown activity」
    として素通りしていたことが判明——基本的な活動にも関わらず長らく
    未実装だった。"""
    xml = f'<WriteLine {_UI_XMLNS} DisplayName="Print it" Text="[&quot;hi&quot;]" />'
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, WriteLineNode)
    assert node.text == VbExpr(text='"hi"')
    assert node.display_name == "Print it"


def test_throw_properties():
    """知見148: `Throw`(.NET Workflow Foundation本体の標準活動、
    `WriteLine`と同じ`WF_NS`)。`Exception`属性は実機で`[New Exception(
    "message")]`という、知見148で新規対応した`New ClassName(arg)`構文が
    使われていた(`Manyakarthik/210701152-CS19P21-ARPA`)。"""
    xml = (
        f"<Throw {_UI_XMLNS} DisplayName=\"Boom\" "
        'Exception="[New Exception(&quot;boom&quot;)]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ThrowNode)
    assert node.exception == VbExpr(text='New Exception("boom")')
    assert node.display_name == "Boom"


def test_rethrow_properties():
    """知見149: `Rethrow`(.NET Workflow Foundation本体の標準活動、
    `Throw`の対になる属性無しのリーフ活動)。`Catch`ブロック内で現在
    捕捉中の例外を再発生させる定石パターン。"""
    xml = f'<Rethrow {_UI_XMLNS} DisplayName="Re-raise" />'
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, RethrowNode)
    assert node.display_name == "Re-raise"


def test_terminate_workflow_properties():
    """知見150: `TerminateWorkflow`(.NET Workflow Foundation本体の標準
    活動、`Throw`・`Rethrow`と対になる、ワークフロー全体を即座に停止する
    活動)。実機で確認した`Reason`属性(`Siva-PythonPirates/CS19P21-ARPA`
    等)に加え、`Exception`属性も同時に持つ実例(`jyjang1222/
    learning-uipath`)も確認済み——両方をパーサーで保持する。"""
    xml = (
        f"<TerminateWorkflow {_UI_XMLNS} DisplayName=\"Stop\" "
        'Reason="[&quot;fatal&quot;]" Exception="[exception]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, TerminateWorkflowNode)
    assert node.reason == VbExpr(text='"fatal"')
    assert node.exception == VbExpr(text="exception")
    assert node.display_name == "Stop"


def test_delay_properties():
    """知見151: `ui:Delay`(UiPath独自の待機活動——GitHub code searchで
    10000件超ヒットする最頻出活動の1つ)。`Duration`属性は実機確認した
    全件(`AI-Dep/AI-Antigravity`・`UiPath/skills`)で`[...]`角括弧の無い
    生の.NET TimeSpanリテラル(`"00:00:01"`等)だった。"""
    xml = f'<ui:Delay {_UI_XMLNS} DisplayName="Wait" Duration="00:00:00.500" />'
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, DelayNode)
    assert node.duration == Literal(value="00:00:00.500")
    assert node.display_name == "Wait"


def test_send_hotkey_properties():
    """知見152: `ui:SendHotkey`(GitHub code searchで1936件ヒットする
    `Click`/`TypeInto`と同じ基本UI Automation活動)。`KeyModifiers`は
    `.NET`の`[Flags]`列挙型のToString()直列化形式(`", "`区切り、
    `cameronmcnz/uipath-tutorials`の実機XAMLで`"Ctrl, Shift"`を確認)。"""
    xml = (
        f"<ui:SendHotkey {_UI_XMLNS} DisplayName=\"Save\" "
        'Key="s" KeyModifiers="Ctrl">'
        "<ui:SendHotkey.Target>"
        "<ui:Target Selector=\"&lt;wnd title='Notepad' /&gt;\" />"
        "</ui:SendHotkey.Target>"
        "</ui:SendHotkey>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, SendHotkeyNode)
    assert "Notepad" in node.selector
    assert node.key == Literal(value="s")
    assert node.key_modifiers == Literal(value="Ctrl")
    assert node.display_name == "Save"


def test_send_hotkey_with_no_target_has_none_selector():
    """知見152: `AI-Dep/AI-Antigravity`の実機XAMLで、`ui:SendHotkey.Target`
    自体が省略された自己終了タグ(`<ui:SendHotkey Key="esc" ... />`)を
    確認済み——現在フォーカス中のウィンドウへグローバルに送信する意味論
    と推定されるが、本パーサーでは`selector=None`として保持するのみ
    (コード生成側で`# TODO`へ倒す、未対応)。"""
    xml = f'<ui:SendHotkey {_UI_XMLNS} Key="esc" DisplayName="Close" />'
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, SendHotkeyNode)
    assert node.selector is None
    assert node.key == Literal(value="esc")


def test_hover_selector_and_cursor_position():
    """知見157: `ui:Hover`(GitHub code searchで151件ヒット)。`Click`
    (知見9)と`Target`/`CursorPosition`の構造が全く同じ(`sujan5757/
    RPAWorks`の実機XAMLで確認)——`ClickType`/`MouseButton`/
    `KeyModifiers`が無い点のみ異なる。"""
    xml = (
        f"<ui:Hover {_UI_XMLNS} DisplayName=\"Hover link\">"
        "<ui:Hover.Target>"
        "<ui:Target Selector=\"&lt;wnd app='notepad.exe' /&gt;\" />"
        "</ui:Hover.Target>"
        "<ui:Hover.CursorPosition>"
        '<ui:CursorPosition Position="Center" />'
        "</ui:Hover.CursorPosition>"
        "</ui:Hover>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, HoverNode)
    assert "notepad.exe" in node.selector
    assert node.cursor_position == "Center"
    assert node.display_name == "Hover link"


def test_activate_selector_and_properties():
    """知見162: `ui:Activate`(GitHub code searchで604件ヒット)。
    `UiPath/skills`公式リポジトリのStudio実機ground-truthコーパス+
    `Digital-RPA/MRE_B2BE`等の実機XAMLで確認した構造は`Target`+
    `DelayBefore`/`DelayMS`/`ContinueOnError`のみ——`Click`/`Hover`
    より単純で`CursorPosition`自体を持たない。"""
    xml = (
        f"<ui:Activate {_UI_XMLNS} DisplayName=\"Activate 'chrome.exe'\">"
        "<ui:Activate.Target>"
        "<ui:Target Selector=\"&lt;wnd app='chrome.exe' /&gt;\" />"
        "</ui:Activate.Target>"
        "</ui:Activate>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ActivateNode)
    assert "chrome.exe" in node.selector
    assert node.display_name == "Activate 'chrome.exe'"
    assert node.delay_before is None
    assert node.delay_ms is None
    assert node.continue_on_error is None


def test_target_selector_normalizes_x_null_to_none():
    """知見163: `_target_selector`(`Click`/`Hover`/`Activate`/`TypeInto`/
    `TypeSecureText`/`SendHotkey`/`GetText`/`GetFullText`/`SelectItem`/
    `UiElementExists`の10箇所で重複していたインライン実装を統合した
    共通ヘルパー)。`UiPath/skills`公式リポジトリのStudio実機
    ground-truthコーパス(`Activate.xaml`)で発見した`Selector=
    "{x:Null}"`(未設定)という実例——修正前は文字列`"{x:Null}"`が
    そのまま`selector`に残り、`if not node.selector:`判定を素通りして
    `# TODO: ... had no mappable attributes: {x:Null}`という紛らわしい
    文言になっていた。知見13の`{x:Null}`→`None`正規化規約に揃えた。"""
    xml = (
        f"<ui:Activate {_UI_XMLNS} DisplayName=\"Activate\">"
        "<ui:Activate.Target>"
        '<ui:Target Selector="{x:Null}" />'
        "</ui:Activate.Target>"
        "</ui:Activate>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ActivateNode)
    assert node.selector is None


def test_set_focus_reuses_activate_node():
    """知見164: `ui:SetFocus`(GitHub code searchで68件ヒット)は
    `DisplayName`が`"Set Focus '...'"`になる`Activate`の同義の別活動
    (`JoeIaquinto/UiPath-VidCreator`等の実機XAMLで確認)——属性構成が
    完全に同一(`Target`+`DelayBefore`/`DelayMS`/`ContinueOnError`)
    なため同じ`ActivateNode`を返す。"""
    xml = (
        f"<ui:SetFocus {_UI_XMLNS} DisplayName=\"Set Focus 'obs64.exe OBS'\">"
        "<ui:SetFocus.Target>"
        "<ui:Target Selector=\"&lt;wnd app='obs64.exe' /&gt;\" />"
        "</ui:SetFocus.Target>"
        "</ui:SetFocus>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ActivateNode)
    assert "obs64.exe" in node.selector
    assert node.display_name == "Set Focus 'obs64.exe OBS'"


def test_check_selector_and_action():
    """知見165: `ui:Check`(チェックボックス操作、GitHub code searchで
    805件ヒット)。実機(`PacktPublishing/Robotic-Process-Automation-
    RPA-for-Developers`・`miyaichi/UiLession`)で確認した`Action`は
    `"Check"`/`"Uncheck"`の2種、`Target`+`ContinueOnError`/
    `DelayAfter`/`DelayBefore`。"""
    xml = (
        f"<ui:Check {_UI_XMLNS} Action=\"Uncheck\" DisplayName=\"Check 'INPUT'\">"
        "<ui:Check.Target>"
        "<ui:Target Selector=\"&lt;webctrl name='lname' tag='INPUT' type='checkbox' /&gt;\" />"
        "</ui:Check.Target>"
        "</ui:Check>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, CheckNode)
    assert "checkbox" in node.selector
    assert node.action == "Uncheck"
    assert node.display_name == "Check 'INPUT'"
    assert node.delay_before is None
    assert node.delay_after is None
    assert node.continue_on_error is None


def test_highlight_selector_color_and_time():
    """知見166: `ui:Highlight`(要素の視覚的ハイライト、GitHub code
    searchで289件ヒット)。実機(`PacktPublishing/Robotic-Process-
    Automation-RPA-for-Developers`・`SuneetPatil/IRCTC-tatkal-booking`)
    で確認した属性は`Color`(`"Blue"`/`"Gold"`等)・`HighlightTime`
    (ミリ秒)+`Target`のみ——出力を一切持たない。"""
    xml = (
        f"<ui:Highlight {_UI_XMLNS} Color=\"Gold\" HighlightTime=\"1000\" "
        'DisplayName="Highlight \'TEXTAREA\'">'
        "<ui:Highlight.Target>"
        "<ui:Target Selector=\"&lt;webctrl tag='TEXTAREA' /&gt;\" />"
        "</ui:Highlight.Target>"
        "</ui:Highlight>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, HighlightNode)
    assert "TEXTAREA" in node.selector
    assert node.color == "Gold"
    assert node.highlight_time == Literal(value="1000")
    assert node.display_name == "Highlight 'TEXTAREA'"


def test_kill_process_properties():
    """知見169: `ui:KillProcess`(GitHub code searchで1514件ヒット——
    REFrameworkの標準サブワークフロー`KillAllProcesses.xaml`で多用
    される)。`Target`/`Selector`を一切持たず、`ProcessName`(実機
    確認済みの値は`"iexplore"`/`"msedge"`、`.exe`拡張子を含まない)で
    指定した名前に一致する全プロセスを終了する。実機(`piyushagarwal08/
    JU-Notes`・`vajrang-b/UiPathIn30Days`)で確認した属性構成を再現
    する。"""
    xml = (
        f"<ui:KillProcess {_UI_XMLNS} "
        'AppliesTo="{x:Null}" ContinueOnError="{x:Null}" Process="{x:Null}" '
        'DisplayName="Kill Process edge" ProcessName="msedge" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, KillProcessNode)
    assert node.process_name == Literal(value="msedge")
    assert node.display_name == "Kill Process edge"
    assert node.process is None
    assert node.applies_to is None
    assert node.continue_on_error is None


def test_close_tab_properties():
    """知見170: `ui:CloseTab`(GitHub code searchで782件ヒット)。
    `Target`/`Selector`を一切持たず、唯一の属性`Browser`(`UiBrowser`
    型変数参照)が`{x:Null}`の場合(ほとんどのREFramework実例)と
    動的VB式(`[firefox]`、`piyushagarwal08/JU-Notes`)の両方を確認
    済み。"""
    xml = f'<ui:CloseTab {_UI_XMLNS} Browser="{{x:Null}}" DisplayName="Close Tab" />'
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, CloseTabNode)
    assert node.browser is None
    assert node.display_name == "Close Tab"


def test_close_tab_with_browser_variable_reference():
    xml = f'<ui:CloseTab {_UI_XMLNS} Browser="[firefox]" DisplayName="Close Tab" />'
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, CloseTabNode)
    assert node.browser == VbExpr(text="firefox")


def test_log_message_properties():
    xml = (
        f"<ui:LogMessage {_UI_XMLNS} "
        'DisplayName="Log Message" Level="Info" Message="[&quot;done&quot;]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, LogMessageNode)
    assert node.message == VbExpr(text='"done"')
    assert node.level == "Info"
    assert node.display_name == "Log Message"


def test_log_message_level_as_enum_reference():
    """知見124: `Level`が`[UiPath.Core.Activities.LogLevel.Info]`という
    `[...]`角括弧VB式で列挙の完全修飾名を参照する実例(実機XAMLで発見)。
    確認済みのプレフィックスが前置されている場合のみ末尾のメンバー名
    (`"Info"`)を取り出し、以降は既存の`"Info"`/`"Error"`の確認済み経路
    へ流す。"""
    xml = (
        f"<ui:LogMessage {_UI_XMLNS} "
        'DisplayName="Log Message" '
        'Level="[UiPath.Core.Activities.LogLevel.Info]" '
        'Message="[&quot;done&quot;]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, LogMessageNode)
    assert node.level == "Info"


def test_log_message_level_as_unconfirmed_enum_reference_kept_raw():
    """知見124: `LogLevel.Warn`等、確認済みプレフィックスは一致するが
    メンバー名自体が未確認(`"Info"`/`"Error"`以外)の場合は、取り出した
    メンバー名(`"Warn"`)をそのまま`level`に保持する——コード生成側の
    `# TODO`診断メッセージで`"Warn"`が読める形になる。"""
    xml = (
        f"<ui:LogMessage {_UI_XMLNS} "
        'Level="[UiPath.Core.Activities.LogLevel.Warn]" '
        'Message="[&quot;done&quot;]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, LogMessageNode)
    assert node.level == "Warn"


def test_input_dialog_properties():
    """知見131: `ui:InputDialog`(`UiPath.Core.Activities`、
    `cameronmcnz/uipath-tutorials`の`NumberGuesser`の実機XAMLの属性構成を
    そのまま合成XMLで再現する)。"""
    xml = (
        f"<ui:InputDialog {_UI_XMLNS} "
        'Options="{x:Null}" DisplayName="Input Dialog" IsPassword="False" '
        'Label="Pick a number between 1 and 10" Title="What will you choose?">'
        "<ui:InputDialog.Result>"
        '<OutArgument x:TypeArguments="x:Int32">[guess]</OutArgument>'
        "</ui:InputDialog.Result>"
        "</ui:InputDialog>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, InputDialogNode)
    assert node.title == Literal(value="What will you choose?")
    assert node.label == Literal(value="Pick a number between 1 and 10")
    assert node.is_password == "False"
    assert node.options is None
    assert node.result == VbExpr(text="guess")
    assert node.display_name == "Input Dialog"


def test_get_outlook_mail_messages_properties():
    """知見120: `ui:GetOutlookMailMessages`(`SendOutlookMailNode`と対になる
    受信側)。`cameronmcnz/uipath-tutorials`の実機XAMLの属性構成を合成XML
    で再現する——`Filter`はOutlookのDASL/Jetフィルタ構文そのもの
    (`]`で終わらないため`_parse_expr`がVB式の`[...]`角括弧記法と誤認
    しない)。"""
    xml = (
        f"<ui:GetOutlookMailMessages {_UI_XMLNS} "
        "Account=\"{x:Null}\" Filter=\"[importance]='normal'\" "
        'TimeoutMS="{x:Null}" DisplayName="Get Outlook Mail Messages" '
        'GetAttachements="False" MailFolder="Inbox" MarkAsRead="False" '
        'Messages="[MessageBox]" OnlyUnreadMessages="False" Top="30" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, GetOutlookMailMessagesNode)
    assert node.messages == VbExpr(text="MessageBox")
    assert node.account is None
    assert node.filter == Literal(value="[importance]='normal'")
    assert node.mail_folder == "Inbox"
    assert node.get_attachments == "False"
    assert node.mark_as_read == "False"
    assert node.only_unread_messages == "False"
    assert node.top == Literal(value="30")


def test_invoke_workflow_file(main_wf):
    invoke = main_wf.root.body[9]
    assert isinstance(invoke, InvokeWorkflowFileNode)
    assert invoke.workflow_file == "Sub1.xaml"
    assert invoke.arguments["in_text"] == Literal(value="hello")
    # 知見72: `ContinueOnError="{x:Null}"`(実機の確認済み実例)は未設定
    # (`None`)として捕捉される。
    assert invoke.continue_on_error is None


def test_multiple_assign_operations():
    """知見122: `ui:MultipleAssign.AssignOperations`配下の`scg:List
    <ui:AssignOperation>`。`cameronmcnz/uipath-tutorials`の実機XAMLの
    属性構成をそのまま合成XMLで再現する——各`AssignOperation`の
    `.To`/`.Value`は単一の`Assign`と全く同じ構造。"""
    xml = (
        '<ui:MultipleAssign '
        'xmlns:ui="http://schemas.uipath.com/workflow/activities" '
        'xmlns:scg="clr-namespace:System.Collections.Generic;assembly=System" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" '
        'DisplayName="Multiple Assign">'
        "<ui:MultipleAssign.AssignOperations>"
        '<scg:List x:TypeArguments="ui:AssignOperation" Capacity="4">'
        "<ui:AssignOperation>"
        "<ui:AssignOperation.To>"
        '<OutArgument x:TypeArguments="x:Int32">[count]</OutArgument>'
        "</ui:AssignOperation.To>"
        "<ui:AssignOperation.Value>"
        '<InArgument x:TypeArguments="x:Int32">0</InArgument>'
        "</ui:AssignOperation.Value>"
        "</ui:AssignOperation>"
        "<ui:AssignOperation>"
        "<ui:AssignOperation.To>"
        '<OutArgument x:TypeArguments="x:Int32">[secretNumber]</OutArgument>'
        "</ui:AssignOperation.To>"
        "<ui:AssignOperation.Value>"
        '<InArgument x:TypeArguments="x:Int32">5</InArgument>'
        "</ui:AssignOperation.Value>"
        "</ui:AssignOperation>"
        "</scg:List>"
        "</ui:MultipleAssign.AssignOperations>"
        "</ui:MultipleAssign>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, MultipleAssignNode)
    assert node.display_name == "Multiple Assign"
    assert len(node.assignments) == 2
    assert node.assignments[0] == AssignNode(target=VbExpr(text="count"), value=Literal(value="0"))
    assert node.assignments[1] == AssignNode(
        target=VbExpr(text="secretNumber"), value=Literal(value="5")
    )


def test_multiple_assign_to_with_nested_csharp_reference_is_none_not_whitespace():
    """知見136: `.To`が`<CSharpReference>`(知見129のC#式言語形)を
    ネストして持つ場合、`OutArgument`自身の`.text`はタグ間の空白
    (改行+インデント)のみ——これを無視せずそのまま使うと`AssignNode.
    target`が空白文字列の`Literal`になり、`'\n    ' = value`という
    構文的に無効なPythonコードを生成してしまっていた(`ShonHarsh/
    Wordle-Default-Word-Engine`の実機XAMLで発見)。`target`は`None`に
    なるべき(未対応のC#式言語形として、でっち上げた空白文字列を使わず
    `# TODO`へ委ねる)。"""
    xml = (
        '<ui:MultipleAssign '
        'xmlns:ui="http://schemas.uipath.com/workflow/activities" '
        'xmlns:scg="clr-namespace:System.Collections.Generic;assembly=System" '
        'xmlns:mv="clr-namespace:Microsoft.VisualBasic.Activities;assembly=System.Activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" '
        'DisplayName="Multiple Assign">'
        "<ui:MultipleAssign.AssignOperations>"
        '<scg:List x:TypeArguments="ui:AssignOperation" Capacity="4">'
        "<ui:AssignOperation>"
        "<ui:AssignOperation.To>"
        '<OutArgument x:TypeArguments="x:String">\n'
        '  <CSharpReference x:TypeArguments="x:String">message</CSharpReference>\n'
        "</OutArgument>"
        "</ui:AssignOperation.To>"
        "<ui:AssignOperation.Value>"
        '<InArgument x:TypeArguments="x:String">done</InArgument>'
        "</ui:AssignOperation.Value>"
        "</ui:AssignOperation>"
        "</scg:List>"
        "</ui:MultipleAssign.AssignOperations>"
        "</ui:MultipleAssign>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, MultipleAssignNode)
    assert node.assignments[0].target is None


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


def test_do_while_condition_as_visual_basic_value_property_element():
    """知見122: `Condition`は通常`[...]`角括弧の属性形だが、
    `cameronmcnz/uipath-tutorials`の実機XAMLで`<ui:InterruptibleDoWhile.
    Condition><mva:VisualBasicValue ExpressionText="..." />
    </ui:InterruptibleDoWhile.Condition>`という、省略されない要素形
    そのものを発見した——`ExpressionText`は角括弧無しの生のVB式テキスト。
    """
    xml = (
        '<ui:InterruptibleDoWhile '
        'xmlns:ui="http://schemas.uipath.com/workflow/activities" '
        'xmlns:mva="clr-namespace:Microsoft.VisualBasic.Activities;assembly=System.Activities" '
        'DisplayName="Do While">'
        "<ui:InterruptibleDoWhile.Body>"
        '<Sequence DisplayName="Body" />'
        "</ui:InterruptibleDoWhile.Body>"
        "<ui:InterruptibleDoWhile.Condition>"
        '<mva:VisualBasicValue x:TypeArguments="x:Boolean" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" '
        'ExpressionText="guess &lt;&gt; secretNumber" />'
        "</ui:InterruptibleDoWhile.Condition>"
        "</ui:InterruptibleDoWhile>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, DoWhileNode)
    assert node.condition == VbExpr(text="guess <> secretNumber")


def test_if_condition_as_visual_basic_value_property_element():
    """知見123: While/DoWhile(知見122)と同じ`<X.Condition><mva:
    VisualBasicValue ExpressionText="..." /></X.Condition>`形は`If`
    でも同じ仕組み(`_condition_expr`)で起こりうるため、`If.Condition`
    にもフォールバックを適用する(`If`固有の実機確認はまだ無いが、
    `Condition`は`If`/`While`/`DoWhile`いずれも共通の`[...]`省略記法が
    `VisualBasicValue`の糖衣であるという同一の仕組みに基づくため、
    合成XMLで構造を確認する)。"""
    xml = (
        '<If xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:mva="clr-namespace:Microsoft.VisualBasic.Activities;assembly=System.Activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" '
        'DisplayName="If">'
        "<If.Condition>"
        '<mva:VisualBasicValue x:TypeArguments="x:Boolean" '
        'ExpressionText="count &gt; 0" />'
        "</If.Condition>"
        "<If.Then>"
        '<Sequence DisplayName="Then" />'
        "</If.Then>"
        "</If>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, IfNode)
    assert node.condition == VbExpr(text="count > 0")


def test_switch_expression_as_visual_basic_value_property_element():
    """知見123: `Switch.Expression`も`Condition`系と同じ`_condition_expr`
    経由でパースされるため、`<Switch.Expression><mva:VisualBasicValue
    ExpressionText="..." /></Switch.Expression>`形も同様にフォールバック
    される(合成XMLで構造を確認)。"""
    xml = (
        '<Switch xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:mva="clr-namespace:Microsoft.VisualBasic.Activities;assembly=System.Activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" '
        'x:TypeArguments="x:String" DisplayName="Switch">'
        "<Switch.Expression>"
        '<mva:VisualBasicValue x:TypeArguments="x:String" '
        'ExpressionText="choice" />'
        "</Switch.Expression>"
        "</Switch>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, SwitchNode)
    assert node.expression == VbExpr(text="choice")


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
    assert scope.body[0].cell == Literal(value="A1")
    assert scope.body[0].sheet_name == "Sheet1"


def test_attach_window_unwraps_body_sequence():
    """知見153: `ui:AttachWindow`(GitHub code searchで1100件ヒット)。
    `AI-Dep/AI-Antigravity`の実機XAMLで確認した構造——
    `ExcelApplicationScope`/`WordApplicationScope`とは違い
    `ActivityAction`+`DelegateInArgument`のラッパーを持たず、
    `.Body`配下に直接`Sequence`が1つ入るだけの単純な形
    (`ForEach.Body`/`While.Body`と同じ`_unwrap_body_sequence`パターン)。"""
    xml = (
        f"<ui:AttachWindow {_UI_XMLNS} "
        'DisplayName="Attach to Notepad" '
        'Selector="&lt;wnd app=\'notepad.exe\' /&gt;">'
        "<ui:AttachWindow.Body>"
        '<Sequence DisplayName="Body">'
        '<ui:SendHotkey DisplayName="Esc" Key="esc" />'
        "</Sequence>"
        "</ui:AttachWindow.Body>"
        "</ui:AttachWindow>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, AttachWindowNode)
    assert "notepad.exe" in node.selector
    assert node.display_name == "Attach to Notepad"
    assert len(node.body) == 1
    assert isinstance(node.body[0], SendHotkeyNode)


def test_window_scope_reuses_attach_window_node():
    """知見158: `ui:WindowScope`(GitHub code searchで1688件ヒット
    ——`AttachWindow`の1100件より多い!)は`AttachWindow`と同義の別
    活動(`DisplayName`が常に`"Attach Window '...'"`になる、実機9件以上
    で確認)。構造は`OpenApplication`(知見154)と同じ`ActivityAction`+
    `DelegateInArgument`のラッパーを持つが、意味論は`AttachWindow`と
    同じため同じ`AttachWindowNode`を返す。"""
    xml = (
        f"<ui:WindowScope {_UI_XMLNS} "
        'ApplicationWindow="{x:Null}" SearchScope="{x:Null}" '
        'TimeoutMS="{x:Null}" Window="{x:Null}" '
        'DisplayName="Attach Window \'Calculator Applicati\'" '
        'Selector="&lt;wnd app=\'notepad.exe\' /&gt;">'
        "<ui:WindowScope.Body>"
        '<ActivityAction x:TypeArguments="x:Object">'
        "<ActivityAction.Argument>"
        '<DelegateInArgument x:TypeArguments="x:Object" Name="ContextTarget" />'
        "</ActivityAction.Argument>"
        '<Sequence DisplayName="Do">'
        '<ui:SendHotkey DisplayName="Esc" Key="esc" />'
        "</Sequence>"
        "</ActivityAction>"
        "</ui:WindowScope.Body>"
        "</ui:WindowScope>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, AttachWindowNode)
    assert "notepad.exe" in node.selector
    assert node.display_name == "Attach Window 'Calculator Applicati'"
    assert len(node.body) == 1
    assert isinstance(node.body[0], SendHotkeyNode)
    assert node.application_window is None
    assert node.search_scope is None
    assert node.timeout_ms is None
    assert node.window is None


def test_browser_scope_reuses_attach_window_node():
    """知見161: `ui:BrowserScope`(「Attach Browser」、GitHub code
    searchで3388件ヒット——`WindowScope`よりさらに多い)。構造は
    `WindowScope`と同じ`ActivityAction`+`DelegateInArgument`ラッパー
    (`PacktPublishing/Robotic-Process-Automation-Projects`等の実機XAML
    で確認)で、意味論も同じ(既存ブラウザに接続して`Body`を実行)ため
    同じ`AttachWindowNode`を返す。"""
    xml = (
        f"<ui:BrowserScope {_UI_XMLNS} "
        'Browser="{x:Null}" SearchScope="{x:Null}" TimeoutMS="{x:Null}" '
        'UiBrowser="{x:Null}" BrowserType="Chrome" '
        'DisplayName="Attach Browser \'chrome.exe Home\'" '
        'Selector="&lt;html app=\'chrome.exe\' /&gt;">'
        "<ui:BrowserScope.Body>"
        '<ActivityAction x:TypeArguments="x:Object">'
        "<ActivityAction.Argument>"
        '<DelegateInArgument x:TypeArguments="x:Object" Name="ContextTarget" />'
        "</ActivityAction.Argument>"
        '<Sequence DisplayName="Do">'
        '<ui:SendHotkey DisplayName="Esc" Key="esc" />'
        "</Sequence>"
        "</ActivityAction>"
        "</ui:BrowserScope.Body>"
        "</ui:BrowserScope>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, AttachWindowNode)
    assert "chrome.exe" in node.selector
    assert node.display_name == "Attach Browser 'chrome.exe Home'"
    assert len(node.body) == 1
    assert isinstance(node.body[0], SendHotkeyNode)
    assert node.browser is None
    assert node.browser_type == "Chrome"
    assert node.ui_browser is None
    assert node.search_scope is None
    assert node.timeout_ms is None


def test_open_application_unwraps_activity_action_body():
    """知見154: `ui:OpenApplication`。`AttachWindow`(知見153)とは違い
    `ActivityAction`+`DelegateInArgument`のラッパーを持つ(実機
    `PacktPublishing/Robotic-Process-Automation-RPA-for-Developers`の
    `KeyboardActions.xaml`で確認: `DelegateInArgument.Name`は
    `"ContextTarget"`固定)——`ExcelApplicationScope`と同じ構造。"""
    xml = (
        f"<ui:OpenApplication {_UI_XMLNS} "
        'DisplayName="Open Application \'notepad.exe\'" '
        'FileName="C:\\Windows\\System32\\notepad.exe" '
        'Selector="&lt;wnd app=\'notepad.exe\' /&gt;">'
        "<ui:OpenApplication.Body>"
        '<ActivityAction x:TypeArguments="x:Object">'
        "<ActivityAction.Argument>"
        '<DelegateInArgument x:TypeArguments="x:Object" Name="ContextTarget" />'
        "</ActivityAction.Argument>"
        '<Sequence DisplayName="Do">'
        '<ui:SendHotkey DisplayName="Esc" Key="esc" />'
        "</Sequence>"
        "</ActivityAction>"
        "</ui:OpenApplication.Body>"
        "</ui:OpenApplication>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, OpenApplicationNode)
    assert node.file_name == Literal(value="C:\\Windows\\System32\\notepad.exe")
    assert "notepad.exe" in node.selector
    assert len(node.body) == 1
    assert isinstance(node.body[0], SendHotkeyNode)


def test_open_application_dynamic_file_name_and_nullable_attrs():
    """知見154: `FileName`は実機で動的VB式の実例も確認済み
    (`piyushagarwal08/JU-Notes`の`[in_Config("UiDemoPath").ToString]`)。
    `Arguments`/`WorkingDirectory`/`ApplicationWindow`/`TimeoutMS`/
    `ContinueOnError`は`{x:Null}`(未設定、`None`に正規化される)。"""
    xml = (
        f"<ui:OpenApplication {_UI_XMLNS} "
        'ApplicationWindow="{x:Null}" Arguments="{x:Null}" '
        'TimeoutMS="{x:Null}" WorkingDirectory="{x:Null}" '
        'DisplayName="Open Application" '
        'FileName="[in_Config(&quot;UiDemoPath&quot;).ToString]" '
        'Selector="&lt;wnd app=\'uidemo.exe\' /&gt;" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, OpenApplicationNode)
    assert node.file_name == VbExpr(text='in_Config("UiDemoPath").ToString')
    assert node.arguments is None
    assert node.working_directory is None
    assert node.application_window is None
    assert node.timeout_ms is None
    assert node.continue_on_error is None
    assert node.body == []


def test_open_browser_url_and_browser_type():
    """知見168: `ui:OpenBrowser`(GitHub code searchで2648件ヒット)。
    `OpenApplication`と同じ`ActivityAction`+`DelegateInArgument`
    ラッパーを持つが`Target`/`Selector`は一切持たない(既存ウィンドウ
    に接続するのではなく新しいブラウザインスタンスを起動する活動の
    ため)。実機(`PacktPublishing/Robotic-Process-Automation-RPA-for-
    Developers`)で確認した属性構成をそのまま再現する。"""
    xml = (
        f"<ui:OpenBrowser {_UI_XMLNS} "
        'UiBrowser="{x:Null}" BrowserType="IE" DisplayName="Open Browser" '
        'Hidden="False" NewSession="True" Private="False" '
        'Url="https://www.google.com/">'
        "<ui:OpenBrowser.Body>"
        '<ActivityAction x:TypeArguments="x:Object">'
        "<ActivityAction.Argument>"
        '<DelegateInArgument x:TypeArguments="x:Object" Name="ContextTarget" />'
        "</ActivityAction.Argument>"
        '<Sequence DisplayName="Do">'
        '<ui:SendHotkey DisplayName="Esc" Key="esc" />'
        "</Sequence>"
        "</ActivityAction>"
        "</ui:OpenBrowser.Body>"
        "</ui:OpenBrowser>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, OpenBrowserNode)
    assert node.url == Literal(value="https://www.google.com/")
    assert node.browser_type == "IE"
    assert node.hidden == Literal(value="False")
    assert node.new_session == Literal(value="True")
    assert node.private == Literal(value="False")
    assert node.ui_browser is None
    assert node.communication_method is None
    assert len(node.body) == 1
    assert isinstance(node.body[0], SendHotkeyNode)


def test_open_browser_dynamic_url_and_output_binding():
    """知見168: `Url`は実機で動的VB式(`[NewsUrl]`、`allenlooplee/
    RPABook`)の実例も確認済み。`UiBrowser`は出力バインディングの実例
    (`[firefox]`、`piyushagarwal08/JU-Notes`)を確認済み。"""
    xml = (
        f"<ui:OpenBrowser {_UI_XMLNS} "
        'BrowserType="Firefox" UiBrowser="[firefox]" Url="[NewsUrl]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, OpenBrowserNode)
    assert node.url == VbExpr(text="NewsUrl")
    assert node.ui_browser == VbExpr(text="firefox")
    assert node.body == []


def test_word_application_scope_and_replace_text_in_document():
    """知見121: `ui:WordApplicationScope`+`ui:ReplaceTextInDocument`
    (`UiPath/skills`公式リポジトリの実機XAMLの属性構成をそのまま合成XML
    で再現する)。`_parse_excel_application_scope`と同じ
    `ActivityAction`+`DelegateInArgument`構造。"""
    xml = (
        f"<ui:WordApplicationScope {_UI_XMLNS} "
        'DisplayName="Word Application Scope" FileName="Output\\OfferLetter.docx" '
        'Visible="False">'
        "<ui:WordApplicationScope.Body>"
        '<ActivityAction x:TypeArguments="ui:WordDocument">'
        "<ActivityAction.Argument>"
        '<DelegateInArgument x:TypeArguments="ui:WordDocument" Name="WordDocumentScope" />'
        "</ActivityAction.Argument>"
        '<ui:ReplaceTextInDocument DisplayName="Replace Text in Document" '
        'Search="{{Candidate}}" Replace="[candidate]" />'
        "</ActivityAction>"
        "</ui:WordApplicationScope.Body>"
        "</ui:WordApplicationScope>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, WordApplicationScopeNode)
    assert node.file_name == "Output\\OfferLetter.docx"
    assert node.scope_var == "WordDocumentScope"
    assert len(node.body) == 1
    replace = node.body[0]
    assert isinstance(replace, WordReplaceTextNode)
    assert replace.search == Literal(value="{{Candidate}}")
    assert replace.replace == VbExpr(text="candidate")
    assert replace.display_name == "Replace Text in Document"


def test_word_replace_text_alternate_tag_name():
    """知見121: 実機で2つの異なるタグ名(`ui:ReplaceTextInDocument`/
    `ui:WordReplaceText`)を確認した——どちらも同じ`WordReplaceTextNode`
    へパースされる。"""
    xml = f'<ui:WordReplaceText {_UI_XMLNS} DisplayName="Replace Text" Search="[a]" Replace="[b]" />'
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, WordReplaceTextNode)
    assert node.search == VbExpr(text="a")
    assert node.replace == VbExpr(text="b")


def test_send_outlook_mail_and_set_to_clipboard(main_wf):
    mail = main_wf.root.body[18]
    assert isinstance(mail, SendOutlookMailNode)
    assert mail.to == Literal(value="a@b.com")
    assert mail.subject == Literal(value="hi")

    clip = main_wf.root.body[19]
    assert isinstance(clip, SetToClipboardNode)
    assert clip.text == Literal(value="cliptext")


def test_send_mail_smtp_properties():
    """知見116: `ui:SendMail`(DisplayName「Send SMTP Mail Message」)。
    `cameronmcnz/uipath-tutorials`の実機保存済みXAML(Gmail SMTP送信)の
    属性構成をそのまま合成XMLで再現する。"""
    xml = (
        f"<ui:SendMail {_UI_XMLNS} "
        'xmlns:scg="clr-namespace:System.Collections.Generic;assembly=System" '
        'Bcc="{x:Null}" Cc="{x:Null}" From="{x:Null}" MailMessage="{x:Null}" '
        'Name="{x:Null}" TimeoutMS="{x:Null}" '
        'Body="Catch me outside, will you." DisplayName="Send SMTP Mail Message" '
        'Email="arpeeyeah@gmail.com" EnableSSL="True" IsBodyHtml="False" '
        'Password="100thMeridian" Port="465" SecureConnection="Auto" '
        'Server="smtp.gmail.com" Subject="Look at this attachment!" '
        'To="cameronmcnz@outlook.com">'
        "<ui:SendMail.Files>"
        '<scg:List x:TypeArguments="InArgument(x:String)" Capacity="0" />'
        "</ui:SendMail.Files>"
        "</ui:SendMail>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, SendMailNode)
    assert node.to == Literal(value="cameronmcnz@outlook.com")
    assert node.server == Literal(value="smtp.gmail.com")
    assert node.port == Literal(value="465")
    assert node.enable_ssl == "True"
    assert node.secure_connection == "Auto"
    assert node.has_populated_files is False
    assert node.from_ is None
    assert node.mail_message is None


def test_copy_file_properties():
    """知見117: `ui:CopyFile`。`allenlooplee/RPABook`の実機保存済みXAMLの
    属性構成をそのまま合成XMLで再現する。"""
    xml = (
        f"<ui:CopyFile {_UI_XMLNS} "
        'ContinueOnError="{x:Null}" Destination="[uploadFileName]" '
        'DisplayName="Copy File" Overwrite="False" Path="youqian.xlsx" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, CopyFileNode)
    assert node.path == Literal(value="youqian.xlsx")
    assert node.destination == VbExpr(text="uploadFileName")
    assert node.overwrite == "False"
    assert node.continue_on_error is None


def test_build_data_table_extracts_column_names_from_embedded_schema():
    """知見117: `ui:BuildDataTable`。`TableInfo`に埋め込まれた.NET DataSetの
    XMLスキーマから列名を抜き出す——`marcelocruzrpa/uipath-ai-skills`の
    ground-truth実例の構造をそのまま合成XMLで再現する。"""
    table_info = (
        "<NewDataSet>"
        '<xs:schema id="NewDataSet" xmlns="" '
        'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
        'xmlns:msdata="urn:schemas-microsoft-com:xml-msdata">'
        '<xs:element name="NewDataSet" msdata:IsDataSet="true">'
        "<xs:complexType><xs:choice minOccurs=\"0\" maxOccurs=\"unbounded\">"
        '<xs:element name="TableName"><xs:complexType><xs:sequence>'
        '<xs:element name="Column1" minOccurs="0" />'
        '<xs:element name="Column2" type="xs:int" minOccurs="0" />'
        "</xs:sequence></xs:complexType></xs:element>"
        "</xs:choice></xs:complexType></xs:element>"
        "</xs:schema></NewDataSet>"
    )
    xml = (
        f"<ui:BuildDataTable {_UI_XMLNS} "
        f'DataTable="[checklogTable]" DisplayName="Build Data Table" '
        f'TableInfo="{html.escape(table_info)}" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, BuildDataTableNode)
    assert node.data_table == VbExpr(text="checklogTable")
    assert node.columns == ["Column1", "Column2"]


def test_build_data_table_with_unparseable_table_info_returns_empty_columns():
    xml = (
        f"<ui:BuildDataTable {_UI_XMLNS} "
        'DataTable="[dt]" TableInfo="not valid xml &lt;" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, BuildDataTableNode)
    assert node.columns == []


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


def test_parse_workflow_file_tolerates_assembly_qualified_clr_namespace_xmlns(tmp_path):
    """知見132: `xmlns:mv="clr-namespace:Microsoft.VisualBasic;assembly=
    Microsoft.VisualBasic, Version=10.0.0.0, Culture=neutral,
    PublicKeyToken=..."`形(`mnsy1/UiPath_ACMEVerifyAccountPositions`の
    実機XAML、REFrameworkの`RetryCurrentTransaction.xaml`で発見——
    REFramework系の多数の実プロジェクトで共通して使われる典型的な
    ファイル)。libxml2がこの値を「valid URIではない」と過剰に厳格な
    検証で拒否する既知の挙動があり、修正前は`lxml.etree.XMLSyntaxError`
    でワークフロー全体のパースが完全に失敗していた。"""
    xaml = (
        '<Activity x:Class="Test" '
        'xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" '
        'xmlns:mv="clr-namespace:Microsoft.VisualBasic;assembly='
        'Microsoft.VisualBasic, Version=10.0.0.0, Culture=neutral, '
        'PublicKeyToken=b03f5f7f11d50a3a">'
        '<Sequence DisplayName="Body" />'
        "</Activity>"
    )
    path = tmp_path / "Test.xaml"
    path.write_text(xaml, encoding="utf-8")
    wf = parse_workflow_file(path)
    assert wf.class_name == "Test"
    assert isinstance(wf.root, SequenceNode)


def test_parse_workflow_file_treats_null_class_name_as_unset(tmp_path):
    """知見145: `x:Class="{x:Null}"`(`bacdillon/UiPath-Automation`の
    実機XAMLで発見——Studioでクラス名が未設定/削除された状態の
    ワークフロー)。`_parse_expr`(知見13)が属性値の`{x:Null}`を一般に
    「未設定」として`None`へ正規化する規約を`x:Class`にも適用する——
    正規化せずに放置すると、修正前は`class_name`にリテラル文字列
    `"{x:Null}"`がそのまま残り、`uipath_codegen`が生成するPython関数
    定義の名前に埋め込まれ`def {x:Null}(...):`という構文的に無効な
    コードになっていた。"""
    xaml = (
        '<Activity x:Class="{x:Null}" '
        'xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
        '<Sequence DisplayName="Body" />'
        "</Activity>"
    )
    path = tmp_path / "Test.xaml"
    path.write_text(xaml, encoding="utf-8")
    wf = parse_workflow_file(path)
    assert wf.class_name == ""
    assert isinstance(wf.root, SequenceNode)


def test_parse_workflow_file_normalizes_identifier_case_against_declaration(tmp_path):
    """知見130(【重大、未解決】として記録)の実修正: VB.NETは識別子の
    大文字小文字を区別しないため、ワークフロー引数`out_RequirementLanCur`
    (小文字`o`)の宣言と、本体`Assign.To`内の`[Out_RequirementLanCur]`
    (大文字`O`)という別表記の参照が、`TanMzCs2025/
    EDSAChallengeTania2025_AmazonProductSearchAndFilter`の実機XAML
    (`Browser_ValidateLangAndCur.xaml`)で実際に混在していた——これを
    放置すると関数の仮引数`out_RequirementLanCur`と本体内の無関係な
    ローカル変数`Out_RequirementLanCur`という2つの別々のPython識別子に
    なってしまう(構文的に正しいが意味的に誤ったコードを静かに生成する
    既知の限界)。`parse_workflow_file`の入口でXML木全体を正規化する
    ことで、どちらも宣言時の表記(`out_RequirementLanCur`)に揃う。"""
    xaml = (
        '<Activity x:Class="Test" '
        'xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
        "<x:Members>"
        '<x:Property Name="out_RequirementLanCur" Type="OutArgument(x:Boolean)" />'
        "</x:Members>"
        '<Sequence DisplayName="Body">'
        '<Assign DisplayName="Set it">'
        "<Assign.To>"
        '<OutArgument x:TypeArguments="x:Boolean">[Out_RequirementLanCur]</OutArgument>'
        "</Assign.To>"
        "<Assign.Value>"
        '<InArgument x:TypeArguments="x:Boolean">True</InArgument>'
        "</Assign.Value>"
        "</Assign>"
        "</Sequence>"
        "</Activity>"
    )
    path = tmp_path / "Test.xaml"
    path.write_text(xaml, encoding="utf-8")
    wf = parse_workflow_file(path)
    assert "out_RequirementLanCur" in wf.arguments
    assign = wf.root.body[0]
    assert isinstance(assign, AssignNode)
    assert assign.target == VbExpr(text="out_RequirementLanCur")


def test_parse_workflow_file_normalizes_local_variable_identifier_case(tmp_path):
    """知見130: 「通常のローカル変数の読み書きでも理論上同じように
    起こりうる」という記録の、ローカル変数版の回帰テスト——`<Variable
    Name="myVar">`宣言と本体内の`[MyVar]`参照という表記揺れも同様に
    宣言時の表記へ正規化される。"""
    xaml = (
        '<Activity x:Class="Test" '
        'xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
        '<Sequence DisplayName="Body">'
        "<Sequence.Variables>"
        '<Variable x:TypeArguments="x:String" Name="myVar" />'
        "</Sequence.Variables>"
        '<Assign DisplayName="Set it">'
        "<Assign.To>"
        '<OutArgument x:TypeArguments="x:String">[MyVar]</OutArgument>'
        "</Assign.To>"
        "<Assign.Value>"
        '<InArgument x:TypeArguments="x:String">hi</InArgument>'
        "</Assign.Value>"
        "</Assign>"
        "</Sequence>"
        "</Activity>"
    )
    path = tmp_path / "Test.xaml"
    path.write_text(xaml, encoding="utf-8")
    wf = parse_workflow_file(path)
    assign = wf.root.body[0]
    assert isinstance(assign, AssignNode)
    assert assign.target == VbExpr(text="myVar")


def test_parse_workflow_file_identifier_case_normalization_skips_member_access(tmp_path):
    """知見130の修正: メンバアクセス(`.`直後、例: `obj.MyVar`の`MyVar`)は
    変数名ではなくメソッド/プロパティ名のため、たまたま宣言済み変数名と
    同じ文字列でも書き換えない——`CurrentRow("MyVar").ToString()`のような
    式が壊れないことを確認する(文字列リテラルの内側も同様に対象外)。"""
    xaml = (
        '<Activity x:Class="Test" '
        'xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
        '<Sequence DisplayName="Body">'
        "<Sequence.Variables>"
        '<Variable x:TypeArguments="x:String" Name="myVar" />'
        "</Sequence.Variables>"
        '<Assign DisplayName="Set it">'
        "<Assign.To>"
        '<OutArgument x:TypeArguments="x:String">[myVar]</OutArgument>'
        "</Assign.To>"
        "<Assign.Value>"
        '<InArgument x:TypeArguments="x:String">[obj.MyVar.ToString()]</InArgument>'
        "</Assign.Value>"
        "</Assign>"
        "</Sequence>"
        "</Activity>"
    )
    path = tmp_path / "Test.xaml"
    path.write_text(xaml, encoding="utf-8")
    wf = parse_workflow_file(path)
    assign = wf.root.body[0]
    assert isinstance(assign, AssignNode)
    assert assign.value == VbExpr(text="obj.MyVar.ToString()")
