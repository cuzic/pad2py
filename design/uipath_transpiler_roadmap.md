# UiPath→Python トランスパイラ完成までのロードマップ

本ドキュメントは「研究フェーズ(知見1〜36の実機確認)」から「実装フェーズ」へ
移行するための全体像を整理したもの。[design/uipath_xaml_findings.md](uipath_xaml_findings.md)・
[design/uipath_migration_priorities.md](uipath_migration_priorities.md)・
[design/uipath_vb_expression_mapping.md](uipath_vb_expression_mapping.md)が
「何がどう直列化されるか」の実機検証ログであるのに対し、本ドキュメントは
「それを踏まえてどういう順序で何を作るか」を記す。v1完成後の次の一手は
[design/uipath_feature_catalog.md](uipath_feature_catalog.md)(UiPath機能全体の
カタログと移行価値の優先順位付け)も参照。

## 現状整理(2026-11-05時点、実装フェーズ完了後に再俯瞰)

**この節は研究フェーズ完了時点(知見1〜36)のまま更新されず古くなっていた
——以下、Phase 2〜7の実装が実際に完了した後の実態に合わせて書き直す。**

**実装は既に存在する**: `dump_daemon/uipath_dsl`(XAMLツリーウォーカー)・
`uipath_expr`(VB.NET式パーサー)・`uipath_codegen`(Pythonコード生成)・
`uipath_selector`(Classic Selector→pywinautoマッピング)・
`uipath_codegen_coverage`(カバレッジ計測)の5パッケージ、実装約3,950行+
テスト約2,880行(UiPath関連テスト271件、リポジトリ全体969件)。PAD側
(`pad_dsl`・`pad_expr`・`pad_codegen`・`pad_action_lib`、実装約7,546行)の
おおよそ半分の規模——v1スコープがPADより狭い(Tier1活動一式+Classic
Selectorのみ)ことと整合する。

**できていること(厚い)**: VB.NET式の変換規則は知見42〜91の系統的な
.NETランタイムソース照合(`Conversions.vb`/`Operators.vb`/
`Utils.LateBinder.vb`)により、算術・比較・論理・単項演算子すべてで
`Nothing`/文字列/Boolean混在オペランドの型強制がVBの実挙動と一致する
ところまで固められている。制御フロー一式(Sequence/If/ForEach/TryCatch/
Switch/While/DoWhile/Break/Parallel)・Variables/Argumentsの既定値初期化・
複数ファイルプロジェクト組み立て(`Invoke Workflow File`解決・
`Out`/`InOutArgument`警告)・Classic Selectorマッピングも実装済みで、
実機確認済みフィクスチャ(`Main.xaml`/`Sub1.xaml`)に対する回帰テストで
固定されている。

