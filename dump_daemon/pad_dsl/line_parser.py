"""DSLテキストの行(`pad_dsl.tokens`でプレースホルダ化済み)1行分を`Record`へ変換する。

`pad_dsl.tokens`(エスケープ解除)と`pad_dsl.types`(構築先の値・Record型)にのみ依存する。
複合式の構文木化は`pad_expr`core(Lark文法)に委譲するが、`pad_expr`側が本モジュールの
`_resolve_value`/`_stringify_resolved_expr_token`を参照する向きの依存があるため、循環を
避けて呼び出し時に遅延importする(`_render_raw_expr`参照)。
"""
from __future__ import annotations

import re
from typing import Any

from .tokens import _unescape, _unescape_comment
from .types import (
    ActionRecord,
    BlockRecord,
    CaseDefaultRecord,
    CaseRecord,
    CommentRecord,
    ElseIfActionRecord,
    ElseIfFunctionRecord,
    ElseIfRecord,
    EnumRef,
    IfActionRecord,
    IfFunctionRecord,
    IfRecord,
    KeywordRecord,
    LoopForeachRecord,
    LoopRecord,
    LoopWhileRecord,
    OnBlockErrorRecord,
    OnErrorRecord,
    RawExpr,
    RawRecord,
    Record,
    SetVariableRecord,
    SwitchRecord,
    UiElementRef,
    VarRef,
    WaitActionRecord,
)

_DOTTED_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")
# design/dsl_format_findings.md 知見55(実機検証済み)——`EnumRef`判定専用の、より厳しい版。
# `_DOTTED_RE`は1個以上のドットにマッチするため、`InnerVar.SomeProperty`のような
# `VariableTrailer`(ユーザー変数へのドット付きプロパティアクセス、`EnumRef`の
# 「既知の未解決の曖昧性」として上のクラスdocstringに記した形)も誤ってEnumRef扱いしてしまっていた。
# これまでに実機キャプチャした全てのEnumRef値(`Display.DefaultButton.Button1`等)・action_id
# (`MouseAndKeyboard.SendMouseClick.Click`等)は例外なく`Namespace.Enum.Value`という
# ちょうど3セグメント(ドット2個)だったため、EnumRef判定だけドット数2個以上を要求するよう
# 厳しくした。2セグメント(ドット1個)はVariableTrailerの可能性を優先してVarRefへフォールバックする
# (完全な曖昧性解消ではない——3セグメント以上のVariableTrailerや2セグメントのEnumRefが
# 実在すれば依然として誤判定しうるが、これまでの実機証拠に基づく最善の判断)。
_ENUM_REF_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){2,}$")
_INT_RE = re.compile(r"-?\d+")
_FLOAT_RE = re.compile(r"-?\d+\.\d+")
_FUNC_COND_RE = re.compile(r"^(IF|ELSE IF) ([A-Za-z_][A-Za-z0-9_]*)\((.*)\) THEN$")
# design/dsl_format_findings.md 知見50(実機検証済み)——`[WaitAction]`カテゴリ(`Wait for window`等)は
# 単純な`WAIT <seconds>`キーワードとは全く別の構文で、`WAIT (<ActionId> <Param>: <Value> ...) FOR <秒数>`
# という、丸括弧で囲んだアクション呼び出し風の式を伴う。例:
# `WAIT (UIAutomation.WaitForWindow.ToOpen Window: appmask['...'] FocusWindow: False) FOR 5`
# `FOR <秒数>`句は「Fail with timeout error」トグルが有効な場合のみ付与され、無効な場合は
# `WAIT (...)`のみで終わる(知見50の追記で実機確認済み)——そのため`FOR`句全体を省略可能にしている。
# design/dsl_format_findings.md 知見66・67・70・71(実機検証済み、空の場合のみ)——
# バックティック1組``はPADの「中身を一度も編集せず保存した」空文字列の第3の直列化
# 構文(Text.CreateHTMLContentのHtmlEditor・Database.ExecuteSqlStatement.Executeの
# Statement・XML.WriteXmlToFile.WriteToFileFormattedのXml等、リッチテキスト/SQL/XML
# エディタ系の値で確認)。非空のバックティック文字列(中身がある場合の表現・
# エスケープ規則)は実機未確認のため、この空の形だけを認識する——`token == "``"`の
# 完全一致のみ扱い、それ以外のバックティックを含むトークンはVarRefへのフォールバックを
# 維持する(でっち上げない)。
_EMPTY_BACKTICK_STRING = "``"
_WAIT_ACTION_RE = re.compile(r"^WAIT \((.+)\)(?: FOR (.+))?$")
# design/dsl_format_findings.md 知見54(実機検証済み)——`[ConditionAction]`カテゴリ
# (`If window`/`If window contains element`/`If image`等)は、知見50の`WAIT (...)`と全く同じ丸括弧パターンを
# 条件式として再利用する。例:
# `IF (UIAutomation.IfWindow.IsOpen Window: appmask['...'] InstantCheck: False) THEN`
# `IfFunctionRecord`(`Contains(a, b) THEN`、知見18-2)とは異なり、丸括弧が`IF`/`ELSE IF`の
# 直後(関数名の前)から始まり、中身がPAD関数の位置引数ではなく`ActionRecord`と同じ
# `<ActionId> <Param>: <Value>`形式になる。
_IF_ACTION_RE = re.compile(r"^(IF|ELSE IF) \((.+)\) THEN$")


