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
class ParallelForEachNode:
    """`<ParallelForEach x:TypeArguments="..." Values="...">
    <ActivityAction>...<Sequence>...</Sequence></ActivityAction>
    </ParallelForEach>`(知見270、discovery-fresh-pass-8で発見、裸の
    core WFタグ(`ui:`プレフィックス無し、`WF_NS`)、タグ名限定GitHub
    検索で多数の真の実機ヒット)。構造は`ForEachNode`(知見5)と完全に
    同一(`ActivityAction`+`DelegateInArgument`、`.Body`明示ラップ・
    `ParallelForEach`直下への暗黙配置の両形式とも実機確認——`ForEach`の
    `.Body`有無両対応と同じ判断)で、唯一の違いは意味論(並行実行)。

    実機3件(公式`UiPath-Services/StudioTemplates`の
    `OrchestrationProcess`テンプレート(2箇所、`upaf:FormTaskData`の
    単一タスク反復+`scg:List(upaf:FormTaskData)`のバッチ反復)、
    `mariokellner/UiPath-Parallel-Background-RE-Framework`の
    `Main.xaml`)で構成を確認——いずれも`ActivityAction`が
    `ParallelForEach`の直接の子(`.Body`明示ラップ無し)、`Values`は
    `[TaskList]`/`[TaskBatches]`/`[Enumerable.Range(1, cint(Config(...
    )))]`という実機確認済みのVB式。

    `ParallelNode`(知見19・20)が既に確立した「Pythonネイティブの軽量な
    並行実行の代替が無いため、v1ではブランチを単純に順次実行する(でっち
    上げた並行実行を装わない、明示的なコメント付きの簡略化)」という
    誠実な前例をそのまま継承する——`ForEachNode`とは別のノード型・
    生成関数として実装し(型が同一だと`_generate_node`のisinstance
    判定で`ForEach`と区別できず、この近似コメントを出せなくなるため)、
    コード生成自体は`_generate_for_each`の`for item in values:`と
    全く同じロジックを呼ぶが、先頭に`ParallelNode`と同じ形式の
    `# NOTE`コメントを追加する。"""

    item_var: str
    values: Expr
    body: list["Node"] = field(default_factory=list)
    type_arguments: str = "x:Object"


@dataclass
class RepeatNumberOfTimesXNode:
    """`<ui:RepeatNumberOfTimesX NumberOfTimes="..." StartAt="...">
    <ui:RepeatNumberOfTimesX.Body><ActivityAction x:TypeArguments="x:Int32">
    <ActivityAction.Argument><DelegateInArgument x:TypeArguments="x:Int32"
    Name="CurrentItem" /></ActivityAction.Argument><Sequence
    DisplayName="Do">...</Sequence></ActivityAction></ui:
    RepeatNumberOfTimesX.Body></ui:RepeatNumberOfTimesX>`(知見227、
    `ForEach`(知見5)と同じ`ActivityAction`+`DelegateInArgument`構造——
    唯一の違いは反復対象が明示的なコレクションではなく整数回数指定
    (`NumberOfTimes`+`StartAt`)であること)。タグ名限定GitHub検索で
    265件ヒット。`item_var`は`DelegateInArgument`の`Name`(実機全件で
    `"CurrentItem"`、公式ドキュメント確認済みの既定名と一致)。

    公式ドキュメント(WebSearch経由確認)で`StartAt`は「`CurrentItem`
    の開始値」(既定`1`)、`NumberOfTimes`は「繰り返し回数」(開始値に
    関わらず常にこの回数だけ実行)と確認済み——`StartAt`は反復回数には
    影響しない。実機複数件で`StartAt`省略(`Apress/Robotic-Process-
    Automation-Using-UiPath-StudioX`)・`StartAt="0"`(`RPA-UiPath-
    Projects/Sort-country-list`)の両方を確認——ground-truthの既定値
    `"1"`は常に実機で明示されるわけではなく、省略時はPython側で
    リテラル`1`を補う。`range(start_at, start_at + number_of_times)`
    に対応する。"""

    number_of_times: Expr
    start_at: Expr | None = None
    item_var: str = "CurrentItem"
    body: list["Node"] = field(default_factory=list)
    display_name: str | None = None


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
class ContinueNode:
    """`<ui:Continue />`(知見226、`Break`(知見18)と同じ属性無しの
    自己終了タグ、タグ名限定GitHub検索で458件ヒット)。ground-truth
    (`marcelocruzrpa/uipath-ai-skills`)・実機複数件
    (`PacktPublishing/Robotic-Process-Automation-RPA-for-Developers`
    の`ControlFlows.xaml`等)いずれも確認した構成に完全一致。
    Pythonの`continue`文に対応する——`Break`と同様、ループ外での
    使用はPython自身の構文エラー(`SyntaxError`)に委ねる(事前の
    文脈検証は行わない、既存の`BreakNode`実装と同じ判断)。"""


@dataclass
class ReturnNode:
    """`<ui:Return />`(知見238、`Break`/`Continue`と同じ属性無しの
    自己終了タグ、サブエージェントによる7回目の新規発見パス——
    `UiPath.System.Activities`のground-truth全件リストと既実装
    活動リストの体系的な差分で発見——タグ名限定GitHub検索で82件
    ヒット)。ground-truth(`marcelocruzrpa/uipath-ai-skills`)・実機
    (`crcnum4/UP_Loan_Prescreen`の`Meridian/AutoApprove.xaml`、
    `ui:IfElseIfBlock.Then`内の早期終了として複数回使用——
    `CommentOut`無効化ではないことを独立に再取得・確認)いずれも
    `<ui:Return />`に完全一致。

    公式ドキュメント(WebSearch経由確認、`return`ページ)で「エラー
    無しでワークフローをその時点で終了する(`Out`引数はその時点の
    値のまま返される)」と確認済み——本トランスパイラは各ワーク
    フローを独立したPython関数として生成するため、Pythonの`return`
    文(値無し)に直接対応する。Libraryプロジェクト内での呼び出し元
    ワークフローへの終了伝播という.NET側特有の既知の制約
    (公式ドキュメント確認済み)は、本トランスパイラがライブラリを
    呼び出し元へインライン展開する実行モデルを持たないため該当しない
    ——`Break`/`Continue`と同様、関数外での使用はPython自身の構文
    エラーに委ねる。"""

    display_name: str | None = None


@dataclass
class StartTimerNode:
    """`<ui:StartTimer Timer="..." />`(知見271、discovery-fresh-pass-9で
    発見、タグ名限定GitHub検索で14件ヒット)。公式ドキュメント
    (WebSearch経由確認)「新しいタイマーを作成するか、引数として渡された
    既存のタイマーを再起動する」——`System.Diagnostics.Stopwatch.
    Restart()`(経過時間をゼロへリセットして計測を開始)に相当する。

    実機2件(`paulsamuel-w-e/UiPath-Projects`の`SimpleWorkflow/
    Main.xaml`、`WasserstromPAteam/GPO-Roster-Avendra`の
    `GPO Roster Avendra_Performer/Google Address API Workflows/
    Download_Processed Output.xaml`)で確認した構成——`Timer`
    (`ui:Timer`型の変数、属性は唯一この1個のみ、ground-truth
    (`marcelocruzrpa/uipath-ai-skills`)でも同一)。下流アクセスは
    `start_time.Elapsed.TotalSeconds.ToString()`
    (`paulsamuel-w-e`実機)・`Timer11.ElapsedMilliseconds>600000`
    (`WasserstromPAteam`実機、`If`条件での数値比較)の2種類のみ
    実機確認済み——狭い確定済みサーフェスのため`StopTimerNode`/
    `ResetTimerNode`/`ResumeTimerNode`と共有する薄いラッパークラス
    `_Timer`(`.Elapsed`/`.ElapsedMilliseconds`のみ露出)として実装
    する(`_ImapMailMessage`と同じ設計判断クラス)。"""

    timer: Expr = None
    display_name: str | None = None


@dataclass
class StopTimerNode:
    """`<ui:StopTimer Timer="..." />`(知見271、`StartTimer`の対、
    タグ名限定GitHub検索で8件ヒット)。公式ドキュメント「`StartTimer`で
    開始したタイマーを停止する」——`Stopwatch.Stop()`(経過時間の
    累積を止めるが値は保持する)に相当する。実機
    (`paulsamuel-w-e/UiPath-Projects`)で`Timer="[start_time]"`の
    構成を確認。"""

    timer: Expr = None
    display_name: str | None = None


@dataclass
class ResetTimerNode:
    """`<ui:ResetTimer Timer="..." />`(知見271、タグ名限定GitHub検索で
    6件ヒット)。公式ドキュメント/フォーラム確認——「タイマーをゼロに
    戻す」——`Stopwatch.Reset()`(経過時間をゼロへリセットし、かつ
    計測も停止する)に相当する。実機(`WasserstromPAteam/
    GPO-Roster-Avendra`)で`Timer="[Timer11]"`、`If`条件
    `Timer11.ElapsedMilliseconds&gt;600000`で10分超過を判定した直後に
    呼ばれる構成を確認。"""

    timer: Expr = None
    display_name: str | None = None


@dataclass
class ResumeTimerNode:
    """`<ui:ResumeTimer Timer="..." />`(知見271、タグ名限定GitHub検索で
    4件ヒット)。公式ドキュメント/フォーラム確認——「渡されたタイマーを
    再開する」(`ResetTimer`で止めた後も経過時間をゼロのまま返し続け
    ないようにするための活動、とフォーラムで説明)——`Stopwatch.
    Start()`を既に停止中のインスタンスへ呼ぶ(経過時間をリセットせず
    計測を再開する)動作に相当する——`StartTimer`(常にゼロへリセット
    して再起動)とは意味論上明確に異なる。ground-truthで同じ
    `Timer`属性1個のみの構成を確認(実機での使用例は本調査では
    `StartTimer`/`StopTimer`/`ResetTimer`より少なく、タグ名限定検索
    4件のみだったが、4活動が常に同じ実機ファイル群に揃って出現する
    (ノイズではない)ことと、公式ドキュメント・ground-truthの構成が
    他3兄弟と完全に一致することから実装対象とした)。"""

    timer: Expr = None
    display_name: str | None = None


@dataclass
class BeepNode:
    """`<ui:Beep />`(知見277、discovery-fresh-pass-10で発見、`Break`/
    `Continue`/`Return`と同じ属性無しの自己終了タグ、タグ名限定GitHub
    検索で約13件ヒット)。ground-truth(`marcelocruzrpa/uipath-ai-skills`)
    ・実機2件(`kckustomac/rpa-devops`の`Main.xaml`、`anza-lab/
    LPL--Server4-latest-codes`の`LPL TID Letters_Automation Project/
    LMS Workflows/LMS portal login.xaml`)いずれも`<ui:Beep />`に完全
    一致。

    公式ドキュメント(WebSearch経由確認、`beep`ページ)で「Windowsの
    サウンド設定の既定のビープ音(Default Beep)に関連付けられた音を
    再生する」と確認済み——固定の周波数/長さのトーンを生成する.NETの
    `Console.Beep()`(既定800Hz・200ms)とは異なる、Windows既定の
    通知音を再生する動作のため、`winsound.Beep(freq, dur)`ではなく
    `winsound.MessageBeep()`(引数省略時の既定`MB_OK`が「既定のビープ音
    (Default Beep)」を再生する、Python公式ドキュメント確認済み)が
    正確に対応する。"""

    display_name: str | None = None


@dataclass
class IfElseIfBlockNode:
    """`<ui:IfElseIfBlock BlockType="ElseIf" Condition="..."
    DisplayName="...">`(知見239、`ui:IfElseIfV2.ElseIfs`
    (`BindingList<ui:IfElseIfBlock>`)の要素——単独のトップレベル
    活動としては登場しない、`IfElseIfV2Node`専用の補助データクラス
    のため`Node`合併型には加えない)。`BlockType`は`.ElseIfs`配下では
    実機確認済みの値が常に`"ElseIf"`のみ(他の値は未確認のため
    保持しない)。`Condition`はプレーンな属性(`InArgument`ラップ形は
    実機未確認)、`.Then`は`If.Then`/`IfElseIfV2.Then`と違い実機では
    常に`Sequence`でラップされる(単一アクティビティでも`Sequence
    DisplayName="Body"`が明示される、知見224の`ModifyText`と同じ
    「常にラップ」構造)ため`_unwrap_body_sequence`で対応する。"""

    condition: Expr = None
    then_body: list["Node"] = field(default_factory=list)
    display_name: str | None = None


@dataclass
class IfElseIfV2Node:
    """`<ui:IfElseIfV2 Condition="...">`(知見239、サブエージェントに
    よる7回目の新規発見パスで発見、タグ名限定GitHub検索で390件
    ヒット)。ground-truth(`marcelocruzrpa/uipath-ai-skills`)・実機
    複数件(`vajrang-b/UiPathIn30Days`の`Task30/Main.xaml`等、
    `.ElseIfs`が常に空のif/else構成——`HarshShindeTR/APISanity`・
    `SagarYelmarTR/TaxCaddy_sanity`の`Main.xaml`、`.ElseIfs`配下に
    `BlockType="ElseIf"`の`ui:IfElseIfBlock`が実際に1件以上入った
    if/elif/else構成を確認、いずれも`CommentOut`無効化ではない)で
    構造を確認した——`Condition`(トップレベル)+`.Then`+`.ElseIfs`
    (`BindingList<ui:IfElseIfBlock>`、実機では空または1件以上)+
    `.Else`。

    .NETの現代的な複数分岐if/elif/else構文——`Condition`
    (トップレベルif)が真なら`.Then`、`.ElseIfs`を先頭から順に評価し
    最初に真になったブロックの`.Then`、どれも偽なら`.Else`を実行する
    ——Pythonの`if/elif*/else`に直接対応する。`.Then`/`.Else`は実機
    では常に`Sequence`でラップされる(`ModifyText`知見224と同じ
    「常にラップ」構造、`If`の「複数ステップの時だけラップ」知見5
    とは異なる)ため`_unwrap_body_sequence`で対応する。`Condition`式
    の変換失敗時は`If`(知見5・61・155)と同じ厳格な失敗モード
    (`NotImplementedError`をそのまま伝播)——反復対象・条件式を誤って
    推測すると分岐全体が誤るため。"""

    condition: Expr = None
    then_body: list["Node"] = field(default_factory=list)
    else_ifs: list[IfElseIfBlockNode] = field(default_factory=list)
    else_body: list["Node"] = field(default_factory=list)
    display_name: str | None = None


@dataclass
class AddLogFieldsNode:
    """`<ui:AddLogFields><ui:AddLogFields.Fields><InArgument
    x:TypeArguments="x:String" x:Key="...">...</InArgument>...
    </ui:AddLogFields.Fields></ui:AddLogFields>`(知見240、知見238と同じ
    7回目発見パスでの候補、タグ名限定GitHub検索で1880件ヒット——今回の
    発見パス全体で最も高い実機利用率)。ground-truth
    (`marcelocruzrpa/uipath-ai-skills`)は空の`Fields=Dictionary<String,
    InArgument>`のみ。実機は公式`UiPath/Community.Activities`リポジトリ
    自身が配布するREFrameworkテンプレート(`Templates/ReFrameWork/
    Main.xaml`)で確認——populated時は`<scg:Dictionary>`ラッパー自体が
    無くなり各エントリが`x:Key`付き`<InArgument x:TypeArguments="x:String"
    x:Key="logF_BusinessProcessName">[VB式]</InArgument>`として直接の子に
    なる、知見104の`HttpClient.Headers`と同じ直列化パターン——既存の
    `_xkey_dict_entries()`をそのまま再利用できた。

    公式ドキュメント確認済みの実行時意味論: 以降実行される全ての
    `Log Message`活動の出力に、`Remove Log Fields`で明示的に削除される
    まで追加フィールドとして付与され続ける(ブロックスコープではなく
    「実行がそこを通過した後」という命令的な持続——`If.Then`内で実行
    されたかどうかに関わらない)。本トランスパイラは各ワークフローを
    独立したPython関数として生成するため、関数ローカルな`_log_fields`
    辞書(関数内のどこからでも`.update()`/`.pop()`で変更可能、
    Pythonの関数ローカル変数は`if`/`for`/`try`等の入れ子ブロックを
    跨いで共有されるため再現できる)として実装する——スレッドセーフな
    真のアンビエントコンテキストではなく、ワークフロー単体の近似。
    フォーラム報告(未公式確認)によれば呼び出し先ワークフローにも伝播
    するとされるが、本トランスパイラの`ScopeInfo`はファイル単位で
    一度だけ構築されるため、呼び出し元ファイルを跨いだ伝播は未対応
    (既存の`data_table_columns`と同じ既知のファイル単位の限界)。"""

    fields: dict[str, Expr] = field(default_factory=dict)
    display_name: str | None = None


@dataclass
class RemoveLogFieldsNode:
    """`<ui:RemoveLogFields><ui:RemoveLogFields.Fields><scg:List
    x:TypeArguments="InArgument(x:String)"><InArgument
    x:TypeArguments="x:String">fieldName</InArgument>...</scg:List>
    </ui:RemoveLogFields.Fields></ui:RemoveLogFields>`(知見240、
    `AddLogFields`の対になる削除活動、同じ発見パス——GitHubタグ名限定
    検索で918件ヒット)。ground-truthは空の`Fields=List<InArgument
    (x:String)>`のみ。実機は`AddLogFields`と同じ公式REFrameworkテンプ
    レート(`Templates/ReFrameWork/Framework/SetTransactionStatus.xaml`)
    で確認——`<scg:List x:TypeArguments="InArgument(x:String)"
    Capacity="N">`配下に`<InArgument x:TypeArguments="x:String">
    logF_TransactionStatus</InArgument>`形のフィールド名リテラル文字列が
    直接の子として並ぶ、既存の`_parse_property_element_list()`
    (知見207・218)が想定する`<scg:List>`+素のテキスト子要素パターンと
    完全一致したため再利用できた。削除するフィールド名の集合を保持し、
    `AddLogFieldsNode`と同じ関数ローカル`_log_fields`辞書から
    `.pop(key, None)`する(無かった場合も無視、`.NET`側も未存在キーの
    削除は無害と推定——例外発生を示す記述は公式ドキュメントに無い)。"""

    fields: list[Expr] = field(default_factory=list)
    display_name: str | None = None


@dataclass
class DeserializeJsonNode:
    """`<ui:DeserializeJson x:TypeArguments="njl:JObject" JsonString="..."
    JsonObject="...">`(知見241、タグ名限定GitHub検索で1230件ヒット
    ——知見229で「典型的な『未モデル化の型付きオブジェクトへの
    ダウンストリームdot-access』問題、`GetFileInfoX`/`GetFolderInfoX`と
    同種」と注意深く記録されていた活動)。ground-truth
    (`marcelocruzrpa/uipath-ai-skills`)でジェネリック活動
    (`DeserializeJson<T>`、ファイル名が`` DeserializeJson`1.xaml ``)
    であることが判明——既定の`x:TypeArguments`は`njl:JObject`
    (`Newtonsoft.Json.Linq.JObject`)。実機複数件(`andumorie/uipath-
    face-recognition-framework`の`Main-Identify.xaml`、`base64ai/
    uipath-samples`の`Base64.ai Facial Verification.xaml`)でも
    `x:TypeArguments="njl:JObject"`のみ確認——他の型引数(カスタム
    POCO等)は未確認のため対象外とする。

    `base64ai/uipath-samples`で確認済みのダウンストリーム利用形
    (`formattedJson("matches").Count.ToString`)により、
    `GetFileInfoX`/`GetFolderInfoX`が引き返した「未確認の広いdot-access
    サーフェス」懸念は実際には**狙い撃ちできる狭い範囲**だと判明した:
    VB.NETの`識別子(引数)`添字構文(知見126・203の`DataRow`行アクセス
    `row("col")`と構文的に同一、`ScopeInfo.json_object_vars`で型を
    追跡して判別)+`.Count`(コレクション要素数、既存の`.Length`→
    `len()`と同じ意味論)のみ対応する——JObjectの他のメンバ
    (`.Properties()`・`.SelectToken(path)`等)は未確認のため見送る。
    `JObject`→Python`dict`(`json.loads()`の戻り値)という素直な表現で、
    `GetFileInfoX`のような架空のラッパークラスは不要。"""

    json_string: Expr = None
    json_object: Expr = None
    type_argument: str | None = None
    display_name: str | None = None


@dataclass
class DeserializeJsonArrayNode:
    """`<ui:DeserializeJsonArray JsonString="..." JsonArray="..." />`
    (知見245、`DeserializeJson<njl:JObject>`(知見241)の兄弟活動、
    タグ名限定GitHub検索で142件ヒット)。`DeserializeJson`と違い
    ジェネリックではない(`x:TypeArguments`無し、実機確認済み)——
    `JsonArray`は常に`njl:JArray`型。

    実機2件(`vajrang-b/UiPathIn30Days`の`SourceCode/2024/Projects/
    April 2024/RandomuserMeApi/Main.xaml`、`base64ai/uipath-samples`
    の`Sequences/Base64.ai Facial Recognition.xaml`)で確認済みの
    ダウンストリーム利用形(`formattedJson.Count.ToString`、
    `currentItem("picture")("large").ToString()`——`ui:ForEach
    x:TypeArguments="njl:JToken"`の反復変数経由)は、知見241の
    `JObject`と同じ狙い撃ちできる狭いパターン(VBの`識別子(引数)`
    添字構文+`.Count`)——`JArray`も`JObject`と同じ`ScopeInfo.
    json_object_vars`機構を共有してよい(両方ともPython側は`json.
    loads()`の戻り値という素の`dict`/`list`表現で、添字アクセス・
    要素数カウントの意味論に違いが無いため)。`JObject`→`JArray`間の
    `ui:ForEach`ループ変数(`currentItem`)への型伝播は、既存の
    `ForEachRow`の`data_row_vars`伝播(知見203)と同じ既存パターンを
    再利用する。

    知見244追記: 実機`vajrang-b/UiPathIn30Days`サンプルは
    `DeserializeJson`の出力`JObject`から`JsonObject("results").
    ToString()`という式で本活動の`JsonString`入力を作っていた——これを
    調査中に、`json_object_vars`添字アクセス直後に単独で`.ToString()`
    が続く式の実行時型(スカラーかJSONコンテナか)が静的に決定不能で、
    既存の`_vb_cstr()`への単純な変換は後者の場合に無効なJSON文字列を
    生成してしまう(`render.py`の`_render_chained_access`で修正、
    `str()`/`json.dumps()`どちらに倒すかでっち上げず`NotImplementedError`
    へ倒す)という独立したバグを発見・修正した。"""

    json_string: Expr = None
    json_array: Expr = None
    display_name: str | None = None


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
class ActivateNode:
    """`<ui:Activate>`(知見162、GitHub code searchで604件ヒット)。
    `UiPath/skills`公式リポジトリのStudio実機ground-truthコーパス
    (`UiPath.UIAutomation.Activities/25.10/Activate.xaml`、知見128で
    発見した504件の単体活動フィクスチャ)+複数の実機XAML
    (`Digital-RPA/MRE_B2BE`等)で確認した構造は`Target`+`DelayBefore`/
    `DelayMS`/`ContinueOnError`のみ——`ClickNode`/`HoverNode`より
    さらに単純で、`CursorPosition`自体を持たない(クリックも移動も
    伴わず、指定した要素/ウィンドウをフォアグラウンドへ切り替える
    だけの活動であるため)。pywinautoの`set_focus()`(両バックエンドの
    `base_wrapper`で共通にサポートされる確認済みの標準API)が直接
    対応する——`move_mouse_input()`のような既定値の罠(知見157)は
    無い、最も単純な変換の1つ。

    知見164追記: `ui:SetFocus`(`UiPath/skills`公式ground-truthコーパス
    +`JoeIaquinto/UiPath-VidCreator`等の実機XAML、GitHub code searchで
    68件ヒット)は`DisplayName`が`"Set Focus '...'"`になる同義の別活動
    だと判明した——`Target`+`DelayBefore`/`DelayMS`/`ContinueOnError`
    という属性構成が`Activate`と完全に同一(`AttachWindow`/
    `WindowScope`/`BrowserScope`、知見153・158・161と同じ「同義の別名
    活動」パターン)。`_parse_activate`は属性名のみを汎用的に読む
    (タグ名に依存しない)ため、新しい専用のパーサー関数は追加せず
    `_DISPATCH`に同じ`_parse_activate`を2つのタグ名で登録するだけで
    済んだ——このノード型を再利用するあらゆる活動と同様。"""

    selector: str | None = None
    display_name: str | None = None
    delay_before: Expr = None
    delay_ms: Expr = None
    continue_on_error: Expr = None


@dataclass
class CheckNode:
    """`<ui:Check>`(知見165、チェックボックス操作、GitHub code searchで
    805件ヒット——知見164の`ui:SetFocus`調査中に実機XAML(`PakamTharunReddy/
    RPA`)で遭遇)。実機5件(`PacktPublishing/Robotic-Process-Automation-
    RPA-for-Developers`・`miyaichi/UiLession`)で確認した属性は`Action`
    (実機確認済みの値は`"Check"`/`"Uncheck"`の2種)+`Target`+
    `ContinueOnError`/`DelayAfter`/`DelayBefore`(いずれも全件
    `{x:Null}`)。`DelayBefore`は他のUI Automation活動(`Click`/
    `TypeInto`/`Hover`/`Activate`/`SendHotkey`)と共有の「Common」属性
    グループで意味論確認済み(知見106)のため同様に扱うが、`DelayAfter`
    は本調査で初めて遭遇した属性で意味論未確認——`DelayMS`と同じ理由
    (非既定値設定時は`# TODO`へ倒す)で保守的に扱う。

    `Action="Check"`/`"Uncheck"`は「指定の最終状態へ**設定する**」操作
    (単純な無条件トグルではない)——実機確認したpywinautoのUIA
    `ButtonWrapper`(`CheckBox`/`RadioButton`/`Button`の`control_type`に
    適用される)が`toggle()`+`get_toggle_state()`(`0=unchecked`/
    `1=checked`/`2=indeterminate`)を標準サポートしているため、現在の
    状態を読んでから目的の状態と異なる場合のみ`toggle()`を呼ぶ
    (無条件に`click_input()`すると既にチェック済みの場合に誤って
    外してしまう)専用ヘルパーで実装する。"""

    selector: str | None = None
    display_name: str | None = None
    action: str | None = None
    delay_before: Expr = None
    delay_after: Expr = None
    continue_on_error: Expr = None


@dataclass
class HighlightNode:
    """`<ui:Highlight>`(知見166、要素の視覚的ハイライト、GitHub code
    searchで289件ヒット——知見164の`ui:SetFocus`調査中に実機XAML
    (`PacktPublishing/Robotic-Process-Automation-RPA-for-Developers`)
    で遭遇)。実機確認した属性は`Color`(`"Blue"`/`"Gold"`等、.NETの
    `Color`構造体の名前付き色、実機で複数の異なる値を確認)・
    `HighlightTime`(ミリ秒、実機確認済み`"3000"`/`"1000"`)+`Target`
    のみ——出力(`Result`等)を一切持たない。

    この活動は画面上に一時的な色付き枠を表示するだけの**純粋な視覚的
    デバッグ支援**で、後続のアクティビティへ渡すデータや制御フローへの
    影響が一切無い(実機確認した全件で出力バインディングも無い)。
    pywinautoには`draw_outline()`という近い機能があるが、対応する色
    文字列の語彙が`'red'`/`'green'`/`'blue'`の3色のみ(`base_wrapper.py`
    で確認済み)でUiPathの`.NET Color`構造体の全名前付き色(`Gold`等)を
    カバーできず、かつ`draw_outline()`自体は描画するだけで
    `HighlightTime`経過後に自動で消す機能を持たない(タイマー処理を
    追加する必要がある)——`Click`のように「正確性が自動化の結果に
    影響する」活動とは違い、この活動の実行結果が自動化スクリプトの
    正しさに全く影響しないため、不確実な視覚的再現を試みるより
    `# Highlight`コメント(`ui:Comment`、知見119と同じ「実行時の挙動が
    無い活動はコメントへ変換する」設計)として扱う方が誠実——`# TODO`
    (何かが未実装/未対応)ではなく、意図的な「この活動には再現すべき
    実行時効果が無い」という判断を示す。"""

    selector: str | None = None
    display_name: str | None = None
    color: str | None = None
    highlight_time: Expr = None


@dataclass
class CloseApplicationNode:
    """`<ui:CloseApplication>`(知見171、GitHub code searchで532件
    ヒット)。`Target`+`DisplayName`/`ContinueOnError`のみという、
    `ActivateNode`(知見162)と全く同じ属性構成——実機3件
    (`HarshadRanganathan/uipath-learning`・`piyushagarwal08/JU-Notes`・
    `allenlooplee/RPABook`)で確認。`ActivateNode`を再利用せず新規に
    ノード型を分けたのは、生成するpywinauto呼び出しが`set_focus()`
    (フォーカス切替、副作用なし)とは全く異なる`close()`
    (`WM_CLOSE`送信、ウィンドウを実際に閉じる)になるため——
    `AttachWindowNode`のような「透過スコープ」族と違い、これは
    「実際に効果を起こす」活動であり、ノード型を共有すると
    生成コードの意図が不明瞭になるという判断。"""

    selector: str | None = None
    display_name: str | None = None
    continue_on_error: Expr = None


@dataclass
class CloseWindowNode:
    """`<ui:CloseWindow>`(知見172、GitHub code searchで276件ヒット)。
    `CloseApplication`(知見171)と同じ「閉じる」意味論だが、属性構成が
    全く違う——`Target`ラッパー経由ではなく`Selector`を直接のフラット
    属性として持つ「Classic」世代の活動(`UiPath/skills`公式
    ground-truthコーパスの25.10系には存在せず、`AttachWindow`/
    `OpenApplication`(知見154)と同じ旧世代の属性慣習)。実機3件
    (`SuneetPatil/IRCTC-tatkal-booking`・`PacktPublishing/Robotic-
    Process-Automation-RPA-for-Developers`・`KonduitAI/mailbox
    detection-workflow`)で確認した属性は`Selector`+`UseWindow`
    (既存のウィンドウ参照を再利用する、`[browser_window.Element.
    GetTopLevelWindow]`のようなVB式——`OpenBrowser`の`UiBrowser`
    バインディング等と同じ「未モデル化のオブジェクト参照」カテゴリ)
    +`ContinueOnError`。`TimeoutMS`/`WaitForReady`は他のUI Automation
    活動と同様、生成コードに影響しないため無視する。

    `_attr(elem, "Selector")`はフラット属性の生取得のみで`{x:Null}`
    正規化を行わない(`_parse_expr`を通さないため)——`AttachWindow`/
    `OpenApplication`ではSelectorが必須属性で実機上`{x:Null}`に
    なる例が無く潜在していたが、`CloseWindow`は`UseWindow`使用時に
    `Selector="{x:Null}"`になる実例(実機2件)が頻出するため、
    本ノードのパーサーで初めて明示的な正規化が必要になった。"""

    selector: str | None = None
    use_window: Expr = None
    display_name: str | None = None
    continue_on_error: Expr = None


@dataclass
class WindowStateNode:
    """`<ui:MaximizeWindow>`(知見173、GitHub code searchで1632件
    ヒット——実際のタグ名は検索語の部分一致で発見、1632件は`ui:Maximize`
    を含む全文字列のヒット数であり真の件数ではない点に注意)/
    `<ui:MinimizeWindow>`(44件)/`<ui:RestoreWindow>`(13件)という
    3つの同義の兄弟活動——いずれも`Window`+`DisplayName`/
    `ContinueOnError`のみの同一属性構成で、唯一違うのはpywinautoで
    呼ぶメソッド名(`maximize()`/`minimize()`/`restore()`、いずれも
    `.venv`のソースで両バックエンド共通の確認済み標準API)。実機4件
    (`allenlooplee/RPABook`・`PacktPublishing/Robotic-Process-
    Automation-Projects`・`piyushagarwal08/JU-Notes`・`Apress/Robotic-
    Process-Automation-Using-UiPath-StudioX`・`LowyShin/lwrpa-uip-
    giipxls2kvs`)で確認した`Window`の値は`{x:Null}`(ほとんどの実例)
    と`[Saved.Values(Of Window)("ActiveWindow")]`(StudioXの保存済み
    `Window`型変数参照、`Apress`の実機XAMLで確認)の2種。

    `Window`が`{x:Null}`の場合の意味論は「現在アクティブな(フォーカス
    中の)ウィンドウ」——pywinautoの`findwindows.find_elements()`が
    標準サポートする`active_only=True`(`win32functions.
    GetGUIThreadInfo()`でOS全体のアクティブウィンドウハンドルを取得、
    実装を確認済みの標準API)を`Desktop(backend="uia").
    window(active_only=True)`経由で使うことで対応する——`CloseTab`
    (知見170)の`send_keys('^w')`と同じ「対象省略時は現在フォーカス中
    のものを指す」という確認済みの意味論パターン。`Window`が変数参照
    の場合は(`Window`型オブジェクト自体が未モデル化のため、知見154・
    161・168・170・172で繰り返し確認済みの既知の限界)`# TODO`へ倒す。"""

    method: str = "maximize"
    window: Expr = None
    display_name: str | None = None
    continue_on_error: Expr = None


