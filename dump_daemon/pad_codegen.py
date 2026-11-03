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
  絶対にしない)。design/dsl_format_findings.md 知見56(実機検証済み)——`generate_python()`に
  `parse_control_repository()`の結果を`repository`引数として渡すと、`Ignore: False`の
  `Attributes`(`Class`/`Name`)から組み立てた`Desktop(backend="uia").window(...)
  .child_window(...)`形式のセレクタ式を、実際に実機で対象要素を一意に特定できることを
  確認した(`_build_pywinauto_selector_expr()`)。当初はこの式をTODOコメントへの**提案**
  (実行コード自体は変えない)として追記するだけに留めていたが、`UIAutomation.Click.Click`に
  限っては、(1)このセレクタ式自体が実機で対象要素を一意に特定できると確認済みであること、
  (2)`.click_input()`自体も`pad_ui_helpers.py`でG1/G2実機検証済みのpywinauto操作であること、
  の2つの既に確証済みの要素を組み合わせるだけなので、確認済みのパラメータの組み合わせ
  (`ClickType: LeftClick`・`MousePositionRelativeToElement: MiddleCenter`・
  `OffsetX`/`OffsetY: 0`、知見38のDSLキャプチャ全件で確認済みの唯一の組み合わせ)かつ
  セレクタが実際に解決できる場合に限り、実行コードそのものを生成するよう拡張した。
  それ以外のクリック種別・位置基準・オフセットや、セレクタが解決できない場合は、
  依然として安全なTODO+ヒントのままにする——でっち上げた変換は一切しない。

対応範囲:
- `SetVariableRecord` → 代入文
- `ConditionalNode` → `if`/`elif`/`else`
- `SwitchNode` → `if`/`elif`/`else`(design/dsl_format_findings.md 知見33で実機確認済みの
  `CASE <operator> <value>`構文通り、`CASE`自身の演算子を`_OPERATOR_MAP`経由で変換する)
- `GuardedNode`(`ON ERROR`で保護された文) → `try`/`except Exception`(design/dsl_format_findings.md
  知見34・36で実機確認済み。ただし変換するのは1アームかつ名前無しcatch-allの場合のみ——
  複数アーム・名前付きケースは、PADのエラーケース名とPythonの例外型の対応表が無いため
  `# TODO`に倒す。「Throw error」のDSL表現は未検証)
