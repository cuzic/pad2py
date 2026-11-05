"""`UIAutomation.Click.Click`(UI要素クリック)のcodegen。"""
from __future__ import annotations

from ...pad_dsl import ActionRecord, EnumRef, UiElementRef
from ..context import CodegenContext
from ..render import INDENT
from ..selectors import _build_pywinauto_selector_expr, _is_start_button_element


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
            if _is_start_button_element(element.path, ctx):
                # design/dsl_format_findings.md 知見44・docs-local(Robin.Engine.dll再調査、
                # 知見59〜のVariableTrailer調査の副産物)で、この「Start Button」は
                # Attributes空の特殊タグ`:startbutton`だと確定済み——通常のUIAセレクタが
                # 組み立てられないため、Windows自体の既知の仕組み(Winキー押下でスタート
                # メニューの開閉をトグル)に対応付ける。
                return [f"{prefix}pyautogui.press('win')"]
            selector_expr = _build_pywinauto_selector_expr(element.path, ctx)
            if selector_expr is not None:
                return [f"{prefix}{selector_expr}.click_input()"]
    if node.action_id in ("UIAutomation.GetWindow.Get", "UIAutomation.GetWindow.GetUseTimeout"):
        # design/dsl_format_findings.md 知見57で実機確認済み(`.GetUseTimeout`)・
        # 知見117でdecompileにより確認済み(`.Get`——`UseTimeout: False`固定の兄弟
        # セレクタで、`Timeout`パラメータ自体が存在しない以外は同一)。`Control`パラメータは
        # `UIAutomation.Click.Click`と同じ`UiElementRef`で、知見56の`_build_pywinauto_
        # selector_expr()`がそのまま使える。「window instance」出力変数は、知見57で
        # 確認した通りPAD側では単なる変数名(`VarRef`)として他のアクションに渡されるだけ
        # なので、Python側でも`Desktop(backend="uia").window(...)`の戻り値(pywinautoの
        # WindowSpecification)をそのまま代入するだけで特別な結線は不要。
        #
        # `BringWindowToFront: True`時の正確な意味論(`.set_focus()`相当か等)は知見57で
        # 明記した通り実機未検証のため、これが確認できた`False`(省略時含む)の場合に限る。
        # `Timeout`パラメータ(`.GetUseTimeout`のみ)の正確な意味論(待機ポーリングの有無等)
        # も実機未検証のため、生成コードには一切反映しない(値を無視するだけで、架空の
        # 待機処理は追加しない)。
        element = node.params.get("Control")
        bring_to_front = node.params.get("BringWindowToFront", False)
        window_var = node.output_vars.get("WindowInstance")
        if isinstance(element, UiElementRef) and bring_to_front is False and window_var:
            selector_expr = _build_pywinauto_selector_expr(element.path, ctx)
            if selector_expr is not None:
                return [f"{prefix}{window_var} = {selector_expr}"]
    if node.action_id == "UIAutomation.GetWindow.GetForegroundWindow":
        # design/dsl_format_findings.md 知見117(decompile+実機確認済み):
        # `UIAutomation.Actions.dll`を逆コンパイルし、`GetWindow`アクションには
        # `Control`(UI要素参照)を使わない第3のセレクタ`GetForegroundWindow`
        # (`GetWindowMode.ForegroundWindow`)が存在すると確認した——`WindowTitle`/
        # `WindowInstance`の2つの出力のみを持ち、入力のUI要素参照は一切無い。
        # `win32gui.GetForegroundWindow()`(既存の依存関係pywin32)でHWNDを取得し、
        # `Desktop(backend="uia").window(handle=...)`でラップする方式が実機で
        # 正しく現在のフォアグラウンドウィンドウを返すことをVM上の実venvで確認した。
        window_var = node.output_vars.get("WindowInstance")
        title_var = node.output_vars.get("WindowTitle")
        if window_var:
            lines = [f'{prefix}{window_var} = Desktop(backend="uia").window(handle=win32gui.GetForegroundWindow())']
            if title_var:
                lines.append(f"{prefix}{title_var} = {window_var}.window_text()")
            return lines
    return None
