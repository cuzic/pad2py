# PADの内部アセンブリ逆コンパイルによる文法の裏付け(Robin Language)

## 背景・経緯

design/dsl_format_findings.md はこれまで、実機PADでアクションを1つずつ追加して「コピーとして貼り付け」の出力を観察する、という帰納的な手法でDSL文法を解明してきた(知見1〜26)。この方法では、個別のアクションの挙動は確認できるが、「なぜ一部のデフォルト値は省略され一部は省略されないのか」(知見19〜21・23)のような**文法全体に関わる規則**は、1アクションずつ試す限り永遠に収束しない("モグラ叩き"になる)という指摘をユーザーから受けた。

PAD Desktop は .NET(WPF)アプリケーションであり、「コピーとして貼り付け」機能のシリアライザは実際にインストールされているDLLの中にIL(中間言語)として存在する。これをデコンパイルして**一次ソースとしてのロジック**を直接読むことで、個別の実機検証よりもはるかに効率的かつ確実に文法全体を把握できると判断し、ユーザーの明示的な了承を得た上で実施した。

## 手法

1. `~/.dotnet`(.NET 8 SDK + .NET 6 ランタイム、サンドボックスにインストール)経由で `ilspycmd`(クロスプラットフォームの.NET逆コンパイラ、dotnet tool、バージョン8.2.0.7535)をインストール。
2. WinRM(`pywinrm`)経由で、PAD実機VM(`pad2py-pad-host`)の `C:\Program Files (x86)\Power Automate Desktop\Microsoft.Flow.RPA.Desktop.Robin.Language.dll`(578,888バイト)をBase64エンコードで取得。
3. `ilspycmd -p -o <outdir> Robin.Language.dll` でC#ソースに逆コンパイル(291ファイル生成)。
4. `grep`で`"THEN"`等のDSL特有文字列をキーに、関連クラスを特定して読み込んだ。
5. (後続のティックで)同じ手法で`Microsoft.Flow.RPA.Desktop.Modules.UIAutomation.Actions.dll`
   (197ファイル)と`Modules.MouseAndKeyboard.Actions.dll`も取得・逆コンパイルした。

**注記**: 逆コンパイルした.NETアセンブリはPAD(Microsoft製品)の著作物であり、このリポジトリには一切コミットしていない(サンドボックスのスクラッチ領域のみに保持)。本ドキュメントは確認した事実(クラス名・文字列リテラル・シリアライズロジックの要旨)を独自の言葉で要約したものであり、デコンパイルされたコード自体の転載は行っていない。相互運用性の調査目的で、自分のライセンスで導入した自分のPADインストールを対象にしている。

PADの内部コード名は **"Robin"** であることが判明した(アセンブリ名・名前空間が全て`*.Robin.*`)。

## 確認できた事実(ソースコードによる裏付け)

### インデントは正確に4スペース

`BaseBlock`クラスに以下の定数が存在する:

```
protected const int IndentationSpacesPerLevel = 4;
protected string IndentationText => string.Empty.PadLeft(Level * 4);
```

知見7の実機検証(4スペース)と完全に一致。各`IStatement`は`Level`という整数プロパティを持ち、`BaseBlock`は`List<IStatement>`をフラットに保持して`Level * 4`でインデントして`ToString()`する——つまりPAD自身の内部表現も、我々の`indent`フィールド+フラットリストという設計(知見7・10)と同じ考え方だった。

### 比較演算子は8種類、`Contains`等は演算子ではなく完全に別の仕組み

`ComparisonOperator` enum:

```
EqualTo, NotEqualTo, LessThan, LessThanOrEqualTo, GreaterThan, GreaterThanOrEqualTo, In, NotIn
```

`ComparisonOperatorExtensions.ToString(TextFormatOptions format)` が実際の記号を定義している:

| enum値 | 記号(Upper format) |
| --- | --- |
| EqualTo | `=` |
| NotEqualTo | `<>` |
| LessThan | `<` |
| LessThanOrEqualTo | `<=` |
| GreaterThan | `>` |
| GreaterThanOrEqualTo | `>=` |
| In | `IN` |
| NotIn | `NOT IN` |

知見18で実機確認した6種類(`=`/`<>`/`<`/`<=`/`>`/`>=`)と完全一致。**新発見**: `In`/`NotIn`という7・8番目の値が存在する(実機のIf/Loop conditionダイアログの16択Operatorドロップダウンには無かった——別のUI経路(おそらく式エディタ)でのみ使われると見られ、未確認)。

**重要**: `Contains`/`Does not contain`/`Starts with`等のテキスト演算子は、この`ComparisonOperator` enumに**一切含まれていない**。これらは別の仕組み(後述の`FunctionExpression`)であり、知見18-2で実機確認した「関数呼び出し構文」という理解が完全に正しかったことが裏付けられた。

**既知の未検証ギャップ**: `NOT IN`は半角スペースを含む**2トークン**の演算子記号である。現在のパーサー(`_parse_line`)は`IF <operand1> <operator> <operand2> THEN`を`operator`が単一トークンである前提で`tokens[2]`として読んでいるため、もし実際に`NOT IN`が使われるDSL行に遭遇すると誤パースする。実機で`In`/`Not in`を使うUI経路が未特定のため、今回は修正を見送り、既知のギャップとして記録するに留めた。

### 制御構文のToString実装(全て実機知見と一致)

| クラス | `ToString()`が生成する形式 | 対応する知見 |
| --- | --- | --- |
| `AssignStatement` | `SET <var> TO <expr>` | 知見5 |
| `IfStatement` | `IF <expr> THEN` | 知見6 |
| `ElseIfStatement`(`IfStatement`を継承) | `ELSE IF <expr> THEN` | 知見11 |
| `ElseStatement` | `ELSE` | 知見11 |
| `EndStatement` | `END` | 知見6 |
| `LoopStatement` | `LOOP <var> FROM <from> TO <to> STEP <step>` | 知見8 |
| `ForEachStatement` | `LOOP FOREACH <var> IN <iterator>` | 知見9 |
| `WhileStatement` | `LOOP WHILE <expr>` | 知見9 |
| `BreakStatement` | `EXIT LOOP` | 知見12 |
| `ContinueStatement` | `NEXT LOOP` | 知見12 |
| `SwitchStatement` | `SWITCH <expr>` | **新発見・未検証** |
| `CaseStatement` | `CASE <value>` | **新発見・未検証** |
| `CommentStatement` | `# <comment>`(単一行)/ `/# <comment> #/`(複数行) | **新発見・未検証** |

`IfStatement`/`WhileStatement`はいずれも`Expression`(値の比較)または`Statement`(ネストした真偽値ステートメント、例: 「If window」のようなUI状態チェック系アクション)のどちらか一方を持つ設計になっている——`Expression`が`null`の場合は`"(" + Statement + ")"`という形式になる。これは「If window」「If window contains」のような、オペランド比較ではなくUI状態を直接評価するアクションの表現方法を示唆している(未検証)。

### `FunctionExpression`: 任意個数の引数を持つ汎用関数呼び出し構文

```
Name + "(" + string.Join(", ", Arguments) + ")"
```

引数の個数に制約がない汎用実装であることが確認できた。これは知見18-2・22で実装した`IfFunctionRecord`/`ElseIfFunctionRecord`(カンマ区切りで任意個数の引数をパースする設計)が、`Contains`だけでなく**`Does not contain`/`Starts with`/`Does not start with`/`Ends with`/`Does not end with`/`Is empty`/`Is not empty`/`Is blank`/`Is not blank`の全10種のテキスト演算子に対して構造的に正しく動作する**ことを裏付ける——引数の個数がアクションによって異なって(例: `Is empty`系は1引数のみ)も、`_FUNC_COND_RE`+カンマ分割という実装は引数個数に依存しないため、問題なく対応できる。実際に`Contains`以外の9種を実機で確認する作業は依然として必要(どの引数位置にどんな値が来るかはアクション依存のため)。

