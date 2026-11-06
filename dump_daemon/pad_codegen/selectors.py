"""UI要素リポジトリ(`CodegenContext.repository`)からpywinautoセレクタ式を組み立てる。

複数のアクションファミリー(`actions.ui_element`/`actions.wait`/`actions.conditions`)が
共有する基盤。`CodegenContext`を明示引数で受け取ることで、以前のモジュールレベル
グローバル状態(`_active_repository`)への依存を排除している。
"""
from __future__ import annotations

from ..pad_dsl import ActionRecord, UiElementRef, VarRef, WaitActionRecord
from .context import CodegenContext
from .render import render_value

_REPOSITORY_ATTR_TO_PYWINAUTO_KWARG = {
    "Class": "class_name",
    "Name": "title",
}


def _window_expr_by_instance_or_title_class(params: dict, by: str) -> str | None:
    """design/dsl_format_findings.md 知見121(decompile確認済み): `GetWindow`/`IfWindow`/
    `WaitForWindow`等が共有する3セレクタ構造(`Control`/`WindowInstance`/`Title`+`Class`)
    のうち、`Control`ベース以外の2つ(`WindowInstance`=裸の変数参照・`Title`+`Class`=
    `Class`が空の場合のみ対応)のウィンドウ参照を解決する。`conditions.py`の`IfWindow`・
    `wait.py`の`WaitForWindow`/`WaitForWindowContent`で共有する(知見190で発見した
    `wait.py`側の未結線を解消するため、知見121で`conditions.py`に実装済みのロジックを
    こちらへ抽出した)。
    """
    if by == "ByInstanceOrHandle":
        window_instance = params.get("WindowInstance")
        return render_value(window_instance) if isinstance(window_instance, VarRef) else None
    if by == "ByTitleClass":
        title = params.get("Title")
        window_class = params.get("Class")
        if isinstance(title, str) and window_class == "":
            return f"Desktop(backend='uia').window(title={render_value(title)})"
        return None
    return None


def _is_start_button_element(path: tuple[str, ...], ctx: CodegenContext) -> bool:
    """`appmask['Start Button']`がPAD独自の特殊タグ`:startbutton`(知見44)を指しているか判定する。

    知見44で実機確認済みの通り、Windowsタスクバーの「Start Button」はふつうのUIA属性ベースの
    セレクタではなく、`Attributes: []`(空)・`CustomValue: ":startbutton"`という予約済みの
    擬似セレクタで直列化される——そのため`_build_pywinauto_selector_expr()`は使える属性が
    無く`None`を返す(でっち上げを避けるため)。だが`:startbutton`自体はPAD固有の推測ではなく
    Windows自体の既知の仕組み(Winキー押下でスタートメニューの開閉がトグルされる)に対応する
    固定のOS要素のため、このタグに限りpyautogui経由のWinキー押下へ安全に対応付けられる。
    """
    if len(path) != 1:
        return False
    repository = ctx.repository.get("appmask")
    if not repository:
        return False
    entry = repository.get(path[0])
    if entry is None or len(entry.selectors) != 1 or len(entry.selectors[0]) != 1:
        return False
    return entry.selectors[0][0].custom_value == ":startbutton"


