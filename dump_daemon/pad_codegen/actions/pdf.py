"""`Pdf.*`のcodegen。

`pad_action_lib.pdf_actions`へ委譲する。`Pdf.ExtractTextFromPDF`というaction_idは
design/dsl_format_findings.md 知見76〜78で確認済み——ただし知見78に明記した通り、
通常のクリップボード往復(知見75方式)ではなく(1)Robin.Core.dll/Robin.Engine.dllから
導いたaction_id構築式、(2)PADデザイナー自身のUI要素のAutomationId、(3)検索+キーボード
追加(`set_focus()`+`{ENTER}`)でPADデザイナー自身が実際にエラー無く受理、という
3つの独立した経路が収束したことによる確証であり、知見75の「貼り付け→レンダリング
確認→コピー読み戻し」とは異なる特殊ケース。パラメータ名は実機UIではなく、
`ExtractTextFromPDFAction`クラスの`InputArgument`/`OutputArgument`属性宣言
(ilspycmdによる decompile、知見76/77/78)から読み取った値——PDFFile/PagesToExtract/
PageNumber/FromPageNumber/ToPageNumber/Password/DetectLayout/ExtractedText。
RDP接続時に知見75方式のコピー往復確認が取れたら知見78に追記し確証を格上げする。

PAD UI側でデフォルト値のまま変更していないオプション引数(PagesToExtract="All"・
Password=""・DetectLayout=False等)はDSLのパラメータ一覧に現れない(他のTier1/2
アクションのオプション引数と同じ挙動、例: `file.py`の`IfFileExists`無し系・
`compression.py`の`Password`省略時)ため、`pad_action_lib.pdf_actions.
extract_text_from_pdf()`自身のPython側デフォルト値と一致する literal を
`p.get(name, <default>)`で補う。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import enum_last, safe_render


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("Pdf."):
        return None
    prefix = INDENT * indent
    p = node.params

    if action_id == "Pdf.ExtractTextFromPDF":
        pdf_file = safe_render(p.get("PDFFile"))
        if pdf_file is None or not node.output_var:
            return None

        if "PagesToExtract" in p:
            pages_to_extract = enum_last(p.get("PagesToExtract"))
            if pages_to_extract is None:
                return None
            pages_to_extract_arg = repr(pages_to_extract)
        else:
            pages_to_extract_arg = repr("All")

        page_number = safe_render(p.get("PageNumber", 0))
        from_page_number = safe_render(p.get("FromPageNumber", 0))
        to_page_number = safe_render(p.get("ToPageNumber", 0))
        password = safe_render(p.get("Password", ""))
        detect_layout = safe_render(p.get("DetectLayout", False))
        if None in (page_number, from_page_number, to_page_number, password, detect_layout):
            return None

        return [
            f"{prefix}{node.output_var} = pdf_actions.extract_text_from_pdf("
            f"{pdf_file}, pages_to_extract={pages_to_extract_arg}, page_number={page_number}, "
            f"from_page_number={from_page_number}, to_page_number={to_page_number}, "
            f"password={password}, detect_layout={detect_layout})"
        ]

    return None