### `ParenthesisExpression`: `LOOP WHILE`の丸括弧の正体

```
"(" + Expression + ")"
```

知見9で発見した「`LOOP WHILE (LoopIndex) < (10)`はオペランドが丸括弧で囲まれる」という挙動は、`ComparisonExpression`自体ではなく(`ComparisonExpression.ToString()`は丸括弧を一切付けない)、各オペランドが個別に`ParenthesisExpression`でラップされていることによるものだと判明した。**未解明**: どの文脈で各オペランドが`ParenthesisExpression`に包まれるかを決めているロジックは、Language.dll(文法定義アセンブリ)ではなく、UI/アクションモジュール側(おそらく`Microsoft.Flow.RPA.Desktop.Modules.MouseAndKeyboard.Actions.dll`等)にあると推測されるが、今回は追跡していない。

### デフォルト値省略の謎(知見19〜21・23)は未解決のまま——理由も判明

`ActionStatement`(一般アクション行の構造)自体は、既に構築済みの`IInputArgument[] inputs`配列を受け取って`ToString()`するだけで、**「どのパラメータを配列に含めるか」を決めるロジックはLanguage.dll(文法層)には存在しない**。この判断は、各アクションモジュール(`Modules.MouseAndKeyboard.Actions.dll`等、50以上存在する個別のアクションDLL群)側のUI/シリアライズコードに委ねられていると考えられる。つまり「一貫した規則がない」という我々の結論(知見23)は、**実装上も一貫した規則が存在しない(各アクションの実装者がそれぞれ個別に判断している)可能性が高い**ことがアーキテクチャ面からも裏付けられた——今後この謎を解明するには、Language.dllではなく個別のアクションモジュールDLL群を調査する必要がある(今回はスコープ外)。

## デフォルト値省略の謎(知見19〜21・23)を完全に解明——`ActionSelector`の`Prop().ShouldBe()`/`Show()`パターン

上記「Language.dllにはこの判断ロジックが無い」という調査結果を受けて、実際にアクションモジュールDLL(`Microsoft.Flow.RPA.Desktop.Modules.MouseAndKeyboard.Actions.dll`、WinRM経由で取得・逆コンパイル)を調査し、**デフォルト値省略の謎を完全に解明した**。

PADの各アクションクラス(例: `SendKeys`、`SendMouseClick`、`PressReleaseKey`)は、`[InputArgument]`属性を持つプロパティの集合として定義される。しかし**1つのアクションクラスが、複数の`ActionSelector<T>`サブクラス("variant"=DSL上の`action_id`末尾)を持ちうる**。各`ActionSelector`のコンストラクタは以下の2種類の宣言を組み合わせる:

- **`Prop<T>(expr).ShouldBe(value)`**: 「このプロパティの値が`value`であることが、このvariantが選ばれるための条件」という**判別子(discriminator)**の宣言。
- **`Show<T>(expr)`** または **`ShowAll()`**: 「このプロパティ(群)をDSLのパラメータとして表示する」という宣言。

実例(`FocusAndSendKeysSelector`、`MouseAndKeyboard.SendKeys.FocusAndSendKeys`に対応):

```
UseName("FocusAndSendKeys");
Prop<SendKeysTo>(s => s.SendKeysTo).ShouldBe((SendKeysTo)0);   // 判別子: SendKeysTo == Foreground
Show<int>(s => s.DelayBetweenKeystrokes);
Show<bool>(s => s.SendTextAsHardwareKeys);
Show<EncryptableObject>(s => s.TextToSend);
```

同じ`SendKeys`クラスの別variant(`FocusAndSendKeysByTitleClassSelector`、`...FocusAndSendKeysByTitleClass`に対応)は判別子が異なり、`Show`される項目も増える:

```
UseName("FocusAndSendKeysByTitleClass");
Prop<SendKeysTo>(s => s.SendKeysTo).ShouldBe((SendKeysTo)3);   // 判別子: SendKeysTo == ByTitleClass
Show<int>(s => s.DelayBetweenKeystrokes);
Show<bool>(s => s.SendTextAsHardwareKeys);
Show<EncryptableObject>(s => s.TextToSend);
Show<string>(s => s.Title);   // By title/classモード固有の追加フィールド
Show<string>(s => s.Class);
```

**確立した規則**: あるプロパティがDSLのテキストに出力されるかどうかは、以下で決まる——

1. そのプロパティが、現在選ばれているvariant(=実際の`action_id`)の`ActionSelector`において`Prop().ShouldBe()`の**判別子として使われている**場合 → **DSLには出力されない**。なぜなら、その値は選ばれた`action_id`自体に既に暗示されており(「`FocusAndSendKeysByTitleClass`」という名前自体が`SendKeysTo == ByTitleClass`を意味する)、改めてパラメータとして書く必要が無いため。
2. それ以外(`Show()`または`ShowAll()`で明示的に示されているプロパティ)→ **値が`[DefaultValue]`属性と一致していてもDSLに出力される**。

これは`SendMouseClick`(知見21)でも完全に一致した。`SendMouseClickSelector`(`...SendMouseClick.Click`に対応)は:

```
UseName("Click");
Prop<bool>(c => c.MoveMouse).ShouldBe(false);   // 判別子: MoveMouse == false
Show<MouseClickType>(c => c.ClickType);
Show<int>(c => c.MillisecondsDelay);
Show<bool>(c => c.MoveMouse);                   // ← Propと同じプロパティだがShowも宣言されている
```

`MoveMouse`は`Prop().ShouldBe(false)`判別子であると同時に`Show()`でも宣言されているが、実機では省略されていた(知見21)——つまり**判別子として機能している間は、`Show()`が併記されていても判別子としての扱いが優先され、省略される**ことが実データと整合する。一方`ClickType`/`MillisecondsDelay`は判別子ではなく単なる`Show()`なので、`[DefaultValue(MouseClickType.LeftClick)]`/`[DefaultValue(0)]`という既定値と一致していても(実機ではまさにこの既定値を使った)、省略されずに出力されていた(`ClickType: ...LeftClick MillisecondsDelay: 0`)。

`PressReleaseKey`(知見23)も同様に完全解明できた。`PressKeySelector`(`...PressReleaseKey.PressKey`に対応):

```
UseName("PressKey");
Prop<KeyEventType>(c => c.Event).ShouldBe(KeyEventType.Press);   // 判別子: Event == Press
ShowAll();                                                        // 残り全フィールド(Control/Alt/Shift/Win)を無条件に表示
```

「Action to perform」(`Event`プロパティ)が判別子として`action_id`の末尾(`PressKey`/`ReleaseKey`)に変換されるため省略され、`ShowAll()`により残りの`Control`/`Alt`/`Shift`/`Win`は(触っていなくても)**無条件に全て**出力される——知見23で観測した「4つの真偽値が全部出力された」という挙動と完全に一致する。

**結論**: design/dsl_format_findings.md 知見19〜21・23で「アクション・フィールドごとに個別確認するしかない」としていた暫定結論は、**今回の`ActionSelector`のソースコード調査により、明確で一貫した規則(判別子は省略・Show/ShowAllは常に出力)に置き換えられた**。今後どのアクションがどのプロパティを省略するかを予測するには、そのアクションの`ActionSelector`サブクラス群(`Prop().ShouldBe()`と`Show()`/`ShowAll()`の宣言)を確認すればよい——UIを1つずつクリックして試行錯誤する必要はなくなった。

