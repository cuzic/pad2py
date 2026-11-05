# UiPath→Python トランスパイラ完成までのロードマップ

本ドキュメントは「研究フェーズ(知見1〜36の実機確認)」から「実装フェーズ」へ
移行するための全体像を整理したもの。[design/uipath_xaml_findings.md](uipath_xaml_findings.md)・
[design/uipath_migration_priorities.md](uipath_migration_priorities.md)・
[design/uipath_vb_expression_mapping.md](uipath_vb_expression_mapping.md)が
「何がどう直列化されるか」の実機検証ログであるのに対し、本ドキュメントは
「それを踏まえてどういう順序で何を作るか」を記す。

## 現状整理(2026-11-05時点)

**できていること**: XAMLの構造(制御フロー一式・VB式・Variables/Arguments・
project.json・Library・REFramework)はP0がほぼ完了。VB式変換ルール
(P0 #2)も知見32・36で主要演算子・型変換関数・三項If・文字列補間・
`String.IsNullOrEmpty`・クォートエスケープまで実機確認済み。

**まだゼロなもの**: UiPath側には**パーサー・コード生成・実行時ライブラリが
1行も存在しない**。PAD側の`dump_daemon/pad_dsl`・`pad_expr`・`pad_codegen`・
`pad_action_lib`(合計約9500行の実装+約7200行のテスト、README.md「構成」
節参照)に相当するものが無い。知見1〜36は全て「研究フェーズ」の産物で、
「実装フェーズ」はこれから丸ごと始まる。

PAD側との比較で言うと、UiPathは**IR取得の入口は易しいが、カバーすべき
表面積ははるかに広い**(知見1で確認済みの通り、PADはクリップボードDSLの
裏技が必須だったのに対し、UiPathの`.xaml`はただのXMLファイルなので
そのままパースできる)。一方でアクティビティ種類・セレクタ体系・プロジェクト
形態の複雑さはPADの比ではない。

## Phase 0: 残る研究のクローズ

VM(UiPath Studio実機)に依存するものと依存しないものを分けて進める。

- **(完了)** `And`/`Or`非短絡評価の安全なPython変換アルゴリズム設計。
  `&`/`|`ビット演算子への変換、両オペランド括弧必須、をPython実挙動で
  検証し確定(design/uipath_vb_expression_mapping.md参照)
- **(完了、一部未解決点あり)** セレクタの意味論調査(知見37)。
  Classic Selector(WND/CTRL/WEBCTRL)の属性語彙・Dynamic Selector
  (`{{Value}}`)・Anchor Baseは公式ドキュメントで把握。**ただしModern
  活動の`Fuzzy selector`/`Strict selector`の実XAML直列化形は公式
  ドキュメントに記載が無く未確認のまま残った**——旧Studio
  (2021.4.4)でModern活動を1つ置けば新Studio問題を待たずに確認できる
  可能性があり、次の候補タスクとして記録
- **VM依存、新Studio問題(知見33〜35)の解消待ち**:
  - Coded Workflows(P2 #11)の実際のC#記法とXAMLとの連携方法
  - Object Repository(P2 #12)の`.objects/`構造とModern selectorのXAML表現
  - C#式言語プロジェクト(P3 #18)の新Studioでの選択UI有無

## Phase 1: スコープ決定(技術調査ではなく意思決定)【決定済み、2026-11-05】

PAD側は段階的にTier1→Tier2→Tier3とアクション範囲を広げたが、UiPathは
標準アクティビティだけで数百、Marketplace/NuGet込みだと際限がない。
以下、ユーザーの意思決定により確定:

1. **対象ワークフロー種別: Sequence/Flowchartのみ**。State Machine
   (2パス参照解決が必要、知見30)はv1スコープ外とし、Phase 8の「明示的に
   スコープ外とするもの」に送る
2. **対象プロジェクト種別: Processのみ**。Library(公開済み`.nupkg`に
   元の`.xaml`が含まれないという技術的制約、知見28)はv1スコープ外
3. **初期カバー対象アクティビティ(Tier1相当): 知見で実機確認済みの
   活動一式**——`Assign`/`If`/`ForEach`/`TryCatch`/`Switch`/`While`/
   `DoWhile`/`Break`/`Parallel`/`MessageBox`/`HttpClient`
   (`ui:HttpClient`)/`Excel Application Scope`+`Write Cell`/
   `Send Outlook Mail Message`/`Click`/`Invoke Workflow File`/
   `Append Line`/`Read Text File`/`Invoke Code`/`Set To Clipboard`

競合状況の再確認(Robocorp Converter Acceleratorの保守状況、UiPathの
`uip` CLI/AI-agent向けSkill展開の進捗)は、本格実装着手の判断材料としては
後回しでよいと判断——今は技術調査(Phase 0)を優先する。

## Phase 2: ランタイム方針の確認

[[pad2py_runtime_direction]](メモ)の「generator関数+replayジャーナル」
方針をUiPath側にも適用できるか検討する。制御フロー構造(Sequence/If/
ForEach/TryCatch/Switch/Parallel/While/DoWhile)は、知見5・6・9・11・14・
18〜21で確認済みの通りPADの`BlockNode`/`ConditionalNode`と同形のIRに
落とせる見込みが高く、**基本的には同じアーキテクチャを流用できる**と
予想される。State Machineだけは別扱い(名前→ノードのマップを先に構築し、
`x:Reference`を解決してから組み立てる2パス方式、知見30)が必要で、
Python側でも明示的なステートマシンループへの変換が要る。

## Phase 3: XAMLパーサー(IR抽出)

PADよりここは楽——クリップボードDSLの裏技が不要で、`.xaml`はただのXML。
`lxml`(既存依存)で直接ツリーウォーカーを書き、`pad_dsl`相当のIRへ
変換する。実装すべきもの:

- **XAMLツリーウォーカー**: `<Sequence>`/`<If>`/`<ForEach>`等の構造を
  `BlockNode`/`ConditionalNode`風のIRへ変換。知見13の原則
  (`x:TypeArguments`が`x:Object`かどうかで`[...]`角括弧式/`<Literal>`
  要素/生テキストのどれで来るか決まる)を踏まえた分岐が必須
- **VB.NET式パーサー**(`pad_expr`相当): 知見32・36で構文が出尽くした
  範囲——リテラル・変数参照・9演算子(`Mod`/`\`/`^`/`And`/`AndAlso`/`Or`/
  `OrElse`/`Xor`/`Not`)・型変換関数(`CStr`/`CInt`/`CDbl`/`CBool`)・
  `IsNot`/`Nothing`/`IsNothing`・三項`If(cond,t,f)`・文字列補間
  `$"...{expr}..."`・`String.IsNullOrEmpty`——をカバーするLark文法を
  新規に書けば十分。フルVB.NET文法の実装やRoslyn連携は過剰
- **State Machine用の2パス参照解決**(`x:Name`→`x:Reference`マップ構築)

## Phase 4: アクティビティ→Pythonコード生成(`pad_action_lib`相当)

Phase 1で決めたTier1アクティビティから順にコード生成ルールを実装する。
PAD側の`codegen_coverage.py`のようなカバレッジ計測ツールを作り、優先度順に
埋めていく。未対応アクティビティは架空のAPI呼び出しをでっち上げず
`# TODO`を出す(`pad_codegen`・`raw_fallback.py`と同じ正直さの方針)。

**ここが最大の未解決問題**: **セレクタの意味論マッピング**。UiPathの
セレクタは`<wnd app='notepad.exe' cls='Notepad' .../><ctrl name='...'
role='editable text' />`という独自XML+fuzzy matching+Computer Vision
フォールバックという体系を持つ(知見9の`ui:Click`構造確認時に実例を
見ているが、意味論自体は未調査)。これをpywinautoのセレクタ体系
(`title`/`control_type`/`auto_id`等)にどう落とすかは、知見1〜36の
どこにも調査が無い、新規に立てるべき調査トラック。Click/Type Into/
Get Text等のUI自動化アクティビティを扱う以上避けて通れない。
選択肢:
  - (a) UiPathのセレクタ属性をできる範囲でpywinauto検索条件に素朴に
    マッピングし、fuzzy/CVフォールバックは最初から非対応と明言する
  - (b) UiPathのセレクタ構文パーサー自体を実装し、実行時に独自の
    マッチングロジックを持たせる(pywinautoより重い実装になる)
  - 現実的には(a)から始めて実データで不足を確認しながら広げるのが
    PAD側の既存方針(段階的カバレッジ拡大)と一貫する

## Phase 5: Variables/Arguments/スコープのコード生成

構造は知見8・12で確定済み。VBのコンテナ単位スコープ
(`<Container.Variables>`配下)→Pythonのレキシカルスコープ(クロージャ)
への変換を実装する。知見17で確認した「Sequenceスコープの変数をクロージャ
越しに参照できずコンパイルエラーになる」意味論の逆(VB側の制約がPython
生成時にどう影響するか)も踏まえる必要がある。

## Phase 6: プロジェクト組み立て(project.json→複数ファイル統合)

Main.xaml+サブワークフローファイル+project.jsonから1つのPythonパッケージ
を生成する。

- `Invoke Workflow File`(知見12)→関数呼び出しへの変換、ワークフロー引数
  (`<x:Members>`宣言)→Python関数シグネチャへの変換
- Library参照(知見26・27)→CLR名前空間エイリアス経由の呼び出し→Python
  モジュール参照への変換。ただし**ソースが手元に無い外部Library(他人の
  Library・Marketplace経由)は`.nupkg`からの復元が技術的に不可能**
  (知見28、コンパイル済み`.dll`のみでXAMLソースを含まない)。この場合は
  PAD側の`raw_fallback.py`と同じ「正直にTODOスタブを出す」方針を踏襲し、
  .NETデコンパイルという全く別の技術トラックには踏み込まない

## Phase 7: 検証基盤

PAD側の`test_round_trip.py`・`trace_compare.py`相当のものを作る。
`xaml_probe`(および`xaml_probe_lib`・`xaml_probe_reframework`)を
体系的なフィクスチャ集に育て、パース→コード生成→期待Pythonの比較を
回帰テスト化する。知見ごとに1つ以上の実機XAMLフィクスチャが既にある状態
なので、素材自体はかなり揃っている。

## Phase 8: 明示的にスコープ外とするもの(v1では着手しない)

- **Coded Workflows**: C#→Pythonという全く別のコード生成トラック。
  WF活動木→Python変換のノウハウが再利用できない
- **Object Repository / Modern selector**: 有効化条件(知見31)は分かった
  が、XAML表現自体が未調査。新Studio問題(知見33〜35)の解消待ち
- **State Machine**: Phase 1でスコープに含めると決めた場合のみ着手
- **Orchestratorのキュー/アセット/トリガー連携**: 実際のOrchestrator
  接続を伴い共有状態への副作用リスクがある(`uipath_migration_priorities.md`
  P2 #13)。コード生成というよりランタイム統合の問題で、別イニシアチブ
  として切り出すべき
- **外部Library依存の完全解決**: `.nupkg`に元ソースが無い以上、
  .NETデコンパイル(ILSpy等)以外に道が無い。技術的に別トラック

## 次にやること

Phase 0のVM非依存タスク(`And`/`Or`変換アルゴリズム・セレクタ意味論の
公式ドキュメント調査)は完了(知見37、design/uipath_vb_expression_mapping.md)。
残る候補:

1. **Phase 2〜3着手(最有力)**: `dump_daemon`に`uipath_dsl`(仮称)
   パッケージを新設し、最小のXAMLツリーウォーカー(`Sequence`+`Assign`+
   `MessageBox`程度)を`xaml_probe/Main.xaml`で試作する。PAD側の最初の
   一歩(`pad_dsl`の最小実装)と同じ進め方
2. **Modern活動のFuzzy/Strict selector実XAML確認**(VM要、ただし新Studio
   問題とは独立): 旧Studio(2021.4.4)でModern UI Automation活動
   (`Set Selected Item`等)を1つ置いてXAMLを確認する。新Studio問題の
   解消を待たずに着手できる可能性がある——ただしVMは他セッションと共用
   のため、使用タイミングの調整が必要
