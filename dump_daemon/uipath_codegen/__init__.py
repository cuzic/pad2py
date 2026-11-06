"""`uipath_dsl`のIR(`Node`) → Pythonソース文字列を生成する codegen core。

`generate_python()`が単一ファイル用の公開エントリポイント。`pad_codegen`と
同じ設計方針(値・条件式の文字列化は`render.py`に分離、未対応の構文は架空の
API呼び出しをでっち上げず`# TODO`コメントに倒す)を踏襲するが、v1スコープ
(design/uipath_transpiler_roadmap.md Phase 1)のアクティビティ種類が
`pad_codegen`の`action_id`空間よりずっと小さいため、`actions/`のような
サブパッケージへの分割はせずこのモジュール1つに収めている。

**条件式は値とは異なる失敗モードを採用する**(`pad_codegen`の
`IfActionRecord`処理と同じ判断): `If.Condition`/`While.Condition`/
`DoWhile.Condition`/`Switch.Expression`/`ForEach.Values`が安全に
Python式へ変換できない場合、でっち上げた真偽値/反復対象で制御フロー
全体を誤らせるよりコード生成自体を失敗させる(`NotImplementedError`
をそのまま伝播させる)。値(`Assign`の右辺等)が変換できない場合は
`# TODO`コメント+`None`プレースホルダへ倒す(値の誤りは局所的だが、
条件・反復対象の誤りは分岐/ループ全体に影響するため)。

知見155追記: `ForEach.Values`はこの一覧に当初明記されていなかったが、
`_generate_for_each`の実装は(ドキュメント化されていないまま)既に
このモジュールが元から持つ厳格モードを採用していた——実機XAML
(`plaah/web-application-with-rpa-dhl`、未確認の`config(...)`関数呼び出し
を`Values`に含む)で実際にこの経路を踏んだ際に発見し、当初は見落としか
意図的な設計か不明な論点として記録していたが、再検討の結果「反復対象を
誤って推測すると、ループの**全ての**反復が間違ったデータに対して実行
される」というのは「分岐全体を反転させる」のと同じ、むしろそれ以上の
影響範囲を持つ失敗モードであり、`Assign`の右辺1箇所限定の誤りとは
性質が異なると判断——既存の実装(厳格モード)を変更せず、この
docstringへ`ForEach.Values`を正式に明記することで方針を確定した。

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
import re
from pathlib import Path

from openpyxl.utils import column_index_from_string
from openpyxl.utils.cell import coordinate_from_string
from openpyxl.utils.exceptions import CellCoordinatesException

from ..uipath_dsl.types import (
    ActivateNode,
    AppendLineNode,
    AssignNode,
    AttachWindowNode,
    BreakNode,
    BuildDataTableNode,
    CheckNode,
    ClickNode,
    CloseApplicationNode,
    CloseTabNode,
    CloseWindowNode,
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
    FlowStepNode,
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
    KillProcessNode,
    Literal,
    LogMessageNode,
    MessageBoxNode,
    MultipleAssignNode,
    Node,
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
    VariableDecl,
    VbExpr,
    WhileNode,
    WordApplicationScopeNode,
    WordReplaceTextNode,
    WorkflowFile,
    WriteLineNode,
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


def _collect_out_arg_names(arguments: dict[str, str]) -> frozenset[str]:
    """知見78・86: `workflow.arguments`の値(`<x:Property Type="...">`の
    生テキスト、例: `"InArgument(x:String)"`)が`OutArgument`/
    `InOutArgument`で始まる引数名の集合を返す——`generate_python()`
    (呼び出し先の関数本体への`# TODO`追記)と`generate_project_python()`
    (呼び出し元側への`# WARNING`追記、知見86)の両方で同じ判定基準を
    共有するための共通ヘルパー。"""
    return frozenset(
        arg_name
        for arg_name, type_str in arguments.items()
        if type_str.lower().startswith(("outargument", "inoutargument"))
    )


def generate_python(
    workflow: WorkflowFile,
    invoke_resolver: dict[str, str] | None = None,
    func_name: str | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
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

    知見78: `workflow.arguments`の値(`<x:Property Type="...">`の生テキスト、
    例: `"InArgument(x:String)"`)が`OutArgument`/`InOutArgument`で始まる
    場合、VBの引数方向付きByRef渡し(呼び出し元の変数へ結果を書き戻す)に
    相当するPython機能は無い——Pythonの関数パラメータは常に値渡しで、
    関数側での再代入は呼び出し元に伝播しない。架空の戻り値バインディング
    (`return`文の追加や呼び出し側での`var = func(...)`への変換)をでっち
    上げる代わりに、関数本体の先頭に`# TODO`を1行追記して明示する
    ——関数自体は(`In`方向の引数は問題無く機能するため)生成を続ける。

    知見86: `invoke_resolver`と同じキー(`workflow_file`文字列)で、その
    呼び出し先が持つOut/InOutArgument方向の引数名集合を渡す
    `out_arg_resolver`——`_generate_invoke_workflow_file`が呼び出し元側の
    `Invoke Workflow File`呼び出し文自身にも`# WARNING`を付けられるように
    する(知見78は呼び出し先の関数定義側にしか`# TODO`が出ず、呼び出し元
    の呼び出し文には何の手がかりも残らなかった、という残課題の解消)。
    `generate_project_python()`経由でのみ構築され、単体の
    `generate_python()`呼び出しでは省略してよい(その場合は警告無し、
    既存の後方互換動作のまま)。"""
    params = list(workflow.arguments.keys())
    name = func_name or _safe_func_name(workflow.class_name)
    header = f"def {name}({', '.join(params)}):"
    body = _generate_node(
        workflow.root, indent=1, invoke_resolver=invoke_resolver, out_arg_resolver=out_arg_resolver
    )
    out_params = _collect_out_arg_names(workflow.arguments)
    if out_params:
        body = [
            f"{INDENT}# TODO: argument(s) {', '.join(sorted(out_params))} are Out/InOutArgument "
            "— VB ByRef write-back to the caller's variable is not supported, Python "
            "parameters are always by-value; the caller will not see any updated value",
            *body,
        ]
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
    # `send_keys`(`CloseTab`→`send_keys('^w')`変換先、知見170——対象を
    # 指定しないグローバルなキー送信)も同様。
    if any("send_keys(" in line for line in body):
        imports.append("from pywinauto.keyboard import send_keys")
    # `requests`(`HttpClient`→`requests.request(...)`変換先、知見96)も同様。
    if any("requests.request(" in line for line in body):
        imports.append("import requests")
    # `openpyxl`(`ExcelApplicationScope`→`openpyxl.load_workbook(...)`変換先、
    # 知見97)も同様。
    if any("openpyxl.load_workbook(" in line for line in body):
        imports.append("import openpyxl")
    # `docx`(`WordApplicationScope`→`docx.Document(...)`変換先、知見121)
    # も同様。
    if any("docx.Document(" in line for line in body):
        imports.append("import docx")
    # `win32com.client`(`SendOutlookMail`→`win32com.client.Dispatch(...)`
    # 変換先、知見98)も同様。
    if any("win32com.client.Dispatch(" in line for line in body):
        imports.append("import win32com.client")
    # `time`(`Click`の`DelayBefore`→`time.sleep(...)`変換先、知見106)も同様。
    if any("time.sleep(" in line for line in body):
        imports.append("import time")
    # `sqlite3`(`DatabaseConnect`の`ProviderName="System.Data.SQLite"`→
    # `sqlite3.connect(...)`変換先、知見114)も同様。標準ライブラリだが
    # 他のヘルパー同様、使用時のみ注入する。
    if any("sqlite3.connect(" in line for line in body):
        imports.append("import sqlite3")
    # `smtplib`/`email.mime.text`(`SendMail`→`smtplib.SMTP_SSL(...)`
    # 変換先、知見116)も同様。標準ライブラリ。
    if any("smtplib.SMTP_SSL(" in line for line in body):
        imports.append("import smtplib")
    if any("email.mime.text.MIMEText(" in line for line in body):
        imports.append("import email.mime.text")
    # `shutil`/`os`(`CopyFile`→`shutil.copy(...)`変換先、知見117)も同様。
    if any("shutil.copy(" in line for line in body):
        imports.append("import shutil")
    # `os.getcwd()`(`Environment.CurrentDirectory`変換先、知見140)も
    # 同じ`os`モジュールのため同じ条件にまとめる。
    if any("os.path." in line or "os.getcwd(" in line for line in body):
        imports.append("import os")
    # `base64`(`Convert.ToBase64String`→`base64.b64encode(...)`変換先、
    # 知見130)も同様。
    if any("base64.b64encode(" in line for line in body):
        imports.append("import base64")
    # `datetime`(`File.GetLastWriteTime`→`datetime.datetime.
    # fromtimestamp(...)`変換先、知見142)も同様。
    if any("datetime.datetime.fromtimestamp(" in line for line in body):
        imports.append("import datetime")
    # `glob`(`Directory.GetFiles`の2引数searchPattern形→`glob.glob(...)`
    # 変換先、知見134)も同様。
    if any("glob.glob(" in line for line in body):
        imports.append("import glob")
    # `re`(`Regex.Replace`→`re.sub(...)`変換先、知見144)も同様。
    if any("re.sub(" in line for line in body):
        imports.append("import re")
    # `logging`(`LogMessage`→`logging.info(...)`/`.error(...)`変換先、
    # 知見119)も同様。
    if any("logging.info(" in line or "logging.error(" in line for line in body):
        imports.append("import logging")
    # `subprocess`(`OpenApplication`→`subprocess.Popen(...)`変換先、
    # 知見154、`KillProcess`→`subprocess.run(...)`変換先、知見169)も
    # 同様。
    if any("subprocess.Popen(" in line or "subprocess.run(" in line for line in body):
        imports.append("import subprocess")
    # `webbrowser`(`OpenBrowser`→`webbrowser.open(...)`変換先、知見168)
    # も同様。
    if any("webbrowser.open(" in line for line in body):
        imports.append("import webbrowser")
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
    # `_pywinauto_type_keys_escape`(`TypeInto`→`type_keys()`の特殊文字
    # エスケープ先、知見110)も同様。
    if any(f"{_TYPE_KEYS_ESCAPE_HELPER_NAME}(" in line for line in body):
        imports.append(_TYPE_KEYS_ESCAPE_HELPER_SOURCE.rstrip("\n"))
    # `_pywinauto_set_toggle_state`(`Check`→`toggle()`の目的状態判定先、
    # 知見165)も同様。
    if any(f"{_SET_TOGGLE_STATE_HELPER_NAME}(" in line for line in body):
        imports.append(_SET_TOGGLE_STATE_HELPER_SOURCE.rstrip("\n"))
    return imports


