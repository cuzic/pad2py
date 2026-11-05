"""`uipath_dsl`のIR(`Node`) → Pythonソース文字列を生成する codegen core。

`generate_python()`が単一ファイル用の公開エントリポイント。`pad_codegen`と
同じ設計方針(値・条件式の文字列化は`render.py`に分離、未対応の構文は架空の
API呼び出しをでっち上げず`# TODO`コメントに倒す)を踏襲するが、v1スコープ
(design/uipath_transpiler_roadmap.md Phase 1)のアクティビティ種類が
`pad_codegen`の`action_id`空間よりずっと小さいため、`actions/`のような
サブパッケージへの分割はせずこのモジュール1つに収めている。

**条件式は値とは異なる失敗モードを採用する**(`pad_codegen`の
`IfActionRecord`処理と同じ判断): `If.Condition`/`While.Condition`/
`Switch.Expression`が安全にPython式へ変換できない場合、でっち上げた真偽値で
制御フロー全体を誤らせるよりコード生成自体を失敗させる(`NotImplementedError`
をそのまま伝播させる)。値(`Assign`の右辺等)が変換できない場合は
`# TODO`コメント+`None`プレースホルダへ倒す(値の誤りは局所的だが、
条件の誤りは分岐全体を反転させうるため)。

**複数ファイル結線**: `generate_project_python()`が、`Invoke Workflow File`
で参照されるサブワークフロー(同じディレクトリ内の別`.xaml`)を実際に辿り、
1つのPythonモジュールへまとめて変換する公開エントリポイント。到達できる
参照先ファイルをBFSで発見し、各ファイルを個別のPython関数として生成した上で、
`Invoke Workflow File`呼び出しをそのファイル名に対応する関数呼び出しへ
変換する(`generate_python()`はこの解決情報を持たないため単体で呼ぶと
常に`# TODO`へ倒れる、後方互換のデフォルト動作)。参照先ファイルが存在しない
場合もでっち上げず`# TODO`に倒す——相対パス解決自体の間違いである可能性を
含めて、黒箱化しない。

**変数の既定値(design/uipath_transpiler_roadmap.md Phase 5)**: `Sequence`/
`TryCatch`の`<Container.Variables>`配下に宣言された変数(`VariableDecl`)は、
そのスコープの先頭で明示的に初期化文を生成する——VB.NETの変数は明示的な
代入前でも「その型の既定値」で読めるため(Pythonのローカル変数は未代入の
参照が`NameError`になり挙動が異なる)、これを再現するために必要。
`Default`属性があればその値、無ければ`.NET`の`default(T)`相当(数値型→`0`
/`0.0`、真偽値型→`False`、それ以外(参照型・未知の型)→`None`)を使う。
数値/真偽値の型判定は`Switch`の`x:Key`数値判定(`_SWITCH_NUMERIC_TYPES`)と
同じ既知の型タグ集合のみを信頼し、未知の型は安全側の`None`に倒す。
"""
from __future__ import annotations

import json
from pathlib import Path

from ..uipath_dsl.types import (
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
    MessageBoxNode,
    Node,
    ParallelNode,
    ReadTextFileNode,
    SendOutlookMailNode,
    SequenceNode,
    SetToClipboardNode,
    SwitchNode,
    TryCatchNode,
    UnknownActivityNode,
    VariableDecl,
    WhileNode,
    WorkflowFile,
)
from ..uipath_dsl.xaml_tree import parse_workflow_file
from ..uipath_selector import selector_text_to_pywinauto
from .render import (
    VB_ADD_HELPER_NAME,
    VB_ADD_HELPER_SOURCE,
    VB_AND_HELPER_NAME,
    VB_AND_HELPER_SOURCE,
    VB_BOOL_HELPER_NAME,
    VB_BOOL_HELPER_SOURCE,
    VB_CDBL_HELPER_NAME,
    VB_CDBL_HELPER_SOURCE,
    VB_CMP_HELPER_NAME,
    VB_CMP_HELPER_SOURCE,
    VB_CSTR_HELPER_NAME,
    VB_CSTR_HELPER_SOURCE,
    VB_DIV_HELPER_NAME,
    VB_DIV_HELPER_SOURCE,
    VB_MOD_HELPER_NAME,
    VB_MOD_HELPER_SOURCE,
    VB_NUM_HELPER_NAME,
    VB_NUM_HELPER_SOURCE,
    VB_OR_HELPER_NAME,
    VB_OR_HELPER_SOURCE,
    VB_XOR_HELPER_NAME,
    VB_XOR_HELPER_SOURCE,
    render_expr,
)

