"""UiPath `.xaml`(WFアクティビティ木のXML)を`uipath_dsl.types`のIRへ変換する
ツリーウォーカー。

`pad_dsl`のような「テキスト→トークン列→indentベースでブロック木」という
2段階パースは不要——XMLなので`lxml`で直接パースし、XML要素の親子関係を
そのままIRの親子関係に写す1段階変換になっている
(`dump_daemon/uipath_dsl/types.py`のモジュールdocstring参照)。

対話的セッション内の実行は前提にしない——ローカルの`.xaml`ファイルを直接
読むだけで完結する(PAD側の`clipwire`越しの実機操作が不要という、
design/uipath_xaml_findings.md 知見1の利点をそのまま活かす設計)。
"""
from __future__ import annotations

import re
from pathlib import Path

from lxml import etree

from .types import (
    ActivateNode,
    AppendLineNode,
    AssignNode,
    AttachWindowNode,
    BreakNode,
    BuildDataTableNode,
    CatchArm,
    CheckNode,
    ClickNode,
    CommentNode,
    CopyFileNode,
    DatabaseConnectNode,
    DatabaseDisconnectNode,
    DelayNode,
    DoWhileNode,
    Expr,
    ExcelApplicationScopeNode,
    ExcelAppendRangeNode,
    ExcelReadCellNode,
    ExcelReadRangeNode,
    ExcelWriteCellNode,
    ExcelWriteRangeNode,
    ExecuteNonQueryNode,
    ExecuteQueryNode,
    FlowchartNode,
    FlowDecisionNode,
    FlowNode,
    FlowStepNode,
    FlowSwitchArm,
    FlowSwitchNode,
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
    Literal,
    LogMessageNode,
    MessageBoxNode,
    MultipleAssignNode,
    Node,
    OpenApplicationNode,
    ParallelNode,
    ReadTextFileNode,
    RethrowNode,
    SelectItemNode,
    SendHotkeyNode,
    SendMailNode,
    SendOutlookMailNode,
    SequenceNode,
    SetToClipboardNode,
    SwitchArm,
    SwitchNode,
    TerminateWorkflowNode,
    ThrowNode,
    TryCatchNode,
    TypeIntoNode,
    UiElementExistsNode,
    UnknownActivityNode,
    VariableDecl,
    VbExpr,
    WhileNode,
    WordApplicationScopeNode,
    WordReplaceTextNode,
    WorkflowFile,
    WriteLineNode,
)

# 知見1〜36で確認済みの主要XML名前空間URI。
WF_NS = "http://schemas.microsoft.com/netfx/2009/xaml/activities"
UI_NS = "http://schemas.uipath.com/workflow/activities"
X_NS = "http://schemas.microsoft.com/winfx/2006/xaml"
SAP_NS = "http://schemas.microsoft.com/netfx/2009/xaml/activities/presentation"


def _split_tag(tag: str) -> tuple[str | None, str]:
    """lxmlの`{namespace-uri}localname`形式を`(namespace_uri, localname)`に分解する。
    無名前空間タグ(通常は無い)は`(None, tag)`。"""
    if tag.startswith("{"):
        ns, _, local = tag[1:].partition("}")
        return ns, local
    return None, tag


def _is_property_element(local_name: str) -> bool:
    """`<Assign.To>`/`<Sequence.Variables>`のようなプロパティ要素構文
    (ドット区切り)かどうか。実際の子アクティビティとの判別に使う——
    ドットを含む要素はプロパティ値であって子アクティビティではない。"""
    return "." in local_name


def _parse_expr(raw: str | None) -> Expr:
    """属性値/テキストノードをIRの`Expr`に変換する(知見13: `[...]`角括弧なら
    VB式、それ以外は生リテラル、`{x:Null}`/`None`は未設定)。"""
    if raw is None:
        return None
    if raw == "{x:Null}":
        return None
    stripped = raw.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        return VbExpr(text=stripped[1:-1])
    return Literal(value=raw)


def _attr(elem: etree._Element, name: str, ns: str | None = None) -> str | None:
    """名前空間付き/無し属性を取得する簡易ヘルパー。"""
    key = f"{{{ns}}}{name}" if ns else name
    return elem.get(key)


def _attr_expr(elem: etree._Element, name: str) -> Expr:
    return _parse_expr(_attr(elem, name))


def _direct_children(elem: etree._Element) -> list[etree._Element]:
    """コメント/処理命令を除いた直接の子要素。"""
    return [c for c in elem if isinstance(c.tag, str)]


def _find_property_element(
    elem: etree._Element, local_property_name: str
) -> etree._Element | None:
    """`<ParentTag.PropertyName>`形式の直接の子を探す(タグ名の一致は
    ローカル名のサフィックスで判定——親タグ名自体は名前空間プレフィックス
    込みで変わりうるため、`.PropertyName`で終わるかで見る)。"""
    for child in _direct_children(elem):
        _, local = _split_tag(child.tag)
        if local == local_property_name or local.endswith(f".{local_property_name}"):
            return child
    return None


def _activity_children(elem: etree._Element) -> list[etree._Element]:
    """プロパティ要素(ドット区切り)を除いた、実際の子アクティビティ要素。"""
    result = []
    for child in _direct_children(elem):
        _, local = _split_tag(child.tag)
        if _is_property_element(local):
            continue
        result.append(child)
    return result


def _parse_body(elem: etree._Element) -> list[Node]:
    """直接の子アクティビティ列をパースする(`Sequence`/`If.Then`等の中身)。"""
    return [parse_activity(child) for child in _activity_children(elem)]


def _single_body(elem: etree._Element | None) -> list[Node]:
    """`If.Then`/`If.Else`のように0〜1個の子を持ちうるプロパティ要素の中身を
    ノード列として返す(知見5: 複数ステップなら`Sequence`で自動ラップされる
    ので、ここではラップを解かずそのまま1要素のリストにする——呼び出し側が
    `SequenceNode`かどうかで複数ステップかを判断できる)。"""
    if elem is None:
        return []
    return _parse_body(elem)


def _parse_variable_default(var_elem: etree._Element) -> str | None:
    """`Variable.Default`の値を取得する。知見7が記録した2つの直列化形の
    両方に対応する——(1)本fixtureの実例である属性形(`Default="init"`)、
    (2)公式ドキュメント上は確認されているが本fixtureには実例が無かった
    子要素形(`<Variable.Default><Literal x:TypeArguments="...">init
    </Literal></Variable.Default>`)。後者は`Literal`要素の`.text`を使う
    (`Literal`自身の`x:TypeArguments`は変数本体の型と一致するはずという
    前提——実機で不一致の実例が出た場合は要再検討)。属性形が優先
    (両方が同時に存在する実例は無いはずだが、存在する場合は属性を信じる)。
    """
    attr_default = _attr(var_elem, "Default")
    if attr_default is not None:
        return attr_default
    default_elem = _find_property_element(var_elem, "Default")
    if default_elem is None:
        return None
    children = _direct_children(default_elem)
    if not children:
        return None
    return children[0].text


def _parse_variables(elem: etree._Element) -> list[VariableDecl]:
    """`Sequence.Variables`/`TryCatch.Variables`配下の`<Variable>`列。"""
    container = _find_property_element(elem, "Variables")
    if container is None:
        return []
    decls = []
    for var_elem in _direct_children(container):
        _, local = _split_tag(var_elem.tag)
        if local != "Variable":
            continue
        decls.append(
            VariableDecl(
                name=_attr(var_elem, "Name") or "",
                type_arguments=_attr(var_elem, "TypeArguments", X_NS)
                or _attr(var_elem, "TypeArguments")
                or "x:Object",
                default=_parse_variable_default(var_elem),
            )
        )
    return decls


def _parse_sequence(elem: etree._Element) -> SequenceNode:
    return SequenceNode(
        variables=_parse_variables(elem),
        body=_parse_body(elem),
        display_name=_attr(elem, "DisplayName"),
    )


def _find_sequence_child(elem: etree._Element) -> etree._Element | None:
    for child in _activity_children(elem):
        ns, local = _split_tag(child.tag)
        if (ns, local) == (WF_NS, "Sequence"):
            return child
    return None


def _unwrap_body_sequence(body_prop_elem: etree._Element | None) -> list[Node]:
    """`ForEach.Body`/`While.Body`/`DoWhile.Body`/`ExcelApplicationScope.Body`
    のように、本体が**常に**(ステップ数によらず、0個でも)`<Sequence
    DisplayName="Body"/"Do">`でラップされるコンテナ(知見22: `ForEach`と
    `ExcelApplicationScope`は`ActivityAction`+`DelegateInArgument`を共用する
    同型構造)向けのヘルパー。`If.Then`/`If.Else`(複数ステップの時だけ
    `Sequence`でラップされる可変長コンテナ、知見5)とは異なる挙動のため
    `_single_body`とは別関数にしている。

    ラップ用`Sequence`自身がローカル変数を宣言している場合(実機未確認だが
    文法上は可能)、その変数は現状の最小実装では読み捨てる——既知の簡略化。
    """
    if body_prop_elem is None:
        return []
    seq = _find_sequence_child(body_prop_elem)
    if seq is None:
        return _parse_body(body_prop_elem)
    return _parse_body(seq)


def _argument_text(prop_elem: etree._Element | None) -> str | None:
    """`<Assign.To><OutArgument ...>[result]</OutArgument></Assign.To>`の
    ように、プロパティ要素(`Assign.To`)自身ではなく**その子の`OutArgument`/
    `InArgument`要素**がテキストを持つ(プロパティ要素自身の`.text`は
    タグ間の空白のみ)。この子要素を見つけてその`.text`を返す。

    知見136: `OutArgument`/`InArgument`要素自身がテキストを持たず、
    代わりに`<CSharpReference>`/`<CSharpValue>`(知見129のC#式言語形)
    等のネストした子要素を持つ場合、`.text`はそのネスト要素の開始タグ
    直前の空白(改行+インデント)のみを返す——これを無視せずそのまま
    `Literal`の値として使うと、`'\n    ' = value`のような構文的に無効な
    Pythonコードを生成してしまう実害を`ShonHarsh/
    Wordle-Default-Word-Engine`の実機XAMLで発見した。テキストが空白のみ
    かつネストした子要素が存在する場合は、未対応の形として`None`を返し
    ——でっち上げた空白文字列を使わず、呼び出し元の既存の
    `# TODO`フォールバックに委ねる。"""
    if prop_elem is None:
        return None
    children = _direct_children(prop_elem)
    if not children:
        return None
    arg_elem = children[0]
    text = arg_elem.text
    if text is not None and text.strip() == "" and _direct_children(arg_elem):
        return None
    return text


