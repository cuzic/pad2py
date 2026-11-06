# 共通RPA変換フレームワーク化ロードマップ

## この文書の位置づけ

本リポジトリは現在、**完全に独立した2つのトラック**として実装されている。

| トラック | 対象 | 実装 |
|---|---|---|
| PAD | Power Automate Desktop(クリップボードDSL) | `pad_dsl`/`pad_expr`/`pad_codegen`/`pad_action_lib` |
| UiPath | UiPath Studio(`.xaml`) | `uipath_dsl`/`uipath_expr`/`uipath_codegen`/`uipath_selector` |

両者は設計思想(FCIS的なcore分割、「でっち上げない」方針、knowledge.mdへの実機確認ログ蓄積)を**独立に収束させて同じ結論に達した**——つまりこの設計思想自体はツール依存ではなく本質的に汎用であることが、2回の独立実装によって実証されている。しかし現状、この汎用性は**各トラックが同じパターンを別々に再実装している**という形でしか表れておらず、共有されたコード・共有された規約として結晶化していない。

本文書は、「共通RPA変換フレームワーク」という理想の状態を具体的に定義し、現状とのギャップを棚卸しし、実行順序を提案するものである。**これは実装の指示ではなく計画書**——特にPhase 2以降はUiPathトラック(別セッションが並行して活発に開発中)のソースに触れるため、着手前にユーザー自身の判断・両トラックの調整が必要。

**追記(2026-11-05、ユーザー方針確認後)**: 本プロジェクトはまだ外部ユーザーが存在しないOSSのため、**後方互換性を気にする必要は無い**(API・IRの形を破壊的に変更してよい)。これにより下記Phase 2・3の「移行コスト」に関する懸念は後退する。ただし**互換性の制約が無いこと**と**複数セッションが同じgit作業ツリーを共有している状態での衝突リスク**は別の軸であり、後者は引き続き有効な制約——UiPathトラックのソースに触れる変更は、互換性維持のためではなく「他セッションの作業中のコードを書き換えて衝突・破壊しないため」に調整が必要、という理由に変わる。

調査根拠: `pad_dsl/types.py` ↔ `uipath_dsl/types.py`、`pad_codegen/__init__.py` ↔ `uipath_codegen/__init__.py`、各`actions/*.py`のTODO生成箇所を実際に読み比べた結果に基づく(2026-11-05時点)。

---

## 理想の状態(6層、具体的に)

### 層1: 共通IR(中間表現)

**目指す形**: ツールごとのフロントエンド(字句/XML解析)は現状維持でよいが、その出力は共有パッケージ(仮称`rpa_ir`)が定義する型にする。

```python
# rpa_ir/nodes.py (イメージ)
@dataclass
class ActionCallNode:
    action_id: str                 # ツール内で一意な識別子(PAD: "File.Copy", UiPath: 活動のCLR型名等)
    params: dict[str, "Value"]
    output_bindings: dict[str, str]  # パラメータ名 → 変数名(複数出力対応、PAD知見58で必要性が実証済み)

@dataclass
class ConditionalNode:
    arms: list[tuple["Value", list["Node"]]]   # N-ary(IF/ELSEIF/ELSE)。binary(if/else)は arms の長さ2の特殊形として表現できる
    else_body: list["Node"] | None

@dataclass
class SwitchNode:
    expression: "Value"
    arms: list[tuple["Value", list["Node"]]]
    default: list["Node"] | None

@dataclass
class ErrorHandlingNode:
    body: list["Node"]
    handlers: list[tuple["Value | None", list["Node"]]]  # None=catch-all
    attachment: Literal["wraps_following_statement", "wraps_body"]  # 後述、ここだけは差異を型で明示する
```

- `Value`型(`Literal`/`VarRef`/`RawExpr`/`EnumRef`)は両トラックでほぼ同形なので素直に共有できる。
- `SwitchNode`は両トラックで既に構造が一致している(最も生成コストの低い統合対象)。
- `ActionCallNode`(文字列キー+辞書の汎用レコード)は、UiPathが現在活動ごとに専用dataclass(`MessageBoxNode`/`ClickNode`等、11種+`UnknownActivityNode`)を持っている構造からの**移行コストを伴う**——ただし移行する価値は高い。専用dataclassは活動が増えるたびに型を増やす必要があるが、汎用レコードは「新しい活動=新しいaction_idの文字列」でしかなく、PAD側で116アクションまで線形にスケールした実績がある。
- `ErrorHandlingNode`: PADの`GuardedNode`(直前の文に遡及的に付与)とUiPathの`TryCatchNode`(先頭から囲む)は**構築方向が逆**で、これは単なる命名の違いではなく実際のツールの挙動差である。共有型に無理に1つの構築手順を強制せず、`attachment`フィールドで明示する(でっち上げない方針をIR設計自体にも適用する)。

