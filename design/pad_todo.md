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
- [ ] 🖥️ ON ERROR/ON BLOCK ERRORの名前付き・複数アーム(8/16)の実機再確認とcodegen結線。
- [ ] 💻🖥️ `pad_expr`(Lark式パーサー)の演算子優先順位・結合性を実機で確認し、確認できたら
  `pad_codegen`を`RawExpr`丸ごとTODOから実際のPython式生成へ切り替える。複合式(`AND`/`OR`/算術混在)の
  実例を複数実機コンパイルして優先順位の違いが出るケースを探す。
- [ ] 🖥️ `Cryptography.*`/`Compression.*`のDPAPI`Sensitive`引数 — 恒久的に非対応と結論済みだが、
  「暗号化環境自体を模倣してテストする」余地があるか再検討(低優先度、現状は見送り)。

## B. 一度も実機検証していない領域(TODOより深い穴)

- [ ] 🖥️ **`IfFunctionRecord`(Contains/Does not contain/Is empty等)の初回実機キャプチャ** — 優先度最高。
  パーサー上の型はdecompile推定のみで実機DSLキャプチャ・codegen結線がゼロ。`Robin.Engine.dll`内の
  実装クラス位置も未特定。日常的な使用頻度が高いと見込まれる。
- [ ] 🖥️ `VariableTrailer`の引数付きトレーラ(`.Name (args)`)を実際に生成するPAD機能の特定。
- [ ] 🖥️ 型混在の`+`(数値+文字列等)のディスパッチルール(`ExpressionCalculator`/`CalculatorBase<T>`)調査。
- [ ] 🖥️ Tier3(Excel/Word/PowerPoint/PDF)アクションの実機DSLキャプチャ・codegen結線 —
  `pad_action_lib`には純粋関数実装(openpyxl/python-docx/python-pptx/pdfium)が既にあるが、
  action_id/パラメータ名の実機確認・codegenへの結線は未着手。

## C. 構造的・運用上の課題

- [x] 💻 UI要素セレクタ生成が「周辺を含めた一括コピー」時のみ機能する制約のUX改善余地の検討
  (単体コピー時の案内メッセージ強化など、VM不要でできる範囲) — commit 92ac6a4で対応。
  ControlRepositoryデータが一切無い場合、TODOコメントに「広い範囲をコピーし直す」案内を
  直接追加した。
- [ ] 💻 ランタイム設計(generator関数+リプレイジャーナル方式、memory: `pad2py_runtime_direction`)への
  移行可否の判断・設計ドキュメント化。Tier1/2結線をやり直さずに済むタイミングを見極める。
- [ ] 💻 ローカル`main`とGitHub `origin/main`のコミット分岐(履歴相違)の整理 — 複数セッションが
  同じローカル作業ディレクトリに直接コミットし続けている状態の整理(force-push等の破壊的操作は
  ユーザー確認必須)。

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
