# GitHub Actions(windows-latest)実機検証で得られた知見

検証対象リポジトリ: https://github.com/cuzic/pad2py
対象ワークフロー: `.github/workflows/windows-ci.yml`

このドキュメントは、`design/control_dump_tech_selection.md` の技術選定を実際にWindows環境(GitHub Actions `windows-latest`ランナー)上で動かして検証した過程で判明した知見をまとめる。ローカルのLinux環境や設計段階の推測だけでは分からなかった、実機固有の挙動が複数見つかった。

## 検証ラウンドの推移

| ラウンド | 結果 | 原因 |
| --- | --- | --- |
| [#1](https://github.com/cuzic/pad2py/actions/runs/41534269092) | 1 failed, 20 passed, 10 errors | `pywinauto.Application.start()`+`top_window()`がプロセスID基準でウィンドウを検索し失敗 |
| [#2](https://github.com/cuzic/pad2py/actions/runs/41534774086) | 1 failed, 20 passed, 10 errors | `Desktop().windows()`(複数形)が返す生の`UIAWrapper`に`.wait()`が存在しない |
| [#3](https://github.com/cuzic/pad2py/actions/runs/41535294869) | 1 failed, 19 passed, 10 errors | `Desktop().window()`(単数形, `WindowSpecification`)の`.wait("visible")`がタイムアウト |
| [#4](https://github.com/cuzic/pad2py/actions/runs/41536000640) | 1 failed, 29 passed, 1 skipped | `daemon.py`が`captured_at`にUNIX epoch floatを書き込みスキーマ適合に失敗(実装バグ) |
| [#5](https://github.com/cuzic/pad2py/actions/runs/41536257572) | 30 passed, 1 skipped | — (第1ラウンド完了) |
| [#6](https://github.com/cuzic/pad2py/actions/runs/41537305578) | 1 failed, 31 passed, 4 skipped | 第2ラウンドで追加した診断print文の日本語が`UnicodeEncodeError`で失敗 |
| [#7](https://github.com/cuzic/pad2py/actions/runs/41537533518) | 1 failed, 32 passed, 3 skipped | ウィンドウ発見直後のコントロールツリー未構築による間欠的失敗(知見7) |
| [#8](https://github.com/cuzic/pad2py/actions/runs/41538097136) | **33 passed, 3 skipped** | — (第2ラウンド完了) |

8回の反復修正を経て、設計した技術スタック(pywinauto uiaバックエンドでのツリー走査、mssでのスクリーンショット、FastAPI常駐デーモン、JSON Schema適合、comtypes経由のUIA3 Rawフォールバックとイベント購読)が実機Windows環境で動作することを確認した。

## 知見1: `pywinauto.Application.start()`+`top_window()`はWindows 11以降で機能しない場合がある

### 症状
```
RuntimeError: No windows for that process could be found
```

### 原因(推測)
`Application.start("notepad.exe")`が返すプロセスIDと、実際にウィンドウを所有するプロセスのIDが一致しない。Windows 11以降、Notepadはパッケージ化アプリとして、起動時に別プロセス(ホストプロセス)へのリダイレクトが発生していると推測される。`top_window()`は内部で`findwindows.find_elements(process=self.process, ...)`という**プロセスID基準**の検索を行うため、起動元プロセスのPIDではウィンドウが見つからない。

### 設計への反映
PAD→Python変換で生成されるコードが、起動したアプリのウィンドウを`Application.start()`+`top_window()`で取得する実装になっていると、同様の問題が本番環境でも発生しうる。**生成コード側でも、プロセスID基準ではなく、タイトル/クラス名などの属性基準でウィンドウを検索する設計(`Desktop().window(title_re=...)`等)を既定のテンプレートとすべき**。これは `dump_daemon/daemon.py` の `_get_foreground_window()` が元々採用していた設計方針(フォアグラウンドウィンドウ取得)の正しさを裏付ける結果でもある。

## 知見2: `Desktop().window()`(単数)と`Desktop().windows()`(複数)でデフォルトの可視性フィルタが異なる

### 症状
`Desktop(backend="uia").windows(title_re=".*Notepad.*")`(複数形)は即座にウィンドウを検出できるが、`Desktop(backend="uia").window(title_re=".*Notepad.*").wait("visible", timeout=15)`(単数形)は一貫してタイムアウトする。

### 原因(推測、未確定)
pywinautoのソースコード(`pywinauto/__init__.py`)を確認した結果、`Desktop.windows()`は`visible_only=False, enabled_only=False`を明示的にデフォルト指定しているが、`Desktop.window()`はこれらを指定せず、内部の`find_elements`のデフォルト挙動に委ねている。このCI環境のNotepadウィンドウが、UIA上で一時的に(あるいは恒常的に)`IsVisible=False`を報告している可能性が高い。パッケージ化アプリのホスティング挙動(`ApplicationFrameHost`的な仕組み)によるものと推測されるが、確定的な原因特定には至っていない。

### 回避策(採用した設計)
1. `Desktop().windows(title_re=...)`(可視性フィルタなし)で確実にウィンドウを検出する
2. 見つかったウィンドウの`handle`を使って`Desktop().window(handle=...)`に包み直し、`.wait()`/`.child_window()`等の便利メソッドが使える`WindowSpecification`を得る(handleベースの解決は可視性フィルタの影響を受けない)

### 設計への反映
制御dumpスクリプトおよび変換後の生成コードのいずれにおいても、**ウィンドウ検索は常にこの「可視性フィルタなしで発見→handleで再束縛」の2段階方式を既定とする**べきである。単純に`.window(title_re=...)`を直接使うテンプレートは、本番の業務アプリでも同様の問題を起こすリスクがある。

## 知見3: UIAフォーカス変化イベントの購読(A6)は原因未特定のまま不安定

`comtypes`経由の`IUIAutomationFocusChangedEventHandler`登録自体は(別の検証項目A5: RawViewWalkerの子要素列挙)で成功しているが、フォーカス変化イベントハンドラの登録・解除を行う検証(`test_focus_changed_handler_registers_and_unregisters_cleanly`)は、`pytest.skip`にフォールバックする設計にしていたため「原因不明のまま成功扱いにならずスキップ」という状態で終わっている。**これは唯一の未解決項目であり、次回の検証対象とする**(本ドキュメントの「次の検証」参照)。

## 知見4: IRスキーマが要求する`date-time`フォーマットとPythonの`time.time()`の不一致

### 症状
```
jsonschema.exceptions.ValidationError: 1793657889.7574785 is not of type 'string'
```

### 原因
`dump_daemon/daemon.py`の実装バグ。`ir_trace.schema.json`/`ui_tree_snapshot.schema.json`は`captured_at`/`timestamp`を`{"type": "string", "format": "date-time"}`と定義しているが、実装では`time.time()`(UNIX epochのfloat)をそのまま書き込んでいた。

### 対応
`datetime.now(timezone.utc).isoformat()`によるISO 8601文字列に修正。この修正により初めてD1/D2(実キャプチャデータのスキーマ適合)がグリーンになった。**スキーマ設計自体は正しく、実装側のケアレスミスだった**という点で、JSON Schemaを先に固定して実装をその制約下で書く、という開発順序の有効性を裏付けた。

## 第2ラウンド: 残課題の追加検証(A6原因調査、A4/B3/C3/D3-D4)

第1ラウンド完了後、残っていた項目を追加検証した。4回の反復修正([#6](https://github.com/cuzic/pad2py/actions/runs/41537305578), [#7](https://github.com/cuzic/pad2py/actions/runs/41537533518), [#8](https://github.com/cuzic/pad2py/actions/runs/41538097136))を経て、**33 passed, 3 skipped** に到達した。

### 知見5: A6の真因は「CI環境の制約」ではなく実装バグだった

当初「CI環境側の制約で原因不明のままskip」としていたA6(UIAフォーカス変化イベントの購読)は、`-rA`オプションでスキップ理由のトレースバックを可視化したところ、即座に真因が判明した。

```
TypeError: required argument 'handler' missing
```

`IUIAutomation::AddFocusChangedEventHandler`の実際のCOMシグネチャは`(cacheRequest, handler)`の**2引数**だが、実装では`handler`の1引数のみを渡していた。`uia.AddFocusChangedEventHandler(None, handler)`に修正したところ、実際にフォーカス変化イベントが発火することまで確認できた(`[A6] focus changed events observed: 1`)。**「CI環境のせいで分からない」と早期に判断せず、まず診断情報(トレースバック)を可視化することが原因特定への最短路だった**という教訓。

### 知見6: `-s`オプション使用時、WindowsランナーのデフォルトコンソールコードページはUTF-8ではない

`print()`で日本語の診断メッセージを出力する検証を追加した際、`UnicodeEncodeError: 'charmap' codec can't encode characters`で失敗した。pytestの`-s`(出力キャプチャ無効化)はPythonの標準出力を直接Windowsコンソールに書き込むため、ランナーの既定コードページ(UTF-8ではない)の影響を受ける。`PYTHONUTF8=1`環境変数で解決した。**制御dumpスクリプトやPAD→Python変換後の生成コードが、ログや診断メッセージに日本語を含む場合、Windows実行環境では明示的にUTF-8モードを強制する必要がある**ことを示す実例。

### 知見7: ウィンドウ発見直後は内部コントロールツリーが完全に構築されていない場合がある(間欠的事象)

`test_dump_uia_tree_extracts_expected_attributes`が1回だけ間欠的に失敗し(`['Window', 'StatusBar', 'Text', 'Text', ...]`で編集領域のControlTypeが見つからない)、再実行では成功した。ウィンドウのハンドル解決に成功した直後、OS側の内部コントロールツリー構築が追いついていないタイミングでUIAツリーを走査すると、不完全なスナップショットになる競合状態があると推測される。`descendants()`の件数が安定するまで短時間(最大5秒)ポーリングしてから返す設計に修正し、再発しなくなった。**制御dumpスクリプト本体も、ウィンドウ発見直後に即座にキャプチャするのではなく、同様の安定化待ちを入れるべき**。

### 知見8: UIA仮想化リストは、今回のCI環境では実際には問題にならなかった

D3/D4(大規模ツリーでの頑健性)として、80個のファイルを含むフォルダーをエクスプローラーで開いて検証したところ、**199要素が取得でき、ファイル数80を上回った**(各ファイル行がアイコン・名前テキスト等の複数のUIA要素に分解されるため)。研究フェーズで指摘していた「UIA仮想化リストにより画面外の行が実体化されない」という懸念は、少なくともこのCI環境のエクスプローラーでは再現しなかった。これは**「問題が起きなかった」という結果自体が一つの検証結果**であり、より大規模(数百〜数千件)なリストや、エクスプローラー以外のアプリ(カスタムグリッドコントロール等)では依然として再現する可能性があるため、「安全」と結論づけるのは早計である。

### 検証未完了の項目(ランナー環境の制約によりツール自体が無かったもの)

| 項目 | 状態 | 理由 |
| --- | --- | --- |
| A4: Electron/Chromium系アプリでのpywinauto標準View検証 | 未検証 | `code`(VSCode)、`msedge`(Edge)のいずれも`windows-latest`ランナーのPATH上に見つからなかった。ワークフローに明示的なインストール手順を追加しない限り検証不可 |
| B3: pytesseract OCRフォールバック | 未検証 | `tesseract`バイナリがランナー上に見つからなかった。同上、明示的インストールが必要 |

これらは「CI環境では検証できなかった」という結果であり、「問題がある/ない」の判断材料ではない。本格的に検証する場合は、ワークフローに`choco install tesseract vscode`等のインストールステップを追加する必要があり、それ自体が本来の目的(実機での技術的実現可能性の検証)からやや外れたインフラ構築作業になるため、今回はスコープ外とした。

### 検証で得られた定量データ

- **C3(キャプチャレイテンシ)**: 10回のサンプリングで平均103.4ms、最小93.7ms、最大109.9ms(応答が即時返却されることの定量的確認。生データは`latency_stats.json`としてCIアーティファクトに保存)
- **D3/D4(大規模ツリー)**: 80ファイルのフォルダーで199要素を正常に取得・スキーマ検証をパス

## 検証不可能な項目(CI環境そのものの構造的制約)

| 項目 | 状態 | 理由 |
| --- | --- | --- |
| G1/G2: PAD本体の「Run Python script」アクションからの実際のマーカー同期 | CI不可 | PADはMicrosoftアカウントへのサインイン・ライセンスが必要で、GitHub Actionsの無人ランナーでは検証不可能。ローカル実機でのみ検証可能 |
| G3: マルチモニタ・DPIスケーリング | CI不可 | ランナーは単一仮想ディスプレイのため再現不可 |
