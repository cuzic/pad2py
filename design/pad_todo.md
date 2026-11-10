# PAD→Python変換: 残課題ToDo

このファイルはPAD(Power Automate Desktop)→Python変換トラックの残課題を追跡するためのもので、
UiPathトラック(`design/uipath_transpiler_roadmap.md`等)とは別管理。各項目は完了したら`[x]`に変更し、
関連コミット・知見番号を追記する。複数セッションが並行してこのリポジトリを編集するため、
チェックを入れる際は直前に`git pull`相当(fetch済みの最新状態)を確認してからにする。

- 判断基準(優先度ではなく「今すぐ着手できるか」の目印):
  - 🖥️ = PAD実機VM(`pad2py-pad-host`)でのRDP/WinRM操作が必要
  - 💻 = ローカル(パーサー/codegen/テスト)のみで完結、VM不要

## A. codegenの既知TODO(14/202分岐点、理由は特定済み——`uv run python3 -m dump_daemon.codegen_coverage`で随時再計測)

**2026-11-05確認済みの注記**: 14件のうち3件(`Variables.IncreaseVariable`/`DecreaseVariable`/
`Compression.UnzipFiles`)は、実機コードが本当に未結線なのではなく、カバレッジ測定に使っている
実機キャプチャフィクスチャがたまたまゲートを満たさない形(`Value`がプレースホルダーの文字列
リテラルで`VarRef`ではない、出力変数の`=>`束縛が無い等)になっているだけ——`tests/test_pad_codegen.py`
の専用テスト(`SET Counter TO 10\nVariables.IncreaseVariable...`等)では正しく実コードを生成することを
別途確認済み。フィクスチャ自体は実機キャプチャの忠実な記録を保つため書き換えない(でっち上げ
防止)——この3件は実質的には解決済みとみなしてよい。残り11件(`Text.RecognizeEntitiesInText`の
外部NLP未導入による恒久的フォールバック、`ON ERROR`named/multiple arms、他の🖥️系)が実質的な
残課題。

- [x] 💻🖥️ CSVヘッダー無しケース(`FirstLineContainsColumnNames: False`)の実機確認→`pad_action_lib.datatable`の
  ヘッダー無しモード対応。`File.ReadFromCSVFile`/`WriteToCSVFile`/`Variables.ConvertDataTableToCSV`/
  `GenerateDataTableFromCSV`が対象。実機で列名の既定規則(`Column1`等?)を確認するまでコードは書かない。
  ✅ **実機確認・結線完了(知見84)**: VMが空いたタイミングで知見81の「Run実行+ファイル
  書き出し」手法を使い、`1,2,3\n4,5,6\n`というヘッダー無しCSVを実機で読み込ませ、
  `IncludeColumnNames: True`で書き戻した結果列名は**`"Column#1"`/`"Column#2"`/
  `"Column#3"`**(`#`付き、推測していた`"Column1"`とは異なる)だと確定した。
  `datatable.py`に`first_line_contains_column_names`/`include_column_names`引数を
  追加し、`File.ReadFromCSVFile.ReadCSV`/`File.WriteToCSVFile.WriteCSV`/
  `Variables.ConvertDataTableToCSV.DataTableToCSVCommonSeparator`を結線した
  (`Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator`は`ReadFieldsAsText`
  の数値コレーション挙動が別途未確認のため`True`の場合のみ)。
  ✅ **`ReadFieldsAsText: False`も実機確認・結線完了(知見92)**: VMが空いたタイミングで
  知見81の手法を使い、`"007"`が`"7"`に変化(先頭ゼロ消失)することを確認——数値として
  解釈できるフィールドは実際に数値型へ変換されると確定した。`datatable_from_csv_text()`
  に`read_fields_as_text`引数を追加し`True`/`False`両方を結線した
  (`codegen_coverage.py`: 179/202→180/202)。
  ✅ **`TrimFields`も実機確認・結線完了(知見93)**: VMが空いたタイミングで知見81の
  手法を使い、`" 7 , abc "`→`TrimFields: True`で`"7,abc"`・`False`で`" 7 , abc "`
  のまま、と確認——単純な`.strip()`相当だと確定した。`datatable_from_csv_text()`/
  `file_actions.read_from_csv_file()`に`trim_fields`引数を追加し、
  `Variables.GenerateDataTableFromCSV`/`File.ReadFromCSVFile.ReadCSV`の両方で
  実際に値を読み取って結線するよう修正した(従来は値を読み取らず常に無視していた
  潜在的な不整合だった)。
- [x] 💻🖥️ `Variables.FilterDataTable`の条件(`FilterParameters`)スキーマを特定・結線。
  ✅ **decompile+実機確認・結線完了(知見90)**: RDP不要——`ilspycmd`でVM上の
  `Microsoft.Flow.RPA.Desktop.Modules.Variables.Actions.dll`を再デコンパイルし、
  `FilterParameters`が`COLUMN`/`OPERATOR`/`VALUE`/`RULE`列(16種の`FilterConditionOperator`・
  `Or`/`And`の`RULE`)だと判明。知見81のRun実行手法でTier1確認済みアクションだけから
  `FilterParameters`テーブル自体を組み立て、`Equal`・`Contains`・2条件ANDの3パターンを
  実機検証、全て一致。`filter_datatable()`を実装・結線した(`codegen_coverage.py`:
  177/202→178/202)。
- [x] 💻🖥️ `Variables.JoinDataTable`の結合条件(`JoinParameters`)スキーマを特定・結線。
  ✅ **decompile+実機確認・結線完了(知見91)**: RDP不要——知見90と同じ2段階アプローチ。
  `JoinParameters`は`"COLUMN 1"`/`OPERATOR`/`"COLUMN 2"`列(列名に半角スペース注意、
  `OPERATOR`は`JoinComparisonOperator`6種、全行AND結合)。`Inner`/`Left`/`Full`の3種を
  Tier1確認済みアクションだけで組み立てた2テーブルで実機検証、列名重複時の`" (2)"`
  リネーム・null埋めまで含めて全て一致。`join_datatable()`を実装・結線した
  (`codegen_coverage.py`: 178/202→179/202)。これでA節の「FilterDataTable/JoinDataTable
  のスキーマ未確認」ブロッカーは両方解消。
  🐛 **自己発見バグを修正(知見97)**: 留保事項だった順序比較演算子(`GreaterThan`等)を
  実機確認したところ、`JoinDataTable`では数値変換せず文字列の辞書順で比較する
  (`"9" GreaterThan "10"`が真)と判明——知見91で実装した数値変換ロジックは誤りだった
  ため削除した(`FilterDataTable`側は元々数値変換ロジックが無く偶然正しかった)。
- [x] 🖥️ `Variables.SubtractLists`/`FindCommonListItems`が使うPAD独自比較エンジン
  (`ComparisonCalculator.Compare`)の挙動確認(大文字小文字・型変換ルール)。
  ✅ **実機確認・結線完了(知見85)**: VMが空いたタイミングで知見81の「Run実行+
  ファイル書き出し」手法を使い、`["Apple"] - ["apple"]`(大文字小文字)・
  `["1"] - [1]`(文字列vs数値)を実機で検証。結果: 文字列は大文字小文字を
  **区別する**が、数値文字列と数値は**型をまたいで等価**と判定される。
  `variables_actions.py`に`_pad_compare_equal()`を実装し、`subtract_lists()`/
  `find_common_list_items()`の`NotImplementedError`を解消、`pad_codegen`も結線した。
  ✅ **フォローアップも解決(知見88)**: `IF`/`SET`の`=`/`<>`演算子も同じ比較エンジンと
  全く同じ型変換規則に従うと実機確認(`"1" = 1`は真、`"Apple" = "apple"`は偽)。
  `expr_runtime.pad_equal()`を新設し`render_condition()`/`_render_expr_as_python()`の
  両方で`=`→`pad_equal(a, b)`・`<>`→`not pad_equal(a, b)`に変更、`variables_actions.py`の
  重複実装もこちらへ統一した。
- [x] 🖥️ `UIAutomation.IfImage.ExistsOnScreen`のPython変換ロジック(画像照合の意味論)。
  `IfImageAction.Images`は`List<PngEncodedImage>`(実際にスクリーンキャプチャで切り出した
  PNGバイナリそのもの、paste/Tier1アクションの組み合わせでは作れない)で、実機のUI要素
  リポジトリ/画像セレクタ取得にはRDPが必要(知見38/39/42)という制約で真にRDP必要。
  ✅ **実装完了(知見207)**: desktop access下でドラッグ選択による画像キャプチャを実機実行、
  実際のPNGバイナリを含む`ImageRepositorySymbol`を初めて取得した。`FindAllImages: False`・
  画像1件のみ・`SearchAlgorithm: Legacy`という実機確認済みの組み合わせに限定して
  `pad_codegen`へ結線(`imgrepo[...]`角括弧リスト構文専用の`ImageRepositoryRefList`型、
  `control_repository.parse_image_repository()`、`pad_action_lib.ui_image_actions.
  image_exists_on_screen()`——`pyautogui.locateOnScreen()`への委譲、PADのTolerance値は
  線形近似でconfidenceへ変換する旨を明記した非厳密対応)。複数画像・`FindAllImages: True`・
  他アルゴリズムは引き続き未確認のため`NotImplementedError`のまま。
  ✅ **訂正・結線完了(知見196・199)**: 当初ここに一緒に挙げていた
  `UIAutomation.IfWindowContains.WindowContainsElement`は、「RDP必要」という本項目の判断が
  誤りだったと判明——`IfWindowContainsAction`は`WaitForWindowContentAction`と全く同じ
  `WindowContainsActionBase`を共有し、`Control`(`Click.Click`の`Element`と同じ既知の
  `UiElementRef`機構)のセレクタ解決さえできれば`exists()`へ1対1対応するだけで、RPC不透明な
  `CheckForWindowContent()`の内部実装理解は不要だった(知見196の論法をそのまま適用)。
  `WindowDoesNotContainElement`/`WindowContainsElementInState`も含め結線済み、残る
  `WindowContainsText`/`WindowDoesNotContainText`のみ依然見送り(テキストマッチの
  意味論が実機未確認)。