def _parse_assign(elem: etree._Element) -> AssignNode:
    to_elem = _find_property_element(elem, "To")
    value_elem = _find_property_element(elem, "Value")
    target = _parse_expr(_argument_text(to_elem))
    value = _parse_expr(_argument_text(value_elem))
    return AssignNode(target=target, value=value)


def _parse_multiple_assign(elem: etree._Element) -> MultipleAssignNode:
    """知見122: `ui:MultipleAssign.AssignOperations`配下の`scg:List
    <ui:AssignOperation>`。各`AssignOperation`の`.To`/`.Value`は単一の
    `Assign`(`_parse_assign`)と全く同じ構造——同じ`_argument_text`
    ヘルパーをそのまま再利用する。"""
    ops_elem = _find_property_element(elem, "AssignOperations")
    assignments: list[AssignNode] = []
    if ops_elem is not None:
        for list_elem in _direct_children(ops_elem):
            for op_elem in _direct_children(list_elem):
                to_elem = _find_property_element(op_elem, "To")
                value_elem = _find_property_element(op_elem, "Value")
                target = _parse_expr(_argument_text(to_elem))
                value = _parse_expr(_argument_text(value_elem))
                assignments.append(AssignNode(target=target, value=value))
    return MultipleAssignNode(assignments=assignments, display_name=_attr(elem, "DisplayName"))


def _parse_message_box(elem: etree._Element) -> MessageBoxNode:
    return MessageBoxNode(
        text=_attr_expr(elem, "Text"),
        caption=_attr_expr(elem, "Caption"),
        buttons=_attr(elem, "Buttons"),
        chosen_button=_attr_expr(elem, "ChosenButton"),
    )


def _parse_input_dialog(elem: etree._Element) -> InputDialogNode:
    return InputDialogNode(
        title=_attr_expr(elem, "Title"),
        label=_attr_expr(elem, "Label"),
        is_password=_attr(elem, "IsPassword"),
        options=_attr_expr(elem, "Options"),
        result=_in_argument_property_expr(elem, "Result"),
        display_name=_attr(elem, "DisplayName"),
    )


def _parse_if(elem: etree._Element) -> IfNode:
    then_elem = _find_property_element(elem, "Then")
    else_elem = _find_property_element(elem, "Else")
    return IfNode(
        condition=_condition_expr(elem, "Condition"),
        then_body=_single_body(then_elem),
        else_body=_single_body(else_elem),
    )


def _find_activity_action(elem: etree._Element) -> etree._Element | None:
    for child in _direct_children(elem):
        _, local = _split_tag(child.tag)
        if local == "ActivityAction":
            return child
    return None


def _parse_for_each(elem: etree._Element) -> ForEachNode:
    """`ui:ForEach`(知見5、`.Body`配下に`ActivityAction`+
    `DelegateInArgument`)と基本WF版`System.Activities.Statements.
    ForEach<T>`(知見155)の両方を扱う——後者は`Body`がContent
    Property(`.NET`のXAMLで省略可能な唯一のプロパティ)のため、
    `<ForEach.Body>`での明示ラップと、`<ForEach>`直下に`ActivityAction`
    を直接子として置く暗黙形の両方が実機で確認済み(`R1zzabh/
    signalforge`は前者、`plaah/web-application-with-rpa-dhl`・
    `rufoabrahamguyo/sow-calix`・`NihadVeliyev/Student-Placement-
    Eligibility-Automation-using-UiPath-and-Excel`・`EnnioArnold/
    Dispatcher-Framework`は後者)。`.Body`が見つからない場合は`elem`
    自身の直接の子から`ActivityAction`を探すフォールバックで両形式に
    対応する。"""
    body_elem = _find_property_element(elem, "Body")
    if body_elem is None:
        body_elem = elem
    action = _find_activity_action(body_elem)
    item_var = ""
    body: list[Node] = []
    if action is not None:
        arg_elem = _find_property_element(action, "Argument")
        if arg_elem is not None:
            for d in _direct_children(arg_elem):
                item_var = _attr(d, "Name") or ""
        body = _unwrap_body_sequence(action)
    return ForEachNode(
        item_var=item_var,
        values=_attr_expr(elem, "Values"),
        body=body,
        type_arguments=_attr(elem, "TypeArguments", X_NS) or "x:Object",
    )


def _parse_for_each_row(elem: etree._Element) -> ForEachNode:
    """知見118: `ui:ForEachRow`(`UiPath.System.Activities`、`SuneetPatil/
    IRCTC-tatkal-booking`等の実機XAMLで発見)。`ui:ForEach`(知見5)と
    直接の子要素構造が全く同じ(`.Body`→`ActivityAction`+
    `DelegateInArgument`→`Sequence`)で、唯一の違いは反復対象を指す属性名
    (`Values`ではなく`DataTable`)——意味論も「反復対象の各要素を
    `item_var`へ束縛してbodyを実行する」で完全に同じ(`DataTable`は
    `list[dict]`表現、知見114・115で確立)のため、既存の`ForEachNode`/
    `_generate_for_each`をそのまま再利用する(新しいノード型・生成関数は
    不要)。`TypeArguments`は実機で`sd:DataRow`固定だったが、`ForEachNode.
    type_arguments`自体はコード生成に影響しない(デバッグ情報としての
    保持のみ)ため、確認済みの値のままそのまま使う。"""
    body_elem = _find_property_element(elem, "Body")
    action = _find_activity_action(body_elem) if body_elem is not None else None
    item_var = ""
    body: list[Node] = []
    if action is not None:
        arg_elem = _find_property_element(action, "Argument")
        if arg_elem is not None:
            for d in _direct_children(arg_elem):
                item_var = _attr(d, "Name") or ""
        body = _unwrap_body_sequence(action)
    return ForEachNode(
        item_var=item_var,
        values=_attr_expr(elem, "DataTable"),
        body=body,
        type_arguments=_attr(elem, "TypeArguments", X_NS) or "sd:DataRow",
    )


def _parse_try_catch(elem: etree._Element) -> TryCatchNode:
    catches_elem = _find_property_element(elem, "Catches")
    catches: list[CatchArm] = []
    if catches_elem is not None:
        for catch_elem in _direct_children(catches_elem):
            _, local = _split_tag(catch_elem.tag)
            if local != "Catch":
                continue
            exc_type = _attr(catch_elem, "TypeArguments", X_NS) or _attr(
                catch_elem, "TypeArguments"
            ) or ""
            action = _find_activity_action(catch_elem)
            var_name = None
            body: list[Node] = []
            if action is not None:
                arg_elem = _find_property_element(action, "Argument")
                if arg_elem is not None:
                    for d in _direct_children(arg_elem):
                        var_name = _attr(d, "Name")
                handler = _find_property_element(action, "Handler")
                body = _single_body(handler)
            catches.append(CatchArm(exception_type=exc_type, var_name=var_name, body=body))
    finally_elem = _find_property_element(elem, "Finally")
    return TryCatchNode(
        try_body=_single_body(_find_property_element(elem, "Try")),
        variables=_parse_variables(elem),
        catches=catches,
        finally_body=_single_body(finally_elem),
    )


def _parse_switch(elem: etree._Element) -> SwitchNode:
    """`Switch`の`case`群は`IDictionary<TKey, Activity>`(知見21、`x:Key`は
    アクティビティ要素自身の属性)だが、`Default`は辞書のキーではなく
    .NETの`Switch<T>.Default`という**別のプロパティ**で、`<Switch.Default>`
    というプロパティ要素として直列化される(知見40で実機確認——当初は
    `Default`も何らかの特別な`x:Key`を持つ辞書エントリだろうと誤って
    仮定しており、`_activity_children()`がプロパティ要素を除外するため
    `<Switch.Default>`配下の活動が完全に無言で読み捨てられるバグがあった)。
    """
    arms: list[SwitchArm] = []
    default_elem = _find_property_element(elem, "Default")
    if default_elem is not None:
        default_children = _direct_children(default_elem)
        if default_children:
            arms.append(SwitchArm(key=None, body=[parse_activity(default_children[0])]))
    for child in _activity_children(elem):
        key = _attr(child, "Key", X_NS) or _attr(child, "Key")
        arms.append(SwitchArm(key=key, body=[parse_activity(child)]))
    return SwitchNode(
        expression=_condition_expr(elem, "Expression"),
        type_arguments=_attr(elem, "TypeArguments", X_NS) or _attr(elem, "TypeArguments") or "",
        arms=arms,
    )


def _condition_expr(elem: etree._Element, attr_name: str) -> Expr:
    """知見122: `Condition`は通常`[...]`角括弧の属性形(`_attr_expr`、
    知見14で確認済みの「角括弧式の正体は`VisualBasicValue`の省略記法」
    という理解の通り)だが、`cameronmcnz/uipath-tutorials`の実機XAMLで
    `<X.Condition><mva:VisualBasicValue ExpressionText="..." />
    </X.Condition>`という、省略されない要素形そのものに実際に出会った
    ——`ExpressionText`は角括弧無しの生のVB式テキストを保持する。属性形
    が無い場合のみこの要素形へフォールバックする。"""
    direct = _attr_expr(elem, attr_name)
    if direct is not None:
        return direct
    prop_elem = _find_property_element(elem, attr_name)
    if prop_elem is None:
        return None
    for child in _direct_children(prop_elem):
        _, local = _split_tag(child.tag)
        if local == "VisualBasicValue":
            text = _attr(child, "ExpressionText")
            if text is not None:
                return VbExpr(text=text)
    return None


