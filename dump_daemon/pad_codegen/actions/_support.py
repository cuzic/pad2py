"""Tier1/Tier2(`pad_action_lib`)系アクションのcodegen横断ヘルパー。

`pad_action_lib`の各関数はこのcodegenとは独立に実装された純粋関数レイヤーで、
`design/dsl_format_findings.md`で実機確認したaction_id・パラメータ名を使って
呼び出す側(この`pad_codegen.actions`配下の各ファミリーモジュール)がそれぞれ
結線する。

パーサーには知見72で確認した3つの既知の制限があり、該当パラメータは正当な
Python識別子にならない`VarRef`へのフォールバックになる(`P'<base64>'`形式の
DPAPI保護値、空のバックティック文字列` `` `、`{ }`配列リテラル)。でっち上げた
壊れたPythonコードを出力しないよう、`safe_render()`はこれらを検出したら`None`を
返し、呼び出し元はその場で`generate()`から`None`を返して`generate_action()`の
汎用`# TODO`フォールバックに委ねる。
"""
from __future__ import annotations

from ...pad_dsl import EnumRef, VarRef
from ..render import render_value


def safe_render(value: object) -> str | None:
    """`render_value()`のラッパー。識別子として安全でない`VarRef`には`None`を返す。"""
    if isinstance(value, VarRef) and not value.name.isidentifier():
        return None
    return render_value(value)


def enum_last(value: object) -> str | None:
    """`EnumRef`の最後のドット区切り要素(例: `Text.TrimOption.Both` → `"Both"`)。

    リテラルのenum値(PAD UIのドロップダウン選択、実機データでは常にこの形)以外
    (変数参照等、実機未確認)は`None`を返す。
    """
    if isinstance(value, EnumRef):
        return value.value.rsplit(".", 1)[-1]
    return None
