"""UiPath `.xaml`(Windows Workflow Foundationアクティビティ木)のIRノード型定義。

`dump_daemon.pad_dsl.types`と同じ設計方針(純粋なデータ構造のみ、パース処理
(`xaml_tree.py`)には依存しない、他の全core——将来の`uipath_codegen`等——が
ここに定義された型を「共有語彙」として参照する)を踏襲する。

PADのDSLと違い、UiPathの`.xaml`はただのXMLなので、PAD側のような
「フラットなトークン列→indentベースでブロック木に組み立て直す」という
2段階パース(`tokens.py`/`line_parser.py`/`block_tree.py`)は不要——XMLの
親子関係がそのままブロック構造になる。そのため`uipath_dsl`は`pad_dsl`より
シンプルな1段階構成(`xaml_tree.py`がXML木を直接このモジュールの型へ変換する)
になっている。

スコープは[design/uipath_transpiler_roadmap.md](../../design/uipath_transpiler_roadmap.md)
のPhase 1で確定した範囲(Sequence/Flowchartのみ、Processプロジェクトのみ、
知見で実機確認済みの活動一式)に対応する。それ以外のアクティビティは
`UnknownActivityNode`として素通しし、架空の変換をでっち上げない
(`pad_codegen`の`# TODO`方針と同じ「正直さ」の踏襲)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VbExpr:
    """`[...]`角括弧で囲まれたVB.NET式テキスト(design/uipath_xaml_findings.md
    知見2・13)。角括弧を除いた中身の生テキストのみを保持する——VB.NET式
    パーサー自体(design/uipath_transpiler_roadmap.md Phase 3)は別モジュールの
    範囲で、ここでは文字列のまま持ち越す(`pad_dsl.RawExpr`と同じ「でっち上げず
    テキストを失わない」方針)。
    """

    text: str


@dataclass(frozen=True)
class Literal:
    """`[...]`で囲まれていない生の値(知見13: `x:TypeArguments`が`x:Object`
    以外の単純型の場合、属性値やテキストノードがVB式ではなく生のリテラルとして
    そのまま直列化される——例: `<InArgument x:TypeArguments="x:String">case1
    </InArgument>`の`case1`)。
    """

    value: str


Expr = VbExpr | Literal | None
"""プロパティ値の表現。角括弧式(`VbExpr`)・生リテラル(`Literal`)・未設定
(`None`、`{x:Null}`/属性省略のいずれか)のいずれか。"""


@dataclass(frozen=True)
class VariableDecl:
    """`<Variable x:TypeArguments="..." Name="..." Default="..."? />`
    (`Sequence.Variables`・`TryCatch.Variables`等のコンテナ内、知見8)。

    `default`は知見7が記録した2つの直列化形の両方に対応する——属性形
    (`Default="init"`、本fixtureの実例)と、`<Variable.Default><Literal
    x:TypeArguments="...">init</Literal></Variable.Default>`という子要素形
    (公式ドキュメント上は確認済みだが本fixtureには実例が無かったもの、
    `xaml_tree._parse_variable_default`参照)。いずれの形でも最終的には
    文字列として格納する。
    """

    name: str
    type_arguments: str
    default: str | None = None


@dataclass
class SequenceNode:
    """`<Sequence>`。`Sequence.Variables`配下の変数宣言と、直接の子アクティビティ列。"""

    variables: list[VariableDecl] = field(default_factory=list)
    body: list["Node"] = field(default_factory=list)
    display_name: str | None = None


@dataclass
class AssignNode:
    """`<Assign><Assign.To>...</Assign.To><Assign.Value>...</Assign.Value></Assign>`
    (知見2)。`target`は変数名(`OutArgument`の中身からVB式/リテラルの区別を
    解いた上での裸の変数名を期待するが、最小実装では`Expr`のまま保持し、
    単純な変数名への代入以外(プロパティアクセス付き等)は後続フェーズで解釈する。
    """

    target: Expr
    value: Expr


@dataclass
class MultipleAssignNode:
    """`<ui:MultipleAssign>`(知見122、`UiPath.System.Activities`)。
    `.AssignOperations`配下の`scg:List<ui:AssignOperation>`の各要素は
    `.To`/`.Value`を持ち、単一の`Assign`(知見2)と構造・意味論が完全に
    同じ——複数の`Assign`を1つの活動にまとめた糖衣構文に過ぎないと判断し、
    各要素を既存の`AssignNode`として素直に再利用する(新しい値表現を
    でっち上げない)。"""

    assignments: list[AssignNode] = field(default_factory=list)
    display_name: str | None = None


@dataclass
class MessageBoxNode:
    """`<ui:MessageBox Text="..." />`(知見2・5)。

    `buttons`/`chosen_button`は知見107で追加——UiPath公式ドキュメントで
    `ChosenButton`の戻り値が`"Ok"`/`"Yes"`/`"No"`/`"Cancel"`のいずれかと
    確認済み、`Buttons`(`"Ok"`/`"OkCancel"`/`"YesNo"`/`"YesNoCancel"`等)
    もGitHub上の実機保存済みXAMLで実在を確認済み。生成コードは`print()`
    一発のみ(ダイアログの対話的なブロッキング・ユーザー入力は再現しない)
    のため、`Buttons`が単一ボタン(`"Ok"`、実機確認済みの既定)以外、
    または`ChosenButton`が実際に変数へ束縛されている(=ワークフローが
    選択結果を使っている)場合は、選択の意味論を再現できないことを明示
    するため`# TODO`へ倒す(`uipath_codegen`参照)——でっち上げた
    `input()`等のユーザー入力再現は行わない。"""

    text: Expr = None
    caption: Expr = None
    buttons: str | None = None
    chosen_button: Expr = None


@dataclass
class InputDialogNode:
    """`<ui:InputDialog Title="..." Label="..." IsPassword="..."
    Options="{x:Null}" />`+`<ui:InputDialog.Result><OutArgument>...
    </OutArgument></ui:InputDialog.Result>`(知見131、`UiPath.Core.
    Activities`、`cameronmcnz/uipath-tutorials`の`NumberGuesser`・
    `MIETDevelopers/112-KavyaDhar-RPA`の`UserInp`の実機XAMLで発見)。

    `MessageBox`(上記)の「でっち上げた`input()`等のユーザー入力再現は
    行わない」という方針とは**異なる**判断になる——`MessageBox`は通知/
    選択ダイアログであり`input()`への変換自体が意味論の飛躍だが、
    `InputDialog`はそもそも「ユーザーにテキスト入力を求め、その結果を
    `Result`へ返す」活動そのもので、Pythonの`input()`組み込み関数が
    まさに同じ意味論(テキストを促し、文字列を返す)を持つ——これは
    代替・妥協ではなく直接対応する変換。

    実機確認済みの範囲: `IsPassword="False"`(2件とも確認)・`Options`
    未設定(2件とも`{x:Null}`)の組み合わせのみ安全な変換対象とする。
    `IsPassword="True"`(パスワード入力、`getpass.getpass()`が対応先と
    推測されるが実機未確認)・`Options`設定済み(選択肢付きダイアログに
    変わると推測されるが実機未確認)は、推測せず`# TODO`へ倒す。
    """

    title: Expr = None
    label: Expr = None
    is_password: str | None = None
    options: Expr = None
    result: Expr = None
    display_name: str | None = None


@dataclass
class IfNode:
    """`<If Condition="...">...</If>`(知見5)。`If.Then`/`If.Else`はそれぞれ
    0〜1個の子アクティビティを持ちうる(複数ステップなら`Sequence`でラップ
    される、知見5)——`then_body`/`else_body`はそのラップを解いたノード列。
    """

    condition: Expr
    then_body: list["Node"] = field(default_factory=list)
    else_body: list["Node"] = field(default_factory=list)


@dataclass
class ForEachNode:
    """`<ui:ForEach x:TypeArguments="..." Values="...">
    <ui:ForEach.Body><ActivityAction>...<Sequence DisplayName="Body">...
    </Sequence></ActivityAction></ui:ForEach.Body></ui:ForEach>`(知見5)。
    `item_var`は`DelegateInArgument`の`Name`。

    知見155追記: 基本WF版`System.Activities.Statements.ForEach<T>`
    (`ui:`プレフィックス無し、`WF_NS`)もパースして同じ`ForEachNode`へ
    変換する——UiPathプログラマがVB式ベースのループ(`Directory.
    GetFiles(...)`/`JArray.Parse(...)`/`.AsEnumerable()`等)を書く際に
    `ui:ForEach`ではなく基本WF版を直接使う実例を5件以上実機確認した
    (`plaah/web-application-with-rpa-dhl`・`R1zzabh/signalforge`・
    `rufoabrahamguyo/sow-calix`・`NihadVeliyev/Student-Placement-
    Eligibility-Automation-using-UiPath-and-Excel`・`EnnioArnold/
    Dispatcher-Framework`)。構造は`ui:ForEach`と全く同じ
    `ActivityAction`+`DelegateInArgument`だが、`Body`がContent
    Property(XAMLで省略可能な唯一のプロパティ)のため、`<ForEach.Body>`
    での明示ラップ(`R1zzabh/signalforge`)と、`<ForEach>`直下に
    `ActivityAction`を直接子として置く暗黙形(他4件)の両方が実在する
    ——`_parse_for_each`が両形式に対応する。なお`AI-Dep/
    AI-Antigravity`の実機XAML(`CurrentItem`を属性として直接持つ形、
    `ActivityAction`無し)も発見したが、これは`ForEach<T>`の実際の
    .NET API(`CurrentItem`プロパティ自体が存在しない)と矛盾するため
    非標準(AIが生成した合成コードの可能性が高い)と判断し、実装の
    根拠には採用しなかった——Microsoft公式サンプル(`dotnet/samples`)
    とTFS標準ビルドテンプレート(`microsoft/sql-server-samples`)で
    確認した本来の`ActivityAction`形のみを「確認済みの実機構造」として
    採用した。
    """

    item_var: str
    values: Expr
    body: list["Node"] = field(default_factory=list)
    type_arguments: str = "x:Object"


@dataclass
class CatchArm:
    """`TryCatch.Catches`配下の`<Catch x:TypeArguments="...">`1本
    (知見6・知見「Populated TryCatch.Catches」)。`var_name`は
    `DelegateInArgument`の`Name`(例外変数名)。"""

    exception_type: str
    var_name: str | None = None
    body: list["Node"] = field(default_factory=list)


@dataclass
class TryCatchNode:
    """`<TryCatch>`(知見6)。"""

    try_body: list["Node"] = field(default_factory=list)
    variables: list[VariableDecl] = field(default_factory=list)
    catches: list[CatchArm] = field(default_factory=list)
    finally_body: list["Node"] = field(default_factory=list)


@dataclass
class SwitchArm:
    """`<Switch>`配下の1アーム。`key=None`はdefaultアーム——`x:Key`付きの
    辞書エントリ(知見21)とは別物の`<Switch.Default>`プロパティ要素として
    直列化される(知見40、実機確認済み)。"""

    key: str | None
    body: list["Node"] = field(default_factory=list)


@dataclass
class SwitchNode:
    """`<Switch x:TypeArguments="..." Expression="...">`(知見9)。各アームは
    `<Assign x:Key="1">`のように、アクティビティ要素自身が`x:Key`属性を
    持つ形で直接の子になる(知見21)。
    """

    expression: Expr
    type_arguments: str
    arms: list[SwitchArm] = field(default_factory=list)


@dataclass
class WhileNode:
    """`<ui:InterruptibleWhile Condition="...">`(知見14、実体は
    `ui:InterruptibleWhile`で`While`という独立タグは存在しない)。"""

    condition: Expr
    body: list["Node"] = field(default_factory=list)


@dataclass
class DoWhileNode:
    """`<ui:InterruptibleDoWhile Condition="...">`。`While`と対になる
    実装だが知見では`Condition`属性の実例を未確認(本fixtureでは省略されて
    いた=未設定のDo Whileのまま)。"""

    condition: Expr
    body: list["Node"] = field(default_factory=list)


@dataclass
class BreakNode:
    """`<ui:Break />`(知見18、属性なしの自己終了タグ)。"""


@dataclass
class ParallelNode:
    """`<Parallel>`(知見19・20)。直接の子`Activity`要素それぞれが1つの
    ブランチ(複数ステップのブランチは`Sequence`でラップされる——`branches`の
    各要素はラップを解かない生の`Node`のままにして、呼び出し側が
    `SequenceNode`かどうかを見て判断する)。"""

    branches: list["Node"] = field(default_factory=list)


@dataclass
class ClickNode:
    """`<ui:Click>`(知見9)。`selector`は`ui:Click.Target`配下の`ui:Target`
    要素の`Selector`属性(素のXML文字列、意味論は知見37参照——本パーサーでは
    まだ解析しない)。

    `click_type`/`mouse_button`/`key_modifiers`は実機XAML
    (design/evidence/uipath_xaml_probe/Main.xaml、知見71)で確認した
    `ClickType`/`MouseButton`/`KeyModifiers`属性の生テキストをそのまま
    保持する(例: `"CLICK_SINGLE"`/`"BTN_LEFT"`/`"None"`)。これらの
    非nullable列挙型プロパティはStudioが常に具体的な値を直列化するため
    (`{x:Null}`にはならない)、コード生成側(`_generate_click`)が
    「実機確認済みの既定値そのまま」かどうかを判定できるようにするために
    保持する——未確認の値(ダブルクリック・右クリック・修飾キー併用等)は
    `# TODO`へ倒す(`uipath_codegen/__init__.py`参照、でっち上げたマッピングで
    クリック種別を誤らせるより安全側に倒す)。

    `cursor_position`は`ui:Click.CursorPosition`配下の`ui:CursorPosition`
    要素の`Position`属性(知見73、実機確認済みの値は`"Center"`のみ——
    pywinautoの`click_input()`既定(ターゲット要素の中心座標)と一致する
    ため現状は安全)。

    `cursor_offset_x`/`cursor_offset_y`は知見105で追加——`gh api
    search/code`でGitHub上の実機保存済みXAMLから、`Position="TopLeft"`+
    `OffsetX`/`OffsetY`(属性形・`<CursorPosition.OffsetX>`プロパティ要素
    形の両方が実在、後者は値が空なら未設定)という実例を確認した。
    `TopRight`/`BottomLeft`/`BottomRight`時のoffsetの符号規約(右端/下端
    からの向き)は実機未確認のため依然未対応——`TopLeft`(pywinautoの
    `click_input(coords=...)`が既定で使うのと同じ原点、知見105参照)の
    場合のみ`_generate_click`が実コード生成する。

    `delay_before`は知見106で追加——UiPath公式ドキュメント
    (docs.uipath.com/activities/other/latest/ui-automation/click)で
    「活動が何らかの操作を始める前の待機時間(ミリ秒、既定200ms)」と
    確認済み。未設定時は`{x:Null}`という文字列として直列化される(他の
    列挙型属性とは異なりnullable——`_attr_expr`経由で`Expr`として捕捉し、
    `{x:Null}`は正しく`None`になる)。`delay_ms`は同じ`DelayMS`属性だが
    公式ドキュメントに記載が無く意味論が未確認のため、捕捉はするが
    コード生成では確認済みの既定値(`None`)以外は`# TODO`へ倒す。"""

    selector: str | None = None
    display_name: str | None = None
    click_type: str | None = None
    mouse_button: str | None = None
    key_modifiers: str | None = None
    cursor_position: str | None = None
    cursor_offset_x: str | None = None
    cursor_offset_y: str | None = None
    delay_before: Expr = None
    delay_ms: Expr = None


@dataclass
class HoverNode:
    """`<ui:Hover>`(知見157、GitHub code searchで151件ヒット)。
    `ClickNode`(知見9)と`Target`/`CursorPosition`の構造が全く同じ
    (`sujan5757/RPAWorks`の実機XAMLで確認)——`ClickType`/`MouseButton`/
    `KeyModifiers`(クリック自体には存在する属性)が無い点のみ異なる。
    `cursor_position`/`cursor_offset_x`/`cursor_offset_y`は`ClickNode`
    と同じ意味論(知見73・105)で、`delay_before`/`delay_ms`も同じ
    (知見106)。実機で確認した`SendWindowMessages`/`SimulateHover`は
    全て`{x:Null}`(未設定)——両方とも`Click`の`SimulateClick`/
    `SendWindowMessages`と同じ理由(正確な実装APIが未文書化)で、
    非既定値が設定されている場合は`# TODO`へ倒す。

    pywinautoの`move_mouse_input()`ラッパー自体の既定値(`coords=(0, 0)`
    `absolute=True`)は要素の中心に移動する意味にならない(`(0, 0)`を
    画面の絶対座標として解釈してしまう)ため、代わりに`click_input()`
    自身の既定値(`coords=(None, None)`・`absolute=False`——`None`は
    要素の中心を相対座標で計算した後に画面座標へ変換する)を
    `button='move'`で呼び出す形で実装する——`ClickNode`の既定
    (`CursorPosition`省略時)が依拠しているのと同じ既定値経路を再利用
    することで、新たな前提を持ち込まない。"""

    selector: str | None = None
    display_name: str | None = None
    cursor_position: str | None = None
    cursor_offset_x: str | None = None
    cursor_offset_y: str | None = None
    delay_before: Expr = None
    delay_ms: Expr = None
    send_window_messages: Expr = None
    simulate_hover: Expr = None


@dataclass
class TypeIntoNode:
    """`<ui:TypeInto>`。`selector`は`ui:TypeInto.Target`配下の`ui:Target`
    要素の`Selector`属性(`ClickNode`と同じ構造)。

    `uipath-activities-survey`調査フォーク(design/uipath_feature_catalog.md
    Part B3)が「実務で最も出現頻度が高いカテゴリ」と評価したUI
    Automation Classic基本活動群の最初の拡張対象。`gh api search/code`で
    GitHub上の実機保存済みXAML(`UiPath/skills`公式リポジトリ含む、複数件)
    を確認した結果、以下の属性はいずれも`{x:Null}`として直列化される
    実例が確認できた(= nullable、`xaml_tree._attr_expr`経由で捕捉する
    必要がある。`ClickNode`の`click_type`等とは違い`_attr`では不十分):
    `ClickBeforeTyping`/`EmptyField`/`SimulateType`/`SendWindowMessages`/
    `DelayBefore`/`DelayMS`/`DelayBetweenKeys`/`AlterIfDisabled`/
    `ContinueOnError`/`ActivateBefore`(または`Activate`、下記参照)。

    **`Activate`/`ActivateBefore`の表記揺れ**: UiPath公式の`UiPath/skills`
    リポジトリのテスト用フィクスチャ(2026年、現行の`Classic`パッケージ)は
    `ActivateBefore`属性を使うが、複数の古い(2017〜2021年頃の)サードパーティ
    リポジトリは`Activate`属性を使う——おそらくパッケージバージョン間での
    リネーム。本パーサーは`activate_before`フィールドに両方を同じ意味として
    格納する(どちらの属性名でXAMLに現れても後続のコード生成は区別しない)。

    `click_before_typing`の実機確認済みの値は`{x:Null}`/`"False"`/`"True"`/
    `"NONE"`の4種(NONEがBoolean列挙の`False`相当なのか別の3値enumなのかは
    未確定——いずれも「クリックしない」として安全側に扱う)。

    `text`はタイプする文字列(`InArgument<String>`相当)。コード生成側
    (`_generate_type_into`)がpywinautoの`type_keys()`へ変換する際、
    `~^%+(){}`はpywinauto独自の特殊キー構文として解釈されてしまうため
    (`dump_daemon/pad_ui_helpers.py`の`set_vb_expression_field`docstringが
    PAD調査時に発見した同じ罠)、生成コード側でエスケープヘルパーを
    必ず経由させる。"""

    selector: str | None = None
    display_name: str | None = None
    text: Expr = None
    empty_field: Expr = None
    click_before_typing: Expr = None
    simulate_type: Expr = None
    send_window_messages: Expr = None
    delay_before: Expr = None
    delay_ms: Expr = None
    delay_between_keys: Expr = None
    activate_before: Expr = None
    alter_if_disabled: Expr = None
    continue_on_error: Expr = None


@dataclass
class SendHotkeyNode:
    """`<ui:SendHotkey>`(知見152、GitHub code searchで1936件ヒット——
    `Click`/`TypeInto`と同じ`UiPath.Core.Activities`の基本UI Automation
    活動)。`selector`は`ui:SendHotkey.Target`配下の`ui:Target`要素の
    `Selector`属性(`ClickNode`/`TypeIntoNode`と同じ構造)——ただし実機で
    `Target`要素自体が省略された自己終了タグの実例(`AI-Dep/
    AI-Antigravity`の`<ui:SendHotkey Key="esc" DisplayName="..." />`)も
    確認済み(現在フォーカス中のウィンドウへグローバルに送信する意味論
    と推定されるが、本パーサーでは未対応——コード生成側で`# TODO`へ倒す)。

    `Key`/`KeyModifiers`/`SpecialKey`の3属性の関係は実機調査で意外な
    発見があった: `SpecialKey`は`"True"`/`"False"`/`{x:Null}`/属性自体が
    省略、のいずれも実例があり(`cameronmcnz/uipath-tutorials`の
    `ExtractPDFwithAnchors/Main.xaml`で`SpecialKey="{x:Null}"`かつ
    `Key="5"`、`KeyModifiers="Ctrl, Shift"`という実例を確認)、`Key`が
    特殊キー名かどうかの判定に`SpecialKey`属性の値が実際に信頼できる
    形で使えるとは言い切れない——`Key`の文字列自体(1文字なら生の
    キー文字、既知の特殊キー名(`"enter"`/`"tab"`/`"esc"`/`"pgup"`/
    `"f1"`〜`"f24"`/`"num0"`〜`"num9"`等、全て実機確認済み)に一致すれば
    特殊キー)から判定する方が安全——`render.py`/`uipath_codegen`側で
    `SpecialKey`属性自体は一切参照しない設計とした。`KeyModifiers`は
    `.NET`の`[Flags]`列挙型のToString()直列化形式(`", "`区切り、例:
    `"Ctrl, Shift"`)で複数同時指定が実機で確認済み——`"Ctrl"`/`"Alt"`/
    `"Shift"`/`"None"`は確認済みだが`"Win"`は未確認のため`# TODO`へ倒す。"""

    selector: str | None = None
    display_name: str | None = None
    key: Expr = None
    key_modifiers: Expr = None
    click_before_typing: Expr = None
    empty_field: Expr = None
    send_window_messages: Expr = None
    delay_before: Expr = None
    delay_between_keys: Expr = None
    delay_ms: Expr = None
    activate: Expr = None


@dataclass
class GetTextNode:
    """`<ui:GetText>`(知見111)。`selector`は`ui:GetText.Target`配下の
    `ui:Target`要素の`Selector`属性(`ClickNode`/`TypeIntoNode`と同じ構造)。

    `UiPath/skills`公式リポジトリの複数の実機保存済みXAMLで確認した属性は
    `ContinueOnError`/`DelayBefore`/`DelayMS`(いずれも`{x:Null}`の実例が
    あり nullable)のみ——`TypeInto`のような`ClickBeforeTyping`/
    `EmptyField`等の追加オプションは無い、単純な構造。`text`は出力先
    (`OutArgument`相当、実機では`Text="[varName]"`という`VbExpr`形で
    確認済み)。

    公式ドキュメントは裏のCLR型を`UiPath.Core.Activities.GetValue`
    (プロパティ名は`Value`)と記載しているが、実機XAML上の属性名は常に
    `Text`——`HttpClient`(知見29、DisplayNameとCLR型名の不一致)と同種の
    「ドキュメントの用語と実際の直列化属性名が食い違う」ケース。本パーサー・
    コード生成は実機確認済みの`Text`属性名を信頼する。"""

    selector: str | None = None
    display_name: str | None = None
    text: Expr = None
    delay_before: Expr = None
    delay_ms: Expr = None
    continue_on_error: Expr = None


@dataclass
class SelectItemNode:
    """`<ui:SelectItem>`(知見112)。`selector`は`ui:SelectItem.Target`配下の
    `ui:Target`要素の`Selector`属性(`ClickNode`等と同じ構造)。`item`は
    選択する値(`Item`属性、実機ではリテラル文字列・`VbExpr`の両方の実例が
    ある)。

    `UiPath/skills`公式リポジトリ含む複数件の実機保存済みXAMLで確認した
    属性: `ContinueOnError`/`DelayAfter`/`DelayBefore`はいずれも`{x:Null}`
    の実例がありnullable。`Items`(ドロップダウン等の選択可能な項目一覧、
    `<ui:SelectItem.Items><scg:List>...`の子要素形)はStudioが記録時に
    キャプチャした設計時スナップショットであり実行時には使われないため
    (`Item`で指定した値を実際に選べるかどうかは実行時のUI状態で決まる)、
    本パーサーは捕捉しない。

    `alter_if_disabled`は`Click`/`TypeInto`とは違い公式ドキュメントで
    確認済み——本活動は入力方式が`SimulateClick`固定(ユーザーが変更
    不可)で、既定で無効化された要素も操作対象になる("disabled elements
    are altered by default")と明記されている。実機XAMLでも
    `AlterIfDisabled="True"`という明示的な実例を確認した——これは
    `Click`/`TypeInto`の「未文書化のため常に見送り」とは異なり、確認済みの
    既定として扱える。"""

    selector: str | None = None
    display_name: str | None = None
    item: Expr = None
    delay_before: Expr = None
    delay_after: Expr = None
    continue_on_error: Expr = None
    alter_if_disabled: Expr = None


@dataclass
class UiElementExistsNode:
    """`<ui:UiElementExists>`(知見113、DisplayNameは「Element Exists」)。
    `selector`は`ui:UiElementExists.Target`配下の`ui:Target`要素の
    `Selector`属性(`ClickNode`等と同じ構造)。`exists`は出力先
    (`Exists`属性、Boolean変数のみ受け付けると公式ドキュメントで確認済み)。

    `gh api search/code`で確認した3件の独立した実機保存済みXAML
    (いずれも真のタグ名が`ui:ElementExists`ではなく`ui:UiElementExists`
    であることを確認——公式ドキュメントの裏のCLR型名
    `UiPath.Core.Activities.UiElementExists`とも一致する)はいずれも
    `ContinueOnError`/`DelayBefore`/`DelayMS`に相当する属性が一切現れず
    (`{x:Null}`すら無く完全に省略)、公式ドキュメントのプロパティ一覧にも
    これらは載っていない——`Click`/`TypeInto`/`GetText`/`SelectItem`の
    「Common」カテゴリの属性とは違い、この活動には本当に存在しないと
    判断し、捕捉対象に含めない(無い属性を推測で持たせるとでっち上げに
    なる)。

    `ui:ElementExists`(`UiElementExists`抜き)という別名の実例も2件
    見つかったが、1件は`TODO_SELECTOR_...`という明らかなプレースホルダ値を
    含む非Studio生成(サードパーティ変換ツールの合成テストデータ)、もう
    1件はStudioの`.Target`ラッパーを持たない旧式の直列化(信頼度が低い
    学生課題リポジトリ)で、いずれも実機Studio保存の確証が弱いため採用
    しなかった。"""

    selector: str | None = None
    display_name: str | None = None
    exists: Expr = None


@dataclass
class DatabaseConnectNode:
    """`<ui:DatabaseConnect>`(知見114、`UiPath.Database.Activities`、Tier A
    からTier B「Database活動」への着手第1件)。`marcelocruzrpa/
    uipath-ai-skills`リポジトリの`studio-ground-truth/UiPath.Database.
    Activities/2.0/`(実機Studioから自動収集されたと明記された参照用XAML
    集)で属性の完全な語彙を確認し、`allenlooplee/RPABook`の実例で実際に
    値が入った形を確認した——`ConnectionString="Data Source=db.sqlite;
    Version=3;"`・`ProviderName="System.Data.SQLite"`。

    `provider_name`/`connection_string`は.NET ADO.NETの語彙(プロバイダ
    invariant name・プロバイダ固有の接続文字列書式)で、Pythonの標準
    ライブラリとは1対1対応しない——プロバイダごとに別のPythonライブラリ
    (SQLiteなら標準の`sqlite3`、SQL Serverなら`pyodbc`等)が必要になる。
    本バージョンでは実機確認できた`"System.Data.SQLite"`のみ対応し、
    それ以外のプロバイダは`# TODO`へ倒す(でっち上げ回避)。
    `secure_connection_string`(`SecureString`型、公式ドキュメントで存在は
    確認したが実機での使用例は未確認)も同様に見送る。"""

    connection_string: Expr = None
    secure_connection_string: Expr = None
    provider_name: Expr = None
    database_connection: Expr = None
    display_name: str | None = None


@dataclass
class DatabaseDisconnectNode:
    """`<ui:DatabaseDisconnect DatabaseConnection="...">`(知見114)。
    `database_connection`は閉じる対象の接続変数(`DatabaseConnectNode.
    database_connection`と同じ変数名を指す、実機では`[VarName]`形の
    `VbExpr`)。"""

    database_connection: Expr = None
    display_name: str | None = None


@dataclass
class ExecuteQueryNode:
    """`<ui:ExecuteQuery>`(知見114)。`sql`/`existing_db_connection`/
    `data_table`(出力、`DataTable`属性)が本体。`parameters`は
    `ui:ExecuteQuery.Parameters`配下の`x:Key`付き辞書(`_xkey_dict_entries`
    で共通パース)——実機確認できた実例は空のみで、populated時の
    プレースホルダ書式(`:name`/`@name`/`?`のどれがSQL側で使われるか)が
    未確認のため、populated時はコード生成を見送る(`parameters`自体は
    保持するが、空でなければ`# TODO`に倒す判断はcodegen側で行う)。

    `command_type`の実機確認済みの値は`"Text"`のみ(`CommandType`属性、
    ADO.NETの`System.Data.CommandType`列挙——`"StoredProcedure"`も列挙値
    として存在するはずだが実機未確認)。"""

    sql: Expr = None
    parameters: dict[str, Expr] = field(default_factory=dict)
    existing_db_connection: Expr = None
    data_table: Expr = None
    command_type: str | None = None
    continue_on_error: Expr = None
    timeout_ms: Expr = None
    display_name: str | None = None


@dataclass
class ExecuteNonQueryNode:
    """`<ui:ExecuteNonQuery>`(知見114)。`ExecuteQueryNode`と同じ構造だが
    出力が`DataTable`ではなく`AffectedRecords`(影響を受けた行数、整数)。"""

    sql: Expr = None
    parameters: dict[str, Expr] = field(default_factory=dict)
    existing_db_connection: Expr = None
    affected_records: Expr = None
    command_type: str | None = None
    continue_on_error: Expr = None
    timeout_ms: Expr = None
    display_name: str | None = None


@dataclass
class InvokeWorkflowFileNode:
    """`<ui:InvokeWorkflowFile WorkflowFileName="...">`(知見12)。
    `arguments`は`ui:InvokeWorkflowFile.Arguments`配下の`x:Key`付き
    `InArgument`/`OutArgument`を`{引数名: 式}`に展開したもの。

    `continue_on_error`は実機XAML(`Main.xaml`、知見72)で確認した
    `ContinueOnError`属性(`{x:Null}`=未設定が確認済みの唯一の値)を
    そのまま保持する——`None`(未設定)以外の値(`"True"`等)を検出した
    場合、`_generate_invoke_workflow_file`は現在の「例外をそのまま
    伝播させる」コード生成がVBの「エラーを無視して継続する」挙動と
    食い違うことを認識し、でっち上げたtry/except変換はせず`# TODO`へ
    倒す(実機で`ContinueOnError="True"`の実例が無いため、どう継続する
    べきかの正確な挙動を未確認のまま)。"""

    workflow_file: str
    arguments: dict[str, Expr] = field(default_factory=dict)
    continue_on_error: Expr = None


@dataclass
class CopyFileNode:
    """`<ui:CopyFile>`(知見117、`UiPath.System.Activities`。実機XAML
    ([allenlooplee/RPABook]等複数件)+`marcelocruzrpa/uipath-ai-skills`の
    ground-truthで属性を確認——`Path`/`Destination`は`InArgument<String>`
    (リテラル・VbExprの両方の実例あり)、`Overwrite`は`"True"`/`"False"`
    両方の実例を確認済み。`DestinationResource`/`PathResource`(ground-truth
    のみ、Integration Service連携用と推定)は未確認のため見送る。"""

    path: Expr = None
    destination: Expr = None
    overwrite: str | None = None
    destination_resource: Expr = None
    path_resource: Expr = None
    continue_on_error: Expr = None
    display_name: str | None = None


@dataclass
class BuildDataTableNode:
    """`<ui:BuildDataTable>`(知見117、`UiPath.System.Activities`)。
    `TableInfo`は列定義を持つ.NET `DataSet` XMLスキーマ(`xs:schema`)が
    丸ごと埋め込まれた文字列属性——`marcelocruzrpa/uipath-ai-skills`の
    ground-truthで実例を確認した。本パーサーは列名のみを抜き出す
    (`xs:element`の`name`属性、`TableName`要素直下の最初の階層のみ)。
    列の型情報は捕捉しない(Pythonの`list[dict]`表現では実行時の値の型が
    そのまま使われるため、静的な型情報は不要——`SelectItem.Items`
    (知見112)と同じ「design-timeスナップショットは実行時に不要」という
    判断)。"""

    data_table: Expr = None
    columns: list[str] = field(default_factory=list)
    display_name: str | None = None


@dataclass
class AppendLineNode:
    """`<ui:AppendLine FileName="..." Text="..." />`(知見15)。

    `encoding`/`use_default_encoding`は知見108で追加——UiPath公式
    ドキュメント(docs.uipath.com/activities/other/latest/workflow/
    append-line)で確認済み: `UseDefaultEncoding=True`(既定)なら
    OSの既定エンコーディング、`False`で`Encoding`未指定なら
    (BOM検出に失敗した場合)UTF-8が既定として選ばれる。実機フィクスチャ
    (`Main.xaml`)で`UseDefaultEncoding="False"`(`Encoding`未指定)の
    実例を確認済み。"""

    file_name: Expr
    text: Expr
    encoding: str | None = None
    use_default_encoding: str | None = None


@dataclass
class ReadTextFileNode:
    """`<ui:ReadTextFile FileName="..." Content="..." />`(知見16、`Content`は
    `OutArgument`相当で`[VarName]`角括弧形)。

    `encoding`は知見108で追加——UiPath公式ドキュメントで`Encoding`未指定
    時はBOM検出→(検出失敗時)システムのANSIコードページが使われると確認
    済み(`Append Line`の`UseDefaultEncoding=False`時の既定——UTF-8とは
    異なる)。`ReadTextFile`には`UseDefaultEncoding`相当のプロパティは
    無い(公式ドキュメントに記載無し)。"""

    file_name: Expr
    content: Expr
    encoding: str | None = None


@dataclass
class InvokeCodeNode:
    """`<ui:InvokeCode Code="...">`(知見17、インラインVB.NETコードは
    プレーンな文字列属性)。`code`はVB.NETコードのプレーン文字列で、
    式パーサー(`VbExpr`)の対象外——別のコード生成トラック(ロードマップ
    Phase 8のCoded Workflowsに近いが、こちらはワークフロー内埋め込みの
    短いコード片)。"""

    code: str
    arguments: dict[str, Expr] = field(default_factory=dict)


@dataclass
class SetToClipboardNode:
    """`<ui:SetToClipboard Text="..." />`。"""

    text: Expr


@dataclass
class CommentNode:
    """`<ui:Comment Text="..." />`(知見119、`PacktPublishing/
    Robotic-Process-Automation-Projects`の実機XAMLで発見)。アクティビティ
    木に挿入される純粋な注釈——`Text`は常に生のリテラル文字列(VbExprでは
    無い、実機確認済み)で実行時の挙動は一切無い。Pythonの`#`コメント行
    へ変換する。"""

    text: str


@dataclass
class DelayNode:
    """`<ui:Delay Duration="..." />`(知見151、UiPath独自の待機活動
    ——GitHub code search(`"ui:Delay Duration=" extension:xaml`)で
    10000件超ヒットする最頻出活動の1つにも関わらず、これまで完全に
    未実装だった)。`Duration`属性は実機確認した全件(`AI-Dep/
    AI-Antigravity`・`UiPath/skills`の複数XAML)で`[...]`角括弧の無い
    生の.NET TimeSpan書式リテラル(`"00:00:01"`/`"00:00:00.500"`等の
    `"HH:MM:SS[.fffffff]"`)だった——`Click`の`DelayBefore`(知見106、
    ミリ秒単位の数値)とは異なる書式。`Duration`は`Expr`として保持し、
    `Literal`(生のTimeSpanリテラル)の場合のみ秒数に変換して
    `time.sleep(秒数)`へ変換する——`VbExpr`(角括弧付きの動的式)の
    場合は、TimeSpanを返す任意の式が秒数へどう変換されるべきか未確認
    のため`# TODO`へ倒す(でっち上げるよりは安全)。"""

    duration: Expr = None
    display_name: str | None = None


@dataclass
class WriteLineNode:
    """`<WriteLine Text="..." />`(知見147、`System.Activities.
    Statements.WriteLine`——UiPath独自活動ではなく.NET Workflow
    Foundation本体の標準活動、`WF_NS`名前空間。`RealBenTen10/
    Handle-Order`等、この実機検証を通じて非常に高頻度で「unknown
    activity」として素通りしていたことが判明——基本的な活動にも関わらず
    長らく未実装だった)。`Text`は動的な式が確認済み(VBの`&`連結式含む)
    のため`Expr`として扱う。`Console.WriteLine`相当で、Pythonの
    `print()`と直接対応する——`MessageBox`(知見79)と違い、対話的な
    ブロッキングやユーザーの選択を伴わない単純なテキスト出力のため
    「でっち上げ」の懸念が無い。"""

    text: Expr
    display_name: str | None = None


@dataclass
class ThrowNode:
    """`<Throw Exception="..." />`(知見148、`System.Activities.
    Statements.Throw`——`WriteLine`(知見147)と同じ.NET Workflow
    Foundation本体の標準活動、UiPath独自ではない)。`Exception`属性は
    実機で`[New Exception("message")]`という、知見148で新規対応した
    `New ClassName(arg)`構文が使われていた(`Manyakarthik/
    210701152-CS19P21-ARPA`)。`Exception`は`Expr`として保持し、確認済み
    の安全なクラス名(`render.py`の`_NEW_OBJECT_CLASSES`)の場合のみ
    Pythonの`raise`文へ変換する——未確認のクラス名の場合は`# TODO`へ
    倒す(`raise`しないことで本来即座に停止するはずの制御フローが継続
    してしまう既知の限界だが、架空の例外クラスをでっち上げるよりは
    安全)。"""

    exception: Expr = None
    display_name: str | None = None


@dataclass
class TerminateWorkflowNode:
    """`<TerminateWorkflow Reason="..." Exception="..." />`(知見150、
    `System.Activities.Statements.TerminateWorkflow`——`Throw`(知見148)
    ・`Rethrow`(知見149)と同じ.NET Workflow Foundation本体の標準活動)。
    `TryCatch`で捕捉できない即座のワークフロー全体停止という意味論を持ち、
    Pythonの`SystemExit`(デフォルトでは`except Exception:`に捕捉されず
    伝播する)が最も近い対応物。実機で確認した3件(`Siva-PythonPirates/
    CS19P21-ARPA`・`jyjang1222/learning-uipath`・`andumorie/
    uipath-face-recognition-framework`)は全て`Reason`属性を持っていた
    (`Exception`属性は無いか、持っていても常に`Reason`も併用されていた)。
    `Reason`のみの場合は`raise SystemExit(reason)`へ変換するが、
    `Exception`属性も同時に指定されている場合は、両者がどう合成される
    べきか(メッセージに例外情報をどう埋め込むか)が実機未確認のため
    `# TODO`へ倒す(でっち上げるよりは安全)。"""

    reason: Expr = None
    exception: Expr = None
    display_name: str | None = None


@dataclass
class RethrowNode:
    """`<Rethrow />`(知見149、`System.Activities.Statements.Rethrow`
    ——`Throw`(知見148)の対になる、.NET Workflow Foundation本体の標準
    活動。属性を一切持たないリーフ活動で、`Catch`ブロック内で現在捕捉中
    の例外を再発生させる)。Pythonの`except`ブロック内の引数無し`raise`
    文(現在処理中の例外を再発生させる)が全く同じ意味論で直接対応する
    ——`TryCatch`(知見11)の`Catch`ブロックで非常に高頻度に使われる
    定石パターンにも関わらず、`Throw`と同時に見落とされていた。"""

    display_name: str | None = None


@dataclass
class LogMessageNode:
    """`<ui:LogMessage Level="..." Message="..." />`(知見119、
    `UiPath.System.Activities`、`PacktPublishing/
    Robotic-Process-Automation-Projects`の実機XAMLで発見)。実機確認済み
    の`level`は`"Info"`/`"Error"`のみ——他の値(`"Warn"`/`"Trace"`/
    `"Fatal"`はUiPathのLogLevel列挙として存在が推定されるが実機未確認)は
    コード生成を見送る。

    知見124追記: `Level`は`[UiPath.Core.Activities.LogLevel.Info]`という
    `[...]`角括弧VB式で列挙の完全修飾名を参照する形でも直列化される
    (実機確認済み)。`xaml_tree._parse_log_level`がこの形から確認済みの
    メンバー名(`"Info"`/`"Error"`)だけを取り出し、この`level`フィールド
    自体は常に素の文字列(`"Info"`/`"Error"`、または未確認の生テキスト)
    のまま保持する——`Expr`化はしない。"""

    message: Expr
    level: str | None = None
    display_name: str | None = None


@dataclass
class ExcelWriteCellNode:
    """`<ui:ExcelWriteCell Cell="..." SheetName="..." Text="..." />`
    (知見22)。

    知見119追記: `cell`は当初`str`型だったが、`PacktPublishing/
    Robotic-Process-Automation-Projects`の実機XAMLで`Cell="[&quot;B&quot;
    +intCounter.ToString]"`(ループ内での連番セル指定、現場では非常に
    一般的な実務パターン)という動的な実例を発見したため`Expr`へ昇格
    した。`sheet_name`は全てのExcel活動(`ExcelReadRange`/
    `ExcelWriteRange`/`ExcelAppendRange`含む)で実機確認済みの実例が常に
    リテラル文字列("Sheet1"等)だったため`str`のまま残す(他の兄弟活動と
    一貫性を保つ)。

    知見135追記: `display_name`は他のExcel活動(`ExcelReadCellNode`等)
    と違い当初欠けていた——実機では`DisplayName`属性が常に存在する
    (Studioが活動を配置する際に既定で付与するため)ため追加した。知見84
    で確立した`_with_scope_child_display_name`(スコープ子の生成行を
    `# {display_name}`コメントで包む)をそのまま適用する。"""

    cell: Expr
    sheet_name: str
    text: Expr
    display_name: str | None = None


@dataclass
class ExcelReadCellNode:
    """`<ui:ExcelReadCell>`(知見119、`ExcelWriteCellNode`と対になる読み取り
    側、`PacktPublishing/Robotic-Process-Automation-Projects`の実機XAMLで
    発見)。`cell`は`ExcelWriteCellNode`と同じ`Expr`(動的なセル指定の実例
    あり)。`result`は`ui:ExcelReadCell.Result`配下の`OutArgument`要素
    (`_in_argument_property_expr`、知見115で確立した共通パーサーで取得
    ——`InArgument`/`OutArgument`のどちらのタグ名でも同じロジックで
    動作する)。"""

    cell: Expr
    sheet_name: str
    result: Expr
    display_name: str | None = None


@dataclass
class AttachWindowNode:
    """`<ui:AttachWindow Selector="...">...</ui:AttachWindow>`(知見153、
    `UiPath.Core.Activities`。GitHub code searchで1100件ヒット)。
    `ExcelApplicationScopeNode`/`WordApplicationScopeNode`とは異なり
    `ActivityAction`+`DelegateInArgument`のラッパーを持たない——実機
    (`AI-Dep/AI-Antigravity`の`FA_CS_Asset_Entry.xaml`)で確認した構造は
    `<ui:AttachWindow.Body><Sequence>...</Sequence></ui:AttachWindow.Body>`
    という単純な形で、`ForEach.Body`/`While.Body`と同じ「常に`Sequence`
    でラップされる」パターン(`_unwrap_body_sequence`、知見22)がそのまま
    使える。

    `AttachWindow`自身はスコープ変数を生成せず、子活動(実機確認済みの
    `ClickNode`/`TypeIntoNode`/`SendHotkeyNode`は全て`selector`を自己
    完結的に(絶対パスで)保持する設計、知見9・110・152)が`AttachWindow`
    が解決したウィンドウハンドルへの相対参照に依存する構造には**なって
    いない**——よって`AttachWindow`は「`Selector`を注釈コメントとして
    出力し子をそのまま再帰実行する透過的なラッパー」として安全に実装
    できる(`ExcelApplicationScope`のような`scope_var`束縛は不要)。

    知見158追記: `ui:WindowScope`(GitHub code searchで1688件ヒット
    ——`AttachWindow`の1100件より多い!)が、`DisplayName`が常に
    `"Attach Window '...'"`になる同義の別活動(おそらく異なるUI
    Automationパッケージバージョンでの名称、`allenlooplee/RPABook`・
    `HarshadRanganathan/uipath-learning`等9件以上の実機XAMLで確認)だと
    判明した。意味論は`AttachWindow`と同じ(既存ウィンドウに接続して
    `Body`を実行、プロセス起動は行わない)だが、構造は`AttachWindow`
    とは違い`OpenApplication`(知見154)と同じ`ActivityAction`+
    `DelegateInArgument`(`Name`は`"ContextTarget"`)のラッパーを持つ。
    `ApplicationWindow`/`SearchScope`/`TimeoutMS`/`Window`という4つの
    追加属性を持つが、実機確認した9件以上全てで`{x:Null}`(未設定)
    だった——同じ`AttachWindowNode`を再利用し、これらが設定されている
    場合は(`OpenApplication`の`ApplicationWindow`等と同じ理由で)
    `# TODO`へ倒す。"""

    selector: str | None = None
    body: list["Node"] = field(default_factory=list)
    display_name: str | None = None
    application_window: Expr = None
    search_scope: Expr = None
    timeout_ms: Expr = None
    window: Expr = None


@dataclass
class OpenApplicationNode:
    """`<ui:OpenApplication FileName="..." Selector="...">...
    </ui:OpenApplication>`(知見154、`UiPath.Core.Activities`。GitHub
    code searchで複数実例ヒット)。`AttachWindowNode`(知見153)とは違い
    `ActivityAction`+`DelegateInArgument`のラッパーを持つ(実機
    `PacktPublishing/Robotic-Process-Automation-RPA-for-Developers`の
    `KeyboardActions.xaml`で確認: `x:TypeArguments="x:Object"`・
    `DelegateInArgument`の`Name`は`"ContextTarget"`固定)——`ExcelApplication
    Scope`(知見22)と同じ構造。ただし`AttachWindow`と同じ理由(子活動が
    `selector`を自己完結的に保持する設計)で`ContextTarget`は本実装では
    束縛しない(子が参照している実例を確認していない)。

    `FileName`は実機で生リテラル(`"C:\\Windows\\System32\\notepad.exe"`)
    と動的VB式(`"[in_Config(\"UiDemoPath\").ToString]"`、
    `piyushagarwal08/JU-Notes`)の両方を確認済み。`Arguments`
    (`"[in_TestLogFile]"`、`allenlooplee/RPABook`)・`ApplicationWindow`
    (開いたウィンドウ参照を受け取る出力バインディング、`"[OBSWindow]"`、
    `JoeIaquinto/UiPath-VidCreator`)・`WorkingDirectory`・`TimeoutMS`・
    `ContinueOnError`も実機で非`{x:Null}`の実例を確認済みだが、いずれも
    (Windowsコマンドライン引数の分割規則/UiElement出力変数の表現/
    「ウィンドウが現れるまで待つ」ポーリング挙動)の正確な意味論が
    未確認のため、本実装では`FileName`(+`Selector`の注釈コメント)
    のみサポートし、それ以外が設定されている場合は`# TODO`へ倒す
    (でっち上げるよりは安全)。"""

    file_name: Expr = None
    selector: str | None = None
    arguments: Expr = None
    working_directory: Expr = None
    application_window: Expr = None
    timeout_ms: Expr = None
    continue_on_error: Expr = None
    body: list["Node"] = field(default_factory=list)
    display_name: str | None = None


@dataclass
class ExcelApplicationScopeNode:
    """`<ui:ExcelApplicationScope WorkbookPath="...">...</ui:ExcelApplicationScope>`
    (知見22、`ActivityAction`+`DelegateInArgument`で`ForEach`と同じ構造)。"""

    workbook_path: str
    scope_var: str = "ExcelWorkbookScope"
    body: list["Node"] = field(default_factory=list)


@dataclass
class WordApplicationScopeNode:
    """`<ui:WordApplicationScope FileName="...">...</ui:WordApplicationScope>`
    (知見121、`UiPath.Word.Activities`。`ExcelApplicationScopeNode`
    (知見22)と同じ`ActivityAction`+`DelegateInArgument`構造。`UiPath/
    skills`公式リポジトリの複数の実機XAMLで発見した。`Visible`(実機確認済み
    の値は常に`"False"`)は、`ExcelApplicationScope`と同じユーザー決定
    (2026-11-05、`openpyxl`ファイルベース——ライブCOM自動化ではない)に
    合わせて`python-docx`(ファイルベース、Wordプロセス不要)を選んだため
    無視する——ライブWordアプリケーションを実際に表示/非表示にする挙動は
    再現しない(既知の限界、`ExcelApplicationScope`のライブマクロ実行
    未対応と同種)。"""

    file_name: str
    scope_var: str = "WordDocumentScope"
    body: list["Node"] = field(default_factory=list)


@dataclass
class WordReplaceTextNode:
    """`<ui:ReplaceTextInDocument>`/`<ui:WordReplaceText>`(知見121、
    `WordApplicationScope`配下の子活動)。実機で2つの異なるタグ名を確認
    した——DisplayName「Replace Text in Document」(裏のCLR型名
    `ui:ReplaceTextInDocument`)と「Replace Text」(`ui:WordReplaceText`)、
    おそらくパッケージバージョン間のリネーム(`SendMail`の`Account`/
    `DisplayName`の表記揺れと同種)。意味論は完全に同じ(`Search`を
    `Replace`へ置換)と判断し、両方のタグ名を同じノード型へディスパッチ
    する。`Search`は実機で`VbExpr`(`[変数名]`)とリテラル文字列
    (`"{{Candidate}}"`、Wordドキュメント内の生のプレースホルダ文字列、
    VB式ではない)の両方の実例を確認済み。"""

    search: Expr = None
    replace: Expr = None
    display_name: str | None = None


@dataclass
class ExcelReadRangeNode:
    """`<ui:ExcelReadRange>`(知見115、`ExcelApplicationScope`配下の子活動、
    `ExcelWriteCellNode`と同じ「スコープと連動する」活動)。`range`は
    `ui:ExcelReadRange.Range`配下の`InArgument`要素(ネストした`<Literal
    Value="">`要素形——実機確認済みの値は空文字列のみ、「シート全体の
    使用範囲」を意味する)。`sheet_name`は`ExcelWriteCellNode`と同じ
    `str`型(VbExprは未対応、既存の制約を継承)。`add_headers`は実機で
    `"True"`/`"False"`の両方を確認済み(harvested空テンプレートの既定は
    `"True"`)。"""

    sheet_name: str = ""
    range: Expr = None
    add_headers: str | None = None
    data_table: Expr = None
    display_name: str | None = None


@dataclass
class ExcelWriteRangeNode:
    """`<ui:ExcelWriteRange>`(知見115、`ExcelReadRangeNode`と対になる
    書き込み側)。`starting_cell`は属性直書き(`StartingCell="A1"`、
    `Range`のようなネスト構造ではない)。`data_table`は書き込む内容
    (入力、実機では`[dataTableVar]`形のVbExpr)。`add_headers`の
    harvested空テンプレートの既定は`"False"`(`ExcelReadRange`とは
    非対称な既定値)。"""

    sheet_name: str = ""
    starting_cell: str | None = None
    add_headers: str | None = None
    data_table: Expr = None
    display_name: str | None = None


@dataclass
class ExcelAppendRangeNode:
    """`<ui:ExcelAppendRange>`(知見117)。`ExcelWriteRangeNode`とは違い
    `AddHeaders`/`StartingCell`は無い(確認済み、常にシート末尾への
    追記のみ)——これは`ExcelWriteRangeNode`の修正(知見115追記、`append()`
    ベースの実装から直接セル指定へ変更)で外した「常に末尾追記する」挙動
    そのものに正確に対応する、別の活動。"""

    sheet_name: str = ""
    data_table: Expr = None
    display_name: str | None = None
    display_name: str | None = None


@dataclass
class SendOutlookMailNode:
    """`<ui:SendOutlookMail To="..." Subject="..." Body="..." />`(知見24)。

    `cc`/`bcc`/`importance`/`sensitivity`/`is_body_html`/`is_draft`/
    `has_populated_files`は知見98でコード生成対象に追加した属性(実機
    確認済みの値は`Cc`/`Bcc`ともに`{x:Null}`、`Importance`/`Sensitivity`
    ともに`"Normal"`、`IsBodyHtml`/`IsDraft`ともに`"False"`、`Files`は
    空の`scg:List`)。これら以外の値は実機未確認のためコード生成しない
    (知見96のHttpClientと同じ「確認済みの既定値のみ対応」方針)。"""

    to: Expr
    subject: Expr
    body: Expr
    cc: Expr = None
    bcc: Expr = None
    importance: str | None = None
    sensitivity: str | None = None
    is_body_html: str | None = None
    is_draft: str | None = None
    has_populated_files: bool = False
    extra_attrs: dict[str, str] = field(default_factory=dict)


@dataclass
class GetOutlookMailMessagesNode:
    """`<ui:GetOutlookMailMessages>`(知見120、`SendOutlookMailNode`
    (知見24・98・102)と対になる受信側、`UiPath.Mail.Activities`。
    `cameronmcnz/uipath-tutorials`の複数の実機XAMLで属性を確認した。

    `filter`の実機確認済みの値はOutlookのDASL/Jetフィルタ構文そのもの
    (`"[importance]='normal'"`)——UiPathが変換を一切せずOutlookの
    `Items.Restrict()`へそのまま渡していると見受けられる生の文字列
    (VB式の`[...]`角括弧記法ではない、`_parse_expr`が`]`で終わらない
    ため自然に`Literal`として捕捉される)。`account`/`get_attachments`/
    `mark_as_read`/`only_unread_messages`/`mail_folder`は確認済みの
    既定値構成(いずれも`"False"`/`"Inbox"`/未設定)のみ対応し、それ以外は
    `# TODO`へ倒す——`SendOutlookMail`と同じ「確認済みの既定値のみ対応」
    方針。"""

    messages: Expr = None
    account: Expr = None
    filter: Expr = None
    mail_folder: str | None = None
    get_attachments: str | None = None
    mark_as_read: str | None = None
    only_unread_messages: str | None = None
    top: Expr = None
    timeout_ms: Expr = None
    display_name: str | None = None


@dataclass
class SendMailNode:
    """`<ui:SendMail>`(知見116、DisplayNameは「Send SMTP Mail Message」
    (1.24未満)/「Send SMTP Email」(1.24以降)——`SendOutlookMail`同様、
    DisplayNameと裏のCLR型名`ui:SendMail`が食い違う。`UiPath.Mail.
    Activities`の汎用SMTP送信活動、`SendOutlookMailNode`(Outlook COM
    経由)とは独立したもう一つのメール送信経路)。

    `marcelocruzrpa/uipath-ai-skills`の`studio-ground-truth/`(知見114)で
    属性の完全な語彙を確認したところ、新しい(2.8)パッケージバージョンは
    Integration Service連携(`UseISConnection`)・OAuth・添付用の
    `BackupSlot`パターン等、非常に複雑な構造だと判明したが、
    `cameronmcnz/uipath-tutorials`の実機保存済みXAML(Gmail SMTP送信、
    実際に動作したと記載)で確認できたpopulated時の実例は、昔からの
    単純なSMTP直結属性(`Server`/`Port`/`Email`/`Password`/`EnableSSL`/
    `SecureConnection`)のみで構成されていた——`UseISConnection`等の
    新機能に触れない限りシンプルな経路のまま使えると判断し、この確認
    済みの単純な経路のみ対応する。

    `enable_ssl="True"`(確認済みの実例、`smtplib.SMTP_SSL`に対応)以外は
    `# TODO`——`SecureConnection`の列挙値を公式ドキュメントが明記して
    いない(「SSL/TLSの暗号化方式を指定する」という説明のみ)ため、
    `EnableSSL`無しでの動作(平文/STARTTLS)は未確認のまま見送る。"""

    to: Expr = None
    cc: Expr = None
    bcc: Expr = None
    subject: Expr = None
    body: Expr = None
    is_body_html: str | None = None
    email: Expr = None
    password: Expr = None
    server: Expr = None
    port: Expr = None
    enable_ssl: str | None = None
    secure_connection: str | None = None
    from_: Expr = None
    name: Expr = None
    reply_to: Expr = None
    use_oauth: str | None = None
    mail_message: Expr = None
    continue_on_error: Expr = None
    timeout_ms: Expr = None
    has_populated_files: bool = False
    display_name: str | None = None


@dataclass
class HttpClientNode:
    """`<ui:HttpClient EndPoint="..." Method="..." />`(知見29、
    DisplayName「HTTP Request」の裏のCLR型名)。`extra_attrs`に主要属性以外の
    生の属性値を残し、取りこぼしを防ぐ(`pad_codegen`の素通し方針と同じ)。

    `body`/`timeout_ms`は知見96でコード生成対象に追加した属性
    (`Body`/`TimeoutMS`、実機確認済みの既定値は`{x:Null}`/`"6000"`)。

    `headers`は知見104で追加——`gh api search/code`でGitHub上の実機保存
    済みXAMLから、populated時の実直列化形(`<InArgument x:Key="...">`、
    値は直接テキスト形・ネストした`<Literal>`子要素形の両方が実在)を
    確認し、`dict[str, Expr]`へパースする。`has_populated_collections`は
    `Cookies`/`Parameters`/`UrlSegments`/`Attachments`(`Headers`は専用
    フィールドに昇格したため対象外)のいずれかに1件以上のエントリが
    あるかを示す——これらのpopulated時の意味論(`Parameters`がクエリ
    文字列かフォームデータか等)はまだ未確認のため、空の場合のみ
    コード生成し、それ以外は`# TODO`へ倒す(知見96)。"""

    endpoint: Expr
    method: str = "GET"
    body: Expr = None
    timeout_ms: str | None = None
    headers: dict[str, Expr] = field(default_factory=dict)
    has_populated_collections: bool = False
    extra_attrs: dict[str, str] = field(default_factory=dict)


@dataclass
class FlowStepNode:
    """`<FlowStep>`(知見100、実際のUiPath/.NET保存済みXAMLで確認済み)。
    直接の子として実行する活動を0〜1個持つ(複数ステップなら`Sequence`で
    ラップされる——`If.Then`/`If.Else`と同じ可変長パターン、知見5。
    `ForEach.Body`等の「常にラップされる」パターンとは違い、`xaml_tree`
    側でラップを解かない——呼び出し側が`SequenceNode`かどうかで複数
    ステップかを判断できる、`_single_body`と同じ方針)。`next`は
    `FlowStep.Next`——無ければ(フローチャート終端)`None`。

    `next`は循環しうる(知見100で確認済みの実例が実際にループしていた)
    ——フィールドの型`FlowNode`は`None`も許容する自己参照的な再帰型。
    """

    body: list["Node"] = field(default_factory=list)
    next: "FlowNode" = None


@dataclass
class FlowDecisionNode:
    """`<FlowDecision Condition="...">`(知見100)。`Condition`は`If`/
    `While`と全く同じVB式属性形(知見5・14)。`true_branch`/`false_branch`
    は`FlowDecision.True`/`.False`——いずれも省略可能(VBの意味論上、
    分岐先が無ければそのままフローチャート終端になる、でっち上げた
    既定遷移は作らない)。"""

    condition: Expr
    true_branch: "FlowNode" = None
    false_branch: "FlowNode" = None


@dataclass
class FlowSwitchArm:
    """`FlowSwitch`配下の1ケース。`key=None`はdefaultアーム
    (`FlowSwitch.Default`プロパティ要素、知見40の`Switch.Default`と
    同じ規約)。"""

    key: str | None
    node: "FlowNode" = None


@dataclass
class FlowSwitchNode:
    """`<FlowSwitch x:TypeArguments="..." Expression="...">`(知見100)。
    各ケースは`FlowSwitch`の直接の子`<FlowStep x:Key="...">`(知見21の
    UiPath本体`Switch`と同じ属性形、知見100で実機確認済み)。"""

    expression: Expr
    type_arguments: str
    arms: list[FlowSwitchArm] = field(default_factory=list)


FlowNode = FlowStepNode | FlowDecisionNode | FlowSwitchNode | None
"""Flowchartのグラフを構成する1ノード。`None`はそこでフローが終端する
ことを表す——`Node`(通常の子アクティビティ列)とは別の再帰型。"""


@dataclass
class FlowchartNode:
    """`<Flowchart>`(知見100)。`variables`は`Flowchart.Variables`
    (`Sequence.Variables`と同じ規約、知見8)。`start`は`Flowchart.
    StartNode`——`FlowNode`のグラフの入口。

    ワークフローのルート型としてのみ対応する(Phase 1の決定「Sequence/
    Flowchartのみ」)——他の通常アクティビティ(`Node`)の子として
    ネストした`Flowchart`は本パーサーの対象外(実機で未確認)。
    """

    variables: list[VariableDecl] = field(default_factory=list)
    start: FlowNode = None


@dataclass
class UnknownActivityNode:
    """v1スコープ(design/uipath_transpiler_roadmap.md Phase 1)に含まれない、
    または本パーサーがまだ対応していないアクティビティ。架空のコードを
    でっち上げず、タグ名と属性をそのまま保持して後続フェーズ(または人間)が
    判断できるようにする——`pad_codegen`の`# TODO`出力と同じ「正直さ」の方針。

    知見84との違い(意図的な非対称性、将来「同じバグ」として誤って
    「修正」しないための注記): **子要素は一切保持しない**
    (`xaml_tree.parse_activity`参照)——未知のアクティビティ型の子要素が
    「実行すべき子アクティビティの列」なのか「設定用のプロパティ要素」
    なのかは、その具体的な型を知らない限り判別不可能(知見22で
    `ExcelApplicationScopeNode`の`.Body`→`ActivityAction`→`Sequence`が
    実行可能な子アクティビティ列だと実機確認できたのとは違い、未知の型
    全般に同じ仮定を適用するのは確証の無い推測になる)。知見84は
    「子が実行可能な列だと確定している」場合の修正であり、未知の型にまで
    この仮定を広げることは、でっち上げを避ける本クラスの設計意図に反する。
    """

    tag: str
    display_name: str | None = None
    attrs: dict[str, str] = field(default_factory=dict)


Node = (
    SequenceNode
    | AssignNode
    | MultipleAssignNode
    | MessageBoxNode
    | InputDialogNode
    | IfNode
    | ForEachNode
    | TryCatchNode
    | SwitchNode
    | WhileNode
    | DoWhileNode
    | BreakNode
    | ParallelNode
    | ClickNode
    | HoverNode
    | TypeIntoNode
    | SendHotkeyNode
    | GetTextNode
    | SelectItemNode
    | UiElementExistsNode
    | DatabaseConnectNode
    | DatabaseDisconnectNode
    | ExecuteQueryNode
    | ExecuteNonQueryNode
    | InvokeWorkflowFileNode
    | CopyFileNode
    | BuildDataTableNode
    | AppendLineNode
    | ReadTextFileNode
    | InvokeCodeNode
    | SetToClipboardNode
    | CommentNode
    | DelayNode
    | WriteLineNode
    | ThrowNode
    | RethrowNode
    | TerminateWorkflowNode
    | LogMessageNode
    | ExcelReadCellNode
    | ExcelWriteCellNode
    | AttachWindowNode
    | OpenApplicationNode
    | ExcelApplicationScopeNode
    | WordApplicationScopeNode
    | WordReplaceTextNode
    | ExcelReadRangeNode
    | ExcelWriteRangeNode
    | ExcelAppendRangeNode
    | SendOutlookMailNode
    | GetOutlookMailMessagesNode
    | SendMailNode
    | HttpClientNode
    | UnknownActivityNode
)


@dataclass
class WorkflowFile:
    """1つの`.xaml`ファイル全体(`<Activity x:Class="...">`)。`arguments`は
    `<x:Members><x:Property Name="..." Type="InArgument(...)" /></x:Members>`
    (知見12、Processのワークフロー引数宣言)。Libraryの`ActivityBuilder`形
    (知見26)はv1スコープ外(ロードマップPhase 1決定)のため未対応。
    """

    class_name: str
    root: SequenceNode | FlowchartNode
    arguments: dict[str, str] = field(default_factory=dict)
    variables: list[VariableDecl] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
