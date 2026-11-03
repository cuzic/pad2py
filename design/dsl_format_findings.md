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

## 5. `SET`も専用キーワード構文(`WAIT`と同系統)

g1g2_testフローに「Set variable」アクション(UIA上のautomation_id: `LanguageConstructs.Assign`、変数名`TestVar`、値`He said "hello" and used \ in C:\temp\file.txt`)を追加して再度コピーしたところ、DSL上は以下の形式だった:

```
SET TestVar TO $'''He said \"hello\" and used \\ in C:\\temp\\file.txt'''
```

つまり`SET <VarName> TO <value>`という**ベアキーワード構文**であり、`LanguageConstructs.Assign Value: ...`のような一般アクション行ではない。`WAIT`と同じく、UIA上のautomation_idとDSL表現が一致しない例がもう一つ実証された。値部分の文字列エスケープ(`\"`→`"`、`\\`→`\`)は一般アクション行の文字列リテラルと同じ規則に従う。

パーサー(`dump_daemon/pad_dsl_parser.py`)は`SetVariableRecord(var_name, value)`として専用の構造化レコード型を追加し、`SET <token> TO <token>`のパターンを`WAIT`より先に判定するようにした(`tests/test_pad_dsl_parser.py`に実データで検証済み)。未確認: `TO`の右辺が文字列リテラルでなく式(`%OtherVar%`参照や算術式)の場合にどう表現されるか。

## 6. `IF`/`END`構文: 変数参照は`%...%`ではなく裸トークンで表現される(制御フロー再現の核心的知見)

g1g2_testフローに「If」アクション(第1オペランドに`%TestVar%`、演算子デフォルトの「Equal to (=)」、第2オペランドに`hello`というプレーンテキストを入力)を追加して再度コピーしたところ、DSL上は以下の形式だった:

```
IF TestVar = $'''hello''' THEN
END
```

重要な発見:

1. **`IF`は`<operand1> <operator> <operand2> THEN`という固定トークン列の後置構文**で、対応する閉じタグは別行の`END`(`WAIT`/`SET`と同じベアキーワードのグループ)。ブロックの中身(THEN〜END間のアクション)は、今回はIf/End挿入直後に空のままコピーしたため確認できていない——**別途、IF内部にアクションを配置した状態での再検証が必要**。
2. **UI上で`%TestVar%`と入力した変数参照は、DSL上では`%`記号を伴わない裸の識別子`TestVar`として出力される**。これは研究ノート・当初の設計で想定していた「変数参照は`%VarName%`形式」という前提を覆す実証結果であり、パーサー/コード生成の双方に影響する:
   - パーサー側: 値トークンが「プレースホルダキー(文字列リテラル)」でも「`True`/`False`」でもない裸の識別子である場合、**それは変数参照である可能性が高い**(ただし現状は単なる文字列トークンとして保持しているのみで、「変数参照」と「未知の識別子」を区別する型情報はまだ持たせていない)。
   - コード生成側: Python変換時にこの裸トークンをどう扱うか(ローカル変数名としてそのまま使うか、명시的な変数ストア経由にするか)は今後の設計課題。
3. 演算子は`=`という1トークンの記号で表現された(「Equal to (=)」選択時)。他の演算子(`<>`, `>`, `<`, `>=`, `<=`, 文字列の`contains`等)がどう表現されるかは未検証。
4. 第2オペランドにプレーンテキスト`hello`を入力すると、自動的に文字列リテラル`$'''hello'''`として保存された(Set variableの値フィールドと同じ型推論ルール)。

パーサーは`IfRecord(operand1, operator, operand2)`を追加し、`IF <tok> <tok> <tok> THEN`のパターンを検出するようにした。`END`は`_KNOWN_KEYWORDS`に追加(`tests/test_pad_dsl_parser.py`で検証済み)。**未対応**: THEN〜END間のネストしたアクション列をブロック構造として組み立てる処理(現状のパーサーは行単位のフラットな`list[Record]`を返すのみで、`IfRecord`と対応する`END`の間の要素をグルーピングしていない)——これは将来、スタックベースの後処理(`IF`でpush、`END`でpopしてブロックを構築)として実装する必要がある。`ELSE`/`ELSE IF`構文も未検証。

## 7. ネスト構造は**4スペースインデント**で表現される(重要: パーサーのstrip()が情報を破棄していた)

Ifブロック内(`IF...THEN`と`END`の間)に「Set variable」アクション(`InnerVar`)を実機で追加してから再コピーしたところ、DSL上は以下のように**4スペースインデント**でネストが表現されていた:

```
IF TestVar = $'''hello''' THEN
    SET InnerVar TO $'''inside the if block'''
END
```

つまりPADのDSLはPython同様、**インデントがブロック構造の一次情報**になっている(`END`によるキーワード的な閉じタグと、インデントの両方で冗長にネストを表現している)。これは制御フロー再現(ループ・条件分岐のネスト復元)の設計において最重要の文法要素であり、当初の「フラットな行の列」という実装(`parse_dsl`が各行を`line.strip()`してから処理)では、**インデント情報がパース前に失われてしまっていた**ことが判明した。

対応として、`parse_dsl`を以下のように修正した:
- 各行の先頭空白文字数を`strip()`前に数え、`indent_level = leading_spaces // 4`を算出
- 全レコード型(`ActionRecord`/`KeywordRecord`/`SetVariableRecord`/`IfRecord`/`RawRecord`)に`indent: int = 0`フィールドを追加し、該当する深さを保持させる

これにより、**行の列から木構造を組み立てる後処理**(`IF`の`indent`と対応する`END`の`indent`が一致する箇所をマッチングする等)が今後実装可能になった。木構造組み立て処理自体は未実装(次の検証候補)。

## 8. `LOOP`(カウントループ)構文: `IF`と同系統のベアキーワード+`END`

実機で「Loop」アクション(Start from=1, End to=3, Increment by=1、出力変数`LoopIndex`)を追加して再コピーしたところ、DSL上は以下の形式だった:

```
LOOP LoopIndex FROM 1 TO 3 STEP 1
END
```

`IF`/`SET`/`WAIT`と同じ「ベアキーワード行」のグループで、`LOOP <出力変数名> FROM <開始> TO <終了> STEP <刻み>`という固定トークン列。閉じタグは`IF`と同じ`END`(名前空間で区別されないため、ネストした`IF`/`LOOP`が混在する場合は**インデントだけが唯一の構造的な手がかり**になる——`END`単体ではどのブロックを閉じているか判別できない)。

これはユーザーの当初の構想(複数トレースからページ送りループの条件分岐・ループを再現する)に直結する核心的な文法要素であり、**`LOOP`の開始/終了/刻みの各オペランドが数値リテラルだけでなく変数参照や式になりうるか**(例: リストの長さに応じた動的な終了値)は未検証。`For each`(`LanguageConstructs.Foreach`、リスト/コレクションの反復)の構文も未検証——ページ送りのような「不定回数の反復」は`LOOP`より`For each`や`Loop condition`(While、`LanguageConstructs.While`)の方が実際の変換対象に近い可能性が高く、次の検証候補とする。

パーサーに`LoopRecord(loop_var, start, end, step)`を追加し、`LOOP <tok> FROM <tok> TO <tok> STEP <tok>`のパターンを検出するようにした(`tests/test_pad_dsl_parser.py`で実データ検証済み)。

## 9. `LOOP FOREACH`/`LOOP WHILE`構文: 同じ「LOOP」接頭辞でも中身の文法が異なる

「For each」(Value to iterate=`%TestVar%`, Store into=`CurrentItem`)と「Loop condition」(While。First operand=`%LoopIndex%`, Operator=「Less than (<)」, Second operand=`10`)の2アクションを実機で追加して再コピーしたところ、DSL上はそれぞれ以下の形式だった:

```
LOOP FOREACH CurrentItem IN TestVar
END
```
```
LOOP WHILE (LoopIndex) < (10)
END
```

重要な発見:

1. **`LOOP`という接頭辞は共通だが、2語目(`FOREACH`/`WHILE`)で後続の文法が完全に変わる**。カウントループ(`LOOP <var> FROM ... TO ... STEP ...`、知見8)と合わせて、`LOOP`プレフィックスには少なくとも3つの方言がある。パーサーは`tokens[1]`で分岐する必要がある。
2. **`LOOP WHILE`のオペランドは丸括弧で囲まれる**(`(LoopIndex) < (10)`)。これは`IF`(知見6: `IF TestVar = $'''hello''' THEN`、括弧なし)と**同じ「First operand/Operator/Second operand」ダイアログ**から生成されているにもかかわらず、DSL表現が異なる——UIのダイアログ形状とDSLの文法は1:1対応しないことを示す追加の実証例。パーサーには丸括弧を剥がす`_strip_parens()`ヘルパーを追加した。
3. ここでも変数参照(`%TestVar%`・`%LoopIndex%`)は`%`なしの裸トークンとして出力され、知見6の結論を再確認した。
4. ネスト時の`END`配置も確認: `LOOP WHILE`をIfブロック内に追加した場合、

   ```
   IF TestVar = $'''hello''' THEN
       SET InnerVar TO $'''inside the if block'''
       LOOP WHILE (LoopIndex) < (10)
       END
   END
   ```
   のように、**ブロックの開始行と対応する`END`は同じインデント深さ**になる(中身だけが1段深い)。知見7のインデント仕様と整合する。

パーサーに`LoopForeachRecord(item_var, collection)`と`LoopWhileRecord(operand1, operator, operand2)`を追加した(`tests/test_pad_dsl_parser.py`で実データ検証済み)。未検証: `For each`でのリスト要素の型(今回はTestVar=文字列を指定したため設計時エラーが出たが、コピー&ペースト自体は正常に行えた)、`ELSE`/`ELSE IF`、`Exit loop`/`Next loop`のDSL表現。

## 10. `build_block_tree()`: インデント情報からブロック木を組み立てる後処理を実装

知見7(ネストは4スペースインデント)・知見9(ブロック開始行と対応する`END`は同じindent深さ、本体だけが+1)で確立したルールに基づき、`parse_dsl()`が返す**フラットな**`list[Record]`(`indent`フィールド付き)から、`IfRecord`/`LoopRecord`/`LoopForeachRecord`/`LoopWhileRecord`とその本体を`BlockNode(header, body)`としてグルーピングする`build_block_tree()`を実装した。

アルゴリズムはスタック型の再帰下降パース(`parse_level(level)`が「同じ`indent`の`END`に出会うまで」を1つのブロック本体として読み進め、ブロック開始レコードに出会ったら`level+1`で再帰する)。これは実機データを使わない純粋なロジック実装だが、これまでの全知見(インデント計算、`END`の意味論、各ブロック開始構文の判別)を統合して初めて正しく書けるものなので、**これまでの実機検証全体の正しさを検算する**役割も兼ねている。

`tests/test_pad_dsl_parser.py`で以下を検証:
- ブロック構文を含まないフラットなDSL(`REAL_FLOW_DSL`)では、木構造化してもレコード列がそのまま変わらないこと
- `IF`の中に`SET`が1つだけネストする最小ケース(`NESTED_IF_DSL`)で正しく`BlockNode`にグルーピングされること
- `IF`の中に`LOOP WHILE`(本体は空)がネストする、知見9で実機キャプチャした実際のケースで、2階層のネストが正しく組み立てられること

これで、IR設計(design/control_dump_tech_selection.md)が目指していた「複数トレースからページ送りループ・条件分岐を再現する」ための**構文木レベルの土台**が、実機検証済みの文法の範囲(SET/IF/LOOP系3種)でひとまず完成した。未対応: `ELSE`/`ELSE IF`(ブロック木への組み込み方が未設計)、構文エラー(対応する`END`が無いデータ)に対するより堅牢なエラー報告。
