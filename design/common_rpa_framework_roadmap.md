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
- **2026-11-05追記(実装を進める中で判明した訂正)**: 上の`ConditionalNode`サンプルの
  「binaryはN-aryの特殊形として表現できる」という見立ては、実際に両トラックのコードを
  読んだ上で**採用しないことに決めた**(Phase 2の決定事項参照)。`SwitchNode`も見た目ほど
  単純ではなく、UiPathは等価専用ディスパッチだがPADは比較演算子付き`CASE`を持つ
  (Phase 2参照、共通`Arm`型に`operator: str | None`を追加する設計で対応予定)。
  零ベースで考えた最初の素描と、実装に踏み込んだ後の現実には差があったという記録として
  この節は訂正せずに残す。
- `ActionCallNode`(文字列キー+辞書の汎用レコード)は、UiPathが現在活動ごとに専用dataclass(`MessageBoxNode`/`ClickNode`等、11種+`UnknownActivityNode`)を持っている構造からの**移行コストを伴う**——ただし移行する価値は高い。専用dataclassは活動が増えるたびに型を増やす必要があるが、汎用レコードは「新しい活動=新しいaction_idの文字列」でしかなく、PAD側で116アクションまで線形にスケールした実績がある。
- `ErrorHandlingNode`: PADの`GuardedNode`(直前の文に遡及的に付与)とUiPathの`TryCatchNode`(先頭から囲む)は**構築方向が逆**で、これは単なる命名の違いではなく実際のツールの挙動差である。共有型に無理に1つの構築手順を強制せず、`attachment`フィールドで明示する(でっち上げない方針をIR設計自体にも適用する)。
  **2026-11-05追記(この見立ても`ConditionalNode`/`IfNode`と同じ理由で撤回)**: 実際の
  両トラックの型(`GuardedNode`/`OnErrorNode`の判別子`case_name`は任意ラベル、
  `TryCatchNode`/`CatchArm`の判別子`exception_type`は実際の.NET型、`finally_body`/
  `variables`はUiPath専用)を読んだ結果、`attachment`1フィールドでは吸収できない
  非対称性が複数あると判明し、Phase 2で**統合しない**と決定した。

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
| (c) **pad_codegen/pad_action_libのOS依存コード**(`win32timezone`/`win32crypt`/`win32gui`等pywin32の薄いラッパー、および`MouseAndKeyboard.*`が委譲する`pyautogui`) | 「正しい引数でOS依存APIを呼んでいるか」——(b)と同種、呼び出し側のロジック検証 | **安全かつ高ROI**。一般的なテストダブル手法で対応可能 |
| (d) **模擬対象アプリ**(例: 模擬Notepad) | (b)より高い再現度(実UIAプロトコル越しの通信まで)で検証したい場合 | 価値はあるが、UIA自体がWindows OS機能のため「Windowsが丸ごと不要になる」わけではない。(b)と違う軸の投資であり優先度は低い |

**(b)の実装(完了)**: `tests/fake_pywinauto.py`に、生成コードが実際に呼び出す最小限のpywinauto API表面(`Desktop(backend="uia")`/`.window()`/`.child_window()`/`.exists()`/`.wrapper_object()`/`.click_input()`/`.set_focus()`/`.type_keys()`/`.wait()`/`.wait_not()`)だけをフェイク実装した。`pywinauto.Desktop`をこのフェイクに差し替えてから生成コードを`exec()`すれば、実Windows・実アプリ無しで「正しいセレクタ・正しい操作列で呼ばれたか」をアサートできる。未知の呼び出し形は素直に`AttributeError`になる(でっち上げて成功させることはしない)。`test_generate_python_from_click_click_actually_clicks_against_fake_pywinauto`で、既存の「文字列として生成コードを検査するだけ」のテストを「実際に`exec()`して動作を検証する」テストへ格上げする実例を示した。現状Linux上でこの種のテストは0件だった(pywinautoを要する生成コードは一切`exec()`されていなかった)ので、新規にカバレッジが生まれた形。

**(c)のpyautogui実装(2026-11-05追記)**: `win32gui`/`win32con`と同じ理由(`pyautogui`は
本プロジェクトの依存関係にすら入っておらず、ディスプレイ依存のためそもそも
インストールしても`import`できないことがある)で、`tests/fake_win32.py`と同じ
`sys.modules`注入方式の`tests/fake_pyautogui.py`を新設した。`MouseAndKeyboard.*`が
生成する5つの呼び出し形(`click()`/`moveTo(x, y)`/`typewrite(text, interval=...)`/
`keyDown(key)`/`keyUp(key)`)をフェイクし、既存の5つのcodegenテスト
(SendKeys/MoveMouse/SendMouseClick×2/PressReleaseKey×2)を文字列検査のみ→実際の
`exec()`検証へ移行した。