### 層2: 「でっち上げない」を型で強制する変換結果の契約

**目指す形**:

```python
# rpa_codegen/result.py (イメージ)
@dataclass
class Converted:
    lines: list[str]

@dataclass
class Unsupported:
    reason: Literal[
        "UNVERIFIED_SEMANTICS",   # 実機確認が取れていない
        "STRUCTURAL_LIMITATION",  # 現在のIR/ライブラリの表現力を超える(例: DataTable列独立管理)
        "ENV_CONSTRAINT",         # 検証環境側の制約(例: Office未インストール)
        "RDP_REQUIRED",           # UI操作の実機確認にRDPが必須
        "OUT_OF_SCOPE",           # v1スコープ外と明示的に決定済み
    ]
    detail: str

ConversionResult = Converted | Unsupported
```

`# TODO`コメントのレンダリングは`Unsupported`からの**射影**として自動生成する(現在のように各呼び出し箇所が手書きの自由文字列を書くのではない)。これにより「未解決の内訳を理由別に自動集計する」(現在`pad_todo.md`を手作業で分類・維持している作業)がツールの出力から導出可能になる。

### 層3: セレクタ/モード一括発見ツールの資産化

**目指す形**: 今回の監査で使った「`ActionSelectorBase`を継承する全型をリフレクションで列挙し、既存codegenの`action_id`マッピングと突き合わせる」手順を、**コミットされたスクリプト+コマンド**にする。

```
tools/pad_selector_audit.py      # dispatch関数群をAST走査してwire済みaction_id集合を抽出
tools/pad_selector_audit.ps1     # VM上でActionSelectorBase由来の全型を列挙(知見135-137の手法)
```

実行結果は「未結線セレクタ一覧」としてCIやレポートに出力し、`pad_todo.md`への反映を半自動化する。UiPath側には活動種別が数百〜数千あるため、この種の**体系的な差分発見ツール**が無いと手探りのまま進むことになり、むしろUiPath側こそ優先度が高い。

### 層4: 実行結果まで比較する検証規約

**目指す形**: テストヘルパーを規約化する。

```python
def assert_generated(dsl: str, expected_vars: dict[str, object]) -> None:
    """IR→コード生成→exec()→出力値の一致、までを1回で検証する。
    文字列一致やcompile()成功だけのテストはこのヘルパーを使わず書けないようにする
    (レビューで検出できるように、ヘルパー非経由のexec()呼び出しをlintで検出する)。
    """
```

今回のセッションで繰り返し発見したバグ(`ZipFile`出力の`None`化、`Destination`意味論の逆転)は、**まさにこの規約が無かったために既存テストが長期間グリーンのまま放置されていた**事例。既存テストの「代入先の値を見ていないexec()テスト」への**遡及的な全件棚卸し**(1回やれば済む有限タスク)も必要。

### 層5: ランタイムサービス層の地図

**目指す形**: `design/pad_runtime_services.md`のような単一のリファレンスドキュメントを作り、個々のアクション調査の**前に**参照する。

| サービス | 役割 | 発見した知見 |
|---|---|---|
| `IListIndexService`(`Robin.Core.Execution.ListIndexService`) | インデックスの0始まり/1始まり変換 | 知見133: `ScriptType.Robin`は常に0始まり |
| DPAPI entropy定数 | `Sensitive`値の復号 | 知見112 |
| `ComparisonCalculator`系 | `=`/`<>`等の型変換規則 | 知見85・98 |
| `CSVUtilities` | CSV/固定長パースの正確な規則 | 知見127・132 |

この地図は**既に発見済みの事実を1ページに集約するだけ**で済む低コストな作業であり、同時に「他にどんなサービスがありそうか」をRobin.Core.dll/Robin.Shared.Runtime.dllから`I*Service`インターフェース名でリフレクション列挙して**先回りで探す**フェーズを確立する。今回は`SortDataTable`の調査中に偶然`IListIndexService`に出会っただけで、体系的に探してはいなかった。

