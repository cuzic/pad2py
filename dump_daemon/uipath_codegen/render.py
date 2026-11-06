"""`uipath_dsl.types.Expr`(`VbExpr`/`Literal`/`None`)をPython式のソース文字列へ
変換する。`pad_codegen.render`と同じ関心事の切り出し(値・条件式の文字列化、
副作用無し)。

**失敗モードの方針**(`pad_codegen`の`SetVariableRecord`/`IfActionRecord`
処理と同じ): この関数は「安全に変換できない」と判断した入力に対して
`NotImplementedError`を送出する。呼び出し側(`uipath_codegen/__init__.py`)が
これをどう扱うか(代入先なら`# TODO`+プレースホルダへ倒す、条件式なら
でっち上げた真偽値で制御フローを誤らせるよりコード生成全体を失敗させる)を
文脈ごとに決める。
"""
from __future__ import annotations

from dump_daemon.uipath_expr import (
    ArrayLiteral,
    BinOp,
    BoolLiteral,
    ChainedAccess,
    ExprNode,
    FuncCall,
    Ident,
    InterpolatedString,
    NothingLiteral,
    NumberLiteral,
    Paren,
    StringLiteral,
    UnaryOp,
    parse_vb_expr,
)

from ..uipath_dsl.types import Expr, Literal, VbExpr

# design/uipath_vb_expression_mapping.md で実機確認済み(知見32・36)の
# 型変換関数は全て、値そのものがVBとPythonで食い違いうる(知見42・45・52と
# 同じ種類の問題)ため、個別に`_render_func_call`内で処理する(下記参照)。
# 単純な名前変換だけで安全な型変換関数は無くなった(`CDbl`も知見52で
# `Nothing`/桁区切り文字列の食い違いが見つかり特別扱いに移行した)。

# `CDbl(x)`は.NETランタイム本体のソース(`Microsoft.VisualBasic.Core`の
# `Conversions.vb`、`dotnet/runtime`リポジトリ、VM不使用——公式ドキュメント
# だけでは確定できなかった知見46の残課題を、実際のランタイム実装
# ソースコードという「確度の高いソース」で確定、知見52参照)で以下を
# 確定した:
# - `CDbl(Nothing)`: `ToDouble(Object)`/`ToDouble(String)`いずれも
#   `If Value Is Nothing Then Return 0`——`0`を返す(例外にならない)。
# - `CDbl("1,234.5")`のような桁区切り文字列: 内部の`ParseDouble`が
#   `Double.Parse`に`NumberStyles.AllowThousands`を含むフラグを渡して
#   いるため、桁区切りのコンマは実際に受理される。
# - `CDbl(True)`: `ToDouble(Object)`の`Case TypeCode.Boolean`は
#   `Return CDbl(DirectCast(Value, Boolean))`——知見51で確定した
#   「Booleanの数値変換はTrue→-1」の一般規則がここにも適用される。
# Pythonの`float(None)`は`TypeError`、`float("1,234.5")`は桁区切りの
# コンマで`ValueError`になるため、単純な`float(x)`への変換のままでは
# 食い違う。桁区切りの妥当性(3桁ごとの正しいグループ化か)までは検証
# せず単純に除去する軽微な簡略化を許容する(でっち上げた検証ロジックより
# 単純な方を選んだ、既知の限界として下記に記録)。
# `CDbl("&H1A")`/`CInt("&H1A")`のような`&H`/`&O`16進・8進リテラル文字列
# (知見46・53で「軽微な既知の限界」として未対応のまま残していたもの)は、
# .NETランタイム本体のソース(`Microsoft.VisualBasic.CompilerServices.
# Utils.IsHexOrOctValue`、`dotnet/runtime`リポジトリの
# `Utils.LateBinder.vb`、`DoubleType.FromString`/`IntegerType.FromString`
# 両方がこの判定を`ParseDouble`より先に試す——VM不使用、知見67で解消)で
# 以下を確定した: 先頭の半角/全角空白(`chSpace`/`chIntlSpace`、Pythonの
# `str.strip()`は既定でどちらも空白として扱う)をスキップした後、`&`に
# 続けて`H`/`O`(大文字小文字区別無し)+1文字以上の数字が続く場合のみ、
# 通常の`ParseDouble`経由ではなく16進/8進として直接整数へ変換する——
# それ以外の文字(`&B`の2進等)が続く場合は`FormatException`になる(2進
# リテラル文字列は今回も対象外のまま、実例が無いため)。
VB_CDBL_HELPER_NAME = "_vb_cdbl"
VB_CDBL_HELPER_SOURCE = """\
def _vb_cdbl(x):
    if x is None:
        return 0.0
    if isinstance(x, bool):
        return -1.0 if x else 0.0
    if isinstance(x, str):
        s = x.strip()
        if len(s) >= 3 and s[0] == "&" and s[1].lower() in "ho":
            return float(int(s[2:], 16 if s[1].lower() == "h" else 8))
        return float(x.strip().replace(",", ""))
    return float(x)
"""

# `CStr(Double)`はVBの既定フォーマット("G"、丸め桁数15——mscorlib/Legacy
# ターゲット、知見30-6参照)に従い、整数値になる場合は小数点を省略する
# (`CStr(4.0)`は`"4.0"`ではなく`"4"`)。Microsoft Learn「CStr関数の戻り値」
# および「標準の数値書式指定文字列」(G書式)で確定済み(2026-11-05、
# VM不使用、公式ドキュメントで確定——知見46参照)。Pythonの`str(float)`は
# 整数値でも常に`.0`を残すため食い違う。`NaN`/`Infinity`/`-Infinity`は
# G書式とは独立に`Double.ToString()`が特別扱いする文字列
# ("NaN"/"Infinity"/"-Infinity")を返すため、`%g`書式より先に判定する。
# 生成コードはこのヘルパー関数を直接呼び出す形にする(`_render_func_call`の
# `cstr`、`_render_bin_op`の`&`の両方で使う——`&`もVBの文字列結合時に同じ
# 変換規則を使うため)。生成スクリプトへの実際の挿入は
# `uipath_codegen/__init__.py`の`_collect_imports`が使用時のみ行う
# (未使用時に余計なコードを増やさない既存方針、`pyperclip`/`Desktop`の
# import挿入と同じ仕組み)。
# `x is None`(`Nothing`)の場合は空文字列を返す(2026-11-05追補、知見56
# 参照)——.NETランタイム本体のソース(`Conversions.vb`の
# `ToString(Object)`)を確認すると`CStr(Nothing)`自体は実際には`Nothing`
# (nullのString参照)を返すが、これをそのままPythonの`str(x)`に通すと
# `"None"`という絶対にVBが出力しない文字列になってしまう(VBの文字列
# 結合`&`は`System.String.Concat`経由でnull文字列を自動的に空文字列へ
# 読み替えるため、`&`の文脈では最終的に空文字列と等価になる——
# `Operators.vb`の`ConcatenateObject`で確認)。「nullを厳密に伝播させる」
# より「`&`での最も一般的な実用シナリオで正しい結果になる」ことを優先し、
# 空文字列へ丸める近似を採用した(単独の`CStr(Nothing)`がダイアログ等
# 文字列以外の文脈でどう扱われるかまでは追跡しない、既知の限界)。
VB_CSTR_HELPER_NAME = "_vb_cstr"
VB_CSTR_HELPER_SOURCE = """\
def _vb_cstr(x):
    if x is None:
        return ""
    if isinstance(x, float):
        if x != x:
            return "NaN"
        if x == float("inf"):
            return "Infinity"
        if x == float("-inf"):
            return "-Infinity"
        return "%.15g" % x
    return str(x)
"""