def _build_pywinauto_selector_expr(path: tuple[str, ...], ctx: CodegenContext) -> str | None:
    """`parse_control_repository()`(知見44)のエントリから、確証のあるpywinautoセレクタ式を
    組み立てる(知見56: `appmask['Window \\'Untitled - Notepad\\'']['Document \\'Text Editor\\'']`の
    実例で、`Desktop(backend="uia").window(title="Untitled - Notepad").child_window(
    class_name="Edit")`が実機で正しく対応する実要素を一意に特定できることを確認済み)。

    `ControlRepositorySelectorElement.attributes`のうち`Ignore: False`の属性だけを使う
    (`Ignore: True`はPAD自身の要素特定ロジックが使わない属性——知見46)。`Class`/`Name`
    属性だけを`class_name`/`title`へ対応付ける。`Process`属性はpywinautoの`window()`/
    `child_window()`がプロセス**名**を直接受け付けない(`process=`はPIDを要求する)ため
    意図的に使わない。経路上のいずれかのセグメントでリポジトリに情報が無い、または
    使える属性が1つも無い(例: 知見44の`:startbutton`のような特殊タグで`Attributes`が
    空)場合は、でっち上げた式を返さず`None`にする。

    design/dsl_format_findings.md 知見56の追記(実機検証済み): 1つの`ControlRepositoryEntry`の
    `selectors[0]`自体が**複数の`ControlRepositorySelectorElement`からなる内部チェーン**に
    なりうる(例: 電卓の「7」ボタンは`pane(Class: CalcFrame)` → `button(Class: Button,
    Name: 7)`という2段)。当初の実装は`entry.selectors[0][0]`(チェーンの最初の1要素)だけを
    見ていたため、この例では実際のボタンではなく中間の`pane`要素(`control_type: Pane`)を
    指す誤った式を生成してしまっていた(実機で`child_window(class_name="CalcFrame")`が
    ボタンではなくPaneに解決されることを確認して発覚)。チェーン内の各要素を**それぞれ
    別個の`.child_window(...)`呼び出し**として連ねる(属性を1つの呼び出しにまとめて
    しまうと、異なる階層の要素が同じ属性名を異なる値で持つ場合に情報をサイレントに
    失う恐れがあるため、PAD自身の内部チェーン構造をそのまま1対1で複製する方針にした)
    よう修正し、実機で`Desktop(backend="uia").window(title="Calculator").child_window(
    class_name="CalcFrame").child_window(class_name="Button", title="7")`が電卓の
    実際の「7」ボタン(`control_type: Button`, `name: 7`)を正しく一意に特定できることを
    確認した。
    """
    repository = ctx.repository.get("appmask")
    if not repository:
        return None
    calls: list[str] = []
    for name in path:
        entry = repository.get(name)
        if entry is None or not entry.selectors or not entry.selectors[0]:
            return None
        for element in entry.selectors[0]:
            kwargs: dict[str, str] = {}
            for attr in element.attributes:
                if attr.get("Ignore"):
                    continue
                kwarg_name = _REPOSITORY_ATTR_TO_PYWINAUTO_KWARG.get(attr.get("Name"))
                value = attr.get("Value")
                if kwarg_name is not None and isinstance(value, str):
                    kwargs[kwarg_name] = value
            if not kwargs:
                return None
            kwargs_str = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
            if not calls:
                calls.append(f'Desktop(backend="uia").window({kwargs_str})')
            else:
                calls.append(f".child_window({kwargs_str})")
    return "".join(calls)

def _ui_element_hint(node: ActionRecord | WaitActionRecord, ctx: CodegenContext) -> str:
    """未対応アクションのTODOコメントに、関連するUI要素の表示名を付記する。

    design/dsl_format_findings.md 知見38で確認した通り、`Click UI element in window`等の
    パラメータ値は`UiElementRef`(`appmask['<表示名>']`への名前参照)であり、実際のセレクタ
    文字列はDSLテキストに含まれない(知見39・42・43で取得経路を実機で探索し尽くし、v1では
    変換不能と確定——本モジュール冒頭のdocstring参照)。架空のセレクタをでっち上げる代わりに、
    せめて表示名だけでもTODOコメントに残すことで、ユーザーが手動でpywinautoのセレクタを
    補う際の手がかりにする。
    """
    # design/dsl_format_findings.md 知見46: 対象が別要素の子孫の場合、`UiElementRef.path`は
    # 祖先から対象までの表示名のタプルになる(例: `("Window 'Untitled - Notepad'",
    # "Document 'Text Editor'")`)。フルパスをそのまま見せた方が、ユーザーが手動で
    # pywinautoのセレクタを組み立てる際の手がかりとして有用。
    paths = [v.path for v in node.params.values() if isinstance(v, UiElementRef)]
    if not paths:
        return ""
    joined = ", ".join(" > ".join(repr(name) for name in path) for path in paths)
    hints = [h for p in paths if (h := _build_pywinauto_selector_expr(p, ctx)) is not None]
    if hints:
        suggestion = f"; verified pywinauto selector: {' / '.join(hints)}"
    elif not ctx.repository:
        # design/pad_todo.md C節: 単体コピー(ControlRepositoryデータが一切無い)の場合、
        # セレクタ提案を試すだけ無駄なので、代わりに原因と対処法を直接案内する。
        suggestion = (
            "; no ControlRepository data in input — copy a wider range of actions"
            " (including this one's surroundings) to get a verified selector suggestion,"
            " see README 'UI要素セレクタについて'"
        )
    else:
        suggestion = ""
    return (
        f" (UI element: {joined}; selector not available from DSL, see knowledge 38/39/42/43/46"
        f" — fill in manually{suggestion})"
    )
