# UiPath→Python移行: 調査・リバースエンジニアリング項目の優先順位と進捗

PADで使った手法(実機キャプチャ+pytest検証+知見ドキュメント化)を踏まえて整理した、
UiPath→Python化に向けた調査項目の一覧。実データによる検証状況は
[design/uipath_xaml_findings.md](uipath_xaml_findings.md)の知見1〜11を参照。

**重要な前提**(知見1で確認済み): PADと違い、UiPathのXAML/WF自体はMicrosoftの
公開技術で、アクティビティのパラメータも大半が公式ドキュメント
(activities.uipath.com)にある。つまり多くの項目は「リバースエンジニアリング」
ではなく「ドキュメントを読む+実機で1個ずつXAML化して確認(ドキュメントの記載漏れ・
Studioが吐く暗黙のデフォルト値を確認する程度)」で済む——これはPADより調査コストが
低いという発見自体が重要。

## P0: 基盤

| # | 項目 | 状況 |
|---|---|---|
| 1 | 制御フロー一式のXAML確認(If/Switch/While/DoWhile/ForEach/TryCatch/Parallel/Break) | **完了**: If・ForEach・TryCatch+Catch・Switch(知見5・6・9・11、caseへのアクティビティ追加時の実XAML形=`x:Key`はアクティビティ要素自身の属性になる、を知見21で確定)・While/DoWhile(知見14、実体は`ui:InterruptibleWhile`/`ui:InterruptibleDoWhile`)・Break(知見18、属性なしの自己終了タグ)・Parallel(知見19、`ui:`プレフィックスを持たない素のWFアクティビティ、知見20でブランチ構造も確定=直接の子`Activity`要素)。ドロップゾーンへのドラッグ&ドロップ自動化も知見20で解決(`drag_activity_from_panel()`)。**残課題**: Parallelの複数ブランチの並び、1ブランチ/case内に複数ステップを入れる場合のSequenceラップ(今後の調査候補参照) |
| 2 | VB.NET式 → Python式の変換ルール | **机上整理に着手+一部検証済み**: [design/uipath_vb_expression_mapping.md](uipath_vb_expression_mapping.md)に初期の変換表を作成。`<Literal>`要素/生テキスト/`[...]`角括弧式の使い分けは知見13で実機確定(`x:TypeArguments`が`x:Object`かどうかが本質)。演算子・型変換・`And`/`Or`と`AndAlso`/`OrElse`の非短絡/短絡の違い等は大半まだ未検証 |
| 3 | Variables/Argumentsの正式宣言のXAML形 | **完了**: Variablesは知見8(`<Container.Variables>`配下、`Variable.Default`は`<Literal>`要素)、Argumentsは知見12(ファイル先頭の`<x:Members><x:Property Name="..." Type="InArgument(x:String)" /></x:Members>`) |
| 4 | project.jsonの全体スキーマ(Process/Library/Test、`targetFramework`) | **Processのみ完了**(知見1・知見「今後の調査候補」)。Library/Testプロジェクト、`targetFramework: Windows/Cross-platform`は未着手——インストール済みバージョン(Studio app-21.4.4)のUIには切替箇所が見当たらなかった |
| 5 | 捕獲用ツールの内製化(pywinauto操作のスクリプト化) | **着手**: 繰り返し使った操作パターンを[dump_daemon/uipath_ui_helpers.py](../dump_daemon/uipath_ui_helpers.py)に関数として切り出した(`pad_ui_helpers.py`のUiPath版)。`pad_dsl_parser.py`/`codegen_coverage.py`に相当する本格的なキャプチャ自動化ツール(アクティビティ名を渡すだけで単独ワークフロー生成→XAML差分取得)はまだ無い |

## P1: 実務フローのカバレッジに必須

