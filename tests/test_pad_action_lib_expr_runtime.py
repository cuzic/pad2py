"""`pad_action_lib.expr_runtime`の単体テスト。

design/dsl_format_findings.md 知見86で実機確認したPADの`+`演算子の値の意味論
(数値/数値文字列同士は数値加算、そうでなければ文字列結合)を検証する。
"""
from __future__ import annotations

from dump_daemon.pad_action_lib import expr_runtime as er


def test_pad_add_adds_two_numbers() -> None:
    assert er.pad_add(1, 2) == 3


def test_pad_add_coerces_numeric_string_and_number() -> None:
    # 実機確認済み: `1 + "2" = 3`(TypeErrorにならず数値加算)。
    assert er.pad_add(1, "2") == 3
    assert er.pad_add("2", 1) == 3


def test_pad_add_coerces_two_numeric_strings() -> None:
    assert er.pad_add("1", "2") == 3


def test_pad_add_concatenates_non_numeric_strings() -> None:
    # 実機確認済み: `"a" + "b" = "ab"`。
    assert er.pad_add("a", "b") == "ab"


def test_pad_add_falls_back_to_string_concat_when_either_side_is_non_numeric() -> None:
    assert er.pad_add("a", 1) == "a1"
    assert er.pad_add(1, "a") == "1a"


def test_pad_equal_coerces_numeric_string_and_number() -> None:
    # design/dsl_format_findings.md 知見88で実機確認済み: `"1" = 1`は真。
    assert er.pad_equal("1", 1) is True
    assert er.pad_equal(1, "1") is True


def test_pad_equal_is_case_sensitive_for_strings() -> None:
    # 実機確認済み: `"Apple" = "apple"`は偽(知見85の比較エンジンと同じ規則)。
    assert er.pad_equal("Apple", "apple") is False


def test_pad_equal_matches_identical_strings() -> None:
    assert er.pad_equal("abc", "abc") is True


def test_pad_equal_matches_identical_numbers() -> None:
    assert er.pad_equal(1, 1) is True
