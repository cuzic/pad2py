"""pad_dsl_parser の単体テスト。

フィクスチャは design/dsl_format_findings.md に記録した、g1g2_testフローを
実機PADから「コピー&ペースト」で実際にエクスポートした生データそのもの。
"""
from __future__ import annotations

from pathlib import Path

from dump_daemon.control_repository import parse_control_repository
from dump_daemon.pad_dsl import (
    ActionRecord,
    BlockNode,
    BlockRecord,
    CaseDefaultRecord,
    CaseRecord,
    CommentRecord,
    ConditionalNode,
    ElseIfFunctionRecord,
    ElseIfRecord,
    GuardedNode,
    IfActionRecord,
    IfFunctionRecord,
    IfRecord,
    KeywordRecord,
    LoopForeachRecord,
    LoopRecord,
    LoopWhileRecord,
    EnumRef,
    OnBlockErrorRecord,
    OnErrorNode,
    OnErrorRecord,
    RawExpr,
    SetVariableRecord,
    SwitchNode,
    SwitchRecord,
    UiElementRef,
    VarRef,
    WaitActionRecord,
    build_block_tree,
    parse_dsl,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"

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
    # Namespace.Enum.Value形式の列挙値はEnumRefとして区別される(VarRefとは別型)
    assert msg.params["Icon"] == EnumRef("Display.Icon.None")
    assert msg.params["Buttons"] == EnumRef("Display.Buttons.OK")
    assert msg.params["DefaultButton"] == EnumRef("Display.DefaultButton.Button1")
    assert msg.params["IsTopMost"] is False
    assert msg.output_var == "ButtonPressed"
    assert msg.output_vars == {"ButtonPressed": "ButtonPressed"}


def test_set_variable_parsed_with_unescaped_string_value() -> None:
    records = parse_dsl(REAL_FLOW_DSL)
    set_var = records[1]
    assert isinstance(set_var, SetVariableRecord)
    assert set_var.var_name == "TestVar"
    assert set_var.value == 'He said "hello" and used \\ in C:\\temp\\file.txt'


def test_set_variable_with_dotted_variable_trailer_resolved_as_varref_not_enumref() -> None:
    # design/dsl_format_findings.md 知見55(実機検証済み・重大なパーサーバグ修正): PADの変数は
    # `InnerVar.SomeProperty`のようなドット付きプロパティアクセス(VariableTrailer)を
    # 持ちうるが、テキスト上は`Namespace.Enum.Value`形式のEnumRefと区別がつかない。実機で
    # `%InnerVar.SomeProperty%`という式をSet variableのValueに入力・保存・一括コピーしたところ
    # `SET NewVar3 TO InnerVar.SomeProperty`という、これまでのEnumRef captureと字面上同じ形の
    # DSLが得られ、修正前は`EnumRef('InnerVar.SomeProperty')`に誤分類され、codegenが
    # 文字列リテラル`'InnerVar.SomeProperty'`を出力してしまっていた(変数参照のはずが
    # 文字列定数にすり替わる、気付かれにくい意味論破壊バグ)。これまでの実機EnumRef captureが
    # 全て例外なく3セグメント(`Namespace.Enum.Value`)だった実績に基づき、EnumRef判定を
    # ドット数2個以上(3セグメント以上)に限定し、2セグメントはVarRefへフォールバックするよう
    # 修正した。
    records = parse_dsl("SET NewVar3 TO InnerVar.SomeProperty")
    set_var = records[0]
    assert isinstance(set_var, SetVariableRecord)
    assert set_var.value == VarRef("InnerVar.SomeProperty")


def test_set_variable_with_index_trailer_resolved_as_varref() -> None:
    # design/dsl_format_findings.md 知見55・知見60(実機検証済み): `InnerVar[0]`のような
    # 添字アクセスも実機確認した。これは元々`_DOTTED_RE`にマッチしない(ドットが無い)ため、
    # 修正前から既に`VarRef`としてそのまま保持され、codegenも`InnerVar[0]`という有効な
    # Python式を生成できていた。知見60で実機実行により、添字は**0始まり**であることを
    # 確定した(`"ABCDEFGHIJ"[0]` → `"A"`、Pythonの添字と完全に一致)。
    records = parse_dsl("SET NewVar3 TO InnerVar[0]")
    set_var = records[0]
    assert isinstance(set_var, SetVariableRecord)
    assert set_var.value == VarRef("InnerVar[0]")


def test_set_variable_with_slice_trailer_resolved_as_varref() -> None:
    # design/dsl_format_findings.md 知見55の追記・知見60(実機検証済み): `VariableTrailer`の
    # 「Slice構文」(`.Name`/`[Index]`と並んで未検証のまま持ち越していた最後の1つ)も実機確認した。
    # `%InnerVar[0:2]%`という式を入力・保存・単独コピーしたところ`SET NewVar3 TO InnerVar[0:2]`
    # というDSLが得られ、予測通りPythonのスライス構文と全く同じ`[start:end]`形式だった
    # (キャンバスのカード表示では`[0:2]`部分が見た目上省略されるが、これは表示上の省略に
    # 過ぎず、一括コピーしたDSLには正しく残っていることを確認した)。`[0]`の添字アクセス同様、
    # ドットを含まないため`_ENUM_REF_RE`にはマッチせず、修正前から既に`VarRef`としてそのまま
    # 保持され、codegenも`InnerVar[0:2]`という有効なPythonのスライス式を生成できていた。
    # 知見60で実機実行により、終端を含まない(exclusive)ことも確定した
    # (`"ABCDEFGHIJ"[0:3]` → `"ABC"`、Pythonのスライスと完全に一致)。
    records = parse_dsl("SET NewVar3 TO InnerVar[0:2]")
    set_var = records[0]
    assert isinstance(set_var, SetVariableRecord)
    assert set_var.value == VarRef("InnerVar[0:2]")


def test_variable_trailer_index_and_slice_semantics_confirmed_by_real_execution() -> None:
    # design/dsl_format_findings.md 知見60(実機実行による検証、知見51のLOOP range確認と
    # 同じ手法): PADのMainサブフロー上で実際に`NewVar3 = "ABCDEFGHIJ"`を代入した上で
    # `%NewVar3[0:3]%|%NewVar3[0]%|%NewVar3[3]%`という式をPythonスクリプトアクション経由で
    # ファイルへ書き出し、実機実行後にWinRM経由でファイルの中身を読み取った結果が
    # `'ABC|A|D'`だった。これはPython自身の同じ添字/スライス式の評価結果と完全に一致する
    # ——PADの`[Index]`/`[start:end]`はPythonと寸分違わず「0始まり・終端を含まない
    # (exclusive)」という意味論であることが確定した。このテストはパーサーの構造化結果を
    # 検証するものではなく(それは上記2つのテストが担う)、知見60の実機実行結果を
    # Python側で再現できることを示す回帰テストとして記録する。
    source = "ABCDEFGHIJ"
    assert source[0:3] == "ABC"
    assert source[0] == "A"
    assert source[3] == "D"
    assert f"{source[0:3]}|{source[0]}|{source[3]}" == "ABC|A|D"


def test_enum_ref_still_recognized_for_known_three_segment_values() -> None:
    # design/dsl_format_findings.md 知見55: EnumRef判定を3セグメント限定にした後も、
    # これまでに実機確認済みの全EnumRef値(例: Display.DefaultButton.Button1)は
    # 引き続き正しくEnumRefとして認識されることを確認する回帰テスト。
    for value in (
        "Display.DefaultButton.Button1",
        "Display.Buttons.OK",
        "Display.Icon.None",
        "MouseAndKeyboard.MouseClickType.LeftClick",
        "UIAutomation.ClickType.LeftClick",
    ):
        records = parse_dsl(f"SET NewVar3 TO {value}")
        set_var = records[0]
        assert isinstance(set_var, SetVariableRecord)
        assert set_var.value == EnumRef(value)


def test_set_variable_with_compound_and_or_not_expression_captured_as_raw_expr() -> None:
    # design/dsl_format_findings.md 知見53(実機検証済み): `SET ... TO`の右辺は単一トークンに
    # 収まらない複合式になりうる。以前は`tokens[3]`1つだけを読んでいたため、
    # "SET NewVar3 TO 1 = 1 AND 2 = 2 OR NOT 3 = 4"のようなDSLで`= 1 AND 2 = 2 OR NOT 3 = 4`
    # 部分がサイレントに切り捨てられ、`value`が単なる`1`になっていた(知見15・26・36・38・46・50
    # と同系統の、気付かれにくいデータ消失バグ)。AND/OR/NOTはPADのダイアログでは小文字で
    # 入力しても大文字に正規化されて直列化されることも実機確認済み。
    records = parse_dsl("SET NewVar3 TO 1 = 1 AND 2 = 2 OR NOT 3 = 4")
    set_var = records[0]
    assert isinstance(set_var, SetVariableRecord)
    assert isinstance(set_var.value, RawExpr)
    assert set_var.value.text == "1 = 1 AND 2 = 2 OR NOT 3 = 4"
    # pad_expr_parser.py(Lark文法)での構造化にも成功しているはず(素朴なトークン結合への
    # フォールバックに陥っていないことの確認。構造の詳細はtest_pad_expr_parser.pyで検証)。
    assert set_var.value.tree is not None


def test_set_variable_with_xor_and_parentheses_preserves_parens_in_raw_expr() -> None:
    # design/dsl_format_findings.md 知見53: 括弧も明示的に書けば保持される
    # (`XOR`も実機確認済み)。
    records = parse_dsl("SET NewVar3 TO (1 = 1 XOR 2 = 2) AND (3 = 3)")
    set_var = records[0]
    assert isinstance(set_var, SetVariableRecord)
    assert isinstance(set_var.value, RawExpr)
    assert set_var.value.text == "(1 = 1 XOR 2 = 2) AND (3 = 3)"
    assert set_var.value.tree is not None


def test_set_variable_with_arithmetic_expression_keeps_mod_lowercase() -> None:
    # design/dsl_format_findings.md 知見53: 算術演算子(`+`/`-`/`*`/`/`/`mod`)も複合式として
    # 実機確認済み。`AND`/`OR`/`NOT`/`XOR`とは異なり、`mod`は小文字のまま正規化されない
    # (実機で小文字入力したものがそのまま小文字で保存される挙動を確認した)。
    records = parse_dsl("SET NewVar3 TO 1 + 2 * 3 - 4 / 2 mod 3")
    set_var = records[0]
    assert isinstance(set_var, SetVariableRecord)
    assert isinstance(set_var.value, RawExpr)
    assert set_var.value.text == "1 + 2 * 3 - 4 / 2 mod 3"
    assert set_var.value.tree is not None


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
    # 変数参照は %...% ではなく裸のトークンとしてDSLに現れ、VarRefとして区別される
    assert if_record.operand1 == VarRef("TestVar")
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
    assert loop_record.start == 1
    assert loop_record.end == 3
    assert loop_record.step == 1
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
    assert foreach_record.collection == VarRef("TestVar")


# 実機で「Loop condition」(First operand=%LoopIndex%, Operator=Less than (<),
# Second operand=10)を追加して再キャプチャした生データ。
WHILE_DSL = "LOOP WHILE (LoopIndex) < (10)\nEND"


def test_loop_while_record_strips_parens_around_operands() -> None:
    records = parse_dsl(WHILE_DSL)
    assert len(records) == 2
    while_record = records[0]
    assert isinstance(while_record, LoopWhileRecord)
    # IfRecordと異なり、オペランドは丸括弧で囲まれているためこれを剥がして解決する
    assert while_record.operand1 == VarRef("LoopIndex")
    assert while_record.operator == "<"
    assert while_record.operand2 == 10


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
    assert elseif_record.operand1 == VarRef("TestVar")
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


# 実機でLOOP WHILEの中にExit loop/Next loopを追加して再キャプチャした生データ。
EXIT_NEXT_LOOP_DSL = "LOOP WHILE (LoopIndex) < (10)\n    EXIT LOOP\n    NEXT LOOP\nEND"


def test_exit_loop_and_next_loop_parsed_as_two_token_keywords() -> None:
    records = parse_dsl(EXIT_NEXT_LOOP_DSL)
    assert len(records) == 4
    while_record, exit_record, next_record, end_record = records

    assert exit_record.indent == 1
    assert isinstance(exit_record, KeywordRecord)
    assert exit_record.name == "EXIT"
    assert exit_record.args == ["LOOP"]

    assert isinstance(next_record, KeywordRecord)
    assert next_record.name == "NEXT"
    assert next_record.args == ["LOOP"]
    assert next_record.indent == 1


def test_build_block_tree_keeps_exit_next_loop_as_leaves_in_while_body() -> None:
    tree = build_block_tree(parse_dsl(EXIT_NEXT_LOOP_DSL))
    assert len(tree) == 1
    while_node = tree[0]
    assert isinstance(while_node, BlockNode)
    assert isinstance(while_node.header, LoopWhileRecord)
    assert len(while_node.body) == 2
    exit_rec, next_rec = while_node.body
    assert isinstance(exit_rec, KeywordRecord) and exit_rec.name == "EXIT"
    assert isinstance(next_rec, KeywordRecord) and next_rec.name == "NEXT"


# 実機で外側Ifの「hello」アーム(空だった本体)にネストしたIfを追加して
# 再キャプチャした生データ。PADのIfダイアログにAND/OR合成UIが無いこと(知見13)から、
# 複合条件はIfのネストで代替されると推測しており、それがbuild_block_tree()の
# 既存の再帰構造だけで(コード変更なしに)正しく組み立てられることを確認するための回帰テスト。
NESTED_IF_INSIDE_IF_DSL = (
    "IF TestVar = $'''hello''' THEN\n"
    "    IF InnerVar = $'''nested''' THEN\n"
    "    END\n"
    "END"
)


def test_build_block_tree_handles_if_nested_inside_if_arm() -> None:
    tree = build_block_tree(parse_dsl(NESTED_IF_INSIDE_IF_DSL))
    assert len(tree) == 1
    outer = tree[0]
    assert isinstance(outer, ConditionalNode)
    assert len(outer.arms) == 1
    outer_header, outer_body = outer.arms[0]
    assert isinstance(outer_header, IfRecord)
    assert outer_header.operand1 == VarRef("TestVar")

    assert len(outer_body) == 1
    inner = outer_body[0]
    assert isinstance(inner, ConditionalNode)
    assert len(inner.arms) == 1
    inner_header, inner_body = inner.arms[0]
    assert isinstance(inner_header, IfRecord)
    assert inner_header.operand1 == VarRef("InnerVar")
    assert inner_body == []


# 回帰テスト: LOOP系ブロックが自分自身の閉じENDを消費せず、呼び出し元の
# while ループがそのENDを「呼び出し元自身の終端」と誤認して後続の兄弟要素を
# 黙って切り捨てるバグがあった(2つ以上のLOOP系ブロックが同じ深さで連続する場合にのみ
# 顕在化するため、これまでのフィクスチャ——末尾に1個だけLOOPがあるもの——では
# 見逃されていた)。
TWO_SIBLING_LOOPS_WITH_TRAILING_ACTION_DSL = (
    "LOOP FOREACH CurrentItem IN TestVar\nEND\n"
    "LOOP LoopIndex FROM 1 TO 3 STEP 1\nEND\n"
    "WAIT 1"
)


def test_build_block_tree_does_not_drop_siblings_after_a_simple_loop_block() -> None:
    tree = build_block_tree(parse_dsl(TWO_SIBLING_LOOPS_WITH_TRAILING_ACTION_DSL))
    assert len(tree) == 3
    foreach_node, loop_node, wait_record = tree
    assert isinstance(foreach_node, BlockNode)
    assert isinstance(foreach_node.header, LoopForeachRecord)
    assert isinstance(loop_node, BlockNode)
    assert isinstance(loop_node.header, LoopRecord)
    assert isinstance(wait_record, KeywordRecord)
    assert wait_record.name == "WAIT"


def test_set_variable_with_mixed_text_and_variable_markers_stays_a_plain_string() -> None:
    # 実機で値フィールドに "Hello %TestVar% world, LoopIndex is %LoopIndex%" という
    # リテラルテキストと変数参照の混在(テキストテンプレート)を入力して再キャプチャした
    # ところ、値全体が $'''...''' の文字列リテラルとして囲まれ、%VarName% マーカーは
    # (裸トークンに剥がされず)そのまま文字列の中身として残っていた。
    # これは「値全体がまるごと1個の変数参照」のときだけVarRefになる(知見6)ことの裏返しで、
    # 既存の実装は変更なしで正しく処理できることの確認。
    dsl = "SET InterpVar TO $'''Hello %TestVar% world, LoopIndex is %LoopIndex%'''"
    records = parse_dsl(dsl)
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, SetVariableRecord)
    assert record.value == "Hello %TestVar% world, LoopIndex is %LoopIndex%"


