# PAD アクション体系 → pywinauto / pyautogui API 対応表

## PAD の「UI オートメーション」カテゴリの主要アクション一覧とその内容は?

### Takeaway
Microsoft Learn の UI automation actions reference (en-us, 最終更新 2024-10-14 / ページ更新 2025-04-28) には、ウィンドウ操作系(Get window, Focus window, Set window state, Set window visibility, Move window, Resize window, Close window, If window, Wait for window)と要素操作系(Get details of window, Get details of a UI element in window, Click UI element in window, Populate text field in window, Press button in window, Select radio button in window, Set checkbox state in window, Set drop-down list value in window, Select menu option in window, Select tab in window, Drag and drop UI element in window, Expand/collapse tree node in window, Hover mouse over UI element in window 等)が同じページにまとめて掲載されている。つまり「ウィンドウ」操作は独立したアクショングループではなく、UI オートメーションカテゴリの一部として提供されている。

### Cited Findings
- UI オートメーションアクションは「物理モード」と「シミュレートモード」の2種類の実行方式を持つ。物理モードはマウス/キーボードを実際に制御して操作し、シミュレートモードはプログラム的に(マウス/キーボードを乗っ取らず、対象画面をフォアグラウンドにしなくても)動作する — [UI automation actions reference](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/uiautomation)
- すべての UI 要素はセレクターで識別され、セレクターは `>` 記法で親子階層を表す。アプリケーションウィンドウのセレクターは常に `:desktop` をルート要素とする — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/uiautomation)
- 代表的なアクションと主要パラメータ(抜粋):
  - **Get details of window**: Window(UI element), Window property(Get window title / Get window text / Get window location and size / Get process name), Bring to front(bool) → 戻り値 WindowProperty
  - **Get details of a UI element in window**: UI element, Attribute name(既定 "Own Text") → AttributeValue
  - **Get selected checkboxes in window** / **Get selected radio button in window**: チェックボックス/ラジオボタンの状態・選択名を取得
  - **Extract data from window** / **Extract data from table**: 画面またはテーブルからデータを抽出し、Excel またぎ変数に格納
  - **Take screenshot of UI element**: UI element, Save mode(Clipboard/File), File format(BMP/EMF/EXIF/GIF/JPG/PNG/TIFF/WMF)
  - **Focus text field in window** / **Populate text field in window**: テキストボックスにフォーカス/入力。Populate は Simulate action(bool), If field isn't empty(Replace/Append), Click before populating(Left-click/Double-click/No) を持つ
  - **Press button in window**: ボタン押下
  - **Select radio button in window** / **Set checkbox state in window** / **Set drop-down list value in window** / **Select tab in window** / **Select menu option in window**: 各種コントロールの選択・状態設定
  - **Click UI element in window**: UI element, Click type(Left/Right/Double/Middle-click, Left/Right button down/up), Simulate action(bool), Mouse position relative to UI element(9方位), Offset X/Y
  - **Drag and drop UI element in window**: ドラッグ元/ドロップ先 UI element, Click type(Left/Right-click), オフセット・相対位置パラメータ
  - **Expand/collapse tree node in window**: ツリーノードの展開/折りたたみ、Folders path(正規表現対応)
  - **Hover mouse over UI element in window**: UI element のみ
  - すべて [UI automation actions reference](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/uiautomation)
- ウィンドウ関連アクション(同ページに同居): **Get window**(Specific window/Foreground window, Bring window to front, Fail if window isn't found, Timeout → WindowTitle, AutomationWindow)、**Focus window**(By window UI element/By window instance・handle/By title and・or class)、**Set window state**(Restored/Maximized/Minimized)、**Set window visibility**(Visible/Hidden)、**Move window**(Position X/Y)、**Resize window**(Width/Height)、**Close window**、**If window**(Is open/Isn't open/Is focused/Isn't focused)、**Wait for window**(Open/Close/Become focused/Lose focus, Focus window after it opens) — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/uiautomation)
- 条件・待機系: **If window contains**(Contains/Doesn't contain UI element・text、要素の Enabled/Disabled 状態チェック)、**Wait for window content**(同条件が現れる/消えるまで待機)、**If image** / **Wait for image**(画面上の画像の有無・出現/消失を待機。X1/Y1/X2/Y2 でサブ領域、Tolerance で画像差異許容度を指定) — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/uiautomation)
- シミュレートモードには技術別の既知の制限がある(例: WPF の Textbox/Togglebutton/Richtextbox/Listitem/Griditem/Combobox では Click UI element / Press button のシミュレートが機能しない等) — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/uiautomation)
- UI オートメーションアクション(Use desktop を除く)は、対象アプリが昇格権限で動作している場合、Power Automate 自体も管理者として実行する必要がある — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/uiautomation)

