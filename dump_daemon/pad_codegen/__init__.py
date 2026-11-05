"""ブロック木(`pad_dsl`の`Node`) → Pythonソース文字列を生成する codegen core。

`generate_python()`が唯一の公開エントリポイント。内部は関心事ごとに以下へ分割している:

- `context`: `CodegenContext`(UI要素リポジトリ等、呼び出し1回分の外部情報をイミュータブルに
  保持する——以前の`_active_repository`モジュールグローバル+`try/finally`を置き換える)
- `render`: 値・条件式のPython文字列化(副作用無し)
- `selectors`: UI要素リポジトリからpywinautoセレクタ式を組み立てる共有基盤
- `actions`: `ActionRecord`/`WaitActionRecord`/`IfActionRecord`ごとのcodegen
  (`scripting`/`mouse_keyboard`/`window`/`ui_element`/`wait`/`conditions`、互いに依存しない)

このモジュール自身は「`Node`の種類に応じてどこへ処理を委譲するか」というディスパッチ
(`_generate_node`以下)だけを持ち、個々のアクションの変換ロジックは一切持たない。
"""
from __future__ import annotations

from .actions import generate_action
from .actions.conditions import render_if_window_condition
from .actions.wait import generate as generate_wait_action
from .context import CodegenContext
from .error_tags import resolve_error_tag
from .render import INDENT, render_condition, render_text_template, render_value
from ..pad_dsl import (
    ActionRecord,
    BlockNode,
    BlockRecord,
    CaseDefaultRecord,
    CommentRecord,
    ConditionalNode,
    ElseIfActionRecord,
    ElseIfFunctionRecord,
    ElseIfRecord,
    GuardedNode,
    IfActionRecord,
    IfFunctionRecord,
    IfRecord,
    KeywordRecord,
    LoopForeachRecord,
    LoopRecord,
    LoopWhileRecord,
    Node,
    RawExpr,
    RawRecord,
    SetVariableRecord,
    SwitchNode,
    WaitActionRecord,
)
from ..pad_dsl.types import OnErrorArmHeader
from ..control_repository.types import ControlRepositoryEntry

__all__ = [
    "CodegenContext",
    "INDENT",
    "generate_python",
    "render_condition",
    "render_text_template",
    "render_value",
]


def generate_python(
    nodes: list[Node],
    repository: dict[str, dict[str, ControlRepositoryEntry]] | None = None,
) -> str:
    """ブロック木からスタンドアロンのPythonソースを生成する(末尾改行付き)。

    `repository`は`parse_control_repository()`の戻り値(知見44)。渡された場合、大半の
    未対応UI要素アクションでは`# TODO`コメント中のUI要素ヒントに、実機検証済み(知見56)の
    pywinautoセレクタ式の提案を付記するだけ(あくまでコメント内の提案であり、実行される
    コードそのものは変えない)。例外は`UIAutomation.Click.Click`で、確認済みのパラメータの
    組み合わせ(ClickType: LeftClick等)かつセレクタが解決できる場合に限り、`.click_input()`
    を使った実行コードを生成する。でっち上げたセレクタで動くコードを生成することは無い。
    省略時(`None`)は従来通りの挙動(ヒント無し)のまま完全に後方互換。

    `CodegenContext`を1回だけ組み立て、以降の全ての内部ヘルパーに明示的な引数として
    渡していく(以前のモジュールグローバル`_active_repository`+`try/finally`を廃止した——
    FCISに沿った、再入可能な純粋関数としての実装)。
    """
    ctx = CodegenContext(repository=repository or {})
    body = _generate_block_body(nodes, indent=0, ctx=ctx)
    imports = []
    if any("time.sleep(" in line for line in body):
        imports.append("import time")
    if any("pyautogui." in line for line in body):
        imports.append("import pyautogui")
    if any("Desktop(" in line for line in body):
        imports.append("from pywinauto import Desktop")
    if any("contextlib.redirect_stdout(" in line for line in body):
        imports.append("import contextlib")
        imports.append("import io")
    if any("os.path.split(" in line for line in body):
        imports.append("import os")
    for module_name in (
        "text_actions",
        "datetime_actions",
        "variables_actions",
        "file_actions",
        "folder_actions",
        "compression_actions",
        "cryptography_actions",
        "database_actions",
        "web_actions",
        "xml_actions",
        "pdf_actions",
        "excel_actions",
        "word_actions",
        "powerpoint_actions",
        "cmd_actions",
        "clipboard_actions",
    ):
        if any(f"{module_name}." in line for line in body):
            imports.append(f"from dump_daemon.pad_action_lib import {module_name}")
    imports.sort()
    header = [*imports, ""] if imports else []
    return "\n".join(header + body) + "\n"


