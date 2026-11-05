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
# 型変換関数のうち、単純な名前変換で安全に対応できるもの。`CDbl`は`float()`
# で十分(浮動小数点への変換は丸めの余地が無く情報を失わない)。`CStr`/
# `CInt`/`CBool`は値そのものがVBとPythonで食い違いうる(知見42・45と同じ
# 種類の問題)ため、個別に`_render_func_call`内で処理する(下記参照)。
_CAST_FUNCS = {
    "cdbl": "float",
}

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
VB_CSTR_HELPER_NAME = "_vb_cstr"
VB_CSTR_HELPER_SOURCE = """\
def _vb_cstr(x):
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
VB_CMP_HELPER_NAME = "_vb_cmp"
VB_CMP_HELPER_SOURCE = """\
def _vb_cmp(a, b):
    def _vb_is_num(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool)
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
        b = float(b)
    elif isinstance(a, str) and _vb_is_num(b):
        a = float(a)
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
VB_ADD_HELPER_NAME = "_vb_add"
VB_ADD_HELPER_SOURCE = """\
def _vb_add(a, b):
    def _vb_is_num(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool)
    if isinstance(a, bool):
        a = -1 if a else 0
    if isinstance(b, bool):
        b = -1 if b else 0
    if a is None and b is None:
        return ""
    if a is None:
        a = 0 if _vb_is_num(b) else ""
    elif b is None:
        b = 0 if _vb_is_num(a) else ""
    if _vb_is_num(a) and isinstance(b, str):
        b = float(b)
    elif isinstance(a, str) and _vb_is_num(b):
        a = float(a)
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
    if isinstance(a, bool):
        a = -1 if a else 0
    elif a is None:
        a = 0
    elif isinstance(a, str):
        a = float(a)
    if isinstance(b, bool):
        b = -1 if b else 0
    elif b is None:
        b = 0
    elif isinstance(b, str):
        b = float(b)
    if b == 0:
        if a == 0:
            return float("nan")
        return float("inf") if a > 0 else float("-inf")
    return a / b
"""

# design/uipath_vb_expression_mapping.md「確認済み演算子の変換上の注意点」
# (2026-11-05確定分): And/Or/Xorは全て、両オペランドを括弧で囲んだ上で
# Pythonのビット演算子(&/|/^)へ1対1で変換する——Pythonのboolがintの
# サブクラスであるため、ブール/整数どちらのオペランドでも意味論が一致する。
_BITWISE_OPS = {"and": "&", "or": "|", "xor": "^"}
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
        # design/uipath_transpiler_roadmap.md 知見36/uipath_exprのdocstring
        # 参照: 文字列補間`$"..."`の中身(`{expr}`)はuipath_exprがまだ
        # 構文解析していないため、安全にPython f-stringへ変換できない。
        raise NotImplementedError(
            f"string interpolation is not yet supported by codegen: {node.raw}"
        )
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
            operand = _render_node(node.operand)
            return f"(lambda _x: (not _x) if isinstance(_x, bool) else ~_x)({operand})"
        if op in ("-", "+"):
            return f"{node.op}({_render_node(node.operand)})"
        raise NotImplementedError(f"unsupported unary operator: {node.op!r}")
    if isinstance(node, FuncCall):
        return _render_func_call(node)
    if isinstance(node, BinOp):
        return _render_bin_op(node)
    raise NotImplementedError(f"unsupported expression node: {node!r}")


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
    try:
        return float(text) != 0
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
        # 文字列引数も`float()`を経由すれば数値と同じ経路で丸められる。
        if len(args) != 1:
            raise NotImplementedError("CInt expects exactly 1 argument")
        return f"round(float({args[0]}))"
    if key == "cbool":
        if len(args) != 1:
            raise NotImplementedError("CBool expects exactly 1 argument")
        arg_node = node.args[0]
        if isinstance(arg_node, StringLiteral):
            return repr(_vb_cbool_of_string_literal(arg_node.value))
        # リテラル文字列以外(変数参照・関数呼び出し等)は実行時の型が
        # コード生成時には分からない——文字列型であれば`bool(x)`は
        # `_vb_cbool_of_string_literal`と同じ理由で誤りうる既知の限界
        # (design/uipath_vb_expression_mapping.md参照)。数値/真偽値型なら
        # `bool(x)`はVBのCBoolと一致するため、でっち上げた型チェックを
        # 挿入するより素直な`bool(x)`のままにする。
        return f"bool({args[0]})"
    if key in _CAST_FUNCS:
        if len(args) != 1:
            raise NotImplementedError(f"{node.name} expects exactly 1 argument")
        return f"{_CAST_FUNCS[key]}({args[0]})"
    if key == "isnothing":
        if len(args) != 1:
            raise NotImplementedError("IsNothing expects exactly 1 argument")
        return f"({args[0]} is None)"
    if key == "string.isnullorempty":
        if len(args) != 1:
            raise NotImplementedError("String.IsNullOrEmpty expects exactly 1 argument")
        return f"(not ({args[0]}))"
    if key == "if" and len(args) == 3:
        # 三項演算子`If(cond, whenTrue, whenFalse)`(知見36)。
        return f"({args[1]} if {args[0]} else {args[2]})"
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
        # `Mod`も`Nothing`を`0`として扱う数値演算子(知見49、同ページで
        # 確定)なので`_vb_num()`で両オペランドを事前に揃える。
        a = f"{VB_NUM_HELPER_NAME}({left})"
        b = f"{VB_NUM_HELPER_NAME}({right})"
        return f"({a}) - (({b}) * int(({a}) / ({b})))"
    if op == "\\":
        # VBの`\`(整数除算)はゼロ方向への切り捨て(truncation、Microsoft
        # Learn「\ Operator」——例: `67 \ -3`は`-22`)。Pythonの`//`は
        # 負方向への床除算(floor、`67 // -3`は`-23`)で、両オペランドの
        # 符号が異なる場合に値が食い違うため単純な`//`への変換は不可。
        # `int()`はtruncate-toward-zeroなので`int(a / b)`で正しく再現できる。
        # `\`も`Nothing`を`0`として扱う数値演算子(知見49)。
        return f"int({VB_NUM_HELPER_NAME}({left}) / {VB_NUM_HELPER_NAME}({right}))"
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
        return (
            f"(float('nan') if (({left}) < 0 and ({right}) != int({right})) "
            f"else (({left}) ** ({right})))"
        )
    if op in _BITWISE_OPS:
        return f"({left}) {_BITWISE_OPS[op]} ({right})"
    if op in _SHORT_CIRCUIT_OPS:
        return f"({left}) {_SHORT_CIRCUIT_OPS[op]} ({right})"
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