INDENT = "    "

__all__ = [
    "INDENT",
    "generate_python",
    "generate_project_python",
    "generate_project_from_json",
]

# .NET例外型名 → Pythonの組み込み例外へのマッピング。知見確認済みの
# `s:Exception`(`System.Exception`のCLR名前空間エイリアス表記、知見6)
# 以外は未確認——未知の型は無条件で`Exception`にフォールバックする
# (個別の.NET例外階層をPythonの例外階層へ精密対応させることは
# v1スコープ外)。
_EXCEPTION_TYPE_MAP = {
    "s:exception": "Exception",
    "system.exception": "Exception",
}


def generate_python(
    workflow: WorkflowFile,
    invoke_resolver: dict[str, str] | None = None,
    func_name: str | None = None,
) -> str:
    """`WorkflowFile`(`uipath_dsl.parse_workflow_file()`の戻り値)から
    スタンドアロンのPython関数定義ソースを生成する(末尾改行付き)。

    ワークフロー引数(`workflow.arguments`)をそのまま関数の仮引数にする。

    `invoke_resolver`は`Invoke Workflow File`の`workflow_file`属性文字列
    (例: `"Sub1.xaml"`)→呼び出し先Python関数名の対応表。単体で
    `generate_python()`を呼ぶ場合は省略してよく、その場合は全ての
    `Invoke Workflow File`が`# TODO`に倒れる(`generate_project_python()`
    参照)。

    `func_name`は定義する関数名を`class_name`由来のデフォルトから上書きする
    (`generate_project_python()`が同名クラスの衝突を避けるために使う)。
    """
    params = list(workflow.arguments.keys())
    name = func_name or _safe_func_name(workflow.class_name)
    header = f"def {name}({', '.join(params)}):"
    body = _generate_node(workflow.root, indent=1, invoke_resolver=invoke_resolver)
    body = _ensure_nonempty_suite(body, indent=1)
    imports = _collect_imports(body)
    lines = [*imports, ""] if imports else []
    lines.extend([header, *body])
    return "\n".join(lines) + "\n"


def _safe_func_name(class_name: str) -> str:
    return class_name.replace(" ", "_").replace("-", "_") or "workflow"


def _collect_imports(body: list[str]) -> list[str]:
    imports = []
    if any("pyperclip." in line for line in body):
        imports.append("import pyperclip")
    if any("Desktop(" in line for line in body):
        imports.append("from pywinauto import Desktop")
    imports.sort()
    # `_vb_cstr`(CStr/`&`の変換先、知見46)はヘルパー関数定義そのものを
    # 未使用時に増やさないよう、使われている場合のみ注入する——
    # import文とは違い複数行の定義なので、importのソート対象外で末尾に
    # 追加する。
    if any(f"{VB_CSTR_HELPER_NAME}(" in line for line in body):
        imports.append(VB_CSTR_HELPER_SOURCE.rstrip("\n"))
    # `_vb_cmp`(比較演算子の型変換先、知見47)も同じ理由で使用時のみ注入する。
    if any(f"{VB_CMP_HELPER_NAME}(" in line for line in body):
        imports.append(VB_CMP_HELPER_SOURCE.rstrip("\n"))
    # `_vb_add`(`+`演算子の型混在ディスパッチ先、知見48)も同様。
    if any(f"{VB_ADD_HELPER_NAME}(" in line for line in body):
        imports.append(VB_ADD_HELPER_SOURCE.rstrip("\n"))
    # `_vb_num`(`-`/`*`/`/`/`Mod`/`\`の数値強制先、知見49)も同様。
    if any(f"{VB_NUM_HELPER_NAME}(" in line for line in body):
        imports.append(VB_NUM_HELPER_SOURCE.rstrip("\n"))
    # `_vb_div`(`/`のゼロ除算処理先、知見50)も同様。
    if any(f"{VB_DIV_HELPER_NAME}(" in line for line in body):
        imports.append(VB_DIV_HELPER_SOURCE.rstrip("\n"))
    # `_vb_cdbl`(`CDbl`のNothing/桁区切り文字列強制先、知見52)も同様。
    if any(f"{VB_CDBL_HELPER_NAME}(" in line for line in body):
        imports.append(VB_CDBL_HELPER_SOURCE.rstrip("\n"))
    # `_vb_mod`(`Mod`のゼロ除算の型依存処理先、知見54)も同様。
    if any(f"{VB_MOD_HELPER_NAME}(" in line for line in body):
        imports.append(VB_MOD_HELPER_SOURCE.rstrip("\n"))
    # `_vb_and`/`_vb_or`/`_vb_xor`(`And`/`Or`/`Xor`の`Nothing`処理先、
    # 知見59)も同様。
    if any(f"{VB_AND_HELPER_NAME}(" in line for line in body):
        imports.append(VB_AND_HELPER_SOURCE.rstrip("\n"))
    if any(f"{VB_OR_HELPER_NAME}(" in line for line in body):
        imports.append(VB_OR_HELPER_SOURCE.rstrip("\n"))
    if any(f"{VB_XOR_HELPER_NAME}(" in line for line in body):
        imports.append(VB_XOR_HELPER_SOURCE.rstrip("\n"))
    # `_vb_bool`(`AndAlso`/`OrElse`のBoolean変換先、知見60)も同様。
    if any(f"{VB_BOOL_HELPER_NAME}(" in line for line in body):
        imports.append(VB_BOOL_HELPER_SOURCE.rstrip("\n"))
    return imports