_ACTION_ID_RE = _DOTTED_RE
# "REPEAT"は design/dsl_format_findings.md 知見37(実機検証済み)の`REPEAT ACTION`用。
# "NEXT"は既存の`NEXT LOOP`と`NEXT ACTION`(同じくON ERRORの本体内で使える——いずれも
# 同じ`"NEXT ACTION"`という2トークンのベアキーワードのため、追加の実装は不要)の両方で使われる。
# "THROW"は design/dsl_format_findings.md 知見41(実機検証済み)の`THROW ERROR`用——
# `ON BLOCK ERROR`の「Throw error」を選ぶと本体に追加される2トークンのベアキーワード。
# "LABEL"/"GOTO"は design/dsl_format_findings.md 知見48(実機検証済み)——`Label`アクション
# (フロー制御カテゴリ)が`LABEL <名前>`、`ON ERROR`/`ON BLOCK ERROR`の「Exception handling
# mode」を「Go to label」にすると本体に`GOTO <名前>`が追加される。いずれも2トークンの
# ベアキーワードで、`REPEAT ACTION`等と同じ`KeywordRecord`機構でそのまま表現できる。
_KNOWN_KEYWORDS = {"WAIT", "END", "ELSE", "EXIT", "NEXT", "REPEAT", "THROW", "LABEL", "GOTO"}

def _strip_parens(token: str) -> str:
    """`LOOP WHILE`のオペランド(`(LoopIndex)`等)を囲む丸括弧を取り除く。"""
    if token.startswith("(") and token.endswith(")"):
        return token[1:-1]
    return token


def _merge_not_in(tokens: list[str]) -> list[str]:
    """隣接する`"NOT"`・`"IN"`の2トークンを1個の`"NOT IN"`トークンへ結合する。

    `NOT IN`は`"NOT IN"`(内部に空白を1つ持つ**1つの**文字列)として直列化されることが
    確定済み。`IF`/`ELSE IF`/`LOOP WHILE`の演算子は固定位置の
    トークン(`tokens[2]`等)として読むため、空白区切りで2トークンになる`NOT IN`を
    そのままにすると以降の全トークン位置がずれてしまう(以前から既知だったギャップ)。
    ここで先に1トークンへ結合しておくことで、既存の固定位置ロジックを変更せずに対応できる。
    """
    merged: list[str] = []
    i = 0
    while i < len(tokens):
        if tokens[i] == "NOT" and i + 1 < len(tokens) and tokens[i + 1] == "IN":
            merged.append("NOT IN")
            i += 2
        else:
            merged.append(tokens[i])
            i += 1
    return merged


def _resolve_value(token: str, placeholders: dict[str, str | tuple[str, ...]]) -> Any:
    if token.startswith("\x00UIE") and token in placeholders:
        path = placeholders[token]
        assert isinstance(path, tuple)
        return UiElementRef(path)
    if token in placeholders:
        value = placeholders[token]
        assert isinstance(value, str)
        return _unescape(value)
    if token == _EMPTY_BACKTICK_STRING:
        return ""
    if token == "True":
        return True
    if token == "False":
        return False
    if _FLOAT_RE.fullmatch(token):
        return float(token)
    if _INT_RE.fullmatch(token):
        return int(token)
    if _ENUM_REF_RE.fullmatch(token):
        return EnumRef(token)
    return VarRef(token)


