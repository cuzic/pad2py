# LLM駆動コード生成アーキテクチャパターン・ベストプラクティス（IR/JSON→Pythonコード生成）

対象範囲: PADフロー由来の構造化中間表現(IR/JSON)を、ChatGPT/Gemini/M365 Copilotなどチャット型LLMサービスに参照ライブラリとともに渡し、LLM自身にPythonコード生成を行わせる運用の設計妥当性に関する調査。

## Q1. 「構造化された仕様からのLLM支援コード生成」(spec-to-code)に関する既存パターンと、few-shot手法の効果

### Takeaway
構造化仕様→コード生成では「構造化された中間分析/IRを挟む」「仕様を検証可能な形で明示する」「few-shotは少数でも効くが、ランダム選択よりも類似事例の検索選択(retrieval-based selection)の方が有効」という3点が共通して支持されている。ただしfew-shotの効果はタスクのドメイン特化度が高いほど小さくなる傾向がある。

### Cited Findings
- SpecCoderは、生のrequirementsとコードの間に構造化された仕様分析(structured specification analysis)を挟み、まず仕様に基づくファインチューニングで構造化分析を生成させ、その後カリキュラム型のデュアルタスク強化学習(生成+判別を同時最適化)で性能を上げるという2段階構成を取る — [SpecCoder (arXiv 2609.06041)](https://arxiv.org/pdf/2609.06041)
- 自動車向け組み込みソフトウェアのspec2code研究では、高位/低位/形式仕様からの初期生成と、バックプロンプトによる反復的な改善を組み合わせるパイプライン（生成・検証・フィードバック収集・モデル更新のバランス調整が必要）を提案している — [Towards Specification-Driven LLM-Based Generation of Embedded Automotive Software (arXiv 2411.13269)](https://arxiv.org/pdf/2411.13269)
- 2026年の論文は、構造化仕様をLLM入力として使うことでリポジトリレベルの高品質コード生成が実現可能になり、同時に検証可能性(verifiability)も高まると論じている — [LLM-Assisted Repository-Level Generation with Structured Spec-Driven Engineering (arXiv 2605.02455)](https://arxiv.org/pdf/2605.02455)
- 実務ガイドは「仕様の質がAIコード生成の質を決める」「制約が具体的か、統合ポイントが特定されているかをチェックし、チェックが通らなければ生成前に仕様を洗練する」ことを推奨している — [Spec-driven development: from requirements to reliable code with AI (kinde.com)](https://kinde.com/learn/ai-for-software-engineering/using-ai-for-apis/spec-driven-development-from-requirements-to-reliable-code-with-ai/)
- コードの脆弱性検出タスクにおいて、検索によって選ばれたfew-shot例(retrieval-selected demonstrations)は、ランダムに選んだ例よりも全てのshot数で優れており、特に3〜5shotで差が最大化される。一方でk=1〜2では効果があるが、例を増やすと劣化する傾向がある — [Retrieval-Augmented Few-Shot Prompting Versus Fine-Tuning for Code Vulnerability Detection (arXiv 2512.04106)](https://arxiv.org/pdf/2512.04106)
- コード要約タスクでは、固定の例ではなくBM25で選んだ例示(exemplar)を使うことで有意な性能向上が報告されている — [Automatic Semantic Augmentation of Language Model Prompts (arXiv 2304.06815)](https://arxiv.org/pdf/2304.06815)
- Nashid et al.の研究では、少数の適切に選ばれたコード例示により、テストアサーション生成で76%、プログラム修復で52%の完全一致精度を達成した — [CODEX論文概要 (synapsesocial.com summary of ICSE 2023 paper)](https://synapsesocial.com/papers/W4384302749)
- ドメイン特化のtext-to-codeタスクを対象にした2026年のarXiv研究では、few-shotプロンプティングによる類似度向上はわずかであり、検索ベースのRAGの方がドメイン整合性においてより一貫した効果を示した — [Exploring different approaches to customize language models for domain-specific text-to-code generation (arXiv 2603.16526)](https://arxiv.org/pdf/2603.16526)
- COCOGENは構造化されたcommonsense出力をPythonコードとして表現し、Codexにfew-shot例を与えてプロンプトする。コード形式のプロンプトはコードモデル(Codex)にはテキストモデルより効果が大きく、典型的なコード規約に似た形式であるほど有用だった。わずか15例でCodexがより大きなファインチューニング済みモデルをスクリプト/グラフ生成タスクで上回ったと報告されている — [COCOGEN summary (hackernoon.com)](https://hackernoon.com/structured-llm-prompts-drive-better-results-with-cocogen)

### Inferences
- PAD IR→Pythonコード生成においても、「IR→Pythonコード」の少数の対になった例(few-shot)をプロンプトに含めることは有効だが、例の数を増やしすぎると却って劣化しうるため、2〜5個程度の「多様で代表的な」ペア例に絞るのが妥当と考えられる。
- ランダムに選んだ静的な例よりも、変換対象のIRアクション種別(例: クリック操作、ファイル操作、条件分岐)に類似した例を動的に選んで提示する(retrieval的選択)方が品質向上に寄与する可能性が高い。
- PADのアクション(例: `UI.Click`, `File.Copy`)はニッチなドメインであるため、few-shotの効果は限定的になりうる(2603.16526の知見)。この場合は構造化IR自体の表現の質(命名の一貫性、型情報の明示)がより重要になる。

### Gaps
- 「PADのような業務フロー型IR」に特化した spec-to-code の実証研究は見つからなかった。一般的なプログラム合成・DSL研究からの類推に留まる。
- few-shot例の最適な「個数」や「選択アルゴリズム」についての定量的なコンセンサス値(例: 「3例が最適」等)を直接裏付ける一次資料は見つからなかった。

---

## Q2. エージェント型コーディングツール(Claude Code / Copilot Workspace / Codex)における決定的処理とLLM判断の分担設計

### Takeaway
主要なエージェント型コーディングツールは共通して「ハーネス(決定的な実行基盤・ツール呼び出し制御・ファイルI/O・サンドボックス)」と「モデル(曖昧な意思決定・計画・コード本文の生成)」を明確に分離する設計を取っている。Claude Codeは特に「コードベースの大部分が決定的インフラであり、AIの判断はごく一部」という比率が報告されている。Copilot WorkspaceはTask→Spec→Plan→Codeという段階的フローで、各段階の出力(仕様・計画)を人間がレビュー・編集できる構造にしている。

### Cited Findings
- ある分析ではClaude Codeを「言語モデルはより大きな決定的インフラストラクチャに埋め込まれた小さな構成要素にすぎないシステム」と表現している — [claude code (aman.ai)](https://aman.ai/primers/ai/claude-code/)
- 2026年の"Dive into Claude Code"レポートの二次分析によれば、Claude Codeのコードベースの98.4%が決定的インフラ、1.6%がAI判断ロジックという比率が報告されている（この数値は原典ではなく二次的なリポジトリ要約からのもので、裏取りが必要） — [Dive-into-Claude-Code secondary summary (sourcepulse.org)](https://www.sourcepulse.org/projects/28324983)
- Karpathyの見解(記事内の引用)として、LLMは決定を変動させる役割を持ち、実行自体は固定され、ツールは検索やファイル読み込みのような決定的ロジックをラップする。LLMはツールを選択するが、ツール自体がロジックを実行する、という分担が述べられている — [Stop Asking LLMs to Grep (news.lavx.hu)](https://news.lavx.hu/article/stop-asking-llms-to-grep-why-deterministic-tasks-belong-to-programs-not-ai)
- あるレビューはAIエージェントの設計を「固定ワークフロー」「自律エージェント」「ハイブリッド」に分類し、ハイブリッド(ワークフローのシェル+エージェントのコア)が成熟した本番システムで最も一般的だと述べている — [Peering Inside the Engine (akmaier.substack.com)](https://akmaier.substack.com/p/peering-inside-the-engine-diving)
- GitHub Copilot Workspaceは「Task → Specification → Plan → Code」というフローを取る。Specificationは実装詳細ではなく成功基準を定義するものとされ、実装の詳細はPlanフェーズに委ねられる。Planは仕様をコード変更・テストなどのステップに分解したもので、ユーザーが進む前に編集できる。コードは承認済みのPlanから生成され、変更ファイルがレビュー用に表示される — [GitHub Next: Copilot Workspace overview](https://github.com/githubnext/copilot-workspace-user-manual/blob/main/overview.md); [Copilot Workspace概要 (zilliz.com)](https://zilliz.com/blog/what-is-copilot-workspace-and-why-it-matters)
- OpenAI Codexはエージェントループ(ハーネスがツール呼び出しを実行し、その出力をコンテキストに追加して再度モデルに問い合わせる)を中核とし、ハーネスがツール利用を媒介し、実行を監査可能にし、長時間タスクでモデルの軌道維持を助けるとされる — [OpenAI Codex解説 (dev.to)](https://dev.to/_37bbf0c253c0b3edec531e/openais-codex-what-it-ishow-to-work-and-how-to-use-2gem)
- Codexはクラウド実行時にサンドボックスで動作し、worktreeにより並列エージェントスレッドが競合を避けられる。生成コードは手動レビュー・検証が依然として必須であるとOpenAIは強調している — [同上]
- Anthropicの公式エンジニアリング記事(2025年9月)は、ツールを「決定的システムと非決定的エージェントの間の契約」と定義し、従来の人間向けAPI設計をそのまま流用せず、エージェント向けにツールを再設計すべきと述べている — [Writing effective tools for agents (Anthropic, via 二次要約)](https://byteflare-co.github.io/anthropic-engineering-ja/anthropic/pdfs/08_writing-tools-for-agents.pdf)

### Inferences
- これらの設計パターンをチャット型LLM運用に翻案すると、「IR正規化・バリデーション・ファイル分割・テンプレート展開」などは決定的な前処理コード(Pythonスクリプト等)側で行い、「曖昧なUI要素のセレクタ解釈」「アクション列の意味的なまとまりの把握」「エラーハンドリング方針の判断」のような曖昧性の高い部分だけをLLMのチャットに委ねる、という分担が妥当と考えられる。
- Copilot Workspaceの「Spec→Plan→Code」のように、IR全体を一括でコード化させる前に、まず「変換計画(どのIRノードをどの関数/クラスにマッピングするか)」を中間生成物としてLLMに出力させ、人間がレビューしてから実コード生成に進む2段階フローが、チャットUI運用でも再現しやすく、エラーの早期発見に資する。
- Claude Code/Codexのような「ハーネスが大部分」という比率は、API駆動エージェントに特有の設計であり、チャットUI(ChatGPT/Gemini/Copilot)単体ではハーネス相当の決定的処理を人間(またはチャット外のスクリプト)が担う必要がある。つまりチャットUI運用では「決定的処理」は会話の外、すなわちIR生成・検証・後処理のユーザー側パイプラインに追い出す設計が必須になる。

### Gaps
- OpenAIやGitHubの公式ブログ記事で「決定的処理とLLM判断の分担」を明示的に論じた一次資料には到達できなかった(検索結果は二次解説が中心)。Anthropicの"Writing effective tools for agents"原文も直接フェッチできず、二次要約止まりとなった。
- Copilot Workspaceは2025年12月時点で「Technical Preview (Deprecated/Transitioned)」と分類されている二次資料があったが、GitHub公式での現在のステータスは未確認。この設計パターン自体の有効性ではなく製品継続性に関する留保点として記録する。

---

## Q3. 大きな構造化仕様の一括投入 vs チャンク分割/反復生成——信頼性・一貫性の差と対策

### Takeaway
長いコンテキストを一度に渡すほどLLMの性能は連続的に(cliffではなく緩やかに)劣化し、特に関連情報がコンテキストの中間に埋もれると性能が大きく落ちる("lost in the middle")。対策としては、構文/意味単位でのチャンク分割、テスト駆動の反復生成、出力のスキーマ/構造検証、そして「同じエージェントに生成とテスト両方を書かせない」という自己検証の限界を踏まえた設計が推奨される。

### Cited Findings
- Chromaのベンチマークでは18のフロンティアモデルを対象に、コンテキスト長が伸びるほど性能が劣化することを確認しており、劣化は急激な崖ではなく連続的であると報告されている。200Kトークンのコンテキストウィンドウを持つモデルでも、5万トークン程度で有意な劣化が見られるとされる — [Context Rot (morphllm.com)](https://www.morphllm.com/context-rot)（Chroma研究の二次要約であり、原著の裏取りが望ましい)
- Liu et al. (TACL 2024)の"lost in the middle"研究では、関連文書が入力の中間(20文書中5〜15番目)に位置する場合、先頭・末尾に位置する場合と比べて精度が30%以上低下するU字型の性能曲線が報告されている — [Context Rot (morphllm.com)](https://www.morphllm.com/context-rot)
- 2026年のバグ修正に関する長文コンテキスト研究では、Qwen3-Coder-30B-A3Bは64kトークンのコンテキストで解決率わずか7%、GPT-5-nanoは1件も解決できなかったと報告されている(日本語要約経由、原文未確認) — [The Limits of Long-Context Reasoning in Automated Bug Fixing (fugumt.com要約)](https://fugumt.com/fugumt/paper_check/2602.16069v1)
- LongCodeZipは、RAGがテキスト類似度のみに依拠しがちで暗黙的な依存関係を見落とす可能性を指摘し、関数レベルのチャンク化とパープレキシティベースの枝刈りを提案している — [LongCodeZip (arXiv 2510.00446)](https://arxiv.org/html/2510.00446v1)
- AST(抽象構文木)ベースのチャンキングは、関数定義や制御構造など意味的な境界でコードを分割し、各チャンクが構文的に有効な状態を保つという実務知見が紹介されている — [RAG for LLM Code Generation Using AST-Based Chunking (medium.com)](https://medium.com/@vishnudhat/rag-for-llm-code-generation-using-ast-based-chunking-for-codebase-c55bbd60836e)
- TGen論文(テスト駆動のコード生成)は、問題とテストケースを同時に与えることでMBPPで+12.0%、HumanEvalで+8.5%の正答率向上を報告し、さらに修復ループ(最大5回反復、または同じテストが3回連続で失敗したら停止)を追加するとMBPPで+2.8%、HumanEvalで+3%の追加向上があったとされる。検証はPyTestで実行し、テスト自体は変更不可とする設計 — [Test-Driven Development for Code Generation (themoonlight.io要約)](https://www.themoonlight.io/en/review/test-driven-development-for-code-generation)
- 「自己確認ループ(self-confirming loop)」の問題として、同じAIエージェントがコードとテスト両方を書くと、誤った挙動を"確認"するテストが生成され得るという実務上の指摘があり、対策としてエージェントがコードに触れる前に受け入れ基準(acceptance criteria)を先に書くことが提案されている。また、LLM出力に対しては内容そのものではなく構造・スキーマを検証する設計(ハーネス・データフロー・スキーマ検証は決定的に保つ)が推奨される — [Testing AI-Generated Code: The Self-Confirming Loop (codemyspec.com)](https://codemyspec.com/blog/agentic-testing)
- ConAIR研究では、LLMが生成したテストをそのまま一貫性信号として使うと誤り率が高く(HumanEval/HumanEval+/MBPPで平均37.7%)、ユーザーフィードバックを反復中に組み込んでテストを補正する手法を提案している — [ConAIR (arXiv 2411.15587)](https://arxiv.org/pdf/2411.15587)
- 自動車向けembedded Cを対象にしたspec2codeの実証では、単発(非反復)生成でも一部仕様については形式検証済みコードを生成できたが、曖昧・不完全な仕様が失敗の主要因として挙げられている — [spec2code (alphaxiv概要)](https://alphaxiv.org/overview/2411.13269v1)
- SpecCoder/Specine系の研究では、基礎モデルの生成コードが反復を重ねるうちに自身の仕様分析からドリフト(逸脱)し、5回の改善反復を経てもpass率が40%で停滞したと報告されている — [SpecCoder (arXiv 2609.06041)](https://arxiv.org/pdf/2609.06041)

### Inferences
- PAD IRをまとめて一度にLLMへ渡すアプローチは、IRが大規模(多数のアクション・フロー)になるほど「lost in the middle」的な劣化や生成の一貫性低下(関数間の変数名の不整合、重複定義など)を招くリスクが高いと推測される。
- 対策としては、(a)IRをサブフロー/アクショングループ単位に機械的に分割してLLMに渡す、(b)各チャンクの出力をJSON Schema等で構造検証する決定的なポストプロセスを挟む、(c)生成コードに対する期待動作(入出力例)を仕様側で先に固定し、LLMにテストを書かせきらない、という3点がチャット運用でも実装可能な緩和策になる。
- 「同じLLMにコードとテストの両方を書かせない」という自己確認ループの問題は、チャット型運用(1つのチャットスレッドでコード生成も検証も行う)でこそ顕著に起こりうるため、IR側に期待される入出力やアサーションをあらかじめ明示し、LLMに「仕様通りか」を検証させる設計が重要になる。

### Gaps
- 「巨大な構造化仕様(IR)を一括投入する場合」と「チャンク分割/反復生成する場合」を直接比較した定量的なアブレーション研究(特にコード生成タスクに限定したもの)には到達できなかった。関連する知見はバグ修正・QAタスクの長文コンテキスト研究からの類推である。
- ChatGPT/Gemini/Copilotのような商用チャットUIにおける実際のコンテキストウィンドウ上限とそこでの劣化特性(各サービスのUI上のファイルアップロード機能が内部的にどうチャンク化・要約しているか)は、一次資料で確認できなかった。

---

## Q4. ライブラリ/フレームワークをコンテキストとしてアップロードする設計パターン(API文書・使用例・RAG)

### Takeaway
API文書をコンテキストに追加する「Documentation Augmented Generation (DAG)」は、特に低頻度(ニッチな)APIに対する幻覚(hallucination)を大きく減らすという実証結果がある。一方で高頻度APIでは検索(リトリーバル)の精度が悪いと逆に性能を下げる場合があり、「何を・どれだけ・どう提示するか」の設計が成果を左右する。生成コードは検索によって根拠づけられても正しさが保証されるわけではなく、コンパイル・テスト・静的解析による検証が依然として必要とされる。

### Cited Findings
- 研究論文「On Mitigating Code LLM Hallucinations with API Documentation」は、API幻覚を測定するベンチマークCloudAPIBenchを提示し、取得したAPI文書をプロンプトに追加するDocumentation Augmented Generation (DAG)手法が低頻度APIの性能を大きく改善する一方、検索器が最適でない場合には高頻度APIの性能を悪化させることがあると報告している。著者らはモデルの確信度を確認し、生成されたAPI名を文書化済みAPIのインデックスと照合して検証することを提案している — [On Mitigating Code LLM Hallucinations with API Documentation (arXiv 2407.09726)](https://arxiv.org/pdf/2407.09726)
- Santa Clara大学の学生論文(2025年、査読なし)は、公式API文書をベクターDBに埋め込みドキュメント対応のRAGパイプラインを構築し、プロンプトへの文書追加でコード幻覚を最大60%低減したと報告している(単一の未査読論文であり参考値として扱うべき) — [学位論文 (scholarcommons.scu.edu)](https://scholarcommons.scu.edu/cseng_senior/319)
- geoSurgeのアーキテクチャ概要は、検索はグラウンディングを改善するが正しさを保証しないため、コンパイル・テスト・静的解析による検証を併用すべきと述べている(権威性は低いソース) — [Retrieval-Augmented Code Generation (geosurge.ai)](https://geosurge.ai/corpus/gen-3218/program-synthesis/retrieval-augmented-code-generation.html)
- Anthropicの"Writing effective tools for agents"の文脈では、ツールを「決定的システムと非決定的エージェントの間の契約」と位置づけ、人間向けAPIをそのまま流用せずエージェント向けに再設計すべきと述べている(ライブラリドキュメント設計にも転用可能な原則) — [前掲 (byteflare-co.github.io)](https://byteflare-co.github.io/anthropic-engineering-ja/anthropic/pdfs/08_writing-tools-for-agents.pdf)
- Anthropicの"effective context engineering for AI agents"記事(本調査でWebFetch済み)は、「コンテキストは有限のリソースであり収益が減少していく("diminishing marginal returns")」という原則を提示し、最小限のプロンプトから始めて失敗観察に基づいて指示・例を追加すべきとしている。また、ファイルパス・保存済みクエリ・Webリンクのような「軽量な参照」を保持し、必要時にのみ内容をロードするハイブリッド手法(一部を事前ロード、残りをオンデマンド取得)を推奨している — [Effective context engineering for AI agents (Anthropic)](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)（本調査でWebFetchにより直接取得・要約)
- ChatGPTのProjects機能やCustom GPTのKnowledge filesは、モデルの訓練知識を超える情報をアップロードファイルで拡張する機能を持つとされ、リポジトリ全体を1つのインデックス済みファイルにパックしてアップロードする運用例が紹介されている(2025年時点でGPTs/Assistantsのリトリーバル対応ファイル数上限は20件とされていたが、現行の制限は要確認) — [CodebaseChat (blog.context.ai)](https://blog.context.ai/codebasechat); [news.bensbites.co記事](https://news.bensbites.co/posts/13455-codebasechat/out)

### Inferences
- PAD IR→Pythonコード生成の文脈でも、「参照ライブラリをアップロードする」こと自体はhallucination低減に有効と期待できるが、単にソースコード全体を投げ込むのではなく、(a)使用頻度の高いAPI呼び出しパターンを明示する使用例スニペット、(b)docstring/型シグネチャを抽出したリファレンス、(c)生成されたAPI呼び出し名をライブラリの実シンボル一覧と後から照合する決定的な検証ステップ、を組み合わせる方が、Anthropicの「有限リソース」原則やDAG研究の知見と整合する。
- チャット型LLMサービス(ChatGPT Projects、Gemini、M365 Copilot)でのアップロードは、サービス内部でRAG的な検索・チャンク化が行われている可能性が高く、アップロードするファイル量・形式(全ソースコードか抜粋か)によって検索精度が変動しうる。したがって「ライブラリ全体をそのままアップロード」よりも「APIリファレンス+厳選された使用例」に絞って提供する方が、高頻度/低頻度APIのバランスを考えてもリスクが低いと考えられる。

### Gaps
- ChatGPT Projects/Gemini/M365 CopilotがアップロードされたファイルをどのようにRAG的に処理しているか(チャンクサイズ、埋め込みモデル、検索アルゴリズム)についての公式ドキュメントには到達できなかった。これは各ベンダーの非公開実装詳細である可能性が高い。
- 「ライブラリ使用例スニペットの提供」と「ライブラリソース全体へのRAG」を定量的に比較した実証研究は見つからなかった。

---

## Q5. ニッチなライブラリ(pywinauto/pyautoguiなど)のAPI知識不正確問題へのRAG/function calling対応

### Takeaway
pywinauto/pyautoguiに特化した研究・実証事例は見つからなかったが、近縁領域であるUIオートメーション(Selenium)でのRAGグラウンディングは、標準LLM生成と比べてスクリプト実行成功率を大きく改善する(30%→90%)という実証がある。一般論として、ニッチ/低頻度APIほどAPI文書によるグラウンディング(DAG)の効果が大きいという知見(Q4)がpywinauto/pyautoguiにも適用可能と推測されるが、直接の検証は確認できていない。

### Cited Findings
- 自律QAエージェントに関するプレプリントでは、ページ構造(DOM)に根拠づけたRAGシステムがスクリプト実行成功率を90%まで高めた一方、標準的なLLM生成では30%に留まったと報告されている。著者らはこの向上を「実際のDOMに生成を根拠づけたこと」によるものと説明しているが、評価は単一ドメインに限定されている(pywinauto/pyautoguiではなくSeleniumが対象) — [Autonomous QA Agent preprint (engrxiv.org)](https://engrxiv.org/preprint/view/5891)
- エージェントにおける幻覚はツール呼び出しや計画のステップを経るごとに複合化し、1つの誤ったステップがワークフロー全体に伝播するとされる。ツール関連のリスクとして、誤ったAPI呼び出し、誤ったデータの受け渡し、実際には完了していない操作を「完了」と報告することが挙げられている — [How to Reduce AI Agent Hallucinations and Improve Reliability (analyticsinsight.net)](https://www.analyticsinsight.net/artificial-intelligence/how-to-reduce-ai-agent-hallucinations-and-improve-reliability)
- RAGはグラウンディングを助けるが、モデルが取得したコンテキストを無視することもあるため、それ単独では幻覚を防げないという指摘がある。対策として、取得源に対する出力の検証(操作が実際に成功したかの確認を含む)が推奨される — [What is RAG hallucination? (scality.com)](https://www.scality.com/topics/what-is-rag-hallucination/); [analyticsinsight.net 前掲]
- 検出手法として、回答をアトミックな主張に分解し、各主張を取得コンテキストに対して照合し、裏付けのない主張があれば警告するLLM-as-a-judge方式が一般的であるとされる — [Automatically Detecting Hallucinations in RAG Applications (traceloop.com)](https://traceloop.com/blog/automatically-detecting-hallucinations-in-rag-applications)
- 実務的な緩和策として、低temperature設定、構造化出力、ツール呼び出しの検証、リスクの高いアクションに対する人間レビュー、継続的テストが挙げられている — [analyticsinsight.net; agentwiki.org (Why is my agent hallucinating)](https://agentwiki.org/why_is_my_agent_hallucinating)
- Q4で確認したDAG研究(CloudAPIBench)の知見—低頻度APIに対するAPI文書追加が性能を大きく改善する—は、pywinautoやpyautoguiのような低頻度・ニッチAPIに外挿できる可能性が高いと考えられるが、これらのライブラリ自体を対象とした実証ではない — [On Mitigating Code LLM Hallucinations with API Documentation (arXiv 2407.09726)](https://arxiv.org/pdf/2407.09726)

### Inferences
- pywinauto/pyautoguiのような比較的ニッチなライブラリについては、LLMの事前学習データ中の出現頻度が低く、API名・引数・戻り値の幻覚リスクが高いと推測される(Q4のDAG研究における「低頻度API」の知見からの外挿)。
- 対策として、(a)pywinauto/pyautoguiの公式APIリファレンス(関数シグネチャ・docstring)を抜粋してコンテキストに含める、(b)典型的な操作パターン(ウィンドウ取得→コントロール検索→操作)の正しい使用例スニペットを2〜3個程度few-shotとして提示する、(c)生成されたAPI呼び出しをライブラリの実シンボル一覧(例: `dir(pywinauto)`相当のリスト)と機械的に照合する決定的な後検証ステップを設ける、という3段構えがSelenium事例のRAGグラウンディング(30%→90%)の知見とも整合的である。
- チャット型LLM運用では、ライブラリのソース全体へのRAG(ベクター検索)を自前で組むことは困難なため、実務的には「厳選したAPIリファレンス抜粋+正しい使用例」をアップロードする設計(Q4の推奨)が、pywinauto/pyautoguiのようなニッチライブラリ対策としても優先度が高い。

### Gaps
- pywinauto、pyautoguiそのものを対象にしたLLMのAPI幻覚率やRAG適用効果に関する実証研究・ベンチマークは見つからなかった。これは本調査の重要なギャップであり、該当ライブラリに特化した評価(例: 自作の小規模ベンチマークでAPI呼び出し正答率を手動検証する)が必要と考えられる。
- 「function calling(ツール呼び出し)によってpywinauto/pyautoguiの正しいAPI情報を参照させる」設計の具体的な実装例(例: MCPサーバーでAPIリファレンスを検索可能にする等)についても、直接の事例は確認できなかった。一般的なfunction calling×RAGのパターン(検索ツールをLLMに呼ばせてAPI文書を取得させる)からの類推に留まる。

---

## 補足: 関連する周辺知見

- **IRとしてのPython/DSL設計**: LLM生成向けに設計されたDSL(Anka)は、構文を制約することで、モデルが既に熟知している汎用言語よりも性能が良くなる場合があるという報告がある — [Anka: A DSL for Reliable LLM Code Generation (arXiv 2512.23214)](https://arxiv.org/html/2512.23214v1)。LLMLIFTはPython自体を中間表現として使い、モデルがPythonで要約を書いた後、決定的な変換で検証済みの目的DSLコードを生成する2段階構成を取る — [EECS-2024-11 (berkeley.edu)](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2024/EECS-2024-11.pdf)。
- **2段階(two-pass)パイプライン**: 2026年4月のInfoWorld記事は、LLMがまず簡潔で言語非依存の中間表現を生成し、その後決定的なステップがそのIRからフレームワーク固有コード(Angular/React)を生成する「2パスコンパイラ」的パイプラインを紹介している。これはPAD IR→Python変換の設計方針（IR生成はLLMまたは決定的抽出、コード生成は別フェーズ）と直接的に類似する発想である — [The Two-Pass Compiler Is Back (pulse.bot)](https://www.pulse.bot/ai/news/the-two-pass-compiler-is-back-this-time-its-fixing-ai-code-generation-7f130ff2-9c7b-4de9-8809-65513930c26c/)。
- **RPA→Python変換の実例**: BotCity "Gemini Phoenix"は、UiPathの`project.json`/`Main.xaml`を読み込み、各アクティビティ(Click/TypeIntoなど)をPython(Selenium/BotCity SDK)の等価物にマッピングし、元の実行順序を保持したモジュール式Pythonプロジェクトを生成するカスタムGemini系エージェントとして実装されている。これはPAD→Python変換という本プロジェクトの目的に最も近い実例である — [Gemini BotCity Phoenix (documentation.botcity.dev)](https://documentation.botcity.dev/how-to/gemini-botcity-phoenix/)。Robocorp/Sema4のチームは、古いRPAツールからPythonへの変換ツールを構築した経験から、「移行されたボットはしばしば質が低いままになる」ため機械的変換よりプロセスの再構築を推奨している — [From RPA to Python Automation (sema4.ai)](https://sema4.ai/docs/automation/faq/to-python-automation)。
- **Power Automate(PAD)特有の変換事例**: 本調査では見つからなかった(Gap)。

## 総括(本調査担当分の結論)

1. IR→コードのfew-shot例は少数(2〜5個程度)かつ対象アクション種別に関連性の高いものを選ぶことが望ましい。
2. チャット型LLM運用では、エージェント型ツール(Claude Code/Codex)が持つ「決定的ハーネス」をチャット外のユーザー側パイプライン(IR正規化・バリデーション・出力の構文/スキーマ検証・API呼び出し名の照合)として用意し、LLMには曖昧な解釈・コード本文生成のみを委ねる設計が理論的にも実例的にも支持される。
3. 大きなIRを一括投入するとコンテキスト劣化("lost in the middle"、長文での性能低下)のリスクが高まるため、サブフロー単位の分割生成+各チャンクへのスキーマ検証+テスト駆動の反復修正を組み合わせる方が信頼性が高いと考えられる。
4. ライブラリをコンテキストとして渡す際は、ソース全体よりも厳選したAPIリファレンス+使用例スニペットの方が、Anthropicの「コンテキストは有限リソース」原則やDAG研究の知見と整合する。
5. pywinauto/pyautoguiのようなニッチライブラリに特化した実証は見つからなかったが、低頻度APIに対するDAG(文書による生成補強)の効果(Q4)やSelenium領域でのRAGグラウンディング実証(30%→90%)から、同様の効果が期待できると推測される。これは本調査の最大のエビデンスギャップであり、実運用前に自前の小規模検証(手動でAPI呼び出し正答率を測る)を行うことを推奨する。
