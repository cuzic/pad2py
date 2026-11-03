# G1/G2検証手順書: PADの「Run Python script」アクションからのマーカー同期

前提: `design/control_dump_tech_selection.md`のアクティブマーカー方式、`design/ci_verification_findings.md`知見10(dump_daemonの対話的セッション内起動)。本ドキュメントは、実際にPower Automate Desktop (PAD) を使って検証する際の具体的な手順をまとめる。

## 前提条件(2026-11-03時点のステータス)

- [x] GCP Windows VM(`pad2py-pad-host`)構築済み
- [x] Tailscale経由でのclipwire接続確立済み
- [x] PAD インストール済み(WinRM経由、サイレントインストール)
- [x] `dump_daemon`を対話的セッション内(clipwire経由)で起動し、`/capture`の実キャプチャ成功を確認済み
- [ ] PADへのMicrosoftアカウントサインイン(**人間の手動操作が必須、進行中**)
- [ ] G1/G2本検証(本ドキュメントの対象)

## 検証の目的

PADの「Run Python script」アクションから、`dump_daemon`の`/capture`エンドポイントへ実際に同期トリガーを送れるか、またその際のタイミング・信頼性を実機で確認する。

## 手順

### 1. マーカークライアントスクリプトの配置

`design/control_dump_tech_selection.md` 2.1節のマーカークライアント(`dump_marker.py`)を、PADから呼び出し可能な場所に配置する。

```python
# C:\Users\tomoya_kaw\pad2py\dump_marker.py
import sys
import urllib.request
import json

def main():
    action_id = sys.argv[1]
    flow_name = sys.argv[2]
    body = json.dumps({"action_id": action_id, "flow_name": flow_name}).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:8765/capture",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=2)

if __name__ == "__main__":
    main()
```

(標準ライブラリのみで実装し、PAD側のPython実行環境に`requests`等の追加パッケージが無くても動くようにする。)

### 2. 最小のテストフローをPADで作成する

PADコンソールで新しいフローを作成し、以下のアクションを順に追加する。

1. `Display message`(メッセージ表示) — ダミーの最初のアクション
2. `Run Python script` — `dump_marker.py "action1" "g1g2_test_flow"` を呼び出す(PADの「Run Python script」アクションのパラメータとして、スクリプトパスと引数を設定)
3. `Wait` — 1秒待機
4. `Run Python script` — `dump_marker.py "action2" "g1g2_test_flow"` を再度呼ぶ

### 3. フローを実行し、キャプチャ結果を確認する

フロー実行後、`C:\Users\tomoya_kaw\pad2py\capture_output\actions.jsonl` に2件のレコード(`action1`, `action2`)が追記されているかを、clipwire経由で確認する(`dump_daemon/clipwire_client.py`を使うか、本検証で使った手動のregister/execパターンを踏襲する)。

### 4. 確認すべき項目

| 項目 | 確認方法 |
| --- | --- |
| マーカー呼び出しがPADの実行を妨げない(非同期であること) | フロー全体の実行時間が、マーカー無しの同フローと比べて大きく変わらないこと |
| `action_id`がPAD側で指定した値と一致する | `actions.jsonl`の`action_uid`フィールドを確認 |
| キャプチャのタイミングがPADのアクション実行と対応している | `timestamp`フィールドと、PADの実行ログ(あれば)を突き合わせる |
| UIツリー・スクリーンショットが実際の画面内容を反映している | `ui_tree_ref`/`screenshot_ref`先のファイルを目視確認 |
| PADの「Run Python script」アクションの実行オーバーヘッド | 複数回実行して呼び出しごとの所要時間を記録(design文書のリスク「PADの呼び出しオーバーヘッドでフロー全体が遅くなる」の実測) |

### 5. 既知のリスクと確認ポイント

- PADの「Run Python script」アクションが、指定したPythonインタプリタ(`C:\Users\tomoya_kaw\pad2py\.venv\Scripts\python.exe` 等)を正しく使えるか確認する(2026年のPAD機能「任意のローカルPythonバージョン実行」に依存)。
- PAD自体のウィンドウ(PADランタイム/コンソール)が、`dump_daemon`の`_get_foreground_window()`によるキャプチャ対象として誤って捉えられる可能性がある(知見10のフォローアップ課題)。このテストで実際に問題になるか確認する。