**(a)のrecord/replay化(未着手)**: 今回VMで確認した入出力ペア(例: `IListIndexService.ConvertInput()`の挙動、`CopyFolder`の`Destination`意味論)を、構造化データ(JSON等)として`design/`または専用ディレクトリに永続化し、「既に確認済みの事実」をもう一度VMに聞き直す無駄を無くす。新しい疑問には引き続きVMで答える必要があるが、過去の確認結果の再利用コストはゼロになる。

---

## 現状評価(層ごと)

| 層 | 現状 | 評価 |
|---|---|---|
| 1. 共通IR | `Value`系(`Literal`/`VarRef`/`RawExpr`/`EnumRef`)は`rpa_ir`へ移行済み(PAD側、UiPath側は見送り中)。`SwitchNode`は見た目ほど同形ではないと判明(PADは比較演算子付き`CASE`、UiPathは等価専用)——共通`Arm`型に`operator: str | None`を加える設計は決定済みだが実装は未着手。`ConditionalNode`(N-ary)↔`IfNode`(binary)は**統合しない方針で確定**(構築コストが非対称、どちらのcodegenも得をしないため)。`GuardedNode`(遡及付与、判別子は任意ラベル`case_name`)↔`TryCatchNode`(先頭包含、判別子は実際の.NET型`exception_type`、`finally_body`/`variables`はUiPath専用)も`ConditionalNode`/`IfNode`と同じ理由で**統合しない方針で確定**。`ActionCallNode`相当はPAD側のみ汎用化済み、UiPathは活動ごとの専用dataclass(未着手)。 | **Value系は着手済み、他は「統合しない」決定を含めて設計が進んだ** |
| 2. 型での契約強制 | 両トラックとも`return None`→汎用TODO、という同じ「規約」を持つが、PAD側は1箇所に集約されたTODOレンダラ、UiPath側は呼び出し箇所ごとに手書きの自由文字列。理由コードは両方とも無し(自由文字列のみ) | **部分的**。規約はあるが型で強制されていない、理由の構造化なし |
| 3. 発見ツール | 今回確立した監査手法(知見135-137)はPowerShellスクリプトとしてVM上で毎回その場で書いて実行しているだけで、**リポジトリにコミットされたものは1つも無い** | **未着手**。知見ログに手法は書いてあるが再現可能な資産ではない |
| 4. 実行結果検証 | 知見129以降、新しく書くテストでは出力値を必ずアサートする運用が確立している。`tools/check_exec_assertions.py`で慣習をツール化済み(手動実行のレビュー補助、CI gateではない)——`tests/test_pad_codegen.py`全件への初回実行で実際に1件の見逃しを発見・修正した。ただし既存テストの遡及棚卸しは(今回の1件を除き)まだ実施していない | **部分的だが前進**。新規分は良い状態、ツールで能動的に見逃しを探せるようになった |
| 5. ランタイムサービス地図 | `design/pad_runtime_services.md`に8項目(比較エンジン・数値文字列認識・`/`/`mod`・CSV・`IListIndexService`・DPAPI・Filter/JoinParameters・DateTimeタイムゾーン)を集約済み。「他にどんなサービスがあるか」の先回り探索(Web Cookieジャー等、横断性が弱いものは意図的に対象外)は依然未実施 | **集約完了**。新サービス発見時の追記が今後の運用 |
| 6. 知見ログ/TODOのメタ規約 | `design/KNOWLEDGE_LOG_CONVENTIONS.md`に規約とファイル対応表を明文化済み。次にもう1つツールを調査する際、この1ページを指し示せる状態になった | **ドキュメント化完了** |
| 7. 検証基盤・シミュレータ | (b)`tests/fake_pywinauto.py`(pywinauto)・(c)`tests/fake_win32.py`(win32gui/win32con)・`tests/fake_pyautogui.py`(pyautogui)の3モジュールを実装し、Window/Click/IfWindow/WaitForWindow系・MouseAndKeyboard系で計30件超のcodegenテストを文字列検査のみ→実際の`exec()`検証へ移行済み。`win32timezone`/`win32crypt`は(c)未対応。(a)record/replay化は未着手(今もVM確認結果は知見ログの文章としてのみ残り、再利用可能な構造化データではない) | **(b)(c)かなり充実、(a)(d)は未着手** |

