"""`uipath_codegen`がどこまで実コードを生成できているかを実測するカバレッジ測定ツール。

design/uipath_transpiler_roadmap.md Phase 4が「PAD側の`codegen_coverage.py`
のようなカバレッジ測定ツールを作り、優先度順に埋めていく」と明記していたが、
UiPath側ではこのツール自体がまだ作られていなかった(知見70で着手)。
`dump_daemon.codegen_coverage`(PAD版)と同じ設計方針を踏襲する:

**測定方法**: `uipath_codegen`の内部関数を直接呼ばず、公開関数
`generate_python()`だけを使う(内部実装のリファクタに対して測定ロジックが
壊れにくいようにするため)。実際に実機確認済みのXAMLフィクスチャ
(`design/evidence/uipath_xaml_probe/Main.xaml`/`Sub1.xaml`——知見1〜36で
UiPath Studio実機コンパイル確認したもの、でっち上げたテストデータではない)
を`parse_workflow_file()`で読み込み、その木構造を再帰的に歩いて各ノードを
「分岐点」として個別に測定する。コンテナ型ノード(`IfNode`/`SwitchNode`/
`TryCatchNode`/`WhileNode`/`DoWhileNode`/`ParallelNode`/
`ExcelApplicationScopeNode`)は、PAD版と同じ理由(子ノード自身のカバレッジは
別の分岐点として個別に再帰測定済みのため、親の分岐点自身の分類に混ざらない
ようにする)で、子を空にした最小限のコピーに差し替えてから測定する。

`Main.xaml`は`design/uipath_xaml_findings.md`冒頭の既知の注意点
(知見1〜36の構造を1ファイルに網羅的に詰め込んだ調査用フィクスチャで、実際に
動く自動化フローとしての妥当性は意図されていない)を踏襲するため、この
レポートは「実際のユーザーフローでの使用頻度」を測るものではなく、あくまで
「知見で実機確認済みのXAML構造一式に対してコード生成できるか」を測る。
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .uipath_codegen import generate_python
from .uipath_dsl import (
    CatchArm,
    DoWhileNode,
    ExcelApplicationScopeNode,
    ForEachNode,
    IfNode,
    Node,
    ParallelNode,
    SequenceNode,
    SwitchArm,
    SwitchNode,
    TryCatchNode,
    WhileNode,
    WorkflowFile,
    parse_workflow_file,
)

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "design" / "evidence" / "uipath_xaml_probe"
FIXTURE_FILES = ["Main.xaml", "Sub1.xaml"]
# `NewActivity.xaml`(`uipath_xaml_probe_lib`)はLibraryプロジェクト
# (`ActivityBuilder`形、知見26)で`parse_workflow_file()`がv1スコープ外
# として`ValueError`を出す対象のため、このツールの対象外。


@dataclass
class Unit:
    """測定対象の「分岐点」1件の分類結果。"""

    kind: str
    identity: str
    status: str  # "ok" | "todo" | "error"
    detail: str = ""


@dataclass
class Bucket:
    """同じ`(kind, identity)`を持つ`Unit`群の集計。"""

    total: int = 0
    ok: int = 0
    todo: int = 0
    error: int = 0
    sample_detail: str = ""

    def add(self, unit: Unit) -> None:
        self.total += 1
        if unit.status == "ok":
            self.ok += 1
        elif unit.status == "todo":
            self.todo += 1
            if not self.sample_detail:
                self.sample_detail = unit.detail
        else:
            self.error += 1
            if not self.sample_detail:
                self.sample_detail = unit.detail

    @property
    def label(self) -> str:
        if self.ok == self.total:
            return "OK"
        if self.ok == 0:
            return "ERROR" if self.error and not self.todo else "TODO"
        return "PARTIAL"


def _classify(node: Node) -> tuple[str, str]:
    """子を空にした最小限のノード1個を実際に`generate_python()`へ通し、分類する。"""
    wf = WorkflowFile(class_name="Coverage", root=SequenceNode(body=[node]))
    try:
        code = generate_python(wf)
    except (NotImplementedError, ValueError) as exc:
        return "error", f"{type(exc).__name__}: {exc}"
    todo_lines = [line.strip() for line in code.splitlines() if line.strip().startswith("# TODO")]
    if todo_lines:
        return "todo", todo_lines[0]
    return "ok", ""


def _strip_children(node: Node) -> Node:
    """コンテナ型ノードの子を空にし、このノード自身の「形」だけを測定対象に
    する(`codegen_coverage.py`と同じ発想——子の再帰測定と混ざらないように
    する)。リーフノードはそのまま返す。"""
    if isinstance(node, SequenceNode):
        return SequenceNode(variables=node.variables, body=[], display_name=node.display_name)
    if isinstance(node, IfNode):
        return IfNode(condition=node.condition, then_body=[], else_body=[])
    if isinstance(node, ForEachNode):
        return ForEachNode(
            item_var=node.item_var, values=node.values, body=[], type_arguments=node.type_arguments
        )
    if isinstance(node, TryCatchNode):
        return TryCatchNode(
            try_body=[],
            variables=node.variables,
            catches=[
                CatchArm(exception_type=c.exception_type, var_name=c.var_name, body=[])
                for c in node.catches
            ],
            finally_body=[],
        )
    if isinstance(node, SwitchNode):
        return SwitchNode(
            expression=node.expression,
            type_arguments=node.type_arguments,
            arms=[SwitchArm(key=a.key, body=[]) for a in node.arms],
        )
    if isinstance(node, WhileNode):
        return WhileNode(condition=node.condition, body=[])
    if isinstance(node, DoWhileNode):
        return DoWhileNode(condition=node.condition, body=[])
    if isinstance(node, ParallelNode):
        return ParallelNode(branches=[])
    if isinstance(node, ExcelApplicationScopeNode):
        return ExcelApplicationScopeNode(
            workbook_path=node.workbook_path, scope_var=node.scope_var, body=[]
        )
    return node


def _identity(node: Node) -> str:
    """型名をベースに、`uipath_codegen/__init__.py`で実際に分岐が分かれると
    確認済みのケース(選択時/未選択時)だけ variant を付けて区別する——PAD版の
    `identity`ほど細かくVB式の形までは分けない(VB式自体のカバレッジは
    `tests/test_uipath_expr.py`/`test_uipath_codegen.py`が既に別観点で
    網羅的にテスト済みのため、このツールの関心は「アクティビティ単位の
    コード生成」に絞る)。"""
    name = type(node).__name__
    if isinstance(node, SwitchNode):
        if not node.arms:
            return f"{name} (no arms)"
        return f"{name} (with arms)"
    if isinstance(node, DoWhileNode):
        return f"{name} ({'with condition' if node.condition is not None else 'no condition'})"
    if isinstance(node, TryCatchNode):
        return f"{name} ({'with catches' if node.catches else 'no catches'})"
    return name


def iter_units(node: Node) -> Iterator[Unit]:
    stripped = _strip_children(node)
    status, detail = _classify(stripped)
    yield Unit(kind="activity", identity=_identity(node), status=status, detail=detail)
    for child in _children(node):
        yield from iter_units(child)


def _children(node: Node) -> list[Node]:
    if isinstance(node, SequenceNode):
        return list(node.body)
    if isinstance(node, IfNode):
        return [*node.then_body, *node.else_body]
    if isinstance(node, ForEachNode):
        return list(node.body)
    if isinstance(node, TryCatchNode):
        return [
            *node.try_body,
            *[n for c in node.catches for n in c.body],
            *node.finally_body,
        ]
    if isinstance(node, SwitchNode):
        return [n for arm in node.arms for n in arm.body]
    if isinstance(node, WhileNode):
        return list(node.body)
    if isinstance(node, DoWhileNode):
        return list(node.body)
    if isinstance(node, ParallelNode):
        return list(node.branches)
    if isinstance(node, ExcelApplicationScopeNode):
        return list(node.body)
    return []


def collect_report(fixture_paths: list[Path]) -> dict[tuple[str, str], Bucket]:
    buckets: dict[tuple[str, str], Bucket] = defaultdict(Bucket)
    for path in fixture_paths:
        wf = parse_workflow_file(path)
        for unit in iter_units(wf.root):
            buckets[(unit.kind, unit.identity)].add(unit)
    return buckets


def format_report(buckets: dict[tuple[str, str], Bucket]) -> str:
    total = sum(b.total for b in buckets.values())
    total_ok = sum(b.ok for b in buckets.values())
    lines = ["# uipath_codegen カバレッジレポート", ""]
    if total == 0:
        lines.append("対象ユニットが見つかりませんでした。")
        return "\n".join(lines)
    lines.append(f"全体: {total_ok}/{total} 分岐点が実コードを生成 ({total_ok / total:.0%})")
    lines.append("")

    by_kind: dict[str, list[tuple[str, Bucket]]] = defaultdict(list)
    for (kind, identity), bucket in buckets.items():
        by_kind[kind].append((identity, bucket))

    for kind in sorted(by_kind):
        kind_buckets = by_kind[kind]
        kind_ok = sum(b.ok for _, b in kind_buckets)
        kind_total = sum(b.total for _, b in kind_buckets)
        lines.append(f"## {kind} ({kind_ok}/{kind_total})")
        for identity, bucket in sorted(kind_buckets, key=lambda kv: (kv[1].label != "OK", kv[0])):
            line = f"- [{bucket.label}] {identity} ({bucket.ok}/{bucket.total})"
            if bucket.sample_detail and bucket.label != "OK":
                line += f" — {bucket.sample_detail}"
            lines.append(line)
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    fixture_paths = [FIXTURE_DIR / name for name in FIXTURE_FILES]
    buckets = collect_report(fixture_paths)
    print(format_report(buckets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