def _parse_while(elem: etree._Element) -> WhileNode:
    body_elem = _find_property_element(elem, "Body")
    return WhileNode(
        condition=_condition_expr(elem, "Condition"), body=_unwrap_body_sequence(body_elem)
    )


def _parse_do_while(elem: etree._Element) -> DoWhileNode:
    body_elem = _find_property_element(elem, "Body")
    return DoWhileNode(
        condition=_condition_expr(elem, "Condition"), body=_unwrap_body_sequence(body_elem)
    )


def _parse_parallel(elem: etree._Element) -> ParallelNode:
    return ParallelNode(branches=[parse_activity(c) for c in _activity_children(elem)])


def _cursor_offset(cursor_elem: etree._Element, attr_name: str) -> str | None:
    """知見105: `OffsetX`/`OffsetY`は属性形(`OffsetX="5"`)と、プロパティ
    要素形(`<CursorPosition.OffsetX><InArgument x:TypeArguments="x:Int32"
    /></CursorPosition.OffsetX>`、`InArgument`が空なら未設定)の両方が
    実機で確認済み(`PacktPublishing/Robotic-Process-Automation-Projects`
    の実例)。"""
    direct = _attr(cursor_elem, attr_name)
    if direct is not None:
        return direct
    prop_elem = _find_property_element(cursor_elem, attr_name)
    if prop_elem is None:
        return None
    children = _direct_children(prop_elem)
    if not children:
        return None
    return children[0].text


def _target_selector(elem: etree._Element) -> str | None:
    """知見163: `<X.Target><ui:Target Selector="..." /></X.Target>`から
    `Selector`属性を取得する共通ヘルパー——`Click`/`Hover`/`Activate`/
    `TypeInto`/`TypeSecureText`/`SendHotkey`/`GetText`/`GetFullText`/
    `SelectItem`/`UiElementExists`の10箇所で同一のインライン実装が
    重複していた(バグ修正+重複解消を1回で行う、知見133・141と同じ
    パターン)。知見128のStudio実機ground-truthコーパス(`Activate.xaml`
    等)で`Selector="{x:Null}"`(未設定)という実例を発見した際、
    重複していた10箇所全てが`_parse_expr`(知見13の`{x:Null}`→
    `None`正規化規約)を経由せず`_attr()`で生テキストを直接読んでいた
    ため、この規約から漏れて`selector`に文字列`"{x:Null}"`がそのまま
    残っていた(本来`None`であるべき値が真値として`if not node.
    selector:`判定を素通りし、`# TODO: ... had no mappable attributes:
    {x:Null}`という紛らわしい文言になっていた——でっち上げではない
    ため動作は安全側のままだったが、`None`の場合の「no selector
    captured」という分かりやすい文言には倒れていなかった)。"""
    target_prop = _find_property_element(elem, "Target")
    if target_prop is None:
        return None
    selector = None
    for child in _direct_children(target_prop):
        _, local = _split_tag(child.tag)
        if local == "Target":
            selector = _attr(child, "Selector")
    if selector == "{x:Null}":
        return None
    return selector


def _parse_click(elem: etree._Element) -> ClickNode:
    selector = _target_selector(elem)
    cursor_position = None
    cursor_offset_x = None
    cursor_offset_y = None
    cursor_position_prop = _find_property_element(elem, "CursorPosition")
    if cursor_position_prop is not None:
        for child in _direct_children(cursor_position_prop):
            _, local = _split_tag(child.tag)
            if local == "CursorPosition":
                cursor_position = _attr(child, "Position")
                cursor_offset_x = _cursor_offset(child, "OffsetX")
                cursor_offset_y = _cursor_offset(child, "OffsetY")
    return ClickNode(
        selector=selector,
        display_name=_attr(elem, "DisplayName"),
        click_type=_attr(elem, "ClickType"),
        mouse_button=_attr(elem, "MouseButton"),
        key_modifiers=_attr(elem, "KeyModifiers"),
        cursor_position=cursor_position,
        cursor_offset_x=cursor_offset_x,
        cursor_offset_y=cursor_offset_y,
        delay_before=_attr_expr(elem, "DelayBefore"),
        delay_ms=_attr_expr(elem, "DelayMS"),
    )


def _parse_hover(elem: etree._Element) -> HoverNode:
    selector = _target_selector(elem)
    cursor_position = None
    cursor_offset_x = None
    cursor_offset_y = None
    cursor_position_prop = _find_property_element(elem, "CursorPosition")
    if cursor_position_prop is not None:
        for child in _direct_children(cursor_position_prop):
            _, local = _split_tag(child.tag)
            if local == "CursorPosition":
                cursor_position = _attr(child, "Position")
                cursor_offset_x = _cursor_offset(child, "OffsetX")
                cursor_offset_y = _cursor_offset(child, "OffsetY")
    return HoverNode(
        selector=selector,
        display_name=_attr(elem, "DisplayName"),
        cursor_position=cursor_position,
        cursor_offset_x=cursor_offset_x,
        cursor_offset_y=cursor_offset_y,
        delay_before=_attr_expr(elem, "DelayBefore"),
        delay_ms=_attr_expr(elem, "DelayMS"),
        send_window_messages=_attr_expr(elem, "SendWindowMessages"),
        simulate_hover=_attr_expr(elem, "SimulateHover"),
    )


def _parse_activate(elem: etree._Element) -> ActivateNode:
    selector = _target_selector(elem)
    return ActivateNode(
        selector=selector,
        display_name=_attr(elem, "DisplayName"),
        delay_before=_attr_expr(elem, "DelayBefore"),
        delay_ms=_attr_expr(elem, "DelayMS"),
        continue_on_error=_attr_expr(elem, "ContinueOnError"),
    )


def _parse_check(elem: etree._Element) -> CheckNode:
    return CheckNode(
        selector=_target_selector(elem),
        display_name=_attr(elem, "DisplayName"),
        action=_attr(elem, "Action"),
        delay_before=_attr_expr(elem, "DelayBefore"),
        delay_after=_attr_expr(elem, "DelayAfter"),
        continue_on_error=_attr_expr(elem, "ContinueOnError"),
    )


def _parse_highlight(elem: etree._Element) -> HighlightNode:
    return HighlightNode(
        selector=_target_selector(elem),
        display_name=_attr(elem, "DisplayName"),
        color=_attr(elem, "Color"),
        highlight_time=_attr_expr(elem, "HighlightTime"),
    )


def _parse_type_into(elem: etree._Element) -> TypeIntoNode:
    selector = _target_selector(elem)
    # `Activate`/`ActivateBefore`の表記揺れ(`TypeIntoNode`のdocstring参照)。
    # 同じXAMLに両方が同時に現れた実例は確認していないため、どちらかが
    # 存在すればそれを使う(両方無ければ`_attr_expr`が自然に`None`を返す)。
    activate_before = _attr_expr(elem, "ActivateBefore")
    if activate_before is None and _attr(elem, "Activate") is not None:
        activate_before = _attr_expr(elem, "Activate")
    return TypeIntoNode(
        selector=selector,
        display_name=_attr(elem, "DisplayName"),
        text=_attr_expr(elem, "Text"),
        empty_field=_attr_expr(elem, "EmptyField"),
        click_before_typing=_attr_expr(elem, "ClickBeforeTyping"),
        simulate_type=_attr_expr(elem, "SimulateType"),
        send_window_messages=_attr_expr(elem, "SendWindowMessages"),
        delay_before=_attr_expr(elem, "DelayBefore"),
        delay_ms=_attr_expr(elem, "DelayMS"),
        delay_between_keys=_attr_expr(elem, "DelayBetweenKeys"),
        activate_before=activate_before,
        alter_if_disabled=_attr_expr(elem, "AlterIfDisabled"),
        continue_on_error=_attr_expr(elem, "ContinueOnError"),
    )


def _parse_type_secure_text(elem: etree._Element) -> TypeIntoNode:
    """`<ui:TypeSecureText>`(知見158、GitHub code searchで544件ヒット
    ——`piyushagarwal08/JU-Notes`等の実機XAMLで確認)。`ui:TypeInto`
    (知見110)と属性構成が全く同じ(`ClickBeforeTyping`/`DelayBefore`/
    `DelayBetweenKeys`/`DelayMS`/`EmptyField`/`SendWindowMessages`/
    `SimulateType`/`Activate`)で、唯一の違いは入力文字列を保持する
    属性名が`Text`ではなく`SecureText`(本来`System.Security.
    SecureString`型だが、本トランスパイラはどの変数もPythonの通常の
    識別子として扱うため.NET型の違いは意識する必要が無い)。意味論・
    コード生成はTypeIntoと完全に同じため、新しいノード型を追加せず
    既存の`TypeIntoNode`をそのまま返す(`ui:ForEachRow`が`ForEachNode`
    を再利用するのと同じ設計)。"""
    selector = _target_selector(elem)
    activate_before = _attr_expr(elem, "ActivateBefore")
    if activate_before is None and _attr(elem, "Activate") is not None:
        activate_before = _attr_expr(elem, "Activate")
    return TypeIntoNode(
        selector=selector,
        display_name=_attr(elem, "DisplayName"),
        text=_attr_expr(elem, "SecureText"),
        empty_field=_attr_expr(elem, "EmptyField"),
        click_before_typing=_attr_expr(elem, "ClickBeforeTyping"),
        simulate_type=_attr_expr(elem, "SimulateType"),
        send_window_messages=_attr_expr(elem, "SendWindowMessages"),
        delay_before=_attr_expr(elem, "DelayBefore"),
        delay_ms=_attr_expr(elem, "DelayMS"),
        delay_between_keys=_attr_expr(elem, "DelayBetweenKeys"),
        activate_before=activate_before,
        alter_if_disabled=_attr_expr(elem, "AlterIfDisabled"),
        continue_on_error=_attr_expr(elem, "ContinueOnError"),
    )


