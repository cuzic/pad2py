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
  もの)もpywinauto対応になる見込みだが、**DSLテキスト上のパラメータ値はUI要素リポジトリへの
  名前参照`appmask['<表示名>']`でしかなく、実際のセレクタ文字列(CSS風、design/robin_language_source_findings.md
  参照)自体はクリップボードコピーのDSLテキストには含まれない**(design/dsl_format_findings.md
  知見38で実機確認済み)。セレクタの実体を取得できないか知見39・42・43で実機調査を尽くした
  (PADデザイナーUI上に閲覧経路が無い、ローカルにキャッシュされない、個人用Microsoftアカウントは
  Power Platformメーカーポータル/Dataverseにそもそもアクセスできない、の3点を確認済み)が、
  いずれも行き止まりだった。**これを本プロジェクトのv1スコープの意図的な線引きとして確定する**:
  UI要素セレクタが必要なアクションはPythonへ変換せず、`UiElementRef`で参照されている表示名を
  含む`# TODO`コメントとして明示的に出力する(でっち上げた架空のセレクタ文字列を埋め込むことは
  絶対にしない)。ユーザーはそのTODOコメントを見て、該当するUI要素のセレクタを手動で
  (pywinautoの`best_match`/`class_name`等で)補う前提。

対応範囲:
- `SetVariableRecord` → 代入文
- `ConditionalNode` → `if`/`elif`/`else`
- `SwitchNode` → `if`/`elif`/`else`(design/dsl_format_findings.md 知見33で実機確認済みの
  `CASE <operator> <value>`構文通り、`CASE`自身の演算子を`_OPERATOR_MAP`経由で変換する)
- `GuardedNode`(`ON ERROR`で保護された文) → `try`/`except Exception`(design/dsl_format_findings.md
  知見34・36で実機確認済み。ただし変換するのは1アームかつ名前無しcatch-allの場合のみ——
  複数アーム・名前付きケースは、PADのエラーケース名とPythonの例外型の対応表が無いため
  `# TODO`に倒す。「Throw error」のDSL表現は未検証)
- `BlockNode(LoopRecord)` → `for ... in range(...)`
  (**未検証の前提**: PADの`Start from`〜`End to`は両端を含むと仮定し`range(start, end+1, step)`
  としている。実際にループ本体が複数回実行されるか実機で確認するまでは未確定)
- `BlockNode(LoopForeachRecord)` → `for ... in ...`
- `BlockNode(LoopWhileRecord)` → `while ...`
- `BlockNode(BlockRecord)`(design/dsl_format_findings.md 知見40で実機確認した`BLOCK`/`END`——
  PADの「On block error」アクションが自動生成するグループ化構文) → Python側に対応する制御
  構文は無いので、本体をそのまま現在のインデントに展開するだけ(追加の`if`/`for`等は生成
  しない)。`ON BLOCK ERROR`による保護は`GuardedNode`の`try`/`except`が担う
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
- `ActionRecord`(`UIAutomation.SetWindowState.SetStateByTitleClass`/
  `UIAutomation.MoveWindow.MoveByTitleClass`/`UIAutomation.ResizeWindow.ResizeByTitleClass`/
  `UIAutomation.FocusWindow.FocusByTitleClass`/`UIAutomation.CloseWindow.CloseByTitleClass`) →
  `Desktop(backend='uia').window(title=...)`に対する`.maximize()/.minimize()/.restore()`
  (知見24)・`.move_window(x=, y=)`(知見25)・`.move_window(width=, height=)`(知見25)・
  `.set_focus()`(知見27、実機確認済み)・`.close()`(design/robin_language_source_findings.md——
  `CloseWindowByTitleClassSelector`のソースから他4つと同じパターンだと確認、action_id自体は
  実機未確認でパターンからの推論)。いずれも共通ヘルパー`_window_lookup_expr()`経由で、
  `Window class`を併用しない(空文字列の)場合のみ変換し、クラス名併用(未検証)は`# TODO`のまま。
  `import pyautogui`と同様、使用時のみ`from pywinauto import Desktop`を先頭に出力する)
