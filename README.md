# pad2py

Power Automate Desktop (PAD) のフローを pywinauto / pyautogui ベースの Python スクリプトへ変換するための調査・設計・技術検証リポジトリ。

## 構成

- `research_notes/`, `reports/` — deep research による技術調査結果(フロー形式、アクションマッピング、セレクタ対応、トランスパイラ設計、画面状態IR、複数トレース統合、LLM活用方式)
- `design/` — アーキテクチャ設計・実機検証knowledge一式(下記「主要ドキュメント」参照)
- `dump_daemon/` — 制御dumpスクリプトのプロトタイプ実装
  - `uia_capture.py` / `screenshot.py` / `daemon.py` — UIAツリー走査・スクリーンショット・常駐HTTPデーモン
  - `raw_fallback.py` — comtypes経由のUIA3 Rawフォールバック
  - `trace_compare.py` — 複数トレース比較(ループ本体・ループ変数抽出)
  - `clipwire_client.py` — clipwire(対話的セッション内実行デーモン)のHTTPクライアント
  - `pad_dsl_parser.py` — PADクリップボードDSLのパーサー(実データで検証済み)。SET/IF+ELSE IF+ELSE(ネスト対応)/LOOP(カウント・FOREACH・WHILE)/EXIT・NEXT LOOPを`indent`情報付きのフラットな`Record`列に変換し、`build_block_tree()`で`BlockNode`/`ConditionalNode`の木構造に組み立てる
  - `pad_codegen.py` — `build_block_tree()`の出力からPythonソースを生成する最小限のコードジェネレーター(プロトタイプ)。未対応のアクションは架空のAPI呼び出しをでっち上げず`# TODO`コメントを出力する
  - `pad2py_cli.py` — `parse_dsl()`→`build_block_tree()`→`generate_python()`を1コマンドで結ぶCLIエントリポイント(下記「CLIの使い方」参照)
  - `pad_ui_helpers.py` — PAD UI自動化のための pywinauto ヘルパー(G1/G2検証で実証済み)
- `tests/` — GitHub Actions (windows-latest) 上で技術的な裏付けを検証するpytestスイート

## CLIの使い方

PADのデザイナーで変換したいアクション群を選択して**コピー**し、そのクリップボードテキストを`pad2py`コマンドに渡す(PADのフロー定義ファイルを直接読む機能ではない——理由は後述の「v1スコープ」参照)。

```bash
uv sync --all-groups

# クリップボードテキストをファイルに保存して変換
uv run pad2py flow_snippet.txt -o converted.py

# 標準入力・標準出力でパイプ処理(macOS/Linuxでクリップボードから直接流し込む例)
pbpaste | uv run pad2py > converted.py   # macOS
xclip -o -selection clipboard | uv run pad2py > converted.py   # Linux
```

変換できない構文・アクション(知見18-2の関数呼び出し条件等)は例外を送出し、変換できないアクション(UI要素セレクタが必要なもの等、下記「v1スコープ」参照)は出力中に`# TODO`コメントとして残る——いずれも、架空のPython APIをでっち上げて出力することは無い。

## UI要素セレクタについて(v1時点の状況)

PADのUI automationアクション(`Click UI element in window`等)は、DSLクリップボードテキスト上では`appmask['<表示名>']`というUI要素リポジトリへの名前参照でしか現れない(design/dsl_format_findings.md 知見38)。**1〜4個程度のアクションだけを個別にコピーした場合**、実際に自動化を動かすために必要なセレクタの実体はクリップボードに含まれず、PADデザイナーUI・ローカルキャッシュ・クラウド保存後のポータルのいずれからも取得できなかった(知見39・42・43)。

