"""各モジュールの`[Throws("TagName")]`に対応する例外基底クラス。

`[Throws]`タグは.NET例外型への対応表ではなく、アクションクラスごとに固定された
文字列タグ(PAD DSL上`ON ERROR <TagName>`で照合される)。各action_lib モジュールは
タグ名と同じクラス名で`PadActionError`を継承した例外を定義する(例:
`StartIndexOrLengthOutOfRangeError`)。`[Throws]`タグが無く素の.NET例外がそのまま
伝播すると判明している箇所は、このクラスではなくPython標準の例外(`ValueError`等)を
そのまま投げることで、その非対称性自体を再現する。
"""
from __future__ import annotations


class PadActionError(Exception):
    """全ての`[Throws]`タグ付き例外の基底クラス。"""
