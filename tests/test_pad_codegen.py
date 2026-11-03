"""pad_codegen の単体テスト・結合テスト。

結合テストのフィクスチャは design/dsl_format_findings.md 知見14で実機から
キャプチャした、SET/IF+ELSE IF+ELSE(ネスト込み)/LOOP系3種/EXIT・NEXT LOOPを
網羅するg1g2_testフローの生データ。
"""
from __future__ import annotations

import pytest

from dump_daemon.pad_codegen import (
    generate_python,
    render_condition,
    render_text_template,
    render_value,
)
from dump_daemon.pad_dsl_parser import EnumRef, VarRef, build_block_tree, parse_dsl

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
    assert "for LoopIndex in range(1, (3) + 1, 1):" in code


def test_generate_python_inlines_run_python_script_body() -> None:
    tree = build_block_tree(parse_dsl(FULL_FLOW_DSL))
    code = generate_python(tree)
    assert "import urllib.request, json" in code
    assert 'req = urllib.request.Request("http://127.0.0.1:8765/capture"' in code


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


def test_generate_python_renders_comment_record_as_python_comment() -> None:
    # CommentRecord追加後、codegenがクラッシュせず正しくPythonコメントへ変換すること
    # (design/robin_language_source_findings.mdで構文を確認、未対応のままだと
    # _generate_node()がTypeErrorを送出していたはずの回帰確認)。
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
