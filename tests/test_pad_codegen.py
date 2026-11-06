"""pad_codegen の単体テスト・結合テスト。

結合テストのフィクスチャは design/dsl_format_findings.md 知見14で実機から
キャプチャした、SET/IF+ELSE IF+ELSE(ネスト込み)/LOOP系3種/EXIT・NEXT LOOPを
網羅するg1g2_testフローの生データ。

**手書きDSL文字列を書く際の既知の落とし穴(2026-11-05発見)**: PAD自身のクリップボード
DSLは`IF`/`LOOP`等の本体を必ずインデントする(`pad_dsl.block_tree`はインデント段差で
本体を認識する)。手書きのテスト用DSL文字列で`"IF (...) THEN\nSET X TO 1\nEND"`のように
本体をインデント**しない**と、パーサーは本体を空(IF自身は`pass`のみ)と解釈し、
`SET X TO 1`はIFの外側(無条件)の文として漏れる——`exec()`後に`namespace["X"] == 1`を
アサートするだけのテストは、IFのゲートが実際に機能しているかに関わらず常に通ってしまう
(真の分岐しかテストしていない場合は特に気づきにくい)。条件分岐の実際の動作を検証する
テストは、生成された`if ...:`行自体を取り出して`eval()`する(真偽どちらの分岐でも
本体への依存を持たない)か、本体を含めてテストするなら必ず4スペースでインデントする
こと(真偽両方の分岐を確認する)。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import tempfile
from datetime import datetime
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

    # design/common_rpa_framework_roadmap.md 層7(b)(c)の拡張: pyautoguiも`win32gui`/
    # `win32con`と同じ`sys.modules`注入方式でフェイクし、実際にexec()して検証する
    # (pyautoguiは本プロジェクトの依存関係にすら入っておらず、ディスプレイ依存のため
    # そもそもimportできない——`tests/fake_pyautogui.py`参照)。
    from fake_pyautogui import fake_pyautogui_module

    with fake_pyautogui_module() as registry:
        exec(code, {})
    assert registry.calls == [("typewrite", "Hello World", 0.01)]


def test_generate_python_full_flow_converts_display_message() -> None:
    # design/dsl_format_findings.md 知見184/185で新規結線。このDSL自体は本プロジェクト
    # 最初の実機キャプチャ(知見1)そのもの(Message/Titleは実機で空/既定値だったため
    # 直列化されていない)——以前はTODOのままだったが、現在は実コードを生成する。
    tree = build_block_tree(parse_dsl(FULL_FLOW_DSL))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Display.ShowMessageDialog.ShowMessage" not in code
    assert (
        "ButtonPressed = display_actions.show_message_dialog('', '', "
        "icon='None', buttons='OK', default_button='Button1', is_topmost=False)" in code
    )


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

    from fake_pyautogui import fake_pyautogui_module

    with fake_pyautogui_module() as registry:
        exec(code, {})
    assert registry.calls == [("moveTo", 500, 300)]


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

    from fake_pyautogui import fake_pyautogui_module

    with fake_pyautogui_module() as registry:
        exec(code, {})
    assert registry.calls == [("click",)]


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

    from fake_pyautogui import fake_pyautogui_module

    with fake_pyautogui_module() as registry:
        exec(code, {})
    assert registry.calls == [("click",)]


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
    ("mode", "window_exists", "window_active", "expected_result"),
    [
        ("IsOpenByInstanceOrHandle", True, True, True),
        ("IsOpenByInstanceOrHandle", False, False, False),
        ("IsNotOpenByInstanceOrHandle", True, True, False),
        ("IsNotOpenByInstanceOrHandle", False, False, True),
        ("IsFocusedByInstanceOrHandle", True, True, True),
        ("IsFocusedByInstanceOrHandle", True, False, False),
        ("IsFocusedByInstanceOrHandle", False, False, False),
        ("IsNotFocusedByInstanceOrHandle", True, True, False),
        ("IsNotFocusedByInstanceOrHandle", True, False, True),
        ("IsNotFocusedByInstanceOrHandle", False, False, True),
    ],
)
def test_generate_python_if_window_by_instance_or_handle_modes_evaluate_correctly(
    mode: str, window_exists: bool, window_active: bool, expected_result: bool
) -> None:
    # design/common_rpa_framework_roadmap.md 層7(b)の拡張:
    # `test_generate_python_if_window_modes_evaluate_correctly_against_fake_pywinauto`は
    # `Window: appmask[...]`(Control/リポジトリ経由)の経路しか検証していなかった——
    # `WindowInstance`変数ベースの兄弟セレクタ4モードも同じ10パターンで真偽値まで検証する。
    from fake_pywinauto import FakeControl, FakeRegistry

    dsl = f"IF (UIAutomation.IfWindow.{mode} WindowInstance: AutomationWindow2) THEN\nSET X TO 1\nEND"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    condition_source = code.splitlines()[0].removeprefix("if ").removesuffix(":")

    registry = FakeRegistry()
    criteria = {"title": "Untitled - Notepad"}
    if window_exists:
        registry.register_window(**criteria)
        registry.set_active([criteria], window_active)
    fake_window = FakeControl(registry, criteria)
    namespace: dict[str, object] = {"AutomationWindow2": fake_window}
    exec(code, namespace)
    assert eval(condition_source, namespace) is expected_result


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


@pytest.mark.parametrize(
    ("mode", "window_exists", "window_active", "expected_result"),
    [
        ("IsOpenByTitleClass", True, True, True),
        ("IsOpenByTitleClass", False, False, False),
        ("IsNotOpenByTitleClass", True, True, False),
        ("IsNotOpenByTitleClass", False, False, True),
        ("IsFocusedByTitleClass", True, True, True),
        ("IsFocusedByTitleClass", True, False, False),
        ("IsFocusedByTitleClass", False, False, False),
        ("IsNotFocusedByTitleClass", True, True, False),
        ("IsNotFocusedByTitleClass", True, False, True),
        ("IsNotFocusedByTitleClass", False, False, True),
    ],
)
def test_generate_python_if_window_by_title_class_modes_evaluate_correctly(
    mode: str, window_exists: bool, window_active: bool, expected_result: bool
) -> None:
    # design/common_rpa_framework_roadmap.md 層7(b)の拡張: `Title`+`Class`ベースの兄弟
    # セレクタ4モードも、Control/WindowInstanceベースと同じ10パターンで真偽値まで検証する。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    dsl = f"IF (UIAutomation.IfWindow.{mode} Title: $'''Notepad''' Class: $'''''') THEN\nSET X TO 1\nEND"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    if_line = next(line for line in code.splitlines() if line.startswith("if "))
    condition_source = if_line.removeprefix("if ").removesuffix(":")

    registry = FakeRegistry()
    if window_exists:
        registry.register_window(title="Notepad")
        registry.set_active([{"title": "Notepad"}], window_active)
    with fake_pywinauto_desktop(registry):
        namespace: dict[str, object] = {}
        exec(code, namespace)
        assert eval(condition_source, namespace) is expected_result


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


def test_generate_python_from_real_if_window_contains_element_converts_with_repository() -> None:
    # design/dsl_format_findings.md 知見199: `IfWindowContainsAction`は知見196で解決した
    # `WaitForWindowContentAction`と同じ`WindowContainsActionBase`を共有すると判明——
    # 同じ5兄弟セレクタ構造のうち`WindowContainsElement`を同じロジックで結線した。
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_if_window_contains_element.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert (
        "if Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".child_window(class_name='Edit').exists():" in code
    )
    assert "NotImplementedError" not in code


@pytest.mark.parametrize(
    ("new_action_id", "expected_condition"),
    [
        (
            "WindowContainsElement",
            "Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
            ".child_window(class_name='Edit').exists()",
        ),
        (
            "WindowDoesNotContainElement",
            "not Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
            ".child_window(class_name='Edit').exists()",
        ),
    ],
)
def test_generate_python_converts_if_window_contains_element_modes(
    new_action_id: str, expected_condition: str
) -> None:
    # design/dsl_format_findings.md 知見199: 実機キャプチャ(`WindowContainsElement`)の
    # action_id行を文字列置換して兄弟セレクタを再利用する(知見196と同じ手法)。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_if_window_contains_element.txt"
    ).read_text(encoding="utf-8")
    text = text.replace("WindowContainsElement", new_action_id, 1)
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert f"if {expected_condition}:" in code
    assert "NotImplementedError" not in code

    registry = FakeRegistry()
    registry.register_descendant({"title": "Untitled - Notepad"}, {"class_name": "Edit"})
    with fake_pywinauto_desktop(registry):
        exec(code, {})


@pytest.mark.parametrize("state", ["Enabled", "Disabled"])
def test_generate_python_converts_if_window_contains_element_in_state(state: str) -> None:
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_if_window_contains_element.txt"
    ).read_text(encoding="utf-8")
    text = text.replace(
        "WindowContainsElement Element:",
        f"WindowContainsElementInState State: UIAutomation.State.{state} Element:",
        1,
    )
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    desired = state == "Enabled"
    sel = "Desktop(backend=\"uia\").window(title='Untitled - Notepad').child_window(class_name='Edit')"
    assert f"if ({sel}.exists() and {sel}.wrapper_object().is_enabled() == {desired}):" in code

    registry = FakeRegistry()
    registry.register_descendant({"title": "Untitled - Notepad"}, {"class_name": "Edit"})
    registry.set_enabled([{"title": "Untitled - Notepad"}, {"class_name": "Edit"}], desired)
    with fake_pywinauto_desktop(registry):
        exec(code, {})


def test_generate_python_keeps_if_window_contains_text_as_todo() -> None:
    # design/dsl_format_findings.md 知見199: テキストマッチの正確な意味論が実機未確認
    # のため`WindowContainsText`/`WindowDoesNotContainText`は依然見送り。
    dsl = (
        "IF (UIAutomation.IfWindowContains.WindowContainsText Window: AutomationWindow2 "
        "Text: $'''hello''') THEN\nSET X TO 1\nEND"
    )
    tree = build_block_tree(parse_dsl(dsl))
    with pytest.raises(NotImplementedError, match="WindowContainsText"):
        generate_python(tree)


def test_generate_python_from_real_if_service_capture_converts() -> None:
    # design/dsl_format_findings.md 知見188: 知見187執筆時に「既存の汎用パーサーで対応できる
    # 見込み」と書いたが実際には未結線(NotImplementedErrorへ落ちていた)と判明し、
    # IfService列挙値がWin32標準のSERVICE_STATE定数そのものと確定して正式に結線した
    # ——以前はNotImplementedErrorだったが、現在は実コードを生成する。
    dsl = "IF (Services.IfService.IsRunning Service: $'''Spooler''') THEN\nEND"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "if services_actions.get_service_status('Spooler') == 4:" in code


def test_generate_python_renders_wait_for_service_as_polling_loop_real_capture() -> None:
    # design/dsl_format_findings.md 知見188: 知見50当時はTODOのままだったが、現在は
    # IfServiceと同じWin32標準SERVICE_STATE定数比較の無期限ポーリングへ結線されている。
    dsl = "WAIT (Services.WaitForService.Started Service: $'''Spooler''')"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "while services_actions.get_service_status('Spooler') != 4:" in code


def test_generate_python_from_real_wait_for_window_become_focused_whole_subflow_capture_compiles() -> None:
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_become_focused.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "UIAutomation.WaitForWindow.ToBecomeFocused" in code


def test_generate_python_from_wait_for_window_become_focused_actually_waits_against_fake_pywinauto() -> None:
    # design/common_rpa_framework_roadmap.md 層7(b)の拡張: 上のテストはリポジトリ無し
    # (TODOフォールバック)経路しか見ていなかった——`ToBecomeFocused`/`ToLoseFocus`/
    # `ToClose`の実コード生成経路(リポジトリあり)は、`codegen_coverage.py`の自動
    # フィクスチャ走査では[OK]と判定されるにもかかわらず、`test_pad_codegen.py`側には
    # 一度もexec検証が無かった実在の穴だった。ウィンドウが既にフォーカス済みの状態で
    # execし、ループが即座に(ハングせず)抜けることまで検証する。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_become_focused.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    assert (
        "while not (Desktop(backend=\"uia\").window(title='Untitled - Notepad').exists() "
        "and Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".wrapper_object().is_active()):" in code
    )

    registry = FakeRegistry()
    registry.register_window(title="Untitled - Notepad")
    registry.set_active([{"title": "Untitled - Notepad"}], True)
    with fake_pywinauto_desktop(registry):
        exec(code, {})  # 既にフォーカス済みなので即座に終了するはず


def test_generate_python_from_real_wait_for_window_lose_focus_whole_subflow_capture_compiles() -> None:
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_lose_focus.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "UIAutomation.WaitForWindow.ToLoseFocus" in code


def test_generate_python_from_wait_for_window_lose_focus_actually_waits_against_fake_pywinauto() -> None:
    # 上と対になるテスト: ウィンドウが既にフォーカスを失っている(存在しない)状態でexecし、
    # ループが即座に抜けることを検証する。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_lose_focus.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    assert (
        "while (Desktop(backend=\"uia\").window(title='Untitled - Notepad').exists() "
        "and Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".wrapper_object().is_active()):" in code
    )

    registry = FakeRegistry()  # ウィンドウ未登録=存在しない(=フォーカスも無い)状態
    with fake_pywinauto_desktop(registry):
        exec(code, {})  # 既にフォーカスを失っているので即座に終了するはず


def test_generate_python_from_real_wait_for_window_to_close_whole_subflow_capture_compiles() -> None:
    # `UIAutomation.WaitForWindow.ToClose`は`codegen_coverage.py`の自動フィクスチャ走査
    # では計測されていたが、test_pad_codegen.py側には一度もテストが無かった実在の穴
    # (`tests/test_pad_dsl_parser.py`側にはパーサーレベルのテストのみ存在していた)。
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_to_close.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "UIAutomation.WaitForWindow.ToClose" in code  # リポジトリ無しなのでTODOフォールバック


def test_generate_python_from_wait_for_window_to_close_actually_waits_against_fake_pywinauto() -> None:
    # design/common_rpa_framework_roadmap.md 層7(b)の拡張: リポジトリありの実コード生成
    # 経路(`while ...exists(): time.sleep(...)`)を実際にexec()し、ウィンドウが既に
    # 閉じている状態でループが即座に抜けることまで検証する。
    import os

    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_to_close.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    assert "while Desktop(backend=\"uia\").window(title='Untitled - Notepad').exists():" in code

    registry = FakeRegistry()  # ウィンドウ未登録=既に閉じている状態
    # このフィクスチャも`Scripting.RunPythonScript`でハードコードされたWindowsパスへの
    # 書き込みを含むため、一時ディレクトリへ退避してからexec()する。
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as tmp, fake_pywinauto_desktop(registry):
        try:
            os.chdir(tmp)
            exec(code, {})  # 既に閉じているので即座に終了するはず
        finally:
            os.chdir(original_cwd)


# 実機で「Press/release key」をControl=True(他Falseのまま)でAction to perform=Press、
# 続けてAction to perform=Releaseに切り替えて再キャプチャした生データ(知見23)。
PRESS_CONTROL_DSL = "MouseAndKeyboard.PressReleaseKey.PressKey Control: True Alt: False Shift: False Win: False"
RELEASE_CONTROL_DSL = "MouseAndKeyboard.PressReleaseKey.ReleaseKey Control: True Alt: False Shift: False Win: False"


def test_generate_python_maps_press_key_to_pyautogui_keydown() -> None:
    tree = build_block_tree(parse_dsl(PRESS_CONTROL_DSL))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "pyautogui.keyDown('ctrl')" in code

    from fake_pyautogui import fake_pyautogui_module

    with fake_pyautogui_module() as registry:
        exec(code, {})
    assert registry.calls == [("keyDown", "ctrl")]


def test_generate_python_maps_release_key_to_pyautogui_keyup() -> None:
    tree = build_block_tree(parse_dsl(RELEASE_CONTROL_DSL))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "pyautogui.keyUp('ctrl')" in code

    from fake_pyautogui import fake_pyautogui_module

    with fake_pyautogui_module() as registry:
        exec(code, {})
    assert registry.calls == [("keyUp", "ctrl")]


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

    # design/common_rpa_framework_roadmap.md 層7(b)の拡張: `.maximize()`/`.minimize()`/
    # `.restore()`をfake_pywinautoに追加し、実際に`exec()`して呼ばれることまで検証する。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    registry = FakeRegistry()
    with fake_pywinauto_desktop(registry):
        exec(code, {})
    assert registry.calls == [("maximize", [{"title": "Power Automate | g1g2_test"}], {})]


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


def test_generate_python_from_resize_window_actually_resizes_against_fake_win32() -> None:
    # design/common_rpa_framework_roadmap.md 層7(c): 上のテストは文字列検査のみ——
    # `test_generate_python_from_move_window_actually_moves_against_fake_win32`と対になる
    # 形で、実際に`exec()`し`win32gui.MoveWindow()`が既存のX/Yを保持しつつ幅/高さだけ
    # 更新する正しい引数で呼ばれることを検証する。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop
    from fake_win32 import FakeWin32Registry, fake_win32_modules

    tree = build_block_tree(parse_dsl(RESIZE_WINDOW_DSL))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")

    ui_registry = FakeRegistry()
    ui_registry.register_window(title="Power Automate | g1g2_test")
    win32_registry = FakeWin32Registry()
    win32_registry.set_rect(0, 10, 20, 810, 620)  # 既存のX=10・Y=20を保持する想定

    with fake_pywinauto_desktop(ui_registry), fake_win32_modules(win32_registry):
        exec(code, {})

    assert win32_registry.calls == [("MoveWindow", 0, 10, 20, 1024, 768, True)]


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


def test_generate_python_from_take_screenshot_of_ui_element_and_save_to_file_converts() -> None:
    # design/dsl_format_findings.md 知見161: `TakeScreenshotOfUIElement`の兄弟セレクタ
    # (`SaveMode=File`固定)。`Control`は`UIAutomation.Click.Click`の`Element`と全く同じ
    # `UiElementRef`機構(`appmask[...]`)で、同じ`ControlRepository`フィクスチャの
    # セレクタがそのまま再利用できる——`_build_pywinauto_selector_expr()`は知見56で
    # 確証済みの式を組み立てるだけで、クリックと同じ信頼度。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    fixture_text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_notepad_control_selector.txt"
    ).read_text(encoding="utf-8")
    repo_marker = "# [ControlRepository]"
    control_repository_block = fixture_text[fixture_text.index(repo_marker) :]
    dsl = (
        "UIAutomation.TakeScreenshotOfUIElement.TakeScreenshotOfUIElementAndSaveToFile "
        "Control: appmask['Window \\'Untitled - Notepad\\'']['Document \\'Text Editor\\''] "
        "ImageFilePath: $'''C:\\\\out.png''' ImageFormat: UIAutomation.ImageFormat.Png "
        "ImageFile=> SavedPath\n\n" + control_repository_block
    )
    tree = build_block_tree(parse_dsl(dsl))
    repository = parse_control_repository(dsl)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".child_window(class_name='Edit').capture_as_image().save('C:\\\\out.png', format='PNG')" in code
    )

    registry = FakeRegistry()
    registry.register_descendant({"title": "Untitled - Notepad"}, {"class_name": "Edit"})
    with fake_pywinauto_desktop(registry):
        namespace: dict[str, object] = {}
        exec(code, namespace)
    assert namespace["SavedPath"] == "C:\\out.png"
    assert registry.calls == [
        ("capture_as_image", [{"title": "Untitled - Notepad"}, {"class_name": "Edit"}], {}),
        (
            "capture_as_image.save",
            [{"title": "Untitled - Notepad"}, {"class_name": "Edit"}],
            {"fp": "C:\\out.png", "format": "PNG"},
        ),
    ]


def test_generate_python_from_focus_text_field_converts() -> None:
    # design/dsl_format_findings.md 知見164(`[Action]`属性の網羅列挙監査で新規発見):
    # `FocusTextFieldInWindow`は兄弟セレクタを持たないフラットなアクション
    # (`UIAutomation.FocusTextField`、知見162の`Name`=`Id`)。`TextField`パラメータは
    # `Click.Click`の`Element`と同じ`UiElementRef`機構で、同じ`ControlRepository`
    # フィクスチャのセレクタがそのまま再利用できる。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    fixture_text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_notepad_control_selector.txt"
    ).read_text(encoding="utf-8")
    repo_marker = "# [ControlRepository]"
    control_repository_block = fixture_text[fixture_text.index(repo_marker) :]
    dsl = (
        "UIAutomation.FocusTextField "
        "TextField: appmask['Window \\'Untitled - Notepad\\'']['Document \\'Text Editor\\'']\n\n"
        + control_repository_block
    )
    tree = build_block_tree(parse_dsl(dsl))
    repository = parse_control_repository(dsl)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".child_window(class_name='Edit').set_focus()" in code
    )

    registry = FakeRegistry()
    registry.register_descendant({"title": "Untitled - Notepad"}, {"class_name": "Edit"})
    with fake_pywinauto_desktop(registry):
        exec(code, {})
    assert registry.calls == [
        ("set_focus", [{"title": "Untitled - Notepad"}, {"class_name": "Edit"}], {}),
    ]


def test_generate_python_from_press_button_invokes_by_default() -> None:
    # design/dsl_format_findings.md 知見167(decompile確認済み): `PressWindowButton`
    # (`[Action(Name = "PressButton")]`、知見162の`Name`=`Id`)は`Button`パラメータが
    # `Click.Click`の`Element`と同じ`UiElementRef`機構。`Simulate=False`(既定)は
    # UIAの`InvokePattern`(pywinautoの`.invoke()`)に対応する。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    fixture_text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_notepad_control_selector.txt"
    ).read_text(encoding="utf-8")
    repo_marker = "# [ControlRepository]"
    control_repository_block = fixture_text[fixture_text.index(repo_marker) :]
    dsl = (
        "UIAutomation.PressButton "
        "Button: appmask['Window \\'Untitled - Notepad\\'']['Document \\'Text Editor\\''] "
        "Simulate: False\n\n" + control_repository_block
    )
    tree = build_block_tree(parse_dsl(dsl))
    repository = parse_control_repository(dsl)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".child_window(class_name='Edit').invoke()" in code
    )

    registry = FakeRegistry()
    registry.register_descendant({"title": "Untitled - Notepad"}, {"class_name": "Edit"})
    with fake_pywinauto_desktop(registry):
        exec(code, {})
    assert registry.calls == [
        ("invoke", [{"title": "Untitled - Notepad"}, {"class_name": "Edit"}], {}),
    ]


def test_generate_python_from_press_button_simulate_true_clicks() -> None:
    # 知見167: `Simulate=True`はシミュレートクリック(`SimulateClickElementInWindow`)
    # に対応し、既に`Click.Click`で実機確認済みの`.click_input()`を使う。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    fixture_text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_notepad_control_selector.txt"
    ).read_text(encoding="utf-8")
    repo_marker = "# [ControlRepository]"
    control_repository_block = fixture_text[fixture_text.index(repo_marker) :]
    dsl = (
        "UIAutomation.PressButton "
        "Button: appmask['Window \\'Untitled - Notepad\\'']['Document \\'Text Editor\\''] "
        "Simulate: True\n\n" + control_repository_block
    )
    tree = build_block_tree(parse_dsl(dsl))
    repository = parse_control_repository(dsl)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".child_window(class_name='Edit').click_input()" in code
    )

    registry = FakeRegistry()
    registry.register_descendant({"title": "Untitled - Notepad"}, {"class_name": "Edit"})
    with fake_pywinauto_desktop(registry):
        exec(code, {})
    assert registry.calls == [
        ("click_input", [{"title": "Untitled - Notepad"}, {"class_name": "Edit"}], {}),
    ]


def test_generate_python_from_hover_on_element_moves_mouse_without_clicking() -> None:
    # design/dsl_format_findings.md 知見168(decompile確認済み): `HoverOnElementInWindow`
    # (`[Action(Name = "HoverOnElement")]`、知見162の`Name`=`Id`)は`Element`パラメータが
    # `Click.Click`の`Element`と同じ`UiElementRef`機構のみで、クリックせず要素の中心へ
    # マウスを移動するだけ——pywinautoの`click_input(button='move')`に1:1対応する。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    fixture_text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_notepad_control_selector.txt"
    ).read_text(encoding="utf-8")
    repo_marker = "# [ControlRepository]"
    control_repository_block = fixture_text[fixture_text.index(repo_marker) :]
    dsl = (
        "UIAutomation.HoverOnElement "
        "Element: appmask['Window \\'Untitled - Notepad\\'']['Document \\'Text Editor\\'']\n\n"
        + control_repository_block
    )
    tree = build_block_tree(parse_dsl(dsl))
    repository = parse_control_repository(dsl)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".child_window(class_name='Edit').click_input(button='move')" in code
    )

    registry = FakeRegistry()
    registry.register_descendant({"title": "Untitled - Notepad"}, {"class_name": "Edit"})
    with fake_pywinauto_desktop(registry):
        exec(code, {})
    assert registry.calls == [
        (
            "click_input",
            [{"title": "Untitled - Notepad"}, {"class_name": "Edit"}],
            {"button": "move"},
        ),
    ]


def test_generate_python_from_select_tab_in_window_selects() -> None:
    # design/dsl_format_findings.md 知見169(decompile確認済み): `SelectTabInWindow`は
    # `Tab`パラメータ(`UiElementRef`)のみでネイティブ側の`SelectTabInWindow(e)`を呼ぶだけ
    # ——pywinautoの`UIAWrapper.select()`(SelectionItemPattern)に1:1対応する。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    fixture_text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_notepad_control_selector.txt"
    ).read_text(encoding="utf-8")
    repo_marker = "# [ControlRepository]"
    control_repository_block = fixture_text[fixture_text.index(repo_marker) :]
    dsl = (
        "UIAutomation.SelectTab "
        "Tab: appmask['Window \\'Untitled - Notepad\\'']['Document \\'Text Editor\\'']\n\n"
        + control_repository_block
    )
    tree = build_block_tree(parse_dsl(dsl))
    repository = parse_control_repository(dsl)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".child_window(class_name='Edit').select()" in code
    )

    registry = FakeRegistry()
    registry.register_descendant({"title": "Untitled - Notepad"}, {"class_name": "Edit"})
    with fake_pywinauto_desktop(registry):
        exec(code, {})
    assert registry.calls == [
        ("select", [{"title": "Untitled - Notepad"}, {"class_name": "Edit"}], {}),
    ]


def test_generate_python_from_select_radio_button_in_window_selects() -> None:
    # 知見169: `SelectRadioButtonInWindow`も`SelectTabInWindow`と全く同じ構造
    # (`RadioButton`パラメータのみ、ネイティブ側は`SelectRadioButtonInWindow(e)`のみ)。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    fixture_text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_notepad_control_selector.txt"
    ).read_text(encoding="utf-8")
    repo_marker = "# [ControlRepository]"
    control_repository_block = fixture_text[fixture_text.index(repo_marker) :]
    dsl = (
        "UIAutomation.SelectRadioButton "
        "RadioButton: appmask['Window \\'Untitled - Notepad\\'']['Document \\'Text Editor\\'']\n\n"
        + control_repository_block
    )
    tree = build_block_tree(parse_dsl(dsl))
    repository = parse_control_repository(dsl)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".child_window(class_name='Edit').select()" in code
    )

    registry = FakeRegistry()
    registry.register_descendant({"title": "Untitled - Notepad"}, {"class_name": "Edit"})
    with fake_pywinauto_desktop(registry):
        exec(code, {})
    assert registry.calls == [
        ("select", [{"title": "Untitled - Notepad"}, {"class_name": "Edit"}], {}),
    ]


def test_generate_python_from_set_checkbox_state_checked_toggles_when_currently_unchecked() -> None:
    # design/dsl_format_findings.md 知見169(decompile確認済み): `SetCheckboxStateInWindow`
    # はネイティブ側で目的の真偽状態への設定のみを行う。UIAのCheckBoxはTogglePatternしか
    # 持たず(SelectionItemPatternは無い)、`Toggle()`は一方向に状態を切り替えるだけなので、
    # `get_toggle_state()`で現在の状態を読み、目的の状態と異なる場合のみ`toggle()`する
    # 冪等パターンで実装した。既定(フェイクの`get_toggle_state()`初期値0=unchecked)から
    # `CheckboxState: Checked`を要求するケース——現在状態と異なるので`toggle()`が呼ばれる。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    fixture_text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_notepad_control_selector.txt"
    ).read_text(encoding="utf-8")
    repo_marker = "# [ControlRepository]"
    control_repository_block = fixture_text[fixture_text.index(repo_marker) :]
    dsl = (
        "UIAutomation.SetCheckboxState "
        "Checkbox: appmask['Window \\'Untitled - Notepad\\'']['Document \\'Text Editor\\''] "
        "CheckboxState: UIAutomation.CheckboxState.Checked\n\n" + control_repository_block
    )
    tree = build_block_tree(parse_dsl(dsl))
    repository = parse_control_repository(dsl)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "if Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".child_window(class_name='Edit').get_toggle_state() != 1:" in code
    )
    assert (
        "    Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".child_window(class_name='Edit').toggle()" in code
    )

    registry = FakeRegistry()
    registry.register_descendant({"title": "Untitled - Notepad"}, {"class_name": "Edit"})
    with fake_pywinauto_desktop(registry):
        exec(code, {})
    assert registry.calls == [
        ("toggle", [{"title": "Untitled - Notepad"}, {"class_name": "Edit"}], {}),
    ]


def test_generate_python_from_set_checkbox_state_skips_toggle_when_already_in_target_state() -> None:
    # 知見169: すでに目的の状態であればtoggle()を呼ばない(冪等性の確認)。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    fixture_text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_notepad_control_selector.txt"
    ).read_text(encoding="utf-8")
    repo_marker = "# [ControlRepository]"
    control_repository_block = fixture_text[fixture_text.index(repo_marker) :]
    dsl = (
        "UIAutomation.SetCheckboxState "
        "Checkbox: appmask['Window \\'Untitled - Notepad\\'']['Document \\'Text Editor\\''] "
        "CheckboxState: UIAutomation.CheckboxState.Unchecked\n\n" + control_repository_block
    )
    tree = build_block_tree(parse_dsl(dsl))
    repository = parse_control_repository(dsl)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code

    registry = FakeRegistry()
    registry.register_descendant({"title": "Untitled - Notepad"}, {"class_name": "Edit"})
    with fake_pywinauto_desktop(registry):
        exec(code, {})
    assert registry.calls == []


def test_generate_python_from_drag_and_drop_element_in_verified_combination() -> None:
    # design/dsl_format_findings.md 知見170(decompile確認済み): `DragAndDropElementInWindow`
    # は`ClickType=LeftClick`・`RectangleEdgePointForMouseDown/Up=MiddleCenter`・
    # オフセット0/0の組み合わせ(`Click.Click`で実機確認済みの知見56と同じ組み合わせ)に
    # 限り、pywinautoの`drag_mouse_input(dst=...)`に1:1対応する。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    fixture_text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_notepad_control_selector.txt"
    ).read_text(encoding="utf-8")
    repo_marker = "# [ControlRepository]"
    control_repository_block = fixture_text[fixture_text.index(repo_marker) :]
    element = "appmask['Window \\'Untitled - Notepad\\'']['Document \\'Text Editor\\'']"
    dsl = (
        "UIAutomation.DragAndDropElement "
        f"ControlToDrag: {element} ControlToDropOver: {element} "
        "ClickType: UIAutomation.DragAndDropClickType.LeftClick "
        "MouseDownOffsetX: 0 MouseDownOffsetY: 0 MouseUpOffsetX: 0 MouseUpOffsetY: 0 "
        "RectangleEdgePointForMouseDown: UIAutomation.RectangleEdgePoint.MiddleCenter "
        "RectangleEdgePointForMouseUp: UIAutomation.RectangleEdgePoint.MiddleCenter\n\n"
        + control_repository_block
    )
    tree = build_block_tree(parse_dsl(dsl))
    repository = parse_control_repository(dsl)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    window_expr = "Desktop(backend=\"uia\").window(title='Untitled - Notepad').child_window(class_name='Edit')"
    assert f"{window_expr}.drag_mouse_input(dst={window_expr})" in code

    registry = FakeRegistry()
    registry.register_descendant({"title": "Untitled - Notepad"}, {"class_name": "Edit"})
    with fake_pywinauto_desktop(registry):
        exec(code, {})
    assert registry.calls == [
        (
            "drag_mouse_input",
            [{"title": "Untitled - Notepad"}, {"class_name": "Edit"}],
            {"dst": [{"title": "Untitled - Notepad"}, {"class_name": "Edit"}]},
        ),
    ]


def test_generate_python_keeps_drag_and_drop_as_todo_when_click_type_unverified() -> None:
    # 知見170: `ClickType=RightClick`は実機未検証のため安全にTODOへ倒す。
    fixture_text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_notepad_control_selector.txt"
    ).read_text(encoding="utf-8")
    repo_marker = "# [ControlRepository]"
    control_repository_block = fixture_text[fixture_text.index(repo_marker) :]
    element = "appmask['Window \\'Untitled - Notepad\\'']['Document \\'Text Editor\\'']"
    dsl = (
        "UIAutomation.DragAndDropElement "
        f"ControlToDrag: {element} ControlToDropOver: {element} "
        "ClickType: UIAutomation.DragAndDropClickType.RightClick "
        "MouseDownOffsetX: 0 MouseDownOffsetY: 0 MouseUpOffsetX: 0 MouseUpOffsetY: 0 "
        "RectangleEdgePointForMouseDown: UIAutomation.RectangleEdgePoint.MiddleCenter "
        "RectangleEdgePointForMouseUp: UIAutomation.RectangleEdgePoint.MiddleCenter\n\n"
        + control_repository_block
    )
    tree = build_block_tree(parse_dsl(dsl))
    repository = parse_control_repository(dsl)
    code = generate_python(tree, repository=repository)
    assert "# TODO: map PAD action: UIAutomation.DragAndDropElement" in code


def test_generate_python_from_get_ui_control_echoes_resolved_selector() -> None:
    # design/dsl_format_findings.md 知見175(decompile確認済み): `GetUIControl`は
    # `ActionBase`直継承(ランタイムプロキシ不使用)で`Execute()`が`UIControl = Control;`
    # のみ——`Control`(`UiElementRef`)を無変換でechoするだけなので、解決済みの
    # セレクタ式をそのまま出力変数へ代入すれば、以降の他アクションで通常の変数参照
    # として再利用できる(`UIAutomation.GetWindow.Get`、知見57と同じパターン)。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    fixture_text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_notepad_control_selector.txt"
    ).read_text(encoding="utf-8")
    repo_marker = "# [ControlRepository]"
    control_repository_block = fixture_text[fixture_text.index(repo_marker) :]
    dsl = (
        "UIAutomation.GetUIControl "
        "Control: appmask['Window \\'Untitled - Notepad\\'']['Document \\'Text Editor\\''] "
        "UIControl=> CapturedControl\n\n" + control_repository_block
    )
    tree = build_block_tree(parse_dsl(dsl))
    repository = parse_control_repository(dsl)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "CapturedControl = Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".child_window(class_name='Edit')" in code
    )

    registry = FakeRegistry()
    registry.register_descendant({"title": "Untitled - Notepad"}, {"class_name": "Edit"})
    namespace: dict[str, object] = {}
    with fake_pywinauto_desktop(registry):
        exec(code, namespace)
    assert namespace["CapturedControl"].criteria == {"class_name": "Edit"}


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
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    text = (FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window.txt").read_text(
        encoding="utf-8"
    )
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    assert (
        "Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".wait('exists', timeout=5)" in code
    )
    assert "# TODO: map PAD wait action: UIAutomation.WaitForWindow.ToOpen" not in code

    # design/common_rpa_framework_roadmap.md 層7(b): 文字列検査だけでなく、生成された
    # `.wait()`呼び出しが実際に正しい引数(criteria/timeout)で発行されることまで検証する。
    # このフィクスチャも`Scripting.RunPythonScript`でハードコードされたWindowsパスへの
    # 書き込みを含むため(知見14等)、一時ディレクトリへ退避してからexec()する
    # (`test_generate_python_shows_full_path_for_nested_ui_element_reference`と同じ対策)。
    import os

    registry = FakeRegistry()
    registry.register_window(title="Untitled - Notepad")
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as tmp, fake_pywinauto_desktop(registry):
        try:
            os.chdir(tmp)
            exec(code, {})
        finally:
            os.chdir(original_cwd)
    wait_calls = [c for c in registry.calls if c[0] == "wait"]
    assert wait_calls == [
        ("wait", [{"title": "Untitled - Notepad"}], {"criteria": "exists", "timeout": 5})
    ]


def test_generate_python_converts_wait_for_window_to_unbounded_poll_when_timeout_is_none() -> None:
    # design/dsl_format_findings.md 知見50の追記: 「Fail with timeout error」OFFで
    # `timeout_seconds`が`None`の場合、PADは50ミリ秒間隔で無期限にポーリングを続け、
    # タイムアウトによる失敗が一切発生しない(条件が満たされるかフロー自体がキャンセル
    # されるまで待ち続ける)ことが確認できている。この意味論をでっち上げた有限タイムアウト
    # 値(pywinautoの`.wait()`任せ)に丸めず、同じ`while`+`time.sleep(0.05)`ポーリングとして
    # 再現する。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_no_timeout.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    assert (
        "while not Desktop(backend=\"uia\").window(title='Untitled - Notepad').exists():"
        in code
    )
    assert "    time.sleep(0.05)" in code
    assert "# TODO: map PAD wait action: UIAutomation.WaitForWindow.ToOpen" not in code

    # design/common_rpa_framework_roadmap.md 層7(b): ウィンドウが最初から存在する状態で
    # execし、ポーリングループが実際に(無限に回らず)即座に抜けることまで検証する。
    # このフィクスチャも`Scripting.RunPythonScript`でハードコードされたWindowsパスへの
    # 書き込みを含むため、一時ディレクトリへ退避してからexec()する。
    import os

    registry = FakeRegistry()
    registry.register_window(title="Untitled - Notepad")
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as tmp, fake_pywinauto_desktop(registry):
        try:
            os.chdir(tmp)
            exec(code, {})  # ループ条件が最初からFalseなので即座に終了するはず
        finally:
            os.chdir(original_cwd)


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
    # (ここではControlRepositoryを渡さないため、知見38/46と同じ理由でセレクタが解決できず
    # 意図的にTODOへ倒れる経路を検証している——下のテストがリポジトリありの経路を検証する)
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


def test_generate_python_from_wait_for_window_content_actually_waits_against_fake_pywinauto() -> None:
    # design/common_rpa_framework_roadmap.md 層7(b)の拡張: ControlRepositoryを渡すと
    # 上のテストとは違いTODOではなく実際の`while ...exists(): time.sleep(0.05)`ループが
    # 生成される(Element側のwait、Window側の`.wait()`パスとは別の分岐)。生成コードを
    # 実際に`exec()`し、対象の子孫コントロールが最初から存在する状態ではループが
    # ハングせず即座に抜けることまで検証する。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_content.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    assert (
        "while not Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".child_window(class_name='Edit').exists():" in code
    )

    registry = FakeRegistry()
    registry.register_descendant({"title": "Untitled - Notepad"}, {"class_name": "Edit"})
    with fake_pywinauto_desktop(registry):
        exec(code, {})  # ループ条件が最初からFalseなので即座に終了するはず
    assert registry.calls == []  # exists()自体はcallsに記録されない呼び出し


def test_generate_python_from_wait_for_window_content_not_contain_element_converts() -> None:
    # design/dsl_format_findings.md 知見196: `WindowToNotContainElement`は既存の
    # `WindowToContainElement`結線の単純な否定(同じ`Element`パラメータのみ)。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_content.txt"
    ).read_text(encoding="utf-8")
    text = text.replace("WindowToContainElement", "WindowToNotContainElement")
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    assert (
        "while Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".child_window(class_name='Edit').exists():" in code
    )

    registry = FakeRegistry()
    # 対象の子孫コントロールが存在しない状態からスタート——`not exists()`は真なので
    # `WindowToContainElement`なら無限ループするところ、`WindowToNotContainElement`は
    # 「存在しない」を待つので最初から条件(ループ継続条件)が偽で即座に終了するはず。
    with fake_pywinauto_desktop(registry):
        exec(code, {})


def test_generate_python_from_wait_for_window_content_in_state_converts() -> None:
    # design/dsl_format_findings.md 知見196(decompile確認済み): `State`列挙値は
    # `Enabled`/`Disabled`の2値のみ——pywinautoの`.is_enabled()`と対応付けた。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_content.txt"
    ).read_text(encoding="utf-8")
    text = text.replace(
        "WindowToContainElement Element:",
        "WindowToContainElementInState State: UIAutomation.State.Enabled Element:",
    )
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    assert "# TODO" not in code
    assert (
        "while not (Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".child_window(class_name='Edit').exists() and "
        "Desktop(backend=\"uia\").window(title='Untitled - Notepad')"
        ".child_window(class_name='Edit').wrapper_object().is_enabled() == True):" in code
    )

    registry = FakeRegistry()
    registry.register_descendant({"title": "Untitled - Notepad"}, {"class_name": "Edit"})
    registry.set_enabled([{"title": "Untitled - Notepad"}, {"class_name": "Edit"}], True)
    with fake_pywinauto_desktop(registry):
        exec(code, {})  # 存在してEnabled=Trueなのでループ条件は最初から偽、即座に終了するはず


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

    # design/common_rpa_framework_roadmap.md 層7(b): codegen_coverage.pyの自動走査では
    # 常に[OK]扱いだったが、この実機キャプチャ(whole-subflow)に対する実exec検証は
    # 一度も存在しなかった。
    from fake_pywinauto import FakeControl, FakeRegistry, fake_pywinauto_desktop

    registry = FakeRegistry()
    registry.register_window(title="Untitled - Notepad")
    namespace: dict[str, object] = {}
    with fake_pywinauto_desktop(registry):
        exec(code, namespace)
    assert isinstance(namespace["AutomationWindow2"], FakeControl)
    assert namespace["AutomationWindow2"].criteria == {"title": "Untitled - Notepad"}


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

    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    registry = FakeRegistry()
    registry.register_window(title="Untitled - Notepad")
    namespace: dict[str, object] = {}
    with fake_pywinauto_desktop(registry):
        exec(code, namespace)
    assert namespace["AutomationWindow2"].criteria == {"title": "Untitled - Notepad"}


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

    from fake_pywinauto import fake_pywinauto_desktop

    with fake_pywinauto_desktop() as registry:
        exec(code, {})
    assert registry.calls == [("close", [{"title": "Untitled - Notepad"}], {})]


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

    from fake_pywinauto import fake_pywinauto_desktop

    with fake_pywinauto_desktop() as registry:
        exec(code, {})
    assert registry.calls == [("set_focus", [{"title": "Untitled - Notepad"}], {})]


def test_generate_python_from_focus_window_by_instance_or_handle_converts() -> None:
    # design/dsl_format_findings.md 知見117の追記: `FocusWindow.FocusByInstanceOrHandle`は
    # `CloseWindow.CloseByInstanceOrHandle`(知見57実機確認済み)と全く同じ構造の兄弟セレクタ。
    dsl = "UIAutomation.FocusWindow.FocusByInstanceOrHandle WindowInstance: AutomationWindow2"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "AutomationWindow2.set_focus()" in code

    from fake_pywinauto import FakeControl, FakeRegistry

    registry = FakeRegistry()
    fake_window = FakeControl(registry, {"title": "Untitled - Notepad"})
    exec(code, {"AutomationWindow2": fake_window})
    assert registry.calls == [("set_focus", [{"title": "Untitled - Notepad"}], {})]
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

    # design/common_rpa_framework_roadmap.md 層7(b)(c)の拡張: `WindowInstance`変数を
    # `FakeControl`として注入し、`win32gui.MoveWindow()`が正しい引数で呼ばれることまで検証する。
    from fake_pywinauto import FakeControl, FakeRegistry, fake_pywinauto_desktop
    from fake_win32 import FakeWin32Registry, fake_win32_modules

    ui_registry = FakeRegistry()
    ui_registry.register_window(title="Untitled - Notepad")
    fake_window = FakeControl(ui_registry, {"title": "Untitled - Notepad"})
    win32_registry = FakeWin32Registry()
    win32_registry.set_rect(0, 100, 200, 900, 800)  # 既存の幅800・高さ600を保持する想定
    with fake_pywinauto_desktop(ui_registry), fake_win32_modules(win32_registry):
        exec(code, {"AutomationWindow2": fake_window})
    assert win32_registry.calls == [("MoveWindow", 0, 10, 20, 800, 600, True)]


def test_generate_python_from_resize_window_by_instance_or_handle_converts() -> None:
    dsl = "UIAutomation.ResizeWindow.ResizeByInstanceOrHandle WindowInstance: AutomationWindow2 Width: 640 Height: 480"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "win32gui.MoveWindow(_hwnd, _rect[0], _rect[1], 640, 480, True)" in code
    assert "# TODO" not in code

    from fake_pywinauto import FakeControl, FakeRegistry, fake_pywinauto_desktop
    from fake_win32 import FakeWin32Registry, fake_win32_modules

    ui_registry = FakeRegistry()
    ui_registry.register_window(title="Untitled - Notepad")
    fake_window = FakeControl(ui_registry, {"title": "Untitled - Notepad"})
    win32_registry = FakeWin32Registry()
    win32_registry.set_rect(0, 100, 200, 900, 800)  # 既存のX=100・Y=200を保持する想定
    with fake_pywinauto_desktop(ui_registry), fake_win32_modules(win32_registry):
        exec(code, {"AutomationWindow2": fake_window})
    assert win32_registry.calls == [("MoveWindow", 0, 100, 200, 640, 480, True)]


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

    # design/common_rpa_framework_roadmap.md 層7(b)の拡張: `WindowInstance`はPAD側では
    # 不透明な参照だがPython側では通常の変数参照に過ぎない(知見79/80)ため、事前に
    # `GetWindow`で取得済みのつもりの変数として`FakeControl`を直接名前空間へ注入し、
    # `.maximize()`が実際に正しいパスで呼ばれることまで検証する。
    from fake_pywinauto import FakeControl, FakeRegistry, fake_pywinauto_desktop

    registry = FakeRegistry()
    fake_window = FakeControl(registry, {"title": "Untitled - Notepad"})
    with fake_pywinauto_desktop(registry):
        exec(code, {"AutomationWindow2": fake_window})
    assert registry.calls == [("maximize", [{"title": "Untitled - Notepad"}], {})]


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

    from fake_pywinauto import FakeControl, FakeRegistry, fake_pywinauto_desktop
    from fake_win32 import FakeWin32Registry, fake_win32_modules

    ui_registry = FakeRegistry()
    ui_registry.register_window(title="Untitled - Notepad")
    fake_window = FakeControl(ui_registry, {"title": "Untitled - Notepad"})
    win32_registry = FakeWin32Registry()
    with fake_pywinauto_desktop(ui_registry), fake_win32_modules(win32_registry):
        exec(code, {"AutomationWindow2": fake_window})
    assert win32_registry.calls == [("ShowWindow", 0, 0)]


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

    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop
    from fake_win32 import FakeWin32Registry, fake_win32_modules

    ui_registry = FakeRegistry()
    ui_registry.register_window(title="Notepad")
    win32_registry = FakeWin32Registry()
    with fake_pywinauto_desktop(ui_registry), fake_win32_modules(win32_registry):
        exec(code, {})
    assert win32_registry.calls == [("ShowWindow", 0, 5)]


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

    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop
    from fake_win32 import FakeWin32Registry, fake_win32_modules

    ui_registry = FakeRegistry()
    ui_registry.register_window(title="Untitled - Notepad")
    win32_registry = FakeWin32Registry()
    win32_registry.set_rect(0, 100, 200, 900, 800)  # 既存の幅800・高さ600を保持する想定
    with fake_pywinauto_desktop(ui_registry), fake_win32_modules(win32_registry):
        exec(code, {})
    assert win32_registry.calls == [("MoveWindow", 0, 10, 20, 800, 600, True)]


def test_generate_python_from_resize_window_control_based_converts() -> None:
    # design/dsl_format_findings.md 知見119: `Control`ベースの兄弟セレクタ(`.Resize`)。
    # 層7(b)(c)でまだexec検証していなかった実在のギャップ(`ResizeByTitleClass`/
    # `ResizeByInstanceOrHandle`は既にテスト済みだったが、この`Control`ベース変種には
    # compileテストすら存在していなかった)。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_get_window.txt").read_text(
        encoding="utf-8"
    )
    text = text.replace(
        "UIAutomation.GetWindow.GetUseTimeout Control: appmask['Window \\'Untitled - Notepad\\''] "
        "BringWindowToFront: False Timeout: 5 WindowInstance=> AutomationWindow2",
        "UIAutomation.ResizeWindow.Resize Control: appmask['Window \\'Untitled - Notepad\\''] "
        "Width: 1024 Height: 768",
    )
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert "_hwnd = Desktop(backend=\"uia\").window(title='Untitled - Notepad').wrapper_object().handle" in code
    assert "win32gui.MoveWindow(_hwnd, _rect[0], _rect[1], 1024, 768, True)" in code
    assert "# TODO: map PAD action: UIAutomation.ResizeWindow.Resize" not in code

    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop
    from fake_win32 import FakeWin32Registry, fake_win32_modules

    ui_registry = FakeRegistry()
    ui_registry.register_window(title="Untitled - Notepad")
    win32_registry = FakeWin32Registry()
    win32_registry.set_rect(0, 100, 200, 900, 800)  # 既存のX=100・Y=200を保持する想定
    with fake_pywinauto_desktop(ui_registry), fake_win32_modules(win32_registry):
        exec(code, {})
    assert win32_registry.calls == [("MoveWindow", 0, 100, 200, 1024, 768, True)]


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

    # design/common_rpa_framework_roadmap.md 層7(b)の拡張: `Control`ベースの経路
    # (Title/Classベースとは別のセレクタ解決ロジック)でも`.minimize()`が実際に
    # 呼ばれることを検証する。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    registry = FakeRegistry()
    with fake_pywinauto_desktop(registry):
        exec(code, {})
    assert registry.calls == [("minimize", [{"title": "Untitled - Notepad"}], {})]
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


def test_generate_python_from_calculator_button_actually_clicks_full_chain_against_fake_pywinauto() -> None:
    # design/common_rpa_framework_roadmap.md 層7(b)の拡張: 上のテストは生成コードの
    # *文字列*しか検査していなかった——知見56のバグ(チェーンが中間のpane止まりになる)は
    # まさに「正しい形の呼び出し列を組み立てているか」という層7(b)の守備範囲そのものなので、
    # 実際に`exec()`し、`.click_input()`が3段チェーンの正しいフルパスで(ループ2回分)
    # 呼ばれることまで検証する。
    import os

    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop

    text = (FIXTURES_DIR / "looptest_whole_subflow_with_calculator_button.txt").read_text(
        encoding="utf-8"
    )
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)

    registry = FakeRegistry()
    registry.register_window(title="Untitled - Notepad")
    # このフィクスチャも`Scripting.RunPythonScript`でハードコードされたWindowsパスへの
    # 書き込みを含むため、一時ディレクトリへ退避してからexec()する。
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as tmp, fake_pywinauto_desktop(registry):
        try:
            os.chdir(tmp)
            exec(code, {})
        finally:
            os.chdir(original_cwd)

    expected_path = [
        {"title": "Calculator"},
        {"class_name": "CalcFrame"},
        {"class_name": "Button", "title": "7"},
    ]
    click_calls = [c for c in registry.calls if c[0] == "click_input"]
    assert click_calls == [("click_input", expected_path, {})] * 2  # ループ2回分


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

    from fake_pywinauto import FakeControl, FakeRegistry

    registry = FakeRegistry()
    fake_window = FakeControl(registry, {"title": "Untitled - Notepad"})
    exec(code, {"AutomationWindow2": fake_window})
    assert registry.calls == [("close", [{"title": "Untitled - Notepad"}], {})]


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

    # design/common_rpa_framework_roadmap.md 層7(b)(c)の拡張: `.window_text()`を
    # fake_pywinautoに追加し、実際に`exec()`してフォアグラウンドウィンドウのハンドル解決
    # ・タイトル取得まで一通り検証する。
    from fake_pywinauto import FakeRegistry, fake_pywinauto_desktop
    from fake_win32 import FakeWin32Registry, fake_win32_modules

    ui_registry = FakeRegistry()
    ui_registry.register_window(handle=42)
    ui_registry.set_window_text([{"handle": 42}], "Untitled - Notepad")
    win32_registry = FakeWin32Registry()
    win32_registry.set_foreground(42)
    namespace: dict[str, object] = {}
    with fake_pywinauto_desktop(ui_registry), fake_win32_modules(win32_registry):
        exec(code, namespace)
    assert namespace["WindowTitle2"] == "Untitled - Notepad"


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

    # tools/check_exec_assertions.py(design/common_rpa_framework_roadmap.md 層4)が検出した
    # 穴: 以前はexec()がクラッシュしないことだけを見ており、コメントで「実際に真偽値として
    # 正しく評価できることまで確認する」と書いていながら実際には確認していなかった。
    # Var1="hello"/Var2="ell"という既知の値に対し、4本の条件式が実際に正しい真偽値になる
    # ことまでeval()で確認する。
    namespace: dict[str, object] = {}
    exec(code, namespace)
    condition_lines = [line.removeprefix("if ").removesuffix(":") for line in code.splitlines() if line.startswith("if ")]
    assert condition_lines == ["Var2 in Var1", "Var2 not in Var1", "not Var1", "bool(Var1)"]
    assert [eval(c, namespace) for c in condition_lines] == [True, False, False, True]


def test_generate_python_from_unknown_function_condition_raises() -> None:
    # 知見75の対照実験(`Blurgle(Var1, Var1)`はPAD自身に認識されず"Has error"になった)と
    # 同じ理由で、既知の4関数以外は安全にNotImplementedErrorへ倒す。
    dsl = "SET Var1 TO $'''hello'''\nIF Blurgle(Var1, Var1) THEN\nSET Var2 TO $'''x'''\nEND"
    tree = build_block_tree(parse_dsl(dsl))
    with pytest.raises(NotImplementedError, match="Blurgle"):
        generate_python(tree)


def test_generate_python_from_real_if_function_endswith_startswith_converts_case_insensitive() -> None:
    # design/dsl_format_findings.md 知見204: 知見75のペースト往復手法で`EndsWith`/
    # `StartsWith`が標準If条件UIから到達可能(エラー無く自然文表示される)ことを実機確認、
    # 続けて知見81のRun実行+ファイル書き出し手法で実際の真偽値を確認したところ、両者とも
    # 大文字小文字を区別しないことが判明した("Hello World".EndsWith("world") == True)。
    dsl = (
        "SET Var1 TO $'''Hello World'''\n"
        "SET Var2 TO $'''world'''\n"
        "IF EndsWith(Var1, Var2) THEN\n"
        "END\n"
        "SET Var3 TO $'''HEL'''\n"
        "IF StartsWith(Var1, Var3) THEN\n"
        "END\n"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "from dump_daemon.pad_action_lib import text_actions" in code
    assert "if text_actions.function_condition_ends_with(Var1, Var2):" in code
    assert "if text_actions.function_condition_starts_with(Var1, Var3):" in code
    assert "# TODO" not in code
    assert "NotImplementedError" not in code

    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["Var1"] == "Hello World"


def test_function_condition_ends_with_starts_with_are_case_insensitive() -> None:
    # 知見204で実機確認済みの挙動そのものの単体テスト。
    from dump_daemon.pad_action_lib import text_actions

    assert text_actions.function_condition_ends_with("Hello World", "World") is True
    assert text_actions.function_condition_ends_with("Hello World", "world") is True
    assert text_actions.function_condition_ends_with("hello", "llo") is True
    assert text_actions.function_condition_ends_with("hello", "xyz") is False
    assert text_actions.function_condition_starts_with("hello", "hel") is True
    assert text_actions.function_condition_starts_with("hello", "HEL") is True
    assert text_actions.function_condition_starts_with("hello", "xyz") is False


def test_function_condition_ends_with_starts_with_reject_non_string_arguments() -> None:
    # 知見200が指摘するDataRow/IList型への多態的な挙動は未確認のため、文字列以外は
    # でっち上げずに例外を投げる(design/dsl_format_findings.md 知見204)。
    from dump_daemon.pad_action_lib import text_actions

    with pytest.raises(text_actions.UnsupportedFunctionConditionArgumentError):
        text_actions.function_condition_ends_with(["a", "b"], "b")
    with pytest.raises(text_actions.UnsupportedFunctionConditionArgumentError):
        text_actions.function_condition_starts_with("hello", 1)


@pytest.mark.parametrize("function_name", ["ContainsKey", "Count", "Blank"])
def test_generate_python_from_real_if_function_unreachable_names_raise(function_name: str) -> None:
    # design/dsl_format_findings.md 知見204: `ContainsKey`/`Count`/`Blank`は知見75の
    # ペースト往復手法で標準If条件UIから到達不能("Has error")と実機確認済み——`IsEmpty`の
    # でっち上げた別名として結線しないよう、意図的に未対応のまま安全にNotImplementedErrorへ
    # 倒す(到達可能だが真偽値の意味論が未確認の`IsBlank`も同じ理由で未対応)。
    args = "Var1" if function_name in ("Count", "Blank") else "Var1, Var1"
    dsl = f"SET Var1 TO $'''hello'''\nIF {function_name}({args}) THEN\nEND\n"
    tree = build_block_tree(parse_dsl(dsl))
    with pytest.raises(NotImplementedError, match=function_name):
        generate_python(tree)


def test_generate_python_from_pdf_extract_text_minimal_params_uses_defaults() -> None:
    # design/dsl_format_findings.md 知見156(`ActionSelectorBase`一括列挙監査、知見155の
    # Excelの手法をPDFへ適用): `ExtractTextFromPDFAction`には`PagesToExtract`
    # (`ExtractionMode`: All/Single/Range)を固定する3兄弟セレクタがあり、真のaction_idは
    # `Pdf.ExtractTextFromPDF.ExtractText`等の3セグメント形式——知見78時点のフラットな
    # `Pdf.ExtractTextFromPDF`は実際のDSLでは一度もマッチしなかった(知見156で修正)。
    # オプション引数(PageNumber/FromPageNumber/ToPageNumber/Password/DetectLayout)を
    # 省略した最小形――PAD UI側でデフォルトのまま変更していない場合に一致する。
    dsl = "Pdf.ExtractTextFromPDF.ExtractText PDFFile: $'''C:\\test.pdf''' ExtractedText=> ExtractedText"
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
    # 知見156: `ExtractTextFromPage`セレクタ(`PagesToExtract=Single`固定、decompileで
    # 確認済みの実際の列挙値——`SinglePage`ではない)。
    dsl = (
        "Pdf.ExtractTextFromPDF.ExtractTextFromPage PDFFile: $'''C:\\test.pdf''' "
        "PageNumber: 2 FromPageNumber: 1 "
        "ToPageNumber: 3 Password: $'''secret''' DetectLayout: True "
        "ExtractedText=> ExtractedText"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert (
        "ExtractedText = pdf_actions.extract_text_from_pdf('C:\\\\test.pdf', "
        "pages_to_extract='Single', page_number=2, from_page_number=1, to_page_number=3, "
        "password='secret', detect_layout=True)" in code
    )
    assert "# TODO" not in code


def test_generate_python_from_pdf_extract_text_without_output_var_falls_back_to_todo() -> None:
    # `node.output_var`無しは実機では起こらない想定外の形だが、でっち上げたコードを
    # 出力せず安全にTODOへ倒ることを確認する(他のTier1/2アクションと同じ安全策)。
    dsl = "Pdf.ExtractTextFromPDF.ExtractText PDFFile: $'''C:\\test.pdf'''"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Pdf.ExtractTextFromPDF.ExtractText" in code


def test_generate_python_from_pdf_extract_images_minimal_params_uses_defaults() -> None:
    # 知見156: `ExtractImagesFromPDFAction`も同じ3兄弟セレクタ構造。PAD側に
    # `OutputArgument`が無い(ファイル書き出しのみ)ため、他のアクションと違い
    # `node.output_var`を要求しない。
    dsl = (
        "Pdf.ExtractImagesFromPDF.ExtractImages PDFFile: $'''C:\\test.pdf''' "
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
    # 知見156: `ExtractTablesFromPDFAction`も同じ3兄弟セレクタ構造(`ExtractTables`=All固定)。
    dsl = (
        "Pdf.ExtractTablesFromPDF.ExtractTables PDFFile: $'''C:\\test.pdf''' "
        "MultiPageTables: False "
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
    # design/dsl_format_findings.md 知見155: 知見80では「14アクションが存在する」ことを
    # PADデザイナーの検索結果TreeItemのAutomationIdで確認していたが、これはアクション
    # グループのAutomationIdであり、`LaunchExcel`/`WriteToExcel`/`ReadFromExcel`/
    # `DeleteWorksheet`/`RenameWorksheet`/`SetActiveWorksheet`/`SaveExcel`/`CloseExcel`は
    # 実際には兄弟セレクタを持ち、DSL上の真のaction_idは`Excel.<グループ>.<ActionName>`
    # という3セグメント形式(`ActionSelectorBase`一括列挙監査で確認)——従来のこのテストの
    # フラットなaction_id(`Excel.LaunchExcel`等)は実在しない形式だった(知見155で修正)。
    # パラメータ名はdocs-local/pad_excel_findings.mdのdecompile調査から。
    # `Instance`はPAD側では不透明な参照だが、Python側では他の変数参照と同じ
    # (ここではLaunchExcelの出力変数名をそのまま後続アクションに渡す)。
    dsl = (
        "Excel.LaunchExcel.Launch Instance=> ExcelInstance\n"
        "Excel.AddWorksheet Instance: ExcelInstance Name: $'''Sheet2''' "
        "WorksheetPosition: Excel.WorksheetPosition.Last\n"
        "Excel.WriteToExcel.WriteCell Instance: ExcelInstance Value: $'''hello''' "
        "Column: $'''B''' Row: 2\n"
        "Excel.ReadFromExcel.ReadCell Instance: ExcelInstance "
        "StartColumn: $'''B''' StartRow: 2 CellValue=> CellValue\n"
        "Excel.DeleteWorksheet.DeleteWorksheetByName Instance: ExcelInstance Name: $'''Sheet2'''\n"
        "Excel.RenameWorksheet.RenameWorksheetWithIndex Instance: ExcelInstance "
        "NewName: $'''Renamed''' Index: 0\n"
        "Excel.SetActiveWorksheet.ActivateWorksheetByName Instance: ExcelInstance "
        "Name: $'''Renamed'''\n"
        "Excel.GetActiveWorksheet Instance: ExcelInstance "
        "Name=> SheetName Index=> SheetIndex\n"
        "Excel.GetAllWorksheets Instance: ExcelInstance Worksheets=> SheetNames\n"
        "Excel.GetColumnName CellColumnIndex: 28 ColumnName=> ColumnName\n"
        "Excel.GetFirstFreeColumnRow Instance: ExcelInstance "
        "FirstFreeColumn=> FreeCol FirstFreeRow=> FreeRow\n"
        "Excel.GetFirstFreeRowOnColumn Instance: ExcelInstance Column: $'''A''' "
        "FirstFreeRowOnColumn=> FreeRowOnA\n"
        "Excel.DeleteColumn Instance: ExcelInstance Column: $'''C'''\n"
        "Excel.InsertColumn Instance: ExcelInstance Column: $'''D'''\n"
        "Excel.DeleteRow Instance: ExcelInstance Index: 5\n"
        "Excel.InsertRow Instance: ExcelInstance Index: 6\n"
        "Excel.SaveExcel.Save Instance: ExcelInstance\n"
        "Excel.CloseExcel.Close Instance: ExcelInstance"
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
    assert "excel_actions.delete_column(ExcelInstance, 'C')" in code
    assert "excel_actions.insert_column(ExcelInstance, 'D')" in code
    assert "excel_actions.delete_row(ExcelInstance, 5)" in code
    assert "excel_actions.insert_row(ExcelInstance, 6)" in code
    assert "excel_actions.save_excel(ExcelInstance, save_mode='Save')" in code
    assert "excel_actions.close_excel(ExcelInstance, close_mode='DoNotSave')" in code
    assert "# TODO" not in code


def test_generate_python_from_excel_full_scope_batch_actually_executes_correctly(tmp_path: Path) -> None:
    # design/dsl_format_findings.md 知見124/129/130で繰り返し確認された死角(文字列一致
    # だけの`compile()`テストは、生成コードを実際に`exec()`した際の出力変数の実際の値を
    # 一度も検証していない)を、`test_generate_python_from_excel_full_scope_in_batch_
    # converts_all_actions`(同一DSLの文字列一致版、`compile()`のみ)について塞ぐ。
    # `Excel.SaveExcel.Save`(パス未指定)は`instance.path`が無い`NewDocument`では
    # 実行時に必ず失敗するため、ここでは代わりに`SaveAs`で実在する一時パスへ保存する
    # (action_id自体は別の、同じく知見155で確認済みの兄弟セレクタ)。
    dest = tmp_path / "out.xlsx"
    dsl = (
        "Excel.LaunchExcel.Launch Instance=> ExcelInstance\n"
        "Excel.AddWorksheet Instance: ExcelInstance Name: $'''Sheet2''' "
        "WorksheetPosition: Excel.WorksheetPosition.Last\n"
        "Excel.WriteToExcel.WriteCell Instance: ExcelInstance Value: $'''hello''' "
        "Column: $'''B''' Row: 2\n"
        "Excel.ReadFromExcel.ReadCell Instance: ExcelInstance "
        "StartColumn: $'''B''' StartRow: 2 CellValue=> CellValue\n"
        "Excel.DeleteWorksheet.DeleteWorksheetByName Instance: ExcelInstance Name: $'''Sheet2'''\n"
        "Excel.RenameWorksheet.RenameWorksheetWithIndex Instance: ExcelInstance "
        "NewName: $'''Renamed''' Index: 0\n"
        "Excel.SetActiveWorksheet.ActivateWorksheetByName Instance: ExcelInstance "
        "Name: $'''Renamed'''\n"
        "Excel.GetActiveWorksheet Instance: ExcelInstance "
        "Name=> SheetName Index=> SheetIndex\n"
        "Excel.GetAllWorksheets Instance: ExcelInstance Worksheets=> SheetNames\n"
        "Excel.GetColumnName CellColumnIndex: 28 ColumnName=> ColumnName\n"
        "Excel.GetFirstFreeColumnRow Instance: ExcelInstance "
        "FirstFreeColumn=> FreeCol FirstFreeRow=> FreeRow\n"
        "Excel.GetFirstFreeRowOnColumn Instance: ExcelInstance Column: $'''A''' "
        "FirstFreeRowOnColumn=> FreeRowOnA\n"
        "Excel.DeleteColumn Instance: ExcelInstance Column: $'''C'''\n"
        "Excel.InsertColumn Instance: ExcelInstance Column: $'''D'''\n"
        "Excel.DeleteRow Instance: ExcelInstance Index: 5\n"
        "Excel.InsertRow Instance: ExcelInstance Index: 6\n"
        f"Excel.SaveExcel.SaveAs Instance: ExcelInstance DocumentPath: $'''{dest}'''\n"
        "Excel.CloseExcel.Close Instance: ExcelInstance"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code

    namespace: dict[str, object] = {}
    exec(code, namespace)

    assert namespace["CellValue"] == "hello"
    assert namespace["SheetName"] == "Renamed"
    assert namespace["SheetIndex"] == 0
    assert namespace["SheetNames"] == ["Renamed"]
    assert namespace["ColumnName"] == "AB"
    assert namespace["FreeCol"] == 3
    assert namespace["FreeRow"] == 3
    assert namespace["FreeRowOnA"] == 1

    import openpyxl

    reopened = openpyxl.load_workbook(dest)
    assert reopened.sheetnames == ["Renamed"]
    assert reopened["Renamed"]["B2"].value == "hello"


def test_generate_python_from_excel_get_table_range_converts() -> None:
    # design/dsl_format_findings.md 知見180(decompile確認済み): `IsPivot=False`側は
    # COMの`ListObject.Range`(ヘッダー行を含むテーブル全体)——openpyxlの`Table.ref`も
    # 同じ意味なので1:1対応する。`AddTable`相当のTier1アクションが本プロジェクトに
    # 無いため、テーブル自体の作成だけプレーンなopenpyxl呼び出しで行い(生成コードの
    # 検証対象ではない)、`GetTableRange`の変換・実行結果はDSL経由の生成コードで検証する。
    setup_dsl = (
        "Excel.LaunchExcel.Launch Instance=> ExcelInstance\n"
        "Excel.WriteToExcel.WriteCell Instance: ExcelInstance Value: $'''Name''' "
        "Column: $'''A''' Row: 1\n"
        "Excel.WriteToExcel.WriteCell Instance: ExcelInstance Value: $'''Age''' "
        "Column: $'''B''' Row: 1\n"
        "Excel.WriteToExcel.WriteCell Instance: ExcelInstance Value: $'''Carol''' "
        "Column: $'''A''' Row: 2\n"
        "Excel.WriteToExcel.WriteCell Instance: ExcelInstance Value: 30 "
        "Column: $'''B''' Row: 2"
    )
    tree = build_block_tree(parse_dsl(setup_dsl))
    setup_code = generate_python(tree)
    namespace: dict[str, object] = {}
    exec(setup_code, namespace)

    from openpyxl.worksheet.table import Table

    namespace["ExcelInstance"].active_sheet.add_table(Table(displayName="MyTable", ref="A1:B2"))

    dsl = (
        "Excel.GetTableRange Instance: ExcelInstance TableName: $'''MyTable''' "
        "FirstRowIndex=> FirstRow FirstColumnIndex=> FirstCol "
        "LastRowIndex=> LastRow LastColumnIndex=> LastCol"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "_table_range = excel_actions.get_table_range(ExcelInstance, 'MyTable')" in code
    assert "FirstRow = _table_range[0]" in code
    assert "FirstCol = _table_range[1]" in code
    assert "LastRow = _table_range[2]" in code
    assert "LastCol = _table_range[3]" in code
    assert "# TODO" not in code

    exec(code, namespace)
    assert namespace["FirstRow"] == 1
    assert namespace["FirstCol"] == 1
    assert namespace["LastRow"] == 2
    assert namespace["LastCol"] == 2


def test_generate_python_keeps_get_table_range_as_todo_when_is_pivot_true() -> None:
    # 知見180: `IsPivot=True`はopenpyxlに対応APIが無いため安全にTODOへ倒す。
    dsl = (
        "Excel.GetTableRange Instance: ExcelInstance TableName: $'''MyTable''' "
        "IsPivot: True FirstRowIndex=> FirstRow FirstColumnIndex=> FirstCol "
        "LastRowIndex=> LastRow LastColumnIndex=> LastCol"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Excel.GetTableRange" in code


def test_generate_python_from_excel_read_cell_formula_by_coordinates_converts() -> None:
    # design/dsl_format_findings.md 知見190: `write_to_excel()`が数式文字列をそのまま
    # 書き込むことと対になる読み取り側。
    setup_dsl = (
        "Excel.LaunchExcel.Launch Instance=> ExcelInstance\n"
        "Excel.WriteToExcel.WriteCell Instance: ExcelInstance Value: $'''=1+2''' "
        "Column: $'''A''' Row: 1"
    )
    tree = build_block_tree(parse_dsl(setup_dsl))
    namespace: dict[str, object] = {}
    exec(generate_python(tree), namespace)

    dsl = (
        "Excel.ReadCellFormula.ReadFormulaFromCellCoordinates Instance: ExcelInstance "
        "Column: $'''A''' Row: 1 CellFormula=> CellFormula"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "CellFormula = excel_actions.read_cell_formula(ExcelInstance, 'CellCoordinates', column='A', row=1)" in code
    assert "# TODO" not in code

    exec(code, namespace)
    assert namespace["CellFormula"] == "=1+2"


def test_generate_python_from_excel_read_cell_formula_by_named_cell_converts() -> None:
    setup_dsl = "Excel.LaunchExcel.Launch Instance=> ExcelInstance"
    tree = build_block_tree(parse_dsl(setup_dsl))
    namespace: dict[str, object] = {}
    exec(generate_python(tree), namespace)

    import openpyxl.workbook.defined_name

    instance = namespace["ExcelInstance"]
    sheet = instance.active_sheet
    sheet["B2"] = "=SUM(A1:A5)"
    instance.workbook.defined_names["MyFormulaCell"] = openpyxl.workbook.defined_name.DefinedName(
        "MyFormulaCell", attr_text=f"'{sheet.title}'!$B$2"
    )

    dsl = (
        "Excel.ReadCellFormula.ReadFormulaFromNamedCell Instance: ExcelInstance "
        "CellName: $'''MyFormulaCell''' CellFormula=> CellFormula"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "CellFormula = excel_actions.read_cell_formula(ExcelInstance, 'NamedCell', cell_name='MyFormulaCell')" in code
    assert "# TODO" not in code

    exec(code, namespace)
    assert namespace["CellFormula"] == "=SUM(A1:A5)"


def test_generate_python_from_excel_get_empty_cell_first_empty_cell_coordinates_converts() -> None:
    # design/dsl_format_findings.md 知見192: `GetEmptyCellFromExcel`の8兄弟セレクタのうち
    # `GetEmptyCellsAbsoluteRangeFirstEmptyCell`(行優先探索)。
    setup_dsl = (
        "Excel.LaunchExcel.Launch Instance=> ExcelInstance\n"
        "Excel.WriteToExcel.WriteCell Instance: ExcelInstance Value: $'''x''' "
        "Column: $'''A''' Row: 1"
    )
    tree = build_block_tree(parse_dsl(setup_dsl))
    namespace: dict[str, object] = {}
    exec(generate_python(tree), namespace)

    dsl = (
        "Excel.GetEmptyCellFromExcel.GetEmptyCellsAbsoluteRangeFirstEmptyCell "
        "Instance: ExcelInstance StartColumn: $'''A''' StartRow: 1 EndColumn: $'''B''' "
        "EndRow: 2 EmptyCellsSearchDirection: Excel.EmptyCellsSearchDirection.Rows "
        "EmptyCellColumnIndex=> EmptyCol EmptyCellRowIndex=> EmptyRow"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "_empty_cell = excel_actions.get_empty_cell(ExcelInstance, operation='FirstEmptyCell', "
        "range_mode='Coordinates', start_column='A', start_row=1, end_column='B', end_row=2, "
        "search_direction='Rows')" in code
    )
    assert "EmptyCol = _empty_cell[0]" in code
    assert "EmptyRow = _empty_cell[1]" in code

    exec(code, namespace)
    assert namespace["EmptyCol"] == 2
    assert namespace["EmptyRow"] == 1


def test_generate_python_from_excel_get_empty_cell_all_empty_cells_named_cell_converts() -> None:
    setup_dsl = "Excel.LaunchExcel.Launch Instance=> ExcelInstance"
    tree = build_block_tree(parse_dsl(setup_dsl))
    namespace: dict[str, object] = {}
    exec(generate_python(tree), namespace)

    import openpyxl.workbook.defined_name

    instance = namespace["ExcelInstance"]
    sheet = instance.active_sheet
    sheet["A1"] = "x"
    instance.workbook.defined_names["MyRange"] = openpyxl.workbook.defined_name.DefinedName(
        "MyRange", attr_text=f"'{sheet.title}'!$A$1:$B$1"
    )

    dsl = (
        "Excel.GetEmptyCellFromExcel.GetEmptyCellsNamedCellAllEmptyCells "
        "Instance: ExcelInstance NamedCell: $'''MyRange''' EmptyCells=> EmptyCells"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert (
        "EmptyCells = excel_actions.get_empty_cell(ExcelInstance, operation='AllEmptyCells', "
        "range_mode='NamedCell', named_cell='MyRange')" in code
    )

    exec(code, namespace)
    assert namespace["EmptyCells"] == [{"ColumnIndex": 2, "RowIndex": 1}]


def test_generate_python_from_excel_copy_worksheet_by_name_converts() -> None:
    # design/dsl_format_findings.md 知見193: `SourceInstance`/`TargetInstance`が同一
    # インスタンス参照であれば同一ワークブック内コピーとして実行できる。
    setup_dsl = "Excel.LaunchExcel.Launch Instance=> ExcelInstance"
    tree = build_block_tree(parse_dsl(setup_dsl))
    namespace: dict[str, object] = {}
    exec(generate_python(tree), namespace)
    instance = namespace["ExcelInstance"]
    source_name = instance.workbook.sheetnames[0]
    instance.active_sheet["A1"] = "hi"

    dsl = (
        "Excel.CopyExcelWorksheet.CopyWorksheetWithName "
        f"SourceInstance: ExcelInstance TargetInstance: ExcelInstance SourceWorksheetName: $'''{source_name}''' "
        "TargetWorksheetName: $'''Copy1''' PasteWorksheetPosition: Excel.WorksheetPosition.Last"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        f"excel_actions.copy_excel_worksheet(ExcelInstance, ExcelInstance, 'Copy1', "
        f"find_worksheet_by='Name', source_worksheet_name='{source_name}', "
        "paste_worksheet_position='Last')" in code
    )

    exec(code, namespace)
    assert instance.workbook.sheetnames == [source_name, "Copy1"]
    assert instance.workbook["Copy1"]["A1"].value == "hi"


def test_generate_python_from_excel_clear_cells_absolute_converts() -> None:
    # design/dsl_format_findings.md 知見194: COMの`Range.Clear()`(値・書式両方)相当。
    setup_dsl = (
        "Excel.LaunchExcel.Launch Instance=> ExcelInstance\n"
        "Excel.WriteToExcel.WriteCell Instance: ExcelInstance Value: $'''x''' "
        "Column: $'''A''' Row: 1"
    )
    tree = build_block_tree(parse_dsl(setup_dsl))
    namespace: dict[str, object] = {}
    exec(generate_python(tree), namespace)

    dsl = (
        "Excel.ClearCellsFromExcel.ClearCells Instance: ExcelInstance "
        "StartColumn: $'''A''' StartRow: 1 EndColumn: $'''A''' EndRow: 1"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "excel_actions.clear_cells(ExcelInstance, mode='Absolute', start_column='A', "
        "start_row=1, end_column='A', end_row=1)" in code
    )

    exec(code, namespace)
    assert namespace["ExcelInstance"].active_sheet["A1"].value is None


def test_generate_python_from_excel_clear_cells_relative_to_falls_back_to_todo() -> None:
    # 知見194: `ClearCellsRelativeTo`はライブExcel UIの`ActiveCell`を基準点にするため
    # `excel_actions.clear_cells()`側で`NotImplementedError`に委ねる(ここでは分岐無し)。
    dsl = (
        "Excel.ClearCellsFromExcel.ClearCellsRelativeTo Instance: ExcelInstance "
        "HorizontalDirection: Excel.HorizontalDirection.Left OffsetX: 1 "
        "VerticalDirection: Excel.VerticalDirection.Above OffsetY: 1"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Excel.ClearCellsFromExcel.ClearCellsRelativeTo" in code


def test_generate_python_from_excel_resize_single_column_converts() -> None:
    # design/dsl_format_findings.md 知見195: `[Action(Id = "ResizeColumnsOrRows")]`が
    # クラス名の`...Action`接尾辞を取り除く——action_idは3セグメント形式。
    setup_dsl = "Excel.LaunchExcel.Launch Instance=> ExcelInstance"
    tree = build_block_tree(parse_dsl(setup_dsl))
    namespace: dict[str, object] = {}
    exec(generate_python(tree), namespace)

    dsl = "Excel.ResizeColumnsOrRows.ResizeSingleColumn Instance: ExcelInstance Column: $'''A''' Width: 25"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "excel_actions.resize_columns_or_rows(ExcelInstance, 25, resize_target='Column', "
        "selection_range='Single', column='A')" in code
    )

    exec(code, namespace)
    assert namespace["ExcelInstance"].active_sheet.column_dimensions["A"].width == 25


def test_generate_python_from_excel_resize_all_rows_converts() -> None:
    setup_dsl = "Excel.LaunchExcel.Launch Instance=> ExcelInstance"
    tree = build_block_tree(parse_dsl(setup_dsl))
    namespace: dict[str, object] = {}
    exec(generate_python(tree), namespace)

    dsl = "Excel.ResizeColumnsOrRows.ResizeAllRows Instance: ExcelInstance Height: 40"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "excel_actions.resize_columns_or_rows(ExcelInstance, 40, resize_target='Row', "
        "selection_range='AllAvailable')" in code
    )

    exec(code, namespace)
    assert namespace["ExcelInstance"].active_sheet.sheet_format.defaultRowHeight == 40


def test_generate_python_from_excel_autofit_falls_back_to_todo() -> None:
    # 知見195: Autofit側(ライブExcel COMのレンダリングエンジン依存、知見190で確認済み)は
    # 分岐を追加せず安全にTODOへ倒れる。
    dsl = "Excel.ResizeColumnsOrRows.AutofitSingleColumn Instance: ExcelInstance Column: $'''A'''"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Excel.ResizeColumnsOrRows.AutofitSingleColumn" in code


def test_generate_python_from_excel_delete_cell_converts() -> None:
    # design/dsl_format_findings.md 知見197: `[Action(Id = "DeleteCells")]`が
    # クラス名の`...Action`接尾辞を取り除く(知見195と同じパターン)。
    setup_dsl = (
        "Excel.LaunchExcel.Launch Instance=> ExcelInstance\n"
        "Excel.WriteToExcel.WriteCell Instance: ExcelInstance Value: $'''a''' "
        "Column: $'''A''' Row: 1\n"
        "Excel.WriteToExcel.WriteCell Instance: ExcelInstance Value: $'''b''' "
        "Column: $'''B''' Row: 1"
    )
    tree = build_block_tree(parse_dsl(setup_dsl))
    namespace: dict[str, object] = {}
    exec(generate_python(tree), namespace)

    dsl = (
        "Excel.DeleteCells.DeleteCell Instance: ExcelInstance StartColumn: $'''A''' StartRow: 1 "
        "ShiftCellsDirection: Excel.ShiftCellsDirection.Left"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "excel_actions.delete_cells(ExcelInstance, mode='SingleCell', start_column='A', "
        "start_row=1, shift_direction='Left')" in code
    )

    exec(code, namespace)
    sheet = namespace["ExcelInstance"].active_sheet
    assert sheet["A1"].value == "b"


def test_generate_python_from_excel_unsupported_live_com_modes_fall_back_to_todo() -> None:
    # design/dsl_format_findings.md 知見155: `ReadFromExcel.Read`(`ReadMode=Selection`、
    # ライブExcel UIの現在の選択範囲)・`WriteToExcel.Write`(`WriteMode=ActiveCell`、
    # ライブExcel UIのアクティブセル)はセレクタ自体がスコープ外の値に固定されているため、
    # でっち上げたコードを出力せず安全にTODOへ倒れることを確認する。
    read_selection_dsl = "Excel.ReadFromExcel.Read Instance: ExcelInstance"
    tree = build_block_tree(parse_dsl(read_selection_dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Excel.ReadFromExcel.Read" in code

    write_active_cell_dsl = "Excel.WriteToExcel.Write Instance: ExcelInstance Value: $'''x'''"
    tree = build_block_tree(parse_dsl(write_active_cell_dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Excel.WriteToExcel.Write" in code

    plain_text_dsl = (
        "Excel.ReadFromExcel.ReadCell Instance: ExcelInstance "
        "GetCellContentsMode: Excel.GetCellContentsMode.PlainText CellValue=> CellValue"
    )
    tree = build_block_tree(parse_dsl(plain_text_dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Excel.ReadFromExcel.ReadCell" in code

    launch_under_existing_process_dsl = "Excel.LaunchExcel.LaunchUnderExistingProcess Instance=> ExcelInstance"
    tree = build_block_tree(parse_dsl(launch_under_existing_process_dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Excel.LaunchExcel.LaunchUnderExistingProcess" in code


def test_generate_python_from_word_full_scope_in_batch_converts_all_actions() -> None:
    # design/dsl_format_findings.md 知見157: 知見80の「Word.*のaction_idは実機確認済み」は
    # アクショングループのAutomationId確認に過ぎず、`CloseWord`/`FindAndReplaceWord`/
    # `LaunchWord`/`ReadFromWord`/`SaveWord`/`WriteToWord`は実際には兄弟セレクタを持ち、
    # 真のaction_idは`Word.<グループ>.<ActionName>`という3セグメント形式だった
    # (従来のフラットな判定は実際のDSLでは一度もマッチしなかった、知見155のExcelと同種)。
    dsl = (
        "Word.LaunchWord.Launch Instance=> WordInstance\n"
        "Word.WriteToWord.WriteEndOfDocument Instance: WordInstance Text: $'''hello'''\n"
        "Word.ReadFromWord.Read Instance: WordInstance WordData=> WordData\n"
        "Word.FindAndReplaceWord.FindAndReplaceAllWithoutWildcards Instance: WordInstance "
        "TextToFind: $'''a''' TextToReplaceWith: $'''b'''\n"
        "Word.SaveWord.Save Instance: WordInstance\n"
        "Word.CloseWord.Close Instance: WordInstance"
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


def test_generate_python_from_word_full_scope_batch_actually_executes_correctly(tmp_path: Path) -> None:
    # design/dsl_format_findings.md 知見124/129/130の死角(文字列一致だけの`compile()`
    # テストは実際の出力変数の値を一度も検証していない)を、Wordの全スコープバッチ
    # についても塞ぐ。`Word.SaveWord.Save`(パス未指定)は`NewDocument`では実行時に
    # 必ず失敗するため`SaveAs`(同じく知見157で確認済みの兄弟セレクタ)を使い、
    # `FindAndReplaceWord`の効果を観測するため2回目の`ReadFromWord`を追加した。
    dest = tmp_path / "out.docx"
    dsl = (
        "Word.LaunchWord.Launch Instance=> WordInstance\n"
        "Word.WriteToWord.WriteEndOfDocument Instance: WordInstance Text: $'''hello'''\n"
        "Word.ReadFromWord.Read Instance: WordInstance WordData=> WordData\n"
        "Word.FindAndReplaceWord.FindAndReplaceAllWithoutWildcards Instance: WordInstance "
        "TextToFind: $'''hello''' TextToReplaceWith: $'''world'''\n"
        "Word.ReadFromWord.Read Instance: WordInstance WordData=> WordData2\n"
        f"Word.SaveWord.SaveAs Instance: WordInstance DocumentPath: $'''{dest}'''\n"
        "Word.CloseWord.Close Instance: WordInstance"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code

    namespace: dict[str, object] = {}
    exec(code, namespace)

    assert "hello" in namespace["WordData"]
    assert "world" in namespace["WordData2"]
    assert "hello" not in namespace["WordData2"]

    import docx

    reopened = docx.Document(str(dest))
    assert any("world" in p.text for p in reopened.paragraphs)


def test_generate_python_from_word_insert_image_document_start_and_end_converts(tmp_path: Path) -> None:
    # design/dsl_format_findings.md 知見177(decompile確認済み): `InsertImageToWord`の
    # `Source=File`固定の兄弟セレクタのうち`StartOfDocument`/`EndOfDocument`の2件のみ
    # python-docxで再現可能。
    from PIL import Image

    image_path = tmp_path / "pic.png"
    Image.new("RGB", (4, 4), color="blue").save(image_path)
    dest = tmp_path / "out.docx"
    dsl = (
        "Word.LaunchWord.Launch Instance=> WordInstance\n"
        "Word.WriteToWord.WriteEndOfDocument Instance: WordInstance Text: $'''hello'''\n"
        f"Word.InsertImageToWord.InsertImageDocumentEndFromFile Instance: WordInstance Path: $'''{image_path}'''\n"
        f"Word.SaveWord.SaveAs Instance: WordInstance DocumentPath: $'''{dest}'''\n"
        "Word.CloseWord.Close Instance: WordInstance"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        f"word_actions.insert_image_to_word(WordInstance, '{image_path}', "
        "insert_image_mode='EndOfDocument')" in code
    )

    namespace: dict[str, object] = {}
    exec(code, namespace)

    import docx

    reopened = docx.Document(str(dest))
    assert reopened.inline_shapes
    assert reopened.paragraphs[0].text == "hello"


def test_generate_python_keeps_insert_image_bookmark_mode_as_todo() -> None:
    # 知見177: ブックマーク相対(`StartOfBookmark`等)は実機未確認のため安全にTODOへ倒す。
    dsl = (
        "Word.InsertImageToWord.InsertImageBookmarkStartFromFile Instance: WordInstance "
        "Path: $'''C:\\\\pic.png''' Bookmark: $'''MyBookmark'''"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Word.InsertImageToWord.InsertImageBookmarkStartFromFile" in code


def test_generate_python_from_word_read_bookmark_converts() -> None:
    # design/dsl_format_findings.md 知見181(decompile確認済み): `ReadDocumentByBookmark()`
    # はWord COMの`Bookmarks[name].Range.Text`相当——`word_actions._bookmark_range_text()`
    # (lxmlで`<w:bookmarkStart>`/`<w:bookmarkEnd>`を直接検索)で再現した。
    dsl = (
        "Word.LaunchWord.Launch Instance=> WordInstance\n"
        "Word.ReadFromWord.ReadBookmark Instance: WordInstance "
        "Bookmark: $'''MyBookmark''' WordData=> WordData"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert (
        "WordData = word_actions.read_from_word(WordInstance, read_mode='Bookmark', "
        "pages='1', bookmark='MyBookmark')" in code
    )
    assert "# TODO" not in code

    namespace: dict[str, object] = {}
    exec(code, namespace)
    # ブックマーク自体が無い文書なので、decompile確認済みの「未発見=空文字列」を検証する。
    assert namespace["WordData"] == ""


def test_generate_python_from_word_unsupported_modes_fall_back_to_todo() -> None:
    # ページ/ブックマーク系はライブWordのレンダリング/ライブコレクション依存のため
    # スコープ外(知見157のセレクタ監査でHide/ShowAllから確定)——でっち上げたコードを
    # 出力せず安全にTODOへ倒れることを確認する。ワイルドカード系も同様。
    page_mode_dsl = "Word.ReadFromWord.ReadPage Instance: WordInstance WordData=> WordData"
    tree = build_block_tree(parse_dsl(page_mode_dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Word.ReadFromWord.ReadPage" in code

    bookmark_write_dsl = "Word.WriteToWord.WriteStartOfBookmark Instance: WordInstance Text: $'''x'''"
    tree = build_block_tree(parse_dsl(bookmark_write_dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Word.WriteToWord.WriteStartOfBookmark" in code

    wildcard_dsl = (
        "Word.FindAndReplaceWord.FindAndReplaceSingleWildcards Instance: WordInstance "
        "TextToFind: $'''a''' TextToReplaceWith: $'''b'''"
    )
    tree = build_block_tree(parse_dsl(wildcard_dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Word.FindAndReplaceWord.FindAndReplaceSingleWildcards" in code


def test_generate_python_from_powerpoint_full_scope_batch_converts_all_actions() -> None:
    # design/dsl_format_findings.md 知見158: 知見80の「PowerPoint.*のaction_idは実機
    # 確認済み」はアクショングループのAutomationId確認に過ぎず、`AddPowerPointSlide`/
    # `ClosePowerPoint`/`DeletePowerPointSlide`/`LaunchPowerPoint`/`ReadFromPowerPoint`/
    # `SavePowerPoint`/`WriteToPowerPoint`は実際には兄弟セレクタを持ち、真のaction_idは
    # `PowerPoint.<グループ>.<ActionName>`という3セグメント形式だった(知見155-157の
    # Excel/PDF/Wordと同種の潜在バグ)。`MovePowerPointSlide`は兄弟セレクタが無く、
    # 既存のフラットな形式のままで正しい。
    #
    # 警告(知見174): このDSLは`compile()`のみで`exec()`してはいけない——実際に実行すると
    # `DeletePowerPointSlide.DeleteSlideLast`が唯一のスライドを削除した後に
    # `MovePowerPointSlide`が空のプレゼンテーションに対して呼ばれ、
    # `MoveSlideInvalidSourcePositionError`でクラッシュする。実行可能なDSLは
    # `test_generate_python_from_powerpoint_full_scope_batch_actually_executes_correctly`
    # を参照(2枚目のスライドを追加し、Move→Deleteの順に入れ替えてある)。
    dsl = (
        "PowerPoint.LaunchPowerPoint.Launch Instance=> PPTInstance\n"
        "PowerPoint.AddPowerPointSlide.AddSlideAsLast Instance: PPTInstance "
        "SlideIndex=> NewSlideIndex\n"
        "PowerPoint.WriteToPowerPoint.WriteToFirstSlide Instance: PPTInstance Text: $'''hello'''\n"
        "PowerPoint.ReadFromPowerPoint.Read Instance: PPTInstance PowerPointData=> PPTData\n"
        "PowerPoint.DeletePowerPointSlide.DeleteSlideLast Instance: PPTInstance\n"
        "PowerPoint.MovePowerPointSlide SourceInstance: PPTInstance SourceSlidePosition: 1 "
        "DestinationInstance: PPTInstance DestinationSlidePosition: 2\n"
        "PowerPoint.SavePowerPoint.Save Instance: PPTInstance\n"
        "PowerPoint.ClosePowerPoint.Close Instance: PPTInstance"
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


def test_generate_python_from_powerpoint_full_scope_batch_actually_executes_correctly(
    tmp_path: Path,
) -> None:
    # design/dsl_format_findings.md 知見124/129/130の死角を、PowerPointの全スコープ
    # バッチについても塞ぐ。既存の文字列一致版(`...converts_all_actions`)のDSLを
    # そのまま`exec()`すると実際には**クラッシュする**ことが判明した——`DeletePowerPoint
    # Slide.DeleteSlideLast`が唯一のスライドを削除した後に`MovePowerPointSlide`が
    # (空になった)プレゼンテーションに対して呼ばれ、`MoveSlideInvalidSourcePositionError`
    # を投げる。これは文字列一致だけの旧テストが一度も`exec()`していなかったために
    # 気づかれていなかった(まさに知見124/129/130が繰り返し警告していた死角の実例)。
    # ここでは全く同じ各action_idを1回ずつ使うが、2枚目のスライドを追加して
    # (同じ`AddPowerPointSlide.AddSlideAsLast`の2回目呼び出し)`MovePowerPointSlide`
    # 実行時に実際に2枚存在するよう順序を組み直した——テスト対象のaction_id集合は
    # 変えていない。
    dest = tmp_path / "out.pptx"
    dsl = (
        "PowerPoint.LaunchPowerPoint.Launch Instance=> PPTInstance\n"
        "PowerPoint.AddPowerPointSlide.AddSlideAsLast Instance: PPTInstance "
        "SlideIndex=> NewSlideIndex\n"
        "PowerPoint.AddPowerPointSlide.AddSlideAsLast Instance: PPTInstance "
        "SlideIndex=> NewSlideIndex2\n"
        "PowerPoint.WriteToPowerPoint.WriteToFirstSlide Instance: PPTInstance Text: $'''hello'''\n"
        "PowerPoint.ReadFromPowerPoint.Read Instance: PPTInstance PowerPointData=> PPTData\n"
        "PowerPoint.MovePowerPointSlide SourceInstance: PPTInstance SourceSlidePosition: 1 "
        "DestinationInstance: PPTInstance DestinationSlidePosition: 2\n"
        "PowerPoint.DeletePowerPointSlide.DeleteSlideLast Instance: PPTInstance\n"
        f"PowerPoint.SavePowerPoint.SaveAs Instance: PPTInstance DocumentPath: $'''{dest}'''\n"
        "PowerPoint.ClosePowerPoint.Close Instance: PPTInstance"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code

    namespace: dict[str, object] = {}
    exec(code, namespace)

    assert namespace["NewSlideIndex"] == 1
    assert namespace["NewSlideIndex2"] == 2
    assert namespace["PPTData"].strip() == "hello"

    from pptx import Presentation as _ReopenPresentation

    reopened = _ReopenPresentation(str(dest))
    # MovePowerPointSlideが「helloのスライド」を2番目へ移動した後、
    # DeleteSlideLastが2番目(=helloのスライド)を削除するため、残るのは空スライド1枚のみ。
    assert len(reopened.slides) == 1
    remaining_text = "".join(
        shape.text_frame.text for shape in reopened.slides[0].shapes if shape.has_text_frame
    )
    assert "hello" not in remaining_text


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


def test_generate_python_from_replace_item_in_datatable_everywhere_converts() -> None:
    # design/dsl_format_findings.md 知見176(decompile確認済み): `FindOrReplaceInDataTable`の
    # `SearchMode=FindAndReplace`側(知見165/166のaudit toolで未結線のまま発見された4件の
    # うち1件)。`FindItemInDataTableEverywhere`(知見89)と同じ`DataTableMatches`出力契約
    # (`(行,列)`ペアのリスト)で、テーブルを直接mutateしながら置換する。
    dsl = (
        "SET CSV TO $'''A\nhello\nworld'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> T\n"
        "Variables.FindOrReplaceInDataTable.ReplaceItemInDataTableEverywhere "
        "DataTable: T ValueToFind: $'''hello''' TextToReplaceWith: $'''HI''' AllMatches: True "
        "MatchCase: False MatchEntireCellContents: False DataTableMatches=> M"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "M = variables_actions.find_and_replace_in_datatable_everywhere(T, 'hello', 'HI', "
        "all_matches=True, match_case=False, match_entire_cell_contents=False)" in code
    )
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["M"] == [(0, 0)]
    assert namespace["T"] == [{"A": "HI"}, {"A": "world"}]


def test_generate_python_from_replace_item_in_datatable_with_regex_everywhere_converts() -> None:
    # 知見176: `ReplaceItemInDataTableEverywhere`の兄弟セレクタ(`UseRegex: True`固定)。
    dsl = (
        "SET CSV TO $'''A\norder-123\nno digits'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> T\n"
        "Variables.FindOrReplaceInDataTable.ReplaceItemInDataTableWithRegexEverywhere "
        "DataTable: T ValueToFind: $'''[0-9]+''' TextToReplaceWith: $'''N''' AllMatches: True "
        "DataTableMatches=> M"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "M = variables_actions.find_and_replace_in_datatable_everywhere(T, '[0-9]+', 'N', "
        "all_matches=True, use_regex=True)" in code
    )
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["M"] == [(0, 0)]
    assert namespace["T"] == [{"A": "order-N"}, {"A": "no digits"}]


def test_generate_python_from_replace_item_in_datatable_by_column_index_converts() -> None:
    # 知見176の追記: 兄弟セレクタ`ReplaceItemInDataTableByColumnIndex`(列名でも指定できる)。
    dsl = (
        "SET CSV TO $'''A,B\nx,x\ny,x'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> T\n"
        "Variables.FindOrReplaceInDataTable.ReplaceItemInDataTableByColumnIndex "
        "DataTable: T ValueToFind: $'''x''' TextToReplaceWith: $'''z''' AllMatches: True "
        "MatchCase: False MatchEntireCellContents: False ColumnNameOrIndex: $'''B''' DataTableMatches=> M"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "M = variables_actions.find_and_replace_in_datatable_everywhere(T, 'x', 'z', "
        "all_matches=True, match_case=False, match_entire_cell_contents=False, column='B')" in code
    )
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["M"] == [(0, 1), (1, 1)]
    assert namespace["T"] == [{"A": "x", "B": "z"}, {"A": "y", "B": "z"}]


def test_generate_python_from_replace_item_in_datatable_with_regex_by_column_index_converts() -> None:
    # 知見176の追記: 上記2つの組み合わせ(`UseRegex: True`固定+列名/列インデックス両対応)。
    dsl = (
        "SET CSV TO $'''A,B\norder-1,x\norder-2,y'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: CSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> T\n"
        "Variables.FindOrReplaceInDataTable.ReplaceItemInDataTableWithRegexByColumnIndex "
        "DataTable: T ValueToFind: $'''[0-9]+''' TextToReplaceWith: $'''N''' AllMatches: True "
        "ColumnNameOrIndex: $'''A''' DataTableMatches=> M"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "M = variables_actions.find_and_replace_in_datatable_everywhere(T, '[0-9]+', 'N', "
        "all_matches=True, use_regex=True, column='A')" in code
    )
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["M"] == [(0, 0), (1, 0)]
    assert namespace["T"] == [{"A": "order-N", "B": "x"}, {"A": "order-N", "B": "y"}]


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


def test_generate_python_from_filter_list_end_to_end_via_csv_seeded_parameters() -> None:
    # design/dsl_format_findings.md 知見164-165(`[Action]`属性の網羅列挙監査で新規発見、
    # decompile確認済み): `FilterList`は`FilterDataTable`と同じ`FilterParameters`
    # スキーマ(`OPERATOR`/`VALUE`/`RULE`、`COLUMN`列は無し)を使う兄弟アクション——
    # `Variables.Actions.dll`には`ActionSelectorBase`の兄弟セレクタが無いフラットな
    # アクションのため、知見139以降の監査手法では見落としていた。
    dsl = (
        "SET ParamsCSV TO $'''OPERATOR,VALUE,RULE\nContains,ob,And'''\n"
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: ParamsCSV TrimFields: True "
        "FirstLineContainsColumnNames: True ReadFieldsAsText: True "
        "ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> FP\n"
        "Variables.FilterList ListToFilter: Items FilterParameters: FP IgnoreCase: False "
        "FilteredList=> Filtered"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {"Items": ["Alice", "Bob", "Carol"]}
    exec(code, namespace)
    assert namespace["Filtered"] == ["Bob"]


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

        # design/common_rpa_framework_roadmap.md 層7(b)の拡張・既知の落とし穴:
        # 上のアサーションは真の分岐(ファイルが無い)しか見ておらず、仮にIF文の
        # ゲートが壊れて本体が無条件に実行されるようになっても(例えばテストの
        # DSL文字列がインデント無しの「フラット」な書き方で、本体が構文的にIFの
        # 外側へ漏れてしまう場合——PAD自身のクリップボードDSLは本体を必ず
        # インデントするため本物のキャプチャでは発生しないが、手書きのDSL文字列では
        # 容易に踏める)、同じ結果(`X == 1`)になるため検出できない。偽の分岐
        # (ファイルが実在する)でも`SET X TO 1`が実行されないことを`eval()`で
        # 直接検証し、ゲート自体が機能していることを確認する。
        existing_path = Path(tmp) / "exists.txt"
        existing_path.write_text("x", encoding="utf-8")
        dsl2 = f"IF (File.IfFile.DoesNotExist File: $'''{existing_path}''') THEN\nSET X TO 1\nEND"
        tree2 = build_block_tree(parse_dsl(dsl2))
        code2 = generate_python(tree2)
        if_line = next(line for line in code2.splitlines() if line.startswith("if "))
        condition_source = if_line.removeprefix("if ").removesuffix(":")
        namespace2: dict[str, object] = {}
        exec(code2, namespace2)
        assert eval(condition_source, namespace2) is False


def test_generate_python_from_if_file_exists_evaluates_correctly() -> None:
    # design/common_rpa_framework_roadmap.md 層7(b)の拡張: `File.IfFile.Exists`は
    # `codegen_coverage.py`の自動フィクスチャ走査では常に[OK]扱いだったが(Tier1バッチ
    # フィクスチャ経由、`tests/test_pad_codegen_tier1_actions.py`はcompile()のみで
    # exec()を一度も呼ばない設計)、条件式が実際に正しい真偽値を返すかのexec検証は
    # 一度も無かった。実在のファイル/存在しないファイルの両方で検証する。
    with tempfile.TemporaryDirectory() as tmp:
        existing_path = Path(tmp) / "exists.txt"
        existing_path.write_text("x", encoding="utf-8")
        missing_path = Path(tmp) / "missing.txt"
        for path, expected in ((existing_path, True), (missing_path, False)):
            dsl = f"IF (File.IfFile.Exists File: $'''{path}''') THEN\nSET X TO 1\nEND"
            tree = build_block_tree(parse_dsl(dsl))
            code = generate_python(tree)
            compile(code, "<generated>", "exec")
            assert "# TODO" not in code
            if_line = next(line for line in code.splitlines() if line.startswith("if "))
            condition_source = if_line.removeprefix("if ").removesuffix(":")
            namespace: dict[str, object] = {}
            exec(code, namespace)
            assert eval(condition_source, namespace) is expected


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

        # design/common_rpa_framework_roadmap.md 層7(b): 真の分岐だけでは本体がIFの
        # ゲートを通って実行されたのか無条件に漏れただけなのか区別できない(上の
        # `test_generate_python_from_if_file_does_not_exist_converts`と同じ理由)ため、
        # 偽の分岐(フォルダが実在する)でも本体が実行されないことをeval()で確認する。
        existing_dir = Path(tmp) / "existing_dir"
        existing_dir.mkdir()
        dsl2 = f"IF (Folder.IfFolderExists.DoesNotExist Path: $'''{existing_dir}''') THEN\nSET X TO 1\nEND"
        tree2 = build_block_tree(parse_dsl(dsl2))
        code2 = generate_python(tree2)
        if_line = next(line for line in code2.splitlines() if line.startswith("if "))
        condition_source = if_line.removeprefix("if ").removesuffix(":")
        namespace2: dict[str, object] = {}
        exec(code2, namespace2)
        assert eval(condition_source, namespace2) is False


def test_generate_python_from_if_folder_exists_evaluates_correctly() -> None:
    # design/common_rpa_framework_roadmap.md 層7(b)の拡張:
    # `test_generate_python_from_if_file_exists_evaluates_correctly`と対になるテスト。
    with tempfile.TemporaryDirectory() as tmp:
        existing_dir = Path(tmp) / "existing_dir"
        existing_dir.mkdir()
        missing_dir = Path(tmp) / "missing_dir2"
        for path, expected in ((existing_dir, True), (missing_dir, False)):
            dsl = f"IF (Folder.IfFolderExists.Exists Path: $'''{path}''') THEN\nSET X TO 1\nEND"
            tree = build_block_tree(parse_dsl(dsl))
            code = generate_python(tree)
            compile(code, "<generated>", "exec")
            assert "# TODO" not in code
            if_line = next(line for line in code.splitlines() if line.startswith("if "))
            condition_source = if_line.removeprefix("if ").removesuffix(":")
            namespace: dict[str, object] = {}
            exec(code, namespace)
            assert eval(condition_source, namespace) is expected


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


def test_generate_python_from_rename_files_add_date_or_time_converts() -> None:
    # design/dsl_format_findings.md 知見154(decompileソース直読み): `RenameAddDateOrTime`
    # (`DateTimeToAdd=LastModified`、`RenameFilesAction.GetNewFileNameResolver()`の
    # `AddDateTime`分岐)。`DateTimeFormat`は.NET書式文字列、`DateTimeSeparator`は
    # 文字へ変換される(`_support.RENAME_SEPARATOR_TO_CHAR`)。
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "report.txt"
        src.write_text("x", encoding="utf-8")
        import os as _os
        import time as _time

        mtime = _time.mktime((2026, 11, 6, 9, 0, 0, 0, 0, -1))
        _os.utime(src, (mtime, mtime))
        dsl = (
            f"File.RenameFiles.RenameAddDateOrTime Files: $'''{src}''' "
            "DateTimeToAdd: File.DateTimeToAdd.LastModified "
            "DateTimePosition: File.AddTextPosition.AfterName "
            "DateTimeSeparator: File.Separator.Underscore "
            "DateTimeFormat: $'''yyyyMMdd''' "
            "IfFileExists: File.IfExists.DoNothing RenamedFiles=> R"
        )
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        namespace: dict[str, object] = {}
        exec(code, namespace)
        renamed = Path(tmp) / "report_20261106.txt"
        assert namespace["R"] == [str(renamed)]
        assert renamed.is_file()


def test_generate_python_from_rename_files_add_custom_date_time_converts() -> None:
    # 知見154: `RenameAddCustomDateTime`(`UseCustomDateTime=True`固定)。`CustomDateTime`は
    # 実行時に解決される変数参照(`VarRef`)としてそのまま渡る。
    from datetime import datetime

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "report.txt"
        src.write_text("x", encoding="utf-8")
        dsl = (
            f"File.RenameFiles.RenameAddCustomDateTime Files: $'''{src}''' "
            "CustomDateTime: D "
            "DateTimePosition: File.AddTextPosition.BeforeName "
            "DateTimeSeparator: File.Separator.Dash "
            "DateTimeFormat: $'''yyyy-MM-dd''' "
            "IfFileExists: File.IfExists.DoNothing RenamedFiles=> R"
        )
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        namespace: dict[str, object] = {"D": datetime(2025, 3, 4)}
        exec(code, namespace)
        renamed = Path(tmp) / "2025-03-04-report.txt"
        assert namespace["R"] == [str(renamed)]
        assert renamed.is_file()


def test_generate_python_from_rename_add_sequential_suffix_converts() -> None:
    # 知見154: `RenameAddSequentialSuffix`(`SequenceUseExistingName=True`固定)——
    # バッチ内の複数ファイルで`SequentialNumberer`の状態が共有されることまで検証する。
    with tempfile.TemporaryDirectory() as tmp:
        src1 = Path(tmp) / "a.txt"
        src2 = Path(tmp) / "b.txt"
        src1.write_text("x", encoding="utf-8")
        src2.write_text("x", encoding="utf-8")
        dsl = (
            "File.RenameFiles.RenameAddSequentialSuffix Files: FileList "
            "SequencePosition: File.AddTextPosition.AfterName "
            "SequenceSeparator: File.Separator.Underscore "
            "StartNumberingAt: 1 IncrementBy: 1 UsePadding: True Padding: 2 "
            "IfFileExists: File.IfExists.DoNothing RenamedFiles=> R"
        )
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        namespace: dict[str, object] = {"FileList": [str(src1), str(src2)]}
        exec(code, namespace)
        renamed1 = Path(tmp) / "a_01.txt"
        renamed2 = Path(tmp) / "b_02.txt"
        assert namespace["R"] == [str(renamed1), str(renamed2)]
        assert renamed1.is_file()
        assert renamed2.is_file()


def test_generate_python_from_overwrite_with_sequential_suffix_converts() -> None:
    # 知見154: `OverwriteWithSequentialSuffix`(`SequenceUseExistingName=False`固定)——
    # 既存のファイル名ではなく`SequenceNewName`を使う。
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "a.txt"
        src.write_text("x", encoding="utf-8")
        dsl = (
            f"File.RenameFiles.OverwriteWithSequentialSuffix Files: $'''{src}''' "
            "SequenceNewName: $'''report''' "
            "SequencePosition: File.AddTextPosition.BeforeName "
            "SequenceSeparator: File.Separator.Nothing "
            "StartNumberingAt: 5 IncrementBy: 1 UsePadding: False Padding: 0 "
            "IfFileExists: File.IfExists.DoNothing RenamedFiles=> R"
        )
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        namespace: dict[str, object] = {}
        exec(code, namespace)
        renamed = Path(tmp) / "5report.txt"
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


def test_generate_python_from_database_connect_oracle_converts() -> None:
    # design/dsl_format_findings.md 知見139: `ActionSelectorBase`一括列挙監査を
    # Database.Actions.dllに適用して発見した`OpenConnection`クラスの兄弟セレクタ
    # (`OpenConnectionOracleSelector`)。`pyodbc`等のネイティブドライバ無しでは
    # 実際の接続自体は検証できないため(知見でっち上げ防止の対象外・既存の
    # `database_actions.open_connection()`自体は別途単体テスト済み)、ここでは
    # 生成コードの文字列と構文的妥当性のみ検証する。
    dsl = "Database.Connect.ConnectOracle ConnectionString: $'''DRIVER=Oracle;...''' Connection=> SQLConnection"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert "SQLConnection = database_actions.open_connection('DRIVER=Oracle;...', database_type='Oracle')" in code


def test_generate_python_from_database_connect_and_execute_converts() -> None:
    # design/dsl_format_findings.md 知見139: `ExecuteSqlStatement`クラスの兄弟セレクタ
    # (`ConnectAndExecuteSelector`)——接続文字列から直接実行する一括モード。
    # `pad_action_lib.database_actions.connect_and_execute()`は既に実装・単体テスト済み
    # (`tests/test_pad_action_lib_database.py`)だったが、codegen側は未結線だった。
    dsl = (
        "Database.ExecuteSqlStatement.ConnectAndExecute ConnectionString: $'''DRIVER=SQLite;''' "
        "Statement: $'''SELECT 1''' Timeout: 30 Result=> QueryResult"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "QueryResult = database_actions.connect_and_execute('DRIVER=SQLite;', 'SELECT 1', "
        "database_type='Other', timeout=30)[1]" in code
    )

    # 実際にexec()し、connect_and_executeへ正しい引数が渡ることまで検証する
    # (fake connect=を直接注入できないため、戻り値のタプルを自前で用意した
    # database_actionsのスタブに差し替える)。
    import dump_daemon.pad_action_lib.database_actions as database_actions

    calls = []

    def fake_connect_and_execute(connection_string, statement, database_type="Other", timeout=30, **kwargs):
        calls.append((connection_string, statement, database_type, timeout))
        return ("fake-connection", "fake-result")

    original = database_actions.connect_and_execute
    database_actions.connect_and_execute = fake_connect_and_execute
    try:
        namespace: dict[str, object] = {}
        exec(code, namespace)
    finally:
        database_actions.connect_and_execute = original
    assert calls == [("DRIVER=SQLite;", "SELECT 1", "Other", 30)]
    assert namespace["QueryResult"] == "fake-result"


def test_generate_python_from_database_connect_and_execute_oracle_converts() -> None:
    # design/dsl_format_findings.md 知見139: Oracle専用の兄弟セレクタ。選択した時点で
    # database_typeが"Oracle"に固定される(OpenConnectionOracleSelectorと同じ前例)。
    dsl = (
        "Database.ExecuteSqlStatement.ConnectAndExecuteOracle ConnectionString: $'''DRIVER=Oracle;''' "
        "Statement: $'''SELECT 1 FROM DUAL''' Timeout: 30 Result=> QueryResult"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "QueryResult = database_actions.connect_and_execute('DRIVER=Oracle;', 'SELECT 1 FROM DUAL', "
        "database_type='Oracle', timeout=30)[1]" in code
    )


@pytest.mark.parametrize(
    ("mode", "xml_value", "expected"),
    [
        ("Numeric", "42", 42),
        ("Boolean", "true", True),
        ("DateTime", "2026-01-02", datetime(2026, 1, 2)),
    ],
)
def test_generate_python_from_get_xml_element_value_as_typed_converts(mode: str, xml_value: str, expected: object) -> None:
    # design/dsl_format_findings.md 知見139: `ActionSelectorBase`一括列挙監査を
    # XML.Actions.dllに適用して発見した`GetElementValue`の兄弟セレクタ
    # (`GetElementValueAsNumeric`/`AsBoolean`/`AsDateTime`)。`value_type`はセレクタ
    # 自体が固定するため、既存の`xml_actions.get_xml_element_value()`の`value_type`
    # 引数(実装済み)をそのまま使って結線できた。
    from decimal import Decimal

    dsl = (
        f"SET Doc TO $'''<r><v>{xml_value}</v></r>'''\n"
        f"XML.GetXmlElementValue.GetElementValueAs{mode} Document: Doc XPathQuery: $'''/r/v''' "
        "ElementValue=> N"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert f"value_type={mode!r}" in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    if mode == "Numeric":
        assert namespace["N"] == Decimal(expected)
    else:
        assert namespace["N"] == expected


@pytest.mark.parametrize(
    ("mode", "output_name", "xml_value", "expected"),
    [
        ("Numeric", "NumericValue", "42", 42),
        ("Boolean", "BooleanValue", "true", True),
        ("DateTime", "DateTimeValue", "2026-01-02", datetime(2026, 1, 2)),
    ],
)
def test_generate_python_from_get_xml_element_attribute_as_typed_converts(
    mode: str, output_name: str, xml_value: str, expected: object
) -> None:
    # design/dsl_format_findings.md 知見139・149: `ActionSelectorBase`一括列挙監査を
    # XML.Actions.dllに適用して発見した`GetElementAttribute`の兄弟セレクタ
    # (`GetElementAttributeAsNumeric`/`AsBoolean`/`AsDateTime`)。VM上で
    # `GetXmlElementAttribute`クラスが`TextValue`/`NumericValue`/`DateTimeValue`/
    # `BooleanValue`というモードごとに別々の出力プロパティを持つと確認し、
    # `get_xml_element_attribute()`に`value_type`引数を新規追加して対応した。
    from decimal import Decimal

    dsl = (
        f"SET Doc TO $'''<r v=\"{xml_value}\"/>'''\n"
        f"XML.GetXmlElementAttribute.GetElementAttributeAs{mode} Document: Doc XPathQuery: $'''/r''' "
        f"AttributeName: $'''v''' {output_name}=> N"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert f"value_type={mode!r}" in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    if mode == "Numeric":
        assert namespace["N"] == Decimal(expected)
    else:
        assert namespace["N"] == expected


def test_generate_python_from_execute_xpath_and_get_first_value_only_converts() -> None:
    # design/dsl_format_findings.md 知見139: `ExecuteXPath`の兄弟セレクタ。
    dsl = (
        "SET Doc TO $'''<r><v>a</v><v>b</v></r>'''\n"
        "XML.ExecuteXPathQuery.ExecuteXPathAndGetFirstValueOnly XmlDocument: Doc "
        "XPathQuery: $'''//v/text()''' XPathResult=> R"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert "first_value_only=True" in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["R"] == "a"


def test_generate_python_from_cmd_read_and_split_converts() -> None:
    # design/dsl_format_findings.md 知見139: `ActionSelectorBase`一括列挙監査を
    # Cmd.Actions.dllに適用して発見した`Read`の兄弟セレクタ(`ReadAndSplit`)。
    # `CmdSession`はLinux上では`cmd.exe`を起動できないため、実在のセッション変数
    # (`Session`パラメータは単なる`VarRef`)に対して`.read()`を呼ぶ形に注入した
    # フェイクオブジェクトで検証する。
    dsl = "Cmd.ReadFromCmdSession.ReadAndSplit Session: MySession CmdOutput=> Out CmdError=> Err"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert "Out, Err = MySession.read(split_output_and_error=True)" in code

    class FakeCmdSession:
        def read(self, split_output_and_error: bool = False):
            assert split_output_and_error is True
            return "stdout text", "stderr text"

    namespace: dict[str, object] = {"MySession": FakeCmdSession()}
    exec(code, namespace)
    assert namespace["Out"] == "stdout text"
    assert namespace["Err"] == "stderr text"


def test_generate_python_from_cmd_open_with_code_page_converts() -> None:
    # design/dsl_format_findings.md 知見153(decompile+リフレクション確認済み):
    # `OpenCmdSession`の兄弟セレクタ`OpenWithCodePage`。`Encoding`は列挙名(例: `utf_8`)
    # がそのまま`cmd_actions.open_cmd_session()`の`encoding`引数へ渡り、実際の
    # コードページ変換(`_ENCODING_CODEPAGES`)はそちら側の責務になる。
    import dump_daemon.pad_action_lib.cmd_actions as cmd_actions

    dsl = (
        "Cmd.Open.OpenWithCodePage Directory: $'''C:\\\\work''' "
        "Encoding: Cmd.Encoding.shift_jis CmdSession=> S"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert "change_code_page=True" in code
    assert "encoding='shift_jis'" in code

    calls = []

    def fake_open_cmd_session(directory, **kwargs):
        calls.append((directory, kwargs))
        return "fake-session"

    original = cmd_actions.open_cmd_session
    cmd_actions.open_cmd_session = fake_open_cmd_session
    try:
        namespace: dict[str, object] = {}
        exec(code, namespace)
    finally:
        cmd_actions.open_cmd_session = original
    assert namespace["S"] == "fake-session"
    assert len(calls) == 1
    directory, kwargs = calls[0]
    assert directory == "C:\\work"
    assert kwargs == {"change_code_page": True, "encoding": "shift_jis"}


def test_generate_python_from_write_xml_to_file_without_formatting_converts() -> None:
    # design/dsl_format_findings.md 知見139: `WriteToFileFormatted`の兄弟セレクタ
    # (`Indentation`パラメータ自体がDSL上に無い)。
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "out.xml"
        dsl = (
            f"XML.WriteXmlToFile.WriteToFile File: $'''{out_path}''' "
            "Xml: $'''<r><v>1</v></r>''' Encoding: XML.XMLEncoding.DefaultEncoding"
        )
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        assert "format_xml=False" in code
        exec(code, {})
        assert out_path.read_text(encoding="utf-8") == "<r><v>1</v></r>"


@pytest.mark.parametrize(
    ("action", "params", "expected"),
    [
        ("GetText", "", "hello"),
        ("GetSubtextFromStartTo", " NumberOfChars: 3", "hel"),
        ("GetSubtextFrom", " CharacterPosition: 2", "llo"),
    ],
)
def test_generate_python_from_get_subtext_siblings_converts(action: str, params: str, expected: str) -> None:
    # design/dsl_format_findings.md 知見139・142: `ActionSelectorBase`一括列挙監査を
    # Text.Actions.dllに適用して発見した`GetSubtext`の兄弟セレクタ3件
    # (`GetText`/`GetSubtextFromStartTo`/`GetSubtextFrom`)。既存の`get_subtext()`の
    # `start_index`/`length`引数の組み合わせがそのまま対応できた。
    dsl = f"Text.GetSubtext.{action} Text: $'''hello'''{params} Subtext=> S"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["S"] == expected


def test_generate_python_from_crop_text_after_flag_converts() -> None:
    dsl = "Text.CropText.CropTextAfterFlag Text: $'''a-b-c''' ToFlag: $'''-''' IgnoreCase: False CroppedText=> C IsFlagFound=> F"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["C"] == "b-c"
    assert namespace["F"] is True


def test_generate_python_from_crop_text_between_flags_converts() -> None:
    dsl = (
        "Text.CropText.CropTextBetweenFlags Text: $'''a[b]c''' FromFlag: $'''[''' ToFlag: $''']''' "
        "IgnoreCase: False CroppedText=> C IsFlagFound=> F"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["C"] == "b"
    assert namespace["F"] is True


def test_generate_python_from_join_text_with_delimiter_converts() -> None:
    dsl = (
        "SET L TO List\n"
        "Text.JoinText.JoinWithDelimiter List: L StandardDelimiter: Text.StandardDelimiter.Space "
        "DelimiterTimes: 1 Result=> R"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {"List": ["a", "b", "c"]}
    exec(code, namespace)
    assert namespace["R"] == "a b c"


def test_generate_python_from_join_text_with_custom_delimiter_converts() -> None:
    dsl = "Text.JoinText.JoinWithCustomDelimiter List: L CustomDelimiter: $''', ''' DelimiterTimes: 1 Result=> R"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {"L": ["a", "b", "c"]}
    exec(code, namespace)
    assert namespace["R"] == "a, b, c"


def test_generate_python_from_split_text_with_delimiter_converts() -> None:
    dsl = "Text.SplitText.SplitWithDelimiter Text: $'''a,b,c''' CustomDelimiter: $''',''' DelimiterTimes: 1 Result=> R"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["R"] == ["a", "b", "c"]


def test_generate_python_from_split_at_number_of_characters_converts() -> None:
    dsl = "Text.SplitText.SplitAtNumberOfCharacters Text: $'''abcdef''' SplitInterval: 2 Result=> R"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["R"] == ["ab", "cd", "ef"]


def test_generate_python_from_parse_text_all_matches_converts() -> None:
    dsl = (
        "Text.ParseText.Parse Text: $'''aXbXc''' TextToFind: $'''X''' StartingPosition: 0 "
        "IgnoreCase: False Matches=> M OccurrencePositions=> P"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["M"] == ["X", "X"]
    assert namespace["P"] == [1, 3]


def test_generate_python_from_regex_parse_all_matches_converts() -> None:
    dsl = (
        "Text.ParseText.RegexParse Text: $'''a1b2''' TextToFind: $'''[0-9]''' StartingPosition: 0 "
        "IgnoreCase: False Matches=> M OccurrencePositions=> P"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["M"] == ["1", "2"]
    assert namespace["P"] == [1, 3]


def test_generate_python_from_regex_parse_for_first_occurrence_converts() -> None:
    dsl = (
        "Text.ParseText.RegexParseForFirstOccurrence Text: $'''a1b2''' TextToFind: $'''[0-9]''' "
        "StartingPosition: 0 IgnoreCase: False Match=> M OccurrencePosition=> P"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["M"] == "1"
    assert namespace["P"] == 1


def test_generate_python_from_replace_text_with_regex_converts() -> None:
    dsl = (
        "Text.Replace.ReplaceTextWithRegex Text: $'''a1b2''' TextToFind: $'''[0-9]''' ReplaceWith: $'''#''' "
        "IgnoreCase: False ActivateEscapeSequences: False Result=> R"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["R"] == "a#b#"


@pytest.mark.parametrize(
    ("use_salt", "use_iv"),
    [(True, False), (False, True), (True, True)],
)
def test_generate_python_from_cryptography_encrypt_decrypt_text_with_salt_iv_round_trips(
    use_salt: bool, use_iv: bool
) -> None:
    # design/dsl_format_findings.md 知見139・143: `ActionSelectorBase`一括列挙監査を
    # Cryptography.Actions.dllに適用して発見した、`EncryptTextWithAES`/
    # `DecryptTextWithAES`のUseSalt/UseIV兄弟セレクタ。暗号化側はSalt/
    # InitializationVectorを生成結果として出力し(`EncryptResult.salt`/
    # `.initialization_vector`)、復号側はそれを入力として受け取る——という非対称性
    # (知見143)を、実際にEncrypt→Decryptの往復をexec()して検証する。
    action_suffix = ("UseSalt" if use_salt else "") + ("UseIV" if use_iv else "")
    if use_salt and use_iv:
        action_suffix = "UseSaltAndIV"
    encrypt_outputs = "EncryptedText=> Enc"
    if use_salt:
        encrypt_outputs += " Salt=> SaltVal"
    if use_iv:
        encrypt_outputs += " InitializationVector=> IVVal"
    decrypt_inputs = ""
    if use_salt:
        decrypt_inputs += " Salt: SaltVal"
    if use_iv:
        decrypt_inputs += " InitializationVector: IVVal"
    dsl = (
        "SET Key TO $'''mysecret'''\n"
        f"Cryptography.EncryptText.EncryptTextWithAES{action_suffix} "
        "Encoding: Cryptography.EncryptionEncoding.Unicode "
        "TextToEncrypt: $'''hello world''' EncryptionKey: Key "
        f"PaddingMode: Cryptography.PaddingMode.PKCS7 KeySize: Cryptography.AESKeySize.Bits256 "
        f"{encrypt_outputs}\n"
        f"Cryptography.DecryptText.DecryptTextWithAES{action_suffix} "
        "Encoding: Cryptography.EncryptionEncoding.Unicode "
        f"TextToDecrypt: Enc DecryptionKey: Key{decrypt_inputs} "
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
    if use_salt:
        assert namespace["SaltVal"]
    if use_iv:
        assert namespace["IVVal"]


@pytest.mark.parametrize(
    ("action_suffix", "method", "use_auth"),
    [
        ("UseAuth", "Get", True),
        ("UsePost", "Post", False),
        ("UsePostAndAuth", "Post", True),
    ],
)
def test_generate_python_from_download_to_variable_siblings_converts(
    action_suffix: str, method: str, use_auth: bool
) -> None:
    # design/dsl_format_findings.md 知見139・144: `ActionSelectorBase`一括列挙監査を
    # Web.Actions.dllに適用して発見した、`Download`(`DownloadFromWeb`クラス)の兄弟
    # セレクタ。既存の`download_from_web()`の`method`/`use_credentials`引数が
    # そのまま対応できた。実ネットワークを使わず、`web_actions.download_from_web`
    # 自体をフェイクに差し替えて呼び出し引数を検証する。
    import dump_daemon.pad_action_lib.web_actions as web_actions

    auth_dsl = " UseCredentials: True UserName: $'''u''' Password: $'''p'''" if use_auth else ""
    dsl = (
        f"Web.DownloadFromWeb.Download{action_suffix} Url: $'''http://example.test/''' "
        "ConnectionTimeout: 30 FollowRedirection: True UserAgent: $'''UA''' "
        f"Encoding: Web.Encoding.AutoDetect AcceptUntrustedCertificates: False{auth_dsl} "
        "WebPageText=> T"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code

    calls = []

    def fake_download_from_web(url, *args, **kwargs):
        calls.append((url, kwargs))
        return "fake response"

    original = web_actions.download_from_web
    web_actions.download_from_web = fake_download_from_web
    try:
        namespace: dict[str, object] = {}
        exec(code, namespace)
    finally:
        web_actions.download_from_web = original
    assert namespace["T"] == "fake response"
    assert len(calls) == 1
    _, kwargs = calls[0]
    if method == "Post":
        assert kwargs.get("method") == "Post"
    else:
        assert "method" not in kwargs
    if use_auth:
        assert kwargs["use_credentials"] is True
        assert kwargs["username"] == "u"
        assert kwargs["password"] == "p"


@pytest.mark.parametrize("action_suffix", ["", "UseAuth", "UsePost", "UsePostAndAuth"])
def test_generate_python_from_download_to_file_siblings_converts(action_suffix: str) -> None:
    # 知見144: `DownloadToFile`(`SaveResponse=ToFile`)系。実際にexec()し、
    # `DownloadedFile`出力が保存先パスそのものになることまで検証する(知見144で
    # 修正した`download_from_web()`の潜在バグの回帰防止)。
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "out.bin"
        auth_dsl = " UseCredentials: True UserName: $'''u''' Password: $'''p'''" if "Auth" in action_suffix else ""
        dsl = (
            f"Web.DownloadFromWeb.DownloadToFile{action_suffix} Url: $'''http://example.test/''' "
            "ConnectionTimeout: 30 FollowRedirection: True UserAgent: $'''UA''' "
            f"Encoding: Web.Encoding.AutoDetect AcceptUntrustedCertificates: False{auth_dsl} "
            f"FilePath: $'''{dest}''' DownloadedFile=> F"
        )
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code

        import dump_daemon.pad_action_lib.web_actions as web_actions

        calls = []

        def fake_download_from_web(url, *args, **kwargs):
            calls.append((url, kwargs))
            Path(kwargs["destination_path"]).write_bytes(b"data")
            return kwargs["destination_path"]

        original = web_actions.download_from_web
        web_actions.download_from_web = fake_download_from_web
        try:
            namespace: dict[str, object] = {}
            exec(code, namespace)
        finally:
            web_actions.download_from_web = original
        assert namespace["F"] == str(dest)
        assert len(calls) == 1


@pytest.mark.parametrize("action_suffix", ["", "UseAuth", "UsePost", "UsePostAndAuth"])
def test_generate_python_from_download_to_folder_siblings_converts(action_suffix: str) -> None:
    # design/dsl_format_findings.md 知見152(decompileソース直読み): `DownloadToFolder`系
    # (`FileName=KeepOriginal`)。`destination_folder`引数で`web_actions.download_from_web`
    # へ結線する——ファイル名自動決定自体は`_get_download_file_path()`側の単体テストで
    # 別途検証済みのため、ここでは`destination_folder`kwargが正しく渡ることを検証する。
    with tempfile.TemporaryDirectory() as tmp:
        auth_dsl = " UseCredentials: True UserName: $'''u''' Password: $'''p'''" if "Auth" in action_suffix else ""
        dsl = (
            f"Web.DownloadFromWeb.DownloadToFolder{action_suffix} Url: $'''http://example.test/''' "
            "ConnectionTimeout: 30 FollowRedirection: True UserAgent: $'''UA''' "
            f"Encoding: Web.Encoding.AutoDetect AcceptUntrustedCertificates: False{auth_dsl} "
            f"DestinationFolder: $'''{tmp}''' DownloadedFile=> F"
        )
        tree = build_block_tree(parse_dsl(dsl))
        code = generate_python(tree)
        compile(code, "<generated>", "exec")
        assert "# TODO" not in code
        assert "destination_folder=" in code

        import dump_daemon.pad_action_lib.web_actions as web_actions

        calls = []

        def fake_download_from_web(url, *args, **kwargs):
            calls.append((url, kwargs))
            return str(Path(kwargs["destination_folder"]) / "derived.bin")

        original = web_actions.download_from_web
        web_actions.download_from_web = fake_download_from_web
        try:
            namespace: dict[str, object] = {}
            exec(code, namespace)
        finally:
            web_actions.download_from_web = original
        assert namespace["F"] == str(Path(tmp) / "derived.bin")
        assert len(calls) == 1
        assert calls[0][1]["destination_folder"] == tmp


@pytest.mark.parametrize(
    ("action_suffix", "expected_method", "use_auth"),
    [
        ("SaveToFolder", "Get", False),
        ("UseAuthSaveToFolder", "Get", True),
        ("SaveToFolderPost", "Post", False),
        ("SaveToFolderPut", "Put", False),
        ("UseAuthSaveToFolderPost", "Post", True),
        ("UseAuthSaveToFolderPut", "Put", True),
    ],
)
def test_generate_python_from_invoke_web_service_save_to_folder_siblings_converts(
    action_suffix: str, expected_method: str, use_auth: bool
) -> None:
    # design/dsl_format_findings.md 知見152: `.Arguments`監査で`SaveToFolder`接尾辞
    # セレクタ(及び`UseAuth`/`Post`/`Put`版、計6通り)は`DestinationFolder`/
    # `DownloadedFile`を持つと確定した。`invoke_web_service()`の`destination_folder`
    # 引数(`DownloadToFolder`と同じ`_get_download_file_path()`)で対応する。
    import dump_daemon.pad_action_lib.web_actions as web_actions

    auth_dsl = " Username: $'''u''' Password: $'''p'''" if use_auth else ""
    has_dynamic_method = action_suffix in ("SaveToFolder", "UseAuthSaveToFolder")
    method_dsl = " Method: Web.Method.Get" if has_dynamic_method else ""
    dsl = (
        f"Web.InvokeWebService.InvokeWebService{action_suffix} Url: $'''http://example.test/'''{method_dsl} "
        "Accept: $'''application/xml''' ContentType: $'''application/xml''' "
        "CustomHeaders: $'''''' RequestBody: $'''''' ConnectionTimeout: 30 FollowRedirection: True "
        "FailOnErrorStatus: False EncodeRequestBody: False UserAgent: $'''UA''' "
        f"Encoding: Web.Encoding.AutoDetect AcceptUntrustedCertificates: False TrimRequestBody: True{auth_dsl} "
        "DestinationFolder: $'''C:\\\\out''' DownloadedFile=> F"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert f"method={expected_method!r}" in code
    assert "destination_folder=" in code

    calls = []

    def fake_invoke_web_service(url, *args, **kwargs):
        calls.append((url, kwargs))
        return web_actions.InvokeWebServiceResult(response="", downloaded_file="C:\\out\\derived.bin")

    original = web_actions.invoke_web_service
    web_actions.invoke_web_service = fake_invoke_web_service
    try:
        namespace: dict[str, object] = {}
        exec(code, namespace)
    finally:
        web_actions.invoke_web_service = original
    assert namespace["F"] == "C:\\out\\derived.bin"
    assert len(calls) == 1
    _, kwargs = calls[0]
    assert kwargs["destination_folder"] == "C:\\out"
    if use_auth:
        assert kwargs["use_credentials"] is True


@pytest.mark.parametrize(
    ("action_suffix", "expected_method", "use_auth", "save_suffix"),
    [
        ("PostUpload", "Post", False, None),
        ("UseAuthPostUpload", "Post", True, None),
        ("SaveToFilePostUpload", "Post", False, "File"),
        ("SaveToFolderPostUpload", "Post", False, "Folder"),
        ("UseAuthSaveToFilePostUpload", "Post", True, "File"),
        ("UseAuthSaveToFolderPostUpload", "Post", True, "Folder"),
        ("PutUpload", "Put", False, None),
        ("UseAuthPutUpload", "Put", True, None),
        ("SaveToFilePutUpload", "Put", False, "File"),
        ("SaveToFolderPutUpload", "Put", False, "Folder"),
        ("UseAuthSaveToFilePutUpload", "Put", True, "File"),
        ("UseAuthSaveToFolderPutUpload", "Put", True, "Folder"),
    ],
)
def test_generate_python_from_invoke_web_service_upload_siblings_converts(
    action_suffix: str, expected_method: str, use_auth: bool, save_suffix: str | None
) -> None:
    # design/dsl_format_findings.md 知見152(decompileソース直読み): `Upload`接尾辞
    # セレクタ(計12通り)は`UploadAttachments=True`固定で`RequestBody`/`ContentType`
    # が無く`Attachments`/`UploadType`を使う。`invoke_web_service()`の
    # `upload_attachments`/`attachments`/`upload_type`引数(`WebActions.
    # FormulateWebRequest()`のmultipart/form-data構築を再現)で対応する。
    import dump_daemon.pad_action_lib.web_actions as web_actions

    auth_dsl = " Username: $'''u''' Password: $'''p'''" if use_auth else ""
    if save_suffix == "File":
        output_dsl = "FilePath: $'''C:\\\\out.bin''' DownloadedFile=> F"
    elif save_suffix == "Folder":
        output_dsl = "DestinationFolder: $'''C:\\\\out''' DownloadedFile=> F"
    else:
        output_dsl = "Response=> R"
    dsl = (
        f"Web.InvokeWebService.InvokeWebService{action_suffix} Url: $'''http://example.test/''' "
        "Accept: $'''application/xml''' CustomHeaders: $'''''' ConnectionTimeout: 30 "
        "FollowRedirection: True FailOnErrorStatus: False EncodeRequestBody: False UserAgent: $'''UA''' "
        f"Encoding: Web.Encoding.AutoDetect AcceptUntrustedCertificates: False TrimRequestBody: True{auth_dsl} "
        "Attachments: Attach UploadType: Web.UploadType.FilePath "
        f"{output_dsl}"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert f"method={expected_method!r}" in code
    assert "upload_attachments=True" in code
    assert "attachments=Attach" in code
    assert "upload_type='FilePath'" in code

    calls = []

    def fake_invoke_web_service(url, *args, **kwargs):
        calls.append((url, kwargs))
        if save_suffix:
            return web_actions.InvokeWebServiceResult(response="", downloaded_file="C:\\out\\uploaded.txt")
        return web_actions.InvokeWebServiceResult(response="upload ok")

    original = web_actions.invoke_web_service
    web_actions.invoke_web_service = fake_invoke_web_service
    try:
        namespace: dict[str, object] = {"Attach": [{"NAME": "f1", "ATTACHMENT": "C:\\in.bin"}]}
        exec(code, namespace)
    finally:
        web_actions.invoke_web_service = original
    assert len(calls) == 1
    _, kwargs = calls[0]
    assert kwargs["upload_attachments"] is True
    assert kwargs["attachments"] == [{"NAME": "f1", "ATTACHMENT": "C:\\in.bin"}]
    assert kwargs["upload_type"] == "FilePath"
    if save_suffix:
        assert namespace["F"] == "C:\\out\\uploaded.txt"
    else:
        assert namespace["R"] == "upload ok"


def test_generate_python_from_invoke_soap_service_use_auth_converts() -> None:
    # design/dsl_format_findings.md 知見139・145: `ActionSelectorBase`一括列挙監査を
    # Web.Actions.dllに適用して発見した`InvokeSoapService`の兄弟セレクタ
    # (`InvokeSoapServiceUseAuth`)。既存の`invoke_soap_service()`に
    # `use_credentials`/`username`/`password`を新規追加して対応した(内部で委譲する
    # `invoke_web_service()`は元から対応済み)。
    import dump_daemon.pad_action_lib.web_actions as web_actions

    dsl = (
        "Web.InvokeSoapService.InvokeSoapServiceUseAuth Endpoint: $'''http://example.test/''' "
        "CustomHeaders: $'''''' RequestBody: $'''<a/>''' ConnectionTimeout: 30 FollowRedirection: True "
        "FailOnErrorStatus: False UserAgent: $'''UA''' Encoding: Web.Encoding.AutoDetect "
        "AcceptUntrustedCertificates: False TrimRequestBody: True Username: $'''u''' Password: $'''p''' "
        "Response=> R"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code

    calls = []

    def fake_invoke_web_service(url, *args, **kwargs):
        calls.append((url, kwargs))
        return web_actions.InvokeWebServiceResult(response="soap response")

    original = web_actions.invoke_web_service
    web_actions.invoke_web_service = fake_invoke_web_service
    try:
        namespace: dict[str, object] = {}
        exec(code, namespace)
    finally:
        web_actions.invoke_web_service = original
    assert namespace["R"] == "soap response"
    assert len(calls) == 1
    _, kwargs = calls[0]
    assert kwargs["use_credentials"] is True
    assert kwargs["username"] == "u"
    assert kwargs["password"] == "p"


def test_generate_python_from_invoke_web_service_use_auth_converts() -> None:
    # design/dsl_format_findings.md 知見139・147: `ActionSelectorBase`一括列挙監査を
    # Web.InvokeWebService系29セレクタに適用して発見した`InvokeWebServiceUseAuth`。
    # 既存の`invoke_web_service()`の`use_credentials`/`username`/`password`引数が
    # そのまま対応できた(`Method`は既存の基本セレクタと同じく動的に読む)。
    import dump_daemon.pad_action_lib.web_actions as web_actions

    dsl = (
        "Web.InvokeWebService.InvokeWebServiceUseAuth Url: $'''http://example.test/''' "
        "Method: Web.Method.Get Accept: $'''application/xml''' ContentType: $'''application/xml''' "
        "CustomHeaders: $'''''' RequestBody: $'''''' ConnectionTimeout: 30 FollowRedirection: True "
        "FailOnErrorStatus: False EncodeRequestBody: False UserAgent: $'''UA''' "
        "Encoding: Web.Encoding.AutoDetect AcceptUntrustedCertificates: False TrimRequestBody: True "
        "Username: $'''u''' Password: $'''p''' Response=> R"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code

    calls = []

    def fake_invoke_web_service(url, *args, **kwargs):
        calls.append((url, kwargs))
        return web_actions.InvokeWebServiceResult(response="auth response")

    original = web_actions.invoke_web_service
    web_actions.invoke_web_service = fake_invoke_web_service
    try:
        namespace: dict[str, object] = {}
        exec(code, namespace)
    finally:
        web_actions.invoke_web_service = original
    assert namespace["R"] == "auth response"
    assert len(calls) == 1
    _, kwargs = calls[0]
    assert kwargs["use_credentials"] is True
    assert kwargs["username"] == "u"
    assert kwargs["password"] == "p"


@pytest.mark.parametrize(
    ("action_suffix", "expected_method", "use_auth"),
    [
        ("Post", "Post", False),
        ("Put", "Put", False),
        ("UseAuthPost", "Post", True),
        ("UseAuthPut", "Put", True),
    ],
)
def test_generate_python_from_invoke_web_service_post_put_siblings_converts(
    action_suffix: str, expected_method: str, use_auth: bool
) -> None:
    # design/dsl_format_findings.md 知見150: 各セレクタクラスの`.Arguments`プロパティ
    # (そのセレクタでDSLに実際に現れるパラメータ名の一覧)を確認した結果、
    # `InvokeWebServicePost`/`Put`(及び`UseAuth`版)は`Method`がArgumentsに含まれず
    # セレクタ自体で固定されると確定した——`.Arguments`がプロパティ存在チェックより
    # 信頼できる根拠だと判明(知見147の未確定事項を解消)。
    import dump_daemon.pad_action_lib.web_actions as web_actions

    auth_dsl = " Username: $'''u''' Password: $'''p'''" if use_auth else ""
    dsl = (
        f"Web.InvokeWebService.InvokeWebService{action_suffix} Url: $'''http://example.test/''' "
        "Accept: $'''application/xml''' ContentType: $'''application/xml''' "
        "CustomHeaders: $'''''' RequestBody: $'''''' ConnectionTimeout: 30 FollowRedirection: True "
        "FailOnErrorStatus: False EncodeRequestBody: False UserAgent: $'''UA''' "
        f"Encoding: Web.Encoding.AutoDetect AcceptUntrustedCertificates: False TrimRequestBody: True{auth_dsl} "
        "Response=> R"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert f"method={expected_method!r}" in code

    calls = []

    def fake_invoke_web_service(url, *args, **kwargs):
        calls.append((url, kwargs))
        return web_actions.InvokeWebServiceResult(response="resp")

    original = web_actions.invoke_web_service
    web_actions.invoke_web_service = fake_invoke_web_service
    try:
        namespace: dict[str, object] = {}
        exec(code, namespace)
    finally:
        web_actions.invoke_web_service = original
    assert namespace["R"] == "resp"
    assert len(calls) == 1
    if use_auth:
        assert calls[0][1]["use_credentials"] is True


@pytest.mark.parametrize(
    ("action_suffix", "expected_method", "use_auth"),
    [
        ("SaveToFile", "Get", False),
        ("UseAuthSaveToFile", "Get", True),
        ("SaveToFilePost", "Post", False),
        ("SaveToFilePut", "Put", False),
        ("UseAuthSaveToFilePost", "Post", True),
        ("UseAuthSaveToFilePut", "Put", True),
    ],
)
def test_generate_python_from_invoke_web_service_save_to_file_siblings_converts(
    action_suffix: str, expected_method: str, use_auth: bool
) -> None:
    # design/dsl_format_findings.md 知見150・151: `.Arguments`監査で`SaveToFile`接尾辞
    # セレクタ(及び`UseAuth`/`Post`/`Put`版、計6通り)は`FilePath`/`DownloadedFile`を
    # 持ち`Response`を持たないと確定した。`invoke_web_service()`に新規追加した
    # `save_response`/`destination_path`引数(知見144の`download_from_web()`と同じ
    # パターン)で対応する。
    import dump_daemon.pad_action_lib.web_actions as web_actions

    auth_dsl = " Username: $'''u''' Password: $'''p'''" if use_auth else ""
    # base/UseAuth(Get)版のみMethodが動的パラメータとして現れる。
    has_dynamic_method = action_suffix in ("SaveToFile", "UseAuthSaveToFile")
    method_dsl = " Method: Web.Method.Get" if has_dynamic_method else ""
    dsl = (
        f"Web.InvokeWebService.InvokeWebService{action_suffix} Url: $'''http://example.test/'''{method_dsl} "
        "Accept: $'''application/xml''' ContentType: $'''application/xml''' "
        "CustomHeaders: $'''''' RequestBody: $'''''' ConnectionTimeout: 30 FollowRedirection: True "
        "FailOnErrorStatus: False EncodeRequestBody: False UserAgent: $'''UA''' "
        f"Encoding: Web.Encoding.AutoDetect AcceptUntrustedCertificates: False TrimRequestBody: True{auth_dsl} "
        "FilePath: $'''C:\\\\out.bin''' DownloadedFile=> F"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert f"method={expected_method!r}" in code
    assert "save_response='ToFile'" in code

    calls = []

    def fake_invoke_web_service(url, *args, **kwargs):
        calls.append((url, kwargs))
        return web_actions.InvokeWebServiceResult(response="", downloaded_file="C:\\out.bin")

    original = web_actions.invoke_web_service
    web_actions.invoke_web_service = fake_invoke_web_service
    try:
        namespace: dict[str, object] = {}
        exec(code, namespace)
    finally:
        web_actions.invoke_web_service = original
    assert namespace["F"] == "C:\\out.bin"
    assert len(calls) == 1
    _, kwargs = calls[0]
    assert kwargs["save_response"] == "ToFile"
    assert kwargs["destination_path"] == "C:\\out.bin"
    if use_auth:
        assert kwargs["use_credentials"] is True


def test_generate_python_from_datetime_text_custom_format_round_trips() -> None:
    # design/dsl_format_findings.md 知見139・148: `ActionSelectorBase`一括列挙監査を
    # Text.Actions.dllに適用して発見した`ConvertTextToDateTime.ToDateTimeCustomFormat`/
    # `ConvertDateTimeToText.FromCustomDateTime`。既存の`text_to_datetime()`/
    # `datetime_to_text()`の`custom_format`引数(`dotnet_format_to_strftime()`経由、
    # 実装済み)がそのまま対応できた。実際にText→DateTime→Textの往復をexec()して
    # 検証する。
    dsl = (
        "SET D TO $'''2026-11-05'''\n"
        "Text.ConvertTextToDateTime.ToDateTimeCustomFormat Text: D CustomFormat: $'''yyyy-MM-dd''' DateTime=> Dt\n"
        "Text.ConvertDateTimeToText.FromCustomDateTime DateTime: Dt CustomFormat: $'''yyyy/MM/dd''' Result=> S"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    namespace: dict[str, object] = {}
    exec(code, namespace)
    assert namespace["S"] == "2026/11/05"


def test_generate_python_from_display_show_message_dialog_converts() -> None:
    # design/dsl_format_findings.md 知見184/185: 本プロジェクト最初の実機キャプチャ
    # (知見1、design/g1_g2_verification_result.md)でありながら一度も結線されていな
    # かった`Display.ShowMessageDialog.ShowMessage`を新規結線。実際にダイアログを
    # 表示せず検証するため`ctypes.windll`を偽装注入する。
    import ctypes

    dsl = (
        "Display.ShowMessageDialog.ShowMessage Title: $'''Greeting''' "
        "Message: $'''Hello''' Icon: Display.Icon.Question "
        "Buttons: Display.Buttons.YesNo DefaultButton: Display.DefaultButton.Button1 "
        "IsTopMost: False ButtonPressed=> ButtonPressed"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "ButtonPressed = display_actions.show_message_dialog('Hello', 'Greeting', "
        "icon='Question', buttons='YesNo', default_button='Button1', is_topmost=False)" in code
    )

    class _FakeUser32:
        def MessageBoxW(self, hwnd: int, message: str, title: str, flags: int) -> int:
            assert message == "Hello"
            assert title == "Greeting"
            return 6  # Yes

    class _FakeWindll:
        user32 = _FakeUser32()

    import pytest as _pytest

    monkeypatch = _pytest.MonkeyPatch()
    monkeypatch.setattr(ctypes, "windll", _FakeWindll(), raising=False)
    try:
        namespace: dict[str, object] = {}
        exec(code, namespace)
        assert namespace["ButtonPressed"] == "Yes"
    finally:
        monkeypatch.undo()


def test_generate_python_keeps_show_message_with_timeout_as_todo() -> None:
    # 知見185: タイムアウト時の挙動が標準Win32 APIで正確に再現できないため安全にTODOへ倒す。
    dsl = (
        "Display.ShowMessageDialog.ShowMessageWithTimeout Title: $'''T''' Message: $'''M''' "
        "Timeout: 3 ButtonPressed=> ButtonPressed"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Display.ShowMessageDialog.ShowMessageWithTimeout" in code


def test_generate_python_from_display_select_folder_converts() -> None:
    # design/dsl_format_findings.md 知見185追補: 兄弟セレクタの無いフラットなaction
    # `Display.SelectFolder`(`[Action(Name = "SelectFolder")]`、知見162/179で確認済みの
    # 「Id属性が無ければNameがEffectiveId」というSDK一般ルールをそのまま適用)。
    # 実際にダイアログを表示せず検証するため`tkinter`を偽装注入する。
    import sys
    import types

    dsl = (
        "Display.SelectFolder Description: $'''Pick one''' InitialDirectory: $'''C:\\\\''' "
        "IsTopMost: False SelectedFolder=> SelectedFolder ButtonPressed=> ButtonPressed"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert (
        "SelectedFolder, ButtonPressed = display_actions.show_select_folder_dialog("
        "'Pick one', 'C:\\\\', is_topmost=False)" in code
    )

    fake_tkinter = types.ModuleType("tkinter")

    class _FakeTk:
        def withdraw(self) -> None:
            pass

        def destroy(self) -> None:
            pass

    fake_tkinter.Tk = _FakeTk  # type: ignore[attr-defined]
    fake_filedialog = types.ModuleType("tkinter.filedialog")

    def _askdirectory(**kwargs: object) -> str:
        assert kwargs == {"title": "Pick one", "initialdir": "C:\\"}
        return "C:\\chosen"

    fake_filedialog.askdirectory = _askdirectory  # type: ignore[attr-defined]
    fake_tkinter.filedialog = fake_filedialog  # type: ignore[attr-defined]

    import pytest as _pytest

    monkeypatch = _pytest.MonkeyPatch()
    monkeypatch.setitem(sys.modules, "tkinter", fake_tkinter)
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", fake_filedialog)
    try:
        namespace: dict[str, object] = {}
        exec(code, namespace)
        assert namespace["SelectedFolder"] == "C:\\chosen"
        assert namespace["ButtonPressed"] == "OK"
    finally:
        monkeypatch.undo()


@pytest.mark.parametrize(
    "action_id,expected_func",
    [
        ("Services.Start", "start_service"),
        ("Services.Stop", "stop_service"),
        ("Services.Pause", "pause_service"),
        ("Services.Resume", "resume_service"),
    ],
)
def test_generate_python_from_services_start_stop_pause_resume_converts(
    action_id: str, expected_func: str
) -> None:
    # design/dsl_format_findings.md 知見187: Services.Actions.dllをdecompileし発見した
    # 新規4アクション(フラットなaction、兄弟セレクタ無し)。実際にサービス操作を行わず
    # 検証するため`win32serviceutil`を偽装注入する。
    import sys
    import types

    dsl = f"{action_id} ServiceName: $'''Spooler'''"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO" not in code
    assert f"services_actions.{expected_func}('Spooler')" in code

    calls = []
    fake_win32serviceutil = types.ModuleType("win32serviceutil")
    fake_win32serviceutil.StartService = lambda name: calls.append(name)  # type: ignore[attr-defined]
    fake_win32serviceutil.StopService = lambda name: calls.append(name)  # type: ignore[attr-defined]
    fake_win32serviceutil.ControlService = lambda name, code_: calls.append(name)  # type: ignore[attr-defined]
    fake_win32service = types.ModuleType("win32service")
    fake_win32service.SERVICE_CONTROL_PAUSE = 2  # type: ignore[attr-defined]
    fake_win32service.SERVICE_CONTROL_CONTINUE = 3  # type: ignore[attr-defined]

    import pytest as _pytest

    monkeypatch = _pytest.MonkeyPatch()
    monkeypatch.setitem(sys.modules, "win32serviceutil", fake_win32serviceutil)
    monkeypatch.setitem(sys.modules, "win32service", fake_win32service)
    try:
        namespace: dict[str, object] = {}
        exec(code, namespace)
        assert calls == ["Spooler"]
    finally:
        monkeypatch.undo()


def test_generate_python_keeps_services_action_unknown_as_todo() -> None:
    dsl = "Services.SomeUnknownAction ServiceName: $'''Spooler'''"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD action: Services.SomeUnknownAction" in code


@pytest.mark.parametrize(
    "action_id,expected_code",
    [
        ("Services.IfService.IsRunning", 4),
        ("Services.IfService.IsStopped", 1),
        ("Services.IfService.IsPaused", 7),
    ],
)
def test_generate_python_renders_if_service_status_checks(action_id: str, expected_code: int) -> None:
    # design/dsl_format_findings.md 知見188: IfService列挙値自体がWin32標準のSERVICE_STATE
    # 定数そのものと確定(decompile確認済み)——これまでTODOへ落ちていたのを修正。
    dsl = f"""IF ({action_id} Service: $'''Spooler''') THEN
    SET X TO 1