# `=`/`<>`/`</`<=`/`>`/`>=`(比較演算子)がOption Strict Off下でObject型
# オペランドに適用する型変換規則(Microsoft Learn「Comparison Operators」
# の「Typeless Programming with Relational Comparison Operators」節、
# VM不使用・公式ドキュメントで確定、知見47参照)。片方が数値・片方が文字列
# なら文字列をDoubleへ変換してから数値比較し(変換不可ならVBは
# `InvalidCastException`——Pythonの`float()`も`ValueError`を送出するため
# 「静かに間違った結果を返さず失敗を伝播させる」方向で挙動が一致する)、
# `Nothing`は数値比較では`0`・文字列比較では空文字列として扱う。
# Pythonの`==`等は型をまたいだ暗黙の数値変換をしない(`"5" == 5`は
# 常に`False`)ため、単純な`==`/`<`等への変換のままでは、UiPathで多用される
# 緩い型(`GenericValue`/`Object`型変数)同士の比較が食い違いうる。
# `Boolean`→数値の変換も真っ先に行う(Microsoft Learn「Boolean Data
# Type」「When Visual Basic converts Boolean values to numeric types,
# False becomes 0 and True becomes -1」と明記——VM不使用・公式ドキュメント
# で確定、知見51参照。Pythonの`bool`は`int`のサブクラスで`True`は`1`
# 相当のため、変換無しでは符号が逆になる)。
# 知見68: `_vb_cmp`/`_vb_add`/`_vb_num`/`_vb_div`/`_vb_mod`はいずれも
# 文字列オペランドを`float(x)`で素朴にDoubleへ変換していたが、.NET
# ランタイム本体のソース(`Operators.vb`の`AddObject`/`SubtractObject`/
# `MultiplyObject`/`DivideObject`/`ModObject`/`CompareObjectEqual`等、
# 知見54・59と同じファイル)を確認したところ、文字列オペランドの変換は
# いずれも`CDbl(Convert.ToString(x))`——知見67で`&H`/`&O`16進・8進
# リテラル文字列対応を追加した、まさに同じ`Conversions.ToDouble`経路
# だった。つまり`"&H1A" + 1`/`"&H1A" = 26`のような式も実機では16進
# リテラルとして解釈される——知見67はCDbl/CInt/CBool(型変換関数)のみを
# 対象にしていたが、演算子ディスパッチャ側にも同じ変換経路が使われている
# ため同じ修正が必要だった(VM不使用、`gh api`で取得済みの`Operators.vb`
# を再確認して発見)。各ヘルパーに局所関数`_s2f`(string-to-float、
# `_vb_cdbl`/知見67と同じ判定ロジック)を追加——`_collect_imports`が
# 生成コードに文字通り現れるヘルパー名だけを検知する仕組み上、
# `_vb_cdbl`を直接呼ぶ構造には出来ない(知見50の`_vb_div`が`_vb_num`に
# 依存しない自己完結設計を選んだ理由と同じ)ため、各ヘルパー内に同じ
# ロジックを複製する。
VB_CMP_HELPER_NAME = "_vb_cmp"
VB_CMP_HELPER_SOURCE = """\
def _vb_cmp(a, b):
    def _vb_is_num(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool)
    def _s2f(s):
        if len(s) >= 3 and s[0] == "&" and s[1].lower() in "ho":
            return float(int(s[2:], 16 if s[1].lower() == "h" else 8))
        return float(s)
    if isinstance(a, bool):
        a = -1 if a else 0
    if isinstance(b, bool):
        b = -1 if b else 0
    if a is None and _vb_is_num(b):
        a = 0
    elif b is None and _vb_is_num(a):
        b = 0
    elif a is None and isinstance(b, str):
        a = ""
    elif b is None and isinstance(a, str):
        b = ""
    if _vb_is_num(a) and isinstance(b, str):
        b = _s2f(b)
    elif isinstance(a, str) and _vb_is_num(b):
        a = _s2f(a)
    return (a, b)
"""

# `+`演算子の型混在ディスパッチ規則(Microsoft Learn「+ Operator」の
# Remarks節、VM不使用・公式ドキュメントで確定、知見48参照)。VBの`+`は
# 両方数値なら算術加算、両方文字列なら連結、**片方が数値・片方が文字列
# なら文字列をDoubleへ変換してから算術加算する**(`"34" + 6`は`40`——
# 連結ではなく加算になる、Microsoft公式の例そのもの)。`Nothing`は数値側
# との組では`0`、文字列側との組では`""`として扱われる。Pythonの`+`は
# str+intを`TypeError`で即座にクラッシュさせる(`_vb_cmp`/`_vb_cstr`の
# ケースのような「値は間違っているが動く」ではなく、単純な`+`変換の
# ままでは動かすら出来ない、より重大な問題)。
# `Nothing + Nothing`のみ特別——.NETランタイム本体のソース
# (`Operators.vb`の`AddObject`、知見54で発見した知見52と同じファイル群、
# 知見55参照)で`Empty + Empty`は`Boxed_ZeroInteger`(整数`0`)を返すと
# 確定した。知見48作成時は公式ドキュメントの「どちらかがNothingなら
# 空文字列として扱う」という一般則だけを根拠に`Nothing + Nothing`も`""`
# と推測していたが、実際には「両方Nothing」というこの1組だけ特別に
# 整数`0`になる例外ケースだった(でっち上げではなく実機のランタイム
# ソースで確定済み)。
VB_ADD_HELPER_NAME = "_vb_add"
VB_ADD_HELPER_SOURCE = """\
def _vb_add(a, b):
    def _vb_is_num(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool)
    def _s2f(s):
        if len(s) >= 3 and s[0] == "&" and s[1].lower() in "ho":
            return float(int(s[2:], 16 if s[1].lower() == "h" else 8))
        return float(s)
    if isinstance(a, bool):
        a = -1 if a else 0
    if isinstance(b, bool):
        b = -1 if b else 0
    if a is None and b is None:
        return 0
    if a is None:
        a = 0 if _vb_is_num(b) else ""
    elif b is None:
        b = 0 if _vb_is_num(a) else ""
    if _vb_is_num(a) and isinstance(b, str):
        b = _s2f(b)
    elif isinstance(a, str) and _vb_is_num(b):
        a = _s2f(a)
    return a + b
"""

# `-`/`*`/`/`は`+`と違って文字列同士の特別な意味(連結)を持たない
# 純粋な数値演算子(Microsoft Learn「- Operator」「* Operator」「/
# Operator」、いずれも「Supported Types: All numeric types」と明記し、
# 文字列を直接扱う記載は無い——VM不使用・公式ドキュメントで確定、知見49
# 参照)。`Option Strict Off`下では一般の暗黙変換規則により文字列が
# Doubleへ変換されてから演算される(変換不可なら実行時エラー)。
# `Nothing`は常に`0`として扱われる(3ページとも共通して明記)。Pythonの
# `-`/`*`/`/`は文字列や`None`を渡すと`TypeError`で即座にクラッシュする
# (知見48の`+`と同じ問題がこちらにも存在した)。
VB_NUM_HELPER_NAME = "_vb_num"
VB_NUM_HELPER_SOURCE = """\
def _vb_num(x):
    if isinstance(x, bool):
        return -1 if x else 0
    if x is None:
        return 0
    if isinstance(x, str):
        if len(x) >= 3 and x[0] == "&" and x[1].lower() in "ho":
            return float(int(x[2:], 16 if x[1].lower() == "h" else 8))
        return float(x)
    return x
"""

