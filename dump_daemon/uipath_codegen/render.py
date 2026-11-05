"""`uipath_dsl.types.Expr`(`VbExpr`/`Literal`/`None`)をPython式のソース文字列へ
変換する。`pad_codegen.render`と同じ関心事の切り出し(値・条件式の文字列化、
副作用無し)。

**失敗モードの方針**(`pad_codegen`の`SetVariableRecord`/`IfActionRecord`
処理と同じ): この関数は「安全に変換できない」と判断した入力に対して
`NotImplementedError`を送出する。呼び出し側(`uipath_codegen/__init__.py`)が
これをどう扱うか(代入先なら`# TODO`+プレースホルダへ倒す、条件式なら
でっち上げた真偽値で制御フローを誤らせるよりコード生成全体を失敗させる)を
文脈ごとに決める。
"""
from __future__ import annotations

from dump_daemon.uipath_expr import (
    ArrayLiteral,
    BinOp,
    BoolLiteral,
    ExprNode,
    FuncCall,
    Ident,
    InterpolatedString,
    NothingLiteral,
    NumberLiteral,
    Paren,
    StringLiteral,
    UnaryOp,
    parse_vb_expr,
)

from ..uipath_dsl.types import Expr, Literal, VbExpr

# design/uipath_vb_expression_mapping.md で実機確認済み(知見32・36)の
# 型変換関数のうち、単純な名前変換で安全に対応できるもの。`CStr`は`str()`で
# 十分(VBの`&`に対する`str()`明示挿入と同じ理由で、Pythonの`str()`は`CStr`の
# 「何でも文字列化する」挙動と一致する)。`CDbl`も`float()`で十分(浮動小数点
# への変換は丸めの余地が無く情報を失わない)。`CInt`/`CBool`は値そのものが
# VBとPythonで食い違いうる(知見42と同じ種類の問題)ため、個別に
# `_render_func_call`内で処理する(下記参照)。
_CAST_FUNCS = {
    "cstr": "str",
    "cdbl": "float",
}

# design/uipath_vb_expression_mapping.md「確認済み演算子の変換上の注意点」
# (2026-11-05確定分): And/Or/Xorは全て、両オペランドを括弧で囲んだ上で
# Pythonのビット演算子(&/|/^)へ1対1で変換する——Pythonのboolがintの
# サブクラスであるため、ブール/整数どちらのオペランドでも意味論が一致する。
_BITWISE_OPS = {"and": "&", "or": "|", "xor": "^"}
_SHORT_CIRCUIT_OPS = {"andalso": "and", "orelse": "or"}
_COMPARISON_OPS = {
    "=": "==",
    "<>": "!=",
    "<": "<",
    ">": ">",
    "<=": "<=",
    ">=": ">=",
}


def _render_node(node: ExprNode) -> str:
    if isinstance(node, Ident):
        return node.name
    if isinstance(node, StringLiteral):
        return repr(node.value)
    if isinstance(node, NumberLiteral):
        return repr(node.value)
    if isinstance(node, BoolLiteral):
        return "True" if node.value else "False"
    if isinstance(node, NothingLiteral):
        return "None"
    if isinstance(node, ArrayLiteral):
        items = ", ".join(_render_node(i) for i in node.items)
        return f"[{items}]"
    if isinstance(node, InterpolatedString):
        # design/uipath_transpiler_roadmap.md 知見36/uipath_exprのdocstring
        # 参照: 文字列補間`$"..."`の中身(`{expr}`)はuipath_exprがまだ
        # 構文解析していないため、安全にPython f-stringへ変換できない。
        raise NotImplementedError(
            f"string interpolation is not yet supported by codegen: {node.raw}"
        )
    if isinstance(node, Paren):
        return f"({_render_node(node.inner)})"
    if isinstance(node, UnaryOp):
        op = node.op.lower()
        if op == "not":
            # 既知の未解決リスク(design/uipath_vb_expression_mapping.md参照):
            # VBの`Not`はAnd/Or/Xorと同じ型依存の二重性質を持ち、Boolean
            # オペランドには論理否定、Integerオペランドにはビット反転
            # (2の補数)として働く。Pythonの`not x`はBooleanの場合のみ
            # 正しく、Integerの場合は`~x`が必要——ただしAnd/Or/Xorの
            # `&`/`|`/`^`と違い、Booleanにも正しく働く単一のPython演算子が
            # 無い(`~True`は`-2`になり論理否定と一致しない)。知見32・36の
            # 実機確認例は`Not True`(Boolean)のみで、Integerオペランドの
            # 実例・実機検証が無いため、型を判定するでっち上げコードを
            # 挿入せず、確認済みのBoolean前提のまま`not (...)`とする。
            return f"not ({_render_node(node.operand)})"
        if op in ("-", "+"):
            return f"{node.op}({_render_node(node.operand)})"
        raise NotImplementedError(f"unsupported unary operator: {node.op!r}")
    if isinstance(node, FuncCall):
        return _render_func_call(node)
    if isinstance(node, BinOp):
        return _render_bin_op(node)
    raise NotImplementedError(f"unsupported expression node: {node!r}")