def _generate_body(
    nodes: list[Node], indent: int, invoke_resolver: dict[str, str] | None = None
) -> list[str]:
    lines: list[str] = []
    for node in nodes:
        lines.extend(_generate_node(node, indent, invoke_resolver))
    return lines


def _ensure_nonempty_suite(lines: list[str], indent: int) -> list[str]:
    """`pad_codegen._ensure_nonempty_suite`と同じ理由(design/dsl_format_findings.md
    知見40): `# TODO`コメント行だけの本体はPython構文上は空のsuiteと同じで
    `IndentationError`になるため、実質的な文が1つも無ければ`pass`を補う。
    """
    if any(line.strip() and not line.strip().startswith("#") for line in lines):
        return lines
    return [*lines, f"{INDENT * indent}pass"]


def _todo_value(prefix: str, expr_desc: str) -> list[str]:
    """値が安全に変換できなかった場合の`# TODO`+プレースホルダ出力
    (`pad_codegen`の`SetVariableRecord`処理と同じ安全側フォールバック)。
    呼び出し側が代入文等に組み込む。"""
    return [f"{prefix}# TODO: unresolved VB expression: {expr_desc}"]


def _render_value_or_todo(expr, prefix: str, todo_lines: list[str]) -> str:
    try:
        return render_expr(expr)
    except NotImplementedError as e:
        todo_lines.extend(_todo_value(prefix, str(e)))
        return "None"


def _generate_node(
    node: Node, indent: int, invoke_resolver: dict[str, str] | None = None
) -> list[str]:
    prefix = INDENT * indent
    if isinstance(node, SequenceNode):
        return [
            *_generate_variable_inits(node.variables, indent),
            *_generate_body(node.body, indent, invoke_resolver),
        ]
    if isinstance(node, AssignNode):
        return _generate_assign(node, indent)
    if isinstance(node, MessageBoxNode):
        return _generate_message_box(node, indent)
    if isinstance(node, IfNode):
        return _generate_if(node, indent, invoke_resolver)
    if isinstance(node, ForEachNode):
        return _generate_for_each(node, indent, invoke_resolver)
    if isinstance(node, TryCatchNode):
        return _generate_try_catch(node, indent, invoke_resolver)
    if isinstance(node, SwitchNode):
        return _generate_switch(node, indent, invoke_resolver)
    if isinstance(node, WhileNode):
        return _generate_while(node, indent, invoke_resolver)
    if isinstance(node, DoWhileNode):
        return _generate_do_while(node, indent, invoke_resolver)
    if isinstance(node, BreakNode):
        return [f"{prefix}break"]
    if isinstance(node, ParallelNode):
        return _generate_parallel(node, indent, invoke_resolver)
    if isinstance(node, AppendLineNode):
        return _generate_append_line(node, indent)
    if isinstance(node, ReadTextFileNode):
        return _generate_read_text_file(node, indent)
    if isinstance(node, SetToClipboardNode):
        return _generate_set_to_clipboard(node, indent)
    if isinstance(node, ClickNode):
        return _generate_click(node, indent)
    if isinstance(node, InvokeWorkflowFileNode):
        return _generate_invoke_workflow_file(node, indent, invoke_resolver)
    if isinstance(node, (InvokeCodeNode, ExcelApplicationScopeNode, ExcelWriteCellNode,
                          SendOutlookMailNode, HttpClientNode)):
        return _generate_unresolved_activity(node, indent)
    if isinstance(node, UnknownActivityNode):
        return _generate_unknown(node, indent)
    raise TypeError(f"Unsupported node type for codegen: {type(node)!r}")