def _generate_body(
    nodes: list[Node], indent: int, invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    lines: list[str] = []
    for node in nodes:
        lines.extend(_generate_node(node, indent, invoke_resolver, out_arg_resolver))
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
    呼び出し側が代入文等に組み込む。

    知見141: `expr_desc`(`NotImplementedError`のメッセージ)は、構文
    解析に失敗した元のVB式テキストをそのまま含むことがある
    (`render_expr`の`VbExpr`分岐、`"VB expression failed to parse: "
    f"{expr.text}"`)——VB.NETは丸括弧内での改行(行継続)を許すため、
    `expr.text`自体が複数行になりうる(`JFHaataja/HAMK-miniprojekti`
    の実機XAML、複数行の`Substring(...)`式で発見)。これを単一行の
    f-stringへ無防備に埋め込むと、改行以降が`#`の付かない生のテキスト
    行としてそのまま出力され、タブ/スペース混在のインデントエラー等で
    `compile()`時に構文エラーになる——`single_line`で改行を視認可能な
    形(`\\n`リテラル)に退避し、常に単一行のコメントであることを保証する。
    """
    single_line = expr_desc.replace("\n", "\\n")
    return [f"{prefix}# TODO: unresolved VB expression: {single_line}"]


def _render_value_or_todo(expr, prefix: str, todo_lines: list[str]) -> str:
    try:
        return render_expr(expr)
    except NotImplementedError as e:
        todo_lines.extend(_todo_value(prefix, str(e)))
        return "None"


def _generate_node(
    node: Node, indent: int, invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    prefix = INDENT * indent
    if isinstance(node, FlowchartNode):
        return _generate_flowchart(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, SequenceNode):
        return [
            *_generate_variable_inits(node.variables, indent),
            *_generate_body(node.body, indent, invoke_resolver, out_arg_resolver),
        ]
    if isinstance(node, AssignNode):
        return _generate_assign(node, indent)
    if isinstance(node, MultipleAssignNode):
        return _generate_multiple_assign(node, indent)
    if isinstance(node, MessageBoxNode):
        return _generate_message_box(node, indent)
    if isinstance(node, InputDialogNode):
        return _generate_input_dialog(node, indent)
    if isinstance(node, IfNode):
        return _generate_if(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, ForEachNode):
        return _generate_for_each(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, TryCatchNode):
        return _generate_try_catch(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, SwitchNode):
        return _generate_switch(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, WhileNode):
        return _generate_while(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, DoWhileNode):
        return _generate_do_while(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, BreakNode):
        return [f"{prefix}break"]
    if isinstance(node, ParallelNode):
        return _generate_parallel(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, AppendLineNode):
        return _generate_append_line(node, indent)
    if isinstance(node, ReadTextFileNode):
        return _generate_read_text_file(node, indent)
    if isinstance(node, SetToClipboardNode):
        return _generate_set_to_clipboard(node, indent)
    if isinstance(node, ClickNode):
        return _generate_click(node, indent)
    if isinstance(node, HoverNode):
        return _generate_hover(node, indent)
    if isinstance(node, ActivateNode):
        return _generate_activate(node, indent)
    if isinstance(node, CheckNode):
        return _generate_check(node, indent)
    if isinstance(node, HighlightNode):
        return _generate_highlight(node, indent)
    if isinstance(node, CloseApplicationNode):
        return _generate_close_application(node, indent)
    if isinstance(node, CloseWindowNode):
        return _generate_close_window(node, indent)
    if isinstance(node, KillProcessNode):
        return _generate_kill_process(node, indent)
    if isinstance(node, CloseTabNode):
        return _generate_close_tab(node, indent)
    if isinstance(node, TypeIntoNode):
        return _generate_type_into(node, indent)
    if isinstance(node, SendHotkeyNode):
        return _generate_send_hotkey(node, indent)
    if isinstance(node, GetTextNode):
        return _generate_get_text(node, indent)
    if isinstance(node, SelectItemNode):
        return _generate_select_item(node, indent)
    if isinstance(node, UiElementExistsNode):
        return _generate_ui_element_exists(node, indent)
    if isinstance(node, DatabaseConnectNode):
        return _generate_database_connect(node, indent)
    if isinstance(node, DatabaseDisconnectNode):
        return _generate_database_disconnect(node, indent)
    if isinstance(node, ExecuteQueryNode):
        return _generate_execute_query(node, indent)
    if isinstance(node, ExecuteNonQueryNode):
        return _generate_execute_non_query(node, indent)
    if isinstance(node, InvokeWorkflowFileNode):
        return _generate_invoke_workflow_file(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, CopyFileNode):
        return _generate_copy_file(node, indent)
    if isinstance(node, BuildDataTableNode):
        return _generate_build_data_table(node, indent)
    if isinstance(node, HttpClientNode):
        return _generate_http_client(node, indent)
    if isinstance(node, AttachWindowNode):
        return _generate_attach_window(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, OpenApplicationNode):
        return _generate_open_application(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, OpenBrowserNode):
        return _generate_open_browser(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, ExcelApplicationScopeNode):
        return _generate_excel_application_scope(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, WordApplicationScopeNode):
        return _generate_word_application_scope(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, SendMailNode):
        return _generate_send_mail(node, indent)
    if isinstance(node, SendOutlookMailNode):
        return _generate_send_outlook_mail(node, indent)
    if isinstance(node, GetOutlookMailMessagesNode):
        return _generate_get_outlook_mail_messages(node, indent)
    if isinstance(node, CommentNode):
        return _generate_comment(node, indent)
    if isinstance(node, DelayNode):
        return _generate_delay(node, indent)
    if isinstance(node, WriteLineNode):
        return _generate_write_line(node, indent)
    if isinstance(node, ThrowNode):
        return _generate_throw(node, indent)
    if isinstance(node, RethrowNode):
        return _generate_rethrow(node, indent)
    if isinstance(node, TerminateWorkflowNode):
        return _generate_terminate_workflow(node, indent)
    if isinstance(node, LogMessageNode):
        return _generate_log_message(node, indent)
    if isinstance(
        node,
        (
            InvokeCodeNode,
            ExcelWriteCellNode,
            ExcelReadCellNode,
            ExcelReadRangeNode,
            ExcelWriteRangeNode,
            ExcelAppendRangeNode,
            WordReplaceTextNode,
        ),
    ):
        return _generate_unresolved_activity(node, indent)
    if isinstance(node, UnknownActivityNode):
        return _generate_unknown(node, indent)
    raise TypeError(f"Unsupported node type for codegen: {type(node)!r}")


def _generate_assign(node: AssignNode, indent: int) -> list[str]:
    """知見136・137: 代入先(`target`)を値(`value`)と同じ`_render_value_
    or_todo`経由でレンダリングしてはいけない——その関数は失敗時に
    (例外を投げずに)素の文字列`"None"`を返す仕様のため、`target`側で
    使うと`None = value`という**構文的に無効**なPythonコード
    (`None`はPythonの予約済み特殊値で代入先にできない)を生成してしまう。

    知見136では`node.target is None`(`.To`自体が未捕捉)だけを対策した
    が、知見137で発見したより一般的なケース——`target`自体は`VbExpr`
    として存在するが、その**レンダリングが失敗する**(知見74の`row(...)`
    添字曖昧性等、`render_expr`が`NotImplementedError`を投げる場合)
    ——は捕捉できていなかった(`agilashree/220701015-OAI1903-RPA-Lab`の
    実機XAML、`ForEach`ループ内で`CurrentRow(...)`という添字参照を
    代入先に使う実例で発見)。`target`は`render_expr`を直接呼び、例外が
    発生したらその場で代入文自体を生成せず`# TODO`へ倒す——`target`が
    確定できない代入文は、`value`側だけ`# TODO`に倒して`None = value`
    を作るのではなく、文全体を安全側に倒す。
    """
    prefix = INDENT * indent
    if node.target is None:
        return [f"{prefix}# TODO: Assign with no target (To) captured"]
    try:
        target = render_expr(node.target)
    except NotImplementedError as e:
        return _todo_value(prefix, str(e))
    todo: list[str] = []
    value = _render_value_or_todo(node.value, prefix, todo)
    return [*todo, f"{prefix}{target} = {value}"]


def _generate_multiple_assign(node: MultipleAssignNode, indent: int) -> list[str]:
    """知見122: 各`AssignOperation`を既存の`_generate_assign`へそのまま
    委ねる——`MultipleAssign`は複数の`Assign`を1つの活動にまとめた糖衣
    構文に過ぎないため、新しい生成ロジックは不要。"""
    prefix = INDENT * indent
    lines: list[str] = []
    for assignment in node.assignments:
        lines.extend(_generate_assign(assignment, indent))
    return _with_scope_child_display_name(node, lines, prefix)


# 知見107: `MessageBox`の`Buttons`(UiPath公式ドキュメントに列挙値の記載は
# 無いが、GitHub上の実機保存済みXAMLで`"Ok"`/`"OkCancel"`/`"YesNo"`/
# `"YesNoCancel"`の実在を確認済み、VM不使用)が単一ボタン(`"Ok"`、実機
# フィクスチャで確認済みの既定)以外だと、ユーザーがどのボタンを押すか
# という選択の分岐が生成コードに反映されない——`print()`は非対話的な
# 変換のため、でっち上げた`input()`等のユーザー入力再現はせず、
# 選択肢がある場合は`# TODO`へ倒す。
_MESSAGE_BOX_SAFE_BUTTONS = (None, "Ok")


def _generate_message_box(node: MessageBoxNode, indent: int) -> list[str]:
    """`ui:MessageBox`はPythonのネイティブ対話ダイアログに相当するものが
    無いため、最も単純で誤解の少ない代替としてコンソール出力`print()`に
    変換する(確定的な仕様ではなく、v1の暫定的な既定選択——将来tkinter等の
    実モーダルダイアログへ差し替える余地を残す)。

    知見79: `Caption`(ダイアログのタイトルバー文字列)は捕捉済みだが、
    これまで生成コードで一切使われていなかった——実機フィクスチャでは
    常に`{x:Null}`(未設定)だったため動作は変わらないが、設定されている
    場合は`print()`の出力に含めることで情報を失わない(知見75と同じ
    「捕捉済みのデータを活かす」方針)。`Caption`/`Text`いずれも非文字列が
    束縛される可能性があるため`_vb_cstr()`(知見46)で文字列化する。

    知見107: `Buttons`が単一ボタン(`"Ok"`)以外、または`ChosenButton`
    (UiPath公式ドキュメントで戻り値が`"Ok"`/`"Yes"`/`"No"`/`"Cancel"`の
    いずれかと確認済み)が実際に変数へ束縛されている場合は、`print()`では
    ユーザーの選択を再現できないため`# TODO`へ倒す——「ワークフローが
    選択結果を実際に使っている」ことの検出に`ChosenButton`の捕捉を使う。
    """
    prefix = INDENT * indent
    if node.buttons not in _MESSAGE_BOX_SAFE_BUTTONS or node.chosen_button is not None:
        return [
            f"{prefix}# TODO: MessageBox with Buttons={node.buttons!r} and/or "
            f"ChosenButton captured ({_describe_expr_for_comment(node.chosen_button)}) "
            "— print() cannot reproduce the user's button choice, refusing to guess"
        ]
    todo: list[str] = []
    text = _render_value_or_todo(node.text, prefix, todo)
    if node.caption is None:
        return [*todo, f"{prefix}print({text})"]
    caption = _render_value_or_todo(node.caption, prefix, todo)
    return [
        *todo,
        f"{prefix}print({VB_CSTR_HELPER_NAME}({caption}) + ': ' + {VB_CSTR_HELPER_NAME}({text}))",
    ]


_INPUT_DIALOG_SAFE_IS_PASSWORD = (None, "False")


def _generate_input_dialog(node: InputDialogNode, indent: int) -> list[str]:
    """知見131: `ui:InputDialog`はPythonの`input()`組み込み関数が直接
    対応する(`MessageBox`の「でっち上げない」方針とは違い、`input()`へ
    の変換自体が意味論上の直接対応——`InputDialogNode`のdocstring参照)。

    実機確認済みの`IsPassword="False"`・`Options`未設定の組み合わせのみ
    対応し、それ以外(パスワード入力・選択肢付きダイアログへ変わると
    推測されるが実機未確認)は推測せず`# TODO`へ倒す。
    """
    prefix = INDENT * indent
    if node.is_password not in _INPUT_DIALOG_SAFE_IS_PASSWORD:
        return [
            f"{prefix}# TODO: Input Dialog with IsPassword={node.is_password!r} — only "
            "the non-password (False) case is confirmed, refusing to guess"
        ]
    if node.options is not None:
        return [
            f"{prefix}# TODO: Input Dialog with Options captured "
            f"({_describe_expr_for_comment(node.options)}) — only the plain-text "
            "(no Options) case is confirmed, refusing to guess"
        ]
    if node.label is None:
        return [f"{prefix}# TODO: Input Dialog with no Label captured"]
    if node.result is None:
        return [f"{prefix}# TODO: Input Dialog with no output Result captured"]
    todo: list[str] = []
    label = _render_value_or_todo(node.label, prefix, todo)
    target = _render_value_or_todo(node.result, prefix, todo)
    if node.title is None:
        if todo:
            return todo
        return [f"{prefix}{target} = input({VB_CSTR_HELPER_NAME}({label}))"]
    title = _render_value_or_todo(node.title, prefix, todo)
    if todo:
        return todo
    return [
        f"{prefix}{target} = input({VB_CSTR_HELPER_NAME}({title}) + ': ' "
        f"+ {VB_CSTR_HELPER_NAME}({label}))"
    ]


def _generate_if(
    node: IfNode, indent: int, invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
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
        _generate_body(node.then_body, indent + 1, invoke_resolver, out_arg_resolver), indent + 1
    )
    lines.extend(then_body)
    if node.else_body:
        lines.append(f"{prefix}else:")
        else_body = _ensure_nonempty_suite(
            _generate_body(node.else_body, indent + 1, invoke_resolver, out_arg_resolver), indent + 1
        )
        lines.extend(else_body)
    return lines


def _generate_for_each(
    node: ForEachNode, indent: int, invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    prefix = INDENT * indent
    # `Values`も`If`/`While`/`Switch`と同じ厳格な失敗モード(モジュール
    # docstring参照、知見155で明文化): 反復対象を誤って推測すると全ての
    # 反復が間違ったデータに対して実行されてしまうため、変換できなければ
    # `NotImplementedError`をそのまま伝播させてコード生成自体を失敗させる。
    values = render_expr(node.values)
    lines = [f"{prefix}for {node.item_var or '_item'} in {values}:"]
    body = _ensure_nonempty_suite(
        _generate_body(node.body, indent + 1, invoke_resolver, out_arg_resolver), indent + 1
    )
    lines.extend(body)
    return lines


def _generate_while(
    node: WhileNode, indent: int, invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    prefix = INDENT * indent
    # `While`の条件も`If`と同じBoolean変換規則に従う(知見61)。
    cond = render_expr(node.condition)
    lines = [f"{prefix}while {VB_BOOL_HELPER_NAME}({cond}):"]
    body = _ensure_nonempty_suite(
        _generate_body(node.body, indent + 1, invoke_resolver, out_arg_resolver), indent + 1
    )
    lines.extend(body)
    return lines


def _generate_do_while(
    node: DoWhileNode, indent: int, invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
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
    body = _generate_body(node.body, indent + 1, invoke_resolver, out_arg_resolver)
    body.append(f"{INDENT * (indent + 1)}if not ({VB_BOOL_HELPER_NAME}({cond})):")
    body.append(f"{INDENT * (indent + 2)}break")
    lines.extend(_ensure_nonempty_suite(body, indent + 1))
    return lines


def _generate_try_catch(
    node: TryCatchNode, indent: int, invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    """知見76: `catches`が2件以上の場合、それぞれの.NET例外型が
    `_EXCEPTION_TYPE_MAP`で同じPython例外型(未知の型は無条件で
    `Exception`にフォールバックするため衝突しうる)へ解決されると、
    生成される`except`節は先に書いた方が常に先勝ちする(Pythonの仕様)
    ——後続の`except`節が到達不能な死んだコードになり、意図した
    「特定の例外だけ別処理、それ以外は汎用処理」という制御フローが
    サイレントに崩れる(実際に`exec()`して、後続のハンドラが一度も
    実行されないことを確認済み)。でっち上げた.NET例外階層の精密対応
    (v1スコープ外)をする代わりに、この衝突を検出した場合はでっち上げず
    `# TODO`へ全体を倒す——`try_body`だけ正しく生成して`except`を
    壊すより、安全側に倒す。"""
    prefix = INDENT * indent
    if len(node.catches) > 1:
        resolved_types = [
            _EXCEPTION_TYPE_MAP.get(c.exception_type.lower(), "Exception") for c in node.catches
        ]
        if len(set(resolved_types)) < len(resolved_types):
            exc_types = ", ".join(c.exception_type for c in node.catches)
            return [
                f"{prefix}# TODO: TryCatch with ambiguous/colliding exception type "
                f"mapping among multiple catches ({exc_types}) — generating except "
                "clauses would silently shadow one handler with another, refusing "
                "to guess"
            ]
    lines = _generate_variable_inits(node.variables, indent)
    lines.append(f"{prefix}try:")
    try_body = _ensure_nonempty_suite(
        _generate_body(node.try_body, indent + 1, invoke_resolver, out_arg_resolver), indent + 1
    )
    lines.extend(try_body)
    for catch in node.catches:
        exc_type = _EXCEPTION_TYPE_MAP.get(catch.exception_type.lower(), "Exception")
        as_clause = f" as {catch.var_name}" if catch.var_name else ""
        lines.append(f"{prefix}except {exc_type}{as_clause}:")
        body = _ensure_nonempty_suite(
            _generate_body(catch.body, indent + 1, invoke_resolver, out_arg_resolver), indent + 1
        )
        lines.extend(body)
    if node.finally_body:
        lines.append(f"{prefix}finally:")
        body = _ensure_nonempty_suite(
            _generate_body(node.finally_body, indent + 1, invoke_resolver, out_arg_resolver), indent + 1
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
    """知見81: `_vb_cmp()`(知見77)は`bool`オペランドを比較の**前**に
    `True→-1`/`False→0`へ変換する(知見51と同じ規則)——`type_arguments`が
    `x:Boolean`の場合に`key`を素の文字列リテラル(`'True'`)のまま渡すと、
    `_vb_cmp("flag" is bool True, "True" is str)`の文字列側が
    `_s2f("True")`で`float()`に失敗し`ValueError`で**クラッシュする**
    (知見77導入前は素の`==`で単に`False`になるだけで済んでいた、知見77が
    生んだ新規の退行)。数値型と同じく、Boolean型のキーも裸のPython
    真偽値リテラル(`True`/`False`)として出力し、`_vb_cmp`の`bool`→`int`
    変換を両オペランドに一貫して適用させることで解消する。"""
    type_tag = type_arguments.lower()
    if type_tag in _SWITCH_NUMERIC_TYPES:
        return key
    if type_tag in _BOOLEAN_TYPES:
        return "True" if key.strip().lower() == "true" else "False"
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


def _generate_flowchart(
    node: FlowchartNode, indent: int, invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    """知見100: Flowchartのグラフ(循環・合流を含む一般の有向グラフ——知見100
    で確認した実機XAML例が実際にループを含んでいた)をPythonへ変換する。
    Pythonには`goto`/ラベルが無いため、ディスパッチループ(状態機械)
    パターン(`while _flow is not None: if _flow == 0: ... elif _flow == 1:
    ...`)へ落とす——任意のCFGを構造化言語で表現する標準的な手法で、
    でっち上げた簡略化ではない。各到達可能な`FlowNode`に(文書中の出現順を
    辿るDFS順で)0始まりの整数ラベルを振り、`_flow`という一時変数で
    「今どのノードを実行中か」を追跡する——ラベルはPythonオブジェクトの
    `id()`をキーにした辞書で割り当てるため、同じノードオブジェクトが
    複数箇所から参照されていても(合流・循環)同じラベルになる。

    `FlowDecision`(`If`/`While`と同じBoolean変換規則、知見61の
    `_vb_bool()`)・`FlowSwitch`(`Switch`と同じ`_vb_cmp()`比較規則、知見77
    ——公式ドキュメントが`FlowSwitch<T>`を「`Switch<T>`と同様」と明記して
    いることに基づく類推、FlowSwitch自体の比較規則は実機未確認のため
    knowledge記録に残す)はそれぞれ既存の`If`/`Switch`と同じ変換規則を流用。
    `FlowSwitch`で該当するケースも`Default`も無い場合、既存の`Switch`
    (値が一致するcaseが無ければ何もしない)と同じ意味論だが、ここでは
    `_flow`を明示的に`None`へ倒す必要がある——`_flow`を更新し忘れると
    外側の`while`が同じ状態を永遠に再実行し無限ループになるため(`If`/
    `FlowDecision`は常に`True`/`False`いずれかの分岐へ入るため同じ問題は
    起きない)。`Condition`/`Expression`が未設定(`DoWhile`の「Condition
    未設定」ケース、知見38相当)の場合も同様に、でっち上げた既定分岐を
    選ばず`# TODO`+安全な`_flow = None`終端に倒す。
    """
    prefix = INDENT * indent
    lines = _generate_variable_inits(node.variables, indent)
    if node.start is None:
        return lines

    labels: dict[int, int] = {}
    order: list[FlowStepNode | FlowDecisionNode | FlowSwitchNode] = []

    def _walk(n) -> None:
        if n is None or id(n) in labels:
            return
        labels[id(n)] = len(order)
        order.append(n)
        if isinstance(n, FlowStepNode):
            _walk(n.next)
        elif isinstance(n, FlowDecisionNode):
            _walk(n.true_branch)
            _walk(n.false_branch)
        elif isinstance(n, FlowSwitchNode):
            for arm in n.arms:
                _walk(arm.node)

    _walk(node.start)

    def _label_of(n) -> str:
        return "None" if n is None else str(labels[id(n)])

    lines.append(f"{prefix}_flow = {labels[id(node.start)]}")
    lines.append(f"{prefix}while _flow is not None:")
    body_indent = indent + 1
    body_prefix = INDENT * body_indent
    for i, n in enumerate(order):
        keyword = "if" if i == 0 else "elif"
        lines.append(f"{body_prefix}{keyword} _flow == {i}:")
        inner_indent = body_indent + 1
        inner_prefix = INDENT * inner_indent
        if isinstance(n, FlowStepNode):
            lines.extend(_generate_body(n.body, inner_indent, invoke_resolver, out_arg_resolver))
            lines.append(f"{inner_prefix}_flow = {_label_of(n.next)}")
        elif isinstance(n, FlowDecisionNode):
            if n.condition is None:
                lines.append(f"{inner_prefix}# TODO: FlowDecision with no Condition set — intent unclear")
                lines.append(f"{inner_prefix}_flow = None")
                continue
            cond = render_expr(n.condition)
            lines.append(f"{inner_prefix}if {VB_BOOL_HELPER_NAME}({cond}):")
            lines.append(f"{INDENT * (inner_indent + 1)}_flow = {_label_of(n.true_branch)}")
            lines.append(f"{inner_prefix}else:")
            lines.append(f"{INDENT * (inner_indent + 1)}_flow = {_label_of(n.false_branch)}")
        else:
            if n.expression is None:
                lines.append(f"{inner_prefix}# TODO: FlowSwitch with no Expression set — intent unclear")
                lines.append(f"{inner_prefix}_flow = None")
                continue
            expr = render_expr(n.expression)
            default_arm = next((a for a in n.arms if a.key is None), None)
            value_arms = [a for a in n.arms if a.key is not None]
            for j, arm in enumerate(value_arms):
                arm_keyword = "if" if j == 0 else "elif"
                key_literal = _render_switch_key(arm.key, n.type_arguments)
                lines.append(
                    f"{inner_prefix}{arm_keyword} (lambda _t: _t[0] == _t[1])"
                    f"({VB_CMP_HELPER_NAME}({expr}, {key_literal})):"
                )
                lines.append(f"{INDENT * (inner_indent + 1)}_flow = {_label_of(arm.node)}")
            if value_arms or default_arm is not None:
                header = "else" if value_arms else "if True"
                lines.append(f"{inner_prefix}{header}:")
                target = default_arm.node if default_arm is not None else None
                lines.append(f"{INDENT * (inner_indent + 1)}_flow = {_label_of(target)}")
            else:
                lines.append(f"{inner_prefix}_flow = None")
    return lines


def _generate_switch(
    node: SwitchNode, indent: int, invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    """知見77: Microsoft Learn「Select...Case Statement」のRemarksが
    「`Case expression`は`testexpression = expression`の特殊形として
    評価される」と明記している——つまり各`Case`の比較は`=`演算子と全く
    同じ規則(知見47の`_vb_cmp`、数値/文字列混在オペランドの型変換)に
    従うはずだが、以前の実装は素の`==`を使っており、`Switch`の
    `Expression`が実行時に(`type_arguments`の宣言とは異なり)文字列型の
    値を実際に保持している場合に、本来VBでは一致するはずの比較が
    `# TODO`無しでサイレントに不一致になるという食い違いがあった
    (実際に`exec()`して`"1" == 1`が`False`になり対応する`Case`アームが
    実行されないことを確認済み)。`=`演算子と同じ`_vb_cmp()`経由の比較に
    統一して解消する——`key_literal`自体のレンダリング(`_render_switch_key`、
    数値型は裸のリテラル・それ以外は文字列リテラル)は変更しない。"""
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
        lines.append(
            f"{prefix}{keyword} (lambda _t: _t[0] == _t[1])"
            f"({VB_CMP_HELPER_NAME}({expr}, {key_literal})):"
        )
        body = _ensure_nonempty_suite(
            _generate_body(arm.body, indent + 1, invoke_resolver, out_arg_resolver), indent + 1
        )
        lines.extend(body)
    if default_arm is not None:
        header = "else" if value_arms else "if True"
        lines.append(f"{prefix}{header}:")
        body = _ensure_nonempty_suite(
            _generate_body(default_arm.body, indent + 1, invoke_resolver, out_arg_resolver), indent + 1
        )
        lines.extend(body)
    if not lines:
        return [f"{prefix}# TODO: Switch with no arms: {expr}"]
    return lines


def _generate_parallel(
    node: ParallelNode, indent: int, invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    """WFの`Parallel`(複数ブランチを並行実行)に相当するPythonネイティブの
    軽量な代替は無いため、v1では**ブランチを単純に順次実行**する
    (でっち上げた並行実行を装わない、明示的なコメント付きの簡略化)。"""
    prefix = INDENT * indent
    lines = [f"{prefix}# NOTE: source used Parallel; branches run sequentially here"]
    for branch in node.branches:
        lines.extend(_generate_node(branch, indent, invoke_resolver, out_arg_resolver))
    return lines


# 知見108: `Append Line`の`Encoding`/`UseDefaultEncoding`(UiPath公式
# ドキュメントで確認済み——`UseDefaultEncoding=True`(既定)ならOSの既定
# エンコーディング、`False`で`Encoding`未指定なら(BOM検出失敗時)UTF-8が
# 既定として選ばれる)の確定済みの組み合わせだけをPythonの`open(encoding=
# ...)`へマッピングする。`_UNCONFIRMED_ENCODING`は呼び出し側が`# TODO`へ
# 倒すための見張り値。
_UNCONFIRMED_ENCODING = object()


def _resolve_append_line_encoding(node: AppendLineNode):
    if node.encoding is not None:
        if node.encoding.strip().upper() == "UTF-8":
            return "utf-8"
        return _UNCONFIRMED_ENCODING
    if node.use_default_encoding == "False":
        return "utf-8"
    # True または未設定: OSの既定エンコーディング——Pythonの`open()`も
    # `encoding=`を省略すればロケールの既定エンコーディングを使うため、
    # kwarg自体を付けないことがそのまま正しいマッピングになる。
    return None


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
    実害は無い)。

    知見82: `FileName`が相対パスの場合、UiPath自体が何を基準に解決するか
    (プロジェクトフォルダ基準か、プロセスのカレントディレクトリ基準か)は
    公式ドキュメント・実データのいずれでも確定できず、実世界の報告も
    矛盾している(design/uipath_xaml_findings.md参照)——`open()`は
    Pythonプロセスの実行時カレントディレクトリ基準で解決する、既知の
    残課題として明示的に未解決のまま残す。

    知見108: `Encoding`/`UseDefaultEncoding`は従来一切捕捉されておらず
    `encoding="utf-8"`が無条件に埋め込まれていた——`UseDefaultEncoding=
    False`・`Encoding`未指定(実機フィクスチャの実例)では結果的に正しい
    値だったが、`UseDefaultEncoding=True`(既定)の場合は本来OSの既定
    エンコーディングになるはずで食い違っていた(実機フィクスチャには
    この組み合わせの実例が無かったため発覚していなかった)。"""
    prefix = INDENT * indent
    encoding = _resolve_append_line_encoding(node)
    if encoding is _UNCONFIRMED_ENCODING:
        return [
            f"{prefix}# TODO: Append Line with unconfirmed Encoding "
            f"{node.encoding!r} — refusing to guess the Python codec name"
        ]
    todo: list[str] = []
    file_name = _render_value_or_todo(node.file_name, prefix, todo)
    text = _render_value_or_todo(node.text, prefix, todo)
    encoding_kwarg = f", encoding={encoding!r}" if encoding else ""
    return [
        *todo,
        f'{prefix}with open({file_name}, "a"{encoding_kwarg}) as _f:',
        f'{INDENT * (indent + 1)}_f.write({VB_CSTR_HELPER_NAME}({text}) + "\\n")',
    ]


def _generate_read_text_file(node: ReadTextFileNode, indent: int) -> list[str]:
    """`FileName`の相対パス解決基準の既知の残課題は`_generate_append_line`
    (知見82)と同じ。

    知見108: `Encoding`が明示的に設定されていて、かつ確認済みの`"UTF-8"`
    以外の場合は`# TODO`へ倒す——`ReadTextFile`には`UseDefaultEncoding`
    相当のプロパティが無く(公式ドキュメント確認済み)、`Encoding`未指定
    時の既定(BOM検出→失敗時はシステムのANSIコードページ)は`Append
    Line`の`UseDefaultEncoding=False`時の既定(UTF-8)とは異なるため、
    既存の`encoding="utf-8"`はそのまま変更しない(実機フィクスチャの
    round-trip(`Append Line`が書いたUTF-8ファイルを読む)で正しく動作
    することを確認済みの既存動作を壊さないため)。"""
    prefix = INDENT * indent
    if node.encoding is not None and node.encoding.strip().upper() != "UTF-8":
        return [
            f"{prefix}# TODO: Read Text File with unconfirmed Encoding "
            f"{node.encoding!r} — refusing to guess the Python codec name"
        ]
    todo: list[str] = []
    file_name = _render_value_or_todo(node.file_name, prefix, todo)
    target = _render_value_or_todo(node.content, prefix, todo)
    # 知見138: `target`(`node.content`、代入先)のレンダリングが失敗した
    # 場合、ここで`if todo: return todo`無しに代入文を組み立てると知見
    # 136・137と同じ`None = ...`という構文的に無効なコードを生成して
    # しまう——他の全ての「targetへ代入する」生成関数が既に守っている
    # 「todoが1件でもあれば代入文自体を生成しない」という規約に、この
    # 関数だけが従っていなかった(抜け漏れ)。
    if todo:
        return todo
    return [f'{prefix}{target} = open({file_name}, encoding="utf-8").read()']


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


# `ui:Click`の`ClickType`/`MouseButton`属性(知見71で「唯一確認できた
# 具体例」としていたCLICK_SINGLE/BTN_LEFTの既定値以外)は、知見102で
# `gh api search/code`を使いGitHub上の実機保存済みXAMLから直接確認した
# (VM不使用、知見100のFlowchart直列化形確認と同じ手法)——
# `ClickType="CLICK_DOUBLE"`(ダブルクリック)・`MouseButton="BTN_RIGHT"`/
# `"BTN_MIDDLE"`(右・中クリック)はいずれも実在する値。これらを
# pywinautoの`click_input(button=..., double=...)`引数(インストール済みの
# 実`pywinauto`ソース`base_wrapper.py`/`mouse.py`で確認済み——`button`は
# `'left'`/`'right'`/`'middle'`、`double`は真偽値)へマッピングする。
# `CLICK_UP`/`CLICK_DOWN`(実在するが稀、`button_down`/`button_up`の
# 押し下げ/離すのみに対応すると推定されるが、ドラッグ操作用に2つの別の
# `Click`活動と組み合わせて使われる可能性があり単体での正確な対応が
# 未確認)は対象外のまま`# TODO`へ倒す。
_CLICK_TYPE_KWARGS: dict[str, dict[str, object]] = {
    "CLICK_SINGLE": {},
    "CLICK_DOUBLE": {"double": True},
}
_MOUSE_BUTTON_KWARGS: dict[str, dict[str, object]] = {
    "BTN_LEFT": {},
    "BTN_RIGHT": {"button": "right"},
    "BTN_MIDDLE": {"button": "middle"},
}
# `KeyModifiers`(知見71)は`"Ctrl"`等の非既定値が実在すると確認したが
# (`gh api search/code`)、複数キー併用時の区切り文字・大文字小文字・
# pywinautoの`pressed`引数(空白区切りの`"control"`/`"shift"`/`"alt"`、
# `mouse.py`で確認済み)への正確な対応が未確認のため、依然`# TODO`へ倒す
# (でっち上げるより安全側)。
_KEY_MODIFIERS_CONFIRMED_DEFAULTS = (None, "None")
# `ui:Click.CursorPosition`の`Position`属性(知見73)。実機確認済みの値は
# `"Center"`のみで、これはpywinautoの`click_input()`既定(ターゲット要素の
# 中心座標)と一致するため安全。
_CURSOR_POSITION_CONFIRMED_DEFAULTS = (None, "Center")
# 知見105: `Position="TopLeft"`+`OffsetX`/`OffsetY`(属性形・プロパティ
# 要素形の両方が実在)を`gh api search/code`でGitHub上の実機保存済みXAML
# から確認した(`PacktPublishing/Robotic-Process-Automation-Projects`の
# 実例、VM不使用)。pywinautoの`click_input(coords=...)`はデフォルトで
# ターゲット要素のクライアント座標系(原点が左上)を使う(インストール
# 済みの実`pywinauto`ソース`base_wrapper.py`で確認済み——`coords`未指定時
# `width()/2`/`height()/2`で中心を計算してから`client_to_screen`する)
# ため、`TopLeft`+オフセットは`coords=(offsetX, offsetY)`へそのまま
# マッピングできる、符号の曖昧性が無い唯一の非Center値。`TopRight`/
# `BottomLeft`/`BottomRight`はオフセットの符号規約(どちらの方向に数える
# か)が実機未確認のため依然`# TODO`へ倒す。


def _generate_click(node: ClickNode, indent: int) -> list[str]:
    """`ui:Click`のセレクタ(design/uipath_xaml_findings.md 知見37参照)を
    `uipath_selector`でpywinautoの検索条件連鎖へマッピングする。属性の
    「名前」の対応は机上の推定、`role`の「値」はUIAの`ControlType`語彙との
    一致を未検証のまま渡している——両方とも警告コメントとして生成コードに
    残し、実機で要素を一意特定できることまでは主張しない。マッピング可能な
    属性が1つも無かった場合(セレクタ自体が無い場合含む)は、でっち上げる
    くらいなら`# TODO`に倒す。`ClickType`/`MouseButton`/`KeyModifiers`
    (知見71)が実機確認済みの既定値から外れている場合も同様に`# TODO`へ
    倒す(下記`_CLICK_TYPE_CONFIRMED_DEFAULTS`等参照)。

    知見80: `display_name`(`DisplayName`属性、例: `"Click 'editable
    text'"`)は捕捉済みだがこれまで未活用だった——`# TODO`に倒れる場合も
    含め、どの`Click`を指しているか一目で分かるようコメントとして
    先頭に追記する(知見75・79と同系統の「捕捉済みデータを活かす」改善、
    コメントのみなので挙動は変えない)。"""
    prefix = INDENT * indent
    lines = _generate_click_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_click_body(node: ClickNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if not node.selector:
        return [f"{prefix}# TODO: Click with no selector captured"]
    click_type = node.click_type or "CLICK_SINGLE"
    mouse_button = node.mouse_button or "BTN_LEFT"
    if (
        click_type not in _CLICK_TYPE_KWARGS
        or mouse_button not in _MOUSE_BUTTON_KWARGS
        or node.key_modifiers not in _KEY_MODIFIERS_CONFIRMED_DEFAULTS
    ):
        return [
            f"{prefix}# TODO: Click with non-default ClickType/MouseButton/KeyModifiers "
            f"(ClickType={node.click_type!r}, MouseButton={node.mouse_button!r}, "
            f"KeyModifiers={node.key_modifiers!r}) — mapping not confirmed via real "
            "capture, refusing to guess"
        ]
    coords_kwargs: dict[str, object] = {}
    if node.cursor_position == "TopLeft":
        try:
            x = int(node.cursor_offset_x) if node.cursor_offset_x is not None else 0
            y = int(node.cursor_offset_y) if node.cursor_offset_y is not None else 0
        except ValueError:
            return [
                f"{prefix}# TODO: Click with non-integer CursorPosition offsets "
                f"(OffsetX={node.cursor_offset_x!r}, OffsetY={node.cursor_offset_y!r}) "
                "— refusing to guess"
            ]
        coords_kwargs = {"coords": (x, y)}
    elif (
        node.cursor_position not in _CURSOR_POSITION_CONFIRMED_DEFAULTS
        or node.cursor_offset_x is not None
        or node.cursor_offset_y is not None
    ):
        return [
            f"{prefix}# TODO: Click with non-default CursorPosition "
            f"({node.cursor_position!r}, OffsetX={node.cursor_offset_x!r}, "
            f"OffsetY={node.cursor_offset_y!r}) — offset mapping not confirmed via "
            "real capture, refusing to guess"
        ]
    if node.delay_ms is not None:
        return [
            f"{prefix}# TODO: Click with DelayMS set "
            f"({_describe_expr_for_comment(node.delay_ms)}) — not documented by "
            "UiPath (unlike DelayBefore), semantics not confirmed, refusing to guess"
        ]
    rendered = selector_text_to_pywinauto(node.selector)
    if rendered.expr == 'Desktop(backend="uia")':
        return [
            f"{prefix}# TODO: Click selector had no mappable attributes: {node.selector}"
        ]
    todo: list[str] = []
    delay_before = (
        _render_value_or_todo(node.delay_before, prefix, todo)
        if node.delay_before is not None
        else None
    )
    if todo:
        return todo
    lines = [f"{prefix}# WARNING: {w}" for w in rendered.warnings]
    if delay_before is not None:
        # 知見106: `DelayBefore`(UiPath公式ドキュメントで確認済み——「活動が
        # 何らかの操作を始める前の待機時間」、既定200ms)をミリ秒から秒へ
        # 単位変換して`time.sleep()`へ変換する。
        lines.append(f"{prefix}time.sleep({VB_NUM_HELPER_NAME}({delay_before}) / 1000.0)")
    kwargs = {
        **_CLICK_TYPE_KWARGS[click_type],
        **_MOUSE_BUTTON_KWARGS[mouse_button],
        **coords_kwargs,
    }
    kwargs_str = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
    lines.append(f"{prefix}{rendered.expr}.click_input({kwargs_str})")
    return lines


# 知見157: `ui:Hover`(`ClickNode`と`Target`/`CursorPosition`の構造が
# 全く同じ、GitHub code searchで151件ヒット)。`ClickType`/`MouseButton`/
# `KeyModifiers`が無い点のみ異なるため、`cursor_position`の既定値判定
# ロジック(知見73・105)は`Click`と同じ`_CURSOR_POSITION_CONFIRMED_
# DEFAULTS`を再利用する。pywinautoの`move_mouse_input()`ラッパー自身の
# 既定(`coords=(0, 0)`・`absolute=True`)は要素の中心に移動する意味に
# ならないため、`click_input()`自身の既定(`coords=(None, None)`・
# `absolute=False`)を`button='move'`で呼び出す形で実装する——`Click`の
# 既定(`CursorPosition`省略時に`coords`引数を渡さない)と同じ経路。
def _generate_hover(node: HoverNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_hover_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_hover_body(node: HoverNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if not node.selector:
        return [f"{prefix}# TODO: Hover with no selector captured"]
    coords_kwargs: dict[str, object] = {}
    if node.cursor_position == "TopLeft":
        try:
            x = int(node.cursor_offset_x) if node.cursor_offset_x is not None else 0
            y = int(node.cursor_offset_y) if node.cursor_offset_y is not None else 0
        except ValueError:
            return [
                f"{prefix}# TODO: Hover with non-integer CursorPosition offsets "
                f"(OffsetX={node.cursor_offset_x!r}, OffsetY={node.cursor_offset_y!r}) "
                "— refusing to guess"
            ]
        coords_kwargs = {"coords": (x, y)}
    elif (
        node.cursor_position not in _CURSOR_POSITION_CONFIRMED_DEFAULTS
        or node.cursor_offset_x is not None
        or node.cursor_offset_y is not None
    ):
        return [
            f"{prefix}# TODO: Hover with non-default CursorPosition "
            f"({node.cursor_position!r}, OffsetX={node.cursor_offset_x!r}, "
            f"OffsetY={node.cursor_offset_y!r}) — offset mapping not confirmed via "
            "real capture, refusing to guess"
        ]
    if node.delay_ms is not None:
        return [
            f"{prefix}# TODO: Hover with DelayMS set "
            f"({_describe_expr_for_comment(node.delay_ms)}) — not documented by "
            "UiPath (unlike DelayBefore), semantics not confirmed, refusing to guess"
        ]
    if _literal_str(node.send_window_messages) not in (None, "False"):
        return [
            f"{prefix}# TODO: Hover with non-default SendWindowMessages "
            f"({node.send_window_messages!r}) — exact mapping not confirmed, "
            "refusing to guess"
        ]
    if _literal_str(node.simulate_hover) not in (None, "False"):
        return [
            f"{prefix}# TODO: Hover with non-default SimulateHover "
            f"({node.simulate_hover!r}) — \"uses the target app's own "
            "technology\" per UiPath docs convention for other Simulate* "
            "attributes, exact mechanism not confirmed, refusing to guess"
        ]
    rendered = selector_text_to_pywinauto(node.selector)
    if rendered.expr == 'Desktop(backend="uia")':
        return [
            f"{prefix}# TODO: Hover selector had no mappable attributes: {node.selector}"
        ]
    todo: list[str] = []
    delay_before = (
        _render_value_or_todo(node.delay_before, prefix, todo)
        if node.delay_before is not None
        else None
    )
    if todo:
        return todo
    lines = [f"{prefix}# WARNING: {w}" for w in rendered.warnings]
    if delay_before is not None:
        lines.append(f"{prefix}time.sleep({VB_NUM_HELPER_NAME}({delay_before}) / 1000.0)")
    kwargs = {"button": "move", **coords_kwargs}
    kwargs_str = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
    lines.append(f"{prefix}{rendered.expr}.click_input({kwargs_str})")
    return lines


# 知見162: `ui:Activate`(GitHub code searchで604件ヒット)。`Click`/
# `Hover`より単純(`CursorPosition`自体が無い)——指定した要素/ウィンドウ
# をフォアグラウンドへ切り替えるだけの活動で、pywinautoの`set_focus()`
# (両バックエンドで共通サポートされる確認済みの標準API)が直接対応する。
def _generate_activate(node: ActivateNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_activate_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_activate_body(node: ActivateNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if not node.selector:
        return [f"{prefix}# TODO: Activate with no selector captured"]
    if node.delay_ms is not None:
        return [
            f"{prefix}# TODO: Activate with DelayMS set "
            f"({_describe_expr_for_comment(node.delay_ms)}) — not documented "
            "by UiPath (unlike DelayBefore), semantics not confirmed, "
            "refusing to guess"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: Activate with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    rendered = selector_text_to_pywinauto(node.selector)
    if rendered.expr == 'Desktop(backend="uia")':
        return [
            f"{prefix}# TODO: Activate selector had no mappable attributes: "
            f"{node.selector}"
        ]
    todo: list[str] = []
    delay_before = (
        _render_value_or_todo(node.delay_before, prefix, todo)
        if node.delay_before is not None
        else None
    )
    if todo:
        return todo
    lines = [f"{prefix}# WARNING: {w}" for w in rendered.warnings]
    if delay_before is not None:
        lines.append(f"{prefix}time.sleep({VB_NUM_HELPER_NAME}({delay_before}) / 1000.0)")
    lines.append(f"{prefix}{rendered.expr}.set_focus()")
    return lines


# 知見165: `ui:Check`(GitHub code searchで805件ヒット)。`Action="Check"`
# /`"Uncheck"`は「指定の最終状態へ**設定する**」操作(単純な無条件トグル
# ではない)——無条件に`click_input()`すると既にチェック済みの場合に
# 誤って外してしまうため、pywinautoのUIA`ButtonWrapper`が標準サポート
# する`toggle()`+`get_toggle_state()`(`0=unchecked`/`1=checked`/
# `2=indeterminate`)を使い、現在の状態が目的の状態と異なる場合のみ
# `toggle()`するヘルパーを経由する。
_SET_TOGGLE_STATE_HELPER_NAME = "_pywinauto_set_toggle_state"
_SET_TOGGLE_STATE_HELPER_SOURCE = '''\
def _pywinauto_set_toggle_state(elem, checked):
    if (elem.get_toggle_state() == 1) != checked:
        elem.toggle()
'''
_CHECK_ACTION_CHECKED = {"check": True, "uncheck": False}


def _generate_check(node: CheckNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_check_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_check_body(node: CheckNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if not node.selector:
        return [f"{prefix}# TODO: Check with no selector captured"]
    action_lower = (node.action or "").lower()
    if action_lower not in _CHECK_ACTION_CHECKED:
        return [
            f"{prefix}# TODO: Check with unrecognized Action "
            f"({node.action!r}) — refusing to guess"
        ]
    if node.delay_after is not None:
        return [
            f"{prefix}# TODO: Check with DelayAfter set "
            f"({_describe_expr_for_comment(node.delay_after)}) — not "
            "documented by UiPath (unlike DelayBefore), semantics not "
            "confirmed, refusing to guess"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: Check with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    rendered = selector_text_to_pywinauto(node.selector)
    if rendered.expr == 'Desktop(backend="uia")':
        return [
            f"{prefix}# TODO: Check selector had no mappable attributes: {node.selector}"
        ]
    todo: list[str] = []
    delay_before = (
        _render_value_or_todo(node.delay_before, prefix, todo)
        if node.delay_before is not None
        else None
    )
    if todo:
        return todo
    lines = [f"{prefix}# WARNING: {w}" for w in rendered.warnings]
    if delay_before is not None:
        lines.append(f"{prefix}time.sleep({VB_NUM_HELPER_NAME}({delay_before}) / 1000.0)")
    checked = _CHECK_ACTION_CHECKED[action_lower]
    lines.append(
        f"{prefix}{_SET_TOGGLE_STATE_HELPER_NAME}({rendered.expr}, {checked!r})"
    )
    return lines


# 知見166: `ui:Highlight`(GitHub code searchで289件ヒット)。純粋な視覚的
# デバッグ支援で、後続のアクティビティへ渡すデータや制御フローへの影響が
# 一切無い(実機確認した全件で出力バインディングも無い)——`ui:Comment`
# (知見119)と同じ「実行時の挙動が無い活動はコメントへ変換する」設計で、
# `# TODO`(未実装/未対応)ではなく意図的な「再現すべき実行時効果が無い」
# という判断として常にコメントのみを生成する(`selector_text_to_
# pywinauto`は呼ばない——実際の呼び出しを行わないため不要)。
def _generate_highlight(node: HighlightNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    details = []
    if node.selector:
        details.append(node.selector)
    if node.color:
        details.append(f"Color={node.color}")
    if node.highlight_time is not None:
        details.append(f"HighlightTime={_describe_expr_for_comment(node.highlight_time)}")
    detail = " ".join(details)
    lines = [
        f"{prefix}# Highlight{(' ' + detail) if detail else ''} — visual-only "
        "debugging aid, no automation effect to reproduce"
    ]
    return _with_scope_child_display_name(node, lines, prefix)


# 知見171: `ui:CloseApplication`(GitHub code searchで532件ヒット)。
# `Target`+`DisplayName`/`ContinueOnError`のみという`Activate`(知見162)
# と同じ属性構成だが、生成コードはpywinautoの`close()`(`WM_CLOSE`送信、
# 実際にウィンドウを閉じる)——`set_focus()`(副作用なし)とは全く別の
# 効果なので、`ActivateNode`は再利用せず専用のノード型にした。
def _generate_close_application(node: CloseApplicationNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_close_application_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_close_application_body(node: CloseApplicationNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if not node.selector:
        return [f"{prefix}# TODO: CloseApplication with no selector captured"]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: CloseApplication with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    rendered = selector_text_to_pywinauto(node.selector)
    if rendered.expr == 'Desktop(backend="uia")':
        return [
            f"{prefix}# TODO: CloseApplication selector had no mappable "
            f"attributes: {node.selector}"
        ]
    lines = [f"{prefix}# WARNING: {w}" for w in rendered.warnings]
    lines.append(f"{prefix}{rendered.expr}.close()")
    return lines


# 知見172: `ui:CloseWindow`(GitHub code searchで276件ヒット)。
# `CloseApplication`(知見171)と同じ`close()`意味論だが、属性構成が
# 違う——`Selector`をフラット属性として直接持つ「Classic」世代の
# 活動で、`UseWindow`(既存ウィンドウ参照の再利用、未モデル化の
# オブジェクト参照)が設定されている場合は`# TODO`へ倒す。
def _generate_close_window(node: CloseWindowNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_close_window_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_close_window_body(node: CloseWindowNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.use_window is not None:
        return [
            f"{prefix}# TODO: CloseWindow with UseWindow set "
            f"({_describe_expr_for_comment(node.use_window)}) — existing "
            "window object reference not modeled, refusing to guess"
        ]
    if not node.selector:
        return [f"{prefix}# TODO: CloseWindow with no selector captured"]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: CloseWindow with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    rendered = selector_text_to_pywinauto(node.selector)
    if rendered.expr == 'Desktop(backend="uia")':
        return [
            f"{prefix}# TODO: CloseWindow selector had no mappable "
            f"attributes: {node.selector}"
        ]
    lines = [f"{prefix}# WARNING: {w}" for w in rendered.warnings]
    lines.append(f"{prefix}{rendered.expr}.close()")
    return lines


# 知見169: `ui:KillProcess`(GitHub code searchで1514件ヒット——
# REFrameworkの標準サブワークフロー`KillAllProcesses.xaml`で多用される
# ため極めて高頻度)。`ProcessName`に一致する全プロセスを終了する
# ——Windows標準搭載の確認済みコマンド`taskkill /IM <name>.exe /F`
# (`subprocess.run`経由)が直接対応する。`/T`(プロセスツリー全体の
# 終了)は付けない(.NETの素の`Process.Kill()`は子プロセスを終了しない
# ため、過大な終了範囲をでっち上げないよう安全側に倒す)。
def _generate_kill_process(node: KillProcessNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_kill_process_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_kill_process_body(node: KillProcessNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.process_name is None:
        return [f"{prefix}# TODO: KillProcess with no ProcessName captured"]
    if node.process is not None:
        return [
            f"{prefix}# TODO: KillProcess with Process set "
            f"({_describe_expr_for_comment(node.process)}) — UiPath Process "
            "object reference not modeled, refusing to guess"
        ]
    if node.applies_to is not None:
        return [
            f"{prefix}# TODO: KillProcess with AppliesTo set "
            f"({_describe_expr_for_comment(node.applies_to)}) — semantics "
            "not confirmed, refusing to guess"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: KillProcess with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    todo: list[str] = []
    process_name = _render_value_or_todo(node.process_name, prefix, todo)
    if todo:
        return todo
    return [
        f"{prefix}subprocess.run(["
        f'"taskkill", "/IM", f"{{{VB_CSTR_HELPER_NAME}({process_name})}}.exe", "/F"'
        "])"
    ]


# 知見170: `ui:CloseTab`(GitHub code searchで782件ヒット)。`Target`/
# `Selector`を一切持たず、唯一の属性`Browser`(`UiBrowser`型変数参照)が
# `{x:Null}`(ほとんどのREFramework実例)の場合は「現在フォーカス中の
# タブ/ウィンドウを閉じる」という意味論になり、主要ブラウザ共通の標準
# キーボードショートカット`Ctrl+W`で実現できる——pywinautoの`keyboard.
# send_keys()`(対象を指定しないグローバルなキー送信の確認済み標準API、
# `SendHotkey`の`Target`省略ケース(知見152)で未対応のまま残っていた
# 経路を初めて実際に実装する)を使う。`Browser`が変数参照の場合は
# (`UiBrowser`変数自体が未モデル化のため)`# TODO`へ倒す。
def _generate_close_tab(node: CloseTabNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_close_tab_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_close_tab_body(node: CloseTabNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.browser is not None:
        return [
            f"{prefix}# TODO: CloseTab with Browser set "
            f"({_describe_expr_for_comment(node.browser)}) — UiBrowser "
            "variable reference not modeled, refusing to guess"
        ]
    return [f"{prefix}send_keys('^w')"]


# `pywinauto`の`type_keys()`は`~^%+(){}`を独自の特殊キー構文として解釈する
# (インストール済み`.venv`の`pywinauto/keyboard.py`で確認済み、
# `dump_daemon/pad_ui_helpers.py`の`set_vb_expression_field`docstringが
# PAD調査時に発見した同じ罠と同種)。生成コードが`Text`の実際の値を
# 保証できない(リテラルでもVB式でも、実行時の文字列に上記の文字が
# 含まれる可能性を否定できない)ため、コード生成側で常にこのヘルパーを
# 経由させてエスケープする——各特殊文字を`{c}`で囲む(`{`/`}`自身は
# `{{}`/`{}}}`、`pad_ui_helpers.py`のドキュメント記載と同じ規則)。
_TYPE_KEYS_ESCAPE_HELPER_NAME = "_pywinauto_type_keys_escape"
_TYPE_KEYS_ESCAPE_HELPER_SOURCE = '''\
def _pywinauto_type_keys_escape(s):
    out = []
    for ch in s:
        if ch in "~^%+(){}":
            out.append("{" + ch + "}")
        else:
            out.append(ch)
    return "".join(out)
'''


def _literal_str(expr: Expr) -> str | None:
    """`Expr`が確認済みの生リテラル文字列ならその値を返す(`VbExpr`や
    `None`の場合は`None`——静的に値が分からない/未設定のいずれも、
    呼び出し側が「既知の確認済み値セット」と比較した際に自然に
    マッチしなくなり、安全側の`# TODO`分岐へ落ちる)。"""
    if isinstance(expr, Literal):
        return expr.value
    return None


# 知見110(本修正): `ui:TypeInto`。`gh api search/code`でGitHub上の実機保存
# 済みXAML(`UiPath/skills`公式リポジトリの最新Classicパッケージ用テスト
# フィクスチャ含む、複数件)を確認し、以下を確定した——
# `ClickBeforeTyping`/`EmptyField`/`SimulateType`/`SendWindowMessages`/
# `DelayBefore`/`DelayMS`/`DelayBetweenKeys`/`AlterIfDisabled`/
# `ContinueOnError`/`ActivateBefore`(または旧い`Activate`)はいずれも
# `{x:Null}`として直列化される実例がある(nullable)。
#
# docs.uipath.com「UI Automationの入力方式」ページ(2026-11-05取得)が
# 既定の入力方式を「ハードウェアドライバー経由のシミュレート」(Hardware
# Events)と明言しており、これは`pywinauto`の`type_keys()`(`SendInput`を
# 使う、`click_input()`と同系統)と一致する——`Click`の`SimulateClick`/
# `SendWindowMessages`で未確定だった「既定値の正確な機構」について、
# `TypeInto`では公式ドキュメントで確認が取れた点が異なる。ただし
# `SimulateType`/`SendWindowMessages`が`True`の場合の正確なマッピング
# (「対象アプリ自身の技術を使う」等、具体的なAPIが未記載)は依然未確認
# のため、既定値(`None`/`"False"`)以外は`# TODO`へ倒す——`Click`の
# `SimulateClick`/`SendWindowMessages`と同じ判断。
#
# `ClickBeforeTyping`の実機確認済みの値は`{x:Null}`/`"False"`/`"True"`/
# `"NONE"`の4種。`"NONE"`が真偽値`False`相当の別表記なのか、将来の
# クリック種別を含む3値enumの一部なのかは未確定だが、いずれも「クリック
# しない」という解釈は安全側で一致するため、この4値全てを「クリック
# しない」として扱う。`"True"`のみ、確認済みの既定クリック(`Click`の
# 既定`CLICK_SINGLE`/`BTN_LEFT`と同じ`click_input()`)を発行する。
#
# `EmptyField`(フィールドを消去してから入力)は`True`時の消去手段
# (UiPathがどのAPIで消去するか)が未確認のため、`None`/`"False"`以外は
# `# TODO`へ倒す。
#
# `Activate`/`ActivateBefore`(`TypeIntoNode`のdocstring参照)は
# docs.uipath.comで「既定でチェック済み、外すと入力は現在アクティブな
# ウィンドウへ送られる」と確認済み——`pywinauto`の`type_keys()`の
# `set_foreground`引数(既定`True`)がこれと一致するため、確認済みの
# `"True"`/`None`(両方「既定のまま」)はkwargを付けず、確認済みの
# `"False"`のみ`set_foreground=False`を明示する。それ以外の値(VB式等)
# は静的に真偽が分からないため`# TODO`へ倒す。
def _generate_type_into(node: TypeIntoNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_type_into_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_type_into_body(node: TypeIntoNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if not node.selector:
        return [f"{prefix}# TODO: Type Into with no selector captured"]
    if node.text is None:
        return [f"{prefix}# TODO: Type Into with no Text captured"]
    if _literal_str(node.simulate_type) not in (None, "False"):
        return [
            f"{prefix}# TODO: Type Into with non-default SimulateType "
            f"({node.simulate_type!r}) — \"uses the target app's own "
            "technology\" per UiPath docs, exact mechanism not confirmed, "
            "refusing to guess"
        ]
    if _literal_str(node.send_window_messages) not in (None, "False"):
        return [
            f"{prefix}# TODO: Type Into with non-default SendWindowMessages "
            f"({node.send_window_messages!r}) — exact mapping not confirmed, "
            "refusing to guess"
        ]
    click_before = _literal_str(node.click_before_typing)
    if click_before not in (None, "False", "NONE", "True"):
        return [
            f"{prefix}# TODO: Type Into with unrecognized ClickBeforeTyping "
            f"({node.click_before_typing!r}) — refusing to guess"
        ]
    if _literal_str(node.empty_field) not in (None, "False"):
        return [
            f"{prefix}# TODO: Type Into with EmptyField set "
            f"({node.empty_field!r}) — exact field-clearing mechanism not "
            "confirmed, refusing to guess"
        ]
    if node.delay_ms is not None:
        return [
            f"{prefix}# TODO: Type Into with DelayMS set "
            f"({_describe_expr_for_comment(node.delay_ms)}) — not documented "
            "by UiPath (unlike DelayBefore), semantics not confirmed, "
            "refusing to guess"
        ]
    if node.alter_if_disabled is not None:
        return [
            f"{prefix}# TODO: Type Into with AlterIfDisabled set "
            f"({_describe_expr_for_comment(node.alter_if_disabled)}) — "
            "default not documented by UiPath, refusing to guess"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: Type Into with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    activate_literal = _literal_str(node.activate_before)
    if node.activate_before is not None and activate_literal not in ("True", "False"):
        return [
            f"{prefix}# TODO: Type Into with non-literal Activate/"
            f"ActivateBefore ({node.activate_before!r}) — refusing to guess"
        ]
    rendered = selector_text_to_pywinauto(node.selector)
    if rendered.expr == 'Desktop(backend="uia")':
        return [
            f"{prefix}# TODO: Type Into selector had no mappable attributes: "
            f"{node.selector}"
        ]
    todo: list[str] = []
    delay_before = (
        _render_value_or_todo(node.delay_before, prefix, todo)
        if node.delay_before is not None
        else None
    )
    delay_between_keys = (
        _render_value_or_todo(node.delay_between_keys, prefix, todo)
        if node.delay_between_keys is not None
        else None
    )
    text = _render_value_or_todo(node.text, prefix, todo)
    if todo:
        return todo
    lines = [f"{prefix}# WARNING: {w}" for w in rendered.warnings]
    if delay_before is not None:
        lines.append(f"{prefix}time.sleep({VB_NUM_HELPER_NAME}({delay_before}) / 1000.0)")
    if click_before == "True":
        lines.append(f"{prefix}{rendered.expr}.click_input()")
    kwarg_parts: list[str] = []
    if activate_literal == "False":
        kwarg_parts.append("set_foreground=False")
    if delay_between_keys is not None:
        kwarg_parts.append(f"pause=({VB_NUM_HELPER_NAME}({delay_between_keys}) / 1000.0)")
    text_arg = f"{_TYPE_KEYS_ESCAPE_HELPER_NAME}({VB_CSTR_HELPER_NAME}({text}))"
    args = ", ".join([text_arg, *kwarg_parts])
    lines.append(f"{prefix}{rendered.expr}.type_keys({args})")
    return lines


# 知見152: `ui:SendHotkey`。実機確認済みの特殊キー名(`Key`属性が1文字の
# 生リテラルでない場合)——`SpecialKey`属性自体はパース時点(types.py
# docstring参照)で意図的に無視し、`Key`の文字列値だけで判定する。
_SEND_HOTKEY_NAMED_KEYS = {
    "enter": "ENTER",
    "tab": "TAB",
    "esc": "ESC",
    "pgup": "PGUP",
    "pgdn": "PGDN",
    "home": "HOME",
    "end": "END",
    "up": "UP",
    "down": "DOWN",
    "left": "LEFT",
    "right": "RIGHT",
    "del": "DEL",
}
_SEND_HOTKEY_FKEY_RE = re.compile(r"^f([1-9]|1[0-9]|2[0-4])$")
_SEND_HOTKEY_NUMPAD_RE = re.compile(r"^num([0-9])$")
# `~^%+(){}`はpywinautoの`type_keys()`ミニ言語で特殊文字扱いされるため
# (`_TYPE_KEYS_ESCAPE_HELPER_SOURCE`と同じ規則)、生の1文字キーでもこれら
# に当たる場合は`{ch}`で囲む——`Key`は常に確認済みのリテラル文字列
# (`_literal_str`経由)なので、実行時ヘルパーを呼ばず生成時に静的に処理
# できる。
_SEND_HOTKEY_SPECIAL_CHARS = "~^%+(){}"


def _send_hotkey_key_token(key: str) -> str | None:
    lowered = key.lower()
    if lowered in _SEND_HOTKEY_NAMED_KEYS:
        return f"{{{_SEND_HOTKEY_NAMED_KEYS[lowered]}}}"
    match = _SEND_HOTKEY_FKEY_RE.match(lowered)
    if match is not None:
        return f"{{F{match.group(1)}}}"
    match = _SEND_HOTKEY_NUMPAD_RE.match(lowered)
    if match is not None:
        return f"{{VK_NUMPAD{match.group(1)}}}"
    if len(key) == 1:
        if key in _SEND_HOTKEY_SPECIAL_CHARS:
            return f"{{{key}}}"
        return key
    return None


# 知見152: `KeyModifiers`は.NETの`[Flags]`列挙型のToString()直列化形式
# (`", "`区切り、実機確認済み: `"Ctrl, Shift"`)。`Ctrl`/`Alt`/`Shift`は
# pywinautoの`^`/`%`/`+`接頭辞構文へ直接対応するが、`Win`は同じ接頭辞
# 構文に無い(Windowsキーをモディファイアとして押し続ける構文は
# `{VK_LWIN down}`...`{VK_LWIN up}`で囲む必要がある、実機確認済み
# `KeyModifiers="Win"`単独の実例(`KonduitAI/objectrecognition-rpa`)の
# みサポートし、他のモディファイアとの併用は未確認のため`# TODO`へ倒す。
_SEND_HOTKEY_PREFIX_MODIFIERS = {"ctrl": "^", "alt": "%", "shift": "+"}


def _send_hotkey_wrap_with_modifiers(
    key_modifiers_literal: str, key_token: str
) -> str | None:
    tokens = [t.strip().lower() for t in key_modifiers_literal.split(",")]
    if tokens == ["none"]:
        return key_token
    if tokens == ["win"]:
        return f"{{VK_LWIN down}}{key_token}{{VK_LWIN up}}"
    if "win" in tokens:
        return None
    if len(set(tokens)) != len(tokens):
        return None
    prefix = ""
    for name in ("ctrl", "alt", "shift"):
        if name in tokens:
            prefix += _SEND_HOTKEY_PREFIX_MODIFIERS[name]
    if len(prefix) != len(tokens):
        return None
    return prefix + key_token


def _generate_send_hotkey(node: SendHotkeyNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_send_hotkey_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_send_hotkey_body(node: SendHotkeyNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if not node.selector:
        return [
            f"{prefix}# TODO: SendHotkey with no Target captured (global/"
            "active-window send not yet supported)"
        ]
    key_literal = _literal_str(node.key)
    if key_literal is None:
        return [f"{prefix}# TODO: SendHotkey with no confirmed literal Key captured"]
    key_token = _send_hotkey_key_token(key_literal)
    if key_token is None:
        return [
            f"{prefix}# TODO: SendHotkey with unrecognized Key {key_literal!r} — "
            "not a confirmed single character or named special key, refusing "
            "to guess"
        ]
    modifiers_literal = _literal_str(node.key_modifiers)
    if modifiers_literal is None:
        return [f"{prefix}# TODO: SendHotkey with no confirmed literal KeyModifiers captured"]
    key_sequence = _send_hotkey_wrap_with_modifiers(modifiers_literal, key_token)
    if key_sequence is None:
        return [
            f"{prefix}# TODO: SendHotkey with unrecognized KeyModifiers "
            f"{modifiers_literal!r} — refusing to guess"
        ]
    if _literal_str(node.send_window_messages) not in (None, "False"):
        return [
            f"{prefix}# TODO: SendHotkey with non-default SendWindowMessages "
            f"({node.send_window_messages!r}) — exact mapping not confirmed, "
            "refusing to guess"
        ]
    click_before = _literal_str(node.click_before_typing)
    if click_before not in (None, "False", "True"):
        return [
            f"{prefix}# TODO: SendHotkey with unrecognized ClickBeforeTyping "
            f"({node.click_before_typing!r}) — refusing to guess"
        ]
    if _literal_str(node.empty_field) not in (None, "False"):
        return [
            f"{prefix}# TODO: SendHotkey with EmptyField set "
            f"({node.empty_field!r}) — exact field-clearing mechanism not "
            "confirmed, refusing to guess"
        ]
    if node.delay_ms is not None:
        return [
            f"{prefix}# TODO: SendHotkey with DelayMS set "
            f"({_describe_expr_for_comment(node.delay_ms)}) — not documented "
            "by UiPath (unlike DelayBefore), semantics not confirmed, "
            "refusing to guess"
        ]
    if node.delay_between_keys is not None:
        return [
            f"{prefix}# TODO: SendHotkey with DelayBetweenKeys set "
            f"({_describe_expr_for_comment(node.delay_between_keys)}) — a "
            "single Key press has no \"between keys\" to delay, semantics "
            "not confirmed, refusing to guess"
        ]
    activate_literal = _literal_str(node.activate)
    if node.activate is not None and activate_literal not in ("True", "False"):
        return [
            f"{prefix}# TODO: SendHotkey with non-literal Activate "
            f"({node.activate!r}) — refusing to guess"
        ]
    rendered = selector_text_to_pywinauto(node.selector)
    if rendered.expr == 'Desktop(backend="uia")':
        return [
            f"{prefix}# TODO: SendHotkey selector had no mappable attributes: "
            f"{node.selector}"
        ]
    todo: list[str] = []
    delay_before = (
        _render_value_or_todo(node.delay_before, prefix, todo)
        if node.delay_before is not None
        else None
    )
    if todo:
        return todo
    lines = [f"{prefix}# WARNING: {w}" for w in rendered.warnings]
    if delay_before is not None:
        lines.append(f"{prefix}time.sleep({VB_NUM_HELPER_NAME}({delay_before}) / 1000.0)")
    if click_before == "True":
        lines.append(f"{prefix}{rendered.expr}.click_input()")
    kwarg_parts: list[str] = []
    if activate_literal == "False":
        kwarg_parts.append("set_foreground=False")
    args = ", ".join([repr(key_sequence), *kwarg_parts])
    lines.append(f"{prefix}{rendered.expr}.type_keys({args})")
    return lines


# 知見111: `ui:GetText`。`ContinueOnError`/`DelayMS`は`Click`/`TypeInto`と
# 同じ理由(未確認/未文書化)で非既定値は`# TODO`へ倒す。`DelayBefore`は
# 同じUI Automationパッケージの「Common」カテゴリの属性で、`Click`/
# `TypeInto`で確認済みの意味論(活動開始前の待機)がそのまま適用できる。
#
# 公式ドキュメント(`get-value`ページ)は抽出の正確なAPI(UIAの`Name`/
# `ValuePattern`か、Win32の`GetWindowText`か等)を明記していないが、
# 「指定したUI要素から可視テキストを最大4096文字抽出する」という挙動は
# 確認できている——`pywinauto`の`window_text()`(バックエンドに応じて
# 適切なAPIへ自動的にディスパッチする、要素の表示テキストを返す標準的な
# アクセサ)を正確な1対1対応の主張はせず`# WARNING`付きで採用する
# (`Click`のセレクタマッピング同様、「要素を一意に特定できることまでは
# 主張しない」という既存の警告方針を踏襲)。
def _generate_get_text(node: GetTextNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_get_text_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_get_text_body(node: GetTextNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    # 知見159: `full_text`(`ui:GetFullText`)の場合はラベル/警告文言を
    # 区別する——`GetText`/`GetFullText`は別の活動で、公式ドキュメントが
    # 意味論を明確に区別している(可視テキストのみ・最大4096文字 vs
    # 非表示/切り詰められた部分を含むフルテキスト)ため、両方を同じ
    # `window_text()`へ変換するのは`GetFullText`側でより弱い近似になる
    # ことを警告コメントで明示する。
    label = "Get Full Text" if node.full_text else "Get Text"
    if not node.selector:
        return [f"{prefix}# TODO: {label} with no selector captured"]
    if node.text is None:
        return [f"{prefix}# TODO: {label} with no output Text captured"]
    if node.delay_ms is not None:
        return [
            f"{prefix}# TODO: {label} with DelayMS set "
            f"({_describe_expr_for_comment(node.delay_ms)}) — not documented "
            "by UiPath (unlike DelayBefore), semantics not confirmed, "
            "refusing to guess"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: {label} with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    if _literal_str(node.ignore_hidden) not in (None, "False"):
        return [
            f"{prefix}# TODO: {label} with non-default IgnoreHidden "
            f"({node.ignore_hidden!r}) — exact mechanism not confirmed, "
            "refusing to guess"
        ]
    rendered = selector_text_to_pywinauto(node.selector)
    if rendered.expr == 'Desktop(backend="uia")':
        return [
            f"{prefix}# TODO: {label} selector had no mappable attributes: "
            f"{node.selector}"
        ]
    todo: list[str] = []
    delay_before = (
        _render_value_or_todo(node.delay_before, prefix, todo)
        if node.delay_before is not None
        else None
    )
    target = _render_value_or_todo(node.text, prefix, todo)
    if todo:
        return todo
    lines = [f"{prefix}# WARNING: {w}" for w in rendered.warnings]
    if node.full_text:
        lines.append(
            f"{prefix}# WARNING: exact UI Automation API behind 'Get Full "
            "Text' not independently confirmed (docs state it also covers "
            "non-visible/truncated text, unlike 'Get Text') — using "
            "pywinauto's generic window_text() accessor, which may return "
            "less text than UiPath's real implementation"
        )
    else:
        lines.append(
            f"{prefix}# WARNING: exact UI Automation API behind 'Get Text' not "
            "independently confirmed (docs only state visible-text extraction, "
            "max 4096 chars) — using pywinauto's generic window_text() accessor"
        )
    if delay_before is not None:
        lines.append(f"{prefix}time.sleep({VB_NUM_HELPER_NAME}({delay_before}) / 1000.0)")
    lines.append(f"{prefix}{target} = {rendered.expr}.window_text()")
    return lines


# 知見112: `ui:SelectItem`。`AlterIfDisabled`は`Click`/`TypeInto`とは違い
# 公式ドキュメントで確認済みの既定値(`True`相当——本活動は入力方式が
# `SimulateClick`固定で変更不可、無効化された要素も既定で操作対象になる
# と明記されている)。確認済みの`"True"`/未設定のみ対応、`"False"`
# (無効化要素を操作しない、という逆の挙動)は`pywinauto`の`.select()`に
# それを再現する手段が未確認のため`# TODO`へ倒す。
#
# `Item`を実際に選択する手段は、公式ドキュメントが「対象アプリ自身の
# 技術を使う(SimulateClick)」と明言している——これは`Click`の
# `SimulateClick`(機構未確認のため見送り)とは違い、`pywinauto`の
# `.select()`(Win32の`ComboBoxWrapper`は`CB_SELECTSTRING`等のネイティブ
# メッセージ、UIAは`SelectionItemPattern.Select()`——いずれも「対象の
# ネイティブAPIを直接呼ぶ」という点で「対象アプリ自身の技術を使う」という
# 記述のカテゴリに合致する)という既存の標準アクセサで妥当にマッピング
# できると判断した。1対1の機構確認までは主張せず`# WARNING`を付す。
def _generate_select_item(node: SelectItemNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_select_item_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_select_item_body(node: SelectItemNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if not node.selector:
        return [f"{prefix}# TODO: Select Item with no selector captured"]
    if node.item is None:
        return [f"{prefix}# TODO: Select Item with no Item captured"]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: Select Item with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    if _literal_str(node.alter_if_disabled) not in (None, "True"):
        return [
            f"{prefix}# TODO: Select Item with AlterIfDisabled set "
            f"({node.alter_if_disabled!r}) — UiPath docs only confirm the "
            "True-like default (disabled elements altered by default), "
            "refusing to guess how to reproduce False with pywinauto's "
            "select()"
        ]
    rendered = selector_text_to_pywinauto(node.selector)
    if rendered.expr == 'Desktop(backend="uia")':
        return [
            f"{prefix}# TODO: Select Item selector had no mappable "
            f"attributes: {node.selector}"
        ]
    todo: list[str] = []
    delay_before = (
        _render_value_or_todo(node.delay_before, prefix, todo)
        if node.delay_before is not None
        else None
    )
    delay_after = (
        _render_value_or_todo(node.delay_after, prefix, todo)
        if node.delay_after is not None
        else None
    )
    item = _render_value_or_todo(node.item, prefix, todo)
    if todo:
        return todo
    lines = [f"{prefix}# WARNING: {w}" for w in rendered.warnings]
    lines.append(
        f"{prefix}# WARNING: exact UI Automation API behind 'Select Item' "
        "not independently confirmed (docs only state it uses "
        "SimulateClick, i.e. the target application's own technology) — "
        "using pywinauto's generic select() accessor"
    )
    if delay_before is not None:
        lines.append(f"{prefix}time.sleep({VB_NUM_HELPER_NAME}({delay_before}) / 1000.0)")
    lines.append(f"{prefix}{rendered.expr}.select({VB_CSTR_HELPER_NAME}({item}))")
    if delay_after is not None:
        lines.append(f"{prefix}time.sleep({VB_NUM_HELPER_NAME}({delay_after}) / 1000.0)")
    return lines


# 知見113: `ui:UiElementExists`(DisplayName「Element Exists」)。公式
# ドキュメント・3件の独立した実機保存済みXAMLのいずれにも`ContinueOnError`/
# `DelayBefore`/`DelayMS`に相当する属性が存在しないため、`Click`等とは違い
# これらのTODO分岐は無い(無い属性を推測で持たせるとでっち上げになる)。
#
# 「要素が存在するか(可視でなくても)を確認する、見つからなくても例外を
# 投げない」という公式ドキュメントの説明は、`pywinauto`の
# `WindowSpecification.exists()`(未解決の検索条件に対して呼べる、見つか
# らなければ例外を投げずに`False`を返す標準アクセサ)の挙動そのものと
# ほぼ1対1で一致する——`Click`/`Select Item`のような機構未確認の警告は
# 不要なほど確信度が高いマッピング。
def _generate_ui_element_exists(node: UiElementExistsNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_ui_element_exists_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_ui_element_exists_body(node: UiElementExistsNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if not node.selector:
        return [f"{prefix}# TODO: Element Exists with no selector captured"]
    if node.exists is None:
        return [f"{prefix}# TODO: Element Exists with no output Exists captured"]
    rendered = selector_text_to_pywinauto(node.selector)
    if rendered.expr == 'Desktop(backend="uia")':
        return [
            f"{prefix}# TODO: Element Exists selector had no mappable "
            f"attributes: {node.selector}"
        ]
    todo: list[str] = []
    target = _render_value_or_todo(node.exists, prefix, todo)
    if todo:
        return todo
    lines = [f"{prefix}# WARNING: {w}" for w in rendered.warnings]
    lines.append(f"{prefix}{target} = {rendered.expr}.exists()")
    return lines


def _parse_ado_connection_string(connection_string: str) -> dict[str, str]:
    """ADO.NET接続文字列(`Key1=Value1;Key2=Value2;...`)を辞書に分解する
    (知見114)。キーは小文字・前後空白除去で正規化する(実機確認済みの
    `"Data Source=db.sqlite;Version=3;"`は`Data Source`というスペース
    入りキー)。"""
    parts: dict[str, str] = {}
    for segment in connection_string.split(";"):
        if "=" not in segment:
            continue
        key, _, value = segment.partition("=")
        parts[key.strip().lower()] = value.strip()
    return parts


# 知見114: `ui:DatabaseConnect`。実機確認できた`ProviderName=
# "System.Data.SQLite"`のみ対応する——.NET ADO.NETのプロバイダ名/接続
# 文字列書式はプロバイダごとに異なり、Python側も別ライブラリ(SQL Server
# なら`pyodbc`等)が必要になるため、未確認のプロバイダをでっち上げた
# ライブラリ呼び出しへ変換するより`# TODO`に倒す方が安全。
_SQLITE_PROVIDER_NAMES = {"system.data.sqlite", "sqlite"}


def _generate_database_connect(node: DatabaseConnectNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_database_connect_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_database_connect_body(node: DatabaseConnectNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.database_connection is None:
        return [f"{prefix}# TODO: Database Connect with no output DatabaseConnection captured"]
    if node.secure_connection_string is not None:
        return [
            f"{prefix}# TODO: Database Connect with SecureConnectionString set "
            "— not yet confirmed via real capture, refusing to guess"
        ]
    if not isinstance(node.provider_name, Literal) or node.provider_name.value.strip().lower() not in _SQLITE_PROVIDER_NAMES:
        return [
            f"{prefix}# TODO: Database Connect with unconfirmed ProviderName "
            f"({node.provider_name!r}) — only System.Data.SQLite is confirmed/"
            "mapped so far, refusing to guess a Python driver for other "
            "providers"
        ]
    if not isinstance(node.connection_string, Literal):
        return [
            f"{prefix}# TODO: Database Connect with non-literal ConnectionString "
            f"({node.connection_string!r}) — cannot statically extract the "
            "SQLite file path, refusing to guess"
        ]
    ado_parts = _parse_ado_connection_string(node.connection_string.value)
    db_path = ado_parts.get("data source")
    if db_path is None:
        return [
            f"{prefix}# TODO: Database Connect with ConnectionString missing a "
            f"'Data Source' key ({node.connection_string.value!r}) — refusing "
            "to guess"
        ]
    todo: list[str] = []
    target = _render_value_or_todo(node.database_connection, prefix, todo)
    if todo:
        return todo
    return [
        f"{prefix}{target} = sqlite3.connect({db_path!r})",
        f"{prefix}{target}.row_factory = sqlite3.Row",
    ]


def _generate_database_disconnect(node: DatabaseDisconnectNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_database_disconnect_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_database_disconnect_body(node: DatabaseDisconnectNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.database_connection is None:
        return [f"{prefix}# TODO: Database Disconnect with no DatabaseConnection captured"]
    todo: list[str] = []
    target = _render_value_or_todo(node.database_connection, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}{target}.close()"]


# 知見114: `ui:ExecuteQuery`/`ui:ExecuteNonQuery`共通のガード。両活動とも
# `ExistingDbConnection`必須(接続文字列を自前で持たない)・`CommandType`
# 実機確認済みの値は`"Text"`のみ・`Parameters`は空の場合のみ対応
# (populated時のプレースホルダ書式`:name`/`@name`/`?`のどれがSQL側で
# 使われるか未確認のため、でっち上げず`# TODO`に倒す)。
def _execute_query_family_todo(
    prefix: str,
    existing_db_connection: Expr,
    command_type: str | None,
    parameters: dict[str, Expr],
    continue_on_error: Expr,
    timeout_ms: Expr,
    activity_label: str,
) -> list[str] | None:
    if existing_db_connection is None:
        return [f"{prefix}# TODO: {activity_label} with no ExistingDbConnection captured"]
    if command_type not in (None, "Text"):
        return [
            f"{prefix}# TODO: {activity_label} with unconfirmed CommandType "
            f"({command_type!r}) — only 'Text' is confirmed, refusing to guess"
        ]
    if parameters:
        return [
            f"{prefix}# TODO: {activity_label} with populated Parameters — "
            "the exact SQL placeholder syntax UiPath expects (':name'/"
            "'@name'/'?') is not confirmed via real capture, refusing to "
            "guess"
        ]
    if continue_on_error is not None:
        return [
            f"{prefix}# TODO: {activity_label} with ContinueOnError set "
            f"({_describe_expr_for_comment(continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    if timeout_ms is not None:
        return [
            f"{prefix}# TODO: {activity_label} with TimeoutMS set "
            f"({_describe_expr_for_comment(timeout_ms)}) — Python's sqlite3 "
            "has no matching per-query execution timeout, refusing to guess"
        ]
    return None


def _generate_execute_query(node: ExecuteQueryNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_execute_query_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_execute_query_body(node: ExecuteQueryNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.data_table is None:
        return [f"{prefix}# TODO: Execute Query with no output DataTable captured"]
    if node.sql is None:
        return [f"{prefix}# TODO: Execute Query with no Sql captured"]
    todo = _execute_query_family_todo(
        prefix,
        node.existing_db_connection,
        node.command_type,
        node.parameters,
        node.continue_on_error,
        node.timeout_ms,
        "Execute Query",
    )
    if todo is not None:
        return todo
    collected: list[str] = []
    conn = _render_value_or_todo(node.existing_db_connection, prefix, collected)
    sql = _render_value_or_todo(node.sql, prefix, collected)
    target = _render_value_or_todo(node.data_table, prefix, collected)
    if collected:
        return collected
    return [
        f"{prefix}_cur = {conn}.execute({sql})",
        f"{prefix}{target} = [dict(_r) for _r in _cur.fetchall()]",
    ]


def _generate_execute_non_query(node: ExecuteNonQueryNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_execute_non_query_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_execute_non_query_body(node: ExecuteNonQueryNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.affected_records is None:
        return [f"{prefix}# TODO: Execute Non Query with no output AffectedRecords captured"]
    if node.sql is None:
        return [f"{prefix}# TODO: Execute Non Query with no Sql captured"]
    todo = _execute_query_family_todo(
        prefix,
        node.existing_db_connection,
        node.command_type,
        node.parameters,
        node.continue_on_error,
        node.timeout_ms,
        "Execute Non Query",
    )
    if todo is not None:
        return todo
    collected: list[str] = []
    conn = _render_value_or_todo(node.existing_db_connection, prefix, collected)
    sql = _render_value_or_todo(node.sql, prefix, collected)
    target = _render_value_or_todo(node.affected_records, prefix, collected)
    if collected:
        return collected
    return [
        f"{prefix}_cur = {conn}.execute({sql})",
        f"{prefix}{conn}.commit()",
        f"{prefix}{target} = _cur.rowcount",
    ]


# 知見117: `ui:CopyFile`。`Destination`がフォルダパスの場合は元のファイル名
# で、ファイルパスの場合は指定した名前でコピーされると公式ドキュメントで
# 確認済み——`shutil.copy()`自体がこの区別を内部で処理する(挙動を再発明
# しない)。`Overwrite=False`時の挙動(既存ファイルがある場合にどうなるか)
# は公式ドキュメントに明記が無いが、裏の.NET API(`File.Copy(src, dest,
# overwrite)`)の確立済みの契約(overwrite=false時は`IOException`)に
# 基づき、既存ファイルがあれば`FileExistsError`を投げる形にマッピングする
# ——これはUiPath固有のドキュメントではなく.NET自体の公開APIコントラクト
# に基づく判断であり、架空の挙動のでっち上げとは別種の確信度と位置づける。
def _generate_copy_file(node: CopyFileNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_copy_file_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_copy_file_body(node: CopyFileNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.path is None or node.destination is None:
        return [f"{prefix}# TODO: Copy File with missing Path/Destination"]
    if node.destination_resource is not None or node.path_resource is not None:
        return [
            f"{prefix}# TODO: Copy File with DestinationResource/PathResource set "
            "— Integration Service resource handling not confirmed, refusing "
            "to guess"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: Copy File with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    if node.overwrite not in ("True", "False"):
        return [
            f"{prefix}# TODO: Copy File with unrecognized/unset Overwrite "
            f"({node.overwrite!r}) — true default behavior not confirmed, "
            "refusing to guess"
        ]
    todo: list[str] = []
    path = _render_value_or_todo(node.path, prefix, todo)
    destination = _render_value_or_todo(node.destination, prefix, todo)
    if todo:
        return todo
    lines = [
        f"{prefix}_src = {path}",
        f"{prefix}_dest = {destination}",
        f"{prefix}if os.path.isdir(_dest):",
        f"{INDENT * (indent + 1)}_dest = os.path.join(_dest, os.path.basename(_src))",
    ]
    if node.overwrite == "False":
        lines.append(f"{prefix}if os.path.exists(_dest):")
        lines.append(f"{INDENT * (indent + 1)}raise FileExistsError(_dest)")
    lines.append(f"{prefix}shutil.copy(_src, _dest)")
    return lines


# 知見117: `ui:BuildDataTable`。`TableInfo`に埋め込まれた.NET `DataSet`の
# XMLスキーマから列名を抜き出せるが(`_build_data_table_columns`)、
# Pythonの`list[dict]`表現(`ExecuteQuery`/`ExcelReadRange`と同じ、知見114・
# 115)では列は各行の辞書キーとして実行時に決まるため、空のテーブルの
# 生成自体には列名は不要——`SelectItem.Items`(知見112)と同じ「design-time
# スナップショットは実行時に不要」という判断。
def _generate_build_data_table(node: BuildDataTableNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_build_data_table_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_build_data_table_body(node: BuildDataTableNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.data_table is None:
        return [f"{prefix}# TODO: Build Data Table with no output DataTable captured"]
    todo: list[str] = []
    target = _render_value_or_todo(node.data_table, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}{target} = []"]


# `ContinueOnError`(知見72、実機XAMLで確認した`ui:InvokeWorkflowFile`の
# 属性)が`True`相当の場合、VBは呼び出し先が例外を出しても継続する——
# 現在の生成コード(単純な関数呼び出し)は例外をそのまま伝播させるため、
# 食い違う。実機で`ContinueOnError="True"`の実例・正確な継続後の挙動
# (戻り値をどう扱うか等)を未確認のため、でっち上げたtry/except変換は
# せず`# TODO`に倒す——未設定(`None`)/明示的な`"False"`は現在の挙動
# (伝播)と一致するため確認済みの安全な値として扱う。
_CONTINUE_ON_ERROR_SAFE_VALUES = (None, Literal(value="False"))


def _generate_invoke_workflow_file(
    node: InvokeWorkflowFileNode,
    indent: int,
    invoke_resolver: dict[str, str] | None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    """`invoke_resolver`(`generate_project_python()`が構築する、
    `workflow_file`文字列→Python関数名の対応表)に解決先が見つかった場合のみ
    実際の関数呼び出しへ変換する。単体の`generate_python()`呼び出し
    (`invoke_resolver=None`)や、参照先が解決できなかった場合は、
    呼び出し先の存在を仮定した架空のコードをでっち上げず`# TODO`に倒す。
    `ContinueOnError`(知見72)が確認済みの安全な値から外れている場合も
    同様に`# TODO`へ倒す。

    知見86: 呼び出し先の関数定義側には知見78の`# TODO`が出るが、呼び出し元
    のこの呼び出し文自体には何の警告も出なかった——`out_arg_resolver`
    (`workflow_file`文字列→呼び出し先のOut/InOutArgument方向の引数名
    集合)で、今回の呼び出しが実際にそのいずれかへ値を束縛している場合、
    呼び出し文の直前に`# WARNING`を追記する(呼び出し自体は通常通り
    生成する——`In`方向の引数は正しく機能するため、呼び出しそのものを
    妨げる理由は無い)。"""
    prefix = INDENT * indent
    if node.continue_on_error not in _CONTINUE_ON_ERROR_SAFE_VALUES:
        return [
            f"{prefix}# TODO: Invoke Workflow File with non-default ContinueOnError "
            f"({node.continue_on_error!r}) — error-continuation semantics not "
            "confirmed via real capture, refusing to guess"
        ]
    func_name = (invoke_resolver or {}).get(node.workflow_file)
    if func_name is None:
        return [f"{prefix}# TODO: unresolved Invoke Workflow File: {node.workflow_file}"]
    todo: list[str] = []
    kwargs = []
    for key, expr in node.arguments.items():
        value = _render_value_or_todo(expr, prefix, todo)
        kwargs.append(f"{key}={value}")
    out_args_here = (out_arg_resolver or {}).get(node.workflow_file, frozenset())
    bound_out_args = sorted(out_args_here & node.arguments.keys())
    warning = []
    if bound_out_args:
        warning = [
            f"{prefix}# WARNING: {', '.join(bound_out_args)} are Out/InOutArgument on "
            f"{func_name}() — the bound variable here will NOT be updated after this "
            "call (VB ByRef write-back not supported, see the TODO in the callee)"
        ]
    return [*todo, *warning, f"{prefix}{func_name}({', '.join(kwargs)})"]


def _with_scope_child_display_name(node: Node, lines: list[str], prefix: str) -> list[str]:
    """`ExcelApplicationScopeNode`配下の子活動(`ExcelReadRangeNode`等)の
    `display_name`は捕捉済みだったが知見117まで未活用だった(知見75・
    92〜95と同種の「捕捉済みデータの未活用」)——`# TODO`に倒れない実コード
    生成の場合も含め、どの活動かが分かるようコメントとして先頭に追記する。"""
    display_name = getattr(node, "display_name", None)
    if display_name:
        # 知見141: `display_name`(`DisplayName`属性)が万一改行を含む
        # 場合でも単一行のコメントであることを保証する(`_todo_value`/
        # `_describe_expr_for_comment`と同じ防御的な単一行化)。
        single_line = display_name.replace("\n", "\\n")
        return [f"{prefix}# {single_line}", *lines]
    return lines


# 知見153: `ui:AttachWindow`(GitHub code searchで1100件ヒット)。
# `ExcelApplicationScopeNode`とは違い`scope_var`束縛を一切作らない
# 透過的なラッパーとして実装する——実機確認済みの子活動(`Click`/
# `TypeInto`/`SendHotkey`)は全て`selector`を自己完結的に(絶対パスで)
# 保持する設計のため、`AttachWindow`が解決したウィンドウハンドルへの
# 相対参照に子が依存する構造には**なっていない**(`types.py`の
# `AttachWindowNode`docstring参照)。`Selector`は実行可能なコードでは
# なく注釈コメントとして出力し、子はそのまま`_generate_body`で再帰
# 生成する。
def _generate_attach_window(
    node: AttachWindowNode, indent: int,
    invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_attach_window_body(node, indent, invoke_resolver, out_arg_resolver)
    return _with_scope_child_display_name(node, lines, prefix)


# 知見158: `ui:WindowScope`(`AttachWindow`と同義の別活動)が持つ
# `ApplicationWindow`/`SearchScope`/`TimeoutMS`/`Window`は、実機確認
# した9件以上全てで未設定だった——設定されている場合は
# `OpenApplication`の`ApplicationWindow`等と同じ理由(正確な意味論が
# 未確認)で`# TODO`へ倒す。`ui:AttachWindow`自体はこれらの属性を
# 持たないため常に`None`のままで、この分岐には到達しない。
def _generate_attach_window_body(
    node: AttachWindowNode, indent: int,
    invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    prefix = INDENT * indent
    # 知見161: `BrowserScope`(「Attach Browser」)固有の属性(`browser_
    # type`)が設定されている場合のみラベルを切り替える——`AttachWindow`
    # /`WindowScope`では常に`None`のまま。
    label = "BrowserScope" if node.browser_type is not None else "WindowScope"
    if node.application_window is not None:
        return [
            f"{prefix}# TODO: {label} with ApplicationWindow output "
            f"binding set ({_describe_expr_for_comment(node.application_window)}) "
            "— UiElement output variable not modeled, refusing to guess"
        ]
    if node.search_scope is not None:
        return [
            f"{prefix}# TODO: {label} with SearchScope set "
            f"({_describe_expr_for_comment(node.search_scope)}) — refusing "
            "to guess"
        ]
    if node.timeout_ms is not None:
        return [
            f"{prefix}# TODO: {label} with TimeoutMS set "
            f"({_describe_expr_for_comment(node.timeout_ms)}) — wait-for-"
            "window-ready polling behavior not modeled, refusing to guess"
        ]
    if node.window is not None:
        return [
            f"{prefix}# TODO: WindowScope with Window set "
            f"({_describe_expr_for_comment(node.window)}) — refusing to guess"
        ]
    # 知見161: `ui:BrowserScope`(「Attach Browser」)固有のフィールド。
    # `BrowserType`(どのブラウザエンジンかを示すだけの単純な注釈情報、
    # 実機確認済みの`"Chrome"`/`"Firefox"`/`"IE"`等)は透過的ラッパーの
    # 動作自体に影響しないためdecline判定の対象にしない。
    if node.browser is not None:
        return [
            f"{prefix}# TODO: BrowserScope with Browser set "
            f"({_describe_expr_for_comment(node.browser)}) — attaching via "
            "an existing UiBrowser variable reference (rather than Selector) "
            "not modeled, refusing to guess"
        ]
    if node.ui_browser is not None:
        return [
            f"{prefix}# TODO: BrowserScope with UiBrowser output binding set "
            f"({_describe_expr_for_comment(node.ui_browser)}) — UiBrowser "
            "output variable not modeled, refusing to guess"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: BrowserScope with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    lines: list[str] = []
    if node.selector:
        lines.append(f"{prefix}# Attach window: {node.selector}")
    lines.extend(_generate_body(node.body, indent, invoke_resolver, out_arg_resolver))
    return _ensure_nonempty_suite(lines, indent)


# 知見154: `ui:OpenApplication`。`AttachWindow`(知見153)と同じ理由
# (子活動が`selector`を自己完結的に保持する設計)で`ContextTarget`
# (`ActivityAction`+`DelegateInArgument`の束縛変数)は束縛しない。
# `FileName`のみ(+`Selector`の注釈コメント)の確認済みの単純な場合
# だけ`subprocess.Popen([...])`で実際に起動するコードを生成し、
# `Arguments`/`WorkingDirectory`/`ApplicationWindow`/`TimeoutMS`/
# `ContinueOnError`のいずれかが設定されている場合は、それぞれの正確な
# 意味論(Windowsコマンドライン分割規則/UiElement出力変数表現/
# ウィンドウ出現待ちのポーリング挙動)が未確認のため`# TODO`へ倒す
# (でっち上げるよりは安全)——「開いたプロセスの準備ができるまで待つ」
# 挙動自体も本実装では再現しない(`ExcelApplicationScope`のライブ
# マクロ実行未対応と同種の既知の限界)。
def _generate_open_application(
    node: OpenApplicationNode, indent: int,
    invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_open_application_body(node, indent, invoke_resolver, out_arg_resolver)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_open_application_body(
    node: OpenApplicationNode, indent: int,
    invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    prefix = INDENT * indent
    if node.file_name is None:
        return [f"{prefix}# TODO: OpenApplication with no FileName captured"]
    if node.arguments is not None:
        return [
            f"{prefix}# TODO: OpenApplication with Arguments set "
            f"({_describe_expr_for_comment(node.arguments)}) — Windows "
            "command-line splitting semantics not confirmed, refusing to guess"
        ]
    if node.working_directory is not None:
        return [
            f"{prefix}# TODO: OpenApplication with WorkingDirectory set "
            f"({_describe_expr_for_comment(node.working_directory)}) — "
            "refusing to guess"
        ]
    if node.application_window is not None:
        return [
            f"{prefix}# TODO: OpenApplication with ApplicationWindow output "
            f"binding set ({_describe_expr_for_comment(node.application_window)}) "
            "— UiElement output variable not modeled, refusing to guess"
        ]
    if node.timeout_ms is not None:
        return [
            f"{prefix}# TODO: OpenApplication with TimeoutMS set "
            f"({_describe_expr_for_comment(node.timeout_ms)}) — wait-for-"
            "window-ready polling behavior not modeled, refusing to guess"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: OpenApplication with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    try:
        file_name = render_expr(node.file_name)
    except NotImplementedError as e:
        return _todo_value(prefix, str(e))
    lines: list[str] = [f"{prefix}subprocess.Popen([{VB_CSTR_HELPER_NAME}({file_name})])"]
    if node.selector:
        lines.append(f"{prefix}# Attach window: {node.selector}")
    lines.extend(_generate_body(node.body, indent, invoke_resolver, out_arg_resolver))
    return lines


# 知見168: `ui:OpenBrowser`(GitHub code searchで2648件ヒット)。
# `OpenApplication`(知見154)と違い`BrowserType`別の実行ファイルパスが
# XAMLに明示されず推測が必要になるため、`subprocess.Popen([file_name])`
# のような経路が使えない——代わりにPython標準ライブラリの
# `webbrowser.open(url)`(特定のブラウザ実行ファイルパスを一切推測せず
# OS既定の方法でURLを開く、確認済みの標準API)を使う。`BrowserType`で
# 指定された特定のブラウザが実際に開かれることまでは主張しない。
def _generate_open_browser(
    node: OpenBrowserNode, indent: int,
    invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_open_browser_body(node, indent, invoke_resolver, out_arg_resolver)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_open_browser_body(
    node: OpenBrowserNode, indent: int,
    invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    prefix = INDENT * indent
    if node.url is None:
        return [f"{prefix}# TODO: OpenBrowser with no Url captured"]
    if _literal_str(node.hidden) not in (None, "False"):
        return [
            f"{prefix}# TODO: OpenBrowser with Hidden set "
            f"({node.hidden!r}) — headless-mode reproduction not confirmed, "
            "refusing to guess"
        ]
    if _literal_str(node.new_session) not in (None, "True"):
        return [
            f"{prefix}# TODO: OpenBrowser with non-default NewSession set "
            f"({node.new_session!r}) — session-reuse semantics not "
            "confirmed, refusing to guess"
        ]
    if _literal_str(node.private) not in (None, "False"):
        return [
            f"{prefix}# TODO: OpenBrowser with Private set "
            f"({node.private!r}) — private/incognito mode reproduction not "
            "confirmed, refusing to guess"
        ]
    if node.ui_browser is not None:
        return [
            f"{prefix}# TODO: OpenBrowser with UiBrowser output binding set "
            f"({_describe_expr_for_comment(node.ui_browser)}) — UiBrowser "
            "output variable not modeled, refusing to guess"
        ]
    if node.communication_method is not None:
        return [
            f"{prefix}# TODO: OpenBrowser with CommunicationMethod set "
            f"({_describe_expr_for_comment(node.communication_method)}) — "
            "semantics not confirmed, refusing to guess"
        ]
    todo: list[str] = []
    url = _render_value_or_todo(node.url, prefix, todo)
    if todo:
        return todo
    lines = [
        f"{prefix}# WARNING: BrowserType={node.browser_type!r} requested — "
        "webbrowser.open() uses the OS default browser, not necessarily "
        "this one"
    ]
    lines.append(f"{prefix}webbrowser.open({VB_CSTR_HELPER_NAME}({url}))")
    lines.extend(_generate_body(node.body, indent, invoke_resolver, out_arg_resolver))
    return lines


def _generate_excel_application_scope(
    node: ExcelApplicationScopeNode, indent: int,
    invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    """知見97: `ExcelApplicationScopeNode`は知見22以来常に`_generate_
    unresolved_activity`(知見84以降はその中で子を再帰生成するだけ)へ
    倒れていたが、ユーザー決定(2026-11-05、AskUserQuestion)により
    `openpyxl`(ファイルベース、Excelプロセス不要)への実コード生成に
    対応した——`openpyxl.load_workbook(workbook_path)`でスコープ先頭に
    開き、スコープ末尾で`.save(workbook_path)`する(PAD側の
    `pad_action_lib.excel_actions.launch_excel`/`save_excel`と同じ
    「ファイルを開く→操作→保存」モデル、ライブマクロ実行や開いたまま
    の対話操作は再現できないという同じ既知の限界を引き継ぐ)。

    `scope_var`(知見94)は実際にこのopenpyxl `Workbook`を束縛するPython
    変数名として使う——これまでコメントの中の値でしかなかったものが、
    初めて実際の生成コードの一部になる。

    直接の子が`ExcelWriteCellNode`(知見22でこの構造が実機確認済み唯一の
    「スコープと連動する」子活動)の場合のみ`scope_var`を使った実際の
    セル書き込みコードを生成する(`_generate_excel_write_cell_in_scope`)。
    それ以外の子は`scope_var`と無関係に汎用ディスパッチ(`_generate_node`)
    へそのまま委ねる——`ExcelWriteCellNode`がIf/Switch/ループ越しにネスト
    している場合はこの汎用ディスパッチ経由になり`scope_var`の文脈を失う
    (実機未確認のためその場合は`_generate_unresolved_activity`の
    `# TODO`へ安全に倒れる、知見84の「でっち上げず正直に倒す」方針を継承)。
    """
    prefix = INDENT * indent
    var = node.scope_var
    lines = [f"{prefix}{var} = openpyxl.load_workbook({node.workbook_path!r})"]
    for child in node.body:
        if isinstance(child, ExcelWriteCellNode):
            lines.extend(
                _with_scope_child_display_name(
                    child, _generate_excel_write_cell_in_scope(child, indent, var), prefix
                )
            )
        elif isinstance(child, ExcelReadCellNode):
            lines.extend(
                _with_scope_child_display_name(
                    child, _generate_excel_read_cell_in_scope(child, indent, var), prefix
                )
            )
        elif isinstance(child, ExcelReadRangeNode):
            lines.extend(
                _with_scope_child_display_name(
                    child, _generate_excel_read_range_in_scope(child, indent, var), prefix
                )
            )
        elif isinstance(child, ExcelWriteRangeNode):
            lines.extend(
                _with_scope_child_display_name(
                    child, _generate_excel_write_range_in_scope(child, indent, var), prefix
                )
            )
        elif isinstance(child, ExcelAppendRangeNode):
            lines.extend(
                _with_scope_child_display_name(
                    child, _generate_excel_append_range_in_scope(child, indent, var), prefix
                )
            )
        else:
            lines.extend(_generate_node(child, indent, invoke_resolver, out_arg_resolver))
    lines.append(f"{prefix}{var}.save({node.workbook_path!r})")
    return lines


def _generate_word_application_scope(
    node: WordApplicationScopeNode, indent: int,
    invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    """知見121: `ExcelApplicationScopeNode`(知見97)と同じ設計を踏襲する
    ——`python-docx`(ファイルベース、Wordプロセス不要、既にプロジェクト
    依存に含まれている)への実コード生成。`docx.Document(file_name)`で
    開き、スコープ末尾で`.save(file_name)`する。"""
    prefix = INDENT * indent
    var = node.scope_var
    lines = [f"{prefix}{var} = docx.Document({node.file_name!r})"]
    for child in node.body:
        if isinstance(child, WordReplaceTextNode):
            lines.extend(
                _with_scope_child_display_name(
                    child, _generate_word_replace_text_in_scope(child, indent, var), prefix
                )
            )
        else:
            lines.extend(_generate_node(child, indent, invoke_resolver, out_arg_resolver))
    lines.append(f"{prefix}{var}.save({node.file_name!r})")
    return lines


# 知見121: `ui:ReplaceTextInDocument`/`ui:WordReplaceText`。`python-docx`
# には組み込みの検索置換が無いため、各段落の各run単体に対して文字列
# 置換する標準的なイディオム(python-docxコミュニティで広く使われる
# パターン)を使う——検索対象の文字列が複数のrun(書式の境界)に分割
# されている場合は置換されない、既知の限界(`ExcelApplicationScope`の
# ライブマクロ実行未対応と同種の構造的な制約として受け入れる)。
def _generate_word_replace_text_in_scope(
    node: WordReplaceTextNode, indent: int, scope_var: str
) -> list[str]:
    prefix = INDENT * indent
    if node.search is None or node.replace is None:
        return [f"{prefix}# TODO: Word Replace Text with missing Search/Replace"]
    todo: list[str] = []
    search = _render_value_or_todo(node.search, prefix, todo)
    replace = _render_value_or_todo(node.replace, prefix, todo)
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    inner2 = INDENT * (indent + 2)
    return [
        f"{prefix}for _p in {scope_var}.paragraphs:",
        f"{inner}for _r in _p.runs:",
        f"{inner2}if {VB_CSTR_HELPER_NAME}({search}) in _r.text:",
        f"{INDENT * (indent + 3)}_r.text = _r.text.replace("
        f"{VB_CSTR_HELPER_NAME}({search}), {VB_CSTR_HELPER_NAME}({replace}))",
    ]


def _generate_excel_write_cell_in_scope(
    node: ExcelWriteCellNode, indent: int, scope_var: str
) -> list[str]:
    """知見97: `scope_var`(囲む`ExcelApplicationScopeNode`が開いた
    `openpyxl.Workbook`変数)へのセル書き込み。`openpyxl`の
    `workbook[sheet_name][cell] = value`代入記法(`Worksheet.__setitem__`、
    インストール済みの実`openpyxl`で実際に動作確認済み)を使う。`Text`は
    他の文字列出力先(`Append Line`/`Set To Clipboard`/`MessageBox`、知見46)
    と同じ`_vb_cstr()`経由でVBの文字列化規則に合わせる。"""
    prefix = INDENT * indent
    if node.cell is None:
        return [f"{prefix}# TODO: Excel Write Cell with no Cell captured"]
    todo: list[str] = []
    cell = _render_value_or_todo(node.cell, prefix, todo)
    value = _render_value_or_todo(node.text, prefix, todo)
    if todo:
        return todo
    return [
        f"{prefix}{scope_var}[{node.sheet_name!r}][{cell}] = "
        f"{VB_CSTR_HELPER_NAME}({value})"
    ]


# 知見119: `ui:ExcelReadCell`(`ExcelWriteCellNode`と対になる読み取り側、
# `PacktPublishing/Robotic-Process-Automation-Projects`の実機XAMLで発見)。
def _generate_excel_read_cell_in_scope(
    node: ExcelReadCellNode, indent: int, scope_var: str
) -> list[str]:
    prefix = INDENT * indent
    if node.cell is None:
        return [f"{prefix}# TODO: Excel Read Cell with no Cell captured"]
    if node.result is None:
        return [f"{prefix}# TODO: Excel Read Cell with no output Result captured"]
    todo: list[str] = []
    cell = _render_value_or_todo(node.cell, prefix, todo)
    target = _render_value_or_todo(node.result, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}{target} = {scope_var}[{node.sheet_name!r}][{cell}].value"]


# 知見119: `ui:Comment`。純粋な注釈で実行時の挙動は無い——Pythonの`#`
# コメント行へそのまま変換する(複数行テキストの場合は各行を個別の
# コメント行にする、`#`無しの行が紛れてPythonのコードとして解釈される
# ことを避ける)。
def _generate_comment(node: CommentNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = node.text.splitlines() or [""]
    return [f"{prefix}# {line}" for line in lines]


# 知見151: 実機XAMLで確認済みの.NET TimeSpanリテラル書式
# (`"HH:MM:SS"`/`"HH:MM:SS.fffffff"`)のみを秒数に変換する——それ以外の
# 書式(日数プレフィックス等、未確認)は`None`を返し呼び出し側で`# TODO`
# へ倒す。
_TIMESPAN_LITERAL_RE = re.compile(r"^(\d+):(\d{2}):(\d{2}(?:\.\d+)?)$")


def _parse_timespan_literal_seconds(text: str) -> float | None:
    match = _TIMESPAN_LITERAL_RE.match(text.strip())
    if match is None:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


# 知見151: `ui:Delay`(UiPath独自の待機活動——GitHub code searchで
# 10000件超ヒットする最頻出活動の1つにも関わらず、これまで完全に未実装
# だった)。`Duration`属性は実機確認した全件で`[...]`角括弧の無い生の
# TimeSpanリテラルだった(`Click`の`DelayBefore`、知見106とは異なる
# 書式)——`Literal`の場合のみ秒数に変換して`time.sleep()`へ変換し、
# `VbExpr`(動的式)の場合は未確認のため`# TODO`へ倒す。
def _generate_delay(node: DelayNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_delay_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_delay_body(node: DelayNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.duration is None:
        return [f"{prefix}# TODO: Delay with no Duration captured"]
    if not isinstance(node.duration, Literal):
        return _todo_value(
            prefix,
            "Delay.Duration is a dynamic VB expression, not a confirmed-safe "
            "literal TimeSpan — refusing to guess the semantics",
        )
    seconds = _parse_timespan_literal_seconds(node.duration.value)
    if seconds is None:
        return [
            f"{prefix}# TODO: Delay Duration {node.duration.value!r} is not a "
            "confirmed TimeSpan literal format (HH:MM:SS[.fff])"
        ]
    return [f"{prefix}time.sleep({seconds!r})"]


# 知見147: `WriteLine`(.NET Workflow Foundation本体の標準活動、UiPath
# 独自ではない)。`Console.WriteLine`相当で、Pythonの`print()`と直接
# 対応する——`MessageBox`(知見79)と違い対話的なブロッキング・ユーザー
# の選択を伴わないため、でっち上げの懸念が無い単純な変換。
def _generate_write_line(node: WriteLineNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_write_line_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_write_line_body(node: WriteLineNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.text is None:
        return [f"{prefix}# TODO: Write Line with no Text captured"]
    todo: list[str] = []
    text = _render_value_or_todo(node.text, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}print({VB_CSTR_HELPER_NAME}({text}))"]


# 知見148: `Throw`(.NET Workflow Foundation本体の標準活動、知見147の
# `WriteLine`と同じくUiPath独自ではない)。`Exception`属性は実機で`New
# ClassName(arg)`構文(知見148で新規対応、`render.py`の`_NEW_OBJECT_
# CLASSES`)が使われていた——`_render_value_or_todo`(失敗時に例外無く
# `"None"`を返す)は使わない。`raise None`は構文的には有効だが実行時に
# `TypeError`になり、知見136・137で確立した「代入先が不明な文は全体を
# 倒す」という方針と同じ理由で、レンダリング失敗時は`raise`文自体を
# 生成せず`# TODO`へ倒す(`raise`しないことで本来即座に停止するはずの
# 制御フローが継続してしまう既知の限界だが、架空の例外をでっち上げる
# よりは安全)。
def _generate_throw(node: ThrowNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_throw_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_throw_body(node: ThrowNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.exception is None:
        return [f"{prefix}# TODO: Throw with no Exception captured"]
    try:
        exc = render_expr(node.exception)
    except NotImplementedError as e:
        return _todo_value(prefix, str(e))
    return [f"{prefix}raise {exc}"]


# 知見149: `Rethrow`(.NET Workflow Foundation本体の標準活動、知見148の
# `Throw`の対になる、属性を一切持たないリーフ活動)。`Catch`ブロック内で
# 現在捕捉中の例外を再発生させる——Pythonの引数無し`raise`文(`except`
# ブロック内で現在処理中の例外を再発生させる)が全く同じ意味論で直接
# 対応する。でっち上げの懸念が無い単純な変換。
def _generate_rethrow(node: RethrowNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    return _with_scope_child_display_name(node, [f"{prefix}raise"], prefix)


# 知見150: `TerminateWorkflow`(.NET Workflow Foundation本体の標準活動、
# `Throw`(知見148)・`Rethrow`(知見149)と対になる、`TryCatch`で捕捉
# されない即座のワークフロー全体停止活動)。Pythonの`SystemExit`(デフォ
# ルトでは`except Exception:`に捕捉されず伝播する)が最も近い対応物。
# `Reason`のみの場合だけ変換し、`Exception`属性も同時に指定されている
# 場合は両者がどう合成されるべきか実機未確認のため`# TODO`へ倒す
# (でっち上げるよりは安全)。
def _generate_terminate_workflow(
    node: TerminateWorkflowNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_terminate_workflow_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_terminate_workflow_body(
    node: TerminateWorkflowNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    if node.reason is None:
        return [f"{prefix}# TODO: TerminateWorkflow with no Reason captured"]
    if node.exception is not None:
        return [
            f"{prefix}# TODO: TerminateWorkflow with both Reason and Exception "
            "set — combined semantics not confirmed"
        ]
    todo: list[str] = []
    reason = _render_value_or_todo(node.reason, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}raise SystemExit({VB_CSTR_HELPER_NAME}({reason}))"]


# 知見119: `ui:LogMessage`。実機確認済みの`Level`は`"Info"`/`"Error"`のみ
# ——Python標準ライブラリ`logging`の対応メソッドへマッピングする。
_LOG_LEVEL_METHODS = {"Info": "info", "Error": "error"}


def _generate_log_message(node: LogMessageNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_log_message_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_log_message_body(node: LogMessageNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.message is None:
        return [f"{prefix}# TODO: Log Message with no Message captured"]
    method = _LOG_LEVEL_METHODS.get(node.level or "Info")
    if method is None:
        return [
            f"{prefix}# TODO: Log Message with unconfirmed Level "
            f"({node.level!r}) — only Info/Error are confirmed, refusing "
            "to guess"
        ]
    todo: list[str] = []
    message = _render_value_or_todo(node.message, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}logging.{method}({VB_CSTR_HELPER_NAME}({message}))"]


# 知見115: `ui:ExcelReadRange`/`ui:ExcelWriteRange`。実機確認できた
# `Range`(空文字列=シート全体)・`StartingCell`(`"A1"`のみ)の組み合わせ
# だけ実コード生成し、その他は`# TODO`へ倒す——`openpyxl`の`append()`は
# 既存内容の末尾に追記する挙動で、`StartingCell`が`"A1"`以外(既存シート
# の中間への書き込み)の場合に正確に再現する手段が未確認なため。
# `DataTable`は`ExecuteQuery`(知見114)と同じ`list[dict]`表現に揃える
# ——`AddHeaders`時は最初の行の辞書キーをヘッダー行として書き込む。
def _generate_excel_read_range_in_scope(
    node: ExcelReadRangeNode, indent: int, scope_var: str
) -> list[str]:
    prefix = INDENT * indent
    if node.data_table is None:
        return [f"{prefix}# TODO: Excel Read Range with no output DataTable captured"]
    if node.range is not None and not (
        isinstance(node.range, Literal) and node.range.value == ""
    ):
        return [
            f"{prefix}# TODO: Excel Read Range with non-empty/non-literal "
            f"Range ({node.range!r}) — only the whole-used-range default is "
            "confirmed, refusing to guess"
        ]
    if not node.sheet_name:
        return [f"{prefix}# TODO: Excel Read Range with no SheetName captured"]
    add_headers = node.add_headers if node.add_headers is not None else "True"
    if add_headers not in ("True", "False"):
        return [
            f"{prefix}# TODO: Excel Read Range with unrecognized AddHeaders "
            f"({node.add_headers!r}) — refusing to guess"
        ]
    todo: list[str] = []
    target = _render_value_or_todo(node.data_table, prefix, todo)
    if todo:
        return todo
    lines = [
        f"{prefix}_ws = {scope_var}[{node.sheet_name!r}]",
        f"{prefix}_rows = list(_ws.iter_rows(values_only=True))",
    ]
    if add_headers == "True":
        lines.append(
            f"{prefix}{target} = [dict(zip(_rows[0], _r)) for _r in _rows[1:]] "
            "if _rows else []"
        )
    else:
        lines.append(f"{prefix}{target} = [list(_r) for _r in _rows]")
    return lines


def _generate_excel_write_range_in_scope(
    node: ExcelWriteRangeNode, indent: int, scope_var: str
) -> list[str]:
    """知見115の修正(実機データではなく、既存コードを実際の非空シートに
    対して再検証して発見): 当初`openpyxl`の`Worksheet.append()`で実装
    していたが、`append()`は常にシート末尾に追記する挙動のため、対象
    シートに既存データがある場合に`StartingCell`の実際の位置を無視して
    末尾に追記してしまう——UiPathの`Write Range`は指定した開始セルへ
    上書きする(末尾追記ではない)ため、既存データがあるシートでは誤った
    結果になるバグだった。`Worksheet.cell(row=..., column=..., value=...)`
    による直接セル指定の書き込みに変更して修正——これにより`StartingCell`
    を`"A1"`に限定する必要も無くなり、任意の開始セル("C5"等)に対応できる
    ようになった(以前の制約を偶然副産物として解消)。"""
    prefix = INDENT * indent
    if node.data_table is None:
        return [f"{prefix}# TODO: Excel Write Range with no input DataTable captured"]
    if not node.sheet_name:
        return [f"{prefix}# TODO: Excel Write Range with no SheetName captured"]
    try:
        start_col_letter, start_row = coordinate_from_string(node.starting_cell or "A1")
        start_col = column_index_from_string(start_col_letter)
    except (ValueError, CellCoordinatesException):
        return [
            f"{prefix}# TODO: Excel Write Range with unparseable StartingCell "
            f"({node.starting_cell!r}) — refusing to guess"
        ]
    add_headers = node.add_headers if node.add_headers is not None else "False"
    if add_headers not in ("True", "False"):
        return [
            f"{prefix}# TODO: Excel Write Range with unrecognized AddHeaders "
            f"({node.add_headers!r}) — refusing to guess"
        ]
    todo: list[str] = []
    rows = _render_value_or_todo(node.data_table, prefix, todo)
    if todo:
        return todo
    lines = [
        f"{prefix}_ws = {scope_var}[{node.sheet_name!r}]",
        f"{prefix}_rows = {rows}",
        f"{prefix}if _rows:",
    ]
    inner = INDENT * (indent + 1)
    if add_headers == "True":
        lines.append(f"{inner}for _j, _h in enumerate(list(_rows[0].keys())):")
        lines.append(
            f"{INDENT * (indent + 2)}_ws.cell(row={start_row}, column={start_col} + _j, value=_h)"
        )
        lines.append(f"{inner}_row0 = {start_row + 1}")
    else:
        lines.append(f"{inner}_row0 = {start_row}")
    lines.append(f"{inner}for _i, _row in enumerate(_rows):")
    lines.append(f"{INDENT * (indent + 2)}for _j, _v in enumerate(_row.values()):")
    lines.append(
        f"{INDENT * (indent + 3)}_ws.cell(row=_row0 + _i, column={start_col} + _j, value=_v)"
    )
    return lines


# 知見117: `ui:ExcelAppendRange`。`AddHeaders`/`StartingCell`は無く
# (公式確認済み)、常にシート末尾への追記のみ——これは知見115追記の
# `ExcelWriteRange`修正で外した「`append()`ベースの常に末尾追記する」
# 挙動そのものに正確に対応する、別の活動。
def _generate_excel_append_range_in_scope(
    node: ExcelAppendRangeNode, indent: int, scope_var: str
) -> list[str]:
    prefix = INDENT * indent
    if node.data_table is None:
        return [f"{prefix}# TODO: Excel Append Range with no input DataTable captured"]
    if not node.sheet_name:
        return [f"{prefix}# TODO: Excel Append Range with no SheetName captured"]
    todo: list[str] = []
    rows = _render_value_or_todo(node.data_table, prefix, todo)
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    return [
        f"{prefix}_ws = {scope_var}[{node.sheet_name!r}]",
        f"{prefix}_rows = {rows}",
        f"{prefix}for _row in _rows:",
        f"{inner}_ws.append(list(_row.values()))",
    ]


# 知見102: Outlook `MailItem`の`Importance`/`Sensitivity`/`IsBodyHtml`/
# `IsDraft`/`Cc`/`Bcc`は、知見98では実機フィクスチャで確認できた唯一の
# 既定値構成のみに対応していたが、知見100で確立した「GitHub上の実機
# 保存済みXAMLを`gh api search/code`で直接検索する」手法で非既定値が
# 実在すると確認できたため対応を広げた(VM不使用)。`Importance="High"`
# (`d6wv28/RPA_Repo`の実例で確認、同じ要素内に`Cc`設定済み・
# `IsBodyHtml="True"`も実在することを確認)・`Sensitivity="Personal"`/
# `"Confidential"`・`IsDraft="True"`もいずれも実在。整数値(Microsoft
# Learn Outlook VBAリファレンス、知見98で確認済み)・`.HTMLBody`
# (`Body`ではなく)・`.Save()`(`Send()`ではなく)・`.CC`/`.BCC`
# (いずれもMailItemの標準プロパティ、Microsoft Learnで確認済み)へ
# マッピングする。
_OUTLOOK_IMPORTANCE_VALUES = {"Low": 0, "Normal": 1, "High": 2}
_OUTLOOK_SENSITIVITY_VALUES = {"Normal": 0, "Personal": 1, "Private": 2, "Confidential": 3}
_OUTLOOK_BOOL_VALUES = {"True": True, "False": False}


# 知見116: `ui:SendMail`(DisplayName「Send SMTP Mail Message」/「Send
# SMTP Email」)。実機確認できた唯一のpopulated実例(`cameronmcnz/
# uipath-tutorials`のGmail SMTP送信)は`EnableSSL="True"`・
# `SecureConnection="Auto"`・`Port="465"`という「暗黙SSL」の組み合わせ
# のみで、`smtplib.SMTP_SSL`に正確に対応する。この組み合わせ以外
# (平文/STARTTLS、`UseISConnection`、OAuth、Forward/Reply、`From`/
# `Name`での送信者表示名カスタマイズ)は実機確認が無いため`# TODO`へ倒す。
def _generate_send_mail(node: SendMailNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_send_mail_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_send_mail_body(node: SendMailNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.to is None or node.subject is None or node.body is None:
        return [f"{prefix}# TODO: Send Mail with missing To/Subject/Body"]
    if node.has_populated_files:
        return [
            f"{prefix}# TODO: Send Mail with populated Files — attachment "
            "handling not confirmed via real capture, refusing to guess"
        ]
    if node.mail_message is not None:
        return [
            f"{prefix}# TODO: Send Mail with MailMessage set (Forward/Reply "
            "mode) — not confirmed via real capture, refusing to guess"
        ]
    if node.use_oauth not in (None, "False"):
        return [
            f"{prefix}# TODO: Send Mail with UseOAuth set — OAuth2 flow not "
            "confirmed via real capture, refusing to guess"
        ]
    if node.enable_ssl != "True":
        return [
            f"{prefix}# TODO: Send Mail with EnableSSL "
            f"{node.enable_ssl!r} — only EnableSSL=True (implicit SSL, "
            "smtplib.SMTP_SSL) is confirmed via real capture, refusing to "
            "guess plain/STARTTLS connections"
        ]
    if node.secure_connection not in (None, "Auto"):
        return [
            f"{prefix}# TODO: Send Mail with SecureConnection "
            f"{node.secure_connection!r} — UiPath docs don't enumerate this "
            "property's values, only 'Auto' is confirmed via real capture, "
            "refusing to guess"
        ]
    if node.from_ is not None or node.name is not None:
        return [
            f"{prefix}# TODO: Send Mail with From/Name set — sender header "
            "customization not confirmed via real capture, refusing to guess"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: Send Mail with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    if node.is_body_html not in (None, "True", "False"):
        return [
            f"{prefix}# TODO: Send Mail with unrecognized IsBodyHtml "
            f"({node.is_body_html!r}) — refusing to guess"
        ]
    if node.server is None or node.email is None or node.password is None or node.port is None:
        return [f"{prefix}# TODO: Send Mail with missing Server/Email/Password/Port"]
    todo: list[str] = []
    to = _render_value_or_todo(node.to, prefix, todo)
    subject = _render_value_or_todo(node.subject, prefix, todo)
    body = _render_value_or_todo(node.body, prefix, todo)
    email = _render_value_or_todo(node.email, prefix, todo)
    password = _render_value_or_todo(node.password, prefix, todo)
    server = _render_value_or_todo(node.server, prefix, todo)
    port = _render_value_or_todo(node.port, prefix, todo)
    cc = _render_value_or_todo(node.cc, prefix, todo) if node.cc is not None else None
    bcc = _render_value_or_todo(node.bcc, prefix, todo) if node.bcc is not None else None
    reply_to = (
        _render_value_or_todo(node.reply_to, prefix, todo) if node.reply_to is not None else None
    )
    timeout_ms = (
        _render_value_or_todo(node.timeout_ms, prefix, todo)
        if node.timeout_ms is not None
        else None
    )
    if todo:
        return todo
    is_html = node.is_body_html == "True"
    lines = [
        f'{prefix}_msg = email.mime.text.MIMEText({VB_CSTR_HELPER_NAME}({body}), '
        f'{"html" if is_html else "plain"!r})',
        f"{prefix}_msg[\"Subject\"] = {VB_CSTR_HELPER_NAME}({subject})",
        f"{prefix}_msg[\"From\"] = {VB_CSTR_HELPER_NAME}({email})",
        f"{prefix}_msg[\"To\"] = {VB_CSTR_HELPER_NAME}({to})",
    ]
    if cc is not None:
        lines.append(f"{prefix}_msg[\"Cc\"] = {VB_CSTR_HELPER_NAME}({cc})")
    if bcc is not None:
        lines.append(f"{prefix}_msg[\"Bcc\"] = {VB_CSTR_HELPER_NAME}({bcc})")
    if reply_to is not None:
        lines.append(f"{prefix}_msg[\"Reply-To\"] = {VB_CSTR_HELPER_NAME}({reply_to})")
    timeout_kwarg = (
        f", timeout=({VB_NUM_HELPER_NAME}({timeout_ms}) / 1000.0)" if timeout_ms is not None else ""
    )
    lines.append(
        f"{prefix}_smtp = smtplib.SMTP_SSL({VB_CSTR_HELPER_NAME}({server}), "
        f"int({VB_NUM_HELPER_NAME}({port})){timeout_kwarg})"
    )
    lines.append(f"{prefix}_smtp.login({VB_CSTR_HELPER_NAME}({email}), {VB_CSTR_HELPER_NAME}({password}))")
    lines.append(f"{prefix}_smtp.send_message(_msg)")
    lines.append(f"{prefix}_smtp.quit()")
    return lines


def _generate_send_outlook_mail(node: SendOutlookMailNode, indent: int) -> list[str]:
    """知見98・102: `SendOutlookMailNode`は知見24以来常に`_generate_
    unresolved_activity`へ倒れていたが、`win32com.client`経由で実際の
    Outlookへの送信コードを生成する——ユーザー決定(2026-11-05)により
    `win32com`(実際のOutlookクライアント経由、UiPathの実行時挙動に近い)
    を選択。`CreateItem(0)`(`olMailItem`、Microsoft Learn
    `Outlook.OlItemType`で確認済み)でメールアイテムを作成する。

    `Files`に添付ファイルがある場合のみ、添付の追加方法の実直列化形が
    実機未確認のため`_generate_unresolved_activity`の`# TODO`へ倒す
    (知見75・92〜95と同じ「捕捉済みデータを隠さない」フォールバック)。
    """
    prefix = INDENT * indent
    importance = node.importance if node.importance is not None else "Normal"
    sensitivity = node.sensitivity if node.sensitivity is not None else "Normal"
    is_body_html = node.is_body_html if node.is_body_html is not None else "False"
    is_draft = node.is_draft if node.is_draft is not None else "False"
    if (
        node.has_populated_files
        or importance not in _OUTLOOK_IMPORTANCE_VALUES
        or sensitivity not in _OUTLOOK_SENSITIVITY_VALUES
        or is_body_html not in _OUTLOOK_BOOL_VALUES
        or is_draft not in _OUTLOOK_BOOL_VALUES
    ):
        return _generate_unresolved_activity(node, indent)
    todo: list[str] = []
    to = _render_value_or_todo(node.to, prefix, todo)
    subject = _render_value_or_todo(node.subject, prefix, todo)
    body = _render_value_or_todo(node.body, prefix, todo)
    cc = _render_value_or_todo(node.cc, prefix, todo) if node.cc is not None else None
    bcc = _render_value_or_todo(node.bcc, prefix, todo) if node.bcc is not None else None
    if todo:
        return todo
    body_prop = "HTMLBody" if _OUTLOOK_BOOL_VALUES[is_body_html] else "Body"
    lines = [
        f"{prefix}_outlook = win32com.client.Dispatch('Outlook.Application')",
        f"{prefix}_mail = _outlook.CreateItem(0)",
        f"{prefix}_mail.To = {VB_CSTR_HELPER_NAME}({to})",
        f"{prefix}_mail.Subject = {VB_CSTR_HELPER_NAME}({subject})",
        f"{prefix}_mail.{body_prop} = {VB_CSTR_HELPER_NAME}({body})",
    ]
    if cc is not None:
        lines.append(f"{prefix}_mail.CC = {VB_CSTR_HELPER_NAME}({cc})")
    if bcc is not None:
        lines.append(f"{prefix}_mail.BCC = {VB_CSTR_HELPER_NAME}({bcc})")
    lines.append(f"{prefix}_mail.Importance = {_OUTLOOK_IMPORTANCE_VALUES[importance]}")
    lines.append(f"{prefix}_mail.Sensitivity = {_OUTLOOK_SENSITIVITY_VALUES[sensitivity]}")
    send_method = "Save" if _OUTLOOK_BOOL_VALUES[is_draft] else "Send"
    lines.append(f"{prefix}_mail.{send_method}()")
    return lines


# 知見120: `ui:GetOutlookMailMessages`(`SendOutlookMailNode`と対になる
# 受信側)。`MailFolder="Inbox"`は`GetNamespace("MAPI").GetDefaultFolder
# (6)`(`olFolderInbox`、Microsoft Learn`OlDefaultFolders`列挙で確認済み、
# `SendOutlookMail`の`CreateItem(0)`と同じ確認手法)へマッピング。
# `Filter`はOutlookのDASL/Jetフィルタ構文そのものをUiPathが変換無しで
# そのまま渡していると見受けられるため、`Items.Restrict()`へそのまま
# 渡す(でっち上げた変換は行わない、生の文字列をそのまま委譲)。
# `GetAttachements`/`MarkAsRead`/`OnlyUnreadMessages`は実機確認済みの
# 既定値(`"False"`)以外、`Account`(別メールボックス)・`MailFolder`が
# `"Inbox"`以外は未確認のため`# TODO`へ倒す——`SendOutlookMail`と同じ
# 「確認済みの既定値のみ対応」方針。
_OUTLOOK_FALSE_ONLY_VALUES = (None, "False")


def _generate_get_outlook_mail_messages(
    node: GetOutlookMailMessagesNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_get_outlook_mail_messages_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_get_outlook_mail_messages_body(
    node: GetOutlookMailMessagesNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    if node.messages is None:
        return [f"{prefix}# TODO: Get Outlook Mail Messages with no output Messages captured"]
    if node.account is not None:
        return [
            f"{prefix}# TODO: Get Outlook Mail Messages with Account set "
            f"({_describe_expr_for_comment(node.account)}) — accessing a "
            "non-default mailbox is not confirmed, refusing to guess"
        ]
    if node.mail_folder not in (None, "Inbox"):
        return [
            f"{prefix}# TODO: Get Outlook Mail Messages with MailFolder "
            f"{node.mail_folder!r} — only 'Inbox' is confirmed, refusing "
            "to guess"
        ]
    if node.get_attachments not in _OUTLOOK_FALSE_ONLY_VALUES:
        return [
            f"{prefix}# TODO: Get Outlook Mail Messages with GetAttachements set "
            f"({node.get_attachments!r}) — attachment handling not confirmed, "
            "refusing to guess"
        ]
    if node.mark_as_read not in _OUTLOOK_FALSE_ONLY_VALUES:
        return [
            f"{prefix}# TODO: Get Outlook Mail Messages with MarkAsRead set "
            f"({node.mark_as_read!r}) — refusing to guess"
        ]
    if node.only_unread_messages not in _OUTLOOK_FALSE_ONLY_VALUES:
        return [
            f"{prefix}# TODO: Get Outlook Mail Messages with OnlyUnreadMessages "
            f"set ({node.only_unread_messages!r}) — refusing to guess"
        ]
    if node.timeout_ms is not None:
        return [
            f"{prefix}# TODO: Get Outlook Mail Messages with TimeoutMS set "
            f"({_describe_expr_for_comment(node.timeout_ms)}) — refusing to guess"
        ]
    todo: list[str] = []
    target = _render_value_or_todo(node.messages, prefix, todo)
    filter_expr = (
        _render_value_or_todo(node.filter, prefix, todo) if node.filter is not None else None
    )
    top = _render_value_or_todo(node.top, prefix, todo) if node.top is not None else None
    if todo:
        return todo
    lines = [
        f"{prefix}_outlook = win32com.client.Dispatch('Outlook.Application')",
        f"{prefix}_items = _outlook.GetNamespace('MAPI').GetDefaultFolder(6).Items",
    ]
    if filter_expr is not None:
        lines.append(f"{prefix}_items = _items.Restrict({VB_CSTR_HELPER_NAME}({filter_expr}))")
    if top is not None:
        lines.append(f"{prefix}{target} = list(_items)[:int({VB_NUM_HELPER_NAME}({top}))]")
    else:
        lines.append(f"{prefix}{target} = list(_items)")
    return lines


def _generate_http_client(node: HttpClientNode, indent: int) -> list[str]:
    """知見96: `HttpClientNode`は知見29以来常に`_generate_unresolved_
    activity`へ倒れていたが、`requests`ライブラリへの実変換を行う。

    `TimeoutMS`(UiPath公式ドキュメント docs.uipath.com/activities/other/
    latest/developer/http-request、既定値6000ms——実機フィクスチャの値と
    一致)はミリ秒からrequestsの`timeout`引数(秒)へ単位変換するだけで、
    複雑な解釈は挟まない。

    知見104: `Body`(`requests`の`data=`引数へ)・`Headers`(`requests`の
    `headers=`引数へ、辞書リテラル)も実コード生成する——`gh api
    search/code`でGitHub上の実機保存済みXAMLから、`Body`が実際に設定
    される実例(POSTリクエスト)と`Headers`のpopulated時の実直列化形を
    確認した(VM不使用)。`BodyFormat`/`AcceptFormat`がHTTPヘッダーへどう
    反映されるか(例: `Content-Type`の自動設定)はコミュニティ情報が
    相互に矛盾しており未確認のため、でっち上げた自動注入はしない——
    `Headers`に明示的に`Content-Type`が無ければ`requests`自身の既定動作
    (未設定)に委ねる。

    `Cookies`/`Parameters`/`UrlSegments`/`Attachments`のいずれかに1件
    以上のエントリがある場合は、populated時の意味論(`Parameters`がクエリ
    文字列かフォームデータか等)が実機未確認のため、でっち上げず
    `_generate_unresolved_activity`の`# TODO`(知見75・92)へ委ねる——
    `Method`/`EndPoint`は確認済みのため、そちらにも引き続き同じ詳細情報
    が出る。
    """
    prefix = INDENT * indent
    if node.has_populated_collections:
        return _generate_unresolved_activity(node, indent)
    todo: list[str] = []
    endpoint = _render_value_or_todo(node.endpoint, prefix, todo)
    body_arg = _render_value_or_todo(node.body, prefix, todo) if node.body is not None else None
    header_items = [
        f"{key!r}: {VB_CSTR_HELPER_NAME}({_render_value_or_todo(expr, prefix, todo)})"
        for key, expr in node.headers.items()
    ]
    if todo:
        return todo
    kwargs = [repr(node.method), endpoint]
    if node.timeout_ms:
        try:
            kwargs.append(f"timeout={float(node.timeout_ms) / 1000.0!r}")
        except ValueError:
            pass
    if body_arg is not None:
        kwargs.append(f"data={VB_CSTR_HELPER_NAME}({body_arg})")
    if header_items:
        kwargs.append(f"headers={{{', '.join(header_items)}}}")
    return [f"{prefix}requests.request({', '.join(kwargs)})"]


def _describe_expr_for_comment(expr: Expr) -> str:
    """`# TODO`コメントに埋め込むための人間向け簡易説明(知見75)。
    `render.py`の`render_expr()`のような実行可能Pythonコードへの変換は
    試みない——既に`# TODO`に倒れている活動の説明文字列生成でさらに
    別の`NotImplementedError`/ネストした`# TODO`を誘発しないよう、
    常に例外を出さない`repr()`ベースの素朴な表現に留める。"""
    if expr is None:
        return "(not set)"
    if isinstance(expr, Literal):
        return repr(expr.value)
    if isinstance(expr, VbExpr):
        # 知見141: `expr.text`はVB.NETの丸括弧内改行(行継続)により複数行
        # になりうる(`_todo_value`と同じ根本原因)——`repr()`を経由する
        # 他の分岐と違い生のテキストを直接埋め込むため、同じ単一行化
        # 処理が必要。
        single_line = expr.text.replace("\n", "\\n")
        return f"[{single_line}]"
    return repr(expr)


def _generate_unresolved_activity(node, indent: int) -> list[str]:
    """design/uipath_transpiler_roadmap.md Phase 4で未解決と明記した項目
    (インラインコード・ライブExcel/Outlook連携・`HttpClient`のHeaders等
    プロパティ要素未パース)——架空の変換をでっち上げず`# TODO`に倒す。
    `Invoke Workflow File`自体は`_generate_invoke_workflow_file`が担当する
    (`generate_project_python()`経由であれば実関数呼び出しへ解決される)。

    知見84/88: `ExcelApplicationScopeNode`はかつて子アクティビティ
    (`node.body`)を持つ唯一の未対応アクティビティとしてここで特別扱い
    していたが、知見97で`openpyxl`への実コード生成に対応し、専用の
    `_generate_excel_application_scope`へ移った(この関数には到達しない)。

    知見75: 捕捉済みの主要フィールドをコメントへ追記する——`# TODO`へ
    倒れた後に人間が手動でポートする際、生成コードだけを見て元のXAMLを
    探しに戻らなくて済むようにする(どのメールを送る予定だったか・どの
    インラインコードが埋め込まれていたか等)。でっち上げた実装では
    なく、既に捕捉済みのデータをそのまま見やすくするだけ。

    知見83: `InvokeCodeNode.arguments`(知見23、`Code`内で参照される
    引数名→外側の式の対応表)も同じ理由で追記する——`Code`テキスト自体が
    必ずしも`arguments`のキー名をそのまま参照するわけではない(知見17・
    23の実機確認時、`Code="content=content.ToUpper()"`に対し`Arguments`は
    `myArg`という別名で`content`を束縛していた、実際の対応関係は未確認の
    まま)ため、でっち上げた対応付けの説明はせず、捕捉した生データ
    (`{引数名: 式}`)をそのまま表示するに留める。"""
    prefix = INDENT * indent
    detail = ""
    if isinstance(node, InvokeCodeNode):
        if node.arguments:
            args_desc = ", ".join(
                f"{k}={_describe_expr_for_comment(v)}" for k, v in node.arguments.items()
            )
            detail = f" (Code={node.code!r}, Arguments={{{args_desc}}})"
        else:
            detail = f" (Code={node.code!r})"
    elif isinstance(node, ExcelWriteCellNode):
        # 知見93: `node.text`(書き込む値そのもの)も知見75で`Cell`/
        # `SheetName`だけを追記した際に見落としていた捕捉済みフィールド
        # ——知見92と同じ「捕捉済みデータの未活用」の追加分。知見119で
        # `node.cell`が`str`から`Expr`へ昇格したため`_describe_expr_for_
        # comment`経由で表示する。
        detail = (
            f" (Cell={_describe_expr_for_comment(node.cell)}, "
            f"SheetName={node.sheet_name!r}, "
            f"Text={_describe_expr_for_comment(node.text)})"
        )
    elif isinstance(node, ExcelReadCellNode):
        detail = (
            f" (Cell={_describe_expr_for_comment(node.cell)}, "
            f"SheetName={node.sheet_name!r}, "
            f"Result={_describe_expr_for_comment(node.result)})"
        )
    elif isinstance(node, SendOutlookMailNode):
        # 知見93: `node.body`(メール本文そのもの)も知見75で`To`/`Subject`
        # だけを追記した際に見落としていた捕捉済みフィールド。
        # 知見98: `Cc`/`Bcc`/`Importance`等も専用フィールドへ昇格した
        # ため、このTODOフォールバックに分岐した理由が分かるよう表示する。
        extra = {k: v for k, v in sorted(node.extra_attrs.items()) if k != "DisplayName"}
        detail = (
            f" (To={_describe_expr_for_comment(node.to)}, "
            f"Subject={_describe_expr_for_comment(node.subject)}, "
            f"Body={_describe_expr_for_comment(node.body)}, "
            f"Cc={_describe_expr_for_comment(node.cc)}, "
            f"Bcc={_describe_expr_for_comment(node.bcc)}, "
            f"Importance={node.importance!r}, Sensitivity={node.sensitivity!r}, "
            f"IsBodyHtml={node.is_body_html!r}, IsDraft={node.is_draft!r}"
            f"{f', ExtraAttrs={extra!r}' if extra else ''})"
        )
    elif isinstance(node, HttpClientNode):
        # 知見92: `node.extra_attrs`(`xaml_tree._parse_http_client`が
        # `EndPoint`/`Method`以外の全属性を既に捕捉している——実機
        # フィクスチャでは`BodyFormat`/`AcceptFormat`/`TimeoutMS`等)も
        # これまで一度もTODOコメントへ出ていなかった、同じ未活用パターン。
        # 知見96: `Body`も`EndPoint`/`Method`と同じ専用フィールドへ昇格した
        # ため、このTODOフォールバックに分岐した理由(Body設定済み、または
        # Headers等のコレクションが空でない)が分かるよう表示する。
        extra = {k: v for k, v in sorted(node.extra_attrs.items()) if k != "DisplayName"}
        detail = (
            f" (EndPoint={_describe_expr_for_comment(node.endpoint)}, "
            f"Method={node.method!r}, Body={_describe_expr_for_comment(node.body)}"
            f"{f', ExtraAttrs={extra!r}' if extra else ''})"
        )
    return [f"{prefix}# TODO: unsupported in v1 codegen: {type(node).__name__}{detail}"]


def _generate_unknown(node: UnknownActivityNode, indent: int) -> list[str]:
    """知見92: `node.attrs`(`xaml_tree.parse_activity`が`dict(elem.attrib)`で
    常に全属性を捕捉している、知見75/79/80/83と同じ「捕捉済みデータの
    未活用」パターン)が、これまで一度もTODOコメントへ出ていなかった——
    Libraryアクティビティ呼び出し(例: `<p:NewActivity in_greeting="hello"
    .../>`)の引数のような、人間が手動移植する際に最も必要な情報が
    サイレントに失われていた。`DisplayName`は`display_name`で既に別途
    表示済みのため重複を避けて除外する(それ以外はでっち上げた取捨選択を
    避け、捕捉済みの生データをそのまま表示する)。"""
    prefix = INDENT * indent
    display = f" ({node.display_name})" if node.display_name else ""
    extra_attrs = {k: v for k, v in sorted(node.attrs.items()) if k != "DisplayName"}
    detail = f" attrs={extra_attrs!r}" if extra_attrs else ""
    return [f"{prefix}# TODO: unknown activity{display}: {node.tag}{detail}"]


# --- 複数ファイル結線(generate_project_python) -----------------------------

# 子ノードリストを持つ複合ノード種別 → それらのリストの一覧。
# `Invoke Workflow File`参照の発見(`_iter_invoke_nodes`)専用の走査であり、
# codegen本体の`_generate_node`ディスパッチとは別の関心事(静的な呼び出し
# グラフ解析 vs コード生成)のため意図的に分離している。
#
# 知見88: `ExcelApplicationScopeNode`の分岐が長らく欠けていた——知見84
# (スコープの子アクティビティを実際に再帰生成するよう修正)より前は、
# スコープの子が丸ごと`# TODO`に潰されていたため「子の中の`Invoke
# Workflow File`参照」自体が意味を持たず、この欠落は無害だった。知見84で
# 子アクティビティが実際に生成されるようになった結果、スコープ内に
# ネストした`Invoke Workflow File`の参照先ファイルが
# `_discover_workflow_files`(複数ファイルのBFS発見)に一切見つけて
# もらえず、実在するファイルでも常に`# TODO: unresolved Invoke Workflow
# File`に倒れるという、知見84が新たに意味を持たせてしまった退行を発見・
# 修正した(実際に`generate_project_python()`を実行して再現を確認)。
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
    if isinstance(node, (ExcelApplicationScopeNode, WordApplicationScopeNode)):
        return [node.body]
    if isinstance(node, (AttachWindowNode, OpenApplicationNode, OpenBrowserNode)):
        return [node.body]
    return []


def _iter_invoke_nodes(nodes: list[Node]):
    """`nodes`配下(任意の深さにネストした分岐・ループ・try/catch内含む)の
    `InvokeWorkflowFileNode`を全て列挙する。"""
    for node in nodes:
        if isinstance(node, InvokeWorkflowFileNode):
            yield node
        for child_list in _child_node_lists(node):
            yield from _iter_invoke_nodes(child_list)


def _iter_invoke_nodes_in_flow(flow_node, visited: set[int]):
    """知見100: `_iter_invoke_nodes`のFlowchart版——`FlowNode`のグラフ
    (循環しうる、`id()`ベースの`visited`集合で1回しか処理しない)を辿り、
    各`FlowStepNode.body`内の`InvokeWorkflowFileNode`を列挙する。"""
    if flow_node is None or id(flow_node) in visited:
        return
    visited.add(id(flow_node))
    if isinstance(flow_node, FlowStepNode):
        yield from _iter_invoke_nodes(flow_node.body)
        yield from _iter_invoke_nodes_in_flow(flow_node.next, visited)
    elif isinstance(flow_node, FlowDecisionNode):
        yield from _iter_invoke_nodes_in_flow(flow_node.true_branch, visited)
        yield from _iter_invoke_nodes_in_flow(flow_node.false_branch, visited)
    elif isinstance(flow_node, FlowSwitchNode):
        for arm in flow_node.arms:
            yield from _iter_invoke_nodes_in_flow(arm.node, visited)


def _iter_invoke_nodes_for_root(root):
    """`WorkflowFile.root`(`SequenceNode`または`FlowchartNode`、知見100)
    いずれでも`InvokeWorkflowFileNode`を列挙できるようにする入口。"""
    if isinstance(root, FlowchartNode):
        yield from _iter_invoke_nodes_in_flow(root.start, set())
    else:
        yield from _iter_invoke_nodes(root.body)


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
    for inv in _iter_invoke_nodes_for_root(wf.root):
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
    for inv in _iter_invoke_nodes_for_root(wf.root):
        target = (path.parent / inv.workflow_file).resolve()
        if target in func_names:
            resolver[inv.workflow_file] = func_names[target]
    return resolver


def _build_out_arg_resolver(
    path: Path,
    wf: WorkflowFile,
    func_names: dict[Path, str],
    cache: dict[Path, WorkflowFile],
) -> dict[str, frozenset[str]]:
    """知見86: `_build_invoke_resolver`と同じキー(`workflow_file`文字列)で、
    その呼び出し先(`cache[target]`、既に発見済みのため再パース不要)が
    持つOut/InOutArgument方向の引数名集合を返す——`_generate_invoke_
    workflow_file`が呼び出し元の呼び出し文自体にも警告を出せるようにする。
    """
    resolver: dict[str, frozenset[str]] = {}
    for inv in _iter_invoke_nodes_for_root(wf.root):
        target = (path.parent / inv.workflow_file).resolve()
        if target in func_names:
            resolver[inv.workflow_file] = _collect_out_arg_names(cache[target].arguments)
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
        out_arg_resolver = _build_out_arg_resolver(p, wf, func_names, cache)
        parts.append(
            generate_python(
                wf,
                invoke_resolver=resolver,
                func_name=func_names[p],
                out_arg_resolver=out_arg_resolver,
            ).rstrip("\n")
        )
    return "\n\n\n".join(parts) + "\n"


def generate_project_from_json(project_dir: str | Path) -> str:
    """`project.json`からエントリポイント(`"main"`フィールド、知見27)を
    読み取り、`generate_project_python()`を呼ぶ便利関数。

    v1スコープ(design/uipath_transpiler_roadmap.md Phase 1)はProcess
    プロジェクトのみのため、`designOptions.outputType`が`"Process"`以外
    (例: `"Library"`、知見26の`ActivityBuilder`形は`uipath_dsl`が未対応)
    の場合は`ValueError`で明示的に拒否する——`parse_workflow_file`が
    State Machineルート(知見100以降、Flowchartは対応済み)を拒否するのと
    同じ、スコープ外を黙って誤変換しない方針。
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
