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
