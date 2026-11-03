"""UI要素リポジトリJSON(`# [ControlRepository][PowerAutomateDesktop]`節)のパース。

PADのクリップボードコピーで、フロー(サブフロー)内のアクション群を一括選択してコピーすると、
クリップボードテキストの末尾に`# [ControlRepository][PowerAutomateDesktop]`という区切り行に
続けて、参照先のUI要素リポジトリ全体(`appmask`シンボルの中身)がJSONとしてまるごと含まれる
(知見44で実機確認済み)。`pad_dsl`側のDSLテキスト解析とは完全に独立したフォーマットであり、
このモジュールは`pad_dsl`パッケージの型に一切依存しない。
"""
from __future__ import annotations

import json
from typing import Any

from .types import ControlRepositoryEntry, ControlRepositorySelectorElement

# design/dsl_format_findings.md 知見44(実機検証済み)——フロー内のアクション群を一括選択して
# コピーすると、クリップボードテキストの末尾にこの区切り行から始まるUI要素リポジトリ全体の
# JSONが同梱される。`pad_dsl.parse_dsl()`はこの行以降を通常のDSLレコード列から除外し
# (除外しないとJSON各行がデタラメな`RawRecord`の山になってしまう)、こちらの
# `parse_control_repository()`で別途パースする。
_CONTROL_REPOSITORY_MARKER = "# [ControlRepository][PowerAutomateDesktop]"


def _split_control_repository(text: str) -> tuple[str, str | None]:
    """`# [ControlRepository][PowerAutomateDesktop]`セクションをDSL本体から切り離す。

    区切り行が無ければ`(text, None)`を返す(知見38-43の、1〜4アクションだけを
    個別にコピーしたケース)。
    """
    idx = text.find(_CONTROL_REPOSITORY_MARKER)
    if idx == -1:
        return text, None
    return text[:idx], text[idx + len(_CONTROL_REPOSITORY_MARKER) :]


def _walk_repository_controls(node: dict[str, Any]) -> list[dict[str, Any]]:
    entries = [node] if "Selectors" in node else []
    for child in node.get("Controls") or []:
        entries.extend(_walk_repository_controls(child))
    return entries


def _build_control_repository_entry(node: dict[str, Any]) -> ControlRepositoryEntry:
    selectors: list[list[ControlRepositorySelectorElement]] = []
    for selector in node.get("Selectors") or []:
        path = [
            ControlRepositorySelectorElement(
                name=element.get("Name", ""),
                tag=element.get("Tag", ""),
                custom_value=element.get("CustomValue"),
                ignore=bool(element.get("Ignore", False)),
                attributes=element.get("Attributes") or [],
            )
            for element in selector.get("Elements") or []
        ]
        selectors.append(path)
    return ControlRepositoryEntry(
        name=node.get("Name", ""),
        element_type_name=node.get("ElementTypeName", ""),
        selectors=selectors,
    )


def parse_control_repository(text: str) -> dict[str, dict[str, ControlRepositoryEntry]]:
    """`# [ControlRepository][PowerAutomateDesktop]`セクション(知見44)をパースする。

    戻り値: `{シンボル名(例: "appmask"): {表示名(例: "Start Button"): ControlRepositoryEntry}}`。
    該当セクションが無い入力(単独アクションのコピー等)に対しては空の辞書を返す。
    """
    _, repo_text = _split_control_repository(text)
    if repo_text is None or not repo_text.strip():
        return {}

    data = json.loads(repo_text)
    result: dict[str, dict[str, ControlRepositoryEntry]] = {}
    for symbol in data.get("ControlRepositorySymbols") or []:
        symbol_name = symbol.get("Name", "")
        # `Repository`自体が文字列化されたJSON(二重エンコード)であることに注意。
        inner = json.loads(symbol["Repository"])
        entries: dict[str, ControlRepositoryEntry] = {}
        for screen in inner.get("Screens") or []:
            for node in _walk_repository_controls(screen):
                entry = _build_control_repository_entry(node)
                entries[entry.name] = entry
        result[symbol_name] = entries
    return result

