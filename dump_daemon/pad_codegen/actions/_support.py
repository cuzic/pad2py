"""Tier1/Tier2(`pad_action_lib`)系アクションのcodegen横断ヘルパー。

`pad_action_lib`の各関数はこのcodegenとは独立に実装された純粋関数レイヤーで、
`design/dsl_format_findings.md`で実機確認したaction_id・パラメータ名を使って
呼び出す側(この`pad_codegen.actions`配下の各ファミリーモジュール)がそれぞれ
結線する。

パーサーには知見72で確認した3つの既知の制限があったが、知見74で空のバックティック
文字列` `` `・空の`{ }`配列リテラルの2つは解消した(`pad_dsl.line_parser`が
それぞれ空文字列`""`・空リスト`[]`として正しく解釈する——いずれも実機データが
「空の場合のみ」確認済みで、非空の場合の表現は未確認のため対応しない)。
`P'<base64>'`形式のDPAPI保護値は、知見112で`DpapiSensitiveLiteral`型として
正しく解釈され`render_value()`が`cryptography_actions.decrypt_dpapi_sensitive_value()`
呼び出しへ結線するようになった(元の値を作成したWindowsユーザー自身が生成スクリプトを
実行する場合のみ実際に復号できる)。正当なPython識別子にならない(でっち上げた
壊れたPythonコードになる)`VarRef`だけが`safe_render()`で`None`を返し、呼び出し元は
その場で`generate()`から`None`を返して`generate_action()`の汎用`# TODO`フォールバックに
委ねる。
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


#: `CSVColumnsSeparator`列挙型(`Microsoft.Flow.RPA.Desktop.Modules.Text.Utilities.dll`)の
#: 各選択肢が実際にどの区切り文字になるかを、VM上で`CSVSeparator(CSVColumnsSeparator)`の
#: コンストラクタを直接呼び出して実機確認した結果(知見127)。`SystemDefault`はOSの
#: カルチャ依存の「リスト区切り文字」だが、確認したVMの環境では`Comma`と同じ`","`。
CSV_PREDEFINED_SEPARATOR_TO_DELIMITER = {
    "SystemDefault": ",",
    "Comma": ",",
    "Semicolon": ";",
    "Tab": "\t",
}

#: `Separator`列挙型(`File.Actions.dll`の`RenameFilesAction`、`DateTimeSeparator`/
#: `SequenceSeparator`で使う)の各選択肢が実際にどの文字になるかを、decompileした
#: `RenameFilesAction.GetSeparator()`の実装から確認した結果(知見154)。
RENAME_SEPARATOR_TO_CHAR = {
    "Nothing": "",
    "Space": " ",
    "Dash": "-",
    "Period": ".",
    "Underscore": "_",
}
