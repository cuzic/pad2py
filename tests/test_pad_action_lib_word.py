"""`pad_action_lib.word_actions`の単体テスト(python-docxは完全オフラインで動くので実ファイルで検証)。"""
from __future__ import annotations

from pathlib import Path

import docx
import pytest
from docx.oxml.ns import qn

from dump_daemon.pad_action_lib import word_actions as wa


def test_launch_new_document_then_write_save_and_reload(tmp_path: Path) -> None:
    instance = wa.launch_word(mode="NewDocument")
    wa.write_to_word(instance, "Hello", write_mode="StartOfDocument")
    dest = tmp_path / "out.docx"
    wa.save_word(instance, save_mode="SaveAs", document_path=str(dest))
    assert dest.is_file()

    reloaded = wa.launch_word(mode="StoredDocument", path=str(dest))
    assert wa.read_from_word(reloaded) == "Hello"


def test_launch_stored_document_missing_file_raises() -> None:
    with pytest.raises(wa.LaunchWordFileNotFoundError):
        wa.launch_word(mode="StoredDocument", path="/nonexistent/doc.docx")


def test_launch_unknown_mode_raises() -> None:
    with pytest.raises(ValueError):
        wa.launch_word(mode="Bogus")


def test_write_to_word_start_of_document_prepends(tmp_path: Path) -> None:
    doc = docx.Document()
    doc.add_paragraph("World")
    path = tmp_path / "existing.docx"
    doc.save(path)

    instance = wa.launch_word(mode="StoredDocument", path=str(path))
    wa.write_to_word(instance, "Hello", write_mode="StartOfDocument")
    assert [p.text for p in instance.document.paragraphs] == ["Hello", "World"]


def test_write_to_word_end_of_document_appends() -> None:
    instance = wa.launch_word(mode="NewDocument")
    wa.write_to_word(instance, "First", write_mode="EndOfDocument")
    wa.write_to_word(instance, "Second", write_mode="EndOfDocument")
    assert [p.text for p in instance.document.paragraphs] == ["First", "Second"]


def test_write_to_word_append_new_line_prepends_newline_not_appends() -> None:
    # AppendNewLineはテキストの"前"に\r\nを挿入する(後ではない)という実機の非自明な挙動。
    instance = wa.launch_word(mode="NewDocument")
    wa.write_to_word(instance, "Second", write_mode="EndOfDocument")
    wa.write_to_word(instance, "Third", write_mode="EndOfDocument", append_new_line=True)
    texts = [p.text for p in instance.document.paragraphs]
    assert texts == ["Second", "", "Third"]


def test_write_to_word_multiline_text_becomes_multiple_paragraphs() -> None:
    instance = wa.launch_word(mode="NewDocument")
    wa.write_to_word(instance, "Line1\nLine2\nLine3", write_mode="EndOfDocument")
    assert [p.text for p in instance.document.paragraphs] == ["Line1", "Line2", "Line3"]


def test_write_to_word_bookmark_mode_not_implemented() -> None:
    instance = wa.launch_word(mode="NewDocument")
    with pytest.raises(NotImplementedError):
        wa.write_to_word(instance, "x", write_mode="StartOfBookmark", bookmark="b")


def test_write_to_word_on_read_only_raises() -> None:
    instance = wa.launch_word(mode="NewDocument")
    instance.read_only = True
    with pytest.raises(wa.WordOperationOnReadOnlyDocumentError):
        wa.write_to_word(instance, "x")


def test_read_from_word_whole_document_joins_paragraphs_with_cr() -> None:
    instance = wa.launch_word(mode="NewDocument")
    wa.write_to_word(instance, "A", write_mode="EndOfDocument")
    wa.write_to_word(instance, "B", write_mode="EndOfDocument")
    assert wa.read_from_word(instance) == "A\rB"


def test_read_from_word_page_mode_not_implemented() -> None:
    instance = wa.launch_word(mode="NewDocument")
    with pytest.raises(NotImplementedError):
        wa.read_from_word(instance, read_mode="Page", pages="1")


def _add_bookmark(paragraph, bookmark_id: str, name: str, text: str) -> None:
    """テスト用: `<w:bookmarkStart>`/`<w:bookmarkEnd>`を手動で挿入する
    (`python-docx`に高レベルAPIが無いため、知見181の実装と同じ低レベル手段で
    テスト用フィクスチャ自体も組み立てる)。"""
    from docx.oxml import OxmlElement

    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), bookmark_id)
    start.set(qn("w:name"), name)
    paragraph._p.append(start)
    if text:
        paragraph.add_run(text)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), bookmark_id)
    paragraph._p.append(end)


