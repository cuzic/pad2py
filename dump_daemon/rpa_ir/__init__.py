"""複数のRPAツール変換トラック(`pad_dsl`/`uipath_dsl`等)が共有する中間表現(IR)の核。

design/common_rpa_framework_roadmap.md 層1(共通IR)の第一歩。PAD/UiPathそれぞれの
フロントエンド(字句解析/XML解析)は各ツール固有の事情が大きく異なるため統合しない
——統合する価値があるのはバックエンド側(パース結果の表現以降)だけ、という
ロードマップの判断に基づく。

`values`サブモジュールは「DSL上の値がどう表現されているか」という、字句解析以後の
全coreが参照する共有語彙(`Literal`/`VarRef`/`RawExpr`/`EnumRef`)を提供する。
純粋なデータ構造のみで、パース処理そのものには一切依存しない(FCISの
Functional Core)。

**移行方針(2026-11-05時点)**: `pad_dsl.types`は本パッケージの型を再公開する形へ
移行済み(既存の`pad_dsl`利用側・テストは無変更で動く——`isinstance`チェックが
参照する型オブジェクト自体は`rpa_ir.values`で定義された同一のクラス)。
`uipath_dsl.types`の移行(`VbExpr`→`RawExpr`、`Literal`の統合)は、
`uipath_codegen`を並行して活発に開発している別セッションとの衝突を避けるため、
そのセッションが空いているタイミングでの協調作業として意図的に見送っている
(design/common_rpa_framework_roadmap.md Phase 2参照)。
"""
from __future__ import annotations

from .values import EnumRef, Literal, RawExpr, Value, VarRef

__all__ = ["EnumRef", "Literal", "RawExpr", "Value", "VarRef"]
