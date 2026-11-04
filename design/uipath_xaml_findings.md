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

## 今後の調査候補(未着手)

- Switchのcaseに実際にアクティビティを入れた場合の`x:Null`以外の形(今回は
  UI操作のタイミングの都合で未確認のまま終わった)
  ※ 知見9注記: 直近の試行ではcase本体へのアクティビティ追加操作が反映されず
  空のまま保存された。UI操作手順の再検証が必要。
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
- C#式言語プロジェクト(`expressionLanguage: "CSharp"`)でのInArgument/
  OutArgumentの直列化形式の違い(VB.NETと同じ`[...]`規約を使うのか)
