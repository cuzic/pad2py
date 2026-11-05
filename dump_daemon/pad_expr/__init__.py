"""`SET ... TO`の右辺の複合式(知見53)をLarkで構文解析するモジュール。

design/dsl_format_findings.md 知見53で、`AND`/`OR`/`XOR`/`NOT`の論理式・`+`/`-`/`*`/`/`/`mod`の
算術式・比較演算子が実機DSLでどう直列化されるかは確認済みだが、**演算子の優先順位・結合性は
実機で未検証**。

以下の文法は一般的な言語慣習(`OR` < `XOR` < `AND` < `NOT` < 比較 < `+`/`-` < `*`/`/`/`mod`、
括弧が最優先)を**仮に採用した未検証の仮定**であり、この優先順位が実機の挙動と一致する保証は無い。
そのため`pad_codegen`は本モジュールが構築した構文木を実際のPython式生成にはまだ使わず、
引き続き`RawExpr.text`全体をTODOコメントへ安全に倒す(知見53の方針を変更していない)。

本モジュールの現時点での価値は変換の正しさではなく、以下の2点:
1. 括弧の有無に関わらず(例: `(1 = 1 XOR 2 = 2) AND (3 = 3)`)、トークン単位の素朴な文字列結合
   ではなく実際の再帰下降構文木として式を構造化できること。
2. 構文木から`render_expr()`でテキストを再構成する際、演算子の結合順に関わらず元のDSLテキストと
   常に一致すること(`BinOp`は常に`"{left} {op} {right}"`という形で、優先順位の仮定に依存せず
   左→右のトークン順をそのまま保つため——優先順位の仮定が実機と食い違っていても往復テキストは
   破綻しない)。

**フォールバック方針**(知見15・26・36・38・46・50・53と同じ「データを失わない」方針):
この文法がまだ対応していない実機入力(例: 単項マイナスが式の先頭で裸の数値に直接グルーされる
ケース等、現時点では実機未確認の形)に遭遇して`Lark`の構文解析自体が失敗した場合は、構造化を
諦めて`tree=None`とし、Lark導入前からの素朴なトークン単位の文字列化にフォールバックする。
構文解析の失敗によって`RawExpr.text`(=最終的にTODOコメントに使われる元テキスト)が失われることは
絶対に無い。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Union

from lark import Lark, Transformer
from lark.exceptions import LarkError

from ..pad_dsl.line_parser import _resolve_value, _stringify_resolved_expr_token

_GRAMMAR = r"""
?expr: or_expr

?or_expr: xor_expr
        | or_expr _OR xor_expr   -> or_

?xor_expr: and_expr
         | xor_expr _XOR and_expr -> xor_

?and_expr: not_expr
         | and_expr _AND not_expr -> and_

?not_expr: comparison
         | _NOT not_expr -> not_

?comparison: arith
           | arith comp_op arith -> comparison

comp_op: EQ | NE | LE | GE | LT | GT | IN | NOT_IN

?arith: term
      | arith _PLUS term -> add
      | arith _MINUS term -> sub

?term: atom
     | term _STAR atom -> mul
     | term _SLASH atom -> div
     | term _MOD atom -> mod_

?atom: VALUE "(" arglist ")" -> func_call
     | VALUE                 -> value
     | "(" expr ")"          -> paren

arglist: [expr ("," expr)*]

// 演算子の種類がルールエイリアス(or_/and_/add/mod_等)自体で確定するトークンは
// アンダースコア始まりの名前にして構文木から除外する(Larkの規約)。比較演算子
// (EQ/NE/...)はcomp_opがどの種類かを判定するために必要なので除外しない。
_PLUS.1: "+"
_MINUS.1: "-"
_STAR.1: "*"
_SLASH.1: "/"
NE.1: "<>"
LE.1: "<="
GE.1: ">="
LT.1: "<"
GT.1: ">"
EQ.1: "="
NOT_IN.2: /NOT\s+IN\b/
_AND.1: /AND\b/
_OR.1: /OR\b/
_XOR.1: /XOR\b/
_NOT.1: /NOT\b/
_MOD.1: /mod\b/
IN.1: /IN\b/
VALUE.0: /[^\s(),]+/

