# PAD実行エンジンの共有ランタイムサービス地図

design/common_rpa_framework_roadmap.md 層5(ランタイムサービス地図)。PADの`Robin`実行エンジン
内部には、複数の異なるアクション(DataTable操作・SET式・CSV読み書き等)から横断的に呼ばれる
共有の「サービス」がいくつか存在する。実機確認・decompile・VM上の直接リフレクション呼び出しで
確認済みの事実が`design/dsl_format_findings.md`の各知見に分散しているため、このドキュメントは
**既存の知見を1箇所に集約するだけ**で、新しい事実の確認は行わない(新しい疑問が出てきた時点で
別途VM/decompileで確認し、このドキュメントとその出典知見の両方を更新する)。

各項目は「何を確認したか」「実装している`pad_action_lib`/`pad_codegen`側のコード」
「出典知見」の3点を記載する。

## 1. 比較エンジン(`ComparisonCalculator.Compare`)

- **確認済みの規則**: 文字列同士は大文字小文字を区別する(`"Apple"` ≠ `"apple"`)。
  数値を表す文字列と数値は型をまたいで等価と判定される(`"1" = 1`は真)。
  `IF`/`SET`の`=`/`<>`演算子も同じ規則に従う。
- **実装**: `dump_daemon/pad_action_lib/expr_runtime.py`の`pad_equal()`
  (`render_condition()`/`render_expr_as_python()`の`=`/`<>`から呼ばれる)、
  `variables_actions.py`の`subtract_lists()`/`find_common_list_items()`。
- **出典**: 知見85(`SubtractLists`/`FindCommonListItems`での発見)・知見88(`IF`/`SET`への
  適用)。

## 2. 数値文字列の認識規則(`+`/`=`演算子側)

- **確認済みの規則**: 「数値を表す文字列」の認識範囲はPythonの`int()`/`float()`より狭い。
  - 桁区切りコンマ(`"1,000"`)・前後の空白(`"  5  "`)・明示的な`+`符号(`"+5"`)・
    先頭ゼロ省略の小数(`".5"`)は数値として認識する。
  - **指数表記(`"1e2"`)は数値として認識しない**(文字列結合/不等価になる)。
  - `True`/`False`は数値として扱わない(`1 + True`は`"1True"`、数値加算にはならない)。
  - この規則は**CSV読み込み系の数値変換(下記4節)とは別のPADサブシステム**で、
    CSV側は指数表記を数値として受理するという違いがある——同じ「数値らしい文字列」でも
    サブシステムによって認識範囲が異なる点に注意。
- **実装**: `dump_daemon/pad_action_lib/expr_runtime.py`の`_NUMERIC_STRING_RE`/`_as_number()`/
  `pad_add()`/`pad_equal()`。
- **出典**: 知見86(基本規則)・知見101(指数表記を認識しないこと、CSV系との違い)・
  知見102(桁区切りコンマ)・知見104(空白/符号/先頭ゼロ省略)・知見105(`Boolean`非対応)。

## 3. 算術演算子`/`・`mod`の値の意味論

- **確認済みの規則**: `/`は常に浮動小数点除算でPythonの`/`と完全に一致
  (`-7 / 2 = -3.5`)。`mod`は符号が被除数と一致する(C言語の`fmod`方式、
  `-7 mod 3 = -1`・`7 mod -3 = 1`)——Pythonの`%`(符号は除数と一致)とは異なる。
- **実装**: `dump_daemon/pad_codegen/render.py`の`render_expr_as_python()`
  (`mod`演算子を`math.fmod(a, b)`へ変換)。
- **出典**: 知見81(演算子優先順位の発見)・知見83(`/`・`mod`の値の意味論)。

## 4. CSVの区切り文字・数値変換・固定長パース(`CSVUtilities`)

- **確認済みの規則**:
  - `CSVColumnsSeparator`列挙値(`SystemDefault`/`Comma`/`Semicolon`/`Tab`)の実区切り文字
    は`SystemDefault`→`,`・`Comma`→`,`・`Semicolon`→`;`・`Tab`→`\t`。`Variables.Actions.dll`と
    `File.Actions.dll`は同一アセンブリ(`Text.Utilities.dll`)のこの型を共有する。
  - CSV読み込み時の数値変換(`ReadFieldsAsText: False`)は、桁区切りコンマを数値として
    認識する点は2節の`+`/`=`演算子と同じだが、**指数表記は2節と異なり数値として受理する**。
  - 固定長カラムCSV(`FixedColumnWidths`)の構文はカンマ/空白区切りの幅リスト。
    短い行はエラー、長い行は無視される。
- **実装**: `dump_daemon/pad_codegen/actions/_support.py`の区切り文字マッピング辞書、
  `dump_daemon/pad_action_lib/datatable.py`の`datatable_from_fixed_width_csv()`。