### 層6: 知見ログ+TODOのメタ規約

**目指す形**: 「このリポジトリでは知見をどう記録し、TODOをどう維持するか」を1つのメタドキュメント(`design/KNOWLEDGE_LOG_CONVENTIONS.md`のようなもの)にまとめ、両トラックがこれに従う形にする。現状、PAD側(`dsl_format_findings.md`+`pad_todo.md`)とUiPath側(`uipath_xaml_findings.md`+`uipath_transpiler_roadmap.md`/`uipath_migration_priorities.md`)は**独立したナンバリング・独立したファイル構造**で同じパターンを再発明している——内容としては優れた運用だが、「次にもう1つツール(例: Blue Prism)を調査するとき、このパターンに従ってください」と指し示せる単一のドキュメントが無い。

### 層7: 検証基盤・シミュレータ(2026-11-05追記、ユーザー提案)

ここまでの6層は「正しく変換すること」の話だったが、層7は「変換結果を速く・安く検証できること」自体への投資。今回のセッションでは、実機確認の多くが共用GCP VM(`pad2py-pad-host`)への依存を前提にしており、これが開発速度のボトルネックになっていた(VMの使用待ち、Officeが入っていないという環境制約、RDP必須のUI操作等)。「シミュレータで検証できる仕組み」を作るには、**何を模擬するのか**を区別することが重要——4つの異なる需要があり、模擬できる度合いも、でっち上げ禁止の方針との整合性も全く違う。

| 対象 | 何を確認したいか | シミュレータ化の可否 |
|---|---|---|
| (a) **PAD自身の実行時意味論**(例: 列インデックスは0始まりか、`Destination`パラメータの挙動) | 「PADは実際にどう動くか」という事実そのもの | **原理的に不可**。シミュレータ自身が推測で作られていたら「シミュレータで確認した」は実機確認の代わりにならない——でっち上げ禁止の方針に直接反する。ここに投資すべきは模擬ではなく**record/replay**(後述) |
| (b) **生成されたPythonコード自体の実行**(pywinauto越しのUI Automation操作) | 「pad_codegenが正しい形の呼び出し列を組み立てているか」——PAD/pywinautoの実際の挙動の模倣では無い | **安全かつ高ROI**。本セッションで最初の実装を済ませた(後述) |
| (c) **pad_action_libのOS依存コード**(`win32timezone`/`win32crypt`/`win32gui`等pywin32の薄いラッパー) | 「正しい引数でpywin32 APIを呼んでいるか」——(b)と同種、呼び出し側のロジック検証 | **安全かつ高ROI**。一般的なテストダブル手法で対応可能、未着手 |
| (d) **模擬対象アプリ**(例: 模擬Notepad) | (b)より高い再現度(実UIAプロトコル越しの通信まで)で検証したい場合 | 価値はあるが、UIA自体がWindows OS機能のため「Windowsが丸ごと不要になる」わけではない。(b)と違う軸の投資であり優先度は低い |

**(b)の実装(完了)**: `tests/fake_pywinauto.py`に、生成コードが実際に呼び出す最小限のpywinauto API表面(`Desktop(backend="uia")`/`.window()`/`.child_window()`/`.exists()`/`.wrapper_object()`/`.click_input()`/`.set_focus()`/`.type_keys()`/`.wait()`/`.wait_not()`)だけをフェイク実装した。`pywinauto.Desktop`をこのフェイクに差し替えてから生成コードを`exec()`すれば、実Windows・実アプリ無しで「正しいセレクタ・正しい操作列で呼ばれたか」をアサートできる。未知の呼び出し形は素直に`AttributeError`になる(でっち上げて成功させることはしない)。`test_generate_python_from_click_click_actually_clicks_against_fake_pywinauto`で、既存の「文字列として生成コードを検査するだけ」のテストを「実際に`exec()`して動作を検証する」テストへ格上げする実例を示した。現状Linux上でこの種のテストは0件だった(pywinautoを要する生成コードは一切`exec()`されていなかった)ので、新規にカバレッジが生まれた形。

**(a)のrecord/replay化(未着手)**: 今回VMで確認した入出力ペア(例: `IListIndexService.ConvertInput()`の挙動、`CopyFolder`の`Destination`意味論)を、構造化データ(JSON等)として`design/`または専用ディレクトリに永続化し、「既に確認済みの事実」をもう一度VMに聞き直す無駄を無くす。新しい疑問には引き続きVMで答える必要があるが、過去の確認結果の再利用コストはゼロになる。

