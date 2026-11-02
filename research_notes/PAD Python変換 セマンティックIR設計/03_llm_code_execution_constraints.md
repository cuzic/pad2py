# LLMチャットサービスのコード実行環境(ChatGPT/Gemini/M365 Copilot)の実務上の制約

## ChatGPT Code Interpreter / Advanced Data Analysis のサンドボックス制約(容量・実行時間・永続性)

### Takeaway
ChatGPT のUI(Advanced Data Analysis、現在は単に「ChatGPT」内のコード実行機能として統合)はファイル保持期間など一部の数値が公式ヘルプでも曖昧にしか記載されていない。一方、開発者向けAPI(Responses API の Code Interpreter tool)は公式ドキュメントでコンテナのアイドルタイムアウト(20分)・メモリ階層・レート制限(100RPM/組織)が明記されており、こちらが最も信頼できる一次情報源。いずれも「コンテナが失効すると中の状態・ファイルは完全に失われ、復元不可」という点は共通。

### Cited Findings
- OpenAI の File Uploads FAQ(help.openai.com)は、ChatGPTにアップロードしたファイルのサイズ上限を512MBと案内している(ファイル形式によっては別の上限がある可能性)。Plusユーザーは3時間あたり最大80ファイルまでアップロード可能、無料ユーザーは1日3ファイルまでという制限が記載されている — [OpenAI File Uploads FAQ](https://help.openai.com/en/articles/8555545-uploading-files-in-chatgpt)(直接のWebFetchは403で失敗したため、WebSearchのスニペット経由での確認。原文の直接確認はできていない)
- OpenAI公式の開発者向けドキュメント(developers.openai.com、Code Interpreter tool のガイド)によれば、Responses API の Code Interpreter は「コンテナ」という隔離VM単位で動作し、`type: auto` で自動作成されるか `/v1/containers` エンドポイントで明示的に作成できる。メモリ階層は 1g(デフォルト)/4g/16g/64g から選択可能で、その上限はコンテナのライフタイム全体に適用される — [OpenAI Developers: Code Interpreter tool guide](https://developers.openai.com/api/docs/guides/tools-code-interpreter)
- 同ガイドは「コンテナは20分間使用されないと失効する(expires if it is not used for 20 minutes)」と明記。失効したコンテナへのリクエストは失敗し、データは復元不可能。新しいコンテナを作成しファイルを再アップロードする必要がある。ファイルやPythonオブジェクトなどのメモリ内状態は、同一コンテナが再利用されているターンの間だけ永続化される — [OpenAI Developers: Code Interpreter tool guide](https://developers.openai.com/api/docs/guides/tools-code-interpreter)
- 同ガイドには Code Interpreter tool のレート制限として「100 RPM(organization単位)」が記載されている — [OpenAI Developers: Code Interpreter tool guide](https://developers.openai.com/api/docs/guides/tools-code-interpreter)
- 同ガイドはサポートするファイル形式としてCSV、PDF、DOCX、XLSX、PNG、JPEG、ZIPなど多数のコード/テキスト系形式を列挙しているが、個別の「アップロードサイズ上限」はこのページには記載がない — [OpenAI Developers: Code Interpreter tool guide](https://developers.openai.com/api/docs/guides/tools-code-interpreter)
- OpenAI Community フォーラムの投稿では「ドキュメントによればコンテナは20分未使用で失効する」との言及があり、一部開発者は「頻繁にアクセスしていても24時間程度で失効するように見える」と報告している(これはコミュニティの非公式な観測であり未確認) — [OpenAI Community: best practice for keeping containers alive](https://community.openai.com/t/what-is-the-best-practice-for-keeping-containers-alive/1321557)
- ChatGPT UI側(ヘルプセンター経由、WebSearch要約)では「Advanced Data Analysisにアップロードしたファイルは、プランに応じて異なる期間で削除される」「ファイルは会話(チャット)の保持期間に応じて保持される」とのみ記載され、具体的な時間数は確認できなかった。サードパーティのブログ(未検証)はセッション寿命を「10〜60分の無操作後」または「数時間」と推測しているが、出典が示されておらず信頼性は低い — [third-party summary citing help.openai.com](https://help.openai.com/en/articles/8555545-file-uploads-faq)(一次ソースの直接確認は不可、403エラー)

### Inferences
- UI版(ChatGPT本体)とAPI版(Responses API Code Interpreter)は別の制約体系を持つ。PAD→Python変換パイプラインの構築用途では、挙動が明文化されているAPI版のコンテナモデル(20分アイドルタイムアウト、メモリ階層選択可)を基準に設計すべきで、UI版の非公式な挙動に依存するのは避けるべき。
- 20分のアイドルタイムアウトは、長時間かかるバッチ変換(大量のPADフローをまとめて変換するような処理)には短すぎる可能性がある。定期的なダミー操作でタイマーをリセットする実装上の工夫が必要になりうる。

### Gaps
- ChatGPT UI(消費者向け)でのファイル保持・セッション失効の正確な時間(分/時間単位の数値)は、公式ヘルプページへの直接アクセスが403で拒否されたため確認できなかった。
- 複数ターンにわたる「永続化」の正確な境界(同一チャット内で何時間/何メッセージまで状態が保持されるか)についての公式な数値情報は見つからなかった。

## 独自Pythonパッケージ(.whl/zip)のアップロードとpip install、ネットワークアクセス、事前インストール済みパッケージ

### Takeaway
公式ドキュメントはChatGPT/Responses APIのCode Interpreterにおけるpipインストールやネットワークアクセスの可否を明示的に記載していない。コミュニティの非公式な調査(リバースエンジニアリング的な報告)では、内部的なPyPIミラー経由でのpip/npmインストールが可能だが、一般の外部インターネットへの直接アクセスは遮断されているとする報告が複数あり、これは公式ドキュメントでは確認が取れていない未確認情報である。

### Cited Findings
- OpenAI Developers の Code Interpreter tool ガイドには、事前インストール済みパッケージの一覧、pip installの許可/禁止、ネットワークアクセスの有無についての記載がない(ページ内に言及なし) — [OpenAI Developers: Code Interpreter tool guide](https://developers.openai.com/api/docs/guides/tools-code-interpreter)
- コミュニティのサンドボックス調査ブログ記事では「サンドボックスはgVisorでサンドボックス化されたLinuxコンテナ+Jupyterカーネルであり、pipは内部PyPIミラー経由で動作するが、aptは遮断されている」と報告されている。著者はOpenAIサポートに問い合わせ、「観測した挙動は設計仕様の範囲内」との回答を得たとしている — [Poking Around ChatGPT's Sandbox](https://hn.jakechampion.name/reader/https://mkarots.github.io/blog/chatgpt-sandbox-exploration)(未公式・コミュニティ報告)
- 別のコミュニティ要約(2026年1月の報告の要約)では、Bash・Node.js・約10言語のランタイム、`container.download`ツール、内部プロキシ経由でのpip/npmパッケージインストールが可能だが、外部ネットワークへの直接アクセスは遮断されていると説明されている。この要約自体も「公式文書による裏付けはない」と明記している — [Reddit snapshot summary via WebSearch](https://reddit.sentinel-team.org/posts/1s3pynh/snapshots/2026-03-27T16%3A20%3A19.954082Z)(未公式・未検証)
- OpenAI Community の別スレッド(Hosted Shell機能に関する要望)では、「Code Interpreterには多数の一般的なPythonパッケージが事前インストールされているのに対し、Hosted Shellはデフォルトでより最小限のPython環境しか持たない。Hosted Shellでは追加パッケージをpipでインストールでき、同一コンテナを再利用する場合はパッケージが永続化されうる」との投稿がある — [OpenAI Community: Feature Request - Hosted Shell + Code Interpreter](https://community.openai.com/t/feature-request-allow-hosted-shell-code-interpreter-together-or-provide-python-environment-parity/1410851)(ユーザー投稿、未検証)
- 2023年時点の日本語開発者ブログ(やや古い情報の可能性)では「実行環境はインターネットに接続できず、事前インストールされていないライブラリはpipインストールできない」と報告されている — [developers.gmo.jp](https://developers.gmo.jp/author/jiken)(執筆時期が古く、現在の仕様と異なる可能性がある)

### Inferences
- 「Code Interpreter(ChatGPT本体に統合された機能)」と「Hosted Shell(開発者向けの別ツール)」という2つの異なる実行環境がOpenAI側に存在する可能性が示唆されており、pipインストールの可否はどちらを使うかに依存する可能性がある。PAD→Python変換のライブラリをアップロードして使う運用を検討する場合、どの実行環境(ChatGPT本体のCode Interpreter vs 開発者API経由のHosted Shell/Code Interpreter tool)を指すかによって現実性が大きく変わるため、この区別を明確にした上で再調査する必要がある。
- 外部ネットワークアクセスが遮断されているという報告が複数の非公式ソースで一致していることから、「自社のPyPIリポジトリやプライベートレジストリから直接pip installする」という運用は現実的でない可能性が高い。.whl/zipファイルを直接アップロードし、`sys.path.append()`や`pip install <ローカルファイル>`でインストールする方式であれば、ネットワーク遮断の影響を受けずに実現できる可能性がある(ただしこれも公式文書での確認はできていない)。

### Gaps
- 事前インストール済みPythonパッケージの正式な一覧(公式ドキュメントのURL)は見つからなかった。
- ユーザーがアップロードした`.whl`ファイルをサンドボックス内で`pip install <アップロードしたファイル>`のようにローカルインストールできるかどうかを明示的に確認した公式文書・検証記事は見つからなかった(ネットワーク遮断下でのローカルwheelインストールの可否は未確認)。
- ChatGPT本体のCode InterpreterとOpenAIの開発者向けAPIの"Code Interpreter tool"が内部的に同一のサンドボックス実装を共有しているか、別物かについての公式な明言は見つからなかった。

## Google Gemini の Code Execution 機能(API/App)の現在の仕様

### Takeaway
Gemini API の Code Execution tool は公式ドキュメント(ai.google.dev、リダイレクト先 aistudio.google.com/docs/code-execution)で仕様が比較的明確に記載されている: 利用可能ライブラリは固定リストに限定され、ユーザー独自のライブラリインストールは明示的に禁止(「You can't install your own libraries」)。最大実行時間30秒、エラー時は最大5回まで再生成して再試行、グラフ描画はmatplotlibのみサポート。消費者向けGemini Appについては、API版と同一の仕様が適用されるのか、独自の仕様があるのかを示す公式ドキュメントは見つからなかった。

### Cited Findings
- Google公式ドキュメント(aistudio.google.com/docs/code-execution)は、Code Execution tool が利用できるライブラリとして attrs, chess, contourpy, fpdf, geopandas, imageio, jinja2, joblib, jsonschema, jsonschema-specifications, lxml, matplotlib, mpmath, numpy, opencv-python, openpyxl, packaging, pandas, pillow, protobuf, pylatex, pyparsing, PyPDF2, python-dateutil, python-docx, python-pptx, reportlab, scikit-learn, scipy, seaborn, six, striprtf, sympy, tabulate, tensorflow, toolz, xlrd を列挙している — [Google AI: Code execution](https://aistudio.google.com/docs/code-execution)(ai.google.dev/gemini-api/docs/code-execution から301リダイレクト)
- 同ページは「ユーザーは自分自身のライブラリをインストールできない(You can't install your own libraries)」と明記している — [Google AI: Code execution](https://aistudio.google.com/docs/code-execution)
- 同ページによれば、コード実行環境の最大実行時間は30秒。コードがエラーになった場合、モデルは最大5回までコードを再生成して再実行を試みる — [Google AI: Code execution](https://aistudio.google.com/docs/code-execution)
- 入力ファイルサイズの上限はモデルのトークンウィンドウに依存し、コンテキストウィンドウを超えるアップロードはエラーになる。入力はインラインデータまたはFiles API経由のアップロードに対応するが、環境が最も得意とするのはテキストとCSVファイル。出力ファイルは常にインラインデータとして返される — [Google AI: Code execution](https://aistudio.google.com/docs/code-execution)
- 実行可能な言語はPythonのみ。グラフ描画としてサポートされるのはmatplotlibのみで、モデルはこれら以外のメディアファイルのようなアーティファクトを返せない — [Google AI: Code execution](https://aistudio.google.com/docs/code-execution)
- コード実行を有効化すると、創作的な文章生成など他の出力領域で性能が低下(regressions)することがあるとの注記がある。コード実行を使いこなすモデルの能力にはばらつきがある — [Google AI: Code execution](https://aistudio.google.com/docs/code-execution)
- 課金について、Code Execution tool自体の有効化に追加料金はなく、標準の入出力トークン料率が適用される。プロンプト・生成されたコード・実行結果は中間入力トークンとして、最終的な要約と出力は出力トークンとして課金される — [Google AI: Code execution](https://aistudio.google.com/docs/code-execution)
- Code ExecutionはGoogle検索によるグラウンディングと併用可能。Gemini 3/4モデルではカスタムのfunction callingとも併用できる — [Google AI: Code execution](https://aistudio.google.com/docs/code-execution)
- Gemini Files API全般(Code Execution専用ではなく汎用アップロード)については、サードパーティ情報源(fast.io)が「1ファイルあたり最大2GB、48時間でファイルが失効する」としているが、これは公式ドキュメントでの直接確認ができていない — [fast.io: Gemini Max File Size](https://fast.io/resources/gemini-max-file-size.md)(未検証の二次情報)

### Inferences
- Gemini API の Code Execution は「固定ライブラリ・ライブラリインストール不可・30秒実行上限」という明確な制約により、独自のDSLパーサーやPAD→Python変換のIR処理ロジック(ユーザー独自のPythonパッケージ)をそのままアップロードして動作させることは、現状の仕様では不可能と判断できる。これは3プラットフォームの中で最も明確に「不可」と文書化されているケース。
- 30秒という実行時間上限は、PADフロー全体を一括変換するような長時間処理には全く対応できない。IRの断片ごとに30秒以内で完結する小さな処理に分割する必要がある。

### Gaps
- 消費者向け「Gemini App」(chat.google.com的なコンシューマー向けUI)固有のコード実行機能の仕様(ファイルアップロード制限、ライブラリリスト、実行時間)について、API版とは別の公式ドキュメントは見つからなかった。Gemini AppがAPIと同一のサンドボックス実装を使っているのか独自実装かは未確認。
- Gemini API Code Execution専用の入力ファイルサイズの具体的な数値上限(「トークンウィンドウに依存する」以外の明確なMB数)は公式ドキュメントに記載がなかった。

## Microsoft 365 Copilot の汎用Pythonコード実行環境(Python in Excel以外)

### Takeaway
2026年11月時点で、Microsoft 365 CopilotにはExcel内のPython数式機能(Python in Excel)に加えて、Microsoft Copilot Studio上の「Code Interpreter(プレビュー)」という汎用的なPythonコード生成・実行機能が存在する。ただしこの機能はCopilot Studioのエージェント向け機能であり、2026年8月時点の公式ドキュメントでも「prerelease documentation / preview」と明記されており、本番運用を想定した機能ではない。ファイルサイズは16MB/ファイル、最大10ファイルという制約がある。独自Pythonパッケージのアップロード機能についての記載はない。

### Cited Findings
- Microsoft Learn公式ドキュメント(2026年8月4日更新)は、Copilot Studioの「Code interpreter」機能について「このページはプレリリース文書であり変更される可能性がある(This article is prerelease documentation and is subject to change)」「プレビュー機能は本番運用を意図しておらず、機能が制限される場合がある」と明記している — [Microsoft Learn: Use code interpreter to analyze structured data (preview)](https://learn.microsoft.com/en-us/microsoft-copilot-studio/knowledge-code-interpreter-structured-data)
- 同機能は、エージェントがユーザーの質問に応答するためにPythonコードを生成・実行できるようにするもので、統計分析・テーブル結合・予測・グラフ生成などCSV/Excelの構造化データ分析タスクをサポートする — [Microsoft Learn: Use code interpreter to analyze structured data (preview)](https://learn.microsoft.com/en-us/microsoft-copilot-studio/knowledge-code-interpreter-structured-data)
- ファイルサイズの制約として「Code interpreterが解析できる各ファイルのサイズ上限は、ファイル形式を問わず16MB」「アップロード可能なファイルは最大10個まで」と明記されている — [Microsoft Learn: Use code interpreter to analyze structured data (preview)](https://learn.microsoft.com/en-us/microsoft-copilot-studio/knowledge-code-interpreter-structured-data)
- ライセンス面では「コード生成・実行は『text and generative AI tools (premium)』機能として扱われる」「主権クラウド(Sovereign clouds)では現在サポートされていない」と記載されている — [Microsoft Learn: Use code interpreter to analyze structured data (preview)](https://learn.microsoft.com/en-us/microsoft-copilot-studio/knowledge-code-interpreter-structured-data)
- 構造化データファイルは、(1)エンドユーザーがチャット中にアップロードする方法、(2)作成者がSharePointの「Documents」ライブラリをナレッジソースとして追加する方法、の2通りでエージェントに提供できる — [Microsoft Learn: Use code interpreter to analyze structured data (preview)](https://learn.microsoft.com/en-us/microsoft-copilot-studio/knowledge-code-interpreter-structured-data)
- WebSearchで要約された別のMicrosoft公式リリースノート情報として、「Copilot Studioのこのcode interpreter機能のGeneral Availability(GA)日は2026年5月31日」との言及があったが、これは一次ページの直接確認ではなくWebSearch要約経由の情報であり、上記で直接WebFetchしたページでは「preview」のままと明記されているため、GA化の時期・範囲について情報が矛盾している可能性がある — [WebSearch summary citing Microsoft release notes](https://learn.microsoft.com/microsoft-365-copilot/release-notes)(要検証)
- Microsoft 365 Copilotの2026年4月リリースノート(techcommunity.microsoft.com、WebSearch要約経由)では、「Edit with Copilot」がExcel内でのPython実行(Python in Excel)をサポートし、データ分析の結果がワークブックに反映される旨が記載されている。CopilotはユーザーのリクエストまたはCopilot自身の判断で自動的にPythonを呼び出せるとされる — [techcommunity.microsoft.com: What's new in Microsoft 365 Copilot – April 2026](https://techcommunity.microsoft.com/blog/microsoft365copilotblog/whats-new-in-microsoft-365-copilot--april-2026/4510935)(WebSearch要約経由、未直接確認)
- 「Copilot Notebooks」はコード実行環境ではなく、ナレッジのグラウンディング用ワークスペースであり、Word文書やPowerPointプレゼンテーションの生成に使われるものとして説明されている(コード実行機能ではない) — [WebSearch summary](https://techcommunity.microsoft.com/blog/microsoft365copilotblog/whats-new-in-microsoft-365-copilot--april-2026/4510935)

### Inferences
- Microsoft 365 Copilotエコシステムにおいて「汎用的なPythonコード実行環境」と呼べるのは実質的にCopilot Studioの"Code interpreter"機能のみであり、これは2026年8月時点でも明確に「プレビュー」段階の機能として位置づけられている。PAD→Python変換パイプラインの本番運用コンポーネントとして組み込むには時期尚早と判断すべき。
- 16MBファイルサイズ上限・最大10ファイルという制約は、他の2プラットフォーム(ChatGPT: 512MB、Gemini: Files API経由で2GBとされる)と比べて非常に小さく、大規模なPADフロー定義ファイル(XMLやJSON形式のフロー定義一式)をまとめてアップロードする運用には不向き。
- 独自Pythonライブラリのアップロード機能についての記載が全くないことから、Copilot StudioのCode Interpreterは「構造化データ分析に特化した限定用途」であり、汎用的な独自フレームワーク実行基盤としては設計されていないと考えられる。

### Gaps
- Copilot Studio Code InterpreterのGA(正式リリース)の正確な日付・現在のステータス(2026年11月時点でpreviewのままか、GA済みか)について、公式ドキュメントの直接確認では「preview」の表記のみが得られ、「2026年5月31日GA」という情報はWebSearch要約経由の未検証情報であり、矛盾を解消できなかった。
- Copilot Studio Code Interpreterにおけるコード実行時間の上限、ネットワークアクセスの有無、事前インストール済みパッケージのリストについての情報は、公式ドキュメントのページ内に記載がなく確認できなかった。
- Microsoft 365 Copilot(Word/Excel/Teams等に統合された消費者/企業向けCopilot本体)に、Copilot Studioの機能とは別に独立した汎用Python実行環境が存在するかどうかは確認できなかった(Copilot Studioはエージェントビルダーであり、M365 Copilot本体とは別のプロダクトである可能性がある)。

## DSLパーサー/IR処理ロジックをアップロードしたデータ変換パイプラインの実例・ケーススタディ

### Takeaway
3プラットフォームいずれについても、「独自DSLパーサーやIR処理ロジックをコード実行サンドボックスにアップロードし、大規模なデータ変換パイプラインの一部として使った」という直接的な実例・ケーススタディ・ブログ記事は見つからなかった。関連する近傍の事例(LLMにDSL文法を生成させる取り組みなど)はあるが、いずれも「コード実行サンドボックスへの独自ライブラリアップロード」という運用そのものを扱っていない。

### Cited Findings
- 検索で見つかった関連事例はいずれも本質的に異なるアプローチだった: Microsoft の `dsl-copilot`(GitHub)は文法ファイル・サンプル・検証プラグイン(独自パーサーを実行してエラーを検出)を用いるパイプラインだが、これはLLMにDSL文法を学習させる取り組みであり、ChatGPT/Gemini/Copilotのコード実行サンドボックスへのパッケージアップロードではない。同リポジトリは「文法ファイルを与えてもLLMは言語構造について誤った仮定に基づいてハルシネーションを起こした」と報告している — [Microsoft dsl-copilot (GitHub, via ecosyste.ms listing)](https://awesome.ecosyste.ms/projects/github.com%2Fmicrosoft%2Fdsl-copilot)
- `engineered.at`の記事は、ChatGPTに非形式的な文法をPestの形式文法に変換させようとしたが、構文のドリフトと非生産的な反復が発生し、最終的に手動修正に切り替えたと報告している。これはコード実行サンドボックスの利用ではなく、通常のチャット対話によるコード生成の事例 — [Writing Hurl's grammar twice](https://engineered.at/articles/writing-hurl-s-grammar-twice)
- `codesherpa`(GitHub、OpenAIのfunction callingを使ってChatGPT Code Interpreter的な体験を再現するオープンソースプロジェクト)はファイル永続化を実装しているが、著者自身が「まだ非常にバギーで動作が不安定」と述べており、ChatGPT公式のCode Interpreter内で動いているものではない — [codesherpa (via awesome.ecosyste.ms)](https://awesome.ecosyste.ms/projects/github.com%2Fiamgreggarcia%2Fcodesherpa)

### Inferences
- 「ユーザー独自のPythonライブラリ/フレームワークをLLMチャットのコード実行サンドボックスにアップロードして、大規模な変換パイプラインの一部として運用する」という構想そのものが、現時点(2026年11月)では業界的にまだ実践例が公開されていないニッチな運用パターンであると考えられる。これは本調査で見つかった制約(ネットワークアクセス制限、ライブラリインストール不可、コンテナ/セッションの短い有効期限、ファイルサイズ制限)を踏まえると、技術的な障壁が大きいために実例が少ない可能性がある。

### Gaps
- 3プラットフォームいずれについても、独自DSLパーサー/IR処理ロジックのアップロードをコード実行サンドボックス内で行った直接的な事例は見つからなかった。これは「情報が存在しない」ことの確認であり、調査不足によるものではないと考えられる(複数の検索クエリで類似事例を探索したが該当なし)。

## 既知の制約・失敗パターン

### Takeaway
3プラットフォーム共通で確認できた/報告されている失敗パターンとして、(1) コンテナ/セッションの短い有効期限によるアップロードファイル・状態の消失、(2) 外部ネットワークアクセスの制限(完全遮断、または内部プロキシ経由に限定)、(3) 実行時間の短さ(Geminiは30秒固定)、(4) ファイルサイズ・ファイル数の上限、(5) 独自ライブラリインストールの禁止(Geminiは公式に明記、他は非公式報告)、がある。これらは公式文書で確認できた事実とコミュニティ報告が混在しているため、以下で明確に区別する。

### Cited Findings
**公式文書で確認できた制約:**
- OpenAI Code Interpreter tool(Responses API): コンテナは20分間未使用で失効し、データは復元不可能。新規コンテナ作成とファイル再アップロードが必要 — [OpenAI Developers: Code Interpreter tool guide](https://developers.openai.com/api/docs/guides/tools-code-interpreter)
- OpenAI Code Interpreter tool: レート制限100RPM/組織 — [OpenAI Developers: Code Interpreter tool guide](https://developers.openai.com/api/docs/guides/tools-code-interpreter)
- Gemini API Code Execution: 最大実行時間30秒固定。ユーザーは自分のライブラリをインストールできない。入力ファイルサイズはモデルのトークンウィンドウに制限される。実行可能言語はPythonのみ、描画はmatplotlibのみ — [Google AI: Code execution](https://aistudio.google.com/docs/code-execution)
- Gemini API Code Execution: 有効化すると創作的な文章生成など他の出力領域で性能低下(regressions)が起きる場合がある — [Google AI: Code execution](https://aistudio.google.com/docs/code-execution)
- Microsoft Copilot Studio Code Interpreter(preview): ファイルサイズ上限16MB、最大10ファイル。主権クラウド非対応。プレビュー機能であり本番運用を意図していない — [Microsoft Learn: Use code interpreter to analyze structured data (preview)](https://learn.microsoft.com/en-us/microsoft-copilot-studio/knowledge-code-interpreter-structured-data)

**コミュニティ報告(未確認・非公式)による制約・失敗パターン:**
- ChatGPTのサンドボックスは外部インターネットへの直接アクセスができず、pipは内部PyPIミラー経由に限定されるという報告 — [Poking Around ChatGPT's Sandbox](https://hn.jakechampion.name/reader/https://mkarots.github.io/blog/chatgpt-sandbox-exploration)(非公式、未検証)
- ChatGPTの会話内でコードインタープリタのセッションが切れると、アップロードしたファイルや実行状態は失われるが、チャット履歴のテキスト自体は保持されるという報告。ユーザーは生成物を都度ダウンロードし、長い分析は小さく分割し、再実行用にコードを保持しておくことが推奨されている — [third-party guide, via WebSearch summary](https://www.zo.computer/tutorials/code-interpreter-session-expired-fix-it-or-get-a-better-alternative)(非公式、未検証)
- ChatGPTのCode Interpreterサンドボックスのメモリは512MB〜1GB程度とされ、アップロード自体が成功してもサンドボックス内のメモリ不足で大規模データセットの処理がクラッシュする可能性があるという報告 — [fast.io: ChatGPT Code Interpreter file size limit](https://fast.io/resources/chatgpt-code-interpreter-file-size-limit/)(非公式、未検証)

### Inferences
- 3プラットフォーム全てにおいて「コンテナ/セッションは一定時間で失効し、その際にアップロードしたファイル・インストールしたパッケージ・実行中の状態は完全に失われる」という挙動は、程度の差はあれ共通している。これはPAD→Python変換パイプラインをこれらのサンドボックス上で「長期運用するステートフルな処理基盤」として使うことの根本的な障害になる。
- 独自ライブラリ/DSLパーサーのアップロードによる恒久的な実行環境構築は、Geminiでは公式に不可能と明記されており、OpenAI/Microsoftでも公式な「可能」の明言がない。これらを踏まえると、「ユーザーが独自のPythonライブラリ/フレームワークをアップロードして実行する」という運用構想は、少なくとも3者のうちいずれにおいても、本番運用に足る保証された機能としては現時点(2026年11月)で確立されていないと判断するのが妥当。
- 唯一現実的に近いのはOpenAIのResponses API経由のCode Interpreter toolで、ファイルアップロード・同一コンテナの再利用によるある程度の状態保持(20分以内)が可能という点で、他の2者より柔軟性がある。しかし20分のアイドルタイムアウト、pipインストール/ネットワークアクセスの可否が非公式情報しかない点を踏まえると、これを本番のデータ変換パイプラインの不可欠な一部として組み込むにはリスクが高い。

### Gaps
- 「コンテキストウィンドウの制限により一度に処理できるIR/コード量に上限がある」という点について、Gemini以外(ChatGPT/Copilot)の具体的なトークン数上限や、それがコード実行サンドボックスの入力とどう関係するかの公式な記載は見つからなかった。Geminiについては「入力ファイルサイズはモデルのトークンウィンドウに制限される」という記載のみで、具体的なトークン数(例: Gemini 2.0 Flashで何トークンか)は確認できなかった。
- OpenAI Code Interpreter toolにおけるネットワークアクセスの有無、pip installの可否についての公式な明言は最終的に見つからなかった(非公式情報のみ)。この点は今後OpenAIの公式ドキュメント更新や問い合わせでの再確認が必要。
