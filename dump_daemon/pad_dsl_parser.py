"""PADの「コピー&ペースト」クリップボードDSLのプロトタイプパーサー。

design/dsl_format_findings.md で実機検証した文法に基づく。対応している範囲:
- `ActionId Param: Value ... Output=> Var` 形式の一般アクション行
- `$'''...'''`(複数行可)の文字列リテラル、および `\"`/`\\` のエスケープ解除
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

未対応(今後の実機確認が必要): 複合式(AND/OR)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_STRING_RE = re.compile(r"\$'''(.*?)'''", re.DOTALL)
_ESCAPE_RE = re.compile(r'\\\\|\\"')


def _unescape(raw: str) -> str:
    """DSL文字列リテラル内の `\\"` → `"`、`\\\\` → `\\` を解除する。"""
    return _ESCAPE_RE.sub(lambda m: '"' if m.group(0) == '\\"' else "\\", raw)


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
    """

    value: str


_DOTTED_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")
_INT_RE = re.compile(r"-?\d+")
_FLOAT_RE = re.compile(r"-?\d+\.\d+")


@dataclass
class ActionRecord:
    action_id: str
    params: dict[str, Any] = field(default_factory=dict)
    output_var: str | None = None
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
class RawRecord:
    text: str
    indent: int = 0


Record = (
    ActionRecord
    | KeywordRecord
    | SetVariableRecord
    | IfRecord
    | ElseIfRecord
    | LoopRecord
    | LoopForeachRecord
    | LoopWhileRecord
    | RawRecord
)

_SIMPLE_BLOCK_HEADER_TYPES = (LoopRecord, LoopForeachRecord, LoopWhileRecord)


@dataclass
class BlockNode:
    """単純なブロック構文(`LOOP`系)の開始レコードと、対応する`END`までの本体。"""

    header: LoopRecord | LoopForeachRecord | LoopWhileRecord
    body: list[Node] = field(default_factory=list)


ConditionalArmHeader = IfRecord | ElseIfRecord | KeywordRecord


@dataclass
class ConditionalNode:
    """`IF`/`ELSE IF`*/`ELSE`?/`END`全体を1つの構文単位として表す。

    各アームは`(header, body)`のタプル。`header`は`IfRecord`(先頭のみ)、
    `ElseIfRecord`(0個以上)、または`KeywordRecord(name="ELSE")`(末尾に最大1個)。
    `END`は個々のアームにではなく構文全体に1つだけ対応するため、`ConditionalNode`は
    単一の`body`ではなく`arms`のリストを持つ。
    """

    arms: list[tuple[ConditionalArmHeader, list[Node]]] = field(default_factory=list)


Node = Record | BlockNode | ConditionalNode


def build_block_tree(records: list[Record]) -> list[Node]:
    """`parse_dsl()`が返すフラットな`indent`付きレコード列から、ブロック木を組み立てる。

    design/dsl_format_findings.md 知見7・9・11で確認したルールに基づくスタック型の
    再帰下降パース:
    - `LOOP`系はブロック開始行と対応する`END`が同じindent深さ、本体だけがその1段内側。
    - `IF`/`ELSE IF`/`ELSE`は同じindent深さの1つの構文で、`END`は構文全体に1つだけ。
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
            if isinstance(rec, IfRecord):
                arms: list[tuple[ConditionalArmHeader, list[Node]]] = [(rec, parse_level(level + 1))]
                while pos < len(records):
                    nxt = records[pos]
                    if nxt.indent != level:
                        break
                    if isinstance(nxt, ElseIfRecord):
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
            elif isinstance(rec, _SIMPLE_BLOCK_HEADER_TYPES):
                body.append(BlockNode(header=rec, body=parse_level(level + 1)))
            else:
                body.append(rec)
        return body

    return parse_level(0)


_ACTION_ID_RE = _DOTTED_RE
_KNOWN_KEYWORDS = {"WAIT", "END", "ELSE", "EXIT", "NEXT"}


def parse_dsl(text: str) -> list[Record]:
    placeholders: dict[str, str] = {}

    def _stash(m: re.Match[str]) -> str:
        key = f"\x00STR{len(placeholders)}\x00"
        placeholders[key] = m.group(1)
        return key

    masked = _STRING_RE.sub(_stash, text)

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

    if first in _KNOWN_KEYWORDS:
        return KeywordRecord(name=first, args=tokens[1:], indent=indent)

    if not _ACTION_ID_RE.match(first):
        return RawRecord(text=line, indent=indent)

    record = ActionRecord(action_id=first, indent=indent)
    i = 1
    while i < len(tokens):
        tok = tokens[i]
        if tok.endswith("=>"):
            # 出力パラメータ名自体は破棄し、変数名だけを output_var として保持する
            # (例: `ButtonPressed=> ButtonPressed` のパラメータ名とVar名が同名のケースが
            # 多いが、必ずしも一致するとは限らない)。
            if i + 1 >= len(tokens):
                break
            record.output_var = tokens[i + 1]
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
