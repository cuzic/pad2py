"""`WaitActionRecord`(`WAIT (...)`構文、`[WaitAction]`カテゴリ)のcodegen。"""
from __future__ import annotations

from ...pad_dsl import UiElementRef, WaitActionRecord
from ..context import CodegenContext
from ..render import INDENT, render_value
from ..selectors import _build_pywinauto_selector_expr, _ui_element_hint

_WAIT_ACTION_TARGETS: dict[str, tuple[str, str, str]] = {
    "UIAutomation.WaitForWindow.ToOpen": ("Window", "wait", "exists"),
    "UIAutomation.WaitForWindow.ToClose": ("Window", "wait_not", "exists"),
    "UIAutomation.WaitForWindow.ToBecomeFocused": ("Window", "wait", "active"),
    "UIAutomation.WaitForWindow.ToLoseFocus": ("Window", "wait_not", "active"),
    "UIAutomation.WaitForWindowContent.WindowToContainElement": ("Element", "wait", "exists"),
}

# wait_for文字列 → セレクタ式を埋め込んだ真偽値式。IfWindowの"active"判定と同じ
# 防御的ガード(存在しないウィンドウで`wrapper_object()`が例外にならないよう、まず
# `exists()`を確認する)を使う。
_WAIT_CRITERIA_EXPR = {
    "exists": "{sel}.exists()",
    "active": "({sel}.exists() and {sel}.wrapper_object().is_active())",
}

def generate(node: WaitActionRecord, indent: int, ctx: CodegenContext) -> list[str]:
    """`WaitActionRecord`(design/dsl_format_findings.md 知見50で実機確認した
    `WAIT (<ActionId> ...) FOR <秒数>`構文) → pywinautoの`.wait()`/`.wait_not()`(タイムアウト
    指定あり)、または無期限ポーリングの`while`ループ(タイムアウト指定なし)、それらが
    安全に組み立てられない場合は`# TODO`コメント。

    `UIAutomation.WaitForWindow.ToOpen`等はpywinautoの`WindowSpecification.wait("exists",
    timeout=...)`に自然に対応する。対象のセレクタは知見56の`_build_pywinauto_selector_expr()`
    (Click.Clickで実際の実行コード生成に使っているのと同じ、実機で一意特定を確認済みの仕組み)
    で解決できる場合のみ使う。

    `timeout_seconds`は「Fail with timeout error」トグルがOFFの場合`None`になる(知見50の
    追記)。この場合の実際の挙動——50ミリ秒間隔で無期限にポーリングを続け、タイムアウトに
    よる失敗が一切発生しない(条件が満たされるかフロー自体がキャンセルされるまで待ち続ける)
    ——が確認できたため、同じ意味論を素朴な`while`+`time.sleep(0.05)`ループとして生成する。
    でっち上げた有限タイムアウト値を埋め込むよりも、確認済みの「無期限に待つ」という挙動を
    そのまま再現する方が安全という判断(タイムアウト指定ありの場合のみ`.wait()`/`.wait_not()`
    を使う)。
    """
    prefix = INDENT * indent
    timeout_desc = f"{render_value(node.timeout_seconds)}s" if node.timeout_seconds is not None else "none"
    if node.action_id in ("File.WaitForFile.Created", "File.WaitForFile.Deleted") and node.timeout_seconds is None:
        # design/dsl_format_findings.md 知見69(実機確認済み): `File.WaitForFile.Created`は
        # `IfFile.Exists`と同じ存在チェック(`pad_action_lib.file_actions.if_file_exists()`)を
        # 無期限ポーリングするだけ——pywinautoのセレクタは不要。
        # `File.WaitForFile.Deleted`は知見136(`ActionSelectorBase`一括列挙の監査で発見)で
        # 追加した兄弟セレクタ——`FileCreatedSelector`/`FileDeletedSelector`はいずれも
        # `WaitForFileAction`の`WaitFor`を切り替えるだけの同一構造とVM上で確認済みのため、
        # `Created`と同じ無期限ポーリングパターンの単純な否定で結線した。
        path = node.params.get("File")
        if isinstance(path, str):
            negate = "not " if node.action_id == "File.WaitForFile.Created" else ""
            return [
                f"{prefix}while {negate}file_actions.if_file_exists({render_value(path)}):",
                f"{prefix}{INDENT}time.sleep(0.05)",
            ]
    target = _WAIT_ACTION_TARGETS.get(node.action_id)
    if target is not None:
        param_name, method, wait_for = target
        element = node.params.get(param_name)
        if isinstance(element, UiElementRef):
            selector_expr = _build_pywinauto_selector_expr(element.path, ctx)
            if selector_expr is not None:
                if node.timeout_seconds is not None:
                    timeout = render_value(node.timeout_seconds)
                    return [f"{prefix}{selector_expr}.{method}({wait_for!r}, timeout={timeout})"]
                condition_expr = _WAIT_CRITERIA_EXPR[wait_for].format(sel=selector_expr)
                loop_condition = condition_expr if method == "wait_not" else f"not {condition_expr}"
                return [
                    f"{prefix}while {loop_condition}:",
                    f"{prefix}{INDENT}time.sleep(0.05)",
                ]
    return [
        f"{prefix}# TODO: map PAD wait action: {node.action_id} "
        f"(timeout: {timeout_desc}){_ui_element_hint(node, ctx)}"
    ]
