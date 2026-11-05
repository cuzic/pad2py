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


def test_interpolated_string_with_multiple_nested_quoted_literals_parses():
    """知見66: `{expr}`を2回以上含み、それぞれにネストした文字列リテラル
    がある場合でも、`_prescan_interpolated_strings()`のプレースホルダが
    区間ごとに独立して割り振られ、取り違えなく元の生テキストへ戻ることを
    確認する。"""
    text = '$"{If(a=1,"","s")}-{If(b=1,"","s")}"'
    node, rendered = parse_vb_expr(text)
    assert node == InterpolatedString(raw=text)
    assert rendered == text


def test_unterminated_interpolated_string_falls_back_safely():
    """知見66: 閉じる`"`が無い補間文字列は`_find_interp_string_span()`が
    `None`を返し、置換されないまま元のテキストがLarkに渡る——構文エラーに
    なって`parse_vb_expr`が`(None, raw_text)`を返す既存の安全な
    フォールバックに委ねられ、クラッシュしないことを確認する。"""
    text = '$"abc{x'
    node, rendered = parse_vb_expr(text)
    assert node is None
    assert rendered == text


def test_interpolated_string_nested_inside_another_interpolated_string_boundary_detected():
    """知見69: `{expr}`内部にさらに別の補間文字列`$"..."`が書かれた場合も、
    `_find_interp_string_span`の`{`/`}`深さ追跡が内側の`$"..."`を
    「ネストした文字列リテラル」の開始/終了として扱い、外側の境界を
    正しく検出することを確認する(`$`自体はこの状態機械にとって
    特別な意味を持たない通常の文字であり、続く`"`だけがクォート状態を
    切り替えるため、副作用として正しく動作する)。"""
    text = '$"outer {$"inner {x}"}"'
    node, rendered = parse_vb_expr(text)
    assert node == InterpolatedString(raw=text)
    assert rendered == text


def test_interpolated_string_with_nested_quoted_literal_still_parses():
    """知見66: `{expr}`内部にネストしたVB文字列リテラル(公式ドキュメント
    「Interpolated Strings」自身の`If(age = 1, "", "s")`の例)は、知見65時点
    では`INTERP_STRING`トークンの正規表現がレクサの時点で誤って境界を
    打ち切ってしまい`(None, raw_text)`へ安全にフォールバックしていた。
    `_prescan_interpolated_strings()`が`{`/`}`の深さとネストしたクォート
    状態を見て正しい境界を先に確定するようになったため、`$"..."`全体が
    1つの`InterpolatedString`として(生テキストを変えずに)パースできる
    ことを確認する——`raw`は元のテキストと完全一致(プレースホルダが
    漏れ出していない)。"""
    text = '$"{name} is old{If(age = 1, "", "s")}."'
    node, rendered = parse_vb_expr(text)
    assert node == InterpolatedString(raw=text)
    assert rendered == text


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


def test_and_or_xor_relative_precedence_matches_official_vb_spec():
    """公式ドキュメント(Microsoft Learn「Operator Precedence - Visual
    Basic」、Logical and Bitwise Operatorsの節)が明記する優先順位——
    `Not` > `And`/`AndAlso` > `Or`/`OrElse` > `Xor`(`Xor`が最も緩い)——を
    直接検証する回帰テスト。

    修正前は`or_expr`が最も外側(緩い)、`xor_expr`がその内側というグラマー
    構造になっており、`Or`と`Xor`の相対優先順位が公式仕様と逆だった
    (モジュールdocstringが記す意図した優先順位とも矛盾していた、
    単純な実装漏れ)——括弧無しで`And`/`Or`/`Xor`を混在させる実機データが
    知見32・36のいずれにも無かったため、この文法バグはテストで検出されずに
    残っていた。

    `a And b Or c Xor d`は公式仕様通りなら`((a And b) Or c) Xor d`
    (`Xor`が最も緩いため最後に分割される)になるはずで、修正前の文法では
    誤って`(a And b) Or (c Xor d)`になっていた。
    """
    node, _ = parse_vb_expr("a And b Or c Xor d")
    assert node == BinOp(
        op="Xor",
        left=BinOp(
            op="Or",
            left=BinOp(op="And", left=Ident(name="a"), right=Ident(name="b")),
            right=Ident(name="c"),
        ),
        right=Ident(name="d"),
    )


def test_unary_minus_binds_looser_than_power_matches_official_vb_spec():
    """公式ドキュメント(Microsoft Learn「Operator Precedence - Visual
    Basic」)の算術演算子チェーンでは`^`(累乗)が単項`+`/`-`より強く結合する
    ——`-2 ^ 2`は`(-2) ^ 2`(=4)ではなく`-(2 ^ 2)`(=-4)になる。知見41の
    `And`/`Or`/`Xor`バグの反省から全チェーンを公式表と照合した際
    (design/uipath_vb_expression_mapping.md参照)に確認した回帰テスト
    ——幸いPythonの`**`も単項マイナスより強く結合するため、この点は
    VBとPythonで一致しており、文法のバグも見つからなかった(確認のみ)。
    """
    node, _ = parse_vb_expr("-2 ^ 2")
    assert node == UnaryOp(
        op="-",
        operand=BinOp(op="^", left=NumberLiteral(value=2), right=NumberLiteral(value=2)),
    )