- [x] 💻 **新規発見(知見160、`tools/pad_selector_audit.py`でUIAutomation.Actions.dll全体を
  再監査して判明)した8系統を精査・1件結線(知見161)**: decompileで精査した結果、
  `TakeScreenshotOfUIElement`(兄弟セレクタ2件)は`Control`プロパティが`UIAutomation.
  Click.Click`の`Element`と全く同じ`UiElementRef`機構(パラメータ名に関わらず値の構文
  だけで判別される)で、動作自体もpywinauto標準API(`capture_as_image().save()`)かつ
  曖昧さが無いため、`TakeScreenshotOfUIElementAndSaveToFile`(`SaveMode=File`固定)を
  実機未確認のまま安全に新規結線できた(`SaveMode=Clipboard`固定の兄弟セレクタは
  OSクリップボード書き込みが別の未実装機構のため見送り)。
  - [ ] 🖥️🔍 **残課題(知見161で精査・分類)**:
    - `PopulateTextFieldInWindow`/`SetDropDownListValueInWindow`: セレクタ解決自体は
      同じ`UiElementRef`機構で可能と確認済み(新たなRDP作業は不要)。残るブロッカーは
      `PopulateTextMode`(Replace/Append)・`ClickType`・`OptionsNames`/`OptionsIndeces`/
      `UseRegularExpressions`の正確な挙動が実機未確認なこと——知見81の「Run実行+
      ファイル書き出し確認」で解決できる見込み(VM上での実機確認が必要、RDP不要)。
      **知見173/182で試行・ブロック確定**: 空の`List "Actions"`canvasへのclipboard-paste
      (`.set_focus()`→`.type_keys("^v")`)が、RDP未接続状態が長く続いた今回のVM状態では
      実際のWin32キーボードフォーカス移動を起こせず無反応だった(知見173)。次善策として
      知見78の検索+キーボードadd技法(`Edit "Search actions"`への`.type_keys()`で検索語
      入力)も試したが、`SendInput() inserted only 0 out of 2 keyboard events`で即座に
      失敗(知見182)——`type_keys()`/`SendInput`自体がこのセッション状態では対象を問わず
      全滅していると確定し、「空canvasへのpasteだけが特異的に失敗する」という知見173の
      理解を訂正した。`.invoke()`(ボタン押下・Run実行)は引き続き機能する。実機動作確認
      には**RDP接続以外に有効な代替手段が無い**と確定、RDPが使えるようになるまで保留。
    - `GetSelectedCheckboxesInWindow`/`GetSelectedRadiobuttonInWindow`: UI要素セレクタ
      を使わず「現在のウィンドウ全体をスキャンする」操作と判明——出力される識別名の
      形式(表示テキスト/AutomationId)が実機未確認。**知見175調査時に追加確認**:
      両方とも`UIAutomationActionBase`派生で`PerformAutomation(... r.GetCheckboxState
      /GetSelectedCheckboxesInWindow/GetSelectedRadiobuttonInWindow ...)`という
      `IAutomationRuntimeProxy`経由——知見172のRPC不透明な壁にそのまま該当、
      decompileでは解決不可と確定(RDP実機確認が必要)。
    - `ExtractDataFromTable`/`ExtractDataFromWindow`: ライブExcel COM書き出しを伴う
      複合動作で、知見155のExcelスコープ(openpyxlでは再現不可)と同じ制約に抵触。
    - `WaitForImageAction`: `IfImageAction`と同じ`CheckImageActionBase`系列——知見38/39/42
      の既知の制約(画像セレクタの実機取得にRDPが必要)がそのまま当てはまる。
- [x] 🔍 **新規発見・1件結線(知見164)**: `ActionSelectorBase`一括列挙監査には
  「兄弟セレクタを持たないフラットな`[Action]`クラス自体は検出されない」という
  構造的な盲点があると判明——`[Action]`/`[ConditionAction]`/`[WaitAction]`属性を
  持つ全クラスを直接列挙したところ、UIAutomation.Actions.dllに新たに15系統を発見
  (`tools/selector_dumps/UIAutomation_flat_actions.txt`)。知見160の「8系統」調査は
  この盲点のため氷山の一角だった。`FocusTextFieldInWindow`(→`UIAutomation.
  FocusTextField`)は`TakeScreenshotOfUIElement`(知見161)と同じ低リスク条件
  (`UiElementRef`機構+曖昧さの無い`.set_focus()`)を満たすため新規結線した。
  - [x] 💻 `PressWindowButton`(→`UIAutomation.PressButton`) — 知見167でdecompile
    再精査・新規結線完了。`Button`(`UiElementRef`)+`Simulate`(bool)で`.invoke()`/
    `.click_input()`を切り替えるだけ。`tests/fake_pywinauto.py`に`.invoke()`フェイクを
    追加して検証した。
  - [x] 💻 `HoverOnElementInWindow`(→`UIAutomation.HoverOnElement`) — 知見168で
    decompile精査・新規結線完了。`Element`(`UiElementRef`)のみ、動作はpywinautoの
    `click_input(button='move')`(クリックせず要素中心へ移動)に1:1対応。
  - [x] 💻 `SelectTabInWindow`/`SelectRadioButtonInWindow`(→`UIAutomation.SelectTab`/
    `SelectRadioButton`) — 知見169でdecompile精査・新規結線完了。pywinautoの
    `UIAWrapper.select()`(SelectionItemPattern)に1:1対応。
  - [x] 💻 `SetCheckboxStateInWindow`(→`UIAutomation.SetCheckboxState`) — 知見169で
    decompile精査・新規結線完了。`get_toggle_state()`で現在状態を読み、目的の状態と
    異なる場合のみ`toggle()`する冪等パターン(UIAのTogglePattern自体の制約による
    唯一の実装方法)。
  - [x] 💻 `DragAndDropElementInWindow`(→`UIAutomation.DragAndDropElement`) —
    知見170でdecompile精査・新規結線完了。`Click.Click`で実機確認済み(知見56)の
    `ClickType=LeftClick`・`RectangleEdgePoint=MiddleCenter`・オフセット0/0の組み合わせ
    に限り、pywinautoの`drag_mouse_input(dst=...)`に1:1対応。それ以外はTODO。
  - [ ] 🖥️ **残課題(知見172で確定: decompileでは解決不可、RDP実機確認が必要)**:
    - `SelectMenuOptionInWindow`/`ExpandCollapseTreeNodeInWindow`: `IAutomationRuntimeProxy`
      の実装(`RemoteAutomationRuntimeProxy`、`Microsoft.Flow.RPA.Desktop.Modules.
      UIAutomation.Common.dll`)は`System.Reflection.DispatchProxy`派生の汎用動的プロキシで、
      全呼び出しをRPC越しの別プロセス(サンドボックス化されたオートメーション実行ワーカー)へ
      中継するだけ——このインターフェースの全メソッドの実際の挙動は.NETアセンブリとして
      静的取得・decompileできる範囲の外にある。これ以上はRDPでの実機観察以外に道が無い。
    - [x] 💻 `GetUIControl`(→`UIAutomation.GetUIControl`) — 知見175でdecompile精査・
      新規結線完了。`ActionBase`直継承で`IAutomationRuntimeProxy`を一切使わない唯一の
      例外——`Execute()`は`UIControl = Control;`のみで、`Control`を無変換で出力へ
      echoするだけと確定。知見57の`GetWindow.Get`と同じ「解決済みセレクタ式を出力変数へ
      代入」パターンで結線した。
    - `GetDetailsOfElementInWindow`(→`GetElementDetails`)/`GetWindowDetails`: いずれも
      `UIAutomationActionBase`派生で知見172の`IAutomationRuntimeProxy`RPC不透明な壁に
      該当(`GetUIControl`とは違い依然ブロック)。`AttributeName`/`ExtractionOperation`
      (`"Own Text"`/`"Exists"`/`"Location and Size"`/`"Enabled"`)が実際にどのUIAプロパティ
      に対応するかは、decompileでは解決不可と確定——RDP実機確認が必要。
    - `UseDesktop`/`IfRemoteDesktopIsAvailableAction`/`WaitForRemoteDesktopAction`:
      リモートデスクトップ機能専用、スコープ外の可能性が高い。