# `/`(浮動小数点除算)はMicrosoft Learn「/ Operator」自身が「除算の前に
# 整数オペランドは全てDoubleへ拡張される」と明記しており、`/`の結果は
# オペランドの型によらず常にDouble相当になる(VM不使用、公式ドキュメントで
# 確定、知見50参照)。そのため`/`のゼロ除算は常にDouble方式(`expression2`
# が0なら`expression1`の符号に応じて`PositiveInfinity`/
# `NegativeInfinity`、両方0なら`NaN`——同ページ「Attempted Division by
# Zero」節で確定)になる、型に依存しない唯一の算術演算子。Pythonの`/`は
# ゼロ除算で`ZeroDivisionError`を送出して即座にクラッシュするため、単純な
# `/`変換のままでは動かない(`_vb_num`を経由しても解決しない、`/`固有の
# 問題)。`Mod`/`\`(`\`は整数除算、ゼロ除算は型依存で`DivideByZeroException`
# になりうる、知見49の残課題)は対象外——`_vb_num`に依存せず自己完結させる
# (`_collect_imports`は生成コードに文字通り現れるヘルパー名だけを検知する
# 単純な仕組みのため、`_vb_div`が内部で`_vb_num`を呼ぶ構造だと`_vb_num`の
# 注入漏れが起きる)。
VB_DIV_HELPER_NAME = "_vb_div"
VB_DIV_HELPER_SOURCE = """\
def _vb_div(a, b):
    def _s2f(s):
        if len(s) >= 3 and s[0] == "&" and s[1].lower() in "ho":
            return float(int(s[2:], 16 if s[1].lower() == "h" else 8))
        return float(s)
    if isinstance(a, bool):
        a = -1 if a else 0
    elif a is None:
        a = 0
    elif isinstance(a, str):
        a = _s2f(a)
    if isinstance(b, bool):
        b = -1 if b else 0
    elif b is None:
        b = 0
    elif isinstance(b, str):
        b = _s2f(b)
    if b == 0:
        if a == 0:
            return float("nan")
        return float("inf") if a > 0 else float("-inf")
    return a / b
"""

# `Mod`のゼロ除算は.NETランタイム本体のソース(`Operators.vb`の
# `ModObject`、知見52・53と同じ探索手法、知見54参照)で型依存と確定した。
# `ModObject`はオペランドの`TypeCode`(Integer系/Decimal/Single/Double)で
# 実際の`Mod`演算をディスパッチするだけで、ゼロ除数の特別扱いは無い
# ——結果としてCLRのネイティブ`Mod`演算そのものの挙動がそのまま出る:
# 整数系なら`DivideByZeroException`相当の例外、浮動小数点系
# (Single/Double)なら`NaN`(CLRの浮動小数点`Mod`命令の標準挙動、
# Microsoft Learn「Mod Operator」の「floating-point division returns
# Double.NaN」とも整合)。静的型情報を持たないため、`_vb_num()`後の
# Python実行時型(`int`→整数系の代理、`float`→浮動小数点系の代理)で
# 判定する——この代理方式自体、VBランタイムの`TypeCode`分岐と同じ発想
# (型で挙動を変える)であり、知見45の`Not`以来一貫して使ってきた設計。
VB_MOD_HELPER_NAME = "_vb_mod"
VB_MOD_HELPER_SOURCE = """\
def _vb_mod(a, b):
    def _s2f(s):
        if len(s) >= 3 and s[0] == "&" and s[1].lower() in "ho":
            return float(int(s[2:], 16 if s[1].lower() == "h" else 8))
        return float(s)
    if isinstance(a, bool):
        a = -1 if a else 0
    elif a is None:
        a = 0
    elif isinstance(a, str):
        a = _s2f(a)
    if isinstance(b, bool):
        b = -1 if b else 0
    elif b is None:
        b = 0
    elif isinstance(b, str):
        b = _s2f(b)
    if b == 0:
        if isinstance(a, float) or isinstance(b, float):
            return float("nan")
        raise ZeroDivisionError("Mod by zero (VB would raise DivideByZeroException)")
    return a - (b * int(a / b))
"""

# `And`/`Or`/`Xor`の`Nothing`オペランド処理(知見58の「でっち上げず
# 未対応のまま残す」としていた残課題を、`Operators.vb`の`AndObject`/
# `OrObject`/`XorObject`で型ごとの分岐を具体的に確認した上で解決、知見59
# 参照、VM不使用)。既存の`&`/`|`/`^`への単純な1対1変換(Pythonの`bool`が
# `int`のサブクラスであることを利用)は、両オペランドが実際に値を持つ
# 場合は引き続き正しい——問題は片方(または両方)が`Nothing`の場合のみ:
# - `And`: `Nothing`は他方がBooleanなら`False`(Boolean)、Integerなら
#   `0`(Integer)として扱われる(`AndObject`「Empty with Boolean:
#   Return False」「Empty with Int32: 常に0」で確認)。両方`Nothing`は
#   `0`(Integer、他の単項演算子と同じ`Boxed_ZeroInteger`パターン)。
# - `Or`/`Xor`: `Nothing`は常に`0`相当の単位元として働くため、結果は
#   **他方のオペランドをそのまま返す**(型も維持される——`OrObject`
#   「Empty with Int32: Return Right」、`XorObject`も同じパターン)。
#   両方`Nothing`は`0`(Integer)。
# 知見91: 知見89・90(単項`-`/`+`・`Not`)と全く同じ理由で、`And`/`Or`/
# `Xor`も両オペランドが非`Nothing`の場合に文字列を一切コンバートせず
# `a & b`等へそのまま渡していたため、`"5" And 3`のような式が
# `TypeError: unsupported operand type(s) for &: 'str' and 'int'`で
# クラッシュすると`exec()`で確認した。`Nothing`絡みの分岐(知見59、
# 上記コメント参照)は実機のランタイムソースで個別に確定済みのロジック
# のため変更せず、両オペランドが非`Nothing`の最終行(`a & b`等)にのみ
# 文字列コンバート(`_vb_num`+`round()`と同じ規則、`&H`/`&O`含む)を
# 局所関数`_s2i`として追加する——`_collect_imports`が生成コードに
# 文字通り現れるヘルパー名だけを検知する仕組み上、他のヘルパーを直接
# 呼ぶ構造にはできないため(知見50の`_vb_div`と同じ制約)。
VB_AND_HELPER_NAME = "_vb_and"
VB_AND_HELPER_SOURCE = """\
def _vb_and(a, b):
    def _s2i(s):
        if len(s) >= 3 and s[0] == "&" and s[1].lower() in "ho":
            return int(s[2:], 16 if s[1].lower() == "h" else 8)
        return round(float(s))
    if a is None and b is None:
        return 0
    if a is None:
        return False if isinstance(b, bool) else 0
    if b is None:
        return False if isinstance(a, bool) else 0
    if isinstance(a, str):
        a = _s2i(a)
    if isinstance(b, str):
        b = _s2i(b)
    return a & b
"""
VB_OR_HELPER_NAME = "_vb_or"
VB_OR_HELPER_SOURCE = """\
def _vb_or(a, b):
    def _s2i(s):
        if len(s) >= 3 and s[0] == "&" and s[1].lower() in "ho":
            return int(s[2:], 16 if s[1].lower() == "h" else 8)
        return round(float(s))
    if a is None and b is None:
        return 0
    if a is None:
        return b
    if b is None:
        return a
    if isinstance(a, str):
        a = _s2i(a)
    if isinstance(b, str):
        b = _s2i(b)
    return a | b
"""
VB_XOR_HELPER_NAME = "_vb_xor"
VB_XOR_HELPER_SOURCE = """\
def _vb_xor(a, b):
    def _s2i(s):
        if len(s) >= 3 and s[0] == "&" and s[1].lower() in "ho":
            return int(s[2:], 16 if s[1].lower() == "h" else 8)
        return round(float(s))
    if a is None and b is None:
        return 0
    if a is None:
        return b
    if b is None:
        return a
    if isinstance(a, str):
        a = _s2i(a)
    if isinstance(b, str):
        b = _s2i(b)
    return a ^ b
"""