- 他のUI automationアクションも含め、未対応のものは架空のAPI呼び出しをでっち上げず
  `# TODO`コメントを出力する
- 文字列値中の`%VarName%`マーカー(design/dsl_format_findings.md 知見16)→ f-string化
  (`render_text_template()`。マーカーを含まない文字列は通常の`repr()`のまま)

演算子は実機検証済みの6つの比較演算子(`=`/`<>`/`>`/`>=`/`<`/`<=`、design/dsl_format_findings.md
知見18)と、ソース確認済み(実機未確認)の`IN`/`NOT IN`のみ`_OPERATOR_MAP`に登録している。
未知の演算子に遭遇した場合は、誤った意味論を生成しないよう`ValueError`を送出する。

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
    BlockRecord,
    CaseDefaultRecord,
    CommentRecord,
    ConditionalNode,
    ElseIfFunctionRecord,
    ElseIfRecord,
    EnumRef,
    GuardedNode,
    IfFunctionRecord,
    IfRecord,
    KeywordRecord,
    LoopForeachRecord,
    LoopRecord,
    LoopWhileRecord,
    Node,
    RawRecord,
    SetVariableRecord,
    SwitchNode,
    UiElementRef,
    VarRef,
    WaitActionRecord,
)

INDENT = "    "

# 実機検証済みの6つ(design/dsl_format_findings.md 知見6・9)に加え、`IN`/`NOT IN`は
# design/robin_language_source_findings.md——`ComparisonOperatorExtensions`のソースで
# DSL上の文字列表現が確定しており、Pythonの`in`/`not in`はPADの「コレクションに含まれるか」
# という意味とそのまま対応する自然な写像のため追加した(実機でどのUI経由で使われるかは
# まだ未確認)。
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


def _generate_node(node: Node, indent: int) -> list[str]:
    prefix = INDENT * indent
    if isinstance(node, SetVariableRecord):
        return [f"{prefix}{node.var_name} = {render_value(node.value)}"]
    if isinstance(node, ConditionalNode):
        return _generate_conditional(node, indent)
    if isinstance(node, SwitchNode):
        return _generate_switch(node, indent)
    if isinstance(node, GuardedNode):
        return _generate_guarded(node, indent)
    if isinstance(node, BlockNode):
        return _generate_loop_block(node, indent)
    if isinstance(node, KeywordRecord):
        return _generate_keyword(node, indent)
    if isinstance(node, ActionRecord):
        return _generate_action(node, indent)
    if isinstance(node, WaitActionRecord):
        return _generate_wait_action(node, indent)
    if isinstance(node, CommentRecord):
        # 複数行コメント(`/# ... #/`)はPythonの`#`コメントが1行ずつしか続けられない
        # ため、埋め込まれた改行ごとに別の`#`行として出力する。
        if "\n" in node.text:
            return [f"{prefix}# {line}".rstrip() for line in node.text.split("\n")]
        return [f"{prefix}# {node.text}".rstrip()]
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
        lines.extend(_ensure_nonempty_suite(_generate_block_body(arm_body, indent + 1), indent + 1))
    return lines


def _generate_switch(node: SwitchNode, indent: int) -> list[str]:
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
        lines.extend(_ensure_nonempty_suite(_generate_block_body(arm_body, indent + 1), indent + 1))
    return lines