def test_read_from_word_bookmark_mode_returns_text_between_markers() -> None:
    # design/dsl_format_findings.md 知見181(decompile確認済み): `ReadDocumentByBookmark()`
    # はWord COMの`Bookmarks[name].Range.Text`相当——ブックマーク開始〜終了間のテキスト。
    instance = wa.launch_word(mode="NewDocument")
    p = instance.document.add_paragraph()
    p.add_run("before ")
    _add_bookmark(p, "0", "MyBookmark", "inside text")
    p.add_run(" after")
    assert wa.read_from_word(instance, read_mode="Bookmark", bookmark="MyBookmark") == "inside text"


def test_read_from_word_bookmark_mode_empty_bookmark_returns_empty_string() -> None:
    instance = wa.launch_word(mode="NewDocument")
    p = instance.document.add_paragraph()
    _add_bookmark(p, "0", "EmptyBookmark", "")
    assert wa.read_from_word(instance, read_mode="Bookmark", bookmark="EmptyBookmark") == ""


def test_read_from_word_bookmark_mode_not_found_returns_empty_string() -> None:
    # decompile確認済み: 実機は見つからない場合も例外にせず空文字列を返す。
    instance = wa.launch_word(mode="NewDocument")
    assert wa.read_from_word(instance, read_mode="Bookmark", bookmark="NoSuchBookmark") == ""


def test_read_from_word_bookmark_mode_round_trips_through_save_reload(tmp_path: Path) -> None:
    instance = wa.launch_word(mode="NewDocument")
    p = instance.document.add_paragraph()
    _add_bookmark(p, "0", "MyBookmark", "saved text")
    dest = tmp_path / "out.docx"
    wa.save_word(instance, save_mode="SaveAs", document_path=str(dest))

    reloaded = wa.launch_word(mode="StoredDocument", path=str(dest))
    assert wa.read_from_word(reloaded, read_mode="Bookmark", bookmark="MyBookmark") == "saved text"


def test_read_from_word_requires_instance() -> None:
    with pytest.raises(wa.WordInstanceNotInitializedError):
        wa.read_from_word(None)


def test_find_and_replace_first_match_only_by_default() -> None:
    instance = wa.launch_word(mode="NewDocument")
    instance.document.add_paragraph("cat and cat")
    replaced = wa.find_and_replace_word(instance, "cat", "dog")
    assert replaced == 1
    assert instance.document.paragraphs[0].text == "dog and cat"


def test_find_and_replace_all_matches() -> None:
    instance = wa.launch_word(mode="NewDocument")
    instance.document.add_paragraph("cat and cat")
    replaced = wa.find_and_replace_word(instance, "cat", "dog", all_matches=True)
    assert replaced == 2
    assert instance.document.paragraphs[0].text == "dog and dog"


def test_find_and_replace_match_case() -> None:
    instance = wa.launch_word(mode="NewDocument")
    instance.document.add_paragraph("Cat cat")
    replaced = wa.find_and_replace_word(instance, "cat", "dog", all_matches=True, match_case=True)
    assert replaced == 1
    assert instance.document.paragraphs[0].text == "Cat dog"


def test_find_and_replace_match_entire_word() -> None:
    instance = wa.launch_word(mode="NewDocument")
    instance.document.add_paragraph("cats and cat")
    replaced = wa.find_and_replace_word(
        instance, "cat", "dog", all_matches=True, match_entire_word=True
    )
    assert replaced == 1
    assert instance.document.paragraphs[0].text == "cats and dog"


def test_find_and_replace_empty_text_to_find_is_silent_noop() -> None:
    instance = wa.launch_word(mode="NewDocument")
    instance.document.add_paragraph("unchanged")
    replaced = wa.find_and_replace_word(instance, "", "dog")
    assert replaced == 0
    assert instance.document.paragraphs[0].text == "unchanged"


def test_find_and_replace_wildcards_not_implemented() -> None:
    instance = wa.launch_word(mode="NewDocument")
    with pytest.raises(NotImplementedError):
        wa.find_and_replace_word(instance, "c*t", "dog", match_wild_cards=True)


def test_find_and_replace_on_read_only_raises() -> None:
    instance = wa.launch_word(mode="NewDocument")
    instance.read_only = True
    with pytest.raises(wa.WordOperationOnReadOnlyDocumentError):
        wa.find_and_replace_word(instance, "a", "b")


def test_close_word_with_no_instance_is_silent_noop() -> None:
    wa.close_word(None)  # 例外を投げないことを確認するだけ


