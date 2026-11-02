"""UIAツリーのダンプ(検証項目 A1/A2/A3/A7/A8)。

design/control_dump_tech_selection.md の「UIツリー走査」技術選定(pywinauto, uiaバックエンド)
に対応する実装。design/schemas/ui_tree_snapshot.schema.json の UIElementNode 構造に
準拠したdictを返す。
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def _safe(getter: Callable[[], T]) -> T | None:
    try:
        return getter()
    except Exception:
        return None


def _process_name(pid: int | None) -> str | None:
    if not pid:
        return None
    try:
        import psutil

        return psutil.Process(pid).name()
    except Exception:
        return None


def stable_element_id(automation_id: str | None, control_type: str, path: tuple[int, ...]) -> str:
    """AutomationId+階層パスから決定的な安定IDを生成する(検証項目 A7/A8)。

    同一の静的UIを複数回キャプチャしても同じIDになることを意図している。
    AutomationIdが無い要素は階層パス(兄弟インデックスの連なり)のみでIDが決まるため、
    要素の並び順が変わらない限り再現性がある。
    """
    key = f"{automation_id or ''}|{control_type}|{'.'.join(map(str, path))}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def dump_uia_tree(window: Any, max_depth: int = 25) -> dict[str, Any]:
    """pywinauto(uiaバックエンド)でウィンドウ配下のUIAツリーを再帰的にダンプする。

    `window` は pywinauto の WindowSpecification または UIAWrapper を想定する。
    戻り値は ui_tree_snapshot.schema.json の UIElementNode 構造に準拠する。
    """

    def walk(elem: Any, path: tuple[int, ...], depth: int) -> dict[str, Any]:
        info = _safe(lambda: elem.element_info)
        control_type = (_safe(lambda: info.control_type) if info else None) or "Unknown"
        automation_id = _safe(lambda: info.automation_id) if info else None
        rect = _safe(lambda: info.rectangle) if info else None
        bounding_rect = (
            [rect.left, rect.top, rect.right, rect.bottom] if rect is not None else None
        )
        pid = _safe(lambda: info.process_id) if info else None

        node: dict[str, Any] = {
            "element_id": stable_element_id(automation_id, control_type, path),
            "name": _safe(lambda: info.name) if info else None,
            "automation_id": automation_id,
            "control_type": control_type,
            "class_name": _safe(lambda: info.class_name) if info else None,
            "framework_id": _safe(lambda: info.framework_id) if info else None,
            "bounding_rect": bounding_rect,
            "is_enabled": _safe(lambda: elem.is_enabled()),
            "is_visible": _safe(lambda: elem.is_visible()),
            "process_name": _process_name(pid),
            "children": [],
        }

        if depth < max_depth:
            children = _safe(lambda: list(elem.children())) or []
            for idx, child in enumerate(children):
                node["children"].append(walk(child, path + (idx,), depth + 1))

        return node

    return walk(window, (0,), 0)


def flatten_element_ids(node: dict[str, Any]) -> list[str]:
    ids = [node["element_id"]]
    for child in node["children"]:
        ids.extend(flatten_element_ids(child))
    return ids


def flatten_control_types(node: dict[str, Any]) -> list[str]:
    types = [node["control_type"]]
    for child in node["children"]:
        types.extend(flatten_control_types(child))
    return types


def find_first_with_automation_id(node: dict[str, Any]) -> dict[str, Any] | None:
    if node.get("automation_id"):
        return node
    for child in node["children"]:
        found = find_first_with_automation_id(child)
        if found:
            return found
    return None
