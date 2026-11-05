"""値・条件式のPython文字列への変換。

`pad_dsl`の値型(`VarRef`/`EnumRef`)のみに依存する純粋関数の集まり——`CodegenContext`も
`Node`木も一切知らない、codegen全体の中で最も低レベルな依存の少ないモジュール。
"""
from __future__ import annotations

import re

from ..pad_dsl import EnumRef, VarRef
from ..pad_expr import Atom, BinOp, ExprNode, FuncCall, Paren, UnaryOp

# インデント1段あたりの文字列。`pad_codegen`パッケージ全体がここから参照する
# (循環import回避のため、エントリポイントの`pad_codegen/__init__.py`ではなく
# 依存の少ないこのモジュールに置いている)。
INDENT = "    "

_OPERATOR_MAP = {
    "=": "==",
    "<>": "!=",
    ">": ">",
    ">=": ">=",
    "<": "<",
    "<=": "<=",
    "IN": "in",
    "NOT IN": "not in",
}


_VAR_MARKER_RE = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")


def render_text_template(text: str) -> str:
    """`%VarName%`マーカーを含む文字列値をf-stringに変換する(design/dsl_format_findings.md 知見16)。

    マーカーを含まない文字列は通常の`repr()`と変わらない。マーカーを含む場合は
    トリプルダブルクォートのf-string(改行を含む値でも壊れないように)に変換し、
    `%VarName%`を`{VarName}`に置き換える。リテラル部分のバックスラッシュ・3連続の
    ダブルクォート・波括弧はf-string内で問題を起こさないようエスケープする。
    """
    if not _VAR_MARKER_RE.search(text):
        return repr(text)

    parts: list[str] = []
    pos = 0
    for m in _VAR_MARKER_RE.finditer(text):
        parts.append(_escape_fstring_literal(text[pos : m.start()]))
        parts.append("{" + m.group(1) + "}")
        pos = m.end()
    parts.append(_escape_fstring_literal(text[pos:]))
    return 'f"""' + "".join(parts) + '"""'


def _escape_fstring_literal(segment: str) -> str:
    escaped = segment.replace("\\", "\\\\")
    escaped = escaped.replace('"""', '\\"\\"\\"')
    escaped = escaped.replace("{", "{{").replace("}", "}}")
    return escaped


def render_value(value: object) -> str:
    """DSLの値(`_resolve_value()`の戻り値)をPython式の文字列に変換する。"""
    if isinstance(value, VarRef):
        return value.name
    if isinstance(value, EnumRef):
        # TODO: PADの列挙値(Namespace.Enum.Value)とPython側の対応表がまだ無いため、
        # ひとまず元の完全修飾名を文字列として埋め込む。
        return repr(value.value)
    if isinstance(value, bool):
        return repr(value)
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return render_text_template(value)
    if isinstance(value, list):
        # design/dsl_format_findings.md 知見66・74(実機検証済み、空の場合のみ)——
        # `{ }`空の2次元配列リテラルは`pad_dsl.line_parser._resolve_param_token()`で
        # 空のPythonリスト`[]`に変換される。要素を再帰的にrender_value()へ通すのは
        # 将来非空の配列リテラルが実機確認された場合に備えた一般化で、現状は空リストの
        # みが実際に生成される。
        return "[" + ", ".join(render_value(item) for item in value) + "]"
    raise TypeError(f"Unsupported value type for codegen: {type(value)!r}")


def render_condition(operand1: object, operator: str, operand2: object) -> str:
    try:
        py_operator = _OPERATOR_MAP[operator]
    except KeyError as exc:
        raise ValueError(
            f"Unmapped PAD operator {operator!r}; verify its DSL semantics on real PAD "
            "before adding it to _OPERATOR_MAP"
        ) from exc
    return f"{render_value(operand1)} {py_operator} {render_value(operand2)}"


_UNCONFIRMED_VALUE_SEMANTICS_OPS = frozenset({"mod", "/"})


def render_expr_as_python(node: ExprNode) -> str | None:
    """design/dsl_format_findings.md 知見81で優先順位が実機確認された構文木から、
    実際のPython式を生成する。

    算術演算子`mod`・`/`は値の意味論(`mod`が負数でPythonの`%`と同じ符号規則になるか・`/`が
    常に浮動小数点除算になるか)が実機未検証のため(知見53・81で別の未解決課題として
    明記済み)、木の中にこれらが1つでも含まれる場合は安全に`None`を返す——呼び出し元は
    `RawExpr.text`のTODOフォールバックに委ねる。`SET`式の中に関数呼び出し(`FuncCall`)が
    現れるケースも実機未確認の拡張(`pad_expr`モジュールのdocstring参照)のため同様に扱う。
    """
    if _contains_unconfirmed_value_semantics(node):
        return None
    return _render_expr_as_python(node)


def _contains_unconfirmed_value_semantics(node: ExprNode) -> bool:
    if isinstance(node, Atom):
        return False
    if isinstance(node, Paren):
        return _contains_unconfirmed_value_semantics(node.inner)
    if isinstance(node, UnaryOp):
        return _contains_unconfirmed_value_semantics(node.operand)
    if isinstance(node, FuncCall):
        return True
    if isinstance(node, BinOp):
        if node.op in _UNCONFIRMED_VALUE_SEMANTICS_OPS:
            return True
        return _contains_unconfirmed_value_semantics(
            node.left
        ) or _contains_unconfirmed_value_semantics(node.right)
    raise TypeError(f"Unsupported expr node: {node!r}")


def _render_expr_as_python(node: ExprNode) -> str:
    if isinstance(node, Atom):
        return render_value(node.value)
    if isinstance(node, Paren):
        return f"({_render_expr_as_python(node.inner)})"
    if isinstance(node, UnaryOp):
        if node.op != "NOT":
            raise ValueError(f"Unsupported unary operator: {node.op!r}")
        return f"not {_render_expr_as_python(node.operand)}"
    if isinstance(node, BinOp):
        left = _render_expr_as_python(node.left)
        right = _render_expr_as_python(node.right)
        if node.op == "AND":
            return f"{left} and {right}"
        if node.op == "OR":
            return f"{left} or {right}"
        if node.op == "XOR":
            # design/dsl_format_findings.md 知見81: 実機キャプチャされたXORの被演算子は
            # 常に比較式/真偽値リテラルだったため、論理XORとして解釈する——数値への
            # ビット単位XORの可能性は未検証のまま残る。
            return f"bool({left}) != bool({right})"
        if node.op in ("+", "-", "*"):
            return f"{left} {node.op} {right}"
        if node.op in _OPERATOR_MAP:
            return f"{left} {_OPERATOR_MAP[node.op]} {right}"
        raise ValueError(f"Unsupported binary operator: {node.op!r}")
    raise TypeError(f"Unsupported expr node: {node!r}")

