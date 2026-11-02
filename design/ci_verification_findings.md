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
| [#5](https://github.com/cuzic/pad2py/actions/runs/41536257572) | **30 passed, 1 skipped** | — |

5回の反復修正を経て、設計した技術スタック(pywinauto uiaバックエンドでのツリー走査、mssでのスクリーンショット、FastAPI常駐デーモン、JSON Schema適合)が実機Windows環境で動作することを確認した。

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

## 検証されなかった/できなかった項目(優先度別の現状)

| 項目 | 状態 | 理由 |
| --- | --- | --- |
| A6: フォーカス変化イベントの発火確認 | 未解決(skip) | 登録・解除時に例外が発生し原因未特定。次回調査対象 |
| A4: Electronアプリでのpywinauto標準View失敗確認 | 未実施 | CI環境に対象アプリ(VSCode等)があるか未確認。次回調査対象 |
| B3: pytesseract OCRフォールバック | 未実施 | 検証スイートに未実装。次回調査対象 |
| C3: キャプチャのレイテンシ実測 | 簡易確認のみ(<1秒の assertion) | 具体的な数値が記録されていない。次回調査対象 |
| D3/D4: 深いネスト・大規模ツリーでの頑健性 | 未確認(Notepadは要素数が少ない) | より要素数の多いウィンドウでの検証が必要。次回調査対象 |
| G1/G2: PAD本体の「Run Python script」アクションからの実際のマーカー同期 | CI不可 | PADはMicrosoftアカウントへのサインイン・ライセンスが必要で、GitHub Actionsの無人ランナーでは検証不可能。ローカル実機でのみ検証可能 |
| G3: マルチモニタ・DPIスケーリング | CI不可 | ランナーは単一仮想ディスプレイのため再現不可 |
