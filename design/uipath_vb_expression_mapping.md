# VB.NET式 → Python式 変換ルール

[design/uipath_xaml_findings.md](uipath_xaml_findings.md)知見2で確認した通り、UiPathの
XAML中の式(`InArgument`/`OutArgument`/アクティビティのプロパティ値等)は、角括弧
`[...]`で囲んだVB.NET式テキストとしてそのまま埋め込まれる。変換にはVB.NET式パーサー/
トランスパイラが新規に必要で、PAD用の式パーサー(`pad_expr`)は流用できない
(構文が全く別物、実際に`dump_daemon/uipath_expr/`として別途自作した)。

本ドキュメントは、その変換表。**VB.NETは公開されている言語仕様であり、
UiPath固有のデコンパイル知識は不要**——以下は原則として公開のVB.NET言語仕様に基づく
整理で、実機XAMLで個別に裏取りしたのは「確認済み」と明記した項目(知見2・5・14・
30・32・36、2026-11-05時点で主要な演算子・リテラル・型変換関数は全て確認済み)。

## 確認済み(実機XAMLで裏取り)

| VB.NET | 実機確認の文脈 | Python |
|---|---|---|
| 文字列リテラル `"..."` | `Text="[&quot;Hello from pad2py&quot;]"` (知見2) | `"..."`(同じ) |
| 変数参照 `varName` | `<OutArgument ...>[result]</OutArgument>` (知見2) | `varName`(同じ) |
| 等価比較 `=` | `Condition="[result=&quot;ok&quot;]"` (知見5) | `_vb_cmp(a, b)`経由の`==`(2026-11-05修正、知見47参照——数値/文字列混在オペランドの型変換規則) |
| 配列/コレクションリテラル `{a, b, c}` | `Values="[{&quot;a&quot;,&quot;b&quot;,&quot;c&quot;}]"` (知見5) | `[a, b, c]` |
| メンバ参照(裸の変数名、ループデリゲート変数含む) `item` | `Text="[item]"` (知見5) | `item`(同じ) |
| 不等価 `<>` | `ExpressionText="result&lt;&gt;&quot;x&quot;"`(`While`の`Condition`、知見14) | `_vb_cmp(a, b)`経由の`!=`(同上、知見47) |
| 大小比較 `<`/`<=`/`>`/`>=` | 構文としての受理は確認済みだが、実機個別確認は未実施——`=`/`<>`と同じ比較演算子群として公式ドキュメントに同じ型変換規則が明記されている(知見47) | `_vb_cmp(a, b)`経由の`<`/`<=`/`>`/`>=`(同上) |
| 参照比較 `Is`(`Nothing`判定含む) | `Transition.Condition>[SystemException is Nothing]`(UiPath公式REFrameworkテンプレートの実例、知見30) | `is`(`is None`等) |
| 文字列結合 `&` | 知見32、9演算子複合式の実機コンパイル確認 | `_vb_cstr(a) + _vb_cstr(b)`(2026-11-05修正、知見46参照——`CStr`と同じ変換規則、下記「注意点」参照) |
| 加算 `+` | 構文としての受理は知見32(`2 ^ 2`等の例に含まれる文脈で間接確認)だが、型混在の実機個別確認は未実施——公式ドキュメントに型混在ディスパッチ規則が明記されている(知見48) | `_vb_add(a, b)`(2026-11-05修正、知見48参照——片方が数値・片方が文字列なら連結ではなく算術加算になる。下記「注意点」参照) |
| 減算 `-` / 乗算 `*` | 知見32、9演算子複合式の実機コンパイル確認(型混在の実機個別確認は未実施) | `_vb_num(a) OP _vb_num(b)`(2026-11-05修正、知見49参照——文字列/`Nothing`オペランドの数値強制、下記「注意点」参照) |
| 浮動小数点除算 `/` | 同上 | `_vb_div(a, b)`(2026-11-05修正、知見50参照——文字列/`Nothing`の数値強制に加え、ゼロ除算もVBのDouble方式(`Infinity`/`NaN`)に、下記「注意点」参照) |
| 剰余 `Mod` | 同上 | `_vb_mod(a, b)`(2026-11-05修正、知見49・54参照——単純な`%`では不可、ゼロ除算は型依存(浮動小数点系は`NaN`、整数系は例外)、下記「注意点」参照) |
| 整数除算 `\` | 同上 | `int(round(_vb_num(a)) / round(_vb_num(b)))`(2026-11-05修正、知見49・54参照——単純な`//`では不可、除算前にオペランドを銀行丸めでLongへ変換、下記「注意点」参照) |
| 累乗 `^` | 同上 | `float('nan') if (_vb_num(a)<0 and _vb_num(b)!=int(_vb_num(b))) else (_vb_num(a)**_vb_num(b))`(2026-11-05修正、知見45・57参照——負の底+非整数の指数のみ`NaN`に分岐、文字列/`Nothing`オペランドも`_vb_num()`で数値強制) |
| `And` / `Or`(非短絡評価) | 同上(構文としての受理は知見32)。変換ルールは2026-11-05にPython実挙動で検証し確定(下記「注意点」参照) | `_vb_and(a, b)` / `_vb_or(a, b)`(2026-11-05修正、知見59参照——両方値がある場合は内部で`&`/`\|`を使うため従来通り、`Nothing`絡みの変換規則も含む) |
| `AndAlso` / `OrElse`(短絡評価) | 同上 | `_vb_bool(a) and/or _vb_bool(b)`(2026-11-05修正、知見60参照——結果は常にBoolean型、単純な`and`/`or`はPythonが生のオペランド値を返すため食い違う。下記「注意点」参照) |
| `Not` | 同上(Integerオペランドは知見45で実機確認) | `(lambda _x: (not _x) if isinstance(_x, bool) else ~(0 if _x is None else _x))(x)`(2026-11-05修正、知見45・58参照——Booleanは論理否定、Integerはビット反転、`Nothing`は整数`0`扱い) |
| 単項`-`/`+` | 構文としての受理は知見32 | `(lambda _x: OP(0 if _x is None else _x))(x)`(2026-11-05修正、知見58参照——`Nothing`は整数`0`扱い、`Operators.vb`の`NegateObject`/`PlusObject`で確定) |
| `Xor` | 同上 | `_vb_xor(a, b)`(2026-11-05修正、知見59参照——内部では`And`/`Or`の`&`/`\|`と同じ理由で`^`を使う、`Nothing`絡みの変換規則も含む) |
| `CStr(x)` | 同上 | `_vb_cstr(x)`(2026-11-05修正、知見46・56参照——VBのDouble既定書式(G15)は整数値の小数点を省略するため単純な`str(x)`では食い違う。例: `CStr(4.0)`は`"4"`だが`str(4.0)`は`"4.0"`。`NaN`/`Infinity`/`-Infinity`も特別扱い。`Nothing`は空文字列に近似(知見56、厳密にはnullだが`&`での実用シナリオを優先)) |
| `True` / `False` | 同上 | `True` / `False` |
| `IsNot`(参照比較の否定) | `[CStr(If(result IsNot Nothing, "notnothing", "isnothing")) & ...]`(知見36、実機コンパイル確認) | `is not` |
| `Nothing` | 同上 | `None` |
| 三項演算子 `If(cond, whenTrue, whenFalse)` | 同上 | `whenTrue if _vb_bool(cond) else whenFalse`(2026-11-05修正、知見61参照——`cond`はBooleanへの暗黙変換が必要、下記「注意点」参照) |
| `CInt(x)` | `[... & CStr(CInt("5")) & ...]`(知見36、実機コンパイル確認) | `round(_vb_cdbl(x))`(2026-11-05修正、知見42・53参照——VBの`CInt`は銀行丸め/round-half-to-even(知見42)に加え、`Nothing`→`0`・桁区切り文字列・`Boolean`→`-1`も`CDbl`と同じ変換を内部で使う(知見53、.NETランタイム本体のソースで確定)ため`_vb_cdbl()`経由にする) |
| `CDbl(x)` | 同上 | `_vb_cdbl(x)`(2026-11-05修正、知見52参照——.NETランタイム本体のソース(`Conversions.vb`)で確定。`Nothing`→`0`、桁区切り文字列(`"1,234.5"`)を受理、`Boolean`は`True→-1`) |
| `CBool(x)` | 同上 | 引数が文字列リテラルならコード生成時に`"True"`/`"False"`(大文字小文字無視)か数値(桁区切り文字列も受理、知見63)として確定済みの`True`/`False`を埋め込む(2026-11-05修正、知見42・63参照——Pythonの`bool(文字列)`は空文字列以外は常に`True`になり食い違う。例: `bool("False")`は`True`)。リテラル以外(変数参照等)は`_vb_bool(x)`(2026-11-05修正、知見62参照——知見60・61の`_vb_bool()`を再利用して以前の既知の限界を解消) |
| `IsNothing(x)` | 同上 | `x is None` |
| 文字列補間 `$"...{expr}..."` | `[$"value={result}-end"]`(知見36、実機コンパイル確認——`{`/`}`含めそのまま`[...]`内に直列化される) | `"text1" + _vb_cstr(expr1) + ...`(2026-11-05修正、知見65・66参照——f-stringではなく`+`連結。`{expr}`内にネストした文字列リテラルを含む式も知見66で対応済み。書式指定子・フィールド幅のみ未対応のまま`# TODO`、下記「注意点」参照) |
| `String.IsNullOrEmpty(x)` | `[CStr(String.IsNullOrEmpty("")) & ...]`(知見36、実機コンパイル確認) | `not x`(ただし空白のみの文字列の扱いに差——`String.IsNullOrWhiteSpace`との混同に注意) |
| 文字列中のダブルクォートエスケープ `""` | `["He said ""hi"" today"]`(知見36、実機コンパイル確認——VB文字列リテラル内では`""`が`"`1個を表す) | `\"` |

