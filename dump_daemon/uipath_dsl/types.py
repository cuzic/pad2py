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
class MessageBoxNode:
    """`<ui:MessageBox Text="..." />`(知見2・5)。"""

    text: Expr = None
    caption: Expr = None


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
    ため現状は安全)。`OffsetX`/`OffsetY`(`Position="Custom"`時のみ意味を
    持つと推定)は未確認のまま捕捉しない——`Position`が`"Center"`以外の
    値だった場合は`_generate_click`が`# TODO`へ倒すため、`OffsetX`/
    `OffsetY`を素通りで失っても実害は無い。"""

    selector: str | None = None
    display_name: str | None = None
    click_type: str | None = None
    mouse_button: str | None = None
    key_modifiers: str | None = None
    cursor_position: str | None = None


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
class AppendLineNode:
    """`<ui:AppendLine FileName="..." Text="..." />`(知見15)。"""

    file_name: Expr
    text: Expr


@dataclass
class ReadTextFileNode:
    """`<ui:ReadTextFile FileName="..." Content="..." />`(知見16、`Content`は
    `OutArgument`相当で`[VarName]`角括弧形)。"""

    file_name: Expr
    content: Expr


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
class ExcelWriteCellNode:
    """`<ui:ExcelWriteCell Cell="..." SheetName="..." Text="..." />`(知見22)。"""

    cell: str
    sheet_name: str
    text: Expr


@dataclass
class ExcelApplicationScopeNode:
    """`<ui:ExcelApplicationScope WorkbookPath="...">...</ui:ExcelApplicationScope>`
    (知見22、`ActivityAction`+`DelegateInArgument`で`ForEach`と同じ構造)。"""

    workbook_path: str
    scope_var: str = "ExcelWorkbookScope"
    body: list["Node"] = field(default_factory=list)


@dataclass
class SendOutlookMailNode:
    """`<ui:SendOutlookMail To="..." Subject="..." Body="..." />`(知見24)。"""

    to: Expr
    subject: Expr
    body: Expr


@dataclass
class HttpClientNode:
    """`<ui:HttpClient EndPoint="..." Method="..." />`(知見29、
    DisplayName「HTTP Request」の裏のCLR型名)。`extra_attrs`に主要属性以外の
    生の属性値を残し、取りこぼしを防ぐ(`pad_codegen`の素通し方針と同じ)。"""

    endpoint: Expr
    method: str = "GET"
    extra_attrs: dict[str, str] = field(default_factory=dict)


@dataclass
class UnknownActivityNode:
    """v1スコープ(design/uipath_transpiler_roadmap.md Phase 1)に含まれない、
    または本パーサーがまだ対応していないアクティビティ。架空のコードを
    でっち上げず、タグ名と属性をそのまま保持して後続フェーズ(または人間)が
    判断できるようにする——`pad_codegen`の`# TODO`出力と同じ「正直さ」の方針。
    """

    tag: str
    display_name: str | None = None
    attrs: dict[str, str] = field(default_factory=dict)


Node = (
    SequenceNode
    | AssignNode
    | MessageBoxNode
    | IfNode
    | ForEachNode
    | TryCatchNode
    | SwitchNode
    | WhileNode
    | DoWhileNode
    | BreakNode
    | ParallelNode
    | ClickNode
    | InvokeWorkflowFileNode
    | AppendLineNode
    | ReadTextFileNode
    | InvokeCodeNode
    | SetToClipboardNode
    | ExcelWriteCellNode
    | ExcelApplicationScopeNode
    | SendOutlookMailNode
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
    root: SequenceNode
    arguments: dict[str, str] = field(default_factory=dict)
    variables: list[VariableDecl] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
