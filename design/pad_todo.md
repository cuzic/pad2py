# PAD→Python変換: 残課題ToDo

このファイルはPAD(Power Automate Desktop)→Python変換トラックの残課題を追跡するためのもので、
UiPathトラック(`design/uipath_transpiler_roadmap.md`等)とは別管理。各項目は完了したら`[x]`に変更し、
関連コミット・知見番号を追記する。複数セッションが並行してこのリポジトリを編集するため、
チェックを入れる際は直前に`git pull`相当(fetch済みの最新状態)を確認してからにする。

- 判断基準(優先度ではなく「今すぐ着手できるか」の目印):
  - 🖥️ = PAD実機VM(`pad2py-pad-host`)でのRDP/WinRM操作が必要
  - 💻 = ローカル(パーサー/codegen/テスト)のみで完結、VM不要

## A. codegenの既知TODO(33/186分岐点、理由は特定済み)

- [ ] 💻🖥️ CSVヘッダー無しケース(`FirstLineContainsColumnNames: False`)の実機確認→`pad_action_lib.datatable`の
  ヘッダー無しモード対応。`File.ReadFromCSVFile`/`WriteToCSVFile`/`Variables.ConvertDataTableToCSV`/
  `GenerateDataTableFromCSV`が対象。実機で列名の既定規則(`Column1`等?)を確認するまでコードは書かない。
- [ ] 🖥️ `Variables.FilterDataTable`/`JoinDataTable`の条件/結合キー指定方法を実機で確認(スキーマ未確認のため
  現状`NotImplementedError`)。
- [ ] 🖥️ `Variables.SubtractLists`/`FindCommonListItems`が使うPAD独自比較エンジン
  (`ComparisonCalculator.Compare`)の挙動確認(大文字小文字・型変換ルール)。
- [ ] 🖥️ UI要素系の残り2条件アクション`UIAutomation.IfImage.ExistsOnScreen`/
  `UIAutomation.IfWindowContains.WindowContainsElement`のPython変換ロジック(セレクタ/画像照合の意味論)。
- [~] 💻 ON ERROR/ON BLOCK ERRORの名前付き・複数アームのcodegen結線 — commit (この後のコミット)で、
  知見36の複数アーム構文と知見73の`pad_action_lib`例外タグ(`[Throws]`名=クラス名)を
  `dump_daemon/pad_codegen/error_tags.py`で対応付け、タグ名が既知の場合は実際の
  `except <クラス>:`(同名タグが複数ファミリーに独立定義されている場合はタプルで全て捕捉)
  に変換するようにした——VM不要、既存の確認済み知識の組み合わせのみで実装。ただし
  既存の唯一の実機フィクスチャ(知見36、`RunPythonScriptError`)は`Scripting`系の
  タグで`pad_action_lib`のスコープ外のため今も`# TODO`のまま(想定通り)。
  🖥️ 残課題: `codegen_coverage.py`のerror_handlingバケット(8/16)を実際に動かすには、
  `pad_action_lib`で結線済みのタグ(`CopyFileError`等)を使う`ON ERROR <TagName>`の
  実機キャプチャが別途必要。
- [ ] 💻🖥️ `pad_expr`(Lark式パーサー)の演算子優先順位・結合性を実機で確認し、確認できたら
  `pad_codegen`を`RawExpr`丸ごとTODOから実際のPython式生成へ切り替える。複合式(`AND`/`OR`/算術混在)の
  実例を複数実機コンパイルして優先順位の違いが出るケースを探す。
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
- [ ] 🖥️ 型混在の`+`(数値+文字列等)のディスパッチルール(`ExpressionCalculator`/`CalculatorBase<T>`)調査。
- [ ] 🖥️ Tier3(Excel/Word/PowerPoint/PDF)アクションの実機DSLキャプチャ・codegen結線 —
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