### 確認済み演算子の変換上の注意点

- **`&`(文字列結合)**: VB `&`は非文字列オペランドを自動的に文字列へ変換するが、
  Pythonの`+`はしない——変換側で文字列化を明示的に挟む必要がある。単純な
  `str(x)`では不十分(2026-11-05修正、知見46参照——`CStr`と全く同じ理由、
  Double値の整数値が`"4.0"`ではなく`"4"`になる等)で、`CStr`と同じ
  `_vb_cstr()`ヘルパーを使う。
- **`+`(加算)——単純な`+`への変換は不可(2026-11-05、公式ドキュメントで
  確定、知見48)**: VBの`+`(Microsoft Learn「+ Operator」)は「可能な限り
  算術加算を行い、両方が文字列の場合のみ連結する」——片方が数値・片方が
  文字列の場合は**文字列をDoubleへ変換してから算術加算する**(公式の例:
  `"34" + 6`は`"346"`ではなく`40`)。Pythonの`+`は型が揃っていないと
  `TypeError`で即座にクラッシュするため、単純な`+`変換のままでは動かない
  (`_vb_cmp`/`_vb_cstr`のような「値が間違うが動く」よりも重大)。
  `_vb_add()`ヘルパー(`Nothing`を数値側で`0`・文字列側で`""`として扱う
  規則も含む)を使う。**例外**: `Nothing + Nothing`のみ整数`0`になる
  (2026-11-05、.NETランタイム本体のソース`Operators.vb`の`AddObject`で
  確定、知見55——知見48実装時は上記の一般則をそのまま適用して`""`と
  誤って推測していたが、実際のソースコードでは両方`Nothing`の組だけ
  特別扱いされていた)。