def _generate_block_body(nodes: list[Node], indent: int, ctx: CodegenContext) -> list[str]:
    lines: list[str] = []
    for node in nodes:
        lines.extend(_generate_node(node, indent, ctx))
    return lines


def _ensure_nonempty_suite(lines: list[str], indent: int) -> list[str]:
    """Pythonの`except:`/`if:`等の本体として有効になるよう、`pass`を補う。

    `_generate_block_body`は未対応のキーワード/アクションを`# TODO`コメント行として
    出力することがある(でっち上げたAPI呼び出しを生成しないための意図的な挙動)。
    その結果、本体が「コメント行だけ」になるケースがあり、これは見た目上は非空でも
    Pythonの構文的には空の suite と同じで`IndentationError`になる(知見40の
    `ON BLOCK ERROR`本体が`NEXT ACTION`だけのケースで実際に発覚したバグ)。
    「実質的な文が1つも無い」場合にだけ`pass`を追加する。
    """
    if any(line.strip() and not line.strip().startswith("#") for line in lines):
        return lines
    return [*lines, f"{INDENT * indent}pass"]


def _generate_node(node: Node, indent: int, ctx: CodegenContext) -> list[str]:
    prefix = INDENT * indent
    if isinstance(node, SetVariableRecord):
        if isinstance(node.value, RawExpr):
            # design/dsl_format_findings.md 知見53: AND/OR/XOR/NOT・算術演算子の実機DSL
            # 表現は確認済みだが、演算子の優先順位やmod/XORの境界値での意味論差異が
            # PADとPythonで一致する保証がまだ無いため、でっち上げた変換式を出力せず
            # TODOに倒す(知見50等と同じ安全側フォールバックの方針)。
            return [
                f"{prefix}# TODO: map PAD compound expression for variable "
                f"'{node.var_name}': {node.value.text}",
                f"{prefix}{node.var_name} = None  # unresolved compound expression, see TODO above",
            ]
        return [f"{prefix}{node.var_name} = {render_value(node.value)}"]
    if isinstance(node, ConditionalNode):
        return _generate_conditional(node, indent, ctx)
    if isinstance(node, SwitchNode):
        return _generate_switch(node, indent, ctx)
    if isinstance(node, GuardedNode):
        return _generate_guarded(node, indent, ctx)
    if isinstance(node, BlockNode):
        return _generate_loop_block(node, indent, ctx)
    if isinstance(node, KeywordRecord):
        return _generate_keyword(node, indent)
    if isinstance(node, ActionRecord):
        return generate_action(node, indent, ctx)
    if isinstance(node, WaitActionRecord):
        return generate_wait_action(node, indent, ctx)
    if isinstance(node, CommentRecord):
        # 複数行コメント(`/# ... #/`)はPythonの`#`コメントが1行ずつしか続けられない
        # ため、埋め込まれた改行ごとに別の`#`行として出力する。
        if "\n" in node.text:
            return [f"{prefix}# {line}".rstrip() for line in node.text.split("\n")]
        return [f"{prefix}# {node.text}".rstrip()]
    if isinstance(node, RawRecord):
        return [f"{prefix}# TODO: unparsed DSL line: {node.text}"]
    raise TypeError(f"Unsupported node type for codegen: {type(node)!r}")


