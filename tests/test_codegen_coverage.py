"""`dump_daemon.codegen_coverage`自体の回帰テスト。

実機キャプチャ済みのTier1/Tier2アクション群を`pad_action_lib`へ結線した結果、
`pad_codegen`の分岐点カバレッジが80%以上になったことをロックする(design/
dsl_format_findings.md 知見73)。この閾値を下回ったら、新しいTier1/2アクションの
追加やフィクスチャ変更が既存の結線を壊した可能性が高い。
"""
from __future__ import annotations

from dump_daemon.codegen_coverage import FIXTURES_DIR, collect_report


def test_codegen_coverage_is_at_least_80_percent() -> None:
    fixture_paths = sorted(FIXTURES_DIR.glob("*.txt"))
    buckets = collect_report(fixture_paths)
    total = sum(b.total for b in buckets.values())
    total_ok = sum(b.ok for b in buckets.values())
    assert total > 0
    assert total_ok / total >= 0.80
