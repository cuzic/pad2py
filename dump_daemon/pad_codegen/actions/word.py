"""`Word.*`のcodegen。

`pad_action_lib.word_actions`へ委譲する。知見80で、action_id文字列は全てPADデザイナー
自身の検索結果`TreeItem`のUIA `AutomationId`プロパティを直接読んで実機確認済み
(知見77と同じ経路)。パラメータ名は実機UIではなく、各`*Action`クラスの`InputArgument`/
`OutputArgument`属性宣言(ilspycmdによるdecompile、docs-local/pad_word_findings.md)から
読み取った値。

`Instance`(`WordInstanceHandle`への参照)は`excel.py`の`Instance`と同じく、PAD側では
不透明な参照だがPythonコード生成の観点では他の変数参照と同じ(特別な結線は不要)。

ライブWord COM専用の機能(`Visible`・保護パスワード・ページ単位読み取り・ブックマーク・
ワイルドカード検索)は`pad_action_lib.word_actions`側で最初からスコープ外
(docs-local/pad_word_findings.md)。`Visible`/`*ProtectionPassword`はpython-docx側に
対応概念が無く無視されるだけ(でっち上げた保護をかけない)なので、生成コードにも含めない。
`ReadMode`/`WriteMode`がPage/Bookmark系、`MatchWildCards`が既知の`True`リテラルの場合は、
でっち上げたコードを出力せず安全にTODOフォールバックへ委ねる。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import enum_last, safe_render


def _enum_arg(p: dict, name: str, default: str) -> str | None:
    """enumパラメータの値(省略時は`default`)を`repr()`済みのPython式として返す。"""
    if name in p:
        value = enum_last(p.get(name))
        if value is None:
            return None
        return repr(value)
    return repr(default)


def _optional_path_arg(p: dict, name: str) -> str | None:
    """`FileObject`系のオプション引数(省略時はPythonの`None`リテラル)を返す。"""
    if name in p:
        return safe_render(p.get(name))
    return "None"


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("Word."):
        return None
    prefix = INDENT * indent
    p = node.params

    if action_id == "Word.LaunchWord":
        if not node.output_var:
            return None
        mode = _enum_arg(p, "LaunchWordMode", "NewDocument")
        path = _optional_path_arg(p, "Path")
        read_only = safe_render(p.get("ReadOnly", False))
        if mode is None or path is None or read_only is None:
            return None
        return [
            f"{prefix}{node.output_var} = word_actions.launch_word("
            f"mode={mode}, path={path}, read_only={read_only})"
        ]

    if action_id == "Word.SaveWord":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        save_mode = _enum_arg(p, "SaveMode", "Save")
        document_format = _enum_arg(p, "DocumentFormat", "FromExtension")
        document_path = _optional_path_arg(p, "DocumentPath")
        if save_mode is None or document_format is None or document_path is None:
            return None
        return [
            f"{prefix}word_actions.save_word({instance}, save_mode={save_mode}, "
            f"document_format={document_format}, document_path={document_path})"
        ]

    if action_id == "Word.CloseWord":
        instance = safe_render(p.get("Instance"))
        if instance is None:
            return None
        close_mode = _enum_arg(p, "CloseMode", "DoNotSave")
        document_format = _enum_arg(p, "DocumentFormat", "FromExtension")
        document_path = _optional_path_arg(p, "DocumentPath")
        if close_mode is None or document_format is None or document_path is None:
            return None
        return [
            f"{prefix}word_actions.close_word({instance}, close_mode={close_mode}, "
            f"document_format={document_format}, document_path={document_path})"
        ]

    if action_id == "Word.ReadFromWord":
        instance = safe_render(p.get("Instance"))
        if instance is None or not node.output_var:
            return None
        if "ReadMode" in p:
            read_mode_literal = enum_last(p.get("ReadMode"))
            if read_mode_literal is None or read_mode_literal in ("Page", "Bookmark"):
                return None
            read_mode = repr(read_mode_literal)
        else:
            read_mode = repr("WholeDocument")
        pages = safe_render(p.get("Pages", "1"))
        bookmark = safe_render(p.get("Bookmark", ""))
        if pages is None or bookmark is None:
            return None
        return [
            f"{prefix}{node.output_var} = word_actions.read_from_word({instance}, "
            f"read_mode={read_mode}, pages={pages}, bookmark={bookmark})"
        ]

    if action_id == "Word.WriteToWord":
        instance = safe_render(p.get("Instance"))
        text = safe_render(p.get("Text"))
        if instance is None or text is None:
            return None
        if "WriteMode" in p:
            write_mode_literal = enum_last(p.get("WriteMode"))
            if write_mode_literal is None or write_mode_literal in (
                "StartOfBookmark",
                "EndOfBookmark",
            ):
                return None
            write_mode = repr(write_mode_literal)
        else:
            write_mode = repr("StartOfDocument")
        append_new_line = safe_render(p.get("AppendNewLine", False))
        bookmark = safe_render(p.get("Bookmark", ""))
        if append_new_line is None or bookmark is None:
            return None
        return [
            f"{prefix}word_actions.write_to_word({instance}, {text}, "
            f"append_new_line={append_new_line}, write_mode={write_mode}, bookmark={bookmark})"
        ]

    if action_id == "Word.FindAndReplaceWord":
        instance = safe_render(p.get("Instance"))
        text_to_find = safe_render(p.get("TextToFind"))
        text_to_replace_with = safe_render(p.get("TextToReplaceWith"))
        if instance is None or text_to_find is None or text_to_replace_with is None:
            return None
        raw_match_wild_cards = p.get("MatchWildCards", False)
        if raw_match_wild_cards is True:
            # 既知のTrueリテラルは常にNotImplementedErrorになる(Wordのワイルドカード構文は
            # 正規表現と等価ではなく、憶測で対応表を作らない方針のため実装していない)——
            # でっち上げたコードを出力せず安全にTODOへ倒す。
            return None
        all_matches = safe_render(p.get("AllMatches", False))
        match_case = safe_render(p.get("MatchCase", False))
        match_entire_word = safe_render(p.get("MatchEntireWord", False))
        match_wild_cards = safe_render(raw_match_wild_cards)
        if None in (all_matches, match_case, match_entire_word, match_wild_cards):
            return None
        return [
            f"{prefix}word_actions.find_and_replace_word({instance}, {text_to_find}, "
            f"{text_to_replace_with}, all_matches={all_matches}, match_case={match_case}, "
            f"match_entire_word={match_entire_word}, match_wild_cards={match_wild_cards})"
        ]

    return None