- [x] 🔍 **同じ手法を全モジュールへ拡大適用・1件結線(知見165)**: `pad2py-sweep-
  all-flat-actions`でDatabase/Web/XML/Cmd/Clipboard/DateTime/Text/Cryptography/
  File/Folder/Variables/Compression/Excel/Word/PowerPoint/PDFを一括監査
  (`tools/selector_dumps/_all_modules_flat_actions_raw.txt`)。ほとんどは既に
  結線済みと確認(Database/Web/XML/Cmd/Clipboard/DateTime/Cryptography/File/
  Folder/Compressionは0件)。`Variables.FilterList`(`FilterDataTable`と同じ
  `FilterParameters`スキーマ、知見90の兄弟アクション)を新規発見・結線した
  (Contains/StartsWith/EndsWith/IsEmpty/Equal/NotEqual等10演算子のみ、
  GreaterThan系・IsBlank系は実機規則/Blank値のPython表現が未確認のため
  `NotImplementedError`に留めた)。
  - [x] 💻 `Excel.DeleteColumn`/`DeleteRow`/`InsertColumn`/`InsertRow` — 知見166で
    decompile精査・新規結線完了。openpyxlの`delete_cols()`/`delete_rows()`/
    `insert_cols()`/`insert_rows()`に1:1対応する低リスク追加(セレクタ無し、
    `Instance`+`Column`または`Index`のみ)。
  - [x] 💻 **`Excel.GetTableRange`(`IsPivot=False`側)— 知見180で解決・新規結線完了**:
    `IExcelActions`の具象実装クラス(同じDLL内)まで遡って`GetTableRange()`自体の
    実装を読んだ結果、COMの`ListObject.Range`(ヘッダー行込みのテーブル全体、
    `openpyxl`の`Table.ref`と1:1対応)を**アクティブシートのみ**検索すると確定——
    知見166で懸念していた「ワークシート横断探索」自体が実は不要だった。`IsPivot=True`
    (`PivotTable.TableRange2`、`openpyxl`に対応APIが無い)のみ依然`NotImplementedError`
    のまま保留。
  - [x] 🔍 **decompileで確定確認済み(対応不要、知見171)**: `Excel.Attach`
    (`AttachToRunningExcelDocument`)/`Word.Attach`(`AttachToRunningWord`)/
    `PowerPoint.AttachToRunningPowerPoint`(同型)はいずれもライブCOMプロセスへの
    直接アタッチ、`Excel.RunMacro`はライブExcel上のVBAマクロ実行、
    `Excel.GetSelectedCellRange`はライブExcel UIの「現在の選択範囲」読み取り、
    `PowerPoint.CopyPastePowerPointSlide`は2つの独立`PowerPointInstanceHandle`間の
    クロスプレゼンテーションコピー——6件全てdecompileで確認済みのライブCOM専用機能。
    専用dispatchは元から存在せず汎用TODOフォールバックに安全に落ちるため対応不要。
    ✅ **7件目を追加確認(知見189)**: `_all_modules_flat_actions_raw.txt`の全エントリを
    手動照合したところ`Excel.GetActiveCell`(`GetActiveCellAction`)が一度も検討されずに
    残っていたと判明——decompileした結果、ライブExcel COMの`Application.ActiveCell`
    読み取りのみで`openpyxl`に対応概念が無く、上記6件と同種のライブCOM専用と確定した
    (対応不要、同じTODOフォールバックのままでよい)。これで横断監査リストの全エントリが
    「結線済み」または「対応不要と確認済み」のいずれかに分類された。
  - [x] 🔍 **`tools/pad_selector_audit.py`をExcel/Word/PowerPoint/Pdf/UIAutomationへ実際に
    実行(知見190)**: Excelで84件の候補が出たが、ほぼ全てが`excel_actions.py`自身の
    docstringが既に明記する「ユーザー指定スコープ外」(フィルタ・ソート・オートフィット・
    マクロ実行・セル色設定・コピペ・検索置換・ルックアップ・ライブ選択状態)だった。
    `Excel.ReadCellFormula`(数式文字列の読み取り、`write_to_excel()`の対称操作)のみ
    スコープ内と判断し新規結線した。Word/PowerPoint/Pdfは既知の保留事項のみ(新規発見無し)。
    ✅ **`Excel.DeleteCells`の2件を結線完了(知見197)**: 知見194で「`openpyxl`に
    対応APIが無い」として見送ったが、`docs-local/pad_excel_findings.md`に「技術的には
    可能」と既に記録されていたと再発見し訂正、実装した。COMの`Range.Delete(Shift:=
    xlShiftToLeft/xlShiftUp)`相当を、セル単位の値+書式コピーで近似(使用範囲は
    シフト前に1回だけ固定評価、結合セル絡みは実機未確認のため対応せず)。
    **これで知見190で発見した84件のExcel候補の全てが「結線済み」または
    「ユーザー指定スコープ外(フィルタ・ソート・オートフィット・マクロ実行・
    セル色設定・コピペ・検索置換・ルックアップ・ライブ選択状態)で対応不要」の
    いずれかに分類された——Excel残課題は完全に解消。**
    ✅ **`Excel.ResizeColumnsOrRows`のCustomSize側6件を結線完了(知見195)**:
    `[Action(Id = "ResizeColumnsOrRows")]`がクラス名の`...Action`接尾辞を取り除くと
    判明(知見190の候補報告はこれを見落としていた)——正しいaction_idは
    `Excel.ResizeColumnsOrRows.<セレクタ名>`。`ColumnWidth`/`RowHeight`への直接設定
    (`Single`/`Range`)・`sheet_format.defaultColWidth`/`defaultRowHeight`
    (`AllAvailable`)で対応した。
    ✅ **`Excel.ClearCellsFromExcel`の3件を結線完了(知見194)**: COMの`Range.Clear()`
      (値・書式両方)相当を`cell.value = None`+`cell.style = "Normal"`で近似。
      `ClearCellsRelativeTo`はライブExcel UIの`ActiveCell`を基準点にするため
      知見171/189と同じライブCOM専用機能と判明、見送り。
    ✅ **`Excel.CopyExcelWorksheet`の2件を結線完了(知見193)**: COMの`Worksheet.
      Copy(Before/After)`+リネーム相当。同一ワークブック内コピーのみ対応——
      `openpyxl`の`Workbook.copy_worksheet()`はクロスワークブックコピーを明示的に
      禁止するため(実際に試して確認)、`SourceInstance`/`TargetInstance`が別々の
      ワークブックの場合は`NotImplementedError`。
    ✅ **`Excel.GetEmptyCellFromExcel`の8件を結線完了(知見192)**: `GetEmptyCellsRangeMode`
      (`NamedCell`/`Coordinates`) × `EmptyCellsOperation`(`AllEmptyCells`/`FirstEmptyCell`/
      `FirstEmptyCellInColumn`/`FirstEmptyCellInRow`)。走査順序・空判定(`Cells.Text`が
      空文字列)・「見つからない場合は例外ではなく既定値`(0, 0)`のまま」をdecompileで確定し、
      `excel_actions.get_empty_cell()`として実装した。
    ✅ **`UIAutomation.WaitForWindow`の8件を結線完了(知見191)**: `ToOpen`/`ToClose`/
      `ToBecomeFocused`/`ToLoseFocus` × `ByInstanceOrHandle`/`ByTitleClass`。
      `conditions.py`の`IfWindow`側ロジックを`selectors.py`の
      `_window_expr_by_instance_or_title_class()`へ抽出し`wait.py`と共有する形で実装した。
      残り4件は別種のギャップ: `WaitForWindowContent`の
      `WindowToContainElementInState`/`WindowToContainText`/`WindowToNotContainElement`/
      `WindowToNotContainText`は単純なByリネームではなく判定条件自体が異なる
      (テキストマッチ・要素状態・否定系)。
      ✅ **このうち2件を結線完了(知見196)**: `WindowToNotContainElement`
      (`WindowToContainElement`の単純な否定)・`WindowToContainElementInState`
      (`State`列挙値が`Enabled`/`Disabled`の2値のみと確定、pywinautoの
      `.is_enabled()`と対応付け、タイムアウト指定無しの場合のみ対応)。
      **残り2件(`WindowToContainText`/`WindowToNotContainText`)は依然未解決**:
      テキストマッチの正確な意味論(部分一致/完全一致・大小文字区別・検索範囲)が
      実機未確認のため見送り。
  - [x] 💻 **`Services`は知見165の監査対象リストに含まれていなかったと判明・新規4アクション
    結線完了(知見187)**: `Microsoft.Flow.RPA.Desktop.Modules.Services.Actions.dll`を
    新規取得・decompileし、`Services.Start`/`Stop`/`Pause`/`Resume`(フラットなaction、
    `ServiceController.Start()`/`.Stop()`/`.Pause()`/`.Continue()`)を発見・実装した。
    pywin32の`win32serviceutil`(既存の依存関係)が同じWin32 SCM APIを呼ぶため1対1対応。
    ✅ **自己訂正・結線完了(知見188)**: 知見187時点で「`IfServiceAction`の新発見3兄弟
    セレクタ(`IsInstalled`/`IsNotInstalled`/`IsPaused`)は汎用パーサー側の対応で足りる」と
    書いたのは**確認不足の誤り**だった——実際には既存の`IsRunning`/`IsStopped`含め全て
    `NotImplementedError`/TODOのまま未結線と判明。`IfService`/`WaitForService`列挙値
    自体がWin32標準の`SERVICE_STATE`定数(`IsRunning`=4/`IsStopped`=1/`IsPaused`=7)
    そのものとdecompileで確定し、`services_actions.get_service_status()`/
    `is_service_installed()`を追加して`Services.IfService.*`(5値全て)・
    `Services.WaitForService.*`(3値全て、タイムアウト指定無しの場合のみ)を正式に結線した。
- [~] 💻 ON ERROR/ON BLOCK ERRORの名前付き・複数アームのcodegen結線 — commit (この後のコミット)で、
  知見36の複数アーム構文と知見73の`pad_action_lib`例外タグ(`[Throws]`名=クラス名)を
  `dump_daemon/pad_codegen/error_tags.py`で対応付け、タグ名が既知の場合は実際の
  `except <クラス>:`(同名タグが複数ファミリーに独立定義されている場合はタプルで全て捕捉)
  に変換するようにした——VM不要、既存の確認済み知識の組み合わせのみで実装。ただし
  既存の唯一の実機フィクスチャ(知見36、`RunPythonScriptError`)は`Scripting`系の
  タグで`pad_action_lib`のスコープ外のため今も`# TODO`のまま(想定通り)。
  🖥️ **残課題(知見87で原因確定・RDP必要カテゴリへ再分類)**: `codegen_coverage.py`の
  error_handlingバケット(8/16)を実際に動かすには、`pad_action_lib`で結線済みのタグ
  (`CopyFileError`等)を使う`ON ERROR <TagName>`の実機キャプチャが別途必要だが、
  知見75のペースト技法では**新規作成不可能**と確定した(3段階の切り分け実験で、
  タグ名の有無・単一/複数アーム・アクション種別のいずれを変えても同じ
  `"The statement isn't allowed inside exception handling."`エラーで失敗、知見36の
  既知良好構成`RunPythonScript`+`ON ERROR RunPythonScriptError`をフレッシュペーストしても
  同様に失敗)。`ON ERROR`系構文は**読み取り専用**(ダイアログの「Error handling」有効化を
  実際に操作して初めて構成でき、その結果をコピーして読むことしかできない)——知見82の
  Tier3ダイアログ設定と同じ「🖥️ RDP必要」カテゴリの制約。RDPが使えるようになるまで保留。
- [x] 🖥️ `pad_expr`(Lark式パーサー)の演算子優先順位・結合性を実機で確認し、確認できたら
  `pad_codegen`を`RawExpr`丸ごとTODOから実際のPython式生成へ切り替える。複合式(`AND`/`OR`/算術混在)の
  実例を複数実機コンパイルして優先順位の違いが出るケースを探す。
  ✅ **実機確認・codegen結線完了(知見81)**: **新手法を発見**——ツールバーの`Button "Run"`を
  `.invoke()`で呼ぶだけでRDP接続無しでも実際にフローを実行できることが分かった。新規テスト
  フロー(`pad_expr_precedence`、保存せず破棄)で`SET <Var> TO <式>` + `File.WriteText`の組を
  5パターン貼り付け→Run→`clipwire exec`でファイル内容を読む、という手順で、`1+2*3`=7・
  `True OR True AND False`=True・`True XOR True AND False`=True・`True OR False XOR True`=True・
  `NOT True AND False`=Falseの全5件が、`pad_expr`文法が最初から採用していた
  `OR<XOR<AND<NOT<比較<算術`という仮定と一致することを確認(フラット左結合では説明できない)。
  これにもとづき`render_expr_as_python()`(`dump_daemon/pad_codegen/render.py`)を追加し、
  構文木が`mod`/`/`(値の意味論が別課題として未確認のまま、知見53・81)を含まない場合に
  `SetVariableRecord`の複合式を実際のPython式へ変換するようにした(commit 512cf11)。
  🖥️ 残課題: `mod`の負数での符号規則・`/`が常に浮動小数点除算になるかという値の意味論は
  今回発見した「Run実行+ファイル書き出し」の手法で追って確認できる見込み(知見81に記録)。
  ✅ **`/`・`mod`の値の意味論も実機確認・結線完了(知見83)**: `/`は常に浮動小数点除算で
  Pythonの`/`と完全に一致(`-7 / 2 = -3.5`)。`mod`は符号が被除数と一致する
  (VB.NET/C言語のfmod方式、`-7 mod 3 = -1`・`7 mod -3 = 1`)——Pythonの`%`(符号は除数と
  一致)とは異なるため、`math.fmod(a, b)`として変換するよう`render.py`を更新した
  (commit予定)。これで`pad_expr`の演算子優先順位・値の意味論は全て解決し(関数呼び出しが
  `SET`式内に現れるケースのみ実機未確認のまま)、`SET`複合式のTODOフォールバックは
  構文解析失敗時のみに縮小した。
  💻 **ついでに`UIAutomation.GetWindow.GetUseTimeout`も実コード化(VM不要)**: 知見79/80の
  「不透明な参照(Instance系)はPAD側では単なる変数名、Python側も通常の変数参照で良い」
  という洞察が知見57の「window instance」問題にも当てはまると気づいた。`Control`が
  `UIAutomation.Click.Click`と同じ`UiElementRef`なので知見56のセレクタ式がそのまま使え、
  セレクタが解決でき`BringWindowToFront: True`(意味論未検証)でない場合に限り
  `{変数} = Desktop(backend="uia").window(...)`を生成するよう`ui_element.py`を更新した。
  続けて消費側の`UIAutomation.CloseWindow.CloseByInstanceOrHandle`(知見57追記、
  `WindowInstance`は裸のVarRef)も`{変数}.close()`へ結線し、`GetWindow`→変数→
  `CloseWindow`という一連の流れを結線完了させた(commit予定)。