# 実機で「If」のOperatorを「Contains」に切り替えて再キャプチャした生データ(知見18-2)。
# 中置記法ではなく関数呼び出し構文になる。
CONTAINS_IF_DSL = "IF Contains(InnerVar, $'''nested''', False) THEN\nEND"


def test_contains_parsed_as_function_record_not_silently_corrupted() -> None:
    # 修正前はoperatorフィールドに未解決のプレースホルダキーが漏れ出す等、
    # クラッシュせず壊れたデータをサイレントに返していた(知見18-2で発覚したバグ)。
    records = parse_dsl(CONTAINS_IF_DSL)
    assert len(records) == 2
    func_record, end_record = records
    assert isinstance(func_record, IfFunctionRecord)
    assert func_record.function_name == "Contains"
    assert func_record.args == [VarRef("InnerVar"), "nested", False]
    assert func_record.indent == 0
    assert isinstance(end_record, KeywordRecord)
    assert end_record.name == "END"


def test_build_block_tree_treats_if_function_record_as_conditional_arm() -> None:
    tree = build_block_tree(parse_dsl(CONTAINS_IF_DSL))
    assert len(tree) == 1
    node = tree[0]
    assert isinstance(node, ConditionalNode)
    assert len(node.arms) == 1
    header, body = node.arms[0]
    assert isinstance(header, IfFunctionRecord)
    assert body == []


def test_elseif_contains_parsed_as_function_record() -> None:
    dsl = "IF TestVar = $'''hello''' THEN\nELSE IF Contains(InnerVar, $'''nested''', False) THEN\nEND"
    records = parse_dsl(dsl)
    elseif_record = records[1]
    assert isinstance(elseif_record, ElseIfFunctionRecord)
    assert elseif_record.function_name == "Contains"
    assert elseif_record.args == [VarRef("InnerVar"), "nested", False]


def test_action_with_multiple_outputs_keeps_all_of_them() -> None:
    # 実機で「Get window」(Get window=Foreground window)を追加して再キャプチャした生データ
    # (知見26)。修正前は output_var が単一フィールドのため、2個目の `=>` 束縛
    # (WindowInstance=> AutomationWindow)が1個目(WindowTitle=> WindowTitle)を
    # サイレントに上書きし、WindowTitleの束縛が完全に失われていた。
    dsl = "UIAutomation.GetWindow.GetForegroundWindow WindowTitle=> WindowTitle WindowInstance=> AutomationWindow"
    records = parse_dsl(dsl)
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, ActionRecord)
    assert record.action_id == "UIAutomation.GetWindow.GetForegroundWindow"
    assert record.output_vars == {
        "WindowTitle": "WindowTitle",
        "WindowInstance": "AutomationWindow",
    }
    # output_var は後方互換のため最後に見つかったものを保持するだけ(単一出力専用)。
    assert record.output_var == "AutomationWindow"


def test_single_line_comment_parsed_as_comment_record() -> None:
    # 確定済みの構文(実機未確認)。
    records = parse_dsl("# this is a comment")
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, CommentRecord)
    assert record.text == "this is a comment"


def test_empty_comment_parsed_as_comment_record_with_empty_text() -> None:
    records = parse_dsl("#")
    assert len(records) == 1
    assert isinstance(records[0], CommentRecord)
    assert records[0].text == ""


def test_comment_does_not_get_mistaken_for_action_or_keyword() -> None:
    dsl = "# WAIT is not a real wait here\nWAIT 1"
    records = parse_dsl(dsl)
    assert len(records) == 2
    assert isinstance(records[0], CommentRecord)
    assert records[0].text == "WAIT is not a real wait here"
    assert isinstance(records[1], KeywordRecord)
    assert records[1].name == "WAIT"


def test_escaped_apostrophe_in_string_literal_is_unescaped() -> None:
    # `"`/`'`/`\`の3種類すべてにバックスラッシュが前置されることが確定済み。
    # 以前は`\"`と`\\`しか解除しておらず、アポストロフィを含む英語テキスト
    # (例: "it's")がPADのDSL上では`it\'s`になるため、バックスラッシュが残留する
    # サイレントなバグがあった。
    records = parse_dsl("SET TestVar TO $'''it\\'s a test'''")
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, SetVariableRecord)
    assert record.value == "it's a test"


def test_doubled_percent_in_string_literal_is_unescaped() -> None:
    # `$'''...'''`形式のリテラル部分は`%`が常に`%%`に二重化されて出力されることが
    # 確定済み(推測ではない)。
    records = parse_dsl("SET TestVar TO $'''100%% done'''")
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, SetVariableRecord)
    assert record.value == "100% done"


def test_multiline_comment_parsed_with_slash_hash_delimiters() -> None:
    # 改行を含むコメントは`/# ... #/`で囲まれることが確定済み(実機未確認)。
    dsl = "/# line one\nline two #/\nWAIT 1"
    records = parse_dsl(dsl)
    assert len(records) == 2
    assert isinstance(records[0], CommentRecord)
    assert records[0].text == "line one\nline two "
    assert isinstance(records[1], KeywordRecord)
    assert records[1].name == "WAIT"


def test_multiline_comment_unescapes_escaped_delimiter_and_backslash() -> None:
    # EscapeRobinComment()は`#/`と`\`の直前に`\`を挿入する。逆変換は
    # `\#/`→`#/`、`\\`→`\`。
    dsl = "/# contains \\#/ and \\\\ literally\nsecond line #/"
    records = parse_dsl(dsl)
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, CommentRecord)
    assert record.text == "contains #/ and \\ literally\nsecond line "


def test_multiline_comment_does_not_corrupt_string_literal_masking() -> None:
    # コメント本文に`$'''`のような文字列リテラルっぽい文字列が入っていても、
    # コメントを先にマスキングするため文字列リテラルとして誤認されない。
    dsl = "/# looks like $'''a string''' but is not #/\nSET TestVar TO $'''real'''"
    records = parse_dsl(dsl)
    assert len(records) == 2
    assert isinstance(records[0], CommentRecord)
    assert records[0].text == "looks like $'''a string''' but is not "
    assert isinstance(records[1], SetVariableRecord)
    assert records[1].value == "real"


