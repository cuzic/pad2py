"""B1/B2: GitHub Actions windows-latest ランナーに対話的デスクトップセッションが
存在し、mssでの画面キャプチャが空/黒画像にならないかの検証。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows専用")


def test_full_screen_capture_is_not_blank(tmp_path: Path) -> None:
    from dump_daemon.screenshot import capture_region

    out = capture_region(tmp_path / "full.png")
    assert out.exists()
    assert out.stat().st_size > 1000, "ファイルサイズが極端に小さい(空画像の可能性)"

    from PIL import Image, ImageStat

    img = Image.open(out).convert("L")
    stat = ImageStat.Stat(img)
    assert stat.stddev[0] > 0, (
        "画面全体が単色(対話的デスクトップセッションが存在しない/キャプチャ失敗の可能性)"
    )


def test_region_capture_matches_requested_size(tmp_path: Path) -> None:
    from dump_daemon.screenshot import capture_region

    region = (0, 0, 200, 150)
    out = capture_region(tmp_path / "region.png", region=region)

    from PIL import Image

    img = Image.open(out)
    assert img.size == (200, 150)
