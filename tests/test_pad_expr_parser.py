"""pad_expr_parser(`SET ... TO`複合式のLark構文解析)の単体テスト。

design/dsl_format_findings.md 知見53で実機確認した3つのDSLキャプチャ例を中心に、
素朴なトークン結合(Lark導入前の挙動)ではなく実際の構文木が構築されていることを確認する。
演算子の優先順位そのものはPAD実機で未検証の仮定であるため、ここでは「優先順位が正しいか」は
検証対象にせず、「構文木からの再構成テキストが元のDSLテキストと一致するか」(往復の無損失性)
と「構造が期待通りに組み立てられているか」を確認する。
"""
from __future__ import annotations

from dump_daemon.pad_dsl import EnumRef, UiElementRef, VarRef
from dump_daemon.pad_expr import (
    Atom,
    BinOp,
    FuncCall,
    Paren,
    UnaryOp,
    parse_expr,
    render_expr,
)


def test_logical_compound_expression_builds_real_tree() -> None:
    # 知見53実機キャプチャ: "SET NewVar3 TO 1 = 1 AND 2 = 2 OR NOT 3 = 4"
    tree, text = parse_expr("1 = 1 AND 2 = 2 OR NOT 3 = 4".split(), {})
    assert text == "1 = 1 AND 2 = 2 OR NOT 3 = 4"
    assert isinstance(tree, BinOp) and tree.op == "OR"
    assert isinstance(tree.left, BinOp) and tree.left.op == "AND"
    assert tree.left.left == BinOp("=", Atom(1), Atom(1))
    assert tree.left.right == BinOp("=", Atom(2), Atom(2))
    assert isinstance(tree.right, UnaryOp) and tree.right.op == "NOT"
    # NOTは単項の裸の値ではなく、比較式全体("3 = 4")を包む(比較が論理NOTより
    # 優先度が高いという仮定——`a NOT b = c`のような無意味な構造にはならない)。
    assert tree.right.operand == BinOp("=", Atom(3), Atom(4))


def test_parentheses_are_preserved_structurally_and_round_trip() -> None:
    # 知見53実機キャプチャ: "SET NewVar3 TO (1 = 1 XOR 2 = 2) AND (3 = 3)"
    tree, text = parse_expr("(1 = 1 XOR 2 = 2) AND (3 = 3)".split(), {})
    assert text == "(1 = 1 XOR 2 = 2) AND (3 = 3)"
    assert isinstance(tree, BinOp) and tree.op == "AND"
    assert isinstance(tree.left, Paren)
    assert tree.left.inner == BinOp("XOR", BinOp("=", Atom(1), Atom(1)), BinOp("=", Atom(2), Atom(2)))
    assert isinstance(tree.right, Paren)
    assert tree.right.inner == BinOp("=", Atom(3), Atom(3))


def test_arithmetic_expression_respects_assumed_precedence_tiers() -> None:
    # 知見53実機キャプチャ: "SET NewVar3 TO 1 + 2 * 3 - 4 / 2 mod 3"
    tree, text = parse_expr("1 + 2 * 3 - 4 / 2 mod 3".split(), {})
    assert text == "1 + 2 * 3 - 4 / 2 mod 3"
    # 採用した仮定(*//mod は +/- より強く結合する)のもとでは
    # (1 + (2 * 3)) - ((4 / 2) mod 3) という木になるはず。
    assert tree == BinOp(
        "-",
        BinOp("+", Atom(1), BinOp("*", Atom(2), Atom(3))),
        BinOp("mod", BinOp("/", Atom(4), Atom(2)), Atom(3)),
    )


