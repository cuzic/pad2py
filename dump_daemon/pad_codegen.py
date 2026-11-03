"""`build_block_tree()`が返すブロック木からPythonソースコードを生成する最小限のコードジェネレーター。

design/dsl_format_findings.md で実機検証した文法のうち、`pad_dsl_parser.py`が構造化
できている範囲(SET/IF+ELSE IF+ELSE/LOOP系3種/EXIT・NEXT LOOP)だけを対象にした
プロトタイプ。未対応のアクションは実在しないAPIをでっち上げるのではなく、`# TODO`コメントを
出力するだけに留める。

**pywinauto / pyautoguiの使い分け基準**(`research_notes/Power Automate Desktop Python変換調査/02_action_mapping.md`
で整理した方針に準拠): PADのアクションカテゴリ単位で決まる。
- 「Mouse and keyboard」カテゴリ(座標・物理入力ベース: Send keys/Move mouse/
  Send mouse click/Press release key等)→ **pyautogui**。マウス/キーボードを実際に
  操作する「物理モード」に相当し、ウィンドウオブジェクトを介さず画面座標・フォーカス
  ベースで完結するため。
- 「UI automation」カテゴリの「Windows」サブグループ(Set window state/Move window/
  Resize window/Close window等、ウィンドウ単位の検索・状態操作)→ **pywinauto**
  (`Desktop`/`WindowSpecification` API)。`Find window mode`(By title/class等)で
  ウィンドウを特定し、取得したオブジェクトに対してメソッド呼び出しを行うという構造が
  pywinautoの`Desktop().window(...)`の設計とそのまま対応するため。
- 同カテゴリの要素レベル操作(Click UI element in window等、UIA要素セレクタが必要な
  もの)もpywinauto対応になる見込みだが、セレクタ自体のDSL表現(`By window UI element`
  モード)がまだ未解明のため本モジュールは未対応。

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
- `ActionRecord`(`MouseAndKeyboard.SendKeys.FocusAndSendKeys`) → `pyautogui.typewrite(...)`
  (design/dsl_format_findings.md 知見19。**未検証の前提**: `TextToSend`が特殊キー記法
  (「Insert special keys」で挿入される`{ENTER}`等)を含まない、素のリテラルテキストである
  場合のみを対象にしている——特殊キー記法のDSL表現自体をまだ実機確認していないため、
  含んでいた場合の変換は未対応)
- `ActionRecord`(`MouseAndKeyboard.MoveMouse`) → `pyautogui.moveTo(x, y)`(知見20。
  実機検証済みの`RelativeTo: Screen`・`MovementStyle: Instant`の組み合わせのときだけ変換し、
  それ以外(Window基準・Smoothly等、未検証)は`# TODO`のままにする)
- `ActionRecord`(`MouseAndKeyboard.SendMouseClick.Click`) → `pyautogui.click()`(知見21。
  実機検証済みの`ClickType: LeftClick`のときだけ変換し、それ以外(Right click/Double click等
  7種、未検証)は`# TODO`のままにする。`MillisecondsDelay`が0でなければクリック前に
  `time.sleep(...)`を挿入する)
- `ActionRecord`(`MouseAndKeyboard.PressReleaseKey.PressKey`/`...ReleaseKey`) →
  `pyautogui.keyDown(...)`/`pyautogui.keyUp(...)`(知見23。Control/Alt/Shift/Winのうち
  ちょうど1つだけ`True`の場合のみ変換し、0個または複数同時`True`(未検証)は`# TODO`のまま)
- `ActionRecord`(`UIAutomation.SetWindowState.SetStateByTitleClass`) →
  `Desktop(backend='uia').window(title=...).maximize()/minimize()/restore()`(知見24。
  `Window class`を併用しない(空文字列の)場合のみ変換し、クラス名併用(未検証)は
  `# TODO`のまま。`import pyautogui`と同様、使用時のみ`from pywinauto import Desktop`を
  先頭に出力する)
- 他のUI automationアクションも含め、未対応のものは架空のAPI呼び出しをでっち上げず
  `# TODO`コメントを出力する
- 文字列値中の`%VarName%`マーカー(design/dsl_format_findings.md 知見16)→ f-string化
  (`render_text_template()`。マーカーを含まない文字列は通常の`repr()`のまま)

演算子は実機検証済みの6つの比較演算子(`=`/`<>`/`>`/`>=`/`<`/`<=`、design/dsl_format_findings.md
知見18)のみ`_OPERATOR_MAP`に登録している。未知の演算子に遭遇した場合は、誤った意味論を
生成しないよう`ValueError`を送出する。

`Contains`等のテキスト演算子は中置記法ではなく`FunctionName(operand1, operand2, caseFlag)`
という別の構文(知見18-2)で、パーサー(`pad_dsl_parser.py`)側は`IfFunctionRecord`/
`ElseIfFunctionRecord`として正しく構造化できるようになったが、本モジュールはまだこれを
Pythonの意味論に変換する方法を決めていない(`Contains`系は2引数+真偽フラグ、`Is empty`系は
引数の個数が異なると推測され、確証が無い)。`ConditionalNode`のアームにこれらが含まれる場合、
誤った変換をでっち上げないよう明示的に`NotImplementedError`を送出する。
"""
from __future__ import annotations

import re

from .pad_dsl_parser import (
    ActionRecord,
    BlockNode,
    ConditionalNode,
    ElseIfFunctionRecord,
    ElseIfRecord,
    EnumRef,
    IfFunctionRecord,
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
    "<>": "!=",
    ">": ">",
    ">=": ">=",
    "<": "<",
    "<=": "<=",
}

