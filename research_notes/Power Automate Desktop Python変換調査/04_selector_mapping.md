# PAD UI要素セレクタ ⇔ pywinauto 要素特定方法の対応関係・制約・落とし穴

## PADの「UI要素の追加」機能で生成されるセレクタは内部的にどのようなプロパティ(AutomationId, Name, ControlType, ClassName, 階層パス等)を保持しているか

### Takeaway
PADのUI要素は「複数のセレクタ」の集合として保存され、各セレクタは `element[Attr1="Val1"][Attr2="Val2"]...` という属性付きノードを `>` でつないだ階層(ツリー)構造を持つ。デスクトップ要素では `Name`・`Process` などのアプリ依存属性が使われ、Webページ要素はHTML属性(id/class等)を使う、という点がMicrosoft公式ドキュメントで明記されている。AutomationId/ClassName/ControlTypeという具体的なUIAプロパティ名そのものを列挙した一次情報は見つからなかった(推測で補う必要がある)。

### Cited Findings
- 「Each one of these action groups accepts a different type of UI elements... Each selector consists of multiple elements representing the hierarchical structure of the UI element in the application or webpage. The attributes describe each element uniquely and distinguish it from other elements.」— [Automate using UI elements](https://learn.microsoft.com/en-us/power-automate/desktop-flows/ui-elements)
- UI要素は「UI elements pane」で管理され、右クリック→「Edit」でセレクタビルダー(ビジュアル/テキストエディタ)を開いて編集できる。1つのUI要素に複数セレクタを持たせ、失敗時は定義順で次のセレクタにフォールバックする。— [Automate using UI elements](https://learn.microsoft.com/en-us/power-automate/desktop-flows/ui-elements)
- セレクタの記法: `element[Attribute1="Attribute1Name"][Attribute2="Attribute2Name"]...[Attributen="AttributenName"]` を `>` でつないで階層を表現する。「Web and desktop selectors have the same structure and functionality. The main differences between them are the available attributes. Web selectors use HTML attributes, while desktop selectors use different kinds of attributes based on the application design.」— [Build a custom selector](https://learn.microsoft.com/en-us/power-automate/desktop-flows/build-custom-selectors)
- Notepad例: `:desktop > window[Name="Notes.txt - Notepad"][Process="Notepad"]` のように `Name` と `Process` 属性が使われる。— [Build a custom selector](https://learn.microsoft.com/en-us/power-automate/desktop-flows/build-custom-selectors)
- テキストベースセレクタ機能では「デスクトップ自動化では捕捉した要素の `Name` 属性、ブラウザ自動化では `Text` 属性」を使う。SAPアプリは例外で `Text` 属性(通常は `ID` 属性ベースの既定セレクタの方が効率的)を使う。— [Automate using UI elements](https://learn.microsoft.com/en-us/power-automate/desktop-flows/ui-elements)
- 既知の制限として、「Add UI element」でウィンドウにホバーしてテキストで要素を捕捉すると、`Process` 属性と `Name` 属性を含む既定セレクタが生成される、という具体例がある。— [Automate using UI elements](https://learn.microsoft.com/en-us/power-automate/desktop-flows/ui-elements)
- サードパーティ(Robility)ドキュメントでは「Desktop UIA3を使う際はまず `AutomationID` をセレクタに使い、nullの場合は他の属性組み合わせにフォールバックすべき」という実務上の助言がある(Microsoft公式ではない点に注意)。— [Robility doc](https://robilitydocs.sutherlandglobal.com/robility7/node/2927) (検索結果の要約から、一次ページ本文は未確認)

### Inferences
- PADのセレクタはUIAの「プロパティ名=値」のペアをそのままノード属性として埋め込む設計であり、属性名(`Name`, `Process`, `Id`, `ClassName`, `ControlType`等)はキャプチャモード(UIA/UIA3 Raw/MSAA)やアプリ種別によって利用可能な集合が変わると考えられる。
- 階層全体を保持する(`:desktop > window[...] > pane[...] > ...`)点は、XPath的な「祖先ノードの属性列を連結したパス」であり、pywinautoの`child_window()`の`parent`指定や`.child_window().child_window()`のチェーンに近い構造だが、PADは1つの文字列セレクタに全階層を埋め込む点が異なる。

### Gaps
- Microsoft公式ドキュメント上で「セレクタ属性の全リスト」(AutomationId, ClassName, ControlType, FrameworkId, RuntimeId等UIAプロパティに対応する属性名)を明示したページは検索で見つからなかった。実機のUI要素ピッカーでテキストエディタを開いて実際の属性名を確認する必要がある(未検証)。
- UIA3 Rawモードで追加される「中間階層・非対話要素・フレームワークレベルの要素」が具体的にどのプロパティを追加露出するかの詳細リストも見つからなかった。

---

## PADはMicrosoft UI Automation (UIA) フレームワークをベースにしていると言われるが、具体的にどのAPIレイヤーを使っているか(UIA2/UIA3、またはWin32 API/MSAAとのフォールバック)が分かる情報はあるか

### Takeaway
Microsoft公式ドキュメントが「UIA」「UIA3 Raw」「MSAA」という3つのキャプチャモードを明記しており、PADが内部的にUI Automationのバージョン3(UIA3)の「Raw View」にアクセスする機能を持つことが一次情報で確認できる。既定はUIA(Control View相当)で、UIAで要素が取得できない場合にMSAA(レガシーアプリ向け)やUIA3 Raw(Electronアプリ等の複雑なUI構造向け)に切り替えることが推奨されている。PADの実装言語(.NET/FlaUI使用の有無)を直接裏付ける公式情報は見つからなかった。

### Cited Findings
- 「The UI element picker supports capturing UI Automation (UIA), Raw view of UI Automation v3 (UIA3 Raw), and Microsoft Active Accessibility (MSAA) selectors when working with desktop UI elements. By default, the picker operates in UIA mode.」— [Automate using UI elements](https://learn.microsoft.com/en-us/power-automate/desktop-flows/ui-elements)
- UIAは「UIAは、MSAAを置き換えるためにMicrosoftが導入した最新のアクセシビリティフレームワークであり、WPF・WinForms・UWPなど新しいUIフレームワークで構築されたアプリケーションの自動化に推奨される」— [Automate using UI elements](https://learn.microsoft.com/en-us/power-automate/desktop-flows/ui-elements)
- MSAAは「UIAに先行する古いアクセシビリティ技術で、VB6やクラシックWin32などUIA要素を公開しないレガシーアプリケーション向け」— [Automate using UI elements](https://learn.microsoft.com/en-us/power-automate/desktop-flows/ui-elements)
- UIA3 Rawは「UIA3フレームワークを使用して、生の(フィルタされていない)UI要素ツリーにアクセスする高度なUI Automationベースのキャプチャモード。標準のUIAセレクタがアプリケーションの洗練されたControl Viewに依存するのに対し、UIA3 Rawは中間要素・非対話要素・フレームワークレベルのコンポーネントを含むUI階層のすべての要素を公開する。カスタムレンダリングされたコントロール、Electronベースのアプリ、標準UIAセレクタで要素にアクセスできない場合に特に有用。」— [Automate using UI elements](https://learn.microsoft.com/en-us/power-automate/desktop-flows/ui-elements)
- FlaUI(.NET向けオープンソースUI Automationライブラリ、PADと直接の関係は確認できていないが同種の技術スタック)は`FlaUI.UIA2`(MSAAベース、古いアプリ向け)と`FlaUI.UIA3`(新しいUI Automation 3フレームワークを実装、現在もメンテナンスされている版)に分かれる。— [FlaUI.UIA3 on NuGet](https://www.nuget.org/packages/FlaUI.UIA3/) / [einfochips.com記事](https://www.einfochips.com/blog/getting-started-with-flaui-open-source-ui-automation-for-windows-apps/)

### Inferences
- PADが「UIA3 Raw」という名称を公式ドキュメントで明示的に使っていることから、PADの内部実装(Microsoftのクローズドソース製品)はUI Automationのバージョン3系COMインターフェース(`IUIAutomation3`等、`UIAutomationCore.dll`)に直接アクセスできる経路を持つと考えられる(「〜と推測される」)。これは.NET言語で書かれたWindowsデスクトップ製品が一般に採用する構成(FlaUI.UIA3や`Interop.UIAutomationClient`などのUIA3 COM相互運用層経由)と符合するが、PADチームが実際にFlaUIを使っているかどうかを直接裏付ける一次資料はない。
- UIA/UIA3 Raw/MSAAの3モード切替をユーザーに公開していることから、PADは単一のAPIレイヤーに固定されておらず、要素が見つからない場合に手動でモードを切り替える「フォールバック」をユーザー操作に委ねる設計であり、自動フォールバックではないと考えられる。

### Gaps
- PADの実装言語・使用ライブラリ(C#/.NET + FlaUIか、独自UIAラッパーか)を直接明言したMicrosoft公式資料は見つからなかった。
- 「UIA2」という用語自体はMicrosoft公式のPADドキュメントには出現しない(FlaUIのような第三者ライブラリの文脈でのみ確認)。PADがUIA2(managed `System.Windows.Automation`経由)相当の経路を内部的に持つかどうかは不明。

---

## pywinautoには"uia"バックエンドと"win32"バックエンドがあるが、それぞれの要素特定の仕組み(プロパティの違い、対応するコントロールタイプの違い)はどうなっているか

### Takeaway
pywinautoは2つのバックエンドを持ち、`win32`(既定、Win32 API/MFC・VB6・VCL・簡易WinForms向け)と`uia`(MS UI Automation、WPF・WinForms・UWP・Qt5・ブラウザ向け)で、同じアプリでも取得できる階層・プロパティ・コントロール種別が異なる。`uia`バックエンドは`comtypes`ライブラリを介して`UIAutomationCore.dll`のCOMオブジェクトにアクセスする一方、`win32`バックエンドはすべてのコントロールにウィンドウハンドルを要求するため、UIA要素の一部(ハンドルを持たない要素)は`win32`バックエンドから見えない。

### Cited Findings
- サポートされるアクセシビリティ技術は「Win32 API (backend="win32") - a default backend for now」と「MS UI Automation (backend="uia")」の2つ。— [pywinauto Getting Started Guide](https://pywinauto.readthedocs.io/en/latest/getting_started.html)
- 判別の実務指針:「Microsoft's Spy++ showing all the controls → "win32"で十分。Inspect.exeをUIAモードに切り替えてSpy++より多くのコントロール・プロパティが見える → "uia"を選ぶべき」— [pywinauto Getting Started Guide](https://pywinauto.readthedocs.io/en/latest/getting_started.html)
- 「Win32 API technology ("win32" backend in pywinauto) provides an identifier(handle) for every control. UI Automation API ("uia" backend in pywinauto) may not provide window handle for every GUI element. Such an element is not visible to "win32" backend.」— [pywinauto HowTo doc](https://github.com/vasily-v-ryabov/pywinauto/blob/master/docs/HowTo.txt)
- Application/DesktopオブジェクトはバックエンドごとにPythonオブジェクトとして指定する(`Desktop(backend="uia")`, `Application(backend="uia")`)。— [pywinauto Getting Started Guide](https://pywinauto.readthedocs.io/en/latest/getting_started.html)
- `uia`バックエンドは`comtypes`に依存しており、「custom properties and controls are not supported because of comtypes Python library restrictions」という制約がある。— [pywinauto Getting Started Guide](https://airelil-pywinauto.readthedocs.io/en/atspi/getting_started.html)
- `uia`バックエンドのAPIリファレンスには「`UIAutomationCore.dll`のグローバルCOMオブジェクトを保持するシングルトンクラス」や「UIAフィルタ条件を組み立てる`build_condition`ヘルパー」が存在する(=生のCOM経由でUIAにアクセスしている構造)。— [pywinauto.uia_defines docs](https://pywinauto.readthedocs.io/en/uia/code/pywinauto.uia_defines.html)
- 0.6.4のリリースノートで「multi-threading mode (MTA) for comtypes is enabled by default」という変更がある。— [pywinauto 0.6.4 release notes](https://github.com/pywinauto/pywinauto/releases/tag/0.6.4)
- バックエンドを切り替えると同じアプリでも異なる階層が見える、とGetting Startedガイドが明記。— [pywinauto Getting Started Guide](https://pywinauto.readthedocs.io/en/latest/getting_started.html)
- 両バックエンドともに`find_elements`/`find_window`に以下のキーワード条件を渡せる(`backend`引数で対象バックエンドを選択): `class_name`(「このウィンドウクラスを持つ要素」), `class_name_re`(クラス名の正規表現), `title`(「このテキストを持つ要素」), `title_re`(テキストの正規表現), `auto_id`(「このautomation idを持つ要素(UIAutomation要素向け)」), `control_type`(「この文字列のコントロールタイプを持つ要素(UIAutomation要素向け)」), `framework_id`(「このframework idを持つ要素(UIAutomation要素向け)」), `backend`(検索に使うバックエンド名), `best_match`(「このタイトルに類似した要素」), `handle`(返すべき要素のハンドル), `ctrl_index`(子要素のインデックス), `found_index`(フィルタ後の子要素のインデックス), `predicate_func`(カスタム検証用フック), `top_level_only`(既定True), `visible_only`(既定True), `enabled_only`(既定False), `active_only`(既定False), `process`(このプロセスで動作する要素)。— [pywinauto.findwindows docs](https://pywinauto.readthedocs.io/en/latest/code/pywinauto.findwindows.html)
- `auto_id`・`control_type`・`framework_id`は明示的に「for UIAutomation elements」と注記されている=`win32`バックエンドでは実質的に使えない/意味を持たないプロパティである。— [pywinauto.findwindows docs](https://pywinauto.readthedocs.io/en/latest/code/pywinauto.findwindows.html)

### Inferences
- `auto_id`, `control_type`, `framework_id`はUIAバックエンド専用の検索キーであるため、PADの`AutomationId`/`ControlType`属性をpywinautoに渡す場合は必ず`backend="uia"`を選択する必要があり、`win32`バックエンドでは単純に無視されるか機能しない。
- `win32`バックエンドが要求するウィンドウハンドルはPAD側のセレクタには存在しない概念であり、変換時に失われる情報(逆方向のギャップ)である。

### Gaps
- `uia`バックエンドが内部的にUIA2相当(managed API)ではなくUIA3相当(COM直接)のインターフェースを使っているかを明言した一次ドキュメントは見つからなかった。`comtypes`経由で`UIAutomationCore.dll`のCOMオブジェクトに直接アクセスしている記述から、COMネイティブ層(UIA3相当)にアクセスしていると推測されるが、「UIA3」という用語そのものをpywinauto公式ドキュメントが使っている箇所は確認できなかった。

---

## PADのセレクタ情報をpywinautoのchild_window()やfind_elements()系のAPI呼び出しに変換する際、どのプロパティが1:1で対応し、どのプロパティが対応しないか

### Takeaway
PADの`Name`はpywinautoの`title`(UIAの`Name`プロパティ相当)に、PADの`AutomationId`はpywinautoの`auto_id`に、PADの階層(`>`で連結されたセレクタツリー)はpywinautoの`child_window()`のネストまたは親子関係指定に、それぞれ概念的に対応する。一方でPADの`Process`属性はpywinautoでは`Application`接続時のプロセス指定(`process`キーワード)に対応するが、セレクタ内の階層ノード属性としては扱われない。PADの演算子(`Contains`/`Starts with`/`Ends with`/正規表現)はpywinautoでは`title_re`/`class_name_re`のような`_re`サフィックス付きの正規表現キーのみが直接対応し、「Contains」「Starts with」専用のキーワードはない(正規表現で表現する必要がある)。

### Cited Findings
- pywinautoの`find_elements`/`child_window`系が受け付ける主要キーワードは前問で列挙した通り: `class_name`, `class_name_re`, `title`, `title_re`, `auto_id`, `control_type`, `framework_id`, `backend`, `best_match`, `handle`, `ctrl_index`, `found_index`, `predicate_func`, `top_level_only`, `visible_only`, `enabled_only`, `active_only`, `process`。— [pywinauto.findwindows docs](https://pywinauto.readthedocs.io/en/latest/code/pywinauto.findwindows.html)
- PADのセレクタ属性として確認できた主要なものは`Name`と`Process`(Notepad例)で、演算子として`Equal to`(既定)/`Contains`/`Not equal to`/`Starts with`/`Ends with`/`Regular expression match`(.NET正規表現エンジン)が使える。— [Build a custom selector](https://learn.microsoft.com/en-us/power-automate/desktop-flows/build-custom-selectors)
- テキストベースセレクタはデスクトップでは`Name`属性、ブラウザでは`Text`属性を使う。— [Automate using UI elements](https://learn.microsoft.com/en-us/power-automate/desktop-flows/ui-elements)
- pywinautoの`title`は「window text, name」の意味であり、UIAの`Name`プロパティに相当する。— [pywinauto Getting Started Guide (uia fork)](https://pywinauto-fork.readthedocs.io/en/uia/getting_started.html)
- pywinautoの`print_control_identifiers()`は各コントロールについて`child_window(title=..., auto_id=..., control_type=...)`形式の実行可能なコード片を出力する(Calculator例: `child_window(title="Type:", auto_id="13080", control_type="Text")`)。— [pywinauto Getting Started Guide](https://pywinauto.readthedocs.io/en/latest/getting_started.html)
- pywinautoの`best_match`は「あいまい一致」用のキーで、内部的には`difflib`ベースの`FuzzyDict`/`findbestmatch`モジュールが使われ、既定の一致比率閾値(`limit_ratio`、既定0.5)を下回るとマッチエラーになる。— [pywinauto.findbestmatch docs](https://pywinauto.readthedocs.io/en/latest/code/pywinauto.findbestmatch.html)
- `found_index`は「同一プロパティを持つ複数要素がある場合の曖昧さ解消」のためにウィンドウ指定へ追加できるキーである。— [StackOverflow回答の要約](https://kiwix.lema.org/stackoverflow.com_en_all_2023-11/questions/70965104/how-to-set-focus-on-child-window-with-the-same-name)

### Inferences
- 1:1対応がある程度成立するプロパティ: PAD `Name` ⇔ pywinauto `title`(UIA `Name`プロパティ); PAD `AutomationId`(推測含む) ⇔ pywinauto `auto_id`; PAD `ControlType`(推測含む) ⇔ pywinauto `control_type`; PAD `ClassName`(推測含む) ⇔ pywinauto `class_name`。
- PADにあるがpywinautoに(キーワードとして)直接存在しないもの: `Process`は`child_window`の条件キーではなく、`Application.connect(process=...)`や`find_elements(process=...)`のレベルで扱う別概念である。PADの「演算子(Contains/Starts with/Ends with)」はpywinautoでは専用キーワードがなく、`title_re`/`class_name_re`に正規表現(`.*foo.*`, `^foo`, `foo$`)を書くことで模倣する必要がある。PADの「有効/無効化できる複数セレクタの順序フォールバック」機能に相当する仕組みはpywinauto自体には標準搭載されておらず、呼び出し側で例外処理によるリトライロジックを自作する必要がある。
- 逆に、pywinautoには必要だがPAD側のセレクタ情報には存在しない(=変換時に補完が必要な)もの: `backend`(`"uia"`か`"win32"`かの選択。PADはこの区別をユーザーに見せない)、`top_level_only`/`visible_only`/`enabled_only`/`active_only`といった検索スコープ制御フラグ、`handle`(Win32ウィンドウハンドル。PADのセレクタには存在しない概念)。

### Gaps
- PADの内部セレクタXML/JSON表現(フローのソースファイル内でセレクタがどうシリアライズされているか)を直接確認した一次資料は見つからなかった。属性名の正式な一覧(`Id`, `ClassName`, `ControlType`等をPADが実際にどう命名しているか)は実機でのセレクタテキストエディタの確認、またはPADのフローJSON/XAMLのエクスポートを直接調査する必要がある。

---

## セレクタ変換時によくある落とし穴(動的に変わるAutomationId、インデックスベースの指定の不安定性、マルチモニタ環境での座標ズレ、要素が仮想化されている場合の挙動の違い、.NET/WPF/Win32/Chromiumアプリ間でのバックエンド差異等)は何か

### Takeaway
UIAの`AutomationId`は仕様上「安定性の保証がない」プロパティであり、アプリのビルドやバージョンが変わると変化しうる。インデックスベースの指定(`ctrl_index`/`found_index`)はUI要素の並び順やタイミングに依存して不安定になりやすい。マルチモニタ環境ではDPIスケーリングが異なるモニタ間で座標がずれる既知の不具合がpywinautoに報告されている。仮想化リストでは画面に表示されていない行がUIAツリーに存在しないため、通常の検索では見つからず、`ItemContainer`/`VirtualizedItem`パターンかスクロールによる実体化が必要になる。ChromiumベースのブラウザはChrome 138以降ネイティブUIAをデフォルトで有効化したため、以前は存在したMSAAエミュレーション層経由の遅延・信頼性問題が改善されている(=バックエンド差異は時間軸でも変化する)。

### Cited Findings
- 「While support of an AutomationId is always recommended for better testability, this property is not mandatory... An AutomationId is not necessarily guaranteed to be stable across different releases or builds of an application... The value should be unique among sibling elements but not necessarily unique across the entire desktop.」— [AutomationElement.AutomationIdProperty (Microsoft)](https://msdn.microsoft.com/en-us/library/ms598108)
- `found_index`はプロパティが同一の複数要素を区別するための追加キーとして使われる(=並び順が変わるとインデックスが指す要素も変わりうる)。— [pywinauto関連StackOverflow要約](https://kiwix.lema.org/stackoverflow.com_en_all_2023-11/questions/70965104/how-to-set-focus-on-child-window-with-the-same-name)
- Windowsのディスプレイスケーリングが100%でない場合、pywinauto(win32バックエンド)でツリービュー項目のクリック位置がずれるという既知の不具合報告があり、APIから得る座標と実際の表示座標がスケール比率分ずれることが指摘されている。— [Lightrunミラー(pywinauto GitHub issue)](https://lightrun.com/answers/pywinauto-pywinauto-target-position-is-wrong-for-_perform_click-in-some-cases)
- マルチモニタでDPI設定が異なる場合、Per-Monitor DPI Awarenessの仕組み上、あるモニタで記録した座標が別モニタでは異なる位置を指してしまう(AutoHotkeyフォーラムの一般的な解説。pywinauto固有の確認ではない)。— [AutoHotkeyフォーラム](https://www.autohotkey.com/boards/viewtopic.php?p=537121)
- UI Automationの仮想化項目については「リストの要素がまだUIAツリー上に実体化されていない(virtualized)場合、名前での検索が失敗する。推奨される対処法はコンテナの`ItemContainer`パターンで項目を探し、`VirtualizedItem`パターンで実体化すること」。— [How to Retrieve a Virtualized Item (Microsoft)](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-howto-retrieve-virtualized-item)
- Zoomの参加者リストを例に、pywinautoで可視行のみしか取得できない実例が報告され、`VirtualizedItem`パターンを試す旨のpywinauto GitHub issue #985への言及がある(名前が既知の項目へスクロールする用途には有効だが、全項目の列挙には不向きという指摘つき)。— [StackOverflow(Zoom参加者リスト)](https://kiwix.lema.org/stackoverflow.com_en_all_2023-11/questions/67462157/pywinauto-view-list-items-that-aren-t-visible-on-screen)
- pywinautoは要素が見つからない場合に`ElementNotFoundError`を発生させ、`find_elements`は該当なしの場合に空リストを返す(仮想化による「未実体化」と「本当に存在しない」を区別できない)。— [pywinauto.findwindows docs](https://pywinauto.readthedocs.io/en/latest/code/pywinauto.findwindows.html)
- Chrome 138以降、Windows上のChromiumベースブラウザはネイティブUI Automationをデフォルトで有効化。それ以前はUIAリクエストがMSAAデータへ変換するWindowsのエミュレーション層を経由しており、速度と信頼性が低かった。— [Chrome Developers Blog: Native UI Automation for Windows in Chromium](https://developer.chrome.com/blog/windows-uia-support-update)
- 2020年の報告ではMS Edge Canaryのアドレスバーに対するUIA検索(pywinauto)がタイムアウトしたが、同様の手法はChromeでは動作した(ネイティブUIA導入前の挙動であり、現在は改善されている可能性がある)。— [StackOverflow(Edge Canaryアドレスバー)](https://kiwix.lema.org/stackoverflow.com_en_all_2023-11/questions/63760234/pywinauto-get-url-from-ms-edge-canary-address-bar)
- Power Automate公式ドキュメントは、Electronベースアプリや「カスタムレンダリングされたコントロール」を標準UIAセレクタで識別できない場合にUIA3 Rawモードへの切り替えを推奨している(=PAD自身もElectron/カスタムUIの難しさを公式に認識している)。— [Automate using UI elements](https://learn.microsoft.com/en-us/power-automate/desktop-flows/ui-elements)
- pywinautoの`win32`バックエンドと`uia`バックエンドは同一アプリでも異なる階層を見せる、とGetting Startedガイドが明記。— [pywinauto Getting Started Guide](https://pywinauto.readthedocs.io/en/latest/getting_started.html)
- `uia`バックエンドはWindowsハンドルを持たない要素があり、`win32`バックエンドからは見えない。— [pywinauto HowTo doc](https://github.com/vasily-v-ryabov/pywinauto/blob/master/docs/HowTo.txt)

### Inferences
- PADで記録した`AutomationId`ベースのセレクタをpywinautoの`auto_id`に1:1変換しても、アプリの別バージョン・別ビルドでは`AutomationId`自体がUIA仕様上不安定なため、変換後のスクリプトが長期的に壊れるリスクはPAD側・pywinauto側で共通して存在する。
- PAD/pywinautoのいずれでも「インデックスベース」(PADの階層内での暗黙の順序、pywinautoの`ctrl_index`/`found_index`)は、UIの再描画・項目の追加削除・ロード順の揺れに弱く、`AutomationId`や一意な`Name`が使える場合はそちらを優先すべきという運用上の結論になる。
- Electron/Chromiumアプリについては、PAD側は「UIA3 Rawモードへの切替」という回避策をユーザーに提供しているのに対し、pywinautoには同等の「生ツリーモード」切替機能は標準docsで確認できず、Chromiumの「ネイティブUIA化」(Chrome 138以降)という外部要因の改善に依存する部分が大きい。この非対称性は変換時の重要な制約になる。

### Gaps
- PAD自身がマルチモニタ/DPI問題にどう対処しているか(座標ベースのアクション使用時にDPI補正を自動で行うか等)を明言した一次資料は見つからなかった。
- 仮想化リストに対するPAD側の挙動(スクロールして実体化する機能の有無)を明記した一次資料も見つからなかった。

---

## pywinautoがUIA要素の取得に失敗しやすいアプリケーション種別(Electronアプリ、ブラウザ内要素、仮想化リストボックス等)について何か知見はあるか

### Takeaway
失敗しやすい代表例として、(1) 仮想化リスト/ツリー(スクロール外の行がUIAツリーに存在しない)、(2) Electron/CEF/WebView2ベースのアプリ(HTML層がネイティブUIAツリーの背後に隠れており、ブラウザ自動化(CDP/Playwright等)の方が適切)、(3) Qt5アプリ(環境変数`QT_ACCESSIBILITY`を設定しないとUIAツリーが露出しない)、(4) ChromiumベースブラウザのUIA(Chrome 138より前はMSAAエミュレーション層経由で低速・不安定だったが、現在はネイティブUIA化で改善)が挙げられる。

### Cited Findings
- Electron/CEF/WebView2アプリは「HTMLレイヤーがUIAの背後に隠れているため、ブラウザオートメーション(CDP等)で自動化する必要がある」という趣旨の実践的ガイドが存在する(Windows Desktop E2Eテストに関する第三者スキルドキュメント)。— [windows-desktop-e2e skill](https://www.skills.sh/eugene-ee/affaan-m-ecc/windows-desktop-e2e) / [同ミラー](https://cdn.jsdelivr.net/npm/compact-agent@1.35.0/resources/ecc/skills/windows-desktop-e2e/SKILL.md)
- 同資料は、Qt 5.xアプリはUIAが機能する前に環境変数`QT_ACCESSIBILITY`の設定が必要、と指摘している。— [windows-desktop-e2e skill](https://www.skills.sh/eugene-ee/affaan-m-ecc/windows-desktop-e2e)
- 仮想化されたリスト項目(画面外の行)はUIAツリー上に実体化されておらず、名前ベースの検索が失敗する。Microsoft公式には`ItemContainer`/`VirtualizedItem`パターンでの対処が明記されている。— [How to Retrieve a Virtualized Item (Microsoft)](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-howto-retrieve-virtualized-item)
- Zoom参加者リストの例では、pywinautoは可視行のみ取得でき、スクロールするか`VirtualizedItem`パターン(pywinauto issue #985)を使う必要があった。— [StackOverflow要約](https://kiwix.lema.org/stackoverflow.com_en_all_2023-11/questions/67462157/pywinauto-view-list-items-that-aren-t-visible-on-screen)
- Chromiumは「Chrome 138からWindows上でネイティブUI Automationをデフォルト有効化。それ以前はUIAリクエストがMSAAデータへ変換するエミュレーション層を経由しており、速度と信頼性の問題があった」。— [Chrome Developers Blog](https://developer.chrome.com/blog/windows-uia-support-update)
- 2020年時点でpywinautoによるMS Edge Canaryのアドレスバー検索がタイムアウトした実例があり(当時のUIAエミュレーション層の問題と符合)、同じ手法はChromeでは機能した。— [StackOverflow](https://kiwix.lema.org/stackoverflow.com_en_all_2023-11/questions/63760234/pywinauto-get-url-from-ms-edge-canary-address-bar)
- Power Automate公式ドキュメントも、Electronベースアプリやカスタムレンダリングコントロールを標準UIAで識別できない場合の救済策としてUIA3 Rawモードを明示的に案内している(=PAD側もElectronをUIA取得困難なアプリ種別として認識している一次情報)。— [Automate using UI elements](https://learn.microsoft.com/en-us/power-automate/desktop-flows/ui-elements)

### Inferences
- PADとpywinautoは、Electronアプリや仮想化リストという「UIA取得困難なアプリ種別」についてほぼ同じ弱点を共有している。したがってPAD→pywinauto変換において「PADでUIA3 Rawを使わざるを得なかった要素」は、pywinautoへ変換してもUIAバックエンドでは同様に取得困難であり、ブラウザ自動化系ライブラリ(Playwright等)や座標/画像ベースのフォールバックが必要になる可能性が高い。

### Gaps
- pywinauto自身がElectronアプリに対して失敗する具体的なエラーメッセージやGitHub Issue番号を直接特定した一次資料は見つからなかった(検索では「Electron」と明示したpywinauto固有の報告は得られず、一般的なWindows UIAテスト知見からの類推にとどまる)。
- Qt5の`QT_ACCESSIBILITY`要件がpywinauto公式ドキュメントで明記されているかどうかは未確認(第三者資料のみ)。
