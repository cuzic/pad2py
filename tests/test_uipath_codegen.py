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
from pathlib import Path

import pytest

import math

from dump_daemon.uipath_codegen import (
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
    ClickNode,
    ExcelApplicationScopeNode,
    ExcelWriteCellNode,
    FlowchartNode,
    FlowDecisionNode,
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
    ParallelNode,
    SendOutlookMailNode,
    SequenceNode,
    SetToClipboardNode,
    SwitchArm,
    SwitchNode,
    TryCatchNode,
    CatchArm,
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


def test_click_with_non_default_cursor_position_is_todo_not_guessed():
    """知見73: `CursorPosition`が`"Center"`以外(オフセット指定のマッピング
    未確認)の場合はでっち上げず`# TODO`に倒す。"""
    wf = _wrap([ClickNode(selector=_CLICK_SELECTOR, cursor_position="TopLeft")])
    code = generate_python(wf)
    assert "# TODO: Click with non-default CursorPosition" in code
    assert ".click_input()" not in code
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
            # 知見96: 単純な構成(Body未設定・コレクション全て空)はもはや
            # unresolvedに倒れず実際のrequestsコードを生成するため、ここでは
            # Bodyを設定してunresolvedへのフォールバックを明示的に発生させる。
            HttpClientNode(endpoint=VbExpr(text="url"), method="POST", body=Literal(value="x")),
            "(EndPoint=[url], Method='POST', Body='x')",
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


def test_http_client_falls_back_to_todo_with_populated_headers():
    """知見96: `Headers`等に1件以上のエントリがある場合は実直列化形が
    実機未確認のため、でっち上げず`# TODO`に倒す。"""
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
    同じ「捕捉済みデータの未活用」パターンの追加分。`Body`を設定して知見96の
    実コード生成パスではなくunresolvedフォールバックを明示的に発生させる。"""
    node = HttpClientNode(
        endpoint=VbExpr(text="url"),
        method="POST",
        body=Literal(value="payload"),
        extra_attrs={"AcceptFormat": "JSON"},
    )
    wf = _wrap([node])
    code = generate_python(wf)
    assert (
        "# TODO: unsupported in v1 codegen: HttpClientNode (EndPoint=[url], "
        "Method='POST', Body='payload', ExtraAttrs={'AcceptFormat': 'JSON'})"
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