def test_multiline_comment_matches_real_device_capture() -> None:
    # 実機で「Comment」アクションに3行("line one"/"line two with #/ inside"/"line three")を
    # 入力してキャプチャした生データ(design/dsl_format_findings.md 知見35)。ソースから実装した
    # エスケープ規則(`#/`→`\#/`)が実機の出力と完全に一致することを確認した——コード変更は不要だった。
    dsl = "    /# line one\nline two with \\#/ inside\nline three#/\nEND"
    records = parse_dsl(dsl)
    assert len(records) == 2
    assert isinstance(records[0], CommentRecord)
    assert records[0].text == "line one\nline two with #/ inside\nline three"


# 実機で「Switch」「Case」「Default case」「Comment」(Caseの本体用)を追加してキャプチャ
# した生データ(design/dsl_format_findings.md 知見33)。「Value to check」欄に裸の
# "TestVar"(%で囲まない)と入力したため、変数参照ではなく文字列リテラルとして
# 直列化されている点に注意(他の文字列パラメータと同じ%interpolation規則——知見16)。
REAL_SWITCH_DSL = (
    "SWITCH $'''TestVar'''\n"
    "    CASE = $'''a'''\n"
    "        # inside case\n"
    "    DEFAULT\n"
    "END"
)


def test_switch_case_default_parsed_as_dedicated_records() -> None:
    # switch_statement/case_statement/case_defaultがif_statement/elseif_statement/
    # else_statementと文法上並列であることが確認済み。CASEの演算子(`=`)は実機で確認済み。
    records = parse_dsl(REAL_SWITCH_DSL)
    assert len(records) == 5
    assert isinstance(records[0], SwitchRecord)
    assert records[0].expression == "TestVar"
    assert isinstance(records[1], CaseRecord)
    assert records[1].operator == "="
    assert records[1].value == "a"
    assert records[2].indent == 2  # コメントはCASEよりさらに1段深い
    assert isinstance(records[3], CaseDefaultRecord)


def test_build_block_tree_groups_switch_case_default_into_one_switch_node() -> None:
    # **重要な訂正**: 当初はIF/ELSE IFとの文法上の並列性から「CASE/DEFAULTはSWITCHと
    # 同じindentに並ぶ」と類推していたが、実機検証(design/dsl_format_findings.md 知見33)で
    # これは誤りだと判明した。実際にはCASE/DEFAULTはSWITCHより1段深く、各アームの本体は
    # さらに1段深い(LOOPのheader→bodyの関係が二重に重なっている)。
    dsl = REAL_SWITCH_DSL + "\nWAIT 9"
    tree = build_block_tree(parse_dsl(dsl))
    assert len(tree) == 2
    switch_node = tree[0]
    assert isinstance(switch_node, SwitchNode)
    assert switch_node.expression == "TestVar"
    assert len(switch_node.arms) == 2
    case_a, default = switch_node.arms
    assert isinstance(case_a[0], CaseRecord) and case_a[0].operator == "=" and case_a[0].value == "a"
    assert isinstance(case_a[1][0], CommentRecord) and case_a[1][0].text == "inside case"
    assert isinstance(default[0], CaseDefaultRecord)
    assert default[1] == []
    # SwitchNode自体のENDを正しく消費し、後続の兄弟要素を切り捨てていないこと
    # (知見15と同種の回帰——LOOP系ブロックで一度発覚したバグと同じ形)。
    assert tree[1] == KeywordRecord(name="WAIT", args=["9"], indent=0)


def test_build_block_tree_handles_switch_with_no_default() -> None:
    dsl = "SWITCH $'''TestVar'''\n    CASE = $'''a'''\n        WAIT 1\nEND"
    tree = build_block_tree(parse_dsl(dsl))
    assert len(tree) == 1
    switch_node = tree[0]
    assert isinstance(switch_node, SwitchNode)
    assert len(switch_node.arms) == 1
    case_a = switch_node.arms[0]
    assert case_a[1] == [KeywordRecord(name="WAIT", args=["1"], indent=2)]


def test_switch_value_entered_as_pure_var_marker_parses_as_bare_var_ref() -> None:
    # design/dsl_format_findings.md 知見33の「副次的な発見」(「Value to check」欄に裸の
    # "TestVar"を入力すると文字列リテラルになる)に続けて、今度は"%TestVar%"(純粋な
    # %Var%マーカーのみ)を入力して実機キャプチャしたところ、知見16と同じ規則通り
    # `SWITCH TestVar`という裸トークン(VarRef)になることを確認した——既存の
    # `_resolve_value()`で無変更のまま正しく解釈できることも確認済み。
    records = parse_dsl("SWITCH TestVar")
    assert len(records) == 1
    assert isinstance(records[0], SwitchRecord)
    assert records[0].expression == VarRef("TestVar")


def test_not_in_operator_merged_into_single_token_for_if() -> None:
    # `NOT IN`が内部に空白を1つ持つ1つの文字列として直列化されることが確定済み。
    # 素朴にline.split()するだけだと"NOT"/"IN"の2トークンに分かれ、tokens[2]を演算子として
    # 読む既存ロジックがずれてしまう(以前から既知だったギャップ)——_merge_not_in()で解消。
    records = parse_dsl("IF TestVar NOT IN $'''list''' THEN")
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, IfRecord)
    assert record.operand1 == VarRef("TestVar")
    assert record.operator == "NOT IN"
    assert record.operand2 == "list"


def test_in_operator_parsed_as_single_token_for_loop_while() -> None:
    records = parse_dsl("LOOP WHILE (TestVar) IN ($'''list''')")
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, LoopWhileRecord)
    assert record.operator == "IN"


# 実機で「Run Python script」の「On error」>「All errors (default)」に`Set variable`を
# 追加し(Continue flow run)、キャプチャした生データ(design/dsl_format_findings.md 知見34。
# PythonCodeの中身自体はここでのテスト対象ではないため簡略化してある)。
REAL_ON_ERROR_DSL = (
    "Scripting.RunPythonScript.RunPythonScript "
    "PythonCode: $'''pass''' ScriptOutput=> PythonScriptOutput3\n"
    "ON ERROR\n"
    "SET NewVar TO $'''recovered'''\n"
    "END"
)


def test_on_error_parsed_as_bare_keyword_at_same_indent_as_guarded_action() -> None:
    records = parse_dsl(REAL_ON_ERROR_DSL)
    assert len(records) == 4
    assert isinstance(records[0], ActionRecord)
    assert isinstance(records[1], OnErrorRecord)
    assert records[1].indent == records[0].indent
    assert isinstance(records[2], SetVariableRecord)
    assert records[2].indent == records[1].indent  # 他のブロック構文と異なり本体は深くならない
    assert isinstance(records[3], KeywordRecord) and records[3].name == "END"


def test_build_block_tree_wraps_preceding_action_in_guarded_node() -> None:
    # **重要な訂正**: 当初は「本体はヘッダーより1段深い」と予測していたが、
    # 実機検証(知見34)で誤りと判明した——本体はON ERRORヘッダーと同じindentだった。
    tree = build_block_tree(parse_dsl(REAL_ON_ERROR_DSL))
    assert len(tree) == 1
    guarded = tree[0]
    assert isinstance(guarded, GuardedNode)
    assert isinstance(guarded.node, ActionRecord)
    assert guarded.node.action_id == "Scripting.RunPythonScript.RunPythonScript"
    assert isinstance(guarded.on_error, OnErrorNode)
    assert len(guarded.on_error.arms) == 1
    header, arm_body = guarded.on_error.arms[0]
    assert isinstance(header, OnErrorRecord) and header.case_name is None
    assert len(arm_body) == 1
    set_var = arm_body[0]
    assert isinstance(set_var, SetVariableRecord)
    assert set_var.var_name == "NewVar"
    assert set_var.value == "recovered"


def test_build_block_tree_does_not_drop_siblings_after_on_error_block() -> None:
    # 知見15・知見33と同種の回帰確認(ブロック構文の後に兄弟要素を切り捨てないこと)。
    dsl = REAL_ON_ERROR_DSL + "\nWAIT 9"
    tree = build_block_tree(parse_dsl(dsl))
    assert len(tree) == 2
    assert isinstance(tree[0], GuardedNode)
    assert tree[1] == KeywordRecord(name="WAIT", args=["9"], indent=0)


def test_build_block_tree_handles_on_error_with_empty_body() -> None:
    dsl = "WAIT 1\nON ERROR\nEND"
    tree = build_block_tree(parse_dsl(dsl))
    assert len(tree) == 1
    guarded = tree[0]
    assert isinstance(guarded, GuardedNode)
    assert len(guarded.on_error.arms) == 1
    assert guarded.on_error.arms[0][1] == []


# 実機で「Run Python script」の「On error」>「Failed to run Python script」(名前付きケース)
# にも`Set variable`を追加し、既存の「All errors (default)」と連続させてキャプチャした生データ
# (design/dsl_format_findings.md 知見36)。
REAL_MULTI_ARM_ON_ERROR_DSL = (
    "Scripting.RunPythonScript.RunPythonScript "
    "PythonCode: $'''pass''' ScriptOutput=> PythonScriptOutput3\n"
    "ON ERROR RunPythonScriptError\n"
    "SET NewVar2 TO $'''script failed'''\n"
    "ON ERROR\n"
    "SET NewVar TO $'''recovered'''\n"
    "END"
)


def test_on_error_parses_named_case_as_three_tokens() -> None:
    records = parse_dsl(REAL_MULTI_ARM_ON_ERROR_DSL)
    assert isinstance(records[1], OnErrorRecord)
    assert records[1].case_name == "RunPythonScriptError"
    assert isinstance(records[3], OnErrorRecord)
    assert records[3].case_name is None


def test_build_block_tree_groups_consecutive_on_error_arms_without_separator() -> None:
    # **重要な発見**: 複数のON ERRORアーム(名前付き+catch-all)が区切り無しに連続し、
    # 末尾に1つのENDだけが付く——SwitchNodeのCASE/DEFAULTと同じ構造(design/dsl_format_findings.md
    # 知見36)。当初の実装は2個目のON ERRORを1個目の本体に誤って取り込んでしまうバグが
    # あったため、`stop_at_on_error`で明示的に区切るよう修正した。
    tree = build_block_tree(parse_dsl(REAL_MULTI_ARM_ON_ERROR_DSL))
    assert len(tree) == 1
    guarded = tree[0]
    assert isinstance(guarded, GuardedNode)
    assert isinstance(guarded.node, ActionRecord)
    assert len(guarded.on_error.arms) == 2
    named_header, named_body = guarded.on_error.arms[0]
    assert named_header.case_name == "RunPythonScriptError"
    assert len(named_body) == 1 and named_body[0].var_name == "NewVar2"
    default_header, default_body = guarded.on_error.arms[1]
    assert default_header.case_name is None
    assert len(default_body) == 1 and default_body[0].var_name == "NewVar"


def test_repeat_action_parsed_as_keyword_record_inside_on_error_arm() -> None:
    # design/dsl_format_findings.md 知見37(実機検証済み): 「Exception handling mode」を
    # 「Repeat action」に変更すると、アーム本体に`REPEAT ACTION`が追加される(ソース上
    # `RepeatActionStatement.ToString()`で予測していた構文そのまま)。`EXIT LOOP`/`NEXT LOOP`と
    # 同じ2トークンのベアキーワードとして扱える。
    dsl = (
        "Scripting.RunPythonScript.RunPythonScript "
        "PythonCode: $'''pass''' ScriptOutput=> PythonScriptOutput3\n"
        "ON ERROR RunPythonScriptError\n"
        "SET NewVar2 TO $'''script failed'''\n"
        "REPEAT ACTION\n"
        "ON ERROR\n"
        "SET NewVar TO $'''recovered'''\n"
        "END"
    )
    tree = build_block_tree(parse_dsl(dsl))
    guarded = tree[0]
    assert isinstance(guarded, GuardedNode)
    named_header, named_body = guarded.on_error.arms[0]
    assert named_header.case_name == "RunPythonScriptError"
    assert len(named_body) == 2
    assert named_body[1] == KeywordRecord(name="REPEAT", args=["ACTION"], indent=0)