- [x] 🖥️ `Cryptography.*`/`Compression.*`のDPAPI`Sensitive`引数 — 当初「恒久的に非対応」と
  結論づけていたが、知見112でこの結論自体が誤りだったと判明し解決した。
  ✅ **DPAPI保護値(`P'<base64>'`)自体の復号に成功、恒久的に非対応ではなく「元の
  Windowsユーザー自身が生成スクリプトを実行する場合のみ対応可能」と判明(知見112)**:
  `Microsoft.Flow.RPA.Desktop.Robin.Core.dll`の`DPApi`クラスをVM上でリフレクションに
  より発見し、固定20バイトのentropy定数(ソースからは読めない埋め込み配列だが、
  実行時の値はリフレクションで読める)を実際に取得、`DataProtectionScope.CurrentUser`
  と組み合わせて実機キャプチャ済みの`P'<base64>'`値を実際に復号できることを確認した
  (VM不要・decompileとclipwire exec経由の読み取り専用操作のみ)。`pad_dsl.types`に
  `DpapiSensitiveLiteral`型を追加しパーサーのVarRefフォールバックを解消、
  `cryptography_actions.decrypt_dpapi_sensitive_value()`(`win32crypt`経由)へ結線した。
  `codegen_coverage.py`: 181/202→188/202(93%)。元の値を作成したユーザー以外が
  実行すると`DpapiDecryptionError`になる(でっち上げた平文は返らない)点は正しい
  設計上の制約として残る。
  ✅ **パスワード省略(PAD UIでPasswordを設定しなかった)ケースの結線自体は既に正しく
  実装・結線済みだと合成DSLで確認完了(知見109)**: `Compression.ZipFiles`/
  `UnzipFiles`の`pad_codegen/actions/compression.py`は元々パスワード無しのケース
  向けに結線だけ用意していた(docstring記載通り)が、それを検証する合成テストが
  無かった。実際にzip作成→解凍の往復まで実行するテストを追加し、既存実装が正しい
  ことを確認した。DPAPI保護値(`P'<base64>'`)自体の復号は当時未対応だったが、
  その後知見112で解決した(本項目冒頭参照)。
  ✅ **`Cryptography.*`側も同じパターンで6件を新規結線(知見111)**: `EncryptText`/
  `EncryptFromFile`/`DecryptText`/`DecryptToFile`/`HashTextWithKey`/
  `HashFromFileWithKey`は`pad_action_lib.cryptography_actions`自体は実装済みだが
  `pad_codegen/actions/cryptography.py`に鍵無し2件(`HashText`/`HashFromFile`)分の
  分岐しか無かった(Compressionとは違い結線すら未着手だった)。鍵が(DPAPI保護
  ではなく)ふつうの変数参照の場合の結線を新規実装し、Encrypt→Decrypt往復・
  HashTextWithKeyの値一致を合成DSLで実行確認した。DPAPI保護値自体の復号は
  当時未対応だったが、その後知見112で解決した(本項目冒頭参照)。
- [x] 💻 `Web.*`の`UserAgent`/`FollowRedirection`が値を読み取らず無視されていたバグの修正。
  ✅ **VM不要・既存フィクスチャの再点検で修正完了(知見94)**: 知見93のパターン
  (値を読み取るように見えて実は無視)を他モジュールでも探索した結果発見。
  `UserAgent`の正確なUA文字列は実は`tests/fixtures/tier1_web_xml_batch8.txt`に
  既に実機キャプチャ済み(「正確なバイト列は未確認」というdocstringの記述が古かった)
  だったため、でっち上げではなく実機値そのまま結線できた。`invoke_web_service()`/
  `invoke_soap_service()`は`follow_redirection`/`user_agent`を受け付けておらず、
  httpxの既定`follow_redirects=False`が実機既定`True`と食い違うサイレントなバグ
  だったため修正・結線した。`ClearCookies`/`EncodeRequestBody`は設計変更を伴う/
  decompile未着手のため依然未対応。
  ✅ **体系的な突き合わせで追加2件発見・修正完了(知見95)**: 全フィクスチャの
  実機キャプチャ済みパラメータと各codegen分岐の`p.get(...)`参照を機械的に
  突き合わせたところ、`Web.InvokeSoapService`の`FailOnErrorStatus`/
  `TrimRequestBody`/`AcceptUntrustedCertificates`が`invoke_soap_service()`
  自体に引数が無く常に既定値のまま呼ばれていた(実機値が偶然既定値と一致していた
  ため今まで症状無し)バグと、`Folder.GetFiles`/`GetSubfolders`の`SortBy1`しか
  ゲートしておらず`SortBy2`/`SortBy3`の実際の並べ替えキー指定を見逃す不完全な
  ゲートを発見・修正した。
  ✅ **`EncodeRequestBody`もdecompileで解明・結線完了(知見96)**: VM上の
  `Microsoft.Flow.RPA.Desktop.Modules.Web.Actions.dll`をdecompileし、
  `HttpUtility.UrlEncode`相当(空白は`+`)を`TrimRequestBody`より先に適用する
  実装だと確定。`invoke_web_service()`に`encode_request_body`引数を追加し結線した。
  副産物として`ClearCookies`がフロー実行全体で共有される永続Cookieジャー
  (`CompiledJob.CookieContainer`)のリセットだと意味論が確定したが、再現には
  `pad_action_lib`の「呼び出し毎に新規`httpx.Client`」設計の変更を伴うため、
  実機で複数Web呼び出しを跨ぐ必要例も無いことから依然見送る。

## B. 一度も実機検証していない領域(TODOより深い穴)

- [x] 🖥️ **`IfFunctionRecord`(Contains/Does not contain/Is empty等)の初回実機キャプチャ** —
  ユーザーがPADにサインインし次第、`clipwire exec`(Tailscale、RDPセッション接続不要)経由で
  実機確認完了(知見75)。確認済み4関数: `Contains(a,b)`/`NotContains(a,b)`/`IsEmpty(a)`/
  `IsNotEmpty(a)`。**新しい検証手法を発見**: PADデザイナーのアクションリストはクリップボード
  からのペースト(Ctrl+V)でDSLテキストを直接取り込める(読み取り専用ではなく双方向)——
  `pywinauto`の`control.type_keys()`(対象コントロール宛の疑似キー入力)でこれを駆動すれば、
  ドラッグ&ドロップ・マウスクリック無しで新規アクションの追加・設定確認までRDP無しで完結する
  (ダイアログを閲覧する`descendants()`系の読み取りはRDP無しでは機能しなかったが、ペースト→
  結果の文字列表示を読む→全選択コピーで読み戻す、という往復だけなら十分だった)。
  `pad_codegen`側はこの4関数をPythonの`in`/`not in`/真偽値判定に結線済み(condition_function_call
  ブランチ0/4→4/4、全体カバレッジ82%→83%)。
- [x] 🖥️ **新規発見(知見200)、到達可能性は知見204で決着**: `Robin.Engine.dll`の
  `FunctionExpressionEvaluator`に、既知の4関数(`Contains`/`NotContains`/`IsEmpty`/
  `IsNotEmpty`)以外に`ContainsKey`/`Count`/`EndsWith`/`StartsWith`/`Blank`/`IsBlank`
  という未確認の関数が存在すると判明していた。知見202/203の`clipd`非対話的ウィンドウ
  ステーション問題(ユーザーによるパスワードリセット・RDP接続・clipd再起動で解消)を
  経て、知見75の往復手法で6関数全ての到達可能性を実機確定した: `EndsWith`/
  `StartsWith`/`IsBlank`は標準If条件UIから**到達可能**(`"Has error"`無し)、
  `ContainsKey`/`Count`/`Blank`は**到達不能**(`"Has error"`)。続けて知見81の「Run実行+
  ファイル書き出し」手法で`EndsWith`/`StartsWith`/`IsBlank`の実際の真偽値まで実機確認した
  (知見205): `EndsWith`/`StartsWith`は大文字小文字を区別しない文字列部分一致(結線済み、
  文字列以外は未確認のため例外)、`IsBlank`は空文字列・非空文字列・空白のみの文字列いずれも
  `False`になり`IsEmpty`の別名ではないと確定(何が`True`になるか不明なため未結線のまま
  保留)。`dump_daemon/pad_action_lib/text_actions.py`の`function_condition_ends_with()`/
  `function_condition_starts_with()`と`pad_codegen`の結線まで完了。
- [ ] 🖥️ `VariableTrailer`の引数付きトレーラ(`.Name (args)`)を実際に生成するPAD機能の特定。
  🔍 **どのPAD機能が生成するかはdecompileのみ(VM不要)で特定できた**:
  `Microsoft.Flow.RPA.Desktop.Robin.Engine.dll`を新規取得・ilspycmdで再デコンパイルし、
  `.Parameters`(引数)を実際に読み取っている唯一の評価経路が`RepositoryTrailerHandler.EvaluateControl()`
  (`appmask[...]`UI要素リポジトリ参照専用)だと判明した——DataTable/CustomObject等の汎用メソッド
  呼び出しではなく、**UI要素セレクタに実行時の値を埋め込む「動的セレクタ」専用の機構**
  (UiPathの`Dynamic Selector`相当のPAD版)だった。
  **知見206でdesktop access下の実機検証を実施**: 「Inspect UI elements」ピッカーで要素を
  キャプチャ→Selector builderの属性値欄(例: `Value for Name`)に`%変数名%`を直接入力するだけで
  動的化できることを確認した(`Selector text`プレビューが`[Name="%MyDynamicVar%"]`に変化、
  保存後は`# [ControlRepository]`セクションのRepository JSON内`"Value": "%MyDynamicVar%"`に
  そのまま保存される——`RepositoryTrailerHandler.EvaluateControl()`の`.Parameters`評価と
  整合する入力側の挙動)。**ただし、元々問われていた`.Name (args)`という引数付きトレーラ構文
  自体はDSLテキスト上に一度も出現しなかった**(`Element: appmask[...]`参照は単純な名前参照の
  まま変化無し)——この構文がどのPAD機能から生成されるのかは依然未解明のまま。再調査は
  明確な新しい手がかりが見つかるまで見送る(優先度は低)。
- [x] 💻🖥️ `Variables.FindOrReplaceInDataTable.FindItemInDataTableEverywhere`の出力契約
  (`DataTableMatches`の形)を実機確認。
  ✅ **実機確認・結線完了(知見89)**: RDP不要——`AddRowToDataTable`/`AddColumnToDataTable`等
  Tier1で既に結線済みのアクションだけでDataTableを組み立て、知見81の「Run実行+ファイル
  書き出し」手法で検証。`DataTableMatches`は`(行, 列)`の0始まりペアのリスト(行→列の順、
  `AllMatches: False`でも型は変わらず最初の1件だけのリスト)。既存の`_cell_matches()`を
  再利用した`find_item_in_datatable_everywhere()`を実装・結線した
  (`codegen_coverage.py`: 176/202→177/202)。
  - [x] 💻 **`SearchMode=FindAndReplace`側4件の新規結線(知見176)**: `tools/pad_selector_
    audit.py`の再実行で発見した未結線候補——`ReplaceItemInDataTableEverywhere`/
    `ReplaceItemInDataTableWithRegexEverywhere`/`ReplaceItemInDataTableByColumnIndex`/
    `ReplaceItemInDataTableWithRegexByColumnIndex`。Find側と同じマッチ判定・同じ
    `DataTableMatches`出力契約で、`find_and_replace_in_datatable_everywhere()`を新規実装
    (未使用だった旧`find_or_replace_in_datatable()`を置き換え)。副産物として
    `_cell_matches()`のregex分岐が実機と逆(常にIGNORECASEを付与していたが実機は常に
    大文字小文字を区別)という既存の潜在バグも発見・修正した。VM不要。
    **自己訂正(知見183)**: 知見176の実装自体に、過去に別セッションが3回(知見123/
    125/135)記録していた既知の懸念(「置換後のセル型を元の型へ戻す処理が無い」)を
    見落として持ち込んでいたと判明——`_convert_replaced_text_to_original_type()`を
    追加し、`int`/`float`のみ型変換を復元した(`bool`/日付等は実機未確認のため文字列
    のまま、`MatchEntireCellContents`は decompile確認済みの非対称性で意図的に非変換)。
- [x] 🖥️ 型混在の`+`(数値+文字列等)のディスパッチルール(`ExpressionCalculator`/`CalculatorBase<T>`)調査。
  ✅ **実機確認・結線完了(知見86)**: VMが空いたタイミングで知見81の手法を使い、
  `1 + $'''2'''` = `3`・`$'''2''' + 1` = `3`・`$'''a''' + $'''b'''` = `"ab"`を
  実機で検証。両辺が数値(または数値文字列)なら加算、そうでなければ文字列結合
  にフォールバックすると確定した。`dump_daemon/pad_action_lib/expr_runtime.py`に
  `pad_add()`を実装し、`render_expr_as_python()`の`+`演算子をこれに委譲するよう
  更新した。これで`pad_expr`の演算子優先順位(知見81)・値の意味論
  (知見82・83・86)は全て解決した。
