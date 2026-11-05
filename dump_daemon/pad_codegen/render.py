"""値・条件式のPython文字列への変換。

`pad_dsl`の値型(`VarRef`/`EnumRef`)のみに依存する純粋関数の集まり——`CodegenContext`も
`Node`木も一切知らない、codegen全体の中で最も低レベルな依存の少ないモジュール。
"""
from __future__ import annotations

import re

from ..pad_dsl import EnumRef, VarRef

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

