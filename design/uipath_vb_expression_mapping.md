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
| 等価比較 `=` | `Condition="[result=&quot;ok&quot;]"` (知見5) | `==` |
| 配列/コレクションリテラル `{a, b, c}` | `Values="[{&quot;a&quot;,&quot;b&quot;,&quot;c&quot;}]"` (知見5) | `[a, b, c]` |
| メンバ参照(裸の変数名、ループデリゲート変数含む) `item` | `Text="[item]"` (知見5) | `item`(同じ) |
| 不等価 `<>` | `ExpressionText="result&lt;&gt;&quot;x&quot;"`(`While`の`Condition`、知見14) | `!=` |
| 参照比較 `Is`(`Nothing`判定含む) | `Transition.Condition>[SystemException is Nothing]`(UiPath公式REFrameworkテンプレートの実例、知見30) | `is`(`is None`等) |
| 文字列結合 `&` | 知見32、9演算子複合式の実機コンパイル確認 | `+`(str同士) または f-string(下記「注意点」参照) |
| 剰余 `Mod` | 同上 | `(a) - ((b) * int((a) / (b)))`(単純な`%`では不可、下記「注意点」参照) |
| 整数除算 `\` | 同上 | `int((a) / (b))`(単純な`//`では不可、下記「注意点」参照) |
| 累乗 `^` | 同上 | `**`(ただし残る未確認リスクあり、下記「注意点」参照) |
| `And` / `Or`(非短絡評価) | 同上(構文としての受理は知見32)。変換ルールは2026-11-05にPython実挙動で検証し確定(下記「注意点」参照) | `(a) & (b)` / `(a) \| (b)`(ビット演算子、両オペランドを必ず括弧で囲む) |
| `AndAlso` / `OrElse`(短絡評価) | 同上 | `and`/`or` |
| `Not` | 同上(ただし確認済みはBooleanオペランドのみ、下記「注意点」参照) | `not`(Booleanのみ確認済み) |
| `Xor` | 同上 | `(a) ^ (b)`(ビット演算子。`And`/`Or`の`&`/`|`と同じ理由でPython実挙動で検証済み、下記「注意点」参照) |
| `CStr(x)` | 同上 | `str(x)` |
| `True` / `False` | 同上 | `True` / `False` |
| `IsNot`(参照比較の否定) | `[CStr(If(result IsNot Nothing, "notnothing", "isnothing")) & ...]`(知見36、実機コンパイル確認) | `is not` |
| `Nothing` | 同上 | `None` |
| 三項演算子 `If(cond, whenTrue, whenFalse)` | 同上 | `whenTrue if cond else whenFalse` |
| `CInt(x)` | `[... & CStr(CInt("5")) & ...]`(知見36、実機コンパイル確認) | `round(float(x))`(2026-11-05修正、知見42参照——VBの`CInt`は銀行丸め/round-half-to-even、単純な`int()`は切り捨てで食い違う。例: `CInt(1.5)`は`2`だが`int(1.5)`は`1`。Pythonの`round()`も単一引数では既定でround-half-to-evenのため一致する) |
| `CDbl(x)` | 同上 | `float(x)` |
| `CBool(x)` | 同上 | 引数が文字列リテラルならコード生成時に`"True"`/`"False"`(大文字小文字無視)か数値として確定済みの`True`/`False`を埋め込む(2026-11-05修正、知見42参照——Pythonの`bool(文字列)`は空文字列以外は常に`True`になり食い違う。例: `bool("False")`は`True`)。リテラル以外(変数参照等)は実行時の型が不明なため`bool(x)`のまま(既知の限界、文字列型なら上記と同じ理由で誤りうる) |
| `IsNothing(x)` | 同上 | `x is None` |
| 文字列補間 `$"...{expr}..."` | `[$"value={result}-end"]`(知見36、実機コンパイル確認——`{`/`}`含めそのまま`[...]`内に直列化される) | f-string `f"...{expr}..."` |
| `String.IsNullOrEmpty(x)` | `[CStr(String.IsNullOrEmpty("")) & ...]`(知見36、実機コンパイル確認) | `not x`(ただし空白のみの文字列の扱いに差——`String.IsNullOrWhiteSpace`との混同に注意) |
| 文字列中のダブルクォートエスケープ `""` | `["He said ""hi"" today"]`(知見36、実機コンパイル確認——VB文字列リテラル内では`""`が`"`1個を表す) | `\"` |