## 文字列エスケープの正確な規則(`StringExtensions.cs`で確認——2件のサイレントバグを修正)

`Microsoft.Flow.RPA.Desktop.Robin.Language.Extensions.StringExtensions`を読み、これまで
実機観察だけに基づいていた`\"`/`\\`エスケープの理解が**不完全だった**ことが判明した:

```csharp
public static string EscapeForRobin(this string str, bool interpolated)
{
    if (interpolated) str = str.Replace("%", "%%");
    return Regex.Replace(str, "(?=((\")|(')|(\\\\)))", "\\");
}
```

つまりエスケープ対象は`"`/`'`/`\`の**3種類**(`"`と`\`の2種類だけではない)。さらに
`interpolated`(= `$'''...'''`形式、すなわち`InterpolatedStringAtom`由来の値は常に真)の
場合、クォート類のエスケープより**先に**リテラル`%`が`%%`へ二重化される(`InterpolatedStringAtom.ToString()`
が各リテラル区間に`EscapeForRobin(interpolated: true)`を適用しているため確認済み)。

`pad_dsl_parser.py`の`_unescape()`は従来`\"`→`"`と`\\`→`\`しか解除しておらず、**`\'`の解除が
欠落していた**。これはサイレントなバグで、PADのテキストにアポストロフィ(`it's`、`don't`等、
英語の自動化タスクでは頻出)が含まれるたびに、生成Pythonコードへ不要なバックスラッシュが
そのまま混入していた(気づかれにくい理由: Pythonコード上で見た目に大きな破綻をしない)。
同様に`%%`→`%`の解除も欠落していた。両方とも本調査で修正し、回帰テストを追加した
(`tests/test_pad_dsl_parser.py`の`test_escaped_apostrophe_in_string_literal_is_unescaped`・
`test_doubled_percent_in_string_literal_is_unescaped`)。

また`StringAtom`(非interpolated、`$`プレフィックス無しの単純な`'...'`/`'''...'''`)という
別クラスも存在することを確認した。`pad_dsl_parser.py`はこの形式を一切扱っていないが、
実機でのPADアクションパラメータは(テキスト欄が常に`%Var%`補間に対応しているためか)
一貫して`InterpolatedStringAtom`(`$`プレフィックス付き)として出力されており、今回の
調査でも非interpolated形式の実例は一つも確認できなかった。対応未着手だが優先度は低いと判断。

## 複数行コメント(`/# ... #/`)のパーサー対応を実装

`CommentStatement.ToString()`(前セクション参照)のソース通り、`/# ` + `Comment.EscapeRobinComment()` + `#/`
という形式で実装した。`EscapeRobinComment`は`#/`と`\`の直前にのみ`\`を挿入する
(`"(?=((#/)|(\\\\)))"`への`Regex.Replace`)ため、本文中に`#/`という2文字が現れる場合に
限って正しくエスケープ解除できるよう、マスキング用正規表現を単純な非貪欲`.*?`ではなく
「エスケープされた`#/`・エスケープされた`\`・それ以外の任意の1文字」の繰り返しとして実装した
(単純な`.*?#/`だと、本文中の`\#/`(エスケープされた`#/`)に含まれる`#/`部分で早期に
マッチが終端してしまうサイレントバグになることを、自分で書いたテストで発見・修正した)。
また`/# `の直後に挿入される1文字の空白はデリミタの一部であり、コメント本文そのものでは
ないため、復号時に無条件で1文字分剥がす処理を実装した(実機でこの複数行形式そのものの
生成例はまだ確認できていないため、パーサーは対応したが実機未検証のまま)。

## 新発見: `SWITCH`/`CASE`/`DEFAULT`文と`ON ERROR`/`ON BLOCK ERROR`文(構文のみ確認、ブロック構造は未確認)

`Contexts.Statements`配下に以下のクラスも存在することを確認した(いずれも単体の`ToString()`
出力は確認できたが、**ネスト/ブロック構造を定義するScopeクラスが`Contexts.Blocks`配下には
見当たらず、indent深さの規則はまだ特定できていない**):

- `SwitchStatement.ToString()` → `"SWITCH " + Expression`(例: `SWITCH TestVar`)
- `CaseStatement.ToString()` → `"CASE " + SemiEvaluatableContext`(例: `CASE $'''foo'''`)
- `CaseDefaultStatement.ToString()` → `"DEFAULT"`(固定のベアキーワード、`CASE DEFAULT`ではない)
- `ExceptionCaseStatement.ToString()` → `Type`が`Statement`なら`"ON ERROR " + Case`、
  `Block`なら`"ON BLOCK ERROR " + Case`(例: `ON ERROR ErrorCase1`)。`IsUserDefinedErrorCode`が
  非nullの場合は末尾に` IsUserDefinedErrorCode: <expr>`が追加される。これはPADの各アクション/
  各アクショングループに設定できる「エラー発生時の動作」(Go to label的な機能)のDSL表現と推測される。

IF文と同じ「複数アームが1つの構文を共有しENDは1つだけ」という構造を安易に適用すると誤った
indentを生成する恐れがあるため、`build_block_tree()`・`pad_codegen.py`への実装は意図的に
見送った(`RawRecord`として素通しされる——未対応のアクションと同様、サイレントに壊れるのではなく
明示的に「未対応」として残る)。

## アクション行の正確な直列化規則を`StatementWithArguments`で確認(既存パーサーとの整合性チェック)

`StatementWithArguments.ToStringIgnoreMetadata()`を読み、既存の`ActionRecord`パーサーが
これまで実機データから帰納していた「`ActionId Param: Value ... Output=> Var`」という形式が、
ソースコード上でも正確に一致することを確認した:

```csharp
stringBuilder.Append(actionPath);
if (Inputs.Any())  stringBuilder.Append(" " + string.Join(" ", Inputs.Select(i => i.ToString(...))));
if (Outputs.Any()) stringBuilder.Append(" " + string.Join(" ", Outputs.Select(o => o.ToString(...))));
if (DynamicInputs.Any())  stringBuilder.Append(" " + string.Join(" ", DynamicInputs.Select(...)));
if (DynamicOutputs.Any()) stringBuilder.Append(" " + string.Join(" ", DynamicOutputs.Select(...)));
if (!Inputs.Any() && !Outputs.Any()) stringBuilder.Append(" _");
```

`InputArgument.ToString()` → `"Name" + ": " + Expression`(コロン+半角スペース)、
`OutputArgument.ToString()` → `"Name" + "=> " + Variable`(`=>`+半角スペース)——
いずれも既存パーサーが仮定している区切り文字と完全に一致した。

**新発見1**: Inputs/Outputsが両方とも0個のアクション(パラメータも出力も無い、例えば
「次のアクションへ進む」系の単純なトリガー的アクション)は、末尾に` _`(半角スペース+
アンダースコア)という**プレースホルダトークン**が付く。既存の`_parse_line()`はこの
トークンを「`:`も`=>`も付かない未知のトークン」として黙ってスキップするだけなので、
実害は無い(データロスは起きない)が、意図を把握しておく価値はある。なお、この判定は
`DynamicInputs`/`DynamicOutputs`を見ていないため、静的な`Inputs`/`Outputs`が0個でも
動的な引数を持つアクションでは、動的引数の**後に**この`_`が付く(未検証の組み合わせ)。

**新発見2(重要・既存パーサーの潜在的曖昧性)**: `Variable.ToString()`(`Contexts.Evaluatable.Variable`)
を読み、変数参照が単純な裸識別子だけではないことが判明した:

```csharp
return (HasGlobalPrefix ? "global." : "") + Name.Text
     + string.Join("", Trailers.Select(t => t.ToString(...)));
```

さらに`VariableTrailer.ToString()`は3種類の形を持つ:
- `Name`トレーラ: `"." + Name`(+ 引数があれば` (arg1 arg2 ...)`——**スペース区切り**で
  `Contains(a, b, c)`のようなカンマ区切りとは異なる)
- `Index`トレーラ: `"[" + Index + "]"`
- `Slice`トレーラ: (今回は未調査)

つまり`MyDataTable.Rows`や`MyList[0]`、`global.MySharedVar`のような変数参照が
存在しうる。**`.`で連結された`Name`トレーラは、既存の`_DOTTED_RE`(`Namespace.Enum.Value`
判定用)と字面上まったく区別できない**——`_resolve_value()`は現在、ドット区切りの
トークンを無条件に`EnumRef`として分類しているため、実際には「トレーラ付き変数参照」
だったトークンを誤って列挙値として分類してしまう可能性がある。これまでの実機データでは
単純な裸変数名(`TestVar`等)しか観測しておらず、トレーラ付き変数参照の実例は未確認のため、
現時点ではパーサーへの対応は見送る(誤った決め打ちをしないため)が、今後複雑な変数
(配列要素・カスタムオブジェクトのプロパティ等)を扱うフローを実機確認する際は、この
曖昧性の存在を前提に臨むこと。

## `ON ERROR`/`ON BLOCK ERROR`ブロックの完全な構造を解明(前回の「未解明点」を解消)

前回のティックで「`ExceptionStatement`がアクション行末尾にスペース無しで連結される点が
不自然」と持ち越していた謎を、`IExceptionStatement`の**実際の具象実装**
(`Microsoft.Flow.RPA.Desktop.Robin.Language.Contexts.Blocks.Exceptions.ExceptionStatementBase`——
前セクションの`ExceptionCaseStatement`とは別物で、こちらが本物)を読んで解消した。

`ExceptionStatementBase.ToString()`の先頭は`Environment.NewLine`から始まる(スペースではなく
**改行**)——これで「スペース無しで連結されていた」ように見えた謎が解けた。構造は:

```csharp
// ExceptionStatementBase.ToString(): indentation = base.IndentationText (= Level * 4)
NewLine + indentation + Repeat?.ToString()                              // 任意: リトライ設定
NewLine + join(NewLine, Cases.Select(c => indentation + c.ToString()))  // 任意: 名前付きエラーケース群
NewLine + indentation + CaseDefault?.ToString()                         // 任意: デフォルト(catch-all)
NewLine + indentation + "END"                                           // 必須: 終端
```

各`Case`(`ExceptionCaseScope`、`BaseBlockWithRoot`のサブクラス)は「ルート文(ヘッダー)+
本体」という構造で、`BaseBlockWithRoot.ToString()`が`RootStatement.ToString()`(ヘッダー行)と
`base.ToString()`(`BaseBlock`の本体、各本体文は`Level+1`のインデントで出力)を改行で連結する
(`SetLevel()`が`Cases`各要素のLevelを親の`Level + 1`に設定するのを確認済み)。ヘッダー行自体は
`ExceptionCaseStatement.ToString()`(前セクション)の`"ON ERROR " + Case`、`CaseDefault`
(`ExceptionCaseDefaultScope`、同様の構造)のヘッダーは`ExceptionCaseDefaultStatement.ToString()`の
**`"ON ERROR"`(ケース名無しの素のキーワード、`"ON ERROR "`と違って末尾スペース無し)**。

つまり実際にアクションへ付与された場合の全体像は(保護対象のアクション自身と同じインデント深さに
`ON ERROR`系ヘッダー・`END`が並び、本体だけが1段深い):

```
ActionId Param: Value ... Output=> Var
ON ERROR ErrorCase1
    <このケースで実行する本体アクション群>
ON ERROR ErrorCase2
    <このケースで実行する本体アクション群>
ON ERROR
    <デフォルト(catch-all)ケースの本体アクション群>
END
```

本体アクションの一部として使われると推測される専用キーワードも確認した:
`RepeatActionStatement.ToString()` → `"REPEAT ACTION"`(リトライ、`Repeat`プロパティ経由で
`Cases`より前に出力)、`NextActionStatement.ToString()` → `"NEXT ACTION"`(次のアクションへ
進む、`EXIT LOOP`/`NEXT LOOP`と同じ2トークン形式)。これらの正確な出現位置(本体内のどこに
置けるか)はまだ実機で確認していない。

**結論**: ブロック構造自体はソースコード上完全に解明できた(推測ではなく`BaseBlockWithRoot`/
`ExceptionStatementBase`/`SetLevel()`から直接確認)。残っている不確定要素は、このブロック
全体が実際に**どのアクション(action_id行)に対して、DSLテキスト上どこに現れるか**
(保護対象のアクション行の直後に続くという理解で合っているか)、および実機での出力例が
一つも無いことだけ。

## `SWITCH`/`CASE`/`DEFAULT`のブロックネスト構造をANTLR文法から類推し、パーサー/codegenに実装

前回のティックで最優先課題としていた「`SWITCH`/`CASE`/`DEFAULT`のネスト構造(indent規則)」を、
Printer側ではなく**ANTLRパーサー側**(`Microsoft.Flow.RPA.Desktop.Robin.Language.Parsing.Language.cs`、
ANTLR4で生成されたパーサー本体)から確認した。`Small_statementContext`(=「1つの単純文」という
文法規則)の子ルールアクセサを見ると:

```csharp
public If_statementContext if_statement() { ... }
public Elseif_statementContext elseif_statement() { ... }
public Else_statementContext else_statement() { ... }
public Switch_statementContext switch_statement() { ... }
public Case_statementContext case_statement() { ... }
public Case_defaultContext case_default() { ... }
public While_statementContext while_statement() { ... }
public Loop_statementContext loop_statement() { ... }
// ...
```

**`switch_statement`/`case_statement`/`case_default`は、`if_statement`/`elseif_statement`/
`else_statement`/`while_statement`/`loop_statement`と全く同じ文法規則(`small_statement`の
選択肢)として並列に定義されている**——つまりSWITCH/CASE/DEFAULTにも専用のブロック構造(ANTLRの
サブルール経由の入れ子)は存在せず、IF/ELSE IF/ELSEと全く同じ設計(フラットな文の並びを
indentだけで解釈する)になっていることが文法レベルで確定した。

この文法上の並列性を根拠に、`pad_dsl_parser.py`に`SwitchRecord`/`CaseRecord`/`CaseDefaultRecord`と
`SwitchNode`(`ConditionalNode`と同型——`arms: list[tuple[header, body]]`)を追加し、
`build_block_tree()`で`IF`/`ELSE IF`/`ELSE`と同じ規則(ヘッダー群は同じindent、各アームの本体は
indent+1、`END`は構文全体に1つ)を適用した。`pad_codegen.py`にも`if`/`elif`/`else`(`==`による
等価比較)への変換を追加した。

**明示しておくべき限界**: この実装は確認済みの文法的並列性からの合理的な類推であり、
SWITCH自身が実機で実際にこのインデント規則で出力されるかを直接確認したDSL例は無い
(`LOOP`のrange両端含む仮定と同種の、明示的に文書化された未検証の前提として扱う)。

