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
オペランドの数値変換はいずれも解消済み)**:
- `Mod`/`\`のゼロ除算は未解消のまま残る(知見50参照——`/`と違い型依存の
  ため静的型情報が無いと正しく実装できない)。

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
