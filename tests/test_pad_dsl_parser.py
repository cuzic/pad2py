"""pad_dsl_parser の単体テスト。

フィクスチャは design/dsl_format_findings.md に記録した、g1g2_testフローを
実機PADから「コピー&ペースト」で実際にエクスポートした生データそのもの。
"""
from __future__ import annotations

from dump_daemon.pad_dsl_parser import (
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
    SetVariableRecord,
    SwitchNode,
    SwitchRecord,
    UiElementRef,
    VarRef,
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
    # design/robin_language_source_findings.md: Robin.Language.dllの
    # CommentStatement.ToString()のソースコードで確認した構文(実機未確認)。
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
    # design/robin_language_source_findings.md: StringExtensions.EscapeForRobin()が
    # `"`/`'`/`\`の3種類すべてにバックスラッシュを前置することをソースで確認した。
    # 以前は`\"`と`\\`しか解除しておらず、アポストロフィを含む英語テキスト
    # (例: "it's")がPADのDSL上では`it\'s`になるため、バックスラッシュが残留する
    # サイレントなバグがあった。
    records = parse_dsl("SET TestVar TO $'''it\\'s a test'''")
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, SetVariableRecord)
    assert record.value == "it's a test"


def test_doubled_percent_in_string_literal_is_unescaped() -> None:
    # design/robin_language_source_findings.md: InterpolatedStringAtom.ToString()が
    # リテラル部分を`EscapeForRobin(interpolated: true)`経由で出力し、そこで
    # `%`が常に`%%`に二重化されることをソースで確認した。`_STRING_RE`が捕捉する
    # `$'''...'''`は全てこの経路を通るため、解除は推測ではなくソース上確定している。
    records = parse_dsl("SET TestVar TO $'''100%% done'''")
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, SetVariableRecord)
    assert record.value == "100% done"


def test_multiline_comment_parsed_with_slash_hash_delimiters() -> None:
    # design/robin_language_source_findings.md: CommentStatement.ToString()が
    # 改行を含むコメントを`/# ... #/`で囲むことをソースで確認した(実機未確認)。
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
    # design/robin_language_source_findings.md: ANTLR生成パーサー(Language.cs)の
    # Small_statementContextで、switch_statement/case_statement/case_defaultが
    # if_statement/elseif_statement/else_statementと文法上並列であることを確認した。
    # CASEの演算子(`=`)が実機で確認済み(SemiComparison.ToStringの予測通り)。
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
    # design/robin_language_source_findings.md: ComparisonOperatorExtensions.ToString()の
    # ソースで`NOT IN`が内部に空白を1つ持つ1つの文字列として直列化されることを確認した。
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
    # **重要な訂正**: ソース(design/robin_language_source_findings.md の
    # ExceptionStatementBase.SetLevel())からは「本体はヘッダーより1段深い」と予測していたが、
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
    assert record.params["Element"] == UiElementRef(name="Start Button")
    assert record.params["ClickType"] == EnumRef("UIAutomation.ClickType.LeftClick")
    assert record.params["OffsetX"] == 0


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