def _resolve_param_token(
    tokens: list[str], i: int, placeholders: dict[str, str | tuple[str, ...]]
) -> tuple[Any, int]:
    """パラメータ値1個を`tokens[i]`から読み、`(値, 消費後の次のインデックス)`を返す。

    design/dsl_format_findings.md 知見66(実機検証済み、空の場合のみ)——`{ }`(中に
    空白1個を挟んだ`{`/`}`のペア)は空の2次元配列リテラルの直列化で、空白区切りの
    `line.split()`では2トークンに分かれる。`_resolve_value()`は1トークンしか見ないため、
    ここで2トークン先読みして`{`直後が`}`の場合だけ空リストとして消費する——非空の
    配列リテラル(要素の区切り方・エスケープ規則)は実機未確認のため、この空の形だけを
    認識し、それ以外は通常の`_resolve_value()`(未知の`{`は従来通りVarRefへフォールバック)
    に委ねる。
    """
    if tokens[i] == "{" and i + 1 < len(tokens) and tokens[i + 1] == "}":
        return [], i + 2
    return _resolve_value(tokens[i], placeholders), i + 1


def _stringify_resolved_expr_token(value: Any) -> str:
    """`_resolve_value()`の戻り値を、人間可読な複合式テキストの断片として文字列化する。

    `RawExpr`はPythonへの意味論的な変換を行わないため、元のDSLテキストを極力忠実に
    再構成できればよく、`VarRef`はそのまま変数名(`AND`/`OR`/`mod`等の裸キーワードや
    `(1`のような括弧付き断片もここに落ちる)、数値/真偽値は`str()`、プレースホルダ由来の
    文字列は`repr()`で引用符を復元する。
    """
    if isinstance(value, VarRef):
        return value.name
    if isinstance(value, EnumRef):
        return value.value
    if isinstance(value, UiElementRef):
        return "appmask" + "".join(f"[{p!r}]" for p in value.path)
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return repr(value)
    return str(value)


def _render_raw_expr(tokens: list[str], placeholders: dict[str, str | tuple[str, ...]]) -> RawExpr:
    # pad_exprコアがpad_dsl.line_parser側のヘルパー(_resolve_value等)を参照する向きの
    # 依存があるため、モジュール読み込み順の循環を避けて呼び出し時に遅延importする。
    from ..pad_expr import parse_expr

    tree, text = parse_expr(tokens, placeholders)
    return RawExpr(text=text, tree=tree)


def _parse_action_call_body(
    inner: str, placeholders: dict[str, str | tuple[str, ...]]
) -> tuple[str, dict[str, Any]]:
    """`<ActionId> <Param>: <Value> ...`形式(`WAIT (...)`・`IF (...)`共通、知見50・54)を解析する。

    `ActionRecord`のパラメータ解析と同じ考え方で、`<Name>:`の形をしたトークンだけを
    パラメータ名として扱い、その直後のトークンを値として読む。
    """
    inner_tokens = inner.split()
    action_id = inner_tokens[0]
    params: dict[str, Any] = {}
    i = 1
    while i < len(inner_tokens):
        tok = inner_tokens[i]
        if tok.endswith(":"):
            name = tok[:-1]
            if i + 1 >= len(inner_tokens):
                break
            params[name], i = _resolve_param_token(inner_tokens, i + 1, placeholders)
            continue
        i += 1
    return action_id, params