---

## ギャップ分析とTODO(フェーズ分け)

リスクの低い順に並べている。Phase 0〜1は既存コードの挙動を一切変えない追加作業、Phase 2以降はソースツリーの構造を変える、かつUiPathトラックと調整が必要。

### Phase 0: ドキュメント化・資産化のみ(コード変更ゼロ、両トラックへの影響ゼロ)

- [x] `design/pad_runtime_services.md`を新設し、既知のランタイムサービス(`IListIndexService`/DPAPI/比較エンジン/`CSVUtilities`等)を1ページに集約する(層5)。
  **2026-11-05実施**: 比較エンジン・数値文字列認識規則・`/`/`mod`の意味論・CSV区切り文字と
  固定長パース・`IListIndexService`(0始まり確定)・DPAPI復号・`FilterParameters`/
  `JoinParameters`スキーマ・DateTimeタイムゾーン対応表の8項目を、既存知見(知見65・81・83・
  85・86・88・90・91・92・97・98・99・100-107・112・116・127・128・132・133・138)から
  集約した。新しい事実の確認は行っていない(既存知見の再配置のみ)。
- [ ] 知見135-137の監査スクリプトを`tools/`配下にコミットする(層3)。これ自体は即座に再利用可能な資産になる
- [x] `design/KNOWLEDGE_LOG_CONVENTIONS.md`を新設し、知見ログ+TODOの運用パターンを明文化する(層6)。PAD/UiPath双方のドキュメント対応表も含める。
  **2026-11-05実施**: 「番号は不変・追記専用、訂正は新しい知見番号で行う」という規約を
  git履歴で実証確認(知見97が知見91を書き換えずに訂正していることを確認)した上で明記。
  PAD/UiPathのファイル対応表(知見ログ↔TODO↔段階計画↔式変換ドキュメント)、および
  どちらのトラックにも属さない横断ドキュメント(本roadmap・runtime_services・
  CI検証系)の位置付けも整理した。