- [x] 🖥️ Tier3(Excel/Word/PowerPoint/PDF)アクションの実機DSLキャプチャ・codegen結線 —
  `pad_action_lib`には純粋関数実装(openpyxl/python-docx/python-pptx/pdfium)が既にあるが、
  action_id/パラメータ名の実機確認・codegenへの結線は未着手。
  💻 検証済み(このtick、Excel/PowerPointも追加確認): `pdf_actions.py`/`word_actions.py`/
  `excel_actions.py`/`powerpoint_actions.py`を対応するdocs-local/のdecompile調査ドキュメント
  と逐語的に照合し、非自明な挙動(ページ範囲クランプの非対称性・AppendNewLineが前置/後置・
  CloseWord/CloseExcelのno-op・SlideRange終了側クランプ対単独番号スキップの非対称・Move先の
  範囲が同一/別プレゼンテーションで非対称等)まで含めて既に忠実に実装済みであることを確認した。
  唯一の見つかった改善点: `excel_actions.py`の`_range_to_datatable()`で`FirstLineIsHeader=false`
  時のヘッダー名(列名A/B/C...)が実機未確認の近似であることを示すコメントが無かったので追加
  (commit この後)——PDF側の無ヘッダー時命名("Column1"等)と一致する保証が無いことも明記。
  🔍 **追記**: この`excel_actions.py`/`word_actions.py`/`powerpoint_actions.py`の「実機未確認の
  近似」コメント群(空行除去・ヘッダー無し列名・次の空き行/列の判定等)は、知見112・115・129〜132
  等で使った「VM上でPAD自身のアクションクラスを直接インスタンス化・`Execute()`を呼び出す」
  手法では解決できないと確認した——`pad2py-pad-host`VMには**Word/Excel/PowerPointのいずれも
  COM登録されていない**(`New-Object -ComObject Excel.Application`等が
  `REGDB_E_CLASSNOTREG`で失敗、Officeがインストールされていないため)。Tier3のこの種の
  疑問は、RDPアクセスの有無とは独立に、**Officeがインストールされた別環境**(または
  ユーザー自身の実機)での確認が前提になる。
  残る障壁は`pad_action_lib`側の実装ではなく、action_id文字列・パラメータ直列化形式の実機確認
  (🖥️)のみ——結線作業自体は知見73と同じパターンで機械的に進められる見込み。
  🚫 **ペースト技法は使えないと判明**: 知見75のペースト技法(`IfFunctionRecord`向け)をTier3の
  action_id発見にも使えないか試したが、`PDF.ExtractTextFromPDF`の推定action_idを複数の
  モジュール接頭辞パターンで貼り付けても全て`"Unknown action, Has error"`(または無反応)に
  なった——`IfFunctionRecord`(条件式の文法として汎用的に解釈される)とは違い、`ActionRecord`は
  貼り付け時に閉じた内部カタログへ厳密一致で解決されるらしく、推測では当たらない。
  🔍 **ユーザー提案(dll/exeのリバース解析)で前進、ただし未決着(知見76)**: `ilspycmd`で
  `Robin.Engine.dll`等を再デコンパイルし、action_id構築の一般式
  (`{AssemblyTitle}.{[Action]属性のId}[.{セレクタ名}]`)を`ActionMapperExport`のソースから
  発見・`Text.Trim`で実証した。
  🔍 同tickで`Robin.Core.dll`/`Robin.Language.dll`も追加取得・デコンパイルし式を完全裏付け、
  かつPADデザイナー自身のUI要素(検索結果TreeItemのUIA AutomationId)から`'Pdf.ExtractTextFromPDF'`
  という同じ文字列を直接確認(知見77)——2つの独立した根拠が一致し、action_idの値自体は
  ほぼ確実と言える。**それでもクリップボードのペースト取り込みは依然この文字列を
  `"Unknown action"`として拒否する**という矛盾が残る。仮説: ペースト取り込みは
  `Robin.Language.ActionMapping.ActionMapper`経由の静的・事前生成された後方互換マッピング
  テーブルを使っており、新しいアクションがそこに未収録なだけかもしれない(未検証)。
  プロジェクトの方針上、高確度だが実機DSL往復での確証が無いためまだ結線しない
  (memory `pad2py_clipboard_paste_technique`に次の一手を記録)。
  ✅ **ユーザー提案(VK send key)で前進、`ExtractTextFromPDF`を結線(知見78)**: 検索結果の
  `TreeItem`を`.select()`ではなく`.set_focus()`してから`type_keys("{ENTER}")`すると、
  RDP不要でPADデザイナーに実際にアクションを追加できることを発見——`Pdf.ExtractTextFromPDF`が
  これでエラー無く追加できたことを確認し、(ソース計算式・UI自身のAutomationId・この追加成功)の
  3つの独立した根拠が一致したため「PAD自身の解釈結果による確証」の基準に実質到達したと判断し、
  `extract_text_from_pdf`1件をcodegenに結線した(以降のコミット参照)。キャンバスからの
  コピー読み戻しは依然RDP無しでは失敗する(メニュー系操作が`COMError`になる、新規ポップアップが
  RDP無しで安定しない既知の問題と同根)ため、残りのPDFアクション・Excel/Word/PowerPointの結線は
  この技法を使いつつ1件ずつ地道に確認する必要がある(🖥️のまま)。
  ✅ `extract_text_from_pdf`の`pad_codegen`結線はcommit fc5e7b7で完了(合成DSLテキストでの
  テスト2件+フォールバック1件、`uv run pytest`全件green)。次は同じ技法で
  `ExtractImagesFromPDF`/`ExtractTablesFromPDF`/`ExtractPagesToNewPDF`/`MergeFiles`
  (いずれもPDF)、続けてExcel/Word/PowerPointのTier3アクションを1件ずつ確認する(🖥️)。
  💻 VM待ちの間に知見75/78の手順を`dump_daemon/pad_ui_helpers.py`の再利用可能な関数
  (`find_descendant`/`paste_dsl_into_action_list`/`copy_action_list_as_text`/
  `add_action_via_search`/`get_clipboard_text`)として整備した——次回VM接続時は
  アドホックスクリプトの再構築無しで`add_action_via_search(designer, "Extract images
  from PDF")`のように1行で試せる。**次にVMが空いたら試す検索語の候補**
  (docs-local/pad_pdf_findings.mdの推定action_id表より): 「Extract images from PDF」
  (推定`Pdf.ExtractImagesFromPDF`)・「Extract tables from PDF」
  (推定`Pdf.ExtractTablesFromPDF`)・「Extract pages to new PDF」
  (推定`Pdf.ExtractPages`、他の4件と違い`[Action(Name=...)]`のみで`Id`属性が無い点に注意)・
  「Merge PDF files」(推定`Pdf.MergeFiles`、同じく`Name`属性のみ)——この表自体は
  decompileのみに基づく推定(🔍)であり、`add_action_via_search()`でエラー無く追加できるかの
  実機確認が必要。
  ✅ **VMが空いたタイミングで残り4件を実機確認・結線完了(知見79)**: `pad2py-57`にVM使用可否を
  確認(空いていることを確認)した上で、上記4件の推定action_idを全て実機確認(AutomationId読み取り
  +キーボード追加でエラー無く受理、知見78と同じ3経路収束)。`pad_action_lib.pdf_actions`の
  `extract_images_from_pdf()`/`extract_tables_from_pdf()`/`extract_pages_to_new_pdf()`/
  `merge_pdf_files()`を`pad_codegen`に結線した(`Pdf.MergeFiles`の`Passwords`指定時は
  未確認のためTODOフォールバックのまま)。**これでPDFモジュール5アクション全件の
  action_id確認・codegen結線が完了**。次はExcel/Word/PowerPointのTier3アクションに
  同じ技法(`add_action_via_search`)を適用する(🖥️)。テスト用フロー`pdf_tier3_probe`は
  保存せず破棄、VM解放もpad2py-57へ通知済み。
  ✅ **さらに効率的な確認手段を発見、Excelモジュール全件を一括確認・結線完了(知見80)**:
  キーボード追加すら不要——検索語を1つ入力して結果の`TreeItem`全件の`AutomationId`を
  読むだけで、モジュール丸ごとのaction_idカタログが一括取得できることに気づいた
  (知見77のAutomationId読み取りを「1件ずつ」から「検索語1つで全件」に拡張)。
  これで`Excel.*`14件(スコープ内全件)・`Word.*`8件・`PowerPoint.*`10件の
  action_idを一括実機確認(いずれもdecompile予測と完全一致、モジュール接頭辞は
  `Excel`/`Word`/`PowerPoint`そのもので特別な大小文字差は無し)。`Excel.*`の
  pad_codegen結線(`LaunchExcel`/`SaveExcel`/`CloseExcel`/`ReadFromExcel`/
  `WriteToExcel`/`AddWorksheet`/`DeleteWorksheet`/`RenameWorksheet`/
  `SetActiveWorksheet`/`GetAllWorksheets`/`GetActiveWorksheet`/`GetColumnName`/
  `GetFirstFreeColumnRow`/`GetFirstFreeRowOnColumn`の14件全て)も完了した
  (`Instance`参照はPAD側では不透明参照だが、Python側では他の変数参照と同じなので
  特別な結線は不要だった)。テスト用フロー`tier3_discover`は保存せず破棄済み。
  ✅ **`Word.*`/`PowerPoint.*`のcodegen結線も完了**(🖥️不要、💻のみ):
  `docs-local/pad_word_findings.md`/`pad_powerpoint_findings.md`のパラメータ調査にもとづき、
  `word_actions`の5関数(`launch_word`/`save_word`/`close_word`/`read_from_word`/
  `write_to_word`/`find_and_replace_word`)・`powerpoint_actions`の7関数
  (`launch_power_point`/`save_power_point`/`close_power_point`/`read_from_power_point`/
  `write_to_power_point`/`add_power_point_slide`/`delete_power_point_slide`/
  `move_power_point_slide`)を`dump_daemon/pad_codegen/actions/word.py`/`powerpoint.py`に
  結線した。ライブCOM専用で未対応のモード(Word: ReadMode/WriteModeのPage/Bookmark系、
  既知の`MatchWildCards=True`リテラル)は安全にTODOフォールバックへ委ねた。
  **これでPDF/Excel/Word/PowerPointの全Tier3スコープ内アクションのaction_id確認・
  codegen結線が完了**(残るTier3領域は無し)。
  🖥️ **追記: 挙動確認(実行結果の値比較)を試みたが依然RDPが必要と再確認(知見82)**:
  知見81の「Run実行+ファイル書き出し」手法をTier3にも拡張しようとしたが、キーボード追加した
  アクション(`Pdf.ExtractTextFromPDF`)の設定ダイアログへ`PDFFile`パス等を書き込む段階で
  `child_window()`検索・ブラインドTabナビゲーションの両方がタイムアウトし、依然不可能と
  判明した(3つの独立した経路で再確認、詳細は知見82)。副産物として、固まったダイアログを
  ハング無しに閉じる新手法(`WindowPattern.Close()`の直接COM呼び出し)を発見し、
  `memory: pad2py_run_without_rdp`に記録した。Tier3アクションの往復確認・挙動確認は
  引き続きRDP接続が前提(🖥️のまま、優先度は低)。
  - [x] 💻 **訂正(知見155)**: 上記「`Excel.*`14件結線完了」は、知見80のAutomationId
    確認(アクション**グループ**の存在確認のみ)を「action_id自体の実機確認」と誤って
    混同していた——`ActionSelectorBase`一括列挙監査(知見139以降の標準手法)を初めて
    `Excel.Actions.dll`に適用したところ、`LaunchExcel`/`CloseExcel`/`SaveExcel`/
    `ReadFromExcel`/`WriteToExcel`/`DeleteWorksheet`/`RenameWorksheet`/
    `SetActiveWorksheet`の8グループは実際には兄弟セレクタを持ち、真のaction_idは
    `Excel.<グループ>.<ActionName>`という3セグメント形式だった——従来のフラットな
    判定は**実際のDSLでは一度もマッチせず常にTODOへ落ちていた**(潜在バグ、decompileで
    発見・修正)。decompile(`pad2py-fetch-excel-dll`)で各セレクタの固定列挙値を特定し、
    正しい3セグメント形式へ結線し直した(`pad_action_lib.excel_actions`側は変更不要)。
    - [x] 💻 **同種の潜在バグをWord/PowerPoint/PDFでも発見・修正(知見156-158)**:
      `pad2py-fetch-pdf-dll`/`pad2py-fetch-word-dll`/`pad2py-fetch-powerpoint-dll`で
      DLL本体を取得しdecompile、`ActionSelectorBase`一括列挙監査を適用した結果、
      3モジュール全てで同種の潜在バグを確認。PDF: `ExtractImagesFromPDF`/
      `ExtractTablesFromPDF`/`ExtractTextFromPDF`の3グループ(各3兄弟セレクタ、
      `PagesToExtract`固定)。Word: `CloseWord`/`FindAndReplaceWord`/`LaunchWord`/
      `ReadFromWord`/`SaveWord`/`WriteToWord`の6グループ。PowerPoint:
      `AddPowerPointSlide`/`ClosePowerPoint`/`DeletePowerPointSlide`/
      `LaunchPowerPoint`/`ReadFromPowerPoint`/`SavePowerPoint`/`WriteToPowerPoint`の
      7グループ。いずれも正しい3セグメント形式へ結線し直した(`pad_action_lib`側は
      変更不要)。副産物として、既存のPDF合成テストが実在しない列挙値`SinglePage`
      (実際は`Single`)を仮定していた誤りも発見・修正。
      ✅ **決着(知見162)**: `Pdf.ExtractPages`/`Pdf.MergeFiles`の`[Action(Name=...)]`
      (`Id`属性が無く`Name`属性のみ)についての未確認事項を解消した——
      `Microsoft.PowerPlatform.PowerAutomate.Desktop.Actions.SDK.dll`をdecompileし、
      `ActionAttributeBase.Name`に`[Obsolete("Use ActionAttribute.Id instead.")]`
      という明示的な非推奨注記があることを確認した。つまり`Name`は`Id`の旧名で
      全く同じ役割——`Id`が無く`Name`のみ設定されたクラスは`Name`の値がそのまま
      中間セグメントになると確定した。既存の`Pdf.ExtractPages`/`Pdf.MergeFiles`結線
      (フラットな2セグメント形式)は当初から正しかった(修正不要)。
      `Word.InsertImageToWord`(8セレクタ)は`pad_action_lib`側に未実装
        のため対象外のまま。**訂正(知見177)**: `tools/pad_selector_audit.py`の
        再適用で再調査したところ、`StartOfDocument`/`EndOfDocument`(`Source=File`
        固定)の2件は実はpython-docxの`add_picture()`/`insert_paragraph_before()`
        で再現可能だったと判明し新規結線した——「`InsertImageToWord`全体が
        未実装」という過去の判断は必要以上に広い除外だった。ブックマーク相対・
        テキスト相対・クリップボードソースの残り9件は依然対象外(理由は個別に
        確認済み、知見177参照)。
      - [x] 💻 **`Word.ReadFromWord.ReadBookmark`も新規結線完了(知見181)**:
        `python-docx`に「高レベルAPIが無い」ことは事実だが、OOXMLの
        `<w:bookmarkStart>`/`<w:bookmarkEnd>`をlxmlで直接検索すれば原理的に
        可能だったと判明——Word COMの`Bookmark.Range.Text`を`word_actions.
        _bookmark_range_text()`で再現した。`ReadFromWord.ReadPage`(ライブ
        ページレンダリング依存)はこの技法でも解決せず依然対象外。書き込み側
        (`WriteToWord`/`InsertImageToWord`のブックマーク相対モード)は挿入位置の
        意味論がより複雑なため未着手のまま。
        ✅ **`InsertImageToWord`側の真の障壁を特定(知見198)**: `WriteImageToBookmark()`
        自体のロジックは単純(ブックマーク開始/終了位置へ`Range.Collapse()`するだけ、
        `WriteTextOnBookmark`の`AppendNewLine`段落分割問題とは無関係)と判明したが、
        `python-docx`の公開APIが「ドキュメント/run末尾への画像追加」のみで既存段落の
        途中への画像挿入に対応しないため、`python-docx`の非公開内部実装(リレーションID
        生成・`<w:drawing>`構築)への依存が必要になる——知見181のブックマークテキスト
        読み取り(公開属性への素直なアクセス)とは異なるリスク区分のため見送り継続。
    - [x] 💻 **テスト基盤の死角を解消(知見174)**: Excel/Word/PowerPointの「全スコープ
      バッチ」テストが文字列一致の`compile()`のみで一度も`exec()`していなかったと判明
      (知見124/129/130と同じ死角)。各モジュールに実際に`exec()`して出力変数の値・
      保存ファイルの最終状態まで検証する新規テストを追加したところ、**PowerPointの
      既存DSLは実際に実行すると`MoveSlideInvalidSourcePositionError`でクラッシュする**
      (唯一のスライドを削除した後に空のプレゼンテーションへ`MovePowerPointSlide`を
      呼んでいた)という、6セッション以上気づかれていなかった実行不可能なテストDSLを
      新規発見した。Excel/Wordは実行確認で新規バグ無しと確定。
