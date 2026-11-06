"""design/common_rpa_framework_roadmap.md 層3で構想されていた「セレクタ/モード一括発見
ツールの資産化」の第一版。

使い方:
    uv run python3 -m tools.pad_selector_audit --module Excel \\
        --dump tools/selector_dumps/Excel.txt

`--dump`は`pad2py-audit-<module>-selectors`系のclipwire target(VM上で
`ActionSelectorBase`派生の全型を列挙するPowerShellスクリプト、知見139以降の
`ActionSelectorBase`一括列挙監査の標準手法)の出力を保存したテキストファイル——
`<BaseClass> | <SelectorClassName> | ActionName=<Name>`形式の行の並び。

知見155-158で発見したExcel/PDF/Word/PowerPointの潜在バグ(`pad_codegen`側の
action_id判定がフラットな2セグメント形式のままで、実際のDSLは3セグメント形式
(`<Module>.<BaseClass>.<ActionName>`)だったため一度も実際のDSLでマッチしなかった)
を、今後の新規モジュール調査で未然に防ぐためのツール。

`pad_codegen/actions/<module>.py`をASTで静的解析し、ソースコード中の
`"<Module>.<X>"`または`"<Module>.<X>.<Y>"`という形のdotted文字列リテラルを全て
抽出して「結線済みaction_id集合」とみなす(文字列の形だけで判定するため、辞書リテラル
のキー/値どちらでも、素の`action_id == "..."`比較でも検出できる——どのif分岐の中にある
かという制御フローの解析は行わない、意図的に単純な実装)。

`--id-override BaseClassName=MiddleSegment`で、`[Action(Id = ...)]`属性による
クラス名からの上書き(知見156のPDFの`ExtractImagesFromPDFAction`→`ExtractImagesFromPDF`
等、クラス名の`...Action`接尾辞を取り除く上書き)を指定できる——この上書きの有無自体は
decompileで直接確認する必要があり、本ツールが推測することはない(でっち上げない)。

出力は「未結線候補」の一覧であり、エラーではない——ライブCOM専用機能など意図的に
スコープ外とした既知の除外もここに含まれるため、最終判断は呼び出し側(人間、または
`pad_todo.md`への反映作業)に委ねる。
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

#: `<Module>.<X>`または`<Module>.<X>.<Y>`の形(大文字始まりのドット区切り識別子、
#: 2〜3セグメント)に一致する文字列リテラルをaction_idとみなす。
_ACTION_ID_LITERAL_RE = re.compile(r"^[A-Z][A-Za-z0-9]*(\.[A-Za-z][A-Za-z0-9]*){1,2}$")


def extract_wired_action_ids(py_file: Path) -> set[str]:
    """`py_file`中の全ての文字列リテラルから、action_idの形をしたものを抜き出す。"""
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _ACTION_ID_LITERAL_RE.match(node.value):
                found.add(node.value)
    return found


def parse_selector_dump(dump_file: Path) -> list[tuple[str, str, str]]:
    """`<BaseClass> | <SelectorClassName> | ActionName=<Name>`形式の行を解析する。"""
    entries: list[tuple[str, str, str]] = []
    for line in dump_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or "ActionName=" not in line or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3:
            continue
        base_class, selector_class, action_name_part = parts
        if "ActionName=" not in action_name_part:
            continue
        action_name = action_name_part.split("ActionName=", 1)[1]
        entries.append((base_class, selector_class, action_name))
    return entries


def audit(
    module: str,
    actions_py: Path,
    dump_file: Path,
    id_overrides: dict[str, str] | None = None,
) -> list[str]:
    """`dump_file`中の各セレクタについて、`<module>.<middle>.<ActionName>`が
    `actions_py`に結線されているかを確認し、結線されていないものを返す。
    """
    id_overrides = id_overrides or {}
    wired = extract_wired_action_ids(actions_py)
    missing: list[str] = []
    for base_class, _selector_class, action_name in parse_selector_dump(dump_file):
        middle = id_overrides.get(base_class, base_class)
        candidate = f"{module}.{middle}.{action_name}"
        if candidate not in wired:
            missing.append(candidate)
    return missing


def _default_actions_py(module: str) -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "dump_daemon"
        / "pad_codegen"
        / "actions"
        / f"{module.lower()}.py"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", required=True, help="DSLのモジュール接頭辞(例: Excel)")
    parser.add_argument(
        "--actions-py",
        type=Path,
        default=None,
        help="対象のpad_codegen/actions/*.py (省略時は--moduleの小文字から推測)",
    )
    parser.add_argument("--dump", type=Path, required=True, help="VMリフレクション出力ファイル")
    parser.add_argument(
        "--id-override",
        action="append",
        default=[],
        metavar="BaseClassName=MiddleSegment",
        help="[Action(Id=...)]によるクラス名からの上書き(複数指定可)",
    )
    args = parser.parse_args(argv)

    actions_py = args.actions_py or _default_actions_py(args.module)
    overrides = dict(pair.split("=", 1) for pair in args.id_override)

    missing = audit(args.module, actions_py, args.dump, overrides)
    if missing:
        print(f"[{args.module}] 未結線候補 {len(missing)}件(スコープ外の既知の意図的除外を含む可能性あり):")
        for m in sorted(missing):
            print(f"  - {m}")
    else:
        print(f"[{args.module}] dump内の全セレクタが結線済みのaction_idと一致しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