@dataclass
class GenerateDataTableNode:
    """`<ui:GenerateDataTable>`(知見197、GitHub code searchで180件
    ヒット——知見195で2番目に有望と評価したDataTable操作系候補)。
    公式ground-truthコーパス(25.10・26.2とも同一)は`ColumnSeparators`
    +`ColumnSizes`+`DataTable`(出力)+`Input`+`NewLineSeparator`+
    `Positions`のみだが、実機3件(`vajrang-b/UiPathIn30Days`)では
    ground-truthに載っていない`CSVParsing`(`"True"`/`"False"`)・
    `UseColumnHeader`(全件`"True"`)・`AutoDetectTypes`(`"False"`)も
    確認した——ground-truthコーパスが実機の全属性を網羅していない
    実例(知見128の既存の注意書きを裏付ける)。

    テキスト(`Input`)を区切り文字(`ColumnSeparators`、実機は`";"`/
    `","`の単一文字)+改行(`NewLineSeparator`、実機は`"\\n"`相当か
    未設定)で分割し、1行目を列名とする(`UseColumnHeader="True"`)
    `DataTable`を構築する活動。`CSVParsing="True"`時はPython標準の
    `csv`モジュール(引用符で囲まれたフィールド内の区切り文字を正しく
    扱う、`ReadCsvFile`知見185と同じ`csv.DictReader`)、`"False"`時は
    単純な`str.split()`で対応する。固定幅モード(`Positions`/
    `ColumnSizes`が非null)・`UseColumnHeader`が`"True"`以外・
    `AutoDetectTypes="True"`(型推論の正確な意味論が未確認)は実機での
    使用例を一度も確認できなかったため、常に`# TODO`へ倒す。既存の
    DataTableを読まず新規に構築するため、出力は知見183以来一貫して
    使っているdict行表現で統一できる——知見179の表現非統一性問題を
    回避できる、知見196の`LookupDataTable`と同じ構造的な利点がある。"""

    display_name: str | None = None
    input: Expr = None
    data_table: Expr = None
    column_separators: Expr = None
    new_line_separator: Expr = None
    use_column_header: str | None = None
    csv_parsing: str | None = None
    auto_detect_types: str | None = None
    positions: Expr = None
    column_sizes: Expr = None


@dataclass
class GetAttributeNode:
    """`<ui:GetAttribute>`(知見174、GitHub code searchで274件ヒット)。
    `Target`+`Attribute`(属性名、実機確認済みの値は`"checked"`/
    `"innerText"`/`"relativeVisibility"`——UiPathのブラウザ拡張機能が
    DOM/アクセシビリティツリーから取得する任意の属性名)+`Result`
    (出力、`GetText`/`GetFullText`と同じ`_in_argument_property_expr`
    形)+`ContinueOnError`という構成——実機3件(`rohanbaraskar/
    UiPath-11`・`miyaichi/CalculateClientSecurityHash`・
    `iamgauravjoshi/Shopping-Bot-using-RPA`)で確認。

    `Attribute`は開放的な語彙(UiPathのブラウザ拡張が内部でDOM属性/
    アクセシビリティプロパティへ変換する仕組みで、値ごとに全く別の
    取得経路を要求する)——pywinauto(Win32/UIAバックエンドのみ、
    ブラウザのJS/DOM注入機能を持たない)側にこれを安全に代替できる
    汎用APIが存在しない。`"checked"`はUIAのTogglePattern
    (`get_toggle_state()`、知見165で確認済み)で近似できる可能性が
    あるが、実機のブラウザ要素で本当にDOMの`checked`プロパティと
    UIAのToggle状態が一致するかは(知見38の`role`属性のような
    ハードクラッシュのリスクも含め)VM実機検証なしに確定できないため、
    `Attribute`の値を問わず常に`# TODO`へ倒す——ただし「unknown
    activity」の生の属性ダンプより、`Attribute`名を明示した読みやすい
    `# TODO`にする価値はある(将来VM実機検証が済んだ属性値だけを
    個別に有効化できる土台にもなる)。"""

    selector: str | None = None
    display_name: str | None = None
    attribute: str | None = None
    result: Expr = None
    continue_on_error: Expr = None


@dataclass
class GetPasswordNode:
    """`<ui:GetPassword>`(知見176、GitHub code searchで540件ヒット
    ——うち大半が1つの学習用リポジトリの類似演習の重複だが、それを
    除いても独立した実機10件以上で確認できた、実在する一般的な活動)。
    `ProtectedPassword`(Windows DPAPIで暗号化されたバイナリ、Base64
    表記——実機確認した全件が`AQAAANCMnd8BFdERjHoAwE/Cl+sB...`という
    DPAPIの固定ヘッダ`01 00 00 00 D0 8C 9D DF 01 15 D1 11 8C 7A 00 C0
    4F C2 97 EB`で始まる)+`Result`(出力、実機で2つの直列化形を確認
    ——フラット属性`Result="[pw]"`と、プロパティ要素形`<ui:
    GetPassword.Result><OutArgument>...<VisualBasicReference
    ExpressionText="Password">...`の両方)という構成。`ContinueOnError`
    は実機のどの例でも一度も確認できなかった(本活動自体に存在しない
    可能性もある)。

    `ProtectedPassword`はWindows DPAPI(`CryptProtectData`)で暗号化
    されており、暗号化を行ったWindowsユーザー・マシンの組み合わせ
    でなければ復号できない——UiPath Studioが設計時にローカルマシン
    上で暗号化したものを埋め込むため、この値を生成Pythonコードへ
    移植可能な形で復号する安全な方法は無い(別マシン・別ユーザーで
    実行すれば`CryptUnprotectData`はエラーになる)。さらに資格情報を
    扱う機微な操作であるため、`ProtectedPassword`の値自体を
    生成コードのコメントへ一切出力しない(暗号化済みとはいえ資格情報
    関連のブロブをソースへ残さない、安全側の判断)。`Result`の有無を
    問わず常に`# TODO`へ倒す——知見174の`ui:GetAttribute`と同じ
    「常にTODOへ倒れる活動でも、ノード型を適切にモデル化する価値が
    ある」という判断の2例目。"""

    display_name: str | None = None
    result: Expr = None


@dataclass
class GetSecureCredentialNode:
    """`<ui:GetSecureCredential Target="..." CredentialType="Generic"
    PersistanceType="Enterprise" Result="..." Username="..."
    Password="..." />`(知見248、9回目発見パスで発見、タグ名限定
    GitHub検索で174件ヒット)。`GetPasswordNode`(知見176)とは構造・
    解決可能性が全く異なる——`GetPassword`の`ProtectedPassword`は
    XAML自体に埋め込まれたWindows DPAPI暗号化バイナリ(別マシンでは
    復号不能、永久に`# TODO`)だが、`GetSecureCredential`の`Target`は
    単なるWindows資格情報マネージャーへの**実行時の検索キー名**——
    秘密自体はXAMLには一切含まれず、実行時に
    (`pywin32`——本プロジェクト既存の確認済み依存、`GetOutlookMail
    Messages`等のOutlook COM連携で既に使用中、新規依存の判断は不要)
    `win32cred.CredRead()`で解決する。

    公式の`UiPath/Community.Activities`リポジトリ自身のREFramework
    テンプレート(`Templates/ReFrameWork/Framework/
    GetAppCredentials.xaml`)で実際の使用(`CredentialType="Generic"`
    +`PersistanceType="Enterprise"`+`Result`(bool、取得成功)+
    `Username`(出力)+`Password`(出力、`ss:SecureString`型だが本
    トランスパイラは変数の型を区別しないため関係無い))を確認した
    ——Studio自体が生成する公式ボイラープレートという最も権威的な
    実機ソース(知見240のAddLogFields/RemoveLogFieldsと同じ信頼性
    クラス)。公式ドキュメント(WebFetch経由確認)でも同じ属性構成
    (`CredentialType`/`PersistanceType`は列挙だが確認済みの値は
    `"Generic"`/`"Enterprise"`のみ)を確認。

    `win32cred.CredRead()`は見つからない場合に`None`を返すのではなく
    `pywintypes.error`(`winerror=1168`、`ERROR_NOT_FOUND`)を**投げる**
    ことをWebSearch経由で独立に確認済み(一部のサードパーティ`ctypes`
    再実装ドキュメントは誤って`None`を返すと説明しているが、本物の
    `pywin32`パッケージの実際の挙動はこちらで確認した例外経由)——
    この例外を捕捉して`Result=False`へ変換する。`CredentialBlob`は
    UTF-16(BOM無し、`utf-16-le`)でエンコードされた生バイトとして
    返る(`python-keyring`のWindowsバックエンド実装で確認済みの既知の
    規約)ため`.decode("utf-16-le")`が必要。"""

    target: Expr = None
    credential_type: str | None = None
    persistance_type: str | None = None
    result: Expr = None
    username: Expr = None
    password: Expr = None
    continue_on_error: Expr = None
    display_name: str | None = None


@dataclass
class AddCredentialNode:
    """`<ui:AddCredential Target="..." CredentialType="Generic"
    PersistanceType="Enterprise" Username="..." Password="..."
    SecurePassword="..." Result="..." />`(知見248、`GetSecureCredential`
    の対になる書き込み活動、タグ名限定GitHub検索で125件ヒット)。公式
    `UiPath/Community.Activities`のREFrameworkテンプレート
    (`Templates/ReFrameWork/Framework/GetAppCredentials.xaml`)で実際の
    使用(`CredentialType="Generic"`+`PersistanceType="Enterprise"`+
    `Username`(入力)+`Password`(入力、この実機サンプルでは生の
    `x:String`変数——`SecurePassword`は公式ドキュメント確認済みの別の
    入力プロパティとして存在するが実機未確認のため見送る)、`Result`
    属性自体は実機サンプルに現れない)を確認した。

    `win32cred.CredWrite()`に対応する——`CredentialBlob`は`.encode(
    "utf-16-le")`で`GetSecureCredential`と対になるエンコーディングに
    する。実機未確認の`Result`が設定されている場合(書き込み失敗時の
    意味論が未確認)は見送る。"""

    target: Expr = None
    credential_type: str | None = None
    persistance_type: str | None = None
    username: Expr = None
    password: Expr = None
    secure_password: Expr = None
    result: Expr = None
    continue_on_error: Expr = None
    display_name: str | None = None


@dataclass
class RequestCredentialNode:
    """`<ui:RequestCredential Title="..." Message="..." Result="..."
    Username="..." Password="..." />`(知見248、`GetSecureCredential`が
    見つからなかった場合のフォールバックとして同じREFramework
    テンプレートで使われるGUIプロンプト活動、タグ名限定GitHub検索で
    123件ヒット)。公式ドキュメント確認済み: ユーザーに資格情報の入力
    を求めるダイアログを表示し、`Username`/`Password`(出力)+
    `Result`(bool、ユーザーが入力したか`Cancel`をクリックしたか)を
    返す。

    `InputDialogNode`(知見131)の「`input()`はダイアログへの代替・
    妥協ではなく直接対応する変換」という判断をそのまま継承する——
    `Username`→`input()`、`Password`→`getpass.getpass()`。ただし
    `Result`(Cancel判定)はPythonの素の`input()`/`getpass.getpass()`
    には対応概念が無い(ブロッキング呼び出しに「キャンセル」という
    概念自体が存在しない)——これは省略できない構造的なギャップ
    のため、`Result`が束縛されている場合は常に`True`を代入する
    (実機`UiPath/Community.Activities`のREFrameworkテンプレートでは
    `Result`を後続の`If (Not credentialFound)`で検査する——コンソール
    入力は常に何らかの値を返しキャンセル不能なため、`True`固定が
    「ユーザーが実際に入力した」という最も一般的な実行結果に対応する
    近似だと判断した、`Parallel`の順次実行化と同じ種類の判断)。"""

    title: Expr = None
    message: Expr = None
    result: Expr = None
    username: Expr = None
    password: Expr = None
    continue_on_error: Expr = None
    display_name: str | None = None


@dataclass
class GetUsernamePasswordXNode:
    """`<uas:GetUsernamePasswordX CredentialsSource="CredentialsManager"
    CredentialName="..." OrchestratorCredentialName="{x:Null}"
    AutosubmitTimeoutSeconds="10" TimeoutInSeconds="{x:Null}"
    Credential="..." />`(知見253、10回目発見パスで発見、タグ名限定
    GitHub検索で67件ヒット、`UiPath.Activities.System`名前空間
    (`uas:`——知見237の`UiPath.Activities.System.Text`(`uast:`)とは
    別の、同じ接頭辞を持つ兄弟名前空間)。実機2件
    (`tudor555/Best-Flight`・`adithya0414/GetEmailsWith_IMAP-
    Filtering`)で確認した構成——いずれも`CredentialsSource=
    "CredentialsManager"`+`OrchestratorCredentialName="{x:Null}"`+
    `AutosubmitTimeoutSeconds="10"`+`TimeoutInSeconds="{x:Null}"`で
    完全一致。

    `GetSecureCredentialNode`(知見248)が既に解決した`win32cred.
    CredRead()`基盤をそのまま再利用できる——`CredentialName`が単なる
    実行時のWindows資格情報マネージャー検索キー名で、秘密自体はXAML
    に一切含まれない点も同じ。確認済みの下流アクセス(`Credential.
    Username`/`Credential.Password`、いずれも実機2件とも`ui:SendMail`/
    `ui:GetIMAPMailMessages`の`Email`/`Password`引数として直接消費)に
    絞った`_Win32Credential`薄いラッパークラスで対応する
    (`_ImapMailMessage`(知見250)と同じ判断クラス)。

    `GetSecureCredentialNode`と違い本活動には`Result`出力が存在しない
    (実機2件とも確認)——資格情報が見つからない場合の挙動(公式
    ドキュメント確認済み、記載無し)は未確認のため、でっち上げた
    フォールバックを用意せず`win32cred.CredRead()`の`pywintypes.
    error`(`ERROR_NOT_FOUND`)を素通りさせる(`GetRowItem`/
    `UpdateRowItem`の「不明な場合は自然な例外に委ねる」方針と同じ)
    ——`GetSecureCredentialNode`の`_win32_cred_read()`ヘルパー
    (例外を`None`へ変換、`Result`の計算に必要)は再利用しない。
    `AutosubmitTimeoutSeconds`(対話的ログインダイアログの自動確定
    タイマー、本トランスパイラは対話無しで直接`CredRead()`するため
    意味を持たない)・`OrchestratorCredentialName`/`TimeoutInSeconds`
    (実機2件とも`{x:Null}`)はモデル化しない——`CredentialsSource`が
    `"CredentialsManager"`以外(`"Orchestrator"`、公式ドキュメント確認
    済みの別の選択肢だが実機未確認、Orchestrator接続が必要な既存の
    除外カテゴリ)の場合は`# TODO`へ倒す。"""

    credential: Expr = None
    credential_name: Expr = None
    credentials_source: str | None = None
    orchestrator_credential_name: Expr = None
    display_name: str | None = None


@dataclass
class LoadImageNode:
    """`<ui:LoadImage FileName="..." Image="..." />`(知見178、GitHub
    code searchで58件ヒット)。`UiPath/skills`公式リポジトリの
    Studio実機ground-truthコーパス(`UiPath.UIAutomation.Activities/
    25.10/LoadImage.xaml`)+実機3件(`cameronmcnz/uipath-tutorials`・
    `pdmorale/OCR_Statistics`・`tosigoto/UiPath-SimpleOCR`、いずれも
    OCR活動への入力として使われる)で確認した構成は`FileName`(画像
    ファイルパス)+`Image`(出力、`UiPath.Core.Image`型)+`DisplayName`
    のみ——`ContinueOnError`はground-truth・実機のどちらでも一度も
    確認できなかった。

    `FileName`で指定したファイルから画像を読み込み`Image`へ代入する
    という意味論は、PythonのPillow(`PIL.Image.open()`)が標準的に
    サポートする操作そのもの——`pad_codegen/actions/ui_element.py`の
    `capture_as_image()`(pywinautoがPIL Imageを返す)で本プロジェクト
    が既にPillowを確認済みの依存として使っているため、新しい依存の
    追加判断は不要。`PIL.Image.open()`はファイルが存在しない/画像
    として読めない場合に例外を投げる標準的な挙動のままにする(UiPath
    側の失敗時挙動を独自に模倣するような分岐は追加しない)。"""

    file_name: Expr = None
    image: Expr = None
    display_name: str | None = None


@dataclass
class LookupDataTableNode:
    """`<ui:LookupDataTable>`(知見196、GitHub code searchで197件ヒット
    ——知見195で再調査したDataTable操作ファミリーの中で最も構造的に
    単純と判断した候補)。`UiPath/skills`公式リポジトリのStudio実機
    ground-truthコーパス+実機(`PacktPublishing/Robotic-Process-
    Automation-RPA-for-Developers`)で確認した構成は`DataTable`+
    `LookupColumnName`+`LookupValue`+`TargetColumnName`+`CellValue`
    (出力、実機では`<ui:LookupDataTable.CellValue><OutArgument
    x:TypeArguments="ui:GenericValue">...`というプロパティ要素形)+
    `RowIndex`(出力、実機では`[rowIndex]`というフラット属性形)。
    `LookupColumnIndex`/`TargetColumnIndex`(列インデックス直接指定)・
    `LookupDataColumn`/`TargetDataColumn`(DataColumnオブジェクト参照、
    未モデル化)はground-truthにのみ存在し実機での使用例を一度も確認
    できなかった——設定時は常に`# TODO`へ倒す。

    「単一のセル値+単一の行インデックスを返すだけで、DataTable全体を
    読み直したり再構築したりしない」という点で、知見179が指摘した
    `DataTable`表現の非統一性問題(dict行/list行/空リストが活動ごとに
    混在)の影響を受けにくい——`row[column_name]`という名前ベースの
    アクセス(知見183の`GetRowItem`の`ColumnName`分岐と同じ、dict行を
    前提にした素直な実装)で対応する。公式ドキュメントで確認済み:
    `LookupValue`が見つからない場合`RowIndex`は`-1`を返す(Excelの
    VLOOKUPに類似した挙動)。"""

    display_name: str | None = None
    data_table: Expr = None
    lookup_column_name: Expr = None
    lookup_column_index: Expr = None
    lookup_data_column: Expr = None
    lookup_value: Expr = None
    target_column_name: Expr = None
    target_column_index: Expr = None
    target_data_column: Expr = None
    cell_value: Expr = None
    row_index: Expr = None


@dataclass
class SortDataTableNode:
    """`<ui:SortDataTable>`(知見206、知見195で`FilterDataTable`/
    `JoinDataTables`と共に「列名ベースの値アクセスが本質的に必要」として
    保留した3件の1件。知見203の`ScopeInfo.data_table_columns`
    アーキテクチャが整った今、対象`DataTable`の行表現(dict行か否か)が
    確認できる場合に限り実装できる)。ground-truth(`UiPath.System.
    Activities/25.10`)の属性構成は`ColumnIndex`/`ColumnName`/
    `DataColumn`(列指定の3択)+`DataTable`+`OutputDataTable`+
    `SortOrder`(既定`"Ascending"`)。

    実機2件(`PacktPublishing/Robotic-Process-Automation-RPA-for-
    Developers`・`ShonHarsh/RPADev-S06P01-GetAndSortData-
    WindowsLegacy`)で検証した結果、知見195が発見した`SortOrder`→
    `Order`という別名の実在(片方は`Order`のみ、もう片方は`Order`と
    `SortOrder`を**両方同時に**同じ値で持つ——おそらくStudioの
    シリアライズ形式の版差)を再確認、`"Decending"`(誤字)という値も
    再確認した。`ColumnName`のみが両実機サンプルで使われており
    (`ColumnIndex`/`DataColumn`は実機で非`{x:Null}`の値を一度も確認
    できず、`LookupDataTableNode`の`LookupColumnIndex`/
    `LookupDataColumn`と同じ理由で未対応)、`OutputDataTable`は両方の
    実機サンプルで`DataTable`とは別変数が指定されていた(=
    インプレースではなく新しいDataTableを生成する——.NETの
    `DataView`ベースソートの挙動に合致)。

    `ColumnName`指定時のみ対応し、`ScopeInfo.data_table_columns`に
    対象`DataTable`変数が登録されている(=`BuildDataTable`/
    `ExcelReadRange(AddHeaders=True)`由来と確認できた)場合に限り
    `sorted(DataTable, key=lambda row: row[ColumnName], ...)`を
    生成する。登録が無い場合は「list行の可能性を排除できない」として
    `# TODO`へ倒す——知見205で実証した「表現非依存で安全という思い込みが
    実行時バグになる」教訓をここでも適用する。"""

    display_name: str | None = None
    data_table: Expr = None
    output_data_table: Expr = None
    column_name: Expr = None
    column_index: Expr = None
    data_column: Expr = None
    sort_order: str | None = None


@dataclass
class FilterOperationArgument:
    """`<ui:FilterOperationArgument>`(知見207、`FilterDataTableNode.
    filters`の1要素)。実機3件(`PacktPublishing/Robotic-Process-
    Automation-RPA-for-Developers`・`cameronmcnz/uipath-tutorials`・
    `allenlooplee/RPABook`)で確認した構成: `BooleanOperator`(確認済み
    "And"のみ)+`Operator`(確認済み"EQ"/"GTE"/"EMPTY"の3種)+`Column`
    (プロパティ要素形の`InArgument`、`x:TypeArguments`が`x:String`なら
    列名・`x:Int32`なら列インデックスの2通りを実機で確認)+`Operand`
    (比較値、`EMPTY`では未設定)。"""

    boolean_operator: str | None = None
    operator: str | None = None
    column: Expr = None
    column_type: str | None = None
    operand: Expr = None


@dataclass
class FilterDataTableNode:
    """`<ui:FilterDataTable>`(知見207、知見195で「列名ベースの値
    アクセスが本質的に必要」として保留した3件の1件。知見206の
    `SortDataTable`と同じ`ScopeInfo.data_table_columns`で解消する)。
    ground-truth(`UiPath.System.Activities/25.10`)の属性構成は
    `DataTable`+`Filters`+`OutputDataTable`+`SelectColumns`+
    `SelectColumnsMode`(既定`"Remove"`)に加え、実機で`FilterRowsMode`
    (確認済み"Keep"/"Remove"の両方)という追加属性を発見した。

    実機3件で`OutputDataTable`が`DataTable`と**同じ変数**を指定する
    ケース(インプレース上書き、2/3件)と**別の変数**を指定するケース
    (1/3件)の両方を確認した——知見206の`SortDataTable`とは違い、
    インプレース上書きが実際に使われている。`SelectColumns`は3/3件中
    2件で「未選択」(`<x:Null/>`という単一null要素のリスト、Studioの
    シリアライズ上の「空リスト」の表現)、1件で実際の列名3件
    (`SelectColumnsMode="Keep"`と組み合わせ)を指定していた——後者の
    列選択(列の投影)は本活動では未対応のまま`# TODO`へ倒す(対応する
    `Filters`条件のみが今回の実装範囲)。"""

    display_name: str | None = None
    data_table: Expr = None
    output_data_table: Expr = None
    filter_rows_mode: str | None = None
    select_columns_mode: str | None = None
    filters: list[FilterOperationArgument] = field(default_factory=list)
    select_columns: list[Expr] = field(default_factory=list)


@dataclass
class JoinOperationArgument:
    """`<ui:JoinOperationArgument>`(知見208、`JoinDataTablesNode.
    arguments`の1要素)。実機3件(`TharakaMadushankaWanshathilaka/
    UiPath-Demo-Data-Tables`・`SuatOzcan/UiPathRoboticProcessAutomation`
    のVB実機2件+`ShonHarsh/RPADev-S04P02-...`のC#実機1件)で確認した
    構成: `BooleanOperator`(確認済み"And"のみ)+`Operator`(確認済み
    "EQ"のみ)+`Column1`/`Column2`(プロパティ要素形の`InArgument`、
    実機では`x:TypeArguments="x:String"`のみ確認——`FilterOperationArgument`
    と違い列インデックス(`x:Int32`)の実例は未確認)。`Operand`に対応する
    属性は無い(Joinでは比較対象が`Column2`であり定数値ではないため)。"""

    boolean_operator: str | None = None
    operator: str | None = None
    column1: Expr = None
    column1_type: str | None = None
    column2: Expr = None
    column2_type: str | None = None


@dataclass
class JoinDataTablesNode:
    """`<ui:JoinDataTables>`(知見208、知見195で保留した3件のうち最後の
    1件。知見206/207と同じ`ScopeInfo.data_table_columns`で解消する)。
    ground-truthの属性構成は`Arguments`+`DataTable1`+`DataTable2`+
    `OutputDataTable`+`JoinType`(既定`"Inner"`)。

    `JoinType`の値は公式ドキュメント(`docs.uipath.com/activities/
    other/latest/workflow/join-data-tables`)で確認: `"Inner"`(条件に
    一致する行のみ)・`"Left"`(`DataTable1`の全行を保持、一致しない
    `DataTable2`側はNull)・`"Full"`(両方の全行を保持、一致しない側は
    Null)——実機3件は全て`"Inner"`のみ確認、`"Left"`/`"Full"`は実機
    未確認のため未対応。

    **出力列の重複名解決規則(公式ドキュメントで確認)**: `DataTable2`側
    の列名が`DataTable1`(または既にリネーム済みの他の`DataTable2`列)
    と重複する場合、`_1`→`_2`→...という未使用の連番サフィックスを
    付与する(例: `DataTable1`に`ID`/`ID_1`/`ID_2`があり`DataTable2`に
    `ID`がある場合、`DataTable2`の`ID`は`ID_3`になる)。実機3件全てが
    両テーブルに同名の結合キー列(`"ID"`)を持つため、この規則は
    必須——実装時に直接検証した。"""

    display_name: str | None = None
    data_table1: Expr = None
    data_table2: Expr = None
    output_data_table: Expr = None
    join_type: str | None = None
    arguments: list[JoinOperationArgument] = field(default_factory=list)


@dataclass
class RemoveDuplicateRowsNode:
    """`<ui:RemoveDuplicateRows>`(知見214、知見206-208と同じ
    `ScopeInfo.data_table_columns`DataTable操作系、知見213のタグ名
    限定GitHub検索(`"ui:RemoveDuplicateRows"`)で再発掘)。ground-truth
    +実機2件(`cameronmcnz/uipath-tutorials`の`DedupeExcel/Main.xaml`・
    `mennatullahra/UiPath-ExcelDataManipulation`)で確認した構成は
    `DataTable`+`OutputDataTable`のみ——列選択やオプション属性は一切
    無い、`SortDataTable`/`FilterDataTable`/`JoinDataTables`より単純。
    両実機とも`OutputDataTable`が`DataTable`と同じ変数(インプレース
    上書き)。

    全列の値が完全一致する行を重複として除去し、最初に出現した行を
    残す(.NET`DataTable`の標準的な重複行判定——列の部分一致ではなく
    全列一致)。`ScopeInfo.data_table_columns`で対象`DataTable`がdict
    行と確認できる場合のみ、各行の`dict.values()`(列名→値の順序は
    `BuildDataTable`由来の既存のdict構築規約で常に一定)をキーとして
    重複判定する。"""

    display_name: str | None = None
    data_table: Expr = None
    output_data_table: Expr = None


@dataclass
class SaveImageNode:
    """`<ui:SaveImage FileName="..." Image="..." />`(知見179、
    `LoadImageNode`(知見178)の正反対の操作)。`UiPath/skills`公式
    リポジトリのStudio実機ground-truthコーパス(`UiPath.UIAutomation.
    Activities/25.10/SaveImage.xaml`)+実機確認(`UiPath/Community.
    Activities`公式リポジトリのREFramework標準テンプレート
    `Templates/ReFrameWork/Framework/TakeScreenshot.xaml`で
    `ui:TakeScreenshot`(知見179で対)と組になって使われる、例外発生時
    のスクリーンショット保存フロー)で確認した構成は`FileName`+
    `Image`+`DisplayName`のみ——`ContinueOnError`はどちらでも一度も
    確認できなかった(`LoadImage`と全く同じ属性構成)。

    `Image`(既存の`PIL.Image`オブジェクト変数)を`FileName`で指定した
    パスへ保存するという意味論は、Pillowの`Image.save()`
    (`LoadImage`の`PIL.Image.open()`と対になる標準API)が直接対応する。"""

    file_name: Expr = None
    image: Expr = None
    display_name: str | None = None


@dataclass
class TakeScreenshotNode:
    """`<ui:TakeScreenshot>`(知見179、`UiPath/Community.Activities`
    公式リポジトリのREFramework標準テンプレート`Templates/ReFrameWork/
    Framework/TakeScreenshot.xaml`——例外発生時にスクリーンショットを
    撮って保存する、REFrameworkの標準エラーハンドリングフローの一部、
    知見169の`KillAllProcesses.xaml`と同じ「REFramework標準サブ
    ワークフロー」カテゴリ)で確認。実機3件(`mihhdu/Enhanced-
    REFramework`・`PacktPublishing/Robotic-Process-Automation-
    Projects`・`spritlesoftware/Uipath-RPA-AutomationProjects`)でも
    同じ構成を確認した——`Target`(セレクタ、実機の大半は`{x:Null}`で
    「画面全体」を意味する)+`WaitBefore`(`DelayBefore`とは別名の
    未確認属性、実機で非`{x:Null}`の値を一度も確認できず意味論未確認)
    +`Screenshot`(出力、`ui:Image`型変数)+`DisplayName`。

    `Target`が`{x:Null}`の場合は「画面全体のスクリーンショット」を
    意味し、Pillowの`ImageGrab.grab()`(引数無しで仮想スクリーン全体を
    キャプチャする標準API)が直接対応する。`Target`にセレクタが設定
    されている場合は、pywinautoの`capture_as_image()`(`base_wrapper.
    py`で確認済み、`rectangle()`で取得した矩形をPILでキャプチャして
    返す標準API——`pad_codegen`側で既に確認済みの依存)が対応する。
    `WaitBefore`は意味論未確認のため、非`{x:Null}`の場合は`# TODO`へ
    倒す(`DelayBefore`と同一視するのは、名前が違う以上は安全な
    仮定ではないため)。"""

    selector: str | None = None
    wait_before: Expr = None
    screenshot: Expr = None
    display_name: str | None = None


@dataclass
class GetOcrTextNode:
    """`<ui:GetOCRText>`(知見180、`UiPath/skills`公式リポジトリの
    Studio実機ground-truthコーパス(`UiPath.UIAutomation.Activities/
    25.10/GetOCRText.xaml`)+実機4件(`cameronmcnz/uipath-tutorials`・
    `PacktPublishing/Robotic-Process-Automation-RPA-for-Developers`・
    `DongJoonHan/RPA`)で確認)。`OCREngine`プロパティが`ActivityFunc`
    デリゲート(`Argument`は常にキャプチャした`Image`)でラップした
    別のOCR活動を保持する——実機確認した全例でそのタグは`ui:
    GoogleOCR`(属性`Language`/`Scale`/`Profile`/`AllowedCharacters`/
    `DeniedCharacters`/`Invert`/`ComputeSkewAngle`/`ExtractWords`/
    `FilterRegion`を持つ)。

    `ui:GoogleOCR`という紛らわしいタグ名(実機で`DisplayName="Tesseract
    OCR"`になっている例を複数確認)は、UiPath公式ドキュメント
    (docs.uipath.com/activities/other/latest/ui-automation/google-ocr)
    で明確に確認した——内部クラス名`UiPath.Core.Activities.GoogleOCR`
    のまま、ドキュメント上は「Tesseract OCR」(Tesseract OCR Engine
    4.0使用)と記載されている歴史的な命名の名残で、Google Cloud Vision
    とは**別の**活動(`GoogleCloudVisionOCR`という別タグが存在)。
    `MicrosoftOCR`(実機71件確認——Windows OCR API、Tesseractとは別の
    エンジン)等、`GoogleOCR`以外のタグは未確認のため対応しない。

    本プロジェクトは`pytesseract`(`tests/test_ocr_fallback.py`で実機
    VM検証済みの既存確認済み依存——`pytesseract.image_to_string()`が
    直接対応する)を既に使っているため、`GoogleOCR`=Tesseract OCRという
    対応は新しい依存の追加判断無しに実現できる。`Language`(UiPath公式
    ドキュメントが明記する`tessdata`言語コード接頭辞、例: `"eng"`/
    `"fra"`——`pytesseract.image_to_string(img, lang=...)`の`lang`
    引数と全く同じ語彙)は信頼して渡せるが、`Scale`/`Profile`/
    `AllowedCharacters`/`DeniedCharacters`/`Invert`/
    `ComputeSkewAngle`/`FilterRegion`(いずれも画像の前処理を変える
    属性で、対応するPython側の変換が未確認)が既定値から外れている
    場合、`ExtractWords`(`True`の場合は`WordsInfo`側に単語位置情報が
    必要になるが未モデル化)が`True`の場合、`WordsInfo`出力自体が
    使われている場合は、いずれも`# TODO`へ倒す。"""

    selector: str | None = None
    engine_tag: str | None = None
    language: Expr = None
    scale: str | None = None
    profile: str | None = None
    allowed_characters: Expr = None
    denied_characters: Expr = None
    invert: str | None = None
    compute_skew_angle: str | None = None
    extract_words: str | None = None
    filter_region: Expr = None
    text: Expr = None
    words_info: Expr = None
    display_name: str | None = None