- [x] 💻 `GenerateDataTableFromCSVAction`/`ConvertDataTableToCSVAction`の`ColumnsSeparator`が
  `SystemDefault`以外(Comma/Semicolon/Tab)で常にTODOへ倒れていたゲート漏れ、および
  両方の`CustomColumnsSeparator`兄弟セレクタ(`ReadCustomSeparator`/`DataTableToCSVCustomSeparator`)。
  ✅ **決着(知見127)**: VM上でのリフレクション直接呼び出しで`CSVColumnsSeparator`列挙値の
  実区切り文字(`SystemDefault`/`Comma`→`","`・`Semicolon`→`";"`・`Tab`→`"\t"`)を確認し、
  `pad_codegen/actions/_support.py`にマッピング辞書を追加して全4値を結線、新規2セレクタも結線した。
  `pad_action_lib.datatable`は元から`delimiter`引数を持っていたため変更不要だった。
  - [x] 💻 `File.ReadFromCSVFile.ReadCSV`/`File.WriteToCSVFile.WriteCSV`の同種ゲート漏れ。
    ✅ **決着(知見128)**: VM上のリフレクションで`File.Actions.dll`の`ColumnsSeparator`が
    `Variables.Actions.dll`と全く同じ`Text.Utilities.dll`の`CSVColumnsSeparator`型だと確認し
    (`PropertyType.Assembly.FullName`で同一アセンブリと確定)、同じマッピング辞書を再利用して
    解消。新規セレクタ`ReadCSVWithCustomSeparator`/`WriteCSVWithCustomSeparator`も結線した
    (`ActionSelectorBase.ActionName`プロパティの直接読み取りでdecompile無しに接尾辞を特定)。
  - [x] 💻🖥️ `ReadFixedColumnWidths`/`ReadCSVWithFixedColumnWidths`(固定長カラム読み込み)。
    ✅ **決着(知見132)**: VM上で`CSVUtilities.TryParseColumnWidths()`と
    `GenerateDataTableFromCSVAction.Execute()`を直接呼び出し、`FixedColumnWidths`文字列の
    構文(カンマ/空白区切り)・固定長パースのアルゴリズム・エッジケース(短い行はエラー、
    長い行は無視)を全て解明し、`datatable_from_fixed_width_csv()`/
    `read_from_csv_file_fixed_width()`を新設して両モジュールに結線した。これでCSV読み込み系
    の未結線セレクタは無くなった。
- [x] 💻 `Compression.ZipFiles`の`ZipFile`出力が`zip_files()`の`None`固定戻り値のため
  常に`None`になる潜在バグ(実際に`exec()`する既存テストも代入先の値を見ていなかった死角)。
  ✅ **決着(知見129)**: VM上で`ZipFiles`クラスを直接インスタンス化・`Execute()`呼び出しし、
  `ZipFile`出力が`ArchivePath`と同じパスのechoだと確認、`zip_files()`に`return archive_path`
  を追加した。
- [x] 💻🖥️ 知見123・126で「実機の0始まり/1始まり設定`IsZeroBased`が未確認」として見送っていた
  `ModifyDataTableItem`/`FindItemInDataTableByColumnIndex`/`RetrieveDataTableColumnIntoList`の
  数値列インデックス対応、および`Variables.SortDataTable`の未結線セレクタ`SortWithColumnIndex`。
  ✅ **決着(知見133、本セッション最大の決着)**: `IListIndexService`の実装クラス
  (`Robin.Core.Execution.ListIndexService`)をVM上で直接インスタンス化して確認したところ、
  本プロジェクトが対象とする`ScriptType.Robin`では`IsZeroBased=True`で`ConvertInput()`は
  恒等写像——つまり列インデックスは常に0始まりと確定した(1始まりになるのは対象外の
  `ScriptType.PowerFx`のみ)。共有ヘルパー`_resolve_column_name()`を新設し、3関数の数値
  インデックス対応を解消、`SortWithColumnIndex`も新規結線した。
  - [x] 💻🖥️ `Variables.SortList`の未結線セレクタ`SortListByProperty`(最大3キー・各キー
    独立したAscending/Descending方向の多キーソート)。
    ✅ **決着(知見134)**: 実機の「CustomObject」が`Actions.SDK.Types.CustomObject`
    クラス(`AddOrUpdateProperty()`/`GetProperty()`)だと判明し、VM上で正しく構築して
    `SortListByProperty`の多キーソート挙動を確認した。Pythonの安定ソートを最下位キーから
    順に適用する「安定ソートの繰り込み」で再現できることも確認し、`sort_list()`に
    `key_descending`引数を追加して結線した。
