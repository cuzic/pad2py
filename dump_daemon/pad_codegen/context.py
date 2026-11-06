"""codegen実行中に共有される不変の文脈情報(FCIS: 暗黙のグローバル状態を排除する)。

従来の`pad_codegen.py`は`_active_repository`というモジュールレベルの可変グローバル状態を
`generate_python()`が`try/finally`で設定・復元する設計だった(関数シグネチャだけでは
依存関係が読み取れず、再入不可能——モジュール自身のdocstringで「意図的なトレードオフ」と
明記されていた)。`CodegenContext`は同じ情報(UI要素リポジトリ)をイミュータブルな値として
明示的に引数で受け渡すための器で、このグローバル状態を廃止する。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..control_repository.types import ControlRepositoryEntry, ImageRepositoryEntry


@dataclass(frozen=True)
class CodegenContext:
    """`generate_python()`の呼び出し1回分のコード生成に必要な、外部から渡される情報。

    `repository`は`parse_control_repository()`の戻り値(知見44)。渡された場合、
    一部のアクションのTODOコメントにpywinautoセレクタの提案を付記したり、確認済みの
    パラメータの組み合わせに限り実行コードそのものを生成したりするのに使われる
    (`pad_codegen.selectors`参照)。

    `image_repository`は`parse_image_repository()`の戻り値(知見58・206)。
    `UIAutomation.IfImage.ExistsOnScreen`の`imgrepo['<表示名>']`参照を、実際にキャプチャ
    されたPNGバイナリ(`ImageRepositoryEntry`)へ解決するために使う(`pad_codegen.actions.
    conditions`参照)——`generate_python()`自体は純粋関数のままとし、実際にPNGファイルを
    ディスクへ書き出す副作用は呼び出し側(imperative shell、`pad2py_cli.py`)の責務とする。
    """

    repository: dict[str, dict[str, ControlRepositoryEntry]] = field(default_factory=dict)
    image_repository: dict[str, ImageRepositoryEntry] = field(default_factory=dict)


EMPTY_CONTEXT = CodegenContext()