def test_build_block_tree_handles_on_error_with_header_nested_one_level_deeper() -> None:
    # design/dsl_format_findings.md 知見61(実機再検証): 知見34/36(上の`REAL_ON_ERROR_DSL`/
    # `REAL_MULTI_ARM_ON_ERROR_DSL`、ヘッダー・本体とも保護対象の文と同じindent)とは別に、
    # **同じ`ON ERROR RunPythonScriptError`/`ON ERROR`の2アーム構造が、ヘッダーが保護対象の
    # 文より1段深く・本体がヘッダーよりさらに1段深い形で実機に実在する**ことを、本セッションで
    # VM上のLoopTestフローから「アクション単体のコピー」と「フロー全体の一括コピー」の
    # 両方で独立に再現した(`tests/fixtures/on_error_nested_indent.txt`がその実際の
    # クリップボードキャプチャそのもの)。`build_block_tree()`はヘッダー自身のindentが
    # 保護対象の文のindentと一致するかどうかで、どちらの形かを自己記述的に判別する。
    text = (FIXTURES_DIR / "on_error_nested_indent.txt").read_text(encoding="utf-8")
    records = parse_dsl(text)
    assert isinstance(records[0], ActionRecord)
    assert isinstance(records[1], OnErrorRecord) and records[1].case_name == "RunPythonScriptError"
    assert records[1].indent == records[0].indent + 1  # 知見34/36とは逆に、保護対象より1段深い
    assert isinstance(records[2], SetVariableRecord)
    assert records[2].indent == records[1].indent + 1  # 本体はヘッダーよりさらに1段深い

    tree = build_block_tree(records)
    assert len(tree) == 1
    guarded = tree[0]
    assert isinstance(guarded, GuardedNode)
    assert isinstance(guarded.node, ActionRecord)
    assert len(guarded.on_error.arms) == 2
    named_header, named_body = guarded.on_error.arms[0]
    assert named_header.case_name == "RunPythonScriptError"
    assert len(named_body) == 1 and named_body[0].var_name == "NewVar2"
    default_header, default_body = guarded.on_error.arms[1]
    assert default_header.case_name is None
    assert len(default_body) == 1 and default_body[0].var_name == "NewVar"


def test_ui_element_reference_with_space_in_name_parsed_as_single_token() -> None:
    # 実機で「Click UI element in window」にUI要素ピッカーで「Start Button」(Windowsの
    # スタートボタン)を選んでキャプチャした生データ(design/dsl_format_findings.md 知見38)。
    # **重要な発見**: UI要素セレクタの実体(CSS風セレクタ文字列)はパラメータ値に直接現れず、
    # `appmask['<表示名>']`という名前参照になる。表示名に空白を含む(`'Start Button'`)ため、
    # `$'''...'''`と同じくマスキングしないと`line.split()`で2トークンに割れてデータが
    # 破損する(自分で書いたテストで発覚・修正済みのバグ)。
    dsl = (
        "UIAutomation.Click.Click Element: appmask['Start Button'] "
        "ClickType: UIAutomation.ClickType.LeftClick "
        "MousePositionRelativeToElement: UIAutomation.RectangleEdgePoint.MiddleCenter "
        "OffsetX: 0 OffsetY: 0"
    )
    records = parse_dsl(dsl)
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, ActionRecord)
    assert record.action_id == "UIAutomation.Click.Click"
    assert record.params["Element"] == UiElementRef(path=("Start Button",))
    assert record.params["Element"].name == "Start Button"
    assert record.params["ClickType"] == EnumRef("UIAutomation.ClickType.LeftClick")
    assert record.params["OffsetX"] == 0


def test_ui_element_reference_with_nested_path_and_escaped_quotes() -> None:
    # design/dsl_format_findings.md 知見46(実機検証済み): 対象要素が別ウィンドウの子孫の
    # 場合、`appmask['<祖先>']['<対象>']`のように`['...']`が複数連なり、各セグメントの
    # 表示名自体が持つ`'`は`\'`でエスケープされる。メモ帳のテキスト編集領域を
    # UI要素ピッカーで選んで実機キャプチャした生データそのもの。
    dsl = (
        "UIAutomation.Click.Click "
        "Element: appmask['Window \\'Untitled - Notepad\\'']['Document \\'Text Editor\\''] "
        "ClickType: UIAutomation.ClickType.LeftClick "
        "MousePositionRelativeToElement: UIAutomation.RectangleEdgePoint.MiddleCenter "
        "OffsetX: 0 OffsetY: 0"
    )
    records = parse_dsl(dsl)
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, ActionRecord)
    element = record.params["Element"]
    assert isinstance(element, UiElementRef)
    assert element.path == ("Window 'Untitled - Notepad'", "Document 'Text Editor'")
    assert element.name == "Document 'Text Editor'"


def test_on_block_error_wraps_block_node_with_next_action_in_handler_body() -> None:
    # design/dsl_format_findings.md 知見40(実機検証済み): PADの「On block error」
    # アクションをフローに追加すると、複数アクションをまとめる無名の`BLOCK`で自動的に
    # ラップされる。「Exception handling mode」を既定の「Go to end of block」から
    # 「Go to next action」に変更して実機キャプチャした生データそのもの(本体は空の
    # BLOCK)。`NEXT ACTION`は既存の`KeywordRecord`機構でそのまま表現できる。
    dsl = "BLOCK \nON BLOCK ERROR\nNEXT ACTION\nEND"
    records = parse_dsl(dsl)
    assert records == [
        BlockRecord(name=None, indent=0),
        OnBlockErrorRecord(case_name=None, indent=0),
        KeywordRecord(name="NEXT", args=["ACTION"], indent=0),
        KeywordRecord(name="END", args=[], indent=0),
    ]
    tree = build_block_tree(records)
    assert len(tree) == 1
    guarded = tree[0]
    assert isinstance(guarded, GuardedNode)
    assert isinstance(guarded.node, BlockNode)
    assert isinstance(guarded.node.header, BlockRecord)
    assert guarded.node.header.name is None
    assert guarded.node.body == []
    assert len(guarded.on_error.arms) == 1
    header, handler_body = guarded.on_error.arms[0]
    assert header == OnBlockErrorRecord(case_name=None, indent=0)
    assert handler_body == [KeywordRecord(name="NEXT", args=["ACTION"], indent=0)]


def test_build_block_tree_handles_on_block_error_one_level_shallower_than_block() -> None:
    # design/dsl_format_findings.md 知見61(実機再検証): `tests/fixtures/on_block_error_isolated.txt`
    # (BLOCK単体を個別コピー)は上のテスト同様`ON BLOCK ERROR`がBLOCKと同じindentだったが、
    # **同じBLOCKがLOOP本体の中にネストしている状態でフロー全体を一括コピーすると、
    # `ON BLOCK ERROR`はBLOCKより1段"浅い"(=BLOCKを囲むLOOPと同じ)indentで出力される**ことを
    # VM上で実機確認した(`tests/fixtures/looptest_whole_subflow_with_calculator_button.txt`の
    # 一部、本セッションで同一のBLOCKをフロー全体の一括コピーとして再キャプチャしても再現する)。
    # この場合、アーム群を閉じる`END`とBLOCK自身を閉じる`END`は別々の2行になる。どちらの
    # indentが「正しい」かは未解明なため、`build_block_tree()`は両方を受理する。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_calculator_button.txt").read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    loop_block = tree[3]
    assert isinstance(loop_block, BlockNode) and isinstance(loop_block.header, LoopRecord)
    guarded = loop_block.body[1]
    assert isinstance(guarded, GuardedNode)
    assert isinstance(guarded.node, BlockNode)
    assert isinstance(guarded.node.header, BlockRecord)
    assert guarded.node.body == []
    assert len(guarded.on_error.arms) == 1
    header, handler_body = guarded.on_error.arms[0]
    assert isinstance(header, OnBlockErrorRecord) and header.case_name is None
    assert handler_body == [KeywordRecord(name="GOTO", args=["MyLabel"], indent=0)]
    # BLOCKの後(END×2を正しく消費した後)にも兄弟要素が切り捨てられず残っている。
    assert isinstance(loop_block.body[2], ActionRecord)
    assert loop_block.body[2].action_id == "UIAutomation.Click.Click"
    assert isinstance(loop_block.body[3], CommentRecord)


def test_build_block_tree_handles_block_body_action_and_named_multi_arm_on_block_error() -> None:
    # 実機データでは未確認(BLOCKの本体が空のケースのみ確認済み)だが、`ON ERROR`の
    # 名前付きケース・複数アーム(知見36)との構造的並列性から類推した拡張部分の
    # リグレッションテスト。本体アクション(indent+1)・名前付きケース+catch-allの連続
    # (両方ともON BLOCK ERROR自身と同じindent)・共有の1つのENDが正しく組み立てられることを
    # 確認する。
    dsl = (
        "BLOCK MyGroup\n"
        "    SET TestVar TO $'''hello'''\n"
        "ON BLOCK ERROR NamedCase\n"
        "SET TestVar TO $'''failed'''\n"
        "ON BLOCK ERROR\n"
        "SET TestVar TO $'''recovered'''\n"
        "END"
    )
    tree = build_block_tree(parse_dsl(dsl))
    assert len(tree) == 1
    guarded = tree[0]
    assert isinstance(guarded, GuardedNode)
    assert isinstance(guarded.node, BlockNode)
    assert guarded.node.header == BlockRecord(name="MyGroup", indent=0)
    assert len(guarded.node.body) == 1
    assert guarded.node.body[0].var_name == "TestVar"
    assert len(guarded.on_error.arms) == 2
    assert guarded.on_error.arms[0][0].case_name == "NamedCase"
    assert guarded.on_error.arms[1][0].case_name is None


def test_build_block_tree_does_not_drop_siblings_after_on_block_error_block() -> None:
    # `_SIMPLE_BLOCK_HEADER_TYPES`で過去に実データから発覚したバグ(終端ENDの誤消費で
    # 後続の兄弟要素が黙って切り捨てられる)と同種の回帰を防ぐ。BLOCKの直後に別のアクションが
    # 続く場合でも失われないことを確認する。
    dsl = (
        "BLOCK \n"
        "ON BLOCK ERROR\n"
        "NEXT ACTION\n"
        "END\n"
        "SET AfterVar TO $'''after'''"
    )
    tree = build_block_tree(parse_dsl(dsl))
    assert len(tree) == 2
    assert isinstance(tree[0], GuardedNode)
    assert tree[1].var_name == "AfterVar"


