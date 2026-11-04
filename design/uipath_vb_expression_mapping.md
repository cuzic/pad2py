# VB.NET式 → Python式 変換ルール(初期整理)

[design/uipath_xaml_findings.md](uipath_xaml_findings.md)知見2で確認した通り、UiPathの
XAML中の式(`InArgument`/`OutArgument`/アクティビティのプロパティ値等)は、角括弧
`[...]`で囲んだVB.NET式テキストとしてそのまま埋め込まれる。変換にはVB.NET式パーサー/
トランスパイラが新規に必要で、PAD用の式パーサー(`pad_expr`)は流用できない
(構文が全く別物)。

本ドキュメントは、その変換表の初期整理。**VB.NETは公開されている言語仕様であり、
UiPath固有のデコンパイル知識は不要**——以下は原則として公開のVB.NET言語仕様に基づく
机上整理であり、実機XAMLで個別に裏取りしたのは「確認済み」と明記した項目のみ
(知見2・6)。それ以外は実装時に改めてUiPath Studio上で実際に確認してから
コード化すべき(でっち上げを避けるpad2pyの方針を踏襲)。

## 確認済み(実機XAMLで裏取り)

| VB.NET | 実機確認の文脈 | Python |
|---|---|---|
| 文字列リテラル `"..."` | `Text="[&quot;Hello from pad2py&quot;]"` (知見2) | `"..."`(同じ) |
| 変数参照 `varName` | `<OutArgument ...>[result]</OutArgument>` (知見2) | `varName`(同じ) |
| 等価比較 `=` | `Condition="[result=&quot;ok&quot;]"` (知見5) | `==` |
| 配列/コレクションリテラル `{a, b, c}` | `Values="[{&quot;a&quot;,&quot;b&quot;,&quot;c&quot;}]"` (知見5) | `[a, b, c]` |
| メンバ参照(裸の変数名、ループデリゲート変数含む) `item` | `Text="[item]"` (知見5) | `item`(同じ) |

## 未確認・公開VB.NET仕様に基づく机上整理(実装前に要裏取り)

### 演算子

| VB.NET | 意味 | Python | 注意点 |
|---|---|---|---|
| `&` | 文字列結合 | `+`(str同士) または f-string | VB `&`は非文字列オペランドを自動的に文字列へ変換するが、Pythonの`+`はしない——変換側で`str(x)`を明示的に挟む必要がある |
| `<>` | 不等価 | `!=` | |
| `Mod` | 剰余 | `%` | |
| `\` | 整数除算 | `//` | VBの`\`(バックスラッシュ)と`/`(浮動小数点除算)は別演算子——`/`は常に浮動小数点結果になる点もPythonの`/`と一致(Python 3) |
| `^` | 累乗 | `**` | |
| `And` / `Or` | 論理AND/OR(**非短絡評価**) | `&`/`\|`(ビット演算、bool同士ならビット演算がブール演算として働く) または `and`/`or` | **重要な意味論の罠**: VBの`And`/`Or`はブール型同士でも両辺を必ず評価する非短絡演算子。Pythonの`and`/`or`は短絡評価。安易に`and`/`or`へ置き換えると、副作用のある式(例外送出を含む)の評価タイミングが変わりうる。安全な変換は未確定——要検証 |
| `AndAlso` / `OrElse` | 論理AND/OR(短絡評価) | `and`/`or` | こちらはPythonの`and`/`or`と意味論が一致 |
| `Not` | 論理否定 | `not` | |
| `Xor` | 排他的論理和 | ブール同士なら`!=`、整数同士なら`^` | 型によって変換先が変わる点に注意 |
| `Is` / `IsNot` | 参照比較 | `is` / `is not` | |

### リテラル・定数

| VB.NET | Python |
|---|---|
| `Nothing` | `None` |
| `True` / `False` | `True` / `False`(大文字小文字のみ違う) |
| 文字列中のダブルクォートエスケープ `""` | `\"` |

### 関数・型変換

| VB.NET | Python |
|---|---|
| `CStr(x)` | `str(x)` |
| `CInt(x)` | `int(x)`(ただしVBの`CInt`は四捨五入、Pythonの`int()`は切り捨て——丸め方向の違いに注意、`round()`との使い分けが必要) |
| `CDbl(x)` | `float(x)` |
| `CBool(x)` | `bool(x)` |
| `IsNothing(x)` | `x is None` |
| `String.IsNullOrEmpty(x)` | `not x`(ただし空白のみの文字列の扱いに差——`String.IsNullOrWhiteSpace`との混同に注意) |
| `If(cond, whenTrue, whenFalse)`(VBの三項演算子関数) | `whenTrue if cond else whenFalse` |
| `$"...{expr}..."`(文字列補間) | f-string `f"...{expr}..."` |

### その他の構造

- メンバアクセス `obj.Member` → Python `obj.member`(属性名の大文字小文字規約はPythonとVBで違う——変換時に.NET側のPascalCase属性名をどう扱うかは、ラップ用のPythonオブジェクト設計次第)
- メソッド呼び出し `obj.Method(args)` → 基本的にそのまま`obj.method(args)`(ただし.NET API呼び出し自体をPython側でどう再現するかは別問題——単純な式変換の範囲外)

## 今後の作業

1. 上記の「未確認」項目を、実際にUiPath Studioで小さいサンプル式(Assignの値欄等)を
   組んで保存し、生成XAMLの文字列と突き合わせて検証する(知見2・5・8と同じ手法)。
   特に`And`/`Or`と`AndAlso`/`OrElse`の使い分けは実務フローでの出現頻度が高いと
   予想され、優先的に検証する価値がある。
2. VB.NET式のパーサー自体は、既存のOSS(例: Roslyn系のVB.NETパーサーをPythonから
   呼び出す、またはPython製のVB.NET文法パーサーを新規に書く)を使うか自作するかの
   方式検討が必要——pad2pyの`pad_expr`(PAD独自構文向け)とは別物として設計する。
