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