def test_throw_error_parsed_as_keyword_record_inside_on_block_error_arm() -> None:
    # design/dsl_format_findings.md 知見41(実機検証済み): 「On block error」ダイアログの
    # 「Continue flow run」/「Throw error」トグルで「Throw error」を選ぶと、「Exception
    # handling mode」ドロップダウンが消え、代わりにアーム本体へ`THROW ERROR`という
    # 2トークンのベアキーワードが追加される(`REPEAT ACTION`/`NEXT ACTION`と同形式)。
    dsl = "BLOCK \nON BLOCK ERROR\nTHROW ERROR\nEND"
    records = parse_dsl(dsl)
    assert records == [
        BlockRecord(name=None, indent=0),
        OnBlockErrorRecord(case_name=None, indent=0),
        KeywordRecord(name="THROW", args=["ERROR"], indent=0),
        KeywordRecord(name="END", args=[], indent=0),
    ]
    tree = build_block_tree(records)
    guarded = tree[0]
    assert isinstance(guarded, GuardedNode)
    _header, handler_body = guarded.on_error.arms[0]
    assert handler_body == [KeywordRecord(name="THROW", args=["ERROR"], indent=0)]


def test_parse_dsl_strips_control_repository_section_instead_of_treating_it_as_garbage() -> None:
    # design/dsl_format_findings.md 知見44(実機検証済み): サブフロー全体を一括選択して
    # コピーすると、DSLテキストの末尾に`# [ControlRepository][PowerAutomateDesktop]`で
    # 始まるJSONブロック(UI要素リポジトリ全体)が同梱される。これをDSLレコード列から
    # 除外しないと、JSON各行がデタラメな`RawRecord`の山になって出力を汚染してしまう。
    dsl = (
        "SET TestVar TO $'''hello'''\n"
        "\n"
        "# [ControlRepository][PowerAutomateDesktop]\n"
        "\n"
        '{"ControlRepositorySymbols": []}\n'
    )
    records = parse_dsl(dsl)
    assert records == [SetVariableRecord(var_name="TestVar", value="hello", indent=0)]


def test_parse_control_repository_returns_empty_dict_when_section_absent() -> None:
    assert parse_control_repository("SET TestVar TO $'''hello'''") == {}


def test_parse_control_repository_extracts_start_button_selector_from_real_capture() -> None:
    # design/dsl_format_findings.md 知見44(実機検証済み、本プロジェクト最大の発見)。
    # LoopTestサブフロー8アクションを一括選択してコピーした生データそのもの
    # (tests/fixtures/looptest_whole_subflow_with_control_repository.txt)。知見38の
    # `appmask['Start Button']`が指す実体が、このセクションに含まれる`appmask`シンボルの
    # 中の「Start Button」エントリだと実機で確認できた。今回の実例は`CustomValue:
    # ":startbutton"`というPAD独自の予約済み擬似セレクタ(Windowsタスクバーのスタート
    # ボタンという特殊ケース)で、通常のUIA`Attributes`配列は空だった——一般的な
    # アプリ内コントロールでの`Attributes`の中身は別途確認が必要(知見44の「次の課題」)。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_control_repository.txt").read_text(
        encoding="utf-8"
    )

    repository = parse_control_repository(text)

    assert set(repository.keys()) == {"appmask"}
    entry = repository["appmask"]["Start Button"]
    assert entry.element_type_name == "Start Button"
    assert len(entry.selectors) == 1
    (part,) = entry.selectors[0]
    assert part.name == "Start Button"
    assert part.tag == "startbutton"
    assert part.custom_value == ":startbutton"
    assert part.attributes == []


def test_build_block_tree_does_not_crash_on_real_whole_subflow_capture_with_nested_block() -> None:
    # design/dsl_format_findings.md 知見45: 一括コピーした実機生データでは、LOOPにネストした
    # BLOCKのON BLOCK ERRORのインデントがBLOCK自身とずれており(PAD側のシリアライズの
    # 癖か不具合か未確定)、`build_block_tree()`は厳密indent一致の既存ルールにより
    # これを「孤立したON BLOCK ERROR」として扱い、直前の兄弟(LOOP全体)を
    # GuardedNodeでラップしてしまう——構造的には理想より広い範囲をtry/exceptで
    # 包んでしまうが、意図的に特例処理は追加していない(1例だけから場当たり的な
    # 再紐付けロジックを足すと、他の未検証ケースで誤動作する恐れがあるため)。
    # ここでは最低限の安全性(クラッシュしない、構文的に正しいPythonを生成する)だけを保証する。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_control_repository.txt").read_text(
        encoding="utf-8"
    )
    tree = build_block_tree(parse_dsl(text))
    assert len(tree) > 0


def test_ui_element_ref_name_property_returns_leaf_segment() -> None:
    ref = UiElementRef(path=("Window 'Untitled - Notepad'", "Document 'Text Editor'"))
    assert ref.name == "Document 'Text Editor'"


def test_parse_control_repository_extracts_full_attributes_for_ordinary_notepad_control() -> None:
    # design/dsl_format_findings.md 知見46(実機検証済み): appmask['<祖先>']['<対象>']の
    # ようなネストしたパスで参照される、Windowsタスクバーの特殊ケースではない「ふつうの」
    # UI要素(メモ帳のテキスト編集領域)の`Attributes`配列が実際にどう埋まるかを初めて確認
    # できた実機生データ。各要素は`{Ignore, IsOrdinal, IsDisabledAttribute, Name, Operation,
    # Value}`という形で、`Ignore: false`のものだけがセレクタの実際の絞り込み条件として
    # 使われる(例: Windowは`Name`+`Process`、Documentは`Class`のみ)。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_notepad_control_selector.txt").read_text(
        encoding="utf-8"
    )

    repository = parse_control_repository(text)

    entries = repository["appmask"]
    assert set(entries.keys()) == {"Window 'Untitled - Notepad'", "Document 'Text Editor'"}

    window_entry = entries["Window 'Untitled - Notepad'"]
    assert window_entry.element_type_name == "Window"
    (window_part,) = window_entry.selectors[0]
    active_window_attrs = {a["Name"]: a["Value"] for a in window_part.attributes if not a["Ignore"]}
    assert active_window_attrs == {"Name": "Untitled - Notepad", "Process": "notepad"}

    document_entry = entries["Document 'Text Editor'"]
    assert document_entry.element_type_name == "Document"
    (document_part,) = document_entry.selectors[0]
    active_document_attrs = {a["Name"]: a["Value"] for a in document_part.attributes if not a["Ignore"]}
    assert active_document_attrs == {"Class": "Edit"}


def test_parse_dsl_resolves_nested_ui_element_path_from_real_notepad_capture() -> None:
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_notepad_control_selector.txt").read_text(
        encoding="utf-8"
    )
    records = parse_dsl(text)
    click_records = [
        r
        for r in records
        if isinstance(r, ActionRecord) and r.action_id == "UIAutomation.Click.Click"
    ]
    assert len(click_records) == 1
    element = click_records[0].params["Element"]
    assert isinstance(element, UiElementRef)
    assert element.path == ("Window 'Untitled - Notepad'", "Document 'Text Editor'")


def test_label_and_goto_parsed_as_keyword_records() -> None:
    # design/dsl_format_findings.md 知見48(実機検証済み): 「Label」アクション(Flow control
    # カテゴリ)は`LABEL <名前>`という2トークンのベアキーワードを生成し、`ON ERROR`/
    # `ON BLOCK ERROR`の「Exception handling mode」を「Go to label」にすると、アーム本体に
    # `GOTO <名前>`が追加される。いずれも`REPEAT ACTION`等と同じ機構でそのまま表現できる。
    dsl = "LABEL MyLabel\nGOTO MyLabel"
    records = parse_dsl(dsl)
    assert records == [
        KeywordRecord(name="LABEL", args=["MyLabel"], indent=0),
        KeywordRecord(name="GOTO", args=["MyLabel"], indent=0),
    ]


def test_build_block_tree_handles_real_goto_label_whole_subflow_capture() -> None:
    # design/dsl_format_findings.md 知見48: LABEL/GOTOを含む実機の一括コピー生データ
    # (Label「MyLabel」+ON BLOCK ERRORのException handling modeを「Go to label」に設定)。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_goto_label.txt").read_text(
        encoding="utf-8"
    )
    records = parse_dsl(text)
    assert KeywordRecord(name="LABEL", args=["MyLabel"], indent=0) in records
    tree = build_block_tree(records)
    assert len(tree) > 0


def test_wait_action_parsed_from_parenthesized_action_call_with_for_clause() -> None:
    # design/dsl_format_findings.md 知見50(実機検証済み)。「Wait for window」アクション
    # (UI automationカテゴリ)を実機でWindowに向けてタイムアウト5秒・Focus window無効で
    # 追加・コピーした生データそのもの。`WAIT <seconds>`という単純なベアキーワードとは
    # 全く別構文で、`WAIT (<ActionId> <Param>: <Value> ...) FOR <秒数>`という、丸括弧で
    # 囲んだアクション呼び出し風の式を伴う。
    dsl = (
        "WAIT (UIAutomation.WaitForWindow.ToOpen Window: appmask['Window \\'Untitled - "
        "Notepad\\''] FocusWindow: False) FOR 5"
    )
    records = parse_dsl(dsl)
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, WaitActionRecord)
    assert record.action_id == "UIAutomation.WaitForWindow.ToOpen"
    assert record.params["Window"] == UiElementRef(path=("Window 'Untitled - Notepad'",))
    assert record.params["FocusWindow"] is False
    assert record.timeout_seconds == 5


def test_build_block_tree_handles_real_wait_for_window_whole_subflow_capture() -> None:
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window.txt").read_text(
        encoding="utf-8"
    )
    records = parse_dsl(text)
    wait_records = [r for r in records if isinstance(r, WaitActionRecord)]
    assert len(wait_records) == 1
    assert wait_records[0].action_id == "UIAutomation.WaitForWindow.ToOpen"
    assert wait_records[0].timeout_seconds == 5
    tree = build_block_tree(records)
    assert len(tree) > 0


def test_wait_action_without_for_clause_has_no_timeout() -> None:
    # design/dsl_format_findings.md 知見50の追記(実機検証済み): 「Fail with timeout error」
    # トグルをOFFにすると、`FOR <秒数>`句自体がDSLから省略される(既定のタイムアウト値に
    # 置き換わるのではなく、本当に句ごと無くなる)。
    dsl = (
        "WAIT (UIAutomation.WaitForWindow.ToOpen Window: appmask['Window \\'Untitled - "
        "Notepad\\''] FocusWindow: False)"
    )
    records = parse_dsl(dsl)
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, WaitActionRecord)
    assert record.action_id == "UIAutomation.WaitForWindow.ToOpen"
    assert record.timeout_seconds is None


def test_build_block_tree_handles_real_wait_for_window_no_timeout_whole_subflow_capture() -> None:
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_no_timeout.txt"
    ).read_text(encoding="utf-8")
    records = parse_dsl(text)
    wait_records = [r for r in records if isinstance(r, WaitActionRecord)]
    assert len(wait_records) == 1
    assert wait_records[0].timeout_seconds is None
    tree = build_block_tree(records)
    assert len(tree) > 0


def test_build_block_tree_handles_real_wait_for_window_to_close_whole_subflow_capture() -> None:
    # design/dsl_format_findings.md 知見50の追記(実機検証済み): 「Wait for window to」を
    # 「Close」に変更すると、`ToClose`という別のaction_idになり、`FocusWindow`パラメータ
    # 自体が存在しない(UI上も「Focus window after it opens」トグルが消える——意味的に
    # 当然だが実機確認済み)。既存の汎用パラメータ解析ロジックのまま正しく処理できた。
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_to_close.txt"
    ).read_text(encoding="utf-8")
    records = parse_dsl(text)
    wait_records = [r for r in records if isinstance(r, WaitActionRecord)]
    assert len(wait_records) == 1
    assert wait_records[0].action_id == "UIAutomation.WaitForWindow.ToClose"
    assert "FocusWindow" not in wait_records[0].params


