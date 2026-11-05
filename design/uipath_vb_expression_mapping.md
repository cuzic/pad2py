# VB.NET式 → Python式 変換ルール(初期整理)

[design/uipath_xaml_findings.md](uipath_xaml_findings.md)知見2で確認した通り、UiPathの
XAML中の式(`InArgument`/`OutArgument`/アクティビティのプロパティ値等)は、角括弧
`[...]`で囲んだVB.NET式テキストとしてそのまま埋め込まれる。変換にはVB.NET式パーサー/
トランスパイラが新規に必要で、PAD用の式パーサー(`pad_expr`)は流用できない
(構文が全く別物)。

本ドキュメントは、その変換表の初期整理。**VB.NETは公開されている言語仕様であり、
UiPath固有のデコンパイル知識は不要**——以下は原則として公開のVB.NET言語仕様に基づく
机上整理であり、実機XAMLで個別に裏取りしたのは「確認済み」と明記した項目のみ
(知見2・5・14・30・32)。それ以外は実装時に改めてUiPath Studio上で実際に確認してから
コード化すべき(でっち上げを避けるpad2pyの方針を踏襲)。

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
| 剰余 `Mod` | 同上 | `%` |
| 整数除算 `\` | 同上 | `//` |
| 累乗 `^` | 同上 | `**` |
| `And` / `Or`(非短絡評価) | 同上(構文としての受理は知見32)。変換ルールは2026-11-05にPython実挙動で検証し確定(下記「注意点」参照) | `(a) & (b)` / `(a) \| (b)`(ビット演算子、両オペランドを必ず括弧で囲む) |
| `AndAlso` / `OrElse`(短絡評価) | 同上 | `and`/`or` |
| `Not` | 同上 | `not` |
| `Xor` | 同上 | `(a) ^ (b)`(ビット演算子。`And`/`Or`の`&`/`|`と同じ理由でPython実挙動で検証済み、下記「注意点」参照) |
| `CStr(x)` | 同上 | `str(x)` |
| `True` / `False` | 同上 | `True` / `False` |
| `IsNot`(参照比較の否定) | `[CStr(If(result IsNot Nothing, "notnothing", "isnothing")) & ...]`(知見36、実機コンパイル確認) | `is not` |
| `Nothing` | 同上 | `None` |
| 三項演算子 `If(cond, whenTrue, whenFalse)` | 同上 | `whenTrue if cond else whenFalse` |
| `CInt(x)` | `[... & CStr(CInt("5")) & ...]`(知見36、実機コンパイル確認) | `int(x)`(ただしVBの`CInt`は四捨五入、Pythonの`int()`は切り捨て——丸め方向の違いに注意) |
| `CDbl(x)` | 同上 | `float(x)` |
| `CBool(x)` | 同上 | `bool(x)` |
| `IsNothing(x)` | 同上 | `x is None` |
| 文字列補間 `$"...{expr}..."` | `[$"value={result}-end"]`(知見36、実機コンパイル確認——`{`/`}`含めそのまま`[...]`内に直列化される) | f-string `f"...{expr}..."` |
| `String.IsNullOrEmpty(x)` | `[CStr(String.IsNullOrEmpty("")) & ...]`(知見36、実機コンパイル確認) | `not x`(ただし空白のみの文字列の扱いに差——`String.IsNullOrWhiteSpace`との混同に注意) |
| 文字列中のダブルクォートエスケープ `""` | `["He said ""hi"" today"]`(知見36、実機コンパイル確認——VB文字列リテラル内では`""`が`"`1個を表す) | `\"` |

### 確認済み演算子の変換上の注意点

- **`&`(文字列結合)**: VB `&`は非文字列オペランドを自動的に文字列へ変換するが、
  Pythonの`+`はしない——変換側で`str(x)`を明示的に挟む必要がある。
- **`\`(整数除算)**: VBの`\`(バックスラッシュ)と`/`(浮動小数点除算)は別演算子
  ——`/`は常に浮動小数点結果になる点もPythonの`/`と一致(Python 3)。
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

## 未確認・公開VB.NET仕様に基づく机上整理(実装前に要裏取り)

演算子・リテラル・主要な型変換関数は知見32・36で実機確認済み。`And`/`Or`の
安全な変換アルゴリズムも2026-11-05に設計・検証済み(上記「注意点」参照)。
残るのは`String.IsNullOrEmpty`等の個別API挙動差のみ。

### その他の構造

- メンバアクセス `obj.Member` → Python `obj.member`(属性名の大文字小文字規約はPythonとVBで違う——変換時に.NET側のPascalCase属性名をどう扱うかは、ラップ用のPythonオブジェクト設計次第)
- メソッド呼び出し `obj.Method(args)` → 基本的にそのまま`obj.method(args)`(ただし.NET API呼び出し自体をPython側でどう再現するかは別問題——単純な式変換の範囲外)

## 今後の作業

1. 残る「未確認」項目は`String.IsNullOrEmpty`と文字列中のダブルクォート
   エスケープ`""`のみ(他の主要演算子・関数は知見32・36で実機確認済み)。
2. `And`/`Or`の非短絡評価からPythonへの安全な変換ルール(評価順序・副作用を
   保つ変換パターン)は構文確認だけでは解決しない——実際の変換アルゴリズム
   設計時に改めて検討が必要。
3. VB.NET式のパーサー自体は、既存のOSS(例: Roslyn系のVB.NETパーサーをPythonから
   呼び出す、またはPython製のVB.NET文法パーサーを新規に書く)を使うか自作するかの
   方式検討が必要——pad2pyの`pad_expr`(PAD独自構文向け)とは別物として設計する。
