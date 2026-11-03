"""PADの「コピー&ペースト」クリップボードDSLのプロトタイプパーサー。

design/dsl_format_findings.md で実機検証した文法に基づく。対応している範囲:
- `ActionId Param: Value ... Output=> Var` 形式の一般アクション行(1個のアクションが
  複数の出力を持つ場合(知見26: `WindowTitle=> WindowTitle WindowInstance=> AutomationWindow`)、
  全ての束縛を`ActionRecord.output_vars`(パラメータ名→変数名の辞書)に保持する。
  `output_var`は後方互換のため最後に見つかったものを保持するだけなので、複数出力が
  ありうるアクションでは`output_vars`を参照すること)
- `$'''...'''`(複数行可)の文字列リテラル、および `\"`/`\'`/`\\` のエスケープ解除、
  および`%%`→`%`の解除(design/robin_language_source_findings.md——
  `InterpolatedStringAtom.ToString()`のソースで、リテラル部分は`EscapeForRobin(interpolated: true)`
  経由で常に`%`が`%%`に二重化されてから出力されることを確認した。`_STRING_RE`が捕捉する
  `$'''...'''`形式は全て`InterpolatedStringAtom`由来であり、この二重化を必ず受けているため、
  推測ではなくソース上確定した解除処理。以前は`\'`と`%%`の解除が未実装で、本文中にアポストロフィ
  (例: `it's`)を含むPADテキストが誤って`it\'s`のままPythonコードに混入するサイレントな
  バグがあった)
- `Namespace.Enum.Value` 形式の列挙値、`True`/`False` の真偽値
- `WAIT <seconds>` のようなベアキーワード行(action行のパターンに一致しない行は
  種別不明の `raw` レコードとしてそのまま保持し、サイレントに捨てない)

- `SET <VarName> TO <value>` 形式の変数代入(Set variableアクション。実機検証で
  `SET TestVar TO $'''...'''` の形を確認。`TO` は固定トークン)
- `IF <operand1> <operator> <operand2> THEN` / `END` 形式の条件分岐(実機検証で
  `IF TestVar = $'''hello''' THEN` ... `END` の形を確認。変数参照は `%...%` ではなく
  ベアトークンで表現される)
- ネスト構造は**4スペースインデント**で表現される(実機検証: `IF...THEN`内の
  アクションは先頭に4スペース)。各レコードは`indent`フィールド(0始まりの深さ)を持つ。

- `LOOP <VarName> FROM <start> TO <end> STEP <step>` / `END` 形式のカウントループ
  (実機検証で `LOOP LoopIndex FROM 1 TO 3 STEP 1` ... `END` の形を確認。`IF`と同じく
  ベアキーワード行+`END`で閉じる)
- `LOOP FOREACH <itemVar> IN <collection>` / `END` 形式のコレクション反復(実機検証で
  `LOOP FOREACH CurrentItem IN TestVar` ... `END` の形を確認)
- `LOOP WHILE (<operand1>) <operator> (<operand2>)` / `END` 形式の条件ループ(実機検証で
  `LOOP WHILE (LoopIndex) < (10)` ... `END` の形を確認。**`IF`と異なりオペランドが
  丸括弧で囲まれる**——同じ「First operand/Operator/Second operand」ダイアログ形状でも
  アクションの種類によってDSL表現が異なる例)

- `ELSE IF <operand1> <operator> <operand2> THEN` / `ELSE`(実機検証で
  `IF ... THEN` / `ELSE IF ... THEN` / `ELSE` / `END` の形を確認)。**重要**:
  `IF`/`ELSE IF`/`ELSE`は同じindent深さの**1つの構文**であり、`END`は
  個々のアームにではなく構文全体に1つだけ対応する(`IF`単体がネストしたブロックを
  開くわけではない)。`build_block_tree()`は`ConditionalNode(arms)`としてこれを表現する。
- `build_block_tree()`: `indent`情報を使って、フラットな`list[Record]`から
  ブロック木を組み立てる後処理(design/dsl_format_findings.md 知見7・9・11)。
  `LoopRecord`/`LoopForeachRecord`/`LoopWhileRecord`は単純な`BlockNode(header, body)`
  (本体がindent+1、対応する`END`が同じindentという1:1の構造)。`IfRecord`は
  `ElseIfRecord`/`ELSE`キーワードが同じindentで後続する限り1つの`ConditionalNode`に
  まとめ、最後に現れる`END`1つだけを構文全体の終端として消費する。

- `EXIT LOOP` / `NEXT LOOP`(実機検証。いずれも2トークンのベアキーワードで、
  `KeywordRecord(name="EXIT"/"NEXT", args=["LOOP"])`としてそのまま表現できる。
  `LOOP`系ブロックの本体内に通常のリーフとして現れるため、`build_block_tree()`に
  特別な対応は不要)
- 値の種別区別: `$'''...'''`由来の文字列リテラル、裸の数値トークン(`int`/`float`)、
  `Namespace.Enum.Value`形式の列挙値(`EnumRef`)、それ以外の裸トークン(`VarRef`——変数参照)
  を区別して返す。例えば`IF TestVar = $'''hello''' THEN`では`TestVar`は`VarRef("TestVar")`、
  `hello`はPython文字列`"hello"`になる。コード生成時に「変数名としてそのまま出力するか」
  「文字列リテラルとして`repr()`するか」を判別するために必須の区別(両者とも字面上は
  識別子のように見えうるため、プレースホルダ経由かどうかでしか判別できない)。

- `IF <FuncName>(<arg1>, <arg2>, ...) THEN` / `ELSE IF <FuncName>(...) THEN` 形式の
  関数呼び出し条件(design/dsl_format_findings.md 知見18-2。`Contains`等のテキスト演算子は
  `<operand1> <operator> <operand2>`という中置記法ではなく、この別構文になる。実機検証は
  `Contains(InnerVar, $'''nested''', False) THEN`のみ。`IfFunctionRecord`/
  `ElseIfFunctionRecord`として構造化するが、`build_block_tree()`は`IfRecord`/`ElseIfRecord`
  と同様にこれらも`ConditionalNode`のアームとして扱う。`pad_codegen.py`はまだこの形の
  Python変換方法が未検証のため、遭遇すると明示的に例外を送出する——`Contains`系は
  2引数+真偽フラグ、`Is empty`系は引数の個数が異なると推測されるが未確認であり、
  安易に同じ形式だと仮定しない)

- `# <comment>` 形式の単一行コメント、および `/# ... #/` 形式の複数行コメント
  (design/robin_language_source_findings.md——`CommentStatement.ToString()`のソースで
  両方の形式と、複数行側の正確なエスケープ規則(`EscapeRobinComment`: `#/`とバックスラッシュの
  直前にバックスラッシュを挿入)を確認した。`$'''...'''`の複数行文字列マスキングと同じ手法(DOTALLで
  先に1トークンに退避してから行分割)を複数行コメントにも適用し、マスキングの順序は
  コメント→文字列(コメント本文に`$'''`等が含まれていても文字列リテラルとして
  誤認されないようにするため)。

未対応(今後の実機確認が必要): 複合式(AND/OR)、`IN`/`NOT IN`演算子(ソースコードでは
存在を確認したが、実機でどのUI経由で使えるかは未確認。`NOT IN`は2トークンのため現状の
`_parse_line`では誤パースする既知のギャップがある)。

- `SWITCH <expr>` / `CASE <value>` / `DEFAULT` / `END` 形式の多分岐(design/robin_language_source_findings.md——
  ANTLR生成パーサー`Language.cs`の`Small_statementContext`を読み、`switch_statement`/
  `case_statement`/`case_default`が`if_statement`/`elseif_statement`/`else_statement`/
  `while_statement`/`loop_statement`と**全く同じ文法規則(grammar rule)の選択肢として並列**
  であることを確認した——つまりSWITCH/CASE/DEFAULTにも専用のネスト構造(Block/Scopeクラス)は
  存在せず、IF/ELSE IF/ELSEと同様、フラットな文の並びをindentだけで解釈する設計になっている。
  この文法上の並列性から類推し、`IF`/`ELSE IF`/`ELSE`で確認済みの規則(ヘッダー群は同じindent、
  各アームの本体はindent+1、`END`は構文全体に1つ)を`SWITCH`/`CASE`/`DEFAULT`にもそのまま適用した。
  **注意**: この類推自体は確認済みの文法的並列性に基づく合理的な推論だが、SWITCH自身の
  実機でのインデント規則そのものを直接確認したDSL出力例はまだ無い——`LOOP`の両端含むrange仮定
  (このモジュールの別箇所)と同種の「明示的に文書化された未検証の前提」として扱うこと。

`ON ERROR <Case>` / `ON BLOCK ERROR <Case>`(design/robin_language_source_findings.md——
`ExceptionStatementBase`のソースでブロック構造自体は解明できたが、実機でのDSL出力例が
まだ無く、保護対象のアクションとの結びつき方も実証されていないため、本モジュールでは
未実装のまま(`RawRecord`として保持される)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_STRING_RE = re.compile(r"\$'''(.*?)'''", re.DOTALL)
_ESCAPE_RE = re.compile(r"\\\\|\\\"|\\'")
_COMMENT_RE = re.compile(r"/#((?:\\#/|\\\\|(?!#/).)*)#/", re.DOTALL)
_COMMENT_ESCAPE_RE = re.compile(r"\\(#/|\\)")


def _unescape(raw: str) -> str:
    """DSL文字列リテラル内の `\\"`→`"`・`\\'`→`'`・`\\\\`→`\\` を解除し、続けて
    `%%`→`%` を解除する(`InterpolatedStringAtom.ToString()`のソースで確認した
    `EscapeForRobin(interpolated: true)`の逆操作。順序が重要——先にクォート/
    バックスラッシュのエスケープを解除し、その後で`%`の二重化を解除する)。
    """
    dequoted = _ESCAPE_RE.sub(lambda m: m.group(0)[-1], raw)
    return dequoted.replace("%%", "%")


def _unescape_comment(raw: str) -> str:
    """複数行コメント(`/# ... #/`)内の `\\#/`→`#/`、`\\\\`→`\\` を解除する
    (`CommentStatement.ToString()`が呼ぶ`EscapeRobinComment`の逆操作)。
    """
    return _COMMENT_ESCAPE_RE.sub(lambda m: m.group(1), raw)


@dataclass(frozen=True)
class VarRef:
    """DSL上の裸トークンが変数参照であることを表すマーカー型。

    `$'''...'''`で囲まれていない裸トークンは、数値リテラル/`Namespace.Enum.Value`型の
    列挙値でなければ変数参照(実機検証: design/dsl_format_findings.md 知見6・9——UI上の
    `%VarName%`はDSL上`%`記号なしの裸トークンとして出力される)。文字列リテラル
    ("hello"等)と字面上は区別がつかないため、専用の型でラップして明示する。
    """

    name: str


@dataclass(frozen=True)
class EnumRef:
    """`Namespace.Enum.Value`形式(例: `Display.Icon.None`)の列挙値を表すマーカー型。

    ドット区切りの完全修飾名という見た目でPAD変数参照(ドットを含まない裸識別子)と
    区別できるため、`VarRef`とは別の型にしている。

    **既知の未解決の曖昧性**(design/robin_language_source_findings.md):
    `Variable.ToString()`のソースで、PADの変数参照自体にも`.Name`という
    ドット区切りの「トレーラ」(配列/カスタムオブジェクトのプロパティアクセス、例:
    `MyDataTable.Rows`)が存在しうることを確認した。この形はテキスト上
    `Namespace.Enum.Value`と完全に同じ見た目になるため、`_DOTTED_RE`だけでは
    区別できない。これまでの実機データにトレーラ付き変数参照の実例が無いため、
    現状は全てのドット区切りトークンを`EnumRef`として扱っているが、これは
    トレーラ付き変数が実在する場合に誤分類する可能性がある未解決のギャップ。
    """

    value: str


_DOTTED_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")
_INT_RE = re.compile(r"-?\d+")
_FLOAT_RE = re.compile(r"-?\d+\.\d+")
_FUNC_COND_RE = re.compile(r"^(IF|ELSE IF) ([A-Za-z_][A-Za-z0-9_]*)\((.*)\) THEN$")


@dataclass
class ActionRecord:
    action_id: str
    params: dict[str, Any] = field(default_factory=dict)
    output_var: str | None = None
    output_vars: dict[str, str] = field(default_factory=dict)
    indent: int = 0


@dataclass
class KeywordRecord:
    name: str
    args: list[str] = field(default_factory=list)
    indent: int = 0


@dataclass
class SetVariableRecord:
    var_name: str
    value: Any
    indent: int = 0


@dataclass
class IfRecord:
    operand1: Any
    operator: str
    operand2: Any
    indent: int = 0


@dataclass
class ElseIfRecord:
    operand1: Any
    operator: str
    operand2: Any
    indent: int = 0


@dataclass
class IfFunctionRecord:
    """`IF Contains(a, b, False) THEN`のような関数呼び出し形式の条件(知見18-2)。"""

    function_name: str
    args: list[Any]
    indent: int = 0


@dataclass
class ElseIfFunctionRecord:
    function_name: str
    args: list[Any]
    indent: int = 0


@dataclass
class CommentRecord:
    """`# <comment>`形式の単一行コメント、および`/# ... #/`形式の複数行コメント
    (design/robin_language_source_findings.md——`CommentStatement.ToString()`の
    ソースコードで両方の構文を確認。複数行の場合`text`に改行が含まれる)。
    """

    text: str
    indent: int = 0


@dataclass
class LoopRecord:
    loop_var: str
    start: Any
    end: Any
    step: Any
    indent: int = 0


@dataclass
class LoopForeachRecord:
    item_var: str
    collection: Any
    indent: int = 0


@dataclass
class LoopWhileRecord:
    operand1: Any
    operator: str
    operand2: Any
    indent: int = 0


@dataclass
class SwitchRecord:
    """`SWITCH <expr>`(design/robin_language_source_findings.md——`SwitchStatement.ToString()`
    のソースで構文を確認。ブロックとしてのネスト規則はIF/ELSE IF/ELSEとの文法上の並列性から
    類推した未検証の前提——モジュールdocstring参照)。
    """

    expression: Any
    indent: int = 0


@dataclass
class CaseRecord:
    """`CASE <value>`(`SwitchRecord`のアーム。`SwitchRecord`と同じindentに並ぶ)。"""

    value: Any
    indent: int = 0


@dataclass
class CaseDefaultRecord:
    """`DEFAULT`(ベアキーワード。`SwitchRecord`のcatch-allアーム)。"""

    indent: int = 0


@dataclass
class RawRecord:
    text: str
    indent: int = 0


Record = (
    ActionRecord
    | KeywordRecord
    | SetVariableRecord
    | IfRecord
    | ElseIfRecord
    | IfFunctionRecord
    | ElseIfFunctionRecord
    | CommentRecord
    | LoopRecord
    | LoopForeachRecord
    | LoopWhileRecord
    | SwitchRecord
    | CaseRecord
    | CaseDefaultRecord
    | RawRecord
)

_SIMPLE_BLOCK_HEADER_TYPES = (LoopRecord, LoopForeachRecord, LoopWhileRecord)


@dataclass
class BlockNode:
    """単純なブロック構文(`LOOP`系)の開始レコードと、対応する`END`までの本体。"""

    header: LoopRecord | LoopForeachRecord | LoopWhileRecord
    body: list[Node] = field(default_factory=list)


ConditionalArmHeader = IfRecord | ElseIfRecord | IfFunctionRecord | ElseIfFunctionRecord | KeywordRecord
_IF_HEADER_TYPES = (IfRecord, IfFunctionRecord)
_ELSEIF_HEADER_TYPES = (ElseIfRecord, ElseIfFunctionRecord)


@dataclass
class ConditionalNode:
    """`IF`/`ELSE IF`*/`ELSE`?/`END`全体を1つの構文単位として表す。

    各アームは`(header, body)`のタプル。`header`は`IfRecord`/`IfFunctionRecord`(先頭のみ)、
    `ElseIfRecord`/`ElseIfFunctionRecord`(0個以上)、または`KeywordRecord(name="ELSE")`
    (末尾に最大1個)。`END`は個々のアームにではなく構文全体に1つだけ対応するため、
    `ConditionalNode`は単一の`body`ではなく`arms`のリストを持つ。
    """

    arms: list[tuple[ConditionalArmHeader, list[Node]]] = field(default_factory=list)


SwitchArmHeader = CaseRecord | CaseDefaultRecord
_CASE_ARM_TYPES = (CaseRecord, CaseDefaultRecord)


@dataclass
class SwitchNode:
    """`SWITCH <expr>`/`CASE <value>`*/`DEFAULT`?/`END`全体を1つの構文単位として表す。

    `ConditionalNode`と同じ理由([`IF`/`ELSE IF`/`ELSE`と同じく`switch_statement`/
    `case_statement`/`case_default`も文法上並列な単なる文であり、専用のブロック構造を
    持たない——モジュールdocstring参照)で、`CASE`/`DEFAULT`アームを個別の`BlockNode`
    にせず、`SWITCH`全体を1つの`SwitchNode`としてまとめる。
    """

    expression: Any
    arms: list[tuple[SwitchArmHeader, list[Node]]] = field(default_factory=list)


Node = Record | BlockNode | ConditionalNode | SwitchNode


def build_block_tree(records: list[Record]) -> list[Node]:
    """`parse_dsl()`が返すフラットな`indent`付きレコード列から、ブロック木を組み立てる。

    design/dsl_format_findings.md 知見7・9・11で確認したルールに基づくスタック型の
    再帰下降パース:
    - `LOOP`系はブロック開始行と対応する`END`が同じindent深さ、本体だけがその1段内側。
    - `IF`/`ELSE IF`/`ELSE`は同じindent深さの1つの構文で、`END`は構文全体に1つだけ。
    - `SWITCH`/`CASE`/`DEFAULT`も同様に扱う(design/robin_language_source_findings.md——
      文法上`IF`/`ELSE IF`/`ELSE`と並列な構造であることをANTLR文法から確認したため、
      同じ規則を類推適用。SWITCH自身のインデント規則は未検証の前提——モジュールdocstring参照)。
    対応する`END`が見つからないまま入力が尽きた場合(壊れたデータ等)は、例外を出さず
    そこまでの本体を返す。
    """

    pos = 0

    def is_end(rec: Record, level: int) -> bool:
        return isinstance(rec, KeywordRecord) and rec.name == "END" and rec.indent == level

    def parse_level(level: int) -> list[Node]:
        nonlocal pos
        body: list[Node] = []
        while pos < len(records):
            rec = records[pos]
            if rec.indent < level:
                break
            if is_end(rec, level):
                pos += 1
                return body
            pos += 1
            if isinstance(rec, _IF_HEADER_TYPES):
                arms: list[tuple[ConditionalArmHeader, list[Node]]] = [(rec, parse_level(level + 1))]
                while pos < len(records):
                    nxt = records[pos]
                    if nxt.indent != level:
                        break
                    if isinstance(nxt, _ELSEIF_HEADER_TYPES):
                        pos += 1
                        arms.append((nxt, parse_level(level + 1)))
                        continue
                    if isinstance(nxt, KeywordRecord) and nxt.name == "ELSE":
                        pos += 1
                        arms.append((nxt, parse_level(level + 1)))
                        break
                    break
                if pos < len(records) and is_end(records[pos], level):
                    pos += 1
                body.append(ConditionalNode(arms=arms))
            elif isinstance(rec, SwitchRecord):
                switch_arms: list[tuple[SwitchArmHeader, list[Node]]] = []
                while pos < len(records):
                    nxt = records[pos]
                    if nxt.indent != level or not isinstance(nxt, _CASE_ARM_TYPES):
                        break
                    pos += 1
                    switch_arms.append((nxt, parse_level(level + 1)))
                    if isinstance(nxt, CaseDefaultRecord):
                        break
                if pos < len(records) and is_end(records[pos], level):
                    pos += 1
                body.append(SwitchNode(expression=rec.expression, arms=switch_arms))
            elif isinstance(rec, _SIMPLE_BLOCK_HEADER_TYPES):
                block_body = parse_level(level + 1)
                # parse_level(level + 1)はこのブロック自身の閉じENDを消費できない
                # (そのENDのindentはlevelであり、level + 1ではないため)。ここで明示的に
                # 消費しないと、呼び出し元のwhileループがこのENDを「呼び出し元自身の終端」と
                # 誤認し、後続の兄弟要素を黙って切り捨ててしまう(実データで発覚したバグ)。
                if pos < len(records) and is_end(records[pos], level):
                    pos += 1
                body.append(BlockNode(header=rec, body=block_body))
            else:
                body.append(rec)
        return body

    return parse_level(0)


_ACTION_ID_RE = _DOTTED_RE
_KNOWN_KEYWORDS = {"WAIT", "END", "ELSE", "EXIT", "NEXT"}


def parse_dsl(text: str) -> list[Record]:
    placeholders: dict[str, str] = {}

    def _stash_comment(m: re.Match[str]) -> str:
        key = f"\x00CMT{len(placeholders)}\x00"
        placeholders[key] = m.group(1)
        return key

    def _stash_string(m: re.Match[str]) -> str:
        key = f"\x00STR{len(placeholders)}\x00"
        placeholders[key] = m.group(1)
        return key

    # コメントを先に退避する(本文中に`$'''`等が含まれていても文字列リテラルとして
    # 誤認されないようにするため)。
    masked = _COMMENT_RE.sub(_stash_comment, text)
    masked = _STRING_RE.sub(_stash_string, masked)

    records: list[Record] = []
    for raw_line in masked.split("\n"):
        if not raw_line.strip():
            continue
        stripped = raw_line.lstrip(" ")
        indent = (len(raw_line) - len(stripped)) // 4
        records.append(_parse_line(stripped.rstrip(), placeholders, indent))
    return records


def _strip_parens(token: str) -> str:
    """`LOOP WHILE`のオペランド(`(LoopIndex)`等)を囲む丸括弧を取り除く。"""
    if token.startswith("(") and token.endswith(")"):
        return token[1:-1]
    return token


def _resolve_value(token: str, placeholders: dict[str, str]) -> Any:
    if token in placeholders:
        return _unescape(placeholders[token])
    if token == "True":
        return True
    if token == "False":
        return False
    if _FLOAT_RE.fullmatch(token):
        return float(token)
    if _INT_RE.fullmatch(token):
        return int(token)
    if _DOTTED_RE.fullmatch(token):
        return EnumRef(token)
    return VarRef(token)


def _parse_line(line: str, placeholders: dict[str, str], indent: int = 0) -> Record:
    if line.startswith("\x00CMT") and line in placeholders:
        # `CommentStatement.ToString()`は常に`"/# " + escaped + "#/"`という形で
        # `/#`の直後に1文字の空白を固定で挿入する(コメント本文自体が空白で始まる
        # 場合でも区別なく追加される)。そのためここでは「空白なら剥がす」のような
        # 条件分岐ではなく、常に先頭1文字をデリミタの一部として取り除く。
        return CommentRecord(text=_unescape_comment(placeholders[line][1:]), indent=indent)
    if line.startswith("# "):
        return CommentRecord(text=line[2:], indent=indent)
    if line == "#":
        return CommentRecord(text="", indent=indent)

    func_match = _FUNC_COND_RE.match(line)
    if func_match:
        keyword, func_name, args_str = func_match.groups()
        args = [_resolve_value(a.strip(), placeholders) for a in args_str.split(",")]
        if keyword == "IF":
            return IfFunctionRecord(function_name=func_name, args=args, indent=indent)
        return ElseIfFunctionRecord(function_name=func_name, args=args, indent=indent)

    tokens = line.split()
    first = tokens[0]

    if first == "SET" and len(tokens) >= 4 and tokens[2] == "TO":
        return SetVariableRecord(
            var_name=tokens[1],
            value=_resolve_value(tokens[3], placeholders),
            indent=indent,
        )

    if first == "ELSE" and len(tokens) >= 6 and tokens[1] == "IF" and tokens[-1] == "THEN":
        return ElseIfRecord(
            operand1=_resolve_value(tokens[2], placeholders),
            operator=tokens[3],
            operand2=_resolve_value(tokens[4], placeholders),
            indent=indent,
        )

    if first == "IF" and len(tokens) >= 5 and tokens[-1] == "THEN":
        return IfRecord(
            operand1=_resolve_value(tokens[1], placeholders),
            operator=tokens[2],
            operand2=_resolve_value(tokens[3], placeholders),
            indent=indent,
        )

    if first == "LOOP" and len(tokens) >= 5 and tokens[1] == "FOREACH" and tokens[3] == "IN":
        return LoopForeachRecord(
            item_var=tokens[2],
            collection=_resolve_value(tokens[4], placeholders),
            indent=indent,
        )

    if first == "LOOP" and len(tokens) >= 5 and tokens[1] == "WHILE":
        return LoopWhileRecord(
            operand1=_resolve_value(_strip_parens(tokens[2]), placeholders),
            operator=tokens[3],
            operand2=_resolve_value(_strip_parens(tokens[4]), placeholders),
            indent=indent,
        )

    if (
        first == "LOOP"
        and len(tokens) >= 8
        and tokens[2] == "FROM"
        and tokens[4] == "TO"
        and tokens[6] == "STEP"
    ):
        return LoopRecord(
            loop_var=tokens[1],
            start=_resolve_value(tokens[3], placeholders),
            end=_resolve_value(tokens[5], placeholders),
            step=_resolve_value(tokens[7], placeholders),
            indent=indent,
        )

    if first == "SWITCH" and len(tokens) == 2:
        return SwitchRecord(expression=_resolve_value(tokens[1], placeholders), indent=indent)

    if first == "CASE" and len(tokens) == 2:
        return CaseRecord(value=_resolve_value(tokens[1], placeholders), indent=indent)

    if first == "DEFAULT" and len(tokens) == 1:
        return CaseDefaultRecord(indent=indent)

    if first in _KNOWN_KEYWORDS:
        return KeywordRecord(name=first, args=tokens[1:], indent=indent)

    if not _ACTION_ID_RE.match(first):
        return RawRecord(text=line, indent=indent)

    record = ActionRecord(action_id=first, indent=indent)
    i = 1
    while i < len(tokens):
        tok = tokens[i]
        if tok.endswith("=>"):
            # 出力パラメータ名(例: `ButtonPressed=>`の`ButtonPressed`)とVar名が同名の
            # ケースが多いが、必ずしも一致するとは限らない。1個のアクションが複数の出力を
            # 持つ場合(例: `WindowTitle=> WindowTitle WindowInstance=> AutomationWindow`)が
            # あるため、全ての束縛を output_vars(パラメータ名→変数名)に記録する。
            # output_var は後方互換のため最後に見つかったものを保持する(単一出力の
            # アクションではこれで十分だが、複数出力では output_vars を参照すること)。
            if i + 1 >= len(tokens):
                break
            param_name = tok[:-2]
            var_name = tokens[i + 1]
            record.output_var = var_name
            record.output_vars[param_name] = var_name
            i += 2
            continue
        if tok.endswith(":"):
            name = tok[:-1]
            if i + 1 >= len(tokens):
                break
            record.params[name] = _resolve_value(tokens[i + 1], placeholders)
            i += 2
            continue
        # 未知のトークン形式。パラメータ値が空白を含む等、今回の文法理解を超えるケース。
        i += 1

    return record
