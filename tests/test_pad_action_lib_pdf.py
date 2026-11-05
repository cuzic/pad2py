"""`pad_action_lib.pdf_actions`の単体テスト。

実PDFを`reportlab`(テスト専用依存)で生成し、`pypdf`/`pdfplumber`ベースの実装を検証する。
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from dump_daemon.pad_action_lib import pdf_actions as pdf


def _make_pdf(path: Path, pages: list[str]) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    for text in pages:
        c.drawString(100, 700, text)
        c.showPage()
    c.save()


def _make_pdf_with_table(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    x0, y0, w, h = 100, 500, 200, 100
    c.rect(x0, y0, w, h)
    c.line(x0, y0 + h / 2, x0 + w, y0 + h / 2)
    c.line(x0 + w / 2, y0, x0 + w / 2, y0 + h)
    c.drawString(x0 + 10, y0 + h - 20, "A1")
    c.drawString(x0 + w / 2 + 10, y0 + h - 20, "B1")
    c.drawString(x0 + 10, y0 + 10, "A2")
    c.drawString(x0 + w / 2 + 10, y0 + 10, "B2")
    c.showPage()
    c.save()


def _make_pdf_with_image(path: Path) -> None:
    from PIL import Image

    img = Image.new("RGB", (20, 20), color=(255, 0, 0))
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    img_buf.seek(0)

    c = canvas.Canvas(str(path), pagesize=(200, 200))
    c.drawImage(ImageReader(img_buf), 10, 10, width=50, height=50)
    c.showPage()
    c.save()


def _make_encrypted_pdf(path: Path, password: str) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(user_password=password, owner_password=password)
    with path.open("wb") as fh:
        writer.write(fh)


# --- extract_text_from_pdf ---------------------------------------------------


def test_extract_text_from_pdf_all_pages(tmp_path: Path) -> None:
    f = tmp_path / "a.pdf"
    _make_pdf(f, ["Hello", "World"])
    text = pdf.extract_text_from_pdf(str(f))
    assert "Hello" in text
    assert "World" in text


def test_extract_text_from_pdf_single_page(tmp_path: Path) -> None:
    f = tmp_path / "a.pdf"
    _make_pdf(f, ["PageOne", "PageTwo"])
    text = pdf.extract_text_from_pdf(str(f), pages_to_extract="Single", page_number=2)
    assert "PageTwo" in text
    assert "PageOne" not in text


def test_extract_text_from_pdf_range_clamps_out_of_bounds(tmp_path: Path) -> None:
    f = tmp_path / "a.pdf"
    _make_pdf(f, ["PageOne", "PageTwo"])
    # ToPageNumberが実際のページ数を超えても明示的なエラーにならず最終ページにクランプされる。
    text = pdf.extract_text_from_pdf(
        str(f), pages_to_extract="Range", from_page_number=1, to_page_number=100
    )
    assert "PageOne" in text
    assert "PageTwo" in text


def test_extract_text_from_pdf_single_page_zero_raises_value_error(tmp_path: Path) -> None:
    f = tmp_path / "a.pdf"
    _make_pdf(f, ["x"])
    with pytest.raises(ValueError):
        pdf.extract_text_from_pdf(str(f), pages_to_extract="Single", page_number=0)


def test_extract_text_from_pdf_missing_file_raises() -> None:
    with pytest.raises(pdf.PDFFileDoesNotExistError):
        pdf.extract_text_from_pdf("/nonexistent.pdf")


def test_extract_text_from_pdf_wrong_password_raises(tmp_path: Path) -> None:
    f = tmp_path / "enc.pdf"
    _make_encrypted_pdf(f, "correct")
    with pytest.raises(pdf.InvalidPasswordError):
        pdf.extract_text_from_pdf(str(f), password="wrong")


def test_extract_text_from_pdf_correct_password_succeeds(tmp_path: Path) -> None:
    f = tmp_path / "enc.pdf"
    _make_encrypted_pdf(f, "correct")
    # 本文テキストが無い(空白ページ)ので空文字列になるはずだが、例外は出ない。
    text = pdf.extract_text_from_pdf(str(f), password="correct")
    assert text == ""


def test_extract_text_from_pdf_detect_layout_preserves_words(tmp_path: Path) -> None:
    f = tmp_path / "a.pdf"
    _make_pdf(f, ["Hello World"])
    text = pdf.extract_text_from_pdf(str(f), detect_layout=True)
    assert "Hello" in text
    assert "World" in text


# --- extract_images_from_pdf --------------------------------------------------


def test_extract_images_from_pdf_writes_png(tmp_path: Path) -> None:
    f = tmp_path / "a.pdf"
    _make_pdf_with_image(f)
    out_dir = tmp_path / "images"
    out_dir.mkdir()
    written = pdf.extract_images_from_pdf(str(f), str(out_dir), "img")
    assert len(written) == 1
    assert written[0].endswith("img_0.png")
    assert Path(written[0]).is_file()


def test_extract_images_from_pdf_missing_folder_raises(tmp_path: Path) -> None:
    f = tmp_path / "a.pdf"
    _make_pdf_with_image(f)
    with pytest.raises(pdf.FolderDoesNotExistError):
        pdf.extract_images_from_pdf(str(f), str(tmp_path / "missing"), "img")


def test_extract_images_from_pdf_no_images_returns_empty_list(tmp_path: Path) -> None:
    f = tmp_path / "a.pdf"
    _make_pdf(f, ["no images here"])
    out_dir = tmp_path / "images"
    out_dir.mkdir()
    assert pdf.extract_images_from_pdf(str(f), str(out_dir), "img") == []


# --- extract_tables_from_pdf --------------------------------------------------


def test_extract_tables_from_pdf_with_header(tmp_path: Path) -> None:
    f = tmp_path / "a.pdf"
    _make_pdf_with_table(f)
    tables = pdf.extract_tables_from_pdf(str(f))
    assert len(tables) == 1
    table = tables[0]
    assert table.table_starting_page == 1
    assert table.table_ending_page == 1
    assert table.table_order_in_page == 1
    assert "PDF table #1 in page 1" in table.name
    assert len(table.data_table) == 1  # ヘッダー行を使うと2行中1行がデータ行になる
    assert table.data_table[0] == {"A1": "A2", "B1": "B2"}


def test_extract_tables_from_pdf_without_header_uses_generic_columns(tmp_path: Path) -> None:
    f = tmp_path / "a.pdf"
    _make_pdf_with_table(f)
    tables = pdf.extract_tables_from_pdf(str(f), set_first_row_as_header=False)
    table = tables[0]
    assert len(table.data_table) == 2
    assert table.data_table[0] == {"Column1": "A1", "Column2": "B1"}


def test_extract_tables_from_pdf_no_table_returns_empty_list(tmp_path: Path) -> None:
    f = tmp_path / "a.pdf"
    _make_pdf(f, ["just text"])
    assert pdf.extract_tables_from_pdf(str(f)) == []


# --- extract_pages_to_new_pdf -------------------------------------------------


def test_extract_pages_to_new_pdf_selection(tmp_path: Path) -> None:
    f = tmp_path / "a.pdf"
    _make_pdf(f, ["P1", "P2", "P3", "P4"])
    out = tmp_path / "out.pdf"
    result = pdf.extract_pages_to_new_pdf(str(f), str(out), "1,3-4")
    assert result == str(out)
    reader = PdfReader(str(out))
    assert len(reader.pages) == 3


def test_extract_pages_to_new_pdf_page_out_of_bounds_raises(tmp_path: Path) -> None:
    f = tmp_path / "a.pdf"
    _make_pdf(f, ["P1"])
    out = tmp_path / "out.pdf"
    with pytest.raises(pdf.PageOutOfBoundsError):
        pdf.extract_pages_to_new_pdf(str(f), str(out), "5")


def test_extract_pages_to_new_pdf_equal_range_is_invalid_selection(tmp_path: Path) -> None:
    f = tmp_path / "a.pdf"
    _make_pdf(f, ["P1", "P2"])
    out = tmp_path / "out.pdf"
    # "5-5"のような等しい範囲はPAD側の罠で明示的にエラーになる(単独指定にすべき)。
    with pytest.raises(pdf.InvalidPageSelectionError):
        pdf.extract_pages_to_new_pdf(str(f), str(out), "1-1")


def test_extract_pages_to_new_pdf_invalid_format_raises(tmp_path: Path) -> None:
    f = tmp_path / "a.pdf"
    _make_pdf(f, ["P1"])
    out = tmp_path / "out.pdf"
    with pytest.raises(pdf.InvalidPageSelectionError):
        pdf.extract_pages_to_new_pdf(str(f), str(out), "1-2-3")


def test_extract_pages_to_new_pdf_do_not_modify_existing(tmp_path: Path) -> None:
    f = tmp_path / "a.pdf"
    _make_pdf(f, ["P1"])
    out = tmp_path / "out.pdf"
    out.write_text("existing")
    result = pdf.extract_pages_to_new_pdf(
        str(f), str(out), "1", if_file_exists="DoNotModifyFiles"
    )
    assert result is None
    assert out.read_text() == "existing"


def test_extract_pages_to_new_pdf_missing_source_checked_before_skip(tmp_path: Path) -> None:
    # DoNotModifyFilesでスキップされる場合でも、入力PDFの存在チェックは必ず先に走る。
    out = tmp_path / "out.pdf"
    out.write_text("existing")
    with pytest.raises(pdf.PDFFileDoesNotExistError):
        pdf.extract_pages_to_new_pdf(
            str(tmp_path / "missing.pdf"), str(out), "1", if_file_exists="DoNotModifyFiles"
        )


def test_extract_pages_to_new_pdf_add_sequential_suffix(tmp_path: Path) -> None:
    # design/dsl_format_findings.md 知見115(decompile+実機確認済み): PADの
    # Utilities.GenerateLocalFileName()は最初の候補を常に"(2)"にする
    # ("(1)"は一切試さない、Windows Explorer自身のコピー命名規則とは異なる)。
    f = tmp_path / "a.pdf"
    _make_pdf(f, ["P1"])
    out = tmp_path / "out.pdf"
    out.write_text("existing")
    result = pdf.extract_pages_to_new_pdf(str(f), str(out), "1")
    assert result == str(tmp_path / "out (2).pdf")


# --- merge_pdf_files -----------------------------------------------------------


def test_merge_pdf_files_combines_page_counts(tmp_path: Path) -> None:
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    _make_pdf(a, ["A1", "A2"])
    _make_pdf(b, ["B1"])
    out = tmp_path / "merged.pdf"
    result = pdf.merge_pdf_files([str(a), str(b)], str(out))
    assert result == str(out)
    reader = PdfReader(str(out))
    assert len(reader.pages) == 3


def test_merge_pdf_files_missing_file_raises_and_cleans_up_output(tmp_path: Path) -> None:
    a = tmp_path / "a.pdf"
    _make_pdf(a, ["A1"])
    out = tmp_path / "merged.pdf"
    with pytest.raises(pdf.PDFFileDoesNotExistError):
        pdf.merge_pdf_files([str(a), str(tmp_path / "missing.pdf")], str(out))
    assert not out.exists()


def test_merge_pdf_files_do_not_modify_existing(tmp_path: Path) -> None:
    a = tmp_path / "a.pdf"
    _make_pdf(a, ["A1"])
    out = tmp_path / "merged.pdf"
    out.write_text("existing")
    result = pdf.merge_pdf_files([str(a)], str(out), if_file_exists="DoNotModifyFiles")
    assert result is None
    assert out.read_text() == "existing"


def test_merge_pdf_files_password_reused_for_remaining_files(tmp_path: Path) -> None:
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    _make_encrypted_pdf(a, "secret")
    _make_encrypted_pdf(b, "secret")
    out = tmp_path / "merged.pdf"
    # 1つだけパスワードを渡しても、残りのファイルに同じパスワードが使い回される。
    result = pdf.merge_pdf_files([str(a), str(b)], str(out), passwords=["secret"])
    assert result == str(out)
    reader = PdfReader(str(out))
    assert len(reader.pages) == 2


def test_merge_pdf_files_wrong_password_raises(tmp_path: Path) -> None:
    a = tmp_path / "a.pdf"
    _make_encrypted_pdf(a, "secret")
    out = tmp_path / "merged.pdf"
    with pytest.raises(pdf.InvalidPasswordError):
        pdf.merge_pdf_files([str(a)], str(out), passwords=["wrong"])
