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
    AddDataColumnNode,
    AddDataRowNode,
    AppendLineNode,
    AssignNode,
    AttachWindowNode,
    BreakNode,
    BuildDataTableNode,
    CheckNode,
    ClearDataTableNode,
    ClickNode,
    CloseApplicationNode,
    CloseTabNode,
    CloseWindowNode,
    CommentNode,
    CopyFileNode,
    CreateFileNode,
    DatabaseConnectNode,
    DatabaseDisconnectNode,
    DelayNode,
    DeleteFileNode,
    DeleteFolderNode,
    DoWhileNode,
    ExcelApplicationScopeNode,
    ExcelAppendRangeNode,
    ExcelReadCellNode,
    ExcelReadRangeNode,
    ExcelWriteCellNode,
    ExcelWriteRangeNode,
    ExecuteNonQueryNode,
    ExecuteQueryNode,
    ExtractPdfPageRangeNode,
    ForEachFileNode,
    ForEachFolderNode,
    ForEachNode,
    GenerateDataTableNode,
    GetAttributeNode,
    GetOcrTextNode,
    GetOutlookMailMessagesNode,
    GetPasswordNode,
    GetPdfPageCountNode,
    GetRowItemNode,
    GetTextNode,
    HighlightNode,
    HoverNode,
    HttpClientNode,
    IfNode,
    InputDialogNode,
    InvokeCodeNode,
    InvokePowerShellNode,
    InvokeWorkflowFileNode,
    JoinPdfNode,
    ExportPdfPageAsImageNode,
    ExtractImagesFromPdfNode,
    KillProcessNode,
    Literal,
    LoadImageNode,
    LookupDataTableNode,
    FilterDataTableNode,
    FilterOperationArgument,
    JoinDataTablesNode,
    JoinOperationArgument,
    LogMessageNode,
    ManagePdfPasswordNode,
    MessageBoxNode,
    MoveFileNode,
    MultipleAssignNode,
    OpenApplicationNode,
    OpenBrowserNode,
    OutputDataTableNode,
    ParallelNode,
    PathExistsNode,
    ReadCsvFileNode,
    ReadPdfTextNode,
    ReadTextFileNode,
    WriteTextFileNode,
    RefreshBrowserNode,
    RemoveDataColumnNode,
    RemoveDataRowNode,
    RenameFileNode,
    RenameFolderNode,
    RethrowNode,
    RetryScopeNode,
    SaveImageNode,
    SelectFileNode,
    SelectItemNode,
    SendHotkeyNode,
    SendMailNode,
    SendOutlookMailNode,
    SequenceNode,
    SetToClipboardNode,
    SortDataTableNode,
    SwitchNode,
    TakeScreenshotNode,
    TerminateWorkflowNode,
    ThrowNode,
    TryCatchNode,
    TypeIntoNode,
    UiElementExistsNode,
    UnknownActivityNode,
    VbExpr,
    WhileNode,
    WindowStateNode,
    WordApplicationScopeNode,
    WordReplaceTextNode,
    WriteCsvFileNode,
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


def test_select_file_properties():
    """知見192: `ui:SelectFile`(GitHub code searchで157件ヒット)。
    実機`GSA/RPA-OSS`の`CatalogFramework/Main.xaml`で確認した
    `Filter`+`SelectedFile`(出力)の構成。"""
    xml = (
        f"<ui:SelectFile {_UI_XMLNS} DisplayName=\"Select Input File for Execution\" "
        'Filter="Excel Files (*.xls, *.xlsx)|*.xls;*.xlsx" '
        'SelectedFile="[inputFileFullAddress]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, SelectFileNode)
    assert node.filter == Literal(value="Excel Files (*.xls, *.xlsx)|*.xls;*.xlsx")
    assert node.selected_file == VbExpr(text="inputFileFullAddress")
    assert node.selected_files is None
    assert node.multiselect is None
    assert node.initial_directory is None


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


def test_refresh_browser_properties():
    """知見175: `ui:RefreshBrowser`(GitHub code searchで59件ヒット)。
    `CloseTab`(知見170)と同じ属性構成(`Browser`のみ)——実機
    `PakamTharunReddy/RPA`で確認した`{x:Null}`の実例。"""
    xml = f'<ui:RefreshBrowser {_UI_XMLNS} Browser="{{x:Null}}" DisplayName="Refresh Browser" />'
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, RefreshBrowserNode)
    assert node.browser is None
    assert node.display_name == "Refresh Browser"


def test_refresh_browser_with_browser_variable_reference():
    """実機`csut017/CrowdMarkLoad`で確認した`[browser]`の実例。"""
    xml = f'<ui:RefreshBrowser {_UI_XMLNS} Browser="[browser]" DisplayName="Refresh Browser" />'
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, RefreshBrowserNode)
    assert node.browser == VbExpr(text="browser")