def _generate_guarded(node: GuardedNode, indent: int) -> list[str]:
    """`GuardedNode`(`ON ERROR`/`ON BLOCK ERROR`で保護された文) → `try`/`except Exception`。

    design/dsl_format_findings.md 知見34で実機確認したのは「All errors (default)」
    (名前無しcatch-all、1アームのみ)に本体アクションを追加し「Continue flow run」を選んだ
    ケースのみ——そのDSL上の意味論(エラーを捕捉してハンドラを実行し、続行する)は
    `try`/`except`に自然に対応する。知見36で、名前付きケース(`ON ERROR <CaseName>`)や
    複数アームが区切り無しに連続しうることも実機確認したが、**PADの各エラーケース名が
    Pythonのどの例外型に対応するかは分からない**(`RunPythonScriptError`が`OSError`
    相当なのか等、対応表が無い)ため、複数アームや名前付きケースを安易に`except`の
    型指定に変換することはしない——1アームかつ名前無しcatch-allの場合のみ変換し、
    それ以外は保護対象の文だけ出力して`# TODO`を残す。`node.node`が`BlockNode(BlockRecord)`の
    場合(知見40の`ON BLOCK ERROR`)も構造は全く同じなので、このロジックをそのまま流用できる。
    """
    prefix = INDENT * indent
    if len(node.on_error.arms) == 1 and node.on_error.arms[0][0].case_name is None:
        handler_body = node.on_error.arms[0][1]
        lines = [f"{prefix}try:"]
        lines.extend(_generate_node(node.node, indent + 1))
        lines.append(f"{prefix}except Exception:")
        lines.extend(_ensure_nonempty_suite(_generate_block_body(handler_body, indent + 1), indent + 1))
        return lines
    lines = list(_generate_node(node.node, indent))
    lines.append(f"{prefix}# TODO: ON ERROR/ON BLOCK ERROR handling not converted (named/multiple error cases)")
    return lines


def _generate_loop_block(node: BlockNode, indent: int) -> list[str]:
    prefix = INDENT * indent
    header = node.header
    if isinstance(header, BlockRecord):
        # design/dsl_format_findings.md 知見40: BLOCKはPADの「アクショングループ」で、
        # それ自体はPython側に対応する制御構造を持たない純粋なスコープ区切り。
        # ON BLOCK ERRORによる保護はGuardedNodeのtry/exceptが担うため、ここでは本体を
        # 追加のインデント無しでそのまま展開するだけでよい。
        return _ensure_nonempty_suite(_generate_block_body(node.body, indent), indent)
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
    lines.extend(_ensure_nonempty_suite(_generate_block_body(node.body, indent + 1), indent + 1))
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
        window_expr = _window_lookup_expr(node)
        state = node.params.get("State")
        if window_expr and isinstance(state, EnumRef) and state.value in _WINDOW_STATE_TO_PYWINAUTO_METHOD:
            method = _WINDOW_STATE_TO_PYWINAUTO_METHOD[state.value]
            return [f"{prefix}{window_expr}.{method}()"]
    if node.action_id == "UIAutomation.MoveWindow.MoveByTitleClass":
        window_expr = _window_lookup_expr(node)
        x = node.params.get("X")
        y = node.params.get("Y")
        if window_expr and isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return [f"{prefix}{window_expr}.move_window(x={render_value(x)}, y={render_value(y)})"]
    if node.action_id == "UIAutomation.ResizeWindow.ResizeByTitleClass":
        window_expr = _window_lookup_expr(node)
        width = node.params.get("Width")
        height = node.params.get("Height")
        if window_expr and isinstance(width, (int, float)) and isinstance(height, (int, float)):
            return [
                f"{prefix}{window_expr}.move_window(width={render_value(width)}, height={render_value(height)})"
            ]
    if node.action_id == "UIAutomation.FocusWindow.FocusByTitleClass":
        # design/dsl_format_findings.md 知見27(実機確認済み、SetWindowState等と同じ
        # ByTitleClassパターン)・design/robin_language_source_findings.md
        # (FocusWindowByTitleClassSelectorのソースでaction_idの構成要素を確認)。
        window_expr = _window_lookup_expr(node)
        if window_expr:
            return [f"{prefix}{window_expr}.set_focus()"]
    if node.action_id == "UIAutomation.CloseWindow.CloseByTitleClass":
        # design/robin_language_source_findings.md——CloseWindowByTitleClassSelectorの
        # ソースから、他の4つのByTitleClass系アクションと全く同じパターンだと確認した
        # (action_id自体は実機未確認、パターンからの推論)。
        window_expr = _window_lookup_expr(node)
        if window_expr:
            return [f"{prefix}{window_expr}.close()"]
    return [f"{prefix}# TODO: map PAD action: {node.action_id}{_ui_element_hint(node)}"]


