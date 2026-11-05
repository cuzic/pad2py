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
  関数名の衝突(同じ`class_name`を持つ複数ファイル)は`_2`サフィックスで
  機械的に回避するだけで、意味のある別名付けはしていない。
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
  リテラルとして出力するよう`uipath_codegen`側で補正している
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
