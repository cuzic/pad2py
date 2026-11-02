# 制御dumpスクリプト 技術選定

## 1. 設計上の制約(前提)

- PADのフロー保存形式は非公開で、実用的な一次入力は「コピー&ペースト」機能が出力する行指向テキストDSLのみ(`research_notes/.../01_flow_file_format.md`)。
- PAD実行中の「どのタイミングでどのアクションが走ったか」を外部から正確に知る公式APIは存在しない。
- 変換ターゲットがpywinauto(uiaバックエンド)である以上、キャプチャ側もpywinautoと同じUIAの語彙(AutomationId/ControlType/ClassName等)で記録したほうが、変換時の属性マッピングの揺れが最小になる(`research_notes/.../04_selector_mapping.md`)。
- LLMサンドボックスへの依存は避け、ローカル常駐プロセスとして実行する前提(前段の結論)。

## 2. 同期方式: アクティブマーカー + パッシブイベントのハイブリッド

PADの外から画面を漫然とポーリングするだけでは「どのスナップショットがどのPADアクションに対応するか」を事後的に突き合わせる必要があり、ズレのリスクが高い。そこで、次の2層構成を採る。

### 2.1 アクティブマーカー(主系統)

PADの既存アクションの直後に、ユーザー自身(または半自動の挿入ツール)が **「Run Python script」アクション** を1行追加し、以下のような最小スクリプトを呼ばせる。

```python
# dump_marker.py — PADの Run Python script アクションから呼ばれる極薄クライアント
import sys, requests

def main():
    action_id = sys.argv[1]      # PAD側で %ActionLabel% 等として渡す
    flow_name = sys.argv[2]
    requests.post(
        "http://127.0.0.1:8765/capture",
        json={"action_id": action_id, "flow_name": flow_name},
        timeout=2,
    )

if __name__ == "__main__":
    main()
```

PAD側の「Run Python script」は呼び出しごとに新規インタプリタを起動するため、重い処理(UIAツリー走査・スクリーンショット)をこのスクリプト内でやると実行コストと失敗率が上がる。**重い処理は常駐デーモンに任せ、マーカー側はHTTP POST一発で即座に返す**設計にする。

- 挿入対象: ウィンドウ操作・UI要素操作・待機系アクションの直後(PADのテキストDSLに対して半自動でこの行を挿入するプリプロセッサを別途用意すれば、手作業コストを抑えられる)
- `action_id`: PADのラベル機能、またはDSL上の行番号をそのまま使う(PADの「アクションにラベルを付ける」機能で付与するのが最も確実)

### 2.2 パッシブイベントリスナー(補助系統)

マーカーの間に起きる動的な変化(非同期ロード、仮想化リストの展開、ページ送り後の遅延描画など)を捉えるため、UI Automationのイベント購読を常駐デーモン側で張っておく。

- `comtypes` 経由で `IUIAutomation::AddFocusChangedEventHandler` / `AddStructureChangedEventHandler` を購読し、フォーカス変化・構造変化があるたびに**軽量なイベントログ(ツリー全体ではなく変化箇所のみ)**を追記する
- これは複数トレース比較(フェーズ2)で「終了条件の候補抽出」の裏付けデータとしても使える(前回レポートの該当箇所)

## 3. 常駐デーモンの技術スタック

| 役割 | 採用技術 | 理由 |
| --- | --- | --- |
| HTTPトリガー受信 | `FastAPI` + `uvicorn`(軽量構成なら標準`http.server`でも可) | PAD側マーカーからの同期呼び出しを即時返却しつつ、重い処理をバックグラウンドタスク化できる |
| UIツリー走査 | `pywinauto`(`backend="uia"`) | コード生成ターゲットと属性語彙を一致させる。`top_window().descendants()` を再帰的に辿り、`AutomationId`/`ControlType`/`ClassName`/`Name`/`Rectangle`等を抽出 |
| UIA3 Raw / Electron対応 | `comtypes` 直叩き(`UIAutomationCore.dll`のRawViewWalker) | pywinautoの標準View(Control View)が仮想化リストやElectronアプリで要素を取得できない場合のフォールバック。PAD自身がUIA3 Rawに切り替える場面と同じ条件で切り替える |
| スクリーンショット | `mss` | `pyautogui.screenshot()`よりオーバーヘッドが小さく、高頻度キャプチャに向く。領域指定(アクティブウィンドウの矩形)で容量を抑える |
| アクティブウィンドウ情報 | `pywin32`(`win32gui.GetForegroundWindow` 等) | タイトル・プロセス名・ハンドルの取得 |
| OCRフォールバック | `pytesseract`(必要時のみ) | `Name`属性が取れない要素(カスタム描画コントロール)向け。PADの「Move mouse to text」アクション相当の状況に対応 |
| イベント購読 | `comtypes` + UIA COMインターフェース | フォーカス変化/構造変化の低オーバーヘッドな追跡 |
| 保存形式 | JSON Lines(アクションログ)+ 個別ファイル(UIツリーJSON、PNG) | 後述のIRスキーマに準拠。追記専用でクラッシュ耐性を確保 |

## 4. キャプチャフローの擬似コード

```python
@app.post("/capture")
async def capture(req: CaptureRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(do_capture, req.action_id, req.flow_name)
    return {"status": "queued"}

def do_capture(action_id: str, flow_name: str):
    ts = datetime.utcnow()
    win = get_foreground_window_info()          # win32gui
    tree = dump_uia_tree(win.handle)             # pywinauto -> dict
    shot_path = save_screenshot(win.rect)        # mss
    tree_path = save_ui_tree(tree)
    append_action_record(
        action_id=action_id, flow_name=flow_name, timestamp=ts,
        active_window=win, ui_tree_ref=tree_path, screenshot_ref=shot_path,
    )
```

## 5. 既知のリスクと対応

| リスク | 対応 |
| --- | --- |
| PADの「Run Python script」の呼び出しオーバーヘッドでフロー全体が大幅に遅くなる | マーカー呼び出しは非同期キュー投入のみ(HTTPレスポンスは即時)。重い処理はバックグラウンドタスクで非同期実行し、PAD側の待機時間に影響させない |
| マーカー行の挿入が手作業で漏れる | DSLテキストを半自動で走査し、対象アクション種別の直後に「Run Python script」行を機械的に挿入するプリプロセッサを別途用意する(フェーズ0のタスク) |
| 常駐デーモンのクラッシュでトレースが欠落する | JSON Linesの追記専用ログとし、1アクションごとにフラッシュ。デーモン再起動時は`action_id`の連番ギャップで欠損を検知できるようにする |
| Electron/仮想化リストでpywinautoがツリーを取得できない | UIA3 Raw(comtypes直叩き)への自動フォールバックを`dump_uia_tree`内に実装し、どちらの経路で取得したかを`capture_mode`としてIRに記録する |
| スクリーンショット蓄積によるディスク肥大化 | IR本体には参照パスのみを保持し、古いトレースの生データ(PNG/UIツリーJSON)を定期的にアーカイブ/間引く運用ルールを設ける(前回レポートのリスク対応と同じ) |