- **`-`(減算)・`*`(乗算)・`/`(浮動小数点除算)・`Mod`・`\`——文字列/
  `Nothing`オペランドで単純な変換のままだと`TypeError`(2026-11-05、
  公式ドキュメントで確定、知見49)**: `+`と違いこれらは文字列を特別扱い
  しない純粋な数値演算子(各公式ページ「Supported Types: All numeric
  types」)——`Option Strict Off`下の文字列オペランドは`Double`へ暗黙
  変換されてから演算され、`Nothing`は`0`として扱われる(`-`/`*`/`Mod`の
  各公式ページで確認済み)。Pythonの演算子は文字列/`None`を渡されると
  `TypeError`で即座にクラッシュするため、`_vb_num()`ヘルパーで両
  オペランドを事前に数値へ揃える。
- **`/`(浮動小数点除算)のゼロ除算はVBのDouble方式(2026-11-05、公式
  ドキュメントで確定、知見50)**: `/`は「除算の前に整数オペランドは全て
  Doubleへ拡張される」(Microsoft Learn「/ Operator」)ため、オペランドの
  型によらず常にDouble相当で計算される唯一の算術演算子——ゼロ除算も
  型分岐せず常に`expression1`が0なら`NaN`、それ以外は符号に応じて
  `Infinity`/`-Infinity`になる。Pythonの`/`はゼロ除算で
  `ZeroDivisionError`を即座に送出するため、`_vb_div()`ヘルパー(`_vb_num`
  と同じ数値強制に加えゼロ除算をDouble方式へ分岐)を使う。`Mod`/`\`の
  ゼロ除算は型依存のため未解消のまま残る(下記参照)。
- **Booleanオペランドの算術・比較演算子への変換は`True→-1`(2026-11-05、
  公式ドキュメントで確定、知見51)**: Microsoft Learn「Boolean Data
  Type」が「VBがBooleanを数値型へ変換する際、`False`は`0`、`True`は
  `-1`になる」と明記(VB6互換のための仕様、`Convert.ToInt32`等の.NET
  標準メソッドとは異なる)。Pythonの`bool`は`int`のサブクラスで`True`は
  `1`相当のため、素通しすると符号が逆になる(`5 + True`はVBでは`4`だが
  無変換だと`6`になる)。`_vb_cmp`/`_vb_add`/`_vb_num`/`_vb_div`全ての
  先頭でBooleanを`-1`/`0`へ変換してから残りのロジックに流す
  (`_vb_cstr`のBoolean→文字列変換(`CStr(True)`→`"True"`)は別規則で
  対象外、既に正しい)。
- **`\`(整数除算)・`Mod`(剰余)——単純な`//`/`%`への変換は不可(2026-11-05、
  公式ドキュメントで確定)**: VBの`\`(Microsoft Learn「\ Operator」)は
  **ゼロ方向への切り捨て**(truncation)、`Mod`(同「Mod Operator」)は
  公式の変換式`a - (b * Fix(a / b))`どおり**余りの符号が被除数に従う**。
  いずれもPythonの`//`/`%`(床除算=floor、余りの符号が除数に従う)とは
  **オペランドの符号が異なる場合に結果の値そのものが変わる**(例:
  `67 \ -3`はVBで`-22`・Python`67 // -3`は`-23`、`-7 Mod 3`はVBで
  `-1`・Python`-7 % 3`は`2`)。構文の優先順位の話ではなく実行時の値が
  食い違う、より重大な誤変換だったため、`int(a / b)`(Pythonの`int()`も
  ゼロ方向への切り捨てで、VBの`Fix()`と一致)を使い
  `\`→`int(a / b)`、`Mod`→`a - (b * int(a / b))`という変換式に修正した
  (`tests/test_uipath_codegen.py`の
  `test_mod_and_intdiv_match_vb_sign_semantics_not_python_floor_semantics`
  で両演算子の公式ドキュメント記載例をそのまま`exec()`し実値を検証済み)。
  `/`(浮動小数点除算)自体は常に浮動小数点結果になる点がPythonの`/`と一致
  (Python 3)するため変換不要。
- **`Mod`/`\`のゼロ除算・`\`の銀行丸め先行(2026-11-05、.NETランタイム
  本体のソース`Operators.vb`で確定、知見54)**: `Mod`のゼロ除算は型依存
  (`ModObject`の`TypeCode`別ディスパッチ——浮動小数点系は`NaN`、整数系は
  例外)なので、`_vb_num()`後のPython実行時型(`int`/`float`)を代理指標
  として判定する`_vb_mod()`ヘルパーに変更した。`\`のゼロ除算は型に
  よらず常に例外(Pythonの`/`も型によらず常に`ZeroDivisionError`のため
  無変換のまま一致)。さらに`\`は除算の**前**に両オペランドを銀行丸めで
  Longへ変換する(Microsoft Learn「\ Operator」Remarks節)ため、
  `round(_vb_num(a)) / round(_vb_num(b))`の形に変更した(例:
  `7.5 \ 2`は`7.5`が銀行丸めで`8`になってから切り捨て除算され`4`に
  なる、丸め無しの単純な`int(7.5/2)`は`3`で食い違う)。
- **`And`/`Or`(非短絡評価)の変換ルール——確定(2026-11-05、設計検討+Python
  実挙動で検証)**: `a And b` → Python `(a) & (b)`、`a Or b` → Python
  `(a) | (b)`(ビット演算子)に変換する。理由:
  - VBの`And`/`Or`は「両辺を必ず評価してから結合する」演算子で、しかも
    **オペランドの型によって意味が変わる**(Boolean同士なら論理AND/OR、
    Integer同士ならビットAND/OR)という二重の性質を持つ。
  - Pythonの`&`/`|`は制御構文の`and`/`or`と違って普通の二項演算子
    (`__and__`/`__or__`呼び出し)であり、**両辺を常に評価する**(短絡しない)。
    さらにPythonの`bool`は`int`のサブクラスなので、`True & False`は
    `bool`型の`False`を返し(`bin(5)`風のビット演算にはならない)、
    `5 & 3`は通常のビットANDになる——**VBの型依存の二重性質とPythonの
    `&`/`|`の挙動が偶然ではなく構造的に一致する**(`bool`が`int`の
    サブタイプという設計がVBと同型)。実際に確認:
    ```python
    >>> True & False
    False
    >>> type(True & False)
    <class 'bool'>
    >>> 5 & 3
    1
    ```
  - 両辺が必ず評価されることも実証済み(副作用のある呼び出しで確認):
    ```python
    >>> calls = []
    >>> def f(label, val): calls.append(label); return val
    >>> f('a', False) & f('b', True)
    >>> calls
    ['a', 'b']  # bがFalseで短絡されず、両方呼ばれている
    ```
  - **重要な罠、codegen側で必ず対応が必要**: Pythonの演算子優先順位は
    `&`が比較演算子(`==`等)より**高い**(強く結合する)。これはVBとも
    通常の直感とも逆で、括弧を省略すると静かに誤った意味になる:
    ```python
    >>> x, y = 5, 6
    >>> x == 5 & y == 6          # 括弧無し→誤り
    False                          # 本来はTrueになるべき値がFalseになる
    >>> (x == 5) & (y == 6)      # 括弧あり→正しい
    True
    ```
    (`x == 5 & y == 6`は`x == (5 & y) == 6`という連鎖比較として解釈され、
    意図した「xが5 かつ yが6」とは全く別の式になる。)
    **結論: codegenは`And`/`Or`の両オペランドを無条件に括弧で囲んで
    `&`/`|`を出力すること。** AST→コード生成方式(テキスト置換ではない)
    であれば、この括弧付与は機械的に実施できる——設計上のブロッカーでは
    なく実装時の単純な規則。
  - **既知の限界**(v1では対応不要、記録のみ): VB側でカスタム型に
    `And`/`Or`演算子オーバーロードが定義されている場合(稀)、Python側で
    そのクラスに`__and__`/`__or__`を実装しない限り動かない。優先度低。
  - **(訂正、2026-11-05、知見60)** `AndAlso`/`OrElse`は当初「Pythonの
    `and`/`or`と意味論が完全一致する」としていたが誤りだった——VBの
    `AndAlso`/`OrElse`は公式ドキュメント(Microsoft Learn「AndAlso
    Operator」)により「両オペランドを評価前にBooleanへ変換し、結果も
    常にBoolean」と明記されている。Pythonの`and`/`or`はBoolean変換を
    せず生のオペランド値をそのまま返すため、`0 AndAlso True`のような
    非Boolean値が混ざるケースで食い違う(VBは`False`、Pythonの
    `0 and True`は`0`)。`_vb_bool()`ヘルパーで両オペランドを明示的に
    Booleanへ変換してから`and`/`or`(短絡評価自体はそのまま活用)を
    適用するよう修正した。
- **`If`/`While`/`DoWhile`の条件式・三項`If()`の第1引数(2026-11-05、
  知見61——`AndAlso`/`OrElse`と同じ食い違いが制御構文にも波及していた)**:
  Microsoft Learn「If...Then...Else Statement」が条件式を「Must evaluate
  to True or False, or to a data type that is implicitly convertible to
  Boolean」と定義しており、`AndAlso`/`OrElse`(知見60)と同じBoolean
  変換規則に従う。Pythonの`if`/`while`文の素の真偽値判定(`bool(文字列)`
  は空文字列以外常に`True`)はVBのCBool規則と食い違うため(例:
  `If "False" Then`はVBでは偽になるが、Pythonの素の`if "False":`は
  真)、`_vb_bool()`(`AndAlso`/`OrElse`と同じヘルパー)で明示的に
  条件式をBooleanへ変換してから`if`/`while`文へ渡すよう修正した。
- **`Xor`(2026-11-05、`And`/`Or`の検証過程で判明)**: 当初「ブール同士なら
  `!=`、整数同士なら`^`」と型依存の変換が必要だと考えていたが、`And`/`Or`
  の`&`/`|`統一変換と全く同じ理由(Pythonの`bool`は`int`のサブクラスで、
  `^`はbool同士でも`bool`型の結果を返す)で**型によらず常に`^`で統一できる**
  と判明した。実機ではなくPython自身の挙動で検証:
  ```python
  >>> True ^ False
  True
  >>> type(True ^ False)
  <class 'bool'>
  >>> 5 ^ 3
  6
  ```
  `And`/`Or`と同じく両オペランドを括弧で囲む必要がある(Pythonの`^`も
  比較演算子より結合が強いため)。
- **文字列補間`$"...{expr}..."`(2026-11-05、公式ドキュメントで構文確定、
  知見65・66)**: VBの文字列補間は`$"<text>{<expr>[,<field-width>][:<format-
  string>]}<text>..."`という構造(Microsoft Learn「Interpolated
  Strings」)——`"text1" + _vb_cstr(expr1) + ...`という`+`連結へ変換する
  (f-stringは使わない——理由は`_vb_cstr()`のdocstring/知見65参照)。
  `{expr}`内部にネストした文字列リテラルを含む式(公式ドキュメント自身の
  `If(age = 1, "", "s")`の例を含む)は知見65時点では`uipath_expr`のLark
  レクサが区別できず`# TODO`へ倒れていたが、知見66で`uipath_expr`に
  Lark呼び出し前のプリスキャン(`_prescan_interpolated_strings()`)を
  追加し解消済み。書式指定子・フィールド幅(`{expr:format}`/
  `{expr,width}`)のみ、VBの書式指定子をPython側へ正確に対応させる確証が
  無いため、でっち上げた変換をせず`# TODO`へ倒れる(未対応のまま記録)。
