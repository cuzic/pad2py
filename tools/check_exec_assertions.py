"""`exec()`で生成コードを実行するテストが、結果を実際に検査しているかを検出する簡易チェッカー。

design/common_rpa_framework_roadmap.md 層4(実行結果検証)の規約:「`exec(code, namespace)`の
後は必ず`namespace[...]`への参照か、フェイクの呼び出しログ(`registry.calls`)・`eval()`に
よる検査が続くこと」をコードレビュー慣習からツールへ格上げする最初の一歩。

知見129・130で実際に踏んだ穴(`exec()`はクラッシュしなければ「検証した」ことにはならない
——出力変数の値自体や呼び出し列を見ていなければ、戻り値の型不一致のようなバグを素通りさせる)
の再発を、人間のコードレビューだけに頼らず機械的に検出する。

**この時点ではCIを止めるハード gate にはしない**(既存テストへの遡及適用は別タスクとして
意図的に切り出している——design/common_rpa_framework_roadmap.md Phase 1参照)。まずは
`uv run python3 tools/check_exec_assertions.py [files...]`で手動実行し、新規に追加した
テストが規約を満たしているかをレビューの補助として使う。

**検出手法(意図的に単純な行ベースのヒューリスティック)**: 各`test_*`関数内で`exec(`
呼び出しを見つけ、その行より後ろの関数内の行に、以下のいずれかの「検査の形跡」があるかを
調べる。
- `exec()`の名前空間引数が単純な変数名(例: `namespace`)の場合: `<その変数名>[`または
  `<その変数名>.get(`の出現。
- それ以外(`{}`のような無名の辞書リテラル、または変数へ代入せず注入する形)の場合:
  `.calls`(フェイクの呼び出しログパターン)または`eval(`の出現。
見つからなければ「検査の形跡が無い」として報告する。AST解析ではなく行ベースのため、
複雑な制御フロー(関数を跨ぐヘルパーでの検査等)は見逃す可能性がある——完璧な静的検査では
なく、レビューの目印として使うことを意図している。

**既知の受容可能な検出漏れ(偽陽性)**: 無期限ポーリングループ(`while ...: time.sleep(...)`)
が実際に即座に(ハングせず)終了することだけを確認するテストは、`namespace[...]`/`.calls`/
`eval(`のいずれも無くても正当である(例: `test_generate_python_converts_wait_for_window_to_
unbounded_poll_when_timeout_is_none`)——「exec()が時間内に返ってきたこと自体」が検証対象
なので、人間のレビューで「このテストは例外として妥当」と判断すればよい。
"""
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    path: Path
    function_name: str
    exec_line: int


def _namespace_arg_token(call: ast.Call) -> str | None:
    """`exec(code, <namespace>)`の`<namespace>`部分から、検査の形跡として探すべき
    トークンを決める。変数名ならその変数名、それ以外(辞書リテラル等)なら`None`
    (呼び出し側で`.calls`/`eval(`を探す)。
    """
    if len(call.args) < 2:
        return None
    namespace_node = call.args[1]
    if isinstance(namespace_node, ast.Name):
        return namespace_node.id
    return None


# `.calls`/`eval(`(フェイクの呼び出しログ・条件式評価)に加え、生成コードが実際に
# ファイルシステムへ書き込む系のテスト(Compression/Cryptography等)で使われる
# 「副作用を直接読み返す」検証パターンも正当な検査の形跡として認める。
_GENERIC_EVIDENCE_TOKENS = (".calls", "eval(", ".read_text(", ".read_bytes(", ".is_file(", ".exists(")


def _has_inspection_evidence(lines: list[str], start_line: int, end_line: int, namespace_token: str | None) -> bool:
    following = "\n".join(lines[start_line:end_line])
    if namespace_token is not None:
        if f"{namespace_token}[" in following or f"{namespace_token}.get(" in following:
            return True
    return any(token in following for token in _GENERIC_EVIDENCE_TOKENS)


def check_file(path: Path) -> list[Finding]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines()
    findings: list[Finding] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
            continue
        function_end = max(
            (getattr(child, "end_lineno", node.lineno) for child in ast.walk(node)),
            default=node.lineno,
        )
        for call in ast.walk(node):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "exec"):
                continue
            namespace_token = _namespace_arg_token(call)
            if not _has_inspection_evidence(lines, call.lineno, function_end, namespace_token):
                findings.append(Finding(path=path, function_name=node.name, exec_line=call.lineno))
    return findings


def main(argv: list[str]) -> int:
    targets = [Path(p) for p in argv] if argv else sorted(Path("tests").glob("test_*.py"))
    all_findings: list[Finding] = []
    for target in targets:
        all_findings.extend(check_file(target))

    for finding in all_findings:
        print(f"{finding.path}:{finding.exec_line}: {finding.function_name}() -- exec()の結果を検査していない可能性")

    if all_findings:
        print(f"\n{len(all_findings)}件(design/common_rpa_framework_roadmap.md 層4参照、レビューの目印)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