@dataclass
class ReadPDFWithOCRNode:
    """`<ui:ReadPDFWithOCR>`(知見266、`GetOcrTextNode`(知見180)と同じ
    `OCREngine`/`ActivityFunc`デリゲート構造を再利用する活動、タグ名
    限定GitHub検索で273件ヒット——10回目発見パスの最後の未着手候補)。
    実機6件(`piyushagarwal08/JU-Notes`・`vajrang-b/UiPathIn30Days`
    複数件・`PacktPublishing/Robotic-Process-Automation-RPA-for-
    Developers`・`spritlesoftware/Uipath-RPA-AutomationProjects`)で
    確認した構成——`FileName`(入力PDFパス)、`Range`(`"All"`または
    単一ページ番号の静的リテラル、例`"6"`/`"2"`——公式ドキュメント確認
    済みでは`"7-12"`等のハイフン範囲・`"2-5, 7, 15-End"`等の複合範囲も
    存在するが実機では一度も確認できず`ExtractPdfPageRangeNode`
    (知見200)と同じ「確認済みの単純な形のみ対応」判断)、`Text`
    (出力)、`ImageDpi`(実機確認済みの値は常に`"150"`、省略時は
    `ExportPdfPageAsImageNode`(知見209)と同じ既定値150を採用する
    ——本トランスパイラ独自の推定であり公式の既定値確認ではない)、
    `DegreeOfParallelism`(並列度のパフォーマンスヒント、最終的な
    テキスト出力の正しさには影響しないため捕捉対象に含めない)。

    `OCREngine`は`GetOcrTextNode`と全く同じ`ActivityFunc`デリゲート
    構造(`Argument`は常にキャプチャした`Image`)で別のOCR活動を保持
    する——実機6件中5件で`ui:GoogleOCR`(DisplayName「Tesseract OCR」、
    知見180で確認済みの`pytesseract`マッピング)、残り2件
    (`piyushagarwal08`・`spritlesoftware`)で`ui:MicrosoftOCR`
    (知見180で既に別エンジンとして確認済み、Tesseractとは異なる
    OCRエンジンのため未対応)——`GoogleOCR`以外のタグは`GetOcrTextNode`
    と同じ理由で`# TODO`へ倒す。埋め込まれた`ui:GoogleOCR`自体の
    サブ属性(`Language`/`Scale`/`Profile`/`AllowedCharacters`/
    `DeniedCharacters`/`Invert`/`ComputeSkewAngle`/`ExtractWords`/
    `FilterRegion`)は実機確認した全件で確認済みの既定値のみのため、
    `GetOcrTextNode`と同じ決定境界をそのまま再利用する。

    `pymupdf`(`pdf-render`プラグイン、知見209で既に確認済みの依存)の
    `Pixmap.pil_image()`(PILの`Image`オブジェクトへ直接変換する公式
    API、インストール済みの実`pymupdf`で動作確認済み)で各ページを
    ラスタライズし、`GetOcrTextNode`が確立した`pytesseract.
    image_to_string()`へそのまま渡す——複数ページの結果は`"\n"`で
    連結する(ページ区切りの直列化規約は公式ドキュメント・実機いずれ
    にも記載が無いため、`WordReadTextNode`(知見258)の段落結合と同じ
    本トランスパイラ独自の推定)。"""

    file_name: Expr = None
    range: Expr = None
    text: Expr = None
    image_dpi: Expr = None
    engine_tag: str | None = None
    language: Expr = None
    scale: str | None = None
    profile: str | None = None
    allowed_characters: Expr = None
    denied_characters: Expr = None
    invert: str | None = None
    compute_skew_angle: str | None = None
    extract_words: str | None = None
    filter_region: Expr = None
    display_name: str | None = None


@dataclass
class AddDataRowNode:
    """`<ui:AddDataRow>`(知見181、GitHub code searchで2120件ヒット
    ——`BuildDataTable`(既存)の直後に続く定番パターンとして極めて
    高頻度)。実機4件(`cameronmcnz/uipath-tutorials`・`allenlooplee/
    RPABook`・`piyushagarwal08/JU-Notes`)で確認した属性は`ArrayRow`
    (VB配列リテラル、例: `[{"Hello World", -1}]`——`uipath_expr`の
    `ArrayLiteral`が既に`render_expr`で`[item1, item2, ...]`という
    Pythonリストへ変換する確立済みの経路、新しい式パーサー対応は不要)
    +`DataRow`(既存の`System.Data.DataRow`オブジェクト参照、実機で
    一度も非`{x:Null}`の値を確認できず意味論未確認・未モデル化)+
    `DataTable`(追記先の既存DataTable変数)+`DisplayName`。

    `FilterDataTable`等(知見179で検討し見送った、`DataTable`表現の
    非統一のため活動単体では実行時表現を判断できないDataTable操作系)
    とは違い、本活動は既存のDataTable変数の**内容を読む**必要が無い
    (列名・既存の行表現を一切参照せず、単純に新しい行を末尾に追加
    するだけ)——`list.append(...)`はPythonの素のlistが何を保持して
    いても安全に呼べる。

    知見205追記: 当初は`ArrayRow`をそのままlist行として追加していた
    (`dt.append([val1, val2])`)が、これは同じ`DataTable`を後で読む
    他の活動(`LookupDataTable`/`GetRowItem.ColumnName`等、いずれも
    dict行を前提にした`row[列名]`直接アクセス)が`TypeError`で実行時に
    落ちる実在のバグを生んでいた——「表現非依存で安全」という当初の
    判断は、単体では正しいが他の活動との組み合わせでは不十分だった。
    知見203の`ScopeInfo.data_table_columns`(同じ`DataTable`変数が
    `BuildDataTable`で確認済みの列名を持つと分かる場合)が使える場合は
    `dict(zip(columns, array_row))`としてdict行を追加し、列名が
    分からない場合のみ従来通りlist行のまま追加する(安全側の
    フォールバック)。"""

    array_row: Expr = None
    data_row: Expr = None
    data_table: Expr = None
    display_name: str | None = None


@dataclass
class RemoveDataRowNode:
    """`<ui:RemoveDataRow>`(知見182、`AddDataRow`(知見181)の正反対)。
    `UiPath/skills`公式リポジトリのStudio実機ground-truthコーパス
    (`UiPath.System.Activities/25.10/RemoveDataRow.xaml`)+実機5件
    (`lin8231/762-impl`・`samaypatel27/Stock-Market-Scrapper`・
    `UiPath-Services/OrchestratorManager`)で確認した構成は`DataTable`
    +`Row`(既存の`DataRow`オブジェクト参照、実機確認した非`{x:Null}`
    の実例は複雑なLINQ式`io_UsersData.AsEnumerable().Where(Function
    (Row) ...).First()`——`uipath_expr`が未対応のため安全に`# TODO`へ
    倒れる)+`RowIndex`(整数インデックス、実機2件で`"0"`——「読み込んだ
    ヘッダー行を削除する」という定番パターンで使われる)。

    `AddDataRow`と同じ理由で、`RowIndex`による削除(`del
    {data_table}[{row_index}]`)は`DataTable`変数の実行時表現(dict行/
    list行)を一切問わない安全な操作——インデックス位置で削除する
    だけで、要素の内部構造を読む必要が無い。`Row`が設定されている
    場合は`{data_table}.remove({row})`(Pythonの`list.remove()`は
    最初に一致する要素を削除する、オブジェクト等価性さえ合えば
    内部表現を問わず安全)を試みるが、実機で確認した唯一の非`{x:Null}`
    の実例は`uipath_expr`が未対応のLINQ式のため、結局は安全に
    `# TODO`へ倒れる。"""

    data_table: Expr = None
    row: Expr = None
    row_index: Expr = None
    display_name: str | None = None


@dataclass
class GetRowItemNode:
    """`<ui:GetRowItem>`(知見183、`UiPath/skills`公式リポジトリの
    Studio実機ground-truthコーパス(`UiPath.System.Activities/25.10/
    GetRowItem.xaml`)+実機6件(`cameronmcnz/uipath-tutorials`・
    `allenlooplee/CloudOcrActivitiesPack`・`ShonHarsh/RPADev-...`)で
    確認)。既存の1行(`Row`、通常は`ForEach`のループ変数——`AddDataRow`
    (知見181)/`RemoveDataRow`(知見182)とは違い、本活動は行の**内容を
    読む**必要がある側)から1つの値を取り出す。列の指定方法は`Column`
    (既存の`DataColumn`オブジェクト参照、未モデル化)/`ColumnIndex`
    (整数)/`ColumnName`(文字列)の3種類——実機6件全てが`ColumnName`
    を使っており、`ColumnIndex`の実例は本調査で一度も確認できなかった。

    `ColumnIndex`は`DataTable`変数の実行時表現(dict行/list行)を
    問わない安全な2経路のコードを生成できる——`isinstance(row, dict)`
    の分岐で、dict行なら`list(row.values())[idx]`(位置で値を取る)、
    list行なら`row[idx]`(素の添字アクセス)のいずれかを実行時に選ぶ
    (`AddDataRow`/`RemoveDataRow`の「読まずに済ませる」安全策とは別の
    「両方の表現に対応するコードを生成する」という新しい安全策)。

    `ColumnName`は列名でのアクセスのため、dict行(`AddHeaders=True`
    のExcel読込由来)でなければ意味を成さない——実際のUiPath
    `DataTable`は常に列名を持つため、本トランスパイラがdict行として
    表現した場合にのみ`row[column_name]`が正しく動作する。list行
    表現(`BuildDataTable`/`AddHeaders=False`由来)の場合は`KeyError`
    (dictではないため実際には`TypeError`)で実行時に大きく失敗する——
    知見177の「でっち上げた値で静かに間違えるより、失敗する方が安全」
    という方針と同じ理由で、`row[column_name]`という直接アクセスを
    選んだ(でっち上げた値を返すのではなく、表現が食い違う場合は
    即座に例外で知らせる)。"""

    row: Expr = None
    column: Expr = None
    column_index: Expr = None
    column_name: Expr = None
    value: Expr = None
    display_name: str | None = None


@dataclass
class UpdateRowItemNode:
    """`<ui:UpdateRowItem>`(知見216、`GetRowItem`(知見183)の対になる
    書き込み側、知見215のタグ名限定GitHub検索(`"ui:UpdateRowItem"`)で
    再発掘)。ground-truthの属性構成は`ColumnIndex`+`ColumnName`+
    `Row`+`Value`——`Column`(`DataColumn`オブジェクト参照)は無い。
    実機2件(`Andrew-SOA/Loan_Approval`のVB実機3箇所・`Anusha-TX/
    TestAutomation`のC#実機13箇所)で確認した構成は`ColumnName`
    (VB実機、文字列フラット属性)/`ColumnIndex`(C#実機のみ、数値
    フラット属性——VB実機では一度も非`{x:Null}`の値を確認できず)の
    両方。`Row`は`ForEachRow`のループ変数(`[i_DataRow]`)、`Value`は
    任意のVB式。

    `GetRowItem`と全く同じ理由(知見177・183の「でっち上げた値で
    静かに間違えるより、失敗する方が安全」という方針)で、
    `ColumnName`指定時は`row[column_name] = value`という直接代入を
    選ぶ——list行表現の場合は`TypeError`で実行時に即座に失敗する
    (静かに間違った動作をしない)。`ColumnIndex`指定時は`GetRowItem`
    と同じdict/list両対応だが、位置で値を**書き込む**ため
    `list(row.keys())[idx]`で該当キーを求めてから代入する(dict行の
    場合)/`row[idx] = value`(list行の場合)という2経路に分岐する。"""

    row: Expr = None
    column: Expr = None
    column_index: Expr = None
    column_name: Expr = None
    value: Expr = None
    display_name: str | None = None


@dataclass
class ClearDataTableNode:
    """`<ui:ClearDataTable DataTable="..." />`(知見184、GitHub code
    searchで225件ヒット)。`UiPath/skills`公式リポジトリのStudio実機
    ground-truthコーパス(`UiPath.System.Activities/25.10/
    ClearDataTable.xaml`)+実機3件(`MaxineXiong/Scraping-PDF-Invoices-
    with-RPA`・`jeffdnganga/DSRIncentivesPostingPerformer`)で確認した
    構成は`DataTable`のみ——`DisplayName`以外に属性は一切無い、本調査
    で遭遇した中でも最も単純な活動の1つ。

    `AddDataRow`(知見181)/`RemoveDataRow`(知見182)と同じ理由で、
    全ての行を削除する(`list.clear()`)という操作は`DataTable`変数の
    実行時表現を一切問わない安全な操作——要素を読む必要すら無い。"""

    data_table: Expr = None
    display_name: str | None = None


@dataclass
class OutputDataTableNode:
    """`<ui:OutputDataTable>`(知見184、GitHub code searchで894件
    ヒット)。`UiPath/skills`公式リポジトリのStudio実機ground-truth
    コーパス+実機2件(`piyushagarwal08/JU-Notes`・`vajrang-b/
    UiPathIn30Days`)で確認した構成は`DataTable`+`Text`(出力)+
    `DisplayName`のみ。UiPath公式ドキュメント(docs.uipath.com、
    WebSearchで確認)によれば、`DataTable`をCSV形式の文字列へ変換する
    活動——区切り文字・引用符の扱い・改行コードといった厳密な書式の
    詳細まではドキュメントで確認できなかったため、Python標準の`csv`
    モジュール(確認済みの標準ライブラリ、RFC4180準拠のCSVを生成する)
    で近似する——`GetFullText`(知見159)と同じ「公式ドキュメントで
    確認した大枠の挙動は確信を持って実装するが、厳密な書式の細部は
    未確認として`# WARNING`に残す」という判断パターン。

    `GetRowItem`(知見183)と同じ`isinstance(row, dict)`の実行時分岐で
    `DataTable`変数の両表現(dict行/list行)に対応する——dict行の場合は
    先頭行のキーをヘッダー行として出力し、list行の場合はヘッダー無し
    で値のみを出力する。"""

    data_table: Expr = None
    text: Expr = None
    display_name: str | None = None


@dataclass
class AddDataColumnNode:
    """`<ui:AddDataColumn>`(知見198、GitHub code searchで856件ヒット
    ——知見195で3番目に有望と評価したDataTable操作系候補)。実機2件
    (`HarshadRanganathan/uipath-learning`・`Its-Nishant-10/
    book_scraping`)で確認した構成は`ColumnName`+`DataTable`+
    `x:TypeArguments`(列の.NET型、実機は全件`x:Object`、Pythonには
    対応する型強制が無いためモデル化不要)+`Column`(DataColumnオブジェクト
    参照、未モデル化)+`DefaultValue`+`AllowDBNull`/`AutoIncrement`/
    `MaxLength`/`Unique`(列スキーマ制約)。実機では全て`{x:Null}`の例
    (`Its-Nishant-10`)と、`AllowDBNull="True"`/`AutoIncrement="False"`/
    `MaxLength="100"`/`Unique="False"`という明示的な値の例
    (`HarshadRanganathan`)の両方を確認した。

    知見183の`isinstance(row, dict)`判定(`GetRowItem`)を初めて
    「読み取り」ではなく「既存の全行への書き込み(列の追加)」という
    文脈で使う——dict行の場合のみ、各行に`ColumnName`キー(値は
    `DefaultValue`、未設定なら`None`)を追加する。list行表現の場合は
    何もしない(列の並び順を追跡していないため安全に対応できない)
    ——`GetRowItem`等の既存の読み取り専用のisinstance分岐と違い、
    非dict行では意図的に何もしないという一方向の対応であることを
    生成コードに`# WARNING`コメントで明記する。`AutoIncrement="True"`
    (自動連番割り当て、未確認)・`Unique="True"`(一意性制約の実施、
    未確認)・`AllowDBNull="False"`(既存行へのNOT NULL制約の実施、
    未確認)は常に`# TODO`へ倒す——`MaxLength`は列の追加操作自体には
    影響しない(値の代入時のみ関係する制約で、本トランスパイラは
    どの代入にも文字数制限を課していないため)ためTODO化せず無視する。"""

    display_name: str | None = None
    data_table: Expr = None
    column_name: Expr = None
    column: Expr = None
    default_value: Expr = None
    allow_db_null: str | None = None
    auto_increment: str | None = None
    unique: str | None = None


@dataclass
class RemoveDataColumnNode:
    """`<ui:RemoveDataColumn>`(知見198、GitHub code searchで273件
    ヒット、`AddDataColumn`の正反対)。実機2件(`cameronmcnz/uipath-
    tutorials`・`UiPathJapan/samples`)で確認した構成は`ColumnName`+
    `DataTable`のみ——`Column`(DataColumnオブジェクト参照)・
    `ColumnIndex`(列インデックス直接指定)はground-truth・実機のどちら
    でも非null値を一度も確認できなかった。

    `AddDataColumn`(同知見198)と対になる実装——dict行の場合のみ
    `ColumnName`キーを`dict.pop(key, None)`(キーが無くても安全)で
    削除する。list行表現の場合は何もしない(同じ理由、`# WARNING`
    コメントで明記)。`Column`/`ColumnIndex`が設定されている場合は
    常に`# TODO`へ倒す。"""

    display_name: str | None = None
    data_table: Expr = None
    column_name: Expr = None
    column: Expr = None
    column_index: Expr = None


@dataclass
class ReadCsvFileNode:
    """`<ui:ReadCsvFile>`(知見185、`UiPath.Excel.Activities`名前空間、
    GitHub code searchで657件ヒット)。`UiPath/skills`公式リポジトリの
    Studio実機ground-truthコーパス(`UiPath.Excel.Activities/3.4/
    ReadCsvFile.xaml`)+実機4件(`cameronmcnz/uipath-tutorials`・
    `allenlooplee/RPABook`・`HarshadRanganathan/uipath-learning`)で
    確認した構成は`FilePath`+`DataTable`(出力)+`PathResource`
    (Integration Service連携用リソース、未モデル化)+`Delimitator`
    (UiPathの実際のAPI表記そのまま——`Delimiter`ではなく`Delimitator`、
    実機確認した値は全件`"Comma"`)+`Encoding`(実機で一度も非
    `{x:Null}`の値を確認できず意味論未確認)。`AddHeaders`相当の属性は
    存在しない——`ReadCsvFile`は常に1行目をヘッダーとして扱うと判断
    (CSV読込の標準的な挙動、`ExcelReadRange`の`AddHeaders=True`時
    (知見115)と同じdict行表現に揃える)。

    `csv.DictReader`(Python標準の`csv`モジュール)がこの意味論に
    直接対応する——`OutputDataTable`(知見184)と同じ、確認済みの
    標準ライブラリによる近似。`Delimitator="Comma"`以外・`Encoding`
    設定時・`PathResource`設定時は`# TODO`へ倒す。"""

    file_path: Expr = None
    data_table: Expr = None
    path_resource: Expr = None
    delimitator: str | None = None
    encoding: Expr = None
    display_name: str | None = None


@dataclass
class ReadPdfTextNode:
    """`<ui:ReadPDFText>`(知見199、GitHub code searchで539件ヒット
    ——知見193で調査したPDF活動ファミリーの4番目に有望と評価した候補)。
    `UiPath/skills`公式リポジトリのStudio実機ground-truthコーパス
    (`UiPath.PDF.Activities/3.25/ReadPDFText.xaml`)+実機4件
    (`marcelocruzrpa/uipath-ai-skills`・`spritlesoftware/Uipath-RPA-
    AutomationProjects`・`PacktPublishing/Robotic-Process-Automation-
    RPA-for-Developers`)で確認した構成は`FileName`+`Text`(出力)+
    `Range`(確認した値は`"All"`と単一ページ番号`"2"`の2種)+
    `PreserveFormatting`(実機4件全て`{x:Null}`)。`Password`属性は
    ground-truth・実機のどちらにも存在しなかった(暗号化PDF対応は
    `ReadPDFText`自体には無く、別の`ManagePDFPassword`活動が担う設計
    ——知見193で確認済み)。

    `pypdf`(`pyproject.toml`で既に確認済みの依存——本リポジトリの
    PAD側`pad_action_lib/pdf_actions.py`の`extract_text_from_pdf()`で
    既に実戦投入済みの同じライブラリ)の`PdfReader.pages[i].
    extract_text()`が直接対応する。単一ページ番号の1始まり規約
    (`Range="2"`→`pages[1]`)は、同じPAD側`extract_text_from_pdf()`の
    `page_number - 1`という既存の確認済み変換を踏襲した——UiPath
    Studio実機で1始まりである直接の独立確認はできていないが、同じ
    会社の類似PDF活動2製品間での規約共有という合理的な推論であることを
    明記する。`Range`がハイフン区切りの範囲(例`"8-22"`、知見193で
    `ReadPDFText`自身ではなく兄弟活動`ExtractPDFPageRange`でのみ
    確認した形式)の**静的リテラル**である場合は、`ReadPDFText`自身
    での使用が未確認のため`# TODO`へ倒す——動的な式(`VbExpr`)の場合は
    実行時に`int()`の`ValueError`で自然に失敗させる(独自の事前検証は
    追加しない)。`PreserveFormatting`が非null値の場合は、レイアウト
    保持の挙動が未確認のため`# TODO`へ倒す。"""

    display_name: str | None = None
    file_name: Expr = None
    text: Expr = None
    range: Expr = None
    preserve_formatting: Expr = None


@dataclass
class GetPdfPageCountNode:
    """`<GetPDFPageCount>`(知見200、`upap:`名前空間——知見193で発見した
    `clr-namespace:UiPath.PDF.Activities.PDF;assembly=UiPath.PDF.
    Activities`、`ReadPDFText`等とは違い`http://schemas.uipath.com/...`
    形のURNではない)。実機2件(`Anusha-TX/Group1001_TestAutomation`・
    `vajrang-b/UiPathIn30Days`)で確認した構成は`FileName`+`PageCount`
    (出力)のみ。`FileName`のC#式言語実例(`CSharpValue`プロパティ要素形)
    は既存の`uipath_expr`VB.NET専用文法が正しく未対応として素通りする
    (知見129の既存の限界、本活動固有の問題ではない)。

    `len(pypdf.PdfReader(FileName).pages)`(`pyproject.toml`で既に確認
    済みの依存、PAD側`pad_action_lib/pdf_actions.py`の
    `extract_pages_to_new_pdf()`内で`len(reader.pages)`として既に
    使われている同じイディオム)が直接対応する。"""

    display_name: str | None = None
    file_name: Expr = None
    page_count: Expr = None


@dataclass
class ExtractPdfPageRangeNode:
    """`<ExtractPDFPageRange>`(知見200、`GetPDFPageCount`と同じ
    `upap:`名前空間)。実機`vajrang-b/UiPathIn30Days`で確認した構成は
    `FileName`+`OutputFileName`+`Range`(確認した実例は`"8-22"`という
    ハイフン区切りの単純な範囲のみ——PAD側の`ExtractPagesToNewPDF`
    活動が対応するカンマ区切りの複数範囲(`"1,3,5-10"`)はUiPath側の
    `ExtractPDFPageRange`で独立に確認できていないため、`N-M`形以外は
    `# TODO`へ倒す、別製品の文法を安易に輸入しない判断)。

    `pypdf.PdfReader`+`pypdf.PdfWriter`(`pad_action_lib/pdf_actions.py`
    の`extract_pages_to_new_pdf()`と同じ1始まりページ番号の変換)で
    該当ページを新しいPDFへ書き出す。"""

    display_name: str | None = None
    file_name: Expr = None
    output_file_name: Expr = None
    range: Expr = None


@dataclass
class JoinPdfNode:
    """`<JoinPDF>`(知見201、`GetPDFPageCount`/`ExtractPDFPageRange`
    (知見200)と同じ`upap:`名前空間)。`UiPath/skills`公式リポジトリの
    Studio実機ground-truthコーパス+実機(`vajrang-b/UiPathIn30Days`)
    で確認した構成は`FileList`+`OutputFileName`のみ——`Password`等の
    暗号化関連属性は一切無い。実機の`FileList="[{&quot;a.pdf&quot;,
    &quot;b.pdf&quot;}]"`はVB.NETの配列リテラル構文
    (`uipath_expr`が既に`ArrayLiteral`として対応済み、`render_expr`が
    Pythonの`list`リテラルへ変換することを確認済み——未対応だと思って
    知見195・pad_todo.mdの既存メモで保留していたが、実際には既に動く
    ことが分かった)。

    `pypdf.PdfWriter`(`pad_action_lib/pdf_actions.py`の
    `merge_pdf_files()`と同じ`writer.append(reader)`イディオム)で
    `FileList`の各パスを順に結合する。"""

    display_name: str | None = None
    file_list: Expr = None
    output_file_name: Expr = None


@dataclass
class ExportPdfPageAsImageNode:
    """`<ExportPDFPageAsImage>`(知見209、`GetPDFPageCount`/
    `ExtractPDFPageRange`/`JoinPDF`/`ManagePDFPassword`(知見200-202)と
    同じ`upap:`名前空間)。元々は知見193で「実機確証が薄い」として
    見送っていたが、本tickでGitHub検索を再実行したところ実機2件
    (`Sundsvallskommun/RPA_Sammanstallning-av-PDF`——実在のスウェーデン
    自治体のRPAリポジトリ・`vajrang-b/UiPathIn30Days`)で確証が得られ、
    着手した。両実機で確認した構成は`FileName`+`ImageDpi`(両実機とも
    `"150"`、ground-truthの既定値と一致)+`OutputFileName`+
    `PageNumber`(単一ページ番号のみ、動的な`[Index]`/静的な`"1"`の両方
    を確認——`ExtractPDFPageRange`のようなハイフン区切り範囲は無い)。

    実装には本リポジトリに無いPDFページラスタライズ用ライブラリが必要
    (`pypdf`はテキスト/構造抽出のみで画像描画は出来ない)。ユーザーと
    相談し、全ユーザーに強制する本体`dependencies`への追加ではなく、
    `pyproject.toml`の`[project.optional-dependencies]`
    `pdf-render`グループ(`pymupdf`)という「プラグイン」依存として
    追加する方針にした(知見209の設計判断、詳細は`design/
    uipath_transpiler_roadmap.md`の該当エントリ参照)。生成コード自体は
    `pypdf`と同じ既存の設計(`_collect_imports`がbody文字列から
    `pymupdf.open(`の出現を検出して`import pymupdf`を注入)を踏襲する
    ——トランスパイラ本体(`uipath_codegen`)はこのライブラリを一切
    importしない、コード生成時に文字列として埋め込むだけ。

    `pymupdf.open(FileName)[PageNumber - 1].get_pixmap(dpi=ImageDpi).
    save(OutputFileName)`が直接対応する(`get_pixmap(dpi=...)`は
    PyMuPDF 1.19.2以降の公式API、Web検索で確認済み)。`import fitz`は
    PyMuPDF側で非推奨(`FutureWarning`)のため、現行の`import pymupdf`
    形を使う。"""

    display_name: str | None = None
    file_name: Expr = None
    output_file_name: Expr = None
    page_number: Expr = None
    image_dpi: str | None = None


@dataclass
class ExtractImagesFromPdfNode:
    """`<ExtractImagesFromPDF>`(知見209、`upap:`名前空間——
    `ExportPDFPageAsImage`等と同じ`pdf-render`プラグインで対応できる
    見込み)。実機1件(`vajrang-b/UiPathIn30Days`)で確認した構成は
    `FileName`+`OutputFolderName`のみ(`ImageExtension`属性は一度も
    確認できず)。公式ドキュメント(`docs.uipath.com`検索経由)では
    `ImageExtension`というドロップダウン(`.png`/`.jpeg`/`.tiff`/
    `.bmp`/`.gif`、既定`.png`)の存在が示唆されるが、実機で非デフォルト
    値の確認が無いため設定時は`# TODO`へ倒す。

    注意: 同名の`ExtractImagesFromPDF`活動がArenaRobotics社の
    サードパーティパッケージ(`apac:`名前空間、属性名`Filename`/
    `OutputFolder`/`ImageExtension`(数値enum)——いずれも本活動の
    `FileName`/`OutputFolderName`とは異なる)にも存在することを本tickの
    GitHub調査で確認した。タグ名が同じだけの別物であり、本活動の
    実装には一切関係しない(知見193で既に警告した`apac:ReadPDFText`と
    同じ混同リスク)。

    **出力ファイル名の命名規則は未確定(公式ドキュメント・実機のいずれ
    にも記載が無い)**——本トランスパイラ独自の選択として、PyMuPDFの
    公式レシピ(`recipes-images.rst`)がそのまま使う`img-{xref}.{ext}`
    形式(画像のPDF内部参照番号ベース)を採用する。これはUiPathの実際の
    内部命名を再現したものではないため、生成コードにもその旨のコメント
    を残す。抽出される画像バイト列自体の正しさ(本質的な機能)とは
    独立した、表示上の命名選択に過ぎない。"""

    display_name: str | None = None
    file_name: Expr = None
    output_folder_name: Expr = None
    image_extension: Expr = None


@dataclass
class ManagePdfPasswordNode:
    """`<ManagePDFPassword>`(知見202、`GetPDFPageCount`/
    `ExtractPDFPageRange`/`JoinPDF`(知見200・201)と同じ`upap:`
    名前空間)。`UiPath/skills`公式リポジトリのStudio実機ground-truth
    コーパスは`FileName`+`OutputFileName`のみだが、実機3件(いずれも
    `vajrang-b/UiPathIn30Days`)で`NewUserPassword`(平文VBリテラル
    `"1234"`)と`NewOwnerPassword`(同`"1234"`)の両方——異なる実例で
    それぞれ単独使用——を確認した(ground-truthが実機の全属性を
    網羅していない、知見197の`GenerateDataTable`と同じ傾向)。
    `OldUserPassword`/`OldOwnerPassword`(既存のパスワードの変更/削除
    用と推測される)は実機で一度も非nullの実例を確認できなかったため
    未モデル化、設定時は常に`# TODO`へ倒す。

    `pypdf.PdfWriter.encrypt(user_password, owner_password=...)`
    (`pyproject.toml`で既に確認済みの依存、`pypdf`自体で対話的に
    動作確認済み——本リポジトリのPAD側に暗号化の既存イディオムは
    無いため、`pypdf`本体のAPIを直接使う最初の例)が直接対応する。
    `NewOwnerPassword`のみ設定時は`user_password=""`(空文字列、
    パスワード無しで開けるがowner権限のみ制限される——実際に`pypdf`で
    対話的に確認した挙動)を渡す。"""

    display_name: str | None = None
    file_name: Expr = None
    output_file_name: Expr = None
    new_user_password: Expr = None
    new_owner_password: Expr = None
    old_user_password: Expr = None
    old_owner_password: Expr = None


@dataclass
class WriteCsvFileNode:
    """`<ui:WriteCsvFile>`(知見185、`ReadCsvFile`の正反対)。`UiPath/
    skills`公式リポジトリのStudio実機ground-truthコーパス
    (`UiPath.Excel.Activities/3.4/WriteCsvFile.xaml`)+実機3件で確認
    した構成は`FilePath`+`DataTable`+`AddHeaders`(実機全件`"True"`)+
    `Delimitator`(実機全件`"Comma"`)+`ShouldQuote`(ground-truthの
    既定値`"True"`、実機では一度もシリアライズされているのを見な
    かった——既定値のため省略されている)+`Encoding`。

    `OutputDataTable`(知見184)と同じ`isinstance(data_table[0], dict)`
    の実行時分岐でDataTable変数の両表現に対応する——dict行の場合のみ
    `AddHeaders`の値に従ってヘッダー行を出力し(列名が分かるため)、
    list行の場合はヘッダー無しで値のみを出力する(列名を持たない
    表現のため、`AddHeaders`の値に関わらずヘッダーは書けない——実害の
    無い保守的な縮退であり、でっち上げた列名を書くことはしない)。"""

    file_path: Expr = None
    data_table: Expr = None
    add_headers: str | None = None
    delimitator: str | None = None
    should_quote: str | None = None
    encoding: Expr = None
    display_name: str | None = None


@dataclass
class AppendCsvFileNode:
    """`<ui:AppendCsvFile DataTable="..." FilePath="..."
    Delimitator="Comma" DelimitatorForViewModel="Comma" />`(知見272、
    `WriteCsvFileNode`(知見185)の追記側、discovery-fresh-pass-9で
    「未実装」として発見、タグ名限定GitHub検索で48件ヒット)。公式
    Studio ground-truth(`marcelocruzrpa/uipath-ai-skills`リポジトリ)
    で`AddHeaders`/`ShouldQuote`属性が**存在しない**ことを確認——
    追記先の既存CSVファイルには既にヘッダー行があるため、ヘッダーを
    再出力する選択肢自体が無い(意味論上当然の設計)。

    実機2件(`Apress/Robotic-Process-Automation-Using-UiPath-StudioX`
    の`Chapter_8_CSVAutomationExercise/Main.xaml`、`piyushagarwal08/
    JU-Notes`の`UiPath/Vendor_Certification/Process.xaml`)で確認した
    構成——`DataTable`、`FilePath`(拡張子無しの相対パス`"Data\\
    vendor.csv"`、絶対パス`"C:\\BookSamples\\..."`の両方確認)、
    `Delimitator`(実機2件とも唯一の確認値`"Comma"`、`WriteCsvFileNode`
    と同じ確認済み値)、`Encoding`(実機2件とも`{x:Null}`、
    `WriteCsvFileNode`と同じ「設定時は未確認のためTODO」判断を継承)。
    `DelimitatorForViewModel`はStudioのドロップダウンUI用のミラー属性
    (`Delimitator`の値を常に複製しているだけ)でコード生成に無関係、
    捕捉しない。

    `WriteCsvFileNode`の`"w"`モードでの`csv.writer`書き込みを踏襲する
    が、ヘッダー出力判断が存在しないぶん単純——常にモード`"a"`
    (追記)で開き、`isinstance(data_table[0], dict)`分岐
    (`WriteCsvFileNode`/`OutputDataTable`(知見184/185)と同じ既存の
    dict行/list行両対応)で値のみを書き込む(ヘッダー行は常に出力
    しない)。"""

    file_path: Expr = None
    data_table: Expr = None
    delimitator: str | None = None
    encoding: Expr = None
    display_name: str | None = None


@dataclass
class DeserializeXmlNode:
    """`<ui:DeserializeXml XMLString="..." XMLDocument="...">`(知見228、
    `UiPath.WebAPI.Activities`名前空間だがタグは`ui:`、タグ名限定
    GitHub検索で54件ヒット)。ground-truth(`marcelocruzrpa/
    uipath-ai-skills`、`XMLDocument="{x:Null}" XMLString="{x:Null}"`)・
    実機(`Sundsvallskommun/RPA-openeplatformapi`の`Get Case
    Status.xaml`、`XMLDocument="[ResultAsXMLDocument]"
    XMLString="[ResultString]"`——プレーンな属性で十分、`feli203040/
    PruebaConceptoUiPath`のC#式活動版はプロパティ要素でラップされる
    形も確認)いずれも`XMLString`(文字列入力)+`XMLDocument`(出力、
    .NETの`System.Xml.Linq.XDocument`)の2属性のみ。`lxml.etree.
    fromstring()`(本体の`dependencies`に既にある`lxml`——
    `xaml_tree.py`自身がXAMLパースに使っている既存の確認済み依存、
    `ExportPDFPageAsImage`知見209の「新規依存」とは違う)が対応する
    ——XML宣言内のエンコーディング指定を正しく解釈させるため、文字列
    を`.encode("utf-8")`してバイト列として渡す。"""

    display_name: str | None = None
    xml_string: Expr = None
    xml_document: Expr = None


