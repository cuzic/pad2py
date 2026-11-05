"""uipath_expr の単体テスト。

フィクスチャの式テキストは design/uipath_vb_expression_mapping.md と
design/uipath_xaml_findings.md 知見2・5・14・30・32・36で実機コンパイル
確認済みの`[...]`角括弧式の中身そのもの(でっち上げではない)。
"""
from __future__ import annotations

from dump_daemon.uipath_expr import (
    BinOp,
    BoolLiteral,
    FuncCall,
    Ident,
    InterpolatedString,
    NothingLiteral,
    NumberLiteral,
    Paren,
    StringLiteral,
    UnaryOp,
    parse_vb_expr,
    render_expr,
)

# 知見32: 9演算子を1つの複合式にまとめて実機コンパイル確認した式そのもの。
KNOWN_OP_COMPOUND = (
    'CStr(1 Mod 3) & CStr(5 \\ 2) & CStr(2 ^ 2) & CStr(True And False) '
    "& CStr(True AndAlso False) & CStr(True Or False) & CStr(True OrElse False) "
    "& CStr(True Xor False) & CStr(Not True)"
)

# 知見36: IsNot/Nothing/三項If/CInt/CDbl/CBool/IsNothingの実機コンパイル確認式。
KNOWN_CTYPE_COMPOUND = (
    'CStr(If(result IsNot Nothing, "notnothing", "isnothing")) '
    '& CStr(CInt("5")) & CStr(CDbl("2.5")) & CStr(CBool("True")) '
    "& CStr(IsNothing(Nothing))"
)

# 知見36: String.IsNullOrEmptyとクォートエスケープの実機コンパイル確認式。
KNOWN_ISEMPTY = 'CStr(String.IsNullOrEmpty("")) & "He said ""hi"" today"'

# 知見36: 文字列補間の実機コンパイル確認式。
KNOWN_INTERP = '$"value={result}-end"'


def test_identifier():
    node, rendered = parse_vb_expr("result")
    assert node == Ident(name="result")
    assert rendered == "result"


def test_equality_and_inequality():
    """知見5・14: `=`/`<>`。レンダリング結果は演算子前後に半角スペースが
    入るため、元のテキスト(スペース無し)とは完全一致しない——意味的に
    同等であることだけを確認する(render_expr()のdocstring参照)。"""
    node, rendered = parse_vb_expr('result="ok"')
    assert node == BinOp(op="=", left=Ident(name="result"), right=StringLiteral(value="ok"))
    assert rendered == 'result = "ok"'

    node, rendered = parse_vb_expr('result<>"x"')
    assert node == BinOp(op="<>", left=Ident(name="result"), right=StringLiteral(value="x"))


def test_is_nothing_lowercase_keyword():
    """知見30: UiPath公式REFrameworkテンプレートの実例、小文字の`is`。
    VB.NETの大文字小文字非区別を確認する重要なケース。"""
    node, _ = parse_vb_expr("SystemException is Nothing")
    assert node == BinOp(
        op="is", left=Ident(name="SystemException"), right=NothingLiteral()
    )


def test_known_operator_compound_parses(recwarn):
    node, rendered = parse_vb_expr(KNOWN_OP_COMPOUND)
    assert node is not None, "知見32の実機確認済み式がパース失敗した(フォールバックした)"
    assert rendered == KNOWN_OP_COMPOUND  # 空白込みで完全一致(元々&の前後に空白あり)


def test_known_ctype_compound_parses():
    node, rendered = parse_vb_expr(KNOWN_CTYPE_COMPOUND)
    assert node is not None, "知見36の実機確認済み式がパース失敗した(フォールバックした)"
    assert rendered == KNOWN_CTYPE_COMPOUND


def test_known_isempty_compound_parses():
    node, rendered = parse_vb_expr(KNOWN_ISEMPTY)
    assert node is not None
    assert rendered == KNOWN_ISEMPTY


def test_interpolated_string_is_opaque():
    node, rendered = parse_vb_expr(KNOWN_INTERP)
    assert node == InterpolatedString(raw=KNOWN_INTERP)
    assert rendered == KNOWN_INTERP


def test_ternary_if_is_plain_func_call():
    """知見36: 三項`If(cond, t, f)`はXAML上も特別扱いされない通常の
    関数呼び出し構文——パーサー側でも同様に扱う。"""
    node, _ = parse_vb_expr('If(x, "a", "b")')
    assert isinstance(node, FuncCall)
    assert node.name == "If"
    assert len(node.args) == 3
    assert node.args[0] == Ident(name="x")
    assert node.args[1] == StringLiteral(value="a")
    assert node.args[2] == StringLiteral(value="b")


def test_dotted_static_method_call():
    node, _ = parse_vb_expr('String.IsNullOrEmpty("")')
    assert isinstance(node, FuncCall)
    assert node.name == "String.IsNullOrEmpty"
    assert node.args == (StringLiteral(value=""),)


def test_parenthesized_expr_preserved():
    node, rendered = parse_vb_expr("(1 + 2) * 3")
    assert isinstance(node, BinOp)
    assert node.op == "*"
    assert isinstance(node.left, Paren)
    assert rendered == "(1 + 2) * 3"


def test_unary_minus_and_number_literal():
    node, rendered = parse_vb_expr("-5")
    assert node == UnaryOp(op="-", operand=NumberLiteral(value=5))
    assert rendered == "- 5"


def test_bool_literals():
    node, _ = parse_vb_expr("True")
    assert node == BoolLiteral(value=True)
    node, _ = parse_vb_expr("False")
    assert node == BoolLiteral(value=False)


def test_unparseable_input_falls_back_without_losing_text():
    """この文法が対応していない入力(例: 閉じ括弧の対応が崩れている)でも
    テキストそのものは絶対に失わない(pad_exprと同じフォールバック方針)。"""
    garbage = "CStr(1 Mod 3"  # 閉じ括弧が無い、意図的に壊れた入力
    node, text = parse_vb_expr(garbage)
    assert node is None
    assert text == garbage


def test_render_expr_round_trip_matches_for_simple_cases():
    for text in ["result", "1 Mod 3", "5 \\ 2", "2 ^ 2", "Not True", "Nothing"]:
        node, rendered = parse_vb_expr(text)
        assert node is not None
        assert rendered == text
