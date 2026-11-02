# 画面状態(GUI state)+操作(action)のセマンティックIR設計 — 既存フォーマット調査

## GUIオートメーション/エージェント研究における「状態+アクション」記録の既存フォーマット

### Takeaway
テスト自動化系(Playwright, Selenium IDE)は「アクションの時系列ログ + 周辺証跡(DOM/スクリーンショット/ネットワーク)」を**別ファイルに束ねてzip/JSON化**する設計、GUIエージェント研究系(Mind2Web等)は「1ステップ=1レコード」で、状態(HTML/スクリーンショット)とアクション(operation+target+value)を**ペアで持つフラットなJSON配列**にする設計が主流。いずれも「状態は重い実体を外部参照、アクションは軽量な構造化データとしてインライン」という分離がよく見られる。

### Cited Findings
- Playwrightのトレースは `trace.zip` という単一アーカイブとして出力され、Trace Viewerで各アクションのステップを選ぶと、そのアクション前後の「ページ状態」(DOMスナップショット、スクリーンショット、ネットワーク活動、ログ、ソース、コンソール出力)を表示できる。アクションとスナップショットがペアで管理されている構造自体は公式ページで確認できたが、zip内部のファイル名・スキーマの詳細は公式の `trace-viewer-intro` ページには記載されていなかった — [Playwright Trace Viewer intro](https://playwright.dev/docs/trace-viewer-intro)
- 非公式の解説記事では、`trace.zip` 内に複数の内部ファイルがあり、`trace.trace` エントリは Playwright アクションの改行区切りJSON(NDJSON)を保持しているとされる(ただし出典は二次情報で未検証) — [Playwright Test Trace Viewer 2026解説](https://qaskills.sh/blog/playwright-test-trace-viewer-official-2026)
- Selenium IDEの `.side` ファイルは、プロジェクト全体を保持する単純なJSONで、「コマンド(command)」が「テスト(test)」にまとまり、テストが「スイート(suite)」にまとまる階層構造を持つ。各コマンドは `id`, `comment`, `command` などのキーを持つJSONオブジェクトとして表現される(ただし正式なJSON Schema文書は見つからず、コミュニティのコンバータツールの実装から推測) — [Test Automation University: Codeless Test Automation with Selenium IDE](https://testautomationu.applitools.com/codeless-test-automation-with-selenium-ide/chapter2.html)
- Mind2Web(OSU NLP Group)データセットは「1タスク=1レコード、その中に `actions` というステップのリスト」という構造を取る。各アクションレコードは以下のフィールドを持つ: `action_uid`(ステップID), `raw_html`/`cleaned_html`(アクション実行**前**のページHTML), `operation`(`op`: CLICK/TYPE/SELECT, `original_op`: HOVER/ENTERなど元ラベル, `value`: 入力文字列や選択肢), `pos_candidates`/`neg_candidates`(正解要素・他候補要素のリストで、各要素は `tag`, `is_original_target`, `is_top_level_target`, `backend_node_id`, `attributes`(JSON文字列としてシリアライズされ `json.loads` で復元)を持つ) — [GitHub: OSU-NLP-Group/Mind2Web](https://github.com/OSU-NLP-Group/Mind2Web)
- Mind2Webの画面状態はJSON内では**HTMLのみ**で表現され、アクセシビリティツリーのフィールドは本家データには存在しない。スクリーンショットもメインJSONには含まれず、生データダンプでは `screenshot.json` 内にbase64文字列として、また `{action_id}_before/after.mhtml` という前後スナップショットファイルとして別途格納される — [GitHub: OSU-NLP-Group/Mind2Web](https://github.com/OSU-NLP-Group/Mind2Web)
- サードパーティ派生データセット「Mind2Web-axtree-cleaned-lite-with-tao」は、`cleaned_accessibility_tree` フィールドと次状態のツリーを追加し、候補要素をロール付きの角括弧ID(例: heading要素のCLICKアクション)でインデックスしている。これは公式データではなく派生物 — [Hugging Face: DLI-Lab/Mind2Web-axtree-cleaned-lite-with-tao](https://huggingface.co/datasets/DLI-Lab/Mind2Web-axtree-cleaned-lite-with-tao)

### Inferences
- テスト自動化系フォーマット(Playwright/Selenium)は「再生(リプレイ)」が主目的なため、アクション列は比較的シンプルな構造(セレクタ+操作+値)に留め、画面状態の豊富な証跡はデバッグ用の別チャンネル(zip内の付随ファイル)に分離している。これに対しGUIエージェント研究系(Mind2Web)は「このアクションがどの画面状態で行われたか」をLLMが推論できるようにする目的のため、各ステップのレコードに状態(HTML)を直接埋め込む設計を取っている。PAD→Python変換のIRでも、後段LLMが解釈しやすいように「状態はアクションレコードに直接添付(またはすぐ参照可能な形で同梱)」する設計が参考になる。
- `.side`やMind2Webのいずれも「アクション=操作種別(op/command) + 対象要素 + 値(value)」という3要素構造を採用しており、これはPAD変換IRのアクション表現の基本骨格としても妥当そうである。

### Gaps
- Playwrightの `trace.zip` 内部の正式なファイル一覧とスキーマ(例: `trace.trace`, `trace.network`, `resources/` 等)を公式ドキュメントから直接確認できなかった。二次情報(ブログ)のみで、信頼度は低い。GitHub上の `playwright/packages/trace/src/types.ts` 等のソースコードを直接確認すべき。
- Selenium IDEの `.side` フォーマットの正式なJSON Schema文書(selenium-ide公式リポジトリのTypeScript型定義)を直接確認できなかった。

---

## 2024〜2026年のGUIエージェント研究(WebArena, Mind2Web, OSWorld, AndroidWorld, UFO等)のベンチマークデータセットのJSONスキーマ

### Takeaway
各ベンチマークは「観測(observation)」として**生HTML / アクセシビリティツリー(テキスト化) / スクリーンショット**のいずれか(または組み合わせ)を提供し、「アクション」は**pyautogui的なコード文字列**、**要素IDベースの関数呼び出し(click[1582]等)**、または**座標ベースのJSON**のいずれかで表現される、という3パターンに大別できる。Set-of-Marks(SoM)方式では「番号付きマーカー→ID解決→座標」という間接参照が使われる。

### Cited Findings
- WebArenaの元論文は、フォーカス中タブの3つのレンダリング方式(生HTML/DOM、スクリーンショット、アクセシビリティツリー)を提供する。アクセシビリティツリーはDOMの中からページ内容を示すのに有用な要素だけを残したコンパクトな部分集合で、各要素はロール・テキスト・フォーカス可能性などのプロパティを持つ — [WebArena論文 (arXiv:2307.13854)](https://arxiv.org/pdf/2307.13854)
- WebArenaのアクションはID方式で、ツリーを要素IDつきでシリアライズし、モデルが `click[1582]` のようなコマンドを発行できるようにする(二次情報) — [ChatPaper要約](https://chatpaper.com/paper/6768)
- BrowserGymラッパー(WebArena等を包むOSS)は観測を `axtree_txt`(アクセシビリティツリーのテキスト化)、`pruned_html`、スクリーンショットを含むフィールドとして公開している — [Hugging Face: openenv/browsergym_env models.py](https://huggingface.co/spaces/openenv/browsergym_env/blob/main/models.py)
- OSWorldは実行コマンドで `--observation_type screenshot` のような指定を取り、純粋スクリーンショット設定での実行例が公式READMEに示されている。また実行結果ディレクトリには「スクリーンショット、アクション、ビデオ録画」が保存されると記載されているが、保存されるアクションレコードの正確なフォーマットはREADME本体には記載がなく、`mm_agents/README.md` や `desktop_env/README.md` を参照するよう案内されている(今回はこれらのサブREADMEの直接取得に失敗 — 404) — [GitHub: xlang-ai/OSWorld](https://github.com/xlang-ai/OSWorld)
- OSWorldの観測はデスクトップ全体の2560x1440や1920x1080のスクリーンショットとXML形式のアクセシビリティツリーを提供し、ウィンドウレイアウト・マウス位置・アプリケーション状態を捉えるとされる。アクション空間はpyautoguiを通じて実装され、移動・クリック(左/右/ダブル)・ドラッグ・キー入力・ホットキーをカバーする(二次情報、原論文PDFの要約経由) — [arXiv:2507.19132 (OS-Map論文によるOSWorld言及)](https://arxiv.org/pdf/2507.19132v1)
- AndroidWorldでは、各タスクがエミュレータ状態を操作・検査する独自のsetup/success-check/teardownロジックを持ち、成功判定はUI変化ではなくシステム状態(ADBやSQLiteクエリ等)に対して行われる — [arXiv:2405.14573](https://arxiv.org/pdf/2405.14573)
- AndroidWorldのアクションはJSON形式のコマンドとして、CLICK, SCROLL, INPUT_TEXT, LONG_PRESS, ナビゲーション系アクション、STATUS, ANSWERをカバーするとされる(二次情報) — [alphaxiv.org: AndroidWorldベンチマーク要約](https://www.alphaxiv.org/benchmarks/google-deepmind/androidworld)
- Microsoft UFO²論文は、GUI操作とアプリケーションAPI呼び出しを組み合わせた「ハイブリッドアクション層」を採用し、従来のスクリーンショットベースの操作が脆弱である点を課題として挙げている — [arXiv:2504.14603 (UFO2)](https://arxiv.org/html/2504.14603v2)
- UFO²のドキュメントサイトは、click・set-text・wheel-scroll等のアクションコマンドと、スクリーンショットベース推論を有効にする「visual-mode」設定を列挙している(二次情報、公式ドキュメントサイトだが具体的スキーマは確認できず) — [UFO² overview](https://microsoft.github.io/UFO/ufo2/overview)
- 元のUFO論文は、スクリーンショットとWindowsアプリのコントロール情報を解析するデュアルエージェント構成で、コントロールインタラクションモジュールが人の介入なしにアクションをUIコントロールに紐づける(grounding)と説明している — [arXiv:2402.07939 (UFO)](https://arxiv.org/html/2402.07939v5)
- Set-of-Marks(SoM)プロンプティングはGPT-4Vのgrounding精度向上のために最初に提案され、多くのエージェントタスクで広く使われるようになった。Magmaモデルはセグメンテーション/検出モデルから候補領域を得て、座標を画像サイズで正規化し256binに量子化する — [arXiv:2502.13130 (Magma)](https://arxiv.org/pdf/2502.13130)
- UI-TARSは、解析済み要素に空間座標で配置した番号付きマーカーをスクリーンショットに重ねてSoMプロンプティングを強化しつつ、要素座標を直接予測することも学習する — [arXiv:2501.12326 (UI-TARS)](https://arxiv.org/pdf/2501.12326)
- Xiaomi-GUI-0技術レポートでは、モデルが1ステップに1アクションを選び、その引数をJSONとして出力する。座標は[0,1]²の相対値で、原点は左上 — [arXiv:2606.31410 (Xiaomi-GUI-0)](https://arxiv.org/pdf/2606.31410)
- WebGymのドキュメントは2モードをサポートする: 座標モード(`click(500, 300)` のようなピクセル値)とSet-of-Marksモード(`click([15])` のような要素番号)。SoMがデフォルト — [WebGym docs: rl_context.rst](https://webgym.readthedocs.io/en/latest/_sources/rl_pipeline/rl_context.rst.txt)

### Inferences
- 「状態」の表現は、重い生データ(スクリーンショット/生HTML)と、LLMが扱いやすい軽量なテキスト化(アクセシビリティツリーのテキスト化、`axtree_txt`のようなプルーニング済みテキスト)の二段構成が業界標準になりつつある。PAD変換IRでも、スクリーンショットは外部参照、UI要素情報は軽量なテキスト/JSON要約として両方持たせる設計が合理的。
- アクションの「対象要素の指定方法」は、(a)座標ベース(pyautogui系、Claude computer use)、(b)要素IDベース(WebArenaのclick[1582]、Mind2Webのbackend_node_id)、(c)Set-of-Marksの番号ベース、の3系統があり、座標ベースは環境に依存せず汎用だが曖昧、ID/マーカーベースは解釈性が高いが取得コストがかかる。PADの場合はUI要素のセレクタ(名前・コントロールタイプ等)が既に存在するため、Mind2Web/WebArena型の「要素ID+属性」方式に近い設計が自然となりそう。

### Gaps
- OSWorldの `desktop_env/README.md` および `mm_agents/README.md` の内容(観測・アクションの正確なJSONフィールド名)は直接取得できなかった(404)。GitHub上の実ファイルパスを再確認し、直接フェッチする必要がある。
- AndroidWorldの公式リポジトリ(google-research/android_world)のアクション/観測JSONスキーマは、二次情報(alphaxiv.org, emergentmind.com)経由の記述のみで、原典(GitHub/論文本体)での確認ができていない。
- Microsoft UFO/UFO²のGitHub README(`github.com/microsoft/UFO`)には、画面状態+アクションの記録ログ形式(JSON構造)についての具体的な記載がなかった。実際のログ形式は `ufo/` ディレクトリのソースコード、または `galaxy/README.md`、オンラインドキュメントの "Session Management" / "Visualization" ページにあると推測されるが未確認。

---

## Anthropic Claude "computer use" ツールのスクリーンショット+アクションのやり取り形式

### Takeaway
Claudeのcomputer useツールは、Messages APIの `tool_use`/`tool_result` ブロックを使い、**アクションは `tool_use.input` 内のフラットなJSON(座標は `[x, y]` 配列)**、**画面状態はスクリーンショットのbase64インライン画像を含む `tool_result.content`** として往復する。「action」という単一フィールドではなく、呼び出すツール名(`left_click`, `type`, `scroll` 等)自体がアクション種別を表す設計になっている。

### Cited Findings
- スクリーンショット結果は `tool_result` ブロックの `content` 配列内に、base64インライン画像として返される。フォーマットはPNGまたはJPEGが推奨され、公式サンプルはPNGを使用。各結果は `toolset_name: "computer"` を明示し、`tool_use_id` で呼び出し元に対応づける。例:
```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_01Xf5W1sD8Q9aBcJ7kLmN2pQ",
  "toolset_name": "computer",
  "content": [
    { "type": "image", "source": { "type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo..." } }
  ]
}
```
 — [Claude Platform Docs: computer-use-tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)
- アクションは `tool_use` ブロックとして表現され、`name` フィールド(例: `left_click`, `scroll`, `type`, `key`)がアクション種別そのものを表す。「action」という専用フィールドは存在せず、`input` にはそのメンバーツール固有のパラメータのみが入る。例:
```json
{
  "type": "tool_use",
  "id": "toolu_01WkoTUvSHDzTBu2xnGk8Ep8",
  "name": "left_click",
  "toolset_name": "computer",
  "input": { "coordinate": [512, 742] }
}
```
 — [Claude Platform Docs: computer-use-tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)
- 座標はスクリーンショットのピクセル単位の `[x, y]` で、原点は画面左上。主なアクションの入力フィールド: `screenshot`(`{}`)、`zoom`(`region: [x0,y0,x1,y1]`)、`left_click`/`right_click`/`middle_click`/`double_click`/`triple_click`(`coordinate`省略可、`text`に `"shift"` 等の修飾キー)、`left_click_drag`(`start_coordinate`, `coordinate`, `text`)、`mouse_move`(`coordinate`)、`scroll`(`scroll_direction`, `scroll_amount`, `coordinate`省略可)、`type`(`text`に実テキスト)、`key`(`text`にキー名/`+`結合の組み合わせ、`repeat`省略可)、`hold_key`/`wait`(`duration`) — [Claude Platform Docs: computer-use-tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)
- 失敗時は `is_error: true` を付けたテキストで理由を返す。1回答に複数の `tool_use` が含まれる場合は順番に実行し、最初の失敗で停止、以降のアクションは `"Not executed: an earlier computer action in this turn failed."` という `is_error: true` の結果を返す — [Claude Platform Docs: computer-use-tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)

### Inferences
- Claudeのcomputer use形式は「状態=直前の `tool_result` のスクリーンショット画像」「アクション=直後の `tool_use` のツール名+座標/テキスト」という、**往復のメッセージ列そのものが状態+アクションのペアログになる**設計である。これは、PAD変換IRで「各アクションの直前の画面状態」と「アクション本体」をペアにして記録する際の、実績ある参照モデルとして使える(ただしAnthropicの形式はリアルタイムの会話往復用であり、永続化されたログファイル形式ではない点に注意)。
- `type` と `key` を明確に分離する設計(リテラルテキスト入力 vs. 特殊キー/修飾キー)は、PADの「テキスト入力」アクションと「キー送信」アクションを区別する際の参考になる。

### Gaps
- 元のURL `docs.claude.com/.../computer-use-tool` は `platform.claude.com` にリダイレクトされており、ドキュメントの更新頻度・バージョニング(例: `computer-use-2025-01-24` のようなベータヘッダー文字列)については今回Web検索の二次情報(サードパーティのRustクレート経由)でのみ見かけ、公式ページ本文中では確認できなかった。ベータヘッダー名のバージョン表記は公式ページで再確認が必要。
- 画面状態側に「アクセシビリティツリー」や「UI要素構造」をあわせて渡す公式オプションがあるかどうかは、取得した範囲のドキュメントには記載がなかった(スクリーンショットのみの設計に見える)。

---

## Power Automate Process Mining / Task Mining の録画・ログの構造化データ

### Takeaway
Task Miningは画面録画/操作ログを収集する「入力側」機能、Process Miningは収集されたイベントを「Case ID・Activity・Timestamp」を持つイベントログ(Power BIのデータモデルにおける `Events` テーブル)に変換して分析する「出力側」機能であり、両者はDataverse経由(Fabricショートカットでのリンクも可)で連携する。ただし、録画1件ごとの詳細なUI要素/スクリーンショットのスキーマそのものは公式Learn文書からは確認できなかった。

### Cited Findings
- Task Miningは、ユーザーのデスクトップ上で実行されるタスクの詳細な手順を、個別または共同で記録できる技術で、記録されたユーザー操作を分析することで、業務の実行方法の把握、よくある間違いの特定、自動化候補タスクの特定を可能にする — [Microsoft Learn: Task mining overview](https://learn.microsoft.com/power-automate/task-mining-overview)
- Microsoftのコミュニティ記事は、Task Miningで記録したものをそのままPower Automate Process Mining(PAPM)に取り込める旨を述べ、DataverseデータをFabricにリンクしてソースとして使えるとしている。Dataverseエンティティがショートカットとしてリンクされている場合、新しい録画が追加されるとデータリフレッシュ機能が自動的にプロセスモデルを最新化する — [Microsoft: task-mining-papm-fabric](https://microsoft.github.io/mine-the-gap/posts/task-mining-papm-fabric/)
- Process Miningをプロセスとして公開すると、Power BI側にデフォルトのデータソースと対応するレポートが作成される。このデータモデルは、(1)フィルタ/計算なしの「Process data」、(2)適用フィルタ・計算指標・カスタムメトリクスを使った「View data」、(3)プロセスマイニング用カスタムビジュアルの表示に必要な事前計算済みデータの「Visuals data」、(4)Power BIが必要とする「Helping entities」、の4系統のテーブル群から構成される — [Microsoft Learn Training: Process Mining data model](https://learn.microsoft.com/en-us/training/modules/create-reports-process-mining/process-mining-data-model)
- 公式サンプルのDAXメジャー例から、`Events` テーブルには少なくとも `vendor_continent` や `Case_ID` という列が存在することが確認できる(`AVERAGEX(GROUPBY(Events, Events[vendor_continent], Events[Case_ID]), CALCULATE(COUNTROWS(Events)))`)。これは「ケースごとのイベント数」という典型的なプロセスマイニングのイベントログ構造(Case ID + Activity + Timestamp)を裏付ける — [Microsoft Learn Training: Process Mining data model](https://learn.microsoft.com/en-us/training/modules/create-reports-process-mining/process-mining-data-model)
- ある研究データセット(サードパーティ)は、Power Automateの録画から構築したレコードを、録画ID(ケースIDとみなせる)、ステップID、システムが記録したタイムスタンプとして記述している。これはMicrosoft公式のスキーマではなく、研究用の派生データ — [ar5iv: arXiv:2308.12211](https://ar5iv.labs.arxiv.org/html/2308.12211)

### Inferences
- Process Miningの核心は古典的なプロセスマイニング手法と同じ「イベントログ(Case ID, Activity, Timestamp [,Resource]) 」であり、GUI状態(スクリーンショットやUI要素ツリー)はTask Mining側の録画データに付随する「証跡」として別途保持され、Process Mining側の分析用イベントログには直接含まれない(集計・可視化のための軽量な構造のみが昇格される)と考えられる。PAD変換IRにおいても、「分析・LLM解釈用の軽量イベント構造」と「人間レビュー用の詳細証跡(スクリーンショット等)」を分離しつつ、Case/Activity/Timestampに相当するキーで紐づけておく設計が有効そう。

### Gaps
- Task Mining側で録画1ステップごとに記録される具体的なJSON/テーブルスキーマ(スクリーンショットの格納形式、UI要素情報の有無、アプリ/ウィンドウタイトルのフィールド名など)は、今回確認した公式Learn文書(`task-mining-overview`)には記載がなく、概念的な説明のみであった。Dataverseのテーブル定義(エンティティスキーマ)への直接アクセスが必要。
- `Events` テーブルの全列リスト(列名とデータ型)は、DAXサンプル中に現れた `vendor_continent` と `Case_ID` のみ確認でき、`Activity`/`Timestamp` に相当する実際の列名は未確認。

---

## UI Automation (UIA) ツリーをXML/JSON等にダンプする既存手法・ツール

### Takeaway
Windows UI Automationのツリーをテキスト化するツールは複数存在し、用途に応じて「人間のデバッグ用GUIインスペクタ(Automation Spy等)」と「スクリプト/エージェント用のCLI・ライブラリ(lvt, uitree, UiPathのExport UI Tree)」に分かれる。JSON/XML双方への出力をサポートするツールが主流。

### Cited Findings
- **lvt**(Windows C++ CLI): アプリウィンドウのビジュアルツリーを検査し、JSONまたはXMLとして出力する。フォーマット指定フラグ、深さ制限、ファイルへの出力オプションを持つ。AIエージェントが特定のUI部分を参照できるよう、安定した要素IDを付与する機能もある。ターゲットプロセスのアーキテクチャ(32/64bit)と `lvt.exe` のアーキテクチャを一致させる必要がある — [awesome.ecosyste.ms: asklar/lvt](https://awesome.ecosyste.ms/projects/github.com%2Fasklar%2Flvt)
- **uitree**(Python, PyPI): WindowsのUI Automationツリーをスクリプトやエージェントに公開するツール。`dump` コマンドは `--json` フラグを受け付け、他に `find` と `watch` コマンドもある。読み取り専用設計。ライブツリーの取得にはWindowsとpywinautoが必要で、他プラットフォームでは保存済みのフィクスチャツリーの再生に対応 — [PyPI: uitree](https://pypi.org/project/uitree/)
- **Automation Spy**(C#, GitHub): Microsoft UI Automation階層をブラウズし、各要素のプロパティとコントロールパターンを検査するGUIユーティリティ(エクスポート形式は検索結果からは不明) — [awesome.ecosyste.ms: ddeltasolutions/automation-spy](https://awesome.ecosyste.ms/projects/github.com%2Fddeltasolutions%2Fautomation-spy)
- **UiPathの「Export UI Tree」アクティビティ**: 指定要素配下の全UI要素を、その属性と値とともにXMLまたはJSONファイルにエクスポートするRPAアクティビティで、セレクタのデバッグに有用 — [UiPath Docs (日本語): Export UI Tree](https://docs.uipath.com/ja/activities/other/latest/ui-automation/export-ui-tree)

### Inferences
- `uitree` や `lvt` の「要素に安定IDを付与してAIエージェントが参照できるようにする」という設計意図は、PAD変換IRでも「UI要素ツリーのスナップショットに一意な参照キーを振り、アクションレコード側からそのキーを参照する」という設計(Mind2Webの `backend_node_id` に近い発想)が有効であることを裏付ける。
- JSON/XML両対応ツールが複数存在することから、UIAツリーの「ダンプ形式」自体には業界標準の単一スキーマは存在せず、各ツールが独自のJSON/XML構造を定義している。PAD変換IRのUI要素表現は、既存ツールのいずれかに準拠するのではなく、必要なプロパティ(Name, ControlType, AutomationId, BoundingRectangle等UIAの標準プロパティ)を独自に選定してJSON化するのが実務的と考えられる。

### Gaps
- `lvt` や `uitree` の実際の出力JSONのフィールド名(例: `ControlType`, `Name`, `BoundingRectangle` などUIA標準プロパティがどうマッピングされているか)の具体例は、今回の検索では取得できなかった。各ツールのREADME/ソースを直接確認する必要がある。

---

## 「状態+アクション」ログ設計における一般的なJSON設計パターン(イベントソーシング、OpenTelemetry等からの類推)

### Takeaway
イベントソーシングのベストプラクティス(追記専用・不変・エンベロープ標準フィールド・スキーマバージョニング)とOpenTelemetryのスパン/イベントモデル(操作の開始・終了+属性+タイムスタンプ付きイベントの入れ子構造)は、いずれも「状態+アクション」ログのエンベロープ設計に直接応用できる、業界で確立された参照パターンである。

### Cited Findings
- イベントソーシングのログは追記専用(append-only)であり、誤りがあれば履歴を編集せず訂正イベントを新たに書き込む("If we got it wrong, we write a corrective event") — [techinterview.org: Event Sourcing Low-Level Design](https://www.techinterview.org/post/3233473937/lld-event-sourcing-design/)
- スナップショットはイベントログから再構築可能な非正規化ビューに過ぎず、ログ自体を省略してスナップショットのみを保持してはならない("Snapshots are denormalized views — they can always be reconstructed from the event log. Never store only snapshots without the event log.") — [techinterview.org: Event Sourcing Low-Level Design](https://www.techinterview.org/post/3233473937/lld-event-sourcing-design/)
- エンタープライズ向けのイベントスキーマガイドは、JSON Schema(draft 2020-12)で、バージョン付き `$id`、イベントタイプ名、スキーマバージョン、タイムスタンプ、payloadオブジェクトという標準エンベロープを推奨し、互換性モード(backward/forward/full/none)を定義する。コミュニティのスキル一覧では、イベントID・集約ID(aggregate ID)・イベントタイプ・タイムスタンプ・バージョン・payloadを必須フィールドとし、UUIDと相関/因果(correlation/causation)メタデータの付与を推奨している(ただしこのスキル一覧は信頼度の低い二次情報) — [EventCatalog demo docs: event-schemas](https://demo.eventcatalog.dev/docs/custom/guides/creating-new-microservices/04-event-schemas)
- スキーマ進化の2つの一般的手法は、読み取り時に古いイベントをアップキャストする方法と、イベントタイプ自体をバージョニングする方法(例: `OrderCreated_V1` と `V2`)。古いイベントタイプは削除してはならない(ログ中に永続的に存在するため) — [EventCatalog demo docs: event-schemas](https://demo.eventcatalog.dev/docs/custom/guides/creating-new-microservices/04-event-schemas)
- OpenTelemetryのスパンは、1つの操作に対する開始・終了時刻、名前、スパン種別、属性(attributes)、イベント(events)、ステータス、トレース/スパンIDコンテキストを持つ。イベントはスパン内部に記録されるタイムスタンプ付きエントリ(インラインログのようなもの)で、キャッシュミスやリトライ試行などの例が挙げられる — [OneUptime: OpenTelemetry Data Model for Beginners](https://oneuptime.com/blog/post/2026-02-06-opentelemetry-data-model-beginners/markdown)
- Apache Ozoneの設計文書は、スパンの核となるフィールドとして名前・スパン種別・属性・イベント・ステータス・トレース/スパンIDコンテキストに加え、親スパンID・スパンリンクを挙げ、各イベントは名前・タイムスタンプ・任意の属性を持つとしている — [Apache Ozone HDDS-13679設計文書](https://apache.googlesource.com/ozone/+/5fdf2d2d0bd0ac0edb1fd1f1bb1d382e17e0584c%5E%21)
- OneUptimeのガイドは、サービス単位で共通の「リソース属性(resource attributes)」と、個々の操作を記述する「スパン属性(span attributes)」を区別し、サービスレベルの値をすべてのスパンに繰り返し持たせないことを推奨している — [OneUptime: OpenTelemetry Data Model for Beginners](https://oneuptime.com/blog/post/2026-02-06-opentelemetry-data-model-beginners/markdown)
- Google Cloud Traceは、受信したOpenTelemetryデータを独自形式に変換して保存し(生のOTLPではない)、属性値もOpenTelemetryの型からJSONの型に変換される。イベントレコードは時刻・名前・属性・ドロップされたイベント数を含む — [Google Cloud: Storage schema for trace data](https://cloud.google.com/trace/docs/reference/trace-schema)

### Inferences
- OpenTelemetryの「リソース属性(変化しない文脈: サービス名など) vs. スパン属性(個別操作固有の情報)」という分離は、PAD変換IRでも「フロー全体・セッション共通のメタデータ(マシン名、アプリバージョン等)」と「各アクション固有のメタデータ(クリック座標、入力文字列等)」を分けて持つ設計の裏付けとなる。
- イベントソーシングの「エンベロープ+ペイロード+バージョニング」パターン(イベントID, タイムスタンプ, イベントタイプ, スキーマバージョン, payload)は、PADアクション1件ごとのJSONレコードの最上位構造として直接採用できる。将来のPADバージョンアップやアクション種別追加に対しても、`schema_version` フィールドを持たせることで後方互換を保ちやすくなる。
- OpenTelemetryの「スパン(操作の開始/終了区間)+その内部に入れ子のイベント(タイムスタンプ付きの出来事)」という2階層構造は、「1つのPADアクション実行」を1スパンとし、その前後の画面状態キャプチャを「イベント」として入れ子にする設計に転用できそう(例: `action_span` の中に `before_screenshot_captured`, `action_executed`, `after_screenshot_captured` という3イベント)。

### Gaps
- イベントソーシングおよびOpenTelemetryの標準的参照元であるMartin Fowlerや Greg Youngの原典記事、およびOpenTelemetry公式仕様書(opentelemetry.io/docs/specs)やOTLP protoファイルそのものは、今回の検索では直接取得できず、二次解説記事(ブログ、スキル一覧サイト)からの情報に留まった。権威ある一次資料での裏取りが推奨される。

---

## スクリーンショットの扱い(インラインBase64 vs 外部ファイル参照)の設計上の考慮点

### Takeaway
スクリーンショットのインラインBase64埋め込みは実装がシンプルで自己完結的だが、トークンコスト・リクエストサイズの肥大化という欠点があり、長時間稼働するエージェント/長い会話履行では「ファイル参照(パスやURL)」方式への移行が推奨されている。Anthropicのcomputer useツール自体は往復メッセージ内でbase64インライン方式を採用しているが、これは「1ターンのやり取り」を想定した設計であり、永続的なログ保存の文脈では別の考慮が必要。

### Cited Findings
- OpenAIの開発者フォーラムでは、圧縮済みJPEGをインライン化すると1画像あたり概ね3万トークン以上のコストがかかるという報告があり、アップロード後に参照IDで渡すパターン(GPT-4.1向け)がサポートされているかという質問が投げられている(回答は未確認) — [OpenAI Community: file upload + reference ID pattern](https://community.openai.com/t/is-the-file-upload-reference-id-pattern-supported/1331539)
- あるチュートリアルは、base64はローカルファイルでも機能し画像の可用性を保証できる利点があるが、リクエストサイズを約1/3増加させ、大きなアップロードを遅くするという欠点があると述べている — [ai3c-docs: Lesson 7 Vision & Multimodal Inputs](https://ai3c-docs.pages.dev/docs/tier-1/part-2-api-integration/vision-multimodal)
- LangChainのDeep Agentsドキュメントは、スクリーンショットやチャート画像をファイルシステムやオブジェクトストアに保存し、パスやURLを渡すことを推奨し、長時間稼働する会話ではbase64インラインブロックよりも参照を優先するよう助言している。また、要約処理は古いメッセージから画像ブロックを除去するため、モデルは要約されたテキスト記述のみを保持することになる、とも述べている — [LangChain Docs: Deep Agents multimodal](https://docs.langchain.com/oss/javascript/deepagents/multimodal)
- GitHub Copilot SDKのドキュメントは、ファイルパス添付(ランタイムがファイルを読んでbase64エンコードする)とblob添付(呼び出し元がbase64データを直接渡す)の両方式を提供している — [GitHub Docs: Copilot SDK image-input (fr)](https://docs.github.com/fr/copilot/how-tos/copilot-sdk/features/image-input)
- Anthropicのcomputer useツールにおける画面状態のやり取りは、`tool_result.content` 内にbase64インライン画像(`type: "image", source: {type: "base64", media_type: "image/png", data: "..."}`)として埋め込む方式を採用している(前出) — [Claude Platform Docs: computer-use-tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)

### Inferences
- 「人間のレビュー用」と「LLM入力用」の両方を満たす設計としては、JSON中間表現自体にはスクリーンショットの**外部ファイルパス(または将来的な署名付きURL)への参照のみ**を持たせ、LLMに渡す直前のタイミングで必要な画像だけをbase64にエンコードして動的に注入する「2段階方式」が合理的と考えられる。これにより、(a)JSON自体の可読性・差分管理性(gitでのdiffのしやすさ、ファイルサイズ)が保たれ、(b)人間がレビューする際はファイルパスから画像ビューアで直接開ける、(c)LLMへの入力時にはトークン予算に応じて画像を取捨選択できる、という3つの利点を同時に満たせる。
- 長時間ログ(PADフロー全体)をそのままLLMコンテキストに流し込むシナリオでは、LangChainの助言(古い画像は要約テキストに置き換える)に従い、IR設計時に「スクリーンショットの代替テキスト記述(alt_text/summary)」フィールドを画像参照と並べて持たせておくと、トークン予算超過時のグレースフルデグレードが可能になる。

### Gaps
- OpenAIコミュニティの質問スレッドで言及された「アップロード+参照ID」パターンがGPT-4.1や他モデルで実際にサポートされているかどうかの確定的な回答は、今回の検索では確認できなかった。
- Anthropic APIが画像について「ファイルアップロード+参照ID」方式(base64インラインではない方式)をサポートしているかどうかは、今回取得したcomputer-use-toolページの範囲では明記されていなかった(スクリーンショットツールの応答は常にbase64インラインとして示されていた)。Anthropic Files APIの利用可否について別途確認が必要。