def test_close_application_selector_and_properties():
    """知見171: `ui:CloseApplication`(GitHub code searchで532件
    ヒット)。`Target`+`DisplayName`/`ContinueOnError`のみという
    `Activate`(知見162)と同じ属性構成——実機
    `allenlooplee/RPABook`(`CloseNotepad.xaml`)で確認。"""
    xml = (
        f"<ui:CloseApplication {_UI_XMLNS} DisplayName=\"Close application\">"
        "<ui:CloseApplication.Target>"
        "<ui:Target Selector=\"&lt;wnd app='notepad.exe' /&gt;\" />"
        "</ui:CloseApplication.Target>"
        "</ui:CloseApplication>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, CloseApplicationNode)
    assert "notepad.exe" in node.selector
    assert node.display_name == "Close application"
    assert node.continue_on_error is None


def test_close_application_no_selector():
    """実機`HarshadRanganathan/uipath-learning`(`Web_Recording.xaml`)で
    確認した`Selector="{x:Null}"`(未設定)のケース。"""
    xml = (
        f"<ui:CloseApplication {_UI_XMLNS} DisplayName=\"Close application\">"
        "<ui:CloseApplication.Target>"
        '<ui:Target Selector="{x:Null}" />'
        "</ui:CloseApplication.Target>"
        "</ui:CloseApplication>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, CloseApplicationNode)
    assert node.selector is None


def test_close_window_selector_and_properties():
    """知見172: `ui:CloseWindow`(GitHub code searchで276件ヒット)。
    `CloseApplication`(知見171)と同じ`close()`意味論だが、`Selector`
    をフラット属性として直接持つ「Classic」世代の活動——実機
    `Klaus-in-Tech/Ford.com-scrapper`(`CloseAllApplications.xaml`)
    等で確認。"""
    xml = (
        f"<ui:CloseWindow {_UI_XMLNS} DisplayName=\"Close Window\" "
        "Selector=\"&lt;wnd app='notepad.exe' /&gt;\" />"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, CloseWindowNode)
    assert "notepad.exe" in node.selector
    assert node.display_name == "Close Window"
    assert node.use_window is None
    assert node.continue_on_error is None


def test_close_window_selector_x_null_normalizes_to_none():
    """実機`SuneetPatil/IRCTC-tatkal-booking`(`UseWindow`使用時に
    `Selector="{x:Null}"`になる実例)で確認した正規化が必要なケース——
    `_attr`はフラット属性を生取得するだけで`{x:Null}`正規化を行わない
    ため、本パーサーで明示的に正規化する。"""
    xml = (
        f"<ui:CloseWindow {_UI_XMLNS} DisplayName=\"Close Window\" "
        'Selector="{x:Null}" '
        'UseWindow="[browser_window.Element.GetTopLevelWindow]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, CloseWindowNode)
    assert node.selector is None
    assert node.use_window == VbExpr(text="browser_window.Element.GetTopLevelWindow")


def test_maximize_window_properties():
    """知見173: `ui:MaximizeWindow`/`ui:MinimizeWindow`/`ui:RestoreWindow`。
    `Window`+`DisplayName`/`ContinueOnError`のみという同一属性構成——
    実機`PacktPublishing/Robotic-Process-Automation-Projects`等で確認。"""
    xml = f'<ui:MaximizeWindow {_UI_XMLNS} Window="{{x:Null}}" DisplayName="Maximize Window" />'
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, WindowStateNode)
    assert node.method == "maximize"
    assert node.window is None
    assert node.display_name == "Maximize Window"
    assert node.continue_on_error is None


def test_minimize_window_with_saved_window_variable_reference():
    """実機`Apress/Robotic-Process-Automation-Using-UiPath-StudioX`で
    確認した、StudioXの保存済み`Window`型変数参照を`Window`に指定する
    実例。"""
    xml = (
        f"<ui:MinimizeWindow {_UI_XMLNS} DisplayName=\"Minimize Window\" "
        'Window="[Saved.Values(Of Window)(&quot;ActiveWindow&quot;)]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, WindowStateNode)
    assert node.method == "minimize"
    assert node.window == VbExpr(text='Saved.Values(Of Window)("ActiveWindow")')


def test_restore_window_properties():
    xml = f'<ui:RestoreWindow {_UI_XMLNS} DisplayName="Restore Window" />'
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, WindowStateNode)
    assert node.method == "restore"


def test_generate_data_table_properties():
    """知見197: `ui:GenerateDataTable`(GitHub code searchで180件
    ヒット)。実機`vajrang-b/UiPathIn30Days`で確認した`CSVParsing`+
    `ColumnSeparators`+`UseColumnHeader`——ground-truthコーパスには
    無かった属性群(知見128の既存の注意を裏付ける)。"""
    xml = (
        f"<ui:GenerateDataTable {_UI_XMLNS} "
        'ColumnSizes="{x:Null}" Positions="{x:Null}" CSVParsing="False" '
        'ColumnSeparators=";" DataTable="[Out_DT]" '
        'DisplayName="Generate Data Table From Text" Input="[Out_Text]" '
        'NewLineSeparator="&#10;" UseColumnHeader="True" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, GenerateDataTableNode)
    assert node.input == VbExpr(text="Out_Text")
    assert node.data_table == VbExpr(text="Out_DT")
    assert node.column_separators == Literal(value=";")
    assert node.new_line_separator == Literal(value="\n")
    assert node.use_column_header == "True"
    assert node.csv_parsing == "False"
    assert node.positions is None
    assert node.column_sizes is None


def test_get_attribute_selector_and_properties():
    """知見174: `ui:GetAttribute`(GitHub code searchで274件ヒット)。
    `Target`+`Attribute`+`Result`+`ContinueOnError`という構成——実機
    `iamgauravjoshi/Shopping-Bot-using-RPA`で確認した`Attribute=
    "innerText"`の実例。"""
    xml = (
        f"<ui:GetAttribute {_UI_XMLNS} DisplayName=\"Get Attribute\" "
        'Attribute="innerText">'
        "<ui:GetAttribute.Result>"
        '<OutArgument x:TypeArguments="x:String">[out_Rating]</OutArgument>'
        "</ui:GetAttribute.Result>"
        "<ui:GetAttribute.Target>"
        "<ui:Target Selector=\"&lt;wnd cls='Notepad' /&gt;\" />"
        "</ui:GetAttribute.Target>"
        "</ui:GetAttribute>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, GetAttributeNode)
    assert "Notepad" in node.selector
    assert node.display_name == "Get Attribute"
    assert node.attribute == "innerText"
    assert node.result == VbExpr(text="out_Rating")
    assert node.continue_on_error is None


def test_get_password_with_flat_result_attribute():
    """知見176: `ui:GetPassword`(GitHub code searchで540件ヒット)。
    実機`Parmeetkour/RPA`・`akritimangal/AssignmentsBOT`で確認した
    フラット属性形`Result="[pw]"`。`ProtectedPassword`(DPAPI暗号化
    バイナリ)自体は本トランスパイラが扱う必要が無いため、ノードには
    保持しない。"""
    xml = (
        f"<ui:GetPassword {_UI_XMLNS} DisplayName=\"Get Password\" "
        'ProtectedPassword="AQAAANCMnd8BFdERjHoAwE/Cl" Result="[pw]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, GetPasswordNode)
    assert node.display_name == "Get Password"
    assert node.result == VbExpr(text="pw")


def test_get_password_with_no_result_captured():
    """実機`vajrang-b/UiPathIn30Days`で確認した、`Result`プロパティ
    要素が`VisualBasicReference`(通常のOutArgument直書きとは別の
    特殊な参照形)でラップされているため値を抽出できないケース——
    でっち上げず`result=None`になることを確認する。"""
    xml = (
        f"<ui:GetPassword {_UI_XMLNS} DisplayName=\"Get Password\" "
        'ProtectedPassword="AQAAANCMnd8BFdERjHoAwE/Cl">'
        "<ui:GetPassword.Result>"
        '<OutArgument x:TypeArguments="x:String">'
        '<VisualBasicReference x:TypeArguments="x:String" ExpressionText="Password" />'
        "</OutArgument>"
        "</ui:GetPassword.Result>"
        "</ui:GetPassword>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, GetPasswordNode)
    assert node.result is None


def test_lookup_data_table_properties():
    """知見196: `ui:LookupDataTable`(GitHub code searchで197件ヒット)。
    実機`PacktPublishing/Robotic-Process-Automation-RPA-for-Developers`
    で確認した`LookupColumnName`+`LookupValue`+`TargetColumnName`+
    `CellValue`(プロパティ要素形の`OutArgument`)+`RowIndex`(flat属性)
    の構成。"""
    xml = (
        f"<ui:LookupDataTable {_UI_XMLNS} "
        'LookupColumnIndex="{x:Null}" LookupDataColumn="{x:Null}" '
        'TargetColumnIndex="{x:Null}" TargetDataColumn="{x:Null}" '
        'DataTable="[dt]" DisplayName="Lookup data table" '
        'LookupColumnName="Name" LookupValue="John Gates" '
        'RowIndex="[rowIndex]" TargetColumnName="Name">'
        "<ui:LookupDataTable.CellValue>"
        '<OutArgument x:TypeArguments="ui:GenericValue">[cellValue]</OutArgument>'
        "</ui:LookupDataTable.CellValue>"
        "</ui:LookupDataTable>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, LookupDataTableNode)
    assert node.data_table == VbExpr(text="dt")
    assert node.lookup_column_name == Literal(value="Name")
    assert node.lookup_value == Literal(value="John Gates")
    assert node.target_column_name == Literal(value="Name")
    assert node.cell_value == VbExpr(text="cellValue")
    assert node.row_index == VbExpr(text="rowIndex")
    assert node.lookup_column_index is None
    assert node.lookup_data_column is None
    assert node.target_column_index is None
    assert node.target_data_column is None


def test_sort_data_table_properties_with_order_alias_and_decending_typo():
    """知見195/206: 実機`PacktPublishing/Robotic-Process-Automation-
    RPA-for-Developers`で確認した構成——属性名`Order`(ground-truthの
    `SortOrder`とは別名)+値`"Decending"`(`"Descending"`の誤字)。"""
    xml = (
        f"<ui:SortDataTable {_UI_XMLNS} "
        'ColumnIndex="{x:Null}" DataColumn="{x:Null}" ColumnName="Age" '
        'DataTable="[dt]" DisplayName="Sort data table" '
        'Order="Decending" OutputDataTable="[dtProcessed]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, SortDataTableNode)
    assert node.data_table == VbExpr(text="dt")
    assert node.output_data_table == VbExpr(text="dtProcessed")
    assert node.column_name == Literal(value="Age")
    assert node.column_index is None
    assert node.data_column is None
    assert node.sort_order == "Decending"


def test_sort_data_table_prefers_sort_order_attribute_over_order_alias():
    """知見195/206: 実機`ShonHarsh/RPADev-S06P01-GetAndSortData-
    WindowsLegacy`では`Order`と`SortOrder`が同じ値で**両方同時に**
    直列化されていた——ground-truthの正式名`SortOrder`を優先する。"""
    xml = (
        f"<ui:SortDataTable {_UI_XMLNS} "
        'ColumnIndex="{x:Null}" DataColumn="{x:Null}" ColumnName="Name" '
        'DisplayName="Sort Data Table" Order="Ascending" '
        'SortOrder="Ascending">'
        '<ui:SortDataTable.DataTable>'
        '<InArgument x:TypeArguments="sd:DataTable">[dataTable]</InArgument>'
        "</ui:SortDataTable.DataTable>"
        '<ui:SortDataTable.OutputDataTable>'
        '<OutArgument x:TypeArguments="sd:DataTable">[dataTable]</OutArgument>'
        "</ui:SortDataTable.OutputDataTable>"
        "</ui:SortDataTable>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, SortDataTableNode)
    assert node.data_table == VbExpr(text="dataTable")
    assert node.output_data_table == VbExpr(text="dataTable")
    assert node.column_name == Literal(value="Name")
    assert node.sort_order == "Ascending"


_SCG_XMLNS = (
    'xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
    'xmlns:ui="http://schemas.uipath.com/workflow/activities" '
    'xmlns:scg="clr-namespace:System.Collections.Generic;assembly=mscorlib" '
    'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"'
)


def test_filter_data_table_properties_with_string_columns_and_no_select_columns():
    """知見207: 実機`cameronmcnz/uipath-tutorials`(`DeleteEmpty/Main.
    xaml`)で確認した構成——`Operator="EMPTY"`+`Column`が`x:Int32`型
    (列インデックス)+`Operand`無し+`SelectColumns`が単一の`<x:Null/>`
    (「未選択」のシリアライズ形、`select_columns`は空リストになる)。"""
    xml = (
        f"<ui:FilterDataTable {_SCG_XMLNS} "
        'DataTable="[ExtractDataTable]" DisplayName="Filter Data Table" '
        'FilterRowsMode="Remove" OutputDataTable="[ExtractDataTable]" '
        'SelectColumnsMode="Keep">'
        "<ui:FilterDataTable.Filters>"
        '<scg:List x:TypeArguments="ui:FilterOperationArgument" Capacity="4">'
        '<ui:FilterOperationArgument Operand="{x:Null}" BooleanOperator="And" '
        'Operator="EMPTY">'
        "<ui:FilterOperationArgument.Column>"
        '<InArgument x:TypeArguments="x:Int32">[0]</InArgument>'
        "</ui:FilterOperationArgument.Column>"
        "</ui:FilterOperationArgument>"
        "</scg:List>"
        "</ui:FilterDataTable.Filters>"
        "<ui:FilterDataTable.SelectColumns>"
        '<scg:List x:TypeArguments="InArgument" Capacity="4">'
        "<x:Null/>"
        "</scg:List>"
        "</ui:FilterDataTable.SelectColumns>"
        "</ui:FilterDataTable>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, FilterDataTableNode)
    assert node.data_table == VbExpr(text="ExtractDataTable")
    assert node.output_data_table == VbExpr(text="ExtractDataTable")
    assert node.filter_rows_mode == "Remove"
    assert node.select_columns_mode == "Keep"
    assert node.select_columns == []
    assert len(node.filters) == 1
    filt = node.filters[0]
    assert isinstance(filt, FilterOperationArgument)
    assert filt.boolean_operator == "And"
    assert filt.operator == "EMPTY"
    assert filt.column == VbExpr(text="0")
    assert filt.column_type == "x:Int32"
    assert filt.operand is None


def test_filter_data_table_properties_with_select_columns_and_multiple_filters():
    """知見207: 実機`PacktPublishing/Robotic-Process-Automation-RPA-
    for-Developers`(`Section 6/DataManipulation_DataTables.xaml`)で
    確認した構成——`Operator="GTE"`を2件`BooleanOperator="And"`で結合、
    `Column`が`x:String`型(列名)+`Operand`が`x:Double`型、
    `SelectColumns`に実際の列名3件+`OutputDataTable`が`DataTable`とは
    別の変数。"""
    xml = (
        f"<ui:FilterDataTable {_SCG_XMLNS} "
        'DataTable="[dt]" DisplayName="Filter data table" '
        'FilterRowsMode="Keep" OutputDataTable="[dtProcessed]" '
        'SelectColumnsMode="Keep">'
        "<ui:FilterDataTable.Filters>"
        '<scg:List x:TypeArguments="ui:FilterOperationArgument" Capacity="4">'
        '<ui:FilterOperationArgument BooleanOperator="And" Operator="GTE">'
        "<ui:FilterOperationArgument.Column>"
        '<InArgument x:TypeArguments="x:String">["Age"]</InArgument>'
        "</ui:FilterOperationArgument.Column>"
        "<ui:FilterOperationArgument.Operand>"
        '<InArgument x:TypeArguments="x:Double">[60.0]</InArgument>'
        "</ui:FilterOperationArgument.Operand>"
        "</ui:FilterOperationArgument>"
        '<ui:FilterOperationArgument BooleanOperator="And" Operator="GTE">'
        "<ui:FilterOperationArgument.Column>"
        '<InArgument x:TypeArguments="x:String">["Salary"]</InArgument>'
        "</ui:FilterOperationArgument.Column>"
        "<ui:FilterOperationArgument.Operand>"
        '<InArgument x:TypeArguments="x:Double">[70000.0]</InArgument>'
        "</ui:FilterOperationArgument.Operand>"
        "</ui:FilterOperationArgument>"
        "</scg:List>"
        "</ui:FilterDataTable.Filters>"
        "<ui:FilterDataTable.SelectColumns>"
        '<scg:List x:TypeArguments="InArgument" Capacity="4">'
        '<InArgument x:TypeArguments="x:String">["Name"]</InArgument>'
        '<InArgument x:TypeArguments="x:String">["Age"]</InArgument>'
        '<InArgument x:TypeArguments="x:String">["Salary"]</InArgument>'
        "</scg:List>"
        "</ui:FilterDataTable.SelectColumns>"
        "</ui:FilterDataTable>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, FilterDataTableNode)
    assert node.data_table == VbExpr(text="dt")
    assert node.output_data_table == VbExpr(text="dtProcessed")
    assert node.filter_rows_mode == "Keep"
    assert node.select_columns == [
        VbExpr(text='"Name"'),
        VbExpr(text='"Age"'),
        VbExpr(text='"Salary"'),
    ]
    assert len(node.filters) == 2
    assert node.filters[0].column == VbExpr(text='"Age"')
    assert node.filters[0].column_type == "x:String"
    assert node.filters[0].operand == VbExpr(text="60.0")
    assert node.filters[1].column == VbExpr(text='"Salary"')
    assert node.filters[1].operand == VbExpr(text="70000.0")


def test_join_data_tables_properties_with_duplicate_key_column():
    """知見208: 実機2件(`TharakaMadushankaWanshathilaka/UiPath-Demo-
    Data-Tables`・`SuatOzcan/UiPathRoboticProcessAutomation`)で確認した
    「蔵書(OverdueBooks)とユーザー(Users)を共通の'ID'列でInner結合する」
    構成——`BooleanOperator="And"`+`Operator="EQ"`+`Column1`/`Column2`
    両方`x:String`型。"""
    xml = (
        f"<ui:JoinDataTables {_SCG_XMLNS} "
        'DataTable1="[OverdueBooks]" DataTable2="[Users]" '
        'DisplayName="Join Data Tables" JoinType="Inner" '
        'OutputDataTable="[BarrowedBooks]">'
        "<ui:JoinDataTables.Arguments>"
        '<scg:List x:TypeArguments="ui:JoinOperationArgument" Capacity="4">'
        '<ui:JoinOperationArgument Operand="{x:Null}" BooleanOperator="And" '
        'Operator="EQ">'
        "<ui:JoinOperationArgument.Column1>"
        '<InArgument x:TypeArguments="x:String">["ID"]</InArgument>'
        "</ui:JoinOperationArgument.Column1>"
        "<ui:JoinOperationArgument.Column2>"
        '<InArgument x:TypeArguments="x:String">["ID"]</InArgument>'
        "</ui:JoinOperationArgument.Column2>"
        "</ui:JoinOperationArgument>"
        "</scg:List>"
        "</ui:JoinDataTables.Arguments>"
        "</ui:JoinDataTables>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, JoinDataTablesNode)
    assert node.data_table1 == VbExpr(text="OverdueBooks")
    assert node.data_table2 == VbExpr(text="Users")
    assert node.output_data_table == VbExpr(text="BarrowedBooks")
    assert node.join_type == "Inner"
    assert len(node.arguments) == 1
    arg = node.arguments[0]
    assert isinstance(arg, JoinOperationArgument)
    assert arg.boolean_operator == "And"
    assert arg.operator == "EQ"
    assert arg.column1 == VbExpr(text='"ID"')
    assert arg.column1_type == "x:String"
    assert arg.column2 == VbExpr(text='"ID"')
    assert arg.column2_type == "x:String"


def test_load_image_properties():
    """知見178: `ui:LoadImage`(GitHub code searchで58件ヒット、OCR系
    活動の入力として使われる)。実機`cameronmcnz/uipath-tutorials`で
    確認した`FileName="[file.ToString]"`+`Image="[memeImage]"`の
    実例。"""
    xml = (
        f"<ui:LoadImage {_UI_XMLNS} DisplayName=\"Load Image\" "
        'FileName="[file.ToString]" Image="[memeImage]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, LoadImageNode)
    assert node.file_name == VbExpr(text="file.ToString")
    assert node.image == VbExpr(text="memeImage")
    assert node.display_name == "Load Image"


def test_save_image_properties():
    """知見179: `ui:SaveImage`(`LoadImage`知見178の正反対)。実機
    `UiPath/Community.Activities`公式REFrameworkテンプレートで確認した
    `FileName="[io_FilePath]"`+`Image="[screenshot]"`の実例。"""
    xml = (
        f"<ui:SaveImage {_UI_XMLNS} DisplayName=\"Save screenshot\" "
        'FileName="[io_FilePath]" Image="[screenshot]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, SaveImageNode)
    assert node.file_name == VbExpr(text="io_FilePath")
    assert node.image == VbExpr(text="screenshot")
    assert node.display_name == "Save screenshot"


def test_take_screenshot_with_no_selector_properties():
    """知見179: `ui:TakeScreenshot`(`UiPath/Community.Activities`公式
    REFrameworkテンプレート)。実機で`Target`が`{x:Null}`(画面全体)の
    実例。"""
    xml = (
        f"<ui:TakeScreenshot {_UI_XMLNS} DisplayName=\"Take screenshot\" "
        'WaitBefore="{x:Null}" Screenshot="[screenshot]">'
        "<ui:TakeScreenshot.Target>"
        '<ui:Target Selector="{x:Null}" />'
        "</ui:TakeScreenshot.Target>"
        "</ui:TakeScreenshot>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, TakeScreenshotNode)
    assert node.selector is None
    assert node.wait_before is None
    assert node.screenshot == VbExpr(text="screenshot")
    assert node.display_name == "Take screenshot"


def test_take_screenshot_with_selector_properties():
    """実機`spritlesoftware/Uipath-RPA-AutomationProjects`で確認した、
    セレクタ指定の実例。"""
    xml = (
        f"<ui:TakeScreenshot {_UI_XMLNS} DisplayName=\"Take Screenshot 'Desktop'\" "
        'Screenshot="[screenShot]">'
        "<ui:TakeScreenshot.Target>"
        "<ui:Target Selector=\"&lt;wnd app='explorer.exe' cls='WorkerW' /&gt;\" />"
        "</ui:TakeScreenshot.Target>"
        "</ui:TakeScreenshot>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, TakeScreenshotNode)
    assert "WorkerW" in node.selector
    assert node.screenshot == VbExpr(text="screenShot")


def test_get_ocr_text_google_ocr_engine_properties():
    """知見180: `ui:GetOCRText`。`OCREngine`デリゲートが`ui:GoogleOCR`
    (UiPath公式ドキュメントで「Tesseract OCR」と確認済み)をラップする
    実例——実機`PacktPublishing/Robotic-Process-Automation-RPA-for-
    Developers`で確認した`Language="eng"`+`Scale="1"`の実例。"""
    xml = (
        f"<ui:GetOCRText {_UI_XMLNS} DisplayName=\"Get OCR Text\">"
        "<ui:GetOCRText.OCREngine>"
        '<ActivityFunc x:TypeArguments="sd:Image">'
        '<ActivityFunc.Argument>'
        '<DelegateInArgument x:TypeArguments="sd:Image" Name="Image" />'
        "</ActivityFunc.Argument>"
        '<ui:GoogleOCR Language="eng" Scale="1" Image="[Image]" />'
        "</ActivityFunc>"
        "</ui:GetOCRText.OCREngine>"
        "<ui:GetOCRText.Target>"
        '<ui:Target Selector="{x:Null}" />'
        "</ui:GetOCRText.Target>"
        "<ui:GetOCRText.Text>"
        '<OutArgument x:TypeArguments="ui:GenericValue">[result]</OutArgument>'
        "</ui:GetOCRText.Text>"
        "</ui:GetOCRText>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, GetOcrTextNode)
    assert node.engine_tag == "GoogleOCR"
    assert node.language == Literal(value="eng")
    assert node.scale == "1"
    assert node.text == VbExpr(text="result")
    assert node.selector is None


def test_get_ocr_text_normalizes_x_null_scale_to_none():
    """実機で確認した`Scale="{x:Null}"`——`_attr`が`{x:Null}`正規化を
    行わないフラット文字列属性(知見172と同種のバグを避ける、新しい
    `_attr_or_none`ヘルパーで対応)。"""
    xml = (
        f"<ui:GetOCRText {_UI_XMLNS} DisplayName=\"Get OCR Text\">"
        "<ui:GetOCRText.OCREngine>"
        '<ActivityFunc x:TypeArguments="sd:Image">'
        '<ActivityFunc.Argument>'
        '<DelegateInArgument x:TypeArguments="sd:Image" Name="Image" />'
        "</ActivityFunc.Argument>"
        '<ui:GoogleOCR Scale="{x:Null}" Profile="{x:Null}" Image="[Image]" />'
        "</ActivityFunc>"
        "</ui:GetOCRText.OCREngine>"
        "<ui:GetOCRText.Text>"
        '<OutArgument x:TypeArguments="ui:GenericValue">[result]</OutArgument>'
        "</ui:GetOCRText.Text>"
        "</ui:GetOCRText>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, GetOcrTextNode)
    assert node.scale is None
    assert node.profile is None


def test_get_ocr_text_with_microsoft_ocr_engine():
    """実機で確認した`ui:MicrosoftOCR`(71件ヒット、Tesseractとは別の
    エンジン)——タグ名をそのまま保持し、未確認のまま`# TODO`へ倒せる
    ようにする。"""
    xml = (
        f"<ui:GetOCRText {_UI_XMLNS} DisplayName=\"Get OCR Text\">"
        "<ui:GetOCRText.OCREngine>"
        '<ActivityFunc x:TypeArguments="sd:Image">'
        '<ActivityFunc.Argument>'
        '<DelegateInArgument x:TypeArguments="sd:Image" Name="Image" />'
        "</ActivityFunc.Argument>"
        '<ui:MicrosoftOCR Image="[Image]" />'
        "</ActivityFunc>"
        "</ui:GetOCRText.OCREngine>"
        "<ui:GetOCRText.Text>"
        '<OutArgument x:TypeArguments="ui:GenericValue">[result]</OutArgument>'
        "</ui:GetOCRText.Text>"
        "</ui:GetOCRText>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, GetOcrTextNode)
    assert node.engine_tag == "MicrosoftOCR"


def test_add_data_row_properties():
    """知見181: `ui:AddDataRow`(GitHub code searchで2120件ヒット——
    `BuildDataTable`直後に続く定番パターン)。実機`cameronmcnz/
    uipath-tutorials`で確認した`ArrayRow="[{&quot;Hello World&quot;, -1}]"`
    の実例。"""
    xml = (
        f"<ui:AddDataRow {_UI_XMLNS} DisplayName=\"Add Data Row\" "
        'DataRow="{x:Null}" ArrayRow="[{&quot;Hello World&quot;, -1}]" '
        'DataTable="[MyDataTable]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, AddDataRowNode)
    assert node.array_row == VbExpr(text='{"Hello World", -1}')
    assert node.data_row is None
    assert node.data_table == VbExpr(text="MyDataTable")
    assert node.display_name == "Add Data Row"


def test_remove_data_row_with_row_index_properties():
    """知見182: `ui:RemoveDataRow`(`AddDataRow`知見181の正反対)。実機
    `samaypatel27/Stock-Market-Scrapper`で確認した`RowIndex="0"`
    (読み込んだヘッダー行を削除する定番パターン)の実例。"""
    xml = (
        f"<ui:RemoveDataRow {_UI_XMLNS} DisplayName=\"Removes Heading row\" "
        'Row="{x:Null}" RowIndex="0" DataTable="[read2_dt]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, RemoveDataRowNode)
    assert node.data_table == VbExpr(text="read2_dt")
    assert node.row is None
    assert node.row_index == Literal(value="0")
    assert node.display_name == "Removes Heading row"


def test_remove_data_row_with_row_properties():
    """実機`UiPath-Services/OrchestratorManager`で確認した、複雑なLINQ式
    `Row`の実例。"""
    xml = (
        f"<ui:RemoveDataRow {_UI_XMLNS} DisplayName=\"Remove Data Row\" "
        'RowIndex="{x:Null}" DataTable="[io_UsersData]" '
        'Row="[io_UsersData.AsEnumerable().Where(Function(Row) Convert.ToInt64(Row(&quot;ID&quot;)) = UserID).First()]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, RemoveDataRowNode)
    assert node.row_index is None
    assert "AsEnumerable" in node.row.text


def test_get_row_item_with_column_name_properties():
    """知見183: `ui:GetRowItem`(実機6件全てが`ColumnName`を使用)。
    実機`cameronmcnz/uipath-tutorials`で確認した
    `ColumnName="lastname"`の実例。"""
    xml = (
        f"<ui:GetRowItem {_UI_XMLNS} DisplayName=\"Get Row Item\" "
        'Column="{x:Null}" ColumnIndex="{x:Null}" ColumnName="lastname" '
        'Row="[row]">'
        "<ui:GetRowItem.Value>"
        '<OutArgument x:TypeArguments="x:String">[output]</OutArgument>'
        "</ui:GetRowItem.Value>"
        "</ui:GetRowItem>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, GetRowItemNode)
    assert node.row == VbExpr(text="row")
    assert node.column_name == Literal(value="lastname")
    assert node.column_index is None
    assert node.column is None
    assert node.value == VbExpr(text="output")


def test_clear_data_table_properties():
    """知見184: `ui:ClearDataTable`(GitHub code searchで225件ヒット)。
    実機`jeffdnganga/DSRIncentivesPostingPerformer`で確認した
    `DataTable="[dt_invoicePostingResults]"`の実例——`DataTable`のみの
    最も単純な構成。"""
    xml = (
        f"<ui:ClearDataTable {_UI_XMLNS} DisplayName=\"Clear Data Table\" "
        'DataTable="[dt]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ClearDataTableNode)
    assert node.data_table == VbExpr(text="dt")
    assert node.display_name == "Clear Data Table"


def test_output_data_table_properties():
    """知見184: `ui:OutputDataTable`(GitHub code searchで894件ヒット)。
    実機`vajrang-b/UiPathIn30Days`で確認した`Text="[Out_Str]"`の
    実例。"""
    xml = (
        f"<ui:OutputDataTable {_UI_XMLNS} DisplayName=\"Output Data Table\" "
        'DataTable="[Out_DT]" Text="[Out_Str]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, OutputDataTableNode)
    assert node.data_table == VbExpr(text="Out_DT")
    assert node.text == VbExpr(text="Out_Str")


def test_add_data_column_properties():
    """知見198: `ui:AddDataColumn`(GitHub code searchで856件ヒット)。
    実機`HarshadRanganathan/uipath-learning`で確認した`AllowDBNull`/
    `AutoIncrement`/`MaxLength`/`Unique`が明示的な値を持つ実例。"""
    xml = (
        f"<ui:AddDataColumn {_UI_XMLNS} x:TypeArguments=\"x:Object\" "
        'Column="{x:Null}" DefaultValue="{x:Null}" AllowDBNull="True" '
        'AutoIncrement="False" ColumnName="C" DataTable="[dt]" '
        'DisplayName="Add data column" MaxLength="100" Unique="False" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, AddDataColumnNode)
    assert node.data_table == VbExpr(text="dt")
    assert node.column_name == Literal(value="C")
    assert node.allow_db_null == "True"
    assert node.auto_increment == "False"
    assert node.unique == "False"
    assert node.column is None
    assert node.default_value is None


def test_remove_data_column_properties():
    """知見198: `ui:RemoveDataColumn`(GitHub code searchで273件
    ヒット、`AddDataColumn`の正反対)。実機`cameronmcnz/uipath-
    tutorials`で確認した実例。"""
    xml = (
        f"<ui:RemoveDataColumn {_UI_XMLNS} Column=\"{{x:Null}}\" "
        'ColumnIndex="{x:Null}" ColumnName="firstname" '
        'DataTable="[input]" DisplayName="Remove Data Column" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, RemoveDataColumnNode)
    assert node.data_table == VbExpr(text="input")
    assert node.column_name == Literal(value="firstname")
    assert node.column is None
    assert node.column_index is None


def test_read_csv_file_properties():
    """知見185: `ui:ReadCsvFile`(`UiPath.Excel.Activities`名前空間、
    GitHub code searchで657件ヒット)。実機`HarshadRanganathan/
    uipath-learning`で確認した`FilePath="[csvpath]"`の実例。"""
    xml = (
        f"<ui:ReadCsvFile {_UI_XMLNS} DisplayName=\"Read CSV\" "
        'Encoding="{x:Null}" FilePath="[csvpath]" DataTable="[dataTable]" '
        'Delimitator="Comma" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ReadCsvFileNode)
    assert node.file_path == VbExpr(text="csvpath")
    assert node.data_table == VbExpr(text="dataTable")
    assert node.delimitator == "Comma"
    assert node.encoding is None
    assert node.path_resource is None


def test_read_pdf_text_with_range_all():
    """知見199: `ui:ReadPDFText`(GitHub code searchで539件ヒット)。
    実機`marcelocruzrpa/uipath-ai-skills`で確認した`Range="All"`の
    実例。"""
    xml = (
        f"<ui:ReadPDFText {_UI_XMLNS} PreserveFormatting=\"{{x:Null}}\" "
        'DisplayName="Read PDF Text" FileName="[CurrentFile.FullName]" '
        'Range="All" Text="[strInvoiceText]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ReadPdfTextNode)
    assert node.file_name == VbExpr(text="CurrentFile.FullName")
    assert node.text == VbExpr(text="strInvoiceText")
    assert node.range == Literal(value="All")
    assert node.preserve_formatting is None


def test_read_pdf_text_with_single_page_range():
    """知見199: 実機`PacktPublishing/Robotic-Process-Automation-RPA-
    for-Developers`で確認した単一ページ番号`Range="2"`の実例。"""
    xml = (
        f"<ui:ReadPDFText {_UI_XMLNS} DisplayName=\"Read PDF Text\" "
        'FileName="inputs/PDF/RPA.pdf" Range="2" Text="[pdfText]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ReadPdfTextNode)
    assert node.range == Literal(value="2")


_PDF_XMLNS = 'xmlns:upap="clr-namespace:UiPath.PDF.Activities.PDF;assembly=UiPath.PDF.Activities"'


def test_get_pdf_page_count_properties():
    """知見200: `GetPDFPageCount`(`upap:`名前空間——知見193で発見した
    `clr-namespace:UiPath.PDF.Activities.PDF;assembly=UiPath.PDF.
    Activities`)。実機`vajrang-b/UiPathIn30Days`で確認した実例。"""
    xml = (
        f"<upap:GetPDFPageCount {_PDF_XMLNS} "
        'DisplayName="Get PDF Page Count" FileName="Sample PDF file.pdf" '
        'PageCount="[Pdf_PageCount1]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, GetPdfPageCountNode)
    assert node.file_name == Literal(value="Sample PDF file.pdf")
    assert node.page_count == VbExpr(text="Pdf_PageCount1")


def test_extract_pdf_page_range_properties():
    """知見200: `ExtractPDFPageRange`(`GetPDFPageCount`と同じ`upap:`
    名前空間)。実機`vajrang-b/UiPathIn30Days`で確認した
    `Range="8-22"`の実例。"""
    xml = (
        f"<upap:ExtractPDFPageRange {_PDF_XMLNS} "
        'DisplayName="Extract PDF Page Range" FileName="Sample PDF file.pdf" '
        'OutputFileName="Sample PDF file pages 8 to 22.pdf" Range="8-22" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ExtractPdfPageRangeNode)
    assert node.file_name == Literal(value="Sample PDF file.pdf")
    assert node.output_file_name == Literal(value="Sample PDF file pages 8 to 22.pdf")
    assert node.range == Literal(value="8-22")


def test_join_pdf_properties():
    """知見201: `JoinPDF`(`GetPDFPageCount`/`ExtractPDFPageRange`
    知見200と同じ`upap:`名前空間)。実機`vajrang-b/UiPathIn30Days`で
    確認したVB.NET配列リテラル構文の`FileList`の実例。"""
    xml = (
        f"<upap:JoinPDF {_PDF_XMLNS} DisplayName=\"Join PDF Files\" "
        'FileList="[{&quot;PDF Sample2.pdf&quot;,&quot;Sample PDF file.pdf&quot;}]" '
        'OutputFileName="Combined PDF File.pdf" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, JoinPdfNode)
    assert node.file_list == VbExpr(text='{"PDF Sample2.pdf","Sample PDF file.pdf"}')
    assert node.output_file_name == Literal(value="Combined PDF File.pdf")


def test_export_pdf_page_as_image_properties_with_dynamic_page_number():
    """知見209: `ExportPDFPageAsImage`(`GetPDFPageCount`/
    `ExtractPDFPageRange`/`JoinPDF`知見200・201と同じ`upap:`名前空間)。
    実機`Sundsvallskommun/RPA_Sammanstallning-av-PDF`(実在のスウェーデン
    自治体のRPAリポジトリ)で確認した構成——`PageNumber`が動的な
    `[Index]`、`OutputFileName`が文字列連結式。"""
    xml = (
        f"<upap:ExportPDFPageAsImage {_PDF_XMLNS} "
        'DisplayName="Export PDF Page As Image" FileName="[FilePathPDF]" '
        'ImageDpi="150" OutputFileName="[TempMergeFolderPath + '
        "&quot;tempImage&quot; + Index.ToString + &quot;.jpeg&quot;]\" "
        'PageNumber="[Index]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ExportPdfPageAsImageNode)
    assert node.file_name == VbExpr(text="FilePathPDF")
    assert node.output_file_name == VbExpr(
        text='TempMergeFolderPath + "tempImage" + Index.ToString + ".jpeg"'
    )
    assert node.page_number == VbExpr(text="Index")
    assert node.image_dpi == "150"


def test_export_pdf_page_as_image_properties_with_literal_page_number():
    """知見209: 実機`vajrang-b/UiPathIn30Days`で確認した、全て静的な
    リテラル属性の構成。"""
    xml = (
        f"<upap:ExportPDFPageAsImage {_PDF_XMLNS} "
        'DisplayName="PDF Document to image" FileName="sample.pdf" '
        'ImageDpi="150" OutputFileName="Output\\pdfimage.png" '
        'PageNumber="1" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ExportPdfPageAsImageNode)
    assert node.file_name == Literal(value="sample.pdf")
    assert node.output_file_name == Literal(value="Output\\pdfimage.png")
    assert node.page_number == Literal(value="1")
    assert node.image_dpi == "150"


def test_extract_images_from_pdf_properties():
    """知見209: `ExtractImagesFromPDF`(`ExportPDFPageAsImage`等と同じ
    `upap:`名前空間)。実機`vajrang-b/UiPathIn30Days`で確認した構成
    ——`ImageExtension`属性は一度も確認できなかった。"""
    xml = (
        f"<upap:ExtractImagesFromPDF {_PDF_XMLNS} "
        'DisplayName="Extract Images From PDF document" '
        'FileName="SamplePdf1_12mb_6pages (1).pdf" OutputFolderName="Output" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ExtractImagesFromPdfNode)
    assert node.file_name == Literal(value="SamplePdf1_12mb_6pages (1).pdf")
    assert node.output_folder_name == Literal(value="Output")
    assert node.image_extension is None


def test_manage_pdf_password_with_new_owner_password():
    """知見202: `ManagePDFPassword`(`GetPDFPageCount`/
    `ExtractPDFPageRange`/`JoinPDF`知見200・201と同じ`upap:`名前空間)。
    実機`vajrang-b/UiPathIn30Days`で確認した`NewOwnerPassword`単独
    使用の実例。"""
    xml = (
        f"<upap:ManagePDFPassword {_PDF_XMLNS} "
        'DisplayName="Manage PDF Password" '
        'FileName="SamplePdf1_12mb_6pages (1).pdf" NewOwnerPassword="1234" '
        'OutputFileName="output\\password.pdf" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ManagePdfPasswordNode)
    assert node.file_name == Literal(value="SamplePdf1_12mb_6pages (1).pdf")
    assert node.new_owner_password == Literal(value="1234")
    assert node.new_user_password is None
    assert node.old_user_password is None
    assert node.old_owner_password is None


def test_manage_pdf_password_with_new_user_password():
    """知見202: 実機`vajrang-b/UiPathIn30Days`で確認した
    `NewUserPassword`単独使用の実例。"""
    xml = (
        f"<upap:ManagePDFPassword {_PDF_XMLNS} "
        'DisplayName="Manage PDF Password for security for current file." '
        'FileName="SamplePdf1_12mb_6pages (1).pdf" NewUserPassword="1234" '
        'OutputFileName="Output\\password.pdf" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ManagePdfPasswordNode)
    assert node.new_user_password == Literal(value="1234")
    assert node.new_owner_password is None


def test_write_csv_file_properties():
    """知見185: `ui:WriteCsvFile`(`ReadCsvFile`の正反対)。実機
    `allenlooplee/RPABook`で確認した実例。"""
    xml = (
        f"<ui:WriteCsvFile {_UI_XMLNS} DisplayName=\"Write CSV\" "
        'Encoding="{x:Null}" AddHeaders="True" DataTable="[TestData]" '
        'Delimitator="Comma" FilePath="out.csv" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, WriteCsvFileNode)
    assert node.file_path == Literal(value="out.csv")
    assert node.data_table == VbExpr(text="TestData")
    assert node.add_headers == "True"
    assert node.delimitator == "Comma"


def test_invoke_powershell_properties():
    """知見186: `ui:InvokePowerShell`(GitHub code searchで337件
    ヒット)。実機`nestorzamili/RPA-Grafana-Kibana`で確認した
    `PowerShellProcess="PowerShellCore"`+空の`Parameters`/
    `PowerShellVariables`の実例。"""
    xml = (
        f"<ui:InvokePowerShell {_UI_XMLNS} DisplayName=\"Invoke Power Shell\" "
        'ContinueOnError="{x:Null}" CommandText="node script.js" '
        'IsScript="True" PowerShellProcess="PowerShellCore">'
        "<ui:InvokePowerShell.Parameters>"
        '<scg:Dictionary xmlns:scg="clr-namespace:System.Collections.Generic;'
        'assembly=System.Private.CoreLib" x:TypeArguments="x:String, InArgument" />'
        "</ui:InvokePowerShell.Parameters>"
        "<ui:InvokePowerShell.PowerShellVariables>"
        '<scg:Dictionary xmlns:scg="clr-namespace:System.Collections.Generic;'
        'assembly=System.Private.CoreLib" x:TypeArguments="x:String, Argument" />'
        "</ui:InvokePowerShell.PowerShellVariables>"
        "</ui:InvokePowerShell>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, InvokePowerShellNode)
    assert node.command_text == Literal(value="node script.js")
    assert node.powershell_process == "PowerShellCore"
    assert node.is_script == "True"
    assert node.continue_on_error is None
    assert node.has_parameters is False
    assert node.has_powershell_variables is False


def test_invoke_powershell_with_non_empty_parameters():
    """実機で確認したことはないが、`Parameters`が空でない場合に
    正しく`has_parameters=True`になることを合成データで確認する。"""
    xml = (
        f"<ui:InvokePowerShell {_UI_XMLNS} DisplayName=\"Invoke Power Shell\" "
        'CommandText="Get-Process" PowerShellProcess="PowerShellCore">'
        "<ui:InvokePowerShell.Parameters>"
        '<scg:Dictionary xmlns:scg="clr-namespace:System.Collections.Generic;'
        'assembly=System.Private.CoreLib" x:TypeArguments="x:String, InArgument">'
        '<x:String x:Key="Name">[InArgument(GetType(x:String))]</x:String>'
        "</scg:Dictionary>"
        "</ui:InvokePowerShell.Parameters>"
        "</ui:InvokePowerShell>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, InvokePowerShellNode)
    assert node.has_parameters is True


def test_retry_scope_with_empty_condition_properties():
    """知見187: `ui:RetryScope`(GitHub code searchで3280件ヒット
    ——`UiPath/skills`公式リポジトリのREFramework標準サブワークフロー
    資産(`SetTransactionStatus.xaml`)で確認)。`Condition`が空の
    `ActivityFunc`で、`ActivityBody`が`ui:LogMessage`を1件持つ単純な
    実例。"""
    xml = (
        f"<ui:RetryScope {_UI_XMLNS} DisplayName=\"Retry\" "
        'NumberOfRetries="3">'
        "<ui:RetryScope.ActivityBody>"
        "<ActivityAction>"
        '<Sequence DisplayName="Action">'
        '<ui:LogMessage DisplayName="Log" Level="Info" Message="[&quot;x&quot;]" />'
        "</Sequence>"
        "</ActivityAction>"
        "</ui:RetryScope.ActivityBody>"
        "<ui:RetryScope.Condition>"
        '<ActivityFunc x:TypeArguments="x:Boolean" />'
        "</ui:RetryScope.Condition>"
        "</ui:RetryScope>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, RetryScopeNode)
    assert node.number_of_retries == Literal(value="3")
    assert node.condition_has_body is False
    assert node.retry_interval is None
    assert len(node.body) == 1
    assert isinstance(node.body[0], LogMessageNode)


def test_retry_scope_with_non_empty_condition():
    """実機`liamsrowley/UiPath-REFramework-CalculateClientSecurityHash`
    で確認した、Modern活動による要素状態チェックを含む非空の
    `Condition`の実例(合成データで再現)。"""
    xml = (
        f"<ui:RetryScope {_UI_XMLNS} DisplayName=\"Retry\" "
        'NumberOfRetries="3" RetryInterval="00:10:00">'
        "<ui:RetryScope.ActivityBody>"
        "<ActivityAction>"
        '<Sequence DisplayName="Action" />'
        "</ActivityAction>"
        "</ui:RetryScope.ActivityBody>"
        "<ui:RetryScope.Condition>"
        '<ActivityFunc x:TypeArguments="x:Boolean">'
        '<ui:LogMessage DisplayName="Check" Level="Info" Message="[&quot;x&quot;]" />'
        "</ActivityFunc>"
        "</ui:RetryScope.Condition>"
        "</ui:RetryScope>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, RetryScopeNode)
    assert node.condition_has_body is True
    assert node.retry_interval == Literal(value="00:10:00")


def test_move_file_properties():
    """知見188: `ui:MoveFile`(`CopyFile`知見117の正反対、GitHub code
    searchで575件ヒット)。実機`cameronmcnz/uipath-tutorials`で確認した
    実例。"""
    xml = (
        f"<ui:MoveFile {_UI_XMLNS} DisplayName=\"Move File\" "
        'ContinueOnError="{x:Null}" Overwrite="False" '
        'Path="[file.ToString]" Destination="processed" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, MoveFileNode)
    assert node.path == VbExpr(text="file.ToString")
    assert node.destination == Literal(value="processed")
    assert node.overwrite == "False"
    assert node.continue_on_error is None


def test_path_exists_with_file_path_type():
    """知見188: `ui:PathExists`(GitHub code searchで558件ヒット)。
    実機`PacktPublishing/Robotic-Process-Automation-Projects`で確認した
    `PathType="File"`の実例。"""
    xml = (
        f"<ui:PathExists {_UI_XMLNS} DisplayName=\"Path Exists\" "
        'Exists="[boolFileExists]" Path="[path]" PathType="File" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, PathExistsNode)
    assert node.path == VbExpr(text="path")
    assert node.exists == VbExpr(text="boolFileExists")
    assert node.path_type == "File"
    assert node.resource is None


def test_path_exists_with_folder_path_type():
    """実機`cristinegulescu/startUiPathFromSalesforce`で確認した
    `PathType="Folder"`の実例。"""
    xml = (
        f"<ui:PathExists {_UI_XMLNS} DisplayName=\"Path Exists\" "
        'Exists="[found]" Path="[folder]" PathType="Folder" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, PathExistsNode)
    assert node.path_type == "Folder"


def test_delete_file_properties():
    """知見189: `ui:DeleteFileX`(GitHub code searchで508件ヒット、全件
    `ui:DeleteFileX`——非X形は実機で一度も確認できず)。実機
    `vajrang-b/UiPathIn30Days`で確認した実例。"""
    xml = f'<ui:DeleteFileX {_UI_XMLNS} DisplayName="Delete File" Path="a.txt" />'
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, DeleteFileNode)
    assert node.path == Literal(value="a.txt")
    assert node.display_name == "Delete File"


def test_delete_folder_properties():
    """知見189: `ui:DeleteFolderX`(`DeleteFile`の兄弟活動、GitHub code
    searchで173件ヒット)。実機`happycodingandlife/UiPath-Generate-
    Yearly_Report_Performer`で確認した`Recursive="True"`の実例。"""
    xml = (
        f"<ui:DeleteFolderX {_UI_XMLNS} DisplayName=\"Delete Folder\" "
        'Path="[folder]" Recursive="True" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, DeleteFolderNode)
    assert node.path == VbExpr(text="folder")
    assert node.recursive == "True"


def test_for_each_file_properties():
    """知見190: `ui:ForEachFileX`(GitHub code searchで738件ヒット)。
    実機`marcelocruzrpa/uipath-ai-skills`資産(`PDFExtraction_Main.
    xaml`)で確認した、2変数デリゲート(`CurrentFile`/`CurrentIndex`)+
    `IncludeSubDirectories="True"`の実例。"""
    xml = (
        f"<ui:ForEachFileX {_UI_XMLNS} DisplayName=\"For Each File\" "
        'Folder="[folder]" IncludeSubDirectories="True" OrderBy="NameAscFirst">'
        "<ui:ForEachFileX.Body>"
        '<ActivityAction x:TypeArguments="si:FileInfo, x:Int32">'
        '<ActivityAction.Argument1>'
        '<DelegateInArgument x:TypeArguments="si:FileInfo" Name="CurrentFile" />'
        "</ActivityAction.Argument1>"
        '<ActivityAction.Argument2>'
        '<DelegateInArgument x:TypeArguments="x:Int32" Name="CurrentIndex" />'
        "</ActivityAction.Argument2>"
        '<Sequence DisplayName="Do" />'
        "</ActivityAction>"
        "</ui:ForEachFileX.Body>"
        "</ui:ForEachFileX>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ForEachFileNode)
    assert node.folder == VbExpr(text="folder")
    assert node.include_sub_directories == "True"
    assert node.order_by == "NameAscFirst"
    assert node.item_var == "CurrentFile"
    assert node.index_var == "CurrentIndex"
    assert node.body == []


def test_for_each_folder_properties():
    """知見190: `ui:ForEachFolderX`(`ForEachFile`の兄弟活動、GitHub
    code searchで40件ヒット)。"""
    xml = (
        f"<ui:ForEachFolderX {_UI_XMLNS} DisplayName=\"For Each Folder\" "
        'Folder="[folder]" IncludeSubFolders="False" OrderBy="NameAscFirst">'
        "<ui:ForEachFolderX.Body>"
        '<ActivityAction x:TypeArguments="si:DirectoryInfo, x:Int32">'
        '<ActivityAction.Argument1>'
        '<DelegateInArgument x:TypeArguments="si:DirectoryInfo" Name="CurrentFolder" />'
        "</ActivityAction.Argument1>"
        '<ActivityAction.Argument2>'
        '<DelegateInArgument x:TypeArguments="x:Int32" Name="CurrentIndex" />'
        "</ActivityAction.Argument2>"
        '<Sequence DisplayName="Do" />'
        "</ActivityAction>"
        "</ui:ForEachFolderX.Body>"
        "</ui:ForEachFolderX>"
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, ForEachFolderNode)
    assert node.folder == VbExpr(text="folder")
    assert node.include_sub_folders == "False"
    assert node.item_var == "CurrentFolder"
    assert node.index_var == "CurrentIndex"


def test_rename_file_properties():
    """知見191: `ui:RenameFileX`(GitHub code searchで123件ヒット
    ——`DeleteFileX`(知見189)と同じ「X」付きファイルシステム操作系
    活動ファミリー)。実機`KooBonchan/wine-bouti`で確認した
    `KeepExtension="True"`の実例。"""
    xml = (
        f"<ui:RenameFileX {_UI_XMLNS} DisplayName=\"Rename File\" "
        'FilePath="[path]" NewName="[newname]" KeepExtension="True" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, RenameFileNode)
    assert node.file_path == VbExpr(text="path")
    assert node.new_name == VbExpr(text="newname")
    assert node.keep_extension == "True"
    assert node.file_resource is None


def test_rename_folder_properties():
    """知見191: `ui:RenameFolderX`(`RenameFile`の兄弟活動)。実機
    `PakamTharunReddy/RPA`で確認した実例。"""
    xml = (
        f"<ui:RenameFolderX {_UI_XMLNS} DisplayName=\"Rename Folder\" "
        'FolderPath="dummy" NewName="Dummy" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, RenameFolderNode)
    assert node.folder_path == Literal(value="dummy")
    assert node.new_name == Literal(value="Dummy")


def test_create_file_properties():
    """知見191: `ui:CreateFile`(GitHub code searchで266件ヒット——
    `DeleteFileX`等とは違い非X形のまま)。実機`piyushagarwal08/JU-
    Notes`で確認した実例。"""
    xml = (
        f"<ui:CreateFile {_UI_XMLNS} DisplayName=\"Create File\" "
        'ContinueOnError="{x:Null}" Name="Anuj.txt" Path="C:/Hello/" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, CreateFileNode)
    assert node.path == Literal(value="C:/Hello/")
    assert node.name == Literal(value="Anuj.txt")
    assert node.output is None
    assert node.continue_on_error is None


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


def test_write_text_file_properties():
    """知見212: `ui:WriteTextFile`(`ReadTextFile`の対になる書き込み側)。
    実機3件(`PacktPublishing/Robotic-Process-Automation-RPA-for-
    Developers`・`spritlesoftware/Uipath-RPA-AutomationProjects`・
    `vajrang-b/UiPathIn30Days`)で確認した`FileName`+`Text`のみの構成
    ——`File`/`Output`は常に`{x:Null}`。"""
    xml = (
        f"<ui:WriteTextFile {_UI_XMLNS} "
        'DisplayName="Write Text File" FileName="outputs\\RPA.txt" '
        'Text="[pdfText]" />'
    )
    node = parse_activity(etree.fromstring(xml))
    assert isinstance(node, WriteTextFileNode)
    assert node.file_name == Literal(value="outputs\\RPA.txt")
    assert node.text == VbExpr(text="pdfText")
    assert node.file is None
    assert node.output is None


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
