"""UiPath XAML中の`[...]`角括弧式(`uipath_dsl.types.VbExpr`の中身)をLarkで
構文解析するモジュール。design/uipath_vb_expression_mapping.mdで実機確認
(知見2・5・14・30・32・36)した構文の範囲——フルVB.NET文法ではなく、実機で
受理されると確認できた演算子・関数呼び出し・リテラルのみ——をカバーする。

`dump_daemon.pad_expr`(PAD用)と同じ設計方針を踏襲する:

1. **演算子の優先順位は公開仕様に基づく(実機の混在式での評価順は未検証)**。
   design/uipath_vb_expression_mapping.md知見32・36で確認したのは「各演算子が
   単独で`[...]`式として受理され、変換無しで直列化される」ことだけで、
   異なる優先順位の演算子を括弧無しで混在させた式が実機でどう評価されるかは
   実機確認していない。以下の優先順位はMicrosoft Learn「Operator
   Precedence - Visual Basic」(`learn.microsoft.com/en-us/dotnet/visual-basic/
   language-reference/operators/operator-precedence`)の現行版に基づく
   (高い順: `^` > 単項`+`/`-` > `*`/`/` > `\\`(整数除算) > `Mod` >
   二項`+`/`-` > `&` > 比較(`=`/`<>`/`<`/`>`/`<=`/`>=`/`Is`/`IsNot`) >
   `Not` > `And`/`AndAlso` > `Or`/`OrElse` > `Xor`、`Xor`が論理/ビット演算子
   群の中で最も緩い)。2026-11-05: 文法の実装がこの並び(`And`>`Or`>`Xor`)と
   逆(`Or`>`Xor`>`And`の順に外側から内側へネストしていた)になっていた
   実装バグを発見・修正した——`And`/`Or`/`Xor`を括弧無しで混在させる実機
   データが知見32・36のいずれにも無かったため、長らく未検出だった
   (`tests/test_uipath_expr.py`の`test_and_or_xor_relative_precedence_matches_official_vb_spec`
   参照)。
2. **フォールバック方針**: この文法が対応していない入力(文字列補間
   `$"..."`の中身・未対応の関数・構文エラー)に遭遇した場合、構造化を
   諦めて`tree=None`とし元のテキストをそのまま保持する——構文解析の失敗で
   テキストを失うことは絶対に無い(`pad_expr`・`pad_codegen`と同じ
   「でっち上げない」方針)。
3. **キーワード演算子は大文字小文字を区別しない**: VB.NET自体が言語全体で
   大文字小文字を区別しない仕様であり、知見30のREFrameworkテンプレート
   実例(`[SystemException is Nothing]`、小文字の`is`)でも確認済み——
   Studioの自動整形を経ない外部ソースではキーワードの大文字小文字が
   揺れうる。
4. **文字列補間`$"...{expr}..."`の中身は、この文法(Lark)のレクサ自体は
   解析しない**: `$"..."`全体を1つの不透明な`InterpolatedString`
   アトムとして文字列のまま保持する(`INTERP_STRING`トークンの正規表現
   (下記`_GRAMMAR`定義参照)は、`{expr}`内部にネストしたVB文字列リテラル
   (例: `If(age = 1, "", "s")`の`""`/`"s"`)と、補間文字列自身の`""`
   エスケープを区別できないため——`{`で始まるかどうかを見ない単純な
   正規表現では、レクサの時点でこの2つの意味論的に別物な`"`の使われ方を
   判別不能。**ただし`InterpolatedString.raw`に残った生テキストに対し、
   `uipath_codegen/render.py`側(知見65)で`{`/`}`の深さとネストした
   クォート状態を追跡する手書きの状態機械により、書式指定子・フィールド幅
   (`{expr:format}`/`{expr,width}`)を伴わないプレーンな`{expr}`補間は
   コード生成まで到達できるようになった**——知見15・16・32・36の実機
   確認例(`$"value={result}-end"`等)はいずれもこのプレーンな形だった。
   `{expr}`内部にネストした文字列リテラルを含む式(上記`If(...)`の例)は、
   レクサの時点で依然失敗し(`parse_vb_expr`が`(None, raw_text)`を返す、
   安全なフォールバック)、呼び出し側で`# TODO`に倒れる——この限界自体は
   まだ解消していない(Larkのレクサ自体を書き換えるか、Lark呼び出し前の
   独自プリスキャンが必要で、より大きな変更になるため今回は見送った)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from lark import Lark, Transformer
from lark.exceptions import LarkError

_GRAMMAR = r"""
?expr: xor_expr