**完成に向けて残っているもの**: 詳細は本ドキュメント末尾の新設節
「[残タスク: v1完成までに必要なもの](#残タスク-v1完成までに必要なもの2026-11-05見直し)」
参照。2026-11-05中にユーザーから明示的な意思決定を得た(AskUserQuestion):
(1) Flowchartは実装する、(2) Excel=`openpyxl`・Outlook=`win32com`で実装する、
(3) HttpClientのHeaders/Bodyパースを先に進める、(4) InvokeCodeは今回は
見送る——**この4項目は全て完了した**(HttpClient=知見96、Excel=知見97、
Outlook=知見98、Flowchart=知見100・101)。Flowchartは当初VM実機キャプチャ・
ローカル.NET検証の両方が環境要因でブロックされたが(知見99)、第三の経路
(GitHub上の実機保存済みXAMLを`gh api search/code`で直接確認、知見100)で
VM不使用のまま直列化形を確定し、ディスパッチループパターンで循環・合流を
含む一般のグラフに対応する実装を完了した(知見101)。Phase 1の決定文
「対象ワークフロー種別: Sequence/Flowchartのみ」と実装の食い違いは解消
済み。残るのは実データでの需要が出るまで意図的に見送っている既知の限界
(セレクタ属性・配列添字曖昧性・相対パス・InvokeCode・FlowSwitchの
`x:Key`子要素形等)のみであり、v1「完成」の障害とはみなさない。

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

**カバレッジ計測ツール: 完了(2026-11-05、知見70)**。
`dump_daemon/uipath_codegen_coverage.py`(`uv run python3 -m
dump_daemon.uipath_codegen_coverage`で実行)が実機確認済みXAMLフィクスチャ
(`Main.xaml`/`Sub1.xaml`)を対象に測定し、現状**72%(21/29分岐点)**。
残り8件のうち3件(`DoWhileNode`無条件・`InvokeWorkflowFileNode`単体呼び
出し・Libraryの`UnknownActivityNode`)は仕様通り、残る5件
(`ExcelApplicationScopeNode`/`ExcelWriteCellNode`/`HttpClientNode`/
`InvokeCodeNode`/`SendOutlookMailNode`)が、Tier1確定済みにもかかわらず
`_generate_unresolved_activity`へ常にルーティングされ未実装のまま
(ライブExcel/Outlook連携・インラインコード実行・`HttpClient`のHeaders/
Body未パースという既知の難所、下記参照)——次の実装対象の優先度付けに
このツールを使う。

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

## Phase 5: Variables/Arguments/スコープのコード生成【完了、2026-11-05】

構造は知見8・12で確定済み。`Sequence`/`TryCatch`の`<Container.Variables>`
配下に宣言された変数(`VariableDecl`)を、そのスコープ先頭で初期化する文へ
変換するよう`uipath_codegen`を拡張した——VB.NETの変数は明示代入前でも
「その型の既定値」で読めるため(Pythonのローカル変数は未代入参照が
`NameError`になり挙動が異なる)、これを再現する必要がある。`Default`属性
(知見7の属性形直列化)があればその値、無ければ`.NET`の`default(T)`相当
(数値型→`0`/`0.0`、真偽値型→`False`、それ以外(参照型・未知の型)→
`None`)を使う。`TryCatch.Variables`は`try:`より前(コンストラクト全体の
スコープ)で初期化する。`tests/test_uipath_codegen.py`に3件追加、全606件
通過。

**(完了、2026-11-05追補)** `Variable.Default`の子要素形
(`<Variable.Default><Literal>...</Literal></Variable.Default>`、知見7で
公式ドキュメント上は確認されていたが本fixtureには実例が無かった方)にも
`xaml_tree._parse_variable_default`が対応した——属性形(`Default="init"`)が
優先、無ければ`<Variable.Default>`配下の`<Literal>`要素の`.text`を使う。
実機にその実例が無いため合成XML(`tests/test_uipath_dsl.py`の
`test_variable_default_literal_child_element_form`)で検証、全607件通過。

**既知の制約として引き続き残るもの**:
- ワークフロー引数(`<x:Members>`)は従来通りPython関数の仮引数に
  そのまま対応させるのみで、クロージャによる「Python的レキシカルスコープ」
  への変換は行っていない(関数境界=Sequence境界という単純対応のままで
  十分機能するため、知見17の「クロージャ越し参照不可」というVB側の制約を
  Python側で再現する積極的な理由が無いと判断——再現しないことで生成
  コードがより自由にスコープを跨げてしまう側に倒れるが、これはPythonの
  通常の関数スコープが単にVBより緩いだけで、誤動作は起きない)

## Phase 6: プロジェクト組み立て(project.json→複数ファイル統合)

Main.xaml+サブワークフローファイル+project.jsonから1つのPythonパッケージ
を生成する。

- **(完了、2026-11-05)** `Invoke Workflow File`(知見12)→関数呼び出しへの
  変換、ワークフロー引数(`<x:Members>`宣言)→Python関数シグネチャへの変換:
  `generate_project_python(entry_path)`を実装した。`entry_path`から
  `Invoke Workflow File`で到達可能な`.xaml`をBFSで発見し(`_discover_workflow_files`、
  相対パスは参照元ファイルのディレクトリ基準で解決)、各ファイルを個別の
  Python関数として生成した上で、ファイル間の`Invoke Workflow File`呼び出しを
  対応する関数呼び出し(`Sub1(in_text='hello')`のような形)へ変換する。
  参照先が解決できない場合(存在しないファイル、未提供)は接続済みと偽らず
  `# TODO: unresolved Invoke Workflow File: ...`に倒す——`generate_python()`
  単体呼び出し(`invoke_resolver`省略)も同じ既定動作のまま後方互換を保つ。
  `tests/test_uipath_codegen.py`に4件追加(うち1件は合成した2ファイル構成を
  `exec()`して実際に関数呼び出しが連携することまで検証)、全603件通過。
  **既知の制約**: ワークフロー引数の方向(In/Out)は区別せず全て関数の
  仮引数として扱うのみで、`OutArgument`をPythonの`return`へ対応させる
  変換は実装していない(呼び出し元が戻り値を使う実例が出た時点で再検討)。
  **(部分的に対応、2026-11-05、知見78)** `return`変換そのものは依然
  未実装だが、`Out`/`InOutArgument`方向の引数を検出して関数本体先頭に
  `# TODO`を追記するようになった——架空の書き戻しをでっち上げる代わりに、
  Pythonの値渡しでは呼び出し元への反映が失われるという限界を明示する
  (下記「次にやること」項目39参照)。関数名の衝突(同じ`class_name`を
  持つ複数ファイル)は`_2`サフィックスで機械的に回避するだけで、意味の
  ある別名付けはしていない。**(完了、2026-11-05、知見86・87)** 知見86で
  「`# TODO`は呼び出し先(`Sub1`)の関数定義側にのみ出現し、呼び出し元
  (`Main`)の呼び出し文には何の警告も出ない」という残課題を見つけ、
  一度は`invoke_resolver`の型拡張が既存の公開APIを壊すと判断して実装を
  見送ったが、直後の知見87で「型を変えず、並行する新規オプション引数
  (`out_arg_resolver`)を追加するだけでよい」という後方互換なより安全な
  設計に気づき、実際に実装した——`Main()`の呼び出し文の直前に
  `# WARNING: out_result are Out/InOutArgument on Sub1() — ...`が
  正しく追記されることを実機確認済みの合成2ファイル構成で確認。
- **(完了、2026-11-05)** `project.json`からのエントリポイント自動発見:
  `generate_project_from_json(project_dir)`を追加した。`project.json`の
  `"main"`フィールド(知見27で実機確認済みの実例`"main": "Main.xaml"`)を
  読み取り、そこから`generate_project_python()`を呼ぶ。v1スコープは
  Processプロジェクトのみ(Phase 1の決定)のため、
  `designOptions.outputType`が`"Process"`以外(Library等)の場合は
  `parse_workflow_file`のFlowchart/State Machine拒否と同じ方針で
  `ValueError`により明示的に拒否する。`tests/test_uipath_codegen.py`に
  3件追加、全614件通過。
- Library参照(知見26・27)→CLR名前空間エイリアス経由の呼び出し→Python
  モジュール参照への変換。ただし**ソースが手元に無い外部Library(他人の
  Library・Marketplace経由)は`.nupkg`からの復元が技術的に不可能**
  (知見28、コンパイル済み`.dll`のみでXAMLソースを含まない)。この場合は
  PAD側の`raw_fallback.py`と同じ「正直にTODOスタブを出す」方針を踏襲し、
  .NETデコンパイルという全く別の技術トラックには踏み込まない

## Phase 7: 検証基盤【見直し・2026-11-05】

初版では「PAD側の`test_round_trip.py`・`trace_compare.py`相当のものを作る」
としていたが、実際に両ファイルを確認したところ**UiPath側の検証ニーズとは
別物**だと判明した——`test_round_trip.py`はWindows専用のUI自動化セレクタ
再検出検証(E1/E2、プロセス再起動後もAutomationIdで要素を再発見できるか)、
`trace_compare.py`はPBD(プログラミング・バイ・デモンストレーション)の
複数トレース比較によるループ推測プロトタイプで、どちらも「XAMLパース→
コード生成→期待Pythonとの比較」という回帰テストの話ではなかった。

その「パース→コード生成→期待Pythonの比較を回帰テスト化する」という
Phase 7本来の目的自体は、既に`tests/test_uipath_dsl.py`・
`tests/test_uipath_expr.py`・`tests/test_uipath_codegen.py`・
`tests/test_uipath_selector.py`(2026-11-05時点で合計100件超)が
`design/evidence/uipath_xaml_probe/`の実機フィクスチャ2本
(`Main.xaml`/`Sub1.xaml`)に対して既に果たしている——専用の汎用カバレッジ
フレームワーク(PAD側の`codegen_coverage.py`相当)を今から作るのは、
実機フィクスチャがまだ2本しか無い現時点では時期尚早な過剰設計と判断し、
見送る。実機フィクスチャが今後複数のプロジェクト規模に増えた時点で
改めて検討する。

## Phase 8: 明示的にスコープ外とするもの(v1では着手しない)

- **Coded Workflows**: C#→Pythonという全く別のコード生成トラック。
  WF活動木→Python変換のノウハウが再利用できない
- **Object Repository / Modern selector**: 有効化条件(知見31)もXAML表現
  (知見39、`uix:`名前空間・`NApplicationCard`/`NClick`・スコープ/ターゲット
  2層分離のセレクタ構造)も判明済みだが、v1スコープはClassicのみという
  Phase 1の決定は変えず、Modern対応自体はPhase 8のスコープ外のまま据え置く
  (新Studio問題(知見33〜35)の解消を待たずにここまでは調査できた)
- **State Machine**: Phase 1でスコープに含めると決めた場合のみ着手
- **Orchestratorのキュー/アセット/トリガー連携**: 実際のOrchestrator
  接続を伴い共有状態への副作用リスクがある(`uipath_migration_priorities.md`
  P2 #13)。コード生成というよりランタイム統合の問題で、別イニシアチブ
  として切り出すべき
- **外部Library依存の完全解決**: `.nupkg`に元ソースが無い以上、
  .NETデコンパイル(ILSpy等)以外に道が無い。技術的に別トラック

## Phase 2〜3: XAMLツリーウォーカー実装【着手完了、2026-11-05】

`dump_daemon/uipath_dsl/`パッケージを新設し、Phase 1で確定したTier1
アクティビティ一式(Assign/If/ForEach/TryCatch/Switch/While/DoWhile/
Break/Parallel/MessageBox/HttpClient/Excel Application Scope+Write Cell/
Send Outlook Mail/Click/Invoke Workflow File/Append Line/Read Text File/
Invoke Code/Set To Clipboard)に対応するXAMLツリーウォーカーを実装した。
`pad_dsl`と違いXAMLはただのXMLなので、トークン列→ブロック木という
2段階パースは不要——`lxml`で直接XML木を`types.py`のIRノード型へ変換する
1段階構成(`xaml_tree.py`)。design/evidence/uipath_xaml_probe/の実機
フィクスチャ(`Main.xaml`・`Sub1.xaml`)で19件のテスト(`tests/test_uipath_dsl.py`)
を全て通過。詳細はREADME.md「構成」節および`dump_daemon/uipath_dsl/`の
docstringを参照。未対応アクティビティ(Library呼び出し含む)は
`UnknownActivityNode`へ正直に素通しし、架空の変換はでっち上げない。

実装中に見つかった、XAMLの構造上の既知の簡略化(将来の拡張点):
- `ForEach.Body`/`While.Body`/`DoWhile.Body`/`ExcelApplicationScope.Body`は
  ステップ数によらず**常に**`<Sequence DisplayName="Body"/"Do">`でラップ
  される(`If.Then`/`If.Else`が複数ステップの時だけラップされる可変長
  パターンとは異なる、別の固定パターン)——このラップ用`Sequence`自身が
  ローカル変数を宣言するケースは未対応(実機未確認、文法上は可能)
- **(完了・バグ修正済み、2026-11-05)** `Switch`のdefaultアームの実XAML形
  (知見40): `x:Key`付き辞書エントリ(知見21)とは別の`<Switch.Default>`
  プロパティ要素だと確定。`_parse_switch`がこれを無言で読み捨てていた
  実バグを発見・修正した
- Modern活動のFuzzy/Strict selector(知見37・知見39)は実XAML形を確認済み
  だが、v1スコープがClassicのみという方針により実装は見送り

## Phase 3: VB.NET式パーサー【完了、2026-11-05】

`dump_daemon/uipath_expr/`を新設し、`pad_expr`と同じ設計方針(Lark文法、
演算子の優先順位は公開VB.NET仕様に基づく未検証の仮定、構文解析失敗時は
テキストを失わずフォールバック)でVB.NET式パーサーを実装した。知見32・36で
実機確認済みの構文(リテラル・変数参照・ドット区切り静的メソッド呼び出し・
9演算子`Mod`/`\`/`^`/`And`/`AndAlso`/`Or`/`OrElse`/`Xor`/`Not`・比較演算子
`=`/`<>`/`<`/`>`/`<=`/`>=`/`Is`/`IsNot`・型変換関数`CStr`/`CInt`/`CDbl`/
`CBool`/`IsNothing`・三項`If(cond,t,f)`・文字列補間`$"..."`(中身は解析せず
不透明なアトムとして保持)・`String.IsNullOrEmpty`等の静的メソッド呼び出し)
を全てカバーし、`tests/test_uipath_expr.py`(14件)で知見ドキュメントに
記録された実機確認済み式を1件も失敗させずパースできることを確認した。
`And`/`Or`は構文解析の対象のみ(`BinOp(op="And"/"Or", ...)`として木に残す)
——これを実際に安全な`&`/`|`へ変換するのはPhase 4(codegen)の責務で、
変換ルール自体は既にdesign/uipath_vb_expression_mapping.mdで確定済み。

**`uipath_dsl`とは意図的に疎結合のまま**: `VbExpr`(`uipath_dsl.types`)は
引き続き生テキストのみを保持し、`uipath_expr.parse_vb_expr(vb_expr.text)`を
呼ぶのは利用側(将来のcodegen)の責務とした。`pad_dsl.RawExpr.tree`のように
パース結果をIRノードへ事前に埋め込む設計も検討したが、2つのモジュールが
扱う関心事(XML構造 vs. VB式構文)は直交しており、今の時点で結合する
積極的な理由が無い(かつ`VbExpr`の等価比較が`tree`の有無で変わってしまい
既存テストに不要な手戻りが生じる)と判断し見送った——将来、実際に
codegenで必要になった時点で結合するか、改めて検討する。

## Phase 4: コード生成【実装完了、2026-11-05】

`dump_daemon/uipath_codegen/`を新設し、`uipath_dsl`のIRから`uipath_expr`
経由でPythonソースを生成する`generate_python()`を実装した
(`render.py`=式のPython文字列化、`__init__.py`=ノード種別ごとのディスパッチ)。
`pad_codegen`と同じ「架空のAPIをでっち上げず`# TODO`に倒す」方針を踏襲し、
制御フロー一式(Sequence/Assign/If/ForEach/TryCatch/Switch/While/DoWhile/
Break/Parallel)と単純な入出力系(MessageBox→`print()`/Append Line/
Read Text File/Set To Clipboard→`pyperclip`)、**Click(セレクタ解決込み、
下記参照)**は実際にコード生成し、複数ファイル結線が未実装のInvoke
Workflow File、インラインコードのInvoke Code、ライブCOM連携が要る
Excel/Outlook、プロパティ要素(Headers等)を未パースのHttpClientは
`# TODO`に倒す。`And`/`Or`/`Xor`→`&`/`|`/`^`変換(両オペランド括弧必須)も
設計通り実装。`tests/test_uipath_codegen.py`(16件)で検証済み。

**(2026-11-05追補、知見96)** `HttpClientNode`は実機確認済みの最も単純な
構成(Headers等が全て空・Body未設定)に限り`requests`への実コード生成へ
移行した——下記「実装ログ」項56参照。Excel/Outlook/InvokeCodeは
引き続き`# TODO`のまま(残タスクB参照、ユーザー決定済みで着手予定)。

**セレクタ解決(`dump_daemon/uipath_selector/`、同日中に追加着手・完了。
2026-11-05に実機検証(知見38)を反映して更新)**:
知見37で把握したClassic Selector(`WND`/`CTRL`)の属性語彙に基づき、
`<wnd .../><ctrl .../>`形式のセレクタ文字列をpywinautoの検索条件連鎖
(`Desktop(backend="uia").window(...).child_window(...)...`)へマッピング
する。`cls`→`class_name`・`name`→`title`は実機(pad2py-pad-host VMの
実Notepad)で確認済み(知見38)。`role`→`control_type`は当初マッピング
していたが、実機で`KeyError`を起こすと判明したため**意図的に未対応へ
変更**した(安全側の判断、知見38)。マッピング不能な属性(`role`/`idx`等)
は、でっち上げるより警告コメント(`# WARNING:`)付きで未対応のまま残す。
`tests/test_uipath_selector.py`(7件)で検証済み。

**実装中に見つかった追加の既知の制約**:
- `uipath_expr`に配列/コレクションリテラル`{a, b, c}`(知見5で確認済みだが
  当初パーサー未実装)の対応が漏れていた——`ForEach.Values`が頻出する
  パターンだったため発覚し追加した(`ArrayLiteral`→Python `[...]`)
- `Switch`の`x:Key`は文字列として取得されるため(`uipath_dsl.xaml_tree`)、
  `x:TypeArguments`が数値型(`x:Int32`等)の場合はクォート無しの数値
  リテラルとして出力するよう`uipath_codegen`側で補正している。
  **(2026-11-05、知見77で補強)** この補正は`key_literal`自体の見た目
  (裸の数値/クォート付き文字列)のみの話で、比較自体はさらに`_vb_cmp()`
  (`=`演算子と同じ型変換規則)を経由するため、`Expression`の実行時の型が
  `x:TypeArguments`の宣言と食い違っていても正しく一致する(詳細は
  `design/uipath_xaml_findings.md`知見77参照)
- **生成コードの構文的妥当性はソースXAMLの妥当性に依存する**:
  `design/evidence/uipath_xaml_probe/Main.xaml`は知見確認用に複数の
  独立した機能テストを1ファイルに詰め込んだフィクスチャで、ループの外に
  単独の`<ui:Break />`が置かれている(知見18のXAML形確認のためだけの配置)
  箇所があり、これを忠実に変換すると`break`文がループ外に出て
  `SyntaxError`になる——codegenの変換ロジック自体のバグではなく、
  「現実のワークフローなら制御フローとして妥当なはず」という前提が
  この調査用フィクスチャには当てはまらないことに起因する

## 残タスク: v1完成までに必要なもの(2026-11-05見直し)

Phase 0〜7の実装はほぼ完了し、下の「実装ログ」にある知見65〜91が示す通り
VB式の変換規則は非常に手厚く検証済み(UiPath関連テスト271件、リポジトリ
全体969件)。ここでは「決まったv1スコープに対して何が実際に欠けているか」
だけを俯瞰する。

### A. スコープと実装の食い違い【完了、2026-11-05】

1. **(完了、知見100・101)** Flowchartが実質スコープ外のまま放置されて
   いた問題を解消した。Phase 1の決定(#1、本ドキュメント上部)「対象
   ワークフロー種別: Sequence/Flowchartのみ」と実装の食い違いを、
   `FlowStep`/`FlowDecision`/`FlowSwitch`+`x:Reference`接続という新規
   IR構造・コード生成(ディスパッチループ/状態機械パターン、循環・合流
   を含む一般のグラフに対応)で解消した。VM実機キャプチャ(知見99で
   環境要因によりブロック)の代わりに、GitHub上の実機保存済みXAMLを
   `gh api search/code`で直接確認する第三の経路で直列化形を確定した
   (知見100)。詳細はPhase 1〜4の各節・知見100・101参照。

### B. Tier1確定済みだが未実装の活動【完了、2026-11-05(InvokeCodeのみ見送り決定)】

知見70で発見された5活動のうち、着手順とライブラリはユーザー決定済み
(AskUserQuestion)。知見75・83・92〜95で`# TODO`コメントに捕捉済み
フィールド(元の`.xaml`の値)を追記済みのため、着手時はそこが起点になる。

2. **(完了、知見96)** `HttpClientNode`: `requests`ライブラリへの変換を
   実装した——実機フィクスチャで確認済みの最も単純な構成(`Headers`等の
   コレクションが全て空、`Body`未設定)は実際にコード生成されるように
   なった(カバレッジ72%→76%)。`Body`設定時・コレクション非空時の
   実直列化形は依然未確認のため、その場合は引き続き`# TODO`。
3. **(完了、知見97)** `ExcelApplicationScopeNode`+`ExcelWriteCellNode`:
   `openpyxl`で実装した(ユーザー決定、2026-11-05)——スコープの直接の子
   としての`Write Cell`(知見22で確認済みの実機構造)に限り実コード生成
   (カバレッジ76%→79%)。If/Switch/ループ越しにネストした場合は
   `scope_var`文脈を失うため安全に`# TODO`のまま。
4. **(完了、知見98)** `SendOutlookMailNode`: `win32com`で実装した
   (ユーザー決定、2026-11-05)——`Cc`/`Bcc`未設定・`Files`空・`Importance`/
   `Sensitivity`/`IsBodyHtml`/`IsDraft`が確認済み既定値の場合に限り実
   コード生成(カバレッジ79%→83%)。
5. `InvokeCodeNode`: 今回は見送る(ユーザー決定、2026-11-05)——インライン
   VB.NETコード(文単位、`uipath_expr`が対応する式単位の範囲外)をPythonへ
   どう変換するか自体が未解決のまま

### C. 検証基盤の薄さ(構造的制約、Phase 7で既知として記録済み)

6. 実機確認済みXAMLフィクスチャが`Main.xaml`/`Sub1.xaml`の2本のみ——
   カバレッジ72%(知見70)という数字はこの2本の範囲でしか意味を持たない。
   実世界のワークフローを追加検証すれば、A・B以外の未知のギャップが
   新たに出る可能性が高い。Phase 7は汎用カバレッジフレームワークの構築を
   「実機フィクスチャ2本では時期尚早」として明示的に見送っているが、
   フィクスチャが増えた時点で再検討すべき判断はそのまま有効

### D. 意図的に残した既知の限界(現状では「完成」の障害にしない)

でっち上げを避けるため安全側に`# TODO`/`# WARNING`へ倒した設計判断で、
実データでの需要が出るまで対応を見送ってよいもの:
- セレクタ属性は`cls`/`title`/`automationid`/`name`の4つのみ対応
  (`role`は実機で`KeyError`を確認したため意図的に未対応、知見38)
- 配列/コレクション/`DataTable`行アクセス`識別子(引数)`構文の言語レベルの
  曖昧性(知見74、静的型追跡が無いと解決不可能)
- `Append Line`/`Read Text File`の相対パス解決基準(知見82、公式情報が
  相互に矛盾し確定できない)
- 文字列補間の書式指定子・フィールド幅(知見65)、`&B`2進リテラル文字列
- `ui:Click`の`AlterIfDisabled`/`CursorMotionType`/`DelayBefore`/
  `DelayMS`/`SendWindowMessages`/`SimulateClick`(知見73)
- ワークフロー引数`Out`/`InOutArgument`の実際の値書き戻し(`return`への
  変換、知見78・87で警告のみ実装、変換自体は見送り)

### 優先順位の提案【2026-11-05更新、A・B完了】

A(Flowchart)・B(ライブラリ選定)ともに完了した。Flowchart(知見100・
101)はVM実機キャプチャ(知見99)が環境要因でブロックされたため、
GitHub上の実機保存済みXAMLを直接確認する経路で解決した——VM不使用・
ローカルインストール不要のまま、公式ドキュメントの矛盾(`Flowchart`
クラスのAPI定義とMicrosoft Learn概念説明ページの食い違い)を実機データ
で解消できた好例として記録する。InvokeCodeNodeのみ見送り決定済み
(技術的な未解決課題——インラインVB.NETコードの文単位変換——が残るのみ)。

今後、C・D(検証基盤・既知の限界)はいずれも「実データでの需要が出るまで
見送ってよい」という既存の判断を維持する——実機フィクスチャ(`Main.xaml`/
`Sub1.xaml`)にFlowchartの実例が無いため、知見100・101の実装は実機
フィクスチャでの回帰テストではなく、GitHub実例を模した合成XAML+IRレベル
の直接構築によるテストでのみ検証されている(Phase 7の既存の判断と整合)。
このドキュメント自体の整合性確認(知見ログの番号連続性・本セクションの
現状反映)程度の軽微な保守は継続する。

## 実装ログ(知見65〜91、個別の修正の記録——現在は完了済み項目のみで、
今後の作業はPhase単位の節または上記「残タスク」を参照)

1. **(完了、2026-11-05)** Modern活動のFuzzy/Strict selector実XAML確認:
   旧Studio(2021.4.4)の`xaml_probe`でModern Design Experienceを有効化し、
   実際にModern版`Click`活動をNotepadへターゲット指定して保存、実XAMLを
   確認した(新Studio問題の解消を待たずに着手できた)。結果は知見39
   (design/uipath_xaml_findings.md)参照——Modern活動は全く別の`uix:`
   名前空間・活動クラス(`uix:NApplicationCard`/`uix:NClick`)を使い、
   セレクタは「スコープ(`ScopeSelectorArgument`)」と「ターゲット
   (`FullSelectorArgument`/`FuzzySelectorArgument`)」の2層に分離され、
   `SearchSteps="Selector, FuzzySelector, Image"`が実行時フォールバック
   順序を宣言する、という構造が確定した。実験用に追加した活動は検証後
   `xaml_probe`から削除し元の状態に復元済み(知見31の方針を徹底)。
   v1スコープはClassicのみのため実装は見送り、知見のみ記録。
2. **(完了、2026-11-05)** 複数ファイル結線(Phase 6):
   `generate_project_python()`を`dump_daemon/uipath_codegen/`に追加し、
   `Invoke Workflow File`で参照されるサブワークフローをBFSで実際に辿って
   解決し、Python関数呼び出しへ変換するようにした。詳細はPhase 6節参照。
3. **(完了)** より現実的なフィクスチャでの検証:
   `test_realistic_workflow_actually_executes_correctly`
   (`tests/test_uipath_codegen.py`)で、手作りの現実的なワークフローIR
   (配列リテラル→`ForEach`→`&`による文字列蓄積→`If`/`Else`分岐)を
   `exec()`し、標準出力を実際に検証するところまで確認した——それまでの
   テストは`compile()`レベルの構文確認か生成コード中の行の有無の確認に
   留まっていたのに対し、実行時の正しさまで保証する初めてのテスト
4. **(完了、2026-11-05)** セレクタマッピングの実機検証: pad2py-pad-host
   VM上の実機Notepadで、知見9のClick実例セレクタに対し`uipath_selector`が
   生成するpywinautoチェーンを実際に実行した(design/dsl_format_findings.md
   知見56でPAD側は既に実機検証済み、今回UiPath側も実施)。結果は知見38
   (design/uipath_xaml_findings.md)参照——`cls`→`class_name`・
   `name`→`title`は実機で確認(正しい)、`role`→`control_type`は実機で
   `KeyError`を起こすと判明し、`uipath_selector`から該当マッピングを削除
   (安全側に倒して意図的に未対応へ変更)。`tests/test_uipath_selector.py`を
   新しい挙動に追従させ、全607件通過。
5. **(完了、2026-11-05)** VB.NET演算子の値食い違いバグの系統的点検
   (VM不使用、公式ドキュメントで確定): `Mod`/`\`(符号が異なるオペランドで
   Pythonの`%`/`//`と食い違う)・`CInt`(切り捨てでなく銀行丸め)・
   `CBool`(文字列リテラルがPythonの`bool()`の真偽値判定と食い違う)の
   4件を発見・修正した(知見42・43)。`render.py`の全演算子・関数を
   同じ観点で洗い直したが、それ以外に新たな食い違いは見つからなかった
   ——ただし`^`(負の底+非整数指数の挙動)と`Not`(Integer適用時のビット
   反転)の2点は公式ドキュメントだけでは確定できず、未解決のまま残った
   (知見44参照)。
6. **(完了、2026-11-05)** `^`/`Not`の残る2点の実機検証: 隔離した
   `Sub1.xaml`フィクスチャをpad2py-pad-host VM上のUiPath Studioで
   Debug File実行し、`(-8.0) ^ 0.5`→`NaN`(例外ではなかった)、
   `Not 5`(Integer)→`-6`(ビット反転)を確定した。両方とも実在する
   バグと確定し、`render.py`を修正(`^`は負の底+非整数指数の場合のみ
   `NaN`に分岐、`Not`は実行時に`isinstance(_x, bool)`で論理否定/ビット
   反転を分岐するラムダ式)。回帰テストを`tests/test_uipath_codegen.py`に
   追加、実験で変更したVM側ファイルは元の状態に復元済み。詳細は知見45
   (design/uipath_xaml_findings.md)参照。これで知見42〜45の系統点検は
   完全に完了。
7. **(完了、2026-11-05)** `CStr(Double)`の書式差を修正(VM不使用、公式
   ドキュメントで確定、知見46): 知見45の`^`修正時に軽微な残課題として
   残した「VBのDouble既定書式(G15)は整数値の小数点を省略するため
   `CStr(4.0)`は`"4"`になるが、単純な`str(4.0)`は`"4.0"`」という食い違い
   を、`render.py`に`_vb_cstr()`ヘルパー関数を追加して修正(`CStr`と
   `&`の両方で使用、`NaN`/`Infinity`/`-Infinity`の特別扱いも含む)。
   生成コードへの実際の挿入は既存の`_collect_imports`の仕組み
   (使用時のみ注入)を拡張して対応。回帰テストを
   `tests/test_uipath_codegen.py`に追加、全663件通過(新規10件)。
   G書式の指数表記・カルチャ依存の小数点記号は軽微な既知の限界として
   未対応のまま記録(知見46参照)。
8. **(完了、2026-11-05)** `Append Line`/`SetToClipboard`の不整合修正
   (VM不使用): 知見46の`_vb_cstr()`導入直後のコードベース全体grep監査で
   見つけた、単純な`str()`のまま`_vb_cstr()`に統一されていなかった2箇所
   (`_generate_append_line`/`_generate_set_to_clipboard`)を修正。
9. **(完了、2026-11-05)** 比較演算子(`=`/`<>`/`<`/`<=`/`>`/`>=`)の
   数値/文字列混在オペランド型変換規則を実装(VM不使用、公式ドキュメントで
   確定、知見47): `Option Strict Off`下のObject型オペランド比較では、
   片方が数値・片方が文字列なら文字列をDoubleへ変換してから数値比較する
   (Microsoft Learn「Comparison Operators」)。`Not`(知見45)と同じ実行時
   isinstance分岐の`_vb_cmp()`ヘルパーを追加し、全比較演算子をこれ経由に
   変更。回帰テストを追加、ブリトルな既存テスト2件を新形式に追従させ、
   全698件通過。
10. **(完了、2026-11-05)** `+`演算子の型混在ディスパッチ規則を実装
    (VM不使用、公式ドキュメントで確定、知見48——他セッションが並行して
    進めていたPAD側の知見86に着想を得て調査): VBの`+`は片方が数値・
    片方が文字列の場合、連結ではなく文字列をDoubleへ変換してからの
    算術加算になる(Microsoft Learn「+ Operator」、公式の例
    `"34" + 6`は`40`)。単純な`+`変換のままだとPythonは`str + int`で
    `TypeError`を即座に送出しクラッシュするため、`_vb_cmp`/`_vb_cstr`
    より重大な問題だった。`_vb_add()`ヘルパーを追加し結線、回帰テスト
    追加、全711件通過。`-`/`*`/`/`の型混在ディスパッチは未調査のまま
    今後の調査候補へ記録(知見48参照)。
11. **(完了、2026-11-05)** `-`/`*`/`/`/`Mod`/`\`の文字列/`Nothing`
    オペランド数値強制を実装(VM不使用、公式ドキュメントで確定、知見49
    ——知見48の残課題を解消): これらは`+`と違い文字列を特別扱いしない
    純粋な数値演算子(各公式ページ「Supported Types: All numeric
    types」)——`Nothing`は`0`として扱われる。単純な変換のままだと
    Pythonは文字列/`None`で`TypeError`を即座に送出しクラッシュする
    (知見48の`+`と同じ問題)。`_vb_num()`ヘルパーを追加し`-`/`*`/`/`/
    `Mod`/`\`全てに結線、回帰テスト追加。UiPath関連テスト全130件通過
    (`/`の`Nothing`扱いは公式ページ取得に失敗し類推のまま、ゼロ除算時の
    `NaN`/`DivideByZeroException`挙動差、Boolean算術演算子の挙動は
    いずれも未調査のまま今後の調査候補へ記録、知見49参照)。
12. **(完了、2026-11-05)** `/`のゼロ除算をVBのDouble方式に修正
    (VM不使用、公式ドキュメントで確定、知見50——知見49の残課題を一部
    解消): 正しいURLで`/`の公式ページを再取得し確認——`/`は「除算の前に
    整数オペランドは全てDoubleへ拡張される」ため常にDouble相当になる
    唯一の算術演算子で、ゼロ除算も型分岐せず常に`Infinity`/`-Infinity`/
    `NaN`になる。Pythonの`/`はゼロ除算で`ZeroDivisionError`を即座に
    送出するため、`_vb_div()`ヘルパー(`_vb_num`から独立した自己完結
    実装)を追加し結線。回帰テスト追加、UiPath関連テスト全134件通過。
    `Mod`/`\`のゼロ除算は型依存のため静的型情報が無いと安全に実装
    できず、意図的に未対応のまま残す(知見50参照)。
13. **(完了、2026-11-05)** Booleanオペランドの算術・比較演算子への変換
    (`True→-1`)を修正(VM不使用、公式ドキュメントで確定、知見51——
    知見49・50で繰り返し残していた最後の「未調査」項目を解消):
    Microsoft Learn「Boolean Data Type」が「VBがBooleanを数値型へ変換
    する際、`False`は`0`、`True`は`-1`になる」と明記(VB6互換仕様)。
    Pythonの`bool`は`int`のサブクラスで`True`は`1`相当のため、`_vb_cmp`/
    `_vb_add`/`_vb_num`/`_vb_div`の4ヘルパー全てが符号を取り違えていた
    (`5 + True`はVBで`4`だが無変換だと`6`になっていた)。4ヘルパー全ての
    先頭でBoolean→`-1`/`0`変換を追加。回帰テスト追加、UiPath関連テスト
    全143件通過。これで知見44〜51の「VB.NET演算子の値の食い違い」系統
    点検は、公式ドキュメントだけで確定できる範囲は全て解消完了
    (残るは`Mod`/`\`のゼロ除算(型依存)と`CDbl`の`Nothing`/桁区切り
    文字列(VM実機検証が必要)のみ)。
14. **(完了、2026-11-05)** `CDbl`の`Nothing`/桁区切り文字列/Boolean変換を
    .NETランタイム本体のソースで確定・修正(VM不使用——知見46で「VM実機
    検証が必要」として残していた最後の項目を解消、知見52): 公式
    ドキュメントの代わりに.NETランタイム本体の実装ソース
    (`Microsoft.VisualBasic.Core`パッケージの`Conversions.vb`、
    `dotnet/runtime`リポジトリ、Microsoft Learn APIリファレンスページが
    「Source」リンクとして公式に指している)を直接確認——
    `ToDouble(Object)`/`ToDouble(String)`は`Nothing`に対し例外を出さず
    `0`を返す、`ParseDouble`は`NumberStyles.AllowThousands`を含む
    フラグで`Double.Parse`するため桁区切りのコンマを受理する、
    `Case TypeCode.Boolean`は`CDbl(Boolean)`相当を呼ぶ(知見51の
    Boolean→`-1`規則がここにも適用される)ことを確定した。`_vb_cdbl()`
    ヘルパーを追加し結線(`_CAST_FUNCS`辞書は不要になったため削除)。
    回帰テスト追加、UiPath関連テスト全150件通過。これで知見44〜52の
    「VB.NET演算子・型変換関数の値の食い違い」系統点検は、現実的に
    対応可能な範囲の課題を全て解消した(唯一残るのは`Mod`/`\`のゼロ除算
    (型依存、静的型情報が無く対応不可))。
15. **(完了、2026-11-05)** `CInt`も`CDbl`と同じ`Nothing`/桁区切り文字列の
    食い違いがあると確定・修正(VM不使用、知見53——知見52の`Conversions.vb`
    確認ついでに同じファイル内の`ToInteger`も追い打ちで確認): `CInt`の
    文字列/オブジェクト両オーバーロードも`Nothing`→`0`を処理し、文字列は
    `CDbl`と同じ`ParseDouble`(桁区切り受理)経由でDoubleへ変換してから
    銀行丸めする。修正前の`round(float(x))`は`Nothing`で`TypeError`、
    桁区切り文字列で`ValueError`になり食い違っていた。既存の`_vb_cdbl()`
    ヘルパー(知見52)を再利用し`round(_vb_cdbl(x))`に変更(新規ヘルパー
    追加無し)。回帰テスト追加、UiPath関連テスト全154件通過。`CStr`/`CBool`
    も同じ`Conversions.vb`でクロスチェック済み(`CBool`は既存実装が
    正しいと確認、`&H`/`&O`16進・8進リテラル文字列の非対応のみ軽微な
    既知の限界として残る)。
16. **(完了、2026-11-05)** `Mod`/`\`の残課題(ゼロ除算の型依存・`\`の
    銀行丸め先行)を解決(VM不使用、知見54——知見49・50で「型依存のため
    対応不可」と判断していたものを、`Operators.vb`(`Conversions.vb`と
    同じ`dotnet/runtime`ディレクトリ内の別ファイル、Object型オペランド
    への演算子ディスパッチャの実体)の発見で覆した): `Mod`のゼロ除算は
    実際に型依存(`ModObject`が`TypeCode`別にディスパッチ、整数系は
    例外・浮動小数点系は`NaN`)と確定したが、`uipath_codegen`は静的型を
    追跡していないため`_vb_num()`後のPython実行時型(`int`/`float`)を
    代理指標として判定する`_vb_mod()`ヘルパーで対応——VBランタイム自身も
    実行時の`TypeCode`で分岐しているため、この代理方式で十分と判断を
    改めた。`\`のゼロ除算は型によらず常に例外(Pythonの`/`も常に
    `ZeroDivisionError`のため無変換のまま一致、修正不要)。さらに`\`は
    除算の前に両オペランドを銀行丸めでLongへ変換すると新たに判明
    (`round(_vb_num(a)) / round(_vb_num(b))`に変更、`7.5 \ 2`が`3`では
    なく正しく`4`になるよう修正)。回帰テスト3件追加、UiPath関連テスト
    全160件通過。これで知見44〜54の「VB.NET演算子・型変換関数の値の
    食い違い」系統点検は、公式に確認できた範囲で完全に完了した
    (現時点で既知の残課題は無し)。
17. **(完了、2026-11-05)** `+`演算子の`_vb_add()`自体のバグ
    (`Nothing + Nothing`)を解決(VM不使用、知見55——知見54の
    `Operators.vb`発見ついでに`+`のディスパッチャ`AddObject`も確認):
    `Empty + Empty`は`Boxed_ZeroInteger`(整数`0`)を返すと実ソースで
    確定——知見48実装時は公式ドキュメントの一般則(片方が`Nothing`なら
    文字列側では`""`)をそのまま両方`Nothing`のケースにも適用して`""`と
    誤って推測していたが、実際のソースでは両方`Nothing`の組だけ特別
    扱いされていた。`_vb_add()`の`a is None and b is None`時の戻り値を
    `""`から`0`へ修正。回帰テスト追加、UiPath関連テスト全161件通過。
    「ドキュメントの一般則を鵜呑みにせず、実際のソースがその例外を
    設けていないか確認する」という教訓を記録。
18. **(完了、2026-11-05)** `_vb_cstr()`自体のバグ(`CStr(Nothing)`が
    `"None"`になる)を解決(VM不使用、知見56——知見55に続き`&`の
    ディスパッチャ`ConcatenateObject`を確認して発見): `CStr(Nothing)`の
    実体`ToString(Object)`は実際にはnullを返すが、`&`演算子
    (`ConcatenateObject`)は`CStr(Left) & CStr(Right)`という形でこの
    null化しうる戻り値を`System.String.Concat`相当へそのまま渡す——
    `String.Concat`はnull引数を空文字列として扱う既定動作のため、最終的に
    `Nothing & Nothing`は空文字列になる。修正前の`_vb_cstr(x)`は
    `x is None`を考慮しておらず`str(None)`=`"None"`という絶対にVBが
    出力しない文字列を返していた(`&`は`_vb_cstr`を内部で使うため、
    `"x=" & Nothing`のような頻出シナリオにも伝播していた)。
    `_vb_cstr()`の先頭に`x is None`時は`""`を返す分岐を追加(厳密な
    null伝播ではなく`&`での実用シナリオを優先した近似、既知の限界として
    記録)。回帰テスト追加、UiPath関連テスト全164件通過。知見55に続き
    2回連続で「完了宣言後の別ディスパッチャ確認で既存ヘルパーの
    `Nothing`絡み見落としが見つかる」パターンが発生——他の演算子でも
    同様の見落としが無いか継続確認する価値がある。
19. **(完了、2026-11-05)** `^`演算子が文字列/`Nothing`オペランドで
    `TypeError`になるバグを解決(VM不使用、知見57——知見56の「継続確認」
    提案を実行し`ExponentObject`を確認して発見、3回連続のクロスチェック
    的中): `^`は知見49の型混在対応サイクルより前(知見45)に実装した
    ため、`_vb_num()`による文字列/`Nothing`強制が漏れていた——生成コードの
    `({left}) < 0`という直接比較が`None < 0`/`str < int`で`TypeError`に
    なっていた。`Operators.vb`の`ExponentObject`で`Empty`→`0.0`への変換を
    確認し(`Empty ^ Empty`=`0.0^0.0`=`1`)、`^`の両オペランドに
    `_vb_num()`を適用するよう修正。既存の`eval()`直接実行型テストが
    `_vb_num`未定義で壊れたため、`VB_NUM_HELPER_SOURCE`を明示的に
    名前空間へ注入するよう追従。回帰テスト追加、UiPath関連テスト全166件
    通過。知見55〜57で3回連続、ランタイムソースのクロスチェックから
    実在するバグが見つかった——残りの演算子ディスパッチャ
    (`And`/`Or`/`Xor`/`Not`の`Nothing`絡み、単項`-`)も確認する価値が
    ある。
20. **(完了、2026-11-05)** 単項`Not`/`-`/`+`も`Nothing`オペランドで
    `TypeError`になるバグを解決(VM不使用、知見58——知見57の提案を実行し
    4回連続のクロスチェック的中): `NotObject`/`NegateObject`/
    `PlusObject`いずれも`Case TypeCode.Empty`で`Nothing`を整数`0`として
    扱う(`Not Nothing`=`Not 0`=`-1`、`-Nothing`/`+Nothing`=`0`)。
    修正前は`~None`/`-(None)`/`+(None)`がいずれも`TypeError`を送出して
    いた。3演算子とも`None`を`0`へ読み替えてから演算するよう修正。
    回帰テスト追加、UiPath関連テスト全169件通過。`And`/`Or`/`Xor`
    (二項)の`Nothing`絡みは型依存の分岐が複雑(`Boolean`相手なら論理
    演算結果、`Integer`相手ならそのオペランドの型を維持する等)なため、
    でっち上げた中途半端な実装を避け未対応のまま明示的に記録——実データで
    このパターンが見つかった時点で改めて着手する。
21. **(完了、2026-11-05)** `And`/`Or`/`Xor`の`Nothing`絡みも解決(VM
    不使用、知見59——知見58で「複雑なため保留」としていたが、
    `Operators.vb`の型ごとの分岐を具体的に書き出したことで解決、5回連続
    のクロスチェック的中): `And`は`Nothing`が他方`Boolean`なら`False`・
    `Integer`なら`0`、`Or`/`Xor`は`Nothing`が単位元として働くため他方の
    オペランドをそのまま返す(型も維持)。`_vb_and()`/`_vb_or()`/
    `_vb_xor()`の3ヘルパーを追加し、単純な`&`/`|`/`^`への直接変換から
    これらのヘルパー呼び出しへ変更(両方値がある既存ケースは内部で
    従来通り`&`/`|`/`^`を使うため挙動不変)。回帰テスト追加、UiPath
    関連テスト全180件通過。これで`uipath_codegen`が扱う主要な演算子
    (算術・比較・論理・文字列結合・単項)の`Nothing`絡みエッジケースは
    全て確認・対応済みになった。
22. **(完了、2026-11-05)** `AndAlso`/`OrElse`が常にBoolean型の結果を
    返さないバグを解決(VM不使用、知見60——今回は`Operators.vb`ではなく
    公式ドキュメントの再読で発見、6回連続のクロスチェック的中):
    Microsoft Learn「AndAlso Operator」が「両オペランドを評価前に
    Booleanへ変換し、結果も常にBoolean」と明記——従来「Pythonの`and`/
    `or`と意味論が完全一致する」としていたのは誤りで、Pythonの`and`/
    `or`は生のオペランド値をそのまま返すため`0 AndAlso True`のような
    非Boolean値混在ケースで食い違っていた(VBは`False`、Pythonの
    `0 and True`は`0`)。`_vb_bool()`ヘルパー(`CBool`の文字列判定/
    桁区切り受理規則をランタイム版にしたもの)で両オペランドを明示的に
    Booleanへ変換してから`and`/`or`(短絡評価自体は活用)を適用する
    よう修正。回帰テスト追加(短絡評価が引き続き機能することも生成
    コード自体で確認)、UiPath関連テスト全189件通過。知見44〜60の系統
    点検はこれで完全に完了した。
23. **(完了、2026-11-05)** `If`/`While`/`DoWhile`/三項`If()`の条件も
    Boolean変換が必要と判明し修正(VM不使用、知見61——知見60と同じ
    食い違いが制御構文全体に波及していた、7回連続のクロスチェック的中、
    今回の系統点検で最も実用上のインパクトが大きい発見): Microsoft
    Learn「If...Then...Else Statement」が条件式を「Must evaluate to
    True or False, or to a data type that is implicitly convertible to
    Boolean」と定義——`AndAlso`/`OrElse`(知見60)と全く同じ規則。
    修正前は`If`/`While`/`DoWhile`/三項`If()`いずれも条件式をPythonの
    素の真偽値判定にそのまま委ねており、`If "False" Then`のような
    (緩い型のUiPath変数で現実的に起こりうる)ケースでVBと食い違って
    いた(VBはCBool規則で偽、Pythonの素の`if "False":`は非空文字列
    なので真)。知見60の`_vb_bool()`ヘルパーを全ての条件式(`ElseIf`は
    `IfNode`の再帰構造で自動的に対応)・三項`If()`の第1引数に適用する
    よう修正。既存のブリトルなテスト2件を新形式に追従させ、回帰テスト
    3件追加。UiPath関連テスト全196件通過、リポジトリ全体で全804件通過。
    知見44〜61の系統点検はこれで完全に完了した。
24. **(完了、2026-11-05)** `CBool`の非リテラルフォールバックを
    `_vb_bool()`へ統一(VM不使用、知見62——知見43から記録し続けていた
    既知の限界を、知見60・61で導入したヘルパーの再利用で解消):
    `CBool(someVar)`のような非リテラル引数は従来素の`bool(x)`に
    フォールバックしており、`someVar`が`"False"`/`"0"`を保持する
    文字列の場合に食い違う既知の限界だった。`_vb_bool()`はまさにこの
    用途のために設計されていたため、新規ロジック追加無しで切り替える
    だけで解決。既存テストを更新、値ベースの回帰テストを追加。UiPath
    関連テスト全197件通過。1つのヘルパー追加が複数の既知の限界を
    同時に解消する好例になった。
25. **(完了、2026-11-05)** `CBool`のリテラル文字列専用判定
    (`_vb_cbool_of_string_literal`)が桁区切り文字列を受理せず不整合
    だったバグを修正(VM不使用、知見63——知見62を見直した際に対になる
    コード生成時専用ロジックも確認して発見): `_vb_bool()`はコンマを
    除去してから数値変換するが、コード生成時専用の
    `_vb_cbool_of_string_literal()`は素の`float(text)`のままだった
    ため、`CBool("1,234")`のような桁区切り文字列**リテラル**だけが
    `NotImplementedError`(コード生成失敗)になっていた——同じ値を
    変数経由で渡せば正しく処理できるのに、リテラル直書きだけ失敗する
    不整合。`.replace(",", "")`を追加して規則を揃えた。回帰テスト
    追加、UiPath関連テスト全198件通過。
26. **(完了、2026-11-05)** 文字列補間`$"...{expr}..."`のプレーンな補間を
    実装(VM不使用、公式ドキュメントで構文確定、知見65——知見36以来
    `# TODO`のまま放置していた機能を実装): Microsoft Learn「Interpolated
    Strings」で構文を確定(`{{`/`}}`がリテラル波括弧のエスケープ、
    `{expr[,width][:format]}`が補間式)。`uipath_codegen/render.py`に
    `{`/`}`の深さとネストしたクォート状態を追跡する手書きの状態機械
    (`_split_interpolated_string`)を実装し、プレーンな`{expr}`補間を
    `"text1" + _vb_cstr(expr1) + ...`という`+`連結へ変換(f-stringでは
    ない——`repr()`のクォート文字衝突リスクと、`_vb_cstr()`のVB書式
    規則(知見46)を活かすため)。書式指定子・フィールド幅は確証が無いため
    `NotImplementedError`で`# TODO`へ委ねる。`uipath_expr`のLarkレクサ
    自体は`{expr}`内のネストした文字列リテラルをまだ区別できない既知の
    限界が残る(より大きな変更が必要なため今回は見送り、安全に`# TODO`
    へ倒れることは確認済み)。回帰テスト追加(知見36の実例含む)、UiPath
    関連テスト全204件通過、リポジトリ全体で全818件通過。
27. **(完了、2026-11-05)** 文字列補間`{expr}`内部にネストした文字列
    リテラルを含む式(公式ドキュメント自身の`If(age = 1, "", "s")`の例)
    を解決(VM不使用、知見66——知見65で「より大きな変更が必要」として
    見送っていたLarkレクサの限界を解消): `uipath_expr`に、Lark呼び出し
    前に`{`/`}`の深さを追跡する手書きの状態機械
    (`_find_interp_string_span`)で`$"..."`の正しい境界を確定し、不透明な
    プレースホルダへ一時置換してからLarkへ渡す`_prescan_interpolated_
    strings()`を追加。既存の`INTERP_STRING`正規表現自体は書き換えず、
    前処理1段で「補間文字列自身の`""`エスケープ」と「`{expr}`内の
    ネストしたVB文字列リテラル」の区別不能問題を回避した。知見65で既に
    実装済みだった`render.py`側のコード生成能力(`_split_interpolated_
    string`)にようやく到達できるようになり、`If(age = 1, "", "s")`を
    含む補間も正しく`exec()`できることを確認(`"Alice is old."`)。
    回帰テスト追加(複数`{expr}`・閉じ忘れの安全フォールバックも含む)、
    UiPath関連テスト全207件通過、リポジトリ全体で全825件通過。文字列
    補間の残課題は書式指定子・フィールド幅(知見65参照)のみとなった。
28. **(完了、2026-11-05)** `CDbl`/`CInt`/`CBool`の`&H`/`&O`16進・8進
    リテラル文字列非対応を解決(VM不使用、知見67——知見46・53で2回
    「軽微な既知の限界」として先送りしていた残課題): .NETランタイム
    本体のソース(`Microsoft.VisualBasic.CompilerServices.Utils.
    IsHexOrOctValue`、定義は`Conversions.vb`ではなく別ファイル
    `Utils.LateBinder.vb`——`gh api search/code`でリポジトリ全体検索し
    発見)で、`&H1A`/`&O17`のような文字列が`ParseDouble`を経由せず
    直接16進/8進の整数として変換されると確定。`_vb_cdbl`(`CDbl`/`CInt`
    共用)・`_vb_bool`(`CBool`)・`_vb_cbool_of_string_literal`(`CBool`
    リテラル専用判定、新規共有関数`_parse_vb_hex_or_oct_str`経由)の
    3箇所に同じ`&H`/`&O`判定を追加。`&B`2進リテラル文字列は実例が無い
    ため今回も対象外のまま。回帰テスト追加(リテラル・変数経由の両方)、
    UiPath関連テスト全215件通過、リポジトリ全体で全835件通過。
29. **(完了、2026-11-05)** 演算子ディスパッチャ(`+`/`-`/`*`/`/`/`Mod`/
    比較演算子)の文字列オペランドも`&H`/`&O`16進・8進リテラルとして
    解釈されると確定(VM不使用、知見68——知見67をCDbl/CInt/CBool限定で
    終えた直後、既に取得済みの`Operators.vb`を再確認して波及を発見):
    `AddObject`/`SubtractObject`/`MultiplyObject`/`DivideObject`/
    `ModObject`/`CompareObjectEqual`いずれの文字列オペランド変換も
    `CDbl(Convert.ToString(x))`——知見67と同じ変換経路だったため、
    `"&H1A" + 1`(`27`)等が演算子の文字列オペランドとしても16進リテラル
    として解釈されると確定。`_vb_cmp`/`_vb_add`/`_vb_num`/`_vb_div`/
    `_vb_mod`の全5ヘルパーに同じ判定を追加(`_collect_imports`の制約上、
    各ヘルパーへロジックを複製)。回帰テスト追加、UiPath関連テスト全224件
    通過、リポジトリ全体で全844件通過。
30. **(完了、2026-11-05)** 文字列補間の`{expr}`内部にさらに別の補間
    文字列をネストしたケース(`$"outer {$"inner {x}"}"`)を実際に検証
    (VM不使用、知見69——知見65・66の設計時点では「範囲外」と見なして
    いたが、実際に`exec()`して確認したところ追加実装無しで既に正しく
    動作すると判明): `_find_interp_string_span`(知見66)が`$`自体を
    特別扱いしないこと、`_render_interpolated_string`(知見65)が
    `{expr}`セグメントを再帰的に解析・レンダリングする設計であることの
    2点の組み合わせの副作用として、追加コード無しで動いていた。
    レクサ・コード生成両方のレベルで回帰テストを追加、UiPath関連テスト
    全226件通過、リポジトリ全体で全846件通過。
31. **(完了、2026-11-05)** `uipath_codegen`のカバレッジ測定ツールを新規
    作成(VM不使用、知見70——Phase 4が明記していたが未着手だった
    `codegen_coverage.py`相当の積み残しに着手): 実機確認済みXAML
    フィクスチャ(`Main.xaml`/`Sub1.xaml`)を対象に測定し、現状72%
    (21/29分岐点)を実測。既知の仕様通りの3件を除く残り5件
    (`ExcelApplicationScopeNode`/`ExcelWriteCellNode`/`HttpClientNode`/
    `InvokeCodeNode`/`SendOutlookMailNode`)が、Tier1確定済みにも
    かかわらず未実装のままと数値で確定(新規バグではなく既存コメントが
    明記していた既知の先送り)。回帰テスト追加、UiPath関連テスト全228件
    通過、リポジトリ全体で全849件通過。
32. **(完了、2026-11-05)** `ui:Click`の`ClickType`/`MouseButton`/
    `KeyModifiers`属性が一切キャプチャされず常に単純な左シングルクリック
    として生成される、サイレントな(これまで一度も`# TODO`にならない)
    未検出ギャップを発見・部分的に解決(VM不使用、知見71——知見70の
    カバレッジツール実装作業中に実際のXML属性を再確認して発見): 実機
    確認済みの唯一の値(`CLICK_SINGLE`/`BTN_LEFT`/`None`)の場合のみ従来
    通り`.click_input()`を生成し、それ以外の値(ダブルクリック・右クリック・
    修飾キー併用等、実際のシリアライズ文字列を未確認)は`# TODO`へ倒す
    (`uipath_selector`の`role`属性と同じ「でっち上げるより安全側に倒す」
    方針)。確認済み既定値のケースは挙動を一切変えない。回帰テスト追加、
    UiPath関連テスト全233件通過、リポジトリ全体で全854件通過。
33. **(完了、2026-11-05)** `ui:InvokeWorkflowFile`の`ContinueOnError`
    属性が無視され、`True`設定時に意図しない例外伝播を起こすギャップを
    発見・安全側に倒して解決(VM不使用、知見72——知見71と同じ「実機属性の
    再読み込み」手法で発見。全アクティビティ共通ではなく`InvokeWorkflowFile`/
    `HttpClient`/`InvokeCode`の3要素のみが持つ属性と確認、実際に影響する
    のは実コード生成される`InvokeWorkflowFileNode`のみ): 確認済みの安全な
    値(`None`=未設定、または明示的な`"False"`)の場合のみ従来通り関数
    呼び出しを生成し、`"True"`等は`# TODO`へ倒す(でっち上げたtry/except
    変換はしない)。確認済み既定値のケースは挙動を一切変えない。回帰テスト
    追加、UiPath関連テスト全236件通過、リポジトリ全体で全857件通過。
34. **(完了、2026-11-05)** `ui:Click.CursorPosition`の`Position`属性も
    同じ「サイレントに無視される」パターンと確認、知見71と同じ方針で解決
    (VM不使用、知見73——知見71の属性調査中に同じ要素内の別の子プロパティ
    要素にも気づいた): 実機確認済みの値は`"Center"`のみで、pywinautoの
    `click_input()`既定(ターゲット要素の中心)と一致するため現状のコードは
    確認済みの意味で正しいと確定。`cursor_position`が`None`/`"Center"`の
    場合のみ従来通りコードを生成し、それ以外(`"TopLeft"`等)は`# TODO`へ
    倒す。確認済み既定値のケースは挙動を一切変えない。回帰テスト追加、
    UiPath関連テスト全239件通過、リポジトリ全体で全863件通過。`ui:Click`の
    残る属性(`AlterIfDisabled`/`CursorMotionType`/`DelayBefore`/`DelayMS`/
    `SendWindowMessages`/`SimulateClick`)は実データでの非既定値使用実例が
    無いため未対応のまま記録(知見46のEncodingと同じ優先度判断)。
35. **(完了、2026-11-05)** 配列/コレクション/`DataTable`行アクセスの
    `識別子(引数)`構文が関数呼び出しと言語レベルで曖昧であると発見・現状の
    安全な挙動をロック(VM不使用、知見74——`uipath_expr`の実装不備ではなく
    VB.NET自体の構文的曖昧性、静的型解決無しでは判別不可能): `myArray(0)`
    のような式は常に`FuncCall`として解釈され、Tier1関数名以外は安全に
    `# TODO`へ倒れる(架空の添字アクセス変換はしない)ことを確認・回帰
    テストでロック。変数宣言を追跡して曖昧性を解消する設計の方向性は
    `design/uipath_xaml_findings.md`知見74に記録したが、実機での需要が
    無いため今回は実装を見送った。UiPath関連テスト全240件通過、リポジトリ
    全体で全864件通過。
36. **(完了、2026-11-05)** 知見70で発見した5つの未対応アクティビティの
    `# TODO`コメントに捕捉済みフィールドを追記(VM不使用、知見75——でっち
    上げ無しの改善、人間が手動実装する際に元の`.xaml`へ戻らなくて済む
    手がかりを増やす): `InvokeCodeNode.code`/`ExcelApplicationScopeNode.
    workbook_path`/`ExcelWriteCellNode.cell`・`sheet_name`/
    `SendOutlookMailNode.to`・`subject`/`HttpClientNode.endpoint`・
    `method`を`# TODO`コメントへ追記。コード生成の判断自体は変えず、
    既に捕捉済みのデータを見やすくするだけ。知見70のカバレッジツールの
    出力も副次的に具体的になった。回帰テスト追加、UiPath関連テスト全245件
    通過、リポジトリ全体で全870件通過。
37. **(完了、2026-11-05)** `TryCatch`に複数の`catches`があり未知の.NET
    例外型が同じPython例外型(`Exception`)へ解決される場合、後続の
    ハンドラが到達不能な死んだコードになる実在するバグを発見・安全側に
    倒して解決(VM不使用、知見76——既存コードの実装を読み返し、複数件
    文脈での挙動を`exec()`で具体的に確認して発見): `_EXCEPTION_TYPE_MAP`
    の「未知型は`Exception`にフォールバック」という簡略化が、`catches`
    2件以上では「特定の例外だけ別処理、それ以外は汎用処理」という一般的な
    RPAパターンを壊すと実証(2番目のハンドラが実行時に一度も到達しない)。
    `catches`が2件以上の場合、解決されるPython例外型に重複が無いかを
    事前確認し、重複時はTryCatch全体を`# TODO`へ倒す(でっち上げた例外
    階層対応はしない)。1件のみの`catches`(実機確認済み)は影響無し。
    回帰テスト追加、UiPath関連テスト全247件通過、リポジトリ全体で全872件
    通過。
38. **(完了、2026-11-05)** `Switch`の`Case`比較が`=`演算子と同じ型変換
    規則に従うと公式ドキュメントで確定、素の`==`のままだった食い違いを
    解決(VM不使用、知見77——知見76と同じ「既存コードの読み返し」で発見):
    Microsoft Learn「Select...Case Statement」のRemarksが`Case
    expression`は`testexpression = expression`として評価されると明記
    ——`=`演算子と同じ`_vb_cmp()`(知見47)経由の比較へ統一した。`Switch`の
    `Expression`が`type_arguments`の宣言と異なる実行時の型(例: 宣言上は
    `x:Int32`だが実際は文字列)を保持している場合でも正しく一致する
    ことを`exec()`で確認(修正前は素の`==`で対応するアームが丸ごと
    スキップされていた)。既存テストを新しい生成コード形に追従させ、
    実際にバグを再現するテストを追加。UiPath関連テスト全248件通過、
    リポジトリ全体で全873件通過。
39. **(完了、2026-11-05)** ワークフロー引数の`OutArgument`/
    `InOutArgument`方向がPythonの値渡しパラメータでは呼び出し元への
    書き戻しを実現できないと確認・`# TODO`で明示(VM不使用、知見78——
    知見76・77の「既存コードの読み返し」を`generate_python()`自体にも
    適用して発見。実機属性ではなく型文字列(`OutArgument(x:String)`等)
    自体から直接確定できる言語レベルの事実): VBの`OutArgument`/
    `InOutArgument`は呼び出し元の変数を更新するByRef相当の渡し方だが、
    `generate_python()`は全引数を単純な値渡しパラメータとして扱い、
    `return`文も呼び出し側での変数再束縛も生成していなかった。
    `OutArgument`/`InOutArgument`方向の引数を検出し、関数本体の先頭に
    `# TODO`を追記(関数自体の生成は継続、`In`方向の引数は正しく機能する
    ため全体は倒さない)。回帰テスト追加、UiPath関連テスト全251件通過、
    リポジトリ全体で全876件通過。
40. **(完了、2026-11-05)** `ui:MessageBox`の`Caption`が捕捉済みなのに
    生成コードで一度も使われていなかった点を解決(VM不使用、知見79——
    バグではなく「データの未活用」、知見75・71・73と同系統の改善):
    `MessageBoxNode.caption`が`None`でない場合、`print(_vb_cstr(caption)
    + ': ' + _vb_cstr(text))`のように出力へ含める。`Caption`が未設定
    (実機確認済みの既定)の場合は従来通り挙動を変えない。回帰テスト
    追加、UiPath関連テスト全253件通過、リポジトリ全体で全880件通過。
41. **(完了、2026-11-05)** `ui:Click`の`display_name`が捕捉済みなのに
    未活用だった点を解決(VM不使用、知見80——知見79に続く「捕捉済み
    データの未活用」): `node.display_name`が設定されている場合、
    `# {display_name}`コメントを先頭に追記する(`# TODO`に倒れる分岐も
    含む)。コメントのみの追加で既存の判定ロジック・生成コード自体は
    変更しない。`SequenceNode.display_name`は至る所にネストして出現し
    非説明的な名前が多いため価値/ノイズ比が異なると判断し対象外のまま。
    回帰テスト追加、UiPath関連テスト全254件通過、リポジトリ全体で全881件
    通過。
42. **(完了、2026-11-05)** 知見77(Switchの比較を`_vb_cmp()`経由に統一)
    が`x:Boolean`型の`Switch`キーで新規のクラッシュを生んでいたと自己
    点検で発見・修正(VM不使用、知見81——「この修正自体が新しい問題を
    生んでいないか」の検証で発見): `_render_switch_key`が`x:Boolean`型を
    特別扱いしておらず素の文字列リテラル(`'True'`)のままだったため、
    `_vb_cmp`の`bool`→`int`変換(知見51)と噛み合わず`_s2f("True")`が
    `float()`に失敗して`ValueError`でクラッシュすると`exec()`で確認
    (知見77導入前は素の`==`で単に不一致になるだけで済んでいた)。
    `x:Boolean`型のキーも裸のPython真偽値リテラル(`True`/`False`)として
    出力するよう修正。回帰テスト追加、UiPath関連テスト全258件通過、
    リポジトリ全体で全885件通過。
43. **(完了、2026-11-05)** `Append Line`/`Read Text File`の相対パス
    (`FileName`)の解決基準が公式ドキュメント・実データのいずれでも
    確定できないと確認、既知の残課題として明示的に記録(VM不使用、
    知見82——でっち上げを避けた判断): UiPathフォーラムの非公式情報では
    「プロジェクトフォルダ基準」「Orchestrator経由では見つからない事例」
    「Library内では呼び出し元プロジェクト基準」という互いに矛盾する
    報告があり、単一の確定した仕様として扱えないと判断——現状の素朴な
    `open(file_name, ...)`(Pythonプロセスの実行時カレントディレクトリ
    基準)のままにし、コード側のdocstringとdesign/uipath_xaml_findings.md
    双方に不確実性を明示するコメントを追加した(コード生成ロジック自体の
    変更は無し)。
44. **(完了、2026-11-05)** `InvokeCodeNode.arguments`(知見23)も知見75の
    TODOコメント追記対象に拡張(VM不使用、知見83——知見75実装時に
    見落としていたフィールド): `Code`自体は表示されるが、どの外部変数が
    渡されているか(実機フィクスチャでは`myArg`→`content`)は元のXAMLを
    見ないと分からないままだった。`Code`テキストが`Arguments`のキー名を
    直接参照するとは限らない(知見17・23で確認済みの不一致)ため、対応
    付けの説明はでっち上げず捕捉した生データをそのまま素通しする。
    回帰テスト追加、UiPath関連テスト全260件通過、リポジトリ全体で全907件
    通過。
45. **(完了、2026-11-05)** `ExcelApplicationScopeNode`の子アクティビティが
    スコープ自体の`# TODO`化と一緒にサイレントに失われていた実在するバグ
    を発見・修正(VM不使用、知見84——知見70の5つの未対応アクティビティの
    うちこれだけが子を持つコンテナ構造と気づいて発見): スコープ全体を
    1行の`# TODO`へ潰す従来の実装は`node.body`を一切見ておらず、スコープ
    自体とは無関係に正しく生成できる子アクティビティ(例: `print()`で
    済む`MessageBox`)まで完全に失っていた。`_generate_unresolved_
    activity`が`invoke_resolver`を受け取り、`ExcelApplicationScopeNode`
    の場合はスコープのTODOに続けて子を`_generate_body`で通常通り再帰
    生成するよう修正。実機フィクスチャ(`Main.xaml`)で、修正前は子の
    `ExcelWriteCellNode`の`# TODO`行が生成結果に一切出現しなかったことを
    確認した上で修正。回帰テスト追加、UiPath関連テスト全262件通過、
    リポジトリ全体で全916件通過。
46. **(完了、2026-11-05)** `UnknownActivityNode`が子要素を一切保持しない
    のは知見84と同じ種類のバグではなく意図的な設計と確認(VM不使用、
    知見85——知見84の直後の自己点検、コード変更無し): 未知のアクティビ
    ティ型の子要素が「実行すべき子アクティビティの列」か「設定用の
    プロパティ要素」かは、具体的な型を知らない限り判別不可能——
    `ExcelApplicationScopeNode`で子を再帰生成するよう修正したのは、
    知見22でその特定の型の構造を個別に確認していたからであり、未知の型全般に
    同じ仮定を広げるのはでっち上げになる。コードは変更せず、将来の誤修正
    を防ぐための注記のみ`UnknownActivityNode`のdocstringに追加した。
47. **(完了、2026-11-05)** 知見86で見送った、呼び出し元側への`Out`/
    `InOutArgument`警告を実装(VM不使用、知見87——`invoke_resolver`の型を
    拡張せず、並行する新規オプション引数`out_arg_resolver`を追加する
    ことで後方互換性を保ったまま実現): 知見78の判定ロジックを
    `_collect_out_arg_names()`へ共通化し、`generate_python()`/
    `_generate_node()`/`_generate_body()`以下の全生成関数に
    `invoke_resolver`と並行して素通しする(既存の配線パターンを複製する
    だけの機械的な変更)。`_generate_invoke_workflow_file()`が解決済みの
    呼び出し先の`out_arg_resolver`エントリと今回の呼び出しの引数キーの
    積集合を取り、該当があれば呼び出し文の直前に`# WARNING`を追記する。
    `generate_project_python()`が新設の`_build_out_arg_resolver()`で
    これを構築する。合成2ファイル構成で実際に`# WARNING`が正しく出る
    ことを確認、実機確認済みの`Main.xaml`/`Sub1.xaml`(`In`方向のみ)では
    新しい警告が出ないことも確認——既存の生成結果への退行は無い。
    回帰テスト追加、UiPath関連テスト全264件通過、リポジトリ全体で全920件
    通過。
48. **(完了、2026-11-05)** 知見84が初めて意味を持たせてしまった退行——
    `ExcelApplicationScope`内の`Invoke Workflow File`参照が複数ファイル
    発見で見つけてもらえず常に未解決になるバグを発見・修正(VM不使用、
    知見88——知見87の検証作業中に発見): 複数ファイルのBFS発見を担う
    `_child_node_lists`関数に`ExcelApplicationScopeNode`の分岐が無かった
    ——知見84より前はスコープの子が丸ごと`# TODO`に潰されていたため
    無害だったが、知見84で子アクティビティが実際に再帰生成されるように
    なった結果、この欠落が初めて実害のある退行として現れた(実際に
    `generate_project_python()`を実行して再現を確認)。`_child_node_
    lists`に分岐を追加して修正。回帰テスト追加、UiPath関連テスト全267件
    通過、リポジトリ全体で全928件通過。
49. **(完了、2026-11-05)** 単項`-`/`+`が文字列オペランドで常に
    `TypeError`になっていた実在するバグを発見・`_vb_num()`への統一で
    解決(VM不使用、知見89——`^`演算子(対応済み)と単項`-`/`+`(`Nothing`
    のみ対応済み、知見58)を横に並べて比較して発見): `CStr(-"5")`
    (`&H`限定ではなく単純な数値文字列)を実際に`exec()`して
    `TypeError: bad operand type for unary -: 'str'`を再現。単項`-`/`+`の
    レンダリングを`Nothing`専用の`lambda`ラップから、他の数値演算子と
    同じ`_vb_num()`ヘルパーへの統一に変更——`Nothing`の既存挙動を変えず
    文字列(`&H`/`&O`16進8進リテラル含む)対応を解消、副次的に`lambda`
    ラップも不要になった。回帰テスト追加、UiPath関連テスト全265件通過、
    リポジトリ全体で全954件通過。
50. **(完了、2026-11-05)** `Not`も単項`-`/`+`と全く同じ理由で文字列
    オペランドで常に`TypeError`になっていたバグを解決(VM不使用、
    知見90——知見89の兄弟バグ、修正直後に同じファミリーの他演算子を
    確認して発見): `CStr(Not "5")`を実際に`exec()`して
    `TypeError: bad operand type for unary ~: 'str'`を再現。`Not`の
    `bool`以外分岐を`0 if _x is None else _x`から
    `round(_vb_num(_x))`へ変更——既存の`Nothing`/数値オペランドの確認済み
    挙動を全て変えずに文字列(`&H`/`&O`16進8進リテラル含む)対応を解消。
    回帰テスト追加、UiPath関連テスト全267件通過、リポジトリ全体で全964件
    通過。
51. **(完了、2026-11-05)** `And`/`Or`/`Xor`も単項`-`/`+`・`Not`と全く
    同じ理由で文字列オペランドで常に`TypeError`になっていたバグを解決
    (VM不使用、知見91——知見89・90に続く3件目の兄弟バグ): `CStr("5"
    And 3)`を実際に`exec()`して`TypeError: unsupported operand type(s)
    for &: 'str' and 'int'`を再現。両オペランドが非`Nothing`の最終行
    (`a & b`等)にのみ文字列コンバート(`_vb_num`+`round()`と同じ規則)を
    追加——`Nothing`絡みの既存分岐(知見59で個別に実機確認済み)は変更
    せず、確実にクラッシュするケースだけに修正範囲を絞った。回帰テスト
    追加、UiPath関連テスト全271件通過、リポジトリ全体で全969件通過。
    `-`/`+`/`Not`/`And`/`Or`/`Xor`という型依存の単項/二項演算子ファミリー
    はこれで一通り確認済みになった。
52. **(完了、2026-11-05)** `UnknownActivityNode.attrs`/`HttpClientNode.
    extra_attrs`が既に捕捉済みなのに`# TODO`コメントへ一度も出ていなかった
    バグを解決(VM不使用、知見92——ロードマップ俯瞰レビューで洗い出した
    「残タスク」(下記参照)がいずれも意思決定待ちだったため、自律ループを
    安全に再開できる別の角度として、知見75/79/80/83と同じ「捕捉済み
    データの未活用」パターンをキャッチオール経路(`UnknownActivityNode`)
    自体にも広げて確認して発見): Library呼び出し(`<p:NewActivity
    in_greeting="hellofromlib" .../>`)の引数のような、人間が手動移植する
    際に最も必要な情報が`attrs`/`extra_attrs`に捕捉されているのに生成
    コードから一切見えなかった。`_generate_unknown`/
    `_generate_unresolved_activity`のHttpClient分岐に、捕捉済みの生データを
    ソート済み辞書としてそのまま追記(`DisplayName`は別途表示済みのため
    重複除外、でっち上げた解釈は追加しない)。回帰テスト3件追加、UiPath
    関連テスト全274件通過、リポジトリ全体で全979件通過。
53. **(完了、2026-11-05)** `ExcelWriteCellNode.text`/`SendOutlookMailNode.
    body`も知見75で見落としていた捕捉済みフィールドだったのを解決
    (VM不使用、知見93——知見92修正直後に同じ関数内の他の分岐も横展開して
    確認して発見): 実際にセルへ書き込む値(`Text`)・メール本文
    (`Body`)そのものが生成コードから一切見えなかった。
    `_generate_unresolved_activity`の`ExcelWriteCellNode`/
    `SendOutlookMailNode`分岐にそれぞれ追記。既存テストの期待値更新、
    UiPath関連テスト全274件通過、リポジトリ全体で全979件通過。
54. **(完了、2026-11-05)** `ExcelApplicationScopeNode.scope_var`も
    `WorkbookPath`と同じく捕捉済みなのに未表示だったのを解決(VM不使用、
    知見94——知見92・93に続く同系統の横展開、これで
    `_generate_unresolved_activity`の全分岐のフィールドを一通り確認済み):
    回帰テスト追加(デフォルト値・カスタム値の両方)、UiPath関連テスト
    全275件通過、リポジトリ全体で全988件通過。
55. **(完了、2026-11-05)** `generate_project_from_json`のLibrary拒否が
    実物の実機フィクスチャ(`uipath_xaml_probe_lib`)では一度もテスト
    されていなかったのを解決(VM不使用、知見95——「残タスクC: 検証基盤の
    薄さ」を埋める改善、バグ修正ではなく既存フィクスチャの再活用):
    挙動自体は変更無し、合成`project.json`テストに加えて実機フィクスチャ
    でも同じ拒否が成立することをロック。回帰テスト追加、UiPath関連テスト
    全276件通過、リポジトリ全体で全1005件通過。
56. **(完了、2026-11-05)** `HttpClientNode`の`requests`への実コード生成を
    実装(VM不使用、知見96——ユーザーがFlowchart実装・Excel=openpyxl・
    Outlook=win32com・HttpClient先行・InvokeCode見送りを明示的に決定した
    直後に着手、残タスクB参照): 実機フィクスチャ(`Headers`等のコレクション
    全て空、`Body`未設定)という最も単純な構成に限り`requests.request(method,
    endpoint, timeout=...)`を生成するよう`HttpClientNode`に`body`/
    `timeout_ms`/`has_populated_collections`フィールドを追加。`TimeoutMS`
    既定値6000ms・`AcceptFormat`/`BodyFormat`既定値はUiPath公式ドキュメント
    (docs.uipath.com)で確認——実機フィクスチャの値はいずれもStudio既定値
    のままだったと確定。`requests`を新規依存に追加(`uv add requests`)。
    カバレッジ72%→76%(22/29)に向上、知見70の未対応5活動は4件に減少。
    回帰テスト5件追加、既存のTODO系テスト・カバレッジ閾値テストを更新、
    UiPath関連テスト全280件通過、リポジトリ全体で全1013件通過。
57. **(完了、2026-11-05)** `ExcelApplicationScopeNode`+`ExcelWriteCellNode`
    の`openpyxl`への実コード生成を実装(VM不使用、知見97——知見96に続く
    残タスクB着手): PAD側`pad_action_lib.excel_actions`と同じ「開く→
    操作→保存」モデル(`openpyxl.load_workbook`/`.save`)を踏襲し、
    `scope_var`(知見94)を実際のPython変数名として使う。知見22で確認済みの
    実機構造(Write Cellがスコープの直接の子)に限り`{var}[sheet][cell] =
    _vb_cstr(value)`を生成、それ以外は安全に`# TODO`。カバレッジ76%→79%
    (23/29)。知見84の子再帰生成ロジックは専用関数へ完全に移行したため
    死んだコードとして削除。回帰テスト更新・追加、UiPath関連テスト全280件
    通過、リポジトリ全体で全1014件通過。
58. **(完了、2026-11-05)** `SendOutlookMailNode`の`win32com.client`
    (Outlook COM)への実コード生成を実装(VM不使用、知見98——知見96・97に
    続く残タスクB完了): Microsoft Learn(Outlook VBAリファレンス)で
    `OlItemType.olMailItem=0`・`OlImportance`(Low=0/Normal=1/High=2)・
    `OlSensitivity`(Normal=0/Personal=1/Private=2/Confidential=3)を確認。
    `ClickType`/`MouseButton`(知見71)がUiPath独自トークン名だった教訓から、
    `Importance`/`Sensitivity`の確認済み値(`"Normal"`)以外は実コード
    生成せず安全に`# TODO`へ倒す——`Cc`/`Bcc`未設定・`Files`空・
    `IsBodyHtml`/`IsDraft`が`"False"`の場合のみ`Dispatch('Outlook.
    Application')`→`CreateItem(0)`→`To`/`Subject`/`Body`→`Send()`を
    生成。`extra_attrs`も最初から用意し知見92の再発を防止。カバレッジ
    79%→83%(24/29)。知見70の未対応5活動は残り2件
    (ExcelWriteCellNode/InvokeCodeNode)。回帰テスト追加、UiPath関連
    テスト全289件通過、リポジトリ全体で全1024件通過。
59. **Flowchart実機XAML直列化形の確定とVMブロッカーの経緯**(VM不使用、
    知見99・100): ユーザー決定によりFlowchart実装に着手したが、公式
    ドキュメント(Microsoft Learn「Flowchart workflows」概念説明ページと
    `Flowchart`クラスのAPI定義`[ContentProperty("Nodes")]`)が内部矛盾
    していたため、まずVM実機キャプチャ(pad2py-pad-host、サブエージェント
    委託)を試行——アクティブデスクトップ不在によるマウス/キーボード入力
    到達不能という環境要因でブロックされた(知見99、RDPセッションの
    接続状態を変えても再現、単純な「待てば直る」問題ではないと確認)。
    ローカル`.NET` SDKインストールでの代替検証も、サンドボックスの権限
    制約(外部スクリプト実行・sudo双方)でブロックされた。**第三の経路**
    として`gh api search/code`でGitHub上の実機保存済み`.xaml`ファイル
    (UiPath Studio自身が保存した実物、Microsoft公式サンプルも含む)を
    直接検索・取得し、VM不使用のまま直列化形を確定した(知見100)——
    `x:Name`/`x:Reference`(属性値形・子要素形)/`Flowchart.StartNode`/
    `FlowStep.Next`/`FlowDecision.True`・`.False`/`FlowSwitch.Default`。
    実例が最初から循環・合流(「もう一度試しますか」という典型的な
    ループパターン)を含んでいたため、「非循環の木構造のみ安全側に対応」
    という当初の限定方針を撤回し、一般のグラフに最初から対応する設計へ
    変更した。
60. **(完了、2026-11-05)** Flowchartの実コード生成を実装(VM不使用、
    知見101——知見100の直列化形確定を受けて着手、残タスクA完了):
    `FlowStepNode`/`FlowDecisionNode`/`FlowSwitchArm`/`FlowSwitchNode`/
    `FlowchartNode`を新設(`WorkflowFile.root`を`SequenceNode |
    FlowchartNode`に拡張)。パースは知見30がState Machine用に見込んでいた
    「名前→ノードのマップを先に構築してからx:Referenceを解決する2パス
    方式」を初めて実装(`elem.iter()`によるブランケット走査、循環があっても
    無限ループしない)。コード生成はPythonに`goto`が無いため、ディスパッチ
    ループ(状態機械)パターン(`_flow`+`while`+`if/elif`、ノードの`id()`を
    キーにした整数ラベル)へ変換——任意のCFG(循環・合流含む)を表現する
    標準的な手法。`FlowDecision`は`_vb_bool()`(知見61)、`FlowSwitch`は
    `_vb_cmp()`(知見77、`Switch<T>`との類推)を流用。`FlowSwitch`で
    該当ケースも`Default`も無い場合は`_flow`を明示的に`None`へ倒す
    (さもなくば無限ループになる、`Switch`の「何もしない」意味論との
    唯一の相違点)。複数ファイルBFS発見(`_iter_invoke_nodes_for_root`)も
    Flowchartルートに対応。IRレベル(合流・循環を直接構築)・XAMLパース
    レベル(知見100の実機構造を模した合成XAML)の両方でテスト、無限ループ
    のリスクがある2経路(ケース不一致・Condition未設定)は実際に`exec()`
    してハングしないことまで確認。UiPath関連テスト全297件通過、リポジトリ
    全体で全1066件通過。Phase 1の決定文とスコープ実装の食い違い(残タスク
    A)はこれで完全に解消した。
61. **(完了、2026-11-05)** `ui:Click`の`ClickType="CLICK_DOUBLE"`・
    `MouseButton="BTN_RIGHT"`/`"BTN_MIDDLE"`の実コード生成に対応(VM
    不使用、知見102——知見100で確立した「GitHub上の実機保存済みXAMLを
    `gh api search/code`で直接検索する」手法をClickへ再適用、他の既知の
    限界にも汎用的に効く調査手法だと確定): いずれも実際にUiPath Studioが
    保存した公開済みXAMLで確認済み。pywinautoの実`click_input(button=,
    double=)`引数もインストール済みの実パッケージソースで確認。
    `KeyModifiers`の非既定値・`CLICK_UP`/`CLICK_DOWN`は複数キー併用時の
    区切り文字やドラッグ操作との組み合わせが未確認のため引き続き`# TODO`。
    回帰テスト追加、UiPath関連テスト全300件通過、リポジトリ全体で全1071件
    通過。
62. **(完了、2026-11-05)** `SendOutlookMailNode`の`Importance`/
    `Sensitivity`非既定値・`IsBodyHtml`/`IsDraft="True"`・`Cc`/`Bcc`の
    実コード生成に対応(VM不使用、知見103——知見102の手法をSendOutlookMail
    へ再適用): `Importance="High"`/`"Low"`・`Sensitivity="Personal"`/
    `"Confidential"`・`IsBodyHtml="True"`・`IsDraft="True"`・`Cc`/`Bcc`
    設定済みの実例をGitHub上の実機保存済みXAMLで確認。`.HTMLBody`
    (`IsBodyHtml`時)・`.CC`/`.BCC`・`.Save()`(`IsDraft`時)へマッピング
    (いずれもMicrosoft Learn Outlook VBAリファレンスで確認済み)。`Files`
    に添付がある場合のみ引き続き`# TODO`——これが唯一残る未対応ケース。
    回帰テスト更新・追加、UiPath関連テスト全302件通過、リポジトリ全体で
    全1073件通過。
63. **(完了、2026-11-05)** `HttpClientNode`の`Body`・`Headers`(populated
    時)の実コード生成に対応(VM不使用、知見104——知見102・103に続き
    知見100の手法を再適用): `Body="[text]"`の実例(POST)、`Headers`
    populated時の実直列化形(`scg:Dictionary`ラッパーが無くなり直接の子
    `<InArgument x:Key="...">`になる、値は直接テキスト形・ネストした
    `<Literal>`子要素形の両方が実在)をGitHub上の実機保存済みXAMLで確認。
    `requests`の`data=`/`headers=`引数へマッピング。`BodyFormat`/
    `AcceptFormat`のヘッダーへの自動反映はコミュニティ情報が矛盾しており
    未確認のため、でっち上げた自動注入はしない。`Cookies`/`Parameters`/
    `UrlSegments`/`Attachments`は引き続き`# TODO`。回帰テスト更新・追加、
    UiPath関連テスト全304件通過、リポジトリ全体で全1075件通過。
64. **(完了、2026-11-05)** `ui:Click.CursorPosition`の`Position=
    "TopLeft"`+`OffsetX`/`OffsetY`の実コード生成に対応(VM不使用、知見
    105——知見100の手法を5回目として再適用): pywinautoの`click_input
    (coords=...)`は既定で要素の左上を原点とする座標系を使うと実ソースで
    確認済みのため、`TopLeft`+オフセットは符号の曖昧性なく`coords=(x,
    y)`へマッピングできる。`TopRight`/`BottomLeft`/`BottomRight`は符号
    規約が未確認のため引き続き`# TODO`。`Center`に未確認の非`None`
    オフセットが付く組み合わせも安全側に倒す防御を追加。回帰テスト追加、
    UiPath関連テスト全308件通過、リポジトリ全体で全1087件通過。
65. **(完了、2026-11-05)** `ui:Click`の`DelayBefore`の実コード生成に対応
    (VM不使用、知見106——知見100の手法を6回目として再適用、`DelayMS`/
    `SimulateClick`/`SendWindowMessages`は見送り): `DelayBefore`はUiPath
    公式ドキュメントで「活動開始前の待機時間、既定200ms」と確認済みの
    ため`time.sleep()`へマッピング。`DelayMS`は公式ドキュメントに記載が
    無く意味論不明のため捕捉のみ・コード生成は`# TODO`。`SimulateClick`/
    `SendWindowMessages`は実在する値を確認したが、内部実装機構(pywinauto
    の`.invoke()`相当か`.click()`相当か)が確定できず、構造確認だけでは
    実行時メカニズムの確認に限界があると判断し見送った——知見100の手法の
    適用範囲の境界線を明確化した。回帰テスト追加、UiPath関連テスト全310件
    通過、リポジトリ全体で全1089件通過。
66. **(完了、2026-11-05)** `ui:MessageBox`の`Buttons`/`ChosenButton`を
    捕捉し、サイレントな選択結果の消失を防止(VM不使用、知見107——これまで
    捕捉すらしていなかった属性を発見): UiPath公式ドキュメントで
    `ChosenButton`の戻り値(`"Ok"`/`"Yes"`/`"No"`/`"Cancel"`)を確認、
    `gh api search/code`で`Buttons="YesNo"`等の実使用パターンを確認。
    `print()`という非対話的な変換方式自体は変えず(ユーザー入力の再現は
    v1のMessageBox変換方式の設計範囲外)、`Buttons`が単一ボタン以外、
    または`ChosenButton`が実際に束縛されている場合は`# TODO`へ倒す。
    回帰テスト追加、UiPath関連テスト全313件通過、リポジトリ全体で全1109件
    通過。
67. **(完了、2026-11-05)** `Append Line`/`Read Text File`の`Encoding`/
    `UseDefaultEncoding`未捕捉により実在していたエンコーディング食い違い
    バグを発見・修正(VM不使用、知見108——既存コードを公式ドキュメントと
    読み合わせて発見、知見76〜78と同系統の手法): `encoding="utf-8"`が
    無条件にハードコードされていたが、公式ドキュメントで`Append Line`の
    `UseDefaultEncoding=True`(既定)時はOSの既定エンコーディングになる
    べきと確認——実機フィクスチャの`UseDefaultEncoding=False`実例は
    たまたま確定済みの既定(UTF-8)と一致していたため発覚していなかった。
    確定済みの組み合わせだけを正しくマッピング、`ReadTextFile`は既存の
    確認済み動作を壊さない範囲で未確認のEncoding名のみ`# TODO`へ倒す。
    回帰テスト追加、UiPath関連テスト全319件通過、リポジトリ全体で全1123件
    通過。
68. **(完了、2026-11-05)** `ui:TypeInto`の実コード生成に新規対応(VM
    不使用、知見110——[design/uipath_feature_catalog.md](uipath_feature_catalog.md)
    のTier A最優先項目への着手第1件、知見100の手法を7回目として再適用):
    `UiPath/skills`公式リポジトリ含む複数件の実機保存済みXAMLで属性一覧を
    確認、docs.uipath.comの「UI Automationの入力方式」ページで既定方式が
    `pywinauto`の`type_keys()`(`SendInput`、`Click`の`click_input()`と
    同系統)と一致する「ハードウェアドライバー経由のシミュレート」だと
    確認。`ClickBeforeTyping`(クリック可否)・`Activate`/`ActivateBefore`
    (`set_foreground`kwarg)・`DelayBefore`/`DelayBetweenKeys`(待機時間)の
    確認済みの既定値・値セットのみ実コード生成し、`SimulateType`/
    `SendWindowMessages`(`Click`と同じ理由で機構未確認)・`EmptyField=
    True`(消去手段未確認)・`DelayMS`(未文書化)・`AlterIfDisabled`/
    `ContinueOnError`(前例踏襲で見送り)は`# TODO`へ倒す。`pywinauto`の
    `type_keys()`が`~^%+(){}`を特殊キー構文として解釈する罠
    (`pad_ui_helpers.py`がPAD調査時に発見した同じ罠)を回避するため、新設の
    `_pywinauto_type_keys_escape`ヘルパーを常に経由させる。回帰テスト追加
    (`tests/test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`24件)、
    UiPath関連テスト全345件通過、リポジトリ全体で全1158件通過。
69. **(完了、2026-11-05)** `ui:GetText`の実コード生成に新規対応(VM
    不使用、知見111——Tier A着手第2件、知見100の手法を8回目として再適用):
    `UiPath/skills`公式リポジトリの複数件で属性一覧が`ContinueOnError`/
    `DelayBefore`/`DelayMS`のみ(いずれもnullable)という単純な構造だと
    確定。公式ドキュメントは裏のCLR型を`GetValue`・プロパティ名を
    `Value`と記載するが実機XAMLの属性名は一貫して`Text`(知見29の
    `HttpClient`と同種の用語の食い違い)。抽出の正確なAPIは未確認だが
    「可視テキスト最大4096文字抽出」という挙動は確認済みのため、
    `pywinauto`の`window_text()`を`# WARNING`付きで採用(`Click`の
    セレクタ解決と同じ「1対1確認は主張しない」方針)。`DelayMS`/
    `ContinueOnError`は`Click`/`TypeInto`と同じ理由で`# TODO`。回帰テスト
    追加(`tests/test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`
    8件)、UiPath関連テスト全354件通過、リポジトリ全体で全1174件通過。
70. **(完了、2026-11-06)** `ui:SelectItem`の実コード生成に新規対応(VM
    不使用、知見112——Tier A着手第3件、知見100の手法を9回目として再適用):
    `ContinueOnError`/`DelayAfter`/`DelayBefore`/`Items`はいずれも
    nullable、`Item`(選択する値)が本体という構造だと確定。`AlterIfDisabled`
    は`Click`/`TypeInto`と違い公式ドキュメントで確認済みの既定(`True`
    相当、本活動は入力方式が`SimulateClick`固定で変更不可、無効化要素も
    既定で操作対象)——`"False"`のみ再現手段未確認で`# TODO`。選択自体は
    「対象アプリ自身の技術を使う(SimulateClick)」という記述に`pywinauto`
    の`.select()`(ネイティブAPI直接呼び出し)が合致すると判断し`# WARNING`
    付きで採用。`DelayAfter`(新規、既定300ms確認済み)は活動後の
    `time.sleep()`として生成。回帰テスト追加(`tests/test_uipath_dsl.py`
    1件・`tests/test_uipath_codegen.py`10件)、UiPath関連テスト全365件
    通過、リポジトリ全体で全1214件通過。
71. **(完了、2026-11-06)** `ui:UiElementExists`(DisplayName「Element
    Exists」)の実コード生成に新規対応(VM不使用、知見113——Tier A着手
    第4件、知見100の手法を10回目として再適用): 最初に見つけた実例が
    `ui:ElementExists`というタグ名だったが、信頼度の弱い2件(合成テスト
    データ・旧式直列化)のみで裏付けが不十分だったため再検索し、3件の
    独立した実機リポジトリで真のタグ名が`ui:UiElementExists`だと確定
    (公式ドキュメントの裏のCLR型名とも一致)。`ContinueOnError`/
    `DelayBefore`/`DelayMS`は実機3件・公式ドキュメントともに存在しない
    と確認したため捕捉対象に含めず(無い属性のでっち上げを回避)。
    「見つからなくても例外を投げず存在確認する」という挙動に`pywinauto`
    の`WindowSpecification.exists()`が概念的に一致——`Click`等より確信度
    の高いマッピングで`# WARNING`すら不要だった。回帰テスト追加
    (`tests/test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`5件)、
    UiPath関連テスト全371件通過、リポジトリ全体で全1224件通過。
72. **(完了、2026-11-06)** `ui:DatabaseConnect`/`ui:DatabaseDisconnect`/
    `ui:ExecuteQuery`/`ui:ExecuteNonQuery`の実コード生成に新規対応(VM
    不使用、知見114——Tier A項目2「Database活動」への着手第1件):
    `marcelocruzrpa/uipath-ai-skills`の`studio-ground-truth/`(実機Studio
    から自動収集済みと明記された複数パッケージのXAML参照集)で属性の
    完全な語彙を確認し、`allenlooplee/RPABook`の実例でpopulated時の
    直列化(`ProviderName="System.Data.SQLite"`等)を確認。.NET
    ADO.NETのプロバイダ名はPythonの単一ライブラリに対応しないため、
    実機確認できた`System.Data.SQLite`のみ標準ライブラリ`sqlite3`へ
    マッピング(新規依存無し)、他プロバイダは`# TODO`。`ConnectionString`
    をコード生成時に静的パースし`Data Source`を抽出。`DataTable`出力は
    `list[dict]`(`sqlite3.Row`経由)へマッピングし、実際に一時SQLite DB
    へ対して生成コードを実行して`SELECT`/`DELETE`両方の正しい動作を
    確認済み。`Parameters`は空のみ対応(populated時のプレースホルダ書式
    未確認で`# TODO`)。`BulkInsert`/`BulkUpdate`/`DatabaseTransaction`/
    `InsertDataTable`は今回スコープ外として明示的に見送り。`ui:HttpClient.
    Headers`用だった`_http_client_dict_entries`を`_xkey_dict_entries`に
    汎用化して再利用。回帰テスト追加(`tests/test_uipath_dsl.py`2件・
    `tests/test_uipath_codegen.py`22件)、UiPath関連テスト全395件通過、
    リポジトリ全体で全1256件通過。
73. **(完了、2026-11-06)** `ui:ExcelReadRange`/`ui:ExcelWriteRange`の実
    コード生成に新規対応(VM不使用、知見115——Tier A項目3「Excel
    Classicの残り」への着手第1件): 知見114の`studio-ground-truth/`リポ
    ジトリで属性の完全な語彙を確認、`HarshadRanganathan/uipath-learning`・
    `allenlooplee/RPABook`の実例でpopulated時の直列化を確認。既存の
    `ExcelApplicationScopeNode`配下の子活動として実装(`ExcelWriteCell`
    と同じ構造)。`DataTable`は`ExecuteQuery`(知見114)と同じ`list[dict]`
    表現に統一。`Range`(空文字列=シート全体のみ確認済み)・`StartingCell`
    (`"A1"`のみ確認済み、`openpyxl`の`append()`が常に末尾追記のため
    それ以外は再現手段未確認)以外は`# TODO`。実際に一時`.xlsx`ファイルへ
    対して生成コードを実行し、Sheet1→Sheet2のround-tripが完全一致する
    ことを確認済み。ネストした`InArgument`プロパティの共通パーサー
    `_in_argument_property_expr`を新設(`Click`の`_cursor_offset`から
    発想を汎用化)。回帰テスト追加(`tests/test_uipath_dsl.py`1件・
    `tests/test_uipath_codegen.py`9件)、UiPath関連テスト全405件通過、
    リポジトリ全体で全1266件通過。
74. **(完了、2026-11-06)** `ui:SendMail`(汎用SMTP送信)の実コード生成に
    新規対応(VM不使用、知見116——Tier A項目3「汎用Mail」への着手第1件):
    `studio-ground-truth/UiPath.Mail.Activities/2.8/`では
    `UseISConnection`等を含む複雑な構造だったが、`cameronmcnz/
    uipath-tutorials`の実機XAML(実際にGmail宛へ送信したチュートリアル)
    では`Server`/`Port`/`Email`/`Password`/`EnableSSL`/`SecureConnection`
    という昔からの単純なSMTP直結属性のみで構成されていると確認。
    確認できた唯一の組み合わせ(`EnableSSL="True"`・
    `SecureConnection="Auto"`、Gmailの暗黙SSL)のみ標準ライブラリ
    `smtplib.SMTP_SSL`+`email.mime.text.MIMEText`へマッピング(新規依存
    無し、`SendOutlookMail`のwin32comとは対照的にクロスプラットフォーム)。
    平文/STARTTLS・`UseOAuth`・`UseISConnection`・`Files`添付・
    `MailMessage`(Forward/Reply)・`From`/`Name`での送信者表示名
    カスタマイズはいずれも`# TODO`。`GetIMAPMailMessages`/
    `GetPOP3MailMessages`(受信系)は今回スコープ外として見送り。
    回帰テスト追加(`tests/test_uipath_dsl.py`1件・
    `tests/test_uipath_codegen.py`16件)、UiPath関連テスト全422件通過、
    リポジトリ全体で全1283件通過。
75. **(完了、2026-11-06)** 「実機XAMLに対する実際のコード生成の検証」
    という新しい調査手法を導入し、`ExcelWriteRange`の実在バグを修正、
    `CopyFile`/`BuildDataTable`/`ExcelAppendRange`を新規実装(VM不使用、
    知見117): `generate_python()`/`generate_project_from_json()`を
    GitHub上の外部実プロジェクト(`rpapub/PropulsiveForce`・
    `allenlooplee/RPABook`)に対して直接実行し、クラッシュ無く`# TODO`に
    倒れることと、実際の変換成功率を確認。密な実ワークフロー(1074行)で
    6件の`# TODO`のうち3件(`CopyFile`/`BuildDataTable`/
    `ExcelAppendRange`)を新規実装で解消。過程で`ExcelWriteRange`
    (知見115)の`append()`ベース実装が非空シートへの書き込みで
    `StartingCell`の位置を無視するバグを発見し、`Worksheet.cell()`に
    よる直接セル指定へ修正(副産物として任意の開始セルに対応可能に)。
    `ExcelReadRangeNode`/`ExcelWriteRangeNode`の`display_name`が未活用
    だった件(知見75・92〜95と同種)も`_with_scope_child_display_name`で
    修正。`AddDataRow`(DataTableスキーマのノード間追跡が必要、現行
    アーキテクチャに無い)・`BrowserScope`(別サブシステム)は明示的に
    見送り。回帰テスト追加(`tests/test_uipath_dsl.py`5件・
    `tests/test_uipath_codegen.py`20件、既存2件の修正含む)、UiPath
    関連テスト全444件通過、リポジトリ全体で全1310件通過。
76. **(完了、2026-11-06)** `uipath_expr`文法の「関数呼び出し結果への
    メンバ/メソッドアクセス連鎖」ギャップと、無関係な既存バグ(引数0個の
    関数呼び出し)を修正、`ui:ForEachRow`を既存`ForEachNode`の再利用で
    新規実装(VM不使用、知見118——知見117の手法をさらに3件の実プロジェクト
    へ継続適用): `SuneetPatil/IRCTC-tatkal-booking`の実機XAMLで
    `in_Config("x").ToString.ToLower.Equals("yes")`のようなチェーンが
    構文解析段階で丸ごと失敗すると発見——確認済みのTier1関数
    (`CStr`等)の結果への`.ToUpper()`/`.ToString().Trim()`連鎖すら失敗
    する広範なギャップだった。`postfix`文法規則+`ChainedAccess`IR
    ノードを新設して修正、レンダラーは確認済みの安全なメンバのみ対応
    (`.ToString`→`_vb_cstr()`、`.ToUpper`/`.ToLower`/`.Trim`→Python
    文字列メソッド、`.Equals(arg)`→`==`比較)。実装中に偶然、無関係の
    既存バグ(`arglist`の空引数リストが`None`プレースホルダのまま
    壊れた木になっていた)も発見・修正。`ui:ForEachRow`は`ui:ForEach`と
    直接の子要素構造が完全に同じ(`DataTable`属性名のみ違う)と判明し、
    新しいノード型を追加せず既存`ForEachNode`をそのまま再利用する薄い
    パーサーのみ追加——実際に`list[dict]`に対して生成コードを実行し
    各行が正しく束縛されることを確認済み。回帰テスト追加
    (`tests/test_uipath_expr.py`4件・`tests/test_uipath_codegen.py`
    7件・`tests/test_uipath_dsl.py`1件)、UiPath関連テスト全456件通過、
    リポジトリ全体で全1323件通過。
77. **(完了、2026-11-06)** `ui:Comment`/`ui:LogMessage`/`ui:ExcelReadCell`
    を新規実装、`ExcelWriteCellNode.cell`を`str`から`Expr`へ昇格、素の
    変数へのメンバアクセス連鎖の未発見バグも修正(VM不使用、知見119——
    知見117・118の手法を6件の実プロジェクトへ一括適用、1件は`# TODO`
    0件で完全にクリーンに変換できた): 知見118の`ChainedAccess`修正
    だけではカバーできない別のケース(`intCounter.ToString`のように
    関数呼び出しを介さない素の変数へのチェーン、`IDENT`トークンの正規
    表現がドット区切りを1トークンとして貪欲マッチするため文法の
    `postfix`規則に到達しない)を発見・修正——末尾が確認済みの安全な
    メンバ名の場合のみ分割して同じ変換を適用、`DateTime.Now`等の静的
    クラス参照は無変換のまま変えない安全な追加。`ExcelWriteCellNode.
    cell`は実機XAML(ループ内連番セル指定`"B"+intCounter.ToString`)で
    動的な実例を発見したため`Expr`へ昇格——実際に一時`.xlsx`ファイルへ
    生成コードを実行し正しいセルへ読み書きされることを確認済み。
    `ExcelReadCell`は知見115の`_in_argument_property_expr`共通パーサーが
    `OutArgument`タグでもそのまま動作することを確認。`LogMessage`は
    確認済みの`Info`/`Error`のみ`logging`モジュールへマッピング。
    `BrowserScope`/`AddQueueItem`/`GoogleVisionScope`は明示的に見送り。
    回帰テスト追加(`tests/test_uipath_dsl.py`4件・
    `tests/test_uipath_codegen.py`13件、既存2件の修正含む)、UiPath
    関連テスト全473件通過、リポジトリ全体で全1341件通過。
78. **(完了、2026-11-06)** `ui:GetOutlookMailMessages`(`SendOutlookMail`
    の受信側)を新規実装、2件が`# TODO`0件で完全にクリーンに変換できた
    (VM不使用、知見120——知見117〜119の手法を継続): 5件中4件に実務需要の
    強い信号を確認。`Filter`属性が実機で`"[importance]='normal'"`という
    実例を持つが、これはVB式の`[...]`角括弧記法ではなくOutlookのDASL/
    Jetフィルタ構文そのものだと判明(`]`で終わらないため`_parse_expr`が
    自然に`Literal`として捕捉)——`Items.Restrict()`へそのまま委譲する
    (独自の変換はでっち上げない)。`GetNamespace("MAPI").
    GetDefaultFolder(6)`(`olFolderInbox`、`SendOutlookMail`の
    `CreateItem(0)`と同じ確認手法)経由で受信箱を取得、`Top`があれば
    スライス。実在の実プロジェクト1件で、元のXAML自体に出力変数束縛先と
    `ForEach`反復先の食い違い(作成者のコピペミスと推定)があったが、
    変換元の忠実な再現として正直に同じ挙動を再現した。`Account`(別
    メールボックス)・`MailFolder`が`"Inbox"`以外・`GetAttachements`/
    `MarkAsRead`/`OnlyUnreadMessages`の`"True"`はいずれも未確認のため
    `# TODO`。`WordApplicationScope`+`ReplaceTextInDocument`
    (`python-docx`が既に依存に含まれているため実装コストは低いと見込ま
    れる)は次回へ見送り。回帰テスト追加(`tests/test_uipath_dsl.py`
    1件・`tests/test_uipath_codegen.py`10件)、UiPath関連テスト全484件
    通過、リポジトリ全体で全1354件通過。
79. **(完了、2026-11-06)** `ui:WordApplicationScope`+`ui:
    ReplaceTextInDocument`/`ui:WordReplaceText`を新規実装(VM不使用、
    知見121——知見117〜120の手法を継続、前回見送ったWord系に着手):
    `UiPath/skills`公式リポジトリの`uipath-troubleshoot`テストタスクで
    複数の実例を確認。実機で2つの異なるタグ名(`ui:ReplaceTextInDocument`
    「Replace Text in Document」/`ui:WordReplaceText`「Replace Text」)を
    発見——意味論は同じと判断し両方を同じノード型へディスパッチ。
    `Search`は`"{{Candidate}}"`(ドキュメント内の生のプレースホルダ、VB式
    ではない)と`"[TermsPlaceholder]"`(真のVB変数参照)の両方の実例が
    あると確認。`ExcelApplicationScope`(知見22・97)と同じ設計で
    `python-docx`(既に依存に含まれている)への実コード生成——
    `docx.Document()`で開き、各段落の各run単体に対する文字列置換
    イディオムへ変換、スコープ末尾で`.save()`。実際に一時`.docx`
    ファイルへ生成コードを実行し、プレースホルダがVB変数の値へ正しく
    置換されることを確認済み。検索対象が複数runに分割されている場合は
    置換されない既知の限界(`python-docx`自体の制約)を明示的に受け入れる。
    `_iter_invoke_nodes`のスコープ再帰発見リストにも追加(知見88と同種の
    見落とし防止)。回帰テスト追加(`tests/test_uipath_dsl.py`2件・
    `tests/test_uipath_codegen.py`4件)、UiPath関連テスト全490件通過、
    リポジトリ全体で全1369件通過。
80. **(完了、2026-11-06)** `ui:MultipleAssign`を新規実装(5件中5件に
    出現する最強の実務需要信号)、`Condition`の省略されないプロパティ
    要素形(`mva:VisualBasicValue`)も発見・修正(VM不使用、知見122——
    知見117〜121の手法を新しい実プロジェクト群へ継続): `MultipleAssign`
    の`.AssignOperations`配下の各`AssignOperation`は単一の`Assign`
    (知見2)と構造・意味論が完全に同じ糖衣構文と判断し、既存の
    `AssignNode`/`_generate_assign`をそのまま再利用(新しい生成ロジック
    不要)。修正後の再検証で`ui:InterruptibleDoWhile`の`Condition`が
    属性形ではなく`<X.Condition><mva:VisualBasicValue
    ExpressionText="..." /></X.Condition>`という省略されない要素形
    そのもので直列化される実例を発見——知見14の「角括弧式の正体は
    `VisualBasicValue`の省略記法」という理解の裏付けになったが、Studioが
    常に省略形を使うとは限らないと判明。属性形が無い場合のみこの要素形へ
    フォールバックする`_condition_expr`を新設し`While`/`DoWhile`へ適用。
    `InputDialog`(対話的な入力の非対話変換という設計判断が必要)・
    `New Integer() {...}`(VB.NETの明示的配列構築構文)・`LogMessage`の
    `Level`が列挙参照形になる実例は次回へ見送り。回帰テスト追加
    (`tests/test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`
    2件)、UiPath関連テスト全494件通過、リポジトリ全体で全1381件通過。

81. **(完了、2026-11-06)** `_condition_expr`フォールバックを
    `If.Condition`/`Switch.Expression`へも拡張(知見123——知見122で
    「`While`/`DoWhile`のみ確認済み、`If`/`Switch`は理論上同じ機構だが
    未確認」と明示的に保留していた範囲): `_condition_expr`自体は属性名
    引数化済みの汎用ヘルパーだったため、`_parse_if`/`_parse_switch`の
    `_attr_expr`呼び出しを`_condition_expr`に差し替えるだけで済み、新しい
    解析ロジックの追加はゼロ。`If`/`Switch`固有の実機XAMLでの直接観測は
    まだ無いが、`[...]`省略記法と`mva:VisualBasicValue`要素形がどちらも
    同一のInArgument直列化規約(知見14)に基づく以上、活動の種類に依存
    しない水平展開と判断。回帰テスト追加(`tests/test_uipath_dsl.py`
    2件)、UiPath関連テスト全496件通過、リポジトリ全体で全1385件通過。

82. **(完了、2026-11-06)** `ui:LogMessage`の`Level`列挙参照形
    (`[UiPath.Core.Activities.LogLevel.Info]`)を解決(知見124——知見122
    で発見・見送った3件の保留項目の1件): `Level`は通常`"Info"`/`"Error"`
    の生文字列属性だが、実機XAMLでは`[...]`角括弧VB式で.NET列挙の完全
    修飾名を参照する形でも直列化される実例を発見。`_parse_log_level`を
    新設し、確認済みプレフィックス`"UiPath.Core.Activities.LogLevel."`で
    始まる角括弧形からのみ末尾のメンバー名を取り出し、既存の
    `_LOG_LEVEL_METHODS`(`Info`/`Error`のみ確認済み)による絞り込みと
    `# TODO`フォールバックへそのまま委ねる——コード生成側のロジックは
    無変更。残り2件(`InputDialog`・`New Integer() {...}`)は引き続き
    見送り。回帰テスト追加(`tests/test_uipath_dsl.py`2件)、UiPath関連
    テスト全498件通過、リポジトリ全体で全1392件通過。

83. **(完了、2026-11-06)** VB.NETの明示的配列構築構文`New Integer()
    {...}`を`uipath_expr`文法に追加(知見125——知見122で発見・見送った
    残り2件のうち1件): `[New Integer() {1, 2, 3}]`が`uipath_expr`の
    `{...}`(`array_lit`)では構文解析できず`tree=None`へ倒れていた。
    要素リスト自体の意味論は既存の波括弧リテラルと完全に同じで、唯一の
    違いは前置される型名宣言——`ArrayLiteral`自体が元々要素型を保持
    しないため、型名を解析して捨てる薄いアダプタ(`_NEW`キーワード
    トークン+`new_array_lit`規則)を追加し既存の`ArrayLiteral`へ帰着
    させた(新しいノード型・コード生成ロジックは不要)。
    `uipath_codegen/render.py`は無変更。残り1件(`InputDialog`)は実機
    属性構成が未確認のため引き続き見送り。回帰テスト追加
    (`tests/test_uipath_expr.py`2件)、UiPath関連テスト全500件通過、
    リポジトリ全体で全1396件通過。

84. **(完了、2026-11-06)** 「実機XAMLに対する実際のコード生成の検証」を
    未使用の新規25リポジトリへ適用、`Split`関数を新規実装(知見126——
    知見117〜125の手法を継続): `gh api search/code`で新規25件の
    `Main.xaml`を検証、23件が例外無しで完走(残り2件はv1スコープ外の
    State Machineルート、想定通り)。`Microsoft.VisualBasic.Strings.
    Split`の実機確認済み2引数形(`Split(expr, delimiter)`)を
    `str.split(delimiter)`へ対応——`Delimiter`省略時既定値・`Limit`・
    `Compare`付きの他オーバーロードは未確認のため`# TODO`へ倒す。
    別途、知見74で「実需要が無いため見送った」としていた`row(...)`
    (VB.NETの配列/DataTable行添字と関数呼び出しの構文的曖昧性)に、
    `ForEachRow`反復変数への実需要の裏付けを発見——解消には変数スコープ
    追跡という新アーキテクチャが必要(`AddDataRow`と同種)なため設計課題
    として記録し見送り。回帰テスト追加(`tests/test_uipath_codegen.py`
    3件)、UiPath関連テスト全503件通過、リポジトリ全体で全1399件通過。

85. **(完了、2026-11-06)** 関数呼び出しを介さない素の変数への**メソッド**
    呼び出し連鎖(`mail_Category.Equals(...)`)の文法ギャップを修正、
    `Len`関数を新規実装(知見127——知見117〜126の手法を未使用の新規24
    リポジトリへ継続): 知見118(関数呼び出し結果への連鎖)・知見119
    (関数呼び出し無しのプロパティ連鎖)に続く第3のパターン——関数呼び
    出しを介さない素の変数への**メソッド**呼び出し連鎖(`IDENT`トークンの
    ドット貪欲マッチにより`mail_Category.Equals`全体が単一関数名に
    吸収される)で`NotImplementedError`が伝播していた。`_render_func_
    call`の末尾(Tier1静的メソッド名に一致しなかった場合のみ到達)に、
    知見118の`_render_chained_access`と同じアルゴリズムを再利用する
    フォールバック分岐を追加——新しい変換ロジックは追加していない。
    `Microsoft.VisualBasic.Strings.Len(Expression)`(文字列用法)を
    `len(expr)`へ対応。LINQの`OrderBy`/`ThenBy`+ラムダ式は未対応構文
    領域として`# TODO`への安全なフォールバックを確認、2件のState
    Machineルートは既存のv1スコープ外判断を再確認。回帰テスト追加
    (`tests/test_uipath_codegen.py`4件)、UiPath関連テスト全507件通過、
    リポジトリ全体で全1403件通過。

86. **(完了、2026-11-06)** 新しい実機データ源「`marcelocruzrpa/
    uipath-ai-skills`のground-truthコーパス」を発見、既存のDatabase/
    WebAPI実装の既定値(`{x:Null}`)耐性を確認(知見128、コード変更無し):
    UiPathパッケージ名・バージョンごとに504件の単体活動`.xaml`参照
    フィクスチャ(`<Activity x:Class>`直下に活動1つの最小形)を発見。
    値がほぼ全て`{x:Null}`デフォルトのため実装の根拠にはならないが、
    既存実装(`DatabaseConnect`等・`HttpClient`)が極端な既定値入力でも
    クラッシュしないことを確認。属性名が確認できた新規未実装11活動
    (`BulkInsert`/`BulkUpdate`/`InsertDataTable`/`DatabaseTransaction`/
    `SerializeJson`/`DeserializeJson`系/`ExecuteXPath`/`GetNodes`系/
    `NetHttpRequest`)を実データ待ちの実装候補として`design/
    uipath_feature_catalog.md`に記録。`UiPath.Excel/Mail/System/
    Testing/UIAutomation.Activities`(400件超)は未検証、継続価値あり。

87. **(完了・重要な発見、2026-11-06)** `UiPath/skills`公式リポジトリで
    240件のC#式言語実機プロジェクトを発見(知見129、コード変更無し):
    これまで「VB.NET固定」(Studio 2021.4.4に式言語選択UIが無いことから
    の結論)としていた前提に対する初めての実機反証。UiPath公式の
    `skills`リポジトリ`tests/tasks/uipath-troubleshoot/
    activity-packages/`配下に、活動×エラーシナリオ別に命名された240件の
    `Main.xaml`があり、サンプリングした7件全てが`expressionLanguage:
    "CSharp"`だった。直列化形式を確認: VB.NETの`[...]`角括弧省略記法
    (知見14)の代わりに`<CSharpValue>`(値)/`<CSharpReference>`(出力
    変数参照、1段余分にネスト)というC#専用のプロパティ要素形になる
    ——`_attr_expr`がマッチせず既存の保守的な`# TODO`フォールバックへ
    正しく倒れる(24件検証、クラッシュ0件、誤変換無し)。C#対応自体は
    (1)プロパティ要素形の一般解析、(2)C#式テキスト用の全く別の文法、
    (3)ワークフロー単位の言語判定という「新しい式言語バックエンドの
    追加」に相当する大規模な設計判断のため、今回は実装を見送り重要な
    設計課題として記録(`AddDataRow`・`row(...)`スコープ追跡より大きい
    スコープ)。次tickへの引き継ぎ: この240件corpus(未使用)を次回C#
    対応を検討する際の一次データ源として再利用する価値がある。

88. **(完了・重大な発見、2026-11-06)** 静的メソッド3件(`File.
    ReadAllBytes`/`Convert.ToBase64String`/`Path.
    GetFileNameWithoutExtension`)+`DataTable.Copy`を新規実装、VB.NETの
    識別子大文字小文字の揺れによる【重大】な潜在バグを発見(知見130):
    `String.IsNullOrEmpty`と同じパターンで静的メソッド3件を
    `_render_func_call`に追加、`DataTable.Copy()`(括弧省略形)は
    `_apply_chained_property`経由で`list[dict]`行コピーへ対応。
    別途、`row(...)`/`keyrow(...)`添字曖昧性(知見126)の2件目の実機
    確認も記録。**最重要**: VB.NETは識別子の大文字小文字を区別しないが
    本トランスパイラは区別するため、同一変数が異なる大文字小文字表記で
    参照されるXAML(`out_RequirementLanCur`宣言→本体では
    `Out_RequirementLanCur`参照、実機で発見)では**2つの別々のPython
    変数が静かに生成される**——`# TODO`へ保守的に倒れず、構文的に正しい
    が意味的に誤ったコードを生成するという、`AddDataRow`・`row(...)`
    より深刻な種類の問題。通常のローカル変数でも理論上同じ問題が起こり
    うる一般的な懸念のため、次に「スコープ対応のコード生成アーキテク
    チャ」を設計する際は識別子大文字小文字正規化を最優先要件とすべきと
    判断し、重要な設計課題として記録(今回は実装見送り)。回帰テスト
    追加(`tests/test_uipath_codegen.py`4件)、UiPath関連テスト全511件
    通過、リポジトリ全体で全1411件通過。

89. **(完了、2026-11-06)** `ui:InputDialog`を新規実装(知見131——知見122
    で発見・保留していた最後の1件): GitHub上で実機確認した2件
    (`cameronmcnz/uipath-tutorials`の`NumberGuesser`・`MIETDevelopers/
    112-KavyaDhar-RPA`の`UserInp`)の属性構成が完全に一致
    (`Title`/`Label`リテラル文字列・`IsPassword="False"`・`Options`
    未設定・`.Result`プロパティ要素)。`MessageBox`の「でっち上げた
    `input()`等のユーザー入力再現は行わない」という既存方針とは矛盾
    しない——`InputDialog`は「テキスト入力を求め結果を返す」活動その
    ものでPythonの`input()`が意味論上**直接対応**するため、方針が
    適用される前提(対話を模倣する推測)がそもそも当てはまらないケース
    と判断した。`Title`/`Label`は`MessageBox`の`Caption`/`Text`と同じ
    結合パターンを流用。`IsPassword="True"`・`Options`設定済みは実機
    未確認のため`# TODO`へ倒す。回帰テスト追加(`tests/
    test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`5件)、
    UiPath関連テスト全517件通過(リポジトリ全体は並行作業中の別セッ
    ションのPAD系未完了変更による無関係な失敗4件を除き健全)。

90. **(完了・重要なバグ修正、2026-11-06)** libxml2のxmlns値過剰検証で
    REFramework共通ファイルがパース不能になるバグを発見・修正(知見132):
    `RetryCurrentTransaction.xaml`(REFrameworkの標準構成ファイル、
    多数の実プロジェクトで使われる)が`xmlns:mv="clr-namespace:...,
    Version=10.0.0.0, Culture=neutral, PublicKeyToken=..."`という
    アセンブリ完全修飾名形のxmlns値をlibxml2が「valid URIではない」と
    過剰検証で拒否し、XML解析の入口で完全に失敗していた。
    `parse_workflow_file`の`etree.parse`を、このエラーメッセージ
    (`"is not a valid URI"`)に限定して`recover=True`の寛容パーサーへ
    フォールバックするよう修正——他の種類のXML構文エラーは従来通り
    伝播させる狭い修正。今後検証する実プロジェクトのうち無視できない
    割合がXML解析の入口で弾かれる状態から救われると見込まれる。回帰
    テスト追加(`tests/test_uipath_dsl.py`1件)。

91. **(完了、2026-11-06)** 文字列/配列の`.Contains`/`.Length`+
    `Directory.GetFiles`を新規実装(知見133——知見132と同じ検証バッチの
    継続): `String.Contains(value)`をPythonの`in`演算子へ対応——
    知見118/127の2つの連鎖呼び出し経路で重複していた`Equals`判定を
    `_apply_chained_call`という共通ヘルパーへ整理し、そこへ`Contains`を
    追加。`Directory.GetFiles(path)`(1引数、検索パターン省略)を
    `os.listdir`+`os.path.isfile`のリスト内包表記へ対応。`.Length`
    (配列/文字列いずれも)はPythonの`len()`に型を問わず直接対応する
    ため連鎖呼び出し・呼び出し無し連鎖の両経路に追加。回帰テスト追加
    (`tests/test_uipath_codegen.py`6件)、UiPath関連テスト全523件通過
    (リポジトリ全体は`test_pad_codegen.py`を除き全1133件通過)。

92. **(完了、2026-11-06)** `String.IsNullOrWhiteSpace`/`Path.Combine`/
    `Directory.Exists`を新規実装、`Directory.GetFiles`に2引数形を追加
    (知見134——知見132で修正したREFramework共通ファイルの効果も別
    インスタンス2件で再確認): `String.IsNullOrWhiteSpace(value)`は
    既存の`String.IsNullOrEmpty`と同じパターンで`(not (value or
    '').strip())`へ対応。`Path.Combine(path1, path2, ...)`は.NET側の
    固定オーバーロード+`params`配列版いずれも同じ連結意味論のため
    `os.path.join(*paths)`で2引数以上を対応。`Directory.Exists(path)`
    は`os.path.isdir(path)`。`Directory.GetFiles`の`searchPattern`付き
    2引数形は`glob.glob`+`os.path.isfile`フィルタで対応。`Newtonsoft.
    Json.JsonConvert.DeserializeObject(Of T)(...)`というVB.NETの
    ジェネリック型引数`(Of T)`構文は`uipath_expr`文法が全く未対応
    (新しい構文領域として記録、今回は見送り)。回帰テスト追加
    (`tests/test_uipath_codegen.py`4件)、UiPath関連テスト全527件通過、
    リポジトリ全体で全1445件通過。

93. **(完了、2026-11-06)** `ExcelWriteCellNode`に`display_name`を追加
    (知見135——知見119で「スコープを絞るため見送った」としていた既知の
    バックログ項目の後片付け): `ExcelReadCellNode`等と違い`display_
    name`フィールドが無かった——既に確認済みの実機データ(テスト
    フィクスチャ自体に`DisplayName="Write Cell"`が含まれていたが未
    検証)を元に、`types.py`へフィールド追加・`xaml_tree.py`の
    `_parse_excel_write_cell`で捕捉・`_generate_excel_application_
    scope`内の呼び出しを他のExcel活動と同じ`_with_scope_child_
    display_name`経由に変更。新しい生成ロジックは追加していない、
    ノーリスクな後片付け。回帰テスト追加(既存テストへの検証追加1件・
    `tests/test_uipath_codegen.py`1件)、UiPath関連テスト全528件通過、
    リポジトリ全体で全1446件通過。

94. **(完了・重大バグ修正、2026-11-06)** `Assign`/`MultipleAssign`の
    `.To`がC#式言語形(`<CSharpReference>`)等の未対応ネスト要素を持つ
    場合、構文的に無効なPythonコード(文字列リテラルへの代入)を生成
    していたバグを発見・修正(知見136): `generate_python()`自体は例外
    無く完走していたため`# TODO`の個数だけを見る通常検証では検出
    できず、今回`compile()`で実際にコンパイルして初めて発覚。根本原因
    は`_argument_text`が、ネスト要素前の空白のみの`.text`を無条件に
    返していたこと——「空白のみ+ネストした子要素あり」の場合に`None`
    を返すガードを追加した。同時に`_generate_assign`の別の潜在バグ
    (`node.target is None`の場合、`render_expr(None)`が例外無く
    `"None"`を返すため`None = value`という別の無効コードを生成してい
    た)も発見・修正——`target is None`を明示チェックし`# TODO`へ倒す。
    教訓として、`# TODO`の個数や例外の有無だけでは生成コードの妥当性を
    保証できないため、今後の実機検証でも`compile()`検証を一次チェック
    として併用する価値を記録した。回帰テスト追加(`tests/
    test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`1件)、
    UiPath関連テスト全530件通過、リポジトリ全体で全1454件通過。

95. **(完了・重大バグ修正の続報、2026-11-06)** `Assign`の代入先
    レンダリング失敗で`None = None`という無効なPythonコードを生成して
    いた、知見136で塞ぎ切れていなかった別経路を発見・修正(知見137):
    知見136の教訓を即座に実践し`compile()`検証を実機検証の標準手順に
    追加した結果、未使用の新規13リポジトリの検証で即座に別の経路から
    同じバグが再発していることを発見。知見136は`target is None`
    (フィールド自体が未捕捉)だけを対策していたが、`target`は有効な
    `VbExpr`として存在するがレンダリングが失敗するケース(知見74の
    `CurrentRow(0)`添字曖昧性を代入先に使う実例)は未対策だった——
    `_render_value_or_todo`が失敗時に例外無く`"None"`を返す仕様のため
    `None = None`になっていた。`_generate_assign`で`target`を
    `render_expr`に直接通し`NotImplementedError`を明示捕捉、失敗時は
    文全体を`# TODO`へ倒すよう修正(`value`側のみ失敗した場合は従来
    通り`x = None`を維持する非対称な扱いが正しい)。回帰テスト追加
    (`tests/test_uipath_codegen.py`1件)、UiPath関連テスト全531件通過、
    リポジトリ全体で全1455件通過。

96. **(完了・体系的な棚卸し、2026-11-06)** `ReadTextFile`にも知見136・
    137と同じ「代入先レンダリング失敗→無効なPythonコード」バグを発見・
    修正、他の全生成関数を体系的に棚卸しして健全性を確認(知見138):
    `uipath_codegen/__init__.py`内の`target = _render_value_or_todo
    (...)`呼び出し全箇所(約14箇所)を1つずつ確認し、直後に`if todo:
    return todo`相当のガードがあるかを棚卸しした結果、`_generate_read_
    text_file`だけがこのガードを欠いていた(他の約12箇所は全て健全)。
    `file_name`/`content`いずれかのレンダリングが失敗した場合は代入文
    自体を生成せず`# TODO`群のみを返すよう修正——他の類似関数と同じ
    確立済みの規約に合わせただけ。回帰テスト追加(`tests/
    test_uipath_codegen.py`1件)、UiPath関連テスト全532件通過、
    リポジトリ全体で全1460件通過。

97. **(完了、2026-11-06)** `ToUpperInvariant`/`ToLowerInvariant`を
    新規実装、実機検証に`compile()`を標準手順として定着(知見139——
    知見136〜138の教訓を実践): 既存の`ToUpper`/`ToLower`(知見118)と
    同じ`upper`/`lower`へ対応——Pythonの`str.upper()`/`str.lower()`は
    ロケールを参照しないため「Invariant」の意味論上の食い違いが無い。
    `_CHAINED_PROPERTY_TRANSLATIONS`辞書にキーを追加するだけで、3つの
    呼び出し経路全てに自動反映された(辞書駆動の設計の利点)。新規13
    リポジトリの検証で構文エラーは0件——知見136〜138で修正した潜在
    バグの再発は確認されなかった。回帰テスト追加(`tests/
    test_uipath_codegen.py`2件)、UiPath関連テスト全534件通過、
    リポジトリ全体で全1462件通過。

98. **(完了、2026-11-06)** `Environment.CurrentDirectory`を新規実装
    (知見140——呼び出しを伴わない静的クラスプロパティの完全修飾名
    一致という新しい対応パターン): `os.getcwd()`に直接対応。これまでの
    `ToUpper`/`Length`等は「末尾セグメントの名前だけでベースが何で
    あれ安全な汎用メンバ」だったが、`CurrentDirectory`は`Environment`
    という特定の静的クラスの文脈でのみ意味を持つため、完全修飾名
    (小文字化済み)で厳密に一致させる新しい辞書`_STATIC_PROPERTY_
    TRANSLATIONS`を導入——末尾セグメント判定より先に調べる。無関係な
    変数の同名メンバが誤変換されないことも回帰テストで確認。新規17
    リポジトリの検証で構文エラーは0件。回帰テスト追加(`tests/
    test_uipath_codegen.py`2件)、UiPath関連テスト全536件通過、
    リポジトリ全体で全1464件通過。

99. **(完了・重大バグ修正の第4の発生箇所、2026-11-06)** 複数行のVB式
    テキストが`# TODO`コメントへそのまま埋め込まれ構文的に無効な
    Pythonコードを生成していたバグを発見・修正、`display_name`
    コメント生成15箇所を共有ヘルパーへ統合(知見141——知見139で
    `compile()`を標準化した直後の本tickで早速効果が出た): VB.NETは
    丸括弧内の改行(行継続)を許すため、構文解析に失敗した式の
    テキスト自体が複数行になりうる(`JFHaataja/HAMK-miniprojekti`の
    実機XAMLで発見)。`_todo_value`・`_describe_expr_for_comment`の
    `VbExpr`分岐が、この複数行テキストを単一行のf-stringへ無防備に
    埋め込んでいたため、改行以降が`#`の付かない生のテキスト行として
    出力されタブ/スペース混在のインデントエラーになっていた——改行を
    `\n`リテラルへ退避し単一行化。ついでに`display_name`コメント生成の
    同じ無防備な埋め込みも修正し、`_with_scope_child_display_name`
    (知見84)と全く同じロジックが15個の生成関数に個別にインライン
    複製されていたことも発見——全箇所を共有ヘルパー呼び出しへ統合した
    (バグ修正と重複排除を同時に行う、知見133と同種のパターン)。回帰
    テスト追加(`tests/test_uipath_codegen.py`2件)、UiPath関連テスト
    全538件通過、リポジトリ全体で全1469件通過。

100. **(完了、2026-11-06)** `File.GetLastWriteTime`を新規実装、
     `DateTime`演算+`TimeSpan.Days`の連鎖は複数の未解決ギャップの組み
     合わせと判明し見送り(知見142): `File.GetLastWriteTime(path)`を
     `datetime.datetime.fromtimestamp(os.path.getmtime(path))`へ対応。
     同じ実機XAMLの`(Now - lastModifeRecepies).Days > 14`は(1)修飾無し
     `Now`の素通し・(2)`DateTime`減算の型推論非対応・(3)結果の`.Days`
     という3つの別々の未解決ギャップの連鎖と判明——単発の静的メソッド
     とは規模が違うため、でっち上げず3つ組の課題として見送り記録した
     (将来`DateTime`演算を本格対応する際にまとめて設計する価値あり)。
     新規24リポジトリの検証で構文エラーは0件。回帰テスト追加
     (`tests/test_uipath_codegen.py`1件)、UiPath関連テスト全539件
     通過、リポジトリ全体で全1470件通過。

101. **(完了、2026-11-06)** `Convert.ToDateTime`の診断メッセージを
     改善、`.Split(文字配列)(添字)`の多重未解決ギャップを確認(知見
     143——知見142と同種の「複数ギャップの組み合わせ」の追加確認):
     `Convert.ToDateTime(value)`はカルチャ依存の日付書式解析のため
     推測せず`# TODO`へ倒す判断自体は正しいが、Tier1未登録のため
     知見127の連鎖呼び出しフォールバックへ誤って落ち「`Convert`という
     変数への`.ToDateTime`メソッド呼び出し」と誤認した分かりにくい
     エラーになっていた——Tier1へ明示的に追加し理由を明確に示す専用の
     `# TODO`メッセージへ差し替えた(診断メッセージの品質のみの改善)。
     `StrText.Split(Environment.NewLine.ToCharArray)(0)`は`Environment.
     NewLine`・`.ToCharArray`・`.Split(文字配列)`オーバーロード・
     呼び出し後の添字アクセス(文法未対応)という4つの別々の未解決
     ギャップの連鎖と判明——規模が違うため見送り記録。回帰テスト追加
     (`tests/test_uipath_codegen.py`1件)、UiPath関連テスト全540件
     通過、リポジトリ全体で全1471件通過。

102. **(完了、2026-11-06)** `.LastIndexOf`/`.Substring`/`Regex.Replace`
     を新規実装(知見144): `.LastIndexOf(value)`を`str.rfind(value)`
     へ対応(いずれも最後の出現位置、見つからなければ`-1`)。
     `.Substring(startIndex[, length])`を`s[startIndex:]`/
     `s[startIndex:startIndex+length]`へ対応——同じ実機XAMLの
     `.LastIndexOf`と組み合わせた拡張子除去の定石パターンを両方解決
     する必要があった。`Regex.Replace(input, pattern, replacement)`を
     `re.sub(pattern, replacement, input)`へ対応(引数順の違いに注意、
     確認済みの基本正規表現構文のみ)。既存の回帰テストが`Substring`を
     「未確認メンバの例」に使っていたため別メンバへ差し替え(確認済み
     範囲が広がっていることの直接的な証拠)。新規23リポジトリの検証で
     構文エラーは0件。回帰テスト追加(`tests/test_uipath_codegen.py`
     4件)、UiPath関連テスト全544件通過、リポジトリ全体で全1490件通過
     (並行作業中の別セッションの未完了変更による無関係な失敗1件を
     除く)。

103. **(完了・重大バグ修正の第5の発生箇所、2026-11-06)** `x:Class=
     "{x:Null}"`で関数名が構文的に無効になるバグを発見・修正(知見
     145——`compile()`標準化が再び効果を出した): `bacdillon/
     UiPath-Automation`の実機XAMLで`x:Class="{x:Null}"`(Studioでクラス
     名が未設定/削除された状態と見られる)を発見、生成コードが`def
     {x:Null}(...):`という構文的に無効な関数定義になっていた。知見13の
     「`{x:Null}`は未設定として正規化する」規約が`x:Class`だけ適用
     されていなかった(`_attr()`で直接読まれ`_parse_expr`を経由しない
     唯一の例外だったため)——`parse_workflow_file`で`class_name`抽出
     直後に正規化するガードを追加し、既存の`_safe_func_name`の
     「空文字列なら既定名`workflow`」安全網を正しく機能させた。回帰
     テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
     test_uipath_codegen.py`1件)、UiPath関連テスト全546件通過、
     リポジトリ全体で全1497件通過。

104. **(完了・重要な体系的発見、2026-11-06)** チェーンメンバアクセスが
     大文字小文字を区別していたバグを発見・修正(VB.NETは大文字小文字
     不区別の言語)、`.StartsWith`/`.EndsWith`/`.IndexOf`/`.Replace`/
     `String.Concat`を新規実装(知見146): `johnowino/
     String-Manipulation-in-UIPath`の実機XAML`[strInput.length]`
     (**小文字**の`.length`)から発見——`_render_func_call`の静的
     メソッド名判定は既に`.lower()`で大文字小文字不区別だったが、
     チェーンメンバアクセス側(3つの経路、知見118・119・127)は区別
     する比較のまま取り残されていた結果、既に確認済みの`Length`メンバ
     すら小文字表記では取り逃していた——知見136〜145とは異なる種類の
     「既存の確認済み機能が動かない」バグ。`_CHAINED_PROPERTY_
     TRANSLATIONS`/`_SAFE_BARE_MEMBERS`を小文字化し3経路全てで
     `.lower()`比較するよう修正。同じ実機XAMLで`.StartsWith`/
     `.EndsWith`→`str.startswith`/`str.endswith`、`.IndexOf`→
     `str.find`(知見144の`.LastIndexOf`と対)、`.Replace`→
     `str.replace`、`String.Concat`→`&`演算子と同じ`ToString`変換
     連結も新規実装。回帰テスト追加(`tests/test_uipath_codegen.py`
     9件)、UiPath関連テスト全554件通過、リポジトリ全体で全1506件
     通過。

105. **(完了・見落とし発見、2026-11-06)** `WriteLine`(.NET Workflow
     Foundation本体の基本活動)が完全に未実装だったことを発見・実装
     (知見147): UiPath独自の活動ではなく.NET本体の標準活動
     (`Console.WriteLine`相当)のため、本セッションの複数batchで
     「unknown activity (Write Line)」という`# TODO`が繰り返し出現して
     いたにも関わらず、個々のbatchでは個別の未実装としてしか認識して
     おらず「基本的すぎる活動が丸ごと欠けている」という体系的な見落とし
     として気づくのに時間がかかっていた。`print(_vb_cstr(text))`へ直接
     対応——`MessageBox`と違い対話性を伴わないため、でっち上げの懸念が
     無い直接対応。実装後、同じ新規18リポジトリの再検証で複数ファイルの
     `# TODO`件数が大幅減少(例: 10件→4件、他数ファイルは0件に)——
     基本活動の見落としを埋める効果の大きさを実証した。新たに`new
     DriveInfo(“C”)`(VB.NETの`New`オブジェクト構築構文+曲線引用符の
     データ破損という2つの問題が重なったケース)を未解決として記録、
     見送り。回帰テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
     test_uipath_codegen.py`3件)、UiPath関連テスト全558件通過、
     リポジトリ全体で全1524件通過。

106. **(完了、2026-11-06)** `Throw`(.NET Workflow Foundation本体の
     基本活動)を新規実装、VB.NETの一般的なオブジェクト構築構文`New
     ClassName(arg)`を新規対応(知見148——知見147の直後に見つけた関連
     する見落とし): `Manyakarthik/210701152-CS19P21-ARPA`の実機XAML
     で`Throw.Exception="[New Exception(\"...\")]"`を発見——知見122で
     発見し知見125で配列構築のみ解決していた「VB.NETの`New`構文」の
     より一般的な**オブジェクト構築**形が初めて実機確認された。
     `uipath_expr`に`_NEW IDENT "(" expr ("," expr)* ")" -> new_object`
     を追加(括弧が空かどうかで知見125の配列構築規則と構文上一意に
     分岐、最低1引数を要求してLALR上の曖昧性を回避)。`render.py`に
     `_NEW_OBJECT_CLASSES`(`Exception`/`ApplicationException`)という
     確認済み許可リストを新設し、1引数=メッセージ文字列の形をPython
     組込み`Exception(message)`へ対応——未確認クラス名は明示的に
     decline。`Throw`活動自体は、知見136・137と同じ理由で`raise None`
     になりうる`_render_value_or_todo`を使わず、レンダリング失敗時は
     `raise`文自体を生成せず`# TODO`へ倒す(既知の限界として記録)。
     回帰テスト追加(`tests/test_uipath_expr.py`3件・`tests/
     test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`4件)、
     UiPath関連テスト全566件通過、リポジトリ全体で全1544件通過。

107. **(完了、2026-11-06)** `Rethrow`(`Throw`と対になる.NET Workflow
     Foundation本体の基本活動)を新規実装(知見149——知見148の直後に
     確認した体系的棚卸し): 属性を一切持たないリーフ活動で、
     Pythonの引数無し`raise`文(現在処理中の例外を再発生させる)が
     全く同じ意味論で直接対応——でっち上げの懸念も無い最も単純な
     変換の1つ。`TryCatch`の`Catch`ブロックで非常に高頻度に使われる
     はずの定石パターンにも関わらず、`Throw`と同時に見落とされていた。
     回帰テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
     test_uipath_codegen.py`2件)、UiPath関連テスト全569件通過、
     リポジトリ全体で全1547件通過。

108. **(完了、2026-11-06)** `TerminateWorkflow`(`Throw`・`Rethrow`と
     対になる.NET Workflow Foundation本体の標準活動)を新規実装
     (知見150——GitHub code searchで1100件ヒットの体系的棚卸し):
     `TryCatch`で捕捉されない即座のワークフロー全体停止という意味論を
     持ち、Python組込みの`SystemExit`(デフォルトで`except Exception:`
     に捕捉されず伝播する)が最も近い対応物。実機確認した3件は全て
     `Reason`属性を持ち、1件は`Exception`属性も同時に指定——`Reason`
     のみの場合だけ`raise SystemExit(...)`へ変換し、`Exception`も
     同時指定の場合は合成方法が未確認のため`# TODO`へ倒す(でっち
     上げるよりは安全)。回帰テスト追加(`tests/test_uipath_dsl.py`
     1件・`tests/test_uipath_codegen.py`4件)、UiPath関連テスト全574件
     通過、リポジトリ全体で全1567件通過。

109. **(完了、2026-11-06)** `ui:Delay`(UiPath独自の待機活動、GitHub
     code searchで10000件超ヒットする最頻出活動の1つ)を新規実装
     (知見151——知見147〜150の.NET WF本体活動の棚卸しに続く、UiPath
     独自活動側の棚卸しで発見): `Click`の`DelayBefore`(知見106、
     ミリ秒の数値)とは異なり、`Duration`属性は実機確認した全件で
     `[...]`角括弧の無い生の.NET TimeSpanリテラル(`"HH:MM:SS[.fff]"`)
     だった。専用の正規表現でTimeSpanリテラルを秒数に変換し
     `time.sleep(秒数)`へ変換する——`Duration`が動的なVB式の場合、
     または未確認の書式の場合は`# TODO`へ倒す(でっち上げるよりは
     安全)。回帰テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
     test_uipath_codegen.py`6件)、UiPath関連テスト全582件通過、
     リポジトリ全体で全1586件通過。

110. **(完了、2026-11-06)** `ui:SendHotkey`(GitHub code searchで1936件
     ヒットする`Click`/`TypeInto`と同じ基本UI Automation活動)を新規
     実装(知見152): 実機調査で`SpecialKey`属性が`"True"`/`"False"`/
     `{x:Null}`/省略のいずれも実例があり信頼できないと判明したため、
     `Key`の文字列値(1文字の生リテラルか確認済みの特殊キー名)だけで
     判定する設計に変更。`KeyModifiers`(`.NET`の`[Flags]`列挙型形式、
     `"Ctrl, Shift"`等の複数同時指定を実機確認)は`Ctrl`/`Alt`/`Shift`
     をpywinautoの`^`/`%`/`+`接頭辞構文へ、`Win`単独は`{VK_LWIN
     down}`...`{VK_LWIN up}`の別構文へ変換する。`Target`要素自体が
     省略された実例(フォーカス中ウィンドウへのグローバル送信と推定)
     は未対応のまま`# TODO`へ倒す。回帰テスト追加(`tests/
     test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`19件)、
     UiPath関連テスト全603件通過、リポジトリ全体で全1619件通過。

111. **(完了、2026-11-06)** `ui:AttachWindow`(GitHub code searchで
     1100件ヒットするスコープ活動)を透過的ラッパーとして新規実装
     (知見153——知見151・152で発見した「子を持つスコープ活動が軒並み
     未実装」というパターンの第1弾): `Click`/`TypeInto`/`SendHotkey`
     の子活動は`selector`を自己完結的に(絶対パスで)保持する設計の
     ため、`AttachWindow`自体は`scope_var`束縛を一切作らず「`Selector`
     を注釈コメントとして出力し子をそのまま再帰生成する」透過的な
     ラッパーとして実装した(`ExcelApplicationScope`のような
     `scope_var`束縛は不要)。`_child_node_lists`(知見88が警告する
     複数ファイル結線用の別registry)にも登録漏れ無く追加。実機XAML
     で再検証し、知見151で「`AttachWindow`の子としてネストされており
     到達不能」と記録していた`ui:Delay`呼び出し3件が連動して正しく
     `time.sleep()`として生成されることを確認した。回帰テスト追加
     (`tests/test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`
     5件)、UiPath関連テスト全609件通過、リポジトリ全体で全1635件
     通過。

112. **(完了、2026-11-06)** `ui:OpenApplication`(スコープ活動の棚卸し
     第2弾)を新規実装(知見154): `AttachWindow`(知見153)とは違い
     `ExcelApplicationScope`と同じ`ActivityAction`+`DelegateInArgument`
     のラッパーを持つが、子は`ContextTarget`を参照しない設計のため
     同様に束縛しない。`AttachWindow`との決定的な違い——実際に新しい
     プロセスを起動する活動のため、`FileName`のみ確認済みの単純な
     場合に`subprocess.Popen([...])`を生成する。`Arguments`/
     `WorkingDirectory`/`ApplicationWindow`(出力バインディング)/
     `TimeoutMS`/`ContinueOnError`はいずれも実機で非`{x:Null}`の実例を
     確認したが正確な意味論が未確認のため`# TODO`へ倒す。実機XAMLで
     再検証し、知見151(`Delay`)・152(`SendHotkey`)・153
     (`AttachWindow`)の実装がこの1件で初めて真に連動して活きることを
     確認した。回帰テスト追加(`tests/test_uipath_dsl.py`2件・`tests/
     test_uipath_codegen.py`9件)、UiPath関連テスト全620件通過、
     リポジトリ全体で全1648件通過。

113. **(完了、2026-11-06)** 基本WF版`ForEach<T>`(`ui:ForEach`とは別の
     `WF_NS`のForEach)を新規実装(知見155——知見151で発見した「子を
     持つスコープ活動が軒並み未実装」パターンの最後の1件): 構造は
     `ui:ForEach`(知見5)と完全に同じ`ActivityAction`+
     `DelegateInArgument`だが、`Body`がContent Propertyのため明示
     `.Body`ラップと暗黙形(直接子として`ActivityAction`を置く)の
     両方が実機で確認できた——実UiPathプロジェクト5件で「VB式ベース
     のループを`ui:ForEach`ではなく基本WF版で直接書く」という実在
     パターンを確認。既存の`ForEachNode`型・`_generate_for_each`を
     そのまま再利用し、`_parse_for_each`に`.Body`不在時のフォール
     バックを追加して`(WF_NS, "ForEach")`を`_DISPATCH`へ追加登録
     するだけで済んだ。調査の過程で、最初に参照した実機XAML
     (`AI-Dep/AI-Antigravity`)の`CurrentItem`属性直接形が.NET公式API
     と矛盾する非標準形(AI生成合成コードの疑い)と判明し、実装の
     根拠には採用しなかった(Microsoft公式サンプル+複数の独立した
     実プロジェクトで確認した本来の`ActivityAction`形のみを採用)。
     副産物として`ForEach.Values`の変換失敗時の挙動が`If`/`While`/
     `Switch`と同じ厳格な例外伝播モードになっている(ドキュメント上
     未確定の設計判断)ことを発見し、次の調査候補として記録した。
     回帰テスト追加(`tests/test_uipath_dsl.py`2件)、UiPath関連テスト
     全622件通過、リポジトリ全体で全1656件通過。

114. **(完了、2026-11-06)** `ForEach.Values`の失敗モード方針を確定
     (知見156——知見155が残した論点の解決、動作変更無し): `pad_codegen`
     の`IfActionRecord`の判断根拠を再確認し、「反復対象を誤って推測
     すると全ての反復が間違ったデータに対して実行される」は「分岐が
     反転する」のと同種かそれ以上の影響範囲と判断——既存の厳格モード
     (変更無し)が妥当と結論し、モジュールdocstringに`ForEach.Values`
     (と列挙漏れだった`DoWhile.Condition`)を正式に追記、
     `_generate_for_each`にも説明コメントを追加した。回帰テスト追加
     (`tests/test_uipath_codegen.py`1件、`test_if_with_unparseable_
     condition_raises`と同じ形で`NotImplementedError`伝播を固定)、
     UiPath関連テスト全623件通過、リポジトリ全体で全1657件通過。

115. **(完了、2026-11-06)** `ui:Hover`(GitHub code searchで151件
     ヒットする基本UI Automation活動)を新規実装(知見157): `Click`
     (知見9)と`Target`/`CursorPosition`の構造が全く同じで、
     `ClickType`/`MouseButton`/`KeyModifiers`が無い点のみ異なる。
     実装時にpywinautoの`move_mouse_input()`ラッパー自身の既定値
     (`coords=(0, 0)`・`absolute=True`)が「要素の中心」に移動しない
     罠を発見——`click_input()`自身の既定(`coords=(None, None)`・
     `absolute=False`)を`button='move'`で直接呼び出す実装にして
     `Click`の既定動作と同じ経路を再利用した。回帰テスト追加
     (`tests/test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`
     10件)、UiPath関連テスト全634件通過、リポジトリ全体で全1674件
     通過。

116. **(完了、2026-11-06)** `ui:TypeSecureText`(既存の`TypeIntoNode`
     を再利用)と`ui:WindowScope`(`AttachWindow`より多い1688件ヒット
     の同義活動、既存の`AttachWindowNode`を再利用)を新規実装
     (知見158): `TypeSecureText`は`TypeInto`と属性構成が完全に同じで
     `Text`属性名が`SecureText`なだけ——新しいノード型を追加せず
     既存の`TypeIntoNode`を返すパーサーを追加するだけで済んだ。
     `WindowScope`は`DisplayName`が常に`"Attach Window '...'"`になる
     `AttachWindow`の同義活動(異なるUI Automationパッケージバージョン
     の名称違いと推定)で、構造は`OpenApplication`と同じ`ActivityAction`
     +`DelegateInArgument`のラッパーを持つが意味論は`AttachWindow`と
     同じ——`AttachWindowNode`に`ApplicationWindow`等4フィールドを
     追加し、同じノード型を再利用した。実機XAML(ReFrameworkのログイン
     シーケンス)で両機能が連動して正しく動くことを確認。回帰テスト
     追加(`tests/test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`
     2件)、UiPath関連テスト全638件通過、リポジトリ全体で全1678件
     通過。

117. **(完了、2026-11-06)** `ui:GetFullText`(`GetText`とは別の活動、
     GitHub code searchで300件ヒット)を新規実装(知見159): `Target`
     構造は`GetText`と同じだが出力`Text`はプロパティ要素形で直列化
     される。公式ドキュメントが`GetText`(可視テキストのみ・最大4096
     文字)と`GetFullText`(非表示/切り詰められた部分を含むフルテキ
     スト)を明確に区別しているため、単純な再利用ではなく`GetTextNode`
     に`full_text`判別フラグ・`ignore_hidden`フィールドを追加し、
     `_generate_get_text_body`がラベルと警告文言(`GetFullText`側は
     「UiPathの実装より少ないテキストしか返らない可能性がある」ことを
     明示)を切り替える設計にした——構造は再利用するが意味論の違いは
     隠さない折衷案。副産物として`ui:BrowserScope`(「Attach
     Browser」、`AttachWindow`/`WindowScope`と同種の未実装スコープ
     活動)を発見し、次の棚卸し候補として記録した。回帰テスト追加
     (`tests/test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`
     3件)、UiPath関連テスト全642件通過、リポジトリ全体で全1682件
     通過。

118. **(完了、2026-11-06)** 知見130の【最優先・重大・未解決】識別子
     大文字小文字正規化を実装(知見160): 当初想定していた「`render.py`
     に宣言済み名前の集合を渡す仕組みを新設する」という大掛かりな
     アーキテクチャ変更ではなく、`parse_workflow_file`の入口でXML木
     そのものを正規化する軽量な前処理パスとして解決した——ワークフロー
     引数+全ての`Variable`を1回走査して正規名の表(宣言順で最初の
     表記を採用)を作り、`[...]`で囲まれたVB式(属性値・要素テキスト
     内容の両方の直列化形)の識別子トークンを正規名へ書き換える
     (文字列リテラルの内側・メンバアクセスの直後は対象外)。`render.py`
     ・`uipath_codegen/__init__.py`・既存の個別パーサー関数は一切
     変更していない。知見130が引用した実際の原因XAML(`TanMzCs2025/
     EDSAChallengeTania2025_AmazonProductSearchAndFilter`)で再検証し、
     修正前は`out_RequirementLanCur`(仮引数)と`Out_RequirementLanCur`
     (無関係なローカル変数)という2つの別々の識別子になっていたのが、
     修正後は正しく1つの識別子に揃うことを確認した。回帰テスト追加
     (`tests/test_uipath_dsl.py`3件)、UiPath関連テスト全645件通過、
     リポジトリ全体で全1685件通過。

119. **(完了、2026-11-06)** `ui:BrowserScope`(「Attach Browser」、
     `WindowScope`より多い3388件ヒット)を新規実装(知見161):
     `WindowScope`(知見158)と完全に同じ`ActivityAction`+
     `DelegateInArgument`構造・同じ意味論のため、`AttachWindowNode`を
     3回目の再利用先として同じノード型を返すだけで実装できた。
     ブラウザ固有の`Browser`(入力参照)・`UiBrowser`(出力バインド)・
     `ContinueOnError`は実機確認した5件全てで`{x:Null}`——設定時は
     `# TODO`へ倒す。`BrowserType`は単純な注釈情報のためdecline対象
     にしない。実装中に`_generate_attach_window_body`の`# TODO`文言が
     `"WindowScope"`で固定ハードコードされていた不正確さを発見し、
     `browser_type`の有無でラベルを切り替える修正も同時に入れた。
     実機XAML2件(`Browser`/`UiBrowser`設定済みの実例、全`{x:Null}`の
     単純な実例)で両方の経路を検証。回帰テスト追加(`tests/
     test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`4件)、
     UiPath関連テスト全650件通過、リポジトリ全体で全1690件通過。

120. **(完了、2026-11-06)** `ui:Activate`(GitHub code searchで604件
     ヒット)を新規実装(知見162): `Click`/`Hover`より単純
     (`CursorPosition`自体を持たない、クリックも移動も伴わずフォア
     グラウンド切り替えのみ)な基本UI Automation活動。知見128で発見
     した`UiPath/skills`公式ground-truthコーパスを初めて実際に活用
     (属性名の語彙確認)し、非デフォルト値は別途実機XAML5件で補完
     ——知見128の想定通りの使い方になった好例。pywinautoの
     `set_focus()`(両バックエンドで共通サポートされる確認済みの
     標準API)が直接対応し、`Hover`の`move_mouse_input()`既定値の罠
     (知見157)のような注意点は無い。実機XAML(`Digital-RPA/
     MRE_B2BE`)で`.set_focus()`呼び出しの生成を確認。回帰テスト追加
     (`tests/test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`
     7件)、UiPath関連テスト全658件通過、リポジトリ全体で全1698件
     通過。

121. **(完了、2026-11-06)** `Target.Selector`の`{x:Null}`正規化漏れを
     発見・修正、10箇所の重複インライン実装を共通ヘルパー`_target_
     selector`へ統合(知見163): `Click`/`Hover`/`Activate`/`TypeInto`/
     `TypeSecureText`/`SendHotkey`/`GetText`/`GetFullText`/
     `SelectItem`/`UiElementExists`の10箇所全てが`_attr()`で`Selector`
     属性を直接読んでおり、`_parse_expr`の`{x:Null}`→`None`正規化
     規約(知見13)を経由していなかった——知見162の`ui:Activate`実装
     検証で発見。知見133・141と同じ「バグ修正+重複解消を1回で」
     パターンで対応し、個別のパーサー関数自体は変更していない。
     既存テスト全1698件に退行無し、実機XAML2件で再検証。回帰テスト
     追加(`tests/test_uipath_dsl.py`1件)、UiPath関連テスト全659件
     通過、リポジトリ全体で全1699件通過。

122. **(完了、2026-11-06)** `ui:SetFocus`(`Activate`の同義の別活動)
     を新規実装(知見164): `UiPath/skills`公式ground-truthコーパスで
     `ui:Activate`と属性構成が完全に同一(`Target`+`DelayBefore`/
     `DelayMS`/`ContinueOnError`)だと確認、GitHub上68件ヒット・実機
     (`JoeIaquinto/UiPath-VidCreator`等)で`DisplayName`が`"Set
     Focus '...'"`になる同義の別活動と確認した。`_parse_activate`は
     タグ名に依存しない汎用実装のため、`_DISPATCH`に1行追加するだけ
     で済んだ——このtickで最も経済的な実装。副産物として、タグ名
     自体が`GetValue`になる`GetText`系の実例・`ui:Check`/
     `ui:Highlight`という未実装活動を発見し、次の棚卸し候補として
     記録した。回帰テスト追加(`tests/test_uipath_dsl.py`1件)、
     UiPath関連テスト全660件通過、リポジトリ全体で全1700件通過。

123. **(完了、2026-11-06)** `ui:Check`(チェックボックス操作、GitHub
     code searchで805件ヒット)を新規実装(知見165): `Action="Check"`
     /`"Uncheck"`は「指定の最終状態へ設定する」操作であり、`Click`の
     ような単純な無条件クリックでは誤動作しうる(既にチェック済みの
     状態で`"Check"`をクリックすると誤って外してしまう)——pywinauto
     のUIA`ButtonWrapper`が標準サポートする`toggle()`+`get_toggle_
     state()`を初めて活用し、現在の状態が目的の状態と異なる場合のみ
     `toggle()`する専用ヘルパー`_pywinauto_set_toggle_state`を新規
     追加した。`DelayAfter`(本調査で初めて遭遇、意味論未確認)は
     `DelayMS`と同じ理由で非既定値設定時は`# TODO`へ倒す。実機XAML
     (`miyaichi/UiLession`)で`Check`→`True`/`Uncheck`→`False`の両方
     が正しく生成されることを確認。回帰テスト追加(`tests/
     test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`10件)、
     UiPath関連テスト全671件通過、リポジトリ全体で全1711件通過。

124. **(完了、2026-11-06)** `ui:Highlight`(要素の視覚的ハイライト、
     GitHub code searchで289件ヒット)を新規実装(知見166): 純粋な
     視覚的デバッグ支援で後続のデータ/制御フローへの影響が一切無い
     ——pywinautoの`draw_outline()`は色の語彙(`red`/`green`/`blue`の
     3色のみ)が実機確認済みの`"Gold"`等をカバーできず、かつ
     `HighlightTime`後の自動消去機能も無いため、不確実な視覚的再現を
     試みるより`ui:Comment`(知見119)と同じ設計で常にコメントのみを
     生成する(`# TODO`ではなく「再現すべき実行時効果が無い」という
     意図的な最終判断)。知見165の`ui:Check`(現在の状態を見てから
     条件分岐が必要)とは対照的な新しい判断軸。実機XAML
     (`cameronmcnz/uipath-tutorials`)で`# Highlight Color=Gold
     HighlightTime='1000' — visual-only debugging aid...`が正しく
     生成されることを確認。回帰テスト追加(`tests/test_uipath_dsl.py`
     1件・`tests/test_uipath_codegen.py`3件)、UiPath関連テスト全
     675件通過、リポジトリ全体で全1715件通過。

125. **(完了、2026-11-06)** `ui:GetValue`(`ui:GetText`の裏のCLR型名
     そのものがタグ名として直列化される実例、GitHub code searchで
     1262件ヒット)を新規実装(知見167): `DisplayName`が常に`"Get
     Text '...'"`になり意味論が`GetText`そのもの(出力プロパティ名
     のみ`Text`ではなく`Value`)——`ui:ForEachRow`/`ui:TypeSecureText`/
     `ui:WindowScope`/`ui:BrowserScope`/`ui:SetFocus`に続く4回目の
     既存ノード型(`GetTextNode`、`full_text=False`のまま)再利用
     パターン。`_DISPATCH`に`_parse_get_value`を1行追加するだけで
     `types.py`・`uipath_codegen/__init__.py`は無変更。副産物として
     `ui:OpenBrowser`(`OpenApplication`と同種の未実装活動)を発見し、
     次の棚卸し候補として記録した。回帰テスト追加(`tests/
     test_uipath_dsl.py`1件)、UiPath関連テスト全676件通過、
     リポジトリ全体で全1716件通過。

126. **(完了、2026-11-06)** `ui:OpenBrowser`(GitHub code searchで
     2648件ヒット——`OpenApplication`より多い)を新規実装(知見168):
     `OpenApplication`(知見154)の`subprocess.Popen([file_name])`
     という「XAMLに明示された絶対パスをそのまま使う」経路が使えない
     (`BrowserType`別の実行ファイルパスがXAMLに現れず推測が必要に
     なる)ため、Python標準ライブラリの`webbrowser.open(url)`
     (特定のブラウザ実行ファイルパスを一切推測しない確認済みの標準
     API)を採用した——「確認済みのプロセス起動経路が無い場合は、OS
     抽象化層の標準ライブラリに頼る」という新しい判断パターン。
     `Hidden`/`NewSession`の非既定値・`Private`/`UiBrowser`/
     `CommunicationMethod`が設定されている場合は`# TODO`へ倒す。
     実機XAML(`PacktPublishing`の`Weather.xaml`)で`webbrowser.open()`
     +`# WARNING`コメントが正しく生成されることを確認。回帰テスト
     追加(`tests/test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`
     9件)、UiPath関連テスト全687件通過、リポジトリ全体で全1727件
     通過。

127. **(完了、2026-11-06)** `ui:KillProcess`(GitHub code searchで
     1514件ヒット——REFrameworkの標準サブワークフロー`KillAllProcesses.
     xaml`で多用)を新規実装(知見169): `Target`/`Selector`を一切
     持たず、`ProcessName`(`.exe`拡張子を含まない)で指定した全
     プロセスを終了する。Windows標準搭載の確認済みコマンド`taskkill
     /IM <name>.exe /F`(`subprocess.run`経由)が直接対応する——
     `OpenApplication`/`OpenBrowser`とは違う3番目のパターン(確認済み
     の標準コマンドへ直接対応する最も単純なケース)。`/T`(プロセス
     ツリー全体の終了)は付けない——過大な終了範囲をでっち上げない
     安全側の判断。`Process`/`AppliesTo`/`ContinueOnError`が設定され
     ている場合は`# TODO`へ倒す。実機XAML2件で`taskkill`呼び出しが
     正しく生成されることを確認。回帰テスト追加(`tests/
     test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`6件)、
     UiPath関連テスト全694件通過、リポジトリ全体で全1734件通過。

128. **(完了、2026-11-06)** `ui:CloseTab`(GitHub code searchで782件
     ヒット)を新規実装(知見170): `Target`/`Selector`を一切持たず、
     唯一の属性`Browser`(`UiBrowser`型変数参照)が`{x:Null}`の場合
     (ほとんどのREFramework実例)は「現在フォーカス中のタブ/
     ウィンドウを閉じる」という意味論になり、主要ブラウザ共通の標準
     キーボードショートカット`Ctrl+W`で実現できる——これは知見152の
     `ui:SendHotkey`で「`Target`省略(グローバル送信)」として未対応
     のまま残していた経路と同じもので、pywinautoの`keyboard.send_
     keys()`(モジュールレベルの対象無しグローバル送信、確認済み標準
     API)を初めて実際に実装した。`Browser`が変数参照の場合は
     (`UiBrowser`変数自体が未モデル化のため)`# TODO`へ倒す。実機XAML
     で`send_keys('^w')`の生成を確認。回帰テスト追加(`tests/
     test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`3件)、
     UiPath関連テスト全699件通過、リポジトリ全体で全1739件通過。

129. **(完了、2026-11-06)** `ui:CloseApplication`(GitHub code search
     で532件ヒット)を新規実装(知見171): `Target`+`DisplayName`/
     `ContinueOnError`のみという`Activate`(知見162)と同じ属性構成だが、
     `set_focus()`(副作用なし)とは別の`close()`(`WM_CLOSE`送信、実際
     にウィンドウを閉じる)を生成するため、専用の`CloseApplicationNode`
     とした(属性構成が同じでも副作用の意味論が違うノード型は共有
     しない判断)。実機3件で確認、1件はマッピング可能なセレクタで
     `.close()`生成を確認。回帰テスト追加(`tests/test_uipath_dsl.py`
     2件・`tests/test_uipath_codegen.py`5件)、UiPath関連テスト全704件
     通過、リポジトリ全体で全1746件通過。

130. **(完了、2026-11-06)** `ui:CloseWindow`(GitHub code searchで276件
     ヒット)を新規実装(知見172): `CloseApplication`(知見171)と同じ
     `close()`意味論だが、`Target`ラッパー無しのフラット`Selector`
     属性という「Classic」世代の属性慣習(`AttachWindow`/
     `OpenApplication`と同系統)。`_attr`は`{x:Null}`正規化を行わない
     ため、本活動で初めて専用パーサーに明示的な正規化を追加。
     `UseWindow`(既存ウィンドウ参照の再利用)は未モデル化のため
     `# TODO`へ倒す。実機5件で確認、合成テストで`.close()`生成を確認。
     `<html>`タグセレクタが未マッピングという`uipath_selector`の既存
     ギャップにも遭遇(別調査候補として記録、本件のスコープ外)。
     回帰テスト追加(`tests/test_uipath_dsl.py`2件・`tests/
     test_uipath_codegen.py`6件)、UiPath関連テスト全710件通過、
     リポジトリ全体で全1754件通過。

131. **(完了、2026-11-06)** `ui:MaximizeWindow`/`ui:MinimizeWindow`/
     `ui:RestoreWindow`を新規実装(知見173): 3タグとも属性構成が完全に
     同一(`Window`+`DisplayName`/`ContinueOnError`)なため、`method`
     フィールドで区別する`WindowStateNode`1つに統合した。`Window`が
     `{x:Null}`(省略)の場合は「現在アクティブなウィンドウ」——
     pywinautoの`active_only=True`(`GetGUIThreadInfo()`でOS全体の
     アクティブウィンドウを取得、確認済み標準API)で初めて対応した。
     `Window`が`Saved.Values(Of Window)(...)`のような変数参照の場合は
     未モデル化のため`# TODO`へ倒す。実機5件・実機XAML3件で
     `generate_python()`+`compile()`を確認。回帰テスト追加(`tests/
     test_uipath_dsl.py`3件・`tests/test_uipath_codegen.py`6件)、
     UiPath関連テスト全719件通過、リポジトリ全体で全1763件通過。

132. **(完了、2026-11-06)** `ui:GetAttribute`(GitHub code searchで
     274件ヒット)を新規実装(知見174): `Attribute`は開放的な語彙
     (UiPathのブラウザ拡張がDOM/アクセシビリティツリーから取得)で、
     pywinauto側に安全な汎用代替が無いため、`Attribute`の値を問わず
     常に`# TODO`へ倒す——知見38の`role`属性(実機`KeyError`で裏付け
     済み)と同じ「VM未検証の属性マッピングは追加しない」判断を正面
     から適用。`Attribute`名を明示した読みやすい`# TODO`を生成する
     価値のみを目的に新規実装(常にTODOへ倒れる活動でもノード型を
     モデル化する価値があると判断した初めての例)。実機XAML3件で
     `generate_python()`+`compile()`を確認。回帰テスト追加(`tests/
     test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`5件)、
     UiPath関連テスト全725件通過、リポジトリ全体で全1769件通過。

133. **(完了、2026-11-06)** `ui:RefreshBrowser`(GitHub code search
     で59件ヒット)を新規実装(知見175): `CloseTab`(知見170)と属性
     構成(`Browser`のみ)・実装経路が完全に同型。`Browser`が
     `{x:Null}`の場合は「現在のページを再読み込みする」——`CloseTab`の
     `send_keys('^w')`と同じ経路で`send_keys('{F5}')`(pywinautoの
     CODESグラマーで確認済みの特殊キー構文)を送る。`import`検出
     ロジックも既存のものを再利用でき追加不要だった。`Browser`が
     変数参照の場合は未モデル化のため`# TODO`へ倒す。実機XAML3件で
     `generate_python()`+`compile()`を確認(2件は既知の別制約で
     祖先ノードの時点でスキップ)。回帰テスト追加(`tests/
     test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`3件)、
     UiPath関連テスト全730件通過、リポジトリ全体で全1774件通過。

134. **(完了、2026-11-06)** `ui:GetPassword`(GitHub code searchで
     540件ヒット)を新規実装(知見176): `ProtectedPassword`はWindows
     DPAPI(`CryptProtectData`)で暗号化されたバイナリで、暗号化した
     Windowsユーザー・マシンの組み合わせでなければ復号できず、移植
     可能な安全な復号方法が存在しない。資格情報を扱う機微な操作でも
     あるため、`ProtectedPassword`の値自体をノード型に保持せず生成
     コードへも一切出力しない設計で、常に`# TODO`へ倒す(知見174の
     `ui:GetAttribute`とは別の理由で常にTODOへ倒れる2例目)。`Result`
     の2つの直列化形(フラット属性/`VisualBasicReference`でラップ
     されたプロパティ要素)を`_attr_expr`/`_in_argument_property_expr`
     の`or`連結という新しいパーサー合成パターンで両対応。実機XAML2件
     で`parse_activity()`+`_generate_node()`を実行し値の非漏洩を確認
     (3件目は無関係な既存バグ`NotImplementedError`に遭遇したため
     ワークフロー全体の`compile()`は見送り、別調査候補として記録)。
     回帰テスト追加(`tests/test_uipath_dsl.py`2件・`tests/
     test_uipath_codegen.py`3件)、UiPath関連テスト全735件通過、
     リポジトリ全体で全1779件通過。

135. **(完了、2026-11-06・訂正のみ、コード変更無し)** 知見176/本リスト
     項目134が「既存バグ」と記録した`render_expr`の`NotImplementedError`
     クラッシュ(`.Subject`等の未対応チェインメンバーアクセス)は、
     `render.py`モジュールdocstring・`_generate_if`のインライン
     コメントの両方に明記された**意図的な設計**(条件式コンテキストは
     でっち上げた真偽値で制御フローを誤らせるより生成全体を失敗させる
     方が安全、値コンテキストは`_render_value_or_todo`が`# TODO`へ倒す
     という文脈依存の2段構え)だと判明(知見177)。修正不要、コード
     変更無し——着手前にdocstringを確認したことで誤った「修正」を
     避けられた。

136. **(完了、2026-11-06)** `ui:LoadImage`(GitHub code searchで58件
     ヒット、OCR系活動の入力)を新規実装(知見178): `FileName`+
     `Image`+`DisplayName`のみという構成。Pillow(`PIL.Image.open()`)
     が標準でサポートする「ファイルから画像を読み込む」操作そのものに
     直接対応——`pad_codegen`で既にPillowを確認済みの依存として使って
     いるため新しい依存の追加判断は不要だった。`ReadTextFile`(知見16)
     と同じ「targetへ代入する」パターンを踏襲。実機XAML3件で
     `parse_activity()`+`_generate_node()`、`_collect_imports`への
     `import PIL.Image`検出条件追加により完全な`compile()`も確認。
     回帰テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
     test_uipath_codegen.py`4件)、UiPath関連テスト全740件通過、
     リポジトリ全体で全1784件通過。

137. **(完了、2026-11-06)** `ui:SaveImage`+`ui:TakeScreenshot`を新規
     実装(知見179): `UiPath/Community.Activities`公式REFramework
     テンプレート(`TakeScreenshot.xaml`)自身で使われていることを確認
     した高確証の活動。`SaveImage`は`Image.save()`(`LoadImage`の
     `PIL.Image.open()`と対になる標準API)で直接対応。`TakeScreenshot`
     は`Target`省略時(画面全体)は`PIL.ImageGrab.grab()`、セレクタ
     指定時はpywinautoの`capture_as_image()`で対応。`WaitBefore`
     (`DelayBefore`とは別名の未確認属性)は非`{x:Null}`時`# TODO`へ
     倒す。実機XAML3件(公式テンプレート本体を含む)で`generate_
     python()`+`compile()`を確認。回帰テスト追加(`tests/
     test_uipath_dsl.py`3件・`tests/test_uipath_codegen.py`8件)、
     UiPath関連テスト全750件通過、リポジトリ全体で全1795件通過。
     DataTable操作系活動群(`FilterDataTable`等)は`DataTable`表現の
     非統一というアーキテクチャ上の前提作業が必要なため見送り、
     調査候補として記録。

138. **(完了、2026-11-06)** `ui:GetOCRText`を新規実装(知見180):
     `OCREngine`デリゲートのタグが`ui:GoogleOCR`(UiPath公式ドキュメント
     で「Tesseract OCR」と確認済み——`DisplayName`ではなくタグ名で
     判定したことが、この歴史的な命名の罠を回避できた理由)の場合のみ、
     既存確認済み依存`pytesseract`に対応する。`Language`は`lang`引数へ
     そのまま渡せる。画像前処理属性(`Scale`/`Profile`等)が既定値から
     外れる場合、`GoogleOCR`以外のエンジン(`MicrosoftOCR`等)の場合は
     `# TODO`へ倒す。実装中、フラット文字列属性の`{x:Null}`正規化漏れ
     (知見163・172と同種)を実機確認で発見・`_attr_or_none()`ヘルパー
     追加で即修正。実機XAML3件+合成テストで`generate_python()`+
     `compile()`を確認。回帰テスト追加(`tests/test_uipath_dsl.py`3件・
     `tests/test_uipath_codegen.py`10件)、UiPath関連テスト全741件通過、
     リポジトリ全体で全1807件通過。

139. **(完了、2026-11-06)** `ui:AddDataRow`(GitHub code searchで
     2120件ヒット——`BuildDataTable`直後に続く定番パターン)を新規
     実装(知見181): 知見179で見送ったDataTable操作系の中でも、
     既存のDataTable変数の内容を読まない(単純追記のみ)ため
     `DataTable`表現の非統一に影響されない、数少ない安全な操作と
     判明。`ArrayRow`(VB配列リテラル)は`uipath_expr`の
     `ArrayLiteral`が既に`render_expr`でPythonリストへ変換する
     確立済みの経路のため新規実装は不要——`{data_table}.append(
     {array_row})`のみ。`DataRow`(既存オブジェクト参照)は未モデル化
     のため`# TODO`へ倒す。実機XAML3件で確認。回帰テスト追加
     (`tests/test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`
     5件)、UiPath関連テスト全746件通過、リポジトリ全体で全1813件
     通過。

140. **(完了、2026-11-06)** `ui:RemoveDataRow`(`AddDataRow`知見181の
     正反対)を新規実装(知見182): `RowIndex`によるインデックス削除
     (`del {data_table}[{row_index}]`)は`DataTable`表現非依存で安全。
     実装中、`RowIndex`の`Literal`値を素の文字列のままlistインデックス
     へ使うと`TypeError`になる実機バグを発見——VBの`CInt()`と同じ
     確認済みの整数変換経路(`round(_vb_cdbl(x))`、知見52・53)をコード
     生成側から直接再利用して修正。`Row`(複雑なLINQ式)は`uipath_expr`
     未対応のため安全に`# TODO`へ倒れる。実機XAML3件で確認。回帰テスト
     追加(`tests/test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`
     7件)、UiPath関連テスト全753件通過、リポジトリ全体で全1821件通過。

141. **(完了、2026-11-06)** `ui:GetRowItem`を新規実装(知見183):
     `ColumnIndex`は`isinstance(row, dict)`の実行時分岐でdict行/
     list行の両表現に対応する安全なコードを生成。`ColumnName`(実機
     6件全てが使用)は`row[column_name]`というdict行前提の直接
     アクセス——表現が食い違えば`TypeError`で即座に失敗する(知見177
     と同じ「でっち上げより失敗の方が安全」という判断)。`Column`
     (DataColumnオブジェクト参照)は未モデル化のため`# TODO`。実機
     XAML3件(1件はC#式言語プロジェクトの既知の限界で安全にTODO)+
     合成テストで確認。回帰テスト追加(`tests/test_uipath_dsl.py`1件・
     `tests/test_uipath_codegen.py`10件)、UiPath関連テスト全764件
     通過、リポジトリ全体で全1830件通過。

142. **(完了、2026-11-06)** `ui:ClearDataTable`+`ui:OutputDataTable`
     を新規実装(知見184): `ClearDataTable`は`DataTable`のみの最も
     単純な活動で、`list.clear()`が`DataTable`表現非依存で安全。
     `OutputDataTable`はUiPath公式ドキュメントで確認した「CSV形式へ
     変換」という大枠を、Python標準`csv`モジュールで近似(厳密な
     書式詳細は`# WARNING`——知見159の`GetFullText`と同じ判断パターン)
     し、`GetRowItem`(知見183)と同じ`isinstance(row, dict)`の実行時
     分岐でDataTableの両表現に対応する3つ目の実装パターン。実機XAML
     4件+合成データ3パターンの実行結果を確認。回帰テスト追加
     (`tests/test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`
     9件)、UiPath関連テスト全775件通過、リポジトリ全体で全1839件
     通過。

143. **(完了、2026-11-06)** `ui:ReadCsvFile`+`ui:WriteCsvFile`を新規
     実装(知見185、`UiPath.Excel.Activities`名前空間): `ReadCsvFile`
     は`AddHeaders`相当の属性が無く常に1行目をヘッダー扱いするため
     `csv.DictReader`が直接対応(`ExcelReadRange`のAddHeaders=True
     時・知見115と同じdict行表現)。`WriteCsvFile`は`OutputDataTable`
     (知見184)で確立した`isinstance(data_table[0], dict)`の実行時
     分岐パターンを再利用——`GetRowItem`・`OutputDataTable`・本件の
     3活動で同じ判断パターンを再利用した、本調査で最も再利用性の
     高い実装パターンとなった。実機XAML5件で確認、書込→読込の
     ラウンドトリップも手動確認。回帰テスト追加(`tests/
     test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`16件)、
     UiPath関連テスト全793件通過、リポジトリ全体で全1853件通過。

144. **(完了、2026-11-06)** `ui:InvokePowerShell`(GitHub code search
     で337件ヒット)を新規実装(知見186): `PowerShellProcess=
     "PowerShellCore"`(実機確認した全例)の場合のみ`subprocess.run
     (["pwsh", "-Command", command_text], check=True)`で対応。
     `check=True`は`ContinueOnError`の既定動作(エラー伝播)に揃える
     ための明示的な判断(知見177と同じ「失敗を伝播させる方が安全」)。
     `Parameters`/`PowerShellVariables`の空判定のため新ヘルパー
     `_dict_property_has_entries()`を追加。実機XAML3件で確認。回帰
     テスト追加(`tests/test_uipath_dsl.py`2件・`tests/
     test_uipath_codegen.py`9件)、UiPath関連テスト全804件通過、
     リポジトリ全体で全1863件通過。

145. **(完了、2026-11-06)** `ui:RetryScope`(GitHub code searchで
     3280件ヒット)を新規実装(知見187): 公式REFrameworkテンプレート
     (`SetTransactionStatus.xaml`)のTryCatch+Rethrowパターンから
     「本体が例外無しで完了するまで最大`NumberOfRetries`回まで再試行、
     全回失敗したら最後の例外を伝播」という意味論を確立。本調査で
     初めて新規実装した制御フロー系ノード型(`for`+`try/except`で
     表現、`TryCatchNode`と同じ`invoke_resolver`/`out_arg_resolver`
     伝播)。`Condition`が非空(Modern活動の値ベース条件)・
     `RetryInterval`設定時は`# TODO`。実機XAML2件(公式テンプレート
     含む)+合成データでの`exec()`実行確認(2シナリオ)。回帰テスト
     追加(`tests/test_uipath_dsl.py`2件・`tests/
     test_uipath_codegen.py`6件)、UiPath関連テスト全812件通過、
     リポジトリ全体で全1871件通過。

146. **(完了、2026-11-06)** `ui:MoveFile`+`ui:PathExists`を新規実装
     (知見188): `MoveFile`は`CopyFile`(知見117)と完全に同一の属性
     構成のため、decline判定・ディレクトリ解決ロジック・事前存在
     チェックを丸ごと再利用し`shutil.copy()`→`shutil.move()`のみ
     変更。`PathExists`は`PathType`(File/Folder)で`os.path.isfile()`/
     `isdir()`を正確に切り分ける(`os.path.exists()`のような種別を
     問わない近似はしない)。実機XAML4件で両方の分岐を確認。回帰
     テスト追加(`tests/test_uipath_dsl.py`4件・`tests/
     test_uipath_codegen.py`16件)、UiPath関連テスト全828件通過、
     リポジトリ全体で全1887件通過。

147. **(完了、2026-11-06)** `ui:DeleteFileX`+`ui:DeleteFolderX`を新規
     実装(知見189): 素朴なGitHub code search(`"ui:DeleteFile"`)は
     無印タグに見えたが、実機は全件`X`付き——`"<ui:DeleteFile "`
     (完全一致)で検索エンジン自体が0件を返すことを確認し、無印タグ
     が実在しないと正式に裏付けた(知見150と同種の部分一致の罠)。
     `DeleteFileX`は`os.remove()`、`DeleteFolderX`の`Recursive=
     "True"`は`shutil.rmtree()`・`"False"`は`os.rmdir()`(空の
     フォルダのみ)——いずれもPython標準の確認済みAPI。副産物として
     `ui:ForEachFolderX`という未調査の兄弟活動ファミリーも発見、
     調査候補に追加。実機XAML4件で確認。回帰テスト追加(`tests/
     test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`14件)、
     UiPath関連テスト全844件通過、リポジトリ全体で全1897件通過。

148. **(完了、2026-11-06)** `ui:ForEachFileX`+`ui:ForEachFolderX`を
     新規実装(知見190): 本調査で初めて遭遇した2変数デリゲート
     (`CurrentFile`/`CurrentIndex`)構造に対応する新パーサーヘルパー
     `_parse_two_arg_delegate_vars()`を追加。`CurrentFile`/
     `CurrentFolder`はパス文字列として表現、`os.walk()`/
     `os.scandir()`で再帰/非再帰の両方に対応。実機の`CurrentFile.
     FullName`使用に対応するため`render.py`に新しい`.FullName`メンバ
     変換を追加したが、`_apply_chained_property`だけでは`_SAFE_BARE_
     MEMBERS`の手前のゲートを通過できず、実装直後のテストで生成コード
     に`CurrentFile.FullName`がそのまま残り実行時`AttributeError`に
     なるバグを発見・即修正(`_SAFE_BARE_MEMBERS`に`"fullname"`を
     追加)。実機XAML1件(公式資産)+合成データでの実ファイルシステム
     走査(非再帰/再帰/フォルダ列挙の3パターン)を手動確認。回帰テスト
     追加(`tests/test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`
     9件)、UiPath関連テスト全855件通過、リポジトリ全体で全1906件
     通過。

149. **(完了、2026-11-06)** `ui:RenameFileX`+`ui:RenameFolderX`+
     `ui:CreateFile`を新規実装(知見191): ファイルシステム操作系
     活動群の最後の未実装分。`RenameFileX`/`RenameFolderX`は
     `os.rename()`(`KeepExtension="True"`時は`os.path.splitext()`で
     拡張子を保持)、`CreateFile`は`os.path.join()`+`open(path,
     "w").close()`で対応——いずれも`MoveFileNode`(知見188)と同様、
     既存の確認済みロジックへの素直な帰着で、新しいVB変換やランタイム
     落ちの発見は無かった。`CreateFile`の`Output`は`ForEachFileX`
     (知見190)の「絶対パス文字列」表現パターンを再利用。実機XAML3件
     +合成データ+実際の一時ディレクトリでの`os.rename()`実行結果を
     手動確認。回帰テスト追加(`tests/test_uipath_dsl.py`3件・
     `tests/test_uipath_codegen.py`18件)、UiPath関連テスト全848件
     通過、リポジトリ全体で全1924件通過。

150. **(完了、2026-11-06)** `ui:SelectFile`を新規実装(知見192):
     ネイティブOSファイル選択ダイアログ。`GetPassword`(知見176)・
     `GetAttribute`(知見174)と同じ「常にTODOへ倒れる活動でも型を
     モデル化する価値がある」判断の3例目——headless実行環境で人間の
     ダイアログ操作に代わって応答する安全な方法が無いため、`Filter`/
     出力の有無を問わず常に`# TODO`へ倒す。実機XAML2件
     (`GSA/RPA-OSS`・`lezwon/uipath_deoldify`)+合成データで確認。
     回帰テスト追加(`tests/test_uipath_dsl.py`1件・
     `tests/test_uipath_codegen.py`3件)、UiPath関連テスト全852件
     通過、リポジトリ全体で全1928件通過。

151. **(完了・調査のみ、コード変更無し、2026-11-06)** PDF活動ファミリー
     を調査(知見193): `ui:ReadPDFText`(`FileName`+`Range`(`"All"`/
     単一ページ番号/ハイフン範囲の3形式)+`Text`+`PreserveFormatting`)
     自体は`ui:`名前空間だが、同パッケージの`GetPDFPageCount`/
     `JoinPDF`/`ExtractPDFPageRange`/`ManagePDFPassword`等は
     `clr-namespace:UiPath.PDF.Activities.PDF;assembly=UiPath.PDF.
     Activities`という、本調査で初めて遭遇した非`http://schemas.
     uipath.com/...`形の名前空間を使うことを発見——既存の
     `(namespace, tag)`ディスパッチ機構はこの形式でも構造的には
     そのまま使える(アーキテクチャ上の障害ではない)ことを確認した。
     サードパーティ製の同名タグ`apac:ReadPDFText`
     (`ArenaRobotics.PDF.Activities`)との混同回避も確認。実装は
     見送った。

152. **(完了・調査のみ、コード変更無し、2026-11-06)** `ui:AnchorBase`
     を調査(知見194): `AnchorPosition`+単一子活動の`AnchorProvider`+
     1変数`ActivityAction<ui:Anchor>`の`Action`という構造自体は確認
     できたが、アンカー相対のUI要素探索という本質的な機構がXAMLの
     `Selector`文字列に一切表現されておらず、静的な`generate_python()`
     で安全に模倣できる情報が原理的に存在しないという構造的な壁を
     発見。`GetPassword`/`GetAttribute`/`SelectFile`と同じ「常に
     TODOへ倒れる」活動だが、モデル化する動機(decline文の文脈情報)が
     構造の複雑さに対して薄いと判断し、実装は見送った。

153. **(完了・調査のみ、コード変更無し、2026-11-06)** DataTable操作
     活動ファミリーを再調査(知見195): 知見179の一括保留判断を見直し、
     ground-truthコーパスから新規3活動(`JoinDataTables`/
     `LookupDataTable`/`GenerateDataTable`)を発見。難易度を再評価し、
     `LookupDataTable`(単一セル値+行インデックスの出力のみ)・
     `GenerateDataTable`(新規構築のため出力表現を自分で選べる)・
     `RemoveDataColumn`/`AddDataColumn`(スキーマ変更のみ)を次の
     実装候補、`SortDataTable`/`FilterDataTable`/`JoinDataTables`を
     依然保留と整理した。`SortDataTable`で実機の属性名version skew
     (`SortOrder`→`Order`、値`"Decending"`の誤字)も発見。
     `design/uipath_feature_catalog.md`のDataTableスキーマ解決パス節に
     追記。実装は見送った。

154. **(完了、2026-11-06)** `ui:LookupDataTable`を新規実装(知見196):
     知見195で最有望と評価したDataTable操作系の候補。`DataTable`+
     `LookupColumnName`+`LookupValue`+`TargetColumnName`→`CellValue`+
     `RowIndex`(見つからない場合`-1`、公式ドキュメントで確認)という
     構成で、`row[column_name]`という名前ベースアクセス(知見183の
     `GetRowItem`と同じ)で対応——単一セル値+行インデックスのみを
     返す構造のため、知見179のDataTable表現非統一性問題の影響を
     受けないことを実装を通じて実証した。`LookupColumnIndex`/
     `TargetColumnIndex`/`LookupDataColumn`/`TargetDataColumn`は実機
     未確認のため常にTODOへ倒す。実機XAML1件+合成データ+実際のPython
     実行(一致あり/無しの両方)で確認。回帰テスト追加(`tests/
     test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`8件)、
     UiPath関連テスト全861件通過、リポジトリ全体で全1943件通過。

155. **(完了、2026-11-06)** `ui:GenerateDataTable`を新規実装(知見197):
     知見195で2番目に有望と評価したDataTable操作系の候補。
     ground-truthコーパスに無かった`CSVParsing`/`UseColumnHeader`/
     `AutoDetectTypes`属性を実機で発見(知見128の限界を裏付け)。
     `CSVParsing="True"`は`csv.DictReader`、`"False"`は`str.split()`
     で対応し、いずれも`UseColumnHeader="True"`前提のdict行表現に
     統一——`LookupDataTable`(知見196)と同じ理由(新規構築のため
     出力表現を自分で選べる)でDataTable表現非統一性問題を回避した。
     固定幅モード(`Positions`/`ColumnSizes`)・`AutoDetectTypes=True`・
     複数文字`ColumnSeparators`・非デフォルト`NewLineSeparator`は常に
     TODOへ倒す。実機XAML2件+合成データ+実際のPython実行(両分岐)で
     確認。回帰テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
     test_uipath_codegen.py`11件)、UiPath関連テスト全872件通過、
     リポジトリ全体で全1954件通過。

156. **(完了、2026-11-06)** `ui:AddDataColumn`+`ui:RemoveDataColumn`を
     新規実装(知見198): 知見195で3番目に有望と評価したDataTable操作
     系の候補。知見183の`isinstance(row, dict)`判定を初めて「既存の
     全行への書き込み」という文脈で使用——dict行の場合のみ列を追加/
     削除し、list行表現では意図的に何もしない(`# WARNING`で明記)。
     `AutoIncrement=True`/`Unique=True`/`AllowDBNull=False`は常に
     TODOへ倒し、`MaxLength`は列追加操作自体に影響しないため無視。
     実機XAML(両属性バリエーション)+合成データ+`exec()`経由の実際の
     関数呼び出しでdict行の変更/list行の不変を確認。回帰テスト追加
     (`tests/test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`
     15件)、UiPath関連テスト全887件通過、リポジトリ全体で全1969件
     通過。

157. **(完了、2026-11-06)** `ui:ReadPDFText`を新規実装(知見199):
     知見193で調査したPDF活動ファミリーの中核。`pypdf.PdfReader(...).
     pages[i].extract_text()`(`pyproject.toml`で既に確認済みの依存
     ——本リポジトリのPAD側`pad_action_lib/pdf_actions.py`で既に
     実戦投入済みの同じライブラリ)が直接対応する。単一ページ番号の
     1始まり規約はPAD側の既存確認済み変換(`page_number - 1`)から
     合理的に推論した(UiPath Studio実機での独立確認はできていない
     ことを明記)。`Range`の"All"/数値判定はコード生成時でなく実行時
     の`if`文で行うため、静的`Literal`/動的`VbExpr`のどちらでも同じ
     ロジックで対応——ハイフン範囲(`ExtractPDFPageRange`専用、
     `ReadPDFText`自身では未確認)は静的リテラルの場合のみTODOへ倒す。
     合成データ3パターン+実際に生成した2ページPDFでの実行確認。
     回帰テスト追加(`tests/test_uipath_dsl.py`2件・`tests/
     test_uipath_codegen.py`8件)、UiPath関連テスト全897件通過、
     リポジトリ全体で全1979件通過。

158. **(完了、2026-11-06)** `UiPath.PDF.Activities.PDF`名前空間基盤を
     追加し`GetPDFPageCount`+`ExtractPDFPageRange`を新規実装(知見200):
     知見193で発見した非`http://schemas.uipath.com/...`形の名前空間
     (`PDF_NS`定数)を実際に解禁——既存の`(namespace, tag)`ディスパッチ
     機構がそのまま使えることを実装で確認した。`GetPDFPageCount`は
     `len(pypdf.PdfReader(...).pages)`、`ExtractPDFPageRange`は確認
     済みの`"N-M"`ハイフン範囲形式のみ対応し`pypdf.PdfWriter`で新規
     PDFを書き出す——PAD側`ExtractPagesToNewPDF`のカンマ区切り複数
     範囲文法は独立確認できていないため安易に輸入しなかった。残り
     4活動(`JoinPDF`/`ManagePDFPassword`/`ExportPDFPageAsImage`/
     `ExtractImagesFromPDF`)は実機確認が手薄なため見送り、次候補
     として残す。合成データ+実際に生成した10ページPDFでの実行確認
     (ページ数取得・3-5ページ範囲抽出)。回帰テスト追加(`tests/
     test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`11件)、
     UiPath関連テスト全908件通過。

159. **(完了、2026-11-06)** `JoinPDF`を新規実装(知見201): 知見200で
     見送った`upap:`名前空間の残り活動のうち1件。知見195・200で
     「`FileList`のVB配列リテラル構文(`[{"a.pdf","b.pdf"}]`)が
     `uipath_expr`で解釈できるか未確認」としていた懸念を検証した
     結果、`uipath_expr`は既に`ArrayLiteral`ASTノードを持ち
     `render_expr`も既にPythonの`list`リテラルへの変換に対応済み
     だったと判明——新しいVB構文対応は不要だった。`pypdf.PdfWriter`
     (`pad_action_lib/pdf_actions.py`の`merge_pdf_files()`と同じ
     `writer.append(reader)`イディオム)で対応。実機XAML+実際に
     生成した2ページ+3ページのPDF結合で5ページになることを確認。
     回帰テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
     test_uipath_codegen.py`3件)、UiPath関連テスト全912件通過。

160. **(完了、2026-11-06)** `ManagePDFPassword`を新規実装(知見202):
     知見200で見送った`upap:`名前空間の残り活動のうち1件。
     ground-truthは`FileName`+`OutputFileName`のみだが実機3件で
     `NewUserPassword`/`NewOwnerPassword`(いずれも単独使用)を確認
     (知見197の`GenerateDataTable`と同じground-truthの限界)。
     `pypdf`本体のAPI(`PdfWriter.encrypt(user_password,
     owner_password=...)`)を直接使う初めての活動——本リポジトリの
     PAD側に暗号化の既存イディオムは無い。`NewOwnerPassword`のみ
     設定時は`user_password=""`を渡す(対話的に確認済み、owner-only
     保護として妥当)。`OldUserPassword`/`OldOwnerPassword`は実機
     未確認のため常にTODOへ倒す。実機XAML2件+実際に生成したPDFでの
     暗号化・復号確認。回帰テスト追加(`tests/test_uipath_dsl.py`
     2件・`tests/test_uipath_codegen.py`6件)、UiPath関連テスト
     全920件通過。

161. **(完了・アーキテクチャ刷新、2026-11-06)** 「スコープ対応のコード
     生成アーキテクチャ」第1段を新設し、知見130が最優先と記録していた
     VB.NET識別子の大文字小文字正規化を実装(知見203): ユーザー指示
     (「アーキテクチャ刷新、設計をやりましょう」)を受けて着手。
     `render_expr`/`_render_node`の呼び出し規約を変えずに済むよう、
     `contextvars.ContextVar`によるアンビエントな`ScopeInfo`
     (`uipath_codegen/render.py`の`use_scope()`)を採用——明示的な
     パラメータスレッディング(既存の`invoke_resolver`/
     `out_arg_resolver`と同じ手法)だと150件超の呼び出し箇所に影響する
     ため回避した。`ScopeInfo`は`_build_scope_info()`(`uipath_codegen/
     __init__.py`)がワークフロー木全体を再帰的に歩いて構築する——
     `Node`がUnion型エイリアス(実クラスではない)なので、個々のコン
     テナ型を手で列挙せず「任意のdataclassのフィールドを再帰的に辿る」
     汎用走査(`_walk_scope_sources`、`Flowchart`のグラフ循環は
     `id()`ベースの`visited`集合で防止)にした。知見130の実機バグ
     シナリオ(`out_RequirementLanCur`宣言→`Out_RequirementLanCur`
     参照)を合成XMLで再現し修正を確認。`ScopeInfo`の`data_row_vars`/
     `data_table_columns`フィールドは構築済みだが未消費——次段の
     `row(...)`添字解消(知見126)・`AddDataRow`のDataTableスキーマ
     解決(知見117)に向けた土台として用意した。回帰テスト追加
     (`tests/test_uipath_codegen.py`5件)、UiPath関連テスト全924件
     通過、リポジトリ全体で全2010件通過。

162. **(完了・アーキテクチャ刷新第2段、2026-11-06)** 「スコープ対応の
     コード生成アーキテクチャ」第2段——知見126が発見・保留していた
     `row(...)`/`keyrow(...)`添字の曖昧性を解消(知見204): 知見203で
     構築済みだが未消費だった`ScopeInfo.data_row_vars`
     (`ForEachNode.type_arguments == "sd:DataRow"`の反復変数)を
     `render.py`の`_render_func_call`で実際に使う——1引数呼び出しの
     識別子が`data_row_vars`に含まれる場合のみ`row[列名]`(知見183の
     `GetRowItem.ColumnName`と同じdict行前提の直接アクセス)へ変換。
     既存のTier1確認済み関数名判定が常に優先され、`data_row_vars`に
     含まれない識別子は従来通り`# TODO`へ倒れる。`parse_workflow_file`
     +`generate_python`でのエンドツーエンド確認(`ui:ForEachRow`+
     `row("E-Mail")`→`# TODO`無しで正しいコード生成)。回帰テスト
     追加(`tests/test_uipath_codegen.py`3件)、UiPath関連テスト
     全927件通過、リポジトリ全体で全2013件通過。`data_table_columns`
     (知見117向け)は依然未消費のまま、次段の候補。

163. **(完了・アーキテクチャ刷新第3段・実在バグ修正、2026-11-06)**
     「スコープ対応のコード生成アーキテクチャ」第3段——`ScopeInfo.
     data_table_columns`を初めて消費し、知見117が当初警告していた
     リスクが実際に発生していたことを確認・修正(知見205):
     `AddDataRow`(知見181)が`ArrayRow`を`list.append()`する実装で、
     `BuildDataTable`→`AddDataRow`→`LookupDataTable`(知見196)という
     定番パターンを実際に実行すると`TypeError: list indices must be
     integers or slices, not str`で実行時に落ちる実在のバグを発見した
     ——`LookupDataTable`等のdict行前提の直接アクセスと組み合わせると
     壊れるという、知見117の当初の警告がそのまま現実になっていた。
     `ScopeInfo.data_table_columns`で対象`DataTable`の列名が確認
     できる場合のみ`dict(zip(columns, array_row))`へ変換して追加する
     よう修正——列名が分からない場合は従来通りlist行のまま(安全側の
     フォールバック、後退無し)。式のレンダリングを介さず`ScopeInfo`
     を直接読むための新しい公開アクセサ`render.get_active_scope()`を
     追加。実際に修正前後のクラッシュ有無+修正後の正しい値(行
     インデックス0・セル値30)を対話的に確認。回帰テスト追加
     (`tests/test_uipath_codegen.py`2件、うち1件は`exec()`経由の
     統合テスト)、UiPath関連テスト全929件通過、リポジトリ全体で
     全2015件通過。知見117・126・130が記録した3件の設計課題全てに
     対応する「スコープ対応のコード生成アーキテクチャ」がこれで
     完成した。

164. **(完了、2026-11-10)** `ui:SortDataTable`を新規実装(知見206)——
     知見195で保留した`FilterDataTable`/`SortDataTable`/
     `JoinDataTables`3件のうち、知見203のScopeInfoアーキテクチャが
     整ったことで解消できる条件が揃った`SortDataTable`に着手した。
     `ColumnName`指定+対象`DataTable`が`BuildDataTable`由来で列
     スキーマが確認できる場合のみ`sorted(DataTable, key=lambda row:
     row[ColumnName], reverse=...)`を生成、`ColumnIndex`/`DataColumn`
     (実機で非`{x:Null}`の実例なし)・スコープ情報に登録が無い場合は
     `# TODO`へ倒す。実機2件で`SortOrder`→`Order`という別名+
     `"Decending"`誤字値(知見195で発見)を再確認し、新たに両属性が
     同時に直列化されるケースも発見した——`SortOrder`優先・`Order`
     フォールバックで両方吸収する。回帰テスト追加(`tests/
     test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`4件)、
     UiPath関連テスト全935件通過、リポジトリ全体で全2021件通過。
     残る`FilterDataTable`/`JoinDataTables`は未着手、次の候補。

165. **(完了、2026-11-10)** `ui:FilterDataTable`を新規実装(知見207)
     ——知見195で保留した3件のうち2件目。知見206と同じ`ScopeInfo.
     data_table_columns`を要求し、`Filters`条件(`BooleanOperator=
     "And"`+`Operator`∈{EQ,GTE,EMPTY}、複数条件はAND結合)のみに対応、
     `SelectColumns`(列の投影)は未対応のまま`# TODO`。実機3件で新しい
     未確認属性`FilterRowsMode`(`"Keep"`/`"Remove"`)を発見し、
     `Column`が列名(`x:String`)/列インデックス(`x:Int32`)の2通りの
     型を持つことも確認——列インデックスは静的に既知の列リストへの
     インデックスとして解決し動的な式にも対応する。実機相当の構成を
     `exec()`経由で実際に実行して正しさを確認。回帰テスト追加
     (`tests/test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`
     5件)、UiPath関連テスト全942件通過、リポジトリ全体で全2028件
     通過。残る`JoinDataTables`は未着手、次の候補。

166. **(完了、2026-11-10)** `ui:JoinDataTables`を新規実装(知見208)
     ——知見195で保留した3件のうち最後の1件、これで3件全て解消した。
     `JoinType="Inner"`(実機確認済みの唯一の値、`"Left"`/`"Full"`は
     公式ドキュメントに記載はあるが実機未確認のため`# TODO`)+
     `Operator="EQ"`(実機確認済みの唯一の値)+知見206/207と同じ
     `ScopeInfo.data_table_columns`を両方のDataTableに要求。公式
     ドキュメント(`docs.uipath.com/activities/other/latest/workflow/
     join-data-tables`)で出力列の重複名解決規則(`DataTable2`側が
     `DataTable1`と同名なら`_1`→`_2`...連番サフィックス)を確認し、
     両テーブルの列リストが静的に既知なことを利用してコード生成時に
     この解決を計算・結果をリテラル埋め込みする設計で実装(実行時の
     解決ロジック不要)。実機2件相当の「蔵書とユーザーを共通のID列で
     結合」構成(両テーブルにID列があり重複解決が必須)を`exec()`経由
     で実際に実行して確認。回帰テスト追加(`tests/test_uipath_dsl.py`
     1件・`tests/test_uipath_codegen.py`3件)、UiPath関連テスト全946
     件通過、リポジトリ全体で全2032件通過。知見195・179が記録していた
     DataTable操作ファミリーの保留3件がこれで全て解消した。

167. **(完了、2026-11-10)** 「オプション依存プラグイン」の仕組みを
     新設し`ui:ExportPDFPageAsImage`を新規実装(知見209)——知見193で
     「実機確証が薄い」として保留していたが、GitHub再調査で実機2件の
     確証を得た。実装にはPDFページラスタライズ用の新規サードパーティ
     依存(`pypdf`はテキスト抽出のみで画像描画不可)が必要になった
     ——これまでの全活動(知見196-208)が既存の確認済み依存だけで
     済んでいたのに対し、初めてのケース。ユーザーと相談した結果、
     本体`dependencies`に追加せず、`pyproject.toml`の
     `[project.optional-dependencies]`に`pdf-render = ["pymupdf>=
     1.24.0"]`という「プラグイン」グループを新設する方針にした。
     重要な設計判断: トランスパイラ本体は生成コードが参照する
     ライブラリを一切importする必要が無い(既存の`_collect_imports`
     が生成コード本文の文字列パターンを検出してimport文を注入する
     既存機構——`pypdf`と全く同じ設計をそのまま延長)、コード生成
     自体に新しい実行時依存は不要。テスト用に`dev`依存グループにも
     `pymupdf`を追加(`reportlab`と同じ「テスト専用」の位置付け)、
     該当統合テストは`pytest.importorskip("pymupdf")`で未インストール
     環境では自動skipする設計にした。`pymupdf.open(FileName)
     [PageNumber - 1].get_pixmap(dpi=ImageDpi).save(OutputFileName)`
     (`get_pixmap(dpi=...)`はPyMuPDF 1.19.2以降の公式API)で実装、
     `import fitz`(非推奨)ではなく`import pymupdf`形を使う。実機
     相当の構成を`exec()`経由で実際に実行して確認。回帰テスト追加
     (`tests/test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`
     3件)、UiPath関連テスト全951件通過、リポジトリ全体で全2037件
     通過。`ExtractImagesFromPDF`(出力ファイル命名規則が未確認)は
     未着手のまま、次の候補。

168. **(完了、2026-11-10)** `ui:ExtractImagesFromPDF`を新規実装
     (知見210)——知見209の`pdf-render`プラグイン(`pymupdf`)を
     そのまま再利用。PyMuPDF公式レシピ(`Page.get_images()`+
     `Document.extract_image(xref)`)が直接対応する。調査中に
     GitHub上で同名だが無関係な第三者製活動(ArenaRobotics社の
     `apac:ExtractImagesFromPDF`、属性名も`Filename`/`OutputFolder`/
     数値enumの`ImageExtension`と完全に別物)を発見し、UiPath自身の
     `upap:ExtractImagesFromPDF`とは明確に区別した——知見193が既に
     警告していた「タグ名だけ同じ無関係な別活動」混同リスクの実例。
     `ImageExtension`(UiPath版、文字列ドロップダウン)は実機で非
     `{x:Null}`の実例が無いため設定時は`# TODO`。出力ファイル名の
     命名規則は公式ドキュメント・実機のいずれにも記載が無く未確定
     のため、本トランスパイラ独自の選択(PyMuPDF公式レシピの
     `img-{xref}.{ext}`形式)を採用し、生成コードにその旨のコメントを
     残した——UiPath自身の内部命名を再現したものではないと明示。
     実機相当の構成(埋め込み画像付きPDF)を`exec()`経由で実際に実行
     して確認。回帰テスト追加(`tests/test_uipath_dsl.py`1件・
     `tests/test_uipath_codegen.py`4件)、UiPath関連テスト全956件
     通過、リポジトリ全体で全2042件通過。これで知見193が発見した
     `upap:`名前空間のPDF活動ファミリー7件全てに着手済みとなった。

169. **(完了・調査のみ、コード変更無し、2026-11-10)** 新規活動候補を
     発掘する調査(知見211): 知見128・179と同じGitHub code search
     ヒット数調査の手法で、Orchestratorキュー/トランザクション/
     アセット系活動群(`AddQueueItem`等、数百〜数千件ヒット)を発見。
     `ElementExists`(2412件)は既存実装済み`UiElementExists`の表示名
     への偽陽性ヒットと判明。`AddQueueItem`/`GetTransactionItem`/
     `SetTransactionStatus`等は、Orchestrator接続先URL・認証情報が
     XAML自体に一切現れず(ロボット実行環境側から実行時に注入される、
     公式ドキュメントで確認)、知見194の`AnchorBase`と同種の構造的な
     壁に当たると判明——ただし`AnchorBase`と違い「常に実装を見送る」
     対象ではなく、生成コードへの接続情報受け渡し方式(環境変数/
     追加関数引数等)という新しい設計判断が必要なケース、知見209の
     依存追加相談と同種かそれ以上にユーザーとの事前相談が必要と判断
     し、実装は見送った。

170. **(完了、2026-11-10)** `ui:WriteTextFile`を新規実装(知見212)
     ——`ReadTextFile`(知見16)の対になる書き込み側。GitHub code
     search再調査でOrchestrator接続不要な候補に絞り、`WriteTextFile`
     (1980件ヒット、`IsMatch`の2404件に次ぐ高さ)に着手した。
     ground-truthに`Encoding`属性自体が存在しない(`ReadTextFile`/
     `AppendLine`とは異なる)ことを発見、実機3件で`File`/`Output`が
     常に`{x:Null}`・`FileName`+`Text`のみが実際に使われることを確認
     ——`File`/`Output`は未モデル化のまま`# TODO`。`Encoding`が無い
     ため`ReadTextFile`(知見108)の既存判断(round-trip確認済みの
     `"utf-8"`固定)を踏襲、`Text`は`SetToClipboard`(知見46)と同じ
     `_vb_cstr()`変換を適用。実機相当の構成(非ASCII文字含む)を
     `exec()`経由で実際に書き込み・読み戻しまで確認。回帰テスト追加
     (`tests/test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`
     3件)、UiPath関連テスト全960件通過、リポジトリ全体で全2046件
     通過。次の候補`IsMatch`(2404件ヒット)を記録。

171. **(完了、2026-11-10)** `ui:IsMatch`を新規実装(知見213)——
     調査の過程で、素朴な`IsMatch extension:xaml`検索は一般的な
     WPF/XAMLアプリとの大量の偽陽性を含むと判明(`.xaml`拡張子は
     UiPath専用ではない)、`"ui:IsMatch"`タグ名限定で再検索しUiPath
     関連リポジトリのみに絞り込んだ。実機2件で`Input`+`Pattern`+
     `RegexOption`+`Result`のみの構成を確認、`BuilderPattern`/
     `Model`/`IsBuilderTabModified`(正規表現ビルダーウィザードのUI
     状態メタデータ)は無視。`RegexOption`は実機確認済みの
     `"IgnoreCase"`/`"IgnoreCase, Compiled"`の2値のみ対応
     (`Compiled`は無視、他フラグは`# TODO`)、`re.search()`
     (`.NET Regex.IsMatch`は先頭固定ではなく任意位置マッチ)が直接
     対応する——知見144の`Regex.Replace`→`re.sub`と同じ「.NET/Python
     正規表現構文は十分に互換」の判断を継承。実機相当の構成を
     `exec()`経由で実際に実行して正しさを確認。回帰テスト追加
     (`tests/test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`
     3件)、UiPath関連テスト全964件通過、リポジトリ全体で全2050件
     通過。

172. **(完了、2026-11-10)** `ui:RemoveDuplicateRows`を新規実装
     (知見214)——知見213のタグ名限定GitHub検索手法
     (`"ui:ActivityName"`)を次候補リスト全件に適用して再調査、最も
     ヒット数が高かった`RemoveDuplicateRows`(93件)に着手した。
     ground-truth+実機2件で`DataTable`+`OutputDataTable`のみの
     単純な構成を確認(列選択等のオプション無し)。知見206-208と同じ
     `ScopeInfo.data_table_columns`アーキテクチャをDataTable操作系
     5件目として再利用——対象`DataTable`がdict行と確認できる場合
     のみ、各行の`dict.values()`をキーに全列完全一致の重複行を除去、
     最初に出現した行を残す。実機相当の構成を`exec()`経由で実際に
     実行して正しさを確認。回帰テスト追加(`tests/test_uipath_dsl.py`
     1件・`tests/test_uipath_codegen.py`3件)、UiPath関連テスト全968
     件通過、リポジトリ全体で全2054件通過。残る候補
     `GetEnvironmentVariable`(55件)等を次の候補として記録。

173. **(完了、2026-11-10)** `ui:GetEnvironmentVariable`を新規実装
     (知見215)——公式ドキュメントで「`System.Environment`既知
     プロパティ名(`MachineName`等)を優先しOS環境変数にフォールバック
     する」解決順序を発見した。実機確認済みの`MachineName`→
     `platform.node()`・`UserName`→`getpass.getuser()`のみ対応、
     `OSVersion`(.NETの正確な書式を再現する標準対応が無い)は
     `# TODO`。それ以外(`TEMP`等)は実際のOS環境変数名として
     `os.environ.get()`で解決——Windows固有のUser-levelレジストリ
     永続化までは再現しない(知見108の`ReadTextFile`と同種の判断)。
     `Variable`が静的リテラルでない場合は2経路のどちらか事前判断
     できないため`# TODO`。実機相当の構成を`exec()`経由で実際に
     実行して正しさを確認。回帰テスト追加(`tests/test_uipath_dsl.py`
     1件・`tests/test_uipath_codegen.py`4件)、UiPath関連テスト全972
     件通過、リポジトリ全体で全2058件通過。

174. **(完了、2026-11-10)** `ui:UpdateRowItem`を新規実装(知見216)
     ——知見183の`GetRowItem`の対になる書き込み側。調査中に
     `ExtractFiles`/`CompressFiles`が`ui:`とは別の名前空間
     (`uascw:`)を使うため`"ui:"`限定検索で0件だったことを発見、
     正しい名前空間での再調査を次tickの候補として記録。
     `ColumnName`指定時は`GetRowItem`と同じ「でっち上げた値で静かに
     間違えるより、失敗する方が安全」方針で`row[column_name] =
     value`直接代入(list行は`TypeError`で即座に失敗)。`ColumnIndex`
     指定時は`GetRowItem`と同じdict/list両対応だが、書き込みのため
     `list(row.keys())[idx]`経由のキー解決(dict行)/直接添字代入
     (list行)の2経路に分岐する——読み取り専用コードの単純な反転では
     済まないという実装上の違いを発見・対応。実機相当の構成を
     `exec()`経由で実際に実行して正しさを確認。回帰テスト追加
     (`tests/test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`
     8件)、UiPath関連テスト全980件通過、リポジトリ全体で全2066件
     通過。

175. **(完了、2026-11-10)** `uascw:ExtractFiles`を新規実装(知見217)
     ——知見216で発見した別名前空間(`clr-namespace:UiPath.
     Activities.System.Compression.Workflow`)を正しく指定して
     GitHub検索を再実行し実機確証を得た。実機1件で`FileToExtract`+
     `DestinationFolder`+`CodePage="Default"`+
     `ExtractToADedicatedFolder="False"`+`SkipUnsupportedFiles=
     "False"`のみの構成を確認(`Content`/`File`/
     `DestinationFolderInfo`/`Password`は常に未設定)。Pythonの
     `shutil.unpack_archive()`(標準ライブラリ、zip/tar系を自動判別)
     が新規依存無しで直接対応する——宛先フォルダの自動作成も確認済み。
     `ExtractToADedicatedFolder`/`CodePage`/`SkipUnsupportedFiles`が
     実機確認済みの値以外・`Password`設定時は`# TODO`。実際にzip
     アーカイブを作成して`exec()`経由で展開し正しさを確認。回帰テスト
     追加(`tests/test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`
     3件)、UiPath関連テスト全984件通過、リポジトリ全体で全2070件
     通過。残る`uascw:CompressFiles`は未着手、次の候補。

176. **(完了、2026-11-10)** `uascw:CompressFiles`を新規実装(知見218)
     ——`ExtractFiles`と対になる圧縮側、これで知見216が発見した
     `uascw:`名前空間の圧縮活動2件両方に着手済みとなった。フォーラム
     調査で「フォルダ圧縮時、フォルダ自身の名前はアーカイブに含まれ
     ず中身がトップレベルに展開される(サブフォルダ構造は保持)」という
     未公式ドキュメント化の挙動を確認、`zipfile`(標準ライブラリ)の
     `os.walk()`+`os.path.relpath()`で再現し実際にzip作成して検証
     した。実装中に`ContentToArchive`のリストパース処理が知見207の
     `FilterDataTable.SelectColumns`パーサーと構造的に同一だったため
     `_parse_property_element_list()`という汎用ヘルパーへ一般化し、
     両方がこれに委譲するよう整理した。`Password`/`SecurePassword`
     (`zipfile`標準では暗号化zip作成不可)・確認済み以外の
     `CompressionLevel`/`EncryptionAlgorithm`等は`# TODO`。回帰テスト
     追加(`tests/test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`
     3件)、UiPath関連テスト全988件通過、リポジトリ全体で全2074件
     通過。

177. **(完了、2026-11-10)** `ui:FileExistsX`/`ui:FolderExistsX`を新規
     実装(知見219)——`PathExists`(知見188)の`PathType`固定版と
     推測される2活動。タグ名限定検索で422件・227件という高いヒット
     数を確認し着手。ground-truthの属性構成は`Exists`+`Path`のみ
     (`PathExists`が持つ`PathType`/`Resource`は無い)。実機各2件で
     同じ単純な構成を確認。`FileExistsX`→`os.path.isfile()`、
     `FolderExistsX`→`os.path.isdir()`(`PathExists`の対応する分岐と
     同じAPI)が直接対応する。実際にファイル/フォルダを作成して
     `exec()`経由で正しさを確認。回帰テスト追加(`tests/
     test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`6件)、
     UiPath関連テスト全994件通過、リポジトリ全体で全2080件通過。

178. **(完了、2026-11-10)** `ui:Replace`を新規実装(知見220)——
     `IsMatch`(知見213)と同じ正規表現ビルダー系の兄弟活動、タグ名
     限定検索で359件ヒット。`ChangeCase`の0件ヒットの原因だった第3の
     名前空間`uast:`(`clr-namespace:UiPath.Activities.System.Text`)
     を特定したが、`ChangeCase`自体はヒット数が低く(7件)実装は見送り。
     `Replace`の実機2件で`Input`+`Pattern`+`Replacement`+`Result`+
     `RegexOption="IgnoreCase, Compiled"`の構成を確認、`.NET
     Regex.Replace(input, pattern, replacement)`→`re.sub(pattern,
     replacement, input)`が対応する。`IsMatch`と同じ`RegexOption`
     判断を再利用するため共有定数`_IS_MATCH_ALLOWED_OPTIONS`を
     `_REGEX_ALLOWED_OPTIONS`へ一般化。実機相当の構成を`exec()`経由
     で実際に実行して正しさを確認。回帰テスト追加(`tests/
     test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`3件)、
     UiPath関連テスト全998件通過、リポジトリ全体で全2084件通過。
     残る`Matches`(複数マッチ出力の実機確認が必要)を次の候補として
     記録。

179. **(完了、2026-11-10)** `ui:Matches`を新規実装(知見221)——
     知見220で次候補とした正規表現ビルダー系最後の兄弟活動、タグ名
     限定検索で448件ヒット。実機6件で出力に2種類(`Result`——型未確認
     ・`FirstMatch`——ラベル後の値を抜き出す単一文字列抽出の定番用途)
     があることを発見、`Result`は型未確認のため`# TODO`、
     `FirstMatch`のみ対応した。`.NET Regex.Match(input, pattern).
     Value`→`re.search()`(不一致時は.NETの`Match.Value`の既知の挙動
     に合わせ`None`ではなく`""`を返す)が対応する。実機の実際の
     パターン(可変長lookbehind)がPython標準`re`では非対応
     (`"look-behind requires fixed-width pattern"`)という.NET/Python
     正規表現構文の互換性差異を発見したが、知見144/213/220と同じ
     「パターン文字列自体は変換しない」既存の判断の範囲内——固定幅
     パターンで動作確認。回帰テスト追加(`tests/test_uipath_dsl.py`
     1件・`tests/test_uipath_codegen.py`3件)、UiPath関連テスト全
     1002件通過、リポジトリ全体で全2088件通過。これで知見213発見の
     正規表現ビルダー系活動3件(`IsMatch`/`Replace`/`Matches`)全てに
     着手済みとなった。

180. **(完了、2026-11-10)** `ui:TextToLeftRight`を新規実装(知見222)
     ——文字列を区切り文字の最初の出現位置で左右2つに分割する活動。
     実機2件で`FullText`+`Separator`+`TextToLeft`+`TextToRight`+
     `SeparatorKey`(`"Custom"`/`"NewLine"`の2種を確認)の構成を確認、
     `str.split(separator, 1)`が`.NET`側の「最初の出現位置で分割、
     区切り文字自体は出力に含まない」仕様に対応する。`Separator`が
     見つからない場合の挙動は公式ドキュメントにも未記載のため、
     `GetRowItem`(知見177/183)・`UpdateRowItem`と同じ「フォールバック
     値を捏造せず自然な例外に委ねる」方針を採用——`TextToRight`側の
     代入で自然な`IndexError`が発生するに任せる。`SeparatorKey`が
     実機確認済みの2種以外の場合は`Separator`の正確な事前入力が
     未確認のため`# TODO`。回帰テスト追加(`tests/test_uipath_dsl.py`
     2件・`tests/test_uipath_codegen.py`4件)、UiPath関連テスト全
     1008件通過、リポジトリ全体で全2094件通過。

181. **(完了、2026-11-10)** `ui:SetEnvironmentVariable`を新規実装
     (知見223)——`GetEnvironmentVariable`(知見215)の兄弟活動、タグ
     名限定検索で96件ヒット。`Name`+`Value`の2つのInArgumentのみ、
     常にOS環境変数として設定するだけで`System.Environment`既知
     プロパティ名との2経路判断が無いため、`Get`側と違い動的`Name`も
     問題なく対応できる。`os.environ[name] = value`に対応する
     (プロセス内スコープのみ)。`_collect_imports()`の既存
     `os.environ.`トリガーがブラケット記法`os.environ[`にはマッチ
     しないことを発見、別条件として追加した。`exec()`経由で実際の
     書き込みを確認(テスト後に`finally`でクリーンアップ)。回帰
     テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
     test_uipath_codegen.py`2件)、UiPath関連テスト全1011件通過、
     リポジトリ全体で全2097件通過。同じ調査で`ui:ModifyText`
     (`ucat:`名前空間の子を持つコンテナ型、実装推奨)と
     `ui:GetFileInfoX`/`ui:GetFolderInfoX`(単一不透明型オブジェクト
     出力、ダウンストリームの任意プロパティアクセス未モデル化のため
     見送り)も調査済み——`ModifyText`を次の候補として記録。

182. **(完了、2026-11-10)** `ui:ModifyText`を新規実装(知見224)——
     文字列に`Body`配下の子活動(5番目の非`UI_NS`名前空間`ucat:`
     ="UiPath.Core.Activities.TextModifications")を順番に適用する
     コンテナ型活動、タグ名限定検索で167件ヒット。`SourceText`+
     `OutputText`+`.Body`→`ActivityAction`(`DelegateInArgument`無し)
     →`Sequence`、既存の`_unwrap_body_sequence`/`_find_activity_action`
     ヘルパーを再利用。実機確認済みの子活動3種のみ対応:
     `FindAndReplaceTextModification`(プレーン文字列検索、
     `re.escape()`+`re.sub()`、`MatchCase`省略時は既定`False`=
     大文字小文字を区別しない)、`TrimTextModification`
     (`str.strip()`)、`ToUpperLowerTextModification`
     (`ModificationType`∈{`"Lowercase"`,`"Uppercase"`}、
     `str.lower()`/`str.upper()`)。未対応の子が1つでもあれば部分
     適用せず全体を`# TODO`へ倒す(`FilterDataTable`の`SelectColumns`
     省略時の全体decline、知見207と同じ判断)。**実装中に`re.sub()`の
     第4位置引数が`count`であり`flags`ではないこと
     (`re.search()`/`re.match()`とは引数順が異なる)を発見**——
     `re.IGNORECASE`を位置引数で渡すと大文字小文字の区別が一切効かず
     先頭2件だけに置換が制限される無言の誤動作になっていた、
     `exec()`での動作確認中に捕捉し`flags=`キーワード引数で修正。
     回帰テスト追加(`tests/test_uipath_dsl.py`2件・`tests/
     test_uipath_codegen.py`5件)、UiPath関連テスト全1018件通過、
     リポジトリ全体で全2104件通過。

183. **(完了、2026-11-10)** `ui:CommentOut`を新規実装(知見225)——
     Studioの「コメントアウト」操作で残る、`Body`配下を実行しない
     ラッパー、タグ名限定検索で5056件ヒット(既実装活動の中でも
     最多クラス)。属性は`DisplayName`のみ、`.Body`配下は
     `AttachWindow`(知見153)と同じ直接`Sequence`構造——既存の
     `_unwrap_body_sequence`を再利用。パーサーは`body`を構造情報
     として保持するが、コード生成側は`body`の内容を一切辿らず常に
     1行の説明コメントのみを返す(無効化されているはずの処理を
     実際に実行してしまわないため)——`_ensure_nonempty_suite`の
     既存の仕組みがそのまま`pass`を補うことを確認。`exec()`経由で
     `body`内の副作用のある文(`WriteLine`)が生成コードに一切現れ
     ないことを確認した。回帰テスト追加(`tests/test_uipath_dsl.py`
     1件・`tests/test_uipath_codegen.py`2件)、UiPath関連テスト全
     1021件通過、リポジトリ全体で全2107件通過。同じ発見パスで
     `ui:Continue`(458件ヒット、`Break`と同じ無属性)と
     `ui:RepeatNumberOfTimesX`(265件ヒット、`ForEach`と同じ
     `ActivityAction<Int32>`本体構造)を次の候補として記録。

184. **(完了、2026-11-10)** `ui:Continue`を新規実装(知見226)——
     既実装の`Break`(知見18)と全く同じ属性無しの自己終了タグ、
     タグ名限定検索で458件ヒット。`Break`の既存実装パターン
     (`BreakNode`→`break`、ループ文脈の事前検証は行わずPython自身の
     構文エラーに委ねる)をそのまま真似て`ContinueNode`→`continue`を
     実装、新規インフラ不要。`ForEach`+`If`で特定の値だけ`Continue`
     でスキップする構成を`exec()`経由で実際に実行し、残りのループ回
     だけ処理が続行されることを確認した。回帰テスト追加(`tests/
     test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`1件)、
     UiPath関連テスト全1023件通過、リポジトリ全体で全2109件通過。
     残る`ui:RepeatNumberOfTimesX`(265件ヒット、`ForEach`と同じ
     `ActivityAction<Int32>`本体構造)を次の候補として記録。

185. **(完了、2026-11-10)** `ui:RepeatNumberOfTimesX`を新規実装
     (知見227)——`ForEach`(知見5)と構造が完全に同じ
     `ActivityAction<Int32>`+`DelegateInArgument`(`CurrentItem`)本体、
     タグ名限定検索で265件ヒット。既存の`_find_activity_action`/
     `_unwrap_body_sequence`ヘルパーを再利用。公式ドキュメント確認
     済みの仕様——`StartAt`は`CurrentItem`の開始値のみを決め**反復
     回数には影響しない**、`NumberOfTimes`回だけ常に実行する——を
     `range(start_at, start_at + number_of_times)`で再現、
     `RetryScope`の`_retry_max`と同じ`round(_vb_cdbl(...))`で
     Int32相当に丸める。実機で`StartAt`省略(`Apress/...`)と
     `StartAt="0"`(`RPA-UiPath-Projects/Sort-country-list`)の両方を
     発見——省略時は公式ドキュメント確認済みの既定値`1`を補う。
     `StartAt`の値に関わらず常に`NumberOfTimes`回だけ実行される
     ことを`exec()`経由で確認した。回帰テスト追加(`tests/
     test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`3件)、
     UiPath関連テスト全1028件通過、リポジトリ全体で全2114件通過。
     これで知見225の発見パスで見つかった3件(`CommentOut`/
     `Continue`/`RepeatNumberOfTimesX`)全てに着手済み——次の候補は
     無く、次のtickで新規発見パスが必要。

186. **(完了、2026-11-10)** `ui:DeserializeXml`・`ui:ExecuteXPath`を
     新規実装(知見228)——`UiPath.WebAPI.Activities`パッケージの
     兄弟活動ペア、タグ名限定検索で54件/31件ヒット。`XMLString`
     (入力)+`XMLDocument`(出力、.NET`XDocument`)の2属性のみの
     `DeserializeXml`は`lxml.etree.fromstring()`(本体の既存確認済み
     依存、新規「プラグイン」依存ではない)に対応、`ExecuteXPath`は
     `ExistingXML`/`XMLString`の2入力経路+`XPathExpression`+
     `Result`——公式ドキュメント確認済みの「`XMLString`入力時は
     `ExistingXML`使用不可」仕様に従い`XMLString`優先。`.NET`のXPath
     実装もXPath 1.0相当のため`lxml`の`Element.xpath()`に構文変換
     無しで対応(`Regex`系活動とは違う)、`string(...)`ラップされた
     XPath式はPythonの`str`を返す。`DeserializeXml`→`ExecuteXPath`の
     実機相当パイプライン(`Sundsvallskommun/RPA-openeplatformapi`)を
     `exec()`経由で実際に実行し、単一文字列を正しく抜き出せることを
     確認した。回帰テスト追加(`tests/test_uipath_dsl.py`2件・
     `tests/test_uipath_codegen.py`4件)、UiPath関連テスト全1034件
     通過、リポジトリ全体で全2120件通過。同じ発見パスで見つけた
     `umab:`(`UiPath.Mail.Activities.Business`)名前空間の
     `MarkMailAsReadX`/`DeleteMailX`/`MoveMailX`トリオを次の候補と
     して記録。

187. **(完了、2026-11-10)** `umab:MarkMailAsReadX`・`umab:DeleteMailX`・
     `umab:MoveMailX`を新規実装(知見229)——タグ名限定検索で32件/
     31件/19件ヒット。`MailMessage`は既実装の`GetOutlookMailMessages`
     (知見120)が`win32com.client`経由で生成する生のOutlook COM
     `MailItem`オブジェクトそのもの——新規の型付きオブジェクトモデル
     は不要、Outlook COM API自身の`MailItem.UnRead`/`.Delete()`/
     `.Move(folder)`(Microsoft Learn確認済み)へ直接対応するだけで
     済んだ。`MoveMailX`の`MailFolder`解決は公式ドキュメントに
     明記が無いため、デフォルトストアのルート(`GetDefaultFolder
     (6).Parent`)を起点に再帰探索する新規ヘルパー`_outlook_
     find_folder`(`_vb_cstr`等と同じ「使用時のみ注入される複数行
     ヘルパー関数」パターン)を実装、見つからない場合は`None`を返し
     `.Move(None)`のCOMエラーに自然に委ねる。`pywin32`非搭載のため
     `MailItem`操作自体の`exec()`確認はできなかったが、`win32com`
     非依存の`_outlook_find_folder`ヘルパー自体はソーステキストを
     直接`exec()`してモックフォルダ階層で探索ロジックを確認した。
     回帰テスト追加(`tests/test_uipath_dsl.py`3件・`tests/
     test_uipath_codegen.py`6件)、UiPath関連テスト全1040件通過、
     リポジトリ全体で全2129件通過。

188. **(完了、2026-11-10)** `ui:InsertDataTable`・`ui:BulkInsert`を
     新規実装(知見230)——`ExecuteQuery`/`ExecuteNonQuery`(知見114)
     と同じ`UiPath.Database.Activities`、タグ名限定検索で33件/9件
     ヒット。属性構成・意味論が完全に同じ兄弟活動のため同じコード
     生成関数(`_insert_data_table_family_body`)を共用。
     `ExistingDbConnection`は`DatabaseConnect`(知見114)が常に
     生成する`sqlite3.Connection`——`Connection.executemany()`+`?`
     プレースホルダが対応する。`DataTable`がdict行表現の場合のみ
     列名付き`INSERT INTO table (col1, col2) VALUES (?, ?)`で正確に
     対応でき、list行表現の場合は列名が無いため全列を順序通りに
     与えると仮定する保守的な縮退(`# WARNING`付き)に倒す——
     `WriteCsvFile`(知見185)・`OutputDataTable`(知見184)と同じ
     既存方針の延長。`BulkInsert`の`TableName`はスキーマ修飾名
     (`"stage.datosVivienda"`)も実機確認済み。実際の`sqlite3`
     データベースへ`exec()`経由でdict行・list行の両方を実行し
     確認した。回帰テスト追加(`tests/test_uipath_dsl.py`1件・
     `tests/test_uipath_codegen.py`5件)、UiPath関連テスト全1041件
     通過、リポジトリ全体で全2135件通過。同じ発見パスで見つけた
     `ui:DatabaseTransaction`(28件ヒット、`RetryScope`と構造的に
     同じスコープ活動)を次の候補として記録。

189. **(完了、2026-11-10)** `ui:DatabaseTransaction`を新規実装
     (知見231、公式表示名「Start Transaction」)——タグ名限定検索で
     28件ヒット。`.Body`配下は`AttachWindow`(知見153)・`CommentOut`
     (知見225)と同じ直接`Sequence`。公式ドキュメント確認済みの
     2点が実装判断を左右した: ①既存`DatabaseConnection`渡し/
     `ConnectionString`+`ProviderName`自己接続の2モードがあり、
     後者は`DatabaseConnect`(知見114)と同じ「`System.Data.SQLite`
     以外未確認」方針により未対応。②`UseTransaction=False`
     (「各操作が個別にコミット」)は`ExecuteNonQuery`/
     `InsertDataTable`等の既存コード生成がすでに各自`commit()`する
     実装と完全に一致するため`Body`をそのまま展開するだけで動く一方、
     `UseTransaction=True`(既定値、「全操作を1つのトランザクション
     にまとめ失敗時は全体をロールバック」)は子活動が個別に
     `commit()`してしまう既存実装とは両立せず、子の`commit()`を
     抑制する文脈伝播機構が無いと正しいall-or-nothing保証を再現
     できないため、見た目だけ機能するtry/exceptをでっち上げるより
     `# TODO`へ倒した(`ModifyText`知見224と同じ「部分的に正しい
     より全体を拒否」)。`UseTransaction=False`の場合を実際の
     `sqlite3`データベースへ`exec()`経由で確認した。回帰テスト追加
     (`tests/test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`
     4件)、UiPath関連テスト全1045件通過、リポジトリ全体で全2141件
     通過。知見230の発見パスの候補は全て着手済み——次のtickで新規
     発見パスが必要。

190. **(完了、2026-11-10)** `uast:ExtractText`を新規実装(知見232)——
     `StartingText`と`EndingText`の間の文字列を抜き出す活動、
     タグ名限定検索で41件ヒット。知見220で発見済みだった`uast:`
     (`UiPath.Activities.System.Text`)名前空間を初めて定数化
     (`SYSTEM_TEXT_NS`)。ground-truthには単数形`Result`属性が無く
     `FirstMatch`/`Results`(複数)のみ記載されていたが、実機6件は
     常に`Result`(単数)を使う——知見197・230に続く「ground-truthは
     網羅的ではない」教訓の3度目の実例。マーカー文字列自体は出力に
     含まない(`TextToLeftRight`知見222と同じ判断、他社RPAツールの
     同種機能も同じ規約と確認)。`MatchCase`省略時は公式ドキュメント
     確認済みの既定`False`(大文字小文字を区別しない検索、出力は
     元の大文字小文字を保持)。マーカーが見つからない場合は
     `str.index()`の自然な`ValueError`に委ねる(フォールバック値を
     捏造しない既存方針)。`exec()`経由で大文字小文字を区別しない
     既定・区別する`MatchCase=True`・マーカー不在時の`ValueError`を
     確認した。回帰テスト追加(`tests/test_uipath_dsl.py`1件・
     `tests/test_uipath_codegen.py`6件)、UiPath関連テスト全1051件
     通過、リポジトリ全体で全2148件通過。同じ発見パスで見つけた
     `ui:GetLastDownloadedFile`(129件ヒット、スコープ構造+ポーリング
     処理)と`uix:NMouseScroll`(UIAutomationNextの`uix:`名前空間、
     219件ヒット、実機確認済みは要素記述子無しの単純なグローバル
     マウスホイールスクロール)を次の候補として記録。

191. **(完了、2026-11-10)** `ui:GetLastDownloadedFile`を新規実装
     (知見233、公式表示名「Wait for Download」)——タグ名限定検索で
     129件ヒット。`.Body`配下は`ModifyText`(知見224)と同じ
     `ActivityAction`+`Sequence`。`File`出力(.NET`FileInfo`)は
     `ForEachFileX`/`ForEachFolderX`(知見190)の既存方針(絶対パス
     文字列として表現)を再利用——実機のダウンストリーム利用が
     `.Name`/`.FullName`の2プロパティのみに限定されていたため
     `GetFileInfoX`/`GetFolderInfoX`の「未モデル化の型付き
     オブジェクト」問題には当たらないと判断、`render.py`に`.Name`
     →`os.path.basename()`対応を新規追加。公式ドキュメント確認済み
     の`Timeout`既定`300`秒、`IgnoreFiles`(ダウンロード完了まで
     無視する拡張子)を反映し、`DownloadFolder`配下のスナップショット
     差分を0.5秒間隔でポーリングする近似実装とした(知見206の画像
     照合近似と同じ方針)。実際の一時ディレクトリへ`exec()`経由で
     実行し、一時ファイル→本体ファイルの2段階出現を正しく検出する
     こと・`Timeout`超過時の`TimeoutError`・`.Name`/`.FullName`の
     両方を確認した。**同じ候補群の`uix:NMouseScroll`はサブエージェ
     ントの「実機は常に裸(要素記述子無し)」という主張を独立に
     再検証して反証**(1件は`uix:TargetAnchorable`付きの完全な
     要素記述子、もう1件は`CommentOut`で無効化済み)——UIAutomation
     Next要素記述子オブジェクトモデル(未モデル化)が必要と判明し
     見送り。サブエージェント報告を鵜呑みにせず独立に再検証する
     重要性の実例として記録。回帰テスト追加(`tests/test_uipath_dsl.py`
     1件・`tests/test_uipath_codegen.py`6件)、UiPath関連テスト全
     1058件通過、リポジトリ全体で全2155件通過。

192. **(完了、2026-11-10)** `ui:CheckTrue`・`ui:CheckFalse`を新規実装
     (知見234)——タグ名限定検索で303件/33件ヒット。`Expression`
     (ブール式)+`ErrorMessage`の2属性のみ、公式ドキュメント確認済み
     の「式がfalse(`CheckTrue`)/true(`CheckFalse`)の場合、カスタム
     メッセージ付きの例外を実行時に投げる」に対応する——正確な.NET
     例外型は未確認のため既存の`_EXCEPTION_TYPE_MAP`の未知型
     フォールバックと同じ汎用`Exception`で代用、`Expression`の
     ブール変換は`If`/`While`(知見61)の`_vb_bool()`を再利用し両活動
     共通のコード生成関数で対応した。`exec()`経由で両方向の真偽
     組み合わせを実際に実行し確認した。回帰テスト追加(`tests/
     test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`3件)、
     リポジトリ全体で全2159件通過。**今回の発見パスでは「候補ごとに
     実機2件以上のXAML本文を実際に取得し`CommentOut`無効化・`uix:`
     要素記述子依存を明示確認する」という厳格な方法論を事前に要求**
     (前tickの`uix:NMouseScroll`誤認の反省)——これにより
     UIAutomationNext(`uix:`)名前空間全体を今後の候補から除外する
     方針を確定した(`ueab:`Modern Excel系、知見230と同じ扱い)。
     同じ発見パスで`ui:CreateDirectory`(1760件ヒット)・
     `ui:MergeDataTable`(319件ヒット)・`ui:FormatValue`(13件ヒット)
     を次の候補として記録。

193. **(完了、2026-11-10)** `ui:CreateDirectory`を新規実装(知見235)
     ——`CopyFile`/`MoveFile`/`CreateFile`の兄弟活動、タグ名限定検索
     で1760件ヒット。`Path`のみが実機で非null(`ContinueOnError`/
     `Output`は一度も非null値を確認できず)。`Output`(.NET
     `DirectoryInfo`型、公式ドキュメント確認済みの「作成したフォルダ
     への参照」)は`GetFileInfoX`/`GetFolderInfoX`と同じ「未確認の
     型付きオブジェクトをでっち上げない」判断で未対応。`Path`の作成
     自体は.NET`Directory.CreateDirectory(path)`の確立済みAPI
     コントラクト(既存ディレクトリがあっても例外にならず中間の親
     ディレクトリもまとめて作成)——`CopyFile`(知見117)と同じ
     「.NET自体の公開APIコントラクトに基づく判断」であり
     `os.makedirs(path, exist_ok=True)`に直接対応する。実際の一時
     ディレクトリへ`exec()`経由で実行し、中間ディレクトリの作成・
     既存ディレクトリへの再実行での冪等性を確認した。回帰テスト
     追加(`tests/test_uipath_dsl.py`1件・`tests/
     test_uipath_codegen.py`4件)、リポジトリ全体で全2164件通過。
     残る`ui:MergeDataTable`(319件ヒット)・`ui:FormatValue`
     (13件ヒット)を次の候補として記録。

194. **(完了、2026-11-10)** `ui:MergeDataTable`を新規実装(知見236)
     ——タグ名限定検索で319件ヒット。`Destination`+`Source`+
     `MissingSchemaAction`(実機常に`"Add"`、.NET公式enumは
     `{Add, Ignore, Error, AddWithKey}`)。.NET`DataTable.Merge
     (sourceTable)`は呼び出し先をインプレースで変更するインスタンス
     メソッドのため、`Destination`の`list`表現を`.extend()`で拡張
     することで同じ参照共有の意味論を再現——さらに行を値コピー
     (参照共有ではない)する.NETの挙動に合わせ、dict行は`dict(_r)`
     で浅いコピーしてから追加する(単純な`.extend(source)`だと
     `Source`側の事後変更が`Destination`側へ伝播してしまうという
     実装中に気づいた罠)。本トランスパイラのDataTable表現(固定
     スキーマ無し)はそもそも列追加を自動的に許容するため`"Add"`
     の意味論が`.extend()`だけで自然に成立する。`exec()`経由で
     dict行・list行・連鎖マージ・`Source`事後変更の非伝播を確認
     した。回帰テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
     test_uipath_codegen.py`4件)、リポジトリ全体で全2169件通過。
     残る`ui:FormatValue`(13件ヒット)を次の候補として記録。

195. **(完了、2026-11-10)** `ui:FormatValue`を新規実装(知見237)——
     タグ名限定検索で13件ヒット(やや薄い)。`.Format`配下の3種類の
     子要素に対応: `GeneralNumberFormatProvider`/
     `CurrencyNumberFormatProvider`は`'{:,.Nf}'.format(_vb_cdbl
     (value))`(`Currency`は`Symbol`前置)、`DateTimeFormatProvider`
     は新規実装の`_convert_dotnet_date_pattern()`でトークン変換
     (`yyyy`/`MMMM`/`dddd`等、確認済みの範囲のみ)後に`.strftime()`。
     **実装中に発見した罠**: 最初の実装では未対応の.NET指定子文字
     (`H`/`h`/`m`/`s`等の時刻系トークン)が「予約済み文字ではない」
     と誤認識され、`"HH:mm:ss"`のような未対応パターンがリテラル
     テキストとしてそのまま`strftime()`へ渡ってしまう(サイレント
     に間違った結果を返す)バグを`exec()`確認前の単体テストで発見・
     修正——予約済み文字の判定セットを全指定子文字に拡張した。`Value`
     は入出力同じ変数へのインプレース変換、既存の`.NET DateTime`→
     `datetime.datetime`表現を前提とする。`exec()`経由で3種類全ての
     FormatProviderを実際に実行し確認した。回帰テスト追加(`tests/
     test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`8件)、
     リポジトリ全体で全2179件通過。知見236の発見パスの候補は全て
     着手済み——次のtickで新規発見パスが必要。

196. **(完了、2026-11-10)** `ui:Return`を新規実装(知見238)——
     タグ名限定検索で82件ヒット。サブエージェントが今回初めて
     「`UiPath.System.Activities`のground-truth全件リストと既実装
     リストの体系的な差分」という調査手法を採用、`IfElseIfV2`/
     `Return`/`AddLogFields`/`TimeoutScope`等の候補を発見した。
     `<ui:Return />`(属性無しの自己終了タグ、`Break`/`Continue`と
     同じ構造)。公式ドキュメント確認済みの「エラー無しでワーク
     フローをその時点で終了する」——本トランスパイラが各ワーク
     フローを独立したPython関数として生成する既存アーキテクチャの
     ため、Pythonの`return`文(値無し)に直接対応する。Libraryプロ
     ジェクト内での呼び出し元への終了伝播という.NET側特有の制約は
     本トランスパイラのライブラリ非インライン展開モデルのため該当
     しない。`If.Then`内の早期終了構成を`exec()`経由で実際に実行し
     確認した。回帰テスト追加(`tests/test_uipath_dsl.py`1件・
     `tests/test_uipath_codegen.py`1件)、リポジトリ全体で全2181件
     通過。同じ発見パスで`ui:IfElseIfV2`(390件ヒット)・
     `ui:AddLogFields`(1880件ヒット)・`ui:TimeoutScope`(134件
     ヒット、プリエンプティブ割り込みのインフラ設計判断が必要)を
     次の候補として記録。

197. **(完了、2026-11-10)** `ui:IfElseIfV2`を新規実装(知見239)——
     タグ名限定検索で390件ヒット、知見238と同じ7回目発見パスで
     見つかった現代的な複数分岐if/elif/else構造。`Condition`
     (トップレベルif)+`.Then`+`.ElseIfs`(`BindingList<ui:
     IfElseIfBlock>`、実機では空または1件以上)+`.Else`——
     `vajrang-b/UiPathIn30Days`で`.ElseIfs`が空の単純if/else構成、
     `HarshShindeTR/APISanity`・`SagarYelmarTR/TaxCaddy_sanity`で
     `.ElseIfs`に`BlockType="ElseIf"`が1件以上入ったif/elif/else
     構成を実機確認した。Pythonの`if/elif*/else`に直接対応する——
     `_generate_if`と同じ厳格な条件式失敗モード(`If.Condition`
     (知見61・155)と同じ)をトップレベル・`ElseIfs`各要素両方の
     `Condition`に適用する。副次的に発見した別物のレガシー活動
     `ui:IfElseIf`(`.ConditionBlocks`統合リスト構造)は今回の
     スコープ外として実装対象から除外した。単純if/else・
     if/elif/elseの両方を`exec()`経由で実際に実行し確認した。
     回帰テスト追加(`tests/test_uipath_dsl.py`2件・`tests/
     test_uipath_codegen.py`4件)、リポジトリ全体で全2187件通過。

198. **(完了、2026-11-10)** `ui:AddLogFields`/`ui:RemoveLogFields`を
     新規実装(知見240)——タグ名限定検索で1880/918件ヒット、今回の
     発見パス全体で最高の実機利用率。実機は公式`UiPath/
     Community.Activities`リポジトリ自身のREFrameworkテンプレート
     (`Templates/ReFrameWork/Main.xaml`・`Framework/
     SetTransactionStatus.xaml`)で確認——`AddLogFields.Fields`は
     知見104の`HttpClient.Headers`と同じ`x:Key`付き直列化、
     `RemoveLogFields.Fields`は知見207・218の`_parse_property_
     element_list()`と同じ`<scg:List>`パターンで、いずれも既存
     パーサーをそのまま再利用できた。実行時意味論(`RemoveLogFields`
     まで以降の全`LogMessage`にフィールドが付与され続ける命令的な
     持続)は、バックログが予測した「既存`ScopeInfo`の自然な拡張」
     という読みを半分だけ裏付けた——静的な`ScopeInfo.has_log_fields`
     フラグ(既存`LogMessage`テストへの後方互換ガード)と、関数ローカル
     な`_log_fields`辞書(実行時の動的な状態、新規ヘルパー
     `_log_fields_suffix`経由で`LogMessage`に合流)の2段構成で実装した。
     ファイルを跨いだ(`InvokeWorkflowFile`経由の)フィールド伝播は
     既存の`data_table_columns`と同じ理由で意図的に未対応。実機相当の
     `AddLogFields`→`LogMessage`→`RemoveLogFields`→`LogMessage`の順序を
     `exec()`経由で実際に実行し確認した。回帰テスト追加(`tests/
     test_uipath_dsl.py`4件・`tests/test_uipath_codegen.py`3件)、
     リポジトリ全体で全2194件通過。

199. **(完了、2026-11-10)** `ui:DeserializeJson<njl:JObject>`を新規
     実装・`ui:TimeoutScope`は見送り(知見241)。`TimeoutScope`
     (134件ヒット)は実機`RobotGod1/AgingCareSignOff...`で
     `ThrowExceptionAfter`+`TimeoutMessage`+`ActivityAction<Activity>`
     Body構造を確認したが、本トランスパイラの実際のデプロイ先
     (`pywinauto`依存、Windows GUI自動化)では`signal.alarm`が
     `AttributeError`で確実に壊れ、スレッドベースのソフトタイムアウト
     は孤立スレッドがUI操作を続ける競合状態を招き、事後測定は実機の
     典型例(無限ポーリングループ)に対して何の保護にもならない——
     3つの実装案いずれも`DatabaseTransaction.UseTransaction=True`
     (知見231)と同じ「新規インフラ無しでは誠実な実装ができない」
     ケースと判断し見送った。`DeserializeJson`(1230件ヒット)は
     知見229が「`GetFileInfoX`級の未モデル化オブジェクト懸念」と
     記録していたが、実機`base64ai/uipath-samples`の確認済み利用形
     `formattedJson("matches").Count.ToString`が`DataRow`添字
     (知見126・203)と構文的に同一だったため、新規`ScopeInfo.
     json_object_vars`フィールド1つ(`data_row_vars`と同じ添字解決
     ロジックを共有)+`.Count`を既存の`.Length`→`len()`マッピングへ
     別名追加するだけで対応できた——架空のラッパークラスは不要、
     `JObject`はPythonの`dict`(`json.loads()`の戻り値)に直接対応する。
     C#式言語プロジェクトの実機サンプルは既存の知見129・136の
     「でっち上げず`None`へ倒す」方針がそのまま適用され新規コード
     不要だった。実機相当の式を`exec()`経由で実際に実行し確認した。
     回帰テスト追加(`tests/test_uipath_dsl.py`2件・`tests/
     test_uipath_codegen.py`3件)、リポジトリ全体で全2199件通過。

200. **(完了、2026-11-10)** `ui:GoBack`・`ui:NavigateTo`を新規実装
     (知見242)——サブエージェントによる8回目の新規発見パス
     (`gh api search/code`タグ名限定検索+実機2件以上の個別フェッチ
     確認)で発見。タグ名限定検索で88/423件ヒット。`GoBack`は
     既存の`RefreshBrowser`(知見175)と属性構成が完全に同型
     (`Browser`のみ)——`{x:Null}`の場合、主要ブラウザ共通の
     `Alt+Left`に対応する(`RefreshBrowser`の`{F5}`と同じ
     `keyboard.send_keys()`経路)。`NavigateTo`は`Browser`
     (`{x:Null}`)+`Url`——`Ctrl+L`でアドレスバーへフォーカスし、
     `TypeInto`(知見110)の既存`_pywinauto_type_keys_escape()`
     ヘルパーをそのまま再利用して`Url`をエスケープしてから
     `{ENTER}`で確定する。両方とも新規インフラ不要、既存パターンの
     直接の延長。同じ発見パスで`ui:GetFromClipboard`(86件ヒット)・
     `ui:DeserializeJsonArray`(142件ヒット)・`ui:CopyFolderX`/
     `ui:MoveFolderX`(24/28件ヒット)を次の候補として記録。
     `ui:CheckBox`(無関係なWPFコントロールの誤検出)・
     `ui:InjectJsScript`(ブラウザ内JS実行エンジンが必要、`uix:`/
     `ueab:`と同じ構造的な壁)は対象外と確定。回帰テスト追加
     (`tests/test_uipath_dsl.py`4件・`tests/test_uipath_codegen.py`
     5件)、リポジトリ全体で全2208件通過。

201. **(完了、2026-11-10)** `ui:GetFromClipboard`を新規実装(知見243)
     ——タグ名限定検索で86件ヒット、同じ8回目発見パスの候補。実機2件
     (`tylorbunting/P006---Update-COVID19-Dashboard`・
     `datasherlock/aws-workspace-login-rpa`)で確認——既存の
     `SetToClipboard`の完全な逆方向、`pyperclip.paste()`に対応する。
     `TimeoutMS`は公式ドキュメント確認済みのUI Automation系活動一般の
     実行タイムアウト概念(クリップボードのポーリング待機ではない)
     と判明し、`pyperclip.paste()`に対応するタイムアウト概念自体が
     存在しないため意図的にモデル化しない。`Result`(代入先)は
     `Assign.target`(知見136・137)・`DeserializeJson.JsonObject`
     (知見241)と同じ厳格な失敗モード。このサンドボックスには実際の
     クリップボード機構が無いため`unittest.mock.patch`で`pyperclip.
     paste`自体をモックして`exec()`経由で実際の動作を確認した——
     文字列検証のみだった既存の`SetToClipboard`テストより一歩進んだ
     検証手法。回帰テスト追加(`tests/test_uipath_dsl.py`2件・
     `tests/test_uipath_codegen.py`3件)、リポジトリ全体で全2213件
     通過。

202. **(完了、2026-11-10)** `render.py`のバグ修正2件(知見244)——
     `ui:DeserializeJsonArray`(知見245)の実機サンプル調査中に発見。
     (1)`JObject/JArray`添字(`ScopeInfo.json_object_vars`、知見241)
     直後の単独`.ToString()`(実機`vajrang-b/UiPathIn30Days`で
     `JsonObject("results").ToString()`を発見)は戻り値の実行時型
     (JSONコンテナかスカラーか)が静的に決定不能——`_vb_cstr()`への
     無条件変換は前者の場合に無効なJSONを生成してしまうため、
     `_render_chained_access`冒頭に`NotImplementedError`ガードを
     追加した。(2)3段以上のバレ変数連鎖(実機`base64ai/uipath-
     samples`で`formattedJson.Count.ToString`を発見)は、知見119の
     既存コードが末尾セグメントだけを剥がし`prefix`を不透明な名前
     として扱っていたため中間セグメント(`Count`)が未翻訳のまま
     素通りし実行時`AttributeError`になっていた——`_canonical_name
     (prefix)`を`_render_node(Ident(name=prefix))`の再帰呼び出しに
     変更し修正した(`_SAFE_BARE_MEMBERS`への`"count"`追加漏れも
     同時に修正)。既存の知見241回帰テストは一切壊れていない。

203. **(完了、2026-11-10)** `ui:DeserializeJsonArray`を新規実装
     (知見245)——タグ名限定検索で142件ヒット、`DeserializeJson<njl:
     JObject>`(知見241)の兄弟活動。実機2件(`vajrang-b/
     UiPathIn30Days`・`base64ai/uipath-samples`)で確認——
     `x:TypeArguments`無しの非ジェネリック活動、常に`JArray`→Python
     の`list`(`json.loads()`の戻り値)に対応する。`ScopeInfo.
     json_object_vars`(知見241)を`JsonArray`出力変数+`ui:ForEach
     x:TypeArguments="njl:JToken"`の反復変数の両方に拡張登録——
     `ForEachRow`の`data_row_vars`伝播(知見203)と同じ既存パターンを
     再利用した。知見244のバグ修正により実機サンプルの連鎖式
     (`JObject("results").ToString()`)が正しく`# TODO`へ倒れ、
     `formattedJson.Count.ToString`が正しく`len()`へ変換されることを
     確認した。実機相当の両方の構成を`exec()`経由で実際に実行し確認
     した。回帰テスト追加(`tests/test_uipath_dsl.py`2件・`tests/
     test_uipath_codegen.py`4件)、リポジトリ全体で全2219件通過。

204. **(完了、2026-11-10)** `ui:CopyFolderX`・`ui:MoveFolderX`を
     新規実装(知見246)——タグ名限定検索で24/28件ヒット、8回目発見
     パスの最後のTier 2候補。実機3件(`RobotGod1/
     IndianaOverheadAdjustment.RPA.Uipath.Process`・`Masbahul-bari/
     UiPath`・公式`Apress/Robotic-Process-Automation-Using-UiPath-
     StudioX`)で確認——既存の`CopyFile`/`MoveFile`(知見117・188)の
     フォルダ版、`shutil.copytree()`/`shutil.move()`に対応する。
     `To`が既存ディレクトリの場合の正確な意味論(リネームかネスト
     配置か)は実機サンプルの静的検査だけでは確定できなかったため、
     WebFetch経由で公式ドキュメントの`Overwrite`の説明文(「宛先に
     `From`と同じ名前の既存フォルダがあれば置き換える」)を直接確認
     し、既存の`CopyFile`/`MoveFile`の「移動先/コピー先が既存の
     ディレクトリならファイル名(フォルダ名)を付加する」解決ロジック
     を安全に再利用できると判断した。`CopyFolderX`の`IncludeSubfolders`
     は実機・ground-truth既定値いずれも`"True"`のみ確認——
     `MoveFolderX`には無い(移動は常にフォルダ全体が対象)。実際の
     一時ディレクトリへの読み書きを`exec()`経由で行い、ネストした
     配置・`Overwrite=False`時の`FileExistsError`のいずれも実際の
     ファイルシステム操作で確認した。回帰テスト追加(`tests/
     test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`10件)、
     リポジトリ全体で全2231件通過。8回目発見パスはこれで完了
     ——バックログは再び空になった。

205. **(完了、2026-11-10)** `ui:StartProcess`を新規実装(知見247)
     ——タグ名限定検索で458件ヒット、9回目発見パス。実機2件
     (`cameronmcnz/uipath-tutorials`・`ShonHarsh/UiPath-Program-
     Start-Up-Bot`)で確認——`.NET Process.Start()`相当のOSレベル
     プロセス起動、`FileName`+`Arguments`+`WorkingDirectory`。
     サブエージェントの1位候補`ui:TypeSecureText`は独立再検証で
     既に知見158で実装済みと判明(別のNode型`TypeIntoNode`を再利用
     する設計のため、`Node`サブクラス名ベースの除外リストに載って
     いなかった既知の穴)——2位の`StartProcess`へ進んだ。`Arguments`
     は既存の`OpenApplicationNode`(知見154)と同じ理由(Windows
     コマンドライン分割規則未確認)で見送るが、`WorkingDirectory`は
     `subprocess.Popen()`の`cwd`引数という曖昧性の無い概念のため
     確信を持って対応した。`ExecutionType`は確認済みの既定値
     `"Asynchronous"`のみ対応。`subprocess.Popen`自体をモックして
     `exec()`経由で実際に呼ばれる引数を確認した。回帰テスト追加
     (`tests/test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`
     7件)、リポジトリ全体で全2239件通過。

206. **(完了、2026-11-10)** `ui:GetSecureCredential`・
     `ui:AddCredential`・`ui:RequestCredential`を新規実装(知見248)
     ——タグ名限定検索で174/125/123件ヒット、9回目発見パス。実機は
     公式`UiPath/Community.Activities`のREFrameworkテンプレート
     (`Templates/ReFrameWork/Framework/GetAppCredentials.xaml`)で
     確認——`GetSecureCredential`→`RequestCredential`→
     `AddCredential`のフォールバックフローが一緒に使われている。
     既存の`GetPasswordNode`(知見176、XAML埋め込みDPAPIバイナリで
     永久に`# TODO`)とは全く異なる構造——`Target`は実行時のWindows
     資格情報マネージャー検索キーで、`pywin32`(既存の確認済み依存)
     の`win32cred.CredRead()`/`CredWrite()`に対応する。独立検証で
     `win32cred.CredRead()`が見つからない場合`None`を返すという
     一部のサードパーティ情報源の誤った記述を発見・訂正し、本物の
     `pywin32`は`pywintypes.error`(`winerror=1168`)を投げることを
     確認した上で例外を捕捉するヘルパーを実装——鵜呑みにしていたら
     未処理の例外でクラッシュする生成コードになっていた潜在バグ。
     `CredentialBlob`のUTF-16(`utf-16-le`)エンコード/デコードも
     確認した。`RequestCredential`は`InputDialogNode`(知見131)の
     `input()`直接対応判断を継承、`Result`(Cancel判定)はブロッキング
     入力に対応概念が無いため束縛時は常に`True`(近似)。このサンド
     ボックスには実際の`pywin32`が無いため`sys.modules`へフェイク
     `win32cred`/`pywintypes`を注入して`exec()`経由で
     `AddCredential`→`GetSecureCredential`の往復・見つからない場合の
     正しい`Result=False`を確認した。回帰テスト追加(`tests/
     test_uipath_dsl.py`3件・`tests/test_uipath_codegen.py`8件)、
     リポジトリ全体で全2250件通過。

207. **(完了、2026-11-10)** `uast:SplitText`・`uast:CombineText`を
     新規実装(知見249)——タグ名限定検索で22/12件ヒット、9回目発見
     パス最後のTier 3候補。「トリビアルな穴埋め」という事前評価を
     覆す発見があった: 実機2件(`liamsrowley/uipath-product-
     tracker`・`mhmdreda99/UipathProjects`)で`SeparatorKey=
     "NewLine"`時の`Separator`実際の直列化値を確認したところ、
     同じ`SeparatorKey`概念を持つ既存の`ui:TextToLeftRight`
     (知見222、実CRLFバイト確認済み)とは違う規約——文字そのまま
     `"NewLine"`というラベル文字列だった。もし`TextToLeftRight`と
     同じ戦略を流用していたら`str.split("NewLine")`という静かに
     間違ったコードを生成してしまっていた——`SeparatorKey`の値に
     応じてPython側で実際の区切り文字(確認済みは`"NewLine"`→
     `"\r\n"`のみ)へ変換する設計に切り替えた。`SplitText`は
     `str.split(separator)`、`CombineText`は`separator.join(source)`
     に対応する。実機相当の式を`exec()`経由で実際に実行し確認した。
     回帰テスト追加(`tests/test_uipath_dsl.py`2件・`tests/
     test_uipath_codegen.py`6件)、リポジトリ全体で全2258件通過。
     9回目発見パスはこれで完了。

208. **(完了、2026-11-10)** `ui:GetIMAPMailMessages`を新規実装
     (知見250)——タグ名限定検索で579件ヒット、9回目発見パスで唯一
     残っていた大物候補。実機2件(`cameronmcnz/uipath-tutorials`・
     `JAYASIMMA/Loan_Apply_Utility_Bot`)で確認——`Server`+`Port`+
     `Email`+`Password`/`SecurePassword`+`EnableSSL="True"`+
     `SecureConnection="Auto"`+`MailFolder`+`Top`+`MarkAsRead`+
     `OnlyUnreadMessages`+`DeleteMessages`+`OrderByDate`(公式確認済み
     既定値`"NewestFirst"`+実機確認済み`"OldestFirst"`)。
     `GetOutlookMailMessages`(知見120)の「生のネイティブオブジェクト
     をそのまま返す」方針が`email.message.Message`(`.get()`辞書的
     アクセスのみ、`.Subject`属性アクセス不可)には通用しないと判明
     ——確認済みの下流アクセス(`.Subject`のみ)に絞った最小限の薄い
     ラッパークラス`_ImapMailMessage`を新規設計した
     (`GetLastDownloadedFile`知見233と同じ判断クラス)。`.Attachments`
     は`ui:SaveMailAttachments`と合わせて設計すべきため見送り、
     次の候補として記録。`imaplib.IMAP4_SSL`自体をモックして
     `exec()`経由で`login`/`select`/`search`/`NewestFirst`反転/`Top`
     絞り込み/`fetch`/`MarkAsRead`/`DeleteMessages`/
     `OnlyUnreadMessages`/`close`/`logout`の全制御フローを確認した
     ——標準ライブラリのため既存のOutlook COM系テストより一歩進んだ
     検証手法。回帰テスト追加(`tests/test_uipath_dsl.py`2件・
     `tests/test_uipath_codegen.py`8件)、リポジトリ全体で全2268件
     通過。

209. **(完了、2026-11-10)** `ui:SaveMailAttachments`を新規実装
     (知見251)——タグ名限定検索で329件ヒット、9回目発見パス最後の
     候補。実機2件(`cameronmcnz/uipath-tutorials`・`JAYASIMMA/
     Loan_Apply_Utility_Bot`)で確認——`Message`+`FolderPath`+
     `ExcludeInlineAttachments`+`OverwriteExisting`。知見250で
     見送った`_ImapMailMessage.Attachments`プロパティ
     (`(filename, disposition, part)`タプルのリスト)を新規設計し、
     `FolderPath`の自動作成(公式ドキュメント確認済み)に
     `os.makedirs(..., exist_ok=True)`で対応した。`OverwriteExisting`
     は公式ドキュメント自体が本文とプロパティ説明で矛盾した記述を
     含み`"False"`/未設定時の重複ファイル名解決が未確認と判明した
     ため`"True"`のみ対応(Pythonの`open(..., "wb")`の既定動作が
     そのまま意味論と一致する幸運な一致)。実際のマルチパートMIME
     メール(添付ファイル1件+インライン画像1件)を`imaplib.
     IMAP4_SSL`モック経由で`GetIMAPMailMessages`→`ForEach`→
     `SaveMailAttachments`という実機相当のパイプライン全体に流し、
     `exec()`経由で実際に一時ディレクトリへファイルを書き出し、
     インライン画像の除外・添付ファイル内容の正確性を確認した。
     回帰テスト追加(`tests/test_uipath_dsl.py`2件・`tests/
     test_uipath_codegen.py`4件)、リポジトリ全体で全2274件通過。
     9回目発見パスはこれで完全に完了。

210. **(完了、2026-11-10)** `ui:SelectFolder`を新規実装(知見252)
     ——タグ名限定検索で211件ヒット、10回目発見パス。実機2件
     (`cameronmcnz/uipath-tutorials`・`rohanbaraskar/UiPath-11`)+
     ground-truthいずれも一致した唯一の属性構成は`SelectedFolder`
     (出力)のみ——`SelectFile`(知見192)と違い`Filter`等の入力
     プロパティ自体が存在しない。ネイティブOSダイアログでの対話操作
     そのものを表すため、`SelectFile`と同じ理由で常に`# TODO`へ倒す
     ——知見176・174・192と同じ「常にTODOへ倒れる活動でも適切に
     モデル化する価値がある」判断の4例目。回帰テスト追加(`tests/
     test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`3件)、
     リポジトリ全体で全2278件通過。残る10回目発見パスの候補
     (`uas:GetUsernamePasswordX`・`ui:GetEnvironmentFolder`・
     `ui:GetProcesses`・`ui:ReadPDFWithOCR`・`ui:InvokeVBA`)は
     次の候補として記録。

211. **(完了、2026-11-10)** `uas:GetUsernamePasswordX`を新規実装
     (知見253)——タグ名限定検索で67件ヒット、知見248の
     `win32cred.CredRead()`基盤を再利用。初出の`UiPath.Activities.
     System`名前空間(`uas:`、知見237の`uast:`の兄弟)を確認。実機2件
     (`tudor555/Best-Flight`・`adithya0414/GetEmailsWith_IMAP-
     Filtering`)で完全一致した構成(`CredentialsSource=
     "CredentialsManager"`+`Credential`+`CredentialName`)を確認。
     `Result`出力が存在せず挙動未確認のため`_win32_cred_read`ヘルパー
     (例外を`None`へ変換)は再利用せず、`win32cred.CredRead()`を直接
     呼んで`pywintypes.error`を素通りさせる設計とした——`GetRowItem`/
     `UpdateRowItem`の「不明な場合は自然な例外に委ねる」方針の継承。
     `.Username`/`.Password`ドット記法アクセスには`_ImapMailMessage`
     (知見250)と同じ判断クラスの新規薄いラッパー`_Win32Credential`を
     設計。`exec()`経由で発見・見つからない両ケース(フェイク
     `win32cred`/`pywintypes`モジュール注入)を確認。回帰テスト追加
     (`tests/test_uipath_dsl.py`1件・`tests/test_uipath_codegen.py`
     5件)、リポジトリ全体で全2284件通過。残る10回目発見パスの候補
     (`ui:GetEnvironmentFolder`・`ui:GetProcesses`・
     `ui:ReadPDFWithOCR`・`ui:InvokeVBA`)は次の候補として記録。

212. **(完了、2026-11-10)** `ui:GetEnvironmentFolder`を新規実装
     (知見254)——タグ名限定検索で88件ヒット、`ui:
     GetEnvironmentVariable`(知見215)とは別タグ。実機4件+
     ground-truthで確認できた`SpecialFolder`値は`MyDocuments`/
     `UserProfile`/`Desktop`の3つのみ(.NET`Environment.
     SpecialFolder`は21個の値を持つが、それ以外は実機未確認のため
     `# TODO`へ倒す)。`os.path.expanduser("~")`+`os.path.join()`で
     対応——新規依存不要、既存の`"os.path."`インポートトリガーが
     そのまま効く。実機1件は`FolderPath`をC#の`CSharpReference`
     要素(VBの`InArgument`/`Literal`ではない)で表現していた
     エッジケースも見つけたが、`folder_path=None`として正しく
     `# TODO`へ倒れることを確認し、C#式サポートの追加は見送った。
     回帰テスト追加(`tests/test_uipath_dsl.py`1件・`tests/
     test_uipath_codegen.py`4件)、リポジトリ全体で全2288件通過。
     残る10回目発見パスの候補(`ui:GetProcesses`・
     `ui:ReadPDFWithOCR`・`ui:InvokeVBA`)は次の候補として記録。

213. **(完了、2026-11-10)** `ui:GetProcesses`を新規実装(知見255)
     ——タグ名限定検索で72件ヒット。既存のコア依存`psutil`の
     `psutil.process_iter()`が`Processes`出力に直接対応、新規依存
     不要。実機サンプル調査で知見169の既存記述の不足を発見し、
     副産物として`KillProcess.Process`の既存ギャップも閉じた——
     `GetProcesses`の出力をループした`Process`オブジェクトを
     `CType(...)`キャストして`KillProcess.Process`へ渡す非null実例
     (知見169の時点では確認できていなかった)を発見し、
     `.kill()`で対応。`.ProcessName`→`psutil.Process.name()`は
     既存のチェインメンバ変換テーブルに1エントリ追加するだけで
     対応、`CType(expr, Type)`(.NETの明示的型キャスト、本調査初
     遭遇)は`render.py`に恒等変換として追加(`CStr`/`CInt`等と同じ
     関数呼び出しディスパッチ層)。`AppliesTo="All"`の新しい非null
     実例も発見し、公式ドキュメントで既定値と同じ意味であることを
     確認——知見169の記述を補強。回帰テスト追加(`tests/
     test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`7件、
     既存1件を更新)、リポジトリ全体で全2296件通過。残る10回目
     発見パスの候補(`ui:ReadPDFWithOCR`・`ui:InvokeVBA`)は次の
     候補として記録。

214. **(完了、2026-11-10)** `ui:ReadRange`を新規実装(知見256)
     ——ユーザー要望(Excel/Word/マウスキーボード操作の網羅性向上)で
     専用の調査パスを実施し発見。タグ名限定検索で3904件ヒット、
     本調査史上(知見1〜255)最高ヒット数。`ExcelApplicationScope`
     配下限定の既存`ExcelReadRangeNode`とは別の、`WorkbookPath`を
     自分自身の属性として持つスコープ無し単独動作の"Workbook"系
     活動ファミリーの最初の1件。既存の`openpyxl`基盤を再利用し、
     自分自身で`load_workbook()`/`close()`する。`SheetName`は
     既存のスコープ版の`str`限定制約と違い最初から`Expr`型
     (動的VB式を実機確認済み)として対応。実際の`openpyxl`で
     `exec()`経由の動作確認済み。回帰テスト追加(`tests/
     test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`7件)、
     リポジトリ全体で全2324件通過(本活動の9件分の純増——このティック
     の開始時点で別セッションが並行してOutlookモジュールを独立に
     コミット済み、明示的パスリスト指定で衝突無く共存)。調査パスで
     Word classic(`WordAppendText`等)・マウスキーボード系
     (`ui:SetFocus`等)の候補も判明済み、次のティックで継続実装。

215. **(完了、2026-11-10)** `ui:WriteRange`を新規実装(知見257)
     ——`ReadRange`(知見256)の書き込み側、同じスコープ無し
     "Workbook"系ファミリー。タグ名限定検索で2892件ヒット。実機4件で
     `WorkbookPath`(動的VB式の文字列連結、または角括弧無しの素の
     リテラルパスの両方)・`SheetName`・`StartingCell`(常にA1既定
     相当)・`Password`(常に`{x:Null}`、新規属性)を確認。
     `ExcelWriteRangeNode`(知見115修正済み)が確立した「直接セル
     指定書き込み(既存データのあるシートでも正しい位置へ上書き)」を
     継承しつつ、スコープ無しで自分自身の`load_workbook()`→書き込み
     →`.save()`を行う。`sheet_name`は既存のスコープ版の`str`限定
     制約と違い最初から`Expr`型として対応、`starting_cell`が動的式
     (非`Literal`)の場合は新たに`# TODO`へ倒す判定を追加(実機未
     観測の組み合わせへの事前の安全策)。実際の`openpyxl`で既存データ
     上書き・動的`WorkbookPath`保存の両方を`exec()`経由で確認。
     回帰テスト追加(`tests/test_uipath_dsl.py`2件・`tests/
     test_uipath_codegen.py`7件)、リポジトリ全体で全2333件通過
     (本活動の9件分の純増)。残るWord classic・マウスキーボード系の
     候補は次のティックで継続実装。

216. **(完了、2026-11-10)** `ui:WordAppendText`/`ui:WordSaveAs`/
     `ui:WordReadText`を新規実装(知見258)——同時に知見121の
     `WordApplicationScope`の既存バグも発見・修正した。独立検証で
     実機2件が知見121のground-truth(`UI_NS`+`FileName`属性)とは
     別の直列化規約(専用`WORD_NS`+`FilePath`属性)を使うことを発見
     ——この規約では`WordApplicationScope`自体が丸ごと
     `UnknownActivityNode`に落ち、配下の子活動も一切パースされて
     いなかった。`WORD_NS`定数を新設し両方の名前空間でディスパッチ
     登録、`file_name`抽出も両方の属性名を試すよう修正。新規3活動
     は`WordAppendText`(`Text`のみ、`python-docx`の
     `add_paragraph()`)・`WordSaveAs`(`FilePath`のみ、スコープ末尾の
     無条件保存は継続実行される既知の限界をdocstringに明記)・
     `WordReadText`(`Text`出力、全段落の`"\n".join()`で近似)。
     `parse_workflow_file()`→`generate_python()`→`exec()`の全経路
     で4活動連鎖の動作確認済み。回帰テスト追加(`tests/
     test_uipath_dsl.py`4件・`tests/test_uipath_codegen.py`10件)、
     リポジトリ全体で全2347件通過(本活動の14件分の純増)。残る
     Word classic(`WordInsertDataTable`等)・マウスキーボード系
     (`ui:SetFocus`等)の候補は次のティックで継続実装。

217. **(完了、2026-11-10)** `ui:ReadCell`/`ui:WriteCell`を新規実装
     (知見259)——`ReadRange`/`WriteRange`(知見256/257)と同じ
     スコープ無し"Workbook"系ファミリー。タグ名限定検索で53件/465件
     ヒット。**マウスキーボード系の`ui:SetFocus`(前ティックの候補)
     は知見164で既に`ActivateNode`へ実装済みの偽陽性と判明**——
     Node-class名リストのみでの除外照合では見つからない既存実装を
     再発見しないよう、知見247の二重除外リスト方針を再確認。実機4件
     で`Cell`(静的/動的両方、知見119と同じ連番セル指定パターン)・
     `SheetName`・`WorkbookPath`(動的/静的両方)・`Result`
     (`ReadCell`の出力、テキスト直書き`OutArgument`形)を確認。
     `ExcelReadCellNode`/`ExcelWriteCellNode`(知見22/119)の
     `workbook[sheet_name][cell]`添字記法をそのまま再利用し、自分
     自身で`load_workbook()`する。実際の`openpyxl`で静的読み取り・
     動的連番書き込みの両方を`exec()`経由で確認。回帰テスト追加
     (`tests/test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`
     9件)、リポジトリ全体で全2358件通過(本活動の11件分の純増)。
     残るWord classic(`WordInsertDataTable`等)・マウスキーボード系
     (`ui:GetActiveWindow`等)の候補は次のティックで継続実装。

218. **(完了、2026-11-10)** `ui:WordAddImage`を新規実装(知見260)
     ——タグ名限定検索で49件ヒット。実機3件中2件は`InsertRelativeTo
     ="Document"`/`Position="End"`を明示、1件は両属性とも完全に
     省略——公式ドキュメントで両方が同じ既定値であることを裏取り
     した。それ以外の値(`Text`/`Bookmark`相対モード)は実機未確認の
     ため`# TODO`へ倒す。`python-docx`の`Document.add_picture()`
     (公式ドキュメント確認済み:「ドキュメント末尾に新しい段落として
     画像を追加する」)が確認済みの既定動作に正確に対応——
     `WordAppendTextNode`(知見258)の`add_paragraph()`と対になる
     テキスト版/画像版の関係。実際のPIL生成画像ファイルで`exec()`
     経由の動作確認済み。回帰テスト追加(`tests/test_uipath_dsl.py`
     2件・`tests/test_uipath_codegen.py`4件)、リポジトリ全体で全
     2364件通過(本活動の6件分の純増)。残るWord classic
     (`WordInsertDataTable`・`WordReplacePicture`)・マウスキーボード系
     (`ui:GetActiveWindow`等)の候補は次のティックで継続実装。

219. **(完了、2026-11-10)** `ui:WordInsertDataTable`を新規実装
     (知見261)——タグ名限定検索で28件ヒット。実機2件とも
     `InsertRelativeTo="Text"`+`Position`(`"After"`/`"Replace"`)が
     唯一の確認済み使い方(公式ドキュメント既定の`"Document"`/
     `"Start"`は実機未確認)。**独立検証で汎用XAML構文バグも発見・
     修正**——実機1件の`Text`属性が`"{}{{LINE_ITEMS}}"`(先頭`{}`は
     XAML標準のマークアップ拡張エスケープ接頭辞、実際の値は
     `{{LINE_ITEMS}}`のみ)で、既存の`_parse_expr`がこれを認識せず
     誤った文字列を捕捉していた——活動固有ではない汎用的な構文解析
     バグのため`_parse_expr`自身を修正(知見244・258に続く3件目の
     「独立検証で既存の一般的なバグを発見」事例)、既存テスト全件が
     そのまま通過することを確認。`Text`で検索した段落の直後に
     `python-docx`で構築したテーブルを`addnext()`(標準的なOXML
     要素移動イディオム)で挿入、`Position="Replace"`では元の段落を
     削除。実際の`.docx`で両`Position`モードを`exec()`経由で確認。
     回帰テスト追加(`tests/test_uipath_dsl.py`2件・`tests/
     test_uipath_codegen.py`8件)、リポジトリ全体で全2374件通過
     (本活動の10件分の純増)。残るWord classic(`WordReplacePicture`)
     ・マウスキーボード系(`ui:GetActiveWindow`等)の候補は次のティック
     で継続実装。

220. **(完了、2026-11-10)** `ui:SelectMultipleItems`を新規実装
     (知見262)——タグ名限定検索で11件ヒット。先に調査した
     `ui:GetActiveWindow`(20件ヒット)は実機2件とも`uix:`Modern UI
     Automation/未確認の`Saved.Values`機構と不可分と判明し見送った
     (`GetFileInfoX`/`ui:Pick`と同じ判断)。`SelectItemNode`
     (知見112)の複数選択版——`MultipleItems`(VB配列リテラル、
     `JoinPDFNode`知見201と同じ`ArrayLiteral`→`list`変換)の各要素に
     対して`SelectItemNode`と同じ`pywinauto`の汎用`.select()`
     アクセサを順に呼ぶ。`AddToSelection`(既存選択への追加/先に
     クリアを制御、未設定時の既定挙動が公式ドキュメント未記載)は
     明示的に設定されている場合`# TODO`へ倒す。複数回の`.select()`
     呼び出しが累積するか置き換えるかも未確認の近似として警告
     コメントへ明示。実在する独立著者が実質2名のみという薄い証拠を
     正直に記録。回帰テスト追加(`tests/test_uipath_dsl.py`1件・
     `tests/test_uipath_codegen.py`8件)、リポジトリ全体で全2383件
     通過(本活動の9件分の純増)。残るWord classic
     (`WordReplacePicture`)の候補は次のティックで継続実装、
     マウスキーボード系は知見255の候補が尽きたため新規発見パスが
     必要。

221. **(完了、2026-11-10)** `ui:WordReplacePicture`を新規実装
     (知見263)——タグ名限定検索で25件ヒット、知見256以来のExcel/
     Word classic系調査パスの最後の既知候補。`PictureAltText`/
     `PicturePath`の2属性のみ(他の共通属性は実機3件とも現れず)。
     公式ドキュメント確認済み:「一致するすべての画像を置換」
     「大文字小文字を区別しない」。`python-docx`にはAlt Text検索/
     画像置換の高レベルAPIが無いため、OOXMLの`<wp:docPr descr>`→
     `<pic:blipFill><a:blip r:embed>`という低レベル構造を直接操作
     する標準的なイディオム(画像パーツの`._blob`直接上書き)を
     新規注入ヘルパー関数`_word_replace_picture()`として実装。実際の
     画像ファイル2枚・`.docx`で`exec()`経由の大文字小文字不区別
     マッチ+バイト列置換を確認。回帰テスト追加(`tests/
     test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`3件)、
     リポジトリ全体で全2388件通過(本活動の5件分の純増)。
     知見256以来のExcel/Word classic系調査パスの既知候補はこれで
     全完了・見送り判断済み——マウスキーボード系は候補が尽きたため
     継続には新規発見パスが必要。

222. **(完了、2026-11-10)** `ui:WaitUiElementAppear`を新規実装
     (知見264)——マウスキーボード系の2回目発見パスで発見、タグ名
     限定検索で746件ヒット(本調査史上最強クラスの実務需要信号)。
     `marcelocruzrpa/uipath-ai-skills`のUIAutomation ground-truthが
     Modern/CV記述子系ばかりで新規候補が得られず、ドメイン知識から
     候補名をブレインストーミングする手法に切り替えて発見。実機2件
     以上で`FoundElement`(常に`{x:Null}`、型付きオブジェクトリスク
     無し)・`WaitActive`/`WaitVisible`(`{x:Null}`/`"False"`確認済み、
     `"True"`は実機未確認だが意味論に不確実性が無いため両方対応)・
     `.Target.Selector`(既存の`ui:Target`構造を再利用)を確認。
     `pywinauto`の`WindowSpecification.wait(...)`(文字列条件+秒単位の
     `timeout`引数)が直接対応(`TimeoutMS`は実機全件未設定のため公式
     ドキュメント確認済みの既定30秒をハードコード)。回帰
     テスト追加(`tests/test_uipath_dsl.py`2件・`tests/
     test_uipath_codegen.py`6件)、リポジトリ全体で全2396件通過
     (本活動の8件分の純増)。調査エージェントは`ui:AnchorBase`
     (310件ヒット、`WaitUiElementAppear`をAnchorProviderとして使う
     スコープ活動)を次の候補として記録、`ui:ClickImage`/
     `ui:ClickText`(画像テンプレートマッチング方式、アーキテクチャ
     不一致で見送り)・`ui:DragDrop`(54件だが全て無関係なWPF、新規
     偽陽性)も確認・記録した。

223. **(完了、2026-11-10)** `ui:ReadPDFWithOCR`を新規実装(知見266)
     ——Excel/Word/マウスキーボード網羅性向上の調査パス完了を受け、
     10回目発見パス最後の未着手候補(PDF+OCR系)へ復帰。タグ名限定
     検索で273件ヒット。`GetOcrTextNode`(知見180)と全く同じ
     `OCREngine`/`ActivityFunc`デリゲート構造を再利用——実機6件中
     4件が`GoogleOCR`(Tesseract、知見180確認済みマッピング)、
     2件が`MicrosoftOCR`(知見180で既に別エンジンと確認済み、
     `GetOcrTextNode`と同じ決定境界で未対応)。`Range`は実機確認
     できた`"All"`・単一ページ番号の静的リテラルのみ対応
     (公式ドキュメントのハイフン範囲/複合範囲は実機未確認のため
     `# TODO`)。`pymupdf`(知見209確認済みの`pdf-render`プラグイン)
     の`Pixmap.pil_image()`で各ページをラスタライズし
     `pytesseract.image_to_string()`へ渡す——複数ページは`"\n"`で
     連結(本トランスパイラ独自の推定と明記)。`tesseract`バイナリ
     自体は本サンドボックスに無いため`pytesseract`はモックしたが、
     `pymupdf`側のページ選択/ラスタライズ処理は実際の`.pdf`ファイルで
     `exec()`経由の本物の動作確認を行った(`GetOcrTextNode`自身より
     一段深い検証)。回帰テスト追加(`tests/test_uipath_dsl.py`2件・
     `tests/test_uipath_codegen.py`8件)、リポジトリ全体で全2406件
     通過(本活動の10件分の純増)。10回目発見パスの全候補のうち
     `InvokeVBA`(ライブExcel COM注入が必要、高リスク)のみが残る
     最後の候補。

224. **(完了、2026-11-10)** `ui:ReadColumn`/`ui:ReadRow`を新規実装
     (知見268)——discovery-fresh-pass-8(両バックログ完結を受けて
     起動した無制限8回目発見パス)の最上位推奨候補。タグ名限定検索で
     それぞれ12件/11件ヒット、10件以上の独立リポジトリに分散。
     `ReadRangeNode`/`ReadCellNode`(知見256/259)と同じスコープ無し
     "Workbook"系ファミリーだが、`StartingCell`から1方向(下/右)へ
     最初の空セルまで読む挙動には`openpyxl`の`Cell.offset(row=1)`/
     `Cell.offset(column=1)`APIを使い、セル座標の文字列解析を自前で
     行わずに動的`StartingCell`にも対応できる形に一般化
     (`_generate_read_column_or_row_body`)。回帰テスト追加
     (`tests/test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`
     10件)、リポジトリ全体で全2418件通過(本活動の12件分の純増)。

225. **(完了、2026-11-10)** `ui:GetPOP3MailMessages`を新規実装
     (知見269)——discovery-fresh-pass-8の次点推奨候補。タグ名限定
     検索で14件ヒット。`GetIMAPMailMessagesNode`(知見250)のPOP3版だが、
     POP3にはフォルダ/未読フラグ/日付ソートが無い。実機3件とも
     `EnableSSL="False"`+`SecureConnection="Auto"`+`Port="995"`という
     一見矛盾する組み合わせでGmail(SSL必須)に動作しており、公式
     ドキュメント確認の上で実際の接続セキュリティは`SecureConnection`
     側が制御すると判断し常に`poplib.POP3_SSL`で実装。下流アクセスが
     `GetIMAPMailMessages`と同一パターンのため既存の`_ImapMailMessage`
     ラッパーをそのまま再利用(新規ラッパー不要)。回帰テスト追加
     (`tests/test_uipath_dsl.py`2件・`tests/test_uipath_codegen.py`
     7件)、リポジトリ全体で全2427件通過(本活動の9件分の純増)。

226. **(完了、2026-11-10)** `ParallelForEach`を新規実装(知見270)——
     discovery-fresh-pass-8最後の有力候補、裸のcore WFタグ(`WF_NS`)。
     実機3件(公式`UiPath-Services/StudioTemplates`の
     `OrchestrationProcess`テンプレート×2・`mariokellner/
     UiPath-Parallel-Background-RE-Framework`)で構造を確認——
     `ForEachNode`(知見5・155)と完全に同一の`ActivityAction`+
     `DelegateInArgument`構造だが意味論(並行実行)が異なるため、
     `ParallelNode`(知見19・20)の「逐次実行+誠実な`# NOTE`コメント」
     前例を継承した別ノード型`ParallelForEachNode`として実装
     (`ForEachNode`と同型にすると近似コメントを出す判定ができない
     ため)。回帰テスト追加(`tests/test_uipath_dsl.py`2件・
     `tests/test_uipath_codegen.py`2件)、リポジトリ全体で全2431件
     通過(本活動の4件分の純増)。discovery-fresh-pass-8の全候補が
     これで完結。

227. **(完了、2026-11-10)** `ui:StartTimer`/`ui:StopTimer`/
     `ui:ResetTimer`/`ui:ResumeTimer`を新規実装(知見271)——
     discovery-fresh-pass-9の最有力候補、4活動を一括実装。公式
     ground-truth+実機2件で`Timer`属性1個のみの構成、下流アクセス
     (`.Elapsed.TotalSeconds`/`.ElapsedMilliseconds`)を確認。公式
     ドキュメント+フォーラムで`System.Diagnostics.Stopwatch`への
     1:1対応(`StartTimer`=`Restart()`、`StopTimer`=`Stop()`、
     `ResetTimer`=`Reset()`、`ResumeTimer`=停止中への`Start()`)を
     確認し、`_ImapMailMessage`と同じ設計判断で薄いラッパー`_Timer`
     /`_TimeSpan`として実装。`render.py`の既存の汎用メンバーアクセス
     機構(未知セグメントの素通し)がPascalCase属性名をそのまま通す
     ため、`render.py`側の変更は一切不要だった。回帰テスト追加
     (`tests/test_uipath_dsl.py`4件・`tests/test_uipath_codegen.py`
     3件)、リポジトリ全体で全2438件通過(本活動の7件分の純増)。