@dataclass
class ExecuteXPathNode:
    """`<ui:ExecuteXPath ExistingXML="..." XMLString="..."
    XPathExpression="..." Result="..." />`(知見228、`DeserializeXml`
    の兄弟活動、タグ名限定GitHub検索で31件ヒット)。ground-truth・
    実機複数件(`Sundsvallskommun/RPA-openeplatformapi`で3件、
    `XPathExpression="string(//Status/name)"`のような`string()`
    ラップされたXPath式で単一文字列を抜き出す定番用途)いずれも
    `ExistingXML`(既にパース済みの`XDocument`)と`XMLString`
    (未パースの生文字列、こちらを直接渡すとその場でパースする)の
    2つの入力経路を持つ——実機では常に片方だけが非nullで、他方は
    `{x:Null}`のまま。公式ドキュメント(WebSearch経由確認、
    `execute-x-path`ページ)で「`XMLString`を入力すると`ExistingXML`
    は使用不可になる」と確認済み——`XMLString`が優先される。

    `.NET`の`XDocument.XPathEvaluate`相当は`lxml`の`Element.xpath()`
    (.NET実装もXPath 1.0相当のため構文的な互換性は十分高い、
    `Regex`系活動(知見144/213/220)とは違い構文変換は不要)に対応する
    ——`string(...)`でラップされたXPath式はPythonの`str`を返す
    (`.xpath()`のネイティブな戻り値型分岐、XPath仕様に準拠)。"""

    display_name: str | None = None
    existing_xml: Expr = None
    xml_string: Expr = None
    xpath_expression: Expr = None
    result: Expr = None


@dataclass
class GetXMLNodeAttributesNode:
    """`<ui:GetXMLNodeAttributes Attributes="..." ExistingXMLNode="..." />`
    (知見280、discovery-fresh-pass-11で発見、`UiPath.WebAPI.Activities`
    名前空間だがタグは`ui:`(`DeserializeXml`/`ExecuteXPath`と同じ、
    知見228)、タグ名限定GitHub検索で5件ヒットのみだが実機2件で確認
    済み)。ground-truth(`marcelocruzrpa/uipath-ai-skills`)+実機2件
    (`GSA/RPA-OSS`の`FAS RPA Processes/FAS PSS New Offer-New Template/
    ReadXML-New.xaml`、`fc205/DependencyViewer`の`ProcessPackage.xaml`)
    で`ExistingXMLNode`(`sxl:XElement`型の入力——`ExecuteXPath`
    (知見228)の`.xpath()`戻り値がそのまま渡される実例、`lxml`の
    `_Element`相当)+`Attributes`(出力、`scg:IEnumerable(sxl:
    XAttribute)`型と実機で明示的に型宣言されている変数で確認)の
    2属性のみの構成を確認。

    下流アクセスを`fc205/DependencyViewer`で確認——`Attributes`を
    `ui:ForEach x:TypeArguments="sxl:XAttribute"`で反復し、各要素の
    `.Name`(`attribute.Name = "id"`という文字列比較)+`.Value`
    (`attribute.Value`)にアクセスする——.NET `XAttribute`の確定済み
    狭いアクセスパターン(型未確認の広いサーフェス懸念には当たらない)。
    `lxml`の`Element.attrib.items()`(キー・値のペアを返す、`DeserializeXml`
    /`ExecuteXPath`と同じ既存の確認済み依存)の各ペアを、`.Name`/
    `.Value`のみを持つ薄いラッパークラス`_XAttribute`(`_ImapMailMessage`
    (知見250)と同じ設計判断クラス)でラップする。姉妹活動`ui:
    GetXMLNodes`(子要素ノード自体を返す版)は実機ヒットが無く
    (ground-truthと合成サンプル生成リポジトリのみ)未対応。"""

    display_name: str | None = None
    attributes: Expr = None
    existing_xml_node: Expr = None


@dataclass
class InvokePowerShellNode:
    """`<ui:InvokePowerShell>`(知見186、GitHub code searchで337件
    ヒット——`UiPath/skills`公式リポジトリのStudio実機ground-truth
    コーパスでは`ExecutePowerShell`という別名で存在するが、実機では
    一度も遭遇できず、実機で確認できたのは全て`InvokePowerShell`タグ
    の方だった——同種の活動がバージョン間で改名される現象(知見153・
    158・161と同じ系統)の可能性があるが未確認)。実機3件
    (`cameronmcnz/uipath-tutorials`・`nestorzamili/RPA-Grafana-
    Kibana`・`solankidrashti2965/Invoice-OCR-Automation`)で確認した
    構成は`CommandText`(実行するPowerShellコマンド/スクリプト)+
    `IsScript`(`True`/`False`)+`PowerShellProcess`(実機確認した値は
    全件`"PowerShellCore"`——`pwsh`実行ファイル)+`ContinueOnError`+
    `Parameters`/`PowerShellVariables`(両方とも実機確認した全例で
    空の`scg:Dictionary`——パラメータ渡しは未使用)。`Input`/`Errors`/
    `PipelineOutput`は実機のどの例でも一度もシリアライズされていな
    かった(未設定)。

    `PowerShellProcess="PowerShellCore"`の場合、`subprocess.run(["pwsh",
    "-Command", command_text], check=True)`が直接対応する——`pwsh`は
    PowerShell Core (7+)の確認済み標準実行ファイル名。`check=True`は
    `ContinueOnError`の既定値(`None`/`False`、エラーを伝播させる)に
    合わせる判断——`subprocess.run()`は既定で非ゼロ終了コードを例外に
    しない(UiPathの既定動作と食い違う)ため、明示的に`check=True`を
    付けて「エラー時は例外で失敗する」という既定動作に揃える(知見177
    と同じ「でっち上げた成功より、失敗を伝播させる方が安全」という
    判断)。`PowerShellProcess`が`"PowerShellCore"`以外・`Parameters`/
    `PowerShellVariables`が空でない・`Input`/`Errors`/
    `PipelineOutput`が設定されている場合は`# TODO`へ倒す。"""

    command_text: Expr = None
    is_script: str | None = None
    powershell_process: str | None = None
    continue_on_error: Expr = None
    has_parameters: bool = False
    has_powershell_variables: bool = False
    input: Expr = None
    errors: Expr = None
    pipeline_output: Expr = None
    display_name: str | None = None


@dataclass
class InvokeVBScriptNode:
    """`<ui:InvokeVBScript FileName="..." Result="..."
    WaitForOutput="True">...</ui:InvokeVBScript>`(知見276、discovery-
    fresh-pass-10で発見、タグ名限定GitHub検索で約30件ヒット)。公式
    Studio ground-truth(`marcelocruzrpa/uipath-ai-skills`リポジトリ)
    +公式`UiPathJapan/samples`の`2019.5/InvokeVBScript`サンプルで構成を
    確認——`FileName`(`.vbs`ファイルへのパス)、`.Arguments`
    (`scg:List x:TypeArguments="InArgument(x:String)"`の位置引数
    リスト、`JoinPdfNode.file_list`/`SelectMultipleItemsNode.
    multiple_items`と同じ形、既存の汎用パーサー`_parse_property_
    element_list()`で対応)、`Result`(出力、スクリプトの戻り値を
    捕捉)、`WaitForOutput`(実機全件で唯一の確認値`"True"`)。

    **ランタイム契約を独立検証した**(公式サンプルの実際の`sample.vbs`
    ファイルを取得して確認)——`WScript.Arguments(0)`/`WScript.
    Arguments(1)`で位置引数を読み、`WScript.Echo "..."`で結果文字列を
    書き出す、標準のWindows Script Host(WSH)コンソール契約——これは
    `MSScriptControl.ScriptControl` COMオブジェクト経由という前回の
    推測とは異なり(未検証の推測だったため、今回のパスで裏取りし直し
    訂正した)、`cscript.exe`への単純な`subprocess.run()`呼び出しで
    対応できる、既存の`InvokePowerShellNode`(知見186、`subprocess.
    run(["pwsh", ...])`)と全く同じ設計パターン。

    実機(`mvillanuevas/ReporteRegulatorio`の`Procesos/Timbrado_OH.
    xaml`等、複数回使用)で`Result`の下流アクセス(`vbsResult.Contains
    ("Error")`、プレーンな文字列メソッド)を確認——スカラー文字列の
    確定済み狭いアクセスのため型未確認の広いサーフェス懸念には当たら
    ない。同サンプルで`RunInBatchMode="True"`(`cscript.exe //B`
    ——エラーダイアログ/入力待ちプロンプトを抑制する無人実行向けの
    確認済みフラグ、公式ドキュメントの意味論と一致)+`KillOnTimeout=
    "False"`+`UnicodeSupport="True"`の実例も確認したが、`UnicodeSupport`
    は`cscript.exe`側の出力エンコーディング詳細(`//U`フラグ)に相当
    すると推定しつつも、本サンドボックスでWindows実機検証ができない
    ため値の違いをコード生成に反映しない既知の簡略化とする(True/False
    いずれも受け入れるが`subprocess.run()`呼び出し自体は変えない)。
    `TimeoutMS`(実機全件で`{x:Null}`のみ確認)が設定されている場合は
    `# TODO`へ倒す——`KillOnTimeout`自体は`TimeoutMS`無しでは意味を
    持たないため値を問わない。"""

    file_name: Expr = None
    arguments: list[Expr] = field(default_factory=list)
    result: Expr = None
    wait_for_output: str | None = None
    run_in_batch_mode: str | None = None
    unicode_support: str | None = None
    kill_on_timeout: str | None = None
    timeout_ms: Expr = None
    display_name: str | None = None


@dataclass
class RetryScopeNode:
    """`<ui:RetryScope>`(知見187、`UiPath.System.Activities`、GitHub
    code searchで3280件ヒット——`UiPath/skills`公式リポジトリの
    REFramework標準サブワークフロー資産(`assets/stripped/
    SetTransactionStatus.xaml`)で実際に使われている、知見169・179と
    同じ最高水準の確証)。`ActivityBody`(`ActivityAction`→
    `Sequence`、他のスコープ活動と同じ構造)+`NumberOfRetries`
    (整数)+`RetryInterval`(TimeSpan、実機1件で`"00:10:00"`を確認した
    が公式REFrameworkテンプレートでは省略=`{x:Null}`)+`Condition`
    (`ActivityFunc<Boolean>`——公式REFrameworkテンプレートでは中身の
    無い空の`ActivityFunc`、実機の別例(Modern活動を使う複雑な例)では
    要素の状態チェックを含む非空の実装を確認)+`LogRetriedExceptions`/
    `RetriedExceptionsLogLevel`。

    公式REFrameworkテンプレート(`SetTransactionStatus.xaml`)での
    使い方は、`ActivityBody`内部の`TryCatch`+`Rethrow`(`Catch`節で
    ログを出してから明示的に再スローする、実機確認済みの構造)と
    組み合わせ、`Condition`を空のままにする——これは「本体が例外無しで
    完了するまで、最大`NumberOfRetries`回まで再試行し、全回失敗したら
    最後の例外を伝播させる」という、最もシンプルで確認済みの意味論
    だと判断した。`Condition`が空でない場合(Modern活動の要素状態
    チェック等、未確認の価値ベース条件)・`RetryInterval`が設定されて
    いる場合(再試行間隔の正確な待機時間変換が未確認)・
    `LogRetriedExceptions`/`RetriedExceptionsLogLevel`が設定されている
    場合は`# TODO`へ倒す。"""

    body: list["Node"] = field(default_factory=list)
    number_of_retries: Expr = None
    retry_interval: Expr = None
    condition_has_body: bool = False
    log_retried_exceptions: Expr = None
    retried_exceptions_log_level: Expr = None
    display_name: str | None = None


@dataclass
class MoveFileNode:
    """`<ui:MoveFile>`(知見188、`UiPath.System.Activities`、GitHub
    code searchで575件ヒット)。`CopyFile`(知見117)と全く同じ属性
    構成(`Path`+`Destination`+`Overwrite`+`DestinationResource`/
    `PathResource`+`ContinueOnError`)——`UiPath/skills`公式リポジトリ
    のStudio実機ground-truthコーパス+実機4件(`PacktPublishing/
    Robotic-Process-Automation-Projects`・`cameronmcnz/uipath-
    tutorials`)で確認。`shutil.move()`(`CopyFile`の`shutil.copy()`と
    対になる標準API)が直接対応する——`CopyFile`と同じ「移動先が既存の
    ディレクトリならファイル名を付加する」解決ロジック+
    `Overwrite="False"`時の事前存在チェックをそのまま再利用する
    (移動先が既に存在する場合の`shutil.move`自体の挙動はOSごとに
    異なる——Windowsの`os.rename`は上書きせず失敗するが`shutil.move`
    内部のフォールバック経路では上書きされる場合がある——という
    プラットフォーム依存の挙動に頼らず、`CopyFile`と同じ明示的で
    予測可能なチェックに揃える判断)。"""

    path: Expr = None
    destination: Expr = None
    overwrite: str | None = None
    destination_resource: Expr = None
    path_resource: Expr = None
    continue_on_error: Expr = None
    display_name: str | None = None


@dataclass
class CopyFolderXNode:
    """`<ui:CopyFolderX From="..." To="..." IncludeSubfolders="True"
    Overwrite="True" ContinueOnError="..." />`(知見246、8回目発見パス
    のTier 2候補、タグ名限定GitHub検索で24件ヒット——弱めの実機利用率
    だが実機3件(`RobotGod1/IndianaOverheadAdjustment.RPA.Uipath.
    Process`の`Project/SetUpEnvironmentIfNeeded.xaml`、
    `Masbahul-bari/UiPath`の`moveANDcopy/copy.xaml`、公式`Apress/
    Robotic-Process-Automation-Using-UiPath-StudioX`の
    `Chapter_9_FolderActivitiesExercise/Main.xaml`)で独立に確認、
    一貫して同じ属性構成)で確認済み。`CopyFile`(知見117)のフォルダ版
    ——`From`/`To`/`Overwrite`は`CopyFile`と同じ、`IncludeSubfolders`
    (実機・ground-truth既定値いずれも`"True"`のみ確認、`"False"`時の
    意味論は未確認のため見送る)が新規。`FromResource`/`ToResource`
    (ground-truthのみ、`CopyFile`の`DestinationResource`/`PathResource`
    と同じIntegration Service連携用と推定)は未確認のため見送る。
    `ContinueOnError`はground-truthには無いが実機サンプルに存在する
    (知見197等で繰り返し確認済みの「ground-truthは非網羅的」パターン)
    ——公式ドキュメント(WebSearch経由確認)でも標準の共通プロパティ
    として記載されている。

    公式ドキュメント確認済みの`Overwrite`の意味論(「宛先に`From`と
    同じ名前の既存フォルダがあれば置き換える」)から、`To`は`CopyFile`
    の`Destination`と同じ「既存ディレクトリならその配下に`From`の
    basenameで配置する」解決ロジックがそのまま適用できると判断した
    ——`shutil.copytree()`(`CopyFile`の`shutil.copy()`に対応する
    フォルダ版の標準API)を使う。"""

    from_: Expr = None
    to: Expr = None
    include_subfolders: str | None = None
    overwrite: str | None = None
    from_resource: Expr = None
    to_resource: Expr = None
    continue_on_error: Expr = None
    display_name: str | None = None


@dataclass
class MoveFolderXNode:
    """`<ui:MoveFolderX From="..." To="..." Overwrite="True" />`
    (知見246、`CopyFolderX`の対になる移動活動、タグ名限定GitHub検索で
    28件ヒット)。`MoveFile`(知見188)のフォルダ版——ground-truth・
    実機(公式`Apress/Robotic-Process-Automation-Using-UiPath-
    StudioX`の`Chapter_9_FolderActivitiesExercise/Main.xaml`)いずれも
    `IncludeSubfolders`が無い(`CopyFolderX`と違い、移動はフォルダの
    中身全体を常に対象とするため選択の余地が無いと推定)。`shutil.
    move()`(`MoveFile`に対応するフォルダ版の標準API)を使う——
    `MoveFile`と同じ「移動先が既存のディレクトリなら`From`のbasenameを
    付加する」解決ロジック+`Overwrite="False"`時の事前存在チェックを
    そのまま再利用する。`ContinueOnError`は実機未確認だが
    `CopyFolderX`と対になる活動のため同じく見送る側に倒す
    (`MoveFile`/`CopyFile`が同じプロパティを共有するのと対称的な
    判断)。"""

    from_: Expr = None
    to: Expr = None
    overwrite: str | None = None
    continue_on_error: Expr = None
    display_name: str | None = None


@dataclass
class PathExistsNode:
    """`<ui:PathExists>`(知見188、`UiPath.System.Activities`、GitHub
    code searchで558件ヒット)。`UiPath/skills`公式リポジトリのStudio
    実機ground-truthコーパス+実機2件(`PacktPublishing/Robotic-
    Process-Automation-Projects`・`cristinegulescu/
    startUiPathFromSalesforce`)で確認した構成は`Path`+`Exists`
    (出力)+`Resource`(Integration Service連携用、未モデル化)+
    `PathType`(実機確認済みの値は`"File"`/`"Folder"`の2種)。

    `PathType="File"`の場合は`os.path.isfile()`、`"Folder"`の場合は
    `os.path.isdir()`(いずれもPython標準の確認済みAPI)が直接対応
    する——`os.path.exists()`のような種別を問わない汎用チェックでは
    なく、UiPathの`PathType`が明示的に区別している意味論に正確に
    対応させる。"""

    path: Expr = None
    exists: Expr = None
    resource: Expr = None
    path_type: str | None = None
    display_name: str | None = None


@dataclass
class FileExistsXNode:
    """`<ui:FileExistsX>`(知見219、`PathExists`(知見188)の`PathType=
    "File"`固定版と推測される、GitHub code searchで「`"ui:
    FileExistsX"`」タグ名限定422件ヒット——`PathExists`の558件に
    迫る)。ground-truthの属性構成は`Exists`(出力)+`Path`のみ。
    実機2件(`bogdanripa/Log-Me-In`のVB実機・`Anusha-TX/
    Group1001_TestAutomation`のC#実機)で確認した構成も`Exists`+
    `Path`のみの単純な形。

    `os.path.isfile()`(Python標準の確認済みAPI、`PathExists`の
    `PathType="File"`分岐と同じ対応)が直接対応する。"""

    display_name: str | None = None
    path: Expr = None
    exists: Expr = None


@dataclass
class FolderExistsXNode:
    """`<ui:FolderExistsX>`(知見219、`FileExistsX`と対になる
    フォルダ版、GitHub code searchで「`"ui:FolderExistsX"`」タグ名
    限定227件ヒット)。ground-truthの属性構成は`Exists`(出力)+`Path`
    のみ。実機2件(`AliOmarAbdelhady/Raya_tasks`のC#実機・
    `Gokula-Krishnan9991/UIPATH-Projects`のVB実機)で確認した構成も
    `Exists`+`Path`のみ。

    `os.path.isdir()`(Python標準の確認済みAPI、`PathExists`の
    `PathType="Folder"`分岐と同じ対応)が直接対応する。"""

    display_name: str | None = None
    path: Expr = None
    exists: Expr = None


@dataclass
class DeleteFileNode:
    """`<ui:DeleteFileX>`(知見189、GitHub code searchで508件ヒット
    ——検索語`"ui:DeleteFile"`は`"ui:DeleteFileX"`への部分一致で、
    実機で非X形(`ui:DeleteFile`単体)を一度も確認できなかった
    ——`"<ui:DeleteFile "`(末尾スペース付き完全一致)で0件を確認
    済み)。`UiPath/skills`公式リポジトリのStudio実機ground-truth
    コーパス(`UiPath.System.Activities/25.10/DeleteFileX.xaml`)+
    実機2件(`vajrang-b/UiPathIn30Days`・`andumorie/uipath-face-
    recognition-framework`)で確認した構成は`Path`のみ——
    `DisplayName`以外に属性が無い、`ClearDataTable`(知見184)と同じ
    最も単純な活動の1つ。`ui:`名前空間のまま(`uix:`ではない)
    Target/セレクタの概念を一切持たないため、知見で確立してきた
    「Modern活動除外」の対象ではなく、`os.remove()`(Python標準の
    確認済みAPI)が直接対応する通常のファイルシステム操作だと判断。"""

    path: Expr = None
    display_name: str | None = None


@dataclass
class DeleteFolderNode:
    """`<ui:DeleteFolderX>`(知見189、`DeleteFile`の兄弟活動、GitHub
    code searchで173件ヒット)。実機2件(`tnadu/RPA-Task-Aggregator`・
    `happycodingandlife/UiPath-Generate-Yearly_Report_Performer`)で
    確認した構成は`Path`+`Recursive`(ground-truthの既定値`"True"`、
    実機確認した全例も`"True"`——`"False"`の実例は未確認だが、
    `os.rmdir()`(空のフォルダのみ削除)という確認済みの標準API対応が
    明確なため値を問わず両方対応する)。

    `Recursive="True"`の場合は`shutil.rmtree()`(フォルダとその内容を
    再帰的に削除する確認済みの標準API)、`"False"`の場合は
    `os.rmdir()`(空のフォルダのみ削除、内容がある場合は
    `OSError`で失敗する——でっち上げた「強制的に空にする」処理は
    しない)が直接対応する。"""

    path: Expr = None
    recursive: str | None = None
    display_name: str | None = None


@dataclass
class ForEachFileNode:
    """`<ui:ForEachFileX>`(知見190、`UiPath.System.Activities`、GitHub
    code searchで738件ヒット——知見189で発見した`ui:ForEachFolderX`
    (40件)の兄弟活動)。`UiPath/skills`公式リポジトリのStudio実機
    ground-truthコーパス+実機2件(`marcelocruzrpa/uipath-ai-skills`
    の資産`PDFExtraction_Main.xaml`)で確認した構成は`Folder`
    (走査対象)+`IncludeSubDirectories`(ground-truthの既定値
    `"False"`)+`OrderBy`(実機確認した値は全件`"NameAscFirst"`)+
    `SkipFolderWithoutPermission`(ground-truthの既定値`"False"`)+
    `Body`(`ActivityAction<FileInfo, Int32>`——`ForEachNode`(知見5)
    とは違い**2変数**のデリゲート、`Argument1`=`CurrentFile`/
    `Argument2`=`CurrentIndex`)。

    `CurrentFile`はPythonの単純な文字列(ファイルの絶対パス、.NET
    `FileInfo.FullName`と同じ値)として表現する——`render_expr`の
    チェインメンバアクセス許可リスト(`_apply_chained_property`)は
    メンバ名を問わず未知の名前を安全に拒否するため、`FileInfo`型の
    リッチなオブジェクトをでっち上げる代わりに最小限で確認済みの
    表現(パス文字列そのもの)を選んだ——実機で唯一確認できた
    `CurrentFile.FullName`という使い方だけ、`render.py`に新しい
    `.FullName`(そのまま値を返す、パス文字列自体が既にFullName相当
    のため)という狭いメンバ変換を追加して対応する。`IncludeSub
    Directories`は`True`/`False`両方に`os.walk()`/`os.scandir()`で
    対応するが、`OrderBy`が`"NameAscFirst"`以外・
    `SkipFolderWithoutPermission`が`"True"`の場合は`# TODO`へ倒す
    (権限エラーを握り潰す動作は未モデル化)。"""

    folder: Expr = None
    include_sub_directories: str | None = None
    order_by: str | None = None
    skip_without_permission: str | None = None
    item_var: str = ""
    index_var: str = ""
    body: list["Node"] = field(default_factory=list)
    display_name: str | None = None


@dataclass
class ForEachFolderNode:
    """`<ui:ForEachFolderX>`(知見190、`ForEachFile`の兄弟活動、GitHub
    code searchで40件ヒット——知見189で発見)。属性構成は`ForEachFile`
    と同型(`IncludeSubFolders`/`SkipFoldersWithoutPermission`という
    別名の属性のみ、意味論は同じ)。`CurrentFolder`も同じ理由で
    フォルダの絶対パス文字列として表現する。`IncludeSubFolders=True`
    の場合は`os.walk()`が列挙する**全ての階層の**サブフォルダを対象に
    する(ルート自身は含まない、`os.walk()`の`dirnames`が各階層で
    子フォルダのみを返す確認済みの挙動を利用)。"""

    folder: Expr = None
    include_sub_folders: str | None = None
    order_by: str | None = None
    skip_without_permission: str | None = None
    item_var: str = ""
    index_var: str = ""
    body: list["Node"] = field(default_factory=list)
    display_name: str | None = None


@dataclass
class RenameFileNode:
    """`<ui:RenameFileX>`(知見191、GitHub code searchで123件ヒット
    ——`DeleteFileX`(知見189)と同じ「X」付きファイルシステム操作系
    活動ファミリーの一員)。`UiPath/skills`公式リポジトリのStudio
    実機ground-truthコーパス+実機(`KooBonchan/wine-bouti`)で確認した
    構成は`FilePath`+`NewName`+`KeepExtension`(ground-truthの既定値
    `"True"`)+`FileResource`/`OutputFileResource`(Integration Service
    連携用、未モデル化)。

    `KeepExtension="True"`の場合、元のファイルの拡張子を`NewName`に
    付加してから`os.rename()`(Python標準の確認済みAPI)で改名する
    ——`os.path.splitext()`(拡張子分離)+`os.path.dirname()`
    (ディレクトリ部分の保持)という確認済みの標準的な組み合わせ。"""

    file_path: Expr = None
    new_name: Expr = None
    keep_extension: str | None = None
    file_resource: Expr = None
    output_file_resource: Expr = None
    display_name: str | None = None


@dataclass
class RenameFolderNode:
    """`<ui:RenameFolderX>`(知見191、`RenameFile`の兄弟活動、GitHub
    code searchで実機確認済み)。`FolderPath`+`NewName`のみ——
    `KeepExtension`に相当する属性は無い(フォルダに拡張子の概念は
    無いため)。`os.rename()`が直接対応する。"""

    folder_path: Expr = None
    new_name: Expr = None
    display_name: str | None = None


@dataclass
class CreateFileNode:
    """`<ui:CreateFile>`(知見191、`UiPath.System.Activities`、GitHub
    code searchで266件ヒット——`DeleteFileX`等とは違い非X形のまま)。
    `UiPath/skills`公式リポジトリのStudio実機ground-truthコーパス+
    実機(`piyushagarwal08/JU-Notes`)で確認した構成は`Path`
    (ディレクトリ)+`Name`(ファイル名)+`Output`(出力、実機で非
    `{x:Null}`の値を確認できず——`ForEachFileX`(知見190)と同じ
    「絶対パス文字列」表現で対応する)+`PathResource`(未モデル化)+
    `ContinueOnError`。

    `os.path.join(Path, Name)`で完全パスを組み立て、`open(path,
    "w").close()`(空ファイルを作成する、Python標準の確認済み手法)で
    作成する。既存ファイルが既にある場合の上書き挙動がUiPath実機と
    一致するかは未確認(本調査の対象外)——`CopyFile`/`MoveFile`
    (知見117・188)のような`Overwrite`相当の属性自体がこの活動には
    無いため、既存ファイルの扱いに関する分岐自体が存在しない。"""

    path: Expr = None
    name: Expr = None
    output: Expr = None
    path_resource: Expr = None
    continue_on_error: Expr = None
    display_name: str | None = None


@dataclass
class GetProcessesNode:
    """`<ui:GetProcesses Processes="..." ContinueOnError="..." />`
    (知見255、10回目発見パスの残り候補、タグ名限定GitHub検索で72件
    ヒット)。実機4件(`crcnum4/UP_Underwriter_Dashboard`の
    `Framework/KillAllProcesses.xaml`、`bhsaguiar/
    FlowDrivenFrameworkWindows`・`bhsaguiar/FlowDrivenFramework_Global`
    の`GetProcesses.xaml`、`ozhazdayt/CommentClassifyR`の
    `Check Outlook.xaml`)+ground-truthいずれも`Processes`(出力、
    `IEnumerable<System.Diagnostics.Process>`、`ui:ForEach
    x:TypeArguments="sd:Process"`で消費)+`ContinueOnError`
    (実機全件`{x:Null}`)のみの構成——属性自体は極めて単純。

    下流の実際の消費パターンを実機サンプルで確認した——
    `CurrentProcess.ProcessName`(`CType(currentProcess,
    System.Diagnostics.Process).ProcessName`形、文字列比較)への
    読み取りアクセスと、`KillProcess`(知見169)の`Process`属性への
    そのままの再代入(`CType(currentProcess,
    System.Diagnostics.Process)`——`KillProcess`が`ProcessName`の
    代わりに個々の`Process`オブジェクトを直接終了するケース、知見169
    で「常に`{x:Null}`」としていたが実際には非null例が存在した)の
    2つのみ——いずれもこの実行環境で既に確認済みのコア依存
    `psutil`(`dump_daemon/uia_capture.py`で既に`psutil.Process(pid).
    name()`という同じAPIを使用済み)の`psutil.process_iter()`
    (`psutil.Process`オブジェクトのイテレータを返す)で正確に対応
    できる——新規依存は不要。`.ProcessName`は`psutil.Process.
    name()`メソッドへの1:1対応として`render.py`の既存の括弧省略形
    チェインメンバ変換テーブル(`_CHAINED_PROPERTY_TRANSLATIONS`)に
    追加するだけで対応できる。"""

    processes: Expr = None
    continue_on_error: Expr = None
    display_name: str | None = None


@dataclass
class KillProcessNode:
    """`<ui:KillProcess>`(知見169、GitHub code searchで1514件ヒット
    ——REFrameworkの標準サブワークフロー`KillAllProcesses.xaml`で
    多用されるため極めて高頻度)。`Target`/`Selector`を一切持たず、
    `ProcessName`(実機確認済みの値は`"iexplore"`/`"msedge"`——`.exe`
    拡張子を含まない、.NETの`Process.GetProcessesByName()`と同じ
    慣習)で指定した名前に一致する全プロセスを終了する活動。実機3件
    (`piyushagarwal08/JU-Notes`のREFramework標準`KillAllProcesses.xaml`・
    `vajrang-b/UiPathIn30Days`)で確認した属性は`ProcessName`+
    `Process`(UiPathの`Process`型オブジェクト参照、実機確認した全件で
    `{x:Null}`)・`AppliesTo`(実機で一度も非`{x:Null}`の値を確認でき
    ず意味論未確認)・`ContinueOnError`(全件`{x:Null}`)。

    Windows専用コマンド`taskkill /IM <name>.exe /F`(`subprocess.run`
    経由、プロセス名に一致する全プロセスを強制終了する、Windows標準
    搭載の確認済みコマンド)が直接対応する——`/T`(プロセスツリー全体の
    終了)は付けない(.NETの素の`Process.Kill()`は子プロセスを終了
    しないため、過大な終了範囲をでっち上げないよう安全側に倒す)。

    知見255で発見した新たな実機サンプル(`crcnum4/
    UP_Underwriter_Dashboard`の`Framework/KillAllProcesses.xaml`)は
    `ProcessName="{x:Null}"`+`Process="[CType( currentProcess,
    System.Diagnostics.Process)]"`(`GetProcesses`(知見255)の出力を
    `ui:ForEach`で回したループ変数)という、知見169の時点では一度も
    観測できなかった非null`Process`の実例——`GetProcesses`の
    `psutil.process_iter()`対応と組み合わせることで、`Process`が
    設定されている場合は`<変数>.kill()`(`psutil.Process.kill()`、
    `taskkill`より直接的で確認済みのAPI)で対応する。"""

    process_name: Expr = None
    display_name: str | None = None
    process: Expr = None
    applies_to: Expr = None
    continue_on_error: Expr = None


@dataclass
class CloseTabNode:
    """`<ui:CloseTab Browser="..." />`(知見170、GitHub code searchで
    782件ヒット)。`Target`/`Selector`を一切持たない、唯一の属性は
    `Browser`(`UiBrowser`型変数への参照、`OpenBrowser`の`UiBrowser`
    出力バインディング(知見168)や`BrowserScope`の`UiBrowser`属性と
    同種)。実機確認した値は`{x:Null}`(未設定——`BrowserScope`
    (知見161)の内側で使われ「現在アタッチ中のブラウザの、現在
    アクティブなタブ」を暗黙に指す、REFramework標準の使い方)と、
    動的VB式(`[browserCrunchBase]`/`[firefox]`、`OpenBrowser`の
    `UiBrowser`出力を参照する実例)の両方を確認済み。

    `Browser`が`{x:Null}`(ほとんどのREFramework実例)の場合のみ安全に
    実装する——`UiBrowser`変数参照自体を本トランスパイラはまだ
    モデル化していない(知見154・161・168で繰り返し確認済みの既知の
    限界)ため、変数参照時は`# TODO`へ倒す。`{x:Null}`の場合は
    「現在フォーカス中のタブ/ウィンドウを閉じる」という意味論になり、
    主要ブラウザ(Chrome/Firefox/Edge/IE)共通の標準キーボード
    ショートカット`Ctrl+W`で実現できる——`SendHotkey`(知見152)で
    「`Target`が省略された自己終了タグ(現在フォーカス中のウィンドウ
    へグローバルに送信する意味論)」として未対応のまま残していた
    ケースと同じ経路(pywinautoの`keyboard.send_keys()`、対象を
    指定しないグローバルなキー送信の確認済み標準API)を初めて実際に
    実装する。"""

    browser: Expr = None
    display_name: str | None = None


@dataclass
class RefreshBrowserNode:
    """`<ui:RefreshBrowser Browser="..." />`(知見175、GitHub code
    searchで59件ヒット)。`CloseTab`(知見170)と属性構成・意味論の
    両方が同型——`Target`/`Selector`を一切持たない、唯一の属性は
    `Browser`(`UiBrowser`型変数への参照)。実機3件(`allenlooplee/
    RPABook`・`PakamTharunReddy/RPA`・`csut017/CrowdMarkLoad`)で確認
    した値は`{x:Null}`(ほとんどの実例、「現在アタッチ中のブラウザの、
    現在アクティブなタブ」を暗黙に指す)と動的VB式(`[browser]`)の
    両方。

    `Browser`が`{x:Null}`の場合、意味論は「現在のページを再読み込み
    する」になり、主要ブラウザ共通の標準キーボードショートカット`F5`
    で実現できる——`CloseTab`の`Ctrl+W`と同じ`keyboard.send_keys()`
    (対象を指定しないグローバルなキー送信)経路を再利用する、`{F5}`
    (pywinautoの`.venv`ソース`keyboard.py`のCODESグラマーで確認済みの
    特殊キー構文)という違いのみ。`Browser`が変数参照の場合は
    (`UiBrowser`変数自体が知見154・161・168・170で繰り返し確認済みの
    未モデル化のため)`# TODO`へ倒す。"""

    browser: Expr = None
    display_name: str | None = None