# `AndAlso`/`OrElse`はVBの公式ドキュメント(Microsoft Learn「AndAlso
# Operator」)が「Visual Basic converts each operand as necessary to
# Boolean before evaluating the expression」と明記している通り、**両
# オペランドを評価前にBooleanへ変換し、結果も常にBoolean**になる
# (VM不使用、公式ドキュメントで確定、知見60参照)。単純な`(left) and
# (right)`/`(left) or (right)`への変換は、Pythonの`and`/`or`がBoolean
# 変換をせず**生のオペランド値をそのまま返す**ため食い違う(例:
# `0 AndAlso True`はVBでは`False`(Boolean)になるが、Pythonの
# `0 and True`は`0`(int)を返す——`CStr`で文字列化すると`"False"`対
# `"0"`という明確な違いになる)。`_vb_bool(x)`(`CBool`の文字列判定
# (`_vb_cbool_of_string_literal`)/`ParseDouble`の`NumberStyles.
# AllowThousands`(知見52)と同じ規則をランタイム版にしたもの)で各
# オペランドを明示的にBooleanへ変換してから、短絡評価自体はPython
# ネイティブの`and`/`or`に委ねる(`_vb_bool(...)`という関数呼び出し式を
# `and`/`or`で結ぶため、右辺の評価自体はPythonの通常の短絡評価規則で
# 正しくスキップされる——副作用のある式の二重評価/過剰評価は発生しない)。
VB_BOOL_HELPER_NAME = "_vb_bool"
VB_BOOL_HELPER_SOURCE = """\
def _vb_bool(x):
    if isinstance(x, bool):
        return x
    if x is None:
        return False
    if isinstance(x, str):
        normalized = x.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
        s = x.strip()
        if len(s) >= 3 and s[0] == "&" and s[1].lower() in "ho":
            return int(s[2:], 16 if s[1].lower() == "h" else 8) != 0
        return float(normalized.replace(",", "")) != 0
    return x != 0
"""

# design/uipath_vb_expression_mapping.md「確認済み演算子の変換上の注意点」
# (2026-11-05確定分): And/Or/Xorは両オペランドが実際に値を持つ場合は
# Pythonのビット演算子(&/|/^)への1対1変換で正しい(Pythonのboolがintの
# サブクラスであるため)——`Nothing`オペランドの処理は上記`_vb_and`/
# `_vb_or`/`_vb_xor`ヘルパー(知見59)に委ねる。
_BITWISE_OPS = {"and": VB_AND_HELPER_NAME, "or": VB_OR_HELPER_NAME, "xor": VB_XOR_HELPER_NAME}
_SHORT_CIRCUIT_OPS = {"andalso": "and", "orelse": "or"}
_COMPARISON_OPS = {
    "=": "==",
    "<>": "!=",
    "<": "<",
    ">": ">",
    "<=": "<=",
    ">=": ">=",
}


def _render_node(node: ExprNode) -> str:
    if isinstance(node, Ident):
        # 知見119: `IDENT`トークンの正規表現(ドット区切りを1トークンとして
        # 貪欲マッチ)の都合上、関数呼び出しを介さない素の変数へのメンバ
        # アクセス連鎖(`intCounter.ToString`等、`PacktPublishing/
        # Robotic-Process-Automation-Projects`の実機XAMLで発見)は文法上
        # `postfix`規則に到達せず常に`Ident`としてレクサに1トークンで
        # 吸収されてしまう——知見118の`ChainedAccess`修正だけでは
        # カバーできない別のケース。末尾セグメントが確認済みの安全な
        # メンバ名(`_CHAINED_PROPERTY_TRANSLATIONS`+`ToString`)の場合
        # のみ、ドットで分割して同じ変換を適用する——それ以外(`DateTime.
        # Now`等の静的クラス参照を含む)は末尾が対象メンバ名に一致しない
        # ため従来通り(無変換でそのまま)の挙動を変えない、安全な追加。
        if "." in node.name:
            prefix, _, last = node.name.rpartition(".")
            # 知見130: `Copy`(`DataTable.Copy`、括弧省略形)も同じ安全な
            # メンバ名の一覧に加える。
            if last == "ToString" or last == "Copy" or last in _CHAINED_PROPERTY_TRANSLATIONS:
                return _apply_chained_property(prefix, last)
        return node.name
    if isinstance(node, StringLiteral):
        return repr(node.value)
    if isinstance(node, NumberLiteral):
        return repr(node.value)
    if isinstance(node, BoolLiteral):
        return "True" if node.value else "False"
    if isinstance(node, NothingLiteral):
        return "None"
    if isinstance(node, ArrayLiteral):
        items = ", ".join(_render_node(i) for i in node.items)
        return f"[{items}]"
    if isinstance(node, InterpolatedString):
        return _render_interpolated_string(node.raw)
    if isinstance(node, Paren):
        return f"({_render_node(node.inner)})"
    if isinstance(node, UnaryOp):
        op = node.op.lower()
        if op == "not":
            # VBの`Not`はAnd/Or/Xorと同じ型依存の二重性質を持ち、Boolean
            # オペランドには論理否定、Integerオペランドにはビット反転
            # (2の補数)として働く(Microsoft Learn「Operator Precedence」
            # Logical and Bitwise Operators節)。実機(UiPath Studio Debug
            # File、Sub1.xaml、2026-11-05)で`Not 5`(Integer)を実行して
            # `-6`を確認——Pythonの`~5`と一致、`not 5`(=`False`)とは違う
            # (design/uipath_xaml_findings.md 知見45参照)。Pythonには
            # BooleanにもIntegerにも正しく働く単一演算子が無い(`~True`は
            # `-2`で論理否定と一致しない)ため、実行時にisinstanceで型を
            # 分岐するラムダを生成する。式は一度だけ評価する(副作用の
            # ある呼び出しが二重評価されないように)。
            #
            # 知見90: `Nothing`オペランドだけを`0`へ読み替えていたが
            # (知見58)、知見89(単項`-`/`+`)と全く同じ理由で文字列
            # オペランド(`CStr(Not "5")`等)は未対応のままで`~"5"`が
            # `TypeError: bad operand type for unary ~: 'str'`になる
            # ——実際に`exec()`して再現した。他の数値演算子と同じ
            # `_vb_num()`で文字列(`&H`/`&O`含む)/`Nothing`/`bool`を
            # 一貫してコンバートしてから`round()`で整数化する(`\`の
            # オペランド変換、知見54と同じ銀行丸め——Integerビット反転は
            # 整数値に対してのみ意味を持つため)。
            operand = _render_node(node.operand)
            return (
                "(lambda _x: (not _x) if isinstance(_x, bool) "
                f"else ~round({VB_NUM_HELPER_NAME}(_x)))({operand})"
            )
        if op in ("-", "+"):
            # 知見89: 単項`-`/`+`は`Nothing`オペランドだけを特別扱いして
            # いたが(知見58、`Operators.vb`の`NegateObject`/
            # `PlusObject`で`Case TypeCode.Empty: Return
            # Boxed_ZeroInteger`を確認)、文字列オペランド(数値文字列・
            # `&H`/`&O`16進8進リテラル文字列いずれも、知見49・68)は
            # 一切コンバートせず素の`-`/`+`を適用していたため
            # `TypeError: bad operand type for unary -: 'str'`で
            # クラッシュする——`CStr(-"5")`のような式で実際に再現した
            # (`"&H5"`のような16進リテラル文字列限定の問題ではなく、
            # 単純な数値文字列でも同じクラッシュを再現)。他の全ての
            # 数値演算子(`-`/`*`/`\`/`^`、知見49・68)と同じ`_vb_num()`
            # ヘルパーに統一して解消する——`_vb_num`は`bool`/`Nothing`/
            # 文字列(`&H`/`&O`含む)を一貫して数値へコンバートするため、
            # `operand`の参照が1回だけなので(以前の`Nothing`専用分岐が
            # 必要としていた、副作用の二重評価を避けるための`lambda`
            # ラップも不要になった)。
            operand = _render_node(node.operand)
            return f"{node.op}{VB_NUM_HELPER_NAME}({operand})"
        raise NotImplementedError(f"unsupported unary operator: {node.op!r}")
    if isinstance(node, FuncCall):
        return _render_func_call(node)
    if isinstance(node, ChainedAccess):
        return _render_chained_access(node)
    if isinstance(node, BinOp):
        return _render_bin_op(node)
    raise NotImplementedError(f"unsupported expression node: {node!r}")


