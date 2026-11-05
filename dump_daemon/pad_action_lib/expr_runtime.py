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
"""
from __future__ import annotations


def _as_number(value: object) -> int | float | None:
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
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
    数値を表す文字列と数値は型をまたいで等価と判定される(`"1"` = `1`は真)。
    """
    if a == b:
        return True
    try:
        return float(a) == float(b)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
