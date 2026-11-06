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
1. **UI Automation Classic基本活動の残り**(Type Into/Get Text/Select Item/
   Find Element等): Clickで確立済みのGitHub検索手法(知見100)がそのまま
   転用できる。実務頻度が最も高いカテゴリの穴を塞ぐ。
2. **Database活動**(Execute Query/Execute Non Query等): 実務頻度が高く
   pad2pyに丸ごと欠けている。DataTable型のPython表現(pandasか素のlist of
   dict か)を1つ決めれば実装パターンはHttpClient/Excelと同型。
3. **Excel Classicの残り**(Read Range/Write Range等)・**汎用Mail
   (SMTP/POP3/IMAP)**: 既存の実装パターン(openpyxl/win32com)をそのまま
   拡張するだけで、追加調査コストが最も低い。
4. **HTTP Requestのlegacy/current区別・SOAP Request**: HttpClientの基盤が
   あるので差分実装で済む。

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