def _parse_send_hotkey(elem: etree._Element) -> SendHotkeyNode:
    selector = _target_selector(elem)
    return SendHotkeyNode(
        selector=selector,
        display_name=_attr(elem, "DisplayName"),
        key=_attr_expr(elem, "Key"),
        key_modifiers=_attr_expr(elem, "KeyModifiers"),
        click_before_typing=_attr_expr(elem, "ClickBeforeTyping"),
        empty_field=_attr_expr(elem, "EmptyField"),
        send_window_messages=_attr_expr(elem, "SendWindowMessages"),
        delay_before=_attr_expr(elem, "DelayBefore"),
        delay_between_keys=_attr_expr(elem, "DelayBetweenKeys"),
        delay_ms=_attr_expr(elem, "DelayMS"),
        activate=_attr_expr(elem, "Activate"),
    )


def _parse_get_text(elem: etree._Element) -> GetTextNode:
    selector = _target_selector(elem)
    return GetTextNode(
        selector=selector,
        display_name=_attr(elem, "DisplayName"),
        text=_attr_expr(elem, "Text"),
        delay_before=_attr_expr(elem, "DelayBefore"),
        delay_ms=_attr_expr(elem, "DelayMS"),
        continue_on_error=_attr_expr(elem, "ContinueOnError"),
    )


def _parse_get_full_text(elem: etree._Element) -> GetTextNode:
    """知見159: `ui:GetFullText`(`GetText`とは別の活動、GitHub code
    searchで300件ヒット)。`Target`構造は`GetText`と同じだが、出力
    `Text`はプロパティ要素形(`_in_argument_property_expr`、知見115)で
    直列化される——同じ`GetTextNode`を`full_text=True`で返す。"""
    selector = _target_selector(elem)
    return GetTextNode(
        selector=selector,
        display_name=_attr(elem, "DisplayName"),
        text=_in_argument_property_expr(elem, "Text"),
        delay_before=_attr_expr(elem, "DelayBefore"),
        delay_ms=_attr_expr(elem, "DelayMS"),
        continue_on_error=_attr_expr(elem, "ContinueOnError"),
        full_text=True,
        ignore_hidden=_attr_expr(elem, "IgnoreHidden"),
    )


def _parse_select_item(elem: etree._Element) -> SelectItemNode:
    selector = _target_selector(elem)
    return SelectItemNode(
        selector=selector,
        display_name=_attr(elem, "DisplayName"),
        item=_attr_expr(elem, "Item"),
        delay_before=_attr_expr(elem, "DelayBefore"),
        delay_after=_attr_expr(elem, "DelayAfter"),
        continue_on_error=_attr_expr(elem, "ContinueOnError"),
        alter_if_disabled=_attr_expr(elem, "AlterIfDisabled"),
    )


def _parse_ui_element_exists(elem: etree._Element) -> UiElementExistsNode:
    selector = _target_selector(elem)
    return UiElementExistsNode(
        selector=selector,
        display_name=_attr(elem, "DisplayName"),
        exists=_attr_expr(elem, "Exists"),
    )


def _parse_database_connect(elem: etree._Element) -> DatabaseConnectNode:
    return DatabaseConnectNode(
        connection_string=_attr_expr(elem, "ConnectionString"),
        secure_connection_string=_attr_expr(elem, "SecureConnectionString"),
        provider_name=_attr_expr(elem, "ProviderName"),
        database_connection=_attr_expr(elem, "DatabaseConnection"),
        display_name=_attr(elem, "DisplayName"),
    )


def _parse_database_disconnect(elem: etree._Element) -> DatabaseDisconnectNode:
    return DatabaseDisconnectNode(
        database_connection=_attr_expr(elem, "DatabaseConnection"),
        display_name=_attr(elem, "DisplayName"),
    )


def _parse_execute_query(elem: etree._Element) -> ExecuteQueryNode:
    parameters = _xkey_dict_entries(_find_property_element(elem, "Parameters"))
    return ExecuteQueryNode(
        sql=_attr_expr(elem, "Sql"),
        parameters=parameters,
        existing_db_connection=_attr_expr(elem, "ExistingDbConnection"),
        data_table=_attr_expr(elem, "DataTable"),
        command_type=_attr(elem, "CommandType"),
        continue_on_error=_attr_expr(elem, "ContinueOnError"),
        timeout_ms=_attr_expr(elem, "TimeoutMS"),
        display_name=_attr(elem, "DisplayName"),
    )


def _parse_execute_non_query(elem: etree._Element) -> ExecuteNonQueryNode:
    parameters = _xkey_dict_entries(_find_property_element(elem, "Parameters"))
    return ExecuteNonQueryNode(
        sql=_attr_expr(elem, "Sql"),
        parameters=parameters,
        existing_db_connection=_attr_expr(elem, "ExistingDbConnection"),
        affected_records=_attr_expr(elem, "AffectedRecords"),
        command_type=_attr(elem, "CommandType"),
        continue_on_error=_attr_expr(elem, "ContinueOnError"),
        timeout_ms=_attr_expr(elem, "TimeoutMS"),
        display_name=_attr(elem, "DisplayName"),
    )


def _parse_copy_file(elem: etree._Element) -> CopyFileNode:
    return CopyFileNode(
        path=_attr_expr(elem, "Path"),
        destination=_attr_expr(elem, "Destination"),
        overwrite=_attr(elem, "Overwrite"),
        destination_resource=_attr_expr(elem, "DestinationResource"),
        path_resource=_attr_expr(elem, "PathResource"),
        continue_on_error=_attr_expr(elem, "ContinueOnError"),
        display_name=_attr(elem, "DisplayName"),
    )


_XS_NS = {"xs": "http://www.w3.org/2001/XMLSchema"}


def _build_data_table_columns(table_info: str | None) -> list[str]:
    """知見117: `TableInfo`属性に埋め込まれた.NET `DataSet`のXMLスキーマ
    (`xs:schema`)から列名のみを抜き出す——`xs:complexType/xs:sequence/
    xs:element`という階層(`TableName`要素直下の列定義のみに一致し、
    外側の`NewDataSet`/`TableName`自身の`xs:element`は`xs:choice`配下の
    ため一致しない)で絞り込む。パース失敗時は空リストを返す(呼び出し側が
    `# TODO`へ倒す判断をする)。"""
    if not table_info:
        return []
    try:
        root = etree.fromstring(table_info.encode())
    except etree.XMLSyntaxError:
        return []
    elements = root.findall(".//xs:complexType/xs:sequence/xs:element", _XS_NS)
    return [name for el in elements if (name := el.get("name")) is not None]


def _parse_build_data_table(elem: etree._Element) -> BuildDataTableNode:
    return BuildDataTableNode(
        data_table=_attr_expr(elem, "DataTable"),
        columns=_build_data_table_columns(_attr(elem, "TableInfo")),
        display_name=_attr(elem, "DisplayName"),
    )


def _parse_invoke_workflow_file(elem: etree._Element) -> InvokeWorkflowFileNode:
    args: dict[str, Expr] = {}
    args_elem = _find_property_element(elem, "Arguments")
    if args_elem is not None:
        for arg in _direct_children(args_elem):
            key = _attr(arg, "Key", X_NS) or _attr(arg, "Key")
            if key:
                args[key] = _parse_expr(arg.text)
    return InvokeWorkflowFileNode(
        workflow_file=_attr(elem, "WorkflowFileName") or "",
        arguments=args,
        continue_on_error=_attr_expr(elem, "ContinueOnError"),
    )


def _parse_append_line(elem: etree._Element) -> AppendLineNode:
    return AppendLineNode(
        file_name=_attr_expr(elem, "FileName"),
        text=_attr_expr(elem, "Text"),
        encoding=_attr(elem, "Encoding"),
        use_default_encoding=_attr(elem, "UseDefaultEncoding"),
    )


def _parse_read_text_file(elem: etree._Element) -> ReadTextFileNode:
    return ReadTextFileNode(
        file_name=_attr_expr(elem, "FileName"),
        content=_attr_expr(elem, "Content"),
        encoding=_attr(elem, "Encoding"),
    )


def _parse_invoke_code(elem: etree._Element) -> InvokeCodeNode:
    args: dict[str, Expr] = {}
    args_elem = _find_property_element(elem, "Arguments")
    if args_elem is not None:
        for arg in _direct_children(args_elem):
            key = _attr(arg, "Key", X_NS) or _attr(arg, "Key")
            if key:
                args[key] = _parse_expr(arg.text)
    return InvokeCodeNode(code=_attr(elem, "Code") or "", arguments=args)


def _parse_set_to_clipboard(elem: etree._Element) -> SetToClipboardNode:
    return SetToClipboardNode(text=_attr_expr(elem, "Text"))


def _parse_excel_write_cell(elem: etree._Element) -> ExcelWriteCellNode:
    return ExcelWriteCellNode(
        cell=_attr_expr(elem, "Cell"),
        sheet_name=_attr(elem, "SheetName") or "",
        text=_attr_expr(elem, "Text"),
        display_name=_attr(elem, "DisplayName"),
    )


def _parse_excel_read_cell(elem: etree._Element) -> ExcelReadCellNode:
    return ExcelReadCellNode(
        cell=_attr_expr(elem, "Cell"),
        sheet_name=_attr(elem, "SheetName") or "",
        result=_in_argument_property_expr(elem, "Result"),
        display_name=_attr(elem, "DisplayName"),
    )


def _parse_comment(elem: etree._Element) -> CommentNode:
    return CommentNode(text=_attr(elem, "Text") or "")


def _parse_delay(elem: etree._Element) -> DelayNode:
    return DelayNode(
        duration=_attr_expr(elem, "Duration"),
        display_name=_attr(elem, "DisplayName"),
    )


def _parse_write_line(elem: etree._Element) -> WriteLineNode:
    return WriteLineNode(
        text=_attr_expr(elem, "Text"),
        display_name=_attr(elem, "DisplayName"),
    )