def _parse_line(line: str, placeholders: dict[str, str | tuple[str, ...]], indent: int = 0) -> Record:
    if line.startswith("\x00CMT") and line in placeholders:
        # DSL上のコメントは常に`"/# " + escaped + "#/"`という形で
        # `/#`の直後に1文字の空白を固定で挿入する(コメント本文自体が空白で始まる
        # 場合でも区別なく追加される)。そのためここでは「空白なら剥がす」のような
        # 条件分岐ではなく、常に先頭1文字をデリミタの一部として取り除く。
        comment_raw = placeholders[line]
        assert isinstance(comment_raw, str)
        return CommentRecord(text=_unescape_comment(comment_raw[1:]), indent=indent)
    if line.startswith("# "):
        return CommentRecord(text=line[2:], indent=indent)
    if line == "#":
        return CommentRecord(text="", indent=indent)

    func_match = _FUNC_COND_RE.match(line)
    if func_match:
        keyword, func_name, args_str = func_match.groups()
        args = [_resolve_value(a.strip(), placeholders) for a in args_str.split(",")]
        if keyword == "IF":
            return IfFunctionRecord(function_name=func_name, args=args, indent=indent)
        return ElseIfFunctionRecord(function_name=func_name, args=args, indent=indent)

    wait_action_match = _WAIT_ACTION_RE.match(line)
    if wait_action_match:
        # design/dsl_format_findings.md 知見50(実機検証済み)。括弧の中身は`ActionRecord`と
        # 全く同じ`<ActionId> <Param>: <Value> ...`形式なので、共通ヘルパーで解析する。
        inner, duration_str = wait_action_match.groups()
        action_id, params = _parse_action_call_body(inner, placeholders)
        wait_record = WaitActionRecord(action_id=action_id, params=params, indent=indent)
        if duration_str is not None:
            wait_record.timeout_seconds = _resolve_value(duration_str.strip(), placeholders)
        return wait_record

    if_action_match = _IF_ACTION_RE.match(line)
    if if_action_match:
        # design/dsl_format_findings.md 知見54(実機検証済み)。知見50のWAIT (...)と同じ
        # 丸括弧パターンを再利用する`[ConditionAction]`カテゴリ用の条件式。
        keyword, inner = if_action_match.groups()
        action_id, params = _parse_action_call_body(inner, placeholders)
        if keyword == "IF":
            return IfActionRecord(action_id=action_id, params=params, indent=indent)
        return ElseIfActionRecord(action_id=action_id, params=params, indent=indent)

    tokens = _merge_not_in(line.split())
    first = tokens[0]

    if first == "SET" and len(tokens) >= 4 and tokens[2] == "TO":
        expr_tokens = tokens[3:]
        if len(expr_tokens) == 1:
            value: Any = _resolve_value(expr_tokens[0], placeholders)
        else:
            # design/dsl_format_findings.md 知見53(実機検証済み): `SET ... TO`の右辺は
            # `AND`/`OR`/`XOR`/`NOT`で結合した論理式や`+`/`-`/`*`/`/`/`mod`の算術式のような
            # 複数トークンにまたがる複合式になりうる。以前は`tokens[3]`1つだけを読み、
            # 残りのトークンをサイレントに切り捨てていた(知見15・26・36・38・46・50と
            # 同系統の、気付かれにくいデータ消失バグ)。`RawExpr`としてトークン列全体を
            # 失わずに保持し、codegen側で安全にTODO化する。
            value = _render_raw_expr(expr_tokens, placeholders)
        return SetVariableRecord(
            var_name=tokens[1],
            value=value,
            indent=indent,
        )

    if first == "ELSE" and len(tokens) >= 6 and tokens[1] == "IF" and tokens[-1] == "THEN":
        return ElseIfRecord(
            operand1=_resolve_value(tokens[2], placeholders),
            operator=tokens[3],
            operand2=_resolve_value(tokens[4], placeholders),
            indent=indent,
        )

    if first == "IF" and len(tokens) >= 5 and tokens[-1] == "THEN":
        return IfRecord(
            operand1=_resolve_value(tokens[1], placeholders),
            operator=tokens[2],
            operand2=_resolve_value(tokens[3], placeholders),
            indent=indent,
        )

    if first == "LOOP" and len(tokens) >= 5 and tokens[1] == "FOREACH" and tokens[3] == "IN":
        return LoopForeachRecord(
            item_var=tokens[2],
            collection=_resolve_value(tokens[4], placeholders),
            indent=indent,
        )

    if first == "LOOP" and len(tokens) >= 5 and tokens[1] == "WHILE":
        return LoopWhileRecord(
            operand1=_resolve_value(_strip_parens(tokens[2]), placeholders),
            operator=tokens[3],
            operand2=_resolve_value(_strip_parens(tokens[4]), placeholders),
            indent=indent,
        )

    if (
        first == "LOOP"
        and len(tokens) >= 8
        and tokens[2] == "FROM"
        and tokens[4] == "TO"
        and tokens[6] == "STEP"
    ):
        return LoopRecord(
            loop_var=tokens[1],
            start=_resolve_value(tokens[3], placeholders),
            end=_resolve_value(tokens[5], placeholders),
            step=_resolve_value(tokens[7], placeholders),
            indent=indent,
        )

    if first == "SWITCH" and len(tokens) == 2:
        return SwitchRecord(expression=_resolve_value(tokens[1], placeholders), indent=indent)

    if first == "CASE" and len(tokens) == 3:
        # 実機検証済み(design/dsl_format_findings.md 知見33): `CASE = $'''a'''`のように
        # 演算子が明示される(`SemiComparison`のソース通り)。
        return CaseRecord(
            operator=tokens[1],
            value=_resolve_value(tokens[2], placeholders),
            indent=indent,
        )

    if first == "CASE" and len(tokens) == 2:
        # 演算子が省略される形(値だけが出力される場合)も理論上ありうるが、実機では未確認。
        return CaseRecord(operator=None, value=_resolve_value(tokens[1], placeholders), indent=indent)

    if first == "DEFAULT" and len(tokens) == 1:
        return CaseDefaultRecord(indent=indent)

    if first == "ON" and len(tokens) == 2 and tokens[1] == "ERROR":
        # design/dsl_format_findings.md 知見34(実機検証済み、名前無しcatch-allケース)。
        return OnErrorRecord(case_name=None, indent=indent)

    if first == "ON" and len(tokens) == 3 and tokens[1] == "ERROR":
        # design/dsl_format_findings.md 知見36(実機検証済み、名前付きケース。例:
        # `ON ERROR RunPythonScriptError`)。
        return OnErrorRecord(case_name=tokens[2], indent=indent)

    if first == "ON" and len(tokens) == 3 and tokens[1] == "BLOCK" and tokens[2] == "ERROR":
        # design/dsl_format_findings.md 知見40(実機検証済み、名前無しcatch-all)。
        return OnBlockErrorRecord(case_name=None, indent=indent)

    if first == "ON" and len(tokens) == 4 and tokens[1] == "BLOCK" and tokens[2] == "ERROR":
        # `ON ERROR <CaseName>`(知見36)との類推による実装。named caseの実機確認は
        # まだ無い(未検証の拡張)。
        return OnBlockErrorRecord(case_name=tokens[3], indent=indent)

    if first == "BLOCK" and len(tokens) == 1:
        # design/dsl_format_findings.md 知見40(実機検証済み、無名BLOCK)。
        return BlockRecord(name=None, indent=indent)

    if first == "BLOCK" and len(tokens) == 2:
        # 名前付きBLOCKの実機確認はまだ無い(未検証の拡張)。
        return BlockRecord(name=tokens[1], indent=indent)

    if first in _KNOWN_KEYWORDS:
        return KeywordRecord(name=first, args=tokens[1:], indent=indent)

    if not _ACTION_ID_RE.match(first):
        return RawRecord(text=line, indent=indent)

    record = ActionRecord(action_id=first, indent=indent)
    i = 1
    while i < len(tokens):
        tok = tokens[i]
        if tok.endswith("=>"):
            # 出力パラメータ名(例: `ButtonPressed=>`の`ButtonPressed`)とVar名が同名の
            # ケースが多いが、必ずしも一致するとは限らない。1個のアクションが複数の出力を
            # 持つ場合(例: `WindowTitle=> WindowTitle WindowInstance=> AutomationWindow`)が
            # あるため、全ての束縛を output_vars(パラメータ名→変数名)に記録する。
            # output_var は後方互換のため最後に見つかったものを保持する(単一出力の
            # アクションではこれで十分だが、複数出力では output_vars を参照すること)。
            if i + 1 >= len(tokens):
                break
            param_name = tok[:-2]
            var_name = tokens[i + 1]
            record.output_var = var_name
            record.output_vars[param_name] = var_name
            i += 2
            continue
        if tok.endswith(":"):
            name = tok[:-1]
            if i + 1 >= len(tokens):
                break
            record.params[name], i = _resolve_param_token(tokens, i + 1, placeholders)
            continue
        # 未知のトークン形式。パラメータ値が空白を含む等、今回の文法理解を超えるケース。
        i += 1

    return record
