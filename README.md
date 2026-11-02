# pad2py

Power Automate Desktop (PAD) のフローを pywinauto / pyautogui ベースの Python スクリプトへ変換するための調査・設計・技術検証リポジトリ。

## 構成

- `research_notes/`, `reports/` — deep research による技術調査結果(フロー形式、アクションマッピング、セレクタ対応、トランスパイラ設計、画面状態IR、複数トレース統合、LLM活用方式)
- `design/` — アーキテクチャ設計(制御dumpスクリプトの技術選定、IRのJSON Schema草案)
- `dump_daemon/` — 制御dumpスクリプムのプロトタイプ実装(UIAツリー走査、スクリーンショット、常駐デーモン、複数トレース比較)
- `tests/` — GitHub Actions (windows-latest) 上で技術的な裏付けを検証するpytestスイート

## CI検証の位置づけ

`.github/workflows/windows-ci.yml` は実際のWindows環境で以下を検証する。PAD本体(ライセンス・サインインが必要)が絡む項目はCIでは検証できないため対象外。

| 優先度 | 検証項目 | 対応テストファイル |
| --- | --- | --- |
| P0 | 依存パッケージのインストール(uv) | `tests/test_env.py` |
| P0 | 対話的デスクトップセッションの存在・画面キャプチャ | `tests/test_screenshot.py` |
| P0 | pywinautoによる実アプリUIツリー走査 | `tests/test_uia_capture.py` |
| P0 | 常駐デーモンのHTTP受信・非同期処理 | `tests/test_daemon.py` |
| P0 | 実キャプチャデータのJSON Schema適合 | `tests/test_schema_validation.py`, `tests/test_daemon.py` |
| P1 | uia/win32バックエンド差異、安定element_id、UIA3 Rawフォールバック | `tests/test_uia_capture.py`, `tests/test_raw_fallback.py` |
| P1 | 同一実行内でのセレクタ再検出、複数トレース比較ロジック | `tests/test_round_trip.py`, `tests/test_trace_generalization.py` |
| P2 | プロセス再起動後のセレクタ再検出 | `tests/test_round_trip.py` |

詳細な優先度付けと検証不可能な項目(PAD本体が絡む部分、マルチモニタ等)の一覧は会話記録を参照。

## ローカルでの実行

```bash
uv sync --all-groups
uv run pytest -v
```

Windows以外の環境では大半のテストがスキップされる(`pytest.mark.skipif`)。