def _parse_throw(elem: etree._Element) -> ThrowNode:
    return ThrowNode(
        exception=_attr_expr(elem, "Exception"),
        display_name=_attr(elem, "DisplayName"),
    )


def _parse_rethrow(elem: etree._Element) -> RethrowNode:
    return RethrowNode(display_name=_attr(elem, "DisplayName"))


def _parse_terminate_workflow(elem: etree._Element) -> TerminateWorkflowNode:
    return TerminateWorkflowNode(
        reason=_attr_expr(elem, "Reason"),
        exception=_attr_expr(elem, "Exception"),
        display_name=_attr(elem, "DisplayName"),
    )


_LOG_LEVEL_ENUM_PREFIX = "UiPath.Core.Activities.LogLevel."


def _parse_log_level(elem: etree._Element) -> str | None:
    """知見122で発見・保留した`Level`の列挙参照形(知見124で解決)。
    `Level="Info"`のような生の文字列が通常形だが、`[UiPath.Core.
    Activities.LogLevel.Info]`という、`[...]`角括弧で囲まれたVB式として
    .NET列挙の完全修飾名を参照する実例も実機XAMLで見つかった。角括弧の
    中身が確認済みの列挙プレフィックスで始まる場合のみ末尾のメンバー名
    (`"Info"`)を取り出し、以降は既存の`_LOG_LEVEL_METHODS`(`Info`/
    `Error`のみ確認済み)にそのまま流す——未知の形は無理に解釈せず、
    生のテキストをそのまま返して`# TODO`側の診断メッセージに委ねる。"""
    raw = _attr(elem, "Level")
    if raw is None:
        return None
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if inner.startswith(_LOG_LEVEL_ENUM_PREFIX):
            return inner[len(_LOG_LEVEL_ENUM_PREFIX):]
        return raw
    return raw


def _parse_log_message(elem: etree._Element) -> LogMessageNode:
    return LogMessageNode(
        message=_attr_expr(elem, "Message"),
        level=_parse_log_level(elem),
        display_name=_attr(elem, "DisplayName"),
    )


def _in_argument_property_expr(elem: etree._Element, prop_name: str) -> Expr:
    """`<X.PropName><InArgument x:TypeArguments="...">...</InArgument>
    </X.PropName>`形のプロパティを`Expr`へ変換する(知見115、`ui:
    ExcelReadRange.Range`で確認済み)。`InArgument`の内容は直接テキスト
    (`VbExpr`/生リテラル)か、ネストした`<Literal x:TypeArguments="..."
    Value="..." />`要素(属性`Value`、空文字列を含む)のいずれか。"""
    prop_elem = _find_property_element(elem, prop_name)
    if prop_elem is None:
        return None
    children = _direct_children(prop_elem)
    if not children:
        return None
    in_arg = children[0]
    nested = _direct_children(in_arg)
    if nested:
        value = _attr(nested[0], "Value")
        return _parse_expr(value) if value is not None else None
    return _parse_expr(in_arg.text)


def _parse_excel_read_range(elem: etree._Element) -> ExcelReadRangeNode:
    return ExcelReadRangeNode(
        sheet_name=_attr(elem, "SheetName") or "",
        range=_in_argument_property_expr(elem, "Range"),
        add_headers=_attr(elem, "AddHeaders"),
        data_table=_attr_expr(elem, "DataTable"),
        display_name=_attr(elem, "DisplayName"),
    )


def _parse_excel_write_range(elem: etree._Element) -> ExcelWriteRangeNode:
    return ExcelWriteRangeNode(
        sheet_name=_attr(elem, "SheetName") or "",
        starting_cell=_attr(elem, "StartingCell"),
        add_headers=_attr(elem, "AddHeaders"),
        data_table=_attr_expr(elem, "DataTable"),
        display_name=_attr(elem, "DisplayName"),
    )


def _parse_excel_append_range(elem: etree._Element) -> ExcelAppendRangeNode:
    return ExcelAppendRangeNode(
        sheet_name=_attr(elem, "SheetName") or "",
        data_table=_attr_expr(elem, "DataTable"),
        display_name=_attr(elem, "DisplayName"),
    )


def _parse_attach_window(elem: etree._Element) -> AttachWindowNode:
    body_elem = _find_property_element(elem, "Body")
    body = _unwrap_body_sequence(body_elem)
    return AttachWindowNode(
        selector=_attr(elem, "Selector"),
        body=body,
        display_name=_attr(elem, "DisplayName"),
    )


def _parse_window_scope(elem: etree._Element) -> AttachWindowNode:
    """知見158: `ui:WindowScope`(`AttachWindow`と同義の別活動——`.Body`
    の構造は`ActivityAction`+`DelegateInArgument`、`OpenApplication`
    (知見154)と同じ抽出方法)。同じ`AttachWindowNode`を返す。"""
    body_elem = _find_property_element(elem, "Body")
    action = _find_activity_action(body_elem) if body_elem is not None else None
    body = _unwrap_body_sequence(action) if action is not None else []
    return AttachWindowNode(
        selector=_attr(elem, "Selector"),
        body=body,
        display_name=_attr(elem, "DisplayName"),
        application_window=_attr_expr(elem, "ApplicationWindow"),
        search_scope=_attr_expr(elem, "SearchScope"),
        timeout_ms=_attr_expr(elem, "TimeoutMS"),
        window=_attr_expr(elem, "Window"),
    )


def _parse_browser_scope(elem: etree._Element) -> AttachWindowNode:
    """知見161: `ui:BrowserScope`(「Attach Browser」、`WindowScope`
    (知見158)と同じ`ActivityAction`+`DelegateInArgument`構造の同義
    活動)。同じ`AttachWindowNode`を返す。"""
    body_elem = _find_property_element(elem, "Body")
    action = _find_activity_action(body_elem) if body_elem is not None else None
    body = _unwrap_body_sequence(action) if action is not None else []
    return AttachWindowNode(
        selector=_attr(elem, "Selector"),
        body=body,
        display_name=_attr(elem, "DisplayName"),
        search_scope=_attr_expr(elem, "SearchScope"),
        timeout_ms=_attr_expr(elem, "TimeoutMS"),
        browser=_attr_expr(elem, "Browser"),
        browser_type=_attr(elem, "BrowserType"),
        ui_browser=_attr_expr(elem, "UiBrowser"),
        continue_on_error=_attr_expr(elem, "ContinueOnError"),
    )


def _parse_open_application(elem: etree._Element) -> OpenApplicationNode:
    body_elem = _find_property_element(elem, "Body")
    action = _find_activity_action(body_elem) if body_elem is not None else None
    body = _unwrap_body_sequence(action) if action is not None else []
    return OpenApplicationNode(
        file_name=_attr_expr(elem, "FileName"),
        selector=_attr(elem, "Selector"),
        arguments=_attr_expr(elem, "Arguments"),
        working_directory=_attr_expr(elem, "WorkingDirectory"),
        application_window=_attr_expr(elem, "ApplicationWindow"),
        timeout_ms=_attr_expr(elem, "TimeoutMS"),
        continue_on_error=_attr_expr(elem, "ContinueOnError"),
        body=body,
        display_name=_attr(elem, "DisplayName"),
    )


def _parse_excel_application_scope(elem: etree._Element) -> ExcelApplicationScopeNode:
    body_elem = _find_property_element(elem, "Body")
    action = _find_activity_action(body_elem) if body_elem is not None else None
    scope_var = "ExcelWorkbookScope"
    body: list[Node] = []
    if action is not None:
        arg_elem = _find_property_element(action, "Argument")
        if arg_elem is not None:
            for d in _direct_children(arg_elem):
                scope_var = _attr(d, "Name") or scope_var
        body = _unwrap_body_sequence(action)
    return ExcelApplicationScopeNode(
        workbook_path=_attr(elem, "WorkbookPath") or "", scope_var=scope_var, body=body
    )


def _parse_word_application_scope(elem: etree._Element) -> WordApplicationScopeNode:
    """知見121: `ui:WordApplicationScope`。`_parse_excel_application_scope`
    と完全に同じ構造パーサー(`ActivityAction`+`DelegateInArgument`)。"""
    body_elem = _find_property_element(elem, "Body")
    action = _find_activity_action(body_elem) if body_elem is not None else None
    scope_var = "WordDocumentScope"
    body: list[Node] = []
    if action is not None:
        arg_elem = _find_property_element(action, "Argument")
        if arg_elem is not None:
            for d in _direct_children(arg_elem):
                scope_var = _attr(d, "Name") or scope_var
        body = _unwrap_body_sequence(action)
    return WordApplicationScopeNode(
        file_name=_attr(elem, "FileName") or "", scope_var=scope_var, body=body
    )


def _parse_word_replace_text(elem: etree._Element) -> WordReplaceTextNode:
    return WordReplaceTextNode(
        search=_attr_expr(elem, "Search"),
        replace=_attr_expr(elem, "Replace"),
        display_name=_attr(elem, "DisplayName"),
    )


_SEND_OUTLOOK_MAIL_KNOWN_ATTRS = {
    "To", "Subject", "Body", "Cc", "Bcc", "Importance", "Sensitivity", "IsBodyHtml", "IsDraft",
}


def _parse_send_outlook_mail(elem: etree._Element) -> SendOutlookMailNode:
    """知見98: `Cc`/`Bcc`/`Importance`/`Sensitivity`/`IsBodyHtml`/`IsDraft`も
    `To`/`Subject`/`Body`と同じく専用フィールドへ昇格する。`Files`
    (`scg:List`プロパティ要素、実機フィクスチャでは`Capacity="0"`で子要素
    なし)は1件以上のエントリを持つかどうかだけを記録する(知見96の
    `HttpClient.Headers`と同じ理由——populated時の実直列化形は未確認)。"""
    extra = {
        k: v for k, v in elem.attrib.items() if _split_tag(k)[1] not in _SEND_OUTLOOK_MAIL_KNOWN_ATTRS
    }
    has_populated_files = False
    files_elem = _find_property_element(elem, "Files")
    if files_elem is not None:
        for list_elem in _direct_children(files_elem):
            if _direct_children(list_elem):
                has_populated_files = True
    return SendOutlookMailNode(
        to=_attr_expr(elem, "To"),
        subject=_attr_expr(elem, "Subject"),
        body=_attr_expr(elem, "Body"),
        cc=_attr_expr(elem, "Cc"),
        bcc=_attr_expr(elem, "Bcc"),
        importance=_attr(elem, "Importance"),
        sensitivity=_attr(elem, "Sensitivity"),
        is_body_html=_attr(elem, "IsBodyHtml"),
        is_draft=_attr(elem, "IsDraft"),
        has_populated_files=has_populated_files,
        extra_attrs=extra,
    )


