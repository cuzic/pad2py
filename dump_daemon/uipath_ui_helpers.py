"""UiPath Studioのpywinauto操作のための再利用可能ヘルパー。

design/uipath_xaml_findings.md 知見1〜12を実機で確認する過程で、clipwire越しの
RDPセッション内で繰り返し手作業のスクリプトとして書いていた操作パターンを、
`pad_ui_helpers.py`(PAD用)と同じ要領で関数として切り出したもの。pad2py本体の
codegen/parserとは独立した調査用ツールで、将来UiPathを本格的に調査・実装する
場合の出発点として使う想定。

対話的セッション内(clipwire経由)で実行する前提——WinRM経由ではWindows Session 0
分離のため実ウィンドウにアクセスできない(design/ci_verification_findings.md 知見9/10)。
"""
from __future__ import annotations

import time
from typing import Any

from pywinauto import Desktop
from pywinauto.keyboard import send_keys
from pywinauto.mouse import click, double_click


def find_studio_window() -> Any | None:
    """タイトルに "UiPath Studio" を含むトップレベルウィンドウを返す(空プロジェクト時の
    ウィンドウタイトルは空文字列になることがあるため、サインイン直後は見つからない
    ことがある——知見「UI automationガイドライン」参照)。"""
    for w in Desktop(backend="uia").windows():
        try:
            title = w.window_text()
        except Exception:
            continue
        if "UiPath Studio" in title:
            return w
    return None


def as_window_specification(window: Any) -> Any:
    """生のUIAWrapperを、.child_window()が使えるWindowSpecificationに再束縛する。"""
    return Desktop(backend="uia").window(handle=window.handle)


def search_and_insert_activity(
    window: Any, search_text: str, result_hotkey: str = "%1", settle_s: float = 1.2
) -> None:
    """アクティビティ検索ポップアップを開いて検索語を入力し、指定した結果を選択する。

    検索ポップアップを開く方法は文脈に依存する(知見「UI automation注意点」参照):
    - キャンバスの空き「+」(AddButton)をクリックすると直接開く
    - 既存のアクティビティを選択した状態で Ctrl+Shift+T を押すと、その直後に
      兄弟として挿入される形で開く(どちらも同じ検索ポップアップUIを使う)
    本関数は「ポップアップが既に開いている」ことを前提に、検索語の入力と結果選択のみ
    行う——呼び出し側でAddButtonクリックまたはCtrl+Shift+Tを先に実行すること。

    result_hotkey はポップアップ内の候補に表示される "ALT + N" のNに対応する
    "%N" 形式(例: 1件目なら既定の"%1")。
    """
    for ch in search_text:
        send_keys(ch, pause=0.1)
        time.sleep(0.08)
    time.sleep(settle_s)
    send_keys(result_hotkey)
    time.sleep(1.2)


def set_vb_expression_field(coords: tuple[int, int], text: str, clear_first: bool = True) -> None:
    """Assign/If/Switch等のVB式入力欄(カスタムの `VisualBasicEditor` コントロール)に
    テキストを設定する。

    このコントロールは`pywinauto`の`set_edit_text()`(UIA ValuePattern)を
    サポートしない(`NoPatternInterfaceError`)。`send_keys()`で一括文字列を送ると
    IntelliSenseの割り込みで文字が欠落・重複することがある(例: "result"→"rllllt"、
    design/uipath_xaml_findings.md 知見2の脚注参照)。1文字ずつ`pause`付きで送るのが
    確実——`pad_ui_helpers.paste_text_into()`のクリップボード貼り付け方式は
    このコントロールでは未検証(今後試す価値あり: `{`/`}` 等のエスケープが
    不要になる可能性がある)。

    `{`/`}` を含む値(VB配列リテラル `{"a","b","c"}` 等)は呼び出し側で
    `{{}`/`{}}}` にエスケープしてから渡すこと(`send_keys`の特殊構文のため)。

    **入力確定時の罠**(design/uipath_xaml_findings.md 知見16): このコントロールは
    IntelliSense/オートコンプリート付き。入力後に`{TAB}`で確定しようとすると、
    入力した文字列ではなく**オートコンプリート候補が採用されてしまう**ことがある
    (実例: 変数名`content`を入力して`{TAB}`したら無関係なWPF列挙型
    `ContentAlignment`が採用され、コンパイルエラーになった)。呼び出し側は
    入力後まず`{ESC}`でIntelliSenseドロップダウンだけを閉じ(フィールドの
    編集内容自体は保持される)、その後に**別の場所をクリックして**フォーカスを
    外す、という手順で確定すること。この関数自体はテキスト入力のみを行い、
    確定操作(`{ESC}`+別要素クリック、または単純な`{TAB}`)は呼び出し側の
    判断に委ねている——フィールドの種類(Filenameのような単純プロパティか、
    IntelliSense付きの式/変数束縛欄か)によって安全な確定方法が異なるため。
    """
    click(coords=coords)
    time.sleep(0.6)
    if clear_first:
        send_keys("^a")
        time.sleep(0.2)
        send_keys("{DELETE}")
        time.sleep(0.3)
    for ch in text:
        send_keys(ch, pause=0.15)
        time.sleep(0.12)
    time.sleep(0.5)


def set_datagrid_cell_value(coords: tuple[int, int], text: str) -> None:
    """DataGridView形式のテーブル(Invoke Workflow Fileの引数一覧等)のセルに
    値を入力する。

    単純な`click()`ではセルが選択されるだけで編集モードに入らず、入力した文字が
    無視される(design/uipath_xaml_findings.md 知見12で実機確認)。**必ず
    `double_click()`でセルの編集モードへ入ってから入力する**こと。
    """
    double_click(coords=coords)
    time.sleep(0.8)
    for ch in text:
        send_keys(ch, pause=0.2)
        time.sleep(0.15)
    time.sleep(1)


def dump_tree(ctrl: Any, depth: int = 0, max_depth: int = 6) -> None:
    """UI要素ツリーを`control_type`/`name`付きでインデント表示する簡易デバッグ出力。

    UiPath Studioの一部のツリー(特にリボン・検索結果ツリー)はUIA的に重複ノードを
    持つことがあり(同一要素が深さ違いで複数回見える)、`descendants()`で全体を
    走査すると同じ行が何十回も出ることがある——必要な属性(control_typeや
    rectangle)で事前にフィルタしてから使うこと。
    """
    if depth > max_depth:
        return
    try:
        info = ctrl.element_info
        print(f"{'  ' * depth}{info.control_type} name={info.name!r}")
    except Exception as e:
        print(f"{'  ' * depth}ERR {e}")
        return
    try:
        children = ctrl.children()
    except Exception:
        children = []
    for c in children:
        dump_tree(c, depth + 1, max_depth)


def save_screenshot(path: str) -> None:
    """画面全体のスクリーンショットをPNGとして保存する(`screenshot.py`の
    `capture_region()`と同等だが、UiPath調査では引数無しの全画面キャプチャのみ
    使ったため専用の薄いラッパーとして用意)。"""
    import mss
    import mss.tools

    with mss.MSS() as sct:
        shot = sct.grab(sct.monitors[1])
        mss.tools.to_png(shot.rgb, shot.size, output=path)