### Inferences
- PAD の「物理モード」は pywinauto の `click_input()` / pyautogui のマウス・キーボード物理操作に相当し、「シミュレートモード」は pywinauto の UIA パターン経由の `invoke()` / `click()`(メッセージ送信、カーソルを動かさない)に相当すると考えられる。
- Get details / Get selected checkboxes / Get selected radio button は pywinauto の `wrapper.window_text()`, `wrapper.rectangle()`, `wrapper.is_checked()`, `wrapper.get_properties()` 等のプロパティ取得 API に対応する候補となる。
- Extract data from table は pywinauto の `ListViewWrapper.get_item()` / `GridWrapper` 系 API、または `uiautomation`/`comtypes` 経由でのテーブル全走査に相当すると考えられる。

### Gaps
- 各アクションの詳細な pywinauto 側 1:1 対応(特に Set drop-down list value, Expand/collapse tree node, Drag and drop)について、pywinauto 公式ドキュメントの `ComboBoxWrapper`, `TreeViewWrapper`, `drag_mouse_input()` の具体的な引数は未調査(ツール呼び出し予算の制約で調査しきれなかった)。報告書作成時に pywinauto controls モジュールのリファレンス(`pywinauto.controls.common_controls`)を追加確認することを推奨。

## 「マウスとキーボード」カテゴリのアクション一覧と pyautogui API の対応は?

### Takeaway
Mouse and keyboard actions reference(最終更新 2022-11-23)には Block Input, Get mouse position, Move mouse, Move mouse to image, Move mouse to text on screen (OCR), Send mouse click, Send keys, Press/release key, Set key state, Wait for mouse, Get keyboard identifier, Wait for shortcut key の12アクションがあり、座標指定のクリック・移動・キー送信は pyautogui の `click()`, `moveTo()`, `press()`, `keyDown()`/`keyUp()`, `hotkey()` に概ね1対1で対応できる。一方、画像/OCR ベースのマウス移動(Move mouse to image / Move mouse to text (OCR))や Block Input、Wait for mouse(カーソル形状待機)、Wait for shortcut key のようなグローバルフック系アクションは pyautogui 単体では代替できず、`pyautogui.locateOnScreen()` + 画像認識、または pywinauto/pytesseract/ctypes 等の追加実装が必要になる。

