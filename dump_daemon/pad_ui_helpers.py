"""Power Automate Desktop のUI自動化ヘルパー(pywinauto)。

design/g1_g2_verification_result.mdで実機検証済みのパターンを再利用可能な関数として
切り出したもの。対話的セッション内(clipwire経由)で実行する前提——WinRM経由では
Windows Session 0分離のためPADの実ウィンドウにアクセスできない
(design/ci_verification_findings.md 知見9/10)。
"""
from __future__ import annotations

from typing import Any

import win32clipboard
from pywinauto import Desktop


def find_window_by_title_prefix(prefix: str) -> Any | None:
    """タイトルが指定プレフィックスで始まる最初のトップレベルウィンドウを返す。

    PADのコンソールウィンドウは常に "Power Automate"、フローデザイナーウィンドウは
    "Power Automate | <フロー名>" という可変タイトルを持つため、完全一致ではなく
    前方一致で探す。
    """
    for w in Desktop(backend="uia").windows():
        try:
            title = w.window_text()
        except Exception:
            continue
        if title.startswith(prefix):
            return w
    return None


def find_pad_console_window() -> Any | None:
    """PADのメインコンソールウィンドウ(タイトル完全一致 "Power Automate")を返す。"""
    for w in Desktop(backend="uia").windows():
        if w.window_text() == "Power Automate":
            return w
    return None


def find_pad_designer_window() -> Any | None:
    """PADのフローデザイナーウィンドウ(タイトル "Power Automate | <flow>") を返す。"""
    return find_window_by_title_prefix("Power Automate | ")


def as_window_specification(window: Any) -> Any:
    """生のUIAWrapperを、.wait()/.child_window()が使えるWindowSpecificationに
    handleで再束縛する(design/control_dump_tech_selection.md 2.3節参照)。"""
    return Desktop(backend="uia").window(handle=window.handle)


def set_clipboard_text(text: str) -> None:
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


def paste_text_into(element: Any, text: str, select_all_first: bool = True) -> None:
    """クリップボード経由でテキストを入力する。

    pywinautoの type_keys() は `()`/`{}` 等を特殊キー記法として解釈してしまい、
    Pythonコードのような任意テキストの直接入力には使えない
    (design/g1_g2_verification_result.md で実証済み)。クリップボード+Ctrl+Vなら
    エスケープ不要で確実。
    """
    element.click_input()
    set_clipboard_text(text)
    if select_all_first:
        element.type_keys("^a")
    element.type_keys("^v")


def find_descendant_edit_by_name(window: Any, name_substring: str) -> Any | None:
    """子孫のEditコントロールを、アクセシビリティ名(element_info.name)の部分一致で探す。

    Editコントロールの `.window_text()` は入力中の値を返すため、空のテキストボックスでは
    ラベルと一致しない。ラベル(name)で探すには element_info.name を使う必要がある
    (design/g1_g2_verification_result.md 実装上の注意点を参照)。
    """
    for e in window.descendants(control_type="Edit"):
        try:
            name = e.element_info.name or ""
        except Exception:
            name = ""
        if name_substring in name:
            return e
    return None


def expand_tree_category(window: Any, category_auto_id: str) -> None:
    """アクション検索結果のツリービューで、カテゴリ(折りたたみ可能なTreeItem)を展開する。

    TreeItem自体をクリックしても展開されない場合があり、子の "Expander" ボタンを
    明示的にクリックする必要がある(実機検証で確認)。
    """
    item = window.child_window(auto_id=category_auto_id, control_type="TreeItem")
    item.wait("exists", timeout=10)
    expander = item.child_window(auto_id="Expander", control_type="Button")
    expander.click_input()


def find_descendant(
    window: Any,
    control_type: str,
    name: str | None = None,
    name_substring: str | None = None,
) -> Any | None:
    """子孫を `control_type`(+`name`/`name_substring`)で再帰的に探す(最初の一致を返す)。

    `window.child_window()`は一部のPADデザイナーのコントロール(検索結果の`TreeItem`等)を
    見つけられないことがあるため、`descendants()`の全件スキャンに統一する
    (RDP不要の知見75/78の各手順で共通して使う下地)。
    """
    for c in window.descendants(control_type=control_type):
        try:
            info = c.element_info
        except Exception:
            continue
        if name is not None and info.name != name:
            continue
        if name_substring is not None and name_substring not in (info.name or ""):
            continue
        return c
    return None


