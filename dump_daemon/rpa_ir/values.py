"""複数のRPAツールが共有する「DSL上の値」の表現(`rpa_ir`の核、FCISのFunctional Core)。

このモジュールは純粋なデータ構造のみを持ち、いかなるパース処理にも依存しない。
元は`pad_dsl.types`に`VarRef`/`RawExpr`/`EnumRef`として個別に定義されていたが、
design/common_rpa_framework_roadmap.md 層1の方針に基づきここへ集約した
(`pad_dsl.types`は後方互換のため同名で再公開している——`from __future__ import
annotations`環境なので型チェック上も問題は無い)。

`Literal`は元々PAD側には存在しなかった型——PADは`VarRef`/`RawExpr`/`EnumRef`で
ラップされていない値を素のPython `str`/`int`/`float`/`bool`としてそのまま表現でき、
`Literal`相当のラッパーが無くても曖昧さが生じない(`pad_dsl.line_parser`がトークンの
見た目だけで`VarRef`/`EnumRef`/素のリテラルを判別できる)。一方UiPathの
`uipath_dsl.VbExpr`/`Literal`はいずれもPython上`str`型のテキストを保持するため、
「これは角括弧式(`VbExpr`)か、それとも角括弧で囲まれていない生のリテラルテキストか」を
型で区別する必要がある——`Literal`はその区別のための最小限のラッパー。両ツールの
将来の統合(`uipath_dsl.types`の移行、Phase 2で意図的に見送り中)に備えてここに置くが、
PAD側は現状このまま`Literal`を使わなくてよい(素のPython値で表現を続ける)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Literal:
    """角括弧/マーカー構文で囲まれていない生の値を明示するラッパー型。

    UiPathの`VbExpr`(角括弧式)と同じくPython上`str`型になりうる値を、型で
    明確に区別するために使う(design/uipath_xaml_findings.md 知見13: `x:TypeArguments`
    が単純型の場合、属性値やテキストノードが生のリテラルとしてそのまま直列化される)。
    """

    value: str


@dataclass(frozen=True)
class VarRef:
    """DSL上の裸トークンが変数参照であることを表すマーカー型。

    `$'''...'''`で囲まれていない裸トークンは、数値リテラル/`Namespace.Enum.Value`型の
    列挙値でなければ変数参照(実機検証: design/dsl_format_findings.md 知見6・9——UI上の
    `%VarName%`はDSL上`%`記号なしの裸トークンとして出力される)。文字列リテラル
    ("hello"等)と字面上は区別がつかないため、専用の型でラップして明示する。
    """

    name: str


@dataclass(frozen=True)
class RawExpr:
    """パーサーが完全には構造化しない(または構造化に失敗した)複合式のテキストを、
    失わずに保持するマーカー型。

    PAD側: `SET ... TO`の右辺が単一トークンに収まらない複合式(比較式を`AND`/`OR`/`XOR`/
    `NOT`で結合した論理式、`+`/`-`/`*`/`/`/`mod`による算術式)だったことを示す
    (design/dsl_format_findings.md 知見53、実機検証済み)。これらの演算子は予測通りの
    ベアキーワード(`AND`/`OR`/`XOR`/`NOT`は大文字に正規化される、`mod`は小文字のまま)
    としてDSLに出力される。演算子の優先順位(知見81)・`/`/`mod`の値の意味論
    (知見82・83)はいずれも実機確認済みで、`pad_codegen.render_expr_as_python()`が
    `tree`から実際のPython式を生成する。`text`はそれでも失わずに保持しており、構文解析に
    失敗した場合(`tree=None`)や`SET`式内の関数呼び出し(`FuncCall`、実機未確認の拡張)が
    現れる場合の安全なTODOフォールバックに使われる。

    UiPath側: `[...]`角括弧で囲まれたVB.NET式テキスト(design/uipath_xaml_findings.md
    知見2・13、旧`uipath_dsl.VbExpr`に相当)。角括弧を除いた中身の生テキストを保持する
    ——VB.NET式パーサー自体(`uipath_expr`)は別モジュールの範囲で、ここでは文字列の
    まま持ち越す。

    `tree`はDSLごとの式パーサー(PAD側`pad_expr`のLark文法/UiPath側`uipath_expr`)で
    構文解析した構造化表現で、解析に失敗した場合は`None`。
    """

    text: str
    tree: Any = None


@dataclass(frozen=True)
class EnumRef:
    """`Namespace.Enum.Value`形式(例: `Display.Icon.None`)の列挙値を表すマーカー型。

    ドット区切りの完全修飾名という見た目でPAD変数参照(ドットを含まない裸識別子)と
    区別できるため、`VarRef`とは別の型にしている。

    **既知の未解決の曖昧性**: PADの変数参照自体にも`.Name`という
    ドット区切りの「トレーラ」(配列/カスタムオブジェクトのプロパティアクセス、例:
    `MyDataTable.Rows`)が存在しうることが確認できている。この形はテキスト上
    `Namespace.Enum.Value`と完全に同じ見た目になるため、`_DOTTED_RE`だけでは
    区別できない。これまでの実機データにトレーラ付き変数参照の実例が無いため、
    現状は全てのドット区切りトークンを`EnumRef`として扱っているが、これは
    トレーラ付き変数が実在する場合に誤分類する可能性がある未解決のギャップ。
    """

    value: str


Value = Literal | VarRef | RawExpr | EnumRef
"""DSL上の値の表現(字句解析以後の全coreが参照する共有語彙)。各ツールはこれに
加えて固有の値型(例: PAD側の`DpapiSensitiveLiteral`/`UiElementRef`)を持ちうる。
"""