- [x] 層4の規約(「exec()テストは出力値まで必ずアサートする」)を明文化し、新規テストに適用を義務付ける。
  **2026-11-05実施**: Phase 1の`tools/check_exec_assertions.py`(下記参照)として明文化・
  ツール化を同時に達成した——重複追跡を避けるため、本項目はそちらと同一の成果として
  完了扱いにする。
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
  子孫コントロールを事前登録し、ループが即座に抜けることを確認)。
  **2026-11-05追記**: `fake_pywinauto.py`に`.maximize()`/`.minimize()`/`.restore()`
  (`SetWindowState`、知見27)を追加し、Title/Classベース・Controlベース両方の
  codegenテストをexec検証へ拡張した(呼び出しが正しいパス・引数で記録されることまで確認)。
  層7(b)でまだexec検証していないcodegenテストの残りは、Click/IfWindow以外の
  `UIAutomation.*`アクション(`GetWindow`の戻り値、多要素内部セレクタのチェーン等)の
  棚卸しが次の拡張候補
  **2026-11-05追記(instance/handleベースの兄弟セレクタ4件)**: `WindowInstance`が
  PAD側では不透明な参照でもPython側では通常の変数参照に過ぎない(知見79/80)という
  性質を利用し、`FakeControl`を直接名前空間へ注入する手法で
  `SetWindowState.SetStateByInstanceOrHandle`/`MoveWindow.MoveByInstanceOrHandle`/
  `ResizeWindow.ResizeByInstanceOrHandle`/`SetWindowVisibility.SetVisibilityByInstanceOrHandle`
  の4件もexec検証へ拡張した(`Title`/`Class`ベースの兄弟セレクタとは別の変数解決経路を
  通る分岐のため、独立した検証価値がある)。
  **2026-11-05追記(多要素内部セレクタのチェーン、知見56の退行防止)**: 電卓の「7」ボタン
  (`Window`→`CalcFrame`→`Button`の3段チェーン)の`compile()`のみテストにexec検証を
  追加した。知見56のバグ(チェーンが中間のpane要素止まりになる)はまさに「正しい形の
  呼び出し列を組み立てているか」という層7(b)の守備範囲そのものなので、`.click_input()`
  が3段の正しいフルパスで(ループ2回分)呼ばれることまで確認し、退行(チェーンが途中で
  切れる)を検知できるようにした。
  **2026-11-05追記(`GetForegroundWindow`、知見117)**: `fake_pywinauto.py`に
  `.window_text()`(`set_window_text()`で値を設定できるgetter、`set_active()`と同じ
  レジストリ側状態保持パターン)を追加し、`win32gui.GetForegroundWindow()`→
  `Desktop(...).window(handle=...)`→`.window_text()`という3段の変換を一通りexec検証
  できるようにした。
  **2026-11-05追記(`CloseWindow`/`FocusWindow`のControl/InstanceOrHandle系4件)**:
  `CloseWindow.Close`/`FocusWindow.Focus`(Controlベース)・`CloseByInstanceOrHandle`/
  `FocusByInstanceOrHandle`(WindowInstance変数ベース)の4テストにexec検証を追加した
  (`ByTitleClass`系の兄弟セレクタは既にexec検証済みだったため、まだ手薄だった残り2系統を埋めた)。
  **2026-11-05追記(`IfWindow`のWindowInstance変数ベース4モード)**: 既存の
  `test_generate_python_if_window_modes_evaluate_correctly_against_fake_pywinauto`は
  `Window: appmask[...]`(Control/リポジトリ経由)の経路しか真偽値まで検証していなかった
  ——`WindowInstance`変数ベースの兄弟セレクタ(`IsOpenByInstanceOrHandle`等)4モードにも
  同じ10パターン(ウィンドウ存在/フォーカス状態×期待値)の`eval()`検証を追加した。
  続けて`Title`+`Class`ベースの兄弟セレクタ(`IsOpenByTitleClass`等)4モードにも同じ
  10パターンを追加し、`IfWindow`の3系統(Control/WindowInstance/TitleClass)全てで
  真偽値レベルの検証が揃った。
  **2026-11-05追記(`GetWindow.Get`/`SetWindowVisibility.SetVisibilityByTitleClass`)**:
  `GetWindow.Get`(`.GetUseTimeout`の兄弟セレクタ)は代入された変数の`.criteria`まで、
  `SetVisibilityByTitleClass`は`win32gui.ShowWindow()`の呼び出し引数までexec検証を追加した。
  `MoveWindow.Move`(Controlベースの兄弟セレクタ)にも`win32gui.MoveWindow()`の引数まで
  exec検証を追加し、`MoveWindow`系(ByTitleClass/ByInstanceOrHandle/Control)3系統が揃った。
  **2026-11-05追記(実在のテストカバレッジの穴を発見)**: `UIAutomation.*`の3セレクタ構造
  (Control/WindowInstance/Title+Class)系統を全て機械的に突き合わせたところ、
  `ResizeWindow.Resize`(Controlベース)だけ**compileテストすら1件も存在しない**ことが
  判明した(`ResizeByTitleClass`/`ResizeByInstanceOrHandle`は既存)。新規にcompile+exec検証
  テストを追加し、`MoveWindow`/`ResizeWindow`/`SetWindowState`/`SetWindowVisibility`/
  `CloseWindow`/`FocusWindow`/`GetWindow`の全系統で3セレクタ構造それぞれに最低1件の
  テストが揃ったことを確認した。
  **2026-11-05追記(`codegen_coverage.py`の自動フィクスチャ走査との食い違いを発見)**:
  `codegen_coverage.py`はフィクスチャを自動globして`[OK]`判定するため、
  `UIAutomation.WaitForWindow.ToBecomeFocused`/`ToLoseFocus`/`ToClose`は
  カバレッジレポート上は常に`[OK]`だったが、実際には`test_pad_codegen.py`側に
  リポジトリあり(実コード生成)経路のexec検証が一度も存在しなかった
  (`ToBecomeFocused`/`ToLoseFocus`はリポジトリ無しのTODOフォールバック経路しか
  テストされておらず、`ToClose`はテスト自体が0件だった)。3件とも新規にexec検証
  テストを追加した——「`codegen_coverage.py`が`[OK]`と言っている」ことと
  「`test_pad_codegen.py`に対応する検証がある」ことは別の尺度だという教訓。
  同じ観点で`UIAutomation.GetWindow.GetUseTimeout`(実機キャプチャ、whole-subflow)も
  compile()のみだったためexec検証を追加した。`[OK]`扱いの`UIAutomation.*`全9ブランチ
  (`Click.Click`/`CloseByInstanceOrHandle`/`GetUseTimeout`/`IfWindow.IsOpen`/
  `WaitForWindow`系5件)を1件ずつ確認し、全てexec検証が揃ったことを確認した。
  **2026-11-05追記(`File.IfFile.Exists`/`Folder.IfFolderExists.Exists`の追加、
  および手書きDSL文字列の既知の落とし穴を発見)**: 両セレクタにexec+eval検証を
  新規追加する過程で、手書きのテスト用DSL文字列(`"IF (...) THEN\nSET X TO 1\nEND"`、
  本体をインデントしない)だと`pad_dsl.block_tree`がIFの本体を空と解釈し、`SET X TO 1`
  がIFの外側(無条件)へ漏れることを発見した——`exec()`後に`namespace["X"] == 1`だけを
  見るテストは、真の分岐しかテストしていない場合にIFのゲートが壊れていても気づけない
  (本物のPAD DSLは本体を必ずインデントするため実害は無いが、テストの書き方としては
  罠)。既存の`IfFile.DoesNotExist`/`IfFolderExists.DoesNotExist`テストに偽の分岐の
  検証を追加し、この罠を`tests/test_pad_codegen.py`の冒頭docstringに明記した。
