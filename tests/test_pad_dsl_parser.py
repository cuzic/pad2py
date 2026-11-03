"""pad_dsl_parser の単体テスト。

フィクスチャは design/dsl_format_findings.md に記録した、g1g2_testフローを
実機PADから「コピー&ペースト」で実際にエクスポートした生データそのもの。
"""
from __future__ import annotations

from dump_daemon.pad_dsl_parser import (
    ActionRecord,
    BlockNode,
    ConditionalNode,
    ElseIfRecord,
    IfRecord,
    KeywordRecord,
    LoopForeachRecord,
    LoopRecord,
    LoopWhileRecord,
    SetVariableRecord,
    build_block_tree,
    parse_dsl,
)

REAL_FLOW_DSL = (
    'Display.ShowMessageDialog.ShowMessage Icon: Display.Icon.None '
    'Buttons: Display.Buttons.OK DefaultButton: Display.DefaultButton.Button1 '
    'IsTopMost: False ButtonPressed=> ButtonPressed\n'
    'SET TestVar TO $\'\'\'He said \\"hello\\" and used \\\\ in C:\\\\temp\\\\file.txt\'\'\'\n'
    "Scripting.RunPythonScript.RunPythonScriptCPython PythonCode: $'''import urllib.request, json\n"
    'req = urllib.request.Request(\\"http://127.0.0.1:8765/capture\\", '
    'data=json.dumps({\\"action_id\\": \\"action1\\", \\"flow_name\\": \\"g1g2_test\\"}).encode(), '
    'headers={\\"Content-Type\\": \\"application/json\\"}, method=\\"POST\\")\n'
    "urllib.request.urlopen(req, timeout=2)\n"
    "''' PythonPath: $'''C:\\\\Program Files\\\\Python312\\\\python.exe''' "
    'ScriptOutput=> PythonScriptOutput\n'
    "WAIT 1\n"
    "Scripting.RunPythonScript.RunPythonScriptCPython PythonCode: $'''import urllib.request, json\n"
    'req = urllib.request.Request(\\"http://127.0.0.1:8765/capture\\", '
    'data=json.dumps({\\"action_id\\": \\"action2\\", \\"flow_name\\": \\"g1g2_test\\"}).encode(), '
    'headers={\\"Content-Type\\": \\"application/json\\"}, method=\\"POST\\")\n'
    "urllib.request.urlopen(req, timeout=2)\n"
    "''' PythonPath: $'''C:\\\\Program Files\\\\Python312\\\\python.exe''' "
    "ScriptOutput=> PythonScriptOutput2"
)


def test_parses_five_records_in_order() -> None:
    records = parse_dsl(REAL_FLOW_DSL)
    assert len(records) == 5
    assert isinstance(records[0], ActionRecord)
    assert isinstance(records[1], SetVariableRecord)
    assert isinstance(records[2], ActionRecord)
    assert isinstance(records[3], KeywordRecord)
    assert isinstance(records[4], ActionRecord)


def test_display_message_action_parsed_correctly() -> None:
    records = parse_dsl(REAL_FLOW_DSL)
    msg = records[0]
    assert isinstance(msg, ActionRecord)
    assert msg.action_id == "Display.ShowMessageDialog.ShowMessage"
    assert msg.params["Icon"] == "Display.Icon.None"
    assert msg.params["Buttons"] == "Display.Buttons.OK"
    assert msg.params["DefaultButton"] == "Display.DefaultButton.Button1"
    assert msg.params["IsTopMost"] is False
    assert msg.output_var == "ButtonPressed"


def test_set_variable_parsed_with_unescaped_string_value() -> None:
    records = parse_dsl(REAL_FLOW_DSL)
    set_var = records[1]
    assert isinstance(set_var, SetVariableRecord)
    assert set_var.var_name == "TestVar"
    assert set_var.value == 'He said "hello" and used \\ in C:\\temp\\file.txt'


def test_run_python_script_string_literal_unescaped() -> None:
    records = parse_dsl(REAL_FLOW_DSL)
    action1 = records[2]
    assert isinstance(action1, ActionRecord)
    assert action1.action_id == "Scripting.RunPythonScript.RunPythonScriptCPython"
    code = action1.params["PythonCode"]
    # 元のDSL中では \" だったものが、パース後は実際のダブルクォートに戻っていること
    assert '"http://127.0.0.1:8765/capture"' in code
    assert '"action_id": "action1"' in code
    assert "\\" not in code.replace("\\n", "")  # バックスラッシュ自体は残っていない想定
    assert action1.output_var == "PythonScriptOutput"
    # パスの \\ -> \ アンエスケープも確認
    assert action1.params["PythonPath"] == r"C:\Program Files\Python312\python.exe"


