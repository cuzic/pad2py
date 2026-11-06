# UiPath機能カタログと移行価値の優先順位付け(2026-11-05)

ユーザー依頼「UiPathが持つ機能を網羅的に調査」→「体系的な機能リストを作った上で、
移行する価値があるものを優先順位をつけてください」への回答。2本の調査フォーク
(`uipath-platform-survey`: エンタープライズ製品スイート全体、
`uipath-activities-survey`: Studio/アクティビティ層の深掘り)の結果を統合し、
pad2pyの既存の意思決定([uipath_transpiler_roadmap.md](uipath_transpiler_roadmap.md)
Phase 1のTier1確定・Phase 8のスコープ外決定、
[uipath_migration_priorities.md](uipath_migration_priorities.md)のP0〜P3)との
整合を取って再構成した。

**位置づけの大前提**: pad2pyは「`.xaml`ファイル(WFワークフロー定義)をPythonへ
変換するトランスパイラ」である。UiPathという製品は`.xaml`より遥かに広い
エンタープライズSaaSスイートだが、**`.xaml`に表現が無いものはそもそも
「移行」という操作の対象にならない**(翻訳元が存在しない)。したがって
優先順位付けの第一軸は「XAMLに表現が残るか」であり、その内側でのみ
「実務での出現頻度」「実装コスト」で順位を付ける。

---

## Part A: エンタープライズ製品スイート全体(俯瞰)

`uipath-platform-survey`フォークの結果を要約。详细な出典・確信度は
フォークの原文(このセッションのtask-notification)を参照。

| レイヤー | 製品/機能 | 一言 | XAML表現 | 移行対象か |
|---|---|---|---|---|
| 実行基盤 | Robot(Attended/Unattended)、Assistant | ワークフローを実行するランタイムそのもの | 無し(実行環境の話) | 対象外 |
| 実行基盤 | 配布モデル(Cloud/Automation Suite/Standalone) | ホスティング形態の違い | 無し | 対象外 |
| オーケストレーション | Orchestrator(キュー/アセット/トリガー/環境) | ロボット群の集中管理 | **部分的**(`Get Asset`/`Get Credential`/`Get Queue Item`等の呼び出し活動はXAMLに現れる) | 呼び出し活動のみ条件付き対象(§C参照) |
| オーケストレーション | Maestro(BPMN/Case/Flow、2025新設) | ロボット・AIエージェント・人間を1つの業務プロセスとして統括する上位レイヤー | BPMN/DMN等の別フォーマット(WFのXAMLではない) | 対象外 |
| AI/GenAI | AI Center | MLモデルのホスティング・配信基盤 | モデル呼び出し活動はXAMLに現れるが、モデル自体はXAML外 | 対象外(呼び出し活動も実運用デモ依存で低優先) |
| AI/GenAI | Document Understanding | OCR+分類+抽出のドキュメント処理パイプライン | `UiPath.IntelligentOCR.Activities`の活動群はXAMLに現れる | §Dで評価(効果大・コスト大) |
| AI/GenAI | Communications Mining(→IXP傘下) | 通信データのNLP分析 | 無し(データ分析SaaS側の話) | 対象外 |
| AI/GenAI | Autopilot、Agent Builder/Agents | GenAIによる低コード生成支援・単体エージェント構築 | 無し、またはAgent定義は別フォーマット | 対象外 |
| 発見 | Process Mining | システム横断のイベントログからプロセスを可視化 | 無し(分析SaaS) | 対象外 |
| 発見 | Task Mining | 特定タスクのデスクトップ操作記録→PDD/XAML雛形生成 | **出力側**がXAML雛形(入力がXAMLではない) | 対象外(生成支援ツールであり移行元ではない) |
| 低コードApp/データ | Apps、Data Service/Data Fabric | 業務アプリ構築・ノーコードデータモデリング | 無し | 対象外 |
| 低コードApp/データ | Action Center(Human-in-the-loop) | 人間承認待ちのタスク差し込み | `Create Form Task`等の活動はXAMLに現れる可能性 | 低優先(§D) |
| 分析 | Insights | 運用ダッシュボード・BI | 無し | 対象外 |
| テスト | Test Suite/Test Manager/Test Cloud | アプリ・RPA双方のテスト管理 | `UiPath.Testing.Activities`の一部(アサーション・テストデータ生成)はXAMLに現れる | 低優先(§D) |
| 統合 | Integration Service | サードパーティSaaSへの管理済みコネクタ | `UiPath.IntegrationService.Activities`経由でXAMLに現れる | 対象外(デマンド駆動、§Eのロングテールと同じ扱い) |
| 統治 | Automation Hub、Marketplace(2種類が同名で存在する点に注意) | 組織内のアイデア管理・社内/公開カタログ | 無し(Marketplaceのカスタム活動パッケージ自体はXAMLに現れるが、パッケージごとに個別評価) | 対象外(個別パッケージはデマンド駆動) |
| 未確認領域 | ScreenPlay、Cartographer、Delegate、AI Trust等 | タグライン止まりで機能未確認 | 不明 | 評価不能、現時点では対象外 |