def _generate_conditional(node: ConditionalNode, indent: int, ctx: CodegenContext) -> list[str]:
    prefix = INDENT * indent
    lines: list[str] = []
    for header, arm_body in node.arms:
        if isinstance(header, IfRecord):
            lines.append(f"{prefix}if {render_condition(header.operand1, header.operator, header.operand2)}:")
        elif isinstance(header, ElseIfRecord):
            lines.append(f"{prefix}elif {render_condition(header.operand1, header.operator, header.operand2)}:")
        elif isinstance(header, KeywordRecord) and header.name == "ELSE":
            lines.append(f"{prefix}else:")
        elif isinstance(header, (IfFunctionRecord, ElseIfFunctionRecord)):
            # Contains/NotContains/IsEmpty/IsNotEmptyの関数呼び出し条件
            # (design/dsl_format_findings.md 知見18-2・75で実機確認済み)。知見75で、
            # クリップボードへのペースト+コピー読み取りによる往復確認で、この4つの関数名
            # (綴りの揺れ——DoesNotContain等——は全て"Has error"になり不採用と対照実験済み)
            # がPAD自身に認識されることを確認したため、この4つに限定して変換する。それ以外の
            # 未知の関数名は、誤った意味論をでっち上げるよりはっきり失敗させる。
            condition = _render_function_condition(header)
            if condition is None:
                raise NotImplementedError(
                    f"Function-call condition {header.function_name}(...) is not yet supported "
                    "by codegen; its Python semantics haven't been verified on real PAD."
                )
            keyword = "if" if isinstance(header, IfFunctionRecord) else "elif"
            lines.append(f"{prefix}{keyword} {condition}:")
        elif isinstance(header, (IfActionRecord, ElseIfActionRecord)):
            # 「If window」「If window contains element」等の[ConditionAction]カテゴリ
            # (design/dsl_format_findings.md 知見54)。条件式を誤って翻訳すると制御フローが
            # 丸ごと反転するという、SET文の右辺(知見53)よりもさらに危険な失敗モードになるため、
            # 原則でっち上げた真偽値を出力せずはっきり失敗させる。例外は`UIAutomation.IfWindow.*`
            # で、`IsOpen`/`IsNotOpen`/`IsFocused`/`IsNotFocused`という4通りの単純な真偽値
            # (否定の有無のみ、複雑な設定モードを持たない)であることが確認できたため、知見56の
            # セレクタ組み立てと組み合わせてここだけ変換する(`actions.conditions`参照)。
            # `IfImage`/`IfWindowContains`は複数の設定可能なサブモード(画像の一致アルゴリズム・
            # テキスト包含モード等)を持ち`IfWindow`ほど単純ではないため、依然としてでっち上げず
            # 失敗させる。
            condition = render_if_window_condition(header, ctx)
            if condition is None:
                raise NotImplementedError(
                    f"Action-call condition {header.action_id}(...) is not yet supported by codegen; "
                    "its Python semantics (and UI element selector) haven't been verified on real PAD."
                )
            keyword = "if" if isinstance(header, IfActionRecord) else "elif"
            lines.append(f"{prefix}{keyword} {condition}:")
        else:
            raise TypeError(f"Unexpected conditional arm header: {header!r}")
        lines.extend(_ensure_nonempty_suite(_generate_block_body(arm_body, indent + 1, ctx), indent + 1))
    return lines


def _render_function_condition(header: IfFunctionRecord | ElseIfFunctionRecord) -> str | None:
    """知見75で実機確認済みの4関数(Contains/NotContains/IsEmpty/IsNotEmpty)のみPythonの
    真偽値式に変換する。未知の関数名は`None`を返し、呼び出し元が安全にTODOへ倒す。"""
    args = [render_value(a) for a in header.args]
    if header.function_name == "Contains" and len(args) == 2:
        return f"{args[1]} in {args[0]}"
    if header.function_name == "NotContains" and len(args) == 2:
        return f"{args[1]} not in {args[0]}"
    if header.function_name == "IsEmpty" and len(args) == 1:
        return f"not {args[0]}"
    if header.function_name == "IsNotEmpty" and len(args) == 1:
        return f"bool({args[0]})"
    return None


def _generate_switch(node: SwitchNode, indent: int, ctx: CodegenContext) -> list[str]:
    """`SwitchNode` → `if`/`elif`/`else`(design/dsl_format_findings.md 知見33で実機確認した
    `CASE <operator> <value>`構文通り、`CASE`自身の演算子を`_OPERATOR_MAP`経由で変換する——
    `==`固定ではない。`CaseRecord.operator`が`None`の場合(ソース上`SemiComparison.Operator`は
    nullableだが実機では未確認)は、素のcase値として暗黙の等価比較を仮定する)。
    """
    prefix = INDENT * indent
    lines: list[str] = []
    for i, (header, arm_body) in enumerate(node.arms):
        if isinstance(header, CaseDefaultRecord):
            lines.append(f"{prefix}else:")
        else:
            keyword = "if" if i == 0 else "elif"
            operator = header.operator if header.operator is not None else "="
            condition = render_condition(node.expression, operator, header.value)
            lines.append(f"{prefix}{keyword} {condition}:")
        lines.extend(_ensure_nonempty_suite(_generate_block_body(arm_body, indent + 1, ctx), indent + 1))
    return lines


