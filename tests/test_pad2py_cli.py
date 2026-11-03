"""pad2py_cli の単体テスト・結合テスト。

design/dsl_format_findings.md 知見43を踏まえて作った、`parse_dsl()`→
`build_block_tree()`→`generate_python()`を1コマンドで結ぶCLIエントリポイント
(`dump_daemon/pad2py_cli.py`)の入出力経路を検証する。パーサー/codegen自体は
`test_pad_dsl_parser.py`/`test_pad_codegen.py`で検証済みのため、ここではCLI固有の
I/O配線(ファイル/標準入出力の切り替え、空入力のエラーハンドリング、
`pad2py`コンソールスクリプトとしての疎通)だけを対象にする。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from dump_daemon.pad2py_cli import build_arg_parser, convert, main

FIXTURES_DIR = Path(__file__).parent / "fixtures"

SIMPLE_DSL = "SET TestVar TO $'''hello'''"


def test_convert_runs_full_pipeline() -> None:
    code = convert(SIMPLE_DSL)
    assert code.strip() == "TestVar = 'hello'"


def test_main_reads_stdin_and_writes_stdout(capsys, monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", _FakeStdin(SIMPLE_DSL))
    exit_code = main([])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert out.strip() == "TestVar = 'hello'"


def test_main_reads_input_file_and_writes_output_file(tmp_path) -> None:
    input_path = tmp_path / "in.txt"
    output_path = tmp_path / "out.py"
    input_path.write_text(SIMPLE_DSL, encoding="utf-8")

    exit_code = main([str(input_path), "-o", str(output_path)])

    assert exit_code == 0
    assert output_path.read_text(encoding="utf-8").strip() == "TestVar = 'hello'"


def test_main_dash_means_stdin_and_stdout(capsys, monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", _FakeStdin(SIMPLE_DSL))
    exit_code = main(["-", "-o", "-"])
    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "TestVar = 'hello'"


def test_main_reports_empty_input_as_error_without_crashing(capsys, monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", _FakeStdin("   \n"))
    exit_code = main([])
    assert exit_code == 1
    assert "入力が空です" in capsys.readouterr().err


def test_arg_parser_accepts_input_and_output_options() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(["in.txt", "-o", "out.py"])
    assert args.input == "in.txt"
    assert args.output == "out.py"


def test_console_script_end_to_end_via_subprocess() -> None:
    # design/dsl_format_findings.md 知見40の`BLOCK`/`ON BLOCK ERROR`・知見38の
    # `appmask[...]`UI要素参照を含む、実機キャプチャ由来の複合的なDSLで、
    # サブプロセス経由の実際のコマンド呼び出し(`python -m dump_daemon.pad2py_cli`)が
    # 最初から最後まで通ることを確認する——importパスの配線ミス等はこの形でしか
    # 検出できないため、ユニットテストとは別に意図的にsubprocessで実行する。
    dsl = (
        "SET TestVar TO $'''hello'''\n"
        "BLOCK \n"
        "ON BLOCK ERROR\n"
        "NEXT ACTION\n"
        "END\n"
        "UIAutomation.Click.Click Element: appmask['Start Button'] "
        "ClickType: UIAutomation.ClickType.LeftClick "
        "MousePositionRelativeToElement: UIAutomation.RectangleEdgePoint.MiddleCenter "
        "OffsetX: 0 OffsetY: 0"
    )
    result = subprocess.run(
        [sys.executable, "-m", "dump_daemon.pad2py_cli"],
        input=dsl,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "TestVar = 'hello'" in result.stdout
    assert "try:" in result.stdout
    assert "UI element: 'Start Button'" in result.stdout
    compile(result.stdout, "<generated>", "exec")


def test_cli_handles_real_whole_subflow_capture_with_control_repository_section(tmp_path) -> None:
    # design/dsl_format_findings.md 知見44: サブフロー全体を一括選択してコピーすると
    # UI要素リポジトリのJSONが末尾に同梱される(個別の1〜4アクションコピーとは違う形)。
    # CLIにそのまま渡しても、JSON部分がノイズとして出力に混ざらず、クラッシュせず
    # compileできるPythonを生成することを確認する——「本物のwhole-flow copyをCLIに
    # 渡す」という、これまで一度もテストされていなかった経路そのもの。
    fixture = FIXTURES_DIR / "looptest_whole_subflow_with_control_repository.txt"
    output_path = tmp_path / "out.py"

    exit_code = main([str(fixture), "-o", str(output_path)])

    assert exit_code == 0
    code = output_path.read_text(encoding="utf-8")
    assert "ControlRepositorySymbols" not in code
    assert "appmask" not in code
    compile(code, "<generated>", "exec")


class _FakeStdin:
    """`monkeypatch.setattr(sys, "stdin", ...)`用の最小限のread()だけ持つスタブ。"""

    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text
