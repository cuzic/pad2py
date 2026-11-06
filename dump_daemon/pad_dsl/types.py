"""PADクリップボードDSLの値・ASTノード型(`Record`/`Node`)の定義。

このモジュールは純粋なデータ構造のみを持ち、パース処理(`pad_dsl.line_parser`/
`pad_dsl.block_tree`)にもエスケープ処理(`pad_dsl.tokens`)にも依存しない——
`pad_codegen`を含む他の全coreがここに定義された型を「共有語彙」として参照する。

`VarRef`/`RawExpr`/`EnumRef`は design/common_rpa_framework_roadmap.md 層1の方針に基づき
`dump_daemon.rpa_ir.values`(PAD/UiPath共有のIR核)へ移管済み——ここでは後方互換のため
同一のクラスを再公開している(`isinstance`チェックの対象が同一のクラスオブジェクトに
なるよう、別々に再定義するのではなく再公開する点に注意)。PAD固有の値型
(`DpapiSensitiveLiteral`/`UiElementRef`)はこのモジュールに残す。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..rpa_ir.values import EnumRef as EnumRef
from ..rpa_ir.values import RawExpr as RawExpr
from ..rpa_ir.values import VarRef as VarRef


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


@dataclass(frozen=True)
class ImageRepositoryRefList:
    """`[imgrepo['<表示名>']]`形式の画像リポジトリ参照リスト(**実機検証済み**——
    design/dsl_format_findings.md 知見58・206)。`UIAutomation.IfImage.ExistsOnScreen`の
    `Images`パラメータに現れる、`appmask[...]`(`UiElementRef`)とは別の角括弧リスト
    リテラル構文——`imgrepo['<表示名>']`参照そのものを`[...]`でさらに囲む。実際の画像
    PNGバイナリ自体はこの参照の先(`# [ControlRepository]`セクションの
    `ImageRepositorySymbol`、`control_repository.parse_image_repository()`)にある。

    「Find all images in the list」トグルの存在から複数要素(カンマ区切り)を許容する
    設計だと推測されるが、実機キャプチャで確認できたのは単一要素のケースのみ(知見58)。
    `names`は`[...]`内に現れた`imgrepo['...']`参照の表示名を出現順に保持する。
    """

    names: tuple[str, ...]


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
