"""E3: 複数トレース比較の基礎アルゴリズム(ループ本体・ループ変数の抽出)の検証。

GUI操作を伴わない純粋なロジックテストのため、Windows限定ではない。
"""
from __future__ import annotations

import pytest

from dump_daemon.trace_compare import TraceShapeMismatch, extract_loop_candidate


def _make_trace(page_number: int) -> list[dict]:
    return [
        {"action_type": "UIAutomation.Click", "params": {"Control": "%NextButton%"}},
        {
            "action_type": "UIAutomation.GetText",
            "params": {"Control": "%PageLabel%", "Expected": f"Page {page_number}"},
        },
    ]


def test_extract_loop_candidate_detects_varying_page_param() -> None:
    traces = [_make_trace(1), _make_trace(2), _make_trace(3)]
    result = extract_loop_candidate(traces)

    assert result["body"] == ["UIAutomation.Click", "UIAutomation.GetText"]
    assert 1 in result["loop_vars"]
    assert result["loop_vars"][1]["Expected"] == ["Page 1", "Page 2", "Page 3"]
    assert 0 not in result["loop_vars"], "Clickアクションのパラメータは不変のはず"


def test_extract_loop_candidate_rejects_mismatched_action_sequence() -> None:
    trace_a = [{"action_type": "A", "params": {}}]
    trace_b = [{"action_type": "B", "params": {}}]

    with pytest.raises(TraceShapeMismatch):
        extract_loop_candidate([trace_a, trace_b])


def test_extract_loop_candidate_rejects_mismatched_length() -> None:
    short = [{"action_type": "A", "params": {}}]
    long_ = [{"action_type": "A", "params": {}}, {"action_type": "B", "params": {}}]

    with pytest.raises(TraceShapeMismatch):
        extract_loop_candidate([short, long_])


def test_extract_loop_candidate_requires_at_least_two_traces() -> None:
    with pytest.raises(ValueError):
        extract_loop_candidate([_make_trace(1)])