### Cited Findings
- **Send keys**: Text to send, Delay between keystrokes(既定10ms), Send Text as hardware keys(bool)。特殊キーは `{}` 記法(例 `{Enter}`, `{Tab}`)、モディファイアキーも `{}` で挟む。VK コードに対応するキー一覧(Buttons, Keyboard Control, Function keys 等)が定義されている — [Mouse and keyboard actions reference](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/mouseandkeyboard)
- **Move mouse**: Position X/Y, Relative to(Screen/Active window/Current mouse position), Move mouse from previous position(Instant/With animation 低速・通常・高速) — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/mouseandkeyboard)
- **Send mouse click**: Mouse event to send(Left/Right/Double/Middle click, Left/Right button down/up), Wait(ms単位の事前待機), Move mouse(bool), X/Y, Relative to, Mouse movement style — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/mouseandkeyboard)
- **Get mouse position**: Relative to(Screen/Foreground window) → MousePosX, MousePosY — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/mouseandkeyboard)
- **Move mouse to image** / **Move mouse to text on screen (OCR)**: 画面上またはフォアグラウンドウィンドウ上で画像/テキスト(OCR、Tesseract または Windows OCR エンジン)を検索し、その位置へマウスを移動、オプションでクリックまで実行。Tolerance(既定10)で画像差異許容度、Search mode でサブ領域指定が可能 — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/mouseandkeyboard)
- **Block Input**: マウス/キーボード入力をブロックし、フローが干渉なく操作できるようにする。管理者権限が必要 — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/mouseandkeyboard)
- **Press/release key**: Control/Alt/Shift/Win の押下・解放(bool指定) — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/mouseandkeyboard)
- **Set key state**: Caps Lock/Num Lock/Scroll Lock の On/Off設定 — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/mouseandkeyboard)
- **Wait for mouse**: マウスポインタが特定の形状(Arrow/App starting/Cross/Hand/Help/IBeam/Wait cursor)に Become/Become not するまで待機 — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/mouseandkeyboard)
- **Wait for shortcut key**: 指定ショートカットキーが押されるまでフローを一時停止。Continue flow run on timeout(bool), Continue after(秒) → IndexOfShortcutKeyPressed — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/mouseandkeyboard)
- **Get keyboard identifier**: レジストリからアクティブなキーボード識別子(KeyboardLayoutId)を取得 — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/mouseandkeyboard)
- pyautogui: `moveTo(x, y, duration=num_seconds)` は指定秒数かけてカーソルを移動。`click()` は現在位置で左クリック、`x, y, clicks, interval, button` 引数で挙動変更可能。`hotkey('ctrl', 'c')` のようにキー同時押し。キー入力には `press`, `keyDown`, `keyUp`、キー保持には `hold()` コンテキストマネージャ。マウスが画面四隅に来ると `FailSafeException` が発生するフェイルセーフ機構があり、`pyautogui.PAUSE`(既定0.1秒)で各呼び出し後の待機を制御 — [PyAutoGUI docs](https://pyautogui.readthedocs.io/)

### 対応表(抜粋)
| PAD アクション | 主要パラメータ | pyautogui 相当 |
| --- | --- | --- |
| Move mouse | Position X/Y, Relative to, 移動スタイル | `pyautogui.moveTo(x, y, duration=...)` / `pyautogui.moveRel(dx, dy)` |
| Send mouse click | Mouse event, X/Y, Move mouse | `pyautogui.click(x, y, button='left')` / `pyautogui.doubleClick()` / `pyautogui.mouseDown()` / `mouseUp()` |
| Get mouse position | Relative to | `pyautogui.position()` |
| Send keys | Text to send, 特殊キー `{}` 記法 | `pyautogui.typewrite(text, interval=...)` / `pyautogui.press('enter')` |
| Press/release key | Control/Alt/Shift/Win | `pyautogui.keyDown('ctrl')` ... `pyautogui.keyUp('ctrl')` / `pyautogui.hotkey('ctrl','c')` |
| Move mouse to image | 画像リスト、Tolerance、クリック | `pyautogui.locateCenterOnScreen(image, confidence=...)` → `pyautogui.click(x, y)` |
| Wait for image | 画像出現/消失待機 | `pyautogui.locateOnScreen()` をポーリングするループ実装(pyautogui自体に待機専用APIはない) |
| Set key state (Caps/Num/Scroll Lock) | On/Off | pyautogui に直接対応APIなし。`ctypes`/`keyboard`ライブラリで `VK_CAPITAL` 等をトグル送信する実装が必要 |
| Block Input | ブロック/解除 | pyautogui に相当APIなし。Windows の `BlockInput()` API を `ctypes.windll.user32.BlockInput()` で直接呼ぶ必要 |

### Inferences
- 座標ベースの基本操作(移動・クリック・キー送信)は pyautogui へほぼそのまま移植可能だが、PAD の「Relative to: Active window」「Foreground window」指定は pyautogui には無い概念のため、別途ウィンドウ座標取得(pywinauto の `rectangle()` や `win32gui.GetWindowRect()`)と組み合わせてオフセット計算する実装が必要になる。
- PAD の Wait for image / Move mouse to image のようなポーリング付き待機は、pyautogui の `locateOnScreen` を `while` ループと `time.sleep` + タイムアウト判定で囲むラッパー関数を自作するのが実務上の定石になると考えられる。

### Gaps
- PAD の「Send Text as hardware keys」(実キーストロークのエミュレート)に相当する pyautogui 側の厳密な動作差異(VK_PACKET 送信 vs. 物理キーボードスキャンコード送信)は未確認。
- Wait for shortcut key(グローバルホットキーフック)に相当する pyautogui ネイティブAPIは存在しないことは確認できたが、代替実装(`keyboard` ライブラリの `keyboard.wait()` など)は PAD ドキュメント側では触れられておらず、pyautogui ドキュメント単独では裏取りできなかった。

## 「ウィンドウ」カテゴリのアクションと pywinauto の Application/WindowSpecification API の対応は?

### Takeaway
PAD の「ウィンドウ」操作(Get window, Focus window, Set window state, Set window visibility, Move window, Resize window, Close window, If window, Wait for window)は UI automation actions reference に統合掲載されており、いずれも「Find window mode: By window UI element / By window instance・handle / By title and・or class」という共通の検索方式を持つ。これは pywinauto の `Application.connect(handle=...)` や `Desktop(backend=...).window(title=..., class_name=...)` によるウィンドウ特定、および取得後の `WindowSpecification`/ラッパーオブジェクトに対するメソッド呼び出し(`.maximize()`, `.minimize()`, `.close()`, `.move_window()`, `.wait()`)に対応する。

### Cited Findings
- **Get window**: Specific window(セレクター)/Foreground window の2モード、Bring window to front(bool)、Fail if window isn't found(bool)、Timeout(秒) → WindowTitle, AutomationWindow(Window instance) — [UI automation actions reference](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/uiautomation)
- **Focus window**: By window UI element / By window instance・handle / By title and・or class(ワイルドカード `?`, `*` 使用可) — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/uiautomation)
- **Set window state**: Window state(Restored/Maximized/Minimized) — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/uiautomation)
- **Set window visibility**: Visibility(Visible/Hidden) — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/uiautomation)
- **Move window**: Position X/Y — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/uiautomation)
- **Resize window**: Width/Height(ピクセル) — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/uiautomation)
- **Close window**: ウィンドウを閉じる。見つからない場合やノンインタラクティブモードでの失敗例外あり — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/uiautomation)
- **If window** / **Wait for window**: Is open/Isn't open/Is focused/Isn't focused の分岐、および Open/Close/Become focused/Lose focus を待つブロッキング待機(Focus window after it opens オプション付き) — [同上](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/uiautomation)
- 第三者情報として、ウィンドウが確実に閉じない場合は Close window ではなく「Terminate process」でプロセスID指定終了する方法が Microsoft ドキュメントで案内されている(プロセス全体を終了するため、ウィンドウ単位の終了ではない点に注意) — [Close window by process id](https://learn.microsoft.com/en-us/power-automate/desktop-flows/how-to/close-window-process-id)
- pywinauto: `Application.connect()` は実行中プロセスへのアタッチで、プロセスID・ウィンドウハンドル・パス等で接続できる。`top_window()` はアプリの最前面ウィンドウを `WindowSpecification` として返し、それが以降の `maximize`/`minimize`/`close` 呼び出しの起点となる — [pywinauto.application module docs](https://pywinauto.readthedocs.io/en/atspi/code/pywinauto.base_application.html)
- pywinauto の `HwndWrapper`(Win32バックエンド)は `maximize()`(ウィンドウを最大化)、`minimize()`、`close(wait_time=0)`(ウィンドウを閉じる)、`restore()` を提供。UIA バックエンドの `UIAWrapper` も同名の `maximize()`/`minimize()`/`close()` を持つが、対象コントロールが Window パターンをサポートしない場合(メニュー、ツールチップ等)は "Esc" キー送信にフォールバックするよう注記されている — [pywinauto HwndWrapper](https://pywinauto-fork.readthedocs.io/en/latest/code/pywinauto.controls.hwndwrapper.html) / [pywinauto UIAWrapper](https://pywinauto-fork.readthedocs.io/en/uia/code/pywinauto.controls.uiawrapper.html)
- `wait_cpu_usage_lower(threshold=2.5, timeout=None, usage_interval=None)` はプロセス全体のCPU使用率が閾値を下回るまで待つ `Application` メソッドで、ウィンドウ/要素単位では使えない(GUIが応答する間にバックグラウンド読み込みを待つ用途) — [pywinauto wait_long_operations](https://airelil-pywinauto.readthedocs.io/en/atspi/wait_long_operations.html)

### 対応表(抜粋)
| PAD アクション | pywinauto 相当 |
| --- | --- |
| Get window(Specific/Foreground, Timeout) | `Desktop(backend="uia").window(title=..., class_name=...)` または `Application.connect(...).top_window()`、`wait("exists", timeout=...)` |
| Focus window | `win.set_focus()` |
| Set window state → Maximized/Minimized/Restored | `win.maximize()` / `win.minimize()` / `win.restore()` |
| Set window visibility | `win32gui.ShowWindow(hwnd, SW_HIDE/SW_SHOW)`(pywinautoに直接のHidden/Visible切替APIは確認できず、`win.wrapper_object().set_focus()`経由かwin32gui併用が実務的) |
| Move window | `win.move_window(x=..., y=...)` |
| Resize window | `win.move_window(width=..., height=...)` |
| Close window | `win.close()` |
| If window(Is open/Is focused) | `win.exists()` / `win.is_active()` |
| Wait for window(Open/Close/Become focused/Lose focus) | `win.wait("exists")` / `win.wait_not("exists")` / `win.wait("active")` / `win.wait_not("active")` |

### Inferences
- PAD の「Find window mode: By title and/or class(ワイルドカード対応)」は pywinauto の `title_re=` (正規表現)や `best_match` ロジックに相当し、「By window instance/handle」は `Application.connect(handle=hwnd)` や `Desktop().window(handle=hwnd)` に相当すると考えられる。
- 「Set window visibility」に関する pywinauto の明確な単独APIはドキュメント上確認できず、`pywin32`(`win32gui.ShowWindow`)を併用する実装が一般的と推測される(要追加裏取り)。

### Gaps
- pywinauto 側で「Set window visibility (Hidden/Visible)」に直接対応する公式メソッド名は確認できなかった。`pywin32` 併用が実務解である可能性が高いが、pywinauto 公式ドキュメントからの直接引用では裏取りできていない。
- 「Move window」「Resize window」を一体化した pywinauto の `move_window(x, y, width, height)` のフルシグネチャ(省略時の挙動)は未確認。

## PAD の「待機」系アクションは pywinauto の wait('exists') や timings モジュールとどう対応するか?

### Takeaway
PAD には「Wait for window」「Wait for window content」「Wait for image」「Wait for mouse」「Wait for shortcut key」という複数の待機アクションがあり、いずれも「条件が満たされるまでポーリングし、タイムアウトで例外または分岐」という共通パターンを持つ。これは pywinauto の `WindowSpecification.wait(state, timeout=None, retry_interval=None)` / `wait_not()` と、`pywinauto.timings` モジュールのグローバルなポーリング間隔・タイムアウト設定の組み合わせに対応する。

### Cited Findings
- pywinauto の `wait()` は `exists`, `visible`, `enabled`, `ready`, `active` などの状態名を受け取る。例: ダイアログが exists かつ ready かつ enabled かつ visible になるまで待つ。`wait_not()` はその逆(状態が解除されるまで待つ) — [pywinauto Waiting for Long Operations](https://pywinauto-fork.readthedocs.io/en/stable/wait_long_operations.html)
- `wait()` が例外なく返れば、対象コントロールが存在し、かつ(指定した状態が)visible/enabled/active であることが保証される — [同上]
- 待機失敗時は `pywinauto.timings.TimeoutError` が発生する。`timeout` と `retry_interval` はオプション引数で、既定値は `Timings.window_find_timeout` / `Timings.window_find_retry` に連動する — [同上]
- `timings` モジュールは `Timings.fast()`, `Timings.defaults()`, `Timings.slow()` のグローバルプリセットを提供し、すべてのタイミングを一括でデフォルト・倍速・半速に設定できる — [同上]
- より低レベルな `timings.wait_until` / `timings.wait_until_passes` は任意のPythonコードに対する待機ロジックを提供し、デコレータ `always_wait_until()` / `always_wait_until_passes()` も存在する — [同上]
- PAD 側: **Wait for window content**(Contains/Doesn't contain UI element・text、要素のEnabled/Disabled状態チェックを待つ)、**Wait for image**(画像のAppear/Disappearを待ち、Fail with timeout error(bool)で無限待機かタイムアウト失敗かを選択可能)、**Wait for mouse**(カーソル形状の変化を待つ)、**Wait for shortcut key**(ショートカットキー押下を待ち、Continue flow run on timeoutでタイムアウト時継続可否を指定) — [UI automation actions reference](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/uiautomation) / [Mouse and keyboard actions reference](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/mouseandkeyboard)
- `wait_cpu_usage_lower` は `Application` レベル(プロセス全体)専用の待機で、個々のウィンドウ/要素には使えない — [pywinauto wait_long_operations](https://airelil-pywinauto.readthedocs.io/en/atspi/wait_long_operations.html)

### 対応表(抜粋)
| PAD アクション | pywinauto / timings 相当 |
| --- | --- |
| Wait for window(Open) | `win.wait("exists")` |
| Wait for window(Close) | `win.wait_not("exists")` |
| Wait for window(Become focused) | `win.wait("active")` |
| Wait for window(Lose focus) | `win.wait_not("active")` |
| Wait for window content(Contains UI element) | 対象要素の `WindowSpecification.wait("exists")`、またはカスタムループ + `timings.wait_until(timeout, retry_interval, func)` |
| Wait for image / Wait for mouse / Wait for shortcut key | pywinauto に直接対応APIなし。pyautogui の `locateOnScreen` や `ctypes` 併用 + `pywinauto.timings.wait_until_passes` 相当の自前リトライループが必要 |
| グローバルなタイムアウト・リトライ間隔調整 | `pywinauto.timings.Timings.fast()/defaults()/slow()` |

### Inferences
- PAD の各 Wait アクションに共通する「ポーリング+タイムアウト+(任意で)タイムアウト時続行」という構造は、Python実装では `pywinauto.timings.wait_until_passes(timeout, retry_interval, func, exceptions=...)` のような汎用リトライユーティリティに一本化してラップするのが自然な設計になると考えられる。
- 画像・OCR・マウスカーソル形状待機のように pywinauto の対象外(要素ツリーを持たない)な待機は、pyautoguiや画像認識ライブラリ側で同様の「ポーリングループ + タイムアウト」パターンを自作する必要がある。

### Gaps
- `Timings.window_find_timeout` と `window_find_retry` の具体的な既定値(5秒、0.09秒など)は一次情報(公式readthedocs)ではなく第三者チュートリアル経由の情報であり、インストールされているバージョンの `timings.py` で要検証、として報告する。

## PAD特有の機能(変数データ型、サブフロー呼び出し、On Error/Try-Catch)はPythonでどう実装するのが一般的か?

### Takeaway
PAD の変数データ型(Text, Numeric, Boolean, List, Datatable, Datarow, Custom object)はPythonの標準型・標準ライブラリ(str, int/float, bool, list, pandas.DataFrame または list[dict], dict等)に自然にマッピングできる。サブフロー呼び出しはPythonの関数呼び出しに、On block errorによるブロック単位のエラーハンドリング・Throw custom error・Get last error は Python の try/except, raise, カスタム例外クラスにそれぞれ対応する。

### Cited Findings
- PAD の変数データ型: Text(任意の文字列)、Numeric(数値計算に使える唯一の型)、Boolean(True/False)、List(1次元配列相当のコレクション)、Datatable(行と列を持つ2次元配列相当)、Datarow(For Eachループ時にDatatableから生成される1行)、Custom object(JSONに変換しやすいキー・値ペア)、List of PDF table info(「Extract tables from PDF」専用) — [Variable data types](https://learn.microsoft.com/en-us/power-automate/desktop-flows/variable-data-types)
- 2022年の機能追加により、サブフロー(デスクトップフロー)はText/Number/Boolean/Custom Object/List/Data table型の入力・出力変数を受け渡しできるようになった(それ以前は基本的な文字列のみ) — [Use more data types for input and output variables](https://docs.microsoft.com/power-platform-release-plan/2022wave1/power-automate/more-data-types-input-output-variables)(アーカイブページのため最新ドキュメントでの再確認推奨)
- デスクトップフローは既定ではエラー発生時に実行を停止する。これを変更するには明示的にエラー処理を設定する必要がある — [Handle errors in desktop flows](https://learn.microsoft.com/power-automate/desktop-flows/errors)
- **On block error** アクションは、個別アクションごとに設定する代わりに、ブロック内の複数アクションに共通のエラー処理方針を一括設定できる。ブロックの再試行(retry)はブロックの先頭からやり直し、すべてのブロック再試行が失敗した場合にブロックの「Exception handling mode」が適用される。アクション単位のエラー処理・リトライはブロックのリトライより優先される — [Second level of error handling](https://docs.microsoft.com/en-us/power-platform-release-plan/2020wave2/power-automate/second-level-error-handling-power-automate-desktop)
- 既定の Exception handling mode は、エラーが発生したアクションと実行中のアクションを無視し、ブロックの終端まで進む動作 — [Error (Exception) handling (Power Automate Desktop)](https://www.samurai-emblem.com/2023/02/06/power-automate-desktop-exception-catch/)(第三者情報)
- **Throw custom error** アクションは名前付きのカスタムエラーを発生させ、On block error 側で「+ Custom error」ボタンにより追加したエラー名とマッチする最初のルールが上から順に評価・実行される。マッチしなければ既定の "All errors" ルールが適用される — [同上](https://www.samurai-emblem.com/2023/02/06/power-automate-desktop-exception-catch/)
- Main フロー全体を On block error で包むことで、デスクトップフロー全体の例外ハンドラ(サブフローへのルーティング含む)を構築できる、という実践例がコミュニティ記事にある — [Create an exception handler for the entire desktop flow](https://werkbook.notion.site/Create-an-exception-handler-for-the-entire-desktop-flow-9c4e04794e854f6fac9fefdf9d9fa068)(第三者/コミュニティ記事)
- 直前のエラー情報を後続アクションで使うには **Get last error** アクションを使う — [Second level of error handling](https://docs.microsoft.com/en-us/power-platform-release-plan/2020wave2/power-automate/second-level-error-handling-power-automate-desktop)

### 対応表(抜粋)
| PAD の概念 | Python実装の定石 |
| --- | --- |
| Text / Numeric / Boolean | `str` / `int`・`float` / `bool` |
| List | `list` |
| Datatable | `pandas.DataFrame`、または `list[dict]`(軽量な場合) |
| Datarow(For Each中の1行) | `DataFrame.itertuples()` または `for row in list_of_dict:` のループ変数 |
| Custom object | `dict`、またはJSON変換前提なら `dataclass` + `json.dumps/loads` |
| サブフロー呼び出し(Run subflow、入出力変数の型指定) | Python関数呼び出し(型ヒント付き関数 `def subflow(x: str, y: list) -> dict:`) |
| On block error(ブロック単位のエラー処理・リトライ) | `try: ... except Exception as e: ...` ブロック、リトライは `for attempt in range(n): try: ... except: continue else: break` のようなリトライループ、またはデコレータ(例: `tenacity` ライブラリの `@retry`) |
| Throw custom error | カスタム例外クラス(`class CustomPadError(Exception): ...`)を `raise CustomPadError("ErrorName")` |
| Exception handling mode(エラーを無視して次へ) | `except Exception: pass`(ただし実務上は握りすぎ注意、ログ出力推奨) |
| Get last error | Python標準では直前の例外は`sys.exc_info()`やexceptオブジェクト自体で保持するのが自然(グローバル変数での保持はPAD固有の制約を反映した設計) |

### Inferences
- PAD の「ブロック単位のOn block error + Exception handling mode + Throw custom error」という3層構造は、Pythonでは「`try/except` + カスタム例外の階層 + 必要ならリトライデコレータ」という一般的なエラーハンドリング設計パターンにそのまま写し込める。
- サブフロー入出力の型制約(Text/Number/Boolean/Custom Object/List/Data table のみ)は、Python関数の型ヒットよりも緩い制約であり、Python実装では型ヒントを使いつつもより自由な型(例えばNoneやTuple)を使える点が差異になる。

### Gaps
- 「Get last error」アクションの戻り値の正確なデータ構造(エラー名・メッセージ・発生アクション名などのフィールド一覧)は未調査。Microsoft公式の該当アクションリファレンスページ(Flow control actions reference 等)を別途確認する必要がある。
- `flowcontrol` アクションリファレンスページ自体(On block error, Throw custom error, Get last error, Run subflow の正式な入力パラメータ表)は検索結果にリンクは出たが実際にフェッチしておらず、一次ソースでの詳細確認は未完了(ツール呼び出し予算の制約)。報告書作成時に https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/flowcontrol の直接確認を推奨。

## 既にPAD→Python(pywinauto/pyautogui)のアクション対応表を作成している記事・ドキュメント・ライブラリはあるか?

### Takeaway
Web検索では、PADのアクションとpywinauto/pyautoguiを明示的に1対1で対応付けた記事・ライブラリ・変換ツールは見つからなかった。Power Automate と「Python RPA」を比較するのはレビューサイト(Gartner, G2, PeerSpot, Capterra)の製品比較記事のみで、これらは機能表ではなく満足度・価格帯の比較にとどまる。GitHub上にもPADフローファイルをPythonへ変換するツールや、PADアクション対応表を公開しているプロジェクトは見当たらなかった。

### Cited Findings
- Gartner/G2/PeerSpot/Capterra の比較ページは「Power Automate」と「Python RPA」という商用製品同士の評価・価格比較であり、PADの個別アクションとpywinauto/pyautoguiのAPIを対応付けるものではない。Gartnerでは Power Automate が4.4/5(270件)、Python RPAが4.3/5(7件)。PeerSpotではPower AutomateがRPA分野2位(123件・評価7.8)、Python RPAが23位(2件・評価8.6) — [Gartner比較](https://www.gartner.com/reviews/market/robotic-process-automation/compare/product/power-automate-vs-python-rpa1), [PeerSpot比較](https://www.peerspot.com/products/comparisons/microsoft-power-automate_vs_python-rpa)
- GitHub検索では、pywinauto・pyautoguiそれぞれの一般的なプロジェクト(pywinautoのトピックページ、AutoWinという個人開発の軽量ラッパーライブラリ)がヒットしたが、PAD由来のアクション対応表や変換ツールは確認できなかった — [pywinauto GitHub topic](https://www.github.com/topics/pywinauto), [AutoWin on PyPI](https://pypi.org/project/autowin/)
- サムライエンブレム(samurai-emblem.com)やchercher.techなど、PADの個別アクションを日本語/英語で解説するブログ記事群は多数存在するが、いずれもPAD単体の使い方解説であり、Pythonへの対応表ではない — [Mouse and Keyboard Actions in Power Automate Desktop](https://chercher.tech/power-automate-desktop/mouse-keyboard-actions-power-automate-desktop), [Mouse and Keyboard(Power Automate Desktop Action)](https://www.samurai-emblem.com/power-automate-desktop/power-automate-desktop-actions/power-automate-desktop-action-mouse-and-keyboard-summary/)

### Inferences
- PAD→pywinauto/pyautoguiの体系的な対応表は(今回調査した範囲では)オリジナルコンテンツが存在しないため、本調査で作成する対応表自体が新規性のある一次整理になると考えられる。

### Gaps
- 日本語圏のRPA技術ブログ(Qiita, Zenn等)でPADとPythonの機能比較を行った記事があるかどうかは、英語中心の検索では十分に探索できていない。追加で「Qiita Power Automate Desktop Python 比較」のような日本語クエリでの再検索を推奨(本調査のツール呼び出し予算の制約により未実施)。