---

## 現状評価(層ごと)

| 層 | 現状 | 評価 |
|---|---|---|
| 1. 共通IR | PAD/UiPathは独立実装。`SwitchNode`の構造は既に一致、`RawExpr`↔`VbExpr`は役割は同じだが保持する情報量が違う(PADは`tree`フィールドで構文木を同時保持、UiPathは生テキストのみ)。`ActionCallNode`相当はPAD側のみ汎用化済み、UiPathは活動ごとの専用dataclass。`ConditionalNode`(N-ary)↔`IfNode`(binary)、`GuardedNode`(遡及付与)↔`TryCatchNode`(先頭包含)は**構造そのものが異なる**。 | **未着手**。類似パターンの重複実装はあるが、共有コードはゼロ |
| 2. 型での契約強制 | 両トラックとも`return None`→汎用TODO、という同じ「規約」を持つが、PAD側は1箇所に集約されたTODOレンダラ、UiPath側は呼び出し箇所ごとに手書きの自由文字列。理由コードは両方とも無し(自由文字列のみ) | **部分的**。規約はあるが型で強制されていない、理由の構造化なし |
| 3. 発見ツール | 今回確立した監査手法(知見135-137)はPowerShellスクリプトとしてVM上で毎回その場で書いて実行しているだけで、**リポジトリにコミットされたものは1つも無い** | **未着手**。知見ログに手法は書いてあるが再現可能な資産ではない |
| 4. 実行結果検証 | 知見129以降、新しく書くテストでは出力値を必ずアサートする運用が確立している。ただし(a)これはコードレビュー慣習であって仕組みでは強制されていない、(b)知見129より前に書かれた既存テストの遡及棚卸しは一度も実施していない | **部分的**。新規分は良い状態、既存分は未検証のまま残っている可能性 |
| 5. ランタイムサービス地図 | `IListIndexService`・DPAPI・比較エンジン・`CSVUtilities`等、個別には`dsl_format_findings.md`の各知見に記録済み。1箇所に集約した地図ドキュメントは存在しない。「他にどんなサービスがあるか」の先回り探索は未実施 | **素材はあるが未集約**。地図を作る作業自体は低コスト |
| 6. 知見ログ/TODOのメタ規約 | PAD側・UiPath側それぞれ独立に同型のドキュメントペアを運用し、どちらも機能している。しかし「このやり方自体」を説明するメタドキュメントは存在せず、両トラックの対応関係(どのファイルがどちらの役割か)も暗黙知 | **実践は成熟、ドキュメント化はゼロ** |
| 7. 検証基盤・シミュレータ | (b)`tests/fake_pywinauto.py`(pywinauto)・(c)`tests/fake_win32.py`(win32gui/win32con)の2モジュールを実装し、計3件のcodegenテスト(Click/MoveWindow/SetWindowVisibility)を文字列検査のみ→実際の`exec()`検証へ移行済み。`.wait()`/`.wait_not()`/`.child_window()`/`.set_focus()`/`.type_keys()`は(b)に実装済みだがまだcodegenテストから使われていない。`win32timezone`/`win32crypt`は(c)未対応。(a)record/replay化は未着手(今もVM確認結果は知見ログの文章としてのみ残り、再利用可能な構造化データではない) | **(b)(c)初版あり、拡張の余地が大きい。(a)(d)は未着手** |

---

## ギャップ分析とTODO(フェーズ分け)

リスクの低い順に並べている。Phase 0〜1は既存コードの挙動を一切変えない追加作業、Phase 2以降はソースツリーの構造を変える、かつUiPathトラックと調整が必要。

### Phase 0: ドキュメント化・資産化のみ(コード変更ゼロ、両トラックへの影響ゼロ)

