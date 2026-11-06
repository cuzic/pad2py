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

**未検証のまま残る項目**: `IsNotFocused`(未検証だが命名パターンから確実視)・`InstantCheck`パラメータの正確な意味は未確認のまま持ち越し。~~「If image」の実機DSL表現~~ → 完了(知見58)。

**追記(別ティック・「If service」ドロップダウンの全選択肢を確認)**: 「If service:」ドロップダウンの全選択肢を確認したところ、「Is stopped」「Is installed」「Isn't installed」「Is running」「Is paused」の**5択**だった(スクロールしても追加の選択肢は現れなかった)。知見50/54の`Open`/`Close`/`Become focused`/`Lose focus`や`Is open`/`Isn't open`のような完全な肯定/否定ペアが全選択肢にあると予測していたが、実際には**「installed」だけが肯定/否定ペア**(`Is installed`/`Isn't installed`)を持ち、`running`/`stopped`/`paused`には否定形が存在しない非対称な構成だった。「Is stopped」を選んで保存・単独コピーしたところ:

```
IF (Services.IfService.IsStopped Service: $'''Spooler''') THEN
```

予測通り`Services.IfService.IsStopped`——`IsRunning`(既に確認済み)と対になる命名パターンだった。既存の汎用パーサー/codegenのまま、**一切のコード変更無しで**正しく処理できることを確認した。これで知見50・54・本追記により、`[ConditionAction]`/`[WaitAction]`カテゴリの主要なアクション(`If window`/`If window contains element`/`If image`/`If service`/`Wait for window`/`Wait for window content`/`Wait for service`)は、ドロップダウンの全選択肢まで含めて実機確認が概ね出揃った。

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

## 61. 【重大な訂正】`ON ERROR`/`ON BLOCK ERROR`のインデント規則を実機再検証——知見34/36は実在する一方の形でしかなく、**もう一方の形(ヘッダーが保護対象より1段深い)も実在すると判明**

`pad_codegen.py`のアクションカバレッジを機械的に測定するツール(`dump_daemon/codegen_coverage.py`、新規)を作り、`tests/fixtures/`の実機キャプチャ全14件に通して回帰確認していたところ、`looptest_whole_subflow_with_calculator_button.txt`を変換した結果の木構造が明らかに壊れていた——`WAIT`/`LABEL`/`LOOP`以降の内容が丸ごと無関係な`ON ERROR`ハンドラの中に取り込まれ、`GOTO MyLabel`が全く無関係な先頭アクションのハンドラとして誤って付き、行き場を失った生の`END`キーワードがトップレベルの本体に漏れ出ていた。

**実機再検証**: この壊れた変換の原因を特定するため、`LoopTest`フロー(VM上に現存、本フィクスチャのキャプチャ元そのもの)に対して2つの独立した再コピー実験を行った。

1. **保護対象アクション単体を個別選択してコピー**(知見34/36と同じ手法——フロー全体ではなく1アクションだけを選んで右クリック→コピー):
   ```
   Scripting.RunPythonScript.RunPythonScript PythonCode: $'''...''' ScriptOutput=> PythonScriptOutput3
       ON ERROR RunPythonScriptError
           SET NewVar2 TO $'''script failed'''
       ON ERROR
           SET NewVar TO $'''recovered'''
       END
   ```
   `ON ERROR`ヘッダーが保護対象のアクションより**1段深く**(4スペース)、本体(`SET`)がヘッダーよりさらに**1段深い**(8スペース)——知見34/36の「ヘッダー・本体とも保護対象の文と同じindent」とは完全に異なる形。

2. **フロー全体を選択してコピー**(`Ctrl+A`→`Ctrl+C`、一括コピー):同じ箇所が全く同じインデント(ヘッダー+1段・本体+2段)で出力され、アーカイブ済みの`looptest_whole_subflow_with_calculator_button.txt`と完全に一致した。

この2つの独立した再現により、「単体コピーだからdedentされて消えた」という仮説は排除できた(単体コピーでも1段/2段のインデントがそのまま出力された)。一方、他6件の`whole subflow`系フィクスチャ(`looptest_whole_subflow_with_wait_for_window.txt`等)は、全く同じ`Scripting.RunPythonScript.RunPythonScript`+2アーム`ON ERROR`の構造を、知見34/36通りの「保護対象と同じindent」(0段)で含んでいる。**同一セッション内で、同じ種類の構文が明確に異なる2つのインデント形で実在する**ことになる——おそらく、これらの古いフィクスチャがキャプチャされた時点と本知見の再検証時点の間に、PAD側のクリップボードシリアライザの挙動(バージョン更新等)が変わったことを示唆しているが、断定的な原因は不明なまま。

**`ON BLOCK ERROR`side でも別の実例を発見**: 同フローの`LOOP`本体内にネストした(無名・空)`BLOCK`+`ON BLOCK ERROR`(`GOTO MyLabel`)を、(a)その2行だけを個別選択してコピーすると`ON BLOCK ERROR`は`BLOCK`と**同じ**indent(知見40通り、再確認)になったが、(b)`LOOP`にネストした状態のままフロー全体を一括コピーすると、`ON BLOCK ERROR`は`BLOCK`より**1段浅い**(`BLOCK`を囲む`LOOP`と同じ)indentになった——`BLOCK`自身の閉じ`END`とは別に、ハンドラ群を閉じる`END`がもう1行、別々に存在する形。`ON BLOCK ERROR`の本体(`GOTO MyLabel`)自体は、どちらの場合も常にヘッダーと**同じ**indent(`ON ERROR`の新しい「+1段」規則とは異なり、知見40の規則のまま)。

**実装**: `build_block_tree()`の`OnErrorRecord`/`OnBlockErrorRecord`処理を全面的に見直した。

- 旧実装は`stop_at_on_error`付きの`parse_level(level, ...)`(`level`=保護対象の文のindent、常に固定)を使っていたが、これは「ヘッダー自身のindentが`level`と一致する」という知見34/36の前提に暗黙に依存していた。前提が崩れると、本体パースが暴走して後続の無関係な行を全て飲み込んでしまう(今回発覚した破壊の直接原因)。
- 新実装はヘッダー自身の実際のindent(`arm_level = rec.indent`)を基準に使う。`ON ERROR`は`arm_level`が保護対象の`level`と一致するかどうかで、本体が「ヘッダーと同じ段」(知見34/36の形)か「ヘッダーより1段深い」(本知見の新しい形)かを自己記述的に判別する——後者はIF/LOOP/SWITCHと同じ「ヘッダーの子は+1段」という規則にむしろ合致し、本体が明確に深くなる分、次のアーム見出しとの区別に`rec.indent < level`という既存の素朴な比較だけで足りる(専用フラグ不要)。前者は従来通り、次のアーム見出し/共有`END`への先読み(`stop_at_error_sibling`、旧`stop_at_on_error`を汎用化・改称)が必要。
- `ON BLOCK ERROR`は本体が常にヘッダーと同じ段という知見40の規則を維持しつつ、`BLOCK`に対するヘッダー自身のindentが`level`(`BLOCK`と同じ)または`level - 1`(`BLOCK`を囲む構文と同じ)のどちらでも受理するようにした。`arm_level`が`level`と異なる場合は、アーム群を閉じる`END`とは別に`BLOCK`自身を閉じる`END`をもう1行、明示的に消費する。
- 両方の形について実機キャプチャをそのまま新規フィクスチャとして追加した: `tests/fixtures/on_error_nested_indent.txt`(本知見の新しい`ON ERROR`形、単体コピー)・`tests/fixtures/on_block_error_isolated.txt`(`ON BLOCK ERROR`が`BLOCK`と同じindentになる個別コピー形)。既存の`looptest_whole_subflow_with_calculator_button.txt`が「`BLOCK`より1段浅い`ON BLOCK ERROR`」の実例として既に手元にあったため、そちらは新規キャプチャ不要だった。

**今後の課題**: どちらのインデント形が「現在の」PADの標準的な挙動なのか(あるいは両方とも状況依存で今後も両方出現し続けるのか)は未解明。もし今後、このプロジェクトが対象にするPADのバージョンが特定の1つに固定されるなら、この二重対応は単純化できる可能性がある。`ON BLOCK ERROR`が「なぜ`BLOCK`より1段浅くなりうるのか」(`ON ERROR`と同じ「+1段」パターンにも、知見40の「同じ段」パターンにも当てはまらない、独立した現象)についても、統一的な説明は得られていない。

## 62. UIAutomationによるPADデザイナー自動操作を確立——`Text.Trim`で初のTier1/Tier2系アクション実機キャプチャに成功

これまでの実機確認は全て人手(または別セッション)によるPADデザイナーのGUI操作に依存していたが、今回`pywinauto`(UIAバックエンド)でPADデザイナー自身のウィンドウを直接操作し、検索→アクション追加→パラメータ入力→保存→選択→コピーの全経路を自動化できることを確認した。実行環境は対話的RDPセッション(`clipwire`経由、WinRMは非対話セッションのためGUI操作不可——design/ci_verification_findings.md 知見9〜11の制約通り)。

**確立した操作手順**:
1. `SearchActionsSearchBox`(Actionsサイドパネルの検索欄)に`.set_edit_text()`で検索語を設定(`send_keys`でリテラルな空白を含む文字列を打つと空白が消える——`send_keys`の独自記法でスペースが特殊扱いされるため。値を直接設定したい場合は常に`set_edit_text()`を使うこと)
2. 検索結果の`ActionsTreeView`から、`automation_id`にドットを含む`TreeItem`(カテゴリ見出しは`"Text"`のようにドット無し、具体的アクションは`"Text.Trim"`のようにドット付き)をリーフとして特定し`.double_click_input()`
3. 開いたパラメータダイアログ(`DialogWindow`、メインウィンドウの子として存在——`Desktop(backend="uia").windows()`の別トップレベルウィンドウとしては出てこない点に注意)内の`EditableTextBox`等に値を設定
4. `ActionDialogButtonSaveButton`をクリックして保存
5. `ProgramItemsListBoxActions`(現在のサブフロー内のアクション一覧)から対象の`ListItem`を`.click_input()`→`.set_focus()`→`send_keys("^c")`でクリップボードへコピー
6. `win32clipboard`(同じ対話的セッション内なので直接呼べる)で読み取り

**実機キャプチャ結果**(`Text.Trim`、`Text to trim`に`"hello world"`相当・`What to trim`はデフォルト`Both`のまま保存):
```
Text.Trim Text: $'''helloworld''' TrimOption: Text.TrimOption.Both TrimmedText=> TrimmedText
```

**確認できた事実**:
- action_id`Text.Trim`は、docs-local配下の逆コンパイル調査(`[Action(Name = "Trim")]`、モジュール`Text`)から予測した形とそのまま一致した。
- 列挙値`TrimOption`は、ダイアログ上で一度も触らずデフォルトの`Both`のまま保存したにもかかわらず、`TrimOption: Text.TrimOption.Both`として**省略されずに出力された**——知見19〜21・23で確立した「一部のデフォルト値は省略される」というActionSelector経由の省略規則が、この(単一セレクタしか持たない)アクションの列挙型引数には適用されないことを示す新しい実機データ点。
- 出力変数の既定名`TrimmedText`も、ダイアログ上の提案通りそのまま使われた。

**今後**: この手順を一般化した自動化スクリプトで、Tier1/Tier2の残りのアクション(docs-local/pad_action_modules_findings.md記載)についても同様に実機キャプチャを進める。

## 63. 汎用バッチ自動化で一括14アクションを実機キャプチャ——全て既存の`ActionRecord`汎用パーサーでコード変更無しに構造化できることを確認

知見62の手順を汎用化し、検索語のリストを渡すだけで「検索→リーフの`TreeItem`(auto_idにドットを含む方)を特定→ダブルクリックで追加→ダイアログ内の空の`Edit`コントロール(出力変数名ボックス`ActionDialogVariableEditableTextBox`とメモ欄`ActionNoteEditTextBox`は除外)を全て`"sample"`で埋める→`ActionDialogButtonSaveButton`をクリック」を繰り返し、最後に`ProgramItemsListBoxActions`で全選択(Ctrl+A)して一括コピーする自動化スクリプトを作成した。2回のバッチ実行(6件・8件)で合計14件の新規アクション(`Text.Trim`含め15件)を一括取得できた——個別に選択・コピーする知見62の手順より大幅に効率的。

**実機キャプチャ結果**(`tests/fixtures/tier1_text_variables_batch1.txt`、値は全て自動入力した`"sample"`またはダイアログの初期値のまま):
```
Text.ChangeCase Text: $'''sample''' NewCase: Text.CaseOption.UpperCase Result=> TextWithNewCase
Variables.ReverseList List: $'''sample'''
Text.Pad Text: $'''sample''' PadPosition: Text.PadPosition.Left PaddingText: $'''sample''' TotalLength: 10 PaddedText=> PaddedText
Text.JoinText.Join List: $'''sample''' Result=> JoinedText
Text.AppendLine Text: $'''sample''' LineToAppend: $'''sample''' Result=> Result
Text.EscapeForRegularExpression Text: $'''sample''' EscapedText=> EscapedText
Text.Reverse Text: $'''sample''' ReversedText=> ReversedText
Text.CropText.CropTextBeforeFlag Text: $'''sample''' ToFlag: $'''sample''' IgnoreCase: False CroppedText=> CroppedText IsFlagFound=> IsFlagFound
Text.GetSubtext.GetSubtext Text: $'''sample''' CharacterPosition: $'''sample''' NumberOfChars: $'''sample''' Subtext=> Subtext
Text.SplitText.Split Text: $'''sample''' StandardDelimiter: Text.StandardDelimiter.Space DelimiterTimes: 1 Result=> TextList
Text.ToNumber Text: $'''sample''' Number=> TextAsNumber
Text.FromNumber Number: $'''sample''' DecimalPlaces: 2 UseThousandsSeparator: True FormattedNumber=> FormattedNumber
Text.Random UseUpperCaseLetters: True UseLowerCaseLetters: True UseDigits: True UseSymbols: True MinimumLength: 6 MaximumLength: 10 RandomText=> RandomText
Variables.GenerateRandomNumber.RandomNumber MinimumValue: 0 MaximumValue: 100 RandomNumber=> RandomNumber
```

**確認できた事実**:
- docs-local配下の逆コンパイル調査で予測したaction_id・パラメータ名・enum直列化形式が、ほぼ全件そのまま実機で一致した。
- 複数`ActionSelector`を持つアクションのaction_idは3セグメント形式(`Text.JoinText.Join`/`Text.CropText.CropTextBeforeFlag`/`Text.GetSubtext.GetSubtext`/`Text.SplitText.Split`/`Variables.GenerateRandomNumber.RandomNumber`)——末尾がセレクタ固有の名前になる。単一セレクタのアクションは2セグメント(`Text.ToNumber`/`Text.FromNumber`/`Text.Random`等)。
- `Variables.ReverseList`は`[Mutable]`な`List`引数をその場で書き換えるため、`=>`による出力変数束縛を一切持たない——decompile調査で予測した「Mutable引数は既存の変数をその場で変更する」という理解を実機で裏付けた。
- `Text.Random`・`Variables.GenerateRandomNumber.RandomNumber`は、チェックボックス・数値引数を一切触らずデフォルトのまま保存したが、知見62の`TrimOption`と同様、全てのデフォルト値が省略されずに出力された。
- (自動化上の注意、副産物): `GetSubtext`の`CharacterPosition`/`NumberOfChars`のような数値引数も、ダイアログ上は`Text`引数と同じ`Edit`コントロールとして露出しており、文字列`"sample"`を入れても検証エラーにならずそのまま保存できた——PADの入力引数は型を問わず「式」として扱われ、設計時点では値の型チェックをしていない可能性を示唆する(実行時にどう振る舞うかは別問題、未検証)。

**検証**: `parse_dsl()`に通したところ、この15件全てが既存の汎用`ActionRecord`パーサーでコード変更無しに正しく構造化できることを確認した(`tests/test_pad_dsl_parser.py::test_tier1_text_variables_actions_parse_as_generic_action_records`)——知見36以来の「汎用パーサー設計は未知の新アクションに対して自動的に対応できる」という方針を、Tier1モジュールでも改めて裏付けた。

**今後**: 同じ自動化スクリプトでDateTime/File/Folder/Compression/Cryptography(Tier1)、Database/Web/XML/Cmd/Clipboard(Tier2)の残りのアクションについてもバッチキャプチャを継続する。

## 64. DateTime/Folder/Clipboard系9件を実機キャプチャ——`SubstractDate`のtypoがそのまま直列化されることを確認

知見63の自動化バッチで続けて9件(`DateTime.GetCurrentDateTime`/`Add`/`Subtract`、`Folder.GetFiles`、`Compression.ZipFiles`、`Clipboard.GetText`/`SetText`/`Clear`、「Create new folder」のみ検索結果の特定に失敗)を追加・キャプチャした(`tests/fixtures/tier1_datetime_folder_clipboard_batch2.txt`)。

**確認できた事実**:
- `DateTime.GetCurrentDateTime.Local`——`TimeZoneMode: System`に対応するセレクタ名が`Local`であることをdecompile予測通り確認。
- `DateTime.Subtract FromDate: ... SubstractDate: ...`——decompileで発見した`SubstractDate`という**プロパティ名そのもののtypo**が、実機のDSL直列化にもそのまま現れることを確認した(ソースコードのtypoが単なる内部実装の話ではなく、DSLの外部契約の一部になっている)。
- `Folder.GetFiles`(`GetFilesInFolder`ではない、短縮名)——`SortBy1/2/3`・`SortDescending1/2/3`・`FileFilter`(既定`"*"`)・`IncludeSubfolders`(既定`False`)・`FailOnAccessDenied`(既定`True`)の全パラメータがdecompile予測通り。
- `Clipboard.GetText`/`Clipboard.Clear`はパラメータを一切持たない(前者は`=>`出力束縛のみ)。

**`Compression.ZipFiles`の`Password`パラメータで新しいDSL構文を発見**(詳細は次の知見65)。

## 65. 【重要・セキュリティ関連】`Sensitive`扱いの引数(暗号化キー等)は`P'<DPAPI暗号化Base64>'`という、既存の`$'''...'''`とは全く別のDSL構文で直列化される

`Compression.ZipFiles`の`Password`(decompile調査で`[ArgumentStyling(Sensitive = true)]`付きの`EncryptableObject`型と確認済み)に、ダイアログ上で平文`"sample"`を入力・保存・コピーしたところ、DSL上の値は以下のようになった:

```
Password: P'AQAAANCMnd8BFdERjHoAwE/Cl+sBAAAAWO5tuuCEIUiYIkQ+hIDxiwQAAAACAAAAAAAQZgAAAAEAACAAAAATP1QOI0xAh/j3LzDapFy6TlnrOzKh7FFIom+fArhjrgAAAAAOgAAAAAIAACAAAAAFVc4vy18vtiGxcSUHV2YjkZihDN44a5TsrlC6eddEvRAAAABoRCSHbo9SO/L4NJuOrGePQAAAADspd8IEJzb2el6E9mTJyZ3BJ2Sd9RHuYKjPRUu/DwG4KXPzxAQKsra0mdtsumNhZyNXJzXKnMtmCZtwa5ernDQ='
```

**確認できた事実**:
- 平文の`"sample"`(7バイト)ではなく、**Base64エンコードされた大きなバイナリblob**になっている。
- プレフィックスバイト列(Base64デコード後の先頭)`01 00 00 00 D0 8C 9D DF 01 15 D1 11 8C 7A 00 C0 4F C2 97 EB`は、Windows DPAPI(`System.Security.Cryptography.ProtectedData.Protect()`)が生成するblobの**既知の固定シグネチャ**と一致する。つまり`Sensitive`な引数は、保存時にPAD自身がDPAPIで暗号化してからDSLテキストに埋め込んでいる。
- DSL上の構文は`$'''...'''`(文字列リテラル)ではなく、**`P'<base64>'`という見慣れない形**(シングルクォート1つのみ、前置に`P`)。既存の`_STRING_RE`等はこの構文を認識せず、現状のパーサーは全体を`VarRef`としてフォールバックする(クラッシュもデータ欠落も起きないが、`Password`という変数が実在するという誤った解釈になる——`tests/test_pad_dsl_parser.py::test_tier1_datetime_folder_clipboard_actions_parse_without_crashing`で現状の挙動を回帰テスト化した)。

**重要な設計上の含意**:
- DPAPIの既定モード(`DataProtectionScope.CurrentUser`想定)で暗号化されたblobは、**暗号化した時と同じWindowsユーザーアカウント・同じマシンでなければ復号できない**。つまりこの`P'...'`blobを別のマシン・別のユーザーでコピー&ペーストしても、元の平文には絶対に戻せない。
- `pad2py`がこの構文を将来サポートする場合も、**復号を試みるようなコード(でっち上げたDPAPI復号ロジック)を実装してはならない**——そもそも実行環境が変われば復号不可能であり、知見36以来の「架空のAPI/ロジックをでっち上げない」という方針そのものに加えて、センシティブな値を平文化しようとする試み自体がセキュリティ上好ましくない。`Sensitive`な引数は常に`# TODO`で安全側に倒し、ユーザーに手動で値を補ってもらう設計が妥当。
- 同様の`Sensitive`マーキングは`Cryptography.Actions`(`EncryptionKey`/`HashKey`等)にも多数あり、同じ`P'...'`構文で直列化される可能性が高い(未確認、今後のキャプチャで検証予定)。

## 66. Variables.List系10件・Variables.DataTable系17件を自動バッチで実機キャプチャ——`[Mutable]`な引数しか持たないアクション(出力束縛`=>`なし)が多数存在することを確認

知見63の自動化スクリプトで、`Variables`モジュールの残り(List操作10件、DataTable操作17件、計27件)を2回のバッチ実行で一括キャプチャした(`tests/fixtures/tier1_variables_list_datatable_batch3.txt`)。1回目のバッチ(DataTable系17件)では、検索結果の`TreeItem`走査ロジックが「auto_idにドットを含む最初の`TreeItem`」を基準にしていたため、ネストしたカテゴリノード(`Variables.DataTable`自身もドットを含む)を誤ってリーフと判定し6件を取り逃がした。候補ノードが子に`Expand`という名前の`Button`を持たないこと(=真のリーフである証拠)を追加条件にして自動化スクリプトを修正し、取り逃がした6件(`DeleteRowFromDataTable`/`FilterDataTable`/`MergeDataTables`/`JoinDataTable`/`ConvertDataTableToCSV`/`GenerateDataTableFromCSV`)を再実行して全て成功させた。

**実機キャプチャ結果**(値は全て自動入力した`"sample"`またはダイアログの初期値のまま):
```
Variables.CreateNewList List=> List
Variables.AddItemToList Item: $'''sample''' List: $'''sample'''
Variables.RemoveItemFromList.RemoveItemFromListByIndex ItemIndex: $'''sample''' List: $'''sample'''
Variables.ClearList List: $'''sample'''
Variables.ShuffleList List: $'''sample'''
Variables.MergeLists FirstList: $'''sample''' SecondList: $'''sample''' OutputList=> OutputList
Variables.SubtractLists FirstList: $'''sample''' SecondList: $'''sample''' OutputList=> ListDifference
Variables.FindCommonListItems FirstList: $'''sample''' SecondList: $'''sample''' OutputList=> IntersectionList
Variables.RemoveDuplicateItemsFromList List: $'''sample''' IgnoreCase: False
Variables.SortList.SortList List: $'''sample'''
Variables.CreateNewDatatable InputTable: { } DataTable=> DataTable
Variables.AddRowToDataTable.AppendRowToDataTable DataTable: $'''sample''' RowToAdd: $'''sample'''
Variables.DeleteEmptyRowsFromDataTable DataTable: $'''sample'''
Variables.ModifyDataTableItem DataTable: $'''sample''' ColumnNameOrIndex: $'''sample''' RowIndex: $'''sample''' Value: $'''sample'''
Variables.FindOrReplaceInDataTable.FindItemInDataTableEverywhere DataTable: $'''sample''' AllMatches: True ValueToFind: $'''sample''' MatchCase: False MatchEntireCellContents: False DataTableMatches=> DataTableMatches
Variables.AddColumnToDataTable.AppendColumnToDataTable DataTable: $'''sample''' ColumnName: $'''sample'''
Variables.DeleteColumnFromDataTable.DeleteColumnWithName DataTable: $'''sample''' ColumnName: $'''sample'''
Variables.DeleteDuplicateRowsFromDataTable DataTable: $'''sample'''
Variables.ClearDataTable DataTable: $'''sample'''
Variables.SortDataTable.SortWithColumnName DataTable: $'''sample''' ColumnName: $'''sample''' Order: Variables.SortDirection.Ascending
Variables.FilterDataTable DataTable: $'''sample''' FilterParameters: `` MatchCase: True FilteredDataTable=> FilteredDataTable
Variables.MergeDataTables FirstDataTable: $'''sample''' SecondDataTable: $'''sample''' MergeMode: Variables.MergeMode.AddExtraColumns
Variables.JoinDataTable FirstDataTable: $'''sample''' SecondDataTable: $'''sample''' JoinOperation: Variables.JoinOperationType.Inner JoinParameters: `` JoinedDataTable=> JoinedDataTable
Variables.ConvertDataTableToCSV.DataTableToCSVCommonSeparator DataTable: $'''sample''' IncludeColumnNames: False ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVText=> CSVText
Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator CSVText: $'''sample''' TrimFields: True FirstLineContainsColumnNames: False ReadFieldsAsText: False ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVTable=> CSVTable
Variables.RetrieveDataTableColumnIntoList DataTable: $'''sample''' ColumnNameOrIndex: $'''sample''' ColumnAsList=> ColumnAsList
Variables.DeleteRowFromDataTable DataTable: $'''sample''' RowIndex: $'''sample'''
```

**確認できた事実**:
- `AddItemToList`/`ClearList`/`ShuffleList`/`RemoveDuplicateItemsFromList`/`SortList`/`AddRowToDataTable`/`DeleteEmptyRowsFromDataTable`/`ModifyDataTableItem`/`AddColumnToDataTable`/`DeleteColumnFromDataTable`/`DeleteDuplicateRowsFromDataTable`/`ClearDataTable`/`SortDataTable`/`FilterDataTable`(置換後を上書き)/`MergeDataTables`/`JoinDataTable`/`DeleteRowFromDataTable`は`List`/`DataTable`引数が`[Mutable]`で、出力変数束縛`=>`を一切持たない——知見63で確認した`Variables.ReverseList`と同じパターンがDataTable操作全体に広く適用されている。pad2pyのcodegen側は「Mutable引数を取るアクションは代入文を生成せず、既存変数への破壊的操作(例: `list.append(item)`相当)としてコード化する」という既存方針をそのままDataTable系にも適用できる。
- 一方で`CreateNewList`/`CreateNewDatatable`/`MergeLists`/`SubtractLists`/`FindCommonListItems`/`FindOrReplaceInDataTable`/`SortDataTable`(ソート結果ではなく`SortWithColumnName`自体は実はMutable、要再確認)/`ConvertDataTableToCSV`/`GenerateDataTableFromCSV`/`RetrieveDataTableColumnIntoList`は非破壊(新しい値を生成)で`=>`束縛を持つ——同じモジュール内でも操作ごとにMutable/非Mutableが混在することを実機で裏付けた。
- `Variables.CreateNewDatatable`の`InputTable: { }`——decompileで予測した「2次元配列リテラル」構文が、空配列の場合は`{ }`と直列化されることを確認。ただし現状のパーサーはこの`{`/`}`配列リテラル構文自体に未対応で、`{`がトークンとして単独で`VarRef(name="{")`にフォールバックし、後続の`}`は読み捨てられる(クラッシュもデータ欠落も起きないが、正しく配列として構造化されるわけではない——`tests/test_pad_dsl_parser.py::test_tier1_variables_list_datatable_batch3_parses_as_generic_action_records`で現状の挙動を回帰テスト化した。配列リテラル構文への本格対応は今後の課題)。
- `FilterDataTable`/`JoinDataTable`の`FilterParameters`/`JoinParameters`は、UI上の複合パラメータ(複数条件行)がダイアログで何も設定されなかった場合、空のバックティック文字列 `` `` `` として直列化される——既存の`$'''...'''`や通常のenum値とは異なる第3の文字列的構文(詳細未調査、今後のキャプチャ課題)。
- `Variables.SortDataTable.SortWithColumnName`の`Order`パラメータは`Variables.SortDirection.Ascending`という、`Folder.SortBy`等とは別のenum型(`SortDirection`)を使う。

**検証**: 27件全てが既存の汎用`ActionRecord`パーサーでコード変更無しに正しく構造化できることを確認した(`tests/test_pad_dsl_parser.py::test_tier1_variables_list_datatable_batch3_parses_as_generic_action_records`)。これにより`Variables`モジュールの完了率は5/34→29/34(`capture_coverage.py`)まで進んだ。

**今後**: 残るTier1/2の未キャプチャモジュール(Text残り6件、File 0/16、Folder残り9件、Cryptography 0/8、Database 0/3、Web 0/3、XML 0/10、Cmd 0/5、Variables残り5件)を同じ自動化バッチで継続する。

## 67. Text残り6件・Variables残り5件(計11件)を実機キャプチャ——「ダイアログが閉じ残る」自動化上のバグと、第3の空文字列構文(バックティック)を発見

知見66の自動化バッチで11件(`Text.ParseText`/`Replace`/`RecognizeEntitiesInText`/`CreateHTMLContent`/`ConvertDateTimeToText`/`ConvertTextToDateTime`、`Variables.TruncateNumber`/`IncreaseVariable`/`DecreaseVariable`/`ConvertJsonToCustomObject`/`ConvertCustomObjectToJson`)をまとめて実行したところ、最初の3件(`ParseText`/`Replace`/`RecognizeEntitiesInText`)のみ成功し、残り8件は「Save button not found, cancelling」で失敗した。

**原因判明**: `Text.CreateHTMLContent`(リッチテキスト/HTMLエディタを埋め込む特殊なダイアログ)は、通常の`ActionDialogButtonSaveButton`/`ActionDialogButtonCloseButton`とは異なる`SaveButton`/`CancelButton`という(接頭辞`ActionDialogButton`を持たない)別のauto_idをSave/Cancelボタンに使っていた。自動化スクリプトは旧auto_idでのキャンセルに失敗し、このダイアログが開いたまま次のループへ進んでしまい、以後の検索ボックス操作が全てモーダルダイアログにブロックされ、同じ「Create HTML content」ダイアログを繰り返し検出するだけになっていた(UIAutomationツリーをダンプして確認)。自動化スクリプトを両方のauto_id(`["ActionDialogButtonSaveButton", "SaveButton"]`/`["ActionDialogButtonCloseButton", "CancelButton"]`)を順に試す実装に修正し、残り8件を再実行して全て成功させた(`tests/fixtures/tier1_text_variables_batch4.txt`)。

**実機キャプチャ結果**:
```
Text.ParseText.ParseForFirstOccurrence Text: $'''sample''' TextToFind: $'''sample''' StartingPosition: 0 IgnoreCase: False OccurrencePosition=> Position
Text.Replace.ReplaceText Text: $'''sample''' TextToFind: $'''sample''' IgnoreCase: False ReplaceWith: $'''sample''' ActivateEscapeSequences: False ComparisonType: Text.TextComparisonType.CultureSensitive Result=> Replaced
Text.RecognizeEntitiesInText Text: $'''sample''' Mode: Text.RecognizerMode.DateTime Language: Text.RecognizerLanguage.English RecognizedEntities=> RecognizedEntities
Text.CreateHTMLContent HtmlEditor: `` HtmlContent=> HtmlContent
Text.ConvertDateTimeToText.FromDateTime DateTime: $'''sample''' StandardFormat: Text.WellKnownDateTimeFormat.ShortDate Result=> FormattedDateTime
Text.ConvertTextToDateTime.ToDateTime Text: $'''sample''' DateTime=> TextAsDateTime
Variables.TruncateNumber.GetIntegerPart Number: $'''sample''' Result=> TruncatedValue
Variables.IncreaseVariable Value: $'''sample''' IncrementValue: $'''sample'''
Variables.DecreaseVariable Value: $'''sample''' DecrementValue: $'''sample'''
Variables.ConvertJsonToCustomObject Json: $'''sample''' CustomObject=> JsonAsCustomObject
Variables.ConvertCustomObjectToJson CustomObject: $'''sample''' Json=> CustomObjectAsJson
```

**確認できた事実**:
- `Text.CreateHTMLContent`の`HtmlEditor`パラメータは、リッチテキストエディタの内容を何も編集せずに保存した場合、知見66で発見した空のバックティック文字列`` `` ``で直列化される——`Variables.FilterDataTable`の`FilterParameters`と同じ「バックティック文字列」構文が、全く異なるモジュール(Text)の全く異なる種類のUI(リッチテキストエディタ)でも使われていることを確認した。現状のパーサーはこの構文に未対応で`` `` ``全体が`VarRef`名にフォールバックする(クラッシュもデータ欠落も起きないことを`tests/test_pad_dsl_parser.py::test_tier1_text_variables_batch4_parses_as_generic_action_records`で回帰テスト化)。
- `Variables.IncreaseVariable`/`DecreaseVariable`は`Value`引数が`[Mutable]`で、出力変数束縛`=>`を一切持たない——知見66で確認したMutable引数パターンが数値変数の操作にも適用されることを確認。
- `Text.ParseText.ParseForFirstOccurrence`/`Text.ConvertDateTimeToText.FromDateTime`/`Text.ConvertTextToDateTime.ToDateTime`は3セグメント/2セグメントのaction_idがdecompile予測通り。
- (自動化上の教訓): PAD.Designerのアクションダイアログは、アクションの種類(通常のパラメータ入力/リッチテキストエディタ埋め込み等)によってSave/Cancelボタンのauto_idが異なる場合がある。今後のバッチでも「ダイアログが閉じ残って以降の全操作がブロックされる」という失敗モードに注意し、各バッチの最初にスタックしたダイアログが無いかを確認してから開始するのが安全。

**検証**: 11件全てが既存の汎用`ActionRecord`パーサーでコード変更無しに正しく構造化できることを確認した。これにより`Text`の完了率は13/19→19/19(完了)、`Variables`は29/34→34/34(完了)まで進んだ。

**今後**: 残るTier1/2の未キャプチャモジュール(File 0/16、Folder残り9件、Cryptography 0/8、Database 0/3、Web 0/3、XML 0/10、Cmd 0/5)を同じ自動化バッチで継続する。

## 68. Folder残り9件を実機キャプチャ(Folderモジュール完了)——「If folder exists」はIF文ブロックとして直列化されることを確認

知見67の自動化バッチでFolderモジュールの残り9件を一括キャプチャした(`tests/fixtures/tier1_folder_batch5.txt`)。9件全て一度で成功。

**実機キャプチャ結果**:
```
Folder.Copy Folder: $'''sample''' Destination: $'''sample''' IfFolderExists: Folder.IfExists.DoNothing CopiedFolder=> CopiedFolder
Folder.Create FolderPath: $'''sample''' FolderName: $'''sample''' Folder=> NewFolder
Folder.Delete Folder: $'''sample'''
Folder.Empty Folder: $'''sample'''
Folder.Move Folder: $'''sample''' Destination: $'''sample''' MovedFolder=> MovedFolder
Folder.Rename Folder: $'''sample''' NewName: $'''sample''' RenamedFolder=> RenamedFolder
Folder.GetSubfolders Folder: $'''sample''' FolderFilter: $'''*''' IncludeSubfolders: False FailOnAccessDenied: True SortBy1: Folder.SortBy.NoSort SortDescending1: False SortBy2: Folder.SortBy.NoSort SortDescending2: False SortBy3: Folder.SortBy.NoSort SortDescending3: False Subfolders=> Folders
Folder.GetSpecialFolder SpecialFolder: Folder.SpecialFolder.DesktopDirectory SpecialFolderPath=> SpecialFolderPath
IF (Folder.IfFolderExists.Exists Path: $'''sample''') THEN
END
```

**確認できた事実**:
- PAD.Designerのアクション検索パネル上では「If folder exists」のツリーノードauto_idが`If.Folder.IfFolderExists`(カテゴリが`Folder`ではなく`If`)だったが、実際にDSL化されたaction_idは`Folder.IfFolderExists.Exists`で、`IF (...) THEN ... END`という既存の`IfActionRecord`構文としてそのまま構造化できた——知見36以来の「条件分岐系アクションは`IfActionRecord`として扱う」という既存設計がこのアクションにもそのまま当てはまることを確認(decompile予測通り)。
- `Folder.Copy`の`IfFolderExists: Folder.IfExists.DoNothing`——コピー先に同名フォルダが既に存在する場合の挙動を指定するenum(`Folder.IfExists`)で、`Folder.IfFolderExists`という条件分岐アクションのenum(別物)とは名前が似ているが異なる型。
- `Folder.Delete`/`Folder.Empty`はパラメータ`Folder`のみで出力変数を持たない(破壊的操作で、対象フォルダ自体は`[Mutable]`ではなく単に戻り値が無い設計)。
- `Folder.GetSubfolders`は知見64の`Folder.GetFiles`と全く同じ`SortBy1/2/3`・`SortDescending1/2/3`・`FailOnAccessDenied`パラメータ構成(フィルタ引数名が`FileFilter`ではなく`FolderFilter`になる点のみ異なる)。

**検証**: 10件(8 ActionRecord + 1 IfActionRecord + 1 END KeywordRecord)全てが既存の汎用パーサーでコード変更無しに正しく構造化できることを確認した(`tests/test_pad_dsl_parser.py::test_tier1_folder_batch5_parses_as_generic_action_and_if_records`)。これにより`Folder`の完了率は1/10→10/10(完了)まで進んだ。

**今後**: 残るTier1/2の未キャプチャモジュール(File 0/16、Cryptography 0/8、Database 0/3、Web 0/3、XML 0/10、Cmd 0/5)を同じ自動化バッチで継続する。

## 69. Fileモジュール14件を実機キャプチャ——検索語の類似によるリーフ誤検出、挿入位置が前バッチのIFブロック内に残留する自動化上の問題を発見

Fileモジュール16件を自動化バッチで一括実行したところ14件が新規に正しくキャプチャできたが、2件で問題が発生した(`tests/fixtures/tier1_file_batch6.txt`)。

**問題1(検索語の類似によるリーフ誤検出)**: 「Convert binary to file」の検索で、直前の「Convert file to binary」と同じリーフ(`File.ConvertToBinary`)がもう一度ダブルクリックされてしまい、本来キャプチャすべき`File.ConvertFromBinary`(Base64版の`ConvertFromBase64`に相当する、バイナリ版の逆変換アクション)が取得できなかった。PADのアクション検索が部分文字列一致で、類似した2つの検索語(「Convert file to binary」「Convert binary to file」)が同じ検索結果リストを返し、リーフ検出ロジック(「ドットを含み、Expandボタンを持たない最初のTreeItem」)が毎回同じノードを拾ってしまったと考えられる。`File.ConvertFromBinary`(`ConvertBinaryToFile`)は本知見時点でも未キャプチャのまま残っている。

**問題2(挿入位置の残留)**: 「Get temporary file path」は検索結果が見つからず(`no leaf TreeItem found in search results`、検索語がUI上のアクション名と一致していない可能性——`search_term`案の見直しが必要)、スキップされた。より重要な発見として、このバッチで追加された14件全てが、**前のバッチ(知見68)で開いたままだった`IF (Folder.IfFolderExists.Exists ...) THEN`ブロックの内側**に挿入されていた(さらに`File.IfFile.Exists`の`IF`ブロックも新たにネストして追加された)。PAD.Designerのフローキャンバスは「最後に選択されたアクションの直後」に新規アクションを挿入する仕様で、知見68のバッチ終了時に最後に追加されたアクションがIFブロックの内側だったため、挿入位置(カーソル相当)もブロック内側に残留したと考えられる。キャプチャ内容自体は欠落なく正しく取得できたが(`parse_dsl()`は既存のネストしたIF/WAITブロック構文をそのまま正しく構造化できる)、今後のバッチでは各バッチ開始前に「トップレベルの空行」を明示的に選択してから新規アクションを追加するなど、挿入位置をリセットする対策が望ましい。

**実機キャプチャ結果**(前バッチのIFブロックから中身だけを取り出し、トップレベルに正規化。誤検出による重複`File.ConvertToBinary`は除外):
```
File.Copy Files: $'''sample''' Destination: $'''sample''' IfFileExists: File.IfExists.DoNothing CopiedFiles=> CopiedFiles
File.Move Files: $'''sample''' Destination: $'''sample''' IfFileExists: File.IfExists.DoNothing MovedFiles=> MovedFiles
File.Delete Files: $'''sample'''
File.RenameFiles.Rename Files: $'''sample''' NewName: $'''sample''' KeepExtension: True IfFileExists: File.IfExists.DoNothing RenamedFiles=> RenamedFiles
File.ConvertToBase64 File: $'''sample''' Base64Text=> Base64Text
File.ConvertFromBase64 Base64Text: $'''sample''' File: $'''sample''' IfFileExists: File.IfExists.DoNothing
File.ConvertToBinary File: $'''sample''' BinaryData=> BinaryData
File.ReadTextFromFile.ReadText File: $'''sample''' Encoding: File.TextFileEncoding.UTF8 Content=> FileContents
File.WriteText File: $'''sample''' TextToWrite: $'''sample''' AppendNewLine: True IfFileExists: File.IfFileExists.Overwrite Encoding: File.FileEncoding.Unicode
File.ReadFromCSVFile.ReadCSV CSVFile: $'''sample''' Encoding: File.CSVEncoding.UTF8 TrimFields: True FirstLineContainsColumnNames: False ColumnsSeparator: File.CSVColumnsSeparator.SystemDefault CSVTable=> CSVTable
File.WriteToCSVFile.WriteCSV VariableToWrite: $'''sample''' CSVFile: $'''sample''' CsvFileEncoding: File.CSVEncoding.UTF8 IncludeColumnNames: False IfFileExists: File.IfFileExists.Overwrite ColumnsSeparator: File.CSVColumnsSeparator.SystemDefault
File.GetPathPart File: $'''sample''' RootPath=> RootPath Directory=> Directory FileName=> FileName FileNameWithoutExtension=> FileNameNoExtension Extension=> FileExtension
IF (File.IfFile.Exists File: $'''sample''') THEN
    WAIT (File.WaitForFile.Created File: $'''sample''')
END
```

**確認できた事実**:
- `File.Copy`/`File.Move`/`File.RenameFiles.Rename`は`IfFileExists: File.IfExists.DoNothing`という、知見68の`Folder.Copy`の`IfFolderExists: Folder.IfExists.DoNothing`と対になるenum(モジュールごとに同名パターンの`IfExists`enumを持つ)。
- `File.WriteText`/`File.WriteToCSVFile.WriteCSV`の`IfFileExists`パラメータは、他と異なり`File.IfFileExists.Overwrite`という**別のenum型**(`File.IfExists`ではなく`File.IfFileExists`)を使う——書き込み系アクションのみ「上書き/追記等」の選択肢を持つ別のenumだと判明。
- `File.WaitForFile.Created`は知見57で確立した`WaitActionRecord`(FOR句を伴う`WAIT (...)`構文)としてそのまま構造化できた。
- `File.GetPathPart`は5つの出力変数(`RootPath`/`Directory`/`FileName`/`FileNameWithoutExtension`/`Extension`)を一度に生成する——既存の複数出力変数パーサー機構(知見46相当)がそのまま適用できる。

**検証**: 15件(12 ActionRecord + 1 IfActionRecord + 1 WaitActionRecord + 1 END KeywordRecord)全てが既存の汎用パーサーでコード変更無しに正しく構造化できることを確認した(`tests/test_pad_dsl_parser.py::test_tier1_file_batch6_parses_as_generic_action_if_and_wait_records`)。これにより`File`の完了率は0/16→14/16まで進んだ。

**今後**: 取り逃した`File.ConvertFromBinary`(Convert binary to file)・`File.GetTempPath`(Get temporary file path、検索語の見直しが必要)を次回リトライする。また自動化スクリプトに「バッチ開始前に挿入位置をトップレベルへリセットする」処理の追加を検討する。残るTier1/2の未キャプチャモジュール(Cryptography 0/8、Database 0/3、Web 0/3、XML 0/10、Cmd 0/5)も同じ自動化バッチで継続する。

**追記(計測ツール自体のバグ修正)**: `WaitForFile`(`File.WaitForFile.Created`)・`IfFile`(`File.IfFile.Exists`)を実機キャプチャ・テスト化した直後に`capture_coverage.py`で再計測したところ、両方とも未キャプチャ扱いのままだった。原因は`capture_coverage.py`の`collect_captured_action_ids()`が`isinstance(record, ActionRecord)`のみを集計対象にしており、`WaitActionRecord`/`IfActionRecord`(別のdataclass)を一切見ていなかったこと——知見68で確認した`Folder.IfFolderExists`も同じ理由で実際にはキャプチャ済みなのに未キャプチャ扱いになっていた。`_ACTION_ID_RECORD_TYPES = (ActionRecord, IfActionRecord, WaitActionRecord)`を対象に広げて修正し、`tests/test_capture_coverage.py::test_compute_report_counts_if_and_wait_action_records_too`で回帰テスト化した。この修正自体で全体の完了率が81/116→84/116に上がった(新規キャプチャによる増加ではなく、計測漏れの解消による)。

## 70. File残り2件・Cryptography全8件・Database一部2件を実機キャプチャ——検索語の曖昧一致で別モジュールの同名アクションを誤検出

事前にUIAutomationツリーを直接プローブして「Convert binary data to file」(`File.ConvertFromBinary`)・「Get temporary file」(`File.GetTempPath`、「...file path」ではなく「...file」が正しいUI表記)という正確な検索語を特定したうえで、File残り2件・Cryptography全8件・Database系3件(「Open connection」「Execute SQL statement」「Close connection」)を1バッチで実行した(`tests/fixtures/tier1_crypto_database_batch7.txt`)。

**新たな自動化上の問題(検索語の曖昧一致で別モジュールのアクションを誤取得)**: 「Close connection」で検索したところ、意図した`Database.CloseConnection`ではなく**`FTP.CloseConnection`**(FTPモジュール、Tier1/2の対象外)がリーフとして検出・保存されてしまった。PADのアクション検索はモジュール名を考慮せず部分文字列一致するため、複数モジュールに同名アクション(`XXX.CloseConnection`)が存在する場合、検索結果の先頭に出たものを拾う現状のロジックでは区別できない。誤って捕捉した`FTP.CloseConnection`はpad2pyのTier1/2対象リストに無いため、フィクスチャには採用せず破棄した——知見36以来の「架空の情報を記録しない」方針に基づき、`Database.CloseConnection`は依然未キャプチャとして正直に記録する。

**自動化上の既知の制約(挿入位置リセットの限界)**: 知見69でのバッチ開始前の「`ProgramItemsListBoxActions`の先頭要素をクリックして挿入位置をリセットする」対策を適用したが、今回も新規アクション全てが既存のネストした`IF (File.IfFile.Exists ...) THEN`ブロックの内側(`WAIT`の直後)に追加された。これは新規アクションの追加位置がリスト選択ではなく「フロー全体の末尾」(構造的に最も深くネストしたブロックの末尾)固定で決まる設計であることを示唆する——リスト項目のクリックによる挿入位置リセットは効果が無いと判明した。ただし、ネスト自体はキャプチャ内容の正確性には影響しない(`parse_dsl()`は既存のネスト構文をそのまま正しく構造化できる)ため、今後のバッチでは無理に挿入位置をトップレベルに戻そうとせず、ネストされたまま出力されることを前提にフィクスチャ化時に手動でデデントする運用で十分とわかった。

**実機キャプチャ結果**(ネストを除去し、誤検出の`FTP.CloseConnection`を除外したもの):
```
File.ConvertFromBinary BinaryData: $'''sample''' File: $'''sample''' IfFileExists: File.IfExists.DoNothing
File.GetTempPath TempFile=> TempFile
Cryptography.EncryptText.EncryptTextWithAES Encoding: Cryptography.EncryptionEncoding.Unicode TextToEncrypt: $'''sample''' EncryptionKey: P'<DPAPI base64>' PaddingMode: Cryptography.PaddingMode.PKCS7 KeySize: Cryptography.AESKeySize.Bits256 EncryptedText=> EncryptedText
Cryptography.EncryptFromFile.EncryptFromFileWithAES Encoding: Cryptography.EncryptionEncoding.Unicode FileToEncrypt: $'''sample''' EncryptionKey: P'<DPAPI base64>' PaddingMode: Cryptography.PaddingMode.PKCS7 KeySize: Cryptography.AESKeySize.Bits256 EncryptedText=> EncryptedText2
Cryptography.DecryptText.DecryptTextWithAES Encoding: Cryptography.EncryptionEncoding.Unicode TextToDecrypt: $'''sample''' DecryptionKey: P'<DPAPI base64>' Padding: Cryptography.PaddingMode.PKCS7 KeySize: Cryptography.AESKeySize.Bits256 DecryptedText=> DecryptedText
Cryptography.DecryptToFile.DecryptToFileWithAES Encoding: Cryptography.EncryptionEncoding.Unicode TextToDecrypt: $'''sample''' DecryptionKey: P'<DPAPI base64>' DecryptToFile: $'''sample''' IfFileExists: Cryptography.IfFileExists.AddSequentialSuffix Padding: Cryptography.PaddingMode.PKCS7 KeySize: Cryptography.AESKeySize.Bits256 DecryptedFile=> DecryptedFile
Cryptography.HashText HashAlgorithm: Cryptography.HashAlgorithm.SHA256 Encoding: Cryptography.EncryptionEncoding.Unicode TextToHash: $'''sample''' HashedText=> HashedText
Cryptography.HashFromFile HashAlgorithm: Cryptography.HashAlgorithm.SHA256 Encoding: Cryptography.EncryptionEncoding.Unicode File: $'''sample''' HashedText=> HashedText2
Cryptography.HashTextWithKey HashAlgorithm: Cryptography.KeyedHashAlgorithm.HMACSHA256 Encoding: Cryptography.EncryptionEncoding.Unicode TextToHash: $'''sample''' HashKey: P'<DPAPI base64>' HashedText=> HashedText3
Cryptography.HashFromFileWithKey KeyedHashAlgorithm: Cryptography.KeyedHashAlgorithm.HMACSHA256 Encoding: Cryptography.EncryptionEncoding.Unicode FileToHash: $'''sample''' HashKey: P'<DPAPI base64>' HashedText=> HashedText4
Database.Connect.Connect ConnectionString: $'''sample''' Connection=> SQLConnection
Database.ExecuteSqlStatement.Execute Connection: SQLConnection Statement: `` Timeout: 30 Result=> QueryResult
```

**確認できた事実**:
- 知見65で予測した「`Sensitive`扱いの引数は`P'<DPAPI暗号化Base64>'`構文で直列化される」が、`Cryptography.EncryptText`/`EncryptFromFile`の`EncryptionKey`・`DecryptText`/`DecryptToFile`の`DecryptionKey`・`HashTextWithKey`/`HashFromFileWithKey`の`HashKey`全てで裏付けられた——decompile調査で`[ArgumentStyling(Sensitive = true)]`が付いていた全てのプロパティが、実機でも例外なく同じ構文を使うことを確認。
- `Cryptography.HashText`/`HashFromFile`(キー無し版)は`HashAlgorithm`が`Cryptography.HashAlgorithm`(SHA256等の無印ハッシュ)、`HashTextWithKey`/`HashFromFileWithKey`(キー付き版)は`Cryptography.KeyedHashAlgorithm`(HMACSHA256等)という、似ているが異なるenum型を使う——キー付き/無しでハッシュアルゴリズムの選択肢自体が切り替わる設計。
- `Cryptography.DecryptToFile`の`IfFileExists`パラメータは`Cryptography.IfFileExists.AddSequentialSuffix`という、File/Folderモジュールの`IfExists`/`IfFileExists`とは別の、Cryptographyモジュール独自のenum型。
- `Database.ExecuteSqlStatement.Execute`の`Statement`パラメータは、知見66・67で確認した空のバックティック文字列`` `` ``構文——SQL文を編集しなかった場合のデフォルト値。`Timeout: 30`という数値の既定値も省略されず直列化される(知見62以来の一貫したパターン)。

**検証**: 12件全てが既存の汎用`ActionRecord`パーサーでコード変更無しに正しく構造化できることを確認した(`tests/test_pad_dsl_parser.py::test_tier1_crypto_database_batch7_parses_as_generic_action_records`)。これにより`File`の完了率は12/16→14/16、`Cryptography`は0/8→8/8(完了)、`Database`は0/3→2/3まで進んだ。

**今後**: これにより`File`は16/16(完了)まで進んだ。残る`Database.CloseConnection`(検索語の見直しが必要、例えば「Close database connection」等でFTPと区別する)、および残るTier1/2の未キャプチャモジュール(Web 0/3、XML 0/10、Cmd 0/5)を同じ自動化バッチで継続する。

## 71. Database残り1件・Compression残り1件・Web全3件・XML全10件を実機キャプチャ——事前UIプローブと「名前の完全一致優先」自動化修正により15/15を一度で成功

知見70で判明した「検索語の部分文字列一致による誤爆」問題(`Close connection`→`FTP.CloseConnection`)に対処するため、今回のバッチ実行前にUIAutomationツリーを直接プローブして全15項目の正確なUI表示名を確認した(例: Database側は`Close SQL connection`、XPathアクションは`Execute XPath expression`——`search_term`案の「Execute XPath query」とは異なる、`Invoke SOAP service`ではなく`Invoke SOAP web service`)。さらに自動化スクリプトのリーフ選択ロジックを「ドットを含み展開ボタンを持たない最初のリーフ」から「**名前が検索語と完全一致(大小無視)するものを優先**、無ければ最初の候補にフォールバック(その場合は警告ログを出力)」に変更した。この2つの対策により、`Database.Close`・`Compression.UnzipFiles`・Web全3件・XML全10件の計15件を警告ゼロで一度で正しくキャプチャできた(`tests/fixtures/tier1_web_xml_batch8.txt`)。

**実機キャプチャ結果**:
```
Database.Close Connection: SQLConnection
Compression.UnzipFiles ArchivePath: $'''sample''' DestinationFolder: $'''sample''' Password: P'<DPAPI base64>' IncludeMask: $'''sample''' ExcludeMask: $'''sample'''
Web.DownloadFromWeb.Download Url: $'''sample''' ConnectionTimeout: 30 FollowRedirection: True ClearCookies: False UserAgent: $'''Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.21) Gecko/20100312 Firefox/3.6''' Encoding: Web.Encoding.AutoDetect AcceptUntrustedCertificates: False WebPageText=> WebPageText
Web.InvokeWebService.InvokeWebService Url: $'''sample''' Method: Web.Method.Get Accept: $'''application/xml''' ContentType: $'''application/xml''' CustomHeaders: $'''sample''' RequestBody: $'''sample''' ConnectionTimeout: 30 FollowRedirection: True ClearCookies: False FailOnErrorStatus: False EncodeRequestBody: True UserAgent: $'''Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.21) Gecko/20100312 Firefox/3.6''' Encoding: Web.Encoding.AutoDetect AcceptUntrustedCertificates: False TrimRequestBody: True ResponseHeaders=> WebServiceResponseHeaders Response=> WebServiceResponse StatusCode=> StatusCode
Web.InvokeSoapService.InvokeSoapService Endpoint: $'''sample''' CustomHeaders: $'''sample''' RequestBody: $'''sample''' ConnectionTimeout: 30 FollowRedirection: True ClearCookies: False FailOnErrorStatus: False UserAgent: $'''Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.21) Gecko/20100312 Firefox/3.6''' Encoding: Web.Encoding.AutoDetect AcceptUntrustedCertificates: False TrimRequestBody: True ResponseHeaders=> SoapServiceResponseHeaders Response=> SoapServiceResponse StatusCode=> StatusCode2
XML.ReadFromFile File: $'''sample''' Encoding: XML.FileEncoding.DefaultEncoding XmlDocument=> XmlDocument
XML.WriteXmlToFile.WriteToFileFormatted File: $'''sample''' Xml: `` Encoding: XML.FileEncoding.DefaultEncoding Indentation: 2
XML.GetXmlElementValue.GetElementValue Document: XmlDocument XPathQuery: $'''sample''' TextValue=> XmlElementValue
XML.SetElementValue Document: XmlDocument XPathQuery: $'''sample''' ElementValue: $'''sample'''
XML.GetXmlElementAttribute.GetElementAttribute Document: XmlDocument XPathQuery: $'''sample''' AttributeName: $'''sample''' TextValue=> XmlAttributeValue
XML.SetElementAttribute Document: XmlDocument XPathQuery: $'''sample''' AttributeName: $'''sample''' AttributeValue: $'''sample'''
XML.RemoveElementAttribute Document: XmlDocument XPathQuery: $'''sample''' AttributeName: $'''sample'''
XML.InsertElement Document: XmlDocument XPathQuery: $'''sample''' Element: $'''sample'''
XML.RemoveElement Document: XmlDocument XPathQuery: $'''sample'''
XML.ExecuteXPathQuery.ExecuteXPath XmlDocument: $'''sample''' XPathQuery: $'''sample''' XPathResults=> XPathResults
```

**確認できた事実**:
- **自動変数参照の補完**: `XML.ReadFromFile`で`XmlDocument`という出力変数を作った直後、以降の`XML.GetXmlElementValue`等の`Document`パラメータを一切編集せずに保存したところ、空文字列や未入力エラーにはならず、既に生成済みの`XmlDocument`変数への参照(`Document: XmlDocument`、`$'''...'''`でラップされない裸の`VarRef`)が自動的に事前入力されていた。これは文字列型パラメータ(常に空の`Edit`として露出し`"sample"`で埋められる)とは異なる挙動で、**オブジェクト型パラメータは、スコープ内に型が一致する変数が1つだけ存在する場合、PAD側がそれを自動的にデフォルト選択する**ことを示す——自動化スクリプトの「空のEditを`"sample"`で埋める」ロジックがこれらのパラメータに触れなかったにもかかわらず、有効な値(既存変数参照)が入っていたことから判明した新知見。
- `Web.InvokeWebService`/`Web.InvokeSoapService`の`UserAgent`デフォルト値が、ブラウザのUser-Agent文字列を模した具体的な文字列(`Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.21) Gecko/20100312 Firefox/3.6`)であることを確認——古いFirefoxのUser-Agentがハードコードされたデフォルト値になっている。
- `XML.WriteXmlToFile.WriteToFileFormatted`の`Xml`パラメータは、知見66・67・70で確認した空のバックティック文字列`` `` ``構文。
- `Compression.UnzipFiles`の`Password`は知見65で確認した`P'<DPAPI base64>'`構文——Zip/Unzip双方の暗号化パスワードが同じ構文で統一されている。

**検証**: 15件全てが既存の汎用`ActionRecord`パーサーでコード変更無しに正しく構造化できることを確認した(`tests/test_pad_dsl_parser.py::test_tier1_web_xml_batch8_parses_as_generic_action_records`)。これにより`Database`は2/3→3/3(完了)、`Compression`は1/2→2/2(完了)、`Web`は0/3→3/3(完了)、`XML`は0/10→10/10(完了)まで進んだ。全体は96/116→111/116(96%)に到達し、残るのは`Cmd`モジュール(0/5)のみとなった。

**今後**: 残る`Cmd`モジュール5件(`OpenCmdSession`/`WriteToCmdSession`/`ReadFromCmdSession`/`WaitForTextOnCmdSession`/`CloseCmdSession`)を同じ自動化バッチでキャプチャすれば、Tier1/2の116件全ての実機キャプチャが完了する。

## 72. Cmdモジュール全5件を実機キャプチャ——Tier1/2対象116件の実機DSLキャプチャが完了(100%)

事前にUIプローブで全5件の正確なUI表示名を確認してから(全て`search_term`案と完全一致)実行し、5/5を警告ゼロで一度で正しくキャプチャした(`tests/fixtures/tier1_cmd_batch9.txt`)。これにより`capture_coverage.py`の計測結果が**116/116(100%)**に到達し、知見62から始まったTier1/2実機DSLキャプチャの取り組みが完了した。

**実機キャプチャ結果**:
```
Cmd.Open.Open Directory: $'''sample''' Session=> CmdSession
Cmd.Write Session: CmdSession Command: $'''sample''' SendEnter: True
Cmd.ReadFromCmdSession.Read Session: CmdSession CmdOutput=> CmdOutput
Cmd.WaitForText Session: CmdSession Text: $'''sample''' IsRegEx: False IgnoreCase: True Timeout: 0
Cmd.Close Session: CmdSession
```

**確認できた事実**:
- `Cmd.WaitForText`(「Wait for text on CMD session」)は、知見50・57で確立した`WAIT (<ActionId> ...) FOR <秒数>`構文(`WaitActionRecord`)を使わず、`Timeout: 0`という**通常のパラメータ**を持つ普通の`ActionRecord`として直列化される。つまり「名前に`Wait`を含むアクション」が必ず`WaitActionRecord`になるわけではなく、`[WaitAction]`カテゴリに属するかどうかという実装上の分類が決め手になる——decompile調査で確認していた区分が実機でも裏付けられた。
- `Cmd.Open.Open`/`Cmd.Write`/`Cmd.ReadFromCmdSession.Read`/`Cmd.Close`は全て`Session`パラメータで同一の`CmdSession`変数を参照する(知見71で確認した「オブジェクト型パラメータの自動補完」がここでも働き、2つ目以降のアクションでは`Session: CmdSession`が自動入力された)。

**検証**: 5件全てが既存の汎用`ActionRecord`パーサーでコード変更無しに正しく構造化できることを確認した(`tests/test_pad_dsl_parser.py::test_tier1_cmd_batch9_parses_as_generic_action_records`)。これにより`Cmd`は0/5→5/5(完了)となり、`capture_coverage.py`の全体完了率は111/116→**116/116(100%)**に到達した。

**総括**: 知見62(2026年、`Text.Trim`の初回手動キャプチャ)から始まり、知見63でUIAutomation自動化バッチスクリプトを確立、知見64・65でDPAPI暗号化構文(`P'...'`)を発見、知見66-72で9回のバッチ実行を経て、Text/DateTime/Variables/File/Folder/Compression/Cryptography(Tier1)、Database/Web/XML/Cmd/Clipboard(Tier2)の全12モジュール・116アクションの実機DSLキャプチャが完了した。この過程で、既存の汎用パーサー設計(`ActionRecord`/`IfActionRecord`/`WaitActionRecord`/`KeywordRecord`)が未知のアクションに対しても一切のコード変更なしで正しく構造化できることが一貫して確認され、知見36以来の「汎用パーサー設計」方針の正しさが実機データで裏付けられた。同時に、バックティック文字列`` `` ``・`{ }`配列リテラル・`P'...'`DPAPI構文という3つの「パーサー未対応だがクラッシュもデータ欠落もしない」構文が発見され、今後の拡張課題として記録されている。自動化そのものについても、検索語の部分文字列一致による誤爆(知見70)とその対策(名前の完全一致優先、知見71)、ダイアログ種別によるSave/Cancelボタンauto_idの違い(知見67)、ネストした挿入位置の残留(知見69)という再利用可能な知見が蓄積された。

## 73. `pad_action_lib`(Tier1/2の純粋関数コア、decompileベースの推定実装)を知見66-72で確認済みの実機action_id・パラメータ名へ結線し、`pad_codegen.py`のカバレッジを31%→80%へ引き上げた

`pad_action_lib`自体は「action_idからこの結線を行うのは実機でDSL構文・パラメータ直列化形式を確認した後に別途行う」と自身のdocstringで明記していた、decompileベースの推定実装だった。知見62-72でTier1/2の116アクション全件の実機DSL(action_id文字列・パラメータ名・enum値の実際の表記)が確認できたため、この結線作業を実施した。`dump_daemon/pad_codegen/actions/`配下に`text.py`/`variables.py`/`file.py`/`folder.py`/`compression.py`/`cryptography.py`/`database.py`/`web.py`/`xml.py`/`cmd.py`/`clipboard.py`/`pad_datetime.py`を新設し、既存の`generate_action()`のchain-of-responsibilityディスパッチに追加した(各ファミリーは互いに疎結合、`None`を返せば次のファミリーへフォールスルーする既存の設計をそのまま踏襲)。

**計測結果**: `dump_daemon/codegen_coverage.py`の全体カバレッジが31%(57/186)→**80%(149/186)**に到達した(`action`分岐点は21/137→109/137)。

**安全策——でっち上げたコードを出さないための共通ガード(`actions/_support.py`)**:
- 知見72で発見した3つの「パーサー未対応構文」(`P'<DPAPI base64>'`・空のバックティック文字列` `` `・`{ }`配列リテラル)は、いずれも正当なPython識別子にならない`VarRef`へのパーサーフォールバックとして現れる。全ファミリーモジュール共通の`safe_render()`がこれを検出して`None`を返し、呼び出し元はその場で`generate()`から`None`を返して既存の汎用`# TODO`フォールバックに委ねる——これにより`Cryptography.EncryptText`等のDPAPI鍵を持つ6アクション、`Compression.ZipFiles`/`UnzipFiles`のDPAPIパスワード、`Database.ExecuteSqlStatement.Execute`・`XML.WriteXmlToFile`のバックティック引数、`Variables.CreateNewDatatable`の`{ }`は、壊れた構文を出力せず自動的に未対応のまま残る。
- `pad_action_lib`側が常に`NotImplementedError`を投げる関数(PAD独自の`ComparisonCalculator.Compare`比較エンジンに依存する`Variables.SubtractLists`/`FindCommonListItems`、フィルタ/結合条件のDataTableスキーマ未確認の`FilterDataTable`/`JoinDataTable`、外部NLPライブラリ未導入の`Text.RecognizeEntitiesInText`)は、呼び出しコードを生成すると「生成できたように見えて実行時に必ず壊れる」ためTODOコメントより悪い結果になる——これらは明示的に結線せず、恒久的にフォールバックへ委ねている。
- `File.ReadFromCSVFile.ReadCSV`/`WriteToCSVFile.WriteCSV`・`Variables.ConvertDataTableToCSV.*`/`GenerateDataTableFromCSV.*`は、実機DSLで`FirstLineContainsColumnNames`/`IncludeColumnNames`が明示的に`False`だが、`pad_action_lib.datatable`のCSV変換は常にヘッダー行ありを仮定しており、結線すると見た目は動くが1行分データがずれる・余分なヘッダー行が混入するという静かな誤りになるため、意図的に未対応のまま残した。
- `Variables.FindOrReplaceInDataTable.FindItemInDataTableEverywhere`は実機の出力契約(`DataTableMatches`への一致結果)と`pad_action_lib.find_or_replace_in_datatable()`(置換件数の`int`を返す、`replace_value`必須)が一致しないため未対応。

**既存のパーサー設計を再利用した非自明なマッピング**:
- `Variables.IncreaseVariable`/`DecreaseVariable`・`XML`の各setter/mutator系(`SetElementValue`/`SetElementAttribute`/`RemoveElementAttribute`/`InsertElement`/`RemoveElement`)は、`=>`出力変数を持たない代わりに入力パラメータの変数へ実質的に再代入する意味論であることが実機DSLから読み取れたため、`Document`/`Value`パラメータが`VarRef`である場合のみ同じ変数名へ`{var} = pad_action_lib.func({var}, ...)`という再代入コードを生成する(リテラル値の場合は書き戻す先が無いため未対応のまま残る——`Variables.IncreaseVariable`/`DecreaseVariable`はこの理由で、サンプル値埋め込みにより`Value`が文字列リテラルになっている`tier1_text_variables_batch4.txt`では依然TODOのまま)。
- `Text.GetSubtext.GetSubtext`は実機DSLに`StartIndexType`/`LengthType`相当のモード列挙値が出力されないが、`CharacterPosition`/`NumberOfChars`が明示的に指定されていることから「特定位置から指定文字数」モードが選ばれていたと判断し、`pad_action_lib.text_actions.get_subtext()`の`"StartOfText"`/`"EndOfText"`以外の任意文字列で"カスタム"分岐を選ぶ既定動作を使って変換した。
- `Text.ConvertDateTimeToText.FromDateTime`の`StandardFormat`は、実機で確認できた`ShortDate`の1値だけを.NETの標準書式指定子`"d"`(`ShortDatePattern`、PAD固有のデコンパイル知識ではなく公開されている.NET仕様)へ対応付け、他の値は未確認としてフォールバックに委ねた。
- `Variables.MergeDataTables`(`MergeMode: AddExtraColumns`)は、`merge_datatables()`が行を無条件連結するだけ(各行は独立した辞書のため列数の不一致があってもそのまま追加されるだけでエラー・欠落にならない)という実装が、確認できた唯一の値「余分な列があれば追加する」の意味と合致すると判断し、その場合のみ結線した。
- `File.Copy`/`Move`/`Delete`/`RenameFiles.Rename`の`Files`パラメータは、複数ファイル(リスト変数)を渡すケースの実際の型が未確認のため、生成コードが実行時に`isinstance`で単一文字列/リストどちらでも動くよう正規化する(`Files if isinstance(Files, list) else [Files]`)——どちらか一方の型を決め打ちしない。
- `Cmd.*`は`Open`以外、`Session`変数が`pad_action_lib.cmd_actions.CmdSession`インスタンスを保持する想定でそのメソッド呼び出し(`.write()`/`.read()`/`.wait_for_text()`/`.close()`)に変換する——`cmd_actions`モジュール自体の再importは不要。

**`File.WaitForFile.Created`(wait_action)・`File.IfFile.Exists`/`Folder.IfFolderExists.Exists`(condition_action_call)**: いずれもUI要素セレクタを一切使わない単純な存在チェックで、`pad_action_lib.file_actions.if_file_exists()`/`folder_actions.if_folder_exists()`への素直な変換が可能だったため、既存の`actions/wait.py`・`actions/conditions.py`(`UIAutomation.IfWindow.*`用の既存の仕組み)にそれぞれ分岐を追加した。`WaitForFile`はタイムアウト指定なし(知見50と同じ無期限ポーリング)の場合のみ対応する。

**検証**: `tests/test_pad_codegen_tier1_actions.py`(フィクスチャ9件それぞれについて、結線したアクションが`# TODO`に倒れず正しい呼び出しになること・意図的に未対応としたアクションが正直に`# TODO`のまま残ることの両方を確認)、および全フィクスチャの生成コードが`ast.parse`/`compile()`で構文的に正しいことを確認する回帰チェックを実施した。さらに`tests/test_codegen_coverage.py`で全体カバレッジ80%以上をロックする回帰テストを追加した。

## 74. 知見72で発見した3つのパーサー未対応構文のうち2つ(空のバックティック文字列``・空の`{ }`配列リテラル)をパーサーに実装し、カバレッジを80%→82%へ引き上げた(VM実機操作無しで完結)

知見73の時点で`pad_codegen.py`のカバレッジは80%(149/186)だったが、残るTODOを精査した結果、全て「でっち上げを避けるための正直な未対応」(PAD独自の比較エンジン依存・DataTableスキーマ未確認・外部NLPライブラリ未導入・DPAPI復号不可能等、知見73に詳述済み)であり、それ自体を結線する余地は無いと確認した。唯一の例外が、知見65・67・70-72で発見した3つの「パーサー未対応だがクラッシュもデータ欠落もしない構文」のうち、`P'<base64>'`(DPAPI、そもそも暗号化環境でなければ復号不可能なため恒久的に非対応——知見65の結論通り)を除く2つ:

- **空のバックティック文字列` `` `**: `Text.CreateHTMLContent`の`HtmlEditor`・`Database.ExecuteSqlStatement.Execute`の`Statement`・`XML.WriteXmlToFile.WriteToFileFormatted`の`Xml`で、いずれも「中身を一度も編集せず保存した」場合の値として実機確認済み(知見66・67・70・71)。これまでに観測された全ての実例が空文字列のみで、非空の場合の表現・エスケープ規則は実機未確認。
- **空の`{ }`配列リテラル**: `Variables.CreateNewDatatable`の`InputTable`で、2次元配列を一度も編集せず保存した場合の値として実機確認済み(知見66)。非空の場合の表現は実機未確認。

いずれも「空の場合」という限定的だが実機確認済みの範囲でのみパーサーを拡張した(非空の場合への一般化は行わない——架空の文法を推測しない方針を維持)。`pad_dsl/line_parser.py`の`_resolve_value()`に`token == "``"`の完全一致チェックを追加し、`_resolve_param_token()`という新しい2トークン先読みヘルパー(`{`の直後が`}`の場合のみ空リストとして消費)を導入して、`ActionRecord`のパラメータ解析・`WAIT (...)`/`IF (...)`の丸括弧内解析の両方の呼び出し元で使うようにした。`pad_codegen/render.py`の`render_value()`にも`list`型の描画(要素ごとに再帰的に`render_value()`、現状は空リストのみ生成される)を追加した。

この結果、`_support.safe_render()`がもはや`VarRef`へのフォールバックとして検出しなくなった4アクション(`Text.CreateHTMLContent`・`Database.ExecuteSqlStatement.Execute`・`XML.WriteXmlToFile.WriteToFileFormatted`・`Variables.CreateNewDatatable`)を、それぞれ対応する`pad_action_lib`の既存関数(`text_actions.create_html_content()`・`database_actions.execute_sql_statement()`・`xml_actions.write_xml_to_file()`・`variables_actions.create_new_datatable()`——いずれも知見62-73の時点で既に実装済みだったが、パーサー側の制約で結線できていなかった)へ結線した。

**この知見は実機PAD(GCP VM `pad2py-pad-host`)の操作を一切伴わない**——既に知見62-72で実機キャプチャ済みのフィクスチャ(`tests/fixtures/tier1_*.txt`)だけを根拠にしたパーサー/codegenのみの変更。

**検証**: `tests/test_pad_dsl_parser.py`の該当する回帰テスト4件(`VarRef(name="``")`/`VarRef(name="{")`を期待する古いアサーションを、`""`/`[]`を期待する新しいアサーションへ更新)、`tests/test_pad_codegen_tier1_actions.py`の該当する回帰テスト4件(`# TODO`を期待するアサーションを、実際の変換後コードを期待するアサーションへ更新)、および`tests/test_codegen_coverage.py`の閾値ロックを80%→82%へ更新した。全537件(既存529件+変更分)がパスし、スキップ25件(Windows専用)は変化無し。

## 75. 【新しい実機キャプチャ手法を確立・運用】`IfFunctionRecord`(Contains/Does not contain/Is empty/Is not empty)を実機確認——クリップボードへのペースト+コピー読み取りだけでPADデザイナー自体を駆動する手法を発見

知見18-2・docs-local/robin_language_source_findings.mdで「`FunctionExpression`(`Contains(a, b)`のような関数呼び出し形式の条件式)を実際に生成するPAD機能は未特定」として長年持ち越していた課題を解決した。

**新しい検証手法**: 従来の実機検証は「PADデザイナーでアクションを追加→コピー→クリップボードを読む」という一方向(読み取りのみ)の操作だった。今回、**PADデザイナーの「アクションリスト」領域にDSLテキストをクリップボード経由でペースト(Ctrl+V)すると、実際に構造化されたアクションカードとして取り込まれる**ことを発見した——つまりクリップボードは読み取り専用の経路ではなく、**書き込み(ペーストによるフロー編集)にも使える双方向の経路**だった。これにより、PAD実機をドラッグ&ドロップやマウスクリックに一切頼らず、`clipwire exec`(Tailscale経由のリモートコマンド実行、RDPセッション接続不要)だけで完全に駆動できる:

1. Windows側で`[System.Windows.Forms.Clipboard]::SetText(...)`でクリップボードに仮説のDSLテキストをセットする。
2. PADデザイナーの「アクション」リスト領域(`List "Actions"`、UIAの`ListItem`群を含むコンテナ)にUIA経由で`type_keys("^v")`(Ctrl+V)を送る——`pywinauto`の`control.type_keys()`は対象コントロールへの疑似キーボード入力で、`click_input()`やマウス移動とは異なり**RDP接続無しでも機能する**(知見11・UiPath側の既知の制約とは別の経路)。
3. 貼り付け後のアクションリストをUIA経由で読み取り、PADが実際に構造化されたアクションカード(例: `"If Var1 Contains Var2 then"`という自然文表示)としてレンダリングしたか、構文エラー(`"Has error"`)になったかを確認する。
4. 正しく取り込まれたら、同じ領域を全選択(Ctrl+A)してコピー(Ctrl+C)し、クリップボードを読み戻す(`Get-Clipboard`)——ペースト前のテキストと完全一致することを確認すれば、往復(round-trip)が取れた実機確認となる。

この手法により、**仮説のDSL構文をPADデザイナー自身に「本当に解釈できるか」を問いかけ、構造化された自然文表示・エラーの有無で判定する**という、従来の「アクションを1つずつ追加してコピー」よりはるかに高速な反復検証が可能になった(でっち上げた文法を知見として記録しているわけではない——あくまでPAD自身の解釈結果を観察している点は従来の実機検証と同じ)。

**確認できた事実**: `_FUNC_COND_RE`(`pad_dsl/line_parser.py`、`^(IF|ELSE IF) ([A-Za-z_][A-Za-z0-9_]*)\((.*)\) THEN$`)が想定する関数名として、以下4つを実機で確認した(`tests/fixtures/if_function_contains_notcontains_isempty_isnotempty.txt`):

```
SET Var1 TO $'''hello'''
SET Var2 TO $'''ell'''
IF Contains(Var1, Var2) THEN
END
IF NotContains(Var1, Var2) THEN
END
IF IsEmpty(Var1) THEN
END
IF IsNotEmpty(Var1) THEN
END
```

- `Contains(a, b)` → デザイナー上「If a Contains b then」、エラー無し。
- `NotContains(a, b)` → 「If a Does not contain b then」、エラー無し(`DoesNotContain`/`NotContain`/`ContainsNot`等の他の綴りは全て`"Has error"`になり不採用と確認済み)。
- `IsEmpty(a)` → 「If a Is empty then」、エラー無し(単項関数、引数1個)。
- `IsNotEmpty(a)` → 「If a Is not empty then」、エラー無し(知見18-2の時点では未確認だった対の肯定/否定ペア)。

**対照実験(否定側の確認)**: 存在しない関数名`Blurgle(Var1, Var1)`を同じ構文でペーストすると、`"If Var1 Var1 then, Has error"`(関数名部分の表示テキストが欠落し、エラー扱いになる)——これにより、上記4つが単に「構文として丸ごと受理される」のではなく、**PAD側で個別に認識された関数名として扱われている**ことを対照的に確認した。

**pad_codegen結線**: `IfFunctionRecord`/`ElseIfFunctionRecord`の`function_name`が上記4つのいずれかの場合、Pythonの`in`/`not in`演算子・真偽値判定へ変換する(`Contains`→`b in a`、`NotContains`→`b not in a`、`IsEmpty`→`not a`、`IsNotEmpty`→`bool(a)`)。未知の関数名(前述の対照実験が示す通り、PAD自体が認識しない可能性が高い)は安全に`# TODO`へフォールバックする——`pad_codegen/__init__.py`の`_generate_conditional()`が`IfFunctionRecord`を無条件で`NotImplementedError`にしていた既存のポリシーを、この4つの既知関数名に限定して緩和した。

**検証**: `tests/test_pad_codegen.py`に実機フィクスチャベースのテストを追加し、4つの関数それぞれが正しいPython条件式に変換されること・未知の関数名(`Blurgle`等)は従来通り`NotImplementedError`のままであることを確認した。

## 76. ユーザー提案により`Microsoft.Flow.RPA.Desktop.Robin.Engine.dll`等を再デコンパイルし、action_id構築ロジックの一般式を発見——ただしPDFモジュールでは依然不一致

知見75のペースト技法でTier3(PDF)のaction_idを推測しても`"Unknown action"`になり続けた(design/pad_todo.md参照)ことを受け、ユーザーから「dotnetのdll/exeをリバース解析してみたら」との提案があり、`ilspycmd`(`~/.dotnet`に導入済み、`DOTNET_ROOT`/`PATH`の設定が必要だった)で関連DLLを再デコンパイルした(本リポジトリには逆コンパイル結果自体はコミットしない方針は従来通り——知見の要旨のみ記録)。

**取得・デコンパイルしたDLL**(いずれも`C:\Program Files (x86)\Power Automate Desktop\`直下、WinRM/clipwire経由でBase64取得):
- `Microsoft.Flow.RPA.Desktop.Modules.PDF.Actions.dll`(123,680バイト)
- `Microsoft.Flow.RPA.Desktop.Modules.Text.Actions.dll`(181,048バイト、既に実機確認済みの`Text.Trim`との対比用)
- `Microsoft.Flow.RPA.Desktop.Robin.Engine.dll`(766,248バイト)
- `Microsoft.PowerPlatform.PowerAutomate.Desktop.Actions.SDK.dll`(42,272バイト)

**発見した一般式**(`Robin.Engine.ExportTools.ActionMapperExport.GetMapper()`、`NewSelectorId`の計算ロジックそのもの):

```csharp
val.ModuleName = virtualModule?.Name ?? module.Name;  // module.Nameは[assembly: AssemblyTitle("...")]
val.NewSelectorId = ModuleName + "." + action.Id
    + (HasSelectors(action) ? ("." + selector.ActionName) : "");  // 複数セレクタ持ちの場合のみ3セグメント目
```

つまり**DSL上のaction_idは`{AssemblyTitleAttribute}.{[Action]属性のId(またはNameの後継)}[.{個別セレクタ名}]`という式で構築される**——これは知見66「複数ActionSelectorを持つアクションのaction_idは3セグメント、単一セレクタは2セグメント」を裏付け、かつ**モジュール接頭辞(1セグメント目)の正確な出どころを初めて特定した**(従来は「察するに`Module.Action`形式」という帰納的推測だった)。

**`Text.Trim`で実証**: `TrimTextAction`の属性は`[Action(Name = "Trim", Order = 4)]`(`Name`は`[Obsolete("Use ActionAttribute.Id instead.")]`——新しいアクションは`Id`、古いものは`Name`を使う过渡期と判明)、assembly titleは`[assembly: AssemblyTitle("Text")]`。式を適用すると`"Text" + "." + "Trim"` = `"Text.Trim"`——既に実機確認済みの値と完全一致。

**`PDF`モジュールでは式を適用しても不一致**: `ExtractTextFromPDFAction`の属性は`[Action(Order = 1, Id = "ExtractTextFromPDF")]`、assembly titleは`[assembly: AssemblyTitle("Pdf")]`(大文字小文字に注意——`"PDF"`ではなく`"Pdf"`)。式通りなら`"Pdf.ExtractTextFromPDF"`になるはずだが、知見75のペースト技法でこの文字列(および`"PDF.ExtractTextFromPDF"`・`"PDF.Actions.ExtractTextFromPDF"`・`"PDF.ExtractTextFromPDF.Execute"`の各パターン)を試しても全て`"Unknown action, Has error"`になった(同じtickで実機確認・design/pad_todo.md参照)。`ActionMapperExport`のコードには`action.VirtualModule`という、`module.Name`を上書きできる別経路(`VirtualModuleInfo`)が存在することも判明したが、`VirtualModuleAttribute`自体の定義・使用箇所はまだ追えていない(`Robin.Core.dll`/`Robin.Language.dll`等、未取得の別アセンブリに実装がある可能性が高い)。

**今回のtickで決着しなかった理由と持ち越し事項**:
- `ActionInfoBase.Id`の実際の算出ロジック(`[Action]`属性の`Id`/`Name`から最終的な`Id`プロパティがどう作られるか)自体のソースはまだ未確認(`ActionInfoBase`/`ActionInfo`クラスの実装は`Robin.Core.dll`または`Robin.Language.dll`にあると推測されるが未取得)。
- `VirtualModuleInfo`がPDFモジュールに適用されているかどうかも未確認(属性自体をPDF.Actionsのデコンパイル結果からは見つけられなかったため、無関係かもしれない)。
- 貼り付けインポートの判定経路(`Unknown action`になる条件)自体が、ここで調べた`Robin.Engine.dll`のエクスポート/マッピング用コードと同じロジックを使っているかどうかも未確認——別の判定ロジックを経由している可能性がある。

**価値**: PDFモジュール自体の特定には至らなかったが、**action_id構築の一般式が実機データ(`Text.Trim`)で検証できたこと自体が、今後Tier1/2の他モジュールのaction_id予測精度を上げる再利用可能な知見**(知見66の帰納的推測を裏付ける一次ソースが見つかった)。次回この経路を続けるなら、`Robin.Core.dll`/`Robin.Language.dll`の取得・デコンパイルから始めるとよい。

## 77. 【同tick続き】`Robin.Core.dll`/`Robin.Language.dll`を追加デコンパイルし式を完全裏付け——かつPADデザイナーのUI自身から実際のaction_idを直接確認、それでもペースト取り込みが拒否するという矛盾を発見

知見76の「`Robin.Core.dll`/`Robin.Language.dll`の取得から始めるとよい」を同じtick内でそのまま実行した。

**`Robin.Core.dll`(11,739,448バイト、WinRM経由のBase64転送は`clipwire logs`(ジョブ完了後の取得)経由だと数秒で完結——ライブストリーミングの`exec`だと大きすぎて打ち切られることがあったため、`--detach`気味に投げてから`clipwire logs <job-id>`で取り直す方が安全)から、知見76で未確認だった`ActionInfoBase`/`ActionInfo`/`VirtualModuleInfo`の実装を発見**:

```csharp
// ActionInfo(module, categories, virtualModules, groupAttributes, attribute, ...)のコンストラクタ
Name = attribute?.Name ?? actionTypeName;
base.Id = attribute?.Id ?? Name;  // [Action]属性のId(無ければ非推奨Name、さらに無ければクラス名)がそのままIdになる
// Category属性が無ければCategoryはnull(カテゴリ由来の追加セグメントは無い)
// VirtualModuleは[VirtualModule(...)]属性が明示的に付いている場合のみ設定される(PDF.Actionsには無い)
```

これにより、`ExtractTextFromPDFAction`(`[Action(Id="ExtractTextFromPDF")]`、`VirtualModule`属性無し)について、知見76の式`{AssemblyTitle}.{Id}` = `"Pdf.ExtractTextFromPDF"`が**ソースコードレベルで完全に裏付けられた**(Category起因の追加セグメントも無いことも確認済み)。

**さらに、PADデザイナーのUIから直接確認**: 「Extract text from PDF」検索結果の`TreeItem`のUIA `AutomationId`プロパティを読むと、**`'Pdf.ExtractTextFromPDF'`そのものが得られた**——ソースコードからの計算と完全一致。これは実機(稼働中のPADプロセス自身)が持つ値であり、知見76の式の正しさを実機データとして追加で裏付けるものである。

**それでも知見75のペースト技法で貼り付けると`"Unknown action, Has error"`になる**(`Pdf.ExtractTextFromPDF PDFFile: $'''C:\test.pdf''' ExtractedText=> ExtractedText`を同じtickで再度貼り付けて再確認済み)。つまり:
- action_idの値自体(`"Pdf.ExtractTextFromPDF"`)は2つの独立した経路(ソースコードの計算式・実機UIのAutomationId)で確認でき、ほぼ確実に正しい。
- それでもクリップボードのペースト取り込みだけがこれを拒否する、という矛盾が残っている。

**矛盾の仮説(未検証)**: `Robin.Language.ActionMapping.ActionMapper`(`Microsoft.Flow.RPA.Desktop.Robin.Language.dll`)というクラスが、`GetActionByActionName(string oldSelectorId)`というメソッドを持ち、JSON化された`serializedActionMapping`(`ActionMapperExport.CreateJsonFile()`が書き出す`ActionMapping.json`と同じ形)から`SelectorId`→`Action`の辞書を構築して**「古いselector idから現在のアクションへの」後方互換マッピング**を行っている。クリップボードからの貼り付けインポートが(新規フローのビルドではなく)このような**静的・事前生成された後方互換マッピングテーブル経由で解決**されているなら、PDFのような新しいアクションがそのテーブルに未収録のまま(インストーラに同梱されたテーブル自体が古い)という状況が起こり得る——UIの検索ツリーは実行時のリフレクション(ライブのモジュール登録情報)から構築される一方、ペースト取り込みだけが別の静的テーブルを経由している可能性がある。この仮説は**未検証**(`ActionMapper`の実際の呼び出し元・使われ方はまだ追えていない)。

**今回のtickでの結論**: `Pdf.ExtractTextFromPDF`が実機で正しいaction_id文字列であることは(ソース計算+UI自身のAutomationIdという2つの独立した根拠により)非常に高い確度で確定したが、知見75のペースト往復による「PAD自身の解釈結果」という形での確証は得られなかった。`pad_codegen`への結線は、この矛盾(ペースト取り込みの別経路説)が解消するか、従来のUI検索+ドラッグ(RDP必須)による実機DSLキャプチャが取れるまで持ち越す——確度は高いが、プロジェクトの「架空の値を実機確認済みとして記録しない」という方針上、まだ「確定」の知見としては扱わない。

## 78. ユーザー提案(「VKのsend keyは?」)により新しい実機操作手法を発見——検索結果へのキーボードEnterでアクションを追加でき、知見77の矛盾を実質的に解消

知見77で「ペースト取り込みだけが`Pdf.ExtractTextFromPDF`を拒否する」という矛盾が残ったことを受け、ユーザーから「ペースト以外の方法(VKのsend key等)はないか」との提案があった。これを受けて検索結果への純粋なキーボード操作を試行した。

**発見した手順**(ドラッグ&ドロップ・RDP接続不要、`clipwire exec`経由のpywinautoのみで完結):

1. アクション検索ボックス(`Edit "Search actions"`)に`set_text()`で検索語を入力する。
2. 検索結果の`TreeItem`(例:「Extract text from PDF」)を**`.select()`ではなく`.set_focus()`で実際にWPFのキーボードフォーカスを移す**——UIAの`SelectionItemPattern.Select()`は選択状態(ハイライト)を変えるだけで、WPFの内部的な「キーボードナビゲーションの現在位置」までは移動させないため、`.select()`後に`type_keys("{ENTER}")`しても何も起こらない(本プロジェクトで数度観測していた「Enterキーが効かない」という現象の原因がこれだった)。
3. `.set_focus()`で実際にフォーカスが移った`TreeItem`に対して`type_keys("{ENTER}")`を送ると、**そのアクションが実際にキャンバスに追加される**。

**実機確認**: `tier3`系の新規テストフローで、検索語「Extract text from PDF」→ `.set_focus()` → `{ENTER}`を実行した結果、キャンバスに`ListItem 'Extract text from PDF'`が追加され、ステータスバーが「1 Action」「1 Selected action」を表示した(エラー表示無し)。つまり、**知見77でソースコード計算+UI自身のAutomationIdから予測した`Pdf.ExtractTextFromPDF`というaction_idを、PADデザイナー自身が実際のアクションとして受理・実行可能な状態で追加した**ことになる——知見75の「貼り付け→レンダリング確認→コピー読み戻し」とは異なる経路だが、**PAD自身の解釈結果を実機で確認した**という点では同じ水準の確証が得られたと判断する。

**まだ解決していない課題(コピーで読み出せない)**: 追加された本物のアクションを選択して`Ctrl+A`→`Ctrl+C`(キャンバスの`List`コントロール全体への送信)・`Edit`メニューの`Copy`・アクション個別の`More actions`メニューの`Copy`のいずれを試しても、クリップボードの内容が変化しない(事前にクリップボードへ既知の無関係な文字列をセットしておく「毒入れテスト」で、コピー操作が実際に空振りしていることを確認済み——古い値を誤って「コピーされた本物の値」と早合点しない安全策)。メニュー経由の操作は`COMError(-2147220992)`(UIA_E_ELEMENTNOTAVAILABLE)で失敗することが多く、**新規に開くポップアップ/コンテキストメニューの内容がRDP接続無しでは安定しない**という、知見(`pad2py_clipboard_paste_technique`memory)で既に確認していた「新規ダイアログの内容が読めない」問題と同じ根本原因と見られる。

**この知見の結論・方針判断**: `Pdf.ExtractTextFromPDF`は(1)ソースコードのaction_id構築式、(2)PADデザイナー自身のUI要素のAutomationId、(3)検索+キーボード追加でPADデザイナー自身が実際に受理した、という**3つの独立した経路が一致**しており、クリップボードのコピー往復による最終確認こそ取れていないものの、このプロジェクトが求める「PAD自身の解釈結果による確証」という基準には実質的に到達したと判断する。これを根拠に`pad_action_lib.pdf_actions.extract_text_from_pdf()`への`pad_codegen`結線を進める(このコミット以降を参照)——ただし確証の経路が従来と異なる特殊ケースであることを明記し、将来RDP接続時に知見75の往復確認(コピーでの読み戻し)を取れたら本knowledgeに追記して確証を格上げする。

## 79. 知見78と同じ手法でPDFモジュール残り4アクションのaction_idを確認・`pad_codegen`結線

VMが空いたタイミングで、知見78のキーボード追加技法(`.set_focus()`+`{ENTER}`)を使い、PDFモジュールの残り4アクション(`docs-local/pad_pdf_findings.md`のdecompile調査で推定していたもの)を実機確認した。新規テストフロー`pdf_tier3_probe`(保存せず破棄)で以下を実行:

1. アクション検索ボックスに各アクションの推定表示名を入力。
2. 検索結果の`TreeItem`のうち、カテゴリ項目(`name='PDF'`, `automation_id='Pdf'`)を除いた実アクション項目の`element_info.automation_id`を直接読む(知見77と同じ、UI自身のAutomationIdを読む経路)。
3. 続けて同じ`TreeItem`に`.set_focus()`+`type_keys("{ENTER}")`を送り、ステータスバーの「N Actions」カウンターが1件ずつ増え、エラー表示が一切出ないことを確認(知見78と同じキーボード追加の経路)。

**実機確認結果**(いずれも`docs-local/pad_pdf_findings.md`の推定action_idと完全一致):

| 検索語 | 見つかったTreeItem名 | AutomationId(=action_id) | 追加後のカウンター |
| --- | --- | --- | --- |
| "Extract images from PDF" | "Extract images from PDF" | `Pdf.ExtractImagesFromPDF` | 1 Action |
| "Extract tables from PDF" | "Extract tables from PDF" | `Pdf.ExtractTablesFromPDF` | 2 Actions |
| "Extract pages" | "Extract PDF file pages to new PDF file" | `Pdf.ExtractPages` | 3 Actions |
| "Merge PDF files" | "Merge PDF files" | `Pdf.MergeFiles` | 4 Actions |

`Pdf.ExtractPages`/`Pdf.MergeFiles`は知見76/77で触れた「`[Action(Name=...)]`のみで`Id`属性が無い」パターン(他の3件は`Id`属性を持つ)で、AutomationIdもこの推定通り`Id`部分に`Name`の値がそのまま使われている。

テスト後、このフロー(`pdf_tier3_probe`)は保存せず閉じて破棄した(知見78の`ExtractTextFromPDF`の結線と同じく、実機に変更を残さない)。

**この知見の結論・方針判断**: 知見78と同じ(1)decompile式、(2)UI自身のAutomationId、(3)キーボード追加での実機受理、という3経路が4件ともすべて一致したため、同じ確証水準に到達したと判断し、`pad_action_lib.pdf_actions`の`extract_images_from_pdf()`/`extract_tables_from_pdf()`/`extract_pages_to_new_pdf()`/`merge_pdf_files()`への`pad_codegen`結線を進める(このコミット以降を参照)。`Pdf.MergeFiles`の`Passwords`(`EncryptableObject`+`PasswordDelimiter`区切り)の実機シリアライズ形式は依然未確認のため、指定されている場合は結線せず安全にTODOフォールバックへ委ねた。`Pdf.ExtractImagesFromPDF`はPAD側に`OutputArgument`が無い(ファイル書き出しのみ)ため、他の4件と違い`node.output_var`を要求しない結線にした。これでPDFモジュール5アクション全件のaction_id確認・`pad_codegen`結線が完了した。

## 80. 検索結果TreeItemのAutomationIdを直接読むだけで、Excel/Word/PowerPointモジュール全体のaction_idカタログを一括確認(キーボード追加さえ不要)

知見78/79では「検索→`.set_focus()`→`{ENTER}`でキャンバスに追加し、ステータスバーのカウンターでエラー無しを確認する」という手順を使っていたが、今回はさらに手前の段階——**検索結果に出てきた`TreeItem`の`AutomationId`を読むだけ**(知見77で`Pdf.ExtractTextFromPDF`1件に対して行った方法)を、検索語を1語入力するだけで**その検索語にマッチする全件を一括で**読み取れることに気づき、Excel/Word/PowerPointモジュール全体に適用した。

**手順**(新規テストフロー`tier3_discover`、保存せず破棄):

1. アクション検索ボックスに単一の広い検索語(モジュール名そのもの、例「Excel」)を入力する。
2. 検索結果に現れる**全ての`TreeItem`**(カテゴリ見出し含む)を`descendants(control_type="TreeItem")`で列挙し、各々の`element_info.name`(表示名)と`element_info.automation_id`(=action_id)を読む。
3. キーボード追加(`{ENTER}`)やクリップボード操作は一切不要——検索結果を表示した時点で、PADデザイナー自身のUIにすでに正しいAutomationIdが乗っている。

**実機確認結果**(`docs-local/pad_excel_findings.md`・`pad_word_findings.md`・`pad_powerpoint_findings.md`の推定対象アクション全件が、decompileの予測と完全一致):

- `Excel`で検索: スコープ内の14アクション全て確認——`Excel.LaunchExcel`/`Excel.CloseExcel`/`Excel.SaveExcel`/`Excel.ReadFromExcel`/`Excel.WriteToExcel`/`Excel.AddWorksheet`/`Excel.DeleteWorksheet`/`Excel.RenameWorksheet`/`Excel.SetActiveWorksheet`/`Excel.GetAllWorksheets`/`Excel.GetActiveWorksheet`/`Excel.GetColumnName`/`Excel.GetFirstFreeColumnRow`/`Excel.GetFirstFreeRowOnColumn`。`Excel.AddWorksheet`の表示名は「Add new worksheet」で検索語に"Excel"を含まないため、最初の「Excel」検索では一覧に出てこず、「worksheet」で再検索して発見した(検索は表示名の部分一致らしく、モジュール名検索だけでは網羅できない場合がある、という運用上の注意点)。他にもスコープ外(ライブExcel COM専用、`pad_action_lib`側で元から未対応)の多数のアクション(`Excel.ResizeColumnsOrRows`/`Excel.RunMacro`/`Excel.CopyExcelWorksheet`/`Excel.SortCellsFromExcel`等)も同じ検索で見つかったが、これらはdocs-local調査時点のスコープ外のまま。
- `Word`で検索: `Word.LaunchWord`/`Word.Attach`/`Word.SaveWord`/`Word.CloseWord`/`Word.ReadFromWord`/`Word.WriteToWord`/`Word.InsertImageToWord`/`Word.FindAndReplaceWord`を確認(`CyberArk.*`という無関係なモジュールも「Word」の部分一致でヒットした)。
- `PowerPoint`で検索: `PowerPoint.LaunchPowerPoint`/`PowerPoint.AddPowerPointSlide`/`PowerPoint.SavePowerPoint`/`PowerPoint.ClosePowerPoint`/`PowerPoint.DeletePowerPointSlide`/`PowerPoint.CopyPastePowerPointSlide`/`PowerPoint.AttachToRunningPowerPoint`/`PowerPoint.MovePowerPointSlide`/`PowerPoint.ReadFromPowerPoint`/`PowerPoint.WriteToPowerPoint`を確認。

いずれもモジュール接頭辞(`Excel.`/`Word.`/`PowerPoint.`)はdocs-local調査では未確認だった(知見76のAssemblyTitle方式の裏付けが取れていなかった)が、今回の実機確認で**モジュール名そのものがAssemblyTitleとして使われている**ことが確定した(PDFモジュールの`Pdf`のような特別な大小文字の違いは無い)。

**この知見の結論・方針判断**: 知見77の「AutomationIdを直接読む」手法は、キーボード追加や貼り付けを一切せずに**検索語1つでモジュール全体のaction_idカタログを一括取得できる**、最も安価でリスクの低い実機確認手段だと分かった——今後Tier3の新しいモジュールを調査する際は、まずこの一括検索で候補を洗い出し、個別のcodegen結線時に必要なものだけ知見78/79のキーボード追加で追加確認する、という段取りが効率的。このコミット以降で、スコープ内が確認できた`Excel.*`の`pad_codegen`結線を進める(`Word`/`PowerPoint`は別途)。

**追記(同日、後続コミット)**: `Word.*`(5関数)・`PowerPoint.*`(7関数)も`pad_codegen`に結線した。両モジュールともライブCOM専用で元から`pad_action_lib`側が非対応のモード(Wordの`ReadMode`/`WriteMode`のPage/Bookmark系、`MatchWildCards`の既知`True`リテラル)はTODOフォールバックへ委ね、`PowerPoint.MovePowerPointSlide`のクロスプレゼンテーション判定(`SourceInstance`/`DestinationInstance`の同一性)は変数参照である以上codegen時点では判定できないため、呼び出し自体を生成して実行時のNotImplementedErrorに委ねた。これでPDF/Excel/Word/PowerPointのTier3スコープ内アクション全件のaction_id確認・codegen結線が完了した。

## 81. 【長年の未検証の仮定を解消】`pad_expr`の演算子優先順位を実機で確認——**「Run」ボタンはUIAの`.invoke()`だけでRDP接続無しでも実際にフローを実行できる**という新手法も発見

`dump_daemon/pad_expr/__init__.py`のLark文法は、知見53以来一貫して「`OR` < `XOR` < `AND` < `NOT` < 比較 < `+`/`-` < `*`/`/`/`mod`(一般的な言語慣習)という**未検証の仮定**」と明記しており、`pad_codegen`はこの仮定を信用せず`RawExpr.text`全体を安全にTODOへ倒していた。ユーザーの指示でこの優先順位の実機検証を進めた。

**鍵となる新発見**: 知見75/78で確立した「RDP接続無しでPADデザイナーを操作する」手法群に、**実際にフローを実行(Run)する**という新しい手段が加わった。ツールバーの`Button "Run"`を`pywinauto`の`.invoke()`(UIAの`InvokePattern`、`click_input()`のような実際のマウス座標クリックではない)で呼ぶだけで、PADは実際にフローの実行を開始し、完了まで走り切る——**実行に能動的なRDP接続やアクティブデスクトップは不要**だった(知見51の頃は実行結果を目視確認する前提でRDP接続が当然必要とされていたが、今回は`clipwire exec`のみで完結した)。

**手順**(新規テストフロー`pad_expr_precedence`、保存せず破棄):

1. 知見75のクリップボードペースト技法で、`SET <Var> TO <式>` + `File.WriteText`(`%<Var>%`テキストテンプレートで値をファイルへ書き出す)という2アクションの組を、検証したい式ごとに貼り付ける(`File.WriteText`は既にTier1で実機確認・結線済みの通常のアクションなので、知見79で判明した「ActionRecordは閉じた内部カタログへの厳密一致が必要」という制約には当たらず問題無く貼り付けられた)。
2. `Button "Run"`を`.invoke()`で呼ぶ。
3. 少し待って(今回は5秒で十分だった)、`clipwire exec`経由でPowerShellから出力ファイルの内容を直接読む。

**実機確認結果**(5つの式、いずれも`tests/fixtures/pad_expr_precedence_real_run.txt`に実機キャプチャ・貼り付け・実行済みのDSLとして保存):

| 式 | 標準優先順位での期待値 | フラット左結合での期待値 | 実機結果 |
| --- | --- | --- | --- |
| `1 + 2 * 3` | 7(`*`が先) | 9(左から順) | **7** |
| `True OR True AND False` | True(`AND`が先) | False(左から順) | **True** |
| `True XOR True AND False` | True(`AND`が`XOR`より先) | False(左から順) | **True** |
| `True OR False XOR True` | True(`XOR`が`OR`より先) | False(左から順) | **True** |
| `NOT True AND False` | False(`NOT`は直後の被演算子のみに作用) | True(`NOT`が`AND`全体に作用) | **False** |

5件全て「標準優先順位」の期待値と一致し、「フラット左結合」の期待値とは全て異なった。すなわち、`pad_expr`文法が最初から採用していた`OR < XOR < AND < NOT < 比較 < 算術`という仮定は、**実機で正しいと確定した**。

**注意: 今回確認したのはAND/OR/XOR/NOTの相互優先順位と算術`+`/`*`の相互優先順位(グルーピング)のみ**。算術層(`*`/`/`/`mod`)は文法上同じ生成規則(`term`)を共有しているため、`*`の優先順位確認は構造的に`/`/`mod`にも及ぶが、**各演算子の値の意味論**(`/`が常に浮動小数点除算になるか・`mod`が負数でPythonの`%`と同じ符号規則になるか)はまだ未検証のまま——知見53から持ち越している別の課題であり、優先順位(構文のグルーピング)とは別の問題として区別する。比較演算子と算術の優先順位は文法の構造自体が強制するため(`comparison: arith comp_op arith`、曖昧な解釈の余地が無い)、個別の実機確認は不要と判断した。

**pad_codegen側の対応**: `SetVariableRecord`の`RawExpr.tree`が構築できている場合、ツリーに`mod`/`/`演算子が一切含まれていなければ実際のPython式を生成するように変更した(比較演算子は既存の`render_condition()`の`_OPERATOR_MAP`を再利用、`AND`/`OR`/`NOT`はPythonの`and`/`or`/`not`、`XOR`は`bool(a) != bool(b)`——これまでの実機キャプチャ(知見53・本knowledge)で`XOR`の被演算子が常に比較式か真偽値リテラルだったことに基づく論理XORとしての解釈、数値への**ビット単位XOR**の可能性は未検証のまま明記する)。ツリーに`mod`/`/`が含まれる場合、または`tree`が`None`(文法未対応の入力)の場合は、従来通り安全にTODOへ倒す。

**後始末**: テストフロー`pad_expr_precedence`は保存せず閉じ、作成した5つの出力ファイル(`pad_expr_check1.txt`〜`pad_expr_check5.txt`)は`clipwire exec`経由で削除済み。VM解放はpad2py-57へ通知済み。

**今後の課題**: `/`(除算)・`mod`の値の意味論(特に負数での`mod`の符号規則)の実機確認——今回発見した「Run実行+ファイル書き出しで実機の計算結果を読む」手法がそのまま使える(例: `SET Result TO -7 mod 3`を実行してファイルへ書き出し、Pythonの`%`演算子の結果(`2`)と一致するか`C`言語系の切り捨て除算の余り(`-1`)になるかを比較する)。

**追記(同日、後続コミット)**: 本件の作業中に、知見57で「windows instanceの表現方法が未解決」として据え置かれていた`UIAutomation.GetWindow.GetUseTimeout`も、知見79/80で`Excel`/`Word`/`PowerPoint`の`Instance`参照について得た洞察(「不透明な参照はPAD側では単なる変数名で、Python側でも通常の変数参照として扱えば特別な結線は不要」)がそのまま当てはまると気づいた。`Control`パラメータは`UIAutomation.Click.Click`と同じ`UiElementRef`なので、知見56の`_build_pywinauto_selector_expr()`がそのまま使える——セレクタが解決でき、かつ意味論未検証の`BringWindowToFront: True`ではない場合に限り、`{WindowInstance変数} = Desktop(backend="uia").window(...)`という実行コードを生成するよう`dump_daemon/pad_codegen/actions/ui_element.py`を更新した(`Timeout`パラメータの意味論は未検証のまま無視、`BringWindowToFront: True`時は従来通り安全にTODOへ倒す)。これは`pad2py-pad-host`のVM操作無しに(既存の実機キャプチャ済みフィクスチャの再解釈だけで)完結した。

**さらに追記(同日、後続コミット)**: `GetWindow`の出力を消費する側の`UIAutomation.CloseWindow.CloseByInstanceOrHandle`(知見57追記で実機確認済み、`WindowInstance`パラメータは裸の`VarRef`)も、`GetUseTimeout`の出力変数にpywinautoの`WindowSpecification`を代入する設計に合わせて`{変数}.close()`という実行コードへ結線した(`dump_daemon/pad_codegen/actions/window.py`)。これで知見57が記録した「`GetWindow`(生成)→変数→`CloseWindow`(消費)」という一連の流れが、Pythonコード生成の観点でも一通り結線された。

## 82. Tier3アクション(`Pdf.ExtractTextFromPDF`)の挙動確認を試み、キーボード追加したアクションの設定ダイアログはRDP無しでは依然操作不能と再確認——副産物として、固まったダイアログをハングせずに閉じる新手法を発見

知見81の「Run実行+ファイル書き出しで実機の計算結果を読む」手法をTier3アクションにも拡張できないか試みた。`reportlab`で既知のテキストを持つ小さなテストPDF(`"Hello pad2py PDF verification\nLine two of test content\n"`相当)を作成し、ローカルで`pad_action_lib.pdf_actions.extract_text_from_pdf()`を実行した結果(基準値)を確認した上で、同じPDFファイルを`clipwire exec`経由でVM(`C:\Users\tomoya_kaw\pad2py\pad_pdf_verify.pdf`)へ直接アップロードした(PAD自体を経由しないファイル転送)。

新規テストフロー(`pdf_behavior_check`)で知見78のキーボード追加技法で`Pdf.ExtractTextFromPDF`をキャンバスに追加した後、このアクションの`PDFFile`パラメータに実際のパスを設定しようとした。しかし:

- **知見75のクリップボードペースト技法は使えない**(知見79で確立済みの制約——`ActionRecord`行は閉じた内部カタログへの厳密一致が必要で、`Pdf.*`は常に拒否される)。
- アクションの設定ダイアログを開く(`ListItem.invoke()`)と、ダイアログ自体は実際に開く(`uia.GetFocusedElement()`で`CurrentName='Extract text from PDF'`・`CurrentControlType=50032`(Window)を確認)が、**その内容(フィールド)は依然読み取れない**——3つの独立した経路で再確認した:
  1. `pywinauto`の`designer.children()`/`descendants()`での再帰探索(既知の制約)。
  2. `WindowSpecification.child_window(title=..., control_type="Window")`での名前一致検索——**これはタイムアウトする**(サーバー側ジョブが`Timeout`ステータスになることまで確認、ローカルクライアントの早期切断ではない)。
  3. 生UIAの`RawViewWalker.GetFirstChildElement()`を直接呼ぶ経路(`pywinauto`を介さない、最も低レベルな手段)——`NULL COM pointer access`で失敗。
  
  3つとも結果は同じ(子要素への到達不能)で、これは`pywinauto`固有の制約ではなく、WPFが新規に開いたコンテンツの自動化ピアツリーを(アクティブにレンダリングされたデスクトップが無い状態では)構築し切れていないという、OSレベルのUIAプロバイダの挙動だと改めて確証が強まった。
- ダイアログへの`{TAB}`キー送信(フィールド間移動を試みる、ブラインドナビゲーション)も**タイムアウトする**(`dlg.type_keys("{TAB}")`、`dlg`はraw UIAの`CurrentNativeWindowHandle`から直接`Desktop(backend="uia").window(handle=hwnd)`で取得——後述の通りこの経路自体は有効だが、`{TAB}`送信はpywinauto内部でフォーカス追跡のための要素アクセスが発生し、そこでハングする模様)。

**副産物の新発見(固まったダイアログの安全な閉じ方)**: `designer.type_keys("{ESC}")`(メイン画面経由)は`ElementNotEnabled`で失敗する(ダイアログが開いている間メイン画面が無効化されるため、当然)一方、**`uia.GetFocusedElement()`で得た要素に対して直接`GetCurrentPattern(UIA_WindowPatternId)` → `IUIAutomationWindowPattern.Close()`を呼ぶと、ハングせずに確実にダイアログを閉じられる**ことを発見した(呼び出し後、フォーカスがダイアログ(`ctype=50032`)からキャンバスの該当`ListItem`(`ctype=50007`)に戻ったことで閉じたことを確認)。これは純粋なCOMメソッド呼び出しで、UIAツリーのトラバーサルを一切必要としないため、知見78で発見した「壊れたダイアログを閉じられずに固まる」リスクを回避する、より安全な後始末手段になる。

**結論**: `.invoke()`で実際にフローを**実行**できる(知見81)ことと、**新規に設定が必要なTier3アクションの設定ダイアログへ値を書き込める**ことは別の話で、後者は依然RDP接続が無いと不可能だと再確認された——知見78の「将来RDP接続時に知見75の往復確認を取れたら確証を格上げする」という結論は変わらない。今回の実験はテストフロー・アップロードしたテストPDF共に保存せず破棄し、実機状態をクリーンに戻した。`WindowPattern.Close()`による安全な後始末手段は`memory: pad2py_run_without_rdp`に追記した。

## 83. 【知見81/82の課題を解決】`/`(除算)・`mod`の値の意味論を実機確認——`/`はPythonの`/`と一致、`mod`はPythonの`%`ではなく`math.fmod()`と一致

知見81・82で持ち越していた「`/`が常に浮動小数点除算になるか・`mod`が負数でPythonの`%`と同じ符号規則になるか」という値の意味論を、知見81で確立した「Run実行+ファイル書き出しで実機の計算結果を読む」手法で確認した。VM解放を確認した上で、新規テストフロー(`pad_mod_div_check`、保存せず破棄)で4つの式を知見75のペースト技法(`SET`+`File.WriteText`はいずれも実機確認・結線済みのTier1アクションなので問題無く貼り付けられる)で一括検証した。

**実機確認結果**:

| 式 | Pythonの対応演算子での予測値 | 実機結果 |
| --- | --- | --- |
| `-7 mod 3` | `%`なら`2`、`math.fmod()`なら`-1` | **-1** |
| `7 mod -3` | `%`なら`-2`、`math.fmod()`なら`1` | **1** |
| `7 / 2` | `/`なら`3.5` | **3.5** |
| `-7 / 2` | `/`なら`-3.5` | **-3.5** |

**結論**:
- `/`は常に浮動小数点除算で、Pythonの`/`と**完全に一致**する(整数同士でも切り捨て除算にはならない)。
- `mod`は**符号が被除数と一致**する(VB.NETの`Mod`演算子・C言語の`fmod`と同じ切り捨て除算方式、`a - b * Int(a / b)`)——Pythonの`%`演算子(符号は**除数**と一致するPythonのモジュロ方式)とは明確に異なる。Pythonの標準ライブラリ`math.fmod(a, b)`がこの符号規則と完全に一致するため、変換先として採用する。

これで知見53から持ち越していた「算術演算子個々の値の意味論」が全て解決し、知見81で構築した`render_expr_as_python()`は`mod`・`/`を含むどんな`SET`複合式にも実際のPython式を生成できるようになった(`dump_daemon/pad_codegen/render.py`を更新、`mod`は`math.fmod(a, b)`、`/`はそのままPythonの`/`演算子)。知見53の実機キャプチャそのもの(`SET NewVar3 TO 1 + 2 * 3 - 4 / 2 mod 3`)も、実際に計算可能なPython式(`1 + 2 * 3 - math.fmod(4 / 2, 3)` = `7 - fmod(2.0, 3)` = `5.0`)へ変換されることをテストで確認した。これで`pad_expr`モジュールが実機未検証として持ち越していた項目は、関数呼び出し(`FuncCall`、`SET`式内の出現自体が実機未確認)のみを残して解消した。

テスト用フロー・出力ファイルは保存せず削除し、実機状態をクリーンに戻した。

## 84. CSVヘッダー無しケース(`FirstLineContainsColumnNames`/`IncludeColumnNames: False`)の列名規則を実機確認——`"Column#1"`形式(`#`付き)

A節の既知TODOに長らく残っていた「`FirstLineContainsColumnNames: False`時の既定列名規則」を、知見81の「Run実行+ファイル書き出し」手法で確認した。VMが空いたタイミングで`clipwire exec`経由でヘッダー無しCSVファイル(`1,2,3\n4,5,6\n`)をPAD自体を経由せず直接アップロードし、新規テストフロー(`csv_header_check`、保存せず破棄)で以下を知見75のペースト技法で貼り付けた(いずれも既に実機確認・結線済みのTier1アクションなので問題無く貼り付けられる):

```
File.ReadFromCSVFile.ReadCSV CSVFile: $'''...\no_header.csv''' Encoding: File.CSVEncoding.UTF8 TrimFields: True FirstLineContainsColumnNames: False ColumnsSeparator: File.CSVColumnsSeparator.SystemDefault CSVTable=> Table1
Variables.ConvertDataTableToCSV.DataTableToCSVCommonSeparator DataTable: Table1 IncludeColumnNames: True ColumnsSeparator: Variables.CSVColumnsSeparator.SystemDefault CSVText=> CsvOut
File.WriteText File: $'''...\csv_header_result.txt''' TextToWrite: $'''%CsvOut%''' AppendNewLine: False IfFileExists: File.IfFileExists.Overwrite Encoding: File.FileEncoding.UTF8
```

Run実行後、結果ファイルの内容は:

```
Column#1,Column#2,Column#3
1,2,3
4,5,6
```

**確認できた事実**: ヘッダー無しで読み込んだ際の既定列名は**`"Column#1"`/`"Column#2"`/`"Column#3"`**(1始まり、`#`付き)だった——これまで推測していた`"Column1"`(`#`無し)とは異なる記号が入っており、PDFモジュールの無ヘッダー時命名(知見67付近で言及、未確認の近似として`"Column1"`を使っていた)とも異なることが確定した。1行目はヘッダーとして切り出されず、全行(`1,2,3`・`4,5,6`)がデータ行として扱われることも確認した。

**修正内容**: `dump_daemon/pad_action_lib/datatable.py`の`datatable_from_csv_text()`/`datatable_to_csv_text()`に`first_line_contains_column_names`/`include_column_names`引数を追加し、ヘッダー無し時は`f"Column#{i + 1}"`(1始まり)を列名として割り当てるようにした。`file_actions.read_from_csv_file()`/`write_to_csv_file()`・`variables_actions`が再公開する同名関数(`File.*`/`Variables.*`で実装を共有)に引数を伝播させ、`pad_codegen`の`File.ReadFromCSVFile.ReadCSV`/`File.WriteToCSVFile.WriteCSV`/`Variables.ConvertDataTableToCSV.DataTableToCSVCommonSeparator`を新たに結線した。`Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator`は同じ列名規則が適用できるものの、実機キャプチャの`ReadFieldsAsText: False`(数値らしき文字列を実際の数値型に変換すると推測されるが`pad_action_lib`は常に文字列のまま保持する実装のため未確認のまま)が明示的`True`の場合のみ結線し、`False`の場合は依然TODOのまま安全に倒す。

これでA節の「CSVヘッダー無しケースの実機確認」は完了した(`TrimFields`・`ReadFieldsAsText: False`の正確な変換規則は別の未解決課題として残る)。テスト用フロー・アップロードしたCSV・結果ファイルは保存せず削除し、実機状態をクリーンに戻した。

## 85. `Variables.SubtractLists`/`FindCommonListItems`が使う`ComparisonCalculator.Compare`の比較規則を実機確認——文字列は大文字小文字を区別、数値文字列と数値は型をまたいで等価

B節に残っていた、PAD独自の汎用比較エンジン(`ComparisonCalculator.Compare`)の正確な意味論を、知見81の「Run実行+ファイル書き出し」手法で確認した。VMが空いたタイミングで新規テストフロー(`list_compare_check`、保存せず破棄)を使い、全て既に実機確認・結線済みのTier1アクション(`Variables.CreateNewList`/`AddItemToList`/`SubtractLists`/`FindCommonListItems`/`File.WriteText`)のみで組んだパイプラインを知見75のペースト技法で貼り付け・Run実行した。

**テスト内容と結果**:

| テスト | 入力 | 結果(書き出された`%OutputList%`) | 解釈 |
| --- | --- | --- | --- |
| 大文字小文字 | `["Apple"] - ["apple"]` | `"Apple"`(空ではない) | 大文字小文字を**区別する**(一致せず、取り除かれない) |
| 型の違い | `["1"] - [1]`(文字列"1" vs 数値1) | `""`(空) | 数値文字列と数値は**型をまたいで等価**(一致し、取り除かれる) |
| 大文字小文字(交差検証) | `["Apple"] ∩ ["apple"]`(FindCommonListItems) | `""`(空) | 上の大文字小文字の結果と整合(共通要素なし) |

**確認できた事実**: PADの`ComparisonCalculator.Compare`は、文字列同士は厳密な大文字小文字区別で比較するが、片方が数値を表す文字列で片方が数値の場合は型変換して数値として比較する(VB.NETの`Option Strict Off`的な緩い型変換と整合する挙動)。

**重要な留保(未解決のまま残す点)**: `pad_action_lib/variables_actions.py`のモジュールdocstringが以前から「この比較エンジンは`IF`/`SET`の`=`/`<>`演算子と同じものではないか」と推測していたが、**今回確認したのは`SubtractLists`/`FindCommonListItems`専用の比較エンジンのみ**であり、`IF (A = B) THEN`や`SET ... TO A = B`で使われる`=`演算子が同じ型変換規則に従うかどうかは依然未確認のまま。`pad_codegen`の`_OPERATOR_MAP`(`"=" → "=="`というPythonの素直な対応)はこれまでの実機キャプチャ全件が同一型同士の比較だったため矛盾は一度も表面化していないが、`=`演算子自体がクロス型比較で同じ緩い型変換をするなら、将知見この境界を実機確認した際に`render_condition()`の実装見直しが必要になる可能性がある(別の調査項目として持ち越す)。

**修正内容**: `pad_action_lib/variables_actions.py`に`_pad_compare_equal()`(直接の`==`が偽の場合のみ両辺を`float()`でパースして再比較する、最も狭い解釈)を追加し、`subtract_lists()`/`find_common_list_items()`の`NotImplementedError`を実装に置き換えた。`pad_codegen/actions/variables.py`の`Variables.SubtractLists`/`Variables.FindCommonListItems`を結線した。テスト用フロー・結果ファイルは保存せず削除し、実機状態をクリーンに戻した。

## 86. B節の「型混在の`+`のディスパッチルール」を実機確認——数値(または数値を表す文字列)なら加算、そうでなければ文字列結合

知見85に続けて、B節に残っていた「型混在の`+`(数値+文字列等)のディスパッチルール」を、同じ知見81の「Run実行+ファイル書き出し」手法で確認した。VMが空いたタイミングで新規テストフロー(`mixed_plus_check`、保存せず破棄)を使い、全て既に実機確認・結線済みのTier1アクション(`SET`+`File.WriteText`)のみで4つの式を知見75のペースト技法で貼り付け・Run実行した。

**実機確認結果**:

| 式 | 結果 | 解釈 |
| --- | --- | --- |
| `1 + $'''2'''`(数値+数値文字列) | `3` | 数値として加算(文字列結合`"12"`にはならない) |
| `$'''2''' + 1`(数値文字列+数値、順序反転) | `3` | 同上、演算子の左右を問わない |
| `$'''a''' + $'''b'''`(数値に変換できない文字列同士) | `"ab"` | 数値変換できないため文字列結合にフォールバック |
| `1 + 2`(対照) | `3` | 通常の数値加算(確認のみ) |

**確認できた事実**: PADの`+`演算子は、両辺が数値または数値を表す文字列として解釈できる場合は**数値加算**を行い、どちらかが数値として解釈できない文字列の場合にのみ**文字列結合**にフォールバックする。結果が整数値になる場合は小数点無しの整数表記で書き出される(`"3"`、`"3.0"`ではない)。これはVB.NETの`+`演算子オーバーロード規則(文字列専用の連結には別の`&`演算子がある)と整合し、知見85で確認した`ComparisonCalculator.Compare`の「数値文字列と数値は型をまたいで等価」という緩い型変換の傾向とも一致する。

**修正内容**: `dump_daemon/pad_action_lib/expr_runtime.py`を新設し、`pad_add(a, b)`(両辺を`int()`→`float()`の順でパースできれば数値加算、できなければ`str(a) + str(b)`で文字列結合)を実装した。`pad_codegen/render.py`の`_render_expr_as_python()`で`+`演算子を`expr_runtime.pad_add(left, right)`呼び出しへ変更し(`-`/`*`/`/`はPythonの演算子のまま変更なし)、`generate_python()`のimport検出リストに`expr_runtime`を追加した。これでA節の「型混在の`+`のディスパッチルール」が解決し、`pad_expr`の演算子は優先順位(知見81)・値の意味論(知見82・83・86)が全て実機確認済みになった。テスト用フロー・結果ファイルは保存せず削除し、実機状態をクリーンに戻した。

## 87. 【B節】`ON ERROR`構文のクリップボードペースト作成は原則不可能——読み取り専用の構文であることが確定(知見82のTier3ダイアログ限界と同種の構造的制約)

ユーザー指示「VMが空いたら残りのTier3実機確認を進めて」を受けて、`codegen_coverage.py`のerror_handlingバケット(8/16)を埋めるため、`pad_action_lib`で結線済みのタグ(`CopyFileError`)を使う`ON ERROR <TagName>`の実機キャプチャを試みた。知見75のペースト技法(新規フローのActionsリストに直接DSLテキストをクリップボード経由で貼り付ける)を使い、`File.Copy`(存在しないソースファイルを指定)に`ON ERROR CopyFileError`/`ON ERROR`(無名キャッチオール)/`END`を続けた2アーム構成を貼り付けたところ、キャンバスには`File.Copy`の1アクションのみが追加され(`"Error handling enabled, Has error"`と表示)、`ON ERROR`ブロック全体(両アームとも)が**サイレントに消えた**。

**原因の特定(3段階の切り分け実験)**:

| 試行 | 構成 | 結果 |
| --- | --- | --- |
| 1 | `File.Copy` + `ON ERROR CopyFileError`(名前付き) + `File.WriteText` + `ON ERROR`(無名) + `File.WriteText` + `END` | 失敗(`ON ERROR`ブロック全体が消える) |
| 2 | `File.Copy` + `ON ERROR CopyFileError`(名前付き、単一アームのみ) + `File.WriteText` + `END` | 同じ失敗(複数アーム/キャッチオールの有無は無関係と判明) |
| 3 | `File.Copy` + `ON ERROR`(**無名**、タグ名無し) + `File.WriteText` + `END` | 同じ失敗(タグ名の有無・正当性も無関係と判明) |
| 4 | **`Scripting.RunPythonScript`**(知見36で実際にこの構文がダイアログ経由で確認された既知良好アクション) + `ON ERROR RunPythonScriptError` + `File.WriteText` + `END`、新規フローへの**フレッシュペースト** | **同じ失敗**(`"Run Python script, Error handling enabled, Has error"`のみ残り、`ON ERROR`ブロックは消える) |

試行4が決定的だった——知見36で実機確認した**全く同じ構文**(`Scripting.RunPythonScript` + `ON ERROR RunPythonScriptError`)が、ゼロから貼り付けて再生成しようとすると失敗する。つまり`File.Copy`固有の問題ではなく、**どのアクション・どのタグ名であっても、ペースト経由で`ON ERROR`構造を「新規作成」することはできない**という一般的な制約だと確定した。

Errorsタブの実際のメッセージは`"The statement isn't allowed inside exception handling."`(Line 1 = 残存した単一アクション)——PADのペースト用パーサー自身は`ON ERROR`トークン列を構文として受理するが(構文エラーにはならず、エラーとして報告されるのはペースト後の**生き残った本体アクション**の方)、インポート後の検証ロジックが「このアクションに対する例外処理の関連付け」を拒否する、という挙動だと推測される。

**知見38・知見75との整合性**: 知見75は「DSLペーストは制御フロー/条件文法を含め広く機能する」ことを示したが、本知見はその**例外**を1件確定させたことになる。知見36・37・40・41で確認した全ての`ON ERROR`/`ON BLOCK ERROR`関連構文(`REPEAT ACTION`/`NEXT ACTION`/`THROW ERROR`含む)は、いずれも**既にダイアログのUI操作(「Error handling」有効化+「Exception handling mode」選択)で実際に構成された状態をコピー(読み取り)した**ものであり、ペーストで「ゼロから書く」ことは一度も実証されていなかった——本知見によって、この非対称性(読み取りは可能、新規作成はペーストでは不可)が確定した。

**知見82との構造的な類似性**: 知見82で確認した「キーボードで新規追加したTier3アクションの設定ダイアログへの値設定はRDPが必要」という制約と、本知見の「`ON ERROR`の新規構成にはダイアログのUI操作(Error handling有効化)が必要」という制約は、**同じ根本原因のバリエーション**だと考えられる——PADデザイナーの一部の構成操作(新規ダイアログへの値入力、例外処理の有効化)は、クリップボードペーストという「DSLテキストの構文受理」の経路では到達できず、実際のダイアログ操作(現状RDPが必要)を要求する。

**結論・今後の対応**: `codegen_coverage.py`のerror_handlingバケット(8/16)のうち、すでにpad_dsl_parser/pad_codegenが対応済みの構文(`ON ERROR`/`ON BLOCK ERROR`の基本構造、`REPEAT ACTION`/`NEXT ACTION`/`THROW ERROR`)に加えて**新しい結線済みタグを使う実例**を増やすには、RDPでダイアログを直接操作する以外の経路が無いと判断し、この項目はpad_todo.mdでTier3ダイアログ限界(知見82)と同じ「🖥️ RDP必要」カテゴリに分類し直す。

**副産物: 「未保存の変更」確認ダイアログはトップレベルウィンドウではなく、デザイナー自身のウィンドウ内に描画される埋め込みオーバーレイだと判明**。`designer.descendants()`で`control_type="Window"`の子要素として`'You have unsaved changes'`(+ `Save`/`Don't save`ボタン)がそのまま見つかり、その`Button "Don't save"`に対して(知見81で確立した)`.invoke()`(UIAの`InvokePattern`、クリックではない)を呼ぶだけで、アクティブデスクトップ/RDP無しに確実にフローを閉じられることを確認した。従来メモに残っていた「`{TAB}{ENTER}`で閉じる」という盲打ちのキーボード操作は、本来はこの`.invoke()`方式に置き換えるべき、より確実な手段だと分かった(`designer.close()`やAlt+F4では、このオーバーレイ自体は表示されるが閉じる動作には繋がらなかった——原因は未調査のまま)。テスト用フロー`onerror_tag_check`・4つの切り分け試行はこの方式で保存せずに閉じ、出力ファイルも作成していないため、追加のクリーンアップは不要。

## 88. 【知見85の低優先度フォローアップを解決】`IF`/`SET`の`=`/`<>`演算子も`ComparisonCalculator.Compare`と同じ型変換規則に従うと実機確認——`render_condition`/`SET`複合式の両方を修正

知見85で「`SubtractLists`/`FindCommonListItems`専用の比較エンジンで確認した型変換規則(数値文字列と数値は型をまたいで等価)が、`IF`/`SET`の`=`/`<>`演算子でも同じかどうかは未確認」と留保していた項目を、知見87の調査完了後、知見81の「Run実行+ファイル書き出し」手法で解決した。新規テストフロー(`eq_compare_check`、保存せず破棄)に、全て既に実機確認・結線済みのTier1アクション(`SET`+`File.WriteText`)のみで5つの比較式を知見75のペースト技法で貼り付け・Run実行した。

**実機確認結果**:

| 式 | 結果 | 解釈 |
| --- | --- | --- |
| `$'''1''' = 1`(数値文字列 vs 数値) | `True` | 型をまたいで等価と判定(知見85の`ComparisonCalculator.Compare`と同じ) |
| `$'''Apple''' = $'''apple'''`(大文字小文字) | `False` | 大文字小文字を区別する(知見85と整合) |
| `1 = 1`(対照) | `True` | 通常の数値比較(確認のみ) |
| `$'''abc''' = $'''abc'''`(対照) | `True` | 通常の文字列比較(確認のみ) |
| `$'''1''' <> 1`(`<>`での対照確認) | `False` | `=`の結果の否定と整合、`<>`側も同じ型変換規則に従う |

**確認できた事実**: PADの`=`/`<>`演算子は、知見85で確認した`SubtractLists`等の内部比較エンジン(`ComparisonCalculator.Compare`)と**全く同じ型変換規則**に従う——つまりPAD内部では比較系の全機能(条件式演算子・リスト比較エンジン)が同一の比較ロジックを共有していると考えられる。これにより知見85で残していた留保事項が解消された。

**修正内容**: `dump_daemon/pad_action_lib/expr_runtime.py`に`pad_equal(a, b)`(知見85の`_pad_compare_equal`と同じロジック: 直接の`==`が偽の場合のみ両辺を`float()`でパースして再比較)を追加し、`variables_actions.py`の`_pad_compare_equal`はこちらの再エクスポートに統一(ロジックの重複を解消)。`pad_codegen/render.py`の`render_condition()`(`IF`/`CASE`/`WHILE`で使用)と`_render_expr_as_python()`(`SET`複合式で使用)の両方で、`=`→`expr_runtime.pad_equal(a, b)`・`<>`→`not expr_runtime.pad_equal(a, b)`に変更した(Pythonの素直な`==`/`!=`では数値文字列と数値のクロス型比較を再現できないため、知見86の`pad_add`と同じ理由で専用ヘルパーに委ねる)。既存の`=`演算子を使うテスト4件が期待通り「良い意味で」壊れ、新しい生成結果に合わせて修正した。テスト用フロー・結果ファイルは保存せず削除し、実機状態をクリーンに戻した。

## 89. B節の`Variables.FindOrReplaceInDataTable.FindItemInDataTableEverywhere`の出力契約を実機確認——`DataTableMatches`は`(行, 列)`の0始まりペアのリスト

A/B節のRDP必須項目を再点検した結果、`FindOrReplaceInDataTable.FindItemInDataTableEverywhere`だけは「出力契約(`DataTableMatches`の形)が未確認」という理由で未結線だったが、これは`AddRowToDataTable`/`AddColumnToDataTable`等、既にTier1として実機確認・結線済みのアクションだけでDataTableを組み立てられるため、知見81の「Run実行+ファイル書き出し」手法をそのまま適用できることに気づいた(RDP不要)。

新規テストフロー(`find_replace_check`、保存せず破棄)で、`CreateNewDatatable`+`AddColumnToDataTable`(2列作成)+`CreateNewList`/`AddItemToList`/`AddRowToDataTable`(2行追加: `["apple","banana"]`・`["Apple","cherry"]`)でDataTableを構築し、`FindItemInDataTableEverywhere`を3パターンで実行、結果を`File.WriteText`で書き出した。

**実機確認結果**:

| パラメータ | 結果(`%DataTableMatches%`の生テキスト) | 解釈 |
| --- | --- | --- |
| `ValueToFind: "apple"`・`AllMatches: True`・`MatchCase: False`・`MatchEntireCellContents: False` | `"0, 0\n1, 0"` | (0,0)=`"apple"`・(1,0)=`"Apple"`(大文字小文字無視で部分一致)の2件 |
| 同条件で`AllMatches: False` | `"0, 0"` | 最初の1件のみ(行→列の順で走査した最初の一致)——スカラーではなく要素数1のリストのまま(直列化形式が変わらないため) |
| 同条件で`MatchEntireCellContents: True` | `"0, 0\n1, 0"` | セル全体一致でも(大文字小文字無視のため)両方一致、結果は変わらず |
| `ValueToFind: "zzz_nomatch"` | `""`(空) | 一致無しは空リスト |

**確認できた事実**: `DataTableMatches`は`(行インデックス, 列インデックス)`の0始まりペアのリストで、行→列の順で走査して見つかった順に並ぶ。`AllMatches: False`でも型は変わらず(最初の1件だけを含むリストのまま)。`MatchCase`/`MatchEntireCellContents`の意味論は知見85/知見のFindOrReplaceで既に確認済みの`_cell_matches()`ロジック(大文字小文字無視・部分一致/全体一致の切り替え)とそのまま一致した。

**修正内容**: `dump_daemon/pad_action_lib/variables_actions.py`に`find_item_in_datatable_everywhere()`(既存の`_cell_matches()`ヘルパーを再利用、`is_regex=False`固定)を実装し、`pad_codegen/actions/variables.py`の`Variables.FindOrReplaceInDataTable.FindItemInDataTableEverywhere`を結線した(`codegen_coverage.py`: 176/202→177/202、87%→88%)。テスト用フロー・結果ファイルは保存せず削除し、実機状態をクリーンに戻した。

## 90. 【新手法】decompile(ilspycmd)+知見81のRun実行検証を組み合わせ、`Variables.FilterDataTable`の`FilterParameters`スキーマを特定・結線

知見89の「Tier1確認済みアクションだけでDataTableを組み立てられるなら、未知の出力/入力契約もRun実行で検証できる」という発見を、A節で長らく`NotImplementedError`のまま残っていた`Variables.FilterDataTable`(フィルタ条件のDataTableスキーマが未確認)にも適用した。ただし今回は「出力の形」ではなく「入力(`FilterParameters`)に何を書けば受理されるか」自体が未知だったため、まず知見76/77の手法(`ilspycmd`でPAD本体のDLLを再デコンパイル)でソースを特定してから、知見81のRun実行で裏取りする、という2段階のアプローチを取った。

**手順1(decompile)**: `clipwire exec`でVM上の`C:\Program Files (x86)\Power Automate Desktop\Microsoft.Flow.RPA.Desktop.Modules.Variables.Actions.dll`(259,864バイト)をBase64化して取得し、ローカルの`ilspycmd`で逆コンパイル(本リポジトリには逆コンパイル結果自体はコミットしない方針は従来通り)。`FilterDataTableAction.Execute()`・`FilterDataTableExtensions`・`FilterDataTableUtilities.BuildFilterExpression()`から、`FilterParameters`の列スキーマが**`COLUMN`/`OPERATOR`/`VALUE`/`RULE`**(いずれも大文字)の4列であり、`OPERATOR`は`FilterConditionOperator`という16種(`Equal`/`NotEqual`/`GreaterThan`/`GreaterThanOrEqual`/`LessThan`/`LessThanOrEqual`/`IsEmpty`/`IsNotEmpty`/`IsBlank`/`IsNotBlank`/`StartsWith`/`EndsWith`/`Contains`/`NotContains`/`NotStartsWith`/`NotEndsWith`)の列挙型名の文字列、`RULE`は`FilterLogicalOperator`(`Or`/`And`、2行目以降でのみ読まれ前の行との結合方法を表す)だと判明した。さらに`Equal`/`NotEqual`限定の非自明な挙動も発見: 列の実際の値の型とフィルタ値(`VALUE`)の型が一致しない場合、`Equal`は**常に偽**、`NotEqual`は**常に真**になる(`columnType != rawValue.GetType()`という`flag`判定)。

**手順2(実機検証)**: decompileで判明したスキーマが本当に受理されるか、`CreateNewDatatable`+`AddColumnToDataTable`+`AddItemToList`/`AddRowToDataTable`(いずれもTier1確認済み)だけで`FilterParameters`テーブル自体を組み立て、知見81のRun実行+ファイル書き出しで検証した(新規テストフロー`filter_dt_check`、保存せず破棄)。

| テスト | 条件 | 結果(`FilteredDataTable`をCSV変換した内容) | 解釈 |
| --- | --- | --- | --- |
| 単一条件 | `Age Equal "30"`(Name/Age列、値は全て文字列) | `Alice,30`/`Carol,30`(Bobの25は除外) | decompile通りの単純`Equal`が機能 |
| 2条件AND | `Age Equal "30"` AND `Name Equal "Carol"` | `Carol,30`のみ | `RULE: And`による2条件の結合が機能 |
| `Contains` | `Name Contains "ob"` | `Bob,25`のみ | 部分一致演算子も機能 |

3パターンとも一切のエラー無く実行でき、全て期待通りの結果になった——decompileで読んだスキーマが完全に正しいと確証された。

**修正内容**: `dump_daemon/pad_action_lib/variables_actions.py`に`filter_datatable(table, conditions, match_case=True)`を実装した。論理演算子の優先順位(ANDがORより強く結合)に従い、`RULE: Or`が現れた位置でOR区切りのAND-groupに分割してから評価する(単純な左から右への畳み込みではない)。`Equal`/`NotEqual`の型不一致時の挙動もdecompileの`flag`判定を忠実に再現した。`pad_codegen/actions/variables.py`の`Variables.FilterDataTable`を結線し、`FilterParameters`が知見72の「一度も編集されていない」空バックティック文字列(`` `` ``→Pythonの`""`)の場合は`[]`に読み替える(`FilterDataTableAction.Execute()`自身も`FilterParameters.Rows.Count == 0`で元のテーブルをそのまま返すため、この既定動作と一致する)。`codegen_coverage.py`: 177/202→178/202(88%)。

**留保事項**: 実機で直接検証したのは`Equal`・`Contains`・`RULE: And`の組み合わせのみ。残り13種の演算子(`GreaterThan`等の順序比較・`IsEmpty`/`IsBlank`系・`StartsWith`等)と`RULE: Or`(OR-group分割)自体はdecompileしたソースコードに忠実な実装であり、ソースの正確性自体は`Equal`/`Contains`の一致で裏付けられたが、個別には実機未検証のまま。`Variables.JoinDataTable`も同じDLL内に`JoinDataTableExtensions`(`TryGetJoinFirstColumnName`等)が見つかっており、同じ2段階アプローチ(decompile→Run検証)で次に調査できる見込みだが、`JoinDataTableAction`自体はFilterより実装が複雑(複合インデックスによる最適化パス・Left/Full結合でのnull埋め・重複列名の` (2)`リネーム等)なため、本tickでは着手しなかった。

## 91. 知見90と同じ手法(decompile+Run実行検証)を`Variables.JoinDataTable`にも適用——`JoinParameters`スキーマを特定し、`Inner`/`Left`/`Full`全3種を実機確認

知見90で確立した「decompileでスキーマを特定→知見81のRun実行手法でTier1確認済みアクションだけから実際にそのスキーマを構築して検証」という2段階アプローチを、同じDLL内に見つかっていた`JoinDataTableAction`/`JoinDataTableExtensions`にも適用した。

**decompile結果**: `JoinParameters`は`"COLUMN 1"`/`OPERATOR`/`"COLUMN 2"`の3列を持つDataTable(`FilterParameters`の`COLUMN`と異なり**列名に半角スペースを含む**点に注意)。`OPERATOR`は`JoinComparisonOperator`(`Equal`/`NotEqual`/`GreaterThan`/`GreaterThanOrEqual`/`LessThan`/`LessThanOrEqual`の6種、`FilterConditionOperator`の文字列系演算子は無し)。全条件行はAND結合(`FilterParameters`の`RULE`列に相当するものは存在しない)。`RowsMatch()`が`ComparisonCalculator.I.Compare`(知見85/88で確認済みの同じ比較エンジン)に委譲しているため、`Equal`/`NotEqual`はクロス型の数値文字列同値判定も効くと推測できる。`BuildEmptyResultTable()`で両テーブルの列名が重複する場合、2番目のテーブル側の列名に`" (2)"`を付けて区別する。`Left`/`Full`結合の不一致側は`null`で埋める。

**実機検証**: `T1`(Name/Age列、Alice/30・Bob/25)と`T2`(Name/City列、Alice/NYC・Carol/LA)を構築し、`JoinParameters`(`COLUMN 1`="Name" `OPERATOR`="Equal" `COLUMN 2`="Name")で`Inner`/`Left`/`Full`の3パターンを実行した。

| JoinOperation | 結果(CSV) | 解釈 |
| --- | --- | --- |
| `Inner` | `Name,Age,Name (2),City` / `Alice,30,Alice,NYC` | 一致するAliceのみ、列名重複が`Name (2)`に |
| `Left` | 上記 + `Bob,25,,`(空セル) | T1の不一致行(Bob)もNoneパディングで残る |
| `Full` | 上記 + `,,Carol,LA`(T1側が空セル) | T2の不一致行(Carol)もT1側を空にして追加 |

3パターンとも一切のエラー無く実行でき、decompileで予測した通りの結果(列名の`" (2)"`リネーム・null埋めの空セル化を含む)と完全に一致した。

**修正内容**: `dump_daemon/pad_action_lib/variables_actions.py`に`join_datatable(first, second, join_parameters, join_operation="Inner")`を実装した。`Equal`/`NotEqual`は知見85/88の`pad_equal()`、順序比較系は数値変換できる場合のみ数値として比較する(decompileのComparisonCalculator委譲を再現、個別の実機検証は`Equal`のみ)。`pad_codegen/actions/variables.py`の`Variables.JoinDataTable`を結線し、`JoinParameters`が空バックティック文字列の場合は`[]`に読み替える——`FilterDataTable`と違い`JoinDataTableAction.Execute()`には早期returnが無く、空条件での`all()`判定がPAD側の`.All()`と同じVacuous-True(直積/cartesian product)になるため、この読み替えは実機の挙動と一致する(知見90の「未設定なら元のテーブルのまま」とは異なる意味論)。`codegen_coverage.py`: 178/202→179/202(89%)。

**留保事項**: 実機で直接検証したのは`Equal`のみ。残り5種の順序比較演算子はdecompileしたソースコードに忠実な実装だが個別には実機未検証。これで`pad_todo.md`のA節に長年残っていた「`FilterDataTable`/`JoinDataTable`のスキーマ未確認」というブロッカーは両方解消された。

## 92. A節最後の未確認項目を解決——`Variables.GenerateDataTableFromCSV`の`ReadFieldsAsText: False`は数値らしきフィールドを実際の数値型に変換すると実機確認(先頭ゼロが失われる)

A節に長く残っていた「`ReadFieldsAsText: False`の数値コレーション挙動は推測のみで未確認」という項目を、知見81の「Run実行+ファイル書き出し」手法で解決した。ヘッダー無しCSVテキスト`"007,abc\n1,2"`を`SET`で変数に入れ、`Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator`(`ReadFieldsAsText: False`)で読み込んだ結果を`Variables.ConvertDataTableToCSV`でCSVテキストに戻し、`File.WriteText`で書き出した(新規テストフロー`csv_type_check`、保存せず破棄)。

**実機確認結果**: 書き出されたテキストは`"7,abc\n1,2\n"`——`"007"`が`"7"`になり**先頭ゼロが失われた**。これは文字列のままなら起こり得ない変化であり、`ReadFieldsAsText: False`が数値として解釈できるフィールドを実際に数値型へ変換していることの直接証拠になる(`"abc"`は変化せず文字列のまま)。

**確認できた事実**: `ReadFieldsAsText: False`時、CSVの各フィールドは数値としてパースできれば数値型に変換され(整数らしき文字列は整数に、そうでなければ浮動小数点数にパースされると推測され、今回のテストでは整数ケースのみ確認)、パースできない場合は文字列のまま保持される——`int()`→`float()`の順でパースを試みるPython側の既存パターン(知見86の`pad_add`等と同系統)と一致する解釈で実装できる。

**修正内容**: `dump_daemon/pad_action_lib/datatable.py`の`datatable_from_csv_text()`に`read_fields_as_text: bool = True`引数を追加し、`False`の場合は各セルに`_csv_as_number()`(`int()`→`float()`の順でパース、失敗時は元の文字列のまま)を適用するようにした。`pad_codegen/actions/variables.py`の`Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator`の結線条件を「`ReadFieldsAsText`が`True`のときのみ」から「`True`/`False`どちらでも結線」に緩和した。これでA節に残っていたDataTable/CSV関連の実機未確認事項は全て解決し、A節の未解決分岐点は23/202→22/202(89%→89%、小数点以下では変化なし、整数部では180/202)になった。テスト用フロー・結果ファイルは保存せず削除し、実機状態をクリーンに戻した。

**留保事項**: 浮動小数点数(小数点を含むフィールド、例: `"3.14"`)が実際に`float`へ変換されるか、負数・指数表記等の扱いは未検証のまま(整数ケースのみ実機確認)。`TrimFields`パラメータ(今回は`True`のまま固定)の効果も`pad_codegen`側では依然未結線(別の低優先度の未解決項目として残る)。

## 93. 低優先度の持ち越し項目`TrimFields`を実機確認——単純な前後空白除去(`.strip()`)と確定

A節に「低優先度」として残っていた`TrimFields`(CSV各フィールドの前後空白除去と推測されていたが未確認)を、知見81の「Run実行+ファイル書き出し」手法で解決した。`SET CSV TO $''' 7 , abc '''`(各フィールドの前後に空白を含むCSVテキスト)を`Variables.GenerateDataTableFromCSV`で`TrimFields: True`/`False`の両方で読み込み、`Variables.ConvertDataTableToCSV`で戻した結果を角括弧で囲んで書き出した(新規テストフロー`trimfields_check`、保存せず破棄)。

**実機確認結果**:

| `TrimFields` | 結果 | 解釈 |
| --- | --- | --- |
| `True` | `[7,abc]` | 各フィールドの前後空白が除去される |
| `False` | `[ 7 , abc ]` | 空白がそのまま保持される |

推測通り単純な`.strip()`相当の挙動であり、特別な意味論(タブ/改行のみ除去する等)は無いと確定した。

**修正内容**: `dump_daemon/pad_action_lib/datatable.py`の`datatable_from_csv_text()`に`trim_fields: bool = True`引数を追加し、`True`の場合はCSV各セル(ヘッダー行含む)に`.strip()`を適用してから列名割り当て/数値変換(知見92)を行うようにした。`pad_action_lib/file_actions.py`の`read_from_csv_file()`にも同じ引数を追加して委譲した。`pad_codegen/actions/variables.py`の`Variables.GenerateDataTableFromCSV.ReadPredefinedSeparator`・`pad_codegen/actions/file.py`の`File.ReadFromCSVFile.ReadCSV`の両方で`TrimFields`を読み取って結線するよう更新した(従来は値を読み取らず常に無視していた——もし実機で`TrimFields: False`な非トリムCSVが来た場合に誤った結果を生成しうる、知らぬ間の挙動不一致だった)。テスト用フロー・結果ファイルは保存せず削除し、実機状態をクリーンに戻した。

**留保事項**: ヘッダー行自体(`FirstLineContainsColumnNames: True`時の列名)もトリム対象になるかは直接確認しておらず(今回のテストは`FirstLineContainsColumnNames: False`で実施)、実装では一貫性のため同じ`.strip()`をヘッダー行にも適用しているが、これは推測の範囲内にとどまる。

## 94. 【VM不要、既存フィクスチャの再点検で発見】`Web.*`の`UserAgent`/`FollowRedirection`が`web_actions`側で未対応のまま無視されていたバグを修正——`UserAgent`の正確な文字列は既に実機フィクスチャに含まれていた

知見93の「パラメータを読み取っているように見えて実は無視している」という不整合のパターンを他のモジュールでも探すため、`pad_codegen/actions/*.py`全体を「無視」「未実装のまま」等のキーワードで再点検した。`web.py`の`Web.*`モジュールに同種の問題を発見したが、今回は**VMでの新規実機検証は一切不要**だった——既存の実機キャプチャ`tests/fixtures/tier1_web_xml_batch8.txt`を読み直すだけで解決した。

**発見した事実**: `web.py`のモジュールdocstringには「`UserAgent`はPAD側のハードコードされたFirefox 3.6 UA文字列だが正確なバイト列は未確認」と書かれていたが、**実際には`tier1_web_xml_batch8.txt`に正確な文字列が既にキャプチャされていた**(`UserAgent: $'''Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.21) Gecko/20100312 Firefox/3.6'''`、`DownloadFromWeb`/`InvokeWebService`/`InvokeSoapService`の3アクション全てで同一値)——「でっち上げを避けるため未確認のまま」という判断自体は古い情報に基づく誤りだった。

さらに`pad_action_lib.web_actions`の`invoke_web_service()`/`invoke_soap_service()`は`follow_redirection`/`user_agent`という引数を**そもそも受け付けていなかった**(`download_from_web()`だけが対応済み)。`httpx.Client()`はリダイレクト追従の既定値が`follow_redirects=False`であり、実機の既定値`FollowRedirection: True`と食い違う——つまり`InvokeWebService`/`InvokeSoapService`経由で生成されたPythonコードは、実機のPADフローとは異なり**リダイレクトを追従しない**という、サイレントな挙動不一致のバグになっていた。

**修正内容**: `dump_daemon/pad_action_lib/web_actions.py`の`invoke_web_service()`/`invoke_soap_service()`に`follow_redirection: bool = True`・`user_agent: str | None = None`引数を追加し、`httpx.Client(follow_redirects=follow_redirection, ...)`・`headers.setdefault("User-Agent", user_agent)`を適用するようにした(`download_from_web()`と同じパターンに統一)。`pad_codegen/actions/web.py`の3アクション全ての結線で`FollowRedirection`/`UserAgent`パラメータを読み取り、実際に渡すよう修正した(`Web.DownloadFromWeb.Download`は`user_agent`を実装側は既に対応していたのに結線漏れだった)。`httpx.Client`のコンストラクタ引数を捕捉するテスト(`monkeypatch`でクラスを差し替え)で`follow_redirects`が正しく渡ることを、`httpx.MockTransport`で`User-Agent`ヘッダーが正しく送られることをそれぞれ確認した。

**留保事項**: `ClearCookies`/`EncodeRequestBody`は依然未対応のまま意図的にTODOへ残す。`ClearCookies`はPAD側がフロー実行全体で永続的なCookieセッションを持つ前提の挙動と推測されるが、`pad_action_lib`側は呼び出し毎に新規`httpx.Client`を作る設計のためCookie永続化という概念自体が無く、対応には`CodegenContext`へセッション状態を持たせる等の大きな設計変更を伴う。`EncodeRequestBody`はdecompile調査が未着手のため意味論が未確認のまま。

## 95. 【VM不要、全フィクスチャの機械的突き合わせで発見】`Web.InvokeSoapService`の`FailOnErrorStatus`/`TrimRequestBody`/`AcceptUntrustedCertificates`欠落、`Folder.GetFiles`/`GetSubfolders`の`SortBy2/3`ゲート漏れを同時に修正

知見93・94で見つけた「値を読み取っているように見えて実は無視」パターンを体系的に洗い出すため、`tests/fixtures/*.txt`の各実機キャプチャ済みパラメータ名と、対応する`pad_codegen/actions/*.py`の`generate()`分岐内で実際に`p.get(...)`参照されているパラメータ名を機械的に突き合わせるスクリプトを書いて全モジュールを一括点検した(VM不要、ローカルのみ)。

**発見1: `Web.InvokeSoapService.InvokeSoapService`** — 実機キャプチャには`FailOnErrorStatus: False`・`TrimRequestBody: True`・`AcceptUntrustedCertificates: False`が明示的に含まれているが、`invoke_soap_service()`自体がこれらの引数を一切受け付けておらず(`invoke_web_service()`への委譲時に常に既定値のまま呼んでいた)、`pad_codegen`側もこれらを読み取っていなかった。たまたま実機の値が全て既定値と一致していたため今まで表面化しなかった潜在バグ。`invoke_soap_service()`に3引数を追加し`invoke_web_service()`へ素通りさせ、`pad_codegen/actions/web.py`の対応する分岐で実際に読み取るよう修正した。

**発見2: `Web.InvokeWebService`/`InvokeSoapService`の`Encoding`** — `DownloadFromWeb`では`Encoding: AutoDetect`であることをゲートで確認しているが、`InvokeWebService`/`InvokeSoapService`では`Encoding`パラメータ自体を一切読み取らず、値を問わず常に変換を進めてしまっていた。`DownloadFromWeb`と同じ`AutoDetect`確認ゲートを追加した(現時点で両アクションとも応答エンコーディングの明示上書き機能自体を実装していないため、`AutoDetect`以外の値が来たら安全にTODOへ倒す)。

**発見3: `Folder.GetFiles`/`Folder.GetSubfolders`の`SortBy2`/`SortBy3`** — 既存のゲートは`SortBy1 != "NoSort"`のみを確認しており、`SortBy1: NoSort`かつ`SortBy2`/`SortBy3`に実際の並べ替えキーが指定されている(2次・3次キーだけを使うケース)を見逃していた。実機フィクスチャでは3つとも常に`NoSort`だったため今まで表面化しなかった。`SortBy2`/`SortBy3`も`NoSort`であることを確認する完全なゲートに修正した。

**意義**: 知見93・94で見つけた「値を読み取るふりをして無視する」パターンが、個別の思いつきではなく体系的な見落としとして複数箇所に存在していたことが、機械的な突き合わせによって確認できた。この種のバグはテストでは検出されない(生成されたコードがコンパイル・実行自体は成功するため)——実機の既定値が偶然TODOフォールバックの既定動作と一致する限り症状が出ないサイレントな不整合である。

## 96. `Web.InvokeWebService`の`EncodeRequestBody`をdecompileで解明——`HttpUtility.UrlEncode`相当、`TrimRequestBody`より先に適用。副産物として`ClearCookies`がフロー全体で共有される永続Cookieジャーだと確定(実装は設計変更を伴うため見送り)

知見90・91で確立した「`ilspycmd`でPAD本体のDLLを再デコンパイルしスキーマ/意味論を特定する」手法を、知見94・95で未対応のまま残した`Web.InvokeWebService`の`EncodeRequestBody`に適用した。VM上の`Microsoft.Flow.RPA.Desktop.Modules.Web.Actions.dll`(208,184バイト)を取得・decompileし、`InvokeWebServiceAction.Execute()`のソースを直読みした。

**発見した事実**: `EncodeRequestBody: True`の場合、`RequestBody`全体に`HttpUtility.UrlEncode(RequestBody)`(`application/x-www-form-urlencoded`形式のURLエンコード、空白は`+`——Pythonの`urllib.parse.quote_plus()`と同じ規則)を適用してから、`FormulateWebRequest()`内部で`TrimRequestBody`の処理(文字列全体の`.Trim()`)を行う、という順序だった。つまり**エンコードが先、トリムが後**。

**副産物の発見**: `FormulateWebRequest()`の実装を読む過程で、`ClearCookies`の正体も判明した——`CompiledJob.CookieContainer`という、**1回のフロー実行全体で共有される永続的なCookieジャー**が存在し、各Web系アクションの呼び出しのたびに、レスポンスのCookie(`Set-Cookie`)が無条件にこのジャーへ蓄積され(`CompiledJob.CookieContainer.Add(response.Cookies)`)、次の呼び出しでもそのまま使われる。`ClearCookies: True`の場合のみ、リクエスト送信直前にこのジャーを空の新規`CookieContainer`へ差し替える。つまりPADは**ブラウザのような暗黙のCookieセッションをフロー実行全体で維持**しており、`ClearCookies: False`(実機で唯一確認できている値)は「このセッションを維持したまま続ける」ことを意味する。

**修正内容**: `dump_daemon/pad_action_lib/web_actions.py`の`invoke_web_service()`に`encode_request_body: bool = False`引数を追加し、`urllib.parse.quote_plus()`→(`trim_request_body`なら)`.strip()`の順で適用するようにした(`InvokeSoapService`には`EncodeRequestBody`自体のパラメータが無い——SOAPボディは常にXMLのため不要)。`pad_codegen/actions/web.py`の`Web.InvokeWebService.InvokeWebService`を結線した。

**`ClearCookies`は依然未対応のまま意図的に保留**: 意味論自体はdecompileで確定したが、再現するには`pad_action_lib`側に「呼び出し毎に新規`httpx.Client`を作る」という現在の設計を変更し、フロー実行全体(1つの生成されたPythonスクリプトの実行全体)で共有される永続的なCookie状態(`httpx.Client`インスタンス自体の共有、または`CodegenContext`経由のセッション状態注入)を新設する必要がある——これは個別のパラメータ結線ではなく、codegenのアーキテクチャに踏み込む決定であり、かつ実機フィクスチャでは常に`ClearCookies: False`(かつ1フィクスチャにつきWeb系アクションは1個のみ)しか確認できておらず、複数のWeb呼び出しを跨ぐCookie永続化が実際に必要になる実例も無いため、今回は見送った。

## 97. 【自己発見バグ】`JoinDataTable`の順序比較演算子(GreaterThan等)が実機では数値変換せず文字列の辞書順で比較すると判明——知見91で実装した数値変換は誤りだったため削除

知見90・91で結線した`FilterDataTable`/`JoinDataTable`の演算子のうち、実機で直接検証したのは`Equal`・`Contains`・2条件ANDのみで、順序比較演算子(`GreaterThan`等)は「decompileしたソースに忠実な実装だが個別の実機検証はしていない」という留保事項として明記していた。VMが空いたタイミングで、この留保事項を追加検証する目的で`FilterDataTable`と`JoinDataTable`それぞれの`GreaterThan`を実機確認したところ、**知見91で実装した数値変換ロジックが実機の挙動と食い違っている**ことが判明した。

**`FilterDataTable`での確認(数値変換なしの実装のまま偶然正しかった)**: 列`Value`(文字列`"9"`/`"10"`/`"2"`)に対し`Value GreaterThan "5"`でフィルタしたところ、結果は`"9"`のみ(`"10"`・`"2"`は除外)——これは数値比較(`9>5`真・`10>5`真・`2>5`偽、2件該当のはず)とは食い違い、**文字列の辞書順比較**(`"9">"5"`真・`"10">"5"`偽(`'1'<'5'`)・`"2">"5"`偽)と完全に一致する。`filter_datatable()`の実装は元々`cell > value`(Pythonの文字列比較)をそのまま使っており、数値変換ロジックを追加していなかったため、**偶然ではあるが既に正しい実装**だった。

**`JoinDataTable`での確認(知見91のバグを発見)**: `Table1`(`Value="9"`の1行)と`Table2`(`Value="5"`/`"10"`/`"2"`の3行)を`Value GreaterThan Value`で結合したところ、結果は**全3行とも一致**(`9,5`・`9,10`・`9,2`)——数値比較なら`9>10`が偽になり2件のみのはずだが、文字列比較なら`"9">"5"`・`"9">"10"`(`'9'>'1'`)・`"9">"2"`が全て真になり3件マッチする。実機は3件だったため、**こちらも文字列の辞書順比較**だと確定した。ところが`join_datatable()`の`_join_condition_matches()`は`Equal`/`NotEqual`以外の演算子に対して`_join_as_number()`で数値変換を試みてから比較する実装になっており、これは実機の挙動と食い違う**誤りだった**。

**意義**: `FilterDataTable`(`DataView.RowFilter`という.NET標準の式評価エンジン)と`JoinDataTable`(`ComparisonCalculator.Compare`というPAD独自の比較エンジン、知見85/88の`=`/`<>`と同じエンジン)は、**`Equal`/`NotEqual`では後者がクロス型の数値文字列同値判定をする(知見85/88)が、順序比較演算子ではどちらのエンジンも数値変換をしない**(常に文字列として比較する)という点で一致することが確認できた。クロス型の緩い変換は`Equal`/`NotEqual`限定の挙動であり、順序比較には適用されない。

**修正内容**: `dump_daemon/pad_action_lib/variables_actions.py`の`_join_condition_matches()`から`_join_as_number()`による数値変換ロジックを削除し、`GreaterThan`等を`a > b`(Pythonの素直な比較、文字列なら辞書順)のまま使うようにした(`_join_as_number()`自体も未使用になったため削除)。`filter_datatable()`側は元々数値変換ロジックを持っていなかったため変更不要だった。回帰テスト(`test_join_datatable_greater_than_compares_as_strings_not_numbers`)を追加した。テスト用フロー・結果ファイルは保存せず削除し、実機状態をクリーンに戻した。

**教訓**: 「decompileしたソースコードを忠実に実装する」だけでは不十分で、decompileされた呼び出しチェーンの先(この場合`ComparisonCalculator.Compare`自体の内部実装)まで読み切らないと、呼び出し元の型変換前処理を誤って真の比較ロジックだと錯覚しうる——実機のRun実行による裏取りが無ければ見逃していたバグだった。

## 98. 知見90で留保していた`FilterDataTable`の`Equal`型不一致挙動を実機確認——decompileの推測通り「型が食い違えば常に不一致」と確定

知見97に続けて、知見90・91で「decompileのソースに忠実な実装だが実機未検証」として残していたもう1つの留保事項(`Equal`/`NotEqual`の型不一致挙動)を実機確認した。`SET CSV TO $'''30'''`→`Variables.GenerateDataTableFromCSV`(`ReadFieldsAsText: False`)で列`Column#1`を**実際の数値型**(知見92)に変換したテーブルに対し、`FilterParameters`(`COLUMN: Column#1`・`OPERATOR: Equal`・`VALUE: $'''30'''`——これは文字列)でフィルタしたところ、結果は**0件**(ヘッダー行のみ)だった。

**確認できた事実**: 列の実際の値の型(数値)とフィルタ値`VALUE`の型(文字列)が食い違う場合、見た目の値が一致していても(`30`と`"30"`)`Equal`は常に不一致と判定される——decompileした`FilterDataTableAction`の`flag`判定(`columnType != rawValue.GetType()`)がそのまま実機でも成立することが確定した。知見85/88の`ComparisonCalculator.Compare`(`=`/`<>`演算子、`SubtractLists`等)が行う「数値文字列と数値は型をまたいで等価」という**緩い**変換とは対照的に、`FilterDataTable`の`Equal`(`DataView.RowFilter`という別の比較エンジン)は型不一致を**常に不一致**として扱う、より厳格な挙動だと確認できた——両エンジンの挙動は似ているようで異なる。

**修正内容**: 実装(`filter_datatable()`の型不一致判定)はdecompileに基づく記述のまま変更不要だった(元から正しかった)。コメント・テストのdocstringを「decompile済みソースの推測」から「知見98で実機確認済み」に更新するのみ。テスト用フロー・結果ファイルは保存せず削除し、実機状態をクリーンに戻した。これで知見90・91の留保事項のうち、`Equal`の型不一致判定と順序比較演算子(知見97)の両方が実機確認済みになった。

## 99. 知見90の最後の留保事項`RULE: Or`のグループ分割ロジックを実機確認——単純なOR結合も正しく動作

知見90・97・98に続けて、`FilterDataTable`の`FilterParameters`に関する最後の留保事項(`RULE: Or`によるAND-groupの分割ロジックは`Equal`の2条件ANDでしか実機確認しておらず、OR自体は未検証)を実機確認した。3行のテーブル(Alice/30・Bob/25・Carol/40)に対し、`Age Equal 30`(1行目、`RULE`は無視される)・`Age Equal 40 RULE: Or`(2行目)の2条件でフィルタしたところ、結果はAlice・Carol(Bobを除外)——`filter_datatable()`の「`RULE: Or`が現れた位置でOR区切りのAND-groupに分割し、いずれかのgroupが真なら一致」というロジックが単純な2条件ORのケースで正しく動作することを確認した(複雑な3条件以上の混在ANDOR優先順位は今回未検証のまま)。

実装は元から正しく変更不要だった。コメント・テストのdocstringを更新するのみ。これで知見90で結線した`FilterDataTable`の全ての留保事項(順序比較演算子=知見97、`Equal`型不一致=知見98、`RULE: Or`=本知見)が実機確認済みになった。テスト用フロー・結果ファイルは保存せず削除し、実機状態をクリーンに戻した。

## 100. 知見92の留保事項(小数・負数・指数表記)を実機確認——指数表記の整数値が小数点無しで表示される既知のバグを発見・修正

知見92・93に続けて、`GenerateDataTableFromCSV`の`ReadFieldsAsText: False`に残っていた最後の留保事項(小数点を含むフィールド・負数・指数表記の扱いは整数ケースのみ実機確認済みで未検証)を実機確認した。`SET CSV TO $'''3.14,-5,1e2,abc'''`を`ReadFieldsAsText: False`で読み込み、`ConvertDataTableToCSV`で書き戻したところ結果は`"3.14,-5,100,abc"`だった。

**確認できた事実**: 小数(`"3.14"`)はそのまま小数として変換される。負数(`"-5"`)もそのまま負の整数として変換される。指数表記(`"1e2"`)も数値として解釈され、**整数値になる場合は小数点無しの表示**(`"100"`、`"100.0"`ではない)になる——これは知見86の`+`演算子の結果表示規則(整数値になる場合は小数点無し)と同じ.NET側の既定表示規則が、ここでも一貫して適用されていることを示す。

**発見したバグ**: `_csv_as_number()`は`int()`が失敗した場合に`float()`でパースした結果をそのまま返していたため、`"1e2"`は`float("1e2")`=`100.0`(Pythonのfloat)になり、CSV書き戻し時に`str(100.0)`=`"100.0"`という、実機の`"100"`とは食い違う文字列を生成していた——`"3.14"`/`"-5"`では問題が起きなかったため見逃されていた、指数表記特有のバグだった。

**修正内容**: `dump_daemon/pad_action_lib/datatable.py`の`_csv_as_number()`で、`float()`でパースした結果が整数値(`.is_integer()`)の場合は`int()`に変換するようにした(`int()`での直接パースが失敗する指数表記等の経路でのみ発生する差分を補正)。回帰テストを追加した。テスト用フロー・結果ファイルは保存せず削除し、実機状態をクリーンに戻した。これで知見92に残っていた留保事項は全て解決した。

## 101. `+`/`=`演算子の「数値を表す文字列」判定は指数表記を含まないと実機確認——CSV読み込み系の数値変換とは別のPADサブシステムで、より狭い規則を使うと判明

知見100の指数表記調査がCSV読み込み系(`GenerateDataTableFromCSV`)で成立することを確認した直後、同じ「数値を表す文字列」判定が`+`演算子(知見86)・`=`演算子(知見88)でも同じ規則(Pythonの`int()`/`float()`と同じ範囲)で成立するかを実機確認した。`SET Result TO 1 + $'''1e2'''`を実行したところ、結果は**`"11e2"`**(文字列結合)——`101`や`101.0`(数値加算)ではなかった。続けて`SET EqResult TO $'''1e2''' = 100`を実行したところ、結果は**`False`**だった。

**確認できた事実**: `+`/`=`演算子が「数値を表す文字列」と認識する範囲は、知見92・100で確認したCSV読み込み系(`GenerateDataTableFromCSV`の`ReadFieldsAsText: False`)の数値変換規則より**狭い**——指数表記(`"1e2"`)を数値として認識せず、`1 + "1e2"`は文字列結合にフォールバックし(`str(1) + "1e2"` = `"11e2"`)、`"1e2" = 100`は型不一致(片方が「数値と認識されない文字列」のまま)で偽になる。これはPAD内部で**異なる2つのサブシステム**(CSV型推論 vs 演算子のオペランド型判定)が、それぞれ別の「数値らしさ」判定ロジックを使っていることを示す——`int()`/`float()`というPythonの単一の緩い判定基準だけでは、PADの複数のサブシステムの挙動差を正確に再現できないことが分かった重要な発見。

**修正内容**: `dump_daemon/pad_action_lib/expr_runtime.py`に`_NUMERIC_STRING_RE`(符号+整数+小数部のみ、指数表記を除外する正規表現)を追加し、`_as_number()`(`pad_add()`が使う)がこの正規表現にマッチする文字列のみを数値として解釈するよう制限した。`pad_equal()`も独自に`float(a) == float(b)`で判定していたのを`_as_number()`の共有判定に統一した(`SubtractLists`/`FindCommonListItems`/`JoinDataTable`の`Equal`/`NotEqual`も同じ`pad_equal()`に委譲しているため、これらも同時に修正される——知見85/91で確認した`ComparisonCalculator.Compare`が全て同じ内部ヘルパーを共有している可能性と整合する)。`_csv_as_number()`(CSV読み込み系)は意図的に変更しない——これは別のPADサブシステムで、指数表記を数値として受理するのが正しい実機挙動だと知見100で確認済みのため。

テスト用フロー・結果ファイルは保存せず削除し、実機状態をクリーンに戻した。

## 102. 知見101の裏取り——`+`/`=`演算子は桁区切りコンマ(`"1,000"`)を数値として認識すると実機確認、新たな見逃しバグを発見・修正

知見101で「指数表記は数値として認識されない」と確認した直後、同じ「数値を表す文字列」判定の範囲を確かめるため、桁区切りコンマを含む文字列(`"1,000"`)でも同様のテストを行った。`SET R1 TO 1 + $'''1,000'''`・`SET R2 TO $'''1,000''' = 1000`を実行したところ、結果は**`R1=1001`・`R2=True`**——指数表記とは逆に、**桁区切りコンマは数値として認識される**ことが判明した(`1,000`は数値`1000`として解釈され、`1+1000=1001`になる。文字列結合なら`"11,000"`になるはずだった)。

**確認できた事実**: `+`/`=`演算子の「数値を表す文字列」判定は、指数表記は除外するが桁区切りコンマは許容する、という非対称な規則を持つ。これはPythonの`int()`/`float()`(どちらも非対応)とも、知見101で実装した直後の正規表現(コンマ非対応)とも食い違う——つまり知見101の修正自体が、コンマ区切り数値に対する**新たな回帰バグ**を生んでいたことが、この追加検証で発覚した(修正直後に気づいたため実害は出ていない)。

**修正内容**: `dump_daemon/pad_action_lib/expr_runtime.py`の`_NUMERIC_STRING_RE`を`^[+-]?[\d,]+(\.\d+)?$`(整数部にコンマを許容、指数表記`e`/`E`は依然除外)に変更し、`_as_number()`で実際に`int()`/`float()`へ渡す前にコンマを除去するようにした。桁区切りの3桁ごとのグルーピングが厳密に検証されるか(例: `"1,0"`のような不正な区切りが拒否されるか)は未検証のまま、より緩い「コンマを含んでいれば除去して数値変換を試みる」という寛容な実装にとどめた。回帰テストを追加した。テスト用フロー・結果ファイルは保存せず削除し、実機状態をクリーンに戻した。

**教訓**: 1つの実機確認結果から導いた規則(「指数表記は除外」)を、安易に「その他の非標準表記も全て除外」という方向に一般化せず、桁区切りのような別のよくある非標準表記は個別に実機確認する必要がある、という当然ながら重要な教訓を再確認した。

## 103. CSV読み込みサブシステムも桁区切りコンマを数値として認識すると実機確認——知見92/100の`_csv_as_number()`に同じ見逃しがあったため修正

知見102で`+`/`=`演算子が桁区切りコンマを数値として認識すると確認した直後、同じ見逃しがCSV読み込みサブシステム(`GenerateDataTableFromCSV`、知見92・100)にも無いか確認した。CSVのクォート構文(`"1,000"`、ダブルクォートで囲むことでコンマを区切り文字ではなくフィールド値の一部として保護する標準CSV記法)を使い、`SET CSV2 TO $'''"1,000"'''`→`ReadFieldsAsText: False`で読み込んだところ、結果は数値`1000`(ラウンドトリップ後`"1000"`)だった——予想通り、こちらのサブシステムも桁区切りコンマを数値として認識する。

**確認できた事実**: `+`/`=`演算子用のサブシステム(知見101・102)とCSV読み込み用のサブシステム(知見92・100)は、「指数表記」の扱いこそ異なる(前者は非対応、後者は対応)が、「桁区切りコンマ」の扱いは両方とも対応している、という共通点がある。

**修正内容**: `dump_daemon/pad_action_lib/datatable.py`の`_csv_as_number()`で、`int()`/`float()`に渡す前にコンマを除去するようにした(`_as_number()`と同じパターン)。回帰テストを追加した。テスト用フロー・結果ファイルは保存せず削除し、実機状態をクリーンに戻した。これで知見92に残っていた数値変換関連の留保事項は全て解決し、`pad_add`/`pad_equal`/CSV読み込みの3箇所全てで桁区切りコンマを正しく扱えるようになった。

## 104. `+`/`=`演算子の数値文字列判定——前後の空白・明示的な`+`符号・先頭ゼロ省略の小数も数値として認識すると実機確認、新たな見逃しバグを発見・修正

知見101〜103の「数値を表す文字列」判定の境界確認を継続し、残っていた一般的なバリエーション(前後の空白・明示的な`+`符号・`.5`のような先頭ゼロ省略の小数)を実機確認した。`1 + $'''  5  '''`・`$'''  5  ''' = 5`・`1 + $'''+5'''`・`1 + $'''.5'''`を実行したところ、結果は**`6`・`True`・`6`・`1.5`**——4パターン全て数値として正しく認識された。

**確認できた事実**: `+`/`=`演算子の数値文字列判定は、前後の空白・明示的な符号・先頭ゼロ省略の小数という、一般的な数値表記のバリエーションを広く許容する——知見101の「指数表記のみを除外する」という理解を補強する結果になった。

**発見したバグ**: 知見101〜103で実装した`_NUMERIC_STRING_RE`(`^[+-]?[\d,]+(\.\d+)?$`)は、前後の空白を許容せず(`^`/`$`で厳密に囲まれ空白を含まない)、かつ先頭ゼロ省略の小数(`.5`、整数部が空)も`[\d,]+`が最低1文字を要求するため拒否していた——つまり`"  5  "`や`".5"`は実機では数値として認識されるにもかかわらず、現在の実装では文字列結合側にフォールバックしてしまう新たな見逃しバグだった。

**修正内容**: `dump_daemon/pad_action_lib/expr_runtime.py`の`_NUMERIC_STRING_RE`を`^\s*[+-]?([\d,]+\.?\d*|\.\d+)\s*$`に変更し、前後の空白と先頭ゼロ省略の小数の両方を許容するようにした(実際の数値変換自体はPythonの`int()`/`float()`が前後の空白を自然に許容するため、ゲート部分の修正だけで十分だった)。CSV読み込みサブシステム(`_csv_as_number()`)はそもそも事前のゲート(正規表現)を持たず`int()`/`float()`を直接試みる実装のため、この種の見逃しは最初から発生しない(確認のみ、変更不要)。回帰テストを追加した。テスト用フロー・結果ファイルは保存せず削除し、実機状態をクリーンに戻した。

## 105. 知見81の持ち越し課題を解決——`XOR`に数値オペランドを使うとPAD自身が静的検証エラーにする、`+`演算子は`Boolean`リテラルを数値として扱わない

知見81で「`XOR`の被演算子が常に比較式/真偽値リテラルだったため論理XORとして解釈したが、数値へのビット単位XORの可能性は未検証」として持ち越していた課題を実機確認した。`SET R1 TO 5 XOR 3`を貼り付け・保存を試みたところ、**ペースト自体はエラー無く受理されるが、PADデザイナー自身の静的検証で`"Parameter 'Value': Operand of type 'Numeric value' can't be part of an XOR condition."`というエラーになる**ことが判明した——つまり`XOR`は仕様として数値オペランドを許可しない(ビット単位XORという選択肢自体が存在しない)。これにより知見81の論理XOR解釈(`bool(a) != bool(b)`)が唯一の正しい実装であることが確定し、「数値へのビット単位XOR」という懸念は実機確認により完全に排除された——`pad_codegen`側のコード変更は不要。

**副産物の発見**: 同じ調査の過程で`+`演算子に`Boolean`リテラル(`True`/`False`)を渡すテストも行った。`SET R2 TO 1 + True`を実行したところ、結果は**`"1True"`**(文字列結合)——数値加算の`2`ではなかった。これはPythonの`bool`が`int`の部分型であるため、`_as_number()`の`isinstance(value, (int, float))`チェックが`True`/`False`も誤って数値として受理してしまう、という見逃しバグだった(`1 + True`をPythonで素朴に実行すると`2`になってしまう)。

一方で`SET R3 TO True = 1`を実行した結果は**`True`**(真)——`=`演算子は`Boolean`と数値の等価性を認める。ただしこれは`pad_equal()`の`a == b`早期判定(Pythonの`bool`/`int`比較が言語機能として`True == 1`を真にする)にそのまま捕まるだけであり、`_as_number()`経由の数値文字列変換ロジックには到達しないため、`_as_number()`から`bool`を除外しても`pad_equal()`のこの挙動には影響しない。

**修正内容**: `dump_daemon/pad_action_lib/expr_runtime.py`の`_as_number()`で`isinstance(value, bool)`を`isinstance(value, (int, float))`より先に判定し、`bool`の場合は`None`(数値として扱わない)を返すようにした。これにより`pad_add(1, True)`が正しく`"1True"`(文字列結合)になる。回帰テストを追加した。テスト用フロー・結果ファイルは保存せず削除し、実機状態をクリーンに戻した。これで知見81から持ち越していた最後の未検証項目(XOR数値オペランド)が解決した。

## 106. 知見93の留保事項(ヘッダー行のトリム対象可否)を実機確認——実装は既に正しかった

知見93で「ヘッダー行自体(`FirstLineContainsColumnNames: True`時の列名)もトリム対象になるかは直接確認しておらず、実装では一貫性のため同じ`.strip()`をヘッダー行にも適用しているが、これは推測の範囲内にとどまる」として持ち越していた項目を実機確認した。`SET CSV TO $''' Name , Age \n Alice , 30 '''`(ヘッダー行・データ行とも前後に空白)を`FirstLineContainsColumnNames: True`・`TrimFields: True`で読み込み、`ConvertDataTableToCSV`で書き戻したところ、結果は`"Name,Age\nAlice,30"`——**ヘッダー行もデータ行と同じくトリムされる**ことが確認できた。

既存の実装(`datatable_from_csv_text()`がヘッダー/データ行を区別せず、CSV全体に`.strip()`を一括適用してから先頭行をヘッダーとして切り出す処理)は、推測通りで既に正しかったため修正不要。コメント・テストのdocstringを「推測」から「知見106で実機確認済み」に更新するのみ。テスト用フロー・結果ファイルは保存せず削除し、実機状態をクリーンに戻した。

## 107. 知見98の鏡像——`FilterDataTable`の`NotEqual`型不一致挙動も実機確認、既に正しく実装済みと確定

知見98で確認した「`Equal`は型不一致の場合常に偽」の鏡像(`NotEqual`は型不一致の場合常に真)を実機確認した。知見98と同じ手法(`ReadFieldsAsText: False`で列を数値型(int)に変換したテーブル)に対し、`NotEqual "30"`(文字列)でフィルタしたところ、結果は**元のテーブルがそのまま残る**(行が除外されない)——つまり型不一致時は`NotEqual`が常に真と判定されることが確認できた。

既存の実装(`_filter_condition_matches()`の`"NotEqual"`分岐、`return True if type_mismatch else ...`)は decompile済みソースの`flag`判定通りで既に正しかったため修正不要。回帰テストを追加した。テスト用フロー・結果ファイルは保存せず削除し、実機状態をクリーンに戻した。

## 108. `Variables.IncreaseVariable`/`DecreaseVariable`の実際の演算方向を実機確認——既にテストで仮定していた加減算の意味論が正しいと確定

`codegen_coverage.py`で`Variables.IncreaseVariable`/`DecreaseVariable`が0/1(TODO)のまま残っていた理由を調査した。知見66/67で実機キャプチャした唯一の実物フィクスチャ(`tests/fixtures/tier1_text_variables_batch4.txt`)はバッチ自動化の汎用プレースホルダーで`Value: $'''sample'''`(文字列リテラル)になっており、`[Mutable]`な`Value`引数がVarRefでないため安全にTODOへ倒れる(知見66で確認済みの設計判断)。`tests/test_pad_codegen.py`の`test_generate_python_converts_increase_decrease_variable_with_real_variable_ref`は現実的なVarRef入力(`SET Counter TO 10`→`IncreaseVariable Value: Counter IncrementValue: 5`→`DecreaseVariable Value: Counter DecrementValue: 3`→期待値`12`)での合成DSLテストとして既に存在していたが、これは**仮定**(`increase_variable()`/`decrease_variable()`の実装が`value + increment`/`value - decrement`だろうという推測)の検証であり、実機Runでの確証はまだ無かった。

知見81の「Run実行+ファイル書き出し」手法を使い、まさにこのテストと同じDSL(`SET Counter TO 10`/`Variables.IncreaseVariable Value: Counter IncrementValue: 5`/`Variables.DecreaseVariable Value: Counter DecrementValue: 3`/`File.WriteText`で`%Counter%`を書き出し)を実機にペーストしてRunした結果、`Counter`は**`12`**(10+5-3)になった——既存の`pad_action_lib.variables_actions.increase_variable()`/`decrease_variable()`の実装(`value + increment`/`value - decrement`)、およびcodegen側の`{var} = variables_actions.{func}({var}, {amount})`という再代入パターンが、ともに実機の挙動と一致すると確定した。

修正は不要(既存実装が既に正しかった)。`test_generate_python_converts_increase_decrease_variable_with_real_variable_ref`のdocstringを「推測」から「知見108で実機確認済み」に更新した。テスト用フロー・結果ファイルは保存せず削除し、実機状態をクリーンに戻した。なお`codegen_coverage.py`のカウントは実物フィクスチャ(`tier1_text_variables_batch4.txt`)基準のため、この合成テストでの確証は0/1(TODO)の表示自体を変えない——これは文字列リテラルの`Value`に対しては書き戻し先が無いためTODOのままで正しい設計判断であり、真の未解決ではない。

## 109. `Compression.ZipFiles`/`UnzipFiles`のパスワード省略ケースを合成DSLで実行確認——既存の結線は正しく実装済みと確定(VM不要)

`pad_codegen/actions/compression.py`は自身のdocstringで「実機キャプチャでは`Password`が常にWindows DPAPI保護値(`P'<base64>'`、知見72)で現れ`VarRef`へフォールバックするため、本モジュールはパスワード無しの圧縮/展開フローのために結線だけ用意する」と明記していたが、その「パスワード無しの場合の結線」自体を実行して確認する合成テストが無かった(知見78のPDF`Password`省略ケースと同じパターン)。

`tempfile.TemporaryDirectory()`で実ファイルを用意し、`Compression.ZipFiles`(`ArchiveComment`のみ空文字列、`Password`省略)→実際にzipファイルが生成されることを確認→続けて`Compression.UnzipFiles`(`IncludeMask: '*'`・`ExcludeMask`省略)→展開結果が元のファイル内容と一致することを確認、という往復を合成DSLで実行するテストを追加した。`pad_action_lib.compression_actions.zip_files()`/`unzip_files()`(`pyzipper`経由のAES対応実装、zip-slip対策含む)・codegen側の結線(`_as_list_expr()`によるリスト/単一文字列の吸収含む)ともに既に正しく実装されていたため、コード修正は不要だった。VM不要(ローカルの`zipfile`/`pyzipper`のみで完結)。DPAPI保護値(`P'<base64>'`)自体の復号は依然未対応のまま(低優先度、pad_todo.md参照)。

## 110. `UIAutomation.Click.Click`の最後の未対応分岐——「Start Button」特殊擬似セレクタ(`:startbutton`)をWinキー押下へ結線(VM不要)

知見44で実機確認済みの通り、Windowsタスクバーの「Start Button」は`Attributes: []`(空)・`CustomValue: ":startbutton"`という予約済みの擬似セレクタで直列化され、通常のUIA属性ベースのセレクタが組み立てられないため、`_build_pywinauto_selector_expr()`は`None`を返し常にTODOへ倒れていた(`codegen_coverage.py`の`UIAutomation.Click.Click`が長らく6/7のPARTIALのままだった唯一の原因)。

`:startbutton`はPAD固有の推測ではなく**Windows自体の既知の仕組み**(Winキー押下でスタートメニューの開閉がトグルされる、OSの標準動作)に対応する固定の要素だと分かっているため、でっち上げたセレクタではなく確定した事実としてWinキー押下(`pyautogui.press('win')`、既存の`MouseAndKeyboard.PressReleaseKey`の`Win`→`'win'`マッピングと同じpyautoguiキー名)に対応付けられると判断した。`selectors.py`に`_is_start_button_element()`(リポジトリの該当エントリが`selectors[0]`に`custom_value == ":startbutton"`の要素1つだけを持つかを判定)を追加し、`actions/ui_element.py`の`UIAutomation.Click.Click`分岐で、既存の確証済みパラメータ組み合わせ(LeftClick/MiddleCenter/オフセット0)の判定の後、この特殊ケースを先にチェックして`pyautogui.press('win')`を生成するよう結線した。既存テスト(`test_generate_python_omits_selector_hint_for_special_pseudo_selector`)はTODOフォールバックを期待していたため、実際に結線されたコードをコンパイル・アサートする内容に更新した。`codegen_coverage.py`: 180/202→181/202(90%)。

## 111. `Cryptography.*`の鍵省略(DPAPI以外)ケースを合成DSLで実行確認し、`EncryptText`/`EncryptFromFile`/`DecryptText`/`DecryptToFile`/`HashTextWithKey`/`HashFromFileWithKey`を新規結線(VM不要)

知見109の`Compression.*`と全く同じパターンが`Cryptography.*`にも残っていた——実機キャプチャ(`tier1_crypto_database_batch7.txt`)では鍵パラメータ(`EncryptionKey`/`DecryptionKey`/`HashKey`)が常にWindows DPAPI保護値(`P'<base64>'`、知見72)で現れ`VarRef`へフォールバックするため常にTODOへ倒れていたが、`pad_action_lib.cryptography_actions`(AES-CBC・HMAC実装、decompile調査で確認済みの弱い既定動作も忠実に再現)自体は既に完全に実装済みで、`codegen`側の結線(`actions/cryptography.py`)がまだ`HashText`/`HashFromFile`(鍵無し)の2件しか無く、鍵付きの6件(`EncryptText`/`EncryptFromFile`/`DecryptText`/`DecryptToFile`/`HashTextWithKey`/`HashFromFileWithKey`)は分岐自体が存在していなかった。

鍵パラメータが(DPAPI保護ではなく)ふつうの変数参照の場合に結線が正しく動くことを、実際にEncryptText→DecryptTextの往復(平文が復元される)・EncryptFromFile→DecryptToFileの往復(実ファイルで)・HashTextWithKey(Python標準`hmac`モジュールでの直接計算と一致)を合成DSLで実行して確認する3つのテストを追加した。実機キャプチャで確認済みの非対称な命名(`EncryptText`は`PaddingMode`、`DecryptText`は`Padding`——同じ意味のパラメータ名が異なる、知見70で発見済みの実機の実際の挙動)・`KeySize`列挙値(`Bits256`等)の整数への対応付け(`_AES_KEY_SIZE_MAP`)もそのまま踏襲した。`codegen_coverage.py`の実物フィクスチャ基準の0/1表示自体は(DPAPI鍵のままのため)変わらないが、これは正しい設計判断であり真の未解決ではない(知見108・109と同じ構造)。

## 112. 【本プロジェクト最大級の発見】`P'<base64>'`(DPAPI保護値)の実際の復号に成功——`Sensitive`パラメータが恒久的に非対応ではなく「元のWindowsユーザー自身が実行する場合のみ」対応可能だと判明(VM不要・decompileとclipwire exec経由のリフレクションのみ・読み取り専用)

知見65以来「暗号化した環境でなければ復号不可能なため恒久的に非対応」と結論づけていた`Cryptography.*`/`Compression.*`の`Sensitive`引数(`P'<base64>'`)について、pad_todo.mdの「暗号化環境自体を模倣してテストする余地があるか」という持ち越し課題を実際に検証した。

**訂正できた誤った前提**: DPAPI(`CryptUnprotectData`)自体はWindowsユーザーのプロファイル(マスターキー)に依存するが、**対話的なRDPログインは必須ではない**——`clipwire exec`(Tailscale経由の非対話PowerShell/Pythonセッション、`tomoya_kaw`ユーザーとして実行)からでも、同じユーザーの別のDPAPI保護値なら復号できる可能性がある。実際に試した結果、`[System.Security.Cryptography.ProtectedData]::Unprotect($bytes, $null, 'CurrentUser')`は`"The data is invalid."`で失敗したが、これはRDPが無いからではなく**暗号化時に使われた追加のentropy(第2引数)を渡していなかったことが原因**だと判明した。

**entropy定数の特定**: `Get-ChildItem *.dll | ForEach { [Reflection.Assembly]::LoadFrom(...).GetTypes() | Where Name -eq 'DPApi' }`という1回のclipwire exec呼び出しで`Power Automate Desktop`フォルダ内の全DLLを総当たりし、`Microsoft.Flow.RPA.Desktop.Robin.Core.dll`の`Microsoft.Flow.RPA.Desktop.Robin.Core.Utilities.DPApi`クラスだと特定した。`ilspycmd`でこのDLLを逆コンパイルしたところ、`private static readonly byte[] EntropyBytes`という固定20バイトのentropy定数(コンパイル時埋め込み配列、ソース上は値が読めない形式)が使われていることが分かった——`[Reflection.Assembly]`でロードした型に対しリフレクションで`GetField("EntropyBytes", NonPublic|Static).GetValue(null)`を呼び、**実行時の実際の値を直接読み取る**ことで、ソースコードからは読めないこの定数値(Base64: `Sz6nr1A3YB/QAleuNWXcUrk8OOo=`)を取得できた。

**実際の復号に成功**: このentropy値+`DataProtectionScope.CurrentUser`で`tier1_crypto_database_batch7.txt`の実機キャプチャ済み`EncryptionKey: P'<base64>'`を復号したところ、`"sample"`(このバッチキャプチャで使われた汎用プレースホルダー文字列そのもの)が得られた——でっち上げではなく本物の復号に成功した。Python側でも`win32crypt.CryptUnprotectData(raw, entropy, None, None, 0)`(pywin32、既存の依存関係)で同じ結果が得られることをVM上の実venvで確認した(**引数順序に注意**: `CryptUnprotectData(DataIn, OptionalEntropy, Reserved, PromptStruct, Flags)`——entropyは2番目の位置引数であり、3番目ではない。最初に3番目に渡す誤りをしたまま気づかずVM確認を怠っていたら、全く異なる——しかし一見動きそうに見える——バグを埋め込んでいたところだった)。

**結論と実装**: `pad_dsl.types`に`DpapiSensitiveLiteral`型を追加し、`line_parser._resolve_value()`で`P'<base64>'`構文を(従来の`VarRef`フォールバックではなく)この型として認識するようにした。`pad_action_lib.cryptography_actions.decrypt_dpapi_sensitive_value()`(上記entropy定数+`win32crypt.CryptUnprotectData`、`win32crypt`が無い環境では`DpapiDecryptionError`を投げる)を新設し、`render_value()`がこの型を`cryptography_actions.decrypt_dpapi_sensitive_value('<base64>')`呼び出しへ変換するようにした。既存の`Cryptography.*`(知見111)/`Compression.*`(知見109)のcodegen結線は変更不要——`safe_render()`経由で自動的に実コードが生成されるようになった。`codegen_coverage.py`: 181/202→188/202(93%)、`Cryptography.*`6件・`Compression.ZipFiles`が一気にOKになった(`Compression.UnzipFiles`は別の理由——実機キャプチャに`=>`出力変数束縛が無い——で依然TODO)。

**重要な限界(でっち上げではない正しい制約)**: この復号は**元の値を作成したWindowsユーザー自身が生成スクリプトを実行する場合のみ**機能する(DPAPI CurrentUserスコープの原理上)——他人のPADフローのエクスポートを無関係なマシン/ユーザーで変換する場合は`DpapiDecryptionError`になる(でっち上げた平文を返すことは無い)。これは`pad2py`が主眼とする「自分の既存フローを自分のマシンでPythonへ移行する」用途とは完全に整合する。entropy定数は今回調査したPADビルドから抽出した値であり、将来の別バージョンで変更される可能性は否定できない(その場合も復号が例外で失敗するだけで、誤った平文は返らない)。

## 113. 知見57が持ち越していた`GetWindow`の他モード・`ByInstanceOrHandle`系アクションの選別子確認を試みたが、依然RDP必要と再確認(VM不要、結論は否定的)

知見57で「Get windowドロップダウンの他の選択肢」「他のByInstanceOrHandle系アクション(SetWindowStateByInstanceOrHandle等)の実機DSL」が未検証のまま持ち越されていたのを、知見80で確立した「アクション検索ボックスに検索語を入力し結果TreeItemのAutomationIdを一括読み取る」手法(RDP不要)で解決できないか試した。

`"Get window"`/`"window state"`/`"close window"`で検索したところ、いずれも**モジュール/アクションの基底名(`UIAutomation.GetWindow`/`UIAutomation.SetWindowState`/`UIAutomation.CloseWindow`等)しか得られず**、知見57で既に確認済みの`.GetUseTimeout`のようなセレクタ接尾辞(モード)は一切現れなかった——つまりこの検索結果は「アクション自体」の識別までしか見せず、追加する際に開く設定ダイアログ内のドロップダウンで選んだモードに応じてどのセレクタ接尾辞になるかは、ダイアログの中身を読まなければ分からない。知見82で確認済みの「新規ダイアログの内容読み取りはタイムアウトする」という制約にそのまま阻まれるため、この手法はこの種の問題には効かないと判明した。`GetWindow`の他モード・`BringWindowToFront: True`の意味論・`ByInstanceOrHandle`系の他アクションは、依然RDP必要のまま(知見80の手法はaction_idカタログ化には有効だが、同一action内の複数セレクタ変種の列挙には使えないという適用限界が明確になった)。

## 114. `Folder.GetSpecialFolder`(`pad_action_lib.folder_actions.get_special_folder()`)がWindows実行環境では常にクラッシュする潜在バグを発見・修正(VM確認付き)

`codegen_coverage.py`で`Folder.GetSpecialFolder`は唯一の実機キャプチャ値`DesktopDirectory`(→内部キー`"Desktop"`)に対して`[OK]`表示だったが、実装自体(`get_special_folder()`)を読み直したところ、`"Desktop"`キーの解決ロジックが**Linux専用のXDG環境変数**(`XDG_DESKTOP_DIR`)しか見ていないことに気づいた——生成スクリプトは常にWindows上で実行される前提(PAD自体がWindows専用)なので、`XDG_DESKTOP_DIR`はまず設定されておらず、実機のWindows上で実際にこのコードを実行すると常に`NotImplementedError`になる潜在バグだった(`codegen_coverage.py`の「実コードが生成できたか」という指標は、生成されたコードが実際のターゲット環境で動くかどうかまでは検証しないため、見逃されていた)。テストも一切無かった。

`win32com.shell.shell.SHGetFolderPath`(公開されたWindows APIのpywin32バインディング、PAD固有の推測ではない)+`win32com.shell.shellcon`のCSIDL定数を使い、`"Desktop"`/`"Documents"`/`"AppData"`キーを実際に解決できるようにした。VM上の実venvで直接確認したところ、**`CSIDL_MYDOCUMENTS`という属性は存在するが`SHGetFolderPath`に渡すと`com_error: The parameter is incorrect.`になる**(値が12で、本来の`CSIDL_CONNECTIONS`と食い違っている、pywin32側の既知の命名ゆれらしい)ことが判明し、正しく動く`CSIDL_PERSONAL`に修正した——実際にVMで検証しなければ気づかずバグを埋め込んでいたところだった(知見112のDPAPI実装の引数順序ミスと同種の教訓)。確認済み: `Desktop`→`C:\Users\<user>\Desktop`、`Documents`(`CSIDL_PERSONAL`)→`C:\Users\<user>\Documents`、`AppData`(`CSIDL_APPDATA`)→`C:\Users\<user>\AppData\Roaming`。`"Temp"`は`tempfile.gettempdir()`(クロスプラットフォーム標準)に統一した。

## 115. 【実機確認で既存バグを発見】`AddSequentialSuffix`の命名規則は`"(1)"`ではなく`"(2)"`から始まる——`Cryptography.DecryptToFile`/PDF抽出・結合アクションの既存実装を修正

`pdf_actions._add_sequential_suffix()`は「PADの`Utilities.GenerateLocalFileName`の正確な命名規則は未確認」として、`cryptography_actions._next_sequential_path()`と同じ"(1)"方式(Windows Explorerのコピー命名規則と同じ、素朴に推測していた規則)で近似していた。知見112で確立した「DLL総当たりリフレクションでクラス/メソッドを直接発見する」手法を応用し、`Microsoft.Flow.RPA.Desktop.Robin.Shared.Runtime.dll`の`Utilities.GenerateLocalFileName(directory, name)`を実際に特定、さらに**メソッド自体を直接リフレクションで呼び出す**(decompileして推測するのではなく、PADの実際のコンパイル済みロジックをそのまま実行して観測する、知見112のさらに一歩進んだ手法)ことで、推測ではなく確定的に正しい挙動を得た。

VM上で複数のディレクトリ状態を用意して直接呼び出した結果:
- 対象ファイルが存在しない → 変更無しでそのまま返す。
- 対象ファイルのみ存在(`"(1)"`等の数字付きファイルは無い) → **`"(2)"`を返す**(`"(1)"`は一切試さない)。
- 対象ファイル+`"(1)"`が存在 → やはり`"(2)"`を返す(`"(1)"`の有無は結果に影響しない)。
- 対象ファイル+`"(2)"`が存在 → `"(3)"`を返す。
- 対象ファイル+`"(1)"`+`"(2)"`+`"(3)"`が存在 → `"(4)"`を返す。

つまり実際の規則は「元ファイルを暗黙の`"(1)"`相当として数え、最初の候補は常に`"(2)"`から始め、以降は既存の数字付きファイルと衝突する限り1ずつ増やす」であり、Windows Explorer自身のコピー命名規則(`"(1)"`から始まる)とは異なる。`cryptography_actions._next_sequential_path()`・`pdf_actions._add_sequential_suffix()`の両方を修正し(`n=1`→`n=2`開始)、既存テスト(`"(1)"`を期待していた)を更新、新たに複数の数字付きファイルが既に存在するケースの回帰テストを追加した。

## 116. `DateTime.GetCurrentDateTime`の`Windows`タイムゾーンモード(知見65以来「対応表が無いため実装不可」としていた)を、PAD自身の埋め込み対応表をdecompileで発見して解決

知見65以来「Windowsタイムゾーン名→IANA名の対応表が無いと実装できないため、でっち上げた対応表は作らない」として`NotImplementedError`のままにしていた`get_current_datetime()`の`Windows`モードを、知見112・115で確立した「DLL総当たりリフレクション/decompileで実際のクラス・データを直接取得する」手法で解決した。

`Microsoft.Flow.RPA.Desktop.Modules.DateTime.Actions.dll`を逆コンパイルしたところ、`GetCurrentDateTime`アクションには`UseName()`で確認できる5つのセレクタ(`Local`=`TimeZoneMode.System`、`Current`=`Specific`、`Windows`=`Windows`、`CustomOffset`/`CustomTimeZone`=`Custom`の2バリアント)が存在すると判明した——**知見113で「action検索結果はダイアログ内で選ぶモードのセレクタ接尾辞までは見せない」と結論づけていたが、decompileされたソース上の`UseName()`呼び出しを直接読めば、ダイアログを一切開かずにこれら全セレクタ名が分かる**(知見113の限界は検索ボックス経由の手法固有のものであり、decompile自体の限界ではなかった)。

さらに`Windows`モードの実行ロジック(`DateTimeActions.GetCurrentDateTime()`)を読んだところ、`TimeZoneDictionary.GetMappedTimeZone(TimeZoneLocation.ToString())`で`TimeZoneLocation`列挙(141値、`PacificStandardTime`等スペース無しの名前)から実際のWindows `TimeZoneInfo.Id`文字列(`"Pacific Standard Time"`等)への対応表を経由し、`TimeZoneInfo.GetSystemTimeZones()`から一致するものを探していることが分かった。この`TimeZoneDictionary._timeZoneDictionary`は(DPAPIのentropy定数のようにコンパイル時埋め込みバイト配列ではなく)**ソース上にプレーンな`Dictionary<string,string>`リテラルとしてそのまま読める**141件の実データで、これをそのまま転記して`_TIME_ZONE_LOCATION_TO_WINDOWS_ID`とした(でっち上げではない、PAD自身の対応表)。

IANA名への変換は不要だと判明した——Windows `TimeZoneInfo.Id`文字列は、既存の依存関係である`pywin32`の`win32timezone.TimeZoneInfo(windows_id)`にそのまま渡せば正しい`tzinfo`として機能する。VM上の実venvで`win32timezone.TimeZoneInfo('Pacific Standard Time')`/`'Tokyo Standard Time'`を実際に使い、正しいUTCオフセット付き現在時刻が返ることを確認した。`get_current_datetime()`の`Windows`分岐を実装し直し、`win32timezone`が無い環境(非Windows)では明示的な`GetCurrentDateTimeError`になるようにした。既存テスト(`NotImplementedError`を期待)を更新し、未知の`TimeZoneLocation`のエラー・既知の値での実際のタイムゾーン変換(Windows専用、skipif付き)の両方をテストした。

`Current`(`Specific`の別名、`[Deprecated]`属性付き)・`CustomOffset`/`CustomTimeZone`セレクタの実機DSL直列化形式・`TimeZoneLocation`/`InputType`パラメータの実際のDSL表現はいずれも依然未確認のため、`pad_codegen`側の結線はまだ行わない(`pad_action_lib`層の実装自体が正しく動くようになったのみ)。

## 117. 知見57・113が持ち越していた`UIAutomation.GetWindow`の他モードを、decompileされたソース上の`UseName()`呼び出しを直接読んで解決(VM確認付き)

知見116で見つけた「decompileされたソース上の`UseName()`を直接読めばダイアログを開かずにセレクタ接尾辞が全て分かる」手法を`UIAutomation.Actions.dll`(既に取得済み)の`GetWindow`アクションに適用した。`GetWindowBase`クラスには3つの`ActionSelector`があると確認できた:

- `UIAutomation.GetWindow.Get`(`GetWindowMode.SpecificWindow`・`UseTimeout: False`固定) — `.GetUseTimeout`の兄弟セレクタで、`Timeout`パラメータ自体が存在しない(UI上で隠されているのではなく、選択された時点でパラメータ自体が別物になる)以外は完全に同一の構造。
- `UIAutomation.GetWindow.GetUseTimeout`(既知・知見57で実機確認済み)。
- `UIAutomation.GetWindow.GetForegroundWindow`(`GetWindowMode.ForegroundWindow`) — `Control`(UI要素参照)を一切使わない、`WindowTitle`/`WindowInstance`の2出力のみを持つ全く別の構造。

`.Get`は既存の`.GetUseTimeout`結線(知見57・81)をそのまま適用できる(action_idを追加するだけ)。`.GetForegroundWindow`は`win32gui.GetForegroundWindow()`(既存の依存関係pywin32)でHWNDを取得し`Desktop(backend="uia").window(handle=...)`でラップする方式を考案し、VM上の実venvで実際に実行して正しいフォアグラウンドウィンドウ(このtickでは`"Power Automate"`自身)が返ることを確認した。既存の合成テスト(`test_generate_python_from_get_window_foreground_mode_with_two_output_vars_compiles`、以前はTODOフォールバックを期待)を実コード生成を確認する内容に更新し、`.Get`用の新規合成テストを追加した。

副産物として、知見113の「`GetWindow`の他モードは依然RDP必要」という結論が誤りだったことも確定した——知見113は検索ボックス経由の手法固有の限界であり、decompileされたソースを直接読む(今回の手法)ならRDP不要で解決できる。`BringWindowToFront: True`時の意味論・`Timeout`の実際のポーリング挙動は、`Control`(UI要素)自体の実機動作観察が必要なため依然未確認のまま。

## 118. 知見117の手法を`CloseWindow`/`FocusWindow`にも適用——`GetWindow`と全く同じ3セレクタ構造だと判明、`.Close`/`.Focus`/`.FocusByInstanceOrHandle`を解決

`UIAutomation.Actions.dll`の同じ逆コンパイル結果の中で、`CloseWindow`/`FocusWindow`も`GetWindow`と**全く同じ3セレクタ構造**(`Control`ベース/`WindowInstance`ベース/`Title`+`Class`ベース)を持つと確認した:

- `CloseWindow`: `.Close`(`Control`)・`.CloseByInstanceOrHandle`(`WindowInstance`、知見57で既に実機確認・結線済み)・`.CloseByTitleClass`(`Title`/`Class`、結線済み)。
- `FocusWindow`: `.Focus`(`Control`)・`.FocusByInstanceOrHandle`(`WindowInstance`)・`.FocusByTitleClass`(`Title`/`Class`、結線済み)。

未結線だった3つ(`.Close`/`.Focus`/`.FocusByInstanceOrHandle`)のうち、`Control`ベースの2つ(`.Close`/`.Focus`)は知見56の`_build_pywinauto_selector_expr()`に`.close()`/`.set_focus()`を呼ぶだけで結線でき、`.FocusByInstanceOrHandle`は既存の`.CloseByInstanceOrHandle`と全く同じ`WindowInstance`(`VarRef`)パターンで`.set_focus()`を呼ぶだけで結線できた。

`.close()`/`.set_focus()`自体がpywinautoの標準APIとして実際に動くことを、Notepadを使ってVM上の実venvで確認した(`Desktop(...).window(title='Untitled - Notepad')`を`.set_focus()`後`.close()`し、`exists()`が`True`→`False`になることを確認)。実機キャプチャは無いため、`looptest_whole_subflow_with_get_window.txt`のDSL/リポジトリをaction_idだけ差し替えた合成テキストで3件のテストを追加した。

## 119. 【既存の出荷済みコードに実在したバグを発見】`MoveWindow`/`ResizeWindow`/`SetWindowState`にも`GetWindow`と同じ3セレクタ構造を発見、その過程でpywinautoに`move_window()`メソッド自体が無いという、以前からのバグを発見・修正

知見117・118の手法(decompileされたソース上の`UseName()`呼び出しを直接読む)を`MoveWindow`/`ResizeWindow`/`SetWindowState`にも適用したところ、これらも`GetWindow`/`CloseWindow`/`FocusWindow`と全く同じ3セレクタ構造(`Control`ベース/`WindowInstance`ベース/`Title`+`Class`ベース)を持つと確認した——未結線だった6つ(`MoveWindow.Move`/`MoveWindow.MoveByInstanceOrHandle`/`ResizeWindow.Resize`/`ResizeWindow.ResizeByInstanceOrHandle`/`SetWindowState.SetState`/`SetWindowState.SetStateByInstanceOrHandle`)を解決しようとした。

**その過程で、既に出荷済みだった`MoveWindow.MoveByTitleClass`/`ResizeWindow.ResizeByTitleClass`(`codegen_coverage.py`で`[OK]`表示されていた)の実装に、実際には存在しないpywinautoメソッド`.move_window(x=, y=)`/`.move_window(width=, height=)`を呼んでいるという実行時バグを発見した**。VM上の実venvでNotepadウィンドウに対し実際に`.move_window(x=100, y=100)`を呼んだところ`AttributeError: Neither GUI element (wrapper) nor wrapper method 'move_window' were found`になった——`dir(w.wrapper_object())`で確認したところ、UIAバックエンドの`WindowSpecification`には`maximize`/`minimize`/`restore`(`SetWindowState`系が使う、こちらは正しく動く)はあるが`move_window`/`resize`等の位置・サイズ変更メソッドは一切無い。知見114(Folder.GetSpecialFolder)と同種の「`codegen_coverage.py`は生成の成否しか見ず実行時の正しさは見ない」ことが原因で見逃されていたバグ。

正しい方式は`win32gui.MoveWindow(hwnd, x, y, width, height, repaint)`(既存の依存関係pywin32、常にx/y/width/height全てを要求する)で、VM上の実venvでNotepadを使い実際に動くことを確認した(移動時はサイズを、リサイズ時は位置を`win32gui.GetWindowRect()`で読み取って保持する)。`actions/_window_state.py`に共有ヘルパー`render_move_or_resize()`を新設し、既存の`MoveByTitleClass`/`ResizeByTitleClass`の実装をこれに差し替え、新規の6分岐(`Control`/`WindowInstance`ベース)もこれで結線した。生成されたコードの完全な実行パターン(`.wrapper_object().handle`→`win32gui.GetWindowRect()`→`win32gui.MoveWindow()`)もNotepadで実機確認済み(移動後にサイズが保持され、リサイズ後に位置が保持されることを確認)。既存の2テスト(誤った`.move_window()`呼び出しを期待)を更新し、新規6分岐の合成テストを追加した。

## 120. 【完全に未結線だった新規アクションを発見】`UIAutomation.SetWindowVisibility`(Windowsカテゴリ7アクション目、GetWindow等と同じ3セレクタ構造)を発見・結線

知見117〜119でカバーした`GetWindow`/`CloseWindow`/`FocusWindow`/`MoveWindow`/`ResizeWindow`/`SetWindowState`に続き、`UIAutomation.Actions.dll`の`[Action(Category = "Windows", ...)]`を全て洗い出したところ、7番目の兄弟アクション`SetWindowVisibility`が存在し、`pad_codegen`に一切(TODO分岐すら無く)結線されていないと判明した——知見117〜119と全く同じ3セレクタ構造(`SetVisibility`=`Control`ベース/`SetVisibilityByInstanceOrHandle`=`WindowInstance`ベース/`SetVisibilityByTitleClass`=`Title`+`Class`ベース)、`Visibility`列挙(`Visible`/`Hidden`)を実行時に`Visibility == Visibility.Visible`という真偽値へ変換するだけの単純なロジック。

pywinautoの`WindowSpecification`に`hide()`/`show()`相当のメソッドは無い(知見119と同種の確認、VM上の実venvで`dir(w.wrapper_object())`に`hide`/`show`/`visib`を含む名前が`get_show_state`/`is_visible`/`verify_visible`しかないことを確認)。`win32gui.ShowWindow(hwnd, win32con.SW_SHOW/SW_HIDE)`が実機で正しく動くことを、Notepadを`IsWindowVisible()`で確認しながらVM上の実venvで確認した(非表示→`0`、再表示→`1`)。`actions/_window_state.py`に`render_set_visibility()`を追加し、3セレクタ全てを結線、合成テストを3件追加した。

## 121. 同じ手法を条件式アクション`UIAutomation.IfWindow`にも適用——`IsOpen`/`IsNotOpen`/`IsFocused`/`IsNotFocused`それぞれに未結線の兄弟セレクタ8個を発見・解決(VM不要)

`UIAutomation.Actions.dll`内の全`[Action]`/`[ConditionAction]`/`[WaitAction]`属性クラス(14個)を洗い出し、`Windows`カテゴリ以外もチェックしたところ、条件式アクション`IfWindow`(`ConditionAction`)も知見117〜120と同じ3セレクタ構造を4モード(`IsOpen`/`IsNotOpen`/`IsFocused`/`IsNotFocused`)それぞれに持つ(計12セレクタ)と確認した——既存の`render_if_window_condition()`は`Control`ベースの4つしか結線しておらず、`ByInstanceOrHandle`/`ByTitleClass`の兄弟セレクタ(計8つ)が未結線だった。

ウィンドウ参照の取得元(`Control`経由のセレクタ式/`WindowInstance`のVarRef/`Title`+`Class`)が違うだけで、以降の`exists()`/`is_active()`という真偽値ロジックは完全に同一だと確認できたため、`render_if_window_condition()`をaction_idの接尾辞(`ByInstanceOrHandle`/`ByTitleClass`の有無)で分岐し、window式の組み立て方法だけを切り替える形に書き換えた。`exists()`/`is_active()`自体は既存の`Control`ベース4セレクタで既に実機確認済みのロジックの再利用のため、新たなVM確認は不要だった。16件のパラメトライズテストを追加した(既存4件+新規12件)。`UIAutomation.IfRemoteDesktopIsAvailable`(`IsDesktopAvailable`というランタイムプロキシ側の実装で、decompile済みDLL群には実体が無く意味論の確証が得られない)は、条件分岐の誤判定という最悪のでっち上げリスクがあるため今回は見送った。

## 122. 同じ手法を`Variables.Actions.dll`にも適用——`GenerateRandomNumber`の兄弟セレクタ`ListOfRandomNumbers`を発見、既存の`pad_action_lib`実装がそのまま使えると確認して結線(VM不要)

知見117〜121の「decompileされたソース上の`UseName()`呼び出しを直接読む」手法を`Variables.Actions.dll`にも適用したところ、`GenerateRandomNumber`アクションに`RandomNumber`(単一値、結線済み)の他に`ListOfRandomNumbers`(複数値、`GenerateMultipleNumbers: True`固定、`NumbersCount`/`AllowDuplicates`/`RandomNumbers`[リスト出力]を使う)という兄弟セレクタが存在し、未結線だったと判明した。

`pad_action_lib.variables_actions.generate_random_number()`を確認したところ、**元から`count`/`allow_duplicates`引数を持ち複数生成に完全対応済み**だった(既存の`RandomNumber`セレクタは単に`[0]`で先頭要素だけを取り出していただけ)——新規実装は一切不要で、codegenの結線を1分岐追加するだけで済んだ。合成DSLで実際に実行し、指定件数・重複無し・範囲内という3条件を満たすリストが返ることを確認するテストを追加した。

同じ`Variables.Actions.dll`には他にも`FindOrReplaceInDataTable`(8セレクタ中1つのみ結線——`ByColumnIndex`/`WithRegex`系7個が未結線)・`GenerateDataTableFromCSVAction`(3セレクタ中1つのみ結線——`ReadCustomSeparator`/`ReadFixedColumnWidths`が未結線)という同種の未結線セレクタ群が見つかっており、次の調査対象として記録する(対応する`pad_action_lib`関数の有無を要確認)。

## 123. `FindOrReplaceInDataTable`の未結線セレクタのうち、安全に解決できる2つ(`FindItemInDataTableWithRegexEverywhere`/`FindItemInDataTableByColumnIndex`)を結線——残り5つ(Replace系4つ+regex×列指定1つ)は意図的に見送り

知見122で見つけた`FindOrReplaceInDataTable`の8セレクタ構造(`SearchMode`: Find/FindAndReplace × `SearchBy`: Everywhere/OnColumn × `UseRegex`: True/False、一部組み合わせのみ実在)をdecompileで完全に把握した。このうち**Find系(DataTableを変更しない、`DataTableMatches`出力のみ)の2つ**を解決した:

- `FindItemInDataTableWithRegexEverywhere`(`UseRegex: True`固定、`MatchEntireCellContents`/`MatchCase`は選べない)。
- `FindItemInDataTableByColumnIndex`(`SearchBy: OnColumn`固定)——`ColumnNameOrIndex`パラメータは実機のPAD自体が文字列(列名)/数値(列インデックス、`int.TryParse`で判定)の両方を受け付けるが、**この層では列名のみに対応する**(列インデックスの0始まり/1始まり設定`_listIndexService.IsZeroBased`が未確認のため、安全側に倒して数値は非対応のまま)。

`find_item_in_datatable_everywhere()`に`use_regex`/`column`引数を追加して結線した(既存の`_cell_matches()`ヘルパーがそのまま使えた)。実機キャプチャが無いため`Variables.GenerateDataTableFromCSV`で実データを用意した合成DSLで実際に実行・確認するテストを追加した。

**残り5セレクタ(`ReplaceItemInDataTableEverywhere`/`ByColumnIndex`/`WithRegexEverywhere`/`WithRegexByColumnIndex`+`FindItemInDataTableWithRegexByColumnIndex`)は意図的に見送った**。decompileした`FindOrReplaceInDataTable.Execute()`を読むと、既存の`pad_action_lib.find_or_replace_in_datatable()`には複数の未確認・未実装のギャップがあると判明した: (1) `AllMatches: False`の早期停止が無い、(2) Replace時も`DataTableMatches`を出力するはずだが現在の実装は置換件数の`int`を返すだけ、(3) 置換後のセル型を元の型(int等)へ戻す処理(`Converter.ConvertToType`)が無く常に文字列になる。これらを実機未検証のまま埋めると、DataTableを実際に書き換える処理で誤った結果をでっち上げるリスクが高い(Findのみの読み取り専用操作より一段と危険)ため、今回は見送り、ギャップの詳細を記録するに留めた。

## 124. 【本tick最大の発見】`AddRowToDataTable`の`RowToAdd`が実際には`List`であり、`pad_action_lib.add_row_to_datatable()`の既存実装(`dict(row)`)はクラッシュする潜在バグだったと判明——知見90・91等の「Tier1アクションだけでDataTableを組み立てる」手法が実は`pad_action_lib`層を経由する変換では一度も検証されていなかったと確定

知見123の調査中、`FindOrReplaceInDataTable`のテスト用DataTableを知見90・91と同じ「`CreateNewDatatable`+`AddColumnToDataTable`+`CreateNewList`+`AddItemToList`+`AddRowToDataTable`」というTier1アクションの組み合わせで組み立てようとしたところ、生成されたPythonコードを実際に`exec()`すると**`add_row_to_datatable()`内の`dict(row)`が`ValueError: dictionary update sequence element #0 has length N; 2 is required`でクラッシュする**ことを発見した。

**根本原因**: `Microsoft.Flow.RPA.Desktop.Modules.Variables.Actions.dll`を逆コンパイルして確認したところ、`AddRowToDataTable.RowToAdd`は実際には**`List<object>`**であり、`DataRow.ItemArray = RowToAdd.ToArray()`という**列の並び順による位置対応**で行に追加される(辞書のキー対応ではない)。`pad_action_lib.add_row_to_datatable()`の型ヒントは`row: Row`(`dict[str, object]`)で、実装も`table.append(dict(row))`——`row`が辞書でなければ必ず失敗する。

**この重大な事実**: 知見90・91・97・98・99・107・111等で繰り返し使ってきた「`CreateNewDatatable`+`AddColumnToDataTable`+`CreateNewList`+`AddItemToList`+`AddRowToDataTable`だけでTier1アクションのみからDataTableを組み立てる」という実機検証手法は、**実機のPAD自身の実行エンジン**(C#/.NETのネイティブ実装)を使って**実機確認**するためのものであり、`pad_action_lib`(このPythonポート)を経由した**codegen→生成Python実行**の往復では一度も検証されていなかった。つまり、`FilterDataTable`/`JoinDataTable`の入力スキーマ自体の確証(知見90・91)は正しいが、「そのスキーマをPython側でTier1アクションのcodegenから実際に組み立てる」という変換のテストカバレッジには、今回発見まで大きな穴があった。

**今回の修正(部分的)**: `add_row_to_datatable()`を、`row`が`list`の場合は`columns_of(table)`(既存の行から推測した列順序)と位置で対応付けて辞書に変換するよう修正した。**ただしこの`DataTable`表現(列順序を各行の辞書のキー順序で保持する、`datatable.py`モジュールdocstring参照)には列だけを独立して追跡する仕組みが無いため、行が1件も無い状態(`AddColumnToDataTable`だけ呼ばれた直後)で`list`形式の`RowToAdd`を渡すと列名が全く分からず解決不能**——この場合はでっち上げた列名を使わず明示的な`ValueError`にするよう変更した(以前の`dict()`の分かりにくいクラッシュより改善したが、根本的には未解決)。

**残る構造的課題(design/pad_todo.mdに記録)**: 「空のDataTableに`AddColumnToDataTable`で列を追加した直後に`AddRowToDataTable`で最初の行を`List`で追加する」という、知見90・91のVM検証で繰り返し使ったパターン自体は、**現在のDataTable表現では原理的に解決不能**——真に解決するには`DataTable`を「行のリスト」ではなく「列名リスト+行のリスト」を持つ型に再設計する必要があり、`datatable.py`・`variables_actions.py`の広範囲に影響する大きな変更になる。今回は影響範囲の大きさから見送り、明示的なエラーメッセージへの改善のみ行った。

## 125. 知見124の穴を塞ぐ——`FilterDataTable`/`JoinDataTable`の`pad_codegen`→`pad_action_lib`end-to-end実行テストを初めて追加、パイプライン全体が正しく動くことを確認(VM不要)

知見124で「`FilterDataTable`/`JoinDataTable`の入力スキーマ自体(知見90・91)はPAD実機で確認済みだが、そのスキーマをPython側のcodegenから実際に組み立てて実行するテストが一度も無かった」と判明したため、この穴を実際に塞いだ。

`AddRowToDataTable`経由でテーブルを組み立てる方法は(知見124の通り)空テーブルへの最初の行追加ができないため使えないが、`Variables.GenerateDataTableFromCSV`でCSVテキストから直接テーブルを種付けする経路(`AddColumnToDataTable`を経由しない、これ自体は以前から正しく結線済み)を使えば回避できる。この経路で、知見90の確認済み例(`Age Equal 30`で`Carol`のみ残る)・知見91の確認済み例(`Name`列で`Inner`結合、重複列名に`" (2)"`付与)をそのままDSL化し、`generate_python()`→実際の`exec()`まで通して確認するテストを2件追加した。

**結果**: 両方とも一発で正しく動いた——`filter_datatable()`/`join_datatable()`自体のロジック、`safe_render()`による`FilterParameters`/`JoinParameters`VarRef渡し、`GenerateDataTableFromCSV`の`CSVTable`出力との組み合わせは、知見124で見つかった`AddRowToDataTable`固有の問題とは独立して正しく機能することが確認できた。これにより「`FilterDataTable`/`JoinDataTable`自体の実装は健全、穴は`AddRowToDataTable`での組み立て経路のみ」という、知見124の切り分けを裏付けることができた。

## 126. 知見124の横展開——`ModifyDataTableItem`も実機では`ColumnNameOrIndex`が列名/列インデックスの両対応だが、`pad_action_lib`側に知見123と同種の未対応ガードが無かったサイレントなバグの芽を発見・修正(VM不要)

知見124・125で「DataTable操作系はPAD実機の実引用型とpad2py側の想定がずれていないか」を疑って横展開した結果、`Microsoft.Flow.RPA.Desktop.Modules.Variables.Actions.dll`の`ModifyDataTableItem.Execute()`を再確認したところ、`ColumnNameOrIndex`は`FindOrReplaceInDataTable`(知見123)と全く同じパターン——`string`型で受け取り、`int.TryParse(ColumnNameOrIndex, out result)`が成功すれば`_listIndexService.ConvertInput(result)`で列インデックスとして解釈し`DataTable.Rows[num2][num.Value]`(位置アクセス)、失敗すれば列名として`DataTable.Columns[ColumnNameOrIndex]`相当の名前アクセスを行う、という二重解釈をしていると確認した。

知見123では`FindItemInDataTableByColumnIndex`について「実機の0始まり/1始まり設定`_listIndexService.IsZeroBased`が未確認のため数値は非対応のまま」と明示的に判断・docstringに記録していたが、`pad_action_lib.modify_datatable_item(table, row_index, column, value)`(`table[row_index][column] = value`という辞書キー直接代入)には**この種のガードが一切無かった**——数値文字列の`ColumnNameOrIndex`(例: `"1"`)が渡された場合、本来は列インデックスとして解釈すべきところを、単にキー名`"1"`の列への代入として処理してしまう(たまたまそういう名前の列があれば意図通りに見えてしまうが、実際には別の意味論)。これは知見124の「生成コードが実際に実行されたことのないパスには想定外の型ギャップが隠れている」という教訓が、別のDataTable系アクションにも当てはまる具体例だった。

**修正**: `modify_datatable_item()`の先頭に、`column`が(符号付きの)数字のみで構成される場合に`ValueError`を投げるガードを追加した。知見123の判断(IsZeroBasedが未確認である限り、でっち上げた解釈をするより明示的なエラーを優先する)をそのまま再利用し、新規のVM検証は不要だった。`tests/test_pad_action_lib_variables.py`に`test_modify_datatable_item_rejects_numeric_column_index`を追加して回帰を防止した。

**教訓**: 「同じDLL内の同種パラメータ(`ColumnNameOrIndex`という名前そのもの)が複数のアクションで再利用されている場合、1つのアクションで発見したサイレントな型ギャップは、同じDLL内の他のアクションにも横展開して確認する価値がある」——`pad_todo.md`の個別アクション単位のTODO潰しだけでなく、こうした「パラメータ名の再利用パターン」を軸にした横断チェックも、まだ見つかっていないギャップを拾える有効な手法として記録する。

## 127. `GenerateDataTableFromCSV`/`ConvertDataTableToCSV`の`ColumnsSeparator`が`SystemDefault`以外(Comma/Semicolon/Tab)で常にTODOへ倒れていたゲートを解消し、両方の`CustomColumnsSeparator`兄弟セレクタ(`ReadCustomSeparator`/`DataTableToCSVCustomSeparator`)も新規結線(VM上のリフレクション直接呼び出しで確認)

知見125終了時に次の調査対象として記録していた`GenerateDataTableFromCSVAction`の未結線セレクタ(`ReadCustomSeparator`/`ReadFixedColumnWidths`)を調査した。`Microsoft.Flow.RPA.Desktop.Modules.Variables.Actions.dll`を逆コンパイルすると、この両方に加えて**既存の`ReadPredefinedSeparator`自体にも見落としがあった**と判明した——`pad_codegen/actions/variables.py`の既存実装は`ColumnsSeparator`が`"SystemDefault"`以外(`Comma`/`Semicolon`/`Tab`)の場合も常に`None`(TODO)を返していたが、これは単なる実装の手抜きであり、実機の`ReadPredefinedSeparator`セレクタ自体はこの3値もそのまま受け付ける。同じ`ColumnsSeparator`列挙型は`Variables.ConvertDataTableToCSV.DataTableToCSVCommonSeparator`でも使われており、そちらも同じゲート漏れだった。

**列挙型の実体確認(VM上のリフレクション直接呼び出し、decompile単独では不十分だったケース)**: `CSVColumnsSeparator`/`CSVColumnsSeparatorType`/`CSVSeparator`は`Variables.Actions.dll`ではなく共有の`Microsoft.Flow.RPA.Desktop.Modules.Text.Utilities.dll`に定義されていた(`Get-ChildItem *.dll`を`Power Automate Desktop`インストールディレクトリの非再帰(直下)で実行して特定——再帰的な全件`LoadFrom`は`dotnet`ランタイムや多数の言語リソースフォルダを含むため実行時間が長すぎてタイムアウトした、という新たな運用上の注意点も確認)。`CSVColumnsSeparator`列挙値は`SystemDefault=0`/`Comma=1`/`Semicolon=2`/`Tab=3`。実際の区切り文字は`CSVSeparator(CSVColumnsSeparator)`コンストラクタをVM上で直接呼び出し(`[Activator]::CreateInstance`)、`.Separator`プロパティを読み取って確認した: `SystemDefault`→`","`(確認したVMの環境では`Comma`と同じ——`SystemDefault`自体はOSカルチャ依存の「リスト区切り文字」であり、別ロケールでは`Comma`と異なる可能性は残るが、この限界は既存のpad2pyの既定値(`delimiter=","`)にも元から内在していたもので今回新たに持ち込んだものではない)、`Semicolon`→`";"`、`Tab`→`"\t"`。

`CSVColumnsSeparatorType`列挙値は`Predefined=0`/`Custom=1`/`FixedColumnWidths=2`——これはDSL上の`ColumnsSeparatorType`パラメータとしては現れず(action_idのセレクタ接尾辞自体がこの3値のどれかを固定する、知見116以降で確立した「decompileされたセレクタの`ShouldBe()`呼び出しを読む」パターンそのもの)、`GenerateDataTableFromCSVAction`は`ReadFromCSVPredefinedSeparatorSelector`(`UseName("ReadPredefinedSeparator")`)/`ReadFromCSVCustomSeparatorSelector`(`UseName("ReadCustomSeparator")`)/`ReadFromCSVFixedColumnWidthsSelector`(`UseName("ReadFixedColumnWidths")`)の3セレクタを持つと確認した。`ConvertDataTableToCSVAction`は`DataTableToCSVCommonSeparatorSelector`/`DataTableToCSVCustomSeparatorSelector`の2セレクタ(書き込み側はFixedColumnWidthsに相当する選択肢が無い)。

**今回の修正**: `pad_codegen/actions/_support.py`に`CSV_PREDEFINED_SEPARATOR_TO_DELIMITER`辞書(4値のマッピング)を追加し、`ReadPredefinedSeparator`/`DataTableToCSVCommonSeparator`の`separator != "SystemDefault"`ゲートを撤廃してこの辞書で実際の区切り文字へマッピングするよう修正した。さらに新規に`Variables.GenerateDataTableFromCSV.ReadCustomSeparator`/`Variables.ConvertDataTableToCSV.DataTableToCSVCustomSeparator`の2ブランチを追加し、`CustomColumnsSeparator`パラメータをそのまま`delimiter`引数として渡すよう結線した。`pad_action_lib.datatable.py`の`datatable_from_csv_text()`/`datatable_to_csv_text()`は元から`delimiter`引数を持っていた(既存実装は単に`pad_codegen`側がそれを渡していなかっただけ)ため、`pad_action_lib`側の変更は一切不要だった。

**見送った項目**: `ReadFixedColumnWidths`(固定長カラム読み込み)は、`csv.reader`ベースの現在の`datatable_from_csv_text()`実装とは根本的に異なるアルゴリズム(文字位置による分割)が必要であり、`FixedColumnWidths`文字列のフォーマット(`CSVUtilities.TryParseColumnWidths`で解析、おそらく`"10,20,15"`のようなカンマ区切りの幅リスト)の正確な意味論を今回は検証していないため、知見123・124と同じ「不確実なアルゴリズムを実装するよりTODOのまま残す」判断で見送った。次の調査対象として`pad_todo.md`に記録する。`File.ReadFromCSVFile`/`File.WriteToCSVFile`も同じ`ColumnsSeparator`列挙型を使っており、同種のゲート漏れ(`separator != "SystemDefault"`固定)が残っている可能性が高いが、今回は`File.Actions.dll`を未デコンパイルのため確認せず、次の調査対象として記録する。

テストは`tests/test_pad_codegen.py`に5件(`ReadPredefinedSeparator`のSemicolon/Tab、`ReadCustomSeparator`、`DataTableToCSVCommonSeparator`のSemicolon、`DataTableToCSVCustomSeparator`)を追加し、全て実際に`exec()`してDataTable/CSVテキストの内容を検証した。既存の`tests/test_pad_codegen_tier1_actions.py`2件(`datatable_to_csv_text`/`datatable_from_csv_text`呼び出しの期待文字列)も、新たに`delimiter=','`が追加されるようになった生成コードに合わせて更新した。

## 128. 知見127の横展開——`File.ReadFromCSVFile`/`File.WriteToCSVFile`も同じ`CSVColumnsSeparator`列挙型を使っており、同種のゲート漏れと未結線の`CustomSeparator`兄弟セレクタが存在すると確認・解消(VM不要、リフレクションのみ)

知見127で見送った「`File.Actions.dll`は未デコンパイルのため未確認」という次の調査対象をそのまま実施した。VM上に`File.Actions.dll`のコピーを置いて直接リフレクションで型を列挙したところ、`ReadFromCSVFileAction`/`WriteToCSVFileAction`の`ColumnsSeparator`プロパティの型が**`Variables.Actions.dll`やこのファイル自身とは無関係に、知見127で特定した`Microsoft.Flow.RPA.Desktop.Modules.Text.Utilities.dll`の`CSVColumnsSeparator`型そのもの**(`PropertyType.Assembly.FullName`で確認、同一アセンブリ)であると確認した——つまりモジュールをまたいで共有される列挙型であり、知見127で確立した`CSV_PREDEFINED_SEPARATOR_TO_DELIMITER`マッピングをそのまま再利用できる。

**セレクタのaction_id接尾辞の確認方法(新しい小技)**: これまで(知見116以降)はdecompileされたソースの`base.UseName("...")`呼び出しを目で読んで接尾辞を確認していたが、今回は`File.Actions.dll`のdecompileをまだしていなかったため、代わりに**`ActionSelectorBase.ActionName`プロパティをインスタンス化して直接読み取る**手法を使った(`[Activator]::CreateInstance($selectorType)`→`.ActionName`)。これはdecompile無しでも機能し、確認できた接尾辞は既知の`ReadCSV`/`WriteCSV`(知見66のフィクスチャと一致)に加え、新規に`ReadCSVWithCustomSeparator`/`ReadCSVWithFixedColumnWidths`/`WriteCSVWithCustomSeparator`の3つ。

**修正**: `pad_codegen/actions/file.py`の`File.ReadFromCSVFile.ReadCSV`/`File.WriteToCSVFile.WriteCSV`から`separator != "SystemDefault"`ゲートを撤廃し`CSV_PREDEFINED_SEPARATOR_TO_DELIMITER`でマッピング、新規に`File.ReadFromCSVFile.ReadCSVWithCustomSeparator`/`File.WriteToCSVFile.WriteCSVWithCustomSeparator`の2ブランチを追加した。`pad_action_lib.file_actions.read_from_csv_file()`/`write_to_csv_file()`も知見127の`datatable.py`と同じく元から`delimiter`引数を持っていたため、`pad_action_lib`側の変更は不要だった。`ReadCSVWithFixedColumnWidths`は知見127と同じ理由(固定長パース未実装)で見送った。

`tests/test_pad_codegen.py`に2件(`tempfile.TemporaryDirectory()`で実ファイルへの書き込み→読み込みの往復を検証、Semicolon/CustomSeparator各1件)、`tests/test_pad_codegen_tier1_actions.py`の既存アサーション1件を更新した。

## 129. `Compression.ZipFiles`の`ZipFile`出力が常に`None`になる潜在バグを発見・修正——「実際に`exec()`する」テストでも代入先の値を一度も検証していなかった死角

知見127・128の作業中、`codegen_coverage.py`で`Compression.UnzipFiles (0/1)`がTODOのままだった理由を再確認していたところ(実機キャプチャに`=>`出力束縛自体が無いという既に知見112で判明・了承済みの理由だった、知見124参照)、隣接する`Compression.ZipFiles`の既存コードを読み直して**別の、これまで誰も気づいていなかった実バグ**を発見した。

`pad_action_lib.compression_actions.zip_files()`は型ヒント`-> None`で、実際に`return`文を一つも持たず常に`None`を返す。一方`pad_codegen/actions/compression.py`は`{node.output_var} = compression_actions.zip_files(...)`という**代入文**を生成する——つまり実機で`ZipFile=> 変数名`を束縛したフローをpad2pyで変換すると、生成されたPythonを実行した時点でその変数は常に`None`になる。既存の合成テスト(`test_generate_python_from_compression_zip_unzip_without_password_converts`)は`ZipFile=> ZipFile`を実際に束縛して`exec()`までしていたが、アサーションは`archive_path.is_file()`(zipファイルが実際に作られたかという副作用)だけで、**`namespace["ZipFile"]`の値そのものは一度も検証していなかった**——知見124・128と同じ「実際に実行するテストを書いても、代入先の値を見ていなければ`None`化のような静かなバグは素通りする」という死角のもう一つの実例。

**実機確認(VM上の直接呼び出し、decompile不要)**: `Microsoft.Flow.RPA.Desktop.Modules.Compression.Actions.dll`の`ZipFiles`クラス(action名とは違い実クラス名に`Action`接尾辞は無い)を`[Activator]::CreateInstance()`でインスタンス化し、`ArchivePath`/`FilesOrFoldersToZip`/`CompressionLevel`/`ArchiveComment`プロパティを`FileObject(string)`コンストラクタ経由でリフレクションから直接設定、`Execute(null)`を直接呼び出して(`ActionContext`は未使用で済んだ)実際にzipファイルを作成させた。実行後の`ZipFile`プロパティ(`FileObject`型)の`.FullName`を読み取ると、渡した`ArchivePath`と**全く同じパス文字列**だった——つまり`ZipFile`出力は単なる`ArchivePath`のecho。

**修正**: `zip_files()`の戻り値型を`str`に変更し、末尾に`return archive_path`(入力をそのまま返す、でっち上げた正規化処理は追加しない)を追加した。`pad_codegen`側の既存の代入文生成はそのまま正しく機能するようになる(コード変更不要)。既存の合成テストに`assert namespace["ZipFile"] == str(archive_path)`を追加し、`tests/test_pad_action_lib_compression.py`の基本往復テストにも同様のアサーションを追加した。

**教訓(知見124・128と合わせて確定)**: 「生成コードを実際に`exec()`するテスト」であっても、副作用だけを検証して代入先の変数の値を見ていなければ、戻り値の型不一致(`None`化)のようなバグは検出できない——今後の同種レビューでは、出力変数を束縛するテストでは必ずその変数の値も具体的にアサートする。

## 130. 知見129の横展開中に発見した、`Folder.Copy`のより重大な2段のバグ——`CopiedFolder`出力の`None`化(知見129と同種)に加え、`Destination`パラメータの意味論自体が実機と逆だった(コピー先の正確なパスではなく既存の親フォルダ)

知見129のパターン(`-> None`で常に`None`を返す関数をcodegenが代入文に使っている)を機械的に横展開するため、`dump_daemon/pad_action_lib/*.py`内の全ての`-> None`なトップレベル関数を列挙し、`pad_codegen/actions/*.py`側で`{node.output_var} = module.func(...)`という代入に使われているものをスクリプトで突き合わせた(VM不要、ローカルのgrep/正規表現のみ)。該当したのは`folder_actions.copy_folder()`1件のみ。

**VM上の直接呼び出しで確認した実機の挙動(2点とも事前の想定と異なっていた)**:
1. `CopiedFolder`出力は知見129のZipFilesと同種の「結果の場所を指すecho」だが、
2. **`Destination`パラメータの意味論自体が、既存の`pad_action_lib.copy_folder()`の想定(コピー先の正確なパス、`dst.parent`が存在すればよい)と逆だった**——実機の`CopyFolder`クラスを直接インスタンス化・`Execute(null)`を呼び出して検証したところ、(a) `Destination`自体が存在しないと`ActionException`(「Destination folder ... doesn't exist」)になる(**親ではなく`Destination`自身**の存在が必須)、(b) 実際のコピー結果は`Destination`直下に**`Folder`(コピー元)と同じ名前のフォルダとしてネストされる**(Unixの`cp -r source dest/`と同じ、`shutil.copytree(src, dest)`が想定する「destは正確な新パス」という意味論とは違う)、(c) `CopiedFolder`出力はこのネストされたパス(`Destination/<元の名前>`)を指す。`IfFolderExists`(DoNothing/Overwriteの2値)はこのネストされた結果フォルダ内でのファイル単位の上書き判定で、既存の`_copy_function`のファイル単位ロジックとは整合していた(この部分は元から正しかった)。

これは知見124・128・129と並ぶ「実際に本番ロジックのパスを通るテストが一度も無かったため発覚が遅れた」系のバグだが、知見129より一段深刻——単に出力変数が`None`になるだけでなく、**コピー先のディレクトリ構造自体が実機と異なる場所になる**(1階層分フラット化されてしまう)。既存の`tests/test_pad_action_lib_folder.py`の`test_copy_folder_recursive`はこの誤った「destは正確なパス」という前提のまま書かれていたため、このバグを一度も検出できなかった。

**修正**: `copy_folder()`を実機の意味論に合わせて書き直した——`destination`自体の存在を検証(`dst.parent`ではなく)、実際のコピー先を`Path(destination) / Path(source).name`に変更、戻り値として`str(dst)`(ネストされた結果パス)を追加。既存テストを新しい意味論(`dst_parent`は事前に存在させる、結果は`dst_parent / "src"`)に書き直し、`destination`自体が存在しない場合に`InvalidDestinationFolderError`になる新規テストを追加した。`pad_codegen/actions/folder.py`側の代入文生成は変更不要(元から`{output_var} = folder_actions.copy_folder(...)`で正しい形だった)。`tests/test_pad_codegen.py`に実際に`exec()`してネストされたパスとファイル内容の両方を検証するend-to-endテストを追加した。

**横展開の手法として記録**: 「`-> None`で常に`None`を返す関数が、codegen側で代入文(`{var} = func(...)`)に使われていないか」という機械的な突き合わせは、decompileもVMも使わずローカルのみで完結する低コストな監査であり、知見129のような潜在バグを体系的に見つけ出せる(今回は該当1件のみだったため横展開はこれで打ち切り)。

## 131. 知見130で見送った次の調査対象——`Folder.Move`も`Destination`パラメータの意味論が実機と逆だったと確認(`MovedFolder`出力自体は元々`None`化バグは無かった)

知見130の末尾で記録した「`Folder.Move`等、他のアクションも`Destination`的なパラメータが『正確なパス』か『既存の親フォルダ』かの意味論を同様に取り違えている可能性がある」を直接検証した。VM上で`MoveFolder`クラスを直接インスタンス化・`Execute(null)`を呼び出したところ、`CopyFolder`(知見130)と**全く同じパターン**だと確認した: `Destination`自体が存在しないと`ActionException`になり、結果は`Destination`直下に`Folder`と同じ名前でネストされ、`MovedFolder`出力はこのネストされたパスを指す。`MoveFolder`には`IfFolderExists`に相当するパラメータが無いこと(実機のプロパティ一覧で確認済み)も確認した。

`pad_action_lib.folder_actions.move_folder()`自体は`-> str`で元から戻り値を返していたため知見129・130のような`None`化バグは無かったが、`destination`の意味論(「存在してはいけない正確な新パス」という既存実装の前提)が実機と完全に逆だった——つまり実機のPADフローを変換すると、現行実装では本来成功すべき移動が「destination already exists」という誤ったエラーになる(逆に、本来エラーになるべき「destinationの親フォルダが存在しない」ケースはチェックされず`shutil.move()`の分かりにくいエラーに委ねていた)。

**修正**: `move_folder()`を`copy_folder()`と同じ構造に合わせて書き直した——`destination`自体の存在を検証(存在しなければ`InvalidDestinationFolderError`)、実際の移動先を`Path(destination) / Path(source).name`に変更、ネストされた移動先が既に存在する場合のみ`MoveFolderError`(従来の「上書きオプションが無い」チェックをネスト先に適用し直した)。既存テストを新しい意味論に書き直し、`destination`自体が存在しない場合の新規テストも追加した。`tests/test_pad_codegen.py`に実際に`exec()`してネストされたパス・移動元の消滅・ファイル内容を検証するend-to-endテストを追加した。

この2件(知見130・131)で`Folder.*`モジュール内の「既存の親フォルダに同名でネストする」という`Destination`系パラメータの意味論パターンは出尽くした——`Folder.Rename`は`new_name`(同じ親フォルダ内での改名)で同種のパラメータを持たないため対象外、`Folder.Create`/`Folder.Delete`/`Folder.Empty`も`Destination`的なパラメータを持たない。

(知見130・131の調査中、`File.Copy`/`File.Move`の`copy_files()`/`move_files()`も同じ`Destination`系パラメータを持つため横展開で確認したが、こちらは元から正しく「既存の親フォルダへファイル名でネスト」する実装・既に戻り値も実際にアサートするテスト済みだったため、修正不要と確定した。)

## 132. 知見122・127・128で繰り返し見送っていた`ReadFixedColumnWidths`/`ReadCSVWithFixedColumnWidths`(固定長カラムCSV)を、`CSVUtilities`のVM上直接呼び出しで仕様を完全に解明して新規結線

`Variables.GenerateDataTableFromCSV.ReadFixedColumnWidths`/`File.ReadFromCSVFile.ReadCSVWithFixedColumnWidths`は、知見122で最初に発見されて以降、知見127・128で「`FixedColumnWidths`文字列のフォーマット(`CSVUtilities.TryParseColumnWidths`の正確な解析規則)が未検証」という理由で繰り返し見送られていた唯一の残課題だった。知見112・115と同じ「decompileだけでは読めない実行時のロジックを、VM上でメソッドを直接呼び出して確認する」手法で、この最後の穴を塞いだ。

**`FixedColumnWidths`文字列の構文(`Microsoft.Flow.RPA.Desktop.Modules.Text.Utilities.dll`の`CSVUtilities.TryParseColumnWidths(string, out int[])`をVM上で直接呼び出して確認)**: カンマ・空白のいずれか(連続も可)で区切る——`"10,20,15"`/`"10, 20, 15"`/`"10 20 15"`は全て`[10, 20, 15]`になり、`"10,,20"`(空トークン)も無視されて`[10, 20]`になる。整数に変換できないトークン(`"10.5"`等)が1つでもあれば不正(`ok=False`)。

**固定長パース自体のアルゴリズム(`GenerateDataTableFromCSVAction`を直接インスタンス化・`Execute(null)`を呼び出して確認)**: 区切り文字を使わず、各行を先頭から`widths`で指定した文字数ずつ切り出す(文字位置のみで列が決まる)。`TrimFields`/`ReadFieldsAsText`/`FirstLineContainsColumnNames`の意味論は`datatable_from_csv_text()`(区切り文字版)と完全に同一——ヘッダー行も同じ幅で切り出された上でトリム対象になり(`"COLABCDEHE"`→列名`"COL"`/`"ABCDE"`/`"HE"`)、`ReadFieldsAsText: False`で数値変換も同じ`_csv_as_number()`相当の挙動になる。エッジケース2点を実機確認: (1)行が`sum(widths)`より短いと`ActionException`(「Data table generation failed. Error while parsing text」)になる、(2)行が長い場合は余りの文字を単に無視する(エラーにならない)。末尾の改行は空の追加行を生まない(Pythonの`str.splitlines()`と同じ挙動)。

**実装**: `pad_action_lib/datatable.py`に`_parse_fixed_column_widths()`(上記構文の実装)・`_split_fixed_width_line()`(短い行は`ValueError`、長い行は無視)・`datatable_from_fixed_width_csv()`を新設し、`variables_actions`経由で公開。`file_actions.py`にも同じロジックを使う`read_from_csv_file_fixed_width()`を追加(`File.ReadFromCSVFile`には`ReadFieldsAsText`パラメータ自体が無いため、その引数は持たない——知見127・128確認時に判明済みの構造と整合)。`pad_codegen/actions/variables.py`/`file.py`に両方のaction_idブランチを新規追加し、`tests/test_pad_action_lib_variables.py`に単体テスト5件、`tests/test_pad_codegen.py`に実際に`exec()`する end-to-endテスト2件(Variables側はDSL文字列内に埋め込んだ実改行文字で複数行CSVTextを構成、知見125の教訓通り`\n`エスケープ文字列ではなく実改行を使う、File側は実ファイルへの書き込み→読み込み)を追加した。

これで知見122で発見した`GenerateDataTableFromCSVAction`の3セレクタ・`File.ReadFromCSVFile`/`WriteToCSVFile`の全セレクタ(Write側にはFixedColumnWidths相当の選択肢が無いことは知見128で確認済み)が完全に結線され、CSV読み込み系の未結線セレクタは無くなった。

## 133. 【本セッション最大の決着】知見123・126で「実機のゼロ始まり/1始まり設定(`IsZeroBased`)が未確認」としていた数値列インデックスを、`IListIndexService`の実装クラスをVM上で直接確認して恒久的に解決——Robin DSL(本プロジェクトの対象)は常に0始まりと確定

`Variables.SortDataTable`の未結線セレクタを探索中、`SortDataTableAction`の構築に`IListIndexService`という依存が必要だと判明した。知見123(`FindItemInDataTableByColumnIndex`)・知見126(`ModifyDataTableItem`)で繰り返し「実機の0始まり/1始まり設定`_listIndexService.IsZeroBased`が未確認」という理由で数値列インデックス対応を見送っていたのが、まさにこの同じサービスだった——ならばVM上でこのサービス自体を直接確認すればよいと気づき、実行した。

**確認方法(decompile不要、リフレクションのみ)**: `Microsoft.Flow.RPA.Desktop.Robin.Core.dll`から実装クラス`Robin.Core.Execution.ListIndexService`(パラメータ無しコンストラクタを持つ)を発見し、直接インスタンス化した。`Initialize(ScriptType)`を呼ぶ前の既定状態で`IsZeroBased`プロパティを読むと`True`、`ConvertInput(int)`は恒等写像(入力をそのまま返す)だった。さらに`Initialize()`に`ScriptType`列挙の両値を渡して確認したところ: `ScriptType.Robin`→`IsZeroBased=True`・`ConvertInput()`恒等写像(0始まり)、`ScriptType.PowerFx`→`IsZeroBased=False`・`ConvertInput(n) = n - 1`(1始まり、PowerFx自身の1始まり慣習を内部の0始まり表現へ変換)。

**この確認が持つ決定的な意味**: 本プロジェクトが変換対象とする「クリップボードDSL」は`Microsoft.Flow.RPA.Desktop.Robin.*`名前空間(プロジェクト全体で繰り返し出現する接頭辞)が示す通り、常に`ScriptType.Robin`であり、PowerFxベースの別の記述方式は対象外。したがって**本プロジェクトが扱う範囲では列インデックス・リストインデックスは常に0始まり(Pythonのリスト添字と完全に一致)**と確定した——知見123・126時点では「安全側に倒して非対応のまま」という慎重な判断が正しかったが、今回の確認でその慎重さがもはや不要になった。

**修正・新規結線**: `pad_action_lib/variables_actions.py`に共有ヘルパー`_resolve_column_name(table, column)`(数値文字列なら`columns_of(table)`への0始まりインデックスとして解決、範囲外なら明示的`ValueError`)を新設し、以下3箇所に適用した:
- `modify_datatable_item()`: 知見126の`ValueError`ガードを撤廃し、数値`ColumnNameOrIndex`を正しく解決するよう変更。
- `find_item_in_datatable_everywhere()`: 知見123で「列名のみ対応」としていた制限を撤廃(`Variables.FindOrReplaceInDataTable.FindItemInDataTableByColumnIndex`で数値インデックスが使えるようになった)。
- `retrieve_datatable_column_into_list()`: 同種のサイレントな未対応(数値を単純な辞書キーとして扱ってしまう潜在バグ)を同様に解消。

さらに`sort_datatable()`に`column: str | int`を追加(`int`の場合は`_resolve_column_name()`で解決)し、`Variables.SortDataTable`の完全未結線だった兄弟セレクタ`SortWithColumnIndex`(`ActionSelectorBase.ActionName`の直接読み取りで接尾辞を確認済み)を新規結線した。

**副産物の発見**: `Variables.SortList`にも`SortListByProperty`という未結線セレクタがあり、`SortListBase`の実プロパティ(`Property1/2/3`+`SortDirection1/2/3`、最大3キーで各キーが独立したAscending/Descending方向を持てる)が判明した。これは既存の`sort_list(items, descending: bool, keys: list[str] | None)`(単一の`descending`が全キー共通)の設計では表現できない——各キーごとに独立した方向を持つ多キーソートへの対応は、`sort_list()`自体のシグネチャ変更が必要なより大きな変更になるため、今回は見送り、`pad_todo.md`に次の調査対象として記録する。

テストは`tests/test_pad_action_lib_variables.py`に6件(数値インデックス対応3関数×各1〜2件)、`tests/test_pad_codegen.py`に2件(数値インデックスでの`FindItemInDataTableByColumnIndex`・`SortWithColumnIndex`、両方実際に`exec()`して結果を検証)を追加した。知見126で追加した「数値インデックス拒否」テストは不要になったため「数値インデックス受理」テストに置き換えた。

## 134. 知見133で見送った`Variables.SortList.SortListByProperty`(最大3キー・各キー独立方向の多キーソート)を、実機の`CustomObject`型をVM上で直接構築して仕様を確認し新規結線

知見133で発見した`SortListByProperty`セレクタ(`SortListBase`の`Property1/2/3`+`SortDirection1/2/3`)を、VM上の直接呼び出しで仕様を確認して結線した。

**実機の「オブジェクトのリスト」の正体を特定**: `SortListByProperty.Execute()`にPowerShellの`Hashtable`を渡すと`"'Age' isn't a valid field"`で失敗した——PADの実行時の「CustomObject」はプレーンな辞書ではなく、`Microsoft.PowerPlatform.PowerAutomate.Desktop.Actions.SDK.Types.CustomObject`という専用クラス(`AddOrUpdateProperty(string, object)`/`GetProperty(string)`というメソッド経由でプロパティにアクセスする)だと判明した。このクラスをVM上で正しく構築(`[Activator]::CreateInstance`+`AddOrUpdateProperty`の繰り返し呼び出し)してから渡すと成功した。

**多キーソートの実機挙動を確認**: `{Name: "Bob", Age: 30}`/`{Name: "Alice", Age: 25}`/`{Name: "Carol", Age: 25}`の3件のリストに対し、`Property1: "Age" (Ascending)`・`Property2: "Name" (Descending)`で実行すると結果は`Carol, Alice, Bob`になった——Age昇順が優先され、Age同値(25)のCarol/Aliceの間はName降順(C>A)でCarolが先になる、標準的なSQLの`ORDER BY Age ASC, Name DESC`と同じ多キーソート。Property3を空文字列にしても無視され、エラーにはならなかった。

**Python実装**: Pythonの`list.sort()`が安定ソートであることを利用し、**最下位キーから順に個別の`sort()`を適用し、最後に最上位キーをソートする**という標準的な「安定ソートの繰り込み」で多キー・独立方向のソートを実現できることを確認した(実際に上記の実機確認済み入出力と一致することを単体テストで検証)。既存の`sort_list(items, descending, keys)`(単一`descending`が全キー共通)に`key_descending: list[bool] | None`引数を追加し、各キー独立の方向に対応した。`pad_codegen/actions/variables.py`に`Variables.SortList.SortListByProperty`を新規結線した——`Property1/2/3`がリテラル文字列であることを要求し(空文字列なら未使用として除外)、VarRefの場合は使用するキー数を静的に決定できないため安全にTODOへ委ねる。

`tests/test_pad_action_lib_variables.py`に独立方向の多キーソート単体テスト1件、`tests/test_pad_codegen.py`に`Variables.ConvertJsonToCustomObject`で辞書を構築し`CreateNewList`+`AddItemToList`でリスト化、実際に`exec()`してソート結果を検証するend-to-endテスト1件を追加した。

## 135. 【本セッション最大の横展開】`Variables.Actions.dll`の全`ActionSelector`サブクラスをVM上で一括列挙し、知見133・134以外にも7件の未結線兄弟セレクタを発見・新規結線——個別に探すのではなく「全セレクタを列挙→既存コードと機械的に突き合わせ」という手法そのものを確立した

知見133・134で`SortDataTable`/`SortList`の未結線セレクタを個別に見つけた流れで、「他にも同様の未結線セレクタが潜んでいないか」を体系的に確認するため、`Variables.Actions.dll`内で`ActionSelectorBase`を継承する**全ての**型をリフレクションで一括列挙し、各型の`ActionName`プロパティを読み取って全セレクタの正式な接尾辞一覧を取得した。これを`pad_codegen/actions/variables.py`の既存コードと文字列突き合わせしたところ、知見133・134で解決済みの2件に加えて以下7件の未結線セレクタが見つかった(4件は実装済み、1件は既知の理由で意図的に見送り、2件は既に対応済みと確認):

1. **`Variables.TruncateNumber.GetDecimalPart`/`RoundNumber`**: `truncate_number()`自体は`GetDecimalPart`/`RoundAtNthDecimalDigits`モードを既に実装済みだったが、codegen側の分岐が`GetIntegerPart`の1つしか無かった。`RoundNumber`というセレクタ表示名に対し、実機の`Operation`列挙値自体は`RoundAtNthDecimalDigits`(VM上のリフレクションで確認、でっち上げでは分からなかった対応関係)。VM上で`TruncateNumber.Execute()`を直接呼び出し、丸め規則が「0.5を偶数側に丸める」(banker's rounding、`2.5`→`2`・`3.5`→`4`)——Pythonの`round()`の既定動作と一致——だと確認した。**既知の限界として明記**: 実機は.NETの`decimal`型(10進数の正確な演算)だが、この層は`float`を受け取るため、`2.675`のような2進数で正確に表現できない値では`round()`の結果が実機と食い違う可能性がある(`truncate_number()`のdocstringに追記)。
2. **`Variables.RemoveItemFromList.RemoveItemFromListByValue`**: `remove_item_from_list_by_value()`自体は既にあったがcodegen未結線。VM上で`RemoveItemFromList.Execute()`を直接呼び出し(`IListIndexService`依存のコンストラクタ注入が必要だった)、`ItemMatchAllOccurrences`パラメータの意味(`False`=最初の1件だけ削除/`True`=一致する全要素を削除)を確認し、`all_occurrences`引数を追加した。
3. **`Variables.FindOrReplaceInDataTable.FindItemInDataTableWithRegexByColumnIndex`**: 知見123で個別に結線した`FindItemInDataTableWithRegexEverywhere`(UseRegex固定)と`FindItemInDataTableByColumnIndex`(列名/列インデックス)の**組み合わせ**セレクタ。既存の`find_item_in_datatable_everywhere()`が両方のパラメータを既に独立にサポートしていたため、codegen側の新規分岐1つだけで結線できた。`VisibleArguments`をVM上で確認し、`MatchCase`/`MatchEntireCellContents`は他のRegex系と同じく選択不可(常に既定値False)と確定した。
4. **`Variables.DeleteColumnFromDataTable.DeleteColumnWithIndex`**: 知見133で確立した`_resolve_column_name()`をそのまま再利用し、`delete_column_from_datatable()`の引数型を`str | int`に拡張して結線した。
5. **`Variables.AddRowToDataTable.InsertItemToDataTable`/`Variables.AddColumnToDataTable.InsertColumnToDataTable`**: `AppendRowToDataTable`/`AppendColumnToDataTable`の兄弟セレクタ。両方とも`PositionToAddRow`/`PositionToAddColumn`という追加パラメータ(それぞれ`AddRowMode`={`BeforeRowIndex`,`EndOfDataTable`}/`AddColumnMode`={`BeforeColumnIndex`,`LastColumn`}列挙型)を持つと今回初めて判明した——**既存の`AppendXxx`セレクタは常に`EndOfDataTable`/`LastColumn`に固定されている**とVM上の`Constraints`辞書で確認できたため、既存の`add_row_to_datatable()`/`add_column_to_datatable()`の「常に末尾に追加する」という実装は元から正しかった(潜在バグではなかった)。`Insert`側は`BeforeRowIndex`/`BeforeColumnIndex`固定で、`RowIndex`/`ColumnIndex`(0始まり、知見133)の**指定位置の前に挿入**するという、Pythonの`list.insert(index, item)`と全く同じセマンティクスだとVM上の直接呼び出しで確認した。新規関数`insert_row_to_datatable()`/`insert_column_to_datatable()`を実装し(`AddRowToDataTable`の`RowToAdd`型変換ロジックは`_coerce_row()`として共通化)、両方を結線した。
6. **`Variables.FindOrReplaceInDataTable.Replace*`系4セレクタ**(`ReplaceItemInDataTableEverywhere`/`ReplaceItemInDataTableByColumnIndex`/`ReplaceItemInDataTableWithRegexEverywhere`/`ReplaceItemInDataTableWithRegexByColumnIndex`): 知見123で確認した既存の`find_or_replace_in_datatable()`の既知のギャップ(早期停止無し・置換時のDataTableMatches出力欠落・型保持無し)がまだ未解決のため、今回も意図的に見送った(方針は知見123から変更無し)。
7. 残りのCSV系3セレクタ(`ReadPredefinedSeparator`/`ReadCustomSeparator`/`ReadFixedColumnWidths`)・`SortWithColumnName`/`SortWithColumnIndex`/`SortList`/`SortListByProperty`は知見127・128・132・133・134で既に解決済みと再確認した。

**手法として確立**: 個別のアクションを調査する過程で偶然見つけるのではなく、「`ActionSelectorBase`を継承する全ての型を一括列挙し、`ActionName`で既存コードと機械的に突き合わせる」という手順自体が、未結線セレクタを体系的・網羅的に発見できる低コストな監査手法として確立した(decompile不要、リフレクションのみ、1つのPowerShellスクリプトで完結)。他のモジュール(`File.Actions.dll`等)にも同じ手法を適用する価値がある(次の調査対象として`pad_todo.md`に記録)。

## 136. 知見135の監査手法を`File.Actions.dll`にも適用し、6件の未結線セレクタを新規結線——その過程で、既存の`rename_add_text()`が実在しない列挙値名を仮定していた潜在バグ(まだcodegenに結線されていなかったため未出荷)も発見・修正

知見135末尾の次の調査対象を実行し、`File.Actions.dll`の全`ActionSelector`サブクラスを同じ手法で一括列挙した。既存codegenとの突き合わせで以下を発見・結線した:

1. **`File.ReadTextFromFile.ReadTextAsList`**(`ReadText`の兄弟セレクタ、出力変数名が`Content`ではなく`Contents`): `file_actions.read_text_from_file()`自体は既に`store_content_as="List"`モードを実装済みで未結線だっただけ。VM上で`ReadTextFromFileAction.Execute()`を直接呼び出し、`splitlines()`と同じ挙動(末尾の空行を生まない)だと確認して結線した。
2. **`File.IfFile.DoesNotExist`**(`Exists`条件の兄弟セレクタ): `FileExistsSelector`/`FileDoesNotExistSelector`がいずれも`IfFileAction`の`CheckMode`を切り替えるだけの同一構造だとVM上で確認し、既存の`_EXISTENCE_CHECKS`マップに`negate`フラグを追加して対応した。
3. **`File.WaitForFile.Deleted`**(`Created`の兄弟セレクタ): 同様に`WaitForFileAction`の`WaitFor`を切り替えるだけの構造だと確認し、既存の無期限ポーリングパターンの単純な否定で結線した。
4. **`File.RenameFiles`の4つの文字列操作系兄弟セレクタ**(`RenameAddText`/`RenameRemoveText`/`RenameReplaceText`/`RenameChangeExtension`): `rename_add_text()`/`rename_remove_text()`/`rename_replace_text()`/`rename_change_extension()`は全て既に実装済みだったが、codegen側の分岐が`Rename`(`SetNewName`、知見66で結線済み)の1つしか無かった。

**この過程で発見した潜在バグ**: `RenameFilesAction`の`TextPosition`プロパティの実機の列挙値をVM上のリフレクションで確認したところ、`BeforeName`/`AfterName`だった——しかし既存の`rename_add_text(original_name, text, position: str = "Suffix")`は`position == "Prefix"`判定で実在しない`"Prefix"`/`"Suffix"`という名前を仮定していた(既存の単体テストもこの誤った名前のまま書かれ、グリーンのまま誰にも気づかれていなかった)。幸い、このセレクタ自体がまだcodegenに結線されていなかったため、実際に出荷された生成コードに影響した訳ではない——「結線前に発見できた」珍しいケース。VM上で`RenameFilesAction`を直接呼び出し(`TextToAdd: "NEW"`、`TextPosition: BeforeName`→`"NEWreport.txt"`、`AfterName`→`"reportNEW.txt"`)、`BeforeName`=先頭追加・`AfterName`=末尾追加と確定させ、関数の既定値・判定・既存テストを実機の列挙値名に修正した。`RemoveText`/`ReplaceText`は全ての一致箇所を置換する(Pythonの`str.replace()`既定動作と一致)ことも実機確認し、既存実装が正しいと確定した。

**今回も見送った項目**: `RenameAddDateOrTime`/`RenameAddCustomDateTime`/`RenameAddSequentialSuffix`(日時書式・連番の開始値/増分/パディング等、パラメータが多く個々の書式仕様が未検証)、`OverwriteWithSequentialSuffix`(別アクションのIfFileExists系の3つ目の選択肢と見られるが未調査)は、今回のtickでは時間の都合により見送り、`pad_todo.md`に次の調査対象として記録する。

テストは`tests/test_pad_action_lib_file.py`の`test_rename_schemes`を正しい列挙値名に修正、`tests/test_pad_codegen.py`に6件(`ReadTextAsList`・`IfFile.DoesNotExist`・`WaitForFile.Deleted`・`RenameAddText`/`RenameRemoveText`/`RenameReplaceText`/`RenameChangeExtension`)のend-to-endテスト(実ファイルを作成し、実際に`exec()`してリネーム結果のファイルが存在することまで検証)を追加した。

## 137. `Folder.Actions.dll`にも同じ監査を適用し`Folder.IfFolderExists.DoesNotExist`を発見・結線——型名の部分一致で探す以前の簡易チェックでは見逃していたことが判明し、監査手法自体を「`ActionSelectorBase`を基底型として正しく辿る」方式に統一

知見136の次の調査対象として`Folder.Actions.dll`に同じ監査を適用した。ここで、過去の簡易チェック(型名が`"IfFolder"`という部分文字列を含むかで検索)では、実際のセレクタクラス名`FolderExistsSelector`/`FolderDoesNotExistSelector`(`IfFolder`という文字列を含まない)を取り逃していたと判明した——`BaseType`を`ActionSelectorBase`まで正しく遡る列挙方法(知見135・136で確立した本来の手法)で再確認し、`Folder.IfFolderExists.DoesNotExist`(`File.IfFile.DoesNotExist`と全く同じ、`IfFolderExistsAction`の`CheckMode`を切り替えるだけの構造)を発見した。既存の`_EXISTENCE_CHECKS`マップの`negate`フラグをそのまま再利用して結線した。`Compression.Actions.dll`には`ActionSelector`サブクラスが1つも無い(ZipFiles/UnzipFilesは単一モード)ことも確認した。

**教訓**: 型名の部分文字列一致は便利だが、PAD側のクラス命名規則(`FolderExistsSelector`等、ホストアクション名を省略する命名)に依存すると取り逃しが起こる——必ず`BaseType`を`ActionSelectorBase`まで辿る正式な方法を使うべきと確定した。

## 138. `DateTime.GetCurrentDateTime`の未結線セレクタ4件(`Current`/`Windows`/`CustomOffset`/`CustomTimeZone`)を新規結線——`CustomTimeZone`はルックアップテーブルを経由しない別経路だと発見

`DateTime.Actions.dll`に知見135-137の監査を適用し、`Local`のみ結線済みだった`GetCurrentDateTime`に残り4つの兄弟セレクタがあると確認した。全て同じ`GetCurrentDateTime`アクションの`TimeZoneMode`(`System`/`Specific`/`Windows`/`Custom`)+`InputType`(`Offset`/`Windows`、`Custom`モード内のみ意味を持つ)の組み合わせで表現されている。

**VM上の直接呼び出しで確認した対応関係**(decompile不要):
- `Current`(実機で`[Deprecated]`属性付き)→`TimeZoneMode.Specific`、`Offset`パラメータ(IANA文字列、既存の`get_current_datetime()`がそのまま対応済み)
- `Windows`→`TimeZoneMode.Windows`、`TimeZoneLocation`パラメータ(知見116で解決済みの141エントリ対応表を経由)
- `CustomOffset`→`TimeZoneMode.Custom`+`InputType.Offset`、`CustomOffset`パラメータ(既存のUTC+Nシフト)
- `CustomTimeZone`→`TimeZoneMode.Custom`+`InputType.Windows`、`CustomTimeZone`パラメータ——**これが新発見**: `custom_timezone`引数は既存の関数シグネチャに存在していたが本体で一度も使われていなかった。VM上で`CustomOffset=9.0`と`CustomTimeZone="Tokyo Standard Time"`を実行し、どちらも同一の結果(UTC+9)になることを確認した——つまり`Windows`モードの`TimeZoneLocation`(スペース無しの141値、ルックアップテーブル経由)とは違い、`CustomTimeZone`は.NETの`TimeZoneInfo.Id`形式の文字列(スペースを含む、例: `"Tokyo Standard Time"`)を**ルックアップテーブルを経由せず直接**`win32timezone.TimeZoneInfo()`へ渡す別経路。

`get_current_datetime()`に`input_type: str = "Offset"`引数を追加し、`Custom`モード内で`Offset`/`Windows`の2経路に分岐するよう修正した。知見116が「実機DSLでの直列化形式(パラメータ名)が未確認」として保留していた点は、本セッション中に確立した「リフレクションのプロパティ名=DSL上のパラメータ名」という実証済みパターン(知見117以降で繰り返し確認済み)に基づき結線した——個々のパラメータの実機キャプチャ例自体はまだ無いが、この対応規則自体は多数の既存知見で裏付けられている。

テストは`tests/test_pad_action_lib_datetime.py`に`CustomTimeZone`系1件(Windows専用skip)、`tests/test_pad_codegen.py`にプラットフォーム非依存な`CustomOffset`のend-to-endテスト1件(実際に`exec()`してUTC+5時間が正しく計算されることを検証)を追加した。

## 139. `ActionSelectorBase`一括列挙監査を`Database.Actions.dll`に適用し、`Database.Connect.ConnectOracle`/`Database.ExecuteSqlStatement.ConnectAndExecute`/`ConnectAndExecuteOracle`を新規結線——`connect_and_execute()`は既に実装済みだったが未結線だった

知見135-138の監査手法(`ActionSelectorBase`を基底型として辿る、VM上のリフレクション直接呼び出し)を、これまで未着手だった`Database`/`Web`/`XML`/`Cmd`/`Text`/`Cryptography`の6モジュールに一括適用した(VM上で`[System.Reflection.Assembly]::LoadFrom()`→`GetTypes()`→`BaseType`を`ActionSelectorBase`まで辿る→`ActionName`プロパティ読み取り、という知見135と同じ手順)。

**Database.Actions.dllの発見**: 既存結線は`Database.Connect.Connect`(`OpenConnection`クラス)・`Database.ExecuteSqlStatement.Execute`(`ExecuteSqlStatement`クラス)・`Database.Close`(`CloseConnection`クラス)の3件のみだった。全`ActionSelectorBase`サブクラス5件を列挙したところ、以下2件が未発見・未結線の兄弟セレクタだと判明した:

- `OpenConnectionOracleSelector`(ActionName=`ConnectOracle`): `OpenConnection`クラスの兄弟セレクタ。VM上で`OpenConnection`クラスのプロパティ一覧(`DatabaseType`/`Connection`/`ConnectionString`/`ProviderLibraryPath`等)を確認し、`OpenConnectionOtherSelector`(既存結線の`Connect`)と同一クラス・同一`ConnectionString`プロパティを共有すると確定した。
- `ConnectAndExecuteSelector`(ActionName=`ConnectAndExecute`)・`ConnectAndExecuteOracleSelector`(ActionName=`ConnectAndExecuteOracle`): `ExecuteSqlStatement`クラスの兄弟セレクタ(`ConnectionString`/`DatabaseType`/`Statement`/`Timeout`/`Result`プロパティを同一クラスが持つと確認)——接続文字列から接続・実行・(暗黙に)切断までを1アクションで行う一括モード。

`pad_action_lib.database_actions.connect_and_execute()`は**既に実装済み**(`tests/test_pad_action_lib_database.py`で単体テスト済み)だったが、`pad_codegen`側の結線が一度も無かった——知見129以来何度も見つかっている「下の層は実装済みだがcodegen側の分岐が無い」パターン。`Database.Connect.ConnectOracle`→`database_actions.open_connection(..., database_type='Oracle')`、`Database.ExecuteSqlStatement.ConnectAndExecute[Oracle]`→`database_actions.connect_and_execute(..., database_type='Other'/'Oracle', ...)[1]`として結線した。

**留保事項(実機キャプチャによる確証はまだ無い)**: `DatabaseType`パラメータ自体がDSL上でどう直列化されるか(明示的に`Other`以外を選んだ場合)は未確認——既存の`Connect.Connect`も元々このパラメータを読んでいなかった前例に合わせ、`ConnectAndExecute`も読まずにデフォルト("Other")のまま結線した。`ConnectAndExecute`の出力束縛が本当に`Result`1個だけ(`Connection`の別出力が無い)かも、`Execute`セレクタと同一クラスという構造的推測に基づくものであり、実機DSLキャプチャでの直接確認はまだ無い。

Web/XML/Cmd/Text/Cryptography の5モジュールも同じ監査を実行し、未結線セレクタの全量を把握した(詳細はdesign/pad_todo.md参照)——Database以外はまだ個別の結線作業に未着手。

## 140. 知見139のXML.Actions.dll分を結線完了——`GetElementValueAsNumeric`/`AsBoolean`/`AsDateTime`・`ExecuteXPathAndGetFirstValueOnly`・`WriteToFile`(非フォーマット)の5件を新規結線

知見139でDatabase以外は「監査完了・結線は未着手」としていたXML.Actions.dllについて、結線作業まで完了した。`pad_action_lib.xml_actions.get_xml_element_value()`は元々`value_type: str = "Text"`引数を持っていた(Text以外の値は未使用のまま実装だけ存在していた)ため、`GetElementValueAsNumeric`/`AsBoolean`/`AsDateTime`の3セレクタは既存の`get_xml_element_value()`にそのまま`value_type="Numeric"/"Boolean"/"DateTime"`を渡すだけで結線できた(`Database.Connect.ConnectOracle`と同じ「セレクタ自体がモードを固定する」パターン)。同様に`execute_xpath_query()`の`first_value_only`引数・`write_xml_to_file()`の`format_xml`引数も既存実装のまま`ExecuteXPathAndGetFirstValueOnly`/`WriteToFile`(非フォーマット版)に対応できた。

**見送った項目**: `GetElementAttribute`クラスの`AsNumeric`/`AsBoolean`/`AsDateTime`3セレクタは、`get_xml_element_attribute()`自体に`value_type`引数が無く(常に文字列を返す)、新規の型変換ロジック実装が必要なため今回は見送った——`get_xml_element_value()`の`value_type`実装をそのまま再利用できる可能性が高いが、属性用のValueType列挙値がElement用と同じ文字列("Numeric"/"Boolean"/"DateTime")かは実機未確認。

テストは`tests/test_pad_codegen.py`に4件追加(`GetElementValueAsNumeric/AsBoolean/AsDateTime`の3パターンparametrize+`ExecuteXPathAndGetFirstValueOnly`+`WriteToFile`)、全て実際に`exec()`して出力値まで検証した。

## 141. 知見139のCmd.Actions.dll分を結線完了——`ReadAndSplit`を新規結線、`OpenWithCodePage`は`Encoding`型の意味論未確認のため見送り

知見139でCmd.Actions.dllの未結線セレクタ2件(`OpenWithCodePage`/`ReadAndSplit`)を確認済みだったが結線は未着手だった。VM上で各セレクタの所属クラスのプロパティを確認した:

- `ReadFromCmdSession`クラス: `CmdOutput: String`/`CmdError: String`/`SplitOutputAndError: Boolean`——既存結線の`Read`(`SplitOutputAndError=False`)の兄弟セレクタ`ReadAndSplit`(`SplitOutputAndError=True`)は、既存の`CmdSession.read(split_output_and_error=True)`がそのまま`(stdout, stderr)`タプルを返す実装になっていたため、2つの出力変数(`CmdOutput`/`CmdError`)への展開として新規結線できた。
- `OpenCmdSession`クラス: `ChangeCodePage: Boolean`/`Encoding: Encoding`(単純な文字列ではなく専用の`Encoding`型)——既存の`open_cmd_session(encoding: str = "utf-8")`はこの1つの文字列引数をPythonの`subprocess`テキストデコードと`chcp {encoding}`コマンド引数の両方に再利用しているが、PAD実機の`Encoding`列挙値がどう直列化されるか(コードページ番号かコーデック名か)・既存の`chcp {encoding}`という呼び出し自体がPADの実際の挙動と一致するかはいずれも実機未確認——新規結線は見送った(既存の`change_code_page`/`encoding`引数自体の設計もこの観点で再検証が必要という留保事項が新たに判明した)。

テストは`tests/test_pad_codegen.py`に`ReadAndSplit`の1件を追加した(`CmdSession`はLinux上で`cmd.exe`を起動できないため、`Session`変数へ注入したフェイクオブジェクトで`.read(split_output_and_error=True)`の呼び出しを検証)。

## 142. 知見139のText.Actions.dll分を結線完了——13件を新規結線、既存`GetSubtext`の列挙値文字列の誤りも発見・修正

知見139でText.Actions.dllの未結線セレクタ(23セレクタ中13件)を確認済みだったが結線は未着手だった。VM上で各セレクタの所属クラスのプロパティと関連する列挙型(`SubtextStartIndex`/`SubtextLength`/`JoinTextDelimiter`/`SplitTextDelimiter`/`CropTextMode`/`StandardDelimiter`)のメンバー名を直接確認し、以下13件を新規結線した——全て`pad_action_lib.text_actions`側の既存実装(`get_subtext()`/`crop_text()`/`join_text()`/`split_text()`/`parse_text()`/`replace_text()`が元から持っていた引数)を呼び分けるだけで済んだ:

- `GetSubtextAction`(1クラスで4つの兄弟セレクタ、既存`GetSubtext`含む): `GetText`(StartOfText×EndOfText)・`GetSubtextFromStartTo`(StartOfText×NumberOfChars)・`GetSubtextFrom`(CharacterPosition×EndOfText)。
- `CropTextAction`: `CropTextAfterFlag`(`mode='GetTextAfterFlag'`)・`CropTextBetweenFlags`(`mode='GetTextBetweenFlags'`、`FromFlag`/`ToFlag`両方使用)。
- `JoinTextAction`: `JoinWithDelimiter`(`delimiter_type='Standard'`)・`JoinWithCustomDelimiter`(`delimiter_type='Custom'`)。
- `SplitTextAction`: `SplitWithDelimiter`(`delimiter_type='Custom'`)・`SplitAtNumberOfCharacters`(`delimiter_type='NumberOfCharacters'`)。
- `ParseTextAction`: `Parse`(`is_regex=False, first_occurrence_only=False`、`Matches`/`OccurrencePositions`リスト出力)・`RegexParse`(`is_regex=True, first_occurrence_only=False`)・`RegexParseForFirstOccurrence`(`is_regex=True, first_occurrence_only=True`)。
- `ReplaceTextAction`: `ReplaceTextWithRegex`(`is_regex=True`)。

**既存バグの発見・修正**: VM上で`SubtextStartIndex`/`SubtextLength`の実際の列挙値を確認したところ、`StartOfText`/`CharacterPosition`・`EndOfText`/`NumberOfChars`だと判明した——既存の`Text.GetSubtext.GetSubtext`結線が使っていた`"AtSpecificCharacter"`/`"SpecificLength"`という文字列はこれと**一致していなかった**(実在しない列挙値名だった)。幸い`get_subtext()`の分岐ロジックが`== "StartOfText"`/`== "EndOfText"`という等値判定のみ(どちらにも一致しなければ無条件に「カスタム」側へ進む)だったため、間違った文字列でも偶然挙動には影響していなかった——正しい列挙値名に修正した(`tests/test_pad_codegen_tier1_actions.py`の対応するアサーションも合わせて更新)。

テストは`tests/test_pad_codegen.py`に13件追加し、全て実際に`exec()`して出力値まで検証した。

## 143. 知見139のCryptography.Actions.dll分(AES Salt/IV系12セレクタ)を結線完了——自己発見バグ(`node.output_var`の多重出力での不定動作)も修正

知見139でCryptography.Actions.dllの未結線セレクタ(AES暗号/復号16セレクタ中12件、Salt/IV組み合わせ系)を確認済みだったが結線は未着手だった。VM上で`EncryptTextAction`/`EncryptFromFileAction`/`DecryptTextAction`/`DecryptToFileAction`各クラスのプロパティを確認したところ、いずれも`UseSalt`/`UseIV`(Boolean)・`Salt`/`InitializationVector`(String)プロパティを持ち、各兄弟セレクタ(`...UseSalt`/`...UseIV`/`...UseSaltAndIV`)はこの2つのBooleanの組み合わせをセレクタ自体で固定すると確定した。既存の`encrypt_text()`/`encrypt_from_file()`の`use_salt`/`use_iv`引数、`decrypt_text()`/`decrypt_to_file()`の`salt`/`iv`引数がそのまま対応できたため、12件全て新規結線した。

**暗号化/復号の非対称性**: 暗号化側(`EncryptResult.salt`/`.initialization_vector`)はSalt/IVを**ランダム生成した結果として出力**するが、復号側はSalt/IVを**入力として受け取る**(暗号化時に生成された値を再現する必要があるため)。

**自己発見バグ(実装中に発見・即修正)**: 最初の実装で、Encrypt側の主出力(`EncryptedText`)を`node.output_var`から取得していたが、`node.output_var`は`pad_dsl.line_parser`のコメントの通り「複数の`=>`出力がある場合、最後に見つかったものを保持する」という後方互換用の単一値アクセサであり、Encrypt+Salt+IVのように複数の出力バインディングがある場合は**意図しない方(最後に見つかったSalt/IV)を指してしまう**。実際にexec()するテストを書いた段階で`NameError: name 'Enc' is not defined`として即座に検出でき、`node.output_vars.get("EncryptedText")`(辞書の明示的なキー指定)に修正した——`CropText`/`ParseText`等の既存の多重出力アクションが最初から`output_vars`辞書のみを使っていた理由を、自分で同じ罠を踏んで再確認した形になった。

テストは`tests/test_pad_codegen.py`に、UseSalt/UseIV/UseSaltAndIVの3パターンでEncrypt→Decryptの往復を実際に`exec()`し、復号結果が元の平文に一致することまで検証するテストを追加した。

## 144. 知見139のWeb.Actions.dll分(Download系)を結線完了——8件を新規結線、既存`download_from_web()`の`SaveResponse=ToFile`潜在バグも発見・修正

知見139でWeb.Actions.dllの未結線セレクタ(46セレクタ中、組み合わせが非常に多いため後回しにしていた)のうち、最も安全に結線できるDownload系12セレクタに着手した。VM上で確認したところ、12セレクタ全てが**同一の`DownloadFromWeb`クラス**で、`SaveResponse`(`ToVariable`/`ToFile`、2値)×`DownloadMethod`(`Get`/`Post`)×`UseCredentials`(Boolean)の組み合わせをセレクタ自体が固定していると判明した——`FileName`(`KeepOriginal`/`SpecifyFullPath`)という3つ目の軸も発見したが、これは`SaveResponse=ToFile`のサブモードで、`DownloadToFolder`系(`KeepOriginal`、レスポンスからファイル名を自動決定)は決定方法が実機/decompile未確認のため見送り、`SpecifyFullPath`(`FilePath`で直接パス指定)の8通りのみ新規結線した。既存の`download_from_web()`の`save_response`/`destination_path`/`method`/`use_credentials`引数が元から対応済みだったため、呼び分けのみで済んだ。

**既存バグの発見・修正**: `download_from_web()`は`save_response="ToFile"`時に常に`None`を返していた(`DownloadedFile`出力が元々どのcodegen経路からも使われていなかったため、今まで気づかれなかった)——知見129(`Compression.ZipFiles`)・知見130(`Folder.Copy`)と同種の「呼び出し側が指定したパスをそのまま返すべき出力」パターンに合わせ、`destination_path`をそのまま返すよう修正した。既存の単体テスト(`result is None`というアサーション)もこの修正に合わせて更新した。

`ActionName`がクラス名と一致しない2件(`DownloadUseAuthUsePost`クラス→ActionName=`DownloadUsePostAndAuth`、`DownloadToFileUsePostUseAuth`クラス→ActionName=`DownloadToFileUsePostAndAuth`)を実装前に発見し、正しいActionNameで結線した(これを見逃すと誤ったaction_id文字列を使うことになっていた)。

テストは`tests/test_pad_codegen.py`に7件追加(ToVariable系3パターン・ToFile系4パターン、実ネットワークを使わず`web_actions.download_from_web`自体をフェイクに差し替えて呼び出し引数と出力値を検証)。残るInvokeWebService(32セレクタ)・InvokeSoapService(2セレクタ)・DownloadToFolder系(4セレクタ)は次回以降の対象として記録する。

## 145. 知見139のWeb.Actions.dll分(InvokeSoapService)を結線完了——「プロパティ名=DSL名」という既存の経験則の反例を発見、`InputArgumentAttribute.Name`が真の根拠だと確定

知見139でWeb.Actions.dllの`InvokeSoapServiceUseAuth`を確認済みだったが結線は未着手だった。結線前にVM上で`InvokeSoapServiceAction`クラスのプロパティを確認したところ、既存結線が使っている`Endpoint`パラメータが実際のC#プロパティ名では`Url`になっていることに気づいた——これは知見117以降繰り返し確認してきた「リフレクションのプロパティ名=DSL上のパラメータ名」という経験則の**反例**である。

原因を追って`Url`プロパティの`InputArgumentAttribute`を確認したところ、`Name=Endpoint`という明示的な上書きが設定されていた。一方`UseAuthentication`/`Username`/`Password`プロパティの同属性は`Name`が空——つまり**正しい経験則は「プロパティ名」ではなく「`InputArgumentAttribute.Name`(空ならプロパティ名そのもの)」**だったと確定した。これまでの知見117以降の全ての結線は(`Name`属性を明示的に上書きする設計が今回初めて見つかったケースのため)偶然影響を受けていなかったが、今後VM監査を行う際はプロパティ名だけでなく`InputArgumentAttribute`自体も確認すべき、という教訓が得られた。

`Username`/`Password`は`Name`が空(プロパティ名そのまま)だと確認できたため、`InvokeSoapServiceUseAuth`を安全に結線した——既存の`invoke_soap_service()`に`use_credentials`/`username`/`password`引数を新規追加し(内部で委譲する`invoke_web_service()`は元から対応済み)、`UseAuthentication=True`時のみこれらを渡すようにした。副産物として`Password`プロパティに`ArgumentStylingAttribute(Sensitive=True)`が付いていることも確認し、他の暗号化系パラメータと同じDPAPI保護値の扱いが必要になる可能性を記録した(今回の実装自体はDPAPI値の読み取りに既存の`safe_render()`がそのまま対応する)。

テストは`tests/test_pad_codegen.py`に1件追加し、`web_actions.invoke_web_service`を差し替えて`use_credentials`/`username`/`password`が正しく渡ることをexec検証した。

## 146. 知見145の反例発見を受け、本セッションで新規結線した全パラメータ名を`InputArgumentAttribute.Name`で再検証——Web.InvokeSoapServiceの`Url`/`Endpoint`以外に反例は無いと確認

知見145で「リフレクションのプロパティ名=DSL名」という経験則の反例(`InvokeSoapServiceAction.Url`が実際には`Endpoint`という名前でDSLに現れる)を発見したため、本セッション(知見139-145)で新規結線した全パラメータ名(`Database`/`XML`/`Cmd`/`Text`/`Cryptography`/`Web.DownloadFromWeb`、計40件超)についてVM上で`InputArgumentAttribute.Name`を一括確認した。結果、知見145の`Url`→`Endpoint`以外には反例が見つからなかった——本セッションの既存結線は全て安全だと確認できた。今後も新しいモジュールのプロパティ名を使う際は、プロパティ名だけでなく必ず`InputArgumentAttribute.Name`(または`OutputArgumentAttribute.Name`)を確認する運用を継続する。

## 147. Web.InvokeWebService系(29セレクタ)の構造を解明——`Method`は実機で既に動的パラメータだったと判明、`InvokeWebServiceUseAuth`のみ結線完了

知見144・145に続き、Web.Actions.dllの残りセレクタ群(InvokeWebService系29セレクタ)の構造をVM上で確認した。全て単一の`InvokeWebServiceBase`クラスで、`Method`はこのクラス自身の列挙型(`Get`/`Post`/`Connect`/`Head`/`Put`/`Delete`/`Options`/`Trace`/`Patch`の9値)だと判明——**既存の実機キャプチャ(基本セレクタ)でも`Method: Web.Method.Get`が既に通常のDSLパラメータとして明示的に現れており**、`pad_codegen`側も元からこれを動的に読んで結線していた(知見144までの「セレクタ自体が1つの列挙値を固定する」という典型パターンとは異なる)。

このため、`InvokeWebServicePost`/`InvokeWebServicePut`等の接尾辞セレクタが`Method`の選択肢を制限しているのか、それとも単に同じ機能への別のUIエントリポイント(ユーザーが「POST リクエストを送信する」で検索しやすくするため等)に過ぎないのかは、今回の調査だけでは確定できなかった——基本セレクタが既に全9つのMethod値を自由に選べる以上、無理に別物として結線を推測するより、実機キャプチャまたはdecompileでの裏取りを待つのが安全と判断した。

一方`InvokeWebServiceUseAuth`(`UseAuthentication`/`Username`/`Password`のみを追加する兄弟セレクタ)は、既存の`Method`動的読み取りロジックにそのまま認証引数を重ねられるため安全に結線できた——既存の`invoke_web_service()`が元から`use_credentials`/`username`/`password`を実装済みだったため、呼び分けのみで済んだ。

`SaveResponse`(ToVariable/ToFile)・`UploadType`(FilePath/Binary)・`FileName`(KeepOriginal/SpecifyFullPath)という3つの追加列挙も確認できたが、`SaveToFile`/`SaveToFolder`/`Upload`接尾辞セレクタの結線(`invoke_web_service()`側にファイル入出力機能を新規実装する必要がある)は引き続き見送る。

テストは`tests/test_pad_codegen.py`に1件追加し、`web_actions.invoke_web_service`を差し替えて`use_credentials`/`username`/`password`の受け渡しをexec検証した。

## 148. 知見142で見送ったText.Actions.dllの.NET書式変換系2件も結線完了——`dotnet_format_to_strftime()`は既に実装済みだった

知見142で「.NET書式→Python strftime変換の検証が必要」として見送っていた`ConvertDateTimeToText.FromCustomDateTime`/`ConvertTextToDateTime.ToDateTimeCustomFormat`を再調査した。`pad_action_lib.text_actions.datetime_to_text()`/`text_to_datetime()`は**既に`format_type`/`custom_format`・`date_is_in_custom_format`/`custom_format`引数を実装済み**(内部で`dotnet_format_to_strftime()`を呼ぶ)だったため、見送る必要が無かったと判明した。

VM上で`DateTimeConversionFormat`列挙値(`Standard`/`Custom`)を確認し、既存の`format_type`パラメータの文字列と完全一致することも確認した。両セレクタとも「セレクタ自体がモードを固定する」パターン(`FromCustomDateTime`→`format_type='Custom'`固定、`ToDateTimeCustomFormat`→`date_is_in_custom_format=True`固定)で安全に結線できた。

テストは`tests/test_pad_codegen.py`に1件追加し、Text→DateTime→Textの往復を実際に`exec()`して(`"2026-11-05"`→`datetime(2026,11,5)`→`"2026/11/05"`)検証した。これで知見142で見送った項目は全て解消し、Text.Actions.dllの23セレクタ全件(鍵無しの`RecognizeEntitiesInText`を除く)が結線完了した。

## 149. 知見140で見送ったXML.Actions.dllの`GetElementAttribute`型変換系3件も結線完了——`get_xml_element_attribute()`に`value_type`を新規実装

知見140で「`get_xml_element_attribute()`に`value_type`引数が無く新規実装が必要」として見送っていた`GetElementAttributeAsNumeric`/`AsBoolean`/`AsDateTime`を実装した。VM上で`GetXmlElementAttribute`クラスのプロパティを確認したところ、`ValueType`列挙値(`Text`/`Numeric`/`DateTime`/`Boolean`)は`GetElementValue`と共通の型だが、出力の構造が異なると判明した——`GetElementValue`は単一の`Subtext`出力をそのまま型変換するのに対し、`GetElementAttribute`は`TextValue`/`NumericValue`/`DateTimeValue`/`BooleanValue`という**モードごとに別々の出力プロパティ**を持つ。

既存の`get_xml_element_value()`の型変換ロジック(`Decimal`/`dateutil_parser`/真偽値判定)を`_convert_xml_text_value()`として共通化し、`get_xml_element_attribute()`に`value_type: str = "Text"`引数を追加して(既定値は従来の文字列そのままの挙動を保つ)両関数で再利用した。

テストは`tests/test_pad_codegen.py`に3パターンのparametrizeテストを追加し、実際に`exec()`してXML属性値から型変換済みの値が出力変数に入ることまで検証した。これでXML.Actions.dllの12セレクタ全件が結線完了した。

## 150. 知見147の未確定事項を解消——各セレクタの`.Arguments`プロパティが「DSLに実際に現れるパラメータ名」の確定的な根拠だと判明、`InvokeWebServicePost`/`Put`系4件を新規結線

知見147で「`InvokeWebServicePost`/`Put`接尾辞セレクタが`Method`を制限しているのか、単なる別UIエントリかは確定できなかった」としていた点を、`ActionSelectorBase`サブクラス自身の`.Arguments`プロパティ(そのセレクタで実際にDSLに現れるパラメータ名の一覧、インスタンス化して直接読み取れる)を確認することで解消した。

`InvokeWebServiceSelector`(基本)・`InvokeWebServiceUseAuthSelector`の`.Arguments`には`Method`が含まれるが、`InvokeWebServicePostSelector`/`InvokeWebServicePutSelector`/`InvokeWebServiceUseAuthPostSelector`/`InvokeWebServiceUseAuthPutSelector`の`.Arguments`には`Method`が**含まれない**——つまりこれらのセレクタは`Method`をDSLパラメータとして露出せず、セレクタ自体が`Post`/`Put`に固定していると確定した。

**監査手法の更なる改善**: 知見135(プロパティ名で判別)→知見145(`InputArgumentAttribute.Name`で判別)→本知見(`.Arguments`/`.VisibleArguments`で判別)という順で、より確定的な根拠に到達した——`.Arguments`は「このセレクタがインスタンス化された時点でDSLシリアライズに実際に使われるプロパティ名の一覧」そのものであり、個々のプロパティの存在や属性を推測で組み合わせるより直接的で確実。今後の監査はまず`.Arguments`を確認することを標準手順とする。

`InvokeWebServicePost`/`InvokeWebServicePut`/`InvokeWebServiceUseAuthPost`/`InvokeWebServiceUseAuthPut`の4件を、既存の`invoke_web_service()`の`method`引数を固定値で渡す形で新規結線した。テストは`tests/test_pad_codegen.py`に4パターンのparametrizeテストを追加し、`web_actions.invoke_web_service`を差し替えて`method`/`use_credentials`の受け渡しをexec検証した。

## 151. 知見150の`.Arguments`監査手法でWeb.InvokeWebService系`SaveToFile`接尾辞6セレクタを新規結線——`InvokeWebServiceResult.downloaded_file`フィールドを初めて実際に設定

知見147・150で見送っていた`SaveToFile`接尾辞セレクタ(`InvokeWebServiceSaveToFile`/`InvokeWebServiceUseAuthSaveToFile`/`InvokeWebServiceSaveToFilePost`/`InvokeWebServiceSaveToFilePut`/`InvokeWebServiceUseAuthSaveToFilePost`/`InvokeWebServiceUseAuthSaveToFilePut`、計6セレクタ)を、知見150で確立した`.Arguments`監査手法で確認した。全て`FilePath`/`DownloadedFile`を持ち`Response`/`ResponseHeaders`/`StatusCode`を持たない——`SaveResponse=ToFile`相当のモードだと確定した。`Method`は基本セレクタと`UseAuth`(Get)版のみ`Arguments`に含まれ、`Post`/`Put`接尾辞版は含まれない(知見150の`Post`/`Put`固定パターンと同じ)。

`invoke_web_service()`の`InvokeWebServiceResult.downloaded_file`フィールド自体は元から定義されていたが、これまでどの呼び出し元からも設定されたことが無かった(常に`None`)。知見144の`download_from_web()`の`save_response`/`destination_path`引数と同じパターンで、`invoke_web_service()`にも`save_response: str = "ToVariable"`/`destination_path: str | None = None`引数を新規追加し、`save_response="ToFile"`時にレスポンスボディを指定パスへ書き込み、書き込んだパスをそのまま`downloaded_file`として返すようにした(`destination_path`が親ディレクトリの存在しないパスの場合は`DirectoryDoesNotExistError`、未指定の場合は`InvokeWebServiceError`)。

`pad_codegen/actions/web.py`側は既存の`_INVOKE_WEB_SERVICE_FIXED_METHOD`/`_INVOKE_WEB_SERVICE_ACTION_IDS`の仕組みを拡張し、`_INVOKE_WEB_SERVICE_SAVE_TO_FILE`という新規セットでSaveToFile系6件を判別、`FilePath`パラメータを読み取って`destination_path`として渡し、出力変数は`Response`系では無く`DownloadedFile`(`node.output_vars.get("DownloadedFile")`)を`{tmp}.downloaded_file`へ束縛するよう分岐した。

テストは`tests/test_pad_action_lib_web.py`に`invoke_web_service()`の単体テスト1件、`tests/test_pad_codegen.py`に6パターンのparametrizeテストを追加し、`web_actions.invoke_web_service`を差し替えて`save_response`/`destination_path`/`method`/`use_credentials`の受け渡しと出力変数への束縛をexec検証した。これでWeb.InvokeWebService系29セレクタ中、`Get`/`Post`/`Put`×`UseAuth`×`SaveToFile`の組み合わせ(計10セレクタ)が結線完了し、残るは`SaveToFolder`(ファイル名自動決定、知見144の`DownloadToFolder`と同じ未確認事項)・`Upload`(`RequestBody`の代わりに`Attachments`/`UploadType`を使う別の新規実装が必要)の計約19セレクタとなった。

## 152. Web.Actions.dllをdecompile(ilspycmd)し、知見147・151で見送っていた`SaveToFolder`/`Upload`/`DownloadToFolder`系(計22セレクタ)を全て新規結線——`WebActions.GetDownloadFilePath()`/`FormulateWebRequest()`のロジックをそのまま再現

VM上の`.Arguments`監査(知見150の手法)だけでは「`SaveToFolder`系のファイル名自動決定アルゴリズム」「`Upload`系のmultipart/form-data構築方法」が分からず、知見144・147・151では見送っていた。これらを解消するため、`pad2py-fetch-web-dll`(既存のclipwire target)で`Microsoft.Flow.RPA.Desktop.Modules.Web.Actions.dll`(208,184バイト)をBase64経由で取得し、ローカルの`ilspycmd`(`~/.dotnet/tools/ilspycmd`、`dotnet`自体はPATH外の`~/.dotnet/dotnet`に存在、`PATH`/`DOTNET_ROOT`を設定して実行)で逆コンパイル(本リポジトリには逆コンパイル結果自体はコミットしない方針は従来通り)した。

**`DownloadToFolder`/`SaveToFolder`系(計10セレクタ: `DownloadToFolder`×4・`InvokeWebService*SaveToFolder*`(Upload以外)×6)**: `WebActions.GetDownloadFilePath(response, keepOriginalFileName, destinationFolder, filePath)`の実装を発見。`keepOriginalFileName=True`の場合:
1. `Content-Disposition`ヘッダの`filename=`(正規表現、オプションの`UTF-N`プレフィックス対応)を最優先。
2. 無ければレスポンスURLの最後のパスセグメント。
3. パスが`/`(ルート)の場合はホスト名+`.html`にフォールバック。
4. `Utilities.SanitizeFileName(text, "_")`でサニタイズして`destinationFolder`と結合。

`Utilities.SanitizeFileName`自体は別の共有SDK DLL内にあり未decompileのため、Windowsのファイル名として不正な文字集合(`<>:"/\|?*`+制御文字、`Path.GetInvalidFileNameChars()`相当)を`_`に置換する一般的な実装で代替した——これだけが実機/decompile未確認の箇所である。`download_from_web()`/`invoke_web_service()`に`_get_download_file_path()`として実装し、両関数に`destination_folder`引数を追加(`destination_path`との二択、`SaveToFile`/`SaveToFolder`の判別に対応)した。`InvokeWebServiceBase.Execute()`も`SaveResponse==ToFile`時に`DestinationFolder`/`FilePath`を同じ`GetDownloadFilePath()`に渡しているとdecompileで確認済み(`SaveToFile`/`SaveToFolder`は同じコードパスの`FileName`列挙値の違いに過ぎない)。

**`Upload`系(計12セレクタ: `InvokeWebService{Post,Put}{,SaveToFile,SaveToFolder}{,UseAuth}Upload`)**: `WebActions.FormulateWebRequest()`の`uploadAttachments`分岐を発見。`boundary = "---------------------------" + DateTime.Now.Ticks.ToString("x")`で区切り、`Attachments`DataTable(列名`NAME`/`ATTACHMENT`、`Constants.InvokeServiceActions.InvokeWebServiceColumnNames`で定義済み)の各行を`--{boundary}\r\n` + `Content-Disposition: form-data; name="{NAME}"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n` + 添付データ + `\r\n`として書き出し、最後に`--{boundary}--\r\n`で終端する。`UploadType.FilePath`(`row["ATTACHMENT"]`をファイルパスとして読み込み`Path.GetFileName()`をfilenameに使う)と`UploadType.Binary`(`BinaryObject.Data`を直接使う)の2方式があるが、本プロジェクトに`BinaryObject`相当の型が無いため`FilePath`方式のみ実装し、`Binary`は`None`を返してTODOへ倒した。全12セレクタで`UploadAttachments=True`固定、`RequestBody`/`ContentType`はDSL上に存在しない(`.Hide<>()`で隠されている、`EncodeRequestBody`/`TrimRequestBody`は存在するが効果が無い——multipart構築時は`RequestBody`分岐自体に入らない)ことも確認した。

**監査手法の記録**: `.Arguments`プロパティ(知見150)は「どのパラメータがDSLに現れるか」を確定できるが、「現れたパラメータがどう処理されるか」(ファイル名決定アルゴリズム・multipart形式)はdecompileでなければ分からない——両者は補完関係にあり、後者が必要な場合は今回のように対象DLLをVMから取得してローカルでdecompileする(知見90の`ilspycmd`手法)のが確実。

テストは`tests/test_pad_action_lib_web.py`に`_get_download_file_path()`系4件(Content-Disposition優先・URL末尾セグメント・ルートパスのhost+.htmlフォールバック・不正文字サニタイズ)・`invoke_web_service()`のSaveToFolder/Upload系3件、`tests/test_pad_codegen.py`に`DownloadToFolder`系4パターン・`InvokeWebService*SaveToFolder*`系6パターン・`InvokeWebService*Upload`系12パターンのparametrizeテストを追加し、いずれも実際に`exec()`して検証した。これでWeb.Actions.dll全46セレクタ中、未結線で残るのは`UploadType.Binary`方式(本プロジェクトに型が無く意図的に見送り)のみとなった。

## 153. Cmd.Actions.dllをdecompileし`OpenWithCodePage`の`Encoding`型を解明——Windowsコードページ番号そのものを基底値に持つ共有列挙型だった、`chcp`には整数を送る

知見141で見送っていた`Cmd.Open.OpenWithCodePage`(`Encoding`型パラメータの意味論が実機未確認)を解消した。`pad2py-fetch-cmd-dll`(新規clipwire target)で`Microsoft.Flow.RPA.Desktop.Modules.Cmd.Actions.dll`(52,552バイト)を取得し`ilspycmd`でdecompileしたところ、`OpenCmdSession.Execute()`が`(int)Encoding`というキャストを行っており、`Encoding`プロパティの型自体がこのDLL内では定義されていない(`Microsoft.Flow.RPA.Desktop.Robin.Shared.Runtime.Enums`という外部namespaceからの`using`)ことが分かった。

`Microsoft.Flow.RPA.Desktop.Robin.Shared.Runtime.dll`(`Get-ChildItem -Recurse`で特定)を直接リフレクションで問い合わせ(型の`GetTypes()`→`Name -eq "Encoding"`→`[System.Enum]::GetNames()`+`GetValues()`)、全150メンバーの名前と基底`int`値を取得した——`utf_8=65001`・`shift_jis=932`・`Windows_1252=1252`等、**各メンバーの基底値がそのままWindowsのコードページ番号**になっている共有列挙型だと確定した(decompileとリフレクションの両方で確認、でっち上げではない)。

`CmdSessionActions.OpenCmdSession()`の実装(decompile直読み): `ChangeCodePage=False`(`Open`)の場合は`Encoding.Default`(OS既定のANSIコードページ)を使い`Encoding`パラメータ自体はDSL上に存在しない(`Hide<Encoding>()`)。`ChangeCodePage=True`(`OpenWithCodePage`)の場合のみ`System.Text.Encoding.GetEncoding((int)Encoding)`で`StandardOutputEncoding`/`StandardErrorEncoding`を設定し、プロセス起動後に`chcp {encoding}`(`encoding`は**整数のコードページ番号そのもの**、コーデック名の文字列ではない)を最初のコマンドとして送信する。

`pad_action_lib.cmd_actions.open_cmd_session()`に、リフレクション確認済みの全150メンバーをそのまま転記した`_ENCODING_CODEPAGES: dict[str, int]`を追加し、`encoding`引数の意味を「`ChangeCodePage=True`の場合は列挙名(`_ENCODING_CODEPAGES`のキー)、コードページ番号→Python`cp<N>`コーデックへ変換して`subprocess.Popen(encoding=...)`に渡し、`chcp <N>`をそのまま整数で送信」に変更した(`ChangeCodePage=False`の場合は`encoding`引数自体を無視し、ホスト依存の`Encoding.Default`の代わりに安全な既定値`utf-8`を使う——この挙動は元から変更無し)。未知の列挙名は`OpenCmdError`で安全に失敗する。

`pad_codegen/actions/cmd.py`に`Cmd.Open.OpenWithCodePage`のディスパッチを新規追加し、`Encoding`パラメータを`enum_last()`で読み取った列挙名の文字列をそのまま`encoding=`引数へ渡すだけで済んだ(コードページ変換自体は`pad_action_lib`側の責務)。

テストは`tests/test_pad_action_lib_cmd.py`に`_ENCODING_CODEPAGES`のサンプル値確認・`change_code_page=True`時に`chcp <コードページ番号>`が送信されることの確認(`CmdSession.write`をフェイクに差し替えて検証)・未知の列挙名で`OpenCmdError`になることの確認の3件、`tests/test_pad_codegen.py`に`OpenWithCodePage`のexec検証1件を追加した。これでCmd.Actions.dllの4セレクタ全件が結線完了した。

## 154. File.Actions.dllをdecompileし`RenameAddDateOrTime`/`RenameAddCustomDateTime`/`RenameAddSequentialSuffix`/`OverwriteWithSequentialSuffix`を結線——`rename_add_datetime()`/`rename_make_sequential()`の既存の未確認実装に2件の潜在バグを発見・修正

知見136で見送っていた`File.RenameFiles`の残り4セレクタ(`RenameAddDateOrTime`/`RenameAddCustomDateTime`/`RenameAddSequentialSuffix`/`OverwriteWithSequentialSuffix`)を、`pad2py-fetch-file-dll`(新規clipwire target)で取得した`Microsoft.Flow.RPA.Desktop.Modules.File.Actions.dll`(171,824バイト)のdecompileで解消した。全て単一の`RenameFilesAction`クラスの兄弟セレクタで、`RenameFilesAction.GetNewFileNameResolver()`(`RenameScheme`ごとの`Func<FileObject, string>`を返すswitch式)に全スキームの正確なアルゴリズムが書かれていた。

**`AddDateTime`スキーム**(`RenameAddDateOrTime`=`UseCustomDateTime:False`・`RenameAddCustomDateTime`=`UseCustomDateTime:True`の兄弟セレクタ): `DateTimeToAdd`列挙(`Current`/`CreationTime`/`LastAccessed`/`LastModified`)で使うタイムスタンプを選び、`DateTimeFormat`(.NET書式文字列)で`.ToString()`、`DateTimePosition`(`AddTextPosition`、知見136と同じ`BeforeName`/`AfterName`)の位置に`DateTimeSeparator`(`Separator`列挙、`Nothing`/`Space`/`Dash`/`Period`/`Underscore`——`GetSeparator()`で実際の文字へ変換、既定`Space`)を挟んで結合する。

**`MakeSequential`スキーム**(`RenameAddSequentialSuffix`=`SequenceUseExistingName:True`・`OverwriteWithSequentialSuffix`=`SequenceUseExistingName:False`の兄弟セレクタ): 連番(`StartNumberingAt`から`IncrementBy`ずつ加算、バッチ内で状態共有)を`UsePadding`時は`Padding`桁まで`0`埋めし、`SequencePosition`の位置に`SequenceSeparator`を挟んで、`SequenceUseExistingName`なら既存のファイル名(拡張子抜き)、そうでなければ`SequenceNewName`と結合する。

**既存実装の潜在バグ発見・修正**: `pad_action_lib.file_actions`の`rename_add_datetime()`/`rename_make_sequential()`はいずれも知見136より前に実機未確認のまま書かれた推測実装で、codegenに結線されていなかった(`pad_todo.md`に「未検証」として記録済み)——出荷前に以下2件を発見・修正できた:
1. `rename_add_datetime()`は`position`に存在しない`"Prefix"`/`"Suffix"`を仮定していた(実機は`rename_add_text()`と同じ`BeforeName`/`AfterName`、知見136の`RenameAddText`修正と全く同じ種類の誤り)。
2. `rename_make_sequential()`/`rename_add_datetime()`はいずれも`Separator`を一切挟まない直接連結を仮定していたが、実機は`GetSeparator()`で変換した区切り文字を常に挟む(既定`Space`)——`rename_make_sequential()`の既存テストは区切り文字無しの連結(`"file001.txt"`)を仮定しており、decompileで反証された。

`rename_add_datetime()`は`dotnet_format`引数を直接受け取り`text_actions.dotnet_format_to_strftime()`(知見148と同じ再利用)で変換するよう修正、`rename_make_sequential()`は`base_text: str | None = None`(Noneなら既存のファイル名、値を渡すと`SequenceNewName`相当)・`position`・`separator`引数を新規追加した。新規`file_actions.file_timestamp(path, which)`で`CreationTime`/`LastAccessed`/`LastModified`のファイルタイムスタンプを取得する。

`pad_codegen/actions/file.py`の`_RENAME_SCHEME_TRANSFORMS`ディスパッチを拡張し、各変換関数が`(ループ前に1回だけ出すセットアップ行のリスト, _rename_new_baseを計算する式)`のタプルを返す設計に変更した——`MakeSequential`系はバッチ内で状態共有する`SequentialNumberer`をループ前に1回だけ生成する必要があるため(既存の4つの単純な文字列変換セレクタは空リストを返すだけで済む)。`Separator`列挙→実際の文字への変換は`_support.RENAME_SEPARATOR_TO_CHAR`に切り出し、`CSV_PREDEFINED_SEPARATOR_TO_DELIMITER`と同じパターンで管理する。

テストは`tests/test_pad_action_lib_file.py`に`rename_add_datetime()`/`rename_make_sequential()`/`file_timestamp()`の新規テスト5件(既存の区切り文字無し仮定テストも知見154を踏まえて`separator=""`明示に修正)、`tests/test_pad_codegen.py`に4セレクタ分のexec検証テストを追加した。これで`File.Actions.dll`の`RenameFiles`系(`RenameScheme`列挙の全6パターン)が結線完了した。

## 155. Excel.Actions.dllに`ActionSelectorBase`一括列挙監査(知見139以降の標準手法)を初適用——知見80の「14アクション確認済み」はグループ名のみで、実際のaction_idは8グループで3セグメント形式だった(既存の「完了済み」結線が実際には一度もマッチしていなかった潜在バグ)

知見139以降、Web/XML/Cmd/Text/Cryptography/Database/File/Folder/Variablesの各モジュールには`ActionSelectorBase`一括列挙監査を適用してきたが、PDF/Excel/Word/PowerPointの4モジュール(知見80で「Tier3スコープ内アクション全件のaction_id確認・codegen結線が完了」と記録されていた)にはこの監査を一度も適用していなかった。「ToDo何が残っているか」の洗い出しの一環でExcel.Actions.dllに適用したところ、重大な見落としが見つかった。

知見80の手法(PADデザイナーの検索結果`TreeItem`のAutomationIdを直接読む)は、**アクション検索パネルに表示される項目のAutomationId**を確認したものだった——これは「`Excel.ReadFromExcel`というアクション(グループ)が存在する」ことの確認であり、実際にそのアクションをキャンバスに追加して選択(モード)を決めた後の**真のDSL action_id文字列**ではなかった。VM上のリフレクション(`Microsoft.Flow.RPA.Desktop.Modules.Excel.Actions.dll`を`[System.Reflection.Assembly]::LoadFrom()`→`GetTypes()`→`ActionSelectorBase`派生を辿る、知見139と同じ手法)で確認したところ、Excel.Actions.dllには95以上の`ActionSelector<T>`サブクラスが存在し、知見80で「14アクション」として確認した以下8グループには実際に兄弟セレクタがあった:

| グループ | 兄弟セレクタ(`ActionName`) | 固定される列挙値 |
| --- | --- | --- |
| `LaunchExcel` | `Launch`/`LaunchAndOpen`/`LaunchUnderExistingProcess`/`LaunchAndOpenUnderExistingProcess` | `LaunchExcelMode`(New/Stored)×`LaunchInNewInstance`(True/False) |
| `CloseExcel` | `Close`/`CloseAndSave`/`CloseAndSaveAs` | `CloseMode`(DoNotSave/Save/SaveAs) |
| `SaveExcel` | `Save`/`SaveAs` | `SaveMode`(Save/SaveAs) |
| `ReadFromExcel` | `Read`/`ReadCell`/`ReadCells`/`ReadAllCells`/`ReadNamedCell` | `ReadMode`(Selection/SingleCell/RangeOfCells/AllCells/NamedCells) |
| `WriteToExcel` | `Write`/`WriteCell`/`WriteNamedCell` | `WriteMode`(ActiveCell/SpecifiedCell/NamedCells) |
| `DeleteWorksheet` | `DeleteWorksheetByIndex`/`DeleteWorksheetByName` | `FindWorksheetBy`(Index/Name) |
| `RenameWorksheet` | `RenameWorksheetWithIndex`/`RenameWorksheetWithName` | 同上 |
| `SetActiveWorksheet` | `ActivateWorksheetByIndex`/`ActivateWorksheetByName` | 同上 |

残り6グループ(`AddWorksheet`/`GetActiveWorksheet`/`GetAllWorksheets`/`GetColumnName`/`GetFirstFreeColumnRow`/`GetFirstFreeRowOnColumn`)は兄弟セレクタが存在せず、既存のフラットな`Excel.<グループ名>`形式のままで正しいと確認できた。

**影響の確定**: `pad_codegen/actions/excel.py`は上記8グループを全てフラットな2セグメント形式(`action_id == "Excel.ReadFromExcel"`等)で判定していた——これは実際のDSL(3セグメント形式)とは文字列として一致しないため、**実際のPADフローからエクスポートされたDSLでは一度も発火せず、常にTODOフォールバックに落ちていた**。知見80の時点で実機確認済みと記録されていたが、その確認は「アクションが存在する」ことだけであり「パラメータの直列化形式(action_id自体)」は依然decompileの推測のままだった、という確証レベルの取り違えが原因。

`pad2py-fetch-excel-dll`(新規clipwire target)でDLL本体を取得し`ilspycmd`でdecompileし、各`ActionSelector<T>`サブクラスの`Prop<>.ShouldBe()`/`Show<>()`/`Hide<>()`呼び出しを直接読み、どのパラメータがどの値に固定されるかを確定した。`ReadFromExcel.Read`(ReadMode=Selection)・`WriteToExcel.Write`(WriteMode=ActiveCell)・`LaunchExcel.LaunchUnderExistingProcess`/`LaunchAndOpenUnderExistingProcess`(LaunchInNewInstance=False、既存の生きているExcelプロセスへのCOMアタッチ)は、既存の`pad_action_lib.excel_actions`のスコープ外(openpyxlでは再現不可)と一致するため、意図的に結線せずTODOへ委ねた。

`pad_action_lib.excel_actions`自体の関数シグネチャ(`launch_excel()`/`close_excel()`/`save_excel()`/`read_from_excel()`/`write_to_excel()`/`delete_worksheet()`/`rename_worksheet()`/`set_active_worksheet()`)はいずれも変更不要だった——問題は`pad_codegen`側のディスパッチキー(action_id文字列)だけだったため、各セレクタの固定列挙値をハードコードした3セグメント形式のディスパッチへ置き換えるだけで済んだ(`enum_last()`で動的に読む必要は無い、セレクタが選ばれた時点で値は一意に確定しているため)。

既存の`tests/test_pad_codegen.py::test_generate_python_from_excel_full_scope_in_batch_converts_all_actions`/`test_generate_python_from_excel_unsupported_live_com_modes_fall_back_to_todo`も、同じ誤ったフラットなaction_id形式でDSLを手書きしていたため「自己整合的に見えるが実在しない形式を検証していた」テストだった——正しい3セグメント形式に修正した。

**今後の方針**: PDF/Word/PowerPointモジュールも知見80の同じ手法(グループ名のAutomationIdのみ確認)で「完了」と記録されているため、同種の潜在バグ(フラットなaction_id判定が実際には3セグメント形式で一度もマッチしない)が無いか、同じ`ActionSelectorBase`一括列挙監査を適用して確認する必要がある——次回以降の調査対象として記録する。

## 156-158. PDF/Word/PowerPointにも同じ`ActionSelectorBase`一括列挙監査を適用——知見155と全く同種の潜在バグを3モジュール全てで発見・修正(知見80の「完了」記録が3モジュール分全て取消し)

知見155でExcelに発見した「知見80はアクション**グループ**のAutomationIdしか確認しておらず、真のDSL action_idは3セグメント形式だった」という潜在バグが、同じ知見80の手法で「完了」と記録されていたPDF/Word/PowerPointの残り3モジュールにも存在するかを確認した。`pad2py-fetch-pdf-dll`/`pad2py-fetch-word-dll`/`pad2py-fetch-powerpoint-dll`(新規clipwire target)でDLL本体を取得し`ilspycmd`でdecompile、`ActionSelectorBase`派生を辿るリフレクション監査(知見139・150の標準手法)を適用した結果、**3モジュール全てで同種の潜在バグを発見**した。

**知見156(PDF.Actions.dll)**: `ExtractImagesFromPDFAction`/`ExtractTablesFromPDFAction`/`ExtractTextFromPDFAction`の3クラスにそれぞれ`PagesToExtract`(`ExtractionMode`: All/Single/Range)を固定する3兄弟セレクタ(`Extract*`/`Extract*FromPage`/`Extract*FromPageRange`)があった。これら3クラスは`[Action(Id = "ExtractImagesFromPDF")]`等の明示的な`Id`属性でクラス名の`...Action`接尾辞を取り除いており、真のaction_idは`Pdf.ExtractImagesFromPDF.ExtractImages`等の3セグメント形式。**副産物の発見**: 既存の合成テストが`PagesToExtract: Pdf.ExtractionMode.SinglePage`という**実在しない列挙値名**(実際は`Single`)を仮定していた——知見136の`rename_add_text()`の`Prefix`/`Suffix`と同じ種類の誤り。`Pdf.ExtractPages`(`ExtractPagesToNewPDFAction`)/`Pdf.MergeFiles`は兄弟セレクタが存在せず(リフレクションで確認)フラットな形式のままだが、この2クラスは`[Action(Name = "ExtractPages")]`のように`Id`属性ではなく`Name`属性のみを持つ——`Id`無しの場合に本当にクラス名(`ExtractPagesToNewPDFAction`)が使われるのか、`Name`が何らかの形でaction_idに影響するのかは今回のdecompileだけでは確定できず、新たな未確認事項として記録する(既存の結線を変更する根拠は無いため、現状維持のまま)。

**知見157(Word.Actions.dll)**: `CloseWord`/`FindAndReplaceWord`/`LaunchWord`/`ReadFromWord`/`SaveWord`/`WriteToWord`の6グループに兄弟セレクタがあった(いずれも`Id`属性の上書きが無くクラス名がそのまま中間セグメントなので、第3セグメントの欠落のみが問題)。`FindAndReplaceWord`は`{AllMatches, MatchWildCards}`の2×2=4通りの兄弟セレクタ(`FindAndReplaceSingle`/`FindAndReplaceSingleWildcards`/`FindAndReplaceAllWildcards`/`FindAndReplaceAllWithoutWildcards`)で、ワイルドカード系2件は既存の方針通りスコープ外。`InsertImageToWord`(8セレクタ)は`pad_action_lib`側に未実装のため対象外のまま。

**知見158(PowerPoint.Actions.dll)**: `AddPowerPointSlide`/`ClosePowerPoint`/`DeletePowerPointSlide`/`LaunchPowerPoint`/`ReadFromPowerPoint`/`SavePowerPoint`/`WriteToPowerPoint`の7グループに兄弟セレクタがあった(同じく`Id`属性の上書き無し)。`MovePowerPointSlide`は兄弟セレクタが存在せず、既存のフラットな形式のままで正しい。

**影響の確定**: PDF/Word/PowerPointの合計16グループの`pad_codegen`ディスパッチは、知見80で「確認済み」と記録された後、一度も実際のDSLでマッチせず常にTODOフォールバックに落ちていた——Excelの知見155と完全に同じ構造の潜在バグ。各選択済みセレクタが固定する列挙値(`CloseMode`/`SaveMode`/`ReadMode`/`WriteMode`/`AddSlidePosition`/`DeleteSlidePosition`等)は、decompileした`ActionSelector<T>`サブクラスの`Prop<>.ShouldBe()`から直接ハードコードし、`enum_last()`で動的に読む必要を無くした(セレクタ選択時点で値が一意に確定しているため)。`pad_action_lib`側(`word_actions`/`powerpoint_actions`/`pdf_actions`)の関数シグネチャはいずれも変更不要だった。

既存の`tests/test_pad_codegen.py`の該当する合成(synthetic)バッチテスト4件(PDF×3関数+1件、Word、PowerPoint)も、同じ誤ったフラットなaction_id形式でDSLを手書きしていたため正しい3セグメント形式に修正した。

**教訓の総括**: 知見80の「検索結果TreeItemのAutomationIdを1語の検索で一括確認する」手法は、**アクショングループの存在確認**(「このアクションがPADに存在する」)としては有効だが、**真のDSL action_id文字列の確認**(「このアクションが実際にどう直列化されるか」)には使えない——後者には知見139以降確立してきた`ActionSelectorBase`一括列挙監査(decompile+リフレクション)が必須、という確証レベルの違いを明確に区別する必要がある。今後、新しいモジュールを「完了」と記録する際は、この両方を満たしていることを確認すること。

## 159. design/common_rpa_framework_roadmap.md 層3「セレクタ/モード一括発見ツールの資産化」を実装——`tools/pad_selector_audit.py`で知見155-158の手法をコミット済みスクリプトへ

知見155-158でExcel/PDF/Word/PowerPointに発見した「`ActionSelectorBase`一括列挙監査で確認したaction_id(3セグメント形式)と、`pad_codegen`側の実際の結線が食い違っている」という潜在バグのクラスを、今後の新規モジュール調査で機械的に検出できるよう、`design/common_rpa_framework_roadmap.md`の層3で構想されていたツールを実装した。

`tools/pad_selector_audit.py`は、(1) VM上の`ActionSelectorBase`派生型を列挙するリフレクションスクリプトの出力(`<BaseClass> | <SelectorClassName> | ActionName=<Name>`形式、知見139以降のテンプレート)を解析し、(2) `pad_codegen/actions/<module>.py`をASTで静的解析して文字列リテラルからaction_id形式の値を全て抽出し、(3) dump内の各セレクタについて`<Module>.<BaseClass>.<ActionName>`が結線済み集合に含まれるかを突き合わせる。`[Action(Id=...)]`によるクラス名からの上書き(知見156のPDF)は`--id-override`で明示的に指定する(decompile結果から人間が確認した値をそのまま渡すだけで、ツール自身が推測することはない)。

Excel/Word/PowerPoint/PDFの実際のVMリフレクション出力を`tools/selector_dumps/{Excel,Word,PowerPoint,PDF}.txt`としてコミットし(decompileしたC#ソース自体ではなく、知見139の標準フォーマットに整形済みの短い列挙結果のみ——従来通り逆コンパイル結果自体は非追跡の方針を維持)、ツールで検証した結果:
- PDF/PowerPoint: dump内の全セレクタが結線済み(0件の未結線候補)。
- Word: 18件の未結線候補(ワイルドカード系2件・ページ/ブックマーク読み取り2件・ブックマーク書き込み2件・`InsertImageToWord`系12件)——いずれも既知の意図的スコープ外と一致。
- Excel: 84件の未結線候補——いずれもライブExcel COM専用(`ActivateCell`/`AutoFillCells`/`ClearCells`/`SetColor`/`SortCells`等)として知見155で確認済みのスコープ外と一致。

この検証自体が、知見155-158の修正が正しく完全であること(スコープ内のセレクタに漏れが無いこと)の独立した裏付けにもなった。`tests/test_pad_selector_audit.py`にツール自身の単体テスト(埋め込みフィクスチャでの文字列抽出・dump解析・突き合わせロジック検証)と、実際の`Excel.txt`を使った回帰防止テスト(知見155で修正した8グループのうち、スコープ外と確認済みの4件以外が全て結線済みであることを確認)を追加した。

## 160. `tools/pad_selector_audit.py`を全Tier1/2モジュール+Web+UIAutomationへ適用——既存結線の完全性を独立に確認、かつUIAutomationの8アクション系統が完全に未着手だったと新規発見

知見159のツールをExcel/Word/PowerPoint/PDF以外の全モジュール(Database/Text/Cryptography/File/Folder/Variables/Cmd/Web/XML/DateTime/UIAutomation)にも適用した。`pad2py-sweep-all-selectors-v3`(新規clipwire target、複数DLLを1回のPowerShell実行でまとめて列挙——1モジュールずつ実行するより高速)で取得したリフレクション出力を`tools/selector_dumps/`に追加した。

**`--id-override`の要否に関する新知見**: Tier1/2モジュールの`*Action`接尾辞付きクラス名(例: `ConvertDateTimeToTextAction`/`CropTextAction`/`IfFileAction`/`WaitForFileAction`)は、ほぼ全てが`[Action(Id=...)]`でこの接尾辞を取り除いた名前(例: `ConvertDateTimeToText`/`CropText`/`IfFile`/`WaitForFile`)をDSLの中間セグメントとして使う——ただし`Cmd.OpenCmdSession`→`Open`・`Database.OpenConnection`→`Connect`・`Text.ReplaceTextAction`→`Replace`のような、単純な接尾辞除去ではない任意の命名もある。これらのoverride値は全て**既に実機DSLキャプチャで確認済みの既存結線(`pad_codegen/actions/*.py`)から逆算して導出した**(新たな推測は一切していない——既存結線の文字列を正解データとして使っただけ)。

**検証結果(全てスコープ内は結線完了と確認)**:
- Database/Text/Cryptography/Cmd/Web/XML/DateTime: 適切な`--id-override`を与えると、dump内の全セレクタが結線済みと一致(0件)。
- File/Folder: 単一ファイル(`file.py`/`folder.py`)だけでは`IfFile`/`WaitForFile`/`IfFolderExists`系が「未結線」に見えたが、これは`conditions.py`/`wait.py`に分散して結線されているための見かけ上のギャップだと判明——ツール自体を「`--actions-py`省略時は`pad_codegen/actions/`ディレクトリ全体を対象にする」設計に変更し解消した。
- Variables: `FindOrReplaceInDataTable`の`Replace*`系4件のみ未結線——知見123で意図的に見送った既知のギャップ(早期停止無し等)と完全に一致、想定通り。

**UIAutomation.Actions.dllの新規発見(新たなTODO)**: `CloseWindow`/`FocusWindow`/`GetWindow`/`MoveWindow`/`ResizeWindow`/`SetWindowState`/`SetWindowVisibility`/`WaitForWindow`/`WaitForWindowContent`の9系統(知見116-120で確認済み)は`...Base`/`...Action`接尾辞を除去する同じパターンで全て結線済みと確認できた。`IfWindow`/`IfImage`/`IfWindowContains`は`conditions.py`が`action_id.startswith("UIAutomation.IfWindow.")`という前方一致判定を使っており、本ツールの単純な文字列リテラル抽出では検出できない(ツールの既知の盲点、`IfWindow`自体は実際には結線済み・`IfImage`/`IfWindowContains`は`conditions.py`のコメントに明記された意図的な未対応)。

一方、以下8系統は`pad_codegen`のどのファイルにも一切登場せず、**この調査で初めて「存在すら認識していなかった未着手のアクション系統」として発見した**: `ExtractDataFromTable`/`ExtractDataFromWindow`(テーブル/ウィンドウからのデータ抽出)・`GetSelectedCheckboxesInWindow`/`GetSelectedRadiobuttonInWindow`(チェックボックス/ラジオボタンの選択状態取得)・`PopulateTextFieldInWindow`(テキストフィールド入力)・`SetDropDownListValueInWindow`(ドロップダウン操作)・`TakeScreenshotOfUIElement`(UI要素のスクリーンショット)・`WaitForImageAction`(画像の出現/消失待機、`IfImageAction`と同系統)。いずれもUI要素セレクタ(知見38以来の既知の制約でRDPが必要)を必要とするため、実装着手には実機セレクタ確認が前提になる——`pad_todo.md`に新規TODOとして記録する。

## 161. 知見160で新規発見したUIAutomationの8系統を精査——`TakeScreenshotOfUIElement`はClickと同じ`UiElementRef`機構を使うだけで実装可能と判明、新規結線完了

知見160で「UIAutomation.Actions.dllに一切着手していなかった8アクション系統を発見」と記録した直後、`pad2py-fetch-uiautomation-dll`でDLL本体を取得し`ilspycmd`でdecompileして各系統を精査した。8系統は実装難度が大きく2つに分かれると判明した。

**低リスク・新規結線した1件(`TakeScreenshotOfUIElement`、兄弟セレクタ2件)**: `Control`プロパティ(`[InputArgument(Order = 1)] public override UIControl Control`、`Name`属性の上書き無し)を持ち、これは`UIAutomation.Click.Click`の`Element`パラメータと全く同じ`UiElementRef`機構——`pad_dsl.line_parser._resolve_value()`はUI要素参照をパラメータ名ではなく値の構文(`appmask[...]`プレースホルダートークン)だけで判別するため、パラメータ名が違っても(`Element`/`Control`/`TextField`/`DropDownList`等)同じ`_build_pywinauto_selector_expr()`(知見56で確証済み)がそのまま使える。本体の動作(`capture_as_image()`でpywinautoがPIL Imageを返し`.save(path, format=...)`で保存)はpywinauto自身の標準API(RPA特有の未検証の意味論ではない)で、`ImageFormat`列挙値(`Bmp`/`Png`/`Jpeg`/`Gif`/`Tiff`)は単純に大文字化するだけでPILの`format=`引数と一致する——曖昧さの無い機能のため実機未確認でも安全に結線できると判断した。兄弟セレクタ`TakeScreenshotOfUIElement`(`SaveMode=Clipboard`固定)はOSクリップボードへの画像書き込みという別の未実装の仕組みが必要なため見送り、`TakeScreenshotOfUIElementAndSaveToFile`(`SaveMode=File`固定)のみ結線した。

**残り7系統は実装を見送った(でっち上げない判断)**:
- `PopulateTextFieldInWindow`/`SetDropDownListValueInWindow`: `Control`プロパティ自体は同じ`UiElementRef`機構(`Name`属性で`TextField`/`DropDownList`に上書き)で解決可能と確認できたが、`PopulateTextMode`(`Replace`/`Append`)の正確な挙動・`ClickType`がテキスト設定にどう影響するか・`SetDropDownListValueInWindow`の`OptionsNames`/`OptionsIndeces`/`UseRegularExpressions`の正確なマッチング規則は、実際のランタイム実装(`IAutomationRuntimeProxy.PopulateTextFieldInWindow()`/`.SetDropDownListValueInWindow()`、本DLLには実装本体が無く別のランタイムアセンブリ)に委ねられており、decompileだけでは確定できない——知見81の「Run実行+結果比較」による実機確認が必要(セレクタ解決自体は知見56で確証済みなので新たなRDP作業は不要、VM上でRun+ファイル書き出し確認すれば済む見込み)。
- `GetSelectedCheckboxesInWindow`/`GetSelectedRadiobuttonInWindow`: 逆コンパイルすると`PerformAutomation(..., (UIControl)null, true)`が常に`null`で呼ばれており、`Control`型のプロパティ自体をクラスが持たない——つまりUI要素セレクタでは無く「現在のウィンドウ全体をスキャンする」操作(出力は選択されたチェックボックス/ラジオボタンの識別名リスト)。識別名の形式(表示テキストか、AutomationIdか)が実機未確認。
- `ExtractDataFromTable`/`ExtractDataFromWindow`: ライブExcel COM(`IExcelActions`)への書き出しを伴う複合動作で、知見155のExcelスコープ(openpyxlでは再現不可)と同じ制約に直接抵触する。
- `WaitForImageAction`: `IfImageAction`と同じ`CheckImageActionBase`系列で、知見38/39/42の既知の制約(画像セレクタの実機取得にRDPが必要)がそのまま当てはまる。

テストは`tests/test_pad_codegen.py`に`TakeScreenshotOfUIElementAndSaveToFile`のexec検証テストを追加し、`tests/fake_pywinauto.py`に`.capture_as_image().save()`のフェイクを新規実装した(既存の`FakeControl`/`FakeRegistry`パターンに倣う)。

## 162. 知見156の未解決事項(`Pdf.ExtractPages`/`Pdf.MergeFiles`の`Name`属性)を解消——`Microsoft.PowerPlatform.PowerAutomate.Desktop.Actions.SDK.dll`のdecompileで、`ActionAttributeBase.Name`は`Id`の非推奨な旧名であり同じ役割だと確定

知見156で「`Pdf.ExtractPages`(`ExtractPagesToNewPDFAction`クラス)/`Pdf.MergeFiles`は`[Action(...)]`に`Id`属性が無く`Name`属性のみを持つ——`Id`無しの場合に本当にクラス名がaction_idになるのか、`Name`が何らかの形でaction_idに影響するのかは今回のdecompileだけでは確定できない」として残していた未解決事項を、SDK自体の属性定義をdecompileして解消した。

`pad2py-fetch-actions-sdk-dll`(新規clipwire target)で`Microsoft.PowerPlatform.PowerAutomate.Desktop.Actions.SDK.dll`(42,272バイト、`[Action]`属性自体や`ActionSelectorBase`が定義されている中核SDK)を取得し`ilspycmd`でdecompileしたところ、`ActionAttributeBase`(`[Action]`/`[ConditionAction]`/`[WaitAction]`の共通基底)の定義に以下を確認した:

```csharp
public abstract class ActionAttributeBase : Attribute
{
    public string Id { get; set; }
    [Obsolete("Use ActionAttribute.Id instead.")]
    public string Name { get; set; }
    ...
}
```

`Name`プロパティには`[Obsolete("Use ActionAttribute.Id instead.")]`という明示的な非推奨注記があり、これは「`Id`の旧名であり同じ役割を持つ(SDKのバージョンが上がる過程で`Name`→`Id`へ改名されたが、後方互換のため両方のプロパティが残っている)」ことを意味する——`Id`が未設定で`Name`のみ設定されているクラス(`ExtractPagesToNewPDFAction`の`Name = "ExtractPages"`、`MergeFiles`クラスの`Name = "MergeFiles"`)は、`Name`の値がそのまま中間セグメントとして使われると確定した(値を読み取る側のEngine/Runtime実装は本SDK dllには無く別アセンブリだが、`Obsolete`注記自体が「同じ用途の後継プロパティ」であることを明確に示しており、これ以上の裏付けを待たずに安全に確定できる水準の確証)。

結論: 既存の`pad_codegen/actions/pdf.py`の`Pdf.ExtractPages`/`Pdf.MergeFiles`という結線(フラットな2セグメント形式)は、当初から正しかったと確定した——修正は不要。`design/pad_todo.md`の残課題注記を解消する。

## 163. セルフレビューで知見153・152の実装に2件の潜在バグを発見・修正——Pythonコーデック命名規則とdecompile由来の`Uri.Segments`仕様の見落とし

今セッションの一連のコミット(a20e304〜d584d53)を自己レビューした結果、decompileの解釈自体は正しかったがPython側への変換に見落としがあった2件を発見した。

**1件目(`cmd_actions.py`、知見153)**: `open_cmd_session()`が`python_encoding = f"cp{codepage}"`でPythonコーデック名を組み立てていたが、`_ENCODING_CODEPAGES`の150メンバー中`IBM037=37`だけが3桁未満のコードページ番号で、Pythonの実際のコーデック名は`"cp037"`(0埋め済み)であり`"cp37"`は`codecs.lookup()`が`LookupError`になる(`codecs.lookup("cp37")`→失敗、`codecs.lookup("cp037")`→成功、を実際に確認)。既存テストは`utf_8`/`shift_jis`/`Windows_1252`/`ibm850`(いずれも3桁以上)だけを確認していたため見逃していた。`f"cp{codepage:03d}"`に修正(`chcp`へ送る整数自体は0埋め不要、知見153通り変更無し)。

**2件目(`web_actions.py`、知見152)**: `_get_download_file_path()`が、末尾が`/`で終わる**非ルート**パス(例: `/downloads/`)の場合に`path.rsplit("/", 1)[-1]`で空文字列を返していた——decompileした.NETの`Uri.Segments`は、このケースでも最後のセグメント自体に末尾の`/`を含める(`segments = ["/", "downloads/"]`)ため、正しい変換は`"downloads/"`(その後`_sanitize_file_name()`で`/`自体が`_`に置換されるため最終的には`"downloads_"`)。真のルートパス(`path == "/"`)のケースは既に正しく処理されていたが、「非ルートかつ末尾が`/`」という中間ケースが未対応だった。

両方とも、実際のPAD/pywinauto実行では発生しにくいエッジケース(IBM037は稀な中国語/EBCDIC系コードページ、末尾スラッシュのダウンロードURLは非典型)だが、decompileした.NET側の仕様とPython実装の間の不一致という意味では紛れもないバグだったため修正し、再発防止のテストを追加した。

## 164. `ActionSelectorBase`一括列挙監査には「兄弟セレクタを持たないフラットな`[Action]`クラス」を見落とす盲点があると発覚——UIAutomation.Actions.dllに新たに15系統を発見、`FocusTextField`を新規結線

知見139以降確立してきた`ActionSelectorBase`一括列挙監査(`ActionSelectorBase`派生型をリフレクションで列挙する)には、**兄弟セレクタを一切持たない単一の`[Action]`クラス自体は検出されない**という構造的な盲点があると気づいた——`ActionSelectorBase`派生型の一覧には、そのクラスを**対象とする**セレクタしか現れないため、セレクタが1つも無いクラス(知見155のExcelの`AddWorksheet`等と同じパターン)は一覧に載らない。知見160の「UIAutomation.Actions.dllに8系統が未着手」という調査も、この盲点のせいで**氷山の一角**だったと判明した。

VM上で`[Action]`/`[ConditionAction]`/`[WaitAction]`属性を持つ全クラス(セレクタの有無を問わず)を直接列挙し、`ActionSelectorBase`一括列挙の結果(セレクタを持つクラスの集合)と突き合わせたところ、**セレクタを持たないクラスが新たに15個**見つかった(`tools/selector_dumps/UIAutomation_flat_actions.txt`に保存): `GetDetailsOfElementInWindow`(→`GetElementDetails`)・`GetUIControl`・`GetWindowDetails`・`DragAndDropElementInWindow`(→`DragAndDropElement`)・`ExpandCollapseTreeNodeInWindow`(→`ExpandCollapseTreeNode`)・`FocusTextFieldInWindow`(→`FocusTextField`)・`PressWindowButton`(→`PressButton`)・`SelectRadioButtonInWindow`(→`SelectRadioButton`)・`SetCheckboxStateInWindow`(→`SetCheckboxState`)・`IfRemoteDesktopIsAvailableAction`(→`IfRemoteDesktopIsAvailable`)・`SelectMenuOptionInWindow`(→`SelectMenuOption`)・`SelectTabInWindow`(→`SelectTab`)・`UseDesktop`・`WaitForRemoteDesktopAction`(→`WaitForRemoteDesktop`)・`HoverOnElementInWindow`(→`HoverOnElement`)。いずれも`pad_codegen`には一切登場せず、今回初めて存在を認識した。

このうち`FocusTextFieldInWindow`(`[Action(Name = "FocusTextField")]`、知見162で確認済みの`Name`=`Id`の旧名)はdecompileで精査した結果、`TakeScreenshotOfUIElement`(知見161)と全く同じ低リスク条件を満たしていた——`TextField`パラメータが`Click.Click`の`Element`と同じ`UiElementRef`機構、動作も`.set_focus()`(`UIAutomation.FocusWindow`系で既に実コード生成に使っている確証済みのpywinauto操作)そのもので曖昧さが無いため、実機未確認のまま安全に新規結線した。

**他の候補の実装可否(decompile精査済み、未着手)**:
- `PressWindowButton`: `Button`パラメータ(同じ`UiElementRef`機構)+`Simulate`(bool)。`Simulate=False`→`r.PressButtonInWindow(e)`(UIAの`InvokePattern`相当、pywinautoの`.invoke()`——本プロジェクトのRun実行用アドホックスクリプトで既に使用実績あり、知見81)、`Simulate=True`→`r.SimulateClickElementInWindow(e)`(`.click_input()`と同じ)。2つのpywinautoメソッドを`Simulate`で動的に切り替えるだけで実装可能——低リスクだが`.invoke()`のフェイク実装(`tests/fake_pywinauto.py`)が未整備のため次回以降に持ち越し。
- `HoverOnElementInWindow`/`SelectTabInWindow`/`SelectMenuOptionInWindow`/`SelectRadioButtonInWindow`/`SetCheckboxStateInWindow`/`ExpandCollapseTreeNodeInWindow`/`DragAndDropElementInWindow`: 未精査(セレクタ機構は同じ`UiElementRef`の可能性が高いが、個々の動作の正確なpywinauto対応は未確認)。
- `GetDetailsOfElementInWindow`/`GetUIControl`/`GetWindowDetails`: UI要素の属性/詳細を読み取る系——`AttributeName`が`SuggestedValues`付きの自由文字列(`"Own Text"`/`"Exists"`/`"Location and Size"`/`"Enabled"`)で、各値が実際にどのUIAプロパティに対応するかは実機/decompileでの追加確認が必要。
- `UseDesktop`/`IfRemoteDesktopIsAvailableAction`/`WaitForRemoteDesktopAction`: リモートデスクトップ機能専用——このプロジェクトのスコープ外である可能性が高い。

テストは`tests/test_pad_codegen.py`に`FocusTextField`のexec検証テストを追加した。`design/pad_todo.md`に残り14候補を新規TODOとして記録する。

## 165. 知見164の「フラット`[Action]`クラス」監査を全モジュールへ拡大適用——`Variables.FilterList`を新規結線、Excel/Word/PowerPointに追加のCOM専用/openpyxl候補を発見

知見164でUIAutomation.Actions.dllに適用した「`[Action]`/`[ConditionAction]`/`[WaitAction]`属性を持つ全クラスを直接列挙し、`ActionSelectorBase`一括列挙の結果(セレクタを持つクラスの集合)と突き合わせる」手法を、`pad2py-sweep-all-flat-actions`(新規clipwire target、複数DLLを1回で処理)で残りの主要モジュール(Database/Web/XML/Cmd/Clipboard/DateTime/Text/Cryptography/File/Folder/Variables/Compression/Excel/Word/PowerPoint/PDF)にも適用した。結果は`tools/selector_dumps/_all_modules_flat_actions_raw.txt`に保存し、既存の結線済みaction_id集合と突き合わせたところ、ほとんどは既に結線済みと確認できた(Database/Web/XML/Cmd/Clipboard/DateTime/Cryptography/File/Folder/Compressionは1件の未結線も無し)。

**新規発見・結線1件(`Variables.FilterList`)**: `Variables.Actions.dll`に兄弟セレクタの無いフラットなアクションとして存在し、これまで全く未着手だった。decompileした`FilterListUtilities.EvaluateFilterConditions()`/`EvaluateSingleCondition()`から、`FilterParameters`は知見90の`FilterDataTable`と同じ`OPERATOR`/`VALUE`/`RULE`列を持つDataTable(`COLUMN`列は無い——各リスト項目そのものが評価対象)で、OR区切りのAND-group群として評価する同じ構造だと確認した。

**`FilterList`特有の非自明な挙動(decompile確認済み)**: `IgnoreCase`は単なる大文字小文字の区別だけでなく、`Equal`/`NotEqual`の**比較アルゴリズム自体を切り替える**——`IgnoreCase=True`の場合は文字列化した値同士の単純な大文字小文字区別無し比較(クロス型の数値文字列同値判定はしない)、`IgnoreCase=False`の場合のみ`ComparisonCalculator.Compare`(=`expr_runtime.pad_equal()`、知見85/88のクロス型同値判定)に委譲する。これは`FilterDataTable`/`JoinDataTable`の`MatchCase`/暗黙の規則とは異なる、`FilterList`固有の仕様。

`GreaterThan`/`GreaterThanOrEqual`/`LessThan`/`LessThanOrEqual`(実機のクロス型比較規則が知見97のJoinDataTableの「常に文字列比較」と矛盾しうるため未確認)と`IsBlank`/`IsNotBlank`(PADの`Blank`値に対応するPython表現がこのプロジェクトには無い)は、でっち上げず`NotImplementedError`にした——Contains/NotContains/StartsWith/NotStartsWith/EndsWith/NotEndsWith/IsEmpty/IsNotEmpty/Equal/NotEqualの10演算子のみ実装。

**Excel/Word/PowerPointの追加候補(未実装のまま記録)**: `Excel.Attach`/`Word.Attach`/`PowerPoint.AttachToRunningPowerPoint`(いずれもライブCOMプロセスへのアタッチ、知見155のスコープ外パターンと同じ)、`Excel.RunMacro`(ライブExcel COM専用)、`Excel.GetSelectedCellRange`(ライブUIの現在選択範囲、同スコープ外)、`Excel.DeleteColumn`/`DeleteRow`/`InsertColumn`/`InsertRow`(openpyxlの`delete_cols()`/`delete_rows()`/`insert_cols()`/`insert_rows()`に対応しそうな有力候補、未精査)、`Excel.GetTableRange`(Excel Table構造体のレンジ取得、COM専用か要確認)、`PowerPoint.CopyPastePowerPointSlide`(クロスプレゼンテーションのコピー、`MovePowerPointSlide`と同種の複合動作)。`design/pad_todo.md`に新規TODOとして記録する。

テストは`tests/test_pad_action_lib_variables.py`に`filter_list()`の単体テスト8件、`tests/test_pad_codegen.py`にCSVシード経由のend-to-end exec検証1件を追加した。

## 166. 知見165で記録した`Excel.DeleteColumn`/`DeleteRow`/`InsertColumn`/`InsertRow`を新規結線、`Excel.GetTableRange`はCOM/Table依存のため未着手のまま保留

知見165で発見したExcel追加候補のうち、`DeleteColumn`/`DeleteRow`/`InsertColumn`/`InsertRow`の4件を`/tmp/.../excel_dll/decompiled/Excel.Actions.decompiled.cs`から直接decompile精査した(セッション前半で取得済みのDLLを再利用)。4件とも`ActionSelectorBase`の兄弟セレクタを持たないフラットな`[Action]`クラスで(`tools/selector_dumps/_all_modules_flat_actions_raw.txt`の`EffectiveId=`空欄=クラス名そのものが`action_id`、知見164のルール通り)、パラメータは`Instance: ExcelInstanceHandle`+`Column: string`(Delete/InsertColumn)または`Instance`+`Index: int`(Delete/InsertRow)のみ——セレクタの曖昧さも無い。ライブExcel COMの`ExcelActions.DeleteColumn()`等を直接呼ぶだけで、スプレッドシート上の列/行シフト操作という単純明快な意味なので、`openpyxl`の`Worksheet.delete_cols()`/`delete_rows()`/`insert_cols()`/`insert_rows()`(いずれもスタート位置+amount=1)に1:1で対応すると確認し、実機未確認のまま安全に新規結線した(知見161/164で確立した「セレクタ機構が既知かつ単一の曖昧さ無しライブラリ呼び出しに1:1対応する」低リスク追加の基準を満たす)。

`ColumnNotFoundError`(decompile確認: `Column`の書式が不正、または`ActionException.ID==1`相当)は`openpyxl.utils.column_index_from_string()`が`ValueError`を投げるケースにマップした。`RowNotFoundError`は`Index`が1未満の場合に対応させた(decompile上は native呼び出し内部の検証だが、Pythonの`delete_rows`/`insert_rows`自体は0以下のindexでも例外を投げずに無言で奇妙な動作をするため、同等の防御的チェックを明示的に追加した——これは実機の正確なエラー条件の模倣ではなく、「本来エラーになるべき入力でPython側が黙って誤動作する」ことを防ぐための安全策)。`DeleteColumnError`/`InsertColumnError`/`DeleteRowError`/`InsertRowError`はそれ以外の`openpyxl`例外を包んだ。

`Excel.GetTableRange`(`IsPivot`フラグで`GetTableRange`/`GetPivotTableRange`のどちらかをネイティブに呼ぶ)は保留を継続する——`openpyxl`は名前付きTable自体は`Worksheet.tables[name].ref`で読めるが(1)PADの`Instance`はワークブック全体を指す一方Table名はワークシートをまたいで検索する必要があり既存コードに前例の無い探索が要る、(2)`IsPivot=True`のPivotTableレンジ取得は`openpyxl`に対応するAPIが無い(ライブExcel COM専用の機能)——`IsPivot`分岐の半分だけ実装するのはでっち上げに近いため、両分岐とも未着手のまま`design/pad_todo.md`に残す。

実装: `dump_daemon/pad_action_lib/excel_actions.py`に`delete_column`/`insert_column`/`delete_row`/`insert_row`と対応する例外(`ColumnNotFoundError`/`DeleteColumnError`/`InsertColumnError`/`RowNotFoundError`/`DeleteRowError`/`InsertRowError`)を追加。`dump_daemon/pad_codegen/actions/excel.py`に`Excel.DeleteColumn`/`Excel.InsertColumn`/`Excel.DeleteRow`/`Excel.InsertRow`の4フラットaction_idを新規結線。テストは`tests/test_pad_action_lib_excel.py`に単体テスト8件、`tests/test_pad_codegen.py`の既存Excel全スコープバッチテストに4行追加して検証した。

## 167. 知見164の残課題`PressWindowButton`(→`UIAutomation.PressButton`)を新規結線——`Simulate`で`.invoke()`/`.click_input()`を切り替え

知見164で「`PressWindowButton`は低リスクだが`.invoke()`の`tests/fake_pywinauto.py`フェイクが未整備」と記録していた残課題を解消した。`pad2py-pad-host`のVMが他セッション(`pad2py-57`)でbusyだったため、VM非依存の純粋なdecompile再精査+ローカルコード実装という方針を選んだ(既にセッション前半で取得済みの`UIAutomation.Actions.dll`の decompile結果をそのまま再利用、新規のVM操作は無し)。

`PressWindowButton`クラス(`[Action(Name = "PressButton", Category = "FormFilling")]`、知見162確認済みの`Name`=`Id`の旧名——`tools/selector_dumps/UIAutomation_flat_actions.txt`で`EffectiveId=PressButton`と確認——action_idは`UIAutomation.PressButton`)の`Execute()`をdecompile精査した: `Button`パラメータ(`UIControl`型、`Click.Click`の`Element`と全く同じ`UiElementRef`機構)で特定した要素に対し、`Simulate`(bool、既定`False`)で2つの完全に異なるネイティブ呼び出しを切り替えるだけだと確認した——`Simulate=False`→`PressButtonInWindow`(UIAの`InvokePattern`経由、pywinauto標準APIの`.invoke()`に1:1対応)、`Simulate=True`→`SimulateClickElementInWindow`(既に`Click.Click`で実機確認済みの`.click_input()`と同じ合成マウスクリック)。いずれも単一の曖昧さ無しライブラリ呼び出しで、知見161/164/166で確立した低リスク追加の基準を満たすため、実機未確認のまま安全に新規結線した。

`tests/fake_pywinauto.py`の`FakeControl`に`.invoke()`(呼び出しログに`"invoke"`を記録するだけの最小フェイク)を追加——ドキュメント先頭の「対応しているAPI表面」リストも更新した。

実装: `dump_daemon/pad_codegen/actions/ui_element.py`に`UIAutomation.PressButton`の分岐を追加(`Simulate`の真偽で`method = "click_input" if simulate else "invoke"`)。テストは`tests/test_pad_codegen.py`に`Simulate=False`/`Simulate=True`両方のexec検証テストを追加した。

## 168. 知見164の残課題`HoverOnElementInWindow`(→`UIAutomation.HoverOnElement`)を新規結線——`click_input(button='move')`で実装

知見164の残課題リストにあった`HoverOnElementInWindow`/`SelectTabInWindow`/`SelectMenuOptionInWindow`/`SelectRadioButtonInWindow`/`SetCheckboxStateInWindow`/`ExpandCollapseTreeNodeInWindow`/`DragAndDropElementInWindow`の7系統をdecompile精査する中で、最も単純だった`HoverOnElementInWindow`を先行実装した(残り6系統は個々の動作のpywinauto対応がまだ不明瞭なため、知見164の記載通り未精査のまま継続する——でっち上げず1件ずつ精査する方針)。`pad2py-pad-host`VMが他セッションでbusyのため、今回も既存decompile結果の再利用のみで新規VM操作は行っていない。

`HoverOnElementInWindow`クラス(`[Action(Name = "HoverOnElement")]`、知見162の`Name`=`Id`——`tools/selector_dumps/UIAutomation_flat_actions.txt`で`EffectiveId=HoverOnElement`確認——action_idは`UIAutomation.HoverOnElement`)の`Execute()`は`PerformAutomation(... (r, e) => r.HoverOnElementInWindow(e) ...)`のみで、`Element`パラメータ(`UIControl`、`Click.Click`の`Element`と同じ`UiElementRef`機構)以外に意味論を左右する分岐が一切無い——ネイティブ側の「クリックせず要素へマウスを移動する」という単純な意味。

pywinautoの`base_wrapper.BaseWrapper.click_input()`を調べ(`.venv/lib/python3.12/site-packages/pywinauto/base_wrapper.py`)、`button='move'`(docstring: "`button` 引数は'left'/'right'/'middle'/'x'、'move'は特殊ケース")を指定した場合は`button_down`/`button_up`を一切送らずマウスを要素中心(既定の`coords=(None, None)`)へ移動するだけだと確認した——これは`move_mouse_input()`の内部実装そのもの(`move_mouse_input`は`click_input(button='move', ...)`を呼ぶだけの薄いラッパー)でもあり、pywinauto公式の「クリックせず移動する」唯一の標準手段。単一の曖昧さ無しライブラリ呼び出しなので、知見161/164/166/167の低リスク基準を満たすと判断し、実機未確認のまま安全に結線した。`tests/fake_pywinauto.py`への追加は不要(既存の`.click_input(**kwargs)`フェイクがそのまま`button='move'`も記録できる)。

実装: `dump_daemon/pad_codegen/actions/ui_element.py`に`UIAutomation.HoverOnElement`の分岐を追加。テストは`tests/test_pad_codegen.py`にexec検証テストを1件追加した。

## 169. 知見164/168の残課題`SelectTabInWindow`/`SelectRadioButtonInWindow`/`SetCheckboxStateInWindow`を新規結線——`.select()`/`.toggle()`+`get_toggle_state()`の冪等パターン

知見168に続き、残り6系統のうち構造が単純な3件をdecompile精査・結線した(`SelectMenuOptionInWindow`/`ExpandCollapseTreeNodeInWindow`/`DragAndDropElementInWindow`は個々の動作がまだ不明瞭なため未精査のまま継続)。VMは依然busyのため、今回も既存decompile結果の再利用のみ。

**`SelectTabInWindow`(→`UIAutomation.SelectTab`、`Tab`パラメータ)/`SelectRadioButtonInWindow`(→`UIAutomation.SelectRadioButton`、`RadioButton`パラメータ)**: 両方とも`Execute()`は`PerformAutomation(... (r, e) => r.SelectTabInWindow(e)/r.SelectRadioButtonInWindow(e) ...)`のみで、他の分岐が無い全く同じ構造。pywinautoの`controls/uiawrapper.py`の`UIAWrapper.select()`(`iface_selection_item.Select()`、UIAの`SelectionItemPattern`)のdocstringに「通常ラジオボタン・ツリービュー項目・リスト項目に使う」と明記されており、タブ項目もUIAの`SelectionItemPattern`を実装する標準コントロールのため1:1対応すると判断した。

**`SetCheckboxStateInWindow`(→`UIAutomation.SetCheckboxState`)**: `Execute()`は`r.SetCheckboxStateInWindow(e, CheckboxState == CheckboxState.Checked)`——目的の真偽状態(`CheckboxState`列挙は`Checked`/`Unchecked`の2値のみ、decompile確認済み)を渡すだけ。pywinautoの`controls/uia_controls.py`の`ButtonWrapper.toggle()`のdocstring自体に「チェックボックスの状態を切り替えるだけ(ラジオボタンには`select()`を使うこと、ラジオボタンはUIAでToggle未対応)」と明記されている通り、UIAのCheckBoxは`TogglePattern`しか持たず`Toggle()`は状態を一方向に切り替えるだけ(目的の状態へ直接設定するAPIが無い)——これはPAD側の推測ではなくUIA自体の制約。`get_toggle_state()`(`0`=unchecked/`1`=checked)で現在状態を読み、目的の状態と異なる場合のみ`toggle()`する冪等パターンで実装した(現在状態が既に目的通りならtoggleしない——これが「目的の状態に設定する」の唯一の正しい実装)。

`tests/fake_pywinauto.py`に`.select()`(呼び出し記録のみ)と、`.toggle()`/`.get_toggle_state()`(`FakeRegistry`に`_toggle_states`状態を追加、`toggle()`実行時に実際に0↔1を反転させる——「既に目的状態ならtoggleしない」という冪等性をテストで検証できるようにするため、単なる呼び出し記録だけでなく最小限の状態遷移を実装した)を追加した。

実装: `dump_daemon/pad_codegen/actions/ui_element.py`に`UIAutomation.SelectTab`/`UIAutomation.SelectRadioButton`/`UIAutomation.SetCheckboxState`の3分岐を追加。テストは`tests/test_pad_codegen.py`に4件(select系2件、checkbox系2件——toggleする場合/しない場合)追加した。

## 170. 知見164/169の残課題`DragAndDropElementInWindow`を新規結線——`Click.Click`と同じ検証済みパラメータ組み合わせに限定、`SelectMenuOptionInWindow`/`ExpandCollapseTreeNodeInWindow`は依然保留

知見169の残り3系統(`SelectMenuOptionInWindow`/`ExpandCollapseTreeNodeInWindow`/`DragAndDropElementInWindow`)をdecompile精査した。

**`SelectMenuOptionInWindow`は保留継続**: `Execute()`は`r.SelectMenuOptionInWindow(e)`のみを呼ぶ構造自体は`SelectTabInWindow`/`SelectRadioButtonInWindow`(知見169)と同じだが、`Control`プロパティのNameオーバーライドが無い(ベースクラスの既定名のまま)。問題はpywinauto側の対応手段の曖昧さ——メニュー項目はネイティブWin32メニューがUIAに変換される際、`SelectionItemPattern`(知見169の`.select()`)・`InvokePattern`(`.invoke()`、知見167)のどちらを実装するかコントロールの種類次第で一定しない(decompileした`SelectMenuOptionInWindow`自身にはパターン選択ロジックが見えず、ネイティブ側のランタイムプロキシ実装——`UIAutomation.Core.dll`相当、未取得——にしか判定ロジックが無い)。でっち上げずに1つを選ぶ根拠が無いため保留のまま。

**`ExpandCollapseTreeNodeInWindow`は保留継続**: `FoldersPath`(文字列、"/"区切りのツリーパスらしき名前)+`UseRegex`(bool)+`Operation`(Expand/Collapse)という3パラメータを持ち、ネイティブ側で`r.ExpandCollapseTreeNodeInWindow(e, FoldersPath, expandInsteadOfCollapse, UseRegex)`を呼ぶ——複数階層のツリーノードを名前(または正規表現)で辿りながら各階層を展開/折りたたむという複合操作で、`Click.Click`型の「1要素+固定パラメータ」パターンとは異質。正確な走査アルゴリズム(大文字小文字区別・部分一致/完全一致・各階層でのExpandCollapsePattern呼び出し順序等)はネイティブ側実装(未取得)にしかなく、推測で実装するとでっち上げになるため保留。

**`DragAndDropElementInWindow`は新規結線**: `Control`(→`ControlToDrag`)+`ControlToDropOver`(いずれも`Click.Click`の`Element`と同じ`UiElementRef`機構)に加え、`ClickType`(`LeftClick`/`RightClick`の2値)・`MouseDownOffsetX/Y`・`MouseUpOffsetX/Y`・`RectangleEdgePointForMouseDown/Up`(`Click.Click`と全く同じ`RectangleEdgePoint`列挙、9点グリッド)を持つ——ネイティブ側で`DragAndDropElementInWindow(dragElement, dropElement, ...)`を呼ぶだけ。知見56で実機確認済みなのは`Click.Click`の`ClickType=LeftClick`・`RectangleEdgePoint=MiddleCenter`・オフセット0/0の組み合わせのみなので、全く同じ制約をここにも適用した——この組み合わせに限れば、pywinautoの`base_wrapper.BaseWrapper.drag_mouse_input(dst=..., src=None, button="left")`(`src`省略時は呼び出し元自身、`dst`に別の`BaseWrapper`を渡すと`_calc_click_coords()`で中点座標を自動計算する——まさに「MiddleCenter+オフセット0/0」の意味そのもの)に1:1対応する単一の曖昧さ無しライブラリ呼び出しだと確認し、安全に結線した。`RightClick`・矩形基準点変更・オフセット有りの組み合わせは実機未検証のため、`Click.Click`と同じ方針で安全にTODOへ倒す。

`tests/fake_pywinauto.py`に`.drag_mouse_input(dst: FakeControl)`(`dst`のフルパスを記録するだけの最小フェイク)を追加。

実装: `dump_daemon/pad_codegen/actions/ui_element.py`に`UIAutomation.DragAndDropElement`の分岐を追加。テストは`tests/test_pad_codegen.py`に検証済み組み合わせのexecテスト1件・未検証組み合わせのTODOフォールバックテスト1件を追加した。

## 171. 知見165に記録した「おそらくライブCOM専用」の6候補をdecompileで確定確認——`Excel.Attach`/`Word.Attach`/`PowerPoint.AttachToRunningPowerPoint`/`Excel.RunMacro`/`Excel.GetSelectedCellRange`/`PowerPoint.CopyPastePowerPointSlide`

知見165/166/170で「ライブCOM専用、知見155のスコープ外パターンと同じ可能性が高い」として「未精査」のまま`design/pad_todo.md`に残していた6候補について、既存の決定を裏付けるだけでなく、実際にdecompileして確定させた——「可能性が高い」止まりだと将来のtickで同じ候補を何度も再調査しかねないため、実装こそ不要だが確認自体は済ませる方針で1件ずつ見た。

- `Excel.Attach`(`AttachToRunningExcel`): `ExcelActions.AttachToRunningExcelDocument(...)`を呼ぶ——ライブExcel COMプロセスへの直接アタッチ。
- `Excel.RunMacro`(`RunExcelMacro`): `ExcelActions.RunMacro(instance, macro)`を呼ぶ——ライブExcelインスタンス上でVBAマクロを実行する、`openpyxl`に対応物が存在しない機能。
- `Excel.GetSelectedCellRange`(`GetSelectedCellRange`): `ExcelActions.GetSelectedCellRange(...)`を呼ぶ——ライブExcel UIの「現在の選択範囲」を読む。ファイルベースの`openpyxl`には対話的に操作中のUI状態という概念自体が無い。
- `Word.Attach`(`AttachToRunningWord`): `Excel.Attach`と同型のライブWord COMプロセスへの直接アタッチ。
- `PowerPoint.AttachToRunningPowerPoint`(`AttachToRunningPowerPoint`): 同様にライブPowerPoint COMプロセスへの直接アタッチ。
- `PowerPoint.CopyPastePowerPointSlide`(`CopyPastePowerPointSlide`): `SourceInstance`/`DestinationInstance`という**2つの独立した`PowerPointInstanceHandle`**を受け取り、`_powerPointOperations.CopyPasteSlide(source, sourcePos, dest, destPos)`を呼ぶ——クロスプレゼンテーションのスライドコピーという、`dump_daemon/pad_action_lib/powerpoint_actions.py`のモジュールdocstライン自身が最初から明記していた既知のスコープ外機能と完全に一致する構造だと確認した。

6件全て、該当する`pad_codegen/actions/*.py`に専用dispatchが元から存在せず(確認済み)、汎用の`# TODO: map PAD action: ...`フォールバックに安全に落ちる——コード変更は不要。`design/pad_todo.md`の該当項目を「未精査」から「decompileで確定確認済み(対応不要)」に更新し、今後のtickで同じ候補を再調査しないようにした。

## 172. 知見170の保留2件(`SelectMenuOptionInWindow`/`ExpandCollapseTreeNodeInWindow`)——`IAutomationRuntimeProxy`の実装自体がRPC越しのサンドボックスプロセスにあり、静的decompileでは原理的に解決不可と確定

知見170で「ネイティブ側ランタイムプロキシ実装(`UIAutomation.Core.dll`相当、未取得)でしか判定できない」と記録した2件について、`pad2py-pad-host`が一時的にidleになったタイミングで、Designer UIには一切触れない読み取り専用のリフレクション調査(clipwire exec、既存の「busy/idle問わず安全」の方針通り)を実施し、実装の所在を確定させた。

`C:\Program Files (x86)\Power Automate Desktop`配下の全5685 DLLを`[System.Reflection.Assembly]::LoadFrom()`→`GetInterfaces()`で走査し、`IAutomationRuntimeProxy`(またはそれに似た名前)を実装する型を検索した。唯一のヒットは`Microsoft.Flow.RPA.Desktop.Modules.UIAutomation.Common.dll`の`RemoteAutomationRuntimeProxy`クラス——これを`ilspycmd`でdecompileした結果、**`System.Reflection.DispatchProxy`派生の汎用動的プロキシ**だと判明した。`Invoke(MethodInfo targetMethod, object[] args)`は`targetMethod.Invoke(_automationServerEndpoint.GetService<IAutomationRuntimeProxy>(), args)`——メソッド名を見ずに全呼び出しをそのまま別プロセス(`IAutomationServerEndpoint`、RPCでのサンドボックス化されたオートメーション実行ワーカー)へ中継するだけで、`SelectMenuOptionInWindow`/`ExpandCollapseTreeNodeInWindow`固有のロジックはこのクラスにも、スキャンした他のどのDLLにも存在しない。

つまり、これら2件(および`IAutomationRuntimeProxy`インターフェースの全メソッド)の実際の挙動は、.NETアセンブリとして静的に取得・decompileできる範囲の外(別プロセスのネイティブまたは別ランタイムの実装、あるいは動的生成されたアセンブリ)にある——「decompileで突き止める」というこのセッション全体の中核手法が原理的に適用できない領域だと確定した。これ以上の追跡はPAD自体の内部プロセス境界を越えるリバースエンジニアリングになり、知見38/39/42由来の「RDPでの実機確認」で挙動を観察する以外に道が無い。`design/pad_todo.md`を「decompileでは解決不可と確定、RDP実機確認が必要」に更新した。

## 173. `PopulateTextFieldInWindow`の実機確認を試み、clipboard-paste技法がこのセッションの現在のデスクトップ状態では効かないという新しい環境的制約を発見(RDP不要のはずが、実質的にブロックされている)

`pad2py-pad-host`が長時間idleだったため、`design/pad_todo.md`で「RDP不要、知見81の`Run実行+ファイル書き出し確認`で解決できる見込み」と記録していた`PopulateTextFieldInWindow`の`Mode`(Replace/Append)・`ClickType`・`Simulate`の実際の挙動を確認する試みを行った。手順は[[pad2py_clipboard_paste_technique]]/[[pad2py_run_without_rdp]]に記録済みの確立手法通り: (1) Notepad起動、(2) PAD Consoleで新規フロー作成(`pad2py_populate_probe`、`New flow`ボタン`.invoke()`→ダイアログの`Edit "Flow name"`に`.set_text()`→`Button "Create"` `.invoke()`、確立済みの手順)、(3) `UIAutomation.PopulateTextField TextField: appmask[既存のNotepad捕獲セレクタ] Text: $'''Hello PAD2PY''' Mode: UIAutomation.PopulateTextMode.Replace Simulate: True`をControlRepository付きでクリップボードへ設定、Designerの`List "Actions"`を`.set_focus()`→`.type_keys("^v")`でペースト。

**ペーストが一切反映されなかった**(`List "Actions"`は`"You don't have any actions here yet"`のまま、`"0 Actions"`)。クリップボード自体の内容はWindows側で独立に`Get-Clipboard`相当(`[System.Windows.Forms.Clipboard]::GetText()`)で読み返して正しく設定されていたことを確認済み(意図したDSL行+ControlRepository JSON、4039文字、文字化け無し)——問題はペースト対象側にあると確定。生のUIA `GetFocusedElement()`(comtypes経由)で`.set_focus()`直後の実際のフォーカス先を確認したところ、**`"Desktop 1"`(ControlType 50033=Pane、PADウィンドウの外)にフォーカスが残っていた**——`.set_focus()`自体は例外を出さず「成功」したように見えるが、実際のWin32キーボードフォーカスはPADウィンドウの中に全く移動していなかった。

この挙動は[[pad2py_clipboard_paste_technique]]が記録した過去の成功例(知見75の`IfFunctionRecord`キャプチャ、知見81の`Run`実行検証)とは異なる——これらは既にアクションが存在する`List`、またはRun実行自体(キーボードフォーカス移動を伴わない`.invoke()`のみ)だった可能性が高く、**空の`List "Actions"`への新規ペーストという操作自体を伴うテストは、このセッションではこれが初めてだった**。推測(未確証、次回要検証): 過去の成功時には直近にRDP接続があり、WindowsのデスクトップセッションがUI操作に必要な「アクティブ」状態を保持していた可能性がある——今回は長時間RDP接続が無い状態での試行であり、空のWPFリスト(既存の項目=キーボードナビゲーションカーソルの足がかりが無い)への`.set_focus()`が、アクティブでないデスクトップ上では実際のフォーカス移動を引き起こせないという、知見81/82で既知だった「アクティブデスクトップが必要な操作」のカテゴリが、**既存の知見より広い範囲(空のリストへの初回ペースト)にも及ぶ**ことを示唆している。

試験後は即座にクリーンアップした: Designerの`Button "Close window"` `.invoke()`でフローを閉じ(未保存確認ダイアログも出ず、アクション0件のまま正常終了)、Notepadプロセスを`Stop-Process`で終了。`pad2py_populate_probe`という名前の空のフロー自体は(削除には追加のUI操作が必要なため)PADのフロー一覧に残存している——実害は無いコスメティックな残骸として許容した。

`design/pad_todo.md`を更新: `PopulateTextFieldInWindow`/`SetDropDownListValueInWindow`は依然「RDP不要」の分類のままだが、**この具体的な技法(空canvasへのclipboard-paste)は現在のVM状態では機能しないと確認済み**——次回挑戦する際は、(a) RDPが接続された直後の状態で再試行する、または(b) 知見78の「検索→キーボードaddで項目を先に作ってから、既存項目のあるListへペースト/編集する」という既存項目ありの状態でのペーストに切り替える、のいずれかを先に試すべきとの教訓を記録した。

## 174. 知見124/129/130が繰り返し指摘していた「文字列一致だけの`compile()`テストは実際の出力変数の値を一度も検証していない」という死角を、Excel/Word/PowerPointの「全スコープバッチ」テストに対して横断的に塞いだ——PowerPointの既存DSLは実際に`exec()`すると**クラッシュする**ことが新規発見された

知見173でVM作業が一時的にブロックされたため、VM不要のテスト基盤強化へ切り替えた。`tests/test_pad_codegen.py`内で`compile(code, "<generated>", "exec")`は呼ぶが`exec(code, ...)`を一度も呼ばないテストを機械的に検索したところ、`test_generate_python_from_excel_full_scope_in_batch_converts_all_actions`/`..._word_..`/`..._powerpoint_..`(いずれも複数アクションを一括で結線確認する最重要テスト)が該当すると判明した——知見124「`AddRowToDataTable`」・知見129「`ZipFile`出力の`None`化」・知見130「`Folder.Copy`の`Destination`意味論」という、このセッションで繰り出されてきた実バグは全て「生成コードの文字列は正しいが、実際に実行した結果は検証していない」という同一の死角から見つかったもので、この死角自体がExcel/Word/PowerPointの最重要end-to-endテストにまだ残っていた。

**Excel**: `test_generate_python_from_excel_full_scope_batch_actually_executes_correctly`を新規追加(`tempfile`で実在する一時パスへ`SaveAs`、`Save`(パス未指定)は`NewDocument`では必ず失敗するため意図的に別の兄弟セレクタへ差し替え)。`CellValue`/`SheetName`/`SheetIndex`/`SheetNames`/`ColumnName`/`FreeCol`/`FreeRow`/`FreeRowOnA`の全出力値を実際に計算・アサートし、保存後のファイルを`openpyxl.load_workbook()`で再読込して最終状態も確認した——**一発で全て正しく通り、新規バグは発見されなかった**(手計算した期待値と完全一致)。

**Word**: `test_generate_python_from_word_full_scope_batch_actually_executes_correctly`を新規追加。`FindAndReplaceWord`の効果を実際に観測するため2回目の`ReadFromWord`を追加し(元のDSLは`TextToFind: 'a'`で対象テキスト`"hello"`に`'a'`が無く効果が見えないテストだったため、`'hello'→'world'`に変更——テスト対象のaction_id自体は変更していない)、置換前後の`WordData`/`WordData2`を実際に比較・保存後のdocxを再読込して検証した——**こちらも一発で通り、新規バグ無し**。

**PowerPoint(本件が今回の最大の発見)**: 旧テストの`compile()`専用DSL(`AddPowerPointSlide`で1枚追加→`WriteToPowerPoint`→`ReadFromPowerPoint`→`DeletePowerPointSlide.DeleteSlideLast`で**その1枚を削除**→`MovePowerPointSlide`(`SourceSlidePosition: 1`/`DestinationSlidePosition: 2`))を実際に`exec()`してみたところ、**`MovePowerPointSlide`の時点でスライドが0枚になっており、`move_power_point_slide()`内の`source_slide_position > count`チェックで`MoveSlideInvalidSourcePositionError`が投げられてクラッシュする**ことが分かった——これは丸6セッション以上「実行して確認済み」と記録されていたテストが、実際には一度も実行可能な状態になっていなかったという、まさに知見124/129/130が警告していた死角そのものの実例。

実行可能にするため、同一のaction_id集合を保ったまま(新しいアクション種別は追加していない)`AddPowerPointSlide.AddSlideAsLast`をもう一度呼んで2枚目のスライドを追加し、`MovePowerPointSlide`→`DeletePowerPointSlide.DeleteSlideLast`の順序に入れ替えた新規テスト`test_generate_python_from_powerpoint_full_scope_batch_actually_executes_correctly`を追加。`NewSlideIndex`/`NewSlideIndex2`/`PPTData`を実際に検証し(`_slide_text()`が末尾に`"\n"`を付与する仕様も実行して初めて判明し、`.strip()`で吸収)、保存後のpptxを再読込して「移動→削除の結果、残る1枚にはhelloが含まれない」ことまで確認した——こちらも一発で通ったが、**旧い文字列一致テスト自体が「実行可能性の保証が無いまま6件以上のアクションを連鎖させる」という潜在的に危険なテストパターンだったこと自体が今回の収穫**。

旧来の文字列一致テスト(`..._converts_all_actions`)はそのまま残し(個々の生成コードの正確な文字列表現を見るテストとしての価値は維持)、新規のexec検証テストを並置する方針を採った——知見129/130と同じ「文字列一致と実行確認は別の懸念であり、両方必要」という教訓に従った。既存の文字列一致版PowerPointテストはクラッシュするDSLをそのまま残しているが、それは`compile()`(構文エラーが無いことの確認)のみなので実害は無い——ただし次に誰かがこの古いテストを安易に`exec()`付きへ「改善」しようとした場合に今回と同じ罠にかかる可能性があるため、コメントで注意書きを追加した。

テストは`tests/test_pad_codegen.py`に3件(Excel/Word/PowerPoint、いずれも`tempfile`を使った実ファイル往復込み)追加。VM/RDPとも不要。

## 175. `UIAutomation.GetUIControl`を新規結線——`ActionBase`直継承のため`IAutomationRuntimeProxy`(知見172のRPC不透明な壁)を一切経由しない唯一の例外だった

知見172で`IAutomationRuntimeProxy`経由のアクションは静的decompileで解決不能と確定した直後、知見129(`GetDetailsOfElementInWindow`/`GetUIControl`/`GetWindowDetails`、`AttributeName`→UIAプロパティ対応が未確認)の残り2件を再確認する中で、`GetUIControl`だけは例外だと判明した。`GetWindowDetails`は`UIAutomationActionBase`派生で`r.GetDetailsOfWindow(element, attributeName, BringToFront)`という全く同じRPC経由(知見172の壁がそのまま適用、依然ブロック継続)だが、`GetUIControl`クラス自体は**`ActionBase`を直接継承し`UIAutomationActionBase`ではない**——`Execute()`の全文は`UIControl = Control;`の1行のみで、ランタイムプロキシを一切使わない。`[Action(Category = "DataExtraction", Order = 26)]`にName/Id属性が無く(知見155の「クラス名そのものがaction_id」ルール通り`UIAutomation.GetUIControl`、`tools/selector_dumps/UIAutomation_flat_actions.txt`で`EffectiveId=`空欄も確認済み)、兄弟セレクタも無い。

つまり`GetUIControl`は「`Control`(`UiElementRef`)を無変換で`UIControl`出力へecho(コピー)するだけ」という、PAD側の意味論自体が完全にdecompileで確定した唯一のケースで、知見57の`UIAutomation.GetWindow.Get`と全く同じ「解決済みのセレクタ式を出力変数へ代入する」パターンがそのまま使える——`Control`が`UiElementRef`で解決できれば、`{output_var} = {selector_expr}`を生成するだけで、以降の他アクションでこの変数を通常のpywinauto参照として再利用できる。

実装: `dump_daemon/pad_codegen/actions/ui_element.py`に`UIAutomation.GetUIControl`の分岐を追加。テストは`tests/test_pad_codegen.py`にexec検証テストを1件追加(`fake_pywinauto`で出力変数が実際に正しいセレクタ条件を保持していることまで確認)。

`GetDetailsOfElementInWindow`/`GetWindowDetails`(`AttributeName`/`ExtractionOperation`→UIAプロパティの対応)は、知見172で確定した`IAutomationRuntimeProxy`のRPC不透明な壁にそのまま該当するため、依然`design/pad_todo.md`の「decompileでは解決不可、RDP実機確認が必要」カテゴリに残す。副産物として`GetSelectedCheckboxesInWindow`/`GetSelectedRadiobuttonInWindow`(知見161の残課題)もdecompile確認したところ、両方とも`UIAutomationActionBase`派生で同じRPC経由(`r.GetCheckboxState`/`GetSelectedCheckboxesInWindow`/`GetSelectedRadiobuttonInWindow`)だったため、同じ壁に該当すると確定した。

## 176. `tools/pad_selector_audit.py`をVariables.Actions.dllに再適用して発見した未結線4件(`FindOrReplaceInDataTable`の`Replace*`系兄弟セレクタ)を新規結線——同じ`_cell_matches()`内の正規表現大文字小文字区別バグも合わせて修正

知見175調査の一環で、全モジュールに対して`tools/pad_selector_audit.py`を再実行し横断的に未結線候補が残っていないか確認したところ、Variables.Actions.dllに4件の未結線候補(`Variables.FindOrReplaceInDataTable.ReplaceItemInDataTableByColumnIndex`/`ReplaceItemInDataTableEverywhere`/`ReplaceItemInDataTableWithRegexByColumnIndex`/`ReplaceItemInDataTableWithRegexEverywhere`)を発見した——他の全モジュール(Database/Web/File/Folder/Cmd/Cryptography/DateTime/Text/XML/Variables以外)は監査済みで全セレクタ結線済みと確認(Clipboard/Compressionのみ、`ActionSelectorBase`一括列挙用のVMダンプ自体が未取得のため監査不可、低優先度のまま残す)。

decompileで確認した`FindOrReplaceInDataTable`クラス(既に知見89/123/133/135で`SearchMode=Find`側4件を確認済み)の`Execute()`を再精査したところ、`SearchMode=FindAndReplace`側(`Replace*`系4件)はFind側と**全く同じマッチ判定ロジック・同じ`DataTableMatches`出力契約**(`(行,列)`の0始まりペアのリスト)を使い、マッチしたセルを即座に3分岐(`UseRegex`/`MatchEntireCellContents`/それ以外)で置換しながらテーブルを直接mutateするだけだと確認した——Find側で確立済みの`_cell_matches()`/`_resolve_column_name()`をそのまま再利用できる構造。

**副産物として発見・修正したバグ**: `_cell_matches()`のUseRegex分岐が`ignore_case`引数(`not match_case`)でregexに`re.IGNORECASE`を付与していたが、decompileした`FindOrReplaceInDataTable.Match()`のUseRegex分岐は`regex?.IsMatch(text)`のみで`MatchCase`を一切参照せず、`ValidateAndInitializeRegex()`も`RegexOptions.Compiled`のみ(IgnoreCase無し)でコンパイルしている——つまり実機のregex系セレクタ(`MatchCase`が常にHidden+既定値False)は**常に大文字小文字を区別する**のに、既存の実装(知見123/135で結線済みの`FindItemInDataTableWithRegexEverywhere`/`WithRegexByColumnIndex`)は逆に常に大文字小文字を無視していた——既存のテストはこの違いを検出できる入力(大文字小文字が異なる候補を含む文字列)を使っていなかったため今まで気づかれていなかった潜在バグ。`_cell_matches()`のregex分岐を「`ignore_case`/`entire_cell`パラメータを無視し常に`re.search(find_value, text)`(大文字小文字区別・アンカー無し)」に修正した。

新規実装: `pad_action_lib/variables_actions.py`の未使用(どのcodegenからも呼ばれていなかった)`find_or_replace_in_datatable()`(`int`件数を返す旧実装、置換ステップのregex分岐にも同じIGNORECASEバグがあった)を、`find_item_in_datatable_everywhere()`と同じ引数名・同じ`list[tuple[int,int]]`出力契約を持つ`find_and_replace_in_datatable_everywhere()`へ置き換えた(旧関数はcodegenから一度も参照されていなかったため、シグネチャ変更による既存動作への影響は無い)。

実装: `dump_daemon/pad_codegen/actions/variables.py`に`Variables.FindOrReplaceInDataTable.ReplaceItemInDataTableEverywhere`/`ReplaceItemInDataTableWithRegexEverywhere`/`ReplaceItemInDataTableByColumnIndex`/`ReplaceItemInDataTableWithRegexByColumnIndex`の4分岐を追加。テストは`tests/test_pad_action_lib_variables.py`に単体テスト8件(新関数4件+regexの大文字小文字区別修正確認2件+旧テストの置き換え)、`tests/test_pad_codegen.py`にexec検証テスト4件(CSV経由でDataTableを組み立て、置換後のテーブル内容・`DataTableMatches`の両方を検証)を追加。VM不要。

## 177. `tools/pad_selector_audit.py`をWord/PowerPoint/Pdfにも再適用——`Word.InsertImageToWord`の`StartOfDocument`/`EndOfDocument`(`Source=File`固定)2件が実はpython-docxで再現可能だったと判明、新規結線

知見176に続き`tools/pad_selector_audit.py`をWord/PowerPoint/Pdfにも再適用した。PowerPoint/Pdfは全セレクタ結線済みと確認(新規発見無し)。Wordは`InsertImageToWord`(11セレクタ)/`ReadFromWord.ReadBookmark`/`ReadPage`/`WriteToWord.WriteStartOfBookmark`/`WriteEndOfBookmark`/`FindAndReplaceWord`のワイルドカード系2件が未結線候補として挙がった——これらは`pad_todo.md`で既に「`pad_action_lib`側に未実装のため対象外」と記録済みの既知の除外のはずだったが、`InsertImageToWord`について`pad_action_lib.word_actions.insert_image_to_word()`の既存実装を再確認したところ、**全10バリアントを無条件に`NotImplementedError`とする実装になっており、個別の分岐すら無かった**と判明した。

decompileで`InsertImageToWord.Execute()`を精査し直すと、`InsertImageMode`は`switch`文で3グループに分かれる——(1)`StartOfDocument`/`EndOfDocument`は`WriteImage()`(ライブWordの「挿入位置」操作だが、本質的にはPADが保持する`WordInstanceHandle`に対する単純な「先頭/末尾に画像を追加する」操作)、(2)`StartOfBookmark`/`EndOfBookmark`は`WriteImageToBookmark()`(python-docxにブックマークナビゲーションが無く既存の制約通り)、(3)`StartOfText`/`EndOfText`は`WriteImageRelativeToText()`(`TextToFind`位置特定アルゴリズムが未確認)。つまり(1)のグループだけは、既存の`write_to_word()`の`StartOfDocument`/`EndOfDocument`(知見未記載だが既に結線済み)と全く同じ「先頭に新規段落を挿入/末尾に新規段落を追加」という構造で、`python-docx`の`Document.add_picture()`(末尾)・`paragraph.insert_paragraph_before()`+`run.add_picture()`(先頭)でそのまま再現できると確認した——モジュールdocstring自体は「クリップボード画像挿入」としか名指ししておらず、ファイルソースの`StartOfDocument`/`EndOfDocument`まで一律除外する理由は元から無かった(過去の判断が必要以上に広く除外していた)。

`Source=Clipboard`系(OSクリップボードの画像読み取り機構が本プロジェクトに未確立)・ブックマーク相対・テキスト相対は、decompileした通りそれぞれ別の理由で依然`NotImplementedError`のまま(でっち上げず保留継続)。

実装: `pad_action_lib/word_actions.py`の`insert_image_to_word()`を無条件`NotImplementedError`から、`StartOfDocument`/`EndOfDocument`を実装しそれ以外を`NotImplementedError`とする実装へ書き換え(`InsertImageWordError`例外クラスを新規追加、decompile確認済みの`[Throws]`タグ名と一致)。`dump_daemon/pad_codegen/actions/word.py`に`Word.InsertImageToWord.InsertImageDocumentStartFromFile`/`InsertImageDocumentEndFromFile`の2分岐を追加。テストは`tests/test_pad_action_lib_word.py`に単体テスト6件(Pillowで実PNGを生成して実際に`.docx`へ挿入・再読込して検証)、`tests/test_pad_codegen.py`にexec検証テスト1件・TODOフォールバック確認1件を追加。VM不要。

## 178. `tools/pad_selector_audit.py`の全モジュール横断再実行を完了——`Clipboard`/`Compression`の`ActionSelectorBase`一括列挙も新たにVM上で実施し、プロジェクト全モジュールのセレクタ監査が完全網羅に到達したと確定

`pad2py-pad-host`が再度idleになったタイミングで、知見165時点で「`ActionSelectorBase`一括列挙用のVMダンプ自体が未取得」として唯一未監査のまま残っていた`Clipboard`/`Compression`に対し、読み取り専用のリフレクション列挙(Designer UI非依存、既存の「busy/idle問わず安全」の方針通り)を実施した。

`Microsoft.Flow.RPA.Desktop.Modules.Clipboard.Actions.dll`/`Microsoft.Flow.RPA.Desktop.Modules.Compression.Actions.dll`を対象に、知見164で確立した「`[Action]`属性を持つ全クラスを直接列挙し、`ActionSelectorBase`派生型の集合と突き合わせる」手法(`HasSelector`列で判定)を適用した結果、**両モジュールとも兄弟セレクタが1つも存在しない**(`Clipboard`: `ClearClipboardContents`/`GetClipboardText`/`SetClipboardText`の3件、`Compression`: `UnzipFiles`/`ZipFiles`の2件、全て`HasSelector=False`)と確定した——知見165の「`Clipboard`/`Compression`は0件」という以前の確認(別の`_all_modules_flat_actions_raw.txt`一括スイープ経由)と完全に一致し、既存の結線(`codegen_coverage.py`で両モジュールとも100%)に抜けが無いことが二重に確証された。

これにより、本プロジェクトが対象とする全Tier1/2/3モジュール(Database/Web/XML/Cmd/Clipboard/DateTime/Text/Cryptography/File/Folder/Variables/Compression/Excel/Word/PowerPoint/PDF/UIAutomation)のセレクタ監査(`ActionSelectorBase`一括列挙+フラットアクション一括列挙の両方)が完全に網羅され、`tools/pad_selector_audit.py --module <全モジュール>`を実行して未結線候補が出るのは意図的な既知除外(ライブCOM専用・RDP必須・外部ライブラリ未導入等、個別にdecompileまたは実機で確認済み)のみという状態に到達したと確定した。

`tools/selector_dumps/Clipboard_flat_actions.txt`/`Compression_flat_actions.txt`を新規保存(知見164の`UIAutomation_flat_actions.txt`と同じ命名規則・フォーマット——`tools/pad_selector_audit.py`本体の`--dump`が期待するシブリングセレクタ専用フォーマットとは異なるため、同名の`Clipboard.txt`/`Compression.txt`ではなく明示的に`_flat_actions`サフィックスを付けて区別した)。コード変更は無し(確認のみ)。

## 179. `design/common_rpa_framework_roadmap.md`層3の残課題「`ActionSelectorBase`列挙用PowerShellスクリプト自体の資産化」を完了——`tools/pad_selector_audit.ps1`を新規コミット

知見139以降、`ActionSelectorBase`派生型を列挙する手順(モジュール名を引数にした`clipwire`のアドホックターゲット)を知見139/159/165/171/178等のたびに都度書き直していた。これをパラメータ化された1本のスクリプトに資産化した——`design/common_rpa_framework_roadmap.md`層3が「次の課題」として明記していた残り半分(Pythonツール`tools/pad_selector_audit.py`自体は知見159で資産化済みだったが、VM側のPowerShellスクリプトは専用の`.ps1`ファイルとしてまだコミットされていなかった)。

`tools/pad_selector_audit.ps1`(`-Dlls <DLLファイル名の配列>`・`-Root <インストールディレクトリ、既定値あり>`のパラメータを持つ)は、知見139-178で蓄積した標準手順(BaseTypeチェーンを`ActionSelector*`まで遡って対象型を判定、直接の親`ActionSelector<TTarget>`の型引数からターゲットクラス名を取得、`ActionName`プロパティをインスタンス化して読み取る)をそのまま1本化しただけで、新しい判定ロジックは何も追加していない(でっち上げ無し)。読み取り専用(`Execute()`を一切呼ばずインスタンス化のみ)なので、Designer UIを操作中の他セッションがいても安全に実行できる既存の方針を維持する。

**実機で動作確認済み**: `Microsoft.Flow.RPA.Desktop.Modules.Database.Actions.dll`に対して実行した出力が既存のコミット済み`tools/selector_dumps/Database.txt`(5行)と完全一致、`Microsoft.Flow.RPA.Desktop.Modules.Excel.Actions.dll`に対しても既存の`tools/selector_dumps/Excel.txt`(103行)と`diff`でバイト単位の完全一致を確認した——このスクリプトが過去の全ての監査結果を再現できる(後方互換)ことを実証した。

実装: `tools/pad_selector_audit.ps1`を新規コミット。`design/common_rpa_framework_roadmap.md`の層3セクションとPhase 0のチェックリスト項目を`[x]`完了に更新した。コード変更(`pad_action_lib`/`pad_codegen`)は無し、`tools/pad_selector_audit.py`本体も無変更。

## 180. 知見166で保留していた`Excel.GetTableRange`を、同一DLL内の`IExcelActions`実装クラス(`ActionRuntimeBase`派生の具象実装)まで遡って精査し、decompileのみで完全に解決——`IsPivot=False`側を新規結線

知見166で「ワークシート横断探索の前例が無い点と`IsPivot=True`に対応するopenpyxl APIが無い点の両方が未解決、`IsPivot`分岐の片方だけ実装するのはでっち上げに近い」として保留した`Excel.GetTableRange`を再調査した。これまでのPAD側decompile調査は`[Action]`クラス(`GetTableRange : ActionBase`、`_excelActions.GetTableRange(...)`を呼ぶだけの薄いラッパー)までしか読んでいなかったが、同じ`Excel.Actions.dll`内に`IExcelActions`インターフェースの**具象実装クラス**(`class ExcelActions : ActionRuntimeBase, IExcelActions`、COM Interopを直接操作する本体)が存在することに気づき、そちらの`GetTableRange(ExcelInstanceVariant, string)`/`GetPivotTableRange(...)`の実装自体を直接読んだ。

**解決した事実**: (1) 非Pivot側は`FindTableInSheet(activeSheet, tableName)`でテーブルを探し、見つかった`ListObject`の**`"Range"`プロパティ**(COMの`ListObject.Range`——ヘッダー行+データ行+(存在すれば)合計行を含むテーブル全体、`DataBodyRange`ではない)を`RangeBounds`(`Range.Row`/`Range.Column`が1始まりとdecompileで確認済み)で読むだけ。これは`openpyxl`の`Table.ref`(OOXML仕様上、同じくヘッダー行を含む範囲文字列)と1:1で対応する——「でっち上げ」ではなく確定事実だった。(2) **検索範囲はワークブック全体ではなくアクティブシートのみ**(`GetActiveSheet(excelInstance)`で取得した1枚に対して`FindTableInSheet`を呼ぶ)——知見166で懸念していた「ワークシート横断探索」自体が実は不要だったと判明し、既存の`instance.active_sheet`規約とそのまま一致する。(3) Pivot側は`PivotTable.TableRange2`(COMのピボットテーブル専用プロパティ、ページフィルタ領域を含む)を読むだけで、こちらは確かに`openpyxl`に対応APIが無いため、依然`NotImplementedError`のまま保留する——「`IsPivot`分岐の片方だけ実装する」ことへの以前の懸念は、非Pivot側が完全に確定事実である以上、もはや「でっち上げ」ではなく、Pivot側だけを明示的に未対応とする安全な部分実装になった。

**教訓**: `[Action]`クラス自身がネイティブAPI(`IExcelActions`等のインターフェース)を呼ぶだけの薄いラッパーである場合、そのインターフェースの**具象実装が同じDLL内に存在するか**を確認する価値がある——知見172(`IAutomationRuntimeProxy`、UIAutomationモジュール)では実装がRPC越しの別プロセスだったため原理的に不可能だったが、Excel(ライブCOM直接操作、サンドボックス化されていない)では実装自体が同じアセンブリ内に静的に存在し、decompileだけで完全に解決できた——「RPC越しか直接COMか」というモジュールごとのアーキテクチャの違いが、decompileで解決可能かどうかを左右する決定的な要因だと再確認した。

実装: `pad_action_lib/excel_actions.py`に`get_table_range()`(`GetTableRangeError`例外クラス新規追加)を実装。`dump_daemon/pad_codegen/actions/excel.py`に`Excel.GetTableRange`(`IsPivot=False`のみ、`IsPivot=True`または非リテラルは安全にTODOへ倒す)の分岐を追加。テストは`tests/test_pad_action_lib_excel.py`に単体テスト4件、`tests/test_pad_codegen.py`にexec検証テスト1件・TODOフォールバック確認1件を追加。VM不要。

**同じ技法で他の「ライブCOM専用」判定も再検証したが、今回は新規発見なし**: 知見171で確認したExcelの`RunMacro`/`GetSelectedCellRange`/`Attach`、PowerPoint の`CopyPastePowerPointSlide`も、同じ`ExcelActions`/`PowerPointOperations`具象実装クラス内の該当メソッド本体を直接読み直した。`AttachToRunningExcelDocument`は`ExcelFunctions.AttachToRunningExcelDocument(...)`でライブプロセスへの直接アタッチ、`RunMacro`はライブExcel上のVBAマクロ実行(`MacroCommandParser`+`Application.Run`相当)、`GetSelectedCellRange`はライブExcel UIの`Selection`プロパティ(現在のユーザー選択範囲、ファイルベースには対応概念が無い)、PowerPointの`CopyPasteSlide`は`Slide.Copy()`+`Slides.Paste()`(Windows OSクリップボード経由のライブCOM操作)——4件とも実装を直接読んでも代替手段が無いと再確認できた。知見180の「同じDLL内の具象実装まで遡る」技法が有効だったのは`GetTableRange`が本当に単純なプロパティ読み取りだったからで、万能というわけではないと確認した。

## 181. 知見180の技法をWordにも適用——`ReadFromWord.ReadBookmark`(`Bookmark.Range.Text`相当)をlxmlでのOOXML直接検索により新規実装、`python-docx`に無い機能を自前で実装した初めての例

知見180・前段の再検証に続き、`Word.Actions.dll`の`IWordOperationsFacade`具象実装クラス(`WordOperationsFacade`)内の`ReadDocumentByPage()`/`ReadDocumentByBookmark()`の実装本体も直接読み直した。

`ReadDocumentByPage()`は`Range(...)[WdInformation.wdNumberOfPagesInDocument]`や`GetSinglePageContent()`(Word COMの`GoTo(wdGoToPage, ...)`相当、ライブレンダリング結果にのみ存在する「ページ」概念)に依存——これはExcelの`RunMacro`等と同じ、ライブCOM無しには原理的に不可能なケースで、知見180の技法を適用しても解決しないと再確認した(`python-docx`はページ分割という概念自体を持たない)。

一方`ReadDocumentByBookmark()`は`((_Document)val).Range(ref obj, ref obj2).Text`——名前で見つけたブックマークの`Range.Start`/`Range.End`間の生テキストを返すだけの**構造的な範囲読み取り**で、ライブレンダリングに依存しない。既存の`design/pad_todo.md`の判断(「`python-docx`にブックマークナビゲーションAPIが無い」)は事実として正しいが、これは「`python-docx`の**高レベル**APIに無い」という意味であり、「OOXML構造上ブックマークの位置特定・テキスト抽出が原理的に不可能」という意味ではなかった——これまでの知見166・175・177・180の「ライブCOM専用か」という切り分けとは異なる、**「高レベルAPIが無いだけで、低レベルのXML操作なら実装できる」という新しいカテゴリ**だったと判明した。

OOXMLでは`<w:bookmarkStart w:name="..." w:id="N"/>`と`<w:bookmarkEnd w:id="N"/>`という2つの空要素でブックマークの範囲が区切られ(`python-docx`の内部表現も`lxml`の`Element`ツリーそのもの、`docx.oxml.ns.qn()`で名前空間付きタグ名を取得できる)、間に挟まれた`<w:t>`要素のテキストを文書順に連結すればWord COMの`Range.Text`と同じ結果になる——`document.element.body.iter()`で文書順の全子孫を列挙し、名前が一致する`bookmarkStart`から同じ`w:id`を持つ`bookmarkEnd`までの区間にある`w:t`のテキストを連結するだけで実装できた。`ReadDocumentByBookmark()`自身の`if (val2 == null || val2.Empty) return string.Empty;`(ブックマークが**見つからない場合も例外にせず空文字列を返す**という非自明な挙動)も確認し、同じ挙動で実装した。

複数段落をまたぐブックマーク(段落境界に`\r`を挿入すべきかどうか、知見81の`"\r".join(...)`規約との整合性)はWord COM実機で未確認のため、`<w:t>`の内容をそのまま連結するだけに留め、でっち上げた`\r`挿入ロジックは追加しなかった——単一段落内のブックマークという典型例でのみ忠実な実装である点を明記した。

書き込み側(`WriteToWord`/`InsertImageToWord`のブックマーク相対モード)は、挿入位置の意味論(既存コンテンツの前後どちらに挿入されるか、`bookmarkStart`/`bookmarkEnd`自体を移動させる必要があるか等)がより複雑で未確認のため、今回は読み取り側のみ先行実装し、書き込み側は依然`NotImplementedError`のまま保留する。

実装: `pad_action_lib/word_actions.py`に`_bookmark_range_text()`(lxml直接検索)を追加し、`read_from_word()`の`Bookmark`モードを無条件`NotImplementedError`から実装へ変更。`dump_daemon/pad_codegen/actions/word.py`に`Word.ReadFromWord.ReadBookmark`の分岐を追加。テストは`tests/test_pad_action_lib_word.py`に単体テスト4件(見つかる場合・空ブックマーク・見つからない場合・保存→再読込往復)、`tests/test_pad_codegen.py`にexec検証テスト1件を追加。VM不要。