### 確認済み演算子の変換上の注意点

- **`&`(文字列結合)**: VB `&`は非文字列オペランドを自動的に文字列へ変換するが、
  Pythonの`+`はしない——変換側で`str(x)`を明示的に挟む必要がある。
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
  - `AndAlso`/`OrElse`(短絡評価)はPythonの`and`/`or`と意味論が完全一致
    するため、引き続きそのまま変換してよい(変更なし)。
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
- **`And`/`Or`/`Xor`自体の相対優先順位(2026-11-05、`dump_daemon/uipath_expr/`
  のバグとして発見・修正)**: VB.NET公式仕様(Microsoft Learn「Operator
  Precedence - Visual Basic」)では論理/ビット演算子群の優先順位は高い順に
  `Not` > `And`/`AndAlso` > `Or`/`OrElse` > `Xor`(`Xor`が最も緩い)だが、
  `uipath_expr`の文法実装は`Or`と`Xor`の相対順が逆になっていた(`And`/`Or`/
  `Xor`を括弧無しで混在させる実機データが無かったため長らく未検出)。
  修正済み、詳細は`dump_daemon/uipath_expr/__init__.py`のモジュール
  docstringと`tests/test_uipath_expr.py`の
  `test_and_or_xor_relative_precedence_matches_official_vb_spec`参照。

### 残る未確認リスク(2026-11-05、知見42・43の系統の調査で洗い出したが確定できなかったもの)

知見42(`Mod`/`\`)・知見43(`CInt`/`CBool`)で見つかった「公式ドキュメントで
確認すると実は値が食い違う」パターンに基づき、他の演算子も同じ観点で
洗い直した結果、以下の2点は**公式ドキュメントだけでは確定できず、
実機検証(VM)が無いと白黒つけられない**ため、コードは変更せず既知の
リスクとして記録するに留めた(`dump_daemon/uipath_codegen/render.py`の
該当箇所にも同内容のコメントあり):

- **`^`(累乗)は常にDouble型で計算される**(Microsoft Learn「^ Operator」)
  ため、VBの`2^2`は`4.0`相当になるがPythonの`2 ** 2`は整数`4`のまま——
  通常は数値として等価だが、`CStr()`等で文字列化した際の見た目が変わる
  可能性がある(未検証)。さらに**負の底に非整数の指数**(例:
  `(-8) ^ 0.5`)を与えた場合、VBAの関連ドキュメントは「指数が整数でない
  限り底は負であってはならない」と示唆しているが、VB.NET側が実際に
  何を返す(例外・`NaN`相当)かは公式ドキュメントで確認できなかった。
  Pythonの`**`は同じ入力に対し**複素数**を返す(`(-8) ** 0.5` →
  `(1.73...e-16+2.83j)`)ため、もしVBが例外や`NaN`を返すなら誤変換になる
  ——でっち上げた分岐処理は挿入せず、単純な`**`変換のまま残した。
- **`Not`はAnd/Or/Xorと同じ型依存の二重性質**(Booleanには論理否定、
  Integerにはビット反転/2の補数)を持つが、`&`/`|`/`^`のような単一の
  Python演算子で両方を正しく表現できない(`~True`は`-2`になり論理否定の
  `False`と一致しない)。知見32・36の実機確認例は`Not True`
  (Booleanオペランド)のみで、Integerオペランドの実例・実機検証が無い
  ため、型判定のでっち上げコードは挿入せず、確認済みのBoolean前提のまま
  `not (...)`とした——Integerオペランドへの`Not`適用が実際に発生する
  ワークフローが見つかった時点で改めて対応する。

## 現状のまとめ(2026-11-05)

演算子・リテラル・主要な型変換関数は知見32・36で実機確認済み、`And`/`Or`/`Xor`
の安全な変換アルゴリズムも設計・検証済み(上記「注意点」参照)。`Mod`/`\`/
`CInt`/`CBool`は公式ドキュメントとの突き合わせで値の食い違いが見つかり
修正済み(知見42・43)。`^`/`Not`の2点は公式ドキュメントだけでは確定
できない残課題として明示的に記録した(上記)——このドキュメントが扱う
変換表としての「未確認」項目は、この2点を除いて実質ゼロになった。
パーサー自体も`dump_daemon/uipath_expr/`(Lark文法による自作、`pad_expr`
とは別設計)として実装済みで、`dump_daemon/uipath_codegen/render.py`が
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