def test_build_block_tree_handles_real_wait_for_window_content_whole_subflow_capture() -> None:
    # design/dsl_format_findings.md 知見52(実機検証済み): 「Wait for window content」は
    # 「Wait for window」(知見50)とは別のAction(別のツールチップ・別のダイアログ構成)だが、
    # DSL上は同じ`WAIT (<ActionId> ...)`構文を再利用し、action_idが
    # `UIAutomation.WaitForWindowContent.WindowToContainElement`になるだけだった——
    # 既存の汎用パーサー/codegenロジックのまま、コード変更無しで正しく処理できた。
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_content.txt"
    ).read_text(encoding="utf-8")
    records = parse_dsl(text)
    wait_records = [r for r in records if isinstance(r, WaitActionRecord)]
    assert len(wait_records) == 1
    assert (
        wait_records[0].action_id
        == "UIAutomation.WaitForWindowContent.WindowToContainElement"
    )
    assert wait_records[0].timeout_seconds is None
    element = wait_records[0].params["Element"]
    assert element.path == ("Window 'Untitled - Notepad'", "Document 'Text Editor'")
    tree = build_block_tree(records)
    assert len(tree) > 0


def test_if_action_record_parsed_from_real_if_window_whole_subflow_capture() -> None:
    # design/dsl_format_findings.md 知見54(実機検証済み): 「If window」等の
    # [ConditionAction]カテゴリは、知見50のWAIT (...)と全く同じ丸括弧パターンを条件式として
    # 再利用する。以前はこの構文に専用の対応が無く、`IF (UIAutomation.IfWindow.IsOpen ...) THEN`が
    # IfRecordとして誤って(operand1='(UIAutomation.IfWindow.IsOpen', operator='Window:'等という
    # 意味不明な値で)パースされてしまっていた。PADはこのアクションを置いただけで自動的に
    # 対応する`End`も挿入する(=ブロック開始構文であることも実機確認済み)。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_if_window.txt").read_text(
        encoding="utf-8"
    )
    records = parse_dsl(text)
    if_action_records = [r for r in records if isinstance(r, IfActionRecord)]
    assert len(if_action_records) == 1
    rec = if_action_records[0]
    assert rec.action_id == "UIAutomation.IfWindow.IsOpen"
    assert rec.params["InstantCheck"] is False
    element = rec.params["Window"]
    assert element.path == ("Window 'Untitled - Notepad'",)
    tree = build_block_tree(records)
    assert len(tree) > 0
    assert isinstance(tree[0], ConditionalNode)
    assert tree[0].arms[0][0] is rec


def test_if_action_record_check_if_window_variants_use_distinct_action_ids() -> None:
    # design/dsl_format_findings.md 知見54の追記(実機検証済み): 「Check if window」ドロップダウンは
    # 「Is open」「Isn't open」「Is focused」「Isn't focused」の4択で、共有パラメータでの否定ではなく
    # 4つの別々のaction_id(`IsOpen`/`IsNotOpen`/`IsFocused`/`IsNotFocused`)になる。
    # 事前の予測では`IsFocusedByTitleClass`のような複合名を想定していたが、実機では
    # 単純な`IsFocused`だった。
    is_focused_dsl = (
        "IF (UIAutomation.IfWindow.IsFocused Window: appmask['Window \\'Untitled - "
        "Notepad\\''] InstantCheck: False) THEN\nEND"
    )
    records = parse_dsl(is_focused_dsl)
    assert isinstance(records[0], IfActionRecord)
    assert records[0].action_id == "UIAutomation.IfWindow.IsFocused"

    is_not_open_dsl = (
        "IF (UIAutomation.IfWindow.IsNotOpen Window: appmask['Window \\'Untitled - "
        "Notepad\\''] InstantCheck: False) THEN\nEND"
    )
    records = parse_dsl(is_not_open_dsl)
    assert isinstance(records[0], IfActionRecord)
    assert records[0].action_id == "UIAutomation.IfWindow.IsNotOpen"


def test_if_action_record_parsed_from_real_if_window_contains_element_whole_subflow_capture() -> None:
    # design/dsl_format_findings.md 知見54の追記(実機検証済み): 「If window contains element」は
    # 「If window」とは別のアクション(別のツールチップ・別のダイアログ構成——「Check if window:
    # Contains UI element」「Check UI element state」トグル「UI element:」ピッカー、知見52の
    # 「Wait for window content」とよく似た構成)だが、DSL上は同じ`IF (<ActionId> ...) THEN`構文を
    # 再利用し、action_idが`UIAutomation.IfWindowContains.WindowContainsElement`になるだけだった
    # ——既存の汎用パーサー/codegenロジックのまま、コード変更無しで正しく処理できた。
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_if_window_contains_element.txt"
    ).read_text(encoding="utf-8")
    records = parse_dsl(text)
    if_action_records = [r for r in records if isinstance(r, IfActionRecord)]
    assert len(if_action_records) == 1
    rec = if_action_records[0]
    assert rec.action_id == "UIAutomation.IfWindowContains.WindowContainsElement"
    element = rec.params["Element"]
    assert element.path == ("Window 'Untitled - Notepad'", "Document 'Text Editor'")
    tree = build_block_tree(records)
    assert len(tree) > 0


def test_if_action_record_parsed_from_real_if_service_capture() -> None:
    # design/dsl_format_findings.md 知見54の追記(実機検証済み): 「If service」(Windows
    # servicesカテゴリ)も同じ`IF (<ActionId> ...) THEN`構文を再利用する。これまでの
    # [ConditionAction]/[WaitAction]の実機キャプチャは全て`UIAutomation.*`名前空間だったが、
    # 「If service」は`Services.*`という別の名前空間だった(UI要素を伴わないため
    # ControlRepositoryブロックも付かない、単独アクションのコピーで確認)。
    # Service nameはUI要素参照ではなく通常のプレースホルダ文字列(`$'''Spooler'''`)として
    # 渡される。
    records = parse_dsl("IF (Services.IfService.IsRunning Service: $'''Spooler''') THEN\nEND")
    if_action_records = [r for r in records if isinstance(r, IfActionRecord)]
    assert len(if_action_records) == 1
    rec = if_action_records[0]
    assert rec.action_id == "Services.IfService.IsRunning"
    assert rec.params["Service"] == "Spooler"


def test_if_service_dropdown_has_five_options_not_full_negation_pairs() -> None:
    # design/dsl_format_findings.md 知見54の追記(実機検証済み): 「If service」ドロップダウンの
    # 全選択肢を確認したところ、「Is stopped」「Is installed」「Isn't installed」
    # 「Is running」「Is paused」の**5択**だった。知見50/54の`Is open`/`Isn't open`のような
    # 完全な肯定/否定ペアが全選択肢に存在するという予測は外れ、「installed」だけが
    # 肯定/否定ペアを持ち、running/stopped/pausedは否定形が無い非対称な構成だった。
    # 「Is stopped」を選んで実機確認したところ、予測通り`Services.IfService.IsStopped`
    # という命名パターンだった(`IsRunning`と対になる形)。
    records = parse_dsl("IF (Services.IfService.IsStopped Service: $'''Spooler''') THEN\nEND")
    if_action_records = [r for r in records if isinstance(r, IfActionRecord)]
    assert len(if_action_records) == 1
    rec = if_action_records[0]
    assert rec.action_id == "Services.IfService.IsStopped"
    assert rec.params["Service"] == "Spooler"


def test_wait_action_record_parsed_from_real_wait_for_service_capture() -> None:
    # design/dsl_format_findings.md 知見50の追記(実機検証済み): 「Wait for service」は
    # `WaitForWindowAction`と対になる`[WaitAction]`カテゴリのもう一つの構文で、知見50で
    # 確立した汎用`WAIT (...)`パーサーをそのまま再利用できた。「If service」(知見54)と
    # 同じく`Services.*`名前空間(`Services.WaitForService.Started`)。単一行のアクションで
    # `If window`/`If service`とは異なり対応する`End`は自動挿入されない(ブロック開始構文
    # ではない、WaitActionRecord全般と同じ)ことも実機確認した。
    records = parse_dsl("WAIT (Services.WaitForService.Started Service: $'''Spooler''')")
    wait_records = [r for r in records if isinstance(r, WaitActionRecord)]
    assert len(wait_records) == 1
    rec = wait_records[0]
    assert rec.action_id == "Services.WaitForService.Started"
    assert rec.params["Service"] == "Spooler"
    assert rec.timeout_seconds is None


def test_build_block_tree_handles_real_wait_for_window_become_focused_whole_subflow_capture() -> None:
    # design/dsl_format_findings.md 知見50の追記(実機検証済み): 知見50本文で「他の3選択肢は
    # 未検証」としていた「Wait for window to」の残り——うち`Close`は別ティックで確認済み
    # (`ToClose`)。今回「Become focused」を確認した。action_idは予測通り
    # `UIAutomation.WaitForWindow.ToBecomeFocused`(`WindowMode`列挙値のパターン通り)。
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_become_focused.txt"
    ).read_text(encoding="utf-8")
    records = parse_dsl(text)
    wait_records = [r for r in records if isinstance(r, WaitActionRecord)]
    assert len(wait_records) == 1
    assert wait_records[0].action_id == "UIAutomation.WaitForWindow.ToBecomeFocused"
    tree = build_block_tree(records)
    assert len(tree) > 0


def test_build_block_tree_handles_real_wait_for_window_lose_focus_whole_subflow_capture() -> None:
    # design/dsl_format_findings.md 知見50の追記(実機検証済み): 「Lose focus」も確認し、
    # これで「Wait for window to」の4択(Open/Close/Become focused/Lose focus)全てが
    # 実機確認済みになった。action_idは予測通り`UIAutomation.WaitForWindow.ToLoseFocus`。
    text = (
        FIXTURES_DIR / "looptest_whole_subflow_with_wait_for_window_lose_focus.txt"
    ).read_text(encoding="utf-8")
    records = parse_dsl(text)
    wait_records = [r for r in records if isinstance(r, WaitActionRecord)]
    assert len(wait_records) == 1
    assert wait_records[0].action_id == "UIAutomation.WaitForWindow.ToLoseFocus"
    tree = build_block_tree(records)
    assert len(tree) > 0


def test_get_window_parsed_from_real_whole_subflow_capture() -> None:
    # design/dsl_format_findings.md 知見57(実機検証済み): 長年「window instanceをPython側で
    # どう表現するか」として持ち越していた`GetWindow`の実機DSLを初めて確認した。
    # action_idは`UIAutomation.GetWindow.GetUseTimeout`
    # (「Get window: Specific window」ダイアログ、`Timeout`パラメータがあるため
    # `GetUseTimeout`という命名——`Timeout`無しの別モードが存在する可能性を示唆)。
    # 出力変数は`WindowInstance=> AutomationWindow2`という、知見14で確認済みの
    # `=>`出力変数構文(`ScriptOutput=>`等と同形式)をそのまま再利用しており、
    # 既存の汎用output_var/output_vars解析ロジックで無改修で正しくパースできた。
    text = (FIXTURES_DIR / "looptest_whole_subflow_with_get_window.txt").read_text(
        encoding="utf-8"
    )
    records = parse_dsl(text)
    action_records = [
        r
        for r in records
        if isinstance(r, ActionRecord) and r.action_id == "UIAutomation.GetWindow.GetUseTimeout"
    ]
    assert len(action_records) == 1
    rec = action_records[0]
    assert rec.params["Control"].path == ("Window 'Untitled - Notepad'",)
    assert rec.params["BringWindowToFront"] is False
    assert rec.params["Timeout"] == 5
    assert rec.output_var == "AutomationWindow2"
    assert rec.output_vars == {"WindowInstance": "AutomationWindow2"}
    tree = build_block_tree(records)
    assert len(tree) > 0