@dataclass
class GoBackNode:
    """`<ui:GoBack Browser="..." />`(知見242、サブエージェントによる
    8回目の新規発見パスで発見、タグ名限定GitHub検索で88件ヒット)。
    `RefreshBrowser`(知見175)と属性構成・意味論が完全に同型——
    `Target`/`Selector`を一切持たない、唯一の属性は`Browser`
    (`UiBrowser`型変数への参照)。実機2件(`DfDganeshh/DomainChecker`
    の`Framework/Process.xaml`、`piyushagarwal08/JU-Notes`の
    `UiPath/ACME_Testing/Main.xaml`)で確認した値は`{x:Null}`
    (「現在アタッチ中のブラウザ」を暗黙に指す)と動的VB式変数参照の
    両方——`RefreshBrowser`と全く同じパターン。

    `Browser`が`{x:Null}`の場合、意味論は「ブラウザの履歴を1つ戻る」
    になり、主要ブラウザ共通の標準キーボードショートカット`Alt+Left`
    で実現できる(pywinautoの`.venv`ソース`keyboard.py`のCODESグラマーで
    `{LEFT}`(特殊キー)・`%`(Altの修飾子記法)いずれも確認済み)——
    `RefreshBrowser`の`{F5}`と同じ`keyboard.send_keys()`経路を再利用
    する。`Browser`が変数参照の場合は`RefreshBrowser`と同じ理由で
    `# TODO`へ倒す。兄弟活動`ui:GoForward`はGitHub検索で5件ヒットのみ
    (`GoBack`の88件と比べ著しく薄い実機利用率)のため今回は対象外。"""

    browser: Expr = None
    display_name: str | None = None