def _generate_assign(node: AssignNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    todo: list[str] = []
    target = _render_value_or_todo(node.target, prefix, todo)
    value = _render_value_or_todo(node.value, prefix, todo)
    return [*todo, f"{prefix}{target} = {value}"]


def _generate_message_box(node: MessageBoxNode, indent: int) -> list[str]:
    """`ui:MessageBox`はPythonのネイティブ対話ダイアログに相当するものが
    無いため、最も単純で誤解の少ない代替としてコンソール出力`print()`に
    変換する(確定的な仕様ではなく、v1の暫定的な既定選択——将来tkinter等の
    実モーダルダイアログへ差し替える余地を残す)。"""
    prefix = INDENT * indent
    todo: list[str] = []
    text = _render_value_or_todo(node.text, prefix, todo)
    return [*todo, f"{prefix}print({text})"]


def _generate_if(
    node: IfNode, indent: int, invoke_resolver: dict[str, str] | None = None
) -> list[str]:
    prefix = INDENT * indent
    # 条件式は値より厳格——変換できなければ例外を伝播させてコード生成自体を
    # 失敗させる(モジュールdocstring参照)。`If...Then...Else Statement`
    # ページが「conditionはTrue/Falseに評価できるか、暗黙的にBooleanへ
    # 変換可能な型」と明記しているため(知見61)、`_vb_bool()`(知見60の
    # `AndAlso`/`OrElse`と同じヘルパー)で明示的にBooleanへ変換する——
    # Pythonの`if`文自体の素の真偽値判定(`bool(文字列)`は空文字列以外
    # 常に`True`)はVBのCBool規則と食い違う(例: `If someStr Then`で
    # `someStr`が`"False"`/`"0"`の場合、VBは`False`扱いだがPythonの
    # 素の`if "False":`は`True`になる)。
    cond = render_expr(node.condition)
    lines = [f"{prefix}if {VB_BOOL_HELPER_NAME}({cond}):"]
    then_body = _ensure_nonempty_suite(
        _generate_body(node.then_body, indent + 1, invoke_resolver), indent + 1
    )
    lines.extend(then_body)
    if node.else_body:
        lines.append(f"{prefix}else:")
        else_body = _ensure_nonempty_suite(
            _generate_body(node.else_body, indent + 1, invoke_resolver), indent + 1
        )
        lines.extend(else_body)
    return lines


def _generate_for_each(
    node: ForEachNode, indent: int, invoke_resolver: dict[str, str] | None = None
) -> list[str]:
    prefix = INDENT * indent
    values = render_expr(node.values)
    lines = [f"{prefix}for {node.item_var or '_item'} in {values}:"]
    body = _ensure_nonempty_suite(
        _generate_body(node.body, indent + 1, invoke_resolver), indent + 1
    )
    lines.extend(body)
    return lines


def _generate_while(
    node: WhileNode, indent: int, invoke_resolver: dict[str, str] | None = None
) -> list[str]:
    prefix = INDENT * indent
    # `While`の条件も`If`と同じBoolean変換規則に従う(知見61)。
    cond = render_expr(node.condition)
    lines = [f"{prefix}while {VB_BOOL_HELPER_NAME}({cond}):"]
    body = _ensure_nonempty_suite(
        _generate_body(node.body, indent + 1, invoke_resolver), indent + 1
    )
    lines.extend(body)
    return lines


def _generate_do_while(
    node: DoWhileNode, indent: int, invoke_resolver: dict[str, str] | None = None
) -> list[str]:
    """WFの`InterruptibleDoWhile`に相当するPythonネイティブ構文は無いため、
    `while True: ... ; if not (cond): break`の定石パターンへ変換する。
    `Condition`が未設定(本fixtureでの実例、design/uipath_xaml_findings.md
    知見38相当)の場合は意図が不明なため変換せずTODOに倒す。"""
    prefix = INDENT * indent
    if node.condition is None:
        return [f"{prefix}# TODO: Do While with no Condition set — intent unclear"]
    # `DoWhile`の条件も`If`/`While`と同じBoolean変換規則に従う(知見61)。
    cond = render_expr(node.condition)
    lines = [f"{prefix}while True:"]
    body = _generate_body(node.body, indent + 1, invoke_resolver)
    body.append(f"{INDENT * (indent + 1)}if not ({VB_BOOL_HELPER_NAME}({cond})):")
    body.append(f"{INDENT * (indent + 2)}break")
    lines.extend(_ensure_nonempty_suite(body, indent + 1))
    return lines


def _generate_try_catch(
    node: TryCatchNode, indent: int, invoke_resolver: dict[str, str] | None = None
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_variable_inits(node.variables, indent)
    lines.append(f"{prefix}try:")
    try_body = _ensure_nonempty_suite(
        _generate_body(node.try_body, indent + 1, invoke_resolver), indent + 1
    )
    lines.extend(try_body)
    for catch in node.catches:
        exc_type = _EXCEPTION_TYPE_MAP.get(catch.exception_type.lower(), "Exception")
        as_clause = f" as {catch.var_name}" if catch.var_name else ""
        lines.append(f"{prefix}except {exc_type}{as_clause}:")
        body = _ensure_nonempty_suite(
            _generate_body(catch.body, indent + 1, invoke_resolver), indent + 1
        )
        lines.extend(body)
    if node.finally_body:
        lines.append(f"{prefix}finally:")
        body = _ensure_nonempty_suite(
            _generate_body(node.finally_body, indent + 1, invoke_resolver), indent + 1
        )
        lines.extend(body)
    return lines


# `Switch`の`x:TypeArguments`がこれらの数値型の場合、`x:Key`属性値
# (常に文字列として取得される、`uipath_dsl.xaml_tree._parse_switch`参照)を
# クォート無しの数値リテラルとして出力する——`x:Object`等そのほかの型は
# 安全側に倒して文字列リテラル扱いのままにする(実機で非数値キーの実例が
# まだ無いため、過剰に賢い推測はしない)。
_SWITCH_NUMERIC_TYPES = {
    "x:int32", "x:int16", "x:int64", "x:byte", "x:double", "x:single", "x:decimal",
}


def _render_switch_key(key: str, type_arguments: str) -> str:
    if type_arguments.lower() in _SWITCH_NUMERIC_TYPES:
        return key
    return repr(key)


_BOOLEAN_TYPES = {"x:boolean"}


def _default_value_literal(type_arguments: str) -> str:
    """`Default`が明示されていない変数宣言の初期値——.NETの`default(T)`相当。
    数値型は`0`/`0.0`、真偽値型は`False`、それ以外(参照型・未知の型)は
    `Nothing`相当の`None`に倒す(型の語彙は`_SWITCH_NUMERIC_TYPES`と同じ
    既知集合のみ信頼し、未知の型を誤って数値/真偽値扱いしない)。"""
    type_tag = type_arguments.lower()
    if type_tag in _SWITCH_NUMERIC_TYPES:
        return "0.0" if type_tag in {"x:double", "x:single", "x:decimal"} else "0"
    if type_tag in _BOOLEAN_TYPES:
        return "False"
    return "None"


def _render_variable_init(decl: VariableDecl) -> str:
    if decl.default is None:
        value = _default_value_literal(decl.type_arguments)
    else:
        type_tag = decl.type_arguments.lower()
        if type_tag in _SWITCH_NUMERIC_TYPES:
            value = decl.default
        elif type_tag in _BOOLEAN_TYPES:
            value = "True" if decl.default.strip().lower() == "true" else "False"
        else:
            value = repr(decl.default)
    return f"{decl.name} = {value}"


def _generate_variable_inits(variables: list[VariableDecl], indent: int) -> list[str]:
    """`Sequence`/`TryCatch`の`<Container.Variables>`配下の変数を、その
    スコープの先頭で初期化する文に変換する(モジュールdocstring「変数の
    既定値」節参照)。"""
    prefix = INDENT * indent
    return [f"{prefix}{_render_variable_init(v)}" for v in variables]


def _generate_switch(
    node: SwitchNode, indent: int, invoke_resolver: dict[str, str] | None = None
) -> list[str]:
    prefix = INDENT * indent
    expr = render_expr(node.expression)
    lines: list[str] = []
    default_arm = None
    value_arms = []
    for arm in node.arms:
        if arm.key is None:
            default_arm = arm
        else:
            value_arms.append(arm)
    for i, arm in enumerate(value_arms):
        keyword = "if" if i == 0 else "elif"
        key_literal = _render_switch_key(arm.key, node.type_arguments)
        lines.append(f"{prefix}{keyword} {expr} == {key_literal}:")
        body = _ensure_nonempty_suite(
            _generate_body(arm.body, indent + 1, invoke_resolver), indent + 1
        )
        lines.extend(body)
    if default_arm is not None:
        header = "else" if value_arms else "if True"
        lines.append(f"{prefix}{header}:")
        body = _ensure_nonempty_suite(
            _generate_body(default_arm.body, indent + 1, invoke_resolver), indent + 1
        )
        lines.extend(body)
    if not lines:
        return [f"{prefix}# TODO: Switch with no arms: {expr}"]
    return lines


def _generate_parallel(
    node: ParallelNode, indent: int, invoke_resolver: dict[str, str] | None = None
) -> list[str]:
    """WFの`Parallel`(複数ブランチを並行実行)に相当するPythonネイティブの
    軽量な代替は無いため、v1では**ブランチを単純に順次実行**する
    (でっち上げた並行実行を装わない、明示的なコメント付きの簡略化)。"""
    prefix = INDENT * indent
    lines = [f"{prefix}# NOTE: source used Parallel; branches run sequentially here"]
    for branch in node.branches:
        lines.extend(_generate_node(branch, indent, invoke_resolver))
    return lines


def _generate_append_line(node: AppendLineNode, indent: int) -> list[str]:
    """`Text`は`InArgument<String>`型(知見15)——非文字列式が束縛された場合、
    VBは`CStr`と同じ書式規則で暗黙に文字列化する(知見46参照)。実機で
    捕捉した実例(design/evidence/uipath_xaml_probe/Main.xaml)は常に
    リテラル文字列`Text="hello"`で、この暗黙変換が実際に発生する実例は
    無いが、Studioが数値式を明示的な`CStr(...)`へ自動変換せずそのまま
    保存した場合に備え、単純な`str()`ではなく`CStr`/`&`と同じ`_vb_cstr()`
    を使う(知見46の修正と一貫性を取るための内部的な安全策——`node.text`が
    既に`CStr(...)`を含む場合は`_vb_cstr(_vb_cstr(x))`の二重適用になるが、
    `_vb_cstr`は冪等(文字列への再適用は`str`分岐を素通りするだけ)なので
    実害は無い)。"""
    prefix = INDENT * indent
    todo: list[str] = []
    file_name = _render_value_or_todo(node.file_name, prefix, todo)
    text = _render_value_or_todo(node.text, prefix, todo)
    return [
        *todo,
        f'{prefix}with open({file_name}, "a", encoding="utf-8") as _f:',
        f'{INDENT * (indent + 1)}_f.write({VB_CSTR_HELPER_NAME}({text}) + "\\n")',
    ]


def _generate_read_text_file(node: ReadTextFileNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    todo: list[str] = []
    file_name = _render_value_or_todo(node.file_name, prefix, todo)
    target = _render_value_or_todo(node.content, prefix, todo)
    return [
        *todo,
        f'{prefix}{target} = open({file_name}, encoding="utf-8").read()',
    ]


def _generate_set_to_clipboard(node: SetToClipboardNode, indent: int) -> list[str]:
    """`Text`は`Append Line`と同じ`InArgument<String>`型——同じ理由
    (知見46、`_generate_append_line`参照)で`_vb_cstr()`を使う。`pyperclip`
    自体は非文字列を渡されても内部でPythonの`str()`を呼んで落ちはしない
    (`pyperclip/__init__.py`の各バックエンド実装で確認済み)が、それだと
    VBのG書式と食い違う文字列がクリップボードに載ってしまう。"""
    prefix = INDENT * indent
    todo: list[str] = []
    text = _render_value_or_todo(node.text, prefix, todo)
    return [*todo, f"{prefix}pyperclip.copy({VB_CSTR_HELPER_NAME}({text}))"]


def _generate_click(node: ClickNode, indent: int) -> list[str]:
    """`ui:Click`のセレクタ(design/uipath_xaml_findings.md 知見37参照)を
    `uipath_selector`でpywinautoの検索条件連鎖へマッピングする。属性の
    「名前」の対応は机上の推定、`role`の「値」はUIAの`ControlType`語彙との
    一致を未検証のまま渡している——両方とも警告コメントとして生成コードに
    残し、実機で要素を一意特定できることまでは主張しない。マッピング可能な
    属性が1つも無かった場合(セレクタ自体が無い場合含む)は、でっち上げる
    くらいなら`# TODO`に倒す。"""
    prefix = INDENT * indent
    if not node.selector:
        return [f"{prefix}# TODO: Click with no selector captured"]
    rendered = selector_text_to_pywinauto(node.selector)
    if rendered.expr == 'Desktop(backend="uia")':
        return [
            f"{prefix}# TODO: Click selector had no mappable attributes: {node.selector}"
        ]
    lines = [f"{prefix}# WARNING: {w}" for w in rendered.warnings]
    lines.append(f"{prefix}{rendered.expr}.click_input()")
    return lines


def _generate_invoke_workflow_file(
    node: InvokeWorkflowFileNode, indent: int, invoke_resolver: dict[str, str] | None
) -> list[str]:
    """`invoke_resolver`(`generate_project_python()`が構築する、
    `workflow_file`文字列→Python関数名の対応表)に解決先が見つかった場合のみ
    実際の関数呼び出しへ変換する。単体の`generate_python()`呼び出し
    (`invoke_resolver=None`)や、参照先が解決できなかった場合は、
    呼び出し先の存在を仮定した架空のコードをでっち上げず`# TODO`に倒す。"""
    prefix = INDENT * indent
    func_name = (invoke_resolver or {}).get(node.workflow_file)
    if func_name is None:
        return [f"{prefix}# TODO: unresolved Invoke Workflow File: {node.workflow_file}"]
    todo: list[str] = []
    kwargs = []
    for key, expr in node.arguments.items():
        value = _render_value_or_todo(expr, prefix, todo)
        kwargs.append(f"{key}={value}")
    return [*todo, f"{prefix}{func_name}({', '.join(kwargs)})"]


def _generate_unresolved_activity(node, indent: int) -> list[str]:
    """design/uipath_transpiler_roadmap.md Phase 4で未解決と明記した項目
    (インラインコード・ライブExcel/Outlook連携・`HttpClient`のHeaders等
    プロパティ要素未パース)——架空の変換をでっち上げず`# TODO`に倒す。
    `Invoke Workflow File`自体は`_generate_invoke_workflow_file`が担当する
    (`generate_project_python()`経由であれば実関数呼び出しへ解決される)。"""
    prefix = INDENT * indent
    return [f"{prefix}# TODO: unsupported in v1 codegen: {type(node).__name__}"]


def _generate_unknown(node: UnknownActivityNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    display = f" ({node.display_name})" if node.display_name else ""
    return [f"{prefix}# TODO: unknown activity{display}: {node.tag}"]


# --- 複数ファイル結線(generate_project_python) -----------------------------

# 子ノードリストを持つ複合ノード種別 → それらのリストの一覧。
# `Invoke Workflow File`参照の発見(`_iter_invoke_nodes`)専用の走査であり、
# codegen本体の`_generate_node`ディスパッチとは別の関心事(静的な呼び出し
# グラフ解析 vs コード生成)のため意図的に分離している。
def _child_node_lists(node: Node) -> list[list[Node]]:
    if isinstance(node, SequenceNode):
        return [node.body]
    if isinstance(node, IfNode):
        lists = [node.then_body]
        if node.else_body:
            lists.append(node.else_body)
        return lists
    if isinstance(node, (ForEachNode, WhileNode, DoWhileNode)):
        return [node.body]
    if isinstance(node, TryCatchNode):
        lists = [node.try_body, *(c.body for c in node.catches)]
        if node.finally_body:
            lists.append(node.finally_body)
        return lists
    if isinstance(node, SwitchNode):
        return [arm.body for arm in node.arms]
    if isinstance(node, ParallelNode):
        return [node.branches]
    return []


def _iter_invoke_nodes(nodes: list[Node]):
    """`nodes`配下(任意の深さにネストした分岐・ループ・try/catch内含む)の
    `InvokeWorkflowFileNode`を全て列挙する。"""
    for node in nodes:
        if isinstance(node, InvokeWorkflowFileNode):
            yield node
        for child_list in _child_node_lists(node):
            yield from _iter_invoke_nodes(child_list)


def _discover_workflow_files(
    path: Path, cache: dict[Path, WorkflowFile], order: list[Path]
) -> None:
    """`path`から`Invoke Workflow File`で到達可能な`.xaml`をBFS的に発見し、
    `cache`/`order`へ積む。参照先が実在しない(相対パス解決の誤り、または
    単に未提供)場合はそこで探索を打ち切る——存在しないファイルをでっち上げて
    解決済みと偽ることはしない(`generate_project_python`側で`# TODO`に
    倒れる)。"""
    if path in cache:
        return
    wf = parse_workflow_file(path)
    cache[path] = wf
    order.append(path)
    for inv in _iter_invoke_nodes(wf.root.body):
        target = (path.parent / inv.workflow_file).resolve()
        if target.is_file():
            _discover_workflow_files(target, cache, order)


def _unique_func_names(order: list[Path], cache: dict[Path, WorkflowFile]) -> dict[Path, str]:
    used: set[str] = set()
    names: dict[Path, str] = {}
    for p in order:
        base = _safe_func_name(cache[p].class_name)
        name = base
        n = 2
        while name in used:
            name = f"{base}_{n}"
            n += 1
        used.add(name)
        names[p] = name
    return names


def _build_invoke_resolver(
    path: Path,
    wf: WorkflowFile,
    func_names: dict[Path, str],
) -> dict[str, str]:
    resolver: dict[str, str] = {}
    for inv in _iter_invoke_nodes(wf.root.body):
        target = (path.parent / inv.workflow_file).resolve()
        if target in func_names:
            resolver[inv.workflow_file] = func_names[target]
    return resolver


def generate_project_python(entry_path: str | Path) -> str:
    """`entry_path`から`Invoke Workflow File`で到達可能な全`.xaml`を
    1つのPythonモジュール(複数の`def`を並べたソース文字列)へ変換する。

    各ファイルは個別のPython関数になり、ファイル間の`Invoke Workflow File`
    呼び出しは対応する関数呼び出しへ変換される(到達できなかった参照は
    `generate_python()`単体呼び出しと同じく`# TODO`に倒れる)。
    """
    entry = Path(entry_path).resolve()
    cache: dict[Path, WorkflowFile] = {}
    order: list[Path] = []
    _discover_workflow_files(entry, cache, order)
    func_names = _unique_func_names(order, cache)

    parts = []
    for p in order:
        wf = cache[p]
        resolver = _build_invoke_resolver(p, wf, func_names)
        parts.append(
            generate_python(wf, invoke_resolver=resolver, func_name=func_names[p]).rstrip("\n")
        )
    return "\n\n\n".join(parts) + "\n"


def generate_project_from_json(project_dir: str | Path) -> str:
    """`project.json`からエントリポイント(`"main"`フィールド、知見27)を
    読み取り、`generate_project_python()`を呼ぶ便利関数。

    v1スコープ(design/uipath_transpiler_roadmap.md Phase 1)はProcess
    プロジェクトのみのため、`designOptions.outputType`が`"Process"`以外
    (例: `"Library"`、知見26の`ActivityBuilder`形は`uipath_dsl`が未対応)
    の場合は`ValueError`で明示的に拒否する——`parse_workflow_file`が
    Flowchart/State Machineを拒否するのと同じ、スコープ外を黙って
    誤変換しない方針。
    """
    project_dir = Path(project_dir)
    project_json_path = project_dir / "project.json"
    data = json.loads(project_json_path.read_text(encoding="utf-8"))

    output_type = data.get("designOptions", {}).get("outputType")
    if output_type is not None and output_type != "Process":
        raise ValueError(
            f"unsupported project outputType: {output_type!r} (expected 'Process', "
            "v1 scope per design/uipath_transpiler_roadmap.md Phase 1)"
        )

    main = data.get("main")
    if not main:
        raise ValueError(f"project.json has no 'main' entry point: {project_json_path}")

    return generate_project_python(project_dir / main)
