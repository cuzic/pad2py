# 制御dumpスクリプト 技術選定

> **2026-11-02 改訂**: GitHub Actions (`windows-latest`) 実機でのCI検証(8ラウンドの反復修正、最終結果 33 passed / 3 skipped)で得られた知見を反映した。検証の経緯と根拠は [`design/ci_verification_findings.md`](ci_verification_findings.md) を参照。本改訂での変更点は「2.3 ウィンドウ特定方式」「3の表の訂正」「5のリスク表への追加」「6(新設: 生成コードへの反映)」。
>
> **2026-11-02 追記**: 別プロジェクト `~/rust-nicola`(Windows実機CIでのIME/ウィンドウ操作の先行事例)の知見を反映した。「2.4 ウィンドウ発見方式のさらなる改善(rust-nicola知見)」を新設。

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
- **実機検証で確定した注意点**: `IUIAutomation::AddFocusChangedEventHandler` の実際のCOMシグネチャは `(cacheRequest, handler)` の2引数である。`cacheRequest` を省略して `handler` のみを渡すと `TypeError: required argument 'handler' missing` になる(第1引数に `handler` が渡ってしまい、第2引数`handler`が不足するため)。`cacheRequest` には `None` を渡せばよい。`RemoveFocusChangedEventHandler` は `handler` の1引数のみで正しい。

### 2.3 ウィンドウ特定方式(実機検証で確定)

当初「`pywinauto.Application(backend="uia").start(exe)` → `app.top_window()`」というプロセスID基準の典型パターンを想定していたが、GitHub Actions `windows-latest`(Windows 11ベース)での実機検証で**このパターンは機能しないことが判明した**(`RuntimeError: No windows for that process could be found`)。原因は、Windows 11以降のアプリ(Notepad含む)が起動元プロセスとウィンドウ所有プロセスが一致しない形でホストされる場合があるため。これは制御dumpスクリプトだけでなく、**PAD→Python変換後の生成コードが対象アプリを起動する際にも同じ問題を起こしうる**、本質的な設計変更点である。

実機検証で安定動作を確認した方式は次の2段階:

1. **発見**: `Desktop(backend="uia").windows(title_re=..., ...)`(複数形。`visible_only=False`がデフォルトのため、ウィンドウが一時的に`IsVisible=False`を報告する場合でも検出できる)でプロセスの起動とは無関係にタイトル/クラス名等の属性で対象ウィンドウを探す。戻り値は生の`UIAWrapper`で、`.wait()`や`.child_window()`は使えない。
2. **再束縛**: 見つかったウィンドウの`handle`を使って`Desktop(backend="uia").window(handle=...)`(単数形、`WindowSpecification`)に包み直す。handle基準の解決は可視性フィルタの影響を受けず、かつ`.wait()`/`.child_window()`等の便利メソッドが使えるようになる。

さらに、発見直後は対象ウィンドウの内部コントロールツリー(テキスト編集領域等)がまだ完全に構築されていない場合があることも実機検証で判明した(間欠的に再現)。**ウィンドウを返す前に`descendants()`の件数が数回連続で変化しなくなるまで短時間(目安5秒)ポーリングする「安定化待ち」を標準の手順に含める**。

### 2.4 ウィンドウ発見方式のさらなる改善(rust-nicola知見)

別プロジェクト `~/rust-nicola`(Windows実機CIでのIME/キーボード制御・UIAutomation操作の先行事例、`tools/e2e/wt/wt_vocab.py`)には、2.3節よりもさらに頑健な3つの手法が実装・実運用されている。これらはPAD変換プロジェクトの制御dumpスクリプトおよびコード生成テンプレートの両方に取り込むべき改善である。