> **【重要な訂正】実機検証の結果、上記のインデント規則の予測は誤りだったと判明した**
> (design/dsl_format_findings.md 知見33)。`CASE`/`DEFAULT`は`SWITCH`と同じindentではなく、
> `SWITCH`より1段深いindentに配置され、各アームの本体はさらに1段深かった(`SWITCH`→`CASE`の
> 関係も`CASE`→本体の関係も`LOOP`→本体と同じ構造——二重に重なっている)。「文法規則が並列
> だから印字時のインデント規則も同じ」という推論自体が誤りだった、という教訓。文法上の
> 並列性という発見自体(専用のBlock/Scopeクラスが無いこと)は正しいままで、`CASE`に演算子
> (`=`等)が明示されることも実機で確認済み。詳細・修正後の実装はdesign/dsl_format_findings.md
> 知見33を参照。

## ANTLR文法(`Language.cs`の`ExpressionContext`サブクラス群)で複合式・算術式・IN系演算子を一括確認

`SWITCH`/`CASE`/`DEFAULT`の構造解明に続けて、同じANTLR生成パーサー(`Language.cs`)の
`ExpressionContext`(値・条件式を表す汎用ルール)のサブクラス一覧を確認した:
`ArithmExpContext`/`ComparisonExpContext`/`FactorExpContext`/`FunctionExpContext`/
`InvalidExpContext`/`LogicalExpContext`/`NotExpContext`/`OperantExpContext`/`ParenthesisExpContext`。
これは`IF`の条件自体が(これまで仮定していた「オペランド1個+演算子1個+オペランド2個」という
固定3トークン構造ではなく)**再帰的な式木を許す汎用`expression()`ルール**として実装されている
ことを意味する——`If_statementContext.Expression => expression()?.ToEvaluatableContext();`で確認済み。

各クラスの`ToEvaluatableContext()`/対応する`Evaluatable.Expressions`配下の実装クラスの`ToString()`
から、以下が確定した:

- **`LogicalExpContext`→`LogicalExpression`**: `<expr1> AND <expr2>` / `<expr1> OR <expr2>` /
  `<expr1> XOR <expr2>`(`AND`/`OR`に加え**`XOR`も存在**——これまでのUIドロップダウンや
  研究ノートでは見た記憶が無く、ANTLR文法調査で初めて判明した)。いずれも単純な中置記法で
  キーワードは`keywordFormat`に応じて大文字化される。
- **`NotExpContext`→`NotExpression`**: `NOT <expr>`(前置、単項)。
- **`ArithmExpContext`→`ArithmeticExpression`**: `<expr1> + <expr2>` / `-` / `*` / `/` /
  `<expr1> mod <expr2>`(**`mod`だけは`keywordFormat`を経由せず常に小文字固定**——`ToCodeString()`
  がFormatStringを呼ばずに直接`"mod"`を返すため。他の演算子キーワードとの数少ない例外)。
- **`ComparisonExpContext`→`ComparisonExpression`/`SpecialComparisonExpression`**:
  `ComparisonOperatorExtensions.ToString(format)`で6つの対称演算子(`=`/`<>`/`<`/`<=`/`>`/`>=`)に
  加え`In`→`"IN"`、`NotIn`→`"NOT IN"`(**1つの`ToString()`呼び出しの戻り値として、内部に
  半角スペース1つを含む1つの文字列**)を確認。`NotIn`が`IsSpecialComparisonOperator()`で
  区別される特別な演算子だったため、`ComparisonExpression`と`SpecialComparisonExpression`という
  似た2クラスに分かれている(ToStringの出力形式自体はどちらも同じ)。

**実装した対応**: `NOT IN`はソース上確定した1演算子の直列化だが、空白区切りのDSLテキスト上では
2トークンに分かれるため、`pad_dsl_parser.py`に`_merge_not_in()`(隣接する`"NOT"`/`"IN"`トークンを
`"NOT IN"`へ結合)を追加し、`IF`/`ELSE IF`/`LOOP WHILE`の既存の固定位置ロジックを変更せずに
対応した(以前から既知だったギャップの解消)。`pad_codegen.py`の`_OPERATOR_MAP`にも
`"IN": "in"`/`"NOT IN": "not in"`を追加した(Pythonの`in`/`not in`はPADの「含まれるか」という
意味とそのまま対応する自然な写像と判断)。

**実装を見送った対応**: `AND`/`OR`/`XOR`/`NOT`による複合条件式、`+`/`-`/`*`/`/`/`mod`による
算術式は、いずれも**再帰的な式木**を必要とするため見送った。現在の`IfRecord`等は
「オペランド1個+演算子1個+オペランド2個」という完全にフラットな構造を前提にしており、
`A AND B OR C`のような式を正しく表現するには構造自体の再設計が必要(優先順位・結合性も
未確認)。安易な部分対応は誤った意味論を生成する恐れが大きいため、`pad_dsl_parser.py`の
モジュールdocstringに確定した構文を明記した上で、別タスクとして持ち越す。

> **追記**: design/dsl_format_findings.md 知見53で実機DSL表現自体は確認し、`RawExpr`型で
> トークン列を失わずに保持してTODOフォールバックするところまでは実装した。ここで見送った
> 「再帰的な式木への再設計」自体は、優先順位・結合性の実機確認が済むまで引き続き持ち越し。

## UI要素セレクタ(「By window UI element」モード)の文字列フォーマットを解明

research_notesの調査時点から「本格的なUIA要素セレクタの文法がまだ未解明」としていた、
PADの**UI要素セレクタ**(`Click`/`Get text`等のUI automationアクションで「By window UI element」
モードを選んだ際に使う、個々のボタン・テキストボックス等を特定する仕組み)の文字列フォーマットを、
`Microsoft.Flow.RPA.Desktop.Modules.UIAutomation.Actions.dll`と、その依存先SDK
(`Microsoft.Flow.RPA.Desktop.Modules.SDK.Extended.Controls`名前空間)から確認した。

`ClickElementInWindow`(`UIAutomation.Actions`の`Click`アクション)は`[InputArgument(Name = "Element")]`
として`UIControl`型の`Control`プロパティを持つ。`UIControl : Control : BaseControl`で、
実体は`Selectors`(`IList<Selector>`)というリスト。`BaseControl.ToString()`/
`Selector.ToString(bool isRoot)`/`SelectorElement.ToString()`/`SelectorAttribute.ToString()`を
辿ると、**CSS属性セレクタに似た独自記法**であることが確定した:

- 要素間は` > `(子孫方向への結合子)で連結。ルート要素には`:desktop >`が前置される
  (`Selector.CreateSelectorString()`)。
- 各要素は`Tag`(エスケープされた識別子)+属性列。属性は:
  - `[name]` — 属性の存在チェック(`Operator.None`)
  - `[name="value"]` — 完全一致(`Operator.EqualTo`、記号`=`)
  - `[name!="value"]` — 不一致(`NotEqualTo`、`!=`)
  - `[name*="value"]` — 部分一致(`Contains`、`*=`)
  - `[name^="value"]` — 前方一致(`StartsWith`、`^=`)
  - `[name$="value"]` — 後方一致(`EndsWith`、`$=`)
  - `[name@="value"]` — 正規表現一致(`RegexMatch`、`@=`——他の演算子にはない記号で、
    CSS標準の属性セレクタ演算子を独自拡張したものと分かる)
  - `:eq(N)` — 序数(何番目の要素か、`IsOrdinal`属性用)
  - `:disabled` — 無効化状態チェック
- 値の`%VarName%`部分は`Selector.GetExpressionsRobin()`(`VisualRegexExpression`/
  `CustomRegexExpression`で抽出)経由でRobinランタイムに変数参照として伝わる——つまり
  セレクタ文字列の内部に`%VarName%`マーカーを埋め込める(他の文字列パラメータと同じ
  インターポレーション形式がセレクタ内部でも使える)。

