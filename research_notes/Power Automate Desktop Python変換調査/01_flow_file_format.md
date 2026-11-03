# Power Automate Desktop (PAD) フローファイルの内部データ形式・取得/パース方法

## PAD のフローは .flow ファイルやパッケージとしてどう保存・エクスポートされるか?拡張子や内部構造は?

### Takeaway
PAD(クラウド接続版)のフロー定義の正本は Dataverse の `workflow` テーブル(カテゴリ値 6 = Desktop Flow)に **JSON/テキストとして** 格納されており、ローカルディスク上に単純な `.flow`/`.pad` 単体ファイルとしてエクスポートされる公式な仕組みは見当たらなかった。ローカルキャッシュはバイナリではなくフォルダ構造として存在し、クラウド同期が前提になっている。これは Power Apps の `.msapp`(ZIPアーカイブ)とは明確に異なる仕組みである。

> **【実機検証による重要な訂正・追記】** design/dsl_format_findings.md 知見43(実機検証済み)。上記のDataverse `workflow`テーブル説明は、**組織(Entra IDテナント)に紐づいたDataverse環境を持つ場合にのみ成立する**ことが実機で判明した。個人用Microsoftアカウント(MSA、例: `xxx@hotmail.com`)でPADにサインインして使っている場合、`make.powerautomate.com`等のPower Platformメーカーポータル自体が`AADSTS500200: User account is a personal Microsoft account. Personal Microsoft accounts are not supported for this application unless explicitly invited to an organization.`というエラーで拒否され、そもそもDataverse環境にアクセスできない。本ドキュメント下部で触れている「1つのフローにつきOneDrive上に2つのファイルが保存される」というコミュニティ報告の方が、個人アカウント利用時の実態に近い可能性がある——個人アカウントでのPAD利用時のフロー格納場所は、Dataverseではなく(組織向けとは別の)簡素化されたバックエンド(OneDrive等)である可能性が高く、未調査のまま残っている。