**結論**: エンタープライズ製品スイートの大部分(Orchestrator本体・Maestro・AI Center・
Process/Task Mining・Apps・Data Service・Insights・Test Cloud・Integration Service・
Automation Hub)は、**そもそもXAMLという翻訳元を持たないため、トランスパイラの
対象になり得ない**。例外は「Orchestratorへの呼び出し活動」「Document
Understanding/Testingの一部活動」のように、SaaS機能の一部がXAML上の
アクティビティとして顔を出すケースのみで、これらはPart Bの個別活動として評価する。

---

## Part B: Activities/Studio層の体系的カタログ

`uipath-activities-survey`フォークの結果を要約。**pad2pyの既存Tier1確定リスト**
(roadmap.md Phase1: Assign/If/ForEach/TryCatch/Switch/While/DoWhile/Break/Parallel/
MessageBox/HttpClient/Excel Application Scope+Write Cell/Send Outlook Mail/Click/
Invoke Workflow File/Append Line/Read Text File/Invoke Code/Set To Clipboard)は
「実装済み」として明示する。

### B1. ワークフロー/プロジェクト構造
- **ダイアグラム種別4種**: Sequence(✅実装済み)、Flowchart(✅実装済み、知見100-101)、
  State Machine(❌未実装、Phase1でスコープ外の意思決定済み)、Global Exception Handler
  (❌未調査)
- **プロジェクト種別**: Process(✅対応)、Library(✅対応)、Template/Tests(❌未対応、
  低優先)
- **式言語**: VB.NET(✅対応)、C#(❌未対応、`uipath_migration_priorities.md` P3#18で
  旧Studioでは未確認、新StudioはVM長期ブロックで調査中断中)
- **REFramework**: State Machineベースの4状態テンプレート(Init/Get Transaction
  Data/Process Transaction/End Process)。フォークの指摘通り**実務での出現頻度が
  非常に高い**(無人ロボットの実運用デファクト標準)。State Machine未対応が
  REFrameworkへの対応をブロックしている根本原因。
- **Coded Workflows**: C#の`.cs`ファイル、XAMLではない。Phase8で既にスコープ外
  決定済み、変更なし。

### B2. System パッケージ(制御フロー・ファイル操作)
制御フロー系はTier1でほぼ実装済み。ファイル操作(Copy File/Folder、Create
Folder/File、Delete、File Exists、Compress/Zip)はAppend Line/Read Text File以外
未対応。DataTable/List操作系も未対応(優先度は実務頻度次第、未評価)。

### B3. UI Automationパッケージ(最大・最も重要な領域)
- **Modern基本活動(Click/Type Into/Get Text/Select Item等)とClassic活動
  (pad2pyの対象はこちら)**: フォークが「実務で最も出現頻度が高いカテゴリ」と
  明言。pad2pyは既にClick(ClickType/MouseButton/CursorPosition/DelayBefore)を
  実装済みで、この層の中核はカバーできている。Type Into/Get Text/Select Item等の
  **同系統の他の基本活動は未確認・未実装**——Clickで確立したGitHub検索手法
  (知見100)がそのまま転用できるはずで、投資対効果が最も高い。
- **Object Repository**: 知見31・39で構造は判明済みだが、Phase1でClassicのみに
  スコープ限定した決定は維持(Phase8)。
- **Computer Vision/OCR**: Citrix等で選択子が使えない環境向け。別エンジン
  (CVサーバー接続やOCRライブラリ)への依存があり実装コストが高く、一般的な
  移行対象としては優先度低(フォークの評価に同意)。