def _parse_get_outlook_mail_messages(elem: etree._Element) -> GetOutlookMailMessagesNode:
    """知見120: `ui:GetOutlookMailMessages`。"""
    return GetOutlookMailMessagesNode(
        messages=_attr_expr(elem, "Messages"),
        account=_attr_expr(elem, "Account"),
        filter=_attr_expr(elem, "Filter"),
        mail_folder=_attr(elem, "MailFolder"),
        get_attachments=_attr(elem, "GetAttachements"),
        mark_as_read=_attr(elem, "MarkAsRead"),
        only_unread_messages=_attr(elem, "OnlyUnreadMessages"),
        top=_attr_expr(elem, "Top"),
        timeout_ms=_attr_expr(elem, "TimeoutMS"),
        display_name=_attr(elem, "DisplayName"),
    )


def _parse_send_mail(elem: etree._Element) -> SendMailNode:
    """知見116: `ui:SendMail`(DisplayName「Send SMTP Mail Message」/
    「Send SMTP Email」)。`Files`のpopulated判定は`_parse_send_outlook_mail`
    と同じロジック(知見75・92〜95)。"""
    has_populated_files = False
    files_elem = _find_property_element(elem, "Files")
    if files_elem is not None:
        for list_elem in _direct_children(files_elem):
            if _direct_children(list_elem):
                has_populated_files = True
    return SendMailNode(
        to=_attr_expr(elem, "To"),
        cc=_attr_expr(elem, "Cc"),
        bcc=_attr_expr(elem, "Bcc"),
        subject=_attr_expr(elem, "Subject"),
        body=_attr_expr(elem, "Body"),
        is_body_html=_attr(elem, "IsBodyHtml"),
        email=_attr_expr(elem, "Email"),
        password=_attr_expr(elem, "Password"),
        server=_attr_expr(elem, "Server"),
        port=_attr_expr(elem, "Port"),
        enable_ssl=_attr(elem, "EnableSSL"),
        secure_connection=_attr(elem, "SecureConnection"),
        from_=_attr_expr(elem, "From"),
        name=_attr_expr(elem, "Name"),
        reply_to=_attr_expr(elem, "ReplyTo"),
        use_oauth=_attr(elem, "UseOAuth"),
        mail_message=_attr_expr(elem, "MailMessage"),
        continue_on_error=_attr_expr(elem, "ContinueOnError"),
        timeout_ms=_attr_expr(elem, "TimeoutMS"),
        has_populated_files=has_populated_files,
        display_name=_attr(elem, "DisplayName"),
    )


_HTTP_CLIENT_FALLBACK_COLLECTION_PROPS = ("Cookies", "Parameters", "UrlSegments", "Attachments")


def _xkey_dict_entries(prop_elem: etree._Element | None) -> dict[str, Expr]:
    """`x:Key`付き辞書エントリの共通パーサー(知見104で`ui:HttpClient.
    Headers`向けに実装、知見114で`ui:ExecuteQuery`/`ui:ExecuteNonQuery`の
    `Parameters`にも再利用——同じ`scg:Dictionary`/`x:Key`直列化パターンが
    複数の活動で共有されているため)。

    知見104: 空の場合は`<scg:Dictionary x:TypeArguments="x:String,
    InArgument(x:String)" />`(子要素なしの自己終了タグ)だが、populated時は
    この`scg:Dictionary`ラッパー自体が無くなり、各エントリが直接の子
    `<InArgument x:Key="...">`になる——値は直接テキスト形
    (`<InArgument x:Key="content-Type">application/json</InArgument>`、
    `VamsiyadavChakka/OrchestratorAPI-s`の実例)とネストした`<Literal>`
    子要素形(`<InArgument x:Key="Content-Type"><Literal>text/plain
    </Literal></InArgument>`、`vajrang-b/UiPathIn30Days`の実例)の両方が
    実在するため、両対応する。"""
    if prop_elem is None:
        return {}
    entries: dict[str, Expr] = {}
    for child in _direct_children(prop_elem):
        key = _attr(child, "Key", X_NS) or _attr(child, "Key")
        if key is None:
            continue
        nested = _direct_children(child)
        text = nested[0].text if nested else child.text
        entries[key] = _parse_expr(text)
    return entries


def _parse_http_client(elem: etree._Element) -> HttpClientNode:
    """知見96: `Body`/`TimeoutMS`も`EndPoint`/`Method`と同じく専用フィールドへ
    昇格する(それまでは`extra_attrs`の生文字列止まりだった)。

    知見104: `Headers`は実際にpopulated時の直列化形を確認できたため
    `headers`フィールドへパースする。`Cookies`/`Parameters`/
    `UrlSegments`/`Attachments`(同じ`InArgument x:Key`形のはずだが、
    populated時の意味論——`Parameters`がクエリ文字列かフォームデータか等
    ——がまだ未確認)は引き続き「1件以上のエントリを持つかどうか」だけを
    `has_populated_collections`として記録し、中身のパースはしない
    (でっち上げ回避)。"""
    known = {"EndPoint", "Method", "Body", "TimeoutMS"}
    extra = {k: v for k, v in elem.attrib.items() if _split_tag(k)[1] not in known}
    headers = _xkey_dict_entries(_find_property_element(elem, "Headers"))
    has_populated = False
    for prop_name in _HTTP_CLIENT_FALLBACK_COLLECTION_PROPS:
        prop_elem = _find_property_element(elem, prop_name)
        if prop_elem is None:
            continue
        for dict_elem in _direct_children(prop_elem):
            if _direct_children(dict_elem):
                has_populated = True
    return HttpClientNode(
        endpoint=_attr_expr(elem, "EndPoint"),
        method=_attr(elem, "Method") or "GET",
        body=_attr_expr(elem, "Body"),
        timeout_ms=_attr(elem, "TimeoutMS"),
        headers=headers,
        has_populated_collections=has_populated,
        extra_attrs=extra,
    )


_FLOW_NODE_LOCAL_NAMES = {"FlowStep", "FlowDecision", "FlowSwitch"}


def _flow_attr_reference(elem: etree._Element, attr_name: str) -> str | None:
    """`PropName="{x:Reference Name}"`(マークアップ拡張の属性値形、知見100
    で実機確認済み、例: `True="{x:Reference __ReferenceID0}"`)から`Name`を
    取り出す。該当しなければ`None`。"""
    raw = _attr(elem, attr_name)
    if raw is None:
        return None
    raw = raw.strip()
    if not (raw.startswith("{") and raw.endswith("}")):
        return None
    inner = raw[1:-1].strip()
    if not inner.startswith("x:Reference"):
        return None
    return inner[len("x:Reference"):].strip()


def _flow_make_placeholder(local_name: str) -> FlowStepNode | FlowDecisionNode | FlowSwitchNode:
    if local_name == "FlowDecision":
        return FlowDecisionNode(condition=None)
    if local_name == "FlowSwitch":
        return FlowSwitchNode(expression=None, type_arguments="")
    return FlowStepNode()


def _flow_prescan_names(root: etree._Element, name_to_node: dict[str, FlowNode]) -> None:
    """知見100: Flowchartのグラフは名前付きノード(`x:Name`)への`x:Reference`
    参照で循環・合流しうる——知見30がState Machine用に見込んでいた「名前→
    ノードのマップを先に構築してからx:Referenceを解決する2パス方式」を
    Flowchartでも採用する。1パス目は全体をブランケットに`iter()`で
    一度だけ走査し、`x:Name`を持つ`FlowStep`/`FlowDecision`/`FlowSwitch`
    要素それぞれに対し型だけ確定した空のプレースホルダを登録する——これに
    より2パス目で「まだ見ていない名前への前方参照」でも型を知らずに
    プレースホルダを作ってしまう(中身を誤った型で埋めることになる)
    心配が無くなる。"""
    for elem in root.iter():
        _, local = _split_tag(elem.tag)
        if local not in _FLOW_NODE_LOCAL_NAMES:
            continue
        name = _attr(elem, "Name", X_NS) or _attr(elem, "Name")
        if name and name not in name_to_node:
            name_to_node[name] = _flow_make_placeholder(local)


def _resolve_flow_target(
    elem: etree._Element, prop_name: str, name_to_node: dict[str, FlowNode]
) -> FlowNode:
    """`elem`の`prop_name`プロパティ(`Next`/`True`/`False`)が指す先の
    `FlowNode`を解決する——知見100で確認した3つの直列化形(属性値形
    `{x:Reference Name}`、プロパティ要素+`<x:Reference>Name</x:Reference>`
    子要素形、プロパティ要素+ネストした本体定義形)のいずれにも対応する。
    本体定義形の場合、中身は(`_flow_prescan_names`で登録済みの)
    プレースホルダを返すだけで、実際の内容埋めは`_parse_flowchart`の
    ブランケット2パス目(`iter()`)がその要素を独立に処理する時に行う
    ——ここで再帰的にパースすると同じノードを2回処理してしまう。"""
    ref_name = _flow_attr_reference(elem, prop_name)
    if ref_name is not None:
        return name_to_node.get(ref_name)
    prop_elem = _find_property_element(elem, prop_name)
    if prop_elem is None:
        return None
    children = _direct_children(prop_elem)
    if not children:
        return None
    child = children[0]
    c_ns, c_local = _split_tag(child.tag)
    if (c_ns, c_local) == (X_NS, "Reference"):
        return name_to_node.get((child.text or "").strip())
    name = _attr(child, "Name", X_NS) or _attr(child, "Name")
    return name_to_node.get(name) if name else None


