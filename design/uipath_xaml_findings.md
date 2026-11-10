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

**(2026-11-05追補、知見109)** `Invoke Workflow File`の`Isolated`属性
(既定`False`相当)に関連する追加のニュアンスを発見——詳細は知見109
参照。「`Out`/`InOutArgument`のByRef書き戻しが失われる」という本知見の
限界は、実は`Isolated=False`(非分離実行、UiPath公式ドキュメントで
確認済みの既定)という前提の上に成り立っている可能性がある——
`Isolated=True`の場合は呼び出し先が別プロセス/セッションで動くため
値渡しに近い挙動になり、むしろ本知見の限界が目立たなくなる(または
別の意味で一致する)可能性がある。実機での`Isolated=True`の使用例は
非常に稀(GitHub実例でも1件未満)だったため、この相互作用自体は未検証
のまま記録のみに留める。

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

## 97. `ExcelApplicationScopeNode`+`ExcelWriteCellNode`を実際に`openpyxl`へ変換するコード生成を実装——知見70以来TODO固定だった5活動のうち2件目を解消(VM不使用、ユーザーの明示的な意思決定を受けて着手)

知見96(HttpClient)に続き、ユーザー決定済みの`openpyxl`でExcel連携の
コード生成に着手した。

**設計**: PAD側`dump_daemon/pad_action_lib/excel_actions.py`の既存方針
(ファイルベース`openpyxl`、ライブExcelプロセス・マクロ実行・開いたまま
の対話操作は再現不可能という既知の限界を明示)をそのまま踏襲——「開く→
操作→保存」モデルで`openpyxl.load_workbook(workbook_path)`をスコープ
先頭、`.save(workbook_path)`をスコープ末尾に生成する。`scope_var`
(知見94で捕捉済みだったがコメント内の文字列止まりだった`DelegateInArgument.
Name`)を、実際にこのワークブックを束縛するPython変数名として初めて使う。

**`ExcelWriteCellNode`との連携方法**: 知見22で確認済みの実機構造(`Write
Cell`はスコープの直接の子)に限って対応する——`_generate_excel_
application_scope`が`node.body`を直接走査し、`ExcelWriteCellNode`の
場合のみ`scope_var`を使った`{var}[sheet_name][cell] = _vb_cstr(value)`
という代入文を生成する(`openpyxl.Worksheet.__setitem__`代入記法、
インストール済みの実`openpyxl`で`wb['Sheet1']['A1'] = 'hello'`→
`wb['Sheet1']['A1'].value == 'hello'`と実際に動作確認済み——Pythonライブラリ
に対する「実機確認」に相当)。それ以外の子(If/Switch/ループ越しに
ネストした`ExcelWriteCellNode`含む)は汎用ディスパッチへ委ね、
`scope_var`文脈を失う場合は安全に`# TODO`へ倒す(実機未確認のケースを
でっち上げない)。

**知見84/88の扱い**: `ExcelApplicationScopeNode`はもはや
`_generate_unresolved_activity`へ到達しないため、その中にあった知見84の
子再帰生成ロジック(と知見94のTODO詳細分岐)は死んだコードとして削除した
——専用の`_generate_excel_application_scope`に機能が完全に移った。
知見88(`_child_node_lists`へのExcelApplicationScopeNode分岐、複数ファイル
発見用)は別の関心事(静的呼び出しグラフ解析)のため変更不要、そのまま
機能する。

**カバレッジツールでの見え方(重要な注記)**: `ExcelWriteCellNode`は
`uipath_codegen_coverage`では引き続き`TODO`と判定される——このツールは
各ノード型を`_strip_children`で単独に切り出して測定するため、`scope_var`
文脈に依存する知見97の対応は単独評価では(安全側に倒れる設計なので)
`# TODO`経路に入る。実際の`Main.xaml`全体(スコープに正しくネストした
状態)では実コード生成されることは別途ユニットテストで確認済み——
バグではなく、カバレッジツールの測定方法の限界として記録する。

**結果**: カバレッジ76%(22/29、知見96)→79%(23/29)へ向上。知見70の
未対応5活動は残り3件(ExcelWriteCellNode(※単独評価のみ)/InvokeCodeNode/
SendOutlookMailNode)。回帰テストを更新・追加(スコープ単体でのカスタム
`scope_var`使用確認・Scope+WriteCell連携の実コード生成確認・
真に未対応な子(InvokeCode)のTODOが引き続き出ることの確認)、UiPath関連
テスト全280件通過、リポジトリ全体で全1014件通過。

## 98. `SendOutlookMailNode`を実際に`win32com.client`(Outlook COM)へ変換するコード生成を実装——知見70以来TODO固定だった5活動のうち3件目を解消(VM不使用、ユーザーの明示的な意思決定を受けて着手)

知見96(HttpClient)・知見97(Excel)に続き、ユーザー決定済みの`win32com`で
Outlook連携のコード生成に着手した。

**実機データの再確認**: `Main.xaml`の`<ui:SendOutlookMail>`(知見24)を
再確認すると、`Cc`/`Bcc`/`Account`/`ReplyTo`/`MailMessage`/`TimeoutMS`は
いずれも`{x:Null}`、`Files`は`<scg:List Capacity="0" />`(空)、
`Importance="Normal"`・`Sensitivity="Normal"`・`IsBodyHtml="False"`・
`IsDraft="False"`——いずれもStudioの既定値のままだった(HttpClientの
`TimeoutMS`/`AcceptFormat`が知見96で既定値のままと確定したのと同じ構図)。

**公式ドキュメント確認**(learn.microsoft.com、Outlook VBAリファレンス
——UiPathのSendOutlookMailは内部的にOutlook COMオブジェクトモデルを
ラップしていると推定されるため、VBA版の公式ドキュメントを根拠にした):
`OlItemType.olMailItem = 0`、`OlImportance`(`olImportanceLow=0`/
`olImportanceNormal=1`/`olImportanceHigh=2`)、`OlSensitivity`
(`olNormal=0`/`olPersonal=1`/`olPrivate=2`/`olConfidential=3`)。

**意図的に確認済みの値のみ対応する設計**(知見71のClickType/MouseButton
と同じ教訓): UiPathの`ClickType`/`MouseButton`は`CLICK_SINGLE`/
`BTN_LEFT`という独自トークン名で、一般的な.NET/Outlook語彙とは一致
しなかった——同じ理由で、`Importance`/`Sensitivity`の実際のXAML直列化
文字列が確認済みの`"Normal"`以外(`"Low"`/`"High"`/`"Personal"`等)で
本当にOutlook VBAの英語名と一致するかは未確認のため、`"Normal"`
(両方とも)・`IsBodyHtml`/`IsDraft`の`"False"`以外は実コード生成せず
`# TODO`へ安全に倒す。`Cc`/`Bcc`設定済み・`Files`に添付ありの場合も
同様(添付の追加方法(`Attachments.Add`)自体は標準的だが、実際の値の
受け渡し形が実機未確認)。

**実装**(`dump_daemon/uipath_dsl/types.py`・`xaml_tree.py`・
`uipath_codegen/__init__.py`): `SendOutlookMailNode`に`cc`/`bcc`/
`importance`/`sensitivity`/`is_body_html`/`is_draft`/
`has_populated_files`/`extra_attrs`を追加(知見92の教訓を活かし、今回は
最初から`extra_attrs`も用意して同じ「捕捉済みデータの未活用」の再発を
防いだ)。新設の`_generate_send_outlook_mail`は確認済みの安全な構成の
場合のみ`win32com.client.Dispatch('Outlook.Application')`→
`CreateItem(0)`→`To`/`Subject`/`Body`代入(`_vb_cstr()`経由)→`Send()`
という実コードを生成、それ以外は`_generate_unresolved_activity`の
`# TODO`へ委ねる(その詳細コメントにも新設フィールドを追記)。

**結果**: カバレッジ79%(23/29、知見97)→83%(24/29)へ向上。知見70の
未対応5活動は残り2件(ExcelWriteCellNode(※単独評価のみ、知見97参照)/
InvokeCodeNode)。回帰テスト追加(単純ケースの実コード生成・7種の
未確認フィールドそれぞれでのTODOフォールバック・実機フィクスチャでの
確認)、UiPath関連テスト全289件通過、リポジトリ全体で全1024件通過。

## 99. Flowchart実機XAMLキャプチャの試行が、VM側の環境要因(アクティブデスクトップの不在)でブロックされた——UiPath/XAML側の問題ではない(VM側の技術的制約、サブエージェントに委託して発見)

Flowchartのスコープ食い違い(残タスクA)に着手するにあたり、公式ドキュメント
(Microsoft Learn)自体が矛盾していることが判明した——「Flowchart
workflows」概念説明ページの例は`FlowStep.Next`/`FlowDecision.True`/
`.False`でノードを入れ子にする形だったが、`Flowchart`クラスのAPI定義
(`[ContentProperty("Nodes")]`、`Nodes`が平坦なFlowNodeリスト、`StartNode`
は別プロパティ)を見ると、実際には分岐の合流やループがある場合に
`x:Reference`で名前参照する直列化形になるはずで、単純な入れ子では
表現できない。この矛盾を解消するには実機キャプチャが必要と判断し
(知見31・39と同じ方針)、ユーザーに確認した上でVM実機キャプチャに着手した。

**試行結果(サブエージェントに委託、pad2py-pad-host VM)**: UIAツリーの
読み取り専用操作(ウィンドウ/コントロール一覧の取得等)は問題なく成功
したが、**マウス/キーボードでの入力操作(`pywinauto`の`click_input`等、
内部的に`SetCursorPos`を使う)が`RuntimeError: There is no active
desktop required for moving mouse cursor!`で即座に失敗**した。`query
session`で確認したところ、session 2が`tomoya_kaw`としてアクティブな
RDPセッションであり、コンソール(session 1)は切断状態だった——
`OpenInputDesktop`は有効なハンドルを返すにもかかわらず、実際の入力は
届かない。キーボードのみの`send_keys`は例外なく「成功」を報告したが、
選択したツリー項目への`Shift+F10`が実際にはどこにもコンテキストメニューを
開かなかったことから、キーボード入力の到達性も同様に信頼できないと確認
した——自動化プロセスがsession 2のアクティブな入力デスクトップに
アタッチされていない、という同じセッション分離の問題が原因と推定される。

**これはUiPath/XAMLの構造上の問題ではなく、VM側の環境要因**: Main.xaml・
Sub1.xaml構築時の過去の大量の`uipath-*` clipwireターゲット(ドラッグ&
ドロップ・クリック操作含む)が過去に成功していた実績があることから、この
入力到達性の問題は常に存在したわけではなく、**VM側のセッション状態
(誰が・いつアクティブなRDPセッションを握っているか)に依存する一時的な
制約**である可能性が高い——他セッションとの共有VMであることに起因する
競合と推定されるが、確定はできていない(知見38以前の「他セッションとの
共有、ハンズオン作業前に状況確認」という既存メモの運用方針が実際に
効いてくる場面)。

**対応**: サブエージェントはこの状況で自らRDPサインインする(本プロジェクトの
既存の境界、知見「PAD sign-in boundary」と同種の制約)ことはせず、クリーン
アップ(追加した一時ファイル・clipwireターゲットの削除、`xaml_probe`
プロジェクトが変更されていないことの確認)を完了した上でブロッカーとして
正直に報告するに留めた——架空のXAML構造をでっち上げて実装を進めることは
しなかった。

**追加確認(同日、軽量な読み取り専用チェックで再検証)**: 「他セッションが
RDPを掴んでいるだけで、手が空けば直るはず」という仮説を検証するため、
`query user`でセッション状態を再確認したところ、session 2(`tomoya_kaw`)
は`Active`→**`Disc`(切断済み)**に変わっていた——つまり、サブエージェント
が試行した時点とは状態が変わっている。しかし、この状態で同じ`pywinauto.
mouse.move`を再試行しても**全く同じ`RuntimeError: There is no active
desktop required for moving mouse cursor!`で失敗**した。これは「他セッション
がRDPを使い終われば直る」という単純な仮説を否定する——`Active`でも
`Disc`でも同じ失敗になるということは、問題は特定セッションの接続状態
そのものではなく、**clipwire-execの実行コンテキスト自体がどのセッションの
入力デスクトップにもアタッチされていない(Windowsのセッション0分離に近い
状況、サービスとして動いている場合に典型的)**という、より根本的な
VM側の構成要因である可能性が高い——ただし確定診断はしていない(VM
インフラの詳細設定は本プロジェクトの範囲外と判断し、これ以上は追わない)。

**現状**: Flowchartの実装はこの知見の時点で保留。単純な「待てば直る」
問題ではなく、人間によるVM側の直接確認(どのセッションがどう入力
デスクトップにアタッチされているか、あるいはclipd自体の実行コンテキスト
の見直し)が必要——自律ループでは安全に解消できない種類のブロッカーとして
記録する。

## 100. Flowchartの実際のXAML直列化形(`x:Name`/`x:Reference`/`Flowchart.StartNode`/`FlowStep.Next`/`FlowDecision.True`・`.False`/`FlowSwitch.Default`)を、VM不使用・実機GitHubコードから確定(知見99のVMブロッカーを別路線で回避)

知見99でVM実機キャプチャ(GUI操作)・ローカル.NET SDKでの検証がいずれも
環境要因でブロックされたため、**第三の経路**として「実際にUiPath
Studioで保存された、GitHub上に公開済みの実物の`.xaml`ファイル」を
`gh api search/code`で検索・直接取得して確認した——VM不使用、ローカル
インストール不要、既存ツールセットの範囲内。

**確認した実例**(いずれも実際にStudioが保存した生のXAML、手書きの
擬似コードではない):
1. `PacktPublishing/Robotic-Process-Automation-RPA-for-Developers`の
   `FlowchartDemo.xaml`(UiPath、分岐が合流し、さらに**ループ**して
   先頭に戻る実例——「もう一度試しますか?」という典型的なRPAパターン)
2. `dotnet/samples`の`PromotionalDiscountWorkflow.xaml`(Microsoft公式
   サンプル、`FlowSwitch`の実例——Flowchart.StartNode自身がこの
   Microsoft Learnページの例の元ネタ)
3. `shanuka27/Learn-RPA`の`FlowSwitch.xaml`(新しいUiPath Studioが
   保存した実例、`FlowSwitch`のケース`x:Key`がUiPath本体の`Switch`
   活動(知見21)と同じ**属性形**であることを確認)

**確定した直列化形**:
- `Flowchart.StartNode`はプロパティ要素。中身は最初のノードの**完全な
  定義**をそのままネストする場合(例1)と、別の場所で完全定義された
  ノードへの`<x:Reference>Name</x:Reference>`参照の場合(例2・3)の
  両方が実在する——「ノードが文書中で最初に出現した箇所がそのノードの
  本体定義、それ以降の出現は全て`x:Reference`参照」という原則が実際の
  配置を決める(StartNodeが本体を持つかただの参照かは、たまたま
  そこが最初の出現かどうかで決まるだけで、どちらも等価)。
- 各`FlowStep`/`FlowDecision`/`FlowSwitch`は`x:Name="__ReferenceIDN"`
  (Studioが振る自動生成名、連番)を持つ。本体定義は1回だけで、以降の
  参照は`{x:Reference Name}`(属性値としてのマークアップ拡張、例:
  `True="{x:Reference __ReferenceID0}"`)または`<Prop.Name><x:Reference>
  Name</x:Reference></Prop.Name>`(子要素形、例1の`FlowStep.Next`で
  両方の形が同一ファイル内に混在して実際に使われていた)のいずれか。
- `FlowStep`: 直接の子として実行する1つの活動(複数ステップなら
  `Sequence`でラップ——他のコンテナと同じ既知のパターン)+任意の
  `<FlowStep.Next>`(次のノード、無ければフロー終端)。
- `FlowDecision`: `Condition="[...]"`属性(`If`/`While`と全く同じVB式
  属性形、知見5・14と同じ規約)+`<FlowDecision.True>`/`.False>`
  プロパティ要素(各々1つのFlowNode、無ければ`# TODO`ではなくそのまま
  フロー終端——VBの意味論上`FlowDecision.True`/`.False`は省略可能)。
- `FlowSwitch`: `x:TypeArguments`+`Expression="[...]"`属性(例3、新しい
  Studioでは`VisualBasicValue`ラッパー経由のプロパティ要素形も実在する
  が、これはVB式ホスティング機構自体の版違い——知見36以来確認してきた
  パターンと同じ——であり、Flowchartグラフ構造自体の話ではない)。各
  ケースは`FlowSwitch`の直接の子`<FlowStep x:Key="...">`(属性形、
  知見21のUiPath本体`Switch`と同じ規約、例3で確認——古いMicrosoft公式
  サンプル(例2)は`<x:Key><x:String>...</x:String></x:Key>`という
  子要素形だったが、これはUiPath本体の`Switch`とは異なる書き方であり、
  UiPathのFlowSwitchが実際にこの古い形を使うかは未確認——両対応で
  パースする)。`<FlowSwitch.Default>`プロパティ要素(知見40の`Switch.
  Default`と同じ規約)。
- `Flowchart`自身の直接の子として、使われている全ノード名を列挙する
  フラットな`<x:Reference>Name</x:Reference>`の並び(`[ContentProperty
  ("Nodes")]`の実体)が存在する——これはグラフを辿れば自動的に分かる
  情報の重複であり、パース上は無視してよい(存在を無視して構わない、
  実害が無いことを確認済み)。

**合流・ループは実在する、かつ一般的**: 例1(UiPath自身の基本チュートリアル
相当のコード)が最初の実例として既に合流**とループ**の両方を含んでいた
ことから、「分岐が合流しない木構造」という限定的な前提は現実のFlowchartを
代表しない——知見99のVM試行開始時に想定していた「まず非循環の木構造だけ
安全側に対応する」という当初方針は撤回し、**一般のグラフ(循環含む)に
最初から対応する**設計へ変更した(Pythonには`goto`が無いため、ディスパッチ
ループ/状態機械パターン(`while _flow is not None: if _flow == 0: ...`)
で任意のグラフ形を構造的に表現する——でっち上げではなく、任意CFGを
構造化言語へ変換する標準的な手法)。

## 101. Flowchartの実コード生成を実装——ディスパッチループ(状態機械)パターンで循環・合流を含む一般のグラフに対応(VM不使用、知見100の直列化形確定を受けて実装完了)

知見100で確定したXAML直列化形(`x:Name`/`x:Reference`/`Flowchart.
StartNode`/`FlowStep.Next`/`FlowDecision.True`・`.False`/`FlowSwitch.
Default`)に基づき、`dump_daemon/uipath_dsl/types.py`・`xaml_tree.py`・
`dump_daemon/uipath_codegen/__init__.py`にFlowchartの実装を追加した。
これでPhase 1の決定文「対象ワークフロー種別: Sequence/Flowchartのみ」と
実装の食い違い(残タスクA、俯瞰レビューで発見)が解消した。

**IR(`types.py`)**: `FlowStepNode`(`body: list[Node]`+`next: FlowNode`)・
`FlowDecisionNode`(`condition: Expr`+`true_branch`/`false_branch:
FlowNode`)・`FlowSwitchArm`+`FlowSwitchNode`(`expression`/`type_arguments`
+`arms: list[FlowSwitchArm]`)・`FlowNode = FlowStepNode | FlowDecisionNode
| FlowSwitchNode | None`(再帰的な自己参照型)・`FlowchartNode`
(`variables`+`start: FlowNode`)を新設。`WorkflowFile.root`の型を
`SequenceNode | FlowchartNode`に拡張。`FlowNode`ファミリーは意図的に
既存の`Node`ユニオンへ含めない(Flowchartのグラフ構造と通常の子活動列は
別の関心事であり、`_generate_node`の通常ディスパッチには乗せない)。

**パース(`xaml_tree.py`)**: 知見30がState Machine用に見込んでいた
「名前→ノードのマップを先に構築してからx:Referenceを解決する2パス方式」
を初めて実装した——1パス目(`_flow_prescan_names`)は`elem.iter()`で
Flowchart全体をブランケット走査し、`x:Name`付きの`FlowStep`/
`FlowDecision`/`FlowSwitch`要素それぞれに型だけ確定した空のプレース
ホルダを登録する(前方参照でも型を知らずに誤った型のプレースホルダを
作ってしまう心配を無くす)。2パス目(`_parse_flowchart`本体)も同じ
`elem.iter()`ブランケット走査で、各ノード要素に出会うたびその
プレースホルダへ中身を埋める——ネストの深さに関わらず各ノードがちょうど
1回処理され、循環があっても`iter()`は単純な文書順走査なので無限ループ
しない。3つの参照形(属性値`{x:Reference Name}`、プロパティ要素+
`<x:Reference>Name</x:Reference>`子要素、プロパティ要素+ネストした
本体定義)はいずれも`_resolve_flow_target`/`_flow_node_from_element`が
統一的に解決する。

**コード生成(`uipath_codegen/__init__.py`)**: Pythonには`goto`/ラベルが
無いため、`_generate_flowchart`はディスパッチループ(状態機械)パターン
(`_flow`という一時変数+`while _flow is not None: if _flow == 0: ...
elif _flow == 1: ...`)へ変換する——任意のCFG(循環・合流含む)を構造化
言語で表現する標準的な手法で、でっち上げた簡略化ではない。各到達可能な
`FlowNode`に(オブジェクトの`id()`をキーにした辞書で)0始まりの整数
ラベルを振るため、同じノードオブジェクトが複数箇所から参照されていても
(合流・循環)同じラベルになり、正しく収束する。`FlowDecision`は`If`/
`While`と同じBoolean変換規則(知見61の`_vb_bool()`)、`FlowSwitch`は
`Switch`と同じ`_vb_cmp()`比較規則(知見77——公式ドキュメントが
`FlowSwitch<T>`を「`Switch<T>`と同様」と明記していることに基づく類推、
FlowSwitch自体の比較規則そのものは実機未確認のため、既知の前提として
記録する)を流用する。

**無限ループ回避の設計判断**: `FlowSwitch`で該当するcaseも`Default`も
無い場合(`Switch`では単に何もしないだけの意味論)、ディスパッチループ
では`_flow`を明示的に`None`へ倒す処理が必要——`_flow`を更新し忘れると
外側の`while`が同じ状態を永遠に再実行し無限ループになる(`FlowDecision`
は常に`True`/`False`いずれかの分岐へ入るため同じ問題は起きない)。
`Condition`/`Expression`が未設定の場合も同様に、でっち上げた既定分岐を
選ばず`# TODO`+安全な`_flow = None`終端に倒す(`DoWhile`の「Condition
未設定」ケース、知見38相当、と同じ方針)。

**複数ファイルBFS発見の対応**: `_discover_workflow_files`等が使う
`_iter_invoke_nodes`(知見88)はFlowchartのグラフを辿れないため、
`id()`ベースの`visited`集合で循環を安全に扱う`_iter_invoke_nodes_in_
flow`を新設し、`_iter_invoke_nodes_for_root`で`SequenceNode`/
`FlowchartNode`どちらのルートでも機能するようにした。

**テスト**: IRレベル(`_wrap_flowchart`ヘルパー、同じPythonオブジェクトを
複数箇所から参照させることで合流・循環を直接表現)・XAMLパースレベル
(知見100で確認した実機構造を模した合成XAML、実際に`parse_workflow_file`
→`generate_python`→`exec()`まで通した統合テスト)の両方で検証。
特に「caseもdefaultも無いFlowSwitch」「Condition未設定のFlowDecision」
という無限ループのリスクがある2経路は、実際に`exec()`してハングしない
(正しく終了する)ことまで確認した。UiPath関連テスト全297件通過、
リポジトリ全体で全1066件通過。

**今後の既知の限界**(でっち上げを避けて未対応のまま残したもの):
- `FlowSwitch`のケース`x:Key`が子要素形(`<x:Key><x:String>...</x:String>
  </x:Key>`、知見100の古いMicrosoft公式サンプルで確認)の場合は未対応
  (UiPath自身が実際にこの形を使うかは未確認のため、属性形のみ実装)
- `Flowchart`自体が通常アクティビティ(`Node`)の子としてネストする
  ケースは未対応(実機で未確認、Phase 1の決定は「ワークフロー種別」
  としてのFlowchartのみを指すと解釈)
- `FlowSwitch`の比較規則が`_vb_cmp()`と完全に一致するかは実機未確認
  (`Switch<T>`との類推のみ、上記参照)

## 102. `ui:Click`の`ClickType="CLICK_DOUBLE"`・`MouseButton="BTN_RIGHT"`/`"BTN_MIDDLE"`を実機XAML(GitHub実例)+pywinauto実ソースで確認し、実コード生成に対応(VM不使用、知見100の手法をClickへ再適用)

Flowchart(知見100・101)で確立した「`gh api search/code`でGitHub上の
実機保存済みXAMLを直接検索・確認する」という手法が、他の既知の限界にも
使えないか検証した。知見71で「実機確認済みの唯一の具体例
(`CLICK_SINGLE`/`BTN_LEFT`)以外は確証が無い」として`# TODO`に倒していた
`ui:Click`の`ClickType`/`MouseButton`属性を対象に試したところ、以下が
実際にUiPath Studioが保存した公開済みXAMLで確認できた:

- `ClickType="CLICK_DOUBLE"`(298件、`HarshadRanganathan/uipath-learning`
  等の実例で確認)
- `MouseButton="BTN_RIGHT"`(242件、`michalkulisiewicz/
  baselinker_subiekt_integrator`の実例で確認、同一ファイル内に
  `BTN_LEFT`と`BTN_RIGHT`が混在していた)
- `MouseButton="BTN_MIDDLE"`(6件のみだが実在)
- `ClickType="CLICK_UP"`/`"CLICK_DOWN"`も実在する(15件・27件)が、
  ドラッグ操作用に2つの別の`Click`活動(押し下げ→離す)と組み合わせて
  使われる可能性があり、単体での正確な対応は依然未確認のため今回は
  対象外のまま`# TODO`に残した
- `KeyModifiers="Ctrl"`等の非既定値も検索上は実在が示唆されたが
  (`"KeyModifiers=\"Ctrl\""`で658件)、実際に`ui:Click`要素上でこの値を
  確認できた実例を見つけられず、複数キー併用時の区切り文字等も不明の
  ままのため今回は対象外のまま`# TODO`に残した

**pywinauto側の確認**(VM不使用、インストール済みの実`pywinauto`パッケージ
のソースを直接確認——`.venv/lib/.../pywinauto/base_wrapper.py`・
`mouse.py`、これも「実機確認」に類する確度の高いソース、知見97の
openpyxl確認と同じ手法): `click_input(button="left"/"right"/"middle",
double=False/True, ..., pressed="")`。`pressed`は空白区切りの
`"control"`/`"shift"`/`"alt"`(小文字、`mouse.py`の`pressed.lower().
split()`で確認)——これがUiPathの`KeyModifiers`値とどう対応するかは
依然未確認のため、`KeyModifiers`の非既定値には今回は手を出さなかった。

**余談**: pywinautoの`_set_cursor_pos`のコメント「`handles non-active
desktop case`」と、実際のエラーメッセージ生成コードを確認したところ、
知見99でVM実機キャプチャ中に遭遇した`RuntimeError: There is no active
desktop required for moving mouse cursor!`は、`win32api.SetCursorPos`が
返す`pywintypes.error`をpywinauto自身がこの特定の既知のケース向けに
翻訳した文言だと確定した——「アクティブな入力デスクトップにアタッチ
されていないプロセスからの入力注入」という一般的に知られたWindowsの
制約に対するpywinauto側の既知の対処だったと分かる(知見99の推測を
裏付ける追加確認、VM側の問題解決には直結しないが原因の理解を深めた)。

**修正**(`dump_daemon/uipath_codegen/__init__.py`): `_CLICK_TYPE_KWARGS`/
`_MOUSE_BUTTON_KWARGS`辞書を新設し、`_generate_click_body`が確認済みの
値の組み合わせから`click_input()`の実引数(`button=`/`double=`)を組み立てる
よう変更。`KeyModifiers`の確認済み既定値チェックは変更せず(引き続き
`"None"`のみ安全)。回帰テスト追加(確認済み4通りの組み合わせの実コード
生成、`CLICK_UP`・`KeyModifiers="Ctrl"`が引き続きTODOに倒れることの確認)、
UiPath関連テスト全300件通過、リポジトリ全体で全1071件通過。

**この知見で確定したこと**: 知見100で確立した「GitHub上の実機保存済み
XAMLを直接検索する」手法は、Flowchart固有の問題ではなく、UiPathの
あらゆる「実機確認が無く`# TODO`に倒していた属性値」に対して一般的に
有効な調査手法だと分かった——知見71・73で未確認のまま残していた他の
`ui:Click`属性(`AlterIfDisabled`/`CursorMotionType`/`DelayBefore`/
`DelayMS`/`SendWindowMessages`/`SimulateClick`)や、他のアクティビティの
未確認の値についても、同じ手法で追加調査する価値がある。

## 103. `SendOutlookMailNode`の`Importance`/`Sensitivity`非既定値・`IsBodyHtml`/`IsDraft="True"`・`Cc`/`Bcc`を実機XAML(GitHub実例)で確認し、実コード生成に対応(VM不使用、知見102の手法を再適用)

知見102に続き、「GitHub上の実機保存済みXAMLを直接検索する」手法を
`SendOutlookMailNode`(知見98で`Cc`/`Bcc`未設定・既定値構成のみに限定
していた)へ再適用した。`gh api search/code`で以下が実際にUiPath
Studioが保存した公開済みXAMLで確認できた(`d6wv28/RPA_Repo`の
`SendEmailDuplicatesAndExceptions.xaml`が1つの要素で`Importance="High"`・
`IsBodyHtml="True"`・`Cc`設定済みを同時に示す決定的な実例):

- `Importance="High"`(6件)/`"Low"`(1件)
- `Sensitivity="Personal"`(4件)/`"Confidential"`(1件)
- `IsBodyHtml="True"`(上記実例で確認)
- `IsDraft="True"`(10件)
- `Cc`/`Bcc`が実際に設定されている実例(`Cc="[in_Config(&quot;
  ExceptionEmailTo&quot;).ToString]"`)

**Outlook側の確認**(Microsoft Learn Outlook VBAリファレンス、VM不使用):
`MailItem.CC`/`.BCC`(Stringプロパティ、Read/write、表示名のカンマ/
セミコロン区切りリスト)・`MailItem.HTMLBody`(Stringプロパティ、
`Body`の代わりに使うとHTML本文になる)・`MailItem.Save`(新規アイテムを
既定フォルダ(Drafts)へ保存するだけで送信しない——`IsDraft="True"`時の
挙動として確定)。

**修正**(`dump_daemon/uipath_codegen/__init__.py`): `_OUTLOOK_IMPORTANCE_
VALUES`/`_OUTLOOK_SENSITIVITY_VALUES`(知見98で確認済みの整数マッピング
全体を解放、以前は`"Normal"`のみ許可)・`_OUTLOOK_BOOL_VALUES`を新設。
`_generate_send_outlook_mail`が`IsBodyHtml`に応じて`.Body`/`.HTMLBody`
を切り替え、`Cc`/`Bcc`が設定されていれば`.CC`/`.BCC`へ代入、`IsDraft`に
応じて`.Send()`/`.Save()`を切り替えるよう変更。`Files`に添付がある
場合のみ(添付の追加方法が実機未確認のため)`# TODO`へ倒す——これが
`SendOutlookMailNode`の唯一残る未対応ケースになった。

回帰テスト更新・追加(Cc/Bcc/Importance(Low/High)/Sensitivity(Personal/
Confidential)/IsBodyHtml/IsDraftそれぞれの実コード生成確認)、UiPath
関連テスト全302件通過、リポジトリ全体で全1073件通過。

## 104. `HttpClientNode`の`Body`・`Headers`(populated時)を実機XAML(GitHub実例)で確認し、実コード生成に対応(VM不使用、知見100の手法を再適用)

知見102・103に続き、「GitHub上の実機保存済みXAMLを直接検索する」手法を
`HttpClientNode`(知見96で`Headers`等のコレクションが全て空・`Body`
未設定という最も単純な構成のみに限定していた)へ再適用した。

**`Body`の実例**(`vajrang-b/UiPathIn30Days`の`MistralApi/Main.xaml`):
`Body="[text]"`というVB式属性が実際に設定されたPOSTリクエストの実例を
確認——`BodyFormat="application/json"`と組み合わせて使われていた。

**`Headers`のpopulated時の実直列化形**(2つの異なる実例で確認):
`<ui:HttpClient.Headers>`が空の場合は`<scg:Dictionary x:TypeArguments=
"x:String, InArgument(x:String)" />`(子要素なしの自己終了タグ)だが、
populated時はこの`scg:Dictionary`ラッパー自体が無くなり、各エントリが
直接の子`<InArgument x:Key="...">`になる——値の直列化形は2つの実例で
異なっており、両方が実在する:
- 直接テキスト形: `<InArgument x:TypeArguments="x:String" x:Key=
  "content-Type">application/json</InArgument>`
  (`VamsiyadavChakka/OrchestratorAPI-s`の実例、同じ要素が`Parameters`
  にも全く同じ形で使われていた)
- ネストした`<Literal>`子要素形: `<InArgument x:TypeArguments="x:String"
  x:Key="Content-Type"><Literal x:TypeArguments="x:String">text/plain
  </Literal></InArgument>`(`vajrang-b/UiPathIn30Days`の実例)

**修正**(`dump_daemon/uipath_dsl/types.py`・`xaml_tree.py`・
`uipath_codegen/__init__.py`): `HttpClientNode.headers: dict[str, Expr]`
を新設。`_http_client_dict_entries()`が両方の値直列化形に対応して
パースする。`_generate_http_client`は`Body`を`requests`の`data=`引数へ、
`headers`を辞書リテラルの`headers=`引数へ変換する——`BodyFormat`/
`AcceptFormat`がHTTPヘッダーへどう反映されるか(`Content-Type`の自動
設定等)はコミュニティ情報が相互に矛盾しており未確認のため、でっち上げた
自動注入はしない(`Headers`に明示的に無ければ`requests`自身の既定動作
(未設定)に委ねる)。`Cookies`/`Parameters`/`UrlSegments`/`Attachments`
(`Parameters`は`Headers`と全く同じ`InArgument x:Key`形と確認できたが、
populated時の意味論——クエリ文字列かフォームデータか等——は未確認の
ため、今回は対象外のまま)のいずれかにエントリがある場合のみ、引き続き
`# TODO`へ倒す。

回帰テスト更新・追加(Body/Headers単体それぞれの実コード生成確認)、
UiPath関連テスト全304件通過、リポジトリ全体で全1075件通過。

**この知見で確定したこと**: 知見100で確立した調査手法(GitHub実例検索)
は、知見102(Click)・知見103(SendOutlookMail)・本知見(HttpClient)と
4回連続で異なるアクティビティに対して実証的に有効だった——「実機確認が
無く`# TODO`に倒していた属性値」という本プロジェクト全体に共通するパターン
に対する、汎用的で安価な調査手法として確立したと言える。

## 105. `ui:Click.CursorPosition`の`Position="TopLeft"`+`OffsetX`/`OffsetY`を実機XAML(GitHub実例)で確認し、実コード生成に対応(VM不使用、知見100の手法を再適用)

知見102〜104に続き、「GitHub上の実機保存済みXAMLを直接検索する」手法を
`ui:Click.CursorPosition`(知見73で`"Center"`のみに限定していた)へ
再適用した。`gh api search/code`で`Position="TopLeft"`
(574件)・`"TopRight"`(84件)・`"BottomLeft"`(33件)・`"BottomRight"`
(40件)・`"Custom"`(2件)が実際にUiPath Studioが保存した公開済みXAMLで
確認できた。

**実例の詳細**(`PacktPublishing/Robotic-Process-Automation-Projects`の
`ZOHOAutomation.xaml`): `<ui:CursorPosition OffsetX="5" OffsetY="8"
Position="TopLeft" />`(属性形)という実例を2件確認。同じファイル内に
`Position="Center"`で`OffsetX`/`OffsetY`が`<CursorPosition.OffsetX>
<InArgument x:TypeArguments="x:Int32" /></CursorPosition.OffsetX>`
(プロパティ要素形、`InArgument`が空=未設定)という実例もあり——
`Center`時のオフセットは実際には未設定のままだった(知見73の既存の
「`Center`はオフセット無し」という前提と整合、新しい矛盾は見つからず)。

**pywinauto側の確認**(VM不使用、インストール済みの実`pywinauto`ソース):
`click_input(coords=...)`は未指定時`width()/2`・`height()/2`(クライアント
座標系、原点は要素の左上)で中心を計算してから`client_to_screen`する
——つまり`coords`パラメータは常に**要素の左上を原点とする座標**を期待する。
したがって`Position="TopLeft"`+`OffsetX`/`OffsetY`は`coords=(offsetX,
offsetY)`へ符号の曖昧性なくそのままマッピングできる、唯一の非`Center`値
だと確定した。`TopRight`/`BottomLeft`/`BottomRight`はオフセットがどちらの
方向に数えるか(右端から減算か、それとも別の規約か)が実機未確認のため
対象外のまま。

**修正**(`dump_daemon/uipath_dsl/types.py`・`xaml_tree.py`・
`uipath_codegen/__init__.py`): `ClickNode`に`cursor_offset_x`/
`cursor_offset_y`を追加(属性形・プロパティ要素形の両方に対応する
`_cursor_offset()`ヘルパー経由)。`_generate_click_body`は`Position=
"TopLeft"`の場合に`coords=(x, y)`を実際に生成する。`Center`に非`None`の
オフセットが付いている(実機未確認の組み合わせ)場合も安全側に`# TODO`
へ倒すようにした——知見92〜95と同じ「捕捉済みデータを隠さない」観点の
延長で、既存の「`Center`は常にオフセット無し」という前提が崩れた場合に
サイレントに誤変換しないための防御。

回帰テスト追加(TopLeft+オフセットの実コード生成・オフセット省略時の
既定`(0, 0)`・TopRight/Center+オフセット組み合わせ/非整数オフセットの
TODOフォールバック)、UiPath関連テスト全308件通過、リポジトリ全体で
全1087件通過。

**この知見で確定したこと**: 知見100の調査手法は5回連続(Flowchart・
Click ClickType/MouseButton・SendOutlookMail・HttpClient・本知見の
CursorPosition)で異なる種類の「実機確認が無く`# TODO`に倒していた
属性値」を解消できた——UiPath/.NETエコシステム全体でGitHub上に大量の
実プロジェクトが公開されていることを活かした、本プロジェクトにとって
VM実機キャプチャに次ぐ(多くの場合VMより手軽な)第二の確度の高い検証
手段として確立したと言える。

## 106. `ui:Click`の`DelayBefore`を実機XAML(GitHub実例)+公式ドキュメントで確認し、実コード生成に対応——`DelayMS`は公式ドキュメントに記載が無く意味論不明と判明(VM不使用、知見100の手法を再適用)

知見102・105に続き、「GitHub上の実機保存済みXAMLを直接検索する」手法を
`ui:Click`の残る未対応属性(`DelayBefore`/`DelayMS`/`SendWindowMessages`/
`SimulateClick`/`AlterIfDisabled`、知見73で未確認のまま記録)へ適用した。

**`SimulateClick`/`SendWindowMessages`は見送り**: 実際に`SimulateClick=
"True"`(2888件)・`SendWindowMessages="True"`(322件)が実在することは
確認できたが、UiPath公式ドキュメント(docs.uipath.com)はこれらの属性の
存在と既定値(`False`)のみ記載し、**内部的な実装機構には触れていない**。
コミュニティ情報(フォーラム)は「マウスドライバに依存しない」「一部の
アプリケーションでは効かない」という大まかな挙動は一致して述べるが、
正確な実現方式(pywinautoの`.invoke()`(UIA Invoke pattern)に相当するか、
`.click()`(Windowsメッセージ送信)に相当するか)は確定できなかった——
知見69のような単純な構造確認と違い、これは実行時の挙動そのものに関わる
ため、類推だけで実装するとでっち上げになるリスクが高いと判断し見送った。

**`DelayBefore`は実装**: UiPath公式ドキュメント
(docs.uipath.com/activities/other/latest/ui-automation/click)で
「活動が何らかの操作を始める前の待機時間(ミリ秒)、既定200ms」と確認
済み。`gh api search/code`で`DelayBefore="2000"`等の実例(448件)も確認。
`time.sleep(ms / 1000.0)`へマッピングする、確度の高い単純な変換。

**`DelayMS`は見送り**: `DelayBefore`と違い、UiPath公式ドキュメントの
Click活動ページに**全く記載が無い**(検索結果「The document doesn't
include a DelayMS property」)。`DelayBefore`/`DelayMS`は実機XAMLでは独立
して設定されうる(片方だけ設定、もう片方`{x:Null}`の実例をそれぞれ
確認済み)ため、同じ属性の別名ではなく別の意味を持つプロパティだと
推定されるが、具体的に何を指すか(クリック動作自体の持続時間か、別の
タイムアウトか)が確認できないため、でっち上げず捕捉のみ・コード生成は
`# TODO`へ倒す。

**両属性とも`{x:Null}`がnullable(未設定)の直列化形**(他の`Click`
列挙型属性(`ClickType`等)とは異なり、知見71で確認した「Studioは常に
具体的な値を直列化する」非nullable型ではない)——`_attr_expr()`経由で
`Expr`として捕捉し、既存の`{x:Null}`→`None`変換規約(知見13)をそのまま
適用できた。

**修正**(`dump_daemon/uipath_dsl/types.py`・`xaml_tree.py`・
`uipath_codegen/__init__.py`): `ClickNode`に`delay_before`/`delay_ms`
(`Expr`)を追加。`_generate_click_body`は`delay_before`が設定されていれば
`click_input()`呼び出しの直前に`time.sleep()`を追記し、`delay_ms`が
設定されていれば(意味論未確認のため)`# TODO`へ倒す。

回帰テスト追加(DelayBefore単体の実コード生成・DelayMSのTODOフォール
バック)、UiPath関連テスト全310件通過、リポジトリ全体で全1089件通過
(他セッションが並行作業中のPAD側テスト1件の失敗は本変更と無関係——
`dump_daemon/pad_codegen/actions/text.py`が原因、本コミットには含めない)。

**この知見で確定したこと**: 知見100の調査手法は、XAML構造・属性値の
存在確認には非常に有効だが、**実行時の内部動作メカニズムの確認には
限界がある**(`SimulateClick`/`SendWindowMessages`のケース)——構造的な
事実(属性名・値・直列化形)はGitHub実例で高確度に確定できるが、「その
値が実際に何をするか」は公式ドキュメントまたはVM実機検証が無い限り、
類推に留め実装を見送るべきという判断基準を明確化した。

## 107. `ui:MessageBox`の`Buttons`/`ChosenButton`を公式ドキュメント+実機XAML(GitHub実例)で確認し、サイレントな選択結果の消失を防止(VM不使用、知見100の手法を再適用)

知見79・80に続き、`ui:MessageBox`の残る未確認属性を調査した。
`MessageBoxNode`の`_generate_message_box`は非対話的な`print()`への
変換(v1の暫定選択、知見79のdocstring参照)だが、`Buttons`(ダイアログに
表示する選択肢)と`ChosenButton`(ユーザーが選んだ結果を束縛する
OutArgument)の両属性がこれまで全く捕捉されていなかった——`Buttons`が
単一の`"Ok"`以外(例: `"YesNo"`)で、かつワークフローが`ChosenButton`の
結果を使って分岐している場合、`print()`への変換はその分岐の意味論を
サイレントに失う(知見92〜95と同じ「捕捉済みデータの未活用」ではなく、
「そもそも捕捉すらしていなかった」ケース)。

**確認内容**: UiPath公式ドキュメント(docs.uipath.comの検索結果)で
`ChosenButton`の戻り値が`"Ok"`/`"Yes"`/`"No"`/`"Cancel"`のいずれかと
確認済み。`gh api search/code`で`Buttons="YesNo"`+`ChosenButton="[式]"`
という実際の使用パターン(196件、`Apress/Robotic-Process-Automation-
Using-UiPath-StudioX`の実例)・`Buttons="OkCancel"`(64件)・
`Buttons="YesNoCancel"`(33件)を確認。

**実装しなかったもの**: `ChosenButton`の実際の値(ユーザーが実行時に
どのボタンを押すか)を再現する手段(`input()`等によるユーザー入力の
でっち上げ)は、`print()`という非対話的な変換方式の設計そのものと
矛盾するため実装しない——これはAPIマッピングの確認問題ではなく、
v1のMessageBox変換方式自体の設計判断(知見79のdocstringが既に
「将来tkinter等の実モーダルダイアログへ差し替える余地を残す」と
明記している範囲)。

**修正**(`dump_daemon/uipath_dsl/types.py`・`xaml_tree.py`・
`uipath_codegen/__init__.py`): `MessageBoxNode`に`buttons`/
`chosen_button`を追加して捕捉するようにした。`_generate_message_box`は
`Buttons`が単一ボタン(`"Ok"`、実機フィクスチャ確認済みの既定)以外、
または`ChosenButton`が実際に変数へ束縛されている場合に`# TODO`へ倒す
——選択の分岐をサイレントに失うより、「このMessageBoxは手動で見直す
必要がある」と明示する。既存の実機フィクスチャ(全て単一`Ok`ボタン・
`ChosenButton`未使用)は影響を受けず、引き続き`print()`を生成する。

回帰テスト追加(Buttons非既定値・ChosenButton束縛済みそれぞれのTODO
フォールバック確認)、UiPath関連テスト全313件通過、リポジトリ全体で
全1109件通過。

## 108. `Append Line`/`Read Text File`の`Encoding`/`UseDefaultEncoding`を公式ドキュメントで確認し、実在するエンコーディング食い違いバグを発見・修正(VM不使用、知見100の手法を再適用)

知見107に続き、`ui:AppendLine`/`ui:ReadTextFile`の既存コード生成ロジック
を読み返したところ、`Encoding`/`UseDefaultEncoding`属性が一切捕捉されて
おらず、`encoding="utf-8"`が無条件にハードコードされていたと判明した
——これは単なる「捕捉済みデータの未活用」(知見92〜95)ではなく、
**実在する属性自体を一度も見ていなかった**ケースで、知見107のMessageBox
と同系統の発見。

**公式ドキュメントで確認**(docs.uipath.com、VM不使用): `Append Line`は
`Encoding`/`UseDefaultEncoding`の両方を持つ——`UseDefaultEncoding=True`
(既定)ならOSの既定エンコーディング、`False`で`Encoding`未指定なら
(BOM検出に失敗した場合)**UTF-8**が既定として選ばれる、と明記。一方
`Read Text File`は`Encoding`のみ持ち(`UseDefaultEncoding`相当のプロパティ
は存在しない)、`Encoding`未指定時の既定はBOM検出→失敗時は**システムの
ANSIコードページ**(UTF-8とは異なる)と明記。

**発見した実在するバグ**: 実機フィクスチャ(`Main.xaml`)の`Append Line`
は`UseDefaultEncoding="False"`・`Encoding`未指定で、この組み合わせの
確定済みの既定(UTF-8)と既存のハードコード`encoding="utf-8"`がたまたま
一致していたため、これまで発覚していなかった。しかし`UseDefaultEncoding
=True`(既定値、`Append Line`の最も基本的な使い方)の場合は本来OSの既定
エンコーディングになるはずで、無条件の`utf-8`ハードコードと食い違って
いた——実機フィクスチャにこの組み合わせの実例が無かったことによる
既知のギャップ(他の多くの知見と違い、今回は実機データでの確認ではなく
公式ドキュメントとの読み合わせで発覚)。

**修正**(`dump_daemon/uipath_dsl/types.py`・`xaml_tree.py`・
`uipath_codegen/__init__.py`): `AppendLineNode`に`encoding`/
`use_default_encoding`、`ReadTextFileNode`に`encoding`を追加して捕捉。
`_resolve_append_line_encoding()`が確定済みの組み合わせ(`False`+未指定
→`"utf-8"`、`True`/未設定→`None`=kwarg自体を付けずOS既定に委ねる、
`Encoding="UTF-8"`明示→`"utf-8"`)だけをマッピングし、それ以外
(`"Unicode"`等の未確認のエンコーディング名)は`# TODO`へ倒す。
`ReadTextFile`は既存の`encoding="utf-8"`ハードコード(実機フィクスチャの
round-trip(`Append Line`が書いたUTF-8ファイルを読む)で正しく動作する
ことを確認済み)はそのまま変更せず、`Encoding`が確認済みの`"UTF-8"`
以外に明示的に設定されている場合のみ`# TODO`へ倒す——既存の確認済み
動作を壊さない範囲での最小限の修正に留めた。

回帰テスト追加(`UseDefaultEncoding`4パターンの解決確認・未確認
エンコーディング名のTODOフォールバック)、UiPath関連テスト全319件通過、
リポジトリ全体で全1123件通過。

**この知見で確定したこと**: 知見100の調査手法(GitHub実例検索)は構造・
値の実在確認に強いが、本知見は**既存コードを公式ドキュメントと読み合わせる
だけで発見できた**(知見76〜78・86〜88と同系統の「既存実装の読み返し」
手法)——両方の手法を併用する価値を改めて確認した。

## 109. `Invoke Workflow File`の`Isolated`属性が、`Out`/`InOutArgument`のByRef限界(知見78)とは別の軸で参照共有セマンティクスに影響することを公式ドキュメントで発見——実機での使用頻度が低いため記録のみ、コード変更は見送り(VM不使用)

知見100の手法(`gh api search/code`)を`ui:InvokeWorkflowFile`の未確認
属性に適用する過程で、`shanuka27/Learn-RPA`の実例に`UnSafe="False"`
という未確認の属性(公式ドキュメントに記載無し、内部的/非公開の属性と
推定——これ自体は見送り)を見つけたのをきっかけに、関連する公式
ドキュメント調査で`Isolated`という別の重要な属性の存在を発見した。

**公式ドキュメントで確認**: `Isolated`プロパティ(既定`False`)は
「分離実行されたワークフローは親と異なるセッションで起動できる」ことを
制御する。重要な記載:「`Isolated=False`(非分離)の場合、呼び出し先への
引数渡しは**参照渡し**になる——呼び出し先ワークフロー内でオブジェクトを
変更すると、メインワークフロー側のオブジェクトも変更される」「分離
ワークフロー間ではシリアライズ不可能な型(`UIBrowser`/`UIElement`等)を
渡せない」。

**知見78との関係**: 知見78は「`Out`/`InOutArgument`方向の引数がPythonの
値渡しでは呼び出し元へ書き戻されない」という限界を記録したが、これは
`Isolated=False`(確認済みの既定)という前提の上に成り立つ、より広い
事実の一部だと分かった——VBの非分離`Invoke Workflow File`は、`In`方向の
引数であっても**参照型(クラス・リスト・ディクショナリ等)なら呼び出し先
での変更が呼び出し元に伝播する**(C#/VBの参照型セマンティクスそのもの)。
Pythonも可変コンテナ型(`list`/`dict`等)は同様の参照共有セマンティクスを
持つため、**この特定のケースでは偶然Python側の既存の関数呼び出し規約が
VBの挙動と一致している**可能性が高い(両言語とも「オブジェクト参照の
値渡し」という同じモデルのため)——ただし文字列・数値等の不変型では
両言語とも値渡しの挙動になり一致する。したがって知見78が本当に問題に
なるのは「不変型(文字列・数値)を`Out`/`InOutArgument`として使う場合」
に限られる可能性が高いと今回の調査で分かった(ただし`Isolated=True`
(分離実行)の場合は挙動が変わる可能性があり、その相互作用は未検証)。

**コード変更は見送り**: `gh api search/code`で`Isolated="True"`
(0件)・`Isolated="False"`(1件のみ)を確認——実機での明示的な使用は
極めて稀(多くの場合、既定値のまま省略されていると推定)。この属性を
捕捉・警告文に反映する価値はあるが、「参照型 vs 値型」を静的に判別する
には型追跡が必要(知見74の配列添字曖昧性と同じ種類の、型情報が無いと
解決できない問題)で、現時点では過剰な実装になると判断し、知見として
記録するのみでコード変更は見送った。

## 110. `ui:TypeInto`を実機XAML(GitHub実例、`UiPath/skills`公式リポジトリ含む)+公式ドキュメント(UI Automationの入力方式)で確認し、実コード生成に対応——UiPath機能カタログ(design/uipath_feature_catalog.md)のTier A最優先項目への着手第1件(VM不使用、知見100の手法を再適用)

[design/uipath_feature_catalog.md](uipath_feature_catalog.md)のTier A
(「UI Automation Classic基本活動の残り」)の最初の実装対象として、
`Click`(知見100-106)に続く2件目のUI Automation Classic基本活動として
`ui:TypeInto`を調査・実装した。

**`gh api search/code`で確認した属性一覧**: `UiPath/skills`公式リポジトリ
(2026年、`activity-packages/classic-typeinto-field-not-cleared`という
Classicパッケージ専用のテストフィクスチャ)を含む複数件の実機保存済み
XAMLを確認した結果、以下の属性は全て`{x:Null}`として直列化される実例が
ある(nullable、知見106と同じ理由で`_attr_expr`経由で捕捉する必要がある):
`ClickBeforeTyping`/`EmptyField`/`SimulateType`/`SendWindowMessages`/
`DelayBefore`/`DelayMS`/`DelayBetweenKeys`/`AlterIfDisabled`/
`ContinueOnError`/`ActivateBefore`。

**`Activate`/`ActivateBefore`の表記揺れ**: `UiPath/skills`(最新)は
`ActivateBefore`を使うが、2017〜2021年頃の複数のサードパーティ
リポジトリは同じ意味で`Activate`という属性名を使っている——パッケージ
バージョン間でのリネームと推定(確証は取れていないが、両方を同じ
フィールドとして受け入れることで実害は無い)。

**`ClickBeforeTyping`の値セット**: `{x:Null}`/`"False"`/`"True"`/
`"NONE"`の4種を実機で確認。`"NONE"`が`False`相当の別表記か将来の3値
enumの一部かは未確定だが、「クリックしない」という解釈は4値とも安全側で
一致するため、`"True"`以外を全て「クリックしない」として扱った。

**公式ドキュメントで確認(入力方式)**: docs.uipath.comの
「UI Automationの入力方式」ページで、既定の入力方式を「ハードウェア
ドライバー経由のシミュレート」(Hardware Events、フォアグラウンド必須)と
明言していると確認した——これは`pywinauto`の`type_keys()`(`SendInput`を
使う、`Click`の`click_input()`と同系統、知見71-73で既に実コード生成に
使っている既定経路と同じ機構)と一致する。`Click`の`SimulateClick`/
`SendWindowMessages`では「既定値の正確な機構」自体が未確認だったのに対し、
`TypeInto`ではこの一点が公式ドキュメントで確認できた、という違いがある
(知見で記録しておく価値のある非対称性)。ただし`SimulateType`/
`SendWindowMessages`が`True`の場合の具体的なAPI(「対象アプリ自身の
技術を使う」等、何のAPIかは記載無し)は依然未確認のため、`Click`と同じ
理由でコード生成は見送り(`# TODO`)。

**`Activate`の意味論**: 同ページで「既定でチェック済み、外すと入力は
現在アクティブなウィンドウへ送られる」と確認——`pywinauto`の
`type_keys()`の`set_foreground`引数(既定`True`)と対応付けられる。
確認済みの`"True"`/未設定は既定のままkwarg無し、確認済みの`"False"`のみ
`set_foreground=False`を明示する。

**`EmptyField`は見送り**: `True`時にUiPathが実際に使うフィールド消去
手段(`SetValue("")`なのか選択範囲+削除なのか)が未確認のため、`Click`の
方針と同じく確認済みの既定値(`None`/`"False"`)のみ対応し、`True`は
`# TODO`に倒した。

**`type_keys()`の特殊文字エスケープが必須**: `pywinauto`の`type_keys()`は
`~^%+(){}`を独自の特殊キー構文として解釈する——これは本プロジェクトが
PAD調査時に既に発見していた罠(`dump_daemon/pad_ui_helpers.py`の
`set_vb_expression_field`docstring参照)と同一で、`TypeInto`の生成コードに
そのまま当てはまる。`Text`の実行時の値(リテラルでもVB式でも)が安全だと
静的に保証できないため、コード生成側は常に新設の
`_pywinauto_type_keys_escape`ヘルパー(`{`/`}`自身も含め各特殊文字を
`{c}`で囲む)を経由させる——他の`VB_*`ヘルパーと同じ「使用時のみ注入」
方式(`_collect_imports`)。

`dump_daemon/uipath_dsl/types.py`に`TypeIntoNode`、`xaml_tree.py`に
`_parse_type_into`(`(UI_NS, "TypeInto")`へディスパッチ登録)、
`uipath_codegen/__init__.py`に`_generate_type_into`を追加。
`tests/test_uipath_dsl.py`に2件・`tests/test_uipath_codegen.py`に24件
追加、全1158件通過。

## 111. `ui:GetText`を実機XAML(GitHub実例、`UiPath/skills`公式リポジトリ含む)+公式ドキュメントで確認し、実コード生成に対応——Tier A着手第2件(VM不使用、知見100の手法を8回目として再適用)

[design/uipath_feature_catalog.md](uipath_feature_catalog.md)のTier A
3件目(`Click`→`TypeInto`→`GetText`)。`gh api search/code`で
`UiPath/skills`公式リポジトリの複数件(`classic-browserscope-efail`/
`classic-typeinto-field-not-cleared`/`classic-click-noop-simulate`の
各`process/Main.xaml`)を確認し、`ui:GetText`は`ContinueOnError`/
`DelayBefore`/`DelayMS`(いずれも`{x:Null}`実例ありnullable)のみという
単純な構造だと確定した——`TypeInto`のような追加オプションは無い。

**ドキュメント用語と実属性名の食い違い**: 公式ドキュメント(docs.uipath.com
の`get-value`ページ)は裏のCLR型を`UiPath.Core.Activities.GetValue`、
出力プロパティ名を`Value`と記載しているが、実機XAML上の属性名は4件
全て一貫して`Text`——知見29(`HttpClient`のDisplayNameとCLR型名の不一致)
と同種のケース。本パーサー・コード生成は実機確認済みの`Text`を信頼する。

同ドキュメントは抽出の正確なAPI(UIAの`Name`/`ValuePattern`かWin32の
`GetWindowText`か等)は明記していないが、「可視テキストを最大4096文字
抽出する」という挙動は確認できた。`Click`のセレクタ解決と同じ「要素を
一意に特定できることまでは主張しない」方針を踏襲し、`pywinauto`の
`window_text()`(バックエンドに応じて適切なAPIへ自動ディスパッチする
標準的なアクセサ)を`# WARNING`付きで採用した——1対1の機構確認までは
主張しない。

`dump_daemon/uipath_dsl/types.py`に`GetTextNode`、`xaml_tree.py`に
`_parse_get_text`(`(UI_NS, "GetText")`へディスパッチ登録)、
`uipath_codegen/__init__.py`に`_generate_get_text`を追加。
`tests/test_uipath_dsl.py`に1件・`tests/test_uipath_codegen.py`に8件
追加、全1174件通過。

## 112. `ui:SelectItem`を実機XAML(GitHub実例、`UiPath/skills`公式リポジトリ含む)+公式ドキュメントで確認し、実コード生成に対応——Tier A着手第3件(VM不使用、知見100の手法を9回目として再適用)

[design/uipath_feature_catalog.md](uipath_feature_catalog.md)のTier A
4件目(`Click`→`TypeInto`→`GetText`→`SelectItem`)。`gh api search/code`で
`UiPath/skills`公式リポジトリ含む複数件の実機保存済みXAMLを確認し、
`ContinueOnError`/`DelayAfter`/`DelayBefore`/`Items`はいずれも`{x:Null}`
実例ありでnullable、`Item`(選択する値、リテラル・`VbExpr`の両方の実例
あり)が本体という構造だと確定した。`Items`(ドロップダウン等の選択可能な
項目一覧、`<ui:SelectItem.Items><scg:List>...`形)はStudioが記録時に
キャプチャした設計時スナップショットで実行時には使われないため捕捉対象
としない。

**`AlterIfDisabled`が`Click`/`TypeInto`と違い確認済み**: 公式ドキュメント
(`select-item`ページ)に「本活動は入力方式が`SimulateClick`固定で
ユーザーが変更できず、無効化された要素も既定で操作対象になる」と明記
されている——実機XAML(`UiPath/skills`)でも`AlterIfDisabled="True"`という
明示的な実例を確認した。`Click`/`TypeInto`では同じ属性が「未文書化の
ため常に見送り」だったのに対し、`SelectItem`ではこれが確認済みの既定
という違いがある。逆の`"False"`(無効化要素を操作しない)は`pywinauto`の
`.select()`でそれを再現する手段が未確認のため`# TODO`へ倒した。

**`Item`選択の実装手段**: 公式ドキュメントが「`SimulateClick`=対象アプリ
自身の技術を使う」と明言している——`Click`の`SimulateClick`(機構未確認
のため見送り)とは違い、`pywinauto`の`.select()`(Win32の
`ComboBoxWrapper`は`CB_SELECTSTRING`等のネイティブメッセージ、UIAは
`SelectionItemPattern.Select()`——いずれも「対象のネイティブAPIを直接
呼ぶ」という点で「対象アプリ自身の技術を使う」という記述のカテゴリに
合致する)という既存の標準アクセサで妥当にマッピングできると判断した。
1対1の機構確認までは主張せず`# WARNING`を付す。

`DelayAfter`(活動終了後の待機時間、公式ドキュメントで既定300msと確認
済み)は`Click`/`TypeInto`/`GetText`には無かった新規属性——確認済みの
`DelayBefore`と同じ考え方で、活動本体(`.select()`呼び出し)の後に
`time.sleep()`として生成する。

`dump_daemon/uipath_dsl/types.py`に`SelectItemNode`、`xaml_tree.py`に
`_parse_select_item`(`(UI_NS, "SelectItem")`へディスパッチ登録)、
`uipath_codegen/__init__.py`に`_generate_select_item`を追加。
`tests/test_uipath_dsl.py`に1件・`tests/test_uipath_codegen.py`に10件
追加、全1214件通過。

## 113. `ui:UiElementExists`(DisplayName「Element Exists」)を実機XAML(GitHub実例)+公式ドキュメントで確認し、実コード生成に対応——Tier A着手第4件、タグ名の誤認を実機複数件で訂正(VM不使用、知見100の手法を10回目として再適用)

[design/uipath_feature_catalog.md](uipath_feature_catalog.md)のTier A
5件目(`Click`→`TypeInto`→`GetText`→`SelectItem`→`Element Exists`)。

**タグ名の訂正**: 最初に見つかった2件の実例(`gh api search/code`の
`"<ui:ElementExists "`検索)は`ui:ElementExists`というタグ名だったが、
1件は`TODO_SELECTOR_...`という明らかなプレースホルダ文字列を含む
非Studio生成の合成テストフィクスチャ(サードパーティのXAML変換ツール
`rasl-generator`のテストデータ)、もう1件は`.Target`ラッパーを持たない
旧式の直列化(信頼度の低い学生課題リポジトリ)だった。再検索
(`"ElementExists.Target"`)で見つかった3件の独立した実機リポジトリ
(`SuneetPatil/IRCTC-tatkal-booking`・`PacktPublishing/...-Projects`・
`allenlooplee/RPABook`)はいずれも真のタグ名が**`ui:UiElementExists`**
だと一致して示しており、公式ドキュメント(`ui-element-exists`ページ)の
裏のCLR型名`UiPath.Core.Activities.UiElementExists`とも一致した。
最初の2件は実機Studio保存の確証が弱いため不採用とした。

**属性構成**: 3件の実機XAMLいずれにも`ContinueOnError`/`DelayBefore`/
`DelayMS`に相当する属性が一切現れず(`{x:Null}`すら無く完全に省略)、
公式ドキュメントのプロパティ一覧にもこれらは載っていない——`Click`/
`TypeInto`/`GetText`/`SelectItem`が共有する「Common」カテゴリの属性とは
違い、この活動には本当に存在しないと判断し、捕捉対象に含めなかった
(無い属性を推測で持たせるとでっち上げになる)。出力は`Exists`属性
(Boolean変数のみ受け付けると公式ドキュメントで確認済み)。

**実装**: 公式ドキュメントが「要素が存在するか(可視でなくても)を確認
する」と説明しており、見つからなかった場合に例外を投げるかどうかは
明記されていなかったが、`pywinauto`の`WindowSpecification.exists()`
(未解決の検索条件に対して呼べる、見つからなければ例外を投げずに
`False`を返す標準アクセサ)の挙動と概念的に一致する——`Click`/
`SelectItem`で必要だった「機構未確認」の`# WARNING`すら不要なほど
確信度の高いマッピングだった。

`dump_daemon/uipath_dsl/types.py`に`UiElementExistsNode`、
`xaml_tree.py`に`_parse_ui_element_exists`(`(UI_NS,
"UiElementExists")`へディスパッチ登録)、`uipath_codegen/__init__.py`に
`_generate_ui_element_exists`を追加。`tests/test_uipath_dsl.py`に1件・
`tests/test_uipath_codegen.py`に5件追加、全1224件通過。

## 114. `ui:DatabaseConnect`/`ui:DatabaseDisconnect`/`ui:ExecuteQuery`/`ui:ExecuteNonQuery`を実機XAML+公式ドキュメントで確認し、SQLiteプロバイダのみ実コード生成に対応——Tier A項目2「Database活動」への着手第1件(VM不使用)

[design/uipath_feature_catalog.md](uipath_feature_catalog.md)のTier A
項目2(Database活動、「実務頻度が高いが完全に欠けている」と評価された
領域)の最初の着手——項目1(UI Automation Classic基本活動の残り、
Click/TypeInto/GetText/SelectItem/Element Exists)が一通り片付いたため、
次の項目へ進んだ。これまでのUI Automation系の知見100手法(Click以降)とは
別の新しい調査源を発見した。

**新しい高価値な調査源の発見**: `marcelocruzrpa/uipath-ai-skills`
リポジトリの`uipath-core/references/studio-ground-truth/`配下に、
「Harvested」(実機Studioから自動収集)と明記された、複数のUiPath活動
パッケージ(Database/Excel/Mail/PDF/Persistence/System/Testing/
UIAutomation/WebAPI)のXAMLリファレンス集が存在すると発見した——AI
コーディングエージェント向けに整備されたと見られる参照データで、
各活動を未設定のまま(全属性`{x:Null}`)配置した「空テンプレート」が
網羅的に揃っている。これは属性の**完全な語彙**(見落としが無いことの
確認)には最適だが、populated時の実際のシリアライズ例(リテラル値の
書式等)は別途、実際のプロジェクトリポジトリで確認する必要がある
——両者を組み合わせて使う(語彙は空テンプレート、実例は実プロジェクト)
という新しい調査パターンを確立した。他のパッケージ(Excel/Mail/PDF/
WebAPI等)の今後の拡張作業でもこのリポジトリを優先的に調査すべき。

**確定した構造**: `ui:DatabaseConnect`(`DatabaseConnection`出力・
`ConnectionString`/`ProviderName`/`SecureConnectionString`)・
`ui:DatabaseDisconnect`(`DatabaseConnection`入力)・`ui:ExecuteQuery`
(`Sql`/`ExistingDbConnection`/`DataTable`出力/`CommandType`/
`Parameters`)・`ui:ExecuteNonQuery`(同様だが`AffectedRecords`出力)。
`allenlooplee/RPABook`の実機プロジェクトで populated時の実例
(`ProviderName="System.Data.SQLite"`・`ConnectionString="Data
Source=db.sqlite;Version=3;"`・`CommandType="Text"`)を確認した。
`ExecuteQuery`/`ExecuteNonQuery`は`ExistingDbConnection`必須(自前の
接続文字列は持たない——公式ドキュメントで「既存接続が渡された場合は
ConnectionString/SecureConnectionStringは無視される」と確認済み)。

**ライブラリ選定とスコープ**: .NET ADO.NETの`ProviderName`(プロバイダ
invariant name)はPythonの単一ライブラリに1対1対応しない——プロバイダ
ごとに別のPythonドライバが必要になる構造的な問題。実機確認できたのは
`"System.Data.SQLite"`のみのため、**今回はSQLiteのみ対応**し標準
ライブラリ`sqlite3`へマッピングした(新規依存追加は不要)。他のプロバイダ
(SQL Server/PostgreSQL/MySQL/Oracle等)は`# TODO`へ倒す——でっち上げた
ドライバ呼び出しで誤動作させるより安全側。`ConnectionString`は
`Data Source=...;Version=3;`という ADO.NET形式(セミコロン区切り
key=value)をコード生成時に静的パースし、`Data Source`キーの値を
`sqlite3.connect()`へ直接埋め込む——リテラルでない(動的な)接続文字列は
静的解析できないため`# TODO`へ倒す。

`ExecuteQuery`の`DataTable`出力は`list[dict]`(各行を列名→値の辞書)へ
マッピング——`sqlite3.Row`を`row_factory`に設定し`dict(row)`で変換する、
追加依存なしで実現できる最もPythonicな表現と判断した。`ExecuteNonQuery`
後は明示的に`.commit()`を呼ぶ(SQLiteの自動コミットに依存しない)。
`Parameters`辞書(`ui:HttpClient.Headers`と同じ`x:Key`形、知見104の
`_xkey_dict_entries`を汎用化して再利用)は実機確認できた実例が空のみの
ため、populated時はプレースホルダ書式(`:name`/`@name`/`?`のどれを
UiPath側のSQLが使うか)が未確認として`# TODO`へ倒す。

**スコープ外として明示的に見送ったもの**(Database活動パッケージの
残り、同じ`UiPath.Database.Activities`に`BulkInsert`/`BulkUpdate`/
`DatabaseTransaction`/`InsertDataTable`が存在するとground-truthリポジトリ
で確認済みだが今回は未着手): `DatabaseTransaction`(`UseTransaction`
付きのスコープ活動、トランザクション境界の実装は別途必要)・
`BulkInsert`/`BulkUpdate`/`InsertDataTable`(DataTable引き渡しの往復が
絡み実装コストが高い)。

生成コードを実際に`sqlite3`の実DBに対して実行し(本セッションの
一時ファイル、リポジトリには残していない)、`SELECT`結果の`list[dict]`
化・`DELETE`の`AffectedRecords`取得の両方が正しく動くことを確認済み。

`dump_daemon/uipath_dsl/types.py`に`DatabaseConnectNode`/
`DatabaseDisconnectNode`/`ExecuteQueryNode`/`ExecuteNonQueryNode`、
`xaml_tree.py`に対応する4つのパーサー関数(`_xkey_dict_entries`に
汎用化した上で再利用)、`uipath_codegen/__init__.py`に4つの生成関数を
追加。`tests/test_uipath_dsl.py`に2件・`tests/test_uipath_codegen.py`に
22件追加、全1256件通過。

## 115. `ui:ExcelReadRange`/`ui:ExcelWriteRange`を実機XAML(ground-truthリポジトリ+実プロジェクト)で確認し、確認済みの既定値のみ実コード生成に対応——Tier A項目3「Excel Classicの残り」への着手第1件(VM不使用)

[design/uipath_feature_catalog.md](uipath_feature_catalog.md)のTier A
項目3(Excel Classicの残り)の最初の着手。知見114で発見した
`marcelocruzrpa/uipath-ai-skills`の`studio-ground-truth/UiPath.Excel.
Activities/3.4/`で属性の完全な語彙を確認し、`HarshadRanganathan/
uipath-learning`・`allenlooplee/RPABook`の実プロジェクトでpopulated時の
直列化を確認した。

**確定した構造**: `ui:ExcelReadRange`/`ui:ExcelWriteRange`はいずれも
既存の`ExcelApplicationScopeNode`(知見22・97)配下の子活動——
`ExcelWriteCellNode`と同じ「スコープと連動する」構造。`Range`
(`ExcelReadRange`のみ)は属性直書きではなく`<ui:ExcelReadRange.Range>`
配下の`InArgument`要素(さらにネストした`<Literal Value="">`要素形、
`Click`の`CursorPosition.OffsetX`(知見105)と同種のプロパティ要素形)。
実機確認できた値は空文字列のみ(「シート全体の使用範囲」を意味する)。
`StartingCell`(`ExcelWriteRange`のみ)は単純な属性直書き(`"A1"`)。
`AddHeaders`はhervested空テンプレートの既定が`ExcelReadRange`は
`"True"`、`ExcelWriteRange`は`"False"`という非対称な既定値だと確認した。

**実装**: `DataTable`を`ExecuteQuery`(知見114)と同じ`list[dict]`
表現に揃えた(異なる活動パッケージ間でも同じ「表形式データ」の
Python表現を統一する判断)。`openpyxl`の`Worksheet.iter_rows
(values_only=True)`で読み取り、`AddHeaders`時は最初の行を辞書キーとして
`dict(zip(...))`する。書き込みは`Worksheet.append()`——これは常に既存
内容の末尾に追記する挙動のため、`StartingCell`が確認済みの`"A1"`
以外(既存シートの中間への書き込み)の場合は正確な再現手段が未確認とし
`# TODO`へ倒した。`Range`が空文字列以外(特定範囲の指定)も同じ理由で
`# TODO`。

実際に`openpyxl`で作成した一時`.xlsx`ファイル(本セッションのみ、
リポジトリには残していない)に対して生成コードを実行し、Sheet1から
ヘッダー付きで読み取った`list[dict]`をSheet2へ書き込んだ結果が元の
データと完全に一致することを確認済み(round-trip検証)。

`dump_daemon/uipath_dsl/types.py`に`ExcelReadRangeNode`/
`ExcelWriteRangeNode`、`xaml_tree.py`に`_in_argument_property_expr`
(ネストした`InArgument`プロパティの共通パーサー、`Click`の
`_cursor_offset`から発想を汎用化)+対応する2つのパーサー関数、
`uipath_codegen/__init__.py`に`_generate_excel_application_scope`の
子ディスパッチ拡張+2つの生成関数を追加。`tests/test_uipath_dsl.py`に
1件・`tests/test_uipath_codegen.py`に9件追加、全1266件通過。

## 116. `ui:SendMail`(汎用SMTP送信、DisplayName「Send SMTP Mail Message」/「Send SMTP Email」)を実機XAML(ground-truthリポジトリ+実プロジェクト)で確認し、確認済みの唯一の接続構成(暗黙SSL)のみ実コード生成に対応——Tier A項目3「汎用Mail」への着手第1件(VM不使用)

[design/uipath_feature_catalog.md](uipath_feature_catalog.md)のTier A
項目3(「汎用Mail(SMTP/POP3/IMAP)」)の最初の着手。知見114の
`studio-ground-truth/UiPath.Mail.Activities/2.8/`で属性の完全な語彙を
確認したところ、現行(2.8)パッケージバージョンは`UseISConnection`
(Integration Service連携)・`UseOAuth`・添付用の`BackupSlot`パターン等、
`SendOutlookMail`(知見24・98・102)より遥かに複雑な構造だと判明した。

**実機のpopulated実例は意外に単純だった**: `cameronmcnz/uipath-tutorials`
の`SendGmailEmail/Main.xaml`(DisplayName「Send SMTP Mail Message」、
実際にGmail宛へ送信したと記載されたチュートリアル)で確認した実属性は、
`Server`/`Port`/`Email`/`Password`/`EnableSSL`/`SecureConnection`という
昔からの単純なSMTP直結属性のみ——`UseISConnection`等の新機能に触れない
限り、2.8パッケージでも昔からの単純な経路がそのまま使えると判明した。
確認できた具体的な組み合わせは`EnableSSL="True"`・
`SecureConnection="Auto"`・`Port="465"`(Gmailの暗黙SSL、SMTPS)。

**公式ドキュメントの限界**: `docs.uipath.com/activities/other/latest/
productivity/send-mail`で確認したが、`SecureConnection`の列挙値
(`Auto`以外に何があるか)・`EnableSSL`プロパティ自体(ドキュメントには
記載が無い、Windows-Legacy版のXAML属性名だが古いドキュメントの版には
載っていない可能性)を明記していない——このため「暗黙SSL(`EnableSSL=
True`+実機確認済みの`Port`)」という確認済みの唯一の組み合わせのみ実
コード生成し、平文接続・STARTTLS(`SecureConnection`の他の値)・
`UseOAuth`・`UseISConnection`・`Files`添付・`MailMessage`
(Forward/Reply)・`From`/`Name`での送信者表示名カスタマイズは
いずれも`# TODO`へ倒した——`HttpClient`(知見96)以来の「確認済みの
構成のみ対応」方針を踏襲。

**実装**: Pythonの標準ライブラリ`smtplib.SMTP_SSL`+`email.mime.text.
MIMEText`へマッピング(新規依存無し、クロスプラットフォーム——
`SendOutlookMail`の`win32com`がWindows専用だったのとは対照的)。
`_msg.as_string()`相当の構築(`email.mime.text.MIMEText`インスタンスへ
`Subject`/`From`/`To`/`Cc`/`Bcc`/`Reply-To`ヘッダーを設定)を実際に
Python標準ライブラリで構築し、RFC 2822準拠のメッセージ文字列が正しく
生成されることを確認済み(実際のSMTP送信は本セッションでは未検証
——認証情報・ネットワークアクセスが必要なため)。`DisplayName`と
裏のCLR型名`ui:SendMail`の食い違いは知見29(`HttpClient`)・知見111
(`UiElementExists`)と同種のパターン。

`dump_daemon/uipath_dsl/types.py`に`SendMailNode`、`xaml_tree.py`に
`_parse_send_mail`(`(UI_NS, "SendMail")`へディスパッチ登録、`Files`の
populated判定は`_parse_send_outlook_mail`と同じロジックを再利用)、
`uipath_codegen/__init__.py`に`_generate_send_mail`を追加。
`tests/test_uipath_dsl.py`に1件・`tests/test_uipath_codegen.py`に16件
追加、全1283件通過。`GetIMAPMailMessages`/`GetPOP3MailMessages`
(受信系、`Messages`出力の構造等が別途調査必要)は今回スコープ外として
見送り。

## 117. 「実機XAMLに対する実際のコード生成の検証」という新しい調査手法を導入——真の非空シートに対する`ExcelWriteRange`の実在バグを発見・修正し、GitHub上の外部実プロジェクトから新たな実装候補(`CopyFile`/`BuildDataTable`/`ExcelAppendRange`)を特定(VM不使用)

ユーザーからの「もっとできることないのかなぁ」という問いかけを受け、
これまでの「個別活動を1つずつ機械的に実装する」Tier A一巡とは別の
検証軸として、**pad2py自身の`generate_python()`/`generate_project_from_json()`
を実際にGitHub上の外部の実プロジェクト(自分のテストフィクスチャではない)
に対して実行する**という新しい調査手法を導入した——これまでの「実機
XAMLの属性構造を確認する」調査(知見100の手法)とは別軸で、「生成コード
自体が正しく動くか」を実データで検証する。

**手法**: `gh api search/code`で`"main": "Main.xaml"` + `"projectType":
"Process"` + `filename:project.json`を検索して小規模な実Processプロジェクト
(`rpapub/PropulsiveForce`)を発見、`generate_project_from_json()`を実行し
正しく`# TODO`に倒れることを確認(クラッシュ無し)。さらに
`allenlooplee/RPABook`の既存調査済みリポジトリから、Flowchartベースの
デモ(`Demo1`)とExcel/BrowserScope/DataTable操作が密に混在する実ワーク
フロー(`Demo7/Main.xaml`、1074行)を選び、`generate_python()`を直接実行。
Demo1は完全にエラー無く変換できた(ディスパッチループ構文がFlowchartの
`Condition="True"`という非角括弧のリテラル条件まで正しく処理できることを
確認——合成テストでは作っていなかった実例)。Demo7は1074行中わずか6件の
`# TODO`のみで、すべて具体的で既知の活動(`CopyFile`/`AddDataRow`×2/
`BrowserScope`/`BuildDataTable`/`ExcelAppendRange`)だと判明した——
自分で推測した優先順位(Tier A/B/C/D)とは独立に、実際の外部ワークフローが
何を必要としているかを直接確認できる、より強い根拠を得られた。

**実在バグの発見・修正(`ExcelWriteRange`、知見115の追記)**: この調査の
過程で、既存の`ExcelWriteRange`実装(`openpyxl`の`Worksheet.append()`
ベース)を「既にデータがあるシート」に対して再検証したところ(ランダムな
外部データではなく自分で意図的に組んだ再現テスト)、`append()`が常に
シート末尾に追記する挙動のため、`StartingCell`の実際の位置を無視して
末尾に追記してしまうという実在のバグを発見した——知見115の時点のテストは
常に空シートに書き込んでいたため発覚していなかった。`Worksheet.cell
(row=..., column=..., value=...)`による直接セル指定の書き込みに変更して
修正——これにより「既存データの途中への上書き」が正しく動くようになり、
副産物として`StartingCell`を`"A1"`に限定する制約も解消された(任意の
開始セルに対応可能に)。実際に非空シートへ生成コードを実行し、修正前後の
挙動差を確認済み。

**`CopyFile`**(`UiPath.System.Activities`): `Path`/`Destination`
(リテラル・VbExprの両方の実例)・`Overwrite`(`"True"`/`"False"`の両方の
実例)を確認。`Destination`がフォルダパスかファイルパスかの判定は
`shutil.copy()`自体が内部で処理する(UiPath公式ドキュメントが「フォルダ
パスなら元の名前、ファイルパスなら指定名」と説明する挙動と一致)。
`Overwrite="False"`時の挙動は公式ドキュメントに明記が無いが、裏の.NET
API`File.Copy(src, dest, overwrite)`の確立済みの契約(`overwrite=false`
時は既存ファイルがあると例外)に基づき`FileExistsError`を投げるガードを
実装——実際に一時ファイルへ2回コピーを実行し、1回目は成功・2回目は正しく
例外が発生することを確認済み。`DestinationResource`/`PathResource`
(ground-truthのみで発見、Integration Service連携用と推定)は未確認のため
見送り。

**`BuildDataTable`**(`UiPath.System.Activities`): `TableInfo`属性に
.NET `DataSet`のXMLスキーマ(`xs:schema`)が丸ごと埋め込まれるという、
これまでに無かった直列化形を確認(`marcelocruzrpa/uipath-ai-skills`の
ground-truth)。本パーサーは`xs:complexType/xs:sequence/xs:element`という
階層で列名を抜き出すが、Pythonの`list[dict]`表現(知見114・115で確立)
では列は各行の辞書キーとして実行時に決まるため、空テーブルの生成自体に
列名は不要と判断し(`SelectItem.Items`、知見112と同じ判断)、`dt = []`
を生成するだけで足りた。

**`ExcelAppendRange`**: `AddHeaders`/`StartingCell`が無く常にシート末尾
への追記のみという構造を確認——これは`ExcelWriteRange`の上記修正で
`append()`ベースの実装から外した挙動そのものに正確に対応する、別の活動
だと判明した(偶然ではなく、実際にUiPathが2つの別活動として区別して
いる設計だと再確認)。

**captured-but-unused data の追加発見**: `ExcelReadRangeNode`/
`ExcelWriteRangeNode`の`display_name`フィールドは知見115で捕捉していた
にもかかわらず、スコープ配下の子活動用のコード生成経路(`_generate_
excel_*_range_in_scope`)には display_name コメントを追記するロジックが
無く、知見75・92〜95と同種の「捕捉済みデータの未活用」が残っていたと
今回判明——`_with_scope_child_display_name`という共通ヘルパーを新設して
修正した。

**スコープ外として明示的に見送ったもの**: `AddDataRow`(`ArrayRow`の
位置指定の値を`list[dict]`表現の辞書へ変換するには対象`DataTable`の
列名が必要だが、`BuildDataTable`の`TableInfo`から抜き出した列名を
ノード間で追跡する仕組み(セレクタ解決やInvoke Workflow Fileの解決と
同種の、cross-node resolverの新設)が現在のcodegenアーキテクチャに
無く、今回は新設しなかった——`list`(位置指定)で妥協すると、既に実装
済みの`ExcelWriteRange`(`AddHeaders=True`時に`.keys()`を呼ぶ)等の
dict前提の消費者を静かに壊す実害があるため、正直に`# TODO`へ倒す方が
安全と判断。将来「DataTableスキーマ解決パス」を新設する際の具体的な
動機として記録しておく)。`BrowserScope`(Web UI Automationの別サブ
システム、別途調査が必要)。

`dump_daemon/uipath_dsl/types.py`に`CopyFileNode`/`BuildDataTableNode`/
`ExcelAppendRangeNode`、`xaml_tree.py`に対応するパーサー関数(`TableInfo`
XMLスキーマパーサー含む)、`uipath_codegen/__init__.py`に対応する生成
関数+`ExcelWriteRange`の修正+`_with_scope_child_display_name`ヘルパーを
追加。`tests/test_uipath_dsl.py`に5件・`tests/test_uipath_codegen.py`に
20件追加(既存2件の修正含む)、全1310件通過。外部実プロジェクトでの
再検証(`Demo7/Main.xaml`)で`# TODO`数が6→3件に減少したことを確認。

## 118. `uipath_expr`文法の「関数呼び出し結果へのメンバ/メソッドアクセス連鎖」ギャップと、無関係な既存バグ(引数0個の関数呼び出し)を発見・修正、`ui:ForEachRow`を既存`ForEachNode`の再利用で新規実装(知見117の手法を継続、VM不使用)

知見117で導入した「実機XAMLに対する実際のコード生成の検証」を、さらに
3件の多様な実プロジェクト(`SuneetPatil/IRCTC-tatkal-booking`・
`vajrang-b/UiPathIn30Days`・`HarshadRanganathan/uipath-learning`)に対して
継続実行した。

**`uipath_expr`文法のギャップ(重要度の高い発見)**: `SuneetPatil/
IRCTC-tatkal-booking`の実機XAML(`If Condition="[in_Config(&quot;
insurance&quot;).ToString.ToLower.Equals(&quot;yes&quot;)]"`)を変換した
ところ、`If.Condition`の構文解析失敗が未捕捉のまま伝播し(モジュール
docstringが明記する意図した「条件式の失敗は伝播させる」設計通りの挙動
ではあるが)、ファイル全体の変換が丸ごと失敗した。原因を追跡したところ、
**関数呼び出し結果へのメンバ/メソッドアクセスの連鎖
(`FuncCall(...).Member1.Member2...`)が文法に一切対応していない**という、
この1ファイルに限らない広範な既存ギャップだと判明した——確認済みの
Tier1関数(`CStr`等)の結果への`.ToUpper()`/`.ToString().Trim()`連鎖すら
構文解析段階で失敗していた(`DateTime.Now.ToString("yyyy").Trim()`のような
一般的なVB.NETの慣用句も同様)。`postfix`規則(`atom`と`power_expr`の間に
新設)を追加し、`ChainedAccess`という新しいIRノード型(`target`は任意の式、
`members`はドット区切りの各セグメント、`args`は末尾呼び出しの引数
——`None`なら末尾も単純なプロパティアクセス)で表現するよう修正した。

レンダラー側(`uipath_codegen/render.py`)は確認済みの安全な.NETメンバの
みを実コード変換する——`.ToString`は既存の`CStr`と同じ`_vb_cstr()`
ヘルパーへ(design/uipath_vb_expression_mapping.mdで`CStr`/`.ToString`を
実質同等と整理済み)、`.ToUpper`/`.ToLower`/`.Trim`はPython文字列メソッド
への直接の名前変換(いずれも.NET `String`型の標準メソッドでPython`str`の
対応メソッドと同じ意味論)、`.Equals(arg)`(1引数)は`==`比較へ(文字列
同士の`Equals`はPythonの`==`と同じ値比較になる)。未知のメンバ・メソッド
は`# TODO`/条件式の失敗伝播のいずれかへ安全に倒す(他の`_render_*`関数と
同じ「でっち上げ回避」方針)。

**無関係な既存バグの偶発的発見**: この修正の実装中、`arglist: [expr
("," expr)*]`という既存の文法規則(引数0個の関数呼び出しを表現する
`[...]`のLark既定動作、`maybe_placeholders`)が、引数0個の場合に空リスト
ではなく**単一の`None`プレースホルダ子を生成する**という、全く別件の
既存バグを発見した——`Foo()`のような引数無し関数呼び出しが
`FuncCall(args=(None,))`という壊れた木になっていた(VB式の引数が実際に
Pythonの`None`になることは無いため、安全に判別・修正できた)。実機データ
で引数0個の関数呼び出しが使われる実例が今回の調査まで無かったため、
長らく未検出だったと推定される(知見41の`And`/`Or`/`Xor`優先順位バグと
同種の「混在パターンの実機データが無かったため長らく未検出」というパターン)。

**`ui:ForEachRow`**(`UiPath.System.Activities`、`HarshadRanganathan/
uipath-learning`で発見): `ui:ForEach`(知見5)と直接の子要素構造が完全に
同じ(`.Body`→`ActivityAction`+`DelegateInArgument`→`Sequence`)で、
唯一の違いは反復対象を指す属性名(`Values`ではなく`DataTable`)——意味論も
完全に同じ(`DataTable`は`list[dict]`表現、知見114・115で確立)。新しい
ノード型・生成関数を追加せず、既存の`ForEachNode`/`_generate_for_each`を
そのまま再利用する薄いパーサー(`_parse_for_each_row`)のみ追加した。
実際に`list[dict]`に対して生成コードを実行し、各行(`dict`)が正しく
`row`へ束縛されることを確認済み。

**新たに発見したが今回は見送ったもの**: `AppendWriteCsvFile`(CSV書き込み、
Python標準の`csv`モジュールで実装可能と見込まれる)・SQL Server以降の
ProviderName(`Microsoft.Data.SqlClient`、SQLite以外のプロバイダの実在
確認——知見114でSQLite限定とした判断の妥当性を裏付ける実例)・`row(
"ColumnName")`(DataRowインデクサ、`row`が`list[dict]`の`dict`要素だと
分かっていれば`row["ColumnName"]`に対応するはずだが、知見74の配列添字
曖昧性と同じ理由でスコープ認識が無い限り安全に判別できない)・
`dt.Rows.IndexOf(row)`(未確認の関数チェーン)は、いずれも別の機会に
記録しておく。

`dump_daemon/uipath_expr/__init__.py`に`ChainedAccess`+文法規則+
`arglist`の修正、`uipath_codegen/render.py`に`_render_chained_access`、
`uipath_dsl/xaml_tree.py`に`_parse_for_each_row`(`(UI_NS,
"ForEachRow")`へディスパッチ登録、既存`ForEachNode`を返す)を追加。
`tests/test_uipath_expr.py`に4件・`tests/test_uipath_codegen.py`に7件・
`tests/test_uipath_dsl.py`に1件追加、全1323件通過。

## 119. 「実機XAMLに対する実際のコード生成の検証」で6件の実プロジェクトを一括検証——`ui:Comment`/`ui:LogMessage`/`ui:ExcelReadCell`を新規実装、`ExcelWriteCellNode.cell`を`str`から`Expr`へ昇格、素の変数へのメンバアクセス連鎖の未発見バグも修正(知見117・118の手法を継続、VM不使用)

知見117・118の「実機XAMLに対する実際のコード生成の検証」をさらに6件の
多様な実プロジェクト(`PacktPublishing/Robotic-Process-Automation-
Projects`の3ファイル・`allenlooplee/RPABook`・`HarshadRanganathan/
uipath-learning`・`vajrang-b/UiPathIn30Days`)へ一括適用した。1件
(`Excel_Sum_Formula.xaml`)は**`# TODO`が0件で完全にクリーンに変換できた
**——良い検証結果。

**別件のレンダラーバグ(知見118の追加調査で発見)**: `"A"+intCounter.
ToString`(動的セル指定の実例、下記)を検証する過程で、知見118で修正した
`ChainedAccess`(関数呼び出し結果へのチェーン)だけではカバーできない
別のケースを発見した——`intCounter.ToString`のように**関数呼び出しを
介さない素の変数**へのメンバアクセス連鎖は、`IDENT`トークンの正規表現
(ドット区切りを1トークンとして貪欲マッチする、`postfix`文法規則とは
無関係にレクサ段階で1トークンに吸収されてしまう)の都合で、修正前は
不正な`intCounter.ToString`というPython属性アクセスがそのまま出力
されていた(構文的には有効だが、Pythonの`int`に`.ToString`属性は無く
実行時`AttributeError`になる、サイレントな誤変換)。レンダラーの`Ident`
処理に、末尾セグメントが確認済みの安全なメンバ名(`ToString`/
`ToUpper`/`ToLower`/`Trim`)の場合のみ分割して知見118の変換を適用する、
安全な追加修正を行った——`DateTime.Now`のような静的クラス参照(末尾が
対象メンバ名に一致しない)は無変換のまま変わらない。

**`ExcelWriteCellNode.cell`を`str`から`Expr`へ昇格**: `PacktPublishing/
Robotic-Process-Automation-Projects`の実機XAMLで`Cell="[&quot;B&quot;+
intCounter.ToString]"`(ループ内での連番セル指定、現場では非常に一般的な
実務パターン)という動的な実例を発見——知見22以来`str`型固定だったため
このパターンは常に`# TODO`に倒れていた。`sheet_name`は全Excel活動で
常にリテラルだったため`str`のまま残した(非対称昇格、兄弟活動との
一貫性を優先)。実際に一時`.xlsx`ファイル(既存セルにプリセット値、
`intCounter=5`)へ生成コードを実行し、`A5`から読んで`B5`へ正しく書き
込まれることを確認済み(round-trip検証)。

**`ui:ExcelReadCell`**(`ExcelWriteCellNode`と対になる読み取り側):
`Cell`は同じ`Expr`、`.Result`はネストした`OutArgument`要素形——
知見115で確立した`_in_argument_property_expr`共通パーサーが`InArgument`
以外のタグ名(`OutArgument`)でも同じロジックでそのまま動作することを
確認できた(タグ名を見ずに「最初の子要素のテキストまたはネストした
Literal」という構造だけを見ているため)。

**`ui:Comment`**: 純粋な注釈活動、`Text`属性(常にリテラル)をそのまま
Pythonの`#`コメント行へ変換する——実行時の挙動は一切無い。

**`ui:LogMessage`**: 実機確認済みの`Level`は`"Info"`/`"Error"`のみ——
Python標準ライブラリ`logging`の対応メソッド(`logging.info`/
`logging.error`)へマッピング。他の値(`"Warn"`等)は未確認のため
`# TODO`へ倒す。

**新たに発見したが今回は見送ったもの**: `BrowserScope`(既知の大きな
別サブシステム)・`AddQueueItem`(Orchestrator連携、Phase8で既に方針
決定済みのスコープ外)・`GoogleVisionScope`(サードパーティ/ニッチな
Marketplaceパッケージ)・`Out/InOutArgument`のByRef書き戻し制約(既知の
制約)・`ExcelReadCellNode`/`ExcelWriteCellNode`が`ExcelApplicationScope.
Body`の直接の子ではなく更にIf/ForEach越しにネストしている場合は
`scope_var`の文脈を失い`# TODO`に倒れる(知見84で既に文書化済みの構造的
制約、新しいバグではない)。`ExcelWriteCellNode`には`display_name`
フィールドが(他のExcel活動と違い)無い——実機では`DisplayName`属性が
存在するため将来追加する価値はあるが、今回はスコープを絞るため見送った。

`dump_daemon/uipath_dsl/types.py`に`CommentNode`/`LogMessageNode`/
`ExcelReadCellNode`を追加、`ExcelWriteCellNode.cell`を`Expr`へ変更。
`xaml_tree.py`に対応するパーサー関数(`_parse_comment`/
`_parse_log_message`/`_parse_excel_read_cell`、既存`_parse_excel_write_
cell`も更新)。`uipath_codegen/__init__.py`に`_generate_comment`/
`_generate_log_message`/`_generate_excel_read_cell_in_scope`を追加、
`_generate_excel_write_cell_in_scope`を`Expr`対応に更新、`render.py`の
`Ident`処理に素の変数チェーン対応を追加。`tests/test_uipath_dsl.py`に
4件・`tests/test_uipath_codegen.py`に13件追加(既存2件の修正含む)、
全1341件通過。

## 120. `ui:GetOutlookMailMessages`(`SendOutlookMailNode`と対になる受信側)を新規実装、2件が`# TODO`0件で完全にクリーンに変換できた(知見117〜119の手法を継続、VM不使用)

知見117〜119の「実機XAMLに対する実際のコード生成の検証」を、Word
Application Scope・Outlookメール受信系の実プロジェクト(`UiPath/skills`
の`uipath-troubleshoot`テストタスク・`cameronmcnz/uipath-tutorials`の
複数ファイル)へ継続適用した。5件中4件に`GetOutlookMailMessages`が
出現する強い実務需要の信号を確認——`SendOutlookMail`(知見24・98・102)
の受信側として自然な実装対象だった。

**確定した構造**: `Messages`(出力)・`Account`(別メールボックス指定、
未確認)・`Filter`・`MailFolder`(確認済みの既定`"Inbox"`)・
`GetAttachements`(UiPath自身の属性名の表記ゆれ、確認済みの既定
`"False"`)・`MarkAsRead`/`OnlyUnreadMessages`(確認済みの既定
`"False"`)・`Top`(件数上限、確認済みの実例`"30"`)・`TimeoutMS`。

**`Filter`の直列化形の発見**: 実機で`Filter="[importance]='normal'"`
という実例を確認したが、これはVB式の`[...]`角括弧記法ではなく、
**OutlookのDASL/Jetフィルタ構文そのもの**(`Items.Restrict()`に渡す
ネイティブのクエリ文字列、角括弧はOutlook側のプロパティ名を示す記法)
だと判明した——`]`で終わらない(末尾が`'normal'`のクォート)ため
`_parse_expr`の`[...]`判定が自然に不一致となり、意図せず正しく
`Literal`として捕捉されていた(VB式と誤認するコーナーケースを偶然
回避できていた、という発見自体も記録に値する)。コード生成側はこの
文字列をそのまま`Items.Restrict()`へ委譲する(UiPath自身が変換して
いないと見受けられるため、独自の変換はでっち上げない)。

**実装**: `GetNamespace("MAPI").GetDefaultFolder(6)`(`olFolderInbox`、
Microsoft Learn`OlDefaultFolders`列挙で確認済み、`SendOutlookMail`の
`CreateItem(0)`と同じ確認手法)経由で受信箱の`Items`コレクションを取得、
`Filter`があれば`.Restrict()`、`Top`があれば`list(...)[:N]`でスライス。
実際に2件の実プロジェクト(`ConnectToOutlook`・`FilterOutlookEmail`)を
変換したところ、いずれも`# TODO`0件で完全にクリーンな実行可能コードに
なった——`FilterOutlookEmail`では元のXAML自体に`Messages`の束縛先
(`MessageBox`)と`ForEach`の反復先(`EmailMessages`)が食い違うという
実在のバグ(チュートリアル作成者のコピペミスと推定)があったが、これは
変換元の忠実な再現であり本トランスパイラの問題ではない——正直に同じ
挙動を再現した。

**新たに発見したが今回は見送ったもの**: `WordApplicationScope`+
`ReplaceTextInDocument`(`UiPath.Word.Activities`、`UiPath/skills`の
`uipath-troubleshoot`テストタスクで発見。`ExcelApplicationScope`と同じ
`ActivityAction`+`DelegateInArgument`構造——`python-docx`は既にプロジェクト
依存に含まれているため実装コストは低いと見込まれるが、今回はスコープを
絞るため次回へ見送った)。

`dump_daemon/uipath_dsl/types.py`に`GetOutlookMailMessagesNode`、
`xaml_tree.py`に`_parse_get_outlook_mail_messages`(`(UI_NS,
"GetOutlookMailMessages")`へディスパッチ登録)、`uipath_codegen/
__init__.py`に`_generate_get_outlook_mail_messages`を追加。
`tests/test_uipath_dsl.py`に1件・`tests/test_uipath_codegen.py`に10件
追加、全1354件通過。

## 121. `ui:WordApplicationScope`+`ui:ReplaceTextInDocument`/`ui:WordReplaceText`を新規実装(知見117〜120の手法を継続、VM不使用)

知見117〜120で前回見送った`WordApplicationScope`系(`UiPath.Word.
Activities`)に着手した。`UiPath/skills`公式リポジトリの
`uipath-troubleshoot`テストタスク(Word関連の障害切り分けシナリオ集、
`word-scope-*`/`word-replace-text-*`という命名から、UiPathが実際の
サポートシナリオ再現用に用意した実機Studio保存済みXAMLと判断できる)で
複数の実例を確認した。

**2つの異なるタグ名を発見**: `ui:ReplaceTextInDocument`(DisplayName
「Replace Text in Document」)と`ui:WordReplaceText`(DisplayName
「Replace Text」)——意味論は完全に同じ(`Search`を`Replace`へ置換)で、
おそらくパッケージバージョン間のリネーム(`SendMail`の`ui:SendMail`/
DisplayName不一致と同種のパターン)。両方のタグ名を同じ
`WordReplaceTextNode`へディスパッチするよう実装した。

**`Search`の直列化形の発見**: 2つの実例で異なる形を確認した——
`Search="{{Candidate}}"`(Wordドキュメント内に実在する生のプレースホルダ
文字列、VB式ではない、`{`で始まるが`_parse_expr`のVB式判定`[...]`とは
無関係なためそのまま`Literal`として正しく捕捉される)と`Search=
"[TermsPlaceholder]"`(真のVB変数参照)の両方が実在する——用途に応じて
Wordドキュメント内の固定プレースホルダを検索する場合と、動的な検索語を
使う場合の両方に対応できる構造だと確認した。

**実装**: `ExcelApplicationScope`(知見22・97)と全く同じ設計を踏襲——
`python-docx`(既にプロジェクト依存に含まれている、ファイルベースで
Wordプロセス不要)への実コード生成。`docx.Document(file_name)`で開き、
`WordReplaceTextNode`(スコープの直接の子の場合のみ)は各段落の各run単体
に対して文字列置換する標準的なイディオムへ変換、スコープ末尾で
`.save(file_name)`する。実際に一時`.docx`ファイル(`{{Candidate}}`という
プレースホルダを含む段落)へ生成コードを実行し、VB変数の値へ正しく
置換されることを確認済み(round-trip検証)。`Visible`属性(実機確認済み
の値は常に`"False"`)は、`ExcelApplicationScope`の`openpyxl`採用時と
同じ理由(ファイルベース、ライブCOM自動化ではない)で無視する。

**既知の限界(意図的に受け入れる)**: `python-docx`には組み込みの検索
置換が無いため、検索対象の文字列が複数のrun(書式の境界、例えば検索語の
前半が太字・後半が通常文字といった混在)に分割されている場合は置換
されない——`ExcelApplicationScope`のライブマクロ実行未対応と同種の、
選んだライブラリに起因する構造的な制約として明示的に受け入れる。

`dump_daemon/uipath_dsl/types.py`に`WordApplicationScopeNode`/
`WordReplaceTextNode`、`xaml_tree.py`に対応するパーサー関数
(`(UI_NS, "WordApplicationScope")`・`(UI_NS, "ReplaceTextInDocument")`・
`(UI_NS, "WordReplaceText")`の3つをディスパッチ登録)、`uipath_codegen/
__init__.py`に`_generate_word_application_scope`/`_generate_word_
replace_text_in_scope`を追加(`_iter_invoke_nodes`のスコープ再帰発見
リストにも追加、知見88と同種の見落とし防止)。`tests/test_uipath_dsl.py`
に2件・`tests/test_uipath_codegen.py`に4件追加、全1369件通過。

## 122. `ui:MultipleAssign`を新規実装(5件中5件に出現する最強の実務需要信号)、`Condition`の省略されないプロパティ要素形(`mva:VisualBasicValue`)も発見・修正(知見117〜121の手法を新しい実プロジェクト群へ継続、VM不使用)

知見117〜121の「実機XAMLに対する実際のコード生成の検証」を、これまで
使っていなかった新しい実プロジェクト群(`cameronmcnz/uipath-tutorials`
の追加ファイル・`rpabotsworld/uipath-with-github-action`・
`ShonHarsh/RPADev-S02P01-ForEachIfStatement-VB`・`miyag/
UiPath.ReusableCode`)へ適用した。**5件中5件に`MultipleAssign`が出現する
**——これまでの検証で見た中で最も強い実務需要の信号だった。

**`ui:MultipleAssign`**(`UiPath.System.Activities`): `.AssignOperations`
配下の`scg:List<ui:AssignOperation>`の各要素は`.To`/`.Value`を持ち、
単一の`Assign`(知見2)と構造・意味論が完全に同じ——複数の`Assign`を
1つの活動にまとめた糖衣構文に過ぎないと判断し、新しい値表現をでっち
上げず各要素を既存の`AssignNode`として再利用、コード生成も既存の
`_generate_assign`を単純にループで呼ぶだけで済んだ。

**`Condition`の省略されないプロパティ要素形の発見**: `MultipleAssign`
修正後の再検証で、`ui:InterruptibleDoWhile`の`Condition`が`# TODO`に
倒れる実例を発見した——`Condition`属性そのものが存在せず、代わりに
`<ui:InterruptibleDoWhile.Condition><mva:VisualBasicValue
ExpressionText="guess &lt;&gt; secretNumber" />
</ui:InterruptibleDoWhile.Condition>`という、プロパティ要素形そのもの
(`mva:VisualBasicValue`、`Microsoft.VisualBasic.Activities`——.NET
Workflow Foundation自体の標準型で、UiPath独自ではない)が直列化されて
いた。知見14で「`[...]`角括弧式の正体は`VisualBasicValue`の省略記法」
と確認済みだったが、Studioが常に省略形(`Condition="[...]"`属性)を
使うとは限らず、省略されない完全形も実在すると今回確認できた——
`ExpressionText`属性が角括弧無しの生のVB式テキストを保持する。属性形が
無い場合のみこの要素形へフォールバックする`_condition_expr`を新設し、
`While`/`DoWhile`の両方に適用した(`If`/`Switch`等の他の条件式プロパティ
も理論上同じ機構のはずだが、実機確認はまだ`While`/`DoWhile`のみ——
確認が取れたものだけ修正する方針を継続)。

**新たに発見したが今回は見送ったもの**: `InputDialog`(ユーザー入力
ダイアログ、`MessageBox`の入力版——`MessageBox`が`print()`へ変換される
のと同じ「非対話的な変換」の限界に直面するため設計判断が必要)・
`New Integer() {...}`(VB.NETの明示的配列構築構文、既存の`{a,b,c}`配列
リテラルとは別の文法)・`Log Message`の`Level`属性がVB式で囲まれた列挙
参照(`"[UiPath.Core.Activities.LogLevel.Info]"`)になる実例(現在は
プレーンな文字列`"Info"`/`"Error"`のみ対応、列挙参照形は未対応)・
`Verify Expression with Operator`(`UiPath.Testing.Activities`、知見の
P3で既に低優先と判断済み)。

`dump_daemon/uipath_dsl/types.py`に`MultipleAssignNode`、`xaml_tree.py`
に`_parse_multiple_assign`+`_condition_expr`(`_parse_while`/
`_parse_do_while`を更新)、`uipath_codegen/__init__.py`に
`_generate_multiple_assign`を追加。`tests/test_uipath_dsl.py`に2件・
`tests/test_uipath_codegen.py`に2件追加、全1381件通過。

## 123. `_condition_expr`フォールバックを`If.Condition`/`Switch.Expression`へも適用(知見122で保留した範囲を拡張、VM不使用)

知見122で「`If`/`Switch`等の他の条件式プロパティも理論上同じ機構のはず
だが、実機確認はまだ`While`/`DoWhile`のみ」と明示的に保留した項目を
今回拡張した。`_condition_expr(elem, attr_name)`自体は属性名を
引数化した汎用ヘルパーとして既に実装済みであり(`While`/`DoWhile`固有の
ロジックは一切含まない)、`If._parse_if`の`condition=_attr_expr(elem,
"Condition")`と`_parse_switch`の`expression=_attr_expr(elem,
"Expression")`を、それぞれ同じ`_condition_expr(elem, "Condition")`/
`_condition_expr(elem, "Expression")`に差し替えるだけで済んだ——新しい
解析ロジックの追加はゼロ。

`If`/`Switch`固有の実機XAML(`<If.Condition><mva:VisualBasicValue
.../></If.Condition>`形)はまだ直接観測していないが、`[...]`角括弧
省略記法と`mva:VisualBasicValue`プロパティ要素形がどちらも.NET
Workflow Foundationの`InArgument`直列化規約(知見14)に基づく同一の
機構である以上、Studioがどちらの形で直列化するかは活動の種類に
依存しない——`Condition`/`Expression`という属性名の違いだけで、
それを包むプロパティ要素の構造自体は`While`/`DoWhile`と変わらない
ため、確認済みの機構を同じ属性名パターンを持つ別の活動へ水平展開する
ことは「確認済みの値のみを安全網として適用する」方針からも妥当と
判断した(新しい値表現をでっち上げているわけではなく、既に確認済みの
`VisualBasicValue`パース経路を再利用しているだけ)。

`dump_daemon/uipath_dsl/xaml_tree.py`の`_parse_if`/`_parse_switch`の
2箇所のみ変更。`tests/test_uipath_dsl.py`に`If`/`Switch`それぞれの
プロパティ要素形を合成XMLで再現する回帰テストを2件追加、全1385件通過。

## 124. `ui:LogMessage`の`Level`列挙参照形(`[UiPath.Core.Activities.LogLevel.Info]`)を解決(知見122で発見・保留した項目、VM不使用)

知見122で発見しつつ見送った3件のうちの1件、「`Log Message`の`Level`
属性がVB式で囲まれた列挙参照(`"[UiPath.Core.Activities.LogLevel.Info]"`)
になる実例」を解決した。`Level`は通常`"Info"`/`"Error"`という生の
文字列属性(知見119)だが、実機XAMLでは`[UiPath.Core.Activities.
LogLevel.Info]`という、`[...]`角括弧VB式で.NET列挙の完全修飾名を
参照する形でも直列化される——これは知見14の「`[...]`はVisualBasicValue
の省略記法」という理解と整合する(ただし対象が式ではなく列挙メンバーの
修飾名である点が、これまでの`[...]`の使われ方とは異なる新しいパターン)。

`xaml_tree.py`に`_parse_log_level`を新設: `Level`の生テキストが
`[...]`で囲まれ、かつ内部が確認済みのプレフィックス`"UiPath.Core.
Activities.LogLevel."`で始まる場合のみ末尾のメンバー名(`"Info"`)を
取り出す。それ以外の形(プレフィックス不一致、角括弧無し)は無理に
解釈せず生テキストをそのまま返し、既存の`_LOG_LEVEL_METHODS`
(`Info`/`Error`のみ確認済み、知見119)による絞り込みと`# TODO`への
フォールバックへそのまま委ねる——`LogMessageNode.level`フィールド自体
は変更せず常に素の文字列のまま保持し、コード生成側(`_generate_log_
message_body`)は一切変更していない。これにより`Level="Warn"`等、
取り出したメンバー名が未確認な場合も、角括弧形・生文字列形どちらでも
同じ診断品質の`# TODO`メッセージになる。

`tests/test_uipath_dsl.py`に2件追加(確認済みメンバー名`Info`が実コード
生成へ到達する経路・未確認メンバー名`Warn`が生テキストのまま保持されて
`# TODO`へ落ちる経路)、全1392件通過。残り2件
(`InputDialog`・`New Integer() {...}`)は引き続き見送り。

## 125. VB.NETの明示的配列構築構文`New Integer() {...}`を`uipath_expr`文法に追加(知見122で発見・保留した残り2件のうち1件、VM不使用)

知見122・124で見送った残り2件のうちの1件、「`New Integer() {...}`
(VB.NETの明示的配列構築構文、既存の`{a,b,c}`配列リテラルとは別の文法)」
を解決した。これは`uipath_dsl`/`xaml_tree.py`側の課題ではなく
`uipath_expr`(`[...]`角括弧式の中身を解析するLark文法)側の課題——
`[New Integer() {1, 2, 3}]`のような値が、既存の`{...}`(`array_lit`
規則、知見5)では構文解析できず`tree=None`へ倒れていた。

VB.NETでは`Dim x As Integer() = New Integer() {1, 2, 3}`のように、
配列を明示的な型付きコンストラクタ構文(`New <Type>() {...}`)で初期化
できる——要素リスト自体(`{1, 2, 3}`)の意味論は既存の波括弧リテラルと
全く同じで、唯一の違いは前置される型名宣言(`New Integer()`)の有無。
既存の`ArrayLiteral`データクラスは元々要素型を保持していない
(Pythonの動的型付けリストに対応する以上、型情報はそもそも不要)ため、
型名を解析して捨てるだけの薄いアダプタとして`new_array_lit`規則を
追加し、既存の`ArrayLiteral`へそのまま帰着させた——新しいノード型も
新しいコード生成ロジックも不要(`MultipleAssign`(知見122)・
`ForEachRow`(知見118)と同種の「既存ノードの無料の再利用」パターン)。

文法上は`_NEW.2: /New\b/i`という大文字小文字不区別キーワード
トークン(既存の`TRUE`/`FALSE`/`NOTHING`等と同じパターン)を追加し、
`?atom`規則に`_NEW IDENT "(" ")" "{" arglist "}" -> new_array_lit`を
追加しただけ。型名(`Integer`/`String`等)を保持しないため、この形で
入力した式を`render_expr`で往復させると出力は`{1, 2, 3}`(波括弧形)に
なる——値の意味論は完全に同じだが、入力テキストとの文字単位の往復は
保証しない(既存の`render_expr`全体の既知の制約と同種)。

`dump_daemon/uipath_expr/__init__.py`のみ変更(文法・`_NEW`トークン・
`_ExprTransformer.new_array_lit`)。`uipath_codegen/render.py`は
`ArrayLiteral`を既に汎用的にPythonリストへ変換済みのため無変更。
`tests/test_uipath_expr.py`に2件追加、全500件通過(リポジトリ全体で
全1396件通過)。残り1件(`InputDialog`)は、実機での正確な属性構成
(`Title`/`Label`/`DefaultValue`等)がまだ未確認のため引き続き見送り。

## 126. 「実機XAMLに対する実際のコード生成の検証」を未使用の新規25リポジトリへ適用——`Split`関数を新規実装、知見74の`row(...)`添字曖昧性に実需要の裏付けを発見(知見117〜125の手法を継続、VM不使用)

知見117〜125の手法を、これまで使っていなかった25件の新規GitHubリポジトリ
(`gh api search/code`で`extension:xaml uipath`検索、`mihhdu/
Enhanced-REFramework`・`ShonHarsh`系の複数リポジトリ・`HAC-2020/
rocket`・`nkarkare/UDISEAutomation`等)の`Main.xaml`へ適用した。25件中
23件が`parse_workflow_file`+`generate_python`を例外無しで完走(残り2件は
State Machineルート——知見済みのv1スコープ外として想定通り`ValueError`)。
`# TODO`件数は0〜7件まで様々で、新しい未確認パターンが多数残っている
ことを確認した一方、2件の`NotImplementedError`例外(`# TODO`より重い、
パース自体は成功するがコード生成が構文全体を落とす)を発見した。

**解決: `Split`関数**(`HAC-2020/rocket`ではなく`nkarkare/
UDISEAutomation`の実機XAML、`Split(in_Category, ",")`)。`Microsoft.
VisualBasic.Strings.Split(Expression, Delimiter, Limit, Compare)`の
4引数オーバーロードのうち、実機で確認できた2引数形(`Expression`+
`Delimiter`のみ)だけを`str.split(delimiter)`へ対応させた。`Delimiter`
省略時の既定値(半角スペース)・`Limit`(VBの「返す要素数」とPythonの
`maxsplit`の「分割回数」は算術的に1つずれる)・`Compare`(大文字小文字
無視分割)付きの3引数・4引数形は未確認のため`# TODO`へ明示的に倒す。
既知の限界として、リテラル空文字列`Delimiter=""`の場合はVBが元の文字列
1件だけの配列を返す一方Pythonの`str.split("")`は`ValueError`になる
食い違いがあるが、実機でこの形にまだ遭遇していないため対応を見送る
(知見42と同種の、確認済みの範囲外は無理に埋めない方針)。

**未解決・既存の確認済み制約への実需要の裏付け: `row(...)`添字**
(`HAC-2020/rocket`、`row("E-Mail")`/`row(in_Config("NameHeader").
ToString)`等)。これは知見74で既に文書化済みの「VB.NETは配列/コレク
ション/DataTable行アクセスも関数呼び出しと全く同じ`識別子(引数)`構文を
使うため、静的型情報無しでは構文だけで判別不能」という言語レベルの
曖昧性そのもの——知見74は当時「変数宣言を追跡して曖昧性を解消する設計は
実機確認済みの需要が無いため見送った」としていたが、今回`ForEachRow`
(知見118、`TypeArguments="sd:DataRow"`確認済み)の反復変数`row`に対する
`row("列名")`呼び出しという、まさにその想定ケースの実需要を確認した。
解消には、`uipath_dsl`→`uipath_codegen`の生成パス全体を通じて「この
識別子はどのスコープでDataRow型として束縛されたか」という変数スコープ
情報を新たに追跡する必要があり、現状の`render_expr`/`_render_node`は
式単体を引数の型情報無しに文字列へ変換する純粋関数で、この手の
文脈情報を一切持たない——`AddDataRow`(知見122で見送った別件、
クロスノードのDataTableスキーマ解決が必要)と同種の「新しいアーキテク
チャ設計が必要」な課題であり、今回は見送って設計課題として記録する
(でっち上げた`row[...]`変換を、スコープ追跡無しに名前が`row`である
ことだけから推測することはしない)。

`dump_daemon/uipath_codegen/render.py`の`_render_func_call`に`split`
分岐を追加。`tests/test_uipath_codegen.py`に3件追加、UiPath関連テスト
全503件通過、リポジトリ全体で全1399件通過。

## 127. 関数呼び出しを介さない素の変数への**メソッド**呼び出し連鎖(`mail_Category.Equals(...)`)の文法ギャップを修正、`Len`関数を新規実装(未使用の新規24リポジトリでの実機検証、知見117〜126の手法を継続、VM不使用)

知見117〜126の手法を、さらに未使用の新規24件のGitHubリポジトリ
(`AsmaTrabelsi/RPA-Excel-Data-Entry-Automation`・`LowyShin/
lwrpa-uip-moveoldfiles`・`nmnithinkrishna/uipathos-manufacturing-
AutonomousProductFabrication`等)へ適用した。

**解決: 素の変数への関数呼び出し連鎖**。知見118は「関数呼び出し結果へ
のメンバ/メソッドアクセス連鎖」(`CStr(x).ToUpper()`)を、知見119は
「関数呼び出しを介さない素の変数への**プロパティ**アクセス連鎖、呼び出し
無し」(`intCounter.ToString`)を解決していたが、`nmnithinkrishna/
uipathos-manufacturing-AutonomousProductFabrication`の実機XAMLで
`mail_Category.Equals("Order")`という**第3のパターン**——関数呼び出しを
介さない素の変数への**メソッド**呼び出し連鎖(末尾が引数付き呼び出し)
——に遭遇し、`NotImplementedError`でコード生成全体が落ちることを発見
した。原因は知見119と同根: `IDENT`トークンの正規表現がドット区切りを
1トークンとして貪欲マッチするため、`mail_Category.Equals`全体が`(`に
到達する前に単一の関数名として吸収され、文法上`FuncCall(name=
"mail_Category.Equals", args=(...))`になってしまう——`postfix`規則
(知見118)には到達しない。

`_render_func_call`の末尾(確認済みTier1静的メソッド名のいずれにも
一致しなかった場合のみ到達する、静的クラス参照の誤変換を避けるため)に
新しい分岐を追加: `node.name`が`.`を含む場合、知見118の`_render_
chained_access`と全く同じアルゴリズム(先頭セグメントを基点とし、中間
セグメントは`_apply_chained_property`でプロパティ連鎖、末尾セグメント
は確認済みの安全な変換(`Equals`1引数→`==`、または引数無しの
プロパティ相当)のみ適用)を再利用する——新しい変換ロジックを追加した
わけではなく、既存の確認済みロジックを別の文法経路からも使えるように
しただけ。実機の`mail_Category.Equals("Order",
StringComparison.InvariantCultureIgnoreCase)`(2引数のカルチャ依存
比較オーバーロード)は、知見118で既に対象外と明示済みの形のため、この
新しい経路でも引き続き`# TODO`へ倒れる(回帰テストで確認——でっち上げ
無し)。

**解決: `Len`関数**(`LowyShin/lwrpa-uip-moveoldfiles`、`Len(sRstHttp)`)。
`Microsoft.VisualBasic.Strings.Len(Expression)`は文字列に対して文字数を
返し、Pythonの`len(str)`と直接対応する——実機で見つかった引数名は
いずれも文字列用途のHungarian記法(`s`接頭辞)だった。既知の限界として、
VBの`Len`は非文字列(構造体等)には別の意味論(バイトサイズ)があり
Pythonの`len()`とは食い違うが、実機確認は文字列用法のみのため文字列
用法を想定した直接マッピングとする(知見42と同種の、確認済みの範囲外は
無理に埋めない方針)。

**新たに見送ったもの**: `Directory.GetFiles(...).OrderBy(Function(s)
...).ThenBy(Function(s) ...)`(`pdmorale/OCR_Statistics`)——LINQの
`OrderBy`/`ThenBy`メソッドチェーン+ラムダ式(`Function(s) ...`)という、
`uipath_expr`文法が全く対応していない構文領域(関数リテラル自体が
未対応)で、`tree=None`への安全なフォールバックが正しく機能している
(クラッシュはしない、`# TODO`へ倒れる)。2件のState Machineルート
(`sujanfx/autopilot-hr`・`whooaaapppp/yearlyreport-uipath`)は既存の
v1スコープ外の判断(Phase 1)を想定通り再確認しただけ。

`dump_daemon/uipath_codegen/render.py`の`_render_func_call`に`len`
分岐+ドット付き関数名のフォールバック分岐を追加。`tests/
test_uipath_codegen.py`に4件追加、UiPath関連テスト全507件通過、
リポジトリ全体で全1403件通過。

## 128. 新しい実機データ源「`marcelocruzrpa/uipath-ai-skills`のground-truthコーパス」を発見——既存実装(Database/WebAPI)の既定値(`{x:Null}`)耐性を確認、新規未実装活動11件を棚上げ記録(コード変更無し、VM不使用)

知見117〜127の実機検証を拡張中に、`marcelocruzrpa/uipath-ai-skills`
リポジトリの`uipath-core/references/studio-ground-truth/`配下に、
UiPathパッケージ名・バージョンごとに整理された504件の`.xaml`参照
フィクスチャ(`UiPath.Database.Activities/2.0`・`UiPath.Excel.
Activities/3.4`(117件)・`UiPath.Mail.Activities/2.8`(45件)・
`UiPath.PDF.Activities/3.25`・`UiPath.Persistence.Activities/1.4`・
`UiPath.System.Activities/25.10・26.2`(199件)・`UiPath.Testing.
Activities/25.10`・`UiPath.UIAutomation.Activities/25.10`(76件)・
`UiPath.WebAPI.Activities/2.4`)を発見した——Studioから各活動を単体で
エクスポートしたと見られる`<Activity x:Class="...">`直下に活動1つだけ
を置く最小形(例: `<ui:DatabaseConnect DatabaseConnection="{x:Null}" />`)。
これまで集めてきた「実際のワークフロー(`Main.xaml`)」とは違う種類の
データ源——個々の活動の**完全な属性一覧**(デフォルト値込み)を
一括で確認できる点が貴重だが、値そのものはほぼ全て未設定
(`{x:Null}`)のデフォルトのみで、「実際に使われた値」の実例としては
弱い(`confirmed-safe-only`方針上、これだけでは新しい値の変換ロジックを
実装する根拠にはならない)。

**検証(コード変更無し)**: `UiPath.Database.Activities/2.0`の10件+
`UiPath.WebAPI.Activities/2.4`の`HttpClient`/`SerializeJson`/
`DeserializeJsonArray`を、`parse_activity()`+`_generate_node()`へ直接
(`Sequence`ラッパー無しで単体活動として)通し、既存実装
(`DatabaseConnect`/`DatabaseDisconnect`/`ExecuteQuery`/
`ExecuteNonQuery`、知見114/`HttpClient`、知見114)がこの「ほぼ全属性が
`{x:Null}`」という極端な既定値入力でもクラッシュしないことを確認した
——`DatabaseConnection="{x:Null}"`(出力先未束縛)は想定通り`# TODO`、
`HttpClient`の既定値一式(`Method="GET"`・`AcceptFormat="ANY"`・
`TimeoutMS="6000"`等)は`requests.request('GET', None, timeout=6.0)`を
正しく生成した(既存実装の防御的健全性の追加確認、新しい発見では無い)。

**新規未実装の棚上げ(将来の実装候補、実データ待ち)**: このコーパスで
初めて正確な属性名を確認した未実装活動11件——`BulkInsert`/
`BulkUpdate`/`InsertDataTable`/`DatabaseTransaction`
(`UiPath.Database.Activities`)、`SerializeJson`/`DeserializeJson`/
`DeserializeJsonArray`/`DeserializeXml`/`ExecuteXPath`/`GetNodes`/
`GetXMLNodes`/`GetXMLNodeAttributes`/`NetHttpRequest`
(`UiPath.WebAPI.Activities`)。属性名自体は権威的(UiPathパッケージ
本体からのエクスポート)だが、値が全て`{x:Null}`のため実際の使用パターン
(例: `SerializeJson`の`Settings`に何が入るか)は未確認——実装には
別途、非デフォルト値を持つ実機`Main.xaml`での使用例が必要(今回は
値の実例が無いため実装を見送る、でっち上げ回避)。`design/
uipath_feature_catalog.md`に参照ポインタとして記録した。
`UiPath.Excel.Activities`/`UiPath.Mail.Activities`/`UiPath.System.
Activities`/`UiPath.Testing.Activities`/`UiPath.UIAutomation.
Activities`(合計400件超)はまだ未検証——今後のtickで継続する価値がある。

## 129. 【重要】`UiPath/skills`公式リポジトリで240件のC#式言語実機プロジェクトを発見——VB.NET専用という前提の再検討が必要(知見117〜128の手法を継続、VM不使用)

これまでの実機検証(知見117〜128)は、見つかった実プロジェクトが
全て`expressionLanguage: "VisualBasic"`(VB.NET)だったため気づかなかったが、
`UiPath`公式GitHub Organizationの`skills`リポジトリ(`uipath-ai-skills`
とは別物、UiPath社自身が管理するリポジトリ)の`tests/tasks/
uipath-troubleshoot/activity-packages/`配下に、240件の「特定のエラー
シナリオを再現するための意図的に構成された」`Main.xaml`プロジェクトが
あることを発見した(`db-execute-query-timeout-expired`・
`word-replace-text-headers-skipped`・`uia-alter-if-disabled`等、
活動パッケージ×エラーシナリオ別に命名)。サンプリングした全ての
`project.json`(`db-*`系4件・`word-*`系1件・`uia-*`系1件・`sys-*`系1件、
計7件)が`"expressionLanguage": "CSharp"`だった——これは design/
uipath_xaml_findings.md本ファイルの「今後の調査候補」に記録済みの
「C#式言語プロジェクトでのInArgument/OutArgumentの直列化形式の違い」
(当時はStudio 2021.4.4に式言語選択UIが見当たらず実機確認を断念していた
項目)に対する、**実機証拠を伴う初めての反証**——これまで「VB.NET固定」
と結論していたが、より新しいStudio(22.x以降、またはC#を明示指定する
別の作成経路)で生成されたC#式言語プロジェクトが実在し、しかもこの
公式リポジトリでは**サンプリングした範囲内で全件がC#**だった。

**実機確認した直列化形式の違い**(`db-execute-query-clr-crash`の
`DatabaseConnect`より):
```xml
<ui:DatabaseConnect.ConnectionString>
  <InArgument x:TypeArguments="x:String">
    <CSharpValue x:TypeArguments="x:String">"Server=...;..."</CSharpValue>
  </InArgument>
</ui:DatabaseConnect.ConnectionString>
<ui:DatabaseConnect.DatabaseConnection>
  <OutArgument x:TypeArguments="uidb:DatabaseConnection">
    <CSharpReference x:TypeArguments="uidb:DatabaseConnection">dbConnection</CSharpReference>
  </OutArgument>
</ui:DatabaseConnect.DatabaseConnection>
```
VB.NETの`[...]`角括弧省略記法(知見14)の代わりに、値は`<CSharpValue>`
(式テキストをC#構文のまま保持、今回の例では単純な文字列リテラル)、
出力変数参照は`<CSharpReference>`(VBの`OutArgument`直下テキストと違い、
もう1段ネストした要素)というC#専用のラッパー型で直列化される——VB式の
`[...]`省略記法は一切使われない。属性ショートハンド形(`Property="[...]"`)
自体がVB式言語専用の記法であり、C#式言語プロジェクトでは常にこの
プロパティ要素+`CSharpValue`/`CSharpReference`形になると推測される
(今回確認した7件のサンプル全てで一貫していた)。

**現状の挙動(クラッシュ無し、正しく保守的)**: `_attr_expr`は`[...]`
角括弧属性を期待するため、C#式言語のプロパティ要素形では常に`None`を
返し、既存の「値が無い場合は`# TODO`」という保守的な経路へ正しく
フォールバックする——`uipath_codegen`はクラッシュせず、でっち上げた
誤変換も生成しない(今回検証した24件中、例外は0件)。ただし実質的に
C#式言語プロジェクト全体がほぼ`# TODO`ばかりになり、カバレッジは
VB.NETプロジェクトに比べて大幅に低い。

**今回は実装を見送る(大規模な設計判断が必要)**: C#式言語への対応は、
今回のtickで安全に収められる規模を超える——少なくとも(1)
`<CSharpValue>`/`<CSharpReference>`のプロパティ要素形を一般的に解析
する経路の新設、(2)C#式テキスト自体を構文解析する全く別の文法
(`uipath_expr`はVB.NET文法専用、C#は演算子・リテラル構文がVBと異なる
——例: 文字列連結`&`→`+`、比較`AndAlso`/`OrElse`→`&&`/`||`、代入無し
三項演算子の構文等)、(3)ワークフロー全体がC#かVBかをどう判定するか
(`project.json`の`expressionLanguage`は読んでいない——現状の
`parse_workflow_file`はXAML単体しか読まずProject全体のメタデータには
アクセスしない設計)が必要になる——`AddDataRow`(知見122)・`row(...)`
スコープ追跡(知見126)と同種どころか、それ以上に大きい「新しい式言語
バックエンドの追加」という設計判断であり、今回は見送って重要な設計
課題として記録する。

**次のtickへの引き継ぎ事項**: この`UiPath/skills`リポジトリの240件の
シナリオ(`db-*`13件・`word-*`7件・`web-*`4件・`uia-*`1件・`sys-*`2件を
ダウンロード済み、`/tmp/batch7`は本tick終了時に削除済み)は、公式かつ
意図的に構成された高品質な実例データであり、C#対応を実施する際の
一次データ源として再度ダウンロードする価値が非常に高い——VB.NET
プロジェクトも含まれている可能性があるため(今回は未確認)、全240件の
`project.json`を先にスキャンして言語別に分類するところから始めると
良い。

## 130. 静的メソッド3件(`File.ReadAllBytes`/`Convert.ToBase64String`/`Path.GetFileNameWithoutExtension`)+`DataTable.Copy`を新規実装、VB.NETの識別子大文字小文字の揺れによる【重大】な潜在バグを発見(未使用の新規25リポジトリでの実機検証、知見117〜129の手法を継続、VM不使用)

知見117〜129の手法を未使用の新規25リポジトリへ適用した。24件が
例外無しで完走(1件はState Machineルート、想定通り)。

**解決: 静的メソッド3件+`DataTable.Copy`**(`Dits21/Proyecto-Sistema-
RPA-para-mejorar-el-procesamiento-de-lectura-de-facturas-`の1ファイル
で4件とも発見、OCR結果画像のBase64エンコード処理)。`System.IO.File.
ReadAllBytes(path)`→`open(path, 'rb').read()`、`System.Convert.
ToBase64String(Byte())`→`base64.b64encode(bytes).decode('ascii')`
(返り値を.NET同様の`String`に揃える)、`System.IO.Path.
GetFileNameWithoutExtension(path)`→`os.path.splitext(os.path.
basename(path))[0]`をいずれも1引数の確認済み形のみ`_render_func_call`
の確認済み静的メソッド一覧に追加した(`String.IsNullOrEmpty`と同じ
パターン)。`DataTable.Copy()`(括弧省略形`dtUB92.Copy`で実機確認)は
既存のDataTable表現(`list[dict]`)に対応する、各行の辞書も独立させる
リスト内包表記へ対応——`_apply_chained_property`(知見118/119/127で
確立した「安全なメンバ名のみ変換」の共通経路)に追加し、知見119の
`Ident`分岐の安全リストにも`Copy`を加えた(呼び出し構文の有無を問わず
同じ経路を通る)。

**追加確認(コード変更無し)**: `row(...)`/`keyrow(...)`のDataRow添字
曖昧性(知見126で発見・保留)の、さらに2件目(`Pk-NY/
Information_on_IssueData_RPA_Uipath`)の実機確認——`ForEachRow`反復
変数名が`row`以外(`keyrow`)でも同じ曖昧性が起こることを確認した
(保留方針に変更無し、知見126の設計課題としての優先度を補強する
証拠として記録)。

**【重大、未解決】VB.NETの識別子は大文字小文字を区別しないが、本
トランスパイラは区別する——同一識別子の大文字小文字の揺れで異なる
Python変数が生成されうる**(`TanMzCs2025/
EDSAChallengeTania2025_AmazonProductSearchAndFilter`の`Browser_
ValidateLangAndCur.xaml`で発見)。このXAMLは`OutArgument`を
`out_RequirementLanCur`(小文字`o`)という名前で宣言しているが、本体の
`Assign`アクティビティは`To`で`Out_RequirementLanCur`(大文字`O`)という
**別の表記**を使って同じ引数を参照している——VB.NET自体は大文字小文字を
区別しない言語のため、Studio/.NETコンパイラはこの2つを同じ変数として
正しく解決する。しかし本トランスパイラは各識別子の参照をXAML中に現れた
まさにそのテキストのままPython識別子として素通りさせるため(`render_
expr`/`_render_node`の`Ident`処理は常に文脈自由な純粋関数)、生成された
Pythonコードでは`out_RequirementLanCur`(関数の仮引数)と
`Out_RequirementLanCur`(本体内で新たに作られる無関係なローカル変数)
という**2つの別々の変数**になってしまう——`# TODO`で保守的に失敗する
のではなく、**構文的には正しいが意味的に誤ったコードを静かに生成する**
という、知見74/118/119/126よりも深刻な種類の問題(値の食い違いが実行時
まで表面化しない)。

この問題は今回発見した1箇所(`OutArgument`の参照)に限らず、**通常の
ローカル変数の読み書きでも理論上同じように起こりうる**——VB.NET識別子
が大文字小文字の揺れを許す以上、ソースのどこでも起こりうる一般的な
問題である。解消には、ワークフロー(または関数)単位で宣言済みの変数・
引数名を大文字小文字を区別せずに正規化されたPython識別子へ対応付ける
名前解決パスが必要——現状の`render_expr`/`_render_node`には宣言済み
名前の集合を渡す仕組みが無く、知見122の`AddDataRow`(クロスノードの
DataTableスキーマ解決)・知見126の`row(...)`(変数スコープのDataRow型
追跡)に続く**3件目の「スコープ情報が式レンダリングに必要」という実需要
の確認**であり、かつ重大度は最も高い(他の2件は保守的に`# TODO`へ倒れる
が、この問題は倒れずに誤ったコードを生成する)。今回は実装を見送るが、
次に「スコープ対応のコード生成アーキテクチャ」を設計する際は、この
識別子大文字小文字正規化を**最優先**の要件として含めるべきと判断し、
重要な設計課題として記録する。

`dump_daemon/uipath_codegen/render.py`の`_render_func_call`に静的
メソッド3分岐、`_apply_chained_property`/`Ident`分岐に`Copy`を追加。
`dump_daemon/uipath_codegen/__init__.py`の`_collect_imports`に`base64`
検出を追加。`tests/test_uipath_codegen.py`に4件追加、UiPath関連テスト
全511件通過、リポジトリ全体で全1411件通過。

## 131. `ui:InputDialog`を新規実装(知見122で発見・保留していた最後の1件、`MessageBox`とは異なる「直接対応」の判断、VM不使用)

知見122・124・125で見送った3件のうち、唯一残っていた`InputDialog`
(「対話的な入力の非対話変換という設計判断が必要」としていた項目)を
今回解決した。GitHub検索(`ui:InputDialog extension:xaml`、総計5176件)
で実機確認した2件(`cameronmcnz/uipath-tutorials`の`NumberGuesser`・
`MIETDevelopers/112-KavyaDhar-RPA`の`UserInp`)は属性構成が完全に一致:
`Title`/`Label`(両方リテラル文字列)・`IsPassword="False"`・
`Options="{x:Null}"`(2件とも未設定)・`.Result`プロパティ要素
(`OutArgument`、知見115の`_in_argument_property_expr`をそのまま再利用)。

**`MessageBox`(知見2・5・79・107)とは異なる設計判断**: `MessageBoxNode`
のdocstringには「でっち上げた`input()`等のユーザー入力再現は行わない」
と明記されている——`MessageBox`は通知/選択ダイアログであり、`input()`
への変換は意味論上の飛躍(ユーザーの選択という行為を、存在しない対話的
入力で置き換える推測)になるため。しかし`InputDialog`はそもそも
「ユーザーにテキスト入力を求め、その結果を`Result`へ返す」活動
そのもので、Pythonの`input()`組み込み関数が**まさに同じ意味論**
(テキストを促し、文字列を返す)を持つ——これは代替・妥協ではなく
直接対応する変換であり、`MessageBox`の既存方針と矛盾しない(方針が
適用される前提——「対話を模倣する推測」——がそもそも当てはまらない
ケース)。`Title`/`Label`は`MessageBox`の`Caption`/`Text`と同じ
「`Title`が無い場合は`Label`のみ、ある場合は`"Title: Label"`形で結合」
という既に確立したパターンをそのまま流用した。

**実機確認済みの範囲のみ対応**: `IsPassword="True"`(パスワード入力、
`getpass.getpass()`が対応先と推測されるが実機未確認)・`Options`設定済み
(選択肢付きダイアログに変わると推測されるが実機未確認)は、2件とも
確認できなかったため推測せず`# TODO`へ倒す——`MessageBox`の`Buttons`/
`ChosenButton`の扱いと同じ「ワークフローが対話の結果を実際に使っている
可能性がある場合は安全側に倒す」方針を踏襲した。

`dump_daemon/uipath_dsl/types.py`に`InputDialogNode`、`xaml_tree.py`に
`_parse_input_dialog`、`uipath_codegen/__init__.py`に`_generate_input_
dialog`を追加。`tests/test_uipath_dsl.py`に1件・`tests/
test_uipath_codegen.py`に5件追加、UiPath関連テスト全517件通過
(リポジトリ全体は、並行作業中の別セッションのPAD系未完了変更により
`test_pad_codegen.py`の4件が別途失敗中——本変更とは無関係、UiPath関連
テストのみで検証)。

## 132. 【重要】libxml2のxmlns値過剰検証でREFramework共通ファイルがパース不能になるバグを発見・修正(未使用の新規23リポジトリでの実機検証、VM不使用)

知見117〜131の手法を未使用の新規23リポジトリへ適用する過程で、
`mnsy1/UiPath_ACMEVerifyAccountPositions`の`RetryCurrentTransaction.xaml`
——REFramework(多数のUiPathプロジェクトの標準テンプレート)に含まれる、
極めて典型的で広く使われているファイル——が`lxml.etree.XMLSyntaxError`
でXML解析自体の段階から完全に失敗することを発見した。原因は`xmlns:mv=
"clr-namespace:Microsoft.VisualBasic;assembly=Microsoft.VisualBasic,
Version=10.0.0.0, Culture=neutral, PublicKeyToken=b03f5f7f11d50a3a"`
という、アセンブリ完全修飾名(`Version`/`Culture`/`PublicKeyToken`を
含む、空白とカンマを含む)を値に持つ`clr-namespace`形のxmlns宣言——
libxml2がこれを「valid URIではない」と過剰に厳格な検証で拒否する
(XML Namespaces仕様自体はxmlns値を厳密なRFC3986 URIに制限しておらず、
.NET/WPF/WFの慣習として空白・カンマを含むアセンブリ修飾名形式が広く
使われている——XAML自体は不正ではない、libxml2側の既知の過剰検証)。

`parse_workflow_file`の`etree.parse(str(path))`を`try`で囲み、
`XMLSyntaxError`のメッセージが`"is not a valid URI"`を含む場合**のみ**
`etree.XMLParser(recover=True)`の寛容パーサーへフォールバックするよう
修正した——他の種類のXML構文エラー(閉じタグ不整合・切断されたファイル
等、本物の壊れたファイル)は従来通りそのまま例外を伝播させる、エラー
メッセージで厳密に絞った狭い修正(`recover=True`を無条件に使うと
本物の構文エラーも静かに握り潰してしまうリスクがあるため避けた)。

**影響範囲の推定**: `RetryCurrentTransaction.xaml`はREFrameworkの標準
構成ファイルの1つで、REFrameworkベースの実プロジェクトは非常に多い
(知見で蓄積した実例でも複数回遭遇済み)——この1つのバグ修正で、今後
検証する実プロジェクト全体のうち無視できない割合が、XML解析の入口で
即座に弾かれる状態から救われると見込まれる。

`dump_daemon/uipath_dsl/xaml_tree.py`の`parse_workflow_file`のみ変更。
`tests/test_uipath_dsl.py`に合成XMLで同じxmlns値を再現する回帰テストを
1件追加。

## 133. 文字列/配列の`.Contains`/`.Length`+`Directory.GetFiles`を新規実装(知見132と同じ検証バッチの継続、VM不使用)

**解決: `.Contains(arg)`**(`sarvesh0718/RCM-Bot-using-uipath-studio`・
`harsranjan/RPA`の実機XAML、いずれも`strXxx.ToLower.Contains(...)`
という形で発見)。知見127で確立した「素の変数への連鎖呼び出し」
フォールバック経路・知見118の`_render_chained_access`経路の両方に
`Contains`(1引数)を追加——どちらも「`base`は既にレンダリング済み
文字列、末尾セグメントだけ未確定」という同じ形に帰着するため、重複して
いた`Equals`判定ロジックを`_apply_chained_call`という共通ヘルパーへ
まとめ、そこへ`Contains`を追加した(リファクタと機能追加を同時に
行った——`Equals`判定の重複が3箇所目になりそうだったタイミングで
整理)。`String.Contains(value)`はPythonの`in`演算子と同じ意味論
(包含判定、オペランドの順序が逆になる点に注意: `base.Contains(x)`→
`x in base`)。

**解決: `Directory.GetFiles(path)`**(`dexbob/RPA_Example`の実機XAML
`Directory.GetFiles(Str_OutputFolder)`で発見)。検索パターン・再帰
オプションを省略した1引数の確認済み形のみ、指定ディレクトリ直下の
ファイルのみ(サブディレクトリは含まない、.NETの既定動作)をフルパスで
列挙するリスト内包表記(`[os.path.join(p, n) for n in os.listdir(p)
if os.path.isfile(os.path.join(p, n))]`)へ対応した。

**解決: `.Length`**(同じ実機XAMLで`Directory.GetFiles(...).Length`と
連鎖して使われていた、括弧省略形)。.NETの`Length`プロパティは配列
(`String()`等)・文字列(`String.Length`)のいずれでも文字数/要素数を
返す——Pythonの`len()`に型を問わず同じ意味論で直接対応するため、
`_apply_chained_property`(連鎖呼び出し経路)と知見119の`Ident`分岐
(呼び出し無しの素の変数への連鎖、`_SAFE_BARE_MEMBERS`へ追加)の
両方に追加した。

`dump_daemon/uipath_codegen/render.py`に`_apply_chained_call`
(新設、`Equals`/`Contains`の共通ロジック)・`directory.getfiles`
分岐・`Length`/`_SAFE_BARE_MEMBERS`を追加。`tests/
test_uipath_codegen.py`に6件追加、UiPath関連テスト全523件通過
(リポジトリ全体は`test_pad_codegen.py`を除き全1133件通過)。

## 134. `String.IsNullOrWhiteSpace`/`Path.Combine`/`Directory.Exists`を新規実装、`Directory.GetFiles`に2引数形(`searchPattern`)を追加(未使用の新規15リポジトリでの実機検証、知見132で修正したREFramework共通ファイルの再確認含む、VM不使用)

知見117〜133の手法を未使用の新規15リポジトリへ適用した。知見132で
修正したlibxml2のxmlns過剰検証問題の効果を、同じ`RetryCurrentTransaction.
xaml`の別の2インスタンス(`ahmed-ismail999/
RPA-UiPath--Verify-Account-Position`・`MarkRaef/UiPath`)で再確認した
——いずれもXML解析自体は正常に通過し(修正前は即座に失敗していた)、
`in_Config(...)`という既知の配列添字曖昧性(知見74)でのみ`# TODO`相当の
decline(`If`条件内のため例外伝播、想定通り)に至る——REFramework系の
実プロジェクトへの実際の効果を確認できた。

**解決: `String.IsNullOrWhiteSpace(value)`**(`Ray-Tel/CICDtest`の実機
XAML`String.IsNullOrWhiteSpace(in_ConfValueExpectedResult)`で発見)。
既存の`String.IsNullOrEmpty`(知見96)と同じパターンで追加——`null`・
空文字列・空白のみの文字列いずれも`True`を返す仕様を`(not (value or
'').strip())`で再現する(`value or ''`が`None`も空文字列に正規化)。

**解決: `Path.Combine(path1, path2, ...)`**(同上の実機XAML`Path.
Combine("Tests\Cache\", targetFile+"..."+".json")`で発見)。.NETの
2〜4個の固定オーバーロード+`params`配列版はいずれも「N個のパス片を
順に連結する」という同じ意味論で、Pythonの`os.path.join(*paths)`も
同じ可変長引数の連結ユーティリティ(後続引数が絶対パスの場合に
それ以前を無視する挙動も共通、.NET公式ドキュメント確認済み)のため、
引数個数2以上なら安全に対応できると判断した。

**解決: `Directory.Exists(path)`**(`manju1201/RPA_UiPath`の実機XAML
`Directory.Exists(ScreenshotFileInfo.DirectoryName)`で発見)。`os.path.
isdir(path)`へ直接対応。

**解決: `Directory.GetFiles`の2引数形**(`aimannoor17/
UiPath-Automation-Projects`の実機XAML`Directory.GetFiles(
"samples/scanned-reports","*.pdf")`で発見)。知見133で実装した1引数形
に加え、`searchPattern`付きの2引数形を追加——.NETの`*`/`?`ワイルド
カード構文はPythonの`glob`モジュールと同じ記法のため`glob.glob`を
使い、結果をディレクトリも含めてしまう可能性があるため`os.path.
isfile`で絞り込み、1引数形と同じ「ファイルのみ」という契約を保った。

**新たに発見したが今回は見送ったもの**: `Path.Combine`以外の
`.Combine(...)`以外の未知メソッド(`.GetField(...)`・`.ToSingle(...)`、
おそらくDocument Understanding関連のカスタム型のメソッド、実機確認
不足)・`Newtonsoft.Json.JsonConvert.DeserializeObject(Of T)(...)`
(VB.NETのジェネリック型引数`(Of T)`構文自体が`uipath_expr`文法で
全く未対応——新しい構文領域、関数リテラル同様に将来の拡張候補として
記録)。

`dump_daemon/uipath_codegen/render.py`に静的メソッド3分岐
(`string.isnullorwhitespace`/`path.combine`/`directory.exists`)+
`directory.getfiles`の2引数形拡張。`dump_daemon/uipath_codegen/
__init__.py`の`_collect_imports`に`glob`検出を追加。`tests/
test_uipath_codegen.py`に4件追加、UiPath関連テスト全527件通過、
リポジトリ全体で全1445件通過(並行作業中の別セッションのPAD系問題も
解消済み)。

## 135. `ExcelWriteCellNode`に`display_name`を追加(知見119で「スコープを絞るため見送った」としていた既知のバックログ項目、VM不使用)

知見119で「`ExcelWriteCellNode`には`display_name`フィールドが(他の
Excel活動と違い)無い——実機では`DisplayName`属性が存在するため将来
追加する価値はあるが、今回はスコープを絞るため見送った」と明示的に
記録していた項目を解決した——新しい実機検証では無く、既に確認済みの
実機データ(`PacktPublishing/Robotic-Process-Automation-Projects`の
`Cell="[&quot;B&quot;+intCounter.ToString]" DisplayName="Write Cell"`)
を元に、既存のテストフィクスチャですら`DisplayName`属性自体は含んで
いたが未検証だった値を確認・配線しただけの、ノーリスクな後片付け。

`ExcelReadCellNode`/`ExcelReadRangeNode`/`ExcelWriteRangeNode`/
`ExcelAppendRangeNode`は既に知見84の`_with_scope_child_display_name`
(スコープ子の生成行を`# {display_name}`コメントで包む共通ヘルパー)を
使っていたが、`ExcelWriteCellNode`だけが取り残されていた——`types.py`
に`display_name: str | None = None`フィールドを追加、`xaml_tree.py`の
`_parse_excel_write_cell`に`display_name=_attr(elem, "DisplayName")`を
追加、`uipath_codegen/__init__.py`の`_generate_excel_application_scope`
内の呼び出しを他のExcel活動と同じ`_with_scope_child_display_name`経由
に変更しただけで、新しい生成ロジックは一切追加していない。

既存の`tests/test_uipath_dsl.py`の`test_excel_write_cell_with_dynamic_
cell_expression`に`node.display_name == "Write Cell"`の検証を追加
(XMLフィクスチャ自体は変更無し、元々未検証だった値を検証対象に
加えただけ)。`tests/test_uipath_codegen.py`に1件追加、UiPath関連
テスト全528件通過、リポジトリ全体で全1446件通過。

## 136. 【重大バグ】`Assign`/`MultipleAssign`の`.To`がC#式言語形(`<CSharpReference>`)等の未対応ネスト要素を持つ場合、構文的に無効なPythonコードを生成していたバグを発見・修正(未使用の新規13リポジトリでの実機検証、VM不使用)

知見117〜135の手法を未使用の新規13リポジトリへ適用する過程で、
`ShonHarsh/Wordle-Default-Word-Engine`の実機XAMLから生成したPythonコード
に`'\n                  ' = 'Wordle-Default-Word-Engine.Main.
OperationCompleted;'`という、**文字列リテラルへの代入**という構文的に
無効なコードが混入していることを発見した——`generate_python()`自体は
例外無く完走していたため、`# TODO`の個数だけを見る通常の検証手順では
検出できなかった(今回`compile()`で実際にコンパイルを試して初めて
発覚——このバグはいつから存在していたか不明で、過去のtickで生成した
コードが同じ理由で無効になっていたケースを遡って検出する手段は無い)。

**根本原因**: `xaml_tree.py`の`_argument_text(prop_elem)`
(`Assign`/`MultipleAssign`の`.To`/`.Value`で共通使用)は、`<Assign.To>`
直下の`OutArgument`/`InArgument`要素自身の`.text`を返す——通常は
`<OutArgument>[result]</OutArgument>`のように直接テキストを持つが、
知見129で発見したC#式言語形では`<OutArgument><CSharpReference>
message</CSharpReference></OutArgument>`のようにテキストの代わりに
ネストした子要素を持つ。この場合`.text`(lxml)は「開始タグ直後から
最初の子要素タグ直前まで」のテキスト、つまりネスト要素前の改行+
インデントの**空白のみ**を返す——`_argument_text`はこれを無条件に
返していたため、`_parse_expr`が角括弧記法に一致しないその空白文字列を
そのまま`Literal(value='\n    ')`として採用し、最終的にコード生成側が
これを代入先(`target`)としてそのまま埋め込んでいた。

**修正**: `_argument_text`に「子要素の`.text`が空白のみ、かつその子
要素自身がさらに子要素を持つ(=ネストした未対応の要素形)」場合は
`None`を返すガードを追加——でっち上げた空白文字列を使わず、呼び出し元
の既存の`# TODO`フォールバックに委ねる。さらに`_generate_assign`
(`node.target is None`)自体にも**別の**潜在バグがあったことを同時に
発見した——`_render_value_or_todo(None, ...)`は例外を投げずに素の文字列
`"None"`を返す仕様(`render_expr(None) == "None"`)のため、これを放置
すると今度は`None = value`という**別の**構文的に無効なコードを生成して
しまう。`node.target is None`を明示チェックし、代入文を一切生成せず
`# TODO: Assign with no target (To) captured`へ倒すよう修正した——
2つの異なる経路で同じ「無効なPythonコード生成」という結果に至っていた
ため、両方を塞いだ。

**教訓**: `# TODO`の個数や例外の有無だけでは「生成されたコードが実際に
有効なPythonか」を保証できない——`_compiles()`(テストスイートでは
既に徹底されている)のような実際のコンパイル検証を、今後の実機検証
バッチでも(テストに限らず)一次チェックとして併用する価値がある。

`dump_daemon/uipath_dsl/xaml_tree.py`の`_argument_text`・
`dump_daemon/uipath_codegen/__init__.py`の`_generate_assign`を修正。
`tests/test_uipath_dsl.py`に1件・`tests/test_uipath_codegen.py`に1件
追加、UiPath関連テスト全530件通過、リポジトリ全体で全1454件通過。

## 137. 【重大バグ・続報】`Assign`の代入先レンダリング失敗で`None = None`という無効なPythonコードを生成していた、知見136で塞ぎ切れていなかった別経路を発見・修正(知見136の教訓を即座に実践、`compile()`を実機検証の標準手順に追加、VM不使用)

知見136の教訓(「`# TODO`の個数や例外の有無だけでは生成コードの妥当性を
保証できない」)を即座に実践し、本tickの実機検証から`compile()`による
構文検証を標準手順に加えた——未使用の新規13リポジトリを検証した結果、
`agilashree/220701015-OAI1903-RPA-Lab`の実機XAMLで**別の経路**から同じ
「無効なPythonコード生成」バグが再発していることを即座に発見した。

**根本原因(知見136と異なる経路)**: 知見136で修正したのは`node.target
is None`(`.To`自体が未捕捉)の場合だが、今回発見したのは`target`自体は
有効な`VbExpr`として存在するが、その**レンダリングが失敗する**
ケース——`ForEach`ループ内で`CurrentRow(0)`(知見74の配列/DataTable行
添字と関数呼び出しの構文的曖昧性、確認済みの既存の決定)を代入先に使う
実例(`CurrentRow(キー) = 値`という、VB.NETではDataRowの列への代入)。
知見136修正後の`_generate_assign`は`target`も`value`と同じ
`_render_value_or_todo`経由でレンダリングしていたが、この関数は失敗時
に例外を投げずに素の文字列`"None"`を返す仕様——これを代入先として
使うと`None = None`(`None`はPythonの予約済み特殊値で代入先にできない)
という構文的に無効なコードになる。知見136の修正は「`target`フィールド
自体が最初から`None`」という狭いケースだけを塞いでおり、「`target`は
存在するがレンダリングに失敗する」というより一般的で実際に多く
発生するケースを塞ぎ切れていなかった。

**修正**: `_generate_assign`で`target`を`render_expr`に直接通し、
`NotImplementedError`を明示的に捕捉——失敗したら代入文自体を一切生成
せず文全体を`# TODO`へ倒す(`value`側だけ失敗した場合は従来通り
`None`プレースホルダで代入文自体は維持する、非対称な扱いが正しい
——代入先が不明な文は意味を持たないが、代入先が分かっていて値だけ
不明な文は`x = None`という読める形で十分に有用なため)。

**教訓の強化**: 1つの`# {prefix}{target} = {value}`という形のコード
生成パターンに「失敗時に`"None"`という文字列を返す」ヘルパー
(`_render_value_or_todo`)を無差別に両側(target/value)へ適用すると、
ヘルパー自体は正しく動作していても呼び出し側の文脈(代入先と代入値の
非対称性)を無視した誤用になる——同種のパターン(他の活動の`target`的な
位置)が他にも潜んでいないか、今後の実機検証で`compile()`検証を継続する
価値がある。

`dump_daemon/uipath_codegen/__init__.py`の`_generate_assign`のみ変更。
`tests/test_uipath_codegen.py`に1件追加、UiPath関連テスト全531件通過、
リポジトリ全体で全1455件通過。

## 138. 【重大バグ・体系的な棚卸し】`ReadTextFile`にも同じ「代入先レンダリング失敗→無効なPythonコード」バグを発見・修正、他の全生成関数を体系的に棚卸しして健全性を確認(知見137の「同種のパターンが他にも潜んでいないか」を即座に実行、VM不使用)

知見137で記録した「同種のパターン(他の活動の`target`的な位置)が
他にも潜んでいないか」という申し送りを、新しい実機バッチを待たずに
即座に実行した——`uipath_codegen/__init__.py`内の`target = _render_
value_or_todo(...)`という形の呼び出し全箇所(`grep`で機械的に抽出)を
1つずつ確認し、直後に`if todo: return todo`(またはそれに相当する、
いずれかの値のレンダリングが失敗した場合に代入文自体を生成しない
ガード)があるかを棚卸しした。

**発見: `_generate_read_text_file`(`ReadTextFile`)にも同じ欠落が
あった**。他の約10個の類似関数(`DatabaseConnect`/`DatabaseDisconnect`/
`ExecuteQuery`/`ExecuteNonQuery`/`ExcelReadCell`/`ExcelReadRange`/
`GetOutlookMailMessages`/`InputDialog`(知見131で自分が書いた箇所も
含めて確認済み)等)は全て正しく`if todo: return todo`を守っていたが、
`_generate_read_text_file`だけがこのガードを欠いており、`node.content`
(読み取り結果の代入先)のレンダリングが失敗すると`None = open(...)...`
という構文的に無効なコードを生成しうる状態だった——知見136・137と
全く同じ根本原因(「失敗時に例外無く`"None"`を返す`_render_value_
or_todo`を代入先位置で無防備に使う」)の、第3の発生箇所。

**修正**: `_generate_read_text_file`に`if todo: return todo`を追加——
`file_name`/`content`いずれかのレンダリングが失敗した場合は代入文
自体を生成せず`# TODO`群のみを返す(他の類似関数と同じ、確立済みの
規約に単純に合わせただけ)。

**棚卸しの結果(他の全箇所は健全と確認)**: `_generate_assign`(知見
136・137で既に修正済み)・`_generate_read_text_file`(今回修正)以外の
全ての`target = ...`呼び出し箇所(約12箇所)は、既に`if todo: return
todo`または同等のガードを備えていることを確認した——新たな修正は不要。

`dump_daemon/uipath_codegen/__init__.py`の`_generate_read_text_file`
のみ変更。`tests/test_uipath_codegen.py`に1件追加、UiPath関連テスト
全532件通過、リポジトリ全体で全1460件通過。

## 139. `ToUpperInvariant`/`ToLowerInvariant`を新規実装、実機検証に`compile()`を標準手順として定着(未使用の新規13リポジトリでの実機検証、知見136〜138の教訓を実践、VM不使用)

知見136〜138で確立した「`# TODO`の個数や例外の有無だけでは生成コードの
妥当性を保証できない」という教訓を、本tickから標準の検証手順
(`compile()`で実際にコンパイルを試す)として恒常的に組み込んだ——
未使用の新規13リポジトリを検証し、構文エラーは0件だった(知見136〜138
で修正した3箇所の潜在バグが、少なくともこのサンプルでは再発していない
ことを確認)。

**解決: `ToUpperInvariant`/`ToLowerInvariant`**(`R1zzabh/signalforge`
の実機XAML`method.ToUpperInvariant`で発見、括弧省略形)。既存の
`ToUpper`/`ToLower`(知見118)と同じ`upper`/`lower`へ対応する——
「Invariant」(カルチャ非依存)の呼称が示す違いは、トルコ語の`i`/`İ`の
ような一部言語でのカルチャ依存の大小文字変換を避ける点だが、Pythonの
`str.upper()`/`str.lower()`はそもそもロケールを一切参照しない
(Unicode標準の単純な大小文字マッピングのみ)仕様のため、意味論上の
食い違いが無い——`_CHAINED_PROPERTY_TRANSLATIONS`辞書にキーを追加
するだけで、知見118の`_render_chained_access`・知見119の`Ident`分岐・
知見127の`_render_func_call`フォールバックの3経路全てに自動的に
反映された(辞書駆動の設計の利点)。

**新たに確認(コード変更無し)**: `config(...)`(`plaah/
web-application-with-rpa-dhl`)・`rjs(...)`(`cristinegulescu/
startUiPathFromSalesforce`)はいずれも知見74のDataTable行/配列添字
曖昧性の別インスタンス——既存の保守的な`# TODO`decline(`If`条件内の
場合は例外伝播)が正しく機能していることを再確認しただけ。

`dump_daemon/uipath_codegen/render.py`の`_CHAINED_PROPERTY_
TRANSLATIONS`に2キー追加。`tests/test_uipath_codegen.py`に2件追加、
UiPath関連テスト全534件通過、リポジトリ全体で全1462件通過。

## 140. `Environment.CurrentDirectory`を新規実装——呼び出しを伴わない静的クラスプロパティの完全修飾名一致という新しい対応パターンを導入(未使用の新規17リポジトリでの実機検証、`compile()`標準化を継続、VM不使用)

知見117〜139の手法を未使用の新規17リポジトリへ適用した。`compile()`
検証でも構文エラーは0件(知見136〜138で修正した潜在バグの再発無し)。

**解決: `Environment.CurrentDirectory`**(`E5Prasanth/Acme`の実機XAML
で発見、`Environment.CurrentDirectory & "\Data.txt"`という一時ファイル
パス構築パターン)。`System.Environment.CurrentDirectory`は呼び出しを
伴わない静的クラスの**プロパティ**(メソッドではない)で、Pythonの
`os.getcwd()`に直接対応する。

これまでの`ToUpper`/`Length`/`Copy`等の対応(知見118・119・130・133)は
いずれも「末尾セグメントの名前だけで、ベースが何であれ安全に適用できる
汎用メンバ」(例: `.ToUpper`は文字列である限り常に`str.upper()`)だった
が、`CurrentDirectory`はそうではない——`Environment`という**特定の
静的クラス**の文脈でのみ`os.getcwd()`を意味し、他の任意の変数の
`.CurrentDirectory`という同名メンバ(例えば架空の`FileInfo`型の変数)
まで同じに変換してしまうと誤変換になる。このため末尾セグメントだけを
見る既存の`_SAFE_BARE_MEMBERS`/`_CHAINED_PROPERTY_TRANSLATIONS`とは
別に、**完全修飾名(小文字化済み)で厳密に一致**させる新しい辞書
`_STATIC_PROPERTY_TRANSLATIONS`を導入した——`_render_node`の`Ident`
分岐で、末尾セグメント判定より先にこちらを調べる。回帰テストで、
無関係な変数の同名メンバ(`someFileInfo.CurrentDirectory`)が誤変換
されず従来通り無変換のまま通過することも確認した(でっち上げ回避の
直接的な検証)。

`dump_daemon/uipath_codegen/render.py`に`_STATIC_PROPERTY_TRANSLATIONS`
(新設)+`Ident`分岐への組み込み。`dump_daemon/uipath_codegen/
__init__.py`の`_collect_imports`の`os`検出条件に`os.getcwd(`を追加。
`tests/test_uipath_codegen.py`に2件追加、UiPath関連テスト全536件通過、
リポジトリ全体で全1464件通過。

## 141. 【重大バグ・第4の発生箇所】複数行のVB式テキストが`# TODO`コメントへそのまま埋め込まれ構文的に無効なPythonコードを生成していたバグを発見・修正、`display_name`コメント生成15箇所を共有ヘルパーへ統合(`compile()`標準化が初回で成果を出す、VM不使用)

知見139で`compile()`を実機検証の標準手順として定着させた直後の本tick
で、早速その効果が出た——未使用の新規15リポジトリの検証で
`JFHaataja/HAMK-miniprojekti`の実機XAMLから生成したPythonコードが
「タブとスペースの混在」という`compile()`時の構文エラーを起こすことを
発見した。これは知見136〜138(代入先レンダリング失敗)とは**別の根本
原因**を持つ、同じ「`# TODO`の個数や例外の有無だけでは生成コードの
妥当性を保証できない」という教訓の第4の実例。

**根本原因**: VB.NETは丸括弧内での改行(行継続)を許容する言語仕様
——実機XAMLには`PdfText.Substring(\n\tPdfText.IndexOf("Duedate:") +
9,\n(...)\n)`のような複数行にわたる式が実在した。この式の構文解析に
失敗すると、`render.py`の`render_expr`が`NotImplementedError(f"VB
expression failed to parse: {expr.text}")`を投げる——`expr.text`が
複数行のままこの例外メッセージに含まれる。これを`uipath_codegen/
__init__.py`の`_todo_value(prefix, expr_desc)`が単一行のf-stringへ
無防備に埋め込んでいたため、改行以降が`#`の付かない生のテキスト行
としてそのまま出力され、元のXAMLのインデント(タブ)がPythonコードの
インデントに紛れ込んで構文エラーになっていた。同じ無防備な埋め込みが
`_describe_expr_for_comment`の`VbExpr`分岐(`f"[{expr.text}]"`、`# TODO:
unknown activity`等のコメント内で使われる)にも存在した。

**修正**: `_todo_value`・`_describe_expr_for_comment`の`VbExpr`分岐の
両方で、埋め込む前にテキストの改行を`\n`リテラル(視認可能な2文字)へ
退避し、常に単一行のコメントであることを保証した。

**ついでに発見・同時対応**: `display_name`(`DisplayName`属性)を
`# {display_name}`コメントへ変換する処理(知見84の`_with_scope_
child_display_name`共有ヘルパー)にも同じ無防備な埋め込みがあった
(実機確認は無いが、`DisplayName`も理論上改行を含みうるため同じ防御を
適用——これは「VB式のでっち上げ」ではなく単なる防御的なコメント
安全化のため、確認済みの実需要を待たずに適用して問題ない)。さらに、
`_with_scope_child_display_name`と**全く同じロジック**
(`if node.display_name: return [f"{prefix}# {node.display_name}",
*lines]; return lines`)が、ヘルパー自体を使わず15個の生成関数
(`_generate_multiple_assign`/`_generate_click`/`_generate_type_into`/
`_generate_database_connect`等)に個別にインライン複製されていたこと
も発見した——全15箇所を共有ヘルパーの呼び出しへ統合し、修正を1箇所に
まとめた(知見133の`_apply_chained_call`統合と同種の「バグ修正と重複
排除を同時に行う」パターン)。

`dump_daemon/uipath_codegen/__init__.py`の`_todo_value`・
`_describe_expr_for_comment`・`_with_scope_child_display_name`を修正、
15箇所のインライン重複を`_with_scope_child_display_name`呼び出しへ
統合。`tests/test_uipath_codegen.py`に2件追加、UiPath関連テスト
全538件通過、リポジトリ全体で全1469件通過。

## 142. `File.GetLastWriteTime`を新規実装、`DateTime`演算+`TimeSpan.Days`の連鎖は複数の未解決ギャップの組み合わせと判明し見送り(未使用の新規24リポジトリでの実機検証、`compile()`標準化を継続、VM不使用)

知見117〜141の手法を未使用の新規24リポジトリへ適用した。`compile()`
検証でも構文エラーは0件。

**解決: `File.GetLastWriteTime(path)`**(`CarmenTheodoraCraciun/
DailyMealWithGroceryList`の実機XAML`File.GetLastWriteTime(
"./recepies.json")`で発見、ファイル更新チェック用のキャッシュ鮮度
判定パターン)。1引数の確認済み形のみ、`datetime.datetime.
fromtimestamp(os.path.getmtime(path))`へ対応——.NETの`File.
GetLastWriteTime`・Pythonの`os.path.getmtime`はいずれもファイル
システムのローカル時刻を返す点で意味論が一致する。

**見送り(複数の未解決ギャップの組み合わせと判明)**: 同じ実機XAMLの
`If`条件`(Now - lastModifeRecepies).Days > 14`は、以下の3つの別々の
未解決ギャップが連鎖した複合ケースだと判明した——(1)VB.NETの
`Now`(`Microsoft.VisualBasic.DateAndTime.Now`の修飾無し短縮形、
`Imports Microsoft.VisualBasic`相当の暗黙インポート)が現在`Ident`の
素通し経路でそのまま`"Now"`という未定義識別子として出力されてしまう
(既存の既知の限界)、(2)`DateTime - DateTime`の減算が`TimeSpan`を
返すという.NET側の型推論を、本トランスパイラの二項演算子レンダリング
(`_render_bin_op`)は一切型情報を持たずに処理するため対応できない、
(3)その結果(`TimeSpan`)の`.Days`プロパティ(Pythonの`timedelta.
days`に対応するはず)——この3つが揃わないと意味のある変換にならない
ため、`File.GetLastWriteTime`のような単発の静的メソッドとは違う規模の
作業になる。今回は`.Days`単体をでっち上げで対応せず、3つ組の課題として
見送り記録する(将来`DateTime`演算を本格的に対応する際にまとめて
設計する価値がある)。

`dump_daemon/uipath_codegen/render.py`に`file.getlastwritetime`分岐を
追加。`dump_daemon/uipath_codegen/__init__.py`の`_collect_imports`に
`datetime`検出を追加。`tests/test_uipath_codegen.py`に1件追加、
UiPath関連テスト全539件通過、リポジトリ全体で全1470件通過。

## 143. `Convert.ToDateTime`の診断メッセージを改善(でっち上げず明示的な理由を表示)、`.Split(文字配列)(添字)`の多重未解決ギャップを確認(未使用の新規21リポジトリでの実機検証、知見142と同種の「複数ギャップの組み合わせ」の追加確認、VM不使用)

知見117〜142の手法を未使用の新規21リポジトリへ適用した。`compile()`
検証でも構文エラーは0件。

**改善: `Convert.ToDateTime`の診断メッセージ**(`KeerthikaBaskar/
220701126-RPA-LAB`の実機XAML`Convert.ToDateTime(str_Date).ToString`で
発見)。`Convert.ToDateTime(String)`は.NETの現在のカルチャの日付書式
規則に依存した解析(カルチャ非依存の固定書式は存在しない)で、実機の
`"08/26/2021"`がMM/dd/yyyyかdd/MM/yyyyかを静的解析だけから確定でき
ない——Pythonの`datetime.strptime`は明示的な書式文字列が必要なため、
推測せず`# TODO`へ倒す判断自体は正しい。しかし修正前は、`convert.
todatetime`がTier1確認済み静的メソッド一覧に無かったため知見127の
「素の変数への連鎖呼び出し」フォールバックへ誤って落ち、「`Convert`
という変数の`.ToDateTime`メソッド呼び出し」と誤認した分かりにくい
エラーメッセージ(`unsupported chained method call: .ToDateTime(...)`)
になっていた——`convert.todatetime`をTier1に明示的に追加し、カルチャ
依存のため推測しないという理由を明確に示す専用の`# TODO`メッセージへ
差し替えた(変換ロジックは追加していない、診断メッセージの品質のみの
改善)。

**確認(コード変更無し): `.Split(文字配列)(添字)`の多重未解決ギャップ**
(`MU-Neha/CS19P21-ARPA`の実機XAML`StrText.Split(Environment.NewLine.
ToCharArray)(0)`で発見)。知見142の`DateTime`演算+`.Days`と同種の、
複数の別々の未解決ギャップが連鎖した複合ケースと判明した——(1)
`Environment.NewLine`という静的プロパティ未対応(知見140の`Environment.
CurrentDirectory`と同種だが別の名前)、(2)`.ToCharArray`(文字配列への
変換、Pythonの`list(s)`に対応するはず)未対応、(3)`.Split(文字配列)`
という、既存の確認済み`Split(文字列, 区切り文字列)`(知見126)とは
異なるオーバーロード(配列中のいずれかの文字で分割、`str.split(sep)`
とは意味論が違う)未対応、(4)さらにその結果への`(0)`という追加の
呼び出し直後の添字アクセス——これは`uipath_expr`文法が全く構文解析
できない(`tree=None`)新しい構文領域(知見74の「関数呼び出し後に
さらに添字アクセスする」形、グラマー上`postfix`規則が二重の括弧呼び出し
を許していない)。4つが連鎖しているため、`File.GetLastWriteTime`の
ような単発の追加とは規模が違う——今回は見送り、将来まとめて設計する
価値がある複合ケースとして記録する。

`dump_daemon/uipath_codegen/render.py`に`convert.todatetime`分岐
(明示的な`# TODO`decline)を追加。`tests/test_uipath_codegen.py`に
1件追加、UiPath関連テスト全540件通過、リポジトリ全体で全1471件通過。

## 144. `.LastIndexOf`/`.Substring`/`Regex.Replace`を新規実装(未使用の新規23リポジトリでの実機検証、`compile()`標準化を継続、VM不使用)

知見117〜143の手法を未使用の新規23リポジトリへ適用した。`compile()`
検証でも構文エラーは0件。

**解決: `.LastIndexOf(value)`**(`IS300-G6/PwC-Onboarding`の実機XAML
`excelFilePath.LastIndexOf(".")`で発見、拡張子の位置を調べる定石
パターン)。Pythonの`str.rfind(value)`と同じ意味論——いずれも最後に
出現した位置を返し、見つからない場合は`-1`を返す(.NET/Python公式
ドキュメントで確認済み)。`_apply_chained_call`(知見133で確立した
共通ヘルパー)に追加。

**解決: `.Substring(startIndex)`/`.Substring(startIndex, length)`**
(同上の実機XAML`excelFilePath.Substring(0, excelFilePath.
LastIndexOf("."))`で発見、`.LastIndexOf`と組み合わせた拡張子除去の
定石パターン——両方を同時に解決する必要があった)。1引数形は
`s[startIndex:]`、2引数形は`s[startIndex:startIndex+length]`
(第2引数は「開始位置からの文字数」、終了位置そのものではない点に
注意、.NET公式ドキュメント確認済み)。既存の回帰テスト`test_assign_
chained_access_with_unsupported_member_falls_back_to_todo`が
`Substring`を「未確認メンバの例」として使っていたため、別の未確認
メンバ(`PadLeft`)へ差し替えた(知見で新しいメンバを確認するたびに
この種のテスト更新が必要になる、良い副産物——「確認済みの範囲が
広がっている」ことの直接的な証拠)。

**解決: `Regex.Replace(input, pattern, replacement)`**
(`vermilion9312/RegularExpression`の実機XAML`Regex.Replace(str,
pattern, "******")`で発見)。3引数の確認済み形のみ`re.sub(pattern,
replacement, input)`へ対応——.NETとPythonの引数の並び順が異なる点に
注意(.NET: `(input, pattern, replacement)`、Python: `(pattern, repl,
string)`)。既知の限界: 名前付きキャプチャグループの記法(.NET
`(?<name>...)`/Python`(?P<name>...)`)等、.NET固有の正規表現構文を
使う場合は食い違う可能性があるが、確認済みの基本構文(`\d{6}$`等)の
範囲でのみ対応する。

`dump_daemon/uipath_codegen/render.py`の`_apply_chained_call`に
`LastIndexOf`/`Substring`(1・2引数)分岐、`_render_func_call`に
`regex.replace`分岐を追加。`dump_daemon/uipath_codegen/__init__.py`の
`_collect_imports`に`re`検出を追加。`tests/test_uipath_codegen.py`に
4件追加(既存1件の差し替え含む)、UiPath関連テスト全544件通過、
リポジトリ全体で全1490件通過(`test_pad_codegen.py`の1件は並行作業中
の別セッションの未完了変更により別途失敗中——本変更とは無関係)。

## 145. 【重大バグ・第5の発生箇所】`x:Class="{x:Null}"`で関数名が構文的に無効になるバグを発見・修正(未使用の新規21リポジトリでの実機検証、`compile()`標準化が再び効果を出す、VM不使用)

知見117〜144の手法を未使用の新規21リポジトリへ適用する過程で、
`bacdillon/UiPath-Automation`の実機XAMLから生成したPythonコードが
`def {x:Null}(DB_Connection):`という、関数定義のシグネチャ自体が構文的
に無効なコードになることを発見した——`compile()`検証が知見136〜141に
続いて再び効果を出した5番目の発生箇所。

**根本原因**: ワークフローのルート`<Activity x:Class="...">`の
`x:Class`属性値が、実機では`"{x:Null}"`(Studioでクラス名が未設定
または削除された状態のワークフローと見られる)になっていた。
知見13で確立した規約——`{x:Null}`という属性値は一般に「未設定」として
`None`/空文字列へ正規化する——は`_parse_expr`を経由する全ての属性で
一貫して適用されていたが、`x:Class`はクラス名が常に実在の文字列である
という前提のため`_attr()`で直接読まれ`_parse_expr`を経由しない唯一の
例外だった——この規約の抜け漏れにより、`class_name`にリテラル文字列
`"{x:Null}"`がそのまま残っていた。`uipath_codegen`側の`_safe_func_name`
には既に「`class_name`が空文字列なら既定名`workflow`」という安全網が
あったが、`class_name`は空文字列ではなく非空の`"{x:Null}"`という
文字列だったため、この安全網は機能せず素通りしていた。

**修正**: `parse_workflow_file`で`class_name`を抽出した直後に、
`"{x:Null}"`の場合は空文字列へ正規化するガードを追加した——これにより
既存の`_safe_func_name`の安全網が正しく働き、`def workflow(...):`へ
倒れる。

`dump_daemon/uipath_dsl/xaml_tree.py`の`parse_workflow_file`のみ変更。
`tests/test_uipath_dsl.py`に1件・`tests/test_uipath_codegen.py`に1件
追加、UiPath関連テスト全546件通過、リポジトリ全体で全1497件通過。

## 146. 【重要な体系的発見】チェーンメンバアクセスが大文字小文字を区別していたバグを発見・修正(VB.NETは大文字小文字不区別の言語)、`.StartsWith`/`.EndsWith`/`.IndexOf`/`.Replace`/`String.Concat`を新規実装(未使用の新規14リポジトリでの実機検証、VM不使用)

知見117〜145の手法を未使用の新規14リポジトリへ適用する過程で、
`johnowino/String-Manipulation-in-UIPath`という.NET文字列操作の基本
メソッドを一通りデモする実機XAML(`[strInput.length]`という**小文字**
の`.length`表記)から、既存実装の体系的な欠陥を発見した。

**根本原因**: VB.NETは識別子の大文字小文字を区別しない言語——
`.Length`/`.length`/`.LENGTH`はいずれも同じメンバを指す。`_render_
func_call`の静的メソッド名判定(`key = node.name.lower()`)は既に
この方針で実装済みだったが、チェーンメンバアクセス側(`_apply_
chained_property`/`_apply_chained_call`/`_render_node`のIdent分岐、
知見118・119・127で確立した3つの経路)は大文字小文字を区別する
比較のまま取り残されていた——`[strInput.length]`という小文字表記の
実例により、既に確認済みの`Length`メンバすら認識できず`# TODO`へ
倒れてしまっていた(新しいメンバの未対応ではなく、既存の確認済み
メンバの**取り逃し**という、知見136〜145とは異なる種類の「正しく
動くはずの機能が動かない」バグ)。

**修正**: `_CHAINED_PROPERTY_TRANSLATIONS`/`_SAFE_BARE_MEMBERS`の
キー・値を小文字へ統一し、3つの呼び出し経路全てで比較直前に
`.lower()`する——出力には元の大文字小文字を使わないため(`len()`/
`.upper()`等の変換先は入力の表記と無関係)、安全に正規化できる。

**同じ実機XAMLで追加発見・新規実装**:
- `.StartsWith(value)`/`.EndsWith(value)`→Pythonの`str.startswith`/
  `str.endswith`に直接対応(.NET公式ドキュメント確認済み)。
- `.IndexOf(value)`→`str.find(value)`(知見144の`.LastIndexOf`→
  `rfind`と対になる、最初の出現位置、見つからなければ`-1`)。
- `.Replace(oldValue, newValue)`→`str.replace(old, new)`(単純な
  部分文字列の全置換、正規表現ではない——`Regex.Replace`は知見144で
  別途対応済み)。
- `String.Concat(a, b, c, ...)`→VBの`&`演算子(知見46の`_vb_cstr`)と
  同じ`ToString`変換規則で連結(各引数を暗黙的に文字列化してから
  連結する.NETの仕様に合わせる)。

`dump_daemon/uipath_codegen/render.py`の`_CHAINED_PROPERTY_
TRANSLATIONS`/`_SAFE_BARE_MEMBERS`を小文字化、`_apply_chained_
property`/`_apply_chained_call`/`_render_node`のIdent分岐に
`.lower()`比較を追加、`_apply_chained_call`に`StartsWith`/
`EndsWith`/`IndexOf`/`Replace`分岐、`_render_func_call`に
`string.concat`分岐を追加。`tests/test_uipath_codegen.py`に9件
追加、UiPath関連テスト全554件通過、リポジトリ全体で全1506件通過。

## 147. 【見落とし発見】`WriteLine`(.NET Workflow Foundation本体の基本活動)が完全に未実装だったことを発見・実装(未使用の新規18リポジトリでの実機検証、VM不使用)

知見117〜146の手法を未使用の新規18リポジトリへ適用する過程で、
`WriteLine`(`http://schemas.microsoft.com/netfx/2009/xaml/activities`
——`WF_NS`、UiPath独自の活動ではなく.NET Workflow Foundation本体の
標準活動)が`uipath_dsl`/`uipath_codegen`のどこにも実装されていない
ことに気づいた——この実機検証を通じて「unknown activity (Write
Line)」という`# TODO`コメントが非常に高頻度(本セッションの複数の
batchで繰り返し)で出現していたにも関わらず、個々のbatchでは「この
活動は未実装」という個別の事実としてしか認識しておらず、「これほど
基本的な活動が丸ごと欠けている」という体系的な見落としとして気づく
のに時間がかかっていた——知見184(PAD側の`Display.ShowMessageDialog`
未結線の発見、別セッションの知見)と同種の「基本的すぎて見落とされて
いた機能」というパターン。

**実装**: `WriteLine`は`Console.WriteLine`相当で、Pythonの`print()`
と直接対応する——`MessageBox`(知見79)と違い対話的なブロッキングや
ユーザーの選択を伴わない単純なテキスト出力のため、でっち上げの懸念が
無い直接対応。`Text`属性は動的な式(VBの`&`連結式含む)が確認済みの
ため`Expr`として扱い、`_vb_cstr()`(知見46)経由で文字列化してから
`print()`に渡す——`_vb_cstr`を使う理由はVBの`&`演算子と同じ変換規則に
揃えるため(非文字列値を渡された場合の見た目の一致)。

**効果の大きさ**: 実装後、同じ新規18リポジトリの再検証で複数ファイルの
`# TODO`件数が大幅に減少した(例:`RealBenTen10/Handle-Order`は10件→
4件、他の数ファイルは`WriteLine`のみが残っていた`# TODO`だったため
0件に)——他の個別の静的メソッド追加1つあたりの効果より明らかに大きい、
基本活動の見落としを埋めることの価値を実証した。

**新たに発見した未解決事項(コード変更無し)**: `new DriveInfo(“C”)`
(`saurabhshaan/Disk-Monitoring-and-Clean-Up-Robot`)は(1)VB.NETの
一般的なオブジェクト構築構文`New ClassName(args)`(知見125の配列専用
構文とは別の、まだ未対応の構文領域)、(2)引用符がタイプライター風の
曲線引用符(`“”`、直線の`"`ではない)という、元のソースデータ自体が
破損している(実際の.NETコンパイラでもこのままではコンパイルエラーに
なるはず)という2つの問題が重なったケース——本トランスパイラの責任
範囲外の破損データとして見送る。

`dump_daemon/uipath_dsl/types.py`に`WriteLineNode`、`xaml_tree.py`に
`_parse_write_line`+`(WF_NS, "WriteLine")`の`_DISPATCH`登録、
`uipath_codegen/__init__.py`に`_generate_write_line`/`_generate_
write_line_body`を追加。`tests/test_uipath_dsl.py`に1件・`tests/
test_uipath_codegen.py`に3件追加、UiPath関連テスト全558件通過、
リポジトリ全体で全1524件通過。

## 148. `Throw`(.NET Workflow Foundation本体の基本活動)を新規実装、VB.NETの一般的なオブジェクト構築構文`New ClassName(arg)`を新規対応(知見147の直後に見つけた関連する見落とし、VM不使用)

知見147で`WriteLine`の見落としを発見・実装した直後、同じ.NET Workflow
Foundation本体の基本活動である`Throw`(`System.Activities.Statements.
Throw`、例外を明示的に発生させる活動)も同様に未実装だったことに気づき
(`Manyakarthik/210701152-CS19P21-ARPA`の実機XAML`Throw/4-Exception`で
確認)、合わせて実装した。

**新しい構文領域: `New ClassName(arg)`**。`Throw.Exception`属性の実機
値は`[New Exception("First number or Second number is zero")]`——
知見122で発見し知見125で`New Integer() {...}`(配列構築)のみ解決して
いた「VB.NETの`New`構文」のうち、より一般的な**オブジェクト構築**の
形がここで初めて実機確認された。`uipath_expr`文法に`_NEW IDENT "("
expr ("," expr)* ")" -> new_object`という新しい規則を追加——知見125の
配列構築規則(`_NEW IDENT "(" ")" "{" arglist "}"`、括弧は必ず空)とは
「括弧が空かどうか」で構文上一意に分岐するため、最低1個の引数を要求
する設計で曖昧性を回避した(実機確認済みの範囲でも常に1個以上の引数を
持つため実害は無い)。新しいASTノード`NewObject(class_name, args)`を
`uipath_expr`に追加。

**コード生成側の確認済み許可リスト**: `render.py`に`_NEW_OBJECT_
CLASSES`(`exception`/`applicationexception`、完全修飾名含む)を新設
——いずれも「1引数=メッセージ文字列」というPython組込み`Exception`と
同じコンストラクタ形を持つため`Exception(message)`へ直接対応する。
未確認のクラス名(カスタム例外型等)は意味論を推測できないため
`NotImplementedError`で明示的に declineする——でっち上げた任意クラスの
変換はしない。

**`Throw`活動自体の実装**: `Exception`属性を`Expr`として保持し、
レンダリングに成功した場合のみ`raise {expr}`文を生成する。知見136・
137で確立した「代入先が不明な文は全体を# TODOへ倒す」という方針と
同じ理由で、`_render_value_or_todo`(失敗時に例外無く`"None"`を返す)
は使わない——`raise None`は構文的には有効だが実行時に`TypeError`に
なるため、レンダリング失敗時は`raise`文自体を生成せず`# TODO`へ倒す
(既知の限界: 本来即座に停止するはずの制御フローが、生成コードでは
継続してしまう——架空の例外をでっち上げるよりは安全と判断した)。

`dump_daemon/uipath_expr/__init__.py`に`NewObject`+`new_object`文法
規則+transformer。`dump_daemon/uipath_codegen/render.py`に`_render_
new_object`+`_NEW_OBJECT_CLASSES`。`dump_daemon/uipath_dsl/types.py`
に`ThrowNode`、`xaml_tree.py`に`_parse_throw`+`(WF_NS, "Throw")`の
`_DISPATCH`登録、`uipath_codegen/__init__.py`に`_generate_throw`/
`_generate_throw_body`を追加。`tests/test_uipath_expr.py`に3件・
`tests/test_uipath_dsl.py`に1件・`tests/test_uipath_codegen.py`に4件
追加、UiPath関連テスト全566件通過、リポジトリ全体で全1544件通過。

## 149. `Rethrow`(`Throw`と対になる.NET Workflow Foundation本体の基本活動)を新規実装(知見148の直後に確認した体系的棚卸し、VM不使用)

知見148で`Throw`を実装した直後、その対になる`Rethrow`
(`System.Activities.Statements.Rethrow`——`Catch`ブロック内で現在
捕捉中の例外を再発生させる、属性を一切持たないリーフ活動)も同様に
未実装のままだったことに気づいた(知見147・148で見つけた「基本的な
.NET活動の見落とし」パターンの棚卸しを即座に行った結果)。

Pythonの`except`ブロック内の引数無し`raise`文(現在処理中の例外を
再発生させる)が全く同じ意味論で直接対応する——属性が無いため解析
対象のデータも無く、でっち上げの懸念も無い最も単純な変換の1つ。
`TryCatch`(知見11)の`Catch`ブロックで「ログだけ出して元の例外を
そのまま再発生させる」という定石パターンに非常に高頻度で使われる
はずの活動であるにも関わらず、今まで見落とされていた。

`dump_daemon/uipath_dsl/types.py`に`RethrowNode`(属性無しのリーフ)、
`xaml_tree.py`に`_parse_rethrow`+`(WF_NS, "Rethrow")`の`_DISPATCH`
登録、`uipath_codegen/__init__.py`に`_generate_rethrow`(`_with_scope_
child_display_name`経由で`raise`を1行生成)を追加。`tests/
test_uipath_dsl.py`に1件・`tests/test_uipath_codegen.py`に2件追加、
UiPath関連テスト全569件通過、リポジトリ全体で全1547件通過。

## 150. `TerminateWorkflow`(`Throw`・`Rethrow`と対になる.NET Workflow Foundation本体の標準活動)を新規実装(知見148・149に続く体系的棚卸し)

知見147(`WriteLine`)・148(`Throw`)・149(`Rethrow`)で「基本的な
.NET Workflow Foundation本体の活動の見落とし」という系統的な欠落が
判明したため、同じ`WF_NS`の標準活動群を棚卸しし、`TerminateWorkflow`
(`System.Activities.Statements.TerminateWorkflow`)も未実装のまま
残っていたことを発見した。GitHub code search(`"TerminateWorkflow"
extension:xaml uipath`)で1100件のヒットを確認——`While`/`DoWhile`
(知見14、`ui:InterruptibleWhile`/`ui:InterruptibleDoWhile`経由で
既に対応済み)と同じ優先度で実機確認に進んだ。

実機で3件(`Siva-PythonPirates/CS19P21-ARPA`の`TerminateWorkflow.xaml`、
`jyjang1222/learning-uipath`の`Main.xaml`、`andumorie/
uipath-face-recognition-framework`の`Identify.xaml`)をダウンロードし
構造を確認: 全件で`Reason`属性(VB式文字列)を持ち、1件(`jyjang1222`)
のみ追加で`Exception`属性(`[exception]`——`Catch`ブロック内の捕捉
済み例外変数)も同時に指定していた。`TerminateWorkflow`は`TryCatch`
で捕捉されない即座のワークフロー全体停止という意味論を持ち、Python
組込みの`SystemExit`(デフォルトでは`except Exception:`に捕捉されず
伝播する——`except:`のみが捕捉する)が最も近い確認済みの対応物。

`Reason`のみの場合は`raise SystemExit(_vb_cstr(reason))`へ変換する
(`WriteLine`の`Text`と同じ理由で`_vb_cstr`を通す——`Reason`がVB式の
結果非文字列になりうるケースに対応)。一方、`Exception`属性も同時に
指定されている場合は、両者がどう合成されるべきか(メッセージに例外
情報をどう埋め込むか)が実機未確認のため、知見148・149と同じ
「でっち上げるよりは安全」の方針で`# TODO`へ倒す——`Reason`文字列を
単純に流用して`Exception`情報を黙って捨てることも検討したが、確認
できていない情報の欠落を無言で許容するのは「でっち上げ」の裏返し
(過小な変換も一種のでっち上げ)と判断し、明示的な`# TODO`で欠落を
可視化する方を選んだ。

`dump_daemon/uipath_dsl/types.py`に`TerminateWorkflowNode(reason,
exception, display_name)`、`xaml_tree.py`に`_parse_terminate_workflow`
+`(WF_NS, "TerminateWorkflow")`の`_DISPATCH`登録、`uipath_codegen/
__init__.py`に`_generate_terminate_workflow`/`_generate_terminate_
workflow_body`(Reason未設定→TODO、Exception同時設定→TODO、それ
以外→`raise SystemExit(...)`)を追加。ダウンロード済みの3件の実機
XAMLで`generate_python()`+`compile()`を実行し、`Reason`単独の2件は
`raise SystemExit(...)`を正しく生成(1件は内部で未確認の`New
BusinessRuleException(...)`も検出し、知見148の方針通り別途`# TODO`
へ倒した)、`Exception`併用の1件は意図通り`# TODO`のみで`SystemExit`
を生成しないことを確認。回帰テスト追加(`tests/test_uipath_dsl.py`
1件・`tests/test_uipath_codegen.py`4件)、UiPath関連テスト全574件
通過、リポジトリ全体で全1567件通過。

## 151. `ui:Delay`(UiPath独自の最頻出活動の1つ)が完全に未実装だったことを発見・実装(GitHub code searchで10000件超ヒット)

知見147〜150で「.NET Workflow Foundation本体の基本活動の見落とし」
という系統的な欠落パターンを見つけたのに続いて、同じ観点でUiPath
独自活動側も棚卸ししたところ、`ui:Delay`(指定時間だけ待機する、
RPAワークフローでは非常に高頻度に使われる最も基本的な活動の1つ)が
完全に未実装のまま残っていたことを発見した。GitHub code search
(`"ui:Delay Duration=" extension:xaml`)で確認すると、`"Delay"
extension:xaml uipath`全体では10192件・`ui:Delay`に限定しても
数千件規模のヒットがあり、`While`/`DoWhile`(知見14)と同程度か
それ以上の最頻出活動であるにも関わらず、今まで一度も実装されて
いなかった。

実機で3件(`AI-Dep/AI-Antigravity`の`FA_CS_Asset_Entry.xaml`、
`UiPath/skills`公式リポジトリの`PerfBot/Main.xaml`・
`mail-delete-outlook-mail-stale-reference/process/Main.xaml`)を
ダウンロードして`Duration`属性の形式を確認したところ、全件で
`[...]`角括弧の無い生の.NET TimeSpan書式リテラル(`"00:00:01"`・
`"00:00:00.500"`・`"00:00:30"`・`"00:00:00.5000000"`)だった——
`Click`の`DelayBefore`(知見106、ミリ秒単位の数値)とは異なる書式
であることを確認(両者を混同しないよう別のパース関数とした)。
GitHub code search(`"ui:Delay" "TimeSpan" extension:xaml`)では
動的なTimeSpan式(`[TimeSpan.FromSeconds(...)]`等)の実例は見つから
なかった——Studioの`Delay`活動プロパティパネルが`Duration`を固定値
ピッカーとして提示する(VB式入力欄ではない)実装上の性質と整合する。

Pythonの`time.sleep(秒数)`が直接対応する——ブロッキングやユーザーの
選択を伴わない単純な待機のため「でっち上げ」の懸念が無い。
`Duration`が`Literal`(生のTimeSpanリテラル)の場合のみ、専用の正規表現
(`^(\d+):(\d{2}):(\d{2}(?:\.\d+)?)$`、実機確認した`HH:MM:SS[.fff]`
書式のみ)で秒数へ変換する。`Duration`が`VbExpr`(角括弧付きの動的式)
の場合、または正規表現にマッチしない未確認の書式(日数プレフィックス
付き等)の場合は、知見148〜150と同じ「でっち上げるよりは安全」の
方針で`# TODO`へ倒す。

`dump_daemon/uipath_dsl/types.py`に`DelayNode(duration, display_name)`、
`xaml_tree.py`に`_parse_delay`+`(UI_NS, "Delay")`の`_DISPATCH`登録、
`uipath_codegen/__init__.py`に`_parse_timespan_literal_seconds`
(正規表現ベースのTimeSpan→秒数変換)・`_generate_delay`/
`_generate_delay_body`を追加(`time`モジュールのimportは知見106の
`time.sleep(`検出条件を再利用、新規import検出コードは不要)。
ダウンロード済みの3件の実機XAMLで`generate_python()`+`compile()`を
実行し、直接到達可能な1件(`PerfBot/Main.xaml`)で`time.sleep(30.0)`
が正しく生成されることを確認——残り2件の`ui:Delay`呼び出しは、それ
ぞれ未実装の別活動(基本WF版`ForEach`・`ui:AttachWindow`)の子として
ネストされており到達不能だったため、今回のスコープ外の既存の別課題
として確認のみ行った(今回の実装自体には影響無し)。回帰テスト追加
(`tests/test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`6件、
リテラル秒数・小数秒・時分秒複合・DisplayName・Duration未設定・
動的式declin・未確認書式declineの6パターンを個別にテスト)、UiPath
関連テスト全582件通過、リポジトリ全体で全1586件通過。

## 152. `ui:SendHotkey`(GitHub code searchで1936件ヒットする基本UI Automation活動)を新規実装——`SpecialKey`属性が信頼できないという意外な発見付き

`Click`/`TypeInto`と同じ`UiPath.Core.Activities`の基本UI Automation
活動群のうち、キーボードショートカットを送信する`ui:SendHotkey`
(GitHub code searchで1936件ヒット)が未実装のまま残っていたことを
発見した。実機で11件(`PacktPublishing/Robotic-Process-Automation-*`
複数リポジトリ、`cameronmcnz/uipath-tutorials`、`HarshadRanganathan/
uipath-learning`、`AI-Dep/AI-Antigravity`、`KonduitAI/
objectrecognition-rpa`、`GSA/RPA-OSS`、`nkarkare/UDISEAutomation`、
`piyushagarwal08/JU-Notes`、`JoeIaquinto/UiPath-VidCreator`、
`whooaaapppp/VendorDetailPerformer`、`miyaichi/CertificationExam4`)の
`Key`/`KeyModifiers`/`SpecialKey`属性を調査した結果、意外な発見が
あった: `SpecialKey`属性は`"True"`/`"False"`/`{x:Null}`/属性自体が
省略、のいずれも実例があり(`cameronmcnz/uipath-tutorials`の
`ExtractPDFwithAnchors/Main.xaml`で`SpecialKey="{x:Null}"`かつ
`Key="5"`・`KeyModifiers="Ctrl, Shift"`、`AI-Dep/AI-Antigravity`の
`FA_CS_Asset_Entry.xaml`で`SpecialKey`属性自体が無く`Key="esc"`かつ
`Target`要素も省略、という実例を確認)、`Key`が特殊キー名かどうかの
判定に`SpecialKey`属性の値を信頼して使えるとは言い切れない。実際
`Key`の文字列値自体が1文字の生リテラルか、既知の特殊キー名
(`"enter"`/`"tab"`/`"esc"`/`"pgup"`/`"pgdn"`/`"home"`/`"end"`/
`"up"`/`"down"`/`"left"`/`"right"`/`"del"`/`"f1"`〜`"f24"`/
`"num0"`〜`"num9"`——いずれもGitHub code searchで個別に実例を確認
済み)のいずれかで一貫して判定できたため、本実装では`SpecialKey`
属性自体を一切参照せず`Key`の文字列値だけで判定する設計とした。

`KeyModifiers`は`.NET`の`[Flags]`列挙型のToString()直列化形式
(`", "`区切り、`cameronmcnz/uipath-tutorials`で`"Ctrl, Shift"`の
複数同時指定を確認)。`Ctrl`/`Alt`/`Shift`はpywinautoの`type_keys()`
ミニ言語の`^`/`%`/`+`接頭辞構文に直接対応するが、`Win`
(`KonduitAI/objectrecognition-rpa`の`KeyModifiers="Win"`、Win+Up/
Win+Leftのウィンドウ操作ショートカット)は同じ接頭辞構文に無く、
`{VK_LWIN down}`...`{VK_LWIN up}`で囲む別構文が必要(pywinauto公式
ドキュメント文字列で確認済みの構文)——`Win`単独の場合のみサポート
し、他のモディファイアとの併用は未確認のため`# TODO`へ倒す。

また`AI-Dep/AI-Antigravity`の実機XAMLで`<ui:SendHotkey Key="esc"
DisplayName="..." />`(`Target`要素自体が省略された自己終了タグ)も
発見した——`Click`/`TypeInto`とは違いTargetが無くても構文的に正当
という既存の想定(`Target`は必須)を崩す新しい発見。現在フォーカス
中のウィンドウへグローバルに送信する意味論と推定されるが、本実装
では対応せず`# TODO`へ倒す(でっち上げるよりは安全)。

`dump_daemon/uipath_dsl/types.py`に`SendHotkeyNode`(`Click`/
`TypeInto`と同じく`selector`/`key`/`key_modifiers`/`click_before_
typing`/`empty_field`/`send_window_messages`/`delay_before`/`delay_
between_keys`/`delay_ms`/`activate`を保持)、`xaml_tree.py`に
`_parse_send_hotkey`+`(UI_NS, "SendHotkey")`の`_DISPATCH`登録、
`uipath_codegen/__init__.py`に`_send_hotkey_key_token`(特殊キー名
テーブル+`f\d+`/`num\d`正規表現)・`_send_hotkey_wrap_with_modifiers`
(モディファイア→pywinauto接頭辞/Win専用ラップ変換)・
`_generate_send_hotkey`/`_generate_send_hotkey_body`(`TypeInto`と
同じ構造——`SendWindowMessages`/`ClickBeforeTyping`/`EmptyField`/
`DelayMS`/`DelayBetweenKeys`の非既定値は同じ理由で`# TODO`へ倒す)を
追加。ダウンロード済みの8件の実機XAMLで`generate_python()`+
`compile()`を実行し、直接到達可能な1件(`KonduitAI/
objectrecognition-rpa`の`ScoreImage.xaml`)で`Win+Up`/`Win+Left`の
両方が`{VK_LWIN down}{UP}{VK_LWIN up}`/`{VK_LWIN down}{LEFT}
{VK_LWIN up}`として正しく生成されることを確認——残り7件の
`ui:SendHotkey`呼び出しは、知見150・151と同じパターンで未実装の
別活動(`ui:OpenApplication`、UiPathのアプリ起動スコープ活動)の子
としてネストされており到達不能だった(今回のスコープ外、ただし
`ui:AttachWindow`(知見151で遭遇)・`ui:OpenApplication`(今回
遭遇)という「子を持つスコープ活動が軒並み未実装」というパターンが
3回連続で確認できたため、次の棚卸し候補として記録しておく)。回帰
テスト追加(`tests/test_uipath_dsl.py`2件・`tests/
test_uipath_codegen.py`19件、確認済み特殊キー名・Win単独・複数
モディファイア併用・DisplayName・Target省略・未確認Key・Win併用
declin・DelayBefore・DelayMS declineの各パターンを個別にテスト)、
UiPath関連テスト全603件通過、リポジトリ全体で全1619件通過。

## 153. `ui:AttachWindow`(子を持つスコープ活動の棚卸し第1弾)を透過的ラッパーとして新規実装——`AttachWindow`に閉じ込められていた`ui:Delay`(知見151)も連動して到達可能になった

知見151・152で「子を持つスコープ活動が軒並み未実装」というパターンに
3回連続で遭遇し(`ui:AttachWindow`・`ui:OpenApplication`・基本WF版
`ForEach`)、次の棚卸し候補として記録したうちの第1弾として
`ui:AttachWindow`(GitHub code searchで1100件ヒット)を実装した。

実機(`AI-Dep/AI-Antigravity`の`FA_CS_Asset_Entry.xaml`)で構造を
再確認したところ、`ExcelApplicationScope`/`WordApplicationScope`
(知見22・121)とは違い`ActivityAction`+`DelegateInArgument`のラッパー
を持たず、`<ui:AttachWindow.Body><Sequence>...</Sequence></ui:
AttachWindow.Body>`という単純な形だった——`ForEach.Body`/
`While.Body`と同じ「常に`Sequence`でラップされる」パターン
(`_unwrap_body_sequence`、知見22で確立)がそのまま使えた。

既に確認済みの通り、`Click`/`TypeInto`/`SendHotkey`(知見9・110・152)
は全て`selector`を自己完結的に(絶対パスで)保持する設計のため、
`AttachWindow`が解決したウィンドウハンドルへの相対参照に子が依存する
構造には**なっていない**。よって`AttachWindow`自体は`scope_var`束縛を
一切作らず、「`Selector`を注釈コメントとして出力し子をそのまま
`_generate_body`で再帰生成する透過的なラッパー」として実装した——
当初の見立て(知見151・152の今後の調査候補)通りの結果になった。

実装にあたり、`_child_node_lists`(知見88が警告する「複数ファイル
結線用の子ノードリスト走査」専用の別registry)への登録漏れに注意
した——`ExcelApplicationScopeNode`/`WordApplicationScopeNode`が
過去に実際にこの登録漏れで`InvokeWorkflowFile`参照を見失う退行を
起こした実例(知見88)があったため、`AttachWindowNode`も同じ場所へ
`[node.body]`として登録した。

実機XAML(`FA_CS_Asset_Entry.xaml`)で再検証したところ、今回の実装
によって知見151で「`ui:AttachWindow`の子としてネストされており
到達不能」と記録していた`ui:Delay`呼び出し3件が、連動して正しく
`time.sleep(0.5)`/`time.sleep(1.0)`×2として生成されることを確認
した——スコープ活動を1つ実装するだけで、以前の知見で「スコープ外」
として保留していた子の実装が自動的に活きる好例。同ファイル内の
別の未対応箇所(`Click`の`Selector`欠落・基本WF版`ForEach`・
`InputDialog`の出力未設定・`MessageBox`のボタン選択再現不可)は
`AttachWindow`とは無関係な既存の個別課題のまま健全に`# TODO`へ倒れ
続けることも確認した(透過的ラッパーが既存の`# TODO`を隠してしまわ
ないことの確認、知見84の教訓と同じ検証パターン)。

`dump_daemon/uipath_dsl/types.py`に`AttachWindowNode(selector, body,
display_name)`、`xaml_tree.py`に`_parse_attach_window`
(`_unwrap_body_sequence`を再利用)+`(UI_NS, "AttachWindow")`の
`_DISPATCH`登録、`uipath_codegen/__init__.py`に
`_generate_attach_window`(`_generate_body`で子を再帰生成、
`_ensure_nonempty_suite`で空本体に`pass`を補う)を追加し、
`_child_node_lists`にも登録。回帰テスト追加(`tests/
test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`5件、
Selector注釈コメント・DisplayName・Selector未設定・空本体・子の
`# TODO`透過の各パターンを個別にテスト)、UiPath関連テスト全609件
通過、リポジトリ全体で全1635件通過。

## 154. `ui:OpenApplication`(スコープ活動の棚卸し第2弾)を実装——`AttachWindow`とは異なり実際にプロセスを起動するコードを生成

知見153の`ui:AttachWindow`に続き、「子を持つスコープ活動が軒並み
未実装」というパターン(知見151・152で発見)の第2弾として
`ui:OpenApplication`(`UiPath.Core.Activities`)を実装した。

実機構造を確認したところ、`AttachWindow`とは違い`ExcelApplication
Scope`(知見22)と同じ`ActivityAction`+`DelegateInArgument`のラッパー
を持つ(`PacktPublishing/Robotic-Process-Automation-RPA-for-Developers`
の`KeyboardActions.xaml`で確認: `DelegateInArgument.Name`は
`"ContextTarget"`固定)。ただし子活動(`TypeInto`/`SendHotkey`)は
実機で`ContextTarget`を一切参照しておらず、`AttachWindow`と同じ
「子は絶対セレクタを自己完結的に保持する」設計が当てはまるため、
本実装でも`ContextTarget`は束縛しない。

`AttachWindow`との決定的な違いは、`AttachWindow`が既存のウィンドウに
「接続する」だけなのに対し、`OpenApplication`は実際に新しいプロセスを
「起動する」活動である点——よって`AttachWindow`の「注釈コメント+
透過的再帰」だけでは不十分で、`subprocess.Popen([file_name])`という
実行可能なコードを追加生成する。

実機5件(`piyushagarwal08/JU-Notes`・`spritlesoftware/
Uipath-RPA-AutomationProjects`・`masatomix/My_Attended_Framework`・
`allenlooplee/RPABook`・`JoeIaquinto/UiPath-VidCreator`)を調査した
結果、`FileName`は生リテラル(`"C:\Windows\System32\notepad.exe"`)と
動的VB式(`"[in_Config(\"UiDemoPath\").ToString]"`)の両方を確認した
一方、`Arguments`(`"[in_TestLogFile]"`、`allenlooplee/RPABook`)・
`ApplicationWindow`(開いたウィンドウ参照を受け取る出力バインディング、
`"[OBSWindow]"`、`JoeIaquinto/UiPath-VidCreator`)・`WorkingDirectory`・
`TimeoutMS`(`"2000"`)・`ContinueOnError`(`"True"`)も非`{x:Null}`の
実例を確認した——いずれも正確な意味論(Windowsコマンドライン引数の
分割規則・UiElement出力変数の表現・「ウィンドウが現れるまで待つ」
ポーリング挙動)が未確認のため、知見148以来の「でっち上げるよりは
安全」の方針でこれらが設定されている場合は個別に`# TODO`へ倒す。

`dump_daemon/uipath_dsl/types.py`に`OpenApplicationNode(file_name,
selector, arguments, working_directory, application_window,
timeout_ms, continue_on_error, body, display_name)`、`xaml_tree.py`に
`_parse_open_application`(`_find_activity_action`+`_unwrap_body_
sequence`、`ExcelApplicationScope`と同じ抽出方法)+`(UI_NS,
"OpenApplication")`の`_DISPATCH`登録、`uipath_codegen/__init__.py`に
`_generate_open_application`/`_generate_open_application_body`
(`FileName`のみ確認済みの単純な場合だけ`subprocess.Popen([...])`を
生成、`Selector`は注釈コメント、子は`_generate_body`で再帰生成)を
追加し、`_child_node_lists`(知見88が警告する複数ファイル結線用の
別registry)にも`AttachWindowNode`と一緒にタプルで登録。`subprocess`
の`import`検出条件を`_collect_imports`に追加。

実機XAML(`KeyboardActions.xaml`)で再検証したところ、以前は
「unknown activity (Open Application)」の`# TODO`1つに潰れていた
箇所が、`subprocess.Popen(['C:\\Windows\\System32\\notepad.exe'])`→
`# Attach window: ...`→(子の)`TypeInto`の`type_keys()`呼び出し→
`SendHotkey`の`type_keys('^s')`呼び出し、という一連の実行可能な
コードとして正しく連鎖生成されることを確認した——知見151(`Delay`)・
152(`SendHotkey`)・153(`AttachWindow`)の実装がこの1件で初めて
真に連動して活きた格好になる。回帰テスト追加(`tests/
test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`9件、
FileName動的式・Arguments/WorkingDirectory/ApplicationWindow/
TimeoutMS/ContinueOnError各declineパターン・DisplayName・子TODO
透過を個別にテスト)、UiPath関連テスト全620件通過、リポジトリ全体で
全1648件通過。

## 155. 基本WF版`ForEach<T>`(`ui:ForEach`とは別の`WF_NS`のForEach)を新規実装——1件の実機XAMLが非標準(AI生成合成コードの疑い)だったため実装の根拠から除外した判断含む

知見151で発見した「子を持つスコープ活動が軒並み未実装」というパターン
の最後の1件、基本WF版`System.Activities.Statements.ForEach<T>`
(`ui:`プレフィックス無し、`WF_NS`)を実装した。

当初、知見151で発見した`AI-Dep/AI-Antigravity`の実機XAML
(`FA_CS_Asset_Entry.xaml`)を構造調査の出発点にしたところ、`<ForEach
x:TypeArguments="ui:DataRow" Values="[AssetData.Rows]"
CurrentItem="[CurrentRow]">`という、`CurrentItem`を直接属性として
持ち`ActivityAction`/`DelegateInArgument`を一切使わない形だった——
しかし.NET公式の`ForEach<T>`APIには`CurrentItem`というプロパティ自体
が存在しない(`Body: ActivityAction<T>`と`Values`のみ)ため、この
直接属性形は本来の`ForEach<T>`の実際のシリアライズ形式と矛盾する。
Microsoft公式サンプル(`dotnet/samples`の`GetEmployeesByPositionTypes.
xaml`)とTFS標準ビルドテンプレート(`microsoft/sql-server-samples`の
`DefaultTemplate.xaml`)で本来の`ActivityAction`+`DelegateInArgument`
形を確認し、さらに実際のUiPathプロジェクト5件(`plaah/
web-application-with-rpa-dhl`・`R1zzabh/signalforge`・
`rufoabrahamguyo/sow-calix`・`NihadVeliyev/Student-Placement-
Eligibility-Automation-using-UiPath-and-Excel`・`EnnioArnold/
Dispatcher-Framework`)で「UiPathプログラマがVB式ベースのループ
(`Directory.GetFiles(...)`/`JArray.Parse(...)`/`.AsEnumerable()`等)を
`ui:ForEach`ではなく基本WF版`ForEach<T>`で直接書く」という実在する
パターンを確認した。`AI-Dep/AI-Antigravity`というリポジトリ名自体が
AI生成コードを強く示唆しており、.NET APIと矛盾する非標準の直接属性形
は「でっち上げるよりは安全」の方針に照らして実装の根拠から除外し、
Microsoft公式+複数の独立した実UiPathプロジェクトで確認した本来の
`ActivityAction`形のみを採用した——「実機確認済み」の基準として、
出典の信頼性自体を検証する必要があるという教訓になった。

構造は`ui:ForEach`(知見5)と完全に同じ`ActivityAction`+
`DelegateInArgument`だが、`Body`がContent Property(XAMLで省略可能な
唯一のプロパティ)のため、`<ForEach.Body>`での明示ラップ
(`R1zzabh/signalforge`)と、`<ForEach>`直下に`ActivityAction`を直接
子として置く暗黙形(他4件、より高頻度)の両方が実在する。既存の
`ForEachNode`型・既存の`_generate_for_each`コード生成はそのまま
再利用できるため、新しいノード型やコード生成関数は追加せず、
`_parse_for_each`に「`.Body`が見つからなければ`elem`自身を対象に
`ActivityAction`を探す」フォールバックを追加し、`_DISPATCH`に
`(WF_NS, "ForEach"): _parse_for_each`を追加登録するだけで済んだ。

実機XAML(`R1zzabh/signalforge`の`Main.xaml`)で再検証し、
`for incidentId in incidentIds:`が正しく生成されることを確認した。
一方、`plaah/web-application-with-rpa-dhl`の`Main.xaml`は`Values`に
未確認の関数呼び出し(`config(...)`)を含んでおり、`generate_python()`
全体が`NotImplementedError`で停止する(`# TODO`への安全なフォール
バックではなく例外伝播)ことを確認した——これは本実装が原因ではなく、
`_generate_for_each`が`If.Condition`/`While.Condition`/`Switch.
Expression`と同じ「条件式の変換失敗はコード生成自体を失敗させる」
方針(モジュールdocstring)を`ForEach.Values`にも(ドキュメントには
明記されていないが)既に適用していたという既存の挙動——`ui:ForEach`
でも同じ条件で同じく例外伝播していたはずだが、これまでの実機検証で
たまたま踏まれていなかった。`ForEach.Values`を「条件」と同じ厳格な
失敗モードにすべきか「値」と同じ`# TODO`緩和モードにすべきかは
ドキュメント上未確定の設計判断のため、本tickでは変更せず次の調査
候補として記録する(今回のスコープ=`WF_NS`ディスパッチ追加、とは
別の既存の論点)。

`dump_daemon/uipath_dsl/types.py`の`ForEachNode`docstringに知見155
を追記(新しいフィールドやノード型は追加していない)、`xaml_tree.py`
の`_parse_for_each`に`body_elem`フォールバック追加+`(WF_NS,
"ForEach")`の`_DISPATCH`登録。回帰テスト追加(`tests/
test_uipath_dsl.py`2件、暗黙形・明示`.Body`ラップ形を個別にテスト)、
UiPath関連テスト全622件通過、リポジトリ全体で全1656件通過。

## 156. `ForEach.Values`の失敗モード方針を確定(知見155が残した論点の解決、動作変更無し)

知見155で記録した「`ForEach.Values`の変換失敗時に`If.Condition`/
`While.Condition`/`Switch.Expression`と同じ厳格な例外伝播モードが
(ドキュメント化されないまま)既に実装されていたが、意図的な設計か
見落としか未確定」という論点を再検討し、方針を確定した。

`pad_codegen`の`IfActionRecord`処理の判断根拠(「値の誤りは局所的だが、
条件の誤りは分岐全体を反転させうるため」)を再確認した結果、
`ForEach.Values`も同じ理屈が当てはまる、むしろそれ以上の影響範囲を
持つと判断した: 反復対象を誤って推測すると、ループの**全ての**
反復が間違ったデータに対して実行されてしまう——これは「分岐が
反転する」のと同種か、それより広い影響範囲(1回のif分岐 vs N回の
繰り返し全て)であり、`Assign`の右辺1箇所限定の誤りとは明確に性質が
異なる。よって既存の実装(厳格モード、変更無し)が妥当という結論に
達し、モジュールdocstring(`dump_daemon/uipath_codegen/__init__.py`
冒頭)の「条件式は値とは異なる失敗モードを採用する」の列挙に
`ForEach.Values`(および同じ理由で既に厳格モードだった`DoWhile.
Condition`、こちらも列挙漏れだった)を正式に追記し、`_generate_
for_each`自体にも`_generate_if`と同水準の説明コメントを追加した。

実装上の変更は無く、ドキュメントと既存コードの整合性を取っただけ——
ただし「このモジュールのコードが実際にどう振る舞うか」を正確に反映
したドキュメントが無い状態は、将来の実装者が誤って挙動を変えてしまう
リスクがあったため、知見155で発見した実機XAMLの再現経路
(`config(...)`という未確認関数呼び出しが`Values`に含まれる場合)を
回帰テストとして`tests/test_uipath_codegen.py`に追加し
(`test_for_each_with_unparseable_values_raises`、`test_if_with_
unparseable_condition_raises`と同じ形)、この方針が将来のリファクタ
で意図せず壊れないよう固定した。UiPath関連テスト全623件通過、
リポジトリ全体で全1657件通過。

## 157. `ui:Hover`(GitHub code searchで151件ヒットする基本UI Automation活動)を新規実装——pywinautoの`move_mouse_input()`ラッパー自身の既定値が「要素の中心」にならない罠を発見

`Click`/`TypeInto`/`SendHotkey`と同じ`UiPath.Core.Activities`の基本
UI Automation活動のうち、`ui:Hover`(マウスを要素に乗せるだけで
クリックしない活動、GitHub code searchで151件ヒット)が未実装のまま
残っていたことを発見した。実機(`sujan5757/RPAWorks`の
`Mouseactivity/Main.xaml`)で構造を確認したところ、`ClickNode`
(知見9)と`Target`/`CursorPosition`の構造が全く同じで、`ClickType`/
`MouseButton`/`KeyModifiers`(クリック自体に固有の属性)が無い点のみ
異なっていた——確認した`DelayBefore`/`DelayMS`/`SendWindowMessages`/
`SimulateHover`は全て`{x:Null}`(未設定)。

実装時にpywinautoのAPI調査で見落としやすい罠を発見した:
pywinautoには`move_mouse_input(coords=(0, 0), pressed="", absolute=
True)`という便利ラッパーが存在し、素朴には「`Click`の`click_input()`
に対応するHover用メソッド」として使いたくなるが、このラッパー自身の
既定値`coords=(0, 0)`・`absolute=True`は**要素の中心には移動しない**
——`click_input()`内部の座標解決ロジック(`.venv/lib/python3.12/
site-packages/pywinauto/base_wrapper.py`)を読むと、`coords[0]`が
`None`の場合のみ要素の幅/高さの半分(=中心)を計算し、かつ
`absolute=False`の場合のみその相対座標を`client_to_screen()`で
画面座標へ変換する——`move_mouse_input()`の既定`coords=(0, 0)`は
`None`ではないため中心計算が走らず、かつ`absolute=True`のため画面
座標変換も走らない。結果、素朴に`move_mouse_input()`を既定値のまま
呼ぶと画面の絶対座標`(0, 0)`(画面左上付近)へ移動してしまい、
`Click`の既定動作(要素の中心へのクリック)と整合しない。

この罠を回避するため、`move_mouse_input()`ラッパーを使わず
`click_input()`自身を`button='move'`で直接呼び出す実装にした——
`click_input()`自身の既定(`coords=(None, None)`・`absolute=False`)
が正しく「要素の中心を相対座標で計算し画面座標へ変換する」ため、
`Click`が`CursorPosition`省略時に`coords`引数を渡さずに依拠している
のと全く同じ経路を再利用できる(新たな前提を持ち込まない)。

`dump_daemon/uipath_dsl/types.py`に`HoverNode`(`ClickNode`から
`click_type`/`mouse_button`/`key_modifiers`を除き、`send_window_
messages`/`simulate_hover`を追加した構成)、`xaml_tree.py`に
`_parse_hover`(`_parse_click`と同じTarget/CursorPosition抽出)+
`(UI_NS, "Hover")`の`_DISPATCH`登録、`uipath_codegen/__init__.py`に
`_generate_hover`/`_generate_hover_body`(`_CURSOR_POSITION_CONFIRMED_
DEFAULTS`を`Click`と共有、`SendWindowMessages`/`SimulateHover`の
非既定値は`# TODO`へ倒す)を追加。実機XAML(`sujan5757/RPAWorks`)で
`generate_python()`+`compile()`を実行したが、同ファイルのセレクタが
Web系属性(`html`/`webctrl`の`id`/`aaname`)を使っており、これは
`Click`活動でも同じ理由で`# TODO`へ倒れる既知の制約(`selector_text_
to_pywinauto`が未対応の属性)だったため、成功パス自体は単体テスト
(`cls`/`name`属性を使う確認済みマッピング対象のセレクタ)で直接
確認した。回帰テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
test_uipath_codegen.py`10件)、UiPath関連テスト全634件通過、
リポジトリ全体で全1674件通過。

## 158. `ui:TypeSecureText`(既存の`TypeIntoNode`を再利用)と`ui:WindowScope`(`AttachWindow`より多い1688件ヒットの同義活動、既存の`AttachWindowNode`を再利用)を新規実装

同じtickで2つの「既存ノード型を再利用するだけで実装できる」高頻度
未実装活動を発見・実装した——いずれも新しいノード型を追加せず、
既存のパーサー/コード生成を再利用できた。

**`ui:TypeSecureText`**(GitHub code searchで544件ヒット): 実機
(`piyushagarwal08/JU-Notes`の`UiDemo_Login.xaml`)で構造を確認した
ところ、`ui:TypeInto`(知見110)と属性構成が完全に同じ
(`ClickBeforeTyping`/`DelayBefore`/`DelayBetweenKeys`/`DelayMS`/
`EmptyField`/`SendWindowMessages`/`SimulateType`/`Activate`)で、
唯一の違いは入力文字列を保持する属性名が`Text`ではなく`SecureText`
(本来`System.Security.SecureString`型だが、本トランスパイラは
どの変数もPythonの通常の識別子として扱うため.NET型の違いを意識する
必要が無い)。意味論・コード生成が完全に同じため、新しいノード型を
追加せず既存の`TypeIntoNode`を返す`_parse_type_secure_text`を追加
するだけで済んだ(`ui:ForEachRow`が`ForEachNode`を再利用するのと
同じ設計パターン)。

**`ui:WindowScope`**(GitHub code searchで1688件ヒット——`ui:
AttachWindow`の1100件より多い!): 同じ実機XAMLで`DisplayName`が
常に`"Attach Window '...'"`になる活動を発見し、`allenlooplee/
RPABook`・`HarshadRanganathan/uipath-learning`等9件以上の実機XAMLで
意味論(既存ウィンドウに接続して`Body`を実行、プロセス起動は行わ
ない)が`AttachWindow`(知見153)と同じであることを確認した——
おそらく異なるUI Automationパッケージバージョンでの名称違い。
構造は`AttachWindow`とは違い`OpenApplication`(知見154)と同じ
`ActivityAction`+`DelegateInArgument`(`Name`は`"ContextTarget"`)の
ラッパーを持つが、子は`ContextTarget`を参照しない設計のため同様に
束縛しない。`ApplicationWindow`/`SearchScope`/`TimeoutMS`/`Window`
という4つの追加属性を持つが、実機確認した9件以上全てで`{x:Null}`
だった——`AttachWindowNode`にこれら4つのフィールドを追加し、設定
されている場合は`OpenApplication`の`ApplicationWindow`等と同じ理由
(正確な意味論が未確認)で`# TODO`へ倒す。

実機XAML(`piyushagarwal08/JU-Notes`の`UiDemo_Login.xaml`、`ReFramework`
系のログインシーケンス)で`generate_python()`+`compile()`を実行し、
`WindowScope`が正しく`# Attach window: ...`+子の再帰生成に展開され、
`TypeSecureText`が`TypeInto`と全く同じ`type_keys(_pywinauto_type_
keys_escape(_vb_cstr(Password)))`を生成することを確認した——同じ
1ファイルで両方の新機能が連動して正しく動く実例になった(知見154が
`Delay`・`SendHotkey`・`AttachWindow`を連動させたのと同種のパターン)。

`dump_daemon/uipath_dsl/xaml_tree.py`に`_parse_type_secure_text`
(`TypeIntoNode`を返す)+`(UI_NS, "TypeSecureText")`、`_parse_window_
scope`(`AttachWindowNode`を返す)+`(UI_NS, "WindowScope")`の
`_DISPATCH`登録。`dump_daemon/uipath_dsl/types.py`の`AttachWindowNode`
に`application_window`/`search_scope`/`timeout_ms`/`window`の4
フィールドを追加、`uipath_codegen/__init__.py`の`_generate_attach_
window`を`_generate_attach_window_body`に分割し新規フィールドの
decline判定を追加(既存の`AttachWindow`自身はこれらを一切設定しない
ため挙動は変わらない)。回帰テスト追加(`tests/test_uipath_dsl.py`
2件・`tests/test_uipath_codegen.py`2件)、UiPath関連テスト全638件
通過、リポジトリ全体で全1678件通過。

## 159. `ui:GetFullText`(`GetText`とは別の活動、GitHub code searchで300件ヒット)を新規実装——既存の`GetTextNode`を再利用しつつ、意味論の違いを警告文言で区別する判断

`ui:GetText`(知見111)の兄弟活動である`ui:GetFullText`が未実装の
まま残っていたことを発見した。実機(`PacktPublishing/
Robotic-Process-Automation-RPA-for-Developers`の
`Scraping-UnStructured.xaml`、`SuneetPatil/IRCTC-tatkal-booking`の
`ReviewBookingPage.xaml`、`GSA/Credit_Card_Logging_Bot`の複数XAML)で
構造を確認した結果、`Target`は`GetText`と同じ構造だったが、出力
`Text`は属性形(`Text="[varName]"`)ではなくプロパティ要素形
(`<ui:GetFullText.Text><OutArgument>...</OutArgument></ui:
GetFullText.Text>`、知見115の`_in_argument_property_expr`で抽出)
だった——加えて`IgnoreHidden`(実機確認した全件で`"False"`)という
`GetText`には無い属性を持つ。`ContinueOnError`(実機で`"True"`の
実例も確認)は`GetText`と共通。

意味論上の判断が必要だった: 公式ドキュメントは`GetText`を「可視
テキストのみ・最大4096文字」、`GetFullText`を「非表示/切り詰められた
部分を含むフルテキスト」と明確に区別している——両者を同じ
`window_text()`(既にGetText自体が「正確な1対1対応の主張はしない」
という既存の警告付きの近似だった)へ変換すると、`GetFullText`側は
GetTextよりさらに弱い(より不確実な)近似になる。単純に`GetTextNode`
を再利用して同じ変換・同じ警告文言を出すのは、この意味論の違いを
隠してしまう恐れがあるため、`GetTextNode`に`full_text`(判別フラグ)
と`ignore_hidden`の2フィールドを追加し、`_generate_get_text_body`が
`full_text`の値に応じてラベル(`"Get Text"`/`"Get Full Text"`)と
警告文言(`GetFullText`の場合は「UiPathの実装より少ないテキストしか
返らない可能性がある」ことを明示)を切り替える設計にした——構造・
出力先の再利用はするが、確認済みの意味論の違いは隠さないという
折衷案。

`dump_daemon/uipath_dsl/types.py`の`GetTextNode`に`full_text: bool
= False`・`ignore_hidden: Expr = None`の2フィールドを追加、
`xaml_tree.py`に`_parse_get_full_text`(`_in_argument_property_expr`
でText抽出、`full_text=True`で返す)+`(UI_NS, "GetFullText")`の
`_DISPATCH`登録、`uipath_codegen/__init__.py`の`_generate_get_text_
body`を`full_text`分岐付きに拡張(既存の`GetText`呼び出しは
`full_text`が常に`False`のデフォルトのため挙動は変わらない——既存の
全テストが無変更で通過することを確認)。実機XAML(`PacktPublishing`の
`Scraping-UnStructured.xaml`)で`generate_python()`+`compile()`を
実行し、`Get Full Text`ラベル付きの`window_text()`呼び出しが正しく
生成されることを確認した——別の2件(`GSA/Credit_Card_Logging_Bot`)は
`ui:BrowserScope`(「Attach Browser」、`AttachWindow`/`WindowScope`
(知見153・158)と同種の未実装スコープ活動)の子としてネストされて
おり到達不能だったため、今回のスコープ外の既存の別課題として確認の
み行った(次の棚卸し候補として記録)。回帰テスト追加(`tests/
test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`3件)、UiPath
関連テスト全642件通過、リポジトリ全体で全1682件通過。

## 160. 知見130の【最優先・重大・未解決】識別子大文字小文字正規化を実装——`render.py`を一切変更せず、`parse_workflow_file`入口でのXML木前処理という軽量な解決策で対応

知見130で「次に『スコープ対応のコード生成アーキテクチャ』を設計する際は
最優先の要件として含めるべき」と記録し実装を見送っていた問題(VB.NETは
識別子の大文字小文字を区別しないが、本トランスパイラの`render_expr`/
`_render_node`は識別子参照をXAML中のテキストのまま文脈自由に素通りさせる
ため、ワークフロー引数/変数の宣言と参照で大文字小文字の表記が揺れると
意味的に誤った2つの別々のPython識別子を静かに生成してしまう)を、
当初想定していた「`render.py`に宣言済み名前の集合を渡す仕組みを新設する」
という大掛かりなアーキテクチャ変更ではなく、**`parse_workflow_file`の
入口でXML木そのものを正規化する軽量な前処理パス**として解決した。

設計の要点: (1) `_collect_declared_identifier_names`がワークフロー
全体を1回走査し、ワークフロー引数(`_find_members`)+(深さを問わない)
全ての`<Variable Name="...">`を小文字キーで収集し、宣言順で最初に見つ
かった表記を正規名として採用する。(2) `_normalize_identifier_case_in_
tree`がXML木をもう1回走査し、`[...]`で囲まれたVB式(属性値・要素テキスト
内容の両方の直列化形、知見13)の中の識別子トークンを正規名へ書き換える
——文字列リテラル(`"..."`)の内側とメンバアクセス(`.`直後、例:
`obj.Foo`の`Foo`)は対象外(メソッド/プロパティ名であり変数名ではない
ため)。(3) `parse_workflow_file`が既存の`class_name`/`arguments`/
`variables`/本体抽出より前にこの正規化を実行するため、**`render.py`・
`uipath_codegen/__init__.py`・既存の`xaml_tree.py`の個別パーサー関数は
一切変更していない**——下流の全ての既存ロジックは、あたかも元から
表記が揺れていなかったかのようなXML木を読むだけで済む。

実機確認: 知見130が引用した実際の原因XAML(`TanMzCs2025/
EDSAChallengeTania2025_AmazonProductSearchAndFilter`の`Browser_
ValidateLangAndCur.xaml`)を再ダウンロードして`generate_python()`を
実行し、修正前は`def Hover(out_RequirementLanCur): ... Out_
RequirementLanCur = 'False'`という2つの別々の識別子になっていたのが、
修正後は`out_RequirementLanCur = 'False'`(関数の仮引数と同じ識別子)
に正しく揃うことを確認した。実装中に発見した追加の罠: このファイルの
`Assign.To`は`[Out_RequirementLanCur]`を**属性値ではなく`<OutArgument>`
要素のテキスト内容**として直列化していた(知見13の「`x:TypeArguments`
が`x:Object`以外の場合の属性形/要素テキスト形の両方があり得る」規約の
典型例)——属性値のみを対象にした最初の実装では素通りしてしまい、
要素テキストへの同じ正規化ロジックを追加して初めて実際に修正できた
(実機データでの検証が無ければ発覚しなかった種類のギャップ)。

既存の`Main.xaml`/`Sub1.xaml`フィクスチャ+この session で蓄積した
複数の実機XAML(再ダウンロードした3件)で`generate_python()`+
`compile()`を再実行し、退行が無いことを確認(いずれも正規化対象の
表記揺れ自体を含まないため生成結果は変化せず、実行速度も数ミリ秒の
オーダーで実用上無視できる)。回帰テスト追加(`tests/test_uipath_dsl.py`
3件——引数の表記揺れ・ローカル変数の表記揺れ・メンバアクセス/文字列
リテラルの誤爆防止を個別にテスト)、UiPath関連テスト全645件通過、
リポジトリ全体で全1685件通過。

## 161. `ui:BrowserScope`(「Attach Browser」、`WindowScope`より多い3388件ヒット)を新規実装——`AttachWindowNode`を3回目の再利用

知見159で発見した`ui:BrowserScope`(「Attach Browser」、`GSA/
Credit_Card_Logging_Bot`の実機XAMLで遭遇)を実装した。GitHub code
searchで**3388件ヒット**——`ui:WindowScope`(知見158、1688件)より
さらに多い、実務で非常に高頻度に使われる活動だと判明した。

実機5件(`PacktPublishing/Robotic-Process-Automation-Projects`・
`piyushagarwal08/JU-Notes`・`miyaichi/CertificationExam1`・
`allenlooplee/RPABook`)で構造を確認した結果、`ui:WindowScope`と
完全に同じ`ActivityAction`+`DelegateInArgument`(`Name`は
`"ContextTarget"`固定)のラッパー構造で、意味論も同じ(既存の
ウィンドウ/ブラウザに接続して`Body`を実行、起動は行わない)——
`AttachWindowNode`(知見153・158)を3回目の再利用先として同じ
ノード型を返すだけで実装できた。ブラウザ固有の追加属性は`Browser`
(アタッチ先を指す既存の`UiBrowser`型変数への入力参照)・`UiBrowser`
(アタッチ結果を受け取る出力バインディング、`ApplicationWindow`と
同種)・`ContinueOnError`の3つで、実機確認した5件全てで`{x:Null}`
だった——`SearchScope`/`TimeoutMS`は`WindowScope`と共有の既存
フィールドをそのまま再利用できた。`BrowserType`(`"Chrome"`/
`"Firefox"`/`"IE"`等、実機確認済み)は単純な注釈情報(どのブラウザ
エンジンかを示すだけで透過的ラッパーの動作自体には影響しない)として
保持するのみで、decline判定の対象にはしなかった。

実装中に発見した副産物: `_generate_attach_window_body`の既存の
`# TODO`文言が`"WindowScope"`で固定ハードコードされていたため、
`BrowserScope`経由で同じ分岐(`SearchScope`/`TimeoutMS`等の共有
フィールド)に到達すると不正確なラベルが出てしまう——`node.browser_
type is not None`(`BrowserScope`のみ設定される)でラベルを
`"BrowserScope"`/`"WindowScope"`に切り替える小さな修正を同時に
入れた。

実機XAML(`PacktPublishing`の`Main.xaml`——`UiBrowser`/`Browser`の
両方が設定されている実例、`piyushagarwal08/JU-Notes`の`Main.xaml`
——全て`{x:Null}`の単純な実例)で`generate_python()`+`compile()`を
実行し、前者は`# TODO: BrowserScope with UiBrowser output binding
set`/`# TODO: BrowserScope with Browser set`へ正しく倒れ、後者は
`# Attach window: <html app='firefox.exe' .../>`+子の再帰生成が
正しく動くことを確認した。回帰テスト追加(`tests/test_uipath_dsl.py`
1件・`tests/test_uipath_codegen.py`4件)、UiPath関連テスト全650件
通過、リポジトリ全体で全1690件通過。

## 162. `ui:Activate`(GitHub code searchで604件ヒット)を新規実装——`Click`/`Hover`より単純な「フォアグラウンド切り替えのみ」の活動、`UiPath/skills`公式ground-truthコーパスを初めて実際に活用

`Click`(知見9)・`Hover`(知見157)と同じ`UiPath.Core.Activities`の
基本UI Automation活動のうち、指定したウィンドウ/要素をフォアグラウンド
へ切り替えるだけの`ui:Activate`(GitHub code searchで604件ヒット)が
未実装のまま残っていたことを発見した。

知見128で発見した`marcelocruzrpa/uipath-ai-skills`のStudio実機
ground-truthコーパス(`uipath-core/references/studio-ground-truth/
UiPath.UIAutomation.Activities/25.10/Activate.xaml`)を、知見128で
「属性**名**の一覧としては権威的で有用、populated時の実例は別途実
プロジェクトで確認が必要」と記録していた通りの使い方で初めて実際に
活用した——属性の完全な語彙(`Target`+`DelayBefore`/`DelayMS`)を
このground-truthコーパスで確認し、非デフォルト値(`ContinueOnError`
を含む`Selector`設定済みの実例)は別途実機XAML5件(`Digital-RPA/
MRE_B2BE`・`revaturelabs/uipath-automation-2`・`FadyYosry/
IMDb_RottenTomatoes`・`piyushagarwal08/JU-Notes`)で補完した——
`CursorPosition`自体を持たない点が`Click`/`Hover`より単純だと確定
できた(クリックも移動も伴わない活動であるため)。

pywinautoの`set_focus()`(両バックエンドの`base_wrapper`で共通に
サポートされる確認済みの標準API)が直接対応する——`Hover`で発見した
`move_mouse_input()`の既定値の罠(知見157)のような注意点は無い、
最も単純な変換の1つ。

`dump_daemon/uipath_dsl/types.py`に`ActivateNode(selector, display_
name, delay_before, delay_ms, continue_on_error)`、`xaml_tree.py`に
`_parse_activate`(`_parse_hover`と同じTarget抽出、`CursorPosition`
抽出は無し)+`(UI_NS, "Activate")`の`_DISPATCH`登録、`uipath_codegen/
__init__.py`に`_generate_activate`/`_generate_activate_body`
(`DelayMS`/`ContinueOnError`の非デフォルト値は同じ理由で`# TODO`へ
倒す)を追加。実機XAML(`Digital-RPA/MRE_B2BE`の`CloseSICS.xaml`)で
`generate_python()`+`compile()`を実行し、`.set_focus()`呼び出しが
正しく生成されることを確認した——別の実機XAML(`PacktPublishing`の
`Main.xaml`)では`Activate`が知見161の`BrowserScope`(`Browser`/
`UiBrowser`設定済みで`# TODO`へ倒れる)の子としてネストされており
到達不能だったことも確認したが、これは既存の別課題で今回のスコープ
外。回帰テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
test_uipath_codegen.py`7件)、UiPath関連テスト全658件通過、
リポジトリ全体で全1698件通過。

## 163. `Target.Selector`の`{x:Null}`正規化漏れを発見・修正、10箇所の重複インライン実装を共通ヘルパーへ統合(知見133・141と同じ「バグ修正+重複解消を1回で」パターン)

知見162(`ui:Activate`)の実装検証で、`UiPath/skills`公式ground-truth
コーパス(`Activate.xaml`)の`Selector="{x:Null}"`(未設定)という
実例を使って手動確認したところ、`selector`フィールドに文字列
`"{x:Null}"`がそのまま残り(本来`None`であるべき)、`# TODO: Activate
selector had no mappable attributes: {x:Null}`という紛らわしい文言に
なることを発見した。

原因を遡ると、`Target`プロパティ要素配下の`ui:Target`要素から
`Selector`属性を取得する処理(`selector = None; target_prop = _find_
property_element(elem, "Target"); ...; selector = _attr(child,
"Selector")`という6行のブロック)が、`_parse_click`/`_parse_hover`/
`_parse_activate`/`_parse_type_into`/`_parse_type_secure_text`/
`_parse_send_hotkey`/`_parse_get_text`/`_parse_get_full_text`/
`_parse_select_item`/`_parse_ui_element_exists`の**10箇所全てで
バイト同一のまま重複**しており、いずれも`_attr()`で属性値を直接
読むため`_parse_expr`(知見13の`{x:Null}`→`None`正規化規約)を経由
していなかった——でっち上げではなく「解析できなかった」という安全側
の結果自体は変わらないため実害は軽微だったが、`None`の場合に出る
分かりやすい「no selector captured」という文言には倒れず、`{x:Null}`
という内部実装の生テキストがそのまま利用者向けのコメントに漏れて
いた。

知見133(`.Equals`等の`_apply_chained_call`統合)・知見141
(`_with_scope_child_display_name`の15箇所重複解消)と同じ「バグ修正
と重複解消を1回で行う」パターンで、新しい共通ヘルパー`_target_
selector(elem)`を追加し、`{x:Null}`→`None`正規化をこの1箇所に
集約した上で、10箇所の重複インラインブロックを全て`selector =
_target_selector(elem)`という1行呼び出しへ置き換えた——この10個の
活動の個別のパーサー関数自体は他に一切変更していない。既存の
全1698件のテスト(退行無し)に加え、実機XAML2件(`PacktPublishing`の
`KeyboardActions.xaml`・`Digital-RPA/MRE_B2BE`の`CloseSICS.xaml`)で
`generate_python()`+`compile()`を再検証し、挙動が変わらないことを
確認した。回帰テスト追加(`tests/test_uipath_dsl.py`1件、`Activate`
を使って`{x:Null}`→`None`正規化を直接確認)、UiPath関連テスト全
659件通過、リポジトリ全体で全1699件通過。

## 164. `ui:SetFocus`(`Activate`の同義の別活動)を新規実装——`UiPath/skills`公式ground-truthコーパスで構造の同一性を即座に確認できた好例、副産物として`GetValue`タグ名直書き実例を発見

知見128で発見した`marcelocruzrpa/uipath-ai-skills`のStudio実機
ground-truthコーパス(`UiPath.UIAutomation.Activities/25.10/`配下)を
知見162の`ui:Activate`に続いて再び活用し、同ディレクトリの
`SetFocus.xaml`を確認したところ、`ui:Activate`と属性構成が完全に
同一(`Target`+`DelayBefore`/`DelayMS`/`ContinueOnError`のみ)だと
判明した。GitHub code search(`"ui:SetFocus" extension:xaml`)で68件
ヒットし、実機(`JoeIaquinto/UiPath-VidCreator`の`Main.xaml`・
`PakamTharunReddy/RPA`の`Browser_fillvalues.xaml`)で`DisplayName`が
`"Set Focus '...'"`になる同義の別活動(`AttachWindow`/`WindowScope`/
`BrowserScope`、知見153・158・161と同じ「同義の別名活動」パターン)
だと確認した。

`_parse_activate`は属性名のみを汎用的に読む(タグ名自体には依存
しない)実装だったため、新しい専用パーサー関数を追加する必要が無く、
`_DISPATCH`に`(UI_NS, "SetFocus"): _parse_activate`を1行追加するだけ
で実装できた——このtickで最も経済的な実装になった。

実機XAML(`PakamTharunReddy/RPA`の`Browser_fillvalues.xaml`)で
`generate_python()`+`compile()`を実行し、`# Set Focus 'INPUT
name'`というコメント付きで(セレクタがWeb系属性のため既知の制約で
`# TODO: Activate selector had no mappable attributes`へ倒れる
ケースだったが)正しく動くことを確認した——ラベルが`"SetFocus"`
ではなく`"Activate"`のままなのは意図的な単純化(`WindowScope`/
`BrowserScope`のように複数の判別フィールドを持つ構造ではなく、
`display_name`の直前コメントで既に区別できるため)。

副産物として、この実機XAMLで`<GetValue ContinueOnError="{x:Null}" />`
という**タグ名を`ui:GetText`ではなく`GetValue`で直書きした実例**を
発見した——知見111の`GetTextNode`docstringが「公式ドキュメントは裏の
CLR型を`UiPath.Core.Activities.GetValue`(プロパティ名は`Value`)と
記載しているが、実機XAML上の属性名は常に`Text`」と記録していた話とは
別に、**タグ名自体が`GetValue`になる実例**(属性名は不明、`Text`では
なく生成コードが「Get Text」というコメントで表示されたことから
UiPath Studio側はこれを`GetText`活動として表示しているらしい)——
次の調査候補として記録する(未実装)。同じファイルで`ui:Check`
(チェックボックス操作)・`ui:Highlight`(要素の視覚的ハイライト)も
未実装の活動として遭遇した——いずれも次の棚卸し候補。

回帰テスト追加(`tests/test_uipath_dsl.py`1件)、UiPath関連テスト全
660件通過、リポジトリ全体で全1700件通過。

## 165. `ui:Check`(チェックボックス操作、GitHub code searchで805件ヒット)を新規実装——pywinautoのToggleパターン(`toggle()`/`get_toggle_state()`)を初めて活用、「無条件クリックは危険」という新しい判断パターン

知見164の`ui:SetFocus`実機XAML調査中に遭遇した`ui:Check`
(チェックボックス操作、GitHub code searchで805件ヒット)を実装した。
実機5件(`PacktPublishing/Robotic-Process-Automation-RPA-for-
Developers`・`miyaichi/UiLession`)で構造を確認した結果、`Action`
(実機確認済みの値は`"Check"`/`"Uncheck"`の2種)+`Target`+
`ContinueOnError`/`DelayAfter`/`DelayBefore`——`DelayBefore`は他のUI
Automation活動と共有の「Common」属性グループで意味論確認済み
(知見106)だが、`DelayAfter`は本調査で初めて遭遇した属性で意味論
未確認のため`DelayMS`と同じ理由で非既定値設定時は`# TODO`へ倒す。

実装上の重要な判断: `Action="Check"`/`"Uncheck"`は「指定の最終状態へ
**設定する**」操作であり、`Click`のような単純な無条件クリックでは
ない——既にチェック済みの状態で`Action="Check"`を無条件にクリック
すると誤って外してしまう(逆に`Action="Uncheck"`で未チェック状態を
クリックすると誤って入れてしまう)。これを安全に実装するため、
pywinautoのUIA`ButtonWrapper`(`CheckBox`/`RadioButton`/`Button`の
`control_type`に適用される)が標準サポートする`toggle()`+
`get_toggle_state()`(`0=unchecked`/`1=checked`/`2=indeterminate`、
`.venv/lib/python3.12/site-packages/pywinauto/controls/uia_controls.py`
で確認)を初めて活用した——現在の状態を読んでから目的の状態と異なる
場合のみ`toggle()`を呼ぶ専用ヘルパー`_pywinauto_set_toggle_state`を
新規追加した。本トランスパイラがこれまでの活動(`Click`等)では
「現在の状態を考慮せず単純に操作する」で十分だったのに対し、
`Check`/`Uncheck`は「現在の状態を見てから条件分岐する」という初めて
の種類の活動であり、無条件の`click_input()`を使うと**でっち上げでは
なく実際の誤動作**(意図と逆の結果)を生む可能性がある点に注意して
設計した。

`dump_daemon/uipath_dsl/types.py`に`CheckNode(selector, display_name,
action, delay_before, delay_after, continue_on_error)`、`xaml_tree.py`
に`_parse_check`(`_target_selector`を再利用、知見163)+`(UI_NS,
"Check")`の`_DISPATCH`登録、`uipath_codegen/__init__.py`に
`_SET_TOGGLE_STATE_HELPER_SOURCE`(新規ヘルパー関数定義、使用時のみ
注入)・`_generate_check`/`_generate_check_body`(`Action`が確認済みの
`"Check"`/`"Uncheck"`以外、または`DelayAfter`/`ContinueOnError`が
設定されている場合は`# TODO`へ倒す)を追加。実機XAML
(`miyaichi/UiLession`の`Open.xaml`)で`generate_python()`+
`compile()`を実行し、`Action="Check"`→`_pywinauto_set_toggle_
state(..., True)`、`Action="Uncheck"`→`..., False)`の両方が正しく
生成される(4件全て)ことを確認した——別の実機XAML
(`PacktPublishing`)は`Check`がWebベースのセレクタを使っており、
既知の制約(`selector_text_to_pywinauto`が`webctrl`属性に未対応)で
`# TODO`へ倒れることも確認した(今回のスコープ外の既存の別課題)。
回帰テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
test_uipath_codegen.py`10件)、UiPath関連テスト全671件通過、
リポジトリ全体で全1711件通過。

## 166. `ui:Highlight`(要素の視覚的ハイライト、GitHub code searchで289件ヒット)を新規実装——実行時効果が無い活動を`# TODO`ではなく常にコメント生成として扱う新しい判断パターン

知見164の`ui:SetFocus`実機XAML調査中に遭遇した`ui:Highlight`
(要素の視覚的ハイライト、GitHub code searchで289件ヒット)を実装
した。実機4件(`PacktPublishing/Robotic-Process-Automation-RPA-for-
Developers`・`SuneetPatil/IRCTC-tatkal-booking`)で構造を確認した
結果、`Color`(`.NET Color`構造体の名前付き色、実機確認済みの値は
`"Blue"`/`"Gold"`)・`HighlightTime`(ミリ秒、実機確認済みの値は
`"3000"`/`"1000"`)+`Target`のみ——出力バインディング(`Result`等)を
一切持たない。

設計上の重要な判断: この活動は画面上に一時的な色付き枠を表示する
だけの**純粋な視覚的デバッグ支援**で、後続のアクティビティへ渡す
データや制御フローへの影響が一切無い。pywinautoには近い機能
(`draw_outline()`)があるが、対応する色文字列の語彙が`'red'`/
`'green'`/`'blue'`の3色のみ(`.venv/lib/python3.12/site-packages/
pywinauto/base_wrapper.py`で確認)で実機確認した`"Gold"`等をカバー
できず、かつ`draw_outline()`自体は描画するだけで`HighlightTime`
経過後に自動で消す機能を持たない——不確実な視覚的再現を試みるより、
`ui:Comment`(知見119)と同じ「実行時の挙動が無い活動はコメントへ
変換する」設計を適用する方が誠実だと判断した。これは知見165の
`ui:Check`(「現在の状態を見てから条件分岐する」必要があった)とは
対照的な、「活動の実行結果が自動化スクリプトの正しさに全く影響
しない」という新しい判断軸——`# TODO`(何かが未実装/未対応、将来
対応の余地がある)ではなく、意図的に「この活動には再現すべき実行時
効果が無い」という最終判断を示す常時成功のコメント生成パスとして
実装した(`selector_text_to_pywinauto`による選択子マッピングの
成否判定自体が不要——実際の呼び出しを一切行わないため)。

`dump_daemon/uipath_dsl/types.py`に`HighlightNode(selector, display_
name, color, highlight_time)`、`xaml_tree.py`に`_parse_highlight`
(`_target_selector`を再利用、知見163)+`(UI_NS, "Highlight")`の
`_DISPATCH`登録、`uipath_codegen/__init__.py`に`_generate_highlight`
(`Color`/`HighlightTime`/`Selector`を全て注釈コメントへ埋め込むだけ
——decline分岐が1つも無い、このtickで最も単純な実装)を追加。実機
XAML(`cameronmcnz/uipath-tutorials`の`Xample-Orchestrator01/
Main.xaml`)で`generate_python()`+`compile()`を実行し、`# Highlight
Color=Gold HighlightTime='1000' — visual-only debugging aid, no
automation effect to reproduce`が正しく生成されることを確認した
——別の実機XAML(`PacktPublishing`)は`Highlight`が知見164で発見した
`GetValue`タグ名直書き活動(未実装)の子としてネストされており到達
不能だったことも確認したが、これは既存の別課題で今回のスコープ外。
回帰テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
test_uipath_codegen.py`3件)、UiPath関連テスト全675件通過、
リポジトリ全体で全1715件通過。

## 167. `ui:GetValue`(`ui:GetText`の裏のCLR型名そのものがタグ名として直列化される実例)を新規実装——4回目の`GetTextNode`再利用

知見164で発見した`<GetValue ContinueOnError="{x:Null}" />`という
タグ名自体が`GetValue`になる実例(GitHub code searchで1262件ヒット)
を調査し、実装した。知見111の`GetTextNode`docstringは「公式ドキュメ
ントは裏のCLR型を`UiPath.Core.Activities.GetValue`(プロパティ名は
`Value`)と記載しているが、実機XAML上の属性名は常に`Text`」という
ドキュメントの用語と実装の食い違いを記録していたが、今回の発見は
それとは別に**タグ名自体が本当に`GetValue`になる**実例——`ui:`
プレフィックス付きで`UI_NS`名前空間内のタグとして確認(`PakamTharunReddy/
RPA`の初回発見時は見落としていたが、`ui:`プレフィックスは正しく
存在していた)。

実機5件(`HarshadRanganathan/uipath-learning`・`cameronmcnz/
uipath-tutorials`・`allenlooplee/RPABook`・`PacktPublishing/
Robotic-Process-Automation-Projects`)で構造を確認した結果、
`DisplayName`が常に`"Get Text '...'"`になり(意味論が`GetText`
そのもの、`GetFullText`のような「可視テキストのみ」と「フル
テキスト」の違いは無い)、出力プロパティ名のみ`Text`ではなく
`Value`(プロパティ要素形、知見159の`_in_argument_property_expr`で
抽出)という違いだった。属性は`ContinueOnError`+`Target`のみ——
`DelayBefore`/`DelayMS`は実機で一度も確認できなかった(`ui:GetText`
の属性形とは違い常に省略されるらしい)。意味論が`GetText`そのもの
なので`full_text=False`(既定)のまま同じ`GetTextNode`を返す——
`ui:ForEachRow`/`ui:TypeSecureText`/`ui:WindowScope`/`ui:BrowserScope`/
`ui:SetFocus`に続く、既存ノード型を再利用するだけで実装できた4回目の
「同義の別タグ名」パターン。

`dump_daemon/uipath_dsl/xaml_tree.py`に`_parse_get_value`
(`_target_selector`+`_in_argument_property_expr`を再利用)+
`(UI_NS, "GetValue")`の`_DISPATCH`登録のみ——`types.py`・
`uipath_codegen/__init__.py`は一切変更していない(新しいフィールドも
不要)。実機XAML3件で`generate_python()`+`compile()`を実行したが、
いずれも`ui:AnchorBase`・`ui:OpenBrowser`という異なる未実装のコン
テナ活動の子としてネストされており到達不能だったため(今回のスコープ
外の既存の別課題)、成功パス自体は単体テストで直接確認した。副産物
として`ui:OpenBrowser`(`BrowserType`/`Hidden`/`NewSession`/`Private`/
`UiBrowser`/`Url`属性を確認、`ui:OpenApplication`(知見154)と同種の
「実際に新しいプロセス(ブラウザ)を起動する」活動と推定)という
未実装活動を発見し、次の棚卸し候補として記録する。回帰テスト追加
(`tests/test_uipath_dsl.py`1件)、UiPath関連テスト全676件通過、
リポジトリ全体で全1716件通過。

## 168. `ui:OpenBrowser`(GitHub code searchで2648件ヒット)を新規実装——`webbrowser`標準ライブラリで実行ファイルパスの推測を避ける新しい判断パターン

知見167で発見した`ui:OpenBrowser`(GitHub code searchで2648件ヒット
——`OpenApplication`より多い、新しいブラウザインスタンスを起動する
活動)を実装した。実機5件(`PacktPublishing/Robotic-Process-
Automation-RPA-for-Developers`・`allenlooplee/RPABook`・
`piyushagarwal08/JU-Notes`・`miyaichi/CalculateClientSecurityHash`)
で構造を確認した結果、`OpenApplication`(知見154)と同じ
`ActivityAction`+`DelegateInArgument`ラッパーを持つが`Target`/
`Selector`は一切持たない(既存ウィンドウに接続するのではなく新規
起動する活動であるため)。属性は`Url`(生リテラル/動的VB式の両方を
確認)・`BrowserType`(`"IE"`/`"Chrome"`/`"Firefox"`)・`Hidden`/
`NewSession`/`Private`(Boolean、既定値は`"False"`/`"True"`/
`"False"`——`Hidden="True"`の実例も確認したが「ヘッドレスモード」の
再現方法は未確認)・`UiBrowser`(出力バインディング、`[firefox]`の
実例を確認)・`CommunicationMethod`(実機で一度も非`{x:Null}`の値を
確認できず意味論未確認)。

設計上の重要な判断: `OpenApplication`の`subprocess.Popen([file_
name])`という「XAMLに明示された絶対パスをそのまま使う」安全な経路が
`OpenBrowser`には使えない——`BrowserType`別の実行ファイルパスはXAML
に一切現れず、OS/インストール環境依存の推測(`chrome.exe`がどこに
あるか等)が必要になってしまう。知見151(`ui:Delay`)以来の「確認済み
の標準APIを使い、新しい前提を持ち込まない」方針に従い、Python標準
ライブラリの`webbrowser.open(url)`(特定のブラウザ実行ファイルパスを
一切推測せずOS既定の方法でURLを開く、確認済みの標準API)を採用した
——`BrowserType`で指定された特定のブラウザが実際に開かれることまで
は主張せず`# WARNING`で明示する。これは知見154の`OpenApplication`
(XAMLに明示されたパスがあるので直接起動できる)とは対照的な、「確認
済みのプロセス起動経路が無い場合は、OS抽象化層の標準ライブラリに
頼る」という新しい判断パターン。

`dump_daemon/uipath_dsl/types.py`に`OpenBrowserNode(url, browser_
type, hidden, new_session, private, ui_browser, communication_
method, body, display_name)`、`xaml_tree.py`に`_parse_open_browser`
(`OpenApplication`と同じ`ActivityAction`抽出)+`(UI_NS,
"OpenBrowser")`の`_DISPATCH`登録、`uipath_codegen/__init__.py`に
`_generate_open_browser`/`_generate_open_browser_body`(`Hidden`/
`NewSession`の非既定値・`Private`/`UiBrowser`/`CommunicationMethod`
が設定されている場合は`# TODO`へ倒す)を追加し、`_child_node_lists`
(知見88が警告する複数ファイル結線用の別registry)にも登録。`webbrowser`
の`import`検出条件を`_collect_imports`に追加。実機XAML
(`PacktPublishing`の`Weather.xaml`)で`generate_python()`+
`compile()`を実行し、`import webbrowser`+`# WARNING: BrowserType=
'IE' requested...`+`webbrowser.open(_vb_cstr('https://www.google.
com/'))`が正しく生成されることを確認した(2件全て)。回帰テスト追加
(`tests/test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`9件)、
UiPath関連テスト全687件通過、リポジトリ全体で全1727件通過。

## 169. `ui:KillProcess`(GitHub code searchで1514件ヒット——REFrameworkの標準サブワークフローで多用)を新規実装——Windows標準`taskkill`コマンドへの直接対応

`OpenApplication`(知見154)・`OpenBrowser`(知見168)に続く
プロセス関連活動として`ui:KillProcess`(GitHub code searchで
1514件ヒット)を実装した。実機3件(`piyushagarwal08/JU-Notes`の
REFramework標準サブワークフロー`KillAllProcesses.xaml`・
`vajrang-b/UiPathIn30Days`)で構造を確認した結果、`Target`/
`Selector`を一切持たない(既存ウィンドウに接続するのではなく、
プロセス名で指定した全プロセスを終了する活動であるため)、
`ProcessName`(実機確認済みの値は`"iexplore"`/`"msedge"`——`.exe`
拡張子を含まない、.NETの`Process.GetProcessesByName()`と同じ慣習)
+`Process`(UiPathの`Process`型オブジェクト参照、実機確認した全件で
`{x:Null}`)+`AppliesTo`(実機で一度も非`{x:Null}`の値を確認できず
意味論未確認)+`ContinueOnError`(全件`{x:Null}`)。

`OpenApplication`/`OpenBrowser`とは違う3番目のパターン:
`OpenApplication`はXAMLに明示された絶対パスを`subprocess.Popen`で
直接起動、`OpenBrowser`は実行ファイルパスが推測できないため
`webbrowser`標準ライブラリに頼った——`KillProcess`はWindows標準
搭載の確認済みコマンド`taskkill /IM <name>.exe /F`(`subprocess.run`
経由)が直接対応する、最も単純なケースに戻った。`/T`(プロセス
ツリー全体の終了)は付けない——.NETの素の`Process.Kill()`は子プロセス
を終了しないため、過大な終了範囲をでっち上げないよう安全側に倒した
判断。

`dump_daemon/uipath_dsl/types.py`に`KillProcessNode(process_name,
display_name, process, applies_to, continue_on_error)`、
`xaml_tree.py`に`_parse_kill_process`+`(UI_NS, "KillProcess")`の
`_DISPATCH`登録、`uipath_codegen/__init__.py`に`_generate_kill_
process`/`_generate_kill_process_body`(`Process`/`AppliesTo`/
`ContinueOnError`が設定されている場合は`# TODO`へ倒す)を追加。
`subprocess`の`import`検出条件(既存の`subprocess.Popen(`に加えて
`subprocess.run(`も検出するよう拡張)。実機XAML2件
(`KillAllProcesses.xaml`・`vajrang-b/UiPathIn30Days`の`Main.xaml`)
で`generate_python()`+`compile()`を実行し、`subprocess.run(["taskkill",
"/IM", f"{_vb_cstr('iexplore')}.exe", "/F"])`/
`f"{_vb_cstr('msedge')}.exe"`が正しく生成されることを確認した
(2件全て)。回帰テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
test_uipath_codegen.py`6件)、UiPath関連テスト全694件通過、
リポジトリ全体で全1734件通過。

## 170. `ui:CloseTab`(GitHub code searchで782件ヒット)を新規実装——pywinautoの`keyboard.send_keys()`(対象無しのグローバル送信)を初めて実際に活用、知見152が残していた未対応経路を解消

知見169の`ui:KillProcess`調査の延長で、OpenApplication/OpenBrowserの
対になる「閉じる」系活動を調査し、`ui:CloseTab`(GitHub code search
で782件ヒット)を実装した。実機3件(`allenlooplee/RPABook`・
`PacktPublishing/Robotic-Process-Automation-Projects`・
`piyushagarwal08/JU-Notes`)で構造を確認した結果、`Target`/
`Selector`を一切持たない、唯一の属性は`Browser`(`UiBrowser`型変数
参照——`OpenBrowser`の`UiBrowser`出力バインディング(知見168)や
`BrowserScope`の`UiBrowser`属性(知見161)と同種)のみ。実機確認した
値は`{x:Null}`(ほとんどのREFramework実例、`BrowserScope`の内側で
使われ「現在アタッチ中のブラウザの、現在アクティブなタブ」を暗黙に
指す)と、動的VB式(`[browserCrunchBase]`/`[firefox]`)の両方。

`Browser`が`{x:Null}`の場合、意味論は「現在フォーカス中のタブ/
ウィンドウを閉じる」になり、主要ブラウザ(Chrome/Firefox/Edge/IE)
共通の標準キーボードショートカット`Ctrl+W`で実現できる——これは
知見152の`ui:SendHotkey`で「`Target`が省略された自己終了タグ
(`AI-Dep/AI-Antigravity`の実機XAMLで確認、現在フォーカス中のウィン
ドウへグローバルに送信する意味論と推定)」として**未対応のまま
残していた経路**と全く同じもので、今回`ui:CloseTab`の実装を通じて
初めて実際に実装することになった——pywinautoの`keyboard.send_keys()`
(モジュールレベルの関数、要素を指定せず現在フォーカス中のものへ
キーを送る確認済み標準API、`Click`/`TypeInto`/`SendHotkey`が使う
要素単位の`.type_keys()`メソッドとは別の経路)がこのケースに
ちょうど対応する。`Browser`が変数参照の場合は(`UiBrowser`変数自体
が知見154・161・168で繰り返し確認済みの未モデル化のため)`# TODO`
へ倒す。

`dump_daemon/uipath_dsl/types.py`に`CloseTabNode(browser, display_
name)`、`xaml_tree.py`に`_parse_close_tab`+`(UI_NS, "CloseTab")`の
`_DISPATCH`登録、`uipath_codegen/__init__.py`に`_generate_close_tab`
/`_generate_close_tab_body`(`Browser`が変数参照の場合は`# TODO`、
それ以外は`send_keys('^w')`)を追加。`from pywinauto.keyboard import
send_keys`の`import`検出条件を`_collect_imports`に追加。実機XAML
(`piyushagarwal08/JU-Notes`の`SHA1_Close.xaml`)で`generate_python()`
+`compile()`を実行し、`from pywinauto.keyboard import send_keys`+
`send_keys('^w')`が正しく生成されることを確認した。回帰テスト追加
(`tests/test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`3件)、
UiPath関連テスト全699件通過、リポジトリ全体で全1739件通過。

## 171. `ui:CloseApplication`(GitHub code searchで532件ヒット)を新規実装——pywinautoの`close()`(`WM_CLOSE`送信)で`ActivateNode`の`set_focus()`とは別の専用ノード型に

知見170の`ui:CloseTab`に続き、同じ「閉じる」系活動の兄弟として
`ui:CloseApplication`(GitHub code searchで532件ヒット)を調査した。
実機3件(`HarshadRanganathan/uipath-learning`の`Web_Recording.xaml`・
`piyushagarwal08/JU-Notes`のBlankProcess1`Main.xaml`・
`allenlooplee/RPABook`の`CloseNotepad.xaml`)で確認した構造は`Target`
+`DisplayName`/`ContinueOnError`のみ——知見162の`ui:Activate`と完全に
同一の属性構成。

ただし`ActivateNode`は再利用しなかった。属性構成が同一でも、生成する
pywinauto呼び出しの意味が全く違う——`Activate`は`set_focus()`
(フォーカス切替のみ、副作用なし)だが、`CloseApplication`は
`close()`(実機確認した`.venv`の`pywinauto/controls/hwndwrapper.py`
の実装で`self.post_message(win32defines.WM_CLOSE)`を送る、ウィンドウ
を実際に閉じる副作用のある操作)。`AttachWindowNode`を`WindowScope`/
`BrowserScope`で再利用した「透過スコープ」族(知見158・161)とは違い、
これは「実際に効果を起こす」活動同士なので、属性構成の一致だけを
理由にノード型を共有すると生成コードの意図(フォーカス切替か、
ウィンドウを閉じるか)が型レベルで読み取れなくなる——ノード型は
最終的な副作用の意味論で分けるべきだという判断。

実機3件で選択肢を確認:
- `HarshadRanganathan/uipath-learning`: `Selector="{x:Null}"`(未設定)
  →`# TODO: CloseApplication with no selector captured`
- `piyushagarwal08/JU-Notes`: 同じく`Selector="{x:Null}"`(ただし
  `OpenApplication.Body`の内側にネストされており、`OpenApplication`
  自体が`Arguments`設定時に未対応のため`# TODO`止まりで本体が
  展開されない——既知の別ギャップ、本調査の対象外)
- `allenlooplee/RPABook`: `Selector="<wnd app='notepad.exe' cls='Notepad'
  title='TestLog*' />"`(マッピング可能なセレクタ)→
  `Desktop(backend="uia").window(class_name='Notepad',
  title='TestLog*').close()`

`dump_daemon/uipath_dsl/types.py`に`CloseApplicationNode(selector,
display_name, continue_on_error)`、`xaml_tree.py`に
`_parse_close_application`+`(UI_NS, "CloseApplication")`の
`_DISPATCH`登録(`_target_selector`共通ヘルパー、知見163を再利用)、
`uipath_codegen/__init__.py`に`_generate_close_application`/
`_generate_close_application_body`(`Activate`の決定木——`selector`
無し→`# TODO`、`continue_on_error`設定時→`# TODO`、セレクタが
マッピング不能→`# TODO`、それ以外は`close()`——をそのまま流用)を
追加。実機XAML(`allenlooplee/RPABook`の`CloseNotepad.xaml`)で
`generate_python()`+`compile()`を実行し、
`Desktop(backend="uia").window(...).close()`が正しく生成されることを
確認した。回帰テスト追加(`tests/test_uipath_dsl.py`2件・
`tests/test_uipath_codegen.py`5件)、UiPath関連テスト全704件通過、
リポジトリ全体で全1746件通過。

## 172. `ui:CloseWindow`(GitHub code searchで276件ヒット)を新規実装——`Target`ラッパー無しのフラット`Selector`属性という「Classic」世代の属性慣習、`{x:Null}`正規化が初めて必要になったケース

知見171の`ui:CloseApplication`に続き、同じ「閉じる」系の兄弟活動として
`ui:CloseWindow`(GitHub code searchで276件ヒット)を調査した。実機5件
(`SuneetPatil/IRCTC-tatkal-booking`・`PacktPublishing/Robotic-Process-
Automation-RPA-for-Developers`・`KonduitAI/mailboxdetection-workflow`・
`aliya-rahmani/Projects`・`Klaus-in-Tech/Ford.com-scrapper`)で確認した
属性は`Selector`(`Target`子要素でラップせず、タグ自身の**フラット
属性**として直接持つ)+`UseWindow`(既存のウィンドウオブジェクト参照を
再利用する、実機で確認した値は`[browser_window.Element.
GetTopLevelWindow]`——`OpenBrowser`の`UiBrowser`出力バインディング
(知見168)等と同じ「未モデル化のオブジェクト参照」カテゴリ)+
`ContinueOnError`+`TimeoutMS`/`WaitForReady`(他のUI Automation活動と
同様、生成コードに影響しないため無視)。`UiPath/skills`公式リポジトリ
の25.10系ground-truthコーパスには存在せず、`AttachWindow`/
`OpenApplication`(知見154)と同じ旧世代(「Classic」)の属性慣習だと
確認した。

ここで初めて`{x:Null}`正規化の必要な新しいケースに遭遇した——
`AttachWindowNode`/`OpenApplicationNode`の`selector=_attr(elem,
"Selector")`は`_attr_expr`を経由しない生のフラット属性取得のため、
知見13の`{x:Null}`→`None`正規化を素通りする。`AttachWindow`/
`OpenApplication`ではSelectorが実質必須の属性で実機上`{x:Null}`に
なる例が無く問題が潜在していたが、`CloseWindow`は`UseWindow`使用時に
`Selector="{x:Null}"`になる実例(実機`SuneetPatil/IRCTC-tatkal-
booking`・`PacktPublishing/...`の2件)が頻出するため、本活動の専用
パーサー`_parse_close_window`で明示的に`if selector == "{x:Null}":
selector = None`という正規化を行った(知見163の`_target_selector`と
同じ規約だが、フラット属性用の別経路のため共通ヘルパー化はしていない
——`Target`ラッパー構造を前提とする`_target_selector`とは入力形状が
違うため)。

意味論は`CloseApplication`(知見171)と同一(pywinautoの`close()`、
`WM_CLOSE`送信)だが、属性構成(`Target`ラッパー無し)が全く違うため
`CloseApplicationNode`は再利用せず専用の`CloseWindowNode`とした。
`UseWindow`が設定されている場合は(オブジェクト参照自体が未モデル化
のため)`# TODO`へ倒す。

実機確認中に別の既知の限界にも再遭遇した——`aliya-rahmani/Projects`・
`Klaus-in-Tech/Ford.com-scrapper`の実機セレクタは`<html app='chrome.exe'
title='...' />`(`<wnd .../>`ではなく`<html>`タグ)で、現在の
`uipath_selector`モジュール(`_map_node`)は`node.tag == "wnd"`判定で
属性マップを選ぶため`<html>`タグは`_CTRL_ATTR_MAP`(属性0件マッチ)
に落ちて「no mappable attributes」になる——これは本活動固有の問題
ではなく`uipath_selector`全体の既存ギャップ(知見143で`<html>`タグへ
触れた記録はあるが、属性マッピングの拡張は未着手)なので、本調査の
スコープ外として別の調査候補に回す(下記「今後の調査候補」に追記)。
実機`<wnd>`ベースのセレクタ(合成テストで再現)では
`Desktop(backend="uia").window(class_name='Notepad').close()`が正しく
生成されることを確認した。

`dump_daemon/uipath_dsl/types.py`に`CloseWindowNode(selector,
use_window, display_name, continue_on_error)`、`xaml_tree.py`に
`_parse_close_window`+`(UI_NS, "CloseWindow")`の`_DISPATCH`登録、
`uipath_codegen/__init__.py`に`_generate_close_window`/
`_generate_close_window_body`を追加。回帰テスト追加(`tests/
test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`6件)、UiPath
関連テスト全710件通過、リポジトリ全体で全1754件通過。

## 173. `ui:MaximizeWindow`/`ui:MinimizeWindow`/`ui:RestoreWindow`(GitHub code searchでそれぞれ検索語の部分一致含む1632件/44件/13件ヒット)を新規実装——`WindowStateNode.method`で1つの生成関数に統合、pywinautoの`active_only=True`で「現在アクティブなウィンドウ」の意味論に初めて対応

知見172の`ui:CloseWindow`に続き、ウィンドウ状態操作系の活動を調査した
結果、`ui:MaximizeWindow`/`ui:MinimizeWindow`/`ui:RestoreWindow`という
3つの完全に同義な兄弟活動を発見した。実機5件(`allenlooplee/RPABook`・
`PacktPublishing/Robotic-Process-Automation-Projects`・
`piyushagarwal08/JU-Notes`・`Apress/Robotic-Process-Automation-Using-
UiPath-StudioX`・`LowyShin/lwrpa-uip-giipxls2kvs`)で確認した属性構成
は3タグとも完全に同一——`Window`+`DisplayName`/`ContinueOnError`のみ。
違いはpywinautoで呼ぶメソッド名(`maximize()`/`minimize()`/`restore()`、
`.venv`のソースで両バックエンド(`hwndwrapper.py`・`uiawrapper.py`)
共通に実装されている確認済み標準API)だけなので、属性構成そのものを
抽象化した`WindowStateNode(method, window, display_name,
continue_on_error)`という1つのノード型に統合し、`method`フィールドで
3つのタグを区別する——`_parse_window_state(elem, method)`という共通
パーサーに3つの薄いラッパー関数(`_parse_maximize_window`/
`_parse_minimize_window`/`_parse_restore_window`)から呼ぶ形にした。

実機確認した`Window`の値は`{x:Null}`(ほとんどの実例)と
`[Saved.Values(Of Window)("ActiveWindow")]`(StudioXの保存済み
`Window`型変数参照、`Apress/Robotic-Process-Automation-Using-UiPath-
StudioX`の実機XAMLで確認)の2種。`Window`が変数参照の場合は
(`Window`型オブジェクト自体が未モデル化のため、知見154・161・168・
170・172で繰り返し確認済みの既知の限界)`# TODO`へ倒す。

`Window`が`{x:Null}`(省略)の場合の意味論は「現在アクティブな
(フォーカス中の)ウィンドウ」——これまでの活動では`CloseTab`
(知見170)の`send_keys('^w')`のような「対象省略時はグローバルな
操作で対応する」という回避策しか無かったが、今回初めてpywinauto
`findwindows.find_elements()`の`active_only=True`パラメータ
(`.venv`のソースで`win32functions.GetGUIThreadInfo()`経由でOS全体の
アクティブウィンドウハンドルを取得する実装を確認済み、両バックエンド
共通でサポートされる標準API)を使い、`Desktop(backend="uia").
window(active_only=True)`という形で「現在アクティブなウィンドウ」
自体を検索条件として直接表現できた——これは今まで発見していなかった
pywinautoの標準機能で、将来「対象省略=現在アクティブなウィンドウ」
という同じ意味論を持つ活動(例えば知見152が残した`ui:SendHotkey`の
対象省略ケースでも、`send_keys()`より`active_only=True`で取得した
要素への`.type_keys()`の方が意図が明確になる可能性がある)に再利用
できる発見。

実機XAML(`PacktPublishing/...`の`ZOHOAutomation.xaml`・
`piyushagarwal08/JU-Notes`の`SHA1_Open.xaml`・`LowyShin/lwrpa-uip-
giipxls2kvs`の`XLS2KVS.xaml`)で`generate_python()`+`compile()`を
実行し、`Desktop(backend="uia").window(active_only=True).maximize()`/
`.minimize()`が正しく生成されることを確認した(`allenlooplee/RPABook`
・`Apress/...`の2件はState Machineルートのためv1スコープ外で
スキップ——既知の制約、本調査と無関係)。回帰テスト追加(`tests/
test_uipath_dsl.py`3件・`tests/test_uipath_codegen.py`6件)、UiPath
関連テスト全719件通過、リポジトリ全体で全1763件通過。

## 174. `ui:GetAttribute`(GitHub code searchで274件ヒット)を新規実装——`Attribute`の値を問わず常に`# TODO`へ倒す、知見38の`role`と同じ「VM未検証の属性マッピングは追加しない」判断を初めて正面から適用したケース

`ui:MaximizeWindow`系(知見173)に続き、`ui:GetAttribute`(GitHub code
searchで274件ヒット)を調査した。実機3件(`rohanbaraskar/UiPath-11`・
`miyaichi/CalculateClientSecurityHash`・`iamgauravjoshi/Shopping-Bot-
using-RPA`)で確認した構造は`Target`+`Attribute`(属性名の文字列、
実機確認済みの値は`"checked"`/`"innerText"`/`"relativeVisibility"`)+
`Result`(出力、`GetText`/`GetFullText`と同じ`_in_argument_property_
expr`形)+`ContinueOnError`。

`Attribute`は開放的な語彙——UiPathのブラウザ拡張機能がDOM/
アクセシビリティツリーから値ごとに全く別の経路で取得する仕組みで
ある。pywinauto(Win32/UIAバックエンドのみ、ブラウザのJS/DOM注入
機能を一切持たない)側にこれを安全に代替できる汎用APIが存在しない。
`"checked"`はUIAのTogglePattern(`get_toggle_state()`、知見165で
確認済み)で近似できる「かもしれない」という仮説はあるが、実機の
ブラウザ要素で本当にDOMの`checked`プロパティとUIAのToggle状態が
一致するかは独立に確認できておらず、知見38で`role`属性を
`control_type`へそのまま渡した際に実機`KeyError`というハード
クラッシュで裏付けられた「UiPathの語彙とpywinautoの語彙が一致する
保証は無い」という教訓を踏まえると、仮説のまま実装するのは本調査
全体を貫く「確認済みの安全な変換のみ」という方針に反する。

そのため本活動は`Attribute`の値を一切区別せず、常に`# TODO`へ倒す
設計にした——ただし「unknown activity」の生の属性ダンプに比べて、
`Attribute`名を明示した読みやすい`# TODO`(例: `# TODO: GetAttribute
(Attribute='innerText') — no pywinauto/UIA equivalent confirmed for
arbitrary DOM/accessibility attribute retrieval, refusing to guess`)
を生成する価値はある——将来、実機VM(pad2py-pad-host)で特定の
`Attribute`値(例えば`"checked"`)だけを個別に実機検証できれば、その
値だけを有効化する拡張の土台にもなる。これは本調査全体で初めて
「常にTODOへ倒れる活動」を、ノード型を適切にモデル化する価値がある
と判断して新規実装した例——Highlight(知見166、常に成功+コメント)
とは対照的な判断だが、両方とも「架空のAPIをでっち上げない」という
同じ方針の別の現れ方。

実機XAML3件で`generate_python()`+`compile()`を実行し、3種の
`Attribute`値すべてで名前付きの`# TODO`が正しく生成されることを
確認した(`miyaichi/...`の実機セレクタは`<wnd ...>`で部分的に
マッピング可能、`iamgauravjoshi/...`は`<webctrl ...>`で完全に
未マッピング——いずれにせよ`Attribute`自体の理由で`# TODO`になる
ため、セレクタのマッピング可否に関わらず安全に倒れることを確認)。
回帰テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
test_uipath_codegen.py`5件)、UiPath関連テスト全725件通過、
リポジトリ全体で全1769件通過。

## 175. `ui:RefreshBrowser`(GitHub code searchで59件ヒット)を新規実装——`CloseTab`(知見170)と属性構成・実装経路が完全に同型、`send_keys('{F5}')`で「ブラウザ再読み込み」に対応

知見174の`ui:GetAttribute`に続き、ブラウザ操作系の活動を調査した
結果、`ui:RefreshBrowser`(GitHub code searchで59件ヒット)を発見した
——これは知見170の`ui:CloseTab`と属性構成が完全に同型(`Target`/
`Selector`を一切持たず、唯一の属性は`Browser`というUiBrowser型変数
参照)で、実装経路もそのまま再利用できた。実機3件(`allenlooplee/
RPABook`・`PakamTharunReddy/RPA`・`csut017/CrowdMarkLoad`)で確認した
`Browser`の値は`{x:Null}`(ほとんどの実例、「現在アタッチ中の
ブラウザの、現在アクティブなタブ」を暗黙に指す)と動的VB式
(`[browser]`)の両方。

`Browser`が`{x:Null}`の場合の意味論は「現在のページを再読み込み
する」になり、主要ブラウザ(Chrome/Firefox/Edge/IE)共通の標準
キーボードショートカット`F5`で実現できる——`CloseTab`の`Ctrl+W`
(`send_keys('^w')`)と全く同じ`keyboard.send_keys()`(対象を
指定しないグローバルなキー送信)経路を再利用し、`{F5}`
(pywinautoの`.venv`ソース`keyboard.py`のCODESグラマーで確認済みの
特殊キー構文——`^w`の修飾キー構文とは別の、単独キー用の波括弧構文)
を送るだけの違い。既存の`send_keys(`検出による`from pywinauto.
keyboard import send_keys`の`import`追加条件(知見170)もそのまま
再利用でき、新しい`import`検出ロジックは不要だった。`Browser`が
変数参照の場合は(`UiBrowser`変数自体が知見154・161・168・170で
繰り返し確認済みの未モデル化のため)`# TODO`へ倒す。

実機XAML3件で`generate_python()`+`compile()`を実行し、
`PakamTharunReddy/RPA`の実例で`send_keys('{F5}')`が正しく生成される
ことを確認した(`allenlooplee/RPABook`・`csut017/CrowdMarkLoad`の
2件は、それぞれ`TryCatch`の複数`Catch`間での例外型の曖昧性(別の
既知の制約)・`BrowserScope`の`UiBrowser`出力バインディング未設定
(知見161・168で繰り返し確認済みの既知の制約)により、祖先ノードの
時点で先に`# TODO`へ倒れてスキップ——いずれも本調査と無関係な既存の
制約)。回帰テスト追加(`tests/test_uipath_dsl.py`2件・`tests/
test_uipath_codegen.py`3件)、UiPath関連テスト全730件通過、
リポジトリ全体で全1774件通過。

## 176. `ui:GetPassword`(GitHub code searchで540件ヒット)を新規実装——`ProtectedPassword`(Windows DPAPI暗号化バイナリ)は常にTODOへ倒し、かつ生成コードへ値そのものを一切出力しない安全設計

知見175の`ui:RefreshBrowser`に続き、`ui:GetPassword`(GitHub code
searchで540件ヒット——うち大半が1つの学習用リポジトリ
(`vajrang-b/UiPathIn30Days`)の類似演習(`Task31`/`Task33`)の重複
だったが、それを除外した検索(`NOT repo:vajrang-b/UiPathIn30Days`)
でも独立した実機10件以上(`Parmeetkour/RPA`・`akritimangal/
AssignmentsBOT`・`leticiassilva/Exercicio.Dev.Redesign`等)で確認
できた、実在する一般的な活動)を調査した。

確認した構成は`ProtectedPassword`(Windows DPAPIで暗号化された
Base64バイナリ——実機確認した全件が`AQAAANCMnd8BFdERjHoAwE/Cl+sB...`
というDPAPIの固定ヘッダ`01 00 00 00 D0 8C 9D DF 01 15 D1 11 8C 7A 00
C0 4F C2 97 EB`で始まる)+`Result`(出力、実機で2つの直列化形を確認
——フラット属性`Result="[pw]"`(`akritimangal/...`・`Parmeetkour/...`)
と、プロパティ要素形で`VisualBasicReference ExpressionText=
"Password"`という通常の`OutArgument`直書きとは異なる特殊な参照構造
(`vajrang-b/...`)の両方)。`ContinueOnError`は実機のどの例でも一度も
確認できなかった。

`ProtectedPassword`はWindows DPAPI(`CryptProtectData`)で暗号化されて
おり、暗号化を行ったWindowsユーザー・マシンの組み合わせでなければ
復号できない——UiPath Studioが設計時にローカルマシン上で暗号化した
値をXAMLへ直接埋め込むため、別マシン・別ユーザーで実行する生成
Pythonコードへこれを移植可能な形で復号する安全な方法が無い。さらに
資格情報を扱う機微な操作であるため、本活動は`ProtectedPassword`の
値自体をそもそもノード型に保持せず(パース時点で読み取らない)、
生成コードのコメントへも一切出力しない安全設計にした——知見174の
`ui:GetAttribute`(VM未検証のためTODOへ倒す)とは異なる理由
(「原理的に移植不可能」+「資格情報の機微性」の2つ)でTODOへ倒れる、
常にTODOへ倒れる活動の2例目。

二つの`Result`直列化形のうち、`VisualBasicReference`でラップされた
特殊な参照構造は`_in_argument_property_expr`(知見115)の既存の
「`Value`属性を持つ単純なネスト要素」という前提に一致せず、安全に
`None`を返す(でっち上げない)ことをテストで確認した——`_attr_expr`
(フラット属性形)と`_in_argument_property_expr`(プロパティ要素形)
を`or`で連結する、本調査で初めて使った「出力変数の直列化形が複数ある
場合に両方を順に試す」という新しいパーサー合成パターン。

実機XAML3件のうち2件(`Parmeetkour/RPA`・`akritimangal/
AssignmentsBOT`)で`parse_activity()`+`_generate_node()`を実行し、
`ProtectedPassword`の値が生成コードへ一切現れないことを確認した
(3件目`vajrang-b/...`はワークフロー全体の`compile()`時に無関係な
既存の`NotImplementedError`(`.Subject`のような未対応チェイン
メンバーアクセスが`render_expr`で捕捉されずクラッシュする、
`_render_func_call`のバグ)に遭遇したため、本活動単体の
`parse_activity()`/`_generate_node()`呼び出しでの検証に限定した——
`generate_python()`全体がこの種の未対応例外で丸ごとクラッシュする
のは本調査と無関係な別の既存バグで、安全側に`# TODO`へ倒すべき
箇所が例外の握り潰し漏れでクラッシュに変わっている可能性があり、
別の調査候補として記録)。回帰テスト追加(`tests/test_uipath_dsl.py`
2件・`tests/test_uipath_codegen.py`3件)、UiPath関連テスト全735件
通過、リポジトリ全体で全1779件通過。

## 177. 知見176が「別の既存バグ」と記録した`render_expr`の`NotImplementedError`クラッシュは、実際には`render.py`モジュールdocstring・`_generate_if`のインラインコメントの両方に明記された意図的な設計だったと判明——訂正

知見176の`ui:GetPassword`実機確認中、`vajrang-b/UiPathIn30Days`の
ワークフロー全体の`compile()`が`render_expr`の`NotImplementedError`
(`.Subject`という未対応のチェインメンバーアクセス)で丸ごとクラッシュ
する現象に遭遇し、「安全に`# TODO`へ倒すべき箇所が例外の握り潰し漏れ
でクラッシュに変わっている既存バグ」と記録し、横断的な改善候補として
`今後の調査候補`に追加した。本tickで実際に修正に着手する前に
`dump_daemon/uipath_codegen/render.py`のモジュールdocstring(ファイル
先頭)を読み直したところ、**これはバグではなく明記された意図的な
設計**だと判明した——該当箇所を引用する:

> **失敗モードの方針**: この関数は「安全に変換できない」と判断した
> 入力に対して`NotImplementedError`を送出する。呼び出し側
> (`uipath_codegen/__init__.py`)がこれをどう扱うか(代入先なら
> `# TODO`+プレースホルダへ倒す、条件式なら**でっち上げた真偽値で
> 制御フローを誤らせるよりコード生成全体を失敗させる**)を文脈ごとに
> 決める。

実際に`_generate_if`(`If.Condition`を処理する関数)のインライン
コメントにも同じ方針が明記されていた:「条件式は値より厳格——変換
できなければ例外を伝播させてコード生成自体を失敗させる」。対照的に、
`_render_value_or_todo`(単純な値の代入先を処理する関数)は
`NotImplementedError`を`try/except`で捕捉し、`# TODO`+プレース
ホルダ(`"None"`)へ倒す——つまり「値の文脈では`# TODO`、条件式の
文脈では例外伝播による生成全体の失敗」という**文脈依存の2段構えの
安全策**が既に実装されている。でっち上げた真偽値(例えば安全側に
倒すつもりで`False`を返す)で`If`文の分岐自体を間違えると、それは
`# TODO`コメントより遥かに発見しにくい「静かに間違った動作をする」
バグになる——この方針はpad2py全体の「架空のAPIをでっち上げない」
という大原則の、条件式という特に危険なコンテキストへの正しい適用
だった。

**訂正**: 知見176の該当段落と`design/uipath_transpiler_roadmap.md`
実装ログ項目134の該当箇所は「既存バグ」という誤った記録として残すが
(訂正は新しい知見として追記する、という本ドキュメントの既存の
慣習——知見113参照)、実際には修正不要。`今後の調査候補`からも該当
項目を解決済み(ネガティブ)として記録し直した。

**教訓**: 一見「でっち上げを防ぐための安全策が中途半端にしか効いて
いない」ように見えるコードに遭遇した際は、修正に着手する前に当該
モジュールのdocstring・インラインコメントを必ず読むこと——今回は
幸い実際の修正(スコープ外の変更)に着手する前に気づけたが、一歩
踏み出す前の確認を怠れば、意図的な安全策を破壊する誤った「修正」を
加えてしまうリスクがあった。

## 178. `ui:LoadImage`(GitHub code searchで58件ヒット、OCR系活動の入力として使われる)を新規実装——Pillow(`PIL.Image.open()`)が標準でサポートする操作そのものに直接対応、新しい依存の追加判断は不要

知見177の訂正作業の次に、`UiPath/skills`公式リポジトリのStudio実機
ground-truthコーパス(`UiPath.UIAutomation.Activities/25.10/
LoadImage.xaml`)+実機3件(`cameronmcnz/uipath-tutorials`・
`pdmorale/OCR_Statistics`・`tosigoto/UiPath-SimpleOCR`、いずれもOCR
活動(Tesseract/Google Vision等)への入力として使われる文脈)で
`ui:LoadImage`(GitHub code searchで58件ヒット)を調査した。確認した
構成は`FileName`(画像ファイルパス)+`Image`(出力、`UiPath.Core.
Image`型)+`DisplayName`のみ——`ContinueOnError`はground-truth・
実機のどちらでも一度も確認できなかった。

`FileName`で指定したファイルから画像を読み込み`Image`へ代入すると
いう意味論は、Pythonの標準的な画像処理ライブラリPillow
(`PIL.Image.open()`)がサポートする操作そのもの——本トランスパイラが
新しい依存を追加判断する必要は無い。`pad_codegen/actions/
ui_element.py`の`capture_as_image()`(pywinautoの画面キャプチャが
PIL Imageを返す)で、本プロジェクトが既にPillowを確認済みの依存として
使っていることを確認した上での判断。知見169(`taskkill`)・知見168
(`webbrowser`)のような「確認済み標準ライブラリへの直接対応」と同じ
判断パターンだが、今回は標準ライブラリではなく既存の確認済み
サードパーティ依存(Pillow)への対応という、わずかに異なるバリエー
ション。`ReadTextFile`(知見16)と同じ「targetへ代入する」パターン
(`_render_value_or_todo`を入出力両方に適用し、`todo`が1件でもあれば
代入文自体を生成しない、知見138の規約)を踏襲した。

実機XAML3件で`parse_activity()`+`_generate_node()`を実行し、
`memeImage = PIL.Image.open(_vb_cstr(file))`のような正しいコードが
生成されることを確認し、`_collect_imports`に`import PIL.Image`の
検出条件を追加して完全な`compile()`も確認した。回帰テスト追加
(`tests/test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`4件)、
UiPath関連テスト全740件通過、リポジトリ全体で全1784件通過。

## 179. `ui:SaveImage`+`ui:TakeScreenshot`を新規実装——REFramework公式テンプレートの例外時スクリーンショット保存フローを実機確認、`LoadImage`(知見178)の対になるPillow APIで対応

知見178の`ui:LoadImage`の対になる活動として、`ui:SaveImage`+`ui:
TakeScreenshot`を調査した。GitHub code searchでの素朴なヒット数
(それぞれ1060件/1096件)は`ui:SaveImageFile`等の長いタグ名への部分
一致を含むため正確ではないが、**`UiPath/Community.Activities`公式
リポジトリのREFrameworkテンプレート自身**(`Templates/ReFrameWork/
Framework/TakeScreenshot.xaml`——知見169の`KillAllProcesses.xaml`と
同じ「REFramework標準サブワークフロー」カテゴリ、例外発生時に
スクリーンショットを撮って保存する標準エラーハンドリングフロー)で
使われている、という最高水準の確証を得た。実機3件(`mihhdu/
Enhanced-REFramework`・`PacktPublishing/Robotic-Process-Automation-
Projects`・`spritlesoftware/Uipath-RPA-AutomationProjects`)+
`UiPath/skills`公式ground-truthコーパス(`SaveImage.xaml`)でも同じ
構成を確認した。

`ui:SaveImage`は`FileName`+`Image`+`DisplayName`のみ(`LoadImage`と
完全に同一の属性構成)。`Image`(既存のPIL Imageオブジェクト変数)を
`FileName`で指定したパスへ保存する意味論は、Pillowの`Image.save()`
(`LoadImage`の`PIL.Image.open()`と対になる標準API)が直接対応する。

`ui:TakeScreenshot`は`Target`(セレクタ、実機の大半は`{x:Null}`)+
`WaitBefore`(`DelayBefore`とは別名の未確認属性、実機で非`{x:Null}`
の値を一度も確認できず)+`Screenshot`(出力)+`DisplayName`。`Target`
が`{x:Null}`の場合は「画面全体」を意味し、Pillowの`ImageGrab.grab()`
(引数無しで仮想スクリーン全体をキャプチャする標準API)が直接対応
する。セレクタが設定されている場合はpywinautoの`capture_as_image()`
(`base_wrapper.py`で確認済み、`LoadImage`のdocstringで言及した
`pad_codegen`側の既存利用と同じ確認済み依存)が対応する。`WaitBefore`
は名前が`DelayBefore`と違う以上、同一視は安全な仮定ではないため
意味論未確認として非`{x:Null}`時は`# TODO`へ倒す。

実機XAML3件(公式REFrameworkテンプレート本体を含む)で
`generate_python()`+`compile()`を実行し、`screenshot = PIL.
ImageGrab.grab()`+`screenshot.save(io_FilePath)`(Target省略時)、
`Desktop(...).window(...).capture_as_image()`+`.save(...)`(セレクタ
指定時)の両方が正しく生成されることを確認した。回帰テスト追加
(`tests/test_uipath_dsl.py`3件・`tests/test_uipath_codegen.py`8件)、
UiPath関連テスト全750件通過、リポジトリ全体で全1795件通過。

**本tickで調査し実装を見送ったもの(今後の調査候補へ記録)**:
`FilterDataTable`(GitHub code searchで1554件ヒット)・
`AddDataColumn`(856件)・`RemoveDataColumn`(271件)・
`SortDataTable`(285件)・`MergeDataTable`(318件)というDataTable
操作系の活動群を検討したが、本トランスパイラの`DataTable`表現が
活動ごとに非統一(`BuildDataTableNode`は常に空の`[]`、`ExcelReadRange`
は`AddHeaders=True`なら`[dict(zip(header, row)) for row in rows]`・
`False`なら`[list(row) for row in rows]`——知見115)で、かつ変数の
生成元を跨いだ型追跡(フロー解析)を本トランスパイラは行わないため、
「このDataTable変数が実際にどちらの表現か」を活動単体の情報からは
判断できない。列名でのフィルタ・列の追加/削除といった操作は実行時
表現(dict行か素のlist行か)を前提にせざるを得ず、確認なしに前提を
置くことは本調査全体の「でっち上げない」方針に反するため見送った。
着手するには`DataTable`表現の統一(または変数ごとの表現追跡)という
より大きなアーキテクチャ上の前提作業が必要。

## 180. `ui:GetOCRText`を新規実装——`OCREngine`デリゲートのタグが`ui:GoogleOCR`(UiPath公式ドキュメントで「Tesseract OCR」と確認)の場合のみ既存確認済み依存`pytesseract`で対応

知見179の`ui:TakeScreenshot`/`ui:SaveImage`で整えたPillow系の画像
パイプラインを踏まえ、OCR系の活動`ui:GetOCRText`(`UiPath/skills`
公式リポジトリのStudio実機ground-truthコーパス+実機4件
(`cameronmcnz/uipath-tutorials`・`PacktPublishing/Robotic-Process-
Automation-RPA-for-Developers`・`DongJoonHan/RPA`)で確認)を調査
した。`OCREngine`プロパティが`ActivityFunc`デリゲート(`Argument`は
常にキャプチャした`Image`)で別のOCR活動をラップする、UiPathの
「OCR Engine選択」アーキテクチャになっている。

実機で遭遇した興味深い罠: ラップされた活動のタグは`ui:GoogleOCR`
だが、実機の`DisplayName`は`"Tesseract OCR"`になっている例を複数
確認した——これはGoogle Cloud Vision APIへの誤誘導ではなく、
UiPath公式ドキュメント(docs.uipath.com/activities/other/latest/
ui-automation/google-ocr、WebSearchで確認)で明記されている歴史的な
命名の名残だと判明した。内部クラス名`UiPath.Core.Activities.
GoogleOCR`のまま、ドキュメント上は「Tesseract OCR Engine 4.0を使用」
と明記されている——Google Cloud Vision APIを使う活動は
`GoogleCloudVisionOCR`という**別の**タグ名で存在する。知見38の
`role`属性の教訓(UiPathの語彙とpywinautoの語彙が一致する保証は無い)
と同じ種類の罠だが、今回はタグ名そのものの意味が実際の実装と
ズレているという、より根本的なレベルの罠だった——`DisplayName`
(人間が見るラベル、自由に変更可能)ではなく活動タグ名そのもの
(`node.tag`)で判定する実装にしたことが、たまたまこの罠を回避
できた理由(`DisplayName`文字列マッチングで実装していたら、
`DisplayName`を変更された実機XAMLで誤判定していた可能性がある)。

`GoogleOCR`(=Tesseract OCR)と確認できた場合のみ、本プロジェクトが
既に実機VM検証済みの依存`pytesseract`(`tests/test_ocr_fallback.py`
——notepadへの入力文字列を実際にOCRで読み取れることを実機確認済み)
が直接対応する——新しい依存の追加判断は不要。`Language`(UiPath公式
ドキュメントが明記する`tessdata`言語コード接頭辞、例: `"eng"`)は
`pytesseract.image_to_string(img, lang=...)`の`lang`引数と全く同じ
語彙のため信頼して渡せる。画像の前処理を変える属性(`Scale`/
`Profile`/`AllowedCharacters`/`DeniedCharacters`/`Invert`/
`ComputeSkewAngle`/`FilterRegion`)が既定値から外れている場合、
`ExtractWords`/`WordsInfo`(単語位置情報、未モデル化)が使われている
場合、`GoogleOCR`以外のタグ(`MicrosoftOCR`——実機71件確認、Windows
OCR API、Tesseractとは別のエンジン——等)の場合は`# TODO`へ倒す。
`Target`が`{x:Null}`の場合は`TakeScreenshot`(知見179)と同じ
`PIL.ImageGrab.grab()`で画面全体を対象にする。

実装中、内部のOCR活動要素の`Scale`/`Profile`/`Invert`/
`ComputeSkewAngle`/`ExtractWords`属性を素朴に`_attr()`で取得した
ところ、実機`cameronmcnz/uipath-tutorials`の`Scale="{x:Null}"`が
そのまま文字列として残り`node.scale not in (None, "1")`の判定を
誤って通過する(知見163・172と同種の`{x:Null}`正規化漏れ)バグを
実機確認で発見・即修正した——フラット文字列属性(`Expr`ではなく
プレーンな`str | None`で保持する属性)向けの新しいヘルパー
`_attr_or_none()`を追加し、既存の`_attr_expr`(`Expr`へ変換する
属性向け)とは別経路として整理した。

実機XAML3件+合成テストで`generate_python()`+`compile()`を実行し、
`GoogleOCR`+既定値の実例(`invoiceNumber = pytesseract.image_to_
string(_img)`)、`Scale`/`Profile`が既定値から外れる実例(正しく
`# TODO`)の両方を確認した。回帰テスト追加(`tests/test_uipath_dsl.py`
3件・`tests/test_uipath_codegen.py`10件)、UiPath関連テスト全741件
通過、リポジトリ全体で全1807件通過。

## 181. `ui:AddDataRow`(GitHub code searchで2120件ヒット——`BuildDataTable`直後に続く定番パターンとして極めて高頻度)を新規実装——`DataTable`表現の非統一(知見179)に影響されない、数少ない「表現非依存で安全な」DataTable操作

知見180の`ui:GetOCRText`に続き、知見179で見送ったDataTable操作系の
活動群を再検討する中で、`ui:AddDataRow`(GitHub code searchで2120件
ヒット——`BuildDataTable`(既存)の直後に続く定番パターンとして、本
調査で遭遇した中でも最高頻度級)を発見した。実機4件(`cameronmcnz/
uipath-tutorials`・`allenlooplee/RPABook`・`piyushagarwal08/JU-
Notes`)で確認した構成は`ArrayRow`(VB配列リテラル、例: `[{"Hello
World", -1}]`)+`DataRow`(既存の`System.Data.DataRow`オブジェクト
参照、実機で一度も非`{x:Null}`の値を確認できず意味論未確認)+
`DataTable`(追記先の既存DataTable変数)+`DisplayName`。

知見179で`FilterDataTable`等を見送った理由(`DataTable`表現が活動
ごとに非統一で、活動単体の情報から実行時表現を判断できない)を
本活動にも当てはめて検討したが、`AddDataRow`は**既存のDataTable
変数の内容を一切読まない**(列名・既存の行表現を全く参照せず、
単純に新しい行を末尾に追加するだけ)という点で根本的に違うと判明
した——Pythonの素の`list.append(...)`は保持している要素が何であれ
(dict行でもlist行でも空リストでも)安全に呼べるため、`DataTable`
変数がどちらの表現であっても正しく動作する。これは「活動単体の
情報から実行時表現を判断できない」という問題が、読み取り系の操作
(フィルタ・列追加等、列名で既存の行にアクセスする必要がある)にのみ
当てはまり、追記のみの操作には当てはまらないという、知見179の判断
をより正確に絞り込む発見だった。

`ArrayRow`自体の変換も新しい実装は一切不要だった——`uipath_expr`
モジュールの`ArrayLiteral`(VBの`{val1, val2, ...}`配列リテラル構文)
が既に`render.py`の`_render_node`で`[item1, item2, ...]`という
Pythonリストへ変換する確立済みの経路として存在しており
(いつ追加されたか本調査では未確認——既存の対応範囲の再発見)、
複雑な式(`DateTime.Today.ToString(...)`・文字列結合・`If(...)`三項
演算子等、実機`allenlooplee/RPABook`で確認)を含む配列リテラルも
既存のVB式パーサー/レンダラーがそのまま正しく処理することを実機
XAMLで確認した。

実機XAML3件で`parse_activity()`+`_generate_node()`を実行し(2件は
`generate_python()`全体の`compile()`も確認、3件目は知見177で確認
済みの意図的な設計(未対応の`If`条件式でコード生成全体を失敗させる)
により無関係な別の活動でスキップ)、`MyDataTable.append(['Hello
World', -_vb_num(1)])`のような正しいコードが生成されることを確認
した。回帰テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
test_uipath_codegen.py`5件)、UiPath関連テスト全746件通過、
リポジトリ全体で全1813件通過。

## 182. `ui:RemoveDataRow`(`AddDataRow`知見181の正反対)を新規実装——`RowIndex`によるインデックス削除を実機確認、`Literal`を素のPython文字列のままlistインデックスへ使うと`TypeError`になる実機バグを発見・修正

知見181の`ui:AddDataRow`の対になる活動として`ui:RemoveDataRow`
(`UiPath/skills`公式リポジトリのStudio実機ground-truthコーパス
(`UiPath.System.Activities/25.10/RemoveDataRow.xaml`)+実機5件
(`lin8231/762-impl`・`samaypatel27/Stock-Market-Scrapper`・
`UiPath-Services/OrchestratorManager`)で確認)を調査した。確認した
構成は`DataTable`+`Row`(既存の`DataRow`オブジェクト参照)+
`RowIndex`(整数インデックス)+`DisplayName`。実機で非`{x:Null}`の
`Row`の実例は複雑なLINQ式(`io_UsersData.AsEnumerable().Where
(Function(Row) Convert.ToInt64(Row("ID")) = UserID).First()`)
のみで、`uipath_expr`が未対応のため安全に`# TODO`へ倒れることを
確認した。`RowIndex`の実例は2件とも`"0"`——「読み込んだヘッダー行を
削除する」という、`AddHeaders=False`で読み込んだDataTableの先頭行
(ヘッダー)を除去する定番パターンだった。

知見181と同じ理由で、`RowIndex`によるインデックス削除
(`del {data_table}[{row_index}]`)は`DataTable`変数の実行時表現を
一切問わない安全な操作だと判断したが、実装中に実機XAMLでの動作確認
(`compile()`だけでなく生成コードの意味そのものを吟味する)によって
重大な実機バグを発見した——`RowIndex="0"`は知見2・5の規約により
`Literal(value="0")`(常に文字列として保持)としてパースされ、
これを`render_expr`でそのまま使うと`del {data_table}['0']`という
Pythonコードが生成される。Pythonのlistは文字列インデックスを
受け付けず`TypeError: list indices must be integers or slices, not
str`で即座にクラッシュする——`compile()`(構文チェックのみ)では
検出できず、実行してみて初めて発覚する種類のバグだった。

`_vb_num`(既存の算術変換ヘルパー)は`float`を返すため代用できない
(`list[0.0]`も同じ`TypeError`になる)。正しい解決策は、VBの
`CInt()`関数呼び出しが既に使っている確認済みの整数変換経路
(`render.py`の`_render_func_call`、知見52・53で確定した
`round(_vb_cdbl(x))`——`CInt`は切り捨てではなく銀行丸めで、
Pythonの`round()`の既定動作と一致することを確認済み)を、
`RemoveDataRow`のコード生成側から直接呼ぶことだった——ユーザーが
明示的に`CInt(...)`と書いていないVB式でも、「Pythonの整数が必要な
コンテキストで使う」という生成側の都合で同じ確認済みの変換を
再利用する、これまでとは違う使い方(既存のVB関数呼び出し変換を
コード生成側の都合で直接呼ぶ初めての例)。`_collect_imports`の
`_vb_cdbl(`検出条件(既存)がそのまま効くため、新しい`import`検出
ロジックは不要だった。

実機XAML3件で`parse_activity()`+`_generate_node()`を実行し、
`del t[round(_vb_cdbl('0'))]`が正しく生成されることを修正後に確認
した(合成データでの実行結果も手動確認済み)。回帰テスト追加
(`tests/test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`7件)、
UiPath関連テスト全753件通過、リポジトリ全体で全1821件通過。

## 183. `ui:GetRowItem`を新規実装——`ColumnIndex`は実行時`isinstance`分岐で`DataTable`の両表現(dict行/list行)に対応、`ColumnName`は実機6件全ての実例に合わせてdict行を前提にした直接アクセス

知見182の`ui:RemoveDataRow`に続き、同じ`UiPath.System.Activities`
名前空間のDataTable操作系活動`ui:GetRowItem`(`UiPath/skills`公式
リポジトリのStudio実機ground-truthコーパス+実機6件(`cameronmcnz/
uipath-tutorials`・`allenlooplee/CloudOcrActivitiesPack`・
`ShonHarsh/RPADev-...`)で確認)を調査した。既存の1行(`Row`、通常は
`ForEach`のループ変数)から1つの値を取り出す活動で、列の指定方法は
`Column`(既存の`DataColumn`オブジェクト参照、未モデル化)/
`ColumnIndex`(整数)/`ColumnName`(文字列)の3種類——実機6件**全て**
が`ColumnName`を使っており、`ColumnIndex`の実例は本調査で一度も
確認できなかった。

`AddDataRow`(知見181)/`RemoveDataRow`(知見182)が「既存の行の内容を
読まずに済ませる」ことで`DataTable`表現の非統一を回避したのとは違い、
`GetRowItem`は行の**内容を読む**必要がある——知見179で検討した
読み取り系操作と同じ種類の課題に正面から向き合うことになった。ここで
2つの異なる解決策を使い分けた:

- **`ColumnIndex`**(位置によるアクセス): `isinstance(row, dict)`の
  実行時分岐で、dict行なら`list(row.values())[idx]`(位置で値を取る)
  ・list行なら`row[idx]`(素の添字アクセス)のいずれかを実行時に選ぶ
  ——静的な型追跡を一切せず、生成コード自身が両方の表現に対応する、
  `AddDataRow`/`RemoveDataRow`とは別の「両方に対応するコードを生成
  する」という新しい安全策。
- **`ColumnName`**(列名によるアクセス): `row[column_name]`という
  dict行前提の直接アクセス。実際のUiPath`DataTable`は常に列名を持つ
  ため、本トランスパイラがdict行として表現した場合にのみ正しく動作
  する——list行表現の場合は`TypeError`で実行時に大きく失敗する。
  これは知見177の「でっち上げた値で静かに間違えるより、失敗する方が
  安全」という方針をそのまま適用した判断——`ColumnName`は実機6件
  全てで使われている以上、常に`# TODO`へ倒すと活動自体が実質無意味
  になる一方、`list(row)`から列名でマッチする値を推測するような
  でっち上げは論外。「正しければ動く、間違っていれば即座に分かる
  形で失敗する」という中間の解を選んだ。

実機XAML3件(うち1件はC#式言語プロジェクト——知見129の既存の限界で
`Row`が未対応の`CSharpValue`形になり安全に`# TODO`へ倒れることを
確認)+合成テストで`generate_python()`+`compile()`を実行し、両方の
`ColumnIndex`経路(dict行/list行)の実行結果も手動確認した。回帰
テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
test_uipath_codegen.py`10件)、UiPath関連テスト全764件通過、
リポジトリ全体で全1830件通過。

## 184. `ui:ClearDataTable`+`ui:OutputDataTable`を新規実装——前者は最も単純な「表現非依存で安全な」操作、後者はPython標準csvモジュールでCSV変換を近似(GetFullTextと同じ「大枠は確信、書式の細部はWARNING」判断)

知見183の`ui:GetRowItem`に続き、`UiPath.System.Activities`名前空間の
残るDataTable操作系活動を調査した。`UiPath/skills`公式リポジトリの
Studio実機ground-truthコーパスで`ClearDataTable.xaml`/
`OutputDataTable.xaml`の両方を発見し、実機(`MaxineXiong/Scraping-
PDF-Invoices-with-RPA`・`jeffdnganga/DSRIncentivesPostingPerformer`・
`piyushagarwal08/JU-Notes`・`vajrang-b/UiPathIn30Days`)でも確認した。

`ui:ClearDataTable`は`DataTable`のみ——`DisplayName`以外に属性が
一切無い、本調査で遭遇した中でも最も単純な活動の1つ。`AddDataRow`
(知見181)/`RemoveDataRow`(知見182)と同じ理由で、`list.clear()`は
`DataTable`変数の実行時表現を一切問わない安全な操作(要素を読む
必要すら無い、「表現非依存で安全な」操作の中でも最も単純な例)。

`ui:OutputDataTable`は`DataTable`+`Text`(出力)のみ。UiPath公式
ドキュメント(docs.uipath.com、WebSearchで確認)によれば
`DataTable`をCSV形式の文字列へ変換する活動だが、区切り文字・引用符の
扱い・改行コードといった厳密な書式の詳細はドキュメントで確認でき
なかった——知見159の`GetFullText`(「exact UI Automation API behind
'Get Full Text' not independently confirmed」という`# WARNING`)と
同じ判断パターンを適用し、Python標準の`csv`モジュール(確認済みの
標準ライブラリ)で近似しつつ、厳密な書式が未確認であることを
`# WARNING`コメントに明記した。`GetRowItem`(知見183)と同じ
`isinstance(row, dict)`の実行時分岐で`DataTable`の両表現(dict行の
場合は先頭行のキーをヘッダー行として出力・list行の場合はヘッダー
無しで値のみ出力)に対応する、3つ目の「実行時分岐で両表現に対応する」
実装パターン。

実機XAML4件で`parse_activity()`+`_generate_node()`+`_collect_imports`
を実行し、`generate_python()`+`compile()`を確認した。合成データで
3パターン(dict行/list行/空リスト)全ての実行結果も手動確認し、
いずれも意味の通るCSV文字列(`'a,b\r\n1,2\r\n3,4\r\n'`等)が生成される
ことを確認した。回帰テスト追加(`tests/test_uipath_dsl.py`2件・
`tests/test_uipath_codegen.py`9件)、UiPath関連テスト全775件通過、
リポジトリ全体で全1839件通過。

## 185. `ui:ReadCsvFile`+`ui:WriteCsvFile`を新規実装(`UiPath.Excel.Activities`名前空間)——`csv.DictReader`/`csv.writer`で直接対応、`OutputDataTable`(知見184)の`isinstance`分岐パターンを`WriteCsvFile`で再利用

知見184の`ui:OutputDataTable`で確立したPython標準`csv`モジュールに
よるCSV対応を踏まえ、同じファミリーの`ui:ReadCsvFile`/`ui:
WriteCsvFile`(`UiPath.Excel.Activities`名前空間)を調査した。
`UiPath/skills`公式リポジトリのStudio実機ground-truthコーパス
(`UiPath.Excel.Activities/3.4/ReadCsvFile.xaml`/`WriteCsvFile.xaml`)
+実機4件(`cameronmcnz/uipath-tutorials`・`allenlooplee/RPABook`・
`HarshadRanganathan/uipath-learning`)で確認した。

`ui:ReadCsvFile`は`FilePath`+`DataTable`(出力)+`PathResource`
(Integration Service連携用リソース、未モデル化)+`Delimitator`
(UiPathの実際のAPI表記そのまま——`Delimiter`ではなく`Delimitator`、
実機確認した値は全件`"Comma"`)+`Encoding`(実機で一度も非
`{x:Null}`の値を確認できず意味論未確認)。`AddHeaders`相当の属性が
存在しない——CSVの1行目を常にヘッダーとして扱うという意味論だと
判断し、`csv.DictReader`(Python標準の`csv`モジュール)が直接対応
する。これは`ExcelReadRange`の`AddHeaders=True`時(知見115)と同じ
dict行表現に揃える判断。

`ui:WriteCsvFile`は`ReadCsvFile`の正反対で、`FilePath`+`DataTable`+
`AddHeaders`(実機全件`"True"`)+`Delimitator`(実機全件`"Comma"`)+
`ShouldQuote`(ground-truthの既定値`"True"`、実機では一度も明示的に
シリアライズされているのを見なかった)+`Encoding`。`OutputDataTable`
(知見184)で確立した`isinstance(data_table[0], dict)`の実行時分岐
パターンをそのまま再利用し、dict行の場合のみ`AddHeaders`に従って
ヘッダー行を出力し、list行の場合は列名を持たないためヘッダー無しで
値のみを出力する(`AddHeaders`の値に関わらず——でっち上げた列名を
書かない保守的な縮退、`# WARNING`で明記)。1つの判断パターン
(`isinstance`分岐)が複数の活動(`GetRowItem`知見183・
`OutputDataTable`知見184・`WriteCsvFile`本件)で再利用された、本調査
全体を通じて最も再利用性の高い実装パターンになった。

実機XAML5件(`ReadCsvFile`3件+`WriteCsvFile`2件)で`generate_
python()`+`compile()`を確認し、合成データで書込→読込のラウンド
トリップ(`{'name': 'alice', 'age': '30'}`等)が正しく動作することも
手動確認した。回帰テスト追加(`tests/test_uipath_dsl.py`2件・
`tests/test_uipath_codegen.py`16件)、UiPath関連テスト全793件通過、
リポジトリ全体で全1853件通過。

## 186. `ui:InvokePowerShell`(GitHub code searchで337件ヒット)を新規実装——`PowerShellProcess="PowerShellCore"`の場合のみ`subprocess.run(["pwsh", "-Command", ...], check=True)`で対応、`check=True`でContinueOnErrorの既定動作に揃える

知見185のCSV系活動群から離れ、`ui:InvokePowerShell`を調査した。
`UiPath/skills`公式リポジトリのStudio実機ground-truthコーパスでは
`ExecutePowerShell`という別名で存在する(`ui:ExecutePowerShell
CommandText="{x:Null}" ... IsScript="False" PowerShellProcess=
"PowerShellCore"`)が、実機では一度も`ExecutePowerShell`タグに
遭遇できず、全て`InvokePowerShell`タグだった——同種の活動名が
バージョン間で変わる現象(知見153・158・161と同じ系統、Classic/
Modernの世代差の可能性があるが未確認)。実機3件
(`cameronmcnz/uipath-tutorials`・`nestorzamili/RPA-Grafana-Kibana`・
`solankidrashti2965/Invoice-OCR-Automation`)で確認した構成は
`CommandText`(実行するPowerShellコマンド/スクリプト)+`IsScript`+
`PowerShellProcess`(実機確認した値は全件`"PowerShellCore"`)+
`ContinueOnError`+`Parameters`/`PowerShellVariables`(両方とも実機
確認した全例で空の`scg:Dictionary`——パラメータ渡しは未使用)。
`Input`/`Errors`/`PipelineOutput`は実機のどの例でも一度も
シリアライズされていなかった。

`PowerShellProcess="PowerShellCore"`の場合、`subprocess.run(["pwsh",
"-Command", command_text], check=True)`が直接対応する——`pwsh`は
PowerShell Core (7+)の確認済み標準実行ファイル名。`check=True`を
明示的に付けたのは本活動固有の判断——`subprocess.run()`は既定で
非ゼロ終了コードを例外にしないため、`ContinueOnError`の既定値
(`None`/`False`、エラーを伝播させてワークフローを停止する)と
食い違う。でっち上げた「常に成功」という挙動より、知見177と同じ
「エラー時は例外で失敗する方が安全」という判断で`check=True`を
付けた——`KillProcess`(知見169)の`subprocess.run()`呼び出しには
`check`を付けていなかったことに気づき、本活動で初めて意識的に
この判断を行った(`KillProcess`の方は対象プロセスが既に存在しない
場合でも正常終了するコマンドのため、この違いが問題にならなかった
だけで、後から振り返ると`check=True`を検討する価値があった可能性
がある——今回は新規実装のみに留め、既存の`KillProcess`の挙動変更は
スコープ外として見送った)。

`Parameters`/`PowerShellVariables`の空判定(`scg:Dictionary`の子
要素数)のために新しいヘルパー`_dict_property_has_entries()`を追加
した——`<X.PropName><scg:Dictionary .../></X.PropName>`形のプロパティ
が実際に何らかのエントリを持つかどうかを判定する、本調査で初めて
遭遇した「辞書プロパティの空判定」という新しいパーサーパターン。

実機XAML3件で`generate_python()`+`compile()`を確認した(1件は
`PowerShellProcess`未設定のため安全に`# TODO`へ倒れ、1件は明示的な
`ContinueOnError="False"`で安全に`# TODO`へ倒れることも確認)。
回帰テスト追加(`tests/test_uipath_dsl.py`2件・`tests/
test_uipath_codegen.py`9件)、UiPath関連テスト全804件通過、
リポジトリ全体で全1863件通過。

## 187. `ui:RetryScope`(GitHub code searchで3280件ヒット)を新規実装——公式REFrameworkテンプレートのTryCatch+Rethrowパターンから「本体が例外無しで完了するまで再試行」という意味論を確立、本調査初の制御フロー系新規ノード型

知見186の`ui:InvokePowerShell`に続き、`ui:RetryScope`
(`UiPath.System.Activities`、GitHub code searchで3280件ヒット——
本調査で遭遇した活動の中でも最高水準の頻度)を調査した。`UiPath/
skills`公式リポジトリのREFramework標準サブワークフロー資産
(`assets/stripped/SetTransactionStatus.xaml`)で実際に使われている
ことを確認した、知見169・179と同じ最高水準の確証を得た制御フロー系
活動——これまでの`GetTextNode`/`ClickNode`等のリーフ活動とは違い、
`TryCatchNode`/`WhileNode`と同種の「本体(`body`)を持つノード型」を
本調査で初めて新規実装することになった。

構造は`ActivityBody`(`ActivityAction`→`Sequence`、他のスコープ活動と
同じ構造)+`NumberOfRetries`(整数)+`RetryInterval`(TimeSpan)+
`Condition`(`ActivityFunc<Boolean>`)+`LogRetriedExceptions`/
`RetriedExceptionsLogLevel`。公式REFrameworkテンプレートでの実際の
使い方を読み解くと、`ActivityBody`内部に`TryCatch`+`Rethrow`
(`Catch`節でログを出してから明示的に再スローする、実機確認済みの
構造)を置き、`Condition`は空の`ActivityFunc`(中身が一切無い)のまま
にする——これは「本体が例外無しで完了するまで、最大
`NumberOfRetries`回まで再試行し、全回失敗したら最後の例外を伝播
させる」という最もシンプルで確認済みの意味論だと判断した。

もう一方の実機例(`liamsrowley/UiPath-REFramework-
CalculateClientSecurityHash`)ではModern活動(`uix:NCheckState`等)を
使い、`Condition`に実際の要素状態チェックを含む非空の実装・
`RetryInterval="00:10:00"`(再試行間隔の明示的な待機)を確認した——
これはより複雑な「値ベースの再試行条件」パターンで、正確な意味論が
未確認のため`# TODO`へ倒す(`Condition`の空判定には`_activity_func_
has_body()`という新しいヘルパーを追加した)。

実装は`for`+`try/except`のPythonループで表現する——`_retry_max =
round(_vb_cdbl(number_of_retries))`で整数変換(知見182・183と同じ
`CInt`相当の確認済み経路)した後、`for _retry_attempt in
range(_retry_max): try: <body>; break except Exception: if
_retry_attempt == _retry_max - 1: raise`という構造。`TryCatchNode`と
同じ`invoke_resolver`/`out_arg_resolver`を本体生成に伝播させる必要が
あり(本体内の`Invoke Workflow File`解決のため)、`_generate_retry_
scope`の関数シグネチャを`_generate_try_catch`と同じ形に揃えた。

実機XAML2件(公式REFrameworkテンプレート含む)+合成テストで
`parse_activity()`+`_generate_node()`+`compile()`を実行し、合成
データで実際にPythonとして`exec()`し、「2回目の試行で成功する」
「全て失敗して最後の例外が伝播する」の両シナリオが正しく動作する
ことを手動確認した(公式テンプレート側は本体内の`in_Config(...)`
という別の未対応関数呼び出しにより`# TODO`へ倒れたが、`RetryScope`
自体の構造解析・`NumberOfRetries`抽出・`Condition`空判定は正しく
動作することを確認済み)。回帰テスト追加(`tests/test_uipath_dsl.py`
2件・`tests/test_uipath_codegen.py`6件)、UiPath関連テスト全812件
通過、リポジトリ全体で全1871件通過。

## 188. `ui:MoveFile`+`ui:PathExists`を新規実装——`MoveFile`は`CopyFile`(知見117)の正反対として実装を丸ごと再利用、`PathExists`は`PathType`の値(File/Folder)で`os.path.isfile()`/`isdir()`を正確に切り分け

知見187の`ui:RetryScope`から離れ、ファイルシステム操作系の基本活動
`ui:MoveFile`(GitHub code searchで575件ヒット)+`ui:PathExists`
(558件ヒット)を調査した。`UiPath/skills`公式リポジトリのStudio実機
ground-truthコーパス+実機4件(`PacktPublishing/Robotic-Process-
Automation-Projects`・`cameronmcnz/uipath-tutorials`・
`cristinegulescu/startUiPathFromSalesforce`)で確認した。

`ui:MoveFile`は`ui:CopyFile`(知見117)と**完全に同一の属性構成**
(`Path`+`Destination`+`Overwrite`+`DestinationResource`/
`PathResource`+`ContinueOnError`)だった——実装は`CopyFile`の
decline判定・移動先ディレクトリ解決ロジック・`Overwrite="False"`時の
事前存在チェックをそのまま丸ごと再利用し、最後の1行だけ`shutil.
copy()`→`shutil.move()`に変える形で済んだ。移動先が既に存在する場合
の`shutil.move()`自体の挙動はOS・Pythonバージョンに依存する
(Windowsの`os.rename()`は上書きに失敗するが、`shutil.move`内部の
フォールバック経路で上書きされる場合がある)ため、このプラット
フォーム依存の挙動に頼らず、`CopyFile`と同じ明示的で予測可能な
事前チェックに揃えた判断。

`ui:PathExists`は`Path`+`Exists`(出力)+`Resource`(未モデル化)+
`PathType`——実機2件で確認した値は`"File"`/`"Folder"`の2種のみ。
`os.path.exists()`のような種別を問わない汎用チェックではなく、
`PathType="File"`は`os.path.isfile()`・`"Folder"`は`os.path.isdir()`
という、UiPathが明示的に区別している意味論に正確に対応させた——
種別を無視した近似(`os.path.exists()`だけで済ませる)ではなく、
確認できた語彙の範囲内で忠実に対応する判断。

実機XAML4件で`generate_python()`+`compile()`を確認した
(`MoveFile`は`Overwrite="True"`/`"False"`の両方、`PathExists`は
`PathType="File"`/`"Folder"`の両方を実機で確認)。回帰テスト追加
(`tests/test_uipath_dsl.py`4件・`tests/test_uipath_codegen.py`16件)、
UiPath関連テスト全828件通過、リポジトリ全体で全1887件通過。

## 189. `ui:DeleteFileX`+`ui:DeleteFolderX`を新規実装——GitHub code search上は「ui:DeleteFile」という無印タグに見えたが実機は全件「X」付き、部分一致検索の罠を実機ゼロ件確認で正式に裏付け

知見188の`ui:MoveFile`/`ui:PathExists`に続き、ファイルシステム操作系
の基本活動`ui:DeleteFile`(素朴なGitHub code searchで508件ヒット)+
`ui:DeleteFolder`(173件ヒット)を調査した。実際にダウンロードした
実機XAMLを確認すると、タグは全件`ui:DeleteFileX`/`ui:DeleteFolderX`
(「X」付き)だった——検索語`"ui:DeleteFile"`が`"ui:DeleteFileX"`への
部分一致でヒットしていたという、知見150(TakeScreenshot/SaveImage)
と同種の罠。今回は`"<ui:DeleteFile "`(末尾スペース付き完全一致)で
GitHub code search自体が0件を返すことを確認し、「無印タグは実在
しない」と正式に裏付けた——単に実機サンプルで1つも見なかっただけで
なく、検索エンジン自体の集計で裏を取った点が今回の新しい確認手法。

`ui:`名前空間のまま(Modern活動の`uix:`ではない)、Target/セレクタの
概念を一切持たない単純な属性構成——`DeleteFileX`は`Path`のみ
(`UiPath/skills`公式リポジトリのStudio実機ground-truthコーパス+
実機2件(`vajrang-b/UiPathIn30Days`・`andumorie/uipath-face-
recognition-framework`)で確認)、`DeleteFolderX`は`Path`+
`Recursive`(ground-truthの既定値`"True"`、実機確認した全例も
`"True"`)。

`DeleteFileX`は`os.remove()`、`DeleteFolderX`の`Recursive="True"`は
`shutil.rmtree()`(フォルダとその内容を再帰的に削除)・`"False"`は
`os.rmdir()`(空のフォルダのみ削除、内容がある場合は`OSError`で
失敗する——でっち上げた「強制的に空にする」処理はしない)——いずれも
Python標準の確認済みAPI。`Recursive="False"`の実機例は確認できな
かったが、`os.rmdir()`という対応が明確なため値を問わず両方対応した
(知見117の`CopyFile`の`Overwrite`と同じ、両方の確認済み値に対応する
判断)。

副産物として、実機XAML調査中に`ui:ForEachFolderX`(サブフォルダを
反復する活動)という未調査の活動も発見した——今回のスコープ外として
今後の調査候補に追加する。実機XAML4件で`generate_python()`+
`compile()`を確認(2件は無関係な既存の限界(C#式言語プロジェクト・
未対応関数呼び出し)で安全に`# TODO`へ倒れることも確認)、合成データ
で`Recursive`両方の値の成功パスも確認した。回帰テスト追加(`tests/
test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`14件)、UiPath
関連テスト全844件通過、リポジトリ全体で全1897件通過。

## 190. `ui:ForEachFileX`+`ui:ForEachFolderX`を新規実装——`CurrentFile`/`CurrentFolder`をパス文字列として表現、`render.py`に新しい`.FullName`メンバ変換を追加、実装直後のテストで`_SAFE_BARE_MEMBERS`登録漏れによる実行時AttributeErrorを発見・即修正

知見189で発見した`ui:ForEachFolderX`(40件ヒット)+その兄弟活動
`ui:ForEachFileX`(GitHub code searchで738件ヒット——本調査で遭遇した
中でも高頻度)を実装した。`UiPath/skills`公式リポジトリのStudio
実機ground-truthコーパス+実機(`marcelocruzrpa/uipath-ai-skills`の
資産`PDFExtraction_Main.xaml`)で確認した構成は`Folder`+
`IncludeSubDirectories`/`IncludeSubFolders`+`OrderBy`(実機確認した
値は全件`"NameAscFirst"`)+`SkipFolderWithoutPermission`/
`SkipFoldersWithoutPermission`+`Body`——`ForEachNode`(知見5)とは違い
**2変数**のデリゲート(`ActivityAction<FileInfo, Int32>`、
`Argument1`=`CurrentFile`/`Argument2`=`CurrentIndex`)という、本調査で
初めて遭遇した複数デリゲート変数の構造。新しいパーサーヘルパー
`_parse_two_arg_delegate_vars()`を追加して対応した。

`CurrentFile`/`CurrentFolder`の表現方法が最大の設計判断だった——
`render_expr`のチェインメンバアクセス許可リスト(`_apply_chained_
property`)はメンバ名を問わず未知の名前を安全に拒否する(型情報を
持たないため)ため、`.NET FileInfo`/`DirectoryInfo`のリッチなオブ
ジェクトをでっち上げる代わりに、ファイルの絶対パス文字列
(`.FullName`と同じ値)として表現する最小限の設計を選んだ。
`IncludeSubDirectories`/`IncludeSubFolders`は`True`/`False`の両方に
`os.walk()`/`os.scandir()`(いずれもPython標準の確認済みAPI)で対応
した——再帰時は`os.walk()`の`dirnames`(各階層での直下の子フォルダ
のみを返す確認済みの挙動)を利用して、ルート自身を含まない全階層の
サブフォルダ/ファイルを列挙する。`OrderBy`が確認済みの`"NameAscFirst"`
以外・`SkipFolder(s)WithoutPermission="True"`(権限エラーの握り潰し、
未モデル化)の場合は`# TODO`へ倒す。

実機サンプル(`CurrentFile.FullName`という実際の使われ方を確認)に
対応するため、`render.py`の`_apply_chained_property`に新しい
`.FullName`(そのまま値を返す、パス文字列自体が既にFullName相当の
ため)というメンバ変換を追加した——`.FullName`自体は`FileInfo`/
`DirectoryInfo`以外の.NET型(`Type`・`Assembly`等)にも存在するため
本来は型文脈が必要な変換だが、本トランスパイラの対象範囲でそれらの
型が使われる実例は一度も確認していないという、既存の`.ToString`/
`.Length`(型を問わない判定)と同じ現実的なリスク判断を踏襲した。

実装直後のテスト実行で、`_apply_chained_property`に`.FullName`を
追加しただけでは実機サンプルの`CurrentFile.FullName`(括弧無しの
メンバアクセス連鎖)が変換されず、生成コードに`CurrentFile.FullName`
が**そのまま**残ってしまうバグを発見した——`compile()`(構文チェック
のみ)は通過するが、実行すれば`AttributeError: 'str' object has no
attribute 'FullName'`で確実にクラッシュする、知見182のRowIndexバグ
と同種の「構文的には正しいが実行すれば落ちる」バグだった。原因は
`render.py`の`_render_node`のIdent分岐(知見119: 括弧省略形のメンバ
アクセス連鎖は字句解析上1トークンとして吸収されるため、`_apply_
chained_property`とは別の、`_SAFE_BARE_MEMBERS`で許可された名前
のみを通す独立したゲートを持つ)が、`fullname`を`_SAFE_BARE_MEMBERS`
に登録していなかったため——`_apply_chained_property`自体にケースを
追加するだけでは、この手前のゲートを通過できず到達しなかった。
`_SAFE_BARE_MEMBERS`へ`"fullname"`を追加して即修正し、実機サンプル
で`CurrentFile.FullName`が正しく`CurrentFile`へ変換されることを
再確認した。

実機XAML1件(公式資産`PDFExtraction_Main.xaml`、再帰列挙+
`CurrentFile.FullName`使用)+合成テストで`generate_python()`+
`compile()`を確認し、実際のファイルシステムに対して非再帰/再帰/
フォルダ列挙の3パターン全ての実行結果も手動確認した(名前順ソート・
階層の正しさを含む)。回帰テスト追加(`tests/test_uipath_dsl.py`2件・
`tests/test_uipath_codegen.py`9件)、UiPath関連テスト全855件通過、
リポジトリ全体で全1906件通過。

## 191. `ui:RenameFileX`+`ui:RenameFolderX`+`ui:CreateFile`を新規実装——ファイルシステム操作系の最後の未実装活動群、`MoveFileNode`(知見188)と同様の既存ロジック再利用パターンを踏襲

知見189で確認した「`ui:DeleteFileX`/`ui:DeleteFolderX`等、`X`付きが
実在して無印タグは実在ゼロ」というファイルシステム操作系活動ファミリー
の調査の続きとして、`ui:RenameFileX`(GitHub code searchで123件ヒット)+
`ui:RenameFolderX`(同ファミリーの兄弟活動)+`ui:CreateFile`
(`UiPath.System.Activities`、266件ヒット——`DeleteFileX`等とは違い
非`X`形のまま実在することを確認)を実装した。`UiPath/skills`公式
リポジトリのStudio実機ground-truthコーパス+実機サンプル3件
(`KooBonchan/wine-bouti`の`RenameFileX`、`PakamTharunReddy/RPA`の
`RenameFolderX`、`piyushagarwal08/JU-Notes`の`CreateFile`)で構成を
確認した。

`RenameFileX`は`FilePath`+`NewName`+`KeepExtension`
(ground-truthの既定値`"True"`)+`FileResource`/`OutputFileResource`
(Integration Service連携用、未モデル化のため常に`# TODO`)。
`KeepExtension="True"`の場合、元のファイルの拡張子を`NewName`に
付加してから`os.rename()`で改名する——`os.path.splitext()`
(拡張子分離)+`os.path.dirname()`(ディレクトリ部分の保持)という
確認済みの標準的な組み合わせ。`RenameFolderX`は`FolderPath`+
`NewName`のみ(`KeepExtension`に相当する属性は無い——フォルダに
拡張子の概念が無いため)で、同じ`os.rename()`パターンに倒した。
`CreateFile`は`Path`(ディレクトリ)+`Name`(ファイル名)+`Output`
(出力、実機サンプルでは非`{x:Null}`の値を確認できなかった)+
`PathResource`(未モデル化)+`ContinueOnError`で、
`os.path.join(Path, Name)`で完全パスを組み立て、`open(path,
"w").close()`(空ファイルを作成する、Python標準の確認済み手法)で
作成する。

`CreateFile`の`Output`は、`ForEachFileX`(知見190)で確立した
「絶対パス文字列として表現する」パターンをそのまま再利用した——
`.NET`の`FileInfo`オブジェクトをでっち上げず、生成した完全パスの
文字列そのものを代入する。また、既存ファイルが既にある場合の
上書き挙動がUiPath実機と一致するかは確認できなかった(本調査の
対象外)ため、`CopyFile`/`MoveFile`(知見117・188)のような
`Overwrite`相当の属性自体がこの活動には無く、既存ファイルの扱いに
関する分岐を一切設けていない——「確認できないことは実装しない」
という方針をそのまま適用した。

3つとも実装パターン自体は新規性が低く、`MoveFileNode`(知見188、
`CopyFileNode`の決定木を再利用)と同じ「既存の確認済みロジックへの
素直な帰着」で済んだ——新しいVB変換・新しいランタイム落ちの発見は
今回は無かった。実機XAML3件で`generate_python()`+`compile()`を
確認(`RenameFileX`サンプルは`.AsText(...)`/`.Format(...)`という
無関係な既存の未対応呼び出しでTODO化されたが、これは新機能のバグ
ではない)。`RenameFileX`の成功パス(`KeepExtension="True"`)は
実機サンプルが踏まなかったため合成XMLで別途確認し、さらに実際の
一時ディレクトリで`old.txt`→`renamed.txt`(拡張子保持)への実際の
リネームが実行時に正しく動くことも手動確認した。回帰テスト追加
(`tests/test_uipath_dsl.py`3件・`tests/test_uipath_codegen.py`18件)、
UiPath関連テスト全848件通過、リポジトリ全体で全1924件通過(28件
skip、変化無し)。

## 192. `ui:SelectFile`を新規実装——ネイティブOSファイル選択ダイアログ、知見176(`GetPassword`)・知見174(`GetAttribute`)と同じ「常にTODOへ倒れる活動でも型をモデル化する価値がある」判断の3例目

GitHub code searchで`"<ui:SelectFile "`(123件ヒットした`RenameFileX`と
同様の、トレーリングスペース付き完全一致パターン)が157件ヒットした。
`UiPath/skills`公式リポジトリのStudio実機ground-truthコーパス(`UiPath.
System.Activities/25.10/SelectFile.xaml`)+実機2件(`GSA/RPA-OSS`の
`CatalogFramework/Main.xaml`、`lezwon/uipath_deoldify`の`Main.xaml`)で
確認した構成は`Filter`(拡張子フィルタ文字列、例`"Excel Files (*.xls,
*.xlsx)|*.xls;*.xlsx"`)+`SelectedFile`(出力、単一選択)+
`InitialDirectory`/`Multiselect`/`SelectedFiles`(複数選択時の出力、
ground-truthコーパスでは全件`{x:Null}`——実機2件とも非null値を確認
できなかったため未検証のまま)。

この活動はOSのネイティブなファイル選択ダイアログを表示し、ユーザーの
実際の選択操作を待つ——`GetPassword`(知見176、DPAPI暗号化を復号する
安全な方法が無い)や`GetAttribute`(知見174)と同様、本質的に人間の
対話操作そのものを表しているため、headless実行環境で代わりに応答する
確認済みの安全な方法は存在しない。そのため`Filter`・出力の有無を問わず
常に`# TODO`へ倒す設計とした——この判断自体に新規性は無いが、「常に
TODOへ倒れる活動でもノード型を適切にモデル化しておく価値がある
(declineメッセージに`DisplayName`等の文脈情報を残せる、将来`Multiselect`
等の実例が見つかった際の拡張の土台になる)」という既存方針の3例目として
実装した。

実機サンプル2件+合成XMLで`parse_activity()`+`generate_python()`+
`compile()`を確認。回帰テスト追加(`tests/test_uipath_dsl.py`1件・
`tests/test_uipath_codegen.py`3件)、UiPath関連テスト全852件通過、
リポジトリ全体で全1928件通過(28件skip、変化無し)。

## 193. PDF活動ファミリーの調査(実装は見送り)——`ui:ReadPDFText`はコード変更無しでも既に安全にTODO化、`UiPath.PDF.Activities.PDF`という本調査で初めて遭遇した非`http://schemas.uipath.com/...`形の名前空間を発見

ユーザー指示によりユーザーから提示された3件の調査候補のうち、
`ui:ReadPDFText`(GitHub code searchで539件ヒット)を中心にPDF活動
ファミリーを調査した(実装は行わず調査のみ)。知見128で発見した
`marcelocruzrpa/uipath-ai-skills`のground-truthコーパス
(`UiPath.PDF.Activities/3.25`、12件、当時「未検証」として記録)を
この調査で実際に確認した。

`ui:ReadPDFText`(`http://schemas.uipath.com/workflow/activities`
名前空間、`ui:`)自体の構成は`FileName`+`PreserveFormatting`
(実機4件全て`{x:Null}`)+`Text`(出力)+`Range`。`Range`は
ground-truthの既定値`"All"`に加え、実機で`"2"`(単一ページ番号、
`PacktPublishing/Robotic-Process-Automation-RPA-for-Developers`)の
実例を確認し、同じ`UiPath.PDF.Activities`パッケージの兄弟活動
`ExtractPDFPageRange`(後述)では`"8-22"`(ハイフン区切りの範囲)の
実例も確認した——`Range`は`"All"` / 単一ページ番号 / ハイフン範囲の
少なくとも3種の文字列形式を取りうる。`Password`属性は`ui:ReadPDFText`
のground-truth・実機のどちらにも存在しなかった(暗号化PDF対応は
`ReadPDFText`自体には無く、別の`ManagePDFPassword`活動が担う設計)。

**最大の発見**: 同じ`UiPath.PDF.Activities`パッケージ内の
`GetPDFPageCount`/`JoinPDF`/`ExtractPDFPageRange`/`ManagePDFPassword`/
`ExportPDFPageAsImage`/`ExtractImagesFromPDF`は`ui:`(`http://schemas.
uipath.com/workflow/activities`)**ではなく**、`upap:`という別の
プレフィックスで、XML名前空間URIそのものが`clr-namespace:UiPath.PDF.
Activities.PDF;assembly=UiPath.PDF.Activities`という**CLRネームスペース
形式の文字列**になっている——本調査で初めて遭遇した、`http://schemas.
uipath.com/...`形のURN以外の活動名前空間。実機サンプル(`Anusha-TX/
Group1001_TestAutomation`のVB.NET版、`vajrang-b/UiPathIn30Days`の
flat属性版)で両方の直列化形(プロパティ要素形・flat属性形)を確認した。
`xaml_tree.py`の`_DISPATCH`は`(namespace_uri, tag)`タプルをキーにして
おり、lxmlは常に解決済みの完全URIを`elem.tag`へ渡すため、この新しい
namespace定数(例: `PDF_NS = "clr-namespace:UiPath.PDF.Activities.PDF;
assembly=UiPath.PDF.Activities"`)を追加して`_DISPATCH`に登録するだけで
既存のディスパッチ機構はそのまま使える——アーキテクチャ上の障害では
ない、という点は確認できた。

`vajrang-b/UiPathIn30Days`の実機サンプルでは`GetPDFPageCount`
(`FileName`+`PageCount`出力)/`JoinPDF`(`FileList`+`OutputFileName`、
`FileList`の値は`[{"a.pdf","b.pdf"}]`というVB配列リテラル構文——
現状の`uipath_expr`パーサーがこれを解釈できるか未検証)/
`ExtractPDFPageRange`(`FileName`+`OutputFileName`+`Range="8-22"`)/
`ManagePDFPassword`(`FileName`+`NewUserPassword`(平文VBリテラル)+
`OutputFileName`、暗号化されていない通常の文字列のため`GetPassword`
の DPAPI問題とは無関係)という具体的な実例を確認した。別のサンプル
(`burakyucel0/Project55`)で見つかった`apac:ReadPDFText`
(`Password`属性あり、`Filename`小文字n)は`ArenaRobotics.PDF.
Activities`という**サードパーティ製の別ベンダー活動パッケージ**だと
判明——同名の活動タグでも名前空間が異なれば完全に別物であるという、
本調査にとって新しい注意点(タグ名だけでの判定は危険、`(namespace,
tag)`の組で初めて活動が一意に決まるという既存の設計方針の重要性を
裏付ける実例)。

実装は見送った(ユーザー指示は調査のみ)。`ui:ReadPDFText`自体は
既存の未知活動フォールバック(`UnknownActivityNode`)で安全に素通り
するため緊急性は無い。実装するなら`FileName`+`Range`(3種の形式を
確認済み)+`Text`は`pypdf`/`pdfplumber`等の確認済みPythonライブラリで
対応できる見込みが高いが、`UiPath.PDF.Activities.PDF`名前空間の
新規追加という前例の無い作業が前提になる。コード変更無し。

## 194. `ui:AnchorBase`の調査(実装は見送り)——制御フロー構造は確認できたが、本質的な機構(アンカー相対のUI要素探索)にセレクタ上の表現が無く、headless実行で代替する安全な方法が無いという構造的な壁を発見

GitHub code searchで`"<ui:AnchorBase "`が309件ヒット。公式
ground-truthコーパス(`UiPath.UIAutomation.Activities/25.10`、76件)
には`AnchorBase`は含まれていなかった(ディレクトリ一覧で確認済み、
`Anchor`を含むファイル名は0件)ため、実機サンプルのみで調査した
(`cameronmcnz/uipath-tutorials`の`PDFExtract/Main.xaml`等)。

構造自体は明確に確認できた: `AnchorPosition`(例`"Top"`)属性+
`AnchorBase.AnchorProvider`(**単一の**子活動、実機では`ui:
WaitUiElementAppear`でアンカー点となるUI要素を探す)+
`AnchorBase.Action`(`ActivityAction<ui:Anchor>`という**1変数**の
デリゲート、`DelegateInArgument`の名前は実機で`"ContextAnchor"`、
本体に`ui:GetValue`等の通常の活動を1つ以上含む)。知見190の
`ForEachFileX`/`ForEachFolderX`で確立した単変数`ActivityAction`の
解析ロジックがそのまま使える構造で、新しいパーサーヘルパーは不要
——構文的な解析自体は難しくない。

**壁になったのは機構そのもの**: `AnchorBase`の目的は「アンカー要素を
起点に、画面上の相対位置関係でそれに近い別の要素を探す」という
UiPath実行エンジンの画面上の視覚的探索機能であり、これは`Selector`
文字列(XMLに直接現れる、確認可能な情報)では一切表現されない
——実機サンプルの`Action`内の`ui:GetValue`の`Selector`は`<ctrl
role='text' />`という、単独では複数の要素にマッチしうる極めて汎用的な
値で、実際にどの要素が選ばれるかは「アンカーに最も近い」という
XAMLに書かれていない実行時の画面幾何情報に依存する。`Click`/
`TypeInto`の`SimulateClick`(機構未確認のため常に見送り)と同種の
「確認できない入力方式」問題よりも一段深い——この活動は構造上、
実行時の画面状態を見ずに静的な`generate_python()`で安全に模倣
できる情報がXAML側に原理的に存在しない。

したがって`AnchorBase`を実装するとしても、`Body`(`Action`内の
子活動群)の`Selector`自体がアンカー文脈に依存した相対指定である
限り、常に`# TODO`へ倒すしかない——知見176の`GetPassword`・
知見174の`GetAttribute`・知見192の`SelectFile`と同じ「常にTODOへ
倒れる活動」の4例目になるが、これらと違い**モデル化する動機が弱い**
(3例はいずれも「属性値自体」の変換不可が理由で、ノード型を作れば
decline文に`DisplayName`等の文脈を残せる価値があったが、`AnchorBase`
は構造が制御フロー系で複雑(`body`+2つの子活動スロット)な割に、
得られる価値はdeclineコメント1行のみ)。実装は見送った。コード変更
無し。

## 195. DataTable操作活動ファミリーの再調査(実装は見送り)——知見179の一括保留判断を見直し、活動ごとの難易度に大きな差があることを発見、ground-truthコーパスから未知の新規活動3件(`JoinDataTables`/`LookupDataTable`/`GenerateDataTable`)を発見、`SortDataTable`で実機の属性名バージョン差異(`SortOrder`→`Order`、値`"Decending"`という誤字)を発見

知見179で「`FilterDataTable`/`AddDataColumn`/`RemoveDataColumn`/
`SortDataTable`/`MergeDataTable`は`DataTable`表現の非統一性という
アーキテクチャ上の前提作業が必要」として一括保留した判断を、知見128の
ground-truthコーパス(`UiPath.System.Activities/25.10`)+実機サンプルで
再調査した。

ground-truthコーパスに実在が確認できた同系活動一覧(括弧内は属性):
`FilterDataTable`(`DataTable`+`Filters`+`OutputDataTable`+
`SelectColumns`+`SelectColumnsMode`)、`RemoveDataColumn`(`Column`/
`ColumnIndex`/`ColumnName`+`DataTable`)、`SortDataTable`(`ColumnIndex`/
`ColumnName`/`DataColumn`+`DataTable`+`OutputDataTable`+`SortOrder`)、
`MergeDataTable`(`Destination`+`Source`+`MissingSchemaAction`)、
**および知見179では未発見だった3件の新規活動**:
`JoinDataTables`(`Arguments`+`DataTable1`+`DataTable2`+
`OutputDataTable`+`JoinType`、2つのDataTableのリレーショナルjoin)、
`LookupDataTable`(`DataTable`+`LookupColumnIndex`/`LookupColumnName`/
`LookupDataColumn`+`LookupValue`+`TargetColumnIndex`/`TargetColumnName`/
`TargetDataColumn`+`CellValue`出力+`RowIndex`出力、単一値の検索)、
`GenerateDataTable`(`Input`+`ColumnSeparators`/`ColumnSizes`/
`Positions`+`NewLineSeparator`+`DataTable`出力、テキストを区切り文字/
固定幅でDataTableへ変換)。`AddDataColumn`はこのコーパスには存在せず
(別パッケージ版の可能性、実機のみで構成確認——後述)。

実機サンプルで構成を検証した結果、**知見179の一括保留判断には見直す
余地がある**ことが分かった——5活動の実際の難易度は一様ではない:
- `RemoveDataColumn`/`AddDataColumn`(実機`HarshadRanganathan/
  uipath-learning`で確認、`AllowDBNull`/`AutoIncrement`/`MaxLength`/
  `Unique`が実機で`{x:Null}`ではなく`"True"`/`"False"`/`"100"`という
  **明示的な値を持つ実例を確認**——ground-truthの「既定`{x:Null}`」
  という前提は実機の実態と異なっていた)はスキーマ変更のみ(列の追加/
  削除)で行の**値**を読む必要が無いため、知見183で確立した
  `isinstance(row, dict)`判定と組み合わせれば「dict行表現の場合のみ
  対応・それ以外は`# TODO`」という部分対応が可能かもしれない——ただし
  `MaxLength`/`Unique`等の.NET DataColumn制約はPython側に強制する仕組みが
  無く、それらが設定された場合にどう振る舞うべきかは未確定。
- `MergeDataTable`はスキーマが同一であれば単純な行リストの結合
  (`Destination.extend(Source)`相当)で済む可能性があるが、
  `MissingSchemaAction`(既定`"Add"`)が示す「スキーマが異なる場合に
  列を追加する」挙動を実現するには、結局列名解決が必要になる。
- `LookupDataTable`は出力が単一のセル値+単一の行インデックスに
  限定されるため、他の4活動より**構造的に単純**——
  `LookupColumnIndex`/`TargetColumnIndex`のような列インデックス直接
  指定の実例があれば、dict行表現への依存すら避けられる可能性がある。
  今回確認した5活動の中で最も有望な次の実装候補と判断する。
- `GenerateDataTable`は既存のDataTableを読むのではなく**新しく
  構築する**活動のため、出力の表現形式(dict行か否か)を自分で選べる
  ——既存の非統一性問題を回避できる構造的な利点がある。区切り文字/
  固定幅という2種のテキスト分割方式の意味論を確認できれば、
  実装候補として有望。
- `SortDataTable`/`FilterDataTable`/`JoinDataTables`は依然、任意の
  行表現に対する列名ベースの値アクセスが必要で、知見179の指摘した
  「変数の生成元を跨いだ列スキーマ追跡」というアーキテクチャ課題が
  そのまま当てはまる——この3件は保留を継続する。

**独立した実機バージョン差異の発見**: `SortDataTable`はground-truth
(`UiPath.System.Activities/25.10`)では`SortOrder`(値`"Ascending"`/
`"Descending"`)という属性名だが、実機`PacktPublishing/Robotic-
Process-Automation-RPA-for-Developers`のサンプルでは属性名が
**`Order`**(`SortOrder`ではない)で、値も**`"Decending"`**
(正しい`"Descending"`の誤字)になっていた——ground-truthコーパスは
特定バージョン(25.10)のみを収録しているため、より古い/新しい
Activitiesパッケージバージョンで属性名・取りうる値の表記が変わる
(あるいは単純にUiPath側の既知の誤字が長期間修正されずに残っている)
可能性を示す実例。将来`SortDataTable`を実装する際は、`SortOrder`
だけでなく`Order`という別名の実在もパーサーで吸収する必要がある
(例: `_attr_expr(elem, "SortOrder") or _attr_expr(elem, "Order")`)。

実装は見送った(ユーザー指示は調査のみ)。知見179の一括保留判断は
`FilterDataTable`/`SortDataTable`/`JoinDataTables`には今も妥当だが、
`LookupDataTable`/`GenerateDataTable`/`RemoveDataColumn`は次の
実装候補として`design/uipath_feature_catalog.md`の「DataTableスキーマ
解決パス」節に追記した。コード変更無し。

## 196. `ui:LookupDataTable`を新規実装——知見195で「DataTable操作ファミリーの中で最も構造的に単純」と評価した候補を実装、単一セル値+行インデックスのみを返す構造が知見179の表現非統一性問題の影響を受けにくいことを実証

知見195で「DataTable操作ファミリーの中で最も有望な次の実装候補」と
評価した`ui:LookupDataTable`(GitHub code searchで197件ヒット)を
実装した。`UiPath/skills`公式リポジトリのStudio実機ground-truth
コーパス+実機(`PacktPublishing/Robotic-Process-Automation-RPA-for-
Developers`)で確認した構成は`DataTable`+`LookupColumnName`+
`LookupValue`+`TargetColumnName`+`CellValue`(出力、実機では`<ui:
LookupDataTable.CellValue><OutArgument x:TypeArguments="ui:
GenericValue">...`というプロパティ要素形)+`RowIndex`(出力、実機では
`[rowIndex]`というflat属性形)。`LookupColumnIndex`/`TargetColumnIndex`
(列インデックス直接指定)・`LookupDataColumn`/`TargetDataColumn`
(DataColumnオブジェクト参照、未モデル化)はground-truthにのみ存在し
実機での使用例を一度も確認できなかったため、設定時は常に`# TODO`へ
倒す。

公式ドキュメント(docs.uipath.com)で`LookupValue`が見つからない場合
`RowIndex`は`-1`を返す(ExcelのVLOOKUPに類似した挙動)ことを確認した
——`CellValue`については見つからない場合の挙動は公式ドキュメントに
明記が無かったため、`None`のまま(Pythonの未設定値)にする設計とした。

実装自体は`row[column_name]`という名前ベースアクセス(知見183の
`GetRowItem`の`ColumnName`分岐と同じ、dict行を前提にした素直な実装)
で、DataTable全体を`for`文で1回走査して最初に一致した行の列値+
インデックスを返す。知見195で予想した「単一のセル値+単一の行
インデックスを返すだけなら、DataTable全体を読み直したり再構築
したりしないため、知見179の表現非統一性問題(dict行/list行/空リストが
活動ごとに混在)の影響を受けにくい」という見立てが実装を通じて
実証できた——他のDataTable操作活動(`SortDataTable`等)と違い、列の
並び順や全体のスキーマを一切追跡する必要が無かった。

実機サンプルの属性構成(フラット属性形+プロパティ要素形の混在)で
`parse_activity()`+`generate_python()`+`compile()`を確認し、さらに
実際のPythonインタプリタでdict行のリストに対する検索ロジックを
手動実行し、一致あり(行インデックス+セル値を正しく返す)・一致なし
(`-1`+`None`を返す、公式ドキュメントの挙動と一致)の両方を確認した。
回帰テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
test_uipath_codegen.py`8件)、UiPath関連テスト全861件通過、リポジトリ
全体で全1943件通過(28件skip、変化無し——知見196着手時点でリポジトリ
全体は別セッションの並行作業により知見205まで進んでいたが、`design/
uipath_xaml_findings.md`/本トランスパイラのコード自体には競合は無かった)。

## 197. `ui:GenerateDataTable`を新規実装——知見195で2番目に有望と評価した候補、ground-truthコーパスに無かった`CSVParsing`/`UseColumnHeader`/`AutoDetectTypes`属性を実機で発見、`csv.DictReader`/`str.split()`の二択で安全に対応

知見195で「DataTable操作ファミリーの2番目に有望な候補」と評価した
`ui:GenerateDataTable`(GitHub code searchで180件ヒット)を実装した。
`UiPath/skills`公式リポジトリのStudio実機ground-truthコーパス
(25.10・26.2の両バージョンで内容が完全に同一)は`ColumnSeparators`+
`ColumnSizes`+`DataTable`+`Input`+`NewLineSeparator`+`Positions`のみ
だったが、実機3件(`vajrang-b/UiPathIn30Days`)では**ground-truthに
一切載っていない**`CSVParsing`(`"True"`/`"False"`)・
`UseColumnHeader`(確認した全件`"True"`)・`AutoDetectTypes`
(確認できた値は`"False"`)という3つの追加属性を発見した——知見128が
最初から注記していた「ground-truthコーパスは属性**名**の一覧としては
権威的だが、新しい値の変換ロジックを実装する根拠にはならない(ほぼ
全て`{x:Null}`のデフォルトのみ)」という限界が、今回は「そもそも
ground-truthに存在しない属性が実機には存在する」という、より強い
形で裏付けられた。

実機で確認した構成(`Input`+`ColumnSeparators`(単一文字、実機は
`";"`/`","`)+`NewLineSeparator`(実機は改行文字そのもの、または
`{x:Null}`)+`UseColumnHeader="True"`+`CSVParsing`(True/False両方の
実例を確認)+`DataTable`(出力)+`AutoDetectTypes`)に基づき、
`CSVParsing="True"`時はPython標準の`csv`モジュール(`csv.DictReader`、
`ReadCsvFile`知見185と同じ、引用符で囲まれたフィールド内の区切り
文字を正しく扱う)、`"False"`時は単純な`str.split()`で対応した
——いずれも`UseColumnHeader="True"`前提のdict行表現で出力を統一
できる。固定幅モード(`Positions`/`ColumnSizes`が非null、GitHub検索
では176件ヒットしたが実際に非null値を使う実例は複数サンプルを
確認しても一度も見つからなかった)・`UseColumnHeader`が`"True"`
以外・`AutoDetectTypes="True"`(型推論の正確な意味論——文字列を
どの.NET型へどう変換するか——が未確認)は常に`# TODO`へ倒す。
`ColumnSeparators`が複数文字の場合(`csv`モジュールの`delimiter`は
1文字しか受け付けない)・`NewLineSeparator`がリテラル改行文字以外の
場合も同様にTODO化する、独自の安全策を追加した。

知見196の`LookupDataTable`と同じ理由(既存のDataTableを読まず新規に
構築するため、出力の表現形式を自分で選べる)で、知見179の表現非
統一性問題を回避できることを実装を通じて確認した。実機サンプル2件
(`CSVParsing="True"`/`"False"`の両方)+合成データで`parse_activity()`
+`generate_python()`+`compile()`を確認し、さらに実際のPython
インタプリタで両方の分岐(`csv.DictReader`経由/`str.split()`経由)を
実行し、同一の入力テキストから同一のdict行リストが生成されることを
手動確認した。回帰テスト追加(`tests/test_uipath_dsl.py`1件・
`tests/test_uipath_codegen.py`11件)、UiPath関連テスト全872件通過、
リポジトリ全体で全1954件通過(28件skip、変化無し)。

## 198. `ui:AddDataColumn`+`ui:RemoveDataColumn`を新規実装——知見195で3番目に有望と評価したDataTable操作系候補、知見183の`isinstance(row, dict)`判定を初めて「既存の全行への書き込み」という文脈で使用、list行表現には`# WARNING`付きで意図的に非対応のまま

知見195で「DataTable操作ファミリーの3番目に有望な候補」と評価した
`ui:AddDataColumn`(GitHub code searchで856件ヒット)+`ui:
RemoveDataColumn`(273件ヒット、`AddDataColumn`の正反対)を実装した。
`RemoveDataColumn`は`UiPath/skills`公式リポジトリのStudio実機
ground-truthコーパスがあるが、`AddDataColumn`は知見195の調査時点
から変わらずコーパスに存在しない(別パッケージ版の可能性、実機のみで
構成確認)。

実機確認した構成: `AddDataColumn`は`ColumnName`+`DataTable`+
`x:TypeArguments`(列の.NET型、実機は全件`x:Object`、Pythonには対応
する型強制が無いためモデル化不要)+`Column`(DataColumnオブジェクト
参照、未モデル化)+`DefaultValue`+`AllowDBNull`/`AutoIncrement`/
`MaxLength`/`Unique`(列スキーマ制約)。実機2件で、全て`{x:Null}`の例
(`Its-Nishant-10/book_scraping`)と、`AllowDBNull="True"`/
`AutoIncrement="False"`/`MaxLength="100"`/`Unique="False"`という
明示的な値の例(知見195で確認済みの`HarshadRanganathan/uipath-
learning`)の両方を再確認した。`RemoveDataColumn`は`ColumnName`+
`DataTable`のみ(実機2件で`Column`/`ColumnIndex`はどちらも常に
`{x:Null}`)。

知見183の`GetRowItem`で確立した`isinstance(row, dict)`判定を、
初めて「読み取り」ではなく「既存の全行への書き込み(列の追加/削除)」
という文脈で使った——dict行の場合のみ、各行に`ColumnName`キーを
追加(`AddDataColumn`、値は`DefaultValue`、未設定なら`None`)/削除
(`RemoveDataColumn`、`dict.pop(key, None)`でキーが無くても安全)する。
list行表現の場合は意図的に何もしない——`GetRowItem`等の既存の
読み取り専用ternary式と違い、この「非dict行では沈黙する」という
片方向の対応を生成コードの`# WARNING`コメントで明記した(`OutputDataTable`
知見184の近似実装と同じ「大枠は確信、適用範囲の限界はコメントで
明示する」という判断パターン)。

`AutoIncrement="True"`(自動連番割り当て、未確認)・`Unique="True"`
(一意性制約の実施、未確認)・`AllowDBNull="False"`(既存行への
NOT NULL制約の実施、未確認)は常に`# TODO`へ倒す——`MaxLength`は
列の追加操作自体には影響しない(値の代入時のみ関係する制約で、本
トランスパイラはどの代入にも文字数制限を課していないため)ため
TODO化せず無視する設計とした。

実機サンプル(両方の属性バリエーション)で`parse_activity()`+
`generate_python()`+`compile()`を確認し、さらに実際のPython
インタプリタで両活動を実行し、dict行が正しく変更される一方で
list行表現の要素が変更されずに残ることを確認した(`exec()`経由で
生成関数を実際に呼び出し、ミュータブルな`list`オブジェクトへの
インプレース変更を直接検証する、本調査で新しいテスト手法)。回帰
テスト追加(`tests/test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`
15件)、UiPath関連テスト全887件通過、リポジトリ全体で全1969件通過
(28件skip、変化無し)。

## 199. `ui:ReadPDFText`を新規実装——知見193で発見したPDF活動ファミリーの中核、`pypdf`(本リポジトリのPAD側で既に実戦投入済みの依存)を再利用、単一ページ番号の1始まり規約はPAD側の既存確認済み変換から合理的に推論

知見193で調査した`ui:ReadPDFText`(GitHub code searchで539件ヒット)
を実装した。構成(`FileName`+`Text`+`Range`+`PreserveFormatting`)
自体は知見193で既に確定済み——`UiPath/skills`公式リポジトリのStudio
実機ground-truthコーパス+実機4件で、`Range`が`"All"`と単一ページ
番号`"2"`の2種を取ることを確認していた。

実装にあたり最も重要な発見は、**本リポジトリ自身のPAD側
(`dump_daemon/pad_action_lib/pdf_actions.py`)に、既に`pypdf`を使った
`extract_text_from_pdf()`という成熟した実装が存在すること**だった
——UiPath側のトランスパイラがこのPAD側の関数を直接importすることは
しない(生成コードは常に自己完結、標準ライブラリ+確認済み第三者
ライブラリのみに依存するという既存の設計方針、`pyproject.toml`で
`pypdf`自体は既に確認済みの依存)が、同じ`pypdf.PdfReader(...).
pages[i].extract_text()`というイディオムをそのまま踏襲し、さらに
重要な設計判断——**単一ページ番号は1始まり**(`Range="2"`→
`pages[1]`、0始まりへの変換が必要)——を、PAD側の`extract_text_from_
pdf()`内の既存の確認済み変換(`page_number - 1`)から合理的に推論した。
UiPath Studio実機でこの1始まり規約を独立に確認できたわけではない
(知見193時点でも未確認のまま)が、同じ会社の類似PDF活動2製品間
での規約共有という妥当な推論であることを型のdocstring・設計コメント
に明記した——確認済みの直接証拠と合理的推論を明確に区別するという、
本調査で初めて踏んだ「別製品の確認済み挙動からの類推」という新しい
種類の判断。

`Range`が`"All"`の場合は全ページのテキストを連結、それ以外は
`int(Range) - 1`で0始まりへ変換した単一ページを抽出する——この分岐は
`Range`が静的な`Literal`か動的な`VbExpr`かを問わず同じランタイム
`if`文で対応できるため、コード生成時に値を知る必要が無い(知見193で
確認した`ExtractPDFPageRange`専用のハイフン範囲`"8-22"`のような
形式は、`ReadPDFText`自身での使用が未確認のため、**静的リテラル**
でハイフンを含む場合のみ`# TODO`へ倒す——動的な式の場合は`int()`の
`ValueError`で実行時に自然に失敗させる、独自の事前検証を追加しない
という既存方針)。`PreserveFormatting`が非null値の場合は常に
`# TODO`へ倒す。

合成データ(静的"All"・静的"2"・動的`VbExpr`の3パターン全て)で
`generate_python()`+`compile()`を確認し、さらに実際に`pypdf`で
2ページの空白PDFを生成して実行し、全ページ抽出・単一ページ抽出の
両方が例外無く動作することを手動確認した。回帰テスト追加(`tests/
test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`8件)、
UiPath関連テスト全897件通過、リポジトリ全体で全1979件通過(28件
skip、変化無し)。

## 200. `UiPath.PDF.Activities.PDF`名前空間基盤を追加し`GetPDFPageCount`+`ExtractPDFPageRange`を新規実装——知見193で発見した非`http://schemas.uipath.com/...`形の名前空間を実際に解禁、既存の`(namespace, tag)`ディスパッチ機構がそのまま使えることを実装で確認

知見193で発見した`UiPath.PDF.Activities.PDF`名前空間
(`clr-namespace:UiPath.PDF.Activities.PDF;assembly=UiPath.PDF.
Activities`、`upap:`プレフィックス、`ReadPDFText`等が使う通常の
`http://schemas.uipath.com/workflow/activities`とは異なる)を
`dump_daemon/uipath_dsl/xaml_tree.py`に`PDF_NS`定数として追加し、
この名前空間を使う6活動(`GetPDFPageCount`/`JoinPDF`/
`ExtractPDFPageRange`/`ManagePDFPassword`/`ExportPDFPageAsImage`/
`ExtractImagesFromPDF`)のうち、実機で非null値の確認ができていた
`GetPDFPageCount`+`ExtractPDFPageRange`の2件を実装した(残り4件は
実機確認が手薄なため今回は見送り、次tick以降の候補として残す)。

既存の`_DISPATCH`辞書は`(namespace_uri, tag)`タプルをキーにしており、
lxmlは常に解決済みの完全URI(今回のCLRネームスペース形式の文字列も
含む)を`elem.tag`へ渡すため、`(PDF_NS, "GetPDFPageCount")`のような
エントリを追加するだけで既存のディスパッチ機構がそのまま機能する
ことを実装で確認した——知見193で予想した「アーキテクチャ上の障害
ではない」という見立てが正しかった。

`GetPDFPageCount`(実機2件`Anusha-TX/Group1001_TestAutomation`・
`vajrang-b/UiPathIn30Days`で確認)は`FileName`+`PageCount`のみで、
`len(pypdf.PdfReader(...).pages)`が直接対応する——本リポジトリ自身
のPAD側`pad_action_lib/pdf_actions.py`の`extract_pages_to_new_pdf()`
内で既に`len(reader.pages)`として使われている同じイディオム。

`ExtractPDFPageRange`(実機`vajrang-b/UiPathIn30Days`で確認)は
`FileName`+`OutputFileName`+`Range`(確認した実例は`"8-22"`という
ハイフン区切りの単純な範囲のみ)。重要な設計判断として、PAD側の
`ExtractPagesToNewPDF`活動が対応するカンマ区切りの複数範囲文法
(`"1,3,5-10"`、`_parse_page_selection()`で確認済み)を安易に輸入
しなかった——UiPath側の`ExtractPDFPageRange`でこの豊富な文法が
実際に使えるかは独立に確認できていないため、確認済みの`N-M`形
以外の**静的リテラル**は`# TODO`へ倒し、動的な式の場合は実行時の
`int()`の`ValueError`で自然に失敗させる(知見199の`ReadPDFText`と
同じ方針、別製品の確認済み文法を安易に転用しない判断)。

合成データ(両活動、静的・動的Rangeの両パターン)で`generate_python()`
+`compile()`を確認し、さらに実際に`pypdf`で10ページの空白PDFを
生成して実行し、ページ数取得+指定範囲(3-5ページ)の正しい抽出
(抽出後3ページになる)を手動確認した。回帰テスト追加(`tests/
test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`11件)、
UiPath関連テスト全908件通過。リポジトリ全体では並行作業中の別
セッション(PAD側の`If Image Exists On Screen`機能、`dump_daemon/
pad_dsl/`等が未コミットの状態)による無関係な1件のテスト失敗
(`test_pad_dsl_parser.py::test_if_image_exists_on_screen_parsed_
from_real_capture`)があったが、本トランスパイラのコードとは一切
無関係であることを確認した(知見128以来の「共有git作業ツリー」
注意点の実例)。

## 201. `JoinPDF`を新規実装——知見195・知見200時点で「VB配列リテラル構文が未対応かもしれない」と保留していた懸念を検証し、`uipath_expr`/`render_expr`が既に`ArrayLiteral`→Pythonの`list`リテラル変換に対応済みと判明

知見200で見送った`UiPath.PDF.Activities.PDF`名前空間(`upap:`)の
残り活動のうち、`JoinPDF`を実装した。`UiPath/skills`公式リポジトリ
のStudio実機ground-truthコーパス+実機(`vajrang-b/UiPathIn30Days`)
で確認した構成は`FileList`+`OutputFileName`のみ(`Password`等の
暗号化関連属性は一切無い)。

知見195・知見200で「`FileList`の実機シリアライズ形
(`[{"a.pdf","b.pdf"}]`というVB.NETの配列リテラル構文)を`uipath_expr`
が解釈できるか未確認」として実装候補からペンディングにしていたが、
実際に検証したところ`uipath_expr`は既に`ArrayLiteral`という専用の
ASTノード型を持ち、`render_expr`(`uipath_codegen/render.py`)も既に
これをPythonの`list`リテラルへ変換する処理を持っていた——つまり
着手前の懸念は的外れで、実装自体に新しいVB構文対応は一切不要だった。
`render_expr(VbExpr(text='{"a.pdf", "b.pdf"}'))`が`['a.pdf', 'b.pdf']`
を返すことを対話的に確認した。

`pypdf.PdfWriter`(`pad_action_lib/pdf_actions.py`の`merge_pdf_files()`
と同じ`writer.append(reader)`イディオム)で`FileList`の各パスを
順に結合する——新しい依存・新しいイディオムの追加は不要だった。

実機サンプル(VB配列リテラル構文そのまま)で`parse_activity()`+
`generate_python()`+`compile()`を確認し、さらに実際に`pypdf`で
2ページ+3ページの空白PDF2件を生成して結合を実行し、結合後5ページに
なることを手動確認した。回帰テスト追加(`tests/test_uipath_dsl.py`
1件・`tests/test_uipath_codegen.py`3件)、UiPath関連テスト全912件
通過。

## 202. `ManagePDFPassword`を新規実装——`pypdf`本体のAPI(`PdfWriter.encrypt()`)を直接使う初めての活動、ground-truthが`NewUserPassword`/`NewOwnerPassword`を一切載せていなかったことを再確認

知見200で見送った`upap:`名前空間の残り活動のうち`ManagePDFPassword`
を実装した。`UiPath/skills`公式リポジトリのStudio実機ground-truth
コーパスは`FileName`+`OutputFileName`のみ(`知見197`の
`GenerateDataTable`と同じ「ground-truthが実機の全属性を網羅して
いない」傾向)だが、実機3件(いずれも`vajrang-b/UiPathIn30Days`)で
`NewUserPassword`(平文VBリテラル)と`NewOwnerPassword`(同)の両方
——異なる実例でそれぞれ単独使用——を確認した。`OldUserPassword`/
`OldOwnerPassword`(既存パスワードの変更/削除用と推測)は実機で
一度も非nullの実例を確認できなかったため未モデル化。

この活動は本調査で初めて、本リポジトリのPAD側に既存イディオムが
無く、`pypdf`本体のAPI(`PdfWriter.encrypt(user_password,
owner_password=...)`)を直接使った——`pad_action_lib/pdf_actions.py`
には暗号化(パスワードを新規に設定する)機能は無く、復号
(`_open_decrypted`、既存のパスワードで開く)のみ。`pypdf`を対話的に
実行して確認した挙動: `NewOwnerPassword`のみ設定時は
`user_password=""`(空文字列)を渡すとパスワード無しで開けるが
owner権限のみ制限される——これがUiPath実機の挙動と完全に一致するか
までは確認できていないが、PDFの一般的な仕様(owner-only保護)として
妥当な解釈であることを明記する。

実機サンプル2件(`NewUserPassword`単独・`NewOwnerPassword`単独)で
`parse_activity()`+`generate_python()`+`compile()`を確認し、さらに
実際に`pypdf`で空白PDFを生成して両パターンを実行し、生成したPDFが
正しく暗号化され、意図したパスワードで(またはowner-onlyの場合は
パスワード無しで)開けることを手動確認した。回帰テスト追加
(`tests/test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`
6件)、UiPath関連テスト全920件通過。

## 203. 「スコープ対応のコード生成アーキテクチャ」を新設——知見130が最優先と記録していたVB.NET識別子の大文字小文字正規化を実装、`contextvars`によるアンビエントなスコープ情報で既存の`render_expr`呼び出し規約を一切変えずに済ませた

知見117(`AddDataRow`のクロスノードDataTableスキーマ解決)・知見126
(`row(...)`添字のDataRow型追跡)・知見130(識別子の大文字小文字正規化、
「次にスコープ対応アーキテクチャを設計する際は最優先の要件として含め
るべき」と明記)という3件の「式レンダリングにスコープ情報が必要」な
設計課題に対応する、新しいアーキテクチャの第1段を実装した。ユーザー
からの明示的な指示(「アーキテクチャ刷新、設計をやりましょう」)を
受けて着手。

**設計**: `render_expr`/`_render_node`(`uipath_codegen/render.py`)は
式単体を文脈無しに文字列化する純粋関数で、呼び出し規約(引数は式
のみ)を変える仕組みが無いという知見130の診断はそのまま正しかったが、
実際に全呼び出し経路(`uipath_codegen/__init__.py`内の`_render_value_
or_todo`呼び出しは150件超)へ新しい引数を明示的にスレッディングする
のは、既存の`invoke_resolver`/`out_arg_resolver`(`_generate_node`/
`_generate_body`経由で約77箇所に伝播済み)と同種の手法を踏襲すると
あまりに広範囲な変更になる。代わりに`contextvars.ContextVar`による
アンビエントなスコープ情報(`ScopeInfo`)を採用した——`render_expr`/
`_render_node`の関数シグネチャを一切変えずに、`generate_python()`の
`with render.use_scope(scope):`ブロックの間だけ有効化する設計。
`contextvars`はネスト・再入可能なため、`generate_project_python()`が
複数ファイルへ順に`generate_python()`を呼んでもスコープ情報が別
ファイルへ漏れないことも確認した(回帰テストで検証)。スコープ情報が
無い(呼び出し元が`use_scope`を使わない場合、デフォルトは`None`)場合
は常に無変換——既存の挙動を一切変えない安全なデフォルトになっている。

**`ScopeInfo`の構築**(`_build_scope_info()`、`uipath_codegen/
__init__.py`): ワークフロー木全体を再帰的に歩いて、宣言済みの
識別子(`workflow.arguments`+全ての`VariableDecl`)の小文字キー→
実際の表記(最初に見つかったものを正規形とする)という対応表を作る。
`Node`は実クラスではなく巨大な`Union`型エイリアスのため`isinstance`
の対象にできない——個々のコンテナ型を手で列挙する代わりに「任意の
dataclassのフィールドを再帰的に辿る」という汎用的な走査(`_walk_
scope_sources`)にした。これにより`SwitchArm`/`CatchArm`等のNode本体
ではない補助dataclass内部の`.body`も自動的に拾え、将来新しい
コンテナ型が追加されても個別対応が要らない。`Flowchart`はグラフ
構造(`FlowNode.next`等)でループを持ちうるため、`id()`に基づく
`visited`集合で無限再帰を防いだ。

`ScopeInfo`は`canonical_names`(今回実際に消費する)に加え、
`data_row_vars`(`ForEachNode.type_arguments == "sd:DataRow"`の
反復変数、知見126向け)・`data_table_columns`(`BuildDataTableNode`の
`data_table`変数名→`columns`、知見117向け)というフィールドも用意した
——今回は構築するが消費しない、将来の`row(...)`添字解消・AddDataRow
解禁に向けた土台。`BuildDataTableNode.columns`は実はパーサー側で
すでに抽出・保持されていた(知見117)にもかかわらず、コード生成側が
一度も読んでいなかったことが分かった——両方の情報源はすでに存在して
いたのに、それらを橋渡しする仕組みが無かっただけだった。

**`render.py`側の消費**: `_render_node`のIdent分岐のうち、ドット無し
の素の識別子は`_canonical_name()`経由で即座に正規化する。ドット付き
識別子のうち、末尾セグメントが確認済みの安全なメンバ名(知見118〜
140で確立した`_apply_chained_property`の経路)に一致する場合は、
先頭セグメント(変数参照部分)のみ正規化してからメンバ変換を適用する
——`DateTime.Now`等の静的クラス参照を含む未一致のドット付き名前は
従来通り無変換のまま(でっち上げた正規化をしない安全策)。

実機で知見130が発見した正確なシナリオ(`out_RequirementLanCur`という
表記で宣言されたOutArgumentを、本体が`Out_RequirementLanCur`
(大文字`O`)という別表記で参照する)を合成XMLで再現し、修正前なら
2つの別々のPython変数になり関数の仮引数が一度も更新されない静かな
誤りを生成していたのが、正しく1つの変数へ正規化されることを確認
した。通常のローカル変数宣言での大文字小文字の揺れ(`myCounter`
宣言、`MyCounter`で代入、`myCounter`で読み取り)も同様に確認。
宣言済み集合に無い識別子は無変換のまま(でっち上げ無し)・スコープ
情報が別の`generate_python()`呼び出しへ漏れないことも回帰テストで
確認した。回帰テスト追加(`tests/test_uipath_codegen.py`5件)、
UiPath関連テスト全924件通過、リポジトリ全体で全2010件通過(28件
skip、変化無し)。

**今後**: `ScopeInfo`の`data_row_vars`/`data_table_columns`フィールド
は構築済みだが未消費——次の段として、`row(...)`/`keyrow(...)`添字
(知見126)を`render_expr`の`FuncCall`分岐で`data_row_vars`を使って
解消すること、`AddDataRow`の`ArrayRow`(知見117)を`data_table_
columns`を使って`list[dict]`へ変換することが、同じ`ScopeInfo`基盤の
上に実装できる状態になった。

## 204. 「スコープ対応のコード生成アーキテクチャ」第2段——知見126が発見・保留していた`row(...)`/`keyrow(...)`添字の曖昧性を、知見203の`ScopeInfo.data_row_vars`で解消

知見203で新設した`ScopeInfo`アーキテクチャの第2段として、知見126が
発見し知見130でも実需要を再確認していた`row(...)`/`keyrow(...)`添字
の曖昧性(VB.NETの`識別子(引数)`構文は関数呼び出しとDataRow行の列
アクセスで全く同じ見た目になり、静的型情報無しでは構文だけでは判別
不能)を解消した。

`ScopeInfo.data_row_vars`(`ForEachNode.type_arguments.lower() ==
"sd:datarow"`の反復変数、知見203で構築済みだが知見203自身では未消費
だったフィールド)を`render.py`の`_render_func_call`で実際に使う——
呼び出し先の識別子が1引数で呼ばれ、かつその識別子(大文字小文字を
区別せず`ScopeInfo.canonical_names`で正規化)が`data_row_vars`に
含まれる場合のみ、`row[列名]`という添字アクセス(知見183の
`GetRowItem.ColumnName`分岐と同じ、dict行を前提にした直接アクセス)
へ変換する。既存のTier1確認済み関数名判定(`CStr`/`Split`等)は全て
この新しい判定より前に実行されるため、万が一DataRow反復変数の名前が
確認済みの関数名と衝突しても、既存の確認済み変換が優先される(衝突の
実例は本調査では一度も確認していないが、安全側の優先順位として記録)。
`ScopeInfo`が無い(今まで通り`use_scope()`を使わない呼び出し)場合、
または識別子が`data_row_vars`に含まれない場合は、従来通り
`NotImplementedError`で保守的に`# TODO`へ倒れる——でっち上げた列
アクセス変換はしない。

`ui:ForEachRow`(知見118、`ForEachNode`を再利用)の反復変数名は
`row`固定ではなく、知見130で`keyrow`という別名の実例も確認済み
——合成データで両方の変数名+大文字小文字の揺れ(`KeyRow("Status")`
→`keyRow['Status']`)を確認した。また、`ForEachRow`ではない通常の
`ForEach`(`type_arguments`が`sd:DataRow`以外)の反復変数に対する
同じ構文の呼び出しは、`data_row_vars`に含まれないため引き続き
`# TODO`へ倒れることも確認した(でっち上げ防止の安全策が機能して
いることの裏付け)。実際に`parse_workflow_file()`+`generate_python()`
で実機相当のXAML(`ui:ForEachRow`+`row("E-Mail")`参照)を通して
エンドツーエンドで確認し、`# TODO`無しで`for row in dt: print(row
['E-Mail'])`相当のコードが生成されることを確認した。

回帰テスト追加(`tests/test_uipath_codegen.py`3件)、UiPath関連
テスト全927件通過、リポジトリ全体で全2013件通過(28件skip、変化
無し)。`ScopeInfo.data_table_columns`(`AddDataRow`のクロスノード
DataTableスキーマ解決、知見117向け)は依然未消費のまま——次の段の
候補として残る。

## 205. 「スコープ対応のコード生成アーキテクチャ」第3段——知見117が当初警告していた「`AddDataRow`のlist行追加が他の活動を実行時に壊す」リスクが実際に発生していたことを確認・修正、`ScopeInfo.data_table_columns`で初めて消費

知見203で構築したが未消費のまま残していた`ScopeInfo.data_table_
columns`(`BuildDataTableNode`の対象変数→確認済みの列名、知見117で
パーサー側はすでに抽出・保持していたが生成側が一度も読んでいなかった
情報)を、ついに実際に消費する3段目の実装を行った。

**発見した実在のバグ**: 知見117は当初「`ArrayRow`(位置指定)を
`list`のまま追加する妥協案は、既に実装済みの`ExcelWriteRange`
(`AddHeaders=True`時に`.keys()`を呼ぶ)等のdict前提の消費者を
静かに壊す実害があるため、正直に`# TODO`へ倒す方が安全」と警告して
いた。しかし後の知見181で`AddDataRow`は実際に`list.append()`方式で
実装されており、この警告がそのまま現実になっていた——`BuildDataTable`
→`AddDataRow`→`LookupDataTable`(知見196)という、本調査で何度も
繰り返し確認した定番パターンの組み合わせを実際に実行して確認した
ところ、`TypeError: list indices must be integers or slices, not str`
で実行時に落ちることを確認した(`generate_python()`自体は正常に
完了し、`compile()`も通過する——構文的には正しいが実行すれば確実に
クラッシュする、知見182のRowIndexバグと同種の問題)。`GetRowItem.
ColumnName`(知見183)・`OutputDataTable`/`WriteCsvFile`のdict行分岐・
`AddDataColumn`/`RemoveDataColumn`(知見198)も同じ理由で影響を受ける。

**修正**: `_generate_add_data_row_body`で、対象`DataTable`変数が
`ScopeInfo.data_table_columns`経由で確認済みの列名を持つと分かる
場合のみ、`ArrayRow`を`dict(zip(columns, array_row))`へ変換してから
追加するよう変更した——`BuildDataTable`→`AddDataRow`の組み合わせが
dict行として一貫するようになり、上記の`TypeError`が解消される。
列名が分からない場合(`DataTable`が`BuildDataTable`由来だと確認
できない、`ScopeInfo`自体が無い等)は、従来通り位置指定の`list`の
まま追加する安全側のフォールバックのまま変えていない——既存の
動作に対する後退は無い。`uipath_codegen/render.py`に`get_active_
scope()`という新しい公開アクセサを追加した(`AddDataRow`の生成関数は
式のレンダリング(`render_expr`)を介さずに`ScopeInfo`を直接読む
必要があったため)。

実際に`BuildDataTable`→`AddDataRow`→`LookupDataTable`という上記の
組み合わせを`generate_python()`で生成し、修正前は`TypeError`で
クラッシュすること・修正後は正しく`{'Name': 'Alice', 'Age': 30}`
というdict行が追加され`LookupDataTable`が正しく行インデックス0・
セル値30を返すことの両方を対話的に確認した。回帰テスト追加
(`tests/test_uipath_codegen.py`2件、うち1件は`exec()`経由で生成
コードを実際に実行する統合テスト)、UiPath関連テスト全929件通過、
リポジトリ全体で全2015件通過(28件skip、変化無し)。

**知見203で設計した3段構成(識別子大文字小文字正規化・`row(...)`
添字解消・DataTableスキーマ解決)がこれで全て実装完了した**——
知見117・126・130が記録していた「式レンダリングにスコープ情報が
必要」という3件の設計課題全てに対応する基盤が揃った。

## 206. `ui:SortDataTable`を新規実装——知見195で「列名ベースの値アクセスが本質的に必要」として保留した3件の1件を、知見203のScopeInfoアーキテクチャで解消、実機で`SortOrder`/`Order`両属性同時存在という新しい版差を発見

知見195で`FilterDataTable`/`SortDataTable`/`JoinDataTables`の3件を
「対象`DataTable`の行表現(dict行か否か)が活動単体の情報からは判断
できない」として一括保留していたが、知見203〜205で`ScopeInfo.
data_table_columns`(`BuildDataTable`の列スキーマが実際に確認できた
変数のみを追跡)が整ったことで、このうち`SortDataTable`は解消できる
条件が揃った。

ground-truth(`UiPath.System.Activities/25.10`)の属性構成は
`ColumnIndex`/`ColumnName`/`DataColumn`(列指定の3択)+`DataTable`+
`OutputDataTable`+`SortOrder`(既定`"Ascending"`)。実機2件
(`PacktPublishing/Robotic-Process-Automation-RPA-for-Developers`・
`ShonHarsh/RPADev-S06P01-GetAndSortData-WindowsLegacy`)で検証した
結果、両方とも`ColumnName`のみを使用(`ColumnIndex`/`DataColumn`は
実機で非`{x:Null}`の値を一度も確認できず、知見196の`LookupDataTable`
と同じ理由で未対応とした)、`OutputDataTable`は`DataTable`とは別の
変数が指定されていた(インプレースではなく新しいDataTableを生成する
——.NETの`DataView`ベースソートの挙動に合致)。

**新しい版差の発見**: 知見195で見つけた`SortOrder`→`Order`という
別名+`"Decending"`という誤字値を実機で再確認したが、今回
`ShonHarsh/RPADev-S06P01-GetAndSortData-WindowsLegacy`では**`Order`
と`SortOrder`が同じ値で両方同時に**シリアライズされていた
(`PacktPublishing`の方は`Order`のみ)——単純な「新旧どちらかの名前」
ではなく、Studioのバージョンによって両方同時出力するケースがある
ことを示す。パーサーは`SortOrder`を優先し`Order`をフォールバックで
読む(`_attr(elem, "SortOrder") or _attr(elem, "Order")`)。

`ColumnName`指定+対象`DataTable`が`BuildDataTable`由来で列スキーマが
確認できる(`columns`が空でない)場合のみ`OutputDataTable = sorted(
DataTable, key=lambda row: row[ColumnName], reverse=...)`を生成する。
`ScopeInfo.data_table_columns`への登録はあるが`columns`が空
(`TableInfo`からスキーマを抽出できなかった場合)は、知見205の
`AddDataRow`と同じ理由(その場合`AddDataRow`はlist行のまま追加する
フォールバックに倒れるため、実際の行表現はdictではない)で
`# TODO`へ倒す——`in`演算子だけでなく値の真偽までチェックする必要が
あった(本tickで実際にテストして発見・修正)。それ以外(スコープ情報
に登録が無い、`ColumnIndex`/`DataColumn`指定、`SortOrder`/`Order`が
未知の値)は全て`# TODO`へ倒す。

回帰テスト追加(`tests/test_uipath_dsl.py`2件・`tests/
test_uipath_codegen.py`4件、うち1件は`exec()`経由で生成コードを
実際に実行し`sorted()`の結果を確認する統合テスト)、UiPath関連テスト
全935件通過、リポジトリ全体で全2021件通過(28件skip、変化無し)。

残る`FilterDataTable`/`JoinDataTables`は、`SortDataTable`より複雑な
入力構造(`Filters`コレクション・`Arguments`結合条件)を持つため、
今回の調査・実装はまだ着手していない——次の実装候補として記録する。

## 207. `ui:FilterDataTable`を新規実装——知見195で保留した3件のうち2件目を知見206と同じScopeInfoアーキテクチャで解消、実機3件で`FilterRowsMode`という新しい未確認属性+`Column`の列名/列インデックス2通りの型を発見

知見206に続き、知見195で保留した3件のうち`FilterDataTable`に着手
した。ground-truth(`UiPath.System.Activities/25.10`)の属性構成は
`DataTable`+`Filters`+`OutputDataTable`+`SelectColumns`+
`SelectColumnsMode`(既定`"Remove"`)。

実機3件(`PacktPublishing/Robotic-Process-Automation-RPA-for-
Developers`・`cameronmcnz/uipath-tutorials`の`DeleteEmpty/Main.xaml`
・`allenlooplee/RPABook`の`src/Demo7/Main.xaml`)で構成を検証した結果:

- **新しい未確認属性`FilterRowsMode`を発見**(ground-truthには存在
  せず、3件全てで確認): 値`"Keep"`(条件に一致する行を残す)/
  `"Remove"`(一致する行を除去する)の両方を実機で確認。cameron
  サンプルはファイル名自体が`DeleteEmpty`(空行を削除)で、
  `FilterRowsMode="Remove"`+`Operator="EMPTY"`という意図と一致する。
- `Filters`(`scg:List<ui:FilterOperationArgument>`)の各要素は
  `BooleanOperator`(確認済み`"And"`のみ)+`Operator`(確認済み
  `"EQ"`/`"GTE"`/`"EMPTY"`の3種、複数条件は全てANDで結合)+`Column`
  (プロパティ要素形の`InArgument`、**`x:TypeArguments`が`x:String`
  なら列名・`x:Int32`なら列インデックスの2通りを実機で確認**)+
  `Operand`(比較値、`EMPTY`では未設定)。
- `OutputDataTable`は知見206の`SortDataTable`とは違い、実機3件中2件で
  `DataTable`と**同じ変数**(インプレース上書き)、1件で別変数という
  両方のパターンを確認した。
- `SelectColumns`は3件中2件が「未選択」(`<x:Null/>`という単一null
  要素のリスト、Studioの「空リスト」のシリアライズ形)、1件
  (Packtサンプル)が実際の列名3件(`SelectColumnsMode="Keep"`との
  組み合わせ)を指定していた。

知見206の`SortDataTable`と同じ`ScopeInfo.data_table_columns`(対象
`DataTable`が`BuildDataTable`由来で列スキーマが確認できる場合)を
要求し、`Filters`条件のみに対応(複数条件はANDで結合、`Keep`は一致
行を残す・`Remove`は一致行を除去)。列インデックス指定(`x:Int32`)は
`columns[index]`という静的に既知の列リストへのインデックスとして
解決するため、動的な式でも対応できる(`round(_vb_cdbl(...))`で知見182
と同じ整数変換を経由——素のVB`Literal`は文字列のため)。`SelectColumns`
(列の投影)は本tickでは未対応のまま`# TODO`へ倒す——`Filters`条件の
実装のみに範囲を絞った。

Packtサンプルの実際の属性(`<InArgument x:TypeArguments="...">`要素の
`TypeArguments`)を読み取るために`x:`名前空間付き属性アクセスが必要
だった(知見21以来の`X_NS`定数を再利用)——最初の実装では無名前空間で
読んでいたため`column_type`が常に`None`になるバグをテストで検出・
修正した。

実機3件相当の構成(EMPTY+列インデックス+Remove、EQ+GTE+列名+Keep)を
`exec()`経由で実際に実行し、正しい行が残る/除去されることを確認した。
回帰テスト追加(`tests/test_uipath_dsl.py`2件・`tests/
test_uipath_codegen.py`5件)、UiPath関連テスト全942件通過、リポジトリ
全体で全2028件通過(28件skip、変化無し)。

残る`JoinDataTables`(`Arguments`結合条件+`JoinType`)は未着手のまま、
次の実装候補として記録する。

## 208. `ui:JoinDataTables`を新規実装——知見195で保留した3件を全て解消、公式ドキュメントで出力列の重複名解決規則(`_1`→`_2`...連番サフィックス)を確認・実装

知見206(`SortDataTable`)・知見207(`FilterDataTable`)に続き、知見195
で保留した3件のうち最後の1件`JoinDataTables`に着手した——これで
知見195・知見179が記録していたDataTable操作ファミリーの保留3件が
全て解消した。

ground-truthの属性構成は`Arguments`+`DataTable1`+`DataTable2`+
`OutputDataTable`+`JoinType`(既定`"Inner"`)。実機3件
(`TharakaMadushankaWanshathilaka/UiPath-Demo-Data-Tables`・
`SuatOzcan/UiPathRoboticProcessAutomation`のVB実機2件——両方とも
「蔵書(OverdueBooks)とユーザー(Users)を共通の`ID`列で結合する」という
構造的に同一の構成、+`ShonHarsh/RPADev-S04P02-...`のC#実機1件、知見136
の既存の安全な未対応経路でそのまま`None`に倒れることを確認)で検証した
結果、`Arguments`(`scg:List<ui:JoinOperationArgument>`)の各要素は
`BooleanOperator`(確認済み`"And"`のみ)+`Operator`(確認済み`"EQ"`
のみ)+`Column1`/`Column2`(プロパティ要素形、実機では`x:String`型
(列名)のみ確認——知見207の`FilterOperationArgument`と違い列インデックス
の実例は無かった)。`Operand`に対応する属性は存在しない(比較対象が
`Column2`であり定数値ではないため)。

**出力列の重複名解決規則を公式ドキュメント(`docs.uipath.com/
activities/other/latest/workflow/join-data-tables`)で確認**:
`DataTable2`側の列が`DataTable1`(または既にリネーム済みの他の
`DataTable2`列)と同名の場合、`_1`→`_2`→...という未使用の連番
サフィックスを付与する(ドキュメント記載の例: `DataTable1`に`ID`/
`ID_1`/`ID_2`があり`DataTable2`に`ID`がある場合、`DataTable2`の
`ID`は`ID_3`になる)。実機3件全てが両テーブルに同名の結合キー列
(`"ID"`)を持つため、この規則への対応は実装の必須要件だった。
`JoinType`の値も同ドキュメントで確認: `"Inner"`(一致行のみ)・
`"Left"`(`DataTable1`の全行保持)・`"Full"`(両方の全行保持)——実機
3件は全て`"Inner"`のみ確認、`"Left"`/`"Full"`は実機未確認のため
未対応のまま`# TODO`へ倒す。

知見206/207と同じ`ScopeInfo.data_table_columns`で`DataTable1`/
`DataTable2`両方のdict行+列スキーマが確認できる場合のみ対応する。
列の重複名解決自体は、両テーブルの列リストがコード生成時に既に
静的に分かっているため、**コード生成時にPythonで計算**し解決後の
列名リストを生成コードへリテラルとして埋め込む(実行時の解決ロジック
は不要、知見206のインデックス解決と同じ「静的に既知の情報は実行時
コードではなくコード生成時に処理する」という設計判断)。

実機2件相当の構成(`OverdueBooks`×`Users`、両方に`ID`列)を`exec()`
経由で実際に実行し、`DataTable2`側の`ID`が`ID_1`に正しくリネームされ
`Inner`結合の一致行のみが出力されることを確認した。回帰テスト追加
(`tests/test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`3件)、
UiPath関連テスト全946件通過、リポジトリ全体で全2032件通過(28件skip、
変化無し)。

**知見195・知見179が記録していたDataTable操作ファミリーの保留3件
(`SortDataTable`/`FilterDataTable`/`JoinDataTables`)がこれで全て
解消した**——知見203のScopeInfoアーキテクチャが当初の3つの設計課題
(知見117・126・130)に加えて、予定していなかったこの3件も解消する
という、想定を超えた再利用価値を持つことが確認できた。

## 209. 「オプション依存プラグイン」の仕組みを新設し`ui:ExportPDFPageAsImage`を新規実装——知見193で「実機確証が薄い」として見送った活動をGitHub再調査で実機確証を得て着手、新規サードパーティ依存の追加をユーザーと相談し本体dependenciesではなくoptional-dependenciesの「プラグイン」群として解決

知見193で「ground-truthの既定値のみで実機の非デフォルト値確認が無い」
として保留していた`ExportPDFPageAsImage`/`ExtractImagesFromPDF`を、
GitHub code searchを再実行して調査した結果、両方で実機の非デフォルト
値確認が得られた。`ExportPDFPageAsImage`は実機2件
(`Sundsvallskommun/RPA_Sammanstallning-av-PDF`——実在のスウェーデン
自治体のRPAリポジトリ・`vajrang-b/UiPathIn30Days`)で`FileName`+
`ImageDpi`(両実機とも`"150"`、ground-truthの既定値と一致)+
`OutputFileName`+`PageNumber`(単一ページ番号、動的な`[Index]`/静的な
`"1"`の両方を確認)という構成を確認した。

**新しいアーキテクチャ課題**: この活動の実装には、本リポジトリに
存在しないPDFページラスタライズ用ライブラリが必要だった(`pypdf`は
テキスト/構造抽出のみで画像描画はできない)。これまでの全ての活動
(知見196-208)は既存の確認済み依存(`pypdf`/`openpyxl`/PIL)を再利用
するだけで済んでいたため、初めて「新規サードパーティ依存の追加」が
必要になるケースだった。ユーザーに相談したところ、まず「見送る」
との回答を得たが、続けて「依存追加が必要な機能についてはプラグイン
での対応を可能にする仕組みにしたい」という方針が示された。

この方針を受けて設計・実装したのが「オプション依存プラグイン」の
仕組み: `pyproject.toml`の`[project.optional-dependencies]`に活動
カテゴリ単位の名前付きグループ(`pdf-render = ["pymupdf>=1.24.0"]`)
を追加し、本体`dependencies`には一切追加しない。重要な気付きは、
トランスパイラ本体(`uipath_codegen`)が実際には**生成コードが参照
するライブラリをimportする必要が無い**という点——既存の`pypdf`/
`openpyxl`(coordinate計算部分を除く)も、コード生成処理自体は
`"pypdf.PdfReader(...)"`という**文字列**を生成するだけで、`pypdf`
自体をimportしてはいない。この既存の設計をそのまま延長し、
`pymupdf`も同様に「`_collect_imports`が生成コード本文の`"pymupdf.
open("`という文字列の出現を検出して`import pymupdf`を注入する」
という既存のimport収集機構(知見で何度も使われてきた`_collect_imports`
のパターンマッチング)にそのまま載せた——コード生成自体に新しい
実行時依存は一切不要。テストでの`exec()`検証用には`dev`依存グループ
に`pymupdf`を追加し(既存の`reportlab`と同じ「テスト専用」の位置
付け)、該当する統合テストは`pytest.importorskip("pymupdf")`で
インストールが無い環境では自動skipする設計にした——「プラグインが
無くても他の全テストは通る」ことを確認済み。

ライブラリ選定は`PyMuPDF`(ネイティブバイナリをwheelに内包、
システム側に`poppler`等の追加インストールが不要)を`pdf2image`
(`poppler-utils`というシステム側の別インストールが必要)より優先した
——`uv add`で確認したところ`pymupdf==2.1`は`onnxruntime`/
`pymupdf-layout`/`pymupdf4llm`等を伴う88MB超の大きめのインストール
になることが分かったが、これは`dev`/`pdf-render`という明示的に
選択した場合のみ発生し、本体の通常インストールには一切影響しない。

実装は`pymupdf.open(FileName)[PageNumber - 1].get_pixmap(dpi=
ImageDpi).save(OutputFileName)`が直接対応する(`get_pixmap(dpi=...)`
はPyMuPDF 1.19.2以降の公式API、Web検索で確認済み)。`import fitz`
(旧名)はPyMuPDF側で非推奨(`FutureWarning`)のため、現行の
`import pymupdf`形を使う。実機相当の構成(reportlabで生成した2ページ
PDFの2ページ目を画像化)を`exec()`経由で実際に実行し、正しいページが
画像化されることを確認した。回帰テスト追加(`tests/
test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`3件、うち1件は
`pytest.importorskip`付きの`exec()`統合テスト)、UiPath関連テスト全
951件通過、リポジトリ全体で全2037件通過(28件skip、変化無し)。

`ExtractImagesFromPDF`(同じ`pdf-render`プラグインで対応できる見込み
だが、出力ファイルの命名規則が公式ドキュメントにも実機にも確認が
無く——`ImageExtension`という未発見の属性の存在も判明——未確定の
ままのため、別tickでの個別調査が必要)は今回は未着手のまま、次の
実装候補として記録する。

## 210. `ui:ExtractImagesFromPDF`を新規実装——知見209の`pdf-render`プラグインをそのまま再利用、GitHub調査で同名だが無関係な第三者製活動(ArenaRobotics社`apac:`名前空間)の実例を発見・区別、出力ファイル名は未確認のため本トランスパイラ独自の命名を採用し明示的にコメントで注記

知見209で保留した`ExtractImagesFromPDF`の出力ファイル命名規則を
調査するため、GitHub code searchで`ExtractImagesFromPDF ImageExtension`
を検索したところ、`burakyucel0/Project55`が一致した。しかし実際に
確認すると`apac:ExtractImagesFromPDF`(`clr-namespace:
ArenaRobotics.PDF.Activities.Controllers;assembly=ArenaRobotics.PDF.
Activities`)という**UiPathの`upap:ExtractImagesFromPDF`とは無関係の
第三者製アクティビティ**だった——属性名も`Filename`(`FileName`では
ない)/`OutputFolder`(`OutputFolderName`ではない)/`ImageExtension`
(数値enum`"0"`/`"4"`、UiPath版のドロップダウン文字列とは別物)で
完全に異なる。知見193で既に警告していた`apac:ReadPDFText`と同じ
「タグ名が同じだけの無関係な別活動」混同リスクが、今度は
`ExtractImagesFromPDF`でも実例として確認された——タグ名だけでなく
名前空間を必ず確認する必要性を改めて実証した。

UiPath自身の`upap:ExtractImagesFromPDF`について、`ImageExtension`の
非デフォルト値を実機で確認する追加調査はできなかった(実機1件
`vajrang-b/UiPathIn30Days`は`FileName`+`OutputFolderName`のみで
`ImageExtension`属性自体が無い)。公式ドキュメント検索では
`ImageExtension`ドロップダウン(`.png`/`.jpeg`/`.tiff`/`.bmp`/`.gif`、
既定`.png`)の存在が示唆されたが、実機確認が無いため`ImageExtension`
が設定されている場合は`# TODO`へ倒す——未設定(既定`.png`相当)の
場合のみ対応する。

**出力ファイル名の命名規則自体も公式ドキュメント・実機のいずれにも
記載が無く未確定**——本質的な機能(画像バイト列の正しい抽出)とは
独立した表示上の選択として、PyMuPDF公式レシピ(知見209でWebFetch
確認した`recipes-images.rst`)がそのまま使う`img-{xref}.{ext}`形式
(画像のPDF内部参照番号ベース)を採用した。これはUiPath自身の内部
命名を再現したものではないため、生成コードにもコメントでその旨を
明示する。知見209の`pdf-render`プラグイン(`pymupdf`)をそのまま
再利用——`Document.extract_image(xref)`が返す`dict`の`"image"`
(バイト列)/`"ext"`(拡張子)キーで、ページをまたいで重複する画像
参照(`xref`)を1回だけ抽出する(公式レシピが明示する仕様)。

実機相当の構成(reportlabでPNG画像を埋め込んだPDFを生成)を`exec()`
経由で実際に実行し、埋め込み画像のバイト列が正しく抽出されることを
確認した。回帰テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
test_uipath_codegen.py`4件、うち1件は`pytest.importorskip`付きの
`exec()`統合テスト)、UiPath関連テスト全956件通過、リポジトリ全体で
全2042件通過(28件skip、変化無し)。

これで知見193が発見した`upap:`名前空間のPDF活動ファミリー7件
(`ReadPDFText`/`GetPDFPageCount`/`ExtractPDFPageRange`/`JoinPDF`/
`ManagePDFPassword`/`ExportPDFPageAsImage`/`ExtractImagesFromPDF`)の
うち、未着手は無くなった。

## 211. 新規活動候補を発掘する調査(実装は見送り)——Orchestratorキュー/トランザクション/アセット系活動群(`AddQueueItem`等、GitHub code searchで数千件ヒット)が、XAMLに一切現れないOrchestrator接続情報を本質的に必要とするため、知見194の`AnchorBase`と同種の構造的な壁に当たると判明

知見193-210で`upap:`PDF活動ファミリー・DataTable操作ファミリーの
明示的なTODOバックログを全て解消したため、知見128・179と同じ手法
(GitHub code searchでの素朴なヒット数調査)で新しい実装候補を発掘
した。

GitHub code searchのヒット数(本tick時点、認証済みレート制限の直前
まで取得): `SetTransactionStatus`(3236件)・`ElementExists`
(2412件)・`GetTransactionItem`(848件)・`AddQueueItem`(846件)・
`GetQueueItems`(308件)・`FindChildren`(226件)・`GetAsset`(71件)・
`AddTransactionItem`(56件)。これまで実装した活動の多くが数百件程度
だったのに対し、`SetTransactionStatus`/`ElementExists`の数千件は
突出して高い。

**`ElementExists`は偽陽性と判明**: 調査の結果、これは別活動のタグ名
ではなく、既存実装済みの`ui:UiElementExists`の**表示名**("Element
Exists"、公式ドキュメントで"internal name UiPath.Core.Activities.
UiElementExists"と確認)がGitHub code searchの`DisplayName`属性文字列
にマッチしていた偽陽性だった——タグ名ベースではなく素朴な文字列検索
だけに頼ると、こうした表示名由来の過大カウントに引っかかる教訓。

**Orchestratorキュー/トランザクション/アセット系(`AddQueueItem`/
`GetTransactionItem`/`SetTransactionStatus`/`AddTransactionItem`/
`GetAsset`/`SetAsset`等)は、知見194の`AnchorBase`と同種の構造的な壁に
当たる**: ground-truthコーパス(`UiPath.System.Activities/25.10`)で
確認した属性構成(`AddQueueItem`は`QueueType`+`ItemInformation`
(`Dictionary<string, InArgument>`)+`Priority`等)自体は把握できたが、
公式ドキュメント(`docs.uipath.com/activities/other/latest/workflow/
add-queue-item`、WebFetch確認)で「ロボットはOrchestratorに接続済みで
なければならず、ロボット自身のOrchestratorアカウント権限で実行される」
ことが明記されている——Orchestratorの接続先URL・認証情報は**XAML自体
には一切現れず**、ロボット実行環境側(UiPath Robot/Assistantの
マシンレベル登録)から実行時に注入される。これは`AnchorBase`が
抱えていた「アンカー相対探索の実質的な機構がSelector文字列に一切
表現されない」という問題と全く同じ構造——静的な`generate_python()`
が安全に模倣できる情報がXAML自体に原理的に存在しない。

実装するには、生成コードに新たな設計(例: 環境変数や追加の関数引数
からOrchestrator接続情報を読み取る、`requests`(既存の確認済み依存、
知見96の`HttpClient`で既に使用)でOrchestrator REST APIを直接呼ぶ等)
を導入する必要があり、これは`AnchorBase`のような「常に実装を見送る」
判断とは異なり、クレデンシャル/ネットワーク接続という新しいリスク
領域を生成コードに持ち込む設計判断——知見209の依存追加の相談と同種、
あるいはそれ以上に、ユーザーとの事前相談が必要な種類の決定だと判断
した。本tickでは実装に着手せず、調査結果のみ記録する。

コード変更無し。次にOrchestratorキュー系活動へ着手する場合は、まず
この設計判断(接続情報の受け渡し方式)をユーザーと相談することから
始める必要がある。

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
  下げて保留する → **知見129で実機証拠を発見・更新**: `UiPath/skills`公式
  リポジトリに240件のC#式言語プロジェクト(`expressionLanguage: "CSharp"`)
  を発見、Studioインストール無しでGitHub上の実例から直列化形式
  (`<CSharpValue>`/`<CSharpReference>`プロパティ要素形)を確認できた。
  対応自体は新しい式言語バックエンドの追加という大規模な設計判断が必要
  なため見送り継続中(知見129参照)
- **(解決)** ~~`Invoke Code`に実際に1つ以上の`Argument`を追加した場合の形~~
  → 知見23で解決(`x:Key`付き`InArgument`要素列になる)。残る派生課題:
  方向`Out`/`InOut`の引数を追加した場合に`OutArgument`/`InOutArgument`の
  どちらになるか(今回は`In`のみ確認)
- 知見172で遭遇した`uipath_selector`モジュールの既存ギャップ——
  `<html app='...' title='...' />`(ブラウザ/Webページのルートノードを
  表すセレクタタグ、実機`aliya-rahmani/Projects`・`Klaus-in-Tech/
  Ford.com-scrapper`の`CloseWindow`実例で確認)が`_map_node`
  (`dump_daemon/uipath_selector/__init__.py`)の`node.tag == "wnd"`
  判定で`_CTRL_ATTR_MAP`に落ち、`app`/`title`が一切マッピングされず
  「no mappable attributes」という過度に保守的な`# TODO`になる。
  `<html>`ノードが実機のUIAツリー/Webオートメーションでどう扱われる
  べきか(`wnd`と同じ`app`→無視・`title`→`title`マッピングで十分か、
  それとも`url`等`html`固有の属性が別に存在するか)を実機XAMLで追加
  調査してから、`_WND_ATTR_MAP`相当の`_HTML_ATTR_MAP`を追加するか
  `<html>`を`<wnd>`と同じ扱いにするかを判断する——`Click`/`TypeInto`
  等、Webページを対象にするあらゆる活動に影響する横断的な改善候補
- **(解決・ネガティブ)** ~~知見176で遭遇した、`render_expr`が未対応の
  チェインメンバーアクセス(`.Subject`)で`NotImplementedError`を
  投げ`generate_python()`全体がクラッシュする問題~~ → 知見177で
  調査し、これは`render.py`モジュールdocstring・`_generate_if`の
  インラインコメントの両方に明記された**意図的な設計**だと判明
  (条件式コンテキストでは、でっち上げた真偽値で制御フローを誤らせる
  よりコード生成全体を失敗させる方が安全という判断)。バグではない
  ため追加の修正は不要——詳細は知見177参照
- 知見179で検討し見送った、`FilterDataTable`/`AddDataColumn`/
  `RemoveDataColumn`/`SortDataTable`/`MergeDataTable`というDataTable
  操作系の活動群(GitHub code searchでそれぞれ285〜1554件ヒット、
  合計すると本調査で遭遇した中でも最大級の頻度)。本トランスパイラの
  `DataTable`表現が活動ごとに非統一(空の`[]`/dict行/素のlist行)で、
  変数の生成元を跨いだ型追跡を行わないため活動単体の情報からは実行時
  表現を判断できない、というアーキテクチャ上の前提作業(`DataTable`
  表現の統一、または変数ごとの表現追跡の導入)が必要——着手するなら
  まずそちらを先に設計する必要がある、相対的に大きな調査候補
- **(解決)** ~~知見189で発見した`ui:ForEachFolderX`~~ → 知見190で
  `ui:ForEachFileX`と共に実装済み