### B4. ドキュメント/ファイル形式パッケージ
- **Excel Classic**: Write Cell/Excel Application Scopeは✅実装済み。Read Range/
  Write Range/Append Range等の**残りの活動群は未実装**——openpyxlへの対応
  パターンは確立済みなので低コストで拡張可能。
- **Mail**: Send Outlook Mailは✅実装済み(win32com)。汎用SMTP/POP3/IMAP活動は
  未実装だが同じパターンが転用できる。
- **Word/PDF**: 未実装。フォークは「中程度の実務頻度、自己完結的で実装コストも
  中程度」と評価。
- **Document Understanding(`UiPath.IntelligentOCR.Activities`)**: タクソノミー
  管理・分類・抽出という独立した学習コストの大きい領域。フォークの評価
  (「実装コスト大・一般的な移行対象としての頻度は相対的に低い」)に同意。

### B5. システム統合パッケージ
- **Database(`UiPath.Database.Activities`)**: Execute Query/Execute Non Query/
  Bulk Insert等。フォークは「エンタープライズRPAで極めて高頻度、pad2py未着手」と
  明言——**明確な実装ギャップ**。
- **HTTP/REST/SOAP**: HttpClientのBody/Headersは✅実装済み(知見96/104)。
  Legacy/current HTTP Requestの区別、SOAP Request、XML/JSONヘルパー活動は
  未実装。
- **Terminal/Mainframe**: ニッチだが金融・保険業界で根強い。安全なTODOフォール
  バックとしての対応で十分(フル実装の優先度は低い)。
- **SAP/Citrix/Java**: 専用活動パッケージが(ほぼ)存在せず、汎用UI Automation/CV
  活動の対象として既にカバーされる構造——個別の実装項目は不要。

### B6. 資格情報/Orchestrator連携活動
Get Asset/Get Credential/Get Queue Item/Run Job等。ライブなOrchestrator接続に
依存するため、静的なXAML→Pythonの変換では「設定値ルックアップへのスタブ
+TODOコメント」が現実的な落とし所(Phase8の既存方針と一致)。フル実装は
別イニシアチブ。

