"""PADの「コピー&ペースト」クリップボードDSLのプロトタイプパーサー。

design/dsl_format_findings.md で実機検証した文法に基づく。対応している範囲:
- `ActionId Param: Value ... Output=> Var` 形式の一般アクション行
- `$'''...'''`(複数行可)の文字列リテラル、および `\"`/`\\` のエスケープ解除
- `Namespace.Enum.Value` 形式の列挙値、`True`/`False` の真偽値
- `WAIT <seconds>` のようなベアキーワード行(action行のパターンに一致しない行は
  種別不明の `raw` レコードとしてそのまま保持し、サイレントに捨てない)

未対応(今後の実機確認が必要): SET/LOOP FOREACH/IF 等の他のキーワード構文、
`%VarName%` 変数参照の値種別としての明示的な扱い。
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


@dataclass
class KeywordRecord:
    name: str
    args: list[str] = field(default_factory=list)


@dataclass
class RawRecord:
    text: str


Record = ActionRecord | KeywordRecord | RawRecord

_ACTION_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")
_KNOWN_KEYWORDS = {"WAIT"}


def parse_dsl(text: str) -> list[Record]:
    placeholders: dict[str, str] = {}

    def _stash(m: re.Match[str]) -> str:
        key = f"\x00STR{len(placeholders)}\x00"
        placeholders[key] = m.group(1)
        return key

    masked = _STRING_RE.sub(_stash, text)

    records: list[Record] = []
    for line in masked.split("\n"):
        line = line.strip()
        if not line:
            continue
        records.append(_parse_line(line, placeholders))
    return records


def _resolve_value(token: str, placeholders: dict[str, str]) -> Any:
    if token in placeholders:
        return _unescape(placeholders[token])
    if token == "True":
        return True
    if token == "False":
        return False
    return token


def _parse_line(line: str, placeholders: dict[str, str]) -> Record:
    tokens = line.split()
    first = tokens[0]

    if first in _KNOWN_KEYWORDS:
        return KeywordRecord(name=first, args=tokens[1:])

    if not _ACTION_ID_RE.match(first):
        return RawRecord(text=line)

    record = ActionRecord(action_id=first)
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