# 知見118: `ChainedAccess`(関数呼び出し結果へのメンバ/メソッドアクセスの
# 連鎖、例: `in_Config("x").ToString.ToLower.Equals("yes")`)。確認済みの
# 安全な.NETメンバのみ対応し、未知のメンバは`# TODO`(呼び出し側の
# `_render_value_or_todo`/条件式の失敗伝播のいずれか)へ倒す——他の
# `_render_*`関数と同じ「でっち上げ回避」方針。`ToString`は`CStr`と同じ
# `VB_CSTR_HELPER_NAME`ヘルパーへ(design/uipath_vb_expression_mapping.md
# で`CStr`/`.ToString`を実質同等と整理済み)、`ToUpper`/`ToLower`/`Trim`は
# Python文字列メソッドへの直接の名前変換(いずれも.NET `String`型の
# 標準メソッドでPython `str`の対応メソッドと同じ意味論、Microsoft Learn/
# Python公式ドキュメントで確認済み)。`Equals(arg)`(1引数)は`==`比較へ
# (文字列同士の`Equals`はPythonの`==`と同じ値比較になる、.NET `String.
# Equals`の既定の序数比較とPythonの文字列`==`はいずれも単純な文字列値比較
# で一致——カルチャ依存の比較オーバーロードは未確認のため対象外)。
_CHAINED_PROPERTY_TRANSLATIONS = {"ToUpper": "upper", "ToLower": "lower", "Trim": "strip"}


def _render_chained_access(node: ChainedAccess) -> str:
    base = _render_node(node.target)
    members = list(node.members)
    if node.args is None:
        for member in members:
            base = _apply_chained_property(base, member)
        return base
    for member in members[:-1]:
        base = _apply_chained_property(base, member)
    last = members[-1]
    args = [_render_node(a) for a in node.args]
    if not args:
        # `.ToUpper()`等、空括弧付きの呼び出しは角括弧無しのプロパティ
        # アクセスと同じ意味論(.NETの慣習——引数無しメソッドは括弧の
        # 有無を問わず同じ)。
        return _apply_chained_property(base, last)
    if last == "Equals" and len(args) == 1:
        return f"({base}) == ({args[0]})"
    raise NotImplementedError(f"unsupported chained method call: .{last}(...)")


def _apply_chained_property(base: str, member: str) -> str:
    if member == "ToString":
        return f"{VB_CSTR_HELPER_NAME}({base})"
    if member == "Copy":
        # 知見130: `DataTable.Copy()`(`Dits21/Proyecto-Sistema-RPA-...`
        # の実機XAML`dtUB92.Copy`で発見、括弧無しの呼び出し——VB.NETの
        # 引数無しメソッドは括弧省略可能という既存の慣習、知見118参照)。
        # 既存のDataTable表現(`list[dict]`、知見114/115)に対応する
        # コピーは、各行の辞書も独立させる浅いコピーのリスト内包表記
        # ——`.Copy()`を複数回呼んだ結果が元のDataTableと行データを
        # 共有しないことを保証する。
        return f"[dict(_r) for _r in {base}]"
    if member in _CHAINED_PROPERTY_TRANSLATIONS:
        return f"{base}.{_CHAINED_PROPERTY_TRANSLATIONS[member]}()"
    raise NotImplementedError(f"unsupported chained member access: .{member}")


def _split_interpolated_string(raw: str) -> list[tuple[str, str]]:
    """文字列補間`$"...{expr}..."`(`raw`は`$"`〜閉じ`"`まで全体)を、
    リテラルテキスト区間と`{expr}`区間の列へ分解する(知見65、公式
    ドキュメント「Interpolated Strings」で確定)。

    VBの文字列補間の構文は`{{`/`}}`がリテラルの`{`/`}`(ダブらせて
    エスケープ)、`{expr[,field-width][:format-string]}`が補間式——公式の
    例`$"{name} is {age:D3} year{If(age = 1, "", "s")} old."`が示す通り、
    `{expr}`の中には**エスケープ無しの通常のVB文字列リテラル**(`""`/
    `"s"`)がネストしうる。`{`の後、ネストした文字列リテラルの外側
    (トップレベル)で最初に現れる`,`/`:`/`}`を区切りとして扱うことで、
    単純な正規表現やLarkのレクサでは崩れるこのネスト構造を手書きの
    状態機械で正しく分解する。`,field-width`/`:format-string`が実際に
    見つかった場合は、VBの書式指定子をPython側へ正確に対応させる
    確証が無いため(でっち上げを避け)サポート対象外として
    `NotImplementedError`を送出する——プレーンな`{expr}`補間のみ対応する。
    """
    assert raw.startswith('$"') and raw.endswith('"')
    body = raw[2:-1]
    segments: list[tuple[str, str]] = []
    buf: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if c == "{" and i + 1 < n and body[i + 1] == "{":
            buf.append("{")
            i += 2
            continue
        if c == "}" and i + 1 < n and body[i + 1] == "}":
            buf.append("}")
            i += 2
            continue
        if c == "{":
            if buf:
                segments.append(("text", "".join(buf)))
                buf = []
            depth_paren = 0
            in_quote = False
            j = i + 1
            start = j
            format_colon_idx: int | None = None
            comma_idx: int | None = None
            while j < n:
                cj = body[j]
                if in_quote:
                    if cj == '"':
                        if j + 1 < n and body[j + 1] == '"':
                            j += 2
                            continue
                        in_quote = False
                    j += 1
                    continue
                if cj == '"':
                    in_quote = True
                elif cj == "(":
                    depth_paren += 1
                elif cj == ")":
                    depth_paren -= 1
                elif cj == "}" and depth_paren == 0:
                    break
                elif cj == ":" and depth_paren == 0 and format_colon_idx is None:
                    format_colon_idx = j
                elif (
                    cj == ","
                    and depth_paren == 0
                    and comma_idx is None
                    and format_colon_idx is None
                ):
                    comma_idx = j
                j += 1
            if j >= n:
                raise NotImplementedError(
                    f"unterminated interpolated expression in: {raw!r}"
                )
            if format_colon_idx is not None or comma_idx is not None:
                raise NotImplementedError(
                    "interpolated string field-width/format-string "
                    f"(e.g. {{expr:format}}) is not yet supported: {raw!r}"
                )
            expr_text = body[start:j]
            segments.append(("expr", expr_text))
            i = j + 1
            continue
        buf.append(c)
        i += 1
    if buf:
        segments.append(("text", "".join(buf)))
    return segments