- [x] 💻🖥️ `Variables.Actions.dll`の全`ActionSelector`サブクラスを一括列挙する監査で
  発見した未結線セレクタ7件(`TruncateNumber.GetDecimalPart`/`RoundNumber`、
  `RemoveItemFromList.RemoveItemFromListByValue`、`FindOrReplaceInDataTable.
  FindItemInDataTableWithRegexByColumnIndex`、`DeleteColumnFromDataTable.
  DeleteColumnWithIndex`、`AddRowToDataTable.InsertItemToDataTable`、
  `AddColumnToDataTable.InsertColumnToDataTable`)。
  ✅ **決着(知見135)**: 全てVM上の直接呼び出しで仕様確認して新規結線した。副産物として
  既存の`AppendRowToDataTable`/`AppendColumnToDataTable`が常に末尾固定(`PositionToAddRow:
  EndOfDataTable`/`PositionToAddColumn: LastColumn`)で正しく、潜在バグではなかったことも
  確認した。`Replace*`系4セレクタは知見123の既知のギャップ(早期停止無し等)のため今回も
  意図的に見送った。
  - [x] 💻🖥️ `File.Actions.dll`にも同じ監査手法を適用。
    ✅ **決着(知見136)**: `ReadTextAsList`/`IfFile.DoesNotExist`/`WaitForFile.Deleted`/
    `RenameAddText`/`RenameRemoveText`/`RenameReplaceText`/`RenameChangeExtension`の6件を
    新規結線。副産物として、`rename_add_text()`が実在しない列挙値名(`Prefix`/`Suffix`、
    実機は`BeforeName`/`AfterName`)を仮定していた潜在バグも発見・修正した(幸いまだ
    codegenに結線されていなかったため出荷前に発見できた)。
    ✅ **決着(知見154、decompileで解消)**: `pad2py-fetch-file-dll`でDLL本体を取得し
    decompile、`RenameFilesAction.GetNewFileNameResolver()`から`AddDateTime`/
    `MakeSequential`スキームの正確なアルゴリズムを特定。`RenameAddDateOrTime`/
    `RenameAddCustomDateTime`/`RenameAddSequentialSuffix`/`OverwriteWithSequentialSuffix`
    の4件を新規結線完了。副産物として`rename_add_datetime()`/`rename_make_sequential()`
    (いずれも未結線だった推測実装)の潜在バグ2件(存在しない`Prefix`/`Suffix`、区切り文字
    無し仮定)も発見・修正した。これで`RenameFiles`系(`RenameScheme`列挙の全6パターン)が
    結線完了。
  - [x] 💻🖥️ `Folder.Actions.dll`/`Compression.Actions.dll`にも同じ監査手法を適用。
    ✅ **決着(知見137)**: `Folder.IfFolderExists.DoesNotExist`を発見・結線した
    (`FolderExistsSelector`という名前自体に`"IfFolder"`を含まないため、型名部分一致の
    簡易チェックでは見逃していたと判明——`ActionSelectorBase`を基底型として正しく
    辿る方式に監査手法を統一した)。`Compression.Actions.dll`には`ActionSelector`
    サブクラスが1つも無いことも確認(ZipFiles/UnzipFilesは単一モード)。
    **再確認+`Clipboard.Actions.dll`も新規確認(知見178)**: `Clipboard`(3件)/
    `Compression`(2件)とも兄弟セレクタ0件と確定(`tools/selector_dumps/
    Clipboard_flat_actions.txt`/`Compression_flat_actions.txt`)——これで本プロジェクト
    対象の全モジュールのセレクタ監査(`ActionSelectorBase`一括列挙+フラットアクション
    一括列挙の両方)が完全網羅に到達した。
  - [x] 💻🖥️ `DateTime.GetCurrentDateTime`にも同じ監査で`Current`/`Windows`/
    `CustomOffset`/`CustomTimeZone`(`Local`以外の4モード)が未結線と判明。
    ✅ **決着(知見138)**: 全モードがVM上の直接呼び出しで解明・結線完了
    (`CustomTimeZone`はルックアップテーブルを経由しない別経路だと発見、
    `dump_daemon/pad_codegen/actions/pad_datetime.py`参照)。
  - [x] 💻🖥️ `Database.Actions.dll`に監査を適用。
    ✅ **決着(知見139)**: `Database.Connect.ConnectOracle`/
    `Database.ExecuteSqlStatement.ConnectAndExecute`/`ConnectAndExecuteOracle`の3件を
    新規結線完了(`connect_and_execute()`は`pad_action_lib`側に既に実装済みだったが
    codegen未結線だった)。
  - [~] 💻🖥️ `Web.Actions.dll`/`XML.Actions.dll`/`Cmd.Actions.dll`/`Text.Actions.dll`/
    `Cryptography.Actions.dll`にも監査を適用(知見139と同じ手法)。
    **2026-11-05更新**: `XML`/`Cryptography`は全件結線完了、`Cmd`/`Text`も僅かな
    残課題(下記)を除き完了(知見140-143・148・149)。`Web`のみ組み合わせ爆発のため
    段階的対応中(下記参照):
    - [x] `XML.Actions.dll`(12セレクタ、全件結線完了)。
      ✅ **決着(知見140)**: `GetElementValueAsNumeric`/`AsBoolean`/`AsDateTime`・
      `ExecuteXPathAndGetFirstValueOnly`・`WriteToFile`(非フォーマット)の5件を
      新規結線完了(既存の`get_xml_element_value()`/`execute_xpath_query()`/
      `write_xml_to_file()`が元々対応する引数を持っていたため、呼び分けのみ)。
      ✅ **決着(知見149)**: `GetElementAttribute`の`AsNumeric`/`AsBoolean`/
      `AsDateTime`3兄弟も新規結線完了——`get_xml_element_attribute()`に
      `value_type`引数を新規実装し(`get_xml_element_value()`と変換ロジックを
      共通化)、VM確認済みの`ValueType`列挙値で対応した。
    - [x] `Cmd.Actions.dll`(4セレクタ、全件結線完了)。
      ✅ **決着(知見141)**: `Open`二重発見は単に`Open`/`OpenWithCodePage`が同じ
      `OpenCmdSession`クラスの兄弟セレクタだったと判明(既存結線は前者のみ)。
      `ReadAndSplit`(`Read`の兄弟セレクタ)を新規結線完了。
      ✅ **決着(知見153、decompile+リフレクションで解消)**: `pad2py-fetch-cmd-dll`
      でDLL本体を取得しdecompile、`Encoding`が`Microsoft.Flow.RPA.Desktop.Robin.
      Shared.Runtime.Enums.Encoding`(各メンバーの基底値=Windowsコードページ番号)
      だと特定。`open_cmd_session()`に全150メンバーの`_ENCODING_CODEPAGES`を追加し、
      `chcp`には整数のコードページ番号そのものを送るよう修正。`OpenWithCodePage`を
      新規結線完了。
    - [x] `Text.Actions.dll`(23セレクタ、`RecognizeEntitiesInText`を除き全件結線完了)。
      ✅ **決着(知見142)**: `GetSubtext`系3(`GetText`/`GetSubtextFromStartTo`/
      `GetSubtextFrom`)・`CropText`系2(`CropTextAfterFlag`/`CropTextBetweenFlags`)・
      `JoinText`系2・`SplitText`系2・`ParseText`系3(`Parse`/`RegexParse`/
      `RegexParseForFirstOccurrence`)・`ReplaceText`系1(`ReplaceTextWithRegex`)の
      合計13件を新規結線完了。副産物として既存`GetSubtext`結線が実在しない列挙値名
      (`'AtSpecificCharacter'`/`'SpecificLength'`)を使っていた潜在的な不整合も発見・
      修正した(偶然挙動には影響していなかった)。
      ✅ **決着(知見148)**: `DateTimeToText`系の`FromCustomDateTime`・`ToDateTime`系の
      `ToDateTimeCustomFormat`も新規結線完了——`dotnet_format_to_strftime()`・
      `datetime_to_text()`/`text_to_datetime()`の`custom_format`引数は実は既に実装済み
      だったため、見送る必要は無かった。
    - [x] `Cryptography.Actions.dll`(AES暗号/復号16セレクタ)。
      ✅ **決着(知見143)**: Salt/IV組み合わせ系12件(Encrypt/Decrypt×Text/File×
      UseSalt/UseIV/UseSaltAndIV)を新規結線完了。既存の`encrypt_text()`/
      `encrypt_from_file()`の`use_salt`/`use_iv`引数、`decrypt_text()`/
      `decrypt_to_file()`の`salt`/`iv`引数がそのまま対応できた。実装中に
      `node.output_var`の多重出力での不定動作による自己発見バグも即座に修正した
      (`output_vars`辞書の明示キー指定に変更)。
    - [~] `Web.Actions.dll`(46セレクタ、組み合わせが非常に多いため段階的に対応)。
      ✅ **決着(知見144、Download系12セレクタのうち8件)**: `DownloadFromWeb`クラスの
      `SaveResponse`(ToVariable/ToFile)×`Method`(Get/Post)×`UseCredentials`の
      8組み合わせ(`FileName=SpecifyFullPath`、直接パス指定の場合)を新規結線完了。
      副産物として既存`download_from_web()`の`SaveResponse=ToFile`時に`DownloadedFile`
      出力が常に`None`になる潜在バグも発見・修正した。
      ✅ **決着(知見145、InvokeSoapService系2件)**: `InvokeSoapServiceUseAuth`を
      新規結線完了。結線前のVM確認で、既存結線の`Endpoint`パラメータが実際の
      C#プロパティ名では`Url`だと判明——**「リフレクションのプロパティ名=DSL名」
      という従来の経験則の反例**を発見し、真の根拠は`InputArgumentAttribute.Name`
      (空ならプロパティ名そのまま)だと確定した(今後のVM監査ではこの属性も
      必ず確認すること)。
      ✅ **決着(知見147、InvokeWebService系29セレクタのうち1件)**: `InvokeWebService
      UseAuth`を新規結線完了。調査の結果、全29セレクタが単一の`InvokeWebServiceBase`
      クラスで、`Method`はこのクラス自身の列挙型(9値)であり**基本セレクタの実機
      キャプチャでも既に動的DSLパラメータとして現れている**と判明——`Post`/`Put`
      接尾辞セレクタが`Method`を制限しているのか単なる別UIエントリかは当初確定
      できなかった。
      ✅ **決着(知見150、未確定事項を解消・4件追加)**: 各セレクタクラスの
      `.Arguments`プロパティ(インスタンス化して直接読み取れる、そのセレクタで
      実際にDSLに現れるパラメータ名の一覧)を確認し、`InvokeWebServicePost`/
      `Put`(及び`UseAuth`版)は`Method`が`Arguments`に含まれず**セレクタ自体で
      固定**と確定。4件を新規結線完了——**監査手法として`.Arguments`確認を標準
      手順に追加**(プロパティ存在チェックより確定的な根拠)。
      ✅ **決着(知見151、InvokeWebService系`SaveToFile`接尾辞6件追加)**: `.Arguments`
      監査で`SaveToFile`/`UseAuthSaveToFile`/`SaveToFilePost`/`SaveToFilePut`/
      `UseAuthSaveToFilePost`/`UseAuthSaveToFilePut`が`FilePath`/`DownloadedFile`
      を持ち`Response`系を持たないと確定。`invoke_web_service()`に
      `save_response`/`destination_path`引数を新規実装(知見144の
      `download_from_web()`と同じパターン、`InvokeWebServiceResult.downloaded_file`
      フィールドを初めて実際に設定)し、6件を新規結線完了。
      ✅ **決着(知見152、`DownloadToFolder`/`SaveToFolder`/`Upload`系22件、
      decompile(ilspycmd)で解消)**: `pad2py-fetch-web-dll`でDLL本体を取得し
      ローカルでdecompileして`WebActions.GetDownloadFilePath()`(Content-
      Disposition優先→URL末尾セグメント→ルートはhost+.html、のファイル名自動
      決定)と`FormulateWebRequest()`のmultipart/form-data構築ロジックを特定、
      `_get_download_file_path()`/`_build_multipart_body()`として再現した。
      `DownloadToFolder`系4件・`InvokeWebService*SaveToFolder*`系6件・
      `InvokeWebService*Upload`系12件(`UploadType.FilePath`方式のみ、
      `Binary`は`BinaryObject`型が本プロジェクトに無く見送り)を新規結線完了。
      これでWeb.Actions.dll全46セレクタ中、未結線は`UploadType.Binary`方式のみ。
    監査手法自体(VM上のリフレクション: `ActionSelectorBase`列挙→`ActionName`読み取り→
    所属する`[Action]`属性付きクラスのプロパティ一覧で判別子の意味を特定)は知見139で
    再確認済みで、次回以降も同じ手順で個々のモジュールの結線を進められる。
    **知見145の追記**: プロパティ名を直接DSLパラメータ名として使う前に、そのプロパティの
    `InputArgumentAttribute.Name`(空でなければそれが優先、空ならプロパティ名)も必ず
    確認すること——`Url`→`Endpoint`のような明示的な上書きが実在する。