- [ ] 層7(a): VM確認結果を構造化データ(JSON等)として永続化するrecord/replay形式を設計する。
  **2026-11-05追記(設計検討のみ、まだ未着手)**: `design/schemas/`には既に
  `ir_trace.schema.json`/`ui_tree_snapshot.schema.json`(G1/G2検証プロトコル用、
  UIツリー・スクリーンショットの実行トレース記録)が存在するが、これは層7(a)が
  想定する「VM確認済みの事実の再利用」とは**別の目的**(1回の実行の挙動キャプチャ)
  であり代替にはならないと確認した。一方、層7(a)が本当に欲しいもの
  (`IListIndexService.ConvertInput()`の挙動、`CSVColumnsSeparator`マッピング等)は
  既に`design/pad_runtime_services.md`(層5、本セッションで新設)と、確認済みの値を
  直接埋め込んだPythonコード自身(`_NUMERIC_STRING_RE`/`_DPAPI_ENTROPY`/
  `_support.py`のマッピング辞書等、いずれも知見番号を引用するdocstring付き)という
  形で**既に十分に再利用可能**になっている——これらはまさに「もう一度VMに聞き直す
  必要がない」状態そのもの。層7(a)として**本当に未解決なまま残っている**のは、
  知見135-137の`ActionSelectorBase`一括列挙監査(層3)のような**生のリフレクション
  列挙結果**(例: `Database.Actions.dll`の全セレクタ名一覧)で、これは実行するたびに
  VM上で再列挙しているため、取得結果をJSONとして保存すれば次回から再列挙不要になる
  ——つまり層7(a)と層3(発見ツールの`tools/`化、VM依存のため未着手)は実質的に
  同じ前提(VMアクセス)に依存する一体の投資だと判明した。両方ともVMが実際に使える
  タイミングで、監査スクリプトの出力を構造化JSONとして保存する形で同時に着手するのが
  筋が良い(設計方針の確定、実装はVM待ち)。
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
- [x] 層4の規約をlint化する(`exec(code, namespace)`の後に`namespace[...]`へのアサートが続いているかを検出する簡易チェック)。
  **2026-11-05実施**: `tools/check_exec_assertions.py`を新設(AST解析で`test_*`関数内の
  `exec()`呼び出しを検出し、後続に`namespace[...]`/`.calls`/`eval(`/ファイル読み返し系
  (`.read_text(`等)のいずれも無ければ報告する——CIを止めるハードgateではなく
  `uv run python3 tools/check_exec_assertions.py`で手動実行するレビュー補助)。
  `tests/test_pad_codegen.py`全件に実行したところ**実際に1件、本物の見逃しを発見**
  (`test_generate_python_from_real_if_function_contains_batch_converts_all_four`——
  コメントで「実際に真偽値として正しく評価できることまで確認する」と書きながら、
  実際には`exec()`がクラッシュしないことしか見ていなかった)。4条件式を`eval()`して
  期待する真偽値と一致することまで検証するよう修正した。残り2件(無期限ポーリングが
  ハングせず即座に終了することだけを確認するテスト)は既知の妥当な例外としてツール
  自身のdocstringに記録した。既存テストへの遡及適用(今回の1件の修正を除く)は
  意図的に別タスクとして切り出したまま。
