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

未対応(今後の実機確認が必要): LOOP FOREACH、ELSE/ELSE IF、複合式(AND/OR)、
インデント情報からの木構造組み立て(現状は`indent`を保持した**フラットな**
レコード列を返すのみで、`IfRecord`/`LoopRecord`と対応する`END`を自動的にグルーピングしない)。
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
class LoopRecord:
    loop_var: str
    start: Any
    end: Any
    step: Any
    indent: int = 0


@dataclass
class RawRecord:
    text: str
    indent: int = 0


Record = ActionRecord | KeywordRecord | SetVariableRecord | IfRecord | LoopRecord | RawRecord

_ACTION_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")
_KNOWN_KEYWORDS = {"WAIT", "END"}


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


def _resolve_value(token: str, placeholders: dict[str, str]) -> Any:
    if token in placeholders:
        return _unescape(placeholders[token])
    if token == "True":
        return True
    if token == "False":
        return False
    return token


def _parse_line(line: str, placeholders: dict[str, str], indent: int = 0) -> Record:
    tokens = line.split()
    first = tokens[0]

    if first == "SET" and len(tokens) >= 4 and tokens[2] == "TO":
        return SetVariableRecord(
            var_name=tokens[1],
            value=_resolve_value(tokens[3], placeholders),
            indent=indent,
        )

    if first == "IF" and len(tokens) >= 5 and tokens[-1] == "THEN":
        return IfRecord(
            operand1=_resolve_value(tokens[1], placeholders),
            operator=tokens[2],
            operand2=_resolve_value(tokens[3], placeholders),
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
