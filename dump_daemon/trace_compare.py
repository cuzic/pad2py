"""複数トレースからのループ本体・ループ変数抽出(検証項目 E3)のプロトタイプ実装。

PBD/Web macro generalization研究(Rousillon等, research_notes/.../02_trace_generalization.md)の
発想を単純化したもの。同じ長さ・同じ action_type 列を持つ複数トレースについて、
各位置の params の値がトレース間で変化する部分をループ変数、変化しない部分を
ループ本体の固定パラメータとみなす。

終了条件の確定は前回の調査で「人間確認が必須」とされているため、ここでは扱わない
(別途、最終トレースとの差分を人間に提示する確認UIの対象とする)。
"""
from __future__ import annotations

from typing import Any


class TraceShapeMismatch(Exception):
    """トレース間でアクション種別・長さが一致しない場合に発生する。"""


def extract_loop_candidate(traces: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """複数トレースを比較し、ループ本体(action_type列)とループ変数候補を抽出する。

    traces: 各要素が1本のトレース(action_type/paramsを持つdictのリスト)。
    全トレースは同じ長さ・同じaction_type列を持つことを前提とする
    (終了条件を含む異なる長さのトレースは別途扱う)。
    """
    if len(traces) < 2:
        raise ValueError("ループ推測には最低2本のトレースが必要")

    lengths = {len(t) for t in traces}
    if len(lengths) != 1:
        raise TraceShapeMismatch(
            "トレース長が一致しない。終了条件を含む最終トレースは人間確認で別途処理する前提のため、"
            "ここでは同一長のトレース群のみを受け付ける。"
        )

    length = lengths.pop()
    body: list[str] = []
    loop_vars: dict[int, dict[str, list[Any]]] = {}

    for i in range(length):
        action_types = {t[i]["action_type"] for t in traces}
        if len(action_types) != 1:
            raise TraceShapeMismatch(f"位置{i}でアクション種別が一致しない: {action_types}")
        body.append(action_types.pop())

        all_keys: set[str] = set()
        for t in traces:
            all_keys.update(t[i].get("params", {}).keys())

        for key in all_keys:
            values = [t[i].get("params", {}).get(key) for t in traces]
            if len(set(values)) > 1:
                loop_vars.setdefault(i, {})[key] = values

    return {"body": body, "loop_vars": loop_vars}
