"""mss を使った高速スクリーンショット取得(検証項目 B1/B2)。

design/control_dump_tech_selection.md の技術選定に対応する実装。
pyautogui.screenshot() よりオーバーヘッドが小さく、高頻度キャプチャに向く。
"""
from __future__ import annotations

from pathlib import Path


def capture_region(save_path: Path, region: tuple[int, int, int, int] | None = None) -> Path:
    """画面(または指定領域)をPNGとして保存する。

    region は (left, top, right, bottom)。None の場合はプライマリモニタ全体を撮る。
    """
    import mss
    import mss.tools

    with mss.mss() as sct:
        if region is None:
            monitor = sct.monitors[1]
        else:
            left, top, right, bottom = region
            monitor = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        shot = sct.grab(monitor)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        mss.tools.to_png(shot.rgb, shot.size, output=str(save_path))
    return save_path