def _generate_wait_action(node: WaitActionRecord, indent: int) -> list[str]:
    """`WaitActionRecord`(design/dsl_format_findings.md 知見50で実機確認した
    `WAIT (<ActionId> ...) FOR <秒数>`構文) → `# TODO`コメント。

    `UIAutomation.WaitForWindow.ToOpen`等はpywinautoの`WindowSpecification.wait("exists",
    timeout=...)`に自然に対応しそうに見えるが、対象ウィンドウのセレクタ自体は`Window`
    パラメータの`UiElementRef`が指す名前参照でしかなく、実セレクタがDSLから取得できない
    (知見38・46と同じ制約)。でっち上げたセレクタを埋め込まず、action_id・タイムアウト秒数・
    関連UI要素の表示名をTODOコメントに残すだけに留める。`timeout_seconds`は「Fail with
    timeout error」トグルがOFFの場合`None`になる(知見50の追記——`FOR <秒数>`句自体が
    DSLから省略される、実機確認済み)。
    """
    prefix = INDENT * indent
    timeout_desc = f"{render_value(node.timeout_seconds)}s" if node.timeout_seconds is not None else "none"
    return [
        f"{prefix}# TODO: map PAD wait action: {node.action_id} "
        f"(timeout: {timeout_desc}){_ui_element_hint(node)}"
    ]


def _ui_element_hint(node: ActionRecord | WaitActionRecord) -> str:
    """未対応アクションのTODOコメントに、関連するUI要素の表示名を付記する。

    design/dsl_format_findings.md 知見38で確認した通り、`Click UI element in window`等の
    パラメータ値は`UiElementRef`(`appmask['<表示名>']`への名前参照)であり、実際のセレクタ
    文字列はDSLテキストに含まれない(知見39・42・43で取得経路を実機で探索し尽くし、v1では
    変換不能と確定——本モジュール冒頭のdocstring参照)。架空のセレクタをでっち上げる代わりに、
    せめて表示名だけでもTODOコメントに残すことで、ユーザーが手動でpywinautoのセレクタを
    補う際の手がかりにする。
    """
    # design/dsl_format_findings.md 知見46: 対象が別要素の子孫の場合、`UiElementRef.path`は
    # 祖先から対象までの表示名のタプルになる(例: `("Window 'Untitled - Notepad'",
    # "Document 'Text Editor'")`)。フルパスをそのまま見せた方が、ユーザーが手動で
    # pywinautoのセレクタを組み立てる際の手がかりとして有用。
    paths = [v.path for v in node.params.values() if isinstance(v, UiElementRef)]
    if not paths:
        return ""
    joined = ", ".join(" > ".join(repr(name) for name in path) for path in paths)
    return f" (UI element: {joined}; selector not available from DSL, see knowledge 38/39/42/43/46 — fill in manually)"


def _window_lookup_expr(node: ActionRecord) -> str | None:
    """`Title`/`Class`パラメータから`Desktop(backend='uia').window(title=...)`式を組み立てる。

    `Window class`を併用した組み合わせ(知見24で未検証のまま)では`None`を返し、
    呼び出し元に架空の変換をさせない。`Title`/`Class`の両方を持つ`UIAutomation.*ByTitleClass`
    系アクション(SetWindowState/MoveWindow/ResizeWindow)で共通して使うヘルパー。
    """
    title = node.params.get("Title")
    window_class = node.params.get("Class")
    if isinstance(title, str) and window_class == "":
        return f"Desktop(backend='uia').window(title={render_value(title)})"
    return None