def _render_interpolated_string(raw: str) -> str:
    """`_split_interpolated_string()`で分解した各区間を、Pythonの`+`
    連結式へレンダリングする(知見65)。f-string(`f"..."`)ではなく明示的な
    `+`連結を選んだ理由は2つ: (1) `{expr}`内のVB式を`repr()`した結果が
    ダブルクォート文字列になりうる(例: アポストロフィを含む文字列)ため、
    f-stringのクォート文字と衝突しPython 3.11以前では構文エラーになる
    リスクがある。(2) f-stringの`{expr}`はPythonの素の`str()`で書式化する
    が、VBの文字列補間は実際には`CStr`/`&`と同じ書式規則(知見46)に
    従うため、`_vb_cstr()`を明示的に挟む方がより正確。各`{expr}`は
    `parse_vb_expr()`で構文木へ変換してから`_render_node()`で再帰的に
    レンダリングする(ネストした補間式自体は想定していない——VBの公式
    構文上も`{expr}`の中にさらに`$"..."`を書く例は見当たらない)。
    """
    segments = _split_interpolated_string(raw)
    parts: list[str] = []
    for kind, value in segments:
        if kind == "text":
            if value:
                parts.append(repr(value))
            continue
        inner_node, _consumed = parse_vb_expr(value)
        if inner_node is None:
            raise NotImplementedError(
                f"could not parse interpolated expression {value!r} in: {raw!r}"
            )
        rendered = _render_node(inner_node)
        parts.append(f"{VB_CSTR_HELPER_NAME}({rendered})")
    if not parts:
        return repr("")
    return " + ".join(parts)


def _parse_vb_hex_or_oct_str(text: str) -> int | None:
    """文字列が`&H`/`&O`16進・8進リテラル形式(`Microsoft.VisualBasic.
    CompilerServices.Utils.IsHexOrOctValue`、知見67)に該当するかを判定し、
    該当する場合はその整数値を返す(該当しなければ`None`)。先頭の半角/
    全角空白をスキップした後、`&`+`H`/`O`(大文字小文字区別無し)+1文字
    以上の数字が続く場合のみ該当する——`VB_CDBL_HELPER_SOURCE`/
    `VB_BOOL_HELPER_SOURCE`(ランタイム生成コード側、自己完結の都合で
    同じロジックを埋め込んでいる)と同じ規則。"""
    stripped = text.strip()
    if len(stripped) < 3 or stripped[0] != "&" or stripped[1].lower() not in "ho":
        return None
    base = 16 if stripped[1].lower() == "h" else 8
    return int(stripped[2:], base)


def _vb_cbool_of_string_literal(text: str) -> bool:
    """VBの`CBool`は文字列引数を`"True"`/`"False"`(大文字小文字区別無し)と
    認識するか、さもなくば数値として評価して非ゼロかどうかで判定する——
    それ以外の文字列は実行時に型不一致例外になる(参考: O'Reilly VB.NET
    言語リファレンス、.NET公式ランタイムソース`BooleanType.FromString`)。
    Pythonの`bool(文字列)`は空文字列以外は常に`True`になり挙動が違う
    (例: `bool("False")`は`True`、知見42と同じ種類の食い違い)ため、
    リテラル文字列の場合はコード生成時に実際の変換結果を確定させて
    そのまま埋め込む(`_render_func_call`参照)。"""
    normalized = text.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    hex_or_oct = _parse_vb_hex_or_oct_str(text)
    if hex_or_oct is not None:
        # `&H`/`&O`リテラル文字列(知見67)は`ParseDouble`を経由せず直接
        # 整数として判定される——`_vb_bool`(知見60)のランタイム版と
        # 同じ規則にコード生成時のこちらも揃える。
        return hex_or_oct != 0
    try:
        # 桁区切りのコンマは実際に受理される(`ParseDouble`の
        # `NumberStyles.AllowThousands`、知見52で確定)——`_vb_bool`
        # (知見60)側のランタイム版は既にコンマを除去しているため、
        # コード生成時のこちらのリテラル専用判定でも同じ規則に揃える
        # (知見63、揃えないと`CBool("1,234")`のようなリテラルだけが
        # 不要に`NotImplementedError`になってしまう不整合だった)。
        return float(normalized.replace(",", "")) != 0
    except ValueError:
        raise NotImplementedError(
            f"CBool({text!r}): not 'True'/'False' or numeric — VB would raise "
            "a type-mismatch exception at runtime, refusing to guess the result"
        ) from None


