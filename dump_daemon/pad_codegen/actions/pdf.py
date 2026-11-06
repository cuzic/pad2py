"""`Pdf.*`のcodegen。

`pad_action_lib.pdf_actions`へ委譲する。5つのaction_id(`Pdf.ExtractTextFromPDF`/
`Pdf.ExtractImagesFromPDF`/`Pdf.ExtractTablesFromPDF`/`Pdf.ExtractPages`/
`Pdf.MergeFiles`)は design/dsl_format_findings.md 知見76〜79で確認済み——ただし
知見75の「貼り付け→レンダリング確認→コピー読み戻し」という通常の実機往復確認とは
異なる特殊ケース。確証の経路は(1)Robin.Core.dll/Robin.Engine.dllから導いたaction_id
構築式、(2)PADデザイナー自身のUI要素のAutomationId、(3)検索+キーボード追加
(`set_focus()`+`{ENTER}`)でPADデザイナー自身が実際にエラー無く受理、という
3つの独立した経路の収束による(知見78で`ExtractTextFromPDF`、知見79で残り4件も
同じ3経路で確認)。パラメータ名は実機UIではなく、各`*Action`クラスの
`InputArgument`/`OutputArgument`属性宣言(ilspycmdによるdecompile)から読み取った値。
RDP接続時に知見75方式のコピー往復確認が取れたら各知見に追記し確証を格上げする。

PAD UI側でデフォルト値のまま変更していないオプション引数(PagesToExtract="All"・
Password=""・DetectLayout=False等)はDSLのパラメータ一覧に現れない(他のTier1/2
アクションのオプション引数と同じ挙動、例: `file.py`の`IfFileExists`無し系・
`compression.py`の`Password`省略時)ため、`pad_action_lib.pdf_actions`の各関数自身の
Python側デフォルト値と一致する literal を`p.get(name, <default>)`で補う。

`Pdf.MergeFiles`の`Passwords`(`EncryptableObject`、`PasswordDelimiter`区切りの
複数パスワードを1つのテキストにまとめる特殊な直列化)は実機でのシリアライズ形式が
未確認のため、指定されている場合は安全側でTODOフォールバックに委ねる(でっち上げた
split処理を生成しない)。`Pdf.ExtractImagesFromPDF`はPAD側に`OutputArgument`が
無い(ファイル書き出しのみ)ため、`node.output_var`の有無を問わず常に文イチ文として
生成する(`file.py`の`File.Delete`と同じ扱い)。

知見155・156(`ActionSelectorBase`一括列挙監査、Excelに続きPDFへも適用): decompileで
`ExtractImagesFromPDFAction`/`ExtractTablesFromPDFAction`/`ExtractTextFromPDFAction`
にはそれぞれ`PagesToExtract`(`ExtractionMode`: All/Single/Range)を固定する3つの
兄弟セレクタ(`Extract*`/`Extract*FromPage`/`Extract*FromPageRange`)が存在し、
DSL上の真のaction_idは`Pdf.<Id属性の値>.<ActionName>`という3セグメント形式だと
判明した(`[Action(Id = "ExtractImagesFromPDF")]`等の明示的な`Id`属性でクラス名の
`...Action`接尾辞が取り除かれる——`Pdf.ExtractPages`/`Pdf.MergeFiles`はこの`Id`属性が
無く`Name`属性のみのため、真の中間セグメントが実機未確認のまま)。従来のフラットな
`Pdf.ExtractImagesFromPDF`等の判定は実際のDSLでは一度もマッチしなかった(知見156で
発見・修正、Excelの知見155と同種の潜在バグ)。`PagesToExtract`はセレクタごとに固定
されるため`enum_last()`で動的に読まず、選択されたセレクタからハードコードする。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import enum_last, safe_render


def _as_list_expr(rendered: str) -> str:
    return f"({rendered} if isinstance({rendered}, list) else [{rendered}])"


def _if_file_exists_arg(p: dict) -> str | None:
    """`IfFileExists`のenum値(省略時は`"AddSequentialSuffix"`)を返す(`!r`適用前の素の文字列)。"""
    if "IfFileExists" in p:
        return enum_last(p.get("IfFileExists"))
    return "AddSequentialSuffix"


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("Pdf."):
        return None
    prefix = INDENT * indent
    p = node.params

    # 知見156: `ExtractionMode`(All/Single/Range)はセレクタごとに固定。
    _PDF_EXTRACT_TEXT_PAGES_MODE = {
        "Pdf.ExtractTextFromPDF.ExtractText": "All",
        "Pdf.ExtractTextFromPDF.ExtractTextFromPage": "Single",
        "Pdf.ExtractTextFromPDF.ExtractTextFromPageRange": "Range",
    }
    pages_to_extract_arg = _PDF_EXTRACT_TEXT_PAGES_MODE.get(action_id)
    if pages_to_extract_arg is not None:
        pdf_file = safe_render(p.get("PDFFile"))
        if pdf_file is None or not node.output_var:
            return None

        page_number = safe_render(p.get("PageNumber", 0))
        from_page_number = safe_render(p.get("FromPageNumber", 0))
        to_page_number = safe_render(p.get("ToPageNumber", 0))
        password = safe_render(p.get("Password", ""))
        detect_layout = safe_render(p.get("DetectLayout", False))
        if None in (page_number, from_page_number, to_page_number, password, detect_layout):
            return None

        return [
            f"{prefix}{node.output_var} = pdf_actions.extract_text_from_pdf("
            f"{pdf_file}, pages_to_extract={pages_to_extract_arg!r}, page_number={page_number}, "
            f"from_page_number={from_page_number}, to_page_number={to_page_number}, "
            f"password={password}, detect_layout={detect_layout})"
        ]

    _PDF_EXTRACT_IMAGES_PAGES_MODE = {
        "Pdf.ExtractImagesFromPDF.ExtractImages": "All",
        "Pdf.ExtractImagesFromPDF.ExtractImagesFromPage": "Single",
        "Pdf.ExtractImagesFromPDF.ExtractImagesFromPageRange": "Range",
    }
    pages_to_extract_arg = _PDF_EXTRACT_IMAGES_PAGES_MODE.get(action_id)
    if pages_to_extract_arg is not None:
        pdf_file = safe_render(p.get("PDFFile"))
        images_folder = safe_render(p.get("ImagesFolder"))
        images_name = safe_render(p.get("ImagesName"))
        if pdf_file is None or images_folder is None or images_name is None:
            return None

        page_number = safe_render(p.get("PageNumber", 0))
        from_page_number = safe_render(p.get("FromPageNumber", 0))
        to_page_number = safe_render(p.get("ToPageNumber", 0))
        password = safe_render(p.get("Password", ""))
        if None in (page_number, from_page_number, to_page_number, password):
            return None

        return [
            f"{prefix}pdf_actions.extract_images_from_pdf({pdf_file}, {images_folder}, {images_name}, "
            f"pages_to_extract={pages_to_extract_arg!r}, page_number={page_number}, "
            f"from_page_number={from_page_number}, to_page_number={to_page_number}, password={password})"
        ]

    _PDF_EXTRACT_TABLES_PAGES_MODE = {
        "Pdf.ExtractTablesFromPDF.ExtractTables": "All",
        "Pdf.ExtractTablesFromPDF.ExtractTablesFromPage": "Single",
        "Pdf.ExtractTablesFromPDF.ExtractTablesFromPageRange": "Range",
    }
    pages_to_extract_arg = _PDF_EXTRACT_TABLES_PAGES_MODE.get(action_id)
    if pages_to_extract_arg is not None:
        pdf_file = safe_render(p.get("PDFFile"))
        if pdf_file is None or not node.output_var:
            return None

        page_number = safe_render(p.get("PageNumber", 0))
        from_page_number = safe_render(p.get("FromPageNumber", 0))
        to_page_number = safe_render(p.get("ToPageNumber", 0))
        password = safe_render(p.get("Password", ""))
        multi_page_tables = safe_render(p.get("MultiPageTables", True))
        set_first_row_as_header = safe_render(p.get("SetFirstRowAsHeader", True))
        if None in (
            page_number,
            from_page_number,
            to_page_number,
            password,
            multi_page_tables,
            set_first_row_as_header,
        ):
            return None

        return [
            f"{prefix}{node.output_var} = pdf_actions.extract_tables_from_pdf("
            f"{pdf_file}, pages_to_extract={pages_to_extract_arg!r}, page_number={page_number}, "
            f"from_page_number={from_page_number}, to_page_number={to_page_number}, "
            f"password={password}, multi_page_tables={multi_page_tables}, "
            f"set_first_row_as_header={set_first_row_as_header})"
        ]

    if action_id == "Pdf.ExtractPages":
        pdf_file = safe_render(p.get("PDFFile"))
        dest = safe_render(p.get("ExtractedPDFPath"))
        page_selection = safe_render(p.get("PageSelection"))
        if pdf_file is None or dest is None or page_selection is None or not node.output_var:
            return None

        password = safe_render(p.get("Password", ""))
        if_exists = _if_file_exists_arg(p)
        if password is None or if_exists is None:
            return None

        return [
            f"{prefix}{node.output_var} = pdf_actions.extract_pages_to_new_pdf("
            f"{pdf_file}, {dest}, {page_selection}, password={password}, "
            f"if_file_exists={if_exists!r})"
        ]

    if action_id == "Pdf.MergeFiles":
        if "Passwords" in p:
            return None
        pdf_files = safe_render(p.get("PDFFiles"))
        dest = safe_render(p.get("MergedPDFPath"))
        if pdf_files is None or dest is None or not node.output_var:
            return None

        if_exists = _if_file_exists_arg(p)
        if if_exists is None:
            return None

        return [
            f"{prefix}{node.output_var} = pdf_actions.merge_pdf_files("
            f"{_as_list_expr(pdf_files)}, {dest}, if_file_exists={if_exists!r})"
        ]

    return None
