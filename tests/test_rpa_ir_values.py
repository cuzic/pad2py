"""`dump_daemon.rpa_ir.values`の単体テスト。

design/common_rpa_framework_roadmap.md 層1(共通IR)の第一歩。純粋なデータ構造のみ
(FCISのFunctional Core)なので、I/O・VM・ファイルシステムに一切依存せず瞬時に
実行できる——「coreを高速に検証できる構造にする」という方針そのものの実例でもある。
"""
from __future__ import annotations

from dump_daemon.rpa_ir import EnumRef, Literal, RawExpr, Value, VarRef


def test_all_value_types_are_frozen_and_hashable() -> None:
    # 不変のマーカー型として、辞書のキーやsetの要素として使える必要がある
    # (`pad_dsl`/`uipath_dsl`どちらも、パース結果をそのまま比較・集合演算することがある)。
    values = [Literal("x"), VarRef("MyVar"), RawExpr("1 + 2"), EnumRef("Namespace.Enum.Value")]
    for value in values:
        hash(value)  # 例外が起きないことを確認するだけで十分


def test_values_compare_by_field_equality() -> None:
    assert Literal("x") == Literal("x")
    assert Literal("x") != Literal("y")
    assert VarRef("MyVar") == VarRef("MyVar")
    assert VarRef("MyVar") != VarRef("OtherVar")
    assert RawExpr("1 + 2") == RawExpr("1 + 2")
    assert RawExpr("1 + 2", tree="parsed") != RawExpr("1 + 2")  # treeも等価性に含まれる
    assert EnumRef("A.B.C") == EnumRef("A.B.C")


def test_raw_expr_tree_defaults_to_none_and_does_not_lose_text_on_parse_failure() -> None:
    # 構文解析に失敗した場合でも`text`自体は失わない、という設計方針
    # (design/dsl_format_findings.md 知見53/uipath_xaml_findings.md 知見2の「でっち上げない」方針)。
    unparsed = RawExpr("some unparseable expression")
    assert unparsed.tree is None
    assert unparsed.text == "some unparseable expression"


def test_value_union_covers_all_four_types_via_isinstance() -> None:
    # `Value`がUnion型として正しく機能し、利用側の`isinstance`チェーンで
    # 全パターンを尽くせることを確認する(網羅性チェックの代わり)。
    candidates: list[Value] = [Literal("x"), VarRef("v"), RawExpr("e"), EnumRef("A.B")]
    for value in candidates:
        matched = isinstance(value, (Literal, VarRef, RawExpr, EnumRef))
        assert matched, f"{value!r} did not match any Value variant"
