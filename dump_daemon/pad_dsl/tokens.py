"""PADクリップボードDSLの字句レベルのエスケープ・マスキング処理。

`$'''...'''`文字列リテラル・`/# ... #/`複数行コメント・`appmask['...']`UI要素参照は、
いずれも本文中に区切り文字(`'''`・`#/`・`[`/`]`)自体が現れうるため、素朴な正規表現の
非貪欲マッチでは壊れる。ここでは「対応するエスケープ解除規則」とセットで、各リテラルの
境界を検出する正規表現を提供する(実際にdsl_text中でプレースホルダに退避する処理は
`pad_dsl/__init__.py`の`parse_dsl()`が行う)。
"""
from __future__ import annotations

import re

_STRING_RE = re.compile(r"\$'''(.*?)'''", re.DOTALL)
_ESCAPE_RE = re.compile(r"\\\\|\\\"|\\'")
_COMMENT_RE = re.compile(r"/#((?:\\#/|\\\\|(?!#/).)*)#/", re.DOTALL)
_COMMENT_ESCAPE_RE = re.compile(r"\\(#/|\\)")
# design/dsl_format_findings.md 知見38(実機検証済み)——UI要素セレクタの実体(SelectorElement等の
# CSS風セレクタ文字列)はActionRecordのパラメータ値に直接は現れず、「UI要素」リポジトリへの
# 名前参照`appmask['<表示名>']`として埋め込まれる。表示名に空白を含みうる(`'Start Button'`等)ため、
# `$'''...'''`と同じくマスキングしてから行分割する必要がある。知見46(実機検証済み)で、対象が
# 別要素の子孫の場合は`['<祖先の表示名>']['<対象の表示名>']`のように`['...']`が複数連なり、
# 各セグメントの表示名自体に含まれる`'`は`\'`でエスケープされることが判明した
# (例: `appmask['Window \'Untitled - Notepad\'']['Document \'Text Editor\'']`)。
# `(?:\\.|[^'\\])*`でエスケープ済み文字(`\'`・`\\`等)をセグメント内の通常文字として許容し、
# `(?:\[...\])+`で1個以上の`['...']`セグメントの連なり全体を1つのUI要素参照としてマッチさせる。
_UI_ELEMENT_RE = re.compile(r"appmask(?:\['(?:\\.|[^'\\])*'\])+")
_UI_ELEMENT_SEGMENT_RE = re.compile(r"\['((?:\\.|[^'\\])*)'\]")
# design/dsl_format_findings.md 知見58・206(実機検証済み)——`UIAutomation.IfImage.
# ExistsOnScreen`の`Images`パラメータは`appmask[...]`とは別の、画像リポジトリへの名前参照
# `imgrepo['<表示名>']`を**さらに角括弧`[...]`で囲んだ**リスト リテラル構文
# (`[imgrepo['Image']]`)。`appmask[...]`と違い祖先パス(複数セグメントの連なり)は無く、
# `imgrepo['...']`は常に単一セグメント。「Find all images in the list」トグルの存在から
# カンマ区切りの複数要素(`[imgrepo['A'], imgrepo['B']]`)も許容すると推測されるが、
# 実機キャプチャで確認できたのは単一要素のケースのみ(知見58)——複数要素の区切り文字自体は
# 未確認のため、`,`区切りという想定はこの正規表現止まりの保守的な拡張であり、でっち上げた
# 意味論をcodegen側へは一切持ち込まない(`pad_codegen`は単一要素のケースのみ結線する)。
_IMAGE_REPOSITORY_LIST_RE = re.compile(
    r"\[\s*imgrepo(?:\['(?:\\.|[^'\\])*'\])+(?:\s*,\s*imgrepo(?:\['(?:\\.|[^'\\])*'\])+)*\s*\]"
)
_IMAGE_REPOSITORY_REF_RE = re.compile(r"imgrepo\['((?:\\.|[^'\\])*)'\]")
# design/dsl_format_findings.md 知見44(実機検証済み)——フロー内のアクション群を一括選択して
# コピーすると、クリップボードテキストの末尾にこの区切り行から始まるUI要素リポジトリ全体の
# JSONが同梱される。`parse_dsl()`はこの行以降を通常のDSLレコード列から除外し(除外しないと
# JSON各行がデタラメな`RawRecord`の山になってしまう)、`parse_control_repository()`で
# 別途パースする。
_CONTROL_REPOSITORY_MARKER = "# [ControlRepository][PowerAutomateDesktop]"


def _unescape(raw: str) -> str:
    """DSL文字列リテラル内の `\\"`→`"`・`\\'`→`'`・`\\\\`→`\\` を解除し、続けて
    `%%`→`%` を解除する(確定済みのエスケープ処理の逆操作。順序が重要——先にクォート/
    バックスラッシュのエスケープを解除し、その後で`%`の二重化を解除する)。
    """
    dequoted = _ESCAPE_RE.sub(lambda m: m.group(0)[-1], raw)
    return dequoted.replace("%%", "%")


def _unescape_ui_element_segment(raw: str) -> str:
    """`appmask['...']`の1セグメント内の`\\'`→`'`・`\\\\`→`\\`を解除する(知見46)。

    `_unescape()`と違い`%%`→`%`の解除は行わない——UI要素の表示名が`$'''...'''`形式の
    文字列リテラルと同じ経路で生成されているという確証は無く、`%`の二重化規則が
    適用される根拠が無いため、確認できた`\\'`/`\\\\`のエスケープ解除だけに留める。
    """
    return _ESCAPE_RE.sub(lambda m: m.group(0)[-1], raw)


def _unescape_comment(raw: str) -> str:
    """複数行コメント(`/# ... #/`)内の `\\#/`→`#/`、`\\\\`→`\\` を解除する
    (確定済みのコメントエスケープ処理の逆操作)。
    """
    return _COMMENT_ESCAPE_RE.sub(lambda m: m.group(1), raw)
