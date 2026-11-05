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

from dump_daemon.uipath_codegen import generate_python
from dump_daemon.uipath_dsl import (
    AssignNode,
    BreakNode,
    ClickNode,
    ForEachNode,
    IfNode,
    Literal,
    MessageBoxNode,
    ParallelNode,
    SequenceNode,
    SwitchArm,
    SwitchNode,
    TryCatchNode,
    CatchArm,
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
