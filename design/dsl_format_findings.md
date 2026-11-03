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

## 11. `ELSE IF`/`ELSE`: `IF`とは別ブロックではなく、同じ構文の追加アーム(重要な設計訂正)

知見10の`build_block_tree()`は「`IfRecord`は単独でブロックを開き、自分専用の`END`を持つ」という前提で実装していたが、実機で「Else if」(`TestVar = 'world'`)と「Else」を`IF`の後に追加して再コピーしたところ、この前提が誤りだと判明した:

```
IF TestVar = $'''hello''' THEN
ELSE IF TestVar = $'''world''' THEN
ELSE
    SET InnerVar TO $'''inside the if block'''
    LOOP WHILE (LoopIndex) < (10)
    END
END
```

重要な発見:

1. **`IF`/`ELSE IF`/`ELSE`は全て同じindent深さ(この例では0)の、1つの構文の異なる「アーム」である**。`IF`自体はネストしたブロックを単独で開かない——`ELSE IF`や`ELSE`が同じindentで後続する限り、それらは兄弟アームであり、ネストした子ではない。
2. **`END`は個々のアームにではなく、構文全体(`IF`...`ELSE IF`*...`ELSE`?)にちょうど1つだけ対応する**。この例では`IF`アームも`ELSE IF`アームも本体が空(条件式を書いただけで中身を追加しなかったため)で、最後の`ELSE`アームだけが本体(`SET`+`LOOP WHILE`)を持つが、`END`は全体で1個のみ。
3. `ELSE IF`は`ELSE`と`IF`という2つの別トークンの組み合わせ(`tokens[0]="ELSE"`, `tokens[1]="IF"`)であり、その後は通常の`IF`と同じ`<operand1> <operator> <operand2> THEN`が続く。`ELSE`単体(条件なし)はオペランドを持たないベアキーワード。

これは「同じUIダイアログ形状でもDSL表現が違う」(知見6・9)とは別種の訂正で、**ブロック境界の認識そのものを誤っていた**ケース。`build_block_tree()`を書き直し、`ElseIfRecord`を新設、`ConditionalNode(arms: list[(header, body)])`という専用のノード型を導入して、`IfRecord`を見つけたら同じindentで`ElseIfRecord`/`ELSE`キーワードが続く限りアームとして回収し、最後に現れる`END`1つだけを消費するように修正した(`LOOP`系は従来通り「開始行=対応する`END`が1:1」の単純な`BlockNode`のまま)。`tests/test_pad_dsl_parser.py`に実データで検証済み。

## 12. `EXIT LOOP`/`NEXT LOOP`: 単純な2トークンのベアキーワード

`LOOP WHILE`ブロックの中に「Exit loop」「Next loop」アクションを実機で追加して再コピーしたところ、DSL上は以下の形式だった:

```
LOOP WHILE (LoopIndex) < (10)
    EXIT LOOP
    NEXT LOOP
END
```

`EXIT LOOP`/`NEXT LOOP`はいずれも`WAIT`と同系統の単純なベアキーワードで、`KeywordRecord(name="EXIT"/"NEXT", args=["LOOP"])`としてそのまま表現できる。ブロックを開かず、`LOOP`系の本体内に通常のリーフとして出現するだけなので、`build_block_tree()`への変更は不要だった(`_KNOWN_KEYWORDS`に`"EXIT"`/`"NEXT"`を追加するだけで対応完了)。`tests/test_pad_dsl_parser.py`で実データ検証済み。

なお検証の過程で、「Exit loop」アクションをループの外側に誤って配置すると、design-timeに`Exit loop can't be outside loop.`というバリデーションエラーが出ることを確認した——ただし「コピーとして貼り付け」自体はこのエラーがあっても正常に実行できる(G1/G2検証と同様、design-timeエラーはコピー操作をブロックしない)。

## 13. 複合条件式(AND/OR): `If`アクションのUIレベルでは非対応(否定的知見)

`IF`/`LOOP WHILE`で使われている「First operand/Operator/Second operand」ダイアログを再度開いて確認したところ、**この3フィールド構成が唯一の入力形態**であり、AND/OR等で複数条件を組み合わせるUIは存在しなかった(「Add condition」のような追加ボタンや、Simple/Advancedモード切り替えも見当たらない)。

したがって、PADで複合条件(例:「AかつB」)を表現する場合、**単一の`IF`アクションのDSLとしては表現されず**、`IF`のネスト(`IF A THEN IF B THEN ... END END`)や、`ELSE IF`チェーンによる代替表現になっていると推測される。これはトランスパイラ設計にとって重要な意味を持つ: ソースのPADフローにAND/OR相当のロジックがあっても、DSL/IRの文法要素としては独立した`AndRecord`/`OrRecord`のようなものは不要で、既存の`ConditionalNode`のネスト(知見11)だけで表現が完結する可能性が高い。

この仮説を実機で検証した(続き: 知見14)。

## 14. ネストした`IF`(AND相当)の実機検証 — `build_block_tree()`はコード変更なしで正しく組み立てる

外側`IF`(`TestVar = 'hello'`)の、それまで空だった本体に、さらに`IF`(`InnerVar = 'nested'`)を追加して再コピーしたところ、DSL上は以下の形式だった:

```
IF TestVar = $'''hello''' THEN
    IF InnerVar = $'''nested''' THEN
    END
ELSE IF TestVar = $'''world''' THEN
ELSE
    ...
END
```

内側の`IF...END`は外側`IF`アームの本体(indent+1)に完全に収まり、外側の`ELSE IF`/`ELSE`/`END`は外側の深さ(indent 0)のまま正しく継続している。これは知見13で立てた「複合条件はIFのネストで代替される」という仮説を裏付ける直接的な実機証拠である。

重要な点: `build_block_tree()`(知見10・11)は**1行もコードを変更せずに**この2階層のネストを正しく木構造化できた。`IfRecord`を見つけた時点で`parse_level(level+1)`を呼んでアーム本体を再帰的にパースする設計になっており、その本体の中にさらに`IfRecord`が現れても同じロジックが再帰的に適用されるため。`tests/test_pad_dsl_parser.py`に`NESTED_IF_INSIDE_IF_DSL`として回帰テストを追加し、2段ネストの`ConditionalNode`が正しく得られることを確認した。

## 15. コード生成の試作中に発覚した`build_block_tree()`の重大バグ: LOOP系ブロックの後続兄弟が黙って消える

検証済みのIR(`Record`/`BlockNode`/`ConditionalNode`)からPythonコードを生成する最小限のジェネレーター(`dump_daemon/pad_codegen.py`)を試作し、これまで確認した全構文を含む結合テスト用フロー(`LOOP FOREACH`の直後に`LOOP`(カウント)が続き、さらにアクションと`WAIT`が続く)でエンドツーエンドにテストしたところ、`LOOP FOREACH`より後ろの全レコード(カウント`LOOP`・`Scripting.RunPythonScript`アクション・`WAIT`)が木構造から**黙って消えている**ことが発覚した。

**根本原因**: `build_block_tree()`の`LoopRecord`/`LoopForeachRecord`/`LoopWhileRecord`(`_SIMPLE_BLOCK_HEADER_TYPES`)用の分岐は、本体を`parse_level(level + 1)`で再帰的に取得するだけで、**ブロック自身の閉じ`END`を明示的に消費していなかった**(`ConditionalNode`側は`if pos < len(records) and is_end(records[pos], level): pos += 1`で明示的に消費しており、`IfRecord`はこのバグの影響を受けない)。

この`END`はブロックヘッダ自身と同じ深さ(`level`)にあるため、`level + 1`で動いている再帰呼び出しからは「自分の担当範囲外(`indent < level + 1`)」として素通りされ、消費されないまま呼び出し元に制御が戻る。呼び出し元のwhileループは次の反復でこの同じ`END`を再び見ることになるが、呼び出し元自身も`level`という同じ深さで終端`END`を探しているため、**「ブロック自身の終端」と「呼び出し元自身の終端」を区別できず、後者だと誤認してその場で`return`してしまう**——結果、そのブロックより後ろにある同じ深さの兄弟要素が全て読み飛ばされる。

**これまでの全フィクスチャで見逃されていた理由**: このバグは「同じ深さでLOOP系ブロックの直後にさらに兄弟要素が続く」場合にのみ顕在化する。知見8・9・12で使ったテストフィクスチャは、たまたまどれも検証対象のLOOP系ブロックがその深さにおける**最後の要素**だったため(例: `LOOP_WHILE_INSIDE_IF_DSL`はIfアームの最後がLOOP WHILE、`EXIT_NEXT_LOOP_DSL`はフィクスチャ全体の最後がLOOP WHILE)、「誤って早期returnする」ことと「正しく処理が終わる」ことの結果が偶然一致しており、バグが表面化しなかった。

**修正**: `_SIMPLE_BLOCK_HEADER_TYPES`の分岐にも、`ConditionalNode`と同様に`parse_level(level + 1)`の呼び出し直後に`END`の明示的な消費処理を追加した。回帰テストとして、`LOOP FOREACH`と`LOOP`(カウント)を兄弟として連続させ、さらに`WAIT`を後続させた最小フィクスチャ(`tests/test_pad_dsl_parser.py`の`TWO_SIBLING_LOOPS_WITH_TRAILING_ACTION_DSL`)を追加し、3つとも木構造に残ることを確認した。

**教訓**: 単体テストのフィクスチャが毎回「検証対象の構文が末尾に来る」形になっていたため、构造化ロジックの境界条件(複数の同種ブロックが兄弟として連続するケース)が長期間カバーされていなかった。実際にエンドツーエンドでコード生成まで試すことで初めて発覚した——パーサーの単体テストだけでなく、実際に使う形(複数アクションを含む完全なフロー)での結合テストが重要であることを示す一例。

## 16. 値フィールド内の`%VarName%`混在(テキストテンプレート)は文字列リテラルとしてそのまま保持される

これまでの知見6・9では「値全体がまるごと1個の変数参照のとき、UIの`%VarName%`はDSL上`%`記号なしの裸トークンになる」ことを確認していたが、**値の一部だけが変数参照で残りはリテラルテキストの場合(テキストテンプレート)にどう表現されるか**は未検証だった。

実機でSet variableの値フィールドに`Hello %TestVar% world, LoopIndex is %LoopIndex%`(リテラルテキストと2つの変数参照が混在)を入力して再コピーしたところ、DSL上は以下のようにそのまま文字列リテラルとして保持されていた:

```
SET InterpVar TO $'''Hello %TestVar% world, LoopIndex is %LoopIndex%'''
```

つまり:
- **値全体がまるごと1個の変数参照** → `%`記号を剥がした裸トークン(`VarRef`)として表現される(知見6・9)
- **リテラルテキストと変数参照が混在(テキストテンプレート)** → `$'''...'''`の文字列リテラルとして丸ごと囲まれ、`%VarName%`マーカーは**そのまま文字列の中身として残る**(置換・展開されない)

この違いはPADのパーサー/シリアライザが「式全体が単一の変数式かどうか」で表現方法を切り替えていることを示唆する。重要な点: **既存の`pad_dsl_parser.py`の実装はこのケースを変更なしで正しく処理できる**——`$'''...'''`で囲まれた値は常にプレースホルダ経由で復元されるため、中身に`%...%`が含まれていてもただの文字列として扱われ、`VarRef`と誤認されることはない(`tests/test_pad_dsl_parser.py`に回帰テストを追加して確認)。

**今後のコード生成への示唆 → 実装済み(知見17参照)**: 当初`pad_codegen.py`の`render_value()`はこのような文字列をそのまま`repr()`していたため、生成されるPythonコードには文字列として`"Hello %TestVar% world..."`というリテラルの`%TestVar%`がそのまま埋め込まれ、実行時に`TestVar`変数の値へ置換されない問題があった。この後すぐに`render_text_template()`を実装して解消した(知見17)。

## 17. コード生成: `%Var%`テキストテンプレートをf-stringへ変換