END"""
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO" not in code
    assert f"if services_actions.get_service_status('Spooler') == {expected_code}:" in code


@pytest.mark.parametrize(
    "action_id,negated",
    [
        ("Services.IfService.IsInstalled", False),
        ("Services.IfService.IsNotInstalled", True),
    ],
)
def test_generate_python_renders_if_service_installed_checks(action_id: str, negated: bool) -> None:
    dsl = f"""IF ({action_id} Service: $'''Print Spooler''') THEN
    SET X TO 1
END"""
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO" not in code
    call = "services_actions.is_service_installed('Print Spooler')"
    expected = f"if not {call}:" if negated else f"if {call}:"
    assert expected in code


@pytest.mark.parametrize(
    "action_id,expected_code",
    [
        ("Services.WaitForService.Started", 4),
        ("Services.WaitForService.Stopped", 1),
        ("Services.WaitForService.Paused", 7),
    ],
)
def test_generate_python_renders_wait_for_service_as_polling_loop(action_id: str, expected_code: int) -> None:
    dsl = f"WAIT ({action_id} Service: $'''Spooler''')"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO" not in code
    assert f"while services_actions.get_service_status('Spooler') != {expected_code}:" in code
    assert "time.sleep(0.05)" in code


@pytest.mark.parametrize(
    ("mode", "expected_condition"),
    [
        ("ToOpenByInstanceOrHandle", "not AutomationWindow2.exists()"),
        ("ToCloseByInstanceOrHandle", "AutomationWindow2.exists()"),
        (
            "ToBecomeFocusedByInstanceOrHandle",
            "not (AutomationWindow2.exists() and AutomationWindow2.wrapper_object().is_active())",
        ),
        (
            "ToLoseFocusByInstanceOrHandle",
            "(AutomationWindow2.exists() and AutomationWindow2.wrapper_object().is_active())",
        ),
    ],
)
def test_generate_python_converts_wait_for_window_by_instance_or_handle_modes(
    mode: str, expected_condition: str
) -> None:
    # design/dsl_format_findings.md 知見190・191: `conditions.py`の`IfWindow`側は
    # `ByInstanceOrHandle`/`ByTitleClass`に既に対応済みだったが、`wait.py`側の
    # `WaitForWindow`は`Control`ベースの素のセレクタしか持たない未結線のギャップだった。
    dsl = f"WAIT (UIAutomation.WaitForWindow.{mode} WindowInstance: AutomationWindow2)"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO" not in code
    assert f"while {expected_condition}:" in code
    assert "time.sleep(0.05)" in code


@pytest.mark.parametrize(
    ("mode", "expected_condition"),
    [
        ("ToOpenByTitleClass", "not Desktop(backend='uia').window(title='Notepad').exists()"),
        ("ToCloseByTitleClass", "Desktop(backend='uia').window(title='Notepad').exists()"),
    ],
)
def test_generate_python_converts_wait_for_window_by_title_class_modes(mode: str, expected_condition: str) -> None:
    dsl = f"WAIT (UIAutomation.WaitForWindow.{mode} Title: $'''Notepad''' Class: $'''''')"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO" not in code
    assert f"while {expected_condition}:" in code


def test_generate_python_wait_for_window_by_instance_or_handle_stops_immediately_when_already_satisfied() -> None:
    # ウィンドウが既に開いている状態からスタートすれば、生成した`while`ループは
    # 一度も反復せずに抜ける(無限ループにならないことを実際に実行して確認する)。
    from fake_pywinauto import FakeControl, FakeRegistry

    dsl = "WAIT (UIAutomation.WaitForWindow.ToOpenByInstanceOrHandle WindowInstance: AutomationWindow2)"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")

    registry = FakeRegistry()
    criteria = {"title": "Untitled - Notepad"}
    registry.register_window(**criteria)
    fake_window = FakeControl(registry, criteria)
    namespace: dict[str, object] = {"AutomationWindow2": fake_window}
    exec(code, namespace)


def test_generate_python_wait_for_window_by_title_class_with_class_set_falls_back_to_todo() -> None:
    dsl = "WAIT (UIAutomation.WaitForWindow.ToOpenByTitleClass Title: $'''Notepad''' Class: $'''Notepad''')"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "# TODO: map PAD wait action: UIAutomation.WaitForWindow.ToOpenByTitleClass" in code