| # | 項目 | 状況 |
|---|---|---|
| 6 | UI Automationセレクタの実XAML形 | **完了**(知見11): `ui:Click`の`Selector`属性が擬似XML文字列として埋め込まれることを実機確認 |
| 7 | 高頻度アクティビティカテゴリ(Excel/File/Folder/Mail/HTTP Request/Word/PDF/Clipboard/Database) | **着手**: File系の`Append Line`(知見15、属性値への直接リテラル埋め込みという第4の直列化形)・`Read Text File`(知見16、`OutArgument`も`[VarName]`角括弧形で直列化、Propertiesパネル経由のIntelliSense入力の罠)・UiPath特有の`Invoke Code`(知見17・23、インラインコードはプレーンな文字列属性・引数コレクションは空は`scg:Dictionary`・非空は`x:Key`要素列)・Excel系の`Excel Application Scope`+`Write Cell`(知見22、スコープ系アクティビティの構造が`ForEach`と同じ`ActivityAction`+`DelegateInArgument`、ただしデリゲート変数は暗黙参照が既定)・Mail系の`Send Outlook Mail Message`(知見24、添付ファイルの空コレクションは`scg:List`)・Clipboard系の`Set To Clipboard`(知見24、最小の「生の属性値」形)の6件確認。HTTP Request(要パッケージ追加、未確認のまま)/Word/PDF/Databaseはまだ未着手 |
| 8 | Invoke Workflow File(サブワークフロー呼び出し)とLibraryプロジェクト | **ファイルパス直接参照は完了**(知見12: `ui:InvokeWorkflowFile`+`.Arguments`のキー付き辞書、`<Literal>`vs`[...]`の使い分けに新たな仮説)。**Library参照経由の呼び出しは未着手** |
| 9 | 例外処理の全体像(TryCatch本体 + プロジェクト設定の自動リトライ) | **TryCatch本体は完了**(知見9)。Project Settingsダイアログ(General/Workflow Analyzer/Activities Settings各種)を確認したが、インストール済みバージョン(Studio app-21.4.4)には自動リトライやグローバル例外ハンドラに相当する設定項目が見当たらなかった——より新しいStudioバージョンのみの機能か、または別の仕組み(テンプレート経由でのGlobal Exception Handlerワークフロー追加等)である可能性 |

## P2: 本番運用フローへの対応・戦略判断

| # | 項目 | 状況 |
|---|---|---|
| 10 | REFramework(Robotic Enterprise Framework)のXAML構造 | 未着手 |
| 11 | Coded Workflows(C#/VB code-behindの新機能) | 未着手——もし広く使われていれば、WFアクティビティ木の変換よりコード→コード変換の方が簡単という切り口の転換もあり得る |
| 12 | Object Repository(`.objects/`配下の構造化セレクタストア) | 未着手。今回のサンプルプロジェクトでは「Object Repositoryを有効化しますか」という案内のみ確認(知見11とは別方式) |
| 13 | Orchestratorアセット/キュー連携アクティビティ | 未着手 |
| 14 | `.nupkg`パッケージ構造 | 未着手 |

## P3: 長期的・ニッチ、または明示的に対象外にする判断を早めにするための調査

| # | 項目 | 状況 |
|---|---|---|
| 15 | State Machineワークフロー種別 | 未着手(優先度低のまま) |
| 16 | Computer Vision/画像ベースセレクタ | 未着手(`# TODO`対象として扱う方針は維持) |
| 17 | Marketplaceカスタムアクティビティパッケージ | 対象外方針を維持(`# TODO`) |
| 18 | C#式言語プロジェクト(`expressionLanguage: "CSharp"`) | 未着手 |
| 19 | Test Suite(データ駆動テスト・アサーション) | 未着手(優先度低のまま) |

## 次の一手の候補(優先度順)

1. **P0 #1の残り**(While/DoWhile/Parallel/Break)——制御フローを完全に揃える
2. **P1 #8**(Invoke Workflow File)——PADのサブフローに相当する重要な構造
3. **P0 #2**(VB式変換ルールの体系化)——ここまでの実データ(`[...]`記法・`<Literal>`要素・
   比較演算子`=`等)を整理してドキュメント化するだけでも価値がある
4. **P1 #7**(高頻度アクティビティ)——PADで既に116件実機キャプチャ済みのFile/Folder等との
   概念対応が強く、知見の使い回しが効く
