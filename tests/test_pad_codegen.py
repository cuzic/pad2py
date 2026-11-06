"""pad_codegen の単体テスト・結合テスト。

結合テストのフィクスチャは design/dsl_format_findings.md 知見14で実機から
キャプチャした、SET/IF+ELSE IF+ELSE(ネスト込み)/LOOP系3種/EXIT・NEXT LOOPを
網羅するg1g2_testフローの生データ。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import tempfile
from pathlib import Path

import pytest

from dump_daemon.control_repository import parse_control_repository
from dump_daemon.pad_codegen import (
    generate_python,
    render_condition,
    render_text_template,
    render_value,
)
from dump_daemon.pad_dsl import (
    EnumRef,
    VarRef,
    build_block_tree,
    parse_dsl,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"

FULL_FLOW_DSL = (
    "Display.ShowMessageDialog.ShowMessage Icon: Display.Icon.None Buttons: Display.Buttons.OK "
    "DefaultButton: Display.DefaultButton.Button1 IsTopMost: False ButtonPressed=> ButtonPressed\n"
    "IF TestVar = $'''hello''' THEN\n"
    "    IF InnerVar = $'''nested''' THEN\n"
    "    END\n"
    "ELSE IF TestVar = $'''world''' THEN\n"
    "ELSE\n"
    "    SET InnerVar TO $'''inside the if block'''\n"
    "    LOOP WHILE (LoopIndex) < (10)\n"
    "        EXIT LOOP\n"
    "        NEXT LOOP\n"
    "    END\n"
    "END\n"
    'SET TestVar TO $\'\'\'He said \\"hello\\" and used \\\\ in C:\\\\temp\\\\file.txt\'\'\'\n'
    "LOOP FOREACH CurrentItem IN TestVar\n"
    "END\n"
    "LOOP LoopIndex FROM 1 TO 3 STEP 1\n"
    "END\n"
    "Scripting.RunPythonScript.RunPythonScriptCPython PythonCode: $'''import urllib.request, json\n"
    'req = urllib.request.Request(\\"http://127.0.0.1:8765/capture\\", '
    'data=json.dumps({\\"action_id\\": \\"action1\\"}).encode(), method=\\"POST\\")\n'
    "urllib.request.urlopen(req, timeout=2)\n"
    "''' PythonPath: $'''C:\\\\Program Files\\\\Python312\\\\python.exe''' "
    "ScriptOutput=> PythonScriptOutput\n"
    "WAIT 1"
)


def test_render_value_distinguishes_varref_enumref_and_literals() -> None:
    assert render_value(VarRef("TestVar")) == "TestVar"
    assert render_value(EnumRef("Display.Icon.None")) == "'Display.Icon.None'"
    assert render_value("hello") == "'hello'"
    assert render_value(1) == "1"
    assert render_value(True) == "True"


def test_render_condition_maps_known_operators() -> None:
    # design/dsl_format_findings.md 知見18で実機確認した6種の比較演算子すべて。
    # 知見88: `=`/`<>`は数値を表す文字列と数値を型をまたいで等価と判定するため
    # 専用ヘルパー(expr_runtime.pad_equal)経由になる。
    assert (
        render_condition(VarRef("TestVar"), "=", "hello")
        == "expr_runtime.pad_equal(TestVar, 'hello')"
    )
    assert render_condition(VarRef("X"), "<>", 1) == "not expr_runtime.pad_equal(X, 1)"
    assert render_condition(VarRef("X"), ">", 1) == "X > 1"
    assert render_condition(VarRef("X"), ">=", 1) == "X >= 1"
    assert render_condition(VarRef("LoopIndex"), "<", 10) == "LoopIndex < 10"
    assert render_condition(VarRef("X"), "<=", 1) == "X <= 1"


def test_render_condition_rejects_unverified_operator() -> None:
    # Containsはそもそも中置演算子ではなく関数呼び出し構文(知見18-2)なので、
    # パーサーが対応していない現状では到達しえないはずだが、render_condition単体としても
    # 未知の演算子記号を渡されたら例外を出すことを確認する。
    with pytest.raises(ValueError, match="Unmapped PAD operator"):
        render_condition(VarRef("X"), "Contains", 1)


def test_generate_python_full_flow_compiles_as_valid_python() -> None:
    tree = build_block_tree(parse_dsl(FULL_FLOW_DSL))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")  # SyntaxErrorなしでコンパイルできること


def test_generate_python_renders_if_elif_else_and_nested_if() -> None:
    # 知見88: `=`は数値を表す文字列と数値を型をまたいで等価と判定するため
    # 専用ヘルパー(expr_runtime.pad_equal)経由になる。
    tree = build_block_tree(parse_dsl(FULL_FLOW_DSL))
    code = generate_python(tree)
    assert "if expr_runtime.pad_equal(TestVar, 'hello'):" in code
    assert "    if expr_runtime.pad_equal(InnerVar, 'nested'):" in code
    assert "elif expr_runtime.pad_equal(TestVar, 'world'):" in code
    assert "else:" in code


def test_generate_python_renders_loop_family() -> None:
    tree = build_block_tree(parse_dsl(FULL_FLOW_DSL))
    code = generate_python(tree)
    assert "while LoopIndex < 10:" in code
    assert "break" in code
    assert "continue" in code
    assert "for CurrentItem in TestVar:" in code
    # design/dsl_format_findings.md 知見51(実機検証済み): PADのLOOPはendを含まない
    # (Pythonのrange()と同じセマンティクス)。
    assert "for LoopIndex in range(1, 3, 1):" in code


def test_generate_python_inlines_run_python_script_body() -> None:
    tree = build_block_tree(parse_dsl(FULL_FLOW_DSL))
    code = generate_python(tree)
    assert "import urllib.request, json" in code
    assert 'req = urllib.request.Request("http://127.0.0.1:8765/capture"' in code


def test_generate_python_binds_script_output_to_captured_stdout() -> None:
    # ScriptOutput(DSL上のScriptOutput=>)が`print()`相当の標準出力を捕捉した値になることを
    # 確認した(正確な文字単位の書式——末尾改行・型変換——は未確認のため、生のテキストを
    # そのまま代入するだけの最小限の変換に留める)。
    dsl = "Scripting.RunPythonScript.RunPythonScriptCPython PythonCode: $'''print(1 + 1)''' ScriptOutput=> Out1"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "import contextlib" in code
    assert "import io" in code
    assert "with contextlib.redirect_stdout(io.StringIO()) as _pyscript_stdout:" in code
    assert "Out1 = _pyscript_stdout.getvalue()" in code
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    # 実行して、実際にprint()の内容が変数に渡ることを確認する(構文チェックだけでなく
    # 実際のランタイム挙動まで検証する)。
    assert namespace["Out1"] == "2\n"


def test_generate_python_script_exception_sets_empty_output_instead_of_propagating() -> None:
    # スクリプト自身が例外を投げても、それはON ERRORで捕捉可能な例外としては伝播せず、
    # ScriptOutputが空文字列になるだけでフロー自体は正常に続行することが確認できている
    # (インフラ的な失敗とユーザースクリプト自身の実行時エラーは別扱いになる)。これを反映し、
    # スクリプト本体の例外をtry/exceptで吸収し、出力変数を空文字列にすることを確認する
    # (でっち上げた例外伝播をせず、確認された「エラーは出力の空文字列化で吸収される」
    # 挙動に合わせる)。
    dsl = (
        "Scripting.RunPythonScript.RunPythonScriptCPython PythonCode: "
        "$'''raise ValueError(\"boom\")''' ScriptOutput=> Out1"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    namespace: dict[str, object] = {}
    exec(code, namespace)  # 例外が外へ伝播せず正常終了することそのものが検証対象
    assert namespace["Out1"] == ""


def test_generate_python_run_python_script_without_output_var_stays_unwrapped() -> None:
    # 出力変数束縛(ScriptOutput=>)が無い場合は、stdoutを捕捉する必要が無いので
    # 従来通りスクリプト本体をそのままインラインに展開するだけ(余計なラップをしない)。
    dsl = "Scripting.RunPythonScript.RunPythonScriptCPython PythonCode: $'''x = 1 + 1'''"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "contextlib" not in code
    assert "x = 1 + 1" in code


def test_generate_python_renders_wait_as_time_sleep() -> None:
    tree = build_block_tree(parse_dsl(FULL_FLOW_DSL))
    code = generate_python(tree)
    assert "import time" in code
    assert "time.sleep(1)" in code


def test_generate_python_marks_unmapped_action_with_todo_not_fabrication() -> None:
    tree = build_block_tree(parse_dsl(FULL_FLOW_DSL))
    code = generate_python(tree)
    # Display.ShowMessageDialog はまだUI automationへのマッピングが無いため、
    # 架空のAPI呼び出しをでっち上げず、TODOコメントになっていること。
    assert "# TODO: map PAD action: Display.ShowMessageDialog.ShowMessage" in code


def test_render_text_template_without_markers_is_plain_repr() -> None:
    assert render_text_template("no vars here") == repr("no vars here")


def test_render_text_template_converts_markers_to_fstring_braces() -> None:
    result = render_text_template("Hello %TestVar% world, LoopIndex is %LoopIndex%")
    assert result == 'f"""Hello {TestVar} world, LoopIndex is {LoopIndex}"""'
    compile(result, "<test>", "eval")


def test_render_text_template_doubles_literal_braces_in_fstring() -> None:
    result = render_text_template("value {x} here %Var%")
    assert result == 'f"""value {{x}} here {Var}"""'
    compile(result, "<test>", "eval")


def test_render_text_template_actually_substitutes_variable_values_at_runtime() -> None:
    # 実機で実際にキャプチャした値(design/dsl_format_findings.md 知見16)を使い、
    # 単に構文が通るだけでなく、生成されたf-stringが実行時に正しく変数を埋め込むことまで検証する。
    code = render_text_template("Hello %TestVar% world, LoopIndex is %LoopIndex%")
    namespace = {"TestVar": "hello", "LoopIndex": 5}
    result = eval(code, {}, namespace)  # noqa: S307 - テスト内でのみ使用する生成コードの評価
    assert result == "Hello hello world, LoopIndex is 5"


def test_generate_python_interpolates_text_template_set_variable() -> None:
    # 実機で確認したInterpVarのSET文(知見16)を結合テストでも確認する。
    dsl = "SET InterpVar TO $'''Hello %TestVar% world, LoopIndex is %LoopIndex%'''"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert 'InterpVar = f"""Hello {TestVar} world, LoopIndex is {LoopIndex}"""' in code


# 実機で「Send keys」(Text to send="Hello World", Delay between keystrokes=10,
# Send Text as hardware keys=False)を追加して再キャプチャした生データ(知見19)。
SEND_KEYS_DSL = (
    "MouseAndKeyboard.SendKeys.FocusAndSendKeys TextToSend: $'''Hello World''' "
    "DelayBetweenKeystrokes: 10 SendTextAsHardwareKeys: False"
)


def test_generate_python_maps_send_keys_to_pyautogui_typewrite() -> None:
    tree = build_block_tree(parse_dsl(SEND_KEYS_DSL))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "import pyautogui" in code
    assert "pyautogui.typewrite('Hello World', interval=0.01)" in code


def test_generate_python_full_flow_still_marks_display_message_as_todo() -> None:
    # SendKeysのマッピング追加後も、まだ対応していないアクション(Display message)は
    # 引き続きでっち上げずTODOのままであること(回帰確認)。
    tree = build_block_tree(parse_dsl(FULL_FLOW_DSL))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Display.ShowMessageDialog.ShowMessage" in code


# 実機で「Move mouse」(Position X=500, Position Y=300, Relative to=Screen(既定),
# Move mouse from previous position=Instant(既定))を追加して再キャプチャした生データ(知見20)。
MOVE_MOUSE_DSL = (
    "MouseAndKeyboard.MoveMouse X: 500 Y: 300 "
    "RelativeTo: MouseAndKeyboard.PositionRelativeTo.Screen "
    "MovementStyle: MouseAndKeyboard.MovementStyle.Instant"
)


def test_generate_python_maps_move_mouse_to_pyautogui_moveto() -> None:
    tree = build_block_tree(parse_dsl(MOVE_MOUSE_DSL))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "import pyautogui" in code
    assert "pyautogui.moveTo(500, 300)" in code


def test_generate_python_leaves_move_mouse_as_todo_when_relative_to_is_unverified() -> None:
    # RelativeToがScreen以外(未検証)の場合は、でっち上げず架空の変換をしないこと。
    dsl = (
        "MouseAndKeyboard.MoveMouse X: 10 Y: 20 "
        "RelativeTo: MouseAndKeyboard.PositionRelativeTo.Window "
        "MovementStyle: MouseAndKeyboard.MovementStyle.Instant"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: MouseAndKeyboard.MoveMouse" in code
    assert "pyautogui.moveTo" not in code


# 実機で「Send mouse click」(Mouse event to send=Left click(既定), Wait=0(既定),
# Move mouse=off(既定))を追加して再キャプチャした生データ(知見21)。
SEND_MOUSE_CLICK_DSL = (
    "MouseAndKeyboard.SendMouseClick.Click "
    "ClickType: MouseAndKeyboard.MouseClickType.LeftClick MillisecondsDelay: 0"
)


def test_generate_python_maps_left_click_to_pyautogui_click() -> None:
    tree = build_block_tree(parse_dsl(SEND_MOUSE_CLICK_DSL))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "pyautogui.click()" in code
    assert "time.sleep" not in code  # MillisecondsDelay=0なのでsleepは不要


def test_generate_python_inserts_sleep_before_click_when_delay_is_nonzero() -> None:
    dsl = (
        "MouseAndKeyboard.SendMouseClick.Click "
        "ClickType: MouseAndKeyboard.MouseClickType.LeftClick MillisecondsDelay: 500"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "import time" in code
    assert "time.sleep(0.5)" in code
    assert "pyautogui.click()" in code


def test_generate_python_leaves_send_mouse_click_as_todo_for_unverified_click_types() -> None:
    # Right click等(未検証)は推測でマッピングせずTODOのままであること。
    dsl = (
        "MouseAndKeyboard.SendMouseClick.Click "
        "ClickType: MouseAndKeyboard.MouseClickType.RightClick MillisecondsDelay: 0"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: MouseAndKeyboard.SendMouseClick.Click" in code
    assert "pyautogui.click" not in code


def test_generate_python_raises_clearly_for_contains_function_condition() -> None:
    # Containsはパーサー側では正しく構造化できる(design/dsl_format_findings.md 知見18-2の
    # バグ修正後)が、Pythonへの変換方法はまだ未検証なので、codegenは架空の変換をでっち上げず
    # はっきり失敗すること。
    dsl = "IF Contains(InnerVar, $'''nested''', False) THEN\nEND"
    tree = build_block_tree(parse_dsl(dsl))
    with pytest.raises(NotImplementedError, match="Contains"):
        generate_python(tree)


def test_generate_python_raises_clearly_for_if_window_action_condition() -> None:
    # design/dsl_format_findings.md 知見54: 「If window」等の[ConditionAction]カテゴリは
    # `IF (<ActionId> ...) THEN`という知見50のWAIT (...)と同じ丸括弧構文を条件式として使う。
    # パーサー側はIfActionRecordとして正しく構造化できるが、対象UI要素のセレクタがDSLから
    # 取得できない上、条件を誤訳すると制御フロー全体が反転するという危険な失敗モードになるため、
    # IfFunctionRecordと同じ方針でcodegenははっきり失敗すること(でっち上げた真偽値を出さない)。
    dsl = (
        "IF (UIAutomation.IfWindow.IsOpen Window: appmask['Window \\'Untitled - "
        "Notepad\\''] InstantCheck: False) THEN\nEND"
    )
    tree = build_block_tree(parse_dsl(dsl))
    with pytest.raises(NotImplementedError, match="UIAutomation.IfWindow.IsOpen"):
        generate_python(tree)


def test_generate_python_from_real_if_window_whole_subflow_capture_raises() -> None:
    # repositoryを渡さない場合は、知見56のセレクタ解決ができないため従来通り
    # NotImplementedErrorのまま(完全に後方互換)。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_if_window.txt").read_text(
        encoding="utf-8"
    )
    tree = build_block_tree(parse_dsl(text))
    with pytest.raises(NotImplementedError, match="UIAutomation.IfWindow.IsOpen"):
        generate_python(tree)


def test_generate_python_converts_if_window_is_open_when_selector_resolves() -> None:
    # `IsOpen`/`IsNotOpen`/`IsFocused`/`IsNotFocused`の4通りの単純な真偽値(複雑な設定モード
    # 無し)であることが確認できたため、知見56のセレクタ組み立てと組み合わせて実行コードを
    # 生成するようにした(IfImage/IfWindowContainsは複数の設定可能なサブモードを持ち複雑な
    # ため、依然NotImplementedErrorのまま)。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_if_window.txt").read_text(
        encoding="utf-8"
    )
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "if Desktop(backend=\"uia\").window(title='Untitled - Notepad').exists():" in code
    assert "NotImplementedError" not in code


@pytest.mark.parametrize(
    ("mode", "expected_condition"),
    [
        ("IsOpen", "Desktop(backend=\"uia\").window(title='Untitled - Notepad').exists()"),
        ("IsNotOpen", "not Desktop(backend=\"uia\").window(title='Untitled - Notepad').exists()"),
        (
            "IsFocused",
            "(Desktop(backend=\"uia\").window(title='Untitled - Notepad').exists() and "
            "Desktop(backend=\"uia\").window(title='Untitled - Notepad').wrapper_object().is_active())",
        ),
        (
            "IsNotFocused",
            "not (Desktop(backend=\"uia\").window(title='Untitled - Notepad').exists() and "
            "Desktop(backend=\"uia\").window(title='Untitled - Notepad').wrapper_object().is_active())",
        ),
    ],
)
def test_generate_python_converts_all_four_if_window_modes(mode: str, expected_condition: str) -> None:
    # 4つのWindowModeそれぞれの変換を確認する。
    # IsFocused/IsNotFocusedは、ウィンドウが存在しない場合にwrapper_object()が例外を
    # 投げてしまうのを避けるための防御的なexists()ガードを合成している(_render_if_window_
    # condition()のコメント参照)。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_if_window.txt").read_text(
        encoding="utf-8"
    )
    original_dsl = (
        "IF (UIAutomation.IfWindow.IsOpen Window: appmask['Window \\'Untitled - "
        "Notepad\\''] InstantCheck: False) THEN"
    )
    modified_dsl = (
        f"IF (UIAutomation.IfWindow.{mode} Window: appmask['Window \\'Untitled - "
        "Notepad\\''] InstantCheck: False) THEN"
    )
    assert original_dsl in text
    text = text.replace(original_dsl, modified_dsl)
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert f"if {expected_condition}:" in code


@pytest.mark.parametrize(
    ("mode", "window_exists", "window_active", "expected_result"),
    [
        ("IsOpen", True, True, True),
        ("IsOpen", False, False, False),
        ("IsNotOpen", True, True, False),
        ("IsNotOpen", False, False, True),
        ("IsFocused", True, True, True),
        ("IsFocused", True, False, False),
        ("IsFocused", False, False, False),  # 存在しないウィンドウ=exists()ガードで例外無しにFalse
        ("IsNotFocused", True, True, False),
        ("IsNotFocused", True, False, True),
        ("IsNotFocused", False, False, True),
    ],
)
def test_generate_python_if_window_modes_evaluate_correctly_against_fake_pywinauto(
    mode: str, window_exists: bool, window_active: bool, expected_result: bool
) -> None:
    # design/common_rpa_framework_roadmap.md 層7(b): 上の4テストは生成された条件式の
    # *文字列*しか検査していなかった——この条件式の本体は`pass`のみ(実機キャプチャに
    # THENブロックの中身が無いため)で、`exec()`しても分岐の実際の真偽は観測できない。
    # そこで生成コードを`exec()`した後の名前空間で条件式自体を`eval()`し、フェイクの
    # ウィンドウ状態(存在/フォーカス)を変えたときに正しい真偽値になることを検証する。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    text = (FIXTURES_DIR / "looptest_whole_subflow_with_if_window.txt").read_text(
        encoding="utf-8"
    )
    original_dsl = (
        "IF (UIAutomation.IfWindow.IsOpen Window: appmask['Window \\'Untitled - "
        "Notepad\\''] InstantCheck: False) THEN"
    )
    modified_dsl = (
        f"IF (UIAutomation.IfWindow.{mode} Window: appmask['Window \\'Untitled - "
        "Notepad\\''] InstantCheck: False) THEN"
    )
    text = text.replace(original_dsl, modified_dsl)
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    condition_source = code.splitlines()[2].removeprefix("if ").removesuffix(":")

    registry = FakeRegistry()
    if window_exists:
        registry.register_window(title="Untitled - Notepad")
        registry.set_active([{"title": "Untitled - Notepad"}], window_active)
    with fake_pywinauto_desktop(registry):
        namespace: dict[str, object] = {}
        exec(code, namespace)
        assert eval(condition_source, namespace) is expected_result


@pytest.mark.parametrize(
    ("mode", "expected_condition"),
    [
        ("IsOpenByInstanceOrHandle", "AutomationWindow2.exists()"),
        ("IsNotOpenByInstanceOrHandle", "not AutomationWindow2.exists()"),
        (
            "IsFocusedByInstanceOrHandle",
            "(AutomationWindow2.exists() and AutomationWindow2.wrapper_object().is_active())",
        ),
        (
            "IsNotFocusedByInstanceOrHandle",
            "not (AutomationWindow2.exists() and AutomationWindow2.wrapper_object().is_active())",
        ),
    ],
)
def test_generate_python_converts_if_window_by_instance_or_handle_modes(
    mode: str, expected_condition: str
) -> None:
    # design/dsl_format_findings.md 知見121(decompile確認済み): `IfWindow`も知見117〜120と
    # 同じ3セレクタ構造を4モードそれぞれに持つ(計12セレクタ)——`WindowInstance`ベースの
    # 兄弟セレクタ4つ。
    dsl = f"IF (UIAutomation.IfWindow.{mode} WindowInstance: AutomationWindow2) THEN\nSET X TO 1\nEND"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert f"if {expected_condition}:" in code
    assert "NotImplementedError" not in code


@pytest.mark.parametrize(
    ("mode", "expected_condition"),
    [
        ("IsOpenByTitleClass", "Desktop(backend='uia').window(title='Notepad').exists()"),
        ("IsNotOpenByTitleClass", "not Desktop(backend='uia').window(title='Notepad').exists()"),
        (
            "IsFocusedByTitleClass",
            "(Desktop(backend='uia').window(title='Notepad').exists() and "
            "Desktop(backend='uia').window(title='Notepad').wrapper_object().is_active())",
        ),
        (
            "IsNotFocusedByTitleClass",
            "not (Desktop(backend='uia').window(title='Notepad').exists() and "
            "Desktop(backend='uia').window(title='Notepad').wrapper_object().is_active())",
        ),
    ],
)
def test_generate_python_converts_if_window_by_title_class_modes(mode: str, expected_condition: str) -> None:
    # design/dsl_format_findings.md 知見121の追記: `Title`+`Class`ベースの兄弟セレクタ4つ。
    dsl = f"IF (UIAutomation.IfWindow.{mode} Title: $'''Notepad''' Class: $'''''') THEN\nSET X TO 1\nEND"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert f"if {expected_condition}:" in code
    assert "NotImplementedError" not in code


def test_generate_python_from_real_if_window_contains_element_whole_subflow_capture_raises() -> None:
    # design/dsl_format_findings.md 知見54の追記: 「If window contains element」も知見54の
    # IfActionRecord/_generate_conditional()のNotImplementedErrorフォールバックをそのまま
    # 再利用でき、コード変更は不要だった。
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_if_window_contains_element.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    with pytest.raises(
        NotImplementedError, match="UIAutomation.IfWindowContains.WindowContainsElement"
    ):
        generate_python(tree)


def test_generate_python_from_real_if_service_capture_raises() -> None:
    # design/dsl_format_findings.md 知見54の追記: 「If service」(Services.*名前空間)も
    # 同じNotImplementedErrorフォールバックをそのまま再利用でき、コード変更は不要だった。
    dsl = "IF (Services.IfService.IsRunning Service: $'''Spooler''') THEN\nEND"
    tree = build_block_tree(parse_dsl(dsl))
    with pytest.raises(NotImplementedError, match="Services.IfService.IsRunning"):
        generate_python(tree)


def test_generate_python_renders_wait_for_service_as_todo() -> None:
    # design/dsl_format_findings.md 知見50の追記: 「Wait for service」も知見50の
    # _generate_wait_action()のTODOフォールバックをそのまま再利用でき、コード変更は不要だった。
    dsl = "WAIT (Services.WaitForService.Started Service: $'''Spooler''')"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO: map PAD wait action: Services.WaitForService.Started (timeout: none)" in code


def test_generate_python_from_real_wait_for_window_become_focused_whole_subflow_capture_compiles() -> None:
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_become_focused.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "UIAutomation.WaitForWindow.ToBecomeFocused" in code


def test_generate_python_from_real_wait_for_window_lose_focus_whole_subflow_capture_compiles() -> None:
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_lose_focus.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "UIAutomation.WaitForWindow.ToLoseFocus" in code


# 実機で「Press/release key」をControl=True(他Falseのまま)でAction to perform=Press、
# 続けてAction to perform=Releaseに切り替えて再キャプチャした生データ(知見23)。
PRESS_CONTROL_DSL = "MouseAndKeyboard.PressReleaseKey.PressKey Control: True Alt: False Shift: False Win: False"
RELEASE_CONTROL_DSL = "MouseAndKeyboard.PressReleaseKey.ReleaseKey Control: True Alt: False Shift: False Win: False"


def test_generate_python_maps_press_key_to_pyautogui_keydown() -> None:
    tree = build_block_tree(parse_dsl(PRESS_CONTROL_DSL))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "pyautogui.keyDown('ctrl')" in code


def test_generate_python_maps_release_key_to_pyautogui_keyup() -> None:
    tree = build_block_tree(parse_dsl(RELEASE_CONTROL_DSL))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "pyautogui.keyUp('ctrl')" in code


def test_generate_python_leaves_press_key_as_todo_when_no_modifier_is_true() -> None:
    # 0個のモディファイアがTrue(未検証の組み合わせ)の場合は推測でマッピングしないこと。
    dsl = "MouseAndKeyboard.PressReleaseKey.PressKey Control: False Alt: False Shift: False Win: False"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: MouseAndKeyboard.PressReleaseKey.PressKey" in code
    assert "pyautogui.keyDown" not in code


# 実機で「Set window state」(Find window mode=By title and/or class, Window title=
# "Power Automate | g1g2_test", Window class=(空のまま), Window state=Maximized)を
# 追加して再キャプチャした生データ(知見24)。
SET_WINDOW_STATE_DSL = (
    "UIAutomation.SetWindowState.SetStateByTitleClass "
    "Title: $'''Power Automate | g1g2_test''' Class: $'''''' "
    "State: UIAutomation.WindowState.Maximized"
)


def test_generate_python_maps_set_window_state_to_pywinauto() -> None:
    tree = build_block_tree(parse_dsl(SET_WINDOW_STATE_DSL))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "from pywinauto import Desktop" in code
    assert "Desktop(backend='uia').window(title='Power Automate | g1g2_test').maximize()" in code


def test_generate_python_leaves_set_window_state_as_todo_when_class_is_used() -> None:
    # Window classを併用するケース(未検証)は推測でマッピングしないこと。
    dsl = (
        "UIAutomation.SetWindowState.SetStateByTitleClass "
        "Title: $'''Notepad''' Class: $'''Notepad''' "
        "State: UIAutomation.WindowState.Maximized"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: UIAutomation.SetWindowState.SetStateByTitleClass" in code
    assert "Desktop(" not in code


# 実機で「Move window」「Resize window」(いずれもFind window mode=By title and/or class,
# Window title="Power Automate | g1g2_test"(自動補完), Window class=空のまま)を
# 追加して再キャプチャした生データ(知見25)。
MOVE_WINDOW_DSL = (
    "UIAutomation.MoveWindow.MoveByTitleClass "
    "Title: $'''Power Automate | g1g2_test''' Class: $'''''' X: 100 Y: 50"
)
RESIZE_WINDOW_DSL = (
    "UIAutomation.ResizeWindow.ResizeByTitleClass "
    "Title: $'''Power Automate | g1g2_test''' Class: $'''''' Width: 1024 Height: 768"
)


def test_generate_python_maps_move_window_to_win32gui_move_window() -> None:
    # design/dsl_format_findings.md 知見119(実機確認済み): pywinautoの
    # `WindowSpecification`には`move_window()`メソッド自体が無い(UIAバックエンドで
    # `AttributeError`になることをVM上の実venvでNotepadを使い確認した)。
    # `win32gui.MoveWindow(hwnd, x, y, width, height, repaint)`に差し替えた
    # (Width/Heightは未指定のためその場の`GetWindowRect()`の値を保持する)。
    tree = build_block_tree(parse_dsl(MOVE_WINDOW_DSL))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "from pywinauto import Desktop" in code
    assert "import win32gui" in code
    assert "_hwnd = Desktop(backend='uia').window(title='Power Automate | g1g2_test').wrapper_object().handle" in code
    assert "_rect = win32gui.GetWindowRect(_hwnd)" in code
    assert "win32gui.MoveWindow(_hwnd, 100, 50, _rect[2] - _rect[0], _rect[3] - _rect[1], True)" in code


def test_generate_python_from_move_window_actually_moves_against_fake_win32() -> None:
    # design/common_rpa_framework_roadmap.md 層7(c): 上のテストは生成コードの文字列しか
    # 検査していなかった——`tests/fake_pywinauto.py`+`tests/fake_win32.py`を組み合わせて
    # 実際に`exec()`し、`win32gui.MoveWindow()`が正しい引数(既存の`GetWindowRect()`から
    # 幅/高さを保持しつつX/Yだけ更新)で呼ばれることを検証する。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop
    from fake_win32 import FakeWin32Registry, fake_win32_modules

    tree = build_block_tree(parse_dsl(MOVE_WINDOW_DSL))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")

    ui_registry = FakeRegistry()
    ui_registry.register_window(title="Power Automate | g1g2_test")
    win32_registry = FakeWin32Registry()
    win32_registry.set_rect(0, 10, 20, 810, 620)  # 既存の幅800・高さ600を保持する想定

    with fake_pywinauto_desktop(ui_registry), fake_win32_modules(win32_registry):
        exec(code, {})

    assert win32_registry.calls == [("MoveWindow", 0, 100, 50, 800, 600, True)]


def test_generate_python_maps_resize_window_to_win32gui_move_window() -> None:
    # design/dsl_format_findings.md 知見119: X/Yは未指定のためその場の`GetWindowRect()`の
    # 値を保持する。
    tree = build_block_tree(parse_dsl(RESIZE_WINDOW_DSL))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "win32gui.MoveWindow(_hwnd, _rect[0], _rect[1], 1024, 768, True)" in code


def test_generate_python_leaves_move_window_as_todo_when_class_is_used() -> None:
    dsl = "UIAutomation.MoveWindow.MoveByTitleClass Title: $'''Notepad''' Class: $'''Notepad''' X: 0 Y: 0"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: UIAutomation.MoveWindow.MoveByTitleClass" in code
    assert "Desktop(" not in code


def test_generate_python_maps_focus_window_to_pywinauto_set_focus() -> None:
    # design/dsl_format_findings.md 知見27(実機確認済み)。
    dsl = "UIAutomation.FocusWindow.FocusByTitleClass Title: $'''Notepad''' Class: $'''''' "
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "Desktop(backend='uia').window(title='Notepad').set_focus()" in code

    # design/common_rpa_framework_roadmap.md 層7(b): 文字列検査に加え、実際に`exec()`して
    # `.set_focus()`が正しいセレクタで呼ばれたことまで検証する。
    from fake_pywinauto import fake_pywinauto_desktop

    with fake_pywinauto_desktop() as registry:
        exec(code, {})
    assert registry.calls == [("set_focus", [{"title": "Notepad"}], {})]


def test_generate_python_maps_close_window_to_pywinauto_close() -> None:
    # 他のByTitleClass系アクションと同じパターンだと確認できている(action_id自体は実機未確認)。
    dsl = "UIAutomation.CloseWindow.CloseByTitleClass Title: $'''Notepad''' Class: $'''''' "
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "Desktop(backend='uia').window(title='Notepad').close()" in code

    from fake_pywinauto import fake_pywinauto_desktop

    with fake_pywinauto_desktop() as registry:
        exec(code, {})
    assert registry.calls == [("close", [{"title": "Notepad"}], {})]


def test_generate_python_leaves_focus_window_as_todo_when_class_is_used() -> None:
    dsl = "UIAutomation.FocusWindow.FocusByTitleClass Title: $'''Notepad''' Class: $'''Notepad''' "
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: UIAutomation.FocusWindow.FocusByTitleClass" in code
    assert "Desktop(" not in code


def test_generate_python_renders_comment_record_as_python_comment() -> None:
    # CommentRecord追加後、codegenがクラッシュせず正しくPythonコメントへ変換すること
    # (未対応のままだと_generate_node()がTypeErrorを送出していたはずの回帰確認)。
    tree = build_block_tree(parse_dsl("# hello comment"))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# hello comment" in code


def test_generate_python_splits_multiline_comment_into_one_hash_line_per_line() -> None:
    # Pythonの`#`コメントは1行ずつしか続けられないため、`/# ... #/`由来の
    # 埋め込み改行を含む CommentRecord.text は複数の`#`行に分割する必要がある
    # (そのまま1つの`# {text}`に入れると改行がコメント終端になりSyntaxErrorになる)。
    tree = build_block_tree(parse_dsl("/# line one\nline two #/"))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# line one" in code
    assert "# line two" in code


def test_generate_python_renders_switch_case_default_as_if_elif_else() -> None:
    # design/dsl_format_findings.md 知見33で実機確認した構造通り: CASE/DEFAULTはSWITCHより
    # 1段深いindent、各アームの本体はさらに1段深い。CASEには演算子(`=`)が明示される。
    # SwitchNodeに対する唯一のcodegenテスト——生成結果が実際にPythonとして正しく動くこと
    # (構文だけでなく実行結果も)をeval/execで確認する。
    dsl = (
        "SET Result TO $'''none'''\n"
        "SWITCH TestVar\n"
        "    CASE = $'''a'''\n"
        "        SET Result TO $'''matched a'''\n"
        "    CASE = $'''b'''\n"
        "        SET Result TO $'''matched b'''\n"
        "    DEFAULT\n"
        "        SET Result TO $'''matched default'''\n"
        "END"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "if expr_runtime.pad_equal(TestVar, 'a'):" in code
    assert "elif expr_runtime.pad_equal(TestVar, 'b'):" in code
    assert "else:" in code

    namespace: dict[str, object] = {"TestVar": "b"}
    exec(code, namespace)
    assert namespace["Result"] == "matched b"


def test_generate_python_renders_not_in_operator_as_python_not_in() -> None:
    # IN/NOT INのDSL表現は確定しており、Pythonのin/not inは意味的にそのまま対応するため
    # _OPERATOR_MAPに追加した(実機でどのUI経由で使われるかは未確認)。
    dsl = "IF TestVar NOT IN $'''list''' THEN\n    WAIT 1\nEND"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "if TestVar not in 'list':" in code


def test_generate_python_renders_guarded_node_as_try_except() -> None:
    # design/dsl_format_findings.md 知見34(実機確認済み、「All errors (default)」+
    # 「Continue flow run」の組み合わせのみ)。GuardedNodeに対する唯一のcodegenテスト——
    # 生成結果が実際にPythonとして正しく動くこと(構文だけでなく実行結果も、except節が
    # 本当に例外を捕捉してハンドラを実行することも)をexecで確認する。
    # `SET Result TO UndefinedVar`は未定義変数の参照(NameError)でON ERRORハンドラを誘発する。
    dsl = "SET Result TO UndefinedVar\nON ERROR\nSET Result TO $'''recovered'''\nEND"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "try:" in code
    assert "except Exception:" in code

    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["Result"] == "recovered"


def test_generate_python_leaves_multi_arm_on_error_as_todo() -> None:
    # design/dsl_format_findings.md 知見36(実機確認済み): 名前付きケース+catch-allが
    # 区切り無しに連続しうる。`RunPythonScriptError`は`pad_action_lib`のスコープ外
    # (Scripting系)のタグなので対応する例外クラスが無く、1つでも未知のタグがあると
    # 全アームを安全に`# TODO`へ丸ごと倒す(下の`test_generate_python_converts_named_on_error_arm...`
    # 系との対比——既知のタグなら実際に`except`節へ変換できる)。
    dsl = (
        "SET Result TO $'''a'''\n"
        "ON ERROR RunPythonScriptError\n"
        "SET Result TO $'''b'''\n"
        "ON ERROR\n"
        "SET Result TO $'''c'''\n"
        "END"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "Result = 'a'" in code
    assert "# TODO: ON ERROR/ON BLOCK ERROR handling not converted" in code
    assert "try:" not in code


def test_generate_python_converts_named_on_error_arm_to_known_tag_exception() -> None:
    # design/pad_todo.md A節: 知見36で確定した複数アーム構文に、知見73で`pad_action_lib`へ
    # 結線済みの`[Throws]`タグ例外クラス(`pad_action_lib.errors.PadActionError`の
    # サブクラス)を組み合わせる。タグ名(`CopyFileError`)がクラス名と一致する場合、
    # でっち上げではなく確認済みの対応関係として実際の`except`節に変換できる。
    dsl = (
        "File.Copy Files: $'''__nonexistent_source__.txt''' Destination: $'''__DEST_DIR__''' "
        "IfFileExists: File.IfExists.DoNothing CopiedFiles=> CopiedFiles\n"
        "ON ERROR CopyFileError\n"
        "SET NewVar2 TO $'''failed'''\n"
        "ON ERROR\n"
        "SET NewVar TO $'''recovered'''\n"
        "END"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "from dump_daemon.pad_action_lib import file_actions" in code
    assert "try:" in code
    assert "except file_actions.CopyFileError:" in code
    assert "except Exception:" in code
    assert "# TODO: ON ERROR" not in code

    # 実在するディレクトリを宛先にし、存在しないファイルをコピーさせて、確実に
    # `CopyFileError`(`InvalidDestinationFolderError`等ではなく)を発生させた上で
    # 本当にexcept節が捕捉してハンドラを実行することまで確認する。
    dest_dir = tempfile.mkdtemp()
    code_with_real_dest = code.replace("__DEST_DIR__", dest_dir)
    namespace: dict[str, object] = {}
    exec(code_with_real_dest, namespace)
    assert namespace["NewVar2"] == "failed"


def test_generate_python_converts_colliding_tag_name_to_tuple_of_all_matching_classes() -> None:
    # `FileNotFoundError`は`file_actions`/`compression_actions`/`cryptography_actions`に
    # それぞれ無関係な別クラスとして独立に存在する(同じタグ名を持つだけで継承関係は無い)。
    # DSL側だけではどのファミリーのタグかを判別できないため、安全側に全てをタプルで捕捉する。
    dsl = (
        "File.ReadTextFromFile.ReadText File: $'''a.txt''' Encoding: File.FileEncoding.Default "
        "ReadContent=> ReadContent\n"
        "ON ERROR FileNotFoundError\n"
        "SET NewVar2 TO $'''missing'''\n"
        "END"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "from dump_daemon.pad_action_lib import compression_actions" in code
    assert "from dump_daemon.pad_action_lib import cryptography_actions" in code
    assert "from dump_daemon.pad_action_lib import file_actions" in code
    assert (
        "except (compression_actions.FileNotFoundError, "
        "cryptography_actions.FileNotFoundError, file_actions.FileNotFoundError):"
    ) in code


def test_generate_python_falls_back_to_todo_when_named_arm_tag_is_unknown() -> None:
    # 既知のタグ(CopyFileError)と未知のタグが混在する場合も、部分的に変換すると保護範囲が
    # 歯抜けになり誤解を招くため、全アームを安全に`# TODO`へ丸ごと倒す。
    dsl = (
        "File.Copy Files: $'''source.txt''' Destination: $'''dest''' "
        "IfFileExists: File.IfExists.DoNothing CopiedFiles=> CopiedFiles\n"
        "ON ERROR CopyFileError\n"
        "SET NewVar2 TO $'''failed'''\n"
        "ON ERROR SomeTotallyUnknownTag\n"
        "SET NewVar3 TO $'''unknown'''\n"
        "END"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO: ON ERROR/ON BLOCK ERROR handling not converted" in code
    assert "except file_actions.CopyFileError:" not in code
    assert "try:" not in code


def test_generate_python_renders_on_block_error_as_try_except_with_pass_body() -> None:
    # design/dsl_format_findings.md 知見40(実機検証済み): PADの「On block error」が
    # 自動生成する空のBLOCKに「Go to next action」を設定して実機キャプチャした生データ
    # そのもの。BLOCK自体はPython側に対応する制御構文を持たないため本体は`pass`になり、
    # ハンドラ内の`NEXT ACTION`はPADのcase名同様マッピング未検証のため`# TODO`に倒れる
    # (でっち上げた`continue`/`break`等は生成しない)。
    dsl = "BLOCK \nON BLOCK ERROR\nNEXT ACTION\nEND"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "try:" in code
    assert "    pass" in code
    assert "except Exception:" in code
    assert "# TODO: unmapped keyword: NEXT ACTION" in code


def test_generate_python_renders_throw_error_as_todo_without_fabricating_raise() -> None:
    # design/dsl_format_findings.md 知見41(実機検証済み): 「Throw error」を選んだ
    # `ON BLOCK ERROR`本体の`THROW ERROR`はPythonの`raise`に素直に対応しそうに見えるが、
    # 何を`raise`すべきか(元の例外の再送出か、固定のエラーメッセージか)が実機未検証のため、
    # 安易に`raise`をでっち上げず`# TODO`コメントに倒す——`_ensure_nonempty_suite()`
    # (知見40で発見したバグの修正)のおかげでコメントだけの本体でも`pass`が補われ、
    # 生成コードはそのまま`compile()`できる。
    dsl = "BLOCK \nON BLOCK ERROR\nTHROW ERROR\nEND"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO: unmapped keyword: THROW ERROR" in code
    assert "raise" not in code


def test_generate_python_names_ui_element_in_todo_without_fabricating_selector() -> None:
    # design/dsl_format_findings.md 知見38・39・42・43: UI要素セレクタ(appmask['<表示名>']が
    # 指す実際のCSS風セレクタ文字列)はDSLテキストにもPADデザイナーUI/ローカルキャッシュ/
    # 個人アカウントでのPower Platformメーカーポータルのいずれにも存在せず、v1では変換不能と
    # 確定した(本プロジェクトの意図的なスコープ外)。でっち上げたセレクタを埋め込む代わりに、
    # `UiElementRef`の表示名だけをTODOコメントに残し、ユーザーが手動で補えるようにする。
    dsl = (
        "UIAutomation.Click.Click Element: appmask['Start Button'] "
        "ClickType: UIAutomation.ClickType.LeftClick "
        "MousePositionRelativeToElement: UIAutomation.RectangleEdgePoint.MiddleCenter "
        "OffsetX: 0 OffsetY: 0"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO: map PAD action: UIAutomation.Click.Click" in code
    assert "UI element: 'Start Button'" in code
    assert "appmask" not in code
    # design/pad_todo.md C節: 単体コピー(ControlRepositoryデータが一切無い)の場合は、
    # セレクタ不明の理由と対処法(広い範囲をコピーし直す)を直接案内する。
    assert "no ControlRepository data in input" in code


def test_generate_python_omits_no_repository_hint_when_repository_present_but_element_missing() -> None:
    # 上のテストとの対比: ControlRepositoryデータ自体は渡されているが、対象要素がその中に
    # 見つからない場合は「単体コピーだからデータが無い」という案内は的外れなので出さない
    # (従来通りの、セレクタ提案無しのTODOコメントのまま)。
    dsl = (
        "UIAutomation.Click.Click Element: appmask['Start Button'] "
        "ClickType: UIAutomation.ClickType.LeftClick "
        "MousePositionRelativeToElement: UIAutomation.RectangleEdgePoint.MiddleCenter "
        "OffsetX: 0 OffsetY: 0"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree, repository={"appmask": {}})
    compile(code, "<generated>", "exec")
    assert "# TODO: map PAD action: UIAutomation.Click.Click" in code
    assert "UI element: 'Start Button'" in code
    assert "no ControlRepository data in input" not in code
    assert "verified pywinauto selector" not in code


def test_generate_python_converts_click_click_to_click_input_when_selector_resolves() -> None:
    # design/dsl_format_findings.md 知見56: セレクタ式自体は実機(Notepadの実ウィンドウ)で
    # 対象要素を一意に特定できると確認済みで、`.click_input()`自体もpad_ui_helpers.pyで
    # G1/G2実機検証済みのpywinauto操作。確認済みのパラメータの組み合わせ(ClickType:
    # LeftClick等)でセレクタが解決できる場合に限り、TODOコメントではなく実行コードとして
    # 生成されるようになったことを確認する。
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_notepad_control_selector.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert (
        "Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".child_window(class_name='Edit').click_input()" in code
    )
    assert "# TODO: map PAD action: UIAutomation.Click.Click" not in code
    assert "appmask" not in code


def test_generate_python_from_click_click_actually_clicks_against_fake_pywinauto() -> None:
    # design/common_rpa_framework_roadmap.md 層7(検証基盤・シミュレータ)の第一歩:
    # 上の`test_generate_python_converts_click_click_to_click_input_when_selector_resolves`は
    # 生成コードを文字列として検査するだけだった——これは実際に`exec()`し、`tests/fake_pywinauto.py`
    # のフェイクUIツリー経由で「正しいセレクタ・正しい操作で呼ばれたか」を検証する。
    # 実Windows・実Notepad・実pywinautoバックエンドは一切不要(でっち上げ禁止の対象は
    # 「PAD/pywinautoの実際の挙動」であり、ここで検証しているのはpad_codegen自身が組み立てる
    # 呼び出し列の形だけなので、この原則とは無関係に安全)。
    import os

    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_notepad_control_selector.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")

    registry = FakeRegistry()
    registry.register_descendant({"title": "Untitled - Notepad"}, {"class_name": "Edit"})
    # このフィクスチャは`Scripting.RunPythonScript`でハードコードされたWindowsパス
    # (`C:\Users\...`)へのファイル書き込みも含む(知見14等のループ検証用の副産物)。
    # Linux上では`\`がパス区切りとして解釈されず、cwdに奇妙な名前のファイルが
    # 作られてしまうため、一時ディレクトリへ退避してから`exec()`する。
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as tmp, fake_pywinauto_desktop(registry):
        try:
            os.chdir(tmp)
            exec(code, {})
        finally:
            os.chdir(original_cwd)

    # looptest系フィクスチャ(ループ本体に同じクリックが複数回出現する)なので、
    # 「少なくとも1回、正しいセレクタ・正しい操作で呼ばれた」ことを検証する。
    assert registry.calls
    assert all(
        call == ("click_input", [{"title": "Untitled - Notepad"}, {"class_name": "Edit"}], {})
        for call in registry.calls
    )


def test_generate_python_keeps_click_click_as_todo_when_click_type_unverified() -> None:
    # design/dsl_format_findings.md 知見21と同じ方針: 実機確認済みなのは`ClickType:
    # LeftClick`(かつMiddleCenter・オフセット0/0)の組み合わせのみ。それ以外のクリック種別
    # (Right click等)はPythonでの対応が未検証のため、セレクタが解決できる場合でも
    # でっち上げた変換はせず安全なTODOのままにする。
    dsl = (
        "UIAutomation.Click.Click Element: appmask['Window \\'Untitled - Notepad\\'']"
        "['Document \\'Text Editor\\''] ClickType: UIAutomation.ClickType.RightClick "
        "MousePositionRelativeToElement: UIAutomation.RectangleEdgePoint.MiddleCenter "
        "OffsetX: 0 OffsetY: 0"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO: map PAD action: UIAutomation.Click.Click" in code
    assert "click_input" not in code


def test_generate_python_keeps_get_window_use_timeout_as_todo_when_bring_to_front_true() -> None:
    # 知見57: `BringWindowToFront: True`時の正確な意味論(`.set_focus()`相当か等)は
    # 実機未検証のため、セレクタが解決できてもTODOのままにする。
    fixture_text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_notepad_control_selector.txt"
    ).read_text(encoding="utf-8")
    repository = parse_control_repository(fixture_text)
    dsl = (
        "UIAutomation.GetWindow.GetUseTimeout Control: appmask['Window \\'Untitled - Notepad\\''] "
        "BringWindowToFront: True Timeout: 5 WindowInstance=> AutomationWindow2"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree, repository=repository)
    assert "# TODO: map PAD action: UIAutomation.GetWindow.GetUseTimeout" in code


def test_generate_python_keeps_click_click_as_todo_when_offset_unverified() -> None:
    # design/dsl_format_findings.md 知見38のDSLキャプチャ全件で確認済みなのは
    # OffsetX/OffsetY: 0のみ。非ゼロオフセットの実機挙動(pywinautoのcoords=指定が
    # 対応するか等)は未検証のため、セレクタが解決できてもTODOのままにする。
    dsl = (
        "UIAutomation.Click.Click Element: appmask['Window \\'Untitled - Notepad\\'']"
        "['Document \\'Text Editor\\''] ClickType: UIAutomation.ClickType.LeftClick "
        "MousePositionRelativeToElement: UIAutomation.RectangleEdgePoint.MiddleCenter "
        "OffsetX: 5 OffsetY: 0"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO: map PAD action: UIAutomation.Click.Click" in code
    assert "click_input" not in code


def test_generate_python_converts_wait_for_window_to_real_wait_when_timeout_given() -> None:
    # design/dsl_format_findings.md 知見50・56: セレクタがリポジトリから解決でき、かつ
    # 「Fail with timeout error」がONでタイムアウト秒数が実際に分かっている場合に限り、
    # pywinautoの`.wait("exists", timeout=...)`という実行コードを生成するようにした。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window.txt").read_text(
        encoding="utf-8"
    )
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert (
        "Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".wait('exists', timeout=5)" in code
    )
    assert "# TODO: map PAD wait action: UIAutomation.WaitForWindow.ToOpen" not in code


def test_generate_python_converts_wait_for_window_to_unbounded_poll_when_timeout_is_none() -> None:
    # design/dsl_format_findings.md 知見50の追記: 「Fail with timeout error」OFFで
    # `timeout_seconds`が`None`の場合、PADは50ミリ秒間隔で無期限にポーリングを続け、
    # タイムアウトによる失敗が一切発生しない(条件が満たされるかフロー自体がキャンセル
    # されるまで待ち続ける)ことが確認できている。この意味論をでっち上げた有限タイムアウト
    # 値(pywinautoの`.wait()`任せ)に丸めず、同じ`while`+`time.sleep(0.05)`ポーリングとして
    # 再現する。
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_no_timeout.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert (
        "while not Desktop(backend=\"uia\").window(title='Untitled - Notepad').exists():"
        in code
    )
    assert "    time.sleep(0.05)" in code
    assert "# TODO: map PAD wait action: UIAutomation.WaitForWindow.ToOpen" not in code


def test_generate_python_from_real_whole_subflow_capture_compiles() -> None:
    # design/dsl_format_findings.md 知見44・45: LoopTestサブフロー8アクションを一括選択して
    # コピーした実機生データ(UI要素リポジトリのJSONを含む)をフルパイプラインに通した
    # End-to-Endの回帰テスト。知見1以来、1〜4アクションの個別コピーでしか検証してこな
    # かった「whole-flow copy」の経路を初めて検証する。知見45の通りネストしたBLOCKの
    # ON BLOCK ERRORのインデントがずれるため理想的な構造にはならないが、クラッシュせず
    # 構文的に正しいPythonを生成できることを保証する。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_control_repository.txt").read_text(
        encoding="utf-8"
    )
    tree = build_block_tree(parse_dsl(text))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "ControlRepositorySymbols" not in code
    assert "appmask" not in code
    assert "UI element: 'Start Button'" in code


def test_generate_python_shows_full_path_for_nested_ui_element_reference() -> None:
    # design/dsl_format_findings.md 知見46: appmask['<祖先>']['<対象>']のような複数セグメント
    # の参照(メモ帳のテキスト編集領域、実機キャプチャ)では、TODOコメントに祖先から対象
    # までのフルパスを表示し、でっち上げたセレクタは埋め込まない。
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_notepad_control_selector.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "ControlRepositorySymbols" not in code
    assert "appmask" not in code
    assert "\"Window 'Untitled - Notepad'\" > \"Document 'Text Editor'\"" in code


def test_generate_python_renders_label_as_comment_and_leaves_goto_as_todo() -> None:
    # design/dsl_format_findings.md 知見48: `LABEL <名前>`はジャンプ先マーカーとして
    # コメントに残すが、Pythonに`goto`文は無いため`GOTO <名前>`をでっち上げた制御フロー
    # (例外・whileループへの書き換え等)に変換することはせず、素直に`# TODO`へ倒す。
    dsl = "LABEL MyLabel\nSET TestVar TO $'''hello'''\nGOTO MyLabel"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# label: MyLabel" in code
    assert "# TODO: unmapped keyword: GOTO MyLabel" in code


def test_generate_python_renders_wait_action_as_todo_with_timeout_and_ui_element() -> None:
    # design/dsl_format_findings.md 知見50: `WAIT (<ActionId> ...) FOR <秒数>`構文は
    # pywinautoの`WindowSpecification.wait("exists", timeout=...)`に自然に対応しそうに
    # 見えるが、対象のセレクタ自体がDSLから取得できない(知見38・46と同じ制約)ため、
    # でっち上げたセレクタを埋め込まず、action_id・タイムアウト秒数・UI要素の表示名を
    # TODOコメントに残すだけに留める。
    dsl = (
        "WAIT (UIAutomation.WaitForWindow.ToOpen Window: appmask['Window \\'Untitled - "
        "Notepad\\''] FocusWindow: False) FOR 5"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO: map PAD wait action: UIAutomation.WaitForWindow.ToOpen (timeout: 5s)" in code
    assert "UI element: \"Window 'Untitled - Notepad'\"" in code
    assert "appmask" not in code


def test_generate_python_converts_compound_set_variable_expression_to_real_python() -> None:
    # design/dsl_format_findings.md 知見53(実機DSL表現)・知見81(演算子の優先順位を実機確認)。
    # `SET ... TO`の右辺が複合式(AND/OR/XOR/NOT・算術式)になるケース(知見49の続き)。
    # 優先順位が実機確認済みのため、`mod`/`/`を含まない場合は実際のPython式へ変換する。
    dsl = "SET NewVar3 TO 1 = 1 AND 2 = 2 OR NOT 3 = 4"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    # 知見88: `=`は専用ヘルパー(expr_runtime.pad_equal)経由になる。
    assert (
        "NewVar3 = expr_runtime.pad_equal(1, 1) and expr_runtime.pad_equal(2, 2) "
        "or not expr_runtime.pad_equal(3, 4)" in code
    )
    assert "# TODO" not in code

    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["NewVar3"] is True  # (1=1) AND (2=2) OR (NOT (3=4)) = True


def test_generate_python_converts_xor_in_set_variable_expression_to_bool_inequality() -> None:
    # 知見81: 実機キャプチャされたXORの被演算子は常に比較式/真偽値リテラルだったため、
    # 論理XOR(`bool(a) != bool(b)`)として解釈する。
    dsl = "SET Result TO True XOR True AND False"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "Result = bool(True) != bool(True and False)" in code
    assert "# TODO" not in code

    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["Result"] is True  # True XOR (True AND False) = True XOR False = True


def test_generate_python_converts_arithmetic_precedence_in_set_variable_expression() -> None:
    # 知見81: `1 + 2 * 3`が実機で`*`優先(7)と確認済み。知見86で`+`は
    # expr_runtime.pad_add()に委譲するよう結線されたため、`*`の結果が
    # pad_add()の第2引数になる。
    dsl = "SET Result TO 1 + 2 * 3"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "Result = expr_runtime.pad_add(1, 2 * 3)" in code
    assert "# TODO" not in code

    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["Result"] == 7


def test_generate_python_converts_division_to_python_division() -> None:
    # design/dsl_format_findings.md 知見82(実機確認済み): `/`は常に浮動小数点除算で
    # Pythonの`/`と一致する(`7 / 2 = 3.5`・`-7 / 2 = -3.5`)。
    dsl = "SET Result TO -7 / 2"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "Result = -7 / 2" in code
    assert "# TODO" not in code

    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["Result"] == -3.5


def test_generate_python_converts_mod_to_math_fmod() -> None:
    # design/dsl_format_findings.md 知見82(実機確認済み): `mod`の符号は被除数と一致し
    # (C言語のfmodと同じ)、Pythonの`%`(符号は除数と一致)とは異なる
    # (`-7 mod 3 = -1`・`7 mod -3 = 1`、Pythonの`%`ならそれぞれ`2`・`-2`になり食い違う)。
    dsl = "SET Result1 TO -7 mod 3\nSET Result2 TO 7 mod -3"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "import math" in code
    assert "Result1 = math.fmod(-7, 3)" in code
    assert "Result2 = math.fmod(7, -3)" in code
    assert "# TODO" not in code

    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["Result1"] == -1
    assert namespace["Result2"] == 1


def test_generate_python_converts_plus_to_pad_add_for_numeric_string_coercion() -> None:
    # design/dsl_format_findings.md 知見86(実機確認済み): `+`は両辺が数値(または数値を
    # 表す文字列)として解釈できる場合は数値加算を行う(`1 + "2" = 3`・`"2" + 1 = 3`、
    # Pythonの素直な`+`なら前者はTypeError、後者は`"21"`になり食い違う)。
    dsl = "SET Result1 TO 1 + $'''2'''\nSET Result2 TO $'''2''' + 1"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "from dump_daemon.pad_action_lib import expr_runtime" in code
    assert "Result1 = expr_runtime.pad_add(1, '2')" in code
    assert "Result2 = expr_runtime.pad_add('2', 1)" in code
    assert "# TODO" not in code

    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["Result1"] == 3
    assert namespace["Result2"] == 3


def test_generate_python_converts_plus_to_string_concat_when_not_numeric() -> None:
    # design/dsl_format_findings.md 知見86(実機確認済み): どちらかが数値として解釈
    # できない文字列の場合は文字列結合にフォールバックする(`"a" + "b" = "ab"`)。
    dsl = "SET Result TO $'''a''' + $'''b'''"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code

    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["Result"] == "ab"


def test_generate_python_from_real_knowledge53_compound_arithmetic_expression_converts() -> None:
    # design/dsl_format_findings.md 知見53の実機キャプチャそのもの(`SET NewVar3 TO
    # 1 + 2 * 3 - 4 / 2 mod 3`)。知見82でmod/除算の値の意味論も確認済みのため、
    # 実際に計算できるPython式へ変換されることを確認する:
    # (1 + 2*3) - ((4/2) mod 3) = 7 - fmod(2.0, 3) = 7 - 2.0 = 5.0
    dsl = "SET NewVar3 TO 1 + 2 * 3 - 4 / 2 mod 3"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code

    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["NewVar3"] == 5.0


def test_generate_python_falls_back_to_todo_for_func_call_in_compound_expression() -> None:
    # `pad_expr`モジュールのdocstring: SET式の中の関数呼び出しは文法上受理されるが実機未確認の
    # 拡張のため、でっち上げたコードを出力せず安全にTODOへ倒れることを確認する。
    dsl = "SET Result TO Contains(Var1, Var2)"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD compound expression for variable 'Result': Contains(Var1, Var2)" in code


def test_generate_python_from_real_wait_for_window_whole_subflow_capture_compiles() -> None:
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window.txt").read_text(
        encoding="utf-8"
    )
    tree = build_block_tree(parse_dsl(text))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO: map PAD wait action: UIAutomation.WaitForWindow.ToOpen" in code


def test_generate_python_renders_wait_action_without_timeout_as_none() -> None:
    # design/dsl_format_findings.md 知見50の追記: 「Fail with timeout error」OFFで
    # `FOR <秒数>`句自体が無い場合、`timeout_seconds`が`None`になり、`render_value(None)`は
    # 未対応の値型で例外になるため、TODOコメントでは"timeout: none"と表示するよう別扱いする。
    dsl = (
        "WAIT (UIAutomation.WaitForWindow.ToOpen Window: appmask['Window \\'Untitled - "
        "Notepad\\''] FocusWindow: False)"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO: map PAD wait action: UIAutomation.WaitForWindow.ToOpen (timeout: none)" in code


def test_generate_python_from_real_wait_for_window_no_timeout_whole_subflow_capture_compiles() -> None:
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_no_timeout.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "(timeout: none)" in code


def test_generate_python_from_real_wait_for_window_content_whole_subflow_capture_compiles() -> None:
    # design/dsl_format_findings.md 知見52: 「Wait for window content」も知見50の
    # WaitActionRecord/_generate_wait_action()をそのまま再利用でき、コード変更は不要だった。
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_content.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert (
        "# TODO: map PAD wait action: "
        "UIAutomation.WaitForWindowContent.WindowToContainElement (timeout: none)" in code
    )


def test_generate_python_from_real_goto_label_whole_subflow_capture_compiles() -> None:
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_goto_label.txt").read_text(
        encoding="utf-8"
    )
    tree = build_block_tree(parse_dsl(text))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# label: MyLabel" in code
    assert "# TODO: unmapped keyword: GOTO MyLabel" in code


def test_generate_python_from_real_get_window_use_timeout_capture_converts_to_window_lookup() -> (
    None
):
    # design/dsl_format_findings.md 知見56・57・81(実機確認済み): かつては「window
    # instance」の表現方法が未解決のため`GetWindow.GetUseTimeout`はTODO+セレクタ提案の
    # ヒント止まりだったが、知見81の作業中に「window instanceはPAD側では単なる変数名
    # (VarRef)であり、Python側もpywinautoのWindowSpecificationをそのまま代入するだけで
    # 特別な結線が不要」と気づき、実行コードへ格上げした(BringWindowToFront: False時のみ)。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_get_window.txt").read_text(
        encoding="utf-8"
    )
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "AutomationWindow2 = Desktop(backend=\"uia\").window(title='Untitled - Notepad')" in code
    assert "# TODO: map PAD action: UIAutomation.GetWindow.GetUseTimeout" not in code


def test_generate_python_from_get_window_get_selector_without_timeout_converts() -> None:
    # design/dsl_format_findings.md 知見117(decompile確認済み): `.Get`は`.GetUseTimeout`
    # の兄弟セレクタ(`UseTimeout: False`固定、`Timeout`パラメータ自体が存在しない)で、
    # 実機キャプチャは無いが知見57・81で確立済みの結線がそのまま使える——`.GetUseTimeout`
    # の実機キャプチャ(`looptest_whole_subflow_with_get_window.txt`)のDSL/リポジトリを
    # action_idだけ差し替えた合成テキストで確認する。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_get_window.txt").read_text(
        encoding="utf-8"
    )
    text = text.replace(
        "UIAutomation.GetWindow.GetUseTimeout Control: appmask['Window \\'Untitled - Notepad\\''] "
        "BringWindowToFront: False Timeout: 5 WindowInstance=> AutomationWindow2",
        "UIAutomation.GetWindow.Get Control: appmask['Window \\'Untitled - Notepad\\''] "
        "BringWindowToFront: False WindowInstance=> AutomationWindow2",
    )
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "AutomationWindow2 = Desktop(backend=\"uia\").window(title='Untitled - Notepad')" in code
    assert "# TODO: map PAD action: UIAutomation.GetWindow.Get" not in code


def test_generate_python_from_close_window_close_selector_converts() -> None:
    # design/dsl_format_findings.md 知見117の追記(decompile確認済み): `CloseWindow`の
    # `.Close`は`GetWindow.Get`と全く同じ構造(`Control`ベース)の兄弟セレクタ。
    # VM上の実venvで`Desktop(...).window(...).close()`が実際にウィンドウを閉じる
    # ことを確認した(Notepadで実機確認)。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_get_window.txt").read_text(
        encoding="utf-8"
    )
    text = text.replace(
        "UIAutomation.GetWindow.GetUseTimeout Control: appmask['Window \\'Untitled - Notepad\\''] "
        "BringWindowToFront: False Timeout: 5 WindowInstance=> AutomationWindow2",
        "UIAutomation.CloseWindow.Close Control: appmask['Window \\'Untitled - Notepad\\'']",
    )
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "Desktop(backend=\"uia\").window(title='Untitled - Notepad').close()" in code
    assert "# TODO: map PAD action: UIAutomation.CloseWindow.Close" not in code


def test_generate_python_from_focus_window_focus_selector_converts() -> None:
    # design/dsl_format_findings.md 知見117の追記: `FocusWindow.Focus`も同じ構造。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_get_window.txt").read_text(
        encoding="utf-8"
    )
    text = text.replace(
        "UIAutomation.GetWindow.GetUseTimeout Control: appmask['Window \\'Untitled - Notepad\\''] "
        "BringWindowToFront: False Timeout: 5 WindowInstance=> AutomationWindow2",
        "UIAutomation.FocusWindow.Focus Control: appmask['Window \\'Untitled - Notepad\\'']",
    )
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "Desktop(backend=\"uia\").window(title='Untitled - Notepad').set_focus()" in code
    assert "# TODO: map PAD action: UIAutomation.FocusWindow.Focus" not in code


def test_generate_python_from_focus_window_by_instance_or_handle_converts() -> None:
    # design/dsl_format_findings.md 知見117の追記: `FocusWindow.FocusByInstanceOrHandle`は
    # `CloseWindow.CloseByInstanceOrHandle`(知見57実機確認済み)と全く同じ構造の兄弟セレクタ。
    dsl = "UIAutomation.FocusWindow.FocusByInstanceOrHandle WindowInstance: AutomationWindow2"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "AutomationWindow2.set_focus()" in code
    assert "# TODO" not in code


def test_generate_python_from_move_window_by_instance_or_handle_converts() -> None:
    # design/dsl_format_findings.md 知見119(decompile+実機確認済み)。
    dsl = "UIAutomation.MoveWindow.MoveByInstanceOrHandle WindowInstance: AutomationWindow2 X: 10 Y: 20"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "_hwnd = AutomationWindow2.wrapper_object().handle" in code
    assert "win32gui.MoveWindow(_hwnd, 10, 20, _rect[2] - _rect[0], _rect[3] - _rect[1], True)" in code
    assert "# TODO" not in code


def test_generate_python_from_resize_window_by_instance_or_handle_converts() -> None:
    dsl = "UIAutomation.ResizeWindow.ResizeByInstanceOrHandle WindowInstance: AutomationWindow2 Width: 640 Height: 480"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "win32gui.MoveWindow(_hwnd, _rect[0], _rect[1], 640, 480, True)" in code
    assert "# TODO" not in code


def test_generate_python_from_set_window_state_by_instance_or_handle_converts() -> None:
    dsl = (
        "UIAutomation.SetWindowState.SetStateByInstanceOrHandle WindowInstance: AutomationWindow2 "
        "State: UIAutomation.WindowState.Maximized"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "AutomationWindow2.maximize()" in code
    assert "# TODO" not in code


def test_generate_python_from_set_window_visibility_by_instance_or_handle_converts() -> None:
    # design/dsl_format_findings.md 知見120(decompile+実機確認済み): `UIAutomation.
    # Actions.dll`に完全に未結線だった`SetWindowVisibility`アクション(3セレクタ構造)を
    # 発見・結線した。`win32gui.ShowWindow(hwnd, SW_HIDE)`がVM上の実venvで実際に
    # ウィンドウを非表示にすることを確認した(`win32gui.IsWindowVisible()`で確認)。
    dsl = (
        "UIAutomation.SetWindowVisibility.SetVisibilityByInstanceOrHandle "
        "WindowInstance: AutomationWindow2 Visibility: UIAutomation.Visibility.Hidden"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "win32gui.ShowWindow(AutomationWindow2.wrapper_object().handle, win32con.SW_HIDE)" in code
    assert "import win32con" in code
    assert "# TODO" not in code


def test_generate_python_from_set_window_visibility_by_title_class_converts() -> None:
    dsl = (
        "UIAutomation.SetWindowVisibility.SetVisibilityByTitleClass Title: $'''Notepad''' Class: $'''''' "
        "Visibility: UIAutomation.Visibility.Visible"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert (
        "win32gui.ShowWindow(Desktop(backend='uia').window(title='Notepad').wrapper_object().handle, "
        "win32con.SW_SHOW)" in code
    )


def test_generate_python_from_set_window_visibility_control_based_converts() -> None:
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_get_window.txt").read_text(
        encoding="utf-8"
    )
    text = text.replace(
        "UIAutomation.GetWindow.GetUseTimeout Control: appmask['Window \\'Untitled - Notepad\\''] "
        "BringWindowToFront: False Timeout: 5 WindowInstance=> AutomationWindow2",
        "UIAutomation.SetWindowVisibility.SetVisibility Control: appmask['Window \\'Untitled - Notepad\\''] "
        "Visibility: UIAutomation.Visibility.Hidden",
    )
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert (
        "win32gui.ShowWindow(Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".wrapper_object().handle, win32con.SW_HIDE)" in code
    )
    assert "# TODO: map PAD action: UIAutomation.SetWindowVisibility.SetVisibility" not in code

    # design/common_rpa_framework_roadmap.md 層7(b)(c): 文字列検査に加えて、実際に
    # `exec()`してフェイク越しに`win32gui.ShowWindow(..., win32con.SW_HIDE)`が呼ばれる
    # ことまで検証する。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop
    from fake_win32 import FakeWin32Registry, fake_win32_modules

    ui_registry = FakeRegistry()
    ui_registry.register_window(title="Untitled - Notepad")
    win32_registry = FakeWin32Registry()

    with fake_pywinauto_desktop(ui_registry), fake_win32_modules(win32_registry):
        exec(code, {})

    assert ("ShowWindow", 0, 0) in win32_registry.calls  # handle=0(フェイク既定), SW_HIDE=0


def test_generate_python_from_move_window_control_based_converts() -> None:
    # design/dsl_format_findings.md 知見119: `Control`ベースの兄弟セレクタ(`.Move`)。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_get_window.txt").read_text(
        encoding="utf-8"
    )
    text = text.replace(
        "UIAutomation.GetWindow.GetUseTimeout Control: appmask['Window \\'Untitled - Notepad\\''] "
        "BringWindowToFront: False Timeout: 5 WindowInstance=> AutomationWindow2",
        "UIAutomation.MoveWindow.Move Control: appmask['Window \\'Untitled - Notepad\\''] X: 10 Y: 20",
    )
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "_hwnd = Desktop(backend=\"uia\").window(title='Untitled - Notepad').wrapper_object().handle" in code
    assert "win32gui.MoveWindow(_hwnd, 10, 20, _rect[2] - _rect[0], _rect[3] - _rect[1], True)" in code
    assert "# TODO: map PAD action: UIAutomation.MoveWindow.Move" not in code


def test_generate_python_from_set_window_state_control_based_converts() -> None:
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_get_window.txt").read_text(
        encoding="utf-8"
    )
    text = text.replace(
        "UIAutomation.GetWindow.GetUseTimeout Control: appmask['Window \\'Untitled - Notepad\\''] "
        "BringWindowToFront: False Timeout: 5 WindowInstance=> AutomationWindow2",
        "UIAutomation.SetWindowState.SetState Control: appmask['Window \\'Untitled - Notepad\\''] "
        "State: UIAutomation.WindowState.Minimized",
    )
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "Desktop(backend=\"uia\").window(title='Untitled - Notepad').minimize()" in code
    assert "# TODO: map PAD action: UIAutomation.SetWindowState.SetState" not in code


def test_generate_python_omits_selector_hint_when_repository_not_given() -> None:
    # design/dsl_format_findings.md 知見56: `repository`省略時は完全に従来通りの挙動
    # (ヒント無し)で、後方互換性を保つ。
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_content.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    code = generate_python(tree)
    assert "verified pywinauto selector" not in code


def test_generate_python_from_cryptography_encrypt_decrypt_text_without_dpapi_key_round_trips() -> None:
    # 実機キャプチャ(tier1_crypto_database_batch7.txt)はEncryptionKey/DecryptionKeyが
    # 常にWindows DPAPI保護値(P'<base64>'、知見72)で現れVarRefへフォールバックするため
    # TODOのまま残る(知見109のCompression.Passwordと同じパターン)——鍵がふつうの変数
    # 参照の場合の結線自体を、実際にEncryptText→DecryptTextの往復を実行して確認する
    # (知見111)。パラメータ名はPaddingMode(Encrypt側)/Padding(Decrypt側)という実機の
    # 非対称な命名をそのまま使う。
    dsl = (
        "SET Key TO $'''mysecret'''\n"
        "Cryptography.EncryptText.EncryptTextWithAES Encoding: Cryptography.EncryptionEncoding.Unicode "
        "TextToEncrypt: $'''hello world''' EncryptionKey: Key "
        "PaddingMode: Cryptography.PaddingMode.PKCS7 KeySize: Cryptography.AESKeySize.Bits256 "
        "EncryptedText=> Enc\n"
        "Cryptography.DecryptText.DecryptTextWithAES Encoding: Cryptography.EncryptionEncoding.Unicode "
        "TextToDecrypt: Enc DecryptionKey: Key "
        "Padding: Cryptography.PaddingMode.PKCS7 KeySize: Cryptography.AESKeySize.Bits256 "
        "DecryptedText=> Dec"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["Dec"] == "hello world"
    assert namespace["Enc"] != "hello world"


def test_generate_python_from_cryptography_hash_with_key_without_dpapi_key_converts() -> None:
    # HashTextWithKey/HashFromFileWithKeyも同じDPAPI鍵パターン(知見111)。
    dsl = (
        "SET Key TO $'''mysecret'''\n"
        "Cryptography.HashTextWithKey HashAlgorithm: Cryptography.KeyedHashAlgorithm.HMACSHA256 "
        "Encoding: Cryptography.EncryptionEncoding.Unicode TextToHash: $'''hello''' HashKey: Key "
        "HashedText=> Hashed"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "Hashed = cryptography_actions.hash_text_with_key('hello', Key, "
        "encoding='Unicode', hash_algorithm='HMACSHA256')" in code
    )
    namespace: dict[str, object] = {}
    exec(code, namespace)
    expected = hmac.new(
        "mysecret".encode("utf-16-le"), "hello".encode("utf-16-le"), hashlib.sha256
    ).digest()
    assert namespace["Hashed"] == base64.b64encode(expected).decode("ascii")


def test_generate_python_from_cryptography_encrypt_decrypt_file_without_dpapi_key_round_trips() -> None:
    # EncryptFromFile/DecryptToFileも同じDPAPI鍵パターン(知見111)——実ファイルで
    # 暗号化→復号の往復を実行して確認する。
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src_file = tmp_path / "plain.txt"
        src_file.write_bytes(b"secret bytes")
        dest_dir = tmp_path / "decrypted.bin"

        dsl = (
            "SET Key TO $'''mysecret'''\n"
            f"Cryptography.EncryptFromFile.EncryptFromFileWithAES Encoding: Cryptography.EncryptionEncoding.Unicode "
            f"FileToEncrypt: $'''{src_file}''' EncryptionKey: Key "
            "PaddingMode: Cryptography.PaddingMode.PKCS7 KeySize: Cryptography.AESKeySize.Bits256 "
            "EncryptedText=> Enc\n"
            "Cryptography.DecryptToFile.DecryptToFileWithAES Encoding: Cryptography.EncryptionEncoding.Unicode "
            f"TextToDecrypt: Enc DecryptToFile: $'''{dest_dir}''' DecryptionKey: Key "
            "IfFileExists: Cryptography.IfFileExists.Overwrite "
            "Padding: Cryptography.PaddingMode.PKCS7 KeySize: Cryptography.AESKeySize.Bits256 "
            "DecryptedFile=> DecFile"
        )
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        namespace: dict[str, object] = {}
        exec(code, namespace)
        assert dest_dir.read_bytes() == b"secret bytes"


def test_generate_python_converts_start_button_pseudo_selector_to_win_key_press() -> None:
    # design/dsl_format_findings.md 知見44: 「Start Button」のような特殊な擬似セレクタ
    # (`CustomValue: ":startbutton"`、`Attributes: []`)は、使える属性が1つも無いため
    # 通常のpywinautoセレクタ式(`_build_pywinauto_selector_expr()`)は組み立てられない。
    # でっち上げた属性ベースのセレクタを提案する代わりに、`:startbutton`はPAD固有の
    # 推測ではなくWindows自体の既知の仕組み(Winキー押下でスタートメニューの開閉を
    # トグル)に対応する固定のOS要素であるため、Winキー押下へ安全に対応付ける。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_control_repository.txt").read_text(
        encoding="utf-8"
    )
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "pyautogui.press('win')" in code


def test_generate_python_chains_all_elements_of_a_multi_element_internal_selector() -> None:
    # design/dsl_format_findings.md 知見56の追記(実機検証済み・バグ修正): 1つの
    # ControlRepositoryEntryのselectors[0]自体が複数のControlRepositorySelectorElementから
    # なる内部チェーンになりうる例を、電卓の「7」ボタン(appmask['Window \'Calculator\'']
    # ['Button \'7\'']、「Button '7'」エントリ自体がpane(Class: CalcFrame)→
    # button(Class: Button, Name: 7)という2段チェーン)で実機確認した。
    # 修正前は`entry.selectors[0][0]`(チェーンの最初の1要素)だけを見ていたため、
    # 実際にはボタンではなく中間のpane要素(実機でcontrol_type: Paneと確認)を指す
    # 誤った式(`child_window(class_name="CalcFrame")`止まり)を生成してしまっていた。
    # 修正後はチェーンの全要素をそれぞれ別個の`.child_window(...)`として連ね、
    # 実機で電卓の実際の「7」ボタン(control_type: Button, name: 7)を正しく一意に
    # 特定できる式を生成することを確認した。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_calculator_button.txt").read_text(
        encoding="utf-8"
    )
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    # このフィクスチャの電卓「7」ボタンへのUIAutomation.Click.Clickは、確認済みの
    # パラメータの組み合わせ(ClickType: LeftClick等)なので、知見56のチェーン修正後の
    # 正しいセレクタ式を使った実行コード(.click_input())として生成されるようになった
    # (以前はTODOコメント中の提案止まりだった——詳細は_generate_action()のコメント参照)。
    assert (
        'Desktop(backend="uia").window(title=\'Calculator\')'
        ".child_window(class_name='CalcFrame').child_window(class_name='Button', title='7')"
        ".click_input()" in code
    )
    # バグがあった頃の誤った(中間のpane止まりの)式が生成されていないことも確認する。
    assert 'window(title=\'Calculator\').child_window(class_name=\'CalcFrame\'))' not in code


def test_generate_python_from_real_get_window_whole_subflow_capture_compiles() -> None:
    # design/dsl_format_findings.md 知見57: GetWindow(UIAutomation.GetWindow.GetUseTimeout)は
    # 未対応アクションとして知見38/46と同じ安全なTODOフォールバックに倒れ、架空のウィンドウ
    # インスタンス変換をでっち上げないことを確認する。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_get_window.txt").read_text(
        encoding="utf-8"
    )
    tree = build_block_tree(parse_dsl(text))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO: map PAD action: UIAutomation.GetWindow.GetUseTimeout" in code


def test_generate_python_from_real_close_window_by_instance_handle_capture_converts() -> None:
    # design/dsl_format_findings.md 知見57・81: `WindowInstance`は裸の変数参照として
    # 直列化されると実機確認済み(GetWindow.GetUseTimeoutの出力変数と同じ変数名を参照する
    # 設計)。知見81の作業でwindow instanceが単なる変数参照であることに気づいたため、
    # 同じ変数へ`.close()`を呼ぶ実コードへ格上げした。
    text = (FIXTURES_DIR / "closewindow_by_instance.txt").read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "AutomationWindow2.close()" in code
    assert "# TODO: map PAD action: UIAutomation.CloseWindow.CloseByInstanceOrHandle" not in code


def test_generate_python_from_get_window_foreground_mode_with_two_output_vars_compiles() -> None:
    # design/dsl_format_findings.md 知見117(decompile+実機確認済み): `UIAutomation.
    # Actions.dll`を逆コンパイルし`GetForegroundWindow`が`Control`を使わない第3の
    # セレクタだと確認、`win32gui.GetForegroundWindow()`+`Desktop(backend="uia").
    # window(handle=...)`で実機が正しいフォアグラウンドウィンドウを返すことをVM上の
    # 実venvで確認した——以前は未対応としてTODOフォールバックのままにしていた。
    dsl = "UIAutomation.GetWindow.GetForegroundWindow WindowTitle=> WindowTitle2 WindowInstance=> AutomationWindow2"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert "AutomationWindow2 = Desktop(backend=\"uia\").window(handle=win32gui.GetForegroundWindow())" in code
    assert "WindowTitle2 = AutomationWindow2.window_text()" in code


def test_generate_python_from_real_if_image_exists_on_screen_capture_raises() -> None:
    # design/dsl_format_findings.md 知見58: 「If image」(UIAutomation.IfImage.ExistsOnScreen)も
    # 知見54のIfActionRecord/NotImplementedErrorフォールバックをそのまま再利用でき、
    # コード変更は不要だった——画像マッチングのPython対応(pyautogui.locateOnScreen等)は
    # 実機検証が無いため、架空の変換をでっち上げずはっきり失敗させる。
    text = (FIXTURES_DIR / "if_image_exists_on_screen.txt").read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    with pytest.raises(NotImplementedError, match="UIAutomation.IfImage.ExistsOnScreen"):
        generate_python(tree)


def test_generate_python_from_real_if_function_contains_batch_converts_all_four() -> None:
    # design/dsl_format_findings.md 知見75: クリップボードへのペースト+コピー読み取りによる
    # 往復確認(RDP不要、PADデザイナー自体がContains/NotContains/IsEmpty/IsNotEmptyという
    # 4つの関数名を認識し、エラー無く自然文表示することを実機確認済み)。
    text = (FIXTURES_DIR / "if_function_contains_notcontains_isempty_isnotempty.txt").read_text(
        encoding="utf-8"
    )
    tree = build_block_tree(parse_dsl(text))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "if Var2 in Var1:" in code
    assert "if Var2 not in Var1:" in code
    assert "if not Var1:" in code
    assert "if bool(Var1):" in code
    assert "# TODO" not in code
    assert "NotImplementedError" not in code

    namespace: dict[str, object] = {}
    exec(code, namespace)  # 実際に真偽値として正しく評価できることまで確認する


def test_generate_python_from_unknown_function_condition_raises() -> None:
    # 知見75の対照実験(`Blurgle(Var1, Var1)`はPAD自身に認識されず"Has error"になった)と
    # 同じ理由で、既知の4関数以外は安全にNotImplementedErrorへ倒す。
    dsl = "SET Var1 TO $'''hello'''\nIF Blurgle(Var1, Var1) THEN\nSET Var2 TO $'''x'''\nEND"
    tree = build_block_tree(parse_dsl(dsl))
    with pytest.raises(NotImplementedError, match="Blurgle"):
        generate_python(tree)


def test_generate_python_from_pdf_extract_text_minimal_params_uses_defaults() -> None:
    # design/dsl_format_findings.md 知見78: `Pdf.ExtractTextFromPDF`というaction_idは
    # 知見75の「貼り付け→コピー読み戻し」往復確認ではなく、(1)decompileしたaction_id
    # 構築式、(2)PADデザイナー自身のUI要素AutomationId、(3)検索+`set_focus()`+`{ENTER}`で
    # PADデザイナー自身が実際にエラー無く受理、という3経路収束による確証——よって以下のDSL
    # 行は実機キャプチャではなく、その確証にもとづき手書きした合成(synthetic)テキスト。
    # オプション引数(PagesToExtract/PageNumber/FromPageNumber/ToPageNumber/Password/
    # DetectLayout)を省略した最小形――PAD UI側でデフォルトのまま変更していない場合に
    # 一致する、他のTier1/2アクション(例: file.py/compression.pyのPassword省略)と同じ挙動。
    dsl = "Pdf.ExtractTextFromPDF PDFFile: $'''C:\\test.pdf''' ExtractedText=> ExtractedText"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "from dump_daemon.pad_action_lib import pdf_actions" in code
    assert (
        "ExtractedText = pdf_actions.extract_text_from_pdf('C:\\\\test.pdf', "
        "pages_to_extract='All', page_number=0, from_page_number=0, to_page_number=0, "
        "password='', detect_layout=False)" in code
    )
    assert "# TODO" not in code


def test_generate_python_from_pdf_extract_text_all_params_given_converts() -> None:
    # 知見78と同じ合成(synthetic)テキスト――オプション引数を全て明示した場合の経路。
    dsl = (
        "Pdf.ExtractTextFromPDF PDFFile: $'''C:\\test.pdf''' "
        "PagesToExtract: Pdf.ExtractionMode.SinglePage PageNumber: 2 FromPageNumber: 1 "
        "ToPageNumber: 3 Password: $'''secret''' DetectLayout: True "
        "ExtractedText=> ExtractedText"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert (
        "ExtractedText = pdf_actions.extract_text_from_pdf('C:\\\\test.pdf', "
        "pages_to_extract='SinglePage', page_number=2, from_page_number=1, to_page_number=3, "
        "password='secret', detect_layout=True)" in code
    )
    assert "# TODO" not in code


def test_generate_python_from_pdf_extract_text_without_output_var_falls_back_to_todo() -> None:
    # `node.output_var`無しは実機では起こらない想定外の形だが、でっち上げたコードを
    # 出力せず安全にTODOへ倒ることを確認する(他のTier1/2アクションと同じ安全策)。
    dsl = "Pdf.ExtractTextFromPDF PDFFile: $'''C:\\test.pdf'''"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Pdf.ExtractTextFromPDF" in code


def test_generate_python_from_pdf_extract_images_minimal_params_uses_defaults() -> None:
    # design/dsl_format_findings.md 知見79: 知見78と同じ3経路収束(decompile式・UI自身の
    # AutomationId・set_focus()+{ENTER}でのPADデザイナー自身による実機受理)で
    # `Pdf.ExtractImagesFromPDF`を確認済み。PAD側に`OutputArgument`が無い(ファイル書き出し
    # のみ)ため、他のアクションと違い`node.output_var`を要求しない。
    dsl = (
        "Pdf.ExtractImagesFromPDF PDFFile: $'''C:\\test.pdf''' "
        "ImagesFolder: $'''C:\\out''' ImagesName: $'''page'''"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "from dump_daemon.pad_action_lib import pdf_actions" in code
    assert (
        "pdf_actions.extract_images_from_pdf('C:\\\\test.pdf', 'C:\\\\out', 'page', "
        "pages_to_extract='All', page_number=0, from_page_number=0, to_page_number=0, "
        "password='')" in code
    )
    assert "# TODO" not in code


def test_generate_python_from_pdf_extract_tables_all_params_given_converts() -> None:
    # 知見79と同じ合成(synthetic)テキスト。
    dsl = (
        "Pdf.ExtractTablesFromPDF PDFFile: $'''C:\\test.pdf''' "
        "PagesToExtract: Pdf.ExtractionMode.All MultiPageTables: False "
        "SetFirstRowAsHeader: False ExtractedPDFTables=> Tables"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert (
        "Tables = pdf_actions.extract_tables_from_pdf('C:\\\\test.pdf', pages_to_extract='All', "
        "page_number=0, from_page_number=0, to_page_number=0, password='', "
        "multi_page_tables=False, set_first_row_as_header=False)" in code
    )
    assert "# TODO" not in code


def test_generate_python_from_pdf_extract_pages_minimal_params_uses_defaults() -> None:
    # 知見79と同じ合成(synthetic)テキスト。`Pdf.ExtractPages`はExtractPagesToNewPDFAction
    # (`[Action(Name=...)]`のみで`Id`属性が無い点がExtractTextFromPDF等とは異なる)。
    dsl = (
        "Pdf.ExtractPages PDFFile: $'''C:\\test.pdf''' ExtractedPDFPath: $'''C:\\out.pdf''' "
        "PageSelection: $'''1,3-5''' ExtractedPDFFile=> NewPDF"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert (
        "NewPDF = pdf_actions.extract_pages_to_new_pdf('C:\\\\test.pdf', 'C:\\\\out.pdf', "
        "'1,3-5', password='', if_file_exists='AddSequentialSuffix')" in code
    )
    assert "# TODO" not in code


def test_generate_python_from_pdf_merge_files_minimal_params_uses_defaults() -> None:
    # 知見79と同じ合成(synthetic)テキスト。`PDFFiles`は`Files`系と同じ単一/リスト正規化を使う。
    dsl = (
        "Pdf.MergeFiles PDFFiles: $'''C:\\a.pdf''' MergedPDFPath: $'''C:\\merged.pdf''' "
        "MergedPDF=> Merged"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert (
        "Merged = pdf_actions.merge_pdf_files(('C:\\\\a.pdf' if isinstance('C:\\\\a.pdf', list) "
        "else ['C:\\\\a.pdf']), 'C:\\\\merged.pdf', if_file_exists='AddSequentialSuffix')" in code
    )
    assert "# TODO" not in code


def test_generate_python_from_pdf_merge_files_with_passwords_falls_back_to_todo() -> None:
    # `Passwords`(EncryptableObject+PasswordDelimiter区切り)の実機シリアライズ形式は
    # 未確認のため、指定されている場合は安全にTODOへ倒れることを確認する。
    dsl = (
        "Pdf.MergeFiles PDFFiles: $'''C:\\a.pdf''' MergedPDFPath: $'''C:\\merged.pdf''' "
        "Passwords: $'''secret''' MergedPDF=> Merged"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Pdf.MergeFiles" in code


def test_generate_python_from_excel_full_scope_in_batch_converts_all_actions() -> None:
    # design/dsl_format_findings.md 知見80: Excel.*のaction_idは全て、PADデザイナー自身の
    # 検索結果TreeItemのAutomationIdを直接読んで実機確認済み(知見77と同じ経路、キーボード
    # 追加さえ不要)。パラメータ名はdocs-local/pad_excel_findings.mdのdecompile調査から。
    # `Instance`はPAD側では不透明な参照だが、Python側では他の変数参照と同じ
    # (ここではLaunchExcelの出力変数名をそのまま後続アクションに渡す)。
    dsl = (
        "Excel.LaunchExcel LaunchExcelMode: Excel.LaunchExcelMode.NewDocument "
        "ReadOnly: False Instance=> ExcelInstance\n"
        "Excel.AddWorksheet Instance: ExcelInstance Name: $'''Sheet2''' "
        "WorksheetPosition: Excel.WorksheetPosition.Last\n"
        "Excel.WriteToExcel Instance: ExcelInstance Value: $'''hello''' "
        "WriteMode: Excel.WriteExcelMode.SpecifiedCell Column: $'''B''' Row: 2\n"
        "Excel.ReadFromExcel Instance: ExcelInstance "
        "ReadMode: Excel.ReadExcelCellsMode.SingleCell StartColumn: $'''B''' StartRow: 2 "
        "CellValue=> CellValue\n"
        "Excel.DeleteWorksheet Instance: ExcelInstance "
        "FindWorksheetBy: Excel.FindWorksheetBy.Name Name: $'''Sheet2'''\n"
        "Excel.RenameWorksheet Instance: ExcelInstance NewName: $'''Renamed''' "
        "FindWorksheetBy: Excel.FindWorksheetBy.Index Index: 0\n"
        "Excel.SetActiveWorksheet Instance: ExcelInstance "
        "FindWorksheetBy: Excel.FindWorksheetBy.Name Name: $'''Renamed'''\n"
        "Excel.GetActiveWorksheet Instance: ExcelInstance "
        "Name=> SheetName Index=> SheetIndex\n"
        "Excel.GetAllWorksheets Instance: ExcelInstance Worksheets=> SheetNames\n"
        "Excel.GetColumnName CellColumnIndex: 28 ColumnName=> ColumnName\n"
        "Excel.GetFirstFreeColumnRow Instance: ExcelInstance "
        "FirstFreeColumn=> FreeCol FirstFreeRow=> FreeRow\n"
        "Excel.GetFirstFreeRowOnColumn Instance: ExcelInstance Column: $'''A''' "
        "FirstFreeRowOnColumn=> FreeRowOnA\n"
        "Excel.SaveExcel Instance: ExcelInstance SaveMode: Excel.SaveExcelMode.Save\n"
        "Excel.CloseExcel Instance: ExcelInstance CloseMode: Excel.CloseExcelMode.DoNotSave"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "from dump_daemon.pad_action_lib import excel_actions" in code
    assert (
        "ExcelInstance = excel_actions.launch_excel("
        "launch_excel_mode='NewDocument', path=None, read_only=False)" in code
    )
    assert "excel_actions.add_worksheet(ExcelInstance, 'Sheet2', worksheet_position='Last')" in code
    assert (
        "excel_actions.write_to_excel(ExcelInstance, 'hello', write_mode='SpecifiedCell', "
        "column='B', row=2, cell_name='', write_to_all_cells=False)" in code
    )
    assert (
        "CellValue = excel_actions.read_from_excel(ExcelInstance, read_mode='SingleCell', "
        "start_column='B', start_row=2, end_column='A', end_row=1, cell_name='', "
        "first_line_is_header=False, trim_empty_cells=False)" in code
    )
    assert (
        "excel_actions.delete_worksheet(ExcelInstance, find_worksheet_by='Name', "
        "name='Sheet2', index=0)" in code
    )
    assert (
        "excel_actions.rename_worksheet(ExcelInstance, 'Renamed', find_worksheet_by='Index', "
        "name='', index=0)" in code
    )
    assert (
        "excel_actions.set_active_worksheet(ExcelInstance, find_worksheet_by='Name', "
        "name='Renamed', index=0)" in code
    )
    assert "_active_worksheet = excel_actions.get_active_worksheet(ExcelInstance)" in code
    assert "SheetName = _active_worksheet[0]" in code
    assert "SheetIndex = _active_worksheet[1]" in code
    assert "SheetNames = excel_actions.get_all_worksheets(ExcelInstance)" in code
    assert "ColumnName = excel_actions.get_column_name(28)" in code
    assert "_first_free = excel_actions.get_first_free_column_row(ExcelInstance)" in code
    assert "FreeCol = _first_free[0]" in code
    assert "FreeRow = _first_free[1]" in code
    assert (
        "FreeRowOnA = excel_actions.get_first_free_row_on_column(ExcelInstance, 'A')" in code
    )
    assert "excel_actions.save_excel(ExcelInstance, save_mode='Save', document_path=None)" in code
    assert (
        "excel_actions.close_excel(ExcelInstance, close_mode='DoNotSave', document_path=None)"
        in code
    )
    assert "# TODO" not in code


def test_generate_python_from_excel_unsupported_live_com_modes_fall_back_to_todo() -> None:
    # ライブExcel UIの「現在の選択範囲/アクティブセル」依存の値は、openpyxlベースの
    # バックエンドでは意味を持たないため(docs-local/pad_excel_findings.md)、でっち上げた
    # コードを出力せず安全にTODOへ倒れることを確認する。
    read_selection_dsl = (
        "Excel.ReadFromExcel Instance: ExcelInstance "
        "ReadMode: Excel.ReadExcelCellsMode.Selection CellValue=> CellValue"
    )
    tree = build_block_tree(parse_dsl(read_selection_dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Excel.ReadFromExcel" in code

    write_active_cell_dsl = (
        "Excel.WriteToExcel Instance: ExcelInstance Value: $'''x''' "
        "WriteMode: Excel.WriteExcelMode.ActiveCell"
    )
    tree = build_block_tree(parse_dsl(write_active_cell_dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Excel.WriteToExcel" in code

    plain_text_dsl = (
        "Excel.ReadFromExcel Instance: ExcelInstance "
        "GetCellContentsMode: Excel.GetCellContentsMode.PlainText CellValue=> CellValue"
    )
    tree = build_block_tree(parse_dsl(plain_text_dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Excel.ReadFromExcel" in code


def test_generate_python_from_word_full_scope_in_batch_converts_all_actions() -> None:
    # design/dsl_format_findings.md 知見80: Word.*のaction_idは全て、PADデザイナー自身の
    # 検索結果TreeItemのAutomationIdを直接読んで実機確認済み。パラメータ名は
    # docs-local/pad_word_findings.mdのdecompile調査から。
    dsl = (
        "Word.LaunchWord LaunchWordMode: Word.LaunchWordMode.NewDocument "
        "ReadOnly: False Instance=> WordInstance\n"
        "Word.WriteToWord Instance: WordInstance Text: $'''hello''' "
        "WriteMode: Word.WriteWordMode.EndOfDocument\n"
        "Word.ReadFromWord Instance: WordInstance "
        "ReadMode: Word.ReadWordMode.WholeDocument WordData=> WordData\n"
        "Word.FindAndReplaceWord Instance: WordInstance TextToFind: $'''a''' "
        "TextToReplaceWith: $'''b''' AllMatches: True\n"
        "Word.SaveWord Instance: WordInstance SaveMode: Word.SaveWordMode.Save\n"
        "Word.CloseWord Instance: WordInstance CloseMode: Word.CloseWordMode.DoNotSave"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "from dump_daemon.pad_action_lib import word_actions" in code
    assert (
        "WordInstance = word_actions.launch_word(mode='NewDocument', path=None, "
        "read_only=False)" in code
    )
    assert (
        "word_actions.write_to_word(WordInstance, 'hello', append_new_line=False, "
        "write_mode='EndOfDocument', bookmark='')" in code
    )
    assert (
        "WordData = word_actions.read_from_word(WordInstance, read_mode='WholeDocument', "
        "pages='1', bookmark='')" in code
    )
    assert (
        "word_actions.find_and_replace_word(WordInstance, 'a', 'b', all_matches=True, "
        "match_case=False, match_entire_word=False, match_wild_cards=False)" in code
    )
    assert (
        "word_actions.save_word(WordInstance, save_mode='Save', "
        "document_format='FromExtension', document_path=None)" in code
    )
    assert (
        "word_actions.close_word(WordInstance, close_mode='DoNotSave', "
        "document_format='FromExtension', document_path=None)" in code
    )
    assert "# TODO" not in code


def test_generate_python_from_word_unsupported_modes_fall_back_to_todo() -> None:
    # ページ/ブックマーク系はライブWordのレンダリング/ライブコレクション依存のため
    # pad_action_lib側がNotImplementedErrorにする——でっち上げたコードを出力せず安全に
    # TODOへ倒れることを確認する。既知のMatchWildCards=Trueリテラルも同様。
    page_mode_dsl = (
        "Word.ReadFromWord Instance: WordInstance ReadMode: Word.ReadWordMode.Page "
        "WordData=> WordData"
    )
    tree = build_block_tree(parse_dsl(page_mode_dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Word.ReadFromWord" in code

    bookmark_write_dsl = (
        "Word.WriteToWord Instance: WordInstance Text: $'''x''' "
        "WriteMode: Word.WriteWordMode.StartOfBookmark"
    )
    tree = build_block_tree(parse_dsl(bookmark_write_dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Word.WriteToWord" in code

    wildcard_dsl = (
        "Word.FindAndReplaceWord Instance: WordInstance TextToFind: $'''a''' "
        "TextToReplaceWith: $'''b''' MatchWildCards: True"
    )
    tree = build_block_tree(parse_dsl(wildcard_dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Word.FindAndReplaceWord" in code


def test_generate_python_from_powerpoint_full_scope_batch_converts_all_actions() -> None:
    # design/dsl_format_findings.md 知見80: PowerPoint.*のaction_idも同じ経路で実機確認済み。
    # パラメータ名はdocs-local/pad_powerpoint_findings.mdのdecompile調査から。
    dsl = (
        "PowerPoint.LaunchPowerPoint LaunchPowerPointMode: "
        "PowerPoint.LaunchPowerPointMode.NewPresentation ReadOnly: False "
        "Instance=> PPTInstance\n"
        "PowerPoint.AddPowerPointSlide Instance: PPTInstance "
        "AddSlidePosition: PowerPoint.AddSlidePosition.LastSlide SlideIndex=> NewSlideIndex\n"
        "PowerPoint.WriteToPowerPoint Instance: PPTInstance Text: $'''hello''' "
        "WriteMode: PowerPoint.WriteMode.FirstSlide\n"
        "PowerPoint.ReadFromPowerPoint Instance: PPTInstance "
        "ReadMode: PowerPoint.ReadMode.WholePresentation PowerPointData=> PPTData\n"
        "PowerPoint.DeletePowerPointSlide Instance: PPTInstance "
        "DeleteSlidePosition: PowerPoint.DeleteSlidePosition.LastSlide\n"
        "PowerPoint.MovePowerPointSlide SourceInstance: PPTInstance SourceSlidePosition: 1 "
        "DestinationInstance: PPTInstance DestinationSlidePosition: 2\n"
        "PowerPoint.SavePowerPoint Instance: PPTInstance "
        "SaveMode: PowerPoint.SaveMode.Save\n"
        "PowerPoint.ClosePowerPoint Instance: PPTInstance "
        "CloseMode: PowerPoint.CloseMode.DoNotSave"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "from dump_daemon.pad_action_lib import powerpoint_actions" in code
    assert (
        "PPTInstance = powerpoint_actions.launch_power_point(mode='NewPresentation', "
        "path=None, read_only=False)" in code
    )
    assert (
        "NewSlideIndex = powerpoint_actions.add_power_point_slide(PPTInstance, "
        "add_slide_position='LastSlide', slide_position=1)" in code
    )
    assert (
        "powerpoint_actions.write_to_power_point(PPTInstance, 'hello', "
        "append_new_line=False, write_mode='FirstSlide', slide_position=1)" in code
    )
    assert (
        "PPTData = powerpoint_actions.read_from_power_point(PPTInstance, "
        "read_mode='WholePresentation', slides='1')" in code
    )
    assert (
        "powerpoint_actions.delete_power_point_slide(PPTInstance, "
        "delete_slide_position='LastSlide', slide_position=1)" in code
    )
    assert (
        "powerpoint_actions.move_power_point_slide(PPTInstance, 1, PPTInstance, 2)" in code
    )
    assert (
        "powerpoint_actions.save_power_point(PPTInstance, save_mode='Save', "
        "document_format='FromExtension', document_path=None)" in code
    )
    assert (
        "powerpoint_actions.close_power_point(PPTInstance, close_mode='DoNotSave', "
        "document_format='FromExtension', document_path=None)" in code
    )
    assert "# TODO" not in code


def test_generate_python_from_real_pad_expr_precedence_run_compiles() -> None:
    # design/dsl_format_findings.md 知見81: 「Run」ボタンを.invoke()で呼び実機で実際に
    # フローを実行し、5つの式の計算結果(7/True/True/True/False)をファイル経由で確認した
    # 実機キャプチャ。`File.WriteText`呼び出しを含むため(Windowsパス宛の実I/O)、ここでは
    # compile()のみ行いexec()はしない(exec()ベースの数値検証は上の単体テストで実施済み)。
    text = (FIXTURES_DIR / "pad_expr_precedence_real_run.txt").read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert "Result1 = expr_runtime.pad_add(1, 2 * 3)" in code
    assert "Result2 = True or True and False" in code
    assert "Result3 = bool(True) != bool(True and False)" in code
    assert "Result4 = True or bool(False) != bool(True)" in code
    assert "Result5 = not True and False" in code


def test_generate_python_converts_increase_decrease_variable_with_real_variable_ref() -> None:
    # 実機キャプチャ(tier1_text_variables_batch4.txt)はバッチ自動化の汎用プレースホルダー
    # "sample"がValueに入っており(VarRefでないため安全にTODOへ倒れる、knowledge 66)、
    # IncreaseVariable/DecreaseVariableは[InputArgument(Mutable=true)](その場で変数を
    # 変更する)ため実際の利用では常にValueが変数参照になる——この既に結線済みのコード
    # パスを、現実的なVarRef入力で合成DSLとして検証する。
    # design/dsl_format_findings.md 知見108(実機確認済み): まさにこのDSL(Counter=10→
    # +5→-3)を実機Runした結果Counterは12になり、加算/減算の方向(value+increment/
    # value-decrement)が実装と一致すると確定した。
    dsl = "SET Counter TO 10\nVariables.IncreaseVariable Value: Counter IncrementValue: 5\nVariables.DecreaseVariable Value: Counter DecrementValue: 3"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert "Counter = variables_actions.increase_variable(Counter, 5)" in code
    assert "Counter = variables_actions.decrease_variable(Counter, 3)" in code

    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["Counter"] == 12


def test_generate_python_from_list_of_random_numbers_converts() -> None:
    # design/dsl_format_findings.md 知見122(decompile確認済み): `GenerateRandomNumber`の
    # 兄弟セレクタ`ListOfRandomNumbers`(`GenerateMultipleNumbers: True`固定)。
    # `pad_action_lib.variables_actions.generate_random_number()`は元から`count`/
    # `allow_duplicates`引数を持ち複数生成に対応済みだったため、結線を追加するだけで済んだ
    # (新規実装は不要)。
    dsl = (
        "Variables.GenerateRandomNumber.ListOfRandomNumbers MinimumValue: 1 MaximumValue: 10 "
        "NumbersCount: 5 AllowDuplicates: False RandomNumbers=> Nums"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert "Nums = variables_actions.generate_random_number(1, 10, 5, allow_duplicates=False)" in code

    namespace: dict[str, object] = {}
    exec(code, namespace)
    nums = namespace["Nums"]
    assert isinstance(nums, list)
    assert len(nums) == 5
    assert len(set(nums)) == 5
    assert all(1 <= n <= 10 for n in nums)


def test_generate_python_from_find_item_in_datatable_with_regex_everywhere_converts() -> None:
    # design/dsl_format_findings.md 知見123(decompile確認済み、実機未確認):
    # `FindOrReplaceInDataTable`の兄弟セレクタ`FindItemInDataTableWithRegexEverywhere`
    # (`UseRegex: True`固定)。`Variables.GenerateDataTableFromCSV`でCSVから直接
    # DataTableを作る(知見124の「空のテーブルにList経由で最初の行を追加できない」
    # 問題を回避する、実機確認済みの経路)。
    dsl = (
        "SET CSV TO $'''A\norder-123\nno digits'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> T\n"
        "Variables.FindOrReplaceInDataTable.FindItemInDataTableWithRegexEverywhere "
        "DataTable: T ValueToFind: $'''[0-9]+''' AllMatches: True DataTableMatches=> M"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "M = variables_actions.find_item_in_datatable_everywhere(T, '[0-9]+', "
        "all_matches=True, use_regex=True)" in code
    )
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["M"] == [(0, 0)]


def test_generate_python_from_find_item_in_datatable_by_column_index_converts() -> None:
    # design/dsl_format_findings.md 知見123の追記: 兄弟セレクタ
    # `FindItemInDataTableByColumnIndex`(列名でも指定できる)。
    dsl = (
        "SET CSV TO $'''A,B\nx,x\ny,x'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> T\n"
        "Variables.FindOrReplaceInDataTable.FindItemInDataTableByColumnIndex "
        "DataTable: T ValueToFind: $'''x''' AllMatches: True MatchCase: True "
        "MatchEntireCellContents: False ColumnNameOrIndex: $'''B''' DataTableMatches=> M"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert "column='B'" in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["M"] == [(0, 1), (1, 1)]


def test_generate_python_from_find_item_in_datatable_by_numeric_column_index_converts() -> None:
    # design/dsl_format_findings.md 知見133(実機確認済み): `ColumnNameOrIndex`は数値文字列
    # (0始まり)でも列インデックスとして解決できる——知見123で「IsZeroBased未確認」として
    # 列名のみに限定していた制限を解消した。
    dsl = (
        "SET CSV TO $'''A,B\nx,x\ny,x'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> T\n"
        "Variables.FindOrReplaceInDataTable.FindItemInDataTableByColumnIndex "
        "DataTable: T ValueToFind: $'''x''' AllMatches: True MatchCase: True "
        "MatchEntireCellContents: False ColumnNameOrIndex: $'''1''' DataTableMatches=> M"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["M"] == [(0, 1), (1, 1)]


def test_generate_python_from_sort_datatable_with_column_index_converts() -> None:
    # design/dsl_format_findings.md 知見133: `SortDataTable`の兄弟セレクタ
    # `SortWithColumnIndex`(VM上でActionSelectorBase.ActionNameを直接読み取って確認済み)。
    dsl = (
        "SET CSV TO $'''A,B\nx,2\ny,1'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> T\n"
        "Variables.SortDataTable.SortWithColumnIndex DataTable: T ColumnIndex: 1 "
        "Order: Variables.SortDirection.Ascending"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["T"] == [{"A": "y", "B": "1"}, {"A": "x", "B": "2"}]


def test_generate_python_from_filter_datatable_end_to_end_via_csv_seeded_tables() -> None:
    # design/dsl_format_findings.md 知見124の追記: 知見124で発見したように、
    # `Variables.FilterDataTable`/`JoinDataTable`はこれまで(知見90・91等)
    # decompileとPAD実機でのみ検証されており、`pad_codegen`が生成したPythonを
    # 実際にexec()するテストが一度も無かった(`AddRowToDataTable`経由でテーブルを
    # 組み立てる方法は空テーブルへの最初の行追加ができないため使えない——
    # `GenerateDataTableFromCSV`で種データを用意する安全な回避経路を使う)。
    # 知見90の確認済み例(`Age Equal 30`)をそのままend-to-endで実行し、
    # codegen→pad_action_lib全体のパイプラインが正しく動くことを確認する。
    dsl = (
        "SET CSV TO $'''Name,Age\nCarol,30\nAlice,25'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> T\n"
        "SET ParamsCSV TO $'''COLUMN,OPERATOR,VALUE,RULE\nAge,Equal,30,And'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: ParamsCSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> FP\n"
        "Variables.FilterDataTable DataTable: T FilterParameters: FP MatchCase: True "
        "FilteredDataTable=> Filtered"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["Filtered"] == [{"Name": "Carol", "Age": "30"}]


def test_generate_python_from_join_datatable_end_to_end_via_csv_seeded_tables() -> None:
    # design/dsl_format_findings.md 知見124の追記: 知見91の確認済み例(Innerで`Name`列を
    # 結合)をend-to-endで実行する。重複列名への" (2)"付与(知見91実機確認済み)も含めて
    # pad_codegen→pad_action_lib全体のパイプラインが正しく動くことを確認する。
    dsl = (
        "SET CSV1 TO $'''Name,Age\nCarol,30\nAlice,25'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV1 TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> T1\n"
        "SET CSV2 TO $'''Name,City\nCarol,Tokyo\nBob,Osaka'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV2 TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> T2\n"
        "SET ParamsCSV TO $'''COLUMN 1,OPERATOR,COLUMN 2\nName,Equal,Name'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: ParamsCSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> JP\n"
        "Variables.JoinDataTable FirstDataTable: T1 SecondDataTable: T2 JoinParameters: JP "
        "JoinOperation: Variables.JoinOperation.Inner JoinedDataTable=> Joined"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["Joined"] == [{"Name": "Carol", "Age": "30", "Name (2)": "Carol", "City": "Tokyo"}]


def test_generate_python_from_compression_zip_unzip_without_password_converts() -> None:
    # 実機キャプチャ(tier1_datetime_folder_clipboard_batch2.txt/tier1_web_xml_batch8.txt)
    # はPasswordが常にWindows DPAPI保護値(`P'<base64>'`)で現れ、知見72の通りVarRef
    # フォールバックになるためTODOのまま残る——`pad_codegen/actions/compression.py`
    # 自身のdocstringが明記する「パスワード無しの圧縮/展開フローのために結線だけ用意する」
    # という既に結線済みのコードパスを、Password省略(PDFのPassword省略と同じ既定値扱い、
    # knowledge 78)の現実的な合成DSLとして検証し、実際にzip/unzip往復まで実行して確認する。
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src_file = tmp_path / "hello.txt"
        src_file.write_text("hello world", encoding="utf-8")
        archive_path = tmp_path / "out.zip"
        dest_dir = tmp_path / "extracted"

        zip_dsl = (
            f"Compression.ZipFiles ArchivePath: $'''{archive_path}''' "
            f"FilesOrFoldersToZip: $'''{src_file}''' "
            "CompressionLevel: Compression.CompressionLevel.BestBalanceOfSpeedAndCompression "
            "ArchiveComment: $'''''' ZipFile=> ZipFile"
        )
        tree = build_block_tree(parse_dsl(zip_dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        assert (
            f"ZipFile = compression_actions.zip_files('{archive_path}', "
            f"('{src_file}' if isinstance('{src_file}', list) else ['{src_file}']), "
            "compression_level=6, password='', archive_comment='')" in code
        )
        namespace: dict[str, object] = {}
        exec(code, namespace)
        assert archive_path.is_file()
        # knowledge 129: ZipFile出力は実機確認済みでArchivePathと同一のパスを指す
        # (以前はzip_files()がNoneを返していたため、ここは常にNoneになる潜在バグだった)。
        assert namespace["ZipFile"] == str(archive_path)

        unzip_dsl = (
            f"Compression.UnzipFiles ArchivePath: $'''{archive_path}''' "
            f"DestinationFolder: $'''{dest_dir}''' IncludeMask: $'''*''' "
            "ExcludeMask: $'''''' UnzippedFiles=> UnzippedFiles"
        )
        tree2 = build_block_tree(parse_dsl(unzip_dsl))
        code2 = generate_python(tree2)
        compile(code2, "<generated>", "exec")
        assert "# TODO" not in code2
        namespace2: dict[str, object] = {}
        exec(code2, namespace2)
        assert (dest_dir / "hello.txt").read_text(encoding="utf-8") == "hello world"


def test_generate_python_from_generate_datatable_from_csv_semicolon_separator() -> None:
    # design/dsl_format_findings.md 知見127(decompile+リフレクション実機確認済み):
    # `ColumnsSeparator`はSystemDefault以外にComma/Semicolon/Tabも選択可能で、
    # 実際の区切り文字はVM上で`CSVSeparator(CSVColumnsSeparator)`を直接呼び出して
    # 確認した(SystemDefault/Comma→","、Semicolon→";"、Tab→"\t")。
    dsl = (
        "SET CSV TO $'''Name;Age\nAlice;30\nBob;25'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.Semicolon CSVTable=> T"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert "delimiter=';'" in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["T"] == [{"Name": "Alice", "Age": "30"}, {"Name": "Bob", "Age": "25"}]


def test_generate_python_from_generate_datatable_from_csv_tab_separator() -> None:
    dsl = (
        "SET CSV TO $'''Name\tAge\nAlice\t30'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.Tab CSVTable=> T"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["T"] == [{"Name": "Alice", "Age": "30"}]


def test_generate_python_from_generate_datatable_from_csv_custom_separator() -> None:
    # design/dsl_format_findings.md 知見127: `GenerateDataTableFromCSV`の兄弟セレクタ
    # `ReadCustomSeparator`(decompileされた`ReadFromCSVCustomSeparatorSelector`の
    # `UseName("ReadCustomSeparator")`で確認済み)。
    dsl = (
        "SET CSV TO $'''Name|Age\nAlice|30'''\n"
        "Variables.GenerateDataTableFromCSV.ReadCustomSeparator CSVText: CSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "CustomColumnsSeparator: $'''|''' CSVTable=> T"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert "delimiter='|'" in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["T"] == [{"Name": "Alice", "Age": "30"}]


def test_generate_python_from_convert_datatable_to_csv_semicolon_separator() -> None:
    dsl = (
        "SET CSV TO $'''Name,Age\nAlice,30'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> T\n"
        "Variables.ConvertDataTableToCSV.DataTableToCSVCommonSeparator DataTable: T "
        "IncludeColumnNames: True ColumnsSeparator: Variables.CSVColumnsSeparator.Semicolon CSVText=> Out"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert "delimiter=';'" in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["Out"] == "Name;Age\r\nAlice;30\r\n"


def test_generate_python_from_convert_datatable_to_csv_custom_separator() -> None:
    # design/dsl_format_findings.md 知見127: `ConvertDataTableToCSV`の兄弟セレクタ
    # `DataTableToCSVCustomSeparator`(decompileされた
    # `DataTableToCSVCustomSeparatorSelector`の`UseName(...)`で確認済み)。
    dsl = (
        "SET CSV TO $'''Name,Age\nAlice,30'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> T\n"
        "Variables.ConvertDataTableToCSV.DataTableToCSVCustomSeparator DataTable: T "
        "IncludeColumnNames: True CustomColumnsSeparator: $'''|''' CSVText=> Out"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert "delimiter='|'" in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["Out"] == "Name|Age\r\nAlice|30\r\n"


def test_generate_python_from_file_write_read_csv_semicolon_separator_round_trips() -> None:
    # design/dsl_format_findings.md 知見128: 知見127と同じ`CSVColumnsSeparator`列挙型を
    # `File.ReadFromCSVFile`/`File.WriteToCSVFile`も使っていると確認したため、同じ
    # ゲート漏れ(SystemDefault以外で常にTODO)を解消した。
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "out.csv"
        dsl = (
            "SET CSV TO $'''Name,Age\nAlice,30'''\n"
            "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV TrimFields: True "
            "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
            "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> T\n"
            f"File.WriteToCSVFile.WriteCSV VariableToWrite: T CSVFile: $'''{out_path}''' "
            "CsvFileEncoding: File.CSVEncoding.UTF8 IncludeColumnNames: True "
            "IfFileExists: File.IfFileExists.Overwrite ColumnsSeparator: File.CSVColumnsSeparator.Semicolon\n"
            f"File.ReadFromCSVFile.ReadCSV CSVFile: $'''{out_path}''' Encoding: File.CSVEncoding.UTF8 "
            "TrimFields: True FirstLineContainsColumnNames: True "
            "ColumnsSeparator: File.CSVColumnsSeparator.Semicolon CSVTable=> RoundTripped"
        )
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        assert "delimiter=';'" in code
        namespace: dict[str, object] = {}
        exec(code, namespace)
        assert out_path.read_text(encoding="utf-8-sig") == "Name;Age\nAlice;30\n"
        assert namespace["RoundTripped"] == [{"Name": "Alice", "Age": "30"}]


def test_generate_python_from_file_write_read_csv_custom_separator_round_trips() -> None:
    # design/dsl_format_findings.md 知見128: `ReadCSVWithCustomSeparator`/
    # `WriteCSVWithCustomSeparator`兄弟セレクタ(`ActionName`プロパティをVM上で
    # リフレクション直接呼び出しして確認した正確なaction_id接尾辞)。
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "out.csv"
        dsl = (
            "SET CSV TO $'''Name,Age\nAlice,30'''\n"
            "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV TrimFields: True "
            "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
            "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> T\n"
            f"File.WriteToCSVFile.WriteCSVWithCustomSeparator VariableToWrite: T CSVFile: $'''{out_path}''' "
            "CsvFileEncoding: File.CSVEncoding.UTF8 IncludeColumnNames: True "
            "IfFileExists: File.IfFileExists.Overwrite CustomColumnsSeparator: $'''|'''\n"
            f"File.ReadFromCSVFile.ReadCSVWithCustomSeparator CSVFile: $'''{out_path}''' "
            "Encoding: File.CSVEncoding.UTF8 TrimFields: True FirstLineContainsColumnNames: True "
            "CustomColumnsSeparator: $'''|''' CSVTable=> RoundTripped"
        )
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        assert "delimiter='|'" in code
        namespace: dict[str, object] = {}
        exec(code, namespace)
        assert out_path.read_text(encoding="utf-8-sig") == "Name|Age\nAlice|30\n"
        assert namespace["RoundTripped"] == [{"Name": "Alice", "Age": "30"}]


def test_generate_python_from_folder_copy_nests_under_destination_and_returns_path() -> None:
    # design/dsl_format_findings.md 知見130(VM上の直接呼び出しで実機確認済み): `Destination`は
    # コピー先の正確なパスではなく既存の親フォルダで、結果は`Destination/<Folderの名前>`に
    # ネストされる。`CopiedFolder`出力はこのネストされたパスを指す(知見129のZipFilesと同種の
    # 「代入先が常にNoneになる」潜在バグが`copy_folder()`にもあったため合わせて修正)。
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "a.txt").write_text("hello", encoding="utf-8")
        dest_parent = tmp_path / "dst"
        dest_parent.mkdir()

        dsl = (
            f"Folder.Copy Folder: $'''{src_dir}''' Destination: $'''{dest_parent}''' "
            "IfFolderExists: Folder.IfExists.DoNothing CopiedFolder=> CopiedFolder"
        )
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        namespace: dict[str, object] = {}
        exec(code, namespace)
        expected = dest_parent / "src"
        assert namespace["CopiedFolder"] == str(expected)
        assert (expected / "a.txt").read_text(encoding="utf-8") == "hello"


def test_generate_python_from_folder_move_nests_under_destination_and_returns_path() -> None:
    # design/dsl_format_findings.md 知見131(VM上の直接呼び出しで実機確認済み): `Folder.Copy`
    # (知見130)と全く同じ意味論——`Destination`は既存の親フォルダで、結果は
    # `Destination/<Folderの名前>`にネストされる。`move_folder()`は元から戻り値を返していたが
    # (`None`化のバグはなかった)、`Destination`自体の意味論が実機と逆だった。
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "a.txt").write_text("hello", encoding="utf-8")
        dest_parent = tmp_path / "dst"
        dest_parent.mkdir()

        dsl = (
            f"Folder.Move Folder: $'''{src_dir}''' Destination: $'''{dest_parent}''' "
            "MovedFolder=> MovedFolder"
        )
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        namespace: dict[str, object] = {}
        exec(code, namespace)
        expected = dest_parent / "src"
        assert namespace["MovedFolder"] == str(expected)
        assert not src_dir.exists()
        assert (expected / "a.txt").read_text(encoding="utf-8") == "hello"


def test_generate_python_from_generate_datatable_from_csv_fixed_column_widths() -> None:
    # design/dsl_format_findings.md 知見132(VM上の直接呼び出しで実機確認済み):
    # `GenerateDataTableFromCSV`の兄弟セレクタ`ReadFixedColumnWidths`(知見122で次の
    # 調査対象として記録、知見127・128で一旦見送っていたもの)。
    dsl = (
        "SET CSV TO $'''AAABBBBBCC\nDDDEEEEEFF'''\n"
        "Variables.GenerateDataTableFromCSV.ReadFixedColumnWidths CSVText: CSV TrimFields: True "
        "FirstLineContainsColumnNames: False ReadFieldsAsText: True "
        "FixedColumnWidths: $'''3,5,2''' CSVTable=> T"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert "datatable_from_fixed_width_csv" in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["T"] == [
        {"Column#1": "AAA", "Column#2": "BBBBB", "Column#3": "CC"},
        {"Column#1": "DDD", "Column#2": "EEEEE", "Column#3": "FF"},
    ]


def test_generate_python_from_file_read_csv_fixed_column_widths() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "fixed.txt"
        csv_path.write_text("AAABBBBBCC\r\nDDDEEEEEFF", encoding="utf-8")

        dsl = (
            f"File.ReadFromCSVFile.ReadCSVWithFixedColumnWidths CSVFile: $'''{csv_path}''' "
            "Encoding: File.CSVEncoding.UTF8 TrimFields: True FirstLineContainsColumnNames: False "
            "FixedColumnWidths: $'''3,5,2''' CSVTable=> T"
        )
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        assert "read_from_csv_file_fixed_width" in code
        namespace: dict[str, object] = {}
        exec(code, namespace)
        assert namespace["T"] == [
            {"Column#1": "AAA", "Column#2": "BBBBB", "Column#3": "CC"},
            {"Column#1": "DDD", "Column#2": "EEEEE", "Column#3": "FF"},
        ]


def test_generate_python_from_sort_list_by_property_with_independent_directions() -> None:
    # design/dsl_format_findings.md 知見133・134(VM上で実機の`SortListBase.Execute()`を
    # 直接呼び出して確認済み): `SortList`の兄弟セレクタ`SortListByProperty`、age昇順・
    # name降順の2キーソート(Property3は空文字列で未使用)。
    dsl = (
        "Variables.CreateNewList List=> L\n"
        "Variables.ConvertJsonToCustomObject Json: $'''{\"name\": \"Bob\", \"age\": 30}''' "
        "CustomObject=> O1\n"
        "Variables.AddItemToList List: L Item: O1\n"
        "Variables.ConvertJsonToCustomObject Json: $'''{\"name\": \"Alice\", \"age\": 25}''' "
        "CustomObject=> O2\n"
        "Variables.AddItemToList List: L Item: O2\n"
        "Variables.ConvertJsonToCustomObject Json: $'''{\"name\": \"Carol\", \"age\": 25}''' "
        "CustomObject=> O3\n"
        "Variables.AddItemToList List: L Item: O3\n"
        "Variables.SortList.SortListByProperty List: L Property1: $'''age''' "
        "Property2: $'''name''' Property3: $'''''' "
        "SortDirection1: Variables.SortDirection.Ascending "
        "SortDirection2: Variables.SortDirection.Descending "
        "SortDirection3: Variables.SortDirection.Ascending"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert [item["name"] for item in namespace["L"]] == ["Carol", "Alice", "Bob"]


def test_generate_python_from_truncate_number_get_decimal_part_converts() -> None:
    # design/dsl_format_findings.md 知見135: `TruncateNumber`の兄弟セレクタ`GetDecimalPart`
    # (`truncate_number()`自体は既に対応済みでcodegen側だけ未結線だった)。
    dsl = "Variables.TruncateNumber.GetDecimalPart Number: 3.7 Result=> R"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["R"] == pytest.approx(0.7)


def test_generate_python_from_truncate_number_round_number_converts() -> None:
    # design/dsl_format_findings.md 知見135: 兄弟セレクタ`RoundNumber`(実機の`Operation`
    # 列挙値は`RoundAtNthDecimalDigits`、VM上のリフレクションで確認済み)。
    dsl = "Variables.TruncateNumber.RoundNumber Number: 3.14159 DecimalPlaces: 2 Result=> R"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["R"] == 3.14


def test_generate_python_from_remove_item_from_list_by_value_converts() -> None:
    # design/dsl_format_findings.md 知見135: `RemoveItemFromList`の兄弟セレクタ
    # `RemoveItemFromListByValue`(`ItemMatchAllOccurrences`で全件削除か最初の1件かを切り替える、
    # VM上で`RemoveItemFromList.Execute()`を直接呼び出して確認済み)。
    dsl = (
        "Variables.CreateNewList List=> L\n"
        "Variables.AddItemToList List: L Item: $'''a'''\n"
        "Variables.AddItemToList List: L Item: $'''b'''\n"
        "Variables.AddItemToList List: L Item: $'''a'''\n"
        "Variables.RemoveItemFromList.RemoveItemFromListByValue List: L Item: $'''a''' "
        "ItemMatchAllOccurrences: True"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["L"] == ["b"]


def test_generate_python_from_insert_item_to_datatable_converts() -> None:
    # design/dsl_format_findings.md 知見135: `AddRowToDataTable`の兄弟セレクタ
    # `InsertItemToDataTable`(`RowIndex`は0始まり、`list.insert()`と同じ挿入位置)。
    # 2列のテーブルを使い、知見124の単一要素リストのあいまいさ(1列テーブルで`RowToAdd`が
    # 裸のスカラーになるか未確認)を回避する。
    dsl = (
        "SET CSV TO $'''A,B\nx,x\nz,z'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> T\n"
        "Variables.CreateNewList List=> Row\n"
        "Variables.AddItemToList List: Row Item: $'''y'''\n"
        "Variables.AddItemToList List: Row Item: $'''y'''\n"
        "Variables.AddRowToDataTable.InsertItemToDataTable DataTable: T RowIndex: 1 RowToAdd: Row"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["T"] == [{"A": "x", "B": "x"}, {"A": "y", "B": "y"}, {"A": "z", "B": "z"}]


def test_generate_python_from_insert_column_to_datatable_converts() -> None:
    # design/dsl_format_findings.md 知見135: `AddColumnToDataTable`の兄弟セレクタ
    # `InsertColumnToDataTable`(`ColumnIndex`は0始まり)。
    dsl = (
        "SET CSV TO $'''A,B\nx,y'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> T\n"
        "Variables.AddColumnToDataTable.InsertColumnToDataTable DataTable: T "
        "ColumnName: $'''NEW''' ColumnIndex: 1"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["T"] == [{"A": "x", "NEW": "", "B": "y"}]


def test_generate_python_from_delete_column_with_index_converts() -> None:
    # design/dsl_format_findings.md 知見135: `DeleteColumnFromDataTable`の兄弟セレクタ
    # `DeleteColumnWithIndex`(`ColumnIndex`は0始まり、知見133で確定済み)。
    dsl = (
        "SET CSV TO $'''A,B,C\nx,y,z'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> T\n"
        "Variables.DeleteColumnFromDataTable.DeleteColumnWithIndex DataTable: T ColumnIndex: 1"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["T"] == [{"A": "x", "C": "z"}]


def test_generate_python_from_find_item_in_datatable_with_regex_by_column_index_converts() -> None:
    # design/dsl_format_findings.md 知見135: `FindOrReplaceInDataTable`の兄弟セレクタ
    # `FindItemInDataTableWithRegexByColumnIndex`(`UseRegex: True`固定+列名/列インデックス
    # 両対応の組み合わせ)。
    dsl = (
        "SET CSV TO $'''A,B\norder-123,x\nno-digits,x'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> T\n"
        "Variables.FindOrReplaceInDataTable.FindItemInDataTableWithRegexByColumnIndex "
        "DataTable: T ValueToFind: $'''[0-9]+''' AllMatches: True "
        "ColumnNameOrIndex: $'''0''' DataTableMatches=> M"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["M"] == [(0, 0)]


def test_generate_python_from_if_file_does_not_exist_converts() -> None:
    # design/dsl_format_findings.md 知見136: `File.IfFile.Exists`の兄弟セレクタ
    # `File.IfFile.DoesNotExist`(単純な否定、`ActionSelectorBase`一括列挙の監査で発見)。
    with tempfile.TemporaryDirectory() as tmp:
        missing_path = Path(tmp) / "missing.txt"
        dsl = f"IF (File.IfFile.DoesNotExist File: $'''{missing_path}''') THEN\nSET X TO 1\nEND"
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        namespace: dict[str, object] = {}
        exec(code, namespace)
        assert namespace["X"] == 1


def test_generate_python_from_if_folder_does_not_exist_converts() -> None:
    # design/dsl_format_findings.md 知見137: `Folder.IfFolderExists.Exists`の兄弟セレクタ
    # `DoesNotExist`(`FolderExistsSelector`という名前自体に"IfFolder"という部分文字列を
    # 含まないため、型名の部分一致で探す監査では見逃していた——`ActionSelectorBase`を
    # 基底型として正しく辿る方法で発見)。
    with tempfile.TemporaryDirectory() as tmp:
        missing_path = Path(tmp) / "missing_dir"
        dsl = f"IF (Folder.IfFolderExists.DoesNotExist Path: $'''{missing_path}''') THEN\nSET X TO 1\nEND"
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        namespace: dict[str, object] = {}
        exec(code, namespace)
        assert namespace["X"] == 1


def test_generate_python_from_wait_for_file_deleted_converts() -> None:
    # design/dsl_format_findings.md 知見136: `File.WaitForFile.Created`の兄弟セレクタ
    # `File.WaitForFile.Deleted`(存在チェックを無期限ポーリングするだけの単純な否定)。
    with tempfile.TemporaryDirectory() as tmp:
        missing_path = Path(tmp) / "already_gone.txt"
        dsl = f"WAIT (File.WaitForFile.Deleted File: $'''{missing_path}''')"
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        namespace: dict[str, object] = {}
        exec(code, namespace)  # ファイルが既に存在しないため即座に完了するはず


def test_generate_python_from_read_text_from_file_as_list_converts() -> None:
    # design/dsl_format_findings.md 知見136: `File.ReadTextFromFile`の兄弟セレクタ
    # `ReadTextAsList`(出力変数名は`Content`ではなく`Contents`)。
    with tempfile.TemporaryDirectory() as tmp:
        text_path = Path(tmp) / "lines.txt"
        text_path.write_text("a\nb\nc", encoding="utf-8")

        dsl = (
            f"File.ReadTextFromFile.ReadTextAsList File: $'''{text_path}''' "
            "Encoding: File.TextFileEncoding.UTF8 Contents=> L"
        )
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        namespace: dict[str, object] = {}
        exec(code, namespace)
        assert namespace["L"] == ["a", "b", "c"]


def test_generate_python_from_rename_files_add_text_converts() -> None:
    # design/dsl_format_findings.md 知見136: `File.RenameFiles`の兄弟セレクタ`RenameAddText`
    # (`TextPosition`の実機の列挙値は`BeforeName`/`AfterName`、VM上で確認済み)。
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "report.txt"
        src.write_text("x", encoding="utf-8")
        dsl = (
            f"File.RenameFiles.RenameAddText Files: $'''{src}''' TextToAdd: $'''_v2''' "
            "TextPosition: File.TextPosition.AfterName "
            "IfFileExists: File.IfExists.DoNothing RenamedFiles=> R"
        )
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        namespace: dict[str, object] = {}
        exec(code, namespace)
        renamed = Path(tmp) / "report_v2.txt"
        assert namespace["R"] == [str(renamed)]
        assert renamed.is_file()


def test_generate_python_from_rename_files_remove_text_converts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "file_old.txt"
        src.write_text("x", encoding="utf-8")
        dsl = (
            f"File.RenameFiles.RenameRemoveText Files: $'''{src}''' TextToRemove: $'''_old''' "
            "IfFileExists: File.IfExists.DoNothing RenamedFiles=> R"
        )
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        namespace: dict[str, object] = {}
        exec(code, namespace)
        renamed = Path(tmp) / "file.txt"
        assert namespace["R"] == [str(renamed)]
        assert renamed.is_file()


def test_generate_python_from_rename_files_replace_text_converts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "file_old.txt"
        src.write_text("x", encoding="utf-8")
        dsl = (
            f"File.RenameFiles.RenameReplaceText Files: $'''{src}''' TextToReplace: $'''old''' "
            "ReplaceWith: $'''new''' IfFileExists: File.IfExists.DoNothing RenamedFiles=> R"
        )
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        namespace: dict[str, object] = {}
        exec(code, namespace)
        renamed = Path(tmp) / "file_new.txt"
        assert namespace["R"] == [str(renamed)]
        assert renamed.is_file()


def test_generate_python_from_rename_files_change_extension_converts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "report.txt"
        src.write_text("x", encoding="utf-8")
        dsl = (
            f"File.RenameFiles.RenameChangeExtension Files: $'''{src}''' NewExtension: $'''csv''' "
            "IfFileExists: File.IfExists.DoNothing RenamedFiles=> R"
        )
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        namespace: dict[str, object] = {}
        exec(code, namespace)
        renamed = Path(tmp) / "report.csv"
        assert namespace["R"] == [str(renamed)]
        assert renamed.is_file()


def test_generate_python_from_get_current_datetime_custom_offset_converts() -> None:
    # design/dsl_format_findings.md 知見138: `GetCurrentDateTime`の兄弟セレクタ
    # `CustomOffset`(`Local`以外、`ActionSelectorBase`一括列挙の監査で発見・VM上の
    # 直接呼び出しで仕様確認)。プラットフォーム非依存(`win32timezone`不要)なので
    # ここで検証する。
    from datetime import datetime, timedelta, timezone

    dsl = (
        "DateTime.GetCurrentDateTime.CustomOffset DateTimeFormat: DateTime.DateTimeFormat.DateAndTime "
        "CustomOffset: 5 CurrentDateTime=> D"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    delta = (namespace["D"] - now_utc) - timedelta(hours=5)
    assert abs(delta.total_seconds()) < 5
