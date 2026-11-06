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
    # 知見144: `DownloadedFile`出力として使えるよう、保存先パスをそのまま返す
    # (ZipFiles/PDF結合等と同じ「呼び出し側が指定した値をそのまま返す」パターン)。
    assert result == str(dest)
    assert dest.read_bytes() == b"binary-data"


def test_download_from_web_to_folder_derives_filename_from_content_disposition(tmp_path: Path) -> None:
    # 知見152(decompileソース直読み): `WebActions.GetDownloadFilePath()`はContent-
    # Dispositionの`filename=`を最優先する。
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"report-bytes",
            headers={"Content-Disposition": 'attachment; filename="report.pdf"'},
        )

    result = web.download_from_web(
        "http://example.test/download",
        save_response="ToFile",
        destination_folder=str(tmp_path),
        client=_client(handler),
    )
    dest = tmp_path / "report.pdf"
    assert result == str(dest)
    assert dest.read_bytes() == b"report-bytes"


def test_download_from_web_to_folder_derives_filename_from_url_when_no_content_disposition(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x")

    result = web.download_from_web(
        "http://example.test/files/data.csv",
        save_response="ToFile",
        destination_folder=str(tmp_path),
        client=_client(handler),
    )
    assert result == str(tmp_path / "data.csv")


def test_download_from_web_to_folder_root_path_falls_back_to_host_html(tmp_path: Path) -> None:
    # 知見152: URLパスがルート(`/`)の場合はホスト名+`.html`になる
    # (`WebActions.GetDownloadFilePath()`のdecompile確認通り)。
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html/>")

    result = web.download_from_web(
        "http://example.test/",
        save_response="ToFile",
        destination_folder=str(tmp_path),
        client=_client(handler),
    )
    assert result == str(tmp_path / "example.test.html")


def test_download_from_web_to_folder_sanitizes_invalid_characters(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"x", headers={"Content-Disposition": 'attachment; filename="a:b?c.txt"'}
        )

    result = web.download_from_web(
        "http://example.test/",
        save_response="ToFile",
        destination_folder=str(tmp_path),
        client=_client(handler),
    )
    assert result == str(tmp_path / "a_b_c.txt")


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


def test_invoke_web_service_save_response_to_file_writes_bytes_and_sets_downloaded_file(tmp_path: Path) -> None:
    # design/dsl_format_findings.md 知見150: `InvokeWebServiceSaveToFileSelector`の
    # 兄弟セレクタ向けに`save_response`/`destination_path`を新規追加した——
    # `InvokeWebServiceResult.downloaded_file`フィールド自体は元から存在していたが
    # 設定されていなかった(知見144の`download_from_web()`と同じパターン)。
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"binary-data")

    dest = tmp_path / "out.bin"
    result = web.invoke_web_service(
        "http://example.test/",
        save_response="ToFile",
        destination_path=str(dest),
        client=_client(handler),
    )
    assert result.downloaded_file == str(dest)
    assert dest.read_bytes() == b"binary-data"


def test_invoke_web_service_save_response_to_folder_derives_filename(tmp_path: Path) -> None:
    # 知見152: `InvokeWebService*SaveToFolder*`系は`download_from_web()`の
    # `destination_folder`と同じ`_get_download_file_path()`を再利用する。
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"data",
            headers={"Content-Disposition": 'attachment; filename="report.pdf"'},
        )

    result = web.invoke_web_service(
        "http://example.test/download",
        save_response="ToFile",
        destination_folder=str(tmp_path),
        client=_client(handler),
    )
    dest = tmp_path / "report.pdf"
    assert result.downloaded_file == str(dest)
    assert dest.read_bytes() == b"data"


def test_invoke_web_service_upload_attachments_sends_multipart_with_file_contents(tmp_path: Path) -> None:
    # design/dsl_format_findings.md 知見152(decompileソース直読み): `UploadAttachments`
    # は`WebActions.FormulateWebRequest()`のmultipart/form-data構築をそのまま再現する
    # ——境界(`boundary`)付きのContent-Typeで上書きされ、各添付ファイルは
    # `NAME`/`ATTACHMENT`列のDataTableから読み込まれる。
    attachment = tmp_path / "hello.txt"
    attachment.write_bytes(b"hello world")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["content_type"] = request.headers["content-type"]
        captured["body"] = request.read()
        return httpx.Response(200, text="ok")

    web.invoke_web_service(
        "http://example.test/upload",
        method="Post",
        upload_attachments=True,
        attachments=[{"NAME": "file1", "ATTACHMENT": str(attachment)}],
        upload_type="FilePath",
        client=_client(handler),
    )
    assert captured["content_type"].startswith("multipart/form-data; boundary=")
    body = captured["body"]
    assert b'Content-Disposition: form-data; name="file1"; filename="hello.txt"' in body
    assert b"Content-Type: application/octet-stream" in body
    assert b"hello world" in body