- `BlockNode(LoopRecord)` → `for ... in range(start, end, step)`
  (**実機検証済み**——design/dsl_format_findings.md 知見51。当初は「両端を含む」
  (`range(start, end+1, step)`)と仮定していたが誤りで、PADの`LOOP X FROM 1 TO 3 STEP 1`は
  実際には`End`を含まず2回(X=1,2)しか実行されない——Pythonの`range(start, end, step)`と
  同じ「終端を含まない」セマンティクスだと実機確認した)
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
    ControlRepositoryEntry,
    CommentRecord,
    ConditionalNode,
    ElseIfActionRecord,
    ElseIfFunctionRecord,
    ElseIfRecord,
    EnumRef,
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
    を使った実行コードを生成する(`_generate_action()`内のコメント参照)。でっち上げたセレクタで
    動くコードを生成することは無い。
    省略時(`None`)は従来通りの挙動(ヒント無し)のまま完全に後方互換。
    """
    global _active_repository
    previous_repository = _active_repository
    _active_repository = repository or {}
    try:
        body = _generate_block_body(nodes, indent=0)
    finally:
        _active_repository = previous_repository
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
    imports.sort()
    header = [*imports, ""] if imports else []
    return "\n".join(header + body) + "\n"


# `generate_python()`の呼び出し期間中だけ設定される、現在のUI要素リポジトリ(知見44)。
# 深く再帰する内部のcodegenヘルパー群(`_generate_conditional`等)全ての関数シグネチャに
# 引数を追加するのを避けるための、意図的なモジュールレベル状態(`generate_python()`内で
# try/finallyにより必ず元の値に復元される——再入可能な公開APIは`generate_python()`のみ、
# かつ単一スレッド・同期実行前提のため許容)。
_active_repository: dict[str, dict[str, ControlRepositoryEntry]] = {}


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
        elif isinstance(header, (IfActionRecord, ElseIfActionRecord)):
            # 「If window」「If window contains element」等の[ConditionAction]カテゴリ
            # (design/dsl_format_findings.md 知見54)。条件式を誤って翻訳すると制御フローが
            # 丸ごと反転するという、SET文の右辺(知見53)よりもさらに危険な失敗モードになるため、
            # 原則でっち上げた真偽値を出力せずはっきり失敗させる。例外は`UIAutomation.IfWindow.*`
            # (`IfWindowAction`)で、decompileした実装(Microsoft.Flow.RPA.Desktop.Modules.
            # UIAutomation.Actions.dllのIfWindowAction.Execute())が`IsOpen`/`IsNotOpen`/
            # `IsFocused`/`IsNotFocused`という4通りの単純な真偽値(否定の有無のみ)で、
            # 複雑な設定モードを持たないと実際のソースで確認できたため、知見56のセレクタ組み立て
            # と組み合わせてここだけ変換する。`IfImage`/`IfWindowContains`はソース確認した限りでも
            # 複数の設定可能なサブモード(画像の一致アルゴリズム・テキスト包含モード等)を持ち、
            # `IfWindow`ほど単純ではないため、依然としてでっち上げず失敗させる。
            condition = _render_if_window_condition(header)
            if condition is None:
                raise NotImplementedError(
                    f"Action-call condition {header.action_id}(...) is not yet supported by codegen; "
                    "its Python semantics (and UI element selector) haven't been verified on real PAD."
                )
            keyword = "if" if isinstance(header, IfActionRecord) else "elif"
            lines.append(f"{prefix}{keyword} {condition}:")
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
            if node.output_var:
                # PADの公開ドキュメント(Microsoft公式Learnの関連解説記事・コミュニティ記事、
                # 複数の第三者ソースで一致)によれば、ScriptOutputはスクリプトが`print()`で
                # 標準出力に書き出した内容がそのまま値になる、という仕組みが確認できる。
                # ただし末尾改行の有無・複数回print()時の結合・型変換(常に文字列固定か、
                # 数値へ変換されるか)は公開資料・実機のいずれでも確認できなかったため、
                # 余計な推測(stripやint変換等)を加えず、標準出力の生テキストを
                # そのまま代入する最小限の変換に留める(`# NOTE`は安全側の注意書きであり、
                # `# TODO`ではない——変換自体は実行可能なコードとして生成されるため)。
                inner_prefix = prefix + INDENT
                lines = [f"{prefix}with contextlib.redirect_stdout(io.StringIO()) as _pyscript_stdout:"]
                lines.extend(
                    f"{inner_prefix}{line}" if line else "" for line in code.splitlines()
                )
                lines.append(f"{prefix}{node.output_var} = _pyscript_stdout.getvalue()")
                lines.append(
                    f"{prefix}# NOTE: {node.output_var} is the script's raw stdout text; "
                    "trailing newline / type coercion are not verified against real PAD"
                )
                return lines
            return [f"{prefix}{line}" if line else "" for line in code.splitlines()]
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
    if node.action_id == "UIAutomation.Click.Click":
        # design/dsl_format_findings.md 知見56で、`_build_pywinauto_selector_expr()`が
        # 組み立てるセレクタ式自体は実機(Notepad/Calculatorの実ウィンドウ)で対象要素を
        # 一意に特定できると確認済み。これまでは知見38の方針(セレクタがDSLから直接
        # 取得できない)を理由に、この確証済みの式をTODOコメント中の「提案」止まりにしていたが、
        # 知見56がその制約自体を解消した(リポジトリ経由でセレクタが実際に得られる)ため、
        # 以下の条件を全て満たす場合——(1)セレクタが実機で解決できる、(2)実機で確認済みの
        # パラメータの組み合わせ(ClickType: LeftClick・MousePositionRelativeToElement:
        # MiddleCenter・OffsetX/OffsetY: 0、知見38のDSLキャプチャ全件で確認済みの唯一の組み合わせ)
        # である——に限り、`.click_input()`(`pad_ui_helpers.py`でG1/G2実機検証済みの
        # pywinautoクリック方式)を使った実コードを生成する。それ以外のクリック種別・
        # 位置基準・オフセット(未検証)やセレクタが解決できない場合は、従来通り安全な
        # TODO+ヒントのままにする。
        element = node.params.get("Element")
        if (
            isinstance(element, UiElementRef)
            and node.params.get("ClickType") == EnumRef("UIAutomation.ClickType.LeftClick")
            and node.params.get("MousePositionRelativeToElement")
            == EnumRef("UIAutomation.RectangleEdgePoint.MiddleCenter")
            and node.params.get("OffsetX") == 0
            and node.params.get("OffsetY") == 0
        ):
            selector_expr = _build_pywinauto_selector_expr(element.path)
            if selector_expr is not None:
                return [f"{prefix}{selector_expr}.click_input()"]
    return [f"{prefix}# TODO: map PAD action: {node.action_id}{_ui_element_hint(node)}"]


# action_id → (UiElementRefを持つパラメータ名, pywinautoの.wait()/.wait_not()どちらを
# 使うか, 渡すwait_for文字列)。知見50・52で実機確認したWaitActionの全5バリアント。
# "active"は`WindowSpecification.wait()`が受け付ける標準の状態名(pywinauto自身のAPI、
# 「ウィンドウがアクティブ(フォーカスを持つ)か」の意味でPAD側のToBecomeFocused/
# ToLoseFocusの意味とそのまま対応する)。
_WAIT_ACTION_TARGETS: dict[str, tuple[str, str, str]] = {
    "UIAutomation.WaitForWindow.ToOpen": ("Window", "wait", "exists"),
    "UIAutomation.WaitForWindow.ToClose": ("Window", "wait_not", "exists"),
    "UIAutomation.WaitForWindow.ToBecomeFocused": ("Window", "wait", "active"),
    "UIAutomation.WaitForWindow.ToLoseFocus": ("Window", "wait_not", "active"),
    "UIAutomation.WaitForWindowContent.WindowToContainElement": ("Element", "wait", "exists"),
}


def _generate_wait_action(node: WaitActionRecord, indent: int) -> list[str]:
    """`WaitActionRecord`(design/dsl_format_findings.md 知見50で実機確認した
    `WAIT (<ActionId> ...) FOR <秒数>`構文) → pywinautoの`.wait()`/`.wait_not()`、
    またはそれが安全に組み立てられない場合は`# TODO`コメント。

    `UIAutomation.WaitForWindow.ToOpen`等はpywinautoの`WindowSpecification.wait("exists",
    timeout=...)`に自然に対応する。対象のセレクタは知見56の`_build_pywinauto_selector_expr()`
    (Click.Clickで実際の実行コード生成に使っているのと同じ、実機で一意特定を確認済みの仕組み)
    で解決できる場合のみ使う。`timeout_seconds`は「Fail with timeout error」トグルがOFFの
    場合`None`になる(知見50の追記)が、その場合PAD側が実際に無期限に待つのか・内部的な
    既定値があるのかは公開資料・実機のいずれでも確証が持てておらず、pywinauto側の
    `.wait()`はtimeout省略時に有限のデフォルト(`Timings.window_find_timeout`)にフォール
    バックしてしまい「無期限待ち」と「有限待ちで静かに失敗」という異なる挙動になりうる
    ため、`timeout_seconds`が実際に数値で確認できる場合に限り変換する——`None`の場合は
    でっち上げたタイムアウト値を埋め込まず、安全なTODOのままにする。
    """
    prefix = INDENT * indent
    timeout_desc = f"{render_value(node.timeout_seconds)}s" if node.timeout_seconds is not None else "none"
    target = _WAIT_ACTION_TARGETS.get(node.action_id)
    if target is not None and node.timeout_seconds is not None:
        param_name, method, wait_for = target
        element = node.params.get(param_name)
        if isinstance(element, UiElementRef):
            selector_expr = _build_pywinauto_selector_expr(element.path)
            if selector_expr is not None:
                timeout = render_value(node.timeout_seconds)
                return [f"{prefix}{selector_expr}.{method}({wait_for!r}, timeout={timeout})"]
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
    hints = [h for p in paths if (h := _build_pywinauto_selector_expr(p)) is not None]
    suggestion = f"; verified pywinauto selector: {' / '.join(hints)}" if hints else ""
    return (
        f" (UI element: {joined}; selector not available from DSL, see knowledge 38/39/42/43/46"
        f" — fill in manually{suggestion})"
    )


_REPOSITORY_ATTR_TO_PYWINAUTO_KWARG = {
    "Class": "class_name",
    "Name": "title",
}


def _build_pywinauto_selector_expr(path: tuple[str, ...]) -> str | None:
    """`parse_control_repository()`(知見44)のエントリから、確証のあるpywinautoセレクタ式を
    組み立てる(知見56: `appmask['Window \\'Untitled - Notepad\\'']['Document \\'Text Editor\\'']`の
    実例で、`Desktop(backend="uia").window(title="Untitled - Notepad").child_window(
    class_name="Edit")`が実機で正しく対応する実要素を一意に特定できることを確認済み)。

    `ControlRepositorySelectorElement.attributes`のうち`Ignore: False`の属性だけを使う
    (`Ignore: True`はPAD自身の要素特定ロジックが使わない属性——知見46)。`Class`/`Name`
    属性だけを`class_name`/`title`へ対応付ける。`Process`属性はpywinautoの`window()`/
    `child_window()`がプロセス**名**を直接受け付けない(`process=`はPIDを要求する)ため
    意図的に使わない。経路上のいずれかのセグメントでリポジトリに情報が無い、または
    使える属性が1つも無い(例: 知見44の`:startbutton`のような特殊タグで`Attributes`が
    空)場合は、でっち上げた式を返さず`None`にする。

    design/dsl_format_findings.md 知見56の追記(実機検証済み): 1つの`ControlRepositoryEntry`の
    `selectors[0]`自体が**複数の`ControlRepositorySelectorElement`からなる内部チェーン**に
    なりうる(例: 電卓の「7」ボタンは`pane(Class: CalcFrame)` → `button(Class: Button,
    Name: 7)`という2段)。当初の実装は`entry.selectors[0][0]`(チェーンの最初の1要素)だけを
    見ていたため、この例では実際のボタンではなく中間の`pane`要素(`control_type: Pane`)を
    指す誤った式を生成してしまっていた(実機で`child_window(class_name="CalcFrame")`が
    ボタンではなくPaneに解決されることを確認して発覚)。チェーン内の各要素を**それぞれ
    別個の`.child_window(...)`呼び出し**として連ねる(属性を1つの呼び出しにまとめて
    しまうと、異なる階層の要素が同じ属性名を異なる値で持つ場合に情報をサイレントに
    失う恐れがあるため、PAD自身の内部チェーン構造をそのまま1対1で複製する方針にした)
    よう修正し、実機で`Desktop(backend="uia").window(title="Calculator").child_window(
    class_name="CalcFrame").child_window(class_name="Button", title="7")`が電卓の
    実際の「7」ボタン(`control_type: Button`, `name: 7`)を正しく一意に特定できることを
    確認した。
    """
    repository = _active_repository.get("appmask")
    if not repository:
        return None
    calls: list[str] = []
    for name in path:
        entry = repository.get(name)
        if entry is None or not entry.selectors or not entry.selectors[0]:
            return None
        for element in entry.selectors[0]:
            kwargs: dict[str, str] = {}
            for attr in element.attributes:
                if attr.get("Ignore"):
                    continue
                kwarg_name = _REPOSITORY_ATTR_TO_PYWINAUTO_KWARG.get(attr.get("Name"))
                value = attr.get("Value")
                if kwarg_name is not None and isinstance(value, str):
                    kwargs[kwarg_name] = value
            if not kwargs:
                return None
            kwargs_str = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
            if not calls:
                calls.append(f'Desktop(backend="uia").window({kwargs_str})')
            else:
                calls.append(f".child_window({kwargs_str})")
    return "".join(calls)


def _render_if_window_condition(header: IfActionRecord | ElseIfActionRecord) -> str | None:
    """`UIAutomation.IfWindow.*`(`IfWindowAction`、decompile結果は`_generate_conditional()`の
    コメント参照)の条件式をpywinautoの真偽値式に変換する。セレクタが知見56の仕組みで解決
    できない場合、または`IfWindow`ファミリー以外(`IfImage`/`IfWindowContains`等、ソース上も
    `IfWindow`より複雑な複数サブモードを持つと確認済み)の場合は`None`を返し、呼び出し元に
    安全なフォールバック(`NotImplementedError`)をさせる。

    `IsFocused`/`IsNotFocused`は、decompileしたソース自体には存在チェックが無く直接
    `IsWindowFocused()`を呼ぶだけだが、ウィンドウが存在しない場合にpywinautoの
    `wrapper_object()`は例外を投げてしまう(PAD側は「閉じているウィンドウはフォーカスされて
    いない」という素直な意味でFalseを返すと推測される)。そのため`exists()`を先に確認する
    防御的な合成式にしている——これは意味論そのものの推測ではなく、クラッシュを避けるための
    自然な実装上のガードであり、`IsOpen`/`IsNotOpen`(`exists()`の直接確認・否定)は
    decompile結果そのまま。
    """
    if not header.action_id.startswith("UIAutomation.IfWindow."):
        return None
    window = header.params.get("Window")
    if not isinstance(window, UiElementRef):
        return None
    selector_expr = _build_pywinauto_selector_expr(window.path)
    if selector_expr is None:
        return None
    mode = header.action_id.rsplit(".", 1)[-1]
    exists_expr = f"{selector_expr}.exists()"
    if mode == "IsOpen":
        return exists_expr
    if mode == "IsNotOpen":
        return f"not {exists_expr}"
    if mode in ("IsFocused", "IsNotFocused"):
        active_expr = f"({exists_expr} and {selector_expr}.wrapper_object().is_active())"
        return active_expr if mode == "IsFocused" else f"not {active_expr}"
    return None


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
