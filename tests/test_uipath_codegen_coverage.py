"""`dump_daemon.uipath_codegen_coverage`自体の回帰テスト。

design/evidence/uipath_xaml_probe/Main.xaml・Sub1.xaml(知見1〜36で実機
コンパイル確認済みのXAML構造)を対象に、`uipath_codegen`の分岐点カバレッジが
現時点で79%(23/29)であることをロックする(知見70、知見96でHttpClientNode・
知見97でExcelApplicationScopeNodeのTODO解消により72%→76%→79%へ向上)。
この閾値を下回ったら既存の結線が壊れた可能性が高い——上回る変化(新しい
アクティビティのcodegen対応等)は歓迎なので、閾値を更新してよい。

**`ExcelWriteCellNode`が依然TODO判定になる理由(バグではない)**: このツール
は`_strip_children`で各ノード型を単独に切り出して測定するが、知見97の
`ExcelWriteCellNode`対応は囲む`ExcelApplicationScopeNode`の`scope_var`
文脈に依存する設計のため、単独評価では(意図的に安全側の)`# TODO`経路に
入る。実際の`Main.xaml`全体(スコープに正しくネストした状態)では実コード
生成される——`test_excel_application_scope_with_write_cell_generates_
real_code_together`(test_uipath_codegen.py)参照。
"""
from __future__ import annotations

from dump_daemon.uipath_codegen_coverage import FIXTURE_DIR, FIXTURE_FILES, collect_report


def test_uipath_codegen_coverage_is_at_least_79_percent() -> None:
    fixture_paths = [FIXTURE_DIR / name for name in FIXTURE_FILES]
    buckets = collect_report(fixture_paths)
    total = sum(b.total for b in buckets.values())
    total_ok = sum(b.ok for b in buckets.values())
    assert total > 0
    # 23/29 ≈ 79.31% — 閾値は切り捨てた79%で浮動小数点の誤差を避ける。
    assert total_ok / total >= 0.79


def test_uipath_codegen_coverage_reports_the_remaining_deferred_activities_as_todo() -> None:
    """design/uipath_transpiler_roadmap.md Phase 4が「架空の変換をでっち上げず
    # TODOに倒す」と明記した活動が、このカバレッジツールでも一貫してTODO
    判定になることの回帰テスト——知見96でHttpClientNode・知見97で
    ExcelApplicationScopeNodeが実コード生成対応済みになったため、知見70の
    5件から残り3件へ更新(新しい実装が追加された場合はこのテストも更新が
    必要になる、その場合はカバレッジが向上した良い兆候)。"""
    fixture_paths = [FIXTURE_DIR / name for name in FIXTURE_FILES]
    buckets = collect_report(fixture_paths)
    todo_identities = {
        identity for (kind, identity), bucket in buckets.items() if kind == "activity" and bucket.label == "TODO"
    }
    for expected in (
        "ExcelWriteCellNode",
        "InvokeCodeNode",
        "SendOutlookMailNode",
    ):
        assert expected in todo_identities, f"{expected} should still be TODO (or coverage improved — update test)"
    for resolved in ("HttpClientNode", "ExcelApplicationScopeNode"):
        assert resolved not in todo_identities, (
            f"{resolved} is codegen-supported now (知見96・97) — if this starts "
            "failing because it moved back to TODO, that's a regression"
        )
