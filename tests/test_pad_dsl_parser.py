"""pad_dsl_parser の単体テスト。

フィクスチャは design/dsl_format_findings.md に記録した、g1g2_testフローを
実機PADから「コピー&ペースト」で実際にエクスポートした生データそのもの。
"""
from __future__ import annotations

from dump_daemon.pad_dsl_parser import (
    ActionRecord,
    IfRecord,
    KeywordRecord,
    SetVariableRecord,
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
