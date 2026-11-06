# UiPath `.xaml`/`project.json` の実データによる構造確認

`dsl_format_findings.md`(PAD)と同じ手法——実機で最小限のサンプルを作り、生成された
ファイルを直接読んで実データで検証する——をUiPathにも適用した記録。PADと異なり
UiPathの`.xaml`はクリップボードDSLの逆解析が不要な、ディスク上の普通のXMLファイル
なので、調査コストはPADよりかなり低い(知見1参照)。

検証環境: GCP上のWindows Server 2022 VM(`pad2py-pad-host`、PADと共用)に
UiPath Studio Community Edition(Automation Cloud個人アカウントでサインイン済み)
をインストールし、`xaml_probe`という空のProcessプロジェクトを作成。`clipwire`
(対話的RDPセッション内で動くリモート実行デーモン)経由でpywinautoを駆動して
Studio UIを直接操作し、生成された`Main.xaml`/`project.json`を読み取った。
繰り返し使った操作パターン(アクティビティ検索ポップアップの開き方、VB式入力欄への
文字送信、DataGridViewセルの編集等)は[dump_daemon/uipath_ui_helpers.py](../dump_daemon/uipath_ui_helpers.py)
に再利用可能な関数として切り出してある(P0項目5、`pad_ui_helpers.py`のUiPath版)。
実データは[design/evidence/uipath_xaml_probe/](evidence/uipath_xaml_probe/)に
保存している(`Main.xaml`は本ドキュメントの知見5-9で参照する最終形)。

## 1. UiPathのXAMLはPADのクリップボードDSLよりリバースエンジニアリング難易度が低い

PADの最大の障害は「フローをファイルとしてエクスポートする公式手段が無い」ことで、
そのためクリップボードDSLを実機検証で逆解析するという迂回路が必要だった
(`dsl_format_findings.md`参照)。UiPathの`.xaml`は普通のXMLファイルとして
ディスク上(`<project>/Main.xaml`等)に存在するため、この「そもそも機械可読な
表現が手に入らない」問題は発生しない。標準のXMLパーサー(Python標準の
`xml.etree`等)だけで完全なIRが取れる。

難易度が下がるのはあくまで「IRの入手」であって、「IRからPythonへの変換」の
難易度は別の場所に移る(知見2・6参照)。

## 2. 式はVB.NET式として角括弧`[...]`に埋め込まれる

属性値・要素の中身として式(文字列リテラルも変数参照も)が現れる箇所は、
`[...]`で囲んだVB.NET式テキストとしてそのまま埋め込まれる:

```xml
<ui:MessageBox Text="[&quot;Hello from pad2py&quot;]" />
<OutArgument x:TypeArguments="x:Object">[result]</OutArgument>
<If Condition="[result=&quot;ok&quot;]" />
```

これをPythonに変換するには**VB.NET式パーサー/トランスパイラが新規に必要**で、
PAD用に作った式パーサー(`pad_expr`の`RawExpr`等)は構文が異なるため流用できない。
UiPathへ本格着手する場合の中核的な新規エンジニアリングはここになる。

ただし全ての値が`[...]`式というわけではない——知見7参照。

## 3. 名前空間・アセンブリ参照は「使われたアクティビティパッケージ」単位で自動増加する

ファイル先頭の`TextExpression.NamespacesForImplementation`/
`ReferencesForImplementation`(`<sco:Collection>`)は、使ったアクティビティの
パッケージに応じて自動的に増える。空のBlank Processでは最小限の一覧だったが、
`UiPath.System.Activities`配下のアクティビティ(MessageBox/Assign/If等)を
使った時点で`UiPath.Excel`/`UiPath.Mail`/`UiPath.UIAutomationCore`等が
一括で追加された(これらは`project.json`の`dependencies`に元々あった4パッケージ
全部の名前空間で、個別アクティビティ単位ではなく**パッケージ単位**で追加される)。

さらに、`System.Exception`のような**任意の.NET型参照**(Catchの型、変数の型等)
を使うと、それに対応する`xmlns:s="clr-namespace:System;assembly=mscorlib"`の
ような新しい名前空間prefixがルート`<Activity>`要素に追加される(知見9)。
つまり依存関係の洗い出しは「どのアクティビティパッケージを使ったか」だけでなく
「どの.NET型を参照したか」も辿る必要がある。

## 4. デザイナー専用ノイズは`sap`/`sap2010` prefixで機械的に判別できる

`sap:VirtualizedContainerService.HintSize`・`sap2010:WorkflowViewState.IdRef`・
`sap:WorkflowViewStateService.ViewState`(`IsExpanded`/`IsPinned`/
`ShouldCollapseAll`等のデザイナー上の表示状態を持つ`Dictionary`)は、全て
純粋な設計時メタデータで実行時の意味を持たない。これらは常に`sap`/`sap2010`
prefixを持つため、XMLパーサー側で名前空間prefixを見てスキップすればよく、
PADのノイズ(`**REGION`やコメント等、構文的に紛れ込む形)より機械的に
判別しやすい。

## 5. 制御フロー: `If`/`ForEach`/`TryCatch`+`Catch`/`Switch`の実構造

`MessageBox → Assign → If → ForEach → TryCatch(Catch付き) → Switch`という
サンプルを実際にStudio上で構築し、確認できた構造(全文は
[evidence/uipath_xaml_probe/Main.xaml](evidence/uipath_xaml_probe/Main.xaml)参照):

- **`If`/`TryCatch`/`Assign`/`Sequence`は素のWF標準型**(`System.Activities.Statements`、
  `ui:`名前空間prefix無し)。**`ForEach`/`MessageBox`はUiPath独自の`ui:`名前空間型**
  (stock WFの`ForEach<T>`ではない)。制御フローでも「WF標準品」と「UiPath再実装品」が
  混在しており、アクティビティごとに確認が必要——一律に仮定できない。
- `ui:ForEach`はコレクションを`Values`属性(VB式)で保持し、`CurrentIndex`を
  出力に持つ。ループ本体は標準WFのデリゲートパターン
  (`ActivityAction`/`ActivityAction.Argument`/`DelegateInArgument`)で表現され、
  ループ変数(例: `item`)は本体内で他の変数と同じ裸の名前で参照される(`[item]`)。
- `Switch`は式の型を推論できない場合(今回は`result`が未型付けの`x:Object`)、
  `x:TypeArguments`が**黙って`x:Int32`にデフォルトされる**(知見8参照)。

## 6. 「空・未設定」は3種類の異なる形で直列化される

アクティビティの省略可能な子要素が空のとき、どう直列化されるかは**アクティビティ
ごとに異なる**。一律に「無ければ省略」と仮定すると誤る:

1. **属性のみの自己終了タグ**(子要素プロパティが全て空): 例 `<If Condition="..." />`
   はThen/Elseが両方空のとき、`<If.Then>`等の子要素が一切現れない。
2. **プロパティそのものが省略される**: `TryCatch`にCatchが1つも無いとき
   `<TryCatch.Catches>`要素自体が存在しない(`<TryCatch DisplayName="Try Catch" />`)。
3. **`x:Null`による明示的なプレースホルダ**: `Switch`の空のcase(アクティビティを
   何も入れていない)は`<x:Null x:Key="<caseValue>" />`という明示的なnullエントリに
   なる——省略されるわけではない。

パーサー側は「この要素/プロパティが存在しない」「存在するがnull」「存在し中身がある」
の3状態を区別する必要がある。

## 7. リテラルの直列化形式は式(`[...]`)とは別物——`Variable.Default`は`<Literal>`要素

Variablesパネル(後述知見8)で変数にデフォルト値を設定すると、知見2の`[...]`角括弧
VB式ではなく、生テキストを持つ`<Literal>`要素になる:

```xml
<Variable x:TypeArguments="x:String" Name="myVar">
  <Variable.Default>
    <Literal x:TypeArguments="x:String">init</Literal>
  </Variable.Default>
</Variable>
```

つまり「式かリテラルか」は構文(角括弧の有無)だけでは判定できず、
`InArgument`/`OutArgument`/アクティビティのプロパティ値は`[...]`式、
`Variable.Default`は`<Literal>`要素、という**文脈ごとに異なる2つの直列化規約**
を両方扱う必要がある。

## 8. 変数はスコープを持つ活性化アクティビティの`<Container.Variables>`配下に宣言される

Variablesパネル(Studio下部のタブ)でString型変数`myVar`(デフォルト`"init"`)を
宣言すると、フラットな一覧ではなく、追加時にフォーカスされていたコンテナ
(今回は`TryCatch`)の`<Container.Variables>`コレクション内に配置された:

```xml
<TryCatch.Variables>
  <Variable x:TypeArguments="x:String" Name="myVar"> ... </Variable>
</TryCatch.Variables>
```

スコープはUI上で明示的に選べるフィールド(「Scope」列)であり、推測ではなく
実データ。スコープ解決はPythonのレキシカルスコープと同様、アクティビティ木を
上に辿ればよい。

なお、Assignの「To」欄に未宣言の変数名を直接入力して暗黙生成した変数
(例: `result`)は**型無し(`x:TypeArguments="x:Object"`)**になり、Studio上で
常に赤い警告アイコンが付く。Variablesパネル経由の正式宣言は型が明示され
警告が出ない。つまり「型が明示されているかどうか」で生成経路(暗黙代入 vs
正式宣言)をある程度推測できる。

## 9. `Switch`の型推論失敗とブロッキングダイアログ

未型付け変数(`result`、`x:Object`)を`Switch`の式に使うと、`x:TypeArguments`は
`x:Object`にはならず**`x:Int32`にフォールバック**する。この状態で文字列
(`"ok"`)をcase値として入力すると、他の箇所(赤い警告アイコンで済む)とは違い、
**"ok is not a valid value for Int32."というブロッキングのモーダルダイアログ**
が出て先に進めない。トランスパイラは`Switch`の`x:TypeArguments`属性を
必ず実際の値から読み取る必要があり、式の変数宣言型と一致する保証はない。

`System.Exception`のような型をCatchの型として選ぶと、対応する
`xmlns:s="clr-namespace:System;assembly=mscorlib"`が自動的にルート要素へ
追加される(知見3参照)。

## 10. UI自動化(pywinauto)上の注意点——この調査を再現・拡張する場合

- Assign/If/Switch等の値入力欄は`VisualBasicEditor`というIntelliSense付きの
  カスタムコントロールで、`pywinauto`の`set_edit_text()`(UIA ValuePattern)は
  `NoPatternInterfaceError`で使えない。`send_keys()`で一括文字列を送ると
  文字の欠落・重複が起きる(例: `"result"` → `"rllllt"`)ことがある——
  フィールドをクリックして`^a{DELETE}`で空にした後、1文字ずつ`pause=0.15`
  程度の間隔で送る必要がある。単純な文字列プロパティ(MessageBoxの`Text`等)
  は通常の`send_keys()`で問題なかった。
- `{`/`}`は`send_keys()`では`{{}`/`{}}}`とエスケープが必要(VB配列リテラル
  `{"a","b","c"}`の入力時等)。
- TryCatchの「Add new catch」で行を追加した直後、型を確定する前にEscapeを
  押すと追加した空のcatchごと消える——型ドロップダウンで選択した後は
  Escapeでなく別の場所へのクリックで確定してから保存する必要がある。
- 新規に開いたStudioウィンドウがサインイン完了前に起動していた場合、
  Assistant側が後からライセンス許可された(Connected, Licensed)としても
  Studio側は独自に「Sign In to get started」画面を表示し続ける——
  プロセスを再起動(`C:\Users\<user>\AppData\Local\UiPath\app-<ver>\UiPath.Studio.exe`
  を再実行)すれば新しい認証状態を反映する。

## 11. UI Automationセレクタの実XAML形(`ui:Click`)

`Click`アクティビティ(`UiPath.UIAutomation.Activities`、`ui:Click`)を配置し、
Studioの「Indicate on screen」(画面上で対象を指し示す)機能で実機のメモ帳
(Notepad)のテキスト編集領域を実際に指し示して選択した。生成された実XAML:

```xml
<ui:Click.Target>
  <ui:Target ClippingRegion="{x:Null}" Element="{x:Null}"
      Id="08a8fa5e-3c19-4ee1-85fa-994c1ce9905c"
      InformativeScreenshot="849d8ae2b957aedee203fee24ac85ff3"
      Selector="&lt;wnd app='notepad.exe' cls='Notepad' title='Untitled - Notepad' /&gt;&lt;wnd aaname='Horizontal' cls='Edit' /&gt;&lt;ctrl name='Text Editor' role='editable text' /&gt;">
    <ui:Target.TimeoutMS>
      <InArgument x:TypeArguments="x:Int32" />
    </ui:Target.TimeoutMS>
    <ui:Target.WaitForReady>
      <InArgument x:TypeArguments="ui:WaitForReady" />
    </ui:Target.WaitForReady>
  </ui:Target>
</ui:Click.Target>
```

- `Selector`属性の中身は、HTMLエンティティでエスケープされた**擬似XML文字列**
  (`&lt;wnd .../&gt;&lt;wnd .../&gt;&lt;ctrl .../&gt;`)で、`<wnd>`(トップレベル
  ウィンドウ、`app`/`cls`/`title`属性)→`<wnd>`(子孫コンテナ、`aaname`/`cls`)→
  `<ctrl>`(最終要素、`name`/`role`)という階層チェーン。PADの`appmask['...']`
  (UI要素リポジトリへの名前参照)とは違い、セレクタの実体がそのままアクティビティの
  属性値として埋め込まれる——別リポジトリを介さず単体のXAMLだけで完結する。
- `ClippingRegion`/`Element`は未使用時`{x:Null}`(画像/直接要素参照など他の
  ターゲティング方式用の予備フィールド)。`ui:Click.CursorPosition`
  (`OffsetX`/`OffsetY`)はクリック位置オフセットで、指定無しなら空の`InArgument`。
- `InformativeScreenshot`の値はファイル名で、プロジェクト直下の`.screenshots/`
  フォルダに同名の`.png`として実体が保存される(Studioのデザイン時プレビュー用、
  実行時には不要)。
- プロジェクトフォルダには他に`.local/`(`AllDependencies.json`・
  `PackageCache.json`・`references.db`等のNuGetキャッシュ)と`.settings/Debug|Release/`
  (環境/マシン依存の設定ファイル)が生成される——いずれもGit管理対象外にすべき
  ローカル専用ファイル(通常`.gitignore`に入る)。

## 12. Invoke Workflow File(サブワークフロー呼び出し)とワークフロー引数(Arguments)の実XAML形

2つ目のワークフローファイル`Sub1.xaml`(Add > Sequence)を作り、`in_text`という
`In`方向・`String`型の引数(Arguments)を宣言した。実XAML:

```xml
<Activity ... x:Class="Sub1" ...>
  <x:Members>
    <x:Property Name="in_text" Type="InArgument(x:String)" />
  </x:Members>
  ...
```

**変数(Variables)とは全く別の直列化形**であることが確認できた——Variablesは
知見8の通り`<Container.Variables>`に活性化アクティビティのスコープ付きで
宣言されるのに対し、ワークフロー自体の入出力引数(Arguments)は、ファイル先頭の
`<x:Members>`に`<x:Property Name="..." Type="InArgument(x:String)"/>`
(または`OutArgument(...)`/`InOutArgument(...)`)という形で宣言される。これは
`x:Class`直下、名前空間コレクションより前に来る——WFの「このクラスはこういう
公開プロパティを持つ」というXAMLメンバ宣言の仕組みをそのまま使っている。

`Main.xaml`側で`Invoke Workflow File`アクティビティを追加し、ファイル名に
`Sub1.xaml`を指定、「Import Arguments」で`in_text`を取り込んで値`"hello"`を
設定した結果:

```xml
<ui:InvokeWorkflowFile ArgumentsVariable="{x:Null}" ContinueOnError="{x:Null}"
    DisplayName="Invoke Workflow File" LogEntry="No" LogExit="No" UnSafe="False"
    WorkflowFileName="Sub1.xaml">
  <ui:InvokeWorkflowFile.Arguments>
    <InArgument x:TypeArguments="x:String" x:Key="in_text">
      <Literal x:TypeArguments="x:String">hello</Literal>
    </InArgument>
  </ui:InvokeWorkflowFile.Arguments>
</ui:InvokeWorkflowFile>
```

- `WorkflowFileName`はプレーンな文字列属性(角括弧`[...]`式ではない)——呼び出し先
  パスは基本的に静的なファイル名として扱われる。
- 引数の受け渡しは`<ui:InvokeWorkflowFile.Arguments>`配下に、呼び出し先の引数名を
  `x:Key`とした`InArgument`/`OutArgument`の辞書的なコレクションとして表現される。
- **知見7の「リテラルは`<Literal>`要素、式は`[...]`角括弧」という区別について、
  後続の実験(知見13)で仮説を検証し確定させた**。詳細は知見13参照——結論は
  「`x:TypeArguments`が`x:Object`かどうか」が本質的な分岐点で、`<Literal>`要素か
  生テキストかは同じ「コンパイル時定数」を表す2つの表面上のバリエーションに過ぎない。
- `ArgumentsVariable`(引数全体を1つの`Dictionary`変数で渡す代替手段)・
  `ContinueOnError`は共に未指定で`{x:Null}`。`LogEntry`/`LogExit`は既定で`No`。

## 13. `<Literal>`要素・生テキスト・`[...]`角括弧式の使い分け(知見7・12の仮説を検証)

知見12で立てた仮説(「`x:TypeArguments`が厳密な型か`x:Object`かで決まるのでは」)を、
`Sub1.xaml`に`Assign`を追加し、既存の`String`型引数`in_text`へリテラル`"test2"`を
代入する実験で検証した:

```xml
<Assign.To>
  <OutArgument x:TypeArguments="x:String">[in_text]</OutArgument>
</Assign.To>
<Assign.Value>
  <InArgument x:TypeArguments="x:String">test2</InArgument>
</Assign.Value>
```

ここで新たに**3つ目の直列化形**が確認できた——`x:TypeArguments="x:String"`の
`InArgument`にリテラル値を入れると、`<Literal>`要素でも`[...]`角括弧式でもなく、
**`<InArgument>`要素の中に生テキストをそのまま書く**形になった(`test2`、
引用符すら無い)。一方`Assign.To`側の`[in_text]`(引数への変数参照)は、同じ
`x:String`型でも当然ながら`[...]`角括弧式のまま(リテラルではなく参照なので)。

これで3種類全てが実機で確認できたことになる:

| 直列化形 | 確認した文脈 | 型 |
|---|---|---|
| `[...]`角括弧式 | `Assign.Value`(知見2)、`If.Condition`(知見5)、`ui:ForEach.Values`(知見5)、変数/引数参照全般 | `x:Object`、または任意の型の**参照**(リテラルでない式) |
| `<Literal x:TypeArguments="...">text</Literal>` | `Variable.Default`(知見8)、`ui:InvokeWorkflowFile.Arguments`内の`InArgument`(知見12) | 厳密な型(`x:String`等)の**リテラル** |
| `<InArgument>text</InArgument>`(生テキスト、ラップ無し) | `Assign.Value`の`InArgument`(知見13、この実験) | 厳密な型(`x:String`)の**リテラル** |

**結論**: 本質的な分岐点は「`x:TypeArguments`が`x:Object`かどうか」の1点のみ
——`x:Object`は常にVB式の`[...]`角括弧形式になり(ボックス化が必要なため
コンパイル時定数として直接表現できない、と推測される)、厳密な型(`x:String`等)の
リテラルは常に何らかの「コンパイル時定数」表現になる。ただし後者が`<Literal>`要素に
なるか生テキストになるかは、**どのプロパティ/アクティビティがその値を保持しているか
(Assignの汎用`Assign.Value` vs `InvokeWorkflowFile.Arguments`のキー付き辞書)に
依存する表面上の違い**で、意味論上はどちらも同じ「コンパイル時リテラル」を表す
——トランスパイラ側はこの2形式を同列に扱ってよい。

## 14. `While`の実体は`ui:InterruptibleWhile`、`[...]`角括弧式の正体は`VisualBasicValue`の省略記法だと判明

`While`アクティビティを追加し、条件に`result<>"x"`(`result`は知見2のAssignで
暗黙生成した`x:Object`型変数)を設定したところ、2つの重要な発見があった。

**(1) `While`は`ui:InterruptibleWhile`として直列化される**——検索候補の表示名は
単に「While」だが、実体は一時停止/再開・キャンセルに対応したUiPath独自の
`ui:`名前空間アクティビティで、素のWF`While`ではない。知見5で「If/TryCatch/
Assign/Sequenceは素のWF型、ForEach/MessageBoxはUiPath独自型」と整理したが、
Whileも後者(UiPath独自)側に入ることが分かった——制御フロー系は個別に確認が
必要という方針を改めて裏付ける結果。同じ理由で`Do While`も`ui:InterruptibleDoWhile`
として直列化されることを確認した(命名規則から予想通り)。

**(2) `[...]`角括弧式の正体が判明した。** これまで多くの箇所で見てきた
`Condition="[result=&quot;ok&quot;]"`のような角括弧記法は、実は次の冗長形の
**省略記法(XAMLのMarkup Extension的な糖衣構文)** だったと分かった:

```xml
<ui:InterruptibleWhile.Condition>
  <mva:VisualBasicValue x:TypeArguments="x:Boolean" ExpressionText="result&lt;&gt;&quot;x&quot;" />
</ui:InterruptibleWhile.Condition>
```

`mva:VisualBasicValue`(`Microsoft.VisualBasic.Activities`名前空間、知見1から
既に`xmlns:mva`としてルート要素に宣言済み)は、WF4.5以降の標準機能である
VB式評価アクティビティで、`ExpressionText`属性に生のVB式テキストを保持する
(代入可能な式の場合は`VisualBasicReference`になる、と推測される——未確認)。
`[...]`角括弧構文は、Studioがこの`VisualBasicValue`/`VisualBasicReference`
アクティビティをXAML属性1つに圧縮して書くための省略記法であり、**同じ
VB式エンジンの2つの異なる直列化表現**に過ぎない——知見13までで「別物」として
扱っていた区別のうち、角括弧式についてはここで実体が統一的に理解できた
(ただし知見13の`<Literal>`要素・生テキストは、式ではなくコンパイル時定数という
本質的に別の仕組みなので、この統合には含まれない)。

**実務上の含意**: `While`の条件のように、冗長形(`<X.Property><mva:VisualBasicValue
ExpressionText="..." /></X.Property>`)で書かれるか、`Condition="[...]"`の
省略形で書かれるかはアクティビティ・プロパティごとに異なるらしい(`If.Condition`は
省略形、`InterruptibleWhile.Condition`は冗長形だった)。トランスパイラの式パーサーは
**両方の形(`[...]`属性と`<mva:VisualBasicValue ExpressionText="...">`要素)を
同じVB式として扱う正規化ステップ**を最初に挟むのが筋が良さそうだ。

## 15. 高頻度アクティビティの例(`Append Line`)と、文字列リテラルの直列化形がさらに増えた

PADで既に116件実機キャプチャ済みのFile/Folderカテゴリと概念対応が強いUiPathの
`Append Line`(`UiPath.System.Activities`、`ui:AppendLine`)を実機確認した:

```xml
<ui:AppendLine DisplayName="Append Line" FileName="out.txt" Text="hello"
    UseDefaultEncoding="False" />
```

`Text`欄にも`FileName`欄にも、Studio上では(MessageBoxの`Text`と同じく)
`"hello"`のように引用符付きで入力したにもかかわらず、生成されたXAMLは
**引用符すら無い生の属性値**(`Text="hello"`)になった。知見13で見た
「生テキストを`<InArgument>`要素の中に書く」形よりもさらに圧縮された、
**属性値に直接リテラルを書く第4の形**が存在することになる。

同じ「文字列リテラルをStringプロパティに設定する」操作でも、MessageBoxの
`Text`は`[&quot;Hello from pad2py&quot;]`(角括弧VB式)になり、AppendLineの
`Text`/`FileName`は`hello`(生の属性値)になった——**入力方法(クォート付きで
VBエディタに入力)が同じでも、どのアクティビティのどのプロパティかによって
最終的な直列化形が変わる**ことが実機で確認できた。これはおそらくプロパティ
ごとに割り当てられたXAML値コンバータ/デザイナーの実装差によるもので、
入力方法だけから出力形式を予測することはできない——トランスパイラの式/
リテラル判定ロジックは、知見13の3形式に加えてこの「生の属性値」形も
同列に扱う必要がある。

## 16. `OutArgument`(出力引数)も`[VarName]`角括弧形で直列化される——`Read Text File`で確認

知見14で判明した「`[...]`角括弧式 = `VisualBasicValue`/`VisualBasicReference`の
省略記法」は`InArgument`(入力引数)の文脈で確認したものだったが、`OutArgument`
(出力引数)でも同じ省略記法が使われることを`Read Text File`
(`UiPath.Core.Activities.ReadTextFile`)で確認した。

手順: `Read Text File`をキャンバスに追加 → `Filename`欄に`"out.txt"`を入力
→ Propertiesパネルの`Output`グループに現れる`Output to`欄(=`Content`
プロパティ、型は`OutArgument<String>`)にスコープ`Sequence`の`String`型変数
`content`を新規作成して束縛 → 保存。生成されたXAML:

```xml
<ui:ReadTextFile Content="[content]" DisplayName="Read Text File"
    FileName="out.txt" sap2010:WorkflowViewState.IdRef="ReadTextFile_1" />
```

対応する変数宣言(`Sequence.Variables`):

```xml
<Variable x:TypeArguments="x:String" Name="content" />
```

ポイント:

- `Content`(OutArgument)の直列化形は`FileName`(InArgument、知見15で見た
  「生の属性値」形とは別物)とは異なり、**単純な変数参照は角括弧属性値
  `[content]`になる**——知見14の`VisualBasicValue`省略記法が入力/出力の
  引数方向を問わず同じ構文で扱われることが確認できた。
- 複雑な式(知見14の`While`条件のような)は`<mva:VisualBasicValue>`/
  `VisualBasicReference`のネスト要素形になったが、単純な識別子1個の参照
  (今回の`content`)は属性値ショートハンドで済んでいる。おそらくXAMLシリアライザ
  が式の複雑さ(あるいは単純な識別子かどうか)によって属性値形とネスト要素形を
  使い分けている——境界条件(例: プロパティアクセス`foo.Bar`は属性値のままか、
  ネスト要素になるか)は未確認。
- UI操作上の注意点(ハマりどころ): Propertiesパネルの`Output to`欄は単なる
  テキスト入力ではなく**IntelliSense/オートコンプリート付きのVB式エディタ**
  になっている。`pywinauto`で1文字ずつ`send_keys`した後に`{TAB}`で確定しようと
  すると、**入力中の文字列ではなくオートコンプリート候補(例: WPFの
  `ContentAlignment`列挙型)が採用されてしまう**という罠があった
  (実際に`Output to="ContentAlig..."`というコンパイルエラーが発生した)。
  正しい確定方法は、入力後に`{ESC}`でIntelliSenseドロップダウンだけを閉じてから
  (フィールド自体の編集は破棄されない)、別の場所をクリックしてフォーカスを
  外す、という手順。これは知見10のVisualBasicEditor入力の注意点に追加される
  新しいパターンで、`uipath_ui_helpers.py`の`set_vb_expression_field()`の
  ドキュメントに反映する必要がある。
- `Read Text File`のキャンバス上インラインカード表示には`Filename`欄しか
  現れず、`Output to`(出力変数束縛)はキャンバス上では操作できない——
  Propertiesパネル(右側ペイン、`Output`グループ)を開く必要がある。これは
  「メインの入力プロパティだけがキャンバスにインライン表示され、出力プロパティ
  やその他の設定はPropertiesパネル行き」という、UiPathデザイナーUIの一般的な
  パターンだと考えられる(`MessageBox`の`Text`、`Assign`の左辺=`To`、
  `ForEach`の`CurrentIndex`などでも同様の構造が予想されるが、各アクティビティ
  ごとの実機確認はまだ網羅していない)。

## 17. `Invoke Code`——インラインVB.NETコードブロックの直列化形と、2種類目の`Arguments`コレクション形

`Invoke Code`(`UiPath.Core.Activities.InvokeCode`、Available > Workflow > Invoke)
を実機確認した。これはPADに無いUiPath特有のアクティビティで、デザイナー上の
「Edit Code」ボタンから開く専用の`Code Editor`ダイアログ(VB.NET/C#選択可、既定
`VBNet`)にインラインでコードを書けるものだが、**デザイナー上は単なるテキスト
エディタ扱いで、変数名の補完・構文ハイライト以上の支援はなく、`()`を含む
VB式を1文字ずつ`send_keys`で入力する際に特別なエスケープ(`{(}`/`{)}`)が
必要**(`pywinauto`の`send_keys`特殊構文のため、知見10の罠と同系統)。

`content = content.ToUpper()`というコードを入力して保存した結果:

```xml
<ui:InvokeCode ContinueOnError="{x:Null}" Code="content=content.ToUpper()"
    DisplayName="Invoke code" sap2010:WorkflowViewState.IdRef="InvokeCode_1">
  <ui:InvokeCode.Arguments>
    <scg:Dictionary x:TypeArguments="x:String, Argument" />
  </ui:InvokeCode.Arguments>
</ui:InvokeCode>
```

ポイント:

- `Code`プロパティは**プレーンな文字列属性**(`Code="content=content.ToUpper()"`)
  として直列化され、知見14の`[...]`角括弧式(`VisualBasicValue`省略記法)にも
  知見7/13の`<Literal>`要素にもならない。これは`Code`の型が`InArgument<String>`
  ではなく単純な`String`プロパティだからだと考えられる——「コードそのもの」は
  実行時に評価されるVB式ではなく、アクティビティが内部でコンパイルする
  ソーステキストという扱い。デザイナー入力欄に空白を含むコードを入力したが
  (`content = content.ToUpper()`)、保存後は**等号の前後の空白が自動的に除去**
  されていた(`content=content.ToUpper()`)——Code Editorダイアログ側で何らかの
  整形/正規化が行われている可能性がある(未検証: VB.NETパーサーによる
  再フォーマットか、単なる入力欄のトリミングか)。
- `Invoke Code`の`Arguments`(引数の受け渡し、`Edit Arguments`ボタン経由)は、
  **空のときだけ**`scg:Dictionary x:TypeArguments="x:String, Argument"`
  (`System.Collections.Generic.Dictionary<string, Argument>`の素の直列化、
  自己終了タグ`<scg:Dictionary .../>`)になる。知見20で1件追加して検証した
  ところ、**値が1つ以上あるときは`scg:Dictionary`という型名自体がXAML上から
  消え**、知見12の`Invoke Workflow File`や知見21の`Switch`のcaseと同じ
  `x:Key`付き子要素の並びに切り替わることが判明した(詳細は知見23)。
  つまり「空コレクションのときだけ具象型`scg:Dictionary`で明示的に直列化され、
  要素が入ると`IDictionary<TKey,TValue>`共通の`x:Key`タグ付き子要素列という
  WF標準の表現に統一される」という規則だと考えられる——当初の想定(知見17執筆時)
  とは逆の結果だった。
- `ContinueOnError="{x:Null}"`は他のアクティビティ(知見12の`Invoke Workflow
  File`)と同じ「未設定のNullable(Of Boolean)は`{x:Null}`」パターン。
- **移行上重要な意味論の発見**: 保存後にデザイナーへ戻ると、Propertiesパネル上部に
  `No compiled code to run / error BC30451: 'content' is not declared.`という
  コンパイルエラーが表示された。`content`はこの`Invoke Code`を含む`Sequence`の
  スコープに宣言済みの変数(知見8の`<Container.Variables>`)だが、**`Code`ブロックは
  それを暗黙に参照できない**——知見8で確認した「通常のVB式(`[...]`角括弧やActivity
  プロパティ)はスコープ内の変数をクロージャ的に自由参照できる」という挙動とは
  異なり、`Invoke Code`のコードは独立にコンパイルされる別アセンブリ相当の文脈で
  実行され、外側のスコープの変数を使うには`Edit Arguments`経由で明示的に
  `Argument`として宣言・束縛する必要がある、という設計だと考えられる。
  トランスパイラにとっては「`Invoke Code`内で使われる識別子は、周囲のPythonスコープ
  にある変数と同一視してはならず、必ず明示的な引数渡しとして扱う」という制約が
  導ける——これはPAD側に存在しない概念で、UiPath固有の移行上の注意点。
  (`Error List`パネルの"No errors found"は`Analyze Project`等を明示的に実行した
  場合のlint結果であり、このコンパイルエラーとは別系統——後者はActivity自身の
  デザイン時検証。両者の関係・トリガー条件は未確認。)

## 18. `Break`は属性なしの自己終了タグ——プロパティを持たないアクティビティの最小形

P0項目の残りだった制御フロー系アクティビティのうち`Break`
(`UiPath.Core.Activities.Break`、Available > Workflow > Control)を実機確認した。
キャンバスに追加しただけで(プロパティを一切設定せず)保存した結果:

```xml
<ui:Break sap:VirtualizedContainerService.HintSize="497,22" sap2010:WorkflowViewState.IdRef="Break_1" />
```

`DisplayName`すら属性に現れない——デザイナー上は「Break」という名前で表示されて
いた。これは一見、知見6の「既定値は省略される」パターンの`DisplayName`版に見えるが、
**単純にそう断定はできない**: 知見6で見た`TryCatch`は空の状態でも
`<TryCatch DisplayName="Try Catch" />`のように、既定値と一致する`DisplayName`を
明示的に保持していた。つまり同じ「既定名のまま」でもアクティビティによって
`DisplayName`を出力する/しないが分かれている——`Break`のような極小アクティビティ
(プロパティが実質無い)では省略され、`TryCatch`のような構造を持つアクティビティ
では保持される、という傾向が今回のサンプルからは読み取れるが、母数が少なく
確定的な規則とは言えない。トランスパイラ側は「`DisplayName`属性が無い場合は
アクティビティ種別の既定表示名を使う」というフォールバックを用意しておく必要がある。

P0項目「制御フロー一式」の残りは`Parallel`のみとなった(知見1参照)。

## 19. `Parallel`は`ui:`名前空間を持たない「素の」WFアクティビティ

P0の制御フロー一式の最後の未着手項目だった`Parallel`
(Available > Workflow > Control)を実機確認した。キャンバスに追加しただけ
(ブランチを1つも追加しない状態)で保存した結果:

```xml
<Parallel sap:VirtualizedContainerService.HintSize="497,101" sap2010:WorkflowViewState.IdRef="Parallel_1" />
```

ポイント:

- **`ui:`プレフィックスを持たない**——`If`/`TryCatch`/`Assign`/`Sequence`と同じ
  `System.Activities.Statements.Parallel`で、`Parallel`はUiPathによる再実装が
  無く素のWindows Workflow Foundationの標準アクティビティがそのまま使われている
  ことを実機確認できた(Propertiesパネルの型表示も`System.Activities.Statements.
  Parallel`)。知見14で判明した「`While`/`DoWhile`はUiPath独自実装(`ui:
  InterruptibleWhile`等)」とは対照的——**どの制御フローがUiPath再実装でどれが
  素のWFかはアクティビティごとに個別に確認する必要がある**、という知見14の
  教訓がここでも裏付けられた。
- プロパティは`Condition`(VB式、任意)と`Private`のみ。ブランチ(並列実行する
  複数の子アクティビティ)はデザイナー上「Drop activity here」という**ドラッグ
  &ドロップ専用のゾーン**になっており、今回使っている検索ポップアップ経由の
  アクティビティ追加操作(`+`ボタンクリック→名前入力→Alt+N)が機能しなかった
  ——クリックしても検索ポップアップが開かない。これは知見9の「Switchのcase本体
  へのアクティビティ追加が反映されない」という既知の未解決問題と**同じ種類の
  UI自動化上の制約**だと考えられる(両方とも「ドロップゾーン」という特殊な
  挿入先UI)。そのため`Parallel`に複数ブランチを追加した場合の実際のXAML構造
  (`<Parallel>`の子要素として複数のActivityが並ぶと推測されるが未確認)は
  今回も確認できなかった——真のドラッグ&ドロップ(mouse press/move/release)の
  シミュレーションが必要な、共通の今後の課題として記録する。
- `Parallel For Each`(`ForEach`の並列版)、`Run Parallel Process`
  (別プロセスとして並列実行、`UiPath.System.Activities`配下)という関連
  アクティビティも検索結果で見つかった——いずれも未確認。

P0項目1「制御フロー一式のXAML確認」は、単体アクティビティとしての型・プロパティ
確認という意味では全項目(If/Switch/While/DoWhile/ForEach/TryCatch/Parallel/
Break)が完了した。ただし**複数の子アクティビティをドロップゾーンに追加した
場合の構造**(Switchのcase本体、Parallelの各ブランチ)はドラッグ&ドロップ
自動化が未解決のため引き続き未確認——この1点のみが今後の課題として残る。

## 20. ドロップゾーンへのドラッグ&ドロップ自動化に成功——`Parallel`のブランチ構造を確定

知見9・知見19で未解決だった「`Drop activity here`型ドロップゾーンへの
アクティビティ追加」を、`pywinauto`での**真のドラッグ操作**
(`mouse.press`→複数回の`mouse.move`→`mouse.release`)で解決した。

これまでの「`+`(AddButton)クリック→検索ポップアップ→名前入力→Alt+N」という
挿入方法は、キャンバス上の「アクティビティの直後に新規追加」専用の操作であり、
`Parallel`のブランチや`Switch`のcase本体のような「汎用ドロップゾーン」はそもそも
検索ポップアップ自体を開かない設計になっている——UiPath StudioのWPFキャンバスは
これらのゾーンに対して本物のドラッグ&ドロップ(ツールボックスの`Activities`
パネルからのドラッグ)だけを受け付ける。`press()`した直後に1回だけ`move()`で
目的地へ飛ばすと、WPFのドラッグ開始閾値(数ピクセルの移動量)を下回り
ドラッグとして認識されないことがあったため、中間地点を経由する複数回の`move()`
を挟む必要があった(`dump_daemon/uipath_ui_helpers.py`の
`drag_activity_from_panel()`として実装・一般化した)。

この手法で`Parallel`に`Assign`(`To = content`, `Value = "branch1"`)を1つ
ドラッグした結果:

```xml
<Parallel sap:VirtualizedContainerService.HintSize="497,106" sap2010:WorkflowViewState.IdRef="Parallel_1">
  <Assign sap:VirtualizedContainerService.HintSize="262,60" sap2010:WorkflowViewState.IdRef="Assign_2">
    <Assign.To>
      <OutArgument x:TypeArguments="x:String">[content]</OutArgument>
    </Assign.To>
    <Assign.Value>
      <InArgument x:TypeArguments="x:String">branch1</InArgument>
    </Assign.Value>
  </Assign>
</Parallel>
```

ポイント:

- **各ブランチは`<Parallel>`の直接の子`Activity`要素**であることが確定した
  ——`Sequence`等のラッパーは強制されない(単一アクティビティのブランチは
  そのアクティビティ自身がそのまま子になる)。複数ステップを1ブランチに
  入れたい場合はユーザーが明示的に`Sequence`をドラッグする必要があると推測
  されるが、これ自体は今回未検証。
- `Assign.To`/`Assign.Value`は、知見13で確立した規則(`x:TypeArguments`が
  `x:Object`以外の明示的型のときは`<InArgument>`/`<OutArgument>`要素+生テキスト)
  通りの形で確認できた——`[content]`という角括弧形は`OutArgument`要素の
  **中身のテキスト**として書かれており(属性値のショートハンドではない)、
  `branch1`という`Value`も引用符なしの生テキストになっている。これは`Assign`
  アクティビティ単体でこの明示要素形を見る初めての実例(これまでは知見12の
  `Invoke Workflow File`引数`<InArgument x:Key="...">`でのみ確認していた)。
- **2つ目以降のブランチの追加は今回未検証のまま残った**——1つ目のブランチ
  (`Assign`)を追加した直後、2つ目のアクティビティ(`Write Line`)を隣接
  ドロップゾーンへドラッグする試行では実際には追加されなかった(キャンバスが
  横スクロールしていて座標がずれていた可能性が高い)。ドラッグ先の座標を
  事前にスクリーンショットで確認してから実行する、という運用上の注意が必要
  ——複数ブランチの子要素の並び方自体は「`<Parallel>`配下に複数の`Activity`
  要素が並ぶだけ」という単純な構造になると予想されるが、実機未確認。
- この手法は`Switch`のcase本体(知見9)にも同様に適用できるはずで、次の
  実験候補とする。

## 21. `Switch`のcaseにアクティビティを追加した実XAML形が確定——`x:Key`はアクティビティ要素自身の属性になる

知見9・知見20で積み残しだった「`Switch`のcaseにアクティビティを実際に入れた
場合の`x:Null`以外の形」を、知見20で確立した`drag_activity_from_panel()`で
解決した。`Switch`(`Expression="[result]"`、Int32型、case `1`)のcase本体
(Outlineパネル上は`Switch > Case: 1`として表示される)に`Assign`
(`To = content`, `Value = "case1"`)をドラッグした結果:

```xml
<Switch x:TypeArguments="x:Int32" DisplayName="Switch" Expression="[result]" ...>
  <Assign x:Key="1" sap:VirtualizedContainerService.HintSize="262,60" sap2010:WorkflowViewState.IdRef="Assign_3">
    <Assign.To>
      <OutArgument x:TypeArguments="x:String">[content]</OutArgument>
    </Assign.To>
    <Assign.Value>
      <InArgument x:TypeArguments="x:String">case1</InArgument>
    </Assign.Value>
  </Assign>
</Switch>
```

ポイント:

- 知見9で確認した空caseの形`<x:Null x:Key="1" />`と比較すると、**`x:Key`属性は
  `x:Null`要素ではなく、実際に配置したアクティビティ要素自身(`<Assign
  x:Key="1" ...>`)に移動する**——`Switch`の内部表現は
  `IDictionary<TKey, Activity>`で、case値(`x:Key`)はこの辞書のキーとして
  どのActivity型の要素にも同じように付与される、という素直な構造だと確定した。
  `x:Null`は「このキーに対応する値(Activity)がまだ無い」ことを表す
  プレースホルダに過ぎず、`x:Key`自体はcase値のキャリアであって`x:Null`固有の
  ものではなかった。
- 1 caseに複数ステップを入れたい場合は(`Parallel`のブランチと同様)ユーザーが
  明示的に`Sequence`をドラッグしてその中に複数アクティビティを入れる必要がある
  と推測される(1 caseに対応する値は単一の`Activity`のため)——これ自体は未検証。
- これで知見9・19・20で積み残していた「ドロップゾーン系」の構造確認はすべて
  完了した。`drag_activity_from_panel()`ヘルパーは`Switch`のcase、`Parallel`の
  ブランチの両方で同じ呼び出し方で機能することが実証された。

## 22. `Excel Application Scope`——「スコープ」系アクティビティの実XAML形(`ActivityAction`+`DelegateInArgument`をForEachと共用)

P1項目7(高頻度アクティビティ)の一環として、Excel/Mail/Database等で共通する
「スコープ(接続を開いて配下のアクティビティで使い、閉じる)」構造の代表例として
`Excel Application Scope`(`UiPath.Excel.Activities`、Available > App
Integration > Excel)を実機確認した。`WorkbookPath`に`"wb.xlsx"`を設定し、
内部に`Write Cell`(`Sheet1`のセル`A1`に`"hello"`を書き込み)を1つ追加した結果:

```xml
<ui:ExcelApplicationScope Password="{x:Null}" DisplayName="Excel Application Scope"
    InstanceCachePeriod="3000" WorkbookPath="wb.xlsx">
  <ui:ExcelApplicationScope.Body>
    <ActivityAction x:TypeArguments="ui:WorkbookApplication">
      <ActivityAction.Argument>
        <DelegateInArgument x:TypeArguments="ui:WorkbookApplication" Name="ExcelWorkbookScope" />
      </ActivityAction.Argument>
      <Sequence DisplayName="Do">
        <ui:ExcelWriteCell Cell="A1" DisplayName="Write Cell" SheetName="Sheet1" Text="hello" />
      </Sequence>
    </ActivityAction>
  </ui:ExcelApplicationScope.Body>
</ui:ExcelApplicationScope>
```

ポイント:

- **「スコープ」アクティビティの中身は知見8の`ForEach`のループ本体と全く同じ
  `ActivityAction`+`ActivityAction.Argument`+`DelegateInArgument`の構造**で
  表現される——「配下のアクティビティに暗黙のコンテキスト変数を1つ渡す」という
  WFの仕組みを、ループ変数(ForEachの`item`)にもスコープの接続ハンドル
  (Excel Application Scopeの`ExcelWorkbookScope`、型`ui:WorkbookApplication`)
  にも同じように使い回している。これはUiPathの実装方針の一般原則だと考えられ、
  他のスコープ系アクティビティ(Outlook、Database、SAPなど)も同型の構造に
  なると推測できる(個別の実機確認はまだ)。
- `ExcelWorkbookScope`という`DelegateInArgument`は宣言されるものの、配下の
  `ui:ExcelWriteCell`のXAML属性(`Cell="A1"`、`SheetName="Sheet1"`、
  `Text="hello"`)のどこにも**明示的には参照されていない**——スコープ内の
  アクティビティは暗黙のうちに「最も近い祖先の`ExcelApplicationScope`」を
  対象にする設計で、デリゲート変数を直接使うのはむしろ稀なケース(複数の
  Excelインスタンスを明示的に使い分けたい場合など)だと考えられる。この点は
  `ForEach`の`item`(全ての子アクティビティから明示的に`[item]`参照する)とは
  対照的——同じ`ActivityAction`機構でも、ループ変数は明示参照が必須、
  スコープハンドルは暗黙参照が既定、という利用パターンの違いがある。
- `ExcelWriteCell`自体の属性(`Cell`/`SheetName`/`Text`)は、知見15の
  `Append Line`と同じ「生の属性値」直列化形(知見7/13の4形式のうち最も
  圧縮された形)になっている。

## 23. `Invoke Code`のArgumentsに値を1つ追加すると`scg:Dictionary`が消え、`x:Key`付き子要素列になる(知見17の積み残しを解決)

知見17で「空の`<scg:Dictionary x:TypeArguments="x:String, Argument" />`しか
確認できなかった」としていた`Invoke Code`の`Arguments`に、`Edit Arguments`
ダイアログから`myArg`(方向`In`、型`String`、値`content`)という引数を1つ
追加して保存した結果:

```xml
<ui:InvokeCode ContinueOnError="{x:Null}" Code="content=content.ToUpper()" DisplayName="Invoke code">
  <ui:InvokeCode.Arguments>
    <InArgument x:TypeArguments="x:String" x:Key="myArg">
      <mva:VisualBasicValue x:TypeArguments="x:String" ExpressionText="content" />
    </InArgument>
  </ui:InvokeCode.Arguments>
</ui:InvokeCode>
```

ポイント:

- 予想に反して`scg:Dictionary`という型名は一切現れず、知見12の`Invoke
  Workflow File`・知見21の`Switch`のcaseと**全く同じ**「`x:Key`付き
  `InArgument`/`OutArgument`要素が並ぶだけ」という表現になった。「空コレクション
  は具象型`scg:Dictionary`で明示直列化され、要素が入るとWF標準の`IDictionary`
  表現(`x:Key`付き子要素列)に切り替わる」という規則だと考えられる——XAML
  シリアライザが、コレクションが空の場合にのみ具象型のデフォルトコンストラクタ
  呼び出しとして表現し、要素があるときは型を問わず統一的な`IDictionary`
  構文を使う、という挙動の一例。トランスパイラの実装上は「`x:Key`を持つ兄弟
  要素の並び」を見れば型(`scg:Dictionary`か`InArgument`の辞書かを問わず)に
  関わらず同じパーサーで処理できる、という割り切りが可能。
- 引数の値`content`(変数参照)は、`<mva:VisualBasicValue
  x:TypeArguments="x:String" ExpressionText="content" />`という**知見14で
  確認したネスト要素形**になった。`[content]`角括弧属性値のショートハンドでは
  ない——角括弧ショートハンドは属性値コンテキスト(`Text="[content]"`のように
  XML属性として書く場所)でのみ使える表記であり、ここでは`<InArgument>`の
  子要素という非属性コンテキストなので、知見21の`Assign.Value`(属性値ではなく
  要素中のプレーンテキスト、リテラルの場合)とも異なり、**式(変数参照)の
  場合はネスト要素形に戻る**ことが分かった。まとめると、値の表現は
  (1) 属性値コンテキストなら`[...]`角括弧、(2) 要素コンテキストでリテラルなら
  生テキストまたは`<Literal>`要素(知見13)、(3) 要素コンテキストで式(変数参照
  等)なら`<mva:VisualBasicValue>`/`VisualBasicReference`のネスト要素、という
  3方向の使い分けがある。

## 24. `Send Outlook Mail Message`——添付ファイルの空コレクションは`scg:List`(`scg:Dictionary`とは別型)

P1項目7の一環として`Send Outlook Mail Message`(`UiPath.Mail.Activities`、
`UiPath.Mail.Outlook.Activities`に依存)を実機確認した。`To`/`Subject`/
`Body`に`"a@b.com"`/`"hi"`/`"body"`を設定した結果:

```xml
<ui:SendOutlookMail Account="{x:Null}" Bcc="{x:Null}" Cc="{x:Null}" MailMessage="{x:Null}"
    ReplyTo="{x:Null}" TimeoutMS="{x:Null}" Body="body" DisplayName="Send Outlook Mail Message"
    Importance="Normal" IsBodyHtml="False" IsDraft="False" Sensitivity="Normal"
    Subject="hi" To="a@b.com">
  <ui:SendOutlookMail.Files>
    <scg:List x:TypeArguments="InArgument(x:String)" Capacity="0" />
  </ui:SendOutlookMail.Files>
</ui:SendOutlookMail>
```

- `To`/`Subject`/`Body`は知見15/22と同じ「生の属性値」形。`Importance`/
  `Sensitivity`等のenum系プロパティも同様に生の属性値(`"Normal"`)。
- 添付ファイル一覧(`Files`、UI上の「Attach Files」)は空のとき
  `<scg:List x:TypeArguments="InArgument(x:String)" Capacity="0" />`になる
  ——知見17/23で見た`Arguments`の`scg:Dictionary`とは別の具象コレクション型
  (`System.Collections.Generic.List<InArgument<string>>`)で、**空コレクション
  は具象型で明示直列化される**という知見23の規則がここでも再現されている。
  複数ファイルを追加した場合の子要素形(`<InArgument>`が並ぶだけか)は未検証。
- 併せて`Set To Clipboard`(`UiPath.System.Activities`、Available > System >
  Clipboard)も実機確認した: `<ui:SetToClipboard Text="..." />`という、
  `Append Line`/`ExcelWriteCell`と同じ最小の「生の属性値」形のみで、プロパティ
  は`Text`1つだけの単純なアクティビティだった。`Get From Clipboard`
  (出力変数バインド)・`Copy Selected Text`(選択中のUI要素からの取得、`Target`
  セレクタを持つと予想される)は未確認。

## 25. Libraryプロジェクトの`project.json`——`Process`との4つの構造的差分を確定

P0項目4(project.jsonの全体スキーマ)のLibrary部分を実機確認した。Home画面の
「New Project」から「Library」を選択して`xaml_probe_lib`という空のLibrary
プロジェクトを新規作成し、生成された`project.json`を既存の`xaml_probe`
(Process)の`project.json`(知見1)と比較した:

```json
// xaml_probe (Process)                    // xaml_probe_lib (Library)
"main": "Main.xaml",                       "main": "NewActivity.xaml",
"dependencies": {                          "dependencies": {
  "UiPath.Excel.Activities": "[2.10.4]",     "UiPath.Excel.Activities": "2.10.4",
  ...                                          ...
},                                          },
"designOptions": {                         "designOptions": {
  "outputType": "Process",                   "outputType": "Library",
  ...                                          ...
},                                          },
"entryPoints": [                           // ← entryPoints キー自体が存在しない
  { "filePath": "Main.xaml", ... }
],
```

ポイント(4つの構造的差分):

1. **`main`のデフォルトファイル名が異なる**: Processは`Main.xaml`、Libraryは
   `NewActivity.xaml`——Libraryプロジェクト新規作成時のプロジェクトツリーにも
   `Main.xaml`ではなく`NewActivity.xaml`が生成される。
2. **`dependencies`のバージョン表記から角括弧が消える**: Processは
   `"[2.10.4]"`(NuGetの厳密固定レンジ構文)だが、Libraryは`"2.10.4"`
   (角括弧なし、"この値以上"を意味する最小バージョン制約)になる。これは
   Libraryが他プロジェクトに依存関係として取り込まれることを前提に、
   消費側プロジェクトとのバージョン互換性解決の余地を残すための意図的な
   違いだと考えられる——**同じ`UiPath.Excel.Activities`という依存関係文字列
   でも、プロジェクト種別によって記法の意味が変わる**ため、トランスパイラが
   `project.json`から依存バージョンを読み取る際はこの違いを区別する必要がある。
3. **`designOptions.outputType`が`"Process"`→`"Library"`に変わる**——これが
   P0調査当初に探していた「project.jsonのtargetFramework以外のプロジェクト
   種別スイッチ」の正体だった。ただし**これはUI上のトグルではなく、
   新規プロジェクト作成時にウィザードで選んだ種別がそのまま書き込まれる
   だけの値**で、既存プロジェクトの種別を後から変更するUIはStudio上に
   存在しない(作成後に`project.json`を手で書き換えるしかないと推測される)
   ——これまでのP1 #9調査で「Project Settingsダイアログにそれらしいトグルが
   見当たらない」という結果だったのも、探す場所が元々間違っていた
   (プロジェクト作成ウィザードの選択肢であって、後からの設定項目ではない)
   ことで説明がつく。
4. **`entryPoints`キー自体がLibraryには存在しない**——Processでは
   `[{filePath, uniqueId, input, output}]`という配列だったが(知見1)、
   Libraryの`project.json`には`entryPoints`というキーそのものが無い。
   Libraryは「どのワークフローも再利用可能な部品になりうる」という性質上、
   単一の実行開始点という概念がそもそも無いためだと考えられる。
5. (差分ではないが念のため) `targetFramework`は Library でも`"Legacy"`
   のままで、知見1の既存調査候補(`Windows`/`Cross-platform`切り替えUIが
   見当たらない)はLibraryプロジェクトでも再現しなかった——この項目は
   引き続き本バージョンのStudioでは露出していないと考えられる。

補足: 既定で生成される`NewActivity.xaml`の中身は、Processの`Main.xaml`
(常に`<Sequence>`がルート、知見1)とは異なり**`<Activity>`直下に
名前空間/アセンブリ参照だけがあり、ルートとなる子アクティビティが
一切存在しない空のXAML**だった(空のLibraryなのでデザイン画面に何も
配置していないため)。また`x:Class="Main"`になっており、ファイル名
`NewActivity.xaml`とは一致しない——`x:Class`はファイル名から独立した
論理クラス名で、Libraryでは既定で`Main`になるらしい(Processの
`Main.xaml`でも同様に`x:Class="Main"`だったため、Studioの既定クラス名
生成ロジックがファイル名に依存しないことが分かる)。

## 26. Libraryのワークフローに引数を追加すると、ルート要素が`ActivityBuilder`に変わる——Processの`x:Class`付きワークフローとは別物

Libraryプロジェクト(`xaml_probe_lib`、知見25)の`NewActivity.xaml`に`Assign`
アクティビティ1つ(`in_greeting = "hi"`)を追加し、「To」欄に書いた未宣言の
識別子`in_greeting`をVariablesパネルでいったん`String`型変数として正式宣言
(知見10〜のパターン)したうえで、その変数の右クリックメニューから
**`Convert to Argument`** を実行して`In`方向・`String`型の引数に昇格させた。
保存後のXAML全文(抜粋)は以下の通りで、知見12で見た`Sub1.xaml`(Processの
2つ目のワークフロー、`Invoke Workflow File`からファイルパス参照される側)とは
**ルート要素の構造自体が異なる**という重大な違いが判明した:

```xml
<!-- xaml_probe_lib/NewActivity.xaml(Library、引数を持つ) -->
<Activity mc:Ignorable="sap sap2010"
    xmlns:this="clr-namespace:" ...>  <!-- x:Class 属性が無い! -->
  <x:Members>
    <x:Property Name="in_greeting" Type="InArgument(x:String)" />
  </x:Members>
  <this:Main.in_greeting>                        <!-- 新パターン -->
    <InArgument x:TypeArguments="x:String" />
  </this:Main.in_greeting>
  ...
  <sap2010:WorkflowViewState.IdRef>ActivityBuilder_1</sap2010:WorkflowViewState.IdRef>
  ...
  <Sequence ...>
    <Assign ...>
      <Assign.To>
        <OutArgument x:TypeArguments="x:String">[in_greeting]</OutArgument>
      </Assign.To>
      <Assign.Value>
        <InArgument x:TypeArguments="x:String">hi</InArgument>
      </Assign.Value>
    </Assign>
  </Sequence>
</Activity>
```

```xml
<!-- xaml_probe/Sub1.xaml(Process、Invoke Workflow Fileからファイルパス参照、知見12) -->
<Activity ... x:Class="Sub1" ...>
  <x:Members>
    <x:Property Name="in_text" Type="InArgument(x:String)" />
  </x:Members>
  ...
```

ポイント:

1. **`x:Class`属性が消え、代わりに`xmlns:this="clr-namespace:"`という空の
   名前空間エイリアスが現れる**——Sub1.xamlでは`x:Class="Sub1"`という
   具体的なクラス名が付いていたのに対し、Libraryの引数付きワークフローでは
   クラス名による命名をやめ、無名の`this:`エイリアス経由でメンバーに
   アクセスする形に変わっている。
2. **`<this:Main.{引数名}>`という、知見12には無かった新しい要素が追加される**
   ——`<x:Members>`での`x:Property`宣言(型だけの宣言)に加えて、この要素が
   実際の`InArgument`インスタンス(空のプレースホルダ)をその名前付きメンバーに
   紐付けている。Sub1.xamlでは型宣言だけで十分だったのに、Libraryの
   ワークフローではこの追加のバインディング要素が必要になる——WFの
   `ActivityBuilder`(名前付きActivityのビルダーパターン)が`x:Class`方式とは
   別の、より明示的なメンバーバインディング機構を使っているためだと考えられる。
3. **`sap2010:WorkflowViewState.IdRef`のルート要素が`ActivityBuilder_1`**
   になっている——Sub1.xamlやMain.xamlのルートはシリアライズ上は`Activity`
   要素のままIdRefも通常の活性化アクティビティ命名規則(`Sequence_N`等)
   だったのに対し、Libraryの引数付きワークフローは明示的に`ActivityBuilder`
   という型として識別子が振られている。これは「このXAMLはファイルパスで直接
   実行されるワークフローではなく、再利用可能なActivity型としてコンパイルされる
   設計時定義である」ということをStudio/WFランタイムが区別して扱っている
   証拠だと考えられる——Libraryがビルドされると各ワークフローが実際に
   `System.Activities.ActivityBuilder`からコンパイルされた個別のActivity型
   (DLL内のクラス)になる、というUiPath Libraryの基本的な仕組み
   (「このXAMLを他プロジェクトからツールボックスの1アクティビティとして
   使えるようにする」)がXAMLの型注釈レベルでも確認できたことになる。
4. (環境面のノイズ) `Convert to Argument`実行後、保存されたXAMLの
   `TextExpression.ReferencesForImplementation`に`UiPath.Excel`・
   `UiPath.Mail`・`System.ServiceModel`等、空のワークフロー作成時
   (知見25)には無かった大量のアセンブリ参照が追加されていた——
   Studioが最初のアクティビティ追加時にプロジェクト全体の依存関係から
   必要になりうる参照を再計算・展開する挙動だと考えられ、意味のある
   構造差分ではない。

**移行上の意味**: トランスパイラがUiPathワークフローXAMLを解析する際、
「ファイルパス参照される通常のワークフロー」(`x:Class`付き)と
「Libraryとしてパッケージされ他プロジェクトからActivity型として使われる
ワークフロー」(`ActivityBuilder`型、`this:`エイリアス経由のメンバー
バインディング)を区別する必要がある——後者はLibraryプロジェクトの
`NewActivity.xaml`のような、引数を1つ以上持つワークフローで出現する
(知見25で確認した「空のLibraryワークフローにはこの区別が無い」ことから、
区別が生じるのは引数を追加した時点だと推測されるが、引数ゼロのまま
Libraryとして公開した場合にどうなるかは未検証)。

## 27. Library参照経由のアクティビティ呼び出しは`InvokeWorkflowFile`と全く別物——CLR名前空間エイリアス経由の直接要素呼び出しになる(P1 #8完結)

知見25・26で作成・公開した`xaml_probe_lib`ライブラリ(ローカルNuGetフィード
経由、知見末尾の「長時間処理」要領参照)を`xaml_probe`(Process)の依存関係に
追加し、Activitiesパネルから実際にドラッグ&ドロップで`Main.xaml`に配置した
結果、知見12の`ui:InvokeWorkflowFile`(ファイルパス参照)とは**全く異なる**
直列化形になることが判明した:

```xml
<!-- ルートActivity要素のxmlns宣言に新しいエイリアスが追加される -->
<Activity ... xmlns:p="clr-namespace:xaml_probe_lib;assembly=xaml_probe_lib" ...>
  ...
  <!-- 実際の呼び出し: 単一のXML要素、引数は生のXML属性 -->
  <p:NewActivity sap:VirtualizedContainerService.HintSize="497,22"
      sap2010:WorkflowViewState.IdRef="NewActivity_1"
      in_greeting="hellofromlib" />
```

ポイント:

1. **ライブラリは`clr-namespace:{ライブラリ名};assembly={ライブラリ名}`という
   CLR名前空間アセンブリ参照として、XAMLのルート`xmlns:`宣言に追加される**
   (今回のエイリアスは自動採番で`p:`)。`UiPath.Core.Activities`が`ui:`、
   `System.Activities.Statements`が無接頭辞、という既知の名前空間と同列に、
   **自作Libraryも「普通のコンパイル済み.NETアセンブリの名前空間」として
   扱われる**ことが実機で確定した——知見26で確認した「Libraryのワークフローは
   `ActivityBuilder`としてコンパイルされ独立したActivity型になる」という
   推測が、消費側プロジェクトのXAMLでも完全に裏付けられた形になる。
2. **呼び出しは`<p:{ワークフローファイル名}>`という単一のXML要素**になり、
   知見12の`ui:InvokeWorkflowFile`+`WorkflowFileName`属性+
   `<ui:InvokeWorkflowFile.Arguments>`という「ラッパーアクティビティ+
   辞書コレクション」の2段構造が一切出てこない——ライブラリ参照のワークフロー
   は、Message BoxやAppendLineのようなビルトインアクティビティと**全く同じ
   直列化パターン**(単一要素+属性)で呼び出される。要素名はLibrary内の
   XAMLファイル名(`NewActivity.xaml`→`NewActivity`)がそのままActivity型名
   になっている(知見26で確認した`x:Class="Main"`ではなく、ファイル名が
   採用される点に注意——`x:Class`はLibraryのコンパイル時に型名として
   使われていない、または上書きされると考えられる)。
3. **ワークフロー引数(`in_greeting`)は、`InArgument`/`[...]`角括弧のどちらでも
   なく、プレーンなXML属性値**(`in_greeting="hellofromlib"`)になった——
   これは知見7/13/15で確立した「コンパイル時定数リテラルは生の属性値」という
   規則の延長で説明がつく(値が単純な文字列リテラルだったため)。変数参照や
   式を渡した場合に`[...]`角括弧形になるかは今回未検証だが、知見13の規則
   (属性値コンテキストでは式は角括弧ショートハンド)から類推すると、式を渡せば
   `in_greeting="[someVar]"`になると予想される。
4. 依存関係として追加されたLibraryは、Process側の`TextExpression.
   NamespacesForImplementation`/`ReferencesForImplementation`コレクションにも
   (他のUiPathパッケージと同列に)`xaml_probe_lib`という名前空間・
   アセンブリ参照として自動追加されていた。

**移行上の結論**: トランスパイラの観点では、「Library参照のアクティビティ
呼び出し」は構造的には「サードパーティ/ビルトインのカスタムアクティビティ
呼び出し」と区別する必要が無い——両方とも「XML要素名(`{alias}:{型名}`)+
属性としての入力引数」という同じパターンで表現される。むしろ区別が必要
なのは**「ファイルパスで直接参照されるサブワークフロー」(`ui:
InvokeWorkflowFile`、知見12)と「パッケージとして配布されるワークフロー」
(Library参照、本知見)の2つの呼び出し方式**であり、後者を見分ける唯一の
手がかりは、要素の名前空間エイリアスがルート`xmlns:`宣言で
`clr-namespace:{プロジェクト固有名};assembly={同名}`という自作ライブラリ
らしいパターンになっているかどうか(`UiPath.*`や`System.*`等の既知の
公式名前空間ではないかどうか)を`project.json`の`dependencies`と突き合わせて
判定する、という設計になりそうである。

## 28. `.nupkg`の中身を実機確認——**公開されたLibraryには元のXAMLソースが含まれない**(移行戦略上の重大な制約)

知見27で公開した`xaml_probe_lib.1.0.1.nupkg`(実体はZIP形式のOPCパッケージ、
NuGetパッケージそのもの)を展開して中身を確認した(P2項目14)。

```
xaml_probe_lib.nuspec
[Content_Types].xml
_rels/.rels
package/services/metadata/core-properties/{guid}.psmdcp
lib/net45/
  xaml_probe_lib.dll                            ← コンパイル済み本体アセンブリ
  xaml_probe_lib_Expressions_43412436.dll        ← VB式だけを集めた別アセンブリ
  project.json                                    (そのまま同梱)
  .settings/Release/settings-*.json × 6           (デザイン時既定値のスナップショット)
```

`xaml_probe_lib.nuspec`の内容(抜粋):

```xml
<dependencies>
  <group targetFramework=".NETFramework4.6.1">
    <dependency id="UiPath.Excel.Activities" version="2.10.4" />
    ...
  </group>
</dependencies>
```

ポイント(移行ツール設計への影響が大きい、重要度の高い発見):

1. **`.nupkg`は標準的なOPC(Open Packaging Conventions)形式のZIPで、
   中身は`[Content_Types].xml`・`_rels/.rels`・`package/services/
   metadata/core-properties/*.psmdcp`という、.docx/.xlsx等と同じ
   Microsoftパッケージング規格に準拠している**——`project.json`の
   `"targetFramework": "Legacy"`は、実際のNuGetパッケージでは
   `targetFramework=".NETFramework4.6.1"`という具体的なTFM
   (Target Framework Moniker、フォルダ名としては`lib/net45/`という
   慣用の短縮形)に対応することが確定した。
2. **ワークフローのロジックは`xaml_probe_lib.dll`という単一のコンパイル済み
   .NETアセンブリにビルドされ、VB式(`[...]`角括弧式)は
   `{ライブラリ名}_Expressions_{ハッシュ}.dll`という別アセンブリに
   さらに分離コンパイルされる**——知見14で解明した「`[...]`=
   `VisualBasicValue`の省略記法」という式の仕組みは、Library公開時には
   ついに「動的評価されるVB式インタープリタ呼び出し」から「事前コンパイル
   された.NET IL」に変換される、という最終形態が確認できた。
3. **最も重要な発見: `project.json`は同梱されるが、元の`.xaml`ソース
   ファイルは一切含まれていない**——Publishダイアログの「Include Sources」
   チェックボックス(知見23時点では未検証、既定でオンになっていた)は
   オンのまま公開したにもかかわらず、展開したパッケージ内のどこにも
   `*.xaml`が見つからなかった。これは「Include Sources」が別の意味
   (おそらくPDBデバッグシンボル、または別の配布経路)を指しており、
   **公開されたLibraryパッケージを入手しただけでは、ワークフローの元の
   XAML構造(=知見1〜27で解析してきたアクティビティ木)を取り出す手段が
   無い**ことを意味する。
4. **移行戦略上の帰結**: PAD→Python移行(pad2py)では「ユーザーが保有する
   `.pad`ファイル(≒ソースそのもの)を直接解析する」という前提が成立したが、
   UiPath→Python移行では、**対象プロジェクトが外部Library(自作の
   `.nupkg`、Marketplace製アクティビティ等)に依存している場合、そのLibrary
   内部のワークフローロジックはXAML解析の対象にできず、`.dll`の.NET
   デコンパイル(ILSpy等)という全く別の技術スタックが必要になる**。
   これは「UiPath→Pythonは開いた隙間(niche)だが、依存Libraryを多用する
   大規模プロジェクトでは追加の障壁がある」という business context上の
   重要な留保事項であり、今後の調査候補・ビジネス文脈メモリに反映する
   価値がある。自プロジェクト内の`.xaml`(Process本体やファイルパス参照の
   サブワークフロー)は従来通り解析可能——問題になるのはあくまで
   「外部配布されたLibrary」経由のロジックに限られる。

## 29. HTTP Requestアクティビティ——DisplayNameと裏のCLR型名が一致しない例、`{x:Null}`による未設定引数の直列化パターン

P1 #7(高頻度アクティビティの網羅)の残課題だった**HTTP Request**を確認した。
Studio 2021.4.4標準の`UiPath.WebAPI.Activities` v1.18.0は
「Studio 22.10.5以降が必要」という互換性エラーで追加できなかったため、
Manage PackagesダイアログのVersionドロップダウンから**v1.6.0**を明示選択して
インストールし直すことで追加できた(新しいバージョンがデフォルトで
提示されても、古いStudioでは動かないことがある——`project.json`の
`dependencies`は常に「使われているバージョン」であって「最新版」とは
限らないことの実例)。

キャンバスに追加すると、プロパティパネルでの編集を待たずに**専用の
「HTTP Request Wizard」ダイアログ**が自動的に開いた(End point / Timeout /
Request Method / Accept response as / Parameters / Attachments /
Authentication等をまとめて設定できるウィザードUI)。これは設計時のみの
UX上の便宜であり、確定したXAML構造には影響しない。

確定したXAML(`If.Then`内、`EndPoint`は動作確認用のプレースホルダ値):

```xml
<ui:HttpClient Body="{x:Null}" ConsumerKey="{x:Null}" ConsumerSecret="{x:Null}"
    ContinueOnError="{x:Null}" OAuth1Token="{x:Null}" OAuth1TokenSecret="{x:Null}"
    OAuth2Token="{x:Null}" Password="{x:Null}" ResourcePath="{x:Null}"
    ResponseHeaders="{x:Null}" Result="{x:Null}" StatusCode="{x:Null}"
    Username="{x:Null}" AcceptFormat="ANY" BodyFormat="application/xml"
    ClientCertificate="[Nothing]" ClientCertificatePassword="[Nothing]"
    DisplayName="HTTP Request" EndPoint="https(example.com/api)"
    sap:VirtualizedContainerService.HintSize="200,22"
    sap2010:WorkflowViewState.IdRef="HttpClient_1" Method="GET" TimeoutMS="6000">
  <ui:HttpClient.Attachments>
    <scg:Dictionary x:TypeArguments="x:String, InArgument(x:String)" />
  </ui:HttpClient.Attachments>
  <ui:HttpClient.Cookies>
    <scg:Dictionary x:TypeArguments="x:String, InArgument(x:String)" />
  </ui:HttpClient.Cookies>
  <ui:HttpClient.Headers>
    <scg:Dictionary x:TypeArguments="x:String, InArgument(x:String)" />
  </ui:HttpClient.Headers>
  <ui:HttpClient.Parameters>
    <scg:Dictionary x:TypeArguments="x:String, InArgument(x:String)" />
  </ui:HttpClient.Parameters>
  <ui:HttpClient.UrlSegments>
    <scg:Dictionary x:TypeArguments="x:String, InArgument(x:String)" />
  </ui:HttpClient.UrlSegments>
</ui:HttpClient>
```

重要な発見:

1. **DisplayName「HTTP Request」の裏のCLR要素名は`ui:HttpClient`であり、
   `HttpRequest`ではない**。Studio UI上の表示名・Activitiesパネルの検索語と、
   実際にXAMLへシリアライズされるクラス名が一致しない例——トランスパイラ側で
   「アクティビティ名→生成コード」のマッピング表を作る際、UI表示名だけでなく
   実際のXML要素名(`ui:HttpClient`)を正としてマッピングキーに使う必要が
   あることを示す実例。
2. **未設定のまま触れられなかった引数は`{x:Null}`という WPF markup extension
   リテラルで直列化される**——これは知見16・23等で見てきた「値が入っている
   引数は`[VarName]`や`"literal"`のInArgument短縮記法になる」パターンとは別の、
   「そもそも一度もUIで値を設定していない(=未使用)引数」専用の表現。
   一方`ClientCertificate`/`ClientCertificatePassword`は同じく未設定なのに
   `[Nothing]`(VB.NETのNull値をInArgument短縮記法で表した形)になっており、
   **同じ「未設定」でも、プロパティの定義のされ方(既定値を持つかどうか等)に
   よって`{x:Null}`と`[Nothing]`の2通りの直列化がありうる**ことが分かった。
   トランスパイラは両方を「未設定/None」として同一視して読み飛ばせる必要がある。
3. **5つの`Dictionary`型コレクションプロパティ(Attachments / Cookies /
   Headers / Parameters / UrlSegments)が全て同じ空コレクション直列化
   パターン(`<scg:Dictionary x:TypeArguments="x:String, InArgument(x:String)" />`)
   を使う**——知見17・24で確認した「空のコレクションは具象型を明示した
   自己完結タグになる」パターンが、1つのアクティビティに複数の同種
   コレクションプロパティがある場合でも一律に適用されることを確認した。
4. `EndPoint`は他の単純文字列プロパティ同様、ラッパー無しの生属性値
   (`EndPoint="..."`)で表現される——`InArgument`要素化されるのは値を
   式(変数参照等)で設定した場合のみという、既存知見と一貫した結果。

これでP1 #7の高頻度アクティビティ確認(Append Line・Read Text File・
Invoke Code・Excel Application Scope+Write Cell・Send Outlook Mail Message・
Set To Clipboard・HTTP Request)はひとまず主要なものを一巡した。
残るWord/PDF/Databaseは今後の調査候補とする。

## 30. Robotic Enterprise Framework(REFramework)テンプレートを実機確認——State Machine構造の確定、`targetFramework: "Portable"`の実例、そしてUiPath自身がAI向け`AGENTS.md`/`CLAUDE.md`をテンプレートに同梱している発見(P2 #10・P0#4・P2#17)

Studio 2021.4.4のStart画面「New from Template」→「Robotic Enterprise Framework」から
テンプレート(バージョン26.10.1、クラウドから都度ダウンロードされる——インストール
済みStudioのバージョンとは独立に最新版が配布される)を使ってプロジェクトを作成した。

**重要な前提**: プロジェクト作成直後、Studioが「プロジェクトを開けない」エラーを
出した:

```
The project 'C:\Users\tomoya_kaw\Documents\UiPath\xaml_probe_reframework\project.json'
could not be opened: Could not find a part of the path 'C:\Users\tomoya_kaw\AppData\
Local\UiPath\app-21.4.4\net5.0'..
```

これは、公式テンプレート自体がインストール済みStudioよりもはるかに新しい
バージョン向けに作られていることを示す実例である(後述の`project.json`の
依存パッケージバージョンが軒並み2025〜2026年のものであることからも裏付けられる)。
Studioはプロジェクトを開けなかったが、**テンプレートのファイル一式はディスクに
展開済み**だったため、ファイルシステム経由で直接内容を確認できた。

### 30-1. ディレクトリ構造——知見25(Library)からさらに増えた新要素

```text
xaml_probe_reframework/
  project.json
  entry-points.json          ← 新規(project.jsonのentryPointsと別に存在)
  Main.xaml                  ← State Machine
  Main.xaml.json             ← 新規(ワークフロー単位のサイドカーファイル)
  README.md / LICENSE
  Data/Config.json, Data/Input|Output|Temp/placeholder.txt
  Framework/*.xaml(8ファイル)+ AGENTS.md + CLAUDE.md
  Tests/*.xaml(6ファイル)+ Tests.xlsx
  .codedworkflows/ConnectionsFactory.cs, ConnectionsManager.cs  ← Coded Workflows(C#)
  .project/design.json, CodedBindingsMetadata.json, PackageBindingsMetadata.json
  .entities/   .local/   .tmh/config.json
```

