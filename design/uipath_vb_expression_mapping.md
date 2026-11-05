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
| `And` / `Or`(非短絡評価) | 同上(構文としての受理のみ確認、非短絡という実行時意味論自体は公開仕様通り) | `&`/`\|` または `and`/`or`(下記「注意点」参照) |
| `AndAlso` / `OrElse`(短絡評価) | 同上 | `and`/`or` |
| `Not` | 同上 | `not` |
| `Xor` | 同上 | ブール同士なら`!=`、整数同士なら`^` |
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
- **`And`/`Or`(非短絡評価)の変換——重要な意味論の罠**: VBの`And`/`Or`は
  ブール型同士でも両辺を必ず評価する非短絡演算子。Pythonの`and`/`or`は
  短絡評価。安易に`and`/`or`へ置き換えると、副作用のある式(例外送出を含む)の
  評価タイミングが変わりうる。知見32で構文としての受理は確認したが、
  安全な変換ルール自体は未確定——要検証。`AndAlso`/`OrElse`(短絡評価)は
  Pythonの`and`/`or`と意味論が一致するため、こちらは素直に変換してよい。
- **`Xor`**: ブール同士なら`!=`、整数同士なら`^`——型によって変換先が変わる。

## 未確認・公開VB.NET仕様に基づく机上整理(実装前に要裏取り)

演算子・リテラル・主要な型変換関数は知見32・36で実機確認済み。残るのは
個別APIの挙動差(下記)と、変換アルゴリズム設計そのものの課題のみ。

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