### Cited Findings
- Dataverse の `workflow` テーブルには `clientdata` という Memo 型カラムがあり、これは「流定义及其 connectionReferences 的字符串编码的 JSON」(フロー定義とその connectionReferences をエンコードした JSON 文字列)と説明されている — [Process (Workflow) table/entity reference (zh-cn)](https://learn.microsoft.com/zh-cn/power-apps/developer/data-platform/reference/entities/workflow)
- `workflow` テーブルには `desktopflowmodules` という Memo 型カラムが別途あり、「このワークフローに関連するデスクトップフローモジュール」と説明されている。この列は "Power Automate Workflow Table Extensions" という追加ソリューションによって追加されたものである — [Process (Workflow) table/entity reference](https://learn.microsoft.com/power-apps/developer/data-platform/reference/entities/workflow); [es-es 版](https://learn.microsoft.com/es-es/powerapps/developer/data-platform/reference/entities/workflow)
- `desktopflowmodule` という専用テーブル(論理名 `desktopflowmodule`, 複数形 `desktopflowmodules`)も存在するが、Microsoft Learn のリファレンスは Web API のPATCH/DELETE操作の一覧のみで、格納される内容(モジュール本体)のスキーマは記載していない — [Desktop Flow Module (desktopflowmodule) table/entity reference](https://learn.microsoft.com/en-ie/power-apps/developer/data-platform/reference/entities/desktopflowmodule)
- Microsoft Power Users コミュニティのスレッドでは、ソリューションをエクスポートすると各デスクトップフローごとに JSON ファイルが1つ生成されるが、その中身は「エンコードされたパッケージ記述(encoded package description)」になっていると報告されている。さらに「Schema V2」では、そのエンコード済みパッケージ文字列はもはや存在せず、代わりに「desktop flow binaries(デスクトップフローのバイナリ)」が含まれるようになったとされている(バージョン間でフォーマットが変化したことを示す一次証言) — [Power Users community thread](https://powerusers.microsoft.com/t5/Power-Automate-Desktop/Governance-Monitoring-Power-Automate-Desktop-Flows/m-p/2656902)(※元スレッドはリダイレクトで `community.powerplatform.com` に移動済みだが、移動先ページ自体はフォーラムのトップページで該当スレッド本文は確認できなかった。内容は検索結果のスニペット経由の確認)
- PAD コンソールのローカルキャッシュは単一ファイルではなく **フォルダ構造** として存在し、既定の場所は `C:\Users\[YourUserName]\AppData\Local\Microsoft\Power Automate Desktop\Console\Workspace` であると複数のコミュニティ投稿が報告している。フロー実行時にクラウドからこのフォルダにデータがダウンロードされてキャッシュとして使われるが、PAD はこのキャッシュから復元することはできないとも報告されている — [DEV Community: Power Automate Desktop flow local folder](https://dev.to/01kg/power-automate-desktop-flow-local-folder-2aa5); コミュニティスレッド群(Missing flows in My Flows)
- 実行ログは `Console\Scripts` 配下にフロー・実行ごとのサブフォルダとして保存されるが、フロー終了後はクリアされクラウドに送られるため、実行中にしか捕捉できないという MVP の報告がある — コミュニティフォーラム(ソース同上、ログ関連スレッド)
- あるコミュニティスレッドでは、1つのフローにつき OneDrive 上に2つのファイルが保存され、それらに不整合が起きると PAD がフローを破損扱いしてコンソールから隠してしまうという報告がある(具体的なファイル拡張子は言及されていない) — Power Users community (Missing flows in My Flows スレッド群)
- サードパーティツール(UiPath Marketplace の `PAD_ExportFlows` / `PAD_ImportFlows`)は、「PAD はフローのエクスポート/バックアップ作成を許可していない (PAD does not allow to export/create backups of flows developed in Power Automate Desktop)」と明記している。このツールはあくまで WinAutomation 由来の独自構文を使い、サブフローを `.subflow` ファイル、入出力引数を `.arg` ファイルに書き出す、**独自の**(Microsoft非公式の)シリアライズ形式である — [Export Power Automate Desktop (PAD) Flows – UiPath Marketplace](https://marketplace.uipath.com/listings/export-power-automate-desktop-pad-flows); [Import 版](https://marketplace.uipath.com/listings/import-power-automate-desktop-pad-flows)

### Inferences
- `clientdata`(クラウドフローと共通のメカニズム)と `desktopflowmodules`/`desktopflowmodule` という、クラウドフローの JSON ワークフロー定義とは別の専用カラム/テーブルが用意されていることから、デスクトップフローの「アクション本体」は `clientdata` の JSON とは別の、desktop 専用のシリアライズ領域(`desktopflowmodules`)に格納されていると考えられる。
- コミュニティ報告にある「Schema V2 で encoded package 文字列がバイナリに変わった」という証言は、Microsoft が意図的にフォーマットをブラックボックス化(圧縮/独自バイナリ化)した可能性を示唆しており、サードパーティが安定してパースできる文書化されたテキスト/XML/JSON形式が公式には存在しない、または頻繁に変わっていることを示している。
- 「PAD はフローのエクスポート/バックアップを許可しない」という第三者ツールの明言は、**単体の `.flow`/`.pad` ファイルとしてネイティブにエクスポートする公式GUI機能が(少なくとも調査時点までは)存在しないこと**を強く示唆する。Power Apps の `.msapp`(ZIPコンテナ)のような、ユーザーが直接扱える単一ファイル形式とは根本的に異なる設計である。

### Gaps
- `desktopflowmodules` カラムの中身(JSON/XML/Base64/gzip バイナリのいずれか)の具体的なスキーマは、Microsoft Learn 上に文書化されたものを発見できなかった。
- 「Schema V2 の desktop flow binaries」の正確な中身(バイナリの先頭マジックナンバーやエンコーディング)についての一次資料(Microsoft公式または詳細なリバースエンジニアリング記事)は見つからなかった。
- ローカル環境専用(非Dataverse接続、スタンドアロン版)の PAD で、フローをファイルシステム上に直接保存する際の拡張子・フォーマットについての確証は得られなかった(コミュニティはクラウド同期前提の情報のみ)。
- Power Apps の `.msapp` 形式(ZIPアーカイブで YAML/JSON を含む)との構造的な比較は、`.msapp` 側の文書は豊富だが、PAD側の対応物が不明なため直接比較はできなかった。**ただし両者は無関係な別フォーマットであることは確認できる**(`.msapp` は Canvas アプリのパッケージ形式、PAD フローは Dataverse の `workflow`/`desktopflowmodule` テーブルに保存される RPA スクリプト)。

---

## フロー定義内でアクション(マウスクリック、テキスト入力、待機、変数設定、If、繰り返し等)はどのようなスキーマで表現されているか?

### Takeaway
PAD の UI(デザイナー)内でアクションを選択してコピーすると、クリップボードに **独自のテキストベースDSL**(XML/JSONではない、行指向のスクリプト言語)が書き出されることが実例で確認できた。構文は `SET 変数名 TO 式`、`LOOP FOREACH 項目 IN コレクション` ～ `END`、`名前空間.モジュール.アクション名 パラメータ名: 値 ... 出力パラメータ=> 変数名` という形式であり、文字列リテラルは `$'''...'''` のトリプルクォートで表現される。

### Cited Findings
- GitHub リポジトリ `Hardik-S/geodata` には `geodata PAD Flow as text.txt` という、PAD からエクスポートされたフローのプレーンテキスト表現が含まれている。README はこれを「PAD を開かずに抽出ロジックを確認できるよう、プレーンテキスト形式でエクスポートした PAD フロー」と説明している — [Hardik-S/geodata](https://github.com/Hardik-S/geodata)
- そのテキストファイルの実際の構文例(WebFetch で内容確認): 変数代入は `SET RowIndex TO 1` のように `SET <name> TO <expression>` の形。ループは `LOOP FOREACH Row IN Rows` で開始し `END` で閉じ、入れ子にできる(`LOOP FOREACH Column IN Columns` が内側に存在)。アクション呼び出しは `名前空間.モジュール.アクション` の形のアクションIDに続けて、名前付きパラメータ(`パラメータ名: 値`)を並べ、出力は `=>` で変数に紐づける。例: `Text.SplitText.SplitWithDelimiter Text: Row CustomDelimiter: $'''\s+''' IsRegEx: True Result=> Columns`、`Excel.WriteToExcel.WriteCell Instance: ExcelInstance Row: RowIndex Column: ColumnIndex Value: Column`。文字列・パス表現はトリプルシングルクォート `$'''...'''`(Windowsパスはバックスラッシュを二重化)。セクションは `**REGION <name>` / `**ENDREGION` でグルーピングされ、各アクション行の前に `@@copilotGeneratedAction: 'True'` のようなタグが付くケースがある — [Hardik-S/geodata raw file](https://raw.githubusercontent.com/Hardik-S/geodata/main/geodata%20PAD%20Flow%20as%20text.txt)
- Microsoft公式リリースノート(2021 wave 1)は、PADデザイナーの「拡張されたコピー&ペースト機能」が「画像とUI要素もコピーするようになった」ことと、「この機能はクリップボード経由でも利用できる」ことを明記している。つまりアクションのコピー結果はクリップボードに置かれるテキスト(+添付のUI要素/画像データ)であり、これが上記のテキストDSLの出どころであることが裏付けられる — [Enhanced copy and paste feature (archived release plan page)](https://learn.microsoft.com/en-gb/power-platform-release-plan/2021wave1/power-automate/enhanced-copy-paste-feature)
- Power Fx 対応版フローのドキュメントには、アクションの入力欄がテキストとして記述される際のルールが詳述されている: 式は `=` で始まる必要があり(例 `=Sum(10,20)`)、文字列補間は `${式}` 構文を使う(例 `The total number is ${Sum(10, 20)}`)。これは UI/Web セレクタの中でも使える、と明記されている — [Power Fx in desktop flows](https://learn.microsoft.com/en-us/power-automate/desktop-flows/power-fx)
- 同ドキュメントは、Power Fx 有効化フローでは **`Switch` / `Case` / `Default case` アクションが現時点でサポートされていない** という既知の制限を明記している — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/power-fx)
- 同ドキュメントのバージョン履歴には、Power Fx 無効フローでは不明な型のオブジェクトを「General value」と呼ぶのに対し、Power Fx フローでは厳格な型システムを使い、`dynamic variable`(実行時に型/値が変わる変数)と `dynamic value`(実行時にスキーマが決まる値)を区別する、という型モデルの説明がある — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/power-fx)

### Inferences
- geodata リポジトリのサンプルは「コピー&ペースト」機能由来のテキスト表現であり、これはおそらく **PAD内部の永続フォーマットそのものではなく、UI操作用の中間テキスト表現(デザイナーのクリップボード形式)** である可能性が高い。ただし、構文(`名前空間.モジュール.アクション パラメータ: 値 Result=> 変数`)は PAD のアクションスキーマ(名前空間付きアクションID、名前付きパラメータ、明示的な出力変数指定)の実態をかなり正確に反映していると考えられ、内部データ構造(JSON等)もおそらく同様に「アクションID + パラメータ辞書 + 出力変数名」の形を取っていると推測できる。
- `If` アクションが Power Fx 版では「単一の条件式を受け取る」という記述(前のバージョンは複数オペランドを受け取っていた)から、非Power Fx版の `If` は複数の「オペランド1 演算子 オペランド2」のペアを保持する構造(AND/OR で複数条件を結合)だったことが推測される。

### Gaps
- geodata のテキストファイルには If ブロックや UI 要素セレクタの実例が含まれておらず、`IF`/`SWITCH`/マウスクリック等アクションの具体的なテキスト構文(あるいはJSON/XML構文)を直接確認することはできなかった。
- PAD がディスク/Dataverse に保存する際の**内部シリアライズ形式**(クリップボードのテキストDSLとは別物である可能性がある、JSON/XML/独自バイナリのいずれか)を直接確認できる公式資料は見つからなかった。
- 「マウスクリック」「待機」など具体的なアクション名ごとのパラメータ名一覧(スキーマ)を列挙した公式リファレンスは、今回のクロールでは発見に至らなかった(Microsoft Learn の actions-reference 配下に存在する可能性が高いが、個別アクションページへの深掘りは本調査のスコープ内で未実施)。

---

## UI要素セレクタはフロー定義内でどのような形式で保存されているか?

### Takeaway
PAD の UI 要素セレクタは、XPathに似た **階層的な属性条件のブラケット記法**(`:desktop > window[Name="..."][Process="..."]` のような文字列)として表現される。UIA (UI Automation) と MSAA (Microsoft Active Accessibility) の2種類のアクセシビリティAPIベースのセレクタに対応し、1つのUI要素に複数セレクタを持たせてフォールバックできる仕組みがあるが、セレクタがファイル内で具体的にどのバイト表現(プレーン文字列 / XML属性 / JSON配列)で保存されているかは確認できなかった。

### Cited Findings
- セレクタは「要素のアプリケーション階層内での位置を示すレベル」から構築され、`>` 記法で階層を示す。Notepad の例: `:desktop > window[Name="Notes.txt - Notepad"][Process="Notepad"]` — [Build a custom selector](https://learn.microsoft.com/en-US/power-automate/desktop-flows/build-custom-selectors)
- セレクタ内で変数を使うと `:desktop > window[Name="%WindowName%"][Process="Notepad"]` のような形になる(`%変数名%` 構文) — [同上]
- UI要素ピッカーは UIA と MSAA の両方のセレクタをキャプチャできる。UIA が既定の推奨方式で、MSAA はUIAでアクセスできない旧式/独自UIのアプリケーション向け — [UI elements (en-US)](https://learn.microsoft.com/en-US/power-automate/desktop-flows/ui-elements)
- 等価演算子と「含む」以外にも複数の演算子があり、その一つは正規表現マッチで、正規表現エンジンは .NET のものを使用する — [Build a custom selector](https://learn.microsoft.com/en-US/power-automate/desktop-flows/build-custom-selectors)
- 1つのUI要素に対して複数のセレクタを保持でき、あるセレクタが失敗すると定義された順序で次のセレクタが使われる(フォールバック機構) — [同上]
- セレクタビルダーには「ビジュアルエディタ」と「テキストエディタ」の両方があり、ユーザーが上記のブラケット記法を直接テキストとして編集できる — [同上]
- Power Fx 対応フロー(v2.43以降)では、UI/Web要素セレクタの構文内で変数や Power Fx 式を使うことができ、文字列補間構文 `${式}` をセレクタ内に書ける(例: ドル記号自体をリテラルとして使いたい場合は `${` のようにエスケープする) — [Power Fx in desktop flows](https://learn.microsoft.com/en-us/power-automate/desktop-flows/power-fx)

### Inferences
- セレクタの「テキストエディタ」でユーザーが直接編集できる文字列表現(`:desktop > window[...][...]`)が、おそらくそのままフロー定義内の保存値(文字列プロパティ)として使われている可能性が高い。すなわちセレクタは構造化されたXML/JSON木ではなく、**1本の文字列としてシリアライズされたブラケット記法のパス式**として保存されていると推測される(XPathに類似した設計思想)。

### Gaps
- セレクタがフロー定義のJSON/XML/バイナリのどの「フィールド」に、どのようなキー名で格納されるか(例: `Selector` プロパティ、`UIElement` オブジェクトの一部かなど)を示す一次資料は見つからなかった。
- UIA/MSAA の切り替えがデータ形式上どう区別されるか(プロパティのプレフィックスが異なるのか、別々のフィールドを使うのか)は確認できなかった。

---

## 変数のスコープ・型、制御フロー(条件分岐・ループ・エラーハンドリング)はどう表現されるか?

### Takeaway
PAD には「Power Fx 無効フロー」と「Power Fx 有効フロー」の2つの型システム/構文体系があり、後者は厳格な型付け(Power Fx の型システム)を採用し、`dynamic variable`/`dynamic value`/`untyped object` という明確な概念を持つ。制御フロー(If/Loop)はブロック構造(`LOOP FOREACH ... END` 等)として表現されることがテキストDSLから確認できたが、エラーハンドリング(On Error ブロック等)の具体的な表現形式は確認できなかった。

### Cited Findings
- Power Fx 無効フローでは、不明な型のオブジェクトを指す用語として「General value」が使われる。Power Fx 有効フローは厳格な型システムを使い、`dynamic variable`(実行時に型または値が変わる変数)と `dynamic value`(実行時にスキーマが決まる値)を区別する — [Power Fx in desktop flows](https://learn.microsoft.com/en-us/power-automate/desktop-flows/power-fx)
- Power Fx 有効フローでは配列・リストのインデックスが Excel式と同様の **1始まり**(1-based)になる(例: `Index(numbersArray, 1)` が先頭要素を返す)。これは非Power Fx版の0始まりインデックスとは異なる — [同上]
- Power Fx 有効フロー(v2.43以降)では変数名が**大文字小文字を区別する**ようになった(`NewVar` と `newVar` は別の変数)。v2.42以前は大文字小文字を区別しなかった — [同上]
- Power Fx 有効フローでは、使用前に変数を初期化する必要があり、未初期化変数を式内で使うとエラーになる — [同上]
- `If` アクションは、Power Fx 有効フローでは単一の条件式を受け取る形に変わった。これは「以前は複数のオペランドを受け取っていた」ことを示唆する記述である — [同上]
- 「動的な値(dynamic value)」とされるのは、データテーブル、スキーマ不明なカスタムオブジェクト、「.NETスクリプトの実行」アクションのような動的アクション出力、「デスクトップフローの実行」アクションの出力、事前定義スキーマのないアクション出力(例: 「Excelワークシートから読み取る」「リストから作成」)である — [同上]
- データテーブルの読み取りには `Index(Index(DataTableVar, 1), 2)` のような二重 `Index()` 呼び出しで行・列を指定する — [同上]
- v2.48 では、`Read from Excel`、`Read from CSV`、`Extract data from a web`、`Extract data from window`、`Execute SQL statement`、`Convert JSON to a custom object` といったアクションの出力が、以前は「dynamic variable + 警告」だったのが「untyped data table / untyped custom object」という明示的な型に変わった — [同上]
- `Switch`/`Case`/`Default case` アクションは Power Fx 有効フローでは**現時点で未サポート**という制限がある(=控除分岐の制御フロー表現が全フロー種別で統一されていない) — [同上]
- geodata のテキストDSLサンプルから、ループは `LOOP FOREACH <item> IN <collection>` ～ `END` という明示的な開始・終了キーワードを持つブロック構造で表現され、ネスト(入れ子ループ)が可能であることを直接確認した — [Hardik-S/geodata raw file](https://raw.githubusercontent.com/Hardik-S/geodata/main/geodata%20PAD%20Flow%20as%20text.txt)

### Inferences
- Power Fx 有効フローと無効フローは単に「式の書き方」が違うだけでなく、**変数の型システム・大文字小文字区別・配列インデックスの基準・サポートされるアクション集合(Switchが使えない等)が異なる、事実上別の内部表現/実行モデル**である可能性が高い。パーサーを実装する場合、両モードを区別して扱う必要がある。
- `If` アクションの構造変化(複数オペランド→単一式)は、フロー定義のスキーマバージョン管理(Power Fx有効/無効のフラグ)が各アクションのプロパティ構造に直接影響することを示しており、単一の固定スキーマで全バージョンのPADフローをパースすることはできないと推測される。

### Gaps
- エラーハンドリング(On Error ブロック、リトライ/例外時フロー)がフロー定義内でどのような構造(ブロック、プロパティ、添付アクション等)で表現されるかについて、信頼できる一次情報は見つからなかった。
- 変数の「スコープ」(フロー全体 vs サブフロー内ローカル vs ブロック内ローカル)がデータ構造上どう境界付けられるかの具体的な記述は見つからなかった。
- `If`/`Switch` の非Power-Fx版での具体的な条件式プロパティ名(オペランド1/オペランド2/演算子をどう格納するか)は未確認。

---

## Microsoft公式ドキュメントにフロー定義フォーマットの仕様は公開されているか? "Save as code"/Export 機能とPower Fxとの関係は?

### Takeaway
"Save as code" という名称の機能そのものは今回の調査では確認できなかった。一方で、"Work with desktop flows using code"(開発者向けAPIガイド)という公式ページは存在し、これは **Dataverse Web API を介したフローの一覧取得・入出力スキーマ取得・トリガー実行・キャンセル** を提供するものであり、フロー内部の個々のアクション(UIクリック、If、Loopなど)の定義を取得・編集するAPIではない。Power Fx はフロー内の「式」を記述する言語として統合されているが、これはフロー全体をPower Fxコードとして保存・エクスポートする機能ではない。

### Cited Findings
- 公式ページ「Work with desktop flows using code」(developer/desktop-flow-public-apis)は、Dataverse Web API経由で (1) `category eq 6` でフィルタしてデスクトップフロー一覧を取得、(2) `workflows([Workflow Id])/inputs/$value` と `/outputs/$value` で入出力のJSONスキーマ(`{"schema":{"properties":{...},"type":"object"}}`形式)を取得、(3) `Microsoft.Dynamics.CRM.RunDesktopFlow` アクションでフローを起動、(4) `flowsessions` エンティティで実行状態・出力を取得、(5) `CancelDesktopFlowRun` でキャンセル、という機能を提供すると明記している。ただしこれらはいずれも「フローの入出力」や「実行状態」であり、**フロー内部のアクション列定義そのものを返すエンドポイントは記載されていない** — [Work with desktop flows using code](https://learn.microsoft.com/en-us/power-automate/developer/desktop-flow-public-apis)
- 同ページには、入力スキーマ取得の実例レスポンスが示されている: `{"schema":{"properties":{"inputText":{"default":"","description":"","format":null,"title":"inputText","type":"string","value":""}, ...},"type":"object"}}`。これはJSON Schemaに近い形式である — [同上]
- Power Fx の公式ドキュメントは、Power Fx を「Power Platform全体で論理を表現する低コード言語」であり「汎用・強い型付け・宣言的・関数型のプログラミング言語」と説明し、「Excelのような数式バーやVisual Studio Codeのテキストウィンドウで直接扱える」と述べている。つまりPower Fxは**式(expression)の言語**であり、フロー全体の保存形式を指すものではない — [Power Fx in desktop flows](https://learn.microsoft.com/en-us/power-automate/desktop-flows/power-fx)
- Power Fx統合はPAD v2.39以降が前提条件であり、フロー作成時にコンソールでトグルを有効化する必要がある(=フロー単位で有効/無効を選択する設定であり、既存の非Power Fxフロー形式と並存する) — [同上]
- クラウドフロー(Power Automate/Logic Apps)については、定義が Azure Logic Apps と同じスキーマを共有するJSONオブジェクトである、という説明がコミュニティ記事にある。ただしこれは**クラウドフロー**の話であり、デスクトップフローのアクション定義フォーマットとは別物である — [DEV Community: Understanding the Power Automate definition](https://dev.to/wyattdave/understanding-the-power-automate-definition-42po)

### Inferences
- デスクトップフロー専用の「公開された(文書化された)スキーマ定義」は、クラウドフロー(Logic Apps ワークフロー定義言語のように `workflowdefinition.json` スキーマが公開されている)と比較して**存在しない、または非公開**であると判断できる。公式開発者ガイドが提供するのは「外側からフローを呼び出す/監視するAPI」のみで、「フロー内部の中身を読み書きするAPI」ではない。
- このことから、"Power Fx 統合" は既存のアクション中心(ビジュアルデザイナー)モデルに「式の書き方」を追加するものであり、フロー定義フォーマット自体を公開テキスト形式(例: YAMLファイルへのexport)に置き換えるものではないと考えられる。

### Gaps
- "Save as code" という名称の機能が実際にPADまたはPower Automate(クラウド)に存在するかどうかは確認できなかった(検索結果はPower Fx一般の説明のみで、該当機能名への言及なし)。この名称はユーザーの誤認か、または別のPower Platform機能(例: Power Apps の "View code"系機能)との混同の可能性がある。
- 公式スキーマ定義(JSON SchemaやXSDなど)がGitHubやLearn上で公開されているかどうかは、今回の検索では発見できなかった。

---

## プログラム的に読み込む/変換するためのSDK・API、コミュニティの知見(リバースエンジニアリング報告)はあるか?

### Takeaway
公式のSDK/APIはDataverse Web API経由の「実行・監視」用途に限定され、フロー内部構造を読み書きするための公式SDKは見つからなかった。コミュニティ側は、サードパーティの非公式エクスポート/インポートツール(UiPath Marketplace製、WinAutomation由来の独自形式を使用)や、個人のPoC(GitHub `Hardik-S/geodata`)、フォーラムでの部分的なリバースエンジニアリング報告(Schema V1→V2でのフォーマット変化)にとどまっている。

### Cited Findings
- `pypowerautomate`というPythonパッケージ(PyPI)が存在するが、これは「Power Automate フローをプログラム的に作成・管理・デプロイするためのPythonパッケージ」であり、**クラウドフローのJSONを生成する**ためのものであって、既存フロー(特にデスクトップフロー)を読み込んでパースするものではない — [pypowerautomate · PyPI](https://pypi.org/project/pypowerautomate/)
- UiPath MarketplaceのPAD_ExportFlows/PAD_ImportFlowsは「PADはフローのエクスポート/バックアップ作成を許可していない」と明言し、その代替として、サブフローを`.subflow`ファイル、入出力を`.arg`ファイルとして書き出す独自方式(WinAutomation構文ベース)を提供している。これは公式フォーマットの読み書きではなく、サードパーティが独自に設計した相互変換レイヤーである — [Export PAD Flows](https://marketplace.uipath.com/listings/export-power-automate-desktop-pad-flows); [Import PAD Flows](https://marketplace.uipath.com/listings/import-power-automate-desktop-pad-flows)
- GitHubの個人リポジトリ `Hardik-S/geodata` には、PADからエクスポートしたフローのプレーンテキスト版が含まれ、README には「元の記録マシンの絶対Windowsパスがそのまま含まれるため、再実行時に置き換えが必要」という実務上の注意点も記載されている — [Hardik-S/geodata](https://github.com/Hardik-S/geodata)
- Power Users コミュニティのフォーラムスレッドでは、投稿者が「デスクトップフロー用のxamlのようなファイルを取得してパーサーを作れないか」と質問し、別の投稿者が「ソリューションをエクスポートすると各デスクトップフローごとにJSONファイルが得られるが、エンコードされたパッケージ記述になっている」「Schema V2ではこのパッケージ文字列はもう存在せず、代わりにデスクトップフローバイナリがある」と回答している。これはコミュニティが実際に試行し、フォーマットの世代差を観測した一次証言である — [Power Users community thread](https://powerusers.microsoft.com/t5/Power-Automate-Desktop/Governance-Monitoring-Power-Automate-Desktop-Flows/m-p/2656902)

### Inferences
- 公式SDK/APIが「実行・監視」に限定されていることと、コミュニティが非公式ツールや手動リバースエンジニアリングに頼っていることから、**PADフロー定義フォーマットをPythonで安定的にパースするには、公式に文書化された仕様が存在しないという前提で、サンプルファイルからの経験的なリバースエンジニアリングが必要**になると考えられる。
- 「Schema V2でバイナリ化した」という証言が事実であれば、将来的に(あるいは現在のPADバージョンで)フォーマットが暗号化/圧縮されたバイナリになっている可能性があり、単純なテキスト/XML/JSONパーサーでは対応できないケースが既に生じていることを示唆する。この点はパーサー実装の初期段階で、対象とするPADのバージョン/エクスポート経路(ソリューションエクスポート vs コンソールからの個別フロー vs クリップボードコピー)を明確に切り分ける必要がある。

### Gaps
- Schema V1からV2への変化を詳細に解説した技術記事・GitHub Issue(コードサンプル付き)は発見できなかった。フォーラムの投稿者コメント以上の裏付けは得られていない。
- WinAutomationの `.amp` ファイル自体(PADの前身であるWinAutomationのネイティブフォーマット)についての直接的な技術文書は発見できなかった。関連製品(Fortra/HelpSystemsのAutomate Desktop)が使う「AML (Automation Markup Language)」というXML風マークアップ言語は見つかったが、これはWinAutomationとは別系統の製品(買収・ブランド変遷の経緯が異なる)のドキュメントであり、WinAutomationの`.amp`形式の直接証拠としては使えない。AMLの例: `<AMVARIABLE NAME=... VALUE=...>`のような属性ベースのXMLタグ構造(出典: [AML Introduction](https://hstechdocs.helpsystems.com/manuals/automate/automate_desktop/am_11/Content/Advanced/Introduction_to_AML.htm))。WinAutomationがMicrosoftに買収される前、同じ血統のフォーマットを使っていたかどうかは未確認であり、この類推は推測の域を出ない。
- GitHub上で「PADフローパーサー」を主目的とした、ある程度の規模のオープンソースプロジェクト(スター数や実際のコード規模を伴うもの)は、今回の検索では発見できなかった。`pypowerautomate`はクラウドフロー生成ツールであり対象外。
