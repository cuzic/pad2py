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
  - `pad_ui_helpers.py` — PAD UI自動化のための pywinauto ヘルパー(G1/G2検証で実証済み)
- `tests/` — GitHub Actions (windows-latest) 上で技術的な裏付けを検証するpytestスイート

## 主要ドキュメント

| ドキュメント | 内容 |
| --- | --- |
| [design/control_dump_tech_selection.md](design/control_dump_tech_selection.md) | 制御dumpスクリプトの技術選定・アーキテクチャ |
| [design/ci_verification_findings.md](design/ci_verification_findings.md) | GitHub Actions・実機GCP VM双方での検証知見(知見1〜11) |
| [design/dsl_format_findings.md](design/dsl_format_findings.md) | PADクリップボードDSLの実データによる文法確認(知見1〜33: SET/IF/LOOP系・ネスト構造・UI automationアクションのpywinauto/pyautoguiマッピング・複数出力のバグ修正・文字列エスケープのバグ修正・複数行コメント対応・SWITCH/CASE対応(実機検証で構造を訂正)・IN/NOT IN対応・UI要素セレクタの文字列フォーマット解明・Focus/Close window対応・WaitActionカテゴリ発見まで) |
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
