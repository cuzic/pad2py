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

from dump_daemon.uipath_codegen import generate_project_python, generate_python
from dump_daemon.uipath_dsl import (
    AssignNode,
    BreakNode,
    ClickNode,
    ForEachNode,
    IfNode,
    InvokeWorkflowFileNode,
    Literal,
    MessageBoxNode,
    ParallelNode,
    SequenceNode,
    SwitchArm,
    SwitchNode,
    TryCatchNode,
    CatchArm,
    VariableDecl,
    VbExpr,
    WhileNode,
    WorkflowFile,
    parse_workflow_file,
)

FIXTURE_DIR = Path(__file__).parent.parent / "design" / "evidence" / "uipath_xaml_probe"


def _wrap(body) -> WorkflowFile:
    return WorkflowFile(class_name="Test", root=SequenceNode(body=body))


def _compiles(code: str) -> None:
    compile(code, "<generated>", "exec")


def test_assign_object_typed_expr():
    wf = _wrap([AssignNode(target=VbExpr(text="result"), value=VbExpr(text='"ok"'))])
    code = generate_python(wf)
    assert "result = 'ok'" in code
    _compiles(code)


def test_assign_unparseable_falls_back_to_todo():
    """文字列補間の中身は未対応——TODOコメント+`None`プレースホルダに倒れ、
    架空のf-string変換はでっち上げない。"""
    wf = _wrap([AssignNode(target=VbExpr(text="x"), value=VbExpr(text='$"v={x}"'))])
    code = generate_python(wf)
    assert "# TODO" in code
    assert "x = None" in code
    _compiles(code)


def test_message_box_maps_to_print():
    wf = _wrap([MessageBoxNode(text=Literal(value="hi"))])
    code = generate_python(wf)
    assert "print('hi')" in code
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
    assert "if (x) == ('ok'):" in code
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
    assert "while (x) != ('done'):" in code
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
    assert "if n == 1:" in code  # クォート無しの整数リテラル
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
    assert "if n == 'a':" in code
    _compiles(code)


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
    assert "pyperclip.copy('cliptext')" in code
    assert "try:" in code and "except Exception as exception:" in code
    assert "# TODO: unknown activity" in code  # Library呼び出し(p:NewActivity)


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
    簡略化——OutArgumentをPythonの`return`へ対応させることはv1スコープ外)。
    そのため`Greet`が受け取った引数を`MessageBox`で出力し、`Entry`から
    呼んだときにそれが実際に標準出力に現れることで連携を確認する。
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
