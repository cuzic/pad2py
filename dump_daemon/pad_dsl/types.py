"""PADクリップボードDSLの値・ASTノード型(`Record`/`Node`)の定義。

このモジュールは純粋なデータ構造のみを持ち、パース処理(`pad_dsl.line_parser`/
`pad_dsl.block_tree`)にもエスケープ処理(`pad_dsl.tokens`)にも依存しない——
`pad_codegen`を含む他の全coreがここに定義された型を「共有語彙」として参照する。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class VarRef:
    """DSL上の裸トークンが変数参照であることを表すマーカー型。

    `$'''...'''`で囲まれていない裸トークンは、数値リテラル/`Namespace.Enum.Value`型の
    列挙値でなければ変数参照(実機検証: design/dsl_format_findings.md 知見6・9——UI上の
    `%VarName%`はDSL上`%`記号なしの裸トークンとして出力される)。文字列リテラル
    ("hello"等)と字面上は区別がつかないため、専用の型でラップして明示する。
    """

    name: str


@dataclass(frozen=True)
class RawExpr:
    """`SET ... TO`の右辺が単一トークンに収まらない複合式(比較式を`AND`/`OR`/`XOR`/`NOT`
    で結合した論理式、`+`/`-`/`*`/`/`/`mod`による算術式)だったことを示すマーカー型。

    design/dsl_format_findings.md 知見53(実機検証済み)で確認した通り、これらの演算子は
    予測通りのベアキーワード(`AND`/`OR`/`XOR`/`NOT`は大文字に正規化される、`mod`は
    小文字のまま)としてDSLに出力される。演算子の優先順位(知見81)・`/`/`mod`の値の意味論
    (知見82・83)はいずれも実機確認済みで、`pad_codegen.render_expr_as_python()`が`tree`から
    実際のPython式を生成する。`text`はそれでも失わずに保持しており、構文解析に失敗した場合
    (`tree=None`)や`SET`式内の関数呼び出し(`FuncCall`、実機未確認の拡張)が現れる場合の
    安全なTODOフォールバックに使われる。

    `tree`は`pad_expr_parser.py`のLark文法で構文解析した構造化表現(`ExprNode`、解析に
    失敗した場合は`None`)。
    """

    text: str
    tree: Any = None


@dataclass(frozen=True)
class DpapiSensitiveLiteral:
    """`P'<base64>'`形式のWindows DPAPI保護値(`Sensitive`属性付きパラメータ、知見72)。

    `Cryptography.*`/`Compression.*`の鍵・パスワード系パラメータは、実機で常に
    `P'<CryptProtectData保護済みBase64>'`という、通常の`$'''...'''`文字列リテラルとは
    全く別の構文で直列化される(知見72で発見)。`pad_codegen`の`decrypt_dpapi_sensitive_value()`
    (`pad_action_lib.cryptography_actions`、知見112)経由で、生成スクリプトの実行時に
    Windows DPAPI(`win32crypt.CryptUnprotectData`)で復号できる——ただし復号できるのは
    「生成スクリプトを、このPAD保護値を実際に作成したWindowsユーザー自身が実行する」
    場合のみ(DPAPI CurrentUserスコープの仕組み上、PADを使っていた元のユーザー/
    マシンでしか復号できない——`pad2py`が主眼とする「自分の既存フローを自分のマシンで
    Pythonへ移行する」用途とは整合するが、他人が作成したフローのエクスポートを無関係な
    マシンで変換する場合は復号できず実行時に例外になる)。
    """

    ciphertext_b64: str


@dataclass(frozen=True)
class EnumRef:
    """`Namespace.Enum.Value`形式(例: `Display.Icon.None`)の列挙値を表すマーカー型。

    ドット区切りの完全修飾名という見た目でPAD変数参照(ドットを含まない裸識別子)と
    区別できるため、`VarRef`とは別の型にしている。

    **既知の未解決の曖昧性**: PADの変数参照自体にも`.Name`という
    ドット区切りの「トレーラ」(配列/カスタムオブジェクトのプロパティアクセス、例:
    `MyDataTable.Rows`)が存在しうることが確認できている。この形はテキスト上
    `Namespace.Enum.Value`と完全に同じ見た目になるため、`_DOTTED_RE`だけでは
    区別できない。これまでの実機データにトレーラ付き変数参照の実例が無いため、
    現状は全てのドット区切りトークンを`EnumRef`として扱っているが、これは
    トレーラ付き変数が実在する場合に誤分類する可能性がある未解決のギャップ。
    """

    value: str


@dataclass(frozen=True)
class UiElementRef:
    """`appmask['<表示名>']`形式のUI要素リポジトリ参照(**実機検証済み**——
    design/dsl_format_findings.md 知見38)。`Click UI element in window`のような
    「By window UI element」系アクションの`Element`パラメータに現れる。選択済みUI要素の
    CSS風セレクタ文字列自体はこの参照の先(UI要素リポジトリ側)にあり、ActionRecordのパラメータ値には
    **表示名への参照だけ**が直接埋め込まれる——以前の調査で解明したセレクタ文字列の
    フォーマットは、リポジトリ内部の格納形式であり、DSLテキスト上の直接の値ではなかった。

    対象要素が別のウィンドウ/要素の子孫である場合、`appmask['<親の表示名>']['<対象の表示名>']`
    のように`['...']`が複数連なり、祖先から対象までのパスを表す(**実機検証済み**——
    design/dsl_format_findings.md 知見46)。各セグメントの表示名自体に`'`を含みうる場合は
    `\\'`でエスケープされる(例: `appmask['Window \\'Untitled - Notepad\\'']['Document \\'Text Editor\\'']`)。
    `path`は祖先から対象までの表示名のタプル、`name`はそのうち対象(末尾)の表示名。
    """

    path: tuple[str, ...]

    @property
    def name(self) -> str:
        return self.path[-1]



@dataclass
class ActionRecord:
    action_id: str
    params: dict[str, Any] = field(default_factory=dict)
    output_var: str | None = None
    output_vars: dict[str, str] = field(default_factory=dict)
    indent: int = 0


@dataclass
class KeywordRecord:
    name: str
    args: list[str] = field(default_factory=list)
    indent: int = 0


@dataclass
class WaitActionRecord:
    """`WAIT (<ActionId> <Param>: <Value> ...) FOR <秒数>`形式(**実機検証済み**——
    design/dsl_format_findings.md 知見50)。`[WaitAction]`カテゴリ(`Wait for window`等)の
    実際のDSL表現。単純な`WAIT <seconds>`キーワード(`KeywordRecord`)とは別構文——`ActionRecord`
    と同じ`Param: Value`形式のパラメータを丸括弧で包み、末尾に`FOR <タイムアウト秒数>`が付く。
    """

    action_id: str
    params: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: Any = None
    indent: int = 0


@dataclass
class SetVariableRecord:
    var_name: str
    value: Any
    indent: int = 0


@dataclass
class IfRecord:
    operand1: Any
    operator: str
    operand2: Any
    indent: int = 0


@dataclass
class ElseIfRecord:
    operand1: Any
    operator: str
    operand2: Any
    indent: int = 0


@dataclass
class IfFunctionRecord:
    """`IF Contains(a, b, False) THEN`のような関数呼び出し形式の条件(知見18-2)。"""

    function_name: str
    args: list[Any]
    indent: int = 0


@dataclass
class ElseIfFunctionRecord:
    function_name: str
    args: list[Any]
    indent: int = 0


@dataclass
class IfActionRecord:
    """`IF (<ActionId> <Param>: <Value> ...) THEN`形式の条件(design/dsl_format_findings.md
    知見54で実機確認)。「If window」「If window contains element」「If image」のような
    `[ConditionAction]`カテゴリのアクションが生成する。知見50の`WaitActionRecord`と全く同じ、
    丸括弧で包んだ`<ActionId> <Param>: <Value>`
    形式をそのまま条件式として使う——`IfFunctionRecord`(`Contains(a, b)`のような単純な
    関数呼び出し形式、知見18-2)とは別の、第3の条件表現パターン。
    """

    action_id: str
    params: dict[str, Any] = field(default_factory=dict)
    indent: int = 0


@dataclass
class ElseIfActionRecord:
    action_id: str
    params: dict[str, Any] = field(default_factory=dict)
    indent: int = 0


@dataclass
class CommentRecord:
    """`# <comment>`形式の単一行コメント、および`/# ... #/`形式の複数行コメント
    (両方の構文が確定済み。複数行の場合`text`に改行が含まれる)。
    """

    text: str
    indent: int = 0


@dataclass
class LoopRecord:
    loop_var: str
    start: Any
    end: Any
    step: Any
    indent: int = 0


@dataclass
class LoopForeachRecord:
    item_var: str
    collection: Any
    indent: int = 0


@dataclass
class LoopWhileRecord:
    operand1: Any
    operator: str
    operand2: Any
    indent: int = 0


@dataclass
class SwitchRecord:
    """`SWITCH <expr>`(**実機検証済み**(design/dsl_format_findings.md 知見33): `CASE`/
    `DEFAULT`は`SWITCH`自身より1段深いindentに並び(`IF`/`ELSE IF`/`ELSE`のような「同じindentの
    兄弟」ではない)、各`CASE`/`DEFAULT`の本体はさらにもう1段深い——`LOOP`が本体を1段深くするのと
    同じ構造が、`SWITCH`→`CASE`の間にも`CASE`→本体の間にも、二重に重なっている)。
    """

    expression: Any
    indent: int = 0


@dataclass
class CaseRecord:
    """`CASE <operator> <value>`(**実機検証済み**: design/dsl_format_findings.md 知見33で
    `CASE = $'''a'''`という実例を確認した。演算子が省略されるケースも理論上ありうるが、
    実機では常に演算子付きだった。`SwitchRecord`より1段深いindentに並ぶ)。
    """

    operator: str | None
    value: Any
    indent: int = 0


@dataclass
class CaseDefaultRecord:
    """`DEFAULT`(ベアキーワード、実機検証済み。`SwitchRecord`より1段深いindentに並ぶ
    catch-allアーム)。
    """

    indent: int = 0


@dataclass
class OnErrorRecord:
    """`ON ERROR`(`case_name=None`、名前無しのcatch-allケース)または
    `ON ERROR <CaseName>`(`case_name`に名前、個別のエラーケース)。いずれも実機検証済み
    (design/dsl_format_findings.md 知見34・36)。直前のアクション(または他の文)に対する
    エラーハンドラ群の1アームを開始する。**他の全ブロック構文(IF/LOOP/SWITCH)と異なり、
    本体のindentはヘッダー自身(および保護対象の文)と同じ**——唯一の例外的な構造。
    複数の`ON ERROR`アームが連続する場合、アーム間に区切り(ENDなど)は無く、
    構文全体の終端に`END`が1つだけ付く(`SwitchNode`のCASE/DEFAULTと同じ「複数アーム+
    末尾に1つのEND」という構造)。
    """

    case_name: str | None = None
    indent: int = 0


@dataclass
class BlockRecord:
    """`BLOCK`(`name=None`)または`BLOCK <Name>`(**実機検証済み**
    design/dsl_format_findings.md 知見40)。PADの「On block error」アクションをフローに
    追加すると自動生成される、複数アクションをまとめる無名(または名前付き)のグループ化
    構文。それ自体はIF/LOOPのような制御フローを持たず、`ON BLOCK ERROR`の保護対象範囲を
    区切るためだけに存在する(実機ではUI上「On block error」を単独で追加すると、常に
    このBLOCKで自動的にラップされた状態になる——素のBLOCKをON BLOCK ERROR無しで作る
    手段はUI上確認できていない)。
    """

    name: str | None = None
    indent: int = 0


@dataclass
class OnBlockErrorRecord:
    """`ON BLOCK ERROR`(`case_name=None`、名前無しcatch-all)または
    `ON BLOCK ERROR <CaseName>`。**実機検証済み**(design/dsl_format_findings.md 知見40)。

    `OnErrorRecord`の`BLOCK`版——保護対象が「文」か「ブロック」かに応じて`"ON ERROR"`/
    `"ON BLOCK ERROR"`のどちらを出力するかが切り替わるだけ。構造も`OnErrorRecord`と同一:
    直前の文(ここでは直前の`BlockRecord`開始ブロック全体)を
    保護し、本体のindentはヘッダー自身と同じ、複数アームが区切り無しに連続しうる。
    名前付きケース(`ON BLOCK ERROR <CaseName>`)は`ON ERROR <CaseName>`との類推で実装したが、
    実機では無名catch-allの形のみ確認済み(未検証の拡張)。
    """

    case_name: str | None = None
    indent: int = 0


@dataclass
class RawRecord:
    text: str
    indent: int = 0


Record = (
    ActionRecord
    | KeywordRecord
    | WaitActionRecord
    | SetVariableRecord
    | IfRecord
    | ElseIfRecord
    | IfFunctionRecord
    | ElseIfFunctionRecord
    | IfActionRecord
    | ElseIfActionRecord
    | CommentRecord
    | LoopRecord
    | LoopForeachRecord
    | LoopWhileRecord
    | SwitchRecord
    | CaseRecord
    | CaseDefaultRecord
    | OnErrorRecord
    | BlockRecord
    | OnBlockErrorRecord
    | RawRecord
)

_SIMPLE_BLOCK_HEADER_TYPES = (LoopRecord, LoopForeachRecord, LoopWhileRecord)


@dataclass
class BlockNode:
    """単純なブロック構文(`LOOP`系/`BLOCK`)の開始レコードと、対応する`END`までの本体。"""

    header: LoopRecord | LoopForeachRecord | LoopWhileRecord | BlockRecord
    body: list[Node] = field(default_factory=list)


ConditionalArmHeader = (
    IfRecord
    | ElseIfRecord
    | IfFunctionRecord
    | ElseIfFunctionRecord
    | IfActionRecord
    | ElseIfActionRecord
    | KeywordRecord
)
_IF_HEADER_TYPES = (IfRecord, IfFunctionRecord, IfActionRecord)
_ELSEIF_HEADER_TYPES = (ElseIfRecord, ElseIfFunctionRecord, ElseIfActionRecord)


@dataclass
class ConditionalNode:
    """`IF`/`ELSE IF`*/`ELSE`?/`END`全体を1つの構文単位として表す。

    各アームは`(header, body)`のタプル。`header`は`IfRecord`/`IfFunctionRecord`(先頭のみ)、
    `ElseIfRecord`/`ElseIfFunctionRecord`(0個以上)、または`KeywordRecord(name="ELSE")`
    (末尾に最大1個)。`END`は個々のアームにではなく構文全体に1つだけ対応するため、
    `ConditionalNode`は単一の`body`ではなく`arms`のリストを持つ。
    """

    arms: list[tuple[ConditionalArmHeader, list[Node]]] = field(default_factory=list)


SwitchArmHeader = CaseRecord | CaseDefaultRecord
_CASE_ARM_TYPES = (CaseRecord, CaseDefaultRecord)


@dataclass
class SwitchNode:
    """`SWITCH <expr>`/`CASE <op> <value>`*/`DEFAULT`?/`END`全体を1つの構文単位として表す。

    **実機検証済み**(design/dsl_format_findings.md 知見33)。`ConditionalNode`とは異なり、
    `CASE`/`DEFAULT`は`SWITCH`自身より1段深いindentに並び、各アームの本体はさらに1段深い
    (`SWITCH`→`CASE`の関係は`LOOP`→本体と同じ「ヘッダーより1段深い」構造で、`CASE`→その本体の
    関係でも同じ構造がもう一重重なっている)。当初はIF/ELSE IFと同じ「ヘッダー群が同じindentに
    並ぶ」構造だと類推していたが、実機確認の結果これは誤りだったため訂正した。
    """

    expression: Any
    arms: list[tuple[SwitchArmHeader, list[Node]]] = field(default_factory=list)


OnErrorArmHeader = OnErrorRecord | OnBlockErrorRecord


@dataclass
class OnErrorNode:
    """1個以上の`ON ERROR [CaseName]`または`ON BLOCK ERROR [CaseName]`アームと、それらを
    まとめて閉じる1つの`END`(実機検証済み——design/dsl_format_findings.md 知見34・36・40)。
    `SwitchNode`と同型(`arms: list[tuple[header, body]]`)——複数アームが連続する場合でも
    アーム間に区切りは無く、末尾に`END`が1つだけ付く。`REPEAT ACTION`は実機検証済み
    (知見37)、`NEXT ACTION`は`ON BLOCK ERROR`の本体内で実機確認済み(知見40、`KeywordRecord`
    として素通しされるだけで特別対応は不要)。単独では出現せず、常に`GuardedNode`経由で
    直前の文(`ON ERROR`の場合はアクション、`ON BLOCK ERROR`の場合は`BlockNode`)に紐付く。
    """

    arms: list[tuple[OnErrorArmHeader, list[Node]]] = field(default_factory=list)


@dataclass
class GuardedNode:
    """直前の文(`node`)に`ON ERROR`/`ON BLOCK ERROR`ハンドラ(`on_error`)が紐付いて
    いることを表す。

    `ON ERROR`/`ON BLOCK ERROR`はそれ自身が独立した文ではなく、DSL上では直前の文
    (またはBLOCK)のすぐ後ろ・同じindentに現れてそれを「保護」する。`build_block_tree()`は
    `ON ERROR`/`ON BLOCK ERROR`を独立したノードとしてbodyに追加せず、直前に追加済みの
    ノードをこれでラップし直す。
    """

    node: Node
    on_error: OnErrorNode


Node = Record | BlockNode | ConditionalNode | SwitchNode | GuardedNode