def _render_func_call(node: FuncCall) -> str:
    key = node.name.lower()
    args = [_render_node(a) for a in node.args]
    if key == "cstr":
        if len(args) != 1:
            raise NotImplementedError("CStr expects exactly 1 argument")
        return f"{VB_CSTR_HELPER_NAME}({args[0]})"
    if key == "cint":
        # VBの`CInt`は切り捨てではなく四捨五入(銀行丸め/round-half-to-even、
        # 知見42の`Mod`/`\`と同じ系統の「公式ドキュメントで確定した値の
        # 食い違い」)——Pythonの`round()`も単一引数ではデフォルトで
        # round-half-to-evenなので、公式ドキュメント記載例(0.5→0、1.5→2、
        # 2.5→2)とPythonの`round()`の挙動が一致することを確認済み
        # (単純な`int()`は切り捨てで食い違う、例: `int(1.5)`は`1`)。
        # `.NETランタイム本体のソース(`Conversions.vb`のToInteger、知見52の
        # CDbl確認時に同じファイルで発見、知見53参照)によれば`CInt`の
        # 文字列/オブジェクト両オーバーロードも先頭で`Nothing`→`0`を処理し、
        # 文字列引数は`CDbl`と全く同じ`ParseDouble`(桁区切り受理)経由で
        # Doubleへ変換してから丸める——単純な`float(x)`では`Nothing`で
        # `TypeError`、桁区切り文字列で`ValueError`になり食い違うため、
        # 既に`Nothing`/桁区切り/Boolean(`True→-1`)を正しく扱う`_vb_cdbl()`
        # (知見52)を経由させる。
        if len(args) != 1:
            raise NotImplementedError("CInt expects exactly 1 argument")
        return f"round({VB_CDBL_HELPER_NAME}({args[0]}))"
    if key == "cbool":
        if len(args) != 1:
            raise NotImplementedError("CBool expects exactly 1 argument")
        arg_node = node.args[0]
        if isinstance(arg_node, StringLiteral):
            return repr(_vb_cbool_of_string_literal(arg_node.value))
        # リテラル文字列以外(変数参照・関数呼び出し等)は実行時の型が
        # コード生成時には分からない——以前は`bool(x)`(Python素の真偽値
        # 判定)を使っており、文字列型なら`_vb_cbool_of_string_literal`と
        # 同じ理由で誤りうる既知の限界として記録していた(例:
        # `CBool(someVar)`で`someVar`が`"False"`/`"0"`を保持する場合、
        # `bool("False")`は`True`になり食い違う)。知見60・61で導入した
        # `_vb_bool()`(`_vb_cbool_of_string_literal`と同じ文字列判定
        # ロジックをランタイム版にしたもの、`Nothing`/桁区切りも対応)
        # がこの限界を解消するため、知見62でこちらに切り替えた。
        return f"{VB_BOOL_HELPER_NAME}({args[0]})"
    if key == "cdbl":
        if len(args) != 1:
            raise NotImplementedError("CDbl expects exactly 1 argument")
        return f"{VB_CDBL_HELPER_NAME}({args[0]})"
    if key == "isnothing":
        if len(args) != 1:
            raise NotImplementedError("IsNothing expects exactly 1 argument")
        return f"({args[0]} is None)"
    if key == "string.isnullorempty":
        if len(args) != 1:
            raise NotImplementedError("String.IsNullOrEmpty expects exactly 1 argument")
        return f"(not ({args[0]}))"
    if key == "file.readallbytes":
        # 知見130: `System.IO.File.ReadAllBytes(path)`(`Dits21/
        # Proyecto-Sistema-RPA-...`の実機XAML`file.ReadAllBytes(...)`で
        # 発見)。1引数の確認済み形のみ`open(path, 'rb').read()`へ対応
        # (返り値はPythonの`bytes`、.NETの`Byte()`に対応する)。
        if len(args) != 1:
            raise NotImplementedError("File.ReadAllBytes expects exactly 1 argument")
        return f"open({args[0]}, 'rb').read()"
    if key == "convert.tobase64string":
        # 知見130: `System.Convert.ToBase64String(Byte())`(同上の実機
        # XAML`convert.ToBase64String(...)`で発見)。1引数の確認済み形の
        # みPythonの`base64.b64encode(bytes).decode('ascii')`へ対応——
        # .NETは`String`を返すため`.decode('ascii')`で文字列化まで揃える
        # (Base64はASCII文字集合のみを使うため安全)。
        if len(args) != 1:
            raise NotImplementedError("Convert.ToBase64String expects exactly 1 argument")
        return f"base64.b64encode({args[0]}).decode('ascii')"
    if key == "path.getfilenamewithoutextension":
        # 知見130: `System.IO.Path.GetFileNameWithoutExtension(path)`
        # (同上の実機XAML`path.GetFileNameWithoutExtension(...)`で発見)。
        # 1引数の確認済み形のみ`os.path.splitext(os.path.basename(path))[0]`
        # へ対応する。
        if len(args) != 1:
            raise NotImplementedError(
                "Path.GetFileNameWithoutExtension expects exactly 1 argument"
            )
        return f"os.path.splitext(os.path.basename({args[0]}))[0]"
    if key == "len":
        # 知見127: `Microsoft.VisualBasic.Strings.Len(Expression)`
        # (`LowyShin/lwrpa-uip-moveoldfiles`の実機XAML`Len(sRstHttp)`で
        # 発見)。文字列に対しては文字数を返し、Python`len(str)`と直接
        # 対応する——実機で見つかった引数名(`sRstHttp`等、文字列を示す
        # Hungarian記法)はいずれも文字列用途だった。既知の限界: VBの
        # `Len`は非文字列(構造体等)には「バイトサイズ」を返す別の意味論
        # があり、Pythonの`len()`は文字列・リスト・辞書等のコレクションの
        # 要素数を返す——文字列以外の型に対する実機確認はまだ無いため、
        # 文字列用法のみを想定した直接マッピングとする。
        if len(args) != 1:
            raise NotImplementedError("Len expects exactly 1 argument")
        return f"len({args[0]})"
    if key == "split":
        # 知見126: `Microsoft.VisualBasic.Strings.Split(Expression,
        # Delimiter, Limit, Compare)`の実機確認済みの形は`nkarkare/
        # UDISEAutomation`の実機XAMLで見つかった2引数形
        # (`Split(in_Category, ",")`)のみ——`Delimiter`省略時の既定値
        # (半角スペース)・`Limit`(Pythonの`str.split(sep, maxsplit)`は
        # 「分割回数」、VBの`Limit`は「返す要素数」で算術的に1つずれる)・
        # `Compare`(大文字小文字無視分割)付きの3引数・4引数形は未確認
        # のため見送る。2引数形は`str.split(delimiter)`に素直に対応する
        # (既知の限界: `Delimiter`が空文字列`""`の場合、VBは元の文字列
        # 1件だけの配列を返すが、Pythonの`str.split("")`は`ValueError`
        # になる——リテラル空文字列の実機データにまだ遭遇していないため
        # 対応は見送る、知見42と同種の食い違い)。
        if len(args) != 2:
            raise NotImplementedError(
                "Split with argument count != 2 (bare single-arg default "
                "delimiter, or Limit/Compare overloads) is not confirmed — "
                "refusing to guess"
            )
        return f"{args[0]}.split({args[1]})"
    if key == "if" and len(args) == 3:
        # 三項演算子`If(cond, whenTrue, whenFalse)`(知見36)。`cond`は
        # `If...Then`文と同じく「True/Falseに評価できるか、暗黙的に
        # Booleanへ変換可能な型」が要求される(知見61、`If...Then...Else
        # Statement`ページの`condition`定義で確定)——`_vb_bool()`
        # (知見60の`AndAlso`/`OrElse`と同じヘルパー)で変換する。
        return f"({args[1]} if {VB_BOOL_HELPER_NAME}({args[0]}) else {args[2]})"
    if "." in node.name:
        # 知見127: `mail_Category.Equals("x")`のような、関数呼び出しを
        # 介さない素の変数へのメンバ**メソッド**呼び出し連鎖
        # (`nmnithinkrishna/uipathos-manufacturing-
        # AutonomousProductFabrication`の実機XAMLで発見)。`IDENT`トークン
        # の正規表現がドット区切りを1トークンとして貪欲マッチするため、
        # `mail_Category.Equals`全体が単一の関数名として`FuncCall`に
        # なってしまう——知見119(素の変数への**プロパティ**アクセス連鎖、
        # 呼び出し無し)と同種だが、末尾が呼び出しを伴う点が異なる新しい
        # ケース。この時点で`key`が上のTier1確認済み静的メソッド名
        # (`string.isnullorempty`等)のいずれにも一致しなかった場合のみ
        # ここへフォールバックする——静的クラス参照を誤って変数チェーンと
        # 解釈するリスクを避けるため、Tier1判定を必ず先に終えてから試す。
        # 末尾セグメントが確認済みの安全なメンバ(`_apply_chained_property`
        # /`Equals`)に一致する場合のみ`_render_chained_access`と同じ
        # ロジックを適用し、それ以外は従来通り`# TODO`へ倒す。
        segments = node.name.split(".")
        base = segments[0]
        for member in segments[1:-1]:
            base = _apply_chained_property(base, member)
        last = segments[-1]
        if not args:
            return _apply_chained_property(base, last)
        if last == "Equals" and len(args) == 1:
            return f"({base}) == ({args[0]})"
    raise NotImplementedError(
        f"unsupported function call (not in the confirmed Tier1 set): {node.name}(...)"
    )