def _parse_flow_switch_arms(
    elem: etree._Element, name_to_node: dict[str, FlowNode]
) -> list[FlowSwitchArm]:
    """`FlowSwitch`の各ケース(`FlowSwitch`の直接の子、`x:Key`は知見21の
    UiPath本体`Switch`と同じ属性形、知見100で実機確認済み)と`Default`
    (`FlowSwitch.Default`プロパティ要素、知見40の`Switch.Default`と同じ
    規約)。ケースの対象が既に他所で本体定義済みのノードへの合流の場合、
    `<x:Reference x:Key="...">Name</x:Reference>`という形(実機未確認だが、
    他のプロパティでx:Keyを持つ要素への付与がXAML上可能なことから類推した
    防御的な対応——確実にクラッシュするよりは広く対応する)も扱う。"""
    arms: list[FlowSwitchArm] = []
    default_elem = _find_property_element(elem, "Default")
    if default_elem is not None:
        default_children = _direct_children(default_elem)
        if default_children:
            arms.append(FlowSwitchArm(key=None, node=_flow_node_from_element(
                default_children[0], name_to_node
            )))
    for child in _activity_children(elem):
        key = _attr(child, "Key", X_NS) or _attr(child, "Key")
        arms.append(FlowSwitchArm(key=key, node=_flow_node_from_element(child, name_to_node)))
    return arms


def _flow_node_from_element(elem: etree._Element, name_to_node: dict[str, FlowNode]) -> FlowNode:
    """直接の子要素から`FlowNode`を得る——`<x:Reference>Name</x:Reference>`
    (既に他所で本体定義済みのノードを指す)か、本体定義そのもの
    (`x:Name`で登録済みのプレースホルダを返す、中身の埋め込みは
    `_parse_flowchart`のブランケット2パス目が行う)かのいずれか。"""
    ns, local = _split_tag(elem.tag)
    if (ns, local) == (X_NS, "Reference"):
        return name_to_node.get((elem.text or "").strip())
    name = _attr(elem, "Name", X_NS) or _attr(elem, "Name")
    return name_to_node.get(name) if name else None


def _parse_flowchart(elem: etree._Element) -> FlowchartNode:
    """`<Flowchart>`(知見100、VM不使用——実際にStudioが保存した公開済み
    実機XAMLをGitHub上から直接確認して確定した直列化形)。

    `x:Name`付きの`FlowStep`/`FlowDecision`/`FlowSwitch`要素は文書中の
    どこに出現してもよい(`Flowchart.StartNode`の中、他ノードの`Next`/
    `True`/`False`/ケースの中、または`Flowchart`自身の直接の子として)
    ——2パス構成(`_flow_prescan_names`→本体埋め込み)でこれを扱う。
    本体埋め込みパスは`elem.iter()`でFlowchart全体を1回だけブランケット
    走査し、`FlowStep`/`FlowDecision`/`FlowSwitch`要素に出会うたびその
    プレースホルダへ中身を埋める——ネストの深さに関わらず各ノードが
    ちょうど1回だけ処理される(循環があっても`iter()`は単純な文書順
    走査なので無限ループしない)。
    """
    name_to_node: dict[str, FlowNode] = {}
    _flow_prescan_names(elem, name_to_node)

    for node_elem in elem.iter():
        _, local = _split_tag(node_elem.tag)
        if local not in _FLOW_NODE_LOCAL_NAMES:
            continue
        name = _attr(node_elem, "Name", X_NS) or _attr(node_elem, "Name")
        if not name:
            continue
        target = name_to_node[name]
        if local == "FlowStep":
            assert isinstance(target, FlowStepNode)
            target.body = _parse_body(node_elem)
            target.next = _resolve_flow_target(node_elem, "Next", name_to_node)
        elif local == "FlowDecision":
            assert isinstance(target, FlowDecisionNode)
            target.condition = _attr_expr(node_elem, "Condition")
            target.true_branch = _resolve_flow_target(node_elem, "True", name_to_node)
            target.false_branch = _resolve_flow_target(node_elem, "False", name_to_node)
        else:  # FlowSwitch
            assert isinstance(target, FlowSwitchNode)
            target.expression = _attr_expr(node_elem, "Expression")
            target.type_arguments = (
                _attr(node_elem, "TypeArguments", X_NS) or _attr(node_elem, "TypeArguments") or ""
            )
            target.arms = _parse_flow_switch_arms(node_elem, name_to_node)

    start = _flow_start_node(elem, name_to_node)
    return FlowchartNode(variables=_parse_variables(elem), start=start)


def _flow_start_node(elem: etree._Element, name_to_node: dict[str, FlowNode]) -> FlowNode:
    """`Flowchart.StartNode`——中身がネストした本体定義か`<x:Reference>`か
    (知見100、両方の実例を確認済み)のいずれか。"""
    start_elem = _find_property_element(elem, "StartNode")
    if start_elem is None:
        return None
    children = _direct_children(start_elem)
    if not children:
        return None
    return _flow_node_from_element(children[0], name_to_node)


# (namespace_uri, local_name) -> パース関数。知見1〜36で実機確認済みの
# Tier1アクティビティ(design/uipath_transpiler_roadmap.md Phase 1決定)のみ
# 登録する。それ以外は`UnknownActivityNode`へフォールバックする。
_DISPATCH = {
    (WF_NS, "Sequence"): _parse_sequence,
    (WF_NS, "Assign"): _parse_assign,
    (WF_NS, "If"): _parse_if,
    (WF_NS, "TryCatch"): _parse_try_catch,
    (WF_NS, "Switch"): _parse_switch,
    (WF_NS, "Parallel"): _parse_parallel,
    (WF_NS, "WriteLine"): _parse_write_line,
    (WF_NS, "Throw"): _parse_throw,
    (WF_NS, "Rethrow"): _parse_rethrow,
    (WF_NS, "TerminateWorkflow"): _parse_terminate_workflow,
    (UI_NS, "Delay"): _parse_delay,
    (UI_NS, "MessageBox"): _parse_message_box,
    (UI_NS, "InputDialog"): _parse_input_dialog,
    (UI_NS, "MultipleAssign"): _parse_multiple_assign,
    (UI_NS, "ForEach"): _parse_for_each,
    (WF_NS, "ForEach"): _parse_for_each,
    (UI_NS, "ForEachRow"): _parse_for_each_row,
    (UI_NS, "InterruptibleWhile"): _parse_while,
    (UI_NS, "InterruptibleDoWhile"): _parse_do_while,
    (UI_NS, "Break"): lambda elem: BreakNode(),
    (UI_NS, "Click"): _parse_click,
    (UI_NS, "Hover"): _parse_hover,
    (UI_NS, "Activate"): _parse_activate,
    (UI_NS, "Check"): _parse_check,
    (UI_NS, "Highlight"): _parse_highlight,
    (UI_NS, "SetFocus"): _parse_activate,
    (UI_NS, "TypeInto"): _parse_type_into,
    (UI_NS, "TypeSecureText"): _parse_type_secure_text,
    (UI_NS, "SendHotkey"): _parse_send_hotkey,
    (UI_NS, "GetText"): _parse_get_text,
    (UI_NS, "GetFullText"): _parse_get_full_text,
    (UI_NS, "SelectItem"): _parse_select_item,
    (UI_NS, "UiElementExists"): _parse_ui_element_exists,
    (UI_NS, "DatabaseConnect"): _parse_database_connect,
    (UI_NS, "DatabaseDisconnect"): _parse_database_disconnect,
    (UI_NS, "ExecuteQuery"): _parse_execute_query,
    (UI_NS, "ExecuteNonQuery"): _parse_execute_non_query,
    (UI_NS, "InvokeWorkflowFile"): _parse_invoke_workflow_file,
    (UI_NS, "CopyFile"): _parse_copy_file,
    (UI_NS, "BuildDataTable"): _parse_build_data_table,
    (UI_NS, "AppendLine"): _parse_append_line,
    (UI_NS, "ReadTextFile"): _parse_read_text_file,
    (UI_NS, "InvokeCode"): _parse_invoke_code,
    (UI_NS, "SetToClipboard"): _parse_set_to_clipboard,
    (UI_NS, "ExcelWriteCell"): _parse_excel_write_cell,
    (UI_NS, "ExcelReadCell"): _parse_excel_read_cell,
    (UI_NS, "Comment"): _parse_comment,
    (UI_NS, "LogMessage"): _parse_log_message,
    (UI_NS, "ExcelReadRange"): _parse_excel_read_range,
    (UI_NS, "ExcelWriteRange"): _parse_excel_write_range,
    (UI_NS, "ExcelAppendRange"): _parse_excel_append_range,
    (UI_NS, "AttachWindow"): _parse_attach_window,
    (UI_NS, "WindowScope"): _parse_window_scope,
    (UI_NS, "BrowserScope"): _parse_browser_scope,
    (UI_NS, "OpenApplication"): _parse_open_application,
    (UI_NS, "ExcelApplicationScope"): _parse_excel_application_scope,
    (UI_NS, "WordApplicationScope"): _parse_word_application_scope,
    (UI_NS, "ReplaceTextInDocument"): _parse_word_replace_text,
    (UI_NS, "WordReplaceText"): _parse_word_replace_text,
    (UI_NS, "SendOutlookMail"): _parse_send_outlook_mail,
    (UI_NS, "GetOutlookMailMessages"): _parse_get_outlook_mail_messages,
    (UI_NS, "SendMail"): _parse_send_mail,
    (UI_NS, "HttpClient"): _parse_http_client,
}