def _generate_guarded(node: GuardedNode, indent: int, ctx: CodegenContext) -> list[str]:
    """`GuardedNode`(`ON ERROR`/`ON BLOCK ERROR`で保護された文) → `try`/`except`。

    design/dsl_format_findings.md 知見34で実機確認したのは「All errors (default)」
    (名前無しcatch-all、1アームのみ)に本体アクションを追加し「Continue flow run」を選んだ
    ケースのみ——そのDSL上の意味論(エラーを捕捉してハンドラを実行し、続行する)は
    `try`/`except`に自然に対応する。知見36で、名前付きケース(`ON ERROR <CaseName>`)や
    複数アームが区切り無しに連続しうることも実機確認した。

    名前付きケース(例: `RunPythonScriptError`)は、PADの各アクションごとに固定の文字列タグで
    あり、.NET/Pythonの例外**型**への対応表という発想自体が実態と違うことが確認できた。しかし
    知見73の結線により、`pad_action_lib`の各モジュールはこのタグ名と同じクラス名で
    `PadActionError`を継承した例外を実際に投げるようになった——つまり、タグ名がそのまま
    Pythonの例外クラス名として実在する場合は、でっち上げではなく確認済みの対応関係として
    `except <そのクラス>:`に変換できる(`error_tags.resolve_error_tag()`、複数ファミリーが
    同名タグを独立に持つ場合は全てをタプルで広く捕捉)。名前付きアームが1つでも未知のタグ
    (`pad_action_lib`のスコープ外、例: `Scripting`系)を使っている場合は、全アームを安全に
    `# TODO`へ丸ごとフォールバックする(部分的にだけ変換すると、保護範囲が歯抜けになり
    誤解を招くため)。`node.node`が`BlockNode(BlockRecord)`の場合(知見40の`ON BLOCK ERROR`)も
    構造は全く同じなので、このロジックをそのまま流用できる。
    """
    prefix = INDENT * indent
    except_clauses = _resolve_except_clauses(node.on_error.arms)
    if except_clauses is None:
        lines = list(_generate_node(node.node, indent, ctx))
        lines.append(f"{prefix}# TODO: ON ERROR/ON BLOCK ERROR handling not converted (named/multiple error cases)")
        return lines
    lines = [f"{prefix}try:"]
    lines.extend(_generate_node(node.node, indent + 1, ctx))
    for except_expr, handler_body in except_clauses:
        lines.append(f"{prefix}except {except_expr}:")
        lines.extend(_ensure_nonempty_suite(_generate_block_body(handler_body, indent + 1, ctx), indent + 1))
    return lines


def _resolve_except_clauses(
    arms: list[tuple[OnErrorArmHeader, list[Node]]],
) -> list[tuple[str, list[Node]]] | None:
    """各アームの`case_name`を`except`節の型表現へ解決する。1つでも未知のタグがあれば`None`。"""
    clauses: list[tuple[str, list[Node]]] = []
    for header, body in arms:
        if header.case_name is None:
            clauses.append(("Exception", body))
            continue
        refs = resolve_error_tag(header.case_name)
        if refs is None:
            return None
        expr = refs[0] if len(refs) == 1 else f"({', '.join(refs)})"
        clauses.append((expr, body))
    return clauses


def _generate_loop_block(node: BlockNode, indent: int, ctx: CodegenContext) -> list[str]:
    prefix = INDENT * indent
    header = node.header
    if isinstance(header, BlockRecord):
        # design/dsl_format_findings.md 知見40: BLOCKはPADの「アクショングループ」で、
        # それ自体はPython側に対応する制御構造を持たない純粋なスコープ区切り。
        # ON BLOCK ERRORによる保護はGuardedNodeのtry/exceptが担うため、ここでは本体を
        # 追加のインデント無しでそのまま展開するだけでよい。
        return _ensure_nonempty_suite(_generate_block_body(node.body, indent, ctx), indent)
    if isinstance(header, LoopRecord):
        start = render_value(header.start)
        end = render_value(header.end)
        step = render_value(header.step)
        # design/dsl_format_findings.md 知見51(実機検証済み): PADのLOOPはendを含まない
        # (Pythonのrange()と同じセマンティクス)。`LOOP X FROM 1 TO 3 STEP 1`を実機で
        # 実行し、ループ本体が2回(X=1,2)しか実行されないことを実測で確認した。
        header_line = f"{prefix}for {header.loop_var} in range({start}, {end}, {step}):"
    elif isinstance(header, LoopForeachRecord):
        header_line = f"{prefix}for {header.item_var} in {render_value(header.collection)}:"
    elif isinstance(header, LoopWhileRecord):
        header_line = f"{prefix}while {render_condition(header.operand1, header.operator, header.operand2)}:"
    else:
        raise TypeError(f"Unexpected block header: {header!r}")
    lines = [header_line]
    lines.extend(_ensure_nonempty_suite(_generate_block_body(node.body, indent + 1, ctx), indent + 1))
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
    if node.name == "LABEL" and len(node.args) == 1:
        # design/dsl_format_findings.md 知見48(実機検証済み)。`LABEL <名前>`自体は単なる
        # ジャンプ先マーカーで、対応する`GOTO <名前>`がPythonの`goto`文の不在によりどのみち
        # `# TODO`に倒れる(下のフォールバック)ため、位置が分かるようコメントとして残すだけに
        # 留める——でっち上げた制御フロー(例外やネストしたwhileへの書き換え)は行わない。
        return [f"{prefix}# label: {node.args[0]}"]
    return [f"{prefix}# TODO: unmapped keyword: {node.name} {' '.join(node.args)}".rstrip()]
