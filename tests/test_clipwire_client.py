"""clipwire_client のCLIXML剥離・PNGデコードロジックの単体テスト(ネットワーク不要)。"""
from __future__ import annotations

import base64

import pytest

from dump_daemon.clipwire_client import ExecResult

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_extract_base64_payload_strips_clixml_wrapper() -> None:
    b64 = base64.b64encode(TINY_PNG).decode("ascii")
    raw = (
        "#< CLIXML\r\n"
        + b64
        + '<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">'
        "<Obj S=\"progress\"></Obj></Objs>"
    )
    result = ExecResult(status_code=200, exit_code="0", job_state="completed", raw_text=raw)
    assert result.extract_base64_payload() == b64


def test_extract_png_roundtrips_real_png_bytes() -> None:
    b64 = base64.b64encode(TINY_PNG).decode("ascii")
    raw = "#< CLIXML\r\n" + b64
    result = ExecResult(status_code=200, exit_code="0", job_state="completed", raw_text=raw)
    assert result.extract_png() == TINY_PNG


def test_extract_png_rejects_non_png_data() -> None:
    not_png = base64.b64encode(b"not a png").decode("ascii")
    result = ExecResult(status_code=200, exit_code="0", job_state="completed", raw_text=not_png)
    with pytest.raises(ValueError):
        result.extract_png()


def test_extract_base64_payload_without_clixml_prefix() -> None:
    b64 = base64.b64encode(TINY_PNG).decode("ascii")
    result = ExecResult(status_code=200, exit_code="0", job_state="completed", raw_text=b64)
    assert result.extract_base64_payload() == b64
