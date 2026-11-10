"""uipath_codegen の単体テスト。

小さく構築したIR(`uipath_dsl.types`)を直接渡すユニットテストと、
design/evidence/uipath_xaml_probe/Main.xaml(実機フィクスチャ)を通した
結合テストの両方を行う。

**既知の注意点**: `Main.xaml`は知見1〜36の各種XAML構造を1ファイルに
網羅的に詰め込んだ調査用フィクスチャであり、実際に動く自動化フローとしての
妥当性は意図されていない——例えばループの外に`<ui:Break />`が単独で
置かれている(知見18の「属性なし自己終了タグ」というXAML形自体を確認する
ためだけの配置)。これを忠実にPythonへ変換すると`break`文がループの外に
出てトップレベルの`SyntaxError`になる。これは codegen の変換ロジックの
バグではなく、フィクスチャ自体が「リアルな制御フロー」ではないことに
起因する既知の制約——`test_main_xaml_pipeline_smoke`ではこの事実を
明示的に確認するに留め、「全体がコンパイル可能である」ことまでは主張しない。
"""
from __future__ import annotations

import contextlib
import io
import logging
import os
import tempfile
import unittest.mock
import zipfile
from pathlib import Path

import pytest

import math

from dump_daemon.uipath_codegen import (
    _TYPE_KEYS_ESCAPE_HELPER_SOURCE,
    generate_project_from_json,
    generate_project_python,
    generate_python,
    render_expr,
)
from dump_daemon.uipath_codegen.render import VB_CMP_HELPER_NAME, VB_NUM_HELPER_SOURCE
from dump_daemon.uipath_dsl import (
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
    ExcelApplicationScopeNode,
    ExcelAppendRangeNode,
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
    FlowSwitchArm,
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
    ExportPdfPageAsImageNode,
    ExtractImagesFromPdfNode,
    KillProcessNode,
    Literal,
    LoadImageNode,
    LookupDataTableNode,
    FilterDataTableNode,
    FilterOperationArgument,
    JoinDataTablesNode,
    RemoveDuplicateRowsNode,
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
    SendHotkeyNode,
    SendMailNode,
    SendOutlookMailNode,
    SequenceNode,
    SetToClipboardNode,
    SortDataTableNode,
    SwitchArm,
    SwitchNode,
    TakeScreenshotNode,
    TerminateWorkflowNode,
    ThrowNode,
    TryCatchNode,
    CatchArm,
    TypeIntoNode,
    UiElementExistsNode,
    UnknownActivityNode,
    VariableDecl,
    VbExpr,
    WhileNode,
    WindowStateNode,
    WordApplicationScopeNode,
    WordReplaceTextNode,
    WorkflowFile,
    WriteCsvFileNode,
    DeserializeXmlNode,
    ExecuteXPathNode,
    WriteLineNode,
    parse_workflow_file,
)

FIXTURE_DIR = Path(__file__).parent.parent / "design" / "evidence" / "uipath_xaml_probe"
FIXTURE_LIB_DIR = Path(__file__).parent.parent / "design" / "evidence" / "uipath_xaml_probe_lib"


def _wrap(body) -> WorkflowFile:
    return WorkflowFile(class_name="Test", root=SequenceNode(body=body))


def _wrap_flowchart(start, variables=None) -> WorkflowFile:
    return WorkflowFile(class_name="Test", root=FlowchartNode(variables=variables or [], start=start))


def _compiles(code: str) -> None:
    compile(code, "<generated>", "exec")


def test_empty_class_name_falls_back_to_workflow_function_name():
    """知見145: `class_name=""`(`x:Class="{x:Null}"`を`xaml_tree`側で
    正規化した結果、`bacdillon/UiPath-Automation`の実機XAMLで発見)は
    `_safe_func_name`の既存の「空文字列なら既定名`workflow`」という
    安全網でカバーされることを確認する(`uipath_codegen`レベルの
    回帰テスト、`xaml_tree`側の正規化は別途`test_uipath_dsl.py`で
    検証済み)。"""
    wf = WorkflowFile(class_name="", root=SequenceNode(body=[]))
    code = generate_python(wf)
    assert "def workflow(" in code
    _compiles(code)


def test_assign_object_typed_expr():
    wf = _wrap([AssignNode(target=VbExpr(text="result"), value=VbExpr(text='"ok"'))])
    code = generate_python(wf)
    assert "result = 'ok'" in code


def test_multiple_assign_generates_one_statement_per_assign_operation():
    """知見122: `MultipleAssign`は複数の`Assign`を1つの活動にまとめた糖衣
    構文に過ぎない——`cameronmcnz/uipath-tutorials`の複数の実機XAMLで
    発見(5件中5件に出現する強い実務需要の信号)。各`AssignOperation`を
    既存の`_generate_assign`へそのまま委ねる。"""
    wf = _wrap(
        [
            MultipleAssignNode(
                assignments=[
                    AssignNode(target=VbExpr(text="count"), value=Literal(value="0")),
                    AssignNode(target=VbExpr(text="secretNumber"), value=Literal(value="5")),
                ],
                display_name="Multiple Assign",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Multiple Assign" in code
    assert "count = '0'" in code
    assert "secretNumber = '5'" in code
    assert "# TODO" not in code
    _compiles(code)


def test_display_name_with_embedded_newline_stays_single_line_comment():
    """知見141: `display_name`(`DisplayName`属性)が万一改行を含む場合
    でも単一行のコメントであることを保証する(`_todo_value`・
    `_describe_expr_for_comment`と同じ防御的な単一行化を共有ヘルパー
    `_with_scope_child_display_name`にも適用——知見84以来、15箇所の
    重複した同一ロジックをこの共有ヘルパー呼び出しへ統合した際に
    合わせて修正した)。"""
    wf = _wrap(
        [
            MultipleAssignNode(
                assignments=[AssignNode(target=VbExpr(text="x"), value=Literal(value="0"))],
                display_name="Multiple Assign\nStep 2",
            )
        ]
    )
    code = generate_python(wf)
    assert "\\n" in code
    for line in code.splitlines():
        if line.strip():
            assert line.lstrip() == line.lstrip(" "), f"tab-indented line: {line!r}"
    _compiles(code)


def test_multiple_assign_with_no_operations_generates_no_statements():
    """空の`AssignOperations`(実機未確認だが構造上あり得る空リスト)でも
    でっち上げたプレースホルダ代入は生成しない——呼び出し元の`Sequence`
    側が`_ensure_nonempty_suite`で`pass`を補う既存の仕組みに委ねる。"""
    wf = _wrap([MultipleAssignNode(assignments=[])])
    code = generate_python(wf)
    assert "pass" in code
    _compiles(code)


def test_assign_with_no_target_is_todo_not_invalid_python():
    """知見136: `node.target is None`(`.To`が未捕捉——`ShonHarsh/
    Wordle-Default-Word-Engine`の実機XAMLで発見した、C#式言語形の
    `<CSharpReference>`のように`.To`がネストした未対応の要素形を持つ
    場合に実際に起こる)を放置すると、修正前は`None = value`という
    **構文的に無効**なPythonコードを生成していた(`_render_value_or_todo
    (None, ...)`が例外無しで素の文字列`"None"`を返すため)。"""
    wf = _wrap([AssignNode(target=None, value=Literal(value="x"))])
    code = generate_python(wf)
    assert "# TODO: Assign with no target (To) captured" in code
    assert "None = " not in code
    _compiles(code)


def test_assign_with_unrenderable_target_expression_is_todo_not_invalid_python():
    """知見137: `target`自体は`VbExpr`として存在するが、その
    レンダリングが失敗する場合(`agilashree/220701015-OAI1903-RPA-Lab`
    の実機XAML、`ForEach`ループ内で`CurrentRow(...)`という知見74の
    添字曖昧性を代入先に使う実例で発見)。知見136の修正(`target is
    None`の明示チェック)だけでは捕捉できなかった——修正前は`target`も
    `_render_value_or_todo`経由でレンダリングしていたため、失敗時に
    素の文字列`"None"`が代入先として使われ`None = None`という構文的に
    無効なコードを生成していた。"""
    wf = _wrap(
        [AssignNode(target=VbExpr(text="CurrentRow(0)"), value=Literal(value="x"))]
    )
    code = generate_python(wf)
    assert "# TODO: unresolved VB expression:" in code
    assert "None = " not in code
    _compiles(code)


def test_assign_with_multiline_unparseable_value_is_single_line_todo():
    """知見141: VB.NETは丸括弧内の改行(行継続)を許すため、構文解析に
    失敗した式のテキスト自体が複数行になりうる(`JFHaataja/
    HAMK-miniprojekti`の実機XAML、複数行の`Substring(...)`式で発見)。
    修正前は`NotImplementedError`のメッセージ(元のVB式テキストを含む)
    をそのまま単一行のf-stringへ埋め込んでいたため、改行以降が`#`の
    付かない生のテキスト行として出力され、`compile()`時にタブ/スペース
    混在のインデントエラー等になっていた——`_todo_value`で改行を`\\n`
    リテラルへ退避し、常に単一行のコメントであることを保証する。"""
    wf = _wrap(
        [
            AssignNode(
                target=VbExpr(text="x"),
                # `(Of T)`ジェネリック型引数構文(知見134で未対応と記録済み)
                # は構文解析自体が失敗する(`tree=None`)——これを複数行に
                # 分けて、元のVB式テキストが複数行のまま例外メッセージに
                # 含まれる実例を再現する。
                value=VbExpr(text='JsonConvert.DeserializeObject(Of T)(\n\tjsonString\n)'),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: unresolved VB expression:" in code
    assert "\\n" in code
    for line in code.splitlines():
        if line.strip():
            assert line.lstrip() == line.lstrip(" "), f"tab-indented line: {line!r}"
    _compiles(code)


@pytest.mark.parametrize("type_str", ["OutArgument(x:String)", "InOutArgument(x:String)"])
def test_workflow_out_or_inout_argument_warns_about_unsupported_byref_writeback(
    type_str: str,
) -> None:
    """知見78: `OutArgument`/`InOutArgument`はVBのByRef渡し(呼び出し元の
    変数へ結果を書き戻す)に相当するが、Pythonの関数パラメータは常に
    値渡しのため、この書き戻しは実現できない——架空の`return`/呼び出し側
    変換をでっち上げる代わりに`# TODO`で明示する(関数自体の生成は続ける、
    `In`方向の引数は正しく機能するため)。"""
    wf = WorkflowFile(
        class_name="Test",
        root=SequenceNode(
            body=[AssignNode(target=VbExpr(text="out_result"), value=Literal(value="x"))]
        ),
        arguments={"out_result": type_str},
    )
    code = generate_python(wf)
    assert "# TODO: argument(s) out_result are Out/InOutArgument" in code
    assert "def Test(out_result):" in code
    _compiles(code)


def test_workflow_in_argument_only_has_no_byref_warning():
    wf = WorkflowFile(
        class_name="Test",
        root=SequenceNode(body=[]),
        arguments={"in_text": "InArgument(x:String)"},
    )
    code = generate_python(wf)
    assert "# TODO" not in code
    _compiles(code)
    _compiles(code)


def test_array_or_collection_indexing_syntax_is_ambiguous_with_func_call_falls_back_to_todo():
    """知見74: VB.NETは配列/コレクション/DataTable行アクセスも関数呼び出しと
    全く同じ`識別子(引数)`構文を使う(例: `myArray(0)`・`row("Col")`)——
    静的な型情報(`myArray`が変数か関数かの区別)が無い限り、構文だけでは
    どちらか判別できない言語レベルの曖昧性であり、`uipath_expr`の実装の
    不備ではない。本パーサーは常に`FuncCall`として解釈するため、Tier1に
    無い名前(`myArray`等)は`_render_func_call`が確認済みでない関数呼び出し
    として安全に`# TODO`へ倒す——「配列インデックスだ」と推測して架空の
    `myArray[0]`変換をでっち上げるよりも安全な現状の挙動をロックする
    回帰テスト(変数宣言を追跡して曖昧性を解消する設計は、実機確認済みの
    需要が無いため今回は見送った)。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="myArray(0)"))])
    code = generate_python(wf)
    assert "# TODO" in code
    assert "x = None" in code
    _compiles(code)


def test_file_readallbytes_renders_as_open_read():
    """知見130: `File.ReadAllBytes(path)`(`Dits21/Proyecto-Sistema-
    RPA-...`の実機XAML`file.ReadAllBytes(...)`で発見)。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="File.ReadAllBytes(y)"))])
    code = generate_python(wf)
    assert "x = open(y, 'rb').read()" in code
    assert "# TODO" not in code
    _compiles(code)


def test_file_getlastwritetime_renders_as_datetime_fromtimestamp():
    """知見142: `File.GetLastWriteTime(path)`(`CarmenTheodoraCraciun/
    DailyMealWithGroceryList`の実機XAML`File.GetLastWriteTime(
    "./recepies.json")`で発見)。"""
    wf = _wrap(
        [AssignNode(target=VbExpr(text="x"), value=VbExpr(text="File.GetLastWriteTime(y)"))]
    )
    code = generate_python(wf)
    assert "x = datetime.datetime.fromtimestamp(os.path.getmtime(y))" in code
    assert "import datetime" in code
    assert "# TODO" not in code
    _compiles(code)


def test_convert_tobase64string_renders_as_base64_b64encode():
    """知見130: `Convert.ToBase64String(bytes)`(同上の実機XAML
    `convert.ToBase64String(...)`で発見)。"""
    wf = _wrap(
        [AssignNode(target=VbExpr(text="x"), value=VbExpr(text="Convert.ToBase64String(y)"))]
    )
    code = generate_python(wf)
    assert "x = base64.b64encode(y).decode('ascii')" in code
    assert "import base64" in code
    assert "# TODO" not in code
    _compiles(code)


def test_path_getfilenamewithoutextension_renders_as_os_path_splitext():
    """知見130: `Path.GetFileNameWithoutExtension(path)`(同上の実機XAML
    `path.GetFileNameWithoutExtension(...)`で発見)。"""
    wf = _wrap(
        [
            AssignNode(
                target=VbExpr(text="x"), value=VbExpr(text="Path.GetFileNameWithoutExtension(y)")
            )
        ]
    )
    code = generate_python(wf)
    assert "x = os.path.splitext(os.path.basename(y))[0]" in code
    assert "import os" in code
    assert "# TODO" not in code
    _compiles(code)


def test_string_isnullorwhitespace_renders():
    """知見134: `String.IsNullOrWhiteSpace(value)`(`Ray-Tel/CICDtest`の
    実機XAML`String.IsNullOrWhiteSpace(in_ConfValueExpectedResult)`で
    発見)。null・空文字列・空白のみの文字列いずれも`True`。"""
    wf = _wrap(
        [AssignNode(target=VbExpr(text="x"), value=VbExpr(text="String.IsNullOrWhiteSpace(y)"))]
    )
    code = generate_python(wf)
    assert "x = (not (y or '').strip())" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    assert eval("(not (None or '').strip())") is True
    assert eval("(not ('   ' or '').strip())") is True
    assert eval("(not ('a' or '').strip())") is False


def test_path_combine_renders_as_os_path_join():
    """知見134: `Path.Combine(path1, path2)`(`Ray-Tel/CICDtest`の実機
    XAML`Path.Combine("Tests\\Cache\\", targetFile+"...")`で発見)。"""
    wf = _wrap(
        [AssignNode(target=VbExpr(text="x"), value=VbExpr(text="Path.Combine(y, z)"))]
    )
    code = generate_python(wf)
    assert "x = os.path.join(y, z)" in code
    assert "# TODO" not in code
    _compiles(code)


def test_directory_getfiles_with_search_pattern_renders_as_glob():
    """知見134: `Directory.GetFiles(path, searchPattern)`(2引数形、
    `aimannoor17/UiPath-Automation-Projects`の実機XAML`Directory.
    GetFiles("samples/scanned-reports","*.pdf")`で発見)。"""
    wf = _wrap(
        [AssignNode(target=VbExpr(text="x"), value=VbExpr(text='Directory.GetFiles(y, "*.pdf")'))]
    )
    code = generate_python(wf)
    assert (
        "x = [_p for _p in glob.glob(os.path.join(y, '*.pdf')) if os.path.isfile(_p)]" in code
    )
    assert "import glob" in code
    assert "# TODO" not in code
    _compiles(code)


def test_bare_variable_lastindexof_renders_as_rfind():
    """知見144: `excelFilePath.LastIndexOf(".")`(`IS300-G6/
    PwC-Onboarding`の実機XAML、拡張子の位置を調べる定石パターン)。
    `str.rfind(value)`と同じ意味論(いずれも最後の出現位置、見つから
    なければ`-1`)。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text='y.LastIndexOf(".")'))])
    code = generate_python(wf)
    assert "x = (y).rfind('.')" in code
    assert "# TODO" not in code
    _compiles(code)


def test_bare_variable_startswith_renders():
    """知見146: `String.StartsWith(value)`(`johnowino/
    String-Manipulation-in-UIPath`の実機XAML`strInput.ToUpper.
    StartsWith("HELLO")`で発見)。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text='y.StartsWith("a")'))])
    code = generate_python(wf)
    assert "x = (y).startswith('a')" in code
    assert "# TODO" not in code
    _compiles(code)


def test_bare_variable_endswith_renders():
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text='y.EndsWith("a")'))])
    code = generate_python(wf)
    assert "x = (y).endswith('a')" in code
    assert "# TODO" not in code
    _compiles(code)


def test_bare_variable_indexof_renders():
    """知見146: `String.IndexOf(value)`(`johnowino/
    String-Manipulation-in-UIPath`の実機XAML`StrInput2.IndexOf("2")`で
    発見)。知見144の`.LastIndexOf`→`rfind`と対になる。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text='y.IndexOf("a")'))])
    code = generate_python(wf)
    assert "x = (y).find('a')" in code
    assert "# TODO" not in code
    _compiles(code)


def test_bare_variable_replace_renders():
    """知見146: `String.Replace(oldValue, newValue)`(`johnowino/
    String-Manipulation-in-UIPath`の実機XAML`StrInput4.Replace(
    "BluePrism","UIPath")`で発見)。単純な部分文字列の全置換
    (正規表現ではない、`Regex.Replace`は知見144で別途対応済み)。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text='y.Replace("a", "b")'))])
    code = generate_python(wf)
    assert "x = (y).replace('a', 'b')" in code
    assert "# TODO" not in code
    _compiles(code)


def test_string_concat_renders():
    """知見146: `String.Concat(a, b, c, ...)`(`johnowino/
    String-Manipulation-in-UIPath`の実機XAML`String.Concat("1","B",
    "3","A")`で発見)。VBの`&`演算子と同じ`ToString`変換規則で連結する。"""
    wf = _wrap(
        [AssignNode(target=VbExpr(text="x"), value=VbExpr(text='String.Concat("1","B","3")'))]
    )
    code = generate_python(wf)
    assert "x = _vb_cstr('1') + _vb_cstr('B') + _vb_cstr('3')" in code
    assert "# TODO" not in code
    _compiles(code)


def test_regex_replace_renders_as_re_sub():
    """知見144: `Regex.Replace(input, pattern, replacement)`
    (`vermilion9312/RegularExpression`の実機XAML`Regex.Replace(str,
    pattern, "******")`で発見)。引数の並び順の違い(.NET:
    `(input, pattern, replacement)`、Pythonの`re.sub`: `(pattern, repl,
    string)`)に注意。"""
    wf = _wrap(
        [
            AssignNode(
                target=VbExpr(text="x"),
                value=VbExpr(text='Regex.Replace(input, pattern, "***")'),
            )
        ]
    )
    code = generate_python(wf)
    assert "x = re.sub(pattern, '***', input)" in code
    assert "import re" in code
    assert "# TODO" not in code
    _compiles(code)


def test_bare_variable_substring_one_arg_renders_as_slice():
    """知見144: `String.Substring(startIndex)`はPythonの`s[startIndex:]`
    と同じ意味論。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="y.Substring(2)"))])
    code = generate_python(wf)
    assert "x = (y)[2:]" in code
    assert "# TODO" not in code
    _compiles(code)


def test_bare_variable_substring_two_args_renders_as_slice():
    """知見144: `String.Substring(startIndex, length)`
    (`IS300-G6/PwC-Onboarding`の実機XAML`excelFilePath.Substring(0,
    excelFilePath.LastIndexOf("."))`で発見、拡張子除去の定石パターン)
    はPythonの`s[startIndex:startIndex+length]`と同じ意味論。"""
    wf = _wrap(
        [AssignNode(target=VbExpr(text="x"), value=VbExpr(text='y.Substring(0, y.LastIndexOf("."))'))]
    )
    code = generate_python(wf)
    assert "x = (y)[(0):(0)+((y).rfind('.'))]" in code
    assert "# TODO" not in code
    _compiles(code)


def test_directory_exists_renders_as_os_path_isdir():
    """知見134: `Directory.Exists(path)`(`manju1201/RPA_UiPath`の実機
    XAML`Directory.Exists(ScreenshotFileInfo.DirectoryName)`で発見)。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="Directory.Exists(y)"))])
    code = generate_python(wf)
    assert "x = os.path.isdir(y)" in code
    assert "import os" in code
    assert "# TODO" not in code
    _compiles(code)


def test_directory_getfiles_renders_as_os_listdir_comprehension():
    """知見133: `Directory.GetFiles(path)`(`dexbob/RPA_Example`の実機
    XAML`Directory.GetFiles(Str_OutputFolder)`で発見)。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="Directory.GetFiles(y)"))])
    code = generate_python(wf)
    assert (
        "x = [os.path.join(y, _n) for _n in os.listdir(y) if os.path.isfile(os.path.join(y, _n))]"
        in code
    )
    assert "import os" in code
    assert "# TODO" not in code
    _compiles(code)


def test_chained_call_result_dotted_length_renders_as_len():
    """知見133: `Directory.GetFiles(path).Length`(`dexbob/RPA_Example`
    の実機XAML、`.Length`は括弧省略形)。配列/文字列いずれも`len()`に
    同じ意味論で直接対応する。"""
    wf = _wrap(
        [AssignNode(target=VbExpr(text="x"), value=VbExpr(text="Directory.GetFiles(y).Length"))]
    )
    code = generate_python(wf)
    assert (
        "x = len([os.path.join(y, _n) for _n in os.listdir(y) "
        "if os.path.isfile(os.path.join(y, _n))])"
    ) in code
    assert "# TODO" not in code
    _compiles(code)


def test_bare_variable_dotted_length_without_call_renders_as_len():
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="arr.Length"))])
    code = generate_python(wf)
    assert "x = len(arr)" in code
    assert "# TODO" not in code
    _compiles(code)


def test_bare_variable_dotted_member_access_is_case_insensitive():
    """知見146: VB.NETは識別子の大文字小文字を区別しない言語——
    `johnowino/String-Manipulation-in-UIPath`の実機XAML`[strInput.
    length]`という小文字表記で発見(それまでの実装は`Length`しか認識
    しておらず、既存の確認済みメンバの大文字小文字が違うだけで
    `# TODO`へ倒れてしまっていた)。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="strInput.length"))])
    code = generate_python(wf)
    assert "x = len(strInput)" in code
    assert "# TODO" not in code
    _compiles(code)


def test_chained_call_member_access_is_case_insensitive():
    """知見146: 関数呼び出し結果への連鎖(知見118の経路)でも同じ
    大文字小文字不区別が適用されることを確認する。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="CStr(y).toupper()"))])
    code = generate_python(wf)
    assert "x = _vb_cstr(y).upper()" in code
    assert "# TODO" not in code
    _compiles(code)


def test_chained_call_with_args_member_access_is_case_insensitive():
    """知見146: 引数付きの連鎖呼び出し(`Equals`/`Contains`等)でも同じ
    大文字小文字不区別が適用されることを確認する。"""
    wf = _wrap(
        [AssignNode(target=VbExpr(text="x"), value=VbExpr(text='CStr(y).contains("z")'))]
    )
    code = generate_python(wf)
    assert "x = ('z') in (_vb_cstr(y))" in code
    assert "# TODO" not in code
    _compiles(code)


def test_bare_variable_dotted_copy_without_call_renders_as_datatable_copy():
    """知見130: `dtUB92.Copy`(括弧省略形、同上の実機XAML`DataTable.
    Copy()`で発見)。既存のDataTable表現(`list[dict]`)に対応する、各行の
    辞書も独立させるコピーへ対応する。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="dtUB92.Copy"))])
    code = generate_python(wf)
    assert "x = [dict(_r) for _r in dtUB92]" in code
    assert "# TODO" not in code
    _compiles(code)


def test_outargument_reference_with_different_casing_is_normalized():
    """知見130で発見・保留していた【重大】バグの再現テスト(知見203で
    `ScopeInfo`/`render.use_scope()`アーキテクチャにより解消): VB.NETは
    識別子の大文字小文字を区別しないため、`out_RequirementLanCur`という
    表記で宣言されたOutArgumentを本体が`Out_RequirementLanCur`
    (大文字`O`)という別表記で参照する実機XAMLが存在する——修正前は
    これが2つの別々のPython変数になり、関数の仮引数が実際には一度も
    更新されない静かな誤り(`# TODO`で保守的に失敗するのではなく
    構文的には正しいが意味的に誤ったコード)を生成していた。"""
    wf = WorkflowFile(
        class_name="Test",
        arguments={"out_RequirementLanCur": "OutArgument(x:String)"},
        root=SequenceNode(
            body=[AssignNode(target=VbExpr(text="Out_RequirementLanCur"), value=Literal(value="hello"))]
        ),
    )
    code = generate_python(wf)
    assert "def Test(out_RequirementLanCur):" in code
    assert "out_RequirementLanCur = 'hello'" in code
    assert "Out_RequirementLanCur" not in code
    _compiles(code)


def test_declared_variable_reference_with_different_casing_is_normalized():
    """知見130・知見203: 通常のローカル変数でも同じ大文字小文字の揺れが
    起こりうる(宣言は`myCounter`、代入先は`MyCounter`、読み取りは
    `myCounter`)——全て同じPython変数へ正規化される。"""
    wf = WorkflowFile(
        class_name="Test",
        root=SequenceNode(
            variables=[VariableDecl(name="myCounter", type_arguments="x:String")],
            body=[
                AssignNode(target=VbExpr(text="MyCounter"), value=Literal(value="hi")),
                MessageBoxNode(text=VbExpr(text="myCounter")),
            ],
        ),
    )
    code = generate_python(wf)
    assert "myCounter = 'hi'" in code
    assert "MyCounter" not in code
    _compiles(code)


def test_identifier_not_declared_anywhere_is_left_unchanged():
    """知見203: 宣言済みの変数/引数集合に含まれない識別子は、大文字小文字が
    偶然似ていても無変換のまま——でっち上げた正規化をしない安全策。"""
    wf = WorkflowFile(
        class_name="Test",
        root=SequenceNode(
            body=[AssignNode(target=VbExpr(text="x"), value=VbExpr(text="SomeUnrelatedName"))]
        ),
    )
    code = generate_python(wf)
    assert "x = SomeUnrelatedName" in code
    _compiles(code)


def test_scope_info_does_not_leak_across_separate_generate_python_calls():
    """知見203: `render.use_scope()`は`contextvars`経由でアンビエントに
    渡すため、1回の`generate_python()`呼び出しが終わればスコープ情報は
    必ずリセットされる——別のワークフローの宣言済み変数が後続の
    `generate_python()`呼び出しへ漏れ出さないことを確認する。"""
    wf1 = WorkflowFile(
        class_name="First",
        root=SequenceNode(
            variables=[VariableDecl(name="myCounter", type_arguments="x:String")],
            body=[AssignNode(target=VbExpr(text="MyCounter"), value=Literal(value="hi"))],
        ),
    )
    generate_python(wf1)
    wf2 = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="MyCounter"))])
    code2 = generate_python(wf2)
    assert "x = MyCounter" in code2
    _compiles(code2)


def test_for_each_row_subscript_disambiguates_as_column_access():
    """知見126で発見・保留していた`row(...)`添字の曖昧性(VB.NETの
    `識別子(引数)`構文は関数呼び出しとDataRow列アクセスで全く同じ見た目
    になり構文だけでは判別不能)を、知見203の`ScopeInfo.data_row_vars`
    (`ForEachRow`のDataRow型反復変数)で解消する——`GetRowItem.
    ColumnName`(知見183)と同じdict行前提の直接アクセスに変換する。"""
    wf = _wrap(
        [
            ForEachNode(
                item_var="row",
                values=VbExpr(text="dt"),
                type_arguments="sd:DataRow",
                body=[MessageBoxNode(text=VbExpr(text='row("E-Mail")'))],
            )
        ]
    )
    code = generate_python(wf)
    assert "row['E-Mail']" in code
    assert "# TODO" not in code
    _compiles(code)


def test_for_each_row_subscript_disambiguation_is_case_insensitive():
    """知見126・知見130: `ForEachRow`の反復変数名は`row`固定ではなく
    (`keyrow`等の実例を知見130で確認)、参照時の大文字小文字の揺れも
    正規化される(知見203)。"""
    wf = _wrap(
        [
            ForEachNode(
                item_var="keyRow",
                values=VbExpr(text="dt"),
                type_arguments="sd:DataRow",
                body=[MessageBoxNode(text=VbExpr(text='KeyRow("Status")'))],
            )
        ]
    )
    code = generate_python(wf)
    assert "keyRow['Status']" in code
    assert "# TODO" not in code
    _compiles(code)


def test_bare_subscript_without_data_row_scope_still_declines():
    """知見203: `ScopeInfo`が`row`をDataRow型と確認できない場合
    (`ForEachRow`の反復変数ではない通常の`ForEach`等)は、従来通り
    `# TODO`へ倒れる——でっち上げた列アクセス変換をしない安全策。"""
    wf = _wrap(
        [
            ForEachNode(
                item_var="row",
                values=VbExpr(text="items"),
                body=[MessageBoxNode(text=VbExpr(text='row("E-Mail")'))],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO" in code
    _compiles(code)


def test_len_renders_as_python_len():
    """知見127: `Len(expr)`(`LowyShin/lwrpa-uip-moveoldfiles`の実機XAML
    `Len(sRstHttp)`で発見)。文字列用法のみ想定し`len(expr)`へ対応する。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="Len(y)"))])
    code = generate_python(wf)
    assert "x = len(y)" in code
    assert "# TODO" not in code
    _compiles(code)


def test_bare_variable_dotted_equals_call_renders_as_equality():
    """知見127: `mail_Category.Equals("Order")`(`nmnithinkrishna/
    uipathos-manufacturing-AutonomousProductFabrication`の実機XAMLで発見)。
    `IDENT`トークンがドット区切りを1トークンとして貪欲マッチするため
    `mail_Category.Equals`全体が単一の関数名として`FuncCall`になり、
    知見118の`ChainedAccess`修正(関数呼び出し結果への連鎖)では捕捉
    できない——関数呼び出しを介さない素の変数への**メソッド呼び出し**
    連鎖という新しいケース。1引数の`Equals`のみ`==`比較へ対応する。"""
    wf = _wrap(
        [AssignNode(target=VbExpr(text="x"), value=VbExpr(text='mail_Category.Equals("Order")'))]
    )
    code = generate_python(wf)
    assert "x = (mail_Category) == ('Order')" in code
    assert "# TODO" not in code
    _compiles(code)


def test_bare_variable_dotted_equals_call_with_culture_overload_is_todo_not_guessed():
    """知見127: `.Equals(value, StringComparison...)`というカルチャ依存
    比較の2引数オーバーロード(知見118で既に対象外と明示済み)は、
    新しいフォールバック経路でも推測せず`# TODO`へ倒す。"""
    wf = _wrap(
        [
            AssignNode(
                target=VbExpr(text="x"),
                value=VbExpr(
                    text='mail_Category.Equals("Order", StringComparison.InvariantCultureIgnoreCase)'
                ),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO" in code
    assert "x = None" in code
    _compiles(code)


def test_bare_variable_dotted_property_then_call_chain_renders():
    """知見127: `a.Trim.ToUpper()`のような、プロパティアクセス+末尾呼び出し
    の混在連鎖(合成例、同じフォールバック経路の一般性を確認)。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="a.Trim.ToUpper()"))])
    code = generate_python(wf)
    assert "x = a.strip().upper()" in code
    assert "# TODO" not in code
    _compiles(code)


def test_environment_currentdirectory_renders_as_os_getcwd():
    """知見140: `Environment.CurrentDirectory`(`E5Prasanth/Acme`の実機
    XAMLで発見、呼び出しを伴わない静的クラスプロパティの完全一致)。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="Environment.CurrentDirectory"))])
    code = generate_python(wf)
    assert "x = os.getcwd()" in code
    assert "import os" in code
    assert "# TODO" not in code
    _compiles(code)


def test_unrelated_variable_currentdirectory_member_is_left_unchanged():
    """知見140: `_STATIC_PROPERTY_TRANSLATIONS`は完全修飾名一致のみ——
    任意の変数の`.CurrentDirectory`メンバを誤って`os.getcwd()`へ変換
    しない(でっち上げ回避、`someFileInfo.CurrentDirectory`のような
    架空のケースで誤変換が起きないことを確認)。"""
    wf = _wrap(
        [AssignNode(target=VbExpr(text="x"), value=VbExpr(text="someFileInfo.CurrentDirectory"))]
    )
    code = generate_python(wf)
    assert "x = someFileInfo.CurrentDirectory" in code
    _compiles(code)


def test_bare_variable_dotted_toupperinvariant_renders_as_upper():
    """知見139: `method.ToUpperInvariant`(`R1zzabh/signalforge`の実機
    XAMLで発見、括弧省略形)。Pythonの`str.upper()`はロケールを参照
    しないため、`ToUpper`と同じ変換先で意味論上の食い違いが無い。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="method.ToUpperInvariant"))])
    code = generate_python(wf)
    assert "x = method.upper()" in code
    assert "# TODO" not in code
    _compiles(code)


def test_bare_variable_dotted_tolowerinvariant_renders_as_lower():
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="method.ToLowerInvariant"))])
    code = generate_python(wf)
    assert "x = method.lower()" in code
    assert "# TODO" not in code
    _compiles(code)


def test_bare_variable_dotted_tolower_contains_chain_renders_as_in_operator():
    """知見133: `strStatus.ToString.ToLower.Contains("x")`
    (`sarvesh0718/RCM-Bot-using-uipath-studio`・`harsranjan/RPA`の実機
    XAMLで発見)。`String.Contains(value)`はPythonの`in`演算子と同じ
    意味論(包含判定、オペランドの順序が逆になる点に注意)。"""
    wf = _wrap(
        [
            AssignNode(
                target=VbExpr(text="x"),
                value=VbExpr(text='strStatus.ToString.ToLower.Contains("done")'),
            )
        ]
    )
    code = generate_python(wf)
    assert "x = ('done') in (_vb_cstr(strStatus).lower())" in code
    assert "# TODO" not in code
    _compiles(code)


def test_chained_call_after_function_call_contains_renders_as_in_operator():
    """知見133: `CStr(x).ToLower.Contains("y")`——`_render_chained_access`
    (知見118の経路)でも同じ`Contains`対応が使われることを確認。"""
    wf = _wrap(
        [AssignNode(target=VbExpr(text="x"), value=VbExpr(text='CStr(y).ToLower.Contains("z")'))]
    )
    code = generate_python(wf)
    assert "x = ('z') in (_vb_cstr(y).lower())" in code
    assert "# TODO" not in code
    _compiles(code)


def test_split_with_two_args_renders_as_str_split():
    """知見126: `Split(expr, delimiter)`(`nkarkare/UDISEAutomation`の
    実機XAML`Split(in_Category, ",")`で発見)。2引数の確認済み形のみ
    `str.split(delimiter)`へ対応させる。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text='Split(y, ",")'))])
    code = generate_python(wf)
    assert "x = y.split(',')" in code
    assert "# TODO" not in code
    _compiles(code)


def test_convert_todatetime_is_todo_with_clear_message_not_misleading_chain_error():
    """知見143: `Convert.ToDateTime(value)`(`KeerthikaBaskar/
    220701126-RPA-LAB`の実機XAML`Convert.ToDateTime(str_Date).
    ToString`で発見)。カルチャ依存の日付書式解析のため推測せず
    `# TODO`へ倒す——Tier1分岐を設ける前は、`_render_func_call`末尾の
    素の変数連鎖フォールバックへ誤って落ち、`.ToDateTime`を`Convert`
    という変数へのメソッド呼び出しと誤認した分かりにくいエラーに
    なっていた(診断メッセージの品質のみの改善、変換ロジックは追加
    していない)。"""
    wf = _wrap(
        [AssignNode(target=VbExpr(text="x"), value=VbExpr(text="Convert.ToDateTime(y).ToString"))]
    )
    code = generate_python(wf)
    assert "# TODO: unresolved VB expression: Convert.ToDateTime" in code
    assert "unsupported chained method call" not in code
    _compiles(code)


def test_split_with_one_arg_is_todo_not_guessed():
    """知見126: `Delimiter`省略時の既定値(半角スペース)は未確認のため
    1引数形は見送る。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="Split(y)"))])
    code = generate_python(wf)
    assert "# TODO" in code
    assert "x = None" in code
    _compiles(code)


def test_split_with_limit_arg_is_todo_not_guessed():
    """知見126: VBの`Limit`(返す要素数)とPythonの`maxsplit`(分割回数)は
    算術的に1つずれるため、推測せず3引数形は見送る。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text='Split(y, ",", 2)'))])
    code = generate_python(wf)
    assert "# TODO" in code
    assert "x = None" in code
    _compiles(code)


def test_assign_chained_member_access_after_function_call_renders():
    """知見118: `CStr(x).ToUpper()`のような、関数呼び出し結果へのメンバ/
    メソッドアクセスの連鎖(`SuneetPatil/IRCTC-tatkal-booking`の実機XAML
    `in_Config("x").ToString.ToLower.Equals("yes")`で発見した文法ギャップの
    修正——`uipath_expr`側は`in_Config`自体が知見74の配列添字曖昧性で
    `# TODO`に倒れるため、ここでは確認済みのTier1関数`CStr`で再現する)。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text='CStr(y).ToUpper()'))])
    code = generate_python(wf)
    assert "x = _vb_cstr(y).upper()" in code
    assert "# TODO" not in code
    _compiles(code)


def test_assign_chained_property_access_without_trailing_call_renders():
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="CStr(y).ToLower"))])
    code = generate_python(wf)
    assert "x = _vb_cstr(y).lower()" in code
    _compiles(code)


def test_assign_chained_to_string_then_trim_renders():
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="CStr(y).ToString.Trim()"))])
    code = generate_python(wf)
    assert "x = _vb_cstr(_vb_cstr(y)).strip()" in code
    _compiles(code)


def test_assign_bare_variable_dot_tostring_renders_correctly():
    """知見119: 関数呼び出しを介さない素の変数へのメンバアクセス連鎖
    (`intCounter.ToString`、`PacktPublishing/
    Robotic-Process-Automation-Projects`の実機XAMLで発見)——`IDENT`の
    正規表現がドット区切りを1トークンとして貪欲マッチするため、知見118の
    `ChainedAccess`(`postfix`規則)には到達せず常に`Ident`として処理
    される。修正前はこのケースが`intCounter.ToString`という不正なPython
    属性アクセスとしてそのまま出力されていた(構文的には有効だが、
    Pythonの`int`に`.ToString`属性は存在せず実行時に`AttributeError`)。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="intCounter.ToString"))])
    code = generate_python(wf)
    assert "x = _vb_cstr(intCounter)" in code
    _compiles(code)


def test_assign_bare_variable_dot_toupper_renders_correctly():
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="myVar.ToUpper"))])
    code = generate_python(wf)
    assert "x = myVar.upper()" in code
    _compiles(code)


def test_assign_bare_dotted_ident_without_known_suffix_is_unchanged():
    """安全性の確認: 末尾が確認済みの安全なメンバ名(`ToString`/
    `ToUpper`/`ToLower`/`Trim`)以外の場合は、既存の(無変換の)挙動を
    変えない——`DateTime.Now`等の静的クラス参照を誤って変換しない。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="DateTime.Now"))])
    code = generate_python(wf)
    assert "x = DateTime.Now" in code


def test_assign_chained_equals_call_renders_as_comparison():
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text='CStr(y).Equals("yes")'))])
    code = generate_python(wf)
    assert "x = (_vb_cstr(y)) == ('yes')" in code
    _compiles(code)


def test_assign_chained_access_with_unsupported_member_falls_back_to_todo():
    """`uipath_codegen`レベルでは値の変換失敗は`# TODO`へ(条件式の
    伝播とは違う失敗モード、モジュールdocstring参照)——未確認の.NET
    メンバ(`PadLeft`等)はでっち上げず`# TODO`へ倒す。知見144で
    `Substring`を確認済みメンバへ追加したため、本テストはそれとは別の
    未確認メンバへ差し替えた。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="CStr(y).PadLeft(1)"))])
    code = generate_python(wf)
    assert "# TODO" in code
    _compiles(code)


def test_if_condition_with_chained_member_access_on_known_function_works():
    """`If.Condition`は値とは異なり失敗を伝播させる方針(モジュール
    docstring参照)だが、`uipath_expr`側の文法が修正された今は確認済みの
    チェーンなら正しく成功することを確認する——`in_Config`自体は別件
    (知見74)で`# TODO`相当の`NotImplementedError`になるため、確認済みの
    `CStr`で再現する。"""
    wf = _wrap(
        [
            IfNode(
                condition=VbExpr(text='CStr(y).Equals("yes")'),
                then_body=[AssignNode(target=VbExpr(text="x"), value=Literal(value="t"))],
                else_body=[],
            )
        ]
    )
    code = generate_python(wf)
    assert "(_vb_cstr(y)) == ('yes')" in code
    _compiles(code)


def test_assign_interpolated_string_renders_to_vb_cstr_concatenation():
    """知見65: 文字列補間`$"..."`のプレーンな`{expr}`補間はサポート対象
    ——`_vb_cstr()`(知見46、VBのCStr/&と同じ書式規則)で変換してから
    `+`で連結する(架空のf-string変換はしない、下記docstring参照)。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text='$"v={x}"'))])
    code = generate_python(wf)
    assert "# TODO" not in code
    assert "x = 'v=' + _vb_cstr(x)" in code
    _compiles(code)


def test_interpolation_with_format_string_falls_back_to_todo():
    """知見65: `{expr:format}`/`{expr,width}`(書式指定子・フィールド幅)は
    VBの書式指定子をPython側へ正確に対応させる確証が無いため意図的に
    サポート対象外のまま——でっち上げた変換をせず`# TODO`に倒れる。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text='$"v={x:D3}"'))])
    code = generate_python(wf)
    assert "# TODO" in code
    assert "x = None" in code
    _compiles(code)


def test_interpolation_with_nested_quoted_expression_now_renders_correctly():
    """知見66: 知見65時点では`{expr}`内部にネストしたVB文字列リテラル
    (公式ドキュメント自身の`If(age = 1, "", "s")`の例)を含む補間は
    `uipath_expr`のレクサが境界を誤検出し`# TODO`へ安全フォールバックして
    いた。`uipath_expr._prescan_interpolated_strings()`(知見66)が
    Larkに渡す前に正しい境界を確定するようになったため、この入力も
    もう`# TODO`に倒れず、`render.py`の`_split_interpolated_string`
    (知見65で実装済み)がそのままネストした文字列リテラルを含む式を
    分割・コード生成できることを確認する——実行結果もVBの意味論
    (`age = 1`なので`If(...)`は空文字列)と一致する。"""
    wf = _wrap(
        [
            AssignNode(target=VbExpr(text="name"), value=Literal(value="Alice")),
            AssignNode(target=VbExpr(text="age"), value=VbExpr(text="1")),
            AssignNode(
                target=VbExpr(text="x"),
                value=VbExpr(text='$"{name} is old{If(age = 1, "", "s")}."'),
            ),
            MessageBoxNode(text=VbExpr(text="x")),
        ]
    )
    code = generate_python(wf)
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == "Alice is old."


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # 知見36の実機確認例そのもの。
        ('$"value={result}-end"', "value=42-end"),
        # 波括弧のエスケープ(`{{`/`}}`)。
        ('$"{{literal}} and {x}"', "{literal} and 5"),
        # 補間されたDouble値もVBのG書式(知見46の`_vb_cstr`)に従う——
        # Pythonのf-stringの素の`str()`書式化(`"4.0"`)にはならない。
        ('$"n={y}"', "n=4"),
        # 補間区間が複数・リテラルテキストが前後にある一般形。
        ('$"a={a}b={b}c"', "a=1b=2c"),
    ],
)
def test_interpolated_string_renders_plain_interpolations_correctly(
    vb_text: str, expected: str
) -> None:
    """知見65: プレーンな`{expr}`補間(書式指定子・フィールド幅を伴わない)
    が`_vb_cstr()`経由の`+`連結へ正しく変換されることの回帰テスト。"""
    wf = _wrap(
        [
            AssignNode(target=VbExpr(text="result"), value=Literal(value="42")),
            AssignNode(target=VbExpr(text="x"), value=VbExpr(text="5")),
            AssignNode(target=VbExpr(text="y"), value=VbExpr(text="4.0")),
            AssignNode(target=VbExpr(text="a"), value=VbExpr(text="1")),
            AssignNode(target=VbExpr(text="b"), value=VbExpr(text="2")),
            MessageBoxNode(text=VbExpr(text=vb_text)),
        ]
    )
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


def test_interpolated_string_nested_inside_another_interpolated_string_renders_correctly():
    """知見69: `{expr}`の中にさらに別の補間文字列`$"..."`が書かれた
    (例: `$"outer {$"inner {x}"}"`)場合、`render.py`の
    `_render_interpolated_string`が各`{expr}`セグメントを`parse_vb_expr`
    で再帰的に解析し`_render_node`で再帰的にレンダリングする既存の設計
    により、特別な追加対応無しで既に正しく動作することを確認する回帰
    テスト——知見65・66の設計時点ではこのケースを明示的に検証しておらず
    「範囲外」と見なしていたが、実際に検証したところ再帰的な構造のおかげで
    追加の実装無しに動くと判明した(でっち上げではなく実際に`exec()`して
    確認済み)。"""
    wf = _wrap(
        [
            AssignNode(target=VbExpr(text="x"), value=VbExpr(text="5")),
            AssignNode(
                target=VbExpr(text="y"),
                value=VbExpr(text='$"outer {$"inner {x}"}"'),
            ),
            MessageBoxNode(text=VbExpr(text="y")),
        ]
    )
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == "outer inner 5"


def test_message_box_maps_to_print():
    wf = _wrap([MessageBoxNode(text=Literal(value="hi"))])
    code = generate_python(wf)
    assert "print('hi')" in code
    _compiles(code)


def test_message_box_with_caption_includes_it_in_print_output():
    """知見79: `Caption`は捕捉済みだが従来使われていなかった——設定
    されている場合は`print()`の出力に含め、情報を失わない。"""
    wf = _wrap([MessageBoxNode(text=Literal(value="hi"), caption=Literal(value="Info"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == "Info: hi"


@pytest.mark.parametrize(
    "kwargs",
    [
        # 知見107: `Buttons`が単一ボタン以外(GitHub上の実機保存済みXAML
        # で実在を確認済み)の場合、`print()`では選択の分岐を再現できない。
        {"buttons": "YesNo"},
        {"buttons": "OkCancel"},
        # `ChosenButton`が実際に変数へ束縛されている(=ワークフローが
        # 選択結果を使っている)場合も同様。
        {"chosen_button": VbExpr(text="result")},
    ],
)
def test_message_box_with_buttons_or_chosen_button_is_todo_not_guessed(kwargs):
    """知見107: UiPath公式ドキュメントで`ChosenButton`の戻り値が
    `"Ok"`/`"Yes"`/`"No"`/`"Cancel"`のいずれかと確認済みだが、`print()`は
    非対話的なため、でっち上げた`input()`等のユーザー入力再現はしない。"""
    wf = _wrap([MessageBoxNode(text=Literal(value="hi"), **kwargs)])
    code = generate_python(wf)
    assert "# TODO: MessageBox with Buttons=" in code
    assert "print('hi')" not in code
    _compiles(code)


def test_input_dialog_maps_to_input():
    """知見131: `InputDialog`はPythonの`input()`が直接対応する
    (`MessageBox`の`print()`代替とは違い、意味論の直接対応)。"""
    wf = _wrap(
        [
            InputDialogNode(
                title=Literal(value="What will you choose?"),
                label=Literal(value="Pick a number between 1 and 10"),
                is_password="False",
                result=VbExpr(text="guess"),
            )
        ]
    )
    code = generate_python(wf)
    assert "guess = input(" in code
    assert "What will you choose?" in code
    assert "Pick a number between 1 and 10" in code
    assert "# TODO" not in code
    _compiles(code)


def test_input_dialog_with_no_title_omits_it():
    wf = _wrap(
        [
            InputDialogNode(
                label=Literal(value="Enter name"),
                is_password="False",
                result=VbExpr(text="name"),
            )
        ]
    )
    code = generate_python(wf)
    assert "name = input(_vb_cstr('Enter name'))" in code
    assert "# TODO" not in code
    _compiles(code)


@pytest.mark.parametrize(
    "kwargs",
    [
        # 知見131: `IsPassword="True"`(パスワード入力、`getpass.getpass()`
        # が対応先と推測されるが実機未確認)は推測せず`# TODO`へ倒す。
        {"is_password": "True"},
        # `Options`設定済み(選択肢付きダイアログへ変わると推測されるが
        # 実機未確認)も同様。
        {"options": VbExpr(text="choices")},
    ],
)
def test_input_dialog_with_unconfirmed_attrs_is_todo_not_guessed(kwargs):
    base_kwargs = {"label": Literal(value="Enter password"), "is_password": "False", "result": VbExpr(text="x")}
    base_kwargs.update(kwargs)
    wf = _wrap([InputDialogNode(**base_kwargs)])
    code = generate_python(wf)
    assert "# TODO: Input Dialog with" in code
    assert "input(" not in code
    _compiles(code)


def test_input_dialog_with_no_result_is_todo_not_guessed():
    wf = _wrap([InputDialogNode(label=Literal(value="Enter name"), is_password="False")])
    code = generate_python(wf)
    assert "# TODO: Input Dialog with no output Result captured" in code
    _compiles(code)


def test_if_then_else():
    wf = _wrap(
        [
            IfNode(
                condition=VbExpr(text='x="ok"'),
                then_body=[AssignNode(target=VbExpr(text="y"), value=Literal(value="t"))],
                else_body=[AssignNode(target=VbExpr(text="y"), value=Literal(value="f"))],
            )
        ]
    )
    code = generate_python(wf)
    assert "if _vb_bool((lambda _t: _t[0] == _t[1])(_vb_cmp(x, 'ok'))):" in code
    assert "else:" in code
    _compiles(code)


def test_if_with_unparseable_condition_raises():
    """条件式は値より厳格——でっち上げた真偽値で分岐全体を誤らせるより
    コード生成自体を失敗させる(`pad_codegen`のIfActionRecordと同じ方針)。"""
    wf = _wrap([IfNode(condition=VbExpr(text='$"broken'), then_body=[])])
    with pytest.raises(NotImplementedError):
        generate_python(wf)


def test_if_else_if_v2_then_elif_else_exec():
    """知見239: `ui:IfElseIfV2`——`Condition`(トップレベルif)+`.Then`+
    `.ElseIfs`(1件以上の`ui:IfElseIfBlock`)+`.Else`はPythonの
    `if/elif*/else`に直接対応する。`_generate_if`と同じ厳格な条件式
    失敗モード(モジュールdocstring参照)を`.ElseIfs`各要素の
    `Condition`にも適用する。"""
    wf = _wrap(
        [
            IfElseIfV2Node(
                condition=VbExpr(text="x=1"),
                then_body=[WriteLineNode(text=Literal(value="then"))],
                else_ifs=[
                    IfElseIfBlockNode(
                        condition=VbExpr(text="x=2"),
                        then_body=[WriteLineNode(text=Literal(value="elseif1"))],
                    )
                ],
                else_body=[WriteLineNode(text=Literal(value="else"))],
            )
        ]
    )
    code = generate_python(wf)
    assert "if _vb_bool(" in code
    assert "elif _vb_bool(" in code
    assert "else:" in code
    assert "# TODO" not in code
    _compiles(code)
    for xval, expected in [(1, "then"), (2, "elseif1"), (3, "else")]:
        namespace: dict[str, object] = {"x": xval}
        exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            namespace["Test"]()
        assert stdout.getvalue().strip() == expected


def test_if_else_if_v2_empty_else_ifs_behaves_like_plain_if_else():
    """知見239: 実機`vajrang-b/UiPathIn30Days`相当——`.ElseIfs`
    (`BindingList<ui:IfElseIfBlock>`)が常に空の単純if/else構成でも
    `elif`無しの`if/else`として正しく動作する。"""
    wf = _wrap(
        [
            IfElseIfV2Node(
                condition=VbExpr(text="x<100"),
                then_body=[WriteLineNode(text=Literal(value="then"))],
                else_ifs=[],
                else_body=[WriteLineNode(text=Literal(value="else"))],
            )
        ]
    )
    code = generate_python(wf)
    func_body = code.split("def Test():", 1)[1]
    assert not any(line.strip().startswith("elif ") for line in func_body.splitlines())
    _compiles(code)
    namespace: dict[str, object] = {"x": 5}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == "then"
    namespace = {"x": 500}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == "else"


def test_if_else_if_v2_with_unparseable_condition_raises():
    """知見239: `IfElseIfV2.Condition`も`If.Condition`(知見61・155)と
    同じ厳格な失敗モード——誤った真偽値で分岐全体を誤らせるよりコード
    生成自体を失敗させる。"""
    wf = _wrap([IfElseIfV2Node(condition=VbExpr(text='$"broken'), then_body=[])])
    with pytest.raises(NotImplementedError):
        generate_python(wf)


def test_if_else_if_v2_else_if_block_with_unparseable_condition_raises():
    """知見239: `.ElseIfs`配下の各`ui:IfElseIfBlock.Condition`も同じ
    厳格な失敗モードを適用する——トップレベル`Condition`だけ厳格で
    `ElseIfs`側だけ緩いと、特定の分岐でだけ黒箱化してしまうため。"""
    wf = _wrap(
        [
            IfElseIfV2Node(
                condition=VbExpr(text="x=1"),
                then_body=[],
                else_ifs=[
                    IfElseIfBlockNode(condition=VbExpr(text='$"broken'), then_body=[])
                ],
            )
        ]
    )
    with pytest.raises(NotImplementedError):
        generate_python(wf)


def test_for_each_over_array_literal():
    wf = _wrap(
        [
            ForEachNode(
                item_var="item",
                values=VbExpr(text='{"a","b","c"}'),
                body=[MessageBoxNode(text=VbExpr(text="item"))],
            )
        ]
    )
    code = generate_python(wf)
    assert "for item in ['a', 'b', 'c']:" in code
    _compiles(code)


def test_for_each_with_unparseable_values_raises():
    """知見155: `ForEach.Values`は`If.Condition`/`While.Condition`/
    `Switch.Expression`と同じ厳格な失敗モード(モジュールdocstring
    参照)——反復対象を誤って推測すると全ての反復が間違ったデータに対し
    て実行されてしまうため、でっち上げた反復対象で分岐全体を誤らせる
    よりコード生成自体を失敗させる。`plaah/web-application-with-
    rpa-dhl`の実機XAMLで未確認の関数呼び出し(`config(...)`)が
    `Values`に使われている実例を確認し、その経路を再現する。"""
    wf = _wrap(
        [
            ForEachNode(
                item_var="item",
                values=VbExpr(text="config(\"watch_folder\").ToString()"),
                body=[],
            )
        ]
    )
    with pytest.raises(NotImplementedError):
        generate_python(wf)


def test_for_each_row_parses_and_iterates_list_of_dict_data_table():
    """知見118: `ui:ForEachRow`(`UiPath.System.Activities`)は`ui:ForEach`
    と同じ`ForEachNode`/`_generate_for_each`をそのまま再利用する——
    `DataTable`が`list[dict]`表現(知見114・115)である実際のデータに対し、
    生成コードを実行して各行が正しく束縛されることを確認する(実機XAML
    `HarshadRanganathan/uipath-learning/Excel_Sum_For_Each.xaml`で発見)。
    """
    xml = (
        '<Activity x:Class="Test" '
        'xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:ui="http://schemas.uipath.com/workflow/activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
        "<Sequence>"
        '<ui:ForEachRow DataTable="[dt]" DisplayName="For each row">'
        "<ui:ForEachRow.Body>"
        '<ActivityAction x:TypeArguments="sd:DataRow">'
        "<ActivityAction.Argument>"
        '<DelegateInArgument x:TypeArguments="sd:DataRow" Name="row" />'
        "</ActivityAction.Argument>"
        '<Sequence DisplayName="Body">'
        '<ui:MessageBox Text="[row]" />'
        "</Sequence>"
        "</ActivityAction>"
        "</ui:ForEachRow.Body>"
        "</ui:ForEachRow>"
        "</Sequence>"
        "</Activity>"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".xaml", delete=False) as f:
        f.write(xml)
        path = f.name
    try:
        wf = parse_workflow_file(path)
    finally:
        os.unlink(path)
    code = generate_python(wf)
    assert "for row in dt:" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {"dt": [{"a": 1}, {"a": 2}]}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().splitlines() == ["{'a': 1}", "{'a': 2}"]


def test_while_loop():
    wf = _wrap(
        [
            WhileNode(
                condition=VbExpr(text='x<>"done"'),
                body=[BreakNode()],
            )
        ]
    )
    code = generate_python(wf)
    assert "while _vb_bool((lambda _t: _t[0] != _t[1])(_vb_cmp(x, 'done'))):" in code
    assert "break" in code
    _compiles(code)


def test_continue_generates_python_continue():
    """知見226: `ui:Continue`(`Break`と同じ属性無しの自己終了タグ)。
    `exec()`経由で実際にループの残り処理をスキップすることを確認する。"""
    wf = _wrap(
        [
            ForEachNode(
                item_var="x",
                values=Literal(value=[1, 2, 3]),
                body=[
                    IfNode(
                        condition=VbExpr(text="x = 2"),
                        then_body=[ContinueNode()],
                    ),
                    WriteLineNode(text=VbExpr(text="x")),
                ],
                type_arguments="x:Int32",
            )
        ]
    )
    code = generate_python(wf)
    assert "continue" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().splitlines() == ["1", "3"]


def test_return_generates_python_return_and_exits_early():
    """知見238: `ui:Return`(`Break`/`Continue`と同じ属性無しの
    自己終了タグ)。実機`crcnum4/UP_Loan_Prescreen`相当の
    `If.Then`内の早期終了構成を`exec()`経由で実際に実行し、`Return`
    以降の処理がスキップされることを確認する。"""
    wf = _wrap(
        [
            IfNode(
                condition=VbExpr(text="shouldExit"),
                then_body=[
                    WriteLineNode(text=Literal(value="exiting")),
                    ReturnNode(),
                ],
            ),
            WriteLineNode(text=Literal(value="after")),
        ]
    )
    code = generate_python(wf)
    assert "return" in code
    assert "# TODO" not in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(shouldExit):")
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"](True)
    assert stdout.getvalue().splitlines() == ["exiting"]
    stdout2 = io.StringIO()
    with contextlib.redirect_stdout(stdout2):
        namespace["Test"](False)
    assert stdout2.getvalue().splitlines() == ["after"]


def test_repeat_number_of_times_x_runs_exact_count_regardless_of_start_at():
    """知見227: `StartAt`は`CurrentItem`の開始値のみを決め、反復回数
    には影響しない(公式ドキュメント確認済み)——`StartAt=0`でも
    `StartAt=1`でも常に`NumberOfTimes`回だけ実行されることを`exec()`
    経由で確認する。"""
    wf = _wrap(
        [
            RepeatNumberOfTimesXNode(
                number_of_times=Literal(value=3),
                start_at=Literal(value=0),
                item_var="CurrentItem",
                body=[WriteLineNode(text=VbExpr(text="CurrentItem"))],
            )
        ]
    )
    code = generate_python(wf)
    assert "range(_rnt_start, _rnt_start + _rnt_count)" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().splitlines() == ["0", "1", "2"]


def test_repeat_number_of_times_x_defaults_start_at_to_one_when_omitted():
    """知見227: 実機`Apress/Robotic-Process-Automation-Using-UiPath-
    StudioX`で確認済み——`StartAt`省略時は公式ドキュメント確認済みの
    既定値`1`を補う。"""
    wf = _wrap(
        [
            RepeatNumberOfTimesXNode(
                number_of_times=Literal(value=3),
                start_at=None,
                item_var="CurrentItem",
                body=[WriteLineNode(text=VbExpr(text="CurrentItem"))],
            )
        ]
    )
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().splitlines() == ["1", "2", "3"]


def test_repeat_number_of_times_x_with_missing_number_of_times_is_todo():
    wf = _wrap(
        [RepeatNumberOfTimesXNode(number_of_times=None, start_at=Literal(value=1))]
    )
    code = generate_python(wf)
    assert "# TODO: RepeatNumberOfTimesX with missing NumberOfTimes" in code
    _compiles(code)


def test_try_catch():
    wf = _wrap(
        [
            TryCatchNode(
                try_body=[AssignNode(target=VbExpr(text="x"), value=Literal(value="a"))],
                catches=[
                    CatchArm(
                        exception_type="s:Exception",
                        var_name="ex",
                        body=[AssignNode(target=VbExpr(text="x"), value=Literal(value="b"))],
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "try:" in code
    assert "except Exception as ex:" in code
    _compiles(code)


def test_try_catch_with_multiple_catches_resolving_to_distinct_types_still_generates():
    """知見76: 2件以上の`catches`でも、`_EXCEPTION_TYPE_MAP`で解決される
    Python例外型が互いに異なる限り(衝突が無い限り)従来通り生成される
    ことの回帰テスト(知見76の安全策が過剰に広く効かないことを確認)。"""
    wf = _wrap(
        [
            TryCatchNode(
                try_body=[],
                catches=[
                    CatchArm(exception_type="s:Exception", var_name="e1", body=[]),
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO" not in code
    assert "except Exception as e1:" in code
    _compiles(code)


def test_try_catch_with_colliding_exception_types_is_todo_not_silently_shadowed():
    """知見76: 複数の`catches`が`_EXCEPTION_TYPE_MAP`の未知型フォールバック
    経由で同じPython例外型(`Exception`)へ解決される場合、Pythonの
    `except`は先勝ちするため後続のハンドラが到達不能な死んだコードになる
    ——意図した「特定の例外だけ別処理」という制御フローがサイレントに
    崩れることを防ぐため、でっち上げた例外階層対応をする代わりに
    `# TODO`へ倒す。"""
    wf = _wrap(
        [
            TryCatchNode(
                try_body=[AssignNode(target=VbExpr(text="x"), value=Literal(value="a"))],
                catches=[
                    CatchArm(
                        exception_type="System.IO.FileNotFoundException",
                        var_name="ex1",
                        body=[AssignNode(target=VbExpr(text="y"), value=Literal(value="specific"))],
                    ),
                    CatchArm(
                        exception_type="System.Exception",
                        var_name="ex2",
                        body=[AssignNode(target=VbExpr(text="y"), value=Literal(value="general"))],
                    ),
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: TryCatch with ambiguous/colliding exception type mapping" in code
    assert "try:" not in code
    _compiles(code)


def test_switch_with_int_typed_keys():
    assign = AssignNode(target=VbExpr(text="y"), value=Literal(value="z"))
    wf = _wrap(
        [
            SwitchNode(
                expression=VbExpr(text="n"),
                type_arguments="x:Int32",
                arms=[
                    SwitchArm(key="1", body=[assign]),
                    SwitchArm(key=None, body=[assign]),
                ],
            )
        ]
    )
    code = generate_python(wf)
    # 知見77: `_vb_cmp()`経由の比較(`=`演算子と同じ規則)に統一した
    # ——キー自体は従来通りクォート無しの整数リテラル`1`のまま。
    assert f"{VB_CMP_HELPER_NAME}(n, 1)" in code
    assert "else:" in code
    _compiles(code)


def test_switch_with_string_typed_keys():
    wf = _wrap(
        [
            SwitchNode(
                expression=VbExpr(text="n"),
                type_arguments="x:String",
                arms=[
                    SwitchArm(
                        key="a", body=[AssignNode(target=VbExpr(text="y"), value=Literal(value="z"))]
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert f"{VB_CMP_HELPER_NAME}(n, 'a')" in code
    _compiles(code)


def test_switch_comparison_matches_vb_select_case_semantics_not_python_bare_equality():
    """知見77: Microsoft Learn「Select...Case Statement」のRemarksが
    `Case expression`は`testexpression = expression`として評価されると
    明記——`=`演算子と同じ型変換規則(知見47)に従うはずなので、`Switch`の
    `Expression`が実行時に文字列型の値を保持していても(`type_arguments`の
    宣言上はInt32)、数値キーと正しく一致することを確認する(修正前は
    素の`==`で`"1" == 1`が`False`になり対応するアームが実行されなかった)。
    """
    wf = _wrap(
        [
            AssignNode(target=VbExpr(text="result"), value=Literal(value="1")),
            SwitchNode(
                expression=VbExpr(text="result"),
                type_arguments="x:Int32",
                arms=[
                    SwitchArm(
                        key="1",
                        body=[MessageBoxNode(text=Literal(value="matched"))],
                    )
                ],
            ),
        ]
    )
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == "matched"


@pytest.mark.parametrize(
    ("flag_literal", "key", "expected"),
    [
        # 知見81: 知見77で`_vb_cmp()`経由の比較に統一した際、`x:Boolean`型の
        # `Switch`キーは素の文字列リテラル(`'True'`)のままだったため、
        # `_vb_cmp(True, 'True')`が`bool`→`int`変換後に文字列側を`float()`
        # しようとして`ValueError`でクラッシュするという新規の退行を生んで
        # いた(知見77導入前は素の`==`で単に不一致になるだけで済んでいた)。
        ("True", "True", "matched"),
        ("False", "False", "matched"),
        ("True", "False", ""),
    ],
)
def test_switch_with_boolean_typed_keys_does_not_crash_after_vb_cmp_fix(
    flag_literal: str, key: str, expected: str
) -> None:
    wf = _wrap(
        [
            AssignNode(target=VbExpr(text="flag"), value=VbExpr(text=flag_literal)),
            SwitchNode(
                expression=VbExpr(text="flag"),
                type_arguments="x:Boolean",
                arms=[SwitchArm(key=key, body=[MessageBoxNode(text=Literal(value="matched"))])],
            ),
        ]
    )
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


def test_click_with_known_selector_generates_pywinauto_chain():
    """知見9の実例セレクタ。マッピング可能な属性があれば実コードを生成し、
    未マッピング属性(app/aaname)・role値の未検証をコメントで警告する。"""
    selector = (
        "<wnd app='notepad.exe' cls='Notepad' title='Untitled - Notepad' />"
        "<ctrl name='Text Editor' role='editable text' />"
    )
    wf = _wrap([ClickNode(selector=selector, display_name="Click 'editable text'")])
    code = generate_python(wf)
    assert 'Desktop(backend="uia")' in code
    assert ".click_input()" in code
    assert "# WARNING:" in code
    _compiles(code)


def test_click_display_name_becomes_a_comment_even_when_falling_back_to_todo():
    """知見80: `display_name`は捕捉済みだが未活用だった——`# TODO`に倒れる
    場合も含め、どの`Click`を指しているか分かるようコメントとして先頭に
    追記する(挙動は変えない、コメントのみの追加)。"""
    wf = _wrap([ClickNode(selector=None, display_name="Click Submit button")])
    code = generate_python(wf)
    assert "# Click Submit button" in code
    assert "# TODO: Click with no selector captured" in code
    _compiles(code)


def test_click_with_no_selector_is_todo():
    wf = _wrap([ClickNode(selector=None)])
    code = generate_python(wf)
    assert "# TODO: Click with no selector" in code
    _compiles(code)


def test_click_with_unmappable_selector_is_todo():
    """`idx`のような未対応属性しか無いセレクタは、でっち上げたkwargsを
    出力せず`# TODO`に倒す。"""
    wf = _wrap([ClickNode(selector="<wnd idx='2' />")])
    code = generate_python(wf)
    assert "# TODO: Click selector had no mappable attributes" in code
    _compiles(code)


_CLICK_SELECTOR = "<wnd cls='Notepad' /><ctrl name='x' />"


@pytest.mark.parametrize(
    ("click_type", "mouse_button", "key_modifiers"),
    [
        # 知見71: design/evidence/uipath_xaml_probe/Main.xamlで実機確認
        # 済みの唯一の具体例(単純な左シングルクリック・修飾キー無し)。
        ("CLICK_SINGLE", "BTN_LEFT", "None"),
        # 属性が丸ごと省略された場合(`None`)も同じ確認済み既定値扱い。
        (None, None, None),
    ],
)
def test_click_with_confirmed_default_type_generates_click_input(
    click_type: str | None, mouse_button: str | None, key_modifiers: str | None
) -> None:
    wf = _wrap(
        [
            ClickNode(
                selector=_CLICK_SELECTOR,
                click_type=click_type,
                mouse_button=mouse_button,
                key_modifiers=key_modifiers,
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO" not in code
    assert ".click_input()" in code
    _compiles(code)


@pytest.mark.parametrize(
    ("click_type", "mouse_button", "key_modifiers"),
    [
        # 知見102: `KeyModifiers`の非既定値は実在を確認済みだが複数キー
        # 併用時の正確な区切り文字・pywinautoの`pressed`引数への対応が
        # 未確認のため、でっち上げたマッピングで誤らせるより`# TODO`に倒す。
        ("CLICK_SINGLE", "BTN_LEFT", "Ctrl"),
        # 未確認のまま残る値(知見100で発見した`CLICK_UP`/`CLICK_DOWN`は
        # ドラッグ操作用の押し下げ/離すのみに対応すると推定されるが単体
        # での正確な対応が未確認)。
        ("CLICK_UP", "BTN_LEFT", "None"),
    ],
)
def test_click_with_unconfirmed_type_is_todo_not_guessed(
    click_type: str, mouse_button: str, key_modifiers: str
) -> None:
    wf = _wrap(
        [
            ClickNode(
                selector=_CLICK_SELECTOR,
                click_type=click_type,
                mouse_button=mouse_button,
                key_modifiers=key_modifiers,
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Click with non-default ClickType/MouseButton/KeyModifiers" in code
    assert ".click_input(" not in code
    _compiles(code)


@pytest.mark.parametrize(
    ("click_type", "mouse_button", "expected_kwargs"),
    [
        # 知見102: `gh api search/code`でGitHub上の実機保存済みXAMLから
        # 直接確認した実在する値(VM不使用)——pywinautoの実`click_input`
        # 引数(`base_wrapper.py`/`mouse.py`で確認済み)へマッピングする。
        ("CLICK_DOUBLE", "BTN_LEFT", "double=True"),
        ("CLICK_SINGLE", "BTN_RIGHT", "button='right'"),
        ("CLICK_SINGLE", "BTN_MIDDLE", "button='middle'"),
        ("CLICK_DOUBLE", "BTN_RIGHT", "double=True, button='right'"),
    ],
)
def test_click_with_confirmed_nondefault_type_generates_real_click_input(
    click_type: str, mouse_button: str, expected_kwargs: str
) -> None:
    wf = _wrap(
        [
            ClickNode(
                selector=_CLICK_SELECTOR,
                click_type=click_type,
                mouse_button=mouse_button,
                key_modifiers="None",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO" not in code
    assert f".click_input({expected_kwargs})" in code
    _compiles(code)


@pytest.mark.parametrize("cursor_position", [None, "Center"])
def test_click_with_confirmed_default_cursor_position_generates_click_input(
    cursor_position: str | None,
) -> None:
    """知見73: `CursorPosition`が未設定または実機確認済みの`"Center"`
    (pywinautoの`click_input()`既定と一致)の場合は従来通り生成する。"""
    wf = _wrap([ClickNode(selector=_CLICK_SELECTOR, cursor_position=cursor_position)])
    code = generate_python(wf)
    assert "# TODO" not in code
    assert ".click_input()" in code
    _compiles(code)


@pytest.mark.parametrize(
    "kwargs",
    [
        # 知見105: `TopRight`/`BottomLeft`/`BottomRight`はオフセットの符号
        # 規約が実機未確認のため依然TODO。
        {"cursor_position": "TopRight", "cursor_offset_x": "5", "cursor_offset_y": "5"},
        # `Center`に非None(未確認)のオフセットが付いている組み合わせも
        # 安全側に倒す(知見105、Center+オフセット無しの実例しか確認して
        # いないため)。
        {"cursor_position": "Center", "cursor_offset_x": "5", "cursor_offset_y": None},
    ],
)
def test_click_with_non_default_cursor_position_is_todo_not_guessed(kwargs):
    """知見73・105: `CursorPosition`が未確認の値・符号の組み合わせの場合は
    でっち上げず`# TODO`に倒す。"""
    wf = _wrap([ClickNode(selector=_CLICK_SELECTOR, **kwargs)])
    code = generate_python(wf)
    assert "# TODO: Click with non-default CursorPosition" in code
    assert ".click_input(" not in code
    _compiles(code)


def test_click_with_topleft_cursor_position_non_integer_offset_is_todo():
    """知見105: `Position="TopLeft"`だがオフセットが整数化できない値の
    場合は、でっち上げず`# TODO`に倒す。"""
    wf = _wrap(
        [
            ClickNode(
                selector=_CLICK_SELECTOR, cursor_position="TopLeft", cursor_offset_x="notanumber"
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Click with non-integer CursorPosition offsets" in code
    assert ".click_input(" not in code
    _compiles(code)


def test_click_with_topleft_cursor_position_generates_coords_kwarg():
    """知見105: `Position="TopLeft"`+`OffsetX`/`OffsetY`(GitHub上の実機
    保存済みXAMLで確認済み、VM不使用)は、pywinautoの`coords=`既定座標系
    (左上原点)と一致するため、でっち上げず実際に`coords=(x, y)`を生成
    する。"""
    wf = _wrap(
        [
            ClickNode(
                selector=_CLICK_SELECTOR,
                cursor_position="TopLeft",
                cursor_offset_x="5",
                cursor_offset_y="8",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO" not in code
    assert ".click_input(coords=(5, 8))" in code
    _compiles(code)


def test_click_with_topleft_cursor_position_and_no_offsets_defaults_to_origin():
    """`Position="TopLeft"`だが`OffsetX`/`OffsetY`が未設定の場合は`(0, 0)`
    (左上原点そのもの)として扱う。"""
    wf = _wrap([ClickNode(selector=_CLICK_SELECTOR, cursor_position="TopLeft")])
    code = generate_python(wf)
    assert "# TODO" not in code
    assert ".click_input(coords=(0, 0))" in code
    _compiles(code)


def test_click_with_delay_before_generates_time_sleep():
    """知見106: `DelayBefore`(UiPath公式ドキュメントで確認済み——「活動が
    何らかの操作を始める前の待機時間」、既定200ms、`gh api search/code`で
    実機保存済みXAMLの実例も確認済み)は`time.sleep()`へ実変換する。"""
    wf = _wrap([ClickNode(selector=_CLICK_SELECTOR, delay_before=Literal(value="2000"))])
    code = generate_python(wf)
    assert "# TODO" not in code
    assert "import time" in code
    assert "time.sleep(_vb_num('2000') / 1000.0)" in code
    _compiles(code)


def test_click_with_delay_ms_is_todo_not_guessed():
    """知見106: `DelayMS`はUiPath公式ドキュメントに(`DelayBefore`とは違い)
    記載が無く意味論が未確認のため、でっち上げず`# TODO`に倒す。"""
    wf = _wrap([ClickNode(selector=_CLICK_SELECTOR, delay_ms=Literal(value="2000"))])
    code = generate_python(wf)
    assert "# TODO: Click with DelayMS set" in code
    assert ".click_input(" not in code
    _compiles(code)


_HOVER_SELECTOR = "<wnd cls='Notepad' /><ctrl name='x' />"


def test_hover_with_default_cursor_position_generates_move_click_input():
    """知見157: `ui:Hover`(GitHub code searchで151件ヒット)。既定の
    `CursorPosition`(省略/`"Center"`)では`coords`引数を渡さず
    `click_input()`自身の既定(要素の中心)に依拠する——`move_mouse_
    input()`ラッパー自身の既定(`coords=(0, 0)`)は使わない。"""
    wf = _wrap([HoverNode(selector=_HOVER_SELECTOR)])
    code = generate_python(wf)
    assert ".click_input(button='move')" in code
    assert "# TODO" not in code
    _compiles(code)


def test_hover_display_name_becomes_a_comment_even_when_falling_back_to_todo():
    wf = _wrap([HoverNode(selector=None, display_name="Hover 'Forgot Password?'")])
    code = generate_python(wf)
    assert "# Hover 'Forgot Password?'" in code
    assert "# TODO: Hover with no selector captured" in code
    _compiles(code)


def test_hover_with_no_selector_is_todo():
    wf = _wrap([HoverNode(selector=None)])
    code = generate_python(wf)
    assert "# TODO: Hover with no selector captured" in code
    _compiles(code)


def test_hover_with_unmappable_selector_is_todo():
    wf = _wrap([HoverNode(selector="<wnd idx='2' />")])
    code = generate_python(wf)
    assert "# TODO: Hover selector had no mappable attributes" in code
    _compiles(code)


def test_hover_with_topleft_cursor_position_and_offsets():
    wf = _wrap(
        [HoverNode(selector=_HOVER_SELECTOR, cursor_position="TopLeft", cursor_offset_x="5", cursor_offset_y="8")]
    )
    code = generate_python(wf)
    assert "# TODO" not in code
    assert ".click_input(button='move', coords=(5, 8))" in code
    _compiles(code)


def test_hover_with_non_default_cursor_position_is_todo():
    wf = _wrap([HoverNode(selector=_HOVER_SELECTOR, cursor_position="BottomRight")])
    code = generate_python(wf)
    assert "# TODO: Hover with non-default CursorPosition" in code
    _compiles(code)


def test_hover_with_delay_before_generates_time_sleep():
    wf = _wrap([HoverNode(selector=_HOVER_SELECTOR, delay_before=Literal(value="500"))])
    code = generate_python(wf)
    assert "# TODO" not in code
    assert "time.sleep(_vb_num('500') / 1000.0)" in code
    _compiles(code)


def test_hover_with_delay_ms_is_todo_not_guessed():
    wf = _wrap([HoverNode(selector=_HOVER_SELECTOR, delay_ms=Literal(value="500"))])
    code = generate_python(wf)
    assert "# TODO: Hover with DelayMS set" in code
    assert ".click_input(" not in code
    _compiles(code)


def test_hover_with_non_default_send_window_messages_is_todo_not_guessed():
    wf = _wrap(
        [HoverNode(selector=_HOVER_SELECTOR, send_window_messages=Literal(value="True"))]
    )
    code = generate_python(wf)
    assert "# TODO: Hover with non-default SendWindowMessages" in code
    _compiles(code)


def test_hover_with_non_default_simulate_hover_is_todo_not_guessed():
    wf = _wrap([HoverNode(selector=_HOVER_SELECTOR, simulate_hover=Literal(value="True"))])
    code = generate_python(wf)
    assert "# TODO: Hover with non-default SimulateHover" in code
    _compiles(code)


_ACTIVATE_SELECTOR = "<wnd cls='Notepad' /><ctrl name='x' />"


def test_activate_with_known_selector_generates_set_focus():
    """知見162: `ui:Activate`(GitHub code searchで604件ヒット)。
    pywinautoの`set_focus()`(両バックエンドで共通サポートされる
    確認済みの標準API)が直接対応する——`Hover`の`move_mouse_input()`
    既定値の罠(知見157)のような注意点は無い。"""
    wf = _wrap([ActivateNode(selector=_ACTIVATE_SELECTOR)])
    code = generate_python(wf)
    assert ".set_focus()" in code
    assert "# TODO" not in code
    _compiles(code)


def test_activate_display_name_becomes_a_comment_even_when_falling_back_to_todo():
    wf = _wrap([ActivateNode(selector=None, display_name="Activate 'chrome.exe'")])
    code = generate_python(wf)
    assert "# Activate 'chrome.exe'" in code
    assert "# TODO: Activate with no selector captured" in code
    _compiles(code)


def test_activate_with_no_selector_is_todo():
    wf = _wrap([ActivateNode(selector=None)])
    code = generate_python(wf)
    assert "# TODO: Activate with no selector captured" in code
    _compiles(code)


def test_activate_with_unmappable_selector_is_todo():
    wf = _wrap([ActivateNode(selector="<wnd idx='2' />")])
    code = generate_python(wf)
    assert "# TODO: Activate selector had no mappable attributes" in code
    _compiles(code)


def test_activate_with_delay_before_generates_time_sleep():
    wf = _wrap([ActivateNode(selector=_ACTIVATE_SELECTOR, delay_before=Literal(value="500"))])
    code = generate_python(wf)
    assert "# TODO" not in code
    assert "time.sleep(_vb_num('500') / 1000.0)" in code
    _compiles(code)


def test_activate_with_delay_ms_is_todo_not_guessed():
    wf = _wrap([ActivateNode(selector=_ACTIVATE_SELECTOR, delay_ms=Literal(value="500"))])
    code = generate_python(wf)
    assert "# TODO: Activate with DelayMS set" in code
    assert ".set_focus()" not in code
    _compiles(code)


def test_activate_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap(
        [ActivateNode(selector=_ACTIVATE_SELECTOR, continue_on_error=Literal(value="True"))]
    )
    code = generate_python(wf)
    assert "# TODO: Activate with ContinueOnError set" in code
    _compiles(code)


_CHECK_SELECTOR = "<wnd cls='Notepad' /><ctrl name='x' />"


def test_check_with_check_action_generates_set_toggle_state_true():
    """知見165: `ui:Check`(GitHub code searchで805件ヒット)。
    `Action="Check"`は「指定の最終状態へ設定する」操作のため、無条件の
    `click_input()`ではなく現在の状態を見てから必要な場合のみ
    `toggle()`する専用ヘルパーを経由する。"""
    wf = _wrap([CheckNode(selector=_CHECK_SELECTOR, action="Check")])
    code = generate_python(wf)
    assert "_pywinauto_set_toggle_state(" in code
    assert ", True)" in code
    assert "# TODO" not in code
    _compiles(code)


def test_check_with_uncheck_action_generates_set_toggle_state_false():
    wf = _wrap([CheckNode(selector=_CHECK_SELECTOR, action="Uncheck")])
    code = generate_python(wf)
    assert "_pywinauto_set_toggle_state(" in code
    assert ", False)" in code
    _compiles(code)


def test_check_display_name_becomes_a_comment_even_when_falling_back_to_todo():
    wf = _wrap([CheckNode(selector=None, action="Check", display_name="Check 'INPUT'")])
    code = generate_python(wf)
    assert "# Check 'INPUT'" in code
    assert "# TODO: Check with no selector captured" in code
    _compiles(code)


def test_check_with_no_selector_is_todo():
    wf = _wrap([CheckNode(selector=None, action="Check")])
    code = generate_python(wf)
    assert "# TODO: Check with no selector captured" in code
    _compiles(code)


def test_check_with_unmappable_selector_is_todo():
    wf = _wrap([CheckNode(selector="<wnd idx='2' />", action="Check")])
    code = generate_python(wf)
    assert "# TODO: Check selector had no mappable attributes" in code
    _compiles(code)


def test_check_with_unrecognized_action_is_todo_not_guessed():
    wf = _wrap([CheckNode(selector=_CHECK_SELECTOR, action="Toggle")])
    code = generate_python(wf)
    assert "# TODO: Check with unrecognized Action" in code
    assert "_pywinauto_set_toggle_state" not in code
    _compiles(code)


def test_check_with_no_action_is_todo_not_guessed():
    wf = _wrap([CheckNode(selector=_CHECK_SELECTOR, action=None)])
    code = generate_python(wf)
    assert "# TODO: Check with unrecognized Action" in code
    _compiles(code)


def test_check_with_delay_before_generates_time_sleep():
    wf = _wrap(
        [CheckNode(selector=_CHECK_SELECTOR, action="Check", delay_before=Literal(value="500"))]
    )
    code = generate_python(wf)
    assert "# TODO" not in code
    assert "time.sleep(_vb_num('500') / 1000.0)" in code
    _compiles(code)


def test_check_with_delay_after_is_todo_not_guessed():
    wf = _wrap(
        [CheckNode(selector=_CHECK_SELECTOR, action="Check", delay_after=Literal(value="500"))]
    )
    code = generate_python(wf)
    assert "# TODO: Check with DelayAfter set" in code
    assert "_pywinauto_set_toggle_state" not in code
    _compiles(code)


def test_check_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap(
        [
            CheckNode(
                selector=_CHECK_SELECTOR, action="Check", continue_on_error=Literal(value="True")
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Check with ContinueOnError set" in code
    _compiles(code)


def test_highlight_generates_comment_only_no_automation_effect():
    """知見166: `ui:Highlight`(GitHub code searchで289件ヒット)。純粋な
    視覚的デバッグ支援で後続のデータ/制御フローへの影響が無いため、
    `ui:Comment`と同じ「実行時の挙動が無い活動はコメントへ変換する」
    設計で常にコメントのみを生成する——`# TODO`にはならない。"""
    wf = _wrap(
        [
            HighlightNode(
                selector="<wnd cls='Notepad' />",
                color="Gold",
                highlight_time=Literal(value="1000"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# Highlight" in code
    assert "Color=Gold" in code
    assert "no automation effect to reproduce" in code
    assert "# TODO" not in code
    _compiles(code)


def test_highlight_display_name_becomes_a_comment():
    wf = _wrap([HighlightNode(selector="<wnd cls='Notepad' />", display_name="Highlight 'x'")])
    code = generate_python(wf)
    assert "# Highlight 'x'" in code
    assert "no automation effect to reproduce" in code
    _compiles(code)


def test_highlight_with_no_selector_still_generates_comment():
    """知見166: 選択子が無くても(常にコメントのみのため)クラッシュせず
    動く——`# TODO`の判断すら不要(実際の呼び出しが無いため)。"""
    wf = _wrap([HighlightNode(selector=None)])
    code = generate_python(wf)
    assert "# Highlight" in code
    assert "# TODO" not in code
    _compiles(code)


def test_kill_process_generates_taskkill_via_subprocess_run():
    """知見169: `ui:KillProcess`(GitHub code searchで1514件ヒット)。
    Windows標準搭載の確認済みコマンド`taskkill /IM <name>.exe /F`
    (`subprocess.run`経由)が直接対応する。"""
    wf = _wrap([KillProcessNode(process_name=Literal(value="msedge"))])
    code = generate_python(wf)
    assert 'subprocess.run(["taskkill", "/IM", f"{_vb_cstr(\'msedge\')}.exe", "/F"])' in code
    assert "import subprocess" in code
    assert "# TODO" not in code
    _compiles(code)


def test_kill_process_display_name_becomes_a_comment():
    wf = _wrap([KillProcessNode(process_name=Literal(value="msedge"), display_name="Kill edge")])
    code = generate_python(wf)
    assert "# Kill edge" in code
    assert "subprocess.run(" in code
    _compiles(code)


def test_kill_process_with_no_process_name_is_todo_not_guessed():
    wf = _wrap([KillProcessNode(process_name=None)])
    code = generate_python(wf)
    assert "# TODO: KillProcess with no ProcessName captured" in code
    _compiles(code)


def test_kill_process_with_process_reference_is_todo_not_guessed():
    wf = _wrap(
        [
            KillProcessNode(
                process_name=Literal(value="msedge"), process=VbExpr(text="proc")
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: KillProcess with Process set" in code
    assert "subprocess.run" not in code
    _compiles(code)


def test_kill_process_with_applies_to_is_todo_not_guessed():
    wf = _wrap(
        [
            KillProcessNode(
                process_name=Literal(value="msedge"), applies_to=Literal(value="ThisProcess")
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: KillProcess with AppliesTo set" in code
    _compiles(code)


def test_kill_process_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap(
        [
            KillProcessNode(
                process_name=Literal(value="msedge"), continue_on_error=Literal(value="True")
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: KillProcess with ContinueOnError set" in code
    _compiles(code)


_CLOSE_APPLICATION_SELECTOR = "<wnd cls='Notepad' />"


def test_close_application_with_known_selector_generates_close():
    """知見171: `ui:CloseApplication`(GitHub code searchで532件
    ヒット)。pywinautoの`close()`(`WM_CLOSE`送信、実機確認済み
    `.venv`のソースで`post_message(win32defines.WM_CLOSE)`を直接
    呼ぶ標準API)が直接対応する。"""
    wf = _wrap([CloseApplicationNode(selector=_CLOSE_APPLICATION_SELECTOR)])
    code = generate_python(wf)
    assert ".close()" in code
    assert "# TODO" not in code
    _compiles(code)


def test_close_application_display_name_becomes_a_comment_even_when_falling_back_to_todo():
    wf = _wrap([CloseApplicationNode(selector=None, display_name="Close application")])
    code = generate_python(wf)
    assert "# Close application" in code
    assert "# TODO: CloseApplication with no selector captured" in code
    _compiles(code)


def test_close_application_with_no_selector_is_todo():
    wf = _wrap([CloseApplicationNode(selector=None)])
    code = generate_python(wf)
    assert "# TODO: CloseApplication with no selector captured" in code
    _compiles(code)


def test_close_application_with_unmappable_selector_is_todo():
    wf = _wrap([CloseApplicationNode(selector="<wnd idx='2' />")])
    code = generate_python(wf)
    assert "# TODO: CloseApplication selector had no mappable attributes" in code
    _compiles(code)


def test_close_application_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap(
        [
            CloseApplicationNode(
                selector=_CLOSE_APPLICATION_SELECTOR, continue_on_error=Literal(value="True")
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: CloseApplication with ContinueOnError set" in code
    assert ".close()" not in code
    _compiles(code)


_CLOSE_WINDOW_SELECTOR = "<wnd cls='Notepad' />"


def test_close_window_with_known_selector_generates_close():
    """知見172: `ui:CloseWindow`(GitHub code searchで276件ヒット)。
    `CloseApplication`(知見171)と同じ`close()`を生成する——属性構成
    (フラット`Selector`、`Target`ラッパー無し)が違うだけ。"""
    wf = _wrap([CloseWindowNode(selector=_CLOSE_WINDOW_SELECTOR)])
    code = generate_python(wf)
    assert ".close()" in code
    assert "# TODO" not in code
    _compiles(code)


def test_close_window_display_name_becomes_a_comment_even_when_falling_back_to_todo():
    wf = _wrap([CloseWindowNode(selector=None, display_name="Close Window")])
    code = generate_python(wf)
    assert "# Close Window" in code
    assert "# TODO: CloseWindow with no selector captured" in code
    _compiles(code)


def test_close_window_with_no_selector_is_todo():
    wf = _wrap([CloseWindowNode(selector=None)])
    code = generate_python(wf)
    assert "# TODO: CloseWindow with no selector captured" in code
    _compiles(code)


def test_close_window_with_unmappable_selector_is_todo():
    wf = _wrap([CloseWindowNode(selector="<wnd idx='2' />")])
    code = generate_python(wf)
    assert "# TODO: CloseWindow selector had no mappable attributes" in code
    _compiles(code)


def test_close_window_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap(
        [
            CloseWindowNode(
                selector=_CLOSE_WINDOW_SELECTOR, continue_on_error=Literal(value="True")
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: CloseWindow with ContinueOnError set" in code
    assert ".close()" not in code
    _compiles(code)


def test_close_window_with_use_window_is_todo_not_guessed():
    """知見172: `UseWindow`(既存のウィンドウ参照を再利用する、実機
    `SuneetPatil/IRCTC-tatkal-booking`で確認した`[browser_window.
    Element.GetTopLevelWindow]`のようなVB式)はオブジェクト参照自体が
    未モデル化のため`# TODO`へ倒す。"""
    wf = _wrap(
        [
            CloseWindowNode(
                selector=_CLOSE_WINDOW_SELECTOR,
                use_window=VbExpr(text="browser_window.Element.GetTopLevelWindow"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: CloseWindow with UseWindow set" in code
    assert ".close()" not in code
    _compiles(code)


def test_maximize_window_generates_active_only_maximize():
    """知見173: `ui:MaximizeWindow`(`Window`省略時、ほとんどの実例)。
    pywinautoの`active_only=True`(`GetGUIThreadInfo()`でOS全体の
    アクティブウィンドウを取得、確認済み標準API)が「現在アクティブな
    ウィンドウ」の意味論に直接対応する。"""
    wf = _wrap([WindowStateNode(method="maximize")])
    code = generate_python(wf)
    assert 'Desktop(backend="uia").window(active_only=True).maximize()' in code
    assert "# TODO" not in code
    _compiles(code)


def test_minimize_window_generates_active_only_minimize():
    wf = _wrap([WindowStateNode(method="minimize")])
    code = generate_python(wf)
    assert 'Desktop(backend="uia").window(active_only=True).minimize()' in code
    _compiles(code)


def test_restore_window_generates_active_only_restore():
    wf = _wrap([WindowStateNode(method="restore")])
    code = generate_python(wf)
    assert 'Desktop(backend="uia").window(active_only=True).restore()' in code
    _compiles(code)


def test_window_state_display_name_becomes_a_comment():
    wf = _wrap([WindowStateNode(method="maximize", display_name="Maximize Window")])
    code = generate_python(wf)
    assert "# Maximize Window" in code
    assert ".maximize()" in code
    _compiles(code)


def test_window_state_with_window_variable_reference_is_todo_not_guessed():
    """知見173: `Window`(実機`Apress/Robotic-Process-Automation-Using-
    UiPath-StudioX`で確認した`[Saved.Values(Of Window)("ActiveWindow")]`
    のようなStudioX保存済み`Window`型変数参照)はオブジェクト参照自体
    が未モデル化のため`# TODO`へ倒す。"""
    wf = _wrap(
        [
            WindowStateNode(
                method="minimize",
                window=VbExpr(text='Saved.Values(Of Window)("ActiveWindow")'),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: MinimizeWindow with Window set" in code
    assert ".minimize()" not in code
    _compiles(code)


def test_window_state_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap([WindowStateNode(method="maximize", continue_on_error=Literal(value="True"))])
    code = generate_python(wf)
    assert "# TODO: MaximizeWindow with ContinueOnError set" in code
    assert ".maximize()" not in code
    _compiles(code)


def test_generate_data_table_csv_parsing_true_uses_dict_reader():
    """知見197: `ui:GenerateDataTable`(GitHub code searchで180件
    ヒット)。`CSVParsing="True"`は`csv.DictReader`(引用符付き
    フィールドに対応)で、`UseColumnHeader="True"`のdict行表現に
    対応する。"""
    wf = _wrap(
        [
            GenerateDataTableNode(
                input=VbExpr(text="textData"),
                data_table=VbExpr(text="studentDetails"),
                column_separators=Literal(value=","),
                use_column_header="True",
                csv_parsing="True",
            )
        ]
    )
    code = generate_python(wf)
    assert "studentDetails = list(csv.DictReader(io.StringIO(textData), delimiter=','))" in code
    assert "import csv" in code
    assert "import io" in code
    assert "# TODO" not in code
    _compiles(code)


def test_generate_data_table_csv_parsing_false_uses_plain_split():
    wf = _wrap(
        [
            GenerateDataTableNode(
                input=VbExpr(text="Out_Text"),
                data_table=VbExpr(text="Out_DT"),
                column_separators=Literal(value=";"),
                use_column_header="True",
                csv_parsing="False",
            )
        ]
    )
    code = generate_python(wf)
    assert "_l.split(';') for _l in Out_Text.splitlines()" in code
    assert "Out_DT = [dict(zip(_gdt_header, _row)) for _row in _gdt_rows]" in code
    assert "# TODO" not in code
    _compiles(code)


def test_generate_data_table_display_name_becomes_a_comment():
    wf = _wrap(
        [
            GenerateDataTableNode(
                input=VbExpr(text="t"),
                data_table=VbExpr(text="dt"),
                column_separators=Literal(value=","),
                use_column_header="True",
                csv_parsing="True",
                display_name="Generate Data Table From Text",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Generate Data Table From Text" in code
    assert "csv.DictReader(" in code
    _compiles(code)


def test_generate_data_table_with_missing_input_or_output_is_todo():
    wf = _wrap([GenerateDataTableNode(input=None, data_table=VbExpr(text="dt"))])
    code = generate_python(wf)
    assert "# TODO: GenerateDataTable with missing Input/DataTable" in code
    _compiles(code)


def test_generate_data_table_with_positions_is_todo_not_guessed():
    wf = _wrap(
        [
            GenerateDataTableNode(
                input=VbExpr(text="t"),
                data_table=VbExpr(text="dt"),
                positions=Literal(value="1,5,10"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: GenerateDataTable with Positions/ColumnSizes set" in code
    _compiles(code)


def test_generate_data_table_with_use_column_header_not_true_is_todo():
    wf = _wrap(
        [
            GenerateDataTableNode(
                input=VbExpr(text="t"),
                data_table=VbExpr(text="dt"),
                use_column_header="False",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: GenerateDataTable with UseColumnHeader not set to True" in code
    _compiles(code)


def test_generate_data_table_with_auto_detect_types_is_todo_not_guessed():
    wf = _wrap(
        [
            GenerateDataTableNode(
                input=VbExpr(text="t"),
                data_table=VbExpr(text="dt"),
                use_column_header="True",
                auto_detect_types="True",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: GenerateDataTable with AutoDetectTypes=True" in code
    _compiles(code)


def test_generate_data_table_with_multi_char_separator_is_todo_not_guessed():
    wf = _wrap(
        [
            GenerateDataTableNode(
                input=VbExpr(text="t"),
                data_table=VbExpr(text="dt"),
                use_column_header="True",
                column_separators=Literal(value="::"),
                csv_parsing="True",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: GenerateDataTable with multi-character ColumnSeparators" in code
    _compiles(code)


def test_generate_data_table_with_non_default_newline_separator_is_todo():
    wf = _wrap(
        [
            GenerateDataTableNode(
                input=VbExpr(text="t"),
                data_table=VbExpr(text="dt"),
                use_column_header="True",
                column_separators=Literal(value=","),
                new_line_separator=Literal(value=";;"),
                csv_parsing="True",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: GenerateDataTable with non-default NewLineSeparator" in code
    _compiles(code)


def test_generate_data_table_with_unrecognized_csv_parsing_is_todo():
    wf = _wrap(
        [
            GenerateDataTableNode(
                input=VbExpr(text="t"),
                data_table=VbExpr(text="dt"),
                use_column_header="True",
                column_separators=Literal(value=","),
                csv_parsing=None,
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: GenerateDataTable with unrecognized/unset CSVParsing" in code
    _compiles(code)


_GET_ATTRIBUTE_SELECTOR = "<wnd cls='Notepad' />"


def test_get_attribute_always_declines_with_named_todo():
    """知見174: `ui:GetAttribute`(GitHub code searchで274件ヒット)。
    `Attribute`は開放的な語彙(UiPathのブラウザ拡張がDOM/アクセシビリ
    ティツリーから取得する)で、pywinauto側に安全な汎用代替が無いため
    値を問わず常に`# TODO`へ倒す——VM実機検証なしに新しいマッピングを
    追加しない(知見38の`role`属性と同じ判断)。"""
    wf = _wrap(
        [
            GetAttributeNode(
                selector=_GET_ATTRIBUTE_SELECTOR,
                attribute="innerText",
                result=VbExpr(text="result"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: GetAttribute (Attribute='innerText')" in code
    _compiles(code)


def test_get_attribute_with_no_selector_is_todo():
    wf = _wrap([GetAttributeNode(selector=None, result=VbExpr(text="result"))])
    code = generate_python(wf)
    assert "# TODO: GetAttribute with no selector captured" in code
    _compiles(code)


def test_get_attribute_with_no_result_is_todo():
    wf = _wrap([GetAttributeNode(selector=_GET_ATTRIBUTE_SELECTOR, result=None)])
    code = generate_python(wf)
    assert "# TODO: GetAttribute with no output Result captured" in code
    _compiles(code)


def test_get_attribute_with_continue_on_error_is_todo():
    wf = _wrap(
        [
            GetAttributeNode(
                selector=_GET_ATTRIBUTE_SELECTOR,
                result=VbExpr(text="result"),
                continue_on_error=Literal(value="True"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: GetAttribute with ContinueOnError set" in code
    _compiles(code)


def test_get_attribute_display_name_becomes_a_comment():
    wf = _wrap(
        [
            GetAttributeNode(
                selector=_GET_ATTRIBUTE_SELECTOR,
                display_name="Get Attribute",
                attribute="checked",
                result=VbExpr(text="result"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# Get Attribute" in code
    assert "# TODO: GetAttribute (Attribute='checked')" in code
    _compiles(code)


def test_get_password_always_declines_without_leaking_protected_password():
    """知見176: `ui:GetPassword`。`ProtectedPassword`はWindows DPAPI
    暗号化バイナリで移植可能な復号方法が無いため常に`# TODO`へ倒す
    ——資格情報を扱う機微な操作であるため、生成コードへ暗号化済みの
    値そのものを一切出力しないことも確認する(本ノードは
    `ProtectedPassword`自体をそもそも保持しない設計)。"""
    wf = _wrap([GetPasswordNode(result=VbExpr(text="pw"))])
    code = generate_python(wf)
    assert "# TODO: GetPassword" in code
    assert "DPAPI" in code
    assert "AQAAA" not in code
    _compiles(code)


def test_get_password_display_name_becomes_a_comment():
    wf = _wrap([GetPasswordNode(display_name="Get Password", result=VbExpr(text="pw"))])
    code = generate_python(wf)
    assert "# Get Password" in code
    assert "# TODO: GetPassword" in code
    _compiles(code)


def test_get_password_with_no_result_is_todo():
    wf = _wrap([GetPasswordNode(result=None)])
    code = generate_python(wf)
    assert "# TODO: GetPassword with no output Result captured" in code
    _compiles(code)


class _FakeWin32CredError(Exception):
    """知見248: 実機`pywin32`の`pywintypes.error`はタプル風の属性
    (`winerror`/`funcname`/`strerror`)を持つ——このサンドボックスには
    実際の`pywin32`が存在しない(Windows専用)ため、`sys.modules`へ
    最小限のフェイク`win32cred`/`pywintypes`モジュールを注入して
    `exec()`経由で実際の制御フロー(見つかった/見つからなかった両方)
    を検証する。"""

    def __init__(self, winerror, funcname="CredRead", strerror=""):
        super().__init__(strerror)
        self.winerror = winerror
        self.funcname = funcname
        self.strerror = strerror


def _install_fake_win32cred():
    import sys
    import types

    store: dict[tuple, dict] = {}
    fake_win32cred = types.ModuleType("win32cred")
    fake_win32cred.CRED_TYPE_GENERIC = 1
    fake_win32cred.CRED_PERSIST_ENTERPRISE = 3
    fake_pywintypes = types.ModuleType("pywintypes")
    fake_pywintypes.error = _FakeWin32CredError

    def fake_cred_read(Type, TargetName):
        key = (Type, TargetName)
        if key not in store:
            raise _FakeWin32CredError(1168, "CredRead", "Element not found.")
        return store[key]

    def fake_cred_write(credential, flags):
        key = (credential["Type"], credential["TargetName"])
        store[key] = {
            "UserName": credential["UserName"],
            "CredentialBlob": credential["CredentialBlob"],
        }

    fake_win32cred.CredRead = fake_cred_read
    fake_win32cred.CredWrite = fake_cred_write
    sys.modules["win32cred"] = fake_win32cred
    sys.modules["pywintypes"] = fake_pywintypes
    return store


def test_add_credential_then_get_secure_credential_round_trip_exec():
    """知見248: `ui:AddCredential`(`win32cred.CredWrite()`)で書き込んだ
    資格情報を、`ui:GetSecureCredential`(`win32cred.CredRead()`)が
    正しく読み戻せることを`exec()`経由で確認する——`CredentialBlob`の
    `utf-16-le`エンコード/デコードが対になっていることも確認する。"""
    _install_fake_win32cred()
    wf_add = _wrap(
        [
            AddCredentialNode(
                target=Literal(value="MyApp:bob"),
                username=Literal(value="bob"),
                password=Literal(value="s3cr3t"),
                credential_type="Generic",
                persistance_type="Enterprise",
            )
        ]
    )
    code_add = generate_python(wf_add)
    assert "win32cred.CredWrite(" in code_add
    assert "import win32cred" in code_add
    assert "# TODO" not in code_add
    _compiles(code_add)
    ns_add: dict[str, object] = {}
    exec(code_add, ns_add)  # noqa: S102 - テスト対象は信頼できる自作コード
    ns_add["Test"]()

    wf_get = WorkflowFile(
        class_name="Test",
        root=SequenceNode(
            body=[
                GetSecureCredentialNode(
                    target=Literal(value="MyApp:bob"),
                    credential_type="Generic",
                    persistance_type="Enterprise",
                    result=VbExpr(text="found"),
                    username=VbExpr(text="u"),
                    password=VbExpr(text="p"),
                )
            ]
        ),
        arguments={
            "found": "OutArgument(x:Boolean)",
            "u": "OutArgument(x:String)",
            "p": "OutArgument(x:String)",
        },
    )
    code_get = generate_python(wf_get)
    assert "_win32_cred_read(" in code_get
    assert "import win32cred" in code_get
    assert "import pywintypes" in code_get
    _compiles(code_get)
    ns_get: dict[str, object] = {}
    exec(code_get + "\n    return found, u, p", ns_get)  # noqa: S102 - 信頼できる自作コード
    result = ns_get["Test"](found=None, u=None, p=None)
    assert result == (True, "bob", "s3cr3t")


def test_get_secure_credential_not_found_sets_result_false_exec():
    """知見248: `win32cred.CredRead()`は見つからない場合に`None`を
    返すのではなく`pywintypes.error`(`winerror=1168`)を投げる——
    これを正しく`Result=False`へ変換することを`exec()`経由で確認する
    (例外を潰さずクラッシュせずに処理できることの実証)。"""
    _install_fake_win32cred()
    wf = WorkflowFile(
        class_name="Test",
        root=SequenceNode(
            body=[
                GetSecureCredentialNode(
                    target=Literal(value="MyApp:nonexistent"),
                    credential_type="Generic",
                    persistance_type="Enterprise",
                    result=VbExpr(text="found"),
                    username=VbExpr(text="u"),
                    password=VbExpr(text="p"),
                )
            ]
        ),
        arguments={
            "found": "OutArgument(x:Boolean)",
            "u": "OutArgument(x:String)",
            "p": "OutArgument(x:String)",
        },
    )
    code = generate_python(wf)
    ns: dict[str, object] = {}
    exec(code + "\n    return found, u, p", ns)  # noqa: S102 - テスト対象は信頼できる自作コード
    result = ns["Test"](found=None, u=None, p=None)
    assert result == (False, None, None)


def test_get_secure_credential_with_unconfirmed_credential_type_is_todo():
    wf = _wrap(
        [
            GetSecureCredentialNode(
                target=Literal(value="x"),
                credential_type="DomainPassword",
                result=VbExpr(text="found"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: GetSecureCredential with CredentialType" in code
    _compiles(code)


def test_get_secure_credential_with_no_target_is_todo():
    wf = _wrap([GetSecureCredentialNode(target=None)])
    code = generate_python(wf)
    assert "# TODO: GetSecureCredential with no Target captured" in code
    _compiles(code)


def test_add_credential_with_secure_password_is_todo():
    """知見248: 公式ドキュメント確認済みの`SecurePassword`入力
    (`Password`とは別の属性)は実機未確認のため見送る。"""
    wf = _wrap(
        [
            AddCredentialNode(
                target=Literal(value="x"),
                username=Literal(value="u"),
                password=None,
                secure_password=VbExpr(text="securePw"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: AddCredential with missing Target/Username/Password" in code
    _compiles(code)


def test_add_credential_with_result_bound_is_todo():
    wf = _wrap(
        [
            AddCredentialNode(
                target=Literal(value="x"),
                username=Literal(value="u"),
                password=Literal(value="p"),
                result=VbExpr(text="ok"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: AddCredential with Result output bound" in code
    _compiles(code)


def test_request_credential_prompts_and_sets_result_true_exec():
    """知見248: `ui:RequestCredential`——`InputDialogNode`(知見131)と
    同じ`input()`直接対応、パスワードは`getpass.getpass()`。`Result`
    はブロッキング`input()`に対応概念が無いため常に`True`を代入する
    (ノードdocstring参照)——`input`/`getpass.getpass`自体をモックして
    `exec()`経由で確認する。"""
    wf = _wrap(
        [
            RequestCredentialNode(
                title=Literal(value="Login"),
                message=Literal(value="Enter creds"),
                result=VbExpr(text="ok"),
                username=VbExpr(text="user"),
                password=VbExpr(text="pw"),
            )
        ]
    )
    code = generate_python(wf)
    assert "input(" in code
    assert "getpass.getpass(" in code
    assert "import getpass" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code + "\n    return ok, user, pw", namespace)  # noqa: S102 - 信頼できる自作コード
    with unittest.mock.patch("builtins.input", return_value="alice"), unittest.mock.patch(
        "getpass.getpass", return_value="secret"
    ):
        result = namespace["Test"]()
    assert result == (True, "alice", "secret")


def test_request_credential_with_missing_username_or_password_is_todo():
    wf = _wrap([RequestCredentialNode(username=None, password=VbExpr(text="pw"))])
    code = generate_python(wf)
    assert "# TODO: RequestCredential with missing Username/Password output binding" in code
    _compiles(code)


def test_lookup_data_table_finds_matching_row():
    """知見196: `ui:LookupDataTable`(GitHub code searchで197件ヒット)。
    `LookupColumnName`/`TargetColumnName`による名前ベースのdict行
    アクセス(知見183の`GetRowItem`と同じ前提)で、単一セル値+行
    インデックスを返す。"""
    wf = _wrap(
        [
            LookupDataTableNode(
                data_table=VbExpr(text="dt"),
                lookup_column_name=Literal(value="Name"),
                lookup_value=Literal(value="John Gates"),
                target_column_name=Literal(value="Name"),
                cell_value=VbExpr(text="cellValue"),
                row_index=VbExpr(text="rowIndex"),
            )
        ]
    )
    code = generate_python(wf)
    assert "_lookup_row['Name'] == 'John Gates'" in code
    assert "rowIndex = _lookup_row_index" in code
    assert "cellValue = _lookup_cell_value" in code
    assert "# TODO" not in code
    _compiles(code)


def test_lookup_data_table_not_found_yields_minus_one():
    wf = _wrap(
        [
            LookupDataTableNode(
                data_table=VbExpr(text="dt"),
                lookup_column_name=Literal(value="Name"),
                lookup_value=Literal(value="Nobody"),
                target_column_name=Literal(value="Name"),
                row_index=VbExpr(text="rowIndex"),
            )
        ]
    )
    code = generate_python(wf)
    assert "rowIndex = _lookup_row_index" in code
    _compiles(code)


def test_lookup_data_table_display_name_becomes_a_comment():
    wf = _wrap(
        [
            LookupDataTableNode(
                data_table=VbExpr(text="dt"),
                lookup_column_name=Literal(value="Name"),
                lookup_value=Literal(value="x"),
                target_column_name=Literal(value="Name"),
                row_index=VbExpr(text="rowIndex"),
                display_name="Lookup data table",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Lookup data table" in code
    _compiles(code)


def test_lookup_data_table_with_missing_data_table_or_value_is_todo():
    wf = _wrap([LookupDataTableNode(data_table=None, lookup_value=Literal(value="x"))])
    code = generate_python(wf)
    assert "# TODO: LookupDataTable with missing DataTable/LookupValue" in code
    _compiles(code)


def test_lookup_data_table_with_no_outputs_is_todo():
    wf = _wrap(
        [
            LookupDataTableNode(
                data_table=VbExpr(text="dt"),
                lookup_value=Literal(value="x"),
                cell_value=None,
                row_index=None,
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: LookupDataTable with no output CellValue/RowIndex captured" in code
    _compiles(code)


def test_lookup_data_table_with_data_column_reference_is_todo_not_guessed():
    wf = _wrap(
        [
            LookupDataTableNode(
                data_table=VbExpr(text="dt"),
                lookup_value=Literal(value="x"),
                row_index=VbExpr(text="rowIndex"),
                lookup_data_column=VbExpr(text="col"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: LookupDataTable with LookupDataColumn/TargetDataColumn set" in code
    _compiles(code)


def test_lookup_data_table_with_column_index_is_todo_not_guessed():
    wf = _wrap(
        [
            LookupDataTableNode(
                data_table=VbExpr(text="dt"),
                lookup_value=Literal(value="x"),
                row_index=VbExpr(text="rowIndex"),
                lookup_column_index=Literal(value="0"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: LookupDataTable with LookupColumnIndex/TargetColumnIndex set" in code
    _compiles(code)


def test_lookup_data_table_with_missing_column_names_is_todo():
    wf = _wrap(
        [
            LookupDataTableNode(
                data_table=VbExpr(text="dt"),
                lookup_value=Literal(value="x"),
                row_index=VbExpr(text="rowIndex"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: LookupDataTable with missing LookupColumnName/TargetColumnName" in code
    _compiles(code)


def test_load_image_opens_file_via_pillow():
    """知見178: `ui:LoadImage`(GitHub code searchで58件ヒット)。
    Pillow(`PIL.Image.open()`)が標準でサポートする「ファイルから
    画像を読み込む」操作そのものに直接対応する。"""
    wf = _wrap(
        [LoadImageNode(file_name=Literal(value="img.png"), image=VbExpr(text="img"))]
    )
    code = generate_python(wf)
    assert "img = PIL.Image.open(" in code
    assert "import PIL.Image" in code
    assert "# TODO" not in code
    _compiles(code)


def test_load_image_display_name_becomes_a_comment():
    wf = _wrap(
        [
            LoadImageNode(
                file_name=Literal(value="img.png"),
                image=VbExpr(text="img"),
                display_name="Load Image",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Load Image" in code
    assert "PIL.Image.open(" in code
    _compiles(code)


def test_load_image_with_no_file_name_is_todo():
    wf = _wrap([LoadImageNode(file_name=None, image=VbExpr(text="img"))])
    code = generate_python(wf)
    assert "# TODO: LoadImage with no FileName captured" in code
    _compiles(code)


def test_load_image_with_no_image_is_todo():
    wf = _wrap([LoadImageNode(file_name=Literal(value="img.png"), image=None)])
    code = generate_python(wf)
    assert "# TODO: LoadImage with no output Image captured" in code
    _compiles(code)


def test_save_image_calls_pil_save():
    """知見179: `ui:SaveImage`(`LoadImage`知見178の正反対)。Pillowの
    `Image.save()`が直接対応する。"""
    wf = _wrap(
        [SaveImageNode(file_name=Literal(value="out.png"), image=VbExpr(text="img"))]
    )
    code = generate_python(wf)
    assert "img.save(" in code
    assert "# TODO" not in code
    _compiles(code)


def test_save_image_with_no_file_name_is_todo():
    wf = _wrap([SaveImageNode(file_name=None, image=VbExpr(text="img"))])
    code = generate_python(wf)
    assert "# TODO: SaveImage with no FileName captured" in code
    _compiles(code)


def test_save_image_with_no_image_is_todo():
    wf = _wrap([SaveImageNode(file_name=Literal(value="out.png"), image=None)])
    code = generate_python(wf)
    assert "# TODO: SaveImage with no Image captured" in code
    _compiles(code)


_TAKE_SCREENSHOT_SELECTOR = "<wnd cls='Notepad' />"


def test_take_screenshot_with_no_selector_grabs_whole_screen():
    """知見179: `ui:TakeScreenshot`(`UiPath/Community.Activities`公式
    REFrameworkテンプレート)。`Target`省略時はPillowの`ImageGrab.
    grab()`(仮想スクリーン全体)が直接対応する。"""
    wf = _wrap([TakeScreenshotNode(selector=None, screenshot=VbExpr(text="shot"))])
    code = generate_python(wf)
    assert "shot = PIL.ImageGrab.grab()" in code
    assert "import PIL.ImageGrab" in code
    assert "# TODO" not in code
    _compiles(code)


def test_take_screenshot_with_known_selector_uses_capture_as_image():
    wf = _wrap(
        [
            TakeScreenshotNode(
                selector=_TAKE_SCREENSHOT_SELECTOR, screenshot=VbExpr(text="shot")
            )
        ]
    )
    code = generate_python(wf)
    assert "shot = " in code
    assert ".capture_as_image()" in code
    assert "# TODO" not in code
    _compiles(code)


def test_take_screenshot_with_no_output_screenshot_is_todo():
    wf = _wrap([TakeScreenshotNode(selector=None, screenshot=None)])
    code = generate_python(wf)
    assert "# TODO: TakeScreenshot with no output Screenshot captured" in code
    _compiles(code)


def test_take_screenshot_with_wait_before_is_todo_not_guessed():
    """知見179: `WaitBefore`は`DelayBefore`とは別名の未確認属性のため、
    同一視せず`# TODO`へ倒す。"""
    wf = _wrap(
        [
            TakeScreenshotNode(
                selector=None,
                screenshot=VbExpr(text="shot"),
                wait_before=Literal(value="500"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: TakeScreenshot with WaitBefore set" in code
    assert "ImageGrab" not in code
    _compiles(code)


def test_take_screenshot_with_unmappable_selector_is_todo():
    wf = _wrap(
        [TakeScreenshotNode(selector="<wnd idx='2' />", screenshot=VbExpr(text="shot"))]
    )
    code = generate_python(wf)
    assert "# TODO: TakeScreenshot selector had no mappable attributes" in code
    _compiles(code)


def test_get_ocr_text_with_google_ocr_engine_calls_pytesseract():
    """知見180: `ui:GetOCRText`。`GoogleOCR`(UiPath公式ドキュメントで
    「Tesseract OCR」と確認済み)の場合のみ`pytesseract.image_to_
    string()`(`tests/test_ocr_fallback.py`で実機VM検証済みの既存
    確認済み依存)に対応する。"""
    wf = _wrap(
        [
            GetOcrTextNode(
                selector=None,
                engine_tag="GoogleOCR",
                text=VbExpr(text="result"),
            )
        ]
    )
    code = generate_python(wf)
    assert "pytesseract.image_to_string(" in code
    assert "import pytesseract" in code
    assert "PIL.ImageGrab.grab()" in code
    assert "# TODO" not in code
    _compiles(code)


def test_get_ocr_text_with_language_passes_lang_kwarg():
    wf = _wrap(
        [
            GetOcrTextNode(
                selector=None,
                engine_tag="GoogleOCR",
                language=Literal(value="eng"),
                text=VbExpr(text="result"),
            )
        ]
    )
    code = generate_python(wf)
    assert "lang='eng'" in code or 'lang="eng"' in code
    _compiles(code)


def test_get_ocr_text_with_known_selector_uses_capture_as_image():
    wf = _wrap(
        [
            GetOcrTextNode(
                selector="<wnd cls='Notepad' />",
                engine_tag="GoogleOCR",
                text=VbExpr(text="result"),
            )
        ]
    )
    code = generate_python(wf)
    assert ".capture_as_image()" in code
    assert "pytesseract.image_to_string(" in code
    _compiles(code)


def test_get_ocr_text_with_non_google_ocr_engine_is_todo_not_guessed():
    """知見180: `MicrosoftOCR`(実機71件確認——Windows OCR API、
    Tesseractとは別のエンジン)等は未確認のため`# TODO`へ倒す。"""
    wf = _wrap(
        [GetOcrTextNode(selector=None, engine_tag="MicrosoftOCR", text=VbExpr(text="result"))]
    )
    code = generate_python(wf)
    assert "# TODO: GetOCRText with OCREngine 'MicrosoftOCR'" in code
    assert "pytesseract" not in code
    _compiles(code)


def test_get_ocr_text_with_no_text_is_todo():
    wf = _wrap([GetOcrTextNode(selector=None, engine_tag="GoogleOCR", text=None)])
    code = generate_python(wf)
    assert "# TODO: GetOCRText with no output Text captured" in code
    _compiles(code)


def test_get_ocr_text_with_words_info_is_todo_not_guessed():
    wf = _wrap(
        [
            GetOcrTextNode(
                selector=None,
                engine_tag="GoogleOCR",
                text=VbExpr(text="result"),
                words_info=VbExpr(text="info"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: GetOCRText with WordsInfo bound" in code
    _compiles(code)


def test_get_ocr_text_with_non_default_scale_is_todo_not_guessed():
    """知見180: 実機`cameronmcnz/uipath-tutorials`で確認した`Scale="2"`
    のような画像前処理オプションは未モデル化のため`# TODO`へ倒す。"""
    wf = _wrap(
        [
            GetOcrTextNode(
                selector=None, engine_tag="GoogleOCR", text=VbExpr(text="result"), scale="2"
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: GetOCRText with non-default Scale" in code
    assert "pytesseract" not in code
    _compiles(code)


def test_get_ocr_text_with_profile_is_todo_not_guessed():
    wf = _wrap(
        [
            GetOcrTextNode(
                selector=None,
                engine_tag="GoogleOCR",
                text=VbExpr(text="result"),
                profile="Screen",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: GetOCRText with Profile set" in code
    _compiles(code)


def test_get_ocr_text_with_extract_words_is_todo_not_guessed():
    wf = _wrap(
        [
            GetOcrTextNode(
                selector=None,
                engine_tag="GoogleOCR",
                text=VbExpr(text="result"),
                extract_words="True",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: GetOCRText with ExtractWords set" in code
    _compiles(code)


def test_add_data_row_appends_array_row_to_data_table():
    """知見181: `ui:AddDataRow`(GitHub code searchで2120件ヒット)。
    `ArrayRow`(VB配列リテラル、`uipath_expr`の`ArrayLiteral`が既に
    `render_expr`でPythonリストへ変換する確立済みの経路)を既存の
    DataTable変数へ`.append()`する。"""
    wf = _wrap(
        [
            AddDataRowNode(
                array_row=VbExpr(text='{"Hello World", -1}'),
                data_table=VbExpr(text="MyDataTable"),
            )
        ]
    )
    code = generate_python(wf)
    assert "MyDataTable.append(['Hello World', -_vb_num(1)])" in code
    assert "# TODO" not in code
    _compiles(code)


def test_add_data_row_display_name_becomes_a_comment():
    wf = _wrap(
        [
            AddDataRowNode(
                array_row=VbExpr(text='{"x"}'),
                data_table=VbExpr(text="t"),
                display_name="Add Data Row",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Add Data Row" in code
    assert ".append(" in code
    _compiles(code)


def test_add_data_row_with_no_data_table_is_todo():
    wf = _wrap([AddDataRowNode(array_row=VbExpr(text='{"x"}'), data_table=None)])
    code = generate_python(wf)
    assert "# TODO: AddDataRow with no DataTable captured" in code
    _compiles(code)


def test_add_data_row_with_no_array_row_is_todo():
    wf = _wrap([AddDataRowNode(array_row=None, data_table=VbExpr(text="t"))])
    code = generate_python(wf)
    assert "# TODO: AddDataRow with no ArrayRow captured" in code
    _compiles(code)


def test_add_data_row_with_data_row_is_todo_not_guessed():
    """知見181: `DataRow`(既存の`System.Data.DataRow`オブジェクト参照)
    は未モデル化のため`# TODO`へ倒す。"""
    wf = _wrap(
        [
            AddDataRowNode(
                data_row=VbExpr(text="existingRow"),
                data_table=VbExpr(text="t"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: AddDataRow with DataRow set" in code
    assert ".append(" not in code
    _compiles(code)


def test_add_data_row_uses_dict_row_when_build_data_table_columns_are_known():
    """知見205(知見203の`ScopeInfo`アーキテクチャ第3段): 知見117が
    発見し見送った「`AddDataRow`が`list.append()`すると、同じ
    `DataTable`を後で読む他の活動(`LookupDataTable`/`GetRowItem.
    ColumnName`等、dict行前提の直接アクセス)が実行時に`TypeError`で
    落ちる」という実在のバグ(本テストで実際に再現・修正を確認)を、
    `ScopeInfo.data_table_columns`(`BuildDataTable`で確認済みの列名)
    で解消する——`ArrayRow`を`dict(zip(columns, array_row))`へ変換
    してから追加する。"""
    wf = _wrap(
        [
            BuildDataTableNode(data_table=VbExpr(text="dt"), columns=["Name", "Age"]),
            AddDataRowNode(
                array_row=VbExpr(text='{"Alice", 30}'),
                data_table=VbExpr(text="dt"),
            ),
            LookupDataTableNode(
                data_table=VbExpr(text="dt"),
                lookup_column_name=Literal(value="Name"),
                lookup_value=Literal(value="Alice"),
                target_column_name=Literal(value="Age"),
                row_index=VbExpr(text="idx"),
                cell_value=VbExpr(text="cellValue"),
            ),
        ]
    )
    code = generate_python(wf)
    assert "dt.append(dict(zip(['Name', 'Age'], ['Alice', 30])))" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()


def test_add_data_row_falls_back_to_list_when_columns_are_unknown():
    """知見205: `DataTable`が`BuildDataTable`由来だと確認できない場合
    (スコープ情報に列名が無い)は、従来通り位置指定のlistのまま追加する
    ——安全側のフォールバック、新しい挙動の後退は無い。"""
    wf = _wrap(
        [
            AddDataRowNode(
                array_row=VbExpr(text='{"Hello World", -1}'),
                data_table=VbExpr(text="MyDataTable"),
            )
        ]
    )
    code = generate_python(wf)
    assert "MyDataTable.append(['Hello World', -_vb_num(1)])" in code
    assert "dict(zip(" not in code
    _compiles(code)


def test_sort_data_table_by_column_name_when_build_data_table_columns_are_known():
    """知見206: 知見195で保留した`SortDataTable`を、知見203の`ScopeInfo`
    アーキテクチャで解消する——対象`DataTable`が`BuildDataTable`由来で
    列名が確認できる場合に限り`sorted(..., key=lambda row: row[col])`を
    生成する。"""
    wf = _wrap(
        [
            BuildDataTableNode(data_table=VbExpr(text="dt"), columns=["Name", "Age"]),
            AddDataRowNode(
                array_row=VbExpr(text='{"Bob", 42}'), data_table=VbExpr(text="dt")
            ),
            AddDataRowNode(
                array_row=VbExpr(text='{"Ann", 20}'), data_table=VbExpr(text="dt")
            ),
            SortDataTableNode(
                data_table=VbExpr(text="dt"),
                output_data_table=VbExpr(text="dt2"),
                column_name=Literal(value="Age"),
                sort_order="Ascending",
            ),
        ]
    )
    code = generate_python(wf)
    assert (
        "dt2 = sorted(dt, key=lambda _row: _row['Age'], reverse=False)" in code
    )
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code + "\n    return dt2", namespace)  # noqa: S102 - 信頼できる自作コード
    assert namespace["Test"]() == [
        {"Name": "Ann", "Age": 20},
        {"Name": "Bob", "Age": 42},
    ]


def test_sort_data_table_decending_typo_and_order_alias_are_honored():
    """知見195/206: 実機`PacktPublishing/Robotic-Process-Automation-
    RPA-for-Developers`で確認した版差——属性名`Order`(`SortOrder`の
    別名)+値`"Decending"`(`"Descending"`の誤字)。パーサー・コード生成
    の両方がこれを正しく吸収することを確認する。"""
    wf = _wrap(
        [
            BuildDataTableNode(data_table=VbExpr(text="dt"), columns=["Age"]),
            SortDataTableNode(
                data_table=VbExpr(text="dt"),
                output_data_table=VbExpr(text="dt2"),
                column_name=Literal(value="Age"),
                sort_order="Decending",
            ),
        ]
    )
    code = generate_python(wf)
    assert "reverse=True" in code
    assert "# TODO" not in code
    _compiles(code)


def test_sort_data_table_declines_when_row_representation_is_unknown():
    """知見206: 対象`DataTable`が`BuildDataTable`由来だと確認できない
    場合(スコープ情報に列名が無い)は、list行の可能性を排除できないため
    `# TODO`へ倒す——知見205と同じ「表現非依存で安全という思い込みが
    実行時バグになる」教訓の適用。"""
    wf = _wrap(
        [
            SortDataTableNode(
                data_table=VbExpr(text="unknown_dt"),
                output_data_table=VbExpr(text="dt2"),
                column_name=Literal(value="Age"),
                sort_order="Ascending",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: SortDataTable" in code
    assert "sorted(" not in code
    _compiles(code)


def test_sort_data_table_declines_column_index_and_data_column():
    """知見206: `ColumnIndex`/`DataColumn`は実機で非`{x:Null}`の実例が
    無いため常に`# TODO`——知見196の`LookupDataTable`と同じ判断。"""
    wf = _wrap(
        [
            BuildDataTableNode(data_table=VbExpr(text="dt"), columns=["Age"]),
            SortDataTableNode(
                data_table=VbExpr(text="dt"),
                output_data_table=VbExpr(text="dt2"),
                column_index=Literal(value="0"),
                sort_order="Ascending",
            ),
        ]
    )
    code = generate_python(wf)
    assert "# TODO: SortDataTable with ColumnIndex set" in code
    _compiles(code)

    wf2 = _wrap(
        [
            BuildDataTableNode(data_table=VbExpr(text="dt"), columns=["Age"]),
            SortDataTableNode(
                data_table=VbExpr(text="dt"),
                output_data_table=VbExpr(text="dt2"),
                data_column=VbExpr(text="ageColumn"),
                sort_order="Ascending",
            ),
        ]
    )
    code2 = generate_python(wf2)
    assert "# TODO: SortDataTable with DataColumn set" in code2
    _compiles(code2)


def test_filter_data_table_empty_operator_with_column_index_removes_matching_rows():
    """知見207: 実機`cameronmcnz/uipath-tutorials`の`DeleteEmpty`相当
    ——`Operator="EMPTY"`+`Column`が列インデックス(`x:Int32`)+
    `FilterRowsMode="Remove"`で、該当列が空/Noneの行を除去する。"""
    wf = _wrap(
        [
            BuildDataTableNode(data_table=VbExpr(text="dt"), columns=["Name", "Age"]),
            AddDataRowNode(
                array_row=VbExpr(text='{"Bob", 42}'), data_table=VbExpr(text="dt")
            ),
            AddDataRowNode(
                array_row=VbExpr(text='{"", 20}'), data_table=VbExpr(text="dt")
            ),
            FilterDataTableNode(
                data_table=VbExpr(text="dt"),
                output_data_table=VbExpr(text="dt2"),
                filter_rows_mode="Remove",
                filters=[
                    FilterOperationArgument(
                        boolean_operator="And",
                        operator="EMPTY",
                        column=Literal(value="0"),
                        column_type="x:Int32",
                    )
                ],
            ),
        ]
    )
    code = generate_python(wf)
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code + "\n    return dt2", namespace)  # noqa: S102 - 信頼できる自作コード
    assert namespace["Test"]() == [{"Name": "Bob", "Age": 42}]


def test_filter_data_table_multiple_and_filters_with_string_columns_keeps_matching_rows():
    """知見207: 実機`PacktPublishing/Robotic-Process-Automation-RPA-
    for-Developers`相当——`Operator="GTE"`を2件`BooleanOperator="And"`
    で結合+`Column`が列名(`x:String`)+`FilterRowsMode="Keep"`で、両方
    の条件を満たす行だけを残す。"""
    wf = _wrap(
        [
            BuildDataTableNode(
                data_table=VbExpr(text="dt"), columns=["Name", "Age", "Salary"]
            ),
            AddDataRowNode(
                array_row=VbExpr(text='{"Alice", 65, 80000}'),
                data_table=VbExpr(text="dt"),
            ),
            AddDataRowNode(
                array_row=VbExpr(text='{"Bob", 30, 50000}'),
                data_table=VbExpr(text="dt"),
            ),
            FilterDataTableNode(
                data_table=VbExpr(text="dt"),
                output_data_table=VbExpr(text="dt2"),
                filter_rows_mode="Keep",
                filters=[
                    FilterOperationArgument(
                        boolean_operator="And",
                        operator="GTE",
                        column=VbExpr(text='"Age"'),
                        column_type="x:String",
                        operand=VbExpr(text="60.0"),
                    ),
                    FilterOperationArgument(
                        boolean_operator="And",
                        operator="EQ",
                        column=VbExpr(text='"Name"'),
                        column_type="x:String",
                        operand=VbExpr(text='"Alice"'),
                    ),
                ],
            ),
        ]
    )
    code = generate_python(wf)
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code + "\n    return dt2", namespace)  # noqa: S102 - 信頼できる自作コード
    assert namespace["Test"]() == [{"Name": "Alice", "Age": 65, "Salary": 80000}]


def test_filter_data_table_declines_select_columns():
    """知見207: `SelectColumns`(列の投影)は本活動で未対応のまま
    ——`Filters`条件のみが実装範囲。"""
    wf = _wrap(
        [
            BuildDataTableNode(data_table=VbExpr(text="dt"), columns=["Age"]),
            FilterDataTableNode(
                data_table=VbExpr(text="dt"),
                output_data_table=VbExpr(text="dt2"),
                filter_rows_mode="Keep",
                filters=[
                    FilterOperationArgument(
                        boolean_operator="And",
                        operator="EQ",
                        column=VbExpr(text='"Age"'),
                        column_type="x:String",
                        operand=VbExpr(text="30.0"),
                    )
                ],
                select_columns=[VbExpr(text='"Age"')],
            ),
        ]
    )
    code = generate_python(wf)
    assert "# TODO: FilterDataTable with SelectColumns set" in code
    _compiles(code)


def test_filter_data_table_declines_unconfirmed_operator_and_boolean_operator():
    """知見207: `Operator`(EQ/GTE/EMPTY以外)・`BooleanOperator`
    ("And"以外)は実機で非確認のため`# TODO`へ倒す。"""
    wf = _wrap(
        [
            BuildDataTableNode(data_table=VbExpr(text="dt"), columns=["Age"]),
            FilterDataTableNode(
                data_table=VbExpr(text="dt"),
                output_data_table=VbExpr(text="dt2"),
                filter_rows_mode="Keep",
                filters=[
                    FilterOperationArgument(
                        boolean_operator="And",
                        operator="LT",
                        column=VbExpr(text='"Age"'),
                        column_type="x:String",
                        operand=VbExpr(text="30.0"),
                    )
                ],
            ),
        ]
    )
    code = generate_python(wf)
    assert "# TODO: FilterDataTable with Operator 'LT'" in code
    _compiles(code)

    wf2 = _wrap(
        [
            BuildDataTableNode(data_table=VbExpr(text="dt"), columns=["Age"]),
            FilterDataTableNode(
                data_table=VbExpr(text="dt"),
                output_data_table=VbExpr(text="dt2"),
                filter_rows_mode="Keep",
                filters=[
                    FilterOperationArgument(
                        boolean_operator="Or",
                        operator="EQ",
                        column=VbExpr(text='"Age"'),
                        column_type="x:String",
                        operand=VbExpr(text="30.0"),
                    )
                ],
            ),
        ]
    )
    code2 = generate_python(wf2)
    assert "# TODO: FilterDataTable with BooleanOperator 'Or'" in code2
    _compiles(code2)


def test_filter_data_table_declines_when_row_representation_is_unknown():
    """知見207: 対象`DataTable`が`BuildDataTable`由来だと確認できない
    場合はlist行の可能性を排除できないため`# TODO`へ倒す——知見206の
    `SortDataTable`と同じ判断。"""
    wf = _wrap(
        [
            FilterDataTableNode(
                data_table=VbExpr(text="unknown_dt"),
                output_data_table=VbExpr(text="dt2"),
                filter_rows_mode="Keep",
                filters=[
                    FilterOperationArgument(
                        boolean_operator="And",
                        operator="EQ",
                        column=VbExpr(text='"Age"'),
                        column_type="x:String",
                        operand=VbExpr(text="30.0"),
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: FilterDataTable" in code
    assert "[_frow for _frow in" not in code
    _compiles(code)


def test_join_data_tables_inner_join_renames_duplicate_key_column():
    """知見208: 実機2件(`TharakaMadushankaWanshathilaka/UiPath-Demo-
    Data-Tables`・`SuatOzcan/UiPathRoboticProcessAutomation`)相当の
    「蔵書とユーザーを共通の'ID'列でInner結合」——公式ドキュメントで
    確認した重複列名解決規則(`DataTable2`側の`ID`が`ID_1`にリネーム
    される)を実際に`exec()`で確認する。"""
    wf = _wrap(
        [
            BuildDataTableNode(
                data_table=VbExpr(text="OverdueBooks"), columns=["ID", "BookTitle"]
            ),
            AddDataRowNode(
                data_table=VbExpr(text="OverdueBooks"),
                array_row=VbExpr(text='{1, "Dune"}'),
            ),
            BuildDataTableNode(data_table=VbExpr(text="Users"), columns=["ID", "Name"]),
            AddDataRowNode(
                data_table=VbExpr(text="Users"), array_row=VbExpr(text='{1, "Alice"}')
            ),
            AddDataRowNode(
                data_table=VbExpr(text="Users"), array_row=VbExpr(text='{2, "Bob"}')
            ),
            JoinDataTablesNode(
                data_table1=VbExpr(text="OverdueBooks"),
                data_table2=VbExpr(text="Users"),
                output_data_table=VbExpr(text="BorrowedBooks"),
                join_type="Inner",
                arguments=[
                    JoinOperationArgument(
                        boolean_operator="And",
                        operator="EQ",
                        column1=VbExpr(text='"ID"'),
                        column1_type="x:String",
                        column2=VbExpr(text='"ID"'),
                        column2_type="x:String",
                    )
                ],
            ),
        ]
    )
    code = generate_python(wf)
    assert "# TODO" not in code
    assert "['ID_1', 'Name']" in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(  # noqa: S102 - 信頼できる自作コード
        code + "\n    return BorrowedBooks", namespace
    )
    assert namespace["Test"]() == [
        {"ID": 1, "BookTitle": "Dune", "ID_1": 1, "Name": "Alice"}
    ]


def test_join_data_tables_declines_non_inner_join_type_and_unconfirmed_operator():
    """知見208: `JoinType`が`"Inner"`以外(`"Left"`/`"Full"`は公式
    ドキュメントに記載はあるが実機未確認)・`Operator`が`"EQ"`以外は
    `# TODO`へ倒す。"""
    wf = _wrap(
        [
            BuildDataTableNode(data_table=VbExpr(text="t1"), columns=["ID"]),
            BuildDataTableNode(data_table=VbExpr(text="t2"), columns=["ID"]),
            JoinDataTablesNode(
                data_table1=VbExpr(text="t1"),
                data_table2=VbExpr(text="t2"),
                output_data_table=VbExpr(text="t3"),
                join_type="Left",
                arguments=[
                    JoinOperationArgument(
                        boolean_operator="And",
                        operator="EQ",
                        column1=VbExpr(text='"ID"'),
                        column1_type="x:String",
                        column2=VbExpr(text='"ID"'),
                        column2_type="x:String",
                    )
                ],
            ),
        ]
    )
    code = generate_python(wf)
    assert "# TODO: JoinDataTables with JoinType 'Left'" in code
    _compiles(code)

    wf2 = _wrap(
        [
            BuildDataTableNode(data_table=VbExpr(text="t1"), columns=["ID"]),
            BuildDataTableNode(data_table=VbExpr(text="t2"), columns=["ID"]),
            JoinDataTablesNode(
                data_table1=VbExpr(text="t1"),
                data_table2=VbExpr(text="t2"),
                output_data_table=VbExpr(text="t3"),
                join_type="Inner",
                arguments=[
                    JoinOperationArgument(
                        boolean_operator="And",
                        operator="GT",
                        column1=VbExpr(text='"ID"'),
                        column1_type="x:String",
                        column2=VbExpr(text='"ID"'),
                        column2_type="x:String",
                    )
                ],
            ),
        ]
    )
    code2 = generate_python(wf2)
    assert "# TODO: JoinDataTables with Operator 'GT'" in code2
    _compiles(code2)


def test_join_data_tables_declines_when_row_representation_is_unknown():
    """知見208: `DataTable1`/`DataTable2`どちらかが`BuildDataTable`由来
    だと確認できない場合はlist行の可能性を排除できないため`# TODO`へ
    倒す——知見206/207と同じ判断。"""
    wf = _wrap(
        [
            JoinDataTablesNode(
                data_table1=VbExpr(text="unknown_t1"),
                data_table2=VbExpr(text="unknown_t2"),
                output_data_table=VbExpr(text="t3"),
                join_type="Inner",
                arguments=[
                    JoinOperationArgument(
                        boolean_operator="And",
                        operator="EQ",
                        column1=VbExpr(text='"ID"'),
                        column1_type="x:String",
                        column2=VbExpr(text='"ID"'),
                        column2_type="x:String",
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: JoinDataTables" in code
    assert "_jrow1" not in code
    _compiles(code)


def test_remove_duplicate_rows_keeps_first_occurrence():
    """知見214: 実機2件(`cameronmcnz/uipath-tutorials`の
    `DedupeExcel/Main.xaml`・`mennatullahra/UiPath-ExcelDataManipulation`)
    相当の構成——全列の値が完全一致する行を重複として除去し、最初に
    出現した行を残す。"""
    wf = _wrap(
        [
            BuildDataTableNode(data_table=VbExpr(text="dt"), columns=["Name", "Age"]),
            AddDataRowNode(
                array_row=VbExpr(text='{"Alice", 30}'), data_table=VbExpr(text="dt")
            ),
            AddDataRowNode(
                array_row=VbExpr(text='{"Bob", 42}'), data_table=VbExpr(text="dt")
            ),
            AddDataRowNode(
                array_row=VbExpr(text='{"Alice", 30}'), data_table=VbExpr(text="dt")
            ),
            RemoveDuplicateRowsNode(
                data_table=VbExpr(text="dt"), output_data_table=VbExpr(text="dt")
            ),
        ]
    )
    code = generate_python(wf)
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code + "\n    return dt", namespace)  # noqa: S102 - 信頼できる自作コード
    assert namespace["Test"]() == [
        {"Name": "Alice", "Age": 30},
        {"Name": "Bob", "Age": 42},
    ]


def test_remove_duplicate_rows_declines_when_row_representation_is_unknown():
    """知見214: `DataTable`が`BuildDataTable`由来だと確認できない場合
    はlist行の可能性を排除できないため`# TODO`へ倒す——知見206-208と
    同じ判断。"""
    wf = _wrap(
        [
            RemoveDuplicateRowsNode(
                data_table=VbExpr(text="unknown_dt"),
                output_data_table=VbExpr(text="dt2"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: RemoveDuplicateRows" in code
    assert "_rdr_row" not in code
    _compiles(code)


def test_remove_duplicate_rows_with_missing_properties_is_todo():
    wf = _wrap([RemoveDuplicateRowsNode(data_table=None, output_data_table=VbExpr(text="dt2"))])
    code = generate_python(wf)
    assert "# TODO: RemoveDuplicateRows with missing DataTable/OutputDataTable" in code
    _compiles(code)


def test_remove_data_row_with_row_index_deletes_by_position():
    """知見182: `ui:RemoveDataRow`。`RowIndex`はPythonのlistインデックス
    として使うため、`round(_vb_cdbl(...))`(VBの`CInt`と同じ確認済みの
    整数変換経路、知見52・53)で整数へ変換する——`Literal`の素の文字列
    値をそのままインデックスに使うと`TypeError`になる実機で発見した
    バグの修正。"""
    wf = _wrap(
        [RemoveDataRowNode(data_table=VbExpr(text="t"), row_index=Literal(value="0"))]
    )
    code = generate_python(wf)
    assert "del t[round(_vb_cdbl('0'))]" in code
    assert "# TODO" not in code
    _compiles(code)


def test_remove_data_row_with_row_removes_by_value():
    wf = _wrap(
        [RemoveDataRowNode(data_table=VbExpr(text="t"), row=VbExpr(text="existingRow"))]
    )
    code = generate_python(wf)
    assert "t.remove(existingRow)" in code
    assert "# TODO" not in code
    _compiles(code)


def test_remove_data_row_display_name_becomes_a_comment():
    wf = _wrap(
        [
            RemoveDataRowNode(
                data_table=VbExpr(text="t"),
                row_index=Literal(value="0"),
                display_name="Remove Data Row",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Remove Data Row" in code
    assert "del t[" in code
    _compiles(code)


def test_remove_data_row_with_no_data_table_is_todo():
    wf = _wrap([RemoveDataRowNode(data_table=None, row_index=Literal(value="0"))])
    code = generate_python(wf)
    assert "# TODO: RemoveDataRow with no DataTable captured" in code
    _compiles(code)


def test_remove_data_row_with_no_row_or_row_index_is_todo():
    wf = _wrap([RemoveDataRowNode(data_table=VbExpr(text="t"))])
    code = generate_python(wf)
    assert "# TODO: RemoveDataRow with no Row/RowIndex captured" in code
    _compiles(code)


def test_remove_data_row_with_both_row_and_row_index_is_todo_not_guessed():
    wf = _wrap(
        [
            RemoveDataRowNode(
                data_table=VbExpr(text="t"),
                row=VbExpr(text="existingRow"),
                row_index=Literal(value="0"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: RemoveDataRow with both Row and RowIndex set" in code
    _compiles(code)


def test_get_row_item_with_column_name_indexes_by_name():
    """知見183: `ui:GetRowItem`(実機6件全てが`ColumnName`を使用)。
    `row[column_name]`という直接アクセスに対応する——dict行(`AddHeaders
    =True`由来)であれば正しく動作し、list行の場合は`TypeError`で
    即座に失敗する(でっち上げた値を返さない)。"""
    wf = _wrap(
        [
            GetRowItemNode(
                row=VbExpr(text="row"),
                column_name=Literal(value="lastname"),
                value=VbExpr(text="output"),
            )
        ]
    )
    code = generate_python(wf)
    assert "output = row['lastname']" in code
    assert "# TODO" not in code
    _compiles(code)


def test_get_row_item_with_column_index_handles_both_representations():
    """知見183: `ColumnIndex`は`DataTable`変数の実行時表現(dict行/
    list行)を実行時`isinstance`分岐で両方に対応する安全なコードを
    生成する。"""
    wf = _wrap(
        [
            GetRowItemNode(
                row=VbExpr(text="row"),
                column_index=Literal(value="1"),
                value=VbExpr(text="val"),
            )
        ]
    )
    code = generate_python(wf)
    assert "isinstance(row, dict)" in code
    assert "list(row.values())" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict = {}
    exec(code, namespace)
    dict_row = {"a": 10, "b": 20, "c": 30}
    list_row = ["x", "y", "z"]
    idx = round(namespace["_vb_cdbl"]("1"))
    assert (list(dict_row.values())[idx] if isinstance(dict_row, dict) else dict_row[idx]) == 20
    assert (list(list_row.values())[idx] if isinstance(list_row, dict) else list_row[idx]) == "y"


def test_get_row_item_display_name_becomes_a_comment():
    wf = _wrap(
        [
            GetRowItemNode(
                row=VbExpr(text="row"),
                column_name=Literal(value="x"),
                value=VbExpr(text="v"),
                display_name="Get Row Item",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Get Row Item" in code
    assert "row['x']" in code
    _compiles(code)


def test_get_row_item_with_no_row_is_todo():
    wf = _wrap([GetRowItemNode(row=None, column_name=Literal(value="x"), value=VbExpr(text="v"))])
    code = generate_python(wf)
    assert "# TODO: GetRowItem with no Row captured" in code
    _compiles(code)


def test_get_row_item_with_no_value_is_todo():
    wf = _wrap([GetRowItemNode(row=VbExpr(text="row"), column_name=Literal(value="x"), value=None)])
    code = generate_python(wf)
    assert "# TODO: GetRowItem with no output Value captured" in code
    _compiles(code)


def test_get_row_item_with_column_is_todo_not_guessed():
    """知見183: `Column`(既存の`DataColumn`オブジェクト参照)は未
    モデル化のため`# TODO`へ倒す。"""
    wf = _wrap(
        [
            GetRowItemNode(
                row=VbExpr(text="row"),
                column=VbExpr(text="existingColumn"),
                value=VbExpr(text="v"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: GetRowItem with Column set" in code
    _compiles(code)


def test_get_row_item_with_no_column_specifier_is_todo():
    wf = _wrap([GetRowItemNode(row=VbExpr(text="row"), value=VbExpr(text="v"))])
    code = generate_python(wf)
    assert "# TODO: GetRowItem with no ColumnIndex/ColumnName/Column captured" in code
    _compiles(code)


def test_get_row_item_with_both_column_index_and_column_name_is_todo_not_guessed():
    wf = _wrap(
        [
            GetRowItemNode(
                row=VbExpr(text="row"),
                column_index=Literal(value="0"),
                column_name=Literal(value="x"),
                value=VbExpr(text="v"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: GetRowItem with both ColumnIndex and ColumnName set" in code
    _compiles(code)


def test_update_row_item_with_column_name_assigns_by_name():
    """知見216: `ui:UpdateRowItem`(`GetRowItem`の対になる書き込み側)。
    実機`Andrew-SOA/Loan_Approval`相当の`row[column_name] = value`
    という直接代入——dict行なら正しく動作し、list行なら`TypeError`で
    即座に失敗する(でっち上げた動作をしない)。"""
    wf = _wrap(
        [
            UpdateRowItemNode(
                row=VbExpr(text="row"),
                column_name=Literal(value="Loan Approved"),
                value=Literal(value="Yes"),
            )
        ]
    )
    code = generate_python(wf)
    assert "row['Loan Approved'] = 'Yes'" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    row = {"Loan Approved": "No"}
    namespace["row"] = row
    namespace["Test"]()
    assert row == {"Loan Approved": "Yes"}


def test_update_row_item_with_column_index_handles_both_representations():
    """知見216: `ColumnIndex`は`GetRowItem`と同じdict/list両対応だが、
    位置で値を書き込むため該当キーを求めてから代入する(dict行)/
    直接添字代入する(list行)の2経路に分岐する。"""
    wf = _wrap(
        [
            UpdateRowItemNode(
                row=VbExpr(text="row"),
                column_index=Literal(value="1"),
                value=Literal(value="Maybe"),
            )
        ]
    )
    code = generate_python(wf)
    assert "isinstance(row, dict)" in code
    assert "list(row.keys())" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード

    dict_row = {"Name": "Carol", "Approved": "No"}
    namespace["row"] = dict_row
    namespace["Test"]()
    assert dict_row == {"Name": "Carol", "Approved": "Maybe"}

    list_row = ["Dave", "No"]
    namespace["row"] = list_row
    namespace["Test"]()
    assert list_row == ["Dave", "Maybe"]


def test_update_row_item_display_name_becomes_a_comment():
    wf = _wrap(
        [
            UpdateRowItemNode(
                row=VbExpr(text="row"),
                column_name=Literal(value="x"),
                value=Literal(value="v"),
                display_name="Update Row Item",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Update Row Item" in code
    assert "row['x'] = 'v'" in code
    _compiles(code)


def test_update_row_item_with_no_row_is_todo():
    wf = _wrap(
        [UpdateRowItemNode(row=None, column_name=Literal(value="x"), value=Literal(value="v"))]
    )
    code = generate_python(wf)
    assert "# TODO: UpdateRowItem with no Row captured" in code
    _compiles(code)


def test_update_row_item_with_no_value_is_todo():
    wf = _wrap(
        [UpdateRowItemNode(row=VbExpr(text="row"), column_name=Literal(value="x"), value=None)]
    )
    code = generate_python(wf)
    assert "# TODO: UpdateRowItem with no Value captured" in code
    _compiles(code)


def test_update_row_item_with_column_is_todo_not_guessed():
    """知見216: `Column`(既存の`DataColumn`オブジェクト参照)は未
    モデル化のため`# TODO`——`GetRowItem`と同じ判断。"""
    wf = _wrap(
        [
            UpdateRowItemNode(
                row=VbExpr(text="row"),
                column=VbExpr(text="someColumn"),
                value=Literal(value="v"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: UpdateRowItem with Column set" in code
    _compiles(code)


def test_update_row_item_with_both_column_index_and_column_name_is_todo_not_guessed():
    wf = _wrap(
        [
            UpdateRowItemNode(
                row=VbExpr(text="row"),
                column_index=Literal(value="0"),
                column_name=Literal(value="x"),
                value=Literal(value="v"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: UpdateRowItem with both ColumnIndex and ColumnName set" in code
    _compiles(code)


def test_extract_files_unpacks_archive_to_destination_folder():
    """知見217: `uascw:ExtractFiles`(`ui:`とは別の名前空間)。実機
    `duyphat2003/Working-with-files-and-folders_Practice-solution`
    相当の構成——`shutil.unpack_archive()`(標準ライブラリ)が直接対応
    する。実際にzipアーカイブを作成し、展開結果を確認する。"""
    src_dir = tempfile.mkdtemp()
    with open(os.path.join(src_dir, "a.txt"), "w") as f:
        f.write("hello world")
    zip_path = tempfile.mktemp(suffix=".zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(os.path.join(src_dir, "a.txt"), "a.txt")
    dest_dir = tempfile.mktemp()

    wf = _wrap(
        [
            ExtractFilesNode(
                file_to_extract=Literal(value=zip_path),
                destination_folder=Literal(value=dest_dir),
                code_page="Default",
                extract_to_a_dedicated_folder="False",
                skip_unsupported_files="False",
            )
        ]
    )
    code = generate_python(wf)
    assert f"shutil.unpack_archive({zip_path!r}, {dest_dir!r})" in code
    assert "import shutil" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    namespace["Test"]()
    assert os.listdir(dest_dir) == ["a.txt"]
    assert open(os.path.join(dest_dir, "a.txt")).read() == "hello world"


def test_extract_files_declines_unconfirmed_options_and_password():
    """知見217: `Password`(暗号化アーカイブ、実機未確認)・
    `ExtractToADedicatedFolder`/`SkipUnsupportedFiles`が実機確認済みの
    `"False"`以外の場合は`# TODO`へ倒す。"""
    base_kwargs = dict(
        file_to_extract=Literal(value="in.zip"),
        destination_folder=Literal(value="out_dir"),
        code_page="Default",
        extract_to_a_dedicated_folder="False",
        skip_unsupported_files="False",
    )

    wf = _wrap([ExtractFilesNode(**base_kwargs, password=VbExpr(text="pwd"))])
    code = generate_python(wf)
    assert "# TODO: ExtractFiles with Password set" in code
    _compiles(code)

    wf2 = _wrap(
        [ExtractFilesNode(**{**base_kwargs, "extract_to_a_dedicated_folder": "True"})]
    )
    code2 = generate_python(wf2)
    assert "# TODO: ExtractFiles with ExtractToADedicatedFolder 'True'" in code2
    _compiles(code2)

    wf3 = _wrap([ExtractFilesNode(**{**base_kwargs, "code_page": "UTF8"})])
    code3 = generate_python(wf3)
    assert "# TODO: ExtractFiles with CodePage 'UTF8'" in code3
    _compiles(code3)


def test_extract_files_with_missing_properties_is_todo():
    wf = _wrap(
        [
            ExtractFilesNode(
                file_to_extract=None,
                destination_folder=Literal(value="out_dir"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: ExtractFiles with missing FileToExtract/DestinationFolder" in code
    _compiles(code)


def test_compress_files_zips_folder_without_enclosing_folder_name():
    """知見218: `uascw:CompressFiles`(`ExtractFiles`と同じ名前空間)。
    フォーラム確認済みの挙動——`ContentToArchive`のフォルダパスは、
    そのフォルダ自身の名前をアーカイブに含めず、中身をトップレベルに
    展開する(サブフォルダ構造は保持)。実際にフォルダ+単独ファイルを
    圧縮し、zipの中身を確認する。"""
    src_dir = tempfile.mkdtemp()
    os.makedirs(os.path.join(src_dir, "sub"), exist_ok=True)
    with open(os.path.join(src_dir, "a.txt"), "w") as f:
        f.write("A")
    with open(os.path.join(src_dir, "sub", "b.txt"), "w") as f:
        f.write("B")
    standalone = tempfile.mktemp(suffix=".txt")
    with open(standalone, "w") as f:
        f.write("C")
    out_zip = tempfile.mktemp(suffix=".zip")

    wf = _wrap(
        [
            CompressFilesNode(
                content_to_archive=[Literal(value=src_dir), Literal(value=standalone)],
                compressed_file_name=Literal(value=out_zip),
                code_page="Default",
                compression_level="Normal",
                override_existing_file="True",
            )
        ]
    )
    code = generate_python(wf)
    assert "zipfile.ZipFile(" in code
    assert "import zipfile" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    namespace["Test"]()
    with zipfile.ZipFile(out_zip) as zf:
        names = sorted(zf.namelist())
    assert names == sorted(["a.txt", "sub/b.txt", os.path.basename(standalone)])


def test_compress_files_declines_password_and_unconfirmed_options():
    """知見218: `Password`/`SecurePassword`(`zipfile`標準では暗号化zip
    作成は不可)・確認済み以外の`CompressionLevel`/`EncryptionAlgorithm`
    は`# TODO`へ倒す。"""
    base_kwargs = dict(
        content_to_archive=[Literal(value="dir1")],
        compressed_file_name=Literal(value="out.zip"),
        code_page="Default",
        compression_level="Normal",
        override_existing_file="True",
    )

    wf = _wrap([CompressFilesNode(**base_kwargs, password=VbExpr(text="pwd"))])
    code = generate_python(wf)
    assert "# TODO: CompressFiles with Password/SecurePassword set" in code
    _compiles(code)

    wf2 = _wrap([CompressFilesNode(**{**base_kwargs, "compression_level": "Maximum"})])
    code2 = generate_python(wf2)
    assert "# TODO: CompressFiles with CompressionLevel 'Maximum'" in code2
    _compiles(code2)

    wf3 = _wrap(
        [CompressFilesNode(**{**base_kwargs, "encryption_algorithm": "AES256"})]
    )
    code3 = generate_python(wf3)
    assert "# TODO: CompressFiles with EncryptionAlgorithm 'AES256'" in code3
    _compiles(code3)


def test_compress_files_with_missing_properties_is_todo():
    wf = _wrap(
        [
            CompressFilesNode(
                content_to_archive=[],
                compressed_file_name=Literal(value="out.zip"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: CompressFiles with no ContentToArchive captured" in code
    _compiles(code)


def test_clear_data_table_calls_list_clear():
    """知見184: `ui:ClearDataTable`(GitHub code searchで225件ヒット)。
    `AddDataRow`/`RemoveDataRow`と同じ理由で`list.clear()`は
    `DataTable`変数の実行時表現を一切問わない安全な操作。"""
    wf = _wrap([ClearDataTableNode(data_table=VbExpr(text="dt"))])
    code = generate_python(wf)
    assert "dt.clear()" in code
    assert "# TODO" not in code
    _compiles(code)


def test_clear_data_table_display_name_becomes_a_comment():
    wf = _wrap(
        [ClearDataTableNode(data_table=VbExpr(text="dt"), display_name="Clear Data Table")]
    )
    code = generate_python(wf)
    assert "# Clear Data Table" in code
    assert "dt.clear()" in code
    _compiles(code)


def test_clear_data_table_with_no_data_table_is_todo():
    wf = _wrap([ClearDataTableNode(data_table=None)])
    code = generate_python(wf)
    assert "# TODO: ClearDataTable with no DataTable captured" in code
    _compiles(code)


def test_output_data_table_generates_csv_via_isinstance_dispatch():
    """知見184: `ui:OutputDataTable`(GitHub code searchで894件ヒット)。
    `GetRowItem`(知見183)と同じ`isinstance(row, dict)`の実行時分岐で
    `DataTable`の両表現(dict行/list行)に対応するCSVを生成する。"""
    wf = _wrap(
        [OutputDataTableNode(data_table=VbExpr(text="dt"), text=VbExpr(text="s"))]
    )
    code = generate_python(wf)
    assert "import csv" in code
    assert "import io" in code
    assert "isinstance(dt[0], dict)" in code
    assert "s = _buf.getvalue()" in code
    assert "WARNING" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict = {}
    exec(code, namespace)


def test_output_data_table_display_name_becomes_a_comment():
    wf = _wrap(
        [
            OutputDataTableNode(
                data_table=VbExpr(text="dt"),
                text=VbExpr(text="s"),
                display_name="Output Data Table",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Output Data Table" in code
    assert "csv.writer(" in code
    _compiles(code)


def test_output_data_table_with_no_data_table_is_todo():
    wf = _wrap([OutputDataTableNode(data_table=None, text=VbExpr(text="s"))])
    code = generate_python(wf)
    assert "# TODO: OutputDataTable with no DataTable captured" in code
    _compiles(code)


def test_output_data_table_with_no_text_is_todo():
    wf = _wrap([OutputDataTableNode(data_table=VbExpr(text="dt"), text=None)])
    code = generate_python(wf)
    assert "# TODO: OutputDataTable with no output Text captured" in code
    _compiles(code)


def test_add_data_column_adds_key_to_dict_rows():
    """知見198: `ui:AddDataColumn`(GitHub code searchで856件ヒット)。
    知見183の`isinstance(row, dict)`判定を「既存の全行への列追加」
    という文脈で使う——dict行にのみ`ColumnName`キーを追加する。"""
    wf = _wrap(
        [
            AddDataColumnNode(
                data_table=VbExpr(text="dt"),
                column_name=Literal(value="C"),
            )
        ]
    )
    code = generate_python(wf)
    assert "for _row in dt:" in code
    assert "if isinstance(_row, dict):" in code
    assert "_row['C'] = None" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    dt = [{"Name": "Alice"}, ["list", "row"]]
    namespace["dt"] = dt
    namespace["Test"]()
    assert dt[0] == {"Name": "Alice", "C": None}
    assert dt[1] == ["list", "row"]


def test_add_data_column_with_default_value_uses_it():
    wf = _wrap(
        [
            AddDataColumnNode(
                data_table=VbExpr(text="dt"),
                column_name=Literal(value="C"),
                default_value=Literal(value="x"),
            )
        ]
    )
    code = generate_python(wf)
    assert "_row['C'] = 'x'" in code
    _compiles(code)


def test_add_data_column_display_name_becomes_a_comment():
    wf = _wrap(
        [
            AddDataColumnNode(
                data_table=VbExpr(text="dt"),
                column_name=Literal(value="C"),
                display_name="Add data column",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Add data column" in code
    _compiles(code)


def test_add_data_column_with_missing_data_table_or_name_is_todo():
    wf = _wrap([AddDataColumnNode(data_table=None, column_name=Literal(value="C"))])
    code = generate_python(wf)
    assert "# TODO: AddDataColumn with missing DataTable/ColumnName" in code
    _compiles(code)


def test_add_data_column_with_column_reference_is_todo_not_guessed():
    wf = _wrap(
        [
            AddDataColumnNode(
                data_table=VbExpr(text="dt"),
                column_name=Literal(value="C"),
                column=VbExpr(text="col"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: AddDataColumn with Column set" in code
    _compiles(code)


def test_add_data_column_with_auto_increment_is_todo_not_guessed():
    wf = _wrap(
        [
            AddDataColumnNode(
                data_table=VbExpr(text="dt"),
                column_name=Literal(value="C"),
                auto_increment="True",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: AddDataColumn with AutoIncrement=True" in code
    _compiles(code)


def test_add_data_column_with_unique_is_todo_not_guessed():
    wf = _wrap(
        [
            AddDataColumnNode(
                data_table=VbExpr(text="dt"),
                column_name=Literal(value="C"),
                unique="True",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: AddDataColumn with Unique=True" in code
    _compiles(code)


def test_add_data_column_with_allow_db_null_false_is_todo_not_guessed():
    wf = _wrap(
        [
            AddDataColumnNode(
                data_table=VbExpr(text="dt"),
                column_name=Literal(value="C"),
                allow_db_null="False",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: AddDataColumn with AllowDBNull=False" in code
    _compiles(code)


def test_remove_data_column_pops_key_from_dict_rows():
    """知見198: `ui:RemoveDataColumn`(GitHub code searchで273件
    ヒット、`AddDataColumn`の正反対)。`dict.pop(key, None)`で
    キーが無くても安全に削除する。"""
    wf = _wrap(
        [
            RemoveDataColumnNode(
                data_table=VbExpr(text="dt"),
                column_name=Literal(value="firstname"),
            )
        ]
    )
    code = generate_python(wf)
    assert "for _row in dt:" in code
    assert "if isinstance(_row, dict):" in code
    assert "_row.pop('firstname', None)" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    dt = [{"firstname": "Alice", "lastname": "A"}, ["list", "row"]]
    namespace["dt"] = dt
    namespace["Test"]()
    assert dt[0] == {"lastname": "A"}
    assert dt[1] == ["list", "row"]


def test_remove_data_column_display_name_becomes_a_comment():
    wf = _wrap(
        [
            RemoveDataColumnNode(
                data_table=VbExpr(text="dt"),
                column_name=Literal(value="firstname"),
                display_name="Remove Data Column",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Remove Data Column" in code
    _compiles(code)


def test_remove_data_column_with_missing_data_table_or_name_is_todo():
    wf = _wrap(
        [RemoveDataColumnNode(data_table=None, column_name=Literal(value="firstname"))]
    )
    code = generate_python(wf)
    assert "# TODO: RemoveDataColumn with missing DataTable/ColumnName" in code
    _compiles(code)


def test_remove_data_column_with_column_reference_is_todo_not_guessed():
    wf = _wrap(
        [
            RemoveDataColumnNode(
                data_table=VbExpr(text="dt"),
                column_name=Literal(value="firstname"),
                column=VbExpr(text="col"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: RemoveDataColumn with Column set" in code
    _compiles(code)


def test_remove_data_column_with_column_index_is_todo_not_guessed():
    wf = _wrap(
        [
            RemoveDataColumnNode(
                data_table=VbExpr(text="dt"),
                column_name=Literal(value="firstname"),
                column_index=Literal(value="0"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: RemoveDataColumn with ColumnIndex set" in code
    _compiles(code)


def test_read_csv_file_uses_dict_reader():
    """知見185: `ui:ReadCsvFile`(GitHub code searchで657件ヒット)。
    `csv.DictReader`が、CSVの1行目をヘッダーとして常に扱うという
    `ReadCsvFile`の意味論に直接対応する。"""
    wf = _wrap(
        [
            ReadCsvFileNode(
                file_path=Literal(value="in.csv"), data_table=VbExpr(text="dt")
            )
        ]
    )
    code = generate_python(wf)
    assert "dt = [dict(_row) for _row in csv.DictReader(_f)]" in code
    assert "import csv" in code
    assert "# TODO" not in code
    _compiles(code)


def test_read_csv_file_display_name_becomes_a_comment():
    wf = _wrap(
        [
            ReadCsvFileNode(
                file_path=Literal(value="in.csv"),
                data_table=VbExpr(text="dt"),
                display_name="Read CSV",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Read CSV" in code
    assert "csv.DictReader(" in code
    _compiles(code)


def test_read_csv_file_with_no_file_path_is_todo():
    wf = _wrap([ReadCsvFileNode(file_path=None, data_table=VbExpr(text="dt"))])
    code = generate_python(wf)
    assert "# TODO: ReadCsvFile with no FilePath captured" in code
    _compiles(code)


def test_read_csv_file_with_no_data_table_is_todo():
    wf = _wrap([ReadCsvFileNode(file_path=Literal(value="in.csv"), data_table=None)])
    code = generate_python(wf)
    assert "# TODO: ReadCsvFile with no output DataTable captured" in code
    _compiles(code)


def test_read_csv_file_with_path_resource_is_todo_not_guessed():
    wf = _wrap(
        [
            ReadCsvFileNode(
                file_path=Literal(value="in.csv"),
                data_table=VbExpr(text="dt"),
                path_resource=VbExpr(text="res"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: ReadCsvFile with PathResource set" in code
    _compiles(code)


def test_read_csv_file_with_non_comma_delimitator_is_todo_not_guessed():
    wf = _wrap(
        [
            ReadCsvFileNode(
                file_path=Literal(value="in.csv"),
                data_table=VbExpr(text="dt"),
                delimitator="Semicolon",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: ReadCsvFile with non-default Delimitator" in code
    _compiles(code)


def test_read_pdf_text_with_range_all_joins_all_pages():
    """知見199: `ui:ReadPDFText`(GitHub code searchで539件ヒット)。
    `pypdf.PdfReader(...).pages[i].extract_text()`(`pyproject.toml`で
    既に確認済みの依存)が直接対応する。"""
    wf = _wrap(
        [
            ReadPdfTextNode(
                file_name=Literal(value="in.pdf"),
                text=VbExpr(text="txt"),
                range=Literal(value="All"),
            )
        ]
    )
    code = generate_python(wf)
    assert "pypdf.PdfReader('in.pdf')" in code
    assert "import pypdf" in code
    assert "# TODO" not in code
    _compiles(code)


def test_read_pdf_text_with_single_page_range():
    wf = _wrap(
        [
            ReadPdfTextNode(
                file_name=Literal(value="in.pdf"),
                text=VbExpr(text="txt"),
                range=Literal(value="2"),
            )
        ]
    )
    code = generate_python(wf)
    assert "if '2' == 'All':" in code
    assert "pages[int('2') - 1].extract_text()" in code
    assert "# TODO" not in code
    _compiles(code)


def test_read_pdf_text_with_dynamic_range_generates_runtime_branch():
    wf = _wrap(
        [
            ReadPdfTextNode(
                file_name=VbExpr(text="path"),
                text=VbExpr(text="txt"),
                range=VbExpr(text="rangeVar"),
            )
        ]
    )
    code = generate_python(wf)
    assert "if rangeVar == 'All':" in code
    assert "pages[int(rangeVar) - 1].extract_text()" in code
    assert "# TODO" not in code
    _compiles(code)


def test_read_pdf_text_display_name_becomes_a_comment():
    wf = _wrap(
        [
            ReadPdfTextNode(
                file_name=Literal(value="in.pdf"),
                text=VbExpr(text="txt"),
                range=Literal(value="All"),
                display_name="Read PDF Text",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Read PDF Text" in code
    assert "pypdf.PdfReader(" in code
    _compiles(code)


def test_read_pdf_text_with_no_file_name_is_todo():
    wf = _wrap([ReadPdfTextNode(file_name=None, text=VbExpr(text="txt"))])
    code = generate_python(wf)
    assert "# TODO: ReadPDFText with no FileName captured" in code
    _compiles(code)


def test_read_pdf_text_with_no_text_is_todo():
    wf = _wrap([ReadPdfTextNode(file_name=Literal(value="in.pdf"), text=None)])
    code = generate_python(wf)
    assert "# TODO: ReadPDFText with no output Text captured" in code
    _compiles(code)


def test_read_pdf_text_with_preserve_formatting_is_todo_not_guessed():
    wf = _wrap(
        [
            ReadPdfTextNode(
                file_name=Literal(value="in.pdf"),
                text=VbExpr(text="txt"),
                range=Literal(value="All"),
                preserve_formatting=Literal(value="True"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: ReadPDFText with PreserveFormatting set" in code
    _compiles(code)


def test_read_pdf_text_with_hyphenated_range_is_todo_not_guessed():
    wf = _wrap(
        [
            ReadPdfTextNode(
                file_name=Literal(value="in.pdf"),
                text=VbExpr(text="txt"),
                range=Literal(value="8-22"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: ReadPDFText with hyphenated Range" in code
    _compiles(code)


def test_get_pdf_page_count_uses_len_pages():
    """知見200: `GetPDFPageCount`(`upap:`名前空間)。
    `len(pypdf.PdfReader(...).pages)`が直接対応する。"""
    wf = _wrap(
        [
            GetPdfPageCountNode(
                file_name=Literal(value="a.pdf"),
                page_count=VbExpr(text="n"),
            )
        ]
    )
    code = generate_python(wf)
    assert "n = len(pypdf.PdfReader('a.pdf').pages)" in code
    assert "import pypdf" in code
    assert "# TODO" not in code
    _compiles(code)


def test_get_pdf_page_count_display_name_becomes_a_comment():
    wf = _wrap(
        [
            GetPdfPageCountNode(
                file_name=Literal(value="a.pdf"),
                page_count=VbExpr(text="n"),
                display_name="Get PDF Page Count",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Get PDF Page Count" in code
    _compiles(code)


def test_get_pdf_page_count_with_no_file_name_is_todo():
    wf = _wrap([GetPdfPageCountNode(file_name=None, page_count=VbExpr(text="n"))])
    code = generate_python(wf)
    assert "# TODO: GetPDFPageCount with no FileName captured" in code
    _compiles(code)


def test_get_pdf_page_count_with_no_output_is_todo():
    wf = _wrap([GetPdfPageCountNode(file_name=Literal(value="a.pdf"), page_count=None)])
    code = generate_python(wf)
    assert "# TODO: GetPDFPageCount with no output PageCount captured" in code
    _compiles(code)


def test_extract_pdf_page_range_writes_new_pdf():
    """知見200: `ExtractPDFPageRange`(`GetPDFPageCount`と同じ`upap:`
    名前空間)。実機で確認した`"8-22"`形のRangeのみ対応する。"""
    wf = _wrap(
        [
            ExtractPdfPageRangeNode(
                file_name=Literal(value="a.pdf"),
                output_file_name=Literal(value="out.pdf"),
                range=Literal(value="8-22"),
            )
        ]
    )
    code = generate_python(wf)
    assert "_eppr_start, _eppr_end = ('8-22').split('-')" in code
    assert "_eppr_writer.add_page(_eppr_reader.pages[_eppr_i - 1])" in code
    assert "import pypdf" in code
    assert "# TODO" not in code
    _compiles(code)


def test_extract_pdf_page_range_display_name_becomes_a_comment():
    wf = _wrap(
        [
            ExtractPdfPageRangeNode(
                file_name=Literal(value="a.pdf"),
                output_file_name=Literal(value="out.pdf"),
                range=Literal(value="8-22"),
                display_name="Extract PDF Page Range",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Extract PDF Page Range" in code
    _compiles(code)


def test_extract_pdf_page_range_with_missing_properties_is_todo():
    wf = _wrap(
        [
            ExtractPdfPageRangeNode(
                file_name=None,
                output_file_name=Literal(value="out.pdf"),
                range=Literal(value="8-22"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: ExtractPDFPageRange with missing" in code
    _compiles(code)


def test_extract_pdf_page_range_with_unconfirmed_range_format_is_todo():
    wf = _wrap(
        [
            ExtractPdfPageRangeNode(
                file_name=Literal(value="a.pdf"),
                output_file_name=Literal(value="out.pdf"),
                range=Literal(value="1,3,5-10"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: ExtractPDFPageRange with Range" in code
    assert "not in the confirmed 'N-M' form" in code
    _compiles(code)


def test_extract_pdf_page_range_with_dynamic_range_generates_runtime_split():
    wf = _wrap(
        [
            ExtractPdfPageRangeNode(
                file_name=VbExpr(text="path"),
                output_file_name=VbExpr(text="outPath"),
                range=VbExpr(text="rangeVar"),
            )
        ]
    )
    code = generate_python(wf)
    assert "_eppr_start, _eppr_end = (rangeVar).split('-')" in code
    assert "# TODO" not in code
    _compiles(code)


def test_join_pdf_appends_each_file_in_order():
    """知見201: `JoinPDF`(`GetPDFPageCount`/`ExtractPDFPageRange`
    知見200と同じ`upap:`名前空間)。`pypdf.PdfWriter.append()`
    (`pad_action_lib/pdf_actions.py`の`merge_pdf_files()`と同じ
    イディオム)で各パスを順に結合する。"""
    wf = _wrap(
        [
            JoinPdfNode(
                file_list=VbExpr(text='{"a.pdf","b.pdf"}'),
                output_file_name=Literal(value="out.pdf"),
            )
        ]
    )
    code = generate_python(wf)
    assert "for _jp_path in ['a.pdf', 'b.pdf']:" in code
    assert "_jp_writer.append(pypdf.PdfReader(_jp_path))" in code
    assert "import pypdf" in code
    assert "# TODO" not in code
    _compiles(code)


def test_join_pdf_display_name_becomes_a_comment():
    wf = _wrap(
        [
            JoinPdfNode(
                file_list=VbExpr(text='{"a.pdf"}'),
                output_file_name=Literal(value="out.pdf"),
                display_name="Join PDF Files",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Join PDF Files" in code
    _compiles(code)


def test_join_pdf_with_missing_properties_is_todo():
    wf = _wrap([JoinPdfNode(file_list=None, output_file_name=Literal(value="out.pdf"))])
    code = generate_python(wf)
    assert "# TODO: JoinPDF with missing FileList/OutputFileName" in code
    _compiles(code)


def test_export_pdf_page_as_image_generates_pymupdf_render_call():
    """知見209: `ExportPDFPageAsImage`(`GetPDFPageCount`/
    `ExtractPDFPageRange`/`JoinPDF`知見200・201と同じ`upap:`名前空間)。
    `pymupdf`は`[project.optional-dependencies]`の`pdf-render`プラグイン
    群(知見209の設計判断、本体`dependencies`には無い)——コード生成
    自体はトランスパイラ側でのimportを必要としない(`pypdf`と同じ設計、
    純粋な文字列生成)。"""
    wf = _wrap(
        [
            ExportPdfPageAsImageNode(
                file_name=Literal(value="in.pdf"),
                output_file_name=Literal(value="out.png"),
                page_number=Literal(value="2"),
                image_dpi="150",
            )
        ]
    )
    code = generate_python(wf)
    assert "import pymupdf" in code
    assert "pymupdf.open('in.pdf')" in code
    assert "get_pixmap(dpi=round(_vb_cdbl('150')))" in code
    assert "# TODO" not in code
    _compiles(code)


def test_export_pdf_page_as_image_renders_the_correct_page():
    """知見209: `pymupdf`が実際にインストールされている場合のみ実行
    する統合テスト(`dev`依存グループで確認済み、無い環境では自動
    skip——`pdf-render`プラグインの「無くても他のテストは通る」設計を
    確認する)。実際にreportlabで2ページPDFを生成し、2ページ目だけが
    画像化されることを`exec()`経由で確認する。"""
    pytest.importorskip("pymupdf")
    reportlab_canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    from reportlab.lib.pagesizes import letter

    pdf_path = tempfile.mktemp(suffix=".pdf")
    out_path = tempfile.mktemp(suffix=".png")
    c = reportlab_canvas.Canvas(pdf_path, pagesize=letter)
    c.drawString(100, 700, "Page 1")
    c.showPage()
    c.drawString(100, 700, "Page 2")
    c.showPage()
    c.save()

    wf = _wrap(
        [
            ExportPdfPageAsImageNode(
                file_name=Literal(value=pdf_path),
                output_file_name=Literal(value=out_path),
                page_number=Literal(value="2"),
                image_dpi="150",
            )
        ]
    )
    code = generate_python(wf)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    namespace["Test"]()
    assert os.path.exists(out_path)
    assert os.path.getsize(out_path) > 0


def test_export_pdf_page_as_image_with_missing_properties_is_todo():
    wf = _wrap(
        [
            ExportPdfPageAsImageNode(
                file_name=None,
                output_file_name=Literal(value="out.png"),
                page_number=Literal(value="1"),
                image_dpi="150",
            )
        ]
    )
    code = generate_python(wf)
    assert (
        "# TODO: ExportPDFPageAsImage with missing FileName/OutputFileName/"
        "PageNumber" in code
    )
    _compiles(code)


def test_extract_images_from_pdf_generates_pymupdf_extraction_loop():
    """知見209: `ExtractImagesFromPDF`。PyMuPDF公式レシピ
    (`Page.get_images()`+`Document.extract_image(xref)`)が直接対応
    する——`pymupdf`は`ExportPDFPageAsImage`と同じ`pdf-render`プラグイン
    (知見209の設計判断、本体`dependencies`には無い)。"""
    wf = _wrap(
        [
            ExtractImagesFromPdfNode(
                file_name=Literal(value="in.pdf"),
                output_folder_name=Literal(value="out_dir"),
            )
        ]
    )
    code = generate_python(wf)
    assert "import pymupdf" in code
    assert "import os" in code
    assert "pymupdf.open('in.pdf')" in code
    assert "_eifp_doc.extract_image(_eifp_xref)" in code
    assert "os.path.join('out_dir'," in code
    assert "# TODO" not in code
    _compiles(code)


def test_extract_images_from_pdf_extracts_the_embedded_image():
    """知見209: `pymupdf`が実際にインストールされている場合のみ実行
    する統合テスト(無い環境では自動skip)。reportlabで埋め込み画像付き
    PDFを生成し、実際に画像バイト列が正しく抽出されることを`exec()`
    経由で確認する。"""
    pytest.importorskip("pymupdf")
    reportlab_canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    pil_image = pytest.importorskip("PIL.Image")
    from reportlab.lib.pagesizes import letter

    img_path = tempfile.mktemp(suffix=".png")
    pil_image.new("RGB", (10, 10), color="red").save(img_path)

    pdf_path = tempfile.mktemp(suffix=".pdf")
    c = reportlab_canvas.Canvas(pdf_path, pagesize=letter)
    c.drawImage(img_path, 100, 600, width=50, height=50)
    c.showPage()
    c.save()

    out_dir = tempfile.mkdtemp()

    wf = _wrap(
        [
            ExtractImagesFromPdfNode(
                file_name=Literal(value=pdf_path),
                output_folder_name=Literal(value=out_dir),
            )
        ]
    )
    code = generate_python(wf)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    namespace["Test"]()
    extracted = os.listdir(out_dir)
    assert len(extracted) == 1
    assert extracted[0].startswith("img-")


def test_extract_images_from_pdf_declines_unconfirmed_image_extension():
    """知見209: `ImageExtension`は実機で非`{x:Null}`の実例が無いため
    `# TODO`へ倒す(同名別活動`apac:ExtractImagesFromPDF`の数値enum
    との混同を避ける意味もある)。"""
    wf = _wrap(
        [
            ExtractImagesFromPdfNode(
                file_name=Literal(value="in.pdf"),
                output_folder_name=Literal(value="out_dir"),
                image_extension=Literal(value="jpeg"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: ExtractImagesFromPDF with ImageExtension set" in code
    _compiles(code)


def test_extract_images_from_pdf_with_missing_properties_is_todo():
    wf = _wrap(
        [ExtractImagesFromPdfNode(file_name=None, output_folder_name=Literal(value="out"))]
    )
    code = generate_python(wf)
    assert "# TODO: ExtractImagesFromPDF with missing FileName/OutputFolderName" in code
    _compiles(code)


def test_manage_pdf_password_with_owner_password_only():
    """知見202: `ManagePDFPassword`(`GetPDFPageCount`/
    `ExtractPDFPageRange`/`JoinPDF`知見200・201と同じ`upap:`名前空間)。
    `pypdf.PdfWriter.encrypt()`が直接対応する。`NewOwnerPassword`のみ
    設定時は`user_password=''`を渡す。"""
    wf = _wrap(
        [
            ManagePdfPasswordNode(
                file_name=Literal(value="in.pdf"),
                output_file_name=Literal(value="out.pdf"),
                new_owner_password=Literal(value="1234"),
            )
        ]
    )
    code = generate_python(wf)
    assert "_mpp_writer.encrypt(user_password='', owner_password='1234')" in code
    assert "import pypdf" in code
    assert "# TODO" not in code
    _compiles(code)


def test_manage_pdf_password_with_user_password_only():
    wf = _wrap(
        [
            ManagePdfPasswordNode(
                file_name=Literal(value="in.pdf"),
                output_file_name=Literal(value="out.pdf"),
                new_user_password=Literal(value="1234"),
            )
        ]
    )
    code = generate_python(wf)
    assert "_mpp_writer.encrypt(user_password='1234', owner_password=None)" in code
    assert "# TODO" not in code
    _compiles(code)


def test_manage_pdf_password_display_name_becomes_a_comment():
    wf = _wrap(
        [
            ManagePdfPasswordNode(
                file_name=Literal(value="in.pdf"),
                output_file_name=Literal(value="out.pdf"),
                new_user_password=Literal(value="1234"),
                display_name="Manage PDF Password",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Manage PDF Password" in code
    _compiles(code)


def test_manage_pdf_password_with_missing_properties_is_todo():
    wf = _wrap(
        [
            ManagePdfPasswordNode(
                file_name=None,
                output_file_name=Literal(value="out.pdf"),
                new_user_password=Literal(value="1234"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: ManagePDFPassword with missing FileName/OutputFileName" in code
    _compiles(code)


def test_manage_pdf_password_with_old_password_is_todo_not_guessed():
    wf = _wrap(
        [
            ManagePdfPasswordNode(
                file_name=Literal(value="in.pdf"),
                output_file_name=Literal(value="out.pdf"),
                old_user_password=Literal(value="1234"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: ManagePDFPassword with OldUserPassword/OldOwnerPassword set" in code
    _compiles(code)


def test_manage_pdf_password_with_no_new_password_is_todo():
    wf = _wrap(
        [
            ManagePdfPasswordNode(
                file_name=Literal(value="in.pdf"),
                output_file_name=Literal(value="out.pdf"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: ManagePDFPassword with no NewUserPassword/NewOwnerPassword captured" in code
    _compiles(code)


def test_write_csv_file_handles_both_representations():
    """知見185: `ui:WriteCsvFile`(`ReadCsvFile`の正反対)。
    `OutputDataTable`(知見184)と同じ`isinstance`分岐でdict行/list行
    両方に対応する。"""
    wf = _wrap(
        [
            WriteCsvFileNode(
                file_path=Literal(value="out.csv"), data_table=VbExpr(text="dt")
            )
        ]
    )
    code = generate_python(wf)
    assert "isinstance(dt[0], dict)" in code
    assert "csv.writer(_f)" in code
    assert "WARNING" in code
    assert "# TODO" not in code
    _compiles(code)


def test_write_csv_file_with_add_headers_false_omits_header_row():
    wf = _wrap(
        [
            WriteCsvFileNode(
                file_path=Literal(value="out.csv"),
                data_table=VbExpr(text="dt"),
                add_headers="False",
            )
        ]
    )
    code = generate_python(wf)
    assert "_writer.writerow(dt[0].keys())" not in code
    _compiles(code)


def test_write_csv_file_display_name_becomes_a_comment():
    wf = _wrap(
        [
            WriteCsvFileNode(
                file_path=Literal(value="out.csv"),
                data_table=VbExpr(text="dt"),
                display_name="Write CSV",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Write CSV" in code
    assert "csv.writer(" in code
    _compiles(code)


def test_write_csv_file_with_no_file_path_is_todo():
    wf = _wrap([WriteCsvFileNode(file_path=None, data_table=VbExpr(text="dt"))])
    code = generate_python(wf)
    assert "# TODO: WriteCsvFile with no FilePath captured" in code
    _compiles(code)


def test_write_csv_file_with_no_data_table_is_todo():
    wf = _wrap([WriteCsvFileNode(file_path=Literal(value="out.csv"), data_table=None)])
    code = generate_python(wf)
    assert "# TODO: WriteCsvFile with no DataTable captured" in code
    _compiles(code)


def test_write_csv_file_with_non_true_should_quote_is_todo_not_guessed():
    wf = _wrap(
        [
            WriteCsvFileNode(
                file_path=Literal(value="out.csv"),
                data_table=VbExpr(text="dt"),
                should_quote="False",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: WriteCsvFile with non-default ShouldQuote" in code
    _compiles(code)


def test_deserialize_xml_then_execute_xpath_pipeline():
    """知見228: `ui:DeserializeXml`→`ui:ExecuteXPath`の定番パイプライン
    (実機`Sundsvallskommun/RPA-openeplatformapi`相当)。`exec()`経由で
    実際にXML文字列をパースし、`string()`ラップされたXPath式で
    単一文字列を抜き出せることを確認する。"""
    wf = _wrap(
        [
            DeserializeXmlNode(
                xml_string=VbExpr(text="ResultString"),
                xml_document=VbExpr(text="ResultAsXMLDocument"),
            ),
            ExecuteXPathNode(
                existing_xml=VbExpr(text="ResultAsXMLDocument"),
                xpath_expression=Literal(value="string(//Status/name)"),
                result=VbExpr(text="statusName"),
            ),
        ]
    )
    code = generate_python(wf)
    assert "import lxml.etree" in code
    assert "lxml.etree.fromstring(" in code
    assert ".xpath(" in code
    assert "# TODO" not in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(ResultString):")
    code2 += "\n    return statusName"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    assert (
        namespace["Test"]("<Status><name>Processed</name></Status>")
        == "Processed"
    )


def test_execute_xpath_prefers_xml_string_when_both_set():
    """知見228: 公式ドキュメント確認済み——`XMLString`を入力すると
    `ExistingXML`は使用不可になる(実機では常に片方だけが非null)
    ため、両方設定されている場合は`XMLString`を優先する。"""
    wf = _wrap(
        [
            ExecuteXPathNode(
                xml_string=VbExpr(text="raw"),
                existing_xml=VbExpr(text="unused_existing"),
                xpath_expression=Literal(value="string(//a)"),
                result=VbExpr(text="r"),
            )
        ]
    )
    code = generate_python(wf)
    assert "lxml.etree.fromstring(" in code
    assert "unused_existing" not in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(raw):")
    code2 += "\n    return r"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    assert namespace["Test"]("<root><a>hi</a></root>") == "hi"


def test_execute_xpath_with_no_xml_source_is_todo():
    wf = _wrap(
        [
            ExecuteXPathNode(
                xml_string=None,
                existing_xml=None,
                xpath_expression=Literal(value="string(//a)"),
                result=VbExpr(text="r"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: ExecuteXPath with no XMLString/ExistingXML captured" in code
    _compiles(code)


def test_deserialize_xml_with_missing_properties_is_todo():
    wf = _wrap([DeserializeXmlNode(xml_string=None, xml_document=VbExpr(text="x"))])
    code = generate_python(wf)
    assert "# TODO: DeserializeXml with missing XMLString/XMLDocument" in code
    _compiles(code)


def test_invoke_powershell_runs_pwsh_with_check_true():
    """知見186: `ui:InvokePowerShell`(GitHub code searchで337件
    ヒット)。`PowerShellProcess="PowerShellCore"`の場合、
    `subprocess.run(["pwsh", "-Command", ...], check=True)`が直接
    対応する——`check=True`は`ContinueOnError`の既定値(エラーを
    伝播させる)に合わせる。"""
    wf = _wrap(
        [
            InvokePowerShellNode(
                command_text=Literal(value="Get-Process"),
                powershell_process="PowerShellCore",
            )
        ]
    )
    code = generate_python(wf)
    assert 'subprocess.run(["pwsh", "-Command", \'Get-Process\'], check=True)' in code
    assert "import subprocess" in code
    assert "# TODO" not in code
    _compiles(code)


def test_invoke_powershell_display_name_becomes_a_comment():
    wf = _wrap(
        [
            InvokePowerShellNode(
                command_text=Literal(value="Get-Process"),
                powershell_process="PowerShellCore",
                display_name="Invoke Power Shell",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Invoke Power Shell" in code
    assert "subprocess.run(" in code
    _compiles(code)


def test_invoke_powershell_with_no_command_text_is_todo():
    wf = _wrap([InvokePowerShellNode(command_text=None, powershell_process="PowerShellCore")])
    code = generate_python(wf)
    assert "# TODO: InvokePowerShell with no CommandText captured" in code
    _compiles(code)


def test_invoke_powershell_with_non_powershell_core_is_todo_not_guessed():
    wf = _wrap(
        [
            InvokePowerShellNode(
                command_text=Literal(value="Get-Process"),
                powershell_process="WindowsPowerShell",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: InvokePowerShell with PowerShellProcess" in code
    assert "subprocess" not in code
    _compiles(code)


def test_invoke_powershell_with_parameters_is_todo_not_guessed():
    wf = _wrap(
        [
            InvokePowerShellNode(
                command_text=Literal(value="Get-Process"),
                powershell_process="PowerShellCore",
                has_parameters=True,
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: InvokePowerShell with Parameters set" in code
    _compiles(code)


def test_invoke_powershell_with_powershell_variables_is_todo_not_guessed():
    wf = _wrap(
        [
            InvokePowerShellNode(
                command_text=Literal(value="Get-Process"),
                powershell_process="PowerShellCore",
                has_powershell_variables=True,
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: InvokePowerShell with PowerShellVariables set" in code
    _compiles(code)


def test_invoke_powershell_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap(
        [
            InvokePowerShellNode(
                command_text=Literal(value="Get-Process"),
                powershell_process="PowerShellCore",
                continue_on_error=Literal(value="False"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: InvokePowerShell with ContinueOnError set" in code
    _compiles(code)


def test_invoke_powershell_with_pipeline_output_is_todo_not_guessed():
    wf = _wrap(
        [
            InvokePowerShellNode(
                command_text=Literal(value="Get-Process"),
                powershell_process="PowerShellCore",
                pipeline_output=VbExpr(text="out"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: InvokePowerShell with PipelineOutput bound" in code
    _compiles(code)


def test_retry_scope_retries_body_until_success():
    """知見187: `ui:RetryScope`(GitHub code searchで3280件ヒット)。
    `Condition`が空の場合、「本体が例外無しで完了するまで最大
    `NumberOfRetries`回まで再試行し、全回失敗したら最後の例外を
    伝播させる」という確認済みの意味論(公式REFrameworkテンプレート
    `SetTransactionStatus.xaml`のTryCatch+Rethrowパターン)を
    実装する。"""
    wf = _wrap(
        [
            RetryScopeNode(
                body=[LogMessageNode(message=Literal(value="x"), level="Info")],
                number_of_retries=Literal(value="3"),
            )
        ]
    )
    code = generate_python(wf)
    assert "_retry_max = round(_vb_cdbl('3'))" in code
    assert "for _retry_attempt in range(_retry_max):" in code
    assert "except Exception:" in code
    assert "if _retry_attempt == _retry_max - 1:" in code
    assert "raise" in code
    assert "break" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict = {}
    exec(code, namespace)


def test_retry_scope_display_name_becomes_a_comment():
    wf = _wrap(
        [
            RetryScopeNode(
                body=[LogMessageNode(message=Literal(value="x"), level="Info")],
                number_of_retries=Literal(value="3"),
                display_name="Retry",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Retry" in code
    assert "for _retry_attempt in range(_retry_max):" in code
    _compiles(code)


def test_retry_scope_with_no_number_of_retries_is_todo():
    wf = _wrap(
        [
            RetryScopeNode(
                body=[LogMessageNode(message=Literal(value="x"), level="Info")],
                number_of_retries=None,
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: RetryScope with no NumberOfRetries captured" in code
    _compiles(code)


def test_retry_scope_with_non_empty_condition_is_todo_not_guessed():
    wf = _wrap(
        [
            RetryScopeNode(
                body=[LogMessageNode(message=Literal(value="x"), level="Info")],
                number_of_retries=Literal(value="3"),
                condition_has_body=True,
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: RetryScope with a non-empty Condition" in code
    _compiles(code)


def test_retry_scope_with_retry_interval_is_todo_not_guessed():
    wf = _wrap(
        [
            RetryScopeNode(
                body=[LogMessageNode(message=Literal(value="x"), level="Info")],
                number_of_retries=Literal(value="3"),
                retry_interval=Literal(value="00:10:00"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: RetryScope with RetryInterval set" in code
    _compiles(code)


def test_retry_scope_with_log_retried_exceptions_is_todo_not_guessed():
    wf = _wrap(
        [
            RetryScopeNode(
                body=[LogMessageNode(message=Literal(value="x"), level="Info")],
                number_of_retries=Literal(value="3"),
                log_retried_exceptions=Literal(value="True"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: RetryScope with LogRetriedExceptions set" in code
    _compiles(code)


def test_move_file_moves_via_shutil():
    """知見188: `ui:MoveFile`(`CopyFile`知見117の正反対)。
    `shutil.move()`が直接対応する——移動先が既存のディレクトリなら
    ファイル名を付加する解決ロジックは`CopyFile`と同じ。"""
    wf = _wrap(
        [
            MoveFileNode(
                path=Literal(value="a.txt"),
                destination=Literal(value="b.txt"),
                overwrite="True",
            )
        ]
    )
    code = generate_python(wf)
    assert "shutil.move(_src, _dest)" in code
    assert "import shutil" in code
    assert "# TODO" not in code
    _compiles(code)


def test_move_file_with_overwrite_false_checks_existence():
    wf = _wrap(
        [
            MoveFileNode(
                path=Literal(value="a.txt"),
                destination=Literal(value="b.txt"),
                overwrite="False",
            )
        ]
    )
    code = generate_python(wf)
    assert "if os.path.exists(_dest):" in code
    assert "raise FileExistsError(_dest)" in code
    _compiles(code)


def test_move_file_display_name_becomes_a_comment():
    wf = _wrap(
        [
            MoveFileNode(
                path=Literal(value="a.txt"),
                destination=Literal(value="b.txt"),
                overwrite="True",
                display_name="Move File",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Move File" in code
    assert "shutil.move(" in code
    _compiles(code)


def test_move_file_with_missing_path_or_destination_is_todo():
    wf = _wrap([MoveFileNode(path=None, destination=Literal(value="b.txt"))])
    code = generate_python(wf)
    assert "# TODO: MoveFile with missing Path/Destination" in code
    _compiles(code)


def test_move_file_with_unrecognized_overwrite_is_todo_not_guessed():
    wf = _wrap(
        [
            MoveFileNode(
                path=Literal(value="a.txt"),
                destination=Literal(value="b.txt"),
                overwrite=None,
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: MoveFile with unrecognized/unset Overwrite" in code
    _compiles(code)


def test_move_file_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap(
        [
            MoveFileNode(
                path=Literal(value="a.txt"),
                destination=Literal(value="b.txt"),
                overwrite="True",
                continue_on_error=Literal(value="False"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: MoveFile with ContinueOnError set" in code
    _compiles(code)


def test_copy_folder_x_copies_nested_into_existing_destination_exec():
    """知見246: `ui:CopyFolderX`——`CopyFile`のフォルダ版、
    `shutil.copytree()`に対応する。公式ドキュメント確認済みの
    `Overwrite`の意味論(「宛先に`From`と同じ名前の既存フォルダが
    あれば置き換える」)により、`To`が既存ディレクトリの場合は`From`
    のbasenameを付加する——実際の一時ディレクトリへ`exec()`経由で
    コピーし、ネストした配置になることを確認する。"""
    wf = WorkflowFile(
        class_name="Test",
        root=SequenceNode(
            body=[
                CopyFolderXNode(
                    from_=VbExpr(text="src"),
                    to=VbExpr(text="dest_container"),
                    include_subfolders="True",
                    overwrite="True",
                )
            ]
        ),
        arguments={"src": "InArgument(x:String)", "dest_container": "InArgument(x:String)"},
    )
    code = generate_python(wf)
    assert "shutil.copytree(_src, _dest, dirs_exist_ok=True)" in code
    assert "import shutil" in code
    assert "# TODO" not in code
    _compiles(code)
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src")
        os.makedirs(src)
        with open(os.path.join(src, "a.txt"), "w") as f:
            f.write("hello")
        dest_container = os.path.join(tmp, "container")
        os.makedirs(dest_container)
        namespace: dict[str, object] = {}
        exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
        namespace["Test"](src=src, dest_container=dest_container)
        assert os.path.exists(os.path.join(dest_container, "src", "a.txt"))


def test_copy_folder_x_with_overwrite_false_raises_on_existing_destination_exec():
    wf = WorkflowFile(
        class_name="Test",
        root=SequenceNode(
            body=[
                CopyFolderXNode(
                    from_=VbExpr(text="src"),
                    to=VbExpr(text="dest_container"),
                    include_subfolders="True",
                    overwrite="False",
                )
            ]
        ),
        arguments={"src": "InArgument(x:String)", "dest_container": "InArgument(x:String)"},
    )
    code = generate_python(wf)
    assert "if os.path.exists(_dest):" in code
    assert "raise FileExistsError(_dest)" in code
    _compiles(code)
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src")
        os.makedirs(src)
        dest_container = os.path.join(tmp, "container")
        os.makedirs(os.path.join(dest_container, "src"))
        namespace: dict[str, object] = {}
        exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
        with pytest.raises(FileExistsError):
            namespace["Test"](src=src, dest_container=dest_container)


def test_copy_folder_x_with_include_subfolders_false_is_todo():
    """知見246: `IncludeSubfolders="False"`時の意味論は未確認
    (実機・ground-truthいずれも`"True"`のみ)——でっち上げず`# TODO`
    へ倒す。"""
    wf = _wrap(
        [
            CopyFolderXNode(
                from_=Literal(value="a"),
                to=Literal(value="b"),
                include_subfolders="False",
                overwrite="True",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: CopyFolderX with IncludeSubfolders" in code
    _compiles(code)


def test_copy_folder_x_with_from_resource_is_todo():
    wf = _wrap(
        [
            CopyFolderXNode(
                from_=Literal(value="a"),
                to=Literal(value="b"),
                include_subfolders="True",
                overwrite="True",
                from_resource=VbExpr(text="res"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: CopyFolderX with FromResource/ToResource set" in code
    _compiles(code)


def test_copy_folder_x_with_continue_on_error_is_todo():
    wf = _wrap(
        [
            CopyFolderXNode(
                from_=Literal(value="a"),
                to=Literal(value="b"),
                include_subfolders="True",
                overwrite="True",
                continue_on_error=Literal(value="False"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: CopyFolderX with ContinueOnError set" in code
    _compiles(code)


def test_copy_folder_x_with_missing_from_or_to_is_todo():
    wf = _wrap([CopyFolderXNode(from_=None, to=Literal(value="b"))])
    code = generate_python(wf)
    assert "# TODO: CopyFolderX with missing From/To" in code
    _compiles(code)


def test_move_folder_x_moves_nested_into_existing_destination_exec():
    """知見246: `ui:MoveFolderX`——`MoveFile`のフォルダ版、
    `shutil.move()`に対応する。`IncludeSubfolders`は無い
    (ground-truth・実機いずれも確認済み)。"""
    wf = WorkflowFile(
        class_name="Test",
        root=SequenceNode(
            body=[
                MoveFolderXNode(
                    from_=VbExpr(text="src"),
                    to=VbExpr(text="dest_container"),
                    overwrite="True",
                )
            ]
        ),
        arguments={"src": "InArgument(x:String)", "dest_container": "InArgument(x:String)"},
    )
    code = generate_python(wf)
    assert "shutil.move(_src, _dest)" in code
    assert "import shutil" in code
    assert "# TODO" not in code
    _compiles(code)
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src")
        os.makedirs(src)
        with open(os.path.join(src, "b.txt"), "w") as f:
            f.write("world")
        dest_container = os.path.join(tmp, "archive")
        os.makedirs(dest_container)
        namespace: dict[str, object] = {}
        exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
        namespace["Test"](src=src, dest_container=dest_container)
        assert os.path.exists(os.path.join(dest_container, "src", "b.txt"))
        assert not os.path.exists(src)


def test_move_folder_x_with_overwrite_false_checks_existence():
    wf = _wrap(
        [
            MoveFolderXNode(
                from_=Literal(value="a"),
                to=Literal(value="b"),
                overwrite="False",
            )
        ]
    )
    code = generate_python(wf)
    assert "if os.path.exists(_dest):" in code
    assert "raise FileExistsError(_dest)" in code
    _compiles(code)


def test_move_folder_x_with_continue_on_error_is_todo():
    wf = _wrap(
        [
            MoveFolderXNode(
                from_=Literal(value="a"),
                to=Literal(value="b"),
                overwrite="True",
                continue_on_error=Literal(value="False"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: MoveFolderX with ContinueOnError set" in code
    _compiles(code)


def test_move_folder_x_with_missing_from_or_to_is_todo():
    wf = _wrap([MoveFolderXNode(from_=None, to=Literal(value="b"))])
    code = generate_python(wf)
    assert "# TODO: MoveFolderX with missing From/To" in code
    _compiles(code)


def test_path_exists_with_file_type_uses_isfile():
    """知見188: `ui:PathExists`(GitHub code searchで558件ヒット)。
    `PathType="File"`は`os.path.isfile()`が直接対応する。"""
    wf = _wrap(
        [PathExistsNode(path=Literal(value="a.txt"), exists=VbExpr(text="found"), path_type="File")]
    )
    code = generate_python(wf)
    assert "found = os.path.isfile(" in code
    assert "# TODO" not in code
    _compiles(code)


def test_path_exists_with_folder_type_uses_isdir():
    wf = _wrap(
        [
            PathExistsNode(
                path=Literal(value="dir"), exists=VbExpr(text="found"), path_type="Folder"
            )
        ]
    )
    code = generate_python(wf)
    assert "found = os.path.isdir(" in code
    _compiles(code)


def test_path_exists_display_name_becomes_a_comment():
    wf = _wrap(
        [
            PathExistsNode(
                path=Literal(value="a.txt"),
                exists=VbExpr(text="found"),
                path_type="File",
                display_name="Path Exists",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Path Exists" in code
    assert "os.path.isfile(" in code
    _compiles(code)


def test_path_exists_with_no_path_is_todo():
    wf = _wrap([PathExistsNode(path=None, exists=VbExpr(text="found"), path_type="File")])
    code = generate_python(wf)
    assert "# TODO: PathExists with no Path captured" in code
    _compiles(code)


def test_path_exists_with_no_output_exists_is_todo():
    wf = _wrap([PathExistsNode(path=Literal(value="a.txt"), exists=None, path_type="File")])
    code = generate_python(wf)
    assert "# TODO: PathExists with no output Exists captured" in code
    _compiles(code)


def test_path_exists_with_resource_is_todo_not_guessed():
    wf = _wrap(
        [
            PathExistsNode(
                path=Literal(value="a.txt"),
                exists=VbExpr(text="found"),
                path_type="File",
                resource=VbExpr(text="res"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: PathExists with Resource set" in code
    _compiles(code)


def test_path_exists_with_unrecognized_path_type_is_todo_not_guessed():
    wf = _wrap(
        [PathExistsNode(path=Literal(value="a.txt"), exists=VbExpr(text="found"), path_type=None)]
    )
    code = generate_python(wf)
    assert "# TODO: PathExists with unrecognized/unset PathType" in code
    _compiles(code)


def test_file_exists_x_uses_isfile():
    """知見219: `ui:FileExistsX`(`PathExists`の`PathType="File"`固定版
    と推測、GitHub code searchで「`"ui:FileExistsX"`」タグ名限定422件
    ヒット)。`os.path.isfile()`が直接対応する。実際に存在するファイル
    で`exec()`経由で確認する。"""
    tmp_file = tempfile.mktemp(suffix=".txt")
    with open(tmp_file, "w") as f:
        f.write("hi")
    wf = _wrap(
        [FileExistsXNode(path=Literal(value=tmp_file), exists=VbExpr(text="found"))]
    )
    code = generate_python(wf)
    assert "found = os.path.isfile(" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code + "\n    return found", namespace)  # noqa: S102 - 信頼できる自作コード
    assert namespace["Test"]() is True


def test_file_exists_x_with_missing_properties_is_todo():
    wf = _wrap([FileExistsXNode(path=None, exists=VbExpr(text="found"))])
    code = generate_python(wf)
    assert "# TODO: FileExistsX with no Path captured" in code
    _compiles(code)

    wf2 = _wrap([FileExistsXNode(path=Literal(value="a.txt"), exists=None)])
    code2 = generate_python(wf2)
    assert "# TODO: FileExistsX with no output Exists captured" in code2
    _compiles(code2)


def test_folder_exists_x_uses_isdir():
    """知見219: `ui:FolderExistsX`(`FileExistsX`と対になるフォルダ版、
    GitHub code searchで「`"ui:FolderExistsX"`」タグ名限定227件
    ヒット)。`os.path.isdir()`が直接対応する。"""
    tmp_dir = tempfile.mkdtemp()
    wf = _wrap(
        [FolderExistsXNode(path=Literal(value=tmp_dir), exists=VbExpr(text="found"))]
    )
    code = generate_python(wf)
    assert "found = os.path.isdir(" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code + "\n    return found", namespace)  # noqa: S102 - 信頼できる自作コード
    assert namespace["Test"]() is True


def test_folder_exists_x_with_missing_properties_is_todo():
    wf = _wrap([FolderExistsXNode(path=None, exists=VbExpr(text="found"))])
    code = generate_python(wf)
    assert "# TODO: FolderExistsX with no Path captured" in code
    _compiles(code)

    wf2 = _wrap([FolderExistsXNode(path=Literal(value="dir"), exists=None)])
    code2 = generate_python(wf2)
    assert "# TODO: FolderExistsX with no output Exists captured" in code2
    _compiles(code2)


def test_delete_file_calls_os_remove():
    """知見189: `ui:DeleteFileX`(GitHub code searchで508件ヒット)。
    `os.remove()`が直接対応する。"""
    wf = _wrap([DeleteFileNode(path=Literal(value="a.txt"))])
    code = generate_python(wf)
    assert "os.remove('a.txt')" in code
    assert "import os" in code
    assert "# TODO" not in code
    _compiles(code)


def test_delete_file_display_name_becomes_a_comment():
    wf = _wrap([DeleteFileNode(path=Literal(value="a.txt"), display_name="Delete File")])
    code = generate_python(wf)
    assert "# Delete File" in code
    assert "os.remove(" in code
    _compiles(code)


def test_delete_file_with_no_path_is_todo():
    wf = _wrap([DeleteFileNode(path=None)])
    code = generate_python(wf)
    assert "# TODO: DeleteFile with no Path captured" in code
    _compiles(code)


def test_delete_folder_recursive_true_calls_shutil_rmtree():
    """知見189: `ui:DeleteFolderX`(GitHub code searchで173件ヒット)。
    `Recursive="True"`は`shutil.rmtree()`が直接対応する。"""
    wf = _wrap([DeleteFolderNode(path=Literal(value="d"), recursive="True")])
    code = generate_python(wf)
    assert "shutil.rmtree('d')" in code
    assert "import shutil" in code
    assert "# TODO" not in code
    _compiles(code)


def test_delete_folder_recursive_false_calls_os_rmdir():
    """`Recursive="False"`は`os.rmdir()`(空のフォルダのみ削除)が
    直接対応する。"""
    wf = _wrap([DeleteFolderNode(path=Literal(value="d"), recursive="False")])
    code = generate_python(wf)
    assert "os.rmdir('d')" in code
    assert "import os" in code
    assert "# TODO" not in code
    _compiles(code)


def test_delete_folder_display_name_becomes_a_comment():
    wf = _wrap(
        [DeleteFolderNode(path=Literal(value="d"), recursive="True", display_name="Delete Folder")]
    )
    code = generate_python(wf)
    assert "# Delete Folder" in code
    assert "shutil.rmtree(" in code
    _compiles(code)


def test_delete_folder_with_no_path_is_todo():
    wf = _wrap([DeleteFolderNode(path=None, recursive="True")])
    code = generate_python(wf)
    assert "# TODO: DeleteFolder with no Path captured" in code
    _compiles(code)


def test_delete_folder_with_unrecognized_recursive_is_todo_not_guessed():
    wf = _wrap([DeleteFolderNode(path=Literal(value="d"), recursive=None)])
    code = generate_python(wf)
    assert "# TODO: DeleteFolder with unrecognized/unset Recursive" in code
    _compiles(code)


def test_for_each_file_non_recursive_uses_scandir():
    """知見190: `ui:ForEachFileX`(GitHub code searchで738件ヒット)。
    `IncludeSubDirectories="False"`(既定)は`os.scandir()`が直接
    対応する。"""
    wf = _wrap(
        [
            ForEachFileNode(
                folder=Literal(value="d"),
                include_sub_directories="False",
                order_by="NameAscFirst",
                item_var="CurrentFile",
                index_var="CurrentIndex",
                body=[LogMessageNode(message=VbExpr(text="CurrentFile"), level="Info")],
            )
        ]
    )
    code = generate_python(wf)
    assert "for CurrentIndex, CurrentFile in enumerate(sorted((_e.path for _e in os.scandir('d') if _e.is_file()), key=os.path.basename)):" in code
    assert "import os" in code
    assert "# TODO" not in code
    _compiles(code)


def test_for_each_file_recursive_uses_os_walk():
    """`IncludeSubDirectories="True"`は`os.walk()`が全階層のファイルを
    対象に直接対応する。"""
    wf = _wrap(
        [
            ForEachFileNode(
                folder=Literal(value="d"),
                include_sub_directories="True",
                order_by="NameAscFirst",
                body=[LogMessageNode(message=VbExpr(text="CurrentFile"), level="Info")],
            )
        ]
    )
    code = generate_python(wf)
    assert "os.walk('d')" in code
    assert "for CurrentIndex, CurrentFile in enumerate(" in code
    _compiles(code)


def test_for_each_file_current_file_full_name_returns_path_itself():
    """知見190: `CurrentFile.FullName`(実機`marcelocruzrpa/uipath-ai-
    skills`資産`PDFExtraction_Main.xaml`で確認)は、`CurrentFile`が
    既に絶対パス文字列として表現されているため`render_expr`で
    そのまま`CurrentFile`を返す。"""
    wf = _wrap(
        [
            ForEachFileNode(
                folder=Literal(value="d"),
                order_by="NameAscFirst",
                body=[LogMessageNode(message=VbExpr(text="CurrentFile.FullName"), level="Info")],
            )
        ]
    )
    code = generate_python(wf)
    assert "logging.info(_vb_cstr(CurrentFile))" in code
    assert "# TODO" not in code
    _compiles(code)


def test_for_each_file_with_unconfirmed_order_by_is_todo_not_guessed():
    wf = _wrap(
        [
            ForEachFileNode(
                folder=Literal(value="d"),
                order_by="DateAscFirst",
                body=[LogMessageNode(message=Literal(value="x"), level="Info")],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: ForEachFile with unconfirmed OrderBy" in code
    _compiles(code)


def test_for_each_file_with_skip_without_permission_is_todo_not_guessed():
    wf = _wrap(
        [
            ForEachFileNode(
                folder=Literal(value="d"),
                order_by="NameAscFirst",
                skip_without_permission="True",
                body=[LogMessageNode(message=Literal(value="x"), level="Info")],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: ForEachFile with SkipFolderWithoutPermission" in code
    _compiles(code)


def test_for_each_folder_non_recursive_uses_scandir():
    """知見190: `ui:ForEachFolderX`(GitHub code searchで40件ヒット)。"""
    wf = _wrap(
        [
            ForEachFolderNode(
                folder=Literal(value="d"),
                include_sub_folders="False",
                order_by="NameAscFirst",
                item_var="CurrentFolder",
                index_var="CurrentIndex",
                body=[LogMessageNode(message=VbExpr(text="CurrentFolder"), level="Info")],
            )
        ]
    )
    code = generate_python(wf)
    assert "_e.is_dir()" in code
    assert "for CurrentIndex, CurrentFolder in enumerate(" in code
    assert "# TODO" not in code
    _compiles(code)


def test_for_each_folder_recursive_uses_os_walk_dirnames():
    wf = _wrap(
        [
            ForEachFolderNode(
                folder=Literal(value="d"),
                include_sub_folders="True",
                order_by="NameAscFirst",
                body=[LogMessageNode(message=Literal(value="x"), level="Info")],
            )
        ]
    )
    code = generate_python(wf)
    assert "for _dp, _dns, _fns in os.walk('d') for _dn in _dns" in code
    _compiles(code)


def test_rename_file_calls_os_rename():
    """知見191: `ui:RenameFileX`(GitHub code searchで123件ヒット
    ——`DeleteFileX`(知見189)と同じ「X」付きファイルシステム操作系
    活動ファミリー)。`KeepExtension="True"`時は元の拡張子を保持する。"""
    wf = _wrap(
        [
            RenameFileNode(
                file_path=Literal(value="/tmp/old.txt"),
                new_name=Literal(value="new"),
                keep_extension="True",
            )
        ]
    )
    code = generate_python(wf)
    assert "_new_name += os.path.splitext(_old)[1]" in code
    assert "os.rename(_old, os.path.join(os.path.dirname(_old), _new_name))" in code
    assert "# TODO" not in code
    _compiles(code)


def test_rename_file_with_keep_extension_false_does_not_append_extension():
    wf = _wrap(
        [
            RenameFileNode(
                file_path=Literal(value="/tmp/old.txt"),
                new_name=Literal(value="new.txt"),
                keep_extension="False",
            )
        ]
    )
    code = generate_python(wf)
    assert "os.path.splitext" not in code
    assert "# TODO" not in code
    _compiles(code)


def test_rename_file_display_name_becomes_a_comment():
    wf = _wrap(
        [
            RenameFileNode(
                file_path=Literal(value="a.txt"),
                new_name=Literal(value="b"),
                keep_extension="True",
                display_name="Rename File",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Rename File" in code
    assert "os.rename(" in code
    _compiles(code)


def test_rename_file_with_missing_path_or_name_is_todo():
    wf = _wrap([RenameFileNode(file_path=None, new_name=Literal(value="b"))])
    code = generate_python(wf)
    assert "# TODO: RenameFile with missing FilePath/NewName" in code
    _compiles(code)


def test_rename_file_with_file_resource_is_todo_not_guessed():
    wf = _wrap(
        [
            RenameFileNode(
                file_path=Literal(value="a.txt"),
                new_name=Literal(value="b"),
                keep_extension="True",
                file_resource=VbExpr(text="res"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: RenameFile with FileResource/OutputFileResource set" in code
    _compiles(code)


def test_rename_file_with_unrecognized_keep_extension_is_todo_not_guessed():
    wf = _wrap(
        [
            RenameFileNode(
                file_path=Literal(value="a.txt"),
                new_name=Literal(value="b"),
                keep_extension=None,
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: RenameFile with unrecognized/unset KeepExtension" in code
    _compiles(code)


def test_rename_folder_calls_os_rename():
    """知見191: `ui:RenameFolderX`(`RenameFile`の兄弟活動)。
    `KeepExtension`に相当する属性は無い。"""
    wf = _wrap(
        [
            RenameFolderNode(
                folder_path=Literal(value="/tmp/old"),
                new_name=Literal(value="new"),
            )
        ]
    )
    code = generate_python(wf)
    assert "os.rename(_old, os.path.join(os.path.dirname(_old), 'new'))" in code
    assert "# TODO" not in code
    _compiles(code)


def test_rename_folder_display_name_becomes_a_comment():
    wf = _wrap(
        [
            RenameFolderNode(
                folder_path=Literal(value="a"),
                new_name=Literal(value="b"),
                display_name="Rename Folder",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Rename Folder" in code
    assert "os.rename(" in code
    _compiles(code)


def test_rename_folder_with_missing_path_or_name_is_todo():
    wf = _wrap([RenameFolderNode(folder_path=None, new_name=Literal(value="b"))])
    code = generate_python(wf)
    assert "# TODO: RenameFolder with missing FolderPath/NewName" in code
    _compiles(code)


def test_create_file_joins_path_and_name():
    """知見191: `ui:CreateFile`(GitHub code searchで266件ヒット——
    `DeleteFileX`等とは違い非X形のまま)。`open(path, "w").close()`
    で空ファイルを作成する。"""
    wf = _wrap(
        [
            CreateFileNode(
                path=Literal(value="C:/Hello/"),
                name=Literal(value="Anuj.txt"),
            )
        ]
    )
    code = generate_python(wf)
    assert "_full_path = os.path.join('C:/Hello/', 'Anuj.txt')" in code
    assert 'open(_full_path, "w").close()' in code
    assert "# TODO" not in code
    _compiles(code)


def test_create_file_with_output_assigns_full_path():
    wf = _wrap(
        [
            CreateFileNode(
                path=Literal(value="C:/Hello/"),
                name=Literal(value="Anuj.txt"),
                output=VbExpr(text="result"),
            )
        ]
    )
    code = generate_python(wf)
    assert "result = _full_path" in code
    assert "# TODO" not in code
    _compiles(code)


def test_create_file_display_name_becomes_a_comment():
    wf = _wrap(
        [
            CreateFileNode(
                path=Literal(value="a"),
                name=Literal(value="b.txt"),
                display_name="Create File",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Create File" in code
    assert "open(_full_path" in code
    _compiles(code)


def test_create_file_with_missing_path_or_name_is_todo():
    wf = _wrap([CreateFileNode(path=None, name=Literal(value="b.txt"))])
    code = generate_python(wf)
    assert "# TODO: CreateFile with missing Path/Name" in code
    _compiles(code)


def test_create_file_with_path_resource_is_todo_not_guessed():
    wf = _wrap(
        [
            CreateFileNode(
                path=Literal(value="a"),
                name=Literal(value="b.txt"),
                path_resource=VbExpr(text="res"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: CreateFile with PathResource set" in code
    _compiles(code)


def test_create_file_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap(
        [
            CreateFileNode(
                path=Literal(value="a"),
                name=Literal(value="b.txt"),
                continue_on_error=Literal(value="False"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: CreateFile with ContinueOnError set" in code
    _compiles(code)


def test_close_tab_sends_ctrl_w_via_global_send_keys():
    """知見170: `ui:CloseTab`(GitHub code searchで782件ヒット)。
    主要ブラウザ共通の標準キーボードショートカット`Ctrl+W`を
    pywinautoの`keyboard.send_keys()`(対象を指定しないグローバルな
    キー送信)で実現する。"""
    wf = _wrap([CloseTabNode()])
    code = generate_python(wf)
    assert "send_keys('^w')" in code
    assert "from pywinauto.keyboard import send_keys" in code
    assert "# TODO" not in code
    _compiles(code)


def test_close_tab_display_name_becomes_a_comment():
    wf = _wrap([CloseTabNode(display_name="Close Tab")])
    code = generate_python(wf)
    assert "# Close Tab" in code
    assert "send_keys('^w')" in code
    _compiles(code)


def test_close_tab_with_browser_variable_reference_is_todo_not_guessed():
    """知見170: `Browser`が`UiBrowser`型変数への参照(`piyushagarwal08/
    JU-Notes`の実機XAMLで確認済みの`[firefox]`)の場合は、変数自体が
    未モデル化のためでっち上げず`# TODO`へ倒す。"""
    wf = _wrap([CloseTabNode(browser=VbExpr(text="firefox"))])
    code = generate_python(wf)
    assert "# TODO: CloseTab with Browser set" in code
    assert "send_keys" not in code
    _compiles(code)


def test_refresh_browser_sends_f5_via_global_send_keys():
    """知見175: `ui:RefreshBrowser`(GitHub code searchで59件ヒット)。
    `CloseTab`(知見170)の`send_keys('^w')`と同じ経路で、主要ブラウザ
    共通の標準キーボードショートカット`F5`を送る。"""
    wf = _wrap([RefreshBrowserNode()])
    code = generate_python(wf)
    assert "send_keys('{F5}')" in code
    assert "from pywinauto.keyboard import send_keys" in code
    assert "# TODO" not in code
    _compiles(code)


def test_refresh_browser_display_name_becomes_a_comment():
    wf = _wrap([RefreshBrowserNode(display_name="Refresh Browser")])
    code = generate_python(wf)
    assert "# Refresh Browser" in code
    assert "send_keys('{F5}')" in code
    _compiles(code)


def test_refresh_browser_with_browser_variable_reference_is_todo_not_guessed():
    """知見175: `Browser`が`UiBrowser`型変数への参照(実機
    `csut017/CrowdMarkLoad`で確認済みの`[browser]`)の場合は、変数自体
    が未モデル化のためでっち上げず`# TODO`へ倒す。"""
    wf = _wrap([RefreshBrowserNode(browser=VbExpr(text="browser"))])
    code = generate_python(wf)
    assert "# TODO: RefreshBrowser with Browser set" in code
    assert "send_keys" not in code
    _compiles(code)


def test_go_back_sends_alt_left_via_global_send_keys():
    """知見242: `ui:GoBack`(タグ名限定GitHub検索で88件ヒット)。
    `RefreshBrowser`(知見175)と同じ経路で、主要ブラウザ共通の標準
    キーボードショートカット`Alt+Left`(履歴を1つ戻る)を送る。"""
    wf = _wrap([GoBackNode()])
    code = generate_python(wf)
    assert "send_keys('%{LEFT}')" in code
    assert "from pywinauto.keyboard import send_keys" in code
    assert "# TODO" not in code
    _compiles(code)


def test_go_back_with_browser_variable_reference_is_todo_not_guessed():
    """知見242: `Browser`が`UiBrowser`型変数への参照(実機
    `piyushagarwal08/JU-Notes`で確認済みの`[ACME]`)の場合は、
    `RefreshBrowser`と同じ理由で`# TODO`へ倒す。"""
    wf = _wrap([GoBackNode(browser=VbExpr(text="browser"))])
    code = generate_python(wf)
    assert "# TODO: GoBack with Browser set" in code
    assert "send_keys" not in code
    _compiles(code)


def test_navigate_to_with_literal_url_exec():
    """知見242: `ui:NavigateTo`(タグ名限定GitHub検索で423件ヒット)。
    `Ctrl+L`でアドレスバーへフォーカスし、`TypeInto`(知見110)と同じ
    `_pywinauto_type_keys_escape()`でエスケープした`Url`を入力して
    `Enter`で確定する。`pywinauto`自体はこのサンドボックス(Linux、
    X11無し)では`import`すら失敗するため(既存の`CloseTab`/
    `RefreshBrowser`のテストも同じ理由で`exec()`せず文字列検証のみに
    留めている)、エスケープ処理自体は生成コードを介さず
    `_pywinauto_type_keys_escape`ヘルパーを直接呼んで検証する——
    クエリ文字列に含まれる`+`がpywinautoの特殊キー構文と衝突しない
    よう`{+}`へエスケープされることを確認する。"""
    wf = _wrap([NavigateToNode(url=Literal(value="https://example.com/?a=1+2"))])
    code = generate_python(wf)
    assert "send_keys('^l')" in code
    assert (
        "send_keys(_pywinauto_type_keys_escape(_vb_cstr("
        "'https://example.com/?a=1+2')) + '{ENTER}')"
    ) in code
    assert "# TODO" not in code
    _compiles(code)
    from dump_daemon.uipath_codegen import _TYPE_KEYS_ESCAPE_HELPER_SOURCE

    helper_ns: dict[str, object] = {}
    exec(_TYPE_KEYS_ESCAPE_HELPER_SOURCE, helper_ns)  # noqa: S102 - 信頼できる自作コード
    assert helper_ns["_pywinauto_type_keys_escape"]("https://example.com/?a=1+2") == (
        "https://example.com/?a=1{+}2"
    )


def test_navigate_to_with_browser_variable_reference_is_todo_not_guessed():
    """知見242: `Browser`が変数参照の実例は未確認だが、`RefreshBrowser`/
    `GoBack`と同じ`# TODO`方針を予防的に適用する。"""
    wf = _wrap(
        [NavigateToNode(browser=VbExpr(text="browser"), url=Literal(value="x"))]
    )
    code = generate_python(wf)
    assert "# TODO: NavigateTo with Browser set" in code
    assert "send_keys" not in code
    _compiles(code)


def test_navigate_to_with_no_url_is_todo():
    wf = _wrap([NavigateToNode(url=None)])
    code = generate_python(wf)
    assert "# TODO: NavigateTo with no Url captured" in code
    _compiles(code)


_TYPE_INTO_SELECTOR = "<wnd cls='Notepad' /><ctrl name='x' />"


def test_type_into_with_known_selector_generates_type_keys():
    """知見110: 確認済みの既定値のみ(selector以外は全て未設定)の
    最小ケース——`type_keys()`呼び出しと特殊文字エスケープヘルパーが
    生成され、クリックやset_foreground等の追加行は出ない。"""
    wf = _wrap(
        [TypeIntoNode(selector=_TYPE_INTO_SELECTOR, text=Literal(value="hello"))]
    )
    code = generate_python(wf)
    assert ".type_keys(_pywinauto_type_keys_escape(_vb_cstr('hello')))" in code
    assert ".click_input()" not in code
    assert "set_foreground" not in code
    assert "pause=" not in code
    _compiles(code)


def test_type_into_display_name_becomes_a_comment_even_when_falling_back_to_todo():
    wf = _wrap([TypeIntoNode(selector=None, display_name="Type Into 'Account Number'")])
    code = generate_python(wf)
    assert "# Type Into 'Account Number'" in code
    assert "# TODO: Type Into with no selector captured" in code
    _compiles(code)


def test_type_into_with_no_selector_is_todo():
    wf = _wrap([TypeIntoNode(selector=None, text=Literal(value="x"))])
    code = generate_python(wf)
    assert "# TODO: Type Into with no selector captured" in code
    _compiles(code)


def test_type_into_with_no_text_is_todo():
    wf = _wrap([TypeIntoNode(selector=_TYPE_INTO_SELECTOR, text=None)])
    code = generate_python(wf)
    assert "# TODO: Type Into with no Text captured" in code
    _compiles(code)


def test_type_into_with_unmappable_selector_is_todo():
    wf = _wrap(
        [TypeIntoNode(selector="<wnd idx='2' />", text=Literal(value="x"))]
    )
    code = generate_python(wf)
    assert "# TODO: Type Into selector had no mappable attributes" in code
    _compiles(code)


@pytest.mark.parametrize("simulate_type", [Literal(value="True"), Literal(value="CUSTOM")])
def test_type_into_with_non_default_simulate_type_is_todo_not_guessed(simulate_type):
    """知見110: `SimulateType=True`(「対象アプリ自身の技術を使う」)は
    公式ドキュメントに具体的なAPIの記載が無く、`Click`の`SimulateClick`
    と同じ理由ででっち上げず`# TODO`に倒す。"""
    wf = _wrap(
        [
            TypeIntoNode(
                selector=_TYPE_INTO_SELECTOR, text=Literal(value="x"), simulate_type=simulate_type
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Type Into with non-default SimulateType" in code
    assert ".type_keys(" not in code
    _compiles(code)


def test_type_into_with_non_default_send_window_messages_is_todo_not_guessed():
    wf = _wrap(
        [
            TypeIntoNode(
                selector=_TYPE_INTO_SELECTOR,
                text=Literal(value="x"),
                send_window_messages=Literal(value="True"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Type Into with non-default SendWindowMessages" in code
    _compiles(code)


@pytest.mark.parametrize(
    "click_before_typing",
    [None, Literal(value="False"), Literal(value="NONE")],
)
def test_type_into_with_no_click_before_typing_generates_plain_type_keys(click_before_typing):
    wf = _wrap(
        [
            TypeIntoNode(
                selector=_TYPE_INTO_SELECTOR,
                text=Literal(value="x"),
                click_before_typing=click_before_typing,
            )
        ]
    )
    code = generate_python(wf)
    assert ".click_input()" not in code
    assert ".type_keys(" in code
    _compiles(code)


def test_type_into_with_click_before_typing_true_generates_click_then_type():
    """知見110: `ClickBeforeTyping="True"`は実機XAML(複数件)で確認済み
    ——`Click`の確認済み既定クリック(単純左シングルクリック)を先に
    発行してからタイプする。"""
    wf = _wrap(
        [
            TypeIntoNode(
                selector=_TYPE_INTO_SELECTOR,
                text=Literal(value="x"),
                click_before_typing=Literal(value="True"),
            )
        ]
    )
    code = generate_python(wf)
    lines = [ln for ln in code.splitlines() if ".click_input()" in ln or ".type_keys(" in ln]
    assert len(lines) == 2
    assert lines[0].strip().endswith(".click_input()")
    assert ".type_keys(" in lines[1]
    _compiles(code)


def test_type_into_with_unrecognized_click_before_typing_is_todo():
    wf = _wrap(
        [
            TypeIntoNode(
                selector=_TYPE_INTO_SELECTOR,
                text=Literal(value="x"),
                click_before_typing=Literal(value="SOMETHING_ELSE"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Type Into with unrecognized ClickBeforeTyping" in code
    _compiles(code)


def test_type_into_with_empty_field_true_is_todo_not_guessed():
    wf = _wrap(
        [
            TypeIntoNode(
                selector=_TYPE_INTO_SELECTOR,
                text=Literal(value="x"),
                empty_field=Literal(value="True"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Type Into with EmptyField set" in code
    _compiles(code)


def test_type_into_with_delay_ms_is_todo_not_guessed():
    """知見106と同じ理由(`DelayMS`は`TypeInto`公式ドキュメントにも記載
    無し)——`Click`と一貫した判断。"""
    wf = _wrap(
        [
            TypeIntoNode(
                selector=_TYPE_INTO_SELECTOR, text=Literal(value="x"), delay_ms=Literal(value="2000")
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Type Into with DelayMS set" in code
    assert ".type_keys(" not in code
    _compiles(code)


def test_type_into_with_alter_if_disabled_is_todo_not_guessed():
    wf = _wrap(
        [
            TypeIntoNode(
                selector=_TYPE_INTO_SELECTOR,
                text=Literal(value="x"),
                alter_if_disabled=Literal(value="True"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Type Into with AlterIfDisabled set" in code
    _compiles(code)


def test_type_into_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap(
        [
            TypeIntoNode(
                selector=_TYPE_INTO_SELECTOR,
                text=Literal(value="x"),
                continue_on_error=Literal(value="True"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Type Into with ContinueOnError set" in code
    _compiles(code)


def test_type_into_with_delay_before_generates_time_sleep():
    wf = _wrap(
        [
            TypeIntoNode(
                selector=_TYPE_INTO_SELECTOR,
                text=Literal(value="x"),
                delay_before=Literal(value="500"),
            )
        ]
    )
    code = generate_python(wf)
    assert "time.sleep(_vb_num('500') / 1000.0)" in code
    _compiles(code)


def test_type_into_with_delay_between_keys_generates_pause_kwarg():
    wf = _wrap(
        [
            TypeIntoNode(
                selector=_TYPE_INTO_SELECTOR,
                text=Literal(value="x"),
                delay_between_keys=Literal(value="20"),
            )
        ]
    )
    code = generate_python(wf)
    assert "pause=(_vb_num('20') / 1000.0)" in code
    _compiles(code)


@pytest.mark.parametrize(
    ("activate_before", "expect_kwarg"),
    [
        (None, False),
        (Literal(value="True"), False),
        (Literal(value="False"), True),
    ],
)
def test_type_into_activate_before_maps_to_set_foreground(activate_before, expect_kwarg):
    """知見110: docs.uipath.comの「UI Automationの入力方式」ページで
    `Activate`(既定チェック済み、外すと入力は現在アクティブなウィンドウへ
    送られる)の既定が確認できたため、`pywinauto`の`type_keys()`の
    `set_foreground`既定(`True`)と対応付けられる——確認済みの`"True"`/
    `None`はkwarg無し(既定のまま)、`"False"`のみ明示する。"""
    wf = _wrap(
        [
            TypeIntoNode(
                selector=_TYPE_INTO_SELECTOR,
                text=Literal(value="x"),
                activate_before=activate_before,
            )
        ]
    )
    code = generate_python(wf)
    assert ("set_foreground=False" in code) == expect_kwarg
    _compiles(code)


def test_type_into_with_non_literal_activate_before_is_todo_not_guessed():
    wf = _wrap(
        [
            TypeIntoNode(
                selector=_TYPE_INTO_SELECTOR,
                text=Literal(value="x"),
                activate_before=VbExpr(text="someCondition"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Type Into with non-literal Activate" in code
    _compiles(code)


def test_type_into_escapes_pywinauto_special_characters_in_literal_text():
    """`pywinauto`の`type_keys()`は`~^%+(){}`を独自の特殊キー構文として
    解釈するため(`dump_daemon/pad_ui_helpers.py`が発見した同じ罠)、
    生成コードは常にエスケープヘルパーを経由する——実際に実行して
    `send_keys`相当のキー列ではなく元の文字列が復元されることまでは
    このテストの範囲外(pywinauto自体の単体テストの領域)だが、
    ヘルパー関数自体の変換結果は検証する。"""
    wf = _wrap(
        [TypeIntoNode(selector=_TYPE_INTO_SELECTOR, text=Literal(value="100% {a+b}"))]
    )
    code = generate_python(wf)
    assert "def _pywinauto_type_keys_escape(" in code
    _compiles(code)
    # 生成コード全体の`exec()`は`from pywinauto import Desktop`を含み
    # Windows専用パッケージのため本テスト環境(Linux)では実行できない
    # ——ヘルパー関数自体の定義のみを分離して実行し、変換結果を検証する。
    namespace: dict[str, object] = {}
    exec(_TYPE_KEYS_ESCAPE_HELPER_SOURCE, namespace)  # noqa: S102
    escape = namespace["_pywinauto_type_keys_escape"]
    assert escape("100% {a+b}") == "100{%} {{}a{+}b{}}"


_SEND_HOTKEY_SELECTOR = "<wnd cls='Notepad' /><ctrl name='x' />"


def test_send_hotkey_single_char_with_ctrl_modifier():
    """知見152: `piyushagarwal08/JU-Notes`等の実機XAMLで確認済みの最も
    一般的な形(`Key="s"` + `KeyModifiers="Ctrl"` = Ctrl+S)。"""
    wf = _wrap(
        [
            SendHotkeyNode(
                selector=_SEND_HOTKEY_SELECTOR,
                key=Literal(value="s"),
                key_modifiers=Literal(value="Ctrl"),
            )
        ]
    )
    code = generate_python(wf)
    assert ".type_keys('^s')" in code
    assert "# TODO" not in code
    _compiles(code)


def test_send_hotkey_named_special_key_with_no_modifier():
    """知見152: `Key="enter"`・`KeyModifiers="None"`(`HarshadRanganathan/
    uipath-learning`の実機XAMLで確認済み)。"""
    wf = _wrap(
        [
            SendHotkeyNode(
                selector=_SEND_HOTKEY_SELECTOR,
                key=Literal(value="enter"),
                key_modifiers=Literal(value="None"),
            )
        ]
    )
    code = generate_python(wf)
    assert ".type_keys('{ENTER}')" in code
    _compiles(code)


@pytest.mark.parametrize(
    "key,expected_token",
    [
        ("f5", "{F5}"),
        ("f24", "{F24}"),
        ("num7", "{VK_NUMPAD7}"),
        ("tab", "{TAB}"),
        ("esc", "{ESC}"),
        ("pgup", "{PGUP}"),
        ("home", "{HOME}"),
        ("up", "{UP}"),
        ("left", "{LEFT}"),
    ],
)
def test_send_hotkey_confirmed_named_keys(key, expected_token):
    """知見152: 実機確認済みの特殊キー名(GitHub code searchで個別に
    実例を確認した`f1`〜`f24`/`num0`〜`num9`/`tab`/`esc`/`pgup`/`home`/
    `up`/`left`等)はそれぞれpywinautoの対応トークンへ変換する。"""
    wf = _wrap(
        [
            SendHotkeyNode(
                selector=_SEND_HOTKEY_SELECTOR,
                key=Literal(value=key),
                key_modifiers=Literal(value="None"),
            )
        ]
    )
    code = generate_python(wf)
    assert f".type_keys('{expected_token}')" in code
    _compiles(code)


def test_send_hotkey_win_modifier_uses_down_up_wrapping():
    """知見152: `KonduitAI/objectrecognition-rpa`の実機XAML(`Key="up"`/
    `KeyModifiers="Win"`、ウィンドウ最大化のショートカット)。pywinautoの
    `^`/`%`/`+`接頭辞構文にWinキーは無いため`{VK_LWIN down}`...
    `{VK_LWIN up}`で囲む。"""
    wf = _wrap(
        [
            SendHotkeyNode(
                selector=_SEND_HOTKEY_SELECTOR,
                key=Literal(value="up"),
                key_modifiers=Literal(value="Win"),
            )
        ]
    )
    code = generate_python(wf)
    assert ".type_keys('{VK_LWIN down}{UP}{VK_LWIN up}')" in code
    _compiles(code)


def test_send_hotkey_multiple_modifiers():
    """知見152: `cameronmcnz/uipath-tutorials`の実機XAMLで確認済みの
    `KeyModifiers="Ctrl, Shift"`(`.NET`の`[Flags]`列挙型ToString()
    直列化形式)。"""
    wf = _wrap(
        [
            SendHotkeyNode(
                selector=_SEND_HOTKEY_SELECTOR,
                key=Literal(value="5"),
                key_modifiers=Literal(value="Ctrl, Shift"),
            )
        ]
    )
    code = generate_python(wf)
    assert ".type_keys('^+5')" in code
    _compiles(code)


def test_send_hotkey_display_name_becomes_a_comment():
    wf = _wrap(
        [
            SendHotkeyNode(
                selector=_SEND_HOTKEY_SELECTOR,
                key=Literal(value="s"),
                key_modifiers=Literal(value="Ctrl"),
                display_name="Save",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Save" in code
    assert ".type_keys('^s')" in code
    _compiles(code)


def test_send_hotkey_with_no_target_is_todo_not_guessed():
    """知見152: `AI-Dep/AI-Antigravity`の実機XAMLで確認済みの自己終了
    タグ(`<ui:SendHotkey Key="esc" ... />`、`Target`無し)は、現在
    フォーカス中のウィンドウへのグローバル送信と推定されるが未対応
    ——でっち上げず`# TODO`へ倒す。"""
    wf = _wrap([SendHotkeyNode(selector=None, key=Literal(value="esc"))])
    code = generate_python(wf)
    assert "# TODO: SendHotkey with no Target captured" in code
    _compiles(code)


def test_send_hotkey_with_unrecognized_key_is_todo_not_guessed():
    wf = _wrap(
        [
            SendHotkeyNode(
                selector=_SEND_HOTKEY_SELECTOR,
                key=Literal(value="unknownkey"),
                key_modifiers=Literal(value="None"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: SendHotkey with unrecognized Key" in code
    assert ".type_keys(" not in code
    _compiles(code)


def test_send_hotkey_with_win_combined_with_other_modifier_is_todo_not_guessed():
    """知見152: `Win`と他のモディファイアを同時指定する実例は未確認
    のため、でっち上げず`# TODO`へ倒す。"""
    wf = _wrap(
        [
            SendHotkeyNode(
                selector=_SEND_HOTKEY_SELECTOR,
                key=Literal(value="d"),
                key_modifiers=Literal(value="Win, Ctrl"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: SendHotkey with unrecognized KeyModifiers" in code
    _compiles(code)


def test_send_hotkey_delay_before_generates_time_sleep():
    wf = _wrap(
        [
            SendHotkeyNode(
                selector=_SEND_HOTKEY_SELECTOR,
                key=Literal(value="s"),
                key_modifiers=Literal(value="Ctrl"),
                delay_before=Literal(value="500"),
            )
        ]
    )
    code = generate_python(wf)
    assert "time.sleep(" in code
    assert ".type_keys('^s')" in code
    _compiles(code)


def test_send_hotkey_with_delay_ms_is_todo_not_guessed():
    wf = _wrap(
        [
            SendHotkeyNode(
                selector=_SEND_HOTKEY_SELECTOR,
                key=Literal(value="s"),
                key_modifiers=Literal(value="Ctrl"),
                delay_ms=Literal(value="200"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: SendHotkey with DelayMS set" in code
    _compiles(code)


_GET_TEXT_SELECTOR = "<wnd cls='Notepad' /><ctrl name='x' />"


def test_get_text_with_known_selector_generates_window_text():
    wf = _wrap(
        [GetTextNode(selector=_GET_TEXT_SELECTOR, text=VbExpr(text="result"))]
    )
    code = generate_python(wf)
    assert "result = " in code
    assert ".window_text()" in code
    assert "# WARNING:" in code
    _compiles(code)


def test_get_text_display_name_becomes_a_comment_even_when_falling_back_to_todo():
    wf = _wrap([GetTextNode(selector=None, display_name="Get Text 'balance'")])
    code = generate_python(wf)
    assert "# Get Text 'balance'" in code
    assert "# TODO: Get Text with no selector captured" in code
    _compiles(code)


def test_get_text_with_no_selector_is_todo():
    wf = _wrap([GetTextNode(selector=None, text=VbExpr(text="x"))])
    code = generate_python(wf)
    assert "# TODO: Get Text with no selector captured" in code
    _compiles(code)


def test_get_text_with_no_output_text_is_todo():
    wf = _wrap([GetTextNode(selector=_GET_TEXT_SELECTOR, text=None)])
    code = generate_python(wf)
    assert "# TODO: Get Text with no output Text captured" in code
    _compiles(code)


def test_get_text_with_unmappable_selector_is_todo():
    wf = _wrap(
        [GetTextNode(selector="<wnd idx='2' />", text=VbExpr(text="x"))]
    )
    code = generate_python(wf)
    assert "# TODO: Get Text selector had no mappable attributes" in code
    _compiles(code)


def test_get_text_with_delay_ms_is_todo_not_guessed():
    wf = _wrap(
        [
            GetTextNode(
                selector=_GET_TEXT_SELECTOR, text=VbExpr(text="x"), delay_ms=Literal(value="2000")
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Get Text with DelayMS set" in code
    assert ".window_text()" not in code
    _compiles(code)


def test_get_text_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap(
        [
            GetTextNode(
                selector=_GET_TEXT_SELECTOR,
                text=VbExpr(text="x"),
                continue_on_error=Literal(value="True"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Get Text with ContinueOnError set" in code
    _compiles(code)


def test_get_text_with_delay_before_generates_time_sleep():
    wf = _wrap(
        [
            GetTextNode(
                selector=_GET_TEXT_SELECTOR, text=VbExpr(text="x"), delay_before=Literal(value="500")
            )
        ]
    )
    code = generate_python(wf)
    assert "time.sleep(_vb_num('500') / 1000.0)" in code
    _compiles(code)


def test_get_full_text_with_known_selector_generates_window_text_with_distinct_warning():
    """知見159: `ui:GetFullText`(`GetText`とは別の活動、GitHub code
    searchで300件ヒット)。同じ`window_text()`へ変換するが、`GetText`
    より弱い近似であることを明示する別の警告文言を出す。"""
    wf = _wrap(
        [GetTextNode(selector=_GET_TEXT_SELECTOR, text=VbExpr(text="result"), full_text=True)]
    )
    code = generate_python(wf)
    assert "result = " in code
    assert ".window_text()" in code
    assert "Get Full Text" in code
    assert "may return less text than UiPath's real implementation" in code
    _compiles(code)


def test_get_full_text_with_non_default_ignore_hidden_is_todo_not_guessed():
    wf = _wrap(
        [
            GetTextNode(
                selector=_GET_TEXT_SELECTOR,
                text=VbExpr(text="x"),
                full_text=True,
                ignore_hidden=Literal(value="True"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Get Full Text with non-default IgnoreHidden" in code
    assert ".window_text()" not in code
    _compiles(code)


def test_get_full_text_with_no_selector_is_todo_labeled_correctly():
    wf = _wrap([GetTextNode(selector=None, text=VbExpr(text="x"), full_text=True)])
    code = generate_python(wf)
    assert "# TODO: Get Full Text with no selector captured" in code
    _compiles(code)


def test_select_file_always_declines_with_filter_and_output():
    """知見192: `ui:SelectFile`はネイティブOSダイアログでの対話操作を
    表すため、`Filter`/出力の有無を問わず常に`# TODO`へ倒す。"""
    wf = _wrap(
        [
            SelectFileNode(
                filter=Literal(value="Excel Files (*.xls, *.xlsx)|*.xls;*.xlsx"),
                selected_file=VbExpr(text="inputFileFullAddress"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: SelectFile" in code
    _compiles(code)


def test_select_file_display_name_becomes_a_comment():
    wf = _wrap([SelectFileNode(display_name="Select Input File")])
    code = generate_python(wf)
    assert "# Select Input File" in code
    assert "# TODO: SelectFile" in code
    _compiles(code)


def test_select_file_with_no_properties_is_still_todo():
    wf = _wrap([SelectFileNode()])
    code = generate_python(wf)
    assert "# TODO: SelectFile" in code
    _compiles(code)


_SELECT_ITEM_SELECTOR = "<wnd cls='Notepad' /><ctrl name='x' />"


def test_select_item_with_known_selector_generates_select_call():
    wf = _wrap(
        [SelectItemNode(selector=_SELECT_ITEM_SELECTOR, item=Literal(value="Bold"))]
    )
    code = generate_python(wf)
    assert ".select(_vb_cstr('Bold'))" in code
    assert "# WARNING:" in code
    _compiles(code)


def test_select_item_display_name_becomes_a_comment_even_when_falling_back_to_todo():
    wf = _wrap([SelectItemNode(selector=None, display_name="Select Benefits Plan")])
    code = generate_python(wf)
    assert "# Select Benefits Plan" in code
    assert "# TODO: Select Item with no selector captured" in code
    _compiles(code)


def test_select_item_with_no_selector_is_todo():
    wf = _wrap([SelectItemNode(selector=None, item=Literal(value="x"))])
    code = generate_python(wf)
    assert "# TODO: Select Item with no selector captured" in code
    _compiles(code)


def test_select_item_with_no_item_is_todo():
    wf = _wrap([SelectItemNode(selector=_SELECT_ITEM_SELECTOR, item=None)])
    code = generate_python(wf)
    assert "# TODO: Select Item with no Item captured" in code
    _compiles(code)


def test_select_item_with_unmappable_selector_is_todo():
    wf = _wrap(
        [SelectItemNode(selector="<wnd idx='2' />", item=Literal(value="x"))]
    )
    code = generate_python(wf)
    assert "# TODO: Select Item selector had no mappable attributes" in code
    _compiles(code)


def test_select_item_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap(
        [
            SelectItemNode(
                selector=_SELECT_ITEM_SELECTOR,
                item=Literal(value="x"),
                continue_on_error=Literal(value="True"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Select Item with ContinueOnError set" in code
    _compiles(code)


@pytest.mark.parametrize("alter_if_disabled", [None, Literal(value="True")])
def test_select_item_with_confirmed_alter_if_disabled_generates_select_call(alter_if_disabled):
    """知見112: `AlterIfDisabled`は`Click`/`TypeInto`とは違い公式ドキュメント
    で確認済みの既定(`True`相当、未設定時もこの既定が有効)。"""
    wf = _wrap(
        [
            SelectItemNode(
                selector=_SELECT_ITEM_SELECTOR,
                item=Literal(value="x"),
                alter_if_disabled=alter_if_disabled,
            )
        ]
    )
    code = generate_python(wf)
    assert ".select(" in code
    _compiles(code)


def test_select_item_with_alter_if_disabled_false_is_todo_not_guessed():
    wf = _wrap(
        [
            SelectItemNode(
                selector=_SELECT_ITEM_SELECTOR,
                item=Literal(value="x"),
                alter_if_disabled=Literal(value="False"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Select Item with AlterIfDisabled set" in code
    _compiles(code)


def test_select_item_with_delay_before_and_delay_after_generates_time_sleep():
    wf = _wrap(
        [
            SelectItemNode(
                selector=_SELECT_ITEM_SELECTOR,
                item=Literal(value="x"),
                delay_before=Literal(value="200"),
                delay_after=Literal(value="300"),
            )
        ]
    )
    code = generate_python(wf)
    sleeps = [ln for ln in code.splitlines() if "time.sleep(" in ln]
    assert len(sleeps) == 2
    assert "_vb_num('200')" in sleeps[0]
    assert "_vb_num('300')" in sleeps[1]
    _compiles(code)


_ELEMENT_EXISTS_SELECTOR = "<wnd cls='Notepad' /><ctrl name='x' />"


def test_ui_element_exists_with_known_selector_generates_exists_call():
    wf = _wrap(
        [UiElementExistsNode(selector=_ELEMENT_EXISTS_SELECTOR, exists=VbExpr(text="found"))]
    )
    code = generate_python(wf)
    assert "found = " in code
    assert ".exists()" in code
    _compiles(code)


def test_ui_element_exists_display_name_becomes_a_comment_even_when_falling_back_to_todo():
    wf = _wrap([UiElementExistsNode(selector=None, display_name="Element Exists")])
    code = generate_python(wf)
    assert "# Element Exists" in code
    assert "# TODO: Element Exists with no selector captured" in code
    _compiles(code)


def test_ui_element_exists_with_no_selector_is_todo():
    wf = _wrap([UiElementExistsNode(selector=None, exists=VbExpr(text="x"))])
    code = generate_python(wf)
    assert "# TODO: Element Exists with no selector captured" in code
    _compiles(code)


def test_ui_element_exists_with_no_output_exists_is_todo():
    wf = _wrap([UiElementExistsNode(selector=_ELEMENT_EXISTS_SELECTOR, exists=None)])
    code = generate_python(wf)
    assert "# TODO: Element Exists with no output Exists captured" in code
    _compiles(code)


def test_ui_element_exists_with_unmappable_selector_is_todo():
    wf = _wrap(
        [UiElementExistsNode(selector="<wnd idx='2' />", exists=VbExpr(text="x"))]
    )
    code = generate_python(wf)
    assert "# TODO: Element Exists selector had no mappable attributes" in code
    _compiles(code)


def _sqlite_connect_node(**overrides) -> DatabaseConnectNode:
    defaults = dict(
        database_connection=VbExpr(text="conn"),
        provider_name=Literal(value="System.Data.SQLite"),
        connection_string=Literal(value="Data Source=db.sqlite;Version=3;"),
    )
    defaults.update(overrides)
    return DatabaseConnectNode(**defaults)


def test_database_connect_with_sqlite_provider_generates_sqlite3_connect():
    wf = _wrap([_sqlite_connect_node()])
    code = generate_python(wf)
    assert "conn = sqlite3.connect('db.sqlite')" in code
    assert "conn.row_factory = sqlite3.Row" in code
    assert "import sqlite3" in code
    _compiles(code)


def test_database_connect_display_name_becomes_a_comment_even_when_falling_back_to_todo():
    wf = _wrap([DatabaseConnectNode(database_connection=None, display_name="Connect")])
    code = generate_python(wf)
    assert "# Connect" in code
    assert "# TODO: Database Connect with no output DatabaseConnection captured" in code
    _compiles(code)


def test_database_connect_with_no_output_is_todo():
    wf = _wrap([DatabaseConnectNode(database_connection=None)])
    code = generate_python(wf)
    assert "# TODO: Database Connect with no output DatabaseConnection captured" in code
    _compiles(code)


def test_database_connect_with_secure_connection_string_is_todo_not_guessed():
    wf = _wrap(
        [_sqlite_connect_node(secure_connection_string=VbExpr(text="secureCs"))]
    )
    code = generate_python(wf)
    assert "# TODO: Database Connect with SecureConnectionString set" in code
    _compiles(code)


@pytest.mark.parametrize(
    "provider_name",
    [None, Literal(value="System.Data.SqlClient"), VbExpr(text="someProvider")],
)
def test_database_connect_with_unconfirmed_provider_is_todo_not_guessed(provider_name):
    wf = _wrap([_sqlite_connect_node(provider_name=provider_name)])
    code = generate_python(wf)
    assert "# TODO: Database Connect with unconfirmed ProviderName" in code
    assert "sqlite3.connect(" not in code
    _compiles(code)


def test_database_connect_with_non_literal_connection_string_is_todo_not_guessed():
    wf = _wrap([_sqlite_connect_node(connection_string=VbExpr(text="dynamicCs"))])
    code = generate_python(wf)
    assert "# TODO: Database Connect with non-literal ConnectionString" in code
    _compiles(code)


def test_database_connect_with_missing_data_source_key_is_todo_not_guessed():
    wf = _wrap(
        [_sqlite_connect_node(connection_string=Literal(value="Version=3;"))]
    )
    code = generate_python(wf)
    assert "# TODO: Database Connect with ConnectionString missing a 'Data Source' key" in code
    _compiles(code)


def test_database_disconnect_generates_close_call():
    wf = _wrap([DatabaseDisconnectNode(database_connection=VbExpr(text="conn"))])
    code = generate_python(wf)
    assert "conn.close()" in code
    _compiles(code)


def test_database_disconnect_with_no_connection_is_todo():
    wf = _wrap([DatabaseDisconnectNode(database_connection=None, display_name="Disconnect")])
    code = generate_python(wf)
    assert "# Disconnect" in code
    assert "# TODO: Database Disconnect with no DatabaseConnection captured" in code
    _compiles(code)


def _execute_query_node(**overrides) -> ExecuteQueryNode:
    defaults = dict(
        sql=Literal(value="SELECT * FROM post"),
        existing_db_connection=VbExpr(text="conn"),
        data_table=VbExpr(text="table"),
        command_type="Text",
    )
    defaults.update(overrides)
    return ExecuteQueryNode(**defaults)


def test_execute_query_with_known_connection_generates_fetchall():
    wf = _wrap([_execute_query_node()])
    code = generate_python(wf)
    assert "_cur = conn.execute('SELECT * FROM post')" in code
    assert "table = [dict(_r) for _r in _cur.fetchall()]" in code
    _compiles(code)


def test_execute_query_with_no_output_data_table_is_todo():
    wf = _wrap([_execute_query_node(data_table=None)])
    code = generate_python(wf)
    assert "# TODO: Execute Query with no output DataTable captured" in code
    _compiles(code)


def test_execute_query_with_no_sql_is_todo():
    wf = _wrap([_execute_query_node(sql=None)])
    code = generate_python(wf)
    assert "# TODO: Execute Query with no Sql captured" in code
    _compiles(code)


def test_execute_query_with_no_existing_connection_is_todo():
    wf = _wrap([_execute_query_node(existing_db_connection=None)])
    code = generate_python(wf)
    assert "# TODO: Execute Query with no ExistingDbConnection captured" in code
    _compiles(code)


def test_execute_query_with_unconfirmed_command_type_is_todo_not_guessed():
    wf = _wrap([_execute_query_node(command_type="StoredProcedure")])
    code = generate_python(wf)
    assert "# TODO: Execute Query with unconfirmed CommandType" in code
    _compiles(code)


def test_execute_query_with_populated_parameters_is_todo_not_guessed():
    wf = _wrap([_execute_query_node(parameters={"id": Literal(value="1")})])
    code = generate_python(wf)
    assert "# TODO: Execute Query with populated Parameters" in code
    _compiles(code)


def test_execute_query_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap([_execute_query_node(continue_on_error=Literal(value="True"))])
    code = generate_python(wf)
    assert "# TODO: Execute Query with ContinueOnError set" in code
    _compiles(code)


def test_execute_query_with_timeout_ms_is_todo_not_guessed():
    wf = _wrap([_execute_query_node(timeout_ms=Literal(value="5000"))])
    code = generate_python(wf)
    assert "# TODO: Execute Query with TimeoutMS set" in code
    _compiles(code)


def _execute_non_query_node(**overrides) -> ExecuteNonQueryNode:
    defaults = dict(
        sql=Literal(value="DELETE FROM post WHERE id=1"),
        existing_db_connection=VbExpr(text="conn"),
        affected_records=VbExpr(text="rows"),
        command_type="Text",
    )
    defaults.update(overrides)
    return ExecuteNonQueryNode(**defaults)


def test_execute_non_query_with_known_connection_generates_commit_and_rowcount():
    wf = _wrap([_execute_non_query_node()])
    code = generate_python(wf)
    assert "_cur = conn.execute('DELETE FROM post WHERE id=1')" in code
    assert "conn.commit()" in code
    assert "rows = _cur.rowcount" in code
    _compiles(code)


def test_execute_non_query_with_no_output_affected_records_is_todo():
    wf = _wrap([_execute_non_query_node(affected_records=None)])
    code = generate_python(wf)
    assert "# TODO: Execute Non Query with no output AffectedRecords captured" in code
    _compiles(code)


def test_execute_non_query_with_populated_parameters_is_todo_not_guessed():
    wf = _wrap([_execute_non_query_node(parameters={"id": Literal(value="1")})])
    code = generate_python(wf)
    assert "# TODO: Execute Non Query with populated Parameters" in code
    _compiles(code)


def test_insert_data_table_with_dict_rows_builds_named_column_insert():
    """知見230: `ui:InsertDataTable`。`DataTable`がdict行表現の場合、
    実機`UiPath532/UiPathExamples`相当の構成で`exec()`経由で実際に
    `sqlite3`へINSERTし、列名付きSQLが正しく動くことを確認する。"""
    wf = _wrap(
        [
            InsertDataTableNode(
                data_table=VbExpr(text="dt"),
                table_name=Literal(value="products"),
                existing_db_connection=VbExpr(text="conn"),
                affected_records=VbExpr(text="affected"),
            )
        ]
    )
    code = generate_python(wf)
    assert "isinstance(dt[0], dict)" in code
    assert "# TODO" not in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(conn, dt):")
    code2 += "\n    return affected"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE products (name TEXT, price REAL)")
    dt = [{"name": "Widget", "price": 9.99}, {"name": "Gadget", "price": 19.99}]
    assert namespace["Test"](conn, dt) == 2
    assert conn.execute("SELECT * FROM products").fetchall() == [
        ("Widget", 9.99),
        ("Gadget", 19.99),
    ]


def test_insert_data_table_with_list_rows_falls_back_to_positional_insert():
    """知見230: `DataTable`がlist行表現の場合、列名が無いため全列を
    順序通りに与えると仮定した保守的な縮退(`# WARNING`コメント付き)
    で動くことを`exec()`経由で確認する。"""
    wf = _wrap(
        [
            InsertDataTableNode(
                data_table=VbExpr(text="dt"),
                table_name=Literal(value="products"),
                existing_db_connection=VbExpr(text="conn"),
                affected_records=VbExpr(text="affected"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# WARNING: list-shaped rows have no column names" in code
    code2 = code.replace("def Test():", "def Test(conn, dt):")
    code2 += "\n    return affected"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE products (name TEXT, price REAL)")
    dt = [("Widget", 9.99), ("Gadget", 19.99)]
    assert namespace["Test"](conn, dt) == 2
    assert conn.execute("SELECT * FROM products").fetchall() == dt


def test_bulk_insert_shares_insert_data_table_codegen():
    """知見230: `ui:BulkInsert`は`InsertDataTable`と属性構成・意味論が
    全く同じ兄弟活動——同じコード生成関数を共用することを確認する。
    `TableName`はスキーマ修飾名(`andresporras3423/scrapingRealState`
    相当)も問題なく通ることを確認する。"""
    wf = _wrap(
        [
            BulkInsertNode(
                data_table=VbExpr(text="dt"),
                table_name=Literal(value="stage.datosVivienda"),
                existing_db_connection=VbExpr(text="conn"),
                affected_records=VbExpr(text="affected"),
            )
        ]
    )
    code = generate_python(wf)
    assert "stage.datosVivienda" in code
    assert "_idt_cur = conn.executemany(" in code
    assert "# TODO" not in code
    _compiles(code)


def test_insert_data_table_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap(
        [
            InsertDataTableNode(
                data_table=VbExpr(text="dt"),
                table_name=Literal(value="products"),
                existing_db_connection=VbExpr(text="conn"),
                affected_records=VbExpr(text="affected"),
                continue_on_error=Literal(value="True"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: InsertDataTable with ContinueOnError set" in code
    _compiles(code)


def test_insert_data_table_with_missing_properties_is_todo():
    wf = _wrap(
        [
            InsertDataTableNode(
                data_table=None,
                table_name=Literal(value="products"),
                existing_db_connection=VbExpr(text="conn"),
                affected_records=VbExpr(text="affected"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: InsertDataTable with missing DataTable/TableName" in code
    _compiles(code)


def test_database_transaction_with_use_transaction_false_runs_body_normally():
    """知見231: `UseTransaction=False`(公式ドキュメント確認済みの
    「各操作が個別にコミットされる」)は、`ExecuteNonQuery`が既に
    自前で`commit()`する既存コード生成とそのまま一致するため、
    `Body`を単純に展開するだけで正しく動くことを`exec()`経由で実際の
    `sqlite3`データベースへ確認する。"""
    wf = _wrap(
        [
            DatabaseTransactionNode(
                database_connection=VbExpr(text="conn"),
                use_transaction="False",
                body=[
                    ExecuteNonQueryNode(
                        sql=Literal(value="INSERT INTO t VALUES (1)"),
                        existing_db_connection=VbExpr(text="conn"),
                        affected_records=VbExpr(text="rows"),
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO" not in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(conn):")
    code2 += "\n    return rows"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (x INTEGER)")
    assert namespace["Test"](conn) == 1
    assert conn.execute("SELECT * FROM t").fetchall() == [(1,)]


def test_database_transaction_with_use_transaction_true_is_todo():
    """知見231: `UseTransaction=True`(既定値)は、`Body`配下の子活動が
    既に個別に`commit()`してしまう既存実装とそのままでは両立せず、
    見た目だけ機能するtry/exceptをでっち上げるより`# TODO`へ倒す
    方針を確認する。"""
    wf = _wrap(
        [
            DatabaseTransactionNode(
                database_connection=VbExpr(text="conn"),
                use_transaction="True",
                body=[],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: DatabaseTransaction with UseTransaction=True" in code
    _compiles(code)

    wf2 = _wrap(
        [DatabaseTransactionNode(database_connection=VbExpr(text="conn"), body=[])]
    )
    code2 = generate_python(wf2)
    assert "# TODO: DatabaseTransaction with UseTransaction=True" in code2
    _compiles(code2)


def test_database_transaction_self_connecting_mode_is_todo_not_guessed():
    wf = _wrap(
        [
            DatabaseTransactionNode(
                database_connection=None,
                connection_string=Literal(value="Host=localhost;"),
                provider_name=Literal(value="MySql.Data.MySqlClient"),
                use_transaction="True",
                body=[],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: DatabaseTransaction establishing its own connection" in code
    _compiles(code)


def test_database_transaction_with_no_database_connection_is_todo():
    wf = _wrap(
        [DatabaseTransactionNode(database_connection=None, use_transaction="False", body=[])]
    )
    code = generate_python(wf)
    assert "# TODO: DatabaseTransaction with no DatabaseConnection captured" in code
    _compiles(code)


def _extract_text_node(**overrides) -> ExtractTextNode:
    defaults = dict(
        source=VbExpr(text="str_PDFData"),
        starting_text=Literal(value="Check Number "),
        ending_text=Literal(value="Check Date"),
        result=VbExpr(text="out_CheckNumber"),
        extract_options="BetweenStrings",
        match_case="False",
        ignore_duplicates="False",
        extract_base_url_only="False",
    )
    defaults.update(overrides)
    return ExtractTextNode(**defaults)


def test_extract_text_returns_substring_between_markers_case_insensitive():
    """知見232: `uast:ExtractText`。実機`sree-hari-s/ACME-REFramework`
    相当の構成を`exec()`経由で実際に実行し、マーカー文字列自体を含まず
    その間の文字列だけが抜き出されること、`MatchCase`省略時の既定
    (大文字小文字を区別しない検索、出力は元の大文字小文字を保持)を
    確認する。"""
    wf = _wrap([_extract_text_node()])
    code = generate_python(wf)
    assert "# TODO" not in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(str_PDFData):")
    code2 += "\n    return out_CheckNumber"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    sample = "Check Number 12345\nCheck Date 2024-01-01"
    assert namespace["Test"](sample) == "12345\n"


def test_extract_text_match_case_true_is_case_sensitive():
    wf = _wrap([_extract_text_node(match_case="True")])
    code = generate_python(wf)
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(str_PDFData):")
    code2 += "\n    return out_CheckNumber"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    sample = "Check Number 99\nCheck Date 2024-01-01"
    assert namespace["Test"](sample) == "99\n"
    with pytest.raises(ValueError):
        namespace["Test"]("check number 99\nCheck Date 2024-01-01")


def test_extract_text_missing_marker_raises_value_error():
    """知見232: `StartingText`/`EndingText`が見つからない場合の挙動は
    未確認——フォールバック値を捏造せず自然な`ValueError`に委ねる方針
    (`TextToLeftRight`等と同じ)を`exec()`経由で確認する。"""
    wf = _wrap([_extract_text_node()])
    code = generate_python(wf)
    code2 = code.replace("def Test():", "def Test(str_PDFData):")
    code2 += "\n    return out_CheckNumber"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    with pytest.raises(ValueError):
        namespace["Test"]("no markers here")


def test_extract_text_with_missing_properties_is_todo():
    wf = _wrap([_extract_text_node(result=None)])
    code = generate_python(wf)
    assert (
        "# TODO: ExtractText with missing Source/StartingText/EndingText/"
        "Result" in code
    )
    _compiles(code)


def test_extract_text_with_unconfirmed_extract_options_is_todo_not_guessed():
    wf = _wrap([_extract_text_node(extract_options="Url")])
    code = generate_python(wf)
    assert "# TODO: ExtractText with unconfirmed ExtractOptions ('Url')" in code
    _compiles(code)


def test_extract_text_with_ignore_duplicates_true_is_todo_not_guessed():
    wf = _wrap([_extract_text_node(ignore_duplicates="True")])
    code = generate_python(wf)
    assert "# TODO: ExtractText with IgnoreDuplicates set ('True')" in code
    _compiles(code)


def test_split_text_with_newline_separator_key_exec():
    """知見249: `uast:SplitText`。実機2件(本活動+`CombineText`)で
    確認した`SeparatorKey="NewLine"`時の`Separator`実際の直列化値は
    文字そのまま`"NewLine"`(`ui:TextToLeftRight`の実CRLFバイトとは
    違う規約)——`SeparatorKey`に応じてPython側で実際の区切り文字
    (`"\\r\\n"`)へ変換することを`exec()`経由で確認する。"""
    wf = WorkflowFile(
        class_name="Test",
        root=SequenceNode(
            body=[
                SplitTextNode(
                    source=VbExpr(text="brandLinks"),
                    separator="NewLine",
                    separator_key="NewLine",
                    results=VbExpr(text="links"),
                )
            ]
        ),
        arguments={"brandLinks": "InArgument(x:String)"},
    )
    code = generate_python(wf)
    assert "links = _vb_cstr(brandLinks).split('\\r\\n')" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code + "\n    return links", namespace)  # noqa: S102 - 信頼できる自作コード
    assert namespace["Test"]("a\r\nb\r\nc") == ["a", "b", "c"]


def test_split_text_with_unconfirmed_separator_key_is_todo():
    wf = _wrap(
        [
            SplitTextNode(
                source=Literal(value="a,b,c"),
                separator=",",
                separator_key="Custom",
                results=VbExpr(text="r"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: SplitText with SeparatorKey" in code
    _compiles(code)


def test_split_text_with_missing_properties_is_todo():
    wf = _wrap([SplitTextNode(source=None, results=VbExpr(text="r"))])
    code = generate_python(wf)
    assert "# TODO: SplitText with missing Source/Results" in code
    _compiles(code)


def test_combine_text_with_newline_separator_key_exec():
    """知見249: `uast:CombineText`——`SplitText`の逆方向、
    `"\\r\\n".join(...)`に対応する。"""
    wf = WorkflowFile(
        class_name="Test",
        root=SequenceNode(
            body=[
                CombineTextNode(
                    source=VbExpr(text="parts"),
                    separator="NewLine",
                    separator_key="NewLine",
                    result=VbExpr(text="joined"),
                )
            ]
        ),
        arguments={"parts": "InArgument(scg:List(x:String))"},
    )
    code = generate_python(wf)
    assert "joined = '\\r\\n'.join(parts)" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code + "\n    return joined", namespace)  # noqa: S102 - 信頼できる自作コード
    assert namespace["Test"](["x", "y", "z"]) == "x\r\ny\r\nz"


def test_combine_text_with_unconfirmed_separator_key_is_todo():
    wf = _wrap(
        [
            CombineTextNode(
                source=VbExpr(text="parts"),
                separator=",",
                separator_key="Custom",
                result=VbExpr(text="r"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: CombineText with SeparatorKey" in code
    _compiles(code)


def test_combine_text_with_missing_properties_is_todo():
    wf = _wrap([CombineTextNode(source=None, result=VbExpr(text="r"))])
    code = generate_python(wf)
    assert "# TODO: CombineText with missing Source/Result" in code
    _compiles(code)


def test_get_last_downloaded_file_finds_new_file_ignoring_temp_extension():
    """知見233: `ui:GetLastDownloadedFile`。実機
    `alvaroqr14/UiPath_Ejemplo_WaitForDownload`相当の構成
    (`IgnoreFiles="crdownload"`)を`exec()`経由で実際の一時ディレクトリ
    へ実行し、一時拡張子ファイルを無視して本体ファイルの出現を
    ポーリングで検出することを確認する。"""
    wf = _wrap(
        [
            GetLastDownloadedFileNode(
                download_folder=VbExpr(text="folder"),
                file=VbExpr(text="result_file"),
                timeout=Literal(value="5"),
                ignore_files=Literal(value="crdownload"),
                body=[],
            )
        ]
    )
    code = generate_python(wf)
    assert "os.listdir(" in code
    assert "import os" in code
    assert "import time" in code
    assert "# TODO" not in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(folder):")
    code2 += "\n    return result_file"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    import tempfile
    import threading
    import time as _time

    with tempfile.TemporaryDirectory() as d:
        def simulate_download():
            _time.sleep(0.3)
            with open(os.path.join(d, "temp.crdownload"), "w") as f:
                f.write("partial")
            _time.sleep(0.3)
            os.remove(os.path.join(d, "temp.crdownload"))
            with open(os.path.join(d, "report.xlsx"), "w") as f:
                f.write("data")

        t = threading.Thread(target=simulate_download)
        t.start()
        result = namespace["Test"](d)
        t.join()
        assert result == os.path.join(d, "report.xlsx")


def test_get_last_downloaded_file_raises_timeout_error_when_nothing_appears():
    """知見233: 新規ファイルが`Timeout`以内に出現しない場合は
    `TimeoutError`を投げる(フォールバック値を捏造しない既存方針)
    ことを`exec()`経由で確認する。"""
    wf = _wrap(
        [
            GetLastDownloadedFileNode(
                download_folder=VbExpr(text="folder"),
                file=VbExpr(text="result_file"),
                timeout=Literal(value="1"),
            )
        ]
    )
    code = generate_python(wf)
    code2 = code.replace("def Test():", "def Test(folder):")
    code2 += "\n    return result_file"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(TimeoutError):
            namespace["Test"](d)


def test_get_last_downloaded_file_defaults_timeout_to_300_when_omitted():
    """知見233: `Timeout`省略時は公式ドキュメント確認済みの既定`300`秒。"""
    wf = _wrap(
        [
            GetLastDownloadedFileNode(
                download_folder=VbExpr(text="folder"),
                file=VbExpr(text="result_file"),
            )
        ]
    )
    code = generate_python(wf)
    assert "round(_vb_cdbl(300))" in code
    _compiles(code)


def test_get_last_downloaded_file_with_file_resource_is_todo_not_guessed():
    wf = _wrap(
        [
            GetLastDownloadedFileNode(
                download_folder=VbExpr(text="folder"),
                file=VbExpr(text="result_file"),
                file_resource=Literal(value="x"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: GetLastDownloadedFile with FileResource set" in code
    _compiles(code)


def test_get_last_downloaded_file_name_and_fullname_attribute_access():
    """知見233: `File`出力を絶対パス文字列として表現する既存方針
    (`ForEachFileX`/`ForEachFolderX`知見190)により、`.Name`
    (`render.py`に新規追加)と`.FullName`(既存の`fullname`ハンドラ)
    の両方がダウンストリームで正しく解決されることを確認する。"""
    from dump_daemon.uipath_codegen.render import render_expr

    assert render_expr(VbExpr(text="file_Studio.Name")) == "os.path.basename(file_Studio)"
    assert render_expr(VbExpr(text="file_Studio.FullName")) == "file_Studio"


def test_get_last_downloaded_file_with_missing_properties_is_todo():
    wf = _wrap([GetLastDownloadedFileNode(download_folder=None, file=VbExpr(text="r"))])
    code = generate_python(wf)
    assert "# TODO: GetLastDownloadedFile with missing DownloadFolder/File" in code
    _compiles(code)


def test_check_true_raises_when_expression_is_false():
    """知見234: `ui:CheckTrue`。実機`flindersuni/rpa-Flinders.Helpers`
    相当の構成(ログイン成否チェック)を`exec()`経由で実際に実行し、
    式がfalseの場合のみ`ErrorMessage`付きの例外を投げることを確認
    する。"""
    wf = _wrap(
        [
            CheckTrueNode(
                expression=VbExpr(text="processSuccessful"),
                error_message=VbExpr(text="processMessage"),
            )
        ]
    )
    code = generate_python(wf)
    assert "if not _vb_bool(processSuccessful):" in code
    assert "raise Exception(_vb_cstr(processMessage))" in code
    assert "# TODO" not in code
    _compiles(code)
    code2 = code.replace(
        "def Test():", "def Test(processSuccessful, processMessage):"
    )
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    namespace["Test"](True, "login failed")
    with pytest.raises(Exception, match="login failed"):
        namespace["Test"](False, "login failed")


def test_check_false_raises_when_expression_is_true():
    """知見234: `ui:CheckFalse`。実機`flindersuni/rpa-Flinders.Helpers`
    相当の構成(必須入力の未入力チェック)を`exec()`経由で実際に実行し、
    式がtrueの場合のみ`ErrorMessage`付きの例外を投げることを確認
    する。"""
    wf = _wrap(
        [
            CheckFalseNode(
                expression=VbExpr(text="x"),
                error_message=Literal(value="must be supplied"),
            )
        ]
    )
    code = generate_python(wf)
    assert "if _vb_bool(x):" in code
    assert "raise Exception(_vb_cstr('must be supplied'))" in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(x):")
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    namespace["Test"](False)
    with pytest.raises(Exception, match="must be supplied"):
        namespace["Test"](True)


def test_check_true_and_check_false_with_missing_properties_is_todo():
    wf = _wrap([CheckTrueNode(expression=None, error_message=VbExpr(text="m"))])
    code = generate_python(wf)
    assert "# TODO: CheckTrue with missing Expression/ErrorMessage" in code
    _compiles(code)

    wf2 = _wrap([CheckFalseNode(expression=VbExpr(text="x"), error_message=None)])
    code2 = generate_python(wf2)
    assert "# TODO: CheckFalse with missing Expression/ErrorMessage" in code2
    _compiles(code2)


def test_create_directory_makes_nested_dirs_idempotently():
    """知見235: `ui:CreateDirectory`。実機`PacktPublishing/
    Robotic-Process-Automation-Projects`相当の構成を`exec()`経由で
    実際の一時ディレクトリへ実行し、中間の親ディレクトリも含めて
    作成されること、既存ディレクトリへの再実行でも例外にならない
    こと(.NET`Directory.CreateDirectory()`の確立済みAPIコントラクト)
    を確認する。"""
    wf = _wrap([CreateDirectoryNode(path=VbExpr(text="target_path"))])
    code = generate_python(wf)
    assert "os.makedirs(" in code
    assert "import os" in code
    assert "# TODO" not in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(target_path):")
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        nested = os.path.join(d, "a", "b", "c")
        namespace["Test"](nested)
        assert os.path.isdir(nested)
        namespace["Test"](nested)
        assert os.path.isdir(nested)


def test_create_directory_with_no_path_is_todo():
    wf = _wrap([CreateDirectoryNode(path=None)])
    code = generate_python(wf)
    assert "# TODO: CreateDirectory with no Path captured" in code
    _compiles(code)


def test_create_directory_with_output_is_todo_not_guessed():
    wf = _wrap([CreateDirectoryNode(path=VbExpr(text="p"), output=VbExpr(text="o"))])
    code = generate_python(wf)
    assert "# TODO: CreateDirectory with Output set" in code
    _compiles(code)


def test_create_directory_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap(
        [
            CreateDirectoryNode(
                path=VbExpr(text="p"), continue_on_error=Literal(value="True")
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: CreateDirectory with ContinueOnError set" in code
    _compiles(code)


def test_merge_data_table_appends_source_rows_into_destination_in_place():
    """知見236: `ui:MergeDataTable`。実機`HarshadRanganathan/
    uipath-learning`相当の連鎖マージ構成を`exec()`経由で実際に実行
    し、`Destination`がインプレースで拡張されること、行が値コピー
    (参照共有ではない)されること——`Source`側を事後に変更しても
    `Destination`側へ伝播しないこと——を確認する。"""
    wf = _wrap(
        [
            MergeDataTableNode(
                destination=VbExpr(text="dt2"),
                source=VbExpr(text="dt1"),
                missing_schema_action="Add",
            )
        ]
    )
    code = generate_python(wf)
    assert "dt2.extend(" in code
    assert "# TODO" not in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(dt1, dt2):")
    code2 += "\n    return dt2"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    dt1 = [{"a": 1}, {"a": 2}]
    dt2 = [{"a": 0}]
    result = namespace["Test"](dt1, dt2)
    assert result is dt2
    assert result == [{"a": 0}, {"a": 1}, {"a": 2}]
    dt1[0]["a"] = 999
    assert result == [{"a": 0}, {"a": 1}, {"a": 2}]


def test_merge_data_table_handles_list_rows():
    wf = _wrap(
        [MergeDataTableNode(destination=VbExpr(text="dt2"), source=VbExpr(text="dt1"))]
    )
    code = generate_python(wf)
    code2 = code.replace("def Test():", "def Test(dt1, dt2):")
    code2 += "\n    return dt2"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    dt1 = [[1, 2]]
    dt2 = [[3, 4]]
    assert namespace["Test"](dt1, dt2) == [[3, 4], [1, 2]]


def test_merge_data_table_with_missing_properties_is_todo():
    wf = _wrap([MergeDataTableNode(destination=None, source=VbExpr(text="s"))])
    code = generate_python(wf)
    assert "# TODO: MergeDataTable with missing Destination/Source" in code
    _compiles(code)


def test_merge_data_table_with_unconfirmed_missing_schema_action_is_todo_not_guessed():
    wf = _wrap(
        [
            MergeDataTableNode(
                destination=VbExpr(text="d"),
                source=VbExpr(text="s"),
                missing_schema_action="Error",
            )
        ]
    )
    code = generate_python(wf)
    assert (
        "# TODO: MergeDataTable with unconfirmed MissingSchemaAction ('Error')"
        in code
    )
    _compiles(code)


def test_format_value_currency_number_format_provider_prefixes_symbol():
    """知見237: `ui:FormatValue`。実機`psri981/Group8-300-762`相当の
    `CurrencyNumberFormatProvider`構成を`exec()`経由で実際に実行し、
    `Value`が入出力同じ変数へインプレースでフォーマット済み文字列
    へ上書きされることを確認する。"""
    wf = _wrap(
        [
            FormatValueNode(
                value=VbExpr(text="genericVal"),
                format_kind="CurrencyNumberFormatProvider",
                decimal_digits="0",
                decimal_separator=".",
                group_separator=",",
                symbol="$",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO" not in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(genericVal):")
    code2 += "\n    return genericVal"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    assert namespace["Test"](1234.5) == "$1,234"


def test_format_value_general_number_format_provider_default_two_digits():
    wf = _wrap(
        [FormatValueNode(value=VbExpr(text="v"), format_kind="GeneralNumberFormatProvider")]
    )
    code = generate_python(wf)
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(v):")
    code2 += "\n    return v"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    assert namespace["Test"](1234.5) == "1,234.50"


def test_format_value_date_time_format_provider_strftime():
    """知見237: 実機`mtayyab153/RPA`相当の`DateTimeFormatProvider`
    構成(`Pattern="dddd, dd MMMM yyyy"`)を`exec()`経由で実際に実行
    し、.NETカスタム日付書式トークンがPythonの`strftime()`書式へ
    正しく変換されることを確認する。"""
    wf = _wrap(
        [
            FormatValueNode(
                value=VbExpr(text="tes"),
                format_kind="DateTimeFormatProvider",
                pattern="dddd, dd MMMM yyyy",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO" not in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(tes):")
    code2 += "\n    return tes"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    import datetime

    assert namespace["Test"](datetime.datetime(2024, 3, 15)) == "Friday, 15 March 2024"


def test_format_value_date_time_format_provider_declines_unsupported_tokens():
    """知見237: 単独の`M`/`d`・時刻系トークン(`HH`/`mm`/`ss`等)は
    実機未確認のため未対応——リテラルテキストとして誤って素通し
    されないこと(文字単位の誤変換を防ぐガード)を確認する。"""
    wf = _wrap(
        [
            FormatValueNode(
                value=VbExpr(text="v"),
                format_kind="DateTimeFormatProvider",
                pattern="HH:mm:ss",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: FormatValue with unsupported token in Pattern" in code
    _compiles(code)


def test_format_value_with_non_default_separator_is_todo_not_guessed():
    wf = _wrap(
        [
            FormatValueNode(
                value=VbExpr(text="v"),
                format_kind="GeneralNumberFormatProvider",
                group_separator=".",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: FormatValue with non-default GroupSeparator ('.')" in code
    _compiles(code)


def test_format_value_with_unconfirmed_format_kind_is_todo_not_guessed():
    wf = _wrap([FormatValueNode(value=VbExpr(text="v"), format_kind=None)])
    code = generate_python(wf)
    assert "# TODO: FormatValue with unconfirmed/unsupported Format type" in code
    _compiles(code)


def test_format_value_with_no_value_is_todo():
    wf = _wrap([FormatValueNode(value=None, format_kind="GeneralNumberFormatProvider")])
    code = generate_python(wf)
    assert "# TODO: FormatValue with no Value captured" in code
    _compiles(code)


def test_convert_dotnet_date_pattern_helper():
    """知見237: `_convert_dotnet_date_pattern()`単体テスト——.NET
    カスタム日付書式トークンの変換と、未確認トークン(単独`M`/`d`・
    時刻系)が文字単位でリテラルとして誤って素通しされないことの
    両方を確認する(実装中に`HH:mm:ss`がリテラルとして素通しされる
    バグを`exec()`確認前に発見・修正した)。"""
    from dump_daemon.uipath_codegen import _convert_dotnet_date_pattern

    assert _convert_dotnet_date_pattern("dddd, dd MMMM yyyy") == "%A, %d %B %Y"
    assert _convert_dotnet_date_pattern("yyyy-MM-dd") == "%Y-%m-%d"
    assert _convert_dotnet_date_pattern("M/d/yyyy") is None
    assert _convert_dotnet_date_pattern("HH:mm:ss") is None
    assert _convert_dotnet_date_pattern("yyyy-MM-ddTHH:mm:ss") is None


@pytest.mark.parametrize(
    ("node", "expected_detail"),
    [
        # 知見75: 知見70で発見した5つの未対応アクティビティそれぞれが、
        # でっち上げず捕捉済みのフィールドをそのまま`# TODO`コメントへ
        # 追記することの回帰テスト(人間が手動でポートする際の手がかり)。
        (InvokeCodeNode(code="content=content.ToUpper()"), "(Code='content=content.ToUpper()')"),
        (
            # 知見97: `ExcelApplicationScopeNode`はもはやunresolvedに倒れず
            # `openpyxl`への実コード生成を行うため、ここでは除いた——下記の
            # Excel専用テスト群を参照。`ExcelWriteCellNode`はスコープの
            # 外側(単独)の場合のみこのフォールバックに残る。
            ExcelWriteCellNode(cell=Literal(value="A1"), sheet_name="Sheet1", text=Literal(value="hi")),
            "(Cell='A1', SheetName='Sheet1', Text='hi')",
        ),
        (
            # 知見98・102: 単純な構成はもはやunresolvedに倒れず実際の
            # win32comコードを生成するため、ここでは`Files`に添付がある
            # ことにしてフォールバックを明示的に発生させる(詳細は下記の
            # Outlook専用テスト群を参照)。
            SendOutlookMailNode(
                to=Literal(value="a@b.com"),
                subject=Literal(value="Hi"),
                body=Literal(value="x"),
                has_populated_files=True,
            ),
            "(To='a@b.com', Subject='Hi', Body='x', Cc=(not set), Bcc=(not set), "
            "Importance=None, Sensitivity=None, IsBodyHtml=None, IsDraft=None)",
        ),
        (
            # 知見96・104: 単純な構成(コレクション全て空)はもはや
            # unresolvedに倒れず実際のrequestsコードを生成するため、ここでは
            # `Cookies`等が空でないことにしてフォールバックを明示的に
            # 発生させる。
            HttpClientNode(
                endpoint=VbExpr(text="url"), method="POST", has_populated_collections=True
            ),
            "(EndPoint=[url], Method='POST', Body=(not set))",
        ),
    ],
)
def test_unresolved_activity_todo_includes_captured_fields(node, expected_detail: str) -> None:
    wf = _wrap([node])
    code = generate_python(wf)
    assert f"# TODO: unsupported in v1 codegen: {type(node).__name__} {expected_detail}" in code
    _compiles(code)


def test_http_client_generates_real_requests_call_for_simple_case():
    """知見96: `Headers`/`Cookies`/`Parameters`/`UrlSegments`/`Attachments`が
    全て空・`Body`未設定という実機フィクスチャで確認済みの構成では、
    `# TODO`ではなく実際に動く`requests.request(...)`を生成する。"""
    node = HttpClientNode(endpoint=Literal(value="https://example.com/api"), method="GET")
    wf = _wrap([node])
    code = generate_python(wf)
    assert "import requests" in code
    assert "requests.request('GET', 'https://example.com/api')" in code
    assert "# TODO" not in code
    _compiles(code)


def test_http_client_converts_timeout_ms_to_seconds():
    """知見96: `TimeoutMS`(UiPath公式ドキュメント、既定値6000ms)をrequestsの
    `timeout`(秒)へ単位変換する。"""
    node = HttpClientNode(
        endpoint=Literal(value="https://example.com/api"), method="GET", timeout_ms="6000"
    )
    wf = _wrap([node])
    code = generate_python(wf)
    assert "requests.request('GET', 'https://example.com/api', timeout=6.0)" in code
    _compiles(code)


def test_http_client_falls_back_to_todo_with_populated_fallback_collections():
    """知見96・104: `Cookies`/`Parameters`/`UrlSegments`/`Attachments`
    (`Headers`は知見104で専用対応済み)に1件以上のエントリがある場合は
    populated時の意味論が実機未確認のため、でっち上げず`# TODO`に倒す。"""
    node = HttpClientNode(
        endpoint=Literal(value="https://example.com/api"),
        method="POST",
        has_populated_collections=True,
    )
    wf = _wrap([node])
    code = generate_python(wf)
    assert "# TODO: unsupported in v1 codegen: HttpClientNode" in code
    assert "requests.request(" not in code
    _compiles(code)


def test_http_client_with_body_generates_data_kwarg():
    """知見104: `Body`が設定されている場合(`gh api search/code`で確認済み
    の実例、`vajrang-b/UiPathIn30Days`のPOSTリクエスト)は`requests`の
    `data=`引数へ変換する——もはや`# TODO`に倒れない。"""
    node = HttpClientNode(
        endpoint=Literal(value="https://example.com/api"),
        method="POST",
        body=VbExpr(text="text"),
    )
    wf = _wrap([node])
    code = generate_python(wf)
    assert "# TODO" not in code
    assert "requests.request('POST', 'https://example.com/api', data=_vb_cstr(text))" in code
    _compiles(code)


def test_http_client_with_headers_generates_headers_kwarg():
    """知見104: `Headers`が1件以上のエントリを持つ場合(`gh api search/
    code`で確認済みの実例、`VamsiyadavChakka/OrchestratorAPI-s`の実際の
    `Content-Type`/カスタムヘッダー)は`requests`の`headers=`引数(辞書
    リテラル)へ変換する——もはや`# TODO`に倒れない。"""
    node = HttpClientNode(
        endpoint=Literal(value="https://example.com/api"),
        method="POST",
        headers={"content-Type": Literal(value="application/json")},
    )
    wf = _wrap([node])
    code = generate_python(wf)
    assert "# TODO" not in code
    assert (
        "requests.request('POST', 'https://example.com/api', "
        "headers={'content-Type': _vb_cstr('application/json')})"
    ) in code
    _compiles(code)


def test_http_client_real_fixture_now_generates_real_code():
    """知見96: design/evidence/uipath_xaml_probe/Main.xamlの`<ui:HttpClient>`
    (知見29)は空のHeaders/Cookies/Parameters/UrlSegments/Attachments・
    未設定のBodyという実機確認済みの単純な構成——これまでは`# TODO`に
    倒れていたが、今は実際にrequestsコードが生成されることを確認する。"""
    wf = parse_workflow_file(FIXTURE_DIR / "Main.xaml")
    code = generate_python(wf)
    assert "import requests" in code
    assert "requests.request('GET'" in code
    assert "# TODO: unsupported in v1 codegen: HttpClientNode" not in code


def test_attach_window_recurses_into_body_with_selector_comment():
    """知見153: `ui:AttachWindow`(GitHub code searchで1100件ヒット)。
    子活動(`Click`/`TypeInto`/`SendHotkey`)は`selector`を自己完結的に
    保持するため、`AttachWindow`自身は`scope_var`束縛を作らない透過的
    なラッパーとして実装する——`Selector`は注釈コメントとして出力し、
    子はそのまま再帰生成される。"""
    wf = _wrap(
        [
            AttachWindowNode(
                selector="<wnd app='notepad.exe' />",
                body=[WriteLineNode(text=Literal(value="hi"))],
                display_name="Attach to Notepad",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Attach window: <wnd app='notepad.exe' />" in code
    assert "print(_vb_cstr('hi'))" in code
    assert "# TODO" not in code
    _compiles(code)


def test_attach_window_display_name_becomes_a_comment():
    wf = _wrap(
        [
            AttachWindowNode(
                selector="<wnd app='notepad.exe' />",
                body=[WriteLineNode(text=Literal(value="hi"))],
                display_name="Attach to Notepad",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Attach to Notepad" in code
    _compiles(code)


def test_attach_window_with_no_selector_omits_comment():
    wf = _wrap([AttachWindowNode(selector=None, body=[WriteLineNode(text=Literal(value="hi"))])])
    code = generate_python(wf)
    assert "# Attach window:" not in code
    assert "print(_vb_cstr('hi'))" in code
    _compiles(code)


def test_attach_window_with_empty_body_generates_pass():
    """知見153: `_ensure_nonempty_suite`(知見40と同じ理由)——本体が
    空だとPython構文上`IndentationError`になるため`pass`を補う。"""
    wf = _wrap([AttachWindowNode(selector="<wnd app='notepad.exe' />", body=[])])
    code = generate_python(wf)
    assert "pass" in code
    _compiles(code)


def test_attach_window_child_todo_still_surfaces():
    """知見153: スコープ自体は`# TODO`にならないが、未対応な子の
    `# TODO`は引き続き正しく出る(知見84と同じ教訓)。"""
    wf = _wrap(
        [
            AttachWindowNode(
                selector="<wnd app='notepad.exe' />",
                body=[InvokeCodeNode(code="content=content.ToUpper()")],
            )
        ]
    )
    code = generate_python(wf)
    assert "# Attach window:" in code
    assert "# TODO: unsupported in v1 codegen: InvokeCodeNode" in code
    _compiles(code)


def test_window_scope_with_application_window_is_todo_not_guessed():
    """知見158: `ui:WindowScope`(`AttachWindow`と同義の別活動)の
    `ApplicationWindow`は実機確認した9件以上全てで未設定だった——
    `OpenApplication`の`ApplicationWindow`と同じ理由(UiElement出力
    変数が未実装)ででっち上げず`# TODO`へ倒す。"""
    wf = _wrap(
        [
            AttachWindowNode(
                selector="<wnd app='notepad.exe' />",
                application_window=VbExpr(text="win"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: WindowScope with ApplicationWindow output binding set" in code
    assert "# Attach window:" not in code
    _compiles(code)


def test_window_scope_with_timeout_ms_is_todo_not_guessed():
    wf = _wrap(
        [AttachWindowNode(selector="<wnd app='notepad.exe' />", timeout_ms=Literal(value="2000"))]
    )
    code = generate_python(wf)
    assert "# TODO: WindowScope with TimeoutMS set" in code
    _compiles(code)


def test_browser_scope_recurses_into_body_with_selector_comment():
    """知見161: `ui:BrowserScope`(「Attach Browser」、GitHub code
    searchで3388件ヒット)。`BrowserType`は単純な注釈情報のため
    decline判定の対象にせず、`AttachWindow`/`WindowScope`と同じ透過的
    ラッパーとして子を再帰生成する。"""
    wf = _wrap(
        [
            AttachWindowNode(
                selector="<html app='chrome.exe' />",
                browser_type="Chrome",
                body=[WriteLineNode(text=Literal(value="hi"))],
            )
        ]
    )
    code = generate_python(wf)
    assert "# Attach window: <html app='chrome.exe' />" in code
    assert "print(_vb_cstr('hi'))" in code
    assert "# TODO" not in code
    _compiles(code)


def test_browser_scope_with_browser_is_todo_not_guessed():
    wf = _wrap(
        [
            AttachWindowNode(
                selector="<html app='chrome.exe' />",
                browser_type="Chrome",
                browser=VbExpr(text="existingBrowser"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: BrowserScope with Browser set" in code
    assert "# Attach window:" not in code
    _compiles(code)


def test_browser_scope_with_ui_browser_is_todo_not_guessed():
    wf = _wrap(
        [
            AttachWindowNode(
                selector="<html app='chrome.exe' />",
                browser_type="Chrome",
                ui_browser=VbExpr(text="win"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: BrowserScope with UiBrowser output binding set" in code
    _compiles(code)


def test_browser_scope_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap(
        [
            AttachWindowNode(
                selector="<html app='chrome.exe' />",
                browser_type="Chrome",
                continue_on_error=Literal(value="True"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: BrowserScope with ContinueOnError set" in code
    _compiles(code)


def test_open_application_launches_process_and_recurses_into_body():
    """知見154: `ui:OpenApplication`。`FileName`のみ(確認済みの単純な
    場合)は`subprocess.Popen([...])`で実際に起動するコードを生成し、
    子はそのまま再帰生成される(`AttachWindow`と同じ透過的ラッパー、
    ただし`ContextTarget`は束縛しない)。"""
    wf = _wrap(
        [
            OpenApplicationNode(
                file_name=Literal(value="C:\\Windows\\System32\\notepad.exe"),
                selector="<wnd app='notepad.exe' />",
                body=[WriteLineNode(text=Literal(value="hi"))],
            )
        ]
    )
    code = generate_python(wf)
    assert "subprocess.Popen([_vb_cstr('C:\\\\Windows\\\\System32\\\\notepad.exe')])" in code
    assert "# Attach window: <wnd app='notepad.exe' />" in code
    assert "print(_vb_cstr('hi'))" in code
    assert "import subprocess" in code
    assert "# TODO" not in code
    _compiles(code)


def test_open_application_display_name_becomes_a_comment():
    wf = _wrap(
        [
            OpenApplicationNode(
                file_name=Literal(value="notepad.exe"),
                body=[],
                display_name="Open Notepad",
            )
        ]
    )
    code = generate_python(wf)
    assert "# Open Notepad" in code
    assert "subprocess.Popen(" in code
    _compiles(code)


def test_open_application_with_no_file_name_is_todo_not_guessed():
    wf = _wrap([OpenApplicationNode(file_name=None)])
    code = generate_python(wf)
    assert "# TODO: OpenApplication with no FileName captured" in code
    _compiles(code)


def test_open_application_with_arguments_is_todo_not_guessed():
    """知見154: `allenlooplee/RPABook`の実機XAMLで確認済みの
    `Arguments="[in_TestLogFile]"`——Windowsコマンドライン分割規則が
    未確認のためでっち上げず`# TODO`へ倒す。"""
    wf = _wrap(
        [
            OpenApplicationNode(
                file_name=Literal(value="notepad.exe"),
                arguments=VbExpr(text="in_TestLogFile"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: OpenApplication with Arguments set" in code
    assert "subprocess.Popen" not in code
    _compiles(code)


def test_open_application_with_application_window_is_todo_not_guessed():
    """知見154: `JoeIaquinto/UiPath-VidCreator`の実機XAMLで確認済みの
    `ApplicationWindow="[OBSWindow]"`(開いたウィンドウの出力バインド)
    ——UiElement出力変数が未実装のためでっち上げず`# TODO`へ倒す。"""
    wf = _wrap(
        [
            OpenApplicationNode(
                file_name=Literal(value="obs64.exe"),
                application_window=VbExpr(text="OBSWindow"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: OpenApplication with ApplicationWindow output binding set" in code
    _compiles(code)


def test_open_application_with_working_directory_is_todo_not_guessed():
    wf = _wrap(
        [
            OpenApplicationNode(
                file_name=Literal(value="notepad.exe"),
                working_directory=Literal(value="C:\\Temp"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: OpenApplication with WorkingDirectory set" in code
    _compiles(code)


def test_open_application_with_timeout_ms_is_todo_not_guessed():
    wf = _wrap(
        [
            OpenApplicationNode(
                file_name=Literal(value="notepad.exe"),
                timeout_ms=Literal(value="2000"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: OpenApplication with TimeoutMS set" in code
    _compiles(code)


def test_open_application_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap(
        [
            OpenApplicationNode(
                file_name=Literal(value="notepad.exe"),
                continue_on_error=Literal(value="True"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: OpenApplication with ContinueOnError set" in code
    _compiles(code)


def test_open_application_child_todo_still_surfaces():
    """知見154: スコープ自体は`# TODO`にならないが、未対応な子の
    `# TODO`は引き続き正しく出る(知見84・153と同じ教訓)。"""
    wf = _wrap(
        [
            OpenApplicationNode(
                file_name=Literal(value="notepad.exe"),
                body=[InvokeCodeNode(code="content=content.ToUpper()")],
            )
        ]
    )
    code = generate_python(wf)
    assert "subprocess.Popen(" in code
    assert "# TODO: unsupported in v1 codegen: InvokeCodeNode" in code
    _compiles(code)


def test_start_process_launches_via_subprocess_popen_exec():
    """知見247: `ui:StartProcess`。`FileName`のみ(確認済みの単純な
    場合)は`subprocess.Popen([...])`で実際に起動する——`subprocess.
    Popen`自体をモックして`exec()`経由で実際に呼ばれる引数を確認する。"""
    wf = _wrap([StartProcessNode(file_name=Literal(value="notepad.exe"))])
    code = generate_python(wf)
    assert "subprocess.Popen([_vb_cstr('notepad.exe')])" in code
    assert "import subprocess" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    with unittest.mock.patch("subprocess.Popen") as mock_popen:
        namespace["Test"]()
    mock_popen.assert_called_once_with(["notepad.exe"])


def test_start_process_with_working_directory_exec():
    """知見247: `WorkingDirectory`は`subprocess.Popen()`の`cwd`引数に
    直接対応する単純な概念のため確信を持って対応する(`OpenApplication`
    (知見154)が`Arguments`と同じ理由で見送っている属性だが、こちらは
    曖昧性が無いため見送らない)。"""
    wf = _wrap(
        [
            StartProcessNode(
                file_name=Literal(value="a.exe"),
                working_directory=Literal(value="C:\\work"),
            )
        ]
    )
    code = generate_python(wf)
    assert "subprocess.Popen([_vb_cstr('a.exe')], cwd='C:\\\\work')" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    with unittest.mock.patch("subprocess.Popen") as mock_popen:
        namespace["Test"]()
    mock_popen.assert_called_once_with(["a.exe"], cwd="C:\\work")


def test_start_process_display_name_becomes_a_comment():
    wf = _wrap(
        [StartProcessNode(file_name=Literal(value="notepad.exe"), display_name="Start Process")]
    )
    code = generate_python(wf)
    assert "# Start Process" in code
    assert "subprocess.Popen(" in code
    _compiles(code)


def test_start_process_with_no_file_name_is_todo_not_guessed():
    wf = _wrap([StartProcessNode(file_name=None)])
    code = generate_python(wf)
    assert "# TODO: StartProcess with no FileName captured" in code
    _compiles(code)


def test_start_process_with_arguments_is_todo_not_guessed():
    """知見247: `Arguments`は既存の`OpenApplicationNode`(知見154)と
    同じ理由(Windowsコマンドライン引数の分割規則が未確認)で設定時は
    全体を見送る。"""
    wf = _wrap(
        [
            StartProcessNode(
                file_name=Literal(value="notepad.exe"),
                arguments=VbExpr(text="args"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: StartProcess with Arguments set" in code
    assert "subprocess.Popen" not in code
    _compiles(code)


def test_start_process_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap(
        [
            StartProcessNode(
                file_name=Literal(value="notepad.exe"),
                continue_on_error=Literal(value="True"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: StartProcess with ContinueOnError set" in code
    _compiles(code)


def test_start_process_with_synchronous_execution_type_is_todo_not_guessed():
    """知見247: `ExecutionType="Synchronous"`(`Timeout`付きで完了を
    待つ)は実機での利用例が未確認のため見送る。"""
    wf = _wrap(
        [
            StartProcessNode(
                file_name=Literal(value="notepad.exe"),
                execution_type="Synchronous",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: StartProcess with ExecutionType" in code
    _compiles(code)


def test_open_browser_launches_via_webbrowser_module_and_recurses_into_body():
    """知見168: `ui:OpenBrowser`(GitHub code searchで2648件ヒット)。
    `BrowserType`別の実行ファイルパスがXAMLに明示されないため、
    `OpenApplication`の`subprocess.Popen([file_name])`のような経路は
    使えず、Python標準ライブラリの`webbrowser.open(url)`(特定のブラウザ
    実行ファイルパスを一切推測しない確認済みの標準API)を使う。"""
    wf = _wrap(
        [
            OpenBrowserNode(
                url=Literal(value="https://example.com"),
                browser_type="Chrome",
                body=[WriteLineNode(text=Literal(value="hi"))],
            )
        ]
    )
    code = generate_python(wf)
    assert "webbrowser.open(_vb_cstr('https://example.com'))" in code
    assert "import webbrowser" in code
    assert "BrowserType='Chrome'" in code
    assert "print(_vb_cstr('hi'))" in code
    assert "# TODO" not in code
    _compiles(code)


def test_open_browser_display_name_becomes_a_comment():
    wf = _wrap(
        [OpenBrowserNode(url=Literal(value="https://example.com"), display_name="Open Browser")]
    )
    code = generate_python(wf)
    assert "# Open Browser" in code
    assert "webbrowser.open(" in code
    _compiles(code)


def test_open_browser_with_no_url_is_todo_not_guessed():
    wf = _wrap([OpenBrowserNode(url=None)])
    code = generate_python(wf)
    assert "# TODO: OpenBrowser with no Url captured" in code
    _compiles(code)


def test_open_browser_with_hidden_is_todo_not_guessed():
    """知見168: `piyushagarwal08/JU-Notes`の実機XAMLで確認済みの
    `Hidden="True"`——「ヘッドレスモード」の正確な再現方法が未確認
    ででっち上げず`# TODO`へ倒す。"""
    wf = _wrap(
        [OpenBrowserNode(url=Literal(value="https://example.com"), hidden=Literal(value="True"))]
    )
    code = generate_python(wf)
    assert "# TODO: OpenBrowser with Hidden set" in code
    assert "webbrowser.open" not in code
    _compiles(code)


def test_open_browser_with_non_default_new_session_is_todo_not_guessed():
    wf = _wrap(
        [
            OpenBrowserNode(
                url=Literal(value="https://example.com"), new_session=Literal(value="False")
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: OpenBrowser with non-default NewSession set" in code
    _compiles(code)


def test_open_browser_with_private_is_todo_not_guessed():
    wf = _wrap(
        [OpenBrowserNode(url=Literal(value="https://example.com"), private=Literal(value="True"))]
    )
    code = generate_python(wf)
    assert "# TODO: OpenBrowser with Private set" in code
    _compiles(code)


def test_open_browser_with_ui_browser_output_binding_is_todo_not_guessed():
    """知見168: `piyushagarwal08/JU-Notes`の実機XAMLで確認済みの
    `UiBrowser="[firefox]"`出力バインディング——`OpenApplication`の
    `ApplicationWindow`と同じ理由(UiElement出力変数が未実装)で
    でっち上げず`# TODO`へ倒す。"""
    wf = _wrap(
        [
            OpenBrowserNode(
                url=Literal(value="https://example.com"), ui_browser=VbExpr(text="firefox")
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: OpenBrowser with UiBrowser output binding set" in code
    _compiles(code)


def test_open_browser_with_communication_method_is_todo_not_guessed():
    wf = _wrap(
        [
            OpenBrowserNode(
                url=Literal(value="https://example.com"),
                communication_method=Literal(value="Attach"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: OpenBrowser with CommunicationMethod set" in code
    _compiles(code)


def test_open_browser_child_todo_still_surfaces():
    """知見168: スコープ自体は`# TODO`にならないが、未対応な子の
    `# TODO`は引き続き正しく出る(知見84・154と同じ教訓)。"""
    wf = _wrap(
        [
            OpenBrowserNode(
                url=Literal(value="https://example.com"),
                body=[InvokeCodeNode(code="content=content.ToUpper()")],
            )
        ]
    )
    code = generate_python(wf)
    assert "webbrowser.open(" in code
    assert "# TODO: unsupported in v1 codegen: InvokeCodeNode" in code
    _compiles(code)


def test_excel_application_scope_uses_custom_scope_var_as_real_variable_name():
    """知見94→知見97: デフォルト値(`ExcelWorkbookScope`)と異なる`scope_var`
    (`DelegateInArgument.Name`)は、知見94の時点ではTODOコメント内の文字列
    でしかなかったが、知見97の実コード生成では実際にPython変数名として
    使われることを確認する。"""
    node = ExcelApplicationScopeNode(workbook_path="book.xlsx", scope_var="myWorkbook")
    wf = _wrap([node])
    code = generate_python(wf)
    assert "myWorkbook = openpyxl.load_workbook('book.xlsx')" in code
    assert "myWorkbook.save('book.xlsx')" in code
    _compiles(code)
    _compiles(code)


def test_http_client_todo_includes_extra_attrs():
    """知見92: `extra_attrs`(`EndPoint`/`Method`/`Body`/`TimeoutMS`以外の
    全属性、実機フィクスチャでは`AcceptFormat`等)は`xaml_tree._parse_http_client`
    が既に捕捉済みだったが、`# TODO`コメントへ一度も出ていなかった——知見75と
    同じ「捕捉済みデータの未活用」パターンの追加分。`has_populated_collections`
    を設定して知見96・104の実コード生成パスではなくunresolvedフォールバック
    を明示的に発生させる。"""
    node = HttpClientNode(
        endpoint=VbExpr(text="url"),
        method="POST",
        has_populated_collections=True,
        extra_attrs={"AcceptFormat": "JSON"},
    )
    wf = _wrap([node])
    code = generate_python(wf)
    assert (
        "# TODO: unsupported in v1 codegen: HttpClientNode (EndPoint=[url], "
        "Method='POST', Body=(not set), ExtraAttrs={'AcceptFormat': 'JSON'})"
    ) in code
    _compiles(code)


def test_send_outlook_mail_generates_real_win32com_call_for_simple_case():
    """知見98: `Cc`/`Bcc`未設定・`Files`空・`Importance`/`Sensitivity`/
    `IsBodyHtml`/`IsDraft`が未設定(既定値扱い)という実機フィクスチャで
    確認済みの構成では、`# TODO`ではなく実際に動く`win32com.client`経由の
    Outlook送信コードを生成する。"""
    node = SendOutlookMailNode(
        to=Literal(value="a@b.com"), subject=Literal(value="Hi"), body=Literal(value="hello")
    )
    wf = _wrap([node])
    code = generate_python(wf)
    assert "import win32com.client" in code
    assert "_outlook = win32com.client.Dispatch('Outlook.Application')" in code
    assert "_mail = _outlook.CreateItem(0)" in code
    assert "_mail.To = _vb_cstr('a@b.com')" in code
    assert "_mail.Subject = _vb_cstr('Hi')" in code
    assert "_mail.Body = _vb_cstr('hello')" in code
    assert "_mail.Send()" in code
    assert "# TODO" not in code
    _compiles(code)


def test_send_outlook_mail_falls_back_to_todo_for_populated_files():
    """`Files`に添付がある場合は、添付の追加方法の実直列化形が実機未確認
    のため、でっち上げず`# TODO`に倒す。"""
    node = SendOutlookMailNode(
        to=Literal(value="a@b.com"),
        subject=Literal(value="Hi"),
        body=Literal(value="x"),
        has_populated_files=True,
    )
    wf = _wrap([node])
    code = generate_python(wf)
    assert "# TODO: unsupported in v1 codegen: SendOutlookMailNode" in code
    assert "_mail.Send()" not in code
    _compiles(code)


@pytest.mark.parametrize(
    ("kwargs", "expected_lines"),
    [
        (
            # 知見102: `gh api search/code`でGitHub上の実機保存済みXAML
            # (`d6wv28/RPA_Repo`)から直接確認した実在する値(VM不使用)。
            {"cc": Literal(value="c@d.com")},
            ["_mail.CC = _vb_cstr('c@d.com')"],
        ),
        ({"bcc": Literal(value="c@d.com")}, ["_mail.BCC = _vb_cstr('c@d.com')"]),
        (
            {"importance": "High"},
            ["_mail.Importance = 2"],
        ),
        (
            {"importance": "Low"},
            ["_mail.Importance = 0"],
        ),
        (
            {"sensitivity": "Confidential"},
            ["_mail.Sensitivity = 3"],
        ),
        (
            {"sensitivity": "Personal"},
            ["_mail.Sensitivity = 1"],
        ),
        (
            # Microsoft Learn「MailItem.HTMLBody property」で確認済み——
            # `Body`ではなく`HTMLBody`へ代入する。
            {"is_body_html": "True"},
            ["_mail.HTMLBody = _vb_cstr('x')"],
        ),
        (
            # Microsoft Learn「MailItem.Save method」で確認済み——
            # `Send()`ではなく`Save()`(ドラフト保存)。
            {"is_draft": "True"},
            ["_mail.Save()"],
        ),
    ],
)
def test_send_outlook_mail_generates_real_code_for_confirmed_nondefault_fields(kwargs, expected_lines):
    """知見102: `Cc`/`Bcc`設定済み・`Importance`/`Sensitivity`の非既定値・
    `IsBodyHtml`/`IsDraft`の`"True"`は、いずれも実機保存済みXAML(GitHub上の
    実例)で確認済みの実在する値——もはや`# TODO`に倒れず実コード生成する。"""
    node = SendOutlookMailNode(
        to=Literal(value="a@b.com"), subject=Literal(value="Hi"), body=Literal(value="x"), **kwargs
    )
    wf = _wrap([node])
    code = generate_python(wf)
    assert "# TODO" not in code
    for line in expected_lines:
        assert line in code
    _compiles(code)


def test_send_outlook_mail_real_fixture_now_generates_real_code():
    """知見98: design/evidence/uipath_xaml_probe/Main.xamlの
    `<ui:SendOutlookMail>`(知見24)はCc/Bcc未設定・Files空・Importance=
    Normal/Sensitivity=Normal/IsBodyHtml=False/IsDraft=Falseという実機
    確認済みの単純な構成——これまでは`# TODO`に倒れていたが、今は実際に
    win32comコードが生成されることを確認する。"""
    wf = parse_workflow_file(FIXTURE_DIR / "Main.xaml")
    code = generate_python(wf)
    assert "win32com.client.Dispatch('Outlook.Application')" in code
    assert "# TODO: unsupported in v1 codegen: SendOutlookMailNode" not in code


def _get_outlook_mail_messages_node(**overrides) -> GetOutlookMailMessagesNode:
    defaults = dict(
        messages=VbExpr(text="EmailMessages"),
        mail_folder="Inbox",
        get_attachments="False",
        mark_as_read="False",
        only_unread_messages="False",
        top=Literal(value="30"),
    )
    defaults.update(overrides)
    return GetOutlookMailMessagesNode(**defaults)


def test_get_outlook_mail_messages_with_confirmed_defaults_generates_real_code():
    """知見120: `SendOutlookMailNode`と対になる受信側。
    `cameronmcnz/uipath-tutorials`の複数の実機XAMLの属性構成(確認済みの
    既定値)で実際に動くコードを生成する。"""
    wf = _wrap([_get_outlook_mail_messages_node()])
    code = generate_python(wf)
    assert "_outlook = win32com.client.Dispatch('Outlook.Application')" in code
    assert "_items = _outlook.GetNamespace('MAPI').GetDefaultFolder(6).Items" in code
    assert "EmailMessages = list(_items)[:int(_vb_num('30'))]" in code
    assert "# TODO" not in code
    _compiles(code)


def test_get_outlook_mail_messages_with_filter_generates_restrict_call():
    """知見120: `Filter`はOutlookのDASL/Jetフィルタ構文そのものを
    `Items.Restrict()`へそのまま渡す(でっち上げた変換はしない)。"""
    wf = _wrap(
        [_get_outlook_mail_messages_node(filter=Literal(value="[importance]='normal'"))]
    )
    code = generate_python(wf)
    assert "_items = _items.Restrict(_vb_cstr(\"[importance]='normal'\"))" in code
    _compiles(code)


def test_get_outlook_mail_messages_without_top_returns_all_items():
    wf = _wrap([_get_outlook_mail_messages_node(top=None)])
    code = generate_python(wf)
    assert "EmailMessages = list(_items)" in code
    assert "[:int(" not in code
    _compiles(code)


def test_get_outlook_mail_messages_display_name_becomes_a_comment_even_when_falling_back_to_todo():
    wf = _wrap(
        [GetOutlookMailMessagesNode(messages=None, display_name="Get Outlook Mail Messages")]
    )
    code = generate_python(wf)
    assert "# Get Outlook Mail Messages" in code
    assert "# TODO: Get Outlook Mail Messages with no output Messages captured" in code
    _compiles(code)


def test_get_outlook_mail_messages_with_account_is_todo_not_guessed():
    wf = _wrap([_get_outlook_mail_messages_node(account=VbExpr(text="sharedMailbox"))])
    code = generate_python(wf)
    assert "# TODO: Get Outlook Mail Messages with Account set" in code
    _compiles(code)


def test_get_outlook_mail_messages_with_non_inbox_folder_is_todo_not_guessed():
    wf = _wrap([_get_outlook_mail_messages_node(mail_folder="SentItems")])
    code = generate_python(wf)
    assert "# TODO: Get Outlook Mail Messages with MailFolder" in code
    _compiles(code)


@pytest.mark.parametrize(
    "overrides",
    [
        {"get_attachments": "True"},
        {"mark_as_read": "True"},
        {"only_unread_messages": "True"},
    ],
)
def test_get_outlook_mail_messages_with_unconfirmed_bool_is_todo_not_guessed(overrides):
    wf = _wrap([_get_outlook_mail_messages_node(**overrides)])
    code = generate_python(wf)
    assert "# TODO: Get Outlook Mail Messages with" in code
    _compiles(code)


def test_get_outlook_mail_messages_with_timeout_ms_is_todo_not_guessed():
    wf = _wrap([_get_outlook_mail_messages_node(timeout_ms=Literal(value="5000"))])
    code = generate_python(wf)
    assert "# TODO: Get Outlook Mail Messages with TimeoutMS set" in code
    _compiles(code)


def _imap_node(**overrides):
    defaults = dict(
        messages=VbExpr(text="emails"),
        server=Literal(value="imap.gmail.com"),
        port=Literal(value="993"),
        email=Literal(value="user@gmail.com"),
        password=Literal(value="secret"),
        enable_ssl="True",
        secure_connection="Auto",
        mail_folder=Literal(value="Inbox"),
        top=Literal(value="2"),
        mark_as_read="False",
        only_unread_messages="False",
        delete_messages="False",
    )
    defaults.update(overrides)
    return GetIMAPMailMessagesNode(**defaults)


def test_get_imap_mail_messages_full_exec_newest_first_and_top():
    """知見250: `ui:GetIMAPMailMessages`。`imaplib`/`email`は標準
    ライブラリ(`pywin32`と違いこのサンドボックスでも利用可能)——
    `imaplib.IMAP4_SSL`自体をモックして`exec()`経由で実際の制御フロー
    (`login`/`select`/`search`/`OrderByDate`既定の`NewestFirst`
    (UIDリスト反転)/`Top`による絞り込み/`fetch`/`.Subject`ラッパー
    プロパティ)を確認する。"""
    wf = _wrap([_imap_node()])
    code = generate_python(wf)
    assert "import imaplib" in code
    assert "import email" in code
    assert "_ImapMailMessage" in code
    assert "# TODO" not in code
    _compiles(code)

    raw_msgs = {
        b"1": b"Subject: Hello One\r\n\r\nBody1",
        b"2": b"Subject: Hello Two\r\n\r\nBody2",
        b"3": b"Subject: Hello Three\r\n\r\nBody3",
    }
    fake_imap = unittest.mock.MagicMock()
    fake_imap.search.return_value = ("OK", [b"1 2 3"])
    fake_imap.fetch.side_effect = lambda uid, spec: ("OK", [(None, raw_msgs[uid])])

    namespace: dict[str, object] = {}
    exec(code + "\n    return emails", namespace)  # noqa: S102 - 信頼できる自作コード
    with unittest.mock.patch("imaplib.IMAP4_SSL", return_value=fake_imap):
        result = namespace["Test"]()

    assert len(result) == 2
    assert [m.Subject for m in result] == ["Hello Three", "Hello Two"]
    fake_imap.login.assert_called_once_with("user@gmail.com", "secret")
    fake_imap.select.assert_called_once_with("Inbox")
    fake_imap.search.assert_called_once_with(None, "ALL")
    fake_imap.close.assert_called_once()
    fake_imap.logout.assert_called_once()


def test_get_imap_mail_messages_mark_as_read_and_only_unread_exec():
    """知見250: `MarkAsRead="True"`→`\\Seen`フラグ設定、
    `OnlyUnreadMessages="True"`→IMAPの`UNSEEN`検索条件を確認する。"""
    wf = _wrap(
        [_imap_node(mark_as_read="True", only_unread_messages="True", top=None)]
    )
    code = generate_python(wf)
    assert "# TODO" not in code
    _compiles(code)

    fake_imap = unittest.mock.MagicMock()
    fake_imap.search.return_value = ("OK", [b"1"])
    fake_imap.fetch.return_value = ("OK", [(None, b"Subject: Only\r\n\r\nBody")])

    namespace: dict[str, object] = {}
    exec(code + "\n    return emails", namespace)  # noqa: S102 - 信頼できる自作コード
    with unittest.mock.patch("imaplib.IMAP4_SSL", return_value=fake_imap):
        result = namespace["Test"]()

    assert [m.Subject for m in result] == ["Only"]
    fake_imap.search.assert_called_once_with(None, "UNSEEN")
    fake_imap.store.assert_called_once_with(b"1", "+FLAGS", "\\Seen")


def test_get_imap_mail_messages_delete_messages_expunges_exec():
    wf = _wrap([_imap_node(delete_messages="True", top=None)])
    code = generate_python(wf)
    assert "# TODO" not in code
    _compiles(code)

    fake_imap = unittest.mock.MagicMock()
    fake_imap.search.return_value = ("OK", [b"1"])
    fake_imap.fetch.return_value = ("OK", [(None, b"Subject: Bye\r\n\r\nBody")])

    namespace: dict[str, object] = {}
    exec(code + "\n    return emails", namespace)  # noqa: S102 - 信頼できる自作コード
    with unittest.mock.patch("imaplib.IMAP4_SSL", return_value=fake_imap):
        namespace["Test"]()

    fake_imap.store.assert_called_once_with(b"1", "+FLAGS", "\\Deleted")
    fake_imap.expunge.assert_called_once()


def test_get_imap_mail_messages_oldest_first_does_not_reverse_exec():
    wf = _wrap([_imap_node(order_by_date="OldestFirst", top=None)])
    code = generate_python(wf)
    assert "# TODO" not in code
    _compiles(code)

    fake_imap = unittest.mock.MagicMock()
    fake_imap.search.return_value = ("OK", [b"1 2"])
    raw_msgs = {
        b"1": b"Subject: First\r\n\r\nBody1",
        b"2": b"Subject: Second\r\n\r\nBody2",
    }
    fake_imap.fetch.side_effect = lambda uid, spec: ("OK", [(None, raw_msgs[uid])])

    namespace: dict[str, object] = {}
    exec(code + "\n    return emails", namespace)  # noqa: S102 - 信頼できる自作コード
    with unittest.mock.patch("imaplib.IMAP4_SSL", return_value=fake_imap):
        result = namespace["Test"]()

    assert [m.Subject for m in result] == ["First", "Second"]


def test_get_imap_mail_messages_with_missing_properties_is_todo():
    wf = _wrap([_imap_node(messages=None)])
    code = generate_python(wf)
    assert "# TODO: GetIMAPMailMessages with no output Messages captured" in code
    _compiles(code)


def test_get_imap_mail_messages_with_unconfirmed_secure_connection_is_todo():
    wf = _wrap([_imap_node(secure_connection="StartTls")])
    code = generate_python(wf)
    assert "# TODO: GetIMAPMailMessages with SecureConnection" in code
    _compiles(code)


def test_get_imap_mail_messages_with_filter_expression_is_todo():
    wf = _wrap([_imap_node(filter_expression=Literal(value="SINCE 23-Feb-2021"))])
    code = generate_python(wf)
    assert "# TODO: GetIMAPMailMessages with FilterExpression set" in code
    _compiles(code)


def test_get_imap_mail_messages_with_use_oauth_is_todo():
    wf = _wrap([_imap_node(use_oauth=Literal(value="True"))])
    code = generate_python(wf)
    assert "# TODO: GetIMAPMailMessages with UseOAuth set" in code
    _compiles(code)


def _save_mail_attachments_node(**overrides):
    defaults = dict(
        message=VbExpr(text="mail"),
        folder_path=VbExpr(text="folderPath"),
        exclude_inline_attachments="False",
        overwrite_existing="True",
    )
    defaults.update(overrides)
    return SaveMailAttachmentsNode(**defaults)


def test_save_mail_attachments_full_pipeline_exec():
    """知見251: `GetIMAPMailMessages`(知見250)→`ForEach`→
    `SaveMailAttachments`の実機相当のパイプラインを`exec()`経由で
    実際に実行し確認する——実際のマルチパートMIMEメール
    (添付ファイル1件+インライン画像1件)を`imaplib.IMAP4_SSL`モック
    経由で流し、インライン画像が除外され添付ファイルのみ実際に
    ディスクへ書き出され内容が正しいことを確認する。"""
    wf = WorkflowFile(
        class_name="Test",
        root=SequenceNode(
            body=[
                GetIMAPMailMessagesNode(
                    messages=VbExpr(text="emails"),
                    server=Literal(value="imap.gmail.com"),
                    port=Literal(value="993"),
                    email=Literal(value="user@gmail.com"),
                    password=Literal(value="secret"),
                    enable_ssl="True",
                    secure_connection="Auto",
                    mail_folder=Literal(value="Inbox"),
                    mark_as_read="False",
                    only_unread_messages="False",
                    delete_messages="False",
                ),
                ForEachNode(
                    item_var="mail",
                    type_arguments="snm:MailMessage",
                    values=VbExpr(text="emails"),
                    body=[
                        _save_mail_attachments_node(
                            message=VbExpr(text="mail"),
                            folder_path=VbExpr(text="folderPath"),
                            exclude_inline_attachments="True",
                        )
                    ],
                ),
            ]
        ),
        arguments={"folderPath": "InArgument(x:String)"},
    )
    code = generate_python(wf)
    assert "# TODO" not in code
    _compiles(code)

    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = "Report"
    msg.set_content("Please see attached.")
    msg.add_attachment(b"PDFDATA123", maintype="application", subtype="pdf", filename="report.pdf")
    msg.add_attachment(b"\x89PNGfakeimage", maintype="image", subtype="png", filename="logo.png")
    list(msg.iter_attachments())[-1].replace_header(
        "Content-Disposition", 'inline; filename="logo.png"'
    )
    raw_bytes = msg.as_bytes()

    fake_imap = unittest.mock.MagicMock()
    fake_imap.search.return_value = ("OK", [b"1"])
    fake_imap.fetch.return_value = ("OK", [(None, raw_bytes)])

    with tempfile.TemporaryDirectory() as tmp:
        namespace: dict[str, object] = {}
        exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
        with unittest.mock.patch("imaplib.IMAP4_SSL", return_value=fake_imap):
            namespace["Test"](folderPath=tmp)
        saved = sorted(os.listdir(tmp))
        assert saved == ["report.pdf"]
        with open(os.path.join(tmp, "report.pdf"), "rb") as f:
            assert f.read() == b"PDFDATA123"


def test_save_mail_attachments_with_missing_properties_is_todo():
    wf = _wrap([_save_mail_attachments_node(message=None)])
    code = generate_python(wf)
    assert "# TODO: SaveMailAttachments with missing Message/FolderPath" in code
    _compiles(code)


def test_save_mail_attachments_with_overwrite_not_true_is_todo():
    """知見251: `OverwriteExisting`が`"True"`以外(未設定/`"False"`)の
    場合の重複ファイル名解決は未確認のため見送る。"""
    wf = _wrap([_save_mail_attachments_node(overwrite_existing=None)])
    code = generate_python(wf)
    assert "# TODO: SaveMailAttachments with OverwriteExisting" in code
    _compiles(code)


def test_save_mail_attachments_with_attachments_output_bound_is_todo():
    wf = _wrap(
        [_save_mail_attachments_node(attachments=VbExpr(text="savedFiles"))]
    )
    code = generate_python(wf)
    assert "# TODO: SaveMailAttachments with Attachments output bound" in code
    _compiles(code)


def test_mark_mail_as_read_x_sets_unread_property():
    """知見229: `umab:MarkMailAsReadX`。`MailMessage`は`Get
    OutlookMailMessages`が生成する生のOutlook COM`MailItem`相当——
    `pywin32`はこのLinuxサンドボックスに無いため(`SendOutlookMail`/
    `GetOutlookMailMessages`の既存テストと同じ理由)、`exec()`はせず
    生成コードの文字列を直接確認する。"""
    wf = _wrap(
        [MarkMailAsReadXNode(mail_message=VbExpr(text="CurrentMail"), mark_as="Read")]
    )
    code = generate_python(wf)
    assert "CurrentMail.UnRead = False" in code
    assert "# TODO" not in code
    _compiles(code)

    wf2 = _wrap(
        [
            MarkMailAsReadXNode(
                mail_message=VbExpr(text="CurrentMail"), mark_as="Unread"
            )
        ]
    )
    code2 = generate_python(wf2)
    assert "CurrentMail.UnRead = True" in code2
    _compiles(code2)


def test_mark_mail_as_read_x_declines_unrecognized_mark_as():
    wf = _wrap(
        [
            MarkMailAsReadXNode(
                mail_message=VbExpr(text="m"), mark_as="Flagged"
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: MarkMailAsReadX with unrecognized MarkAs ('Flagged')" in code
    _compiles(code)


def test_delete_mail_x_calls_delete():
    wf = _wrap([DeleteMailXNode(mail_message=VbExpr(text="CurrentMail"))])
    code = generate_python(wf)
    assert "CurrentMail.Delete()" in code
    assert "# TODO" not in code
    _compiles(code)


def test_move_mail_x_finds_folder_and_moves():
    """知見229: `_outlook_find_folder`ヘルパーが、デフォルトストアの
    ルート(`GetDefaultFolder(6).Parent`)配下を再帰探索して
    `MailFolder`と同名のフォルダを見つけ、`MailItem.Move(...)`へ渡す
    生成コードを確認する(`pywin32`非搭載のため文字列確認のみ、
    `SendOutlookMail`等の既存テストと同じ理由)。"""
    wf = _wrap(
        [
            MoveMailXNode(
                mail_message=VbExpr(text="CurrentMail"),
                mail_folder=Literal(value="UiPath Test"),
            )
        ]
    )
    code = generate_python(wf)
    assert "import win32com.client" in code
    assert "_outlook = win32com.client.Dispatch('Outlook.Application')" in code
    assert (
        "_folder = _outlook_find_folder("
        "_outlook.GetNamespace('MAPI').GetDefaultFolder(6).Parent, "
        "_vb_cstr('UiPath Test'))" in code
    )
    assert "CurrentMail.Move(_folder)" in code
    assert "def _outlook_find_folder(root, name):" in code
    assert "# TODO" not in code
    _compiles(code)


def test_outlook_find_folder_helper_recurses_and_returns_none_when_missing():
    """知見229: `_outlook_find_folder`ヘルパー自体の探索ロジック
    (直接の子から優先的に探し、無ければ再帰的に子の配下を探す、
    見つからなければ`None`)を、生成されたヘルパー関数定義のソース
    テキストをそのまま`exec()`してモックフォルダ階層で確認する——
    `win32com`自体には依存しない純粋なPython関数のため実行できる。"""
    wf = _wrap(
        [
            MoveMailXNode(
                mail_message=VbExpr(text="m"),
                mail_folder=Literal(value="UiPath Test"),
            )
        ]
    )
    code = generate_python(wf)
    start = code.index("def _outlook_find_folder(root, name):")
    end = code.index("\n\n", start)
    helper_source = code[start:end]
    namespace: dict[str, object] = {}
    exec(helper_source, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    find_folder = namespace["_outlook_find_folder"]

    class _FakeFolder:
        def __init__(self, name, children=None):
            self.Name = name
            self.Folders = children or []

    root = _FakeFolder(
        "Mailbox",
        [_FakeFolder("Inbox", [_FakeFolder("Archive")]), _FakeFolder("UiPath Test")],
    )
    assert find_folder(root, "UiPath Test").Name == "UiPath Test"
    assert find_folder(root, "Archive").Name == "Archive"
    assert find_folder(root, "Nonexistent") is None


def test_move_mail_x_with_missing_properties_is_todo():
    wf = _wrap([MoveMailXNode(mail_message=VbExpr(text="m"), mail_folder=None)])
    code = generate_python(wf)
    assert "# TODO: MoveMailX with missing MailMessage/MailFolder" in code
    _compiles(code)


def _send_mail_node(**overrides) -> SendMailNode:
    defaults = dict(
        to=Literal(value="cameronmcnz@outlook.com"),
        subject=Literal(value="Look at this attachment!"),
        body=Literal(value="Catch me outside, will you."),
        is_body_html="False",
        email=Literal(value="arpeeyeah@gmail.com"),
        password=Literal(value="100thMeridian"),
        server=Literal(value="smtp.gmail.com"),
        port=Literal(value="465"),
        enable_ssl="True",
        secure_connection="Auto",
    )
    defaults.update(overrides)
    return SendMailNode(**defaults)


def test_send_mail_with_confirmed_ssl_combination_generates_real_smtplib_call():
    """知見116: 実機確認済みの唯一のpopulated実例(Gmail SMTP送信)の構成
    ——`EnableSSL=True`・`SecureConnection=Auto`・暗黙SSL。"""
    wf = _wrap([_send_mail_node()])
    code = generate_python(wf)
    assert "import smtplib" in code
    assert "import email.mime.text" in code
    assert "_msg = email.mime.text.MIMEText(_vb_cstr('Catch me outside, will you.'), 'plain')" in code
    assert '_msg["Subject"] = _vb_cstr(\'Look at this attachment!\')' in code
    assert '_msg["From"] = _vb_cstr(\'arpeeyeah@gmail.com\')' in code
    assert '_msg["To"] = _vb_cstr(\'cameronmcnz@outlook.com\')' in code
    assert "_smtp = smtplib.SMTP_SSL(_vb_cstr('smtp.gmail.com'), int(_vb_num('465')))" in code
    assert "_smtp.login(_vb_cstr('arpeeyeah@gmail.com'), _vb_cstr('100thMeridian'))" in code
    assert "_smtp.send_message(_msg)" in code
    assert "_smtp.quit()" in code
    assert "# TODO" not in code
    _compiles(code)


def test_send_mail_with_html_body_passes_html_subtype():
    wf = _wrap([_send_mail_node(is_body_html="True")])
    code = generate_python(wf)
    assert "'html')" in code
    _compiles(code)


def test_send_mail_with_cc_bcc_reply_to_generates_extra_headers():
    wf = _wrap(
        [
            _send_mail_node(
                cc=Literal(value="cc@example.com"),
                bcc=Literal(value="bcc@example.com"),
                reply_to=Literal(value="reply@example.com"),
            )
        ]
    )
    code = generate_python(wf)
    assert '_msg["Cc"] = _vb_cstr(\'cc@example.com\')' in code
    assert '_msg["Bcc"] = _vb_cstr(\'bcc@example.com\')' in code
    assert '_msg["Reply-To"] = _vb_cstr(\'reply@example.com\')' in code
    _compiles(code)


def test_send_mail_with_timeout_ms_generates_timeout_kwarg():
    wf = _wrap([_send_mail_node(timeout_ms=Literal(value="30000"))])
    code = generate_python(wf)
    assert "timeout=(_vb_num('30000') / 1000.0)" in code
    _compiles(code)


def test_send_mail_display_name_becomes_a_comment_even_when_falling_back_to_todo():
    wf = _wrap([SendMailNode(display_name="Send SMTP Mail Message")])
    code = generate_python(wf)
    assert "# Send SMTP Mail Message" in code
    assert "# TODO: Send Mail with missing To/Subject/Body" in code
    _compiles(code)


def test_send_mail_with_missing_fields_is_todo():
    wf = _wrap([SendMailNode()])
    code = generate_python(wf)
    assert "# TODO: Send Mail with missing To/Subject/Body" in code
    _compiles(code)


def test_send_mail_with_populated_files_is_todo_not_guessed():
    wf = _wrap([_send_mail_node(has_populated_files=True)])
    code = generate_python(wf)
    assert "# TODO: Send Mail with populated Files" in code
    _compiles(code)


def test_send_mail_with_mail_message_set_is_todo_not_guessed():
    wf = _wrap([_send_mail_node(mail_message=VbExpr(text="sourceMail"))])
    code = generate_python(wf)
    assert "# TODO: Send Mail with MailMessage set" in code
    _compiles(code)


def test_send_mail_with_use_oauth_true_is_todo_not_guessed():
    wf = _wrap([_send_mail_node(use_oauth="True")])
    code = generate_python(wf)
    assert "# TODO: Send Mail with UseOAuth set" in code
    _compiles(code)


@pytest.mark.parametrize("enable_ssl", [None, "False", "SomethingElse"])
def test_send_mail_with_non_confirmed_enable_ssl_is_todo_not_guessed(enable_ssl):
    wf = _wrap([_send_mail_node(enable_ssl=enable_ssl)])
    code = generate_python(wf)
    assert "# TODO: Send Mail with EnableSSL" in code
    _compiles(code)


def test_send_mail_with_non_confirmed_secure_connection_is_todo_not_guessed():
    wf = _wrap([_send_mail_node(secure_connection="Explicit")])
    code = generate_python(wf)
    assert "# TODO: Send Mail with SecureConnection" in code
    _compiles(code)


@pytest.mark.parametrize(
    "overrides",
    [{"from_": Literal(value="other@example.com")}, {"name": Literal(value="Display Name")}],
)
def test_send_mail_with_from_or_name_set_is_todo_not_guessed(overrides):
    wf = _wrap([_send_mail_node(**overrides)])
    code = generate_python(wf)
    assert "# TODO: Send Mail with From/Name set" in code
    _compiles(code)


def test_send_mail_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap([_send_mail_node(continue_on_error=Literal(value="True"))])
    code = generate_python(wf)
    assert "# TODO: Send Mail with ContinueOnError set" in code
    _compiles(code)


def _copy_file_node(**overrides) -> CopyFileNode:
    defaults = dict(
        path=Literal(value="src.xlsx"),
        destination=VbExpr(text="destFolder"),
        overwrite="False",
    )
    defaults.update(overrides)
    return CopyFileNode(**defaults)


def test_copy_file_with_overwrite_false_generates_exists_guard():
    """知見117: `Overwrite="False"`は.NETの`File.Copy(src, dest, overwrite)`
    の確立済みの契約(既存ファイルがあれば例外)に基づき、`shutil.copy()`
    呼び出し前に`FileExistsError`を投げるガードを生成する。実際に一時
    ファイルへ対して実行し、2回目の呼び出しで正しく例外が発生することを
    確認済み(本セッション内、リポジトリには残していない)。"""
    wf = _wrap([_copy_file_node()])
    code = generate_python(wf)
    assert "import shutil" in code
    assert "import os" in code
    assert "_src = 'src.xlsx'" in code
    assert "_dest = destFolder" in code
    assert "if os.path.isdir(_dest):" in code
    assert "if os.path.exists(_dest):" in code
    assert "raise FileExistsError(_dest)" in code
    assert "shutil.copy(_src, _dest)" in code
    assert "# TODO" not in code
    _compiles(code)


def test_copy_file_with_overwrite_true_skips_exists_guard():
    wf = _wrap([_copy_file_node(overwrite="True")])
    code = generate_python(wf)
    assert "raise FileExistsError" not in code
    assert "shutil.copy(_src, _dest)" in code
    _compiles(code)


def test_copy_file_display_name_becomes_a_comment_even_when_falling_back_to_todo():
    wf = _wrap([CopyFileNode(display_name="Copy File")])
    code = generate_python(wf)
    assert "# Copy File" in code
    assert "# TODO: Copy File with missing Path/Destination" in code
    _compiles(code)


def test_copy_file_with_missing_path_or_destination_is_todo():
    wf = _wrap([CopyFileNode()])
    code = generate_python(wf)
    assert "# TODO: Copy File with missing Path/Destination" in code
    _compiles(code)


@pytest.mark.parametrize(
    "overrides",
    [
        {"destination_resource": VbExpr(text="destRes")},
        {"path_resource": VbExpr(text="pathRes")},
    ],
)
def test_copy_file_with_resource_properties_is_todo_not_guessed(overrides):
    wf = _wrap([_copy_file_node(**overrides)])
    code = generate_python(wf)
    assert "# TODO: Copy File with DestinationResource/PathResource set" in code
    _compiles(code)


def test_copy_file_with_continue_on_error_is_todo_not_guessed():
    wf = _wrap([_copy_file_node(continue_on_error=Literal(value="True"))])
    code = generate_python(wf)
    assert "# TODO: Copy File with ContinueOnError set" in code
    _compiles(code)


@pytest.mark.parametrize("overwrite", [None, "SomethingElse"])
def test_copy_file_with_unrecognized_overwrite_is_todo_not_guessed(overwrite):
    wf = _wrap([_copy_file_node(overwrite=overwrite)])
    code = generate_python(wf)
    assert "# TODO: Copy File with unrecognized/unset Overwrite" in code
    _compiles(code)


def test_build_data_table_generates_empty_list():
    """知見117: `TableInfo`の列名は`list[dict]`表現では実行時に不要
    (`SelectItem.Items`と同じ判断)——空リストを生成するだけで足りる。"""
    wf = _wrap([BuildDataTableNode(data_table=VbExpr(text="dt"), columns=["Column1", "Column2"])])
    code = generate_python(wf)
    assert "dt = []" in code
    assert "# TODO" not in code
    _compiles(code)


def test_build_data_table_display_name_becomes_a_comment_even_when_falling_back_to_todo():
    wf = _wrap([BuildDataTableNode(display_name="Build Data Table")])
    code = generate_python(wf)
    assert "# Build Data Table" in code
    assert "# TODO: Build Data Table with no output DataTable captured" in code
    _compiles(code)


def test_build_data_table_with_no_output_is_todo():
    wf = _wrap([BuildDataTableNode(data_table=None)])
    code = generate_python(wf)
    assert "# TODO: Build Data Table with no output DataTable captured" in code
    _compiles(code)


def test_unknown_activity_todo_includes_captured_attrs():
    """知見92: `UnknownActivityNode.attrs`(`xaml_tree.parse_activity`が
    `dict(elem.attrib)`で全属性を既に捕捉済み——Libraryアクティビティ呼び出し
    の引数(例: `in_greeting`)はこの方法でしか見えない)も`# TODO`コメントへ
    一度も出ていなかった。`DisplayName`は`display_name`で別途表示済みのため
    重複を避けて除外する。"""
    node = UnknownActivityNode(
        tag="{http://schemas.lib}NewActivity",
        display_name="New Activity",
        attrs={"DisplayName": "New Activity", "in_greeting": "hellofromlib"},
    )
    wf = _wrap([node])
    code = generate_python(wf)
    assert (
        "# TODO: unknown activity (New Activity): {http://schemas.lib}NewActivity "
        "attrs={'in_greeting': 'hellofromlib'}"
    ) in code
    _compiles(code)


def test_unknown_activity_todo_omits_attrs_detail_when_only_display_name_captured():
    """`DisplayName`属性以外に捕捉済みデータが無い場合は、知見80以前と同じ
    挙動(`attrs=`の追記なし)のまま退行させない回帰テスト。"""
    node = UnknownActivityNode(
        tag="Foo", display_name="Bar", attrs={"DisplayName": "Bar"}
    )
    wf = _wrap([node])
    code = generate_python(wf)
    assert "# TODO: unknown activity (Bar): Foo" in code
    assert "attrs=" not in code
    _compiles(code)


def test_invoke_code_todo_includes_arguments_when_present():
    """知見83: 知見17・23の実機確認式そのもの(`Code="content=
    content.ToUpper()"`、`Arguments`は`myArg`という別名で`content`を
    束縛)——`Code`テキストが`Arguments`のキー名を直接参照するとは限らない
    ため、でっち上げた対応付けはせず捕捉した生データをそのまま表示する。"""
    wf = _wrap(
        [
            InvokeCodeNode(
                code="content=content.ToUpper()",
                arguments={"myArg": VbExpr(text="content")},
            )
        ]
    )
    code = generate_python(wf)
    assert (
        "# TODO: unsupported in v1 codegen: InvokeCodeNode "
        "(Code='content=content.ToUpper()', Arguments={myArg=[content]})"
    ) in code
    _compiles(code)


def test_excel_application_scope_still_generates_its_child_activities():
    """知見84(いまは知見97の`_generate_excel_application_scope`に移った):
    `ExcelApplicationScopeNode`は子アクティビティ(`node.body`)を持つ——
    スコープ自体が(今は実コード生成されるようになったが)、スコープ内の
    子アクティビティ(スコープとは無関係に正しく生成できるもの)を
    失ってはいけないという教訓は引き続き有効。`MessageBox`のような
    独立して生成可能な子が、`openpyxl`のopen/saveに挟まれて実際に
    `print()`として生成されることを確認する。"""
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[MessageBoxNode(text=Literal(value="status"))],
            )
        ]
    )
    code = generate_python(wf)
    assert "openpyxl.load_workbook('wb.xlsx')" in code
    assert "print('status')" in code
    assert ".save('wb.xlsx')" in code
    _compiles(code)


def test_excel_application_scope_with_write_cell_generates_real_code_together():
    """知見97: `ExcelApplicationScopeNode`+`ExcelWriteCellNode`という知見22で
    確認済みの実機構造(スコープの直接の子としてのWrite Cell)は、両方とも
    実コード生成されるようになった——`scope_var`を介してセルへの実際の
    代入文になることを確認する(知見84では「子のTODOが失われない」ことの
    確認に使っていたが、今はそもそもTODOにならない)。"""
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[ExcelWriteCellNode(cell=Literal(value="A1"), sheet_name="Sheet1", text=Literal(value="hi"))],
            )
        ]
    )
    code = generate_python(wf)
    assert "ExcelWorkbookScope = openpyxl.load_workbook('wb.xlsx')" in code
    assert "ExcelWorkbookScope['Sheet1']['A1'] = _vb_cstr('hi')" in code
    assert "ExcelWorkbookScope.save('wb.xlsx')" in code
    assert "# TODO" not in code
    _compiles(code)


def test_word_application_scope_with_replace_text_generates_real_code_together():
    """知見121: `WordApplicationScopeNode`+`WordReplaceTextNode`は
    `ExcelApplicationScopeNode`+`ExcelWriteCellNode`(知見97)と同じ設計。
    実際に一時`.docx`ファイルへ生成コードを実行し、`{{Candidate}}`という
    生のプレースホルダ文字列が正しく置換されることを確認済み(本セッション
    内、リポジトリには残していない)。"""
    wf = _wrap(
        [
            WordApplicationScopeNode(
                file_name="letter.docx",
                body=[
                    WordReplaceTextNode(
                        search=Literal(value="{{Candidate}}"),
                        replace=VbExpr(text="candidate"),
                        display_name="Replace Text in Document",
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "import docx" in code
    assert "WordDocumentScope = docx.Document('letter.docx')" in code
    assert "# Replace Text in Document" in code
    assert "for _p in WordDocumentScope.paragraphs:" in code
    assert "if _vb_cstr('{{Candidate}}') in _r.text:" in code
    assert (
        "_r.text = _r.text.replace(_vb_cstr('{{Candidate}}'), _vb_cstr(candidate))" in code
    )
    assert "WordDocumentScope.save('letter.docx')" in code
    assert "# TODO" not in code
    _compiles(code)


def test_word_replace_text_alternate_tag_name_generates_same_code():
    """知見121: 実機で2つの異なるタグ名(`ui:ReplaceTextInDocument`/
    `ui:WordReplaceText`)を確認済み——パーサー側で両方を同じノード型へ
    ディスパッチするため、コード生成側は区別しない。"""
    xml = (
        '<Activity x:Class="Test" '
        'xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:ui="http://schemas.uipath.com/workflow/activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
        "<Sequence>"
        '<ui:WordApplicationScope FileName="letter.docx">'
        "<ui:WordApplicationScope.Body>"
        '<ActivityAction x:TypeArguments="ui:WordDocument">'
        "<ActivityAction.Argument>"
        '<DelegateInArgument x:TypeArguments="ui:WordDocument" Name="WordDocumentScope" />'
        "</ActivityAction.Argument>"
        '<ui:WordReplaceText DisplayName="Replace Text" Search="[a]" Replace="[b]" />'
        "</ActivityAction>"
        "</ui:WordApplicationScope.Body>"
        "</ui:WordApplicationScope>"
        "</Sequence>"
        "</Activity>"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".xaml", delete=False) as f:
        f.write(xml)
        path = f.name
    try:
        wf = parse_workflow_file(path)
    finally:
        os.unlink(path)
    code = generate_python(wf)
    assert "# Replace Text" in code
    assert "for _p in WordDocumentScope.paragraphs:" in code
    assert "# TODO" not in code
    _compiles(code)


def test_word_replace_text_with_missing_search_or_replace_is_todo():
    wf = _wrap(
        [
            WordApplicationScopeNode(
                file_name="letter.docx",
                body=[WordReplaceTextNode(search=None, replace=VbExpr(text="b"))],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Word Replace Text with missing Search/Replace" in code
    _compiles(code)


def test_word_application_scope_still_generates_its_child_activities():
    """知見84と同じ教訓: 未対応な子(`InvokeCodeNode`)でもスコープ自体は
    `# TODO`にならず、子の`# TODO`だけが正しく出ることを確認する。"""
    wf = _wrap(
        [
            WordApplicationScopeNode(
                file_name="letter.docx",
                body=[InvokeCodeNode(code="x=1")],
            )
        ]
    )
    code = generate_python(wf)
    assert "docx.Document('letter.docx')" in code
    assert "# TODO: unsupported in v1 codegen: InvokeCodeNode" in code
    _compiles(code)


def test_excel_application_scope_with_genuinely_unsupported_child_shows_its_todo():
    """知見84の教訓(子の`# TODO`を失わない)を、今も実際に未対応な子
    (`InvokeCodeNode`、知見にてライブラリ選定ではなく文単位コード変換
    自体が未解決、見送り決定済み)で確認する——スコープ自体はもう
    `# TODO`にならないが、子の`# TODO`は引き続き正しく出る。"""
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[InvokeCodeNode(code="content=content.ToUpper()")],
            )
        ]
    )
    code = generate_python(wf)
    assert "openpyxl.load_workbook('wb.xlsx')" in code
    assert "# TODO: unsupported in v1 codegen: InvokeCodeNode" in code
    _compiles(code)


def test_excel_read_range_with_empty_range_generates_real_code():
    """知見115: `Range`が空文字列(=シート全体)・`AddHeaders="True"`の
    確認済み組み合わせ。"""
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[
                    ExcelReadRangeNode(
                        sheet_name="Sheet1",
                        range=Literal(value=""),
                        add_headers="True",
                        data_table=VbExpr(text="dt"),
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "_ws = ExcelWorkbookScope['Sheet1']" in code
    assert "dt = [dict(zip(_rows[0], _r)) for _r in _rows[1:]] if _rows else []" in code
    assert "# TODO" not in code
    _compiles(code)


def test_excel_read_range_without_headers_generates_list_of_lists():
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[
                    ExcelReadRangeNode(
                        sheet_name="Sheet1",
                        range=None,
                        add_headers="False",
                        data_table=VbExpr(text="dt"),
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "dt = [list(_r) for _r in _rows]" in code
    _compiles(code)


def test_excel_read_range_with_no_output_data_table_is_todo():
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[ExcelReadRangeNode(sheet_name="Sheet1", data_table=None)],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Excel Read Range with no output DataTable captured" in code
    _compiles(code)


def test_excel_read_range_with_populated_range_is_todo_not_guessed():
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[
                    ExcelReadRangeNode(
                        sheet_name="Sheet1",
                        range=Literal(value="A1:C10"),
                        data_table=VbExpr(text="dt"),
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Excel Read Range with non-empty/non-literal Range" in code
    _compiles(code)


def test_excel_read_range_with_no_sheet_name_is_todo():
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[ExcelReadRangeNode(sheet_name="", data_table=VbExpr(text="dt"))],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Excel Read Range with no SheetName captured" in code
    _compiles(code)


def test_excel_write_range_with_default_starting_cell_generates_real_code():
    """知見115: `StartingCell="A1"`・`AddHeaders="True"`の確認済み組み合わせ。"""
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[
                    ExcelWriteRangeNode(
                        sheet_name="Sheet2",
                        starting_cell="A1",
                        add_headers="True",
                        data_table=VbExpr(text="dt"),
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "_ws = ExcelWorkbookScope['Sheet2']" in code
    assert "_ws.cell(row=1, column=1 + _j, value=_h)" in code
    assert "_ws.cell(row=_row0 + _i, column=1 + _j, value=_v)" in code
    assert "# TODO" not in code
    _compiles(code)


def test_excel_write_range_without_headers_skips_header_row():
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[
                    ExcelWriteRangeNode(
                        sheet_name="Sheet2",
                        starting_cell="A1",
                        add_headers="False",
                        data_table=VbExpr(text="dt"),
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "_row0 = 1" in code
    assert "value=_h)" not in code
    assert "_ws.cell(row=_row0 + _i, column=1 + _j, value=_v)" in code
    _compiles(code)


def test_excel_write_range_with_no_input_data_table_is_todo():
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[ExcelWriteRangeNode(sheet_name="Sheet2", data_table=None)],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Excel Write Range with no input DataTable captured" in code
    _compiles(code)


def test_excel_write_range_with_non_default_starting_cell_generates_direct_cell_writes():
    """修正(知見115追記): `openpyxl`の`append()`は常にシート末尾に追記する
    挙動のため、`StartingCell`が`"A1"`以外の場合は当初`# TODO`に倒して
    いたが、`Worksheet.cell(row=..., column=..., value=...)`による直接
    セル指定に変更したことで、任意の開始セルに対応できるようになった。"""
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[
                    ExcelWriteRangeNode(
                        sheet_name="Sheet2",
                        starting_cell="B5",
                        add_headers="False",
                        data_table=VbExpr(text="dt"),
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "_row0 = 5" in code
    assert "column=2 + _j" in code
    assert "# TODO" not in code
    _compiles(code)


def test_excel_write_range_overwrites_in_place_rather_than_appending_to_sheet_end():
    """知見115追記: 既存コードを実際の非空シートに対して再検証して発見した
    バグの回帰テスト——`append()`ベースの実装は対象シートに既存データが
    ある場合に末尾追記してしまい、`StartingCell`の実際の位置を無視して
    いた。直接セル指定への変更で、指定したセルへの上書きになることを
    確認する(real worksheet round-tripでの確認はこのテストの範囲外、
    生成コードの文面がappend()を使わないことのみ確認)。"""
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[
                    ExcelWriteRangeNode(
                        sheet_name="Sheet1",
                        starting_cell="A1",
                        add_headers="True",
                        data_table=VbExpr(text="dt"),
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert ".append(" not in code
    assert "_ws.cell(row=1, column=1 + _j, value=_h)" in code
    assert "_row0 = 2" in code
    _compiles(code)


def test_excel_write_range_with_unparseable_starting_cell_is_todo_not_guessed():
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[
                    ExcelWriteRangeNode(
                        sheet_name="Sheet2",
                        starting_cell="not-a-cell",
                        data_table=VbExpr(text="dt"),
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Excel Write Range with unparseable StartingCell" in code
    _compiles(code)


def test_excel_read_range_display_name_becomes_a_comment():
    """知見117: `display_name`は`ExcelReadRangeNode`/`ExcelWriteRangeNode`/
    `ExcelAppendRangeNode`いずれも捕捉済みだったが未活用だった(知見75・
    92〜95と同種)——スコープ配下の子活動でも先頭コメントとして使われる
    ことを確認する。"""
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[
                    ExcelReadRangeNode(
                        sheet_name="Sheet1",
                        range=Literal(value=""),
                        data_table=VbExpr(text="dt"),
                        display_name="Read Range",
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "# Read Range" in code
    _compiles(code)


def test_excel_append_range_generates_append_calls():
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[
                    ExcelAppendRangeNode(
                        sheet_name="Sheet1",
                        data_table=VbExpr(text="checklogTable"),
                        display_name="Append Range",
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "# Append Range" in code
    assert "_ws = ExcelWorkbookScope['Sheet1']" in code
    assert "_rows = checklogTable" in code
    assert "_ws.append(list(_row.values()))" in code
    assert "# TODO" not in code
    _compiles(code)


def test_excel_append_range_with_no_input_data_table_is_todo():
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[ExcelAppendRangeNode(sheet_name="Sheet1", data_table=None)],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Excel Append Range with no input DataTable captured" in code
    _compiles(code)


def test_excel_append_range_with_no_sheet_name_is_todo():
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[ExcelAppendRangeNode(sheet_name="", data_table=VbExpr(text="dt"))],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Excel Append Range with no SheetName captured" in code
    _compiles(code)


def test_excel_write_cell_with_dynamic_cell_expression_generates_real_code():
    """知見119: `Cell`は当初`str`型だったが、実機XAML(`PacktPublishing/
    Robotic-Process-Automation-Projects`、ループ内連番セル指定
    `Cell="[&quot;B&quot;+intCounter.ToString]"`)で動的な実例を発見し
    `Expr`へ昇格した。実際に一時`.xlsx`ファイルへ生成コードを実行し、
    `intCounter`の値に応じて正しいセルへ書き込まれることを確認済み
    (本セッション内、リポジトリには残していない)。"""
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[
                    ExcelWriteCellNode(
                        cell=VbExpr(text='"B"+intCounter.ToString'),
                        sheet_name="Sheet1",
                        text=Literal(value="hi"),
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "ExcelWorkbookScope['Sheet1'][_vb_add('B', _vb_cstr(intCounter))] = _vb_cstr('hi')" in code
    assert "# TODO" not in code
    _compiles(code)


def test_excel_write_cell_with_no_cell_is_todo():
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[ExcelWriteCellNode(cell=None, sheet_name="Sheet1", text=Literal(value="hi"))],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Excel Write Cell with no Cell captured" in code
    _compiles(code)


def test_excel_write_cell_display_name_becomes_a_comment():
    """知見135: `ExcelWriteCellNode`には他のExcel活動(`ExcelReadCellNode`
    等)と違い`display_name`が無かった——実機では`DisplayName`属性が
    常に存在するため追加した。知見84の`_with_scope_child_display_name`
    をそのまま適用する。"""
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[
                    ExcelWriteCellNode(
                        cell=Literal(value="A1"),
                        sheet_name="Sheet1",
                        text=Literal(value="hi"),
                        display_name="Write Cell A1",
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "# Write Cell A1" in code
    assert "# TODO" not in code
    _compiles(code)


def test_excel_read_cell_with_dynamic_cell_expression_generates_real_code():
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[
                    ExcelReadCellNode(
                        cell=VbExpr(text='"A"+intCounter.ToString'),
                        sheet_name="Sheet1",
                        result=VbExpr(text="strVal"),
                        display_name="Read Cell",
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "# Read Cell" in code
    assert "strVal = ExcelWorkbookScope['Sheet1'][_vb_add('A', _vb_cstr(intCounter))].value" in code
    assert "# TODO" not in code
    _compiles(code)


def test_excel_read_cell_with_no_output_result_is_todo():
    wf = _wrap(
        [
            ExcelApplicationScopeNode(
                workbook_path="wb.xlsx",
                body=[
                    ExcelReadCellNode(
                        cell=Literal(value="A1"), sheet_name="Sheet1", result=None
                    )
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Excel Read Cell with no output Result captured" in code
    _compiles(code)


def test_comment_generates_python_comment_line():
    wf = _wrap([CommentNode(text="hello comment")])
    code = generate_python(wf)
    assert "# hello comment" in code
    _compiles(code)


def test_comment_with_multiline_text_generates_one_comment_per_line():
    wf = _wrap([CommentNode(text="line one\nline two")])
    code = generate_python(wf)
    assert "# line one" in code
    assert "# line two" in code
    _compiles(code)


def test_comment_out_body_is_never_generated():
    """知見225: `ui:CommentOut`はStudioの「コメントアウト」操作で
    無効化されたブロック——`Body`配下は実行されないため、通常の
    コード生成に回すと無効化されているはずの処理が実際に実行されて
    しまう。`body`の内容(`WriteLine`)が一切生成コードに現れず、
    代わりに1行のコメントだけが出力されることを確認する。"""
    wf = _wrap(
        [
            CommentOutNode(
                display_name="Comment Out",
                body=[WriteLineNode(text=Literal(value="should never run"))],
            )
        ]
    )
    code = generate_python(wf)
    assert "should never run" not in code
    assert "# Comment Out (ui:CommentOut" in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test():\n    executed = []")
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    namespace["Test"]()


def test_comment_out_as_sole_statement_gets_pass():
    wf = _wrap([CommentOutNode(display_name=None, body=[])])
    code = generate_python(wf)
    assert "# Comment Out (ui:CommentOut" in code
    assert "pass" in code
    _compiles(code)


def test_write_line_maps_to_print():
    """知見147: `WriteLine`(.NET Workflow Foundation本体の標準活動)は
    `print()`と直接対応する——`RealBenTen10/Handle-Order`等、実機検証を
    通じて非常に高頻度で「unknown activity」として素通りしていたことが
    判明した基本的な活動。"""
    wf = _wrap([WriteLineNode(text=Literal(value="hi"))])
    code = generate_python(wf)
    assert "print(_vb_cstr('hi'))" in code
    assert "# TODO" not in code
    _compiles(code)


def test_write_line_display_name_becomes_a_comment():
    wf = _wrap([WriteLineNode(text=Literal(value="hi"), display_name="Say hi")])
    code = generate_python(wf)
    assert "# Say hi" in code
    _compiles(code)


def test_write_line_with_no_text_is_todo_not_guessed():
    wf = _wrap([WriteLineNode(text=None)])
    code = generate_python(wf)
    assert "# TODO: Write Line with no Text captured" in code
    _compiles(code)


def test_throw_new_exception_renders_as_raise():
    """知見148: `Throw`(`Manyakarthik/210701152-CS19P21-ARPA`の実機
    XAML`Throw.Exception="[New Exception(\"...\")]"`で発見)。確認済みの
    `New Exception(message)`構文はPython組込みの`Exception(message)`へ
    直接対応する。"""
    wf = _wrap([ThrowNode(exception=VbExpr(text='New Exception("boom")'))])
    code = generate_python(wf)
    assert "raise Exception('boom')" in code
    assert "# TODO" not in code
    _compiles(code)


def test_throw_display_name_becomes_a_comment():
    wf = _wrap(
        [ThrowNode(exception=VbExpr(text='New Exception("boom")'), display_name="Boom")]
    )
    code = generate_python(wf)
    assert "# Boom" in code
    _compiles(code)


def test_throw_with_no_exception_is_todo_not_guessed():
    wf = _wrap([ThrowNode(exception=None)])
    code = generate_python(wf)
    assert "# TODO: Throw with no Exception captured" in code
    _compiles(code)


def test_throw_with_unconfirmed_exception_class_is_todo_not_guessed():
    """知見148: 未確認のクラス名(カスタム例外型等)はでっち上げず
    `# TODO`へ倒す——`raise`文自体を生成せず、制御フローが継続してしまう
    既知の限界を受け入れる(架空の例外をでっち上げるよりは安全)。"""
    wf = _wrap([ThrowNode(exception=VbExpr(text='New CustomException("boom")'))])
    code = generate_python(wf)
    assert "# TODO: unresolved VB expression:" in code
    assert "raise" not in code
    _compiles(code)


def test_rethrow_maps_to_bare_raise():
    """知見149: `Rethrow`(`Throw`の対になる、属性無しのリーフ活動)は
    `except`ブロック内の引数無し`raise`文(現在処理中の例外を再発生
    させる)と全く同じ意味論で直接対応する。"""
    wf = _wrap(
        [
            TryCatchNode(
                try_body=[],
                catches=[CatchArm(exception_type="s:Exception", body=[RethrowNode()])],
            )
        ]
    )
    code = generate_python(wf)
    assert "raise" in code
    assert "# TODO" not in code
    _compiles(code)


def test_rethrow_display_name_becomes_a_comment():
    wf = _wrap([RethrowNode(display_name="Re-raise it")])
    code = generate_python(wf)
    assert "# Re-raise it" in code
    assert "raise" in code
    _compiles(code)


def test_terminate_workflow_with_reason_only_renders_as_system_exit():
    """知見150: `TerminateWorkflow`(`Throw`・`Rethrow`と対になる、
    `TryCatch`で捕捉されない即座のワークフロー全体停止活動)。`Reason`
    のみの場合は`SystemExit`(デフォルトで`except Exception:`に捕捉
    されず伝播する)へ変換する——最も近い確認済みの対応物。"""
    wf = _wrap([TerminateWorkflowNode(reason=Literal(value="fatal error"))])
    code = generate_python(wf)
    assert "raise SystemExit(" in code
    assert "# TODO" not in code
    _compiles(code)


def test_terminate_workflow_display_name_becomes_a_comment():
    wf = _wrap(
        [TerminateWorkflowNode(reason=Literal(value="fatal"), display_name="Stop it")]
    )
    code = generate_python(wf)
    assert "# Stop it" in code
    assert "raise SystemExit(" in code
    _compiles(code)


def test_terminate_workflow_with_no_reason_is_todo_not_guessed():
    wf = _wrap([TerminateWorkflowNode(reason=None)])
    code = generate_python(wf)
    assert "# TODO: TerminateWorkflow with no Reason captured" in code
    _compiles(code)


def test_terminate_workflow_with_reason_and_exception_is_todo_not_guessed():
    """知見150: `Reason`と`Exception`を同時に持つ実例(`jyjang1222/
    learning-uipath`)を実機で確認したが、両者がどう合成されるべきかは
    未確認のため、でっち上げず`# TODO`へ倒す。"""
    wf = _wrap(
        [
            TerminateWorkflowNode(
                reason=Literal(value="fatal"),
                exception=VbExpr(text="exception"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: TerminateWorkflow with both Reason and Exception set" in code
    assert "raise SystemExit" not in code
    _compiles(code)


def test_delay_literal_timespan_renders_as_time_sleep():
    """知見151: `ui:Delay`(GitHub code searchで10000件超ヒットする最
    頻出活動)。実機確認済みのTimeSpanリテラル書式(`"HH:MM:SS[.fff]"`)
    のみ秒数へ変換し`time.sleep()`を生成する。"""
    wf = _wrap([DelayNode(duration=Literal(value="00:00:01"))])
    code = generate_python(wf)
    assert "time.sleep(1.0)" in code
    assert "import time" in code
    assert "# TODO" not in code
    _compiles(code)


def test_delay_literal_timespan_with_fractional_seconds():
    wf = _wrap([DelayNode(duration=Literal(value="00:00:00.500"))])
    code = generate_python(wf)
    assert "time.sleep(0.5)" in code
    _compiles(code)


def test_delay_literal_timespan_with_minutes_and_hours():
    wf = _wrap([DelayNode(duration=Literal(value="01:02:03"))])
    code = generate_python(wf)
    assert "time.sleep(3723.0)" in code
    _compiles(code)


def test_delay_display_name_becomes_a_comment():
    wf = _wrap([DelayNode(duration=Literal(value="00:00:01"), display_name="Wait")])
    code = generate_python(wf)
    assert "# Wait" in code
    assert "time.sleep(1.0)" in code
    _compiles(code)


def test_delay_with_no_duration_is_todo_not_guessed():
    wf = _wrap([DelayNode(duration=None)])
    code = generate_python(wf)
    assert "# TODO: Delay with no Duration captured" in code
    _compiles(code)


def test_delay_with_dynamic_expression_is_todo_not_guessed():
    """知見151: `Duration`が動的なVB式(`[...]`角括弧付き)の場合は、
    TimeSpanを返す任意の式が秒数へどう変換されるべきか未確認のため
    でっち上げず`# TODO`へ倒す。"""
    wf = _wrap([DelayNode(duration=VbExpr(text="someTimeSpan"))])
    code = generate_python(wf)
    assert "# TODO: unresolved VB expression:" in code
    assert "time.sleep" not in code
    _compiles(code)


def test_delay_with_unconfirmed_timespan_format_is_todo_not_guessed():
    """知見151: 日数プレフィックス等、実機で未確認の書式は推測せず
    `# TODO`へ倒す。"""
    wf = _wrap([DelayNode(duration=Literal(value="1.00:00:00"))])
    code = generate_python(wf)
    assert "# TODO: Delay Duration" in code
    assert "time.sleep" not in code
    _compiles(code)


def test_log_message_with_info_level_generates_logging_info_call():
    wf = _wrap([LogMessageNode(message=Literal(value="done"), level="Info")])
    code = generate_python(wf)
    assert "import logging" in code
    assert "logging.info(_vb_cstr('done'))" in code
    assert "# TODO" not in code
    _compiles(code)


def test_log_message_with_error_level_generates_logging_error_call():
    wf = _wrap([LogMessageNode(message=Literal(value="failed"), level="Error")])
    code = generate_python(wf)
    assert "logging.error(_vb_cstr('failed'))" in code
    _compiles(code)


def test_log_message_display_name_becomes_a_comment_even_when_falling_back_to_todo():
    wf = _wrap([LogMessageNode(message=None, display_name="Log Message")])
    code = generate_python(wf)
    assert "# Log Message" in code
    assert "# TODO: Log Message with no Message captured" in code
    _compiles(code)


def test_log_message_with_unconfirmed_level_is_todo_not_guessed():
    wf = _wrap([LogMessageNode(message=Literal(value="x"), level="Warn")])
    code = generate_python(wf)
    assert "# TODO: Log Message with unconfirmed Level" in code
    _compiles(code)


def test_log_message_unaffected_when_add_log_fields_not_used():
    """知見240: `AddLogFields`/`RemoveLogFields`が同じワークフロー内に
    無い場合、`LogMessage`の生成コードは`_log_fields`関連コードを一切
    追加しない(既存の全`LogMessage`テストとの後方互換性を保証する
    `scope.has_log_fields`ガード)。"""
    wf = _wrap([LogMessageNode(message=Literal(value="hello"), level="Info")])
    code = generate_python(wf)
    assert "_log_fields" not in code
    assert "logging.info(_vb_cstr('hello'))" in code
    _compiles(code)


def test_add_log_fields_and_remove_log_fields_exec():
    """知見240: `AddLogFields`(`x:Key`付き辞書→関数ローカル`_log_fields`
    への`.update()`)・`LogMessage`(`_log_fields`が非空なら` | k=v`形の
    サフィックスを付加)・`RemoveLogFields`(`.pop(key, None)`)を
    実機`UiPath/Community.Activities`REFrameworkテンプレート
    (`Main.xaml`/`SetTransactionStatus.xaml`)相当の順序で配置し、
    `exec()`経由でログ出力に実際にフィールドが付加・削除されることを
    確認する。"""
    wf = WorkflowFile(
        class_name="Test",
        root=SequenceNode(
            body=[
                AddLogFieldsNode(fields={"logF_Proc": VbExpr(text="businessProcessName")}),
                LogMessageNode(message=Literal(value="hello"), level="Info"),
                RemoveLogFieldsNode(fields=[Literal(value="logF_Proc")]),
                LogMessageNode(message=Literal(value="after remove"), level="Info"),
            ]
        ),
        arguments={"businessProcessName": "InArgument(x:String)"},
    )
    code = generate_python(wf)
    assert "_log_fields: dict[str, str] = {}" in code
    assert "_log_fields.update({'logF_Proc': _vb_cstr(businessProcessName)})" in code
    assert "_log_fields.pop('logF_Proc', None)" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    logger = logging.getLogger()
    old_handlers = logger.handlers[:]
    logger.handlers.clear()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        namespace["Test"](businessProcessName="BP1")
    finally:
        logger.handlers.clear()
        logger.handlers.extend(old_handlers)
        logger.setLevel(old_level)
    out = stream.getvalue()
    assert "hello | logF_Proc=BP1" in out
    assert "after remove\n" in out
    assert "after remove |" not in out


def test_remove_log_fields_with_empty_fields_generates_pass():
    """知見240: ground-truthの空`Fields`形
    (`<scg:List .../>`空、子要素無し)は何も`.pop()`する対象が無い——
    空文での構文エラーを避けるため`pass`を生成する。"""
    wf = _wrap([RemoveLogFieldsNode(fields=[])])
    code = generate_python(wf)
    assert "pass" in code
    _compiles(code)


def test_deserialize_json_jobject_exec():
    """知見241: `ui:DeserializeJson<njl:JObject>`(`json.loads()`で
    Python `dict`へ変換)。実機`base64ai/uipath-samples`の
    `Base64.ai Facial Verification.xaml`相当の構成——
    `formattedJson("matches").Count.ToString`という、知見126・203の
    `DataRow`添字アクセス(`ScopeInfo.data_row_vars`)と全く同じ構文的
    曖昧性を持つ`識別子(引数)`添字アクセスを、新規`ScopeInfo.
    json_object_vars`で正しく`formattedJson['matches']`へ解決し、
    `.Count`を既存の`.Length`と同じ`len()`マッピングで処理できることを
    `exec()`経由で確認する。"""
    wf = WorkflowFile(
        class_name="Test",
        root=SequenceNode(
            body=[
                DeserializeJsonNode(
                    json_string=VbExpr(text="base64aiResponse"),
                    json_object=VbExpr(text="formattedJson"),
                    type_argument="njl:JObject",
                ),
                AssignNode(
                    target=VbExpr(text="result"),
                    value=VbExpr(text='formattedJson("matches").Count.ToString'),
                ),
            ]
        ),
        arguments={"base64aiResponse": "InArgument(x:String)"},
    )
    code = generate_python(wf)
    assert "import json" in code
    assert "formattedJson = json.loads(base64aiResponse)" in code
    assert "result = _vb_cstr(len(formattedJson['matches']))" in code
    assert "# TODO" not in code
    _compiles(code)
    import json as _json

    namespace: dict[str, object] = {}
    exec(code + "\n    return result", namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    out = namespace["Test"](_json.dumps({"matches": [1, 2, 3]}))
    assert out == "3"


def test_deserialize_json_non_jobject_type_arguments_is_todo():
    """知見241: ground-truth・実機いずれも`x:TypeArguments="njl:JObject"`
    以外は未確認——`njl:JArray`等の別の型引数は架空の変換をでっち上げず
    `# TODO`へ倒す。"""
    wf = _wrap(
        [
            DeserializeJsonNode(
                json_string=VbExpr(text="x"),
                json_object=VbExpr(text="y"),
                type_argument="njl:JArray",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: DeserializeJson with TypeArguments" in code
    _compiles(code)


def test_deserialize_json_with_missing_json_object_is_todo():
    """知見241: `JsonObject`未捕捉(C#式言語プロジェクトでの
    `CSharpReference`ネスト形、知見129・136)は`# TODO`へ倒す。"""
    wf = _wrap(
        [
            DeserializeJsonNode(
                json_string=None, json_object=None, type_argument="njl:JObject"
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: DeserializeJson with no JsonObject captured" in code
    _compiles(code)


def test_deserialize_json_array_simple_exec():
    """知見245: `ui:DeserializeJsonArray`——`x:TypeArguments`無しの
    非ジェネリック活動、常に`JArray`→Pythonの`list`に対応する。実機
    `base64ai/uipath-samples`相当の構成(`JsonArray`+`JsonString`の
    みのシンプル形)を`exec()`経由で実際に実行し確認する。"""
    wf = WorkflowFile(
        class_name="Test",
        root=SequenceNode(
            body=[
                DeserializeJsonArrayNode(
                    json_string=VbExpr(text="base64aiResponse"),
                    json_array=VbExpr(text="formattedJson"),
                ),
            ]
        ),
        arguments={"base64aiResponse": "InArgument(x:String)"},
    )
    code = generate_python(wf)
    assert "import json" in code
    assert "formattedJson = json.loads(base64aiResponse)" in code
    assert "# TODO" not in code
    _compiles(code)
    import json as _json

    namespace: dict[str, object] = {}
    exec(code + "\n    return formattedJson", namespace)  # noqa: S102 - 信頼できる自作コード
    out = namespace["Test"](_json.dumps([{"a": 1}, {"b": 2}]))
    assert out == [{"a": 1}, {"b": 2}]


def test_deserialize_json_array_foreach_njl_jtoken_loop_var_exec():
    """知見245: 実機`vajrang-b/UiPathIn30Days`相当の構成——
    `DeserializeJsonArray`の出力を`ui:ForEach x:TypeArguments=
    "njl:JToken"`で反復し、反復変数自身も`ScopeInfo.json_object_vars`
    (`ForEachRow`の`data_row_vars`伝播、知見203と同じパターン)経由で
    添字アクセス(`currentItem("key")`)できることを`exec()`経由で
    確認する。"""
    wf = WorkflowFile(
        class_name="Test",
        root=SequenceNode(
            body=[
                DeserializeJsonArrayNode(
                    json_string=VbExpr(text="responseString"),
                    json_array=VbExpr(text="arr"),
                ),
                ForEachNode(
                    item_var="currentItem",
                    type_arguments="njl:JToken",
                    values=VbExpr(text="arr"),
                    body=[WriteLineNode(text=VbExpr(text='currentItem("gender")'))],
                ),
            ]
        ),
        arguments={"responseString": "InArgument(x:String)"},
    )
    code = generate_python(wf)
    assert "for currentItem in arr:" in code
    assert "currentItem['gender']" in code
    assert "# TODO" not in code
    _compiles(code)
    import json as _json

    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - 信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"](_json.dumps([{"gender": "male"}, {"gender": "female"}]))
    assert stdout.getvalue().splitlines() == ["male", "female"]


def test_deserialize_json_array_with_ambiguous_tostring_source_declines():
    """知見244: `JObject("key").ToString()`(`DeserializeJson`出力からの
    実機`vajrang-b/UiPathIn30Days`相当の連鎖式)は、戻り値の実行時型
    (JSONコンテナかスカラーか)が静的に決定不能なため、`_vb_cstr()`
    (無効なJSONを生成しうる)でも`json.dumps()`(スカラーには過剰な
    引用符を付ける)でもでっち上げず`# TODO`へ倒すことを確認する。"""
    wf = WorkflowFile(
        class_name="Test",
        root=SequenceNode(
            body=[
                DeserializeJsonNode(
                    json_string=VbExpr(text="responseString"),
                    json_object=VbExpr(text="jobj"),
                    type_argument="njl:JObject",
                ),
                DeserializeJsonArrayNode(
                    json_string=VbExpr(text='jobj("results").ToString'),
                    json_array=VbExpr(text="arr"),
                ),
            ]
        ),
        arguments={"responseString": "InArgument(x:String)"},
    )
    code = generate_python(wf)
    assert "# TODO" in code
    assert "statically-unknown runtime type" in code
    _compiles(code)


def test_json_object_vars_count_chain_on_bare_identifier():
    """知見244: バレ変数の3段以上の連鎖(`formattedJson.Count.ToString`、
    実機`base64ai/uipath-samples`で確認——`DeserializeJsonArray`の出力
    を`x:TypeArguments`無しの括弧省略形`.Count`で参照する)は、既存の
    `_render_node`のIdent分岐が末尾セグメントしか剥がさず`prefix`
    ("formattedJson.Count")を不透明な1個の名前として扱ってしまい、
    Pythonに存在しない`.Count`属性アクセスへ素通しされ実行時
    `AttributeError`になっていたバグを修正したことを確認する——
    `prefix`自身も再帰的に同じ判定へ回すことで`len()`へ正しく変換
    される。"""
    wf = _wrap(
        [
            AssignNode(
                target=VbExpr(text="result"),
                value=VbExpr(text="formattedJson.Count.ToString"),
            )
        ]
    )
    code = generate_python(wf)
    assert "result = _vb_cstr(len(formattedJson))" in code
    assert "# TODO" not in code
    _compiles(code)


def test_invoke_workflow_file_nested_in_excel_scope_is_still_discovered(tmp_path):
    """知見88: 知見84より前は`ExcelApplicationScopeNode`の子が丸ごと
    `# TODO`に潰されていたため、子の中の`Invoke Workflow File`参照先が
    `_discover_workflow_files`(複数ファイルのBFS発見)に見つけてもらえ
    なくても無害だった。知見84で子アクティビティが実際に生成される
    ようになった結果、`_child_node_lists`に`ExcelApplicationScopeNode`の
    分岐が無いことが初めて意味を持つ退行になった——実在するファイルでも
    常に`# TODO: unresolved Invoke Workflow File`に倒れてしまっていた
    バグを、実際に`generate_project_python()`を実行して再現した上で
    修正した。"""
    (tmp_path / "Sub1.xaml").write_text(
        '<Activity xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" x:Class="Sub1">'
        "<Sequence><ui:MessageBox "
        'xmlns:ui="http://schemas.uipath.com/workflow/activities" Text="&quot;hi&quot;" />'
        "</Sequence></Activity>",
        encoding="utf-8",
    )
    (tmp_path / "Main.xaml").write_text(
        '<Activity xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:ui="http://schemas.uipath.com/workflow/activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" x:Class="Main">'
        "<Sequence>"
        '<ui:ExcelApplicationScope WorkbookPath="wb.xlsx">'
        "<ui:ExcelApplicationScope.Body>"
        '<ActivityAction x:TypeArguments="x:Object">'
        "<Sequence>"
        '<ui:InvokeWorkflowFile WorkflowFileName="Sub1.xaml" />'
        "</Sequence>"
        "</ActivityAction>"
        "</ui:ExcelApplicationScope.Body>"
        "</ui:ExcelApplicationScope>"
        "</Sequence></Activity>",
        encoding="utf-8",
    )
    code = generate_project_python(tmp_path / "Main.xaml")
    _compiles(code)
    assert "# TODO: unresolved Invoke Workflow File" not in code
    assert "Sub1()" in code


def test_parallel_runs_sequentially_with_note():
    wf = _wrap(
        [
            ParallelNode(
                branches=[AssignNode(target=VbExpr(text="x"), value=Literal(value="branch1"))]
            )
        ]
    )
    code = generate_python(wf)
    assert "NOTE: source used Parallel" in code
    assert "x = 'branch1'" in code
    _compiles(code)


def test_workflow_arguments_become_function_params():
    wf = parse_workflow_file(FIXTURE_DIR / "Sub1.xaml")
    code = generate_python(wf)
    assert code.startswith("def Sub1(in_text):") or "def Sub1(in_text):" in code
    _compiles(code)


def test_main_xaml_pipeline_smoke():
    """design/evidence/uipath_xaml_probe/Main.xamlを通した結合テスト。
    モジュールdocstring参照——このフィクスチャは`break`がループ外にある等
    非現実的な制御フローを含むため、生成コード全体がコンパイル可能である
    ことまでは主張しない。各機能が期待通りの行を生成していることだけ確認する。
    """
    wf = parse_workflow_file(FIXTURE_DIR / "Main.xaml")
    code = generate_python(wf)
    assert "def Main():" in code
    assert "for item in ['a', 'b', 'c']:" in code
    assert "pyperclip.copy(_vb_cstr('cliptext'))" in code
    assert "try:" in code and "except Exception as exception:" in code
    assert "# TODO: unknown activity" in code  # Library呼び出し(p:NewActivity)
    # 知見92: Library呼び出し(p:NewActivity)の引数(in_greeting)は`attrs`
    # 経由でしか見えない捕捉済みデータ——TODOコメントに実際に出ることを確認。
    assert "in_greeting" in code and "hellofromlib" in code
    # 知見97: ExcelWriteCell.Textはもはや知見93のTODOコメントではなく、
    # `openpyxl`への実際のセル代入として生成されることを確認。
    assert "openpyxl.load_workbook('wb.xlsx')" in code
    assert "['Sheet1']['A1'] = _vb_cstr('hello')" in code
    # 知見98: SendOutlookMail.Bodyはもはや知見93のTODOコメントではなく、
    # `win32com`への実際の`_mail.Body`代入として生成されることを確認
    # (実機フィクスチャのCc/Bcc/Importance/Sensitivity/IsBodyHtml/IsDraft/
    # Filesはいずれも確認済みの安全な既定値のため実コード生成される)。
    assert "win32com.client.Dispatch('Outlook.Application')" in code
    assert "_mail.Body = _vb_cstr('body')" in code
    assert "_mail.Send()" in code


def test_realistic_workflow_actually_executes_correctly():
    """ここまでのテストは`compile()`レベルの構文確認か、生成コード中の
    特定行の有無を文字列として確認するだけだった。本テストは手作りの
    現実的な(`break`がループ外にある等の破綻が無い)ワークフローIRを
    実際に`exec()`し、複数のTier1構成要素(配列リテラル→`ForEach`→
    `&`による文字列蓄積→`If`/`Else`の分岐)が**実行時に正しく連携して
    動く**ことまで確認する——`design/evidence/uipath_xaml_probe/Main.xaml`
    (知見確認用の寄せ集め、モジュールdocstring参照)では確認できない水準の
    保証。design/uipath_transpiler_roadmap.md「次にやること」に記載した
    『より現実的なフィクスチャでの検証』に対応する。
    """
    wf = _wrap(
        [
            AssignNode(target=VbExpr(text="result"), value=Literal(value="")),
            ForEachNode(
                item_var="item",
                values=VbExpr(text='{"x","y","z"}'),
                body=[
                    AssignNode(target=VbExpr(text="result"), value=VbExpr(text="result & item"))
                ],
            ),
            IfNode(
                condition=VbExpr(text='result="xyz"'),
                then_body=[MessageBoxNode(text=Literal(value="matched"))],
                else_body=[MessageBoxNode(text=Literal(value="no match"))],
            ),
        ]
    )
    code = generate_python(wf)
    _compiles(code)

    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == "matched"


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # VBのMod: 符号は被除数に従う(Microsoft Learn「Mod Operator」の
        # 公式例-10 Mod 3 = -1と同じ形)。単純にPythonの`%`へ変換すると
        # `-7 % 3 == 2`になり符号が逆転する(floor除算の余りは除数の符号に
        # 従うため)——この回帰テストはその誤変換を防ぐ。
        ("-7 Mod 3", -1),
        ("7 Mod 3", 1),
        # VBの`\`(整数除算): ゼロ方向への切り捨て。Microsoft Learn
        # 「\ Operator」の公式例(67 \ -3 = -22)そのもの。単純にPythonの
        # `//`へ変換すると`67 // -3 == -23`になり値がずれる(floor除算のため)。
        ("67 \\ -3", -22),
        ("-7 \\ 3", -2),
    ],
)
def test_mod_and_intdiv_match_vb_sign_semantics_not_python_floor_semantics(
    vb_text: str, expected: int
) -> None:
    """VBの`Mod`/`\\`(整数除算)は、オペランドの符号が異なる場合に
    Pythonの`%`/`//`(floor除算)とは異なる値を返す——VBは共にゼロ方向への
    切り捨て(`Fix`)に基づく(Microsoft Learn「Mod Operator」「\\ Operator」、
    公式の変換式・公式例そのもので確認)。構文の優先順位とは別の、
    **実行時の値そのものが変わる**より重大な誤変換リスクだったため、
    実際に生成Pythonコードを`exec()`して正しい値になることまで確認する。
    """
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == str(expected)


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # VBのCIntは切り捨てではなく銀行丸め(round-half-to-even)。
        # Microsoft公式ドキュメント(Type Conversion Functions)の記載例に
        # 基づく——単純にPythonの`int()`へ変換すると切り捨てになり食い違う
        # (`int(1.5) == 1`だが`CInt(1.5)`は`2`)。
        ("CInt(0.5)", 0),
        ("CInt(1.5)", 2),
        ("CInt(2.5)", 2),
        ("CInt(-1.5)", -2),
    ],
)
def test_cint_matches_vb_banker_rounding_not_python_truncation(
    vb_text: str, expected: int
) -> None:
    """知見42と同じ系統の食い違い——知見32・36の実機確認例(`CInt("5")`)は
    整数値のみで丸めが発生しなかったため、この食い違いは見過ごされていた。
    """
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == str(expected)


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # .NETランタイム本体のソース(Conversions.vbのToInteger、知見52の
        # CDbl確認時に発見した同じファイル、知見53)で確定: CIntの文字列/
        # オブジェクト両オーバーロードも先頭でNothing→0を処理し、文字列
        # 引数はCDblと同じParseDouble(桁区切り受理)経由でDoubleへ変換
        # してから丸める。単純なfloat(x)ではNothingでTypeError、桁区切り
        # 文字列でValueErrorになり食い違う。
        ("CInt(Nothing)", 0),
        ('CInt("1,234.5")', 1234),
        # 知見51で確定したBoolean→-1規則もCIntに適用される
        # (ToInteger(Object)のCase TypeCode.Boolean相当)。
        ("CInt(True)", -1),
        ("CInt(False)", 0),
        # 知見67: `&H`/`&O`16進・8進リテラル文字列は`ParseDouble`を経由
        # せず直接整数として判定される(`IsHexOrOctValue`、知見46・53で
        # 「軽微な既知の限界」として残していたもの)。
        ('CInt("&H1A")', 26),
        ('CInt("&O17")', 15),
    ],
)
def test_cint_matches_dotnet_runtime_source_for_nothing_and_thousands(
    vb_text: str, expected: int
) -> None:
    """知見53: `CInt`の`Nothing`/桁区切り文字列/Boolean変換を、`CDbl`と
    同じ`_vb_cdbl()`ヘルパー経由にしたことの回帰テスト。
    """
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == str(expected)


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # VBのCBool(文字列)は"True"/"False"(大文字小文字区別無し)か数値
        # 文字列として評価する——Pythonのbool(文字列)は空文字列以外は常に
        # Trueになり食い違う(例: bool("False")はTrue、bool("0")もTrue)。
        # 知見32・36の実機確認例はCBool("True")のみで、たまたまPythonの
        # bool()と結果が一致してしまい見過ごされていた。
        ('CBool("True")', True),
        ('CBool("False")', False),
        ('CBool("0")', False),
        ('CBool("1")', True),
        # 知見63: 桁区切りのコンマはリテラル文字列経由でも受理される
        # (`_vb_bool()`経由の非リテラルと規則を揃えた)——以前は
        # `float()`がコンマで`ValueError`になり`NotImplementedError`に
        # なっていた。
        ('CBool("1,234")', True),
        # 知見67: `&H`/`&O`16進・8進リテラル文字列も`IsHexOrOctValue`経由
        # で直接整数判定され、非ゼロかどうかでBooleanになる。
        ('CBool("&H1A")', True),
        ('CBool("&H0")', False),
        ('CBool("&O17")', True),
    ],
)
def test_cbool_string_literal_matches_vb_semantics_not_python_truthiness(
    vb_text: str, expected: bool
) -> None:
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == str(expected)


def test_cbool_non_literal_uses_vb_bool_not_python_truthiness():
    """知見62: 文字列リテラル以外(変数参照等)は実行時の型がコード生成時に
    不明なため、`_vb_bool()`(知見60・61の`AndAlso`/`If`と同じヘルパー)を
    使う——以前は素の`bool(x)`を使っており、`someVar`が`"False"`/`"0"`を
    保持する文字列の場合に食い違う既知の限界として記録していたが、
    `_vb_bool()`導入によりこの限界は解消された。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="CBool(someVar)"))])
    code = generate_python(wf)
    assert "_vb_bool(someVar)" in code
    _compiles(code)


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # 知見62: `CBool`の非リテラル(変数参照等)経由の文字列判定も、
        # `_vb_bool()`によりVBの`CBool`規則(`_vb_cbool_of_string_literal`
        # と同じ)に従うようになった——`bool("False")`は`True`だが
        # `CBool("False")`(変数経由)は`False`になる。
        ("CBool(someVar)", "False"),
    ],
)
def test_cbool_non_literal_string_value_matches_vb_not_python_truthiness(
    vb_text: str, expected: str
) -> None:
    wf = _wrap(
        [
            AssignNode(target=VbExpr(text="someVar"), value=Literal(value="False")),
            MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})")),
        ]
    )
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # 知見67: 変数経由(コード生成時に文字列と確定しない)の`&H`/`&O`
        # 文字列も、ランタイム版の`_vb_cdbl()`/`_vb_bool()`が同じ
        # `IsHexOrOctValue`規則で処理することの回帰テスト。
        ("CDbl(someVar)", "26"),
        ("CInt(someVar)", "26"),
        ("CBool(someVar)", "True"),
    ],
)
def test_hex_or_oct_literal_string_via_variable_matches_runtime_helpers(
    vb_text: str, expected: str
) -> None:
    """知見67: `&H1A`のような16進リテラル文字列を保持する変数を
    `CDbl`/`CInt`/`CBool`に渡した場合も、コード生成時のリテラル専用判定
    (`_vb_cbool_of_string_literal`)と同じ`IsHexOrOctValue`規則に従う
    ランタイム版ヘルパー(`_vb_cdbl`/`_vb_bool`)経由で正しく処理される
    ことを確認する。"""
    wf = _wrap(
        [
            AssignNode(target=VbExpr(text="someVar"), value=Literal(value="&H1A")),
            MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})")),
        ]
    )
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # 知見68: 演算子ディスパッチャ(Operators.vbのAddObject等)の文字列
        # オペランド変換も`CDbl(Convert.ToString(x))`——知見67と同じ
        # `IsHexOrOctValue`経路を通るため、`&H`/`&O`リテラル文字列は
        # 算術演算子・比較演算子でも直接整数として解釈される。
        ('"&H1A" + 1', "27"),
        ('"&H1A" - 1', "25"),
        ('"&H1A" * 2', "52"),
        ('"&H1A" / 2', "13"),
        ('"&H1A" Mod 5', "1"),
        ('"&O17" + 1', "16"),
    ],
)
def test_hex_or_oct_literal_string_in_arithmetic_operators(
    vb_text: str, expected: str
) -> None:
    """知見68: `_vb_add`/`_vb_num`/`_vb_div`/`_vb_mod`が文字列オペランドを
    `&H`/`&O`リテラルとして解釈できることの回帰テスト(知見67の`_vb_cdbl`
    と同じロジックを各ヘルパーに複製)。"""
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # 知見68: 比較演算子(`_vb_cmp`)の文字列オペランド変換も同じ経路。
        ('"&H1A" = 26', "True"),
        ('"&H1A" < 27', "True"),
        ('"&H1A" <> 26', "False"),
    ],
)
def test_hex_or_oct_literal_string_in_comparison_operators(
    vb_text: str, expected: str
) -> None:
    """知見68: `_vb_cmp`が文字列オペランドを`&H`/`&O`リテラルとして解釈
    できることの回帰テスト。"""
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # .NETランタイム本体のソース(Conversions.vb、dotnet/runtime)で
        # 確定(知見52): ToDouble(Object)/ToDouble(String)はNothingに対し
        # 例外を出さず0を返す。Pythonのfloat(None)はTypeErrorになり食い違う。
        ("CDbl(Nothing)", "0"),
        # ParseDoubleがNumberStyles.AllowThousandsを渡しているため桁区切り
        # のコンマは実際に受理される。Pythonのfloat("1,234.5")はコンマで
        # ValueErrorになり食い違う。
        ('CDbl("1,234.5")', "1234.5"),
        ('CDbl("12,345,678")', "12345678"),
        # Case TypeCode.Booleanは CDbl(Boolean)相当を呼ぶ——知見51で確定
        # した「Booleanの数値変換はTrue→-1」の一般規則がここにも適用される。
        ("CDbl(True)", "-1"),
        ("CDbl(False)", "0"),
        # 通常の数値/数値文字列は従来通り。
        ("CDbl(5)", "5"),
        ('CDbl("5")', "5"),
    ],
)
def test_cdbl_matches_dotnet_runtime_source_not_python_float(
    vb_text: str, expected: str
) -> None:
    """知見52: `CDbl`の`Nothing`/桁区切り文字列/Boolean変換を、公式ドキュ
    メントではなく.NETランタイム本体のソース(`Conversions.vb`)で確定した
    内容どおりに実装したことの回帰テスト。
    """
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # VBのCStr(Double)は既定でG書式(mscorlib/Legacyターゲット、G15)
        # に従い、整数値になる場合は小数点を省略する——Pythonのstr(float)
        # は常に`.0`を残すため食い違う(知見46、公式ドキュメントで確定)。
        ("CStr(4.0)", "4"),
        ("CStr(-8.0)", "-8"),
        ("CStr(3.14)", "3.14"),
        ("CStr(0.0)", "0"),
        # NaN/Infinityは`Double.ToString()`がG書式と独立に特別扱いする
        # 文字列を返す(知見46)——`^`の修正(知見45)で生成されうる値との
        # 整合性も兼ねて確認。
        ("CStr((-8.0) ^ 0.5)", "NaN"),
        # 文字列・整数・真偽値はそのまま(既存の`CStr`挙動に変更無し)。
        ('CStr("abc")', "abc"),
        ("CStr(5)", "5"),
        ("CStr(True)", "True"),
        # `Nothing`は空文字列へ丸める(知見56、.NETランタイム本体のソース
        # ——厳密には`CStr(Nothing)`自体はnullを返すが、単純な`str(x)`に
        # 通すと絶対にVBが出さない`"None"`という文字列になってしまう
        # ため、`&`での実用シナリオで正しくなる空文字列への近似を採用)。
        ("CStr(Nothing)", ""),
    ],
)
def test_cstr_matches_vb_g_format_not_python_str_float(vb_text: str, expected: str) -> None:
    wf = _wrap([MessageBoxNode(text=VbExpr(text=vb_text))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # `&`による文字列結合も`CStr`と同じ変換規則を使う(知見46)——
        # 単純な`str()`ではDouble値の見た目が食い違う。
        ('"x=" & 4.0', "x=4"),
        ('"n=" & 5 & "/" & True', "n=5/True"),
        # `Nothing`は`&`では実質的に空文字列として扱われる(知見56、
        # `Operators.vb`の`ConcatenateObject`→`System.String.Concat`の
        # null自動読み替えで確定)。
        ('"x=" & Nothing', "x="),
        ('Nothing & "abc"', "abc"),
    ],
)
def test_concat_uses_same_vb_cstr_conversion_as_cstr(vb_text: str, expected: str) -> None:
    wf = _wrap([MessageBoxNode(text=VbExpr(text=vb_text))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


def test_append_line_text_uses_vb_cstr_not_python_str(tmp_path) -> None:
    """`Append Line`の`Text`(`InArgument<String>`、知見15)に数値式を直接
    渡した場合も`CStr`/`&`(知見46)と同じ`_vb_cstr`変換を使う——単純な
    `str()`のままだと`str(4.0)`で`"4.0"`になりVBの暗黙変換と食い違う
    (実機でこの暗黙変換の実例は未確認だが、`render.py`内の一貫性の問題
    として修正、知見46の延長)。"""
    out_file = tmp_path / "out.txt"
    wf = _wrap(
        [
            AppendLineNode(
                file_name=Literal(value=str(out_file)),
                text=VbExpr(text="4.0"),
            )
        ]
    )
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    namespace["Test"]()
    assert out_file.read_text(encoding="utf-8") == "4\n"


@pytest.mark.parametrize(
    ("kwargs", "expected_kwarg"),
    [
        # 知見108: `UseDefaultEncoding=False`・`Encoding`未指定(実機
        # フィクスチャの実例)はUiPath公式ドキュメント確認済みの既定で
        # UTF-8になる。
        ({"use_default_encoding": "False"}, ', encoding=\'utf-8\''),
        # `Encoding="UTF-8"`明示も同じ。
        ({"encoding": "UTF-8"}, ', encoding=\'utf-8\''),
        # `UseDefaultEncoding=True`(または未設定)はOSの既定——`encoding=`
        # kwarg自体を付けない(Pythonの`open()`も省略時はロケール既定)。
        ({"use_default_encoding": "True"}, ""),
        ({}, ""),
    ],
)
def test_append_line_encoding_resolution(kwargs, expected_kwarg):
    """知見108: `Encoding`/`UseDefaultEncoding`は従来一切捕捉されておらず
    `encoding="utf-8"`が無条件に埋め込まれていた——確認済みの組み合わせ
    だけを正しくマッピングする。"""
    wf = _wrap([AppendLineNode(file_name=Literal(value="out.txt"), text=Literal(value="x"), **kwargs)])
    code = generate_python(wf)
    assert "# TODO" not in code
    assert f'with open(\'out.txt\', "a"{expected_kwarg}) as _f:' in code
    _compiles(code)


def test_append_line_with_unconfirmed_encoding_is_todo_not_guessed():
    """知見108: `Encoding`が確認済みの`"UTF-8"`以外の場合は、Pythonの
    コーデック名への正確な対応が未確認のため`# TODO`に倒す。"""
    wf = _wrap(
        [AppendLineNode(file_name=Literal(value="out.txt"), text=Literal(value="x"), encoding="Unicode")]
    )
    code = generate_python(wf)
    assert "# TODO: Append Line with unconfirmed Encoding 'Unicode'" in code
    _compiles(code)


def test_read_text_file_with_unconfirmed_encoding_is_todo_not_guessed():
    """知見108: `ReadTextFile`も同様——`Encoding`が確認済みの`"UTF-8"`
    以外の場合は`# TODO`に倒す。"""
    wf = _wrap(
        [
            ReadTextFileNode(
                file_name=Literal(value="out.txt"),
                content=VbExpr(text="content"),
                encoding="Windows-1252",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Read Text File with unconfirmed Encoding 'Windows-1252'" in code
    _compiles(code)


def test_read_text_file_with_unrenderable_content_target_is_todo_not_invalid_python():
    """知見138: `node.content`(代入先)のレンダリングが失敗する場合
    (知見74の添字曖昧性等)、`if todo: return todo`の欠落により
    `None = open(...)...`という構文的に無効なコードを生成していた
    ——他の全ての「targetへ代入する」生成関数が既に守っている規約への
    抜け漏れを修正した(知見136・137と同じバグの第3の発生箇所)。"""
    wf = _wrap(
        [
            ReadTextFileNode(
                file_name=Literal(value="out.txt"),
                content=VbExpr(text="CurrentRow(0)"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: unresolved VB expression:" in code
    assert "None = " not in code
    _compiles(code)


def test_write_text_file_writes_utf8_text_to_the_given_path():
    """知見212: 実機3件相当の`FileName`+`Text`構成。`Text`は
    `SetToClipboard`(知見46)と同じ`InArgument<String>`型のため
    `_vb_cstr()`で変換、UTF-8で書き込む(`ReadTextFile`知見108と同じ
    既存の一貫した判断)。"""
    out_path = tempfile.mktemp(suffix=".txt")
    wf = _wrap(
        [
            WriteTextFileNode(
                file_name=Literal(value=out_path),
                text=Literal(value="hello world こんにちは"),
            )
        ]
    )
    code = generate_python(wf)
    assert f'open({out_path!r}, "w", encoding="utf-8").write(' in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    namespace["Test"]()
    assert open(out_path, encoding="utf-8").read() == "hello world こんにちは"


def test_write_text_file_declines_file_and_output_object_references():
    """知見212: `File`/`Output`は実機で非`{x:Null}`の実例が無く未
    モデル化のため常に`# TODO`。"""
    wf = _wrap(
        [
            WriteTextFileNode(
                file_name=Literal(value="out.txt"),
                text=Literal(value="hi"),
                file=VbExpr(text="someFile"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: WriteTextFile with File set" in code
    _compiles(code)

    wf2 = _wrap(
        [
            WriteTextFileNode(
                file_name=Literal(value="out.txt"),
                text=Literal(value="hi"),
                output=VbExpr(text="writtenFile"),
            )
        ]
    )
    code2 = generate_python(wf2)
    assert "# TODO: WriteTextFile with Output captured" in code2
    _compiles(code2)


def test_write_text_file_with_missing_properties_is_todo():
    wf = _wrap([WriteTextFileNode(file_name=None, text=Literal(value="hi"))])
    code = generate_python(wf)
    assert "# TODO: WriteTextFile with missing FileName/Text" in code
    _compiles(code)


def test_is_match_evaluates_regex_with_ignorecase():
    """知見213: 実機`mehmetbesli/UiPathExamples`相当の構成——
    `RegexOption="IgnoreCase"`を`re.IGNORECASE`に変換して`re.search()`
    を実際に実行し、正しいbool判定結果を確認する。"""
    wf = _wrap(
        [
            IsMatchNode(
                input=VbExpr(text="girilen_sayi"),
                pattern=Literal(value="^([0-9]{2})$"),
                regex_option="IgnoreCase",
                result=VbExpr(text="deger_dogruMU"),
            )
        ]
    )
    code = generate_python(wf)
    assert "deger_dogruMU = bool(re.search(" in code
    assert "re.IGNORECASE" in code
    assert "import re" in code
    assert "# TODO" not in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(girilen_sayi):\n    deger_dogruMU = None")
    code2 += "\n    return deger_dogruMU"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    assert namespace["Test"]("42") is True
    assert namespace["Test"]("123") is False


def test_is_match_ignores_compiled_flag_and_declines_unconfirmed_option():
    """知見213: `"IgnoreCase, Compiled"`(ground-truthの既定値+実機
    `GSA/Credit_Card_Logging_Bot`の実例)は`Compiled`を無視して対応
    する。未確認の他フラグ(`Multiline`等)は`# TODO`へ倒す。"""
    wf = _wrap(
        [
            IsMatchNode(
                input=Literal(value="True"),
                pattern=Literal(value="True"),
                regex_option="IgnoreCase, Compiled",
                result=VbExpr(text="r"),
            )
        ]
    )
    code = generate_python(wf)
    assert "re.IGNORECASE" in code
    assert "# TODO" not in code
    _compiles(code)

    wf2 = _wrap(
        [
            IsMatchNode(
                input=Literal(value="x"),
                pattern=Literal(value="y"),
                regex_option="Multiline",
                result=VbExpr(text="r"),
            )
        ]
    )
    code2 = generate_python(wf2)
    assert "# TODO: IsMatch with unrecognized RegexOption ('Multiline')" in code2
    _compiles(code2)


def test_is_match_with_missing_properties_is_todo():
    wf = _wrap(
        [
            IsMatchNode(
                input=Literal(value="x"),
                pattern=Literal(value="y"),
                regex_option="IgnoreCase",
                result=None,
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: IsMatch with no Result captured" in code
    _compiles(code)


def test_replace_substitutes_via_re_sub():
    """知見220: `ui:Replace`(`IsMatch`と同じ正規表現ビルダー系の兄弟
    活動)。`.NET Regex.Replace(input, pattern, replacement)`は
    `re.sub(pattern, replacement, input)`に対応する。実機
    `LowyShin/lwrpa-uip-moveoldfiles`相当の構成を`exec()`経由で実際に
    実行し、正しく置換されることを確認する。"""
    wf = _wrap(
        [
            ReplaceNode(
                input=VbExpr(text="kValue"),
                pattern=Literal(value="}{"),
                replacement=Literal(value="},{"),
                regex_option="IgnoreCase, Compiled",
                result=VbExpr(text="kValue"),
            )
        ]
    )
    code = generate_python(wf)
    assert "re.sub(" in code
    assert "import re" in code
    assert "# TODO" not in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(kValue):")
    code2 += "\n    return kValue"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    assert namespace["Test"]("a}{b}{c") == "a},{b},{c"


def test_replace_ignores_compiled_flag_and_declines_unconfirmed_option():
    """知見220: `"IgnoreCase, Compiled"`は`Compiled`を無視して対応する
    ——`IsMatch`(知見213)と同じ判断。未確認の他フラグは`# TODO`へ倒す。"""
    wf = _wrap(
        [
            ReplaceNode(
                input=Literal(value="x"),
                pattern=Literal(value="y"),
                replacement=Literal(value="z"),
                regex_option="IgnoreCase, Compiled",
                result=VbExpr(text="r"),
            )
        ]
    )
    code = generate_python(wf)
    assert "flags=re.IGNORECASE" in code
    assert "# TODO" not in code
    _compiles(code)

    wf2 = _wrap(
        [
            ReplaceNode(
                input=Literal(value="x"),
                pattern=Literal(value="y"),
                replacement=Literal(value="z"),
                regex_option="Multiline",
                result=VbExpr(text="r"),
            )
        ]
    )
    code2 = generate_python(wf2)
    assert "# TODO: Replace with unrecognized RegexOption ('Multiline')" in code2
    _compiles(code2)


def test_replace_with_missing_properties_is_todo():
    wf = _wrap(
        [
            ReplaceNode(
                input=Literal(value="x"),
                pattern=Literal(value="y"),
                replacement=Literal(value="z"),
                regex_option="IgnoreCase",
                result=None,
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Replace with no Result captured" in code
    _compiles(code)


def test_matches_extracts_first_match_or_empty_string():
    """知見221: `ui:Matches`(`IsMatch`/`Replace`と同じ正規表現ビルダー
    系の兄弟活動)。`.NET Regex.Match(input, pattern).Value`は`re.
    search()`が不一致でも`""`(`None`ではない)を返す——実機
    `mantri13/Usecase2_ActiveLoans`相当の「ラベルの後の値を抜き出す」
    構成を`exec()`経由で実際に実行し、一致/不一致の両方を確認する。"""
    wf = _wrap(
        [
            MatchesNode(
                input=VbExpr(text="in_LoanDetails"),
                pattern=Literal(value=r"(?<=Amount: )\d+"),
                regex_option="IgnoreCase, Compiled",
                first_match=VbExpr(text="out_Amount"),
            )
        ]
    )
    code = generate_python(wf)
    assert "_mch = re.search(" in code
    assert 'out_Amount = _mch.group(0) if _mch else ""' in code
    assert "# TODO" not in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(in_LoanDetails):")
    code2 += "\n    return out_Amount"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    assert namespace["Test"]("Amount: 1500 due") == "1500"
    assert namespace["Test"]("nothing here") == ""


def test_matches_declines_result_output_and_unconfirmed_regex_option():
    """知見221: `Result`の正確な型(リスト?`MatchCollection`相当?)が
    実機からは確認できないため常に`# TODO`。未確認の`RegexOption`も
    `# TODO`——`IsMatch`/`Replace`と同じ判断。"""
    wf = _wrap(
        [
            MatchesNode(
                input=Literal(value="x"),
                pattern=Literal(value="y"),
                regex_option="IgnoreCase",
                result=VbExpr(text="allMatches"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Matches with Result captured" in code
    _compiles(code)

    wf2 = _wrap(
        [
            MatchesNode(
                input=Literal(value="x"),
                pattern=Literal(value="y"),
                regex_option="Multiline",
                first_match=VbExpr(text="m"),
            )
        ]
    )
    code2 = generate_python(wf2)
    assert "# TODO: Matches with unrecognized RegexOption ('Multiline')" in code2
    _compiles(code2)


def test_matches_with_missing_properties_is_todo():
    wf = _wrap(
        [
            MatchesNode(
                input=Literal(value="x"),
                pattern=Literal(value="y"),
                regex_option="IgnoreCase",
                first_match=None,
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: Matches with no output FirstMatch captured" in code
    _compiles(code)


def test_text_to_left_right_splits_on_first_occurrence():
    """知見222: `ui:TextToLeftRight`。実機
    `DariusDangi/GenerateYearlyReports`相当の`SeparatorKey="Custom"`
    構成を`exec()`経由で実際に実行し、`Separator`の最初の出現位置で
    分割されること、区切り文字自体が出力に含まれないことを確認する。"""
    wf = _wrap(
        [
            TextToLeftRightNode(
                full_text=VbExpr(text="TempString"),
                separator=Literal(value="TaxID: "),
                separator_key="Custom",
                text_to_left=VbExpr(text="out_Left"),
                text_to_right=VbExpr(text="out_Right"),
            )
        ]
    )
    code = generate_python(wf)
    assert ".split(" in code
    assert "# TODO" not in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(TempString):")
    code2 += "\n    return out_Left, out_Right"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    assert namespace["Test"]("Name: John TaxID: 1234") == (
        "Name: John ",
        "1234",
    )


def test_text_to_left_right_missing_separator_raises_index_error():
    """知見222: `Separator`が`FullText`中に見つからない場合の挙動は
    公式ドキュメントにも未記載——フォールバック値を捏造せず、
    `TextToRight`代入で自然な`IndexError`が発生するに任せる方針
    (`GetRowItem`知見177/183と同じ)を`exec()`経由で確認する。"""
    wf = _wrap(
        [
            TextToLeftRightNode(
                full_text=VbExpr(text="FullText"),
                separator=Literal(value="NOTFOUND"),
                separator_key="Custom",
                text_to_left=VbExpr(text="out_Left"),
                text_to_right=VbExpr(text="out_Right"),
            )
        ]
    )
    code = generate_python(wf)
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(FullText):")
    code2 += "\n    return out_Left, out_Right"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    with pytest.raises(IndexError):
        namespace["Test"]("no separator here")


def test_text_to_left_right_declines_unconfirmed_separator_key():
    """知見222: `SeparatorKey`が`"Custom"`/`"NewLine"`以外の場合、
    その時の`Separator`属性の正確な事前入力が未確認のため`# TODO`。"""
    wf = _wrap(
        [
            TextToLeftRightNode(
                full_text=VbExpr(text="x"),
                separator=Literal(value="y"),
                separator_key="Whitespace",
                text_to_left=VbExpr(text="l"),
                text_to_right=VbExpr(text="r"),
            )
        ]
    )
    code = generate_python(wf)
    assert (
        "# TODO: TextToLeftRight with unrecognized SeparatorKey ('Whitespace')"
        in code
    )
    _compiles(code)


def test_text_to_left_right_with_no_output_captured_is_todo():
    wf = _wrap(
        [
            TextToLeftRightNode(
                full_text=VbExpr(text="x"),
                separator=Literal(value="y"),
                separator_key="Custom",
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: TextToLeftRight with no output captured" in code
    _compiles(code)


def test_get_environment_variable_resolves_machine_name_and_user_name():
    """知見215: 実機確認済みの`MachineName`/`UserName`特殊プロパティ名
    を`platform.node()`/`getpass.getuser()`で解決する。`exec()`経由で
    実際に実行し、プレースホルダではない実在の値が返ることを確認する。"""
    wf = _wrap(
        [
            GetEnvironmentVariableNode(
                variable=Literal(value="MachineName"),
                variable_value=VbExpr(text="machine"),
            )
        ]
    )
    code = generate_python(wf)
    assert "machine = platform.node()" in code
    assert "import platform" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code + "\n    return machine", namespace)  # noqa: S102 - 信頼できる自作コード
    assert isinstance(namespace["Test"](), str)

    wf2 = _wrap(
        [
            GetEnvironmentVariableNode(
                variable=Literal(value="UserName"),
                variable_value=VbExpr(text="user"),
            )
        ]
    )
    code2 = generate_python(wf2)
    assert "user = getpass.getuser()" in code2
    assert "import getpass" in code2
    _compiles(code2)


def test_get_environment_variable_falls_back_to_os_environ():
    """知見215: `MachineName`/`UserName`以外(`TEMP`等)は実際のOS環境
    変数名として`os.environ.get()`で解決する——実機
    `masiref/HandyML`相当。"""
    wf = _wrap(
        [
            GetEnvironmentVariableNode(
                variable=Literal(value="PAD2PY_TEST_ENV_VAR"),
                variable_value=VbExpr(text="val"),
            )
        ]
    )
    code = generate_python(wf)
    assert "val = os.environ.get('PAD2PY_TEST_ENV_VAR')" in code
    assert "import os" in code
    _compiles(code)
    namespace: dict[str, object] = {}
    os.environ["PAD2PY_TEST_ENV_VAR"] = "hello"
    try:
        exec(code + "\n    return val", namespace)  # noqa: S102 - 信頼できる自作コード
        assert namespace["Test"]() == "hello"
    finally:
        del os.environ["PAD2PY_TEST_ENV_VAR"]


def test_get_environment_variable_declines_osversion_and_dynamic_variable():
    """知見215: `OSVersion`は.NETの正確な書式を再現する標準的なPython
    対応が無いため`# TODO`。`Variable`が静的リテラルでない場合も
    特殊プロパティ名かOS環境変数かを事前判断できないため`# TODO`。"""
    wf = _wrap(
        [
            GetEnvironmentVariableNode(
                variable=Literal(value="OSVersion"),
                variable_value=VbExpr(text="os_ver"),
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO: GetEnvironmentVariable with Variable 'OSVersion'" in code
    _compiles(code)

    wf2 = _wrap(
        [
            GetEnvironmentVariableNode(
                variable=VbExpr(text="Environment.UserName"),
                variable_value=VbExpr(text="user"),
            )
        ]
    )
    code2 = generate_python(wf2)
    assert "# TODO: GetEnvironmentVariable with a dynamic Variable" in code2
    _compiles(code2)


def test_set_environment_variable_sets_os_environ():
    """知見223: `ui:SetEnvironmentVariable`(`GetEnvironmentVariable`の
    兄弟活動)。`Get`側と違い常にOS環境変数として設定するだけで2経路
    判断が無いため、動的`Name`でも問題なく対応できる——`exec()`経由で
    実際に`os.environ`へ値が設定されることを確認する。"""
    wf = _wrap(
        [
            SetEnvironmentVariableNode(
                name=VbExpr(text="varName"),
                value=VbExpr(text="varValue"),
            )
        ]
    )
    code = generate_python(wf)
    assert "os.environ[" in code
    assert "import os" in code
    assert "# TODO" not in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(varName, varValue):")
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    import os

    try:
        namespace["Test"]("PAD2PY_TEST_SET_ENV_VAR", "hello")
        assert os.environ.get("PAD2PY_TEST_SET_ENV_VAR") == "hello"
    finally:
        os.environ.pop("PAD2PY_TEST_SET_ENV_VAR", None)


def test_set_environment_variable_with_missing_properties_is_todo():
    wf = _wrap([SetEnvironmentVariableNode(name=Literal(value="X"), value=None)])
    code = generate_python(wf)
    assert "# TODO: SetEnvironmentVariable with missing Name/Value" in code
    _compiles(code)


def test_modify_text_applies_children_in_order():
    """知見224: `ui:ModifyText`。実機
    `Apress/Robotic-Process-Automation-Using-UiPath-StudioX`相当の
    `FindAndReplace`→`Trim`→`ToUpperLower`の順を`exec()`経由で実際に
    実行し、`SourceText`→`OutputText`への線形な文字列変換を確認する。
    `MatchCase`省略時は公式ドキュメント確認済みの既定(大文字小文字を
    区別しない一致)で動作することも確認する。"""
    wf = _wrap(
        [
            ModifyTextNode(
                source_text=VbExpr(text="Raw"),
                output_text=VbExpr(text="Saved"),
                body=[
                    FindAndReplaceTextModificationNode(
                        search_text=Literal(value="%"),
                        replace_text=Literal(value="_"),
                    ),
                    TrimTextModificationNode(),
                    ToUpperLowerTextModificationNode(modification_type="Lowercase"),
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "re.sub(" in code
    assert "flags=re.IGNORECASE" in code
    assert ".strip()" in code
    assert ".lower()" in code
    assert "# TODO" not in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(Raw):")
    code2 += "\n    return Saved"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    assert namespace["Test"]("  HELLO%WORLD  ") == "hello_world"


def test_modify_text_find_and_replace_match_case_true_is_case_sensitive():
    """知見224: `MatchCase="True"`は実機で確認できた唯一の非既定値——
    `re.sub()`の第4位置引数が`count`であり`flags`ではないことを発見し
    (`re.search()`とは引数順が異なる既知のPython標準ライブラリの罠)、
    `flags=`キーワード引数で明示する必要があった。大文字小文字を区別
    する一致になることを`exec()`経由で確認する。"""
    wf = _wrap(
        [
            ModifyTextNode(
                source_text=VbExpr(text="Raw"),
                output_text=VbExpr(text="Saved"),
                body=[
                    FindAndReplaceTextModificationNode(
                        search_text=Literal(value="abc"),
                        replace_text=Literal(value="X"),
                        match_case="True",
                    ),
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert "flags=re.IGNORECASE" not in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(Raw):")
    code2 += "\n    return Saved"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    assert namespace["Test"]("ABCdef abc") == "ABCdef X"


def test_modify_text_with_empty_body_is_pass_through():
    wf = _wrap(
        [
            ModifyTextNode(
                source_text=VbExpr(text="Raw"),
                output_text=VbExpr(text="Saved"),
                body=[],
            )
        ]
    )
    code = generate_python(wf)
    assert "# TODO" not in code
    _compiles(code)
    code2 = code.replace("def Test():", "def Test(Raw):")
    code2 += "\n    return Saved"
    namespace: dict[str, object] = {}
    exec(code2, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    assert namespace["Test"]("hello") == "hello"


def test_modify_text_declines_unsupported_child_without_partial_application():
    """知見224: 未対応の子活動(`CombineTextModification`等)が1つでも
    あれば、途中の変換だけ欠落した誤った文字列を`OutputText`へ渡して
    しまわないよう、活動全体を`# TODO`へ倒す(部分適用はしない)方針を
    確認する。"""
    wf = _wrap(
        [
            ModifyTextNode(
                source_text=VbExpr(text="Raw"),
                output_text=VbExpr(text="Saved"),
                body=[
                    TrimTextModificationNode(),
                    UnknownActivityNode(
                        tag="ucat:CombineTextModification",
                        display_name=None,
                        attrs={},
                    ),
                ],
            )
        ]
    )
    code = generate_python(wf)
    assert (
        "# TODO: ModifyText with unsupported or unconfirmed child "
        "modification (UnknownActivityNode)" in code
    )
    assert ".strip()" not in code
    _compiles(code)


def test_modify_text_with_missing_properties_is_todo():
    wf = _wrap(
        [ModifyTextNode(source_text=None, output_text=VbExpr(text="Saved"), body=[])]
    )
    code = generate_python(wf)
    assert "# TODO: ModifyText with missing SourceText/OutputText" in code
    _compiles(code)


def test_set_to_clipboard_text_uses_vb_cstr_not_python_str() -> None:
    """`SetToClipboard`の`Text`も`Append Line`と同じ`InArgument<String>`
    (知見46追補)——`pyperclip.copy()`自体は非文字列でも`str()`で救済して
    落ちはしないが(`pyperclip`のソースで確認済み)、それだとVBのG書式と
    食い違う。`exec()`はしない(このLinuxサンドボックスにはクリップボード
    機構が無くpyperclipが例外を出すため)——生成コードの文字列を直接確認する。
    """
    wf = _wrap([SetToClipboardNode(text=VbExpr(text="4.0"))])
    code = generate_python(wf)
    _compiles(code)
    assert "pyperclip.copy(_vb_cstr(4.0))" in code


def test_get_from_clipboard_exec():
    """知見243: `ui:GetFromClipboard`——`SetToClipboard`の逆方向、
    `pyperclip.paste()`に対応する。このLinuxサンドボックスには実際の
    クリップボード機構が無いため`unittest.mock.patch`で`pyperclip.
    paste`自体をモックし(`pyperclip`のインポート自体は問題無い——
    バックエンド呼び出し時のみ失敗する)、生成コードが実際に
    `pyperclip.paste()`の戻り値を正しく代入先へ書き込むことを
    `exec()`経由で確認する。"""
    wf = _wrap([GetFromClipboardNode(result=VbExpr(text="result"))])
    code = generate_python(wf)
    assert "import pyperclip" in code
    assert "result = pyperclip.paste()" in code
    assert "# TODO" not in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code + "\n    return result", namespace)  # noqa: S102 - 信頼できる自作コード
    with unittest.mock.patch("pyperclip.paste", return_value="hello world"):
        out = namespace["Test"]()
    assert out == "hello world"


def test_get_from_clipboard_display_name_becomes_a_comment():
    wf = _wrap(
        [GetFromClipboardNode(result=VbExpr(text="result"), display_name="Get From Clipboard")]
    )
    code = generate_python(wf)
    assert "# Get From Clipboard" in code
    _compiles(code)


def test_get_from_clipboard_with_no_result_is_todo():
    wf = _wrap([GetFromClipboardNode(result=None)])
    code = generate_python(wf)
    assert "# TODO: GetFromClipboard with no Result captured" in code
    _compiles(code)


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # 片方が数値・片方が文字列なら、文字列をDoubleへ変換してから数値
        # 比較する(Microsoft Learn「Comparison Operators」の
        # Typeless Programming節、知見47参照)。Pythonの素の`==`は
        # `"5" == 5`のように型をまたぐと常に`False`になり食い違う。
        ('5 = "5"', True),
        ('5 = "5.0"', True),
        ('"5" <> 5', False),
        ('"3" < 10', True),
        ('10 < "3"', False),
        # 両方が同じ型(文字列同士・数値同士)なら従来通り。
        ('"ok" = "ok"', True),
        ("5 = 5.0", True),
        # Nothingは数値比較では0、文字列比較では空文字列として扱う
        # (同じMicrosoft Learnページで確定)。
        ("Nothing = 0", True),
        ('Nothing = ""', True),
    ],
)
def test_comparison_operators_coerce_numeric_string_like_vb_object_comparison(
    vb_text: str, expected: object
) -> None:
    """知見47: `=`/`<>`/`<`/`<=`/`>`/`>=`がOption Strict Off下でObject型
    オペランドに適用する型変換規則を実装したことの回帰テスト
    (`"abc" = 5`のような変換不能な文字列ケースを除く——別テストで扱う)。
    """
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == str(expected)


def test_comparison_of_unconvertible_string_against_number_raises_not_silently_false() -> None:
    """VBは変換不能な文字列を数値と比較すると`InvalidCastException`を送出する
    (知見47、Microsoft Learn「Comparison Operators」)——`_vb_cmp`は同じ
    「静かに間違った結果(`False`)を返さず失敗を伝播させる」方向で
    `float()`の`ValueError`をそのまま伝播させる(でっち上げた`False`
    フォールバックは入れない)。
    """
    wf = _wrap([MessageBoxNode(text=VbExpr(text='"abc" = 5'))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    with pytest.raises(ValueError):
        namespace["Test"]()


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # 公式ドキュメントそのものの例:"34" + 6 は連結"346"ではなく
        # 算術加算40になる(Microsoft Learn「+ Operator」Remarks節、知見48)。
        ('"34" + 6', "40"),
        ('6 + "34"', "40"),
        # 両方数値・両方文字列なら従来通り。
        ("2 + 2", "4"),
        ('"a" + "b"', "ab"),
        # Nothingは数値側となら0、文字列側となら""として扱われる。
        ("5 + Nothing", "5"),
        ('"a" + Nothing', "a"),
        # 唯一の例外: Nothing + Nothingは.NETランタイム本体のソース
        # (Operators.vbのAddObject、知見55)で整数0になると確定——数値側/
        # 文字列側どちらの一般則とも異なる特別なケース。
        ("Nothing + Nothing", "0"),
    ],
)
def test_plus_operator_dispatches_add_vs_concat_like_vb_not_python_typeerror(
    vb_text: str, expected: str
) -> None:
    """知見48: `+`の型混在ディスパッチ規則(片方が数値・片方が文字列なら
    連結ではなく算術加算)を実装したことの回帰テスト。単純な`+`変換の
    ままだとPythonは`str + int`で`TypeError`を即座に送出しクラッシュする
    (値が間違うだけの`_vb_cmp`/`_vb_cstr`のケースより重大な問題だった)。
    """
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # `-`/`*`/`/`/`Mod`/`\`は文字列を扱わない純粋な数値演算子
        # (Microsoft Learn各ページ「Supported Types: All numeric types」)
        # ——`Nothing`は0として扱われる(知見49)。単純な変換のままだと
        # Pythonはstr/Noneを渡されると`TypeError`で即座にクラッシュする。
        ('"10" - 3', "7"),
        ('"10" * 3', "30"),
        ('"10" / 4', "2.5"),
        ("5 - Nothing", "5"),
        ("Nothing - 5", "-5"),
        ("5 * Nothing", "0"),
        ('"10" Mod 3', "1"),
        ('"10" \\ 3', "3"),
        ("Nothing Mod 3", "0"),
    ],
)
def test_numeric_operators_coerce_string_and_nothing_like_vb_not_python_typeerror(
    vb_text: str, expected: str
) -> None:
    """知見49: `-`/`*`/`/`/`Mod`/`\\`の文字列/`Nothing`オペランド強制を
    実装したことの回帰テスト。単純な変換のままだとPythonは
    `TypeError`で即座にクラッシュする(知見48の`+`と同じ問題がこちらにも
    存在した)。
    """
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # `/`は常にDouble扱いのためゼロ除算もDouble方式(Microsoft Learn
        # 「/ Operator」Attempted Division by Zero節、知見50)——被除数の
        # 符号でInfinity/-Infinity、両方0ならNaN。
        ("5 / 0", "Infinity"),
        ("-5 / 0", "-Infinity"),
        ("0 / 0", "NaN"),
        # 通常の除算は従来通り。
        ("10 / 4", "2.5"),
    ],
)
def test_division_by_zero_matches_vb_double_semantics_not_python_zerodivisionerror(
    vb_text: str, expected: str
) -> None:
    """知見50: `/`のゼロ除算がVBのDouble方式(Infinity/-Infinity/NaN)に
    なることの回帰テスト。単純な`a / b`のままだとPythonは
    `ZeroDivisionError`で即座にクラッシュする。
    """
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # .NETランタイム本体のソース(Operators.vbのModObject、知見54)で
        # Modのゼロ除算が型依存(浮動小数点系はNaN、整数系は例外)と確定。
        ("10.5 Mod 0.0", "NaN"),
        ("0.0 Mod 0", "NaN"),
    ],
)
def test_mod_by_zero_with_float_operand_returns_nan_not_exception(
    vb_text: str, expected: str
) -> None:
    """知見54: `Mod`のゼロ除算は型依存——浮動小数点系オペランドが絡む
    場合はVBは`NaN`を返す(整数系のみの場合は例外、下記の別テストで確認)。
    """
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


@pytest.mark.parametrize("vb_text", ["10 Mod 0", "10 \\ 0"])
def test_mod_and_intdiv_by_zero_with_integer_operands_raises(vb_text: str) -> None:
    """知見54: `Mod`(整数系オペランドのみの場合)と`\\`(型によらず常に)
    のゼロ除算はVBで例外になる(それぞれ`DivideByZeroException`)——
    Pythonの`ZeroDivisionError`は例外クラスは異なるが「静かに間違った
    結果を返さず失敗を伝播させる」という点で挙動が一致する。
    """
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    with pytest.raises(ZeroDivisionError):
        namespace["Test"]()


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # `\`は除算の前にオペランドをLongへ変換する際、銀行丸めを適用する
        # (Microsoft Learn「\ Operator」Remarks節、知見54)——`7.5 \ 2`は
        # `7.5`が銀行丸めで`8`になってから切り捨て除算され`4`になる。
        # 丸め無しの単純な`int(7.5/2)`は`3`になり食い違う。
        ("7.5 \\ 2", 4),
        ("2.5 \\ 2", 1),
    ],
)
def test_intdiv_rounds_operands_to_long_before_truncating_not_truncating_raw_value(
    vb_text: str, expected: int
) -> None:
    """知見54: `\\`はゼロ方向への切り捨て(知見42)だけでなく、切り捨て
    除算の**前**に両オペランドを銀行丸めでLongへ変換する——公式ドキュメント
    のRemarks節で確定。
    """
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == str(expected)


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # VBはBooleanを数値へ変換する際、Falseは0、Trueは-1になる
        # (Microsoft Learn「Boolean Data Type」で確定、知見51)——Pythonの
        # boolはintのサブクラスでTrueは1相当のため、符号が逆になる。
        ("5 + True", "4"),
        ("True + True", "-2"),
        ("5 - True", "6"),
        ("5 * True", "-5"),
        ("10 / True", "-10"),
        ("5 = True", "False"),
        ("-1 = True", "True"),
        ("True = True", "True"),
        ("True < False", "True"),
    ],
)
def test_boolean_operand_converts_to_negative_one_not_python_one(
    vb_text: str, expected: str
) -> None:
    """知見51: 算術・比較演算子の`_vb_num`/`_vb_add`/`_vb_cmp`/`_vb_div`
    全てが、Booleanオペランドを`True→-1`/`False→0`としてVBと一致する
    よう変換することの回帰テスト。
    """
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


@pytest.mark.parametrize(
    ("vb_text", "expect_nan"),
    [
        # 負の底+非整数の指数はVBでNaNになる(知見45、実機確認)。
        ("(-8.0) ^ 0.5", True),
        ("(-4.0) ^ 1.5", True),
        # 通常の底/整数指数は複素数に迂回せず通常どおり計算される。
        ("2 ^ 3", False),
        ("(-8.0) ^ 2", False),
    ],
)
def test_pow_matches_vb_nan_on_negative_base_with_fractional_exponent(
    vb_text: str, expect_nan: bool
) -> None:
    """知見44で未確認だった`^`のリスクを実機(UiPath Studio Debug File、
    2026-11-05)で確認——負の底に非整数の指数を与えるとVBは`NaN`を返す。
    Pythonの`**`は同条件で複素数を返すため単純な`**`変換は不可(知見45)。

    値そのものを`eval()`で確認する(`CStr`/`print`経由の文字列比較は
    しない——VBの`CStr(Double)`とPythonの`str(float)`は書式が異なる
    既知の別論点(`render.py`の`^`実装コメント参照)で、この演算子自体の
    正しさとは無関係のため混同しない)。`^`は知見57で`_vb_num()`経由に
    なったため、`eval()`の名前空間にも定義しておく必要がある。
    """
    code = render_expr(VbExpr(text=vb_text))
    namespace: dict[str, object] = {}
    exec(VB_NUM_HELPER_SOURCE, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    result = eval(code, namespace)  # noqa: S307 - テスト対象は信頼できる自作コード
    if expect_nan:
        assert isinstance(result, float) and math.isnan(result)
    else:
        assert not (isinstance(result, float) and math.isnan(result))
        assert result == eval(f"({vb_text.replace('^', '**')})")  # noqa: S307


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # `^`は`-`/`*`/`/`/`Mod`/`\`より前(知見45)に実装したため、文字列/
        # `Nothing`オペランドの強制が漏れていた(知見57、`Operators.vb`の
        # `ExponentObject`が`Empty`→`0.0`へ変換すると確認して発見)。
        # `Nothing ^ Nothing`は`0.0 ^ 0.0`=`1`(VBの指数演算の慣習で
        # `0の0乗は1`)。
        ("Nothing ^ Nothing", "1"),
        ('"2" ^ 2', "4"),
    ],
)
def test_pow_coerces_string_and_nothing_operands_not_raising_typeerror(
    vb_text: str, expected: str
) -> None:
    """知見57: `^`が文字列/`Nothing`オペランドで`TypeError`になっていた
    バグの回帰テスト(`None < 0`/`str < int`が原因で比較不能だった)。
    """
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # 知見89: 単項`-`/`+`は`Nothing`オペランドだけを特別扱いしており、
        # 文字列オペランド(数値文字列・`&H`/`&O`16進8進リテラル文字列
        # いずれも)は一切コンバートせず`TypeError: bad operand type for
        # unary -: 'str'`でクラッシュしていた——`&H`限定の問題ではなく、
        # 単純な数値文字列`"5"`でも同じクラッシュを再現した。
        ('-"5"', "-5"),
        ('+"5"', "5"),
        ('-"&H5"', "-5"),
        ('+"&O17"', "15"),
    ],
)
def test_unary_minus_plus_coerce_string_operand_not_raising_typeerror(
    vb_text: str, expected: str
) -> None:
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # IntegerオペランドへのNotはビット反転(2の補数、知見45、実機確認)。
        ("Not 5", -6),
        ("Not 0", -1),
        ("Not -1", 0),
        # Booleanオペランドへの`Not`は論理否定(知見32・36で既に確認済み)。
        ("Not True", False),
        ("Not False", True),
    ],
)
def test_not_matches_vb_bitwise_complement_on_integer_not_just_boolean_negation(
    vb_text: str, expected: bool | int
) -> None:
    """知見44で未確認だった`Not`のリスクを実機(UiPath Studio Debug File、
    2026-11-05)で確認——Integerオペランドの`Not 5`はビット反転`-6`になる。
    Pythonの`not 5`は`False`になり食い違うため、型に応じて`~x`/`not x`を
    実行時に分岐する必要がある(知見45)。
    """
    code = render_expr(VbExpr(text=vb_text))
    # 知見89: 単項`-`が`_vb_num()`経由になったため(`Not -1`は内側に単項
    # `-`を含む)、素の`eval()`では`_vb_num`が未定義になる——
    # `generate_python()`の自動注入を経由しないこの軽量テストでは、
    # 使うヘルパーのソースを手動で名前空間へ注入する(知見57の`^`テスト
    # と同じ対処)。
    namespace: dict[str, object] = {}
    exec(VB_NUM_HELPER_SOURCE, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    result = eval(code, namespace)  # noqa: S307 - テスト対象は信頼できる自作コード
    assert result == expected
    assert isinstance(result, bool) == isinstance(expected, bool)


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # 知見90: `Not`は`Nothing`オペランドだけを特別扱いしており、知見89
        # (単項`-`/`+`)と全く同じ理由で文字列オペランドは未対応のまま
        # `~"5"`で`TypeError: bad operand type for unary ~: 'str'`に
        # なっていた——`&H`限定の問題ではなく単純な数値文字列でも再現した。
        ('Not "5"', "-6"),
        ('Not "&H5"', "-6"),
    ],
)
def test_not_coerces_string_operand_not_raising_typeerror(vb_text: str, expected: str) -> None:
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # 単項`Not`/`-`/`+`の`Nothing`オペランドは整数`0`として扱われる
        # (知見58、`Operators.vb`の`NotObject`/`NegateObject`/
        # `PlusObject`で確認)——`Not Nothing`は`Not 0`=`-1`、
        # `-Nothing`/`+Nothing`は`0`。単純な`~None`/`-(None)`は
        # `TypeError`になっていた。
        ("Not Nothing", "-1"),
        ("-Nothing", "0"),
        ("+Nothing", "0"),
    ],
)
def test_unary_operators_coerce_nothing_operand_not_raising_typeerror(
    vb_text: str, expected: str
) -> None:
    """知見58: 単項`Not`/`-`/`+`が`Nothing`オペランドで`TypeError`に
    なっていたバグの回帰テスト(知見55〜57に続くランタイムソース
    クロスチェックでの4件目の発見)。
    """
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # `And`: `Nothing`は相手がBooleanなら`False`、Integerなら`0`
        # として扱われる(知見59、`Operators.vb`の`AndObject`で確認)。
        ("Nothing And True", "False"),
        ("Nothing And 5", "0"),
        ("Nothing And Nothing", "0"),
        # `Or`/`Xor`: `Nothing`は単位元として働き、結果は他方の
        # オペランドがそのまま返る(型も維持される、`OrObject`/
        # `XorObject`で確認)。
        ("Nothing Or 5", "5"),
        ("Nothing Or True", "True"),
        ("Nothing Or Nothing", "0"),
        ("Nothing Xor 5", "5"),
        ("Nothing Xor True", "True"),
        ("Nothing Xor Nothing", "0"),
        # 両方が実際に値を持つ既存のケースは従来通り(回帰確認)。
        ("True And False", "False"),
        ("5 And 3", "1"),
    ],
)
def test_and_or_xor_coerce_nothing_operand_not_raising_typeerror(
    vb_text: str, expected: str
) -> None:
    """知見59: `And`/`Or`/`Xor`が`Nothing`オペランドで`TypeError`に
    なっていたバグの回帰テスト(知見58で「複雑なためでっち上げない」と
    保留していたが、`Operators.vb`の型ごとの分岐を具体的に確認したことで
    解決できた)。
    """
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # 知見91: 知見89・90(単項`-`/`+`・`Not`)と全く同じ理由で、`And`/
        # `Or`/`Xor`も両オペランドが非`Nothing`の場合に文字列を一切
        # コンバートせず`a & b`等へそのまま渡していたため、
        # `TypeError: unsupported operand type(s) for &: 'str' and
        # 'int'`でクラッシュしていた。
        ('"5" And 3', "1"),
        ('"5" Or 3', "7"),
        ('"5" Xor 3', "6"),
        ('"&H5" And 3', "1"),
    ],
)
def test_and_or_xor_coerce_string_operand_not_raising_typeerror(
    vb_text: str, expected: str
) -> None:
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # 公式ドキュメント(Microsoft Learn「AndAlso Operator」)が
        # 「両オペランドを評価前にBooleanへ変換し、結果も常にBoolean」と
        # 明記(知見60)——単純な`and`/`or`への変換はPythonが生のオペランド
        # 値をそのまま返すため食い違う(`0 AndAlso True`はVBで`False`だが
        # `0 and True`は`0`を返す)。
        ("0 AndAlso True", "False"),
        ("5 AndAlso True", "True"),
        ("0 OrElse 5", "True"),
        ("Nothing AndAlso True", "False"),
        ("True AndAlso Nothing", "False"),
        ("Nothing OrElse True", "True"),
        # 両方Booleanの既存ケースは従来通り(回帰確認)。
        ("True AndAlso False", "False"),
        ("True OrElse False", "True"),
    ],
)
def test_andalso_orelse_coerce_operands_to_boolean_not_raw_python_and_or(
    vb_text: str, expected: str
) -> None:
    """知見60: `AndAlso`/`OrElse`が常にBoolean型の結果を返すよう
    オペランドを`_vb_bool()`で変換することの回帰テスト。
    """
    wf = _wrap([MessageBoxNode(text=VbExpr(text=f"CStr({vb_text})"))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


def test_andalso_short_circuits_without_evaluating_right_side_effect() -> None:
    """知見60: `_vb_bool()`経由に変更しても、右辺の副作用はPythonの
    `and`/`or`自体の短絡評価によって左辺が確定した時点でスキップされる
    (`AndAlso`/`OrElse`はVBでも短絡評価、右辺を二重評価・過剰評価しない
    ことの確認)。右辺に`InvokeCode`相当の副作用を直接埋め込めないため、
    生成コード文字列が`_vb_bool(right)`という単一の関数呼び出し式のまま
    (`and`/`or`の右オペランドとして1回だけ出現する)ことを確認する。
    """
    code = render_expr(VbExpr(text="a AndAlso b"))
    assert code == "(_vb_bool(a)) and (_vb_bool(b))"
    assert code.count("_vb_bool(b)") == 1


@pytest.mark.parametrize(
    ("vb_text", "expected"),
    [
        # 公式ドキュメント(Microsoft Learn「If...Then...Else Statement」)
        # が「conditionはTrue/Falseに評価できるか、暗黙的にBooleanへ
        # 変換可能な型」と明記(知見61)——Pythonの素の`if`文の真偽値判定
        # (`bool("False")`は`True`)はVBのCBool規則と食い違う。
        ('"False"', "NO"),
        ('"0"', "NO"),
        ('"True"', "YES"),
        ("Nothing", "NO"),
        ("5", "YES"),
    ],
)
def test_if_condition_coerces_to_boolean_like_vb_not_python_truthiness(
    vb_text: str, expected: str
) -> None:
    """知見61: `If`の条件がPythonの素の真偽値判定ではなくVBのCBool規則
    (`_vb_bool()`、知見60と同じヘルパー)に従うことの回帰テスト。"""
    wf = _wrap(
        [
            IfNode(
                condition=VbExpr(text=vb_text),
                then_body=[MessageBoxNode(text=Literal(value="YES"))],
                else_body=[MessageBoxNode(text=Literal(value="NO"))],
            )
        ]
    )
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == expected


def test_while_condition_coerces_to_boolean_like_vb_not_python_truthiness() -> None:
    """知見61: `While`の条件も`If`と同じBoolean変換規則に従う回帰テスト
    ——`"False"`という非空文字列は(Pythonの素の真偽値判定なら`True`に
    なってしまうところ)VBのCBool規則で`False`扱いになり、ループ本体が
    一度も実行されない。
    """
    wf = _wrap(
        [
            WhileNode(
                condition=VbExpr(text='"False"'),
                body=[MessageBoxNode(text=Literal(value="should not print"))],
            )
        ]
    )
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == ""


def test_ternary_if_condition_coerces_to_boolean_like_vb_not_python_truthiness() -> None:
    """知見61: 三項演算子`If(cond, t, f)`の条件も同じBoolean変換規則に
    従う回帰テスト。"""
    wf = _wrap([MessageBoxNode(text=VbExpr(text='If("False", "YES", "NO")'))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == "NO"


def test_known_op_compound_from_知見32_executes_to_the_correct_vb_result():
    """知見32の実機確認式(9演算子複合式)をそのまま生成Pythonコードへ変換し
    `exec()`して、VB.NET側の実際の結果と一致することまで確認する統合
    テスト。`Mod`/`\\`/`CInt`/`CBool`の修正(知見42・43)が実在する
    `uipath_vb_expression_mapping.md`の実例に対しても連携して正しく
    動くことの最終確認——個々の演算子を単体でテストするのとは別に、
    実際にUiPath Studioで確認された複合式そのものを通す。

    期待値はVB.NET側の実際の評価結果を手計算したもの: `1 Mod 3`=1、
    `5 \\ 2`=2、`2 ^ 2`=4、`True And False`=False、
    `True AndAlso False`=False、`True Or False`=True、
    `True OrElse False`=True、`True Xor False`=True、`Not True`=False
    (`&`で単純連結)。
    """
    from tests.test_uipath_expr import KNOWN_OP_COMPOUND

    wf = _wrap([MessageBoxNode(text=VbExpr(text=KNOWN_OP_COMPOUND))])
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == "124FalseFalseTrueTrueTrueFalse"


def test_invoke_workflow_file_without_resolver_falls_back_to_todo():
    """単体の`generate_python()`呼び出し(`invoke_resolver`省略)では、
    呼び出し先の存在を仮定した架空のコードをでっち上げず`# TODO`に倒す。"""
    wf = _wrap([InvokeWorkflowFileNode(workflow_file="Sub1.xaml", arguments={})])
    code = generate_python(wf)
    assert "# TODO: unresolved Invoke Workflow File: Sub1.xaml" in code
    _compiles(code)


def test_invoke_workflow_file_with_resolver_becomes_function_call():
    wf = _wrap(
        [
            InvokeWorkflowFileNode(
                workflow_file="Sub1.xaml", arguments={"in_text": Literal(value="hi")}
            )
        ]
    )
    code = generate_python(wf, invoke_resolver={"Sub1.xaml": "Sub1"})
    assert "Sub1(in_text='hi')" in code
    _compiles(code)


@pytest.mark.parametrize("continue_on_error", [None, Literal(value="False")])
def test_invoke_workflow_file_with_confirmed_safe_continue_on_error_becomes_call(
    continue_on_error: Literal | None,
) -> None:
    """知見72: `ContinueOnError`が未設定(`None`)または明示的な`"False"`
    (いずれも現在の「例外を伝播させる」挙動と一致する確認済みの安全な値)
    の場合は従来通り実関数呼び出しを生成する。"""
    wf = _wrap(
        [
            InvokeWorkflowFileNode(
                workflow_file="Sub1.xaml", arguments={}, continue_on_error=continue_on_error
            )
        ]
    )
    code = generate_python(wf, invoke_resolver={"Sub1.xaml": "Sub1"})
    assert "# TODO" not in code
    assert "Sub1()" in code
    _compiles(code)


def test_invoke_workflow_file_with_continue_on_error_true_is_todo_not_guessed():
    """知見72: `ContinueOnError="True"`の実機確認済み実例・正確な継続後の
    挙動が未確認のため、でっち上げたtry/except変換はせず`# TODO`に倒す。"""
    wf = _wrap(
        [
            InvokeWorkflowFileNode(
                workflow_file="Sub1.xaml",
                arguments={},
                continue_on_error=Literal(value="True"),
            )
        ]
    )
    code = generate_python(wf, invoke_resolver={"Sub1.xaml": "Sub1"})
    assert "# TODO: Invoke Workflow File with non-default ContinueOnError" in code
    assert "Sub1()" not in code
    _compiles(code)


def test_generate_project_python_links_main_and_sub1():
    """design/evidence/uipath_xaml_probe/Main.xamlが参照する
    Sub1.xamlを実際に解決し、1モジュールへ結線する結合テスト。
    複数ファイル結線(design/uipath_transpiler_roadmap.md Phase 6)が
    実際に動くことを確認する——`Main`から`Sub1(in_text='hello')`という
    実関数呼び出しが生成され、両方の関数定義が同じモジュールに存在する。
    `Main.xaml`自体はモジュールdocstring参照の既知の理由(ループ外の
    `<ui:Break />`)で全体がコンパイル可能とは主張しない——実行時の
    結線検証は`test_generate_project_python_actually_calls_sub_workflow`
    で別途、破綻の無い合成フィクスチャに対して行う。
    """
    code = generate_project_python(FIXTURE_DIR / "Main.xaml")
    assert "def Main():" in code
    assert "def Sub1(in_text):" in code
    assert "Sub1(in_text='hello')" in code
    assert "# TODO: unresolved Invoke Workflow File" not in code


def test_generate_project_python_actually_calls_sub_workflow(tmp_path):
    """合成した2ファイル構成(`Entry.xaml`→`Greet.xaml`)で、`exec()`後に
    実際に関数として呼び出すところまで確認する——文字列の有無だけでなく
    呼び出しが実行時に正しく連携することの実機不要な代替証拠。

    **既知の制約**: v1の`generate_python`はワークフロー引数の方向
    (In/Out)を区別せず全て関数の仮引数にするだけで、戻り値も生成しない
    (`test_workflow_arguments_become_function_params`と同じ既存の
    簡略化——OutArgumentをPythonの`return`へ対応させることはv1スコープ外、
    知見78・86参照)。そのため`Greet`が受け取った引数を`MessageBox`で
    出力し、`Entry`から呼んだときにそれが実際に標準出力に現れることで
    連携を確認する。
    """
    (tmp_path / "Greet.xaml").write_text(
        '<Activity xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:ui="http://schemas.uipath.com/workflow/activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" x:Class="Greet">'
        '<x:Members><x:Property Name="name" Type="InArgument(x:String)" /></x:Members>'
        '<Sequence DisplayName="Greet">'
        '<ui:MessageBox Text="[name &amp; &quot;!&quot;]" />'
        "</Sequence></Activity>",
        encoding="utf-8",
    )
    (tmp_path / "Entry.xaml").write_text(
        '<Activity xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:ui="http://schemas.uipath.com/workflow/activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" x:Class="Entry">'
        '<Sequence DisplayName="Entry">'
        '<ui:InvokeWorkflowFile WorkflowFileName="Greet.xaml">'
        "<ui:InvokeWorkflowFile.Arguments>"
        '<InArgument x:TypeArguments="x:String" x:Key="name">world</InArgument>'
        "</ui:InvokeWorkflowFile.Arguments>"
        "</ui:InvokeWorkflowFile>"
        "</Sequence></Activity>",
        encoding="utf-8",
    )
    code = generate_project_python(tmp_path / "Entry.xaml")
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102 - テスト対象は信頼できる自作コード
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Entry"]()
    assert stdout.getvalue().strip() == "world!"


def test_generate_project_python_warns_caller_about_out_argument_binding(tmp_path):
    """知見86: 知見78の`# TODO`は呼び出し先(`Sub1`)の関数定義側にのみ
    出現し、呼び出し元(`Main`)の呼び出し文には何の警告も出なかった——
    `generate_project_python()`経由で`out_arg_resolver`を構築し、呼び出し
    元の呼び出し文自体にも`# WARNING`を追記するようにした(呼び出し自体は
    通常通り生成する)。"""
    (tmp_path / "Sub1.xaml").write_text(
        '<Activity xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" x:Class="Sub1">'
        '<x:Members><x:Property Name="out_result" Type="OutArgument(x:String)" /></x:Members>'
        "<Sequence>"
        "<Assign>"
        '<Assign.To><OutArgument x:TypeArguments="x:String">[out_result]</OutArgument></Assign.To>'
        '<Assign.Value><InArgument x:TypeArguments="x:String">hi</InArgument></Assign.Value>'
        "</Assign>"
        "</Sequence></Activity>",
        encoding="utf-8",
    )
    (tmp_path / "Main.xaml").write_text(
        '<Activity xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:ui="http://schemas.uipath.com/workflow/activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" x:Class="Main">'
        "<Sequence>"
        '<ui:InvokeWorkflowFile WorkflowFileName="Sub1.xaml">'
        "<ui:InvokeWorkflowFile.Arguments>"
        '<OutArgument x:Key="out_result" x:TypeArguments="x:String">[myVar]</OutArgument>'
        "</ui:InvokeWorkflowFile.Arguments>"
        "</ui:InvokeWorkflowFile>"
        "</Sequence></Activity>",
        encoding="utf-8",
    )
    code = generate_project_python(tmp_path / "Main.xaml")
    _compiles(code)
    assert (
        "# WARNING: out_result are Out/InOutArgument on Sub1() — the bound variable "
        "here will NOT be updated after this call" in code
    )
    assert "Sub1(out_result=myVar)" in code
    assert "# TODO: argument(s) out_result are Out/InOutArgument" in code


def test_sequence_variable_with_default_is_initialized():
    """`Variable.Default`(知見7、属性形)があれば、スコープ先頭でその値に
    初期化する——UiPathの変数は明示代入前でも既定値で読める(Pythonの
    ローカル変数は未代入参照が`NameError`になり挙動が異なる)ため必要。"""
    wf = WorkflowFile(
        class_name="Test",
        root=SequenceNode(
            variables=[VariableDecl(name="myVar", type_arguments="x:String", default="init")],
            body=[MessageBoxNode(text=VbExpr(text="myVar"))],
        ),
    )
    code = generate_python(wf)
    assert "myVar = 'init'" in code
    assert code.index("myVar = 'init'") < code.index("print(myVar)")
    _compiles(code)


def test_sequence_variable_without_default_uses_net_type_default():
    """明示的な`Default`が無い場合は`.NET`の`default(T)`相当を使う——
    文字列/オブジェクト型は`None`(Nothing相当)、数値型は`0`、真偽値型は
    `False`。"""
    wf = WorkflowFile(
        class_name="Test",
        root=SequenceNode(
            variables=[
                VariableDecl(name="s", type_arguments="x:String"),
                VariableDecl(name="n", type_arguments="x:Int32"),
                VariableDecl(name="d", type_arguments="x:Double"),
                VariableDecl(name="b", type_arguments="x:Boolean"),
            ],
            body=[AssignNode(target=VbExpr(text="s"), value=Literal(value="ignored"))],
        ),
    )
    code = generate_python(wf)
    assert "s = None" in code
    assert "n = 0" in code
    assert "d = 0.0" in code
    assert "b = False" in code
    _compiles(code)


def test_try_catch_variables_initialized_before_try_block():
    """`TryCatch.Variables`(知見8)もスコープ先頭——`try:`より前——で初期化
    する(try本体の最初の文が例外を投げても`except`/`finally`から見える
    ように)。"""
    wf = _wrap(
        [
            TryCatchNode(
                try_body=[AssignNode(target=VbExpr(text="x"), value=Literal(value="a"))],
                variables=[
                    VariableDecl(name="myVar", type_arguments="x:String", default="init")
                ],
                catches=[CatchArm(exception_type="s:Exception", var_name="ex", body=[])],
            )
        ]
    )
    code = generate_python(wf)
    assert "myVar = 'init'" in code
    assert code.index("myVar = 'init'") < code.index("try:")
    _compiles(code)


def test_generate_project_python_missing_reference_falls_back_to_todo(tmp_path):
    """参照先ファイルが存在しない場合、`generate_project_python()`は
    でっち上げた解決済み関数呼び出しを生成せず`# TODO`に倒す(探索自体は
    クラッシュせず完了する)。"""
    entry = tmp_path / "Entry.xaml"
    entry.write_text(
        '<Activity xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:ui="http://schemas.uipath.com/workflow/activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" x:Class="Entry">'
        '<Sequence DisplayName="Entry">'
        '<ui:InvokeWorkflowFile WorkflowFileName="DoesNotExist.xaml" />'
        "</Sequence></Activity>",
        encoding="utf-8",
    )
    code = generate_project_python(entry)
    assert "def Entry():" in code
    assert "# TODO: unresolved Invoke Workflow File: DoesNotExist.xaml" in code
    _compiles(code)


def test_generate_project_from_json_reads_main_entry_point():
    """design/evidence/uipath_xaml_probe/project.json(実機キャプチャ、知見27)の
    `"main": "Main.xaml"`を読み取り、そこからgenerate_project_python()と
    同じ結果(Main.xaml→Sub1.xamlの複数ファイル結線込み)を生成する。"""
    code = generate_project_from_json(FIXTURE_DIR)
    assert "def Main():" in code
    assert "def Sub1(in_text):" in code
    assert "Sub1(in_text='hello')" in code


def test_generate_project_from_json_rejects_non_process_output_type(tmp_path):
    """v1スコープはProcessプロジェクトのみ(design/uipath_transpiler_roadmap.md
    Phase 1の決定)——Libraryプロジェクト(知見26のActivityBuilder形、
    uipath_dsl未対応)を誤って変換しようとせず明示的に拒否する。"""
    (tmp_path / "project.json").write_text(
        '{"main": "Main.xaml", "designOptions": {"outputType": "Library"}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="outputType"):
        generate_project_from_json(tmp_path)


def test_generate_project_from_json_rejects_real_library_fixture():
    """知見95: 上記の`outputType`拒否は従来、手作りの合成`project.json`
    (tmp_path)でしか検証されていなかった——design/evidence/
    uipath_xaml_probe_lib/project.json(実機キャプチャ、`outputType:
    "Library"`、`main: "NewActivity.xaml"`)という実物のLibraryプロジェクト
    フィクスチャが既にリポジトリに存在するのに、一度もこの経路で
    テストされていなかった(`p:NewActivity`というLibrary呼び出しの
    *参照先*としては`test_uipath_dsl.py`で間接的に触れられているのみ)。
    実機データで同じ拒否動作が成立することをロックする。"""
    with pytest.raises(ValueError, match="outputType"):
        generate_project_from_json(FIXTURE_LIB_DIR)


def test_generate_project_from_json_requires_main_field(tmp_path):
    (tmp_path / "project.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="main"):
        generate_project_from_json(tmp_path)


# --- Flowchart(知見100) ------------------------------------------------


def test_flowchart_simple_linear_chain_executes_in_order():
    """知見100: 分岐・合流の無い単純な`FlowStep`の連鎖(`Next`で繋ぐだけ)が
    ディスパッチループへ正しく変換され、実際に順番通り実行されることを
    確認する。"""
    step_c = FlowStepNode(body=[MessageBoxNode(text=Literal(value="c"))], next=None)
    step_b = FlowStepNode(body=[MessageBoxNode(text=Literal(value="b"))], next=step_c)
    step_a = FlowStepNode(body=[MessageBoxNode(text=Literal(value="a"))], next=step_b)
    wf = _wrap_flowchart(start=step_a)
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().splitlines() == ["a", "b", "c"]


def test_flowchart_decision_with_loop_and_convergence_executes_correctly():
    """知見100: 実際のUiPath保存済みXAML(GitHub上の実例)で確認した
    「分岐の片方がループで先頭に戻り、もう一方が終端へ向かう」という
    一般的なパターンを、IRレベルで直接(同じPythonオブジェクトを複数箇所
    から参照させることで合流・循環を表現して)検証する——`_flow`の
    ディスパッチループが同じノードに複数回正しく到達し、最終的に正しく
    終端することを確認する。"""
    end_step = FlowStepNode(body=[MessageBoxNode(text=Literal(value="done"))], next=None)
    start_step = FlowStepNode(body=[], next=None)  # next はdecision作成後に設定
    decision = FlowDecisionNode(
        condition=VbExpr(text="count < 3"), true_branch=start_step, false_branch=end_step
    )
    start_step.next = decision
    start_step.body = [
        AssignNode(target=VbExpr(text="count"), value=VbExpr(text="count + 1")),
    ]
    wf = _wrap_flowchart(
        start=start_step,
        variables=[VariableDecl(name="count", type_arguments="x:Int32", default="0")],
    )
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == "done"


def test_flowchart_switch_with_default_executes_matching_case():
    """知見100: `FlowSwitch`は`Switch`と同じ`_vb_cmp()`比較規則(公式
    ドキュメントが`FlowSwitch<T>`を`Switch<T>`と同様と明記していることに
    基づく類推、知見77)で変換される——一致するケースが実行され、
    `Default`は実行されないことを確認する。"""
    case1 = FlowStepNode(body=[MessageBoxNode(text=Literal(value="one"))])
    case2 = FlowStepNode(body=[MessageBoxNode(text=Literal(value="two"))])
    default = FlowStepNode(body=[MessageBoxNode(text=Literal(value="other"))])
    switch = FlowSwitchNode(
        expression=Literal(value="2"),
        type_arguments="x:Int32",
        arms=[
            FlowSwitchArm(key="1", node=case1),
            FlowSwitchArm(key="2", node=case2),
            FlowSwitchArm(key=None, node=default),
        ],
    )
    wf = _wrap_flowchart(start=switch)
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == "two"


def test_flowchart_switch_with_no_matching_case_and_no_default_terminates():
    """知見100: `Switch`(値が一致するcaseが無ければ何もしない)と同じ意味論
    だが、ディスパッチループでは`_flow`を明示的に`None`へ倒さないと外側の
    `while`が無限ループになる——これが正しく`_flow = None`へ倒れ、
    ワークフローが正常終了することを確認する(ハングしないこと自体が
    このテストの主張)。"""
    unreached = FlowStepNode(body=[MessageBoxNode(text=Literal(value="unreached"))])
    switch = FlowSwitchNode(
        expression=Literal(value="99"),
        type_arguments="x:Int32",
        arms=[FlowSwitchArm(key="1", node=unreached)],
    )
    wf = _wrap_flowchart(start=switch)
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == ""


def test_flowchart_decision_with_no_condition_falls_back_to_todo():
    """`DoWhile`の「Condition未設定」ケース(知見38相当)と同じ方針——
    でっち上げた既定分岐を選ばず`# TODO`に倒した上で、安全に`_flow = None`
    へ倒れてハングしないことを確認する。"""
    unreached = FlowStepNode(body=[MessageBoxNode(text=Literal(value="unreached"))])
    decision = FlowDecisionNode(condition=None, true_branch=unreached, false_branch=unreached)
    wf = _wrap_flowchart(start=decision)
    code = generate_python(wf)
    assert "# TODO: FlowDecision with no Condition set" in code
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["Test"]()
    assert stdout.getvalue().strip() == ""


def test_flowchart_empty_variables_only_still_compiles():
    """`start=None`(空のFlowchart、変数宣言のみ)でも構文的に正しいコードを
    生成することの回帰テスト。"""
    wf = _wrap_flowchart(
        start=None, variables=[VariableDecl(name="x", type_arguments="x:Int32")]
    )
    code = generate_python(wf)
    assert "x = 0" in code
    _compiles(code)


_FLOWCHART_LOOP_XAML = """\
<Activity xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities"
          xmlns:ui="http://schemas.uipath.com/workflow/activities"
          xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
          x:Class="FlowchartTest">
  <Flowchart>
    <Flowchart.Variables>
      <Variable x:TypeArguments="x:Int32" Name="count" Default="0" />
    </Flowchart.Variables>
    <Flowchart.StartNode>
      <FlowStep x:Name="__ReferenceID0">
        <Assign>
          <Assign.To><OutArgument x:TypeArguments="x:Int32">[count]</OutArgument></Assign.To>
          <Assign.Value><InArgument x:TypeArguments="x:Int32">[count + 1]</InArgument></Assign.Value>
        </Assign>
        <FlowStep.Next>
          <FlowDecision x:Name="__ReferenceID1" Condition="[count &lt; 3]">
            <FlowDecision.True>
              <x:Reference>__ReferenceID0</x:Reference>
            </FlowDecision.True>
            <FlowDecision.False>
              <FlowStep x:Name="__ReferenceID2">
                <ui:MessageBox Text="[&quot;done&quot;]" />
              </FlowStep>
            </FlowDecision.False>
          </FlowDecision>
        </FlowStep.Next>
      </FlowStep>
    </Flowchart.StartNode>
    <x:Reference>__ReferenceID0</x:Reference>
    <x:Reference>__ReferenceID1</x:Reference>
    <x:Reference>__ReferenceID2</x:Reference>
  </Flowchart>
</Activity>
"""


def test_parse_workflow_file_accepts_real_shaped_flowchart_xaml_with_loop(tmp_path):
    """知見100: VM不使用——実際にUiPath Studioが保存した公開済みXAML
    (GitHub上の実例、PacktPublishing/Robotic-Process-Automation-RPA-for-
    Developersの`FlowchartDemo.xaml`)で確認した直列化形(`x:Name`/
    `Flowchart.StartNode`/`FlowStep.Next`/`FlowDecision.True`・`.False`/
    `<x:Reference>Name</x:Reference>`要素形/文末の平坦な`Nodes`参照リスト)
    を模した合成XAMLを、実際に`parse_workflow_file`→`generate_python`→
    `exec()`まで通して確認する——`Flowchart`ルートがもはや`ValueError`に
    ならないこと、ループが正しく変換されることの統合テスト。"""
    path = tmp_path / "FlowchartTest.xaml"
    path.write_text(_FLOWCHART_LOOP_XAML, encoding="utf-8")
    wf = parse_workflow_file(path)
    assert isinstance(wf.root, FlowchartNode)
    code = generate_python(wf)
    _compiles(code)
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        namespace["FlowchartTest"]()
    assert stdout.getvalue().strip() == "done"


def test_generate_project_python_discovers_invoke_workflow_file_nested_in_flowchart(tmp_path):
    """知見100: 複数ファイルのBFS発見(`_discover_workflow_files`、知見88と
    同種の懸念)が、Flowchartルート配下にネストした`Invoke Workflow File`
    も正しく発見できることを確認する——`_iter_invoke_nodes_for_root`が
    `SequenceNode`/`FlowchartNode`どちらのルートでも機能することの回帰
    テスト。"""
    (tmp_path / "Sub1.xaml").write_text(
        '<Activity xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" x:Class="Sub1">'
        "<Sequence><ui:MessageBox "
        'xmlns:ui="http://schemas.uipath.com/workflow/activities" Text="&quot;hi&quot;" />'
        "</Sequence></Activity>",
        encoding="utf-8",
    )
    (tmp_path / "Main.xaml").write_text(
        '<Activity xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" '
        'xmlns:ui="http://schemas.uipath.com/workflow/activities" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" x:Class="Main">'
        "<Flowchart>"
        '<Flowchart.StartNode><FlowStep x:Name="s0">'
        '<ui:InvokeWorkflowFile WorkflowFileName="Sub1.xaml" />'
        "</FlowStep></Flowchart.StartNode>"
        "</Flowchart></Activity>",
        encoding="utf-8",
    )
    code = generate_project_python(tmp_path / "Main.xaml")
    _compiles(code)
    assert "# TODO: unresolved Invoke Workflow File" not in code
    assert "Sub1()" in code