しかし知見44で判明した通り、**対象アクションを含む範囲を一括選択してコピーすると、クリップボードテキストの末尾にUI要素リポジトリ全体(`# [ControlRepository][PowerAutomateDesktop]`セクション)がJSONとして同梱される**。`pad_dsl_parser.py`の`parse_control_repository()`でこれをパースでき、`parse_dsl()`自身もこのセクションを自動的に読み飛ばすため、一括コピーしたテキストをそのまま`pad2py`に渡しても壊れない。**変換したいアクションは、単体ではなく周囲を含めてまとめてコピーすることを推奨する**(個別コピーだと今でもセレクタ無しのTODOになる)。

知見46で、一般的なアプリ内コントロール(メモ帳のテキスト編集領域)の`Attributes`配列の中身も実機確認できた(`Class`/`Name`/`Process`等、pywinautoの`class_name`/`title`等にほぼ1対1対応する語彙)。対象が別ウィンドウの子孫の場合は`appmask['<祖先>']['<対象>']`のように`['...']`セグメントが複数連なる(`UiElementRef.path`で保持)。ただし確証を持てる実例がまだ2件のみのため、`pad_codegen.py`は現時点では`parse_control_repository()`の結果を実際のpywinautoセレクタ生成には使っておらず、UI要素アクションは引き続き参照パス(`appmask['...']['...']`の各表示名)を含む`# TODO`コメントとして出力する(`_ui_element_hint()`)。でっち上げたセレクタ文字列を埋め込むことは無い。

## 主要ドキュメント

| ドキュメント | 内容 |
| --- | --- |
| [design/control_dump_tech_selection.md](design/control_dump_tech_selection.md) | 制御dumpスクリプトの技術選定・アーキテクチャ |
| [design/ci_verification_findings.md](design/ci_verification_findings.md) | GitHub Actions・実機GCP VM双方での検証知見(知見1〜11) |
| [design/dsl_format_findings.md](design/dsl_format_findings.md) | PADクリップボードDSLの実データによる文法確認(知見1〜52: SET/IF/LOOP系・ネスト構造・UI automationアクションのpywinauto/pyautoguiマッピング・複数出力のバグ修正・文字列エスケープのバグ修正・複数行コメント対応(実機検証済み)・SWITCH/CASE対応(実機検証で構造を訂正)・IN/NOT IN対応・UI要素セレクタの文字列フォーマット解明・Focus/Close window対応・WaitActionカテゴリ発見・ON ERRORブロックの実機検証(構造を訂正)・名前付きケース/複数アーム対応(パーサーバグを修正)・REPEAT ACTION対応・UI要素参照`appmask[...]`の発見(パーサーバグを修正)・PAD「Inspect UI elements」ピッカーで取得したUI要素のPublic Attributes完全一覧・BLOCK/ON BLOCK ERROR/NEXT ACTIONの実機検証とパーサー/codegen実装・THROW ERRORの実機検証・UI要素セレクタ取得の非2FA経路を全て潰し2FA解消が前提条件と確定・2FA承認後クラウド保存に成功するも個人MSAはPower Platformメーカーポータルにアクセス不可と判明(前提の訂正)・一括コピーでUI要素リポジトリJSON(実セレクタ)を発見(本プロジェクト最大の発見)・ネストしたBLOCKのON BLOCK ERRORインデント不一致を発見・UI要素参照の複数階層連結とふつうのコントロールのAttributes語彙を確認(パーサーバグを修正)・LABEL/GOTO(Go to label)の実機検証でON ERROR/ON BLOCK ERROR系の未検証項目を全て解消・IN/NOT IN演算子は標準Ifアクションには存在しないと実機確認・WaitActionカテゴリ(Wait for window)の`WAIT (...) FOR <秒数>`構文を発見しパーサーバグを修正(FOR句省略・ToCloseバリアントも確認)・LOOPのrangeは両端を含まない(Pythonのrange()と同じ終端排除セマンティクス)と実機確認し長年の誤った前提(`range(start, end+1, step)`)を修正・「Wait for window」とは別の新アクション「Wait for window content」(`WindowToContainElement`)を発見しコード変更無しで対応できることを確認まで) |
| [design/robin_language_source_findings.md](design/robin_language_source_findings.md) | PAD実機の内部DLL(Robin Language)を逆コンパイルして文法を一次ソースで裏付けた知見 |
| [design/g1_g2_verification_protocol.md](design/g1_g2_verification_protocol.md) | G1/G2検証の手順書 |
| [design/g1_g2_verification_result.md](design/g1_g2_verification_result.md) | G1/G2検証の結果(PADの「Run Python script」からのマーカー同期に成功) |
| [design/schemas/](design/schemas/) | IR/UIツリーのJSON Schema |

