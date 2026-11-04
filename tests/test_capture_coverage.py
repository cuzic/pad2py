"""capture_coverage.pyの単体テスト。"""
from __future__ import annotations

from dump_daemon.capture_coverage import (
    TARGET_ACTIONS,
    compute_report,
    format_report,
    is_captured,
)


def test_target_actions_have_unique_name_per_module() -> None:
    seen: set[tuple[str, str]] = set()
    for target in TARGET_ACTIONS:
        key = (target.module, target.name)
        assert key not in seen, f"duplicate target: {key}"
        seen.add(key)


def test_compute_report_marks_already_captured_actions() -> None:
    report = compute_report()
    by_name = {
        (target.module, target.name): done
        for items in report.values()
        for target, done in items
    }
    # tests/fixtures/tier1_text_variables_batch1.txtで実際にキャプチャ済みのもの。
    assert by_name[("Text", "Trim")] is True
    assert by_name[("Variables", "ReverseList")] is True


def test_format_report_includes_overall_percentage() -> None:
    report = compute_report()
    text = format_report(report)
    assert "全体:" in text
    assert "%" in text


def test_compute_report_counts_if_and_wait_action_records_too() -> None:
    # design/dsl_format_findings.md 知見69の修正: IfActionRecord/WaitActionRecordは
    # ActionRecordとは別のdataclassのため、修正前はcollect_captured_action_ids()が
    # これらを一切集計せず、実機キャプチャ済みのIfFolderExists/IfFile/WaitForFileが
    # 永遠に未キャプチャ扱いになっていた回帰を防ぐ。
    report = compute_report()
    by_name = {
        (target.module, target.name): done
        for items in report.values()
        for target, done in items
    }
    assert by_name[("Folder", "IfFolderExists")] is True
    assert by_name[("File", "IfFile")] is True
    assert by_name[("File", "WaitForFile")] is True


def test_is_captured_matches_by_prefix_not_substring() -> None:
    from dump_daemon.capture_coverage import TargetAction

    target = TargetAction("Text", "Trim", "Trim text", "Text.Trim")
    assert is_captured(target, {"Text.Trim"}) is True
    assert is_captured(target, {"Text.TrimSomethingElse"}) is True
    # 別アクション(例: Text.TrimOption相当の架空の値)が先頭一致してしまわないよう、
    # 明確に無関係なIDでは一致しないことも確認する。
    assert is_captured(target, {"Text.ChangeCase"}) is False