- **出典**: 知見84(ヘッダー無し列名`"Column#N"`)・知見92/100/103(数値変換・指数表記・
  桁区切りコンマ)・知見106(トリム対象)・知見127/128(区切り文字マッピング)・
  知見132(固定長パース)。

## 5. 列インデックスの基準(`IListIndexService`)

- **確認済みの規則**: 本プロジェクトが対象とする`ScriptType.Robin`(クリップボードDSL)では
  `IsZeroBased=True`で`ConvertInput()`は恒等写像——列インデックスは常に**0始まり**。
  (1始まりになるのは対象外の`ScriptType.PowerFx`のみ。)
- **実装**: `dump_daemon/pad_action_lib/variables_actions.py`の`_resolve_column_name()`
  (`ModifyDataTableItem`/`FindItemInDataTableByColumnIndex`/
  `RetrieveDataTableColumnIntoList`/`SortWithColumnIndex`が共有する)。
- **出典**: 知見133(`IListIndexService`の実装クラスをVM上で直接確認)。

## 6. DPAPI保護値(`Sensitive`パラメータ)

- **確認済みの規則**: `P'<base64>'`という`$'''...'''`とは別のDSL構文で直列化される。
  固定20バイトのentropy定数(`DataProtectionScope.CurrentUser`と組み合わせ)で
  `win32crypt.CryptUnprotectData`経由で復号できる——ただし**元の値を生成したWindowsユーザー
  自身が復号スクリプトを実行する場合のみ**(別ユーザーの実行では`DpapiDecryptionError`)。
  恒久的に非対応という当初の結論は誤りだった。
- **実装**: `dump_daemon/pad_action_lib/cryptography_actions.py`の`_DPAPI_ENTROPY`/
  `decrypt_dpapi_sensitive_value()`。`win32crypt`は関数内で遅延import(モジュール先頭では
  importしない、Linux上でもこのモジュール自体は読み込める設計——
  design/common_rpa_framework_roadmap.md 層7参照)。
- **出典**: 知見65(DSL構文の発見)・知見112(復号成功、結論の訂正)。

## 7. DataTableのフィルタ・結合条件(`FilterParameters`/`JoinParameters`)

- **確認済みの規則**:
  - `FilterDataTable`の`FilterParameters`は`COLUMN`/`OPERATOR`/`VALUE`/`RULE`列
    (16種の`FilterConditionOperator`、`RULE`は`Or`/`And`のグループ分割)。
    `Equal`/`NotEqual`は型が食い違えば常に不一致。
  - `JoinDataTable`の`JoinParameters`は`"COLUMN 1"`/`OPERATOR`/`"COLUMN 2"`列
    (列名に半角スペース、`OPERATOR`は`JoinComparisonOperator`6種、全行AND結合)。
    順序比較演算子(`GreaterThan`等)は**数値変換せず文字列の辞書順で比較する**
    (`FilterDataTable`とは異なる挙動——`"9" GreaterThan "10"`が真になる)。
- **実装**: `dump_daemon/pad_action_lib/variables_actions.py`の`filter_datatable()`/
  `join_datatable()`。
- **出典**: 知見90(`FilterParameters`スキーマ)・知見91(`JoinParameters`スキーマ)・
  知見97(順序比較演算子の自己発見バグ修正)・知見98/107(`Equal`/`NotEqual`型不一致)・
  知見99(`RULE: Or`)。

## 8. DateTimeのタイムゾーン対応表

- **確認済みの規則**: `Windows`モードはPAD自身の埋め込み対応表(decompileで発見)を経由する。
  `CustomTimeZone`モードはこのルックアップテーブルを経由せず、`.NET TimeZoneInfo.Id`文字列を
  直接受け付ける別経路。
- **実装**: `dump_daemon/pad_codegen/actions/pad_datetime.py`、
  `dump_daemon/pad_action_lib/datetime_actions.py`の`get_current_datetime()`。
- **出典**: 知見116(`Windows`モードの対応表発見)・知見138(`CustomTimeZone`が別経路だと発見)。

## まだここに無いもの

- `ActionSelectorBase`一括列挙による未結線セレクタの監査手法(知見135-137)は、
  「ランタイムの挙動」ではなく「発見ツール」の性質が強いため、本ドキュメントではなく
  design/common_rpa_framework_roadmap.md 層3(発見ツール)の対象として別途`tools/`化を検討する
  (Phase 0のTODOとして残っている)。
- `Web.*`のCookieジャー(`CompiledJob.CookieContainer`、知見96)・`ExcelApplicationScope`等の
  Tier3系サービスは、個別action向けの挙動としての性質が強く、横断的な「サービス」とまでは
  言えないため、現時点では知見ログ側の記述のみに留める。
