# 既存のRPAフロー変換・移行ツールに関する先行研究・OSS調査

## GitHub上にPower Automate Desktop (PAD) のフローをPythonや他形式に変換するOSSプロジェクトは存在するか?

### Takeaway
調査した結果、PADフローをPython(または他のプログラミング言語)に直接変換する専用のOSSプロジェクトは見つからなかった。見つかったのは「PythonからPADの制御/生成を行う」「PADからPythonスクリプトを呼び出す」という逆方向・補助的な連携ツールのみであり、PADのフローファイル形式自体が非公開であることがその一因と考えられる。

### Cited Findings
- `PyPowerAutomate`(PyPI)はPower Automateの**クラウドフロー**をPythonコードでプログラム的に構築・レガシーパッケージとしてエクスポートするためのパッケージであり、既存のデスクトップフローを読み込んで変換するものではない — [PyPowerAutomate on PyPI](https://pypi.org/project/pypowerautomate/)
- Microsoft公式リリースプランによれば、PAD(デスクトップフロー)は従来IronPythonベースのエンジンでPythonスクリプトを実行していたが、2026年リリース予定でローカルにインストールした任意のPythonバージョンを実行できる機能(パブリックプレビュー予定日2026年6月30日)が追加される。これは「PADからPythonを呼び出す」実行機能であり、フロー自体をPythonへ変換するものではない — [Use Python v3 in Power Automate for desktop (Microsoft Learn)](https://learn.microsoft.com/power-platform/release-plan/2024wave1/power-automate/use-python-v3-power-automate-desktop); [Run Python scripts using current Python versions in desktop flows (2026 Wave 1 release plan)](https://learn.microsoft.com/en-us/power-platform/release-plan/2026wave1/power-automate/run-python-scripts-using-current-python-versions-desktop-flows); [MC1391903 Message Center notice](https://mc.merill.net/message/MC1391903)
- PADの `.flow` ファイル形式は公式に文書化されておらず、Microsoft Power Platform community フォーラムの投稿では、ソリューションをエクスポートするとデスクトップフローごとにJSONファイルが生成されるが、新しいスキーマではパッケージ記述がエンコードされたバイナリになっており、パーサーを自作するのが難しいと報告されている — [Power Automate Desktop community forum thread](https://powerusers.microsoft.com/t5/Power-Automate-Desktop/Governance-Monitoring-Power-Automate-Desktop-Flows/m-p/2656902)
- ある開発者コミュニティの回答では、PADのインストールディレクトリ内のDLLをリバースエンジニアリングしてアクションの実装を調べる方法が提案されているが、回答者自身がこれは明らかにPower Automateの利用規約に違反する可能性があると指摘している — [Power Automate community thread on recovering flows](https://forwardforever.com/recovering-an-editable-power-automate-desktop-flow-from-a managed-solution/)
- UiPath Marketplace上の `Export Power Automate Desktop (PAD) Flows` は、PAD Designer UI経由でフローの引数・サブフロー情報を `.arg`/`.subflow` というプレーンテキストファイルにエクスポートする自動化であり、フローファイルを直接パースするものではない(PAD自体にはフローのバックアップ/エクスポート機能がないと明記されている) — [UiPath Marketplace: Export PAD Flows](https://marketplace.uipath.com/listings/export-power-automate-desktop-pad-flows)
- GitHub/PyPI検索で見つかる "RPA" 関連Pythonパッケージ(`rpa`/`tebelorg/RPA-Python`、`rpa-suite` 等)は、いずれもPythonから直接Webブラウザやデスクトップアプリを操作するための**独立したRPAライブラリ**であり、PADやUiPathのフロー定義を入力として解釈・変換するものではない — [tebelorg/RPA-Python (GitHub)](https://github.com/tebelorg/RPA-Python); [RPA for Python (PyPI)](https://pypi.org/project/rpa/1.22.6/)

### Inferences
- PADフローのファイル形式(デスクトップフロー用のバイナリ/エンコードされたパッケージ記述)が非公開かつ複雑であることが、OSSとして変換ツールが育っていない構造的な要因と推測される。
- Microsoft自身が「PAD内からPythonスクリプトを呼び出す」方向の統合を強化している(2024年からのPython v3対応、2026年の任意バージョン対応)ことから、Microsoftの戦略は「PADフローをPythonに変換する」のではなく「PADフロー内でPythonを混在実行させる」方向にあると考えられる。

### Gaps
- `.flow`/ソリューションエクスポートJSONの正確なスキーマ(アクション名→パラメータのマッピング)を解析・公開した技術ブログやOSSパーサーは、今回の検索では発見できなかった。GitHub上を直接クロールするような網羅的検索(GitHub Code Search自体)は実行できておらず、ニッチな個人リポジトリが存在する可能性は否定できない。

---

## UiPath、Automation Anywhere、Blue Prism等の他のRPAツールのフローをコードに変換する同様のツール・研究はあるか?

### Takeaway
UiPathのXAMLワークフローをPythonへ変換する完全なオープンソース・トランスパイラは見つからなかったが、「移行アクセラレータ」と呼ばれる商用/ハイブリッドのツールがいくつか存在し、特に Robocorp の Converter Accelerator は UiPath/Blue Prism/Automation Anywhere のワークフローを Robot Framework(Python系OSSフレームワーク)に変換する機能を持つ。Automation Anywhere自身のコミュニティは「RPAツール間でのボットコード移行は、各製品が独自のアーキテクチャ・フレームワーク・コードバインディングを持つため実現不可能」という立場を明言している。

### Cited Findings
- **BotCity Phoenix**は、UiPathのワークフローファイル(`.xaml` + `.json`)をBotCityエコシステム向けのPython自動化コードに変換するClaude Codeスキル(移行アクセラレータ)であり、完全自動の変換ツールではなく、ライセンス等の詳細も明記されていない — [BotCity Phoenix documentation](https://documentation.botcity.dev/how-to/phoenix-botcity/)
- **GEM Phoenix**はGoogle Gemini上に構築されたエージェントで、BotCity Maestro SDK・Selenium・BeautifulSoup・pandas/openpyxlと統合したPythonコードを生成するが、ホスト型ツールであり、オープンソースではない — [GEM Phoenix documentation](https://documentation.botcity.dev/how-to/gemini-botcity-phoenix/)
- PyPI上の `uipath` パッケージはUiPathの `.xaml` ファイルをプログラム的に編集するPython APIであり、XAMLを別言語に変換するものではない(ドキュメントは「coming soon」の状態) — [uipath on PyPI](https://pypi.org/project/uipath)
- MIT ライセンスの `UiPath Workflows To Libs`(UiPath Marketplace, MCCM Innovations)は、XAMLのXML DOMを処理してワークフロー呼び出しをライブラリ呼び出しに変換するツールだが、出力はXAML内の構造変更であり、Pythonなど他言語には変換しない — [UiPath Marketplace: Workflows To Libs](https://marketplace.uipath.com/listings/mccminnovations-uipath-workflows-to-libs)
- **Robocorp Converter Accelerator**(現Sema4.ai系列)は、UiPathプロジェクト、Blue Prismのエクスポート、Automation Anywhereのプロジェクトを読み込み、Robot Framework(Pythonベースのオープンソース自動化フレームワーク)用のファイルに変換する。UiPathについてはSequenceおよびFlowchartワークフロー型のみ対応し、State Machine型は非対応と明記。ページの最終更新は2022年12月と比較的古く、現在の保守状況は不明 — [Robocorp docs: Conversion tools](https://robocorp.com/docs-robot-framework/conversion/tools)
- Automation Anywhereコミュニティフォーラムでは、同社スタッフが「異なるRPAツール間でのボットコード移行は、各製品が独自のアーキテクチャ・フレームワーク・コードバインディングを持つため実現不可能」と回答している一方、別の回答では「Blue Prismのファイルの可読性次第」という留保もつけている — [Automation Anywhere community forum](https://community.automationanywhere.com/developers-forum-36/can-i-migrate-blue-prism-or-uipath-code-to-automation-anywhere-7439)
- UiPathフォーラムの複数スレッドでは、Blue PrismやAutomation Anywhereのプロセスを「手作業で作り直す(rebuild)しかない」という実務者の体験談が繰り返し報告されている。ある回答者は「Automation AnywhereプロジェクトをUiPathへ直接移行するツールはなく、UiPathに詳しいならプロジェクトを再度ゼロから作るほうが良い」と述べている — [UiPath forum: Migrating BluePrism workflows to UiPath](https://forum.uipath.com/t/migrating-blueprism-workflows-to-uipath/554792); [UiPath forum: How to migrate BluePrism process to Uipath?](https://forum.uipath.com/t/how-to-migrate-blueprism-process-to-uipath/243043)
- 移行サービスの求人情報(Roboyoなど)では「Blue PrismオートメーションをUiPathへ変換するための移行アクセラレータ/ツールの経験」が応募条件として挙げられており、商用の非公開ツールが実務では使われている可能性を示すが、具体的な製品名は確認できなかった — [Roboyo job posting](https://job-boards.eu.greenhouse.io/roboyo/jobs/4956117101?gh_src=pzbv6x82teu)

### Inferences
- 「RPAツール間のフロー→コード変換」は技術的には可能(XAMLやプロジェクトファイルの構文解析自体は難しくない)だが、各ベンダーが意図的にエコシステムロックインを維持しているため、公式な相互運用ツールはほとんど存在せず、商用移行コンサルティング(人手を伴うアクセラレータ)が主流になっていると考えられる。
- Robot Frameworkという既存のOSS自動化フレームワークが「変換先」として選ばれる傾向がある(BotCity、Robocorpの例)。これはPythonエコシステムの中でRPA的なキーワード駆動構文を持つOSSが既に存在するためと考えられる。

### Gaps
- Blue Prismのプロセス定義(.bprelease、XML形式)を直接解析する専用OSSツールは発見できなかった。
- Robocorp Converter Acceleratorの現在(2026年時点)の保守状況・GitHubリポジトリの有無・スター数は確認できなかった(ドキュメントページ自体がHTTP 530エラーで再取得できず、2022年12月更新という情報のみ)。

---

## RPAベンダー間のフロー移行ツール(例: UiPathからPower Automateへの移行支援ツール、またその逆)は存在するか? Microsoft や UiPath が公式に提供する移行支援機能はあるか?

### Takeaway
UiPathからPower Automateへの移行は複数のサードパーティ製アクセラレータ(Blueprint Migrate、Kanerika FLIP等)によって商用サービスとして提供されているが、Microsoft自身が無償・公式に提供する「自動変換ツール」としての決定的な証拠は見つからなかった。むしろMicrosoftの最新の戦略は、UiPathボットをそのまま呼び出す統合(Copilot Studioのコンピュータ操作エージェント経由)に向かっているとみられる。

### Cited Findings
- **Blueprint Software Systems の "Migrate"** は、Automation Anywhere・Blue Prism・UiPathの3つのレガシーRPAツールからのインポートをサポートし、Power Automateなど新しい環境への移行を支援する商用プラットフォームである。同社は手作業移行に比べ60〜75%の時間・コスト削減を主張しているが、これはベンダー自身の主張であり第三者検証はない — [Blueprint Migrate Import/Export docs](https://blueprint.helpdocs.io/l/en/article/ajmht7bg69-migrate-import-export); [Blueprint blog: beginners guide RPA platform migration](https://www.blueprintsys.com/blog/rpa/a-beginners-guide-rpa-platform-migration)
- **Kanerika FLIP**はAzure Marketplaceで提供される商用アクセラレータで、UiPathからPower Automateへの変換を「エンドツーエンド」で行うとするが、同社自身のページで「複雑なカスタムアクティビティは再構築が必要になる場合がある」と限界を認めている — [Kanerika: UiPath to Power Automate Migration](https://kanerika.com/services/migration/uipath-to-power-automate)
- **Alithya のRapidAMT**は、ウェビナー資料において「MicrosoftとAlithyaが共同開発した無償ツール」と説明されており、調査した中で最もMicrosoftとの直接的な関係が明記されたツールだが、Microsoft公式ドキュメント上での言及は確認できなかった — [Alithya RPA series webinar page](https://pages.alithya.com/rpa-series)
- Akkodis、Avanadeなど複数のSIerがMicrosoft Marketplace上で有償のRPA移行サービス(PoCやアセスメントベースの移行ファクトリー)を提供しているが、いずれもコンサルティングサービスであり自動変換ツールではない — [Akkodis RPA Migration PoC (Microsoft Marketplace)](https://marketplace.microsoft.com/it-it/product/akkodis-jp.rpa_migration_poc?country=JP); [Avanade Intelligent Automation Migration Factory](https://marketplace.microsoft.com/nb-no/product/avanadeinc.avanade_intelligent_automation_migation_factory?country=BE)
- UiPath・Automation Anywhereの公式フォーラムでは、UiPathからAutomation Anywhereへ(あるいは逆方向へ)の自動移行ツールが存在しないことが繰り返し確認されており、ユーザーは手作業での再構築を推奨されている — [UiPath forum: migration tool automation anywhere to uipath](https://forum.uipath.com/t/migration-tool-automation-anywhere-to-uipath/758439)
- 2026年の記事(findskill.ai)では、Microsoft Copilot StudioのComputer-Use Agent(CUA)機能が2026年5月にGA(一般提供)となり、2025年4月に発表されたUiPathとの双方向統合を使って「UiPathボットをそのまま移行(move over)」するチュートリアルが紹介されている。ただしこれは二次情報源であり、Microsoft公式ブログでの直接確認はできていない — [findskill.ai: Copilot Studio CUA / UiPath migration tutorial](https://findskill.ai/blog/copilot-studio-computer-use-agents-uipath-migration/)

### Inferences
- Microsoftの公式な移行戦略は、「フローのコードを変換する」のではなく「Copilot Studioのエージェント型プラットフォーム上でUiPathの既存ボットを呼び出し続ける」という統合アプローチにシフトしている可能性がある。これは、構文変換よりも実行時オーケストレーションでロックインを緩和するという設計判断だと考えられる。
- 商用移行ツール市場(Blueprint、Kanerika、Laiye等)は活発だが、いずれも「完全自動変換」ではなく「アクセラレータ+人手レビュー」のモデルである。これは、RPAフロー変換が構文的には可能でも、セマンティクス(タイミング・エラーハンドリング・環境依存のセレクタ)の違いにより完全自動化が難しいことを裏付けている。

### Gaps
- Microsoft Power Automateの公式ドキュメント(learn.microsoft.com)上に「UiPathからのインポート」を直接サポートする機能があるかどうかは、今回の検索では確証を得られなかった。Microsoft公式サイトを直接クロールする追加調査が望ましい。
- Blueprint・Kanerika等の商用ツールの内部アーキテクチャ(構文解析ベースか、LLMベースか)についての技術的詳細は非公開であり確認できなかった。

---

## 学術的な研究として、RPAのプロセスマイニングやRPAスクリプトのコード変換・分析に関する論文はあるか?(IEEE, ACM, arXiv等)

### Takeaway
RPAの「プロセス選定」にプロセスマイニングを応用する学術研究は複数存在するが、「RPAスクリプト自体のコード変換・移行」を直接対象とした査読付き論文は見当たらなかった。最も関連性が高いのは2026年のarXiv論文「AutoRPA」で、LLMエージェントの操作ログからRPA関数を合成する(逆方向の)手法を提示している。

### Cited Findings
- **AutoRPA: Efficient GUI Automation through LLM-Driven Code Synthesis from Interactions**(arXiv:2605.21082、2026年5月20日投稿、ICML 2026に採択、著者 Minghao Chen, Xinyi Hu, Zhou Yu, Yufei Yin)は、ReAct型LLMエージェントの逐次推論が反復タスクで非効率である一方、従来型RPAは開発・保守に人手がかかるという問題意識から、LLMエージェントの操作軌跡を「translatorエージェント」で柔軟な手順に変換し、「builderエージェント」が複数軌跡に対する検索拡張生成(RAG)でRPA関数を合成、さらにRPA実行とReActフォールバックを組み合わせた「hybrid repair」で検証・修正するパイプラインを提案している。複数のGUI環境での実験で、最先端エージェントと同等の成功率を保ちながらトークン使用量を82〜96%削減したと報告している — [arXiv:2605.21082](https://arxiv.org/abs/2605.21082)
- ICIS 2019の論文「Process Selection in RPA Projects」は、プロセスマイニング技術に基づく自動化可能なプロセス選定手法を提案し、専門家によるバリデーションを行っている — [検索結果経由、原文未直接確認]
- El-GharibとAmyotによる系統的文献レビュー(arXiv:2204.00751)は、「プロセスマイニングがRPA導入をどのように加速・改善できるか」を問い、van der Aalstらがプロセスマイニングとロボティック・プロセス・オートメーションの関連性を最初に指摘した研究者の一人であると述べている — [arXiv:2204.00751](https://web3.arxiv.org/pdf/2204.00751)
- IIETA (Ingénierie des Systèmes d'Information, ISI vol.28 no.5) 掲載の論文は、プロセスマイニングデータを用いたRPAタスク選定フレームワークを提案し、プロセスマイニングが例外ケースを人間オペレーターへ振り分ける判断において重要な役割を果たすと論じている — [IIETA ISI journal](https://www.iieta.org/journals/isi/paper/10.18280/isi.280513)

### Inferences
- 学術コミュニティの関心は主に「どのプロセスをRPA化すべきか(process selection / process mining)」に向いており、「既存RPAフロー定義をどう別言語・別ツールに変換するか」という工学的問題(本調査の中心テーマ)はまだ十分な学術的注目を受けていないニッチ領域と考えられる。
- AutoRPAはPADやUiPathのような既存フロー定義を「入力」として変換するものではなく、LLMエージェントのトレースから新規にRPAコードを「生成」する方向の研究であり、本調査が探している「既存フローのトランスパイル」とは問題設定が異なる点に注意が必要。

### Gaps
- UI要素セレクタの脆弱性(selector brittleness/drift)を定量的に扱った査読付き学術論文は見つからなかった。見つかったのは実務者ブログ(UiPath関連、非ピアレビュー)のみ — [industrialmonitordirect.com blog on UiPath RPA fragility](https://industrialmonitordirect.com/blogs/knowledgebase/uipath-rpa-fragility-error-handling-and-drift-detection-best-practices)(これは一次学術資料ではないため参考情報扱い)。
- IEEE Xplore・ACM Digital Libraryへの直接アクセス・検索は本調査では実施できておらず(Web検索経由の間接的な結果のみ)、より専門的なデータベース検索が追加で必要。

---

## "low-code to code" や "RPA to script" という文脈での一般的なトランスパイラ事例とそこから得られる設計上の教訓は何か?

### Takeaway
Blockly(ビジュアルブロック)↔Python/MicroPython変換のような教育・ロボティクス分野の事例が最も近いアナロジーとして見つかった。主要な教訓は、(1)視覚要素のメタデータ(コメント等)をテキスト側に保持する必要性、(2)並行実行モデルの違いがテキストへの変換を不可能にする場合がある、(3)双方向同期(text↔block)はAST経由で実現されるが完全な往復変換は難しい、という3点に整理できる。

### Cited Findings
- 2025年の研究(Blockly系デュアルエディタ、ロボティクス教育向け)は、Blocklyのカスタムコードジェネレータでブロック→テキスト変換を行い、抽象構文木(AST)を用いてテキスト→ブロックの逆変換を行うリアルタイム双方向同期システムを2つのロボティクス事例で検証している — [検索結果経由の要約、原論文未直接確認]
- 米国特許US9,727,313(「Systems and methods for bi-directional visual scripting for programming languages」)は、ビジュアルプログラムをテキストに変換する際、元のビジュアル要素を識別するコメントをテキストコードに含める手法を記載している — [US9727313 patent](https://patentimages.storage.googleapis.com/10/d4/1e/81d24177193fd4/US9727313.pdf)
- 別の特許文献では、ブロックプログラムのコメントやコンポーネントがテキストに変換される際に散在してしまうと、生成されるテキストコードの可読性が低下すると指摘されている — [検索結果経由]
- 2016年のMicroPythonメーリングリストでの議論では、Blocklyが並行実行スクリプト(例: 無限ループと並行するボタン押下ハンドラ)をサポートしているか疑問視され、そのような構造はMicroPythonへの変換が不可能になり得ると指摘されている — [python.org MicroPython mailing list archive](https://www.python.org/pipermail/microbit/2016-March/000960.html)
- Booth and Stumpf (2013) の研究は、Arduino向けのビジュアル言語とテキストベース言語を、成人の初心者エンドユーザープログラマを対象に比較し、効果・ユーザー体験・学習の障壁を調査している — [検索結果経由の要約]
- トランスパイラ全般に関する2025年ACSAC発表(TeTRIS)は、トランスパイラのバグを「型・変換の誤復元」「呼び出し命令や配列サイズなど構文要素の未復元」のカテゴリに分類し、文法誘導型のミューテーションとクラッシュ/非実行可能出力/差分実行をオラクルとするテスト手法を提案している — [ACSAC 2025 slides](https://futures.cs.utah.edu/papers/25ACSAC_slides.pdf)
- 2018年の系統的レビューは、トランスパイラがこれまでマルチプラットフォームのトランザクション指向アプリケーション設計に使われてこなかった、という研究ギャップを指摘している — [検索結果経由]

### Inferences
- RPAフロー→コード変換は「ビジュアル→テキスト」変換の一種として、Blockly系の教訓(並行性モデルの不一致、メタデータ保持の必要性)がそのまま当てはまると考えられる。特にPADやUiPathの「待機(Wait)」「エラー時の処理(On Error)」「並列実行」のような構造は、Pythonのasync/await・try/exceptに1対1で対応しない場合があり、Blocklyの並行実行問題と同種の課題になりうる。
- トランスパイラの品質保証手法(TeTRIS的な、差分実行や非実行可能出力をオラクルとするテスト)は、RPA変換ツール開発においても「変換後のPythonコードが元のフローと同じ副作用を持つか」を検証する設計に応用できる可能性がある。

### Gaps
- "RPA to script" というキーワードそのものに直接合致する技術記事・論文は見つからなかった。より近い類似事例として教育用ビジュアルプログラミング(Blockly/Scratch)分野の資料を代替的に報告した。
- Power Automate / UiPath固有の構造(トリガー、コネクタ、動的選択範囲)をBlockly型モデルと比較した研究は見つかっていない。

---

## こうした変換ツールを開発する際によく挙げられる技術的な課題・失敗パターンは何か?

### Takeaway
業界側(移行コンサルティング企業)の発信からは、(1)セレクタ/要素特定方式の環境依存性、(2)待機条件・ループ・条件分岐などのロジック構造の実装差異、(3)例外処理モデルの非互換性、の3点が繰り返し課題として挙げられている。これらは査読付き学術研究というよりベンダー・実務者の経験則としての情報源が中心であることに留意が必要。

### Cited Findings
- Blueprintのブログ(RPA移行の技術的複雑さに関する記事)は、「条件分岐・ループ・待機条件のようなロジック要素は、RPAツール間で大きく構造が異なる」と述べている — [Blueprint blog: technical complexities of migrating between RPA platforms](https://www.blueprintsys.com/blog/rpa/what-are-technical-complexities-migrating-between-rpa-platforms)
- 同記事は「各RPAツールは例外処理(エラーハンドリング)へのアプローチが異なる」とも指摘している — [同上]
- 同記事は「要素識別(セレクタ)の扱い方もRPAツールごとに異なる」と指摘している — [同上]
- MuleSoft RPA Botのリリースノートには、ネットワークタイムアウトエラーが原因でRPA Managerでの実行が誤動作していたバグの修正が記録されており、タイムアウト/ネットワーク遅延に対する実装のセンシティブさを示す一例となっている — [MuleSoft RPA Bot 1.7.14 release notes](https://docs.mulesoft.com/release-notes/rpa-bot/rpa-bot-1.7.14-release-notes)
- Blueprintは「オートメーション業界には、移行は対象RPAプラットフォームでボットを一から書き直すしかない、という思い込みがあるが、それは事実ではない」とマーケティング上で主張しており、裏を返せば業界の支配的な実務慣行が「完全な書き直し」であることを示唆している — [Blueprint blog: why customers stuck on legacy version RPA tools](https://www.blueprintsys.com/blog/rpa/why-customers-stuck-legacy-version-rpa-tools)
- Automation AnywhereコミュニティとUiPathフォーラムの複数の実務者証言(前セクション参照)は、「異なるRPAツール間でのコード移行は実質的に不可能で、再実装が現実的な唯一の方法」という一致した経験を報告している — [Automation Anywhere community forum](https://community.automationanywhere.com/developers-forum-36/can-i-migrate-blue-prism-or-uipath-code-to-automation-anywhere-7439); [UiPath forum](https://forum.uipath.com/t/how-to-migrate-blueprism-process-to-uipath/243043)
- Robocorp Converter Acceleratorのドキュメントは、対応ワークフロー型に制限があることを明記しており(UiPathのState Machine型ワークフローが非対応)、これは変換ツールが全てのフロー制御構造を網羅できないという実例である — [Robocorp docs: Conversion tools](https://robocorp.com/docs-robot-framework/conversion/tools)

### Inferences
- 挙げられる失敗パターン(セレクタ、タイミング/待機、エラーハンドリング)は、いずれも「GUIベースの自動化」特有の、実行時の外部環境(対象アプリのUI状態)に依存する部分に集中している。これは、構文的なフロー→コード変換自体は比較的容易でも、実行時のロバストネス(UI要素が見つかるまでの再試行戦略、タイムアウト値のセマンティクス)を変換先言語で再現することが本質的な難所であることを示している。
- ワークフロー制御構造の非対応(State Machine型など)は、変換ツールが「よくある構造のみサポートし、複雑な構造は手作業での補完を要求する」という部分自動化戦略を取ることが実務上の標準パターンになっていることを示唆する。

### Gaps
- セレクタ環境依存性やタイミング制御の非互換性について、定量的な失敗率や具体的なバグパターンを報告した学術論文・技術白書は見つからなかった。情報源はすべてベンダーブログまたはフォーラムの実務者証言であり、エビデンスの質としては限定的である。
- Power Automate Desktop特有の「UI要素(UI Element)」仕様とUiPathの「セレクタ(Selector)」仕様を直接比較した技術文書は発見できなかった。
