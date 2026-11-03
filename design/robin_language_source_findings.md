# PADの内部アセンブリ逆コンパイルによる文法の裏付け(Robin Language)

## 背景・経緯

design/dsl_format_findings.md はこれまで、実機PADでアクションを1つずつ追加して「コピーとして貼り付け」の出力を観察する、という帰納的な手法でDSL文法を解明してきた(知見1〜26)。この方法では、個別のアクションの挙動は確認できるが、「なぜ一部のデフォルト値は省略され一部は省略されないのか」(知見19〜21・23)のような**文法全体に関わる規則**は、1アクションずつ試す限り永遠に収束しない("モグラ叩き"になる)という指摘をユーザーから受けた。

PAD Desktop は .NET(WPF)アプリケーションであり、「コピーとして貼り付け」機能のシリアライザは実際にインストールされているDLLの中にIL(中間言語)として存在する。これをデコンパイルして**一次ソースとしてのロジック**を直接読むことで、個別の実機検証よりもはるかに効率的かつ確実に文法全体を把握できると判断し、ユーザーの明示的な了承を得た上で実施した。

## 手法

1. `~/.dotnet`(.NET 8 SDK + .NET 6 ランタイム、サンドボックスにインストール)経由で `ilspycmd`(クロスプラットフォームの.NET逆コンパイラ、dotnet tool、バージョン8.2.0.7535)をインストール。
2. WinRM(`pywinrm`)経由で、PAD実機VM(`pad2py-pad-host`)の `C:\Program Files (x86)\Power Automate Desktop\Microsoft.Flow.RPA.Desktop.Robin.Language.dll`(578,888バイト)をBase64エンコードで取得。
3. `ilspycmd -p -o <outdir> Robin.Language.dll` でC#ソースに逆コンパイル(291ファイル生成)。
4. `grep`で`"THEN"`等のDSL特有文字列をキーに、関連クラスを特定して読み込んだ。

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

## 今後の調査候補(未着手)

- `SWITCH`/`CASE`/`CASE DEFAULT`構文の実機検証とパーサー対応
- `COMMENT`(`# ...` / `/# ... #/`)構文の実機検証とパーサー対応(構文は判明したが実機未確認)
- `In`/`Not in`演算子を実機のどのUI経路で使えるかの特定、および`NOT IN`(2トークン)にパーサーが対応していないギャップの解消
- アクションモジュールDLL群(`Modules.*.Actions.dll`)を対象にした、デフォルト値省略ロジックの追加調査
- `StatementWithArguments`(`ActionStatement`の基底クラス)の`ToString()`実装を読み、パラメータ行の正確な区切り文字・エスケープルールをさらに裏付けること