- **`And`/`Or`/`Xor`自体の相対優先順位(2026-11-05、`dump_daemon/uipath_expr/`
  のバグとして発見・修正)**: VB.NET公式仕様(Microsoft Learn「Operator
  Precedence - Visual Basic」)では論理/ビット演算子群の優先順位は高い順に
  `Not` > `And`/`AndAlso` > `Or`/`OrElse` > `Xor`(`Xor`が最も緩い)だが、
  `uipath_expr`の文法実装は`Or`と`Xor`の相対順が逆になっていた(`And`/`Or`/
  `Xor`を括弧無しで混在させる実機データが無かったため長らく未検出)。
  修正済み、詳細は`dump_daemon/uipath_expr/__init__.py`のモジュール
  docstringと`tests/test_uipath_expr.py`の
  `test_and_or_xor_relative_precedence_matches_official_vb_spec`参照。
- **全演算子の優先順位チェーン全体を公式表と再突き合わせ(2026-11-05、
  知見46の延長で実施、VM不使用・バグ無し)**: 知見41で`And`/`Or`/`Xor`の
  相対順バグを見つけた反省から、`uipath_expr`の文法が持つ優先順位
  チェーン全体(`xor_expr→or_expr→and_expr→not_expr→comparison→
  concat→add_expr→mod_expr→intdiv_expr→muldiv_expr→unary_expr→
  power_expr→atom`、緩い順)を、Microsoft Learn「Operator Precedence -
  Visual Basic」の完全な表(`^` > 単項`+`/`-` > `*`/`/` > `\` > `Mod` >
  二項`+`/`-` > `&` > (ビットシフト、未実装・対象外) > 比較演算子 >
  `Not` > `And`/`AndAlso` > `Or`/`OrElse` > `Xor`、きつい順)と1対1で
  照合した。特に単項マイナスと`^`の相対順(`-2^2`がVBでは`-(2^2)`=`-4`
  になる、`^`の方が単項マイナスより強く結合する公式仕様)を実際に
  `parse_vb_expr("-2^2")`で確認し、`UnaryOp(op='-', operand=BinOp(op='^',
  ...))`という正しい構文木になることを確認済み——全チェーンにわたり
  食い違いは見つからなかった(新たな修正は無し、確認のみ)。

### `^`/`Not`——実機検証で確定・修正済み(2026-11-05、知見45)

知見44で「公式ドキュメントだけでは確定できない」として残していた2点を、
ユーザーの指示でVM(`pad2py-pad-host`)実機のUiPath Studio(Debug File、
隔離した`Sub1.xaml`フィクスチャ)で検証し、両方とも実在するバグと確定、
修正した(詳細は知見45参照):

- **`^`(累乗)**: 常にDouble型で計算される(Microsoft Learn「^
  Operator」)ため、VBの`2^2`は`4.0`相当になるがPythonの`2 ** 2`は整数
  `4`のまま——通常は数値として等価だが`CStr()`等での文字列化の見た目は
  変わりうる(この見た目の差異自体は現状未対応、下記参照)。それとは別に
  **負の底に非整数の指数**(例: `(-8.0) ^ 0.5`)を与えた場合、実機確認で
  VBは`NaN`を返すと確定した(例外ではなかった)。Pythonの`**`は同じ入力に
  対し**複素数**を返すため単純な`**`変換のままでは誤変換になる——
  負の底かつ指数が整数でない場合のみ`NaN`に分岐する式に修正済み。
- **`Not`**: And/Or/Xorと同じ型依存の二重性質(Booleanには論理否定、
  Integerにはビット反転/2の補数)を持つと実機確認で確定した
  (`Not 5`→`-6`)。Pythonに両方を正しく表現する単一演算子が無い
  (`~True`は`-2`)ため、実行時に`isinstance(_x, bool)`で分岐するラムダ式
  に修正済み。

**(解決、知見46)** `^`の計算結果がVBでは常にDouble(`CStr`での見た目が
`4.0`のように変わりうる)という、値ではなく文字列表現上の差異は、
`CStr(Double)`/`&`の書式変換を公式ドキュメント(G書式)に基づき修正した
ことで解消した——`CStr(x)`/`&`は両方とも`_vb_cstr()`ヘルパー経由になり、
`CStr(4.0)`は`"4"`(VBと一致)を返すようになった。

**既知の残課題(軽微、未対応、知見46参照)**: G書式の指数表記の閾値・
書式(`E`大文字、2桁指数)とPythonの`e`表記の閾値・書式の違い、および
`ToString()`がカレントカルチャの小数点記号(例: `de-DE`ではカンマ)に
従う可能性は引き続き未対応。UiPath Robot/StudioはこのユーザーのVM環境
では常にen-USロケールと考えられ、実害が出る具体例が見つかるまでは
優先度低と判断。

## 現状のまとめ(2026-11-05)

演算子・リテラル・主要な型変換関数は知見32・36で実機確認済み、`And`/`Or`/`Xor`
の安全な変換アルゴリズムも設計・検証済み(上記「注意点」参照)。`Mod`/`\`/
`CInt`/`CBool`は公式ドキュメントとの突き合わせで値の食い違いが見つかり
修正済み(知見42・43)。`^`/`Not`の2点も実機検証(知見45)で実在するバグと
確定し修正済み。`CStr(Double)`/`&`の書式差(知見46)、比較演算子の型混在
(知見47)、`+`/`-`/`*`/`/`/`Mod`/`\`の型混在・ゼロ除算(知見48〜50)、
Booleanオペランドの数値変換(知見51)、`CDbl`/`CInt`の`Nothing`/桁区切り
文字列(知見52・53、.NETランタイム本体のソースで確定)、`Mod`/`\`の
ゼロ除算・`\`の銀行丸め先行(知見54、同じくランタイム本体のソースで
確定)も全て公式ドキュメント(またはランタイム実装ソース)で確定・
修正済み——このドキュメントが扱う変換表としての「未確認」項目は実質
ゼロになった(G書式の指数表記・カルチャ依存の小数点記号という軽微な
残課題のみ、上記各節参照)。パーサー自体も
`dump_daemon/uipath_expr/`(Lark文法に
よる自作、`pad_expr`とは別設計)として実装済みで、
`dump_daemon/uipath_codegen/render.py`が
この変換表の内容をそのままコード生成ロジックへ反映している
(`tests/test_uipath_expr.py`・`tests/test_uipath_codegen.py`で検証済み)。

### その他の構造(単純な式変換の範囲外、意図的に未対応のまま)

- メンバアクセス `obj.Member` → Python `obj.member`(属性名の大文字小文字規約は
  PythonとVBで違う——変換時に.NET側のPascalCase属性名をどう扱うかは、ラップ用の
  Pythonオブジェクト設計次第)
- メソッド呼び出し `obj.Method(args)` → 知見確認済みのTier1関数
  (`CStr`/`CInt`/`CDbl`/`CBool`/`IsNothing`/`String.IsNullOrEmpty`/三項`If`)
  以外は`render.py`の`_render_func_call`が意図的に`NotImplementedError`を
  送出する(でっち上げを避ける方針、`# TODO`へ倒れる)——任意の.NET API呼び出し
  をPython側でどう再現するかは単純な式変換を超える別問題で、v1スコープ外のまま。
