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
- `Switch`のdefaultアームの実XAML形は未確認(知見9の実例は単一アーム
  `x:Key="1"`のみ)
- Modern活動のFuzzy/Strict selector(知見37)は未対応(そもそもXAML形が
  未確認)

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

1. **Modern活動のFuzzy/Strict selector実XAML確認**(VM要、ただし新Studio
   問題とは独立): 旧Studio(2021.4.4)でModern UI Automation活動
   (`Set Selected Item`等)を1つ置いてXAMLを確認する。新Studio問題の
   解消を待たずに着手できる可能性がある——ただしVMは他セッションと共用
   のため、使用タイミングの調整が必要
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