def test_close_word_do_not_save_does_not_persist(tmp_path: Path) -> None:
    path = tmp_path / "a.docx"
    docx.Document().save(path)
    instance = wa.launch_word(mode="StoredDocument", path=str(path))
    wa.write_to_word(instance, "changed", write_mode="EndOfDocument")
    wa.close_word(instance, close_mode="DoNotSave")
    reloaded = docx.Document(path)
    assert reloaded.paragraphs == [] or reloaded.paragraphs[0].text != "changed"


def test_close_word_save_persists_changes(tmp_path: Path) -> None:
    path = tmp_path / "a.docx"
    docx.Document().save(path)
    instance = wa.launch_word(mode="StoredDocument", path=str(path))
    wa.write_to_word(instance, "changed", write_mode="EndOfDocument")
    wa.close_word(instance, close_mode="Save")
    reloaded = docx.Document(path)
    assert reloaded.paragraphs[0].text == "changed"


def test_close_word_save_propagates_save_error_not_wrapped(tmp_path: Path) -> None:
    instance = wa.launch_word(mode="NewDocument")  # never saved, no path
    with pytest.raises(wa.SaveWordError):
        wa.close_word(instance, close_mode="Save")


def test_save_word_unsupported_format_raises() -> None:
    instance = wa.launch_word(mode="NewDocument")
    with pytest.raises(wa.SaveWordError):
        wa.save_word(instance, save_mode="SaveAs", document_format="PDF", document_path="/tmp/x.pdf")


def test_save_word_unsupported_extension_raises(tmp_path: Path) -> None:
    instance = wa.launch_word(mode="NewDocument")
    with pytest.raises(wa.SaveWordError):
        wa.save_word(instance, save_mode="SaveAs", document_path=str(tmp_path / "out.rtf"))


def test_attach_to_running_word_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        wa.attach_to_running_word()


def _make_png(path: Path) -> None:
    from PIL import Image

    Image.new("RGB", (4, 4), color="red").save(path)


def test_insert_image_to_word_end_of_document_appends(tmp_path: Path) -> None:
    # design/dsl_format_findings.md 知見177(decompile確認済み): `InsertImageToWord`の
    # `StartOfDocument`/`EndOfDocument`(`Source=File`固定)のみ対応。
    image = tmp_path / "pic.png"
    _make_png(image)
    instance = wa.launch_word(mode="NewDocument")
    wa.write_to_word(instance, "Hello", write_mode="StartOfDocument")
    wa.insert_image_to_word(instance, str(image), insert_image_mode="EndOfDocument")
    dest = tmp_path / "out.docx"
    wa.save_word(instance, save_mode="SaveAs", document_path=str(dest))

    reloaded = docx.Document(str(dest))
    assert reloaded.inline_shapes
    # 既存のテキストがそのまま残り、画像は末尾に追加される(先頭ではない)。
    assert reloaded.paragraphs[0].text == "Hello"


def test_insert_image_to_word_start_of_document_prepends(tmp_path: Path) -> None:
    image = tmp_path / "pic.png"
    _make_png(image)
    instance = wa.launch_word(mode="NewDocument")
    wa.write_to_word(instance, "Hello", write_mode="StartOfDocument")
    wa.insert_image_to_word(instance, str(image), insert_image_mode="StartOfDocument")

    assert instance.document.inline_shapes
    # 画像を含む新しい段落が先頭に挿入され、既存のテキストは2番目の段落へ押し出される。
    assert instance.document.paragraphs[0].text == ""
    assert instance.document.paragraphs[1].text == "Hello"


def test_insert_image_to_word_missing_file_raises(tmp_path: Path) -> None:
    instance = wa.launch_word(mode="NewDocument")
    with pytest.raises(wa.InsertImageWordError):
        wa.insert_image_to_word(instance, str(tmp_path / "missing.png"))


def test_insert_image_to_word_instance_none_raises() -> None:
    with pytest.raises(wa.WordInstanceNotInitializedError):
        wa.insert_image_to_word(None, "x.png")


def test_insert_image_to_word_bookmark_and_text_relative_modes_not_implemented(tmp_path: Path) -> None:
    # `StartOfBookmark`/`EndOfBookmark`/`StartOfText`/`EndOfText`はでっち上げず保留。
    image = tmp_path / "pic.png"
    _make_png(image)
    instance = wa.launch_word(mode="NewDocument")
    for mode in ("StartOfBookmark", "EndOfBookmark", "StartOfText", "EndOfText"):
        with pytest.raises(NotImplementedError):
            wa.insert_image_to_word(instance, str(image), insert_image_mode=mode)