**(a) 「起動前後のスナップショット差分」によるウィンドウ発見** — `rust-nicola`はWindows Terminal(パッケージ化アプリ)を制御する際、タイトル文字列の推測ではなく、`EnumWindows`+クラス名フィルタで**起動前の全ウィンドウ一覧を記録**し、起動後に**新規に現れたウィンドウを差分で取得**する(`before = {w["hwnd"] for w in windows()}` → 起動 → `new = [w for w in windows() if w["hwnd"] not in before]`)。この方式は、プロセスIDがウィンドウ所有プロセスと一致しない問題(2.3節)も、タイトル文字列が動的・ローカライズされていて事前に分からない問題も、**両方を同時に回避する**。PADアクション側は対象アプリの正確な起動後タイトルを事前に知らないことが多いため、**本プロジェクトでもこの「差分方式」を既定のウィンドウ発見アルゴリズムとし、タイトル/クラス名による絞り込みは複数の新規ウィンドウを区別する際の補助条件として使う**設計に改める。

**(b) `AttachThreadInput`による前面化の確実化** — `SetForegroundWindow`は呼び出し元スレッドが前景スレッドと異なる場合にOSによって無視されることがあるが、`rust-nicola`は`AttachThreadInput`で呼び出し元スレッドを現在の前景スレッドに一時的にアタッチしてから`SetForegroundWindow`を呼ぶ、という定番の回避策を実装している(`wt_vocab.py::foreground()`)。pywinautoの`.set_focus()`がこの回避策を内部で行っているかは不明なため、**制御dumpスクリプトおよび生成コードの「ウィンドウを前面化する」処理は、pywinautoの`.set_focus()`に加えてこのフォールバックを明示的に実装する**ことを推奨する。

**(c) UIA操作をPowerShell(.NET `UIAutomationClient`)に委譲する選択肢** — 本プロジェクトの実機検証で`comtypes`経由の`AddFocusChangedEventHandler`呼び出しがCOMシグネチャの誤り(`(cacheRequest, handler)`の2引数を要するのに1引数しか渡していなかった)で失敗した(知見5、`ci_verification_findings.md`参照)。`rust-nicola`はPython+comtypesでのUIA直接操作を避け、UIAツリー読み取り(`uia_text()`)やスクリーンショット取得をPowerShellスクリプトにサブプロセスとして委譲し、.NETの型安全な`System.Windows.Automation`名前空間を使っている。.NETのUIAバインディングはCOMシグネチャをラップ済みで引数ミスが起きにくいため、**`dump_daemon`のUIA3 Rawフォールバック・イベント購読部分についても、Python+comtypesでの実装を継続するか、PowerShellサブプロセス委譲に置き換えるかを、A6の安定性が今後問題になった場合の代替案として検討の余地を残す**(現時点ではA6は修正済みで実機検証もPASSしているため、即時の変更は不要)。

## 3. 常駐デーモンの技術スタック