def _vb_cbool_of_string_literal(text: str) -> bool:
    """VBの`CBool`は文字列引数を`"True"`/`"False"`(大文字小文字区別無し)と
    認識するか、さもなくば数値として評価して非ゼロかどうかで判定する——
    それ以外の文字列は実行時に型不一致例外になる(参考: O'Reilly VB.NET
    言語リファレンス、.NET公式ランタイムソース`BooleanType.FromString`)。
    Pythonの`bool(文字列)`は空文字列以外は常に`True`になり挙動が違う
    (例: `bool("False")`は`True`、知見42と同じ種類の食い違い)ため、
    リテラル文字列の場合はコード生成時に実際の変換結果を確定させて
    そのまま埋め込む(`_render_func_call`参照)。"""
    normalized = text.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    try:
        return float(text) != 0
    except ValueError:
        raise NotImplementedError(
            f"CBool({text!r}): not 'True'/'False' or numeric — VB would raise "
            "a type-mismatch exception at runtime, refusing to guess the result"
        ) from None


def _render_func_call(node: FuncCall) -> str:
    key = node.name.lower()
    args = [_render_node(a) for a in node.args]
    if key == "cint":
        # VBの`CInt`は切り捨てではなく四捨五入(銀行丸め/round-half-to-even、
        # 知見42の`Mod`/`\`と同じ系統の「公式ドキュメントで確定した値の
        # 食い違い」)——Pythonの`round()`も単一引数ではデフォルトで
        # round-half-to-evenなので、公式ドキュメント記載例(0.5→0、1.5→2、
        # 2.5→2)とPythonの`round()`の挙動が一致することを確認済み
        # (単純な`int()`は切り捨てで食い違う、例: `int(1.5)`は`1`)。
        # 文字列引数も`float()`を経由すれば数値と同じ経路で丸められる。
        if len(args) != 1:
            raise NotImplementedError("CInt expects exactly 1 argument")
        return f"round(float({args[0]}))"
    if key == "cbool":
        if len(args) != 1:
            raise NotImplementedError("CBool expects exactly 1 argument")
        arg_node = node.args[0]
        if isinstance(arg_node, StringLiteral):
            return repr(_vb_cbool_of_string_literal(arg_node.value))
        # リテラル文字列以外(変数参照・関数呼び出し等)は実行時の型が
        # コード生成時には分からない——文字列型であれば`bool(x)`は
        # `_vb_cbool_of_string_literal`と同じ理由で誤りうる既知の限界
        # (design/uipath_vb_expression_mapping.md参照)。数値/真偽値型なら
        # `bool(x)`はVBのCBoolと一致するため、でっち上げた型チェックを
        # 挿入するより素直な`bool(x)`のままにする。
        return f"bool({args[0]})"
    if key in _CAST_FUNCS:
        if len(args) != 1:
            raise NotImplementedError(f"{node.name} expects exactly 1 argument")
        return f"{_CAST_FUNCS[key]}({args[0]})"
    if key == "isnothing":
        if len(args) != 1:
            raise NotImplementedError("IsNothing expects exactly 1 argument")
        return f"({args[0]} is None)"
    if key == "string.isnullorempty":
        if len(args) != 1:
            raise NotImplementedError("String.IsNullOrEmpty expects exactly 1 argument")
        return f"(not ({args[0]}))"
    if key == "if" and len(args) == 3:
        # 三項演算子`If(cond, whenTrue, whenFalse)`(知見36)。
        return f"({args[1]} if {args[0]} else {args[2]})"
    raise NotImplementedError(
        f"unsupported function call (not in the confirmed Tier1 set): {node.name}(...)"
    )