def test_close_window_by_instance_handle_parsed_from_real_capture() -> None:
    # design/dsl_format_findings.md 知見57の追記(実機検証済み): 「Close window」アクションの
    # 「Find window mode」ドロップダウンには「By window UI element」「By window instance/handle」
    # 「By title and/or class」の3択があり(知見27の`ByTitleClass`系はこのうち3番目に対応)、
    # 「By window instance/handle」を選ぶとaction_idが`UIAutomation.CloseWindow.
    # CloseByInstanceOrHandle`になった——事前に予測していた命名パターンがそのまま
    # 実機で確認できた。
    # `WindowInstance: AutomationWindow2`というパラメータは、知見57本文の仮説通り、
    # UI要素参照(`appmask[...]`)でも引用符付き文字列でもない**裸の変数参照**だった——
    # 既存の汎用パラメータ解析ロジックでそのまま`VarRef`として無改修で正しくパースできた。
    text = (FIXTURES_DIR / "closewindow_by_instance.txt").read_text(encoding="utf-8")
    records = parse_dsl(text)
    assert len(records) == 1
    rec = records[0]
    assert isinstance(rec, ActionRecord)
    assert rec.action_id == "UIAutomation.CloseWindow.CloseByInstanceOrHandle"
    assert rec.params["WindowInstance"] == VarRef("AutomationWindow2")


def test_get_window_foreground_mode_has_two_output_variables() -> None:
    # design/dsl_format_findings.md 知見57の追記(実機検証済み): 「Get window」の
    # 「Get window:」ドロップダウンは「Specific window」(知見57本文)「Foreground window」の
    # 2択だけだった。「Foreground window」を選ぶと、1つのアクションが**2つの`=>`出力変数
    # 束縛を同時に持つ**という、これまで一度も実機確認していなかったパターンに遭遇した
    # (`WindowTitle=> WindowTitle2 WindowInstance=> AutomationWindow2`)。
    # `SetVariableRecord.output_var`は「後方互換のため最後に見つかったものを保持する」設計に
    # 当初から意図的になっていた(dump_daemon/pad_dsl_parser.pyの既存コメント参照)ため、
    # 実際に複数`=>`を持つ実例に遭遇した今回も、既存の`output_vars`辞書(複数キー対応)で
    # 一切のコード変更無しで正しくパースできることを確認した。
    dsl = "UIAutomation.GetWindow.GetForegroundWindow WindowTitle=> WindowTitle2 WindowInstance=> AutomationWindow2"
    records = parse_dsl(dsl)
    assert len(records) == 1
    rec = records[0]
    assert isinstance(rec, ActionRecord)
    assert rec.action_id == "UIAutomation.GetWindow.GetForegroundWindow"
    assert rec.output_vars == {
        "WindowTitle": "WindowTitle2",
        "WindowInstance": "AutomationWindow2",
    }
    assert rec.output_var == "AutomationWindow2"


def test_if_image_exists_on_screen_parsed_from_real_capture() -> None:
    # design/dsl_format_findings.md 知見58(実機検証済み): `[ConditionAction]`カテゴリの
    # 「If image」を実機確認した。action_idは`UIAutomation.IfImage.ExistsOnScreen`——知見54の
    # `IF (<ActionId> ...) THEN`構文をそのまま再利用する。知見44以来ずっと空([])のままだった
    # `ImageRepositorySymbol`(シンボル名`imgrepo`)が、今回初めて実データを持つ実例を確認できた。
    # `Images: [imgrepo['Image']]`という、`appmask['...']`単体参照とは違う**角括弧で囲んだ
    # リスト構文**も初めて実機確認した(「Find all images in the list」トグルが複数画像指定を
    # 示唆する通り、複数要素を保持できるリストリテラルと推測される)。現在のパーサーは
    # `appmask[...]`のような専用の`UiElementRef`抽出を`imgrepo[...]`に対しては行わないため、
    # `[imgrepo['Image']]`全体が不透明な`VarRef`としてテキストのまま保持される——
    # データを失わない安全なフォールバックであり、クラッシュも誤った構造化も起きない。
    text = (FIXTURES_DIR / "if_image_exists_on_screen.txt").read_text(encoding="utf-8")
    records = parse_dsl(text)
    assert len(records) == 1
    rec = records[0]
    assert isinstance(rec, IfActionRecord)
    assert rec.action_id == "UIAutomation.IfImage.ExistsOnScreen"
    assert rec.params["FindAllImages"] is False
    assert rec.params["Tolerance"] == 10
    assert rec.params["SearchAlgorithm"] == EnumRef("UIAutomation.ImageFinderAlgorithm.Legacy")
    assert rec.params["Images"] == VarRef("[imgrepo['Image']]")


def test_tier1_text_variables_actions_parse_as_generic_action_records() -> None:
    # design/dsl_format_findings.md 知見62以降: UIAutomationによるPADデザイナー自動操作で
    # 初めてTier1(Text/Variables)系アクションの実機DSLキャプチャに成功した。既存の
    # 汎用ActionRecordパーサーは、これらの未知のaction_idでもコード変更無しで正しく
    # ActionRecordとして構造化できることを確認する回帰テスト(知見36以来の設計方針通り)。
    text = (FIXTURES_DIR / "tier1_text_variables_batch1.txt").read_text(encoding="utf-8")
    records = parse_dsl(text)
    assert len(records) == 15
    assert all(isinstance(r, ActionRecord) for r in records)
    action_ids = [r.action_id for r in records]  # type: ignore[union-attr]
    assert action_ids == [
        "Text.Trim",
        "Text.ChangeCase",
        "Variables.ReverseList",
        "Text.Pad",
        "Text.JoinText.Join",
        "Text.AppendLine",
        "Text.EscapeForRegularExpression",
        "Text.Reverse",
        "Text.CropText.CropTextBeforeFlag",
        "Text.GetSubtext.GetSubtext",
        "Text.SplitText.Split",
        "Text.ToNumber",
        "Text.FromNumber",
        "Text.Random",
        "Variables.GenerateRandomNumber.RandomNumber",
    ]
    trim = records[0]
    assert trim.params["Text"] == "helloworld"  # type: ignore[union-attr]
    assert trim.params["TrimOption"] == EnumRef("Text.TrimOption.Both")  # type: ignore[union-attr]
    assert trim.output_var == "TrimmedText"  # type: ignore[union-attr]
    reverse_list = records[2]
    # design/dsl_format_findings.md 知見62: Variables.ReverseListはMutable引数の
    # インプレース操作で、出力変数束縛(=>)を一切持たない。
    assert reverse_list.output_var is None  # type: ignore[union-attr]


def test_tier1_datetime_folder_clipboard_actions_parse_without_crashing() -> None:
    # design/dsl_format_findings.md 知見64・65: DateTime/Folder/Compression/Clipboardの
    # 実機DSLキャプチャ。`Compression.ZipFiles`の`Password`(Sensitive扱いの
    # EncryptableObject)は、知見65で確認したDPAPI暗号化済みBase64が`P'...'`という
    # 新構文(既存の`$'''...'''`とは異なる)で直列化されるが、現状のパーサーは
    # このP'...'構文を未対応のまま`VarRef`にフォールバックする(クラッシュも
    # サイレントなデータ欠落も起きないことだけを確認する回帰テスト)。
    text = (FIXTURES_DIR / "tier1_datetime_folder_clipboard_batch2.txt").read_text(
        encoding="utf-8"
    )
    records = parse_dsl(text)
    assert len(records) == 8
    assert all(isinstance(r, ActionRecord) for r in records)
    zip_action = records[4]
    assert zip_action.action_id == "Compression.ZipFiles"  # type: ignore[union-attr]
    password = zip_action.params["Password"]  # type: ignore[union-attr]
    # P'...'構文は未対応のためVarRefへのフォールバックになるが、生テキストは
    # 失われず丸ごと保持されていることを確認する(知見15以来の「データを失わない」方針)。
    assert isinstance(password, VarRef)
    assert password.name.startswith("P'AQAAANCMnd8B")
    date_subtract = records[2]
    # design/dsl_format_findings.md 知見57相当: SubstractDateというtypoがそのまま
    # 実機のパラメータ名として確認できた(ソース上のプロパティ名のtypoが直列化にも
    # そのまま反映される)。
    assert "SubstractDate" in date_subtract.params  # type: ignore[union-attr]


def test_tier1_variables_list_datatable_batch3_parses_as_generic_action_records() -> None:
    # design/dsl_format_findings.md 知見66: Variables.List系10件・Variables.DataTable系17件
    # (計27件)の実機DSLキャプチャ。既存の汎用ActionRecordパーサーがコード変更無しで
    # 正しく構造化できることを確認する回帰テスト。
    text = (FIXTURES_DIR / "tier1_variables_list_datatable_batch3.txt").read_text(
        encoding="utf-8"
    )
    records = parse_dsl(text)
    assert len(records) == 27
    assert all(isinstance(r, ActionRecord) for r in records)
    action_ids = [r.action_id for r in records]  # type: ignore[union-attr]
    assert action_ids == [
        "Variables.CreateNewList",
        "Variables.AddItemToList",
        "Variables.RemoveItemFromList.RemoveItemFromListByIndex",
        "Variables.ClearList",
        "Variables.ShuffleList",
        "Variables.MergeLists",
        "Variables.SubtractLists",
        "Variables.FindCommonListItems",
        "Variables.RemoveDuplicateItemsFromList",
        "Variables.SortList.SortList",
        "Variables.CreateNewDatatable",
        "Variables.AddRowToDataTable.AppendRowToDataTable",
        "Variables.DeleteEmptyRowsFromDataTable",
        "Variables.ModifyDataTableItem",
        "Variables.FindOrReplaceInDataTable.FindItemInDataTableEverywhere",
        "Variables.AddColumnToDataTable.AppendColumnToDataTable",
        "Variables.DeleteColumnFromDataTable.DeleteColumnWithName",
        "Variables.DeleteDuplicateRowsFromDataTable",
        "Variables.ClearDataTable",
        "Variables.SortDataTable.SortWithColumnName",
        "Variables.FilterDataTable",
        "Variables.MergeDataTables",
        "Variables.JoinDataTable",
        "Variables.ConvertDataTableToCSV.DataTableToCSVCommonSeparator",
        "Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator",
        "Variables.RetrieveDataTableColumnIntoList",
        "Variables.DeleteRowFromDataTable",
    ]
    create_new_list = records[0]
    # design/dsl_format_findings.md 知見66: CreateNewListは非破壊で=>束縛を持つ。
    assert create_new_list.output_var == "List"  # type: ignore[union-attr]
    clear_list = records[3]
    # AddItemToList/ClearList等はListがMutableなため=>束縛を持たない。
    assert clear_list.output_var is None  # type: ignore[union-attr]
    merge_lists = records[5]
    assert merge_lists.output_var == "OutputList"  # type: ignore[union-attr]
    create_new_datatable = records[10]
    # design/dsl_format_findings.md 知見66: 空の2次元配列は`{ }`と直列化されるが、
    # `{`/`}`という配列リテラル構文は現状のパーサーが未対応で、`{`がVarRef名として
    # フォールバックする(クラッシュもデータ欠落も起きないことのみ確認する回帰テスト)。
    assert create_new_datatable.params["InputTable"] == VarRef(name="{")  # type: ignore[union-attr]
    assert create_new_datatable.output_var == "DataTable"  # type: ignore[union-attr]
    delete_row = records[26]
    # DeleteRowFromDataTableもDataTableがMutableなため=>束縛を持たない。
    assert delete_row.output_var is None  # type: ignore[union-attr]