| 役割 | 採用技術 | 理由 |
| --- | --- | --- |
| HTTPトリガー受信 | `FastAPI` + `uvicorn`(軽量構成なら標準`http.server`でも可) | PAD側マーカーからの同期呼び出しを即時返却しつつ、重い処理をバックグラウンドタスク化できる |
| UIツリー走査 | `pywinauto`(`backend="uia"`) | コード生成ターゲットと属性語彙を一致させる。対象ウィンドウは2.3節の「発見→handle再束縛→安定化待ち」の手順で取得した`WindowSpecification`/`UIAWrapper`を`descendants()`で再帰的に辿り、`AutomationId`/`ControlType`/`ClassName`/`Name`/`Rectangle`等を抽出(`Application.start()`+`top_window()`は使わない、2.3節参照) |
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
| Electron/仮想化リストでpywinautoがツリーを取得できない | UIA3 Raw(comtypes直叩き)への自動フォールバックを`dump_uia_tree`内に実装し、どちらの経路で取得したかを`capture_mode`としてIRに記録する。**実機検証メモ**: 80ファイルのエクスプローラーで199要素が取得でき、少なくともそのケースでは仮想化による欠落は再現しなかった。これは「安全」の確証ではなく、より大規模なリストやカスタムグリッド等では依然再現しうるため、フォールバック自体は撤去しない |
| スクリーンショット蓄積によるディスク肥大化 | IR本体には参照パスのみを保持し、古いトレースの生データ(PNG/UIツリーJSON)を定期的にアーカイブ/間引く運用ルールを設ける(前回レポートのリスク対応と同じ) |
| プロセスID基準のウィンドウ検索がWindows 11以降で失敗する(実機検証で新規判明) | 2.3節の「発見(タイトル基準, visible_only=False)→handle再束縛→安定化待ち」を標準パターンとする。`Application.start()`+`top_window()`は使用しない |
| ウィンドウ発見直後、内部コントロールツリーが未構築のまま走査してしまう(実機検証で新規判明、間欠的) | 2.3節の「安定化待ち」(descendants()件数が数回連続で変化しなくなるまでポーリング)を必須手順とする |
| comtypes経由のCOM呼び出しでシグネチャを誤る(実機検証で新規判明。例: `AddFocusChangedEventHandler`) | 実装前に対象メソッドのMicrosoft公式リファレンス(引数の型・個数・省略可否)を必ず確認する。`comtypes`は引数不足を`TypeError`として報告するため、エラーメッセージからも気付けるが、設計レビュー段階で確認するのが望ましい |
| Windowsランナーの既定コンソールコードページがUTF-8でない(実機検証で新規判明) | 日本語等のマルチバイト文字をログ・標準出力に書き込むPythonプロセス(常駐デーモン、マーカースクリプト、将来の生成スクリプトのログ出力)は`PYTHONUTF8=1`環境変数、または`sys.stdout.reconfigure(encoding="utf-8")`を明示する |

## 6. 変換後の生成コードへの反映(コード生成テンプレートへの教訓)

本ドキュメントは制御dumpスクリプト(キャプチャ側)の技術選定が主題だが、2.3節で確定した「ウィンドウ特定方式」は、**PAD→Python変換後に出力される側のPythonコード(変換の最終成果物)にも同じ問題が起こりうる**という点で、コードジェネレータのテンプレート設計そのものに影響する。

具体的には、PADの「ウィンドウを探す」「アプリを起動」系アクションをpywinautoコードへ変換する際、ナイーブに`Application(backend="uia").start(path)` → `app.top_window()`というテンプレートを生成すると、本検証で確認したのと同じ`RuntimeError: No windows for that process could be found`が生成コードの実行時に発生しうる。したがって、**コード生成テンプレートの既定実装は次の形に固定する**べきである(2.4節のrust-nicola知見(a)を踏まえ、タイトルの事前推測が不要な「起動前後の差分」方式を既定とする)。

```python
# 生成コードの既定テンプレート(ウィンドウ発見部分)。タイトル文字列を事前に知らなくても動く。
import subprocess, time
from pywinauto import Desktop

def _snapshot_handles():
    return {w.handle for w in Desktop(backend="uia").windows()}

before = _snapshot_handles()
proc = subprocess.Popen([exe_path])
window = None
for _ in range(60):
    time.sleep(0.5)
    new_handles = _snapshot_handles() - before
    if new_handles:
        # 複数の新規ウィンドウが現れた場合は、既知のタイトル/クラス名パターンで絞り込む
        candidates = [h for h in new_handles
                      if title_pattern is None or title_pattern.search(
                          Desktop(backend="uia").window(handle=h).window_text())]
        if candidates:
            window = Desktop(backend="uia").window(handle=candidates[0])
            break
if window is None:
    raise RuntimeError(f"ウィンドウが見つかりませんでした: exe={exe_path}")
window.wait("exists", timeout=10)
```

これにより、Phase 1(コア変換器)の実装時点から「プロセスID基準の素朴な実装」を避け、実機検証済みのパターンを初期テンプレートとして組み込める。フェーズ2(複数トレース比較)・フェーズ3(ロングテール対応)のロードマップ自体への変更は無いが、**Phase 1のタスクに「ウィンドウ発見テンプレートの実装」を明示的に追加し、本節のコードをベースラインとする**ことを推奨する。
