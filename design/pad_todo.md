# PAD→Python変換: 残課題ToDo

このファイルはPAD(Power Automate Desktop)→Python変換トラックの残課題を追跡するためのもので、
UiPathトラック(`design/uipath_transpiler_roadmap.md`等)とは別管理。各項目は完了したら`[x]`に変更し、
関連コミット・知見番号を追記する。複数セッションが並行してこのリポジトリを編集するため、
チェックを入れる際は直前に`git pull`相当(fetch済みの最新状態)を確認してからにする。

- 判断基準(優先度ではなく「今すぐ着手できるか」の目印):
  - 🖥️ = PAD実機VM(`pad2py-pad-host`)でのRDP/WinRM操作が必要
  - 💻 = ローカル(パーサー/codegen/テスト)のみで完結、VM不要

## A. codegenの既知TODO(26/202分岐点、理由は特定済み——`uv run python3 -m dump_daemon.codegen_coverage`で随時再計測)

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
  の数値コレーション挙動が別途未確認のため`True`の場合のみ)。`TrimFields`の正確な
  意味論は別の未解決課題として残る(低優先度)。
- [ ] 🖥️ `Variables.FilterDataTable`/`JoinDataTable`の条件/結合キー指定方法を実機で確認(スキーマ未確認のため
  現状`NotImplementedError`)。
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
- [ ] 🖥️ UI要素系の残り2条件アクション`UIAutomation.IfImage.ExistsOnScreen`/
  `UIAutomation.IfWindowContains.WindowContainsElement`のPython変換ロジック(セレクタ/画像照合の意味論)。
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
- [ ] 🖥️ `Cryptography.*`/`Compression.*`のDPAPI`Sensitive`引数 — 恒久的に非対応と結論済みだが、
  「暗号化環境自体を模倣してテストする」余地があるか再検討(低優先度、現状は見送り)。

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
- [ ] 🖥️ `VariableTrailer`の引数付きトレーラ(`.Name (args)`)を実際に生成するPAD機能の特定。
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

## C. 構造的・運用上の課題

- [x] 💻 UI要素セレクタ生成が「周辺を含めた一括コピー」時のみ機能する制約のUX改善余地の検討
  (単体コピー時の案内メッセージ強化など、VM不要でできる範囲) — commit 92ac6a4で対応。
  ControlRepositoryデータが一切無い場合、TODOコメントに「広い範囲をコピーし直す」案内を
  直接追加した。
- [x] 💻 ランタイム設計(generator関数+リプレイジャーナル方式、memory: `pad2py_runtime_direction`)への
  移行可否の判断・設計ドキュメント化。Tier1/2結線をやり直さずに済むタイミングを見極める —
  `design/runtime_architecture_decision.md`に記録。判断: 今は着手せず、A/B節の実機キャプチャ・
  結線が一巡してから再検討する(出力形状の変更は116アクション分の結線のやり直しを招くため)。
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