### B7. テスト活動
`UiPath.Testing.Activities`のアサーション・テストデータ生成系。実務の本流
ワークフローでの出現頻度は低い(フォーク評価に同意、`uipath_migration_priorities.md`
P3#19と同じ結論)。

### B8. Marketplaceパッケージ
ロングテールで分散しており汎用的な優先順位付けができない。実際に遭遇した
パッケージがあればその時点でデマンド駆動で評価する方針を維持。

---

## Part C: 移行価値の優先順位(結論)

XAML表現の有無(第一軸)→実務頻度(第二軸)→実装コスト(第三軸)で並べた、
次に着手すべき順序。既存のTier1(実装済み)を前提に、「次の一手」として
提案する。

### Tier A: 次に着手すべき(高価値・低〜中コスト、既存パターンの横展開)
1. **(着手済み、2026-11-05〜06)** **UI Automation Classic基本活動の残り**
   (Type Into/Get Text/Select Item/Element Exists): Clickで確立済みの
   GitHub検索手法(知見100)がそのまま転用できた(知見110-113)。
   `Find Element`/`Get Full Text`等、さらに残りの基本活動があれば継続可能。
2. **(着手済み、2026-11-06)** **Database活動**(Execute Query/Execute
   Non Query/Connect/Disconnect): 知見114でSQLiteプロバイダのみ実装
   (`sqlite3`標準ライブラリ)。`BulkInsert`/`BulkUpdate`/
   `DatabaseTransaction`/`InsertDataTable`、SQLite以外のプロバイダ
   (SQL Server/PostgreSQL/MySQL等、要追加のPythonドライバ判断)が残課題。
3. **(着手済み、2026-11-06)** **Excel Classicの残り**(Read Range/Write
   Range)・**汎用Mail(SMTP/POP3/IMAP)**: 知見115でRead Range/Write
   Rangeを実装(`openpyxl`、`list[dict]`表現、既存パターンの拡張)。
   知見116で`SendMail`(汎用SMTP送信)を実装(`smtplib`+
   `email.mime.text`、確認済みの唯一の構成=暗黙SSLのみ)。
   残課題: 特定範囲指定(`Range`が空以外)・`StartingCell`が`"A1"`以外・
   Read Cell/Read Column/Read Row等の他のRead系活動・`GetIMAPMailMessages`/
   `GetPOP3MailMessages`(受信系、まだ未着手)・`SendMail`の平文/STARTTLS/
   OAuth/添付。
4. **HTTP Requestのlegacy/current区別・SOAP Request**: HttpClientの基盤が
   あるので差分実装で済む。

**新しい調査源(知見114で発見)**: `marcelocruzrpa/uipath-ai-skills`
リポジトリの`uipath-core/references/studio-ground-truth/`配下に、
実機Studioから自動収集されたXAMLリファレンス集(Database/Excel/Mail/
PDF/Persistence/System/Testing/UIAutomation/WebAPIの各パッケージを
カバー)が存在する。属性の完全な語彙確認に有用——項目2・3・4の残作業
でも優先的に調査すること(ただしpopulated時の実例は別途実プロジェクトの
リポジトリで確認する必要がある、知見114参照)。

### Tier B: 単体では最大の投資だが、見返りも最大
5. **State Machine対応**: Phase1でスコープ外にした決定の再検討候補。単体では
   このリストの中で最も実装コストが大きい(新しいダイアグラム種別+遷移グラフの
   コード生成)が、**REFrameworkという実務でのデファクト標準テンプレートを
   アンロックする唯一のボトルネック**であり、フォークも「実務での出現頻度を
   考えると不均衡に価値が高い」と評価している。Flowchartのdispatch-loop
   パターン(知見100-101)が設計の土台として転用できる可能性があり、以前
   想定していたよりコストは下がっているかもしれない。

### Tier C: 中価値・自己完結・ニッチ
6. **Word/PDF活動**: 実務頻度は中程度、実装は自己完結的。
7. **Terminal/Mainframe**: フル実装ではなく安全なTODOフォールバックで十分。

### Tier D: 低優先(効果対コストが悪い)
8. **Computer Vision/OCR活動**: 外部エンジン依存でコストが高く、対象となる
   実務頻度(主にCitrix環境)は限定的。
9. **Document Understanding**: 独立した学習コストの大きい製品領域。
10. **Testing活動**: 本流ワークフローでの出現頻度が低い。

### Tier E: 構築by construction対象外(既存のPhase8決定+今回追加分)
- **エンタープライズ製品スイート全体**(Orchestrator本体・Maestro・AI Center・
  Process/Task Mining・Apps・Data Service・Insights・Test Cloud・Integration
  Service・Automation Hub・Communications Mining・Autopilot/Agent Builder):
  Part Aの通り、XAMLという翻訳元を持たない
- **Coded Workflows**(C#、Phase8既存決定)
- **Object Repository / Modern selector**(Phase8既存決定、Classicのみ継続)
- **Orchestratorのライブなキュー/アセット/トリガー連携のフル実装**(Phase8
  既存決定、スタブ+TODOのみ)
- **Marketplaceのロングテールパッケージ**・**外部Library依存の完全解決**
  (`.nupkg`内にソースが無いため.NETデコンパイルが別トラック、Phase8既存決定)

---

## 推奨する次のアクション

Tier Aの4項目はいずれも既存パターンの横展開で、個別に知見ログへ追記しながら
実装できる(知見96/104のHttpClient、知見97のExcel、知見98/103のOutlookと同じ
進め方)。Tier Bの State Machine は単体の意思決定イベント(Phase1の再検討)
として扱うのが良く、着手前に「Flowchartのdispatch-loopパターンがState
Machineにどこまで転用できるか」を小さく調査するステップを挟むのが筋が良い。

### 実機XAMLに対する実際のコード生成の検証(知見117で導入、2026-11-06)

自分で推測した優先順位(Tier A/B/C/D)だけでなく、`generate_python()`/
`generate_project_from_json()`をGitHub上の外部実プロジェクトに対して
直接実行し、実際に何が`# TODO`に倒れるかを確認する手法を導入した——
自分のテストフィクスチャとは独立の、より強い根拠になる。この手法で
`CopyFile`/`BuildDataTable`/`ExcelAppendRange`(いずれも実装済み)を
発見し、さらに`ExcelWriteRange`の実在バグ(非空シートへの書き込みで
`StartingCell`の位置を無視する)も発見・修正できた。今後の新しい活動を
選ぶ際は、Tier A/B/C/Dのリストに加えてこの手法も定期的に併用すると良い
(候補: 別のGitHubリポジトリから複数の実プロジェクトを集めてバッチで
実行し、`# TODO`の頻度を集計する、といった拡張も考えられる)。

**AddDataRowの保留(将来のアーキテクチャ候補)**: `AddDataRow`は
`ArrayRow`(位置指定の値)を対象`DataTable`へ追加する活動だが、
Pythonの`list[dict]`表現では列名が必要で、それは別の`BuildDataTable`
活動の`TableInfo`から来る——つまりノード間でDataTableの列スキーマを
追跡する仕組みが必要になる。これは既存の`invoke_resolver`/
`out_arg_resolver`(Invoke Workflow Fileの解決)と同種の、cross-node
resolverの新設が必要なケース。今回は見送ったが、同種のDataTable操作
活動(`FilterDataTable`/`SortDataTable`/`MergeDataTable`等)が今後増える
ことを見据えると、一度「DataTableスキーマ解決パス」を設計する価値は
ある。

**追記(知見195、2026-11-06、調査のみ・コード変更無し)**: `Filter
DataTable`/`AddDataColumn`/`RemoveDataColumn`/`SortDataTable`/
`MergeDataTable`を実機サンプル+ground-truthコーパスで再調査した結果、
一括保留ではなく活動ごとに難易度差があることが分かった。
**次の実装候補として有望な順**: ①**(完了、知見196)** ~~`LookupDataTable`~~
(新規発見、`DataTable`+`LookupColumn(Index/Name)`+`LookupValue`+
`TargetColumn(Index/Name)`→単一セル値+行インデックスの出力のみで、
列スキーマ全体を追跡しなくても対応できる見込み)→実装済み、見立て通り
表現非統一性問題の影響を受けなかった②**(完了、知見197)**
~~`GenerateDataTable`~~(新規発見、テキストを区切り文字/固定幅で
DataTableへ変換——既存のDataTableを読まず新規に構築するため出力
表現を自分で選べる)→実装済み、`csv.DictReader`/`str.split()`の
二択で対応、固定幅モードは実機未確認のため見送り
③`RemoveDataColumn`/`AddDataColumn`(スキーマ変更のみで行の値は読まない
——知見183の`isinstance(row, dict)`判定と組み合わせればdict行限定で
部分対応できる可能性)。**依然保留**: `SortDataTable`/
`FilterDataTable`/`JoinDataTables`(新規発見の3件目)は列名ベースの
値アクセスが本質的に必要で、このスキーマ解決パスの設計を待つ。
`SortDataTable`は実機で属性名`Order`(ground-truthの`SortOrder`とは
別名)+値`"Decending"`(誤字)という version skew も確認済み——将来
実装時はどちらの属性名も吸収する必要がある。詳細は知見195参照。

**`row(...)`添字の変数スコープ追跡(知見74で見送り、知見126で実需要を
確認・将来のアーキテクチャ候補)**: VB.NETの`識別子(引数)`構文は関数
呼び出し・配列添字・DataTable行の列アクセス(`row("列名")`)のいずれも
同じ見た目になり、静的型情報無しでは構文だけで判別できない(知見74)。
知見126で`ForEachRow`の反復変数に対する`row(...)`呼び出しという実需要
を確認したが、解消には現在の`render_expr`/`_render_node`(式単体を
文脈無しに文字列化する純粋関数)に「この識別子はどのスコープでDataRow
型として束縛されたか」という変数スコープ情報を新たに通す仕組みが必要
——`AddDataRow`と同じ「cross-node/スコープ resolverの新設が必要」な
ケースとして一緒に設計を検討する価値がある。

**新しい参照データ源: `marcelocruzrpa/uipath-ai-skills`のground-truth
コーパス(知見128で発見、2026-11-06)**: `uipath-core/references/
studio-ground-truth/`配下に、UiPathパッケージ名・バージョンごとに
整理された504件の単体活動`.xaml`参照フィクスチャがある
(`UiPath.Database.Activities/2.0`(10件)・`UiPath.Excel.
Activities/3.4`(117件、未検証)・`UiPath.Mail.Activities/2.8`
(45件、未検証)・`UiPath.PDF.Activities/3.25`(12件、知見193で
`ReadPDFText`/`ReadPDFWithOCR`+`upap:`名前空間系6件を検証済み、
残り`ExportPDFPageAsImage`以外は概ね確認)・`UiPath.
Persistence.Activities/1.4`(10件)・`UiPath.System.
Activities/25.10・26.2`(199件、うちDataTable系9件を知見195で検証済み・
残り大半は未検証)・`UiPath.Testing.Activities/25.10`(23件)・
`UiPath.UIAutomation.Activities/25.10`(76件、知見194で`AnchorBase`が
このコーパスに含まれないことのみ確認済み・残りは未検証)・
`UiPath.WebAPI.Activities/2.4`(12件))。各ファイルは
`<Activity x:Class="...">`直下に活動1つだけの最小形
(`parse_workflow_file`が要求する`Sequence`/`Flowchart`ラッパー無し
——`parse_activity()`+`_generate_node()`を直接呼ぶ必要がある)。
値はほぼ全て未設定(`{x:Null}`)のデフォルトのみのため、新しい値の
変換ロジックを実装する根拠にはならない(属性**名**の一覧としては
権威的で有用)——このコーパス単独で活動を実装せず、別途実機
`Main.xaml`で非デフォルト値の使用例を見つけてから組み合わせて使う。
検証済み: `UiPath.Database.Activities`10件+`UiPath.WebAPI.
Activities`の`HttpClient`/`SerializeJson`/`DeserializeJsonArray`
(既存実装の既定値耐性を確認、クラッシュ無し)。未検証(今後のtick候補、
残り約430件): `UiPath.Excel`/`Mail`/`System`/`Testing`/
`UIAutomation.Activities`。

このコーパスで属性名を確認した新規未実装活動11件(実データ待ち):
`BulkInsert`/`BulkUpdate`/`InsertDataTable`/`DatabaseTransaction`
(`UiPath.Database.Activities`)、`SerializeJson`/`DeserializeJson`/
`DeserializeJsonArray`/`DeserializeXml`/`ExecuteXPath`/`GetNodes`/
`GetXMLNodes`/`GetXMLNodeAttributes`/`NetHttpRequest`
(`UiPath.WebAPI.Activities`)。

### 【要検討】C#式言語対応(知見129で実機証拠を発見、2026-11-06)

これまで「VB.NET固定」としていた前提に対する実機反証を発見した——
UiPath公式`skills`リポジトリの`tests/tasks/uipath-troubleshoot/
activity-packages/`配下に240件の`Main.xaml`があり、サンプリングした
7件全てが`expressionLanguage: "CSharp"`だった。VB.NETの`[...]`角括弧
省略記法の代わりに`<CSharpValue>`/`<CSharpReference>`というC#専用の
プロパティ要素形で直列化される。現状は`# TODO`への保守的フォールバック
が正しく働く(クラッシュ無し)が、カバレッジは大幅に下がる。

対応には(1)プロパティ要素形の一般解析、(2)C#式テキスト専用の新しい
文法(`uipath_expr`はVB.NET文法専用)、(3)ワークフロー単位の言語判定、
という「新しい式言語バックエンドの追加」が必要——`AddDataRow`・
`row(...)`スコープ追跡より一段大きいスコープの意思決定であり、着手
するかどうか自体がユーザーとの意思決定事項になりうる。この240件の
corpus(`UiPath/skills`リポジトリ、未使用)は対応検討時の一次データ源
として再利用する価値が高い。詳細は知見129参照。

### 【最優先・重大】識別子の大文字小文字正規化(知見130で発見、2026-11-06)

`AddDataRow`(知見122)・`row(...)`(知見126)に続く3件目の「式レンダ
リングにスコープ情報が必要」な実需要だが、**重大度は最も高い**——
他の2件は保守的に`# TODO`へ倒れるのに対し、こちらは**構文的に正しいが
意味的に誤ったコードを静かに生成する**。VB.NETは識別子の大文字小文字を
区別しないが、本トランスパイラの`render_expr`/`_render_node`は各識別子
参照をXAML中のテキストのまま素通りさせる純粋関数のため、同じ変数が
異なる大文字小文字表記(`out_RequirementLanCur`宣言→本体では
`Out_RequirementLanCur`参照、実機で発見)で参照されると2つの別々の
Python変数が生成されてしまう。通常のローカル変数でも理論上同じ問題が
起こりうる一般的な懸念。次に「スコープ対応のコード生成アーキテクチャ」
(`AddDataRow`のDataTableスキーマ解決・`row(...)`のDataRow型追跡と
統合して設計する価値がある)に着手する際は、この識別子大文字小文字
正規化を**最優先**の要件として含めるべき。詳細は知見130参照。
