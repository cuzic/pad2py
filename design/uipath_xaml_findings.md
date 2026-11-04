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
- Invoke Workflow File(サブワークフロー呼び出し)とLibrary参照時の引数型
- UI Automationセレクタ(`ui:Click`等)の実際のXAML形(今回は未着手、
  UI操作アクティビティそのものを配置していない)
- C#式言語プロジェクト(`expressionLanguage: "CSharp"`)でのInArgument/
  OutArgumentの直列化形式の違い(VB.NETと同じ`[...]`規約を使うのか)
