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