- [x] 既存テストの遡及棚卸し(知見129より前に書かれたexec()テストで、出力値を見ていないものを列挙し、1件ずつ追記)。
  **2026-11-05実施**: `tools/check_exec_assertions.py`をUiPathトラックのテストを除く
  PAD側テストファイル全件(`tests/test_*.py`、UiPath以外の40ファイル)に実行した。
  結果は2件のみで、いずれもツール自身のdocstringに記録済みの既知の妥当な例外
  (無期限ポーリングが即座に終了することだけを確認するテスト)——それ以外に
  未発見の「出力値を見ていない」テストは残っていないことを確認した(本項目で
  挙げていた1件は、ツール新設時に既に発見・修正済み)。これで棚卸しは完了。

### Phase 2: 共通IRの抽出(UiPathトラックと調整必須)

- [x] `rpa_ir`パッケージを新設し、`Value`系(`Literal`/`VarRef`/`RawExpr`/`EnumRef`)を移行する(両トラックで構造が一致しており最もリスクが低い統合対象)。**2026-11-05実施**: `dump_daemon/rpa_ir/values.py`に`Literal`/`VarRef`/`RawExpr`/`EnumRef`(+`Value`union)を定義し、`pad_dsl.types`は同一クラスを再公開する形に移行済み(`isinstance`の対象が同一クラスオブジェクトになるよう再定義ではなく再公開)。既存の`pad_dsl`利用側・テストは無変更で動作(`uv run pytest -q`: 1009 passed, 28 skipped、移行前と同数+新規4件)。`uipath_dsl.types`側の移行(`VbExpr`→`RawExpr`統合含む)は、UiPathトラックを並行開発中の別セッションとの衝突を避けるため意図的に見送り中——次のステップは`SwitchNode`の共通化検討
- [ ] `SwitchNode`の`rpa_ir`移行は**当初の想定より難しい**(2026-11-05、`uipath_dsl.types.SwitchNode`を読み取り調査して判明): PAD側`arms: list[tuple[SwitchArmHeader, list[Node]]]`の`SwitchArmHeader`(`CaseRecord | CaseDefaultRecord`、`CaseRecord.operator: str | None`)は比較演算子付きの`CASE <op> <value>`(知見33)を表せるが、UiPath側`SwitchArm`は`key: str | None`という等価比較専用のディスパッチ(辞書キー相当)で、演算子という概念自体が無い——**見た目が同じ「アーム列」でも意味論が違う**。
  **設計案(2026-11-05、実装はまだしていない・UiPathトラックとの調整待ち)**: 共通`Arm`型を
  `key: Value | None`(`None`=`DEFAULT`/catch-all)・`operator: str | None`
  (`None`=等価比較、`CaseRecord.operator`と同じ値域の文字列)・`body: list[Node]`の3フィールドに
  する。UiPath側は`operator`を常に`None`のまま使えば現状の意味論を一切変えずに型だけ共通化できる
  (UiPath自身のdispatchロジックは変更不要)。PAD側は`CaseRecord.operator`をそのまま`Arm.operator`に
  渡すだけ。つまり**UiPathにとっては無害な追加フィールド**であり、「ツールごとに別のArm型のまま
  `Node`だけ共有する」という代替案より統合度が高く、かつUiPath側のコード変更ゼロで済む。
  `ConditionalNode`(N-ary)の統合方針と同じく、UiPathトラックとの調整・ユーザーへの実施タイミング
  確認が実装着手の前提(本項目は設計のみ、まだ着手していない)。