?xor_expr: or_expr
         | xor_expr _XOR or_expr -> xor_

?or_expr: and_expr
        | or_expr _OR and_expr     -> or_
        | or_expr _ORELSE and_expr -> orelse_

?and_expr: not_expr
         | and_expr _AND not_expr     -> and_
         | and_expr _ANDALSO not_expr -> andalso_

?not_expr: comparison
         | _NOT not_expr -> not_

?comparison: concat
           | concat comp_op concat -> comparison

comp_op: EQ | NE | LE | GE | LT | GT | IS | ISNOT

?concat: add_expr
       | concat _AMP add_expr -> concat_

?add_expr: mod_expr
         | add_expr _PLUS mod_expr  -> add
         | add_expr _MINUS mod_expr -> sub

?mod_expr: intdiv_expr
         | mod_expr _MOD intdiv_expr -> mod_

?intdiv_expr: muldiv_expr
            | intdiv_expr _BACKSLASH muldiv_expr -> intdiv_

?muldiv_expr: unary_expr
            | muldiv_expr _STAR unary_expr  -> mul
            | muldiv_expr _SLASH unary_expr -> div

?unary_expr: power_expr
           | _MINUS unary_expr -> neg
           | _PLUS unary_expr  -> pos

?power_expr: atom
           | atom _CARET unary_expr -> pow_

?atom: IDENT "(" arglist ")" -> func_call
     | IDENT                 -> ident
     | STRING                -> string_lit
     | INTERP_STRING         -> interp_string
     | NUMBER                -> number_lit
     | TRUE                  -> true_lit
     | FALSE                 -> false_lit
     | NOTHING                -> nothing_lit
     | "(" expr ")"          -> paren
     | "{" arglist "}"       -> array_lit

arglist: [expr ("," expr)*]

// ルールエイリアス自体で演算子の種類が確定するトークンはアンダースコア始まりに
// して構文木から除外する(pad_exprと同じLark慣習)。比較演算子はcomp_opが
// どの種類かを判定するために必要なので除外しない。
_PLUS.1: "+"
_MINUS.1: "-"
_STAR.1: "*"
_SLASH.1: "/"
_BACKSLASH.1: "\\"
_CARET.1: "^"
_AMP.1: "&"
NE.2: "<>"
LE.2: "<="
GE.2: ">="
LT.1: "<"
GT.1: ">"
EQ.1: "="
ISNOT.3: /IsNot\b/i
IS.2: /Is\b/i
_ANDALSO.3: /AndAlso\b/i
_AND.2: /And\b/i
_ORELSE.3: /OrElse\b/i
_OR.2: /Or\b/i
_XOR.2: /Xor\b/i
_NOT.2: /Not\b/i
_MOD.2: /Mod\b/i
TRUE.2: /True\b/i
FALSE.2: /False\b/i
NOTHING.2: /Nothing\b/i