- [ ] `design/pad_runtime_services.md`を新設し、既知のランタイムサービス(`IListIndexService`/DPAPI/比較エンジン/`CSVUtilities`等)を1ページに集約する(層5)
- [ ] 知見135-137の監査スクリプトを`tools/`配下にコミットする(層3)。これ自体は即座に再利用可能な資産になる
- [ ] `design/KNOWLEDGE_LOG_CONVENTIONS.md`を新設し、知見ログ+TODOの運用パターンを明文化する(層6)。PAD/UiPath双方のドキュメント対応表も含める
- [ ] 層4の規約(「exec()テストは出力値まで必ずアサートする」)を明文化し、新規テストに適用を義務付ける
- [x] **層7(b)着手**: `tests/fake_pywinauto.py`を新設(`Desktop`/`.window()`/`.child_window()`/`.exists()`/`.wrapper_object()`/`.click_input()`/`.set_focus()`/`.type_keys()`/`.wait()`/`.wait_not()`のフェイク)、`UIAutomation.Click.Click`の既存codegenテストを実際に`exec()`する形へ1件移行。`set_active()`(ウィンドウごとの`is_active()`状態をレジストリ側で保持——`wrapper_object()`は呼ぶたびに新しいオブジェクトを返すため個々のオブジェクトでは状態を持てない)を追加し、`UIAutomation.IfWindow.*`4モード×ウィンドウ存在/フォーカス状態10パターンを、生成された条件式を実際に`eval()`して真偽値まで検証するテストへ拡張(実機キャプチャのTHENブロックが`pass`のみで文字列検査では分岐の実際の真偽を観測できなかった穴を塞いだ)。`.close()`も追加し`FocusWindow`/`CloseWindow`の既存codegenテスト2件も`exec()`検証へ移行。
  また、`pywinauto.Desktop`の差し替え/復元をテストごとに手書きしていた重複(4箇所)を
  `fake_pywinauto_desktop()`コンテキストマネージャに集約した(`tests/fake_win32.py`の
  `fake_win32_modules()`と対になる設計)。
  **2026-11-05追記**: `UIAutomation.WaitForWindow.*`の既存2テスト(タイムアウト指定あり/
  無期限ポーリング)を`compile()`のみ→実際に`exec()`して検証する形へ移行完了。
  タイムアウト指定ありの方は`registry.calls`に`("wait", ..., {"criteria": "exists",
  "timeout": 5})`が実際に記録されることまで確認、無期限ポーリングの方はウィンドウを
  事前登録した状態でexec()し、ループが即座に(ハングせず)抜けることを確認した
  (いずれも`Scripting.RunPythonScript`のハードコードされたWindowsパス書き込みを含む
  フィクスチャのため、既存の一時ディレクトリ退避パターンを適用)。`WaitForWindowContent.WindowToContainElement`(Element側のwait)もControlRepository
  ありの経路をexec検証する新規テストを追加した(`register_descendant()`で対象の
  子孫コントロールを事前登録し、ループが即座に抜けることを確認)。層7(b)でまだ
  exec検証していないcodegenテストの残りは、`.child_window()`を使う他のアクション
  (UIAutomation系の一部)の棚卸しが次の拡張候補
- [ ] 層7(a): VM確認結果を構造化データ(JSON等)として永続化するrecord/replay形式を設計する
- [x] **層7(c)着手**: `tests/fake_win32.py`を新設(`win32gui`/`win32con`、`GetWindowRect`/
  `MoveWindow`/`ShowWindow`/`GetForegroundWindow`/`SW_SHOW`/`SW_HIDE`のフェイク)。
  `win32gui`/`win32con`はpywinautoと違いLinuxでは`import`自体が失敗するため、属性の
  差し替えではなく`sys.modules`へのフェイクモジュール注入方式を取った。`MoveWindow`/
  `SetWindowVisibility`の既存codegenテスト2件を実際に`exec()`する形へ移行。
  **2026-11-05追記**: `ResizeWindow`(`MoveWindow`と同じ`win32gui.MoveWindow()`への
  委譲だが、既存のX/Yを保持しつつ幅/高さだけ更新する点が対称)にも同じパターンの
  exec検証テストを追加。
  残り: `win32timezone`/`win32crypt`は未着手

### Phase 1: 追加のみ(既存の出力形式は変えずに内部だけ型を強化)

- [ ] `pad_codegen`に理由コード付き`Unsupported`型を導入し、既存の`# TODO`コメント文字列はこの型からの射影として**同じ見た目を保ったまま**生成するようにリファクタ(層2)。外部から見た生成コードは変わらないので低リスク
- [ ] 層4の規約をlint化する(`exec(code, namespace)`の後に`namespace[...]`へのアサートが続いているかを検出する簡易チェック)。既存テストへの遡及適用は別タスクとして切り出す
- [ ] 既存テストの遡及棚卸し(知見129より前に書かれたexec()テストで、出力値を見ていないものを列挙し、1件ずつ追記)——有限のバックログタスク

