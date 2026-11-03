"""`UIAutomation.Click.Click`(UI要素クリック)のcodegen。"""
from __future__ import annotations

from ...pad_dsl import ActionRecord, EnumRef, UiElementRef
from ..context import CodegenContext
from ..render import INDENT
from ..selectors import _build_pywinauto_selector_expr


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    prefix = INDENT * indent
    if node.action_id == "UIAutomation.Click.Click":
        # design/dsl_format_findings.md 知見56で、`_build_pywinauto_selector_expr()`が
        # 組み立てるセレクタ式自体は実機(Notepad/Calculatorの実ウィンドウ)で対象要素を
        # 一意に特定できると確認済み。これまでは知見38の方針(セレクタがDSLから直接
        # 取得できない)を理由に、この確証済みの式をTODOコメント中の「提案」止まりにしていたが、
        # 知見56がその制約自体を解消した(リポジトリ経由でセレクタが実際に得られる)ため、
        # 以下の条件を全て満たす場合——(1)セレクタが実機で解決できる、(2)実機で確認済みの
        # パラメータの組み合わせ(ClickType: LeftClick・MousePositionRelativeToElement:
        # MiddleCenter・OffsetX/OffsetY: 0、知見38のDSLキャプチャ全件で確認済みの唯一の組み合わせ)
        # である——に限り、`.click_input()`(`pad_ui_helpers.py`でG1/G2実機検証済みの
        # pywinautoクリック方式)を使った実コードを生成する。それ以外のクリック種別・
        # 位置基準・オフセット(未検証)やセレクタが解決できない場合は、従来通り安全な
        # TODO+ヒントのままにする。
        element = node.params.get("Element")
        if (
            isinstance(element, UiElementRef)
            and node.params.get("ClickType") == EnumRef("UIAutomation.ClickType.LeftClick")
            and node.params.get("MousePositionRelativeToElement")
            == EnumRef("UIAutomation.RectangleEdgePoint.MiddleCenter")
            and node.params.get("OffsetX") == 0
            and node.params.get("OffsetY") == 0
        ):
            selector_expr = _build_pywinauto_selector_expr(element.path, ctx)
            if selector_expr is not None:
                return [f"{prefix}{selector_expr}.click_input()"]
    return None