def test_second_python_script_uses_action2_and_distinct_output_var() -> None:
    records = parse_dsl(REAL_FLOW_DSL)
    action2 = records[4]
    assert isinstance(action2, ActionRecord)
    assert '"action_id": "action2"' in action2.params["PythonCode"]
    assert action2.output_var == "PythonScriptOutput2"


def test_wait_keyword_parsed_as_bare_keyword() -> None:
    records = parse_dsl(REAL_FLOW_DSL)
    wait = records[3]
    assert isinstance(wait, KeywordRecord)
    assert wait.name == "WAIT"
    assert wait.args == ["1"]


# g1g2_testフローに「If」アクション(第1オペランド %TestVar%、演算子 Equal to (=)、
# 第2オペランド "hello")を追加して実機から再キャプチャした生データ。
IF_END_DSL = "IF TestVar = $'''hello''' THEN\nEND"


def test_if_record_parsed_with_bare_variable_reference_and_string_literal() -> None:
    records = parse_dsl(IF_END_DSL)
    assert len(records) == 2
    if_record = records[0]
    assert isinstance(if_record, IfRecord)
    # 変数参照は %...% ではなく裸のトークンとしてDSLに現れる
    assert if_record.operand1 == "TestVar"
    assert if_record.operator == "="
    assert if_record.operand2 == "hello"


def test_end_parsed_as_bare_keyword() -> None:
    records = parse_dsl(IF_END_DSL)
    end_record = records[1]
    assert isinstance(end_record, KeywordRecord)
    assert end_record.name == "END"
    assert end_record.args == []


# Ifブロック内に「Set variable」(InnerVar)を実機で追加して再キャプチャした生データ。
# 4スペースインデントでネストが表現されている点が今回の検証の核心。
NESTED_IF_DSL = (
    "IF TestVar = $'''hello''' THEN\n"
    "    SET InnerVar TO $'''inside the if block'''\n"
    "END"
)


def test_nested_set_variable_inside_if_has_indent_one() -> None:
    records = parse_dsl(NESTED_IF_DSL)
    assert len(records) == 3
    if_record, inner_set, end_record = records
    assert isinstance(if_record, IfRecord)
    assert if_record.indent == 0
    assert isinstance(inner_set, SetVariableRecord)
    assert inner_set.indent == 1
    assert inner_set.var_name == "InnerVar"
    assert inner_set.value == "inside the if block"
    assert isinstance(end_record, KeywordRecord)
    assert end_record.indent == 0


# 実機で「Loop」アクション(Start from=1, End to=3, Increment by=1)を追加して
# 再キャプチャした生データ。
LOOP_DSL = "LOOP LoopIndex FROM 1 TO 3 STEP 1\nEND"


def test_loop_record_parsed_with_bounds_and_step() -> None:
    records = parse_dsl(LOOP_DSL)
    assert len(records) == 2
    loop_record, end_record = records
    assert isinstance(loop_record, LoopRecord)
    assert loop_record.loop_var == "LoopIndex"
    assert loop_record.start == "1"
    assert loop_record.end == "3"
    assert loop_record.step == "1"
    assert loop_record.indent == 0
    assert isinstance(end_record, KeywordRecord)
    assert end_record.name == "END"


# 実機で「For each」(Value to iterate=%TestVar%, Store into=CurrentItem)を
# 追加して再キャプチャした生データ。
FOREACH_DSL = "LOOP FOREACH CurrentItem IN TestVar\nEND"


def test_loop_foreach_record_parsed_with_bare_variable_reference() -> None:
    records = parse_dsl(FOREACH_DSL)
    assert len(records) == 2
    foreach_record = records[0]
    assert isinstance(foreach_record, LoopForeachRecord)
    assert foreach_record.item_var == "CurrentItem"
    assert foreach_record.collection == "TestVar"


# 実機で「Loop condition」(First operand=%LoopIndex%, Operator=Less than (<),
# Second operand=10)を追加して再キャプチャした生データ。
WHILE_DSL = "LOOP WHILE (LoopIndex) < (10)\nEND"


def test_loop_while_record_strips_parens_around_operands() -> None:
    records = parse_dsl(WHILE_DSL)
    assert len(records) == 2
    while_record = records[0]
    assert isinstance(while_record, LoopWhileRecord)
    # IfRecordと異なり、オペランドは丸括弧で囲まれているためこれを剥がして解決する
    assert while_record.operand1 == "LoopIndex"
    assert while_record.operator == "<"
    assert while_record.operand2 == "10"


