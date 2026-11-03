"""`build_block_tree()`が返すブロック木からPythonソースコードを生成する最小限のコードジェネレーター。

design/dsl_format_findings.md で実機検証した文法のうち、`pad_dsl_parser.py`が構造化
できている範囲(SET/IF+ELSE IF+ELSE/LOOP系3種/EXIT・NEXT LOOP)だけを対象にした
プロトタイプ。UI automation操作(クリック・キー入力等)のpywinauto/pyautogui変換は
別途「アクションID→API呼び出し」の対応表が必要で、本モジュールはまだそこまで踏み込んで
いない——未対応のアクションは実在しないAPIをでっち上げるのではなく、`# TODO`コメントを
出力するだけに留める。

対応範囲:
- `SetVariableRecord` → 代入文
- `ConditionalNode` → `if`/`elif`/`else`
- `BlockNode(LoopRecord)` → `for ... in range(...)`
  (**未検証の前提**: PADの`Start from`〜`End to`は両端を含むと仮定し`range(start, end+1, step)`
  としている。実際にループ本体が複数回実行されるか実機で確認するまでは未確定)
- `BlockNode(LoopForeachRecord)` → `for ... in ...`
- `BlockNode(LoopWhileRecord)` → `while ...`
- `KeywordRecord(WAIT)` → `time.sleep(...)`
- `KeywordRecord(EXIT LOOP)` / `KeywordRecord(NEXT LOOP)` → `break`/`continue`
- `ActionRecord`(`Scripting.RunPythonScript.*`) → `PythonCode`パラメータの中身をそのまま展開
  (他のUI automationアクションはまだ対応していないため`# TODO`コメントを出力する)

演算子は実機検証済みの`=`/`<`のみ`_OPERATOR_MAP`に登録している。未検証の演算子
(`<>`/`>`/`>=`/`<=`/文字列の`contains`等)に遭遇した場合は、誤った意味論を生成しないよう
`ValueError`を送出する。
"""
from __future__ import annotations

from .pad_dsl_parser import (
    ActionRecord,
    BlockNode,
    ConditionalNode,
    ElseIfRecord,
    EnumRef,
    IfRecord,
    KeywordRecord,
    LoopForeachRecord,
    LoopRecord,
    LoopWhileRecord,
    Node,
    RawRecord,
    SetVariableRecord,
    VarRef,
)

INDENT = "    "

# 実機検証済みの演算子のみ(design/dsl_format_findings.md 知見6・9)。
_OPERATOR_MAP = {
    "=": "==",
    "<": "<",
}


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
    if isinstance(value, (int, float, str)):
        return repr(value)
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


def generate_python(nodes: list[Node]) -> str:
    """ブロック木からスタンドアロンのPythonソースを生成する(末尾改行付き)。"""
    body = _generate_block_body(nodes, indent=0)
    needs_time = any("time.sleep(" in line for line in body)
    header = ["import time", ""] if needs_time else []
    return "\n".join(header + body) + "\n"


def _generate_block_body(nodes: list[Node], indent: int) -> list[str]:
    lines: list[str] = []
    for node in nodes:
        lines.extend(_generate_node(node, indent))
    return lines


def _generate_node(node: Node, indent: int) -> list[str]:
    prefix = INDENT * indent
    if isinstance(node, SetVariableRecord):
        return [f"{prefix}{node.var_name} = {render_value(node.value)}"]
    if isinstance(node, ConditionalNode):
        return _generate_conditional(node, indent)
    if isinstance(node, BlockNode):
        return _generate_loop_block(node, indent)
    if isinstance(node, KeywordRecord):
        return _generate_keyword(node, indent)
    if isinstance(node, ActionRecord):
        return _generate_action(node, indent)
    if isinstance(node, RawRecord):
        return [f"{prefix}# TODO: unparsed DSL line: {node.text}"]
    raise TypeError(f"Unsupported node type for codegen: {type(node)!r}")


def _generate_conditional(node: ConditionalNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    lines: list[str] = []
    for header, arm_body in node.arms:
        if isinstance(header, IfRecord):
            lines.append(f"{prefix}if {render_condition(header.operand1, header.operator, header.operand2)}:")
        elif isinstance(header, ElseIfRecord):
            lines.append(f"{prefix}elif {render_condition(header.operand1, header.operator, header.operand2)}:")
        elif isinstance(header, KeywordRecord) and header.name == "ELSE":
            lines.append(f"{prefix}else:")
        else:
            raise TypeError(f"Unexpected conditional arm header: {header!r}")
        lines.extend(_generate_block_body(arm_body, indent + 1) or [f"{INDENT * (indent + 1)}pass"])
    return lines


def _generate_loop_block(node: BlockNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    header = node.header
    if isinstance(header, LoopRecord):
        start = render_value(header.start)
        end = render_value(header.end)
        step = render_value(header.step)
        # 未検証の前提: PADのLoopはstart〜endを両端含むと仮定(モジュールdocstring参照)。
        header_line = f"{prefix}for {header.loop_var} in range({start}, ({end}) + 1, {step}):"
    elif isinstance(header, LoopForeachRecord):
        header_line = f"{prefix}for {header.item_var} in {render_value(header.collection)}:"
    elif isinstance(header, LoopWhileRecord):
        header_line = f"{prefix}while {render_condition(header.operand1, header.operator, header.operand2)}:"
    else:
        raise TypeError(f"Unexpected block header: {header!r}")
    lines = [header_line]
    lines.extend(_generate_block_body(node.body, indent + 1) or [f"{INDENT * (indent + 1)}pass"])
    return lines


def _generate_keyword(node: KeywordRecord, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.name == "WAIT":
        seconds = node.args[0] if node.args else "0"
        return [f"{prefix}time.sleep({seconds})"]
    if node.name == "EXIT" and node.args == ["LOOP"]:
        return [f"{prefix}break"]
    if node.name == "NEXT" and node.args == ["LOOP"]:
        return [f"{prefix}continue"]
    return [f"{prefix}# TODO: unmapped keyword: {node.name} {' '.join(node.args)}".rstrip()]


def _generate_action(node: ActionRecord, indent: int) -> list[str]:
    prefix = INDENT * indent
    if node.action_id.startswith("Scripting.RunPythonScript"):
        code = node.params.get("PythonCode")
        if isinstance(code, str):
            lines = [f"{prefix}{line}" if line else "" for line in code.splitlines()]
            if node.output_var:
                # PADのScriptOutputは専用の仕組みであり、単純な戻り値束縛ではないため
                # 自動では生成しない——TODOとして明示する。
                lines.append(f"{prefix}# TODO: bind {node.output_var} to this script's output if needed")
            return lines
    return [f"{prefix}# TODO: map PAD action: {node.action_id}"]