def test_invoke_web_service_upload_attachments_empty_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    with pytest.raises(web.EmptyAttachmentsError):
        web.invoke_web_service(
            "http://example.test/upload",
            method="Post",
            upload_attachments=True,
            attachments=[],
            client=_client(handler),
        )


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


def test_download_from_web_sends_user_agent_header() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        return httpx.Response(200, text="ok")

    web.download_from_web("http://example.test/", user_agent="MyAgent/1.0", client=_client(handler))
    assert captured["headers"]["user-agent"] == "MyAgent/1.0"


def test_invoke_web_service_sends_user_agent_header() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        return httpx.Response(200, text="ok")

    web.invoke_web_service("http://example.test/", user_agent="MyAgent/1.0", client=_client(handler))
    assert captured["headers"]["user-agent"] == "MyAgent/1.0"


def test_invoke_soap_service_sends_user_agent_header() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        return httpx.Response(200, text="ok")

    web.invoke_soap_service("http://example.test/", user_agent="MyAgent/1.0", client=_client(handler))
    assert captured["headers"]["user-agent"] == "MyAgent/1.0"


def test_invoke_web_service_passes_follow_redirection_to_new_client(monkeypatch) -> None:
    # design/dsl_format_findings.md 知見93関連: knowledge 93以前はhttpxの既定
    # follow_redirects=Falseのまま、実機の既定True と食い違っていた。clientを
    # 自前で構築する経路(client未指定時)にfollow_redirection引数が実際に渡る
    # ことを、httpx.Clientのコンストラクタ引数を捕捉して確認する。
    captured = {}
    real_client = httpx.Client

    class _SpyClient(real_client):
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)
            super().__init__(*args, **kwargs, transport=httpx.MockTransport(lambda r: httpx.Response(200)))

    monkeypatch.setattr(web.httpx, "Client", _SpyClient)
    web.invoke_web_service("http://example.test/", follow_redirection=False)
    assert captured["follow_redirects"] is False


def test_invoke_soap_service_passes_trim_request_body() -> None:
    # 知見94の追補: invoke_soap_service()はinvoke_web_service()の薄いラッパーだが、
    # fail_on_error_status/trim_request_body/accept_untrusted_certificatesを実機
    # キャプチャ済みの値にかかわらず常に既定値のまま呼び出していた(codegen側も
    # これらを読み取っていなかった)——現在は明示的に渡せる。
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read()
        return httpx.Response(200, text="<soap/>")

    web.invoke_soap_service(
        "http://example.test/soap",
        request_body="  <Envelope/>  ",
        trim_request_body=False,
        client=_client(handler),
    )
    assert captured["body"] == b"  <Envelope/>  "


def test_invoke_soap_service_passes_fail_on_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="<soap/>")

    with pytest.raises(web.InvokeWebServiceError):
        web.invoke_soap_service(
            "http://example.test/soap",
            request_body="<Envelope/>",
            fail_on_error_status=True,
            client=_client(handler),
        )


def test_invoke_web_service_encodes_request_body_before_trimming() -> None:
    # design/dsl_format_findings.md 知見96(decompile確認済み): EncodeRequestBody:True
    # はHttpUtility.UrlEncode相当(application/x-www-form-urlencoded、空白は+)を
    # TrimRequestBodyより先に適用する。
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read()
        return httpx.Response(200, text="ok")

    web.invoke_web_service(
        "http://example.test/",
        request_body="a b&c",
        encode_request_body=True,
        client=_client(handler),
    )
    assert captured["body"] == b"a+b%26c"


def test_invoke_web_service_does_not_encode_request_body_by_default() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read()
        return httpx.Response(200, text="ok")

    web.invoke_web_service(
        "http://example.test/", request_body="a b&c", client=_client(handler)
    )
    assert captured["body"] == b"a b&c"
