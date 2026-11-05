"""pad_codegen の単体テスト・結合テスト。

結合テストのフィクスチャは design/dsl_format_findings.md 知見14で実機から
キャプチャした、SET/IF+ELSE IF+ELSE(ネスト込み)/LOOP系3種/EXIT・NEXT LOOPを
網羅するg1g2_testフローの生データ。
"""
from __future__ import annotations

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
    assert render_condition(VarRef("TestVar"), "=", "hello") == "TestVar == 'hello'"
    assert render_condition(VarRef("X"), "<>", 1) == "X != 1"
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
    tree = build_block_tree(parse_dsl(FULL_FLOW_DSL))
    code = generate_python(tree)
    assert "if TestVar == 'hello':" in code
    assert "    if InnerVar == 'nested':" in code
    assert "elif TestVar == 'world':" in code
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


def test_generate_python_maps_move_window_to_pywinauto_move_window() -> None:
    tree = build_block_tree(parse_dsl(MOVE_WINDOW_DSL))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "from pywinauto import Desktop" in code
    assert (
        "Desktop(backend='uia').window(title='Power Automate | g1g2_test').move_window(x=100, y=50)" in code
    )


def test_generate_python_maps_resize_window_to_pywinauto_move_window() -> None:
    tree = build_block_tree(parse_dsl(RESIZE_WINDOW_DSL))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert (
        "Desktop(backend='uia').window(title='Power Automate | g1g2_test')"
        ".move_window(width=1024, height=768)" in code
    )


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


def test_generate_python_maps_close_window_to_pywinauto_close() -> None:
    # 他のByTitleClass系アクションと同じパターンだと確認できている(action_id自体は実機未確認)。
    dsl = "UIAutomation.CloseWindow.CloseByTitleClass Title: $'''Notepad''' Class: $'''''' "
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "Desktop(backend='uia').window(title='Notepad').close()" in code


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
    assert "if TestVar == 'a':" in code
    assert "elif TestVar == 'b':" in code
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


def test_generate_python_renders_compound_set_variable_expression_as_todo() -> None:
    # design/dsl_format_findings.md 知見53: `SET ... TO`の右辺が複合式(AND/OR/XOR/NOT・算術式)
    # になるケース(知見49の続き)。演算子の優先順位やmod/XORの境界値での意味論差異が
    # PADとPythonで一致する保証がまだ無いため、でっち上げた変換式を出力せず、変数には
    # 安全な`None`を代入した上でTODOコメントに実際のPAD式テキストを残す。
    dsl = "SET NewVar3 TO 1 = 1 AND 2 = 2 OR NOT 3 = 4"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert (
        "# TODO: map PAD compound expression for variable 'NewVar3': "
        "1 = 1 AND 2 = 2 OR NOT 3 = 4" in code
    )
    assert "NewVar3 = None" in code


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


def test_generate_python_adds_verified_pywinauto_selector_hint_when_repository_given() -> None:
    # design/dsl_format_findings.md 知見56(実機検証済み): 知見46でAttributesの中身
    # (Window: Name/Process、子コントロール: Class)を確認した後も、その情報から実際に
    # pywinautoセレクタを組み立てて実機の要素を特定できるかはこれまで未検証のまま、
    # pad_codegen.pyはTODOコメントに表示名パスを出すだけに留めていた。
    # 実際にDesktop(backend="uia").window(title="Untitled - Notepad").child_window(
    # class_name="Edit")を実機(GCP Windows VM)で実行し、メモ帳の実ウィンドウ・実テキスト
    # 編集領域を正しく一意に特定できることを確認した。これを踏まえ、`generate_python()`に
    # 任意の`repository`引数(`parse_control_repository()`の戻り値)を追加し、
    # 渡された場合はTODOコメントに検証済みのpywinautoセレクタ式を提案として付記する
    # ようにした——あくまでコメント内の提案であり、生成される実行コード自体を変えることは
    # 無い(でっち上げたセレクタで動くコードを出力することは無い、という方針は維持)。
    # `GetWindow.GetUseTimeout`は「window instance」の表現方法が未解決のため、今も
    # TODO+ヒントのまま残っている(Click.Click/WaitActionは既に実コード化済みなので
    # このテストの対象には使えない)。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_get_window.txt").read_text(
        encoding="utf-8"
    )
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    compile(code, "<generated>", "exec")
    assert (
        'verified pywinauto selector: Desktop(backend="uia").window(title=\'Untitled - '
        "Notepad')" in code
    )


def test_generate_python_omits_selector_hint_when_repository_not_given() -> None:
    # design/dsl_format_findings.md 知見56: `repository`省略時は完全に従来通りの挙動
    # (ヒント無し)で、後方互換性を保つ。
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_content.txt"
    ).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    code = generate_python(tree)
    assert "verified pywinauto selector" not in code


def test_generate_python_omits_selector_hint_for_special_pseudo_selector() -> None:
    # design/dsl_format_findings.md 知見56: 知見44の「Start Button」のような特殊な
    # 擬似セレクタ(`CustomValue: ":startbutton"`、`Attributes: []`)は、使える属性が
    # 1つも無いため、でっち上げたセレクタを提案せずヒント無しにフォールバックする。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_control_repository.txt").read_text(
        encoding="utf-8"
    )
    tree = build_block_tree(parse_dsl(text))
    repository = parse_control_repository(text)
    code = generate_python(tree, repository=repository)
    assert "verified pywinauto selector" not in code
    assert "Start Button" in code


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


def test_generate_python_from_real_close_window_by_instance_handle_capture_compiles() -> None:
    # design/dsl_format_findings.md 知見57の追記: CloseByInstanceOrHandleも未対応アクション
    # として安全なTODOフォールバックに倒れ、架空のclose()呼び出しをでっち上げないことを確認する。
    text = (FIXTURES_DIR / "closewindow_by_instance.txt").read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO: map PAD action: UIAutomation.CloseWindow.CloseByInstanceOrHandle" in code


def test_generate_python_from_get_window_foreground_mode_with_two_output_vars_compiles() -> None:
    # design/dsl_format_findings.md 知見57の追記: 2つの`=>`出力変数束縛を持つ
    # GetForegroundWindowも、未対応アクションとして安全なTODOフォールバックに倒れ、
    # 架空の変数代入をでっち上げないことを確認する。
    dsl = "UIAutomation.GetWindow.GetForegroundWindow WindowTitle=> WindowTitle2 WindowInstance=> AutomationWindow2"
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    assert "# TODO: map PAD action: UIAutomation.GetWindow.GetForegroundWindow" in code


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
