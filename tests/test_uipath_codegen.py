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
import os
import tempfile
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
    AppendLineNode,
    AssignNode,
    BreakNode,
    BuildDataTableNode,
    ClickNode,
    CopyFileNode,
    DatabaseConnectNode,
    DatabaseDisconnectNode,
    ExcelApplicationScopeNode,
    ExcelAppendRangeNode,
    ExcelReadRangeNode,
    ExcelWriteCellNode,
    ExcelWriteRangeNode,
    ExecuteNonQueryNode,
    ExecuteQueryNode,
    FlowchartNode,
    FlowDecisionNode,
    FlowStepNode,
    FlowSwitchArm,
    FlowSwitchNode,
    ForEachNode,
    GetTextNode,
    HttpClientNode,
    IfNode,
    InvokeCodeNode,
    InvokeWorkflowFileNode,
    Literal,
    MessageBoxNode,
    ParallelNode,
    ReadTextFileNode,
    SelectItemNode,
    SendMailNode,
    SendOutlookMailNode,
    SequenceNode,
    SetToClipboardNode,
    SwitchArm,
    SwitchNode,
    TryCatchNode,
    CatchArm,
    TypeIntoNode,
    UiElementExistsNode,
    UnknownActivityNode,
    VariableDecl,
    VbExpr,
    WhileNode,
    WorkflowFile,
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


def test_assign_object_typed_expr():
    wf = _wrap([AssignNode(target=VbExpr(text="result"), value=VbExpr(text='"ok"'))])
    code = generate_python(wf)
    assert "result = 'ok'" in code


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


def test_assign_chained_equals_call_renders_as_comparison():
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text='CStr(y).Equals("yes")'))])
    code = generate_python(wf)
    assert "x = (_vb_cstr(y)) == ('yes')" in code
    _compiles(code)


def test_assign_chained_access_with_unsupported_member_falls_back_to_todo():
    """`uipath_codegen`レベルでは値の変換失敗は`# TODO`へ(条件式の
    伝播とは違う失敗モード、モジュールdocstring参照)——未確認の.NET
    メンバ(`Substring`等)はでっち上げず`# TODO`へ倒す。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text="CStr(y).Substring(1)"))])
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
            ExcelWriteCellNode(cell="A1", sheet_name="Sheet1", text=Literal(value="hi")),
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
                body=[ExcelWriteCellNode(cell="A1", sheet_name="Sheet1", text=Literal(value="hi"))],
            )
        ]
    )
    code = generate_python(wf)
    assert "ExcelWorkbookScope = openpyxl.load_workbook('wb.xlsx')" in code
    assert "ExcelWorkbookScope['Sheet1']['A1'] = _vb_cstr('hi')" in code
    assert "ExcelWorkbookScope.save('wb.xlsx')" in code
    assert "# TODO" not in code
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
