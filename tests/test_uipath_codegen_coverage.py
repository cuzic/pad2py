"""`dump_daemon.uipath_codegen_coverage`自体の回帰テスト。

design/evidence/uipath_xaml_probe/Main.xaml・Sub1.xaml(知見1〜36で実機
コンパイル確認済みのXAML構造)を対象に、`uipath_codegen`の分岐点カバレッジが
現時点で72%(21/29)であることをロックする(知見70)。この閾値を下回ったら
既存の結線が壊れた可能性が高い——上回る変化(新しいアクティビティのcodegen
対応等)は歓迎なので、閾値を更新してよい。
"""
from __future__ import annotations

from dump_daemon.uipath_codegen_coverage import FIXTURE_DIR, FIXTURE_FILES, collect_report


def test_uipath_codegen_coverage_is_at_least_72_percent() -> None:
    fixture_paths = [FIXTURE_DIR / name for name in FIXTURE_FILES]
    buckets = collect_report(fixture_paths)
    total = sum(b.total for b in buckets.values())
    total_ok = sum(b.ok for b in buckets.values())
    assert total > 0
    assert total_ok / total >= 0.72


def test_uipath_codegen_coverage_reports_the_5_known_deferred_activities_as_todo() -> None:
    """design/uipath_transpiler_roadmap.md Phase 4が「架空の変換をでっち上げず
    # TODOに倒す」と明記した5つの活動(`_generate_unresolved_activity`、
    `uipath_codegen/__init__.py`参照)が、このカバレッジツールでも一貫して
    TODO判定になることの回帰テスト——新しい実装が追加された場合はこのテスト
    も更新が必要になる(その場合はカバレッジが向上した良い兆候)。"""
    fixture_paths = [FIXTURE_DIR / name for name in FIXTURE_FILES]
    buckets = collect_report(fixture_paths)
    todo_identities = {
        identity for (kind, identity), bucket in buckets.items() if kind == "activity" and bucket.label == "TODO"
    }
    for expected in (
        "ExcelApplicationScopeNode",
        "ExcelWriteCellNode",
        "HttpClientNode",
        "InvokeCodeNode",
        "SendOutlookMailNode",
    ):
        assert expected in todo_identities, f"{expected} should still be TODO (or coverage improved — update test)"