def test_text_round_trip_is_independent_of_the_assumed_precedence() -> None:
    # render_expr()はBinOpを常に"{left} {op} {right}"という左→右の並びのまま出力するだけで
    # 優先順位の仮定に基づいて括弧を補わない。そのため、採用した優先順位の仮定が実機の
    # 挙動と食い違っていたとしても、往復テキスト自体は破綻しないことを明示的に確認する。
    tree = BinOp("-", BinOp("+", Atom(1), BinOp("*", Atom(2), Atom(3))), Atom(9))
    assert render_expr(tree) == "1 + 2 * 3 - 9"


def test_glued_negative_number_literal_is_a_single_atom() -> None:
    # "+"に続けて空白なしで"-4"が来るケースは、二項マイナスのMINUSトークンではなく
    # 1個の負数リテラルとして字句解析されることを確認する(知見無し・未検証の組み合わせだが、
    # 少なくともLarkの字句解析がもっともらしく振る舞うことの確認)。
    tree, text = parse_expr("1 + -4".split(), {})
    assert text == "1 + -4"
    assert tree == BinOp("+", Atom(1), Atom(-4))


def test_variable_trailer_atom_is_resolved_via_existing_var_ref() -> None:
    # design/dsl_format_findings.md 知見59: `[start:end]`スライス・`[Index]`添字は
    # 既存の`_resolve_value()`の`VarRef`フォールバックで文字列として丸ごと保持される。
    # 式パーサーはここを独自に分解せず、既存の値解決ロジックをそのまま再利用する。
    tree, text = parse_expr("InnerVar[0:2] AND True".split(), {})
    assert text == "InnerVar[0:2] AND True"
    assert tree == BinOp("AND", Atom(VarRef("InnerVar[0:2]")), Atom(True))


def test_enum_ref_atom_is_resolved_via_existing_enum_ref() -> None:
    tree, _ = parse_expr("Display.Icon.None AND True".split(), {})
    assert tree == BinOp("AND", Atom(EnumRef("Display.Icon.None")), Atom(True))


def test_string_literal_placeholder_is_resolved_and_round_trips() -> None:
    placeholders = {"\x00STR0\x00": "hello"}
    tree, text = parse_expr(["\x00STR0\x00", "AND", "True"], placeholders)
    assert text == "'hello' AND True"
    assert tree == BinOp("AND", Atom("hello"), Atom(True))


def test_ui_element_placeholder_is_resolved_and_round_trips() -> None:
    placeholders = {"\x00UIE0\x00": ("Window 'Untitled'", "Button 'OK'")}
    tree, text = parse_expr(["\x00UIE0\x00", "AND", "True"], placeholders)
    assert text == 'appmask["Window \'Untitled\'"]["Button \'OK\'"] AND True'
    assert tree == BinOp(
        "AND", Atom(UiElementRef(("Window 'Untitled'", "Button 'OK'"))), Atom(True)
    )


def test_function_call_is_parsed_as_dedicated_node() -> None:
    # 知見18-2のIfFunctionRecordと同じ関数呼び出し構文("Contains(...)")が、ANTLR文法上
    # 汎用Expressionルールのサブクラスとしてどこにでも出現しうることを踏まえた拡張
    # (SET...TO複合式の中での実機確認はまだ無い、未検証の拡張)。
    tree, text = parse_expr("Contains(InnerVar, 1, False) AND 2 = 2".split(), {})
    assert text == "Contains(InnerVar, 1, False) AND 2 = 2"
    assert isinstance(tree, BinOp) and tree.op == "AND"
    assert tree.left == FuncCall("Contains", (Atom(VarRef("InnerVar")), Atom(1), Atom(False)))


def test_unparseable_input_falls_back_to_none_tree_without_losing_text() -> None:
    # Lark文法がまだ対応していない(あるいは単純に構文的に不正な)入力に遭遇した場合、
    # 知見15・26・36・38・46・50・53と同じ「データを失わない」方針で、構造化を諦めて
    # tree=Noneにフォールバックしつつ、テキストそのものは失わないことを確認する。
    tree, text = parse_expr("1 AND".split(), {})
    assert tree is None
    assert text == "1 AND"
