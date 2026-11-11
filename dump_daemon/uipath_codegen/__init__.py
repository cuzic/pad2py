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

import dataclasses
import json
import re
from pathlib import Path

from openpyxl.utils import column_index_from_string
from openpyxl.utils.cell import coordinate_from_string
from openpyxl.utils.exceptions import CellCoordinatesException

from ..uipath_dsl.types import (
    ActivateNode,
    AddDataColumnNode,
    AddDataRowNode,
    AppendLineNode,
    AssignNode,
    AttachWindowNode,
    BreakNode,
    ContinueNode,
    ReturnNode,
    IfElseIfBlockNode,
    IfElseIfV2Node,
    AddLogFieldsNode,
    RemoveLogFieldsNode,
    DeserializeJsonNode,
    GoBackNode,
    NavigateToNode,
    GetFromClipboardNode,
    DeserializeJsonArrayNode,
    CopyFolderXNode,
    MoveFolderXNode,
    StartProcessNode,
    GetSecureCredentialNode,
    AddCredentialNode,
    RequestCredentialNode,
    SplitTextNode,
    CombineTextNode,
    GetIMAPMailMessagesNode,
    SaveMailAttachmentsNode,
    SelectFolderNode,
    GetUsernamePasswordXNode,
    BuildDataTableNode,
    CheckNode,
    ClearDataTableNode,
    ClickNode,
    CloseApplicationNode,
    CloseTabNode,
    CloseWindowNode,
    CommentNode,
    CommentOutNode,
    CopyFileNode,
    CreateFileNode,
    DatabaseConnectNode,
    DatabaseDisconnectNode,
    DelayNode,
    DeleteFileNode,
    DeleteFolderNode,
    DoWhileNode,
    Expr,
    ExcelApplicationScopeNode,
    ExcelAppendRangeNode,
    ReadRangeNode,
    WriteRangeNode,
    ReadCellNode,
    WriteCellNode,
    ExcelReadCellNode,
    ExcelReadRangeNode,
    ExcelWriteCellNode,
    ExcelWriteRangeNode,
    ExecuteNonQueryNode,
    InsertDataTableNode,
    BulkInsertNode,
    DatabaseTransactionNode,
    ExtractTextNode,
    GetLastDownloadedFileNode,
    CheckTrueNode,
    CheckFalseNode,
    CreateDirectoryNode,
    MergeDataTableNode,
    FormatValueNode,
    ExecuteQueryNode,
    ExtractPdfPageRangeNode,
    FlowchartNode,
    FlowDecisionNode,
    FlowStepNode,
    FlowSwitchNode,
    ForEachFileNode,
    ForEachFolderNode,
    ForEachNode,
    RepeatNumberOfTimesXNode,
    GenerateDataTableNode,
    GetAttributeNode,
    GetOcrTextNode,
    GetOutlookMailMessagesNode,
    MarkMailAsReadXNode,
    DeleteMailXNode,
    MoveMailXNode,
    GetPasswordNode,
    GetPdfPageCountNode,
    GetRowItemNode,
    UpdateRowItemNode,
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
    GetProcessesNode,
    KillProcessNode,
    Literal,
    LoadImageNode,
    LookupDataTableNode,
    SortDataTableNode,
    FilterDataTableNode,
    JoinDataTablesNode,
    RemoveDuplicateRowsNode,
    ExportPdfPageAsImageNode,
    ExtractImagesFromPdfNode,
    LogMessageNode,
    ManagePdfPasswordNode,
    MessageBoxNode,
    MoveFileNode,
    MultipleAssignNode,
    Node,
    OpenApplicationNode,
    OpenBrowserNode,
    OutputDataTableNode,
    ParallelNode,
    PathExistsNode,
    FileExistsXNode,
    FolderExistsXNode,
    ReadCsvFileNode,
    ReadPdfTextNode,
    ReadTextFileNode,
    WriteTextFileNode,
    ExtractFilesNode,
    CompressFilesNode,
    IsMatchNode,
    ReplaceNode,
    MatchesNode,
    TextToLeftRightNode,
    GetEnvironmentVariableNode,
    SetEnvironmentVariableNode,
    GetEnvironmentFolderNode,
    FindAndReplaceTextModificationNode,
    TrimTextModificationNode,
    ToUpperLowerTextModificationNode,
    ModifyTextNode,
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
    SelectMultipleItemsNode,
    SendHotkeyNode,
    SendMailNode,
    SendOutlookMailNode,
    SequenceNode,
    SetToClipboardNode,
    SwitchNode,
    TakeScreenshotNode,
    TerminateWorkflowNode,
    ThrowNode,
    TryCatchNode,
    TypeIntoNode,
    UiElementExistsNode,
    WaitUiElementAppearNode,
    UnknownActivityNode,
    VariableDecl,
    VbExpr,
    WhileNode,
    WindowStateNode,
    WordApplicationScopeNode,
    WordReplaceTextNode,
    WordAppendTextNode,
    WordSaveAsNode,
    WordReadTextNode,
    WordAddImageNode,
    WordInsertDataTableNode,
    WordReplacePictureNode,
    WorkflowFile,
    WriteCsvFileNode,
    DeserializeXmlNode,
    ExecuteXPathNode,
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
    ScopeInfo,
    get_active_scope,
    render_expr,
    use_scope,
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


def _walk_scope_sources(obj, visited: set[int], on_node) -> None:
    """`workflow`木全体を再帰的に歩き、`VariableDecl`/`ForEachNode`/
    `BuildDataTableNode`のインスタンスに遭遇するたびに`on_node`を呼ぶ
    (知見117・126・130が記録した「スコープ情報が式レンダリングに必要」
    という3件の実需要に共通する、名前解決の一次情報源)。`Node`は
    実際には巨大な`Union`型エイリアス(実クラスではない)で`isinstance`
    の対象にできないため、個々のケースをハンドラ側で判定する代わりに
    「任意のdataclassのフィールドを再帰的に辿る」という汎用的な走査に
    した——`SwitchArm`/`CatchArm`等のNode本体ではない補助dataclassの
    内部(`.body`)もこれで自動的に拾える。`Flowchart`はグラフ構造
    (`FlowNode.next`等)でループを持ちうるため、`id()`に基づく`visited`
    集合で無限再帰を防ぐ。"""
    if obj is None or isinstance(obj, (str, int, float, bool, bytes)):
        return
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        if id(obj) in visited:
            return
        visited.add(id(obj))
        on_node(obj)
        for f in dataclasses.fields(obj):
            _walk_scope_sources(getattr(obj, f.name), visited, on_node)
    elif isinstance(obj, (list, tuple, frozenset, set)):
        for item in obj:
            _walk_scope_sources(item, visited, on_node)
    elif isinstance(obj, dict):
        for value in obj.values():
            _walk_scope_sources(value, visited, on_node)


def _build_scope_info(workflow: WorkflowFile) -> ScopeInfo:
    """知見130(識別子の大文字小文字正規化、最優先の設計課題として記録)・
    知見126(`row(...)`添字のDataRow型追跡)・知見117(`AddDataRow`の
    クロスノードDataTableスキーマ解決)という3件の「スコープ情報が
    式レンダリングに必要」という実需要に対応する、ワークフロー単位で
    一度だけ構築するスコープ情報。`canonical_names`は今回の`generate_
    python()`から実際に使われる(`render.use_scope()`経由)が、
    `data_row_vars`/`data_table_columns`はまだ消費側が無く、将来の
    拡張に備えてフィールドだけ用意してある。"""
    canonical_names: dict[str, str] = {}

    def register_name(name: str) -> None:
        key = name.lower()
        if key not in canonical_names:
            canonical_names[key] = name

    for arg_name in workflow.arguments:
        register_name(arg_name)
    for decl in workflow.variables:
        register_name(decl.name)

    data_row_vars: set[str] = set()
    data_table_columns: dict[str, list[str] | None] = {}
    has_log_fields = False
    json_object_vars: set[str] = set()

    def on_node(obj) -> None:
        nonlocal has_log_fields
        if isinstance(obj, VariableDecl):
            register_name(obj.name)
        elif isinstance(obj, ForEachNode):
            if obj.type_arguments.lower() == "sd:datarow":
                register_name(obj.item_var)
                data_row_vars.add(obj.item_var.lower())
            elif obj.type_arguments.lower() == "njl:jtoken":
                # 知見245: `JArray`(`DeserializeJsonArray`)を反復する
                # `ui:ForEach x:TypeArguments="njl:JToken"`の反復変数——
                # `ForEachRow`の`data_row_vars`伝播(知見203)と同じ既存
                # パターンで、反復変数自身もJSONトークンの添字アクセス
                # (`currentItem("picture")`)対象として追跡する。
                register_name(obj.item_var)
                json_object_vars.add(obj.item_var.lower())
        elif isinstance(obj, BuildDataTableNode):
            if isinstance(obj.data_table, VbExpr):
                register_name(obj.data_table.text)
                data_table_columns[obj.data_table.text.lower()] = list(obj.columns)
        elif isinstance(obj, (AddLogFieldsNode, RemoveLogFieldsNode)):
            has_log_fields = True
        elif isinstance(obj, DeserializeJsonNode):
            if isinstance(obj.json_object, VbExpr) and (obj.type_argument or "").lower().endswith(
                "jobject"
            ):
                json_object_vars.add(obj.json_object.text.lower())
        elif isinstance(obj, DeserializeJsonArrayNode):
            if isinstance(obj.json_array, VbExpr):
                json_object_vars.add(obj.json_array.text.lower())

    _walk_scope_sources(workflow.root, set(), on_node)

    return ScopeInfo(
        canonical_names=canonical_names,
        data_row_vars=frozenset(data_row_vars),
        data_table_columns=data_table_columns,
        has_log_fields=has_log_fields,
        json_object_vars=frozenset(json_object_vars),
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
    scope = _build_scope_info(workflow)
    with use_scope(scope):
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
    if scope.has_log_fields:
        # 知見240: `AddLogFields`/`RemoveLogFields`は関数ローカルな
        # `_log_fields`辞書を参照する——`if`/`for`/`try`等の入れ子ブロック
        # を跨いでも同じローカル変数を共有できるよう、関数本体の先頭
        # (変数初期化より前)で1回だけ宣言する。
        body = [f"{INDENT}_log_fields: dict[str, str] = {{}}", *body]
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
    # `PIL.Image`(`LoadImage`→`PIL.Image.open(...)`変換先、知見178)も
    # 同様。Pillowは`pad_codegen`で既に確認済みの依存。
    if any("PIL.Image.open(" in line for line in body):
        imports.append("import PIL.Image")
    # `PIL.ImageGrab`(`TakeScreenshot`のTarget省略時→`PIL.ImageGrab.
    # grab()`変換先、知見179)も同様。
    if any("PIL.ImageGrab.grab(" in line for line in body):
        imports.append("import PIL.ImageGrab")
    # `pytesseract`(`GetOCRText`の`GoogleOCR`(=Tesseract OCR)→
    # `pytesseract.image_to_string(...)`変換先、知見180)も同様。
    # `tests/test_ocr_fallback.py`で実機VM検証済みの既存確認済み依存。
    if any("pytesseract.image_to_string(" in line for line in body):
        imports.append("import pytesseract")
    # `csv`/`io`(`OutputDataTable`→`csv.writer(io.StringIO())`変換先、
    # 知見184。`ReadCsvFile`/`WriteCsvFile`→`csv.DictReader`/
    # `csv.writer`変換先、知見185)も同様。標準ライブラリ。
    if any("csv.writer(" in line or "csv.DictReader(" in line for line in body):
        imports.append("import csv")
    if any("io.StringIO(" in line for line in body):
        imports.append("import io")
    # `pypdf`(`ReadPDFText`→`pypdf.PdfReader(...).pages[...].
    # extract_text()`変換先、知見199)。`pyproject.toml`で既に確認済み
    # の依存(PAD側`pad_action_lib/pdf_actions.py`で既に実戦投入済み)。
    if any("pypdf.PdfReader(" in line for line in body):
        imports.append("import pypdf")
    # `pymupdf`(`ExportPDFPageAsImage`→`pymupdf.open(...).get_pixmap(
    # dpi=...).save(...)`変換先、知見209)も同様。`pyproject.toml`の
    # `[project.optional-dependencies]`の`pdf-render`プラグイン群——
    # `pypdf`と違い本体`dependencies`には無い、生成コードが参照する
    # だけの「プラグイン」依存(知見209の設計判断)。
    if any("pymupdf.open(" in line for line in body):
        imports.append("import pymupdf")
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
    # `imaplib`/`email`(`GetIMAPMailMessages`→`imaplib.IMAP4_SSL(...)`・
    # `email.message_from_bytes(...)`変換先、知見250)も同様。
    if any("imaplib.IMAP4_SSL(" in line for line in body):
        imports.append("import imaplib")
    if any("email.message_from_bytes(" in line for line in body):
        imports.append("import email")
    # `psutil`(`GetProcesses`→`psutil.process_iter(...)`変換先、知見255、
    # 既存のコア依存——`dump_daemon/uia_capture.py`で既に使用済み)も同様。
    if any("psutil.process_iter(" in line for line in body):
        imports.append("import psutil")
    # `win32cred`/`pywintypes`(`GetSecureCredential`→`win32cred.
    # CredRead(...)`・`AddCredential`→`win32cred.CredWrite(...)`変換先、
    # 知見248)も同様——`pywintypes.error`は`_win32_cred_read`ヘルパー
    # 自身が参照するため、ヘルパー注入時に一緒に`import`する。
    if any(
        "win32cred.CredRead(" in line or "win32cred.CredWrite(" in line
        or f"{_WIN32_CRED_READ_HELPER_NAME}(" in line
        for line in body
    ):
        imports.append("import win32cred")
    if any(f"{_WIN32_CRED_READ_HELPER_NAME}(" in line for line in body):
        imports.append("import pywintypes")
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
    # `shutil`/`os`(`CopyFile`→`shutil.copy(...)`変換先、知見117。
    # `MoveFile`→`shutil.move(...)`変換先、知見188。`DeleteFolder`
    # (Recursive=True)→`shutil.rmtree(...)`変換先、知見189。
    # `ExtractFiles`→`shutil.unpack_archive(...)`変換先、知見217)も
    # 同様。
    if any(
        "shutil.copy(" in line or "shutil.move(" in line or "shutil.rmtree(" in line
        or "shutil.unpack_archive(" in line or "shutil.copytree(" in line
        for line in body
    ):
        imports.append("import shutil")
    # `zipfile`(`CompressFiles`→`zipfile.ZipFile(...)`変換先、知見218)
    # も同様。
    if any("zipfile.ZipFile(" in line for line in body):
        imports.append("import zipfile")
    # `lxml.etree`(`DeserializeXml`→`lxml.etree.fromstring(...)`変換先、
    # `ExecuteXPath`→`....xpath(...)`変換先、知見228)も同様。`pyproject.
    # toml`で既に確認済みの依存(`xaml_tree.py`自身がXAMLパースに使う)
    # ——`pymupdf`知見209のような新規「プラグイン」依存ではない。
    if any("lxml.etree.fromstring(" in line or ".xpath(" in line for line in body):
        imports.append("import lxml.etree")
    # `os.getcwd()`(`Environment.CurrentDirectory`変換先、知見140)・
    # `os.remove(`/`os.rmdir(`(`DeleteFile`/`DeleteFolder`(Recursive=
    # False)変換先、知見189)・`os.scandir(`/`os.walk(`(`ForEachFile`/
    # `ForEachFolder`変換先、知見190)も同じ`os`モジュールのため同じ
    # 条件にまとめる。
    # `os.environ.get(`(`GetEnvironmentVariable`変換先、知見215)・
    # `os.environ[`(`SetEnvironmentVariable`変換先、知見223)・
    # `os.listdir(`(`GetLastDownloadedFile`のダウンロードフォルダ
    # ポーリング変換先、知見233)・`os.makedirs(`(`CreateDirectory`
    # 変換先、知見235)も同じ`os`モジュールのため同じ条件にまとめる。
    if any(
        "os.path." in line or "os.getcwd(" in line or "os.remove(" in line
        or "os.rmdir(" in line or "os.scandir(" in line or "os.walk(" in line
        or "os.rename(" in line or "os.environ." in line or "os.environ[" in line
        or "os.listdir(" in line or "os.makedirs(" in line
        for line in body
    ):
        imports.append("import os")
    # `platform`/`getpass`(`GetEnvironmentVariable`の`MachineName`/
    # `UserName`特殊プロパティ変換先、知見215)も同様。
    if any("platform.node(" in line for line in body):
        imports.append("import platform")
    if any("getpass.getuser(" in line or "getpass.getpass(" in line for line in body):
        imports.append("import getpass")
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
    # `re`(`Regex.Replace`→`re.sub(...)`変換先、知見144。`IsMatch`→
    # `re.search(...)`変換先、知見213)も同様。
    if any("re.sub(" in line or "re.search(" in line for line in body):
        imports.append("import re")
    # `logging`(`LogMessage`→`logging.info(...)`/`.error(...)`変換先、
    # 知見119)も同様。
    if any("logging.info(" in line or "logging.error(" in line for line in body):
        imports.append("import logging")
    # `json`(`DeserializeJson`→`json.loads(...)`変換先、知見241)も同様。
    if any("json.loads(" in line for line in body):
        imports.append("import json")
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
    # `_outlook_find_folder`(`MoveMailX`→`MailItem.Move(...)`のフォルダ
    # 解決先、知見229)も同様。
    if any(f"{_OUTLOOK_FIND_FOLDER_HELPER_NAME}(" in line for line in body):
        imports.append(_OUTLOOK_FIND_FOLDER_HELPER_SOURCE.rstrip("\n"))
    # `_log_fields_suffix`(`LogMessage`→`_log_fields`辞書のサフィックス化、
    # 知見240)も同様。
    if any(f"{_LOG_FIELDS_SUFFIX_HELPER_NAME}(" in line for line in body):
        imports.append(_LOG_FIELDS_SUFFIX_HELPER_SOURCE.rstrip("\n"))
    # `_win32_cred_read`(`GetSecureCredential`→`win32cred.CredRead(...)`の
    # 「見つからない」例外を`None`へ変換する先、知見248)も同様。
    if any(f"{_WIN32_CRED_READ_HELPER_NAME}(" in line for line in body):
        imports.append(_WIN32_CRED_READ_HELPER_SOURCE.rstrip("\n"))
    # `_ImapMailMessage`(`GetIMAPMailMessages`→`.Subject`属性アクセス先、
    # 知見250)も同様。
    if any(f"{_IMAP_MAIL_MESSAGE_HELPER_NAME}(" in line for line in body):
        imports.append(_IMAP_MAIL_MESSAGE_HELPER_SOURCE.rstrip("\n"))
    # `_Win32Credential`(`GetUsernamePasswordX`→`.Username`/`.Password`
    # 属性アクセス先、知見253)も同様。
    if any(f"{_WIN32_CREDENTIAL_HELPER_NAME}(" in line for line in body):
        imports.append(_WIN32_CREDENTIAL_HELPER_SOURCE.rstrip("\n"))
    # `_word_replace_picture`(`WordReplacePicture`→Alt Text検索+画像
    # パーツの`._blob`直接上書き、知見263)も同様。
    if any(f"{_WORD_REPLACE_PICTURE_HELPER_NAME}(" in line for line in body):
        imports.append(_WORD_REPLACE_PICTURE_HELPER_SOURCE.rstrip("\n"))
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
    if isinstance(node, IfElseIfV2Node):
        return _generate_if_else_if_v2(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, AddLogFieldsNode):
        return _generate_add_log_fields(node, indent)
    if isinstance(node, RemoveLogFieldsNode):
        return _generate_remove_log_fields(node, indent)
    if isinstance(node, DeserializeJsonNode):
        return _generate_deserialize_json(node, indent)
    if isinstance(node, DeserializeJsonArrayNode):
        return _generate_deserialize_json_array(node, indent)
    if isinstance(node, ForEachNode):
        return _generate_for_each(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, RepeatNumberOfTimesXNode):
        return _generate_repeat_number_of_times_x(
            node, indent, invoke_resolver, out_arg_resolver
        )
    if isinstance(node, ForEachFileNode):
        return _generate_for_each_file(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, ForEachFolderNode):
        return _generate_for_each_folder(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, RenameFileNode):
        return _generate_rename_file(node, indent)
    if isinstance(node, RenameFolderNode):
        return _generate_rename_folder(node, indent)
    if isinstance(node, CreateFileNode):
        return _generate_create_file(node, indent)
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
    if isinstance(node, ContinueNode):
        return [f"{prefix}continue"]
    if isinstance(node, ReturnNode):
        return [f"{prefix}return"]
    if isinstance(node, ParallelNode):
        return _generate_parallel(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, AppendLineNode):
        return _generate_append_line(node, indent)
    if isinstance(node, WriteTextFileNode):
        return _generate_write_text_file(node, indent)
    if isinstance(node, ExtractFilesNode):
        return _generate_extract_files(node, indent)
    if isinstance(node, CompressFilesNode):
        return _generate_compress_files(node, indent)
    if isinstance(node, IsMatchNode):
        return _generate_is_match(node, indent)
    if isinstance(node, ReplaceNode):
        return _generate_replace(node, indent)
    if isinstance(node, MatchesNode):
        return _generate_matches(node, indent)
    if isinstance(node, TextToLeftRightNode):
        return _generate_text_to_left_right(node, indent)
    if isinstance(node, GetEnvironmentVariableNode):
        return _generate_get_environment_variable(node, indent)
    if isinstance(node, SetEnvironmentVariableNode):
        return _generate_set_environment_variable(node, indent)
    if isinstance(node, GetEnvironmentFolderNode):
        return _generate_get_environment_folder(node, indent)
    if isinstance(node, ModifyTextNode):
        return _generate_modify_text(node, indent)
    if isinstance(node, ReadTextFileNode):
        return _generate_read_text_file(node, indent)
    if isinstance(node, SetToClipboardNode):
        return _generate_set_to_clipboard(node, indent)
    if isinstance(node, GetFromClipboardNode):
        return _generate_get_from_clipboard(node, indent)
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
    if isinstance(node, WindowStateNode):
        return _generate_window_state(node, indent)
    if isinstance(node, GetProcessesNode):
        return _generate_get_processes(node, indent)
    if isinstance(node, KillProcessNode):
        return _generate_kill_process(node, indent)
    if isinstance(node, AddDataRowNode):
        return _generate_add_data_row(node, indent)
    if isinstance(node, RemoveDataRowNode):
        return _generate_remove_data_row(node, indent)
    if isinstance(node, GetRowItemNode):
        return _generate_get_row_item(node, indent)
    if isinstance(node, UpdateRowItemNode):
        return _generate_update_row_item(node, indent)
    if isinstance(node, ClearDataTableNode):
        return _generate_clear_data_table(node, indent)
    if isinstance(node, OutputDataTableNode):
        return _generate_output_data_table(node, indent)
    if isinstance(node, AddDataColumnNode):
        return _generate_add_data_column(node, indent)
    if isinstance(node, RemoveDataColumnNode):
        return _generate_remove_data_column(node, indent)
    if isinstance(node, ReadCsvFileNode):
        return _generate_read_csv_file(node, indent)
    if isinstance(node, ReadPdfTextNode):
        return _generate_read_pdf_text(node, indent)
    if isinstance(node, GetPdfPageCountNode):
        return _generate_get_pdf_page_count(node, indent)
    if isinstance(node, ExtractPdfPageRangeNode):
        return _generate_extract_pdf_page_range(node, indent)
    if isinstance(node, JoinPdfNode):
        return _generate_join_pdf(node, indent)
    if isinstance(node, ExportPdfPageAsImageNode):
        return _generate_export_pdf_page_as_image(node, indent)
    if isinstance(node, ExtractImagesFromPdfNode):
        return _generate_extract_images_from_pdf(node, indent)
    if isinstance(node, ManagePdfPasswordNode):
        return _generate_manage_pdf_password(node, indent)
    if isinstance(node, WriteCsvFileNode):
        return _generate_write_csv_file(node, indent)
    if isinstance(node, DeserializeXmlNode):
        return _generate_deserialize_xml(node, indent)
    if isinstance(node, ExecuteXPathNode):
        return _generate_execute_xpath(node, indent)
    if isinstance(node, InvokePowerShellNode):
        return _generate_invoke_powershell(node, indent)
    if isinstance(node, RetryScopeNode):
        return _generate_retry_scope(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, GetOcrTextNode):
        return _generate_get_ocr_text(node, indent)
    if isinstance(node, SaveImageNode):
        return _generate_save_image(node, indent)
    if isinstance(node, TakeScreenshotNode):
        return _generate_take_screenshot(node, indent)
    if isinstance(node, CloseTabNode):
        return _generate_close_tab(node, indent)
    if isinstance(node, RefreshBrowserNode):
        return _generate_refresh_browser(node, indent)
    if isinstance(node, GoBackNode):
        return _generate_go_back(node, indent)
    if isinstance(node, NavigateToNode):
        return _generate_navigate_to(node, indent)
    if isinstance(node, TypeIntoNode):
        return _generate_type_into(node, indent)
    if isinstance(node, SendHotkeyNode):
        return _generate_send_hotkey(node, indent)
    if isinstance(node, GetTextNode):
        return _generate_get_text(node, indent)
    if isinstance(node, GenerateDataTableNode):
        return _generate_generate_data_table(node, indent)
    if isinstance(node, GetAttributeNode):
        return _generate_get_attribute(node, indent)
    if isinstance(node, GetPasswordNode):
        return _generate_get_password(node, indent)
    if isinstance(node, GetSecureCredentialNode):
        return _generate_get_secure_credential(node, indent)
    if isinstance(node, AddCredentialNode):
        return _generate_add_credential(node, indent)
    if isinstance(node, RequestCredentialNode):
        return _generate_request_credential(node, indent)
    if isinstance(node, GetUsernamePasswordXNode):
        return _generate_get_username_password_x(node, indent)
    if isinstance(node, LoadImageNode):
        return _generate_load_image(node, indent)
    if isinstance(node, LookupDataTableNode):
        return _generate_lookup_data_table(node, indent)
    if isinstance(node, SortDataTableNode):
        return _generate_sort_data_table(node, indent)
    if isinstance(node, FilterDataTableNode):
        return _generate_filter_data_table(node, indent)
    if isinstance(node, JoinDataTablesNode):
        return _generate_join_data_tables(node, indent)
    if isinstance(node, RemoveDuplicateRowsNode):
        return _generate_remove_duplicate_rows(node, indent)
    if isinstance(node, SelectFileNode):
        return _generate_select_file(node, indent)
    if isinstance(node, SelectFolderNode):
        return _generate_select_folder(node, indent)
    if isinstance(node, SelectItemNode):
        return _generate_select_item(node, indent)
    if isinstance(node, SelectMultipleItemsNode):
        return _generate_select_multiple_items(node, indent)
    if isinstance(node, UiElementExistsNode):
        return _generate_ui_element_exists(node, indent)
    if isinstance(node, WaitUiElementAppearNode):
        return _generate_wait_ui_element_appear(node, indent)
    if isinstance(node, DatabaseConnectNode):
        return _generate_database_connect(node, indent)
    if isinstance(node, DatabaseDisconnectNode):
        return _generate_database_disconnect(node, indent)
    if isinstance(node, ExecuteQueryNode):
        return _generate_execute_query(node, indent)
    if isinstance(node, ExecuteNonQueryNode):
        return _generate_execute_non_query(node, indent)
    if isinstance(node, InsertDataTableNode):
        return _generate_insert_data_table(node, indent)
    if isinstance(node, BulkInsertNode):
        return _generate_bulk_insert(node, indent)
    if isinstance(node, DatabaseTransactionNode):
        return _generate_database_transaction(
            node, indent, invoke_resolver, out_arg_resolver
        )
    if isinstance(node, ExtractTextNode):
        return _generate_extract_text(node, indent)
    if isinstance(node, SplitTextNode):
        return _generate_split_text(node, indent)
    if isinstance(node, CombineTextNode):
        return _generate_combine_text(node, indent)
    if isinstance(node, GetLastDownloadedFileNode):
        return _generate_get_last_downloaded_file(
            node, indent, invoke_resolver, out_arg_resolver
        )
    if isinstance(node, CheckTrueNode):
        return _generate_check_true(node, indent)
    if isinstance(node, CheckFalseNode):
        return _generate_check_false(node, indent)
    if isinstance(node, CreateDirectoryNode):
        return _generate_create_directory(node, indent)
    if isinstance(node, MergeDataTableNode):
        return _generate_merge_data_table(node, indent)
    if isinstance(node, FormatValueNode):
        return _generate_format_value(node, indent)
    if isinstance(node, InvokeWorkflowFileNode):
        return _generate_invoke_workflow_file(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, CopyFileNode):
        return _generate_copy_file(node, indent)
    if isinstance(node, MoveFileNode):
        return _generate_move_file(node, indent)
    if isinstance(node, CopyFolderXNode):
        return _generate_copy_folder_x(node, indent)
    if isinstance(node, MoveFolderXNode):
        return _generate_move_folder_x(node, indent)
    if isinstance(node, PathExistsNode):
        return _generate_path_exists(node, indent)
    if isinstance(node, FileExistsXNode):
        return _generate_file_exists_x(node, indent)
    if isinstance(node, FolderExistsXNode):
        return _generate_folder_exists_x(node, indent)
    if isinstance(node, DeleteFileNode):
        return _generate_delete_file(node, indent)
    if isinstance(node, DeleteFolderNode):
        return _generate_delete_folder(node, indent)
    if isinstance(node, BuildDataTableNode):
        return _generate_build_data_table(node, indent)
    if isinstance(node, HttpClientNode):
        return _generate_http_client(node, indent)
    if isinstance(node, AttachWindowNode):
        return _generate_attach_window(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, OpenApplicationNode):
        return _generate_open_application(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, StartProcessNode):
        return _generate_start_process(node, indent)
    if isinstance(node, OpenBrowserNode):
        return _generate_open_browser(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, ExcelApplicationScopeNode):
        return _generate_excel_application_scope(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, ReadRangeNode):
        return _generate_read_range(node, indent)
    if isinstance(node, WriteRangeNode):
        return _generate_write_range(node, indent)
    if isinstance(node, ReadCellNode):
        return _generate_read_cell(node, indent)
    if isinstance(node, WriteCellNode):
        return _generate_write_cell(node, indent)
    if isinstance(node, WordApplicationScopeNode):
        return _generate_word_application_scope(node, indent, invoke_resolver, out_arg_resolver)
    if isinstance(node, SendMailNode):
        return _generate_send_mail(node, indent)
    if isinstance(node, SendOutlookMailNode):
        return _generate_send_outlook_mail(node, indent)
    if isinstance(node, GetOutlookMailMessagesNode):
        return _generate_get_outlook_mail_messages(node, indent)
    if isinstance(node, GetIMAPMailMessagesNode):
        return _generate_get_imap_mail_messages(node, indent)
    if isinstance(node, SaveMailAttachmentsNode):
        return _generate_save_mail_attachments(node, indent)
    if isinstance(node, MarkMailAsReadXNode):
        return _generate_mark_mail_as_read_x(node, indent)
    if isinstance(node, DeleteMailXNode):
        return _generate_delete_mail_x(node, indent)
    if isinstance(node, MoveMailXNode):
        return _generate_move_mail_x(node, indent)
    if isinstance(node, CommentNode):
        return _generate_comment(node, indent)
    if isinstance(node, CommentOutNode):
        return _generate_comment_out(node, indent)
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
            WordAppendTextNode,
            WordSaveAsNode,
            WordReadTextNode,
            WordAddImageNode,
            WordInsertDataTableNode,
            WordReplacePictureNode,
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


def _generate_if_else_if_v2(
    node: IfElseIfV2Node, indent: int, invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    """知見239: `ui:IfElseIfV2`。`Condition`(トップレベルif)+`.Then`+
    `.ElseIfs`(`BindingList<ui:IfElseIfBlock>`、各要素も`Condition`+
    `.Then`を持つ)+`.Else`——Pythonの`if/elif*/else`に直接対応する。
    `_generate_if`と同じ厳格な失敗モードを全ての`Condition`(トップレベル
    ・各`ElseIfs`要素)に適用する(モジュールdocstring参照)——分岐の
    どこか1箇所でも誤って推測すると、その後続の`elif`/`else`評価全体が
    ずれるため。"""
    prefix = INDENT * indent
    cond = render_expr(node.condition)
    lines = [f"{prefix}if {VB_BOOL_HELPER_NAME}({cond}):"]
    then_body = _ensure_nonempty_suite(
        _generate_body(node.then_body, indent + 1, invoke_resolver, out_arg_resolver), indent + 1
    )
    lines.extend(then_body)
    for block in node.else_ifs:
        block_cond = render_expr(block.condition)
        lines.append(f"{prefix}elif {VB_BOOL_HELPER_NAME}({block_cond}):")
        block_body = _ensure_nonempty_suite(
            _generate_body(block.then_body, indent + 1, invoke_resolver, out_arg_resolver), indent + 1
        )
        lines.extend(block_body)
    if node.else_body:
        lines.append(f"{prefix}else:")
        else_body = _ensure_nonempty_suite(
            _generate_body(node.else_body, indent + 1, invoke_resolver, out_arg_resolver), indent + 1
        )
        lines.extend(else_body)
    return lines


def _generate_add_log_fields(node: AddLogFieldsNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_add_log_fields_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_add_log_fields_body(node: AddLogFieldsNode, indent: int) -> list[str]:
    """知見240: `AddLogFields.Fields`(`x:Key`付き辞書、`_xkey_dict_entries`
    でパース済み)——関数ローカル`_log_fields`辞書(`generate_python()`が
    `scope.has_log_fields`の時だけ関数先頭に宣言)へ`.update()`する。
    値は`LogMessage`自体と同じ`_vb_cstr()`防御的変換(`Fields`は常に
    `x:String`型の`InArgument`だが、既存の`LogMessage.Message`と同じ
    一貫性のため)。"""
    prefix = INDENT * indent
    todo: list[str] = []
    entries = []
    for key, expr in node.fields.items():
        value = _render_value_or_todo(expr, prefix, todo)
        entries.append(f"{key!r}: {VB_CSTR_HELPER_NAME}({value})")
    if todo:
        return todo
    return [f"{prefix}_log_fields.update({{{', '.join(entries)}}})"]


def _generate_remove_log_fields(node: RemoveLogFieldsNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_remove_log_fields_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_remove_log_fields_body(node: RemoveLogFieldsNode, indent: int) -> list[str]:
    """知見240: `RemoveLogFields.Fields`(フィールド名の`List<InArgument
    (x:String)>`、`_parse_property_element_list`でパース済み)——関数
    ローカル`_log_fields`辞書から`.pop(key, None)`する(未存在キーの削除
    は無害、.NET側が例外を投げるという記述は公式ドキュメントに無いため
    無視して継続する実装を選ぶ)。"""
    prefix = INDENT * indent
    todo: list[str] = []
    names = [_render_value_or_todo(expr, prefix, todo) for expr in node.fields]
    if todo:
        return todo
    if not names:
        return [f"{prefix}pass"]
    lines = [f"{prefix}_log_fields.pop({name}, None)" for name in names]
    return lines


def _generate_deserialize_json(node: DeserializeJsonNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_deserialize_json_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_deserialize_json_body(node: DeserializeJsonNode, indent: int) -> list[str]:
    """知見241: `ui:DeserializeJson<njl:JObject>`——`njl:JObject`
    (`Newtonsoft.Json.Linq.JObject`、ground-truth・実機複数件で確認済みの
    唯一の`x:TypeArguments`)のみ対応し、他の型引数(カスタムPOCO等、
    未確認)は見送る。`JObject`はPythonの`dict`(`json.loads()`の戻り値)
    として表現する——`GetFileInfoX`等と違い架空のラッパークラスは不要。
    `JsonObject`(代入先)は`Assign.target`(知見136・137)と同じ厳格な
    失敗モード——`render_expr`を直接呼び、例外発生時は代入文自体を
    生成しない。"""
    prefix = INDENT * indent
    if node.json_object is None:
        return [f"{prefix}# TODO: DeserializeJson with no JsonObject captured"]
    if node.json_string is None:
        return [f"{prefix}# TODO: DeserializeJson with no JsonString captured"]
    type_arg = (node.type_argument or "").rsplit(":", 1)[-1].lower()
    if type_arg != "jobject":
        return [
            f"{prefix}# TODO: DeserializeJson with TypeArguments="
            f"{node.type_argument!r} — only njl:JObject (-> Python dict via "
            "json.loads()) is confirmed, refusing to guess for other .NET types"
        ]
    try:
        target = render_expr(node.json_object)
    except NotImplementedError as e:
        return _todo_value(prefix, str(e))
    todo: list[str] = []
    json_string = _render_value_or_todo(node.json_string, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}{target} = json.loads({json_string})"]


def _generate_deserialize_json_array(node: DeserializeJsonArrayNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_deserialize_json_array_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_deserialize_json_array_body(
    node: DeserializeJsonArrayNode, indent: int
) -> list[str]:
    """知見245: `ui:DeserializeJsonArray`(`DeserializeJson<njl:JObject>`
    (知見241)の兄弟活動)——`x:TypeArguments`無しの非ジェネリック活動、
    常に`JArray`。Pythonの`list`(`json.loads()`の戻り値)として表現
    する。`JsonArray`(代入先)は`DeserializeJson.JsonObject`と同じ
    厳格な失敗モード(`render_expr`を直接呼び、例外発生時は代入文自体
    を生成しない)。"""
    prefix = INDENT * indent
    if node.json_array is None:
        return [f"{prefix}# TODO: DeserializeJsonArray with no JsonArray captured"]
    if node.json_string is None:
        return [f"{prefix}# TODO: DeserializeJsonArray with no JsonString captured"]
    try:
        target = render_expr(node.json_array)
    except NotImplementedError as e:
        return _todo_value(prefix, str(e))
    todo: list[str] = []
    json_string = _render_value_or_todo(node.json_string, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}{target} = json.loads({json_string})"]


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


def _generate_repeat_number_of_times_x(
    node: RepeatNumberOfTimesXNode, indent: int,
    invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    """知見227: `ui:RepeatNumberOfTimesX`。`StartAt`は`CurrentItem`の
    開始値のみを決め、反復回数には影響しない(公式ドキュメント確認
    済み)——`NumberOfTimes`回だけ常に実行する`range(start_at, start_at
    + number_of_times)`に対応する。`StartAt`省略時(実機で確認済み、
    `Apress/Robotic-Process-Automation-Using-UiPath-StudioX`)は
    公式ドキュメント確認済みの既定値`1`をPython側で補う。`RetryScope`
    (`_retry_max`)と同じ`round(_vb_cdbl(...))`でInt32相当に丸める。"""
    prefix = INDENT * indent
    if node.number_of_times is None:
        return [
            f"{prefix}# TODO: RepeatNumberOfTimesX with missing NumberOfTimes"
        ]
    todo: list[str] = []
    number_of_times = _render_value_or_todo(node.number_of_times, prefix, todo)
    start_at = (
        _render_value_or_todo(node.start_at, prefix, todo)
        if node.start_at is not None
        else "1"
    )
    if todo:
        return todo
    lines = [
        f"{prefix}_rnt_start = round({VB_CDBL_HELPER_NAME}({start_at}))",
        f"{prefix}_rnt_count = round({VB_CDBL_HELPER_NAME}({number_of_times}))",
        f"{prefix}for {node.item_var or 'CurrentItem'} in "
        "range(_rnt_start, _rnt_start + _rnt_count):",
    ]
    body = _ensure_nonempty_suite(
        _generate_body(node.body, indent + 1, invoke_resolver, out_arg_resolver),
        indent + 1,
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


def _generate_write_text_file(node: WriteTextFileNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_write_text_file_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_write_text_file_body(node: WriteTextFileNode, indent: int) -> list[str]:
    """知見212: `File`(`FileInfo`オブジェクト参照と推測)・`Output`
    (書き込み後の`FileInfo`出力と推測)は実機で非`{x:Null}`の実例が無く
    未モデル化のため常に`# TODO`。`Text`は`SetToClipboard`(知見46)と
    同じ`InArgument<String>`型のため`_vb_cstr()`で変換する。"""
    prefix = INDENT * indent
    if node.file is not None:
        return [
            f"{prefix}# TODO: WriteTextFile with File set — object "
            "reference not modeled, refusing to guess"
        ]
    if node.output is not None:
        return [
            f"{prefix}# TODO: WriteTextFile with Output captured — "
            "output FileInfo semantics not confirmed, refusing to guess"
        ]
    if node.file_name is None or node.text is None:
        return [f"{prefix}# TODO: WriteTextFile with missing FileName/Text"]
    todo: list[str] = []
    file_name = _render_value_or_todo(node.file_name, prefix, todo)
    text = _render_value_or_todo(node.text, prefix, todo)
    if todo:
        return todo
    return [
        f'{prefix}open({file_name}, "w", encoding="utf-8").write('
        f"{VB_CSTR_HELPER_NAME}({text}))"
    ]


def _generate_extract_files(node: ExtractFilesNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_extract_files_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_extract_files_body(node: ExtractFilesNode, indent: int) -> list[str]:
    """知見217: 実機確認済みの構成(`CodePage="Default"`・
    `ExtractToADedicatedFolder="False"`・`SkipUnsupportedFiles=
    "False"`・`Password`未設定)のみ対応。`shutil.unpack_archive()`
    (標準ライブラリ、zip/tar系の拡張子を自動判別)が直接対応する。"""
    prefix = INDENT * indent
    if node.content is not None or node.file is not None:
        return [
            f"{prefix}# TODO: ExtractFiles with Content/File set — "
            "object reference not modeled, refusing to guess"
        ]
    if node.destination_folder_info is not None:
        return [
            f"{prefix}# TODO: ExtractFiles with DestinationFolderInfo "
            "captured — output FileInfo semantics not confirmed, "
            "refusing to guess"
        ]
    if node.password is not None:
        return [
            f"{prefix}# TODO: ExtractFiles with Password set — "
            "encrypted archive extraction not confirmed in real "
            "samples, refusing to guess"
        ]
    if node.code_page not in (None, "Default"):
        return [
            f"{prefix}# TODO: ExtractFiles with CodePage "
            f"{node.code_page!r} — not confirmed in real samples, "
            "refusing to guess"
        ]
    if node.extract_to_a_dedicated_folder not in (None, "False"):
        return [
            f"{prefix}# TODO: ExtractFiles with ExtractToADedicatedFolder "
            f"{node.extract_to_a_dedicated_folder!r} — only 'False' "
            "confirmed in real samples, refusing to guess"
        ]
    if node.skip_unsupported_files not in (None, "False"):
        return [
            f"{prefix}# TODO: ExtractFiles with SkipUnsupportedFiles "
            f"{node.skip_unsupported_files!r} — only 'False' confirmed "
            "in real samples, refusing to guess"
        ]
    if node.file_to_extract is None or node.destination_folder is None:
        return [
            f"{prefix}# TODO: ExtractFiles with missing FileToExtract/"
            "DestinationFolder"
        ]
    todo: list[str] = []
    file_to_extract = _render_value_or_todo(node.file_to_extract, prefix, todo)
    destination_folder = _render_value_or_todo(node.destination_folder, prefix, todo)
    if todo:
        return todo
    return [
        f"{prefix}shutil.unpack_archive({file_to_extract}, {destination_folder})"
    ]


def _generate_compress_files(node: CompressFilesNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_compress_files_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_compress_files_body(node: CompressFilesNode, indent: int) -> list[str]:
    """知見218: 実機確認済みの構成(`CodePage="Default"`・
    `CompressionLevel="Normal"`・`OverrideExistingFile="True"`・
    `Password`/`SecurePassword`未設定)のみ対応。`ContentToArchive`の
    各要素がフォルダパスの場合、フォーラム調査で確認した挙動
    (フォルダ自身の名前はアーカイブ内に含まれず、中身がトップレベルに
    展開される)を`os.walk()`+`os.path.relpath()`で再現する。"""
    prefix = INDENT * indent
    if node.compressed_file_info is not None:
        return [
            f"{prefix}# TODO: CompressFiles with CompressedFileInfo "
            "captured — output FileInfo semantics not confirmed, "
            "refusing to guess"
        ]
    if node.compressed_resource is not None or node.resources_to_archive is not None:
        return [
            f"{prefix}# TODO: CompressFiles with CompressedResource/"
            "ResourcesToArchive set — not confirmed in real samples, "
            "refusing to guess"
        ]
    if node.password is not None or node.secure_password is not None:
        return [
            f"{prefix}# TODO: CompressFiles with Password/"
            "SecurePassword set — encrypted archive creation not "
            "confirmed in real samples, refusing to guess"
        ]
    if node.code_page not in (None, "Default"):
        return [
            f"{prefix}# TODO: CompressFiles with CodePage "
            f"{node.code_page!r} — not confirmed in real samples, "
            "refusing to guess"
        ]
    if node.compression_level not in (None, "Normal"):
        return [
            f"{prefix}# TODO: CompressFiles with CompressionLevel "
            f"{node.compression_level!r} — not confirmed in real "
            "samples, refusing to guess"
        ]
    if node.encryption_algorithm not in (None, "Classic"):
        return [
            f"{prefix}# TODO: CompressFiles with EncryptionAlgorithm "
            f"{node.encryption_algorithm!r} — not confirmed in real "
            "samples, refusing to guess"
        ]
    if node.override_existing_file not in (None, "True"):
        return [
            f"{prefix}# TODO: CompressFiles with OverrideExistingFile "
            f"{node.override_existing_file!r} — only 'True' confirmed "
            "in real samples, refusing to guess"
        ]
    if node.allow_duplicate_content_names not in (None, "False"):
        return [
            f"{prefix}# TODO: CompressFiles with "
            f"AllowDuplicateContentNames {node.allow_duplicate_content_names!r} "
            "— not confirmed in real samples, refusing to guess"
        ]
    if not node.content_to_archive:
        return [f"{prefix}# TODO: CompressFiles with no ContentToArchive captured"]
    if node.compressed_file_name is None:
        return [f"{prefix}# TODO: CompressFiles with no CompressedFileName captured"]
    todo: list[str] = []
    items = [
        _render_value_or_todo(item, prefix, todo) for item in node.content_to_archive
    ]
    compressed_file_name = _render_value_or_todo(
        node.compressed_file_name, prefix, todo
    )
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    inner2 = INDENT * (indent + 2)
    inner3 = INDENT * (indent + 3)
    return [
        f"{prefix}with zipfile.ZipFile({compressed_file_name}, \"w\") as _cf_zip:",
        f"{inner}for _cf_item in [{', '.join(items)}]:",
        f"{inner2}if os.path.isdir(_cf_item):",
        f"{inner3}for _cf_root, _cf_dirs, _cf_files in os.walk(_cf_item):",
        f"{inner3}{INDENT}for _cf_fn in _cf_files:",
        f"{inner3}{INDENT * 2}_cf_full = os.path.join(_cf_root, _cf_fn)",
        f"{inner3}{INDENT * 2}_cf_zip.write(_cf_full, "
        "os.path.relpath(_cf_full, _cf_item))",
        f"{inner2}else:",
        f"{inner3}_cf_zip.write(_cf_item, os.path.basename(_cf_item))",
    ]


_REGEX_ALLOWED_OPTIONS = {"IgnoreCase", "Compiled"}


def _generate_is_match(node: IsMatchNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_is_match_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_is_match_body(node: IsMatchNode, indent: int) -> list[str]:
    """知見213: `RegexOption`は実機確認済みの`"IgnoreCase"`単体/
    `"IgnoreCase, Compiled"`の2値のみ対応——`Compiled`はPythonの`re`に
    対応概念が無いため無視、未確認の他フラグは`# TODO`へ倒す。"""
    prefix = INDENT * indent
    if node.input is None or node.pattern is None:
        return [f"{prefix}# TODO: IsMatch with missing Input/Pattern"]
    if node.result is None:
        return [f"{prefix}# TODO: IsMatch with no Result captured"]
    if node.regex_option is None:
        return [f"{prefix}# TODO: IsMatch with no RegexOption captured"]
    options = {opt.strip() for opt in node.regex_option.split(",")}
    if not options <= _REGEX_ALLOWED_OPTIONS:
        return [
            f"{prefix}# TODO: IsMatch with unrecognized RegexOption "
            f"({node.regex_option!r}) — refusing to guess"
        ]
    todo: list[str] = []
    input_ = _render_value_or_todo(node.input, prefix, todo)
    pattern = _render_value_or_todo(node.pattern, prefix, todo)
    result = _render_value_or_todo(node.result, prefix, todo)
    if todo:
        return todo
    flags = ", re.IGNORECASE" if "IgnoreCase" in options else ""
    return [
        f"{prefix}{result} = bool(re.search({pattern}, "
        f"{VB_CSTR_HELPER_NAME}({input_}){flags}))"
    ]


def _generate_replace(node: ReplaceNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_replace_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_replace_body(node: ReplaceNode, indent: int) -> list[str]:
    """知見220: `IsMatch`(知見213)と同じ`RegexOption`の判断
    (`"IgnoreCase"`/`"IgnoreCase, Compiled"`のみ対応)。`.NET
    Regex.Replace(input, pattern, replacement)`は`re.sub(pattern,
    replacement, input)`に対応する——`Replacement`内の`$1`等の.NET
    後方参照記法は変換しない(知見144と同じ既存の判断)。"""
    prefix = INDENT * indent
    if node.input is None or node.pattern is None or node.replacement is None:
        return [
            f"{prefix}# TODO: Replace with missing Input/Pattern/Replacement"
        ]
    if node.result is None:
        return [f"{prefix}# TODO: Replace with no Result captured"]
    if node.regex_option is None:
        return [f"{prefix}# TODO: Replace with no RegexOption captured"]
    options = {opt.strip() for opt in node.regex_option.split(",")}
    if not options <= _REGEX_ALLOWED_OPTIONS:
        return [
            f"{prefix}# TODO: Replace with unrecognized RegexOption "
            f"({node.regex_option!r}) — refusing to guess"
        ]
    todo: list[str] = []
    input_ = _render_value_or_todo(node.input, prefix, todo)
    pattern = _render_value_or_todo(node.pattern, prefix, todo)
    replacement = _render_value_or_todo(node.replacement, prefix, todo)
    result = _render_value_or_todo(node.result, prefix, todo)
    if todo:
        return todo
    flags = ", flags=re.IGNORECASE" if "IgnoreCase" in options else ""
    return [
        f"{prefix}{result} = re.sub({pattern}, "
        f"{VB_CSTR_HELPER_NAME}({replacement}), "
        f"{VB_CSTR_HELPER_NAME}({input_}){flags})"
    ]


def _generate_matches(node: MatchesNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_matches_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_matches_body(node: MatchesNode, indent: int) -> list[str]:
    """知見221: `Result`の正確な型(リスト?`MatchCollection`相当?)が
    実機からは確認できないため常に`# TODO`、`FirstMatch`のみ対応。
    `.NET Regex.Match(input, pattern).Value`は`re.search()`が一致
    しない場合も含め、常に文字列(不一致時は`""`)を返す——
    `re.search()`の`None`を同じ`""`へ変換する。"""
    prefix = INDENT * indent
    if node.input is None or node.pattern is None:
        return [f"{prefix}# TODO: Matches with missing Input/Pattern"]
    if node.result is not None:
        return [
            f"{prefix}# TODO: Matches with Result captured — exact "
            "collection type not confirmed in real samples, refusing "
            "to guess"
        ]
    if node.first_match is None:
        return [f"{prefix}# TODO: Matches with no output FirstMatch captured"]
    if node.regex_option is None:
        return [f"{prefix}# TODO: Matches with no RegexOption captured"]
    options = {opt.strip() for opt in node.regex_option.split(",")}
    if not options <= _REGEX_ALLOWED_OPTIONS:
        return [
            f"{prefix}# TODO: Matches with unrecognized RegexOption "
            f"({node.regex_option!r}) — refusing to guess"
        ]
    todo: list[str] = []
    input_ = _render_value_or_todo(node.input, prefix, todo)
    pattern = _render_value_or_todo(node.pattern, prefix, todo)
    first_match = _render_value_or_todo(node.first_match, prefix, todo)
    if todo:
        return todo
    flags = ", re.IGNORECASE" if "IgnoreCase" in options else ""
    return [
        f"{prefix}_mch = re.search({pattern}, "
        f"{VB_CSTR_HELPER_NAME}({input_}){flags})",
        f"{prefix}{first_match} = _mch.group(0) if _mch else \"\"",
    ]


_TEXT_TO_LEFT_RIGHT_ALLOWED_SEPARATOR_KEYS = {"Custom", "NewLine"}


def _generate_text_to_left_right(node: TextToLeftRightNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_text_to_left_right_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_text_to_left_right_body(
    node: TextToLeftRightNode, indent: int
) -> list[str]:
    """知見222: `SeparatorKey`は`"Custom"`/`"NewLine"`のみ対応
    (実機確認済みの2種、他の値は`Separator`属性の正確な事前入力が
    未確認のため`# TODO`)。`Separator`の最初の出現位置で分割する
    `.NET`の挙動は`str.split(sep, 1)`に対応する。`Separator`が
    `FullText`中に見つからない場合の挙動は未確認のため、`TextToRight`
    側の代入で自然な`IndexError`が発生するに任せる(フォールバック値を
    捏造しない、`GetRowItem`知見177/183と同じ方針)。"""
    prefix = INDENT * indent
    if node.full_text is None or node.separator is None:
        return [
            f"{prefix}# TODO: TextToLeftRight with missing FullText/Separator"
        ]
    if node.separator_key is None:
        return [f"{prefix}# TODO: TextToLeftRight with no SeparatorKey captured"]
    if node.separator_key not in _TEXT_TO_LEFT_RIGHT_ALLOWED_SEPARATOR_KEYS:
        return [
            f"{prefix}# TODO: TextToLeftRight with unrecognized SeparatorKey "
            f"({node.separator_key!r}) — refusing to guess"
        ]
    if node.text_to_left is None and node.text_to_right is None:
        return [
            f"{prefix}# TODO: TextToLeftRight with no output captured"
        ]
    todo: list[str] = []
    full_text = _render_value_or_todo(node.full_text, prefix, todo)
    separator = _render_value_or_todo(node.separator, prefix, todo)
    if todo:
        return todo
    lines = [
        f"{prefix}_parts = {VB_CSTR_HELPER_NAME}({full_text}).split("
        f"{VB_CSTR_HELPER_NAME}({separator}), 1)"
    ]
    if node.text_to_left is not None:
        text_to_left = _render_value_or_todo(node.text_to_left, prefix, todo)
        if todo:
            return todo
        lines.append(f"{prefix}{text_to_left} = _parts[0]")
    if node.text_to_right is not None:
        text_to_right = _render_value_or_todo(node.text_to_right, prefix, todo)
        if todo:
            return todo
        lines.append(f"{prefix}{text_to_right} = _parts[1]")
    return lines


_GET_ENVIRONMENT_VARIABLE_SPECIAL_PROPERTIES = {
    "MachineName": "platform.node()",
    "UserName": "getpass.getuser()",
}


def _generate_get_environment_variable(
    node: GetEnvironmentVariableNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_get_environment_variable_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_get_environment_variable_body(
    node: GetEnvironmentVariableNode, indent: int
) -> list[str]:
    """知見215: `Variable`が静的リテラルでない場合、`System.Environment`
    の既知プロパティ名(優先)かOS環境変数(フォールバック)かを事前に
    判断できないため常に`# TODO`。確認済みの`MachineName`/`UserName`
    のみ対応、`OSVersion`は正確な書式を再現する標準的なPython対応が
    無いため未対応。"""
    prefix = INDENT * indent
    if node.variable is None or node.variable_value is None:
        return [
            f"{prefix}# TODO: GetEnvironmentVariable with missing "
            "Variable/VariableValue"
        ]
    if not isinstance(node.variable, Literal):
        return [
            f"{prefix}# TODO: GetEnvironmentVariable with a dynamic "
            "Variable — cannot statically tell apart a System.Environment "
            "property name from an OS environment variable, refusing to "
            "guess"
        ]
    name = node.variable.value
    if name == "OSVersion":
        return [
            f"{prefix}# TODO: GetEnvironmentVariable with Variable "
            "'OSVersion' — no confirmed Python equivalent for .NET's "
            "exact Environment.OSVersion string format, refusing to guess"
        ]
    todo: list[str] = []
    target = _render_value_or_todo(node.variable_value, prefix, todo)
    if todo:
        return todo
    special = _GET_ENVIRONMENT_VARIABLE_SPECIAL_PROPERTIES.get(name)
    if special is not None:
        return [f"{prefix}{target} = {special}"]
    return [f"{prefix}{target} = os.environ.get({name!r})"]


def _generate_set_environment_variable(
    node: SetEnvironmentVariableNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_set_environment_variable_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_set_environment_variable_body(
    node: SetEnvironmentVariableNode, indent: int
) -> list[str]:
    """知見223: `GetEnvironmentVariable`(知見215)と違い、常にOS環境
    変数として設定するだけで`System.Environment`既知プロパティ名との
    2経路判断が無い——`Name`が動的式でも曖昧さが無いため、`Get`側とは
    違い動的`Name`も問題なく対応できる。`os.environ[name] = value`に
    対応する(プロセス内スコープのみ、知見215と同種の判断)。"""
    prefix = INDENT * indent
    if node.name is None or node.value is None:
        return [
            f"{prefix}# TODO: SetEnvironmentVariable with missing Name/Value"
        ]
    todo: list[str] = []
    name = _render_value_or_todo(node.name, prefix, todo)
    value = _render_value_or_todo(node.value, prefix, todo)
    if todo:
        return todo
    return [
        f"{prefix}os.environ[{VB_CSTR_HELPER_NAME}({name})] = "
        f"{VB_CSTR_HELPER_NAME}({value})"
    ]


# 知見254: `.NET Environment.SpecialFolder`は21個の値を持つが、実機で
# 確認できたのは3つのみ——それ以外はでっち上げず`# TODO`へ倒す。
_SPECIAL_FOLDER_PATH_EXPRS = {
    "UserProfile": "os.path.expanduser('~')",
    "Desktop": "os.path.join(os.path.expanduser('~'), 'Desktop')",
    "MyDocuments": "os.path.join(os.path.expanduser('~'), 'Documents')",
}


def _generate_get_environment_folder(
    node: GetEnvironmentFolderNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_get_environment_folder_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_get_environment_folder_body(
    node: GetEnvironmentFolderNode, indent: int
) -> list[str]:
    """知見254: `ui:GetEnvironmentFolder`——実機確認済みの3つの
    `SpecialFolder`値(`UserProfile`/`Desktop`/`MyDocuments`)のみ
    `os.path.expanduser("~")`+`os.path.join()`で対応する。"""
    prefix = INDENT * indent
    if node.folder_path is None:
        return [f"{prefix}# TODO: GetEnvironmentFolder with no FolderPath captured"]
    if node.special_folder not in _SPECIAL_FOLDER_PATH_EXPRS:
        return [
            f"{prefix}# TODO: GetEnvironmentFolder with SpecialFolder "
            f"{node.special_folder!r} — only the confirmed \"UserProfile\"/"
            '"Desktop"/"MyDocuments" values are implemented, refusing to guess'
        ]
    try:
        target = render_expr(node.folder_path)
    except NotImplementedError as e:
        return _todo_value(prefix, str(e))
    return [f"{prefix}{target} = {_SPECIAL_FOLDER_PATH_EXPRS[node.special_folder]}"]


def _generate_find_and_replace_text_modification_line(
    node: FindAndReplaceTextModificationNode, var_name: str, prefix: str
) -> list[str] | None:
    """知見224: `SearchText`はプレーンな文字列検索(正規表現ではない)
    ——`re.escape()`で特殊文字を無効化してから`re.sub()`を使う。
    `MatchCase`省略時は公式ドキュメント確認済みの既定`False`
    (大文字小文字を区別しない)として`re.IGNORECASE`を付ける。
    置換文字列は`lambda`経由で渡し、`\\1`等の.NET側に無い逆参照記法
    として`re.sub()`に誤解釈されないようにする。"""
    if node.search_text is None or node.replace_text is None:
        return None
    if node.match_case not in (None, "True", "False"):
        return None
    todo: list[str] = []
    search = _render_value_or_todo(node.search_text, prefix, todo)
    replace = _render_value_or_todo(node.replace_text, prefix, todo)
    if todo:
        return None
    flags = "" if node.match_case == "True" else ", flags=re.IGNORECASE"
    return [
        f"{prefix}{var_name} = re.sub(re.escape({VB_CSTR_HELPER_NAME}({search})), "
        f"lambda _m: {VB_CSTR_HELPER_NAME}({replace}), {var_name}{flags})"
    ]


def _generate_to_upper_lower_text_modification_line(
    node: ToUpperLowerTextModificationNode, var_name: str, prefix: str
) -> list[str] | None:
    if node.modification_type == "Lowercase":
        return [f"{prefix}{var_name} = {var_name}.lower()"]
    if node.modification_type == "Uppercase":
        return [f"{prefix}{var_name} = {var_name}.upper()"]
    return None


def _generate_modify_text_child_lines(
    child: Node, var_name: str, prefix: str
) -> list[str] | None:
    if isinstance(child, FindAndReplaceTextModificationNode):
        return _generate_find_and_replace_text_modification_line(
            child, var_name, prefix
        )
    if isinstance(child, TrimTextModificationNode):
        return [f"{prefix}{var_name} = {var_name}.strip()"]
    if isinstance(child, ToUpperLowerTextModificationNode):
        return _generate_to_upper_lower_text_modification_line(child, var_name, prefix)
    return None


def _generate_modify_text(node: ModifyTextNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_modify_text_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_modify_text_body(node: ModifyTextNode, indent: int) -> list[str]:
    """知見224: `SourceText`を起点に`body`内の各子活動
    (`FindAndReplaceTextModification`/`TrimTextModification`/
    `ToUpperLowerTextModification`)を順番に適用し`OutputText`へ
    代入する——`ExcelApplicationScope`のようなリソース/接続スコープ
    ではなく文字列を線形に通す単純な処理。未対応の子活動
    (`CombineTextModification`等、実機ヒット0件のため未対応)や
    未確認の設定値が1つでもあれば、途中の変換だけ欠落した誤った
    文字列を`OutputText`へ渡してしまわないよう、活動全体を
    `# TODO`へ倒す(部分適用はしない)。"""
    prefix = INDENT * indent
    if node.source_text is None or node.output_text is None:
        return [f"{prefix}# TODO: ModifyText with missing SourceText/OutputText"]
    todo: list[str] = []
    source_text = _render_value_or_todo(node.source_text, prefix, todo)
    output_text = _render_value_or_todo(node.output_text, prefix, todo)
    if todo:
        return todo
    lines = [f"{prefix}_mod_text = {VB_CSTR_HELPER_NAME}({source_text})"]
    for child in node.body:
        child_lines = _generate_modify_text_child_lines(child, "_mod_text", prefix)
        if child_lines is None:
            return [
                f"{prefix}# TODO: ModifyText with unsupported or unconfirmed "
                f"child modification ({type(child).__name__})"
            ]
        lines.extend(child_lines)
    lines.append(f"{prefix}{output_text} = _mod_text")
    return lines


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


def _generate_get_from_clipboard(node: GetFromClipboardNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_get_from_clipboard_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_get_from_clipboard_body(node: GetFromClipboardNode, indent: int) -> list[str]:
    """知見243: `ui:GetFromClipboard`——`SetToClipboard`の逆方向、
    `pyperclip.paste()`に対応する。`Result`(代入先)は`Assign.target`
    (知見136・137)・`DeserializeJson.JsonObject`(知見241)と同じ厳格な
    失敗モード——`render_expr`を直接呼び、例外発生時は代入文自体を
    生成しない。`TimeoutMS`はUI Automation系活動一般の実行タイムアウト
    概念(クリップボードのポーリング待機ではない)で、`pyperclip.
    paste()`に対応するタイムアウト概念自体が存在しないため意図的に
    モデル化しない。"""
    prefix = INDENT * indent
    if node.result is None:
        return [f"{prefix}# TODO: GetFromClipboard with no Result captured"]
    try:
        target = render_expr(node.result)
    except NotImplementedError as e:
        return _todo_value(prefix, str(e))
    return [f"{prefix}{target} = pyperclip.paste()"]


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


# 知見173: `ui:MaximizeWindow`/`ui:MinimizeWindow`/`ui:RestoreWindow`。
# 属性構成が完全に同一(`Window`+`DisplayName`/`ContinueOnError`)な
# 3つの同義の兄弟活動——pywinautoで呼ぶメソッド名(`maximize()`/
# `minimize()`/`restore()`)だけが違うため、`WindowStateNode.method`
# で1つの生成関数に統合する。`Window`が`{x:Null}`の場合は「現在
# アクティブなウィンドウ」を指す——pywinautoの`active_only=True`
# (`GetGUIThreadInfo()`でOS全体のアクティブウィンドウを取得、確認済み
# 標準API)で対応する。
def _generate_window_state(node: WindowStateNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_window_state_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_window_state_body(node: WindowStateNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.window is not None:
        return [
            f"{prefix}# TODO: {node.method.capitalize()}Window with Window set "
            f"({_describe_expr_for_comment(node.window)}) — Window object "
            "reference not modeled, refusing to guess"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: {node.method.capitalize()}Window with "
            f"ContinueOnError set ({_describe_expr_for_comment(node.continue_on_error)}) "
            "— error-continuation mapping not confirmed, refusing to guess"
        ]
    return [f'{prefix}Desktop(backend="uia").window(active_only=True).{node.method}()']


# 知見174: `ui:GetAttribute`(GitHub code searchで274件ヒット)。
# `Attribute`は開放的な語彙(`"checked"`/`"innerText"`/
# `"relativeVisibility"`等、UiPathのブラウザ拡張がDOM/アクセシビリティ
# ツリーから取得する)で、pywinauto(Win32/UIAバックエンドのみ、ブラウザの
# JS/DOM注入機能を持たない)側にこれを安全に代替できる汎用APIが存在しない
# ——`Attribute`の値を問わず常に`# TODO`へ倒す(知見38の`role`属性と同じ
# 「VM実機検証なしに新しいマッピングを追加しない」という安全側の判断)。
# 知見197: `ui:GenerateDataTable`。既存のDataTableを読まず新規に構築
# するため、出力は知見183以来のdict行表現で統一できる(知見179の
# 表現非統一性問題を回避、知見196の`LookupDataTable`と同じ利点)。
# `CSVParsing="True"`は`csv.DictReader`(`ReadCsvFile`知見185と同じ、
# 引用符付きフィールドに対応)、`"False"`は単純な`str.split()`で
# 対応する。固定幅モード(`Positions`/`ColumnSizes`)・
# `UseColumnHeader`が`"True"`以外・`AutoDetectTypes="True"`は実機未確認
# のため常に`# TODO`へ倒す。
def _generate_generate_data_table(node: GenerateDataTableNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_generate_data_table_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_generate_data_table_body(
    node: GenerateDataTableNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    if node.input is None or node.data_table is None:
        return [f"{prefix}# TODO: GenerateDataTable with missing Input/DataTable"]
    if node.positions is not None or node.column_sizes is not None:
        return [
            f"{prefix}# TODO: GenerateDataTable with Positions/ColumnSizes "
            "set — fixed-width column mode not confirmed in real "
            "samples, refusing to guess"
        ]
    if node.use_column_header != "True":
        return [
            f"{prefix}# TODO: GenerateDataTable with UseColumnHeader not "
            f"set to True ({node.use_column_header!r}) — only the header-"
            "row case is confirmed, refusing to guess"
        ]
    if node.auto_detect_types == "True":
        return [
            f"{prefix}# TODO: GenerateDataTable with AutoDetectTypes=True "
            "— type-inference semantics not confirmed, refusing to guess"
        ]
    if node.column_separators is None:
        return [f"{prefix}# TODO: GenerateDataTable with no ColumnSeparators captured"]
    if (
        isinstance(node.column_separators, Literal)
        and len(node.column_separators.value) != 1
    ):
        return [
            f"{prefix}# TODO: GenerateDataTable with multi-character "
            f"ColumnSeparators ({node.column_separators.value!r}) — "
            "csv module requires a single-character delimiter, refusing "
            "to guess"
        ]
    if node.new_line_separator is not None and not (
        isinstance(node.new_line_separator, Literal)
        and node.new_line_separator.value == "\n"
    ):
        return [
            f"{prefix}# TODO: GenerateDataTable with non-default "
            "NewLineSeparator — only the implicit default/literal "
            '"\\n" case is confirmed, refusing to guess'
        ]
    if node.csv_parsing not in ("True", "False"):
        return [
            f"{prefix}# TODO: GenerateDataTable with unrecognized/unset "
            f"CSVParsing ({node.csv_parsing!r}) — refusing to guess"
        ]
    todo: list[str] = []
    input_text = _render_value_or_todo(node.input, prefix, todo)
    target = _render_value_or_todo(node.data_table, prefix, todo)
    sep = _render_value_or_todo(node.column_separators, prefix, todo)
    if todo:
        return todo
    if node.csv_parsing == "True":
        return [
            f"{prefix}{target} = list(csv.DictReader(io.StringIO({input_text}), "
            f"delimiter={sep}))"
        ]
    return [
        f"{prefix}_gdt_header, *_gdt_rows = "
        f"[_l.split({sep}) for _l in {input_text}.splitlines() if _l]",
        f"{prefix}{target} = [dict(zip(_gdt_header, _row)) for _row in _gdt_rows]",
    ]


def _generate_get_attribute(node: GetAttributeNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_get_attribute_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_get_attribute_body(node: GetAttributeNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if not node.selector:
        return [f"{prefix}# TODO: GetAttribute with no selector captured"]
    if node.result is None:
        return [f"{prefix}# TODO: GetAttribute with no output Result captured"]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: GetAttribute with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    attribute_desc = f"Attribute={node.attribute!r}" if node.attribute else "no Attribute set"
    return [
        f"{prefix}# TODO: GetAttribute ({attribute_desc}) — no pywinauto/UIA "
        "equivalent confirmed for arbitrary DOM/accessibility attribute "
        "retrieval, refusing to guess"
    ]


# 知見176: `ui:GetPassword`。`ProtectedPassword`はWindows DPAPI
# (`CryptProtectData`)で暗号化されており、暗号化したWindowsユーザー・
# マシンの組み合わせでなければ復号できない——移植可能な形で安全に復号
# する方法が無いため常に`# TODO`へ倒す。資格情報を扱う機微な操作である
# ため、`ProtectedPassword`の値自体は生成コードのコメントへ一切出力
# しない。
def _generate_get_password(node: GetPasswordNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_get_password_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_get_password_body(node: GetPasswordNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.result is None:
        return [f"{prefix}# TODO: GetPassword with no output Result captured"]
    return [
        f"{prefix}# TODO: GetPassword — ProtectedPassword is a Windows "
        "DPAPI-encrypted blob tied to the original Windows user/machine "
        "(CryptProtectData), cannot be decrypted portably, refusing to guess"
    ]


# 知見248: `win32cred.CredRead()`は見つからない場合に`None`を返すのでは
# なく`pywintypes.error`(`winerror=1168`、`ERROR_NOT_FOUND`)を投げる
# ことをWebSearch経由で独立に確認済み(`GetSecureCredentialNode`の
# docstring参照)——この例外を`None`へ変換するヘルパーを注入する。
_WIN32_CRED_READ_HELPER_NAME = "_win32_cred_read"
_WIN32_CRED_READ_HELPER_SOURCE = '''\
def _win32_cred_read(target_name, cred_type):
    try:
        return win32cred.CredRead(Type=cred_type, TargetName=target_name)
    except pywintypes.error as e:
        if e.winerror == 1168:
            return None
        raise
'''

_CREDENTIAL_TYPE_CONSTANTS = {"Generic": "win32cred.CRED_TYPE_GENERIC"}
_PERSISTANCE_TYPE_CONSTANTS = {"Enterprise": "win32cred.CRED_PERSIST_ENTERPRISE"}


def _generate_get_secure_credential(node: GetSecureCredentialNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_get_secure_credential_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_get_secure_credential_body(
    node: GetSecureCredentialNode, indent: int
) -> list[str]:
    """知見248: `ui:GetSecureCredential`——`win32cred.CredRead()`に
    対応する(`pywin32`、本プロジェクト既存の確認済み依存)。
    `CredentialBlob`はUTF-16(`utf-16-le`)エンコード済みの生バイト
    として返るため`.decode("utf-16-le")`する。"""
    prefix = INDENT * indent
    if node.target is None:
        return [f"{prefix}# TODO: GetSecureCredential with no Target captured"]
    if node.credential_type not in (None, "Generic"):
        return [
            f"{prefix}# TODO: GetSecureCredential with CredentialType "
            f"{node.credential_type!r} — only the confirmed \"Generic\" "
            "value is implemented, refusing to guess"
        ]
    if node.persistance_type not in (None, "Enterprise"):
        return [
            f"{prefix}# TODO: GetSecureCredential with PersistanceType "
            f"{node.persistance_type!r} — only the confirmed \"Enterprise\" "
            "value is implemented, refusing to guess"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: GetSecureCredential with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    try:
        target = render_expr(node.target)
    except NotImplementedError as e:
        return _todo_value(prefix, str(e))
    targets: dict[str, str] = {}
    for label, expr in (("result", node.result), ("username", node.username), ("password", node.password)):
        if expr is None:
            continue
        try:
            targets[label] = render_expr(expr)
        except NotImplementedError as e:
            return _todo_value(prefix, str(e))
    lines = [
        f"{prefix}_cred = {_WIN32_CRED_READ_HELPER_NAME}({VB_CSTR_HELPER_NAME}({target}), "
        f"{_CREDENTIAL_TYPE_CONSTANTS['Generic']})",
        f"{prefix}if _cred is not None:",
    ]
    inner = INDENT * (indent + 1)
    if "result" in targets:
        lines.append(f"{inner}{targets['result']} = True")
    if "username" in targets:
        lines.append(f"{inner}{targets['username']} = _cred['UserName']")
    if "password" in targets:
        lines.append(f"{inner}{targets['password']} = _cred['CredentialBlob'].decode('utf-16-le')")
    if len(lines) == 2:
        lines.append(f"{inner}pass")
    if "result" in targets:
        lines.append(f"{prefix}else:")
        lines.append(f"{inner}{targets['result']} = False")
    return lines


def _generate_add_credential(node: AddCredentialNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_add_credential_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_add_credential_body(node: AddCredentialNode, indent: int) -> list[str]:
    """知見248: `ui:AddCredential`——`win32cred.CredWrite()`に対応する。
    `CredentialBlob`は`GetSecureCredential`と対になる`.encode(
    "utf-16-le")`でエンコードする。"""
    prefix = INDENT * indent
    if node.target is None or node.username is None or node.password is None:
        return [
            f"{prefix}# TODO: AddCredential with missing Target/Username/"
            "Password"
        ]
    if node.secure_password is not None:
        return [
            f"{prefix}# TODO: AddCredential with SecurePassword set "
            f"({_describe_expr_for_comment(node.secure_password)}) — only "
            "the confirmed plain Password input is implemented, refusing "
            "to guess"
        ]
    if node.result is not None:
        return [
            f"{prefix}# TODO: AddCredential with Result output bound "
            f"({_describe_expr_for_comment(node.result)}) — write-failure "
            "semantics not confirmed in the wild, refusing to guess"
        ]
    if node.credential_type not in (None, "Generic"):
        return [
            f"{prefix}# TODO: AddCredential with CredentialType "
            f"{node.credential_type!r} — only the confirmed \"Generic\" "
            "value is implemented, refusing to guess"
        ]
    if node.persistance_type not in (None, "Enterprise"):
        return [
            f"{prefix}# TODO: AddCredential with PersistanceType "
            f"{node.persistance_type!r} — only the confirmed \"Enterprise\" "
            "value is implemented, refusing to guess"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: AddCredential with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    todo: list[str] = []
    target = _render_value_or_todo(node.target, prefix, todo)
    username = _render_value_or_todo(node.username, prefix, todo)
    password = _render_value_or_todo(node.password, prefix, todo)
    if todo:
        return todo
    return [
        f"{prefix}win32cred.CredWrite({{",
        f"{INDENT * (indent + 1)}'Type': {_CREDENTIAL_TYPE_CONSTANTS['Generic']},",
        f"{INDENT * (indent + 1)}'TargetName': {VB_CSTR_HELPER_NAME}({target}),",
        f"{INDENT * (indent + 1)}'UserName': {VB_CSTR_HELPER_NAME}({username}),",
        f"{INDENT * (indent + 1)}'CredentialBlob': {VB_CSTR_HELPER_NAME}({password}).encode('utf-16-le'),",
        f"{INDENT * (indent + 1)}'Persist': {_PERSISTANCE_TYPE_CONSTANTS['Enterprise']},",
        f"{prefix}}}, 0)",
    ]


def _generate_request_credential(node: RequestCredentialNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_request_credential_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_request_credential_body(node: RequestCredentialNode, indent: int) -> list[str]:
    """知見248: `ui:RequestCredential`——`InputDialogNode`(知見131)の
    「`input()`はダイアログへの直接対応」判断を継承する
    (`Username`→`input()`、`Password`→`getpass.getpass()`)。`Result`
    (Cancel判定)はブロッキング`input()`に対応概念が無いため、束縛
    されていれば常に`True`を代入する(近似、ノードdocstring参照)。"""
    prefix = INDENT * indent
    if node.username is None or node.password is None:
        return [
            f"{prefix}# TODO: RequestCredential with missing Username/"
            "Password output binding"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: RequestCredential with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    try:
        username_target = render_expr(node.username)
        password_target = render_expr(node.password)
    except NotImplementedError as e:
        return _todo_value(prefix, str(e))
    result_target: str | None = None
    if node.result is not None:
        try:
            result_target = render_expr(node.result)
        except NotImplementedError as e:
            return _todo_value(prefix, str(e))
    todo: list[str] = []
    lines: list[str] = []
    if node.message is not None:
        message = _render_value_or_todo(node.message, prefix, todo)
        lines.append(f"{prefix}print({VB_CSTR_HELPER_NAME}({message}))")
    if todo:
        return todo
    lines.append(f"{prefix}{username_target} = input('Username: ')")
    lines.append(f"{prefix}{password_target} = getpass.getpass('Password: ')")
    if result_target is not None:
        lines.append(f"{prefix}{result_target} = True")
    return lines


# 知見253: `win32cred.CredRead()`の生の戻り値(dict、`UserName`/
# `CredentialBlob`キー)に対し、実機2件とも確認した`.Username`/
# `.Password`のドット記法アクセスを可能にする薄いラッパー
# (`_ImapMailMessage`(知見250)と同じ判断クラス)。
_WIN32_CREDENTIAL_HELPER_NAME = "_Win32Credential"
_WIN32_CREDENTIAL_HELPER_SOURCE = '''\
class _Win32Credential:
    def __init__(self, cred):
        self.Username = cred["UserName"]
        self.Password = cred["CredentialBlob"].decode("utf-16-le")
'''


def _generate_get_username_password_x(node: GetUsernamePasswordXNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_get_username_password_x_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_get_username_password_x_body(
    node: GetUsernamePasswordXNode, indent: int
) -> list[str]:
    """知見253: `uas:GetUsernamePasswordX`——`GetSecureCredentialNode`
    (知見248)が確立した`win32cred.CredRead()`基盤を再利用するが、
    本活動には`Result`出力が存在せず資格情報が見つからない場合の
    挙動も未確認のため、`_win32_cred_read()`ヘルパー(例外を`None`へ
    変換)は使わず`win32cred.CredRead()`を直接呼び`pywintypes.error`
    を素通りさせる。"""
    prefix = INDENT * indent
    if node.credential is None:
        return [f"{prefix}# TODO: GetUsernamePasswordX with no Credential output captured"]
    if node.credentials_source not in (None, "CredentialsManager"):
        return [
            f"{prefix}# TODO: GetUsernamePasswordX with CredentialsSource "
            f"{node.credentials_source!r} — only the confirmed "
            '"CredentialsManager" value is implemented, refusing to guess'
        ]
    if node.orchestrator_credential_name is not None:
        return [
            f"{prefix}# TODO: GetUsernamePasswordX with OrchestratorCredentialName set "
            f"({_describe_expr_for_comment(node.orchestrator_credential_name)}) — "
            "Orchestrator-backed credential lookup not supported"
        ]
    if node.credential_name is None:
        return [f"{prefix}# TODO: GetUsernamePasswordX with no CredentialName captured"]
    try:
        target = render_expr(node.credential)
    except NotImplementedError as e:
        return _todo_value(prefix, str(e))
    todo: list[str] = []
    credential_name = _render_value_or_todo(node.credential_name, prefix, todo)
    if todo:
        return todo
    return [
        f"{prefix}{target} = {_WIN32_CREDENTIAL_HELPER_NAME}(win32cred.CredRead("
        f"Type={_CREDENTIAL_TYPE_CONSTANTS['Generic']}, "
        f"TargetName={VB_CSTR_HELPER_NAME}({credential_name})))",
    ]


# 知見178: `ui:LoadImage`(GitHub code searchで58件ヒット、OCR系活動の
# 入力として使われる)。`FileName`で指定した画像ファイルを読み込み
# `Image`へ代入する——Pillow(`PIL.Image.open()`)が標準でサポートする
# 操作そのもので、`pad_codegen`で既にPillowを確認済みの依存として
# 使っているため新しい依存の追加判断は不要。
def _generate_load_image(node: LoadImageNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_load_image_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_load_image_body(node: LoadImageNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.file_name is None:
        return [f"{prefix}# TODO: LoadImage with no FileName captured"]
    if node.image is None:
        return [f"{prefix}# TODO: LoadImage with no output Image captured"]
    todo: list[str] = []
    file_name = _render_value_or_todo(node.file_name, prefix, todo)
    target = _render_value_or_todo(node.image, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}{target} = PIL.Image.open({file_name})"]


# 知見196: `ui:LookupDataTable`。単一セル値+単一行インデックスだけを
# 返すため、知見179のDataTable表現非統一性問題の影響を受けにくい——
# `row[column_name]`という名前ベースアクセス(知見183の`GetRowItem`の
# `ColumnName`分岐と同じ、dict行を前提にした素直な実装)で対応する。
# 見つからない場合`RowIndex`は`-1`(公式ドキュメントで確認済み、Excel
# のVLOOKUPに類似)。
def _generate_lookup_data_table(node: LookupDataTableNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_lookup_data_table_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_lookup_data_table_body(node: LookupDataTableNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.data_table is None or node.lookup_value is None:
        return [f"{prefix}# TODO: LookupDataTable with missing DataTable/LookupValue"]
    if node.cell_value is None and node.row_index is None:
        return [f"{prefix}# TODO: LookupDataTable with no output CellValue/RowIndex captured"]
    if node.lookup_data_column is not None or node.target_data_column is not None:
        return [
            f"{prefix}# TODO: LookupDataTable with LookupDataColumn/"
            "TargetDataColumn set — DataColumn object reference not "
            "modeled, refusing to guess"
        ]
    if node.lookup_column_index is not None or node.target_column_index is not None:
        return [
            f"{prefix}# TODO: LookupDataTable with LookupColumnIndex/"
            "TargetColumnIndex set — column-index-based lookup not "
            "confirmed in real samples, refusing to guess"
        ]
    if node.lookup_column_name is None or node.target_column_name is None:
        return [
            f"{prefix}# TODO: LookupDataTable with missing LookupColumnName/"
            "TargetColumnName"
        ]
    todo: list[str] = []
    data_table = _render_value_or_todo(node.data_table, prefix, todo)
    lookup_column_name = _render_value_or_todo(node.lookup_column_name, prefix, todo)
    lookup_value = _render_value_or_todo(node.lookup_value, prefix, todo)
    target_column_name = _render_value_or_todo(node.target_column_name, prefix, todo)
    if todo:
        return todo
    lines = [
        f"{prefix}_lookup_row_index = -1",
        f"{prefix}_lookup_cell_value = None",
        f"{prefix}for _lookup_i, _lookup_row in enumerate({data_table}):",
        f"{prefix}{INDENT}if _lookup_row[{lookup_column_name}] == {lookup_value}:",
        f"{prefix}{INDENT * 2}_lookup_row_index = _lookup_i",
        f"{prefix}{INDENT * 2}_lookup_cell_value = _lookup_row[{target_column_name}]",
        f"{prefix}{INDENT * 2}break",
    ]
    if node.row_index is not None:
        row_index = _render_value_or_todo(node.row_index, prefix, todo)
        if todo:
            return todo
        lines.append(f"{prefix}{row_index} = _lookup_row_index")
    if node.cell_value is not None:
        cell_value = _render_value_or_todo(node.cell_value, prefix, todo)
        if todo:
            return todo
        lines.append(f"{prefix}{cell_value} = _lookup_cell_value")
    return lines


_SORT_DATA_TABLE_ORDERS = {"Ascending": False, "Descending": True, "Decending": True}


def _generate_sort_data_table(node: SortDataTableNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_sort_data_table_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_sort_data_table_body(node: SortDataTableNode, indent: int) -> list[str]:
    """知見206: `ColumnName`指定+対象`DataTable`がdict行と確認できる
    場合のみ対応する。`ColumnIndex`/`DataColumn`は実機で非`{x:Null}`の
    実例が無いため常に`# TODO`(知見196の`LookupDataTable`と同じ判断)。
    `ScopeInfo.data_table_columns`に登録が無い場合、list行の可能性を
    排除できないため`# TODO`へ倒す(知見205と同じ「表現非依存で安全という
    思い込みが実行時バグになる」教訓の適用)。"""
    prefix = INDENT * indent
    if node.data_table is None or node.output_data_table is None:
        return [
            f"{prefix}# TODO: SortDataTable with missing DataTable/"
            "OutputDataTable"
        ]
    if node.data_column is not None:
        return [
            f"{prefix}# TODO: SortDataTable with DataColumn set — "
            "DataColumn object reference not modeled, refusing to guess"
        ]
    if node.column_index is not None:
        return [
            f"{prefix}# TODO: SortDataTable with ColumnIndex set — "
            "column-index-based sort not confirmed in real samples, "
            "refusing to guess"
        ]
    if node.column_name is None:
        return [f"{prefix}# TODO: SortDataTable with missing ColumnName"]
    if node.sort_order not in _SORT_DATA_TABLE_ORDERS:
        return [
            f"{prefix}# TODO: SortDataTable with unrecognized SortOrder/"
            f"Order ({node.sort_order!r}) — refusing to guess"
        ]
    if not isinstance(node.data_table, VbExpr):
        return [
            f"{prefix}# TODO: SortDataTable with non-identifier DataTable "
            "— row representation cannot be confirmed, refusing to guess"
        ]
    scope = get_active_scope()
    if scope is None or not scope.data_table_columns.get(node.data_table.text.lower()):
        return [
            f"{prefix}# TODO: SortDataTable — DataTable's row "
            "representation (dict vs list) could not be confirmed via "
            "BuildDataTable with a parsed column schema, refusing to guess"
        ]
    todo: list[str] = []
    data_table = _render_value_or_todo(node.data_table, prefix, todo)
    output_data_table = _render_value_or_todo(node.output_data_table, prefix, todo)
    column_name = _render_value_or_todo(node.column_name, prefix, todo)
    if todo:
        return todo
    reverse = _SORT_DATA_TABLE_ORDERS[node.sort_order]
    return [
        f"{prefix}{output_data_table} = sorted({data_table}, "
        f"key=lambda _row: _row[{column_name}], reverse={reverse})"
    ]


_FILTER_DATA_TABLE_BOOLEAN_OPERATORS = {"And"}
_FILTER_DATA_TABLE_BINARY_OPERATORS = {"EQ": "==", "GTE": ">="}
_FILTER_DATA_TABLE_UNARY_OPERATORS = {"EMPTY"}


def _generate_filter_data_table(node: FilterDataTableNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_filter_data_table_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_filter_data_table_body(node: FilterDataTableNode, indent: int) -> list[str]:
    """知見207: `ColumnName`/`SelectColumns`投影は未対応——`Filters`
    条件(`BooleanOperator="And"`+`Operator`∈{EQ,GTE,EMPTY}、実機確認
    済みの3値のみ)のみに対応する。`SortDataTable`(知見206)と同じ
    `ScopeInfo.data_table_columns`で対象`DataTable`がdict行と確認
    できる場合に限る。"""
    prefix = INDENT * indent
    if node.data_table is None or node.output_data_table is None:
        return [
            f"{prefix}# TODO: FilterDataTable with missing DataTable/"
            "OutputDataTable"
        ]
    if node.filter_rows_mode not in ("Keep", "Remove"):
        return [
            f"{prefix}# TODO: FilterDataTable with unrecognized "
            f"FilterRowsMode ({node.filter_rows_mode!r}) — refusing to guess"
        ]
    if node.select_columns:
        return [
            f"{prefix}# TODO: FilterDataTable with SelectColumns set — "
            "column projection not yet implemented, refusing to guess"
        ]
    if not node.filters:
        return [f"{prefix}# TODO: FilterDataTable with no Filters captured"]
    if not isinstance(node.data_table, VbExpr):
        return [
            f"{prefix}# TODO: FilterDataTable with non-identifier "
            "DataTable — row representation cannot be confirmed, "
            "refusing to guess"
        ]
    scope = get_active_scope()
    columns = (
        scope.data_table_columns.get(node.data_table.text.lower()) if scope else None
    )
    if not columns:
        return [
            f"{prefix}# TODO: FilterDataTable — DataTable's row "
            "representation (dict vs list) could not be confirmed via "
            "BuildDataTable with a parsed column schema, refusing to guess"
        ]
    todo: list[str] = []
    conditions: list[str] = []
    for filt in node.filters:
        if filt.boolean_operator not in _FILTER_DATA_TABLE_BOOLEAN_OPERATORS:
            return [
                f"{prefix}# TODO: FilterDataTable with BooleanOperator "
                f"{filt.boolean_operator!r} — only 'And' confirmed, "
                "refusing to guess"
            ]
        if (
            filt.operator not in _FILTER_DATA_TABLE_BINARY_OPERATORS
            and filt.operator not in _FILTER_DATA_TABLE_UNARY_OPERATORS
        ):
            return [
                f"{prefix}# TODO: FilterDataTable with Operator "
                f"{filt.operator!r} — not confirmed in real samples, "
                "refusing to guess"
            ]
        if filt.column is None:
            return [f"{prefix}# TODO: FilterDataTable with missing filter Column"]
        if filt.column_type == "x:Int32":
            col_index = _render_value_or_todo(filt.column, prefix, todo)
            # `Literal`は常に文字列として保持されるため、知見182の
            # `RemoveDataRow`と同じ`round(_vb_cdbl(x))`経由で整数化する
            # (素の文字列をlistインデックスに使うとTypeErrorになる)。
            col_access = f"{columns!r}[round({VB_CDBL_HELPER_NAME}({col_index}))]"
        elif filt.column_type == "x:String":
            col_access = _render_value_or_todo(filt.column, prefix, todo)
        else:
            return [
                f"{prefix}# TODO: FilterDataTable with unrecognized filter "
                f"Column type ({filt.column_type!r}) — refusing to guess"
            ]
        if filt.operator in _FILTER_DATA_TABLE_UNARY_OPERATORS:
            conditions.append(f"(_frow[{col_access}] in (None, ''))")
        else:
            if filt.operand is None:
                return [
                    f"{prefix}# TODO: FilterDataTable with missing Operand "
                    f"for Operator {filt.operator!r}"
                ]
            operand = _render_value_or_todo(filt.operand, prefix, todo)
            op_py = _FILTER_DATA_TABLE_BINARY_OPERATORS[filt.operator]
            conditions.append(f"(_frow[{col_access}] {op_py} {operand})")
    if todo:
        return todo
    data_table = _render_value_or_todo(node.data_table, prefix, todo)
    output_data_table = _render_value_or_todo(node.output_data_table, prefix, todo)
    if todo:
        return todo
    cond_expr = " and ".join(conditions)
    if node.filter_rows_mode == "Remove":
        cond_expr = f"not ({cond_expr})"
    return [
        f"{prefix}{output_data_table} = [_frow for _frow in {data_table} "
        f"if {cond_expr}]"
    ]


def _dedupe_join_columns(cols1: list[str], cols2: list[str]) -> list[str]:
    """知見208: `JoinDataTables`の出力列重複名解決規則(公式ドキュメント
    `docs.uipath.com/activities/other/latest/workflow/join-data-tables`
    で確認)——`DataTable2`側の列が`DataTable1`(または既にリネーム済み
    の他の`DataTable2`列)と同名の場合、`_1`→`_2`→...という未使用の
    連番サフィックスを付与する。`cols1`/`cols2`はコード生成時に`ScopeInfo`
    から静的に分かっているため、この解決自体もコード生成時にPythonで
    計算し、結果の列名リストを生成コードへリテラルとして埋め込む
    (実行時の解決コードは不要)。"""
    used = set(cols1)
    result: list[str] = []
    for col in cols2:
        name = col
        n = 1
        while name in used:
            name = f"{col}_{n}"
            n += 1
        used.add(name)
        result.append(name)
    return result


def _generate_join_data_tables(node: JoinDataTablesNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_join_data_tables_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_join_data_tables_body(node: JoinDataTablesNode, indent: int) -> list[str]:
    """知見208: `JoinType="Inner"`(実機3件全てで確認、`"Left"`/`"Full"`
    は公式ドキュメントに記載はあるが実機未確認のため未対応)+
    `Operator="EQ"`(実機確認済みの唯一の値)のみに対応する。知見206/207
    と同じ`ScopeInfo.data_table_columns`で`DataTable1`/`DataTable2`両方が
    dict行と確認できる場合に限る。"""
    prefix = INDENT * indent
    if (
        node.data_table1 is None
        or node.data_table2 is None
        or node.output_data_table is None
    ):
        return [
            f"{prefix}# TODO: JoinDataTables with missing DataTable1/"
            "DataTable2/OutputDataTable"
        ]
    if node.join_type != "Inner":
        return [
            f"{prefix}# TODO: JoinDataTables with JoinType "
            f"{node.join_type!r} — only 'Inner' confirmed in real "
            "samples, refusing to guess"
        ]
    if not node.arguments:
        return [f"{prefix}# TODO: JoinDataTables with no Arguments captured"]
    if not isinstance(node.data_table1, VbExpr) or not isinstance(
        node.data_table2, VbExpr
    ):
        return [
            f"{prefix}# TODO: JoinDataTables with non-identifier "
            "DataTable1/DataTable2 — row representation cannot be "
            "confirmed, refusing to guess"
        ]
    scope = get_active_scope()
    cols1 = (
        scope.data_table_columns.get(node.data_table1.text.lower()) if scope else None
    )
    cols2 = (
        scope.data_table_columns.get(node.data_table2.text.lower()) if scope else None
    )
    if not cols1 or not cols2:
        return [
            f"{prefix}# TODO: JoinDataTables — DataTable1/DataTable2's "
            "row representation (dict vs list) could not be confirmed "
            "via BuildDataTable with a parsed column schema, refusing "
            "to guess"
        ]
    todo: list[str] = []
    conditions: list[str] = []
    for arg in node.arguments:
        if arg.boolean_operator != "And":
            return [
                f"{prefix}# TODO: JoinDataTables with BooleanOperator "
                f"{arg.boolean_operator!r} — only 'And' confirmed, "
                "refusing to guess"
            ]
        if arg.operator != "EQ":
            return [
                f"{prefix}# TODO: JoinDataTables with Operator "
                f"{arg.operator!r} — only 'EQ' confirmed in real "
                "samples, refusing to guess"
            ]
        if arg.column1 is None or arg.column2 is None:
            return [
                f"{prefix}# TODO: JoinDataTables with missing Column1/Column2"
            ]
        if arg.column1_type != "x:String" or arg.column2_type != "x:String":
            return [
                f"{prefix}# TODO: JoinDataTables with Column1/Column2 "
                f"type other than x:String ({arg.column1_type!r}/"
                f"{arg.column2_type!r}) — not confirmed in real "
                "samples, refusing to guess"
            ]
        col1 = _render_value_or_todo(arg.column1, prefix, todo)
        col2 = _render_value_or_todo(arg.column2, prefix, todo)
        conditions.append(f"(_jrow1[{col1}] == _jrow2[{col2}])")
    if todo:
        return todo
    data_table1 = _render_value_or_todo(node.data_table1, prefix, todo)
    data_table2 = _render_value_or_todo(node.data_table2, prefix, todo)
    output_data_table = _render_value_or_todo(node.output_data_table, prefix, todo)
    if todo:
        return todo
    renamed2 = _dedupe_join_columns(cols1, cols2)
    cond_expr = " and ".join(conditions)
    return [
        f"{prefix}{output_data_table} = [{{**_jrow1, **dict(zip("
        f"{renamed2!r}, [_jrow2[_jc] for _jc in {cols2!r}]))}} "
        f"for _jrow1 in {data_table1} for _jrow2 in {data_table2} "
        f"if {cond_expr}]"
    ]


def _generate_remove_duplicate_rows(
    node: RemoveDuplicateRowsNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_remove_duplicate_rows_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_remove_duplicate_rows_body(
    node: RemoveDuplicateRowsNode, indent: int
) -> list[str]:
    """知見214: 知見206-208と同じ`ScopeInfo.data_table_columns`で対象
    `DataTable`がdict行と確認できる場合のみ対応する。全列の値が完全
    一致する行を重複として除去し、最初に出現した行を残す。"""
    prefix = INDENT * indent
    if node.data_table is None or node.output_data_table is None:
        return [
            f"{prefix}# TODO: RemoveDuplicateRows with missing DataTable/"
            "OutputDataTable"
        ]
    if not isinstance(node.data_table, VbExpr):
        return [
            f"{prefix}# TODO: RemoveDuplicateRows with non-identifier "
            "DataTable — row representation cannot be confirmed, "
            "refusing to guess"
        ]
    scope = get_active_scope()
    columns = (
        scope.data_table_columns.get(node.data_table.text.lower()) if scope else None
    )
    if not columns:
        return [
            f"{prefix}# TODO: RemoveDuplicateRows — DataTable's row "
            "representation (dict vs list) could not be confirmed via "
            "BuildDataTable with a parsed column schema, refusing to guess"
        ]
    todo: list[str] = []
    data_table = _render_value_or_todo(node.data_table, prefix, todo)
    output_data_table = _render_value_or_todo(node.output_data_table, prefix, todo)
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    inner2 = INDENT * (indent + 2)
    return [
        f"{prefix}_rdr_seen = set()",
        f"{prefix}_rdr_result = []",
        f"{prefix}for _rdr_row in {data_table}:",
        f"{inner}_rdr_key = tuple(_rdr_row.values())",
        f"{inner}if _rdr_key not in _rdr_seen:",
        f"{inner2}_rdr_seen.add(_rdr_key)",
        f"{inner2}_rdr_result.append(_rdr_row)",
        f"{prefix}{output_data_table} = _rdr_result",
    ]


# 知見179: `ui:SaveImage`(`LoadImage`知見178の正反対)。`Image`
# (既存のPIL Imageオブジェクト変数)を`FileName`で指定したパスへ保存
# する——Pillowの`Image.save()`(`PIL.Image.open()`と対になる標準API)
# が直接対応する。
def _generate_save_image(node: SaveImageNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_save_image_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_save_image_body(node: SaveImageNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.file_name is None:
        return [f"{prefix}# TODO: SaveImage with no FileName captured"]
    if node.image is None:
        return [f"{prefix}# TODO: SaveImage with no Image captured"]
    todo: list[str] = []
    file_name = _render_value_or_todo(node.file_name, prefix, todo)
    image = _render_value_or_todo(node.image, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}{image}.save({file_name})"]


# 知見179: `ui:TakeScreenshot`(`UiPath/Community.Activities`公式
# リポジトリのREFramework標準テンプレート`TakeScreenshot.xaml`——知見
# 169の`KillAllProcesses.xaml`と同じ「REFramework標準サブワークフロー」
# カテゴリ)。`Target`が`{x:Null}`(画面全体)の場合はPillowの
# `ImageGrab.grab()`(引数無しで仮想スクリーン全体をキャプチャする
# 標準API)、セレクタが設定されている場合はpywinautoの
# `capture_as_image()`(`base_wrapper.py`で確認済み、`pad_codegen`側で
# 既に確認済みの依存)が対応する。`WaitBefore`(`DelayBefore`とは別名の
# 未確認属性)は意味論未確認のため非`{x:Null}`時は`# TODO`へ倒す。
def _generate_take_screenshot(node: TakeScreenshotNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_take_screenshot_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_take_screenshot_body(node: TakeScreenshotNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.screenshot is None:
        return [f"{prefix}# TODO: TakeScreenshot with no output Screenshot captured"]
    if node.wait_before is not None:
        return [
            f"{prefix}# TODO: TakeScreenshot with WaitBefore set "
            f"({_describe_expr_for_comment(node.wait_before)}) — semantics "
            "not confirmed (distinct attribute name from DelayBefore), "
            "refusing to guess"
        ]
    todo: list[str] = []
    target = _render_value_or_todo(node.screenshot, prefix, todo)
    if todo:
        return todo
    if not node.selector:
        return [f"{prefix}{target} = PIL.ImageGrab.grab()"]
    rendered = selector_text_to_pywinauto(node.selector)
    if rendered.expr == 'Desktop(backend="uia")':
        return [
            f"{prefix}# TODO: TakeScreenshot selector had no mappable "
            f"attributes: {node.selector}"
        ]
    lines = [f"{prefix}# WARNING: {w}" for w in rendered.warnings]
    lines.append(f"{prefix}{target} = {rendered.expr}.capture_as_image()")
    return lines


# 知見180: `ui:GetOCRText`。`OCREngine`デリゲートのタグが`ui:
# GoogleOCR`(UiPath公式ドキュメントで「Tesseract OCR」と確認済み
# ——内部クラス名が歴史的事情でそのまま)の場合のみ、本プロジェクトが
# 既に実機VM検証済みの依存`pytesseract`(`tests/test_ocr_fallback.py`)
# が直接対応する。`Language`(UiPath公式ドキュメントが明記する
# `tessdata`言語コードそのもの)は`lang`引数へそのまま渡せるが、
# 画像の前処理を変える他の属性(`Scale`/`Profile`/`AllowedCharacters`/
# `DeniedCharacters`/`Invert`/`ComputeSkewAngle`/`FilterRegion`)が
# 既定値から外れている場合、`ExtractWords`/`WordsInfo`(単語位置情報、
# 未モデル化)が使われている場合は`# TODO`へ倒す。`Target`が`{x:Null}`
# の場合は`TakeScreenshot`(知見179)と同じ`PIL.ImageGrab.grab()`で
# 画面全体を対象にする。
def _generate_get_ocr_text(node: GetOcrTextNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_get_ocr_text_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_get_ocr_text_body(node: GetOcrTextNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.engine_tag != "GoogleOCR":
        return [
            f"{prefix}# TODO: GetOCRText with OCREngine "
            f"{node.engine_tag!r} — only the Tesseract-backed GoogleOCR "
            "engine is confirmed, refusing to guess other engines"
        ]
    if node.text is None:
        return [f"{prefix}# TODO: GetOCRText with no output Text captured"]
    if node.words_info is not None:
        return [
            f"{prefix}# TODO: GetOCRText with WordsInfo bound "
            f"({_describe_expr_for_comment(node.words_info)}) — per-word "
            "position info not modeled, refusing to guess"
        ]
    if node.scale not in (None, "1"):
        return [
            f"{prefix}# TODO: GetOCRText with non-default Scale "
            f"({node.scale!r}) — image preprocessing not modeled, refusing "
            "to guess"
        ]
    if node.profile is not None:
        return [
            f"{prefix}# TODO: GetOCRText with Profile set ({node.profile!r}) "
            "— image preprocessing not modeled, refusing to guess"
        ]
    if node.allowed_characters is not None:
        return [
            f"{prefix}# TODO: GetOCRText with AllowedCharacters set "
            f"({_describe_expr_for_comment(node.allowed_characters)}) — "
            "character whitelisting not modeled, refusing to guess"
        ]
    if node.denied_characters is not None:
        return [
            f"{prefix}# TODO: GetOCRText with DeniedCharacters set "
            f"({_describe_expr_for_comment(node.denied_characters)}) — "
            "character blacklisting not modeled, refusing to guess"
        ]
    if node.invert not in (None, "False"):
        return [
            f"{prefix}# TODO: GetOCRText with non-default Invert "
            f"({node.invert!r}) — image preprocessing not modeled, refusing "
            "to guess"
        ]
    if node.compute_skew_angle not in (None, "False"):
        return [
            f"{prefix}# TODO: GetOCRText with non-default ComputeSkewAngle "
            f"({node.compute_skew_angle!r}) — image preprocessing not "
            "modeled, refusing to guess"
        ]
    if node.extract_words not in (None, "False"):
        return [
            f"{prefix}# TODO: GetOCRText with ExtractWords set "
            f"({node.extract_words!r}) — per-word output not modeled, "
            "refusing to guess"
        ]
    if node.filter_region is not None:
        return [
            f"{prefix}# TODO: GetOCRText with FilterRegion set "
            f"({_describe_expr_for_comment(node.filter_region)}) — region "
            "filtering not modeled, refusing to guess"
        ]
    todo: list[str] = []
    target = _render_value_or_todo(node.text, prefix, todo)
    language = (
        _render_value_or_todo(node.language, prefix, todo)
        if node.language is not None
        else None
    )
    if todo:
        return todo
    lines: list[str] = []
    if not node.selector:
        lines.append(f"{prefix}_img = PIL.ImageGrab.grab()")
    else:
        rendered = selector_text_to_pywinauto(node.selector)
        if rendered.expr == 'Desktop(backend="uia")':
            return [
                f"{prefix}# TODO: GetOCRText selector had no mappable "
                f"attributes: {node.selector}"
            ]
        lines.extend(f"{prefix}# WARNING: {w}" for w in rendered.warnings)
        lines.append(f"{prefix}_img = {rendered.expr}.capture_as_image()")
    lang_kwarg = f", lang={language}" if language is not None else ""
    lines.append(f"{prefix}{target} = pytesseract.image_to_string(_img{lang_kwarg})")
    return lines


# 知見181: `ui:AddDataRow`(GitHub code searchで2120件ヒット——
# `BuildDataTable`直後に続く定番パターン)。`ArrayRow`(VB配列リテラル、
# `uipath_expr`の`ArrayLiteral`が既に`render_expr`でPythonリストへ
# 変換する確立済みの経路)を既存のDataTable変数へ`.append()`する——
# 既存の行表現(dict/list)を読む必要が無いため、`DataTable`表現の
# 非統一(知見179で検討し見送った理由)に影響されない数少ない安全な
# DataTable操作。
def _generate_add_data_row(node: AddDataRowNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_add_data_row_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_add_data_row_body(node: AddDataRowNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.data_table is None:
        return [f"{prefix}# TODO: AddDataRow with no DataTable captured"]
    if node.data_row is not None:
        return [
            f"{prefix}# TODO: AddDataRow with DataRow set "
            f"({_describe_expr_for_comment(node.data_row)}) — DataRow "
            "object reference not modeled, refusing to guess"
        ]
    if node.array_row is None:
        return [f"{prefix}# TODO: AddDataRow with no ArrayRow captured"]
    todo: list[str] = []
    data_table = _render_value_or_todo(node.data_table, prefix, todo)
    array_row = _render_value_or_todo(node.array_row, prefix, todo)
    if todo:
        return todo
    # 知見205: `ScopeInfo.data_table_columns`(知見203で構築済み、同じ
    # `DataTable`変数が`BuildDataTable`で確認済みの列名を持つと分かる
    # 場合)が分かれば、`ArrayRow`(位置指定の値)を列名付きのdict行へ
    # 変換する——`AddDataRow`が素のlist行を追加すると、同じDataTableを
    # 後で読む他の活動(`LookupDataTable`/`GetRowItem.ColumnName`等、
    # いずれもdict行を前提にした直接アクセス)が`TypeError`で実行時に
    # 落ちる実在のバグを修正する。列名が分からない場合は従来通り
    # 位置指定のlistのまま追加する(安全側のフォールバック、新しい
    # 挙動の後退は無い)。
    columns = None
    scope = get_active_scope()
    if scope is not None and isinstance(node.data_table, VbExpr):
        columns = scope.data_table_columns.get(node.data_table.text.lower())
    if columns:
        return [f"{prefix}{data_table}.append(dict(zip({columns!r}, {array_row})))"]
    return [f"{prefix}{data_table}.append({array_row})"]


# 知見182: `ui:RemoveDataRow`(`AddDataRow`知見181の正反対)。`RowIndex`
# による削除(`del {data_table}[{row_index}]`)は`DataTable`変数の
# 実行時表現を問わない安全な操作(知見181と同じ理由)。`Row`が設定
# されている場合は`{data_table}.remove({row})`を試みるが、実機確認
# した実例はLINQ式(`uipath_expr`未対応)のため安全に`# TODO`へ倒れる。
def _generate_remove_data_row(node: RemoveDataRowNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_remove_data_row_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_remove_data_row_body(node: RemoveDataRowNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.data_table is None:
        return [f"{prefix}# TODO: RemoveDataRow with no DataTable captured"]
    if node.row is not None and node.row_index is not None:
        return [
            f"{prefix}# TODO: RemoveDataRow with both Row and RowIndex set "
            "— priority between the two not confirmed, refusing to guess"
        ]
    if node.row_index is not None:
        todo: list[str] = []
        data_table = _render_value_or_todo(node.data_table, prefix, todo)
        row_index = _render_value_or_todo(node.row_index, prefix, todo)
        if todo:
            return todo
        # `RowIndex`はPythonのlistインデックスとして使うため整数が必要——
        # `Literal`は知見2・5の規約で常に文字列として保持されるため、VBの
        # `CInt`と同じ確認済みの変換経路(`round(_vb_cdbl(x))`、知見52・53)
        # を経由して整数へ変換する(`_vb_num`は浮動小数点を返すため
        # インデックスには使えない、素の文字列もインデックスには使えない)。
        return [f"{prefix}del {data_table}[round({VB_CDBL_HELPER_NAME}({row_index}))]"]
    if node.row is not None:
        todo = []
        data_table = _render_value_or_todo(node.data_table, prefix, todo)
        row = _render_value_or_todo(node.row, prefix, todo)
        if todo:
            return todo
        return [f"{prefix}{data_table}.remove({row})"]
    return [f"{prefix}# TODO: RemoveDataRow with no Row/RowIndex captured"]


# 知見183: `ui:GetRowItem`。`ColumnIndex`は`DataTable`変数の実行時表現
# (dict行/list行)を実行時`isinstance`分岐で両方に対応する安全な
# コードを生成できる。`ColumnName`は列名アクセスのため、実際には
# dict行(`AddHeaders=True`由来)でなければ意味を成さないが、UiPathの
# 実DataTableは常に列名を持つため`row[column_name]`という直接アクセス
# を選んだ——表現が食い違う場合は`TypeError`で即座に失敗する(知見177
# と同じ「でっち上げた値で静かに間違えるより、失敗する方が安全」)。
def _generate_get_row_item(node: GetRowItemNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_get_row_item_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_get_row_item_body(node: GetRowItemNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.row is None:
        return [f"{prefix}# TODO: GetRowItem with no Row captured"]
    if node.value is None:
        return [f"{prefix}# TODO: GetRowItem with no output Value captured"]
    if node.column is not None:
        return [
            f"{prefix}# TODO: GetRowItem with Column set "
            f"({_describe_expr_for_comment(node.column)}) — DataColumn "
            "object reference not modeled, refusing to guess"
        ]
    if node.column_index is not None and node.column_name is not None:
        return [
            f"{prefix}# TODO: GetRowItem with both ColumnIndex and "
            "ColumnName set — priority between the two not confirmed, "
            "refusing to guess"
        ]
    todo: list[str] = []
    row = _render_value_or_todo(node.row, prefix, todo)
    target = _render_value_or_todo(node.value, prefix, todo)
    if node.column_index is not None:
        column_index = _render_value_or_todo(node.column_index, prefix, todo)
        if todo:
            return todo
        idx = f"round({VB_CDBL_HELPER_NAME}({column_index}))"
        return [
            f"{prefix}{target} = (list({row}.values())[{idx}] "
            f"if isinstance({row}, dict) else {row}[{idx}])"
        ]
    if node.column_name is not None:
        column_name = _render_value_or_todo(node.column_name, prefix, todo)
        if todo:
            return todo
        return [f"{prefix}{target} = {row}[{column_name}]"]
    return [f"{prefix}# TODO: GetRowItem with no ColumnIndex/ColumnName/Column captured"]


def _generate_update_row_item(node: UpdateRowItemNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_update_row_item_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_update_row_item_body(node: UpdateRowItemNode, indent: int) -> list[str]:
    """知見216: `GetRowItem`(知見183)と全く同じ「でっち上げた値で静か
    に間違えるより、失敗する方が安全」という方針——`ColumnName`指定時は
    `row[column_name] = value`という直接代入(list行なら`TypeError`で
    即座に失敗)。`ColumnIndex`指定時は`GetRowItem`と同じdict/list両
    対応だが、位置で値を書き込むため該当キーを求めてから代入する。"""
    prefix = INDENT * indent
    if node.row is None:
        return [f"{prefix}# TODO: UpdateRowItem with no Row captured"]
    if node.value is None:
        return [f"{prefix}# TODO: UpdateRowItem with no Value captured"]
    if node.column is not None:
        return [
            f"{prefix}# TODO: UpdateRowItem with Column set "
            f"({_describe_expr_for_comment(node.column)}) — DataColumn "
            "object reference not modeled, refusing to guess"
        ]
    if node.column_index is not None and node.column_name is not None:
        return [
            f"{prefix}# TODO: UpdateRowItem with both ColumnIndex and "
            "ColumnName set — priority between the two not confirmed, "
            "refusing to guess"
        ]
    todo: list[str] = []
    row = _render_value_or_todo(node.row, prefix, todo)
    value = _render_value_or_todo(node.value, prefix, todo)
    if node.column_index is not None:
        column_index = _render_value_or_todo(node.column_index, prefix, todo)
        if todo:
            return todo
        idx = f"round({VB_CDBL_HELPER_NAME}({column_index}))"
        inner = INDENT * (indent + 1)
        return [
            f"{prefix}if isinstance({row}, dict):",
            f"{inner}{row}[list({row}.keys())[{idx}]] = {value}",
            f"{prefix}else:",
            f"{inner}{row}[{idx}] = {value}",
        ]
    if node.column_name is not None:
        column_name = _render_value_or_todo(node.column_name, prefix, todo)
        if todo:
            return todo
        return [f"{prefix}{row}[{column_name}] = {value}"]
    return [
        f"{prefix}# TODO: UpdateRowItem with no ColumnIndex/ColumnName/"
        "Column captured"
    ]


# 知見184: `ui:ClearDataTable`。`AddDataRow`/`RemoveDataRow`と同じ理由で
# `list.clear()`は`DataTable`変数の実行時表現を一切問わない安全な操作。
def _generate_clear_data_table(node: ClearDataTableNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_clear_data_table_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_clear_data_table_body(node: ClearDataTableNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.data_table is None:
        return [f"{prefix}# TODO: ClearDataTable with no DataTable captured"]
    todo: list[str] = []
    data_table = _render_value_or_todo(node.data_table, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}{data_table}.clear()"]


# 知見184: `ui:OutputDataTable`。UiPath公式ドキュメント(WebSearchで
# 確認)によれば`DataTable`をCSV形式の文字列へ変換する活動——厳密な
# 区切り文字/引用符/改行コードの書式詳細は未確認のため、Python標準の
# `csv`モジュール(確認済みの標準ライブラリ)で近似する(`GetFullText`
# 知見159と同じ「大枠は確信、書式の細部は`# WARNING`」という判断)。
# `GetRowItem`(知見183)と同じ`isinstance(row, dict)`の実行時分岐で
# `DataTable`の両表現(dict行/list行)に対応する。
def _generate_output_data_table(node: OutputDataTableNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_output_data_table_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_output_data_table_body(node: OutputDataTableNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.data_table is None:
        return [f"{prefix}# TODO: OutputDataTable with no DataTable captured"]
    if node.text is None:
        return [f"{prefix}# TODO: OutputDataTable with no output Text captured"]
    todo: list[str] = []
    data_table = _render_value_or_todo(node.data_table, prefix, todo)
    target = _render_value_or_todo(node.text, prefix, todo)
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    return [
        f"{prefix}# WARNING: exact CSV formatting (delimiter/quoting/line "
        "endings) of UiPath's real OutputDataTable not independently "
        "confirmed — using Python's csv module as a confirmed-standard "
        "approximation",
        f"{prefix}_buf = io.StringIO()",
        f"{prefix}_writer = csv.writer(_buf)",
        f"{prefix}if {data_table} and isinstance({data_table}[0], dict):",
        f"{inner}_writer.writerow({data_table}[0].keys())",
        f"{inner}for _row in {data_table}:",
        f"{INDENT * (indent + 2)}_writer.writerow(_row.values())",
        f"{prefix}else:",
        f"{inner}for _row in {data_table}:",
        f"{INDENT * (indent + 2)}_writer.writerow(_row)",
        f"{prefix}{target} = _buf.getvalue()",
    ]


# 知見198: `ui:AddDataColumn`/`ui:RemoveDataColumn`。知見183の
# `isinstance(row, dict)`判定を「読み取り」ではなく「既存の全行への
# 書き込み(列の追加/削除)」という文脈で使う——dict行の場合のみ対応し、
# list行表現では何もしない一方向の対応であることを`# WARNING`で明記。
def _generate_add_data_column(node: AddDataColumnNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_add_data_column_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_add_data_column_body(node: AddDataColumnNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.data_table is None or node.column_name is None:
        return [f"{prefix}# TODO: AddDataColumn with missing DataTable/ColumnName"]
    if node.column is not None:
        return [
            f"{prefix}# TODO: AddDataColumn with Column set "
            f"({_describe_expr_for_comment(node.column)}) — DataColumn "
            "object reference not modeled, refusing to guess"
        ]
    if node.auto_increment == "True":
        return [
            f"{prefix}# TODO: AddDataColumn with AutoIncrement=True — "
            "auto-incrementing identity column semantics not confirmed, "
            "refusing to guess"
        ]
    if node.unique == "True":
        return [
            f"{prefix}# TODO: AddDataColumn with Unique=True — uniqueness "
            "constraint enforcement not confirmed, refusing to guess"
        ]
    if node.allow_db_null == "False":
        return [
            f"{prefix}# TODO: AddDataColumn with AllowDBNull=False — NOT "
            "NULL constraint enforcement on existing rows not confirmed, "
            "refusing to guess"
        ]
    todo: list[str] = []
    data_table = _render_value_or_todo(node.data_table, prefix, todo)
    column_name = _render_value_or_todo(node.column_name, prefix, todo)
    default_value = (
        _render_value_or_todo(node.default_value, prefix, todo)
        if node.default_value is not None
        else "None"
    )
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    return [
        f"{prefix}# WARNING: dict行表現のDataTableのみ対応(list行は変更されない)",
        f"{prefix}for _row in {data_table}:",
        f"{inner}if isinstance(_row, dict):",
        f"{INDENT * (indent + 2)}_row[{column_name}] = {default_value}",
    ]


def _generate_remove_data_column(node: RemoveDataColumnNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_remove_data_column_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_remove_data_column_body(
    node: RemoveDataColumnNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    if node.data_table is None or node.column_name is None:
        return [f"{prefix}# TODO: RemoveDataColumn with missing DataTable/ColumnName"]
    if node.column is not None:
        return [
            f"{prefix}# TODO: RemoveDataColumn with Column set "
            f"({_describe_expr_for_comment(node.column)}) — DataColumn "
            "object reference not modeled, refusing to guess"
        ]
    if node.column_index is not None:
        return [
            f"{prefix}# TODO: RemoveDataColumn with ColumnIndex set "
            f"({_describe_expr_for_comment(node.column_index)}) — "
            "column-index-based removal not confirmed in real samples, "
            "refusing to guess"
        ]
    todo: list[str] = []
    data_table = _render_value_or_todo(node.data_table, prefix, todo)
    column_name = _render_value_or_todo(node.column_name, prefix, todo)
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    return [
        f"{prefix}# WARNING: dict行表現のDataTableのみ対応(list行は変更されない)",
        f"{prefix}for _row in {data_table}:",
        f"{inner}if isinstance(_row, dict):",
        f"{INDENT * (indent + 2)}_row.pop({column_name}, None)",
    ]


# 知見185: `ui:ReadCsvFile`(`UiPath.Excel.Activities`名前空間)。
# `AddHeaders`相当の属性が無く、CSVの1行目を常にヘッダーとして扱う
# ——`csv.DictReader`(Python標準の`csv`モジュール)が直接対応し、
# `ExcelReadRange`の`AddHeaders=True`時(知見115)と同じdict行表現に
# 揃える。`Delimitator="Comma"`以外・`Encoding`設定時・`PathResource`
# 設定時は未確認のため`# TODO`へ倒す。
def _generate_read_csv_file(node: ReadCsvFileNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_read_csv_file_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_read_csv_file_body(node: ReadCsvFileNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.file_path is None:
        return [f"{prefix}# TODO: ReadCsvFile with no FilePath captured"]
    if node.data_table is None:
        return [f"{prefix}# TODO: ReadCsvFile with no output DataTable captured"]
    if node.path_resource is not None:
        return [
            f"{prefix}# TODO: ReadCsvFile with PathResource set "
            f"({_describe_expr_for_comment(node.path_resource)}) — "
            "Integration Service resource handling not confirmed, "
            "refusing to guess"
        ]
    if node.encoding is not None:
        return [
            f"{prefix}# TODO: ReadCsvFile with Encoding set "
            f"({_describe_expr_for_comment(node.encoding)}) — codec "
            "mapping not confirmed, refusing to guess"
        ]
    if node.delimitator not in (None, "Comma"):
        return [
            f"{prefix}# TODO: ReadCsvFile with non-default Delimitator "
            f"({node.delimitator!r}) — only Comma is confirmed, refusing "
            "to guess"
        ]
    todo: list[str] = []
    file_path = _render_value_or_todo(node.file_path, prefix, todo)
    target = _render_value_or_todo(node.data_table, prefix, todo)
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    return [
        f'{prefix}with open({file_path}, newline="") as _f:',
        f"{inner}{target} = [dict(_row) for _row in csv.DictReader(_f)]",
    ]


# 知見199: `ui:ReadPDFText`。`pypdf.PdfReader(...).pages[i].
# extract_text()`(`pyproject.toml`で既に確認済みの依存、PAD側
# `pad_action_lib/pdf_actions.py`で既に実戦投入済みの同じライブラリ)
# が直接対応する。単一ページ番号は1始まり(PAD側`extract_text_from_pdf`
# の`page_number - 1`という既存の確認済み変換を踏襲、UiPath Studio
# での独立確認はできていない合理的な推論)。
def _generate_read_pdf_text(node: ReadPdfTextNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_read_pdf_text_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_read_pdf_text_body(node: ReadPdfTextNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.file_name is None:
        return [f"{prefix}# TODO: ReadPDFText with no FileName captured"]
    if node.text is None:
        return [f"{prefix}# TODO: ReadPDFText with no output Text captured"]
    if node.preserve_formatting is not None:
        return [
            f"{prefix}# TODO: ReadPDFText with PreserveFormatting set "
            f"({_describe_expr_for_comment(node.preserve_formatting)}) — "
            "layout-preservation behavior not confirmed, refusing to guess"
        ]
    if (
        isinstance(node.range, Literal)
        and node.range.value != "All"
        and "-" in node.range.value
    ):
        return [
            f"{prefix}# TODO: ReadPDFText with hyphenated Range "
            f"({node.range.value!r}) — only confirmed on the sibling "
            "ExtractPDFPageRange activity, not on ReadPDFText itself, "
            "refusing to guess"
        ]
    todo: list[str] = []
    file_name = _render_value_or_todo(node.file_name, prefix, todo)
    target = _render_value_or_todo(node.text, prefix, todo)
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    if isinstance(node.range, Literal) and node.range.value == "All":
        return [
            f"{prefix}{target} = ''.join(_p.extract_text() or '' "
            f"for _p in pypdf.PdfReader({file_name}).pages)"
        ]
    if node.range is None:
        return [f"{prefix}# TODO: ReadPDFText with no Range captured"]
    range_ = _render_value_or_todo(node.range, prefix, todo)
    if todo:
        return todo
    return [
        f"{prefix}_rpt_reader = pypdf.PdfReader({file_name})",
        f"{prefix}if {range_} == 'All':",
        f"{inner}{target} = ''.join(_p.extract_text() or '' "
        "for _p in _rpt_reader.pages)",
        f"{prefix}else:",
        f"{inner}{target} = _rpt_reader.pages[int({range_}) - 1].extract_text() or ''",
    ]


# 知見200: `GetPDFPageCount`(`upap:`名前空間、知見193で発見した
# `clr-namespace:UiPath.PDF.Activities.PDF;assembly=UiPath.PDF.
# Activities`)。`len(pypdf.PdfReader(...).pages)`——PAD側
# `pad_action_lib/pdf_actions.py`の`extract_pages_to_new_pdf()`内で
# 既に使われている同じイディオム——が直接対応する。
def _generate_get_pdf_page_count(node: GetPdfPageCountNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_get_pdf_page_count_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_get_pdf_page_count_body(
    node: GetPdfPageCountNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    if node.file_name is None:
        return [f"{prefix}# TODO: GetPDFPageCount with no FileName captured"]
    if node.page_count is None:
        return [f"{prefix}# TODO: GetPDFPageCount with no output PageCount captured"]
    todo: list[str] = []
    file_name = _render_value_or_todo(node.file_name, prefix, todo)
    target = _render_value_or_todo(node.page_count, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}{target} = len(pypdf.PdfReader({file_name}).pages)"]


# 知見200: `ExtractPDFPageRange`(`GetPDFPageCount`と同じ`upap:`
# 名前空間)。実機で確認した`Range`はハイフン区切りの単純な範囲
# (`"8-22"`)のみ——PAD側の`ExtractPagesToNewPDF`が対応するカンマ区切り
# の複数範囲はUiPath側で独立に確認できていないため、`N-M`形以外の
# **静的リテラル**は`# TODO`へ倒す(動的な式は実行時の`int()`の
# `ValueError`で自然に失敗させる、知見199の`ReadPDFText`と同じ方針)。
_EXTRACT_PDF_RANGE_RE = re.compile(r"^\d+-\d+$")


def _generate_extract_pdf_page_range(
    node: ExtractPdfPageRangeNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_extract_pdf_page_range_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_extract_pdf_page_range_body(
    node: ExtractPdfPageRangeNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    if node.file_name is None or node.output_file_name is None or node.range is None:
        return [
            f"{prefix}# TODO: ExtractPDFPageRange with missing "
            "FileName/OutputFileName/Range"
        ]
    if isinstance(node.range, Literal) and not _EXTRACT_PDF_RANGE_RE.match(
        node.range.value
    ):
        return [
            f"{prefix}# TODO: ExtractPDFPageRange with Range "
            f"({node.range.value!r}) not in the confirmed 'N-M' form, "
            "refusing to guess"
        ]
    todo: list[str] = []
    file_name = _render_value_or_todo(node.file_name, prefix, todo)
    output_file_name = _render_value_or_todo(node.output_file_name, prefix, todo)
    range_ = _render_value_or_todo(node.range, prefix, todo)
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    return [
        f"{prefix}_eppr_start, _eppr_end = ({range_}).split('-')",
        f"{prefix}_eppr_reader = pypdf.PdfReader({file_name})",
        f"{prefix}_eppr_writer = pypdf.PdfWriter()",
        f"{prefix}for _eppr_i in range(int(_eppr_start), int(_eppr_end) + 1):",
        f"{inner}_eppr_writer.add_page(_eppr_reader.pages[_eppr_i - 1])",
        f'{prefix}with open({output_file_name}, "wb") as _eppr_f:',
        f"{inner}_eppr_writer.write(_eppr_f)",
    ]


# 知見201: `JoinPDF`(`GetPDFPageCount`/`ExtractPDFPageRange`知見200と
# 同じ`upap:`名前空間)。`pypdf.PdfWriter`(`pad_action_lib/
# pdf_actions.py`の`merge_pdf_files()`と同じ`writer.append(reader)`
# イディオム)で`FileList`の各パスを順に結合する。実機の`FileList`は
# VB.NET配列リテラル構文だが、`render_expr`が既に`ArrayLiteral`→
# Pythonの`list`リテラルへの変換に対応済み(知見195時点では未確認
# として保留していたが、実際には動くと確認できた)。
def _generate_join_pdf(node: JoinPdfNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_join_pdf_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_join_pdf_body(node: JoinPdfNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.file_list is None or node.output_file_name is None:
        return [f"{prefix}# TODO: JoinPDF with missing FileList/OutputFileName"]
    todo: list[str] = []
    file_list = _render_value_or_todo(node.file_list, prefix, todo)
    output_file_name = _render_value_or_todo(node.output_file_name, prefix, todo)
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    return [
        f"{prefix}_jp_writer = pypdf.PdfWriter()",
        f"{prefix}for _jp_path in {file_list}:",
        f"{inner}_jp_writer.append(pypdf.PdfReader(_jp_path))",
        f'{prefix}with open({output_file_name}, "wb") as _jp_f:',
        f"{inner}_jp_writer.write(_jp_f)",
    ]


# 知見209: `ExportPDFPageAsImage`(`GetPDFPageCount`/`ExtractPDFPageRange`/
# `JoinPDF`知見200・201と同じ`upap:`名前空間)。`pymupdf.open(FileName)
# [PageNumber - 1].get_pixmap(dpi=ImageDpi).save(OutputFileName)`が直接
# 対応する(`get_pixmap(dpi=...)`はPyMuPDF 1.19.2以降の公式API)。
# `pymupdf`は本体`dependencies`ではなく`[project.optional-dependencies]`
# の`pdf-render`プラグイン群(知見209の設計判断)——`pypdf`と同じく、
# トランスパイラ本体はこれをimportしない、生成コードの文字列として
# 埋め込むだけ(`_collect_imports`が`pymupdf.open(`の出現を検出して
# `import pymupdf`を注入する)。
def _generate_export_pdf_page_as_image(
    node: ExportPdfPageAsImageNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_export_pdf_page_as_image_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_export_pdf_page_as_image_body(
    node: ExportPdfPageAsImageNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    if (
        node.file_name is None
        or node.output_file_name is None
        or node.page_number is None
    ):
        return [
            f"{prefix}# TODO: ExportPDFPageAsImage with missing FileName/"
            "OutputFileName/PageNumber"
        ]
    if node.image_dpi is None:
        return [f"{prefix}# TODO: ExportPDFPageAsImage with no ImageDpi captured"]
    todo: list[str] = []
    file_name = _render_value_or_todo(node.file_name, prefix, todo)
    output_file_name = _render_value_or_todo(node.output_file_name, prefix, todo)
    page_number = _render_value_or_todo(node.page_number, prefix, todo)
    if todo:
        return todo
    # `PageNumber`はPythonのlistインデックスとして使うため整数が必要
    # ——知見182の`RemoveDataRow`と同じ`round(_vb_cdbl(x))`経由で変換
    # する(素の`Literal`は文字列のため)。`ImageDpi`は属性値(素の文字列)
    # のため同様に変換する。
    return [
        f"{prefix}_eppi_doc = pymupdf.open({file_name})",
        f"{prefix}_eppi_page = _eppi_doc[round({VB_CDBL_HELPER_NAME}("
        f"{page_number})) - 1]",
        f"{prefix}_eppi_pix = _eppi_page.get_pixmap(dpi=round("
        f"{VB_CDBL_HELPER_NAME}({node.image_dpi!r})))",
        f"{prefix}_eppi_pix.save({output_file_name})",
    ]


# 知見209: `ExtractImagesFromPDF`(`GetPDFPageCount`/`ExtractPDFPageRange`/
# `JoinPDF`/`ExportPDFPageAsImage`と同じ`upap:`名前空間、同じ`pdf-render`
# プラグインを使う)。PyMuPDF公式レシピ(`recipes-images.rst`、知見209で
# WebFetch確認済み)の`Page.get_images()`+`Document.extract_image(xref)`
# が直接対応する——出力ファイル名(`img-{xref}.{ext}`)はUiPath自身の
# 内部命名を再現したものではない、本トランスパイラ独自の選択である旨を
# 生成コードにもコメントで残す(抽出される画像バイト列自体の正しさとは
# 独立した表示上の選択に過ぎない)。
def _generate_extract_images_from_pdf(
    node: ExtractImagesFromPdfNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_extract_images_from_pdf_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_extract_images_from_pdf_body(
    node: ExtractImagesFromPdfNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    if node.file_name is None or node.output_folder_name is None:
        return [
            f"{prefix}# TODO: ExtractImagesFromPDF with missing FileName/"
            "OutputFolderName"
        ]
    if node.image_extension is not None:
        return [
            f"{prefix}# TODO: ExtractImagesFromPDF with ImageExtension set "
            "— non-default output format not confirmed in real samples, "
            "refusing to guess"
        ]
    todo: list[str] = []
    file_name = _render_value_or_todo(node.file_name, prefix, todo)
    output_folder_name = _render_value_or_todo(node.output_folder_name, prefix, todo)
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    inner2 = INDENT * (indent + 2)
    inner3 = INDENT * (indent + 3)
    return [
        f"{prefix}_eifp_doc = pymupdf.open({file_name})",
        f"{prefix}_eifp_seen = set()",
        # 出力ファイル名(`img-{xref}.{ext}`)はUiPathの内部命名を再現
        # したものではなく、本トランスパイラ独自の選択(知見209)。
        f"{prefix}for _eifp_page in _eifp_doc:",
        f"{inner}for _eifp_img in _eifp_page.get_images():",
        f"{inner2}_eifp_xref = _eifp_img[0]",
        f"{inner2}if _eifp_xref in _eifp_seen:",
        f"{inner3}continue",
        f"{inner2}_eifp_seen.add(_eifp_xref)",
        f"{inner2}_eifp_info = _eifp_doc.extract_image(_eifp_xref)",
        f"{inner2}if not _eifp_info:",
        f"{inner3}continue",
        f"{inner2}with open(os.path.join({output_folder_name}, "
        f'f"img-{{_eifp_xref}}.{{_eifp_info[\'ext\']}}"), "wb") as _eifp_f:',
        f"{inner3}_eifp_f.write(_eifp_info['image'])",
    ]


# 知見202: `ManagePDFPassword`(`GetPDFPageCount`/`ExtractPDFPageRange`/
# `JoinPDF`知見200・201と同じ`upap:`名前空間)。`pypdf.PdfWriter.
# encrypt(user_password, owner_password=...)`(`pypdf`本体のAPIを
# 直接使う最初の例、本リポジトリのPAD側に既存の暗号化イディオムは
# 無い)が直接対応する。`NewOwnerPassword`のみ設定時は
# `user_password=""`(対話的に確認済みの挙動、パスワード無しで開ける
# がowner権限のみ制限される)を渡す。`OldUserPassword`/
# `OldOwnerPassword`(既存パスワードの変更/削除用と推測、実機未確認)
# は常に`# TODO`へ倒す。
def _generate_manage_pdf_password(
    node: ManagePdfPasswordNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_manage_pdf_password_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_manage_pdf_password_body(
    node: ManagePdfPasswordNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    if node.file_name is None or node.output_file_name is None:
        return [
            f"{prefix}# TODO: ManagePDFPassword with missing "
            "FileName/OutputFileName"
        ]
    if node.old_user_password is not None or node.old_owner_password is not None:
        return [
            f"{prefix}# TODO: ManagePDFPassword with OldUserPassword/"
            "OldOwnerPassword set — changing/removing an existing "
            "password not confirmed, refusing to guess"
        ]
    if node.new_user_password is None and node.new_owner_password is None:
        return [
            f"{prefix}# TODO: ManagePDFPassword with no NewUserPassword/"
            "NewOwnerPassword captured"
        ]
    todo: list[str] = []
    file_name = _render_value_or_todo(node.file_name, prefix, todo)
    output_file_name = _render_value_or_todo(node.output_file_name, prefix, todo)
    user_password = (
        _render_value_or_todo(node.new_user_password, prefix, todo)
        if node.new_user_password is not None
        else "''"
    )
    owner_password = (
        _render_value_or_todo(node.new_owner_password, prefix, todo)
        if node.new_owner_password is not None
        else "None"
    )
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    return [
        f"{prefix}_mpp_writer = pypdf.PdfWriter()",
        f"{prefix}_mpp_writer.append(pypdf.PdfReader({file_name}))",
        f"{prefix}_mpp_writer.encrypt(user_password={user_password}, "
        f"owner_password={owner_password})",
        f'{prefix}with open({output_file_name}, "wb") as _mpp_f:',
        f"{inner}_mpp_writer.write(_mpp_f)",
    ]


# 知見185: `ui:WriteCsvFile`(`ReadCsvFile`の正反対)。`OutputDataTable`
# (知見184)と同じ`isinstance(data_table[0], dict)`の実行時分岐で
# `DataTable`の両表現に対応する——dict行の場合のみ`AddHeaders`に従って
# ヘッダー行を出力し、list行の場合は列名を持たないためヘッダー無しで
# 値のみを出力する(でっち上げた列名を書かない安全な縮退)。
def _generate_write_csv_file(node: WriteCsvFileNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_write_csv_file_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_write_csv_file_body(node: WriteCsvFileNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.file_path is None:
        return [f"{prefix}# TODO: WriteCsvFile with no FilePath captured"]
    if node.data_table is None:
        return [f"{prefix}# TODO: WriteCsvFile with no DataTable captured"]
    if node.encoding is not None:
        return [
            f"{prefix}# TODO: WriteCsvFile with Encoding set "
            f"({_describe_expr_for_comment(node.encoding)}) — codec "
            "mapping not confirmed, refusing to guess"
        ]
    if node.delimitator not in (None, "Comma"):
        return [
            f"{prefix}# TODO: WriteCsvFile with non-default Delimitator "
            f"({node.delimitator!r}) — only Comma is confirmed, refusing "
            "to guess"
        ]
    if node.should_quote not in (None, "True"):
        return [
            f"{prefix}# TODO: WriteCsvFile with non-default ShouldQuote "
            f"({node.should_quote!r}) — only the True default is "
            "confirmed, refusing to guess"
        ]
    if node.add_headers not in (None, "True", "False"):
        return [
            f"{prefix}# TODO: WriteCsvFile with unrecognized AddHeaders "
            f"({node.add_headers!r}) — refusing to guess"
        ]
    add_headers = node.add_headers if node.add_headers is not None else "True"
    todo: list[str] = []
    file_path = _render_value_or_todo(node.file_path, prefix, todo)
    data_table = _render_value_or_todo(node.data_table, prefix, todo)
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    lines = [
        f"{prefix}# WARNING: AddHeaders is only honored for dict-shaped "
        "rows (column names known) — list-shaped rows are written "
        "without a header line regardless of AddHeaders",
        f'{prefix}with open({file_path}, "w", newline="") as _f:',
        f"{inner}_writer = csv.writer(_f)",
        f"{inner}if {data_table} and isinstance({data_table}[0], dict):",
    ]
    if add_headers == "True":
        lines.append(f"{INDENT * (indent + 2)}_writer.writerow({data_table}[0].keys())")
    lines.extend(
        [
            f"{INDENT * (indent + 2)}for _row in {data_table}:",
            f"{INDENT * (indent + 3)}_writer.writerow(_row.values())",
            f"{inner}else:",
            f"{INDENT * (indent + 2)}for _row in {data_table}:",
            f"{INDENT * (indent + 3)}_writer.writerow(_row)",
        ]
    )
    return lines


def _generate_deserialize_xml(node: DeserializeXmlNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_deserialize_xml_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_deserialize_xml_body(
    node: DeserializeXmlNode, indent: int
) -> list[str]:
    """知見228: `.NET XDocument.Parse()`相当は`lxml.etree.fromstring()`
    (本体の既存確認済み依存`lxml`、`ExportPDFPageAsImage`知見209の
    ような新規「プラグイン」依存ではない)に対応する——XML宣言内の
    エンコーディング指定を正しく解釈させるため、文字列を
    `.encode("utf-8")`してバイト列として渡す。"""
    prefix = INDENT * indent
    if node.xml_string is None or node.xml_document is None:
        return [
            f"{prefix}# TODO: DeserializeXml with missing XMLString/"
            "XMLDocument"
        ]
    todo: list[str] = []
    xml_string = _render_value_or_todo(node.xml_string, prefix, todo)
    xml_document = _render_value_or_todo(node.xml_document, prefix, todo)
    if todo:
        return todo
    return [
        f"{prefix}{xml_document} = lxml.etree.fromstring("
        f"{VB_CSTR_HELPER_NAME}({xml_string}).encode(\"utf-8\"))"
    ]


def _generate_execute_xpath(node: ExecuteXPathNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_execute_xpath_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_execute_xpath_body(node: ExecuteXPathNode, indent: int) -> list[str]:
    """知見228: `DeserializeXml`の兄弟活動。公式ドキュメント確認済み
    ——`XMLString`を入力すると`ExistingXML`は使用不可になる(両方
    非nullな実機例は無い)ため`XMLString`を優先する。`.NET
    XDocument.XPathEvaluate`相当は`lxml`の`Element.xpath()`
    (.NET実装もXPath 1.0相当のため構文変換は不要、`Regex`系活動
    (知見144/213/220)とは違う)に対応する——`string(...)`で
    ラップされたXPath式はPythonの`str`を返す(`.xpath()`の
    ネイティブな戻り値型分岐)。"""
    prefix = INDENT * indent
    if node.xpath_expression is None or node.result is None:
        return [
            f"{prefix}# TODO: ExecuteXPath with missing XPathExpression/"
            "Result"
        ]
    if node.xml_string is None and node.existing_xml is None:
        return [
            f"{prefix}# TODO: ExecuteXPath with no XMLString/ExistingXML "
            "captured"
        ]
    todo: list[str] = []
    xpath_expression = _render_value_or_todo(node.xpath_expression, prefix, todo)
    result = _render_value_or_todo(node.result, prefix, todo)
    if node.xml_string is not None:
        xml_string = _render_value_or_todo(node.xml_string, prefix, todo)
        if todo:
            return todo
        tree_expr = (
            f'lxml.etree.fromstring({VB_CSTR_HELPER_NAME}({xml_string})'
            '.encode("utf-8"))'
        )
    else:
        existing_xml = _render_value_or_todo(node.existing_xml, prefix, todo)
        if todo:
            return todo
        tree_expr = existing_xml
    return [f"{prefix}{result} = {tree_expr}.xpath({xpath_expression})"]


# 知見186: `ui:InvokePowerShell`。`PowerShellProcess="PowerShellCore"`
# (実機確認した全例)の場合、`subprocess.run(["pwsh", "-Command",
# command_text], check=True)`が直接対応する——`check=True`は
# `ContinueOnError`の既定値(エラーを伝播させる)に合わせる(知見177と
# 同じ「でっち上げた成功より失敗を伝播させる方が安全」という判断)。
def _generate_invoke_powershell(node: InvokePowerShellNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_invoke_powershell_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_invoke_powershell_body(node: InvokePowerShellNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.command_text is None:
        return [f"{prefix}# TODO: InvokePowerShell with no CommandText captured"]
    if node.powershell_process != "PowerShellCore":
        return [
            f"{prefix}# TODO: InvokePowerShell with PowerShellProcess "
            f"{node.powershell_process!r} — only PowerShellCore (pwsh) is "
            "confirmed, refusing to guess"
        ]
    if node.has_parameters:
        return [
            f"{prefix}# TODO: InvokePowerShell with Parameters set — "
            "named-parameter binding not modeled, refusing to guess"
        ]
    if node.has_powershell_variables:
        return [
            f"{prefix}# TODO: InvokePowerShell with PowerShellVariables "
            "set — variable binding not modeled, refusing to guess"
        ]
    if node.input is not None:
        return [
            f"{prefix}# TODO: InvokePowerShell with Input set "
            f"({_describe_expr_for_comment(node.input)}) — pipeline input "
            "not modeled, refusing to guess"
        ]
    if node.errors is not None:
        return [
            f"{prefix}# TODO: InvokePowerShell with Errors bound "
            f"({_describe_expr_for_comment(node.errors)}) — error "
            "collection output not modeled, refusing to guess"
        ]
    if node.pipeline_output is not None:
        return [
            f"{prefix}# TODO: InvokePowerShell with PipelineOutput bound "
            f"({_describe_expr_for_comment(node.pipeline_output)}) — "
            "pipeline output capture not modeled, refusing to guess"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: InvokePowerShell with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    todo: list[str] = []
    command_text = _render_value_or_todo(node.command_text, prefix, todo)
    if todo:
        return todo
    return [f'{prefix}subprocess.run(["pwsh", "-Command", {command_text}], check=True)']


# 知見187: `ui:RetryScope`。公式REFrameworkテンプレート
# (`SetTransactionStatus.xaml`)の使い方——`Condition`を空のままにし、
# `ActivityBody`内部の`TryCatch`+`Rethrow`で例外を伝播させる——を
# 「本体が例外無しで完了するまで最大`NumberOfRetries`回まで再試行し、
# 全回失敗したら最後の例外を伝播させる」という確認済みの意味論として
# 実装する。`Condition`が空でない・`RetryInterval`設定・
# `LogRetriedExceptions`/`RetriedExceptionsLogLevel`設定の場合は
# `# TODO`へ倒す。
def _generate_retry_scope(
    node: RetryScopeNode, indent: int, invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_retry_scope_body(node, indent, invoke_resolver, out_arg_resolver)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_retry_scope_body(
    node: RetryScopeNode, indent: int, invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    prefix = INDENT * indent
    if node.condition_has_body:
        return [
            f"{prefix}# TODO: RetryScope with a non-empty Condition — "
            "value-based retry conditions not modeled, refusing to guess"
        ]
    if node.retry_interval is not None:
        return [
            f"{prefix}# TODO: RetryScope with RetryInterval set "
            f"({_describe_expr_for_comment(node.retry_interval)}) — exact "
            "wait-time conversion not confirmed, refusing to guess"
        ]
    if node.log_retried_exceptions is not None:
        return [
            f"{prefix}# TODO: RetryScope with LogRetriedExceptions set "
            f"({_describe_expr_for_comment(node.log_retried_exceptions)}) — "
            "logging behavior not confirmed, refusing to guess"
        ]
    if node.retried_exceptions_log_level is not None:
        return [
            f"{prefix}# TODO: RetryScope with RetriedExceptionsLogLevel "
            f"set ({_describe_expr_for_comment(node.retried_exceptions_log_level)}) "
            "— logging behavior not confirmed, refusing to guess"
        ]
    if node.number_of_retries is None:
        return [f"{prefix}# TODO: RetryScope with no NumberOfRetries captured"]
    todo: list[str] = []
    number_of_retries = _render_value_or_todo(node.number_of_retries, prefix, todo)
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    lines = [f"{prefix}_retry_max = round({VB_CDBL_HELPER_NAME}({number_of_retries}))"]
    lines.append(f"{prefix}for _retry_attempt in range(_retry_max):")
    lines.append(f"{inner}try:")
    body = _ensure_nonempty_suite(
        _generate_body(node.body, indent + 2, invoke_resolver, out_arg_resolver), indent + 2
    )
    lines.extend(body)
    lines.append(f"{INDENT * (indent + 2)}break")
    lines.append(f"{inner}except Exception:")
    lines.append(f"{INDENT * (indent + 2)}if _retry_attempt == _retry_max - 1:")
    lines.append(f"{INDENT * (indent + 3)}raise")
    return lines


# 知見169: `ui:KillProcess`(GitHub code searchで1514件ヒット——
# 知見255: `ui:GetProcesses`——出力の`Processes`(`IEnumerable<System.
# Diagnostics.Process>`)は既存の確認済みコア依存`psutil`
# (`dump_daemon/uia_capture.py`で既に同じAPIを使用済み)の
# `psutil.process_iter()`がそのまま正確に対応する。
def _generate_get_processes(node: GetProcessesNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_get_processes_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_get_processes_body(node: GetProcessesNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.processes is None:
        return [f"{prefix}# TODO: GetProcesses with no Processes output captured"]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: GetProcesses with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    try:
        target = render_expr(node.processes)
    except NotImplementedError as e:
        return _todo_value(prefix, str(e))
    return [f"{prefix}{target} = list(psutil.process_iter())"]


# REFrameworkの標準サブワークフロー`KillAllProcesses.xaml`で多用される
# ため極めて高頻度)。`ProcessName`に一致する全プロセスを終了する
# ——Windows標準搭載の確認済みコマンド`taskkill /IM <name>.exe /F`
# (`subprocess.run`経由)が直接対応する。`/T`(プロセスツリー全体の
# 終了)は付けない(.NETの素の`Process.Kill()`は子プロセスを終了しない
# ため、過大な終了範囲をでっち上げないよう安全側に倒す)。知見255:
# `Process`が設定されている場合(実機`crcnum4/
# UP_Underwriter_Dashboard`で確認——`GetProcesses`の出力をループした
# `psutil.Process`オブジェクト)は`.kill()`で直接対応する
# (`ProcessName`経由の`taskkill`より直接的)。
def _generate_kill_process(node: KillProcessNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_kill_process_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_kill_process_body(node: KillProcessNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.process_name is None and node.process is None:
        return [f"{prefix}# TODO: KillProcess with no ProcessName/Process captured"]
    if node.applies_to is not None and not (
        isinstance(node.applies_to, Literal) and node.applies_to.value == "All"
    ):
        return [
            f"{prefix}# TODO: KillProcess with AppliesTo set "
            f"({_describe_expr_for_comment(node.applies_to)}) — only the "
            'confirmed "All" (default) value is implemented, refusing to '
            "guess"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: KillProcess with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    if node.process is not None:
        try:
            process = render_expr(node.process)
        except NotImplementedError as e:
            return _todo_value(prefix, str(e))
        return [f"{prefix}{process}.kill()"]
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


# 知見175: `ui:RefreshBrowser`(GitHub code searchで59件ヒット)。
# `CloseTab`(知見170)と属性構成・意味論が同型——`Browser`が
# `{x:Null}`の場合は「現在のページを再読み込みする」という意味論に
# なり、主要ブラウザ共通の標準キーボードショートカット`F5`
# (pywinautoの`.venv`ソース`keyboard.py`のCODESグラマーで確認済みの
# 特殊キー構文)で実現する。
def _generate_refresh_browser(node: RefreshBrowserNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_refresh_browser_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_refresh_browser_body(node: RefreshBrowserNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.browser is not None:
        return [
            f"{prefix}# TODO: RefreshBrowser with Browser set "
            f"({_describe_expr_for_comment(node.browser)}) — UiBrowser "
            "variable reference not modeled, refusing to guess"
        ]
    return [f"{prefix}send_keys('{{F5}}')"]


def _generate_go_back(node: GoBackNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_go_back_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_go_back_body(node: GoBackNode, indent: int) -> list[str]:
    """知見242: `ui:GoBack`。`RefreshBrowser`(知見175)と全く同じ
    `Browser`属性構成——`{x:Null}`(既定、現在アタッチ中のブラウザ)
    の場合のみ主要ブラウザ共通の`Alt+Left`(履歴を1つ戻る)に対応する。"""
    prefix = INDENT * indent
    if node.browser is not None:
        return [
            f"{prefix}# TODO: GoBack with Browser set "
            f"({_describe_expr_for_comment(node.browser)}) — UiBrowser "
            "variable reference not modeled, refusing to guess"
        ]
    return [f"{prefix}send_keys('%{{LEFT}}')"]


def _generate_navigate_to(node: NavigateToNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_navigate_to_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_navigate_to_body(node: NavigateToNode, indent: int) -> list[str]:
    """知見242: `ui:NavigateTo`。`Browser`が`{x:Null}`の場合のみ対応
    (実機3件いずれも`{x:Null}`、変数参照の実例は`GoBack`と違い未確認
    だが同じ`# TODO`方針を予防的に適用する)——`Ctrl+L`でアドレスバーへ
    フォーカスし、`Url`を`TypeInto`(知見110)と同じ
    `_pywinauto_type_keys_escape()`でエスケープしてから`{ENTER}`で
    確定する。"""
    prefix = INDENT * indent
    if node.browser is not None:
        return [
            f"{prefix}# TODO: NavigateTo with Browser set "
            f"({_describe_expr_for_comment(node.browser)}) — UiBrowser "
            "variable reference not modeled, refusing to guess"
        ]
    if node.url is None:
        return [f"{prefix}# TODO: NavigateTo with no Url captured"]
    todo: list[str] = []
    url = _render_value_or_todo(node.url, prefix, todo)
    if todo:
        return todo
    url_arg = f"{_TYPE_KEYS_ESCAPE_HELPER_NAME}({VB_CSTR_HELPER_NAME}({url}))"
    return [
        f"{prefix}send_keys('^l')",
        f"{prefix}send_keys({url_arg} + '{{ENTER}}')",
    ]


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
# 知見192: `ui:SelectFile`はOSのネイティブなファイル選択ダイアログを
# 表示し、ユーザーの選択を待つ活動——headless実行環境で代わりに応答する
# 安全な方法は無いため、`Filter`・出力の有無を問わず常に`# TODO`へ倒す
# (知見176の`GetPassword`・知見174の`GetAttribute`と同じ判断)。
def _generate_select_file(node: SelectFileNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_select_file_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_select_file_body(node: SelectFileNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    return [
        f"{prefix}# TODO: SelectFile — displays a native OS file-picker "
        "dialog for interactive user selection, no safe unattended "
        "equivalent exists, refusing to guess"
    ]


def _generate_select_folder(node: SelectFolderNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_select_folder_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_select_folder_body(node: SelectFolderNode, indent: int) -> list[str]:
    """知見252: `ui:SelectFolder`——`SelectFile`(知見192)と同じ理由
    (ネイティブOSダイアログでのユーザー操作そのもの)で常に`# TODO`へ
    倒す。"""
    prefix = INDENT * indent
    return [
        f"{prefix}# TODO: SelectFolder — displays a native OS folder-"
        "picker dialog for interactive user selection, no safe "
        "unattended equivalent exists, refusing to guess"
    ]


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


# 知見262: `ui:SelectMultipleItems`(`SelectItemNode`の複数選択版)。
# `MultipleItems`(VB配列リテラル→Python `list`)の各要素に対して
# `SelectItemNode`と同じ`pywinauto`の汎用`.select()`アクセサを順に
# 呼ぶ——複数回の`.select()`呼び出しが選択を累積するか置き換えるかは
# 未確認の近似(警告コメントで明示する)。`AddToSelection`は公式
# ドキュメント確認済みの意味(既存選択への追加/先にクリア)はあるが
# 未設定時の既定挙動が不明のため、明示的に設定されている場合は
# `# TODO`へ倒す。
def _generate_select_multiple_items(node: SelectMultipleItemsNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_select_multiple_items_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_select_multiple_items_body(
    node: SelectMultipleItemsNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    if not node.selector:
        return [f"{prefix}# TODO: Select Multiple Items with no selector captured"]
    if node.multiple_items is None:
        return [f"{prefix}# TODO: Select Multiple Items with no MultipleItems captured"]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: Select Multiple Items with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    if _literal_str(node.alter_if_disabled) not in (None, "True"):
        return [
            f"{prefix}# TODO: Select Multiple Items with AlterIfDisabled set "
            f"({node.alter_if_disabled!r}) — UiPath docs only confirm the "
            "True-like default, refusing to guess how to reproduce False "
            "with pywinauto's select()"
        ]
    if node.add_to_selection is not None:
        return [
            f"{prefix}# TODO: Select Multiple Items with AddToSelection set "
            f"({_describe_expr_for_comment(node.add_to_selection)}) — "
            "unset-default behavior not confirmed by UiPath docs, refusing "
            "to guess"
        ]
    rendered = selector_text_to_pywinauto(node.selector)
    if rendered.expr == 'Desktop(backend="uia")':
        return [
            f"{prefix}# TODO: Select Multiple Items selector had no mappable "
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
    multiple_items = _render_value_or_todo(node.multiple_items, prefix, todo)
    if todo:
        return todo
    lines = [f"{prefix}# WARNING: {w}" for w in rendered.warnings]
    lines.append(
        f"{prefix}# WARNING: exact UI Automation API behind 'Select Multiple "
        "Items' not independently confirmed — using pywinauto's generic "
        "select() accessor once per item; whether repeated select() calls "
        "accumulate or replace the selection is also unconfirmed"
    )
    if delay_before is not None:
        lines.append(f"{prefix}time.sleep({VB_NUM_HELPER_NAME}({delay_before}) / 1000.0)")
    lines.append(f"{prefix}for _item in {multiple_items}:")
    lines.append(
        f"{INDENT * (indent + 1)}{rendered.expr}.select({VB_CSTR_HELPER_NAME}(_item))"
    )
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


# 知見264: `ui:WaitUiElementAppear`(DisplayName「Find Element」)。
# `pywinauto`の`WindowSpecification.wait(...)`(文字列条件+秒単位の
# `timeout`引数、公式ドキュメント確認済みの既定30秒をそのまま使う)が
# 直接対応する——`WaitVisible`/`WaitActive`は条件文字列への単純な
# 追加のため、実機未確認の`"True"`値も含めて両方対応する(値自体の
# 意味論に不確実性が無いケース、`AlterIfDisabled`等とは違う判断)。
def _generate_wait_ui_element_appear(
    node: WaitUiElementAppearNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_wait_ui_element_appear_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_wait_ui_element_appear_body(
    node: WaitUiElementAppearNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    if not node.selector:
        return [f"{prefix}# TODO: Find Element with no selector captured"]
    if node.found_element is not None:
        return [
            f"{prefix}# TODO: Find Element with FoundElement bound "
            f"({_describe_expr_for_comment(node.found_element)}) — typed "
            "UiElement output not modeled, refusing to guess"
        ]
    rendered = selector_text_to_pywinauto(node.selector)
    if rendered.expr == 'Desktop(backend="uia")':
        return [
            f"{prefix}# TODO: Find Element selector had no mappable "
            f"attributes: {node.selector}"
        ]
    condition = "exists"
    if _literal_str(node.wait_visible) == "True":
        condition += " visible"
    if _literal_str(node.wait_active) == "True":
        condition += " active"
    lines = [f"{prefix}# WARNING: {w}" for w in rendered.warnings]
    lines.append(f"{prefix}{rendered.expr}.wait({condition!r}, timeout=30)")
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


def _insert_data_table_family_body(
    node: InsertDataTableNode | BulkInsertNode, indent: int, activity_label: str
) -> list[str]:
    """知見230: `InsertDataTable`/`BulkInsert`共通のコード生成——
    `DataTable`がdict行表現の場合のみ列名が分かるため`INSERT INTO
    table (col1, col2) VALUES (?, ?)`形で正確に対応し、list行表現の
    場合は列名が無いため`INSERT INTO table VALUES (?, ?)`(全列を
    順序通りに与えると仮定)という保守的な縮退に倒す
    (`WriteCsvFile`知見185・`OutputDataTable`知見184と同じ「両表現に
    対応するが、dict行の時だけ正確」という既存方針)。`?`プレース
    ホルダはSQLiteのネイティブ形式(`DatabaseConnect`知見114が常に
    `sqlite3.connect()`を生成するため)。"""
    prefix = INDENT * indent
    if node.affected_records is None:
        return [f"{prefix}# TODO: {activity_label} with no output AffectedRecords captured"]
    if node.existing_db_connection is None:
        return [f"{prefix}# TODO: {activity_label} with no ExistingDbConnection captured"]
    if node.data_table is None or node.table_name is None:
        return [f"{prefix}# TODO: {activity_label} with missing DataTable/TableName"]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: {activity_label} with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    todo: list[str] = []
    conn = _render_value_or_todo(node.existing_db_connection, prefix, todo)
    data_table = _render_value_or_todo(node.data_table, prefix, todo)
    table_name = _render_value_or_todo(node.table_name, prefix, todo)
    target = _render_value_or_todo(node.affected_records, prefix, todo)
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    return [
        f"{prefix}_idt_table = {VB_CSTR_HELPER_NAME}({table_name})",
        f"{prefix}if {data_table} and isinstance({data_table}[0], dict):",
        f"{inner}_idt_cols = list({data_table}[0].keys())",
        f"{inner}_idt_sql = ('INSERT INTO ' + _idt_table + ' (' "
        "+ ', '.join(_idt_cols) + ') VALUES (' "
        "+ ', '.join(['?'] * len(_idt_cols)) + ')')",
        f"{inner}_idt_cur = {conn}.executemany("
        f"_idt_sql, [tuple(_r[_c] for _c in _idt_cols) for _r in {data_table}])",
        f"{prefix}else:",
        f"{inner}# WARNING: list-shaped rows have no column names — values "
        "are assumed to map positionally to all TableName columns in "
        "table order",
        f"{inner}_idt_sql = ('INSERT INTO ' + _idt_table + ' VALUES (' "
        f"+ ', '.join(['?'] * len({data_table}[0])) + ')')",
        f"{inner}_idt_cur = {conn}.executemany(_idt_sql, {data_table})",
        f"{prefix}{conn}.commit()",
        f"{prefix}{target} = _idt_cur.rowcount",
    ]


def _generate_insert_data_table(node: InsertDataTableNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _insert_data_table_family_body(node, indent, "InsertDataTable")
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_bulk_insert(node: BulkInsertNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _insert_data_table_family_body(node, indent, "BulkInsert")
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_database_transaction(
    node: DatabaseTransactionNode, indent: int,
    invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_database_transaction_body(
        node, indent, invoke_resolver, out_arg_resolver
    )
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_database_transaction_body(
    node: DatabaseTransactionNode, indent: int,
    invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    """知見231: `UseTransaction=False`(「各操作が個別にコミットされる」、
    公式ドキュメント確認済み)は、`Body`配下の子活動(`ExecuteNonQuery`/
    `InsertDataTable`等)が既に各自`commit()`する既存コード生成
    (知見114・230)と完全に一致するため、`Body`をそのまま展開する
    だけで正しく動作する。一方`UseTransaction=True`(既定値、「全操作を
    1つのトランザクションにまとめ失敗時は全体をロールバック」)は、
    子活動が個別に`commit()`してしまう既存実装とそのままでは両立
    しない(先行する文が確定済みのままロールバックしても取り消せ
    ない)——子の`commit()`を抑制する文脈伝播機構が無いと正しい
    all-or-nothing保証を再現できないため、見た目だけ機能するが
    実際には保証しないtry/exceptをでっち上げるより`# TODO`へ倒す
    (`ModifyText`知見224と同じ「部分的に正しいより全体を拒否」)。
    `ConnectionString`/`ProviderName`での自己接続モード(`DatabaseConnect`
    知見114と同じ、MySQL等の未確認プロバイダで実機確認)も同様に
    未対応——`DatabaseConnect`自体が`System.Data.SQLite`以外を
    未確認として`# TODO`へ倒す既存方針と揃える。"""
    prefix = INDENT * indent
    if (
        node.connection_string is not None
        or node.provider_name is not None
        or node.secure_connection_string is not None
    ):
        return [
            f"{prefix}# TODO: DatabaseTransaction establishing its own "
            "connection (ConnectionString/ProviderName set) is not "
            "confirmed for any provider yet (only System.Data.SQLite is "
            "confirmed for DatabaseConnect) — pass an existing "
            "DatabaseConnection instead, refusing to guess"
        ]
    if node.database_connection is None:
        return [
            f"{prefix}# TODO: DatabaseTransaction with no DatabaseConnection "
            "captured"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: DatabaseTransaction with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "refusing to guess"
        ]
    if node.use_transaction not in (None, "True", "False"):
        return [
            f"{prefix}# TODO: DatabaseTransaction with unrecognized "
            f"UseTransaction ({node.use_transaction!r}) — refusing to guess"
        ]
    use_transaction = node.use_transaction if node.use_transaction is not None else "True"
    if use_transaction == "True":
        return [
            f"{prefix}# TODO: DatabaseTransaction with UseTransaction=True "
            "— child activities inside Body already commit individually "
            "(ExecuteNonQuery/InsertDataTable's own codegen), so a faithful "
            "all-or-nothing rollback cannot be reproduced without a "
            "context-propagation mechanism to suppress their commits; "
            "refusing to generate misleading try/except that looks "
            "transactional but isn't"
        ]
    todo: list[str] = []
    _render_value_or_todo(node.database_connection, prefix, todo)
    if todo:
        return todo
    return _ensure_nonempty_suite(
        _generate_body(node.body, indent, invoke_resolver, out_arg_resolver), indent
    )


_EXTRACT_TEXT_FALSE_ONLY_VALUES = (None, "False")


def _generate_extract_text(node: ExtractTextNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_extract_text_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_extract_text_body(node: ExtractTextNode, indent: int) -> list[str]:
    """知見232: `uast:ExtractText`。「`StartingText`と`EndingText`の
    間の文字列を抜き出す」——マーカー文字列自体は出力に含まない
    (`TextToLeftRight`知見222と同じ判断)。`MatchCase`省略時は公式
    ドキュメント確認済みの既定`False`(大文字小文字を区別しない検索、
    出力自体は元の大文字小文字を保持)。`StartingText`/`EndingText`が
    見つからない場合は`str.index()`の自然な`ValueError`に委ねる
    (フォールバック値を捏造しない既存方針)。"""
    prefix = INDENT * indent
    if (
        node.source is None
        or node.starting_text is None
        or node.ending_text is None
        or node.result is None
    ):
        return [
            f"{prefix}# TODO: ExtractText with missing Source/StartingText/"
            "EndingText/Result"
        ]
    if node.extract_options not in (None, "BetweenStrings"):
        return [
            f"{prefix}# TODO: ExtractText with unconfirmed ExtractOptions "
            f"({node.extract_options!r}) — only 'BetweenStrings' is "
            "confirmed, refusing to guess"
        ]
    if node.extract_base_url_only not in _EXTRACT_TEXT_FALSE_ONLY_VALUES:
        return [
            f"{prefix}# TODO: ExtractText with ExtractBaseURLOnly set "
            f"({node.extract_base_url_only!r}) — refusing to guess"
        ]
    if node.ignore_duplicates not in _EXTRACT_TEXT_FALSE_ONLY_VALUES:
        return [
            f"{prefix}# TODO: ExtractText with IgnoreDuplicates set "
            f"({node.ignore_duplicates!r}) — only the confirmed False "
            "default is supported, refusing to guess"
        ]
    if node.match_case not in (None, "True", "False"):
        return [
            f"{prefix}# TODO: ExtractText with unrecognized MatchCase "
            f"({node.match_case!r}) — refusing to guess"
        ]
    todo: list[str] = []
    source = _render_value_or_todo(node.source, prefix, todo)
    starting_text = _render_value_or_todo(node.starting_text, prefix, todo)
    ending_text = _render_value_or_todo(node.ending_text, prefix, todo)
    target = _render_value_or_todo(node.result, prefix, todo)
    if todo:
        return todo
    lines = [
        f"{prefix}_et_source = {VB_CSTR_HELPER_NAME}({source})",
        f"{prefix}_et_start = {VB_CSTR_HELPER_NAME}({starting_text})",
        f"{prefix}_et_end = {VB_CSTR_HELPER_NAME}({ending_text})",
    ]
    if node.match_case == "True":
        lines.extend(
            [
                f"{prefix}_et_start_idx = _et_source.index(_et_start) + len(_et_start)",
                f"{prefix}_et_end_idx = _et_source.index(_et_end, _et_start_idx)",
            ]
        )
    else:
        lines.extend(
            [
                f"{prefix}_et_source_lower = _et_source.lower()",
                f"{prefix}_et_start_idx = _et_source_lower.index(_et_start.lower()) + len(_et_start)",
                f"{prefix}_et_end_idx = _et_source_lower.index(_et_end.lower(), _et_start_idx)",
            ]
        )
    lines.append(f"{prefix}{target} = _et_source[_et_start_idx:_et_end_idx]")
    return lines


# 知見249: `uast:SplitText`/`uast:CombineText`——実機2件(`SplitText`の
# `liamsrowley/uipath-product-tracker`、`CombineText`の`mhmdreda99/
# UipathProjects`)いずれも`SeparatorKey="NewLine"`時の`Separator`
# 実際の直列化値が文字そのまま`"NewLine"`というラベルだった(`ui:
# TextToLeftRight`(知見222)の実CRLFバイトとは異なる規約)——
# `SeparatorKey`の値に応じてPython側で実際の区切り文字へ変換する、
# 確認済みは`"NewLine"`→`"\r\n"`のみ。
_UAST_SEPARATOR_KEY_VALUES = {"NewLine": "\r\n"}


def _generate_split_text(node: SplitTextNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_split_text_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_split_text_body(node: SplitTextNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.source is None or node.results is None:
        return [f"{prefix}# TODO: SplitText with missing Source/Results"]
    if node.separator_key not in _UAST_SEPARATOR_KEY_VALUES:
        return [
            f"{prefix}# TODO: SplitText with SeparatorKey "
            f"{node.separator_key!r} — only the confirmed \"NewLine\" "
            "value is implemented, refusing to guess"
        ]
    todo: list[str] = []
    source = _render_value_or_todo(node.source, prefix, todo)
    target = _render_value_or_todo(node.results, prefix, todo)
    if todo:
        return todo
    separator = _UAST_SEPARATOR_KEY_VALUES[node.separator_key]
    return [f"{prefix}{target} = {VB_CSTR_HELPER_NAME}({source}).split({separator!r})"]


def _generate_combine_text(node: CombineTextNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_combine_text_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_combine_text_body(node: CombineTextNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.source is None or node.result is None:
        return [f"{prefix}# TODO: CombineText with missing Source/Result"]
    if node.separator_key not in _UAST_SEPARATOR_KEY_VALUES:
        return [
            f"{prefix}# TODO: CombineText with SeparatorKey "
            f"{node.separator_key!r} — only the confirmed \"NewLine\" "
            "value is implemented, refusing to guess"
        ]
    todo: list[str] = []
    source = _render_value_or_todo(node.source, prefix, todo)
    target = _render_value_or_todo(node.result, prefix, todo)
    if todo:
        return todo
    separator = _UAST_SEPARATOR_KEY_VALUES[node.separator_key]
    return [f"{prefix}{target} = {separator!r}.join({source})"]


def _generate_get_last_downloaded_file(
    node: GetLastDownloadedFileNode, indent: int,
    invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_get_last_downloaded_file_body(
        node, indent, invoke_resolver, out_arg_resolver
    )
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_get_last_downloaded_file_body(
    node: GetLastDownloadedFileNode, indent: int,
    invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    """知見233: `ui:GetLastDownloadedFile`(公式表示名「Wait for
    Download」)。`File`出力は`ForEachFileX`/`ForEachFolderX`
    (知見190)と同じ「絶対パス文字列そのもの」として表現する
    ——`.Name`は`render.py`に新規追加した`os.path.basename()`対応、
    `.FullName`は既存の`fullname`ハンドラ(base passthrough)で対応
    済み。`DownloadFolder`配下のファイル一覧をBody実行前後でスナップ
    ショット比較し、新規出現したファイルのうち`IgnoreFiles`の拡張子
    (「ダウンロード完了まで無視する拡張子」、公式ドキュメント確認
    済み)に該当しないものをポーリングで探す近似実装——内部の
    ポーリング間隔自体はUiPath側の正確な値が未確認のため本トランス
    パイラ独自の値(0.5秒)を使う(知見206の画像照合近似と同じ
    「正確な再現ではなく近似と明記」方針)。`Timeout`省略時は公式
    ドキュメント確認済みの既定`300`秒。"""
    prefix = INDENT * indent
    if node.file_resource is not None:
        return [
            f"{prefix}# TODO: GetLastDownloadedFile with FileResource set "
            f"({_describe_expr_for_comment(node.file_resource)}) — "
            "Integration Service resource handling not confirmed, "
            "refusing to guess"
        ]
    if node.download_folder is None or node.file is None:
        return [
            f"{prefix}# TODO: GetLastDownloadedFile with missing "
            "DownloadFolder/File"
        ]
    todo: list[str] = []
    download_folder = _render_value_or_todo(node.download_folder, prefix, todo)
    target = _render_value_or_todo(node.file, prefix, todo)
    timeout = (
        _render_value_or_todo(node.timeout, prefix, todo)
        if node.timeout is not None
        else "300"
    )
    ignore_files = (
        _render_value_or_todo(node.ignore_files, prefix, todo)
        if node.ignore_files is not None
        else None
    )
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    lines = [
        f"{prefix}_glf_folder = {VB_CSTR_HELPER_NAME}({download_folder})",
        f"{prefix}_glf_before = set(os.listdir(_glf_folder)) "
        "if os.path.isdir(_glf_folder) else set()",
    ]
    lines.extend(
        _ensure_nonempty_suite(
            _generate_body(node.body, indent, invoke_resolver, out_arg_resolver),
            indent,
        )
    )
    ignore_expr = (
        f"{{_e.strip().lower() for _e in "
        f"{VB_CSTR_HELPER_NAME}({ignore_files}).split(',') if _e.strip()}}"
        if ignore_files is not None
        else "set()"
    )
    lines.extend(
        [
            f"{prefix}_glf_ignore_exts = {ignore_expr}",
            f"{prefix}_glf_deadline = time.monotonic() + round({VB_CDBL_HELPER_NAME}({timeout}))",
            f"{prefix}_glf_found = None",
            f"{prefix}while time.monotonic() < _glf_deadline:",
            f"{inner}_glf_new = (set(os.listdir(_glf_folder)) "
            "if os.path.isdir(_glf_folder) else set()) - _glf_before",
            f"{inner}_glf_candidates = [_f for _f in _glf_new if "
            "os.path.splitext(_f)[1].lstrip('.').lower() not in "
            "_glf_ignore_exts]",
            f"{inner}if _glf_candidates:",
            f"{INDENT * (indent + 2)}_glf_found = max(_glf_candidates, "
            "key=lambda _f: os.path.getmtime(os.path.join(_glf_folder, _f)))",
            f"{INDENT * (indent + 2)}break",
            f"{inner}time.sleep(0.5)",
            f"{prefix}if _glf_found is None:",
            f"{inner}raise TimeoutError("
            "f'GetLastDownloadedFile: no new file appeared in "
            "{_glf_folder!r} within the timeout period')",
            f"{prefix}{target} = os.path.join(_glf_folder, _glf_found)",
        ]
    )
    return lines


def _check_true_false_family_body(
    node: CheckTrueNode | CheckFalseNode, indent: int, activity_label: str, negate: bool
) -> list[str]:
    """知見234: `CheckTrue`/`CheckFalse`共通のコード生成——公式
    ドキュメント確認済みの「式がfalse(`CheckTrue`)/true(`CheckFalse`)
    の場合、カスタムメッセージ付きの例外を実行時に投げる」に対応する。
    .NET側の正確な例外型(コミュニティ情報では`CheckPointException`が
    既定の可能性があるが未確定)は未確認のため、既存の
    `_EXCEPTION_TYPE_MAP`の未知型フォールバックと同じ汎用`Exception`
    で代用する。`Expression`のブール変換は`If`/`While`(知見61)と
    同じ`_vb_bool()`を再利用する。"""
    prefix = INDENT * indent
    if node.expression is None or node.error_message is None:
        return [
            f"{prefix}# TODO: {activity_label} with missing Expression/"
            "ErrorMessage"
        ]
    todo: list[str] = []
    expression = _render_value_or_todo(node.expression, prefix, todo)
    error_message = _render_value_or_todo(node.error_message, prefix, todo)
    if todo:
        return todo
    cond = f"{VB_BOOL_HELPER_NAME}({expression})"
    if negate:
        cond = f"not {cond}"
    return [
        f"{prefix}if {cond}:",
        f"{INDENT * (indent + 1)}raise Exception({VB_CSTR_HELPER_NAME}({error_message}))",
    ]


def _generate_check_true(node: CheckTrueNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _check_true_false_family_body(node, indent, "CheckTrue", negate=True)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_check_false(node: CheckFalseNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _check_true_false_family_body(node, indent, "CheckFalse", negate=False)
    return _with_scope_child_display_name(node, lines, prefix)


# 知見235: `ui:CreateDirectory`。`Output`(.NET`DirectoryInfo`、
# 「作成したフォルダへの参照」、公式ドキュメント確認済み)は実機で
# 非null値を一度も確認できず未対応(`GetFileInfoX`/`GetFolderInfoX`と
# 同じ「未確認の型付きオブジェクトをでっち上げない」判断)。`Path`の
# 作成は.NET`Directory.CreateDirectory(path)`の確立済みAPIコントラクト
# (既存ディレクトリがあっても例外にならず中間の親ディレクトリも
# まとめて作成する)——`CopyFile`(知見117)と同じ「UiPath固有の
# ドキュメントではなく.NET自体の公開APIコントラクトに基づく判断」。
def _generate_create_directory(node: CreateDirectoryNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_create_directory_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_create_directory_body(
    node: CreateDirectoryNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    if node.path is None:
        return [f"{prefix}# TODO: CreateDirectory with no Path captured"]
    if node.output is not None:
        return [
            f"{prefix}# TODO: CreateDirectory with Output set "
            f"({_describe_expr_for_comment(node.output)}) — .NET "
            "DirectoryInfo reference not confirmed via real capture, "
            "refusing to guess"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: CreateDirectory with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    todo: list[str] = []
    path = _render_value_or_todo(node.path, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}os.makedirs({VB_CSTR_HELPER_NAME}({path}), exist_ok=True)"]


def _generate_merge_data_table(node: MergeDataTableNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_merge_data_table_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_merge_data_table_body(
    node: MergeDataTableNode, indent: int
) -> list[str]:
    """知見236: .NET`DataTable.Merge(sourceTable)`は呼び出し先
    (`Destination`)をインプレースで変更するインスタンスメソッド——
    `.extend()`で同じ参照共有の意味論を再現する。行は値コピー
    (`.NET`公式の挙動、参照共有ではない)されるため、dict行は
    `dict(_r)`で浅いコピーしてから追加する(`Source`側の後続変更が
    `Destination`側に伝播しないことを保証)。`MissingSchemaAction`は
    実機確認済みの`"Add"`のみ対応——本トランスパイラのDataTable表現
    (dict行、固定スキーマ無し)はそもそも列の追加を自動的に許容する
    ため`"Add"`の意味論が`.extend()`だけで自然に成立する。"""
    prefix = INDENT * indent
    if node.destination is None or node.source is None:
        return [
            f"{prefix}# TODO: MergeDataTable with missing Destination/Source"
        ]
    if node.missing_schema_action not in (None, "Add"):
        return [
            f"{prefix}# TODO: MergeDataTable with unconfirmed "
            f"MissingSchemaAction ({node.missing_schema_action!r}) — only "
            "'Add' is confirmed, refusing to guess"
        ]
    todo: list[str] = []
    destination = _render_value_or_todo(node.destination, prefix, todo)
    source = _render_value_or_todo(node.source, prefix, todo)
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    return [
        f"{prefix}if {source} and isinstance({source}[0], dict):",
        f"{inner}{destination}.extend(dict(_r) for _r in {source})",
        f"{prefix}else:",
        f"{inner}{destination}.extend(list(_r) for _r in {source})",
    ]


# 知見237: .NETカスタム日付書式トークン→Python`strftime()`書式
# トークンの対応表——`DateTimeFormatProvider.Pattern`実機確認済みの
# `"dddd, dd MMMM yyyy"`に必要なトークンのみ確認済みとして対応し、
# 単独の`M`/`d`(ゼロ埋め無し、Windows/Linux間で`%-m`等の移植性問題
# がある)・時刻系トークン(`HH`/`mm`/`ss`/`tt`等、実機未確認)は
# 未対応のまま`_convert_dotnet_date_pattern()`が`None`を返すことで
# コード生成側が`# TODO`へ倒す。
_DOTNET_DATE_TOKEN_MAP = {
    "yyyy": "%Y",
    "yy": "%y",
    "MMMM": "%B",
    "MMM": "%b",
    "MM": "%m",
    "dddd": "%A",
    "ddd": "%a",
    "dd": "%d",
}
_DOTNET_DATE_SPECIFIER_CHARS = "yMdHhmsftz"


def _convert_dotnet_date_pattern(pattern: str) -> str | None:
    result: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch in _DOTNET_DATE_SPECIFIER_CHARS:
            j = i
            while j < n and pattern[j] == ch:
                j += 1
            token = pattern[i:j]
            py_token = _DOTNET_DATE_TOKEN_MAP.get(token)
            if py_token is None:
                return None
            result.append(py_token)
            i = j
        else:
            result.append("%%" if ch == "%" else ch)
            i += 1
    return "".join(result)


_FORMAT_VALUE_NUMBER_KINDS = (
    "GeneralNumberFormatProvider",
    "CurrencyNumberFormatProvider",
)


def _generate_format_value(node: FormatValueNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_format_value_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_format_value_body(node: FormatValueNode, indent: int) -> list[str]:
    """知見237: `Value`は入出力同じ変数へのインプレース変換(実機
    `psri981/Group8-300-762`で`FormatValue`直後に同じ変数を読む代入
    を確認済み)。`GeneralNumberFormatProvider`/
    `CurrencyNumberFormatProvider`は`'{:,.Nf}'.format(_vb_cdbl(value))`
    (`Currency`はさらに`Symbol`を前置)、`DecimalSeparator`/
    `GroupSeparator`はground-truth既定値`"."`/`","`以外は実機で一度も
    確認できず未対応。`DateTimeFormatProvider`は`.strftime()`
    (`Value`は既存の`.NET DateTime`→`datetime.datetime`表現が前提)。"""
    prefix = INDENT * indent
    if node.value is None:
        return [f"{prefix}# TODO: FormatValue with no Value captured"]
    if node.format_kind not in _FORMAT_VALUE_NUMBER_KINDS + ("DateTimeFormatProvider",):
        return [
            f"{prefix}# TODO: FormatValue with unconfirmed/unsupported "
            f"Format type ({node.format_kind!r}) — only "
            "GeneralNumberFormatProvider/CurrencyNumberFormatProvider/"
            "DateTimeFormatProvider are confirmed, refusing to guess"
        ]
    todo: list[str] = []
    value = _render_value_or_todo(node.value, prefix, todo)
    if todo:
        return todo
    if node.format_kind in _FORMAT_VALUE_NUMBER_KINDS:
        if node.decimal_separator not in (None, "."):
            return [
                f"{prefix}# TODO: FormatValue with non-default "
                f"DecimalSeparator ({node.decimal_separator!r}) — only "
                "'.' is confirmed, refusing to guess"
            ]
        if node.group_separator not in (None, ","):
            return [
                f"{prefix}# TODO: FormatValue with non-default "
                f"GroupSeparator ({node.group_separator!r}) — only ',' is "
                "confirmed, refusing to guess"
            ]
        default_digits = (
            "0" if node.format_kind == "CurrencyNumberFormatProvider" else "2"
        )
        decimal_digits = (
            node.decimal_digits if node.decimal_digits is not None else default_digits
        )
        try:
            digits_int = int(decimal_digits)
        except ValueError:
            return [
                f"{prefix}# TODO: FormatValue with non-numeric "
                f"DecimalDigits ({decimal_digits!r}) — refusing to guess"
            ]
        fmt_spec = "{:,." + str(digits_int) + "f}"
        symbol_prefix = f"{node.symbol!r} + " if node.symbol else ""
        return [
            f"{prefix}{value} = {symbol_prefix}{fmt_spec!r}.format("
            f"{VB_CDBL_HELPER_NAME}({value}))"
        ]
    if node.pattern is None:
        return [f"{prefix}# TODO: FormatValue with no Pattern captured"]
    py_pattern = _convert_dotnet_date_pattern(node.pattern)
    if py_pattern is None:
        return [
            f"{prefix}# TODO: FormatValue with unsupported token in "
            f"Pattern ({node.pattern!r}) — refusing to guess"
        ]
    return [f"{prefix}{value} = {value}.strftime({py_pattern!r})"]


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


# 知見188: `ui:MoveFile`(`CopyFile`知見117の正反対)。`shutil.move()`が
# 直接対応する——`CopyFile`と同じ「移動先が既存のディレクトリなら
# ファイル名を付加する」解決ロジック+`Overwrite="False"`時の事前
# 存在チェックをそのまま再利用する(プラットフォーム依存の`shutil.
# move`自体の上書き挙動に頼らず、明示的で予測可能なチェックに揃える)。
def _generate_move_file(node: MoveFileNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_move_file_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_move_file_body(node: MoveFileNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.path is None or node.destination is None:
        return [f"{prefix}# TODO: MoveFile with missing Path/Destination"]
    if node.destination_resource is not None or node.path_resource is not None:
        return [
            f"{prefix}# TODO: MoveFile with DestinationResource/PathResource "
            "set — Integration Service resource handling not confirmed, "
            "refusing to guess"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: MoveFile with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    if node.overwrite not in ("True", "False"):
        return [
            f"{prefix}# TODO: MoveFile with unrecognized/unset Overwrite "
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
    lines.append(f"{prefix}shutil.move(_src, _dest)")
    return lines


def _generate_copy_folder_x(node: CopyFolderXNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_copy_folder_x_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_copy_folder_x_body(node: CopyFolderXNode, indent: int) -> list[str]:
    """知見246: `ui:CopyFolderX`——`CopyFile`(知見117)のフォルダ版、
    `shutil.copytree()`に対応する。`To`が既存ディレクトリの場合は
    `From`のbasenameを付加する(`CopyFile`と同じ解決ロジック、公式
    ドキュメント確認済みの`Overwrite`の意味論「宛先に`From`と同じ名前
    の既存フォルダがあれば置き換える」とも整合する)。`Overwrite=
    "True"`は`dirs_exist_ok=True`(既存ファイルを上書きしつつマージ
    ——宛先に`From`に無い余分なファイルが残り続ける既知の限界、
    完全な削除→再作成ではない)、`"False"`は`CopyFile`と同じ明示的な
    事前存在チェック。"""
    prefix = INDENT * indent
    if node.from_ is None or node.to is None:
        return [f"{prefix}# TODO: CopyFolderX with missing From/To"]
    if node.from_resource is not None or node.to_resource is not None:
        return [
            f"{prefix}# TODO: CopyFolderX with FromResource/ToResource set "
            "— Integration Service resource handling not confirmed, refusing "
            "to guess"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: CopyFolderX with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    if node.include_subfolders != "True":
        return [
            f"{prefix}# TODO: CopyFolderX with IncludeSubfolders "
            f"{node.include_subfolders!r} — only the confirmed \"True\" "
            "default is implemented, refusing to guess False's semantics"
        ]
    if node.overwrite not in ("True", "False"):
        return [
            f"{prefix}# TODO: CopyFolderX with unrecognized/unset Overwrite "
            f"({node.overwrite!r}) — true default behavior not confirmed, "
            "refusing to guess"
        ]
    todo: list[str] = []
    from_ = _render_value_or_todo(node.from_, prefix, todo)
    to = _render_value_or_todo(node.to, prefix, todo)
    if todo:
        return todo
    lines = [
        f"{prefix}_src = {from_}",
        f"{prefix}_dest = {to}",
        f"{prefix}if os.path.isdir(_dest):",
        f"{INDENT * (indent + 1)}_dest = os.path.join(_dest, os.path.basename(_src))",
    ]
    if node.overwrite == "False":
        lines.append(f"{prefix}if os.path.exists(_dest):")
        lines.append(f"{INDENT * (indent + 1)}raise FileExistsError(_dest)")
        lines.append(f"{prefix}shutil.copytree(_src, _dest)")
    else:
        lines.append(f"{prefix}shutil.copytree(_src, _dest, dirs_exist_ok=True)")
    return lines


def _generate_move_folder_x(node: MoveFolderXNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_move_folder_x_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_move_folder_x_body(node: MoveFolderXNode, indent: int) -> list[str]:
    """知見246: `ui:MoveFolderX`——`MoveFile`(知見188)のフォルダ版、
    `shutil.move()`に対応する(`IncludeSubfolders`無し、ground-truth・
    実機いずれも確認済み)。`MoveFile`と同じ「移動先が既存のディレク
    トリなら`From`のbasenameを付加する」解決ロジック+`Overwrite=
    "False"`時の事前存在チェックをそのまま再利用する。"""
    prefix = INDENT * indent
    if node.from_ is None or node.to is None:
        return [f"{prefix}# TODO: MoveFolderX with missing From/To"]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: MoveFolderX with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    if node.overwrite not in ("True", "False"):
        return [
            f"{prefix}# TODO: MoveFolderX with unrecognized/unset Overwrite "
            f"({node.overwrite!r}) — true default behavior not confirmed, "
            "refusing to guess"
        ]
    todo: list[str] = []
    from_ = _render_value_or_todo(node.from_, prefix, todo)
    to = _render_value_or_todo(node.to, prefix, todo)
    if todo:
        return todo
    lines = [
        f"{prefix}_src = {from_}",
        f"{prefix}_dest = {to}",
        f"{prefix}if os.path.isdir(_dest):",
        f"{INDENT * (indent + 1)}_dest = os.path.join(_dest, os.path.basename(_src))",
    ]
    if node.overwrite == "False":
        lines.append(f"{prefix}if os.path.exists(_dest):")
        lines.append(f"{INDENT * (indent + 1)}raise FileExistsError(_dest)")
    lines.append(f"{prefix}shutil.move(_src, _dest)")
    return lines


# 知見188: `ui:PathExists`。`PathType="File"`は`os.path.isfile()`、
# `"Folder"`は`os.path.isdir()`(いずれもPython標準の確認済みAPI)が
# UiPathの種別を区別する意味論に正確に対応する。
def _generate_path_exists(node: PathExistsNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_path_exists_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_path_exists_body(node: PathExistsNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.path is None:
        return [f"{prefix}# TODO: PathExists with no Path captured"]
    if node.exists is None:
        return [f"{prefix}# TODO: PathExists with no output Exists captured"]
    if node.resource is not None:
        return [
            f"{prefix}# TODO: PathExists with Resource set "
            f"({_describe_expr_for_comment(node.resource)}) — Integration "
            "Service resource handling not confirmed, refusing to guess"
        ]
    if node.path_type not in ("File", "Folder"):
        return [
            f"{prefix}# TODO: PathExists with unrecognized/unset PathType "
            f"({node.path_type!r}) — only File/Folder are confirmed, "
            "refusing to guess"
        ]
    check = "os.path.isfile" if node.path_type == "File" else "os.path.isdir"
    todo: list[str] = []
    path = _render_value_or_todo(node.path, prefix, todo)
    target = _render_value_or_todo(node.exists, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}{target} = {check}({path})"]


def _generate_file_exists_x(node: FileExistsXNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_file_exists_x_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_file_exists_x_body(node: FileExistsXNode, indent: int) -> list[str]:
    """知見219: `PathExists`(知見188)の`PathType="File"`固定版と推測
    される——`os.path.isfile()`が直接対応する。"""
    prefix = INDENT * indent
    if node.path is None:
        return [f"{prefix}# TODO: FileExistsX with no Path captured"]
    if node.exists is None:
        return [f"{prefix}# TODO: FileExistsX with no output Exists captured"]
    todo: list[str] = []
    path = _render_value_or_todo(node.path, prefix, todo)
    target = _render_value_or_todo(node.exists, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}{target} = os.path.isfile({path})"]


def _generate_folder_exists_x(node: FolderExistsXNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_folder_exists_x_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_folder_exists_x_body(node: FolderExistsXNode, indent: int) -> list[str]:
    """知見219: `PathExists`(知見188)の`PathType="Folder"`固定版と
    推測される——`os.path.isdir()`が直接対応する。"""
    prefix = INDENT * indent
    if node.path is None:
        return [f"{prefix}# TODO: FolderExistsX with no Path captured"]
    if node.exists is None:
        return [f"{prefix}# TODO: FolderExistsX with no output Exists captured"]
    todo: list[str] = []
    path = _render_value_or_todo(node.path, prefix, todo)
    target = _render_value_or_todo(node.exists, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}{target} = os.path.isdir({path})"]


# 知見189: `ui:DeleteFileX`。`os.remove()`(Python標準の確認済みAPI)が
# 直接対応する。
def _generate_delete_file(node: DeleteFileNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_delete_file_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_delete_file_body(node: DeleteFileNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.path is None:
        return [f"{prefix}# TODO: DeleteFile with no Path captured"]
    todo: list[str] = []
    path = _render_value_or_todo(node.path, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}os.remove({path})"]


# 知見189: `ui:DeleteFolderX`。`Recursive="True"`は`shutil.rmtree()`、
# `"False"`は`os.rmdir()`(空のフォルダのみ削除)——いずれもPython
# 標準の確認済みAPI。
def _generate_delete_folder(node: DeleteFolderNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_delete_folder_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_delete_folder_body(node: DeleteFolderNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.path is None:
        return [f"{prefix}# TODO: DeleteFolder with no Path captured"]
    if node.recursive not in ("True", "False"):
        return [
            f"{prefix}# TODO: DeleteFolder with unrecognized/unset "
            f"Recursive ({node.recursive!r}) — refusing to guess"
        ]
    todo: list[str] = []
    path = _render_value_or_todo(node.path, prefix, todo)
    if todo:
        return todo
    call = "shutil.rmtree" if node.recursive == "True" else "os.rmdir"
    return [f"{prefix}{call}({path})"]


# 知見190: `ui:ForEachFileX`。`CurrentFile`はファイルの絶対パス文字列
# (`.NET FileInfo.FullName`と同じ値)として表現する——`os.scandir()`
# (非再帰)/`os.walk()`(再帰)はいずれもPython標準の確認済みAPI。
# `OrderBy`は実機確認済みの`"NameAscFirst"`(名前昇順)のみ対応し、
# `SkipFolderWithoutPermission="True"`(権限エラーを握り潰す動作、
# 未モデル化)は`# TODO`へ倒す。
def _generate_for_each_file(
    node: ForEachFileNode, indent: int, invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    prefix = INDENT * indent
    if node.order_by not in (None, "NameAscFirst"):
        return [
            f"{prefix}# TODO: ForEachFile with unconfirmed OrderBy "
            f"({node.order_by!r}) — only NameAscFirst is confirmed, "
            "refusing to guess"
        ]
    if node.skip_without_permission == "True":
        return [
            f"{prefix}# TODO: ForEachFile with SkipFolderWithoutPermission "
            "set — permission-error suppression not modeled, refusing to "
            "guess"
        ]
    folder = render_expr(node.folder)
    if node.include_sub_directories == "True":
        entries_expr = (
            f"sorted((os.path.join(_dp, _fn) for _dp, _dns, _fns in "
            f"os.walk({folder}) for _fn in _fns), key=os.path.basename)"
        )
    else:
        entries_expr = (
            f"sorted((_e.path for _e in os.scandir({folder}) if "
            "_e.is_file()), key=os.path.basename)"
        )
    item_var = node.item_var or "CurrentFile"
    index_var = node.index_var or "CurrentIndex"
    lines = [f"{prefix}for {index_var}, {item_var} in enumerate({entries_expr}):"]
    body = _ensure_nonempty_suite(
        _generate_body(node.body, indent + 1, invoke_resolver, out_arg_resolver), indent + 1
    )
    lines.extend(body)
    return lines


# 知見190: `ui:ForEachFolderX`(`ForEachFile`の兄弟活動)。`os.walk()`の
# `dirnames`(各階層での直下の子フォルダのみを返す確認済みの挙動)を
# 利用して、ルート自身を含まない全階層のサブフォルダを列挙する。
def _generate_for_each_folder(
    node: ForEachFolderNode, indent: int, invoke_resolver: dict[str, str] | None = None,
    out_arg_resolver: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    prefix = INDENT * indent
    if node.order_by not in (None, "NameAscFirst"):
        return [
            f"{prefix}# TODO: ForEachFolder with unconfirmed OrderBy "
            f"({node.order_by!r}) — only NameAscFirst is confirmed, "
            "refusing to guess"
        ]
    if node.skip_without_permission == "True":
        return [
            f"{prefix}# TODO: ForEachFolder with SkipFoldersWithoutPermission "
            "set — permission-error suppression not modeled, refusing to "
            "guess"
        ]
    folder = render_expr(node.folder)
    if node.include_sub_folders == "True":
        entries_expr = (
            f"sorted((os.path.join(_dp, _dn) for _dp, _dns, _fns in "
            f"os.walk({folder}) for _dn in _dns), key=os.path.basename)"
        )
    else:
        entries_expr = (
            f"sorted((_e.path for _e in os.scandir({folder}) if "
            "_e.is_dir()), key=os.path.basename)"
        )
    item_var = node.item_var or "CurrentFolder"
    index_var = node.index_var or "CurrentIndex"
    lines = [f"{prefix}for {index_var}, {item_var} in enumerate({entries_expr}):"]
    body = _ensure_nonempty_suite(
        _generate_body(node.body, indent + 1, invoke_resolver, out_arg_resolver), indent + 1
    )
    lines.extend(body)
    return lines


# 知見191: `ui:RenameFileX`。`KeepExtension="True"`の場合、元のファイルの
# 拡張子を`NewName`に付加してから`os.rename()`(Python標準の確認済み
# API)で改名する——`os.path.splitext()`/`os.path.dirname()`という
# 確認済みの標準的な組み合わせ。
def _generate_rename_file(node: RenameFileNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_rename_file_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_rename_file_body(node: RenameFileNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.file_path is None or node.new_name is None:
        return [f"{prefix}# TODO: RenameFile with missing FilePath/NewName"]
    if node.file_resource is not None or node.output_file_resource is not None:
        return [
            f"{prefix}# TODO: RenameFile with FileResource/"
            "OutputFileResource set — Integration Service resource "
            "handling not confirmed, refusing to guess"
        ]
    if node.keep_extension not in ("True", "False"):
        return [
            f"{prefix}# TODO: RenameFile with unrecognized/unset "
            f"KeepExtension ({node.keep_extension!r}) — refusing to guess"
        ]
    todo: list[str] = []
    file_path = _render_value_or_todo(node.file_path, prefix, todo)
    new_name = _render_value_or_todo(node.new_name, prefix, todo)
    if todo:
        return todo
    lines = [f"{prefix}_old = {file_path}", f"{prefix}_new_name = {new_name}"]
    if node.keep_extension == "True":
        lines.append(f"{prefix}_new_name += os.path.splitext(_old)[1]")
    lines.append(
        f"{prefix}os.rename(_old, os.path.join(os.path.dirname(_old), _new_name))"
    )
    return lines


# 知見191: `ui:RenameFolderX`(`RenameFile`の兄弟活動)。`os.rename()`が
# 直接対応する。
def _generate_rename_folder(node: RenameFolderNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_rename_folder_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_rename_folder_body(node: RenameFolderNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.folder_path is None or node.new_name is None:
        return [f"{prefix}# TODO: RenameFolder with missing FolderPath/NewName"]
    todo: list[str] = []
    folder_path = _render_value_or_todo(node.folder_path, prefix, todo)
    new_name = _render_value_or_todo(node.new_name, prefix, todo)
    if todo:
        return todo
    return [
        f"{prefix}_old = {folder_path}",
        f"{prefix}os.rename(_old, os.path.join(os.path.dirname(_old), {new_name}))",
    ]


# 知見191: `ui:CreateFile`。`os.path.join(Path, Name)`で完全パスを組み
# 立て、`open(path, "w").close()`(空ファイルを作成する、Python標準の
# 確認済み手法)で作成する。`Output`は`ForEachFileX`(知見190)と同じ
# 「絶対パス文字列」表現で対応する。
def _generate_create_file(node: CreateFileNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_create_file_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_create_file_body(node: CreateFileNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.path is None or node.name is None:
        return [f"{prefix}# TODO: CreateFile with missing Path/Name"]
    if node.path_resource is not None:
        return [
            f"{prefix}# TODO: CreateFile with PathResource set "
            f"({_describe_expr_for_comment(node.path_resource)}) — "
            "Integration Service resource handling not confirmed, "
            "refusing to guess"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: CreateFile with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    todo: list[str] = []
    path = _render_value_or_todo(node.path, prefix, todo)
    name = _render_value_or_todo(node.name, prefix, todo)
    if todo:
        return todo
    lines = [
        f"{prefix}_full_path = os.path.join({path}, {name})",
        f'{prefix}open(_full_path, "w").close()',
    ]
    if node.output is not None:
        todo2: list[str] = []
        target = _render_value_or_todo(node.output, prefix, todo2)
        if todo2:
            return todo2
        lines.append(f"{prefix}{target} = _full_path")
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


def _generate_start_process(node: StartProcessNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_start_process_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_start_process_body(node: StartProcessNode, indent: int) -> list[str]:
    """知見247: `ui:StartProcess`——`.NET Process.Start()`相当の
    OSレベルプロセス起動。`Arguments`は既存の`OpenApplicationNode`
    (知見154)と同じ理由(Windowsコマンドライン引数の分割規則が未確認)
    で設定時は全体を見送る。`WorkingDirectory`は`subprocess.Popen()`
    の`cwd`引数に直接対応する単純な概念のため確信を持って対応する。
    `ExecutionType`は公式ドキュメント確認済みの既定値`Asynchronous`
    のみ対応(`Synchronous`は実機未確認のため見送る)。"""
    prefix = INDENT * indent
    if node.file_name is None:
        return [f"{prefix}# TODO: StartProcess with no FileName captured"]
    if node.arguments is not None:
        return [
            f"{prefix}# TODO: StartProcess with Arguments set "
            f"({_describe_expr_for_comment(node.arguments)}) — Windows "
            "command-line splitting semantics not confirmed, refusing to guess"
        ]
    if node.continue_on_error is not None:
        return [
            f"{prefix}# TODO: StartProcess with ContinueOnError set "
            f"({_describe_expr_for_comment(node.continue_on_error)}) — "
            "error-continuation mapping not confirmed, refusing to guess"
        ]
    if node.execution_type not in (None, "Asynchronous"):
        return [
            f"{prefix}# TODO: StartProcess with ExecutionType "
            f"{node.execution_type!r} — only the confirmed \"Asynchronous\" "
            "default is implemented, Synchronous wait-with-Timeout semantics "
            "not confirmed in the wild, refusing to guess"
        ]
    try:
        file_name = render_expr(node.file_name)
    except NotImplementedError as e:
        return _todo_value(prefix, str(e))
    todo: list[str] = []
    kwargs = ""
    if node.working_directory is not None:
        working_directory = _render_value_or_todo(node.working_directory, prefix, todo)
        kwargs = f", cwd={working_directory}"
    if todo:
        return todo
    return [
        f"{prefix}subprocess.Popen([{VB_CSTR_HELPER_NAME}({file_name})]{kwargs})"
    ]


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
        elif isinstance(child, WordAppendTextNode):
            lines.extend(
                _with_scope_child_display_name(
                    child, _generate_word_append_text_in_scope(child, indent, var), prefix
                )
            )
        elif isinstance(child, WordSaveAsNode):
            lines.extend(
                _with_scope_child_display_name(
                    child, _generate_word_save_as_in_scope(child, indent, var), prefix
                )
            )
        elif isinstance(child, WordReadTextNode):
            lines.extend(
                _with_scope_child_display_name(
                    child, _generate_word_read_text_in_scope(child, indent, var), prefix
                )
            )
        elif isinstance(child, WordAddImageNode):
            lines.extend(
                _with_scope_child_display_name(
                    child, _generate_word_add_image_in_scope(child, indent, var), prefix
                )
            )
        elif isinstance(child, WordInsertDataTableNode):
            lines.extend(
                _with_scope_child_display_name(
                    child,
                    _generate_word_insert_data_table_in_scope(child, indent, var),
                    prefix,
                )
            )
        elif isinstance(child, WordReplacePictureNode):
            lines.extend(
                _with_scope_child_display_name(
                    child,
                    _generate_word_replace_picture_in_scope(child, indent, var),
                    prefix,
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


# 知見258: `ui:WordAppendText`——実機2件とも`NewLine`属性は現れず、
# 公式ドキュメント確認済みの既定`True`(テキストの前に新しい段落を
# 挿入する)のみ対応する。`python-docx`の`Document.add_paragraph(text)`
# が正確に対応する。
def _generate_word_append_text_in_scope(
    node: WordAppendTextNode, indent: int, scope_var: str
) -> list[str]:
    prefix = INDENT * indent
    if node.text is None:
        return [f"{prefix}# TODO: Word Append Text with no Text captured"]
    if node.new_line not in (None, "True"):
        return [
            f"{prefix}# TODO: Word Append Text with NewLine set "
            f"{node.new_line!r} — only the confirmed default (True) is "
            "implemented, refusing to guess"
        ]
    todo: list[str] = []
    text = _render_value_or_todo(node.text, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}{scope_var}.add_paragraph({VB_CSTR_HELPER_NAME}({text}))"]


# 知見258: `ui:WordSaveAs`——実機2件とも`SaveAsFileType`/
# `ReplaceExisting`属性は現れず、公式ドキュメント確認済みの既定
# (`"XmlDocument"`=.docx、`True`)のみ対応する。スコープ末尾の無条件
# `.save(file_name)`は本活動の有無にかかわらず継続して実行される
# (`WordApplicationScopeNode`のdocstring参照、既知の限界として明示的に
# 受け入れる)。
def _generate_word_save_as_in_scope(
    node: WordSaveAsNode, indent: int, scope_var: str
) -> list[str]:
    prefix = INDENT * indent
    if node.file_path is None:
        return [f"{prefix}# TODO: Word Save As with no FilePath captured"]
    if node.save_as_file_type not in (None, "XmlDocument"):
        return [
            f"{prefix}# TODO: Word Save As with SaveAsFileType set "
            f"{node.save_as_file_type!r} — only the confirmed default "
            '("XmlDocument"/.docx) is implemented, refusing to guess'
        ]
    if node.replace_existing not in (None, "True"):
        return [
            f"{prefix}# TODO: Word Save As with ReplaceExisting set "
            f"{node.replace_existing!r} — only the confirmed default (True) "
            "is implemented, refusing to guess"
        ]
    todo: list[str] = []
    file_path = _render_value_or_todo(node.file_path, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}{scope_var}.save({file_path})"]


# 知見258: `ui:WordReadText`——`"\n".join(p.text for p in
# document.paragraphs)`でドキュメント全文を近似する(表組み等の
# 非段落コンテンツは捕捉しない既知の限界)。
def _generate_word_read_text_in_scope(
    node: WordReadTextNode, indent: int, scope_var: str
) -> list[str]:
    prefix = INDENT * indent
    if node.text is None:
        return [f"{prefix}# TODO: Word Read Text with no output Text captured"]
    try:
        target = render_expr(node.text)
    except NotImplementedError as e:
        return _todo_value(prefix, str(e))
    return [
        f'{prefix}{target} = "\\n".join(_p.text for _p in {scope_var}.paragraphs)'
    ]


# 知見260: `ui:WordAddImage`——実機3件とも確認済みの既定(`InsertRelativeTo
# ="Document"`・`Position="End"`)のみ対応する。`python-docx`の
# `Document.add_picture(image_path)`(公式ドキュメント確認済み:
# 「ドキュメント末尾に新しい段落として画像を追加する」)が正確に
# 対応する。
def _generate_word_add_image_in_scope(
    node: WordAddImageNode, indent: int, scope_var: str
) -> list[str]:
    prefix = INDENT * indent
    if node.image_path is None:
        return [f"{prefix}# TODO: Word Add Image with no ImagePath captured"]
    if node.insert_relative_to not in (None, "Document"):
        return [
            f"{prefix}# TODO: Word Add Image with InsertRelativeTo set "
            f"{node.insert_relative_to!r} — only the confirmed default "
            '("Document") is implemented, refusing to guess'
        ]
    if node.position not in (None, "End"):
        return [
            f"{prefix}# TODO: Word Add Image with Position set "
            f"{node.position!r} — only the confirmed default (\"End\") is "
            "implemented, refusing to guess"
        ]
    todo: list[str] = []
    image_path = _render_value_or_todo(node.image_path, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}{scope_var}.add_picture({image_path})"]


# 知見261: `ui:WordInsertDataTable`——実機2件とも公式ドキュメント確認済み
# の既定(`InsertRelativeTo="Document"`+`Position="Start"`)を使った
# 実例は無く、`InsertRelativeTo="Text"`+`Position`(`"After"`/
# `"Replace"`)のみ確認済み。`Text`で検索した最初の一致段落の直後に
# `python-docx`で構築したテーブルを`addnext()`(標準的なOXML要素移動
# イディオム)で挿入し、`Position="Replace"`の場合は元の段落を削除する。
# プレースホルダが見つからない場合は`None`に対する属性アクセスで自然な
# `AttributeError`を投げる(でっち上げたフォールバック無し)。
def _generate_word_insert_data_table_in_scope(
    node: WordInsertDataTableNode, indent: int, scope_var: str
) -> list[str]:
    prefix = INDENT * indent
    if node.data_table is None:
        return [f"{prefix}# TODO: Word Insert DataTable with no DataTable captured"]
    if node.insert_relative_to != "Text":
        return [
            f"{prefix}# TODO: Word Insert DataTable with InsertRelativeTo set "
            f"{node.insert_relative_to!r} — only the confirmed \"Text\" value "
            "is implemented, refusing to guess"
        ]
    if node.position not in ("After", "Replace"):
        return [
            f"{prefix}# TODO: Word Insert DataTable with Position set "
            f"{node.position!r} — only the confirmed \"After\"/\"Replace\" "
            "values are implemented, refusing to guess"
        ]
    if node.text is None:
        return [f"{prefix}# TODO: Word Insert DataTable with no Text captured"]
    if node.occurrence is not None:
        return [
            f"{prefix}# TODO: Word Insert DataTable with Occurrence set "
            f"{node.occurrence!r} — multi-occurrence semantics not confirmed, "
            "refusing to guess"
        ]
    if node.occurrence_index is not None:
        return [
            f"{prefix}# TODO: Word Insert DataTable with OccurrenceIndex set "
            f"({_describe_expr_for_comment(node.occurrence_index)}) — "
            "semantics not confirmed, refusing to guess"
        ]
    todo: list[str] = []
    rows = _render_value_or_todo(node.data_table, prefix, todo)
    text = _render_value_or_todo(node.text, prefix, todo)
    if todo:
        return todo
    lines = [
        f"{prefix}_rows = {rows}",
        f"{prefix}_target_p = next((_p for _p in {scope_var}.paragraphs "
        f"if {VB_CSTR_HELPER_NAME}({text}) in _p.text), None)",
        f"{prefix}_tbl = {scope_var}.add_table(rows=0, cols=len(_rows[0]) if _rows else 0)",
        f"{prefix}if _rows:",
        f"{INDENT * (indent + 1)}_hdr = _tbl.add_row().cells",
        f"{INDENT * (indent + 1)}for _j, _h in enumerate(_rows[0].keys()):",
        f"{INDENT * (indent + 2)}_hdr[_j].text = {VB_CSTR_HELPER_NAME}(_h)",
        f"{INDENT * (indent + 1)}for _row in _rows:",
        f"{INDENT * (indent + 2)}_cells = _tbl.add_row().cells",
        f"{INDENT * (indent + 2)}for _j, _v in enumerate(_row.values()):",
        f"{INDENT * (indent + 3)}_cells[_j].text = {VB_CSTR_HELPER_NAME}(_v)",
        f"{prefix}_target_p._p.addnext(_tbl._tbl)",
    ]
    if node.position == "Replace":
        lines.append(f"{prefix}_target_p._p.getparent().remove(_target_p._p)")
    return lines


# 知見263: `ui:WordReplacePicture`——`python-docx`にはAlt Text検索/
# 画像置換のための高レベルAPIが存在しないため、OOXMLの
# `<wp:docPr descr="...">`(Alt Text、公式ドキュメント確認済みで
# 大文字小文字を区別しない)→`<pic:blipFill><a:blip r:embed="rIdN">`
# (画像パーツへのリレーションシップID)という低レベル構造を直接
# 操作するイディオム(python-docxコミュニティで広く使われる、
# 画像パーツの`._blob`を直接上書きする——公開APIには存在しない内部
# 属性)を注入ヘルパー関数として実装する。公式ドキュメント確認済みの
# 「一致するすべての画像を置換する」(1件目限定ではない)を再現する。
_WORD_REPLACE_PICTURE_HELPER_NAME = "_word_replace_picture"
_WORD_REPLACE_PICTURE_HELPER_SOURCE = '''\
def _word_replace_picture(doc, alt_text, picture_path):
    ns_wp = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    ns_a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    ns_pic = "http://schemas.openxmlformats.org/drawingml/2006/picture"
    ns_r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with open(picture_path, "rb") as f:
        new_blob = f.read()
    for shape in doc.inline_shapes:
        docPr = shape._inline.find("{%s}docPr" % ns_wp)
        if (docPr.get("descr") or "").lower() != alt_text.lower():
            continue
        blip = (
            shape._inline.find("{%s}graphic" % ns_a)
            .find("{%s}graphicData" % ns_a)
            .find("{%s}pic" % ns_pic)
            .find("{%s}blipFill" % ns_pic)
            .find("{%s}blip" % ns_a)
        )
        rid = blip.get("{%s}embed" % ns_r)
        doc.part.rels[rid].target_part._blob = new_blob
'''


def _generate_word_replace_picture_in_scope(
    node: WordReplacePictureNode, indent: int, scope_var: str
) -> list[str]:
    prefix = INDENT * indent
    if node.picture_alt_text is None:
        return [f"{prefix}# TODO: Word Replace Picture with no PictureAltText captured"]
    if node.picture_path is None:
        return [f"{prefix}# TODO: Word Replace Picture with no PicturePath captured"]
    todo: list[str] = []
    alt_text = _render_value_or_todo(node.picture_alt_text, prefix, todo)
    picture_path = _render_value_or_todo(node.picture_path, prefix, todo)
    if todo:
        return todo
    return [
        f"{prefix}{_WORD_REPLACE_PICTURE_HELPER_NAME}("
        f"{scope_var}, {VB_CSTR_HELPER_NAME}({alt_text}), {picture_path})"
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


def _generate_comment_out(node: CommentOutNode, indent: int) -> list[str]:
    """知見225: `ui:CommentOut`はStudioの「コメントアウト」操作で
    ワークフロー上に残る、`Body`配下を**実行しない**ラッパー——
    `body`の内容は意図的に一切辿らない(辿って通常のコード生成に
    回すと、無効化されているはずの処理が実際に実行されてしまう)。
    コメント1行のみを出力し、`body`が唯一の文だった場合でも
    `_ensure_nonempty_suite`が`pass`を補ってくれる(他の
    コメントのみ`# TODO`行と同じ扱い)。"""
    prefix = INDENT * indent
    label = (node.display_name or "Comment Out").replace("\n", "\\n")
    return [
        f"{prefix}# {label} (ui:CommentOut — disabled in the original "
        "workflow, body intentionally not generated)"
    ]


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

# 知見240: `AddLogFields`/`RemoveLogFields`が同じワークフロー内に1件以上
# ある場合だけ(`scope.has_log_fields`、既存の`LogMessage`出力を変えない
# 後方互換ガード)、関数ローカル`_log_fields`辞書の現在の内容を` | k=v,
# ...`形のサフィックスへ変換してメッセージに付加する。
_LOG_FIELDS_SUFFIX_HELPER_NAME = "_log_fields_suffix"
_LOG_FIELDS_SUFFIX_HELPER_SOURCE = '''\
def _log_fields_suffix(fields):
    if not fields:
        return ""
    return " | " + ", ".join(f"{k}={v}" for k, v in fields.items())
'''


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
    scope = get_active_scope()
    if scope is not None and scope.has_log_fields:
        return [
            f"{prefix}logging.{method}({VB_CSTR_HELPER_NAME}({message}) + "
            f"{_LOG_FIELDS_SUFFIX_HELPER_NAME}(_log_fields))"
        ]
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


# 知見256: `ui:ReadRange`——`ExcelApplicationScope`/`ExcelReadRange`
# (知見97/115)とは別の、スコープ無し単独動作の"Workbook"系活動ファミリー。
# `ExcelApplicationScopeNode`が確立した`openpyxl`基盤をそのまま
# 再利用するが、スコープを介さず自分自身で`load_workbook()`/`close()`を
# 行う(読み取り専用のone-shot操作のため保存不要)。
def _generate_read_range(node: ReadRangeNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_read_range_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_read_range_body(node: ReadRangeNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.workbook_path is None:
        return [f"{prefix}# TODO: Read Range with no WorkbookPath captured"]
    if node.data_table is None:
        return [f"{prefix}# TODO: Read Range with no output DataTable captured"]
    if node.sheet_name is None:
        return [f"{prefix}# TODO: Read Range with no SheetName captured"]
    if node.range is not None and not (
        isinstance(node.range, Literal) and node.range.value == ""
    ):
        return [
            f"{prefix}# TODO: Read Range with non-empty/non-literal Range "
            f"({node.range!r}) — only the whole-used-range default is "
            "confirmed, refusing to guess"
        ]
    add_headers = node.add_headers if node.add_headers is not None else "True"
    if add_headers not in ("True", "False"):
        return [
            f"{prefix}# TODO: Read Range with unrecognized AddHeaders "
            f"({node.add_headers!r}) — refusing to guess"
        ]
    todo: list[str] = []
    workbook_path = _render_value_or_todo(node.workbook_path, prefix, todo)
    sheet_name = _render_value_or_todo(node.sheet_name, prefix, todo)
    target = _render_value_or_todo(node.data_table, prefix, todo)
    if todo:
        return todo
    lines = [
        f"{prefix}_wb = openpyxl.load_workbook({workbook_path})",
        f"{prefix}_ws = _wb[{VB_CSTR_HELPER_NAME}({sheet_name})]",
        f"{prefix}_rows = list(_ws.iter_rows(values_only=True))",
    ]
    if add_headers == "True":
        lines.append(
            f"{prefix}{target} = [dict(zip(_rows[0], _r)) for _r in _rows[1:]] "
            "if _rows else []"
        )
    else:
        lines.append(f"{prefix}{target} = [list(_r) for _r in _rows]")
    lines.append(f"{prefix}_wb.close()")
    return lines


# 知見257: `ui:WriteRange`——`ReadRangeNode`(知見256)と同じスコープ無し
# "Workbook"系活動ファミリーの書き込み側。`ExcelWriteRangeNode`
# (知見115修正済み)が確立した「`Worksheet.cell(row=..., column=...,
# value=...)`による直接セル指定書き込み」を継承するが、スコープ無しの
# 単独活動のため自分自身で`load_workbook()`→書き込み→`.save()`する。
def _generate_write_range(node: WriteRangeNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_write_range_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_write_range_body(node: WriteRangeNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.workbook_path is None:
        return [f"{prefix}# TODO: Write Range with no WorkbookPath captured"]
    if node.data_table is None:
        return [f"{prefix}# TODO: Write Range with no input DataTable captured"]
    if node.sheet_name is None:
        return [f"{prefix}# TODO: Write Range with no SheetName captured"]
    if node.starting_cell is not None and not isinstance(node.starting_cell, Literal):
        return [
            f"{prefix}# TODO: Write Range with dynamic (non-literal) "
            f"StartingCell ({_describe_expr_for_comment(node.starting_cell)}) "
            "— cell position can't be resolved statically, refusing to guess"
        ]
    starting_cell_literal = (
        node.starting_cell.value if isinstance(node.starting_cell, Literal) else ""
    )
    try:
        start_col_letter, start_row = coordinate_from_string(starting_cell_literal or "A1")
        start_col = column_index_from_string(start_col_letter)
    except (ValueError, CellCoordinatesException):
        return [
            f"{prefix}# TODO: Write Range with unparseable StartingCell "
            f"({starting_cell_literal!r}) — refusing to guess"
        ]
    add_headers = node.add_headers if node.add_headers is not None else "False"
    if add_headers not in ("True", "False"):
        return [
            f"{prefix}# TODO: Write Range with unrecognized AddHeaders "
            f"({node.add_headers!r}) — refusing to guess"
        ]
    todo: list[str] = []
    workbook_path = _render_value_or_todo(node.workbook_path, prefix, todo)
    sheet_name = _render_value_or_todo(node.sheet_name, prefix, todo)
    rows = _render_value_or_todo(node.data_table, prefix, todo)
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    inner2 = INDENT * (indent + 2)
    lines = [
        f"{prefix}_wb = openpyxl.load_workbook({workbook_path})",
        f"{prefix}_ws = _wb[{VB_CSTR_HELPER_NAME}({sheet_name})]",
        f"{prefix}_rows = {rows}",
        f"{prefix}if _rows:",
    ]
    if add_headers == "True":
        lines.append(f"{inner}for _j, _h in enumerate(list(_rows[0].keys())):")
        lines.append(
            f"{inner2}_ws.cell(row={start_row}, column={start_col} + _j, value=_h)"
        )
        lines.append(f"{inner}_row0 = {start_row + 1}")
    else:
        lines.append(f"{inner}_row0 = {start_row}")
    lines.append(f"{inner}for _i, _row in enumerate(_rows):")
    lines.append(f"{inner2}for _j, _v in enumerate(_row.values()):")
    lines.append(
        f"{INDENT * (indent + 3)}_ws.cell(row=_row0 + _i, column={start_col} + _j, value=_v)"
    )
    lines.append(f"{prefix}_wb.save({workbook_path})")
    return lines


# 知見259: `ui:ReadCell`/`ui:WriteCell`——`ReadRangeNode`/`WriteRangeNode`
# (知見256/257)と同じスコープ無し"Workbook"系ファミリー。
# `ExcelReadCellNode`/`ExcelWriteCellNode`(知見22/119)が確立した
# `workbook[sheet_name][cell]`添字記法をそのまま再利用するが、スコープ
# 無しの単独活動のため自分自身で`openpyxl.load_workbook()`を呼ぶ。
def _generate_read_cell(node: ReadCellNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_read_cell_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_read_cell_body(node: ReadCellNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.workbook_path is None:
        return [f"{prefix}# TODO: Read Cell with no WorkbookPath captured"]
    if node.cell is None:
        return [f"{prefix}# TODO: Read Cell with no Cell captured"]
    if node.sheet_name is None:
        return [f"{prefix}# TODO: Read Cell with no SheetName captured"]
    if node.result is None:
        return [f"{prefix}# TODO: Read Cell with no output Result captured"]
    todo: list[str] = []
    workbook_path = _render_value_or_todo(node.workbook_path, prefix, todo)
    sheet_name = _render_value_or_todo(node.sheet_name, prefix, todo)
    cell = _render_value_or_todo(node.cell, prefix, todo)
    target = _render_value_or_todo(node.result, prefix, todo)
    if todo:
        return todo
    return [
        f"{prefix}_wb = openpyxl.load_workbook({workbook_path})",
        f"{prefix}{target} = _wb[{VB_CSTR_HELPER_NAME}({sheet_name})][{cell}].value",
        f"{prefix}_wb.close()",
    ]


def _generate_write_cell(node: WriteCellNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_write_cell_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_write_cell_body(node: WriteCellNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.workbook_path is None:
        return [f"{prefix}# TODO: Write Cell with no WorkbookPath captured"]
    if node.cell is None:
        return [f"{prefix}# TODO: Write Cell with no Cell captured"]
    if node.sheet_name is None:
        return [f"{prefix}# TODO: Write Cell with no SheetName captured"]
    todo: list[str] = []
    workbook_path = _render_value_or_todo(node.workbook_path, prefix, todo)
    sheet_name = _render_value_or_todo(node.sheet_name, prefix, todo)
    cell = _render_value_or_todo(node.cell, prefix, todo)
    value = _render_value_or_todo(node.text, prefix, todo)
    if todo:
        return todo
    return [
        f"{prefix}_wb = openpyxl.load_workbook({workbook_path})",
        f"{prefix}_wb[{VB_CSTR_HELPER_NAME}({sheet_name})][{cell}] = "
        f"{VB_CSTR_HELPER_NAME}({value})",
        f"{prefix}_wb.save({workbook_path})",
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


# 知見250: `ui:GetIMAPMailMessages`——`email.message.Message`
# (`imaplib`経由で取得した生メールの標準的な解析先)は`.get("Subject")`
# 形の辞書的アクセスのみで`.Subject`属性アクセスには対応しないため、
# `GetOutlookMailMessages`(知見120)の「生のネイティブオブジェクトを
# そのまま返す」方針が通用しない——実機確認済みの下流アクセス
# (`.Subject`のみ)に絞った最小限の薄いラッパークラスを注入する。
# 知見251: `ui:SaveMailAttachments`向けに`.Attachments`プロパティ
# (`(filename, disposition, part)`タプルのリスト)を追加——実機確認済み
# の`Mail.Attachments.Any`という別の下流利用(知見250で発見)にも
# 対応する土台になる(`.Any`自体のレンダリング対応は対象外)。
_IMAP_MAIL_MESSAGE_HELPER_NAME = "_ImapMailMessage"
_IMAP_MAIL_MESSAGE_HELPER_SOURCE = '''\
class _ImapMailMessage:
    def __init__(self, msg):
        self._msg = msg

    @property
    def Subject(self):
        return self._msg.get("Subject", "")

    @property
    def Attachments(self):
        result = []
        for part in self._msg.walk():
            disposition = part.get_content_disposition()
            if disposition not in ("attachment", "inline"):
                continue
            filename = part.get_filename()
            if not filename:
                continue
            result.append((filename, disposition, part))
        return result
'''

_IMAP_SECURE_CONNECTION_VALUES = (None, "Auto")
_IMAP_ORDER_BY_DATE_VALUES = (None, "NewestFirst", "OldestFirst")


def _generate_get_imap_mail_messages(
    node: GetIMAPMailMessagesNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_get_imap_mail_messages_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_get_imap_mail_messages_body(
    node: GetIMAPMailMessagesNode, indent: int
) -> list[str]:
    """知見250: `imaplib.IMAP4_SSL`(`EnableSSL`+`SecureConnection=
    "Auto"`が確認済みの唯一の組み合わせ、直接SSL接続と解釈)+
    `email.message_from_bytes()`に対応する。`OrderByDate`は公式
    ドキュメント確認済みの既定値`"NewestFirst"`——IMAPの`SEARCH`が
    返す昇順(古い順)のUIDリストを反転して対応する。"""
    prefix = INDENT * indent
    if node.messages is None:
        return [f"{prefix}# TODO: GetIMAPMailMessages with no output Messages captured"]
    if node.server is None or node.port is None or node.email is None:
        return [
            f"{prefix}# TODO: GetIMAPMailMessages with missing Server/Port/Email"
        ]
    password_expr = node.password if node.password is not None else node.secure_password
    if password_expr is None:
        return [
            f"{prefix}# TODO: GetIMAPMailMessages with no Password/"
            "SecurePassword captured"
        ]
    if node.enable_ssl not in (None, "True"):
        return [
            f"{prefix}# TODO: GetIMAPMailMessages with EnableSSL "
            f"{node.enable_ssl!r} — only the confirmed \"True\" value is "
            "implemented, refusing to guess"
        ]
    if node.secure_connection not in _IMAP_SECURE_CONNECTION_VALUES:
        return [
            f"{prefix}# TODO: GetIMAPMailMessages with SecureConnection "
            f"{node.secure_connection!r} — only the confirmed \"Auto\" "
            "value is implemented, refusing to guess"
        ]
    if node.order_by_date not in _IMAP_ORDER_BY_DATE_VALUES:
        return [
            f"{prefix}# TODO: GetIMAPMailMessages with OrderByDate "
            f"{node.order_by_date!r} — refusing to guess"
        ]
    for label, value in (
        ("TimeoutMS", node.timeout_ms),
        ("ClientName", node.client_name),
        ("ClientVersion", node.client_version),
        ("FilterExpression", node.filter_expression),
        ("UseOAuth", node.use_oauth),
    ):
        if value is not None:
            return [
                f"{prefix}# TODO: GetIMAPMailMessages with {label} set "
                f"({_describe_expr_for_comment(value)}) — refusing to guess"
            ]
    if node.ignore_crl not in (None, "False"):
        return [
            f"{prefix}# TODO: GetIMAPMailMessages with IgnoreCRL "
            f"{node.ignore_crl!r} — only the confirmed \"False\" value is "
            "implemented, refusing to guess"
        ]
    todo: list[str] = []
    target = _render_value_or_todo(node.messages, prefix, todo)
    server = _render_value_or_todo(node.server, prefix, todo)
    port = _render_value_or_todo(node.port, prefix, todo)
    email_addr = _render_value_or_todo(node.email, prefix, todo)
    password = _render_value_or_todo(password_expr, prefix, todo)
    mail_folder = (
        _render_value_or_todo(node.mail_folder, prefix, todo)
        if node.mail_folder is not None
        else repr("Inbox")
    )
    top = _render_value_or_todo(node.top, prefix, todo) if node.top is not None else None
    if todo:
        return todo
    search_criteria = "'UNSEEN'" if node.only_unread_messages == "True" else "'ALL'"
    lines = [
        f"{prefix}_imap = imaplib.IMAP4_SSL({VB_CSTR_HELPER_NAME}({server}), "
        f"int({VB_NUM_HELPER_NAME}({port})))",
        f"{prefix}_imap.login({VB_CSTR_HELPER_NAME}({email_addr}), "
        f"{VB_CSTR_HELPER_NAME}({password}))",
        f"{prefix}_imap.select({VB_CSTR_HELPER_NAME}({mail_folder}))",
        f"{prefix}_typ, _imap_data = _imap.search(None, {search_criteria})",
        f"{prefix}_imap_uids = _imap_data[0].split()",
    ]
    if node.order_by_date != "OldestFirst":
        lines.append(f"{prefix}_imap_uids = list(reversed(_imap_uids))")
    if top is not None:
        lines.append(
            f"{prefix}_imap_uids = _imap_uids[:round({VB_CDBL_HELPER_NAME}({top}))]"
        )
    lines.extend(
        [
            f"{prefix}_imap_messages = []",
            f"{prefix}for _imap_uid in _imap_uids:",
            f"{INDENT * (indent + 1)}_typ, _imap_msg_data = _imap.fetch(_imap_uid, '(RFC822)')",
            f"{INDENT * (indent + 1)}_imap_messages.append("
            f"{_IMAP_MAIL_MESSAGE_HELPER_NAME}(email.message_from_bytes(_imap_msg_data[0][1])))",
        ]
    )
    if node.mark_as_read == "True":
        lines.append(f"{INDENT * (indent + 1)}_imap.store(_imap_uid, '+FLAGS', '\\\\Seen')")
    if node.delete_messages == "True":
        lines.append(f"{INDENT * (indent + 1)}_imap.store(_imap_uid, '+FLAGS', '\\\\Deleted')")
        lines.append(f"{prefix}_imap.expunge()")
    lines.extend(
        [
            f"{prefix}_imap.close()",
            f"{prefix}_imap.logout()",
            f"{prefix}{target} = _imap_messages",
        ]
    )
    return lines


def _generate_save_mail_attachments(
    node: SaveMailAttachmentsNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_save_mail_attachments_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_save_mail_attachments_body(
    node: SaveMailAttachmentsNode, indent: int
) -> list[str]:
    """知見251: `ui:SaveMailAttachments`——`_ImapMailMessage.Attachments`
    (知見250・251)を反復し`FolderPath`へ書き出す。公式ドキュメント
    確認済みの「`FolderPath`が存在しない場合は自動作成される」を
    `os.makedirs(..., exist_ok=True)`で再現する。`OverwriteExisting`は
    `"True"`のみ対応——`open(..., "wb")`の既定動作(常に上書き)が
    そのまま意味論と一致するため追加のコードは不要、`"False"`/未設定
    時の重複ファイル名解決は未確認のため見送る。"""
    prefix = INDENT * indent
    if node.message is None or node.folder_path is None:
        return [
            f"{prefix}# TODO: SaveMailAttachments with missing Message/"
            "FolderPath"
        ]
    if node.attachments is not None:
        return [
            f"{prefix}# TODO: SaveMailAttachments with Attachments output "
            f"bound ({_describe_expr_for_comment(node.attachments)}) — "
            "not confirmed in the wild, refusing to guess"
        ]
    if node.overwrite_existing != "True":
        return [
            f"{prefix}# TODO: SaveMailAttachments with OverwriteExisting "
            f"{node.overwrite_existing!r} — only the confirmed \"True\" "
            "value is implemented (duplicate-filename resolution for "
            "False/unset is not confirmed), refusing to guess"
        ]
    if node.exclude_inline_attachments not in (None, "False", "True"):
        return [
            f"{prefix}# TODO: SaveMailAttachments with unrecognized "
            f"ExcludeInlineAttachments ({node.exclude_inline_attachments!r})"
        ]
    todo: list[str] = []
    message = _render_value_or_todo(node.message, prefix, todo)
    folder_path = _render_value_or_todo(node.folder_path, prefix, todo)
    if todo:
        return todo
    inner = INDENT * (indent + 1)
    lines = [
        f"{prefix}os.makedirs({VB_CSTR_HELPER_NAME}({folder_path}), exist_ok=True)",
        f"{prefix}for _attachment_filename, _attachment_disposition, "
        f"_attachment_part in {message}.Attachments:",
    ]
    if node.exclude_inline_attachments == "True":
        lines.append(f"{inner}if _attachment_disposition == 'inline':")
        lines.append(f"{INDENT * (indent + 2)}continue")
    lines.extend(
        [
            f"{inner}_attachment_dest = os.path.join("
            f"{VB_CSTR_HELPER_NAME}({folder_path}), _attachment_filename)",
            f"{inner}with open(_attachment_dest, 'wb') as _attachment_file:",
            f"{INDENT * (indent + 2)}_attachment_file.write("
            "_attachment_part.get_payload(decode=True))",
        ]
    )
    return lines


_MARK_MAIL_AS_READ_X_VALUES = {"Read": "False", "Unread": "True"}


def _generate_mark_mail_as_read_x(
    node: MarkMailAsReadXNode, indent: int
) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_mark_mail_as_read_x_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_mark_mail_as_read_x_body(
    node: MarkMailAsReadXNode, indent: int
) -> list[str]:
    """知見229: `MailMessage`は`GetOutlookMailMessages`(知見120)が
    `win32com.client`経由で生成する生のOutlook COM`MailItem`
    オブジェクトそのもの——新規の型付きオブジェクトモデルは不要で、
    `MailItem.UnRead`ブールプロパティ(Microsoft Learn確認済み)へ
    直接代入するだけで済む。"""
    prefix = INDENT * indent
    if node.mail_message is None or node.mark_as is None:
        return [
            f"{prefix}# TODO: MarkMailAsReadX with missing MailMessage/MarkAs"
        ]
    if node.mark_as not in _MARK_MAIL_AS_READ_X_VALUES:
        return [
            f"{prefix}# TODO: MarkMailAsReadX with unrecognized MarkAs "
            f"({node.mark_as!r}) — refusing to guess"
        ]
    todo: list[str] = []
    mail_message = _render_value_or_todo(node.mail_message, prefix, todo)
    if todo:
        return todo
    unread = _MARK_MAIL_AS_READ_X_VALUES[node.mark_as]
    return [f"{prefix}{mail_message}.UnRead = {unread}"]


def _generate_delete_mail_x(node: DeleteMailXNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_delete_mail_x_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_delete_mail_x_body(node: DeleteMailXNode, indent: int) -> list[str]:
    """知見229: `MailItem.Delete()`(Microsoft Learn確認済み)に対応する。"""
    prefix = INDENT * indent
    if node.mail_message is None:
        return [f"{prefix}# TODO: DeleteMailX with missing MailMessage"]
    todo: list[str] = []
    mail_message = _render_value_or_todo(node.mail_message, prefix, todo)
    if todo:
        return todo
    return [f"{prefix}{mail_message}.Delete()"]


_OUTLOOK_FIND_FOLDER_HELPER_NAME = "_outlook_find_folder"
_OUTLOOK_FIND_FOLDER_HELPER_SOURCE = '''\
def _outlook_find_folder(root, name):
    for f in root.Folders:
        if f.Name == name:
            return f
    for f in root.Folders:
        found = _outlook_find_folder(f, name)
        if found is not None:
            return found
    return None
'''


def _generate_move_mail_x(node: MoveMailXNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines = _generate_move_mail_x_body(node, indent)
    return _with_scope_child_display_name(node, lines, prefix)


def _generate_move_mail_x_body(node: MoveMailXNode, indent: int) -> list[str]:
    """知見229: `MailFolder`の実際の解決アルゴリズムは公式ドキュメント
    に明記が無い——実機の実例が常にInboxと同階層のトップレベル
    フォルダだったことから、デフォルトストアのルート(`GetDefault
    Folder(6).Parent`、`GetOutlookMailMessages`知見120のInbox取得と
    同じ経路)を起点に`_outlook_find_folder`で再帰探索する。見つから
    ない場合は`None`を返し、`MailItem.Move(None)`のCOMエラーに自然に
    委ねる(フォールバック値を捏造しない既存方針、`TextToLeftRight`
    等と同じ)。"""
    prefix = INDENT * indent
    if node.mail_message is None or node.mail_folder is None:
        return [
            f"{prefix}# TODO: MoveMailX with missing MailMessage/MailFolder"
        ]
    todo: list[str] = []
    mail_message = _render_value_or_todo(node.mail_message, prefix, todo)
    mail_folder = _render_value_or_todo(node.mail_folder, prefix, todo)
    if todo:
        return todo
    return [
        f"{prefix}_outlook = win32com.client.Dispatch('Outlook.Application')",
        f"{prefix}_folder = {_OUTLOOK_FIND_FOLDER_HELPER_NAME}("
        "_outlook.GetNamespace('MAPI').GetDefaultFolder(6).Parent, "
        f"{VB_CSTR_HELPER_NAME}({mail_folder}))",
        f"{prefix}{mail_message}.Move(_folder)",
    ]


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
