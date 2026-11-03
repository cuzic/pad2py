# G1/G2検証結果: PADの「Run Python script」アクションからのマーカー同期(成功)

`design/g1_g2_verification_protocol.md`に基づく検証を実施し、**成功**した。実施日: 2026-11-03。

## 結果サマリ

実機(`pad2py-pad-host`, GCP Windows VM)上でPower Automate Desktopにサインインし、テストフロー`g1g2_test`(Display message → Run Python script(action1) → Wait 1秒 → Run Python script(action2))を作成・実行した。`capture_output/actions.jsonl`に両マーカーが正しい順序・間隔で記録された。

```json
{"action_uid": "action1", "flow_name": "g1g2_test", "timestamp": "2026-11-03T02:13:51.404440+00:00", ...}
{"action_uid": "action2", "flow_name": "g1g2_test", "timestamp": "2026-11-03T02:13:54.868715+00:00", ...}
```

両者の間隔は約3.46秒で、Wait(1秒)+PAD側のアクション遷移オーバーヘッドと整合している。

証拠スクリーンショット: [`evidence/g1_g2/01_flow_with_4_actions.png`](evidence/g1_g2/01_flow_with_4_actions.png)(4アクション構成)、[`02_running_message_dialog.png`](evidence/g1_g2/02_running_message_dialog.png)(実行中、Display messageダイアログ)、[`03_completed_status_ready.png`](evidence/g1_g2/03_completed_status_ready.png)(実行完了、Status: Ready)。

## 重要な訂正: 「Run Python script」アクションの実際の仕様

事前の`g1_g2_verification_protocol.md`では「スクリプトファイルパス+引数」を指定する方式を想定していたが、**実際は異なっていた**。

- アクションのパラメータは、**Pythonコード本体を直接貼り付けるコードエディタ**(AvalonEdit製、aid=`TextEditor`/`SyntaxHighlightingEditor`)
- 「Python engine:」ドロップダウンがあり、選択肢は **`IronPython 2.7 (built-in)`(デフォルト)、`IronPython 3.4 (built-in)`、`CPython (3.7+)`** の3つ
- `CPython (3.7+)`を選ぶと「Python installation path:」欄が追加表示され、`python.exe`への絶対パス指定が必須になる
- **デフォルトはIronPython 2.7**であり、`urllib.request`等のPython 3標準ライブラリは使えない。CPython 3系の構文・標準ライブラリに依存するマーカースクリプトを使う場合は、**明示的に`CPython (3.7+)`へ切り替え、インストールパスを指定する必要がある**

この仕様は、research_notes/.../01_flow_file_format.mdで触れた「2026年にPower Automateが任意のローカルPythonバージョン実行に対応」という調査結果と整合する——「任意のローカルPythonバージョン」とは、まさにこの「Python installation path」欄でユーザーが指定するPythonインストールを指していたと考えられる。

**`design/control_dump_tech_selection.md`のマーカークライアント設計自体は変更不要**(呼び出され方が「ファイル+引数」から「インラインコード」に変わっただけで、PowerShell側でHTTP POSTする、という処理内容そのものは同じ)。ただし、**コード生成テンプレート側は、生成するPADアクション定義に`python_engine: CPython (3.7+)`と`python_installation_path`を明示的に含める**必要がある、という知見が追加された。

## 副産物: 実際のPADアクション内部ID(DSL命名規則の実証)

UIAツリーをダンプした結果、各アクションのTreeItemの`automation_id`が、研究フェーズで推定していた`Namespace.Module.Action`形式のDSL命名規則と**完全に一致**することを実機で確認できた。

| UI上の表示名 | 内部アクションID(automation_id) |
| --- | --- |
| Display message | `Display.ShowMessageDialog` |
| Run Python script | `Scripting.RunPythonScript` |
| Wait | `LanguageConstructs.Wait` |

これは、PADのクリップボードテキストDSL(`Namespace.Module.Action Param: Value ...`)における`Namespace.Module.Action`部分が、UIAツリー上のアクション選択パネルの`automation_id`とほぼ直接対応していることを示す一次証拠であり、今後パーサー/コードジェネレータを実装する際の命名規則の裏付けとして使える。

## 技術的な実装パターン: clipwire経由でのPAD UI自動化

今回、`design/g1_g2_verification_protocol.md`の「PADをGUIで手動操作してもらう」計画から方針転換し、**clipwire経由でpywinautoを使い、Claude側から直接PADのUIを操作した**。確立したパターンは以下の通り。

1. **WinRM(非対話的)でPythonスクリプトのファイル内容だけを書き換える**(`step.py`を固定パスに上書き)
2. **clipwireに1回だけ登録した`run_step`ターゲット**(`python.exe step.py`を固定の絶対パスで実行)を`/exec`で都度呼び出す
3. clipwire自身が対話的RDPセッション内で起動されているため、`step.py`の子プロセスも同じウィンドウステーションを継承し、**PADのUIAツリーに実際にアクセスできる**

この「WinRMでファイル書き換え+clipwireで実行」という分担により、clipwire自体のRust実装を変更せずに、入れ子クオーティング問題を実務上回避できた(詳細は本セッションの会話ログ、および`powershell-clipd`担当セッションへの機能要望メッセージを参照)。

### 判明した実装上の注意点

- **AvalonEdit等のカスタムテキストエディタへの入力**は、pywinautoの`type_keys()`だと`()`/`{}`等が特殊キー記法として誤解釈され失敗する。**Windowsクリップボード経由のペースト(`win32clipboard.SetClipboardText` + `Ctrl+A`→`Ctrl+V`)が確実**。
- **UIA要素の`name`取得**は、`Edit`コントロールに対しては`.window_text()`ではなく`.element_info.name`を使う必要がある(`window_text()`は入力中の値を返すため、空のテキストボックスでは空文字列になりラベルと一致しない)。
- **ツリー項目の展開**は、`TreeItem`自体をクリックするのではなく、その子の`Expander`ボタン(aid=`Expander`)を明示的にクリックする必要がある。
- **ダイアログを開いたままre-runした診断スクリプト**(ツリーダンプ目的の再`double_click_input()`)が、エンジン選択等の未保存の変更を失わせる場合がある。ダイアログの状態を変更する操作とダンプ目的の操作は分離した方が安全。
