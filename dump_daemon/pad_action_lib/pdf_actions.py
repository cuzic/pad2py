"""`PDF.Actions`(テキスト/画像/テーブル抽出、ページ抽出、PDF結合)のロジック層。

PADの実装は`System.IO.Compression`のような他モジュールと違い、生の`PDFium`(Googleの
自己完結型PDFレンダリング/解析ライブラリ)をP/Invokeで直接叩く——Acrobat等のライブ
アプリには依存しない。そのためExcel/Word/PowerPointほどの「ライブアプリ依存」という
制約は無く、この層では`pypdf`(ページ操作・画像抽出)と`pdfplumber`(テキスト位置・
テーブル抽出)で全アクションの再現を試みる。

ただし2つの処理は**PDFiumの出力と一致しない**(別アルゴリズムの近似であり、ポートでは
ない)ことを明示する:
- テーブル抽出: PADは`Microsoft.ProgramSynthesis.Extraction.Pdf`という非公開の
  Microsoft内製テーブル検出エンジンを使っている(ソースはこのDLLに含まれず、
  アルゴリズムの詳細は確認不能)。この層は`pdfplumber`の罫線ベースのテーブル検出
  (全く別のアルゴリズム)を使うため、検出されるテーブルの境界・ページ跨ぎ結合
  (`MultiPageTables`)は再現されない——各ページ独立にしか検出しない。
- `DetectLayout`付きテキスト抽出: PADの単語クラスタリング+余白計算アルゴリズム自体は
  `PdfTextLayoutUtilities.GetTextWithLayoutFromPage`から移植した(忠実に再現)が、
  その入力となる「単語」の切り出し自体がPDFium(文字単位空白判定)と`pdfplumber`
  (独自の単語トークナイザ)で異なるため、出力テキストは一致しない近似に留まる。

ページ番号は全アクションで1始まり。
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
from pypdf import PasswordType, PdfReader, PdfWriter

from .datatable import DataTable, datatable_from_rows
from .errors import PadActionError

_OS_FILE_NOT_FOUND_ERROR = FileNotFoundError


class PDFFileDoesNotExistError(PadActionError):
    pass


class InvalidPasswordError(PadActionError):
    pass


class FailedToExtractTextError(PadActionError):
    pass


class FailedToExtractImagesError(PadActionError):
    pass


class FolderDoesNotExistError(PadActionError):
    pass


class FailedToExtractTablesError(PadActionError):
    pass


class PageOutOfBoundsError(PadActionError):
    pass


class InvalidPageSelectionError(PadActionError):
    pass


class FailedToExtractNewPDFFileError(PadActionError):
    pass


class FailedToMergePDFFilesError(PadActionError):
    pass


def _require_pdf_file(path: str) -> Path:
    p = Path(path)
    if not p.is_file():
        raise PDFFileDoesNotExistError(f"File '{path}' doesn't exist")
    return p


def _open_decrypted(path: Path, password: str | None) -> PdfReader:
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        result = reader.decrypt(password or "")
        if result == PasswordType.NOT_DECRYPTED:
            raise InvalidPasswordError(f"invalid or missing password for '{path}'")
    return reader


def _validate_page_range(
    pages_to_extract: str, page_number: int, from_page_number: int, to_page_number: int
) -> None:
    # ValidatePageRangeは素の`ArgumentException`を投げる([Throws]タグに正規化されない)。
    if pages_to_extract == "Single" and page_number <= 0:
        raise ValueError("Single page number should be greater than zero (0)")
    if pages_to_extract == "Range" and from_page_number <= 0:
        raise ValueError("From page number should be greater than zero (0)")
    if pages_to_extract == "Range" and to_page_number <= 0:
        raise ValueError("To page number should be greater than zero (0)")
    if pages_to_extract == "Range" and from_page_number > to_page_number:
        raise ValueError(
            f"Invalid page selection '{from_page_number}-{to_page_number}'. "
            "The first number must be smaller than the second into a range of pages"
        )


def _valid_page_index_range(
    pages_to_extract: str, page_number: int, from_page_number: int, to_page_number: int, last_page_index: int
) -> tuple[int, int]:
    if pages_to_extract == "All":
        start, end = 0, last_page_index
    elif pages_to_extract == "Single":
        start = end = page_number - 1
    elif pages_to_extract == "Range":
        start, end = from_page_number - 1, to_page_number - 1
    else:
        raise ValueError(f"Unknown ExtractionMode: {pages_to_extract!r}")
    # 範囲外のFrom/Toは明示的なエラーにならず、黙って最終ページにクランプされる
    # (ExtractPagesToNewPDFとは非対称——あちらは範囲外をPageOutOfBoundsErrorにする)。
    return min(start, last_page_index), min(end, last_page_index)


def extract_text_from_pdf(
    pdf_file: str,
    pages_to_extract: str = "All",
    page_number: int = 0,
    from_page_number: int = 0,
    to_page_number: int = 0,
    password: str | None = None,
    detect_layout: bool = False,
) -> str:
    _validate_page_range(pages_to_extract, page_number, from_page_number, to_page_number)
    path = _require_pdf_file(pdf_file)
    try:
        reader = _open_decrypted(path, password)
        last_page_index = len(reader.pages) - 1
        start, end = _valid_page_index_range(
            pages_to_extract, page_number, from_page_number, to_page_number, last_page_index
        )
        if detect_layout:
            with pdfplumber.open(str(path), password=password or None) as pdf:
                parts = [
                    _text_with_layout_from_page(pdf.pages[i]) for i in range(start, end + 1)
                ]
        else:
            parts = [reader.pages[i].extract_text() or "" for i in range(start, end + 1)]
        return "".join(parts)
    except InvalidPasswordError:
        raise
    except Exception as exc:
        raise FailedToExtractTextError(f"Failed to extract text from '{pdf_file}'") from exc


_MARGIN_FACTOR = 0.4


def _box_center(box: dict) -> float:
    return box["bottom"] + (box["top"] - box["bottom"]) / 2.0


def _text_with_layout_from_page(page: "pdfplumber.page.Page") -> str:
    """`PdfTextLayoutUtilities.GetTextWithLayoutFromPage`の移植。

    pdfplumberは画像座標系(原点が左上、Yが下に向かって増える)を使うが、元の
    アルゴリズムはPDF座標系(原点が左下、Yが上に向かって増える、`Top > Bottom`)を
    前提にしているため、ページ高さを使って縦方向を反転してから適用する
    (`flipped = height - image_coord`、差分を取る計算なので高さ自体は変わらない)。
    """
    words = page.extract_words()
    if not words:
        return ""
    height = page.height
    boxes = [
        {
            "text": w["text"],
            "left": w["x0"],
            "right": w["x1"],
            "top": height - w["top"],
            "bottom": height - w["bottom"],
        }
        for w in words
    ]
    # OrderByDescending(Bottom): PDF座標系(Y上向き)でBottomが大きい=物理的にページ上部
    # =読み順で先に来る単語を先頭にする。
    boxes.sort(key=lambda b: b["bottom"], reverse=True)
    avg_height = sum(b["top"] - b["bottom"] for b in boxes) / len(boxes)
    avg_char_width = sum((b["right"] - b["left"]) / len(b["text"]) for b in boxes) / len(boxes)
    margin = avg_height * _MARGIN_FACTOR

    lines: list[list[dict]] = []
    flag = True  # True: 次の単語で新しい行を開始する
    current_line: list[dict] = []
    running_center = -1.0
    n = len(boxes)
    for i in range(n):
        if flag:
            current_line = [boxes[i]]
            running_center = _box_center(boxes[i])
        else:
            current_line.append(boxes[i])

        if i == n - 1:
            lines.append(sorted(current_line, key=lambda b: b["left"]))
            continue

        next_center = _box_center(boxes[i + 1])
        if abs(running_center - next_center) > margin:
            lines.append(sorted(current_line, key=lambda b: b["left"]))
            if not flag:
                flag = True
        else:
            if flag:
                flag = False
            running_center = (running_center + next_center) / 2.0

    out = io.StringIO()
    for line in lines:
        prev = {"left": 0.0, "right": 0.0}  # 行頭は「空のボックス」との間隔=単語自体の左端位置
        for box in line:
            out.write(" " * _spaces_between(prev, box, avg_char_width))
            out.write(box["text"])
            prev = box
        out.write("\n")
    return out.getvalue()


def _spaces_between(prev: dict, current: dict, avg_char_width: float) -> int:
    gap = (current["left"] - prev["right"]) if prev["right"] < current["left"] else 0.0
    count = int(round(gap / avg_char_width, 2))
    return count if count != 0 else 1


def extract_images_from_pdf(
    pdf_file: str,
    images_folder: str,
    images_name: str,
    pages_to_extract: str = "All",
    page_number: int = 0,
    from_page_number: int = 0,
    to_page_number: int = 0,
    password: str | None = None,
) -> list[str]:
    _validate_page_range(pages_to_extract, page_number, from_page_number, to_page_number)
    path = _require_pdf_file(pdf_file)
    folder = Path(images_folder)
    if not folder.is_dir():
        raise FolderDoesNotExistError(f"Folder '{images_folder}' doesn't exist")
    try:
        reader = _open_decrypted(path, password)
        last_page_index = len(reader.pages) - 1
        start, end = _valid_page_index_range(
            pages_to_extract, page_number, from_page_number, to_page_number, last_page_index
        )
        written: list[str] = []
        counter = 0
        for i in range(start, end + 1):
            for image in reader.pages[i].images:
                dest = folder / f"{images_name}_{counter}.png"
                image.image.save(dest, format="PNG")  # 常にPNGとして保存(PDFium実装と同じ)
                written.append(str(dest))
                counter += 1
        return written
    except InvalidPasswordError:
        raise
    except Exception as exc:
        raise FailedToExtractImagesError(f"Failed to extract images from '{pdf_file}'") from exc


@dataclass(frozen=True)
class PDFTableInfo:
    name: str
    table_starting_page: int
    table_ending_page: int
    table_order_in_page: int
    data_table: DataTable = field(default_factory=list)


def _build_table_datatable(rows: list[list[str | None]], set_first_row_as_header: bool) -> DataTable:
    if not rows:
        return []
    num_columns = len(rows[0])
    if set_first_row_as_header and num_columns > 1:
        used: set[str] = set()
        columns: list[str] = []
        for i, raw in enumerate(rows[0]):
            name = raw if raw else f"Column{i + 1}"
            if name in used:
                name = f"Column{i + 1}"
            used.add(name)
            columns.append(name)
        return datatable_from_rows(columns, [list(r) for r in rows[1:]])
    columns = [f"Column{i + 1}" for i in range(num_columns)]
    return datatable_from_rows(columns, [list(r) for r in rows])


def extract_tables_from_pdf(
    pdf_file: str,
    pages_to_extract: str = "All",
    page_number: int = 0,
    from_page_number: int = 0,
    to_page_number: int = 0,
    password: str | None = None,
    multi_page_tables: bool = True,
    set_first_row_as_header: bool = True,
) -> list[PDFTableInfo]:
    del multi_page_tables  # pdfplumberはページ単位でしか検出できず、ページ跨ぎ結合は未実装
    _validate_page_range(pages_to_extract, page_number, from_page_number, to_page_number)
    path = _require_pdf_file(pdf_file)
    try:
        with pdfplumber.open(str(path), password=password or None) as pdf:
            last_page_index = len(pdf.pages) - 1
            start, end = _valid_page_index_range(
                pages_to_extract, page_number, from_page_number, to_page_number, last_page_index
            )
            results: list[PDFTableInfo] = []
            for page_index in range(start, end + 1):
                page_number_1based = page_index + 1
                tables = pdf.pages[page_index].extract_tables()
                for order, raw_table in enumerate(tables, start=1):
                    data_table = _build_table_datatable(raw_table, set_first_row_as_header)
                    num_rows = len(data_table)
                    num_cols = len(data_table[0]) if data_table else len(raw_table[0]) if raw_table else 0
                    name = (
                        f"PDF table #{order} in page {page_number_1based} "
                        f"with {num_rows} rows and {num_cols} columns"
                    )
                    results.append(
                        PDFTableInfo(
                            name=name,
                            table_starting_page=page_number_1based,
                            table_ending_page=page_number_1based,
                            table_order_in_page=order,
                            data_table=data_table,
                        )
                    )
            return results
    except Exception as exc:
        raise FailedToExtractTablesError(f"Failed to extract tables from '{pdf_file}'") from exc


def _parse_page_selection(page_selection: str) -> list[int]:
    pages: list[int] = []
    for segment in page_selection.split(","):
        parts = segment.split("-")
        if len(parts) > 2:
            raise InvalidPageSelectionError(f"Invalid page selection format at '{segment}'")
        numbers = []
        for part in parts:
            try:
                numbers.append(int(part))
            except ValueError as exc:
                bad = segment if not part.strip() else part
                raise InvalidPageSelectionError(f"Invalid page selection format at '{bad}'") from exc
        if len(numbers) > 1:
            lo, hi = numbers[0], numbers[-1]
            if lo >= hi:
                # 等しい場合も罠としてエラーになる(例: "5-5")——1ページだけなら単独指定を使う。
                raise InvalidPageSelectionError(
                    f"Invalid page selection '{lo}-{hi}'. The first number must be smaller "
                    "than the second into a range of pages"
                )
            pages.extend(range(lo, hi + 1))
        else:
            pages.append(numbers[0])
    return sorted(set(pages))


def _add_sequential_suffix(path: Path) -> Path:
    # PADの`Utilities.GenerateLocalFileName`の正確な命名規則は未確認。このパッケージの
    # 他モジュール(`cryptography_actions._next_sequential_path`)と同じ"(1)"方式で近似する。
    stem, suffix = path.stem, path.suffix
    n = 1
    candidate = path
    while candidate.exists():
        candidate = path.with_name(f"{stem} ({n}){suffix}")
        n += 1
    return candidate


def extract_pages_to_new_pdf(
    pdf_file: str,
    extracted_pdf_path: str,
    page_selection: str,
    password: str | None = None,
    if_file_exists: str = "AddSequentialSuffix",
) -> str | None:
    # PDFFileDoesNotExistErrorは、DoNotModifyFilesによるスキップより先に無条件で検証される
    # (出力先が既存でスキップされる場合でも、入力ファイルの存在チェックは必ず先に走る)。
    path = _require_pdf_file(pdf_file)
    dest = Path(extracted_pdf_path)
    if if_file_exists == "DoNotModifyFiles" and dest.exists():
        return None
    try:
        reader = _open_decrypted(path, password)
        page_count = len(reader.pages)
        pages = _parse_page_selection(page_selection)
        out_of_bounds = [p for p in pages if p <= 0 or p > page_count]
        if out_of_bounds:
            raise PageOutOfBoundsError(
                f"Page numbers '{', '.join(str(p) for p in out_of_bounds)}' don't exist in PDF '{pdf_file}'"
            )
        if if_file_exists == "AddSequentialSuffix" and dest.exists():
            dest = _add_sequential_suffix(dest)
        writer = PdfWriter()
        for page_number in pages:
            writer.add_page(reader.pages[page_number - 1])
        with dest.open("wb") as fh:
            writer.write(fh)
        return str(dest)
    except (InvalidPasswordError, PageOutOfBoundsError, InvalidPageSelectionError):
        raise
    except Exception as exc:
        raise FailedToExtractNewPDFFileError(f"Failed to extract new PDF file from '{pdf_file}'") from exc


def merge_pdf_files(
    pdf_files: list[str],
    merged_pdf_path: str,
    passwords: list[str] | None = None,
    if_file_exists: str = "AddSequentialSuffix",
) -> str | None:
    # PADは`PDFFiles`が単一要素の場合にその文字列表現から引用符区切りの複数パスを
    # 正規表現で抜き出すUI向けの特殊挙動を持つが、呼び出し側はすでに明確な
    # `list[str]`を渡す前提のためこの層では再現しない(DSL結線側の関心事)。
    dest = Path(merged_pdf_path)
    if if_file_exists == "DoNotModifyFiles" and dest.exists():
        return None
    if if_file_exists == "AddSequentialSuffix" and dest.exists():
        dest = _add_sequential_suffix(dest)
    try:
        writer = PdfWriter()
        for i, file_path in enumerate(pdf_files):
            src = _require_pdf_file(file_path)
            # パスワードが指定数より少ない場合、最後のパスワードを残りのファイルに使い回す。
            file_password = None
            if passwords:
                file_password = passwords[i] if i < len(passwords) else passwords[-1]
            reader = _open_decrypted(src, file_password)
            writer.append(reader)
        with dest.open("wb") as fh:
            writer.write(fh)
        return str(dest)
    except (PDFFileDoesNotExistError, InvalidPasswordError):
        _try_delete(dest)
        raise
    except Exception as exc:
        _try_delete(dest)
        raise FailedToMergePDFFilesError(f"Failed to merge PDF files: {exc}") from exc


def _try_delete(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
