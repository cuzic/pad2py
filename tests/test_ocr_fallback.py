"""B3: pytesseract OCRフォールバック(Name属性が取れない要素向け)の検証。

tesseractバイナリ自体はpipでは入らないため、CI環境に無い場合はその旨を
記録してスキップする。
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows専用")


def test_tesseract_binary_availability() -> None:
    path = shutil.which("tesseract")
    if path is None:
        pytest.skip("tesseractバイナリがランナー上のPATHに見つからなかった")
    print(f"[B3] tesseract found at: {path}")
    assert path


def test_ocr_extracts_typed_text_from_screenshot(notepad_window, tmp_path: Path) -> None:
    tesseract_path = shutil.which("tesseract")
    if tesseract_path is None:
        pytest.skip("tesseractバイナリがランナー上のPATHに見つからなかった(OCR実行不可)")

    import pytesseract
    from PIL import Image

    pytesseract.pytesseract.tesseract_cmd = tesseract_path

    notepad_window.set_focus()
    notepad_window.type_keys("HELLO PAD2PY", with_spaces=True)
    time.sleep(0.5)

    from dump_daemon.screenshot import capture_region

    rect = notepad_window.rectangle()
    shot_path = capture_region(
        tmp_path / "ocr_target.png",
        region=(rect.left, rect.top, rect.right, rect.bottom),
    )

    text = pytesseract.image_to_string(Image.open(shot_path)).upper()
    print(f"[B3] OCR extracted text: {text!r}")
    assert "HELLO" in text or "PAD2PY" in text, (
        f"OCRで入力文字列を認識できなかった(抽出結果: {text!r})"
    )
