"""フラットな`indent`付き`Record`列から、ブロック木(`Node`)を組み立てる。

`pad_dsl.types`の型定義のみに依存する(エスケープ処理・行単位パースのいずれにも
依存しない、疎結合な純粋関数)。
"""
from __future__ import annotations

from .types import (
    BlockNode,
    BlockRecord,
    CaseDefaultRecord,
    ConditionalArmHeader,
    ConditionalNode,
    GuardedNode,
    KeywordRecord,
    Node,
    OnBlockErrorRecord,
    OnErrorArmHeader,
    OnErrorNode,
    OnErrorRecord,
    Record,
    SwitchArmHeader,
    SwitchNode,
    SwitchRecord,
    _CASE_ARM_TYPES,
    _ELSEIF_HEADER_TYPES,
    _IF_HEADER_TYPES,
    _SIMPLE_BLOCK_HEADER_TYPES,
)


def build_block_tree(records: list[Record]) -> list[Node]:
    """`parse_dsl()`が返すフラットな`indent`付きレコード列から、ブロック木を組み立てる。

    design/dsl_format_findings.md 知見7・9・11で確認したルールに基づくスタック型の
    再帰下降パース:
    - `LOOP`系はブロック開始行と対応する`END`が同じindent深さ、本体だけがその1段内側。
    - `IF`/`ELSE IF`/`ELSE`は同じindent深さの1つの構文で、`END`は構文全体に1つだけ。
    - `SWITCH`/`CASE`/`DEFAULT`は実機検証済み(design/dsl_format_findings.md 知見33)で、
      `IF`/`ELSE IF`とは異なる構造だと判明した: `CASE`/`DEFAULT`は`SWITCH`より1段深いindentに
      並び、各アームの本体はさらに1段深い(`END`は`SWITCH`と同じindentに1つだけ)。
    対応する`END`が見つからないまま入力が尽きた場合(壊れたデータ等)は、例外を出さず
    そこまでの本体を返す。
    """

    pos = 0

    def is_end(rec: Record, level: int) -> bool:
        return isinstance(rec, KeywordRecord) and rec.name == "END" and rec.indent == level

    def parse_level(level: int, stop_at_error_sibling: bool = False) -> list[Node]:
        nonlocal pos
        body: list[Node] = []
        while pos < len(records):
            rec = records[pos]
            if rec.indent < level:
                break
            if stop_at_error_sibling and isinstance(rec, (OnErrorRecord, OnBlockErrorRecord)) and rec.indent == level:
                # design/dsl_format_findings.md 知見40・61: `ON ERROR`/`ON BLOCK ERROR`の
                # 本体がヘッダー自身と**同じ**indentになる実例(知見61で両方の形が実機で
                # 確認された——詳細はOnErrorRecord/OnBlockErrorRecordの分岐コメント参照)
                # では、他の全ブロック構文の「本体はヘッダーより1段深い」という規則では
                # 次のアーム見出し(別のON ERROR/ON BLOCK ERROR)を本体と取り違えてしまう
                # ため、indentの大小だけでは区別できない。`SwitchNode`のCASE/DEFAULTと
                # 同じ「次のアーム見出しに出会ったら(消費せずに)打ち切る」先読みが必要。
                break
            if is_end(rec, level):
                pos += 1
                return body
            pos += 1
            if isinstance(rec, _IF_HEADER_TYPES):
                arms: list[tuple[ConditionalArmHeader, list[Node]]] = [(rec, parse_level(level + 1))]
                while pos < len(records):
                    nxt = records[pos]
                    if nxt.indent != level:
                        break
                    if isinstance(nxt, _ELSEIF_HEADER_TYPES):
                        pos += 1
                        arms.append((nxt, parse_level(level + 1)))
                        continue
                    if isinstance(nxt, KeywordRecord) and nxt.name == "ELSE":
                        pos += 1
                        arms.append((nxt, parse_level(level + 1)))
                        break
                    break
                if pos < len(records) and is_end(records[pos], level):
                    pos += 1
                body.append(ConditionalNode(arms=arms))
            elif isinstance(rec, SwitchRecord):
                # 実機検証済み(design/dsl_format_findings.md 知見33): CASE/DEFAULTは
                # SWITCH自身よりindentが1段深く(level + 1)、各アームの本体はさらに1段深い
                # (level + 2)。SWITCH自身のENDだけはSWITCHと同じlevel。
                switch_arms: list[tuple[SwitchArmHeader, list[Node]]] = []
                while pos < len(records):
                    nxt = records[pos]
                    if nxt.indent != level + 1 or not isinstance(nxt, _CASE_ARM_TYPES):
                        break
                    pos += 1
                    switch_arms.append((nxt, parse_level(level + 2)))
                    if isinstance(nxt, CaseDefaultRecord):
                        break
                if pos < len(records) and is_end(records[pos], level):
                    pos += 1
                body.append(SwitchNode(expression=rec.expression, arms=switch_arms))
            elif isinstance(rec, _SIMPLE_BLOCK_HEADER_TYPES):
                block_body = parse_level(level + 1)
                # parse_level(level + 1)はこのブロック自身の閉じENDを消費できない
                # (そのENDのindentはlevelであり、level + 1ではないため)。ここで明示的に
                # 消費しないと、呼び出し元のwhileループがこのENDを「呼び出し元自身の終端」と
                # 誤認し、後続の兄弟要素を黙って切り捨ててしまう(実データで発覚したバグ)。
                if pos < len(records) and is_end(records[pos], level):
                    pos += 1
                body.append(BlockNode(header=rec, body=block_body))
            elif isinstance(rec, BlockRecord):
                # design/dsl_format_findings.md 知見61(実機再検証・訂正): `BLOCK`の本体は
                # LOOP等と同じくlevel + 1。直後に`ON BLOCK ERROR`が続く場合にこのBLOCK全体を
                # 保護するGuardedNodeへラップし直す点は知見40通りだが、`ON BLOCK ERROR`
                # 自身のindentは「BLOCKと同じlevel」(知見40、単体BLOCKだけを個別コピーした
                # 場合に実機確認・再確認)と「BLOCKより1段浅い(=BLOCKを囲むLOOP等と同じ
                # level - 1)」(知見61、フロー全体の一括コピーでBLOCKがLOOP本体の中に
                # ネストしている実例で確認)の**両方**が実機で確認されており、どちらが
                # 「正しい」かは未解明なので両方を受理する。見つかったほうの実際のindent
                # (`arm_level`)をそのアーム群自身のheader levelとして扱う(本体は
                # arm_level + 1、アーム継続・共有ENDはarm_level)。`arm_level`が`level`
                # (BLOCK自身)と異なる場合、アーム群を閉じるENDとは別にBLOCK自身を閉じる
                # ENDがもう1行存在する(知見61の実例で確認)。
                block_body = parse_level(level + 1)
                block_node: Node = BlockNode(header=rec, body=block_body)
                handler_rec = records[pos] if pos < len(records) else None
                if isinstance(handler_rec, OnBlockErrorRecord) and handler_rec.indent in (level, level - 1):
                    arm_level = handler_rec.indent
                    on_block_error_arms: list[tuple[OnErrorArmHeader, list[Node]]] = []
                    while pos < len(records):
                        nxt = records[pos]
                        if nxt.indent != arm_level or not isinstance(nxt, OnBlockErrorRecord):
                            break
                        pos += 1
                        on_block_error_arms.append((nxt, parse_level(arm_level, stop_at_error_sibling=True)))
                    if pos < len(records) and is_end(records[pos], arm_level):
                        pos += 1
                    if arm_level != level and pos < len(records) and is_end(records[pos], level):
                        pos += 1
                    block_node = GuardedNode(node=block_node, on_error=OnErrorNode(arms=on_block_error_arms))
                elif pos < len(records) and is_end(records[pos], level):
                    pos += 1
                body.append(block_node)
            elif isinstance(rec, OnErrorRecord):
                # design/dsl_format_findings.md 知見61(実機再検証): 知見34/36は「ヘッダー・
                # 本体は保護対象の文と同じindent」としていたが、フロー全体の一括コピー
                # (単体アクションの個別コピーより代表的な実例)で実機再検証したところ、
                # **両方の形が実在する**と判明した——「ヘッダーが保護対象の文と同じindent、
                # 本体もヘッダーと同じindent」(知見34/36、古いキャプチャ)と「ヘッダーが
                # 保護対象の文より1段深く、本体はヘッダーよりさらに1段深い」(知見61、新しい
                # キャプチャ・本セッションでの実機再コピーの両方で再現)で、後者はIF/LOOP/
                # SWITCHと同じ「ヘッダーの子は+1段」という規則に合致する。どちらの実例が
                # 捕まったPADのバージョン差によるものかは未解明。ヘッダー自身のindent
                # (`arm_level`)が呼び出し元の`level`(保護対象の文のindent)と一致するか
                # どうかで、どちらの形かを自己記述的に判別する。
                arm_level = rec.indent
                same_indent_as_protected = arm_level == level
                body_level = arm_level if same_indent_as_protected else arm_level + 1
                on_error_arms: list[tuple[OnErrorArmHeader, list[Node]]] = [
                    (rec, parse_level(body_level, stop_at_error_sibling=same_indent_as_protected))
                ]
                while pos < len(records):
                    nxt = records[pos]
                    if nxt.indent != arm_level or not isinstance(nxt, OnErrorRecord):
                        break
                    pos += 1
                    on_error_arms.append(
                        (nxt, parse_level(body_level, stop_at_error_sibling=same_indent_as_protected))
                    )
                if pos < len(records) and is_end(records[pos], arm_level):
                    pos += 1
                on_error_node = OnErrorNode(arms=on_error_arms)
                if body:
                    body[-1] = GuardedNode(node=body[-1], on_error=on_error_node)
                else:
                    # ON ERRORが文の先頭(保護対象が無い)という壊れたデータ。
                    # 黙って捨てずraw相当として保持する。
                    body.append(on_error_node)
            elif isinstance(rec, OnBlockErrorRecord):
                # BLOCKを伴わない孤立したON BLOCK ERROR(壊れたデータ、または未対応の
                # 出現パターン)。OnErrorRecordの孤立ケースと同じく、直前のノードがあれば
                # それをGuardedNodeでラップし直し、無ければ黙って捨てずraw相当として保持する。
                # 知見61の訂正と同じく、アーム見出し自身のindentを基準に使う。
                arm_level = rec.indent
                orphan_arms: list[tuple[OnErrorArmHeader, list[Node]]] = [
                    (rec, parse_level(arm_level, stop_at_error_sibling=True))
                ]
                while pos < len(records):
                    nxt = records[pos]
                    if nxt.indent != arm_level or not isinstance(nxt, OnBlockErrorRecord):
                        break
                    pos += 1
                    orphan_arms.append((nxt, parse_level(arm_level, stop_at_error_sibling=True)))
                if pos < len(records) and is_end(records[pos], arm_level):
                    pos += 1
                orphan_node = OnErrorNode(arms=orphan_arms)
                if body:
                    body[-1] = GuardedNode(node=body[-1], on_error=orphan_node)
                else:
                    body.append(orphan_node)
            else:
                body.append(rec)
        return body

    return parse_level(0)
