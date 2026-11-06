"""`Word.*`のcodegen。

`pad_action_lib.word_actions`へ委譲する。知見80では、action_id文字列はPADデザイナー
自身の検索結果`TreeItem`のUIA `AutomationId`で「アクションが存在する」ことまでは
確認していたが、これはアクション**グループ**のAutomationIdであり、知見155・156
(Excel/PDF)と同じ`ActionSelectorBase`一括列挙監査を知見157でWordにも適用した結果、
`CloseWord`/`FindAndReplaceWord`/`LaunchWord`/`ReadFromWord`/`SaveWord`/`WriteToWord`
の6グループには実際には兄弟セレクタがあり、DSL上の真のaction_idは
`Word.<グループ>.<ActionName>`という3セグメント形式だと判明した——いずれのグループ
も`[Action(...)]`に`Id`属性の上書きが無いため、中間セグメント自体(クラス名)は従来の
フラットな判定と変わらず正しかったが、**第3セグメントが欠けていたため実際のDSLでは
一度もマッチしなかった**(知見157で発見・修正)。`InsertImageToWord`(8セレクタ)は
pad_action_lib側に未実装のため今回は対象外。

`Instance`(`WordInstanceHandle`への参照)は`excel.py`の`Instance`と同じく、PAD側では
不透明な参照だがPythonコード生成の観点では他の変数参照と同じ(特別な結線は不要)。

ライブWord COM専用の機能(`Visible`・保護パスワード・ページ単位読み取り・ブックマーク・
ワイルドカード検索)は`pad_action_lib.word_actions`側で最初からスコープ外
(docs-local/pad_word_findings.md)。`Visible`/`*ProtectionPassword`はpython-docx側に
対応概念が無く無視されるだけ(でっち上げた保護をかけない)なので、生成コードにも含めない。
`ReadMode`/`WriteMode`がPage/Bookmark系、`MatchWildCards=True`の兄弟セレクタは、
でっち上げたコードを出力せず安全にTODOフォールバックへ委ねる(知見157のセレクタ監査で
`Prop<>.ShouldBe()`から確定、`enum_last()`で動的に読む必要は無い)。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import safe_render


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("Word."):
        return None
    prefix = INDENT * indent
    p = node.params

    # 知見157: `LaunchWord`の兄弟セレクタ2件(`LaunchWordMode`は`NewDocument`/
    # `StoredDocument`で固定、Excelの`LaunchExcel`と同じ構造——Word側は既存プロセスへの
    # アタッチ変種が無い)。
    if action_id == "Word.LaunchWord.Launch":
        if not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = word_actions.launch_word("
            f"mode='NewDocument', path=None, read_only=False)"
        ]

    if action_id == "Word.LaunchWord.LaunchAndOpen":
        path = safe_render(p.get("Path"))
        read_only = safe_render(p.get("ReadOnly", False))
        if path is None or read_only is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = word_actions.launch_word("
            f"mode='StoredDocument', path={path}, read_only={read_only})"
        ]

    # 知見157: `SaveWord`の兄弟セレクタ2件(`SaveMode`は`Save`/`SaveAs`で固定)。
    if action_id == "Word.SaveWord.Save":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        return [
            f"{prefix}word_actions.save_word({instance}, save_mode='Save', "
            f"document_format='FromExtension', document_path=None)"
        ]

    if action_id == "Word.SaveWord.SaveAs":
        instance = safe_render(p.get("Instance"))
        document_path = safe_render(p.get("DocumentPath"))
        if instance is None or document_path is None:
            return None
        return [
            f"{prefix}word_actions.save_word({instance}, save_mode='SaveAs', "
            f"document_format='FromExtension', document_path={document_path})"
        ]

    # 知見157: `CloseWord`の兄弟セレクタ3件(`CloseMode`は`DoNotSave`/`Save`/`SaveAs`で固定)。
    if action_id == "Word.CloseWord.Close":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        return [
            f"{prefix}word_actions.close_word({instance}, close_mode='DoNotSave', "
            f"document_format='FromExtension', document_path=None)"
        ]

    if action_id == "Word.CloseWord.CloseAndSave":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        return [
            f"{prefix}word_actions.close_word({instance}, close_mode='Save', "
            f"document_format='FromExtension', document_path=None)"
        ]

    if action_id == "Word.CloseWord.CloseAndSaveAs":
        instance = safe_render(p.get("Instance"))
        document_path = safe_render(p.get("DocumentPath"))
        if instance is None or document_path is None:
            return None
        return [
            f"{prefix}word_actions.close_word({instance}, close_mode='SaveAs', "
            f"document_format='FromExtension', document_path={document_path})"
        ]

    # 知見157: `ReadFromWord`の兄弟セレクタ3件のうち、`ReadPage`/`ReadBookmark`
    # (ページ単位/ブックマーク読み取り)はpython-docxに対応概念が無くスコープ外。
    if action_id == "Word.ReadFromWord.Read":
        instance = safe_render(p.get("Instance"))
        if instance is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = word_actions.read_from_word({instance}, "
            f"read_mode='WholeDocument', pages='1', bookmark='')"
        ]

    if action_id == "Word.ReadFromWord.ReadBookmark":
        # design/dsl_format_findings.md 知見181(decompile確認済み): `ReadDocumentByBookmark()`
        # はWord COMの`Bookmarks[name].Range.Text`相当——`word_actions._bookmark_range_text()`
        # (`lxml`で`<w:bookmarkStart>`/`<w:bookmarkEnd>`を直接検索)で再現した。
        instance = safe_render(p.get("Instance"))
        bookmark = safe_render(p.get("Bookmark"))
        if instance is None or bookmark is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = word_actions.read_from_word({instance}, "
            f"read_mode='Bookmark', pages='1', bookmark={bookmark})"
        ]

    # 知見157: `WriteToWord`の兄弟セレクタ4件のうち、`WriteStartOfBookmark`/
    # `WriteEndOfBookmark`(ブックマーク書き込み)はスコープ外。
    _WORD_WRITE_MODE_BY_ACTION_NAME = {
        "Word.WriteToWord.WriteStartOfDocument": "StartOfDocument",
        "Word.WriteToWord.WriteEndOfDocument": "EndOfDocument",
    }
    write_mode = _WORD_WRITE_MODE_BY_ACTION_NAME.get(action_id)
    if write_mode is not None:
        instance = safe_render(p.get("Instance"))
        text = safe_render(p.get("Text"))
        append_new_line = safe_render(p.get("AppendNewLine", False))
        if instance is None or text is None or append_new_line is None:
            return None
        return [
            f"{prefix}word_actions.write_to_word({instance}, {text}, "
            f"append_new_line={append_new_line}, write_mode={write_mode!r}, bookmark='')"
        ]

    # 知見157: `FindAndReplaceWord`の兄弟セレクタ4件のうち、`MatchWildCards=True`の
    # 2件(`FindAndReplaceSingleWildcards`/`FindAndReplaceAllWildcards`、Wordのワイルド
    # カード構文は正規表現と等価ではなく憶測で対応表を作らない方針)はスコープ外。
    _WORD_FIND_REPLACE_ALL_MATCHES = {
        "Word.FindAndReplaceWord.FindAndReplaceSingle": False,
        "Word.FindAndReplaceWord.FindAndReplaceAllWithoutWildcards": True,
    }
    all_matches_literal = _WORD_FIND_REPLACE_ALL_MATCHES.get(action_id)
    if all_matches_literal is not None:
        instance = safe_render(p.get("Instance"))
        text_to_find = safe_render(p.get("TextToFind"))
        text_to_replace_with = safe_render(p.get("TextToReplaceWith"))
        match_case = safe_render(p.get("MatchCase", False))
        match_entire_word = safe_render(p.get("MatchEntireWord", False))
        if None in (instance, text_to_find, text_to_replace_with, match_case, match_entire_word):
            return None
        return [
            f"{prefix}word_actions.find_and_replace_word({instance}, {text_to_find}, "
            f"{text_to_replace_with}, all_matches={all_matches_literal}, match_case={match_case}, "
            f"match_entire_word={match_entire_word}, match_wild_cards=False)"
        ]

    # design/dsl_format_findings.md 知見177(decompile確認済み): `InsertImageToWord`の
    # `Source=File`固定の兄弟セレクタのうち、`StartOfDocument`/`EndOfDocument`の2件のみ
    # python-docxで再現可能(ブックマーク相対・テキスト相対・クリップボードソースは
    # `pad_action_lib.word_actions.insert_image_to_word()`側で`NotImplementedError`)。
    _WORD_INSERT_IMAGE_MODE_BY_ACTION_NAME = {
        "Word.InsertImageToWord.InsertImageDocumentStartFromFile": "StartOfDocument",
        "Word.InsertImageToWord.InsertImageDocumentEndFromFile": "EndOfDocument",
    }
    insert_image_mode = _WORD_INSERT_IMAGE_MODE_BY_ACTION_NAME.get(action_id)
    if insert_image_mode is not None:
        instance = safe_render(p.get("Instance"))
        path = safe_render(p.get("Path"))
        if instance is None or path is None:
            return None
        return [
            f"{prefix}word_actions.insert_image_to_word({instance}, {path}, "
            f"insert_image_mode={insert_image_mode!r})"
        ]

    return None