**未確定点(今回は実装せず、文書化のみ)**: このセレクタ文字列が実際にDSLの`ActionRecord`
パラメータ行上で**どう直列化されるか**(`Control: $'''...'''`のように素のセレクタ文字列が
そのままテキスト値として埋め込まれるのか、それとも「コントロールリポジトリ」内の名前/IDへの
参照になるのか)はまだ確認できていない——`UIControl`自体が`IEvaluatableContext`を実装している
形跡は無く(`InputArgument.Expression`が要求する型とどう橋渡しされるかが未確認)、SDK側の
別のアダプタ/ラッパークラスを経由している可能性がある。実機でのDSL出力例も一つも無いため、
パーサー/codegenへの実装はまだ時期尚早と判断した。

**このティックでの追加調査**: `UIControl`→DSL直列化の橋渡しを探して`Modules.SDK.Extended.Converters`
名前空間(`EncryptableObjectTypeConverter`等)を確認したが、`UIControl`専用のコンバータは
見当たらなかった。`IControlRepositoryItem`(`AsUIControl()`/`AsWebControl()`)という
インターフェースも見つけ、「UI要素」が名前付きリポジトリとして管理される可能性を示唆しているが、
確証には至らなかった。`UIAutomationActionBase`(基底クラス)は`Modules.UIAutomation.Actions.dll`
には存在せず(おそらく`Modules.UIAutomation.Common.dll`で定義)、追跡には更なるDLL取得が必要——
深追いするより、実機でのDSL出力例を1つ取得する方が効率的と判断し、このスレッドはここで一旦停止する。

> **【解決】実機検証により「名前/IDへの参照」の予測が正しかったと確定した**(design/dsl_format_findings.md
> 知見38)。「Click UI element in window」アクションにUI要素ピッカーでWindowsのスタートボタンを
> 選んでキャプチャしたところ、`Element: appmask['Start Button']`という形で、
> **UI要素リポジトリ内のエントリへの表示名参照**であることが確定した——本セクションで解明した
> CSS風セレクタ文字列(`[name="value"]`等)は、DSLクリップボードテキストには直接現れず、
> リポジトリ内部の格納形式(おそらく`.msapp`等の別ファイル/別部分に保存されている)である
> ことが判明した。`IControlRepositoryItem`というインターフェース名からの推測は正しかった。

## `[Action]`/`[ConditionAction]`属性でaction_idの構成要素とConditionActionカテゴリを確認

アクションクラス自身の属性(`[Action(Category = "Windows", Order = ..., Id = "FocusWindow")]`等)から、
`action_id`の構成要素(モジュール接頭辞+`Id`+`ActionSelector.UseName()`)が確定的に分かることを
確認した。例: `FocusWindowBase`の`[Action(Category = "Windows", Id = "FocusWindow")]` +
`FocusWindowByTitleClassSelector`の`UseName("FocusByTitleClass")` → 
`UIAutomation.FocusWindow.FocusByTitleClass`(design/dsl_format_findings.md 知見27で実機確認済みの
形と一致)。同じ方法で`CloseWindowBase`(`Id = "CloseWindow"`)+`CloseWindowByTitleClassSelector`
(`UseName("CloseByTitleClass")`)から`UIAutomation.CloseWindow.CloseByTitleClass`を導出し、
他の4つのByTitleClass系アクションと全く同じ`Title`/`Class`パターンだったため、`pad_codegen.py`に
`.set_focus()`(FocusWindow)・`.close()`(CloseWindow)への変換を追加した
(CloseWindowは実機未確認、パターンからの推論)。

**重要な副発見**: `IfWindowAction`(`IsFocusedByTitleClassSelector`等4つのセレクタが対象にする
共通クラス)には`[Action]`ではなく**`[ConditionAction(ResultPropertyName = "Result", Id = "IfWindow")]`**
という別の属性が付いている。これは design/dsl_format_findings.md 知見18-2 で発見した
`Contains`系と同じ「`IfFunctionRecord`形式(`IF <Name>(args...) THEN`)で使われる関数呼び出し条件」
のカテゴリだと判断できる——`IsFocusedByTitleClass`/`IsNotFocusedByTitleClass`/`IsOpenByTitleClass`/
`IsNotOpenByTitleClass`は、独立したアクション行ではなく`IF IsFocusedByTitleClass(Title, Class,
InstantCheck) THEN`のような条件式として現れると推測される(`Show()`順序はTitle→Class→
InstantCheckで確定)。ただし`Contains`自体も実機確認は1例のみでPython変換方法を未確定のままに
しているのと同じ理由(確証が無いまま複数の「関数条件ファミリー」に同じ形を当てはめるのは危険)で、
今回はパーサー/codegenへの実装は見送り、発見の記録のみとした。

## アクション属性に3つ目のカテゴリ`[WaitAction]`を発見、新たなByTitleClass系アクションを確認

`UIAutomation.Actions.dll`内の他のアクションクラスを見て回り、`[Action]`/`[ConditionAction]`に
続く**3つ目の属性カテゴリ**を発見した:

- `WaitForWindowAction`(`ToBecomeFocusedByTitleClass`等4つのSelectorが対象)には
  `[WaitAction(ResultPropertyName = "Result", Id = "WaitForWindow")]`が付いている。
  `ConditionAction`と同じく`Result`プロパティを持つが、`IfWindowAction`と異なり
  通常の`[Action]`と同じ形(`Output=>`で明示的に出力を束縛できる、独立したアクション行として
  振る舞う)に見える——おそらく「条件が真になるまでポーリングして待つ」という、
  タイムアウト・リトライを内包したブロッキング待機アクション固有の属性と推測される
  (実装は未確認)。`WindowMode`の判別子は`BecomeFocused`/`ToClose`/`ToLoseFocus`/`ToOpen`の
  4値(`ToBecomeFocusedByTitleClass`等のUseNameと対応)。

新たなByTitleClassパターンの通常`[Action]`も1件確認した: `SetWindowVisibilityBase`
(`[Action(Category = "Windows", Id = "SetWindowVisibility")]`)+
`SetWindowVisibilityByTitleClassSelector`(`UseName("SetVisibilityByTitleClass")`、
`Title`/`Class`/`Visibility`(`Visible`/`Hiddenの2値enum`)を`Show`)から
`UIAutomation.SetWindowVisibility.SetVisibilityByTitleClass`を導出した。
**今回はcodegen実装を見送った**——pywinautoに「ウィンドウの表示/非表示切り替え」に対応する
確実な公開APIメソッド名の心当たりが無く(`.maximize()`/`.minimize()`/`.restore()`/
`.close()`/`.set_focus()`ほど確信を持てる標準メソッドが無い)、架空のAPI呼び出しを
でっち上げるリスクを避けた。

また、`CloseWindow`/`FocusWindow`には`ByInstanceOrHandle`という3つ目のFind window mode
(`WindowInstance: int`のみをShowする、Title/Classを使わない)も存在することを確認した。
これは design/dsl_format_findings.md 知見26の「Get window」の`WindowInstance=> AutomationWindow`
出力を後続アクションで再利用する経路だと推測されるが、`pad_codegen.py`は`GetWindow`自体を
まだ変換対象にしていない(「window instance」というPAD独自の概念をPython側でどう表現するか
という設計判断が必要)ため、こちらも実装を見送った。

## 【重要な訂正】`ON ERROR`ブロックを実機で検証——ソースから類推したインデント規則は誤りだった

PAD実機のActionダイアログには、どのアクションにも共通して「On error」ボタン(盾アイコン)が
あり、クリックすると「Error handling」セクションが開く——「Failed to run Python script」
「Directory not found」のような**アクション固有の名前付きエラーケース**と、常に最後に
表示される「All errors (default)」(catch-all)が並び、それぞれに`+`ボタンで本体アクション
(`Set variable`/`Run subflow`等)を追加でき、「Continue flow run」/「Throw error」の
トグルがある、という構造を発見した。