## G1/G2検証: PAD実機での動作確認(成功)

GCP上のWindows VM(`pad2py-pad-host`)にPower Automate Desktopをインストール・サインインし、実際のフロー(Display message → Run Python script → Wait → Run Python script)を作成・実行して、`dump_daemon`の`/capture`エンドポイントへのマーカー同期が機能することを確認した。自動化は`clipwire`(対話的RDPセッション内で動くリモート実行デーモン、`~/powershell-clipd`)経由でpywinautoを駆動して行った。詳細は[design/g1_g2_verification_result.md](design/g1_g2_verification_result.md)。

**運用上の注意**: GUI操作・スクリーンショットを伴う自動化(clipwire経由であっても)は、**RDPクライアントが実際に接続中であること**に依存する(知見11)。セッションが切断されると`click_input()`やスクリーンショットが失敗する。

## CI検証の位置づけ

`.github/workflows/windows-ci.yml` は実際のWindows環境で以下を検証する。最終結果: **33 passed, 3 skipped**(詳細は[design/ci_verification_findings.md](design/ci_verification_findings.md)参照)。

| 優先度 | 検証項目 | 対応テストファイル | 結果 |
| --- | --- | --- | --- |
| P0 | 依存パッケージのインストール(uv) | `tests/test_env.py` | PASS |
| P0 | 対話的デスクトップセッションの存在・画面キャプチャ | `tests/test_screenshot.py` | PASS |
| P0 | pywinautoによる実アプリUIツリー走査 | `tests/test_uia_capture.py` | PASS |
| P0 | 常駐デーモンのHTTP受信・非同期処理 | `tests/test_daemon.py` | PASS |
| P0 | 実キャプチャデータのJSON Schema適合 | `tests/test_schema_validation.py`, `tests/test_daemon.py` | PASS |
| P1 | uia/win32バックエンド差異、安定element_id、UIA3 Rawフォールバック、フォーカス変化イベント | `tests/test_uia_capture.py`, `tests/test_raw_fallback.py` | PASS |
| P1 | 同一実行内でのセレクタ再検出、複数トレース比較ロジック | `tests/test_round_trip.py`, `tests/test_trace_generalization.py` | PASS |
| P1 | キャプチャレイテンシの実測 | `tests/test_latency.py` | PASS(平均103ms) |
| P1 | 大規模ツリーでのスキーマ頑健性 | `tests/test_large_tree.py` | PASS(199要素) |
| P2 | プロセス再起動後のセレクタ再検出 | `tests/test_round_trip.py` | PASS |
| P2 | Electron/Chromium系アプリでの標準View検証 | `tests/test_electron_app.py` | SKIP(対象アプリがランナーに無い) |
| P2 | pytesseract OCRフォールバック | `tests/test_ocr_fallback.py` | SKIP(tesseractバイナリがランナーに無い) |
| G1-G3 | PAD本体連携・マルチモニタ | — | CI不可(ライセンス/単一ディスプレイの制約) |

詳細な知見(間欠的な失敗の原因調査、comtypes COMシグネチャの誤りなど)は[design/ci_verification_findings.md](design/ci_verification_findings.md)を参照。

## ローカルでの実行

```bash
uv sync --all-groups
uv run pytest -v
```

Windows以外の環境では大半のテストがスキップされる(`pytest.mark.skipif`)。