@dataclass
class NavigateToNode:
    """`<ui:NavigateTo Browser="..." Url="..." />`(知見242、同じ8回目
    発見パス、タグ名限定GitHub検索で423件ヒット——今回の発見パスで
    最高の実機利用率)。実機3件(`CsKoushik9/Google-Search-using-RPA`
    の`GoogleSearch.xaml`、`lin8231/762-impl`の`FindPHEVs.xaml`×2、
    いずれも動的VB式`Url`+静的リテラル`Url`の両方を確認)で`Browser`は
    常に`{x:Null}`——`GoBack`と違い変数参照の実例は未確認(見つかれば
    同じ`RefreshBrowser`/`GoBack`パターンの`# TODO`へ倒す)。

    `Browser`が`{x:Null}`の場合、意味論は「現在のページで指定URLへ
    遷移する」——主要ブラウザ共通の標準キーボードショートカット
    `Ctrl+L`(アドレスバーへフォーカス)に続けてURLを入力し`Enter`で
    確定する、という`GoBack`/`RefreshBrowser`と同じグローバル
    `keyboard.send_keys()`経路の延長。URL文字列自体は`TypeInto`
    (知見110)と同じ`_pywinauto_type_keys_escape()`(`~^%+(){}`の
    pywinauto特殊構文エスケープ)を再利用する——URLのクエリ文字列に
    `+`/`(`/`)`等が現れる実例が確認済みのため、エスケープ無しでは
    `type_keys`相当の誤動作リスクがある。"""

    browser: Expr = None
    url: Expr = None
    display_name: str | None = None


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
    コード生成は実機確認済みの`Text`属性名を信頼する。

    知見159追記: `full_text`/`ignore_hidden`は`ui:GetFullText`
    (GitHub code searchで300件ヒット)専用のフィールド——`GetText`とは
    別の活動だが、`Target`/出力`Text`という構造は同じで意味論も近い
    (「要素のテキストを取得する」)ため同じ`GetTextNode`を再利用する。
    実機確認した違い: (1)出力`Text`は属性形ではなく`<ui:GetFullText.
    Text><OutArgument>...</OutArgument></ui:GetFullText.Text>`という
    プロパティ要素形(`_in_argument_property_expr`で抽出)、(2)
    `IgnoreHidden`(実機確認済みの値は常に`"False"`)という追加属性を
    持つ。ただし公式ドキュメントは`GetText`を「可視テキストのみ・
    最大4096文字」、`GetFullText`を「非表示/切り詰められた部分を含む
    フルテキスト」と明確に区別しており、両方をpywinautoの同じ
    `window_text()`へ変換するのは`GetText`単体より一段弱い近似だと
    `_generate_get_text`の警告コメントで明示する(`full_text=True`の
    場合は別の警告文言を出す)。"""

    selector: str | None = None
    display_name: str | None = None
    text: Expr = None
    delay_before: Expr = None
    delay_ms: Expr = None
    continue_on_error: Expr = None
    full_text: bool = False
    ignore_hidden: Expr = None


@dataclass
class SelectFileNode:
    """`<ui:SelectFile>`(知見192、GitHub code searchで157件ヒット)。
    OSのネイティブなファイル選択ダイアログを表示し、ユーザーが選んだ
    ファイルを`SelectedFile`(単一選択)/`SelectedFiles`
    (`Multiselect="True"`時、複数選択)へ返す活動。`UiPath/skills`
    公式リポジトリのStudio実機ground-truthコーパス+実機2件
    (`GSA/RPA-OSS`・`lezwon/uipath_deoldify`)で確認した構成は
    `Filter`(拡張子フィルタ文字列、例`"Excel Files (*.xls, *.xlsx)|
    *.xls;*.xlsx"`)+`SelectedFile`(出力)+`InitialDirectory`/
    `Multiselect`/`SelectedFiles`(ground-truthコーパスでは全件
    `{x:Null}`——実機で非null値を確認できず未検証)。

    ネイティブOSダイアログでのユーザー操作そのものを表すため、
    headless実行環境で代わりに応答する安全な方法は無い——知見176の
    `GetPassword`・知見174の`GetAttribute`と同じ「常にTODOへ倒れる
    活動でも、ノード型を適切にモデル化する価値がある」という判断の
    3例目として、`Filter`の有無を問わず常に`# TODO`へ倒す。"""

    display_name: str | None = None
    filter: Expr = None
    initial_directory: Expr = None
    multiselect: Expr = None
    selected_file: Expr = None
    selected_files: Expr = None


@dataclass
class SelectFolderNode:
    """`<ui:SelectFolder SelectedFolder="..." />`(知見252、10回目発見
    パスで発見、タグ名限定GitHub検索で211件ヒット)。`SelectFileNode`
    (知見192)のフォルダ版——実機2件(`cameronmcnz/uipath-tutorials`の
    `SelectedFolderProject/Main.xaml`、`rohanbaraskar/UiPath-11`の
    `Get_Driectory_info/Main.xaml`)+ground-truthいずれも一致した
    唯一の属性構成: `SelectedFolder`(出力)のみ——`Filter`等の入力
    プロパティ自体が存在しない(フォルダ選択ダイアログには拡張子
    フィルタの概念が無いため、`SelectFile`より更に単純)。

    `SelectFile`と同じ理由(ネイティブOSダイアログでのユーザー操作
    そのものを表し、headless実行環境で代わりに応答する安全な方法が
    無い)で常に`# TODO`へ倒す——知見176・174・192と同じ「常にTODOへ
    倒れる活動でも、ノード型を適切にモデル化する価値がある」という
    判断の4例目。"""

    display_name: str | None = None
    selected_folder: Expr = None


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
class SelectMultipleItemsNode:
    """`<ui:SelectMultipleItems>`(知見262、`SelectItemNode`(知見112)の
    複数選択版、タグ名限定GitHub検索で11件ヒット——本調査で最も著者多様性
    が薄い実装済み活動の1つ、独立した実在著者は2名のみ(`PacktPublishing`
    の書籍サンプル4件は同一書籍の別章で近似重複、`cecilioalvarez`の
    2リポジトリは同一人物)。

    `MultipleItems`(選択するラベルのVB配列リテラル、実機確認済み
    `["Saab","Opel"]`/`["Castellano","Euskera"]`——`JoinPDFNode`
    (知見201)の`FileList`と同じ`ArrayLiteral`AST→Python`list`変換が
    そのまま使える)、`.Target`(`SelectItemNode`と同じ`ui:Target`/
    セレクタ構造、実機2件とも`webctrl tag='SELECT' type=
    'select-multiple'`というHTML複数選択要素)、`AddToSelection`/
    `AlterIfDisabled`/`ContinueOnError`/`DelayAfter`/`DelayBefore`
    (ground-truth+実機2件とも全件`{x:Null}`)。

    `AddToSelection`(公式ドキュメント確認済み:「既存の選択に追加する
    か、先にリストボックスの選択をクリアするか」を制御)は実機・
    ground-truthいずれも未設定のままで、未設定時の既定挙動が公式
    ドキュメントに明記されていない——明示的に設定されている場合は
    `# TODO`へ倒す(`SelectItemNode.alter_if_disabled`とは違い、
    こちらは真の既定値が未確認のため)。

    `SelectItemNode`と同じ`pywinauto`の汎用`.select()`アクセサ
    (「`Select Item`の裏の実装APIは未確認、`SimulateClick`相当と
    推定」という既存の警告コメントを継承)を、`MultipleItems`の各
    要素に対して順に呼ぶ——複数回の`.select()`呼び出しが選択を累積
    するか置き換えるかは未確認の追加の近似(既知の限界として明示的に
    警告コメントへ記録する)。"""

    selector: str | None = None
    display_name: str | None = None
    multiple_items: Expr = None
    add_to_selection: Expr = None
    alter_if_disabled: Expr = None
    continue_on_error: Expr = None
    delay_before: Expr = None
    delay_after: Expr = None


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
class WaitUiElementAppearNode:
    """`<ui:WaitUiElementAppear>`(知見264、DisplayNameは「Find Element」、
    `UiPath.Core.Activities.WaitUiElementAppear`、タグ名限定GitHub検索で
    746件ヒット——マウスキーボード系の2回目発見パスで最も強い実務需要の
    信号)。`selector`は`ui:WaitUiElementAppear.Target`配下の`ui:Target`
    要素の`Selector`属性(`ClickNode`等と同じ構造)。

    実機2件以上(`piyushagarwal08/JU-Notes`の`UiPath/BlankProcess1/
    Flowchart.xaml`——`ui:AnchorBase`配下ではない完全な単独使用例、
    `HarshadRanganathan/uipath-learning`の`Selectors/
    Notepad_Basic_Recording_Selector.xaml`)で確認した構成——
    `FoundElement`(出力、実機確認した全件で`{x:Null}`——`UiElement`型の
    出力変数を一切束縛しない、`GetFileInfoX`等で問題になった型付き
    オブジェクトのダウンストリーム利用が実機で一度も確認できなかった
    ため、確認済みの範囲内で安全に無視できる)、`WaitActive`/
    `WaitVisible`(実機確認した全件で`{x:Null}`または`"False"`——
    `"True"`の実例は確認できていない)。公式ドキュメント(WebSearch経由
    確認)によれば「対象のUI要素が画面に出現するまでポーリングする」が
    基本動作で、`WaitVisible`/`WaitActive`はそれぞれ「可視になるまで」
    「アクティブになるまで」待機を追加する。`Target.TimeoutMS`の既定値
    は公式ドキュメント確認済みで30000ms(=30秒)——実機確認した全件とも
    `<ui:Target.TimeoutMS><InArgument x:TypeArguments="x:Int32" /></...>`
    という値未設定の空`InArgument`形だったため、非既定の`TimeoutMS`値
    自体は実機未確認——本活動では捕捉対象に含めず、確認済みの既定
    30秒をそのままハードコードする。

    `pywinauto`の`WindowSpecification.wait(...)`(文字列条件+秒単位の
    `timeout`引数、インストール済みの実`pywinauto`ソースで確認済みの
    標準API)が直接対応する——条件文字列は`'exists'`(既定)に
    `WaitVisible=True`時は`' visible'`、`WaitActive=True`時は
    `' active'`を追加で組み合わせる。`"True"`の実例自体は実機未確認
    だが、公式ドキュメントの説明(「可視/アクティブになるまで待機を
    追加する」)が曖昧さ無く、対応する`pywinauto`マッピングも単純な
    文字列連結のため機械的に対応できる——`AlterIfDisabled`等の過去の
    判断とは違い、値自体の意味論に不確実性が無いケースとして両方の
    値に対応する。"""

    selector: str | None = None
    display_name: str | None = None
    found_element: Expr = None
    wait_active: Expr = None
    wait_visible: Expr = None


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
class InsertDataTableNode:
    """`<ui:InsertDataTable DataTable="..." TableName="..."
    ExistingDbConnection="..." AffectedRecords="..." />`(知見230、
    `ExecuteQuery`/`ExecuteNonQuery`(知見114)と同じ`UiPath.Database.
    Activities`、タグ名限定GitHub検索で33件ヒット)。ground-truthには
    `DataTable`/`TableName`が無いが(知見197と同種の「ground-truthは
    網羅的ではない」実例)、実機複数件(`allenlooplee/RPABook`の
    `SQLiteProcess.xaml`・`UiPath532/UiPathExamples`の`Day 6/
    DataBaseWithUiPath/Main.xaml`)いずれも`DataTable`(入力)+
    `TableName`(挿入先テーブル名)+`ExistingDbConnection`+
    `AffectedRecords`(出力、影響行数)+`ContinueOnError`の構成で
    確認した——`TimeoutMS`はground-truth・実機いずれにも無く
    (`ExecuteQuery`/`ExecuteNonQuery`とは違う)未対応。

    `DatabaseConnect`(知見114)が生成する`sqlite3.Connection`
    (`row_factory = sqlite3.Row`設定済み)が`ExistingDbConnection`の
    実体——`Connection.executemany()`+パラメータ化された`?`
    プレースホルダ(SQLiteのネイティブ形式)が対応する。`DataTable`が
    dict行表現の場合のみ列名が分かるため`INSERT INTO table (col1,
    col2) VALUES (?, ?)`形で正確に対応でき、list行表現の場合は列名が
    無いため`INSERT INTO table VALUES (?, ?)`(全列を順序通りに
    与えると仮定、`# WARNING`コメントで明示)という保守的な縮退に
    倒す——`WriteCsvFile`(知見185)・`OutputDataTable`(知見184)と
    同じ「両表現に対応するが、dict行の時だけ正確な動作」という既存
    方針。"""

    data_table: Expr = None
    table_name: Expr = None
    existing_db_connection: Expr = None
    affected_records: Expr = None
    continue_on_error: Expr = None
    display_name: str | None = None


@dataclass
class BulkInsertNode:
    """`<ui:BulkInsert DataTable="..." TableName="..."
    ExistingDbConnection="..." AffectedRecords="..." />`(知見230、
    `InsertDataTable`と属性構成が全く同じ兄弟活動、タグ名限定GitHub
    検索で9件ヒット——実機`andresporras3423/scrapingRealState`の
    `fincaRaiz.xaml`、`kissandor/thesis`の`ResoultToDataBase.xaml`で
    確認。`TableName`はスキーマ修飾名(`"stage.datosVivienda"`)も
    実機確認済み——特別な解釈はせずそのまま文字列として使う。意味論・
    実装は`InsertDataTable`と完全に同じ(`_generate_insert_data_table_
    family_body`を共用)——UiPath側で両者が別クラスである理由
    (バッチサイズ等の内部最適化の違い)はPython側の挙動には影響
    しない。"""

    data_table: Expr = None
    table_name: Expr = None
    existing_db_connection: Expr = None
    affected_records: Expr = None
    continue_on_error: Expr = None
    display_name: str | None = None


@dataclass
class DatabaseTransactionNode:
    """`<ui:DatabaseTransaction DatabaseConnection="..."
    UseTransaction="...">`(知見231、`InsertDataTable`/`BulkInsert`
    (知見230)と同じ`UiPath.Database.Activities`、タグ名限定GitHub
    検索で28件ヒット、公式表示名「Start Transaction」)。ground-truth
    (`marcelocruzrpa/uipath-ai-skills`)・実機複数件(`Uipathtutorials/
    Usecases`の`Beginners/DatabaseActivities.xaml`・`angelagongli/
    TheSixFootOffice`の`PullOfficeSetting.xaml`)で構造を確認した——
    `.Body`配下は`AttachWindow`(知見153)・`CommentOut`(知見225)と
    同じ直接`Sequence`(`ActivityAction`ラップ無し)。

    公式ドキュメント(WebSearch経由確認、`database-transaction`
    ページ)で2つのモードがあると確認した——①既存の`DatabaseConnection`
    を渡す形(その場合`ConnectionString`/`SecureConnectionString`は
    無視される)、②`ConnectionString`+`ProviderName`で新規接続を自ら
    確立する形(`DatabaseConnect`と同じ引数)。実機
    `angelagongli/TheSixFootOffice`は②のMySQL例(`ProviderName=
    "MySql.Data.MySqlClient"`)だったが、`DatabaseConnect`(知見114)
    自体が`"System.Data.SQLite"`以外のプロバイダを未確認として
    `# TODO`へ倒す既存方針のため、②の自己接続モードは本活動でも
    同様に未対応とし①(既存接続渡し)のみ対応する。

    **`UseTransaction`の実装上の制約**: 公式ドキュメントで
    `UseTransaction=False`時は「各操作が個別にコミットされる」と
    確認——これは`ExecuteNonQuery`/`InsertDataTable`/`BulkInsert`の
    既存コード生成が既に各自`connection.commit()`を呼ぶ実装
    (知見114・230)と完全に一致するため、`Body`をそのまま展開する
    だけで正しく動作する。しかし`UseTransaction=True`(「全操作を
    1つのトランザクションにまとめ、失敗時は全体をロールバックする」
    という意味論、ground-truthの既定値)は、`Body`配下の子活動が
    既に個別に`commit()`してしまう既存コード生成とそのままでは
    両立しない(個々の文が実行直後に確定してしまい、後続の失敗時に
    ロールバックしても先に確定済みの文は取り消せない)——子活動の
    `commit()`呼び出しをスキップさせる仕組み(`ScopeInfo`のような
    文脈伝播機構)が無いと正しいall-or-nothing保証を再現できない
    ため、でっち上げたtry/except(見た目だけ機能するが実際には保証
    しないコード)を生成するより`UseTransaction=True`自体を
    `# TODO`へ倒す判断とした——`ModifyText`(知見224)の「部分的に
    正しいより全体を拒否」と同じ判断。"""

    database_connection: Expr = None
    use_transaction: str | None = None
    continue_on_error: Expr = None
    connection_string: Expr = None
    secure_connection_string: Expr = None
    provider_name: Expr = None
    body: list["Node"] = field(default_factory=list)
    display_name: str | None = None


@dataclass
class ExtractTextNode:
    """`<uast:ExtractText Source="..." StartingText="..."
    EndingText="..." Result="..." ExtractOptions="BetweenStrings" />`
    (知見232、サブエージェントによる5回目の新規発見パスで発見、
    `UiPath.Activities.System.Text`名前空間——知見220で`ChangeCase`
    調査時に発見済みだったが当時は実装対象に採用しなかった`uast:`を
    初めて定数化。タグ名限定GitHub検索で41件ヒット)。実機6件
    (`sree-hari-s/ACME-REFramework`の`Check_PDF.xaml`、OCR抽出した
    PDFテキストから`Check Number`/`Check Date`等のラベル後の値を
    個別に抜き出す定番用途)いずれも`ExtractOptions="BetweenStrings"`
    +`IgnoreDuplicates="False"`+`MatchCase="False"`+
    `ExtractBaseURLOnly="False"`+単一文字列出力`Result`の構成——
    ground-truth(`marcelocruzrpa/uipath-ai-skills`)には`Result`
    (単数)属性が無く`FirstMatch`/`Results`(複数)のみ記載されている
    が(知見197・230と同種の「ground-truthは網羅的ではない」実例)、
    実機は常に`Result`(単数)属性を使い`FirstMatch`/`Results`は
    `{x:Null}`のまま——公式ドキュメント(WebSearch経由確認、
    Studio UI上の表示名は「First extracted text」/「All extracted
    text」)の「最初の1件を返す」出力と同じ役割と判断し`Result`の
    みに対応する(`FirstMatch`/`Results`は実機で一度も使われている
    のを確認できず未対応)。

    「StartingTextとEndingTextの間の文字列を抜き出す」——マーカー
    文字列自体は出力に含まれない(`TextToLeftRight`知見222の
    `Separator`除外と同じ判断、他RPAツール(WorkFusion/Electroneek)
    の同種機能も同じ規約と確認——UiPath公式ドキュメントには含む/
    除くの明記は無いが強い状況証拠による推測)。`StartingText`が
    見つからない・`EndingText`が`StartingText`より後に見つからない
    場合の挙動は未確認——`str.index()`の自然な`ValueError`に委ねる
    (フォールバック値を捏造しない既存方針、`TextToLeftRight`等と
    同じ)。`MatchCase`は公式ドキュメント確認済みの既定`False`
    (大文字小文字を区別しない検索、出力自体は元の大文字小文字を保持)
    ——`ModifyText`の`FindAndReplaceTextModification`(知見224)と
    同じ判断。`IgnoreDuplicates`/`ExtractBaseURLOnly`が`"True"`の
    場合の挙動は実機で一度も確認できず未対応。`ExtractOptions`が
    `"BetweenStrings"`以外(URL抽出等、`ExtractBaseURLOnly`属性の
    存在から推測される別モードの可能性)の場合も未対応。"""

    source: Expr = None
    starting_text: Expr = None
    ending_text: Expr = None
    result: Expr = None
    extract_options: str | None = None
    match_case: str | None = None
    ignore_duplicates: str | None = None
    extract_base_url_only: str | None = None
    display_name: str | None = None


@dataclass
class FindAndReplaceNode:
    """`<uast:FindAndReplace Source="..." ValueToFind="..."
    ReplaceWith="..." MatchCase="..." Result="..." />`(知見279、
    discovery-fresh-pass-11で発見、`UiPath.Activities.System.Text`
    (`uast:`)名前空間の単独活動——`ModifyText`配下専用の子活動
    `FindAndReplaceTextModificationNode`(知見224、`UiPath.Core.
    Activities.TextModifications`、別の名前空間)とは**別のクラス**
    (タグ名は同じ"FindAndReplace"でも別パッケージ)。タグ名限定GitHub
    検索で多数の実機ヒット、本調査最多クラス)。

    ground-truth(`marcelocruzrpa/uipath-ai-skills`)+実機
    (`wan-chee-tin/hr-offer-letter-automation`の`HR Offer Letter
    Automation/Performer_OfferLetterAutomation/Framework/Process.xaml`
    ——同じ変数(`EmailBody`)へ`Source`/`Result`を往復させながら
    `FindAndReplace`を8回連続で呼ぶ「文字列テンプレート置換」の定番
    パターンを確認)で`Source`+`ValueToFind`(実機確認済みは静的
    リテラルのみ、`_FullName`等のプレースホルダ文字列)+`ReplaceWith`
    (静的リテラル・動的VB式の両方確認)+`MatchCase`(ground-truth/
    実機とも唯一の確認値`"False"`)+`Result`(ground-truthには無いが
    実機で常に使用——知見197/230と同種の「ground-truthは網羅的で
    ない」実例)の構成を確認。

    `FindAndReplaceTextModificationNode`(知見224)が確立した
    `re.sub(re.escape(search), lambda _m: replace, source, flags=
    re.IGNORECASE)`をそのまま再利用する——プレーンな文字列検索
    (正規表現ではない)、`MatchCase`省略時/`"False"`時は大文字小文字
    を区別しない、置換文字列は`lambda`経由(`\\1`等の逆参照記法誤解釈
    を防ぐ)。"""

    source: Expr = None
    value_to_find: Expr = None
    replace_with: Expr = None
    match_case: str | None = None
    result: Expr = None
    display_name: str | None = None


@dataclass
class ChangeCaseNode:
    """`<uast:ChangeCase Source="..." ChangeCaseOptions="..."
    Result="..." />`(知見279、discovery-fresh-pass-11で発見、
    `UiPath.Activities.System.Text`(`uast:`)名前空間の単独活動——
    `ModifyText`配下専用の子活動`ToUpperLowerTextModificationNode`
    (知見224、`UiPath.Core.Activities.TextModifications`、別の
    名前空間)とは**別のクラス**。知見220で見送った際は「タグ名限定
    検索で7件のみ」だったが、discovery-fresh-pass-11が`ChangeCase
    Options`という別の確認用属性名で再検索して9件ヒットを再発見、
    さらに実機3件を確認した。

    ground-truth(`marcelocruzrpa/uipath-ai-skills`)+実機2件
    (`itsdevdeep/CPQ-Automation`の`Add PL Attributes.xaml`で
    `ChangeCaseOptions="LowerCase"`、`RajdipDuttaa/
    ACME_Data_Extraction`の`PDFExtraction.xaml`で`ChangeCaseOptions=
    "UpperCase"`——両方の値を独立に実機確認)で`Source`+
    `ChangeCaseOptions`+`Result`の構成を確認。

    `ToUpperLowerTextModificationNode`(知見224)が確立した
    `.lower()`/`.upper()`への変換をそのまま再利用する——`UseCurrentCulture`
    (カルチャ依存の大文字小文字変換)オプションは実機で一度も確認
    できず常にPythonの`str.lower()`/`str.upper()`(カルチャ非依存)を
    使う判断も継承する。"""

    source: Expr = None
    change_case_options: str | None = None
    result: Expr = None
    display_name: str | None = None


@dataclass
class GetLastDownloadedFileNode:
    """`<ui:GetLastDownloadedFile DownloadFolder="..." File="..."
    Timeout="..." IgnoreFiles="...">`(知見233、公式表示名「Wait for
    Download」、サブエージェントによる5回目の新規発見パスで発見、
    タグ名限定GitHub検索で129件ヒット)。ground-truth
    (`marcelocruzrpa/uipath-ai-skills`)・実機多数(`alvaroqr14/
    UiPath_Ejemplo_WaitForDownload`・`mantri13/Usecase2_ActiveLoans`・
    `Apress/Robotic-Process-Automation-Using-UiPath-StudioX`)で確認
    した構造——`.Body`配下は`ModifyText`(知見224)と同じ
    `ActivityAction`(`DelegateInArgument`無し)+`Sequence`。

    `File`出力は.NETの`FileInfo`型だが、`ForEachFileX`/`ForEachFolderX`
    (知見190)の既存方針(`FileInfo`/`DirectoryInfo`をでっち上げず
    絶対パス文字列そのものとして表現する)を再利用する——実機で確認
    できたダウンストリーム利用は`.Name`(`alvaroqr14`の実例)と
    `.FullName`(`mantri13`の実例、既存の`.fullname`ハンドラで対応
    済み)のみで、`GetFileInfoX`/`GetFolderInfoX`(知見で見送り済み)
    のような「未確認の多数のプロパティを持つ不透明な型付きオブジェ
    クト」問題には当たらない——このため`render.py`の
    `_apply_chained_property`に`.Name`(`os.path.basename()`)を
    新規追加した。

    `Timeout`省略時は公式ドキュメント確認済みの既定`300`秒。
    `IgnoreFiles`(カンマ区切りの拡張子リスト、「ダウンロード完了
    まで無視する拡張子」——ブラウザの一時ファイル拡張子
    `.crdownload`/`.part`等を除外する用途、公式ドキュメント確認済み)
    は実機で非null値(`"xlsx, crdownload"`)を確認済み。`DownloadFolder`
    配下のファイル一覧をBody実行前後でスナップショット比較し、新規
    出現したファイルのうち`IgnoreFiles`の拡張子に該当しないものを
    ポーリングで探す近似実装とする(`知見206`の画像照合近似・
    知見184/197のCSV変換近似と同じ「正確な再現ではなく近似と明記」
    方針)——内部のポーリング間隔自体はUiPath側の正確な値が未確認の
    ため本トランスパイラ独自の値を使う。`FileResource`は実機で一度も
    非nullの値を確認できず未対応。"""

    download_folder: Expr = None
    file: Expr = None
    timeout: Expr = None
    ignore_files: Expr = None
    file_resource: Expr = None
    body: list["Node"] = field(default_factory=list)
    display_name: str | None = None


@dataclass
class CheckTrueNode:
    """`<ui:CheckTrue Expression="..." ErrorMessage="..." />`(知見234、
    公式表示名「Check True」、サブエージェントによる6回目の新規発見
    パスで発見、タグ名限定GitHub検索で303件ヒット)。ground-truth
    (`marcelocruzrpa/uipath-ai-skills`)・実機複数件(`flindersuni/
    rpa-Flinders.Helpers`の`LoginToFlindersDashboard/Main.xaml`、
    `Expression="[processSuccessful]"`+`ErrorMessage="[processMessage]"`
    ——「ログイン処理が失敗した場合は例外を投げる」という注釈付き)
    いずれも`Expression`(ブール式)+`ErrorMessage`の2属性のみ。

    公式ドキュメント(WebSearch経由確認、`check-true`ページ)で
    「式がfalseの場合、カスタムメッセージ付きの例外を実行時に投げる」
    と確認済み——.NET側の正確な例外型(コミュニティ情報では
    `CheckPointException`が既定の可能性があるが未確定)は未確認の
    ため、既存の`_EXCEPTION_TYPE_MAP`の未知型フォールバックと同じ
    汎用`Exception`で代用する。`Expression`のブール変換は`If`/`While`
    (知見61)と同じ`_vb_bool()`ヘルパーを再利用する。"""

    expression: Expr = None
    error_message: Expr = None
    display_name: str | None = None


@dataclass
class CheckFalseNode:
    """`<ui:CheckFalse Expression="..." ErrorMessage="..." />`(知見234、
    `CheckTrue`の反転版、公式表示名「Check False」、タグ名限定GitHub
    検索で33件ヒット)。ground-truth・実機(`flindersuni/
    rpa-Flinders.Helpers`、`Expression="[String.IsNullOrWhiteSpace(
    credentialName)]"`——「認証情報名が未入力の場合は例外を投げる」
    という注釈付き)いずれも`CheckTrue`と全く同じ`Expression`+
    `ErrorMessage`の2属性構成。公式ドキュメント確認済みの「式がtrueの
    場合、カスタムメッセージ付きの例外を実行時に投げる」——`CheckTrue`
    とは条件の真偽が反転するだけの意味論。"""

    expression: Expr = None
    error_message: Expr = None
    display_name: str | None = None


@dataclass
class VerifyExpressionNode:
    """`<uta:VerifyExpression Expression="..." ContinueOnFailure="..."
    Result="..." .../>`(知見278、discovery-fresh-pass-11で発見、
    `UiPath.Testing.Activities`パッケージ、タグ名限定GitHub検索で
    2644件ヒット)。`CheckTrueNode`(知見234)と同じ「式がfalseの場合に
    例外を投げる」意味論だが、`ContinueOnFailure`(確認済みの既定値
    `"True"`)により失敗時に例外を投げず続行できる点が異なる——
    テスト自動化フレームワーク(UiPath Test Manager/Studio Test
    Automation)専用のソフトアサーション機構。

    公式ドキュメント(WebSearch経由確認、`verify-expression`
    API参照ページ)で「`ContinueOnFailure`の.NET API既定値は`False`
    (式がfalseなら例外を投げて実行を停止)、`True`なら例外を投げずに
    続行する」と確認済み——ただしStudioが新規配置時に自動補完する
    シリアライズ既定値はground-truth(`marcelocruzrpa/
    uipath-ai-skills`)で`"True"`(.NET API既定値とは異なる、Studio
    自体の UI既定選択)。実機`flindersuni/rpa-Flinders.Foundation`の
    `TestCases/TestDetectEnvironmentTest.xaml`(`CheckTrue`/
    `CheckFalse`(知見234)と同じ作者の別リポジトリ)で`Expression`
    (ブール式)+`ContinueOnFailure="True"`(実機確認済みの値)+
    `TakeScreenshotInCaseOfFailingAssertion`/`...Succeeding...`
    (いずれも`"False"`)の構成を確認——`Result`は同サンプルでは
    未使用(純粋なアサーション用途)だが出力として捕捉対応する。

    `AlternativeVerificationTitle`/`OutputMessageFormat`/
    `KeepScreenshots`/`ScreenshotsPath`は実機で非null値を一度も確認
    できず未対応(`GetFileInfoX`等と同じ「未確認の設定値は推測しない」
    判断)。`ErrorMessage`相当の属性はこの活動には存在しないため、
    本トランスパイラ独自の汎用メッセージを使う。姉妹活動`uta:
    VerifyExpressionWithOperator`(`Operator`列挙型+`FirstExpression`/
    `SecondExpression`の2項比較版)は別途の確認が必要なため今回は
    対象外とする。"""

    expression: Expr = None
    continue_on_failure: str | None = None
    result: Expr = None
    alternative_verification_title: Expr = None
    output_message_format: Expr = None
    keep_screenshots: Expr = None
    screenshots_path: Expr = None
    take_screenshot_in_case_of_failing_assertion: str | None = None
    take_screenshot_in_case_of_succeeding_assertion: str | None = None
    display_name: str | None = None


@dataclass
class VerifyExpressionWithOperatorNode:
    """`<uta:VerifyExpressionWithOperator FirstExpression="..."
    SecondExpression="..." Operator="..." ContinueOnFailure="..."
    Result="..." .../>`(知見281、discovery-fresh-pass-12が`uta:
    VerifyExpression`(知見278)の姉妹活動として深掘りした、`UiPath.
    Testing.Activities`パッケージ、タグ名限定GitHub検索で約3684件
    ヒット)。`VerifyExpressionNode`と同じ`ContinueOnFailure`ベースの
    ソフトアサーション機構だが、単一のブール式ではなく`FirstExpression`
    /`SecondExpression`を`Operator`で比較する2項版。

    実機4件(`psri981/Group8-300-762`の`TestCases/
    TestGetAndAddCrewInfo.xaml`で`Operator="Equality"`+VB式
    `[OutputProducers]`/`["Antoine Fuqua"]`の両方を確認、`matheus-tam/
    CICD_Demo`の`TestCase.xaml`で`Operator="GreaterThan"`+VB式
    `[2]`/`[1]`、`mouyang2001/rpa-group-12`の`TestCases/
    TestCase_OCR_Set2_Mitech.xaml`で`Operator="Contains"`——C#式
    言語プロジェクト(`CSharpValue`、知見129で既に確認済みの対象外
    範囲、`FirstExpression`/`SecondExpression`が`None`になり自然に
    `# TODO`へ倒れる)、公式`UiPath/uipathcli`の`examples/projects/
    calculator/AddTwoNumbersTest.xaml`でも`Operator="Equality"`
    (こちらもC#式)を確認)で、実機で確認できた`Operator`値は
    `Equality`/`GreaterThan`/`Contains`に加え、discovery-fresh-
    pass-12のタグスコープ検索で`Inequality`(9件)/`LessThan`(6件)の
    ヒットも確認済み——いずれも.NET比較演算子の標準的な意味論のため
    (`Equality`/`Inequality`/`GreaterThan`/`LessThan`は`VerifyExpression
    WithOperator`と同じソフトアサーション機構内で使われる単純な比較、
    `Contains`は`FirstExpression.Contains(SecondExpression)`という
    .NET `String.Contains()`の確定済み意味論)5値とも対応する。

    比較は既存の`VB_CMP_HELPER_NAME`(`_vb_cmp`、`Switch`の値アーム
    (知見136)等で既に確立済み)を`Equality`/`Inequality`/
    `GreaterThan`/`LessThan`で再利用し、`Contains`のみ`VB_CSTR_HELPER_
    NAME`経由の文字列包含判定(`second in first`)で対応する。"""

    first_expression: Expr = None
    second_expression: Expr = None
    operator: str | None = None
    continue_on_failure: str | None = None
    result: Expr = None
    alternative_verification_title: Expr = None
    output_message_format: Expr = None
    keep_screenshots: Expr = None
    screenshots_path: Expr = None
    take_screenshot_in_case_of_failing_assertion: str | None = None
    take_screenshot_in_case_of_succeeding_assertion: str | None = None
    display_name: str | None = None


@dataclass
class CreateDirectoryNode:
    """`<ui:CreateDirectory Path="..." ContinueOnError="..."
    Output="..." />`(知見235、`CopyFile`/`MoveFile`/`CreateFile`の
    兄弟活動、サブエージェントによる6回目の新規発見パスで発見、
    タグ名限定GitHub検索で1760件ヒット)。ground-truth
    (`marcelocruzrpa/uipath-ai-skills`)・実機複数件(`PacktPublishing/
    Robotic-Process-Automation-Projects`の`Chapter 05/Framework/
    TakeScreenshot.xaml`、`Path="[screenshotFileInfo.DirectoryName]"`
    ——`If.Else`内で実際に有効な構成として確認、`CommentOut`無効化で
    はない)いずれも`Path`のみが非null、`ContinueOnError`/`Output`は
    実機で一度も非null値を確認できなかった。

    `Output`は公式ドキュメント確認済み(「作成したフォルダへの参照、
    後続の活動で使用する」)で.NETの`DirectoryInfo`型——実機で非null
    の実例が無いため未対応とする(`GetFileInfoX`/`GetFolderInfoX`と
    同じ「未確認の型付きオブジェクト」を新規にでっち上げない判断)。
    `ContinueOnError`も実機で非null値が無いため未対応。`Path`の作成
    は.NET`Directory.CreateDirectory(path)`の確立済みAPIコントラクト
    (既存ディレクトリがあっても例外にならず、中間の親ディレクトリも
    まとめて作成する)——`CopyFile`(知見117)と同じ「UiPath固有の
    ドキュメントではなく.NET自体の公開APIコントラクトに基づく判断」
    であり、Pythonの`os.makedirs(path, exist_ok=True)`に直接対応
    する。"""

    path: Expr = None
    continue_on_error: Expr = None
    output: Expr = None
    display_name: str | None = None


@dataclass
class MergeDataTableNode:
    """`<ui:MergeDataTable Destination="..." Source="..."
    MissingSchemaAction="Add" />`(知見236、`JoinDataTables`/
    `SortDataTable`等と同じDataTable表現の延長、サブエージェントに
    よる6回目の新規発見パスで発見、タグ名限定GitHub検索で319件
    ヒット)。ground-truth(`marcelocruzrpa/uipath-ai-skills`)・実機
    (`HarshadRanganathan/uipath-learning`の`Excel & Data Tables/
    Excel_Merge_Sheets_Approach_1.xaml`、`Destination="[dt2]"`/
    `Source="[dt1]"`→`Destination="[dt3]"`/`Source="[dt2]"`という
    連鎖マージ、`CommentOut`無効化ではないことを独立に再取得・確認)
    いずれも`Destination`+`Source`+`MissingSchemaAction="Add"`のみ。

    .NET`DataTable.Merge(sourceTable)`は呼び出し先(`Destination`)を
    インプレースで変更するインスタンスメソッド(新規テーブルを返す
    のではない)——`Destination`の`list[dict]`/`list[list]`表現
    (知見114/115)を`.extend()`でインプレース拡張することで同じ
    参照共有の意味論を再現する。`DataTable.Merge()`は行を値コピー
    する(参照共有ではない)ため、dict行は浅いコピー(`dict(_r)`)で
    追加する——`Source`側の後続変更が`Destination`側に伝播しない
    ことを保証する。`MissingSchemaAction`∈{Add, Ignore, Error,
    AddWithKey}(.NET公式enum確認済み)のうち実機は常に`"Add"`——
    本トランスパイラのDataTable表現(dict行、固定スキーマ無し)は
    そもそも列の追加を自動的に許容するため`"Add"`の意味論が
    `.extend()`だけで自然に成立する。他の値(`Error`/`Ignore`/
    `AddWithKey`——列制約の強制やキー基準の重複排除が必要)は未対応。
    """

    destination: Expr = None
    source: Expr = None
    missing_schema_action: str | None = None
    display_name: str | None = None


@dataclass
class FormatValueNode:
    """`<ui:FormatValue Value="...">`(知見237、`.Format`プロパティ
    配下に`GeneralNumberFormatProvider`/`CurrencyNumberFormatProvider`/
    `DateTimeFormatProvider`のいずれか1つの子要素を持つ、サブエージェ
    ントによる6回目の新規発見パスで発見、タグ名限定GitHub検索で
    13件ヒット——いくつかは`AutoFor/uipath-ir-builder`の合成生成物
    のため独立の実機確認数は実質5〜6件とやや薄い)。`Value`は実機
    (`psri981/Group8-300-762`の`Main.xaml`、`CurrencyNumberFormat
    Provider DecimalDigits="0" Symbol="$"`+直後の`grossString =
    genericVal`代入で確認)で入出力同じ変数へのインプレース変換
    (フォーマット済み文字列への上書き)であることを確認した。

    `GeneralNumberFormatProvider`/`CurrencyNumberFormatProvider`は
    `DecimalDigits`+`DecimalSeparator`+`GroupSeparator`(+`Currency`
    のみ`Symbol`)——ground-truth既定値`"."`/`","`以外は実機で一度も
    確認できず未対応。Pythonの`'{:,.Nf}'.format(_vb_cdbl(value))`
    (`Currency`はさらに`Symbol`を前置)に対応する。

    `DateTimeFormatProvider`は`Pattern`(.NETカスタム日付書式文字列、
    実機`mtayyab153/RPA`の`HBL Reporting Date Format/Main.xaml`で
    `Pattern="dddd, dd MMMM yyyy"`を確認——`ForEachRow`内の実際に
    有効な実例、`CommentOut`無効化ではない)——.NETの日付トークン
    (`yyyy`/`yy`/`MMMM`/`MMM`/`MM`/`dddd`/`ddd`/`dd`のみ、確認済みの
    範囲に限定)をPythonの`strftime()`書式トークンへ変換する。単独の
    `M`/`d`(ゼロ埋め無し、Windows/Linux間で`%-m`等の移植性問題が
    ある)・時刻系トークン(`HH`/`mm`/`ss`/`tt`等、実機未確認)・
    クォート付きリテラル(.NET構文、実機未確認)は未対応。`Value`は
    既存の`.NET DateTime`→`datetime.datetime`表現(`File.
    GetLastWriteTime`→`datetime.datetime.fromtimestamp(...)`と同じ
    既存の確立済み表現)を前提とし`.strftime()`を直接呼ぶ。"""

    value: Expr = None
    format_kind: str | None = None
    decimal_digits: str | None = None
    decimal_separator: str | None = None
    group_separator: str | None = None
    symbol: str | None = None
    pattern: str | None = None
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
class WriteTextFileNode:
    """`<ui:WriteTextFile FileName="..." Text="..." />`(知見212、
    `ReadTextFile`(知見16)の対になる書き込み側)。実機6件
    (`PacktPublishing/Robotic-Process-Automation-RPA-for-Developers`・
    `spritlesoftware/Uipath-RPA-AutomationProjects`・`vajrang-b/
    UiPathIn30Days`)で確認した構成は`FileName`+`Text`のみ——
    ground-truthの`File`(常に`{x:Null}`、`FileInfo`オブジェクト参照と
    推測・未モデル化)+`Output`(常に未設定、書き込み後の`FileInfo`
    出力と推測・未モデル化)は実機で一度も非`{x:Null}`の値を確認
    できなかった。

    `ReadTextFile`(知見108)とは違い、ground-truthに`Encoding`属性
    自体が存在しない(実機でも一度も確認できず)——公式ドキュメント上は
    `Encoding`未指定時の既定がBOM検出→失敗時はシステムのANSIコード
    ページという`ReadTextFile`と同じ挙動だが、`ReadTextFile`が既存の
    実機round-trip確認済みの判断でそのまま`"utf-8"`を使っている
    (知見108のdocstring参照)のに合わせ、本活動も同じ`"utf-8"`で
    書き込む——読み書き対の既存の一貫した判断を維持する。"""

    display_name: str | None = None
    file_name: Expr = None
    text: Expr = None
    file: Expr = None
    output: Expr = None


@dataclass
class ExtractFilesNode:
    """`<uascw:ExtractFiles>`(知見217、`UiPath.System.Activities`
    パッケージ内だが`ui:`とは別の名前空間
    `clr-namespace:UiPath.Activities.System.Compression.Workflow`
    ——知見216で`ui:`限定検索が0件だった原因と判明)。ground-truthの
    属性構成は`Content`+`DestinationFolder`+`DestinationFolderInfo`+
    `File`+`FileToExtract`+`Password`+`CodePage`(既定`"Default"`)+
    `ConflictResolution`(既定`"Replace"`)+
    `ExtractToADedicatedFolder`(既定`"True"`)+
    `SkipUnsupportedFiles`(既定`"False"`)——11属性と多い。

    実機1件(`duyphat2003/Working-with-files-and-folders_Practice-
    solution`)で確認した構成は`FileToExtract`+`DestinationFolder`+
    `CodePage="Default"`+`ExtractToADedicatedFolder="False"`
    (ground-truthの既定`"True"`とは異なる値、実機では常に`False`)+
    `SkipUnsupportedFiles="False"`のみ——`Content`/`File`/
    `DestinationFolderInfo`/`Password`は常に`{x:Null}`(暗号化
    アーカイブの実例は未確認のため`Password`は未対応)。

    Pythonの`shutil.unpack_archive()`(標準ライブラリ、zip/tar系の
    拡張子を自動判別——`.rar`/`.7z`は未対応だが新規依存無しで
    カバーできる範囲)が直接対応する(宛先フォルダが存在しない場合は
    自動作成することを対話的に確認済み)。`ExtractToADedicatedFolder=
    "True"`(アーカイブ名のサブフォルダへ展開すると推測、実機未確認)・
    `CodePage`が`"Default"`以外・`SkipUnsupportedFiles="True"`
    (実機未確認の挙動)・`Password`設定時はいずれも`# TODO`へ倒す。"""

    display_name: str | None = None
    file_to_extract: Expr = None
    destination_folder: Expr = None
    content: Expr = None
    file: Expr = None
    destination_folder_info: Expr = None
    password: Expr = None
    code_page: str | None = None
    extract_to_a_dedicated_folder: str | None = None
    skip_unsupported_files: str | None = None


@dataclass
class CompressFilesNode:
    """`<uascw:CompressFiles>`(知見218、`ExtractFiles`(知見217)と同じ
    `uascw:`名前空間)。ground-truthの属性構成は`CompressedFileInfo`+
    `CompressedFileName`+`CompressedResource`+`Password`+
    `ResourcesToArchive`+`SecurePassword`+
    `AllowDuplicateContentNames`(既定`"False"`)+`CodePage`(既定
    `"Default"`)+`CompressionLevel`(既定`"Normal"`)+
    `EncryptionAlgorithm`(既定`"Classic"`)+
    `OverrideExistingFile`(既定`"True"`)+プロパティ要素形の
    `ContentToArchive`(`scg:List<InArgument(x:String)>`、圧縮対象の
    ファイル/フォルダパスのリスト)——11属性+1リストと多い。

    実機1件(`Apress/Robotic-Process-Automation-Using-UiPath-
    StudioX`の`Chapter_9_CompressedFileActivtiesExercise`——書籍の
    圧縮活動専用の演習章)で確認した構成は`ContentToArchive`(フォルダ
    パス1件)+`CompressedFileName`(フラット文字列、出力zipパス)+
    `CodePage="Default"`+`CompressionLevel="Normal"`+
    `OverrideExistingFile="True"`のみ——`Password`/`ResourcesToArchive`
    /`CompressedResource`は`{x:Null}`、`EncryptionAlgorithm`/
    `SecurePassword`/`AllowDuplicateContentNames`は実機XAMLに属性
    自体が無い(既定値のまま変更されず、Studioが省略した)。
    `CompressedFileInfo`(出力、`FileInfo`オブジェクトと推測)は
    `[Saved.Values(Of FileInfo)("...")]`という複雑なVB式で設定されて
    いたが未モデル化。

    フォーラム調査(公式ドキュメントには記載無し)で確認: `Content
    ToArchive`にフォルダパスを渡すと、そのフォルダの**中身**がzipの
    トップレベルに入る(フォルダ自身の名前はアーカイブ内に含まれない
    ——「エンクロージングフォルダが失われる」という複数の実機報告と
    一致)。サブフォルダ構造自体は保持される。Pythonの`zipfile`
    (標準ライブラリ)で、ファイルパスはそのまま・フォルダパスは
    `os.walk()`+`os.path.relpath()`(フォルダ自身を基準とした相対
    パス)でこの挙動を再現する。`Password`/`SecurePassword`(`zipfile`
    標準では暗号化zipの作成は不可、`pyzipper`——既存の確認済み依存
    ——なら理論上可能だが実機確証が無いため見送り)・確認済み以外の
    `EncryptionAlgorithm`/`AllowDuplicateContentNames`設定時は
    `# TODO`へ倒す。"""

    display_name: str | None = None
    content_to_archive: list[Expr] = field(default_factory=list)
    compressed_file_name: Expr = None
    compressed_file_info: Expr = None
    compressed_resource: Expr = None
    resources_to_archive: Expr = None
    password: Expr = None
    secure_password: Expr = None
    code_page: str | None = None
    compression_level: str | None = None
    encryption_algorithm: str | None = None
    override_existing_file: str | None = None
    allow_duplicate_content_names: str | None = None


@dataclass
class IsMatchNode:
    """`<ui:IsMatch>`(知見213、GitHub code searchで「`ui:IsMatch`」
    (タグ名限定、`IsMatch`単体では一般的なWPF/XAMLアプリとの偽陽性が
    大量に混入することを本tickで発見)で再検索し実機2件
    (`mehmetbesli/UiPathExamples`・`GSA/Credit_Card_Logging_Bot`)で
    確認した構成。`Input`+`Pattern`+`RegexOption`+`Result`(出力、
    フラット属性形)のみ——`BuilderPattern`/`Model`/
    `IsBuilderTabModified`はStudioの正規表現ビルダーウィザードの
    UI状態メタデータであり、ランタイムの意味論には無関係(確認済み、
    無視する)。

    `RegexOption`は.NET`RegexOptions`の`[Flags]`enumがカンマ区切りで
    直列化される——実機2件で確認した値は`"IgnoreCase"`単体と
    `"IgnoreCase, Compiled"`(ground-truthの既定値と同一)の2種のみ。
    `Compiled`はPythonの`re`モジュールに対応する概念が無い(内部で
    自動キャッシュされるため)安全に無視できるが、未確認の他フラグ
    (`Multiline`/`Singleline`等)が含まれる場合は`# TODO`へ倒す。"""

    display_name: str | None = None
    input: Expr = None
    pattern: Expr = None
    regex_option: str | None = None
    result: Expr = None


@dataclass
class ReplaceNode:
    """`<ui:Replace>`(知見220、`IsMatch`(知見213)と同じ正規表現
    ビルダー系の兄弟活動、GitHub code searchで「`"ui:Replace"`」
    タグ名限定359件ヒット)。ground-truthの属性構成は`Input`+
    `Pattern`+`Replacement`+`IsBuilderTabModified`+`RegexOption`
    (既定`"IgnoreCase, Compiled"`)——`Result`(出力)はground-truthの
    デフォルト状態では現れないが、実機で確認済み。

    実機2件(`piyushagarwal08/JU-Notes`・`LowyShin/
    lwrpa-uip-moveoldfiles`)で確認した構成は`Input`+`Pattern`+
    `Replacement`+`Result`+`RegexOption="IgnoreCase, Compiled"`
    (両実機で同一値)——両実機とも`Input`と`Result`が同じ変数
    (インプレース上書き)。`BuilderPattern`/`Model`/
    `IsBuilderTabModified`は`IsMatch`と同じ正規表現ビルダーウィザードの
    UI状態メタデータで無視する。

    `.NET Regex.Replace(input, pattern, replacement)`は
    Pythonの`re.sub(pattern, replacement, input)`に対応する
    (引数の意味順序が同じ)。`RegexOption`は`IsMatch`と同じ判断
    (`"IgnoreCase"`/`"IgnoreCase, Compiled"`のみ対応)。`Replacement`
    内の`$1`等の.NET後方参照記法とPythonの`\1`記法の違いは変換しない
    (知見144の`Regex.Replace`→`re.sub`と同じ既存の判断を継承、実機
    2件のいずれも後方参照を使っていない)。"""

    display_name: str | None = None
    input: Expr = None
    pattern: Expr = None
    replacement: Expr = None
    regex_option: str | None = None
    result: Expr = None


@dataclass
class MatchesNode:
    """`<ui:Matches>`(知見221、`IsMatch`/`Replace`(知見213・220)と
    同じ正規表現ビルダー系の兄弟活動、GitHub code searchで「`"ui:
    Matches"`」タグ名限定448件ヒット)。ground-truthの属性構成は
    `FirstMatch`(出力)+`Input`+`Pattern`+`IsBuilderTabModified`+
    `RegexOption`(既定`"IgnoreCase, Compiled"`)——`Result`は
    ground-truthには現れないが実機で確認済み。

    実機6件(`mehmetbesli/UiPathExamples`1件・`mantri13/
    Usecase2_ActiveLoans`5件)で、出力は**2種類**確認できた:
    `Result`(1件、集合型と推測されるが具体的な型が実機XAMLだけからは
    確認できない)と`FirstMatch`(5件、`(?<=ラベル:\\s*).*`のような
    lookbehindパターンで「ラベルの後の値だけ抜き出す」という単一文字列
    抽出の定番用途、`out_BankAcctName`/`out_LoanDate`/`out_Amount`等の
    変数名から単一値であることが明確)。`Result`の正確な型(リスト?
    `MatchCollection`相当?)が未確認のため、本活動は`FirstMatch`のみ
    対応し`Result`設定時は`# TODO`へ倒す。

    `.NET Regex.Match(input, pattern).Value`に対応する——マッチしない
    場合、.NETの`Match.Value`は`null`ではなく空文字列`""`を返す
    (.NET公式ドキュメントで確立された既知の挙動)ため、Pythonの
    `re.search()`が`None`を返す場合も同様に`""`へ変換する。
    `RegexOption`は`IsMatch`と同じ判断を再利用する。"""

    display_name: str | None = None
    input: Expr = None
    pattern: Expr = None
    regex_option: str | None = None
    first_match: Expr = None
    result: Expr = None


@dataclass
class TextToLeftRightNode:
    """`<ui:TextToLeftRight>`(知見222)。実機2件
    (`adithya0414/StringManipulation_StringActivities`・
    `DariusDangi/GenerateYearlyReports`)で属性構成を確認:
    `FullText`+`Separator`+`TextToLeft`(出力)+`TextToRight`(出力)
    +`SeparatorKey`(既定`"Custom"`、もう1種`"NewLine"`も実機確認、
    いずれも`Separator`属性自体には実際の区切り文字列が常に
    正しく入っている——`SeparatorKey="NewLine"`時は
    `Separator="&#13;&#10;"`)。

    公式ドキュメント(WebSearch経由確認)によれば「`Separator`の
    最初の出現位置で分割、区切り文字自体は出力に含まない」。
    `SeparatorKey`が`"Custom"`/`"NewLine"`以外の値を取る場合、
    その時の`Separator`属性値が正しく事前入力されるか未確認のため
    `# TODO`へ倒す——`SeparatorKey`自体はPython側のロジックには
    使わず、常に`Separator`の実際の値で`str.split(sep, 1)`する
    (2つの実機確認済みプリセットいずれも`Separator`属性が
    直接使える値になっているため)。

    `Separator`が`FullText`中に見つからない場合の挙動は公式
    ドキュメント・フォーラムいずれにも記載が無く未確認——
    `GetRowItem`(知見177/183)や`UpdateRowItem`と同じ「不明な場合は
    推測せず自然な例外を出す」方針に従い、`TextToRight`側の
    代入で`IndexError`が自然に発生するに任せる(フォールバック値を
    捏造しない)。`CaseSensitive`(既定On)・`CustomSeparatorEnabled`は
    実機でも確認用の差分として現れなかったため未対応。"""

    display_name: str | None = None
    full_text: Expr = None
    separator: Expr = None
    separator_key: str | None = None
    text_to_left: Expr = None
    text_to_right: Expr = None


@dataclass
class SplitTextNode:
    """`<uast:SplitText Source="..." Separator="..." SeparatorKey="..."
    Results="..." />`(知見249、9回目発見パスのTier 3候補、タグ名限定
    GitHub検索で22件ヒット——`UiPath.Activities.System.Text`
    (`uast:`、知見220・232で既に発見済みの第4の名前空間、`ui:`では
    無い点に注意)の比較的新しい活動のため実機ヒットが薄い)。実機
    (`liamsrowley/uipath-product-tracker`の
    `GetBrandAndLinksDictionary.xaml`)で確認: `Source`(入力文字列)+
    `Separator`+`SeparatorKey`+`Results`(出力、複数形——`IEnumerable
    <String>`相当)。

    `TextToLeftRight`(知見222、同じ`SeparatorKey`という概念を持つが
    `ui:`名前空間の別の活動)とは**違う**、`SeparatorKey="NewLine"`
    の時の`Separator`実際の直列化値が確認できた——`TextToLeftRight`
    は実CRLFバイト(`"&#13;&#10;"`)だったが、`SplitText`は実機2件
    (本活動+`CombineText`、下記)いずれも`Separator="NewLine"`という
    **文字そのまま**のラベル文字列だった(実際の改行文字ではない)。
    つまり`uast:`名前空間のこの活動群は`ui:TextToLeftRight`と直列化
    規約が異なり、`Separator`属性の生の値をそのまま使うと区切り文字
    として機能しない——`SeparatorKey`の値に応じてPython側で実際の
    区切り文字へ変換する必要がある。確認済みは`"NewLine"`→`"\\r\\n"`
    (.NETの`Environment.NewLine`、本プロジェクト既存の`vbCrLf`/CRLF
    規約と統一)のみ——他の`SeparatorKey`値(`Comma`/`Tab`等、公式
    ドキュメント確認済みの既定値一覧に存在が推定されるが実機未確認)
    は見送る。`Separator`属性自体はこの意味論の違いに気付いた記録
    として保持するが、コード生成では参照しない。"""

    source: Expr = None
    separator: str | None = None
    separator_key: str | None = None
    results: Expr = None
    display_name: str | None = None


@dataclass
class CombineTextNode:
    """`<uast:CombineText Source="..." Separator="..."
    SeparatorKey="..." Result="..." />`(知見249、`SplitText`の逆方向、
    タグ名限定GitHub検索で12件ヒット)。実機
    (`mhmdreda99/UipathProjects`の`randomweather/Main.xaml`)で確認:
    `Source`(入力、文字列の集合——実機サンプルは`New List(Of String)
    From {...}`というVBコレクション初期化子式で、本トランスパイラの
    式パーサーが未対応のため構文解析自体が失敗し自然に`# TODO`へ倒れる
    ことを確認済み)+`Separator`+`SeparatorKey`+`Result`(出力、単数形
    ——`SplitText.Results`とは違い文字列1つ)。`SplitText`と全く同じ
    `SeparatorKey="NewLine"`→`Separator`が文字そのまま"NewLine"という
    ラベルになる直列化規約を確認(2つの独立した実機サンプルで一致——
    偶然ではなく`uast:`名前空間全体の一貫した規約と判断)。`SplitText`
    と同じ理由で`SeparatorKey="NewLine"`のみ対応し`"\\r\\n"`で
    `str.join()`する。"""

    source: Expr = None
    separator: str | None = None
    separator_key: str | None = None
    result: Expr = None
    display_name: str | None = None


@dataclass
class GetEnvironmentVariableNode:
    """`<ui:GetEnvironmentVariable Variable="..." VariableValue="..." />`
    (知見215、知見214のタグ名限定GitHub検索で再発掘)。実機5件
    (`jainsamyak/UiPath-Attendance-Framework-UAF`・`masiref/HandyML`)で
    確認した`Variable`の値は`"MachineName"`/`"OSVersion"`/`"UserName"`
    /`"TEMP"`/`"[Environment.UserName]"`(動的式)。

    公式ドキュメント(WebSearch経由確認)で解決順序が確認できた:
    ①`System.Environment`の既知プロパティ名(`MachineName`等)と一致
    するか先に確認、②一致しなければOS環境変数として解決
    (Windowsでは`EnvironmentVariableTarget.User`→`Process`の順)。
    実機で確認した`MachineName`/`UserName`はPythonの`platform.node()`
    /`getpass.getuser()`が十分に近い対応——`OSVersion`は.NETの
    `Environment.OSVersion.ToString()`の正確な書式を再現する標準的な
    Python対応が無いため未対応のまま`# TODO`へ倒す。それ以外
    (`TEMP`等)は実際のOS環境変数名として`os.environ.get()`で解決する
    ——Windows固有のUser-levelレジストリ永続化までは再現しない
    (`os.environ`はプロセス起動時にスナップショットされた値のみ、
    `ReadTextFile`知見108と同種の「公式の正確な既定ではないが実用上
    十分」という判断)。`Variable`が静的リテラルでない場合(動的式)は
    事前にどちらの解決経路か判断できないため常に`# TODO`。"""

    display_name: str | None = None
    variable: Expr = None
    variable_value: Expr = None


@dataclass
class SetEnvironmentVariableNode:
    """`<ui:SetEnvironmentVariable Name="..." Value="..." />`(知見223、
    `GetEnvironmentVariable`(知見215)の兄弟活動、タグ名限定GitHub検索
    で96件ヒット)。ground-truth(`<ui:SetEnvironmentVariable
    Name="{x:Null}" Value="{x:Null}" />`)・UiPath公式ドキュメント
    (`UiPath/skills`リポジトリの`activity-docs/UiPath.System.Activities/
    .../SetEnvironmentVariable.md`)いずれも`Name`/`Value`の2つの
    InArgumentのみで設定項目・出力無し、常にOS環境変数として
    設定する(`GetEnvironmentVariable`の`System.Environment`既知
    プロパティ名との2経路判断は無い——書き込みは常にOS環境変数
    のみ)。`os.environ[name] = value`に対応する——プロセス内
    スコープのみで、Windows固有のUser-levelレジストリへの永続化までは
    再現しない(`GetEnvironmentVariable`知見215と同種の「公式の正確な
    既定ではないが実用上十分」という判断)。"""

    display_name: str | None = None
    name: Expr = None
    value: Expr = None


@dataclass
class GetEnvironmentFolderNode:
    """`<ui:GetEnvironmentFolder FolderPath="..." SpecialFolder="..." />`
    (知見254、10回目発見パスの残り候補、タグ名限定GitHub検索で88件
    ヒット)。`GetEnvironmentVariable`(知見215)とは別のタグ——
    `GetEnvironmentVariableNode`と混同しないこと。

    実機4件(`flindersuni/rpa-Flinders.Foundation`の
    `GetCommonDataDirectory.xaml`→`SpecialFolder="MyDocuments"`、
    `lezwon/uipath_deoldify`の`Main.xaml`→`SpecialFolder="UserProfile"`、
    `kconstantej/UiPath_RPA_KenConstante`の`Main.xaml`→
    `SpecialFolder="MyDocuments"`)+ground-truth
    (`SpecialFolder="Desktop"`、既定値)で確認した3つの値のみ対応する
    ——`SpecialFolder`は.NETの`Environment.SpecialFolder`列挙型で、
    公式ドキュメント(WebFetch経由確認)によれば21個の値が存在するが、
    実機で確認できたのは`Desktop`/`MyDocuments`/`UserProfile`の3つ
    だけのため、それ以外(`ProgramFiles`・`ApplicationData`等)は
    `# TODO`へ倒す——でっち上げたパス対応を用意しない。

    `FolderPath`(出力)は.NETの`Environment.GetFolderPath()`が返す
    絶対パス文字列——Windows環境での確認済みマッピング
    (`UserProfile`→`C:\\Users\\<user>`、`Desktop`/`MyDocuments`→その
    直下の`Desktop`/`Documents`サブフォルダ)をPython標準の
    `os.path.expanduser("~")`+`os.path.join()`で再現する(新規依存
    不要、本プロジェクトの実デプロイ対象であるWindows上で正確に
    一致する組み込みAPIの組み合わせ)。公式ドキュメントは「フォルダが
    解決できない場合は空文字列を返し例外を投げない」と明記するが、
    `os.path.expanduser()`はホームディレクトリが解決できない稀な
    状況でも入力をそのまま返すだけで例外を投げない——`os.environ`
    スナップショットに依存する`GetEnvironmentVariable`(知見215)と
    同種の「公式の正確な既定ではないが実用上十分」という判断。"""

    display_name: str | None = None
    folder_path: Expr = None
    special_folder: str | None = None


@dataclass
class FindAndReplaceTextModificationNode:
    """`<ucat:FindAndReplaceTextModification SearchText="..."
    ReplaceText="..." MatchCase="..." />`(知見224、`ui:ModifyText`
    専用の子活動、`TEXT_MODIFICATIONS_NS`名前空間)。実機多数
    (`Apress/Robotic-Process-Automation-Using-UiPath-StudioX`・
    `ok-omes-escrow/...`等)で`SearchText`+`ReplaceText`+任意の
    `MatchCase`(`"True"`時のみ現れる、省略時は公式ドキュメント
    (WebSearch経由確認、`find-and-replace`ページ)で既定`False`
    =大文字小文字を区別しない一致と確認済み)を確認した。`SearchText`
    はプレーンな文字列検索(正規表現ではない、`Replace`/`IsMatch`
    (知見213・220)とは違う)——`re.escape()`で正規表現特殊文字を
    無効化した上で`re.sub()`(`MatchCase`に応じて`re.IGNORECASE`
    有無)を使う、置換文字列側は`lambda`経由で渡し`\\1`等の.NET側に
    無い逆参照記法として誤解釈されないようにする。"""

    display_name: str | None = None
    search_text: Expr = None
    replace_text: Expr = None
    match_case: str | None = None


@dataclass
class TrimTextModificationNode:
    """`<ucat:TrimTextModification />`(知見224、`ui:ModifyText`専用の
    子活動)。実機複数件で常に属性無し(`TrimType`等の左右限定オプション
    は実機で一度も確認できず)——.NETの`String.Trim()`(引数無し、
    前後の空白文字を全て除去)相当、Pythonの`str.strip()`に対応する。"""

    display_name: str | None = None


@dataclass
class ToUpperLowerTextModificationNode:
    """`<ucat:ToUpperLowerTextModification ModificationType="..." />`
    (知見224、`ui:ModifyText`専用の子活動)。実機
    (`ptrielisabeth/RPA-Robotic-Process-Automation-`)で
    `ModificationType="Lowercase"`を確認、公式ドキュメント
    (`to-upper-lower-text-modifications`ページ、WebSearch経由確認)の
    「大文字/小文字のどちらかへ変換する」説明と活動名自体から
    もう一方の値`"Uppercase"`も対になると判断、2値のみ対応
    (それ以外・未指定は`# TODO`)。`UseCurrentCulture`(カルチャ依存の
    大文字小文字変換)オプションは実機で一度も確認できず未対応——
    常にPythonの`str.upper()`/`str.lower()`(カルチャ非依存)を使う。"""

    display_name: str | None = None
    modification_type: str | None = None


@dataclass
class ModifyTextNode:
    """`<ui:ModifyText SourceText="..." OutputText="...">`(知見224、
    タグ名限定GitHub検索で167件ヒット)。ground-truth
    (`marcelocruzrpa/uipath-ai-skills`の`studio-ground-truth`、
    `<ui:ModifyText OutputText="{x:Null}" SourceText="{x:Null}">`)・
    実機複数件(`Apress/Robotic-Process-Automation-Using-UiPath-
    StudioX`等)で確認した構造——`SourceText`/`OutputText`の2属性と
    `.Body`配下`ActivityAction`(`DelegateInArgument`無し、`ForEach`
    (知見5)と違い反復変数を束縛しない)+`Sequence`(`body`、`ActivityAction`
    周りの抽出は既存の`_unwrap_body_sequence`/`_find_activity_action`
    ヘルパーを再利用)。`ExcelApplicationScope`のようなリソース/接続
    スコープではなく、`SourceText`を起点に`body`内の各子活動
    (`FindAndReplaceTextModification`/`TrimTextModification`/
    `ToUpperLowerTextModification`のみ対応——`CombineTextModification`
    は実機ヒット0件のため未対応)を順番に適用し`OutputText`へ代入する
    「文字列を線形に通す」単純な処理のため、実装の複雑さは低い。"""

    display_name: str | None = None
    source_text: Expr = None
    output_text: Expr = None
    body: list[Node] = field(default_factory=list)


@dataclass
class FindStartEndDateModificationNode:
    """`<ucad:FindStartEndDateModification Location="..." TimeUnit="..." />`
    (知見273、`ui:ModifyDate`専用の子活動)。公式ドキュメント
    (`modify-date`ページ、WebSearch経由確認)——「Find」(`Location`、
    対象期間の最初/最後の日を選ぶ)+「Of」(`TimeUnit`、対象期間の単位
    ——週/月/年)という2属性構成。実機(`AravindS-26/Fitness_Tracker`の
    `Main.xaml`)で`Location="LastDay"`+`TimeUnit="Month"`(「今月の
    最終日を求める」)という組み合わせのみ確認——`Location="FirstDay"`
    や`TimeUnit="Week"`/`"Year"`は実機未確認のため未対応。"""

    display_name: str | None = None
    location: str | None = None
    time_unit: str | None = None


@dataclass
class ModifyDateNode:
    """`<ui:ModifyDate SourceDate="..." OutDate="..." OutText="..."
    CustomDateFormat="..." UseCustomDateFormat="..." FormatAsText="...">`
    (知見273、discovery-fresh-pass-9が報告した`ModifyDate`(`
    AddOrSubtractFromDate`とは別のground-truthファイル、知見227で
    "too thin"と判断した`AddOrSubtractFromDate`とは異なる活動)、
    タグ名限定GitHub検索で12件ヒット)。`ModifyTextNode`(知見224)と
    全く同じ`.Body`配下`ActivityAction`(`DelegateInArgument`無し)+
    `Sequence`構造——`SourceDate`を起点に`body`内の子活動
    (`FindStartEndDateModificationNode`のみ対応)を順番に適用し
    `OutDate`へ代入する「日付を線形に通す」処理。

    実機2件(`PakamTharunReddy/RPA`の`RPA_Training/Format.xaml`、
    `AravindS-26/Fitness_Tracker`の`Main.xaml`)で構成を確認したが、
    前者は`FindDayOfWeekDateModification`(`Direction`のみ設定、
    `DayOfWeek`属性が無く設定不完全)・`AddSubtractTimePeriodDate
    Modification`(`Value`のみ設定、単位/符号の属性が無く設定不完全)
    という2つの子活動を含む——明らかに未完成の研修用プレースホルダー
    (属性が意味を成す最小限のセットすら揃っていない)と判断し、この
    2つの子活動は実装対象に含めない(`ModifyTextNode`が実機ヒット0件の
    `CombineTextModification`を見送った判断と同じクラス)。後者
    (`AravindS-26/Fitness_Tracker`)は`FindStartEndDateModification
    Location="LastDay" TimeUnit="Month"`という単一の子活動のみで
    構成が完結しており(`OutDate`が`s:DateTime`型変数、`If Condition=
    "[todaydate=lastday]"`という下流の等価比較のみ確認——型未確認の
    広い下流アクセスという懸念には当たらない)、こちらのみを実装対象と
    する。

    `SourceDate="[Today]"`という実機確認済みの動的式は、VB組み込み
    識別子`Today`(裸の識別子、ドット無し)——本修正まで`render.py`に
    一切対応が無く(確認済みのギャップ、`DateTime.Now`等の静的クラス
    参照も同様に無変換のまま素通しされていた)、本活動の実装の前提
    として`render.py`へ`Today`→`datetime.date.today()`・`Now`→
    `datetime.datetime.now()`(裸の識別子、及び`DateAndTime.`/
    `DateTime.`修飾形の両方)という一般的な修正を追加した——`ModifyDate`
    専用ではなく、任意の式でこれらのVB組み込み識別子を使っていた
    既存の(未発見の)バグも同時に解消する。

    `OutText`/`UseCustomDateFormat`/`CustomDateFormat`/`FormatAsText`
    は実機2件とも(前者は設定不完全な研修用プレースホルダーのため
    判断材料にならない、後者は`OutText={x:Null}`/`CustomDateFormat=
    {x:Null}`で未使用)クリーンな確認済み実例が無いため、いずれかが
    設定されている場合は活動全体を`# TODO`へ倒す(`OutDate`のみ対応)。"""

    display_name: str | None = None
    source_date: Expr = None
    out_date: Expr = None
    out_text: Expr = None
    use_custom_date_format: str | None = None
    custom_date_format: Expr = None
    format_as_text: str | None = None
    body: list[Node] = field(default_factory=list)


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
class GetFromClipboardNode:
    """`<ui:GetFromClipboard TimeoutMS="..."><ui:GetFromClipboard.Result>
    <OutArgument ...>...</OutArgument></ui:GetFromClipboard.Result>
    </ui:GetFromClipboard>`(知見243、8回目発見パスで発見、タグ名限定
    GitHub検索で86件ヒット)。`SetToClipboardNode`の逆方向——実機2件
    (`tylorbunting/P006---Update-COVID19-Dashboard`の`Main.xaml`、
    `datasherlock/aws-workspace-login-rpa`の`Code/Get Authorization
    Code.xaml`)で確認。`Result`の`x:TypeArguments`は`x:String`/
    `ui:GenericValue`の両方が実在するが、いずれのダウンストリーム利用も
    `.Length`(文字列扱い)のみ——単純な文字列として表現してよい。

    `TimeoutMS`は`{x:Null}`(既定)・`5000`等の実値いずれも確認したが、
    UI Automation系活動一般の既知の意味論(公式ドキュメント確認済み、
    `Copy Selected Text`等——「活動の実行がエラーを投げるまでの最大
    待機時間」)であり、「クリップボードに新しい内容が現れるまで
    ポーリングする」という意味ではない。`pyperclip.paste()`は現在の
    クリップボード内容を即座に読むだけで待機自体が発生しないため、
    対応するタイムアウト概念が存在しない——`ContinueOnError`等と同じ
    「意味のある対応先が無いため無視する」既存の判断パターンを適用し、
    モデル化しない(`# TODO`も出さない、本当に無関係なため)。"""

    result: Expr = None
    display_name: str | None = None


@dataclass
class CommentNode:
    """`<ui:Comment Text="..." />`(知見119、`PacktPublishing/
    Robotic-Process-Automation-Projects`の実機XAMLで発見)。アクティビティ
    木に挿入される純粋な注釈——`Text`は常に生のリテラル文字列(VbExprでは
    無い、実機確認済み)で実行時の挙動は一切無い。Pythonの`#`コメント行
    へ変換する。"""

    text: str


@dataclass
class CommentOutNode:
    """`<ui:CommentOut><ui:CommentOut.Body><Sequence
    DisplayName="Ignored Activities">...</Sequence></ui:CommentOut.Body>
    </ui:CommentOut>`(知見225、タグ名限定GitHub検索で5056件ヒット——
    本トランスパイラの既実装活動の中でも最多クラス)。Studioの
    「選択範囲をコメントアウト」操作でワークフロー上に残る、`Body`配下
    を**実行しないまま保持する**ラッパー——ground-truth
    (`marcelocruzrpa/uipath-ai-skills`)・実機複数件
    (`SuneetPatil/IRCTC-tatkal-booking`等)いずれも属性は`DisplayName`
    のみ(他の設定項目は無い)。`.Body`配下の構造は`AttachWindow`
    (知見153)と同じ——`ActivityAction`のラップ無しで直接`Sequence`
    1つが入る——ため既存の`_unwrap_body_sequence`をそのまま再利用
    できるが、コード生成では`body`の内容を一切辿らない(`Body`配下の
    子活動が副作用のあるコードを生成してしまうと、無効化されている
    はずの処理が実際に実行されてしまうため)。"""

    display_name: str | None = None
    body: list[Node] = field(default_factory=list)


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
    `# TODO`へ倒す。

    知見161追記: `ui:BrowserScope`(「Attach Browser」、GitHub code
    searchで3388件ヒット——`WindowScope`よりさらに多い!)も同じ意味論
    (既存のブラウザウィンドウに接続して`Body`を実行、起動は行わない)
    の別活動だと判明した——`WindowScope`と同じ`ActivityAction`+
    `DelegateInArgument`のラッパー構造。`Browser`(アタッチ先を指す
    既存の`UiBrowser`型変数への入力参照、実機確認した9件以上全てで
    `{x:Null}`)・`UiBrowser`(アタッチ結果を受け取る出力バインディング、
    `ApplicationWindow`と同種)・`ContinueOnError`という3つの追加属性を
    持つが、`SearchScope`/`TimeoutMS`は`WindowScope`と共有の既存
    フィールドをそのまま再利用できた。`BrowserType`(`"Chrome"`/
    `"Firefox"`/`"IE"`等、実機確認済み)は単純な注釈情報(どのブラウザ
    エンジンかを示すだけで、透過的ラッパーの動作自体には影響しない)
    として保持するのみで、decline判定の対象にはしない。"""

    selector: str | None = None
    body: list["Node"] = field(default_factory=list)
    display_name: str | None = None
    application_window: Expr = None
    search_scope: Expr = None
    timeout_ms: Expr = None
    window: Expr = None
    browser: Expr = None
    browser_type: str | None = None
    ui_browser: Expr = None
    continue_on_error: Expr = None


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
class StartProcessNode:
    """`<ui:StartProcess FileName="..." Arguments="..."
    WorkingDirectory="..." ExecutionType="..." Timeout="..."
    ContinueOnError="..." />`(知見247、9回目発見パスで発見、タグ名
    限定GitHub検索で458件ヒット)。`UiPath.System.Activities`の
    `.NET Process.Start()`相当のOSレベルプロセス起動活動——`ui:
    BeginProcess`(別のUiPath活動、`ProcessName`+`UsePackage`による
    別のUiPathプロセス呼び出しで全く別物、知見227の`InvokeProcess`と
    同じ「OSサブプロセス起動ではない」カテゴリ)とは無関係。実機2件
    (`cameronmcnz/uipath-tutorials`の`Xample07/Main.xaml`、`ShonHarsh/
    UiPath-Program-Start-Up-Bot`の`Methods/Process_StartProcess.xaml`
    ——後者はC#式言語プロジェクトで、既存の知見129・136の
    「でっち上げず`None`へ倒す」方針がそのまま適用される)で確認済み
    ——`FileName`+`Arguments`(常に`{x:Null}`または未確認の変数参照、
    実機で非nullの具体的な文字列値は未確認)+`WorkingDirectory`
    (常に`{x:Null}`)。

    公式ドキュメント(WebSearch経由確認)で`ExecutionType`
    (既定`Asynchronous`、他に`Synchronous`——`Timeout`付きで完了を
    待つ)+`Timeout`(既定30000ms、`Synchronous`時のみ意味を持つ)+
    `ContinueOnError`も確認したが、実機2件いずれも`ExecutionType`/
    `Timeout`属性自体が無い(既定値のAsynchronous)。`Arguments`は
    既存の`OpenApplicationNode`(知見154)が「Windowsコマンドライン
    引数の分割規則が未確認」として`Arguments`設定時に全体を見送って
    いるのと同じ理由・同じ判断で見送る——`FileName`のみ(+確信を
    持って対応できる`WorkingDirectory`、`subprocess.Popen()`の`cwd`
    引数に直接対応する単純な概念のため)をサポートする。"""

    file_name: Expr = None
    arguments: Expr = None
    working_directory: Expr = None
    execution_type: str | None = None
    timeout: Expr = None
    continue_on_error: Expr = None
    display_name: str | None = None


@dataclass
class OpenBrowserNode:
    """`<ui:OpenBrowser Url="..." BrowserType="...">...</ui:OpenBrowser>`
    (知見168、知見167で発見、GitHub code searchで2648件ヒット——
    `OpenApplication`の複数実例ヒットより多い)。`OpenApplication`
    (知見154)と同じ`ActivityAction`+`DelegateInArgument`(`Name`は
    `"ContextTarget"`固定)のラッパーを持つが、`Target`/`Selector`は
    一切持たない(既存のウィンドウに接続するのではなく、新しいブラウザ
    インスタンスを起動して`Url`へ移動する活動であるため)。

    実機5件(`PacktPublishing/Robotic-Process-Automation-RPA-for-
    Developers`・`allenlooplee/RPABook`・`piyushagarwal08/JU-Notes`・
    `miyaichi/CalculateClientSecurityHash`)で確認した属性は`Url`
    (生リテラル/動的VB式の両方を確認)・`BrowserType`(`"IE"`/
    `"Chrome"`/`"Firefox"`、実機確認済み)・`Hidden`/`NewSession`/
    `Private`(Boolean、実機確認済みの既定値は`Hidden="False"`/
    `NewSession="True"`/`Private="False"`——`Hidden="True"`の実例も
    確認したが「ヘッドレスモード」の正確な再現方法が未確認)・
    `UiBrowser`(開いたブラウザ参照を受け取る出力バインディング、
    `OpenApplication`の`ApplicationWindow`と同種)・
    `CommunicationMethod`(実機で一度も非`{x:Null}`の値を確認できず
    意味論未確認)。

    `BrowserType`別の実行ファイルパスは実機XAMLから直接読み取れず
    (OS/インストール環境依存の推測が必要になる)、`OpenApplication`の
    `subprocess.Popen([file_name])`のような「XAMLに明示された絶対
    パスをそのまま使う」安全な経路が無い——その代わり、Python標準
    ライブラリの`webbrowser.open(url)`(特定のブラウザ実行ファイルパス
    を一切推測せず、OS既定の方法でURLを開く、確認済みの標準API)を
    使う。`BrowserType`で指定された特定のブラウザが実際に開かれる
    ことまでは主張しない(`# WARNING`で明示)——`Hidden`/`NewSession`/
    `Private`/`UiBrowser`/`CommunicationMethod`が確認済みの既定値から
    外れている場合は`# TODO`へ倒す。"""

    url: Expr = None
    browser_type: str | None = None
    hidden: Expr = None
    new_session: Expr = None
    private: Expr = None
    ui_browser: Expr = None
    communication_method: Expr = None
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
    未対応と同種)。

    知見258: Excel/Word/マウスキーボード網羅性向上の調査パスで、独立に
    発見した実機2件(`starmanfrommars/Robotic-Process-Automation-Lab`・
    `Apress/Robotic-Process-Automation-Using-UiPath-StudioX`)が
    `WORD_NS`(専用スキーマURI)+`FilePath`属性という、知見121の
    ground-truth(`UI_NS`+`FileName`属性)とは別の直列化規約を使うことを
    発見した——両方を実機確認済みとしてディスパッチ登録し、`file_name`
    は両方の属性名を試す。"""

    file_name: str
    scope_var: str = "WordDocumentScope"
    body: list["Node"] = field(default_factory=list)


@dataclass
class PowerPointApplicationScopeNode:
    """`<ui:PowerPointApplicationScope PresentationPath="..."
    Password="..." CreateIfNotExists="..." AutoSave="..."
    TemplatePath="...">...</ui:PowerPointApplicationScope>`(知見274、
    discovery-fresh-pass-9が報告した新規活動ファミリー`UiPath.
    PowerPoint.Activities`——`python-pptx`は本体の`dependencies`に
    **既に存在する**既存の確認済み依存(エージェントが「新規オプション
    依存が必要」と報告したのは誤り、`pyproject.toml`を未確認だった)。
    `ExcelApplicationScopeNode`(知見97)/`WordApplicationScopeNode`
    (知見121)と同じ`ActivityAction`+`DelegateInArgument`構造だが、
    子活動が`scope_var`への暗黙のコンテキスト伝播ではなく明示的な
    `Presentation`引数を取る点が異なる(実機で確認済み、`Presentation=
    "[PowerPoint]"`という明示属性)——このため子活動は通常の独立した
    トップレベル活動として実装でき、Excel/Word版のような専用の
    `_in_scope`ディスパッチ機構は不要。

    実機2件(公式`UiPath-Services/StudioTemplates`の
    `CreatePowerPointPresentation`テンプレート、`Apress/
    Robotic-Process-Automation-Using-UiPath-StudioX`の
    `Chapter_10-PresentationAutomationExercise/Main.xaml`)で構成を
    確認。`PresentationPath`(実機2件とも静的リテラルのみ確認——動的式
    の実例が無いため`WordApplicationScopeNode.file_name`と同じ判断で
    `str`型のまま、`Expr`へ昇格しない)、`Password`(実機2件とも
    `{x:Null}`)、`CreateIfNotExists`(実機2件とも`"True"`——公式
    ドキュメント確認済みの「オンにすると存在しないファイルを新規作成、
    オフ(既定)だと存在しない場合エラー」という明確な意味論のため、
    両方の値を対応する)、`AutoSave`(実機2件とも唯一の確認値
    `"False"`——公式ドキュメント確認済みの既定値`"True"`(変更ごとに
    自動保存)とは異なり、`"False"`時は全ての子活動完了後に`Save
    PowerPoint File As`等で明示的に保存する必要がある、両サンプルとも
    事実その構成——`"True"`(変更ごとの自動保存)は実機未確認のため
    未対応)。`TemplatePath`(公式サンプルでのみ出現、`PresentationPath`
    と同じ値——公式ドキュメント確認済みでテンプレート指定は別活動
    `Create New PowerPoint Document`の役割であり本スコープ自体には
    意味が無いと判断、`PresentationPath`と異なる値の場合のみ`# TODO`
    へ倒す)。

    `openpyxl`/`python-docx`と同じファイルベース(ライブPowerPoint
    プロセス不要)の`python-pptx`で実装する——`AutoSave="False"`
    確認済みのため、スコープ自身は末尾で自動保存しない(`WordApplication
    ScopeNode`の無条件末尾`.save()`とは異なる判断、実機のAutoSave
    属性が明示的に異なる値だったことの反映)。"""

    presentation_path: str
    scope_var: str = "PowerPointPresentationScope"
    password: Expr = None
    create_if_not_exists: str | None = None
    auto_save: str | None = None
    template_path: Expr = None
    body: list["Node"] = field(default_factory=list)
    display_name: str | None = None


@dataclass
class FindAndReplaceTextInPresentationNode:
    """`<ui:FindAndReplaceTextInPresentation Presentation="..."
    SearchFor="..." ReplaceWith="..." MatchCase="..."
    WholeWordsOnly="..." NumberOfReplacements="..." />`(知見274、
    `ui:PowerPointApplicationScope`配下で使われる(が明示的な
    `Presentation`引数を取るため構造上は独立した活動)。実機2件で
    `MatchCase="False"`+`WholeWordsOnly="False"`(両サンプルとも唯一の
    確認値)+`NumberOfReplacements="{x:Null}"`(出力、両サンプルとも
    未使用)を確認。`SearchFor`は静的リテラルのみ確認、`ReplaceWith`は
    動的VB式(`Excel.Sheet(...).Cell(...)`等)の実例を確認済みのため
    `Expr`型。`WholeWordsOnly="True"`(単語境界一致)は実機未確認のため
    `# TODO`へ倒す。"""

    presentation: Expr = None
    search_for: Expr = None
    replace_with: Expr = None
    match_case: str | None = None
    whole_words_only: str | None = None
    number_of_replacements: Expr = None
    display_name: str | None = None


@dataclass
class InsertTextInPresentationNode:
    """`<ui:InsertTextInPresentation Presentation="..." ShapeName="..."
    SlideIndex="..." Text="..." />`(知見274)。実機2件で`ShapeName`
    (`"Title 1"`/`"Content Placeholder 2"`、PowerPointのプレース
    ホルダー名)+`SlideIndex`(リテラル整数`"3"`/`"4"`/`"5"`、または
    別の活動の出力変数経由の動的値)+`Text`(静的リテラル、動的VB式
    両方確認)を確認。`SlideIndex`は1始まりと推定する(本トランス
    パイラ独自の推定——`ExtractPDFPageRange`等、既存の全ページ番号系
    属性が1始まりで確認済みという一貫した判断に合わせた、UiPath自体の
    確定済み仕様としての直接確認ではない)——`python-pptx`の0始まり
    `Presentation.slides[idx]`へは`-1`して対応する。"""

    presentation: Expr = None
    shape_name: Expr = None
    slide_index: Expr = None
    text: Expr = None
    display_name: str | None = None


@dataclass
class SavePresentationFileAsNode:
    """`<ui:SavePresentationFileAs Presentation="..." FilePath="..." />`
    (知見274)。実機2件で`FilePath`の静的リテラル(`"Opportunities.
    pptx"`)・動的VB式(`[string.Format("...Report_{0}", ...)]`)の
    両方を確認。`python-pptx`の`Presentation.save(file_path)`が
    直接対応する。"""

    presentation: Expr = None
    file_path: Expr = None
    display_name: str | None = None


@dataclass
class InsertSlideNode:
    """`<ui:InsertSlide Presentation="..." InsertType="End"
    InsertPosition="..." InsertedAtPosition="..." LayoutName="..."
    SlideMasterName="..." />`(知見275、discovery-fresh-pass-10で発見、
    `ui:PowerPointApplicationScope`配下で使われるPowerPoint第2波活動の
    最初の1件、タグ名限定GitHub検索で8件ヒット)。実機4件
    (公式`UiPath-Services/StudioTemplates`の`CreatePowerPointPresentation`
    テンプレート、公式`UiPathJapan/StudioXTemplates`、`Apress/
    Robotic-Process-Automation-Using-UiPath-StudioX`、
    `starmanfrommars/Robotic-Process-Automation-Lab`)全てで完全に
    同一の構成——`InsertType="End"`(唯一の確認値、`InsertPosition`は
    常に`{x:Null}`——`End`以外の挿入位置指定の実例は実機未確認)、
    `LayoutName="Title and Content"`(唯一の確認値)、`SlideMasterName=
    "(default)"`(唯一の確認値)、`InsertedAtPosition`(出力、新しい
    スライドの1始まり番号——公式サンプルのAnnotationTextに「新しい
    スライド番号を返す」と明記、`InsertTextInPresentationNode.
    slide_index`の1始まり推定と整合)。

    `python-pptx`の`Presentation.slide_layouts`(実機確認済みの単一
    既定マスター構成でのみ動作が確認された便利プロパティ、`prs.
    slide_masters[0].slide_layouts`と同じ内容)から`LayoutName`に
    一致するレイアウトを探し、`Presentation.slides.add_slide(layout)`
    (常に末尾に追加——`InsertType="End"`の確認済み唯一値と正確に
    対応)で新規スライドを作成する。"""

    presentation: Expr = None
    insert_type: str | None = None
    layout_name: Expr = None
    slide_master_name: str | None = None
    inserted_at_position: Expr = None
    display_name: str | None = None


@dataclass
class DeleteSlideNode:
    """`<ui:DeleteSlide Presentation="..." DeletePosition="..." />`
    (知見275、タグ名限定GitHub検索で2件ヒットだが、公式
    `UiPath-Services/StudioTemplates`テンプレート内でも使われている
    実質3件目の確認——本調査最小の属性構成)。実機2件(`Apress/
    Robotic-Process-Automation-Using-UiPath-StudioX`・
    `starmanfrommars/Robotic-Process-Automation-Lab`)で`DeletePosition`
    (1始まりの整数リテラル、`InsertTextInPresentationNode.slide_index`
    と同じ1始まり規約と整合)+`Presentation`のみの構成を確認。

    `python-pptx`に公開APIの削除機能が無いため、コミュニティで広く
    知られる標準的なイディオム(`Presentation.slides._sldIdLst`から
    対象の`sldId`要素を取り出し、対応する関係(`r:id`)を`Presentation.
    part.drop_rel()`で解除してから`_sldIdLst`自体からも除去する)を
    注入ヘルパー関数として実装する(`WordReplacePictureNode`(知見263)
    と同じ「`python-pptx`/`python-docx`の高レベルAPIに無い操作をOOXML
    直接操作で補う」設計判断クラス)。"""

    presentation: Expr = None
    delete_position: Expr = None
    display_name: str | None = None


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
class WordAppendTextNode:
    """`<ui:WordAppendText Text="..." />`(知見258、`WordApplicationScope`
    配下の子活動、`WORD_NS`限定——GitHub検索で143件ヒット)。実機2件
    (`starmanfrommars/Robotic-Process-Automation-Lab`・`Apress/
    Robotic-Process-Automation-Using-UiPath-StudioX`)で確認した構成は
    `Text`のみ(両サンプルとも`NewLine`属性は現れず、公式ドキュメント
    確認済みの既定`True`——「テキストの前に新しい段落を挿入する」)。
    `NewLine="False"`(既存段落の末尾に改行無しで追記)は実機未確認のため
    `# TODO`へ倒す。`python-docx`の`Document.add_paragraph(text)`
    (新しい段落を末尾に追加——`NewLine=True`の確認済み既定値に正確に
    対応する)で実装する。"""

    text: Expr = None
    new_line: str | None = None
    display_name: str | None = None


@dataclass
class WordSaveAsNode:
    """`<ui:WordSaveAs FilePath="..." />`(知見258、`WordApplicationScope`
    配下の子活動、`WORD_NS`限定——GitHub検索で65件ヒット)。実機2件
    (上記と同じ)で確認した構成は`FilePath`のみ(拡張子無しのパス
    文字列、例`"...\\INV-2024-001"`)——`SaveAsFileType`/
    `ReplaceExisting`属性は現れず、公式ドキュメント確認済みの既定
    (`SaveAsFileType="XmlDocument"`=`.docx`、`ReplaceExisting=True`)
    のみ対応する。`SaveAsFileType`が明示的に非既定値の場合、拡張子
    自動付与の有無が未確認(公式ドキュメントに記載無し、実機でも
    拡張子無しパスしか観測できていない)のため`# TODO`へ倒す——
    `python-docx`の`Document.save(path)`はパス文字列をそのまま使う
    (拡張子を自動付与しない、生のCOM `SaveAs2`と同じ挙動として
    解釈)。`ReplaceExisting="False"`も実機未確認の意味論のため
    `# TODO`へ倒す(`python-docx`の`save()`は常に無条件上書きのため
    既定`True`は何もせず対応できる)。

    `WordApplicationScopeNode`のスコープ末尾の無条件`.save(file_name)`
    (元のファイルパスへの保存)は本活動の有無にかかわらず継続して実行
    される——本活動が指定した新しいパスへの保存は`.save(file_path)`
    として追加で実行するだけで、既存のスコープ末尾の保存を置き換え
    たり抑制したりはしない(元のテンプレートファイルも同じ最終内容で
    上書きされる副作用が生じる、既知の限界として明示的に受け入れる、
    `ExcelApplicationScope`のライブマクロ実行未対応と同種の判断)。"""

    file_path: Expr = None
    save_as_file_type: str | None = None
    replace_existing: str | None = None
    display_name: str | None = None


@dataclass
class WordReadTextNode:
    """`<ui:WordReadText Text="..." />`(知見258、`WordApplicationScope`
    配下の子活動、`WORD_NS`限定——GitHub検索で67件ヒット)。`Text`は出力
    (ドキュメント全文)。`python-docx`の`"\\n".join(p.text for p in
    document.paragraphs)`で近似する——表組み等の非段落コンテンツは
    捕捉しない既知の限界(`WordReplaceTextNode`の段落/run単位置換と
    同種の、選んだライブラリに起因する構造的制約)。"""

    text: Expr = None
    display_name: str | None = None


@dataclass
class WordAddImageNode:
    """`<ui:WordAddImage ImagePath="..." />`(知見260、`WordApplicationScope`
    配下の子活動、`WORD_NS`限定——GitHub検索で49件ヒット)。実機3件
    (`starmanfrommars/Robotic-Process-Automation-Lab`・`Apress/
    Robotic-Process-Automation-Using-UiPath-StudioX`・
    `spritlesoftware/Uipath-RPA-AutomationProjects`)で確認した
    構成——`ImagePath`(動的VB式、角括弧無しのリテラルパスの両方
    確認)+`InsertRelativeTo`/`Position`(実機3件中2件で明示的に
    `"Document"`/`"End"`、1件は両属性とも完全に省略——公式ドキュメント
    確認済みの既定値がまさに`"Document"`/`"End"`のため、明示/省略の
    いずれも同じ意味)。`Bookmark`/`OccurrenceIndex`/`Text`(他の挿入
    モード専用プロパティ)は実機3件中2件で`{x:Null}`、1件は完全に省略
    ——いずれも非表示/無関係な既定状態。

    `InsertRelativeTo`/`Position`が確認済みの既定(`"Document"`/
    `"End"`)以外の場合は`# TODO`へ倒す——公式ドキュメント確認済みの
    他モード(`Text`相対/`Bookmark`相対)は実機未確認のため対応しない。
    `python-docx`の`Document.add_picture(image_path)`
    (公式ドキュメント確認済み:「ドキュメント末尾に新しい段落として
    画像を追加する」)が「Document」+「End」の確認済み既定動作に
    正確に対応する。"""

    image_path: Expr = None
    insert_relative_to: str | None = None
    position: str | None = None
    display_name: str | None = None


@dataclass
class WordInsertDataTableNode:
    """`<ui:WordInsertDataTable DataTable="..." InsertRelativeTo="Text"
    Position="..." Text="..." />`(知見261、`WordApplicationScope`配下の
    子活動、`WORD_NS`限定——GitHub検索で28件ヒット)。実機2件
    (`Apress/Robotic-Process-Automation-Using-UiPath-StudioX`の
    `Chapter_6-WordAutomationExercise/Main.xaml`、`hannannoor/
    supplyr-rpa`の`src/Main.xaml`)で確認した構成——`WordAddImageNode`
    (知見260)とは対照的に、公式ドキュメント確認済みの既定
    (`InsertRelativeTo="Document"`+`Position="Start"`)を使った実例は
    1件も無く、実機2件とも`InsertRelativeTo="Text"`(`Position`は
    `"Replace"`/`"After"`の両方確認)——プレースホルダ文字列に対する
    相対挿入が実務での唯一の確認済み使い方。`DataTable`は実機1件
    (`hannannoor`)で単純な`[dt_POLines]`形(本プロジェクト既存の
    dict行DataTable表現)を確認、もう1件は`Invoke_Details.
    Table("Table1")`という「Modern Excel」ハンドルAPI呼び出し
    (`render_expr`未対応、個別に`# TODO`へ倒れる、活動自体の実装には
    影響しない)。`Occurrence`/`OccurrenceIndex`は実機2件とも現れず
    (公式ドキュメント確認済みの既定`"All"`/無し)——複数出現時の
    挙動が未確認のため、明示的に設定されている場合は`# TODO`へ倒す。

    `InsertRelativeTo="Document"`(公式ドキュメント確認済みの既定だが
    実機未確認)・`"Bookmark"`相対モードは対応しない。`Text`で検索した
    最初の一致段落(`WordReplaceTextNode`と同じ部分文字列検索、
    段落全体のテキストに対して行う——`python-docx`に組み込みの
    「段落を名前で検索する」API自体が存在しないため標準的なイディオム
    を使う)の直後に`python-docx`の`Document.add_table()`で構築した
    テーブル(`DataTable`のdict行をヘッダー行+データ行として展開、
    公式ドキュメント確認済みの「DataTable column headers are used as
    the table header row」と一致)を`paragraph._p.addnext(table._tbl)`
    (python-docxコミュニティで広く使われる標準的なOXML要素移動
    イディオム、`WordReplaceTextNode`同様の低レベルAPI直接操作)で
    挿入する。`Position="Replace"`の場合は挿入後に元の段落を削除する
    (`paragraph._p.getparent().remove(paragraph._p)`)。プレースホルダ
    が見つからない場合は`None`に対する属性アクセスで自然な
    `AttributeError`を投げる(でっち上げたフォールバック無し、
    `GetRowItem`/`UpdateRowItem`と同じ方針)。"""

    data_table: Expr = None
    insert_relative_to: str | None = None
    position: str | None = None
    text: Expr = None
    occurrence: str | None = None
    occurrence_index: Expr = None
    display_name: str | None = None


@dataclass
class WordReplacePictureNode:
    """`<ui:WordReplacePicture PictureAltText="..." PicturePath="..." />`
    (知見263、`WordApplicationScope`配下の子活動、`WORD_NS`限定——
    GitHub検索で25件ヒット)。実機3件(`Apress/Robotic-Process-
    Automation-Using-UiPath-StudioX`の`Chapter_6-
    WordAutomationExercise/Main.xaml`、`starmanfrommars/Robotic-
    Process-Automation-Lab`の`Lab 7/Main.xaml`、`ashimariyam/
    Employee_Onboarding_UiPath`の`Get picture.xaml`)で確認した構成——
    `PictureAltText`(検索対象の画像Alt Text、静的リテラル・動的
    `CurrentRow("col").ToString`形の両方確認)+`PicturePath`(置換
    画像のファイルパス、動的VB式・リテラルパスの両方確認)の2属性
    のみ——`ContinueOnError`等の他の共通属性は3件とも一度も現れ
    なかった(公式ドキュメントにも記載が無い、本活動には存在しない
    属性と判断)。

    公式ドキュメント確認済みの意味論——「一致するAlt Textを持つ
    すべての画像を置換する」(1件目限定ではない)「大文字小文字を
    区別しない」。`python-docx`にはAlt Text検索/画像置換のための
    高レベルAPIが存在しないため(OOXMLの`<wp:docPr descr="..." />`
    (大文字小文字を区別しないAlt Text)→`<pic:blipFill><a:blip
    r:embed="rIdN">`(画像パーツへのリレーションシップID)という
    低レベル構造を直接操作する必要がある——python-docxコミュニティで
    広く使われる標準的なイディオム(画像パーツの`._blob`を直接
    上書きする、公開APIには存在しない内部属性)を、新規注入ヘルパー
    関数`_word_replace_picture(doc, alt_text, picture_path)`として
    実装する(`_ImapMailMessage`(知見250)と同じ「確認済みの狭い
    アクセスパターンに絞った薄いラッパー」判断、今回は関数形)。"""

    picture_alt_text: Expr = None
    picture_path: Expr = None
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
class ExcelGetWorkbookSheetsNode:
    """`<ui:ExcelGetWorkbookSheets Sheets="[...]" />`(知見284、
    discovery-fresh-pass-13が発見、タグ名限定GitHub検索で128件ヒット)。
    `ExcelApplicationScope`配下専用の子活動(`ExcelReadCellNode`等と同じ
    ファミリー)。属性は`Sheets`(出力変数、プレーン属性形——
    `ExcelReadCellNode.Result`のような`<Foo.Result>`プロパティ要素形
    ではない、`Shivamkr99/Sales-Report-Automation`・`Orica-4S/
    Capybara_Fin028_Performer_Part3`の実機XAMLで確認)の1つだけ。"""

    sheets: Expr = None
    display_name: str | None = None


@dataclass
class ReadRangeNode:
    """`<ui:ReadRange WorkbookPath="..." SheetName="..." DataTable="..."
    AddHeaders="..." Range="..." />`(知見256、Excel/Word/マウスキーボード
    網羅性向上の調査パスで発見、タグ名限定GitHub検索で3904件ヒット——
    本調査で見つかった単独最高ヒット数)。`ExcelReadRangeNode`(知見115)
    と同じ「シート全体の使用範囲を読む」活動だが、別の独立した
    "Workbook"系活動ファミリー(`ExcelApplicationScope`配下限定ではなく、
    `WorkbookPath`を自分自身の属性として持ち、ライブExcelプロセス/スコープ
    無しで単独動作する)——`ReadCell`/`WriteRange`/`WriteCell`等、同じ
    `WorkbookPath`単独指定パターンの兄弟活動が多数存在する。

    実機2件(`PacktPublishing/Robotic-Process-Automation-Projects`の
    `Chapter 02/ReadExcelRequest.xaml`、`mihhdu/Enhanced-REFramework`の
    `Framework/InitAllSettings.xaml`)で確認した構成——`WorkbookPath`
    (`[RequestFilePath]`/`[in_configFile]`、いずれも動的VB式)、
    `SheetName`(`"Sheet1"`という静的リテラル、`"[sheet]"`という動的VB式の
    両方を確認——`ExcelReadRangeNode.sheet_name`の既存の`str`限定制約
    (VbExpr未対応)とは異なり、こちらは最初から動的式を実機確認済みのため
    `Expr`型として対応する)、`DataTable`(出力)、`AddHeaders`
    (`"False"`/`"True"`両方確認済み)、`Range`(属性`{x:Null}`または
    ネストした`<ui:ReadRange.Range><InArgument><Literal Value="" />`
    形——実機2件とも空文字列、`ExcelReadRangeNode`と同じ「シート全体の
    使用範囲」を意味する既存の確認済み判断を継承)。

    `ExcelApplicationScopeNode`(知見97)が既に確立した`openpyxl`
    (ファイルベース、Excelプロセス不要)基盤を再利用するが、スコープ無しの
    単独活動のため、自分自身で`openpyxl.load_workbook()`を呼んで読んだ
    直後に`.close()`する(スコープ版と違い保存不要、読み取り専用の
    one-shot操作)。"""

    workbook_path: Expr = None
    sheet_name: Expr = None
    range: Expr = None
    add_headers: str | None = None
    data_table: Expr = None
    display_name: str | None = None


@dataclass
class WriteRangeNode:
    """`<ui:WriteRange WorkbookPath="..." SheetName="..." DataTable="..."
    AddHeaders="..." StartingCell="..." Password="{x:Null}" />`(知見257、
    `ReadRangeNode`(知見256)の書き込み側、同じスコープ無し"Workbook"系
    活動ファミリー、タグ名限定GitHub検索で2892件ヒット)。

    実機4件(`manickakrish/Filter_ExcelDatatable`の`Main.xaml`、
    `piyushagarwal08/JU-Notes`の`UiPath/Data/Main.xaml`、
    `vajrang-b/UiPathIn30Days`の複数タスク、`cristinegulescu/
    startUiPathFromSalesforce`の`LearnTeams.xaml`)で確認した構成——
    `WorkbookPath`(動的VB式の文字列連結`["Original/" + DateAndTime.
    Now.ToString("dd_MM_yyyy") + ".xlsx"]`、または角括弧無しの素の
    リテラルパス`"C:\\Users\\piyus\\Desktop\\Gujrat.xlsx"`の両方を確認)、
    `SheetName`(静的リテラルのみ確認)、`DataTable`(入力)、
    `AddHeaders`(`"True"`/`"False"`両方確認済み)、`StartingCell`
    (ネストした空文字列`Literal`形、または属性`{x:Null}`形、または
    `"A1"`という既定値と同じ値の明示的リテラル——実機4件とも
    `ExcelWriteRangeNode`(知見115)の既存の「常にA1既定へ倒れる」
    判断と矛盾しない)、`Password`(実機確認済みの値は常に`{x:Null}`、
    `ExcelWriteRangeNode`には存在しない属性)。

    `ExcelWriteRangeNode`の`sheet_name: str`/`starting_cell: str |
    None`という既存の静的文字列限定制約(VbExpr未対応)とは異なり、
    本活動は`WorkbookPath`の動的式実例が多数確認できたことを踏まえ
    `sheet_name`/`starting_cell`も最初から`Expr`型として対応する
    ——`starting_cell`が動的式(リテラルでない)の場合はコード生成時に
    セル位置を静的に解決できないため`# TODO`へ倒す(実機では一度も
    観測されていない組み合わせ)。

    `ExcelWriteRangeNode`が確立した「`Worksheet.cell(row=..., column=...,
    value=...)`による直接セル指定書き込み(`append()`ベースではない)」
    という知見115修正済みのバグ修正を継承する。スコープ無しの単独活動
    のため、自分自身で`openpyxl.load_workbook()`→書き込み→`.save()`
    する(`ReadRangeNode`と違い書き込みのため保存が必要)。"""

    workbook_path: Expr = None
    sheet_name: Expr = None
    starting_cell: Expr = None
    add_headers: str | None = None
    data_table: Expr = None
    display_name: str | None = None


@dataclass
class ReadCellNode:
    """`<ui:ReadCell WorkbookPath="..." SheetName="..." Cell="..." />`
    (知見259、`ReadRangeNode`/`WriteRangeNode`(知見256/257)と同じ
    スコープ無し"Workbook"系ファミリー、タグ名限定GitHub検索で53件
    ヒット)。`ExcelReadCellNode`(知見119、`ExcelApplicationScope`配下
    限定)の単独動作版。

    実機2件(`masiref/HandyML`の`HandyML_Predictor/Main.xaml`、
    `WingsMaker/uipath_chatgpt`の`Main.xaml`)で確認した構成——
    `Cell`(静的リテラル`"B1"`/`"B2"`のみ確認)、`SheetName`
    (静的リテラルのみ確認)、`WorkbookPath`(動的VB式`[str_Filepath]`
    、角括弧無しのリテラルパス`"bot_config.xlsx"`の両方確認)、
    `Result`(出力、ネストした`<ui:ReadCell.Result><OutArgument
    x:TypeArguments="x:String">[変数名]</OutArgument></ui:
    ReadCell.Result>`形——子要素を持たないテキスト直書きの
    `OutArgument`、`ReadRangeNode`/`WriteRangeNode`の`InArgument`形
    とは逆向きだが同じ`_in_argument_property_expr`で対応できる)。

    `ExcelReadCellNode`の`workbook[sheet_name][cell].value`という
    確認済みの変換をそのまま再利用するが、スコープ無しの単独活動
    のため自分自身で`openpyxl.load_workbook()`→読み取り→`.close()`
    する(`ReadRangeNode`と同じ判断)。"""

    workbook_path: Expr = None
    sheet_name: Expr = None
    cell: Expr = None
    result: Expr = None
    display_name: str | None = None


@dataclass
class WriteCellNode:
    """`<ui:WriteCell WorkbookPath="..." SheetName="..." Cell="..."
    Text="..." />`(知見259、`ReadCellNode`の書き込み側、同じスコープ
    無し"Workbook"系ファミリー、タグ名限定GitHub検索で465件ヒット)。
    `ExcelWriteCellNode`(知見22/119、`ExcelApplicationScope`配下限定)
    の単独動作版。

    実機2件(`masiref/HandyML`の`HandyML_Trainer/1_6_Report.xaml`、
    `vajrang-b/UiPathIn30Days`の`Task15/Main.xaml`)で確認した構成——
    `Cell`(静的リテラル`"B1"`、動的VB式`["D"+(Cell_Index+2).ToString]`
    ——知見119で`ExcelWriteCellNode.cell`を`Expr`型へ昇格した時と同じ
    連番セル指定パターンを独立に再確認)、`SheetName`(静的リテラルの
    み確認)、`Text`(入力)、`WorkbookPath`(動的VB式`[argIn_str_...]`、
    角括弧無しのリテラルパス`"Input1.xlsx"`の両方確認)。

    `ExcelWriteCellNode`の`workbook[sheet_name][cell] = _vb_cstr(value)`
    という確認済みの変換をそのまま再利用するが、スコープ無しの単独
    活動のため自分自身で`openpyxl.load_workbook()`→書き込み→`.save()`
    する(`WriteRangeNode`と同じ判断)。"""

    workbook_path: Expr = None
    sheet_name: Expr = None
    cell: Expr = None
    text: Expr = None
    display_name: str | None = None


@dataclass
class ReadColumnNode:
    """`<ui:ReadColumn WorkbookPath="..." SheetName="..." StartingCell="..."
    Result="..." />`(知見268、discovery-fresh-pass-8で発見、タグ名限定
    GitHub検索で12件ヒット・10件以上の独立リポジトリに分散)。`ReadRangeNode`
    /`ReadCellNode`(知見256/259)と同じスコープ無し"Workbook"系ファミリー
    の兄弟活動——`StartingCell`から下方向に、最初の空セルまで1列分の値を
    読み取って`Result`(出力コレクション)へ格納する。

    実機2件(`CertifaiAI/rpa-insurance-fraud`の`workflow/ClaimFormOps/
    GetEachValue.xaml`、`S1L3NTANG3L/UIPath-Mark-Splitter`の
    `Process Only/Main.xaml`)で確認した構成——`WorkbookPath`
    (`[excel_path]`という動的VB式)、`SheetName`(`"ClaimsForm"`という
    静的リテラルのみ確認)、`StartingCell`(`"B1"`/`"C1"`等の静的リテラル
    のみ確認——動的式は未確認だが、後述のコード生成は`openpyxl`の
    `Cell.offset()`API経由で動的式にも自然に対応できるため制約しない)、
    `Result`(出力、`string.Join(",", temp1)`という実機コードで
    イテラブル/コレクション型と確認済み)。公式ドキュメント(Studio
    ground-truth参照、`marcelocruzrpa/uipath-ai-skills`リポジトリの
    `studio-ground-truth/UiPath.Excel.Activities/3.4/ReadColumn.xaml`)
    でも同じ3属性+`Result`の構成を確認。"""

    workbook_path: Expr = None
    sheet_name: Expr = None
    starting_cell: Expr = None
    result: Expr = None
    display_name: str | None = None


@dataclass
class ReadRowNode:
    """`<ui:ReadRow WorkbookPath="..." SheetName="..." StartingCell="..."
    Result="..." />`(知見268、`ReadColumnNode`の水平方向の鏡像——
    `StartingCell`から右方向に、最初の空セルまで1行分の値を読み取って
    `Result`へ格納する。discovery-fresh-pass-8で発見、タグ名限定GitHub
    検索で11件ヒット。

    実機2件(`S1L3NTANG3L/UIPath-Mark-Splitter`の`Process Only/Main.xaml`、
    `Varun-Chowdary-V/ResumeGeneratorBotUiPath`)で確認した構成——
    `WorkbookPath`(`[markSchemaPath]`という動的VB式)、`SheetName`
    (`[markSchemaSheet]`という動的VB式——`ReadColumnNode`の実機確認は
    静的リテラルのみだったが、こちらで動的式の実例も確認できたため
    `sheet_name`も最初から`Expr`型として扱う判断を裏付ける)、
    `StartingCell`(`"A2"`という静的リテラル)、`Result`(出力コレクション)。
    公式ドキュメント(Studio ground-truth)でも`ReadColumn`と同じ3属性+
    `Result`の構成を確認。"""

    workbook_path: Expr = None
    sheet_name: Expr = None
    starting_cell: Expr = None
    result: Expr = None
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
class GetIMAPMailMessagesNode:
    """`<ui:GetIMAPMailMessages Server="..." Port="..." Email="..."
    Password="..." EnableSSL="..." SecureConnection="..."
    MailFolder="..." Top="..." MarkAsRead="..." OnlyUnreadMessages="..."
    DeleteMessages="..." OrderByDate="..." Messages="..." />`
    (知見250、9回目発見パスで見送った`Mail.Activities`プロトコル系候補
    (`GetPOP3MailMessages`等、知見227注記)をようやく実機確認できた、
    タグ名限定GitHub検索で579件ヒット)。実機2件
    (`cameronmcnz/uipath-tutorials`の`GmailAttachments/Main.xaml`、
    `JAYASIMMA/Loan_Apply_Utility_Bot`の`Main.xaml`)で属性を確認。

    `GetOutlookMailMessagesNode`(知見120)の「生のネイティブオブジェクト
    をそのまま返す(ラッパークラスをでっち上げない)」方針が通用しない
    ——Outlook COMの`MailItem`は`.Subject`等をネイティブなCOMプロパティ
    として既に持つが、Python標準の`email.message.Message`(IMAPで
    取得した生メールの標準的な解析先)は`.get("Subject")`形の辞書的
    アクセスのみで`.Subject`属性アクセスには対応しない。実機確認済み
    の下流アクセス(`email.Subject.ToString`/`Mail.Subject.ToLower.
    Contains(...)`)が`.Subject`1つに狭く絞れたため、`GetFileInfoX`等の
    「広い未確認dot-accessサーフェス」懸念には当たらないと判断し、
    `.Subject`プロパティだけを持つ最小限の薄いラッパークラス
    (`_ImapMailMessage`)を注入する——`GetLastDownloadedFile`(知見233)
    の「狙い撃ちできる狭いパターンなら薄いラッパーを作る」判断と同じ
    クラス。`.Attachments`(`Mail.Attachments.Any`という実機確認済みの
    下流利用も1件あるが)は`ui:SaveMailAttachments`(別活動、知見251で
    後続予定)と合わせて設計すべきため今回は見送る——ラッパーに実装
    しない。

    `Server`/`Port`/`Email`/`Password`(または`SecurePassword`、実機
    どちらも確認済み——`SecureString`型の違いは本トランスパイラが
    変数の型を区別しないため関係無い)+`EnableSSL="True"`(実機2件とも
    唯一の確認値)+`SecureConnection="Auto"`(実機2件とも唯一の確認値
    ——`imaplib.IMAP4_SSL`の直接SSL接続と解釈)+`MailFolder`+`Top`+
    `MarkAsRead`(`"True"`/`"False"`両方実機確認済み)+
    `OnlyUnreadMessages`(`"False"`実機確認、`"True"`は未確認だが
    IMAPの`UNSEEN`検索条件への対応が曖昧性無しのため実装)+
    `DeleteMessages`(同様)+`OrderByDate`(公式ドキュメント確認済みの
    既定値`"NewestFirst"`+実機確認済みの`"OldestFirst"`)。

    `ClientName`/`ClientVersion`(IMAP ID拡張)・`FilterExpression`
    (生のIMAP SEARCH構文と推定されるが実機で非nullの実例が無い)・
    `UseOAuth`(別の認証フロー)・`IgnoreCRL`(TLS証明書失効確認の詳細、
    `"False"`のみ実機確認)・`TimeoutMS`はいずれも設定されている場合
    `# TODO`へ倒す。"""

    messages: Expr = None
    server: Expr = None
    port: Expr = None
    email: Expr = None
    password: Expr = None
    secure_password: Expr = None
    enable_ssl: str | None = None
    secure_connection: str | None = None
    mail_folder: Expr = None
    top: Expr = None
    mark_as_read: str | None = None
    only_unread_messages: str | None = None
    delete_messages: str | None = None
    order_by_date: str | None = None
    timeout_ms: Expr = None
    client_name: Expr = None
    client_version: Expr = None
    filter_expression: Expr = None
    use_oauth: Expr = None
    ignore_crl: str | None = None
    display_name: str | None = None


@dataclass
class GetPOP3MailMessagesNode:
    """`<ui:GetPOP3MailMessages Server="..." Port="..." Email="..."
    Password="..." EnableSSL="..." SecureConnection="..." Top="..."
    DeleteMessages="..." Messages="..." />`(知見268続き、
    discovery-fresh-pass-8の次点推奨候補、タグ名限定GitHub検索で14件
    ヒット)。`GetIMAPMailMessagesNode`(知見250)のPOP3版だが、プロトコル
    の制約上POP3にはフォルダ/未読フラグ/日付ソートの概念が無いため
    `MailFolder`/`MarkAsRead`/`OnlyUnreadMessages`/`OrderByDate`は
    存在しない(公式Studio ground-truth、`marcelocruzrpa/
    uipath-ai-skills`リポジトリの`studio-ground-truth/UiPath.Mail.
    Activities/2.8/GetPOP3MailMessages.xaml`で確認)。

    実機3件(`rafifrizqullah111/RPA-Email-Automation`・`GSA/
    AP-Email-Notifications`の`POP3 Sample Workflow - save
    attachment.xaml`・`210927-Reston-UiPath/Mishuba`の
    `GetMailByPOP3.xaml`)で確認した構成——`Server`(`"pop.gmail.com"`
    という静的リテラル、`[str_pop_server]`という動的VB式の両方確認)、
    `Port`(常に`"995"`——POP3Sの既知ポート)、`Email`/`Password`
    (または`SecurePassword`、いずれも実機確認済み)、`EnableSSL`
    (実機3件とも唯一の確認値**`"False"`**——`GetIMAPMailMessages`の
    確認済み値`"True"`とは正反対だが、`SecureConnection="Auto"`
    (実機3件とも唯一の確認値)と組み合わさり、Gmail(SSL必須)に対して
    実際に動作していることから、実際の接続セキュリティは
    `SecureConnection`側が制御しており`EnableSSL`はこの活動では
    影響しないか無視される設計と判断——Port 995は確認済みの
    POP3Sポートのため、常にSSL接続として実装する)、`DeleteMessages`
    (`"False"`/`"True"`両方実機確認済み)、`Top`(`"200"`という静的
    リテラル、属性省略(既定値`"30"`)の両方確認)。

    下流アクセスは`GetIMAPMailMessages`と全く同一パターン
    (`mail.subject.ToString.Contains(...)`+`ui:SaveMailAttachments
    Message="[mail]"`)——`.Subject`/`.Attachments`のみという狭い
    確認済みサーフェスのため、既存の`_ImapMailMessage`ラッパーを
    そのまま再利用する(新規ラッパークラスは注入しない)。

    `ConnectionMode`/`UseISConnection`(いずれもground-truthの既定値
    `"Undefined"`/`"False"`以外は実機未確認)・`TimeoutMS`・
    `UseOAuth`・`IgnoreCRL`(`"False"`のみ実機確認)はいずれも
    `GetIMAPMailMessages`と同じ判断で`# TODO`へ倒す。POP3には
    `OrderByDate`に相当する確認済みの並び替え制御が無いため、`Top`は
    サーバーが返す自然な順序(通常は受信順)の先頭から数える——実際の
    順序保証は公式ドキュメントでも曖昧であることをdocstringに明記
    する(本トランスパイラ独自の仮定であり、UiPath自体の確定仕様では
    ない)。"""

    messages: Expr = None
    server: Expr = None
    port: Expr = None
    email: Expr = None
    password: Expr = None
    secure_password: Expr = None
    enable_ssl: str | None = None
    secure_connection: str | None = None
    top: Expr = None
    delete_messages: str | None = None
    timeout_ms: Expr = None
    use_oauth: Expr = None
    ignore_crl: str | None = None
    connection_mode: str | None = None
    use_is_connection: str | None = None
    display_name: str | None = None


@dataclass
class SaveMailAttachmentsNode:
    """`<ui:SaveMailAttachments Message="..." FolderPath="..."
    ExcludeInlineAttachments="..." OverwriteExisting="..."
    Attachments="..." />`(知見251、`GetIMAPMailMessages`(知見250)で
    意図的に見送った後続活動、タグ名限定GitHub検索で329件ヒット)。
    実機2件(`cameronmcnz/uipath-tutorials`の`GmailAttachments/
    Main.xaml`、`JAYASIMMA/Loan_Apply_Utility_Bot`の`Main.xaml`)で
    確認済み——`Message`(入力、`GetIMAPMailMessages`が生成する
    `_ImapMailMessage`ラッパー)+`FolderPath`+
    `ExcludeInlineAttachments`(`"False"`実機確認)+
    `OverwriteExisting`(`"True"`実機確認、2件目のサンプルのみ設定、
    1件目は未設定)+`Attachments`(出力、実機2件とも`{x:Null}`——
    未確認のため設定されている場合は見送る)。

    公式ドキュメント(WebFetch経由確認)で`FolderPath`が存在しない
    場合は自動作成されることを確認した(`os.makedirs(...,
    exist_ok=True)`に対応)。`OverwriteExisting="False"`(または未設定)
    時の重複ファイル名解決(公式ドキュメント自体が本文と属性説明で
    矛盾した記述——「上書きされる」と「選択時のみ上書き」——を含み、
    旧StudioX版の別活動では「番号を付加する」という記述もあったが
    本活動で確認できる実例が無い)は未確認のため`"True"`のみ対応する
    ——Pythonの`open(..., "wb")`の既定動作(常に上書き)がそのまま
    `"True"`の意味論と一致するため、追加のコードは不要。

    `_ImapMailMessage`(知見250)に新規`.Attachments`プロパティ
    (`(filename, disposition, part)`タプルのリスト)を追加した——
    実機確認済みの`Mail.Attachments.Any`という別の下流利用(知見250で
    発見、本活動の実装には不要だが同じプロパティを共有できる)にも
    対応する土台になる(ただし`.Any`自体のレンダリング対応は今回の
    スコープ外)。"""

    message: Expr = None
    folder_path: Expr = None
    exclude_inline_attachments: str | None = None
    overwrite_existing: str | None = None
    attachments: Expr = None
    display_name: str | None = None


@dataclass
class MarkMailAsReadXNode:
    """`<umab:MarkMailAsReadX MailMessage="..." MarkAs="..." />`(知見229、
    `umab:` = `clr-namespace:UiPath.Mail.Activities.Business;
    assembly=UiPath.Mail.Activities`——タグ名が`ui:`ではない点に注意。
    タグ名限定GitHub検索で32件ヒット。ground-truth・実機複数件
    (`MaxineXiong/Gmail-Automation-RPA`で`MarkAs="Read"`/`"Unread"`の
    両方を確認)いずれも`MailMessage`+`MarkAs`の2属性のみ。

    `MailMessage`は既実装の`GetOutlookMailMessages`(知見120、
    `win32com.client`経由のOutlook COM `MailItem`オブジェクトを直接
    `list()`で保持)が生成する変数そのもの——新規の型付きオブジェクト
    モデルは不要で、Outlook COM API自身の`MailItem.UnRead`ブール
    プロパティ(Microsoft Learn `Outlook.MailItem.UnRead`で確認済み)
    へ直接代入するだけで済む。`MarkAs="Read"`→`UnRead = False`、
    `"Unread"`→`UnRead = True`。"""

    display_name: str | None = None
    mail_message: Expr = None
    mark_as: str | None = None


@dataclass
class DeleteMailXNode:
    """`<umab:DeleteMailX MailMessage="..." />`(知見229、
    `MarkMailAsReadX`と同じ`umab:`名前空間、タグ名限定GitHub検索で
    31件ヒット)。ground-truth・実機複数件(`Apress/Robotic-Process-
    Automation-Using-UiPath-StudioX`等)いずれも`MailMessage`のみの
    単一属性。Outlook COM API自身の`MailItem.Delete()`メソッド
    (Microsoft Learn確認済み)に対応する。"""

    display_name: str | None = None
    mail_message: Expr = None


@dataclass
class MoveMailXNode:
    """`<umab:MoveMailX MailFolder="..." MailMessage="..." />`(知見229、
    `MarkMailAsReadX`/`DeleteMailX`と同じ`umab:`名前空間、タグ名限定
    GitHub検索で19件ヒット)。ground-truth・実機(`MaxineXiong/
    Gmail-Automation-RPA`、`MailFolder="UiPath Test"`——Inboxと同じ
    階層に並ぶトップレベルフォルダの表示名そのもの)いずれも
    `MailFolder`+`MailMessage`の2属性のみ。

    公式ドキュメント(WebSearch経由確認)では`MailFolder`の実際の
    解決アルゴリズム(絶対パス?現在のフォルダからの相対?)は明記
    されておらず、Studio側のフォルダピッカーUIが選んだ表示名の文字列
    としか説明が無い——実機の実例が常にInboxと同階層のトップレベル
    フォルダだったことから、デフォルトストアのルート(`GetDefault
    Folder(6).Parent`、`GetOutlookMailMessages`知見120のInbox取得と
    同じ経路から辿る)を起点に再帰探索する方針とした(`_outlook_
    find_folder`ヘルパー、見つからない場合は`None`を返し`.Move(None)`
    のCOMエラーに自然に委ねる——フォールバック値を捏造しない既存
    方針、`TextToLeftRight`等と同じ)。"""

    display_name: str | None = None
    mail_message: Expr = None
    mail_folder: Expr = None


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
class DownloadFileFromUrlNode:
    """`<uasf:DownloadFileFromUrl Url="..." FileName="..."
    ConflictResolution="..." Timeout="..." UserAgentHeader="..."
    ResponseAttachment="..." />`(知見282、discovery-fresh-pass-12で
    発見、`UiPath.Activities.System.FileOperations`名前空間(`uasf:`、
    本調査初出)、タグ名限定GitHub検索で19件ヒット)。

    ground-truth(`marcelocruzrpa/uipath-ai-skills`、`ConflictResolution
    ="Rename"`が既定値)+実機3件(`PolinaGlebovich/Invoices`・
    `Adam974Moran/UiPathInvoicesTestTask`——いずれもC#式言語プロジェクト
    (`CSharpValue`/`CSharpReference`、知見129で既に対象外と確認済み)
    で`FileName`が`{x:Null}`のまま`ResponseAttachment`(型未確認の
    `upr:ILocalResource`)経由+後続の`ui:MoveFile`で最終配置する構成
    のため本実装の対象外、`RajdipDuttaa/ACME_Data_Extraction`の
    `DownloadCheckRequestPDF.xaml`——VB式言語プロジェクトで`Url=
    "[str_PDFDownloadURL]"`+`FileName="[str_PDFReportPath]"`+
    `ConflictResolution="[UiPath.Activities.System.FileOperations.
    FileConflictBehavior.Replace]"`という完結した構成を確認)で構成を
    確認。

    `ConflictResolution`は確認済み2値——ground-truthの既定値`"Rename"`
    (プレーンな文字列リテラル)と、実機で確認した`[UiPath.Activities.
    System.FileOperations.FileConflictBehavior.Replace]`という完全
    修飾名のVB式参照の両方の直列化形がある——コード生成時にリテラル
    文字列/VB式どちらの形でも末尾が`Rename`/`Replace`のいずれかに
    一致する場合のみ対応する。公式ドキュメント(WebSearch経由確認)
    で確認した3つ目の選択肢(「置き換えない」、実機未確認)は未対応。

    `ResponseAttachment`(出力、`upr:ILocalResource`という型未確認の
    .NETオブジェクト、実機では常に`{x:Null}`かC#専用の参照先)は
    `GetFileInfoX`等と同じ「未確認の型付きオブジェクトをでっち上げない」
    判断で未対応。`Timeout`/`UserAgentHeader`も実機で非null値を一度も
    確認できず未対応。`FileName`は実機確認できた唯一の使い方
    (`ResponseAttachment`経由ではなく直接指定)のみ対応——未指定時の
    「URL情報から自動決定する」挙動(公式ドキュメント確認済みだが実機
    未確認)はでっち上げない。

    既存の確認済みコア依存`requests`(`HttpClientNode`、知見29/96で
    既に使用)の`requests.get(url, stream=True)`+ストリーミング書き込み
    で実装する——`requests`は本体の`dependencies`に既に存在する
    (discovery-fresh-pass-12が`pyproject.toml`を確認して報告済み)。"""

    url: Expr = None
    file_name: Expr = None
    conflict_resolution: Expr = None
    timeout: Expr = None
    user_agent_header: Expr = None
    response_attachment: Expr = None
    display_name: str | None = None


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
    | ParallelForEachNode
    | RepeatNumberOfTimesXNode
    | TryCatchNode
    | SwitchNode
    | WhileNode
    | DoWhileNode
    | BreakNode
    | ContinueNode
    | ReturnNode
    | StartTimerNode
    | StopTimerNode
    | ResetTimerNode
    | ResumeTimerNode
    | BeepNode
    | IfElseIfV2Node
    | AddLogFieldsNode
    | RemoveLogFieldsNode
    | DeserializeJsonNode
    | GoBackNode
    | NavigateToNode
    | GetFromClipboardNode
    | DeserializeJsonArrayNode
    | CopyFolderXNode
    | MoveFolderXNode
    | StartProcessNode
    | GetSecureCredentialNode
    | AddCredentialNode
    | RequestCredentialNode
    | SplitTextNode
    | CombineTextNode
    | GetIMAPMailMessagesNode
    | GetPOP3MailMessagesNode
    | SaveMailAttachmentsNode
    | SelectFolderNode
    | GetUsernamePasswordXNode
    | ParallelNode
    | ClickNode
    | HoverNode
    | ActivateNode
    | CheckNode
    | HighlightNode
    | CloseApplicationNode
    | CloseWindowNode
    | WindowStateNode
    | GenerateDataTableNode
    | GetAttributeNode
    | GetPasswordNode
    | LoadImageNode
    | LookupDataTableNode
    | SortDataTableNode
    | FilterDataTableNode
    | JoinDataTablesNode
    | RemoveDuplicateRowsNode
    | SaveImageNode
    | TakeScreenshotNode
    | GetOcrTextNode
    | ReadPDFWithOCRNode
    | AddDataRowNode
    | RemoveDataRowNode
    | GetRowItemNode
    | UpdateRowItemNode
    | ClearDataTableNode
    | OutputDataTableNode
    | AddDataColumnNode
    | RemoveDataColumnNode
    | ReadCsvFileNode
    | ReadPdfTextNode
    | GetPdfPageCountNode
    | ExtractPdfPageRangeNode
    | JoinPdfNode
    | ExportPdfPageAsImageNode
    | ExtractImagesFromPdfNode
    | ManagePdfPasswordNode
    | WriteCsvFileNode
    | AppendCsvFileNode
    | DeserializeXmlNode
    | ExecuteXPathNode
    | GetXMLNodeAttributesNode
    | InvokePowerShellNode
    | InvokeVBScriptNode
    | RetryScopeNode
    | MoveFileNode
    | PathExistsNode
    | FileExistsXNode
    | FolderExistsXNode
    | DeleteFileNode
    | DeleteFolderNode
    | ForEachFileNode
    | ForEachFolderNode
    | RenameFileNode
    | RenameFolderNode
    | CreateFileNode
    | GetProcessesNode
    | KillProcessNode
    | CloseTabNode
    | RefreshBrowserNode
    | TypeIntoNode
    | SendHotkeyNode
    | GetTextNode
    | SelectFileNode
    | SelectItemNode
    | SelectMultipleItemsNode
    | UiElementExistsNode
    | WaitUiElementAppearNode
    | DatabaseConnectNode
    | DatabaseDisconnectNode
    | ExecuteQueryNode
    | ExecuteNonQueryNode
    | InsertDataTableNode
    | BulkInsertNode
    | DatabaseTransactionNode
    | ExtractTextNode
    | FindAndReplaceNode
    | ChangeCaseNode
    | GetLastDownloadedFileNode
    | CheckTrueNode
    | CheckFalseNode
    | VerifyExpressionNode
    | VerifyExpressionWithOperatorNode
    | CreateDirectoryNode
    | MergeDataTableNode
    | FormatValueNode
    | InvokeWorkflowFileNode
    | CopyFileNode
    | BuildDataTableNode
    | AppendLineNode
    | ReadTextFileNode
    | WriteTextFileNode
    | ExtractFilesNode
    | CompressFilesNode
    | IsMatchNode
    | ReplaceNode
    | MatchesNode
    | TextToLeftRightNode
    | GetEnvironmentVariableNode
    | SetEnvironmentVariableNode
    | GetEnvironmentFolderNode
    | FindAndReplaceTextModificationNode
    | TrimTextModificationNode
    | ToUpperLowerTextModificationNode
    | ModifyTextNode
    | FindStartEndDateModificationNode
    | ModifyDateNode
    | InvokeCodeNode
    | SetToClipboardNode
    | CommentNode
    | CommentOutNode
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
    | OpenBrowserNode
    | ExcelApplicationScopeNode
    | WordApplicationScopeNode
    | PowerPointApplicationScopeNode
    | FindAndReplaceTextInPresentationNode
    | InsertTextInPresentationNode
    | SavePresentationFileAsNode
    | InsertSlideNode
    | DeleteSlideNode
    | WordReplaceTextNode
    | WordAppendTextNode
    | WordSaveAsNode
    | WordReadTextNode
    | WordAddImageNode
    | WordInsertDataTableNode
    | WordReplacePictureNode
    | ExcelReadRangeNode
    | ExcelWriteRangeNode
    | ExcelAppendRangeNode
    | ExcelGetWorkbookSheetsNode
    | ReadRangeNode
    | WriteRangeNode
    | ReadCellNode
    | WriteCellNode
    | ReadColumnNode
    | ReadRowNode
    | SendOutlookMailNode
    | GetOutlookMailMessagesNode
    | MarkMailAsReadXNode
    | DeleteMailXNode
    | MoveMailXNode
    | SendMailNode
    | HttpClientNode
    | DownloadFileFromUrlNode
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
