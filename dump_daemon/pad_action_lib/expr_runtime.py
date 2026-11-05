"""`SET ... TO`複合式の演算子のうち、Pythonの素直な演算子では再現できない
値の意味論を実装する共有ヘルパー。

design/dsl_format_findings.md 知見86(実機確認済み): PADの`+`演算子は両辺が
数値(または数値を表す文字列)として解釈できる場合は数値加算を行い、どちらかが
数値として解釈できない文字列の場合にのみ文字列結合にフォールバックする
(`1 + "2"` = `3`・`"2" + 1` = `3`・`"a" + "b"` = `"ab"`、いずれも実機確認済み)。
VB.NETの`+`演算子オーバーロード規則(文字列専用の連結には別の`&`演算子がある)と
整合する挙動。

design/dsl_format_findings.md 知見88(実機確認済み): `=`/`<>`演算子も知見85の
`ComparisonCalculator.Compare`と同じ型変換規則に従う(`"1" = 1`は真、`"Apple" =
"apple"`は偽)。

design/dsl_format_findings.md 知見101(実機確認済み): `+`/`=`演算子が「数値を表す
文字列」と認識する範囲はPythonの`int()`/`float()`より狭く、**指数表記(`"1e2"`)を
数値として認識しない**——`1 + "1e2"`は数値加算ではなく文字列結合(`"11e2"`)に、
`"1e2" = 100`は偽になる(知見84/92/100のCSV読み込み系の数値変換はこれとは別の
PADサブシステムで、こちらは指数表記を数値として受理する——両者は異なる規則)。
一方で知見102(実機確認済み)の通り、**桁区切りコンマ(`"1,000"`)は数値として
認識する**——`1 + "1,000"` = `1001`(文字列結合ではない)・`"1,000" = 1000`は真。
`_NUMERIC_STRING_RE`で「符号+(コンマ区切り可の)整数+小数部」のみを数値文字列
として認識するよう制限し(指数表記は除外、桁区切りコンマは許容)、実際の数値
変換時はコンマを取り除いてから`int()`/`float()`に渡す。
"""
from __future__ import annotations

import re

_NUMERIC_STRING_RE = re.compile(r"^[+-]?[\d,]+(\.\d+)?$")


def _as_number(value: object) -> int | float | None:
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str) and _NUMERIC_STRING_RE.match(value):
        cleaned = value.replace(",", "")
        try:
            return int(cleaned)
        except ValueError:
            pass
        try:
            return float(cleaned)
        except ValueError:
            pass
    return None


def pad_add(a: object, b: object) -> object:
    na, nb = _as_number(a), _as_number(b)
    if na is not None and nb is not None:
        return na + nb
    return str(a) + str(b)


def pad_equal(a: object, b: object) -> bool:
    """design/dsl_format_findings.md 知見88(実機確認済み)。PADの`=`/`<>`演算子は、

    知見85で確認した`ComparisonCalculator.Compare`(`SubtractLists`等が使う比較エンジン)
    と同じ規則に従う: 文字列同士は大文字小文字を区別するが(`"Apple"` = `"apple"`は偽)、
    数値を表す文字列と数値は型をまたいで等価と判定される(`"1"` = `1`は真)。知見101で
    指数表記(`"1e2"`)は数値として認識されない(`"1e2" = 100`は偽)ことを実機確認済み
    のため、`_as_number()`と同じ`_NUMERIC_STRING_RE`の判定を共有する。
    """
    if a == b:
        return True
    na, nb = _as_number(a), _as_number(b)
    if na is not None and nb is not None:
        return na == nb
    return False
