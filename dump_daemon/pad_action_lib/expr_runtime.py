"""`SET ... TO`複合式の演算子のうち、Pythonの素直な演算子では再現できない
値の意味論を実装する共有ヘルパー。

design/dsl_format_findings.md 知見86(実機確認済み): PADの`+`演算子は両辺が
数値(または数値を表す文字列)として解釈できる場合は数値加算を行い、どちらかが
数値として解釈できない文字列の場合にのみ文字列結合にフォールバックする
(`1 + "2"` = `3`・`"2" + 1` = `3`・`"a" + "b"` = `"ab"`、いずれも実機確認済み)。
VB.NETの`+`演算子オーバーロード規則(文字列専用の連結には別の`&`演算子がある)と
整合する挙動。
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
