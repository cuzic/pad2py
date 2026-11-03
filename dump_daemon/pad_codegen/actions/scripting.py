"""`Scripting.RunPythonScript.*`(Run Python scriptアクション)のcodegen。"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    prefix = INDENT * indent
    if node.action_id.startswith("Scripting.RunPythonScript"):
        code = node.params.get("PythonCode")
        if isinstance(code, str):
            if node.output_var:
                # ScriptOutput(DSL上のScriptOutput=>、既定表示名PythonScriptOutput)は、
                # スクリプトの標準出力を捕捉した値になることが確認できている(正確な書式——
                # 末尾改行・型変換等——は未確認のため、標準出力捕捉を最善の近似として採用する)。
                # さらに重要な点として、スクリプト自身が例外を投げてもそれは呼び出し元に
                # 伝播せず(=ON ERRORで捕捉可能な例外にはならず)、出力変数が空文字列になる
                # だけでフロー自体は正常に続行することも確認できている。これを反映し、
                # スクリプト本体を`try`で包み、例外発生時は出力変数を空文字列にする
                # (でっち上げた例外伝播をせず、確認済みの挙動に合わせる。調査根拠は
                # `docs-local/`配下のリポジトリ非管理メモを参照——ソースコメントには残さない方針)。
                inner_prefix = prefix + INDENT
                lines = [
                    f"{prefix}try:",
                    f"{inner_prefix}with contextlib.redirect_stdout(io.StringIO()) as _pyscript_stdout:",
                ]
                lines.extend(
                    f"{inner_prefix}{INDENT}{line}" if line else "" for line in code.splitlines()
                )
                lines.append(f"{inner_prefix}{node.output_var} = _pyscript_stdout.getvalue()")
                lines.append(f"{prefix}except Exception:")
                lines.append(f"{inner_prefix}{node.output_var} = \"\"")
                return lines
            return [f"{prefix}{line}" if line else "" for line in code.splitlines()]
    return None