%import common.WS
%ignore WS
"""

_PARSER = Lark(_GRAMMAR, start="expr", parser="lalr")


@dataclass(frozen=True)
class BinOp:
    """2項演算子(論理`AND`/`OR`/`XOR`、比較、算術`+`/`-`/`*`/`/`/`mod`)。"""

    op: str
    left: "ExprNode"
    right: "ExprNode"


@dataclass(frozen=True)
class UnaryOp:
    """前置単項演算子。現状`NOT`のみ(知見53に単項マイナスの実機確認は無い)。"""

    op: str
    operand: "ExprNode"


@dataclass(frozen=True)
class Paren:
    """DSLテキスト上に明示的に書かれた丸括弧。元のテキストに丸括弧があった事実そのものを
    保持する(優先順位の仮定だけから丸括弧の有無を復元しているわけではない)。"""

    inner: "ExprNode"


@dataclass(frozen=True)
class FuncCall:
    """関数呼び出し式(`FunctionExpContext`、知見18-2の`IfFunctionRecord`と同じ構文)。

    `SET ... TO`の複合式の中に関数呼び出しが現れた実機キャプチャはまだ無いが、ANTLR文法上
    `FunctionExpression`は汎用`Expression`ルールのサブクラスの1つであり、理論上どこにでも
    出現しうるため文法に含めている(未検証の拡張)。
    """

    name: str
    args: tuple["ExprNode", ...]


@dataclass(frozen=True)
class Atom:
    """末端の値。`_resolve_value()`の戻り値(`VarRef`/`EnumRef`/`UiElementRef`/`bool`/
    `int`/`float`/プレースホルダ由来の文字列)をそのまま保持する——既存の値解決ロジックを
    再利用し、重複させない。"""

    value: Any


ExprNode = Union[BinOp, UnaryOp, Paren, FuncCall, Atom]


class _ExprTransformer(Transformer):
    def __init__(self, placeholders: dict[str, str | tuple[str, ...]]) -> None:
        super().__init__()
        self._placeholders = placeholders

    def value(self, children: list[Any]) -> Atom:
        (tok,) = children
        return Atom(value=_resolve_value(str(tok), self._placeholders))

    def paren(self, children: list[Any]) -> Paren:
        (inner,) = children
        return Paren(inner=inner)

    def func_call(self, children: list[Any]) -> FuncCall:
        name_tok, args = children
        return FuncCall(name=str(name_tok), args=tuple(args))

    def arglist(self, children: list[Any]) -> list[Any]:
        return list(children)

    def comp_op(self, children: list[Any]) -> str:
        (tok,) = children
        return str(tok)

    def comparison(self, children: list[Any]) -> BinOp:
        left, op, right = children
        return BinOp(op=op, left=left, right=right)

    def or_(self, children: list[Any]) -> BinOp:
        left, right = children
        return BinOp(op="OR", left=left, right=right)

    def xor_(self, children: list[Any]) -> BinOp:
        left, right = children
        return BinOp(op="XOR", left=left, right=right)

    def and_(self, children: list[Any]) -> BinOp:
        left, right = children
        return BinOp(op="AND", left=left, right=right)

    def not_(self, children: list[Any]) -> UnaryOp:
        (operand,) = children
        return UnaryOp(op="NOT", operand=operand)

    def add(self, children: list[Any]) -> BinOp:
        left, right = children
        return BinOp(op="+", left=left, right=right)

    def sub(self, children: list[Any]) -> BinOp:
        left, right = children
        return BinOp(op="-", left=left, right=right)

    def mul(self, children: list[Any]) -> BinOp:
        left, right = children
        return BinOp(op="*", left=left, right=right)

    def div(self, children: list[Any]) -> BinOp:
        left, right = children
        return BinOp(op="/", left=left, right=right)

    def mod_(self, children: list[Any]) -> BinOp:
        left, right = children
        return BinOp(op="mod", left=left, right=right)


def render_expr(node: ExprNode) -> str:
    """構文木から、元のDSLテキストと一致するはずの可読テキストを再構成する。

    `BinOp`は常に`"{left} {op} {right}"`という左→右の並びをそのまま出力するだけで、
    優先順位の仮定に基づいて括弧を補ったりはしない——丸括弧は`Paren`ノード(元のテキストに
    実在した丸括弧)からしか出力されないため、優先順位の仮定が実機の挙動と食い違っていても
    テキストの往復には影響しない。
    """
    if isinstance(node, Atom):
        return _stringify_resolved_expr_token(node.value)
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


def parse_expr(
    tokens: list[str], placeholders: dict[str, str | tuple[str, ...]]
) -> tuple[ExprNode | None, str]:
    """`SET ... TO`の右辺トークン列をLark文法で構文解析する。

    戻り値は`(構文木, テキスト)`。構文解析に成功した場合は`render_expr()`で再構成した
    テキストを返す(元のDSLテキストと一致するはず)。この文法がまだ対応していない入力に
    遭遇して`Lark`が構文エラーを出した場合は、構造化を諦めて`tree=None`を返し、テキストは
    Lark導入前と同じ素朴なトークン単位の文字列化にフォールバックする——構文解析の失敗で
    テキストそのものを失うことは無い。
    """
    text = " ".join(tokens)
    try:
        parse_tree = _PARSER.parse(text)
        node = _ExprTransformer(placeholders).transform(parse_tree)
    except LarkError:
        pieces = [
            _stringify_resolved_expr_token(_resolve_value(tok, placeholders)) for tok in tokens
        ]
        return None, " ".join(pieces)
    return node, render_expr(node)
