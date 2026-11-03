"""UI要素リポジトリJSON(`# [ControlRepository][PowerAutomateDesktop]`節)の値の型。

PADクリップボードDSLのテキスト構文(`pad_dsl`)とは完全に独立したJSONフォーマットの
データ構造(知見44で実機確認済み)。`pad_dsl`側はこのJSON節をテキストから切り離すだけで
中身は一切パースしない(両coreの結合点は`_CONTROL_REPOSITORY_MARKER`という区切り文字列
定数のみ)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class ControlRepositorySelectorElement:
    """UI要素セレクタの1階層分の指定(`Elements`配列の1要素、知見44で実機確認済み)。

    `attributes`の内部シェイプ(キー名等)は実機で未確認(今回の実例は常に空配列)のため、
    でっち上げた型でラップせず生のJSON値(`list[dict[str, Any]]`)のまま保持する。
    """

    name: str
    tag: str
    custom_value: str | None
    ignore: bool
    attributes: list[dict[str, Any]]


@dataclass(frozen=True)
class ControlRepositoryEntry:
    """UI要素リポジトリの1エントリ(表示名1つ分)。

    `selectors`は「セレクタの候補」のリストで、各候補はルートから対象要素までの
    `ControlRepositorySelectorElement`のパス(知見44の実例では1階層のみ)。
    """

    name: str
    element_type_name: str
    selectors: list[list[ControlRepositorySelectorElement]]

