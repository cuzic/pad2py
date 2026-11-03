"""`parse_dsl()` → `build_block_tree()` → `generate_python()` を1コマンドで結ぶCLIエントリポイント。

design/dsl_format_findings.md・robin_language_source_findings.mdの実機検証で育てた
`pad_dsl_parser.py`/`pad_codegen.py`には、これまで「ユーザーが実際のフローのDSLテキストを
どう渡して、生成Pythonをどう受け取るか」という入出力経路が存在しなかった(`argparse`等を
grepしても何も出てこない状態)。このモジュールはその最小限の橋渡しだけを行う——

入力: PADの「コピー&ペースト」で得られるクリップボードDSLテキスト(ファイル、または
標準入力)。**PADのフロー定義ファイル(.msapp相当)を直接読む機能ではない**——
research_notes/の調査・design/dsl_format_findings.md 知見43の通り、そのような単体
エクスポート機構はPAD自体に存在しないため、現時点ではユーザーがPADデザイナーで
対象アクション群を選択してコピーしたテキストを渡す運用を前提にする。
出力: 生成されたPythonソースコード(ファイル、または標準出力)。

変換不能な構文・アクションは(`pad_dsl_parser.py`/`pad_codegen.py`の既存の方針通り)
サイレントに無視せず、`RawRecord`や`# TODO`コメントとしてそのまま出力に残る——このCLIは
その挙動に一切手を加えない、薄いI/Oラッパーに徹する。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pad_codegen import generate_python
from .pad_dsl_parser import build_block_tree, parse_dsl


def convert(dsl_text: str) -> str:
    """クリップボードDSLテキストをPythonソースへ変換する(ライブラリとしても使える薄い関数)。"""
    records = parse_dsl(dsl_text)
    tree = build_block_tree(records)
    return generate_python(tree)


def _read_input(path: str | None) -> str:
    if path is None or path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _write_output(path: str | None, code: str) -> None:
    if path is None or path == "-":
        sys.stdout.write(code)
        return
    Path(path).write_text(code, encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pad2py",
        description=(
            "Power Automate Desktop の「コピー&ペースト」クリップボードDSLテキストを "
            "pywinauto/pyautogui ベースのPythonソースへ変換する。"
        ),
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="入力DSLテキストファイルのパス。省略または '-' で標準入力から読む。",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="出力Pythonファイルのパス。省略または '-' で標準出力へ書く。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    dsl_text = _read_input(args.input)
    if not dsl_text.strip():
        print("pad2py: 入力が空です(DSLテキストが渡されませんでした)", file=sys.stderr)
        return 1

    code = convert(dsl_text)
    _write_output(args.output, code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
