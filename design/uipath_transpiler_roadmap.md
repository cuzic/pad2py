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

## 次にやること

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
