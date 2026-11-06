"""`parse_dsl()` → `build_block_tree()` → `generate_python()` を1コマンドで結ぶCLIエントリポイント。

design/dsl_format_findings.mdの実機検証で育てた
`pad_dsl`/`pad_codegen`coreには、これまで「ユーザーが実際のフローのDSLテキストを
どう渡して、生成Pythonをどう受け取るか」という入出力経路が存在しなかった(`argparse`等を
grepしても何も出てこない状態)。このモジュールはその最小限の橋渡しだけを行う——

入力: PADの「コピー&ペースト」で得られるクリップボードDSLテキスト(ファイル、または
標準入力)。**PADのフロー定義ファイル(.msapp相当)を直接読む機能ではない**——
research_notes/の調査・design/dsl_format_findings.md 知見43の通り、そのような単体
エクスポート機構はPAD自体に存在しないため、現時点ではユーザーがPADデザイナーで
対象アクション群を選択してコピーしたテキストを渡す運用を前提にする。
出力: 生成されたPythonソースコード(ファイル、または標準出力)。

変換不能な構文・アクションは(`pad_dsl`/`pad_codegen`の既存の方針通り)
サイレントに無視せず、`RawRecord`や`# TODO`コメントとしてそのまま出力に残る——このCLIは
その挙動に一切手を加えない、薄いI/Oラッパーに徹する。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .control_repository import decode_screenshot_png, parse_control_repository, parse_image_repository
from .pad_codegen import generate_python
from .pad_dsl import build_block_tree, parse_dsl


def convert(dsl_text: str) -> str:
    """クリップボードDSLテキストをPythonソースへ変換する(ライブラリとしても使える薄い関数)。

    知見44の通り、対象アクションを含む範囲を一括選択してコピーした入力には
    `# [ControlRepository][PowerAutomateDesktop]`セクションが同梱されうる。含まれていれば
    `parse_control_repository()`で解析し、知見56のpywinautoセレクタヒント機能
    (`generate_python()`の`repository`引数)に渡す——単体アクションのコピー等、
    セクションが無い入力では`parse_control_repository()`が空の辞書を返すため、
    従来通りヒント無しの出力になる。同様に`parse_image_repository()`(知見58・206)の
    結果を`image_repository`引数に渡し、`UIAutomation.IfImage.ExistsOnScreen`を
    `images/<表示名>.png`参照のコードへ変換する——実際のPNGファイル書き出しは
    `extract_images()`/`main()`側の責務(`generate_python()`自体は純粋関数のまま)。
    """
    records = parse_dsl(dsl_text)
    tree = build_block_tree(records)
    repository = parse_control_repository(dsl_text)
    image_repository = parse_image_repository(dsl_text)
    return generate_python(tree, repository=repository, image_repository=image_repository)


def extract_images(dsl_text: str) -> dict[str, bytes]:
    """`convert()`が生成するコードが`images/<表示名>.png`として参照する画像の実体を取り出す
    (design/dsl_format_findings.md 知見58・206)。戻り値は`{"<表示名>.png": PNGバイナリ}`
    ——`main()`が出力スクリプトと同じディレクトリの`images/`サブディレクトリへ書き出す。
    """
    return {
        f"{entry.name}.png": decode_screenshot_png(entry)
        for entry in parse_image_repository(dsl_text).values()
    }


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

    # design/dsl_format_findings.md 知見58・206: 出力が実ファイルの場合のみ、生成コードが
    # 参照する画像(`images/<表示名>.png`)を同じディレクトリへ書き出す——標準出力への
    # 出力時はファイルシステム上の置き場所が定まらないため書き出さない。
    if args.output and args.output != "-":
        images = extract_images(dsl_text)
        if images:
            images_dir = Path(args.output).parent / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            for filename, data in images.items():
                (images_dir / filename).write_bytes(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
