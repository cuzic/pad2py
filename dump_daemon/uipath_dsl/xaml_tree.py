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

from pathlib import Path

from lxml import etree

from .types import (
    AppendLineNode,
    AssignNode,
    BreakNode,
    CatchArm,
    ClickNode,
    DoWhileNode,
    Expr,
    ExcelApplicationScopeNode,
    ExcelWriteCellNode,
    FlowchartNode,
    FlowDecisionNode,
    FlowNode,
    FlowStepNode,
    FlowSwitchArm,
    FlowSwitchNode,
    ForEachNode,
    HttpClientNode,
    IfNode,
    InvokeCodeNode,
    InvokeWorkflowFileNode,
    Literal,
    MessageBoxNode,
    Node,
    ParallelNode,
    ReadTextFileNode,
    SendOutlookMailNode,
    SequenceNode,
    SetToClipboardNode,
    SwitchArm,
    SwitchNode,
    TryCatchNode,
    UnknownActivityNode,
    VariableDecl,
    VbExpr,
    WhileNode,
    WorkflowFile,
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
    タグ間の空白のみ)。この子要素を見つけてその`.text`を返す。"""
    if prop_elem is None:
        return None
    children = _direct_children(prop_elem)
    if not children:
        return None
    return children[0].text


def _parse_assign(elem: etree._Element) -> AssignNode:
    to_elem = _find_property_element(elem, "To")
    value_elem = _find_property_element(elem, "Value")
    target = _parse_expr(_argument_text(to_elem))
    value = _parse_expr(_argument_text(value_elem))
    return AssignNode(target=target, value=value)


def _parse_message_box(elem: etree._Element) -> MessageBoxNode:
    return MessageBoxNode(
        text=_attr_expr(elem, "Text"),
        caption=_attr_expr(elem, "Caption"),
    )


def _parse_if(elem: etree._Element) -> IfNode:
    then_elem = _find_property_element(elem, "Then")
    else_elem = _find_property_element(elem, "Else")
    return IfNode(
        condition=_attr_expr(elem, "Condition"),
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
        values=_attr_expr(elem, "Values"),
        body=body,
        type_arguments=_attr(elem, "TypeArguments", X_NS) or "x:Object",
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
        expression=_attr_expr(elem, "Expression"),
        type_arguments=_attr(elem, "TypeArguments", X_NS) or _attr(elem, "TypeArguments") or "",
        arms=arms,
    )


def _parse_while(elem: etree._Element) -> WhileNode:
    body_elem = _find_property_element(elem, "Body")
    return WhileNode(condition=_attr_expr(elem, "Condition"), body=_unwrap_body_sequence(body_elem))


def _parse_do_while(elem: etree._Element) -> DoWhileNode:
    body_elem = _find_property_element(elem, "Body")
    return DoWhileNode(
        condition=_attr_expr(elem, "Condition"), body=_unwrap_body_sequence(body_elem)
    )


def _parse_parallel(elem: etree._Element) -> ParallelNode:
    return ParallelNode(branches=[parse_activity(c) for c in _activity_children(elem)])


def _parse_click(elem: etree._Element) -> ClickNode:
    selector = None
    target_prop = _find_property_element(elem, "Target")
    if target_prop is not None:
        for child in _direct_children(target_prop):
            _, local = _split_tag(child.tag)
            if local == "Target":
                selector = _attr(child, "Selector")
    cursor_position = None
    cursor_position_prop = _find_property_element(elem, "CursorPosition")
    if cursor_position_prop is not None:
        for child in _direct_children(cursor_position_prop):
            _, local = _split_tag(child.tag)
            if local == "CursorPosition":
                cursor_position = _attr(child, "Position")
    return ClickNode(
        selector=selector,
        display_name=_attr(elem, "DisplayName"),
        click_type=_attr(elem, "ClickType"),
        mouse_button=_attr(elem, "MouseButton"),
        key_modifiers=_attr(elem, "KeyModifiers"),
        cursor_position=cursor_position,
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
    return AppendLineNode(file_name=_attr_expr(elem, "FileName"), text=_attr_expr(elem, "Text"))


def _parse_read_text_file(elem: etree._Element) -> ReadTextFileNode:
    return ReadTextFileNode(
        file_name=_attr_expr(elem, "FileName"), content=_attr_expr(elem, "Content")
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
        cell=_attr(elem, "Cell") or "",
        sheet_name=_attr(elem, "SheetName") or "",
        text=_attr_expr(elem, "Text"),
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


_HTTP_CLIENT_FALLBACK_COLLECTION_PROPS = ("Cookies", "Parameters", "UrlSegments", "Attachments")


def _http_client_dict_entries(prop_elem: etree._Element | None) -> dict[str, Expr]:
    """知見104: `ui:HttpClient.Headers`が空でない場合の実直列化形
    (`gh api search/code`でGitHub上の実機保存済みXAMLから確認、VM不使用)。
    空の場合は`<scg:Dictionary x:TypeArguments="x:String,
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
    headers = _http_client_dict_entries(_find_property_element(elem, "Headers"))
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
    (UI_NS, "MessageBox"): _parse_message_box,
    (UI_NS, "ForEach"): _parse_for_each,
    (UI_NS, "InterruptibleWhile"): _parse_while,
    (UI_NS, "InterruptibleDoWhile"): _parse_do_while,
    (UI_NS, "Break"): lambda elem: BreakNode(),
    (UI_NS, "Click"): _parse_click,
    (UI_NS, "InvokeWorkflowFile"): _parse_invoke_workflow_file,
    (UI_NS, "AppendLine"): _parse_append_line,
    (UI_NS, "ReadTextFile"): _parse_read_text_file,
    (UI_NS, "InvokeCode"): _parse_invoke_code,
    (UI_NS, "SetToClipboard"): _parse_set_to_clipboard,
    (UI_NS, "ExcelWriteCell"): _parse_excel_write_cell,
    (UI_NS, "ExcelApplicationScope"): _parse_excel_application_scope,
    (UI_NS, "SendOutlookMail"): _parse_send_outlook_mail,
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


def parse_workflow_file(path: str | Path) -> WorkflowFile:
    """`.xaml`ファイル1つをパースして`WorkflowFile`を返す公開エントリポイント。

    対象はProcessプロジェクトの通常ワークフロー(`x:Class`付き、ルートが
    `Sequence`または`Flowchart`のいずれか——Phase 1の決定「対象ワークフロー
    種別: Sequence/Flowchartのみ」、知見100でFlowchartの実装に着手)のみ。
    Libraryの`ActivityBuilder`形(知見26)・State Machineはv1スコープ外で、
    このパーサーも未対応(遭遇すると`ValueError`)。
    """
    tree = etree.parse(str(path))
    root = tree.getroot()
    ns, local = _split_tag(root.tag)
    if local != "Activity":
        raise ValueError(f"unsupported root element: {root.tag!r} (expected Activity)")

    class_name = _attr(root, "Class", X_NS) or _attr(root, "Class") or ""
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