INTERP_STRING.3: /\$"([^"]|"")*"/
STRING.1: /"([^"]|"")*"/
NUMBER.1: /\d+\.\d+|\d+/
IDENT.0: /[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*/

%import common.WS
%ignore WS
"""

_PARSER = Lark(_GRAMMAR, start="expr", parser="lalr")


@dataclass(frozen=True)
class BinOp:
    """2項演算子(`comp_op`の中身・`&`・`+`/`-`・`Mod`・`\\`・`*`/`/`・`^`・
    `And`/`AndAlso`/`Or`/`OrElse`/`Xor`)。`op`は正規化済みの演算子文字列
    (大文字小文字はVB側の表記のまま保持、例: `"Mod"`)。"""

    op: str
    left: "ExprNode"
    right: "ExprNode"


@dataclass(frozen=True)
class UnaryOp:
    """前置単項演算子。`Not`・単項`-`・単項`+`。"""

    op: str
    operand: "ExprNode"


@dataclass(frozen=True)
class Paren:
    """元のテキストに明示的に書かれた丸括弧(`pad_expr.Paren`と同じ:
    優先順位の仮定に関わらず、実在した丸括弧の事実そのものを保持する)。"""

    inner: "ExprNode"


@dataclass(frozen=True)
class FuncCall:
    """関数呼び出し(`CStr(x)`/`CInt(x)`/`CDbl(x)`/`CBool(x)`/`IsNothing(x)`/
    三項演算子`If(cond, t, f)`/`String.IsNullOrEmpty(x)`等、知見32・36で
    実機確認済みの形)。三項`If`は構文上は単なる3引数の関数呼び出しとして
    扱う(知見36で確認した通りXAML上も特別な要素にはならず`[...]`内の
    通常の関数呼び出し構文のまま)。`name`はドット区切りの静的メソッド名
    (`String.IsNullOrEmpty`)も含みうる。"""

    name: str
    args: tuple["ExprNode", ...]


@dataclass(frozen=True)
class Ident:
    """変数参照、またはドット区切りのメンバ/静的クラス参照
    (`String.IsNullOrEmpty`のクラス部分等、関数呼び出しの対象ではない
    単独の参照として出現した場合)。"""

    name: str


@dataclass(frozen=True)
class StringLiteral:
    """文字列リテラル。`value`はVB側の`""`エスケープを`"`1個に正規化済み
    (知見36)。"""

    value: str


@dataclass(frozen=True)
class InterpolatedString:
    """文字列補間`$"...{expr}..."`(知見36)。モジュールdocstring参照の通り、
    `{expr}`の中身は解析せず`raw`に生テキストをそのまま保持する(既知の限界)。
    """

    raw: str


@dataclass(frozen=True)
class NumberLiteral:
    value: float | int


@dataclass(frozen=True)
class BoolLiteral:
    value: bool


@dataclass(frozen=True)
class NothingLiteral:
    """VBの`Nothing`(知見36: Pythonの`None`に対応)。"""


@dataclass(frozen=True)
class ArrayLiteral:
    """配列/コレクションリテラル`{a, b, c}`(design/uipath_xaml_findings.md
    知見5、design/uipath_vb_expression_mapping.md「確認済み」表。Python
    `[a, b, c]`に対応)。"""

    items: tuple["ExprNode", ...]


ExprNode = Union[
    BinOp,
    UnaryOp,
    Paren,
    FuncCall,
    Ident,
    StringLiteral,
    InterpolatedString,
    NumberLiteral,
    BoolLiteral,
    NothingLiteral,
    ArrayLiteral,
]


def _unescape_vb_string(raw: str) -> str:
    """`"He said ""hi"" today"`形式(両端の`"`込み)を`He said "hi" today`
    (中身のみ、`""`→`"`に正規化)へ変換する(知見36)。"""
    inner = raw[1:-1]
    return inner.replace('""', '"')


class _ExprTransformer(Transformer):
    def ident(self, children: list) -> Ident:
        (tok,) = children
        return Ident(name=str(tok))

    def string_lit(self, children: list) -> StringLiteral:
        (tok,) = children
        return StringLiteral(value=_unescape_vb_string(str(tok)))

    def interp_string(self, children: list) -> InterpolatedString:
        (tok,) = children
        return InterpolatedString(raw=str(tok))

    def number_lit(self, children: list) -> NumberLiteral:
        (tok,) = children
        text = str(tok)
        value: float | int = float(text) if "." in text else int(text)
        return NumberLiteral(value=value)

    def true_lit(self, children: list) -> BoolLiteral:
        return BoolLiteral(value=True)

    def false_lit(self, children: list) -> BoolLiteral:
        return BoolLiteral(value=False)

    def nothing_lit(self, children: list) -> NothingLiteral:
        return NothingLiteral()

    def paren(self, children: list) -> Paren:
        (inner,) = children
        return Paren(inner=inner)

    def array_lit(self, children: list) -> ArrayLiteral:
        (items,) = children
        return ArrayLiteral(items=tuple(items))

    def func_call(self, children: list) -> FuncCall:
        name_tok, args = children
        return FuncCall(name=str(name_tok), args=tuple(args))

    def arglist(self, children: list) -> list:
        return list(children)

    def comp_op(self, children: list) -> str:
        (tok,) = children
        return str(tok)

    def comparison(self, children: list) -> BinOp:
        left, op, right = children
        return BinOp(op=op, left=left, right=right)

    def or_(self, children: list) -> BinOp:
        left, right = children
        return BinOp(op="Or", left=left, right=right)

    def orelse_(self, children: list) -> BinOp:
        left, right = children
        return BinOp(op="OrElse", left=left, right=right)

    def xor_(self, children: list) -> BinOp:
        left, right = children
        return BinOp(op="Xor", left=left, right=right)

    def and_(self, children: list) -> BinOp:
        left, right = children
        return BinOp(op="And", left=left, right=right)

    def andalso_(self, children: list) -> BinOp:
        left, right = children
        return BinOp(op="AndAlso", left=left, right=right)

    def not_(self, children: list) -> UnaryOp:
        (operand,) = children
        return UnaryOp(op="Not", operand=operand)

    def concat_(self, children: list) -> BinOp:
        left, right = children
        return BinOp(op="&", left=left, right=right)

    def add(self, children: list) -> BinOp:
        left, right = children
        return BinOp(op="+", left=left, right=right)

    def sub(self, children: list) -> BinOp:
        left, right = children
        return BinOp(op="-", left=left, right=right)

    def mod_(self, children: list) -> BinOp:
        left, right = children
        return BinOp(op="Mod", left=left, right=right)

    def intdiv_(self, children: list) -> BinOp:
        left, right = children
        return BinOp(op="\\", left=left, right=right)

    def mul(self, children: list) -> BinOp:
        left, right = children
        return BinOp(op="*", left=left, right=right)

    def div(self, children: list) -> BinOp:
        left, right = children
        return BinOp(op="/", left=left, right=right)

    def pow_(self, children: list) -> BinOp:
        left, right = children
        return BinOp(op="^", left=left, right=right)

    def neg(self, children: list) -> UnaryOp:
        (operand,) = children
        return UnaryOp(op="-", operand=operand)

    def pos(self, children: list) -> UnaryOp:
        (operand,) = children
        return UnaryOp(op="+", operand=operand)


def render_expr(node: ExprNode) -> str:
    """構文木から、元のVB式テキストに意味的に同等な可読テキストを再構成する。

    `pad_expr.render_expr()`と同じ方針: `BinOp`/`UnaryOp`は優先順位の仮定に
    基づいて括弧を補ったりせず、常に`"{left} {op} {right}"`の並びをそのまま
    出力する——丸括弧は`Paren`ノード(元のテキストに実在した丸括弧)からしか
    出力されないため、優先順位の仮定が実機の挙動と食い違っていてもテキストの
    往復には影響しない。**ただし`pad_expr`と異なり文字単位の完全一致は
    保証しない**——`result="ok"`が`result = "ok"`のように、演算子の前後に
    常に半角スペースを1つ挿入する(元のテキストにスペースが無くても挿入
    する)ため、空白の有無までは往復しない。実際に`design/uipath_vb_expression_mapping.md`
    で確認済みの式全件で検証済み(空白を除けば完全一致)。
    """
    if isinstance(node, Ident):
        return node.name
    if isinstance(node, StringLiteral):
        return '"' + node.value.replace('"', '""') + '"'
    if isinstance(node, InterpolatedString):
        return node.raw
    if isinstance(node, NumberLiteral):
        return str(node.value)
    if isinstance(node, BoolLiteral):
        return "True" if node.value else "False"
    if isinstance(node, NothingLiteral):
        return "Nothing"
    if isinstance(node, ArrayLiteral):
        items = ", ".join(render_expr(i) for i in node.items)
        return "{" + items + "}"
    if isinstance(node, Paren):
        return f"({render_expr(node.inner)})"
    if isinstance(node, UnaryOp):
        return f"{node.op} {render_expr(node.operand)}"
    if isinstance(node, FuncCall):
        args = ", ".join(render_expr(a) for a in node.args)
        return f"{node.name}({args})"
    if isinstance(node, BinOp):
        return f"{render_expr(node.left)} {node.op} {render_expr(node.right)}"
    raise TypeError(f"Unsupported expr node: {node!r}")


def parse_vb_expr(text: str) -> tuple[ExprNode | None, str]:
    """`uipath_dsl.types.VbExpr.text`(`[...]`角括弧を除いた中身)をパースする。

    戻り値は`(構文木, テキスト)`。構文解析に成功した場合は`render_expr()`で
    再構成したテキストを返す(空白の挿入を除き元のテキストと意味的に
    同等——`render_expr()`のdocstring参照)。この文法が
    まだ対応していない入力に遭遇して`Lark`が構文エラーを出した場合は、
    構造化を諦めて`tree=None`を返し、テキストはそのまま素通しする——
    構文解析の失敗でテキストそのものを失うことは無い(`pad_expr`と同じ
    フォールバック方針)。
    """
    try:
        parse_tree = _PARSER.parse(text)
        node = _ExprTransformer().transform(parse_tree)
    except LarkError:
        return None, text
    return node, render_expr(node)