- [ ] UiPath側の活動ごと専用dataclass(`MessageBoxNode`等)を、汎用`ActionCallNode`へ段階的に置き換える。**この変更はUiPath側の`uipath_codegen`のdispatchロジック(現在は型ごとのisinstanceチェーン)にも影響するため、UiPathトラックの作業と正面から衝突する**——着手前に両トラックの作業状況を確認し、ユーザーに実施タイミングを確認する
- [x] `ConditionalNode`(N-ary)と`IfNode`(binary)の統合方針を決める。
  **決定(2026-11-05、「安全かつ投資価値があるものを優先」というユーザー方針を受けて検討)**:
  **統合しない**。両者は見た目は似ているが、統合してもどちらのトラックのcodegenも
  得をしない——`ConditionalNode`は`pad_codegen`だけが消費し、`IfNode`は`uipath_codegen`
  だけが消費していて、両方を同じ型として横断的に処理するコードは現状どこにも無い
  (Phase 3の「共通dispatch基盤」のような将来の消費者が実際に必要になった時点で
  再検討すればよい)。しかも変換方向は非対称にコストが高い:
  PAD→binary(N-ary を `if/else{ if/else{...} }` の入れ子に展開)は機械的に可能だが、
  UiPath側は元々`elseif`という構文自体を持たず(XAML上も`If.Else`に`If`を再帰的に
  ネストして表現する、知見5)、binary→N-aryへ戻す変換はXAMLの実際のネスト構造を
  読み解く必要がある非対称な変換になる。「同じに見えるものを無理に同じ型にする」のは
  過剰統合(over-abstraction)であり、`ErrorHandlingNode`の`attachment`フィールドと同じ
  「でっち上げない」方針([層1](#層1-共通ir中間表現)参照)を型の統合方針そのものにも
  適用した——構築方向・構文上のネスト可否が違う構造は、違う型のままにしておく方が
  誠実。本項目は**設計判断の確定**であり、コード変更は無い(両トラックとも現状の型を
  そのまま使い続ける)。
- [x] `ErrorHandlingNode`の`attachment`フィールドで`GuardedNode`/`TryCatchNode`の構築方向差を吸収する設計を確定する。
  **決定(2026-11-05、実際の両トラックの型定義を読んで判明——`ConditionalNode`/`IfNode`と
  同じ結論)**: **統合しない**。層1素描時点の「`attachment`フィールドだけで吸収できる」
  という見立ては、実際に`dump_daemon/pad_dsl/types.py`(`GuardedNode(node, on_error)`・
  `OnErrorNode(arms: list[tuple[OnErrorRecord | OnBlockErrorRecord, list[Node]]])`、
  各アームの判別子は`case_name: str | None`という**任意のラベル**)と
  `dump_daemon/uipath_dsl/types.py`(`TryCatchNode(try_body, variables, catches:
  list[CatchArm], finally_body)`・`CatchArm(exception_type: str, var_name: str | None,
  body)`、判別子は`exception_type`という**実際の.NET型名**)を読んだ結果、不十分だと
  判明した。`attachment`(構築方向)の違いに加え、判別子の種類そのものが違う
  (PADは型と無関係な任意ラベル、UiPathは型階層に基づく実際の例外型)——`SwitchNode`の
  `operator`発見と同種の、見た目の類似の奥にある意味論の非対称性。さらに
  `finally_body`/`variables`(例外変数宣言)はUiPath側にしか存在しない概念で、
  `attachment`1フィールドでは説明できない非対称情報が複数ある。`ConditionalNode`/
  `IfNode`と同じ理由(横断的に両方を消費するコードが存在しない、変換コストが非対称)
  により、本項目も**統合しない**方針に変更する。コード変更は無い。

### Phase 3: 共通dispatch基盤の統合(Phase 2の成果を前提、最もリスクが高い)

- [ ] PAD側の`CodegenContext`+chain-of-responsibility型`actions/`ディスパッチパターンを共通化し、UiPath側にも適用する(UiPath側は現在このパターンを持たず、1000行超のフラットなif-chainになっている——構造改善の価値自体は高いが着手コストも大きい)
- [ ] 層2の`Unsupported`理由コードをUiPath側にも適用する

---

## 進め方についての所感

- Phase 0は**今すぐ着手してよい**(ドキュメント・ツールの追加のみ、他セッションの作業と衝突しない)。
- Phase 1もリスクは低いが、PAD側のコード変更を伴うため、通常の開発ティックの中で段階的に進めるのが妥当。
- Phase 2以降は、**UiPathトラックの実装が今まさに活発に進行中**(本セッション中も`uipath_codegen/__init__.py`等が並行して更新されていた)であるため、「IRを共通化する」という変更は必然的にUiPath側のソースにも手を入れることになる。これは他セッションの作業と真正面から競合しうる変更であり、**着手前に必ずユーザーに実施タイミング・両トラックの調整方法を確認すること**。
- Phase 2・3を経ても、PAD/UiPathの「フロントエンド(字句解析/XML解析)」は統合する価値が無い(ツールごとの事情が違いすぎる)。統合すべきは一貫して**バックエンド**(IR以降)である。