`entry-points.json`は`project.json`の`entryPoints`と内容が重複するが別ファイルで、
`"$schema": "https://cloud.uipath.com/draft/2024-12/entry-point"`を参照する——
Orchestrator/Cloud側がプロジェクト全体をパースせずエントリポイントだけ読む用の
軽量サイドカーだと推測される。`.codedworkflows/*.cs`はUiPathの「Coded Workflows」
(XAMLではなくC#で書くワークフロー)の雛形で、P2項目「Coded Workflows」の存在を
実機で確認できたことになる(中身は空の接続管理クラスのみで詳細な記法までは
未確認)。

### 30-2. `project.json`の新フィールド

```json
{
  "dependencies": {
    "UiPath.Excel.Activities": "[3.6.1]",
    "UiPath.System.Activities": "[26.6.3]",
    "UiPath.Testing.Activities": "[25.10.2]",
    "UiPath.UIAutomation.Activities": "[26.10.3]"
  },
  "studioVersion": "21.4.4.0",
  "designOptions": {
    "fileInfoCollection": [
      {"editingStatus": "InProgress", "testCaseId": "793c8ea8-...", "fileName": "Tests\\GetTransactionDataTestCase.xaml"}
    ],
    "modernBehavior": false
  },
  "expressionLanguage": "VisualBasic",
  "targetFramework": "Portable"
}
```

- **`targetFramework: "Portable"`** ——P0#4で「UI上に切替トグルが見当たらない」と
  した`Windows`/`Cross-platform`の実際のJSON値をついに実例で確認できた。知見28で
  確認した`"Legacy"`(→`.NETFramework4.6.1`、nuspecの`targetFramework`属性)とは
  別の値で、Studio UI上の表記「Cross-platform (Portable)」がそのまま
  `"Portable"`という文字列になる。依存パッケージのバージョンも軒並り新しく、
  Portableプロジェクトは.NET Framework世代のLegacyパッケージ群とは別の
  パッケージラインを要求することが分かる。
- **`expressionLanguage: "VisualBasic"`**——フィールド自体は存在し明示的に
  書かれている(P3#18の「C#式言語」はこのフィールドの値を変えるだけの
  話である可能性が高いが、Studio UIからの切替手段は今回も発見できず)。
- **`fileInfoCollection`**——Test Manager連携用に、各テストケースXAMLファイルへ
  `testCaseId`(GUID)をマッピングするテーブルが`project.json`内に埋め込まれる
  ことが判明。プロジェクトファイルとテストケースの対応はファイルパスではなく
  このGUIDで管理されている可能性がある。
- **`studioVersion: "21.4.4.0"`**——興味深いことに、これだけ新しい依存関係を
  持つテンプレートであるにもかかわらず`studioVersion`フィールドの値は
  今回使った実機のStudio(21.4.4)のバージョンがそのまま書き込まれている。
  おそらく「プロジェクトを作成した時に使ったStudioのバージョン」を記録する
  だけのメタデータであり、実際の互換性検証には使われていない(だからこそ
  開けないプロジェクトが作成できてしまった)と考えられる。

### 30-3. ルート直下の`AGENTS.md`/`CLAUDE.md`は存在しない——Studioが開いた時に生成される

今回はStudioがプロジェクトを開けなかったため、ルート直下には`AGENTS.md`/
`CLAUDE.md`は存在しなかった(ディレクトリ一覧で確認済み)。ただし
`Framework/AGENTS.md`の冒頭に次の記述がある:

> This guide lives in `Framework/` because Studio overwrites the root
> `AGENTS.md`/`CLAUDE.md` with generic files.

つまり**UiPath Studioは、プロジェクトを開いた際にルート直下へ汎用的な
`AGENTS.md`/`CLAUDE.md`を自動生成する**挙動を持つ(今回は開けなかったため
未確認・今後の課題)。テンプレート側はそれを見越して、REFramework固有の
詳しい手引きを`Framework/AGENTS.md`に退避させ、ルートの`CLAUDE.md`は
`@AGENTS.md`という1行(Claude Code方言の`@`インポート記法)だけの
中継ファイルになっている。

### 30-4. `Framework/AGENTS.md`の中身——UiPath自身がAIコーディングエージェント向けガイドを公式テンプレートに同梱していた(重要なビジネス文脈上の発見)

全文は約130行。目次的に要約すると::

- 冒頭の互換性表で`Language: VisualBasic, fixed for every workflow`、
  `.NET: Minimum Robot version 24.10 = .NET 8 / 26.10 = .NET 10`と明記。
- 「`.xaml`/`.cs`は手で編集せず**uipath-rpaという名のSkill**を使い、
  `uip rpa analyze .`で検証せよ」という指示——**UiPathが`uip`という
  統一CLIツールと、Claude Code等のコーディングエージェント向け`Skill`機構
  (本セッションで使っているものと同種の概念)を前提にした開発フローを
  公式に用意している**ことを意味する。`uip rpa pack`・`uip solution
  projects add`・`uip solution pack/publish/deploy`といったサブコマンドも
  言及されている。
- State Machineの4状態(Initialization/Get Transaction Data/Process
  Transaction/End Process)の役割、`Config`辞書・`TransactionItem`等の
  共有変数、`Framework/*.xaml`各ファイルの引数一覧を表形式で説明——
  実際のMain.xamlの構造(30-5参照)と完全に一致している。
- 「`Process.xaml`を囲む catch-all Try Catchを作るな、Global Exception
  Handlerも使うな、フレームワークが例外を分類・ルーティングする」という
  設計原則の明文化。

**戦略上の含意**: pad2pyが想定する「AIコーディングエージェントがRPAプロジェクトを
読み書きする」というワークフローを、UiPath自身が公式テンプレートレベルで
先取りして用意し始めている。これはUiPath→Python移行ツールの競合・隣接領域の
話に留まらず、「UiPathを使い続けながらAIエージェントで開発効率化する」という
道がUiPath自身によって強化されつつある、というbusiness context上の新しい
シグナルである(=移行せず居座るインセンティブが増す方向)。

### 30-5. State Machineの XAML構造(P2「State Machineワークフロー種別」が初めて実機で確認できた)

`Main.xaml`のルートは`<StateMachine>`で、構造は次の通り:

```xml
<StateMachine InitialState="{x:Reference __ReferenceID3}" DisplayName="General Business Process" ...>
  <State x:Name="__ReferenceID0" DisplayName="Get Transaction Data" ...>
    <State.Entry>
      <Sequence>...</Sequence>
    </State.Entry>
    <State.Transitions>
      <Transition DisplayName="New Transaction" ...>
        <Transition.To>
          <State x:Name="__ReferenceID2" DisplayName="Process Transaction" ...>
            <!-- 初出の参照先は中身をインラインで展開 -->
            ...
            <State.Transitions>
              <Transition DisplayName="Successful" ...>
                <Transition.To>
                  <x:Reference>__ReferenceID0</x:Reference>
                  <!-- 2回目以降の参照はx:Referenceだけになる -->
                </Transition.To>
                <Transition.Action>
                  <ui:Comment Text="Default transition is picked up if there are no errors during initialization" />
                </Transition.Action>
                <Transition.Condition>[SystemException is Nothing]</Transition.Condition>
              </Transition>
            </State.Transitions>
          </State>
        </Transition.To>
      </Transition>
      <Transition DisplayName="No Data" .../>
    </State.Transitions>
  </State>
  <StateMachine.Variables>...</StateMachine.Variables>
</StateMachine>
```

確定した構造規則:

1. **状態は標準XAMLの`x:Name`/`x:Reference`機構で相互参照される**——
   `StateMachine`の`InitialState`属性、各`Transition.To`の参照先は
   いずれも`{x:Reference __ReferenceIDn}`属性構文、または子要素形の
   `<x:Reference>__ReferenceIDn</x:Reference>`のいずれか。
2. **状態の本体(`<State x:Name="...">...</State>`)は、XAML文書中で最初に
   その状態が登場する箇所に1回だけインラインで書かれ、2回目以降の参照は
   `x:Reference`だけになる**——Switch(知見21)やInvoke Code(知見23)の
   ような「同じ構造が繰り返される」パターンとは異なり、グラフ構造(状態が
   複数の遷移元から参照されうる)を表現するための標準XAML機能を転用している。
   これはトランスパイラ実装上、素直な木構造のトップダウン走査だけでは
   対応できず、`x:Name`→実体のマップを一度構築してから`x:Reference`を
   解決する2パスの処理が必要になることを意味する。
3. **`<State.Entry>`が状態進入時に実行されるアクティビティツリー**(今回は
   常に`Sequence`)を保持する。
4. **`<State.Transitions>`は`<Transition>`要素の並び**——各`Transition`は
   `DisplayName`・`Transition.To`(遷移先)・`Transition.Condition`(VB式、
   既存の`[...]`角括弧規約)・`Transition.Action`(遷移時に実行する任意の
   アクティビティ、ここでは`ui:Comment`)を持つ。`Transition.Condition`が
   無い`Transition`は無条件遷移(デフォルト遷移)として扱われる。
5. **終了状態には`IsFinal="True"`属性が付く**(`End Process`状態で確認)。

### 30-6. 名前空間の違い——`Portable`プロジェクトは`System.Private.CoreLib`、`Legacy`プロジェクトは`mscorlib`

今回のPortableプロジェクトの`Main.xaml`ルート要素の名前空間宣言:

```xml
xmlns:s="clr-namespace:System;assembly=System.Private.CoreLib"
xmlns:sco="clr-namespace:System.Collections.ObjectModel;assembly=System.Private.CoreLib"
xmlns:sd="clr-namespace:System.Data;assembly=System.Data.Common"
```

これまでのLegacyプロジェクト(`xaml_probe`等)では一貫して
`xmlns:s="clr-namespace:System;assembly=mscorlib"`だった(知見1等)。
**`targetFramework`の値(`"Legacy"` vs `"Portable"`)によって、同じ
`System`名前空間でも参照先アセンブリ名がCLRランタイムの違い(.NET Framework
の`mscorlib` vs .NET(Core)の`System.Private.CoreLib`)に応じて変わる**ことを
確定できた。トランスパイラがXAMLの名前空間宣言から型を解決する際、
アセンブリ名の違いだけで同一視できるようにする正規化が必要になる。

これでP2「REFramework」・P0#4の`targetFramework`実例・P2「State Machine
ワークフロー種別」が一通り確認できた。`.codedworkflows/`(Coded Workflows)
の詳細な記法、Test Manager連携(`fileInfoCollection`・`Tests/*.xaml`)、
Object Repositoryは今後の調査候補として残る。

### 30-7. 付随して確認した小粒ファイル群(Coded Workflowsの雛形・ワークフロー単位サイドカー)

- **`.codedworkflows/ConnectionsFactory.cs`・`ConnectionsManager.cs`**——
  いずれも`namespace UiPath_REFramework`(プロジェクト名由来と思われる)配下の
  空の雛形。`ConnectionsManager`は`ICodedWorkflowsServiceContainer`を受け取る
  コンストラクタのみで中身は空。今回のテンプレートには実際のCoded Workflow
  (ビジネスロジックをC#で書いたワークフロー本体)は含まれておらず、外部
  接続(Excel/Webサービス等)をC#側で登録するための結線ポイントだけが
  スキャフォールドされている段階だと分かった——Coded WorkflowsはXAMLの
  `Main.xaml`を置き換えるものではなく、`.cs`ファイルとXAMLワークフローが
  並存するプロジェクト構造(C#側はあくまで「外部サービスへの接続定義」の
  置き場)という位置づけらしい。実際のCoded Workflow本体の記法は未確認。
- **`Main.xaml.json`**——ワークフロー1つにつき1つ生成されるサイドカー
  JSON。中身は`DisplayName`/`Tooltip`/`HelpLink`/`Color`/
  `OriginalIconFileName`/`Arguments`のみで、XAML本体から見た目のメタデータ
  (アイコン・色等のデザイン情報)を分離して持っているだけと見られ、
  ロジック・構造には影響しない。
- **`.project/design.json`**——プロジェクト全体の設計時設定
  (`Tags`・`SeparateRuntimeDependencies`・`IncludeSources`・
  `ConnectorKeys`)。Publishダイアログの「Include Sources」チェックボックス
  (知見28)の状態がここに保存されている可能性が高い。

## 31. Object Repositoryを有効化する条件を確認——「UIAutomationパッケージのアップグレード」+「Modern Design Experience」の両方が必要(P2 #12)

`xaml_probe`(Process、Legacy)プロジェクトで右下の「Object Repository」
タブを開くと次の案内が表示された:

> To enable Object Repository, upgrade your UIAutomation package and enable
> Modern Design Experience from Project Settings.

「Manage Packages」「Project Settings」の2つのボタンが並んでおり、
Object Repositoryの有効化には**2つの条件を同時に満たす必要がある**ことが
分かる: (1) `UiPath.UIAutomation.Activities`パッケージを(おそらくModern
Design Experience対応版に)アップグレードすること、(2) Project Settings
ダイアログの「General」タブ最下段にある**「Modern Design Experience」
トグル**(既定で`No`)を`Yes`にすること。

Project Settingsダイアログ自体は`General`・`Workflow Analyzer`・
`Activities Settings`(配下に`OCR`・`Computer Vision`・`Excel Business`・
**`UI Automation Modern`**・**`UI Automation Classic`**・`System`の
サブカテゴリ)という構成で、「UI Automation Modern」と「UI Automation
Classic」が別々のサブカテゴリとして存在することも確認できた——Modern
Design Experienceは単なる見た目の切り替えではなく、セレクタ/ターゲティング
方式そのものが「Modern」と「Classic」で分岐する設計であることが伺える
(詳細な差分は今回は未確認)。

「Modern Design Experience」トグルをクリックすると即座に
「The Modern Design Experience has changed. Reload project to apply
changes.」という確認ダイアログが出た(Reload/Cancel)。**この切り替えは
プロジェクト全体のリロードを要する重い操作**であり、この時点(知見31
初版記録時)では既存の知見1〜30で確立したXAML構造(Classic UI Automation
前提)を壊さないよう、あえてCancelして実際のリロードは行わなかった。
Object Repository配下の`.objects/`構造、Modern方式のセレクタXAML表現は
今後の調査候補として残す——調査する場合は`xaml_probe`を汚さず、専用の
新規プローブプロジェクトを別途作成してから試すのが安全、という方針を
記録していた。

**(2026-11-05追記・方針からの逸脱)**: Modern Selector実XAML確認作業の中で、
上記の「`xaml_probe`を汚さず別プロジェクトを作る」という既存方針を
再確認しないまま、実際に`xaml_probe`上で「Modern Design Experience」を
`Yes`へ切り替えてReloadを実行してしまった(本来はこの知見31を読み返して
から着手すべきだった、プロセス上の反省点)。Reload自体は正常に完了し
(「Adding Dependencies...」表示後、リボンに`App/Web Recorder`/
`Computer Vision`/`Table Extraction`が追加され、Object Repositoryパネルが
`Descriptors`/`UI Activities`タブ付きで有効化された)、スクリーンショット上
Main.xamlの既存アクティビティ木(Assign×3等、同じ赤バッジ付き)は見た目上
変化していないことを確認した。

**(2026-11-05・検証完了、実害無しと確定)**: VMが空いた後、VM上の実ファイルを
取得してコミット済みフィクスチャと直接diffした。`Sub1.xaml`は完全に
バイト一致(sha256も一致)。`Main.xaml`は差分33行のみで、内訳は
(1) `HintSize`属性値(UI上のキャンバスサイズ、デザイナーパネルの表示上の
メタデータに過ぎず意味論に無関係)の変化と、(2) 知見32の作業(本追記より
前、VB.NET演算子9種の実機コンパイル確認)で`Main.xaml`先頭に追加した3件の
テスト用`Assign`(知見32本文に明記されている既知の追加)——のみで、
ForEach/TryCatch/Switch/Click/InvokeWorkflowFile/While/DoWhile/
AppendLine/ReadTextFile/InvokeCode/Break/Parallel/
ExcelApplicationScope/SendOutlookMail/SetToClipboard/Library呼び出しを
含む残り全ての構造はバイト単位で完全一致していた。**つまりModern Design
Experienceの切り替え・リロードは既存のXAML構造を一切書き換えていない**
——今回の方針逸脱は実害無しと確定した。(参考: VM側で`Get-FileHash`による
ハッシュ比較を先に試した際は`Main.xaml`の差分とは無関係に一見ズレた値が
出たが、これは実ファイル内容のdiffという直接的な検証方法でないと
原因切り分けが曖昧になりうる一例——以後も疑わしい時は実内容のdiffを
優先するとよい。)

## 32. VB.NET演算子9種を1つのAssign式にまとめて実機コンパイル確認——`Mod`/`\`/`^`/`And`/`AndAlso`/`Or`/`OrElse`/`Xor`/`Not`が全て`[...]`角括弧式としてそのまま直列化される

[design/uipath_vb_expression_mapping.md](uipath_vb_expression_mapping.md)で
「未確認(机上整理)」としていた演算子のうち、構文としてUiPathのVB式コンパイラが
受理するかどうかが最大の不確実性だった。そこで`xaml_probe`のMain.xaml先頭に
テスト用の`Assign`を追加し、次の複合式を`result`(既存の`x:Object`型変数)に
代入してみた:

```vb
CStr(1 Mod 3) & CStr(5 \ 2) & CStr(2 ^ 2) & CStr(True And False) &
CStr(True AndAlso False) & CStr(True Or False) & CStr(True OrElse False) &
CStr(True Xor False) & CStr(Not True)
```

保存した結果、Error Listは0件(エラー・警告・情報とも0)のまま正常に保存でき、
XAMLには次の通りそのまま直列化された(`&`のみXMLエンティティエスケープ、
VB側の記法自体への変換は一切無い):

```xml
<InArgument x:TypeArguments="x:Object">[CStr(1 Mod 3) &amp; CStr(5 \ 2) &amp;
CStr(2 ^ 2) &amp; CStr(True And False) &amp; CStr(True AndAlso False) &amp;
CStr(True Or False) &amp; CStr(True OrElse False) &amp; CStr(True Xor False) &amp;
CStr(Not True)]</InArgument>
```

これにより、VB式変換マッピング表の「未確認」演算子(`Mod`・`\`・`^`・`And`・
`AndAlso`・`Or`・`OrElse`・`Xor`・`Not`、および`&`連結・`CStr()`・`True`/
`False`リテラル)が、**UiPath Studio上で実際に構文として受理され、既存の
`[...]`角括弧省略記法のまま一切変換されずに直列化される**ことを確認できた
(詳細はマッピング表側に反映済み)。なお今回確認したのは「コンパイルが通り、
想定通りの生テキストとして直列化されるか」という構文・直列化レベルの話で
あり、`And`/`Or`(非短絡)と`AndAlso`/`OrElse`(短絡)の実行時意味論の違い
自体は公開のVB.NET言語仕様通りで変わらない(実行時トレースによる検証は
別途必要だが、変換ルールとしての信頼度は上がった)。

**UI操作上の小さな教訓**: `Assign`の`To`欄(変数名コンボボックス)は、
`pywinauto.keyboard.send_keys()`で素早く複数文字を続けて送ると文字が
欠落する(例: `content`→`cnnnnt`)——知見16で確認したIntelliSense絡みの
罠とは別に、このコンボボックス自体が高速入力に弱いらしい。対策として
(1) 1文字ずつ`pause`を長めに取って送る、または(2) 長い式はWindows
クリップボードに積んで`Ctrl+V`で貼り付ける、の2通りが有効だった
——特に(2)は今回の9演算子複合式のような長い入力で有効。

## 33. より新しいStudioバージョン(26.0.204-cloud)をサイドバイサイドで追加インストール——配布形態がSquirrel per-userからConnected Platform(マシン全体)方式へ刷新されていた

C#式言語・Coded Workflows・Object Repositoryの実機確認にはStudio 2021.4.4より
新しいバージョンが必要という結論が知見30-7・31・今後の調査候補で繰り返し出ていた
ため、同じ`pad2py-pad-host` VMに新バージョンを**既存の2021.4.4を残したまま**
追加インストールした。この過程自体がUiPathの配布アーキテクチャ刷新を実地で
確認する結果になったため、知見として記録する。

**配布形態の変化**: UiPathの公式ダウンロードページ経由で得られる
`download.uipath.com/UiPathStudioSetup.exe`という旧来の固定URLは、実際には
2021年5月付けでピン留めされた古いビルドを返すだけで、もはや「最新版への
固定リンク」としては機能していなかった(`Last-Modified`ヘッダで確認)。
現行のCommunity Editionは`UiPathStudioCommunity.msi`という単体の大型MSI
ではなく、**`UiPathPlatform.msi`という約11MBの小型「Connected Installer」**
を経由する2段階方式に変わっている:

1. `UiPathPlatform.msi`(MSI、要管理者権限)を実行すると、実際のペイロードは
   インストールされず、バックグラウンドサービス`UiPath.Connected.Updater.Service`
   (Squirrelベース、`C:\Program Files\UiPathPlatform\Updater\`に配置)だけが
   登録・起動される。
2. そのサービスが`UiPath.Connected.Installer.Ui.exe`(ウィンドウタイトル
   `UiPath Connected Platform`)という対話的GUIを自動的に開く。このGUIは
   Studio/Assistant・Delegate・Cartographer/Robot/Extensionsの4項目を
   チェックボックスで個別選択できる「製品選択+ライセンス同意+Install」の
   単一画面で、実際の数百MB規模のダウンロード・展開はここで初めて発生する
   (進捗は「Downloading NN%」のプログレスバーで0→100%まで約数分かけて進行)。
3. CLI版`UiPath.Connected.Installer.Cli.exe`も同梱されている(`install`/
   `uninstall`/`upgrade`サブコマンド、`--manifest`必須引数)が、manifest
   のスキーマが文書化されておらず自己流で組み立てるのはリスクが高いと判断し、
   今回はGUI版(`...Installer.Ui.exe`)のチェックボックス操作で進めた。

**インストール先の構造変化**: 旧バージョン(2021.4.4)は
`C:\Users\<user>\AppData\Local\UiPath\app-21.4.4\`というper-user Squirrel
レイアウトだったが、新バージョンは**`C:\Program Files\UiPathPlatform\Studio\
26.0.204-cloud.25540\`というマシン全体(Program Files)レイアウト**に変わって
いる。バージョン番号の表記も`21.4.4`のような単純な3つ組から
`26.0.204-cloud.25540`(年.月.ビルド-エディション.追加番号)という形式に
変わった。両者は完全に独立したディレクトリツリーなので、**サイドバイサイド
インストール自体は特別な配慮なしに成立する**——旧版の起動用ショートカット
(スタートメニューの`UiPath Studio.lnk`)は旧パスを指したままで更新されず、
新版はフルパスで直接起動する必要がある。

**実機で踏んだエラー——Studio/Robotバージョン不整合**: 新Studio
(`UiPath.Studio.exe`、新パス)を初回起動したところ、プロジェクト一覧も
何も出さずに即座にモーダルエラーが出た:

> The installed versions of Studio and Robot do not match. Please restart
> your machine and try again.

これは、同じ「Connected Platform」インストーラでRobotコンポーネントも
同時に更新対象になっていた(GUI上のチェックボックスでは明示的にチェックしたのは
Studioのみだったが、依存関係としてRobot等も併せて処理された形跡がある)ものの、
**旧バージョン(21.4.4)時代のRobot関連サービス(`UiPath.RobotJS.UserHost`等)が
起動中のまま残っていたため、新旧のRobotバイナリ/サービスが同一セッションに
混在し、Studio起動時の整合性チェックで検出・ブロックされた**という挙動と推定
される。エラーメッセージが明示的に「マシンの再起動」を要求している通り、
この手のバージョン不整合はOSレベルのサービス再起動(プロセスの入れ替え)でしか
解消できない設計になっているらしい——`msiserver`のような単体サービスの再起動
では足りない。

**VM運用上の制約でこの先は保留**: 再起動はVM上で同時に動いている他の作業
(PAD Designer側で開いていた`g1g2_test`ワークフロー等)に影響する「共有状態を
変更する操作」に該当するため、知見化はここで一旦止め、再起動の実施はユーザー
確認を経てから次のセッションで続行する方針とした(C#式言語・Coded Workflows・
Object Repositoryの実機確認はこの再起動後に持ち越し)。

**UI操作上の教訓(今後のRDP/VM管理作業全般に有効)**:
- clipwireのexecセッションは**UAC制限付き(非管理者)トークン**で動く。
  管理者権限が要る操作(MSIによるマシン全体インストール、`schtasks /RU SYSTEM`)
  は、対話的UAC確認ダイアログ(`consent.exe`)を要求するか、`Access is denied`
  で即座に失敗するかのいずれかになる。UACダイアログは**対話セッションが
  「接続中」状態でないと表示自体が起きない**(切断中セッションに対する昇格要求は
  ダイアログ無しで単に失敗する)。
- `consent.exe`/`msiexec`を強制終了(`Stop-Process -Force`)すると、Windows
  Installerの内部ロックが残り、次のインストール試行が`Error 1500`
  (「別のインストールが進行中」)で失敗することがある。正規の対処
  (`Restart-Service msiserver`)自体にも管理者権限が要る場合、同じ理由で失敗し、
  時間を置いて再試行するしかない。
- `mss`によるスクリーンショット取得(`BitBlt`)は、RDP接続/切断の前後で
  原因不明の失敗を起こすことがある(今回は接続中・切断後の両方で失敗した)。
  これに対する**画面キャプチャに依存しない代替手段**: `pywinauto.Desktop
  (backend="uia").windows()`+`.descendants()`でUI Automationツリーを直接
  走査し、`click_input()`(実際のマウス移動を要求し、アクティブデスクトップが
  無いと`RuntimeError`になる)の代わりに`toggle()`/`invoke()`(UI Automationの
  Toggle/Invokeパターンをデスクトップ状態に関係なく直接呼ぶ)でコントロールを
  操作する。この方式は今回、BitBltが機能しない状態でも安定して動作した
  ——スクリーンショットが取れない状況での自動化の標準手段として今後も使える。
- `mstsc.exe`にパスワードを渡すCLI引数は存在しない。
  `cmdkey /generic:TERMSRV/<host> /user:<user> /pass:<password>`で
  資格情報を事前登録しておくと、後続の`mstsc /v:<host>`がプロンプト無しで
  繋がる。

## 34. VM再起動で新Studioインストールが消失——Connected Platformの「ダウンロード完了」は実インストールと別物、かつRobotサービスは登録パス更新後も「再起動するまで旧プロセスのまま」

知見33の末尾で保留にした「Studio/Robotバージョン不一致→マシン再起動」を
実際に試した結果、Connected Platformインストーラの挙動についてさらに
いくつかの重要な事実が判明した。

**`gcloud compute instances reset`(ハード再起動)後、新Studioのインストールが
丸ごと消えていた**: 再起動前に`C:\Program Files\UiPathPlatform\Studio\
26.0.204-cloud.25540\UiPath.Studio.exe`として存在していたはずのファイルが、
再起動後には`Studio`サブディレクトリ自体が存在しない状態になっていた
(`Installer`・`Updater`サブディレクトリのみ残存)。原因は、
`UiPath.Connected.Updater.Service`がOS起動時に自動的に未完了インストールの
再処理を始め、`C:\ProgramData\UiPathConnected\Installer\Temp\Installer-<hash>\`
配下に製品ファイルを再ダウンロード・再展開していたが、このときのログ
(`UiPath.Connected.Installer.Ui.<date>.log`の`SendProductsInfoReady`イベント)
を見ると、全製品が`"IsInstalled":true`かつ`"InstallRequested":false`,
`"CanLaunch":false`という状態だった——つまり**「ダウンロード+展開が完了した
ことを示す進捗バーの`Install complete`表示」は、実際の配置(Program Filesへの
コピー・サービス登録等)が完了したことを意味しない**。明示的に「Install」
ボタンを押して`InstallRequested`をtrueにする操作をもう一度行わない限り、
最終的な配置は実行されず、しかもこの「ステージングだけ済んだ」状態は
再起動を跨いで保持されない(次回起動時にまた最初からステージングし直す)。

**インストーラGUIの直接起動は`CommandLine.NoVerbSelectedError`になる**:
`UiPath.Connected.Installer.Ui.exe`を引数無しで直接`Start-Process`すると、
サービス経由で呼ばれる際に渡されるはずの起動verb/コンテキストが欠けており
即座にエラーダイアログになる。正しい起動経路は、ブートストラップMSI
(`UiPathPlatform.msi`)を改めて実行すること——MSIがサービスに正しい
コンテキストで起動を指示し、そこから本来のGUIが開く。

**MSIを2回実行すると`Error 1500`で衝突する——しかもユーザー視点では
「Installing applicationが終わらない」ように見える**: 1回目のMSI実行で
実際には裏で`UiPath.Connected.Installer.Ui.exe`(製品選択画面)が起動して
ユーザー入力待ちの状態で生き続けていたが、**この画面はユーザーのRDP画面には
描画されていなかった**(知見33で触れたBitBlt/アクティブデスクトップ問題と
同系統の現象と思われる)。ユーザーはMSIブートストラップ自身の小さな
「Installing application...」ダイアログだけを見ており、それが進まないので
もう一度MSIを実行した結果、1回目のプロセスがまだ生きていることによる
`Error 1500`(「別のインストールが進行中」)に当たった。**対処は2回目を
キャンセルし、`pywinauto.Desktop(backend="uia").windows()`で既に存在する
1回目の`UiPath.Connected.Installer.Ui.exe`ウィンドウを探して直接UIA操作する
こと**(再実行ではなく、既存プロセスへの接続)。

**製品選択画面で`InstallStudio`をチェックすると`InstallRobot`チェックボックスが
自動的に`enabled=False`になる**: RobotはStudioの`HardDependencies`に
含まれているため、Studioを選ぶと自動的に同時インストール対象になり、
個別にトグルする必要も権限も無い(チェック状態は変更不可)。

**それでも「versions do not match」エラーは再発した——原因はサービスの
登録パスとメモリ上プロセスのギャップ**: 2回目は実際に最後まで
「Install」ボタンを押して完了させ、`C:\Program Files\UiPathPlatform\Studio\
26.0.204-cloud.25540\`と`...\Robot\26.0.204-cloud.25540\`の両方が実在する
ことを確認した。Windowsサービス`UiPath RobotJS Service`の登録情報
(`Get-CimInstance Win32_Service`の`PathName`)も新バイナリを指すよう
更新されていた。**しかし新Studioを起動すると依然として同一のモーダル
エラー(`Incompatible version found Robot: 21.4.4.0, Studio 26.0.204.0`)が
出た**。実行中プロセス`UiPath.RobotJS.ServiceHost`(PID確認済み)は旧
バイナリのままメモリに残っており、サービスレコードのパス更新だけでは
実行中プロセスは入れ替わらない。`Restart-Service`も非管理者トークンでは
`Cannot open ... service`で失敗するため、**エラーメッセージが要求する
「マシンの再起動」は文字通り必須で、サービス単体の再起動で代替することは
(このセッションの権限では)できない**。→ 2回目の`gcloud compute instances
reset`を実施し、再起動後の状態確認は次の知見に持ち越し。

**教訓のまとめ(再利用可能)**:
- Connected Platformの「ダウンロード/展開」完了と「実インストール
  (配置・サービス登録)」完了は別イベントであり、UIの進捗表示だけでは
  区別できない。`SendProductsInfoReady`イベントの`InstallRequested`/
  `CanLaunch`フィールドで確認するのが確実。
- ステージング済みだが未確定の状態は再起動で消える(再ステージングからやり直しになる)。
- 既に起動中の非表示ウィンドウに気づかずMSIを再実行すると`Error 1500`を
  誤って「初回の不具合」と誤認しやすい——**まずプロセス一覧で
  `UiPath.Connected.Installer.Ui`等が既に存在していないか確認するのが先**。
- Windowsサービスの「登録パス更新」と「実行中プロセスの入れ替え」は別物——
  サービスバイナリを差し替えても、OS再起動かサービス自体の再起動
  (admin権限が必要)のどちらかが無い限り、旧プロセスが動き続ける。

## 35. 2回のVM再起動を経ても新Robotバイナリへの切り替わりが発生せず——Studio/Robotバージョン不一致エラーはこのセッションの権限内では解決不能と判断

知見34で保留にした2回目の`gcloud compute instances reset`実施後も、新Studio
(26.0.204-cloud.25540)は全く同じ`The installed versions of Studio and Robot
do not match. Please restart your machine and try again.`エラーで起動不能
だった。この過程で以下を確認・反証した:

- `C:\Program Files\UiPathPlatform\Robot\26.0.204-cloud.25540\`配下に新Robot
  バイナリ(`UiPath.RobotJS.UserHost.exe`等)は実在し、再起動後も
  `UiPath.RobotJS.UserHost`プロセスは新パスから正常に起動していた。
  `Get-CimInstance Win32_Service`で見た`UiPath RobotJS Service`の登録
  `PathName`も新パスを指していた。**つまりファイル配置・サービス登録情報の
  面では新バージョンへの切り替えは完了している**。
- 一方、旧2021.4.4側のper-userプロセス`UiPath.Service.UserHost.exe`
  (`AppData\Local\UiPath\app-21.4.4\`)が、スケジュールタスク`UiPath RobotJS`
  (状態`Running`、ログオントリガーと思われる)によって自動的に再起動され続けて
  いることを発見した。このタスクを`Disable-ScheduledTask`で無効化しようと
  したが`Access is denied`(非管理者トークンでは不可)。
- 旧プロセスを`Stop-Process -Force`で止めた直後(タスクの再起動が間に合わない
  ほど短い間隔)に新Studioを起動しても、**依然として同一エラーが即座(起動後
  10秒未満)に発生**した。これは、エラーの原因が「旧User Hostプロセスが生きて
  いること」ではなく、**`UiPath.RobotJS.ServiceHost`サービス自体(SYSTEM権限で
  動作、非管理者トークンからはパス・コマンドラインの参照すら`Get-CimInstance
  Win32_Process`/`Get-Process`で空になり中身を検証できない)が、ファイル配置は
  新バージョンでもメモリ上では旧バージョンのまま動き続けている**可能性を
  強く示唆する。
- Studio側のログ(`2026-11-05_UiPath.Studio.log`)は再起動後も一貫して
  `Incompatible version found Robot: 21.4.4.0, Studio 26.0.204.0`と出力し、
  `21.4.4.0`という具体的な旧バージョン番号を報告し続けている
  (単なるプレースホルダ値ではなく実際に何らかの経路で旧バージョン情報を
  取得できている様子)。エラーダイアログの「Copy to Clipboard」でコピーした
  内容にはバージョン番号の詳細は含まれず、ログ以上の情報は得られなかった。
- 同じエラーダイアログの「OK」ボタンを押すとStudioプロセスは即座に終了する
  ——これは警告的なモーダルではなく**致命的な起動失敗ダイアログ**であり、
  閉じて別の画面に進むことはできない。

**結論**: `gcloud compute instances reset`によるハードリセットを2回実施しても
解消しなかったことから、この問題はOS再起動では直らない何らかの状態
(Squirrelの「現在のバージョン」解決ファイルの不整合、またはサービスの
実行中プロセスがハードリセットでは正しく再読み込みされない等)に起因する
可能性が高い。原因の特定・解消には管理者権限での`sc.exe query`/
サービスバイナリの直接検査、または画面を直接見ながらの対話的操作
(RDP接続中にユーザー自身が確認する)が必要であり、**このclipwireの非管理者
execセッションの権限・可視性では追加の自動化では解決できないと判断し、
この経路の調査はここで一旦終了する**。C#式言語・Coded Workflows・
Object Repositoryの実機確認は、別の解決手段(例: 旧2021.4.4を完全アン
インストールしてから新規インストールし直す、またはユーザーが対話的に
修復する)が取れるまで保留とする。

## 36. VB.NET式の残り未検証項目(IsNot/Nothing/三項If/CInt/CDbl/CBool/IsNothing/文字列補間/String.IsNullOrEmpty/クォートエスケープ)を実機コンパイル確認——クリップボード貼り付けがIntelliSense干渉を回避する確実な入力手段だと判明

新Studio側の調査が知見35で一旦行き詰まったため、旧Studio(2021.4.4、サイド
バイサイドインストールの影響を受けていない)で`xaml_probe`を使い、知見32の
時点で「公開VB.NET仕様に基づく机上整理」のまま残っていた項目——`IsNot`・
`Nothing`・三項演算子`If(cond, t, f)`・`CInt`/`CDbl`/`CBool`・`IsNothing`・
文字列補間`$"...{expr}..."`・`String.IsNullOrEmpty`・文字列リテラル内の
ダブルクォートエスケープ`""`——を実機コンパイル確認した
(`design/uipath_vb_expression_mapping.md`の「未確認」項目が実質ゼロになった)。

3つ目のAssignとして`CStr(String.IsNullOrEmpty("")) & "He said ""hi"" today"`
も追加し、Error List「No errors found」とXAMLの両方で確認:
```xml
<InArgument x:TypeArguments="x:Object">[CStr(String.IsNullOrEmpty("")) &amp; "He said ""hi"" today"]</InArgument>
```
`String.IsNullOrEmpty`は静的メソッド呼び出し構文のままVB式として問題なく
受理され、VB文字列リテラル内の`""`(ダブルクォート1個を表すエスケープ)も
XMLエスケープ(`&quot;`)と無関係にそのまま埋め込まれる——どちらも特別な
直列化処理を持たず、知見2以来の「`[...]`内は生のVB式テキストがそのまま
入る」という原則の延長で説明できる。

**確認方法**: 知見32と同じ「Assignの値欄に複合式を組んで保存→Error Listで
検証」の手法。1つ目のAssignで`CStr(If(result IsNot Nothing, "notnothing",
"isnothing")) & CStr(CInt("5")) & CStr(CDbl("2.5")) & CStr(CBool("True")) &
CStr(IsNothing(Nothing))`、2つ目のAssignで`$"value={result}-end"`を入力し、
いずれもError Listで「No errors found」を確認した上でXAMLを直接読み、
以下の通りあらゆる項目が**変換無しでそのまま`[...]`角括弧式内に直列化
される**ことを確認した(知見13の原則——`x:TypeArguments`が`x:Object`なら
角括弧形、という以前からの知見と整合):

```xml
<InArgument x:TypeArguments="x:Object">[CStr(If(result IsNot Nothing, "notnothing", "isnothing")) &amp; CStr(CInt("5")) &amp; CStr(CDbl("2.5")) &amp; CStr(CBool("True")) &amp; CStr(IsNothing(Nothing))]</InArgument>
...
<InArgument x:TypeArguments="x:Object">[$"value={result}-end"]</InArgument>
```

文字列補間`$"..."`の`{`/`}`もエスケープ不要でそのまま埋め込まれる
(VB式自体は`&amp;`以外XMLエスケープの対象にならない、知見2以来の一般則通り)。

**UI自動化上の重要な発見——VB式入力欄への文字入力は「1文字ずつsend_keys」
より「クリップボード貼り付け」の方が確実**: `uipath_ui_helpers.py`の
`set_vb_expression_field()`は1文字ずつ`send_keys()`する方式を採っているが、
今回`result IsNot Nothing`のように予約語(`IsNot`/`Nothing`)が連続する式を
この方式で打つと、**予約語の直後のスペースがIntelliSenseの割り込みで
脱落し**`resultIsNotNothing`という無意味な1トークンになってコンパイル
エラーになった。さらに`CStr`が`Cttr`に化けるなど、文字の欠落・誤変換も
発生した(知見2の脚注で既に指摘されていた同種の問題が、英単語が連続する式で
より頻発することを確認)。**対処として、Windowsクリップボードに完全な式
文字列をセットしてから`Ctrl+A`→`Delete`→`Ctrl+V`で貼り付ける方式に切り替えたところ、
一度も文字化けせず確実に入力できた**。`Set-Clipboard`を使う際はPowerShell側の
引用符ネストを避けるため、式文字列をbase64エンコードして
`[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('...'))`経由で
渡すのが安全(`$`で始まる文字列補間式はPowerShellの変数展開と衝突するため
特に有効)。**今後VB式入力欄にテキストを設定する処理は、1文字ずつの
`send_keys`ではなくクリップボード貼り付けを標準手順とすべき**——
`set_vb_expression_field()`のdocstringで「今後試す価値あり」とされていた
代替案が、今回実証的に優位と判明した。

**副次的な発見**: 新Studio側の調査(知見33〜35)でStudio/Robotプロセスを
何度も強制終了した影響で、旧Studio(2021.4.4)もサインアウト状態になって
いた。認証情報の入力はユーザーに依頼し、サインイン後に旧Studioで
`xaml_probe`を問題なく開けることを確認した——サイドバイサイドインストール
したStudio同士でも、Assistant/Robotのプロセスレベルでは認証状態を共有して
いるらしく、一方の強制終了がもう一方のサインイン状態に影響しうる点は
今後の作業で注意が必要。

## 37. セレクタ(Selector)の意味論を公式ドキュメントで調査——Classic/Dynamic/Anchor Baseは把握できたが、ModernのFuzzy/Strict selectorの実XAML形は未確認と判明

[design/uipath_transpiler_roadmap.md](uipath_transpiler_roadmap.md)で
「知見1〜36のどこにも調査が無い最大の未解決問題」と特定したセレクタの
意味論を、UiPath公式ドキュメント(docs.uipath.com)経由で調査した
(VM不使用、Web検索のみ)。

**基本構造**: セレクタは`<node_1/><node_2/>...<node_N/>`というXMLフラグメント
の連鎖で、**最後のノードがターゲット要素、それ以前は親**(先頭が「ルート」=
アプリのトップウィンドウ)。タグ名(`WND`/`CTRL`/`UIA`/`HTML`等)がUIシステム
種別を表す。`RDP`はWNDと同じ属性セットを持つリモート自動化用の別タグ。
ただし**各タグの「役割」自体(ウィンドウ階層とどう対応するか)は公式
ドキュメントに説明文が無く、属性表が個別に列挙されているのみ**。

**属性語彙(マッチ可否込み)**:
- `WND`: マッチ可能—`app`/`cls`/`title`/`aaname`/`ctrlname`(WinForms)/
  `ctrlid`(WinForms)/`aastate`/`curlApplet`。マッチ不可—`idx`/`tid`/
  `pid`/`isremoteapp`。SAP専用属性多数(`sapClient`等)
- `CTRL`: マッチ可能—`role`/`name`/`automationid`/`labeledby`/`aastate`/
  `virtualname`/`text`/`rowName`。マッチ不可—`idx`
- `WEBCTRL`: `tag`/`idx`/`aaname`/`name`/`id`/`parentid`/`class`/
  `css-selector`/`innertext`/`title`(新しいバージョンは
  `visibleinnertext`/`isleaf`も追加)

**ワイルドカード/fuzzy matching**: 構文自体は公式ドキュメントに明記が薄く、
2021.10版に`?`(1文字置換)と`*?`(1文字以上一致)の言及があるのみ。素の
`*`(0文字以上)は非公式(フォーラム)情報にしか出てこない。`idx`はワイルド
カード非対応と明記されているが、フォーラムには`idx='*'`が動く/動かないの
矛盾する報告があり、バージョン依存の可能性——実機検証が必要。

**Dynamic Selector**: 構文は`{{Value}}`(**`[変数]`角括弧式ではない**、
VB式の文字列補間`$"..."`とも別構文)。例:
`<ctrl name='{{MenuOption}}' role='menu item' />`。Studio上ではプロパティ
値を右クリック→変数化、という手順で特定属性値を変数に置き換える。

**Computer Vision (CV) フォールバック**: `CV Screen Scope`配下のCV
アクティビティは**セレクタ無しでも**ボタン/テキスト入力/チェックボックス
等をニューラルネット検出で特定できる——つまりCVはセレクタ構文の拡張では
なく、セレクタが効かない場合の完全な別経路。`Target.Selector`自体は通常の
XML形式だが、CVスコープという別枠の中で動く。

**Modern活動のFuzzy/Strict selector——未解決**: Modern UI Automation
アクティビティ(`Set Selected Item`等)の`Target`プロパティは単純な
`Selector`文字列ではなく、`Fuzzy selector`(マッチングパラメータ)・
`SearchSteps`(識別手法選択)・`Strict selector`(indicateした要素から
生成されたセレクタ)という複合プロパティになっている。これはCVとも別系統の
「Fuzzy vs Strict」という二段構えの仕組みで、**Classicの`Selector`属性
1本とはXAML上の直列化形が構造的に異なる可能性が高いが、実際の要素名・
属性名は公式ドキュメントに出てこず未確認**。知見31で有効化条件を確認した
Object Repository/Modern Design Experienceと合わせて、**旧Studio
(2021.4.4)でもModern活動を1つ置いてXAMLを見れば確認できる可能性がある**
——新Studio問題(知見33〜35)の解消を待たずに着手できるかもしれない。

**Anchor Base**: 近傍要素を基準にターゲットを特定するコンテナ型アクティビ
ティ。`idx`に頼れない/信頼できるセレクタが無い場合の推奨手段。
`AnchorPosition`は`Auto`(左/右/下を探索、同率なら右→左→下の順)/
`Left`/`Top`/`Right`/`Bottom`/`OnTop`。「Relative Element」との使い分けは
未調査(ページ未取得)。

**pywinautoマッピングへの示唆(確定ではなく方向性)**:
- `CTRL`の`automationid`→pywinautoの`auto_id`、`name`→`title`、
  `role`→`control_type`に素直に対応できそう
- `WND`の`cls`→`class_name`、`title`→`title`に対応できそう
- `idx`(マッチ不可=識別専用の順序番号)は`found_index`相当だが、挙動が
  不安定な可能性があるため変換時は警告付きTODOが安全
- `{{Value}}`動的セレクタは「属性値がf-string的に変数展開される」パターン
  として扱えばよさそう
- **CV・Anchor Base・ModernのFuzzy/Strict selectorの3つは、いずれも
  「単純なSelector属性1本」では表現できない別物**——ロードマップPhase 4の
  選択肢(a)「素朴マッピング」で素直に扱えるのはClassic Selectorのみで、
  残り3つはv1スコープでは「検出して`# TODO`」止まりにするのが現実的、
  という方向性を支持する材料になった

## 38. セレクタ実機検証——`role`→`control_type`の素朴マッピングは実機で`KeyError`になると確定(知見37の「素のまま変換」方針への修正)

知見37末尾の「pywinautoマッピングへの示唆」(方向性、未確定)のうち、
`CTRL`の`role`→`control_type`をpad2py-pad-host VM上の実機Notepadで
検証した。知見9の実例セレクタ(`ui:Click`)

```
<wnd app='notepad.exe' cls='Notepad' title='Untitled - Notepad' />
<wnd aaname='Horizontal' cls='Edit' />
<ctrl name='Text Editor' role='editable text' />
```

を素直にマッピングすると`uipath_selector`はこう生成していた:

```python
Desktop(backend="uia").window(class_name='Notepad', title='Untitled - Notepad') \
  .child_window(class_name='Edit') \
  .child_window(title='Text Editor', control_type='editable text')
```

これを実際に起動したNotepadに対して実行すると
**`KeyError: 'editable text'`で即クラッシュする**(pywinautoは`control_type`を
UIAの`ControlType`列挙値に対して検証しており、未知の文字列は単なる
不一致ではなく例外になる)。実機のUIAツリーをダンプして確認した実際の
`control_type`は`'Edit'`で、UiPathの`role`値`'editable text'`とは
文字列として一致しない——知見37が「語彙が一致する保証は無い」と警告していた
内容を実際に裏付け、かつ「単に見つからない」より悪い「ハードクラッシュ」
という形で確認された。

一方、同じ実機検証で以下は**確認済み(正しい)**と確定した:
- `cls`→`class_name`: `class_name='Edit'`は実機のUIAツリー上で一意にマッチする
- `name`→`title`: マッチした要素の実`name`属性値(`'Text Editor'`)は
  セレクタの`name='Text Editor'`と完全一致する
- `role`を含めず(`control_type`を指定せず)`class_name='Edit'`
  (+ あれば`title='Text Editor'`)だけで検索すると、実際に対象要素を
  一意に特定できる

この結果を受け、`dump_daemon/uipath_selector`は`role`→`control_type`の
マッピングを削除し、`role`を意図的に未対応(unmapped、警告コメント付きで
生成コードに残すのみ)へ変更した。1件のみの実機データ(n=1、Notepadの
`Edit`コントロール)からUiPathの`role`語彙全体の対応表を作る根拠は無い
(でっち上げになる)ため、「`role`は安全側で使わない」という保守的な結論に
留め、将来別のUIAコントロール種別で実例が増えた時点で再検討する。

**知見37の「WND/CTRLの第2層(`aaname='Horizontal' cls='Edit'`)が
Classic Selectorの中間階層として独立したノードになる」という構造について**:
実機のUIAツリーでは、Notepadの`Edit`コントロール(`Text Editor`)は
トップレベルウィンドウの**直接の子**であり、`aaname='Horizontal'`に
対応する別階層のUIA要素は見当たらなかった(水平スクロールバーかそれに
近い内部的なMSAA/Win32の層を指している可能性があるが未確認)。実際には
中間の`<wnd cls='Edit'>`ノードがマッピングする`class_name='Edit'`が
最終ターゲット自身と同じ値になり、`pywinauto`の`child_window()`が
部分木全体を探索するため、中間ノードの時点で既に最終要素まで一意に
到達してしまう——Classic Selectorの各ノードが必ずしもUIAツリーの
隣接する1階層ずつに対応するとは限らないことを示す実例だが、今回の
1ケースだけでは一般化できないため、構造上の対応ルール自体は変更せず
今後の検証課題として残す。

## 39. Modern UI Automation活動の実XAML形を確定——`uix:`名前空間、`NApplicationCard`/`NClick`、`FullSelectorArgument`/`FuzzySelectorArgument`/`ScopeSelectorArgument`、`SearchSteps="Selector, FuzzySelector, Image"`で決着

知見37最大の未解決点だった「ModernのFuzzy selector/Strict selectorが実際に
どうXAML直列化されるか」を、pad2py-pad-host VM上の`xaml_probe`プロジェクトで
Modern Design Experienceを有効化した上で、実際にModern版`Click`活動を配置し
実機Notepadへターゲット指定して確定した(手順は本節末尾、実験後は
`xaml_probe`から当該活動を削除して元の状態に復元済み——知見31追記の
「検証用の変更は汚さず戻す」方針を今回は徹底した)。

**最初の壁**: Modern版`Click`は単独では配置できない。Activitiesパネルから
`Click`(`Available > UI Automation > Application`、Classic版と名前も
アイコンも同一で区別不可)を直接キャンバスに置くと
「The current activity must be added inside a Use Application/Browser
activity.」という即時エラーダイアログが出る——Modern活動は必ず
`Use Application/Browser`コンテナ配下に置く必要がある(Classic版`ui:Click`が
単独のトップレベル活動として存在できたのとは対照的な制約)。

**実際の直列化形**(`Use Application/Browser`→`Indicate application to
automate`でNotepadを指定→内側の`Do`に`Click`を追加→
`Indicate target on screen`で実際にNotepadのテキスト編集領域をクリック→
Confirm→保存、という完全な実機操作で確認):

```xml
<Activity ... xmlns:uix="http://schemas.uipath.com/workflow/activities/uix" ...>
  ...
  <uix:NApplicationCard AttachMode="ByInstance" DisplayName="Use Application: Untitled - Notepad" Version="V1">
    <uix:NApplicationCard.Body>
      <ActivityAction x:TypeArguments="x:Object">
        <ActivityAction.Argument>
          <DelegateInArgument x:TypeArguments="x:Object" Name="WSSessionData" />
        </ActivityAction.Argument>
        <Sequence DisplayName="Do">
          <uix:NClick ClickType="Single" DisplayName="Click 'editable text'" KeyModifiers="None" MouseButton="Left">
            <uix:NClick.Target>
              <uix:TargetAnchorable
                ElementType="InputBox"
                FriendlyName="'editable text'"
                FullSelectorArgument="&lt;wnd aaname='Horizontal' cls='Edit' /&gt;&lt;ctrl name='Text Editor' role='editable text' /&gt;"
                FuzzySelectorArgument="&lt;wnd aaname='Horizontal' cls='Edit' /&gt;&lt;ctrl name='Text Editor' role='editable text' automationid='' /&gt;"
                ScopeSelectorArgument="&lt;wnd app='notepad.exe' cls='Notepad' title='Untitled - Notepad' /&gt;"
                SearchSteps="Selector, FuzzySelector, Image"
                ImageBase64="..." InformativeScreenshot="....png" DesignTimeRectangle="..." />
            </uix:NClick.Target>
          </uix:NClick>
        </Sequence>
      </ActivityAction>
    </uix:NApplicationCard.Body>
  </uix:NApplicationCard>
  ...
```

**確定した知見**:

1. **完全に別の名前空間・活動クラス体系**。Modern活動はClassicの`ui:`
   (`http://schemas.uipath.com/workflow/activities`)ではなく新しい`uix:`
   (`http://schemas.uipath.com/workflow/activities/uix`)名前空間を使う。
   `Use Application/Browser`→`uix:NApplicationCard`、`Click`→`uix:NClick`
   ——タグ名も全く異なり、Classic/Modernは design-time 上の見た目だけでなく
   **実行時の型そのものが別物**だと確定した。
2. **`Use Application/Browser`は`ForEach`/`ExcelApplicationScope`と同じ
   `ActivityAction`+`DelegateInArgument`パターン**(知見22の構造が
   ここでも再利用されている)。delegate引数名`WSSessionData`(恐らく
   Window/Web Session Data)が子活動へウィンドウ/ブラウザのセッション情報を
   暗黙に伝播する役割と推測される(detail未検証)。
3. **セレクタが「スコープ」と「ターゲット」の2層に明確に分離される**。
   知見9・知見37で「1本のフラットなSelector文字列」として扱っていたものが、
   Modernでは`Use Application/Browser`側の`ScopeSelectorArgument`
   (ウィンドウ/アプリ単位、今回の例では`<wnd app='notepad.exe' .../>`)と、
   個々の活動の`Target`側の`FullSelectorArgument`(要素単位、ウィンドウより
   下の階層、今回の例では`<wnd aaname='Horizontal' .../><ctrl .../>`)に
   分割され、実行時にこの2つを連結して初めてClassicの1本セレクタと
   等価になる構造だと判明した。
4. **「Fuzzy selector」「Strict selector」という知見37のドキュメント上の
   呼び名は、実XAMLでは`FuzzySelectorArgument`/`FullSelectorArgument`
   という属性名に対応する**——「Strict」=「Full」。今回の実例では両者は
   ほぼ同じ内容(Fuzzy側だけ`automationid=''`が1つ追加)だったが、これは
   対象が単純なネイティブWin32コントロールで曖昧さが少なかったためと
   推測され、一般にFuzzy側はより緩い(属性を間引く・部分一致にする等の)
   マッチングになるはずという知見37の推測の方向性自体は否定されない。
5. **`SearchSteps="Selector, FuzzySelector, Image"`属性が実行時のフォール
   バック順序を文字通り宣言している**——厳密な`Selector`(=Full)が
   一致しなければ`FuzzySelector`、それも失敗すれば埋め込み画像
   (`ImageBase64`)によるイメージマッチングへ段階的にフォールバックする
   設計だと、ドキュメントの推測ではなく実際のシリアライズされた属性値から
   直接確認できた。
6. **`ClickType`/`MouseButton`の値語彙がClassicと異なる**:
   Classic(`ui:Click`)は`ClickType="CLICK_SINGLE"`・
   `MouseButton="BTN_LEFT"`という列挙コード風の値を使うが、Modern
   (`uix:NClick`)は`ClickType="Single"`・`MouseButton="Left"`という
   そのままの英単語を使う——属性名が同じでも値の語彙は活動バージョンごとに
   異なるため、Modern対応のcodegenを書く場合はClassic用の値対応表を
   そのまま流用できない。
7. **デザイン時メタデータが同じ`uix:TargetAnchorable`要素に同居する**:
   `ElementType`(`"InputBox"`という意味論的な分類、生のUIA ControlTypeとは
   別物)・`FriendlyName`・`DesignTimeRectangle`(キャプチャ時の画面座標)・
   `ImageBase64`(実際の要素のスクリーンショット埋め込み)・
   `InformativeScreenshot`(スクリーンショットファイル名参照)。
   セレクタ文字列だけでなく、実行時フォールバックに必要な画像データまで
   同じXAMLファイル内に直接埋め込まれる(`.screenshots/`ディレクトリ等の
   外部ファイル参照ではなく、Base64インライン)。

**v1 codegenへの示唆**(即座の実装は不要、記録のみ): `uipath_dsl`/
`uipath_codegen`がModern活動に対応する場合、`uix:`名前空間のタグを
別ディスパッチ系統として扱う必要があり(Classicの`ui:Click`用パーサーの
単純な拡張では済まない)、セレクタ解決も「スコープ+ターゲットの連結」
という新しい合成ロジックが要る。ロードマップPhase 1の決定通りv1スコープは
Classicのみとし、本知見は「Modern対応を将来やる場合の設計の出発点」として
記録するに留める。

## 40. `Switch`のDefaultアームの実XAML形を確定——`x:Key`付き辞書エントリ(知見21)とは別の`<Switch.Default>`プロパティ要素、パーサーの無言データ消失バグを発見・修正

design/uipath_transpiler_roadmap.mdの「既知の簡略化」に残っていた
「`Switch`のdefaultアームの実XAML形は未確認」を、pad2py-pad-host VM上の
`xaml_probe`で実際に確認した(知見21で確認済みのcase `1`のSwitchに、
「Default」行の「Add an activity」経由で`Assign`(`content = "defaultcase"`)
をドラッグして追加)。結果:

```xml
<Switch x:TypeArguments="x:Int32" DisplayName="Switch" Expression="[result]">
  <Switch.Default>
    <Assign>
      <Assign.To>
        <OutArgument x:TypeArguments="x:String">[content]</OutArgument>
      </Assign.To>
      <Assign.Value>
        <InArgument x:TypeArguments="x:String">defaultcase</InArgument>
      </Assign.Value>
    </Assign>
  </Switch.Default>
  <Assign x:Key="1"> ... </Assign>
</Switch>
```

**`Default`は`x:Key`付き辞書エントリ(知見21の`Cases`、
`IDictionary<TKey, Activity>`)とは全く別の、.NETの`Switch<T>.Default`
という独立したプロパティで、`<Switch.Default>`というプロパティ要素
(ドット区切り、知見1で確立した命名規則通り)として直列化される**。
実機確認前は「Defaultも何らかの特別な`x:Key`を持つ辞書エントリだろう」
という誤った仮定で`uipath_dsl.xaml_tree._parse_switch`を書いており、
`<Switch.Default>`は`_activity_children()`(プロパティ要素を除外する
ヘルパー)によって**完全に無言で読み捨てられていた**——Defaultアームを
持つ実際のワークフローを変換すると、でっち上げでも例外でもなく
「Defaultの中身がそのまま消える」という、プロジェクトの「データを失わない」
方針に反する静かなバグだった(Outlineパネル上は`Switch > Case: 1`と
`Default`が兄弟ノードとして別々に表示されることでも構造の違いが伺えた)。

`_parse_switch`を修正し、`<Switch.Default>`プロパティ要素を先に探して
その直下の活動を`SwitchArm(key=None, ...)`として追加するようにした
(IR側の`SwitchArm.key=None`=defaultという表現自体は既に正しかった——
`uipath_codegen`側のDefault→`else:`変換ロジックも元々問題無し、バグは
パース側のみ)。実機未確認だった`SwitchArm`のdocstringも訂正。
実験後は`xaml_probe`から追加したDefaultアームを削除し元の状態へ復元
(知見31の方針通り、diffで無害化を確認済み)。
`tests/test_uipath_dsl.py`に合成XMLでの検証を1件追加、全611件通過。

## 41. `And`/`Or`/`Xor`の相対優先順位が公式VB.NET仕様と逆だった`uipath_expr`の文法バグを発見・修正(VM不使用、公式ドキュメントで確定)

`dump_daemon/uipath_expr/`のLark文法は、`or_expr`(最も外側=緩い)が
`xor_expr`を内包する構造になっていたが、Microsoft Learn「Operator
Precedence - Visual Basic」(現行版)のLogical and Bitwise Operators節は
高い順に`Not` > `And`/`AndAlso` > `Or`/`OrElse` > `Xor`(`Xor`が最も緩い)と
明記しており、実装は`Or`と`Xor`の相対順が逆だった。モジュールdocstring
自体は正しい意図(`And` > `Or` > `Xor`)を記していたのに、文法のネスト構造が
それと矛盾していた——`And`/`Or`/`Xor`を括弧無しで混在させる実機データが
知見32・36のいずれにも無かったため長らく未検出だった。`xor_expr`を最も
外側に、`or_expr`をその内側に、`and_expr`を一番内側にネストし直して修正、
`tests/test_uipath_expr.py`に`a And b Or c Xor d`が公式仕様通り
`((a And b) Or c) Xor d`になることを確認する回帰テストを追加した。

## 42. `Mod`/`\`(整数除算)を単純にPythonの`%`/`//`へ変換すると符号が異なるオペランドで値そのものが食い違うと確定(VM不使用、公式ドキュメントで確定)

知見41の調査の延長で、`Mod`/`\`の変換式自体(`uipath_vb_expression_mapping.md`
が「同上(確認済み)」として`%`/`//`への単純変換を記載していた箇所)を
Microsoft Learn「Mod Operator」「\ Operator」の公式ドキュメントと照合した
ところ、より重大な問題が見つかった——構文の優先順位ではなく**実行時に
返す値そのものが食い違う**ケースがあると判明した:

- VBの`\`(整数除算)は**ゼロ方向への切り捨て**(truncation)。公式例
  `67 \ -3`は`-22`。Pythonの`//`は**負方向への床除算**(floor)で、
  同じ`67 // -3`は`-23`——オペランドの符号が異なる場合に異なる値になる。
- VBの`Mod`は公式の変換式`a - (b * Fix(a / b))`どおり**余りの符号が被除数に
  従う**。公式例`-10 Mod 3`は`-1`。Pythonの`%`は**余りの符号が除数に従う**
  床除算の余りで、同じ`-7 % 3`は`2`——同じく符号が異なる場合に食い違う。

両者ともオペランドが同符号の場合は`%`/`//`と一致するため、知見32・36の
実機確認(いずれも正の数同士、`1 Mod 3`・`5 \ 2`)ではこの食い違いが
顕在化せず見過ごされていた。`dump_daemon/uipath_codegen/render.py`を
修正し、`\`→`int(a / b)`、`Mod`→`a - (b * int(a / b))`
(Pythonの`int()`もゼロ方向への切り捨てで、VBの`Fix()`と一致)という
VBの公式変換式をそのまま再現する形に変更した。
`tests/test_uipath_codegen.py`の
`test_mod_and_intdiv_match_vb_sign_semantics_not_python_floor_semantics`
で、両演算子の公式ドキュメント記載例をそのまま生成Pythonコードへ変換し
`exec()`して実際の値が一致することまで確認した(静的なXAML確認やASTの
形だけでなく、実行時の値そのものを検証した初めてのケース)。

## 43. `CInt`/`CBool`も知見42と同じ系統の値の食い違いがあると確定(VM不使用、公式ドキュメント・ランタイム仕様で確定)

知見42(`Mod`/`\`)の調査を「他にも似たような食い違いが無いか」という観点で
`CInt`/`CBool`にも広げたところ、どちらも確認済みテーブルに「丸め方向の
違いに注意」という既知の注記こそあったが、実装自体は直していなかった
(ドキュメントに書いただけで対応が止まっていた既知のギャップ)ことと、
さらに`CBool`には記載すら無かった別の食い違いがあることが判明した:

- **`CInt`は切り捨てではなく銀行丸め(round-half-to-even)**。Microsoft
  Learn「Type Conversion Functions」: `CInt`/`CLng`等は小数部を**最も近い
  整数に丸める**、ちょうど中間(`.5`)の場合は**最も近い偶数**に丸める
  (`0.5`→`0`、`1.5`→`2`、`2.5`→`2`)。単純にPythonの`int()`(ゼロ方向への
  切り捨て)へ変換すると`int(1.5)`が`1`になり食い違う。Pythonの`round()`は
  単一引数では既定でround-half-to-evenのため、`round(float(x))`が
  VBの`CInt`と一致すると確認した(`round(0.5)==0`・`round(1.5)==2`・
  `round(2.5)==2`、公式ドキュメントの例と直接突き合わせ済み)。
- **`CBool(文字列)`はPythonの`bool(文字列)`と意味論が異なる**。VBの
  `CBool`は文字列引数を`"True"`/`"False"`(大文字小文字区別無し)と
  認識するか、さもなくば数値として評価して非ゼロかどうかで判定する
  (それ以外は実行時型不一致例外)。Pythonの`bool(文字列)`は**空文字列
  以外は常に`True`**になる——`bool("False")`は`True`、`bool("0")`も
  `True`になり、どちらもVBの意図(`False`)と正反対になる。知見32・36の
  実機確認例は`CBool("True")`のみで、たまたまPythonの`bool()`と結果が
  一致してしまい(非空文字列→`True`)見過ごされていた。

`dump_daemon/uipath_codegen/render.py`を修正し、`CInt`は常に
`round(float(x))`、`CBool`は引数が文字列リテラルの場合のみコード生成時に
実際の変換結果(`True`/`False`)を確定させて埋め込むようにした
(リテラル以外は実行時の型が不明なため`bool(x)`のまま、既知の限界として
docstringに明記)。文字列リテラルが`"True"`/`"False"`でも数値でも無い場合
(例: `CBool("abc")`)は、VBが実行時に型不一致例外を起こすのと同様、
でっち上げた結果を埋め込まず`NotImplementedError`→`# TODO`に倒す。

`tests/test_uipath_codegen.py`に回帰テストを追加し、公式ドキュメント・
ランタイム仕様の具体例をそのまま生成Pythonコードへ変換して`exec()`し、
実行時の値が一致することまで確認した。

## 44. VB.NET演算子の全系統点検(知見42・43パターンの総点検)——`^`と`Not`の2点は公式ドキュメントだけでは確定できず未解決のまま残る

知見42(`Mod`/`\`)・知見43(`CInt`/`CBool`)で「公式ドキュメントと照合すると
値が食い違う」パターンが2件立て続けに見つかったことを受け、ユーザーからの
指示で`uipath_codegen`が扱う全ての演算子・型変換関数をこの観点で
系統的に洗い直した。結果:

- **比較演算子(`=`/`<>`/`<`/`>`/`<=`/`>=`)**: 数値比較はVB/Python間で
  差が無い。文字列比較(`Option Compare Binary`/`Text`の切り替え)は
  理論上は差が出うるが、UiPath側のXAML/project.jsonにこの設定が露出する
  実例を一度も見ていない(VB6/VBAのモジュールレベル設定であり、
  UiPathのワークフロー単位の式には関係しない可能性が高い)——実例が
  無い以上、現状の単純比較のままで問題無いと判断。
- **`Is`/`IsNot`・`IsNothing`・`String.IsNullOrEmpty`・三項`If`・
  `CStr`/`CDbl`**: 再点検したが食い違いの根拠は見つからず、現状の変換で
  問題無いと確認した。
- **`^`(累乗)**: VBは常にDouble型で計算する(Microsoft Learn「^
  Operator」)。負の底に非整数の指数を与えた場合の挙動(例外か`NaN`か)は
  公式ドキュメントで確認できなかった——Pythonの`**`は同じ入力に複素数を
  返すため、もしVBが例外/NaNを返すなら誤変換になりうるが、確定できない
  ため修正は見送り、既知のリスクとして`render.py`とdesign/
  uipath_vb_expression_mapping.mdの両方に明記した。
- **`Not`**: `And`/`Or`/`Xor`と同じ型依存の二重性質(Boolean→論理否定、
  Integer→ビット反転)を持つが、`&`/`|`/`^`と違いBoolean/Integer両方に
  正しく働く単一のPython演算子が無い(`~True`は`-2`)。知見32・36の
  実機確認例は`Not True`(Boolean)のみでIntegerオペランドの実例が無い
  ため、修正は見送り既知のリスクとして明記した。

**この知見で確定したこと**: 知見42・43の2件は実在するバグとして修正済み。
`^`/`Not`の2件は公式ドキュメントの記載が不十分で白黒つけられない
——これ以上の確定には実機(VM)での`^`/`Not`の実挙動確認が必要
(design/uipath_transpiler_roadmap.mdの「次にやること」に追加)。
それ以外の演算子・関数は全て再点検済みで新たな問題は見つからなかった。

## 45. `^`/`Not`の残る2点を実機(Sub1.xaml、Debug File)で検証——両方とも実在のバグと確定し修正した

知見44で公式ドキュメントだけでは白黒つけられず未解決のまま残った2点
(`^`の負の底+非整数指数、`Not`のIntegerオペランド)について、ユーザーの
指示で実機検証を行った。

**検証方法**: `design/evidence/uipath_xaml_probe/Sub1.xaml`(知見38などで
使っている、Main.xamlから隔離した最小フィクスチャ)を一時的に使い、
VM(`pad2py-pad-host`)上のUiPath Studioで以下を実施——

1. Sub1.xamlを開き、クリップボード貼り付け(知見のクリップボード手法)で
   `Assign`+`AppendLine`のペアを2組追加: `CStr((-8.0) ^ 0.5)`の結果と
   `CStr(Not 5)`の結果をそれぞれテキストファイルへ書き出す式。
2. StudioのDebug File(Designタブのリボンボタン)でSub1.xamlを直接実行
   ——Main.xamlの他のアクティビティ(副作用やダイアログを持つもの)を
   経由せず、Sub1単体だけが実行されることを確認済み。
3. 出力されたテキストファイルをclipwire execで読み取り。
4. 検証用に追加した4つのアクティビティを1つずつ削除(固定座標のループでは
   なく、都度スクリーンショットで次の削除対象の座標を確認しながら個別に
   削除——`AppendLine`カードは`Assign`より縦に大きく、削除ごとに後続の
   位置がずれるため固定座標の決め打ちは危険と判断して避けた)。
5. 削除後、diffで`Sub1.xaml`のワークフロー本体が元のコミット済み
   フィクスチャと完全に一致することを確認(HintSize等、今回の作業とは
   無関係な既存の差異のみ残存)。
6. 一時出力ファイル2つをVM上から削除し、`Test-Path`で消失を確認。

**確定した結果**:

- `(-8.0) ^ 0.5`(負の底+非整数の指数)→ `NaN`。知見44で懸念していた
  「例外」ではなく「NaN」だった。Pythonの`**`は同じ入力に複素数
  (`1.7320508075688772e-16+2.8284271247461903j`相当)を返すため、単純な
  `**`変換のままでは誤った結果になる——実在するバグと確定。
- `Not 5`(Integer)→ `-6`。知見44で懸念していた通り、ビット反転
  (2の補数)——Pythonの`~5`と一致、`not 5`(=`False`)とは全く異なる。
  実在するバグと確定。

**修正内容**(`dump_daemon/uipath_codegen/render.py`):

- `^`: 負の底かつ指数が整数でない場合のみ`float('nan')`に分岐し、
  それ以外は従来通り`**`で計算する式に変更。
  ```python
  f"(float('nan') if (({left}) < 0 and ({right}) != int({right})) "
  f"else (({left}) ** ({right})))"
  ```
- `Not`: 実行時にoperandの型を判定し、`bool`なら論理否定、それ以外
  (Integer等)ならビット反転するラムダ式に変更(式を二重評価しないよう
  一度だけ評価する)。
  ```python
  f"(lambda _x: (not _x) if isinstance(_x, bool) else ~_x)({operand})"
  ```

`tests/test_uipath_codegen.py`に`test_pow_matches_vb_nan_on_negative_base_with_fractional_exponent`
と`test_not_matches_vb_bitwise_complement_on_integer_not_just_boolean_negation`を追加
(`render_expr()`の出力を直接`eval()`して値を確認——`CStr`/`print`経由の
文字列比較はしない。`CStr(Double.NaN)`はVBで`"NaN"`、Pythonの
`str(float('nan'))`は`"nan"`になるという、この演算子の正しさとは別論点の
casing差異を誤って拾わないため)。

**この知見で確定したこと**: 知見44で未解決のまま残っていた2点は両方とも
実在するバグであり、実機確認済みの値(`NaN`/`-6`)に基づいて修正・
テスト済み。これで知見42〜45の一連の「VB.NET演算子の値の食い違い」
系統点検は完全に完了した。

## 46. `CStr(Double)`の書式がVBとPythonで食い違うと確定——知見45の`^`修正で残した軽微な既知課題を解消(VM不使用、公式ドキュメントで確定)

知見45で`^`修正時に「VBの`^`は常にDouble型で計算されるため、`CStr()`等での
文字列化の見た目が変わりうる(軽微、未対応)」と残していた課題を、公式
ドキュメントに基づき調査・修正した。

**調査結果**: `CStr`はDouble値に対し`ToString()`の既定書式("G"、
mscorlib/Legacyターゲットでは丸め桁数15、知見30-6参照)に従う
(Microsoft Learn「Return Values for the CStr Function」「標準の数値
書式指定文字列」)。G書式は**小数点以下の末尾ゼロを省略し、不要なら
小数点自体も付けない**と明記されている——このため`CStr(4.0)`は
`"4"`になり、`"4.0"`にはならない。Pythonの`str(float)`は整数値でも
常に`.0`を残すため、確実に食い違う(例外や稀なケースではなく、整数値の
Doubleを文字列化するたび毎回発生する)。`NaN`/`Infinity`/`-Infinity`は
G書式とは独立に`Double.ToString()`が特別扱いする固定文字列を返す
(知見45の`^`修正で生成されうる`NaN`も対象)。

**修正内容**(`dump_daemon/uipath_codegen/render.py`):

- `_CAST_FUNCS`から`"cstr": "str"`を削除し、`CStr`を`_render_func_call`
  内で個別処理(`CInt`/`CBool`と同じ扱い)。生成コード側に挿入する
  ヘルパー関数`_vb_cstr(x)`を呼ぶ形に変更:
  ```python
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
  ```
- `&`(文字列結合)も同じ変換規則を使うべきと判断し(VBの`&`は`CStr`と
  同じ文字列化規則で非文字列オペランドを変換するため)、単純な`str()`
  から同じ`_vb_cstr()`呼び出しへ変更。
- ヘルパー関数の生成コードへの実際の挿入は、既存の`_collect_imports`
  の仕組み(`pyperclip`/`pywinauto.Desktop`のimportと同じパターン、
  使用時のみ注入)を拡張して対応——未使用時に余計なコードを増やさない
  既存方針を維持した。

`tests/test_uipath_codegen.py`に
`test_cstr_matches_vb_g_format_not_python_str_float`
(`CStr(4.0)`→`"4"`、`CStr((-8.0) ^ 0.5)`→`"NaN"`等)と
`test_concat_uses_same_vb_cstr_conversion_as_cstr`
(`"x=" & 4.0`→`"x=4"`)を追加、`exec()`して実際の出力文字列まで確認。

**この知見で確定したこと**: 知見45で「軽微、未対応」として残した
`CStr(Double)`の書式差異は、公式ドキュメントの明記により確定・修正
できた(VM検証不要だった——`Mod`/`\`/`CInt`/`CBool`と同じ「ドキュメント
で確定できる」カテゴリ)。なお、G書式の指数表記の閾値・書式
(`E`大文字、2桁指数)とPythonの`e`表記の閾値・書式の違い、および
`ToString()`がカレントカルチャの小数点記号(例: `de-DE`ではカンマ)に
従う可能性は、依然軽微な既知の限界として未対応のまま残す
(UiPath Robot/StudioはこのユーザーのVM環境では常にen-USロケールと
考えられ、実害が出る具体例が見つかるまでは優先度低と判断)。

**(2026-11-05追補)** `_vb_cstr()`導入直後にコードベース全体を
`grep`で確認したところ、`Append Line`(知見15)の`Text`
(`InArgument<String>`)書き込みが単純な`str()`のままで、`_vb_cstr()`に
統一されていない箇所(`uipath_codegen/__init__.py`の
`_generate_append_line`)が1件残っていたと判明——`CStr`/`&`と同じ
「非文字列式をString型の引数に束縛する」場面なので同じ変換規則を
適用し、`_vb_cstr()`を使うよう修正した(VM不使用、コードベース内の
一貫性修正——実機でこの暗黙変換自体の実例はまだ無いが、`_vb_cstr`は
文字列への再適用に対して冪等なので、既にCStr済みの実例に対しても
実害が無い)。`tests/test_uipath_codegen.py`に
`test_append_line_text_uses_vb_cstr_not_python_str`を追加。

同じ監査で`SetToClipboard`の`Text`(`Append Line`と同じ
`InArgument<String>`)も単純な`str()`のままだった箇所
(`_generate_set_to_clipboard`)を発見・同様に修正した。`pyperclip.copy()`
自体は非文字列を渡しても内部でPythonの`str()`に救済されるため実行時
エラーにはならない(`pyperclip`パッケージの全バックエンド実装
(`copy_windows`含む)のソースで確認済み)が、それだとVBのG書式と
食い違う文字列がクリップボードに載る。`tests/test_uipath_codegen.py`に
`test_set_to_clipboard_text_uses_vb_cstr_not_python_str`を追加(この
Linuxサンドボックスにはクリップボード機構が無く`exec()`できないため、
生成コード文字列の直接確認に留めた)。`_generate_append_line`/
`_generate_set_to_clipboard`以外に`str(`を素のまま使っている箇所は
`uipath_codegen/`全体を`grep`して確認済みで、もう残っていない。

## 47. 比較演算子(`=`/`<>`/`<`/`<=`/`>`/`>=`)がOption Strict Off下で数値/文字列混在オペランドを暗黙変換すると確定——Pythonの素の`==`等とは食い違う(VM不使用、公式ドキュメントで確定)

知見46作業中のgrep監査で`_generate_append_line`/`_generate_set_to_clipboard`の
不整合を見つけた直後、同じ監査精神でPAD側の並行知見(他セッションの知見88
「IF/SETの=/<>演算子も型をまたいで等価と判定される」)を見て、UiPath側の
`=`/`<>`等の比較演算子についても同じ観点(Object型オペランドの型をまたいだ
暗黙変換)を確認していなかったことに気づき、公式ドキュメントで調査した。

**確定した内容**(Microsoft Learn「Comparison Operators (Visual Basic)」の
「Typeless Programming with Relational Comparison Operators」節): `Option
Strict Off`(UiPathプロジェクトの既定、知見確認済み)かつ比較の少なくとも
片方が`Object`型オペランドの場合、**実行時の型**によって比較方法が決まる:

| オペランドの組み合わせ | 比較方法 |
|---|---|
| 両方`String` | 通常の文字列ソート比較 |
| 両方数値 | 両方`Double`に変換して数値比較 |
| 片方数値・片方`String` | `String`を`Double`に変換して数値比較(変換不可なら`InvalidCastException`) |
| それ以外の参照型同士 | `InvalidCastException` |

さらに`Nothing`は数値比較では`0`、文字列比較では空文字列として扱われる
(同ページ「Comparing Numbers」「Comparing Strings」節で確認)。

UiPathのワークフロー変数は`GenericValue`(=`Object`型のラッパー)や明示的な
`Object`型が多用される(Excel/CSV/データテーブルから読み取った値を緩い型で
扱う場面が典型)ため、この「数値↔文字列の暗黙変換」は現実のワークフローで
発生しうる。Pythonの`==`はこのような型をまたいだ暗黙変換を一切しない
(`"5" == 5`は常に`False`)ため、単純な`==`等への変換のままでは誤変換になる。

**修正内容**(`dump_daemon/uipath_codegen/render.py`): 全比較演算子を
実行時にオペランドの型を判定して変換する`_vb_cmp(a, b)`ヘルパー関数経由に
変更した——`Not`の修正(知見45)と同じ「静的な型情報が無いためコード生成時
ではなく実行時にisinstanceで分岐する」設計を踏襲(`uipath_codegen`は
変数の宣言型を辿るシンボルテーブルを持たないため、静的型判定は不可能
——実際の評価結果の型で判定するのが唯一の現実的な手段):
```python
def _vb_cmp(a, b):
    def _vb_is_num(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool)
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
```
変換不能な文字列(例: `"abc" = 5`)は`float()`が`ValueError`を送出する
ことで失敗を伝播させる——VBの`InvalidCastException`と例外クラスは違うが、
「静かに間違った結果(`False`)を返す」よりは「失敗を明示的に伝える」方が
安全という既存方針(`_vb_cbool_of_string_literal`と同じ設計判断)を踏襲。
生成コードは`(lambda _t: _t[0] == _t[1])(_vb_cmp(left, right))`という
単一評価のラムダ式に変換し(`left`/`right`の式を二重評価しない)、
ヘルパー関数定義自体は既存の`_collect_imports`の仕組み(使用時のみ注入)
を拡張して対応した。

**既知の限界**(VBの表の中で意図的に実装を見送った部分): 「それ以外の
参照型同士」の組み合わせ(`InvalidCastException`になるはずのケース)は、
`_vb_cmp`では素のPython `==`等にフォールバックする(`False`になりうる)
——UiPathワークフローでカスタムオブジェクト同士を直接比較する実例が
これまで一度も見つかっていないため、該当するでっち上げた例外送出コードは
挿入しなかった。実例が見つかった時点で改めて対応する。

**この知見で確定したこと**: `=`/`<>`/`<`/`<=`/`>`/`>=`全6種の比較演算子に
ついて、公式ドキュメントで確定できる範囲(数値↔文字列↔`Nothing`の型変換
規則)は全て実装・テスト済み。`tests/test_uipath_codegen.py`に
`test_comparison_operators_coerce_numeric_string_like_vb_object_comparison`
(`5 = "5"`→`True`、`Nothing = 0`→`True`等)と
`test_comparison_of_unconvertible_string_against_number_raises_not_silently_false`
(`"abc" = 5`が`ValueError`を送出することを確認)を追加、既存のブリトル
(生成コード文字列の完全一致を見ていた)テスト2件
(`test_if_then_else`・`test_while_loop`)も新しい出力形式に追従させた。
全698件通過、回帰無し。

## 48. `+`演算子が型混在(数値+文字列)で算術加算になるとVBは規定している——単純な`+`変換のままだとPythonは`TypeError`で即クラッシュする(VM不使用、公式ドキュメントで確定、PAD側の並行知見86に着想を得て調査)

知見47(比較演算子)のコミット直後、他セッションが並行して進めている
PAD側の知見86「型混在の`+`のディスパッチルールを実機確認し実装・結線」
(`git log`で確認)を見て、UiPath側の`+`演算子についても同じ観点
(Object型オペランドの型混在ディスパッチ)を確認していなかったことに
気づき、公式ドキュメントで調査した。

**確定した内容**(Microsoft Learn「+ Operator (Visual Basic)」Remarks節):
VBの`+`は「可能な限り算術加算を行い、両方が文字列の場合のみ連結する」
(ページ冒頭の要約そのもの)。具体的なディスパッチ表(Object型・非Object型
どちらの変種も同じ実行時結果になるため統合して引用):

| オペランドの型 | 結果 |
|---|---|
| 両方数値 | 算術加算 |
| 両方`String` | 連結 |
| 片方数値・片方`String` | `String`を`Double`へ変換してから算術加算(変換不可なら`InvalidCastException`) |
| 片方数値・片方`Nothing` | `Nothing`を`0`として算術加算 |
| 片方`String`・片方`Nothing` | `Nothing`を`""`として連結 |

公式ドキュメントが挙げている例そのもの: `Dim var1 As String = "34"`・
`Dim var2 As Integer = 6`に対し`var1 + var2`は`Option Strict Off`下で
`40`になる(`"346"`という連結結果にはならない)——ページ自身が
「予期しない結果になりうるため`&`を使うことを推奨する」と明記するほど
よく知られた罠。

UiPathのワークフロー変数は知見47と同じ理由(`GenericValue`/`Object`型が
多用される)でこの型混在が現実に発生しうる。単純な`+`→`+`変換のままだと
**Pythonは`str + int`を`TypeError`で即座にクラッシュさせる**——知見47の
比較演算子(値は間違うが動く)より一段重大な問題だった(生成スクリプトが
実行時エラーで止まる)。

**修正内容**(`dump_daemon/uipath_codegen/render.py`): 知見45・47と同じ
設計(静的型情報が無いため実行時isinstanceで分岐)で`_vb_add(a, b)`
ヘルパーを追加:
```python
def _vb_add(a, b):
    def _vb_is_num(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool)
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
```
変換不能な文字列は`float()`の`ValueError`をそのまま伝播させる(知見47と
同じ「静かに間違った結果を返さず失敗を伝播させる」方針)。ヘルパー関数の
生成コードへの注入は既存の`_collect_imports`の仕組みを拡張して対応。

`tests/test_uipath_codegen.py`に
`test_plus_operator_dispatches_add_vs_concat_like_vb_not_python_typeerror`
を追加(`"34" + 6`→`"40"`という公式ドキュメントの例そのものを含む)。
全711件通過、回帰無し。

**この知見で確定したこと**: 知見47の比較演算子に続き、`+`演算子の型混在
ディスパッチも公式ドキュメントで確定・実装できた——PAD側の並行知見と
UiPath側で同種の問題が独立に見つかったことは、この系統の「Option Strict
Off/緩い型システム下の暗黙変換」バグが両トランスパイラ共通の盲点
だったことを示唆する。他の演算子(`-`/`*`/`/`)についても同様の型混在
ディスパッチが定義されているか、今後の調査候補として記録する価値がある
(下記参照)。

## 49. `-`/`*`/`/`/`Mod`/`\`も文字列/`Nothing`オペランドで単純な変換のままだと`TypeError`になる——知見48の残課題を解消(VM不使用、公式ドキュメントで確定)

知見48で残した「`-`/`*`/`/`にも`+`と同様の型混在ディスパッチが定義されて
いるか未調査」という課題を、`-`/`*`/`/`/`Mod`それぞれの公式ページ
(Microsoft Learn「- Operator」「* Operator」「/ Operator」「Mod
Operator」)で確認した。

**確定した内容**: `+`と違い、`-`/`*`/`/`/`Mod`/`\`は**文字列を特別扱い
しない純粋な数値演算子**(いずれも「Supported Types: All numeric
types」と明記、`+`のような「両方文字列なら連結」という分岐が無い)。
`Option Strict Off`下での文字列オペランドは、一般の暗黙変換規則により
`Double`へ変換されてから演算される(`+`の表ほど詳細な記載は無いが、
`Option Strict Statement`ページの一般原則が適用される)。さらに全ページ
共通で「`Nothing`は`0`として扱われる」と明記している(`-`/`*`/`Mod`の
各ページで個別に確認済み、`/`はページ取得に失敗したが同系統の演算子
ページとして同じ扱いと推定——もし将来食い違いが見つかれば訂正する)。

Pythonの`-`/`*`/`/`等は文字列や`None`を渡されると`TypeError`で即座に
クラッシュする——知見48の`+`と全く同じ問題がこれらの演算子にも存在した
(`Mod`/`\`は`-`/`*`/`/`の式を組み合わせて実装しているため、問題は
transitively同じ箇所に存在していた)。

**修正内容**(`dump_daemon/uipath_codegen/render.py`): 知見45・47・48と
同じ設計で`_vb_num(x)`ヘルパーを追加(`+`の`_vb_add`と違い「両方文字列」
の特別扱いが無いぶん単純):
```python
def _vb_num(x):
    if x is None:
        return 0
    if isinstance(x, str):
        return float(x)
    return x
```
`-`/`*`/`/`の両オペランド、および`Mod`/`\`が内部で使う`-`/`*`/`/`相当の
部分式も`_vb_num()`で事前に揃えるよう変更。ヘルパー関数の生成コードへの
注入は既存の`_collect_imports`の仕組みを拡張して対応。

`tests/test_uipath_codegen.py`に
`test_numeric_operators_coerce_string_and_nothing_like_vb_not_python_typeerror`
を追加(`"10" - 3`→`"7"`、`5 - Nothing`→`"5"`、`"10" Mod 3`→`"1"`等)。
UiPath関連テスト全130件通過(`test_uipath_codegen.py`/`test_uipath_expr.py`/
`test_uipath_dsl.py`/`test_uipath_selector.py`)。

**既知の残課題(2026-11-05時点、知見50で`/`のゼロ除算、知見51でBoolean
オペランドの数値変換、知見54で`Mod`/`\`のゼロ除算もいずれも解消済み)**:
今のところ残課題なし。

## 50. `/`演算子のゼロ除算がVBのDouble方式(Infinity/NaN)になると確定——Pythonは`ZeroDivisionError`で即クラッシュする(VM不使用、公式ドキュメントで確定、知見49の残課題を一部解消)

知見49で「`/`のページ取得に失敗したため`Nothing`の扱いは類推で実装した」
「ゼロ除算時の挙動差は未調査」と残していた課題を、正しいURL
(`floating-point-division-operator`)で再取得し確認した。

**確定した内容**(Microsoft Learn「/ Operator」): `/`は「除算の前に整数
オペランドは全てDoubleへ拡張される」と明記——つまり**`/`の結果はオペランド
の型によらず常にDouble相当になる**唯一の算術演算子(`-`/`*`/`Mod`/`\`は
型によって結果型が変わる)。これにより`/`のゼロ除算は型分岐せず常に
Double方式になる(「Attempted Division by Zero」節で確定): `expression2`
が0の場合、`expression1`が0なら`NaN`、それ以外は符号に応じて
`PositiveInfinity`/`NegativeInfinity`。Pythonの`/`はゼロ除算で
`ZeroDivisionError`を即座に送出するため、単純な変換のままでは動かない
(知見48・49の`TypeError`と同系統、より重大な問題)。

**修正内容**(`dump_daemon/uipath_codegen/render.py`): `_vb_div(a, b)`
ヘルパーを追加し`/`演算子を専用に結線(`Nothing`→`0`・文字列→`float()`の
強制も内包、`_vb_num`とは独立した自己完結実装——`_collect_imports`は
生成コードに文字通り現れるヘルパー名だけを検知する単純な仕組みのため、
`_vb_div`が内部で`_vb_num`を呼ぶ構造だと注入漏れが起きるのを避けた):
```python
def _vb_div(a, b):
    if a is None:
        a = 0
    elif isinstance(a, str):
        a = float(a)
    if b is None:
        b = 0
    elif isinstance(b, str):
        b = float(b)
    if b == 0:
        if a == 0:
            return float("nan")
        return float("inf") if a > 0 else float("-inf")
    return a / b
```
`NaN`/`Infinity`/`-Infinity`の文字列化は既存の`_vb_cstr()`(知見46)が
既に特別扱いしているため、`CStr(5 / 0)`は正しく`"Infinity"`になる。

`tests/test_uipath_codegen.py`に
`test_division_by_zero_matches_vb_double_semantics_not_python_zerodivisionerror`
を追加(`5 / 0`→`"Infinity"`、`-5 / 0`→`"-Infinity"`、`0 / 0`→`"NaN"`)。
UiPath関連テスト全134件通過。

**既知の残課題(未解消のまま記録)**: `Mod`/`\`のゼロ除算は`/`と違い
型依存(`Mod`の公式ページ「浮動小数点除算は`NaN`、整数除算は
`DivideByZeroException`」)——静的型情報を持たない現在のアーキテクチャ
では安全に実装できないため、意図的に未対応のまま残す(でっち上げた
型推測は入れない)。

## 51. Booleanオペランドの算術・比較演算子への変換は`True→-1`・`False→0`と確定——知見49・50で残していた「未調査」の最後の1点を解消(VM不使用、公式ドキュメントで確定)

知見49・50作業中に繰り返し「未調査」として残していた「Booleanを算術
演算子に渡した場合の挙動」を、公式ドキュメントで確定した。

**確定した内容**(Microsoft Learn「Boolean Data Type」「Type
Conversions」節): 「When Visual Basic converts Boolean values to
numeric types, False becomes 0 and True becomes -1.」——`False`は`0`、
`True`は**`-1`**になる(VB6時代との互換性のための挙動、同ページが
「.NET Frameworkの変換メソッド(`Convert.ToInt32`等)とは異なる結果に
なりうる」と明記している、VB固有の仕様)。

Pythonの`bool`は`int`のサブクラスで`True`は`1`相当のため、何も変換
しなければ符号が逆になる(`5 + True`はVBでは`5 + (-1) = 4`だが、
Pythonの`bool`をそのまま使うと`5 + True = 6`になってしまう)。これまで
`_vb_cmp`/`_vb_add`/`_vb_num`は`_vb_is_num`で`bool`を意図的に「数値では
ない」として除外していたため(Not/And/Or/Xor等の論理演算子との混同を
避ける目的だった)、算術・比較の文脈でも`bool`がそのままPython側の
`+`/`==`等に素通りし、符号が逆の誤った結果になっていた。

**修正内容**(`dump_daemon/uipath_codegen/render.py`): `_vb_cmp`/
`_vb_add`/`_vb_num`/`_vb_div`の4つのヘルパー全ての先頭で、`bool`
オペランドを`True→-1`・`False→0`へ変換してから残りのロジックに流す
よう統一した(`isinstance(x, bool)`判定を他の全ての判定より先に行う)。
`_vb_cstr`(`CStr(True)`→`"True"`)は対象外——こちらはBoolean→**文字列**
変換で別の規則(`True`/`False`という語そのもの)であり、公式ドキュメント
でも今回確認した数値変換規則とは別節で扱われている、既に正しい挙動。

`tests/test_uipath_codegen.py`に
`test_boolean_operand_converts_to_negative_one_not_python_one`を追加
(`5 + True`→`"4"`、`10 / True`→`"-10"`、`-1 = True`→`"True"`等)。
UiPath関連テスト全143件通過、回帰無し。

**この知見で確定したこと**: 知見49・50で2回にわたり「未調査」として
持ち越していたBooleanの算術演算子への変換規則を確定・修正できた
——知見44〜51の一連の「VB.NET演算子の値の食い違い」系統点検で、現状
公式ドキュメントだけで確定できる範囲の課題は全て解消した(残るのは
`Mod`/`\`のゼロ除算(型依存、静的型情報が無く対応不可)のみ。`CDbl`の
`Nothing`/桁区切り文字列は知見52で.NETランタイム本体のソースにより
VM不使用のまま解決した)。

## 52. `CDbl`の`Nothing`/桁区切り文字列/Boolean変換を.NETランタイム本体のソースで確定——VM実機検証を経ずに解決(知見46・49・50で繰り返し残していた最後の課題)

知見46で「`CDbl(Nothing)`/桁区切り文字列は公式ドキュメントだけでは確定
できず、VM実機検証が必要」として残していた課題を、公式ドキュメントの
代わりに「確度の高いソース」として記録していた.NETランタイム本体の
実装ソースコード(`Microsoft.VisualBasic.Core`パッケージの
`Conversions.vb`、`dotnet/runtime`リポジトリ、GitHub上で公開)を直接
確認することで、VM無しのまま確定できた。

**確認したソースファイル**:
`https://github.com/dotnet/runtime/blob/main/src/libraries/Microsoft.VisualBasic.Core/src/Microsoft/VisualBasic/CompilerServices/Conversions.vb`
(Microsoft Learn APIリファレンスページの`Conversions.ToDouble`項目が
「Source」リンクとしてこのファイルの該当行を指している——公式ドキュメント
のAPIリファレンスページ自体が正式にこのソースへリンクしているため、
非公式な野良ソースの参照ではない)。

**確定した内容**:
- **`CDbl(Nothing)`**: `ToDouble(Object)`/`ToDouble(String)`いずれも
  冒頭で`If Value Is Nothing Then Return 0`——例外にならず`0`を返す。
- **`CDbl("1,234.5")`のような桁区切り文字列**: 文字列版の内部実装
  `ParseDouble`関数が`Double.Parse`へ渡す`NumberStyles`フラグに
  `NumberStyles.AllowThousands`を含んでいる(他に
  `AllowDecimalPoint`/`AllowExponent`/`AllowLeadingSign`/
  `AllowLeadingWhite`/`AllowTrailingSign`/`AllowParentheses`/
  `AllowTrailingWhite`/`AllowCurrencySymbol`も含むが、`AllowThousands`
  以外は今回は実装対象外、下記「既知の限界」参照)——桁区切りのコンマは
  実際に受理される。
- **`CDbl(True)`**: `ToDouble(Object)`の`Select Case`に
  `Case TypeCode.Boolean: Return CDbl(DirectCast(Value, Boolean))`が
  存在し、`CDbl(Boolean)`相当を呼ぶ——知見51で確定した「Booleanの数値
  変換は`True`→`-1`」の一般規則がここにも適用される。

Pythonの`float(None)`は`TypeError`、`float("1,234.5")`はコンマで
`ValueError`になるため、単純な`float(x)`変換のままでは食い違う。

**修正内容**(`dump_daemon/uipath_codegen/render.py`): `CDbl`を
`_CAST_FUNCS`の単純名前変換(`float`)から外し、`CInt`/`CBool`/`CStr`と
同じ個別特別扱いへ移行——これにより`_CAST_FUNCS`辞書自体が空になり、
もう使われなくなったので削除した。`_vb_cdbl(x)`ヘルパーを追加:
```python
def _vb_cdbl(x):
    if x is None:
        return 0.0
    if isinstance(x, bool):
        return -1.0 if x else 0.0
    if isinstance(x, str):
        return float(x.strip().replace(",", ""))
    return float(x)
```

`tests/test_uipath_codegen.py`に
`test_cdbl_matches_dotnet_runtime_source_not_python_float`を追加
(`CDbl(Nothing)`→`"0"`、`CDbl("1,234.5")`→`"1234.5"`、`CDbl(True)`→
`"-1"`等)。UiPath関連テスト全150件通過。

**既知の限界(意図的に未対応のまま記録)**: `ParseDouble`が実際に渡す
`NumberStyles`フラグのうち、今回実装したのは桁区切り(`AllowThousands`)
のみ——`AllowParentheses`(会計表記の括弧を負数として扱う、例:
`"(5)"`→`-5`)・`AllowCurrencySymbol`(通貨記号、例: `"$5"`)は未対応の
まま残す(UiPathの実データでこれらの書式が使われる実例が無く、適用範囲が
狭いため優先度低と判断)。また桁区切りの妥当性(3桁ごとの正しいグループ化
か、例: `"1,2,3"`のような不正な区切り方)も検証していない——単純に全ての
コンマを除去するのみで、VBなら`FormatException`になるはずの不正な
グループ化を黙って受理してしまう軽微な既知の限界として記録する。

**この知見で確定したこと**: 知見46で「VM実機検証が必要」として
`^`/`Not`(知見45で解決済み)と同じ分類に置いていた最後の項目を、VM無しで
解決できた——これにより知見44〜52の「VB.NET演算子・型変換関数の値の
食い違い」系統点検で、現実的に対応可能な範囲の課題は全て解消した。

## 53. `CInt`も`CDbl`と同じ`Nothing`/桁区切り文字列の食い違いがあると確定——.NETランタイム本体のソースを`CInt`についても確認(VM不使用)

知見52で`CDbl`用に`Conversions.vb`(.NETランタイム本体のソース)を確認した
ついでに、同じファイル内の`ToInteger`(`CInt`の実体)も確認したところ、
`CDbl`と全く同じ系統の食い違いが`CInt`にも存在すると判明した。

**確定した内容**: `ToInteger(String)`/`ToInteger(Object)`いずれも
先頭で`If Value Is Nothing Then Return 0`——`CDbl`と同じく`Nothing`は
例外にならず`0`を返す。文字列引数は`IsHexOrOctValue`(`&H`/`&O`リテラル、
今回も対象外のまま)でなければ`CDbl`と全く同じ`ParseDouble`(内部で
`NumberStyles.AllowThousands`を含むフラグを使う、知見52)を経由して
`Double`へ変換してから丸めるため、桁区切り文字列(`"1,234.5"`)も受理
される。`ToInteger(Object)`の`TypeCode`別分岐には`Double`/`Decimal`等の
扱いがあり、知見51で確定した「Booleanの数値変換は`True`→`-1`」の一般
規則もここに波及する。

修正前の`render.py`は`CInt(x)`を`round(float(x))`としていたため、
`CInt(Nothing)`は`TypeError`、`CInt("1,234.5")`は`ValueError`になり
VBの挙動と食い違っていた(知見52作業時には`CInt`まで手が回っていなかった
——`CDbl`の修正だけで満足せず、同じファイル内の類似関数を追い打ちで
確認したことで発見)。

**修正内容**(`dump_daemon/uipath_codegen/render.py`): `CInt`の実装を
`round(float(x))`から`round(_vb_cdbl(x))`(知見52の`_vb_cdbl()`ヘルパーを
再利用)へ変更——`Nothing`/桁区切り文字列/Boolean全てを`CDbl`と同じ
ロジックで正しく処理してから`round()`で銀行丸めする、新規ヘルパー追加
無しの最小限の修正。

`tests/test_uipath_codegen.py`に
`test_cint_matches_dotnet_runtime_source_for_nothing_and_thousands`を
追加(`CInt(Nothing)`→`0`、`CInt("1,234.5")`→`1234`、`CInt(True)`→`-1`
等)。UiPath関連テスト全154件通過、回帰無し。

**この知見で確定したこと**: `CDbl`の実装を直した際に見つけた「確度の
高いソース」を同じファイル内の他の関数にも追い打ちで適用する価値が
あると実証された——`CStr`/`CBool`についても同じ手法でクロスチェック
済み(前のtickで実施、`CBool`は既存実装が正しいことを確認済み、
`&H`/`&O`16進・8進リテラル文字列の非対応のみ軽微な既知の限界として
残る)。

## 54. `Mod`/`\`の残課題(ゼロ除算の型依存・`\`の銀行丸め先行)を.NETランタイム本体の別ファイルで解決——知見44〜53で最後まで残っていた「型依存で対応不可」の判断を覆した(VM不使用)

知見50で見つけた`Conversions.vb`(`CDbl`/`CInt`/`CBool`等の変換**関数**の
実体)に続き、比較・算術演算子を実行時にObject型オペランドへ適用する
ディスパッチャ(`Microsoft.VisualBasic.CompilerServices.Operators`クラス)
の実体である`Operators.vb`(同じ`dotnet/runtime`リポジトリ、同じ
ディレクトリ内の別ファイル)の存在に気づき確認した。これにより、
知見49・50で「型依存のため静的型情報が無いと対応不可」と判断していた
`Mod`/`\`のゼロ除算について、方針を修正する材料が得られた。

**確定した内容**:
- **`Mod`のゼロ除算は実際に型依存**(`Operators.vb`の`ModObject`関数で
  確認——オペランドの`TypeCode`(Integer系/Decimal/Single/Double)に応じて
  `ModInt32`/`ModInt64`/`ModDecimal`/`ModSingle`/`ModDouble`等へ
  ディスパッチするだけで、ゼロ除数の特別扱いは無い。結果はCLRのネイティブ
  `Mod`演算そのものに委ねられる——整数系は`DivideByZeroException`相当の
  例外、浮動小数点系(Single/Double)は`NaN`(Microsoft Learn「Mod
  Operator」の「floating-point division returns Double.NaN」とも整合、
  知見49で既に確認済みだった内容の裏取り)。**この型依存性自体は
  知見49・50の判断通り**だが、`uipath_codegen`は静的な宣言型を追跡
  しておらず、代わりに`_vb_num()`後の**実行時のPython型**(`int`→VBの
  整数系の代理、`float`→VBの浮動小数点系の代理)で判定することにした
  ——VBランタイム自身も`TypeCode`(実行時の型情報)で分岐しているため、
  この代理方式は「静的型が必要」という以前の判断ほど悲観的でなくてよい
  と判明した(知見45の`Not`以来使ってきた設計と同じ発想)。
- **`\`のゼロ除算は型によらず常に例外**(Microsoft Learn「\ Operator」の
  「Attempted Division by Zero」節: 「This is true for all numeric data
  types of the operands」)——`Mod`と違い型依存ではなく、Pythonの`/`も
  ゼロ除数で型によらず常に`ZeroDivisionError`を送出するため、この点は
  既に無変換のまま一致していたと判明(修正不要)。
- **(新発見)`\`は除算の**前**にオペランドをLongへ変換し、その変換は
  銀行丸めの対象になる**(同ページRemarks節: 「Before performing the
  division, Visual Basic attempts to convert any floating-point numeric
  expression to Long... The conversion to Long is also subject to
  banker's rounding」)——`\`の実機未確認だった残課題として今回新たに
  発見した。例: `7.5 \ 2`は`7.5`が銀行丸めで`8`になってから切り捨て
  除算され`4`になる(丸め無しの単純な`int(7.5/2)`は`3`で食い違う)。
  `67 \ -3 = -22`のような整数オペランド例では丸めが発生しないため
  この食い違いは見過ごされていた。

**修正内容**(`dump_daemon/uipath_codegen/render.py`): `Mod`を型依存の
ゼロ除算ロジックを持つ`_vb_mod()`ヘルパー経由に変更:
```python
def _vb_mod(a, b):
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
        if isinstance(a, float) or isinstance(b, float):
            return float("nan")
        raise ZeroDivisionError("Mod by zero (VB would raise DivideByZeroException)")
    return a - (b * int(a / b))
```
`\`は両オペランドを`round()`(知見42で確認済みの銀行丸め)してから
切り捨て除算するよう変更(`int(round(_vb_num(left)) / round(_vb_num(right)))`)。

`tests/test_uipath_codegen.py`に3件追加
(`test_mod_by_zero_with_float_operand_returns_nan_not_exception`、
`test_mod_and_intdiv_by_zero_with_integer_operands_raises`、
`test_intdiv_rounds_operands_to_long_before_truncating_not_truncating_raw_value`)。
UiPath関連テスト全160件通過、回帰無し。

**この知見で確定したこと**: 知見44〜53で唯一「型依存のため対応不可」
として残していた`Mod`/`\`のゼロ除算を、実行時型による代理判定という
既存の設計パターンを適用することで解決できた——これにより知見44〜54の
「VB.NET演算子・型変換関数の値の食い違い」系統点検は、公式に確認
できた範囲で完全に完了した(現時点で既知の残課題は無し)。この経緯は
「型依存だから対応不可」という判断自体を鵜呑みにせず、より多くの一次
情報源(ランタイム本体のソース)に当たることで覆せる場合があるという
教訓として記録する価値がある。

## 55. `Nothing + Nothing`は`+`演算子の一般則の例外で整数`0`になると確定——知見48の`_vb_add()`自体のバグを.NETランタイム本体のソースで発見・修正(VM不使用)

知見54で`Operators.vb`(`Conversions.vb`と同じ`dotnet/runtime`
ディレクトリ内の、Object型オペランドへの演算子ディスパッチャ)の存在を
知った流れで、`+`演算子のディスパッチャ本体`AddObject`も確認したところ、
知見48で実装した`_vb_add()`ヘルパー自体に未発見のバグが見つかった。

**確定した内容**: `AddObject`のソースを直接読むと、`Empty + Empty`
(`Nothing + Nothing`)は`Return Boxed_ZeroInteger`——**整数`0`**を返す
と明記されている。これは知見48で参照した公式ドキュメント(Microsoft
Learn「+ Operator」の「If either Object expression evaluates to
Nothing or DBNull, the + operator treats it as a String with a value
of ''」)の一般則とは異なる——この一般則は「片方がNothingでもう片方が
実際の値を持つ」場合の規則であり、「両方がNothing」という組み合わせは
`AddObject`内で別枠の特別ケースとして扱われ、一般則を上書きしている
ことが実際のソースコードで初めて判明した。知見48実装時はこの一般則を
機械的に両方Nothingのケースにも適用して`""`と推測していたが、これは
誤りだった。

**修正内容**(`dump_daemon/uipath_codegen/render.py`): `_vb_add(a, b)`の
`if a is None and b is None: return ""`を`return 0`に変更。
`tests/test_uipath_codegen.py`の
`test_plus_operator_dispatches_add_vs_concat_like_vb_not_python_typeerror`
に`("Nothing + Nothing", "0")`を追加。UiPath関連テスト全161件通過。

**この知見で確定したこと**: 知見44〜54の系統点検完了を宣言した直後に、
その点検の過程で実装したヘルパー自身のバグ(`Nothing + Nothing`の
エッジケース、どのテストもこれまでカバーしていなかった)が、同じ
「実際のランタイムソースを直接読む」手法で見つかった——「ドキュメントの
一般則をそのまま機械的に適用する」のではなく「実際のソースコードが
その一般則の例外を設けていないか」まで確認する必要があるという、
より踏み込んだ教訓。知見44〜55でこれまでに見つかった全ての問題は
現時点で解消済み。

## 56. `_vb_cstr(None)`が`"None"`という絶対にVBが出さない文字列を返していたバグを発見・修正——知見55に続きクロスチェックで`_vb_cstr`自身のバグを発見(VM不使用)

知見55で`_vb_add`自身のバグを見つけた流れで、`&`演算子のディスパッチャ
`ConcatenateObject`(`Operators.vb`)も確認したところ、`_vb_cstr()`
ヘルパー自身(知見46で導入)に未発見のバグが見つかった。

**確定した内容**: `Conversions.vb`の`ToString(Object)`(`CStr`の実体)は
`If Value Is Nothing Then Return Nothing`——つまり`CStr(Nothing)`自体は
実際には(nullの)`Nothing`を返す。一方`ConcatenateObject`
(`&`演算子のディスパッチャ)は`Return CStr(Left) & CStr(Right)`という
形で、`CStr`の戻り値(nullになりうる)をそのまま`&`(`System.String.Concat`
相当)に渡す——`System.String.Concat`は公式に「null引数は空文字列として
扱う」と保証されている(.NET標準ライブラリの既定動作)ため、結果として
`Nothing & Nothing`は最終的に空文字列`""`になる。

しかし修正前の`_vb_cstr(x)`はこの`x is None`のケースを一切考慮しておらず、
`isinstance(x, float)`に該当しないため最終行の`return str(x)`まで
落ちて`str(None)`=`"None"`という**VBが絶対に出力しない文字列**を
返していた。これは`CStr(Nothing)`単体でも、`"x=" & Nothing`のような
頻出する文字列結合シナリオでも発生する——`&`は`_vb_cstr(left) +
_vb_cstr(right)`の形で実装されている(知見46)ため、この`_vb_cstr`の
バグが`&`演算子にも直接伝播していた。

**修正内容**(`dump_daemon/uipath_codegen/render.py`): `_vb_cstr(x)`の
先頭に`if x is None: return ""`を追加——「`CStr(Nothing)`自体は厳密には
nullを返す」という点までは完全には再現せず、「`&`での最も一般的な実用
シナリオ(文字列結合)で正しい結果になる」ことを優先した近似を採用した
(`uipath_codegen`はnull値を型として伝播させる仕組みを持たないため、
厳密なnull伝播を実装するのは過剰——単独の`CStr(Nothing)`がダイアログ等
文字列以外の文脈でどう扱われるかまでは追跡しない、既知の限界として記録)。

`tests/test_uipath_codegen.py`の
`test_cstr_matches_vb_g_format_not_python_str_float`に
`("CStr(Nothing)", "")`、
`test_concat_uses_same_vb_cstr_conversion_as_cstr`に
`('"x=" & Nothing', "x=")`/`('Nothing & "abc"', "abc")`を追加。UiPath
関連テスト全164件通過。

**この知見で確定したこと**: 知見55に続き、ランタイムソースのクロス
チェックで既存実装自身のバグ(今回は知見46の`_vb_cstr`)がもう1件見つかった
——この「完了宣言後に別の演算子ディスパッチャを確認するたびに、既存
ヘルパーの`Nothing`絡みエッジケースの見落としが見つかる」というパターンが
2回連続した。他の演算子(`^`/比較演算子)のディスパッチャで同様の
`Nothing`絡みの見落としが無いか、継続して確認する価値がある。

## 57. `^`演算子が文字列/`Nothing`オペランドで`TypeError`になるバグを発見・修正——知見56に続き3回目のランタイムソースクロスチェックでの発見(VM不使用)

知見56で示唆した「他の演算子のディスパッチャでも同様の見落としが無いか
継続確認する」を実行し、`Operators.vb`の`ExponentObject`(`^`演算子の
ディスパッチャ)を確認したところ、`^`自体のコード生成に別のバグが
見つかった。

**原因**: `^`は`-`/`*`/`/`/`Mod`/`\`に対する知見49の型混在対応サイクル
より**前**(知見45、2026-11-05の早い段階)に実装していたため、文字列/
`Nothing`オペランドを`_vb_num()`で事前に数値へ強制する処理が
漏れていた。`^`の生成コードは`({left}) < 0`という比較を直接含むため、
`left`が`None`(Nothing)や`str`(数値文字列)のままだと`None < 0`/
`str < int`でPython側が比較不能として`TypeError`を送出していた
(`"2" ^ 2`や`Nothing ^ Nothing`のような式で発生)。

**確定した内容**(`Operators.vb`の`ExponentObject`): `Empty`
(`Nothing`)オペランドは両辺とも`0.0`(Double)に変換してから`^`演算を
行う——`Empty ^ Empty`は`0.0 ^ 0.0`で、VBの指数演算の慣習により`1`に
なる(他の演算子と同じ「`Nothing`→`0`」パターンがここにも適用される)。

**修正内容**(`dump_daemon/uipath_codegen/render.py`): `^`の両オペランドに
`_vb_num()`を適用してから既存のNaN分岐ロジックへ渡すよう変更。

`tests/test_uipath_codegen.py`に
`test_pow_coerces_string_and_nothing_operands_not_raising_typeerror`を
追加(`Nothing ^ Nothing`→`"1"`、`"2" ^ 2`→`"4"`)。既存の
`test_pow_matches_vb_nan_on_negative_base_with_fractional_exponent`は
`render_expr()`の出力を直接`eval()`する方式のため(`generate_python()`の
ヘルパー自動注入を経由しない)、`VB_NUM_HELPER_SOURCE`を`eval()`の
名前空間へ明示的に注入するよう修正——`_vb_num`参照先が追加されたことで
`NameError`になっていたのを解消。UiPath関連テスト全166件通過。

**この知見で確定したこと**: 知見55・56に続き3回連続でランタイムソース
クロスチェックから実在するバグが見つかった——このパターンが続く限り、
残りの演算子ディスパッチャ(`AndObject`/`OrObject`/`XorObject`/
`NotObject`の`Nothing`絡み、`NegateObject`(単項`-`)等)も確認する価値が
ある。知見44〜57でこれまでに見つかった全ての問題は現時点で解消済み。

## 58. 単項`Not`/`-`/`+`も`Nothing`オペランドで`TypeError`になるバグを発見・修正——クロスチェック4件目(VM不使用)

知見57の「残りの演算子ディスパッチャも確認する価値がある」を実行し、
`Operators.vb`の`NotObject`(単項`Not`)・`NegateObject`(単項`-`)・
`PlusObject`(単項`+`)を確認したところ、3つとも`Nothing`オペランドで
バグが見つかった。

**確定した内容**:
- `NotObject`の`Case TypeCode.Empty`は`Return Not 0I`——`Nothing`を整数
  `0`として`Not`を適用し`-1`を返す。
- `NegateObject`/`PlusObject`の`Case TypeCode.Empty`はいずれも
  `Return Boxed_ZeroInteger`——`Nothing`を整数`0`として扱い、単項`-`/`+`
  いずれも`0`を返す。

修正前の実装はいずれも`Nothing`(`None`)を考慮しておらず、`~None`
(`Not`)・`-(None)`(単項`-`)・`+(None)`(単項`+`)がPython側で
`TypeError`を送出していた。

**修正内容**(`dump_daemon/uipath_codegen/render.py`): `Not`のラムダ式を
「`~`を適用する前に`None`を`0`へ読み替える」よう変更(`~0`は`-1`なので
自然に一致する)。単項`-`/`+`も同様に`None`を`0`へ読み替えるラムダ式へ
変更(従来の単純な`{op}({operand})`から`(lambda _x: {op}(0 if _x is
None else _x))({operand})`へ)。

`tests/test_uipath_codegen.py`に
`test_unary_operators_coerce_nothing_operand_not_raising_typeerror`を
追加(`Not Nothing`→`"-1"`、`-Nothing`→`"0"`、`+Nothing`→`"0"`)。UiPath
関連テスト全169件通過。

**既知の残課題**: `And`/`Or`/`Xor`(二項)の`Nothing`絡みエッジケースは
当初型依存で複雑と判断し未対応のまま残していたが、知見59で解決した
(下記参照)。

## 59. `And`/`Or`/`Xor`の`Nothing`絡みエッジケースも解決——知見58で「複雑なため保留」としていた残課題を型ごとの分岐を具体的に確認して解消(VM不使用、クロスチェック5件目)

知見58で「`And`/`Or`/`Xor`は型依存の分岐が複雑なため、でっち上げた
中途半端な実装を避け未対応のまま残す」としていたが、`Operators.vb`の
`AndObject`/`OrObject`/`XorObject`の`Empty`絡み分岐を具体的に(他方の
オペランドの型ごとに)確認したところ、実際には整理可能な単純な規則に
落とし込めると判明した。

**確定した内容**:
- **`And`**: `Nothing`は他方が`Boolean`なら`False`(`Boolean`型)、
  `Int32`(Integer)なら`0`(Integer型)として扱われる(`AndObject`
  「Empty with Boolean: Return False」「Empty with Int32: 常に0」)。
  両方`Nothing`は`0`(Integer、他の単項演算子と同じ
  `Boxed_ZeroInteger`パターン)。
- **`Or`/`Xor`**: `Nothing`は常に`0`相当の単位元として働くため、結果は
  **他方のオペランドをそのまま返す**(型も維持される——`OrObject`
  「Empty with Int32: Return Right」、`XorObject`も同じパターン)。
  両方`Nothing`はいずれも`0`(Integer、`Boxed_ZeroInteger`、直接確認)。

**修正内容**(`dump_daemon/uipath_codegen/render.py`): `_vb_and`/
`_vb_or`/`_vb_xor`の3ヘルパーを追加し、`And`/`Or`/`Xor`の生成コードを
単純な`&`/`|`/`^`への直接変換から、これらのヘルパー呼び出しへ変更
(両オペランドが実際に値を持つ場合は内部で引き続き`&`/`|`/`^`を使う
ため、既存の正しい挙動は維持される)。

```python
def _vb_and(a, b):
    if a is None and b is None:
        return 0
    if a is None:
        return False if isinstance(b, bool) else 0
    if b is None:
        return False if isinstance(a, bool) else 0
    return a & b
```
(`_vb_or`/`_vb_xor`は「`Nothing`なら他方を返す」という、さらに単純な形。)

`tests/test_uipath_codegen.py`に
`test_and_or_xor_coerce_nothing_operand_not_raising_typeerror`を追加
(`Nothing And True`→`"False"`、`Nothing Or 5`→`"5"`、
`Nothing Xor Nothing`→`"0"`等9件、既存の非`Nothing`ケースの回帰確認
2件も含む)。UiPath関連テスト全180件通過。

**この知見で確定したこと**: 知見55〜59で5回連続、ランタイムソースの
クロスチェックから実在するバグ(または解決可能な残課題)が見つかった
——「型依存だから複雑で対応不可」という判断を一度保留した後でも、
具体的に分岐を書き出してみると実装可能な場合がある、という知見58自身の
教訓を体現する結果になった。`uipath_codegen`が扱う主要な演算子
(算術・比較・論理・文字列結合・単項)の`Nothing`絡みエッジケースは、
これで全て確認・対応済みになった。

## 60. `AndAlso`/`OrElse`が常にBoolean型の結果を返さないバグを発見・修正——知見59の直後、今度は公式ドキュメント(VM不使用)から

知見59で`And`/`Or`/`Xor`(非短絡評価)の`Nothing`絡みを解決した流れで、
対になる`AndAlso`/`OrElse`(短絡評価)も同じ観点で見直したところ、
`Nothing`の有無に関わらない、より根本的なバグが見つかった——今回は
`Operators.vb`ではなく公式ドキュメント(Microsoft Learn「AndAlso
Operator」)で確定した。

**確定した内容**: 「Visual Basic converts each operand as necessary to
Boolean before evaluating the expression」(両オペランドを評価前に
Booleanへ変換する)と明記されている——`AndAlso`/`OrElse`の結果は
**常にBoolean型**になる。従来の実装は`(left) and (right)`/`(left) or
(right)`という単純なPython変換だったが、Pythonの`and`/`or`はBoolean
変換をせず**生のオペランド値をそのまま返す**(例: `0 and True`は
`Boolean`の`False`ではなく`int`の`0`を返す)。これにより`0 AndAlso
True`はVBでは`False`になるはずが、修正前は`CStr(0 and True)`=`"0"`
(`Boolean`の`"False"`ではない)になっていた——`Nothing`を一切介さない、
通常の数値オペランドだけでも発生する食い違いだった。

**修正内容**(`dump_daemon/uipath_codegen/render.py`): `_vb_bool(x)`
ヘルパー(`CBool`の文字列判定ロジック(`_vb_cbool_of_string_literal`)と
`ParseDouble`の桁区切り受理規則(知見52)をランタイム版にしたもの)を
追加し、`AndAlso`/`OrElse`の両オペランドをこのヘルパー経由でBooleanへ
変換してから、短絡評価自体はPythonネイティブの`and`/`or`に委ねる
(`_vb_bool(...)`という関数呼び出し式を`and`/`or`で結ぶため、右辺の
評価自体はPythonの通常の短絡評価規則で正しくスキップされる——副作用の
ある式を二重評価・過剰評価しない)。

```python
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
        return float(normalized.replace(",", "")) != 0
    return x != 0
```

`tests/test_uipath_codegen.py`に
`test_andalso_orelse_coerce_operands_to_boolean_not_raw_python_and_or`
(`0 AndAlso True`→`"False"`等8件)と
`test_andalso_short_circuits_without_evaluating_right_side_effect`
(生成コードが`_vb_bool(b)`という単一の式のままで、短絡評価による
右辺のスキップが引き続き機能することを生成コード自体で確認)を追加。
UiPath関連テスト全189件通過。

**この知見で確定したこと**: 知見55〜60で6回連続、クロスチェックから
実在するバグが見つかった——今回は`Operators.vb`ではなく通常の公式
ドキュメントの再読で見つかったことから、「ランタイムソースだけでなく、
対になる演算子(`And`↔`AndAlso`等)を見直す」ことそのものが有効な
手法だと分かる。知見44〜60の系統点検はこれで(現時点で既知の課題は)
完全に完了した。

## 61. `If`/`While`/`DoWhile`/三項`If()`の条件もPythonの素の真偽値判定を使っており、VBのBoolean変換規則と食い違うバグを発見・修正——最も影響範囲が広い発見(VM不使用、クロスチェック7件目)

知見60で`AndAlso`/`OrElse`がBoolean変換を要求すると確定した流れで、
同じ「条件式としてBooleanへの暗黙変換が必要な構文」が他にも無いか
確認したところ、`If`/`While`/`DoWhile`文と三項演算子`If(cond, t, f)`
**全ての条件式**が、同じ食い違いを抱えていたと判明した——UiPathの
ワークフローで最も頻繁に使われる制御構文だけに、影響範囲は今回の
系統点検の中で最も広い。

**確定した内容**(Microsoft Learn「If...Then...Else Statement」):
「condition: Required. Expression. **Must evaluate to True or False,
or to a data type that is implicitly convertible to Boolean.**」——
`If`文の条件式は`AndAlso`/`OrElse`(知見60)と全く同じ「暗黙的に
Booleanへ変換可能な型なら受理し、評価前にBooleanへ変換する」規則に
従う。

修正前の`_generate_if`/`_generate_while`/`_generate_do_while`
(`dump_daemon/uipath_codegen/__init__.py`)と`_render_func_call`の
三項`If`(`render.py`)は、いずれも条件式をPythonの`if`/`while`文の
**素の真偽値判定**(`bool(x)`相当、文字列は空文字列以外常に`True`)に
そのまま委ねていた——これはVBのCBool規則と根本的に食い違う。例えば
`If someVar Then`で`someVar`が文字列`"False"`や`"0"`を保持している
場合(緩い型のUiPath変数で現実的に起こりうる)、VBはCBool規則で`False`
扱いになるが、Pythonの素の`if "False":`は非空文字列なので`True`に
なってしまう。

**修正内容**: `_generate_if`/`_generate_while`/`_generate_do_while`の
条件式、および三項`If()`の第1引数全てを、知見60で導入した`_vb_bool()`
ヘルパーで明示的にBooleanへ変換してから評価するよう変更(`ElseIf`は
`IfNode`の再帰構造を通じて自動的に同じ修正が適用される)。

`tests/test_uipath_codegen.py`に
`test_if_condition_coerces_to_boolean_like_vb_not_python_truthiness`
(`"False"`→`"NO"`、`"0"`→`"NO"`、`Nothing`→`"NO"`等)、
`test_while_condition_coerces_to_boolean_like_vb_not_python_truthiness`、
`test_ternary_if_condition_coerces_to_boolean_like_vb_not_python_truthiness`
を追加。既存のブリトルな生成コード文字列完全一致テスト2件
(`test_if_then_else`・`test_while_loop`)も新形式に追従させた。UiPath
関連テスト全196件通過、リポジトリ全体で全804件通過。

**この知見で確定したこと**: 知見55〜61で7回連続、クロスチェックから
実在するバグが見つかった——今回は制御構文という、今までの算術・比較・
論理演算子とは異なるカテゴリへの波及で、かつ実際の自動化ワークフローで
最も使用頻度の高い構文(`If`/`While`)に影響する点で、これまでで最も
実用上のインパクトが大きい発見だった。「ある構文クラス(演算子)で
確定した規則は、同じ公式ドキュメントが言及する隣接構文(条件式一般)
にも波及していないか確認する」という、知見60で得た教訓をさらに一段
深掘りした形になる。

## 62. `CBool`の非リテラル経由フォールバックも`_vb_bool()`に統一——知見43で記録していた既知の限界をついに解消(VM不使用)

知見60・61で`_vb_bool()`ヘルパーを導入したことで、知見43(`CBool`の
文字列判定修正時)から「既知の限界」として記録し続けていた別の課題も
解消できると気づいた。

**経緯**: `CBool(x)`の変換(`_render_func_call`)は、`x`がコード生成時に
判明する文字列リテラル(例: `CBool("True")`)の場合のみ
`_vb_cbool_of_string_literal()`で正しく判定していたが、`x`が変数参照
などの非リテラル(例: `CBool(someVar)`)の場合は実行時の型が不明なため、
素のPython`bool(x)`にフォールバックしていた——これは`someVar`が
文字列`"False"`/`"0"`を保持している場合に`bool("False")`=`True`
(VBでは`False`になるべき)という食い違いを生む既知の限界だった。

**解決**: `_vb_bool()`はまさにこの「実行時の値の型を見て適切に変換する」
ために設計されたヘルパー(`_vb_cbool_of_string_literal`と同じ文字列
判定ロジックを実行時版にしたもの)なので、`CBool`の非リテラル
フォールバックをこちらに切り替えるだけで解決した——新規ロジックの
追加は不要、既存ヘルパーの再利用のみ。

`tests/test_uipath_codegen.py`の
`test_cbool_non_literal_string_falls_back_to_bool_with_known_limitation`
を`test_cbool_non_literal_uses_vb_bool_not_python_truthiness`へ更新
(生成コードが`_vb_bool(someVar)`になることを確認)、実際の値が正しく
`False`になることを確認する
`test_cbool_non_literal_string_value_matches_vb_not_python_truthiness`
を追加。UiPath関連テスト全197件通過。

**この知見で確定したこと**: 知見60・61で導入した`_vb_bool()`が、知見43
で未解決のまま残していた別の既知の限界も波及的に解消した——1つの
ヘルパー追加が複数の既知の限界を同時に解消する好例になった。知見43・
44〜62の系統点検は、現時点で既知の課題を全て解消した状態になった。

## 63. `CBool`のリテラル文字列判定(`_vb_cbool_of_string_literal`)が桁区切り文字列を受理せず不整合だったバグを修正(VM不使用)

知見62で`CBool`の非リテラルフォールバックを`_vb_bool()`へ統一した際、
念のため対になるコード生成時専用の`_vb_cbool_of_string_literal()`
(リテラル文字列専用の別実装)も見直したところ、桁区切り文字列の扱いに
不整合が見つかった。

**確定した内容**: `_vb_bool()`(知見60)は`float(normalized.replace(",",
""))`という形でコンマを除去してから数値変換しており、これは`CDbl`/
`CInt`/`CBool`いずれの文字列引数も内部で`ParseDouble`
(`NumberStyles.AllowThousands`、知見52)を経由するという確定済みの
事実と整合している。一方`_vb_cbool_of_string_literal()`
(コード生成時にリテラル文字列だけを特別扱いする別実装、知見42・43)は
素の`float(text)`のままコンマを除去していなかったため、`CBool("1,234")`
のような桁区切り文字列**リテラル**だけが`ValueError`→
`NotImplementedError`(コード生成自体の失敗)になっていた——同じ値を
変数経由(`CBool(someVar)`、`someVar = "1,234"`)で渡せば`_vb_bool()`
が正しく処理できるのに、リテラルとして直接書いた場合だけ失敗する
という不整合だった。

**修正内容**(`dump_daemon/uipath_codegen/render.py`):
`_vb_cbool_of_string_literal()`の数値変換部分も`_vb_bool()`と同じ
`.replace(",", "")`を適用し、規則を揃えた。

`tests/test_uipath_codegen.py`の
`test_cbool_string_literal_matches_vb_semantics_not_python_truthiness`
に`('CBool("1,234")', True)`を追加。UiPath関連テスト全198件通過。

**この知見で確定したこと**: 知見62の修正を見直す過程で、対になる
コード生成時専用ロジックとの不整合という、より小さいが実在するバグが
もう1件見つかった——「ランタイム版ヘルパーを直したら、対になる
コード生成時専用ロジックも同じ規則になっているか確認する」という、
今回新たに得られた教訓。

## 64. `Append Line`/`Read Text File`の既定エンコーディング(UTF-8決め打ち)はUiPath公式ドキュメントで正当性を確認——`Encoding`/`UseDefaultEncoding`属性は意図的に未パースのまま記録(VM不使用)

VB.NET演算子の系統点検が一区切りついたため、別のカテゴリ(アクティビティ
プロパティの忠実度)を確認した——`_generate_append_line`/
`_generate_read_text_file`が`encoding="utf-8"`を決め打ちしている点が
正しいかどうか、UiPath公式ドキュメントで確認した。

**確認した内容**(UiPath公式ドキュメント「Append Line」「Read Text
File」アクティビティページ): 「Use default encoding is off by
default. When it's off, UTF-8 encoding is used.」——`UseDefaultEncoding`
は既定で`False`、かつ`False`のときはUTF-8が使われる。実機で捕捉した
実例(design/evidence/uipath_xaml_probe/Main.xaml)の
`<ui:AppendLine ... UseDefaultEncoding="False" />`は、まさにこの
既定状態のまま保存されたものと確認できた(`Encoding`属性自体は
現れていない——値を明示的に変更していない場合は省略されると判明)。
したがって現状の`encoding="utf-8"`決め打ちは、少なくとも**既定設定の
場合**は正しい。

**既知の限界(意図的に未対応のまま記録)**: `AppendLineNode`/
`ReadTextFileNode`(`dump_daemon/uipath_dsl/types.py`)は`Encoding`/
`UseDefaultEncoding`属性自体をXAMLパース時に一切キャプチャしていない
——ユーザーが明示的に`UseDefaultEncoding="True"`(OSのANSIコードページ
依存)や特定の`Encoding`(例: `"Unicode"`=UTF-16、`"ASCII"`等)へ変更
した場合、その情報は完全に失われ、常にUTF-8として生成される。実機で
この非既定設定を使った実例がまだ見つかっていないため(知見15・16の
実例はいずれも既定設定のまま)、どの文字列値がUiPathのどのエンコーディング
名に対応するかの網羅的なマッピング表をでっち上げるのは避け、未対応の
まま記録するに留める——実際の自動化データで非既定エンコーディングの
実例が見つかった時点で改めて着手する。

## 65. 文字列補間`$"...{expr}..."`のプレーンな補間をサポート——知見36以来ずっと`# TODO`に倒れていた機能を実装(VM不使用、公式ドキュメントで構文を確定)

知見36以来、文字列補間`$"..."`は`uipath_expr`のdocstringが「`{expr}`内部に
さらに式がネストしうる構造はレクサで正しく扱えない」と明記して完全に
未対応のまま(常に`# TODO`へ倒れる)残していた。今回、公式ドキュメント
(Microsoft Learn「Interpolated Strings」)で正確な構文規則を確認した上で、
`uipath_codegen/render.py`側(構文解析の後段、コード生成の直前)に手書きの
状態機械を実装し、プレーンな`{expr}`補間(書式指定子・フィールド幅を
伴わない形)をサポートした。

**確定した構文規則**(Microsoft Learn「Interpolated Strings」): 構造は
`$"<text> {<expr> [,<field-width>] [:<format-string>] } <text> ..."`。
リテラルの`{`/`}`は`{{`/`}}`とダブらせてエスケープする。`{expr}`の中には
VB文字列リテラルが(エスケープ無しで)ネストしうる——公式ドキュメント
自身の例`$"{name} is {age:D3} year{If(age = 1, "", "s")} old."`が
`If(age = 1, "", "s")`という、`""`/`"s"`という通常のVB文字列リテラルを
含む式をそのまま`{...}`内に書けることを示している。

**実装の層構造(2段階)**:
1. `uipath_expr`のLarkレクサ(`INTERP_STRING`トークンの正規表現)は、
   `$"..."`全体を1個の不透明なトークンとしてそのまま捕捉するのみ——
   `{expr}`内部にネストした文字列リテラルがあると(`""`/`"s"`のような
   クォートの出現パターンを、補間文字列自身のエスケープ`""`と区別できない
   ため)このレクサ自体が崩れ、式全体が構文解析失敗になる(**この限界は
   未解消のまま残る**、下記参照)。
2. レクサが成功した場合(=`{expr}`内にネストした文字列リテラルが無い
   場合)に限り、`InterpolatedString.raw`に残る生テキストを
   `uipath_codegen/render.py`の`_split_interpolated_string()`
   (`{`/`}`の深さとネストしたクォート状態を追跡する手書きの状態機械)が
   リテラルテキスト区間と`{expr}`区間へ正しく分解し、各`{expr}`を
   `parse_vb_expr()`で再帰的に構文解析してからコードを生成する。

**生成コードの設計**: Pythonのf-string(`f"..."`)ではなく、明示的な`+`
連結(`"text1" + _vb_cstr(expr1) + "text2" + ...`)を選んだ——理由は2つ:
(1) `{expr}`内のVB式を`repr()`した結果がダブルクォート文字列になりうる
(例: アポストロフィを含む文字列)ため、f-stringのクォート文字と衝突し
Python 3.11以前では構文エラーになるリスクがある。(2) f-stringの`{expr}`は
Pythonの素の`str()`で書式化するが、VBの文字列補間は実際には`CStr`/`&`と
同じ書式規則(知見46)に従うため、`_vb_cstr()`を明示的に挟む方がより
正確(実際に`$"n={y}"`(`y=4.0`)で`"n=4"`になることを確認——f-stringの
素の`str()`なら`"n=4.0"`になってしまうところ)。

書式指定子・フィールド幅(`{expr:format}`/`{expr,width}`)が実際に検出
された場合は、VBの書式指定子をPython側へ正確に対応させる確証が無い
ため(でっち上げを避け)`NotImplementedError`を送出し、既存の`# TODO`
フォールバック機構に委ねる——プレーンな補間のみサポート対象。

`tests/test_uipath_codegen.py`に
`test_assign_interpolated_string_renders_to_vb_cstr_concatenation`
(知見36の実例そのものを含む複数ケース)、
`test_interpolation_with_format_string_falls_back_to_todo`、
`test_interpolation_with_nested_quoted_expression_still_falls_back_to_todo`
(レクサの既知の限界が安全にTODOへ倒れることの確認、クラッシュしない
ことの回帰テスト)、
`test_interpolated_string_renders_plain_interpolations_correctly`を追加。
UiPath関連テスト全204件通過、リポジトリ全体で全818件通過。

**既知の残課題(未解消のまま記録)**: `{expr}`内部にネストした文字列
リテラルを含む式(公式ドキュメント自身の例を含む)は、Larkのレクサが
まだ崩れたまま——これを解消するには`INTERP_STRING`トークンの正規表現
自体を書き換えるか、Lark呼び出し前に独自のプリスキャンで`$"..."`の
範囲を正しく特定する、より大きな変更が必要。今回は「プレーンな補間」
という、知見15・16・32・36の実機確認例が全てカバーされる範囲に絞って
実装し、でっち上げた拡張は避けた。

## 66. 文字列補間の`{expr}`内部にネストした文字列リテラルを含む式も解決——知見65で「より大きな変更が必要」として見送っていたLarkレクサの限界を、Lark呼び出し前のプリスキャンで解消(VM不使用)

知見65の「既知の残課題」で明示していた、`{expr}`内部にネストした
VB文字列リテラル(公式ドキュメント自身の例`If(age = 1, "", "s")`)を
含む補間がLarkレクサの時点で崩れる問題を、`uipath_expr`側に
Lark呼び出し前の専用プリスキャンを追加して解消した。知見65の時点で
「`INTERP_STRING`トークンの正規表現自体を書き換えるか、Lark呼び出し前の
独自プリスキャンが必要」と2つの選択肢を記録していたうち、後者を採用
した——正規表現には任意の`{}`ネスト深さを扱う能力が無いため、前者は
原理的に不可能だった。

**実装**(`dump_daemon/uipath_expr/__init__.py`): `_find_interp_string_span()`
が`{`/`}`の深さを追跡する手書きの状態機械で`$"..."`の正しい終端を
確定する——深さ0の間の`"`は補間文字列自身の境界/`""`エスケープ、
深さ1以上(`{expr}`内部)の間の`"`はネストしたVB文字列リテラルの
開始/終了として扱う(知見65の`render.py`の`_split_interpolated_string`
と同じ発想だが、あちらは既に境界が確定した生テキストの*分割*用、
こちらはLarkに渡す前の境界*検出*そのものが目的という違いがある)。
`_prescan_interpolated_strings()`が`parse_vb_expr()`内で`Lark.parse()`の
直前に呼ばれ、見つかった`$"..."`区間を不透明なプレースホルダ
(`$"INTERP<n>"`、`"`を含まないため既存の`INTERP_STRING`正規表現と
確実にマッチする)へ一時置換してからLarkへ渡す。パース後、
`_ExprTransformer`がプレースホルダを元の生テキストへ戻して
`InterpolatedString.raw`に格納するため、知見65で既に実装済みの
`render.py`の`_split_interpolated_string`がそのままネストした文字列
リテラルを含む式も正しく分割・コード生成できるようになった——
知見65の時点でコード生成側の能力は既にあったが、レクサ側がそもそも
境界を誤検出していたため到達できなかった、という構図。

境界が最後まで見つからない(閉じる`"`が無い等)場合は`None`を返し、
置換せず元のテキストをそのままLarkへ渡す——構文エラー→既存の
`(None, raw_text)`フォールバックに安全に委ねる(でっち上げた置換は
しない)。

`tests/test_uipath_expr.py`に
`test_interpolated_string_with_nested_quoted_literal_still_parses`
(公式ドキュメント自身の`If(age = 1, "", "s")`の例そのもの)、
`test_interpolated_string_with_multiple_nested_quoted_literals_parses`
(`{expr}`が複数ある場合にプレースホルダの取り違えが無いこと)、
`test_unterminated_interpolated_string_falls_back_safely`
(閉じる`"`が無い場合に安全にフォールバックすることの回帰テスト)を
追加。`tests/test_uipath_codegen.py`の
`test_interpolation_with_nested_quoted_expression_still_falls_back_to_todo`
は前提(「このケースは`# TODO`に倒れる」)がこの修正で偽になったため、
`test_interpolation_with_nested_quoted_expression_now_renders_correctly`
へ置き換え、実際に`exec()`して`"Alice is old."`という正しい実行結果に
なることまで確認する内容に強化した。UiPath関連テスト全207件通過、
リポジトリ全体で全825件通過。

**この知見で確定したこと**: 知見65から知見66まで、2つのtickに分けて
段階的に実装した(知見65でコード生成側の能力を先に作り、知見66で
その能力に到達できるようレクサ側の限界を解消)——一度に両方を実装
しようとせず、知見65の時点で明示的に「今回は見送った」と記録して
おいたことで、次のtickでスコープが明確なまま着手できた。文字列補間の
既知の残課題はこれで解消し、現時点で残るのは書式指定子・フィールド幅
(`{expr:format}`/`{expr,width}`、知見65参照、VBの書式指定子の対応表が
確証不足のため意図的に未対応のまま)のみ。

## 67. `CDbl`/`CInt`/`CBool`の`&H`/`&O`16進・8進リテラル文字列非対応を解決——知見46・53で「軽微な既知の限界」として記録していた残課題を.NETランタイム本体の別ファイルで確定(VM不使用)

知見46(`CStr`修正時)・知見53(`CInt`のクロスチェック時)で繰り返し
「`&H`/`&O`16進・8進リテラル文字列の非対応のみ軽微な既知の限界として
残る」と記録していた項目(`CDbl("&H1A")`/`CInt("&H1A")`/`CBool("&H1A")`
が通常の数値文字列としてパースされ`ValueError`になってしまう問題)を、
.NETランタイム本体のソースで確定・解決した。

**確認したソースファイル**: `Microsoft.VisualBasic.CompilerServices.
Conversions`(`DoubleType.FromString`/`IntegerType.FromString`/
`BooleanType.FromString`、知見52・53で確認した`Conversions.vb`/
`DoubleType.vb`/`IntegerType.vb`/`BooleanType.vb`)がいずれも文字列引数を
`ParseDouble`(知見52の`NumberStyles.AllowThousands`経由)に渡す**前**に
`Microsoft.VisualBasic.CompilerServices.Utils.IsHexOrOctValue`
(`dotnet/runtime`リポジトリの`Utils.LateBinder.vb`——`IsHexOrOctValue`
自体の定義は`Conversions.vb`や`Utils.vb`ではなく`Partial Class Utils`の
別ファイル`Utils.LateBinder.vb`にあった、GitHub code search(`gh api
search/code`)で発見)を呼んでいることを確認した。

**確定した規則**(`IsHexOrOctValue`): 先頭の半角空白(`chSpace`=`ChrW(32)`)
・全角空白(`chIntlSpace`=`ChrW(&H3000)`、Pythonの`str.strip()`は既定で
どちらも空白として扱うため追加対応不要)をスキップした後、`&`に続けて
`H`/`O`(大文字小文字区別無し)+1文字以上の数字が続く場合のみ該当し、
`ParseDouble`を経由せず`Convert.ToInt64(残りの文字列, 16 または 8)`で
直接整数へ変換する——それ以外の文字(`&B`の2進リテラル等)が続く場合は
`FormatException`になる(2進リテラル文字列はUiPathの実データで使われる
実例が無いため今回も対象外のまま、同じ判断基準は知見50・52の
「実例が無い書式は優先度低」と同じ)。`CBool`/`CInt`はこの関数が返した
Int64値をそれぞれ`CBool(Int64)`/`CInt(Int64)`相当(`!= 0`/切り捨て)で
後処理するのみ。

**修正内容**(`dump_daemon/uipath_codegen/render.py`): `VB_CDBL_HELPER_
SOURCE`(`_vb_cdbl`、`CInt`も`round(_vb_cdbl(x))`経由で再利用するため
自動的に修正される)と`VB_BOOL_HELPER_SOURCE`(`_vb_bool`)の文字列分岐
それぞれに、`ParseDouble`相当の通常パースより先に`&H`/`&O`判定を追加
(自己完結ヘルパーの既存方針上、ロジックを2箇所に複製)。コード生成時の
リテラル専用判定`_vb_cbool_of_string_literal`(知見63)にも同じ判定を
共有関数`_parse_vb_hex_or_oct_str`(render.py内のみで使う、生成コードへは
注入されない通常のPython関数)経由で追加し、ランタイム版と規則を揃えた
(知見63で「揃えないと不整合になる」と学んだ教訓をそのまま適用)。

`tests/test_uipath_codegen.py`の既存パラメトライズ(`test_cint_matches_
dotnet_runtime_source_for_nothing_and_thousands`・
`test_cbool_string_literal_matches_vb_semantics_not_python_truthiness`)に
`&H1A`/`&O17`系のケースを追加、新規`test_hex_or_oct_literal_string_via_
variable_matches_runtime_helpers`で変数経由(コード生成時に文字列と確定
しない場合)のランタイム版ヘルパーも同じ規則に従うことを確認。UiPath
関連テスト全215件通過、リポジトリ全体で全835件通過。

**この知見で確定したこと**: 知見46・53で2回にわたって「軽微な既知の
限界」として先送りしていた項目でも、`gh api search/code`でリポジトリ
全体を検索すれば定義元ファイルが`Conversions.vb`とは別の場所
(`Utils.LateBinder.vb`)にあることまで含めて確定でき、VM無しで解決
できた——「確度の高いソース」技法(知見52以来)はファイル境界を越えた
検索にも有効だと実証された。

## 68. 演算子ディスパッチャ(`+`/`-`/`*`/`/`/`Mod`/比較)の文字列オペランドも`&H`/`&O`16進・8進リテラルとして解釈されると確定——知見67のCDbl/CInt/CBool限定の修正を演算子側にも波及(VM不使用)

知見67で`CDbl`/`CInt`/`CBool`の`&H`/`&O`16進・8進リテラル文字列対応を
解決した直後、同じ日に既に取得済みだった`Operators.vb`(知見54・59で
`AndObject`/`XorObject`等を確認した同じファイル)を今回の観点
(「文字列オペランドをどう数値へ変換しているか」)で再確認したところ、
`AddObject`/`SubtractObject`/`MultiplyObject`/`DivideObject`/
`ModObject`/`CompareObjectEqual`のいずれも、文字列オペランドの変換に
`CDbl(Convert.ToString(x))`——知見67で対応した、まさに同じ
`Conversions.ToDouble`経路を使っていると判明した。つまり`"&H1A" + 1`や
`"&H1A" = 26`のような式も、実機では`&H1A`を16進リテラルとして解釈した
上で演算される——知見67は型変換関数(`CDbl`/`CInt`/`CBool`)のみを対象に
していたため、この演算子側の同じ食い違いは見過ごされたまま残っていた。

**修正内容**(`dump_daemon/uipath_codegen/render.py`): `_vb_cmp`
(比較)・`_vb_add`(`+`)・`_vb_num`(`-`/`*`/`\`/`^`の単項正規化)・
`_vb_div`(`/`)・`_vb_mod`(`Mod`)の5ヘルパーすべてに、知見67の`_vb_cdbl`
と同じ`&H`/`&O`判定ロジックを追加した。`_collect_imports`(`uipath_
codegen/__init__.py`)が生成コードに文字通り現れるヘルパー名だけを検知
する仕組み上、各ヘルパーが`_vb_cdbl`を直接呼ぶ構造にはできない(知見50で
`_vb_div`を`_vb_num`に依存させない自己完結設計にした理由と同じ制約)ため、
`_vb_cmp`/`_vb_add`/`_vb_div`/`_vb_mod`には局所関数`_s2f`(string-to-float)
を定義して複製し、単一オペランドの`_vb_num`には直接インライン化した。

`tests/test_uipath_codegen.py`に
`test_hex_or_oct_literal_string_in_arithmetic_operators`
(`"&H1A" + 1`→`27`等)・
`test_hex_or_oct_literal_string_in_comparison_operators`
(`"&H1A" = 26`→`True`等)を追加。UiPath関連テスト全224件通過、
リポジトリ全体で全844件通過。

**この知見で確定したこと**: 知見52以来のパターン(1つの変換関数で見つけた
食い違いを、同じファイル内の類似関数へ追い打ちで確認する、知見53・67)を
さらに一段広げ、「型変換関数(`Conversions.vb`)で見つけた食い違いが、
別ファイル(`Operators.vb`)の演算子ディスパッチャにも波及しているか」を
確認する視点が有効だと実証した——型変換関数と演算子ディスパッチャが
内部で同じ変換経路(`CDbl`)を共有している以上、片方だけ直して満足せず
もう片方も確認する価値がある。

## 69. 文字列補間の`{expr}`内部にさらに別の補間文字列をネストしたケース(`$"outer {$"inner {x}"}"`)も、既存設計のまま追加実装無しで正しく動作すると確認(VM不使用、検証のみ)

知見65・66の設計時点では、`{expr}`内部にさらに別の補間文字列`$"..."`が
書かれるケース(例: `$"outer {$"inner {x}"}"`)を「範囲外」として明示的に
検証していなかった(知見65の作業ログでは一旦「VMで確認するまで保留」と
位置づけていた)。今回、でっち上げた「対応済み」の主張を避けるため実際に
`exec()`して動作を確認したところ、**追加の実装無しで既に正しく動作する**
と判明した。

**理由**: (1)`uipath_expr`の`_find_interp_string_span`(知見66)は`{`/`}`
の深さだけを追跡する状態機械で、`$`自体を特別扱いしない——内側の`$"..."`
の`"`は単に「ネストした文字列リテラル」の開始/終了としてそのまま扱われ、
外側の境界検出に影響しない。(2)`render.py`の`_render_interpolated_string`
(知見65)は各`{expr}`セグメントを`parse_vb_expr()`で再帰的に解析し
`_render_node()`で再帰的にレンダリングする設計のため、内側の式が
たまたま別の`InterpolatedString`であっても、再帰呼び出しが自然に
処理する——特別扱いするコードを書いた記憶は無く、既存の再帰構造の
副作用として動いていた。

`tests/test_uipath_expr.py`に
`test_interpolated_string_nested_inside_another_interpolated_string_
boundary_detected`(レクサの境界検出)、`tests/test_uipath_codegen.py`に
`test_interpolated_string_nested_inside_another_interpolated_string_
renders_correctly`(`exec()`で`"outer inner 5"`になることまで確認)を
追加。UiPath関連テスト全226件通過、リポジトリ全体で全846件通過。

**この知見で確定したこと**: 「これは範囲外のはず」という推測を実際に
テストで検証する価値があると実証した——検証せずに「対応していない」と
決めつけていたら、既に正しく動いている機能を誤って「既知の限界」として
記録してしまうところだった(知見65・66の「でっち上げない」方針は、
未対応の主張についても同じ厳密さを要求する)。

## 70. `uipath_codegen`のカバレッジ測定ツールを新規作成——`design/uipath_transpiler_roadmap.md` Phase 4が明記していたが未着手だった`codegen_coverage.py`相当の整備を実施、現状72%(21/29)を実測(VM不使用)

`design/uipath_transpiler_roadmap.md`のPhase 4は「PAD側の`codegen_coverage.py`
のようなカバレッジ測定ツールを作り、優先度順に埋めていく」と明記していたが、
UiPath側ではこのツール自体がまだ作られていなかった(PADの`dump_daemon/
codegen_coverage.py`は`pad_codegen`専用で、UiPath側を一切カバーしない)。
知見42〜69の系統的な演算子/型変換関数の修正が一段落したところで、この
明示的に積み残っていたロードマップ上の約束に着手した。

**実装**(`dump_daemon/uipath_codegen_coverage.py`、新規ファイル):
PAD版`codegen_coverage.py`と同じ設計方針——`uipath_codegen`の内部関数を
直接呼ばず公開関数`generate_python()`だけを使う、コンテナ型ノード
(`IfNode`/`SwitchNode`/`TryCatchNode`/`WhileNode`/`DoWhileNode`/
`ParallelNode`/`ExcelApplicationScopeNode`)は子を空にした最小限のコピーに
差し替えて測定する(子自身のカバレッジは再帰で別途測定済みのため、親の
分岐点自身の分類に混ざらないようにする)。対象は実機確認済みのXAML
フィクスチャ(`design/evidence/uipath_xaml_probe/Main.xaml`/`Sub1.xaml`、
知見1〜36でUiPath Studio実機コンパイル確認したもの)を`parse_workflow_file()`
で読み込み、その木構造を実際に歩く——でっち上げたテストデータではなく実機
確認済みの構造一式に対する実測値になる。

**測定結果**: 29分岐点中21件(72%)が実コードを生成できる。TODOに倒れる
残り8件のうち、`DoWhileNode(no condition)`・`InvokeWorkflowFileNode`
(単体`generate_python()`呼び出しでは`invoke_resolver`無しのため常にTODO、
`generate_project_python()`経由なら解決される仕様通りの挙動)・
`UnknownActivityNode`(Libraryの`NewActivity`、v1スコープ外と確定済み)は
いずれも既知の仕様通り。残る5件——`ExcelApplicationScopeNode`/
`ExcelWriteCellNode`/`HttpClientNode`/`InvokeCodeNode`/
`SendOutlookMailNode`——は、Phase 1で「Tier1相当」と確定した活動一式に
含まれているにもかかわらず、`_generate_unresolved_activity`
(`uipath_codegen/__init__.py`、「インラインコード・ライブExcel/Outlook
連携・`HttpClient`のHeaders等プロパティ要素未パース」と明記済み)へ
ルーティングされ、常に`# TODO`に倒れる——これは今回新たに見つかったバグ
ではなく、既存のコメントが明記していた**既知の、意図的な**先送りである
ことを数値で確定させた(でっち上げた「対応済み」の主張を避けるための
正確な現状把握)。

`tests/test_uipath_codegen_coverage.py`に、カバレッジが72%を下回ったら
失敗する回帰テストと、上記5件が一貫してTODO判定になることを固定する
テストを追加。UiPath関連テスト全228件通過、リポジトリ全体で全849件通過。

**この知見で確定したこと**: Phase 4の「カバレッジ測定ツール」という
積み残しのタスクそのものに着手することで、「どの活動が実際にコード生成
できるか」を印象ではなく数値で把握できるようになった——次にTier1活動の
実装を進める際(Excel/Outlook連携・HttpClientのHeaders/Body対応等)は、
このツールで進捗を定量的に追跡できる。

## 71. `ui:Click`の`ClickType`/`MouseButton`/`KeyModifiers`属性が一切キャプチャされず常に単純な左シングルクリックとして生成される未検出のギャップを発見・部分的に解決(VM不使用、知見70のカバレッジツール実装の副産物)

知見70のカバレッジ測定ツールを実装する過程で`Main.xaml`の実際のXML属性を
再確認していたところ、`ClickNode`(`dump_daemon/uipath_dsl/types.py`)が
`selector`/`display_name`の2つしかフィールドを持たず、実機XAMLに存在する
`ClickType`/`MouseButton`/`KeyModifiers`属性(`<ui:Click ... ClickType=
"CLICK_SINGLE" ... KeyModifiers="None" MouseButton="BTN_LEFT">`、
`design/evidence/uipath_xaml_probe/Main.xaml`181行目)が完全に無視され、
`_generate_click`が常に無条件で`.click_input()`(pywinauto既定=左シングル
クリック)を生成すると判明した——`HttpClientNode`の`extra_attrs`のような
素通し機構も無く、ダブルクリック・右クリック・修飾キー併用のフローが
実在すれば、生成コードが**サイレントに間違った種類のクリックを実行する**
(クラッシュも警告も無い、既存の`# TODO`方針より発見しにくい種類のバグ)
というリスクがあった。

**確認できたこと**(実機XAML、知見のみ——ドキュメント不使用): 上記1件の
具体例(`ClickType="CLICK_SINGLE"`/`MouseButton="BTN_LEFT"`/
`KeyModifiers="None"`)のみ。ダブルクリック・右クリック・修飾キー併用時の
実際のシリアライズ文字列(`CLICK_DOUBLE`/`BTN_RIGHT`等、おそらくこの命名
規則通りだが未確認)は実機でも公式ドキュメントでも確認できていない。
pywinautoの`click_input(button='left'|'right'|'middle'|'x', double=bool,
pressed="control shift alt"の空白区切り部分文字列)`(`pywinauto/windows/
mouse.py`、GitHub実ソースで確認)は確認済みだが、UiPath側の文字列との
正確な対応表が無い状態でマッピングをでっち上げるのは危険と判断した。

**修正内容**: `ClickNode`に`click_type`/`mouse_button`/`key_modifiers`
(いずれも生テキストのまま)を追加し、`xaml_tree.py`の`_parse_click`で
素通しキャプチャする(データを失わない、`pad_codegen`と同じ方針)。
`_generate_click`は、これら3属性が実機確認済みの唯一の値(または属性
省略=`None`)と完全一致する場合のみ従来通り`.click_input()`を生成し、
それ以外の値を検出した場合は`# TODO: Click with non-default ClickType/
MouseButton/KeyModifiers (...) — mapping not confirmed via real capture,
refusing to guess`へ倒す——`uipath_selector`の`role`属性と同じ「無言で
でっち上げるより安全側に倒す」方針を踏襲し、確認済みの既定値のケースは
挙動を一切変えない(既存の回帰テスト全件が無修正で通過することで確認済み)。

`tests/test_uipath_dsl.py`の`test_click_selector`に3属性の捕捉確認を追加、
`tests/test_uipath_codegen.py`に確認済み既定値(属性明示/省略の両方)で
`.click_input()`が生成されるテストと、非既定値3パターンで`# TODO`へ倒れる
テストを追加。UiPath関連テスト全233件通過、リポジトリ全体で全854件通過
(知見70のカバレッジは72%のまま——実機フィクスチャの実例が確認済みの
既定値そのものだったため、数値上の変化は無い)。

**この知見で確定したこと**: 知見70のカバレッジツール自体は「TODO/エラーに
倒れる分岐点」しか可視化しないため、「サイレントに間違った値を生成する」
種類のギャップ(今回のClick属性のように、これまで一度も`#TODO`にならず
誰にも気づかれなかった)はカバレッジ測定だけでは見つからない——ツールを
作る作業中に実際のXML属性を手で読み返す過程で偶然見つかった。今後も
「カバレッジ100%」を最終目標にせず、実機属性の再読み込みによる
サイレントギャップの発見を継続する価値があると確認した。

## 72. `ui:InvokeWorkflowFile`の`ContinueOnError`属性が無視され、`True`設定時に意図しない例外伝播を起こすギャップを発見・安全側に倒して解決(VM不使用、知見71と同じ「実機属性の再読み込み」で発見)

知見71でClick属性の再確認を行った際と同じ手法(実機XAMLの全属性を
grepで再確認)を他のサポート済みアクティビティにも適用したところ、
`ui:InvokeWorkflowFile`/`ui:HttpClient`/`ui:InvokeCode`の3要素のみが
`ContinueOnError`属性を持つと判明した(`MessageBox`/`Click`/`AppendLine`
等には存在しない、全アクティビティ共通ではなく一部のみの属性)。
`HttpClient`/`InvokeCode`は知見70で確認済みの通りそもそも全体が
`# TODO`に倒れる(影響無し)が、**実際にコード生成される
`InvokeWorkflowFileNode`だけ**は`ContinueOnError`を一切キャプチャせず、
常に単純な関数呼び出し(例外はそのまま伝播)を生成していた——
`ContinueOnError="True"`の実例が存在すれば、VBでは例外を無視して継続
するはずのフローが、生成Pythonコードでは例外でクラッシュするという
サイレントな食い違いになる。

**確認できたこと**(実機XAML、`Main.xaml`203行目): `ContinueOnError=
"{x:Null}"`(未設定)の1例のみ。`True`設定時に「継続する」とは具体的に
何を意味するか(呼び出し先のOut引数はどうなるか等)は実機でも公式
ドキュメントでも確認していない。

**修正内容**: `InvokeWorkflowFileNode`に`continue_on_error: Expr`
(知見13と同じ`_attr_expr`経由、`{x:Null}`→`None`)を追加。
`_generate_invoke_workflow_file`は、この値が確認済みの安全な値
(`None`=未設定、または明示的な`Literal("False")`——いずれも現在の
「伝播させる」挙動と一致)の場合のみ従来通り関数呼び出しを生成し、
それ以外(`"True"`等)を検出した場合は`# TODO`へ倒す(でっち上げた
try/except変換はしない、知見71の`ClickType`と同じ方針)。

`tests/test_uipath_dsl.py`の`test_invoke_workflow_file`に`None`判定の
確認を追加、`tests/test_uipath_codegen.py`に確認済み安全値(`None`/
`"False"`)で関数呼び出しが生成されるテストと`"True"`で`# TODO`へ倒れる
テストを追加。UiPath関連テスト全236件通過、リポジトリ全体で全857件通過
(知見70のカバレッジは72%のまま、実機フィクスチャの実例が確認済みの
安全値そのものだったため変化無し)。

**この知見で確定したこと**: 知見71の「実機属性を再読み込みして見つけた
サイレントギャップ」という発見パターンが単発ではなく再現可能な手法だと
確認した——`ContinueOnError`のように一部のアクティビティにしか付かない
属性もあるため、1つの属性名の存在確認だけで「全アクティビティ共通の
属性」と決めつけず、実際に`grep`で各要素ごとの出現有無を確認する必要が
あった(今回は3要素のみ、かつそのうち実際にコード生成されるのは
`InvokeWorkflowFileNode`1件のみという、想定より狭い影響範囲だった)。

## 73. `ui:Click.CursorPosition`の`Position`属性も同じ「サイレントに無視される」パターンと確認、知見71と同じ方針で解決(VM不使用)

知見71で`ui:Click`の`ClickType`/`MouseButton`/`KeyModifiers`属性を扱った
際、同じ要素の子プロパティ要素`ui:Click.CursorPosition`配下の
`ui:CursorPosition Position="Center"`も一切キャプチャされていないことに
気づいた(`Main.xaml`181〜191行目)。`Position`はクリック対象要素の
どこを狙うか(中心/四隅等)を指定するプロパティで、`OffsetX`/`OffsetY`は
`Position="Custom"`時のみ意味を持つと推定される(今回のフィクスチャでは
両方とも値の無い空の`InArgument`)。

**確認できたこと**: `Position="Center"`の1例のみ。これはpywinautoの
`click_input()`の既定動作(座標未指定時はターゲット要素の中心、
`win_base_wrapper.py`で確認済み——知見71参照)と一致するため、現状の
コードは**偶然ではなく確認済みの意味で**正しい。`"TopLeft"`等の他の値や
`Custom`時のオフセット座標への変換は未確認。

**修正内容**: `ClickNode`に`cursor_position`(`Position`属性の生テキスト)
を追加、`_generate_click`は`cursor_position`が`None`または`"Center"`の
場合のみ従来通りコードを生成し、それ以外は`# TODO`へ倒す(知見71の
`ClickType`等と全く同じ方針)。`OffsetX`/`OffsetY`は`Position`が
`"Center"`以外なら`# TODO`に倒れるため素通りで失っても実害が無く、
今回は捕捉しない(でっち上げた座標変換よりシンプルな方を選んだ)。

`tests/test_uipath_dsl.py`の`test_click_selector`に捕捉確認を追加、
`tests/test_uipath_codegen.py`に確認済み既定値(`None`/`"Center"`)と
非既定値(`"TopLeft"`)のテストを追加。UiPath関連テスト全239件通過、
リポジトリ全体で全863件通過(知見70のカバレッジは72%のまま、実機
フィクスチャが確認済みの安全値そのものだったため変化無し)。

**この知見で確定したこと**: 知見71・72・73は同じパターンの繰り返し
(実機属性を再読み込み→未キャプチャの属性/子要素を発見→確認済みの
安全な値のみ許可し、それ以外は`# TODO`)——1つの活動の属性を調べる
作業で別の属性/子要素の存在にも自然に気づくことが多く、1回の調査で
複数の知見が連鎖的に見つかるパターンが定着してきた。`ui:Click`自体には
まだ`AlterIfDisabled`/`CursorMotionType`/`DelayBefore`/`DelayMS`/
`SendWindowMessages`/`SimulateClick`という、今回のフィクスチャでは
全て`{x:Null}`(未確認)の属性が残っている——実データでの非既定値使用
実例が無いため、知見46のEncoding同様、優先度を下げて未対応のまま記録する。

## 74. 配列/コレクション/DataTable行アクセスの`識別子(引数)`構文が関数呼び出しと言語レベルで曖昧——現状は安全に`# TODO`へ倒れることを確認・ロック(VM不使用、新規発見)

知見71〜73のアクティビティ属性調査から離れ、`uipath_expr`の式パーサー
自体をあらためて見直していたところ、VB.NETには構文上の重大な曖昧性が
あると気づいた——配列のインデックスアクセス(`myArray(0)`)・
コレクション/辞書アクセス(`myDict("key")`)・`DataTable`の行アクセス
(`row("ColumnName")`)は、いずれも関数呼び出し(`CStr(x)`等)と**全く
同じ**`識別子(引数)`構文を使う。VB.NET自身もこれを静的な型解決(識別子が
変数か関数かの判定)で区別しており、**構文だけでは判別不可能**——これは
`uipath_expr`の実装の不備ではなく、VB.NET言語そのものの構文的な特徴。

**現状の挙動を確認**: `uipath_expr`は常に`FuncCall`として解釈するため、
`myArray(0)`のような式は`_render_func_call`に渡り、`myArray`がTier1の
確認済み関数名(`CStr`/`CInt`/`CDbl`/`CBool`等)のいずれでもないため
`NotImplementedError`→既存の安全なフォールバックで`# TODO`に倒れる
(`x = None`)——「配列インデックスのはず」と推測して架空の`myArray[0]`
変換をでっち上げることはしていない。チェーンされた形
(`dt.Rows(i)("Col")`、呼び出し結果への再呼び出し)はそもそも文法が
対応しておらず、構文解析自体が失敗して安全にフォールバックする
(知見36時点から既知のこの文法の制約がここでも安全網として働いている)。

**解消する設計の方向性(今回は実装しない)**: `Sequence.Variables`/
`WorkflowFile.arguments`等で宣言済みの変数名の集合を`_render_node`系の
関数へスコープを意識せずに(過大近似で十分安全、同一ファイル内のどこかで
変数として宣言されていれば関数名との衝突はVB.NET的にまず起きない)渡し、
識別子がその集合に含まれる場合のみ`識別子(引数)`を添字アクセス
(`識別子[引数]`、複数引数ならタプル添字等要検討)として解釈する、という
設計が考えられる。ただし`_render_node`/`render_expr`等の呼び出し経路
全体にスコープ情報を通す変更が必要で、実機で配列/`DataTable`アクセスを
使うフローの実例が今のところ無いため、今回は見送り、現状の安全な
`# TODO`フォールバックをロックする回帰テストのみ追加した。

`tests/test_uipath_codegen.py`に
`test_array_or_collection_indexing_syntax_is_ambiguous_with_func_call_falls_back_to_todo`
を追加。UiPath関連テスト全240件通過、リポジトリ全体で全864件通過。

**この知見で確定したこと**: 知見71〜73の「実機属性の再読み込み」とは
別の発見経路(式パーサー自体の設計を見直す)でも、新しい(ただし現状は
安全に処理されている)言語レベルの考慮事項を見つけられた——全てのギャップ
が「サイレントに間違ったコードを生成する」種類とは限らず、今回のように
「既に安全側に倒れているが、その理由と限界を明文化する価値がある」
種類の発見も重要だと再確認した。

## 75. 知見70で発見した5つの未対応アクティビティの`# TODO`コメントに捕捉済みフィールドを追記——人間が手動でポートする際の手がかりを増やす(VM不使用、でっち上げ無しの改善)

知見70のカバレッジツールが`# TODO: unsupported in v1 codegen:
ExcelApplicationScopeNode`のように型名しか出力しないことに気づいた
——これは安全だが、人間が後でこのTODOを手動実装する際、元の`.xaml`に
戻って`WorkbookPath`やメール送信先等を確認し直す必要があった。
`uipath_dsl`のパーサーは既にこれらのフィールド(`InvokeCodeNode.code`・
`ExcelApplicationScopeNode.workbook_path`・`ExcelWriteCellNode.cell`/
`sheet_name`・`SendOutlookMailNode.to`/`subject`・`HttpClientNode.
endpoint`/`method`)を素通しで捕捉済みなので、これをコメントに追記する
だけで実装の難易度を上げずに手がかりを増やせる。

**修正内容**(`dump_daemon/uipath_codegen/__init__.py`):
`_generate_unresolved_activity`に`# TODO: unsupported in v1 codegen:
InvokeCodeNode (Code='content=content.ToUpper()')`のような詳細を追記。
`Expr`型(`VbExpr`/`Literal`/`None`)フィールドの説明には新規
`_describe_expr_for_comment()`を使う——既存の`render_expr()`(実行可能
Pythonコードへの変換を試み、失敗時に`NotImplementedError`を送出する)
とは別に、常に例外を出さない`repr()`ベースの素朴な表現に留める(既に
`# TODO`に倒れている活動の説明文生成でさらに別の`# TODO`を誘発しない
ため)。コード生成の判断自体は変えない、純粋にコメントの情報量を増やす
だけの変更。

`tests/test_uipath_codegen.py`に
`test_unresolved_activity_todo_includes_captured_fields`
(5種類すべてをパラメトライズ)を追加。UiPath関連テスト全245件通過、
リポジトリ全体で全870件通過。知見70のカバレッジツール自体の出力も
より具体的になった(副次的な改善)。

## 76. `TryCatch`に複数の`catches`があり、未知の.NET例外型が同じPython例外型(`Exception`)へ解決される場合、後続のハンドラが到達不能な死んだコードになる実在するバグを発見・安全側に倒して解決(VM不使用、新規発見)

知見75でTODOコメントの情報量を増やす作業を終えた後、`_generate_try_catch`
の実装をあらためて読み返していたところ、`_EXCEPTION_TYPE_MAP`の
「未知の.NET例外型は無条件で`Exception`にフォールバックする」という
既存の(意図的な)簡略化が、**`catches`が2件以上あるTryCatch**では
単なる精度の劣化では済まない、より深刻な問題を引き起こすと判明した。

Pythonの`try`/`except`は`except`節を**上から順に試し、最初にマッチした
節だけが実行される**言語仕様を持つ。VB.NETの`TryCatch.Catches`も概念上は
同様に優先順位があるが、実際の`.NET`型階層(例:
`System.IO.FileNotFoundException`は`System.Exception`のサブタイプ)に
基づいて正しくマッチする。知見確認済みの型(`s:Exception`)以外を全て
無条件で`Exception`にフォールバックする現在の実装では、「特定の例外だけ
別処理、それ以外は汎用`Exception`で処理」という極めて一般的なRPAパターン
(例: `FileNotFoundException`を個別に処理し、それ以外は汎用ログだけ出す)
が、両方とも`except Exception:`に解決されてしまい、**2番目以降の
`except`節が実行時に一度も到達しない死んだコード**になる。

**実際に`exec()`して確認**: `FileNotFoundException`用のハンドラを先に、
`System.Exception`用の汎用ハンドラを後に置いたコードを生成し実行した
ところ、常に最初の(本来は特定の例外専用だったはずの)ハンドラだけが
実行され、2番目のハンドラの出力は一度も現れなかった——サイレントに
制御フローが崩れることを実証した。

**修正内容**(`dump_daemon/uipath_codegen/__init__.py`の
`_generate_try_catch`): `catches`が2件以上の場合、各`catch`が
`_EXCEPTION_TYPE_MAP`経由で解決するPython例外型の集合に重複が無いかを
事前に確認する。重複がある場合(今回のような未知型同士のフォールバック
衝突を含む)、でっち上げた.NET例外階層への精密対応(v1スコープ外)をする
代わりに、`try_body`も含めてTryCatch全体を`# TODO`へ倒す——`try_body`
だけ正しく動くが`except`の意味が壊れた中途半端なコードを生成するより、
全体を安全側に倒す判断。1件のみの`catches`(実機確認済みの`Main.xaml`の
実例)は影響を受けない。

`tests/test_uipath_codegen.py`に
`test_try_catch_with_multiple_catches_resolving_to_distinct_types_still_generates`
(安全策が過剰に広く効かないことの確認)、
`test_try_catch_with_colliding_exception_types_is_todo_not_silently_shadowed`
(実際にバグを再現した上で`# TODO`へ倒れることの確認)を追加。UiPath
関連テスト全247件通過、リポジトリ全体で全872件通過(知見70のカバレッジは
72%のまま、実機フィクスチャが単一`catch`のみだったため変化無し)。

**この知見で確定したこと**: 知見74の「言語レベルの曖昧性」と似て、今回も
実機属性の再読み込みではなく既存コードの実装そのものを読み返す
(「この簡略化が複数件の文脈でどう振る舞うか」を具体的に`exec()`で
確認する)ことで見つかった——知見70〜75の「実機属性を調べる」とは別の、
「既存のでっち上げ防止ロジックが単体では正しくても、複数件が組み合わさる
と壊れないか」という第3の発見経路が有効だと確認した。

## 77. `Switch`の`Case`比較が`=`演算子と同じ型変換規則に従うと公式ドキュメントで確定——素の`==`のままだった食い違いを解決(VM不使用、知見76と同じ「既存コードの読み返し」で発見)

知見76で`_generate_try_catch`を読み返した直後、同じ観点(「この簡略化は
複数の文脈で本当に正しいか」)を`_generate_switch`にも適用したところ、
`Switch`の`Case`比較が素のPython `==`のままで、`=`演算子用の`_vb_cmp()`
(知見47、数値/文字列混在オペランドの型変換)を経由していないことに
気づいた。

**確認した公式ドキュメント**(Microsoft Learn「Select...Case
Statement」、VM不使用): Remarksが「`Case expression`という形は
`testexpression = expression`として評価される`Is`形の特殊形」と明記——
つまり`Select Case`の各`Case`比較は**`=`演算子と全く同じ型変換規則**に
従うはずだった。

**実際に`exec()`して確認**: `Switch`の`Expression`が`type_arguments`の
宣言(`x:Int32`)とは異なり実行時に文字列型の値(`"1"`)を実際に保持して
いる場合、修正前のコードは`"1" == 1`という素の比較になり`False`
(Pythonは暗黙の数値/文字列変換をしない)——対応する`Case`アームが
実行されず、意図した分岐が丸ごとスキップされることを実際に再現した。
VBでは`=`演算子の規則により`"1" = 1`は`True`になるはずの比較だった。

**修正内容**(`dump_daemon/uipath_codegen/__init__.py`の
`_generate_switch`): 比較を`(lambda _t: _t[0] == _t[1])(_vb_cmp(expr,
key_literal))`——`_render_bin_op`の`=`演算子と全く同じレンダリング形へ
統一した。`key_literal`自体のレンダリング(`_render_switch_key`、数値型は
裸のリテラル・それ以外は文字列リテラル)は変更していない——`_vb_cmp`が
既にそのどちらの形でも正しく型変換できるため、`key_literal`の形自体を
変える必要が無かった。

既存の`test_switch_with_int_typed_keys`/`test_switch_with_string_typed_keys`
(生成コードの正確な文字列を検証していたため、この修正で形が変わり
更新が必要になった)を新しい形に追従させ、新規
`test_switch_comparison_matches_vb_select_case_semantics_not_python_bare_equality`
で実際にバグを再現した上で修正後に正しく一致することを確認。UiPath
関連テスト全248件通過、リポジトリ全体で全873件通過(知見70のカバレッジは
72%のまま、実機フィクスチャの`Switch`の`Expression`は実際に`x:Int32`型
変数だったため影響無し)。

**この知見で確定したこと**: 知見76で見つけた「既存のでっち上げ防止ロジック
を複数の文脈で再検証する」という発見経路が、1回限りではなく連続して有効
だと実証した——`TryCatch`の次に`Switch`を見直したところすぐにもう1件
見つかった。この系統の検証(「この演算は本当に対応する演算子の変換規則に
従っているか」)を他の構文(`If`/`While`等の条件式——知見61で既に`_vb_bool`
統一済み、`ForEach`の`Values`——単純な反復なので対象外)にも適用する価値が
あるが、`If`/`While`/`DoWhile`/三項`If`は既に知見61で確認済みのため、残る
候補は今のところ見当たらない。

## 78. ワークフロー引数の`OutArgument`/`InOutArgument`方向がPythonの値渡しパラメータでは呼び出し元への書き戻しを実現できないと確認・`# TODO`で明示(VM不使用、新規発見)

知見76・77の「既存コードの読み返し」を`generate_python()`自体にも
適用したところ、`workflow.arguments`(`<x:Members><x:Property Name="..."
Type="InArgument(x:String)" /></x:Members>`、知見12)の値が
`InArgument(...)`/`OutArgument(...)`/`InOutArgument(...)`という方向
付きの型文字列であるにもかかわらず、`generate_python()`がこの方向を
一切見ず、全ての引数を単純に`def func(arg1, arg2, ...):`の値渡し
パラメータとして扱っていると判明した。

VB.NETの`OutArgument`/`InOutArgument`は、呼び出し元の変数を関数終了後に
更新する(ByRef相当の)渡し方——`Invoke Workflow File`で`[myVar]`を
`OutArgument`の`x:Key`に束縛した場合、呼び出し先が値を設定すると
`myVar`が更新される、という挙動がVBの意味論として期待される。一方
Pythonの関数パラメータは常に値渡しで、関数内での再代入は呼び出し元に
一切伝播しない——`return`文も呼び出し側での変数再束縛も生成していない
現在の実装では、この書き戻しがサイレントに失われる。

**確認できたこと**: 実機確認済みのフィクスチャ(`Sub1.xaml`)の引数は
`in_text`(`InArgument(x:String)`)の1件のみで、`Out`/`InOut`方向の実例は
無い——この知見は実機属性ではなく型文字列自体から直接確定できる
(言語レベルの事実であり実機確認を要しない)。

**修正内容**(`dump_daemon/uipath_codegen/__init__.py`の
`generate_python`): `workflow.arguments`の値が`OutArgument`/
`InOutArgument`で始まる引数名を検出し、関数本体の先頭に`# TODO`を
1行追記する——架空の`return`文/呼び出し側変換をでっち上げる代わりに、
この限界を明示する。関数自体の生成は継続する(`In`方向の引数は正しく
機能するため、全体を`# TODO`に倒す必要は無い)。

`tests/test_uipath_codegen.py`に
`test_workflow_out_or_inout_argument_warns_about_unsupported_byref_writeback`
(`OutArgument`/`InOutArgument`両方をパラメトライズ)、
`test_workflow_in_argument_only_has_no_byref_warning`(`InArgument`のみ
なら警告が出ないことの確認)を追加。UiPath関連テスト全251件通過、
リポジトリ全体で全876件通過(知見70のカバレッジは72%のまま、実機
フィクスチャが`InArgument`のみだったため変化無し)。

**この知見で確定したこと**: 知見76・77の「既存コードの読み返し」という
発見経路を、個々のノード生成関数(`_generate_try_catch`/
`_generate_switch`)だけでなく、トップレベルの`generate_python()`自体
(関数シグネチャ・引数の扱い)にも適用する価値があると実証した——
「この簡略化がVBの意味論と本当に一致しているか」を各レイヤーで
問い直す姿勢が継続して有効だった。

## 79. `ui:MessageBox`の`Caption`が捕捉済みなのに生成コードで一度も使われていなかった——`print()`の出力に含めて情報を活かす(VM不使用、知見78に続く「既存コードの読み返し」)

知見76〜78で見つけたバグ3件とは異なり、今回見つけたのはバグではなく
「データの未活用」。`MessageBoxNode.caption`(`ui:MessageBox`の
`Caption`属性、ダイアログのタイトルバー文字列)は`xaml_tree.py`で既に
捕捉されているが、`_generate_message_box`は`node.text`だけを
`print()`に変換し、`node.caption`を完全に無視していた。

実機フィクスチャ(`Main.xaml`)の`Caption`は全て`{x:Null}`(未設定)で、
これまでこの未活用が問題を起こすことは無かった——知見71(Click属性)・
知見73(CursorPosition)と同じ「現状は安全だが情報を失っている」パターン。
`Caption`が設定されている場合、生成コードはそれを完全に捨てていた。

**修正内容**(`dump_daemon/uipath_codegen/__init__.py`の
`_generate_message_box`): `node.caption`が`None`でない場合、
`print(_vb_cstr(caption) + ': ' + _vb_cstr(text))`のように出力へ含める
(`Caption`/`Text`いずれも非文字列が束縛される可能性があるため知見46の
`_vb_cstr()`で文字列化)。`Caption`が`None`(未設定、実機確認済みの
既定)の場合は従来通り`print(text)`のみ——挙動を変えない。

`tests/test_uipath_codegen.py`に
`test_message_box_with_caption_includes_it_in_print_output`を追加。
UiPath関連テスト全253件通過、リポジトリ全体で全880件通過(知見70の
カバレッジは72%のまま、実機フィクスチャの`Caption`は`None`のため変化
無し)。

**この知見で確定したこと**: 知見75(TODOコメントへのフィールド追記)・
知見71・73(Click属性の捕捉)と同じ「捕捉済みだが未活用のデータを
活かす」系の改善が、`MessageBox`のような既に完全対応済みと見えていた
アクティビティにもまだ残っていた——「カバレッジ100%」や「TODO無し」
だけでは「捕捉した全データを活用しているか」までは保証しないと再確認した。

## 80. `ui:Click`の`display_name`が捕捉済みなのに未活用だった——`# TODO`の場合も含めてコメントとして先頭に追記(VM不使用、知見79に続く「捕捉済みデータの未活用」)

知見79の`MessageBox.Caption`に続き、`display_name`フィールドの活用状況を
洗い直したところ、`ClickNode.display_name`(`DisplayName`属性、実機
確認済みの実例`"Click 'editable text'"`)も捕捉済みなのに生成コードで
一度も使われていないと判明した(`UnknownActivityNode.display_name`は
既に`_generate_unknown`で使われているが、`ClickNode`/`SequenceNode`は
未使用のまま)。

`Click`は複数個登場しうる活動で、`DisplayName`はStudio上で人間が
「何をクリックするためのアクティビティか」を示す説明的な名前
(セレクタの生XML文字列より遥かに読みやすい)——生成されたPython
コードを元のXAMLと対比しながら読む人間にとって、この情報が無いのは
地味だが実用上の不便だった。

**修正内容**(`dump_daemon/uipath_codegen/__init__.py`): `_generate_click`
を`_generate_click_body`(既存ロジックをそのまま移した内部関数)の
ラッパーへ変更し、`node.display_name`が設定されている場合に
`# {display_name}`というコメントを先頭に追記する——`# TODO`に倒れる
全ての分岐を含め、どの`Click`を指しているか一目で分かるようにする。
コメントのみの追加で、既存の判定ロジック・生成されるコード自体は
一切変更していない。

`tests/test_uipath_codegen.py`に
`test_click_display_name_becomes_a_comment_even_when_falling_back_to_todo`
を追加。UiPath関連テスト全254件通過、リポジトリ全体で全881件通過
(知見70のカバレッジは72%のまま——コメント追加のみで`# TODO`判定自体は
変えていないため)。

`SequenceNode.display_name`も同様に未活用のまま残っている——`Sequence`
は至る所にネストして出現するため(トップレベル・`ForEach`の本体・
`TryCatch`の各分岐等)、全件にコメントを付けると多くの場合で
`"Sequence_1"`のような非説明的な名前がノイズとして追加されるだけに
なるリスクがあり、`Click`のような「個数が少なく名前が説明的」な
ケースとは価値/ノイズ比が異なると判断し、今回は対象外のまま残す。

## 81. 知見77(Switchの比較を`_vb_cmp()`経由に統一)が`x:Boolean`型の`Switch`キーで新規のクラッシュを生んでいたと判明・修正(VM不使用、自己点検で発見)

知見77で`Switch`の`Case`比較を`=`演算子と同じ`_vb_cmp()`経由に統一した
直後、「この修正自体が別の型で新しい問題を生んでいないか」を自己点検
していたところ、`x:Boolean`型の`Switch`で新規の**クラッシュ**を実際に
生んでいたと判明した——知見77は数値/文字列混在の食い違いを正しく
解決したが、同時に退行を1件持ち込んでいた。

**原因**: `_render_switch_key`は`_SWITCH_NUMERIC_TYPES`のみを特別扱いし、
`x:Boolean`型は(知見46以来存在する`_BOOLEAN_TYPES`集合があるにも
かかわらず)素の文字列リテラル(`repr(key)`、例: `'True'`)のまま出力して
いた。知見77導入前は`flag == 'True'`という素の比較になり、型が食い違う
ため単に`False`(不一致)になるだけで済んでいたが、知見77導入後は
`_vb_cmp(flag, 'True')`——`_vb_cmp`は`bool`オペランドを比較の**前**に
`True→-1`/`False→0`へ変換する(知見51)規則があるため、`flag`(`bool`)は
`-1`/`0`になるが`'True'`(文字列)側はそのまま残り、「数値×文字列」の
組と誤判定されて`_s2f("True")`が`float("True")`を試み
`ValueError`で**クラッシュする**。

**実際に`exec()`して確認**: `x:Boolean`型・キー`"True"`の`Switch`を
生成・実行したところ、`ValueError: could not convert string to float:
'True'`で実際にクラッシュすることを確認した。

**修正内容**(`dump_daemon/uipath_codegen/__init__.py`の
`_render_switch_key`): `type_arguments`が`_BOOLEAN_TYPES`に該当する場合、
数値型と同じ発想で裸のPython真偽値リテラル(`True`/`False`)として出力
する——`_vb_cmp`の`bool`→`int`変換が両オペランドに一貫して適用される
ようになり、`_vb_cmp(True, True)`→`(-1, -1)`→正しく一致する。

`tests/test_uipath_codegen.py`に
`test_switch_with_boolean_typed_keys_does_not_crash_after_vb_cmp_fix`
(True/True一致・False/False一致・True/False不一致の3パターン)を追加。
UiPath関連テスト全258件通過、リポジトリ全体で全885件通過(知見70の
カバレッジは72%のまま、実機フィクスチャの`Switch`は`x:Int32`型のため
変化無し)。

**この知見で確定したこと**: 知見76〜80の高速な修正の連続の中で、
「この修正自体が新しい問題を生んでいないか」を自己点検する価値が
改めて確認できた——知見77は数値/文字列混在の既知のバグを正しく解決
したが、その修正が依拠する`_vb_cmp`のBoolean特別扱い(知見51)との
相互作用まで検証していなかった。今後、既存のヘルパーを別の文脈で
再利用する際は、そのヘルパーの**全ての**特別扱い分岐(`bool`/`None`/
`str`混在等)が新しい利用先でも安全に機能するか確認する価値がある。

## 82. `Append Line`/`Read Text File`の相対パス(`FileName`)が実際に何を基準に解決されるかは公式ドキュメント・実データのいずれでも確定できず、既知の残課題として明示的に記録(VM不使用、でっち上げを避けた判断)

`_generate_append_line`/`_generate_read_text_file`(`dump_daemon/
uipath_codegen/__init__.py`)は`FileName`を`open(file_name, ...)`へ
そのまま渡す——`FileName`が相対パス(実機フィクスチャの実例
`FileName="out.txt"`)の場合、Pythonの`open()`は**プロセスの現在の
作業ディレクトリ(カレントディレクトリ)**を基準に解決する。UiPath
Studio/Robotが実際に何を基準に相対パスを解決するか(プロジェクト
フォルダ基準なのか、プロセスの起動時カレントディレクトリ基準なのか)を
確認しようとしたが、確定した公式ドキュメントの記載を見つけられず、
むしろ**実行環境によって挙動が食い違うという実際の報告**が見つかった
(UiPathフォーラム、非公式情報): Studio上では相対パスがプロジェクト
フォルダ基準で解決されるという報告がある一方、Orchestrator経由の
実行では「Orchestratorは発行元フォルダから実行しているように見えない」
という理由でファイルが見つからない事例、さらにカスタムLibrary内では
「ライブラリのルートではなく呼び出し元プロジェクトのフォルダ基準で
解決される」という中間的な報告まであり、**単一の確定した仕様として
扱える状態ではない**。

**判断**: でっち上げた「プロジェクトフォルダ基準に変換する」ような
修正はしない——公式ドキュメント・実データのいずれでも確定できない
以上、現状の素朴な`open(file_name, ...)`(Pythonプロセスの実行時
カレントディレクトリ基準)のままにし、この不確実性を既知の残課題として
明示的に記録するに留める。生成されたPythonスクリプトを実行する際は、
元のUiPathプロジェクトフォルダをカレントディレクトリにして実行する
ことを運用上の注意点として推奨する(実機確認無しの推測に基づく運用上の
助言であり、コード生成ロジック自体の変更ではない)。

**この知見で確定したこと**: 知見46(Encoding)・知見74(配列インデックス
の曖昧性)と同じ「確証が得られない場合は、でっち上げた変換をするより
明示的に未解決のまま記録する」という方針を、今回新たに見つかった
「相対パス解決基準の不確実性」にも適用した——公式ドキュメントが薄く、
かつ実世界の報告が互いに矛盾する場合は、VM実機検証無しに安易な側へ
倒れたコードを書くより、不確実性そのものを正直に記録する方が誠実だと
判断した。

## 83. `InvokeCodeNode.arguments`(知見23)も知見75のTODOコメント追記対象に拡張——捕捉済みなのに未表示だったデータ(VM不使用)

知見68(零除算との相互作用確認)・知見81(自己点検)に続けて既存の実装を
見返していたところ、`InvokeCodeNode.arguments`(知見23、`Code`内で
参照しうる引数名→外側の式の対応表、実機フィクスチャでは`myArg`→
`content`)が知見75のTODOコメント追記対象に**入っていなかった**と
判明した——`Code`自体は表示されるが、どの外部変数が渡されているかは
元のXAMLを見ないと分からないままだった。

**でっち上げを避けた判断**: `Code`テキスト自体が必ずしも`Arguments`の
キー名を直接参照するとは限らない(知見17・23の実機確認時、
`Code="content=content.ToUpper()"`に対し`Arguments`は`myArg`という
別名で`content`を束縛していた——両者の対応関係の正確な意味論は未確認
のまま)。このため「`Code`中の`content`は実は`myArg`経由で渡された値だ」
のような対応付けの説明はでっち上げず、捕捉した生データ(`{引数名: 式}`)
をそのまま`Arguments={myArg=[content]}`という形で素通しするに留めた。

**修正内容**(`dump_daemon/uipath_codegen/__init__.py`の
`_generate_unresolved_activity`): `InvokeCodeNode`の分岐で`node.
arguments`が空でない場合、`Arguments={...}`を`Code=...`に続けて追記する
(`_describe_expr_for_comment`、知見75と同じ非破壊の説明用ヘルパーを
再利用)。`arguments`が空の場合は従来通り`Code`のみ。

`tests/test_uipath_codegen.py`に
`test_invoke_code_todo_includes_arguments_when_present`
(知見17・23の実機確認式そのもの)を追加。UiPath関連テスト全260件通過、
リポジトリ全体で全907件通過(知見70のカバレッジは72%のまま、`# TODO`
判定自体は変えていないため)。

## 84. `ExcelApplicationScopeNode`の子アクティビティが、スコープ自体の`# TODO`化と一緒にサイレントに失われていた実在するバグを発見・修正(VM不使用、知見83に続く既存実装の読み返し)

知見83で`InvokeCodeNode.arguments`の表示漏れを見つけた直後、同じ
`_generate_unresolved_activity`を対象に「他にも見落としが無いか」を
確認したところ、知見70で発見した5つの未対応アクティビティのうち
`ExcelApplicationScopeNode`だけが**子アクティビティ(`node.body`)を
持つ**ことに気づいた——`InvokeCodeNode`/`ExcelWriteCellNode`/
`SendOutlookMailNode`/`HttpClientNode`はいずれも子を持たない単純な
リーフノードだが、`ExcelApplicationScopeNode`は`ui:ForEach`等と同じ
「子アクティビティを束ねるコンテナ」構造(知見22、`ActivityAction`+
`DelegateInArgument`)を持つ。

`_generate_unresolved_activity`は`node`全体を1行の`# TODO`コメントへ
置き換えるだけで、`node.body`を一切見ていなかった——これは単に
「スコープ自体が未対応」という以上の問題で、**スコープ内にたまたま
含まれる、スコープ自体とは無関係に正しく生成できる子アクティビティ
(例: 単純な`print()`で済む`MessageBox`)まで、サイレントに完全に
失われる**ことを意味する。実機フィクスチャ(`Main.xaml`)の
`ExcelApplicationScopeNode`の子は`ExcelWriteCellNode`(これ自体も
知見70で未対応と確認済み)1件だけだったため、実際にはこの影響は
「子のTODOコメントそのものが消える」という形で現れていた(実際に
`generate_python()`を実行して確認——修正前は`ExcelWriteCellNode`の
`# TODO`行が生成結果に一切出現しなかった)。

**修正内容**(`dump_daemon/uipath_codegen/__init__.py`の
`_generate_unresolved_activity`): `invoke_resolver`を新たに引数として
受け取るようにし、`ExcelApplicationScopeNode`かつ`node.body`が空でない
場合、スコープ自体の`# TODO`コメントに続けて`_generate_body(node.body,
indent, invoke_resolver)`で子アクティビティを通常通り再帰生成する
——子がさらに未対応(`ExcelWriteCellNode`等)なら、子自身の`# TODO`が
個別に出るだけで、親と子の情報が二重に失われることはない。`MessageBox`
のような独立して生成可能な子は、スコープのTODOに続けて実際に動作する
`print(...)`として生成される。

`tests/test_uipath_codegen.py`に
`test_excel_application_scope_still_generates_its_child_activities`
(`MessageBox`子が実際に`print()`になることの確認)、
`test_excel_application_scope_with_unsupported_child_shows_both_todos`
(`Main.xaml`実例と同じ構成——親子両方の`# TODO`が出ることの確認)を
追加。UiPath関連テスト全262件通過、リポジトリ全体で全916件通過(知見70の
カバレッジは72%のまま——`# TODO`判定自体は変えていないため)。

**この知見で確定したこと**: 知見76〜83にわたる一連の「既存実装の
読み返し」の中でも、今回は単なる「捕捉済みデータが未活用」(知見75・
79・80・83)ではなく「子アクティビティそのものが完全に失われる」という、
より深刻な種類のデータ損失だった——`# TODO`へ倒す処理を実装する際は、
「このノードは本当にリーフノードか、それとも子を持つコンテナか」を
毎回確認する価値があると再確認した。

## 85. `UnknownActivityNode`が子要素を一切保持しないのは知見84と同じ種類のバグではなく意図的な設計と確認・将来の誤修正を防ぐ注記を追加(VM不使用、知見84の直後の自己点検)

知見84で`ExcelApplicationScopeNode`の子アクティビティ消失バグを修正した
直後、「他のノード型にも同じ種類のバグが残っていないか」を確認する
一環で`UnknownActivityNode`(`xaml_tree.parse_activity`の`_DISPATCH`に
無い未知のタグ全般へのフォールバック)を調べたところ、こちらも子要素を
一切保持していない(`tag`/`display_name`/`attrs`のみ、子要素フィールド
自体が無い)と確認した。

**知見84とは異なり、これは意図的で正しい設計だと判断した**: 未知の
アクティビティ型の子要素が「実行すべき子アクティビティの列」なのか
「設定用のプロパティ要素」なのかは、その具体的な型を知らない限り
原理的に判別不可能——知見22で`ExcelApplicationScopeNode`の`.Body`→
`ActivityAction`→`Sequence`が実行可能な子アクティビティ列だと実機
確認できたのは、この特定の型の構造を個別に調査したからであり、
「未知の型全般に同じ仮定を適用してよい」という一般原則ではない。
未知の型の子要素を「どうせ実行可能な列だろう」と推測して再帰生成する
のは、まさに本クラスが避けようとしている「でっち上げ」そのものになる。

**対応**: コードの修正はせず(現状が既に正しい)、`UnknownActivityNode`
のdocstringに、知見84との違いを明示する注記を追加した——将来のセッション
(または将来の自分)が「知見84と同じバグがここにも残っている」と誤認して
未知の型の子要素を無条件に再帰生成するような「修正」を加えてしまう
ことを防ぐための、予防的なドキュメント整備。

## 86. 知見78の`# TODO`は呼び出し先(`Sub1`)の関数本体にのみ出現し、呼び出し元(`Main`)側は無警告だったが、後続の知見87で実装した(VM不使用、知見78の延長)

知見78で`Out`/`InOutArgument`方向のワークフロー引数を検出し、関数本体の
先頭に`# TODO`を追記する修正を行った。これが`generate_project_python()`
経由の複数ファイル構成でどう見えるか確認したところ、`# TODO`は
**呼び出し先(`Sub1`)の関数定義側にのみ**出現し、**呼び出し元
(`Main`)側の呼び出し文(`Sub1(out_result=myVar)`)には何の警告も
出ない**と確認した——`Main()`のコードだけを読む人間には、`myVar`が
本来`Sub1`の結果を受け取るはずだったのに実際には受け取れないことを
示す手がかりが一切無い。

このtickでは一度、`invoke_resolver`パラメータ(`dict[str, str]`、
`generate_python()`の公開APIの一部で既存テスト複数件がこの型を直接
構築している)を拡張する(例: `dict[str, tuple[str, frozenset[str]]]`)
と後方互換性が崩れ、`_generate_node`/`_generate_body`の呼び出し経路
全体に新しいパラメータを通す変更が必要になる——1 tickで安全に実装し
切るには見積もりより侵襲的だと判断し、「半端な実装はしない」方針に
従って実装を見送っていた。**その直後のtick(知見87)で、`invoke_resolver`
の型を拡張するのではなく別の新規オプション引数(`out_arg_resolver`)を
追加するという、後方互換性を壊さない設計に気づき、実際に実装した**
(詳細は知見87参照)。

## 87. 知見86で見送った呼び出し元側への警告を実装——`invoke_resolver`の型を拡張せず、別の新規オプション引数で後方互換を保ったまま実現(VM不使用)

知見86で「`invoke_resolver`の型拡張は既存の公開APIを壊す」と判断して
実装を見送ったが、あらためて設計を見直したところ、型を変更する必要は
無く、**既存の`invoke_resolver`と並行する、全く新しい第4のオプション
引数`out_arg_resolver: dict[str, frozenset[str]] | None = None`を
追加するだけで、既存の呼び出し(`generate_python(wf, invoke_resolver=
...)`)を一切変更せずに実現できる**と気づいた——`invoke_resolver`
(`_build_invoke_resolver`が構築、`workflow_file`文字列→関数名)と
同じキー体系で、`out_arg_resolver`は`workflow_file`文字列→その呼び出し
先が持つOut/InOutArgument方向の引数名集合を保持する、独立した並行
パラメータ。

**実装内容**(`dump_daemon/uipath_codegen/__init__.py`):
1. 知見78の判定ロジック(`type_str.lower().startswith(("outargument",
   "inoutargument"))`)を`_collect_out_arg_names()`という共通ヘルパーへ
   切り出し、`generate_python()`本体と`generate_project_python()`
   (新設の`_build_out_arg_resolver`)の両方から再利用する。
2. `generate_python()`/`_generate_node()`/`_generate_body()`、および
   `If`/`ForEach`/`While`/`DoWhile`/`TryCatch`/`Switch`/`Parallel`の各
   生成関数——`invoke_resolver`を素通しするのと全く同じ経路に
   `out_arg_resolver`も素通しで追加する(既存の`invoke_resolver`の
   配線パターンをそのまま複製、新しいデザインの発明ではない)。
3. `_generate_invoke_workflow_file()`が、解決済みの呼び出し先
   (`func_name`)に対応する`out_arg_resolver`のエントリと、今回の
   呼び出しの`node.arguments`のキー集合との**積集合**を取り、1件以上
   あれば呼び出し文の直前に`# WARNING: {引数名...} are Out/InOutArgument
   on {func_name}() — the bound variable here will NOT be updated after
   this call`を追記する——呼び出し自体は(`In`方向の引数は正しく機能
   するため)通常通り生成を続ける。
4. `generate_project_python()`が新設の`_build_out_arg_resolver()`
   (`_build_invoke_resolver`と並行する構造、`cache[target].arguments`
   から対象ワークフローのOut/InOutArgument名を集める)を呼び、
   `generate_python()`へ渡す。

**実機確認**: 合成した2ファイル構成(`Main`→`Sub1`、`Sub1`の
`out_result`が`OutArgument`)で`generate_project_python()`を実行し、
`Main()`の呼び出し文`Sub1(out_result=myVar)`の直前に`# WARNING`が
正しく追記されることを確認。実機確認済みの`Main.xaml`/`Sub1.xaml`
(`in_text`は`InArgument`のみ)では新しい警告が出ないことも確認——
既存の生成結果に対する退行は無い。

`tests/test_uipath_codegen.py`に
`test_generate_project_python_warns_caller_about_out_argument_binding`
を追加。UiPath関連テスト全264件通過、リポジトリ全体で全920件通過
(知見70のカバレッジは72%のまま)。

**この知見で確定したこと**: 知見86で「侵襲的すぎる」と判断した設計を、
型拡張ではなく**並行する新規オプション引数の追加**という形に言い換える
だけで、既存の配線パターン(`invoke_resolver`の素通し)を忠実に複製する
機械的な変更へ縮小できた——「既存の型を変える」と「既存のパターンに
倣った新しいパラメータを追加する」は見た目は似た規模の変更に見えて
リスクが大きく異なる、という教訓。1 tick前の「見送り」判断自体を
再検証し、より安全な設計を見つけた上で実際に実装まで完了させた。

## 88. 知見84が初めて意味を持たせてしまった退行——`ExcelApplicationScope`内の`Invoke Workflow File`参照が複数ファイル発見で見つけてもらえず常に未解決になるバグを発見・修正(VM不使用、知見87の検証作業中に発見)

知見87(呼び出し元への`# WARNING`)の実装を多角的に検証していた際、
`ExcelApplicationScopeNode`の子に`Invoke Workflow File`を入れた
合成構成で`generate_project_python()`を実行したところ、実在する
`Sub1.xaml`を参照しているにもかかわらず常に`# TODO: unresolved Invoke
Workflow File: Sub1.xaml`に倒れてしまうと判明した。

**原因**: 複数ファイルのBFS発見(`_discover_workflow_files`→
`_iter_invoke_nodes`→`_child_node_lists`)を担う`_child_node_lists`
関数に、`ExcelApplicationScopeNode`の分岐が無かった——
`SequenceNode`/`IfNode`/`ForEachNode`/`TryCatchNode`/`SwitchNode`/
`ParallelNode`は網羅されているが、`ExcelApplicationScopeNode`が
漏れていた。

**知見84が初めてこの欠落に意味を持たせた、という経緯**: 知見84より前は
`ExcelApplicationScopeNode`の子アクティビティが丸ごと`# TODO`に潰されて
いたため、「子の中にある`Invoke Workflow File`参照」自体がコード生成上
無意味で、この欠落は無害だった。知見84でスコープの子アクティビティを
実際に再帰生成するよう修正した結果、スコープ内にネストした`Invoke
Workflow File`が初めて「実際に解決されるべき呼び出し」として意味を
持つようになり、`_child_node_lists`の欠落が初めて実害のある退行として
現れた——知見84自身のバグではなく、知見84が別の既存の欠落を「意味の
あるバグ」に変えた、という間接的な経緯。

**修正内容**(`dump_daemon/uipath_codegen/__init__.py`の
`_child_node_lists`): `ExcelApplicationScopeNode`の分岐
(`return [node.body]`)を追加した。

`tests/test_uipath_codegen.py`に
`test_invoke_workflow_file_nested_in_excel_scope_is_still_discovered`
(実際に`generate_project_python()`を実行し、実在するファイルが正しく
解決されることを確認)を追加。UiPath関連テスト全267件通過、リポジトリ
全体で全928件通過(知見70のカバレッジは72%のまま)。

**この知見で確定したこと**: ある修正(知見84)が、別の既存の欠落(今回の
`_child_node_lists`)を無害な状態から有害な状態へ変えてしまうことがある
——修正を実装した直後に「この修正によって新たに到達可能になった
コードパスは他に無いか」を広く確認する価値が、知見81(自分自身の修正の
副作用確認)に続いて今回も実証された。

## 89. 単項`-`/`+`が文字列オペランドで常に`TypeError`になっていた実在するバグを発見・`_vb_num()`への統一で解決(VM不使用、`^`演算子との比較検証中に発見)

4ティック連続で何も新規に見つからなかった後、`^`演算子(`_vb_num()`
経由で文字列/`&H`リテラル対応済み、知見49・68)と単項`-`/`+`
(知見58で`Nothing`だけ対応済み)の実装を横に並べて比較していたところ、
単項`-`/`+`が文字列オペランドを一切コンバートしていないと判明した。

**実際に`exec()`して確認**: `CStr(-"5")`(`&H`限定ではなく単純な数値
文字列)を生成・実行したところ、`TypeError: bad operand type for unary
-: 'str'`で実際にクラッシュした。知見58が`Nothing`オペランドの
クラッシュ(`-(None)`も`TypeError`になる)を解決した際、同じ理屈が
文字列オペランドにも当てはまるはずだったが、見落とされていた——
`CStr`の引数は実行時にどんな型にもなりうる`Object`型の式として扱われる
ため、`-someVar`のような式で`someVar`が緩い型付けの文字列値を実際に
保持している場合、現実のRPAフローでも再現しうる。

**修正内容**(`dump_daemon/uipath_codegen/render.py`): 単項`-`/`+`の
レンダリングを、`Nothing`専用の`lambda`ラップ(`(lambda _x: {op}(0 if
_x is None else _x))(...)`)から、他の数値演算子(`-`/`*`/`\`/`^`、
知見49・68)と同じ`_vb_num()`ヘルパーへの統一(`{op}{VB_NUM_HELPER_NAME}
({operand})`)に変更した——`_vb_num`は`bool`/`Nothing`/文字列(`&H`/`&O`
16進8進リテラル含む)を一貫して数値へコンバートするため、`Nothing`の
場合も含め既存の確認済み挙動を変えずに文字列対応を解消できた。副次的に、
`operand`の参照が1回だけになったため(`_vb_num(x)`は単純な関数呼び出し
引数)、以前の`lambda`ラップ(副作用の二重評価を避けるために必要だった)
も不要になった。

既存の`eval()`直呼びテスト(`test_not_matches_vb_bitwise_complement_
on_integer_not_just_boolean_negation`の`"Not -1"`ケース、`generate_
python()`の自動ヘルパー注入を経由しない軽量テスト)が`_vb_num`未定義で
落ちたため、知見57の`^`テストと同じ対処(`VB_NUM_HELPER_SOURCE`を
手動で`eval`の名前空間へ注入)で追従させた。`tests/test_uipath_
codegen.py`に新規
`test_unary_minus_plus_coerce_string_operand_not_raising_typeerror`
(数値文字列・`&H`/`&O`リテラル文字列の両方)を追加。UiPath関連テスト
全265件通過、リポジトリ全体で全954件通過(知見70のカバレッジは72%の
まま)。

**この知見で確定したこと**: 4ティック連続で新規発見が無かった後、
「既に対応済みの似た演算子と、まだ対応が怪しい演算子を横に並べて
比較する」という、これまでとは少し異なる発見経路で見つけた——
`^`はすでに`_vb_num`経由だが単項`-`/`+`はまだ`Nothing`専用の古い
パターンのままだった、という「対応の進み具合の不均衡」自体が手がかり
になった。evidence(実機XAML)が尽きた後も、既存の修正済みコードと
未修正コードの「整合性の欠け」を探すという軸は依然有効だった。

## 90. `Not`も単項`-`/`+`と全く同じ理由で文字列オペランドで常に`TypeError`になっていた——知見89の兄弟バグ(VM不使用)

知見89(単項`-`/`+`の文字列オペランド`TypeError`)を修正した直後、
「`Not`も同じ`Nothing`専用パターンのままではないか」を確認したところ、
全く同じ理由で`Not`も文字列オペランドで`TypeError`になっていると
判明した。

**実際に`exec()`して確認**: `CStr(Not "5")`を生成・実行したところ、
`TypeError: bad operand type for unary ~: 'str'`で実際にクラッシュ
した——`Not`の実装は`isinstance(_x, bool)`で`bool`分岐のみ特別扱いし、
それ以外は`Nothing`だけを`0`に読み替えて(知見58)そのまま`~`を適用して
いたため、文字列はそのまま`~`演算子に渡ってクラッシュしていた。

**修正内容**(`dump_daemon/uipath_codegen/render.py`): `Not`の`bool`以外
分岐を、`0 if _x is None else _x`から`round({VB_NUM_HELPER_NAME}(_x))`
(知見89と同じ`_vb_num()`、ただし`Not`はビット反転のため整数化が必要な
点が単項`-`/`+`と異なり、`\`の銀行丸め、知見54と同じ`round()`を追加)
へ変更した——`_vb_num`が`Nothing`/文字列(`&H`/`&O`含む)/`bool`を
一貫してコンバートするため、既存の`Nothing`/数値オペランドの確認済み
挙動(`Not Nothing`→`-1`、`Not 5`→`-6`、`Not -1`→`0`)を全て変えずに
文字列対応を解消できた。

`tests/test_uipath_codegen.py`に
`test_not_coerces_string_operand_not_raising_typeerror`(数値文字列・
`&H`リテラル文字列の両方)を追加。UiPath関連テスト全267件通過、
リポジトリ全体で全964件通過(知見70のカバレッジは72%のまま)。

**この知見で確定したこと**: 知見89の「`^`と単項`-`/`+`を並べて比較する」
という発見経路を、修正した直後に**同じファミリーの他の演算子
(`Not`)にもすぐ適用する**ことで、連続して2件目の兄弟バグを見つけた
——1つの演算子の古いパターン(`Nothing`専用の場当たり対応)を見つけたら、
同じ場当たり対応が他の単項/型依存演算子に残っていないか即座に確認する
価値があると実証した。

## 91. `And`/`Or`/`Xor`も単項`-`/`+`・`Not`と全く同じ理由で文字列オペランドで常に`TypeError`になっていた——知見89・90に続く3件目の兄弟バグ(VM不使用)

知見90(`Not`)を修正した直後、「同じファミリーの他の型依存演算子
(`And`/`Or`/`Xor`)にも同じ古いパターンが残っていないか」を確認した
ところ、3件目の兄弟バグが見つかった。

**実際に`exec()`して確認**: `CStr("5" And 3)`を生成・実行したところ、
`TypeError: unsupported operand type(s) for &: 'str' and 'int'`で
実際にクラッシュした(`Or`/`Xor`も同様に`|`/`^`でクラッシュ)。
`_vb_and`/`_vb_or`/`_vb_xor`(知見59)は`Nothing`絡みの分岐のみ型ごとに
正確に対応していたが、両オペランドが非`Nothing`の最終行(`return
a & b`等)では文字列を一切コンバートせずそのまま渡していた。

**修正の範囲を絞った判断**: `Nothing`絡みの分岐(知見59で`Operators.vb`
の`AndObject`/`OrObject`/`XorObject`を個別に確認済み、特に`Or`/`Xor`の
「`Nothing`は単位元として型も維持したまま他方を返す」という規則)は
今回変更しない——この規則の対象が「他方がString型の場合」にまで及ぶかは
未確認のまま(例: `Nothing Or "5"`が`"5"`(文字列のまま)になるのか、
数値へコンバートされた`5`になるのかは今回は検証していない)。でっち上げ
を避け、**確実にクラッシュする**(両オペランドが実際に値を持つ)ケース
だけを修正対象に絞った。

**修正内容**(`dump_daemon/uipath_codegen/render.py`): `_vb_and`/
`_vb_or`/`_vb_xor`の最終行の直前に、局所関数`_s2i`(知見89・90と同じ
`_vb_num`+`round()`の規則、`&H`/`&O`16進8進リテラル含む)を追加し、
`a`/`b`が文字列の場合のみコンバートしてから`&`/`|`/`^`を適用する——
`Nothing`絡みの既存分岐は一切変更していない。

`tests/test_uipath_codegen.py`に
`test_and_or_xor_coerce_string_operand_not_raising_typeerror`を追加。
UiPath関連テスト全271件通過、リポジトリ全体で全969件通過(知見70の
カバレッジは72%のまま)。

**この知見で確定したこと**: 知見89→90→91と、1つの演算子ファミリー
(型依存の単項/二項演算子における`Nothing`専用の場当たり対応)の中で
3件連続して同じパターンの兄弟バグを見つけた——1件見つけたら即座に
「同じ特徴を持つ他の演算子は無いか」を横展開して確認する、という
手順がこのファミリーでは特に高い再現率を示した。この演算子ファミリー
(`-`/`+`/`Not`/`And`/`Or`/`Xor`)はこれで一通り確認済みになった。

## 92. `UnknownActivityNode.attrs`/`HttpClientNode.extra_attrs`が既に捕捉済みなのに`# TODO`コメントへ一度も出ていなかった——知見75/79/80/83と同じ「捕捉済みデータの未活用」パターン(VM不使用、ロードマップ俯瞰レビュー後の自律ループ再開時に発見)

ユーザーからロードマップ全体の俯瞰レビューを依頼され、Flowchartスコープの
食い違いと5活動のライブラリ選定という2件の意思決定待ち項目を整理した直後、
自律ループを再開するにあたり「決定待ちではない、まだ拾われていない
データ未活用の見落としが残っていないか」を`render.py`/`__init__.py`を
読み返して確認したところ発見した。

**`UnknownActivityNode.attrs`**: `xaml_tree.parse_activity`は未知の
アクティビティ型に遭遇すると`dict(elem.attrib)`で**全属性**を無条件に
捕捉している(知見26のLibrary呼び出し発見時から変わらず)。しかし
`_generate_unknown`(`uipath_codegen/__init__.py`)は`display_name`しか
使わず、`attrs`自体は一度もコメントへ出していなかった。実機フィクスチャ
(`Main.xaml`)の`<p:NewActivity in_greeting="hellofromlib" .../>`
(知見26のLibrary呼び出し実例)で実際に確認——`in_greeting`という
Library呼び出しの引数情報が、生成コードからは一切見えない状態になっていた
(人間が手動でポートする際に最も必要な情報のはずなのに、元の`.xaml`に
戻らないと分からない)。

**`HttpClientNode.extra_attrs`**: `_parse_http_client`は`EndPoint`/
`Method`以外の全属性を`extra_attrs`に捕捉する設計(型定義のdocstring
「取りこぼしを防ぐ」とコメントされている)だったが、`_generate_unresolved_
activity`のHttpClient詳細(知見75で`EndPoint`/`Method`のみ追加)は
`extra_attrs`を一度も参照していなかった。実機フィクスチャの`<ui:HttpClient
... AcceptFormat="ANY" BodyFormat="application/xml" ... TimeoutMS="6000"
...>`で確認——`BodyFormat`/`TimeoutMS`等、HTTPリクエストを手動で組み直す際に
有用な情報が同様に失われていた。

**修正**(`dump_daemon/uipath_codegen/__init__.py`): `_generate_unknown`は
`node.attrs`(`DisplayName`は`display_name`で別途表示済みのため重複除外)を
`attrs={...}`として追記。`_generate_unresolved_activity`のHttpClient分岐は
`node.extra_attrs`(同じく`DisplayName`除外)を`ExtraAttrs={...}`として
追記。いずれも既に捕捉済みの生データをソート済み辞書としてそのまま
表示するだけで、でっち上げた解釈・変換ロジックは追加していない
(知見83と同じ方針)。

回帰テスト3件追加
(`test_http_client_todo_includes_extra_attrs`・
`test_unknown_activity_todo_includes_captured_attrs`・
`test_unknown_activity_todo_omits_attrs_detail_when_only_display_name_captured`)、
既存の`test_main_xaml_pipeline_smoke`も`in_greeting`/`hellofromlib`が
実際に生成コードへ出ることを確認するよう拡張。UiPath関連テスト全274件
通過、リポジトリ全体で全979件通過(知見70のカバレッジは72%のまま、
分岐点の構造自体は変えていないため)。

**この知見で確定したこと**: 知見75/79/80/83で見つけた「捕捉済みだが
コメントに出ていないフィールド」のパターンは`UnknownActivityNode`
(v1スコープ外の全アクティビティの受け皿、最も広く使われる経路)自体にも
及んでいた——個別の5活動(知見70)だけでなく、キャッチオール経路も
同じ観点で確認する価値があったことが分かった。

## 93. `ExcelWriteCellNode.text`/`SendOutlookMailNode.body`も知見75で見落としていた捕捉済みフィールド——知見92の直後の自己点検で同じ関数内に残っていた(VM不使用)

知見92(`UnknownActivityNode.attrs`/`HttpClientNode.extra_attrs`)を
修正した直後、同じ`_generate_unresolved_activity`関数内の他の分岐も
「捕捉済みなのに表示していないフィールドが残っていないか」を見直した
ところ、2件追加で見つかった。

**`ExcelWriteCellNode.text`**: 知見75で`Cell`/`SheetName`をTODOコメントに
追記した際、同じノードが持つ`text`(実際にセルへ書き込む値そのもの)を
見落としていた。実機フィクスチャ(`Main.xaml`)で確認——
`<ui:ExcelWriteCell Cell="A1" SheetName="Sheet1" Text="hello" />`の
`Text="hello"`が生成コードに一切出ていなかった。

**`SendOutlookMailNode.body`**: 同様に知見75で`To`/`Subject`を追記した際、
`body`(メール本文そのもの)を見落としていた。実機フィクスチャで確認——
`<ui:SendOutlookMail ... Body="body" ... Subject="hi" To="a@b.com">`の
`Body="body"`が生成コードに一切出ていなかった。

**修正**(`dump_daemon/uipath_codegen/__init__.py`の
`_generate_unresolved_activity`): `ExcelWriteCellNode`分岐に
`Text={_describe_expr_for_comment(node.text)}`を、`SendOutlookMailNode`
分岐に`Body={_describe_expr_for_comment(node.body)}`を追記。知見75・92と
同じ方針(既に捕捉済みの生データをそのまま表示するだけ、でっち上げた
解釈は追加しない)。

既存の`test_unresolved_activity_todo_includes_captured_fields`の期待値を
更新、`test_main_xaml_pipeline_smoke`に`Text='hello'`/`Body='body'`が
生成コードへ実際に出ることの確認を追加。UiPath関連テスト全274件通過、
リポジトリ全体で全979件通過。

**この知見で確定したこと**: 「捕捉済みデータの未活用」パターン(知見75/
79/80/83/92)は、1つのバグを見つけた直後に**同じ関数の他の分岐**も
横展開して確認する価値があると改めて分かった——知見89→90→91の演算子
ファミリーと同種の「1件見つけたら隣接するコードも確認する」手順が、
このパターンでも再現した。

## 94. `ExcelApplicationScopeNode.scope_var`も`WorkbookPath`と同じく捕捉済みなのに`# TODO`コメントへ未表示だった(VM不使用、知見92・93に続く同系統の横展開)

知見93の直後、`_generate_unresolved_activity`に残る最後の未確認分岐
(`ExcelApplicationScopeNode`)も同じ観点で確認した。`scope_var`
(`xaml_tree._parse_excel_application_scope`が`ActivityAction.Argument`
配下の`DelegateInArgument.Name`から実際に読み取る、スコープ内で
ワークブックを指す変数名)が、`WorkbookPath`だけをコメントに追記した
知見75実装時に見落とされていた。実機フィクスチャでは偶然デフォルト値
(`"ExcelWorkbookScope"`)と同じ値だったため、差分としては目立たなかった
が、カスタム名(例: `"myWorkbook"`)の場合に正しく捕捉・表示されることを
合成テストで確認した。

**修正**(`dump_daemon/uipath_codegen/__init__.py`): `ExcelApplicationScopeNode`
分岐に`ScopeVar={node.scope_var!r}`を追記。知見92・93と同じ方針。

回帰テスト追加(デフォルト値・カスタム値の両方)、UiPath関連テスト全275件
通過、リポジトリ全体で全988件通過。知見92→93→94と3件連続で同じ
「捕捉済みデータの未活用」パターンが見つかり、`_generate_unresolved_
activity`の全分岐(`InvokeCodeNode`/`ExcelApplicationScopeNode`/
`ExcelWriteCellNode`/`SendOutlookMailNode`/`HttpClientNode`)が持つ全フィールドを
一通り確認済みになった。

## 95. `generate_project_from_json`のLibraryプロジェクト拒否が、実物の実機フィクスチャ(`uipath_xaml_probe_lib`)では一度もテストされていなかった(VM不使用、検証基盤の薄さを埋める改善)

知見92〜94の「捕捉済みデータの未活用」パターンが
`_generate_unresolved_activity`全分岐で確認済みになったため、別の角度
(ロードマップ俯瞰レビューの「残タスクC: 検証基盤の薄さ」節)から
「既にリポジトリに存在する実機フィクスチャで、まだ一度も通していない
経路が無いか」を確認した。

**発見**: `design/evidence/uipath_xaml_probe_lib/`(`project.json`に
`"outputType": "Library"`、`main`は`"NewActivity.xaml"`)という
実物のLibraryプロジェクトフィクスチャが既に存在し、知見26・28の
調査(Library参照・`.nupkg`の技術的制約)で使われていたにもかかわらず、
`generate_project_from_json()`のLibrary拒否ロジック(Phase 1決定)の
テストは手作りの合成`project.json`(`tmp_path`)でしか検証されておらず、
この実物フィクスチャを一度も通していなかった。実際に手動実行して
`ValueError: unsupported project outputType: 'Library' ...`が正しく
出ることを確認した上で、同じ内容を回帰テスト化した。

**バグではなく、検証基盤の強化**: 挙動自体は合成テストの時点から
正しかった(今回変更無し)。既存の実機フィクスチャを使い切っていなかった
という意味でのギャップ。

`tests/test_uipath_codegen.py`に
`test_generate_project_from_json_rejects_real_library_fixture`を追加
(`FIXTURE_LIB_DIR`定数を新設)。UiPath関連テスト全276件通過、リポジトリ
全体で全1005件通過。

## 96. `HttpClientNode`を実際に`requests`ライブラリへ変換するコード生成を実装——知見70以来TODO固定だった5活動のうち最初の1件を解消(VM不使用、ユーザーの明示的な意思決定を受けて着手)

ユーザーからロードマップ俯瞰レビュー後に「Flowchartスコープ」「Excel/
Outlook/HttpClientのライブラリ選定」という残タスクについて明示的な意思
決定を得た(AskUserQuestion): Flowchart実装・Excel=openpyxl・
Outlook=win32com・HttpClientのHeaders/Bodyパースを今進める(InvokeCode
は見送り)。この知見では、最も小さく・最も実機データで裏付けの取れる
HttpClientから着手した。

**実機データの再確認**: `design/evidence/uipath_xaml_probe/Main.xaml`の
`<ui:HttpClient>`(知見29)を再確認したところ、`Body="{x:Null}"`は
**属性**(プロパティ要素ではない)であり、`Headers`/`Cookies`/
`Parameters`/`UrlSegments`/`Attachments`はいずれも`<ui:HttpClient.
Headers><scg:Dictionary x:TypeArguments="x:String, InArgument(x:String)"
/></ui:HttpClient.Headers>`という**子要素を持たない空の辞書**だった——
つまりこの実機フィクスチャは「もっとも単純な構成(ヘッダーもボディも
無いGETリクエスト)」そのものだった。

**公式ドキュメント確認**(docs.uipath.com/activities/other/latest/
developer/http-request、legacy HttpClient活動): `TimeoutMS`の既定値は
6000ms(実機フィクスチャの値`"6000"`と一致)。`AcceptFormat`既定値`ANY`・
`BodyFormat`既定値`application/xml`も実機フィクスチャの値と一致——
いずれもユーザーが明示的に変更したのではなく単純にStudioの既定値のまま
だったと確定した。

**実装**(`dump_daemon/uipath_dsl/types.py`・`xaml_tree.py`・
`uipath_codegen/__init__.py`): `HttpClientNode`に`body`(`Expr`)・
`timeout_ms`(生文字列)・`has_populated_collections`(bool)を追加。
`_parse_http_client`が`Body`/`TimeoutMS`を専用フィールドとして捕捉し、
5つの`scg:Dictionary`プロパティ要素それぞれに1件以上の子要素があるかを
判定する(populated時の中身のXML形は実機未確認のためパースしない)。
新設の`_generate_http_client`は、`has_populated_collections`が`False`
かつ`body`が`None`(実機確認済みの最も単純な構成)の場合のみ
`requests.request(method, endpoint, timeout=...)`を実際に生成する——
それ以外(Body設定済み、または5つのコレクションのいずれかにエントリが
ある場合)は、実直列化形が未確認のため`_generate_unresolved_activity`の
`# TODO`へ安全に倒す(その際の詳細コメントにも新設の`Body`フィールドを
追記、知見92〜95と同じ「捕捉済みデータを隠さない」方針)。

**結果**: `dump_daemon.uipath_codegen_coverage`の分岐点カバレッジが
72%(21/29)→76%(22/29)へ向上(知見70以来初めての数値改善)。知見70で
発見した5つの未対応アクティビティは4件(ExcelApplicationScopeNode/
ExcelWriteCellNode/InvokeCodeNode/SendOutlookMailNode)に減った。
`requests`を新規依存に追加(`uv add requests`)。回帰テスト5件追加
(単純ケースの実コード生成・`TimeoutMS`単位変換・populated時のTODO
フォールバック・実機フィクスチャでの確認・既存TODO系テストの更新)、
UiPath関連テスト全280件通過、リポジトリ全体で全1013件通過。

**この知見で確定したこと**: 知見70の「5つの未対応アクティビティ」は
必ずしも等しく難しいわけではなく、実機データが「たまたま最も簡単な
ケース(空コレクション・ボディ無し)」だった`HttpClient`は、Excel/
Outlook/InvokeCodeより先に、ライブラリ選定という意思決定すら不要な
形で前進できた——残る4件はいずれもライブラリ選定(Excel=openpyxl・
Outlook=win32com、ユーザー決定済み)またはより大きな設計判断
(InvokeCodeの文単位コード変換、見送り決定済み)が必要。

## 今後の調査候補(未着手)
- **(解決)** ~~ドラッグ&ドロップ専用ゾーンへのアクティビティ追加~~ → 知見20で
  `drag_activity_from_panel()`ヘルパーにより解決し、`Parallel`の単一ブランチ構造
  (直接の子`Activity`要素、ラッパー無し、知見20)と`Switch`のcase本体の構造
  (`x:Key`はアクティビティ要素自身の属性になる、知見21)の両方を確定した。
  残る派生課題:
  - `Parallel`に2つ目以降のブランチを追加した場合の複数子要素の並び(知見20、
    1回目の追加試行はキャンバス座標ズレで失敗——事前のスクリーンショット確認が必要)。
    2回目の試行(知見29作業時)では、既存ブランチ右側の`▽`アイコンや空白領域への
    クリック・ドラッグでは新ブランチ追加ゾーンを発見できず、ホバー時の視覚的な
    手がかり(「+」等)も静止スクリーンショットでは確認できなかった。UI上の
    正確な追加操作(ブランチ境界へのドラッグの正しい座標、またはキーボード
    ショートカット等)は依然未解決——優先度を下げて保留
  - 1つのブランチ/caseに複数ステップを入れたい場合、ユーザーが明示的に
    `Sequence`をドラッグする必要があるという推測(知見20・21)の実機検証
- Libraryプロジェクト・Testプロジェクトの`project.json`の違い、および
  `targetFramework: "Windows"`/`"Cross-platform"`(Legacy以外)での依存関係の違い
  ※ 今回インストールしたバージョン(Studio app-21.4.4)のProject Settingsダイアログ
  (General/Workflow Analyzer/Activities Settings各種/System)には`targetFramework`を
  切り替えるUIが見当たらなかった——Cross-platformプロジェクト種別はNew Projectウィザード
  側(本調査では未確認)か、より新しいStudioバージョンでのみ露出する可能性がある
- Library参照時(`ui:InvokeWorkflowFile`ではなくライブラリの`Activity`型として
  直接ツールボックスに現れる場合)の引数型(知見12はファイルパス直接参照のみ確認)
- セレクタのフォールバック・複数候補(1つの`ui:Target`が複数セレクタを持つケース)、
  Computer Vision/画像ベースターゲティング(`ClippingRegion`/`Element`が実際に
  使われるケース)は知見11では未確認
- **(部分的に解決・ネガティブ)** C#式言語プロジェクト(`expressionLanguage: "CSharp"`)
  でのInArgument/OutArgumentの直列化形式の違い(VB.NETと同じ`[...]`規約を使うのか)
  → Studio 2021.4.4では「New Blank Process」ダイアログ(Name/Location/Description
  のみ)にも、グローバルSettings(General/Design等の全タブ)にも式言語を選択する
  UIが一切存在しないことを確認した。「Use Modern for new projects」はFlowchart
  デザイナースタイルの切り替えであり式言語とは無関係。これはP0#4で確認した
  `targetFramework`切り替えUIの不在と同じ傾向であり、**このバージョンの
  Studioでは全プロジェクトがVB.NET固定**という結論になる。C#式言語の実機確認には
  より新しいStudioバージョン(22.x以降と推定)のインストールが必要——
  今回はインストール済みバージョンの範囲内での追加調査は打ち切り、優先度を
  下げて保留する
- **(解決)** ~~`Invoke Code`に実際に1つ以上の`Argument`を追加した場合の形~~
  → 知見23で解決(`x:Key`付き`InArgument`要素列になる)。残る派生課題:
  方向`Out`/`InOut`の引数を追加した場合に`OutArgument`/`InOutArgument`の
  どちらになるか(今回は`In`のみ確認)
