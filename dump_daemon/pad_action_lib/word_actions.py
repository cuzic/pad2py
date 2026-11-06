"""`Word.Actions`(LaunchWord/CloseWord/SaveWord/ReadFromWord/WriteToWord/FindAndReplaceWord)のロジック層。

PADの実装は`Microsoft.Office.Interop.Word`経由でライブWordプロセスを操作する
(`WordInstanceHandle`がCOMの`Application`/`Document`参照を保持)。`python-docx`は
`.docx`ファイルを直接読み書きするだけでライブアプリを起動しないため、ここでは
「テキスト内容・基本構造の読み書き」(LaunchWord/CloseWord/SaveWord/ReadFromWordの
WholeDocument・Bookmarkモード/WriteToWordのStart・EndOfDocumentモード/
FindAndReplaceWord)に範囲を絞る。クリップボード画像挿入・ライブページ分割・実行中
Wordへのアタッチは、ライブCOMインスタンス無しには原理的に再現できないため
`NotImplementedError`で明示する(でっち上げた近似は作らない)。

design/dsl_format_findings.md 知見181: `ReadFromWord`の`Bookmark`モードは、
`python-docx`に高レベルの`Bookmarks`コレクションAPIが無いため、`lxml`経由で
OOXMLの`<w:bookmarkStart>`/`<w:bookmarkEnd>`を直接検索する低レベル実装
(`_bookmark_range_text()`)で対応した——Word COMの`Document.Bookmarks[name]
.Range.Text`と構造的に同じ検索(名前でブックマークを探し、開始〜終了マーカー間の
テキストを連結する)。`WriteToWord`/`InsertImageToWord`のブックマーク相対モードは
依然未対応(書き込み側は挿入位置の正確な意味論がより複雑なため、読み取り側のみ
先行実装した)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import docx
from docx.oxml.ns import qn

from .errors import PadActionError


class LauchWordError(PadActionError):  # 原文のタイポ("Launch"ではなく"Lauch")をそのまま保持
    pass


class LaunchWordFileNotFoundError(PadActionError):
    pass


class LaunchWordOpenExistingDocumentError(PadActionError):
    pass


class LaunchWordApplicationError(PadActionError):
    pass


class LaunchWordInstallationError(PadActionError):
    pass


class WordInstanceNotInitializedError(PadActionError):
    pass


class WordOperationOnReadOnlyDocumentError(PadActionError):
    pass


class SaveWordError(PadActionError):
    pass


class CloseWordError(PadActionError):
    pass


class ReadWordError(PadActionError):
    pass


class WriteWordError(PadActionError):
    pass


class FindAndReplaceError(PadActionError):
    pass


class InsertImageWordError(PadActionError):
    pass


@dataclass
class WordInstanceHandle:
    """不透明な「Wordインスタンス」ハンドル(実際のライブCOMではなく`docx.Document`を保持)。"""

    document: docx.document.Document
    path: str | None = None
    read_only: bool = False


def launch_word(
    mode: str = "NewDocument",
    path: str | None = None,
    read_only: bool = False,
    visible: bool = True,
    read_protection_password: str = "",
    write_protection_password: str = "",
) -> WordInstanceHandle:
    # Visible/*ProtectionPasswordはライブCOMにのみ意味がある(python-docxには「表示」
    # 「保護パスワード付きで開く」という概念が無い)ため、受け取っても無視する。
    del visible, read_protection_password, write_protection_password
    if mode == "NewDocument":
        return WordInstanceHandle(document=docx.Document(), path=None, read_only=False)
    if mode == "StoredDocument":
        if path is None or not Path(path).is_file():
            raise LaunchWordFileNotFoundError(str(path))
        try:
            document = docx.Document(path)
        except Exception as exc:
            raise LaunchWordOpenExistingDocumentError(str(exc)) from exc
        return WordInstanceHandle(document=document, path=path, read_only=read_only)
    raise ValueError(f"Unknown LaunchWordMode: {mode!r}")


def save_word(
    instance: WordInstanceHandle | None,
    save_mode: str = "Save",
    document_format: str = "FromExtension",
    document_path: str | None = None,
) -> None:
    if instance is None:
        raise WordInstanceNotInitializedError("Instance is required")
    if instance.read_only:
        raise WordOperationOnReadOnlyDocumentError(instance.path or "")
    target_path = document_path if save_mode == "SaveAs" else instance.path
    if target_path is None:
        raise SaveWordError("no path available to save a document that was never saved before")
    extension = Path(target_path).suffix.lower()
    if document_format not in ("FromExtension", "DOCX"):
        raise SaveWordError(
            f"python-docx can only save .docx; requested DocumentFormat {document_format!r} is not supported"
        )
    if document_format == "FromExtension" and extension != ".docx":
        raise SaveWordError(f"python-docx can only save .docx; extension {extension!r} is not supported")
    try:
        instance.document.save(target_path)
    except OSError as exc:
        raise SaveWordError(str(exc)) from exc
    instance.path = target_path


def close_word(
    instance: WordInstanceHandle | None,
    close_mode: str = "DoNotSave",
    document_format: str = "FromExtension",
    document_path: str | None = None,
) -> None:
    if instance is None:
        # Instanceが無い場合は何もせず正常終了(エラーにならない、静かなno-op)。
        return
    if close_mode == "DoNotSave":
        return
    save_mode = "Save" if close_mode == "Save" else "SaveAs"
    # SaveWordが投げるSaveWordError/WordOperationOnReadOnlyDocumentErrorはCloseWordErrorに
    # 包み直さず、そのまま伝播させる(実機の挙動と同じ非対称性)。
    save_word(instance, save_mode=save_mode, document_format=document_format, document_path=document_path)


def _bookmark_range_text(document: docx.Document, bookmark_name: str) -> str | None:
    """design/dsl_format_findings.md 知見181: `python-docx`に高レベルの`Bookmarks`
    コレクションAPIが無いため、OOXMLの`<w:bookmarkStart>`/`<w:bookmarkEnd>`を
    文書順(`document.element.body.iter()`)で直接検索し、両マーカーの間にある
    `<w:t>`要素のテキストを連結する——Word COMの`Bookmark.Range.Text`と同じ
    「名前で見つけた範囲の生テキスト」。見つからない場合は`None`を返す(呼び出し元が
    「未発見」と「空のブックマーク」を区別できるようにする、実機は両方とも空文字列を
    返すため呼び出し元で合流させる)。

    複数の段落をまたぐブックマークは、段落境界に`\\r`を挿入せず`<w:t>`の内容を
    そのまま連結する——単一段落内のブックマークという典型例の範囲内でのみ忠実
    (複数段落をまたぐ場合の正確な`\\r`挿入位置はWord COM実機で未確認のため、
    でっち上げない)。
    """
    bookmark_start_tag = qn("w:bookmarkStart")
    bookmark_end_tag = qn("w:bookmarkEnd")
    name_attr = qn("w:name")
    id_attr = qn("w:id")
    text_tag = qn("w:t")

    descendants = list(document.element.body.iter())
    start_index: int | None = None
    bookmark_id: str | None = None
    for index, element in enumerate(descendants):
        if element.tag == bookmark_start_tag and element.get(name_attr) == bookmark_name:
            start_index = index
            bookmark_id = element.get(id_attr)
            break
    if start_index is None:
        return None

    end_index: int | None = None
    for index in range(start_index + 1, len(descendants)):
        if descendants[index].tag == bookmark_end_tag and descendants[index].get(id_attr) == bookmark_id:
            end_index = index
            break
    if end_index is None:
        return None

    return "".join(
        element.text or "" for element in descendants[start_index:end_index] if element.tag == text_tag
    )


def read_from_word(
    instance: WordInstanceHandle | None,
    read_mode: str = "WholeDocument",
    pages: str = "1",
    bookmark: str = "",
) -> str:
    if instance is None:
        raise WordInstanceNotInitializedError("Instance is required")
    if read_mode == "WholeDocument":
        # Word COMのRange.Textは段落区切りを"\r"(CRのみ)で返す既知の仕様に合わせる
        # (python-docxの段落リストを"\r"で連結して近似する)。
        return "\r".join(p.text for p in instance.document.paragraphs)
    if read_mode == "Page":
        raise NotImplementedError(
            "ReadFromWord Page mode depends on live Word's page layout/rendering engine "
            f"(requested pages={pages!r}); python-docx has no pagination concept"
        )
    if read_mode == "Bookmark":
        # design/dsl_format_findings.md 知見181(decompile確認済み): 実機の
        # `ReadDocumentByBookmark()`は見つからない場合・空のブックマークの場合の
        # 両方で空文字列を返す(例外にしない)。
        text = _bookmark_range_text(instance.document, bookmark)
        return text if text is not None else ""
    raise ValueError(f"Unknown ReadWordMode: {read_mode!r}")


def write_to_word(
    instance: WordInstanceHandle | None,
    text: str,
    append_new_line: bool = False,
    write_mode: str = "StartOfDocument",
    bookmark: str = "",
) -> None:
    if instance is None:
        raise WordInstanceNotInitializedError("Instance is required")
    if instance.read_only:
        raise WordOperationOnReadOnlyDocumentError(instance.path or "")
    if write_mode in ("StartOfBookmark", "EndOfBookmark"):
        raise NotImplementedError(
            f"WriteToWord bookmark modes depend on Word's live Bookmarks collection "
            f"(requested bookmark={bookmark!r}); python-docx has no bookmark navigation API"
        )
    if write_mode not in ("StartOfDocument", "EndOfDocument"):
        raise ValueError(f"Unknown WriteWordMode: {write_mode!r}")

    # AppendNewLineはテキストの"前"に\r\nを挿入する(後ではない)——実機の非自明な挙動。
    content = ("\r\n" + text) if append_new_line else text
    # python-docxの段落はCOM Rangeの生テキストとはモデルが異なるため、「1行=1段落」という
    # 近似を採用する(厳密な再現ではない)。
    lines = content.splitlines() or [""]
    document = instance.document

    if write_mode == "StartOfDocument":
        if document.paragraphs:
            anchor = document.paragraphs[0]
            for line in reversed(lines):
                anchor = anchor.insert_paragraph_before(line)
        else:
            for line in lines:
                document.add_paragraph(line)
    else:  # EndOfDocument
        for line in lines:
            document.add_paragraph(line)


def _build_find_pattern(text_to_find: str, match_case: bool, match_entire_word: bool) -> re.Pattern[str]:
    escaped = re.escape(text_to_find)
    if match_entire_word:
        escaped = rf"\b{escaped}\b"
    return re.compile(escaped, 0 if match_case else re.IGNORECASE)


def find_and_replace_word(
    instance: WordInstanceHandle | None,
    text_to_find: str,
    text_to_replace_with: str,
    all_matches: bool = False,
    match_case: bool = False,
    match_entire_word: bool = False,
    match_wild_cards: bool = False,
) -> int:
    if instance is None:
        raise WordInstanceNotInitializedError("Instance is required")
    if instance.read_only:
        raise WordOperationOnReadOnlyDocumentError(instance.path or "")
    if not text_to_find:
        # 空/NoneのTextToFindは静かなno-op(実機のFindAndReplaceと同じ)。
        return 0
    if match_wild_cards:
        raise NotImplementedError(
            "MatchWildCards uses Word's own wildcard pattern syntax, which is not equivalent "
            "to Python regex; not implemented to avoid guessing the mapping"
        )
    try:
        pattern = _build_find_pattern(text_to_find, match_case, match_entire_word)
    except re.error as exc:
        raise FindAndReplaceError(str(exc)) from exc

    replaced = 0
    # python-docxのrunはWordの書式変更単位で分割されるため、検索文字列が複数runに
    # またがる場合は見つからないことがある(COMのFindはrun境界を越えて検索できるため、
    # これは明確な既知の制限)。
    for paragraph in instance.document.paragraphs:
        for run in paragraph.runs:
            new_text, count = pattern.subn(text_to_replace_with, run.text, count=0 if all_matches else 1)
            if count:
                run.text = new_text
                replaced += count
                if not all_matches:
                    return replaced
    return replaced


def attach_to_running_word(*_args: object, **_kwargs: object) -> WordInstanceHandle:
    raise NotImplementedError(
        "AttachToRunningWord requires attaching to a live Word COM process; "
        "out of scope for the python-docx based implementation"
    )


def insert_image_to_word(
    instance: WordInstanceHandle | None,
    path: str,
    insert_image_mode: str = "StartOfDocument",
) -> None:
    """design/dsl_format_findings.md 知見177(decompile確認済み): `InsertImageMode`の
    `StartOfDocument`/`EndOfDocument`(`Source=File`固定)のみ対応する。ブックマーク相対
    (`StartOfBookmark`/`EndOfBookmark`、python-docxにブックマークナビゲーションAPIが無い)・
    テキスト相対(`StartOfText`/`EndOfText`、実機の`TextToFind`位置特定アルゴリズムが
    未確認)・クリップボード画像ソース(`Source=Clipboard`、OSクリップボードの画像読み取り
    機構が本プロジェクトに未確立)は、でっち上げず`NotImplementedError`のままにする。
    """
    if instance is None:
        raise WordInstanceNotInitializedError("Instance is required")
    if instance.read_only:
        raise WordOperationOnReadOnlyDocumentError(instance.path or "")
    if insert_image_mode not in ("StartOfDocument", "EndOfDocument"):
        raise NotImplementedError(
            f"InsertImageToWord mode {insert_image_mode!r} depends on Word's live Bookmarks "
            "collection or TextToFind position search; python-docx has no equivalent API"
        )
    if not Path(path).is_file():
        raise InsertImageWordError(f"image file not found: {path!r}")
    document = instance.document
    try:
        if insert_image_mode == "EndOfDocument":
            document.add_picture(path)
        else:  # StartOfDocument
            if document.paragraphs:
                new_paragraph = document.paragraphs[0].insert_paragraph_before()
            else:
                new_paragraph = document.add_paragraph()
            new_paragraph.add_run().add_picture(path)
    except Exception as exc:
        raise InsertImageWordError(str(exc)) from exc