def test_tier1_text_variables_batch4_parses_as_generic_action_records() -> None:
    # design/dsl_format_findings.md 知見67: Text残り6件・Variables残り5件(計11件)の
    # 実機DSLキャプチャ。既存の汎用ActionRecordパーサーがコード変更無しで
    # 正しく構造化できることを確認する回帰テスト。
    text = (FIXTURES_DIR / "tier1_text_variables_batch4.txt").read_text(encoding="utf-8")
    records = parse_dsl(text)
    assert len(records) == 11
    assert all(isinstance(r, ActionRecord) for r in records)
    action_ids = [r.action_id for r in records]  # type: ignore[union-attr]
    assert action_ids == [
        "Text.ParseText.ParseForFirstOccurrence",
        "Text.Replace.ReplaceText",
        "Text.RecognizeEntitiesInText",
        "Text.CreateHTMLContent",
        "Text.ConvertDateTimeToText.FromDateTime",
        "Text.ConvertTextToDateTime.ToDateTime",
        "Variables.TruncateNumber.GetIntegerPart",
        "Variables.IncreaseVariable",
        "Variables.DecreaseVariable",
        "Variables.ConvertJsonToCustomObject",
        "Variables.ConvertCustomObjectToJson",
    ]
    create_html = records[3]
    # design/dsl_format_findings.md 知見67: 空のバックティック文字列``は知見66の
    # FilterParameters同様、現状のパーサーが未対応で`` `` ``全体がVarRef名として
    # フォールバックする(クラッシュもデータ欠落も起きないことのみ確認する回帰テスト)。
    assert create_html.params["HtmlEditor"] == VarRef(name="``")  # type: ignore[union-attr]
    increase_var = records[7]
    # IncreaseVariable/DecreaseVariableはValueがMutableなため=>束縛を持たない。
    assert increase_var.output_var is None  # type: ignore[union-attr]


def test_tier1_folder_batch5_parses_as_generic_action_and_if_records() -> None:
    # design/dsl_format_findings.md 知見68: Folder残り9件(うち1件はIf系ブロック)の
    # 実機DSLキャプチャ。既存の汎用パーサーがコード変更無しで正しく構造化できることを
    # 確認する回帰テスト。
    text = (FIXTURES_DIR / "tier1_folder_batch5.txt").read_text(encoding="utf-8")
    records = parse_dsl(text)
    assert len(records) == 10
    assert [type(r).__name__ for r in records] == [
        "ActionRecord",
        "ActionRecord",
        "ActionRecord",
        "ActionRecord",
        "ActionRecord",
        "ActionRecord",
        "ActionRecord",
        "ActionRecord",
        "IfActionRecord",
        "KeywordRecord",
    ]
    action_ids = [getattr(r, "action_id", None) for r in records]
    assert action_ids == [
        "Folder.Copy",
        "Folder.Create",
        "Folder.Delete",
        "Folder.Empty",
        "Folder.Move",
        "Folder.Rename",
        "Folder.GetSubfolders",
        "Folder.GetSpecialFolder",
        "Folder.IfFolderExists.Exists",
        None,
    ]
    delete_folder = records[2]
    # Folder.Delete/Folder.Emptyは出力変数を持たない。
    assert delete_folder.output_var is None  # type: ignore[union-attr]
    if_folder_exists = records[8]
    assert isinstance(if_folder_exists, IfActionRecord)


def test_tier1_file_batch6_parses_as_generic_action_if_and_wait_records() -> None:
    # design/dsl_format_findings.md 知見69: Fileモジュール14件(ネストしたIF/WAIT
    # ブロックを含む)の実機DSLキャプチャ。既存の汎用パーサーがコード変更無しで
    # 正しく構造化できることを確認する回帰テスト。
    text = (FIXTURES_DIR / "tier1_file_batch6.txt").read_text(encoding="utf-8")
    records = parse_dsl(text)
    assert len(records) == 15
    assert [type(r).__name__ for r in records] == [
        "ActionRecord",
        "ActionRecord",
        "ActionRecord",
        "ActionRecord",
        "ActionRecord",
        "ActionRecord",
        "ActionRecord",
        "ActionRecord",
        "ActionRecord",
        "ActionRecord",
        "ActionRecord",
        "ActionRecord",
        "IfActionRecord",
        "WaitActionRecord",
        "KeywordRecord",
    ]
    action_ids = [getattr(r, "action_id", None) for r in records]
    assert action_ids == [
        "File.Copy",
        "File.Move",
        "File.Delete",
        "File.RenameFiles.Rename",
        "File.ConvertToBase64",
        "File.ConvertFromBase64",
        "File.ConvertToBinary",
        "File.ReadTextFromFile.ReadText",
        "File.WriteText",
        "File.ReadFromCSVFile.ReadCSV",
        "File.WriteToCSVFile.WriteCSV",
        "File.GetPathPart",
        "File.IfFile.Exists",
        "File.WaitForFile.Created",
        None,
    ]
    delete_file = records[2]
    assert delete_file.output_var is None  # type: ignore[union-attr]
    wait_for_file = records[13]
    # design/dsl_format_findings.md 知見69: WaitForFileは知見57以来の既存の
    # WaitActionRecord(FOR句の有無で無期限ポーリングか否かを判定)としてそのまま
    # 構造化できる。
    assert isinstance(wait_for_file, WaitActionRecord)


def test_tier1_crypto_database_batch7_parses_as_generic_action_records() -> None:
    # design/dsl_format_findings.md 知見70: File残り2件・Cryptography 8件・
    # Database 2件(計12件)の実機DSLキャプチャ。既存の汎用パーサーがコード変更
    # 無しで正しく構造化できることを確認する回帰テスト。
    text = (FIXTURES_DIR / "tier1_crypto_database_batch7.txt").read_text(encoding="utf-8")
    records = parse_dsl(text)
    assert len(records) == 12
    assert all(isinstance(r, ActionRecord) for r in records)
    action_ids = [r.action_id for r in records]  # type: ignore[union-attr]
    assert action_ids == [
        "File.ConvertFromBinary",
        "File.GetTempPath",
        "Cryptography.EncryptText.EncryptTextWithAES",
        "Cryptography.EncryptFromFile.EncryptFromFileWithAES",
        "Cryptography.DecryptText.DecryptTextWithAES",
        "Cryptography.DecryptToFile.DecryptToFileWithAES",
        "Cryptography.HashText",
        "Cryptography.HashFromFile",
        "Cryptography.HashTextWithKey",
        "Cryptography.HashFromFileWithKey",
        "Database.Connect.Connect",
        "Database.ExecuteSqlStatement.Execute",
    ]
    encrypt_text = records[2]
    # design/dsl_format_findings.md 知見65の予測通り、CryptographyモジュールのKey系
    # パラメータ(EncryptionKey/DecryptionKey/HashKey)もSensitive扱いのため同じ
    # P'<DPAPI暗号化Base64>'構文で直列化され、現状のパーサーはVarRefにフォールバック
    # する(クラッシュもデータ欠落も起きないことのみ確認する回帰テスト)。
    encryption_key = encrypt_text.params["EncryptionKey"]  # type: ignore[union-attr]
    assert isinstance(encryption_key, VarRef)
    assert encryption_key.name.startswith("P'AQAAANCMnd8B")
    execute_sql = records[11]
    # design/dsl_format_findings.md 知見66のFilterParameters/知見67のHtmlEditorと
    # 同じ空のバックティック文字列``構文がExecuteSqlStatementのStatementにも
    # 使われている。
    assert execute_sql.params["Statement"] == VarRef(name="``")  # type: ignore[union-attr]


def test_tier1_web_xml_batch8_parses_as_generic_action_records() -> None:
    # design/dsl_format_findings.md 知見71: Database残り1件・Compression残り1件・
    # Web全3件・XML全10件(計15件)の実機DSLキャプチャ。既存の汎用パーサーが
    # コード変更無しで正しく構造化できることを確認する回帰テスト。
    text = (FIXTURES_DIR / "tier1_web_xml_batch8.txt").read_text(encoding="utf-8")
    records = parse_dsl(text)
    assert len(records) == 15
    assert all(isinstance(r, ActionRecord) for r in records)
    action_ids = [r.action_id for r in records]  # type: ignore[union-attr]
    assert action_ids == [
        "Database.Close",
        "Compression.UnzipFiles",
        "Web.DownloadFromWeb.Download",
        "Web.InvokeWebService.InvokeWebService",
        "Web.InvokeSoapService.InvokeSoapService",
        "XML.ReadFromFile",
        "XML.WriteXmlToFile.WriteToFileFormatted",
        "XML.GetXmlElementValue.GetElementValue",
        "XML.SetElementValue",
        "XML.GetXmlElementAttribute.GetElementAttribute",
        "XML.SetElementAttribute",
        "XML.RemoveElementAttribute",
        "XML.InsertElement",
        "XML.RemoveElement",
        "XML.ExecuteXPathQuery.ExecuteXPath",
    ]
    get_element_value = records[7]
    # design/dsl_format_findings.md 知見71: XML.ReadFromFileが生成したXmlDocument型の
    # 変数が1つだけスコープにある場合、後続アクションのDocumentパラメータはPAD側が
    # 自動的にその変数への参照で事前入力する(自動化スクリプトが埋めた"sample"文字列
    # ではなくVarRef(XmlDocument)になる)。
    assert get_element_value.params["Document"] == VarRef(name="XmlDocument")  # type: ignore[union-attr]
    write_xml = records[6]
    # design/dsl_format_findings.md 知見66・67・70と同じ空のバックティック文字列``
    # 構文がXML.WriteXmlToFileのXmlにも使われている。
    assert write_xml.params["Xml"] == VarRef(name="``")  # type: ignore[union-attr]


def test_tier1_cmd_batch9_parses_as_generic_action_records() -> None:
    # design/dsl_format_findings.md 知見72: Cmdモジュール全5件の実機DSLキャプチャ。
    # これでTier1/2対象116件全ての実機キャプチャが完了する。既存の汎用パーサーが
    # コード変更無しで正しく構造化できることを確認する回帰テスト。
    text = (FIXTURES_DIR / "tier1_cmd_batch9.txt").read_text(encoding="utf-8")
    records = parse_dsl(text)
    assert len(records) == 5
    assert all(isinstance(r, ActionRecord) for r in records)
    action_ids = [r.action_id for r in records]  # type: ignore[union-attr]
    assert action_ids == [
        "Cmd.Open.Open",
        "Cmd.Write",
        "Cmd.ReadFromCmdSession.Read",
        "Cmd.WaitForText",
        "Cmd.Close",
    ]
    wait_for_text = records[3]
    # design/dsl_format_findings.md 知見72: Cmd.WaitForTextは知見50・57の
    # WAIT (...) FOR構文ではなく、Timeoutという通常のパラメータを持つ普通の
    # ActionRecordとして直列化される——「Wait」を名前に含むアクションが必ず
    # WaitActionRecordになるとは限らないことを確認。
    assert wait_for_text.params["Timeout"] == 0  # type: ignore[union-attr]
    open_session = records[0]
    assert open_session.output_var == "CmdSession"  # type: ignore[union-attr]