def _render_bin_op(node: BinOp) -> str:
    op = node.op.lower()
    left = _render_node(node.left)
    right = _render_node(node.right)
    if op in _COMPARISON_OPS:
        python_op = _COMPARISON_OPS[op]
        return (
            f"(lambda _t: _t[0] {python_op} _t[1])"
            f"({VB_CMP_HELPER_NAME}({left}, {right}))"
        )
    if op == "is":
        return f"({left}) is ({right})"
    if op == "isnot":
        return f"({left}) is not ({right})"
    if op == "&":
        # VBの`&`は非文字列オペランドを自動的に文字列化するが、Pythonの`+`は
        # しない——明示的に文字列化を挟む(design/uipath_vb_expression_mapping.md
        # 「確認済み演算子の変換上の注意点」)。`CStr`と同じ変換規則
        # (`VB_CSTR_HELPER_SOURCE`参照、知見46)——単純な`str()`では
        # Double値の見た目が食い違う(`str(4.0)`は`"4.0"`、VBは`"4"`)。
        return f"{VB_CSTR_HELPER_NAME}({left}) + {VB_CSTR_HELPER_NAME}({right})"
    if op == "+":
        # 知見48参照: 単純な`+`では型混在(数値+文字列、Nothing絡み)で
        # `TypeError`になるか、VBの実際の算術加算結果と食い違う。
        return f"{VB_ADD_HELPER_NAME}({left}, {right})"
    if op == "-":
        # 知見49参照: `-`は文字列を扱わない純粋な数値演算子——単純な`-`
        # 変換のままだと文字列/`Nothing`オペランドで`TypeError`になる。
        return f"{VB_NUM_HELPER_NAME}({left}) - {VB_NUM_HELPER_NAME}({right})"
    if op == "mod":
        # VBの`Mod`は余りの符号が**被除数**の符号に従う(Microsoft Learn「Mod
        # Operator」、公式の変換式`a - (b * Fix(a / b))`どおり——例:
        # `-7 Mod 3`は`-1`)。Pythonの`%`は符号が**除数**に従う床除算の余り
        # (`-7 % 3`は`2`)で、両オペランドの符号が異なる場合に値が食い違う
        # ため単純な`%`への変換は不可——VBの公式変換式をそのまま再現する
        # (`int()`はPythonのtruncate-toward-zeroで、VBの`Fix()`と一致)。
        # ゼロ除算は型依存(知見54、`_vb_mod()`参照)なので専用ヘルパーに
        # 一本化した(`Nothing`→`0`の処理も内包、知見49)。
        return f"{VB_MOD_HELPER_NAME}({left}, {right})"
    if op == "\\":
        # VBの`\`(整数除算)はゼロ方向への切り捨て(truncation、Microsoft
        # Learn「\ Operator」——例: `67 \ -3`は`-22`)。Pythonの`//`は
        # 負方向への床除算(floor、`67 // -3`は`-23`)で、両オペランドの
        # 符号が異なる場合に値が食い違うため単純な`//`への変換は不可。
        # `int()`はtruncate-toward-zeroなので`int(a / b)`で正しく再現できる。
        # `\`も`Nothing`を`0`として扱う数値演算子(知見49)。
        # さらに同ページRemarksが「除算の前に浮動小数点オペランドをLongへ
        # 変換しようとする、この変換は銀行丸めの対象」と明記(知見54で
        # 発見、実機未確認だった残課題)——`round()`で両オペランドを先に
        # Longへ丸めてから切り捨て除算する(例: `7.5 \ 2`はVBで`4`
        # (7.5→銀行丸めで8、8\2=4)になり、丸め無しの単純な
        # `int(7.5/2)=3`とは食い違う)。ゼロ除算は型に依存せず常に例外
        # (同ページ「This is true for all numeric data types」)——
        # Pythonの`/`もゼロ除数で型によらず常に`ZeroDivisionError`を
        # 送出するため、この点は無変換のままで既に一致している。
        a = f"round({VB_NUM_HELPER_NAME}({left}))"
        b = f"round({VB_NUM_HELPER_NAME}({right}))"
        return f"int(({a}) / ({b}))"
    if op == "*":
        return f"{VB_NUM_HELPER_NAME}({left}) * {VB_NUM_HELPER_NAME}({right})"
    if op == "/":
        # 知見50参照: `/`は常にDouble扱いになるためゼロ除算もDouble方式
        # (`Infinity`/`NaN`)——単純な`_vb_num(a)/_vb_num(b)`のままだと
        # Pythonの`ZeroDivisionError`で即座にクラッシュする。
        return f"{VB_DIV_HELPER_NAME}({left}, {right})"
    if op == "^":
        # VBの`^`は常にDouble型で計算される(Microsoft Learn「^ Operator」)
        # ため`2^2`はVBでは`4.0`相当になるが、Pythonの`2 ** 2`は整数`4`の
        # まま——通常は数値として等価だが文字列化の見た目が変わりうる。
        # さらに負の底に非整数の指数を与えた場合、実機(UiPath Studio
        # Debug File、Sub1.xaml、2026-11-05)で`(-8.0) ^ 0.5`を実行して
        # `NaN`を確認——Pythonの`**`はこの場合複素数を返すため単純な`**`
        # 変換は不可(design/uipath_xaml_findings.md 知見45参照)。負の底
        # かつ指数が非整数の場合のみNaNに分岐する。
        # `^`は知見49(`-`/`*`/`/`/`Mod`/`\`)の型混在対応サイクルより前
        # (知見45)に実装したため、文字列/`Nothing`オペランドの強制が
        # 漏れていた——`Nothing`/文字列を渡すと`None < 0`/`str < int`で
        # `TypeError`になっていた(知見57、`Operators.vb`の
        # `ExponentObject`で`Empty`→`0.0`への変換を確認して発見)。
        # `_vb_num()`で両オペランドを事前に揃える。
        a = f"{VB_NUM_HELPER_NAME}({left})"
        b = f"{VB_NUM_HELPER_NAME}({right})"
        return f"(float('nan') if (({a}) < 0 and ({b}) != int({b})) else (({a}) ** ({b})))"
    if op in _BITWISE_OPS:
        return f"{_BITWISE_OPS[op]}({left}, {right})"
    if op in _SHORT_CIRCUIT_OPS:
        a = f"{VB_BOOL_HELPER_NAME}({left})"
        b = f"{VB_BOOL_HELPER_NAME}({right})"
        return f"({a}) {_SHORT_CIRCUIT_OPS[op]} ({b})"
    raise NotImplementedError(f"unsupported binary operator: {node.op!r}")


def render_expr(expr: Expr) -> str:
    """`Expr`(`VbExpr`/`Literal`/`None`)をPython式のソース文字列に変換する。

    `VbExpr`は`uipath_expr.parse_vb_expr()`でその場で構文解析する
    (`uipath_dsl`とは意図的に疎結合——design/uipath_transpiler_roadmap.md
    Phase 3の「次にやること」参照)。構文解析自体が失敗した場合、または
    構文解析には成功したがこの関数がまだ対応していない構文(文字列補間の
    中身・未対応の関数呼び出し等)だった場合は、いずれも`NotImplementedError`
    を送出する——架空のPython式をでっち上げて返すことは無い。

    `Literal`は実機データ上すべて文字列値だった(知見2・5等)ため、v1では
    無条件に文字列リテラルとして扱う——Int32/Boolean等の非文字列`Literal`は
    実例が無く未対応(既知の簡略化)。
    """
    if expr is None:
        return "None"
    if isinstance(expr, Literal):
        return repr(expr.value)
    if isinstance(expr, VbExpr):
        tree, _ = parse_vb_expr(expr.text)
        if tree is None:
            raise NotImplementedError(f"VB expression failed to parse: {expr.text}")
        return _render_node(tree)
    raise TypeError(f"Unsupported Expr type: {type(expr)!r}")
