# 複数トレースからの制御フロー推測・一般化(Programming by Demonstration / Program Synthesis / Process Mining)

## Q1. PBD研究におけるWeb/GUIマクロの複数実例からの一般化・ループ推測システム(CoScripter, Vegemite, Rousillon, Helena/Ringer等)

### Takeaway
PBDの系譜では「繰り返しパターンの検出→ループ変数(反復ごとに変わる値)の特定→終了条件の推測」という3段構成が古くから認識されており(Cypherの Eager, 1991年の *Watch What I Do* 所収)、Berkeleyの Ringer→Rousillon→Helena の一連の研究(2016–2018年)がこの考え方をWebスクレイピング/Web自動化に最も具体的に適用している。CoScripterは自然言語風スクリプトの記録・共有に主眼があり、ループの自動推測機能自体は確認できなかった。Vegemiteも同様にCoScripterを拡張したスプレッドシート型マッシュアップツールであり、ループ構造の詳細は文献から確認できなかった(Gap参照)。

### Cited Findings
- Allen Cypherの Eager(1991年、*Watch What I Do* 第9章)は、PBDにおけるループ仕様の問題に初めて取り組んだシステムの一つ。繰り返しパターンを検出する手法として「2つの類似イベントが見つかったら、2番目のイベントが2回目の反復の開始とみなす」というヒューリスティックを採用している。ループは「集合反復(set iteration)」「カウンタ付き反復」「条件成立までの反復(iteration until a condition is satisfied)」の3種に分類される — [Watch What I Do Ch.9](https://acypher.com/wwid/Chapters/Chapter09Intro.html)
- Lau & Weld (IUI 1999) は、実行トレースからプログラムへの一般化には「ループの長さを決定すること」「各反復で規則的に変化する部分に気づくこと」が必要だと整理し、既存のPBDシステムはいずれも一般化の妥当性判断にヒューリスティックなルールに依存しており、それが脆さの原因だと指摘している — [Lau & Weld, IUI 1999 PDF](https://homes.cs.washington.edu/~weld/papers/pbd-iui99.pdf)
- Tessa Lau の2001年博士論文は、PBDを機械学習問題として再定式化し、実行トレースからループと条件分岐を含むプログラムを学習する手法へPBDを一般化している — [UW Lau 2001 thesis](https://digital.lib.washington.edu/researchworks/items/5a0c4fd8-daa4-4043-8837-fcc2171f9970/full)
- CoScripter(IBM Research、Allen Cypherらが関与)は、ユーザー操作を記録し半自然言語のスクリプトとして保存するブラウザマクロレコーダー(現在は終了)。PBDに基づくが、検索結果からは複数デモンストレーションからの自動ループ一般化機能は確認できなかった — [CoScripter (Wikipedia)](https://en.wikipedia.org/wiki/CoScripter), [Mozilla Labs紹介](https://blog.mozilla.org/labs/2007/09/coscripter/)
- Vegemite(Lin, Wong, Nichols, Cypher, Lau; IUI 2009, "End-user programming of mashups with vegemite")は、CoScripterをスプレッドシート型UIで拡張し、複数Webサイトから収集した情報を表に自動入力するPBD/直接操作ハイブリッドツール — [Vegemite IUI2009 PDF](https://jameslin.name/research/vegemite/iui2009/vegemite-iui2009.pdf)
- Ringer(Barman, Gulwani, Bodík; OOPSLA 2016, "Web Automation by Demonstration")は、ユーザーの1回のデモンストレーションを「ユーザーがページを操作するように」振る舞うスクリプトへ変換する記録・再生システム。頑健性のため、スクリプトを複数回再生して各アクションの実行前に成立すべき条件である「トリガー(trigger)」を推論する。さらに類似度に基づくノードアドレッシング手法でページ変更後も要素を再特定する。34件のベンチマークで CoScripter が18%(6件)成功に対し Ringer は74%(25件)成功したと報告 — [Ringer OOPSLA16 PDF](https://microsoft.com/en-us/research/wp-content/uploads/2016/12/oopsla16-web.pdf), [Barman 2015 dissertation EECS-2015-266](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2015/EECS-2015-266.pdf)
- Rousillon(Chasins et al.)は、Ringerをビルディングブロックとして使い、Ringerが記録した「ストレートライン(分岐・ループなし)」のデモンストレーションを一般化して、ループを含む高レベルな Helena プログラムへ変換する。ユーザーは収集したいデータの種類ごとに1つの例を与えれば、システムがそれを一般化する(例: 階層的・分散的なWebデータの最初の1行をデモすれば、残り数百〜数千行を収集するプログラムを生成) — [Helena/Rousillon project](https://helena-lang.org), [schasins/helena GitHub](https://github.com/schasins/helena), [関連論文での言及(ScrapeViz, par.nsf.gov)](https://par.nsf.gov/servlets/purl/10358525)
- Helenaは研究プロトタイプの位置づけであり(Chrome Web Store上でも "still a research prototype!" と明記)、Webページの再デザインや難読化に対してスクリプトを頑健にする「適応型リプレイヤー(adaptive replayer)」を持つ — [Chrome Web Store: Helena Scraper and Automator](https://chromewebstore.google.com/detail/helena-scraper-and-automa/jdejblmbpjeejmmkekfclmhlhohnhcbe), [2018 Rising Stars紹介](https://risingstars18-eecs.mit.edu/?p=519)
- WebRobot(arXiv 2203.09993, 2022年)は、Webに対するRPAのための対話的PBDシンセサイザー。記録されたブラウザ操作とDOMトレースからプログラムを学習し、「プログラムPがトレースAを一般化する」ことを形式的に定義した上で、rewrite-based program synthesis(egg等のequality saturationで知られる手法群)の文脈で新規の「speculate-and-validate」方式を提案。76件のベンチマークで egg 実装のベースラインより優れた結果を報告 — [WebRobot arXiv PDF](https://arxiv.org/pdf/2203.09993)
- Nevill-Manning & Witten の SEQUITUR は、系列中の繰り返しフレーズを検出し規則に置き換える文法帰納(grammar induction)アルゴリズムで、「ループや分岐のようなプログラミング構成要素の推論」や「文法規則の統一による一般化」「手続き的な部分構造の検出」を目的の一つとして挙げている。隣接する記号対が2回以上現れない(digram uniqueness)・規則は2回以上使われる(rule utility)という2つの不変条件で動作する — [Detecting sequential structure (Waikato)](https://researchcommons.waikato.ac.nz/entities/publication/cab77a80-cb57-42fd-8daa-67fae63dd157)
- RecurBot(Intharah, Firman, Brostow; CHI 2018 Extended Abstracts)は、少数のデモンストレーションから学習し残りのステップを予測・実行するGUIタスク自動化システム。先行研究のHILC(Help, It Looks Confusing; IUI 2017)では、ループの開始・終了をユーザーが特定のキー操作で明示的にマークする設計であり、システム側がループ境界を自動推測するわけではない — [RecurBot (UCL)](https://discovery.ucl.ac.uk/id/eprint/10088947/), [HILC arXiv 1611.03906](https://arxiv.org/pdf/1611.03906)

### Inferences
- PAD(Power Automate Desktop)の「ページ送りをページごとに個別記録したフロー」を複数トレースとして与える今回のシナリオは、Rousillonが扱う「複数の似た操作列から1つのHelenaループプログラムを合成する」問題と構造的に最も近い。Rousillonの手がかり(各トレースの対応するDOM/UI要素を比較し、変化する部分=ループ変数、変化しない操作列=ループ本体とする発想)は、PAD複数フローの比較にも応用できる可能性が高い。
- しかし、Eager以来一貫して「ループ検出・終了条件推測はヒューリスティックで脆い」という課題が指摘されており(Lau & Weld 1999)、HILCやRecurBotのように最終的にユーザーに境界を明示させる設計に回帰する例も多い。これは本プロジェクトでも「複数回ページ送りを記録させる」という設計(=ユーザーに暗黙的に反復回数のサンプルを与えさせる)が、完全自動検出の難しさを回避する実務的な妥協点になりうることを示唆する。

### Gaps
- Vegemiteの具体的なループ構文・ループ変数推測メカニズムの詳細(IUI 2009論文本文)は検索結果の要約からは確認できなかった。原論文PDFの本文を直接精読する必要がある。
- Rousillonの原論文(CHI 2018, "Rousillon: Scraping Distributed Hierarchical Web Data")の本文(特にアルゴリズムの節)は検索・フェッチで本文を取得できず(404および関連論文からの間接引用のみ)、ループ本体検出・終了条件推測の正確な技術的詳細(例:DOM木のどの階層をイテレーション単位とするか、次ページ存在判定のロジック)は未確認。ACM Digital Library等での追加調査が必要。
- CoScripterが複数デモンストレーションからの自動ループ一般化機能を持つかどうかは、調査した範囲では確認できなかった(記録・共有・自然言語化が主機能という情報のみ)。

## Q2. Microsoft PROSE framework の複数入出力例からのプログラム合成の仕組み、RPA/デスクトップ自動化トレースへの適用事例

### Takeaway
PROSE(Program Synthesis using Examples)は「DSL + 入出力例」からその例と整合するDSLプログラムをランキング付きで合成する汎用フレームワークであり、FlashFill(Excel)が最も有名な実例だが、調査した範囲ではRPA/デスクトップ自動化トレースへの直接適用事例は確認できなかった。2025年10月時点でMicrosoftはPROSE SDKの新バージョンリリースを停止している。

### Cited Findings
- PROSEは、タスクに合わせて定義したDSL(domain-specific language)と、望ましいプログラムの挙動を示す入出力例を与えると、その例と整合するDSLプログラム群をランキング付きで合成する — [Microsoft Research PROSE page](https://microsoft.com/en-us/research/?p=654579), [microsoft/prose GitHub](https://github.com/microsoft/prose)
- PROSE SDKはNuGetパッケージ群(Microsoft.ProgramSynthesis.Common, Microsoft.ProgramSynthesis.Compiler等)として配布され、必要なパッケージのみ個別にインストール可能。最新バージョンは10.16.5 — [NuGet: Microsoft.ProgramSynthesis.Compiler](https://www.nuget.org/packages/Microsoft.ProgramSynthesis.Compiler/)
- GitHubリポジトリの記載によれば、2025年10月14日時点でPROSE SDKの新バージョンのリリースは停止されている。ライセンスは非商用利用限定で、SDK自体はクローズドソース(利用サンプルコードのみ公開) — [microsoft/prose GitHub](https://github.com/microsoft/prose)
- PROSEのデータラングリングライブラリは、最初 Excel 2013 の FlashFill 機能として実装された — [Microsoft Research PROSE page](https://microsoft.com/en-us/research/?p=654579)

### Inferences
- PROSEはFlashFillのような「文字列変換」「表形式データ抽出」寄りの応用に強みがあり、ループ・分岐を含む手続き的なGUI操作フロー全体を複数トレースから合成する用途への直接適用例は、少なくとも本調査で見つかった公開情報の範囲では存在しない。RPAトレース一般化への応用は、PROSEそのものよりも後述のWebRobot(rewrite-based synthesis)やSmartRPA(process mining的トレースアラインメント)のような専用手法が実際に使われている。

### Gaps
- PROSEがRPA/デスクトップ自動化のトレースに適用された学術研究・事例は検索で見つけられなかった。これは「存在しない」ことの確証ではなく、検索で確認できなかったという留保付きの結論である。PROSE SDKが非商用限定かつ2025年10月でリリース停止となっている点から、現在進行中の新規RPA応用研究は少ないと推測されるが、これも推測の域を出ない。
- PROSEの内部アルゴリズム(witness function, version space algebra等の合成アルゴリズムの詳細)は、今回の検索では公式ページ・GitHub概要の記載に留まり、技術的詳細(論文本文)までは深掘りできていない。

## Q3. プロセスマイニング(Alpha algorithm, Heuristics Miner, Inductive Miner等)による複数イベントログからのループ・分岐を含む制御フローモデル発見、RPAフロー統合への応用可能性

### Takeaway
プロセスマイニングの古典的3アルゴリズム(Alpha, Heuristics Miner, Inductive Miner)はいずれも「多数のケース(トレース)」を前提に、直接継起関係の統計(頻度・比率)からループを含む制御フローモデルを発見するが、Alpha algorithmは短いループ(長さ1・2)を原理的に扱えないという既知の欠陥があり、Heuristics MinerとInductive Minerはそれぞれ閾値付きヒューリスティックや再帰的divide-and-conquerでこれを補っている。RPA分野では、これらの考え方は「UIログを複数のルーティン(繰り返しタスク)に分割し、そこから実行可能なRPAスクリプトを合成する」研究(SmartRPA等)に直接応用されている。

### Cited Findings
- Alpha algorithmは、イベントログから「直接継起(direct succession)」「因果(causality)」「並行(parallel)」「選択(choice)」の4つの関係を抽出し、footprint matrixに記録して、それを基にPetriネットを構成する — [Alpha algorithm (Wikipedia)](https://en.wikipedia.org/wiki/Alpha_algorithm)
- Alpha algorithmは「長さ1のループ」「長さ2のループ」「不可視タスク」「重複タスク」「非フリーチョイス構造」がある場合に正しく機能しないという既知の限界があり、これを補うAlpha+、Alpha++などの拡張が提案されている — [Alpha algorithm (Wikipedia)](https://en.wikipedia.org/wiki/Alpha_algorithm)
- Heuristics Minerは、長さ1のセルフループを a⇒a = |a>a| / (|a>a|+1) という比率が「length-one loop threshold」を超えた場合に追加し、長さ2のループは a⇒b = (|a>b|+|b>a|) / (|a>b|+|b>a|+1) という比率が別の閾値を超えた場合に追加する。ProM実装での依存関係閾値(dependency threshold)のデフォルトは0.9、PM4Pyのデフォルトは0.5など、ツールによりデフォルト値が異なる — [Heuristics Miners for Streaming Event Data](https://arxiv.org/pdf/1212.6383), [bupaverse heuristicsmineR docs](https://bupaverse.r-universe.dev/heuristicsmineR/heuristicsmineR.pdf)
- 2014年の研究は、ProM 6.2版のHeuristics Minerが長さ1・長さ2の短いループに対する依存関係ヒューリスティックの品質が低いと報告し、妥当性・完全性を改善した改良版を提案している — [Improving the quality of the Heuristics Miner in ProM 6.2](https://www.datalearner.com/academic/journal-papers/0957-4174/volumes-and-issues/223/paper-detail/84897)
- Inductive Minerは、ログを再帰的に分割するdivide-and-conquer方式でプロセス木(process tree)を構築する。プロセス木の内部ノードはsequence・choice・parallel・loopなどのオペレータで、葉がアクティビティであり、Inductive Minerは健全(sound)なプロセスモデルの発見を保証する。発見されたプロセス木はPetriネットに変換できる — [Process Discovery using Inductive Miner and Decomposition](https://arxiv.org/pdf/1610.07989)
- PM4Pyでは discover_petri_net_inductive としてノイズ閾値(noise threshold)パラメータ付きで実装されている。2024年の比較研究では、Alpha/Heuristics/ILP/Inductive Minerをloop-in-loop(ループ内ループ)、XOR-in-loopなどのネストしたループ構造で比較しており、Inductive Minerが生成するPetriネットには多数の隠れ遷移(hidden transitions)が含まれ、ログのunderfittingを招く可能性があると報告されている — [process-discovery (tessl.io pm4py docs)](https://tessl.io/registry/tessl/pypi-pm4py/2.7.0/files/docs/process-discovery.md)
- RPAへのプロセスマイニング応用の系統的文献レビュー(arXiv 2204.00751、2022年提出・2023年改訂)は、UiPath, Celonis, myInvenioなどのベンダーが「task mining」という用語でUIデータに基づくプロセスマイニングを採用していると指摘。UiPath Process MiningやDisco、ProM、Celonis等の商用PMツールがRPA候補プロセスの発見(as-is process discovery、ループ箇所の可視化を含む)に使われた事例を複数報告している(例: Disco生成のas-isプロセス図で"Final check of invoice"等の箇所にループが可視化された事例) — [Robotic Process Automation Using Process Mining: A Systematic Literature Review (arXiv 2204.00751)](https://arxiv.org/pdf/2204.00751)
- 同レビューは、SmartRPAのアプローチを「(1)頻出パターン識別技術でUIログからルーティンを自動導出、(2)人間参加型(human-in-the-loop)インタラクションで実世界のルーティン実行にそぐわないセグメントを除外、(3)プロセスマイニングにおけるトレースアラインメント技術で特定ルーティンセグメントに属するユーザー操作を適切に区切られたルーティントレースへクラスタリング」の3段構成として整理している — [同上 arXiv 2204.00751]

### Inferences
- Alpha algorithmが「短いループを扱えない」という欠陥は、PADのページ送りフロー(1〜2種類の操作が繰り返される典型的な短いループ)にとって本質的な障害になりうる。実務応用にはHeuristics MinerやInductive Minerのような短ループ対応拡張が前提となる。
- プロセスマイニングの制御フロー発見アルゴリズムは「多数のケース(同種プロセスの多数回実行ログ)」を前提に統計的頻度でモデルを導出するものであり、本プロジェクトのように「少数(おそらく数本〜十数本)のPADフロートレース」からループを再構成する問題とは、入力の規模・性質が異なる。したがって直接の適用ではなく、「トレースアラインメント」や「頻出パターン識別」といった個別技術コンポーネントの借用(SmartRPAが採用したアプローチ)が現実的と考えられる。

### Gaps
- Inductive Minerが「隠れ遷移を多数生成しうる」ことの一次資料(原論文)での詳細な記述は未確認(二次資料経由の情報)。
- Alpha algorithmの「ステップ5」(footprint matrixからPetriネット構造を導出する具体的な手順)について、ステップバイステップの一次資料説明は本調査では得られなかった(ProMフォーラムの質問スレッドは未回答だった)。van der Aalst, Weijters, Maruster (IEEE TKDE, 2004)の原論文を直接確認する必要がある。

## Q4. 既存RPAベンダー(UiPath, Power Automate, Automation Anywhere)における複数回記録からの自動ループ/パターン検出機能の有無

### Takeaway
調査した範囲では、UiPath・Power Automate・Automation Anywhereのいずれにも「複数回の記録を比較して自動的にループを検出・生成する」機能は確認できなかった。UiPathのTask Captureは「単一キャプチャ内の類似スクリーンショットのマージ」機能を持ち、Task Miningは「繰り返しタスクの自動識別」を行うが、これらは複数の個別記録を1つのループ構造へ統合する機能とは異なる。実務上の標準的パターンは、ユーザーが手動でWhileループ/Do-Whileループを構築し、「Next」ボタンの存在確認(Element Exists)などを終了条件として明示的に設定するというものである。

### Cited Findings
- UiPath Task Captureの公式ドキュメントは、「キャプチャ内で類似のスクリーンショットを検出し、自動または確認を経てマージする」機能を記載している。これは単一の記録(キャプチャ)内の重複アクションを統合するものであり、複数の別個の記録をループへ統合する機能ではない — [UiPath Task Capture docs](https://docs.uipath.com/task-capture/docs/capture-process)
- UiPathコミュニティフォーラムでは、既に記録済みのアクティビティ群をWhileループ/Do-Whileループの中に配置し、停止条件を自分で指定するという手動パターンが一般的な解決策として提示されている — [UiPath forum: how to paginate/loop through browser pages](https://forum.uipath.com/t/how-to-paginate-loop-through-browser-pages/729169)
- ページネーションに関する別フォーラムスレッドでは、「Next」ボタンをクリックするループを組み、ボタンが無効化されている(見つからない)ことをElement ExistsやFind Elementで検出して終了条件とする、という実装パターンが提示されている。あるユーザーは、最終ページでNextボタンが存在しない場合の誤動作を避けるため、For EachよりWhileループの方が信頼性が高いと報告している — [UiPath forum: Table Extraction Next Page Problem](https://forum.uipath.com/t/512751)
- UiPath Task Miningは「従業員のワークフローを自動識別し、自動化可能な繰り返しタスクを識別する」機能を持つ(プロセス発見/タスクマイニングの文脈) — [RPA process mining systematic review (arXiv 2204.00751)](https://arxiv.org/pdf/2204.00751)
- 系統的文献レビュー(arXiv 2204.00751)は、Celonis, UiPath, myInvenio等の商用ベンダーが「task mining」という用語でUIレベルのデータに基づくプロセスマイニングを採用していると述べているが、これは「どのタスクが自動化候補か」を発見するためのものであり、個々のRPAフロー内のループ構造を複数記録から自動構築する機能ではない — [同上]

### Inferences
- 商用RPAベンダーのロードマップは「どの業務プロセスを自動化すべきか(as-isプロセス発見)」や「単一記録内の重複操作のマージ」に向けた機能提供が中心であり、「複数の個別デモンストレーション(例:ページごとに別々に記録したページ送り操作)を比較して1つの一般化されたループフローに統合する」機能は、少なくとも主要ベンダーの標準機能としては確認できず、研究プロトタイプ(Rousillon, WebRobot, SmartRPA等)の領域に留まっていると考えられる。これは本プロジェクトが取り組む課題が、既存ベンダー機能のギャップを埋める研究的な位置づけにあることを示唆する。

### Gaps
- Automation AnywhereおよびMicrosoft Power Automate (Desktop)について、UiPath同様の具体的なフォーラム議論・ドキュメントは本調査では十分に検索できなかった。特にPower Automate Desktop自体のループ関連機能(例:UI要素の存在確認アクションを使った終端条件設定のベストプラクティス)について、Microsoft公式ドキュメントへの直接的な言及は本ノートには含められていない。追加調査が必要。
- 「UiPathのSmart Loop的機能」という問いに対して、UiPath製品内にそのような名称・機能が存在するかどうかは本調査では確認できなかった(検索結果からは確認も否定もできない)。

## Q5. 複数アクションシーケンス比較による(a)ループ本体検出(b)ループ変数特定(c)終了条件推測のための実用的アルゴリズム・ヒューリスティック

### Takeaway
実用的なアプローチとしては、(1) Eager型の「隣接する類似イベントのペアマッチング」ヒューリスティック、(2) Sequitur/REPAIR/LONGESTFIRSTのような文法帰納(grammar induction)による繰り返し部分列の検出、(3) プロセスマイニングの「頻出パターン識別+トレースアラインメント」(SmartRPAが採用)、(4) rewrite-based program synthesisの「speculate-and-validate」(WebRobot)という4系統が確認された。ループ変数の特定は多くのシステムで「反復間で変化するDOM要素・パラメータ値の差分」として扱われ、終了条件の推測は最も難しい部分であり、多くのシステムが最終的にユーザーによる明示的指定(トリガー検証や手動境界マーキング)に依存している。

### Cited Findings
- Eager(Cypher)は、2つの類似イベントが系列中に見つかった場合、2番目のイベントを2回目の反復の開始とみなすという単純なペアマッチングヒューリスティックでループ(繰り返しパターン)を検出する — [Watch What I Do Ch.9](https://acypher.com/wwid/Chapters/Chapter09Intro.html)
- SEQUITURは「隣接記号対の重複禁止(digram uniqueness)」と「規則は2回以上使用されること(rule utility)」という2つの不変条件に基づき、系列中の繰り返しフレーズを検出して文法規則に置き換える。音楽セグメンテーション研究では、頻度優先のREPAIRや、より長い繰り返し部分列を優先するLONGESTFIRSTといった代替手法とも比較されている — [Detecting sequential structure (Waikato)](https://researchcommons.waikato.ac.nz/entities/publication/cab77a80-cb57-42fd-8daa-67fae63dd157)
- SmartRPA(Agostinelli et al., 博士論文2023年のExtended Abstract, BPM 2023 Best Dissertation Award)は、未分割のUIログから実行可能なRPAスクリプトを生成する3段パイプラインを提示している: (i) アドホックにカスタマイズした頻出パターン識別技術(frequent-pattern identification technique)でUIログから繰り返しパターンとしてのルーティンセグメントを導出、(ii) 宣言的制約(declarative constraints)を用いた人間参加型(human-in-the-loop)インタラクションで、実世界のルーティン実行にそぐわない誤検出セグメントを除外、(iii) プロセスマイニングにおけるトレースアラインメント技術を用いて、特定のルーティンセグメントに属する全ユーザー操作を適切に区切られた「ルーティントレース」へクラスタリング。この手法は「ルーティンを終了させるユーザー操作の直後にダミーのend-delimiter(終端区切りアクション)を注入する」という事前知識(semi-supervised、a-prioriに終端区切りを知っている前提)に依存している — [Generating Executable RPA Scripts from Unsegmented UI Logs (Agostinelli, CEUR-WS Vol-3469)](https://ceur-ws.org/Vol-3469/paper-01.pdf)
- SmartRPAはさらに、ルーティン実行中にユーザー入力を要する「ルーティン変種(routine variants)」を検出する「variation point(ユーザーが複数の変種のいずれかを選ぶ分岐点)」の概念を導入し、観測された変種の組み合わせに応じてSWロボットをリアクティブに合成する(C2・C3の課題) — [同上]
- 同論文は、SmartRPAの主な弱点は「実世界UIログの情報品質」に起因し、多様な戦略で実行されたルーティンがセグメント識別に影響を与える可能性があると明記している。さらに「本手法は半教師あり(semi-supervised)の仮定に基づく。ルーティン実行を終了させる各ユーザー操作に付随するend-delimiterを事前に知っているという前提があるため」と限界を明記している — [同上]
- WebRobot(arXiv 2203.09993)は、プログラムPがデモンストレーショントレースAを「一般化する」ことを形式的に定義し(Pがトレースの厳密な前方部分列と整合しつつ、それを超えて動作を拡張できること)、rewrite-based program synthesisの文脈で「speculate-and-validate」という新手法を提案している。これはequality saturation(eggライブラリ)ベースの従来手法よりも76件のベンチマークで優れた結果を示した — [WebRobot arXiv PDF](https://arxiv.org/pdf/2203.09993)
- Ringer(Barman, Gulwani, Bodík; OOPSLA 2016)は、スクリプトを複数回再生(replay)することで各アクション実行前に満たすべき条件である「トリガー」を推論する。これは終了条件そのものではないが、「複数回の実行(トレース)を比較して条件を推論する」という本質的に同種のヒューリスティックである — [Ringer OOPSLA16 PDF](https://microsoft.com/en-us/research/wp-content/uploads/2016/12/oopsla16-web.pdf)
- HILC(Help, It Looks Confusing; Intharah, Firman, Brostow, IUI 2017)は、ループの開始・終了を指導者(ユーザー)が特定のキー操作で明示的にマークし、3回目の信号の直後にスクリプトを完了させるという設計であり、終了条件の「推測」ではなく「ユーザーによる明示」に依存している — [HILC arXiv 1611.03906](https://arxiv.org/pdf/1611.03906)
- Lau & Weld (IUI 1999) は、ループ長の決定と反復ごとの規則的変化の検出がPBDの一般化における中核課題であると位置づけている — [Lau & Weld, IUI 1999 PDF](https://homes.cs.washington.edu/~weld/papers/pbd-iui99.pdf)
- UiPathコミュニティの実務的パターンでは、「Next」ボタンが無効・非存在であることをElement Exists/Find Elementで検出して終了条件とするのが一般的解法として提示されている(ただしこれは人間が設計するものであり、自動推測ではない) — [UiPath forum](https://forum.uipath.com/t/512751)

### Inferences
- 「シーケンスアラインメント/diffアルゴリズム」という観点では、本調査で直接「LCSやMyers diffでPADトレースをアラインしてループ変数を抽出する」という具体的先行研究は見つからなかったが、構造的に等価な役割を果たしているのがSmartRPAの「トレースアラインメント(プロセスマイニング由来)」であり、これはプロセスマイニング分野で複数のトレースを位置合わせしてバリアント間の共通骨格と変動部分を区別する標準的技術である。PADの複数ページ送りトレースに対しても、各トレース(1ページ分の操作列)を行アラインメントし、「変化しない操作=ループ本体」「変化する値(例:クリック対象のページ番号、抽出したテキスト)=ループ変数」「最後のトレースにだけ存在する操作(例:Nextボタンが見つからない分岐)=終了条件のシグナル」という切り分けが実務的に有望な設計として浮かび上がる。
- 終了条件の推測は一貫して最も困難な部分として扱われており、多くの実用システム(HILC, UiPathの実務パターン)が「ユーザーに明示的マークさせる」「Element Existsのような明示的述語をユーザーが設定する」という方向に落ち着いている。これは本プロジェクトにおいても、終了条件(例:「次ページボタンが無効」「行がもうない」)の完全自動推測よりも、複数トレースの最後のトレースの差分(例:最後のトレースにだけ現れる「ボタンが見つからない」というエラー/分岐)をヒントとして提示し、人間に確認させる設計が妥当であることを示唆する。

### Gaps
- 「クラスタリング」を明示的な手法として使っている具体的な公開アルゴリズム(例:アクションシーケンスをベクトル化してk-meansやDBSCANでグルーピングする等)の先行研究は、本調査の検索範囲では確認できなかった。SmartRPAの「クラスタリング」は「トレースアラインメントによるグルーピング」であり、one-hotやembeddingベースの機械学習的クラスタリング手法の適用例は見つけられていない。
- PADの実際のアクション表現(UI要素セレクタ、変数名等)にSequitur的な文法帰納やdiffアルゴリズムを直接適用した先行事例は確認できなかった。これは本プロジェクト固有の新規性が存在する領域である可能性を示す。

## Q6. 複数トレースからの一般化は、どの程度「完全自動」が可能で、どこから人間の確認・修正が必要になるとされているか

### Takeaway
調査した文献は一貫して、複数トレースからの一般化の「完全自動化」には限界があり、(1) ループ候補の誤検出を除外するフィルタリング、(2) 終了条件やループ境界の最終確定、(3) UIログの質・多様性に起因するエラーの処理、の3点で人間の確認・修正(human-in-the-loop)が必要とされている。多くの研究システム自身が「semi-supervised」「人間参加型」であることを明示的に認めている。

### Cited Findings
- SmartRPA(Agostinelli, 2023年BPM Best Dissertation Award論文)は、パイプラインの中に明示的に「human-in-the-loop interaction to filter out those segments not allowed by any real-world routine execution(宣言的制約による誤検出セグメントの除外)」というステップを組み込んでおり、これは完全自動ではなく人間参加型のステップである — [Agostinelli, CEUR-WS Vol-3469](https://ceur-ws.org/Vol-3469/paper-01.pdf)
- 同論文は末尾の "Concluding Remarks" で、"our approach is based on a semi-supervised assumption, since we know a-priori the end-delimiters to be associated with any user action that ends a routine execution. On the other hand, the approach is not aware of the concrete behavior of the routines of interest, which will be discovered by the approach itself. For this reason, we consider this thesis an important step toward the development of a more complete and unsupervised approach."と明記しており、完全な教師なし自動化はまだ達成されておらず将来研究の方向性として位置づけている — [同上]
- 同論文は、手法の主な弱点が「実世界UIログに記録される情報の品質」に相関していると述べ、多様な実行戦略で実行されたルーティンがセグメント識別の正確性に影響しうると認めている — [同上]
- 系統的文献レビュー(arXiv 2204.00751)が整理するSmartRPAの3段ステップのうち、2番目は明確に「a human-in-loop interaction to filter out those segments not allowed by real-world routines under analysis」であり、これは業界レビュー論文でも一般的な整理として採用されている — [RPA process mining SLR (arXiv 2204.00751)](https://arxiv.org/pdf/2204.00751)
- RPAの従来型ライフサイクル(同レビューが引用するJimenez-Ramirez et al. CAiSE'19のフレームに基づく整理)では、「どの業務プロセスステップが自動化候補か」の判断や「フローチャート図のモデリング」は熟練した人間専門家の支援(インタビュー、ウォークスルー、詳細観察)に依存しており、SmartRPA等の研究はこの人間依存を軽減する方向を目指しているに過ぎず、完全に排除するものではない — [Agostinelli, CEUR-WS Vol-3469](https://ceur-ws.org/Vol-3469/paper-01.pdf)
- HILC(IUI 2017)やRecurBot系の研究は、ループの開始・終了をユーザーが明示的に信号(特定のキー操作)でマークする設計を採用しており、これは「終了条件はシステムが推測するのではなく人間が指定する」という設計判断そのものである — [HILC arXiv 1611.03906](https://arxiv.org/pdf/1611.03906)
- 実務者コミュニティ(futureofcoding forum、査読を経ていない非公式な議論)では、「ユーザーがコレクションに対するループであることを明示的に述べるべきで、システムが繰り返し行動を推測しようとするべきではない」という意見があり、推測コストが節約効果を上回るという実務的な懸念が表明されている(ただしこれは単一の意見であり、査読済み研究ではない点に留意) — [futureofcoding forum discussion](https://linen.futureofcoding.org/t/16056193/we-re-experimenting-with-a-novel-form-of-programming-by-exam)
- Lau & Weld (1999) は、既存のPBDシステムがいずれも一般化の妥当性判断にヒューリスティックなルールに依存していることを課題として指摘しており、これは「ヒューリスティックが外れるケースでは人間の介入が必要になる」ことを含意する — [Lau & Weld, IUI 1999 PDF](https://homes.cs.washington.edu/~weld/papers/pbd-iui99.pdf)

### Inferences
- 学術研究全体を通じて、「ループ本体の検出」(頻出パターン識別、文法帰納)は比較的自動化が進んでいる一方、「終了条件の確定」と「誤検出フィルタリング」は人間確認が必要な領域として一貫して残されている。本プロジェクトにおいても、PADの複数ページ送りトレースからループ本体・ループ変数までは比較的高い確度で自動推測できる可能性が高いが、終了条件(次ページが存在しない場合の分岐)については、自動推測結果を人間に提示して確認・修正させるワークフロー(SmartRPAのhuman-in-the-loopフィルタリングに類似)を設計に組み込むことが、既存研究の知見と整合的である。

### Gaps
- 「完全自動化がどの程度の割合(%)で成功するか」という定量的な評価指標(例:正しくループを推測できたケースの割合)について、SmartRPA以外のシステム(Rousillon, WebRobot等)での定量的な成功率データは、本調査の検索範囲では十分に確認できなかった。WebRobotの「76件のベンチマークでベースラインより優れた結果」という記述はあるが、具体的な成功率数値までは本調査では取得できていない。
- Rousillon/Helenaについて、終了条件推測の失敗時にユーザーがどのように修正するか(UIでのデバッグ・修正フロー)の具体的な記述は、原論文本文にアクセスできなかったため未確認。

## 参考: 本ノートで直接確認できなかった主要文献(追加調査推奨)
- Chasins et al., "Rousillon: Scraping Distributed Hierarchical Web Data," CHI 2018 — 原論文本文未取得(404・間接引用のみ)
- Leshed et al., "CoScripter: Automating & Sharing How-To Knowledge in the Enterprise," CHI 2008 — 原論文未取得、ループ一般化機能の詳細不明
- Lin et al., "End-User Programming of Mashups with Vegemite," IUI 2009 — PDFリンクは確認したが本文のループ詳細は未精読
- van der Aalst, Weijters, Maruster, "Workflow Mining: Discovering Process Models from Event Logs," IEEE TKDE 2004 (Alpha algorithm原論文) — 二次資料経由の情報のみ
