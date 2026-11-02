# pad2py

Power Automate Desktop (PAD) のフローを pywinauto / pyautogui ベースの Python スクリプトへ変換するための調査・設計・技術検証リポジトリ。

## 構成

- `research_notes/`, `reports/` — deep research による技術調査結果(フロー形式、アクションマッピング、セレクタ対応、トランスパイラ設計、画面状態IR、複数トレース統合、LLM活用方式)
- `design/` — アーキテクチャ設計(制御dumpスクリプトの技術選定、IRのJSON Schema草案)、および`ci_verification_findings.md`(実機検証で得られた知見)
- `dump_daemon/` — 制御dumpスクリプトのプロトタイプ実装(UIAツリー走査、スクリーンショット、常駐デーモン、複数トレース比較、comtypes経由のUIA3 Rawフォールバック)
- `tests/` — GitHub Actions (windows-latest) 上で技術的な裏付けを検証するpytestスイート

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