「All errors (default)」に`Set variable`(`NewVar`に`'recovered'`を代入)を追加し、
「Continue flow run」を選んで保存・コピーしたところ:

```
Scripting.RunPythonScript.RunPythonScript PythonCode: $'''...''' ScriptOutput=> PythonScriptOutput3
ON ERROR
SET NewVar TO $'''recovered'''
END
```

**ここで前セクション(`ExceptionStatementBase`のソース解析)での予測が誤りだったと判明した**。
ソースから`SetLevel()`の実装(`Cases`/`CaseDefault`の`Level`を親+1に設定)を根拠に、
「ケースの本体は`ON ERROR`ヘッダーより1段深いindentになる」と予測していたが、実機では
**`SET NewVar TO ...`(本体)は`ON ERROR`・`END`と全く同じindent**だった(保護対象の
アクション自身とも同じindent)。つまり`ON ERROR`ブロックは、他のブロック構文(`IF`/`LOOP`/
`SWITCH`、いずれも本体がヘッダーより1段深い)とは異なり、**ヘッダーと本体が同じ段のまま**
という、今まで見た中で唯一の例外的な構造だった。

(今回検証したのは「All errors (default)」という名前無しのcatch-allケース1つだけで、
`Case`/`Repeat`を含む複数ケース構成や`REPEAT ACTION`/`NEXT ACTION`の挙動はまだ未検証。
名前付きケース(例: 「Directory not found」)やRepeatが絡むと、実際には別のインデント規則に
なる可能性もゼロではない)

**(後続のティックで実装完了)**: `OnErrorRecord`(`ON ERROR`ベアキーワード)・`OnErrorNode`
(本体)・`GuardedNode`(直前のノードを`on_error`でラップする新しいNode種別)を
`pad_dsl_parser.py`に追加した。`build_block_tree()`では、`OnErrorRecord`に遭遇したら
本体を**同じ`level`で**再帰的にパースする(他のブロック構文と異なり`level + 1`ではない——
再帰呼び出し自身が同じ`level`の`END`を検出して消費するため、呼び出し元での明示的な
END消費も不要)。パースした本体を直前に`body`へ追加済みのノードを`GuardedNode`で
置き換える形でラップし直す。`pad_codegen.py`側は`GuardedNode`を`try`/`except Exception`に
変換する(「All errors (default)」+「Continue flow run」の組み合わせのみ対応——
名前付きケースや「Throw error」は未検証のため未対応)。

## 今後の調査候補(未着手)

- ~~`ON ERROR`/`ON BLOCK ERROR`ブロックの実機検証~~ → 構文(catch-allケースのみ)は完了・
  ソースの類推が誤りだったと判明・修正済み(本セクション参照)。パーサー/codegenへの実装も
  完了(`OnErrorRecord`/`OnErrorNode`/`GuardedNode`)。名前付きケース・複数ケース・
  `REPEAT ACTION`の実機検証も完了(design/dsl_format_findings.md 知見36・37)。
  **`ON BLOCK ERROR`・`NEXT ACTION`も実機検証完了**(知見40)——`ON BLOCK ERROR`は
  `ON ERROR`と完全に同じ構造(本体のindentがヘッダーと同じ、複数アーム、共有END)だと
  確認でき、新たに発見した`BLOCK`(PADの「On block error」アクションが自動生成する
  無名グループ化構文)とあわせて`BlockRecord`/`OnBlockErrorRecord`として実装した。
  `NEXT ACTION`は予測通り既存の`KeywordRecord`機構で追加実装無しに対応できた。
  **「Throw error」も実機検証完了**(design/dsl_format_findings.md 知見41)——
  `THROW ERROR`という`REPEAT ACTION`/`NEXT ACTION`と同形式の2トークンのベアキーワード
  だった。**「Go to label」も実機検証完了**(知見48)——`Label`アクションが`LABEL <名前>`、
  「Go to label」が本体に`GOTO <名前>`を追加する、同じく2トークンのベアキーワード形式。
  これで`ON ERROR`/`ON BLOCK ERROR`系の未検証項目は全て解消した
- ~~`WaitForWindowAction`等の`[WaitAction]`カテゴリのDSL表現の実機検証~~ → 完了
  (design/dsl_format_findings.md 知見50): `WAIT (<ActionId> <Param>: <Value> ...) FOR <秒数>`
  という、`WAIT <seconds>`とは全く別の構文だった。`action_id`は予測通り
  `UIAutomation.WaitForWindow.ToOpen`。タイムアウトは「Fail with timeout error」
  トグルで初めて設定可能になる(既定5秒)。パーサーに`WaitActionRecord`として実装済み。
  ~~「Fail with timeout error」OFF時の挙動~~ → 完了:`FOR`句自体がDSLから省略される
  (パーサーバグを修正)。~~`ToClose`バリアント~~ → 完了:`UIAutomation.WaitForWindow.ToClose`、
  `FocusWindow`パラメータ自体が存在しない。~~`Become focused`/`Lose focus`の2バリアント~~ →
  完了(design/dsl_format_findings.md 知見50追記): 予測通り`UIAutomation.WaitForWindow.ToBecomeFocused`/
  `ToLoseFocus`——これで「Wait for window to」の4択全てが実機確認済みになった。
  `FocusWindow: True`表記(「Focus window after it opens」トグルON時)は未検証のまま。
  ~~「Wait for service」の構文~~ →
  完了(design/dsl_format_findings.md 知見50追記): `Services.WaitForService.Started`
  ——知見54の「If service」(`Services.IfService.IsRunning`)と同じ`Services.*`名前空間。
  単一行アクションで対応する`End`は自動挿入されない。**新発見**(design/dsl_format_findings.md 知見52): 「Wait for window」とは
  別物の「Wait for window content」という新アクションが存在し、action_idは
  `UIAutomation.WaitForWindowContent.WindowToContainElement`——DSL構文自体は`WAIT (...)`を
  そのまま再利用しており、パーサー/codegenとも無改修で正しく処理できた。「Wait until window」
  ドロップダウンの他の選択肢・「Check UI element state」トグルは未検証のまま持ち越し
- ~~`LOOP X FROM start TO end STEP step`のrangeが両端を含むかどうかの実機検証~~ → 完了
  (design/dsl_format_findings.md 知見51): 実機でLoopIndexの実行回数をファイルへの書き込み
  バイト数として確認し、「1 TO 3」が2回(X=1,2)しか実行されないと判明——`end`を含まない、
  Pythonの`range(start, end, step)`と同じセマンティクスだった。当初`pad_codegen.py`が
  仮定していた「両端を含む」(`range(start, end+1, step)`)は誤りで、修正済み
- `SetWindowVisibility`(action_id確定済み——本セクション参照)のPython変換に使える、確実な
  pywinauto APIの特定(架空のAPI名を避けるため保留中)
