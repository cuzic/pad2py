# 画面状態IRとローカル決定的処理がPAD変換を前進させる

前回調査は、PADフロー定義が非公開フォーマットである以上「クリップボードのテキストDSLを一次入力とし、パーサー→IR→コードジェネレータの三層をVisitorパターンで実装する半自動変換支援ツール」が唯一の現実的な到達点であると結論づけた。今回の拡張調査が示す最終結論は、この三層アーキテクチャの**IR層を「アクション列」から「アクション+画面状態のペア」へ拡張**し、**複数トレースからのループ・分岐再構成はループ本体の検出まではアルゴリズム的に自動化できるが終了条件の確定は一貫して人間判断に依存する**こと、そして最も重要な点として、**「変換モジュールをChatGPT/Gemini/M365 Copilotのコード実行サンドボックスにアップロードして実行する」という運用イメージは2026年11月時点でいずれのプラットフォームでも実務的に成立しない**ことである。Geminiは独自ライブラリインストール不可・30秒実行上限を公式に明記し([Google AI: Code execution](https://aistudio.google.com/docs/code-execution))、ChatGPTのコンテナは20分未使用で失効しデータは復元不可能([OpenAI Developers: Code Interpreter tool guide](https://developers.openai.com/api/docs/guides/tools-code-interpreter))、M365 CopilotのCode Interpreterは2026年8月時点でも「プレリリース文書」と明記されるプレビュー機能に留まる([Microsoft Learn](https://learn.microsoft.com/en-us/microsoft-copilot-studio/knowledge-code-interpreter-structured-data))。したがって推奨アーキテクチャは、変換パイプライン本体(パーサー・IR構築・コード生成・検証)を**ローカル/CI環境で動く決定的なPythonパッケージとして実装**し、LLMには「セレクタの意味解釈」「ループ終了条件の確認」「未対応アクションの処理方針」といった曖昧性の高い判断だけをAPI/チャット経由で問い合わせる役割分担に落とし込む。以下、この結論に至った3つの拡張要件の調査結果を順に統合し、フェーズ分けされた実装ロードマップとリスク対応策を提示する。

## 画面状態とアクションを1レコードに束ねるセマンティックIRが後段推論の土台になる

GUIオートメーション/エージェント研究の既存フォーマットを横断すると、「状態+アクション」記録には収斂した設計原則が見える。テスト自動化系(Playwright)は「アクションの時系列ログ+周辺証跡(DOM/スクリーンショット/ネットワーク)」を`trace.zip`という単一アーカイブに束ね、Trace Viewerで各アクション前後の画面状態を参照できる構造を取る([Playwright Trace Viewer intro](https://playwright.dev/docs/trace-viewer-intro))。一方、GUIエージェント研究系のMind2Webは「1ステップ=1レコード」とし、各レコードが`action_uid`、アクション実行**前**のHTML、`operation`(op/value)、そして正解要素と他候補要素を`backend_node_id`付きで保持する`pos_candidates`/`neg_candidates`という構造を取る([GitHub: OSU-NLP-Group/Mind2Web](https://github.com/OSU-NLP-Group/Mind2Web))。この2系統の違いは目的の違いに由来する——再生(リプレイ)が目的のテスト自動化系は状態の豊富な証跡を別チャンネルに分離し、LLMによる解釈が目的のエージェント研究系は状態をアクションレコードに直接添付する。PAD変換IRは後段でLLM推論(セレクタの意味理解、ループ・分岐の再構成支援)を使う以上、**Mind2Web型の「状態をアクションに同梱する」設計を基本とすべき**である。

状態側の表現方法については、WebArena/BrowserGym/OSWorldといった2024〜2026年のベンチマーク群が「生HTML/アクセシビリティツリー/スクリーンショット」の3系統を使い分けており、軽量なテキスト化(アクセシビリティツリーのプルーニング済みテキスト)と重い生データ(スクリーンショット)を二段構成で持つ設計が業界標準になりつつある([WebArena arXiv:2307.13854](https://arxiv.org/pdf/2307.13854)、[BrowserGym models.py](https://huggingface.co/spaces/openenv/browsergym_env/blob/main/models.py))。Anthropic Claudeのcomputer useツールは、`tool_use.input`のフラットなJSON(座標は`[x, y]`配列、ツール名自体がアクション種別を表す)と`tool_result.content`のbase64インラインスクリーンショットという往復メッセージそのものを状態+アクションのペアログとして機能させる実装例であり([Claude Platform Docs: computer-use-tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool))、`type`(リテラルテキスト入力)と`key`(特殊キー)を明確に分離する設計は、PADの「テキスト入力」と「キー送信」アクションを区別する際の直接的な参考になる。UIAツリーのダンプについては`lvt`や`uitree`のようなCLIツールがJSON/XML双方に対応し、「AIエージェントが参照できる安定ID」を要素に付与する機能を持つ([lvt](https://awesome.ecosyste.ms/projects/github.com%2Fasklar%2Flvt)、[uitree](https://pypi.org/project/uitree/))。これはMind2Webの`backend_node_id`と同じ発想であり、制御dumpスクリプトが出力するUI要素ツリーにも一意な参照キーを振り、アクションレコード側からそのキーで参照する設計が妥当である。

IRのエンベロープ構造は、イベントソーシングとOpenTelemetryの参照パターンから直接借用できる。イベントソーシングのベストプラクティスは追記専用(append-only)でありスナップショットのみを保持してはならないという原則と([techinterview.org](https://www.techinterview.org/post/3233473937/lld-event-sourcing-design/))、エンベロープにイベントID・タイムスタンプ・イベントタイプ・スキーマバージョン・payloadを持たせるパターンを示す。OpenTelemetryはサービス単位で変化しない「リソース属性」と個々の操作固有の「スパン属性」を分離することを推奨しており([OneUptime: OpenTelemetry Data Model](https://oneuptime.com/blog/post/2026-02-06-opentelemetry-data-model-beginners/markdown))、これはPADの「フロー全体のメタデータ(マシン名・PADバージョン)」と「各アクション固有のメタデータ(クリック座標・入力文字列)」を分離する設計の裏付けとなる。これらを統合すると、1アクションのIRレコードは次の構造を持つべきである。

| レイヤー | フィールド例 | 設計根拠 |
| --- | --- | --- |
| エンベロープ | `schema_version`, `trace_id`, `action_uid`, `timestamp`, `flow_meta`(リソース属性) | イベントソーシング+OTelのリソース/スパン属性分離 |
| アクション本体 | `action_type`(PADアクションID), `params`(名前付きパラメータ辞書), `output_var` | 前回調査のテキストDSL構文(アクション呼び出し行)と1:1対応 |
| 画面状態(前) | `ui_tree_ref`(外部ファイル参照+安定ID), `screenshot_ref`(外部ファイルパス), `alt_text`(軽量要約) | Mind2Web型の状態同梱+LangChainのファイル参照推奨 |
| 画面状態(後) | 同上(実行後) | Playwrightの「アクション前後」ペア記録に対応 |
| 候補UI要素 | `target_candidates`(セレクタ+属性のリスト、正解要素フラグ) | Mind2Webの`pos_candidates`/`neg_candidates`に対応 |

スクリーンショットのインライン化については明確なトレードオフがある。Anthropicのcomputer useは1ターンのやり取りを想定してbase64インライン方式を採るが、OpenAIコミュニティでは圧縮JPEGのインライン化が1画像あたり3万トークン以上のコストを生むという報告があり([OpenAI Community](https://community.openai.com/t/is-the-file-upload-reference-id-pattern-supported/1331539))、LangChainのDeep Agentsドキュメントは長時間稼働するエージェント/会話では画像をファイルシステムに保存してパス参照とし、要約処理では古い画像ブロックを除去してテキスト記述のみ残すことを推奨している([LangChain Docs](https://docs.langchain.com/oss/javascript/deepagents/multimodal))。PAD変換IRでは、**JSON本体にはスクリーンショットの外部ファイルパス参照と軽量な`alt_text`要約のみを持たせ、LLMに渡す直前に必要な画像だけをbase64化して動的注入する2段階方式**を採用すべきである。これにより、JSON自体のgit diff可読性、人間レビュー時のファイルビューア直接オープン、LLM入力時のトークン予算に応じた画像取捨選択という3つの利点を同時に満たせる。なお、Power Automate Process/Task MiningのDataverseイベントログ(`Case_ID`相当の構造)は概念的に参考になるが、録画1件ごとの詳細スキーマは公式Learn文書からは確認できず([Task mining overview](https://learn.microsoft.com/power-automate/task-mining-overview))、本プロジェクトは既存PADマイニング機能を利用するのではなく独自の制御dumpスクリプトでIRを構築する前提に変わりはない。

## 複数トレースはループ本体まで自動抽出できるが終了条件は人間確認が必須

同じ操作(ページ送り)を複数回記録したPADフロー+JSONダンプのペア群から、ループ・分岐を含む単一のPythonフローを再構成する問題は、Programming by Demonstration(PBD)研究の系譜が最も直接的な参照先になる。カーネギーの古典Eager(1991年)以来、「繰り返しパターン検出→ループ変数特定→終了条件推測」の3段構成が認識されており([Watch What I Do Ch.9](https://acypher.com/wwid/Chapters/Chapter09Intro.html))、2016〜2018年のBerkeley系研究(Ringer→Rousillon→Helena)がWeb自動化にこれを最も具体的に適用した。Rousillonは、Ringerが記録した「ストレートライン(分岐・ループなし)」のデモンストレーションを一般化し、ループを含む高レベルなHelenaプログラムへ変換する——ユーザーが収集したいデータの最初の1行をデモすれば、システムが残り数百〜数千行を収集するプログラムへ一般化する([Helena/Rousillon project](https://helena-lang.org))。これはPADの「ページ送りをページごとに個別記録する」運用と構造的に最も近く、各トレースの対応するUI要素を比較し、変化する部分をループ変数、変化しない操作列をループ本体とする発想が転用可能である。より形式的なアプローチとしてWebRobot(2022年)は「プログラムPがトレースAを一般化する」ことを形式的に定義し、rewrite-based program synthesisの文脈で「speculate-and-validate」という新手法を提案し、76件のベンチマークでegg実装のベースラインを上回った([WebRobot arXiv:2203.09993](https://arxiv.org/pdf/2203.09993))。

プロセスマイニングの古典アルゴリズムも参照点になるが、重大な制約がある。Alpha algorithmは直接継起・因果・並行・選択の4関係からPetriネットを構成する手法だが、**長さ1・長さ2の短いループを原理的に扱えない**という既知の欠陥を持つ([Alpha algorithm (Wikipedia)](https://en.wikipedia.org/wiki/Alpha_algorithm))。これはPADのページ送りフロー(1〜2種類の操作が繰り返される典型的な短いループ)にとって本質的な障害になりうるため、Heuristics Miner(依存関係比率が閾値を超えた場合に短ループを追加)やInductive Miner(divide-and-conquerでプロセス木を構築し健全性を保証)のような短ループ対応拡張が前提となる([Heuristics Miners論文](https://arxiv.org/pdf/1212.6383)、[Inductive Miner論文](https://arxiv.org/pdf/1610.07989))。ただしこれらは「多数のケース」を前提に統計的頻度でモデルを導出する手法であり、本プロジェクトが想定する「数本〜十数本のPADトレース」という少数サンプルの問題設定とは規模が異なる。この橋渡しとして最も参考になるのがSmartRPA(2023年BPM最優秀論文賞)で、(1)頻出パターン識別技術でUIログからルーティンを自動導出、(2)**人間参加型(human-in-the-loop)インタラクションで実世界の実行にそぐわない誤検出セグメントを除外**、(3)プロセスマイニングのトレースアラインメント技術でルーティントレースへクラスタリングする3段パイプラインを採る([Agostinelli, CEUR-WS Vol-3469](https://ceur-ws.org/Vol-3469/paper-01.pdf))。

決定的なのは、この論文自身が末尾で「本手法は半教師あり(semi-supervised)の仮定に基づく。ルーティン実行を終了させる各ユーザー操作に付随するend-delimiterを事前に知っているという前提があるため」「完全な教師なし自動化はまだ達成されておらず将来研究の方向性である」と明記している点である([同上](https://ceur-ws.org/Vol-3469/paper-01.pdf))。HILC(2017年)やRecurBot系の研究も、ループの開始・終了をユーザーが特定のキー操作で明示的にマークする設計を採り、終了条件の「推測」ではなく「人間による明示」に依存している([HILC arXiv:1611.03906](https://arxiv.org/pdf/1611.03906))。商用RPAベンダー側を見ても、UiPath・Power Automate・Automation Anywhereのいずれにも「複数回の記録を比較して自動的にループを検出・生成する」機能は確認できず、UiPathコミュニティの実務パターンは「Next」ボタンの非存在をElement Existsで検出して終了条件とする**手動構築**が標準である([UiPath forum](https://forum.uipath.com/t/512751))。

これらを統合すると、PAD複数トレースの一般化における自動化/人間介在の境界線は次のように引ける。各トレース(1ページ分の操作列)を行アラインメントし、「変化しない操作列=ループ本体」「反復ごとに変化する値(クリック対象のページ番号、抽出テキスト)=ループ変数」の抽出は、SmartRPAのトレースアラインメントやRousillonの差分比較の発想を応用すれば**比較的高い確度で自動化できる**。一方、「終了条件(次ページボタンが無効/存在しない、というシグナル)の確定」は、学術研究が一貫して人間確認を必要とする領域として扱っており、本プロジェクトでも自動推測結果(例:「最後のトレースにだけ現れる操作/エラーを終了条件の候補として提示」)を人間に確認・修正させるUIを設計に組み込むべきである。実務上の落とし所は、ユーザーに「最後の1回だけ、ボタンが見つからない状態まで余分に記録してもらう」という軽い追加作業を課し、その最終トレースの差分を終了条件のヒントとして自動抽出し、確認ダイアログで人間が承認する、というフローである。これは完全自動化ではないが、既存研究の知見(Eager以来の「ヒューリスティックは脆い」という一致した指摘)を踏まえた、過大な期待を抱かない現実的な設計である。

## LLMサンドボックスへの独自ライブラリアップロードは実務的に成立しない

ユーザーが想定する運用(①PADフロー作成→②制御dumpスクリプトでJSON化→③複数回記録してペアを蓄積→④PADフロー・JSONダンプ・変換モジュールをChatGPT/Gemini/M365 Copilotにアップロード→⑤コード実行環境内で変換モジュールを実行し生成Pythonをダウンロード)を、2026年11月時点の公式制約と照らし合わせると、3プラットフォームのいずれも「独自Pythonパッケージを恒久的に実行基盤として使う」運用には適さないという結論が明確に出る。

Geminiが最も明確に「不可」と文書化している。Google公式ドキュメントはCode Execution toolについて「ユーザーは自分自身のライブラリをインストールできない(You can't install your own libraries)」と明記し、利用可能ライブラリはnumpy/pandas/matplotlib等の固定リストに限定される([Google AI: Code execution](https://aistudio.google.com/docs/code-execution))。最大実行時間は**30秒固定**で、エラー時は最大5回まで再生成して再試行する仕組みしかなく、長時間かかるPADフロー全体の一括変換には全く対応できない。実行言語もPythonのみ、グラフ描画もmatplotlibのみという厳格な制約であり、PADパーサー・IR構築・コード生成という多段処理をこの環境内で完結させることは不可能と判断できる。

ChatGPT(Responses APIのCode Interpreter tool)は3者の中で最も柔軟だが、それでも恒久運用には不向きである。コンテナという隔離VM単位で動作し、**20分間使用されないと失効し、データは復元不可能**(新規コンテナ作成とファイル再アップロードが必要)([OpenAI Developers: Code Interpreter tool guide](https://developers.openai.com/api/docs/guides/tools-code-interpreter))。レート制限は100RPM/組織。独自パッケージのpipインストールやネットワークアクセスの可否について公式ドキュメントは明示しておらず、コミュニティの非公式調査(gVisorサンドボックス+内部PyPIミラー経由でpipは動くが外部ネットワークは遮断、という報告)があるのみで、確証は取れていない([Poking Around ChatGPT's Sandbox](https://hn.jakechampion.name/reader/https://mkarots.github.io/blog/chatgpt-sandbox-exploration))。消費者向けChatGPT UI自体のファイル保持・セッション失効時間についても、公式ヘルプページへの直接アクセスができず正確な数値は確認できなかった。

M365 Copilotは、Excel内のPython数式機能(Python in Excel)を除けば、汎用的なPythonコード生成・実行機能はCopilot Studioの「Code Interpreter」のみであり、これは2026年8月更新の公式ドキュメントでも**「prerelease documentation(プレリリース文書)であり変更される可能性がある」「プレビュー機能は本番運用を意図していない」と明記**されている([Microsoft Learn](https://learn.microsoft.com/en-us/microsoft-copilot-studio/knowledge-code-interpreter-structured-data))。ファイルサイズ上限は形式を問わず16MB、最大10ファイルという厳しい制約があり、独自Pythonライブラリのアップロード機能についての記載は一切ない。GA化時期についてはWebSearch経由の未検証情報(2026年5月31日GA説)と公式ページの「preview」表記が矛盾しており、少なくとも本番運用の基盤として依拠できる状態にはない。

3者を横断比較すると以下のようになる。

| 項目 | Gemini API Code Execution | ChatGPT(Responses API Code Interpreter) | M365 Copilot Studio Code Interpreter |
| --- | --- | --- | --- |
| 独自ライブラリインストール | 公式に不可と明記 | 非公式情報のみ(内部PyPIミラー経由は可能との報告) | 記載なし(想定用途外) |
| 実行時間 | 30秒固定 | コンテナ20分アイドルで失効 | 不明(プレビューのため未記載) |
| ファイルサイズ上限 | トークンウィンドウ依存 | 明記なし(UIは512MBとの二次情報) | 16MB/ファイル、最大10ファイル |
| 永続性 | ターン単位、恒久保持なし | 同一コンテナ内のみ(20分) | プレビュー、本番非対象 |
| 成熟度 | GA(ただし機能制限が明確) | GA(ただし非公式挙動が多い) | プレビュー |

さらに、3プラットフォームいずれについても「独自DSLパーサーやIR処理ロジックをコード実行サンドボックスにアップロードし、大規模データ変換パイプラインの一部として使った」という直接的な実例・ケーススタディは見つからなかった。Microsoftの`dsl-copilot`のような近傍事例は「LLMに文法を学習させる」取り組みであり、サンドボックスへのパッケージアップロードではない([dsl-copilot](https://awesome.ecosyste.ms/projects/github.com%2Fmicrosoft%2Fdsl-copilot))。これは情報不足ではなく、この運用パターン自体が技術的障壁の大きさゆえにまだ実践例が存在しないニッチな領域であることを示している。

**結論として、ユーザーが想定する運用フロー(④⑤)は現時点では推奨できない。** 代替として、変換モジュール本体は**ローカル(ユーザーのPC)またはCI/サーバー環境で動くPythonパッケージとして実行**し、PADフロー・JSONダンプの取り込み、IR構築、コード生成、構文検証までを決定的に完結させる。LLMは、変換パイプラインの外側から**API経由(Anthropic Messages API等)またはChatGPT/Gemini/CopilotのチャットUI経由で、個別の曖昧判断だけを問い合わせる**——例えば「このセレクタ候補のうちどれが意図された要素か」「この3つのトレースの差分は終了条件として扱うべきか」「このUI要素名から推測される業務的な意味は何か」といった、決定的ロジックでは解けないピンポイントの質問に限定する。この設計であれば、サンドボックスの実行時間・容量・永続性の制約を一切受けず、かつLLMの推論力を最も必要な箇所にのみ投入できる。

## 決定的ハーネスとLLM判断の分担が実装の中核になる

この「ローカル決定的処理+LLMへのピンポイント質問」という役割分担は、実はエージェント型コーディングツールの設計原則そのものである。Claude Codeは「言語モデルはより大きな決定的インフラストラクチャに埋め込まれた小さな構成要素にすぎないシステム」と評され([aman.ai](https://aman.ai/primers/ai/claude-code/))、GitHub Copilot Workspaceは「Task→Specification→Plan→Code」という段階的フローを取り、各段階の出力(仕様・計画)を人間がレビュー・編集できる構造にしている([GitHub Next: Copilot Workspace overview](https://github.com/githubnext/copilot-workspace-user-manual/blob/main/overview.md))。OpenAI Codexもハーネスがツール呼び出しを実行し、その出力をコンテキストに追加して再度モデルに問い合わせるエージェントループを中核とし、生成コードは手動レビュー・検証が依然として必須であると強調する([dev.to解説](https://dev.to/_37bbf0c253c0b3edec531e/openais-codex-what-it-ishow-to-work-and-how-to-use-2gem))。これらの設計をチャット型LLM運用に翻案すると、**「IR正規化・バリデーション・ファイル分割・テンプレート展開」は決定的な前処理コード側で行い、「曖昧なUI要素のセレクタ解釈」「アクション列の意味的なまとまりの把握」「エラーハンドリング方針の判断」のような曖昧性の高い部分だけをLLMに委ねる**分担が妥当である。

コンテキストの渡し方にも明確な指針がある。長いコンテキストを一度に渡すほどLLMの性能は連続的に劣化し、Liu et al.(TACL 2024)の"lost in the middle"研究では、関連情報が入力の中間に位置する場合、先頭・末尾に位置する場合と比べて精度が30%以上低下するU字型の性能曲線が報告されている([Context Rot](https://www.morphllm.com/context-rot)経由の要約)。PAD IRを丸ごと一括でLLMに投げるアプローチは、IRが大規模になるほど一貫性低下(関数間の変数名不整合、重複定義)を招くリスクが高いため、**IRをサブフロー/アクショングループ単位に機械的に分割し、各チャンクの出力をJSON Schema等で構造検証する決定的なポストプロセスを挟む**設計が必要になる。また「同じLLMにコードとテストの両方を書かせない」という自己確認ループの問題(ConAIR研究はLLM生成テストをそのまま一貫性信号に使うと平均37.7%の誤り率になると報告: [arXiv:2411.15587](https://arxiv.org/pdf/2411.15587))を避けるため、期待される入出力やアサーションはIR側で先に固定し、LLMには「仕様通りか」の検証だけを委ねるべきである。

ライブラリ知識の正確性については、API文書をコンテキストに追加するDocumentation Augmented Generation(DAG)が低頻度APIの幻覚を大きく改善するという実証がある(CloudAPIBenchベンチマーク: [arXiv:2407.09726](https://arxiv.org/pdf/2407.09726))。pywinauto/pyautoguiそのものを対象にした実証は見つからなかったが、近縁領域のSelenium(DOMに根拠づけたRAG)ではスクリプト実行成功率が標準生成の30%からRAGグラウンディングで90%まで改善したという報告があり([Autonomous QA Agent preprint](https://engrxiv.org/preprint/view/5891))、同様の効果がpywinauto/pyautoguiにも期待できると推測される。したがって、変換モジュールがLLMに問い合わせる際は、ライブラリソース全体ではなく**厳選したAPIリファレンス抜粋+2〜3個の正しい使用例スニペット**を同梱し、生成されたAPI呼び出し名をライブラリの実シンボル一覧と機械的に照合する決定的な後検証ステップを設けるべきである。この点は、前回調査で確認した「pywinauto/pyautoguiへのアクション対応表自体が一次整理であり、既存の確立された対応情報が存在しない」という事実とも整合し、LLMの事前学習データだけに依拠するリスクを裏付ける。なお、RPA→Python変換の最も近い実例であるBotCityの"Gemini Phoenix"は、UiPathの`project.json`/`Main.xaml`を読み込み各アクティビティをPython(Selenium/BotCity SDK)にマッピングするカスタムGeminiエージェントとして実装されており([documentation.botcity.dev](https://documentation.botcity.dev/how-to/gemini-botcity-phoenix/))、これはLLMをAPI経由でパイプラインに統合する(チャットUIのサンドボックスに依存しない)という本提案の方向性を補強する一次証拠である。Sema4.ai(旧Robocorp)のチームも、機械的なRPA→Python変換は「質が低いボットになりがちで、プロセス自体の再構築を推奨する」と自らの経験から釘を刺しており([sema4.ai](https://sema4.ai/docs/automation/faq/to-python-automation))、本プロジェクトが「完全自動変換」ではなく「人手レビュー前提の半自動変換支援」を目標に据えるべきという前回調査の結論を再確認させる。

## 統合アーキテクチャ:4フェーズのロードマップと主要リスク

以上3つの拡張要件を統合すると、推奨アーキテクチャは前回提案の「パーサー→IR→コードジェネレータ」の三層構造を拡張し、**(a)制御dumpスクリプトによる画面状態キャプチャ、(b)アクション+画面状態のペアを保持するセマンティックIR、(c)複数トレース比較によるループ/分岐候補抽出(human-in-the-loop確認付き)、(d)決定的コード生成+ライブラリAPI照合、(e)曖昧判断のみをLLM APIに問い合わせる外部呼び出し層**の5コンポーネントから成る。全体はローカル(またはCI/サーバー)で実行されるPythonパッケージとして実装し、チャット型LLM(ChatGPT/Gemini/M365 Copilot)は「ピンポイントの質問を投げてテキスト回答を受け取るだけの外部サービス」として扱う。この構成は、変換モジュールをLLMサンドボックスにアップロードして実行させるという当初想定の運用を置き換えるものであり、サンドボックスの実行時間・容量・永続性という制約条件を一切受けない。

フェーズ分けは次の4段階を推奨する。

| フェーズ | 範囲 | 主な成果物 |
| --- | --- | --- |
| フェーズ0: フォーマットとIRスキーマ確定 | 前回調査のクリップボードDSL収集に加え、制御dumpスクリプトのUIAツリー/スクリーンショット出力形式を確定。IRのエンベロープ(`schema_version`, `trace_id`, 候補要素リスト等)をJSON Schemaとして固定 | PAD DSL文法(EBNF)、IR JSON Schema、制御dumpスクリプトのプロトタイプ |
| フェーズ1: コア変換器+単一トレースIR | ウィンドウ操作・変数設定・If/Loop・エラーハンドリングを対象に、パーサー→IR→コードジェネレータを実装。画面状態は参照のみ保持し、ゴールデンファイルテストを整備 | 単一フロー変換CLI、ゴールデンテストスイート |
| フェーズ2: 複数トレース比較とhuman-in-the-loop UI | 複数のIR(同一操作の複数回記録)を行アラインメントし、ループ本体・ループ変数の候補を自動抽出。終了条件候補は人間に確認ダイアログで提示し、承認後に単一の一般化Pythonフローへ合成 | トレース比較エンジン、終了条件確認UI(CLIまたは簡易Web) |
| フェーズ3: LLM外部呼び出し層とロングテール対応 | セレクタ解釈・未対応アクション処理・pywinauto/pyautoguiのAPI照合など曖昧判断をAPI経由でLLMに問い合わせる層を実装。画像/OCR系・Block Input等のネイティブAPI依存アクションのラッパーを追加し、診断レポート機能を仕上げる | LLM問い合わせモジュール(プロンプトテンプレート+API照合の決定的検証)、未対応アクション診断レポート |

主要なリスクと対応策は以下の4点に整理できる。第一に、**終了条件の誤推測**(複数トレース比較が誤った境界を提示するリスク)に対しては、フェーズ2のhuman-in-the-loop確認を必須のゲートとし、自動推測結果を「候補」として提示するに留め、人間の明示的承認なしにコード生成へ進めない設計とする。第二に、**LLMサンドボックス運用への過度な期待**(当初の運用イメージ④⑤への固執)に対しては、本調査の制約一覧(Gemini 30秒/インストール不可、ChatGPT 20分失効、M365 Copilotプレビュー)を関係者に明示し、変換モジュールはローカル実行が前提であることを早期に合意形成する。第三に、**ニッチライブラリのAPI幻覚**(pywinauto/pyautoguiの誤った呼び出し生成)に対しては、厳選したAPIリファレンス抜粋の同梱と、生成コードに対する機械的なシンボル照合・`ast.parse`による構文検証を必須のポストプロセスとする。第四に、**画面状態ダンプの肥大化**(スクリーンショット・UIAツリーの蓄積によるストレージ/レビュー負荷)に対しては、JSON本体には外部ファイル参照と軽量な`alt_text`要約のみを持たせ、LLM入力時にのみ必要な画像を動的にbase64化する2段階方式を徹底し、長期保存時は古いトレースの生データを定期的にアーカイブ/間引く運用ルールを設ける。

## 結論

今回の拡張調査が明らかにした最大の洞察は、「画面状態のセマンティックIR化」「複数トレースの一般化」「LLMサンドボックス運用」という3つの拡張要件が、個別には異なる分野(GUIエージェント研究、PBD/プロセスマイニング、SaaS実務制約)に属していながら、**いずれも最終的に同じ設計原則——決定的な構造化処理を手厚くし、LLMの役割を曖昧な判断の補助に限定する——に収斂する**ことである。PADフロー変換という課題は、UIセレクタの脆さや非公開フォーマットといった前回調査が示した技術的制約だけでなく、「ユーザーが想像する運用イメージ(LLMサンドボックスにライブラリをアップロードして丸投げする)」そのものが2026年11月時点の商用LLMサービスの成熟度を超えているという、運用レベルの制約にも向き合う必要がある。この現実を早期に関係者と共有し、ローカル実行の決定的パイプラインを軸とする設計に合意形成できれば、本プロジェクトは「完全自動変換」という過大な目標を掲げずに、「複数回の実演から一般化されたPythonスクリプトを半自動生成し、人間が終了条件とセレクタだけを確認する」という、既存研究の知見(SmartRPA、Rousillon、WebRobot)とも整合する、十分に実現可能な範囲の価値提供に着地できる。
