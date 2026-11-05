"""`ON ERROR <CaseName>`(知見36)の名前付きケースと、`pad_action_lib`が実装する
`[Throws("TagName")]`タグ例外クラス(知見73の結線で実際に使われる)を対応付ける。

design/dsl_format_findings.md 知見36で確認済みの通り、PADの名前付きエラーケースは
.NET/Pythonの例外**型**への対応表ではなく、アクションクラスごとに固定された文字列
タグそのもの。`pad_action_lib`の各モジュールはこのタグ名と同じクラス名で
`PadActionError`を継承した例外を定義している(`pad_action_lib/errors.py`参照)ため、
`ON ERROR <TagName>`のタグ名がこのクラス名のいずれかと一致する場合に限り、安全に
`except`節の型として使える。

**同じタグ名が複数のアクションファミリーで独立に定義されている場合**(例:
`FileNotFoundError`は`file_actions`/`compression_actions`/`cryptography_actions`に
それぞれ無関係な別クラスとして存在する)、どのファミリーのタグかをDSL側だけから
判別できないため、`except`はそれら全てを含むタプルにする——取りうる全ての実クラスを
安全側に広く捕捉するだけで、架空のクラスを作ることはしない。

未知のタグ名(いずれの`pad_action_lib`例外クラスとも一致しない——`Scripting`等、
`pad_action_lib`のスコープ外のアクションファミリーが使うタグも含む)は`None`を返す。
呼び出し元(`pad_codegen._generate_guarded`)はこれを「安全に変換できない」の意味で
受け取り、でっち上げた例外型を使わず既存の`# TODO`フォールバックへ倒す。
"""
from __future__ import annotations

import inspect

from ..pad_action_lib import (
    clipboard_actions,
    cmd_actions,
    compression_actions,
    cryptography_actions,
    database_actions,
    datetime_actions,
    excel_actions,
    file_actions,
    folder_actions,
    pdf_actions,
    powerpoint_actions,
    text_actions,
    web_actions,
    word_actions,
    xml_actions,
)
from ..pad_action_lib.errors import PadActionError

_MODULES = (
    clipboard_actions,
    cmd_actions,
    compression_actions,
    cryptography_actions,
    database_actions,
    datetime_actions,
    excel_actions,
    file_actions,
    folder_actions,
    pdf_actions,
    powerpoint_actions,
    text_actions,
    web_actions,
    word_actions,
    xml_actions,
)


def _short_module_name(module: object) -> str:
    return module.__name__.rsplit(".", 1)[-1]  # type: ignore[attr-defined]


def _collect_tag_references() -> dict[str, tuple[str, ...]]:
    registry: dict[str, list[str]] = {}
    for module in _MODULES:
        short_name = _short_module_name(module)
        for attr_name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and issubclass(obj, PadActionError)
                and obj is not PadActionError
                and obj.__module__ == module.__name__
            ):
                registry.setdefault(obj.__name__, []).append(f"{short_name}.{attr_name}")
    return {name: tuple(refs) for name, refs in registry.items()}


KNOWN_ERROR_TAG_REFS: dict[str, tuple[str, ...]] = _collect_tag_references()


def resolve_error_tag(tag_name: str) -> tuple[str, ...] | None:
    """`ON ERROR <tag_name>`の`except`節に使う型参照(複数あればタプル全部)。未知なら`None`。

    参照は`"{pad_action_libのモジュール短縮名}.{クラス名}"`の形の文字列(例:
    `"file_actions.CopyFileError"`)——生成コード側で`from dump_daemon.pad_action_lib import
    file_actions`済みの前提でそのまま埋め込める。既存の`generate_python()`の自動import検出
    (`f"{module_name}." in line`)がこの形をそのまま検出するため、追加のimport機構は不要。
    """
    return KNOWN_ERROR_TAG_REFS.get(tag_name)