def test_build_block_tree_leaves_flat_records_unchanged() -> None:
    # REAL_FLOW_DSLにはIF/LOOP等のブロック構文が無いため、木構造化しても
    # parse_dsl()の結果とそのまま一致するはず。
    records = parse_dsl(REAL_FLOW_DSL)
    tree = build_block_tree(records)
    assert tree == records


def test_build_block_tree_groups_nested_set_variable_under_if() -> None:
    tree = build_block_tree(parse_dsl(NESTED_IF_DSL))
    assert len(tree) == 1
    node = tree[0]
    assert isinstance(node, ConditionalNode)
    assert len(node.arms) == 1
    header, body = node.arms[0]
    assert isinstance(header, IfRecord)
    assert len(body) == 1
    assert isinstance(body[0], SetVariableRecord)
    assert body[0].var_name == "InnerVar"


# 実機でLOOP WHILEをIfブロック内に追加して再キャプチャした生データ(知見9)。
LOOP_WHILE_INSIDE_IF_DSL = (
    "IF TestVar = $'''hello''' THEN\n"
    "    SET InnerVar TO $'''inside the if block'''\n"
    "    LOOP WHILE (LoopIndex) < (10)\n"
    "    END\n"
    "END"
)


def test_build_block_tree_handles_loop_nested_inside_if() -> None:
    tree = build_block_tree(parse_dsl(LOOP_WHILE_INSIDE_IF_DSL))
    assert len(tree) == 1
    if_node = tree[0]
    assert isinstance(if_node, ConditionalNode)
    assert len(if_node.arms) == 1
    header, body = if_node.arms[0]
    assert isinstance(header, IfRecord)
    assert len(body) == 2

    set_var, while_node = body
    assert isinstance(set_var, SetVariableRecord)
    assert isinstance(while_node, BlockNode)
    assert isinstance(while_node.header, LoopWhileRecord)
    assert while_node.body == []


# 実機で「Else if」「Else」を追加して再キャプチャした生データ(知見11)。
# IF/ELSE IF/ELSEは同じindentの1構文で、ENDは1つだけ対応する。
IF_ELSEIF_ELSE_DSL = (
    "IF TestVar = $'''hello''' THEN\n"
    "ELSE IF TestVar = $'''world''' THEN\n"
    "ELSE\n"
    "    SET InnerVar TO $'''inside the if block'''\n"
    "    LOOP WHILE (LoopIndex) < (10)\n"
    "    END\n"
    "END"
)


def test_elseif_record_parsed_with_bare_variable_reference_and_string_literal() -> None:
    records = parse_dsl(IF_ELSEIF_ELSE_DSL)
    elseif_record = records[1]
    assert isinstance(elseif_record, ElseIfRecord)
    assert elseif_record.operand1 == "TestVar"
    assert elseif_record.operator == "="
    assert elseif_record.operand2 == "world"
    assert elseif_record.indent == 0


def test_else_parsed_as_bare_keyword() -> None:
    records = parse_dsl(IF_ELSEIF_ELSE_DSL)
    else_record = records[2]
    assert isinstance(else_record, KeywordRecord)
    assert else_record.name == "ELSE"
    assert else_record.indent == 0


def test_build_block_tree_groups_if_elseif_else_into_one_conditional_node_with_one_end() -> None:
    tree = build_block_tree(parse_dsl(IF_ELSEIF_ELSE_DSL))
    # IF/ELSE IF/ELSE/END全体がただ1つのConditionalNodeになり、
    # 末尾のENDだけが消費されて他に漏れ出さないこと。
    assert len(tree) == 1
    node = tree[0]
    assert isinstance(node, ConditionalNode)
    assert len(node.arms) == 3

    if_header, if_body = node.arms[0]
    assert isinstance(if_header, IfRecord)
    assert if_body == []

    elseif_header, elseif_body = node.arms[1]
    assert isinstance(elseif_header, ElseIfRecord)
    assert elseif_body == []

    else_header, else_body = node.arms[2]
    assert isinstance(else_header, KeywordRecord)
    assert else_header.name == "ELSE"
    assert len(else_body) == 2
    set_var, while_node = else_body
    assert isinstance(set_var, SetVariableRecord)
    assert isinstance(while_node, BlockNode)
    assert isinstance(while_node.header, LoopWhileRecord)