### Phase 2: 共通IRの抽出(UiPathトラックと調整必須)

- [x] `rpa_ir`パッケージを新設し、`Value`系(`Literal`/`VarRef`/`RawExpr`/`EnumRef`)を移行する(両トラックで構造が一致しており最もリスクが低い統合対象)。**2026-11-05実施**: `dump_daemon/rpa_ir/values.py`に`Literal`/`VarRef`/`RawExpr`/`EnumRef`(+`Value`union)を定義し、`pad_dsl.types`は同一クラスを再公開する形に移行済み(`isinstance`の対象が同一クラスオブジェクトになるよう再定義ではなく再公開)。既存の`pad_dsl`利用側・テストは無変更で動作(`uv run pytest -q`: 1009 passed, 28 skipped、移行前と同数+新規4件)。`uipath_dsl.types`側の移行(`VbExpr`→`RawExpr`統合含む)は、UiPathトラックを並行開発中の別セッションとの衝突を避けるため意図的に見送り中——次のステップは`SwitchNode`の共通化検討
+- [ ] `SwitchNode`の`rpa_ir`移行は**当初の想定より難しい**(2026-11-05、`uipath_dsl.types.SwitchNode`を読み取り調査して判明): PAD側`arms: list[tuple[SwitchArmHeader, list[Node]]]`の`SwitchArmHeader`(`SwitchCaseRecord | SwitchDefaultRecord`)は比較演算子付きの`CASE <op> <value>`(知見33)を表せるが、UiPath側`SwitchArm`は`key: str | None`という等価比較専用のディスパッチ(辞書キー相当)で、演算子という概念自体が無い——**見た目が同じ「アーム列」でも意味論が違う**ため、単純な型統合ではなく「PAD拡張用のオプショナル演算子フィールドを持つ共通型にするか、ツールごとに別のArm型のまま`Node`だけ共有するか」という設計判断が先に必要。`ConditionalNode`(N-ary)と同種の決定事項であり、着手前にユーザーに相談する
- [ ] UiPath側の活動ごと専用dataclass(`MessageBoxNode`等)を、汎用`ActionCallNode`へ段階的に置き換える。**この変更はUiPath側の`uipath_codegen`のdispatchロジック(現在は型ごとのisinstanceチェーン)にも影響するため、UiPathトラックの作業と正面から衝突する**——着手前に両トラックの作業状況を確認し、ユーザーに実施タイミングを確認する
- [ ] `ConditionalNode`(N-ary)と`IfNode`(binary)の統合方針を決める(binaryをN-aryの特殊形として扱うのは技術的には容易だが、UiPath側の既存コードをすべて書き換える必要がある)
- [ ] `ErrorHandlingNode`の`attachment`フィールドで`GuardedNode`/`TryCatchNode`の構築方向差を吸収する設計を確定する

### Phase 3: 共通dispatch基盤の統合(Phase 2の成果を前提、最もリスクが高い)

- [ ] PAD側の`CodegenContext`+chain-of-responsibility型`actions/`ディスパッチパターンを共通化し、UiPath側にも適用する(UiPath側は現在このパターンを持たず、1000行超のフラットなif-chainになっている——構造改善の価値自体は高いが着手コストも大きい)
- [ ] 層2の`Unsupported`理由コードをUiPath側にも適用する

---

## 進め方についての所感

- Phase 0は**今すぐ着手してよい**(ドキュメント・ツールの追加のみ、他セッションの作業と衝突しない)。
- Phase 1もリスクは低いが、PAD側のコード変更を伴うため、通常の開発ティックの中で段階的に進めるのが妥当。
- Phase 2以降は、**UiPathトラックの実装が今まさに活発に進行中**(本セッション中も`uipath_codegen/__init__.py`等が並行して更新されていた)であるため、「IRを共通化する」という変更は必然的にUiPath側のソースにも手を入れることになる。これは他セッションの作業と真正面から競合しうる変更であり、**着手前に必ずユーザーに実施タイミング・両トラックの調整方法を確認すること**。
- Phase 2・3を経ても、PAD/UiPathの「フロントエンド(字句解析/XML解析)」は統合する価値が無い(ツールごとの事情が違いすぎる)。統合すべきは一貫して**バックエンド**(IR以降)である。
