"""UI要素セレクタではなく画面上の画像一致で判定する`UIAutomation.IfImage`系アクションのロジック層。

design/dsl_format_findings.md 知見58・206で実機確認済みの`UIAutomation.IfImage.ExistsOnScreen`
(`FindAllImages: False`・単一画像・`SearchAlgorithm: Legacy`の組み合わせ)のみ対応する。
PAD自身の画像照合アルゴリズム(Tolerance値の正確な意味論・Legacy/Advancedアルゴリズムの
違い)はブラックボックスのため、ここでの実装は**正確な再現ではなく近似**であることを
明記する(知見184・197のCSV変換近似と同じ、「でっち上げるよりはっきり近似と明記する」方針)。
"""
from __future__ import annotations

from .errors import PadActionError


class ImageMatchingUnavailableError(PadActionError):
    pass


def image_exists_on_screen(image_path: str, tolerance: int = 10) -> bool:
    """画面全体から`image_path`のPNG画像を探し、見つかれば`True`を返す。

    `pyautogui.locateOnScreen()`に委譲する——PADのTolerance(知見206のダイアログ説明文
    「basicアルゴリズムの推奨値は10、advancedは4」より、0以上の整数で小さいほど厳密と
    推測される)を、pyautoguiの`confidence`(0.0-1.0、大きいほど厳密)へ
    `confidence = 1 - tolerance / 100`という単純な線形近似で変換する。**この変換式は
    PAD自身の画像照合アルゴリズムとの厳密な対応が実機確認されていない近似**であり、
    Tolerance値を変えたときの実際の一致/不一致の閾値がPAD実機と完全に一致する保証は無い
    (design/dsl_format_findings.md 知見206参照)。`pyautogui`は生成スクリプトの実行環境に
    別途インストールが必要(`dump_daemon`自体の依存関係には含まれない——知見38以来の
    方針通り、生成先のpywinauto/pyautoguiスクリプトが使うランタイム依存)。
    """
    try:
        import pyautogui
    except ImportError as exc:
        raise ImageMatchingUnavailableError(
            "pyautogui is required for UIAutomation.IfImage.ExistsOnScreen; install it "
            "in the generated script's environment (optionally with opencv-python for "
            "the confidence-based partial match used here)."
        ) from exc

    confidence = max(0.0, min(1.0, 1 - tolerance / 100))
    location = pyautogui.locateOnScreen(image_path, confidence=confidence)
    return location is not None
