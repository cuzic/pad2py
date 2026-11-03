# PADクリップボードDSL形式: 実機データによる確認・訂正

`research_notes/.../01_flow_file_format.md`では、GitHub上の二次情報(`Hardik-S/geodata`)からDSL形式を推定していた。今回、実際にPADの「コピー&ペースト」機能(キャンバスで全選択→Ctrl+C)でg1g2_testフロー(4アクション)をコピーし、clipwire経由でクリップボード内容を取得した。以下は実機で確認できた生データと、研究結果との差分。

## 実機で取得した生データ

```
Display.ShowMessageDialog.ShowMessage Icon: Display.Icon.None Buttons: Display.Buttons.OK DefaultButton: Display.DefaultButton.Button1 IsTopMost: False ButtonPressed=> ButtonPressed
Scripting.RunPythonScript.RunPythonScriptCPython PythonCode: $'''import urllib.request, json
req = urllib.request.Request(\"http://127.0.0.1:8765/capture\", data=json.dumps({\"action_id\": \"action1\", \"flow_name\": \"g1g2_test\"}).encode(), headers={\"Content-Type\": \"application/json\"}, method=\"POST\")
urllib.request.urlopen(req, timeout=2)
''' PythonPath: $'''C:\\Program Files\\Python312\\python.exe''' ScriptOutput=> PythonScriptOutput
WAIT 1
Scripting.RunPythonScript.RunPythonScriptCPython PythonCode: $'''import urllib.request, json
req = urllib.request.Request(\"http://127.0.0.1:8765/capture\", data=json.dumps({\"action_id\": \"action2\", \"flow_name\": \"g1g2_test\"}).encode(), headers={\"Content-Type\": \"application/json\"}, method=\"POST\")
urllib.request.urlopen(req, timeout=2)
''' PythonPath: $'''C:\\Program Files\\Python312\\python.exe''' ScriptOutput=> PythonScriptOutput2
```

(このフローの作成過程は`design/g1_g2_verification_result.md`を参照。PADの画面上では4アクション——Display message, Run Python script, Wait, Run Python script——だったが、DSL上は上記の通り。)

## 研究結果との主な相違点

### 1. アクションIDは automation_id よりも1段階詳細(サブアクション名が付く)

UIAツリー上の`automation_id`は`Display.ShowMessageDialog`/`Scripting.RunPythonScript`だったが、DSL上のアクションIDは**末尾にさらにサブアクション名が付く**:

| automation_id(UI要素) | DSL上の実際のアクションID |
| --- | --- |
| `Display.ShowMessageDialog` | `Display.ShowMessageDialog.ShowMessage` |
| `Scripting.RunPythonScript` | `Scripting.RunPythonScript.RunPythonScriptCPython` |

**さらに重要な点**: `RunPythonScriptCPython`という末尾の命名から、**Pythonエンジンの選択(IronPython 2.7 / IronPython 3.4 / CPython)によってDSL上のアクションIDそのものが変わる**と推測される(おそらく`RunPythonScriptIronPython27`等の変種が存在)。パーサー設計では、「1つのUIアクション=1つのDSLアクションID」という単純な前提ではなく、**パラメータ(今回はエンジン選択)によってアクションIDの末尾が変化しうる**ことを考慮する必要がある。

### 2. Enum型パラメータは完全修飾名で表現される

`Icon: Display.Icon.None`、`Buttons: Display.Buttons.OK`、`DefaultButton: Display.DefaultButton.Button1`のように、列挙型の値は`Namespace.EnumType.Value`という完全修飾形式。単純な文字列リテラルではなく、値自体も名前空間を持つ。パーサーは「パラメータ値が識別子パターン(`[A-Za-z][A-Za-z0-9.]*`)の場合は列挙値、`$'''...'''`の場合は文字列リテラル」のように値の種類を判別する必要がある。

### 3. 文字列リテラル内のエスケープ規則

`$'''...'''`で囲まれた複数行文字列リテラルの中で、ダブルクォート(`"`)が`\"`に、バックスラッシュが`\\`にエスケープされていた(例: `\"http://127.0.0.1:8765/capture\"`、`C:\\Program Files\\Python312\\python.exe`)。トリプルクォートなので本来`"`自体はエスケープ不要なはずだが、**PADのシリアライザは文字列リテラル内で`"`と`\`を無条件にエスケープする**仕様と見られる。パーサー実装時は、この前提でアンエスケープ処理を行う必要がある(単純に`\\` → `\`、`\"` → `"`の置換で足りるかは、他のエスケープケース(`\n`等の扱い)も含めてさらなる確認が必要——今回の例では改行はエスケープされず生の改行文字のままだった)。

### 4. `WAIT`は特別なキーワード構文(Namespace.Module.Action形式ではない)

研究段階で推定していた通り、`WAIT`は`LanguageConstructs.Wait Duration: 1`のような一般形式ではなく、**`WAIT <秒数>`というベアキーワード構文**だった。UIAツリー上のautomation_id(`LanguageConstructs.Wait`)とDSL表現が一致しない典型例であり、研究ノートで触れていた「`SET`/`LOOP FOREACH`等の特別なキーワード」のグループに`WAIT`も含まれることが実証された。

## パーサー設計(Phase 1)への示唆

1. 文法(EBNF)は、「`WAIT <num>`」のような**ベアキーワード行**と、「`ActionId Param: Value ... Output=> Var`」という**一般アクション行**の2系統を明確に区別する必要がある(研究ノートの推定通りだが、今回`WAIT`で実証された)。
2. アクションIDの末尾セグメントは、パラメータ(特にドロップダウン選択)によって変化しうるため、**UIのaction選択(automation_id)とDSL上のアクションIDの対応表は1:1ではなく、"方言"(variant)を持つマッピング**として設計する。
3. パラメータ値のパースでは、`$'''...'''`(複数行文字列)、`Namespace.Enum.Value`(列挙値)、裸の`True`/`False`(真偽値)、`%VarName%`(変数参照、未確認だが研究ノートで言及)を区別する字句解析ルールが必要。
4. 文字列リテラル内のエスケープ処理(`\"` → `"`, `\\` → `\`)を実装する。