## C. 構造的・運用上の課題

- [x] 💻 UI要素セレクタ生成が「周辺を含めた一括コピー」時のみ機能する制約のUX改善余地の検討
  (単体コピー時の案内メッセージ強化など、VM不要でできる範囲) — commit 92ac6a4で対応。
  ControlRepositoryデータが一切無い場合、TODOコメントに「広い範囲をコピーし直す」案内を
  直接追加した。
- [x] 💻 ランタイム設計(generator関数+リプレイジャーナル方式、memory: `pad2py_runtime_direction`)への
  移行可否の判断・設計ドキュメント化。Tier1/2結線をやり直さずに済むタイミングを見極める —
  `design/runtime_architecture_decision.md`に記録。判断: 今は着手せず、A/B節の実機キャプチャ・
  結線が一巡してから再検討する(出力形状の変更は116アクション分の結線のやり直しを招くため)。
- [ ] 💻🖥️ `DataTable`表現(列順序を各行の辞書のキー順序で保持する、`datatable.py`モジュール
  docstring参照)が列を行と独立に追跡しないため、「空のテーブルに`AddColumnToDataTable`で
  列を追加した直後に`AddRowToDataTable`で最初の行を`List`形式で追加する」という知見90・91の
  VM検証で繰り返し使ったパターンが、`pad_action_lib`層(Pythonポート)経由では原理的に
  解決不能という構造的課題が知見124で発覚した(詳細は知見124参照)。真に解決するには
  `DataTable`を「列名リスト+行のリスト」を持つ型に再設計する必要があり、`datatable.py`・
  `variables_actions.py`の広範囲に影響する——知見124では`add_row_to_datatable()`を
  「`list`なら既存の列順序に位置対応で追加、列が1件も無ければでっち上げず明示的な
  `ValueError`」に留め、再設計自体は見送った。副産物として、知見90・91・97・98・99・107・111
  等の「Tier1アクションのみからDataTableを組み立てる」実機検証手法が、**実機のPAD自身の
  実行エンジンでのみ検証されており、`pad_action_lib`を経由するcodegen→生成Python実行の
  往復では一度も検証されていなかった**ことも確定した(FilterDataTable/JoinDataTableの
  入力スキーマ自体の確証は正しいが、そのスキーマをPython側のcodegenから実際に組み立てる
  変換のテストカバレッジには大きな穴があった)。
- [ ] 💻 ローカル`main`とGitHub `origin/main`のコミット分岐(履歴相違)の整理 — 複数セッションが
  同じローカル作業ディレクトリに直接コミットし続けている状態の整理(force-push等の破壊的操作は
  ユーザー確認必須)。
  🔍 診断(読み取りのみ、このtick): `git merge-base --is-ancestor origin/main main`が偽——
  単なる「ローカルが進んでいる」ではなく**本当に分岐**している(`git rev-list --left-right
  --count origin/main...main`で92:175、両方とも増え続けている)。origin/mainの先頭は
  `48652dd`(知見54追記、このセッションの前身が以前pushした時点)で止まっている。実際に
  mergeを試す(`--no-commit`含め)診断は**行わなかった**——このリポジトリは複数セッションが
  同時に同じ作業ディレクトリへコミットし続けているため、dry-runでもインデックス/作業ツリーを
  動かすと、別セッションの`git add`/`git commit`が意図せずその中間状態を取り込む実害がある。
  **推奨**: 整理するなら、他セッションの同時コミットを一時的に止めた上で(ユーザーの調整が
  必要)、ユーザー自身が`git merge`/`git rebase`/`push --force`のいずれで整理するかを判断する。
- [x] 💻 **テスト手法の死角の機械的横展開**: 知見129で「実際に`exec()`するテストでも、
  出力変数への代入先の値自体をアサートしていなければ戻り値の型不一致(`None`化)のような
  バグを素通りさせる」という死角を確定させた。
  ✅ **決着(知見130)**: `pad_action_lib`の全`-> None`関数と`pad_codegen`の代入文生成を
  機械的に突き合わせ、`folder_actions.copy_folder()`1件を発見——しかもVM上の直接呼び出しで
  確認したところ、単なる`None`化だけでなく**`Destination`パラメータの意味論自体が実機と
  逆**(コピー先の正確なパスではなく既存の親フォルダで、結果は`Destination/<元の名前>`に
  ネストされる)という、知見129より一段深刻なバグだった。両方を修正済み。
  - [x] 💻🖥️ `Folder.Move`も同様に`Destination`意味論を取り違えている可能性。
    ✅ **決着(知見131)**: VM上で`MoveFolder`クラスを直接確認し、`Folder.Copy`(知見130)と
    全く同じ「既存の親フォルダへ同名でネスト」パターンだったと確認・修正した。
    `Folder.*`モジュール内の`Destination`系パラメータはこれで出尽くした
    (`Rename`/`Create`/`Delete`/`Empty`は対象外)。

## D. 【新規発見・2026-11-06】未着手の対象モジュール(スコープ拡張の要否はユーザー判断が必要)

A/B/C節の既知項目が3tick連続で進展無しだったため、プロジェクト全体のモジュール網羅状況を
`README.md`の知見ログ要約と照らし合わせて再確認した(知見184)。以下は技術的TODOというより
**スコープそのものの判断**(拡張するかどうか)なので、他の項目と異なりユーザーの意思決定を
待つ。実装はまだ一切していない。

- [x] 🔍 **`Display.ShowMessageDialog`(メッセージボックス表示)が本プロジェクト最初の
  実機キャプチャ(知見1、design/g1_g2_verification_result.md)でありながら一度も`pad_codegen`
  に結線されていなかった**(知見185で実装・結線完了)。`Microsoft.Flow.RPA.Desktop.Modules.
  Display.Actions.dll`をdecompileし、`ShowMessage`(`CloseAutomatically=False`固定)を
  `ctypes.windll.user32.MessageBoxW`で確定的に再現する形で実装した。Win32標準`MessageBox`の
  ボタンID(OK=1等)がPAD実機の`FormMessageBox`のDialogResultと完全一致することをdecompileで
  確認済み。兄弟セレクタ`ShowMessageWithTimeout`(タイムアウト時の挙動が標準API/未documented
  APIいずれでも忠実に再現不能なため)は`NotImplementedError`のまま意図的に未実装。
  同tick内の追補で`Display.SelectFolder`(`SelectFolderDialog`、フラットなaction、
  標準`FolderBrowserDialog`→`tkinter.filedialog.askdirectory()`で1対1対応)も実装・
  結線済み。残る兄弟アクションは知見186で個別精査し、今回は全て見送った:
  - `InputDialog`: **`action_id`自体が未確定**(`Name`/`Id`属性どちらも無いフラットな
    action——知見162/179で確認済みの「`Id`無ければ`Name`がEffectiveId」ルールの対象外で、
    「どちらも無ければクラス名がEffectiveId」というフォールバックは未確認)。次にVMが
    空いたタイミングでaction_idをリフレクション確認するのが最優先(ロジック自体は
    `FormInputDialog`を機械的に翻訳できる見込みで労力は小さい)。
  - `SelectFileDialog`: action_id自体は確定可能だが`CheckIfFileExists=False`(既定値)の
    意味論を`tkinter.filedialog`で忠実に再現できるか未確認、生の`comdlg32.
    GetOpenFileNameW`構造体を実機未確認で実装するのはリスクが高いため見送り。
  - `SelectFromListDialog`: `LimitToList`/`AllowMultiple`/`PreSelectItemsWithPlus`/
    `AllowEmpty`が複雑に絡み合い、単一の標準ウィジェットに対応しない(独自UI構築が必要)。
  - `SelectDateDialog`: カレンダーピッカーが標準ライブラリに無く、新規の
    サードパーティ依存(`tkcalendar`等)が必要。
  - `ShowCustomDialog`: JSON Adaptive Cardレンダリングで本プロジェクトの対象範囲外。

  新規発見した`Microsoft.Flow.RPA.Desktop.Modules.System.Actions.dll`は未調査のまま
  次回以降に残す。
- [x] 🔍 **【ユーザー判断が必要】丸ごと未着手の可能性があるPAD標準モジュール群**: `Email`
  (SMTP送受信)・`Outlook`(ライブCOM経由)・`FTP`/`SFTP`・`Printer`・`Registry`・
  `Remote Desktop`(`UseDesktop`等の一部のみ既知)・`Terminal`(VT)・`System`/`Run application`
  (プロセス起動・管理)。`design/pad_todo.md`・`README.md`のいずれにも「対象外」として明示的に
  記載された形跡が無く、除外の意思決定がされたのではなく単に未調査の可能性が高い。
  **これらを本プロジェクトの対象スコープに加えるかどうかは、個々の技術的判断ではなく
  プロジェクト方針の決定であるため、着手せずユーザーへの申し送りとする。**
  → **2026-11-10、ユーザーが`Outlook`のみ明示的にスコープ拡大を指示**(M365ライセンス
  確保・`pad2py-pad-host`へのOffice/Outlookインストール後)。知見208で実装完了(decompile
  ベース、7系統14 action_id、実機未確認)。`Email`/`FTP`/`SFTP`/`Printer`/`Registry`/
  `Remote Desktop`/`Terminal`/`System`は依然ユーザー判断待ちのまま未着手。
- [ ] 🖥️ **`Outlook`モジュールの実機DSLキャプチャ・round-trip確認(知見208)**: 現在の
  実装は全てdecompile(`Microsoft.Flow.RPA.Desktop.Modules.Outlook.Actions.dll`)ベースの
  推定で、実機未確認。VMが空いてOutlookへの実際のサインインが済んだタイミングで、
  知見75の往復確認手法を使い、14 action_id全てのDSL文字列・パラメータ名・
  `ToContains`のBcc除外仕様(decompile確認済みだが実機未確認)を実証確認する。

## VM(`pad2py-pad-host`)使用時の協調ルール

複数のClaudeセッションがこのリポジトリを共有しているため、🖥️付きタスクに着手する前に毎回:

1. `ListAgents`で現在アクティブな(`busy`/`interactive`状態の)他セッションを確認する。
2. PAD/pad2py関連と思われるセッションがあれば、VMを使う前に`SendMessage`で一声かけ、
   使用中でないことを確認してから着手する(無応答の場合は短時間待ってから、競合リスクを明示した上で
   慎重に進める)。
3. VM側でも`query session`(WinRM経由)や関連プロジェクトディレクトリの最近の更新時刻を見て、
   他セッションが実際に接続中でないかを確認する。
4. VM非依存の作業(ドキュメント整備・テスト追加・ローカルcodegen改善)を既定の「次のゴール」とし、
   VM実機作業は「VMが空いていそうなタイミングに機会があれば行う」程度の優先度に留める——
   優先度順で次がVM作業だからといって即座に奪いに行かない。
5. 作業は短時間で区切り、使い終わったら(RDP切断・トンネル停止等)速やかに解放する —
   VMを長時間専有しない。
6. GCPトンネル(WinRM/RDP)が低メモリ等で終了していた場合は、この協調確認を経てから再接続する。
7. `gcloud compute instances reset`やUiPath/PAD関連の共有プロセスの強制終了等、破壊的な操作は
   他セッションの作業を中断するリスクがあるため、ユーザーへの確認を必須とする。