# MouseAndKeyboard.PressReleaseKey.*のBoolパラメータ名 → pyautoguiのキー名。
_MODIFIER_TO_PYAUTOGUI_KEY = {
    "Control": "ctrl",
    "Alt": "alt",
    "Shift": "shift",
    "Win": "win",
}

# UIAutomation.WindowState.* の列挙値 → pywinautoのWindowSpecificationメソッド名。
_WINDOW_STATE_TO_PYWINAUTO_METHOD = {
    "UIAutomation.WindowState.Maximized": "maximize",
    "UIAutomation.WindowState.Minimized": "minimize",
    "UIAutomation.WindowState.Restored": "restore",
}

# PAD変数名として実機で確認した形(常に有効なPython識別子)とみなす。
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
    imports = []
    if any("time.sleep(" in line for line in body):
        imports.append("import time")
    if any("pyautogui." in line for line in body):
        imports.append("import pyautogui")
    if any("Desktop(" in line for line in body):
        imports.append("from pywinauto import Desktop")
    imports.sort()
    header = [*imports, ""] if imports else []
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
        elif isinstance(header, (IfFunctionRecord, ElseIfFunctionRecord)):
            # Contains等の関数呼び出し条件(design/dsl_format_findings.md 知見18-2)。
            # Pythonへの変換方法がまだ未検証のため、誤った意味論をでっち上げるより
            # はっきり失敗させる。
            raise NotImplementedError(
                f"Function-call condition {header.function_name}(...) is not yet supported "
                "by codegen; its Python semantics haven't been verified on real PAD."
            )
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
    if node.action_id == "MouseAndKeyboard.SendKeys.FocusAndSendKeys":
        text = node.params.get("TextToSend")
        if isinstance(text, str):
            delay_ms = node.params.get("DelayBetweenKeystrokes", 10)
            interval = delay_ms / 1000 if isinstance(delay_ms, (int, float)) else 0.01
            return [f"{prefix}pyautogui.typewrite({render_value(text)}, interval={interval!r})"]
    if node.action_id == "MouseAndKeyboard.MoveMouse":
        x = node.params.get("X")
        y = node.params.get("Y")
        # "Relative to: Window"や"Move mouse from previous position: Smoothly"は
        # pyautoguiでの対応方法が未検証のため、確認済みの組み合わせ(Screen基準・Instant)の
        # ときだけ変換する。
        if (
            isinstance(x, (int, float))
            and isinstance(y, (int, float))
            and node.params.get("RelativeTo") == EnumRef("MouseAndKeyboard.PositionRelativeTo.Screen")
            and node.params.get("MovementStyle") == EnumRef("MouseAndKeyboard.MovementStyle.Instant")
        ):
            return [f"{prefix}pyautogui.moveTo({render_value(x)}, {render_value(y)})"]
    if node.action_id == "MouseAndKeyboard.SendMouseClick.Click":
        # "Mouse event to send"には他に7種(Right click/Double click/Middle click等)あるが
        # (design/dsl_format_findings.md 知見21)、実機確認したのはLeft clickのDSL表現
        # (MouseAndKeyboard.MouseClickType.LeftClick)だけなので、それ以外は推測で
        # マッピングせずTODOに倒す。
        if node.params.get("ClickType") == EnumRef("MouseAndKeyboard.MouseClickType.LeftClick"):
            delay_ms = node.params.get("MillisecondsDelay", 0)
            lines = []
            if isinstance(delay_ms, (int, float)) and delay_ms:
                lines.append(f"{prefix}time.sleep({delay_ms / 1000!r})")
            lines.append(f"{prefix}pyautogui.click()")
            return lines
    if node.action_id in (
        "MouseAndKeyboard.PressReleaseKey.PressKey",
        "MouseAndKeyboard.PressReleaseKey.ReleaseKey",
    ):
        # Control/Alt/Shift/Winのうちどれか1つだけがTrueの組み合わせのみ実機検証済み
        # (design/dsl_format_findings.md 知見23)。0個または複数同時Trueの場合の意味論は
        # 未検証のため推測しない。
        active = [name for name in _MODIFIER_TO_PYAUTOGUI_KEY if node.params.get(name) is True]
        if len(active) == 1:
            pyautogui_key = _MODIFIER_TO_PYAUTOGUI_KEY[active[0]]
            func = "keyDown" if node.action_id.endswith("PressKey") else "keyUp"
            return [f"{prefix}pyautogui.{func}({pyautogui_key!r})"]
    if node.action_id == "UIAutomation.SetWindowState.SetStateByTitleClass":
        title = node.params.get("Title")
        window_class = node.params.get("Class")
        state = node.params.get("State")
        # "Window class"を併用した組み合わせは未検証のため、Titleのみ(Classが空文字列)の
        # ときだけ変換する(design/dsl_format_findings.md 知見24)。
        if (
            isinstance(title, str)
            and window_class == ""
            and isinstance(state, EnumRef)
            and state.value in _WINDOW_STATE_TO_PYWINAUTO_METHOD
        ):
            method = _WINDOW_STATE_TO_PYWINAUTO_METHOD[state.value]
            return [f"{prefix}Desktop(backend='uia').window(title={render_value(title)}).{method}()"]
    return [f"{prefix}# TODO: map PAD action: {node.action_id}"]