def get_clipboard_text() -> str:
    """クリップボードのテキストを読む(`win32clipboard`直接呼び出し、PowerShell不要)。"""
    win32clipboard.OpenClipboard()
    try:
        return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


def paste_dsl_into_action_list(designer_window: Any, dsl_text: str) -> None:
    """DSLテキストをクリップボード経由で`List "Actions"`に貼り付ける
    (design/dsl_format_findings.md 知見75、RDP不要)。

    `List "Actions"`コントロール宛の制御対象キー入力(`type_keys()`)は、
    `pywinauto.keyboard.send_keys()`のような画面全体へのSendInputと違い、
    アクティブなデスクトップ接続を必要としない。PADは受理した構文を自然文の
    `ListItem`として表示し、認識できないものには`", Has error"`を付ける——
    これ自体が構文の正誤を判定するオラクルになる(知見75)。
    """
    actions_list = find_descendant(designer_window, "List", name="Actions")
    if actions_list is None:
        raise LookupError('List "Actions" control not found')
    set_clipboard_text(dsl_text)
    actions_list.set_focus()
    actions_list.type_keys("^v")


def copy_action_list_as_text(designer_window: Any) -> str:
    """`List "Actions"`全体をCtrl+A→Ctrl+Cでコピーし、テキストとして読み戻す
    (design/dsl_format_findings.md 知見75の往復確認手順、RDP不要)。

    `paste_dsl_into_action_list()`で貼り付けた内容の読み戻しには有効だが、
    `add_action_via_search()`(知見78のキーボード追加)で追加したアクションには
    使えない——キャンバスからのコピー操作(Ctrl+C・Editメニュー・各アクションの
    "More actions"メニューのいずれも)が`COMError(-2147220992)`で失敗する既知の
    制約がある(新規に開くポップアップ/メニューの内容がRDP接続無しでは安定しない
    問題と同根、知見78参照)。
    """
    actions_list = find_descendant(designer_window, "List", name="Actions")
    if actions_list is None:
        raise LookupError('List "Actions" control not found')
    actions_list.set_focus()
    actions_list.type_keys("^a")
    actions_list.type_keys("^c")
    return get_clipboard_text()


def add_action_via_search(
    designer_window: Any, search_term: str, result_name: str | None = None
) -> Any:
    """検索語を入力し、検索結果へ`.set_focus()`+Enterでアクションをキャンバスへ追加する
    (design/dsl_format_findings.md 知見78、RDP不要)。

    検索結果の`TreeItem`を`.select()`するだけではUIAの`SelectionItemPattern`
    (ハイライト)しか変わらずWPFの内部的なキーボードフォーカスは移動しないため、
    その後の`type_keys("{ENTER}")`は何も起こさない——これが本プロジェクトで
    何度か観測していた「Enterキーが効かない」現象の原因だった(知見78で特定)。
    `.set_focus()`で実際にWPFフォーカスを移してからEnterを送る必要がある。

    `result_name`省略時は`search_term`と同じ名前の`TreeItem`を探す(検索結果の
    表示名が検索語と一致しない場合は明示的に渡す)。追加されたかどうかは、呼び出し元が
    ステータスバーの「N Actions」/「N Selected action」カウンター(タブの汎用的な
    "Actions"ラベルではなくこのカウンターで判定すること、知見78で確認済みの罠)で
    確認する。見つかった`TreeItem`自体を返す。
    """
    search_box = find_descendant(designer_window, "Edit", name="Search actions")
    if search_box is None:
        raise LookupError('Edit "Search actions" control not found')
    search_box.set_text(search_term)
    result = find_descendant(designer_window, "TreeItem", name=result_name or search_term)
    if result is None:
        raise LookupError(f"search result TreeItem not found for: {search_term!r}")
    result.set_focus()
    result.type_keys("{ENTER}")
    return result