- ~~「window instance」(`GetWindow`の出力、`ByInstanceOrHandle`系アクションの入力)をPython側で
  どう表現するかの設計、およびそれに基づく`CloseWindowByInstanceOrHandle`等の実装~~ →
  `GetWindow`・`CloseWindow`(by instance)とも実機DSLを確認済み(design/dsl_format_findings.md
  知見57): `GetWindow`のaction_idは`UIAutomation.GetWindow.GetUseTimeout`、出力は
  `WindowInstance=> <変数名>`という知見14の`=>`出力変数構文の再利用。`CloseWindow`の
  「Find window mode」ドロップダウンには予測通り3択(UI element/instance-handle/title-class)
  あり、「By window instance/handle」で`UIAutomation.CloseWindow.CloseByInstanceOrHandle
  WindowInstance: <変数名>`という、引用符もUI要素参照も付かない**裸の変数参照**を確認した
  (いずれも既存の汎用パーサーで無改修でパース可能)。知見56のpywinautoセレクタ生成と
  組み合わせた実際の変換実装(`GetWindow`→`win = Desktop(...).window(...)`、
  `CloseWindow`→`win.close()`)はまだ見送っており、他の`ByInstanceOrHandle`系アクション
  (`SetWindowStateByInstanceOrHandle`等)の実機DSL・`Timeout`無しモード・
  `BringWindowToFront: True`時の挙動は未確認のまま持ち越し

- ~~`ConditionAction`カテゴリ(`IfWindowAction`の`IsFocusedByTitleClass`等——本セクション参照)が
  実機で本当に`IfFunctionRecord`形式のDSLを生成するかの確認~~ → 完了(design/dsl_format_findings.md
  知見54): 実際には`IfFunctionRecord`ではなく、知見50の`WAIT (...)`と同じ丸括弧構文
  (`IF (<ActionId> <Param>: <Value> ...) THEN`)という第3の条件表現パターンだった。
  「If window」はこのアクション単体で対応する`End`も自動挿入される(=ブロック開始構文)ことも
  確認。当時未対応だったため`IfRecord`へ誤パースされていた重大なバグを`IfActionRecord`/
  `ElseIfActionRecord`型の新設で修正した。codegenは`IfFunctionRecord`と同じ方針で
  `NotImplementedError`を送出しはっきり失敗する(UI要素セレクタ未取得+誤訳時の制御フロー
  反転リスクのため)。`Contains`を含む「関数呼び出し条件ファミリー」群のPython変換方法の検討は
  引き続き持ち越し
- ~~UI要素セレクタが実際のDSLテキスト上でどう直列化されるか~~ → 完了(design/dsl_format_findings.md
  知見38で最初に確定し、知見44・46・50・52・54・55を含む以降の全実機キャプチャで一貫して
  再確認されている)。`ActionRecord`/`WaitActionRecord`/`IfActionRecord`いずれのパラメータ値としても
  `appmask['<表示名>']`(複数階層は`appmask['<親>']['<子>']`)という形でそのまま埋め込まれる——
  本セクションで解明したCSS風セレクタ文字列自体はDSLには直接現れず、`# [ControlRepository]
  [PowerAutomateDesktop]`セクション内のリポジトリJSONに格納される(知見44)。`UIAutomationActionBase`
  のDLL追跡は不要になった
- ~~`SWITCH`/`CASE`/`DEFAULT`の実機検証~~ → 完了(design/dsl_format_findings.md 知見33。
  類推していたインデント規則は誤りだったと判明し、修正済み)
- ~~名前付き`ON ERROR <Case>`ケース・複数ケース構成の実機検証~~ → 完了
  (design/dsl_format_findings.md 知見36。`stop_at_on_error`での区切りバグを修正、
  パーサー/codegenとも実装済み)。`REPEAT ACTION`も実機検証済み(知見37)。
  ~~`NEXT ACTION`・`ON BLOCK ERROR`~~ → 完了(知見40)。~~「Throw error」~~ → 完了
  (知見41、`THROW ERROR`という2トークンのベアキーワード)。~~「Go to label」~~ → 完了
  (知見48、`LABEL <名前>`/`GOTO <名前>`という2トークンのベアキーワード)
- ~~`AND`/`OR`/`XOR`/`NOT`による複合条件式、`+`/`-`/`*`/`/`/`mod`による算術式の実機DSL確認~~ →
  完了(design/dsl_format_findings.md 知見53): 標準の「If」アクションには複合条件を組む
  UIが無い(Operatorドロップダウンは16択のみ)ため、「Set variable」のValue欄に直接
  `%...%`式を書いて実機確認した。`AND`/`OR`/`NOT`/`XOR`は小文字入力でも大文字に正規化
  されるが、`mod`は小文字のまま。この過程で`SET ... TO`パーサーが複数トークンの右辺を
  サイレントに切り捨てる重大なバグ(`tokens[3]`1個だけを読んでいた)を発見・`RawExpr`型で
  修正した。`IfRecord`等を再帰的な式木に再設計し、`RawExpr`から実際のPython式へ機械的に
  変換することは、PADの演算子優先順位・`XOR`のPython対応・`mod`の負数挙動が未検証のため
  持ち越し(安全側のTODOフォールバックで対応済み)
- ~~`IN`/`NOT IN`演算子を実機のどのUI経由で使えるかの特定~~ → 部分的に完了
  (design/dsl_format_findings.md 知見49): 標準の「If」/「Else if」アクションの
  Operatorドロップダウンには存在しないことを実機確認した(ネガティブな結果)。
  到達可能な別の入口(List/Datatable関連アクション等)があるかは未確認のまま
- ~~`/# ... #/`複数行コメント構文の実機検証~~ → 完了(design/dsl_format_findings.md 知見35。
  ソースから実装した構文・エスケープ規則がそのまま一致し、コード変更不要だった)
- `StringAtom`(非interpolated文字列)が実際にどの文脈で出力されるかの特定
- アクションモジュールDLL群(`Modules.*.Actions.dll`)を対象にした、デフォルト値省略ロジックの追加調査
- ~~`StatementWithArguments`(`ActionStatement`の基底クラス)の`ToString()`実装を読み、パラメータ行の正確な区切り文字・エスケープルールをさらに裏付けること~~ → 完了(本セクション参照)
- ~~`VariableTrailer`(`.Name`/`[Index]`/Slice)付きの変数参照が実機でどう出力されるかの確認~~ →
  `.Name`トレーラ・`[Index]`添字アクセスの両方を実機確認(design/dsl_format_findings.md 知見55)。
  懸念していた通り`.Name`トレーラ(`InnerVar.SomeProperty`)は既存の`EnumRef`判定と字面上
  区別できず、実際に誤分類されて文字列リテラルへすり替わる重大なバグとして発覚した。
  これまでの実機EnumRef captureが全て例外なく3セグメントだった実績に基づき、EnumRef判定を
  3セグメント以上に限定する`_ENUM_REF_RE`を新設して修正した(完全な解消ではない暫定対応)。
  `[Index]`添字は元々ドットを含まないため影響を受けず、`VarRef`としてそのままPythonの
  添字アクセス構文に変換できていた。~~Slice構文~~ → 完了(design/dsl_format_findings.md
  知見59): `%InnerVar[0:2]%` → `SET NewVar3 TO InnerVar[0:2]`、Pythonのスライス構文
  `[start:end]`と字面上完全に一致することを実機確認した。これで`VariableTrailer`の
  3形態(`.Name`/`[Index]`/Slice)全てが実機確認済みになった。~~0始まりか1始まりか・
  終端を含むかどうかの意味論~~ → 完了(design/dsl_format_findings.md 知見60): 知見51の
  LOOP range検証と同じ「実機で実行してファイル経由で値を読み取る」手法で決着させた。
  `"ABCDEFGHIJ"[0:3]` → `"ABC"`、`[0]` → `"A"`、`[3]` → `"D"`——いずれもPythonの
  添字/スライス評価結果と完全に一致し、**0始まり・終端排除というPythonと寸分違わぬ
  意味論**であることが確定した
- `IExceptionStatement`の具象実装が本当に`ExceptionCaseStatement`と同じものかどうか、
  そして`StatementWithArguments.ToStringIgnoreMetadata()`末尾への連結がスペース無しに
  見える件(表記ミスか、実際には別の区切り規則があるのか)の確認