def _render_bin_op(node: BinOp) -> str:
    op = node.op.lower()
    left = _render_node(node.left)
    right = _render_node(node.right)
    if op in _COMPARISON_OPS:
        return f"({left}) {_COMPARISON_OPS[op]} ({right})"
    if op == "is":
        return f"({left}) is ({right})"
    if op == "isnot":
        return f"({left}) is not ({right})"
    if op == "&":
        # VBの`&`は非文字列オペランドを自動的に文字列化するが、Pythonの`+`は
        # しない——str()を明示的に挟む(design/uipath_vb_expression_mapping.md
        # 「確認済み演算子の変換上の注意点」)。
        return f"str({left}) + str({right})"
    if op == "+":
        return f"({left}) + ({right})"
    if op == "-":
        return f"({left}) - ({right})"
    if op == "mod":
        # VBの`Mod`は余りの符号が**被除数**の符号に従う(Microsoft Learn「Mod
        # Operator」、公式の変換式`a - (b * Fix(a / b))`どおり——例:
        # `-7 Mod 3`は`-1`)。Pythonの`%`は符号が**除数**に従う床除算の余り
        # (`-7 % 3`は`2`)で、両オペランドの符号が異なる場合に値が食い違う
        # ため単純な`%`への変換は不可——VBの公式変換式をそのまま再現する
        # (`int()`はPythonのtruncate-toward-zeroで、VBの`Fix()`と一致)。
        return f"({left}) - (({right}) * int(({left}) / ({right})))"
    if op == "\\":
        # VBの`\`(整数除算)はゼロ方向への切り捨て(truncation、Microsoft
        # Learn「\ Operator」——例: `67 \ -3`は`-22`)。Pythonの`//`は
        # 負方向への床除算(floor、`67 // -3`は`-23`)で、両オペランドの
        # 符号が異なる場合に値が食い違うため単純な`//`への変換は不可。
        # `int()`はtruncate-toward-zeroなので`int(a / b)`で正しく再現できる。
        return f"int(({left}) / ({right}))"
    if op == "*":
        return f"({left}) * ({right})"
    if op == "/":
        return f"({left}) / ({right})"
    if op == "^":
        # 既知の未解決リスク(design/uipath_vb_expression_mapping.md参照):
        # VBの`^`は常にDouble型で計算される(Microsoft Learn「^ Operator」)
        # ため`2^2`はVBでは`4.0`相当になるが、Pythonの`2 ** 2`は整数`4`の
        # まま——通常は数値として等価だが文字列化の見た目が変わりうる。
        # さらに負の底に非整数の指数を与えた場合(例: `(-8) ^ 0.5`)、
        # Pythonの`**`は複素数を返すが、VB側の挙動(NaN相当か実行時例外か)
        # を公式ドキュメントで確認できておらず実機未検証——でっち上げた
        # 分岐処理は挿入せず、単純な`**`変換のまま残す。
        return f"({left}) ** ({right})"
    if op in _BITWISE_OPS:
        return f"({left}) {_BITWISE_OPS[op]} ({right})"
    if op in _SHORT_CIRCUIT_OPS:
        return f"({left}) {_SHORT_CIRCUIT_OPS[op]} ({right})"
    raise NotImplementedError(f"unsupported binary operator: {node.op!r}")


def render_expr(expr: Expr) -> str:
    """`Expr`(`VbExpr`/`Literal`/`None`)をPython式のソース文字列に変換する。

    `VbExpr`は`uipath_expr.parse_vb_expr()`でその場で構文解析する
    (`uipath_dsl`とは意図的に疎結合——design/uipath_transpiler_roadmap.md
    Phase 3の「次にやること」参照)。構文解析自体が失敗した場合、または
    構文解析には成功したがこの関数がまだ対応していない構文(文字列補間の
    中身・未対応の関数呼び出し等)だった場合は、いずれも`NotImplementedError`
    を送出する——架空のPython式をでっち上げて返すことは無い。

    `Literal`は実機データ上すべて文字列値だった(知見2・5等)ため、v1では
    無条件に文字列リテラルとして扱う——Int32/Boolean等の非文字列`Literal`は
    実例が無く未対応(既知の簡略化)。
    """
    if expr is None:
        return "None"
    if isinstance(expr, Literal):
        return repr(expr.value)
    if isinstance(expr, VbExpr):
        tree, _ = parse_vb_expr(expr.text)
        if tree is None:
            raise NotImplementedError(f"VB expression failed to parse: {expr.text}")
        return _render_node(tree)
    raise TypeError(f"Unsupported Expr type: {type(expr)!r}")
