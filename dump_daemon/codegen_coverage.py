"""`pad_codegen`がどこまで実コードを生成できているかを実測するカバレッジ測定ツール。

design/dsl_format_findings.md 知見50以降、パーサー(`pad_dsl`core)側は`[WaitAction]`/
`[ConditionAction]`カテゴリ等の構文を正しく構造化できるようになった。`pad_codegen`側は
知見62〜74のTier1/2実機キャプチャと知見73の`pad_action_lib`結線を経て大半の`action`分岐点が
実コード生成に対応し(`WaitActionRecord`も`actions/wait.py`で全件対応済み)、現時点の主な
TODO/`NotImplementedError`は「でっち上げを避けるための正直な未対応」(DPAPI暗号化・
DataTableスキーマ未確認・外部NLPライブラリ未導入等、design/pad_todo.md A節参照)に絞られている。
この到達度を目視の印象ではなく実測するために、`tests/fixtures/`の実機キャプチャ全件を実際に
変換し、各「分岐点」(アクションID・キーワード種別・条件式の形など)ごとに「実コードを生成
できたか」「`# TODO`に倒れたか」「`NotImplementedError`/`ValueError`で明示的に拒否されたか」
を集計する。

**測定方法**: `pad_codegen`の内部関数を直接呼ばず、公開関数`generate_python()`だけを
使う(内部実装のリファクタに対して測定ロジックが壊れにくいようにするため)。木構造の
各「分岐点」(`ActionRecord`/`WaitActionRecord`/`KeywordRecord`/`SetVariableRecord`、
`ConditionalNode`の各アーム見出し、`SwitchNode`の各アーム見出し、`BlockNode`の見出し、
`GuardedNode`の保護ラッパー自体)を、本体を空にした最小限のノード列として個別に
`generate_python()`に渡し、出力に`# TODO`行が含まれるか・例外が飛ぶかを見て分類する。
本体を空にするのは、入れ子になった子ノード自身のカバレッジ(別の分岐点として個別に
再帰で測定済み)が、親の分岐点自身の分類に混ざらないようにするため。

**既知の限界(2026-11-05確認)**: `action`バケットの一部(`Variables.IncreaseVariable`/
`DecreaseVariable`/`Compression.UnzipFiles`)は、実機キャプチャフィクスチャがたまたま
`Value`にプレースホルダーの文字列リテラル(`VarRef`ではない)を使っていたり出力変数の
`=>`束縛を欠いていたりするため`TODO`に分類される——codegen自体は`tests/test_pad_codegen.py`
の専用テストで正しく実コードを生成することを確認済み。この測定方法(個々のフィクスチャの
実際のパラメータ値で測る)自体の意図的なトレードオフであり、design/pad_todo.md A節参照。
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .control_repository import parse_control_repository
from .control_repository.types import ControlRepositoryEntry
from .pad_codegen import generate_python
from .pad_dsl import (
    ActionRecord,
    BlockNode,
    CaseDefaultRecord,
    CommentRecord,
    ConditionalNode,
    ElseIfActionRecord,
    ElseIfFunctionRecord,
    ElseIfRecord,
    GuardedNode,
    IfActionRecord,
    IfFunctionRecord,
    IfRecord,
    KeywordRecord,
    Node,
    OnErrorNode,
    RawExpr,
    RawRecord,
    SetVariableRecord,
    SwitchNode,
    WaitActionRecord,
    build_block_tree,
    parse_dsl,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# `_leaf_unit()`でKeywordRecordの識別名を組み立てる際、第1引数がこの集合に含まれる場合のみ
# `"EXIT LOOP"`のように2語で束ねる(`pad_codegen`の`_generate_keyword()`がこの2語の
# 組み合わせでしか分岐しないため)。`LABEL`/`GOTO`のように引数が可変(ラベル名そのもの)な
# キーワードは束ねず、名前だけでグルーピングする(でなければラベル名ごとに別バケツに
# なってしまい集計が無意味に細分化される)。
_KEYWORD_ARG_SUFFIXES = {"LOOP", "ACTION"}

Repository = dict[str, dict[str, ControlRepositoryEntry]]


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


def _classify(nodes: list[Node], repository: Repository) -> tuple[str, str]:
    """最小限のノード列を実際に`generate_python()`へ通し、分類する。"""
    try:
        code = generate_python(nodes, repository=repository)
    except (NotImplementedError, ValueError) as exc:
        return "error", f"{type(exc).__name__}: {exc}"
    todo_lines = [line.strip() for line in code.splitlines() if line.strip().startswith("# TODO")]
    if todo_lines:
        return "todo", todo_lines[0]
    return "ok", ""


def _leaf_unit(node: Node, repository: Repository) -> Unit | None:
    if isinstance(node, ActionRecord):
        kind, identity = "action", node.action_id
    elif isinstance(node, WaitActionRecord):
        kind, identity = "wait_action", node.action_id
    elif isinstance(node, KeywordRecord):
        kind = "keyword"
        if node.args and node.args[0] in _KEYWORD_ARG_SUFFIXES:
            identity = f"{node.name} {node.args[0]}"
        else:
            identity = node.name
    elif isinstance(node, SetVariableRecord):
        kind = "set_variable"
        identity = "compound expression (AND/OR/+-*/mod)" if isinstance(node.value, RawExpr) else "simple value"
    elif isinstance(node, RawRecord):
        # パーサー自体が構造化できなかった行(codegenの不備ではなくパーサーの不備)。
        # 参考情報として残すが、他のkindとは別枠で報告する。
        kind, identity = "unparsed_line (parser gap, not codegen)", node.text[:60]
    elif isinstance(node, CommentRecord):
        return None  # 単純な`#`コメント透過は測定対象外(常にOKで自明)。
    else:
        raise TypeError(f"Unsupported leaf node for coverage measurement: {type(node)!r}")
    status, detail = _classify([node], repository)
    return Unit(kind=kind, identity=identity, status=status, detail=detail)


def _conditional_arm_unit(header, repository: Repository) -> Unit:
    if isinstance(header, (IfRecord, ElseIfRecord)):
        kind, identity = "condition", f"comparison operator {header.operator!r}"
    elif isinstance(header, KeywordRecord):  # ELSE
        kind, identity = "condition", "ELSE"
    elif isinstance(header, (IfFunctionRecord, ElseIfFunctionRecord)):
        kind, identity = "condition_function_call", header.function_name
    elif isinstance(header, (IfActionRecord, ElseIfActionRecord)):
        kind, identity = "condition_action_call", header.action_id
    else:
        raise TypeError(f"Unsupported conditional arm header: {header!r}")
    status, detail = _classify([ConditionalNode(arms=[(header, [])])], repository)
    return Unit(kind=kind, identity=identity, status=status, detail=detail)


def _switch_arm_unit(expression, header, repository: Repository) -> Unit:
    if isinstance(header, CaseDefaultRecord):
        identity = "DEFAULT"
    else:
        identity = f"CASE operator {header.operator!r}"
    status, detail = _classify([SwitchNode(expression=expression, arms=[(header, [])])], repository)
    return Unit(kind="switch_arm", identity=identity, status=status, detail=detail)


def _block_header_unit(header, repository: Repository) -> Unit:
    status, detail = _classify([BlockNode(header=header, body=[])], repository)
    return Unit(kind="block_header", identity=type(header).__name__, status=status, detail=detail)


def _guarded_unit(node: GuardedNode, repository: Repository) -> Unit:
    # 保護対象の中身(本物の`node.node`)は別の分岐点として個別に再帰測定するため、ここでは
    # 「ON ERROR/ON BLOCK ERRORラッパー自身がtry/exceptへ変換されるか」だけを、保護対象を
    # 無害なプレースホルダ(常にOKな`WAIT 0`)に差し替えて測定する。各アームの本体も空にする
    # (本体の中身のカバレッジはそれぞれ別の分岐点として既に測定されるため、ここに混ぜない)。
    empty_arms = [(arm_header, []) for arm_header, _ in node.on_error.arms]
    placeholder = GuardedNode(
        node=KeywordRecord(name="WAIT", args=["0"]),
        on_error=OnErrorNode(arms=empty_arms),
    )
    single_unnamed = len(node.on_error.arms) == 1 and node.on_error.arms[0][0].case_name is None
    identity = "single unnamed catch-all arm" if single_unnamed else "named and/or multiple arms"
    status, detail = _classify([placeholder], repository)
    return Unit(kind="error_handling", identity=identity, status=status, detail=detail)


def iter_units(nodes: list[Node], repository: Repository) -> Iterator[Unit]:
    for node in nodes:
        yield from _walk(node, repository)


def _walk(node: Node, repository: Repository) -> Iterator[Unit]:
    if isinstance(node, ConditionalNode):
        for header, body in node.arms:
            yield _conditional_arm_unit(header, repository)
            yield from iter_units(body, repository)
    elif isinstance(node, SwitchNode):
        for header, body in node.arms:
            yield _switch_arm_unit(node.expression, header, repository)
            yield from iter_units(body, repository)
    elif isinstance(node, BlockNode):
        yield _block_header_unit(node.header, repository)
        yield from iter_units(node.body, repository)
    elif isinstance(node, GuardedNode):
        yield _guarded_unit(node, repository)
        yield from _walk(node.node, repository)
    else:
        unit = _leaf_unit(node, repository)
        if unit is not None:
            yield unit


def collect_report(fixture_paths: list[Path]) -> dict[tuple[str, str], Bucket]:
    buckets: dict[tuple[str, str], Bucket] = defaultdict(Bucket)
    for path in fixture_paths:
        text = path.read_text(encoding="utf-8")
        records = parse_dsl(text)
        tree = build_block_tree(records)
        repository = parse_control_repository(text)
        for unit in iter_units(tree, repository):
            buckets[(unit.kind, unit.identity)].add(unit)
    return buckets


def format_report(buckets: dict[tuple[str, str], Bucket]) -> str:
    total = sum(b.total for b in buckets.values())
    total_ok = sum(b.ok for b in buckets.values())
    lines = ["# pad_codegen カバレッジレポート", ""]
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
    fixture_paths = sorted(FIXTURES_DIR.glob("*.txt"))
    buckets = collect_report(fixture_paths)
    print(format_report(buckets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
