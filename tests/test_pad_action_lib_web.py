"""`pad_action_lib.web_actions`の単体テスト(`httpx.MockTransport`で実ネットワークを使わない)。"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from dump_daemon.pad_action_lib import web_actions as web


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_download_from_web_get_returns_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, text="hello")

    result = web.download_from_web("http://example.test/", client=_client(handler))
    assert result == "hello"


def test_download_from_web_post_sends_parameters_as_form_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.read() == b"a=1"
        return httpx.Response(200, text="ok")

    web.download_from_web(
        "http://example.test/", method="Post", parameters={"a": "1"}, client=_client(handler)
    )


def test_download_from_web_to_file_writes_bytes(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"binary-data")

    dest = tmp_path / "out.bin"
    result = web.download_from_web(
        "http://example.test/",
        save_response="ToFile",
        destination_path=str(dest),
        client=_client(handler),
    )
    assert result is None
    assert dest.read_bytes() == b"binary-data"


def test_download_from_web_to_file_missing_directory_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x")

    with pytest.raises(web.DirectoryDoesNotExistError):
        web.download_from_web(
            "http://example.test/",
            save_response="ToFile",
            destination_path="/nonexistent/dir/out.bin",
            client=_client(handler),
        )


def test_download_from_web_connection_error_wraps() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(web.DownloadFromWebError):
        web.download_from_web("http://example.test/", client=_client(handler))


def test_invoke_web_service_default_content_type_is_xml_not_json() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        return httpx.Response(200, text="<a/>", headers={"X-Test": "1"})

    result = web.invoke_web_service("http://example.test/", client=_client(handler))
    assert captured["headers"]["accept"] == "application/xml"
    assert captured["headers"]["content-type"] == "application/xml"
    assert result.response == "<a/>"
    assert result.status_code == 200
    assert "x-test: 1" in result.response_headers


def test_invoke_web_service_does_not_raise_on_error_status_by_default() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    result = web.invoke_web_service("http://example.test/", client=_client(handler))
    assert result.status_code == 404
    assert result.response == "not found"


def test_invoke_web_service_raises_on_error_status_when_requested() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="oops")

    with pytest.raises(web.InvokeWebServiceError):
        web.invoke_web_service(
            "http://example.test/", fail_on_error_status=True, client=_client(handler)
        )


def test_invoke_web_service_parses_custom_headers() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        return httpx.Response(200, text="ok")

    web.invoke_web_service(
        "http://example.test/",
        custom_headers="X-Custom: value\nX-Other: 42",
        client=_client(handler),
    )
    assert captured["headers"]["x-custom"] == "value"
    assert captured["headers"]["x-other"] == "42"


def test_invoke_web_service_invalid_custom_header_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    with pytest.raises(web.InvalidCustomHeaderError):
        web.invoke_web_service(
            "http://example.test/", custom_headers="not a header line", client=_client(handler)
        )


def test_invoke_soap_service_posts_with_text_xml_content_type() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["headers"] = request.headers
        captured["body"] = request.read()
        return httpx.Response(200, text="<soap/>")

    result = web.invoke_soap_service(
        "http://example.test/soap", request_body="<Envelope/>", client=_client(handler)
    )
    assert captured["method"] == "POST"
    assert captured["headers"]["content-type"] == "text/xml"
    assert captured["body"] == b"<Envelope/>"
    assert result.response == "<soap/>"