知見16のTODOを解消するため、`pad_codegen.py`に`render_text_template(text)`を実装した。`%VarName%`マーカーを含まない文字列はこれまで通り`repr()`、含む場合はトリプルダブルクォートのf-string(`f"""..."""`、改行を含む値でも壊れないように)に変換し、`%VarName%`を`{VarName}`に置き換える。リテラル部分に含まれうる`\`・`"""`・`{`/`}`はf-string内で問題を起こさないようエスケープする(バックスラッシュの二重化、3連続ダブルクォートのエスケープ、波括弧の二重化)。`render_value()`は文字列値をこの関数経由で処理するよう変更した。

**単なる構文チェックに留めず、実行時の意味論まで検証した**: `tests/test_pad_codegen.py`に、生成したf-string式を実際に`eval()`し、`TestVar="hello"`・`LoopIndex=5`を束縛した上で`"Hello hello world, LoopIndex is 5"`という期待通りの文字列になることを確認するテストを追加した(構文的に妥当なだけでなく、PADのテキストテンプレートと同じ実行結果になることの検証)。

## 18. `If`/`Loop condition`の演算子を全種類実機確認——比較演算子は単純な記号、テキスト演算子は関数呼び出し構文

`If`/`Loop condition`ダイアログの「Operator」ドロップダウンを開き、選択可能な全演算子を列挙した:

```
Equal to (=)
Not equal to (<>)
Greater than (>)
Greater than or equal to (>=)
Less than (<)
Less than or equal to (<=)
Contains
Does not contain
Is empty
Is not empty
Starts with
Does not start with
Ends with
Does not end with
Is blank
Is not blank
```

### 18-1. 比較演算子(6種)はすべて単純な記号——`_OPERATOR_MAP`を完全化

残り4種(`<>`/`>`/`>=`/`<=`)を実機で1つずつ選択・保存・コピーして確認した結果、すべて`IF <operand1> <記号> <operand2> THEN`という、既知の`=`/`<`と全く同じ単純な中置記法だった:

| UIのラベル | DSL上の記号 | Python演算子 |
| --- | --- | --- |
| Equal to (=) | `=` | `==` |
| Not equal to (<>) | `<>` | `!=` |
| Greater than (>) | `>` | `>` |
| Greater than or equal to (>=) | `>=` | `>=` |
| Less than (<) | `<` | `<` |
| Less than or equal to (<=) | `<=` | `<=` |

これで`pad_codegen.py`の`_OPERATOR_MAP`に残り4種を追加でき、数値・文字列の比較条件は網羅できる見込み。

### 18-2. テキスト演算子(`Contains`等)は中置記法ではなく**関数呼び出し構文**——重大な文法上の相違

「Contains」を選択すると、ダイアログに新たに**「Ignore case」トグルスイッチ**という第3のフィールドが現れた(First/Operator/Second operandの3フィールド構成が、演算子の種類によって追加フィールドを持つことがある、という初めての発見)。これを保存して再コピーしたところ、DSL上は以下の**完全に異なる形式**だった:

```
IF Contains(InnerVar, $'''nested''', False) THEN
```

つまり`Contains`/`Does not contain`等は`<operand1> <operator> <operand2>`という中置記法ではなく、**`FunctionName(operand1, operand2, caseFlag)`という関数呼び出し構文**になる。第3引数の`False`は「Ignore case」トグルの値(この例ではOFF=大文字小文字を区別する=Case sensitive)に対応すると見られる。これは`IF`/`LOOP WHILE`で確立していた「常に3トークンの中置演算子」という前提を覆す。

**現状のパーサーはこのケースを(エラーを出さずに)サイレントに破壊する**——実際に`parse_dsl("IF Contains(InnerVar, $'''nested''', False) THEN\nEND")`を試したところ、クラッシュせずに以下のような無意味な結果を返した:

```python
IfRecord(operand1=VarRef(name='Contains(InnerVar,'), operator='\x00STR0\x00,', operand2=VarRef(name='False)'), indent=0)
```

(`\x00STR0\x00`は未解決のプレースホルダキーがそのまま`operator`フィールドに漏れ出したもの)。これは「対応していないものは例外を出す」という`pad_codegen.py`の`render_condition()`の設計方針(知見15のコメント参照)とは異なり、**パーサー自体が壊れたデータを沈黙して生成してしまう**既知のギャップであり、修正は別タスクとしてスコープ外にした(関数呼び出し構文は`Contains`系6種・`Is empty`系4種で引数の個数(2引数+フラグ / 1引数のみ)が異なると推測され、対応表の設計にまとまった作業が必要なため)。

**実機操作の後片付け**: 検証後、g1g2_testフローのネストした`If`(`InnerVar`)は元の`Equal to (=)`演算子に復元し、これまでのコミットが前提とするDSL出力(`IF InnerVar = $'''nested''' THEN`)と一致する状態に戻した。

## 19. 初めてのUI automationアクション(`Send keys`)をコード生成でマッピング

これまでのコード生成対応は`SET`/`IF`/`LOOP`系の制御構文と`Scripting.RunPythonScript`(中身が既にPythonなのでそのまま展開するだけ)に限られていた。今回、実際のUI automation操作として「Send keys」(`Mouse and keyboard`カテゴリ)を実機で追加し、`pad_codegen.py`に初めてUI操作アクションのpywinauto/pyautogui変換を実装した。

「Send keys」ダイアログは「Send keys to: Foreground window」(デフォルト)・「Text to send:」・「Insert special keys」・「Delay between keystrokes: 10」・「Send Text as hardware keys:」という構成。Text to send="Hello World"、他はデフォルトのまま保存して再コピーしたところ、DSL上は既存の一般アクション行形式(`ActionId Param: Value ...`)にそのまま収まっていた:

```
MouseAndKeyboard.SendKeys.FocusAndSendKeys TextToSend: $'''Hello World''' DelayBetweenKeystrokes: 10 SendTextAsHardwareKeys: False
```

重要な発見: **デフォルト値のまま変更しなかったフィールド(`Send keys to`)はDSLに一切現れない**——`TextToSend`/`DelayBetweenKeystrokes`/`SendTextAsHardwareKeys`の3パラメータしか出力されず、ダイアログに見えていた「Send keys to: Foreground window」フィールドに対応するパラメータ名は一切登場しなかった。つまり`ActionRecord.params`は**そのアクションが持つ全パラメータの一部(変更されたものだけ)しか含まない**可能性がある——`SendTo`のような項目は、変更されない限りDSLから省略され、PAD側のデフォルト値が暗黙に適用されると解釈するしかない。これはコード生成が「見えているパラメータだけで完全な変換ができるとは限らない」ことを示す重要な制約で、今後UI操作アクションへの対応を広げる際は、各アクションのデフォルト値を公式ドキュメント等で別途把握する必要がある。

> **解決済み**: 「`Send keys to`だけ省略される」理由は[design/robin_language_source_findings.md](robin_language_source_findings.md)で解明した——`SendKeysTo`は`ActionSelector`の`Prop().ShouldBe()`判別子(variantを決める値)であるため省略される。知見23の追記も参照。

`pad_codegen.py`に`MouseAndKeyboard.SendKeys.FocusAndSendKeys` → `pyautogui.typewrite(text, interval=delay_ms/1000)`の変換を追加した(`generate_python()`は使用時のみ`import pyautogui`を先頭に出力する)。**既知の未対応ケース(要注意)**: 今回実機確認したのは「Insert special keys」を使わない素のリテラルテキスト("Hello World")の場合のみ。特殊キー(Enter/Tab等)を挿入した場合のDSL表現(pywinautoの`{ENTER}`構文と同じか、PAD独自の別構文か)はまだ実機確認していない。**現在の実装はこの違いを検出していない**——`TextToSend`が文字列でありさえすれば、中身を問わず無条件に`pyautogui.typewrite()`へ変換してしまうため、もし特殊キー記法が異なる構文だった場合、気づかれないまま誤った(あるいは単に動かない)コードを生成するリスクが残る。安全側に倒すなら本来は特殊キー記法を検出して`# TODO`に倒すべきだが、その記法自体が未確認のため検出ロジックを書けず、今回はこのリスクを許容してスコープ外にした。次に特殊キーを使うSend keysを実機確認した際に、検出・分岐処理を追加する必要がある。

## 20. 2つ目のUI automationアクション(`Move mouse`)——「デフォルト値は省略される」という前提が崩れた

座標ベースでセレクタが不要な「Move mouse」(`Mouse and keyboard`カテゴリ)を実機で追加した。ダイアログは「Position X」「Position Y」「Relative to」(Screen/Window等のドロップダウン、既定Screen)「Move mouse from previous position」(Instant/Smoothly、既定Instant)という構成。X=500, Y=300だけ入力し、残り2つは既定値のまま保存して再コピーしたところ、DSL上は**4パラメータ全てが明示的に出力された**:

```
MouseAndKeyboard.MoveMouse X: 500 Y: 300 RelativeTo: MouseAndKeyboard.PositionRelativeTo.Screen MovementStyle: MouseAndKeyboard.MovementStyle.Instant
```

これは知見19で立てた「デフォルト値のまま変更しなかったフィールドはDSLに現れない」という仮説と矛盾する——「Send keys」の`Send keys to`(デフォルトのまま)は省略されたのに、「Move mouse」の`RelativeTo`/`MovementStyle`(同じくデフォルトのまま)は省略されなかった。つまり**「変更されていないフィールドが省略されるかどうかはアクション・フィールドの種類によって異なり、普遍的なルールではない**」。この挙動差の正確な条件(ドロップダウン/Enum型かテキスト型か、アクションの実装次第か等)はまだ特定できておらず、今後もアクションごとに個別に実機確認する必要がある——「このフィールドはDSLに出ていないから対応不要」と安易に判断してはいけないことを示す重要な教訓。

`pad_codegen.py`に`MouseAndKeyboard.MoveMouse` → `pyautogui.moveTo(x, y)`の変換を追加した。**スコープを絞った安全策**: `RelativeTo: Screen`かつ`MovementStyle: Instant`の組み合わせ(今回実機確認した唯一のケース)のときだけ変換し、それ以外(`Window`基準や`Smoothly`移動等、未検証)は従来通り`# TODO`コメントのままにする——架空の座標変換ロジックをでっち上げないための明示的なガード。`tests/test_pad_codegen.py`には、このガードが実際に機能して意図せぬ変換をしないことを確認する否定的テストケースも追加した。

## 21. 3つ目のUI automationアクション(`Send mouse click`)——Bool型トグルは省略、Enum型は省略されない傾向を補強

「Send mouse click」(`Mouse and keyboard`カテゴリ)を実機で追加した。ダイアログは「Mouse event to send」(ドロップダウン。全8種: Left click/Right click/Double click/Left button down/Left button up/Right button down/Right button up/Middle click。既定Left click)・「Wait」(既定0、単位はおそらくミリ秒)・「Move mouse」(トグル、既定off——onにすると追加のX/Y欄が現れると見られるが未確認)という構成。すべて既定値のまま保存して再コピーしたところ:

```
MouseAndKeyboard.SendMouseClick.Click ClickType: MouseAndKeyboard.MouseClickType.LeftClick MillisecondsDelay: 0
```

ここでも知見20の謎(デフォルト値省略の不統一)に新しいデータ点が加わったが、**今回も単純な規則には収束しなかった**: Bool型トグルの`Move mouse`(off、未変更)は一切出力されない一方、Enum型の`ClickType`は既定値でも出力される(知見20のMoveMouseの`RelativeTo`/`MovementStyle`と同じ傾向)。しかし知見19の「Send keys」では、同じくBool型だった`SendTextAsHardwareKeys`(off、未変更)は出力されていた——つまり「Bool型だから省略される」という単純な説明も成り立たない。今回の3アクション分のデータだけでは一貫した規則を特定できておらず、**「アクションごと・フィールドごとに個別に実機確認するしかない」というのが現時点での結論**。この問題自体を体系的に解明するには、より多くのアクションでの横断的な調査が必要で、今後の課題として残す。

`pad_codegen.py`に`MouseAndKeyboard.SendMouseClick.Click` → `pyautogui.click()`の変換を追加した(知見19・20と同じ方針で、実機検証済みの`ClickType: LeftClick`のときだけ変換し、残り7種のクリック種別は`# TODO`のまま)。`MillisecondsDelay`が0でなければクリック前に`time.sleep(ms/1000)`を挿入する。これで`pyautogui`ベースのマウス操作(移動→クリック)が一通り組めるようになった。

## 22. 知見18-2のバグを修正: `Contains`系の関数呼び出し条件を正しく構造化

知見18-2で発覚した「`Contains(InnerVar, $'''nested''', False)`のような関数呼び出し構文の`IF`を、パーサーがクラッシュせずサイレントに壊れたデータへ変換してしまう」というバグを修正した。

`_FUNC_COND_RE`(`^(IF|ELSE IF) ([A-Za-z_][A-Za-z0-9_]*)\((.*)\) THEN$`)で行全体を先にマッチさせ、マッチした場合は`IfFunctionRecord(function_name, args)`/`ElseIfFunctionRecord(function_name, args)`として構造化するようにした(既存の中置記法用の`IF`/`ELSE IF`判定より前に、`_parse_line()`の先頭でこのチェックを行う)。引数はカンマ区切りで分割し、各引数を既存の`_resolve_value()`に通すため、`VarRef`/文字列リテラル/`True`・`False`等の型区別もそのまま適用される(今回の例では`args = [VarRef("InnerVar"), "nested", False]`)。

`build_block_tree()`も、`IfRecord`/`ElseIfRecord`を判定していた箇所を`_IF_HEADER_TYPES = (IfRecord, IfFunctionRecord)`/`_ELSEIF_HEADER_TYPES = (ElseIfRecord, ElseIfFunctionRecord)`に一般化し、関数呼び出し条件も通常の`IfRecord`と同様に`ConditionalNode`のアームとして正しく扱われるようにした(コード変更はこの型タプルの置き換えのみで、ロジック自体は変更不要——知見14のネストIF確認時と同様、既存の再帰設計が素直に拡張できた)。

`pad_codegen.py`側は、`Contains`をどのPython式に変換すべきかまだ未検証(`in`演算子で素直に対応できそうだが、大文字小文字の扱い(第3引数の真偽フラグ)や、`Does not contain`/`Starts with`等の兄弟演算子の意味論を含めて実機で裏を取っていない)なため、関数呼び出し条件のアームに遭遇すると架空の変換をでっち上げず明示的に`NotImplementedError`を送出するようにした——知見15・18でも採用した「パーサーは正しく構造化するが、意味の分からない変換はコード生成側で明示的に拒否する」という一貫した設計方針。

**教訓**: 「新しいDSL構文は既存の判定ロジックの"前"に専用の正規表現検出を割り込ませる」という設計で、比較的小さな変更で直せた。`build_block_tree()`側も、直接`isinstance(rec, IfRecord)`/`isinstance(nxt, ElseIfRecord)`としていた箇所を`_IF_HEADER_TYPES`/`_ELSEIF_HEADER_TYPES`という型タプル判定に一般化するだけで済み、ブロック木構築の再帰ロジック自体には一切手を入れずに新しいレコード型を取り込めた——「型で分岐する箇所をタプルにまとめておく」という小さな一般化が、後から種類を増やすコストを大きく下げる好例。

## 23. 4つ目のUI automationアクション(`Press/release key`)——修飾キーの押下/解放、さらにデフォルト省略の謎が深まる

「Press/release key」(`Mouse and keyboard`カテゴリ)を実機で追加した。このアクションは**Ctrl/Alt/Shift/Winの修飾キーの押下・解放専用**で、通常のキー(Enter等)は扱わない——ダイアログは「Action to perform」(Press/Release)・「Control」「Alt」「Shift」「Win」(各トグル)のみで構成され、押す「キー」自体を指定する欄は存在しない。知見19で保留にしていた「Send keysの特殊キー記法」を解明する手がかりにはならなかった(別アクションであり、キー名の指定欄がそもそも無いため)。

Control=True(他は触らずFalseのまま)、Action to perform=Pressで保存・再コピーしたところ:

```
MouseAndKeyboard.PressReleaseKey.PressKey Control: True Alt: False Shift: False Win: False
```

続けてAction to performを「Release」に切り替えて再コピーしたところ、action_id自体が変化した(知見3の「パラメータでアクションIDの末尾が変わる」パターンの再確認):

```
MouseAndKeyboard.PressReleaseKey.ReleaseKey Control: True Alt: False Shift: False Win: False
```

ここで**デフォルト値省略の謎(知見19-21)がさらに深まった**: 今回は触っていないAlt/Shift/Win(すべてBool、すべてFalseのまま)が**全部出力された**。知見21の「Send mouse click」ではBool型トグル(`Move mouse`)が省略されたのに対し、今回は同じBool型でも省略されない。3つのアクション(Send keys/Send mouse click/Press release key)で、Bool型フィールドの省略有無がバラバラという結果になり、**「型」だけでも「触ったかどうか」だけでも説明がつかない**ことが確定的になった。今のところ「アクションの実装者がどう設計したか次第」としか言いようがなく、汎用的な予測は諦めて個別確認を続けるしかない。

> **解決済み(2026-11-03追記)**: この謎は、実機の試行錯誤だけでは解決不能という判断からアクションモジュールDLLを逆コンパイルして調査した結果、完全に解明された。詳細は [design/robin_language_source_findings.md](robin_language_source_findings.md) の「デフォルト値省略の謎を完全に解明」節を参照。要約: 各アクションは`ActionSelector`という仕組みで複数のvariant(=`action_id`の末尾)を持ち、`Prop().ShouldBe(value)`で宣言されたプロパティ(=選ばれたvariantを決定する判別子)はDSLから省略され、`Show()`/`ShowAll()`で宣言されたプロパティは(既定値と一致していても)常に出力される、という一貫した規則だった。

`pad_codegen.py`に`MouseAndKeyboard.PressReleaseKey.PressKey`/`...ReleaseKey` → `pyautogui.keyDown(...)`/`pyautogui.keyUp(...)`の変換を追加した。知見19-21と同じ方針で、Control/Alt/Shift/Winのうち**ちょうど1つだけ**`True`の組み合わせ(今回実機確認した唯一のケース)のときだけ変換し、0個または複数同時`True`(未検証)は`# TODO`のままにする。

## 24. 5つ目のUI automationアクション(`Set window state`)——セレクタ不要な「ウィンドウタイトル指定」モードを発見

「Set window state」(`UI automation > Windows`カテゴリ)を実機で追加した。ダイアログには「Find window mode」という3択のドロップダウンがあった: 「By window UI element」(既定。本格的なセレクタピッカーが必要——research_notesで触れていた「セレクタ形式」の本丸だが今回は踏み込まなかった)・「By window instance/handle」(ウィンドウハンドルの変数参照)・**「By title and/or class」**(ウィンドウタイトル文字列、クラス名文字列、または「Select window」ボタンでの対話的選択)。

「By title and/or class」モードはセレクタピッカーを使わずテキストでウィンドウを指定できるため、今回はこれを選んで検証した。Window titleに"Power Automate"と入力すると、PADは自動補完で実際に開いているウィンドウの完全なタイトル("Power Automate | g1g2_test")に置き換えた。Window classは空のまま、Window stateを既定の"Restored"から"Maximized"に変更して保存・再コピーしたところ:

```
UIAutomation.SetWindowState.SetStateByTitleClass Title: $'''Power Automate | g1g2_test''' Class: $'''''' State: UIAutomation.WindowState.Maximized
```

`Class: $''''''`(中身が空の文字列リテラル、`$'''` 直後に `'''` が続く)という初めてのケースも確認できた——既存の`_STRING_RE`(`\$'''(.*?)'''`、非貪欲マッチ)は空文字列も問題なく処理できることを確認済み(コード変更不要)。

`pad_codegen.py`に`UIAutomation.SetWindowState.SetStateByTitleClass` → `Desktop(backend='uia').window(title=...).maximize()/minimize()/restore()`の変換を追加した(`pyautogui`と同様、使用時のみ`from pywinauto import Desktop`をファイル先頭に出力するよう`generate_python()`を拡張)。知見19-23と同じ方針で、`Window class`を併用しない(空文字列の)場合のみ変換し、クラス名併用(未検証——`Desktop().window(title=..., class_name=...)`になるのか等)は`# TODO`のままにする。

これは**初めて「アクション名のテキスト指定でウィンドウを特定する」実機データが取れた**という点で重要——本格的なUIA要素セレクタ(`By window UI element`モードで使われる、ボタンやテキストボックス等の個別要素を特定する仕組み)の文法はまだ未解明だが、ウィンドウ単位の操作であれば、セレクタピッカーを介さずタイトル文字列ベースで十分実用的に変換できる可能性が見えた。

## 25. 「Move window」「Resize window」——同じ`ByTitleClass`パターンが横展開できることを確認

ユーザーから「1ティックあたりの作業量を増やせないか」と要望があったため、1回のPAD往復(コピー&ペースト)で複数アクションをまとめて検証する運用に切り替えた。「Move window」「Resize window」(いずれも`UI automation > Windows`カテゴリ、知見24の`Set window state`と同じサブカテゴリ)を同じフローに続けて追加し、どちらもFind window mode=By title and/or class、Window title="Power Automate"(自動補完で"Power Automate | g1g2_test"に)、Window classは空のまま、Position X=100/Y=50(Move window)、Width=1024/Height=768(Resize window)として保存し、1回のコピーでまとめて確認した:

```
UIAutomation.MoveWindow.MoveByTitleClass Title: $'''Power Automate | g1g2_test''' Class: $'''''' X: 100 Y: 50
UIAutomation.ResizeWindow.ResizeByTitleClass Title: $'''Power Automate | g1g2_test''' Class: $'''''' Width: 1024 Height: 768
```

予想通り、知見24の`Set window state`(`UIAutomation.SetWindowState.SetStateByTitleClass Title: ... Class: ...`)と全く同じ`Title`/`Class`パラメータ構成パターンがそのまま横展開されており、`Windows`サブカテゴリの各アクションはおそらく共通の「Find window mode」基盤実装を共有していると推測できる(複数アクションでパターンの一貫性を確認できたのは初めて——これまでの知見19-23は逆に「一貫しない」ことの確認が多かった)。

`pad_codegen.py`では、3アクション共通の`_window_lookup_expr(node)`ヘルパーを新設し(`Title`/`Class`からの`Desktop(backend='uia').window(title=...)`式組み立てを共通化)、`UIAutomation.MoveWindow.MoveByTitleClass` → `.move_window(x=, y=)`、`UIAutomation.ResizeWindow.ResizeByTitleClass` → `.move_window(width=, height=)`(pywinautoの`move_window()`は幅/高さのみ指定すれば現在位置を保ったままリサイズできる)を追加した。知見24と同じガード(`Window class`併用は未検証のためTODO)を3アクションで共有している。

## 26. パーサーの重大バグ発見: 1アクションが複数の出力変数を持つ場合、後の束縛が前の束縛をサイレントに上書きしていた

「Focus window」(知見25と同じByTitleClassパターンの5件目——予想通りの結果だったため詳細は割愛)に続けて「Get window」を実機で追加した。「Get window:」ドロップダウンには「Foreground window」「Specific window」「UI element」の3モードがあり、「Foreground window」を選ぶとウィンドウセレクタ不要で、design/dsl_format_findings.md知見24-25のByTitleClass系とはまた別の、セレクタすら要らない最もシンプルなモードだと分かった。保存・再コピーしたところ:

```
UIAutomation.GetWindow.GetForegroundWindow WindowTitle=> WindowTitle WindowInstance=> AutomationWindow
```

**ここで重大なバグを発見した**: このアクションは`WindowTitle=> WindowTitle`と`WindowInstance=> AutomationWindow`という**2つの出力束縛**を持つ。これまでの全アクション(Display message、RunPythonScript等)は出力が1個だけだったため気づかなかったが、`ActionRecord.output_var`は単一の`str | None`フィールドしかなく、`_parse_line()`のパラメータ走査ループは`=>`トークンに遭遇するたびに`record.output_var = tokens[i + 1]`と**無条件に上書き**していた。つまりこの例では、1個目の束縛(`WindowTitle=> WindowTitle`)の情報が**完全に、サイレントに失われ**、`output_var`には2個目の`AutomationWindow`だけが残っていた(実際に`parse_dsl()`で検証して再現を確認した)。

知見18-2(Contains)や知見15(LOOP自身の閉じEND消費)と同種の「クラッシュせず静かにデータを失う」バグで、今回は**単体テストのフィクスチャが複数出力を持つアクションを一度も含んでいなかった**ため長らく見逃されていた——知見15の教訓(「検証対象が末尾に来る」偏り)と同じ構造の「フィクスチャの多様性不足」によるカバレッジの穴。

**修正**: `ActionRecord`に`output_vars: dict[str, str]`(パラメータ名→変数名)フィールドを追加し、`=>`に遭遇するたびに**全ての**束縛をここへ記録するようにした。既存の`output_var`フィールドは後方互換のため残し(最後に見つかった束縛を保持する、という従来の——意図せず生まれていた——挙動をそのまま踏襲)、複数出力がありうるアクションでは`output_vars`を参照する設計とした。既存の単一出力アクション全てに対しても`output_vars`が正しく(1エントリの辞書として)埋まることをテストで確認し、新たに2出力の`Get window`を使った回帰テストを追加した。`pad_codegen.py`側は今回`GetWindow`アクション自体を変換対象に追加していない(複数出力の扱い方の設計は別途必要)ため、変更は不要だった。

## 27. ソース調査で発見した2件のサイレントなエスケープ解除バグを修正、複数行コメントをパーサー対応

知見19〜26と同様、ActionSelectorの発見(前回ティック)に続けてデコンパイル済みソースの読み込みを継続したところ、`StringExtensions.cs`から文字列エスケープの正確な規則が判明し、`pad_dsl_parser.py`の既存実装に2件のサイレントバグがあることが分かった。詳細はdesign/robin_language_source_findings.mdの「文字列エスケープの正確な規則」節を参照。

- **`\'`(エスケープされたアポストロフィ)の解除が欠落していた**: `EscapeForRobin()`は`"`/`'`/`\`の3種類全てをエスケープするが、`_unescape()`は`\"`と`\\`の2種類しか解除していなかった。英語テキストの自動化タスクでは`it's`/`don't`のようなアポストロフィを含む文字列が頻出するため、実害が出やすいバグだった。
- **`%%`→`%`の解除が欠落していた**: `InterpolatedStringAtom.ToString()`はリテラル区間の`%`を常に`%%`に二重化してから出力するため(`_STRING_RE`が捕捉する`$'''...'''`は全てこの経路を通る)、解除が必要だった。

いずれも実機データでは一度も踏んでいなかった(今までのフィクスチャにアポストロフィや`%`を含む文字列が無かった)ため気づかれなかった——知見15・26と同種の「フィクスチャの多様性不足によるカバレッジの穴」。両方とも回帰テストを追加して修正した。

さらに`CommentStatement.ToString()`のソースから複数行コメント(`/# ... #/`)の正確な構文とエスケープ規則(`#/`と`\`の直前にのみ`\`を挿入)が判明したため、パーサーに対応を追加した。実装中、単純な`.*?#/`という非貪欲マッチだと本文中の`\#/`(エスケープされた`#/`)の`#/`部分で早期に終端してしまうバグを自分で書いたテストで発見し、エスケープされた区間を正しく読み飛ばす正規表現に修正した。この複数行コメント構文自体はまだ実機での出力例が無い(構文はソースで確認済みだが実機未検証)。

## 28. `SWITCH`/`CASE`/`DEFAULT`をANTLR文法からの類推でパーサー/codegenに実装(実機未検証)

長らく「IF文のような決め打ちを安易に適用すると誤った意味論を生成する恐れがある」として見送っていた`SWITCH`/`CASE`/`DEFAULT`のブロック構造を、PADのANTLR生成パーサー本体(`Language.cs`)の文法規則定義から解明した。詳細はdesign/robin_language_source_findings.mdの該当節を参照。要点: `switch_statement`/`case_statement`/`case_default`は、既に実機確認済みの`if_statement`/`elseif_statement`/`else_statement`と**文法上完全に並列な選択肢**として定義されている(専用のネスト構造は存在しない)。この並列性を根拠に、IF/ELSE IF/ELSEで確立済みのインデント規則(ヘッダー群は同じindent、各アームの本体はindent+1、ENDは構文全体に1つ)をそのまま類推適用し、`SwitchRecord`/`CaseRecord`/`CaseDefaultRecord`/`SwitchNode`をパーサーに、`if`/`elif`/`else`(`==`比較)への変換をcodegenに追加した。

これは今までの「実機で1つずつ確認してから実装する」という方針からの意図的な逸脱である——根拠は「文法レベルでの確認(ANTLRのルール定義)」という、実機データと同程度に確実な一次情報であり、当てずっぽうの推測ではない。ただしSWITCH自身が実際にこのインデント規則で出力される実機データはまだ無く、`LOOP`の両端含むrange仮定と同じ位置づけの「明示的に文書化された未検証の前提」として扱う。

## 29. ANTLR文法から複合式(AND/OR/XOR/NOT)・算術式(+/-/*//mod)・IN系演算子のDSL表現を確認、`NOT IN`パーサーの既知ギャップを解消

`SWITCH`の調査と同じ`Language.cs`の`ExpressionContext`サブクラス群を確認し、これまで「存在は確認したが構文は未確認」としていた複合条件式と、全く未確認だった算術式のDSL表現が判明した。詳細はdesign/robin_language_source_findings.mdの該当節を参照。

- `AND`/`OR`/`XOR`(**XORは今回初めて判明**)による複合条件式、`NOT`前置演算子、`+`/`-`/`*`/`/`/`mod`による算術式——いずれも単純な中置(`NOT`のみ前置)記法であることが確定したが、現在の`IfRecord`等が前提とする「オペランド1個+演算子1個+オペランド2個」という完全にフラットな構造では表現できない(再帰的な式木が必要)。安易な部分対応は誤った意味論を生成する恐れが大きいため、構文を文書化した上で実装は見送った。
- `IN`/`NOT IN`は、DSL上`NotIn`が内部に空白を1つ持つ**1つの**文字列として直列化されることがソースで確定した。これまで「`NOT IN`は2トークンのため誤パースする既知のギャップ」と記録していた問題を、`_merge_not_in()`(隣接する`"NOT"`/`"IN"`トークンを1トークンへ結合)で解消した。`pad_codegen.py`の`_OPERATOR_MAP`にも`in`/`not in`を追加した(Pythonの意味がPADの「含まれるか」とそのまま対応するため)。実機でどのUI経由で使えるかはまだ未確認。

## 30. UI要素セレクタ(「By window UI element」モード)の文字列フォーマットを解明(実装は見送り)

本プロジェクトの初期から(research_notesの事前調査時点から)「本格的なUIA要素セレクタの文法は未解明」として持ち越していた課題に、`Microsoft.Flow.RPA.Desktop.Modules.UIAutomation.Actions.dll`を新たに取得・逆コンパイルして取り組んだ。詳細はdesign/robin_language_source_findings.mdの該当節を参照。

要点: `ClickElementInWindow`等の「By window UI element」系アクションが使う`UIControl`型(SDK Extended層)を辿ると、セレクタは**CSS属性セレクタに似た独自記法**で表現されることが分かった——要素は` > `で連結(ルートには`:desktop >`)、属性は`[name]`(存在チェック)/`[name="value"]`(完全一致)/`[name*="value"]`(部分一致)/`[name^="value"]`(前方一致)/`[name$="value"]`(後方一致)/`[name@="value"]`(正規表現、CSS標準には無い独自拡張)/`:eq(N)`(序数)/`:disabled`(無効化状態)。セレクタ文字列の内部に`%VarName%`マーカーを埋め込める(他の文字列パラメータと同じインターポレーション形式)ことも確認した。

ただし、この**セレクタ文字列自体のフォーマット**が分かったことと、それが**実際のDSLテキスト上でどう直列化されるか**(`ActionRecord`のパラメータ値としてどう埋め込まれるか)は別の問題であり、後者はまだ確認できていない。`UIControl`が`IEvaluatableContext`を実装している形跡が見当たらず、実機でのDSL出力例も無いため、パーサー/codegenへの実装は時期尚早と判断し、見送った。

## 31. `[Action]`属性からaction_idの構成要素を確認し、Focus window/Close windowをcodegen対応。`ConditionAction`カテゴリ(Contains系と同族)を新たに発見

アクションクラス自身の`[Action(Category=..., Id=...)]`属性から、`action_id`(モジュール接頭辞+`Id`+`ActionSelector.UseName()`)の構成を直接確認できることが分かった。詳細はdesign/robin_language_source_findings.mdの該当節を参照。

- `FocusWindowBase`(`Id="FocusWindow"`)+`FocusWindowByTitleClassSelector`(`UseName("FocusByTitleClass")`)から`UIAutomation.FocusWindow.FocusByTitleClass`を導出——これは知見27で実機確認済みの「Focus window」(5件目のByTitleClassパターン確認、詳細省略としていた)の正式なaction_idだった。`CloseWindowBase`/`CloseWindowByTitleClassSelector`から同様に`UIAutomation.CloseWindow.CloseByTitleClass`を導出(こちらは実機未確認、他4つと同一パターンからの推論)。両方とも`pad_codegen.py`に`.set_focus()`/`.close()`への変換を追加した。
- **副発見**: `IsFocusedByTitleClass`等4つのSelectorが対象にする`IfWindowAction`クラスには、通常の`[Action]`ではなく**`[ConditionAction(Id="IfWindow")]`**という別の属性が付いている。これは知見18-2の`Contains`系と同じ「`IF <Name>(args) THEN`という関数呼び出し条件として使われるアクション」のカテゴリだと判断できる——つまりウィンドウの状態チェック系アクションの一部は、独立したアクション行ではなく条件式として現れる。`Contains`自体もPython変換方法が未確定のままなのと同じ理由で、今回は発見の記録のみとし、パーサー/codegenへの実装は見送った。

## 32. アクション属性の3つ目のカテゴリ`[WaitAction]`を発見、新たなByTitleClass系アクション(SetWindowVisibility)を確認

`[Action]`/`[ConditionAction]`に続く3つ目の属性カテゴリ`[WaitAction]`を発見した。`WaitForWindowAction`(「Wait for window」、`ToBecomeFocusedByTitleClass`等4バリアント)に付いており、`ConditionAction`と同じく`Result`出力を持つが、通常の`[Action]`と同様に独立したアクション行として振る舞う——条件が真になるまでポーリングして待つ、タイムアウト/リトライ内包のブロッキング待機アクション固有の属性と推測される(実行時セマンティクスは未確認)。詳細はdesign/robin_language_source_findings.mdの該当節を参照。

新たなByTitleClassパターンの通常アクションとして`SetWindowVisibility`(action_id: `UIAutomation.SetWindowVisibility.SetVisibilityByTitleClass`、パラメータTitle/Class/Visibility)も確認した。ただし今回はcodegen実装を見送った——「ウィンドウの表示/非表示」に対応する確実なpywinauto公開APIの心当たりが無く、`.maximize()`等と同程度の確信を持てないまま架空のAPI呼び出しをでっち上げるリスクを避けた。また`CloseWindow`/`FocusWindow`の`ByInstanceOrHandle`(Window instance変数を使う3つ目のFind window mode)も見つけたが、「window instance」をPython側でどう表現するかという設計判断(`GetWindow`のcodegen未実装と連動)が必要なため見送った。

## 33. 【重要な訂正】`SWITCH`/`CASE`/`DEFAULT`を実機検証——ANTLR文法からの類推(知見28)は構造面で誤りだった

知見28でANTLR文法上の並列性(`IF`/`ELSE IF`/`ELSE`と同じ文法規則の選択肢)から類推実装していた`SWITCH`/`CASE`/`DEFAULT`を、ついに実機(PAD VM、pywinautoでActionsパネルの検索ボックスを操作してアクションを追加)で検証する機会を得た。「Switch」「Case」「Default case」を実際にフローへ追加し、「コピーとして貼り付け」でキャプチャした結果:

```
SWITCH $'''TestVar'''

    CASE = $'''a'''

        # inside case

    DEFAULT

END
```

(`CASE`の本体を確認するため`Case`選択後に`Comment`アクション「inside case」も追加した)

**2つの重要な発見・訂正**:

1. **ブロックのネスト構造が、類推していたものと違った**: `IF`/`ELSE IF`/`ELSE`は「ヘッダー群が同じindentに並ぶ」構造だが、`SWITCH`/`CASE`/`DEFAULT`は**そうではなかった**。`CASE`/`DEFAULT`は`SWITCH`自身より**1段深い**indentに配置され、各`CASE`の本体(ここでは`# inside case`コメント)は**さらに1段深い**。つまり`SWITCH`→`CASE`の関係も`CASE`→本体の関係も、両方とも`LOOP`→本体と同じ「ヘッダーより1段深い」構造になっていて、二重に重なっている。`END`だけは`SWITCH`自身と同じindentに1つ。知見28の「ANTLR文法上の並列性からIF/ELSE IFと同じ規則を類推適用」という判断は、**文法上の並列性という根拠自体は正しかったが、具体的なインデント規則の予測は外れていた**——文法規則が並列だからといって、印字時のインデント規則まで同じとは限らない、という教訓。

2. **`CASE`は演算子を省略しない**: `CASE = $'''a'''`のように、比較演算子(`=`)が明示されていた。design/robin_language_source_findings.mdで`SemiComparison.ToString()`のソースから「演算子はnullableで省略されうる」と確認していた通り、UIの「Operator:」ドロップダウン(既定値「Equal to (=)」)でも明示的に選択できる——バグではなく仕様。

3. **副次的な発見**: `SWITCH`の「Value to check」欄に裸の`TestVar`(`%`で囲まない)と入力したところ、変数参照ではなく**文字列リテラル**`$'''TestVar'''`として直列化された。これはSWITCHの値欄が他の文字列パラメータと同じ`%VarName%`補間規則(知見16)に従う「テキストフィールド」であり、`IF`の「First operand」欄のような純粋な式エディタではないことを意味する(変数を参照したければ`%TestVar%`と入力する必要があった)。**(後日追加検証)** 実際に「Value to check」欄を`%TestVar%`(純粋な%Var%マーカーのみ)に変更して再キャプチャしたところ、知見16の規則通り`SWITCH TestVar`という裸トークン(VarRef)になることを確認した——既存の`_resolve_value()`は無変更のまま正しく解釈できた。

**修正内容**: `pad_dsl_parser.py`の`build_block_tree()`における`SWITCH`処理を、アーム探索のindent判定を`level`→`level + 1`に、各アームの本体パースを`parse_level(level + 1)`→`parse_level(level + 2)`に修正。`CaseRecord`に`operator: str | None`フィールドを追加し、`CASE <operator> <value>`の3トークン形式を正しくパースするようにした。`pad_codegen.py`の`_generate_switch()`も、ハードコードしていた`==`演算子を`CaseRecord.operator`から`_OPERATOR_MAP`経由で変換するよう修正した。既存のテストフィクスチャ(当初の誤った構造を前提にしていたもの)は実機キャプチャした生データに差し替えた。

**教訓**: ソースコード調査(ANTLR文法・逆コンパイル)は「存在する構文」や「演算子の種類」を確定させるには非常に強力だが、「印字時のインデント規則」のような**複数のクラス階層をまたいだ振る舞い**(`SwitchStatement`自体にはBlock/Scopeが無く、実際の印字ロジックは別の場所にある——design/robin_language_source_findings.md参照)は、ソースだけから確実に予測するのが難しいケースがある。今回のように「文法的に並列だから印字規則も同じだろう」という類推は、**必ず実機検証で裏取りする**(または裏取りできるまで明示的に未検証と書く)という、このプロジェクトが当初から掲げてきた方針の正しさを改めて裏付ける結果になった。

## 実機での「フローの実行」による検証が未解決のブロッカーに突き当たった記録(LOOP range仮定の検証は持ち越し)

> **追記**: このLOOP range仮定の検証は、知見47でさらに一度見送られた後、知見51(「LOOPの範囲は両端を含まない」)で最終的に実機確認・解決済み。本節は歴史的経緯の記録として残す。

知見33のSWITCH検証に続けて、`pad_codegen.py`の`range(start, (end) + 1, step)`という未検証の前提(LOOPの`Start from`〜`End to`が両端を含むか)を、実際にフローを実行して確認しようとした。pywinautoでActionsパネルを操作し、新規サブフロー「LoopTest」に「カウンタファイルをリセットするPythonスクリプト」→「LOOP 1 TO 3 STEP 1」→「カウンタファイルに1文字追記するPythonスクリプト」→`END`を構築し、実行後にファイルの文字数でループが何回実行されたかを確認する計画だった。

構築自体は成功したが、**実行(Run/Run from here)がブロックされた**: 「Run from here with default values」メニュー項目が無効化されており、調べたところ`Main`サブフロー側に以前からある無関係な検証エラー(`LOOP FOREACH CurrentItem IN TestVar`——`TestVar`が文字列でリスト/データテーブルではないため)が原因で、**PADはパッケージ全体を検証してからでないと、どのサブフローも実行させない**ことが分かった(重要な新発見: サブフロー単位の独立実行はできない)。この`For each`アクションを一時的に無効化(Disable action)したところ、対応する`End`が「孤立したEND」という別の検証エラーを出したため、安易に無効化するだけでは解決しないと判断し、`Ctrl+Z`で元に戻して`Main`を無傷のまま復元した。

その後、せめてサブフローの追加だけでもクラウドに保存しようとしたところ、セッション冒頭から持ち越されていた**2段階認証(2FA)のブロッカー**(スマートフォンへの通知送信が必要で、エージェントからは完了できない)に再び突き当たり、保存は失敗した(「Error during flow save」)。「LoopTest」サブフロー自体はデザイナーのメモリ上には存在し続けている(セッション内でのクリップボードキャプチャ等には使える可能性があるが、クラウド保存されていないため次回セッションでは消えている可能性が高い)。

**教訓・今後への申し送り**: (1) PADの実行はサブフロー単位で独立していない(パッケージ全体の検証を通過する必要がある)ため、`Main`に実機確認用の「捨てアクション」を残したままにしておくと、将来の実機実行ベースの検証全般がブロックされ続ける。`Main`の`For each`アクション(`TestVar`を文字列のままリスト扱いしようとしている、意図的な検証エラー)をどう扱うか——削除する/修正する/専用のエラー処理を追加する等——は次回以降、ユーザーに相談するか、安全な形で解消することを検討する価値がある。(2) 2FA問題は本セッション冒頭から未解決のままであり、クラウド保存を伴う操作(今回の「実行」自体は保存無しでも試せたが、変更の永続化はできなかった)は引き続き制約される。

## 34. 【重要な訂正】`ON ERROR`ブロックを実機検証——ソースから類推したインデント規則は誤りだった

実行(Run)は上記の理由でブロックされたが、**アクションの追加・設定・「コピーとして貼り付け」によるDSLキャプチャは実行不要でできる**ことに気づき、どのアクションにも共通する「On error」ボタン(盾アイコン、Error handling設定)を調査した。「Run Python script」アクションの「All errors (default)」(catch-allケース)に`Set variable`(`NewVar`に`'recovered'`を代入)を追加し、「Continue flow run」を選んで保存・コピーしたところ:

```
Scripting.RunPythonScript.RunPythonScript PythonCode: $'''...''' ScriptOutput=> PythonScriptOutput3
ON ERROR
SET NewVar TO $'''recovered'''
END
```

design/robin_language_source_findings.mdで`ExceptionStatementBase`のソース(`SetLevel()`)から「ケースの本体はヘッダーより1段深いindentになる」と予測していたが、**実機ではこれが誤りだったと判明した**——`SET NewVar TO ...`(本体)は`ON ERROR`・`END`・保護対象のアクション自身と全く同じindentだった。他の全ブロック構文(IF/LOOP/SWITCH、いずれも本体がヘッダーより1段深い)とは異なる、唯一の例外的な構造。詳細はdesign/robin_language_source_findings.mdの該当節を参照。

今回検証したのは名前無しcatch-allケース1つのみで、複数ケース・`REPEAT ACTION`/`NEXT ACTION`は未検証。

**(後続のティックで実装)**: `pad_dsl_parser.py`に`OnErrorRecord`/`OnErrorNode`/`GuardedNode`(直前のノードをラップする新しいNode種別)を追加し、`build_block_tree()`で「本体は`ON ERROR`と同じlevelで再帰パース」という実機確認済みの規則を実装した。`pad_codegen.py`は`GuardedNode`を`try`/`except Exception`に変換する(「Continue flow run」の意味論にそのまま対応)。`except Exception`節が実際に例外を捕捉してハンドラを実行することをexecベースのテストで確認済み。

## 35. 複数行コメント(`/# ... #/`)を実機検証——ソースから実装した構文・エスケープ規則が完全に一致

ON ERRORと同じく「実行は不要、アクションの追加とコピーだけでDSLをキャプチャできる」ことを活かし、知見27でソース(`CommentStatement.ToString()`)のみに基づいて実装していた複数行コメント構文を実機検証した。「Comment」アクションに3行(`line one` / `line two with #/ inside` / `line three`、本文中にわざと`#/`というエスケープが必要な文字列を含めた)を入力してキャプチャしたところ:

```
/# line one
line two with \#/ inside
line three#/
```

`#/`が`\#/`にエスケープされている点を含め、design/robin_language_source_findings.mdで事前にソースから導出していた規則(`"/# " + EscapeRobinComment(text) + "#/"`)と**完全に一致**し、`pad_dsl_parser.py`のコード変更は一切不要だった(`parse_dsl()`にそのまま通して正しくデコードできることを確認)。知見27の「実機未検証」という注記は不要になったため解消した。

ソースコード調査だけに基づく実装が実機で無修正のまま正確に動いた、数少ない(しかし重要な)成功例——知見33(SWITCH)・知見34(ON ERROR)の「インデント規則は実機で裏取りするまで確信しない」という教訓と対になる、「構文・エスケープ規則など局所的な文字列処理は、ソース1箇所の`ToString()`を正確に読めば実機と一致する」という逆の教訓。

## 36. `ON ERROR`の名前付きケース・複数アーム連続を実機検証——パーサーの重大バグを発見・修正

知見34で検証した「All errors (default)」(名前無しcatch-all、1アームのみ)に続けて、同じ「Run Python script」アクションの「Failed to run Python script」(名前付きケース)にも`Set variable`を追加し(Continue flow run)、既存のcatch-allケースと共存させてキャプチャしたところ:

```
Scripting.RunPythonScript.RunPythonScript PythonCode: $'''...''' ScriptOutput=> PythonScriptOutput3
ON ERROR RunPythonScriptError
SET NewVar2 TO $'''script failed'''
ON ERROR
SET NewVar TO $'''recovered'''
END
```

**2つの発見**:

1. **名前付きケースの構文確定**: `ON ERROR RunPythonScriptError`——design/robin_language_source_findings.mdで`ExceptionCaseStatement.ToString()`から予測していた`"ON ERROR " + Case`という形がそのまま実機で確認できた(`RunPythonScriptError`はUI上の表示名「Failed to run Python script」とは異なる、PAD内部のケース識別子)。
2. **複数アームが区切り無しに連続する**: 名前付きケースの本体(`SET NewVar2 TO ...`)の直後に、間に`END`を挟まず次のアーム(`ON ERROR`、catch-all)がそのまま続き、**構文全体の末尾に`END`が1つだけ**付く——`SWITCH`の`CASE`/`DEFAULT`(知見33)と全く同じ「複数アーム+末尾に1つのEND」という構造だった。

この2件目の発見により、**知見34時点の実装に重大なバグがあった**ことが判明した。当時の実装は「`ON ERROR`の本体を同じlevelで再帰パースし、見つかった`END`で終了する」という単純な1アーム専用ロジックだったため、2個目の`ON ERROR`(catch-all)に出会うと、それを1個目のアームの**本体の一部として誤って取り込んでしまい**、`GuardedNode`が入れ子状に誤ってネストする結果になっていた(1個目のアームの中に2個目の`OnErrorNode`が隠れてしまう、という静かなデータ破損)。さらに、当時の`_parse_line`は`ON ERROR <CaseName>`(3トークン)を全く認識しておらず、名前付きケースの行は`RawRecord`として素通りしていた。

**修正**: `OnErrorRecord`に`case_name: str | None`フィールドを追加し、3トークン形式(`ON ERROR <CaseName>`)を正しくパースするようにした。`OnErrorNode`を`SwitchNode`と同型の`arms: list[tuple[OnErrorRecord, list[Node]]]`に再設計し、`build_block_tree()`に`parse_level(level, stop_at_on_error=True)`という新しいパラメータを追加——各アームの本体パースが、次のアーム見出し(別の`ON ERROR`)に出会ったら(消費せずに)打ち切るようにした(`SWITCH`の`CASE`/`DEFAULT`の処理と同じ考え方)。`pad_codegen.py`の`_generate_guarded()`も、**1アームかつ名前無しcatch-allの場合のみ**`try`/`except`に変換し、複数アーム・名前付きケースは(PADのエラーケース名とPythonの例外型の対応が不明なため)安易に変換せず`# TODO`に倒すよう修正した。

**教訓**: 知見26(複数出力バグ)・知見15(LOOP兄弟切り捨てバグ)と同種の「単純なケースのフィクスチャだけでは発覚しない」構造的バグが、今回も「2つ目の実機データ(複数アーム)」で初めて発覚した。SWITCH(知見33)で先に「複数アーム+末尾1つのEND」というパターンを知っていたにも関わらず、ON ERRORの実装時にそれを類推適用しなかったのが直接の原因——**1つの構文で確認した構造パターンは、関連する別の構文にも適用されうると常に疑うべき**という教訓。

## 37. `REPEAT ACTION`を実機検証、`_KNOWN_KEYWORDS`に追加

知見36の名前付きケース(「Failed to run Python script」)の設定画面をさらに調べたところ、「Continue flow run」を選ぶと新たに「Exception handling mode」というドロップダウンが現れ、3つの選択肢(「Go to next action」(既定)・「Repeat action」・「Go to label」)があることを発見した。「Repeat action」を選んで保存・コピーしたところ:

```
ON ERROR RunPythonScriptError
SET NewVar2 TO $'''script failed'''
REPEAT ACTION
ON ERROR
SET NewVar TO $'''recovered'''
END
```

`REPEAT ACTION`はアーム本体の末尾に追加される、通常の文と変わらない2トークンのベアキーワードだった——design/robin_language_source_findings.mdで`RepeatActionStatement.ToString()`から確認していた構文そのまま。`EXIT LOOP`/`NEXT LOOP`と同じ扱いができるため、`pad_dsl_parser.py`の`_KNOWN_KEYWORDS`に`"REPEAT"`を追加するだけで対応できた(`"NEXT"`は`NEXT LOOP`で既に登録済みのため、`NEXT ACTION`——ソース上`NextActionStatement.ToString()`が同じ`"NEXT ACTION"`を返す——も追加実装無しで対応できる見込み)。

「Go to label」オプションは今回は未検証のまま持ち越し(おそらくPADの「Label」/「Go to label」アクションと連動する、別の構文が必要になると推測される)。

**追加確認**: 「Exception handling mode」を既定の「Go to next action」に戻して再キャプチャしたところ、`REPEAT ACTION`はおろか**いかなるトークンも出力されなかった**(アーム本体は`SET NewVar2 TO ...`だけに戻った)。つまり「Go to next action」(既定の「次のアクションへ進む」という通常のフロー)は明示的な`NEXT ACTION`トークンを伴わない——`REPEAT ACTION`は非既定の選択をした場合にのみ現れる、という理解で確定した。`pad_dsl_parser.py`は元々この状態(本体にREPEAT/NEXTが無い)も問題なく扱えるため、コード変更は不要。

## 38. 【本プロジェクト最大の謎の1つが解決】UI要素セレクタはDSLテキスト上では名前参照`appmask['<表示名>']`にすぎないと判明——パーサーの重大バグも発見・修正

research_notesの初期調査時点から「本格的なUIA要素セレクタの文法が未解明」として持ち越していた課題に、ついに実機で取り組んだ。ON ERRORの実機検証と同じく「実行不要、アクションの追加とコピーだけでDSLをキャプチャできる」ことを活かし、「Click UI element in window」アクションを追加、UI要素ピッカー(pywinautoでマウスカーソルを移動させ、Ctrl+左クリックでキャプチャ)でWindowsのスタートボタンを選択してキャプチャしたところ:

```
UIAutomation.Click.Click Element: appmask['Start Button'] ClickType: UIAutomation.ClickType.LeftClick MousePositionRelativeToElement: UIAutomation.RectangleEdgePoint.MiddleCenter OffsetX: 0 OffsetY: 0
```

**最大の発見**: `Element`パラメータの値は`appmask['Start Button']`——design/robin_language_source_findings.mdで解明した`Selector`/`SelectorElement`/`SelectorAttribute`のCSS風セレクタ文字列(`[name="value"]`等)が直接埋め込まれているのではなく、**UI要素リポジトリ内のエントリへの名前参照**だった。つまり、これまで解明していた「CSS風セレクタ文字列のフォーマット」は実在する知識ではあるが、それは**UI要素リポジトリの内部格納形式**であって、**DSLクリップボードテキストに直接現れる値ではなかった**——両者は別のレイヤーだと判明した。

**新たなパーサーバグを発見・修正**: `appmask['Start Button']`はUI要素の表示名(`'Start Button'`、空白を含む)を単純な角括弧+シングルクォートで囲んだだけの形式で、`$'''...'''`のような保護は無い。既存の`line.split()`による素朴なトークン化では、空白を含む表示名が2トークンに分裂し(`appmask['Start`と`Button']`)、`Element`パラメータの値が`VarRef("appmask['Start")`という壊れた値になり、`Button']`トークンは静かに失われる——知見15・26・36と同種の「フィクスチャの多様性不足で長年気づかれなかったはずのバグ」を、今回は実機データを得た直後に自分で書いたテストで即座に発見した。`_UI_ELEMENT_RE`で`appmask['...']`全体を他の値(`$'''...'''`文字列・`/# #/`コメント)と同じくマスキングしてから行分割するよう修正し、新しい値型`UiElementRef(name)`を追加した。

**今後の課題**: この発見により「UI要素参照がDSLテキスト上でどう直列化されるか」という構文上の謎は解けたが、**実際のセレクタ文字列(CSS風)自体はクリップボードのDSLテキストには含まれていない**ため、`Click UI element in window`等のアクションをPythonのpywinauto呼び出しに変換するには、別途PAD側の「UI要素」リポジトリの中身(表示名→セレクタ文字列のマッピング)を取得する方法が必要になる——`.msapp`ファイルやフローパッケージの別の部分を調べる、あるいはPAD自体のエクスポート機能を使う等、クリップボードコピー以外の経路が必要になると推測される。

## 39. UI要素の「Public Attributes」完全一覧を実機で取得——セレクタ属性語彙がdecompile結果と一致することを確認(ただし保存済みリポジトリエントリの直接取得はまだ未解決)

知見38の続き。「UI elements」パネル(右サイドバーのレイヤーアイコン)のヘッダーにある`+`ボタン横のドロップダウンシェブロンを開くと、「Add UI element」「Add a screen」「Inspect UI elements」の3項目が現れることを発見した。このうち**「Inspect UI elements」**が今回の核心で、クリックすると「UI element picker」という別ウィンドウが開く。これはAdd UI element時に使うピッカーと似た見た目だが、要素を選ぶとフローに追加する代わりに右側に**「Select a UI element to view its attributes」**という属性ビューアーが表示される——「UI要素リポジトリに保存済みの要素を右クリック→プロパティ的な操作で中身を見る」経路ではなく、**ライブのデスクトップ上のUI要素ツリーを探索して任意の要素の属性を見る独立ツール**だった(右クリック→「Rename」「Find usages」「Delete」しか出ない保存済みエントリの編集とは別物)。

ツリーは`Local computer > Window '...' / TaskBar / Desktop Icons`という構成で、現在デスクトップ上に存在するウィンドウ・コントロールをリアルタイムに列挙する(UIAツリーのライブビュー)。`TaskBar > Button 'Start'`を選択し「Show more details」→「Copy to clipboard」でクリップボードにテキストとして属性全体をコピーできた。得られた内容は2セクションに分かれていた:

- **Public attributes**(「These properties can be used as selector attributes when building a custom selector.」という説明付き): `acceleratorKey`・`accessKey`・`automationText`・`boundingRectangle`・`class`・`contentRectangle`・`controlName`・`displayedName`・`elementRole`・`elementTag`・`elementTypeName`・`enabled`・`extendedTag`・`frameworkId`・`handle`・`hasKeyboardFocus`・`hasParent`・`helpText`・`horizontalScrollPercent`・`horizontalViewScrollPercent`・`id`・`isAlive`・`isChecked`・`isContentElement`・`isControlElement`・`isDataGrid`・`isDefault`・`isDialog`・`isGridOrTableControl`・`isHorizontallyScrollable`・`isLegacyIAccessible`・`isOffScreen`・`isPassword`・`isSelected`・`isSelectList`・`isTextBox`・`isTheRoot`・`isTheStartMenu`・`isTreeOrTreeNode`・`isVerticallyScrollable`・`keyboardFocusable`・`legacyDefaultAction`・`localizedControlType`・`name`・`nodeName`・`ordinal`・`processId`・`processName`・`tag`・`text`・`value`・`verticalScrollPercent`・`verticalViewScrollPercent`・`visible`・`visualRectangle`・`windowVisualState`。
- **Internal Properties**: 生のUIA3プロパティ群(`automationId`・`className`・`controlType`(数値)・`runtimeId`・`providerDescription`・`legacyIAccessible.*`等、`uiaType: UIA3`)。

**意義**: 知見36(robin_language_source_findings.mdで逆コンパイルした`SelectorAttribute`)で一次ソースから推測していた属性名の語彙(`Name`/`AutomationId`に類する`controlName`/`class`/`automationText`等)が、実機のPAD UIが提示する「Public attributes」の一覧と一致することを実データで確認できた。これは`Click UI element in window`等のUI automationアクションをpywinautoへ変換する際の属性マッピング表(PAD属性名 → pywinauto `best_match`/`class_name`/`title`/`control_type`等)の土台になる。

**未解決のまま残る点**: このピッカーはあくまで「現在画面上に存在するライブ要素」を調べるツールであり、知見38で見つかった`appmask['Start Button']`という**保存済みリポジトリエントリ**を選んでその保存済みセレクタ属性(キャプチャ時に実際にどの属性の組み合わせが保存されたか)を直接見る手段は、今回の調査ではまだ見つかっていない。保存済みエントリの右クリックメニューには相変わらず「Rename」「Find usages」「Delete」しかなく、「Edit selector」的な項目は無い。次善策として、(a) 保存済み要素をクリックする`Click UI element in window`アクションの実行時に発生する可能性のあるログ/トレースを調べる、(b) PADのプロジェクトファイル(.msapp等)自体を直接覗く、(c) 要素リポジトリの内部ストレージ(レジストリ/ローカルファイル)を探す、といった経路が今後の候補になる。

**追加調査(同ティック内)**: 「保存済み要素の選択UI」側からも探索した。「Click UI element in window」アクションの編集ダイアログで`UI element`欄の右にある3つのアイコン(鉛筆・レイヤー(スタック)・info)をそれぞれクリックしたが、鉛筆とレイヤーアイコンはいずれも目に見える変化を起こさなかった(属性ビューアーもセレクタ編集画面も開かない)。`UI element`欄自体(コンボボックス)をクリックすると、保存済み要素を選び直すためのドロップダウン(「Local computer > Start Button」のツリー + サムネイルプレビュー + Select/Cancel)が開いたが、ここで表示されるのは**サムネイル画像だけ**で、属性やセレクタ文字列は一切表示されなかった。結論として、**PADデザイナーのUIからは、保存済みUI要素リポジトリエントリの内部セレクタ属性を直接閲覧する経路は(今回探索した範囲では)存在しない**——この探索は一旦ここで打ち切り、上記(a)〜(c)の代替経路を今後の課題として持ち越す。

**ローカルファイルストレージの調査(選択肢(c))もこのティックで実施、ネガティブな結果**: WinRM経由で`C:\Users\tomoya_kaw\AppData\Local\Microsoft\Power Automate Desktop`以下を再帰的に調べた。`Designer\Data\<GUID>.settings`というファイルが見つかり、未保存のフローのデザイナー状態(開いているタブ・ブレークポイント・`GraphLayoutETag`)をローカルにキャッシュしていることは確認できたが、中身はUI要素リポジトリとは無関係なJSON(タブ構成のみ)だった。さらに同ディレクトリ配下を`"Start Button"`文字列で再帰grepしたが**一致するファイルは1件も無かった**。これは、今回のPADクラウド接続構成では「UI要素」の実体(セレクタ属性を含む)がローカルにキャッシュされず、クラウド側(フローの保存先)にのみ存在する可能性を示唆している——もしそうなら、このセッションを悩ませている2FA起因のクラウド保存ブロッカー(design/robin_language_source_findings.md等で既出)が解消されない限り、保存済みセレクタの内容を直接確認する手段自体が無い、という結論になる。(b)の`.msapp`ファイル解析も、クラウド保存できていない以上は試せる対象が無い。この行き止まりを記録し、UI要素セレクタの内部格納形式の解明はここで一旦保留とする。

## 40. `ON BLOCK ERROR`の完全な構造と`NEXT ACTION`を実機で確認——`BLOCK`という新構文も発見、パーサー/codegenに実装(知見34・36・37の構造がそのまま再利用できることを確認)

design/robin_language_source_findings.mdで「本体内のどこに置けるか未確認」として持ち越していた`REPEAT ACTION`/`NEXT ACTION`のうち、`NEXT ACTION`の実機未検証分と、同じく構文のみ確認済みだった`ON BLOCK ERROR`の両方を、1回の実機キャプチャで同時に解決できた。

**きっかけ**: 知見34・37で確認した単一アクションの`ON ERROR`の「Exception handling mode」ドロップダウンには`Go to next action`(既定)/`Repeat action`/`Go to label`の3択しかなく、`Go to next action`が既定(トークン無し)のため、どこで`NEXT ACTION`トークンが実際に出力されるのか分からないままだった。Actionsパネルで"Block"を検索すると、Flow control配下に**「On block error」**という単独アクションが見つかった。これをキャンバスへドラッグ&ドロップすると、PADが自動的に**無名の`BLOCK`**(複数アクションをまとめるグループ化構文)でラップした状態になり、「On block error」の設定ダイアログが開く。ここで「Continue flow run」を選ぶと、単一アクションのON ERRORダイアログと同じ「Exception handling mode」ドロップダウンが現れるが、**選択肢が5つ**(`Go to next action`/`Repeat action`/`Go to label`/`Go to beginning of block`/`Go to end of block`)あり、**既定値は`Go to end of block`**だった——単一アクションの場合の既定`Go to next action`とは異なる。つまり「BLOCKレベルでは`Go to next action`は非既定の選択」であり、ここでならトークンが出力されるはずだと推測し、`Go to next action`を選んで保存・コピーしたところ:

```
BLOCK 
ON BLOCK ERROR
NEXT ACTION
END
```

(生の改行まで含めると`'BLOCK \nON BLOCK ERROR\nNEXT ACTION\nEND\n\n'`——`BLOCK`行は名前欄が空だったため末尾にスペースのみが残る。全4行とも先頭に空白は無くindent 0で揃っている。)

**構造上の発見**:
1. `BLOCK`はIF/LOOP等と同じ「ヘッダー+本体(indent+1)+END」の素朴なブロック構文だが、制御フロー上の意味は持たない純粋なグループ化マーカー(今回は空のBLOCKなので本体行は無い)。
2. `ON BLOCK ERROR`は`ON ERROR`と**完全に同じ構造**(design/robin_language_source_findings.md既出の`ExceptionCaseStatement`/`ExceptionCaseDefaultStatement`が`Type`プロパティで`"ON ERROR"`/`"ON BLOCK ERROR"`のどちらを出すか切り替えているだけ、という予測通り)——本体のindentはヘッダー自身と同じ(知見34の規則がそのまま適用される)、複数アームが区切り無しに連続しうる、末尾の`END`は1つだけ共有。ここでも「保護対象」は直前の単一アクションではなく、直前の`BLOCK`ブロック全体。
3. `NEXT ACTION`は予測通り`KeywordRecord(name="NEXT", args=["ACTION"])`としてそのまま表現でき、追加のパーサー実装は不要だった(design/robin_language_source_findings.mdの予測が正しかったことが確定)。

**実装**: `pad_dsl_parser.py`に`BlockRecord`(`BLOCK`/`BLOCK <Name>`)・`OnBlockErrorRecord`(`ON BLOCK ERROR`/`ON BLOCK ERROR <CaseName>`)を追加し、`OnErrorArmHeader`を`OnErrorRecord | OnBlockErrorRecord`に拡張、`OnErrorNode`/`GuardedNode`をそのまま再利用(新しいノード型は作らなかった——構造が本当に同一だったため)。`build_block_tree()`に`BlockRecord`用の分岐を追加: 本体を`parse_level(level + 1)`でパースした後、直後に同じlevelの`OnBlockErrorRecord`が続けば`ON ERROR`と同じ「複数アーム+共有END」ロジックでラップして`GuardedNode(node=BlockNode, on_error=OnErrorNode)`にする(続かない場合は素の`BLOCK...END`として扱うフォールバックも用意したが、UIからは「On block error」経由でしかBLOCKを作る手段が無く、この経路は実機未確認のまま)。`pad_codegen.py`では`BlockNode(BlockRecord)`をPython側の制御構文を持たない純粋な本体展開(`try/except`はGuardedNode側が担当)として追加した。

**副産物のバグ修正**: 実装直後に書いた「本体が`NEXT ACTION`だけの`except`節」のテストで`compile()`が`IndentationError`になるのを発見した——`_generate_block_body()`が未対応キーワードを`# TODO`コメント行として出力した場合、その本体は見た目上は非空でもPython構文的には空のsuiteと同じになる(`except:`直後がコメント行だけだと`IndentationError`)、という**既存コードに潜んでいた一般的なバグ**(ON BLOCK ERRORに限らず、`ON ERROR`本体が未知のキーワードだけの場合にも起きていたはず)。全5箇所の`_generate_block_body(...) or [pass]`パターンを、コメント行だけの場合も`pass`を補う`_ensure_nonempty_suite()`ヘルパーに統一して修正した。

**未検証のまま残る拡張**: 名前付き`ON BLOCK ERROR <CaseName>`・名前付きBLOCK(`BLOCK <Name>`)・`ON BLOCK ERROR`を伴わない素の`BLOCK`(UIから作る手段が見つからず)・本体に複数アクションを含む`BLOCK`のindent、はいずれも`ON ERROR`との構造的類推で実装したのみで、実機データでは確認していない。

## 41. 「Throw error」の実機DSL表現を確認——`THROW ERROR`という単純な2トークンのベアキーワード

知見40の続きで、「On block error」ダイアログの「Continue flow run」/「Throw error」トグル(これまで常に「Continue flow run」側しか実機確認していなかった)の「Throw error」側を試した。「Throw error」を選ぶと「Exception handling mode」ドロップダウン自体が消える(「Continue flow run」を選んだ場合にのみ意味を持つ設定のため)。この状態で保存・コピーしたところ:

```
BLOCK 
ON BLOCK ERROR
THROW ERROR
END
```

`THROW ERROR`は`REPEAT ACTION`(知見37)・`NEXT ACTION`(知見40)と全く同じ、2トークンのベアキーワード(`KeywordRecord(name="THROW", args=["ERROR"])`)として表現でき、`_KNOWN_KEYWORDS`に`"THROW"`を追加するだけで対応できた。design/robin_language_source_findings.mdで未検証のまま持ち越していた「Throw error」のDSL表現が、この最小限の追加だけで解決した。

`pad_codegen.py`側は、`THROW ERROR`が意味的には`raise`に対応しそうに見えても、「何を`raise`すべきか」(元の例外の再送出か、何らかの固定メッセージか)が実機から読み取れないため、安易に`raise`をでっち上げず`# TODO: unmapped keyword: THROW ERROR`に倒す(`_generate_keyword()`の既存の汎用フォールバックがそのまま機能する——追加のコード変更は不要だった)。このテストを書いたことで、知見40で修正した`_ensure_nonempty_suite()`(コメント行だけの本体に`pass`を補うバグ修正)が実際に別のケース(このTHROW ERRORのコメントのみの`except`節)でも効いていることを確認できた。

## 42. UI要素セレクタ探索の「ローカル側から行ける手段」を全て潰す——残る手段はクラウド保存(2FA)のみと確定

知見38・39で見つけた「保存済みUI要素リポジトリエントリの実セレクタをPADデザイナーUIから直接見る方法が無い」という行き止まりについて、ユーザーに「一歩下がって大局的に考えて」と言われたのを機に、残っていた非2FA経路を総ざらいした。

1. **「UI elements」パネルの右クリックメニュー「Find usages」**(これまで未クリックだった最後の項目)を試した。結果は単なる使用箇所一覧(`LoopTest Line: 6 Click on UI element Start Button`)だけで、属性やセレクタ情報は一切含まれていなかった。
2. **ローカルファイルシステムの再探索を拡張**: 前回(知見39)は`%LOCALAPPDATA%\Microsoft\Power Automate Desktop`のみを対象に`"Start Button"`文字列でgrepしたが、今回は対象を`C:\ProgramData\Microsoft\Power Automate Desktop`(存在しない)・`%LOCALAPPDATA%\Packages`・`.db`/`.sqlite`/`.sqlite3`/`.ldb`/`.json`拡張子のファイル全件に広げて再探索したが、UI要素リポジトリらしきデータは見つからなかった(見つかった`.json`は全てデザイナーのタブ状態等、知見39で確認済みのものと同種)。
3. **レジストリ探索**(`HKCU:\Software\Microsoft\Power Automate Desktop`配下)も空振り(該当キー自体が存在しない)。
4. **稼働中プロセスの棚卸し**を行い、PADの内部アーキテクチャを把握した: `PAD.Designer.exe`(デザイナーUI)・`PAD.AutomationServer.exe`(×2、実行エンジン)・`PAD.BridgeToUIAutomation2.exe`(×2、UIAブリッジ——おそらくUI要素ピッカーの実体)・`UIFlowService.exe`・`Microsoft.Flow.RPA.LauncherService.exe`等が別プロセスとして稼働している。これらがクライアント側で完結したローカルキャッシュを持たず、保存のたびにクラウド(Dataverseの`workflow`テーブル、research_notes/の調査で確認済み)とやり取りしている可能性が高い構成であることが、プロセス分割からも裏付けられた。

**結論**: UI要素セレクタの実体を取得する手段のうち、**このセッションでエージェント単独(2FA無し)で試せる経路は全て潰した**。残る唯一の既知の経路は、「LoopTest」フローをクラウドに保存すること(2FA承認がユーザーの携帯端末でのみ完了できるため、エージェント単独では実行不可)であり、保存できれば(a) UI要素リポジトリが同期されたDataverse側のデータを何らかの形で覗く、(b) 保存後にPADの「Export」機能やUI要素リポジトリのエクスポート機能が使えるかを確認する、といった次の調査に進める見込みがある。この2FAブロッカーの解消は、UI要素セレクタ対応アクション(Click/SendKeys等、実際のPADフローの大半を占めると推測される種類)をcodegenで実装するための事実上の前提条件であり、ユーザーへの確認が必要な分岐点として記録する。

## 43. 【重大な構造上の発見】個人用Microsoftアカウント(MSA)はPower Platformメーカーポータルに一切アクセスできない——`.msapp`相当の調査経路そのものが個人アカウントでは存在しない可能性

知見42の続き。ユーザー本人に2FA承認してもらい(`cuzic@hotmail.com`、携帯のMicrosoft Authenticatorで番号一致コードを承認)、「LoopTest」フローのクラウド保存に初めて成功した。保存後、ローカルにUI要素リポジトリらしきキャッシュが新たに出現しないか再探索したが、知見39・42同様に見つからなかった(`DefaultValues.json`等、無関係なデザイナー状態ファイルの更新のみ)。PADのFileメニューにもExport機能は無い(Save/Save as/Exitのみ)。

次善策として、ユーザーの許可を得てブラウザ(実機の実際にサインイン済みのEdgeプロファイル)で`make.powerautomate.com`(Power Platformメーカーポータル、research_notes/で「フローはDataverseの`workflow`テーブルに格納される」と調査済みの画面)を`cuzic@hotmail.com`で開こうとしたところ、サインイン後に以下のエラーで拒否された:

```
AADSTS500200: User account 'cuzic@hotmail.com' is a personal Microsoft account.
Personal Microsoft accounts are not supported for this application unless
explicitly invited to an organization. Try signing out and signing back in
with an organizational account.
```

`flow.microsoft.com`(レガシーな個人向けPower AutomateのURL)にアクセスしても同じ`/organizations/`のOAuthエンドポイントにリダイレクトされ、同じ制約にぶつかると推測される(同一エンドポイントへの再サインインフローが再度始まったのを確認し、エラーを確実視するための2回目のサインイン試行は行わなかった)。

**意義**: これは単なる「このティックで見つからなかった」というネガティブな知見ではなく、**プロジェクトの前提そのものに関わる構造的な発見**である。research_notes/の初期調査(`01_flow_file_format.md`)が述べる「フローはDataverseの`workflow`テーブルの`clientdata`列に格納される」という説明は、**組織(Entra ID テナント)に紐づいたDataverse環境を持つ場合の話**であり、`cuzic@hotmail.com`のような**個人用Microsoftアカウント単体でのPAD利用**では、そもそもメーカーポータル自体にアクセスできない——つまりDataverseの`workflow`テーブルを直接覗くという調査経路も、個人アカウントでは成立しない可能性が高い。個人アカウントでのPower Automate Desktop利用が、組織向けとは異なる(簡素化された、Dataverseを介さない)バックエンドに保存されている可能性があり、これは本プロジェクトが前提としてきた「フロー定義の格納場所」の理解そのものを見直す必要があることを意味する。

**今後の調査候補**: (a) 個人向けPower Automateには別の消費者向けポータル面(モバイルアプリ等)が存在する可能性があり、そちらでのフロー閲覧・UI要素リポジトリ参照を試す、(b) 組織アカウント(`rosettaworks`/`seera-networks`等、ユーザーが実際に保有する組織アカウント)でPADにサインインし直してフローを作成・保存すれば、Dataverseベースの経路(メーカーポータル・Dataverse Web API)が使えるようになる可能性がある(ただし今回捕まえた「LoopTest」フロー自体は個人アカウント側にあるため、この経路では別フローでの再検証になる)、(c) そもそも個人アカウントでのPAD利用は本プロジェクトが実際にターゲットとするユーザー層(典型的なPAD個人利用者)の大半を占めると推測されるため、「組織アカウントなら解決する」では実用上の解決にならない可能性が高く、UI要素セレクタ問題の長期的な解決策としては「v1スコープからUI要素アクションを除外し、要素名付きTODOとして出力する」という代替方針の優先度が相対的に上がった。

> **【劇的な訂正】知見44で、本知見の前提だった「クラウド保存/Dataverseアクセスが唯一の経路」という理解そのものが誤りだったと判明した——クラウドを一切介さない、クリップボードコピーだけで済む経路が存在した。**

## 44. 【本プロジェクト最大の発見】複数アクションを一括選択してコピーすると、クリップボードに実際のUI要素セレクタ(JSON)がまるごと含まれることが判明——知見38・39・42・43の「取得不能」という結論を覆す

知見43までの結論(UI要素セレクタの実体はDSLクリップボードテキストに含まれず、取得にはクラウド保存+組織アカウントが必要)を受けて、「一歩下がって大局的に考える」中で浮上した別の課題――「複数アクションの一括コピーがこれまで一度も試されていない(知見1の最初期の4アクション検証以降、常に1〜4個を手作業で個別にコピーしてきた)」――を検証するため、`LoopTest`サブフロー全体(8アクション、`Loop`・`On block error`・`Click UI element in window`・複数行コメントを含む)をキャンバス内で**Ctrl+A(全選択)→Ctrl+C(コピー)**した。

得られたクリップボードテキストは、知見1-43で見てきた「DSLテキスト1本」ではなく、**2つのセクションから成っていた**:

1. 通常のDSLテキスト(`LOOP ... END`等、これまで確認してきた文法そのまま)
2. **区切り行`# [ControlRepositorySymbols` 以降に続く、生のJSONブロック**:

```json
# [ControlRepository][PowerAutomateDesktop]

{
  "ControlRepositorySymbols": [
    {
      "IgnoreImagesOnSerialization": false,
      "Repository": "{\r\n  \"Screens\": [\r\n    {\r\n      \"Controls\": [],\r\n      ...
        \"ElementTypeName\": \"Start Button\",\r\n      \"Name\": \"Start Button\",\r\n
        \"SelectorCount\": 1,\r\n      \"Selectors\": [\r\n        {\r\n
          \"Elements\": [\r\n            {\r\n              \"Attributes\": [],\r\n
              \"CustomValue\": \":startbutton\",\r\n              \"Name\": \"Start Button\",\r\n
              \"Tag\": \"startbutton\"\r\n            }\r\n          ],\r\n ...
      \"ScreenshotPath\": \"controlRepo-screenshots\\\\b75b5751-....png\"\r\n    }\r\n  ],\r\n  \"Version\": 1\r\n}",
      "ImportMetadata": { "DisplayName": "Local computer", "Type": "Local", "DesktopType": "local" },
      "Name": "appmask"
    }
  ],
  "ImageRepositorySymbol": { "Repository": "{...}", "Name": "imgrepo" },
  "ConnectionReferences": []
}
```

(実際の生データは`tests/fixtures/`に保存予定。`Repository`フィールド自体が**文字列化されたJSON**(二重にエンコードされている)である点に注意。)

**意義**: 知見38で発見した`appmask['<表示名>']`という名前参照の`appmask`が、まさにこの`"Name": "appmask"`というリポジトリシンボルを指していることが構造的に確定した。これまで「名前参照先の実体はDSLテキストに含まれない」と結論していたが、それは**1〜4個程度のアクションだけを個別にコピーしていたから**であり、**フロー(またはサブフロー)のアクション群を一括選択してコピーすれば、参照先のUI要素リポジトリ全体(`ControlRepositorySymbols`)がクリップボードに同梱される**という事実を見落としていた。知見39・42・43で追求した「PADデザイナーUI上に閲覧経路が無い」「ローカルにキャッシュされない」「個人アカウントはクラウドポータルにアクセスできない」という調査は、**どれも的外れな方向への探索だった**——正解は終始クリップボードの中にあり、単に十分な範囲を一括選択していなかっただけだった(知見15・26・36と同系統の「少数サンプルでの検証がもっと単純な事実を覆い隠していた」というパターンが、プロジェクト最大の未解決課題についても繰り返されていたことになる)。

**今回捕まえたセレクタの中身についての注記**: 今回の実例(Windowsタスクバーの「Start Button」)は、`Attributes: []`(空)で`CustomValue: ":startbutton"`という**PAD独自の特殊ショートタグ**(OS標準のスタートボタンを指す予約済みの擬似セレクタ)を使っており、通常のUIA属性ベースのセレクタ(知見39で確認した`automationText`/`class`/`controlName`等のPublic Attributes)ではなかった。これは「要素固有の特殊ケース」である可能性が高く、**一般的なアプリ内コントロール(例: メモ帳のボタンやテキストボックス)の`Attributes`配列が実際にどう埋まるか(知見39のPublic Attributesがそのままキー名として使われるのか等)は、まだ別の実例で確認できていない**——このティックで2つ目の`Click UI element`アクションをNotepad上のコントロールに対して追加しようとしたが、Actionsパネルからのドラッグ&ドロップ操作がこのセッションのsynthetic input(win32api経由のマウスイベント)では認識されず、アクションを追加できなかった(「On block error」の時は成功したドラッグ手法が、今回は再現しなかった——原因未調査)。次のティックでの優先課題とする。

**次のアクション(実装済み)**: `pad_dsl_parser.py`に`parse_control_repository()`を追加した。`parse_dsl()`も、この区切り行以降をDSLレコード列から自動的に除外するよう修正済み(除外しないと、一括コピーしたテキストを渡した途端にJSON各行が`RawRecord`の山になって出力が壊れてしまう——`pad2py` CLIに渡す入力が今後「個別コピー」から「一括コピー」に変わっても壊れないようにするための必須の修正)。`pad_codegen.py`側での実際のpywinautoセレクタ生成への配線は、`Attributes`配列の一般形が未確認のため引き続き見送っている。

## 45. 【知見44の副産物・新発見】`BLOCK`が`LOOP`等にネストすると、`ON BLOCK ERROR`のインデントがBLOCK自身の深さと食い違う——知見40の「ENDは1つだけ共有」という結論はトップレベル限定だったと判明

知見44の一括コピーで得た生データを`pad_dsl_parser.py`に通したところ、`LOOP`本体にネストした`BLOCK`(`On block error`を含む)を含む区間で、期待通りにパースできないことが分かった。該当箇所の生テキスト(indent個数を併記):

```
7  (indent0) LOOP LoopIndex2 FROM 1 TO 3 STEP 1
8  (indent1)     Scripting.RunPythonScript.RunPythonScript ...
9  (indent1)     BLOCK 
10 (indent0) ON BLOCK ERROR
11 (indent0) (空行)
12 (indent0) END
13 (indent1)     END
14 (indent1)     UIAutomation.Click.Click Element: appmask['Start Button'] ...
```

`BLOCK`自身は期待通りindent1(LOOPの本体として1段深い)で出力されているが、続く`ON BLOCK ERROR`・その(空の)本体・対応する`END`(12行目)は**indent0**——`BLOCK`自身よりも浅いindent(LOOPと同じ深さ)で出力されている。その後、`BLOCK`自身を閉じるはずの**もう1つの`END`**(13行目)がindent1で別途出力されている。

これは知見40(同種の構造をトップレベル、つまり両方ともindent0の状態でしか実機確認していなかった)で導いた「`BLOCK`と`ON BLOCK ERROR`は1つの`END`を共有する」という結論と矛盾する。indentが一致しないため、トップレベルでは区別のつかなかった「`BLOCK`自身を閉じる`END`」と「`ON BLOCK ERROR`を閉じる`END`」が、ネストした場合は実は**別々の2つの`END`**であり、知見40の「共有」という理解は**たまたま`BLOCK`と`ON BLOCK ERROR`が同じindentで両方とも閉じていたために1つに見えていただけ**だった可能性が高い——あるいは、`ON BLOCK ERROR`のインデント計算自体がPAD側のシリアライザのバグで、本来`BLOCK`と同じ深さになるべきところが常に(文脈に依存せず)誤った深さで出力されている、という可能性もある。いずれが正しいかは今回の1例だけでは判別できない。

**パーサーの挙動(現状維持、意図的に未修正)**: `build_block_tree()`の既存ロジックは、`ON BLOCK ERROR`のindentが直前の`BLOCK`ヘッダーのindentと**完全一致**する場合だけそれを保護対象として紐付ける仕様のため、今回のようにindentが食い違う実例では「孤立した`ON BLOCK ERROR`」として扱われ、直前の兄弟ノード(今回のケースではLOOP全体)を`GuardedNode`でラップしてしまう——意図より広い範囲を`try`/`except`で包んでしまうが、クラッシュはせず、構文的に正しいPythonを生成し続ける(`compile()`は成功する)。取り残された13行目の`END`は`# TODO: unmapped keyword: END`という無害なコメントとして出力される。たった1つの(それも特殊ケースの)実例から場当たり的な「indent不一致でも直前のBLOCKに紐付け直す」という特殊処理を追加すると、確認していない別のケースで誤ってON BLOCK ERRORを紐付けてしまう恐れがあるため、**意図的にパーサーは変更せず**、既知の未解決の構造的な曖昧さとして記録するに留める。`tests/fixtures/looptest_whole_subflow_with_control_repository.txt`(実機生データそのもの)に対する回帰テストで、最低限「クラッシュせず`compile()`可能なPythonを生成する」ことだけは保証する。

## 46. 【知見44の直接の続き】UI要素参照`appmask[...]`は複数階層をエスケープ付きで連結できると判明——ふつうのアプリ内コントロールの`Attributes`配列も初めて実機確認(パーサーバグを修正)

知見44の「一般的なアプリ内コントロールの`Attributes`配列がどう埋まるか未確認」という課題に取り組んだ。既存の`Click UI element in window`アクション(Start Button参照)の編集ダイアログから「UI element」コンボボックス→「Add UI element」でUI要素ピッカーを開き、メモ帳(`notepad.exe`、起動済み)のテキスト編集領域を実機で新たにキャプチャし直した(前回のドラッグ&ドロップでの新規アクション追加は失敗したため、既存アクションの参照先を差し替える経路に変更——成功)。

このとき**ピッカーのhover検出がsynthetic input(単発の`SetCursorPos`)では反応せず**、`win32api.SetCursorPos()`を複数回に分けて段階的に移動させる(知見38のStart Button捕獲時と同じ手法)ことで初めて成功した——単発ジャンプでは検出されない、という運用上の知見も得た。

**新発見その1: `appmask[...]`は複数階層を連結できる**。対象要素が別ウィンドウの子孫の場合、DSLは:

```
Element: appmask['Window \'Untitled - Notepad\'']['Document \'Text Editor\'']
```

という形になった——`['<祖先の表示名>']['<対象の表示名>']`のように`['...']`セグメントが複数連なり、祖先(ウィンドウ)から対象(コントロール)までのパスを表す。さらに、**各セグメントの表示名自体に含まれる`'`は`\'`でエスケープされる**(`Window 'Untitled - Notepad'`という表示名そのものに`'`が含まれるため)。これは「UI elements」パネルのツリー表示("Local computer > Window 'Untitled - Notepad' > Document 'Text Editor'")の各ノード名がそのままパスのセグメントになっていることを意味する。

**パーサーバグその2を発見・修正**: 既存の`_UI_ELEMENT_RE = re.compile(r"appmask\['([^']*)'\]")`は単一セグメントしか想定しておらず、しかも`[^']*`はエスケープを理解しないため、`\'`の直後の`'`で早期にマッチが崩れ、このネスト形式を正しく拾えなかった(実機データで確認済みの、知見15・26・36・38と同種の「フィクスチャの多様性不足」パターンの再発)。`_UI_ELEMENT_RE`を`appmask(?:\['(?:\\.|[^'\\])*'\])+`という、エスケープ済み文字を許容しつつ`['...']`セグメントを1個以上連続してマッチする形に修正し、`UiElementRef`を単一の`name: str`から`path: tuple[str, ...]`(祖先→対象の順)に変更した(`name`は`path[-1]`を返すプロパティとして後方互換を維持)。

**新発見その2: `Attributes`配列の実際の中身(ふつうのコントロールで初確認)**。知見44のStart Button(特殊な`:startbutton`タグ、`Attributes: []`)とは違う、ふつうのUIA属性ベースのセレクタの実例が得られた:

```jsonc
// Window "Untitled - Notepad" のAttributes(抜粋、Ignore:falseのみが実際の絞り込み条件)
{"Name": "Class", "Value": "Notepad", "Ignore": true}
{"Name": "Name", "Value": "Untitled - Notepad", "Ignore": false}
{"Name": "Process", "Value": "notepad", "Ignore": false}
// (Enabled/Id/Ordinal/Visibleは全てIgnore:true)

// Document "Text Editor" のAttributes(抜粋)
{"Name": "Class", "Value": "Edit", "Ignore": false}
// (Enabled/Id/Name/Ordinal/Password/Visibleは全てIgnore:true)
```

各`Attributes`要素は`{Ignore: bool, IsOrdinal: bool, IsDisabledAttribute: bool, Name: str, Operation: str(例:"EqualTo"), Value: any}`という形で、**`Ignore: false`のものだけが実際にPADの要素特定ロジックで使われる絞り込み条件**(ウィンドウは`Name`+`Process`の論理積、コントロールは`Class`のみ)。属性名の語彙(`Class`/`Enabled`/`Id`/`Name`/`Ordinal`/`Password`/`Process`/`Visible`)は、知見39で確認した「UI element picker」の「Public Attributes」パネルの語彙(`automationText`/`class`/`controlName`等、camelCase)とは**別物**——あちらはライブ要素インスペクタの表示用語彙、こちらは実際にリポジトリへ保存されるセレクタ構築用の語彙だと判明した。この語彙(特に`Class`/`Name`/`Process`)はpywinautoの`title`/`class_name`/`process`といった既存パラメータへほぼ1対1で対応しており、将来的に実際のpywinautoセレクタへ変換する際の土台になる。

**今回は実装を見送った部分**: `parse_control_repository()`で取得できる`ControlRepositoryEntry`情報を実際にpywinautoセレクタへ変換する配線は、今回のティックでは行っていない(確認できた実例がまだ2件——特殊ケース1件+通常ケース1件——のみで、複数階層のウィンドウ探索(`Desktop().window(...)` → `.child_window(...)`のチェーン)やWindow以外のコンテナ種別でのAttributes語彙の一般化に確証が持てないため)。`pad_codegen.py`のTODOコメントは、知見46のフルパス(`"Window 'Untitled - Notepad'" > "Document 'Text Editor'"`)を表示するよう更新したのみ。

## 47. 実機でLOOPの範囲両端含む仮定を検証しようとして断念——`Main`が`LoopTest`を一切呼んでいないことが判明

`pad_codegen.py`冒頭から一貫して「未検証の前提」として持ち越している「PADの`LOOP X FROM 1 TO 3 STEP 1`は両端を含むと仮定し`range(start, end+1, step)`としている」という前提を、生成したPythonではなく**PAD自体を実際に実行**して検証しようと試みた。

調査の過程で判明した事実:
- `LoopTest`サブフロー単体を実行する手段(タブの右クリックメニュー・アクション行の右クリックメニュー「Run from here with default values」)はいずれも見当たらない、または常にグレーアウトしていた。
- ツールバーの実行(▶)ボタンをクリックしても何も起きなかった——`Main`に既知のエラー(`For each CurrentItem in TestVar`で`TestVar`がリストでないためのバリデーションエラー、知見に残る「Main subflowの意図的に壊れたアクション」そのもの)が1件でも存在する限り、パッケージ全体の実行がブロックされる仕様だと判明した(Errors listで`Errors (1)`、`Status: Errors found`の表示が常に出ている)。
- `Main`サブフロー(35アクション、知見14のg1g2_testフィクスチャの出どころ)を全て確認したが、**`LoopTest`サブフローを呼び出す「Run subflow」アクションは1つも存在しない**。つまりこのブロッキングエラーを仮に修正して`Main`の実行に成功したとしても、`LoopTest`のLoopは一切実行されない。
- `Main`自身にも`Loop LoopIndex FROM 1 TO 3 STEP 1`(29行目のForEachの直後、31行目)が存在するが、本体が空(内部にアクションが無い)で、カウンタ検証の役には立たない。

**今回は見送った判断**: `Main`の壊れた`For each`を修正し、`LoopTest`を呼び出す「Run subflow」アクションを新たに追加して実行・検証し、終わったら元に戻す、という手順も検討したが、確立済みの`Main`フロー(過去の複数の知見のフィクスチャの出どころ)への変更を伴う上に、「直して→呼び出しを足して→実行して→戻す」という複数ステップの往復が必要になり、このティックの残り時間で安全に完結させる確証が持てなかったため、**今回は実施を見送った**。LOOPの範囲両端含む仮定の実機検証は、専用のティックを設けて取り組むべき独立したタスクとして持ち越す——候補としては、(a) `Main`の修正+`Run subflow`追加+実行+復元を1ティックで計画的に行う、(b) 代わりに全く新しい使い捨てのサブフロー(例: `LoopVerify`)を作り、空の`Main`相当として単独で検証してから削除する、のいずれか。

> **追記**: 知見51で解決済み。実際には(a)よりさらに軽い第三の方法——`Main`自身が元から持つ空の`Loop LoopIndex FROM 1 TO 3 STEP 1`(31行目)にテスト用アクションを直接挿入する——で検証に成功した。

## 48. `ON ERROR`/`ON BLOCK ERROR`最後の未検証項目「Go to label」を実機確認——`LABEL`/`GOTO`という素朴な2トークンキーワード、`GOTO`はPythonに対応物が無いため意図的に未変換

知見41で「Throw error」を確認した際に最後まで持ち越していた「Go to label」オプション(design/robin_language_source_findings.mdが最初に発見した時点から「別のPADの『Label』/『Go to label』アクションと連動する、別の構文が必要になると推測される」と予想されていた項目)を実機確認した。

まず「On block error」ダイアログの「Exception handling mode」を「Go to label」に切り替えると、「Select label」という新しいドロップダウンが現れ、既存に`Label`アクションが1つも無い状態では「No labels available」と表示された——予想通り、別途`Label`アクション(Actionsパネルで"Label"を検索すると「Flow control」カテゴリに見つかる)が必要だった。`Label`アクションを追加(名前「MyLabel」)してからこのドロップダウンを開き直すと、選択肢として表示された。これを選んで保存・一括コピーしたところ:

```
LABEL MyLabel
LOOP LoopIndex2 FROM 1 TO 3 STEP 1
    ...
    BLOCK 
ON BLOCK ERROR
GOTO MyLabel
END
    END
    ...
```

`LABEL <名前>`(`Label`アクション自身)・`GOTO <名前>`(`ON BLOCK ERROR`アーム本体内の「Go to label」)は、いずれも`REPEAT ACTION`/`NEXT ACTION`/`THROW ERROR`と全く同じ、2トークンのベアキーワードだった——design/robin_language_source_findings.mdで事前に確認していた`GoToLabelStatement`/`LabelStatement`相当のソース予測が正しかったことになる。`_KNOWN_KEYWORDS`に`"LABEL"`/`"GOTO"`を追加するだけで`KeywordRecord`としてそのまま表現できた。

**codegen側の判断**: `LABEL <名前>`自体は単なるジャンプ先マーカーなので、位置がわかるよう`# label: <名前>`というコメントとして残す(実行時の意味は持たない、純粋な注釈)。一方`GOTO <名前>`は、Pythonに`goto`文が存在しないため、**意図的に変換しない**——例外(`raise`/`try`)やネストした`while`ループへの書き換えで擬似的に`goto`を再現することもできなくはないが、元のPAD側の制御フローの意図(エラー発生後にどこまで巻き戻るか、ループを再開するのかフロー全体を再試行するのか等)を安全に汲み取れる保証が無いため、他の未対応要素と同じく`# TODO: unmapped keyword: GOTO <名前>`に倒す(`_generate_keyword()`の既存の汎用フォールバックがそのまま機能し、追加のコード変更は不要だった)。

これで design/robin_language_source_findings.md の「今後の調査候補」に残っていた`ON ERROR`/`ON BLOCK ERROR`系の未検証項目(名前付きケース・複数アーム・`REPEAT ACTION`・`NEXT ACTION`・`THROW ERROR`・`Go to label`)は全て実機確認が完了した。

## 49. `IN`/`NOT IN`演算子は標準の「If」アクションのOperatorドロップダウンには存在しないと判明(ネガティブな結果)

design/robin_language_source_findings.mdでソースコード(`ComparisonOperatorExtensions`)から構文(`"NOT IN"`という内部に空白を1つ持つ1つの文字列)を確認し、パーサーにも`_merge_not_in()`で対応済みだったが、「実機でどのUI経由で使えるかはまだ未確認」として持ち越していた項目を確認した。

LoopTestサブフローに実機で「If」アクションを新規追加し、Operatorドロップダウンの全選択肢を確認した(スクロールして最後まで展開): `Equal to (=)` / `Not equal to (<>)` / `Greater than (>)` / `Greater than or equal to (>=)` / `Less than (<)` / `Less than or equal to (<=)` / `Contains` / `Does not contain` / `Is empty` / `Is not empty` / `Starts with` / `Does not start with` / `Ends with` / `Does not end with` / `Is blank` / `Is not blank`。**`Is in`/`Is not in`に相当する選択肢は無かった**。

**結論**: 標準の「If」/「Else if」アクションのUIからは`IN`/`NOT IN`演算子に到達できないことが実機で確認できた。ソースコード上は`ComparisonOperator`列挙型の一部として存在する(ため`_OPERATOR_MAP`には実装済みのまま残す——実際に出現した際に誤変換しないための正しい対応表という位置づけ)が、UI経由で到達可能な別の入口(List/Datatable関連のアクションカテゴリ等)が別途存在するのか、あるいはExpressions経由でのみ到達可能(UI上の専用アクションが無く、将来のバージョンでのみ追加される予定、等)なのかは未確認のまま。本調査では確認したIf アクションのダイアログは変更を保存せず(Cancel)、フローの状態は元のまま(9 Actions)に戻した。

## 50. 【新構文の発見】`[WaitAction]`カテゴリ(「Wait for window」)の実機DSLを確認——`WAIT <seconds>`とは全く別の`WAIT (<ActionId> ...) FOR <秒数>`構文、パーサーバグを即座に発見・修正

design/robin_language_source_findings.mdで逆コンパイルから存在だけ確認していた`[WaitAction]`カテゴリ(`WaitForWindowAction`、`ToBecomeFocusedByTitleClass`/`ToClose`/`ToLoseFocus`/`ToOpen`の4バリアント)を、実機で初めて確認した。Actionsパネルで"Wait for window"を検索すると「UI automation」カテゴリに見つかり(「Windows services」カテゴリには別途「Wait for service」もある)、ダイアログには「Find window: By window UI element」「Window:」「Wait for window to: Open」(ドロップダウン、他の選択肢は未確認)「Focus window after it opens:」(トグル)「Fail with timeout error:」(トグル)という構成だった。「Fail with timeout error」を有効にすると初めて「Duration:」という秒数入力欄(ツールチップ「Time duration in seconds」、既定値5)が現れた——つまりタイムアウト値はこのトグルが有効な場合のみ設定可能。

既存の「Window 'Untitled - Notepad'」UI要素を対象に設定し、「Focus window after it opens」はOFF(既定)のまま、「Fail with timeout error」をON(Duration: 5)にして保存・一括コピーしたところ:

```
WAIT (UIAutomation.WaitForWindow.ToOpen Window: appmask['Window \'Untitled - Notepad\''] FocusWindow: False) FOR 5
```

**最大の発見**: これは`WAIT <seconds>`という既存の単純なベアキーワード(`KeywordRecord`)とは**全く別の構文**だった。`WAIT (<ActionId> <Param>: <Value> ...) FOR <秒数>`——丸括弧で囲んだ、`ActionRecord`と全く同じ`Param: Value`形式のパラメータを持つ「アクション呼び出し風の式」を`WAIT ( ... )`で包み、末尾に`FOR <タイムアウト秒数>`が付く。`action_id`は`UIAutomation.WaitForWindow.ToOpen`——design/robin_language_source_findings.mdでソースから予測していた`ByTitleClass`系と同じ命名パターン(`WindowMode`列挙値`ToOpen`がそのままaction_id末尾になる)が正しかったことも確定した。`FocusWindow: False`という真偽値パラメータは「Focus window after it opens」トグル(既定でOFF)に対応する。

**パーサーの実装**: 既存の`line.split()`による素朴なトークン化では、丸括弧・`FOR`句・内部の`Param: Value`構造を一切解釈できず、`KeywordRecord(name="WAIT", args=["(UIAutomation.WaitForWindow.ToOpen", "Window:", "\x00UIE0\x00", "FocusWindow:", "False)", "FOR", "5"])`という壊れたバラバラの値になった(実際に実装前に確認した)——さらに悪いことに、既存の`_generate_keyword()`はこの`args[0]`をそのまま`time.sleep("(UIAutomation.WaitForWindow.ToOpen")`のように**構文的には正しいが意味的には完全にデタラメなPython**として出力してしまう(`compile()`は通ってしまうため、他のTODO化パターンと違って**サイレントに壊れた変換**になる、知見15・26・36・38・46と同種だが今回は「コンパイルは通るのに実行時に意味不明」という一段質の悪いバグだった)。専用の正規表現`_WAIT_ACTION_RE`(`^WAIT \((.+)\) FOR (.+)$`)で先に検出し、括弧の中身は`ActionRecord`と同じパラメータ解析ループを再利用する`WaitActionRecord`(`action_id`/`params`/`timeout_seconds`)を新設して対応した。

**codegen側の判断**: `UIAutomation.WaitForWindow.ToOpen`はpywinautoの`WindowSpecification.wait("exists", timeout=...)`に自然に対応しそうに見えるが、対象ウィンドウの実セレクタ自体が`Window`パラメータの`UiElementRef`という名前参照でしかなく、知見38・46と同じ制約でDSLから取得できないため、でっち上げたセレクタを埋め込まず、`# TODO: map PAD wait action: <action_id> (timeout: <秒数>s) (UI element: ...)`というTODOコメントに倒す。

**未検証のまま残る項目**: 「Wait for window to」の他の3選択肢(`ToClose`/`ToBecomeFocusedByTitleClass`/`ToLoseFocus`)・「Focus window after it opens」をONにした場合の`FocusWindow: True`表記・「Wait for service」の構文、はいずれも実機未確認。

**追記(同日、別ティック)**: 「Fail with timeout error」をOFFにした場合の挙動を実機確認した。結果は**`FOR`句自体がDSLから丸ごと省略される**(既定のタイムアウト値に置き換わるわけではない):

```
WAIT (UIAutomation.WaitForWindow.ToOpen Window: appmask['Window \'Untitled - Notepad\''] FocusWindow: False)
```

**新たなパーサーバグを発見・修正**: 実装当初の`_WAIT_ACTION_RE = re.compile(r"^WAIT \((.+)\) FOR (.+)$")`は`FOR`句を必須としていたため、この省略形には一切マッチせず、知見50本文で報告した「サイレントに壊れたPythonを生成する」バグ(`time.sleep("(UIAutomation.WaitForWindow.ToOpen")`相当)がこのバリエーションでも再発していた——実装直後に別の変種を実機キャプチャしたことで、確認済みの構文にもまだ別の落とし穴が残っていたことにすぐ気づけた(知見15・26・36・38・46・50と同系統)。正規表現を`^WAIT \((.+)\)(?: FOR (.+))?$`(`FOR`句全体をオプションに)に修正し、`WaitActionRecord.timeout_seconds`は`FOR`句が無い場合`None`のままにした。`pad_codegen.py`側も`render_value(None)`が例外になる問題(`None`は`render_value()`が対応していない値型)に気づき、`timeout_seconds is None`の場合は`"timeout: none"`という専用の表示に分岐させた。

**さらに追記(同ティック内)**: 「Wait for window to」の残り3選択肢を確認した。ドロップダウンの全選択肢は`Open`/`Close`/`Become focused`/`Lose focus`(前回「他の3選択肢は未検証」としていたのが確定)。`Close`を選ぶと、**「Focus window after it opens」トグル自体がダイアログから消える**(意味的に当然——閉じるのを待つ場合はフォーカスする/しないの概念が無い)。`Close`・タイムアウト無しで保存・コピーしたところ:

```
WAIT (UIAutomation.WaitForWindow.ToClose Window: appmask['Window \'Untitled - Notepad\''])
```

`action_id`は予測通り`UIAutomation.WaitForWindow.ToClose`、`params`には`FocusWindow`が存在せず`Window`だけ——既存の汎用パラメータ解析ループ(`ActionRecord`と共有)がそのまま正しく対応できており、追加のコード変更は不要だった。`Become focused`/`Lose focus`の2つは未検証のまま持ち越し(いずれも`ToBecomeFocusedByTitleClass`相当・`ToLoseFocus`という命名パターンになると予測される)。調査後はLoopTestを元の`Open`設定に戻した。

**さらに追記(別ティック)**: 当時「未検証のまま」と記していた「Wait for service」の実機DSLも確認した。ダイアログは「Wait for service to:」(ドロップダウン、既定値「Start」)「Service name:」「Fail with timeout error:」という構成——`If service`(知見54)とほぼ同じ構成だった。既存のサービス名(`Spooler`)を入力して保存・単独コピーしたところ:

```
WAIT (Services.WaitForService.Started Service: $'''Spooler''')
```

action_idは`Services.WaitForService.Started`——知見54の「If service」(`Services.IfService.IsRunning`)と同じ`Services.*`名前空間で、ドロップダウンの値(`Start`)がそのまま`Started`という過去分詞形でaction_id末尾になるパターン(知見50の`WindowMode`列挙値のパターンと同様)。「Fail with timeout error」がOFFのため`FOR`句は無く、単一行のアクションで`If window`/`If service`とは異なり対応する`End`は自動挿入されない(ブロック開始構文ではない、知見50の`WaitActionRecord`全般と同じ)ことも実機確認した。既存の汎用`WAIT (...)`パーサー/codegenのまま、**一切のコード変更無しで**正しく処理できた。

**最後に残っていた「Wait for window to」の2バリアントも確認(別ティック)**: 「Become focused」「Lose focus」を実機確認し、これで4択(Open/Close/Become focused/Lose focus)全てが出揃った。

```
WAIT (UIAutomation.WaitForWindow.ToBecomeFocused Window: appmask['Window \'Untitled - Notepad\''])
WAIT (UIAutomation.WaitForWindow.ToLoseFocus Window: appmask['Window \'Untitled - Notepad\''])
```

いずれも予測通り`ToBecomeFocused`/`ToLoseFocus`という命名パターンで、「Become focused」を選ぶと「Focus window after it opens」トグル自体がダイアログから消える(知見50の`Close`選択時と同じ、意味的に当然の挙動)ことも確認した。両方とも既存の汎用`WAIT (...)`パーサー/codegenのまま、**一切のコード変更無しで**正しく処理できた——これで`[WaitAction]`カテゴリの`WaitForWindowAction`ファミリーは実機検証が完全に出揃ったことになる。

## 51. 【知見47の続き・ついに解決】LOOPの範囲は両端を含まない(`end`を含まない)——`pad_codegen.py`の当初の前提(`range(start, end+1, step)`)は誤りだったと実機確認

知見47で「専用のティックが必要」として持ち越していた、`pad_codegen.py`冒頭から一貫して未検証の前提としていた「PADの`LOOP X FROM 1 TO 3 STEP 1`は両端を含むと仮定し`range(start, end+1, step)`としている」という前提を、知見47で見送った方針(a)(`Main`の修正+`Run subflow`追加ではなく、`Main`自身が元から持つ空の`Loop LoopIndex FROM 1 TO 3 STEP 1`を直接使う、より軽い代替案)で実機検証した。

**手順**:
1. `Main`サブフロー(35アクション)の唯一のブロッキングエラー(知見47で確認済みの、29行目`For each CurrentItem IN TestVar`——`TestVar`が文字列でリスト/データテーブルではないため)を、右クリック「Disable action」で無効化。対応する`End`(30行目)も同様に無効化しないと「No statement found to match the end statement」という別の検証エラーが出ることが分かり、両方を無効化してようやく`Main`の検証エラーがゼロになった(知見47で発見した「パッケージ全体の検証を通過する必要がある」という制約への対処)。
2. `Main`が元から持つ空の`Loop LoopIndex FROM 1 TO 3 STEP 1`(31行目、知見47で「本体が空」と記録していたもの)の内部に、ファイルへ1文字追記する`Run Python script`アクションをドラッグ&ドロップで追加(Actionsパネルからの複数ステップの細かいマウス移動が必要だった。コンテナのヘッダー行にドロップすると兄弟要素として挿入されてしまうため、ヘッダー行と`End`行の間の狭い隙間に2回目のドラッグを行い、ループ内部への挿入に成功した)。
3. カウンタファイル(`C:\Users\tomoya_kaw\pad2py\loop_range_check.txt`)が存在しない状態から、ツールバーのRun(▶)で`Main`を実行。実行中はステータスバーに「Status: Running HH:MM:SS」、「Variables」パネルに`LoopIndex`のライブな値が表示された。フロー序盤の`Display message`アクションが実際にWindowsのメッセージボックスを表示するため、OKボタンで手動で閉じて実行を継続させた。
4. 実行完了後、WinRM経由で`[System.IO.File]::ReadAllBytes('C:\Users\tomoya_kaw\pad2py\loop_range_check.txt')`を実行し、ファイルの生バイト列を直接確認した。結果は`120, 120`——ASCIIで`"xx"`、つまり**ちょうど2回**の書き込みだった。

**結論**: 「1 TO 3 STEP 1」という名目のループが実際に実行したのは`LoopIndex=1, 2`の2回のみで、`LoopIndex=3`は実行されなかった。これは**PADのLOOPが`end`を含まない**(Pythonの`range(start, end, step)`と全く同じセマンティクス)ことを直接示す、紛れのない実機証拠である。`pad_codegen.py`が当初から掲げていた「両端を含む」(`range(start, end+1, step)`)という前提は**誤り**だったと確定した。

**修正内容**: `pad_codegen.py`の`_generate_loop_block()`における`LoopRecord`分岐のコード生成を
```python
header_line = f"{prefix}for {header.loop_var} in range({start}, ({end}) + 1, {step}):"
```
から
```python
header_line = f"{prefix}for {header.loop_var} in range({start}, {end}, {step}):"
```
に修正し、モジュールdocstringの該当箇所も「未検証の前提」から本知見を指す「実機検証済み」の記述に更新した。既存テスト`tests/test_pad_codegen.py::test_generate_python_renders_loop_family`のアサーション(`"for LoopIndex in range(1, (3) + 1, 1):"`)も新しい文字列に更新した。

**検証後の後始末**: `Main`は`For each`/`End`を再度「Enable action」で有効化し、元の単一の検証エラー(知見47記載のもの)のみに戻した。追加した`Run Python script`アクションは削除。カウンタファイル`loop_range_check.txt`はWinRM経由で削除(`Test-Path`で`False`を確認)。アクティブなデザイナータブは「LoopTest」に戻した——`Main`自体は本検証以前の状態に完全復元されている。

**教訓**: 知見47で一度は「安全に完結させる確証が持てない」として見送った複数ステップの往復(無効化→挿入→実行→削除→有効化→復元)も、各ステップを慎重に確認しながら進めれば1ティック内で完結でき、かつ実機の生バイト値という最も紛れのない形の証拠が得られた。これまで`pad_codegen.py`に長期間残っていた「未検証の前提」コメントの中でも、プロジェクトのコード生成結果に直接影響する(オフバイワンのバグを生成し続けていた)最も重要な項目が、ついに解消された。

## 52. 【新発見】「Wait for window」とは別の新アクション「Wait for window content」を発見——`WindowToContainElement`というaction_id、既存の`WAIT (...)`汎用パーサー/codegenのままコード変更無しで対応できた

知見50で「Wait for window」の実機DSLを確認した際、Actionsパネルで"Wait for window"を検索すると「UI automation」カテゴリに**2件**ヒットすることに気づいていなかった。今回検索結果を展開して初めて2件あることを確認し、それぞれのツールチップを確認したところ、全く別のアクションだと判明した:

- 1件目(知見50で確認済みの「Wait for window」): 「Suspends the execution or the process until a specific window opens, closes, get or loses the focus」——ウィンドウ自体の開閉・フォーカスを待つ。
- 2件目(**今回新発見**「Wait for window content」): 「Suspends the execution of the automation until a specific piece of text or UI element appears or disappears from a Window」——ウィンドウ**内のテキストやUI要素の出現/消失**を待つ、全く別の機能。

2件目をキャンバスにドラッグすると、ダイアログタイトルは「Wait for window content」、構成は「Wait until window:」(ドロップダウン、既定値「Contains UI element」、他の選択肢は未確認)「Check UI element state:」(トグル)「UI element:」(UI要素ピッカー)「Fail with timeout error:」(トグル、知見50と同じくONで初めてDurationが現れると推測されるが未確認)。既存のUI要素リポジトリから「Document 'Text Editor'」(Notepadのテキストエリア)を選択して保存・一括コピーしたところ:

```
WAIT (UIAutomation.WaitForWindowContent.WindowToContainElement Element: appmask['Window \'Untitled - Notepad\'']['Document \'Text Editor\''])
```

**重要な確認結果**: action_idは`UIAutomation.WaitForWindowContent.WindowToContainElement`——知見50の`UIAutomation.WaitForWindow.*`ファミリーとは全く別の名前空間(`WaitForWindowContent`)だが、DSLの構文自体は知見50で発見した`WAIT (<ActionId> <Param>: <Value> ...) FOR <秒数>`(FOR句は省略可能)を完全にそのまま再利用していた。知見50実装時に`_WAIT_ACTION_RE`/`WaitActionRecord`/`_generate_wait_action()`をaction_idに依存しない汎用設計にしていたため、**パーサー・codegenとも一切のコード変更無しで**正しく`WaitActionRecord(action_id="UIAutomation.WaitForWindowContent.WindowToContainElement", params={"Element": UiElementRef(...)}, timeout_seconds=None)`としてパースされ、`# TODO: map PAD wait action: ...`という同じ安全なフォールバックでcodegenされることを確認した(`tests/fixtures/looptest_whole_subflow_with_wait_for_window_content.txt`で実機キャプチャをそのままテスト化、新規追加コード無し)。

**未検証のまま残る項目**: 「Wait until window:」ドロップダウンの他の選択肢(「Contains UI element」以外に何があるか)・「Check UI element state」トグルをONにした場合に追加される設定項目・「Fail with timeout error」ON時のタイムアウト値表記・「UI要素が消える」ケース(Containsの逆、"Does not contain"のような選択肢があるか)は、いずれも実機未確認のまま持ち越し。

**教訓**: 知見50で確立した「action_idに依存しない汎用WaitActionパーサー」という設計判断が、今回の全く別系統の新アクション発見でそのまま活きた——個別のaction_idをハードコードせず、共通の構文パターン(`WAIT (...)`)を抽象化しておいたことで、実機で新しい具体例が見つかってもパーサー/codegenの変更が一切不要という結果になった。これは本プロジェクトが知見36以来重ねてきた「架空のPython APIを決してでっち上げない、TODOへの安全なフォールバックを徹底する」という方針が、未知の新アクションに対しても自動的に安全側に倒れることを示す実例でもある。

## 53. 【重要な訂正・新発見】`AND`/`OR`/`XOR`/`NOT`複合条件・算術式(`+`/`-`/`*`/`/`/`mod`)の実機DSL表現を確認——`SET ... TO`がサイレントに右辺を切り捨てていたパーサーバグを修正

design/robin_language_source_findings.mdがANTLR文法(`Language.cs`の`ExpressionContext`サブクラス群)から「存在するはず」と予測しつつ実機未検証のまま持ち越していた、`AND`/`OR`/`XOR`/`NOT`による複合条件式と`+`/`-`/`*`/`/`/`mod`による算術式を、ついに実機で確認した。

**調査の発端**: 知見49で「標準の『If』アクションのOperatorドロップダウンにはIN/NOT INが無い」と確認済みだったので、今回はその続きとして「If」アクションのダイアログを改めて確認した。ダイアログは「First operand」「Operator」(ドロップダウン)「Second operand」の3項目だけで、複数条件を追加する「+」ボタンや「Group」のような入れ子構造は一切無いことを確認した(Operatorドロップダウンを全スクロールし、16種類——`=`/`<>`/`>`/`>=`/`<`/`<=`/`Contains`/`Does not contain`/`Is empty`/`Is not empty`/`Starts with`/`Does not start with`/`Ends with`/`Does not end with`/`Is blank`/`Is not blank`——で全てであることも確認、robin findingsの「16択」という予測が正しかったと裏付けられた)。

これは「複合条件はIf自身のUIでは組み立てられず、式として直接書くしかない」という仮説を裏付けたため、「Set variable」アクションの「Value」欄に直接`%1 = 1 and 2 = 2 or not 3 = 4%`という式を入力・保存・一括コピーしたところ:

```
SET NewVar3 TO 1 = 1 AND 2 = 2 OR NOT 3 = 4
```

**確認できた事実**:
- `AND`/`OR`/`NOT`は小文字で入力しても**大文字に正規化**されて保存される(アクションカードのプレビュー表示でも、ダイアログを再度開いたときの表示でも、一括コピーしたDSLでも、常に大文字`AND`/`OR`/`NOT`)。
- 括弧も明示的に書けばそのまま保持される:`%(1 = 1 xor 2 = 2) and (3 = 3)%` → `SET NewVar3 TO (1 = 1 XOR 2 = 2) AND (3 = 3)`。`XOR`も同じく大文字に正規化される。
- 算術演算子`+`/`-`/`*`/`/`はそのまま記号で出力され、`mod`は**小文字のまま正規化されない**(`AND`/`OR`/`XOR`/`NOT`とは異なる挙動):`%1 + 2 * 3 - 4 / 2 mod 3%` → `SET NewVar3 TO 1 + 2 * 3 - 4 / 2 mod 3`。
- いずれも単純な空白区切りの単一行で直列化されており、新しい構文パターン(`WAIT (...)`のような専用の括弧構文)は不要で、既存の`SET <var> TO <式>`の枠組みのままトークン列が伸びるだけだった。

**発見された重大なパーサーバグ**: この複合式を実際にパースしてみたところ、`pad_dsl_parser.py`の`SET`文パース処理が`tokens[3]`(4番目のトークン、ここでは`"1"`)**1つだけ**を値として読み、`len(tokens) >= 4`という条件(`== 4`ではなく`>= 4`)のまま残りのトークン(`= 1 AND 2 = 2 OR NOT 3 = 4`)を**サイレントに切り捨てていた**ことが判明した。`SET NewVar3 TO 1 = 1 AND 2 = 2 OR NOT 3 = 4`が`SetVariableRecord(var_name='NewVar3', value=1)`という、見た目は正常でも意味的には完全に誤ったレコードにパースされてしまう——知見15・26・36・38・46・50と同系統の「気付かれにくいデータ消失バグ」だが、今回は複合式という頻出しうる構文で発生する分、影響範囲が広い。

**修正内容**: `pad_dsl_parser.py`に新しい`RawExpr`マーカー型(`text: str`)を追加し、`SET`文の右辺トークン数が1個なら従来通り`_resolve_value()`で単一値として解決、2個以上なら全トークンを`_stringify_resolved_expr_token()`で個別に可読テキスト化して空白連結した`RawExpr`として保持するよう修正した(`_render_raw_expr()`)。`AND`/`OR`/`NOT`/`XOR`やmodのような裸キーワードは`VarRef`経由でそのまま往復し、プレースホルダ由来の文字列・UI要素参照も可読な形で再構成されるため、3つの実機キャプチャ例全てで元のDSLテキストと完全に一致する`RawExpr.text`が得られることをテストで確認した。

**codegen側の判断**: PADの演算子優先順位(特に`AND`/`OR`/`XOR`の優先順位がPythonの`and`/`or`と一致するか、`XOR`のPython対応——Pythonに`xor`という論理演算子キーワードは無く`!=`や`^`で代用する場合に境界値で意味論が食い違わないか、`mod`が負数に対してPythonの`%`と同じ挙動かなど)がいずれも実機未検証のため、でっち上げた変換式を出力せず、`# TODO: map PAD compound expression for variable '<var>': <元のPAD式テキスト>`というコメントと`<var> = None`という安全なフォールバック代入の2行を出力するに留めた(知見50の`WaitActionRecord`と同じ「安全側TODOフォールバック」の方針)。

**未検証のまま残る項目**: PADの演算子優先順位の正確な規則(括弧なしで`AND`と`OR`を混在させた場合の評価順序)・`XOR`の正確なPython対応・`mod`の負数での挙動・文字列結合としての`+`との曖昧性、はいずれも実機未確認のまま持ち越し。これらを確認してから初めて、`RawExpr`から実際のPython式への機械的変換(例えば`ast`ベースの小さな式トランスレータ)を実装する価値がある。

## 54. 【新発見・重要なパーサーバグ修正】`[ConditionAction]`カテゴリ(「If window」等)の実機DSLを確認——知見50の`WAIT (...)`と同じ丸括弧構文を条件式として再利用、`IfRecord`への誤パースを修正

design/robin_language_source_findings.mdが「ConditionActionカテゴリ(`IfWindowAction`の`IsFocusedByTitleClass`等)が実機で本当にIfFunctionRecord形式のDSLを生成するかの確認」として持ち越していた項目を、知見53の調査中にActionsパネルで偶然見つけた「If window」アクションから実機確認した。

Actionsパネルで"If window"を検索すると、「UI automation」カテゴリに「If window」「If window contains element」が、「Windows services」カテゴリに「If service」が見つかった(design/robin_language_source_findings.mdが予測していた`IfWindowAction`系そのもの)。「If window」をキャンバスに追加すると「Get window: By window UI element」(ドロップダウン)「Window:」(UI要素ピッカー)「Check if window: Is open」(ドロップダウン、他の選択肢は未確認)という構成だった。既存の「Window 'Untitled - Notepad'」UI要素を選択して保存したところ、**PADはこのアクション単体で自動的に対応する`End`も挿入した**(=`IF`/`LOOP`等と同じブロック開始構文であることが構成UIの時点で確定した)。一括コピーした結果:

```
IF (UIAutomation.IfWindow.IsOpen Window: appmask['Window \'Untitled - Notepad\''] InstantCheck: False) THEN
```

**確認できた事実**: これは知見18-2で確認済みの`IfFunctionRecord`形式(`IF Contains(a, b, False) THEN`——関数名の直後に空白無しで`(`が続き、中身は位置引数のカンマ区切り)とは**全く別の第3の条件表現パターン**だった。実際には知見50の`WAIT (<ActionId> <Param>: <Value> ...) FOR <秒数>`と完全に同型で、`IF`/`THEN`に置き換わっただけ——`IF (<ActionId> <Param>: <Value> ...) THEN`という、`ActionRecord`と同じ`Param: Value`形式のパラメータを丸括弧で包んだ条件式だった。`action_id`は`UIAutomation.IfWindow.IsOpen`、`InstantCheck`という真偽値パラメータ(「Check if window」のドロップダウンには表示されない隠しパラメータ、おそらく即時チェックか待機を伴うかのフラグ)も確認できた。

**発見された重大なパーサーバグ**: 当時この構文に対応する専用の解析ロジックが存在しなかったため、既存の`IfRecord`(固定位置の`operand1 operator operand2`形式)の解析ロジックが誤ってマッチし、`IfRecord(operand1=VarRef('(UIAutomation.IfWindow.IsOpen'), operator='Window:', operand2=VarRef('\x00UIE0\x00)'))`という意味不明な値にパースされてしまっていた——知見50のWAIT文で最初に発生したのと全く同じ「新しい丸括弧構文を既存の固定位置パーサーが誤認識する」というバグパターンの再発だった。

**修正内容**: 新しい正規表現`_IF_ACTION_RE = re.compile(r"^(IF|ELSE IF) \((.+)\) THEN$")`と、新しいレコード型`IfActionRecord`/`ElseIfActionRecord`(`action_id`/`params`)を追加した。`WaitActionRecord`と`IfActionRecord`/`ElseIfActionRecord`で共通のパラメータ解析ロジックを`_parse_action_call_body()`という共通ヘルパーに切り出し、両方から再利用するようにリファクタリングした。`build_block_tree()`の`_IF_HEADER_TYPES`/`_ELSEIF_HEADER_TYPES`にも新しい型を追加し、`IF (...) THEN`が`IfFunctionRecord`や`IfRecord`と同じ条件分岐ブロックのヘッダーとして正しく扱われるようにした。

**codegen側の判断**: 対象UI要素のセレクタ自体がDSLから取得できない(知見38・46と同じ制約)上、条件式の意味論を誤訳すると制御フロー全体(`if`に入るかどうか)が反転するという、知見53の`SET`文の右辺よりもさらに危険な失敗モードになる。そのため、知見18-2の`IfFunctionRecord`と全く同じ方針——でっち上げた真偽値を出力せず`NotImplementedError`を送出してはっきり失敗させる——を踏襲した。

**追記(同ティック内)**: 「Check if window」ドロップダウンの全選択肢を確認した。「Is open」「Isn't open」「Is focused」「Isn't focused」の4択で全てだった。「Is focused」を選んで保存・一括コピーしたところ`UIAutomation.IfWindow.IsFocused`、「Isn't open」では`UIAutomation.IfWindow.IsNotOpen`——`InstantCheck`のような共有パラメータで否定を表すのではなく、**4つの選択肢それぞれが別々のaction_id**(`IsOpen`/`IsNotOpen`/`IsFocused`/`IsNotFocused`、最後の1つは未検証だが命名パターンから確実視)になることを確認した。design/robin_language_source_findings.mdが予測していた`IsFocusedByTitleClass`という名前ではなく、単純な`IsFocused`だった。

**さらに追記(別ティック)**: 「If window contains element」の実機DSLも確認した。「If window」とは別のアクション(ダイアログは「Check if window: Contains UI element」「Check UI element state」トグル「UI element:」ピッカーという構成——知見52の「Wait for window content」とよく似ている)だが、保存・一括コピーしたところ:

```
IF (UIAutomation.IfWindowContains.WindowContainsElement Element: appmask['Window \'Untitled - Notepad\'']['Document \'Text Editor\''] InstantCheck: False) THEN
```

action_idは`UIAutomation.IfWindowContains.WindowContainsElement`——`UIAutomation.IfWindow.*`とは別の名前空間(`IfWindowContains`)だが、DSL構文は同じ`IF (<ActionId> ...) THEN`をそのまま再利用しており、これも**パーサー・codegenとも一切のコード変更無しで**正しく処理できた(`tests/fixtures/looptest_whole_subflow_with_if_window_contains_element.txt`で実機キャプチャをそのままテスト化)。知見52(`WAIT`側の`WaitForWindowContent`発見)と完全に対になる発見で、「action_idに依存しない汎用パーサー設計」が`WAIT`・`IF`の両方で未知の新アクションに対して自動的に安全側に倒れることを改めて実証した。

**さらに追記(別ティック)**: 「If service」(Windows servicesカテゴリ)の実機DSLも確認した。ダイアログは「If service: Is running」(ドロップダウン)「Service name:」(テキスト)という単純な構成。既存のサービス名(`Spooler`)を入力して保存・単独コピーしたところ:

```
IF (Services.IfService.IsRunning Service: $'''Spooler''') THEN
```

**重要な発見**: これまでの`[ConditionAction]`/`[WaitAction]`の実機キャプチャは`UIAutomation.*`名前空間ばかりだったが、「If service」は初めて見る**`Services.*`という別の名前空間**だった(`Services.IfService.IsRunning`)。UI要素を伴わないアクションのため、単独コピーでは`# [ControlRepository][PowerAutomateDesktop]`ブロックが付かないことも確認できた(知見44の「全選択時のみ付く」という理解と整合)。Service nameはUI要素参照(`appmask[...]`)ではなく、通常のプレースホルダ文字列(`$'''Spooler'''`)として渡される——既存の汎用パーサー/codegenロジックのまま、**一切のコード変更無しで**正しく処理できた。

**未検証のまま残る項目**: `IsNotFocused`(未検証だが命名パターンから確実視)・`InstantCheck`パラメータの正確な意味・「If service」の他の選択肢(「Is running」以外に何があるか、知見50/54の`Is open`/`Isn't open`のようなペアが存在すると予測される)は、いずれも未確認のまま持ち越し。~~「If image」の実機DSL表現~~ → 完了(知見58)。

## 55. 【重大なパーサーバグ修正】変数のドット付きプロパティアクセス(`VariableTrailer`)が`EnumRef`に誤分類され文字列リテラルへすり替わるバグを発見・修正

design/robin_language_source_findings.mdが`EnumRef`型のdocstring内に「既知の未解決の曖昧性」として明記していた懸念——PADの変数参照自体にも`.Name`のようなドット区切りの「トレーラ」(配列/カスタムオブジェクトのプロパティアクセス、例: `MyDataTable.Rows`)が存在しうるが、これは`Namespace.Enum.Value`形式のEnumRefと文字面上区別がつかない、という問題——が、実機キャプチャによってついに実例として確認された。

**発端**: 知見54の調査中に見つけた`InnerVar[0]`のような添字アクセス記法を実機確認する過程で、ドット付きのプロパティアクセスも併せて検証した。「Set variable」のValue欄に`%InnerVar.SomeProperty%`という式を入力・保存・一括コピーしたところ:

```
SET NewVar3 TO InnerVar.SomeProperty
```

これは既存の全EnumRef capture(`Display.DefaultButton.Button1`等)と全く同じ`identifier.identifier`という見た目だった。パーサーの挙動を確認したところ、案の定`EnumRef('InnerVar.SomeProperty')`として誤分類され、`pad_codegen.py`の`render_value()`はEnumRefを「未対応の列挙値」として`repr(value.value)`——つまり**文字列リテラル**`'InnerVar.SomeProperty'`として出力していた。本来は変数`InnerVar`のプロパティ`SomeProperty`への参照のはずが、ただの固定文字列にすり替わってしまう、気付かれにくいが深刻な意味論破壊バグだった。

**修正の根拠**: これまでに実機キャプチャした全てのEnumRef値(`Display.DefaultButton.Button1`/`Display.Buttons.OK`/`Display.Icon.None`/`MouseAndKeyboard.MouseClickType.LeftClick`/`MouseAndKeyboard.MovementStyle.Instant`/`MouseAndKeyboard.PositionRelativeTo.Screen`/`UIAutomation.ClickType.LeftClick`)、および全action_id(`MouseAndKeyboard.SendMouseClick.Click`等)を`tests/`・`dump_daemon/`・`tests/fixtures/*.txt`から再調査したところ、**例外なく全て`Namespace.Enum.Value`というちょうど3セグメント(ドット2個)**だった。一方、今回実機確認した`VariableTrailer`は`InnerVar.SomeProperty`という**2セグメント(ドット1個)**。この実績の差に基づき、EnumRef判定専用の新しい正規表現`_ENUM_REF_RE`(ドット2個以上を要求)を追加し、`_resolve_value()`のEnumRef判定をこちらに切り替えた。2セグメント(ドット1個)の場合は`VarRef`にフォールバックするよう修正した——`VarRef`のcodegen(`render_value()`)は`value.name`をそのままPython識別子として埋め込むため、`InnerVar.SomeProperty`は`InnerVar.SomeProperty`という(構文的に)正しいPython属性アクセス式として生成される。

**添字アクセスも確認**: `%InnerVar[0]%`という式も同じ手順で確認した。`SET NewVar3 TO InnerVar[0]`というDSLが得られたが、これは元々ドットを含まないため`_DOTTED_RE`/`_ENUM_REF_RE`のどちらにもマッチせず、修正前から既に`VarRef(name='InnerVar[0]')`として正しく保持されていた——codegenも`InnerVar[0]`という有効なPython式(リスト/辞書の添字アクセスと同じ構文)を偶然にも正しく生成できていた。

**未検証のまま残る項目**: この修正は完全な曖昧性解消ではない——3セグメント以上の`VariableTrailer`(`MyObj.Prop1.Prop2`のような多段プロパティアクセス)や2セグメントの`EnumRef`が実在すれば依然として誤判定しうる、実機証拠に基づく暫定的な最善の判断に留まる。添字`[0]`が0始まりか1始まりか(知見51のLOOP range同様、実機での動作確認が必要)、`VariableTrailer`がリスト/データテーブル/カスタムオブジェクトのどの型でどう振る舞うか、はいずれも未確認のまま持ち越し。

## 56. 【本プロジェクト2番目に大きい発見】知見46で確認したAttributes(Class/Name/Process)から実際にpywinautoセレクタを組み立て、実機で実要素を一意に特定できることを初めて実証——`pad_codegen.py`が初めて「架空でない」UI要素セレクタ提案を出力するようになった

知見46で「`ControlRepositoryEntry`情報を実際にpywinautoセレクタへ変換する配線は、確認できた実例がまだ2件のみのため実装を見送った」としていた課題に、改めて取り組んだ。これまでは`appmask[...]`のデータ(表示名・`Attributes`配列)を**取得できる**ことまでは実機確認済みだったが、そのデータから組み立てたpywinautoセレクタが**実際に実機の本物の要素を正しく特定できるか**は一度も検証していなかった——「データの実在」と「データの有用性」は別の主張であり、後者がこのプロジェクトにとって最終的に一番重要な問いだった。

**検証方法**: `pad_run`(clipwireの対話的セッション内pywinauto実行)経由で、知見46でキャプチャ済みの実際の属性値をそのまま使ったpywinautoコードをVM上で直接実行した:

```python
from pywinauto import Desktop
d = Desktop(backend="uia")
win = d.window(title="Untitled - Notepad")  # 知見46のWindow Attributes: Name(Ignore:false)
print(win.exists())  # → True
edit = win.child_window(class_name="Edit")  # 知見46のDocument Attributes: Class(Ignore:false)
print(edit.exists())  # → True
```

**結果**: `win.exists()`/`edit.exists()`ともに`True`——`title="Untitled - Notepad"`だけ(`Process`属性は使わずとも)で実際のメモ帳ウィンドウを一意に特定でき、そこから`child_window(class_name="Edit")`で実際のテキスト編集領域も一意に特定できることを実機で確認した。`win.element_info.class_name`は`"Notepad"`(PAD側では`Ignore: true`だが実際の値としては整合)、`win.element_info.process_id`から`psutil`で引いたプロセス名は`"notepad.exe"`(PAD側の`Process: "notepad"`と拡張子以外一致)だった。これは知見46で「将来的に実際のpywinautoセレクタへ変換する際の土台になる」と予測していた`Class`/`Name`/`Process`属性の対応付けが**実際に機能する**ことを示す、初めての実機的根拠である。

**実装内容**: `pad_codegen.py`の`generate_python()`に任意の`repository`引数(`parse_control_repository()`の戻り値)を追加した。各`UiElementRef.path`のセグメントをリポジトリ内のエントリ名と照合し、各エントリの`selectors[0][0].attributes`から`Ignore: False`の属性だけを`Class`→`class_name`/`Name`→`title`に対応付けて(`Process`属性はpywinautoの`window()`/`child_window()`がプロセス**名**を直接受け付けない——`process=`はPIDを要求するため、意図的に使わない)、`Desktop(backend="uia").window(...)`から始まり`.child_window(...)`を連ねるセレクタ式の文字列を組み立てる(`_build_pywinauto_selector_expr()`)。リポジトリに情報が無い・使える属性が1つも無い(知見44の`:startbutton`のような特殊タグで`Attributes`が空の場合等)場合は`None`を返し、呼び出し元は何も付け足さない——**でっち上げたセレクタを返すことは無い**。

この提案は、既存の`# TODO`コメント(`_ui_element_hint()`)に`; verified pywinauto selector: <式>`として**追記するだけ**であり、生成される実行コード自体(`# TODO`行そのもの)は一切変えていない——あくまで「ユーザーが手動でTODOを埋める際の、実機検証済みの出発点」を提供するに留め、「このコードは動く」という誤った確信を与えないようにした。`pad2py_cli.py`の`convert()`も、入力テキストから自動的に`parse_control_repository()`を呼んで`generate_python()`へ橋渡しするよう更新したため、ユーザーは一括コピーした生データをそのまま`pad2py`コマンドに渡すだけでこの提案を得られる(追加の手順は不要)。

実例(知見52の「Wait for window content」フィクスチャに対する実際の出力):

```python
# TODO: map PAD wait action: UIAutomation.WaitForWindowContent.WindowToContainElement (timeout: none) (UI element: "Window 'Untitled - Notepad'" > "Document 'Text Editor'"; selector not available from DSL, see knowledge 38/39/42/43/46 — fill in manually; verified pywinauto selector: Desktop(backend="uia").window(title='Untitled - Notepad').child_window(class_name='Edit'))
```

**設計上の判断(後方互換性)**: `generate_python()`の`repository`引数は省略可能(既定`None`)で、深く再帰する内部のcodegenヘルパー群全ての関数シグネチャを変更するのを避けるため、`generate_python()`の呼び出し期間中だけ有効なモジュールレベルの状態(`_active_repository`、`try`/`finally`で必ず復元)として実装した——`generate_python()`は単一スレッド・同期実行・非再入の公開APIである前提に基づく意図的なトレードオフ。省略時は既存の全167件のテストが無改修でそのまま通ることを確認済み(完全な後方互換)。

**未検証のまま残る項目**: 今回実機確認できたのは「ウィンドウ+直接の子コントロール」という2階層の組み合わせ1パターンのみ。3階層以上のネスト・`Window`以外のコンテナ種別(ダイアログ等)での`Attributes`語彙の一般化・複数の同名候補が存在する場合の曖昧性解消(`found_index`等)は、いずれも実機未検証のまま持ち越し。

**追記(別ティック・重大なバグを発見・即修正)**: 「3階層以上のネスト」の実例を得るため、電卓(`calc.exe`、クラシック版、`win32calc.exe`)を起動し、UI要素ピッカーで「7」ボタンを新たに実機キャプチャした(`appmask['Window \'Calculator\'']['Button \'7\'']`)。このとき、**1つの`ControlRepositoryEntry`自体の`selectors[0]`が複数の`ControlRepositorySelectorElement`からなる内部チェーンになりうる**という、知見44・46では一度も見たことのなかった構造に初めて遭遇した——「Button '7'」エントリの中身は`pane(Class: CalcFrame)` → `button(Class: Button, Name: 7)`という2段チェーンだった(これまでの全実例は`len(selectors[0]) == 1`、チェーンの長さ1のみ)。

直前に実装したばかりの`_build_pywinauto_selector_expr()`は`entry.selectors[0][0]`(チェーンの**最初の1要素だけ**)しか見ていなかったため、この新しい実例に対しては`child_window(class_name="CalcFrame")`という式で止まってしまっていた。実機で確かめたところ、これは**ボタンではなく中間の`pane`要素**(`control_type: Pane`)に解決されてしまうことが分かった——知見56本文の主張(「実機で実要素を一意に特定できる」)が、新しい実例では成立しない状態のまま見過ごされるところだった。

**修正**: チェーン内の各`ControlRepositorySelectorElement`を、それぞれ別個の`.child_window(...)`呼び出しとして連ねるよう修正した(1つの呼び出しにまとめず、PAD自身の内部チェーン構造を1対1でそのまま複製する——異なる階層要素が同じ属性名を異なる値で持つ場合に、まとめてしまうとどちらかの値をサイレントに失う恐れがあるため)。修正後、実機で以下の式が電卓の実際の「7」ボタン(`control_type: Button`, `name: 7`)を正しく一意に特定できることを確認した:

```python
Desktop(backend="uia").window(title="Calculator").child_window(class_name="CalcFrame").child_window(class_name="Button", title="7")
```

(参考: 中間の`pane`を飛ばして`win.child_window(class_name="Button", title="7")`と直接書いても実機では同じボタンに解決されたが、これはpywinautoの`child_window()`が子孫を再帰的に検索する実装上の性質に依存した挙動であり、PAD自身が明示しているセレクタ構造ではないため、採用せずPADの内部チェーンをそのまま複製する方を選んだ。)

**教訓**: 知見56は「実機で動くことを確認した」ことを謳う機能だったにもかかわらず、実装直後に検証できていたのはたった1つの実例(Notepad、チェーン長1)だけだった。2つ目の独立した実例(電卓、チェーン長2)を試しただけで、実装の前提(「エントリ内のチェーンは常に1要素」)が崩れる具体例が即座に見つかった——本プロジェクトがknowledge 15・26・36・38・46・50で繰り返し学んできた「フィクスチャの多様性不足が隠れたバグを生む」というパターンが、今回は自分自身が数分前に書いたばかりの新機能に対して再現した形になる。

## 57. design/robin_language_source_findings.mdが長年持ち越していた「window instance」の実機DSLを初めて確認——`GetWindow`は`=>`出力変数構文を再利用、無改修で正しくパースできた

design/robin_language_source_findings.mdの「今後の調査候補」に長期間残っていた「`GetWindow`の出力(`ByInstanceOrHandle`系アクションの入力になる『window instance』)をPython側でどう表現するか」という課題に関連し、まず`GetWindow`自体の実機DSLを確認した(これまで一度もキャプチャしたことが無かった)。

Actionsパネルで"Get window"を検索すると「UI automation」>「Windows」カテゴリに見つかった。ダイアログは「Get window:」(ドロップダウン、既定値「Specific window」、他の選択肢は未確認)「UI element:」(UI要素ピッカー)「Bring window to front:」(トグル)「Variables produced: AutomationWindow2」(既定の出力変数名)という構成。既存の「Window 'Untitled - Notepad'」UI要素を選択して保存・単独コピーしたところ:

```
UIAutomation.GetWindow.GetUseTimeout Control: appmask['Window \'Untitled - Notepad\''] BringWindowToFront: False Timeout: 5 WindowInstance=> AutomationWindow2
```

**確認できた事実**: action_idは`UIAutomation.GetWindow.GetUseTimeout`——ダイアログに表示されない`Timeout`パラメータ(既定5)が実際には存在し、その存在がaction_id名(`...GetUseTimeout`)に反映されている(「タイムアウトを使うモード」が暗黙に選ばれている、おそらく他に`Timeout`無しのバリアントが存在することを示唆)。出力変数の束縛は`WindowInstance=> AutomationWindow2`——`WindowInstance`という固定のパラメータ名に対し、知見14で確認済みの`=>`出力変数構文(`ScriptOutput=>`/`ButtonPressed=>`と全く同じ形式)がそのまま使われていた。新しい構文は一切無く、既存の汎用`output_var`/`output_vars`解析ロジック(`ActionRecord`のパラメータ解析ループの一部)で**パーサー・codegenとも一切のコード変更無しで**正しく処理できた(`ActionRecord(action_id='UIAutomation.GetWindow.GetUseTimeout', params={'Control': UiElementRef(...), 'BringWindowToFront': False, 'Timeout': 5}, output_var='AutomationWindow2', output_vars={'WindowInstance': 'AutomationWindow2'})`)。codegenは未対応アクションとして知見38/46と同じ安全なTODOフォールバックに倒れ、架空のウィンドウインスタンス変換をでっち上げることは無い。

**「window instance」問題への示唆**: 今回の実機確認で、「window instance」自体は単なる変数名(`AutomationWindow2`)で、DSL上は他の変数と全く区別が付かないただの`VarRef`になることが分かった——つまり、これを受け取る側(`ByInstanceOrHandle`系アクション、知見27の`ByTitleClass`系とは別系統)のDSLパラメータも、おそらく通常の変数参照としてそのまま出現すると予測される(未確認)。Python側の表現としては、知見56で実証したpywinautoセレクタ生成の仕組みと組み合わせれば、`AutomationWindow2 = Desktop(backend="uia").window(title="Untitled - Notepad")`のような代入文として変換できる可能性が見えてきたが、`BringWindowToFront: True`の場合の正確な意味論(`.set_focus()`相当か)・`Timeout`無しモードの構文・`ByInstanceOrHandle`系アクションの実機DSLは、いずれも未検証のため、今回は実装せず文書化のみに留めた。

**未検証のまま残る項目**: 「Get window」ドロップダウンの他の選択肢(「Specific window」以外に何があるか、「All windows」「Active window」のようなものが予測される)・`Timeout`無しモードの構文・`BringWindowToFront: True`時の挙動は、いずれも未確認のまま持ち越し。

**追記(別ティック・`ByInstanceOrHandle`系を確認)**: 「Close window」アクションの「Find window mode」ドロップダウンを確認したところ、「By window UI element」「By window instance/handle」「By title and/or class」の3択だった(「By title and/or class」が知見27で確認済みの`ByTitleClass`系に対応)。「By window instance/handle」を選ぶと「Window instance:」という入力欄(ツールチップ「The instance or handle of the window to close」)が現れ、ここに`%AutomationWindow2%`という式を直接入力・保存・単独コピーしたところ:

```
UIAutomation.CloseWindow.CloseByInstanceOrHandle WindowInstance: AutomationWindow2
```

design/robin_language_source_findings.mdが予測していた`CloseWindowByInstanceOrHandle`という命名パターンがそのまま実機で確認できた(action_id: `UIAutomation.CloseWindow.CloseByInstanceOrHandle`)。より重要な点として、**`WindowInstance`パラメータは引用符もUI要素参照の角括弧も付かない、完全に裸の変数参照**(`VarRef(name='AutomationWindow2')`)だった——知見57本文で立てた仮説(「window instanceは単なる変数名としてDSLに現れる」)が的中し、既存の汎用パラメータ解析ロジックで**一切のコード変更無しで**正しくパースできることを確認した。これで`GetWindow`(知見57本文)→`AutomationWindow2`という変数→`CloseWindow`(by instance)という、window instanceの生成から消費までの実機DSLの流れが一通り確認できたことになる。

**未検証のまま残る項目(追加)**: `BringWindowToFront: True`時の挙動・他の`ByInstanceOrHandle`系アクション(`SetWindowStateByInstanceOrHandle`等、知見27の`ByTitleClass`系に並ぶと予測される仲間)の実機DSLは、いずれも未確認のまま持ち越し。

**さらに追記(別ティック・「Get window」ドロップダウンの全選択肢を確認)**: 「Get window:」ドロップダウンの全選択肢を確認したところ、「Specific window」(知見57本文で確認済み)「Foreground window」の2択だけだった(「All windows」「Active window」のような予測は外れ)。「Foreground window」を選ぶと、ダイアログの「Variables produced」欄に`WindowTitle2`と`AutomationWindow2`という**2つ**の変数名が表示された。保存・単独コピーしたところ:

```
UIAutomation.GetWindow.GetForegroundWindow WindowTitle=> WindowTitle2 WindowInstance=> AutomationWindow2
```

**新発見**: これまでの全captureは`<Param>=> <変数名>`という`=>`出力変数束縛を**高々1個**しか持たなかったが、今回初めて**1つのアクションが2個の`=>`束縛を同時に持つ**実例に遭遇した(`WindowTitle=> WindowTitle2`と`WindowInstance=> AutomationWindow2`)。パーサーを確認したところ、`SetVariableRecord`(`ActionRecord`)の`output_var`フィールドには元々「後方互換のため最後に見つかったものを保持するだけ」という設計意図のコメントが既に書かれており、複数の`=>`束縛を正しく扱うための`output_vars`(複数キー対応の辞書)という仕組みも既に実装済みだった——つまり今回の実例は、過去のどこかのティックで「将来複数出力があるかもしれない」と見越して設計されていた仕組みが、初めて実際のデータで裏付けられた形になる。**一切のコード変更無しで**`output_vars == {"WindowTitle": "WindowTitle2", "WindowInstance": "AutomationWindow2"}`、`output_var == "AutomationWindow2"`(最後に見つかったもの)として正しくパースできることを確認した。

## 58. 【新発見】`[ConditionAction]`カテゴリの最後の未検証項目「If image」を実機確認——知見44以来ずっと空だった`imgrepo`シンボルの初の実データ、角括弧リスト構文も初確認

知見54で「If image」の実機DSLが「未検証のまま残る項目」として持ち越されていた最後の1つを確認した。Actionsパネルで"If image"を検索すると「UI automation」カテゴリに直接見つかった(「If window」等とは違いサブカテゴリ無し)。ダイアログは「If image: exists」(ドロップダウン、他の選択肢は未確認)「Image」(画像選択欄、「Select image(s)」→「Capture image」で画面の矩形範囲をドラッグ選択してキャプチャする)「Search for image on: Entire screen」「Search Mode: Search whole screen or foreground window」「Find all images in the list」(トグル)「Tolerance: 10」という構成。

Notepadのタイトルバー付近を画面キャプチャで選択し(「Image captured successfully」ダイアログでデフォルト名「Image」のまま確定)、保存・単独コピーしたところ:

```
IF (UIAutomation.IfImage.ExistsOnScreen Images: [imgrepo['Image']] FindAllImages: False Tolerance: 10 SearchAlgorithm: UIAutomation.ImageFinderAlgorithm.Legacy) THEN
```

**確認できた事実**:
- action_idは`UIAutomation.IfImage.ExistsOnScreen`——知見54で確立した`IF (<ActionId> ...) THEN`構文をそのまま再利用しており、「If window」はこのアクション単体で対応する`End`も自動挿入される(=ブロック開始構文)ことも実機確認した(知見54の他の`[ConditionAction]`群と同じ)。
- **知見44で発見した`# [ControlRepository][PowerAutomateDesktop]`セクションの`ImageRepositorySymbol`(シンボル名`imgrepo`)に、初めて実データが入った実例を確認できた**。これまでの全captureでは`"ImageRepositorySymbol": {"Repository": "{\"Folders\": [], \"Images\": [], \"Version\": 1}", ...}`のように常に空だったが、今回`"Images"`配列に実際のスクリーンショットPNG(Base64)を含むエントリ(`Id`/`Name`/`Screenshot`等)が1件入った。
- **新しい構文: 角括弧で囲んだリストリテラル**。`Images: [imgrepo['Image']]`——`appmask['...']`が単体の名前参照として裸で出現するのとは異なり、`imgrepo['Image']`全体が`[...]`で囲まれている。「Find all images in the list」トグル(複数の画像候補を同時に検索する機能)の存在から、複数要素をカンマ区切りで保持できるリストリテラル構文(`[imgrepo['A'], imgrepo['B']]`のような形)だと推測されるが、複数要素の実例は未確認。
- `SearchAlgorithm: UIAutomation.ImageFinderAlgorithm.Legacy`という、ダイアログのどの項目にも対応しない隠しパラメータも実機確認できた(知見57の`GetWindow`の`Timeout`と同種の、UIに出ないがDSLには現れるパラメータ)。

**パーサーの挙動**: 現在のパーサーは`appmask[...]`専用の`UiElementRef`抽出ロジックしか持たず、`imgrepo[...]`の角括弧リスト構文は未対応のため、`[imgrepo['Image']]`全体が不透明な`VarRef(name="[imgrepo['Image']]")`としてテキストのまま保持される——構造化はされないが、データを失わず、クラッシュもしない安全なフォールバックであることを確認した。codegenは知見54の`IfActionRecord`の`NotImplementedError`フォールバックをそのまま再利用でき、**一切のコード変更無しで**安全に失敗することを確認した(画像マッチングは`pyautogui.locateOnScreen`等への対応が考えられるが、実機検証が無いため架空の変換はでっち上げない)。

**未検証のまま残る項目**: 「If image」ドロップダウンの他の選択肢(「exists」以外に「doesn't exist」等が予測される)・複数画像をリストに含めた場合の実際の区切り文字・`imgrepo[...]`の角括弧リスト構文の専用パーサー対応・`ImageRepositorySymbol`の`parse_control_repository()`での構造化(現状`ControlRepositorySymbols`のみ対応、`ImageRepositorySymbol`は未対応)は、いずれも未確認・未実装のまま持ち越し。

## 59. 知見55の`VariableTrailer`で最後に残っていた「Slice構文」を実機確認——Pythonのスライス構文`[start:end]`と字面上完全に一致

知見55で`.Name`トレーラ・`[Index]`添字アクセスを実機確認した際、「Slice構文・0始まりか1始まりかは未確認のまま持ち越し」としていた最後の項目を確認した。「Set variable」のValue欄に`%InnerVar[0:2]%`という式を入力・保存・単独コピーしたところ:

```
SET NewVar3 TO InnerVar[0:2]
```

**確認できた事実**: 予測通り、Pythonのスライス構文と全く同じ`[start:end]`という形式(コロン区切り)だった。保存直後のアクションカードのプレビュー表示では`[0:2]`部分が見た目上省略され「InnerVar」とだけ表示されたが、これは表示上の省略に過ぎず、一括コピーしたDSLテキストには`[0:2]`が正しく残っていることを確認した(表示上の省略に実データが引きずられていないか、紛らわしい挙動だったため明記しておく)。`[Index]`添字アクセス(知見55)と同様、ドットを含まないため`_ENUM_REF_RE`にはマッチせず、既存の`VarRef`フォールバックでそのまま保持され、codegenも`InnerVar[0:2]`という構文的に正しいPythonのスライス式を**偶然にも**生成できることを確認した——一切のコード変更は不要だった。

これで知見55が「未検証のまま持ち越し」としていた`VariableTrailer`の3形態(`.Name`/`[Index]`/Slice)全てが実機確認済みになった。

**未検証のまま残る項目**: `start`/`end`が0始まりか1始まりか・終端を含むか含まないか(知見51のLOOP range確認と同種の、実機実行による値の読み取りが必要な検証)は、いずれも実機未確認のまま持ち越し——今回確認できたのはあくまで構文の字面のみで、意味論(実際にどの文字が返るか)はまだ検証していない。

## 60. 【知見59の続き・実機実行で決着】`[Index]`/Slice構文は0始まり・終端排除——Pythonの添字/スライス意味論と完全に一致すると実機実行で確認

知見59で「未検証のまま残る」としていた、`[Index]`/Slice構文が0始まりか1始まりか・終端を含むかどうかという意味論の問題を、知見51のLOOP range検証と同じ手法(実機で実際にフローを実行し、結果をファイル経由で読み取る)で決着させた。

**検証方法**: 知見51と同じく、`Main`の壊れた`For each`/`End`を一時的に無効化してパッケージ全体の検証を通し、`Main`自身が元から持つ空の`Loop LoopIndex FROM 1 TO 3 STEP 1`の本体に、以下の2アクションを一時的に挿入した:

1. `Set variable`: `NewVar3` に文字列`"ABCDEFGHIJ"`(10文字、重複の無いアルファベット)を代入。
2. `Run Python script`: `open(r'C:\...\slice_check.txt','w').write('%NewVar3[0:3]%|%NewVar3[0]%|%NewVar3[3]%')`——スライス・添字アクセスの結果をファイルへ書き出す。

ツールバーのRun(▶)で`Main`を実行し(序盤の`Display message`はOKボタンで手動で閉じた)、完了後にWinRM経由でファイル内容を直接読み取った。

**結果**:

```
'ABC|A|D'
```

Pythonで同じ値に対して同じ添字/スライス式を評価した結果と**完全に一致**することを確認した:

```python
>>> s = "ABCDEFGHIJ"
>>> s[0:3], s[0], s[3]
('ABC', 'A', 'D')
```

- `NewVar3[0:3]` → `"ABC"`(インデックス0・1・2の3文字、インデックス3は含まない)
- `NewVar3[0]` → `"A"`(先頭文字、0始まり)
- `NewVar3[3]` → `"D"`(4文字目、0始まりで添字3)

**結論**: PADの`[Index]`/`[start:end]`構文は、**0始まり・終端を含まない(exclusive)という、Pythonの添字/スライスと寸分違わぬ意味論**であることが実機実行で確定した。これは知見51のLOOPのrange(0始まりではなく、終端排除という点でPythonの`range()`と一致)とあわせて、「PADの各種範囲・添字表現はPythonの対応物と驚くほど自然に一致する」という傾向を補強する結果でもある。これにより、`pad_codegen.py`が`VarRef`としてそのまま素通ししている`InnerVar[0:2]`等の表現は、構文が偶然一致しているだけでなく**意味論的にも正しい**ことが保証された——今後、これらの式を単純な素通し以上の形で積極的に扱う場合(例えば型推論や最適化)でも、安心してPythonのスライス/添字セマンティクスを前提にできる。

**検証後の後始末**: 知見51と全く同じ手順で`Main`を完全に復元した——追加した2アクションを削除、`For each`/`End`を再度有効化して元の単一の検証エラーのみに戻し、テストファイル`slice_check.txt`をWinRM経由で削除(`os.path.exists()`で`False`を確認)、アクティブタブを`LoopTest`に戻した。
