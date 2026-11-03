"""PADの「コピー&ペースト」クリップボードDSLのプロトタイプパーサー。

design/dsl_format_findings.md で実機検証した文法に基づく。対応している範囲:
- `ActionId Param: Value ... Output=> Var` 形式の一般アクション行(1個のアクションが
  複数の出力を持つ場合(知見26: `WindowTitle=> WindowTitle WindowInstance=> AutomationWindow`)、
  全ての束縛を`ActionRecord.output_vars`(パラメータ名→変数名の辞書)に保持する。
  `output_var`は後方互換のため最後に見つかったものを保持するだけなので、複数出力が
  ありうるアクションでは`output_vars`を参照すること)
- `$'''...'''`(複数行可)の文字列リテラル、および `\"`/`\'`/`\\` のエスケープ解除、
  および`%%`→`%`の解除(design/robin_language_source_findings.md——
  `InterpolatedStringAtom.ToString()`のソースで、リテラル部分は`EscapeForRobin(interpolated: true)`
  経由で常に`%`が`%%`に二重化されてから出力されることを確認した。`_STRING_RE`が捕捉する
  `$'''...'''`形式は全て`InterpolatedStringAtom`由来であり、この二重化を必ず受けているため、
  推測ではなくソース上確定した解除処理。以前は`\'`と`%%`の解除が未実装で、本文中にアポストロフィ
  (例: `it's`)を含むPADテキストが誤って`it\'s`のままPythonコードに混入するサイレントな
  バグがあった)
- `Namespace.Enum.Value` 形式の列挙値、`True`/`False` の真偽値
- `WAIT <seconds>` のようなベアキーワード行(action行のパターンに一致しない行は
  種別不明の `raw` レコードとしてそのまま保持し、サイレントに捨てない)

- `SET <VarName> TO <value>` 形式の変数代入(Set variableアクション。実機検証で
  `SET TestVar TO $'''...'''` の形を確認。`TO` は固定トークン)
- `IF <operand1> <operator> <operand2> THEN` / `END` 形式の条件分岐(実機検証で
  `IF TestVar = $'''hello''' THEN` ... `END` の形を確認。変数参照は `%...%` ではなく
  ベアトークンで表現される)
- ネスト構造は**4スペースインデント**で表現される(実機検証: `IF...THEN`内の
  アクションは先頭に4スペース)。各レコードは`indent`フィールド(0始まりの深さ)を持つ。

- `LOOP <VarName> FROM <start> TO <end> STEP <step>` / `END` 形式のカウントループ
  (実機検証で `LOOP LoopIndex FROM 1 TO 3 STEP 1` ... `END` の形を確認。`IF`と同じく
  ベアキーワード行+`END`で閉じる)
- `LOOP FOREACH <itemVar> IN <collection>` / `END` 形式のコレクション反復(実機検証で
  `LOOP FOREACH CurrentItem IN TestVar` ... `END` の形を確認)
- `LOOP WHILE (<operand1>) <operator> (<operand2>)` / `END` 形式の条件ループ(実機検証で
  `LOOP WHILE (LoopIndex) < (10)` ... `END` の形を確認。**`IF`と異なりオペランドが
  丸括弧で囲まれる**——同じ「First operand/Operator/Second operand」ダイアログ形状でも
  アクションの種類によってDSL表現が異なる例)

- `ELSE IF <operand1> <operator> <operand2> THEN` / `ELSE`(実機検証で
  `IF ... THEN` / `ELSE IF ... THEN` / `ELSE` / `END` の形を確認)。**重要**:
  `IF`/`ELSE IF`/`ELSE`は同じindent深さの**1つの構文**であり、`END`は
  個々のアームにではなく構文全体に1つだけ対応する(`IF`単体がネストしたブロックを
  開くわけではない)。`build_block_tree()`は`ConditionalNode(arms)`としてこれを表現する。
- `build_block_tree()`: `indent`情報を使って、フラットな`list[Record]`から
  ブロック木を組み立てる後処理(design/dsl_format_findings.md 知見7・9・11)。
  `LoopRecord`/`LoopForeachRecord`/`LoopWhileRecord`は単純な`BlockNode(header, body)`
  (本体がindent+1、対応する`END`が同じindentという1:1の構造)。`IfRecord`は
  `ElseIfRecord`/`ELSE`キーワードが同じindentで後続する限り1つの`ConditionalNode`に
  まとめ、最後に現れる`END`1つだけを構文全体の終端として消費する。

- `EXIT LOOP` / `NEXT LOOP`(実機検証。いずれも2トークンのベアキーワードで、
  `KeywordRecord(name="EXIT"/"NEXT", args=["LOOP"])`としてそのまま表現できる。
  `LOOP`系ブロックの本体内に通常のリーフとして現れるため、`build_block_tree()`に
  特別な対応は不要)
- 値の種別区別: `$'''...'''`由来の文字列リテラル、裸の数値トークン(`int`/`float`)、
  `Namespace.Enum.Value`形式の列挙値(`EnumRef`)、`appmask['<表示名>']`形式のUI要素
  リポジトリ参照(`UiElementRef`——**実機検証済み** design/dsl_format_findings.md 知見38。
  表示名に空白を含みうるため`$'''...'''`と同じくマスキングしてから行分割する)、
  それ以外の裸トークン(`VarRef`——変数参照)を区別して返す。例えば`IF TestVar = $'''hello''' THEN`
  では`TestVar`は`VarRef("TestVar")`、`hello`はPython文字列`"hello"`になる。コード生成時に
  「変数名としてそのまま出力するか」「文字列リテラルとして`repr()`するか」を判別するために
  必須の区別(両者とも字面上は識別子のように見えうるため、プレースホルダ経由かどうかでしか
  判別できない)。

- `IF <FuncName>(<arg1>, <arg2>, ...) THEN` / `ELSE IF <FuncName>(...) THEN` 形式の
  関数呼び出し条件(design/dsl_format_findings.md 知見18-2。`Contains`等のテキスト演算子は
  `<operand1> <operator> <operand2>`という中置記法ではなく、この別構文になる。実機検証は
  `Contains(InnerVar, $'''nested''', False) THEN`のみ。`IfFunctionRecord`/
  `ElseIfFunctionRecord`として構造化するが、`build_block_tree()`は`IfRecord`/`ElseIfRecord`
  と同様にこれらも`ConditionalNode`のアームとして扱う。`pad_codegen.py`はまだこの形の
  Python変換方法が未検証のため、遭遇すると明示的に例外を送出する——`Contains`系は
  2引数+真偽フラグ、`Is empty`系は引数の個数が異なると推測されるが未確認であり、
  安易に同じ形式だと仮定しない)

- `# <comment>` 形式の単一行コメント、および `/# ... #/` 形式の複数行コメント(**実機検証済み**
  design/dsl_format_findings.md 知見35——本文中に`#/`を含む3行コメントを実機で確認し、
  エスケープ(`#/`をバックスラッシュ付きの形に変換)を含めソース通りの挙動と完全に一致した)。
  design/robin_language_source_findings.md——`CommentStatement.ToString()`のソースで
  両方の形式と、複数行側の正確なエスケープ規則(`EscapeRobinComment`: `#/`とバックスラッシュの
  直前にバックスラッシュを挿入)を確認した。`$'''...'''`の複数行文字列マスキングと同じ手法(DOTALLで
  先に1トークンに退避してから行分割)を複数行コメントにも適用し、マスキングの順序は
  コメント→文字列(コメント本文に`$'''`等が含まれていても文字列リテラルとして
  誤認されないようにするため)。

- `IN`/`NOT IN`演算子(design/robin_language_source_findings.md——`ComparisonOperatorExtensions`の
  ソースで`NOT IN`が内部に空白を1つ持つ1つの文字列として直列化されることを確認した。
  `tokens = line.split()`で素朴に分割すると`"NOT"`/`"IN"`の2トークンになり、`IF`/`ELSE IF`/
  `LOOP WHILE`の固定位置での演算子読み取りがずれてしまうため、`_merge_not_in()`で
  トークン化の直後に1トークンへ結合してから既存の位置ベースロジックに渡している。
  実機でどのUI経由で使えるかはまだ未確認)

未対応(今後の実機確認が必要・構造的に大きな変更が必要なため今回は見送り): `AND`/`OR`/`XOR`
(`LogicalExpression`)・`NOT`前置演算子(`NotExpression`)による複合条件式、`+`/`-`/`*`/`/`/`mod`
(`ArithmeticExpression`)による算術式——いずれもソースコード上は`<operand> <keyword> <operand>`
という単純な中置(`NOT`は前置)記法であることを確認済みだが、現在の`IfRecord`等は
「オペランド1個+演算子1個+オペランド2個」という**フラットな**構造を前提にしており、
再帰的な式木を表現できない。安易に部分対応すると`A AND B OR C`のような式を誤って
解釈する恐れがあるため、構造自体の見直しが必要な別タスクとして持ち越す。

- `SWITCH <expr>` / `CASE <op> <value>` / `DEFAULT` / `END` 形式の多分岐。**実機検証済み**
  (design/dsl_format_findings.md 知見33): `SWITCH $'''TestVar'''` / `CASE = $'''a'''` /
  `DEFAULT` / `END`という実例を確認した。**重要**: 当初はANTLR文法上の`IF`/`ELSE IF`/`ELSE`との
  並列性から「`CASE`/`DEFAULT`は`SWITCH`と同じindentに並ぶ」と類推していたが、これは誤りだった。
  実際には`CASE`/`DEFAULT`は`SWITCH`より**1段深い**indentに並び、各アームの本体は**さらに1段深い**
  (`SWITCH`→`CASE`の関係も`CASE`→本体の関係も、`LOOP`→本体と同じ「ヘッダーより1段深い」構造——
  二重に重なっている)。`END`だけは`SWITCH`と同じindent。`CASE`の演算子は`=`固定ではなく
  `_OPERATOR_MAP`の演算子一般がありうる(ソース上`SemiComparison.Operator`は`ComparisonOperator?`
  型)。

`ON ERROR [<CaseName>]` / `END`(**実機検証済み** design/dsl_format_findings.md 知見34・36)。
直前の文を保護するエラーハンドラで、`OnErrorRecord`/`OnErrorNode`/`GuardedNode`として実装
済み。名前無しcatch-all・名前付きケース(`ON ERROR <CaseName>`)のいずれも実機確認済みで、
複数アームが区切り無しに連続しうる(`SwitchNode`のCASE/DEFAULTと同じ構造)。他の全ブロック
構文と異なり、本体のindentはヘッダー自身と同じ。`REPEAT ACTION`は実機検証済み(知見37)。

`BLOCK` [`<Name>`] / `ON BLOCK ERROR [<CaseName>]` / `END`(**実機検証済み**
design/dsl_format_findings.md 知見40)。PADの「On block error」アクションをフローに追加
すると、複数アクションをまとめる無名の`BLOCK`で自動的にラップされる。`BlockRecord`/
`BlockNode`として表現し、`ON BLOCK ERROR`は`ON ERROR`と全く同じ構造(本体がヘッダーと
同じindent、複数アーム、末尾に共有の`END`)なので`OnErrorNode`/`GuardedNode`をそのまま
再利用する(保護対象は直前のアクションではなく`BlockNode`全体)。本体内の`NEXT ACTION`も
実機確認済み(`KeywordRecord(name="NEXT", args=["ACTION"])`としてそのまま表現でき、
追加実装は不要だった)。名前付きBLOCK・名前付き`ON BLOCK ERROR <CaseName>`・ON BLOCK ERROR
を伴わない素のBLOCKは、いずれも実機では未確認のまま(既存の確認済みパターンからの類推で
実装)。

**UI要素セレクタの実体(`# [ControlRepository][PowerAutomateDesktop]`セクション、
design/dsl_format_findings.md 知見44で実機確認済み)**: 知見38で「DSLテキストには
`appmask['<表示名>']`という名前参照しか現れず、実セレクタは含まれない」としていたのは、
**1〜4個程度のアクションだけを個別にコピーしていた場合に限った話**だった。フロー
(サブフロー)内のアクション群を**一括選択してコピー**すると、クリップボードテキストの
末尾に`# [ControlRepository][PowerAutomateDesktop]`という区切り行に続けて、参照先の
UI要素リポジトリ全体(`appmask`シンボルの中身)がJSONとしてまるごと含まれる。
`parse_dsl()`はこのセクションを(通常のDSLレコード列には含めず)自動的に読み飛ばし、
`parse_control_repository()`で別途パースできる。ただし今回実機確認できた実例は
Windowsタスクバーの「Start Button」という特殊ケース(`CustomValue: ":startbutton"`という
PAD独自の予約済み擬似セレクタで、通常の`Attributes`配列は空)のみで、**一般的なアプリ内
コントロールの`Attributes`配列がどう埋まるかは未確認のまま**(`pad_codegen.py`側での
実際のpywinautoセレクタ生成への配線は、確証が得られるまで見送っている)。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

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
# design/dsl_format_findings.md 知見44(実機検証済み)——フロー内のアクション群を一括選択して
# コピーすると、クリップボードテキストの末尾にこの区切り行から始まるUI要素リポジトリ全体の
# JSONが同梱される。`parse_dsl()`はこの行以降を通常のDSLレコード列から除外し(除外しないと
# JSON各行がデタラメな`RawRecord`の山になってしまう)、`parse_control_repository()`で
# 別途パースする。
_CONTROL_REPOSITORY_MARKER = "# [ControlRepository][PowerAutomateDesktop]"


def _unescape(raw: str) -> str:
    """DSL文字列リテラル内の `\\"`→`"`・`\\'`→`'`・`\\\\`→`\\` を解除し、続けて
    `%%`→`%` を解除する(`InterpolatedStringAtom.ToString()`のソースで確認した
    `EscapeForRobin(interpolated: true)`の逆操作。順序が重要——先にクォート/
    バックスラッシュのエスケープを解除し、その後で`%`の二重化を解除する)。
    """
    dequoted = _ESCAPE_RE.sub(lambda m: m.group(0)[-1], raw)
    return dequoted.replace("%%", "%")


def _unescape_ui_element_segment(raw: str) -> str:
    """`appmask['...']`の1セグメント内の`\\'`→`'`・`\\\\`→`\\`を解除する(知見46)。

    `_unescape()`と違い`%%`→`%`の解除は行わない——UI要素の表示名が`$'''...'''`の
    `InterpolatedStringAtom`由来という確証は無く、`%`の二重化規則が適用される根拠が
    無いため、確認できた`\\'`/`\\\\`のエスケープ解除だけに留める。
    """
    return _ESCAPE_RE.sub(lambda m: m.group(0)[-1], raw)


def _unescape_comment(raw: str) -> str:
    """複数行コメント(`/# ... #/`)内の `\\#/`→`#/`、`\\\\`→`\\` を解除する
    (`CommentStatement.ToString()`が呼ぶ`EscapeRobinComment`の逆操作)。
    """
    return _COMMENT_ESCAPE_RE.sub(lambda m: m.group(1), raw)


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
class EnumRef:
    """`Namespace.Enum.Value`形式(例: `Display.Icon.None`)の列挙値を表すマーカー型。

    ドット区切りの完全修飾名という見た目でPAD変数参照(ドットを含まない裸識別子)と
    区別できるため、`VarRef`とは別の型にしている。

    **既知の未解決の曖昧性**(design/robin_language_source_findings.md):
    `Variable.ToString()`のソースで、PADの変数参照自体にも`.Name`という
    ドット区切りの「トレーラ」(配列/カスタムオブジェクトのプロパティアクセス、例:
    `MyDataTable.Rows`)が存在しうることを確認した。この形はテキスト上
    `Namespace.Enum.Value`と完全に同じ見た目になるため、`_DOTTED_RE`だけでは
    区別できない。これまでの実機データにトレーラ付き変数参照の実例が無いため、
    現状は全てのドット区切りトークンを`EnumRef`として扱っているが、これは
    トレーラ付き変数が実在する場合に誤分類する可能性がある未解決のギャップ。
    """

    value: str


@dataclass(frozen=True)
class UiElementRef:
    """`appmask['<表示名>']`形式のUI要素リポジトリ参照(**実機検証済み**——
    design/dsl_format_findings.md 知見38)。`Click UI element in window`のような
    「By window UI element」系アクションの`Element`パラメータに現れる。選択済みUI要素の
    CSS風セレクタ文字列(`SelectorElement`等、design/robin_language_source_findings.md参照)
    自体はこの参照の先(UI要素リポジトリ側)にあり、ActionRecordのパラメータ値には
    **表示名への参照だけ**が直接埋め込まれる——以前の調査で解明したセレクタ文字列の
    フォーマットは、リポジトリ内部の格納形式であり、DSLテキスト上の直接の値ではなかった。

    対象要素が別のウィンドウ/要素の子孫である場合、`appmask['<親の表示名>']['<対象の表示名>']`
    のように`['...']`が複数連なり、祖先から対象までのパスを表す(**実機検証済み**——
    design/dsl_format_findings.md 知見46)。各セグメントの表示名自体に`'`を含みうる場合は
    `\\'`でエスケープされる(例: `appmask['Window \\'Untitled - Notepad\\'']['Document \\'Text Editor\\'']`)。
    `path`は祖先から対象までの表示名のタプル、`name`はそのうち対象(末尾)の表示名。
    """

    path: tuple[str, ...]

    @property
    def name(self) -> str:
        return self.path[-1]


_DOTTED_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")
_INT_RE = re.compile(r"-?\d+")
_FLOAT_RE = re.compile(r"-?\d+\.\d+")
_FUNC_COND_RE = re.compile(r"^(IF|ELSE IF) ([A-Za-z_][A-Za-z0-9_]*)\((.*)\) THEN$")
# design/dsl_format_findings.md 知見50(実機検証済み)——`[WaitAction]`カテゴリ(`Wait for window`等)は
# 単純な`WAIT <seconds>`キーワードとは全く別の構文で、`WAIT (<ActionId> <Param>: <Value> ...) FOR <秒数>`
# という、丸括弧で囲んだアクション呼び出し風の式を伴う。例:
# `WAIT (UIAutomation.WaitForWindow.ToOpen Window: appmask['...'] FocusWindow: False) FOR 5`
_WAIT_ACTION_RE = re.compile(r"^WAIT \((.+)\) FOR (.+)$")


@dataclass
class ActionRecord:
    action_id: str
    params: dict[str, Any] = field(default_factory=dict)
    output_var: str | None = None
    output_vars: dict[str, str] = field(default_factory=dict)
    indent: int = 0


@dataclass
class KeywordRecord:
    name: str
    args: list[str] = field(default_factory=list)
    indent: int = 0


@dataclass
class WaitActionRecord:
    """`WAIT (<ActionId> <Param>: <Value> ...) FOR <秒数>`形式(**実機検証済み**——
    design/dsl_format_findings.md 知見50)。`[WaitAction]`カテゴリ(`Wait for window`等、
    design/robin_language_source_findings.mdで事前にソースから発見していたカテゴリ)の
    実際のDSL表現。単純な`WAIT <seconds>`キーワード(`KeywordRecord`)とは別構文——`ActionRecord`
    と同じ`Param: Value`形式のパラメータを丸括弧で包み、末尾に`FOR <タイムアウト秒数>`が付く。
    """

    action_id: str
    params: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: Any = None
    indent: int = 0


@dataclass
class SetVariableRecord:
    var_name: str
    value: Any
    indent: int = 0


@dataclass
class IfRecord:
    operand1: Any
    operator: str
    operand2: Any
    indent: int = 0


@dataclass
class ElseIfRecord:
    operand1: Any
    operator: str
    operand2: Any
    indent: int = 0


@dataclass
class IfFunctionRecord:
    """`IF Contains(a, b, False) THEN`のような関数呼び出し形式の条件(知見18-2)。"""

    function_name: str
    args: list[Any]
    indent: int = 0


@dataclass
class ElseIfFunctionRecord:
    function_name: str
    args: list[Any]
    indent: int = 0


@dataclass
class CommentRecord:
    """`# <comment>`形式の単一行コメント、および`/# ... #/`形式の複数行コメント
    (design/robin_language_source_findings.md——`CommentStatement.ToString()`の
    ソースコードで両方の構文を確認。複数行の場合`text`に改行が含まれる)。
    """

    text: str
    indent: int = 0


@dataclass
class LoopRecord:
    loop_var: str
    start: Any
    end: Any
    step: Any
    indent: int = 0


@dataclass
class LoopForeachRecord:
    item_var: str
    collection: Any
    indent: int = 0


@dataclass
class LoopWhileRecord:
    operand1: Any
    operator: str
    operand2: Any
    indent: int = 0


@dataclass
class SwitchRecord:
    """`SWITCH <expr>`(design/robin_language_source_findings.md——`SwitchStatement.ToString()`
    のソースで構文を確認。**実機検証済み**(design/dsl_format_findings.md 知見33): `CASE`/
    `DEFAULT`は`SWITCH`自身より1段深いindentに並び(`IF`/`ELSE IF`/`ELSE`のような「同じindentの
    兄弟」ではない)、各`CASE`/`DEFAULT`の本体はさらにもう1段深い——`LOOP`が本体を1段深くするのと
    同じ構造が、`SWITCH`→`CASE`の間にも`CASE`→本体の間にも、二重に重なっている)。
    """

    expression: Any
    indent: int = 0


@dataclass
class CaseRecord:
    """`CASE <operator> <value>`(**実機検証済み**: design/dsl_format_findings.md 知見33で
    `CASE = $'''a'''`という実例を確認した。`CaseStatement.SemiEvaluatableContext`の実装
    (`SemiComparison`)が`Operator`(nullable)+`RightOperand`を持つため、演算子が省略される
    ケースもソース上ありうるが、実機では常に演算子付きだった。`SwitchRecord`より1段深いindentに
    並ぶ)。
    """

    operator: str | None
    value: Any
    indent: int = 0


@dataclass
class CaseDefaultRecord:
    """`DEFAULT`(ベアキーワード、実機検証済み。`SwitchRecord`より1段深いindentに並ぶ
    catch-allアーム)。
    """

    indent: int = 0


@dataclass
class OnErrorRecord:
    """`ON ERROR`(`case_name=None`、名前無しのcatch-allケース)または
    `ON ERROR <CaseName>`(`case_name`に名前、個別のエラーケース)。いずれも実機検証済み
    (design/dsl_format_findings.md 知見34・36)。直前のアクション(または他の文)に対する
    エラーハンドラ群の1アームを開始する。**他の全ブロック構文(IF/LOOP/SWITCH)と異なり、
    本体のindentはヘッダー自身(および保護対象の文)と同じ**——唯一の例外的な構造。
    複数の`ON ERROR`アームが連続する場合、アーム間に区切り(ENDなど)は無く、
    構文全体の終端に`END`が1つだけ付く(`SwitchNode`のCASE/DEFAULTと同じ「複数アーム+
    末尾に1つのEND」という構造)。
    """

    case_name: str | None = None
    indent: int = 0


@dataclass
class BlockRecord:
    """`BLOCK`(`name=None`)または`BLOCK <Name>`(**実機検証済み**
    design/dsl_format_findings.md 知見40)。PADの「On block error」アクションをフローに
    追加すると自動生成される、複数アクションをまとめる無名(または名前付き)のグループ化
    構文。それ自体はIF/LOOPのような制御フローを持たず、`ON BLOCK ERROR`の保護対象範囲を
    区切るためだけに存在する(実機ではUI上「On block error」を単独で追加すると、常に
    このBLOCKで自動的にラップされた状態になる——素のBLOCKをON BLOCK ERROR無しで作る
    手段はUI上確認できていない)。
    """

    name: str | None = None
    indent: int = 0


@dataclass
class OnBlockErrorRecord:
    """`ON BLOCK ERROR`(`case_name=None`、名前無しcatch-all)または
    `ON BLOCK ERROR <CaseName>`。**実機検証済み**(design/dsl_format_findings.md 知見40)。

    `OnErrorRecord`の`BLOCK`版——同じ`ExceptionCaseStatement`/`ExceptionCaseDefaultStatement`
    クラスが`Type`プロパティ(`Statement`か`Block`か)に応じて`"ON ERROR"`/`"ON BLOCK ERROR"`の
    どちらを出力するかを切り替えているだけ(design/robin_language_source_findings.md)。
    構造も`OnErrorRecord`と同一: 直前の文(ここでは直前の`BlockRecord`開始ブロック全体)を
    保護し、本体のindentはヘッダー自身と同じ、複数アームが区切り無しに連続しうる。
    名前付きケース(`ON BLOCK ERROR <CaseName>`)は`ON ERROR <CaseName>`との類推で実装したが、
    実機では無名catch-allの形のみ確認済み(未検証の拡張)。
    """

    case_name: str | None = None
    indent: int = 0


@dataclass
class RawRecord:
    text: str
    indent: int = 0


Record = (
    ActionRecord
    | KeywordRecord
    | WaitActionRecord
    | SetVariableRecord
    | IfRecord
    | ElseIfRecord
    | IfFunctionRecord
    | ElseIfFunctionRecord
    | CommentRecord
    | LoopRecord
    | LoopForeachRecord
    | LoopWhileRecord
    | SwitchRecord
    | CaseRecord
    | CaseDefaultRecord
    | OnErrorRecord
    | BlockRecord
    | OnBlockErrorRecord
    | RawRecord
)

_SIMPLE_BLOCK_HEADER_TYPES = (LoopRecord, LoopForeachRecord, LoopWhileRecord)


@dataclass
class BlockNode:
    """単純なブロック構文(`LOOP`系/`BLOCK`)の開始レコードと、対応する`END`までの本体。"""

    header: LoopRecord | LoopForeachRecord | LoopWhileRecord | BlockRecord
    body: list[Node] = field(default_factory=list)


ConditionalArmHeader = IfRecord | ElseIfRecord | IfFunctionRecord | ElseIfFunctionRecord | KeywordRecord
_IF_HEADER_TYPES = (IfRecord, IfFunctionRecord)
_ELSEIF_HEADER_TYPES = (ElseIfRecord, ElseIfFunctionRecord)


@dataclass
class ConditionalNode:
    """`IF`/`ELSE IF`*/`ELSE`?/`END`全体を1つの構文単位として表す。

    各アームは`(header, body)`のタプル。`header`は`IfRecord`/`IfFunctionRecord`(先頭のみ)、
    `ElseIfRecord`/`ElseIfFunctionRecord`(0個以上)、または`KeywordRecord(name="ELSE")`
    (末尾に最大1個)。`END`は個々のアームにではなく構文全体に1つだけ対応するため、
    `ConditionalNode`は単一の`body`ではなく`arms`のリストを持つ。
    """

    arms: list[tuple[ConditionalArmHeader, list[Node]]] = field(default_factory=list)


SwitchArmHeader = CaseRecord | CaseDefaultRecord
_CASE_ARM_TYPES = (CaseRecord, CaseDefaultRecord)


@dataclass
class SwitchNode:
    """`SWITCH <expr>`/`CASE <op> <value>`*/`DEFAULT`?/`END`全体を1つの構文単位として表す。

    **実機検証済み**(design/dsl_format_findings.md 知見33)。`ConditionalNode`とは異なり、
    `CASE`/`DEFAULT`は`SWITCH`自身より1段深いindentに並び、各アームの本体はさらに1段深い
    (`SWITCH`→`CASE`の関係は`LOOP`→本体と同じ「ヘッダーより1段深い」構造で、`CASE`→その本体の
    関係でも同じ構造がもう一重重なっている)。当初はIF/ELSE IFと同じ「ヘッダー群が同じindentに
    並ぶ」構造だと類推していたが、実機確認の結果これは誤りだったため訂正した。
    """

    expression: Any
    arms: list[tuple[SwitchArmHeader, list[Node]]] = field(default_factory=list)


OnErrorArmHeader = OnErrorRecord | OnBlockErrorRecord


@dataclass
class OnErrorNode:
    """1個以上の`ON ERROR [CaseName]`または`ON BLOCK ERROR [CaseName]`アームと、それらを
    まとめて閉じる1つの`END`(実機検証済み——design/dsl_format_findings.md 知見34・36・40)。
    `SwitchNode`と同型(`arms: list[tuple[header, body]]`)——複数アームが連続する場合でも
    アーム間に区切りは無く、末尾に`END`が1つだけ付く。`REPEAT ACTION`は実機検証済み
    (知見37)、`NEXT ACTION`は`ON BLOCK ERROR`の本体内で実機確認済み(知見40、`KeywordRecord`
    として素通しされるだけで特別対応は不要)。単独では出現せず、常に`GuardedNode`経由で
    直前の文(`ON ERROR`の場合はアクション、`ON BLOCK ERROR`の場合は`BlockNode`)に紐付く。
    """

    arms: list[tuple[OnErrorArmHeader, list[Node]]] = field(default_factory=list)


@dataclass
class GuardedNode:
    """直前の文(`node`)に`ON ERROR`/`ON BLOCK ERROR`ハンドラ(`on_error`)が紐付いて
    いることを表す。

    `ON ERROR`/`ON BLOCK ERROR`はそれ自身が独立した文ではなく、DSL上では直前の文
    (またはBLOCK)のすぐ後ろ・同じindentに現れてそれを「保護」する
    (design/robin_language_source_findings.md——`StatementWithArguments.ToStringIgnoreMetadata()`
    が`ExceptionStatement`を末尾に改行区切りで連結している)。`build_block_tree()`は
    `ON ERROR`/`ON BLOCK ERROR`を独立したノードとしてbodyに追加せず、直前に追加済みの
    ノードをこれでラップし直す。
    """

    node: Node
    on_error: OnErrorNode


Node = Record | BlockNode | ConditionalNode | SwitchNode | GuardedNode


def build_block_tree(records: list[Record]) -> list[Node]:
    """`parse_dsl()`が返すフラットな`indent`付きレコード列から、ブロック木を組み立てる。

    design/dsl_format_findings.md 知見7・9・11で確認したルールに基づくスタック型の
    再帰下降パース:
    - `LOOP`系はブロック開始行と対応する`END`が同じindent深さ、本体だけがその1段内側。
    - `IF`/`ELSE IF`/`ELSE`は同じindent深さの1つの構文で、`END`は構文全体に1つだけ。
    - `SWITCH`/`CASE`/`DEFAULT`は実機検証済み(design/dsl_format_findings.md 知見33)で、
      `IF`/`ELSE IF`とは異なる構造だと判明した: `CASE`/`DEFAULT`は`SWITCH`より1段深いindentに
      並び、各アームの本体はさらに1段深い(`END`は`SWITCH`と同じindentに1つだけ)。
    対応する`END`が見つからないまま入力が尽きた場合(壊れたデータ等)は、例外を出さず
    そこまでの本体を返す。
    """

    pos = 0

    def is_end(rec: Record, level: int) -> bool:
        return isinstance(rec, KeywordRecord) and rec.name == "END" and rec.indent == level

    def parse_level(level: int, stop_at_on_error: bool = False) -> list[Node]:
        nonlocal pos
        body: list[Node] = []
        while pos < len(records):
            rec = records[pos]
            if rec.indent < level:
                break
            if stop_at_on_error and isinstance(rec, (OnErrorRecord, OnBlockErrorRecord)) and rec.indent == level:
                # ON ERRORの各アームの本体をパースしている最中。次のアーム(別の
                # ON ERROR見出し)に出会ったら、それを自分の本体に取り込まず
                # 呼び出し元(OnErrorRecordの処理)へ判断を戻す——SwitchNodeのCASE/DEFAULTと
                # 同じ「複数アーム+末尾に1つのEND」という構造(design/dsl_format_findings.md
                # 知見36)。
                break
            if is_end(rec, level):
                pos += 1
                return body
            pos += 1
            if isinstance(rec, _IF_HEADER_TYPES):
                arms: list[tuple[ConditionalArmHeader, list[Node]]] = [(rec, parse_level(level + 1))]
                while pos < len(records):
                    nxt = records[pos]
                    if nxt.indent != level:
                        break
                    if isinstance(nxt, _ELSEIF_HEADER_TYPES):
                        pos += 1
                        arms.append((nxt, parse_level(level + 1)))
                        continue
                    if isinstance(nxt, KeywordRecord) and nxt.name == "ELSE":
                        pos += 1
                        arms.append((nxt, parse_level(level + 1)))
                        break
                    break
                if pos < len(records) and is_end(records[pos], level):
                    pos += 1
                body.append(ConditionalNode(arms=arms))
            elif isinstance(rec, SwitchRecord):
                # 実機検証済み(design/dsl_format_findings.md 知見33): CASE/DEFAULTは
                # SWITCH自身よりindentが1段深く(level + 1)、各アームの本体はさらに1段深い
                # (level + 2)。SWITCH自身のENDだけはSWITCHと同じlevel。
                switch_arms: list[tuple[SwitchArmHeader, list[Node]]] = []
                while pos < len(records):
                    nxt = records[pos]
                    if nxt.indent != level + 1 or not isinstance(nxt, _CASE_ARM_TYPES):
                        break
                    pos += 1
                    switch_arms.append((nxt, parse_level(level + 2)))
                    if isinstance(nxt, CaseDefaultRecord):
                        break
                if pos < len(records) and is_end(records[pos], level):
                    pos += 1
                body.append(SwitchNode(expression=rec.expression, arms=switch_arms))
            elif isinstance(rec, _SIMPLE_BLOCK_HEADER_TYPES):
                block_body = parse_level(level + 1)
                # parse_level(level + 1)はこのブロック自身の閉じENDを消費できない
                # (そのENDのindentはlevelであり、level + 1ではないため)。ここで明示的に
                # 消費しないと、呼び出し元のwhileループがこのENDを「呼び出し元自身の終端」と
                # 誤認し、後続の兄弟要素を黙って切り捨ててしまう(実データで発覚したバグ)。
                if pos < len(records) and is_end(records[pos], level):
                    pos += 1
                body.append(BlockNode(header=rec, body=block_body))
            elif isinstance(rec, BlockRecord):
                # 実機検証済み(design/dsl_format_findings.md 知見40): `BLOCK`の本体は
                # LOOP等と同じくlevel + 1。本体の直後、BLOCK自身と同じlevelに区切り無しで
                # `ON BLOCK ERROR`が続く場合は、`OnErrorRecord`と全く同じ「複数アーム+
                # 末尾に1つのEND」構造でこのBLOCK全体を保護するため、GuardedNodeで
                # ラップし直す(保護対象はBlockNode全体)。この場合、OnErrorRecordと同じく
                # 最後のアームの本体パース自身がlevelのENDを消費済みなので、ここでの
                # 明示的な消費は不要。ON BLOCK ERRORが続かない場合(PADのUI上「On block
                # error」アクション経由でしかBLOCKを作る手段が無く、実機では未確認の経路)は
                # LOOP等と同じく自身のENDを明示的に消費する。
                block_body = parse_level(level + 1)
                block_node: Node = BlockNode(header=rec, body=block_body)
                if pos < len(records) and isinstance(records[pos], OnBlockErrorRecord) and records[pos].indent == level:
                    on_block_error_arms: list[tuple[OnErrorArmHeader, list[Node]]] = []
                    while pos < len(records):
                        nxt = records[pos]
                        if nxt.indent != level or not isinstance(nxt, OnBlockErrorRecord):
                            break
                        pos += 1
                        on_block_error_arms.append((nxt, parse_level(level, stop_at_on_error=True)))
                    block_node = GuardedNode(node=block_node, on_error=OnErrorNode(arms=on_block_error_arms))
                elif pos < len(records) and is_end(records[pos], level):
                    pos += 1
                body.append(block_node)
            elif isinstance(rec, OnErrorRecord):
                # 実機検証済み(design/dsl_format_findings.md 知見34・36): 各アームの本体は
                # `ON ERROR`自身と同じlevel。複数アーム(名前付きケース+catch-all等)が
                # 区切り無しに連続しうるため、`stop_at_on_error=True`で次のアーム見出しに
                # 出会ったら本体パースを止める。他のブロック構文と異なり、最後のアームの
                # 本体パース自身がlevelのENDを見つけて消費・終了するので、呼び出し元での
                # 明示的なEND消費は不要。`ON ERROR`は独立したノードではなく直前の文を
                # 保護するものなのでGuardedNodeで直前のノードをラップし直す。
                on_error_arms: list[tuple[OnErrorArmHeader, list[Node]]] = [
                    (rec, parse_level(level, stop_at_on_error=True))
                ]
                while pos < len(records):
                    nxt = records[pos]
                    if nxt.indent != level or not isinstance(nxt, OnErrorRecord):
                        break
                    pos += 1
                    on_error_arms.append((nxt, parse_level(level, stop_at_on_error=True)))
                on_error_node = OnErrorNode(arms=on_error_arms)
                if body:
                    body[-1] = GuardedNode(node=body[-1], on_error=on_error_node)
                else:
                    # ON ERRORが文の先頭(保護対象が無い)という壊れたデータ。
                    # 黙って捨てずraw相当として保持する。
                    body.append(on_error_node)
            elif isinstance(rec, OnBlockErrorRecord):
                # BLOCKを伴わない孤立したON BLOCK ERROR(壊れたデータ、または未対応の
                # 出現パターン)。OnErrorRecordの孤立ケースと同じく、直前のノードがあれば
                # それをGuardedNodeでラップし直し、無ければ黙って捨てずraw相当として保持する。
                orphan_arms: list[tuple[OnErrorArmHeader, list[Node]]] = [
                    (rec, parse_level(level, stop_at_on_error=True))
                ]
                while pos < len(records):
                    nxt = records[pos]
                    if nxt.indent != level or not isinstance(nxt, OnBlockErrorRecord):
                        break
                    pos += 1
                    orphan_arms.append((nxt, parse_level(level, stop_at_on_error=True)))
                orphan_node = OnErrorNode(arms=orphan_arms)
                if body:
                    body[-1] = GuardedNode(node=body[-1], on_error=orphan_node)
                else:
                    body.append(orphan_node)
            else:
                body.append(rec)
        return body

    return parse_level(0)


_ACTION_ID_RE = _DOTTED_RE
# "REPEAT"は design/dsl_format_findings.md 知見37(実機検証済み)の`REPEAT ACTION`用。
# "NEXT"は既存の`NEXT LOOP`と`NEXT ACTION`(同じくON ERRORの本体内で使える——ソース上
# `NextActionStatement.ToString()`が同じ`"NEXT ACTION"`を返すため、追加の実装は不要)の両方で使われる。
# "THROW"は design/dsl_format_findings.md 知見41(実機検証済み)の`THROW ERROR`用——
# `ON BLOCK ERROR`の「Throw error」を選ぶと本体に追加される2トークンのベアキーワード。
# "LABEL"/"GOTO"は design/dsl_format_findings.md 知見48(実機検証済み)——`Label`アクション
# (フロー制御カテゴリ)が`LABEL <名前>`、`ON ERROR`/`ON BLOCK ERROR`の「Exception handling
# mode」を「Go to label」にすると本体に`GOTO <名前>`が追加される。いずれも2トークンの
# ベアキーワードで、`REPEAT ACTION`等と同じ`KeywordRecord`機構でそのまま表現できる。
_KNOWN_KEYWORDS = {"WAIT", "END", "ELSE", "EXIT", "NEXT", "REPEAT", "THROW", "LABEL", "GOTO"}


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


def parse_dsl(text: str) -> list[Record]:
    text, _ = _split_control_repository(text)
    placeholders: dict[str, str | tuple[str, ...]] = {}

    def _stash_comment(m: re.Match[str]) -> str:
        key = f"\x00CMT{len(placeholders)}\x00"
        placeholders[key] = m.group(1)
        return key

    def _stash_string(m: re.Match[str]) -> str:
        key = f"\x00STR{len(placeholders)}\x00"
        placeholders[key] = m.group(1)
        return key

    def _stash_ui_element(m: re.Match[str]) -> str:
        key = f"\x00UIE{len(placeholders)}\x00"
        # 知見46: 各`['...']`セグメントを個別に取り出し、それぞれエスケープを解除してから
        # パス(祖先→対象の順のタプル)として保持する。
        placeholders[key] = tuple(
            _unescape_ui_element_segment(seg) for seg in _UI_ELEMENT_SEGMENT_RE.findall(m.group(0))
        )
        return key

    # コメントを先に退避する(本文中に`$'''`等が含まれていても文字列リテラルとして
    # 誤認されないようにするため)。UI要素参照(`appmask['<表示名>']`)も表示名に空白を
    # 含みうるため同様に退避する。
    masked = _COMMENT_RE.sub(_stash_comment, text)
    masked = _STRING_RE.sub(_stash_string, masked)
    masked = _UI_ELEMENT_RE.sub(_stash_ui_element, masked)

    records: list[Record] = []
    for raw_line in masked.split("\n"):
        if not raw_line.strip():
            continue
        stripped = raw_line.lstrip(" ")
        indent = (len(raw_line) - len(stripped)) // 4
        records.append(_parse_line(stripped.rstrip(), placeholders, indent))
    return records


def _strip_parens(token: str) -> str:
    """`LOOP WHILE`のオペランド(`(LoopIndex)`等)を囲む丸括弧を取り除く。"""
    if token.startswith("(") and token.endswith(")"):
        return token[1:-1]
    return token


def _merge_not_in(tokens: list[str]) -> list[str]:
    """隣接する`"NOT"`・`"IN"`の2トークンを1個の`"NOT IN"`トークンへ結合する。

    design/robin_language_source_findings.md——`ComparisonOperatorExtensions.ToString()`の
    ソースで、`ComparisonOperator.NotIn`は`"NOT IN"`(内部に空白を1つ持つ**1つの**文字列)として
    直列化されることを確認した。`IF`/`ELSE IF`/`LOOP WHILE`の演算子は固定位置の
    トークン(`tokens[2]`等)として読むため、空白区切りで2トークンになる`NOT IN`を
    そのままにすると以降の全トークン位置がずれてしまう(以前から既知だったギャップ)。
    ここで先に1トークンへ結合しておくことで、既存の固定位置ロジックを変更せずに対応できる。
    """
    merged: list[str] = []
    i = 0
    while i < len(tokens):
        if tokens[i] == "NOT" and i + 1 < len(tokens) and tokens[i + 1] == "IN":
            merged.append("NOT IN")
            i += 2
        else:
            merged.append(tokens[i])
            i += 1
    return merged


def _resolve_value(token: str, placeholders: dict[str, str | tuple[str, ...]]) -> Any:
    if token.startswith("\x00UIE") and token in placeholders:
        path = placeholders[token]
        assert isinstance(path, tuple)
        return UiElementRef(path)
    if token in placeholders:
        value = placeholders[token]
        assert isinstance(value, str)
        return _unescape(value)
    if token == "True":
        return True
    if token == "False":
        return False
    if _FLOAT_RE.fullmatch(token):
        return float(token)
    if _INT_RE.fullmatch(token):
        return int(token)
    if _DOTTED_RE.fullmatch(token):
        return EnumRef(token)
    return VarRef(token)


def _parse_line(line: str, placeholders: dict[str, str | tuple[str, ...]], indent: int = 0) -> Record:
    if line.startswith("\x00CMT") and line in placeholders:
        # `CommentStatement.ToString()`は常に`"/# " + escaped + "#/"`という形で
        # `/#`の直後に1文字の空白を固定で挿入する(コメント本文自体が空白で始まる
        # 場合でも区別なく追加される)。そのためここでは「空白なら剥がす」のような
        # 条件分岐ではなく、常に先頭1文字をデリミタの一部として取り除く。
        comment_raw = placeholders[line]
        assert isinstance(comment_raw, str)
        return CommentRecord(text=_unescape_comment(comment_raw[1:]), indent=indent)
    if line.startswith("# "):
        return CommentRecord(text=line[2:], indent=indent)
    if line == "#":
        return CommentRecord(text="", indent=indent)

    func_match = _FUNC_COND_RE.match(line)
    if func_match:
        keyword, func_name, args_str = func_match.groups()
        args = [_resolve_value(a.strip(), placeholders) for a in args_str.split(",")]
        if keyword == "IF":
            return IfFunctionRecord(function_name=func_name, args=args, indent=indent)
        return ElseIfFunctionRecord(function_name=func_name, args=args, indent=indent)

    wait_action_match = _WAIT_ACTION_RE.match(line)
    if wait_action_match:
        # design/dsl_format_findings.md 知見50(実機検証済み)。括弧の中身は`ActionRecord`と
        # 全く同じ`<ActionId> <Param>: <Value> ...`形式なので、既存のパラメータ解析ループを
        # そのまま再利用する。
        inner, duration_str = wait_action_match.groups()
        inner_tokens = inner.split()
        wait_record = WaitActionRecord(action_id=inner_tokens[0], indent=indent)
        i = 1
        while i < len(inner_tokens):
            tok = inner_tokens[i]
            if tok.endswith(":"):
                name = tok[:-1]
                if i + 1 >= len(inner_tokens):
                    break
                wait_record.params[name] = _resolve_value(inner_tokens[i + 1], placeholders)
                i += 2
                continue
            i += 1
        wait_record.timeout_seconds = _resolve_value(duration_str.strip(), placeholders)
        return wait_record

    tokens = _merge_not_in(line.split())
    first = tokens[0]

    if first == "SET" and len(tokens) >= 4 and tokens[2] == "TO":
        return SetVariableRecord(
            var_name=tokens[1],
            value=_resolve_value(tokens[3], placeholders),
            indent=indent,
        )

    if first == "ELSE" and len(tokens) >= 6 and tokens[1] == "IF" and tokens[-1] == "THEN":
        return ElseIfRecord(
            operand1=_resolve_value(tokens[2], placeholders),
            operator=tokens[3],
            operand2=_resolve_value(tokens[4], placeholders),
            indent=indent,
        )

    if first == "IF" and len(tokens) >= 5 and tokens[-1] == "THEN":
        return IfRecord(
            operand1=_resolve_value(tokens[1], placeholders),
            operator=tokens[2],
            operand2=_resolve_value(tokens[3], placeholders),
            indent=indent,
        )

    if first == "LOOP" and len(tokens) >= 5 and tokens[1] == "FOREACH" and tokens[3] == "IN":
        return LoopForeachRecord(
            item_var=tokens[2],
            collection=_resolve_value(tokens[4], placeholders),
            indent=indent,
        )

    if first == "LOOP" and len(tokens) >= 5 and tokens[1] == "WHILE":
        return LoopWhileRecord(
            operand1=_resolve_value(_strip_parens(tokens[2]), placeholders),
            operator=tokens[3],
            operand2=_resolve_value(_strip_parens(tokens[4]), placeholders),
            indent=indent,
        )

    if (
        first == "LOOP"
        and len(tokens) >= 8
        and tokens[2] == "FROM"
        and tokens[4] == "TO"
        and tokens[6] == "STEP"
    ):
        return LoopRecord(
            loop_var=tokens[1],
            start=_resolve_value(tokens[3], placeholders),
            end=_resolve_value(tokens[5], placeholders),
            step=_resolve_value(tokens[7], placeholders),
            indent=indent,
        )

    if first == "SWITCH" and len(tokens) == 2:
        return SwitchRecord(expression=_resolve_value(tokens[1], placeholders), indent=indent)

    if first == "CASE" and len(tokens) == 3:
        # 実機検証済み(design/dsl_format_findings.md 知見33): `CASE = $'''a'''`のように
        # 演算子が明示される(`SemiComparison`のソース通り)。
        return CaseRecord(
            operator=tokens[1],
            value=_resolve_value(tokens[2], placeholders),
            indent=indent,
        )

    if first == "CASE" and len(tokens) == 2:
        # ソース上`SemiComparison.Operator`はnullableなため、演算子が省略される形
        # (`SemiComparison.ToString()`が`RightOperand`だけを返す場合)も理論上ありうるが、
        # 実機では未確認。
        return CaseRecord(operator=None, value=_resolve_value(tokens[1], placeholders), indent=indent)

    if first == "DEFAULT" and len(tokens) == 1:
        return CaseDefaultRecord(indent=indent)

    if first == "ON" and len(tokens) == 2 and tokens[1] == "ERROR":
        # design/dsl_format_findings.md 知見34(実機検証済み、名前無しcatch-allケース)。
        return OnErrorRecord(case_name=None, indent=indent)

    if first == "ON" and len(tokens) == 3 and tokens[1] == "ERROR":
        # design/dsl_format_findings.md 知見36(実機検証済み、名前付きケース。例:
        # `ON ERROR RunPythonScriptError`)。
        return OnErrorRecord(case_name=tokens[2], indent=indent)

    if first == "ON" and len(tokens) == 3 and tokens[1] == "BLOCK" and tokens[2] == "ERROR":
        # design/dsl_format_findings.md 知見40(実機検証済み、名前無しcatch-all)。
        return OnBlockErrorRecord(case_name=None, indent=indent)

    if first == "ON" and len(tokens) == 4 and tokens[1] == "BLOCK" and tokens[2] == "ERROR":
        # `ON ERROR <CaseName>`(知見36)との類推による実装。named caseの実機確認は
        # まだ無い(未検証の拡張)。
        return OnBlockErrorRecord(case_name=tokens[3], indent=indent)

    if first == "BLOCK" and len(tokens) == 1:
        # design/dsl_format_findings.md 知見40(実機検証済み、無名BLOCK)。
        return BlockRecord(name=None, indent=indent)

    if first == "BLOCK" and len(tokens) == 2:
        # 名前付きBLOCKの実機確認はまだ無い(未検証の拡張)。
        return BlockRecord(name=tokens[1], indent=indent)

    if first in _KNOWN_KEYWORDS:
        return KeywordRecord(name=first, args=tokens[1:], indent=indent)

    if not _ACTION_ID_RE.match(first):
        return RawRecord(text=line, indent=indent)

    record = ActionRecord(action_id=first, indent=indent)
    i = 1
    while i < len(tokens):
        tok = tokens[i]
        if tok.endswith("=>"):
            # 出力パラメータ名(例: `ButtonPressed=>`の`ButtonPressed`)とVar名が同名の
            # ケースが多いが、必ずしも一致するとは限らない。1個のアクションが複数の出力を
            # 持つ場合(例: `WindowTitle=> WindowTitle WindowInstance=> AutomationWindow`)が
            # あるため、全ての束縛を output_vars(パラメータ名→変数名)に記録する。
            # output_var は後方互換のため最後に見つかったものを保持する(単一出力の
            # アクションではこれで十分だが、複数出力では output_vars を参照すること)。
            if i + 1 >= len(tokens):
                break
            param_name = tok[:-2]
            var_name = tokens[i + 1]
            record.output_var = var_name
            record.output_vars[param_name] = var_name
            i += 2
            continue
        if tok.endswith(":"):
            name = tok[:-1]
            if i + 1 >= len(tokens):
                break
            record.params[name] = _resolve_value(tokens[i + 1], placeholders)
            i += 2
            continue
        # 未知のトークン形式。パラメータ値が空白を含む等、今回の文法理解を超えるケース。
        i += 1

    return record