def parse_activity(elem: etree._Element) -> Node:
    """1つのアクティビティ要素を`uipath_dsl.types.Node`へ変換する。

    注意: `sap2010:WorkflowViewState.IdRef`属性の値(例: `"ForEach`1_1"`,
    `"Switch`1_1"`)にはWF標準のジェネリック型引数個数を表す`` `1``が付くが、
    これは**IdRef文字列内の命名規則であって、実際のXML要素タグ名には
    付かない**(`<ui:ForEach ...>`/`<Switch ...>`がそのままのタグ名)。
    """
    ns, local = _split_tag(elem.tag)
    handler = _DISPATCH.get((ns, local))
    if handler is not None:
        return handler(elem)
    return UnknownActivityNode(
        tag=f"{{{ns}}}{local}" if ns else local,
        display_name=_attr(elem, "DisplayName"),
        attrs=dict(elem.attrib),
    )


def _find_members(root: etree._Element) -> dict[str, str]:
    """`<x:Members><x:Property Name="..." Type="..." /></x:Members>`
    (知見12、ワークフロー引数宣言)。"""
    members_elem = None
    for child in _direct_children(root):
        _, local = _split_tag(child.tag)
        if local == "Members":
            members_elem = child
            break
    if members_elem is None:
        return {}
    args = {}
    for prop in _direct_children(members_elem):
        _, local = _split_tag(prop.tag)
        if local != "Property":
            continue
        name = _attr(prop, "Name")
        type_ = _attr(prop, "Type")
        if name:
            args[name] = type_ or ""
    return args


_IDENT_OR_STRING_RE = re.compile(r'"[^"]*"|\b[A-Za-z_][A-Za-z0-9_]*\b')
_BRACKETED_VB_EXPR_RE = re.compile(r"^\[(.*)\]$", re.DOTALL)


def _collect_declared_identifier_names(root: etree._Element) -> dict[str, str]:
    """知見130(【重大、未解決】として記録): VB.NETは識別子の大文字小文字を
    区別しないため、ワークフロー引数(`<x:Members><x:Property Name="...">`)
    や`<Variable Name="...">`の宣言と、本体内での参照とで大文字小文字の
    表記が揺れていても.NETコンパイラ上は同じ名前として解決される——
    しかし本トランスパイラの`render_expr`/`_render_node`は識別子参照を
    XAML中のテキストのまま素通りさせる文脈自由な純粋関数のため、揺れを
    放置すると意味的に誤った(2つの別々の)Python識別子を生成してしまう
    (`TanMzCs2025/EDSAChallengeTania2025_AmazonProductSearchAndFilter`の
    実機XAMLで発見、`out_RequirementLanCur`宣言 vs
    `Out_RequirementLanCur`参照)。

    `render.py`に文脈(宣言済み名前の集合)を渡す仕組みを新設する本格的な
    「スコープ対応のコード生成アーキテクチャ」は見送り、その代わりに
    ワークフロー全体を1回走査して宣言済みの名前(ワークフロー引数+
    (深さを問わない)全ての`Variable`)を小文字キーで収集し、`[...]`で
    囲まれたVB式の属性値テキストを宣言時の表記へ正規化する軽量な前処理
    パスとして実装する——`render.py`・`uipath_codegen/__init__.py`は
    一切変更せず、`parse_workflow_file`の入口でXML木を書き換えるだけで
    済む(宣言順で最初に見つかった表記を正規名として採用、`Variable`の
    `Name`属性自体や`[...]`で囲まれていない生リテラル値は対象外)。"""
    canonical: dict[str, str] = {}
    for name in _find_members(root):
        canonical.setdefault(name.lower(), name)
    for elem in root.iter():
        _, local = _split_tag(elem.tag)
        if local != "Variable":
            continue
        name = _attr(elem, "Name")
        if name:
            canonical.setdefault(name.lower(), name)
    return canonical


def _normalize_vb_expr_identifier_case(text: str, canonical: dict[str, str]) -> str:
    """`text`(VB式、`[...]`の内側)中の識別子トークンを`canonical`の表記へ
    正規化する。文字列リテラル(`"..."`)の内側とメンバアクセスの`.`直後
    (`obj.Foo`の`Foo`)は対象外——後者はメソッド/プロパティ名であり変数名
    ではないため、たまたま宣言済み変数名と同じ文字列でも書き換えない。"""

    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.startswith('"'):
            return token
        if match.start() > 0 and text[match.start() - 1] == ".":
            return token
        return canonical.get(token.lower(), token)

    return _IDENT_OR_STRING_RE.sub(repl, text)


def _normalize_identifier_case_in_tree(root: etree._Element, canonical: dict[str, str]) -> None:
    if not canonical:
        return
    for elem in root.iter():
        for attr_name, value in list(elem.attrib.items()):
            m = _BRACKETED_VB_EXPR_RE.match(value)
            if m is None:
                continue
            normalized = _normalize_vb_expr_identifier_case(m.group(1), canonical)
            if normalized != m.group(1):
                elem.set(attr_name, f"[{normalized}]")
        # 知見130追記: `<OutArgument x:TypeArguments="...">[Expr]</OutArgument>`
        # のように、VB式が属性値ではなく要素のテキスト内容として直列化
        # される形(`Assign.To`/`.Value`で頻出)もある——属性値と同じ
        # `[...]`検出・正規化を要素テキストにも適用する。
        if elem.text is not None:
            m = _BRACKETED_VB_EXPR_RE.match(elem.text)
            if m is not None:
                normalized = _normalize_vb_expr_identifier_case(m.group(1), canonical)
                if normalized != m.group(1):
                    elem.text = f"[{normalized}]"


def parse_workflow_file(path: str | Path) -> WorkflowFile:
    """`.xaml`ファイル1つをパースして`WorkflowFile`を返す公開エントリポイント。

    対象はProcessプロジェクトの通常ワークフロー(`x:Class`付き、ルートが
    `Sequence`または`Flowchart`のいずれか——Phase 1の決定「対象ワークフロー
    種別: Sequence/Flowchartのみ」、知見100でFlowchartの実装に着手)のみ。
    Libraryの`ActivityBuilder`形(知見26)・State Machineはv1スコープ外で、
    このパーサーも未対応(遭遇すると`ValueError`)。
    """
    try:
        tree = etree.parse(str(path))
    except etree.XMLSyntaxError as exc:
        # 知見132: `xmlns:mv="clr-namespace:Microsoft.VisualBasic;assembly=
        # Microsoft.VisualBasic, Version=10.0.0.0, Culture=neutral,
        # PublicKeyToken=..."`のような、アセンブリ完全修飾名を含む
        # `clr-namespace`形のxmlns値(`mnsy1/UiPath_ACMEVerifyAccountPositions`
        # の実機XAML、REFrameworkの`RetryCurrentTransaction.xaml`で発見
        # ——REFramework系の多数の実プロジェクトで共通して使われる極めて
        # 典型的なファイル)に対し、libxml2が「valid URIではない」と過剰に
        # 厳格な検証で拒否する既知の挙動(XML Namespaces仕様自体はxmlns値を
        # 厳密なRFC3986 URIに制限していない——空白・カンマを含むアセンブリ
        # 修飾名形式は.NET/WPF/WFの慣習として広く使われており、XAML自体は
        # 不正ではない)。このエラーメッセージに限定して`recover=True`の
        # 寛容パーサーへフォールバックする——他の種類のXML構文エラー
        # (閉じタグ不整合・切断されたファイル等)は従来通りそのまま
        # 例外を伝播させ、本物の壊れたファイルを誤って黒塗りしない。
        if "is not a valid URI" not in str(exc):
            raise
        tree = etree.parse(str(path), etree.XMLParser(recover=True))
    root = tree.getroot()
    ns, local = _split_tag(root.tag)
    if local != "Activity":
        raise ValueError(f"unsupported root element: {root.tag!r} (expected Activity)")

    # 知見130: ワークフロー引数/変数の宣言と参照とで大文字小文字の表記が
    # 揺れていても.NET上は同じ識別子として解決されるため、以降の通常の
    # パース処理が読む前にXML木を正規化する(詳細は`_collect_declared_
    # identifier_names`のdocstring参照)。
    _normalize_identifier_case_in_tree(root, _collect_declared_identifier_names(root))

    class_name = _attr(root, "Class", X_NS) or _attr(root, "Class") or ""
    if class_name == "{x:Null}":
        # 知見145: `x:Class="{x:Null}"`(`bacdillon/UiPath-Automation`の
        # 実機XAMLで発見——Studioでクラス名が未設定/削除された状態の
        # ワークフロー)。`_parse_expr`(知見13)が属性値の`{x:Null}`を
        # 一般に「未設定」として`None`へ正規化する規約と同じものを、
        # ここでも適用する——`x:Class`はこの関数だけが`_attr()`で直接
        # 読んでおり`_parse_expr`を経由しないため、この規約から漏れて
        # いた。正規化せずに放置すると`uipath_codegen`側が生成する
        # Python関数定義`def {class_name}(...)`の名前にリテラル文字列
        # `"{x:Null}"`がそのまま埋め込まれ、`def {x:Null}(...):`という
        # 構文的に無効なコードになっていた(`_safe_func_name`の既存の
        # 「空文字列なら既定名`workflow`」という安全網は、`class_name`
        # が空文字列ではなく非空の`"{x:Null}"`という文字列だったため
        # 機能していなかった)。
        class_name = ""
    arguments = _find_members(root)
    variables = _parse_variables(root)

    seq_elem = None
    flowchart_elem = None
    for child in _activity_children(root):
        c_ns, c_local = _split_tag(child.tag)
        if (c_ns, c_local) == (WF_NS, "Sequence"):
            seq_elem = child
            break
        if (c_ns, c_local) == (WF_NS, "Flowchart"):
            flowchart_elem = child
            break
    if seq_elem is None and flowchart_elem is None:
        raise ValueError(
            "no top-level <Sequence>/<Flowchart> found — State Machine roots "
            "are out of v1 scope (design/uipath_transpiler_roadmap.md Phase 1)"
        )

    root_node = _parse_sequence(seq_elem) if seq_elem is not None else _parse_flowchart(flowchart_elem)
    return WorkflowFile(
        class_name=class_name,
        root=root_node,
        arguments=arguments,
        variables=variables,
    )
